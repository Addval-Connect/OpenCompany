---
name: odoo-rpc-en-opencompany
description: >-
  Cómo se habla con Odoo 19 desde OpenCompany con la tool odoo_jsonrpc, incluida la carga idempotente
  con load() y la taxonomía de errores E100-E500. Lee esto antes de la primera llamada a Odoo;
  contiene la desviación deliberada respecto de la API JSON-2 y las reglas de seguridad de entorno.
allowed-tools: odoo_jsonrpc
metadata:
  agente: TODOS
  tipo: DET
  prioridad: P0
  uso: referencia_compartida
  icon: "🔌"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Odoo desde OpenCompany

## La tool, y por qué no hay URL

Toda llamada a Odoo pasa por la tool **`odoo_jsonrpc`**. El host, la base de datos, el usuario y la
API key viven **en el panel del nodo**, no en tus argumentos: el esquema que ves no tiene campo de
URL ni de credenciales. Esto no es una comodidad, es un blindaje — el nodo existe precisamente
porque un modelo conduciendo un `httpRequest` genérico *inventa* el hostname de la instancia a partir
del nombre del cliente y luego reintenta para siempre contra un host que no autentica.

Consecuencia operativa: **si una llamada falla por login, el problema NO es el host.** El mensaje lo
dice explícitamente ("do NOT retry with a different host"). Es base de datos, usuario o API key mal
configurados en el nodo: escribe un pendiente `entorno_produccion` u `otro` y devuelve el control.
Nunca "pruebes otro host".

Argumentos que sí eliges tú:

```
model        "res.partner", "product.template", "ir.model.data", …
method       search_read | read | search | search_count | create | write | unlink | fields_get | call
method_name  obligatorio cuando method="call"
domain       para search / search_read / search_count
fields       para read / search_read  — pide SIEMPRE el mínimo
ids          obligatorio para read / write / unlink
values       obligatorio para create / write
limit        ≤ 1000    offset, order
args, kwargs posicionales / nombrados cuando method="call"
```

Devuelve `{ok: true, result: …}` o `{ok: false, error: {...}}`. El esquema es cerrado
(`extra="forbid"`): un argumento inventado se rechaza antes de salir a la red.

## Desviación deliberada: transporte legacy, no JSON-2

Odoo 19 introdujo la API JSON-2 (`POST /json/2/<modelo>/<metodo>`, `Authorization: Bearer`,
`X-Odoo-Database`, códigos HTTP reales) y anunció la eliminación de `/xmlrpc`, `/xmlrpc/2` y
`/jsonrpc` **para Odoo 20**.

Nuestra tool habla el transporte antiguo: `https://<host>/jsonrpc`, handshake `common.login` →
`object.execute_kw`. Esto es una decisión consciente, no un descuido:

- Odoo 19 **sigue soportando** `/jsonrpc`; la deprecación afecta a la versión siguiente.
- El modelo de objetos es el mismo. `search_read`, `create`, `write`, `fields_get` y `load` son
  métodos del ORM, idénticos en ambos transportes. Lo que cambia es el sobre, no la carta.
- Todo lo que las referencias de este proyecto dicen sobre modelos, campos, cabeceras nativas y
  `load()` aplica sin cambios.

**Lo que sí cambia para ti:**

- Los errores no llegan como códigos HTTP semánticos, sino dentro del `error` del JSON-RPC. Un
  registro inexistente y una regla de negocio violada llegan con la misma forma; clasifícalos por el
  **texto** del mensaje según la taxonomía de abajo.
- No hay endpoint por modelo: siempre `model` + `method`.
- Cualquier método del ORM que no esté en la lista corta se alcanza con `method="call"` +
  `method_name`.

Cuando Odoo 20 retire `/jsonrpc`, el cambio es en el nodo `odooJsonRpc` (un `_rpc` nuevo), no en
estas skills.

## Carga idempotente: `load()`

`load(fields, data)` es el método del importador nativo — el mismo que usa la interfaz al importar un
CSV. Es la forma de cargar, no `create` en bucle: respeta las cabeceras `<campo>/id`, resuelve xmlids
y **actualiza** en vez de duplicar cuando el `id` ya existe.

