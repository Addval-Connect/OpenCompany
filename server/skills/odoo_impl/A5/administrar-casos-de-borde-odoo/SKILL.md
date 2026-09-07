---
name: administrar-casos-de-borde-odoo
description: >-
  Qué hacer con un rechazo de Odoo que no es un error de dato: clasificar el mensaje, decidir si se
  corrige, se escala o se detiene, y recuperar el estado tras un lote fallido. Úsala solo cuando la
  carga o el QA devuelven algo que el runbook de A5 no cubre.
allowed-tools: odoo_jsonrpc file_read file_modify sandboxed_python javascript_code
metadata:
  agente: A5
  tipo: MIX
  prioridad: P1
  depende_de: carga-a-odoo-y-verifica
  siguiente_agente: COORD
  icon: "🩹"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Casos de borde de la carga

A5 ya validó estructura, formatos, catálogos y referencias antes de escribir. Un rechazo que llega
igual es una de tres cosas: una regla de negocio que solo Odoo conoce, un estado de la instancia que
cambió, o un defecto de diseño aguas arriba. Ninguna se arregla reintentando.

**Regla que gobierna esta skill:** un reintento ciego con el mismo payload gasta iteraciones y no
cambia el resultado. Antes de cualquier segundo intento, tiene que haber cambiado algo — el payload, el
estado de la instancia, o una decisión humana.

**La otra mitad de la regla: un caso de borde no termina la etapa.** Vienes desde el bucle de carga de
`carga-a-odoo-y-verifica` y **vuelves a él**. Un rechazo que necesita criterio humano se convierte en
un pendiente que se **acumula**, no en un `return` inmediato: apartas las filas o difieres el archivo,
anotas el pendiente, y sigues con el resto del plan. El control se devuelve **una vez**, al cerrar el
bucle, con todos los pendientes juntos.

Devolver el control en el primer `E400` deja 20 archivos sin cargar por dos filas, y obliga al
consultor a resolver los problemas de uno en uno: cada respuesta destapa el siguiente rechazo, y una
carga que era una corrida se convierte en diez. La única excepción son las tres cosas que hacen que
seguir sea peligroso, no solo inútil: `E500` (instancia), colisión de prefijo xmlid (paso 3) y falta de
confirmación para escribir en producción.

## Paso 1 — Clasificar el mensaje

Con el transporte legacy los errores llegan todos con la misma forma, dentro del `error` del JSON-RPC o
en `messages` de un `load`. Clasifica por el **texto**:

| El mensaje dice | Es | Acción |
|---|---|---|
| "No matching record found for external id …" | `E300` | ¿lo produce otro archivo del plan? → difiere. Si no → paso 2 |
| `Invalid field 'X' in 'Y'` / `Invalid field Y.X in condition (...)` | `E110` | **Corrígelo tú** con `fields_get` → paso 5 |
| Cabecera desconocida que `fields_get` tampoco explica | `E100` | Defecto de plantilla → paso 5 |
| `Value 'X' not found in selection field` | `E220` | **Corrígelo tú** con las claves de `fields_get` → paso 5 |
| `No matching record found for external id` y el valor **no tiene forma de xmlid** (`CPO/Stock`) | tu error | Cabecera con `/id` de más: quítale el `/id` y Odoo lo busca por nombre |
| "Object … doesn't exist" / un campo que solo trae un módulo | `E510` | Verifica el módulo, no lo instales → paso 6 |
| `The method '…' cannot be called remotely` | `E520` | No hay reintento. Acción manual → paso 6 |
| `duplicate key … "ir_model_data_module_name_uniq_index"` | tu error | Usaste `create`. Cambia a `load` → paso 3 |
| "already exists" / "duplicate key" en otro unique | `E400` o recarga | → paso 3 |
| Texto de un `_constraint` o de un `ValidationError` del modelo | `E400` | Regla de negocio → paso 4 |
| "Access Denied" / "not allowed to" | `E500` | Permisos del usuario de integración → detén |
| Timeout, 502/503, conexión cerrada | `E500` | → paso 6 |
| "uid is false" / login | `E500` | Credenciales del nodo. **No pruebes otro host.** Detén |