```
odoo_jsonrpc(
  model="res.partner",
  method="load",
  fields=["id", "name", "vat", "property_account_position_id/id"],
  values=[
    ["adv_acme.partner_761234567", "ACME SpA", "76.123.456-7", "adv_acme.fiscal_pos_general"],
    ["adv_acme.partner_770001112", "Beta Ltda", "77.000.111-2", ""]
  ]
)
```

`load` es un método de primera clase del tool: `fields` es la cabecera y `values` son las filas. (La
forma antigua `method="call"` + `method_name="load"` + `args=[fields, data]` sigue funcionando, pero no
la uses: la directa valida que cada fila tenga tantos valores como cabeceras y te dice qué fila está
mal antes de tocar Odoo.)

Reglas duras:

- **`create` no es una alternativa a `load` para cargar un archivo.** `create` no registra el xmlid, así
  que la corrida siguiente no reconoce el registro y lo duplica. Y si intentas registrarlo tú
  insertando en `ir.model.data`, la segunda corrida muere con
  `duplicate key value violates unique constraint "ir_model_data_module_name_uniq_index"`, que es la
  forma en que este error se ve en la práctica: **no es un problema de datos, es haber usado `create`.**
  `create` queda para el objeto único de configuración que no lleva xmlid.

- **`"id"` debe estar entre las cabeceras.** Sin esa columna la carga duplica en cada corrida. Si no
  está, no llames: es `E100`.
- **La forma de una columna relacional la decide el valor, no el campo.** Valor `modulo.nombre`
  (`base.cl`) → cabecera `campo/id`, búsqueda por xmlid. Valor legible (`CPO/Stock`, `Insumos y
  Materiales`) → cabecera `campo` a secas, búsqueda por nombre. `/id` sobre un valor que no es xmlid
  devuelve `No matching record found for external id 'CPO/Stock'`: parece referencia faltante y es
  cabecera equivocada.
- `data` son **listas de strings**, en el mismo orden que `fields`. Celda vacía = `""`, no `null`.
- Respuesta: `{"ids": [...], "messages": [...]}`. **`messages` no vacío significa que algo falló**,
  aunque `ok` sea `true` y `ids` traiga elementos. Cada mensaje trae `type`, `message`, y a menudo
  `record` (índice de fila 0-based) y `field`. Lee siempre `messages` antes de declarar éxito.
- Un `load` con `messages` de tipo `error` **no escribió nada** de ese lote: es transaccional.
- Lotes de 200-500 filas. Más grande, un error obliga a repetir todo; más chico, multiplica las
  llamadas (y cada tool-result se queda en el historial encareciendo las iteraciones siguientes).

## Comprobaciones de lectura que se usan siempre

```
# ¿Existe este xmlid?  (evita E300 antes de cargar)
model="ir.model.data", method="search_read",
domain=[["module","=","adv_acme"],["name","=","partner_761234567"]],
fields=["module","name","model","res_id"]

# ¿Qué campos tiene realmente este modelo?  (la autoridad, no la memoria)
model="res.partner", method="fields_get", args=[[]],
kwargs={"attributes": ["type","required","selection","relation","string"]}

# ¿Qué módulos están instalados?
model="ir.module.module", method="search_read",
domain=[["state","=","installed"]], fields=["name","shortdesc","state"]

# ¿Está instalado uno en particular?  (E510 — verificar, no instalar)
model="ir.module.module", method="search_read",
domain=[["name","in",["l10n_cl","l10n_cl_edi"]]], fields=["name","state"]

# Versión de la instancia
model="ir.module.module", method="search_read",
domain=[["name","=","base"]], fields=["latest_version"]
```

## Los módulos no se instalan por RPC (`E520`)

**Odoo bloquea la invocación remota de los métodos administrativos de los modelos `ir.*`.** El
mensaje es literal y no deja lugar a interpretación:

```
"error": "Odoo error: The method 'ir.module.module.get_module_info' cannot be called remotely."
```

Lo mismo aplica a `button_immediate_install`, `button_upgrade`, `button_uninstall` y a los métodos de
`ir.model` / `ir.model.fields` que crean o alteran modelos y campos. **No es un problema de permisos
del usuario de integración y no se arregla con otra credencial ni con otro host**: la instancia no
expone esos métodos por el transporte legacy, punto.

Lo que **sí** funciona sobre `ir.*` es la lectura: `search_read`, `read`, `fields_get`. Con eso
verificas el estado de un módulo, y ahí se acaba tu alcance.

Por lo tanto: **los módulos los instala una persona, a mano, desde la UI de Odoo.** El agente
verifica y reporta; no instala, no lo intenta "por si acaso", y no interpreta el bloqueo como un
error propio que deba reintentar.

- Ver `The method '<algo>' cannot be called remotely` es `E520`: **no lo reintentes nunca**, con
  ningún argumento. Reintentar un método bloqueado gasta iteraciones con el resultado garantizado.
- Si lo que necesitabas era una lectura, hay una vía de solo lectura (arriba). Úsala.
- Si lo que necesitabas era una acción administrativa (instalar, actualizar, crear un campo), es
  trabajo humano: pendiente con el nombre exacto del módulo o del campo, y sigues con el resto del
  plan.

Corolario para la carga: la lista de módulos requeridos se **verifica al principio**, no se descubre
a la mitad. Un módulo ausente detiene los archivos que dependen de él — no la carga completa, y no la
etapa.

`fields_get` sobre los modelos del blueprint es la **única** autoridad sobre qué campos existen.
Ninguna lista de campos escrita en una referencia, incluida esta, es autoridad: todo lo marcado
`[VERIFICAR]` se confirma contra la instancia y el resultado se guarda en
`02-instancia/introspeccion.json`.

## Ajustes de la aplicación: `res.config.settings` (sí se hacen por RPC)

Media configuración de Odoo no vive en un registro sino en un **ajuste**: la contabilidad analítica,
las rutas multi-paso, las ubicaciones de almacenamiento, las unidades de medida, los lotes. Sin el
ajuste encendido, el modelo existe y el menú no aparece — y el síntoma que reporta el usuario es "no
está configurado", no un error. Esto **no** es `E520`: se hace por RPC, y es trabajo tuyo.

El patrón son dos llamadas, y las dos son necesarias:

```
# 1. leer el estado actual (no adivines si ya está encendido)
model="res.config.settings", method="default_get",
args=[["group_analytic_accounting", "group_stock_adv_location", "group_uom"]]

# 2. escribir: create con SOLO lo que cambias, y execute() para aplicarlo
model="res.config.settings", method="create",
args=[{"group_analytic_accounting": true, "group_stock_adv_location": true}]
model="res.config.settings", method="execute", args=[[<id_devuelto>]]
```

- **`create` sin `execute` no cambia nada.** El `create` solo arma el formulario en memoria; `execute`
  es lo que escribe los grupos y los `ir.config_parameter`. Un `create` que devolvió un id y ningún
  `execute` es el fallo silencioso típico: la llamada respondió OK y el ajuste sigue apagado.
- **Solo pones en el `create` los campos que cambias.** El resto lo rellena `default_get`
  internamente con el estado vigente, así que no pisas ajustes ajenos.
- **Verifica después con `default_get`,** no con el valor que enviaste.
- **`group_*` sí, `module_*` NO.** Los campos `group_<algo>` encienden un grupo: son un `write` y los
  haces tú. Los campos `module_<algo>` **instalan un módulo** cuando `execute()` corre — es
  exactamente la acción que no te corresponde (ver `E510`/`E520`), y por esta vía Odoo no te la
  bloquea, así que la barrera tienes que ponerla tú. Un `module_*` que el diseño pide es un pendiente
  `modulo_faltante` con el nombre del módulo, nunca un `True` en tu payload.
- **El cliente web cachea el menú.** Después de encender un ajuste, el menú nuevo aparece al recargar
  la página; que el usuario no lo vea al instante no significa que el ajuste no se aplicó. Compruébalo
  con `ir.ui.menu` (`search_read` por nombre, campo de grupos y `active`) antes de dudar del `execute`.
- El ajuste enciende la **capacidad**, no la configura. `group_stock_adv_location` hace visibles las
  rutas; cuántos pasos tiene cada almacén sigue siendo `stock.warehouse.reception_steps` /
  `delivery_steps`, que es una decisión del blueprint y se escribe como cualquier otro objeto
  `fuente: configuracion`.

Ajustes verificados por RPC en esta instancia: `group_analytic_accounting`,
`group_stock_multi_locations`, `group_stock_adv_location`, `group_stock_production_lot`, `group_uom`,
`group_multi_currency`.