Si no encaja en ninguna, es `E400` con criterio funcional desconocido: pendiente `regla_negocio` con el
mensaje literal. **Nunca resumas ni parafrasees un mensaje de error de Odoo al escalarlo**: el texto
exacto es lo que un consultor funcional reconoce.

## Paso 2 — Referencia no resuelta en la carga (`E300`)

Ya pasó por A4, así que si aparece acá el mundo cambió entre la validación y la carga, o A4 resolvió
contra la instancia y el registro se borró. Verifica el xmlid concreto:

```
model="ir.model.data", method="search_read",
domain=[["module","=","adv_acme"],["name","=","payment_term_30d"]],
fields=["name","model","res_id"]
```

- **No existe y debía crearlo un archivo anterior** que se cargó OK → el archivo anterior cargó menos
  filas de las que crees. Revisa su bitácora: el `messages` de algún lote traía errores que se leyeron
  como éxito.
- **No existe y es un xmlid nativo de Odoo** (`base.*`, `uom.*`) → el módulo no está instalado o el
  nombre es distinto en esta versión. Verifica el `state` del módulo antes de decidir: instalado →
  pendiente `referencia_no_resuelta`; no instalado → `modulo_faltante`.
- **No existe y es un `l10n_*.<algo>`** (`l10n_cl.tax_vat_19_sale`) → **no concluyas módulo ausente.**
  Un registro creado por un paquete de localización lleva xmlid
  `account.<id_de_compañia>_<clave>` (acá el IVA 19% de venta es `account.1_ITAX_19` y el de compra
  `account.1_OTAX_19`), así que el `l10n_*` nunca existió. Resuélvelo con una búsqueda por dominio en
  el modelo destino (`account.tax` con `amount` y `type_tax_use`) y su `res_id` contra
  `ir.model.data`. **Match único o pendiente con la lista de candidatos**: hay siete IVAs al 19% de
  compra y elegir el de un régimen especial produce una contabilidad que cuadra y está mal. El
  procedimiento completo está en `odoo-rpc-en-opencompany` → `E300` sobre un xmlid de la localización.
- **Existe pero apunta a otro modelo** → el diseño referencia el objeto equivocado. Pendiente, no lo
  fuerces.

**No crees el registro faltante para que la referencia resuelva.** Un `res.partner` o una
`product.category` inventada para desatascar un lote deja basura que nadie sabe que existe y que va a
aparecer en un informe contable seis meses después.

## Paso 3 — "Ya existe"

**Antes de clasificar, mira el nombre de la constraint.** Si dice
`ir_model_data_module_name_uniq_index`, el error no es de los datos ni de la instancia: es **tuyo**.
Significa que cargaste con `create` y después intentaste registrar el xmlid a mano en `ir.model.data`,
y ese xmlid ya existía de una corrida anterior. `load()` no produce nunca este error — actualiza el
registro existente. Corrección: **rehaz el archivo con `method="load"`** y no vuelvas a escribir en
`ir.model.data`. No lo escales como `E400` ni lo reintentes: reintentar `create` da exactamente el mismo
mensaje. Y revisa si quedaron registros creados sin xmlid en los intentos previos (un `search_read` del
modelo cruzado contra `ir.model.data`): esos son huérfanos que `load()` no va a reconocer y que hay que
borrar antes de recargar, o quedan duplicados invisibles.

Con cualquier **otra** constraint, son dos causas con tratamiento opuesto, y confundirlas es el error
caro:

- **Es una recarga.** El xmlid ya existía de una corrida anterior. `load()` debería haber actualizado
  en vez de fallar; si falló, es un unique constraint sobre **otro** campo (un `default_code`
  duplicado, un RUT repetido). Ahí el conflicto es con un registro **distinto** que tiene el mismo
  valor natural: es `E400` y va al consultor, porque decidir cuál de los dos es el correcto es una
  decisión de negocio.
- **Colisión de prefijo.** El xmlid existe pero apunta a un registro que este proyecto no creó. Eso
  significa que el `prefijo_xmlid` colisiona con otro proyecto o con un módulo. **Detén la carga
  completa** y escala: seguir sobrescribe registros ajenos.

Distinguirlas: `read` del registro existente y compara con la fila del CSV. Si es el mismo negocio, es
recarga. Si es otro, es colisión.

## Paso 4 — Regla de negocio (`E400`)

Odoo aplicó una validación que el modelo conoce y la plantilla no. Los casos que se repiten:

- **UoM incompatible**: `uom_po_id` en otra `uom.category` que `uom_id`. Corrección de dato, va al
  consultor con el nombre de la categoría correcta.
- **Cuenta contable del tipo equivocado** para el uso (por cobrar en un campo de ingreso). Criterio
  funcional: consultor.
- **Impuesto de venta en un campo de compra** o incoherente con la posición fiscal. Consultor.
- **Moneda del documento distinta de la del diario**. Diseño: pendiente hacia A2.
- **Localización chilena**: comuna como texto libre donde va una entidad; tipo de documento sin diario;
  folios CAF ausentes. El error de folios **no parece de configuración** — el mensaje habla de
  secuencia, no de CAF. Reconócelo y dilo con esas palabras.

Tu trabajo no es decidir el criterio funcional. Es traducir el mensaje de Odoo a algo accionable: qué
fila, qué columna, qué valor, qué esperaba Odoo, y las opciones viables. Después, pendiente
`regla_negocio` **acumulado** — y vuelves al bucle.

**El resto del archivo sigue, y el resto del plan también.** Un `E400` es una falla de fila: separa las
filas rechazadas del lote, **recarga el lote sin ellas** (`load()` es transaccional: si no lo reenvías,
las 299 filas buenas tampoco entraron), marca el archivo `parcial` en `08-carga/estado-carga.json`, y
continúa con el siguiente archivo del plan. No descartes el archivo entero por dos filas, y no termines
la etapa por un archivo parcial.

## Paso 5 — Campo o cabecera que Odoo no reconoce (`E110`, y `E100` si no hay campo)

Empieza siempre igual: **`fields_get` del modelo.** Es una llamada, y decide si esto lo arreglas tú o
es un defecto aguas arriba. Sin ella no puedes distinguir "el nombre está mal" de "el campo no existe",
y son casos opuestos.

**Hay un campo que sostiene el dato (`E110`) → sigue cargando.** `load(fields, data)` recibe `fields`
construido **por ti** a partir de la cabecera del CSV, así que corriges el nombre **en el payload** y
el archivo entra. No estás editando el archivo del consultor: estás mapeando su columna al campo real.
Condiciones para hacerlo, las tres:

1. El match es **inequívoco** — un solo campo del modelo corresponde al dato de esa columna. Dos
   candidatos plausibles no es un match: es un pendiente.
2. Lo registras en `08-carga/bitacora-<modelo>.jsonl` como corrección de cabecera, con el nombre que
   venía y el que usaste. Una carga que funcionó por un mapeo silencioso es irreproducible.
3. Lo reportas igual como **observación para A3**, para que la plantilla quede corregida en el origen.
   El Coordinador re-delega; tú no editas `05-plantillas/`.

Si el dato pertenece a **otro modelo** (el caso clásico: la compañía delega en `partner_id`), escribe en
ese otro modelo y déjalo dicho. Las trampas ya vistas están en `odoo-rpc-en-opencompany` → `E110`.

**Ningún campo sostiene el dato (`E100`) → aguas arriba, y el archivo se detiene.**