## Economía de llamadas

Cada resultado de tool queda en el historial del agente y se re-lee en cada iteración siguiente, así
que el costo crece de forma casi cuadrática con las iteraciones. Por eso:

- **`fields` mínimo, siempre.** Un `search_read` sin `fields` trae decenas de columnas por fila y las
  arrastra por el resto del turno.
- **En bloque, no por fila.** Un `search_read` con `domain=[["name","in",[...]]]` en vez de N
  llamadas; un `load` de 300 filas en vez de 300 `create`.
- **Cachea a archivo.** Introspección y maestros van a `02-instancia/*.json` con `fileModify`; los
  pasos siguientes leen el archivo con `fileRead`, no repiten la consulta.
- `limit` explícito en toda exploración. Sin `limit`, una tabla grande inunda el contexto.

## Taxonomía de errores

Clasificación común para el validador (A4) y el cargador (A5). El código determina **quién** corrige.

| Código | Qué es | Corrige | Efecto |
|---|---|---|---|
| `E100` | Estructura del archivo: falta columna `id`, cabecera desconocida, CSV ilegible, sidecar ausente | Agente | **Detiene el archivo completo** |
| `E110` | **Campo inexistente en el modelo**: `Invalid field 'X' in 'Y'`, `Invalid field Y.X in condition (...)` | Agente, con `fields_get` | Reintenta **una** vez con el campo verificado |
| `E200` | Campo obligatorio vacío | Consultor | Fila rechazada |
| `E210` | Formato inválido: fecha, número, booleano, RUT con DV incorrecto | Consultor | Fila rechazada |
| `E220` | Valor fuera del catálogo (`selection`, `catalogos` del sidecar) | Consultor | Fila rechazada |
| `E300` | Referencia no resuelta: el xmlid de un `<campo>/id` no existe | Consultor o agente según el caso | Fila rechazada |
| `E310` | xmlid duplicado dentro del archivo | Consultor | Ambas filas rechazadas |
| `E320` | Dependencia fuera de orden: referencia a un xmlid de un archivo `NN` mayor | Agente | **Detiene el archivo completo** |
| `E400` | Regla de negocio de Odoo (constraint, validación del modelo) | Consultor con criterio funcional | Fila rechazada |
| `E500` | Error de instancia: caída, timeout, permisos, login | Agente / infraestructura | **Detiene la carga completa** |
| `E510` | **Modelo o módulo ausente**: `Object <modelo> doesn't exist`, `Model not found`, un campo que solo existe con un módulo instalado | Persona, instalando el módulo a mano | **Detiene los archivos de ese módulo** |
| `E520` | **Método no invocable remotamente**: `The method '<X>' cannot be called remotely` (típico en `ir.module.module`, `ir.model`) | Nadie por RPC — es acción manual | No se reintenta |

**Una `E100` o una `E320` detienen el archivo entero; una `E500` detiene la carga completa.** No son
fallas de fila: significan que el archivo o la instancia no están en condiciones, y seguir produce un
estado a medias imposible de auditar. Todo lo demás se reporta por fila y el archivo continúa, para
que el consultor reciba **todos** los problemas en una pasada y no de uno en uno.

**Clasifica por lo que Odoo rechaza, no por lo que a ti te parece mal.** Un dato que la instancia
aceptó no es un error, aunque contradiga una regla que tú conoces: la validación de la localización
puede estar desactivada, el módulo que la impone puede no estar instalado, o el campo puede ser libre
en esta versión. Nunca rechaces una fila con una comprobación que hiciste tú de más y que Odoo no
aplica — eso bloquea una carga correcta y es indistinguible de un error real en el informe.

## El bucle de corrección: qué reintentas tú, y cuántas veces

La carga **no es una pasada**. Es un bucle que converge: intentas, clasificas, corriges lo que te toca
y vuelves a intentar. Devolver el control ante el primer rechazo deja la configuración a medias, y el
consultor recibe un informe de un problema en vez de una base cargada.

Lo que decide el código es **quién** corrige, y por lo tanto si el reintento es tuyo o no:

| Código | ¿lo corriges tú? | Cómo | Intentos |
|---|---|---|---|
| `E110` | **sí** | `fields_get` del modelo → cabecera corregida | 1 por campo |
| `E220` | **sí**, si el valor es una etiqueta y el catálogo trae la clave | `fields_get` con `selection` → clave real | 1 por columna |
| `E300` | **sí**, si el xmlid lo produce otro archivo del plan | **difiere** el archivo y recárgalo después de su dependencia | hasta 2 rondas |
| `E320` | **sí** | reordena el plan y vuelve a intentar en su nueva posición | 1 reordenamiento |
| `E510` | no | verifica el `state` en `ir.module.module`; si falta, los archivos de ese módulo quedan `detenido` con pendiente `modulo_faltante` para instalación manual. **El resto del plan sigue** | 0 |
| `E520` | no | método bloqueado por la instancia; no hay reintento posible por RPC | 0 |
| `E100` | no | el archivo no está en condiciones; queda `detenido` | 0 |
| `E200` `E210` `E400` | no | quita **esas filas** del lote, recarga el resto, y repórtalas | ver abajo |
| `E500` | no | detén la carga completa y devuelve el control | 0 |

**Un lote con filas rechazadas se recarga sin ellas.** `load()` es transaccional: una fila mala tira
el lote entero, así que las 299 filas correctas tampoco entraron. Quitar las filas rechazadas y
reenviar el lote **no** es "reintentar igual" — es la única forma de que el rechazo de una fila no se
convierta en la pérdida del archivo. Anota las filas apartadas con su número de fila del CSV y sigue.

**Regla de progreso (la condición de salida).** Cada ronda del bucle cuenta cuántos archivos pasaron
a `cargado` y cuántas filas nuevas entraron. Una ronda completa **con progreso cero** termina el
bucle: lo que queda no depende de otro archivo, depende de una decisión del consultor. Sin esta regla
el bucle reintenta para siempre los mismos rechazos, que es exactamente el fallo que la tool
`odoo_jsonrpc` existe para evitar.

**Tope duro: 5 rondas.** Si al cabo de 5 rondas queda algo pendiente, reporta el estado y devuelve el
control con los pendientes. Cinco rondas alcanzan para cualquier grafo de dependencias real; más
rondas significan que estás girando sobre un error que no es de orden.

Dos reintentos con el mismo código y el mismo argumento son un bucle, no una corrección. Antes de
reintentar, tiene que haber cambiado algo verificable: un campo confirmado con `fields_get`, una
dependencia cargada, unas filas apartadas, un orden distinto. Si no cambió nada, no reintentes. Y un
módulo ausente **no** cambia dentro del bucle: instalarlo es trabajo de una persona (`E520`), así que
los archivos que dependen de él salen del bucle en la primera ronda en vez de reintentarse en las
cinco.

### `E110`: el campo no existe — no adivines otro nombre

`Invalid field 'tz' in 'res.company'` o `Invalid field res.currency.code in condition ('code','=','US')`
significan lo mismo: **el campo que escribiste no existe en ese modelo.** No es un problema de dato,
de permisos ni de instancia; es el modelo real contradiciendo tu memoria del modelo.

Es el único error que corriges tú sin devolver el control, y tiene un procedimiento fijo:

1. `fields_get` **sobre ese modelo**, filtrando por lo que buscabas:

   ```
   model="res.company", method="fields_get", args=[[]],
   kwargs={"attributes": ["type","required","relation","string"]}
   ```

2. Elige el campo que existe. Si el dato pertenece a otro modelo, escribe **en ese otro modelo**.
3. Reintenta **una sola vez** con el campo verificado. Guarda el hallazgo en
   `02-instancia/introspeccion.json` para no volver a pagar la llamada.
4. Si tras el `fields_get` no hay ningún campo que sostenga el dato, es un pendiente `otro`: el
   diseño pide algo que el modelo no tiene. Devuelve el control; no lo fuerces a un campo parecido.

**Un segundo nombre adivinado es el error.** Tres llamadas seguidas rechazadas por campo inexistente
no son mala suerte, son `fields_get` sin hacer — y cada rechazo queda en el historial encareciendo el
resto del turno.

Trampas ya observadas en este proyecto (verifícalas igual con `fields_get`, no las memorices):