- No edites la plantilla ni el archivo completado. No es tu carpeta.
- No quites la columna "para que pase". Si la columna estaba, alguien llenó datos ahí, y descartarla en
  silencio pierde información que el consultor cree entregada.
- Pendiente `campo_inexistente` **con la lista de campos que sí existen** como evidencia — es lo que
  permite responderlo sin volver a consultar la instancia. Acumúlalo y sigue con el resto del plan.

**No pruebes un segundo nombre a ojo.** Dos rechazos seguidos por campo inexistente significan que el
`fields_get` no se hizo, y cada rechazo se queda en el historial encareciendo el resto del turno.

**Valor fuera del `selection` (`E220`) — el mismo procedimiento, un paso más corto.** `fields_get` con
`attributes: ["selection"]` trae los pares clave/etiqueta; compara contra las claves y después contra
las etiquetas (con `context: {"lang": "en_US"}` si la instancia está traducida y el valor viene en
inglés). Un match único se corrige en el payload y el archivo entra. **Un código de 2-3 caracteres que
no calza exacto no se resuelve por parecido**: produce una clave plausible y equivocada que Odoo acepta
sin protestar, y eso es peor que el rechazo — es pendiente.

Y si **todas** las filas rechazan la misma columna con el mismo motivo, el defecto es de la columna:
si no es obligatoria, quítala del lote, carga el archivo sin ella y repórtala como `E220` de columna con
las claves válidas. Es la diferencia entre perder un archivo completo y perder un atributo.

## Paso 6 — Módulo ausente (`E510`), método bloqueado (`E520`) y error de instancia (`E500`)

`E510` **no es** un error de instancia, aunque comparta la familia 5xx: la instancia está sana, le falta
un módulo. Y **no lo instalas tú**: Odoo no acepta los métodos administrativos de `ir.module.module`
por RPC (`The method 'ir.module.module.get_module_info' cannot be called remotely` — eso es `E520`).
Instalar es trabajo manual de una persona en la UI. Lo tuyo es verificar y reportar:

```
model="ir.module.module", method="search_read",
domain=[["name","in",["l10n_cl","l10n_cl_edi"]]], fields=["name","state"]
```

- **Verifica al principio del bucle, no al tropezar.** Un `search_read` con todos los módulos que el
  plan necesita, en una llamada, antes del primer `load`. Descubrir el módulo ausente en la ronda 3
  desperdició tres rondas.
- `state` distinto de `installed` (incluido `to install` / `to upgrade`, que son estados a medias) →
  los archivos que dependen de ese módulo quedan `detenido` con pendiente `modulo_faltante`, con el
  nombre exacto del módulo. **El resto del plan sigue cargándose.**
- **No llames a `button_immediate_install` ni a ningún método `ir.*` administrativo.** No es cuestión
  de credenciales ni de host: la instancia no los expone. Reintentarlo gasta la iteración y ensucia el
  historial con un error que parece un fallo de la carga.
- **Cuando la persona instale el módulo, reintrospecta antes de recargar.** La introspección previa no
  conoce los campos nuevos, y usarla produce un `E110` que parece un error de diseño. Actualiza
  `02-instancia/introspeccion.json` y recarga solo los archivos que estaban `detenido`.
- Un `E520` sobre algo que **sí** podías leer (el caso típico: `get_module_info` cuando lo que
  querías era el estado) no es un bloqueo real: usa la vía de solo lectura y sigue.

### Error de instancia (`E500`)

- **Timeout o 502/503 en un lote**: el estado es **desconocido**, no fallido. `load()` es transaccional
  por lote, pero un timeout del cliente puede ocurrir con la transacción ya confirmada en el servidor.
  **Verifica antes de reintentar**: consulta `ir.model.data` por los xmlids de ese lote. Están → el
  lote entró, sigue con el siguiente. No están → reintenta ese lote. Reintentar sin verificar es como
  se duplican registros a pesar de la idempotencia, porque el segundo intento puede pegarle a un unique
  sobre otro campo y partir el archivo.
- **Un reintento, no tres.** Si el segundo intento también falla por instancia, detén la carga
  completa: la instancia no está en condiciones y seguir produce un estado a medias imposible de
  auditar.
- **Lotes más chicos** si el timeout es consistente (500 → 200 → 100). Si a 100 filas también hay
  timeout, el problema no es el tamaño.
- **Login o permisos**: no es recuperable desde acá y **no es el host**. Pendiente y control al
  Coordinador.

## Paso 7 — Reportar el estado real

Después de cualquier caso de borde, el estado tiene que quedar escrito, no en tu memoria de la
conversación:

1. Anota en `08-carga/bitacora-<modelo>.jsonl` el lote fallido con el mensaje literal de Odoo y qué
   filas quedaron fuera (en números de fila del CSV, no índices del lote).
2. Actualiza `08-carga/estado-carga.json` **antes de pasar al siguiente archivo**: `estado`,
   `intentos`, `ultimo_codigo`, `filas_apartadas`. Ese archivo es lo que permite reanudar el bucle si
   el turno se corta; dejarlo para el final es dejarlo sin escribir.
3. Si un archivo quedó a medias, dilo con los rangos exactos: "filas 2-301 cargadas, 302-412 no". Un
   "carga parcial" sin rangos obliga a reconstruir a mano qué entró.
4. `carga_completa: false` siempre que haya una fila fuera.
5. Acumula en `02-instancia/capacidades-instancia.json` lo que este caso de borde te enseñó **sobre la
   instancia**, no sobre los datos: el remapeo de cabecera del paso 5 que terminó `cargado`
   (`remapeos_confirmados`), el campo que `fields_get` no reporta (`campos_inexistentes`), la clave de
   `selection` que resolvió un `E220` junto con la lista completa de claves de ese campo
   (`valores_confirmados`), el xmlid real detrás de uno que no existía y la vía por la que lo
   encontraste — incluido "esta columna no lleva `/id`" — (`xmlids_resueltos`), la referencia que no
   existe con su causa y su dueño humano (`xmlids_inexistentes`), la llamada que devolvió
   `cannot be called remotely` (`metodos_bloqueados`), el ajuste de `res.config.settings` que
   encendiste con su valor anterior (`ajustes_aplicados`), la regla de xmlid que verificaste **con su
   evidencia y su contraejemplo** (`reglas_de_xmlid`) — una regla sin contraejemplo se sobreaplica: "todo
   `l10n_*` es sospechoso" habría rechazado `l10n_cl.it_RUT`, que sí existe —, y el tamaño de lote al
   que dejó de haber timeout (`lote_optimo`). Un remapeo que probaste y volvió a fallar no va ahí: solo lo confirmado. Es lo que
   evita que la próxima corrida gaste las mismas rondas en descubrir lo mismo.

## Nunca

- No reintentes un rechazo de negocio sin cambiar el payload.
- No devuelvas el control por un caso de borde de fila o de archivo. Apártalo, anótalo, sigue el plan, y
  entrega todos los pendientes juntos al cerrar el bucle. Solo `E500`, la colisión de prefijo xmlid y la
  falta de confirmación de producción interrumpen la carga.
- No escales un `Invalid field ...` sin el `fields_get` que lo respalde: la mitad de las veces el campo
  existe con otro nombre y la carga podía continuar.
- No intentes instalar un módulo por RPC. Verifica su `state`, escala el `modulo_faltante`, y sigue
  con los archivos que no dependen de él.
- No crees datos maestros para desatascar una referencia.
- No edites `05-plantillas/` ni `06-completadas/`.
- No parafrasees el mensaje de error de Odoo al escalarlo.
- No reintentes un timeout sin verificar primero si el lote entró.
- No reportes como completa una carga con filas fuera.
- No cambies el host ante un fallo de login.