| Querías | Dónde NO está | Dónde está |
|---|---|---|
| Código ISO de una moneda (`USD`) | `res.currency.code` | `res.currency.name` — y el valor es `USD`, no `US` |
| Zona horaria de la compañía | `res.company.tz` | `res.partner.tz` / `res.users.tz` (vía `company.partner_id`) |
| Grupos de un usuario | `res.users.groups_id` | `res.users.group_ids` |
| Compañía de una cuenta contable | `account.account.company_id` | `account.account.company_ids` (m2m en 19) |
| Tipo de contribuyente chileno | `res.partner.l10n_cl_taxpayer_type` | `res.partner.l10n_cl_sii_taxpayer_type` |
| Condición de pago de un contacto | `res.partner.payment_term_id` | `property_payment_term_id` / `property_supplier_payment_term_id` |
| Etiquetas de un contacto | `res.partner.category_ids` | `res.partner.category_id` (sí, m2m en singular) |
| Aplicabilidad de un plan analítico | `account.analytic.plan.applicability` | `default_applicability` |
| UdM de compra de un producto | `product.template.uom_po_id` | eliminado en 19: `uom_id` / `uom_ids` |
| Modelo de depreciación | modelo `account.asset.model` | modelo `account.asset` con `state='model'` |
| Cuentas de entrada/salida de stock | `product.category.property_stock_account_input_categ_id` | eliminadas en 19: queda `property_stock_valuation_account_id` |

### `E300` sobre un xmlid de la localización — el módulo no es el dueño

`No matching record found for external id 'l10n_cl.tax_vat_19_sale'` con `l10n_cl` **instalado** no es
un módulo ausente y no es `E510`. Los registros que crea un paquete de localización al aplicarse —
cuentas, impuestos, diarios, posiciones fiscales — **no llevan el xmlid del módulo**: llevan
`account.<id_de_compañia>_<clave_de_la_plantilla>`. En esta instancia el IVA 19% de venta es
`account.1_ITAX_19` y el de compra `account.1_OTAX_19`; `l10n_cl.tax_vat_19_sale` no existe ni va a
existir. Buscarlo en `ir.module.module` confirma que `l10n_cl` está instalado y deja el problema
exactamente donde estaba.

La resolución es una **búsqueda semántica en el modelo destino**, no una variante del nombre:

```
# 1. el registro, por lo que lo define funcionalmente
model="account.tax", method="search_read",
domain=[["amount","=",19],["type_tax_use","=","sale"]], fields=["name","amount","type_tax_use"]

# 2. su xmlid, por res_id
model="ir.model.data", method="search_read",
domain=[["model","=","account.tax"],["res_id","=",<id>]], fields=["module","name"]
```

**El match tiene que ser único.** Si el dominio devuelve un candidato, lo usas y lo anotas en
`xmlids_resueltos` con la vía. Si devuelve varios, **es un pendiente `referencia_no_resuelta` con la
lista de candidatos**, no el primero de la lista: el IVA 19% de compra convive con seis IVAs de
regímenes especiales (activo fijo, uso común, no recuperable, supermercado), y elegir el equivocado
produce una contabilidad que cuadra y está mal. Reporta nombre y xmlid de cada candidato — es lo que
permite al consultor responder en un minuto.

Dos consecuencias más de aplicar un paquete fiscal:

- **Odoo rechaza usar o editar un impuesto cuyo `country_id` no coincide con el
  `account_fiscal_country_id` de la compañía.** Un impuesto "19%" preexistente de antes de la
  localización queda inutilizable; el que sirve es el del paquete.
- **El paquete solo se aplica con la contabilidad virgen** (cero `account.move`). Aplicarlo es una
  decisión humana y no es reversible sin restaurar la base: nunca lo apliques tú sin confirmación
  explícita, y jamás en producción. La llamada, para cuando esa confirmación existe, es
  `account.chart.template` / `try_loading` con `args=[[], "<codigo>", <company_id>]` y
  `kwargs={"install_demo": false}` — el primer posicional se consume como `ids`, así que pasar
  `args=["cl", 1]` falla con `missing 1 required positional argument: 'company'`.

### `Value 'X' not found in selection field` — clave contra etiqueta

Un `selection` tiene clave (invariable, inglesa) y etiqueta (traducida). El CSV suele traer la
etiqueta, o una clave de una versión anterior. `fields_get` con `attributes: ["selection"]` da los
pares; compara primero contra las claves normalizadas y después contra las etiquetas. Si la instancia
está en español y el valor está en inglés, pide las etiquetas en inglés:
`kwargs={"attributes": ["selection"], "context": {"lang": "en_US"}}`.

**El match tiene que ser único, y un código de 2-3 caracteres no se resuelve por parecido.** `AT` no
es candidato de nada: es un pendiente. Una clave plausible y equivocada la escribe Odoo sin protestar,
y eso es peor que el rechazo.

Cambios de `selection` ya verificados en Odoo 19:

| Modelo.campo | Claves reales | Nota |
|---|---|---|
| `product.template.type` | `consu`, `service`, `combo` | `product` ya no existe: almacenable = `consu` + `is_storable` |
| `product.category.property_valuation` | `periodic`, `real_time` | `manual` → `periodic` |
| `stock.warehouse.delivery_steps` | `ship_only`, `pick_ship`, `pick_pack_ship` | `one_step` → `ship_only`; `reception_steps` **sí** usa `one_step` |
| `res.partner.type` | `contact`, `invoice`, `delivery`, `other` | no confundir con `l10n_cl_sii_taxpayer_type` (`1`-`4`) |
| `account.asset.method_period` | `1`, `12` | son strings |

Y dos validaciones de escritura que rechazan la fila completa, no la columna:

- **Código de cuenta**: `account.account.code` solo acepta alfanumérico y puntos. `1-1-2-05` se
  rechaza; el candidato obvio es `1.1.2.05`, pero cambiar el plan de cuentas del cliente es decisión
  del consultor: repórtalo con el candidato.
- **RUT**: con `l10n_cl` instalado, el dígito verificador se valida al escribir. Un DV incorrecto
  rechaza la fila entera aunque el resto esté perfecto, y el mensaje habla de formato aunque el
  formato esté bien.

El patrón detrás de las dos: en Odoo la compañía delega sus datos de contacto en `partner_id`, y
varios "códigos" viven en `name`. Cuando un campo obvio no existe, pregúntate **qué modelo es el
dueño real del dato** antes de probar otro nombre.

Formato de un error reportado (una fila de `07-validacion/errores-<modelo>.csv`):

```csv
codigo,archivo,fila,columna,valor,mensaje,corrige
E210,20_res.partner.csv,14,vat,76.123.456-8,"DV incorrecto: para 76.123.456 el DV es 7",consultor
E300,31_product.template.csv,7,categ_id/id,adv_acme.categ_insumo,"xmlid no existe; ¿adv_acme.categ_insumos?",consultor
```

Un mensaje de error sin `archivo`+`fila`+`columna` es inútil para quien corrige. Y cuando el valor
erróneo se parece a uno válido, **sugiere el candidato**: es la diferencia entre una corrección de un
minuto y una de media hora.

## Seguridad y entornos

- La API key vive en el parámetro `api_key` del nodo (marcado secreto) o en la variable de entorno
  `ODOO_API_KEY`. **Nunca** en el repositorio, en `blueprint.yaml`, en un artefacto del proyecto, ni
  en un `console`/informe. Si la ves en un archivo, es un hallazgo de seguridad: repórtalo como
  alerta.
- Usuario **dedicado de integración**, nunca la cuenta personal de un consultor: la trazabilidad de
  la carga y la rotación de la clave dependen de eso.
- El acceso a la API externa solo está disponible en planes Custom de Odoo. Si `common.login`
  responde negativo con credenciales correctas, esa es la causa probable.
- **QA y ensayos de carga van contra `staging`, jamás contra producción.** Ramas de Odoo.sh:
  `production`, `staging`, `development`. Staging está neutralizado (correo saliente, crons y pagos
  deshabilitados), que es exactamente lo que hace seguro repetir la carga.
- **Antes de la primera escritura en producción**, confirma explícitamente base de datos y rama, y
  déjalo registrado. Sin esa confirmación, escribir en producción es un pendiente
  `entorno_produccion`, no una decisión del agente.
- El ensayo completo en staging incluye **reconstruir staging desde cero y repetir la carga entera**.
  Es el paso que todos se saltan y el único que detecta las dependencias ocultas entre archivos: una
  carga que funciona sobre una base ya ensuciada por intentos previos no prueba nada.
