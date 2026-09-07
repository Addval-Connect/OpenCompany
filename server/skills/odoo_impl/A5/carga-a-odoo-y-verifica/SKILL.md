---
name: carga-a-odoo-y-verifica
description: >-
  Runbook completo del Agente A5: aplica la configuración por RPC, carga los archivos validados con
  load() en orden de dependencias, verifica con read-back, y ejecuta los casos de QA de cada flujo.
  ÚNICO punto de escritura del sistema. Ejecuta los pasos en orden.
allowed-tools: odoo_jsonrpc file_read file_modify fs_search sandboxed_python javascript_code
metadata:
  agente: A5
  tipo: MIX
  prioridad: P0
  depende_de: valida-archivos-completados
  siguiente_agente: COORD
  icon: "🚀"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Cargar a Odoo y verificar (runbook A5)

**Único punto de escritura del sistema.** Ningún otro agente escribe en Odoo. Lo que hagas acá es lo
único que no se deshace con un archivo corregido: deshacer una carga significa restaurar la base de
datos.

Lee `odoo-rpc-en-opencompany` (transporte, `load()`, taxonomía, **el bucle de corrección**, reglas de
entorno),
`scripts-verificados-de-carga-odoo` (**obligatorio antes del paso 2c** — trae el script ya probado que
convierte el CSV en `fields` + `data` aplicando los remapeos y xmlids ya aprendidos; cópialo, no lo
escribas),
`sandbox-de-codigo-en-opencompany` (qué sandbox puede abrir un
archivo y cuál no), `orden-de-carga-odoo`, `convencion-ids-externos` y
`contrato-implementacion-odoo`. De `flujos-de-referencia`, abre solo los flujos del proyecto: sus
"casos canónicos de QA" son la base del paso 5. Skill adicional solo si hay rechazos que no son de
dato: `administrar-casos-de-borde-odoo`.

Escribes en `08-carga/` y `09-qa/`, en ninguna otra carpeta. La única excepción es
`02-instancia/capacidades-instancia.json`, a cuyas listas **agregas** entradas sin borrar las
existentes (`resultado_ultimo_ensayo` es la única clave que se sobrescribe, porque describe *esta*
corrida). Nunca toques `introspeccion.json`.

## Precondiciones (verifícalas; no las asumas)

1. `07-validacion/` existe y dice qué archivos pasaron. **Solo cargas esos.** Un archivo
   `CON_ERRORES` o `DETENIDO` no se carga ni parcialmente. La lista es la que trae el resultado de A4,
   con el nombre de clave que A4 haya usado (`cargables`, `archivos_ok`, `resumen_archivos_ok`…): lo
   que importa es el veredicto por archivo, no el nombre del campo. Si el resultado dice que se puede
   avanzar y trae la lista de archivos válidos, tienes tu lista — no te detengas por una clave que se
   llama distinto. Si **no** hay veredicto por archivo en ninguna forma, entonces sí es un pendiente.
2. **Entorno confirmado.** `file_read` del `blueprint.yaml` → `entorno_objetivo`. Si es `production` y
   la misión no trae confirmación explícita de **base de datos y rama**, no escribas: pendiente
   `entorno_produccion` y devuelve el control. "Adelante" no es una confirmación de entorno.
3. Cero pendientes con `respuesta: null` que afecten a los modelos a cargar.

## Paso 1 — Aplicar la configuración (`fuente: configuracion`)

Del `blueprint.yaml`, los objetos `fuente: configuracion` los escribes tú directo, en el orden `nn`.
Pocos registros, valores decididos en el diseño.

**Los módulos se verifican primero — y no los instalas tú.** Un modelo o un campo que solo existe con
un módulo instalado no es un error de dato: es `E510`. **Instalar módulos por RPC no es posible en esta
instancia**: Odoo rechaza los métodos administrativos de `ir.module.module` con
`The method '<X>' cannot be called remotely` (`E520`), y eso no se arregla con otra credencial ni con
otro host. Los módulos los instala una persona desde la UI de Odoo.

Lo tuyo, antes de la primera escritura y en **una** llamada: `search_read` de `ir.module.module` con
`domain=[["name","in",[...los del blueprint...]]]` y `fields=["name","state"]`. Los que no estén
`installed` (incluidos `to install` / `to upgrade`, que son estados a medias) generan un pendiente
`modulo_faltante` con el nombre exacto, y **los archivos que dependen de ellos quedan `detenido`; el
resto del plan se carga igual**. No intentes la instalación "por si acaso": el intento gasta la
iteración con resultado garantizado y deja en el historial un error que parece un fallo de la carga.

Cuando la persona instale el módulo, **la introspección anterior quedó vieja**: un `fields_get`
cacheado antes de instalar `l10n_cl` no conoce sus campos, y usarlo produce un `E110` que parece un
error de diseño. Vuelve a introspectar los modelos afectados, actualiza
`02-instancia/introspeccion.json`, y recarga solo los archivos `detenido`.

**Antes de escribir un campo que no viste en la introspección, `fields_get` ese modelo.** Este paso
es donde se inventan nombres de campo: el diseño dice "zona horaria de la compañía" o "moneda USD" y
el nombre plausible no existe (`res.company.tz`, `res.currency.code` — ninguno de los dos es real).
Un rechazo `Invalid field 'X' in 'Y'` es **`E110`**: lo corriges tú con `fields_get` y reintentas
**una** vez con el campo verificado; el procedimiento completo y las trampas conocidas están en
`odoo-rpc-en-opencompany`. Nunca pruebes un segundo nombre a ojo, y nunca escribas el dato en un
campo "parecido" para que la llamada pase.

**Los ajustes de la aplicación son parte de esta etapa, y sí se hacen por RPC.** Antes de escribir los
objetos, enciende lo que el blueprint necesita en `res.config.settings`: sin
`group_analytic_accounting` la contabilidad analítica no aparece en el menú aunque los planes existan;
sin `group_stock_adv_location` no hay rutas; sin `group_stock_multi_locations` no hay ubicaciones; sin
`group_uom` no hay unidades de medida. Un modelo que existe con el menú oculto le llega al usuario como
"no está configurado", no como un error, así que no lo descubres por un rechazo: lo lees con
`default_get` al principio del paso. El patrón (`default_get` → `create` con solo lo que cambias →
**`execute()`**, que es lo que aplica) y la línea que no cruzas (`group_*` sí, `module_*` **no**,
porque instala un módulo) están en `odoo-rpc-en-opencompany` → `res.config.settings`. Anota cada ajuste
que encendiste en `08-carga/bitacora-configuracion.jsonl` y en `capacidades-instancia.json`: un ajuste
aplicado sin registro es indistinguible de uno que ya venía puesto.

**Antes de crear, busca.** Los objetos de configuración son justo los que la localización suele haber
creado ya — el plan de cuentas de `l10n_cl` es el caso clásico, y duplicarlo deja dos planes
convivientes que nadie limpia después:

```
model="account.account", method="search_read",
domain=[["code","in",["1101","1102"]]], fields=["code","name"], limit=200
```

Existe → `write` con lo que el diseño cambia, y registra como actualizado. No existe → créalo **con su
xmlid**, vía `load()` (no `create`), para que quede referenciable por los archivos posteriores. Un
registro de configuración creado con `create` no tiene xmlid, y cualquier `<campo>/id` que lo apunte
va a fallar con `E300` en el archivo siguiente.

Registra cada objeto en `08-carga/bitacora-<modelo>.jsonl` igual que una carga.

## Paso 2 — Construir el plan de carga

**No supongas el orden por el nombre del archivo.** El prefijo `NN` es el orden de dependencias
*cuando existe*; en varios proyectos los archivos llegan sin prefijo, y entonces el orden alfabético
es orden arbitrario y produce `E300` en cascada. Deriva el plan, y déjalo escrito antes de la primera
escritura.

1. `fs_search` sobre `06-completadas/` para la lista real de archivos. Crúzala con `cargables` de
   `07-validacion`: **solo entra al plan lo que está en ambas.**
2. **Un mismo modelo en dos archivos es una colisión, no dos cargas.** Si `res.partner.csv` y
   `res_partner.csv` (variantes con punto y con guion bajo del mismo modelo) traen xmlids comunes con
   columnas distintas, cargar los dos deja el registro con los valores del último y pierde en silencio
   las columnas que solo traía el otro. Compara los conjuntos de `id`: si se solapan, carga **un
   solo** archivo — el que trae el superconjunto de filas y columnas — y reporta la colisión como
   alerta con los dos nombres. No los fusiones tú.
3. **Orden.** Primero el `nn` del `blueprint.yaml`, que es la autoridad. Para lo que no esté ahí,
   derívalo de las referencias: un archivo que trae una columna `<campo>/id` con xmlids del prefijo
   del proyecto depende del archivo que **produce** esos xmlids. Orden topológico: primero los que no
   referencian a nadie. Un ciclo (A referencia a B y B a A) no se resuelve reordenando: carga A sin la
   columna que apunta a B, carga B, y vuelve a cargar A completo — `load()` actualiza, no duplica.
4. Un solo `sandboxed_python` te da el grafo entero sin arrastrar los CSVs al historial: abre cada
   ruta de la lista, y devuelve por archivo solo `{modelo, campos, ids, refs}` — `refs` son los
   valores no vacíos de las columnas `<campo>/id`. El parser está en
   `sandbox-de-codigo-en-opencompany`; los `fields` completos los devuelve el mismo parser cuando
   cargues ese archivo.

Escribe el plan en `08-carga/plan-carga.json`: orden, archivo, modelo, filas, dependencias, y las
colisiones detectadas. Es lo que hace auditable la carga y lo que te permite reanudarla.

## Paso 2b — El bucle de carga (esto no es una pasada)

Mantén el estado en `08-carga/estado-carga.json`, un objeto por archivo:

```json
{"archivo":"res_partner.csv","modelo":"res.partner","estado":"cargado",
 "intentos":2,"ultimo_codigo":"E110","filas_ok":8,"filas_apartadas":[],"lotes":[1]}
```

`estado` es uno de `pendiente` | `cargado` | `diferido` | `parcial` | `detenido`.

**Al empezar, lee `estado-carga.json` si existe.** Un archivo `cargado` no se vuelve a cargar. Que
`load()` sea idempotente hace que reanudar sea seguro; que sea seguro no lo hace gratis: cada recarga
son llamadas y contexto.

**Lee también `02-instancia/capacidades-instancia.json`** (lo crea A1, y es chico). Es lo que esta
instancia ya te enseñó, y te ahorra rondas enteras:

- `metodos_bloqueados` — no vuelvas a llamar nada de esa lista. Es un `E520` garantizado.
- `remapeos_confirmados` — cabeceras cuyo campo real ya se verificó con `fields_get`. Aplícalos al
  construir `fields` **sin volver a introspeccionar**, y anótalos igual en la bitácora de esta corrida.
- `campos_inexistentes` — ya se escaló; no lo re-escales ni pruebes un nombre nuevo a ojo.
- `valores_confirmados` — claves de `selection` ya verificadas por modelo y campo, con el valor del CSV
  que se tradujo a cada una. Aplícalas directamente en el payload; te ahorran el `fields_get` con
  `attributes: ["selection"]` de esa columna.
- `xmlids_resueltos` — el xmlid real detrás de uno que no existía, y **cómo** se resolvió (por `code`,
  por nombre, o enlazando un registro que ya existía). Incluye los casos en que la respuesta es "esta
  columna no lleva `/id`".
- `xmlids_inexistentes` — referencias que no existen en esta instancia y por qué (típicamente un
  paquete de localización sin aplicar). No las vuelvas a buscar ni las trates como `E300` de dato: ya
  tienen dueño humano.
- `modulos` — el `state` de los módulos del plan en la última corrida. Sigue verificándolos con un
  `search_read` (pueden haber cambiado), pero esto te dice qué esperar.
- `ajustes_aplicados` — los ajustes de `res.config.settings` que ya se encendieron. No los vuelvas a
  aplicar a ciegas: léelos con `default_get` y enciende solo lo que falte.
- `lote_optimo` — el tamaño de lote que esta instancia aguantó sin timeout. Si está, empieza por ahí en
  vez de por 500.
- `resultado_ultimo_ensayo` — qué archivos y filas entraron la última vez y qué quedó bloqueado, con
  dueño. Es tu punto de partida: los `bloqueos_reales` que siguen sin respuesta no se reintentan.

Es memoria de **esta** instancia, no doctrina: si contradice lo que Odoo responde ahora, gana Odoo, y
corriges el archivo. Un remapeo que la instancia ya no acepta se borra, no se conserva "porque antes
funcionaba".

El bucle, hasta **5 rondas** (la mecánica completa de reintentos y la regla de progreso están en
`odoo-rpc-en-opencompany` → "El bucle de corrección"):

```
verifica los módulos del plan (un search_read)  -> los archivos de un módulo ausente: detenido
ronda = 1
mientras queden archivos en pendiente|diferido|parcial y ronda <= 5:
    progreso = 0
    por cada archivo del plan, en orden:
        si estado es cargado o detenido -> siguiente
        intenta cargarlo (los lotes de abajo)
        todo entró            -> cargado,  progreso += 1
        E110 / E220           -> corrígelo y reintenta YA, en esta misma ronda
        E300 / E320           -> diferido (su dependencia entra en esta ronda o la próxima)
        E200 / E210 / E400    -> aparta esas filas, recarga el lote sin ellas -> parcial
        E100                  -> detenido (el archivo no está en condiciones)
        E510                  -> detenido + pendiente modulo_faltante (no lo instalas tú)
        E500                  -> detén el bucle completo y devuelve el control
    si progreso == 0 -> corta el bucle: lo que queda no es un problema de orden
    ronda += 1
```

Escribe `estado-carga.json` **al final de cada archivo**, no al final del bucle. Si el turno se corta
—se agota el presupuesto de iteraciones, cae la instancia— la siguiente ejecución reanuda desde ahí en
vez de repetir la carga entera.

**En la misma escritura, acumula `02-instancia/capacidades-instancia.json`.** Es el archivo que hace
que la próxima corrida no repita tus descubrimientos, y solo sirve si lo escribes cuando el hecho
todavía está fresco:

- `metodos_bloqueados` — cada `E520` con la llamada y el mensaje literal.
- `remapeos_confirmados` — cada corrección de cabecera que resultó `cargado`, como
  `{"modelo": "...", "cabecera": "...", "campo": "...", "visto": "..."}`. Solo las que **funcionaron**:
  un remapeo que volvió a fallar no es un hecho confirmado.
- `campos_inexistentes` — los `E100` por campo que no existe, con el modelo. Evita que la próxima
  corrida los vuelva a probar.
- `valores_confirmados` — cada `E220` que resolviste, como
  `{"modelo": "...", "campo": "...", "de": "<valor del CSV>", "a": "<clave real>", "claves": [...]}`.
  Guarda la **lista completa de claves** del campo, no solo la que usaste: es lo que permite resolver el
  siguiente valor de esa misma columna sin otra llamada.
- `xmlids_resueltos` — el xmlid que no existía, el que sí, y por qué vía lo encontraste. Incluye
  explícitamente el caso "la columna no lleva `/id`", que es tu error más caro de re-descubrir.
- `xmlids_inexistentes` — la referencia ausente, la causa verificada y de quién es la acción. No la
  anotes como `remapeo`: no hay nada que remapear.
- `modulos` — `installed` / `uninstalled` según el `search_read` de módulos del plan.
- `ajustes_aplicados` — cada ajuste de `res.config.settings` que encendiste, con su valor anterior:
  `{"campo": "group_uom", "de": false, "a": true, "visto": "..."}`. El valor anterior es lo que permite
  distinguir "lo encendí yo" de "ya venía puesto", que es justo la pregunta que aparece cuando alguien
  reporta que un menú no está.
- `lote_optimo` — el tamaño de lote con el que esta instancia terminó cargando sin timeout, si tuviste
  que bajarlo.
- `resultado_ultimo_ensayo` — el cierre de la corrida: `archivos_completos` / `archivos_totales`,
  `filas_cargadas` / `filas_totales`, si verificaste idempotencia, y `bloqueos_reales` con `codigo`,
  `que` y `corrige`. Sobrescribe la entrada anterior — de esta clave solo importa la última.

Solo hechos verificados contra esta instancia en esta corrida. No escribas criterio funcional ahí (eso
es un pendiente) ni conviertas un caso único en regla: si algo de acá aplica a varios proyectos, quien
lo promueve a una skill compartida es una persona.

Al cerrar el bucle, registra en la bitácora **cuántas rondas** hiciste y qué quedó sin cargar. Un
bucle que terminó por progreso cero y uno que terminó porque todo entró se reportan distinto: el
primero tiene pendientes para el consultor, el segundo no.

## Paso 2c — Cargar un archivo

Por archivo:

1. `file_read` del `.meta.json` (es chico: catálogos, referencias, obligatorios). **El CSV no lo leas
   con `file_read` para convertirlo** — ver el punto 2.
2. **Convierte el CSV a `fields` + `data` con el script S1 de `scripts-verificados-de-carga-odoo`**
   (`sandboxed_python` + `capabilities: ["workspace_read"]`, el único sandbox que puede abrir el
   archivo). **Copia el script y cambia solo sus tres primeras líneas** (`ARCHIVO`, `MODELO`,
   `PREFIJO`). No lo reescribas ni escribas uno propio: el que está en esa skill se verificó contra el
   intérprete real, y volver a derivar la mecánica es de donde salió la mayor parte del costo de las
   corridas anteriores.

   El nombre del archivo es el que devolvió `fs_search`, tal cual — con punto o con guion bajo, con
   prefijo `NN` o sin él. Un nombre "normalizado" a mano es un `file not found` y dos iteraciones
   perdidas.

   Requisito previo, una vez por modelo: `fields_get` guardado en
   `05-plantillas/campos-<modelo>.json`. El script lo lee de ahí en vez de llamar a Odoo, así que la
   introspección se paga una vez y no una vez por lote.

   **`javascript_code` no sirve para este paso**: su sandbox no tiene `require` ni `fs`, y su
   `input_data` no recibe archivos. `require('fs')` / `require('csv-parse')` fallan con
   `require is not defined`; si ves ese error, no cambies de módulo — cambiaste de tool demasiado
   tarde. `python_code` tampoco: prohíbe `import` y no tiene `csv`.
3. **Lee la salida del script antes de llamar a Odoo.** Trae `fields` y `data` listos, y además cuatro
   cosas que son tu trabajo, no del script:

   - `avisos` — cada uno es un rechazo que Odoo va a producir. Los `E210` (DV de RUT, código de cuenta
     con guiones) y `E200` (obligatorio vacío) son **defecto del consultor**: no los arregles tú.
   - `filas_a_apartar_antes_de_enviar` — quítalas de `data` **antes** del `load`. Enviarlas gasta una
     llamada y, como `load()` es transaccional, tumba el lote entero.
   - `descartes_columna` — una columna que no existe en el modelo. Va al informe: descartarla en
     silencio pierde datos que el consultor cree entregados.
   - `xmlids_por_resolver_antes_de_enviar` — un `l10n_*` que apunta a un modelo que crea la plantilla
     contable, así que **no existe** aunque tenga forma válida. Es tuyo: resuélvelo por dominio antes de
     llamar a `load`, o el lote se cae con un `E300` que parece módulo ausente y no lo es.
   - `remapeos` — lo que el script aplicó solo. Va a la bitácora, para que la carga sea reproducible.

   Un aviso `E220` **con lista de claves** es el script negándose a adivinar, no un fallo: ahí decides
   tú, y si no hay match único es pendiente. Y `"id"` tiene que estar en `fields`; si no está, no
   llames — es `E100` y el archivo no debió llegar a esta lista.

   Las tres reglas que el script ya implementa (la columna del xmlid se llama `id`; **la forma de una
   columna relacional la decide el VALOR y no el campo** — `/id` solo si todos los valores no vacíos
   tienen forma `modulo.nombre`; una columna sin campo se remapea o se descarta) están explicadas en
   `scripts-verificados-de-carga-odoo`. Consúltalas cuando un rechazo no cuadre, no para reimplementarlas.
4. Trocea en lotes de **200 a 500 filas**. Más grande, un error obliga a repetir todo el archivo; más
   chico, multiplica las llamadas y cada tool-result se queda en el historial encareciendo cada
   iteración siguiente. Trocea **dentro** del `sandboxed_python` (`data[0:300]`) y devuelve solo el
   lote que vas a cargar: así el archivo completo nunca entra al historial.
5. Por lote:

```
odoo_jsonrpc(model="res.partner",
             method="load",
             fields=["id","name","vat","property_payment_term_id/id"],
             values=[["adv_acme.partner_761234567","ACME SpA","76.123.456-7","adv_acme.payment_term_30d"],
                     ["adv_acme.partner_770001112","Beta Ltda","77.000.111-2",""]])
```

**`load()` es idempotente por diseño**: el `id` existente se actualiza en vez de duplicar. Esa es toda
la razón por la que la columna `id` es obligatoria y por la que este paso se puede repetir.

**Cargar un archivo con `create` no es una variante aceptable, es un defecto.** `create` no registra el
xmlid: la corrida siguiente no reconoce lo que cargaste y lo duplica, y si intentas registrarlo tú
insertando en `ir.model.data` la segunda corrida muere con
`duplicate key … "ir_model_data_module_name_uniq_index"`. Si ves ese mensaje, no es un error de datos —
es la señal de que estás usando `create` donde va `load`.

**La lectura de la respuesta es el paso que se hace mal.** `load` devuelve
`{"ids": [...], "messages": [...]}`, y `ok: true` con `ids` poblado **no significa éxito**:

- `messages` vacío → el lote entró completo.
- `messages` con `type: "error"` → **el lote no escribió nada** (es transaccional). Cada mensaje trae
  `record` (índice de fila 0-based **dentro del lote**) y a menudo `field`. Traduce el índice a número
  de fila del CSV antes de reportarlo, o el consultor busca en la fila equivocada.
- `messages` con `type: "warning"` → entró, pero anótalo en la bitácora.

Un lote con error: **no lo reintentes igual, pero tampoco lo abandones.** Clasifica el mensaje con la
taxonomía y aplica lo que corresponde del bucle:

- `E110` / `E220` son tuyos: `fields_get` del modelo, corriges la cabecera o el valor, y reenvías el
  mismo lote **una** vez, ya corregido.
- `E510` no es tuyo: el archivo queda `detenido` con pendiente `modulo_faltante` (el módulo lo instala
  una persona) y **sigues con el siguiente archivo del plan**. `E520` es la instancia diciéndote que ese
  método no se invoca por RPC: no lo reintentes.
- `E200` / `E210` / `E400` son del consultor, pero el lote no se pierde: **quita esas filas y reenvía
  el resto.** `load()` es transaccional, así que las otras 299 filas tampoco entraron. Las filas
  apartadas van a `estado-carga.json` con su número de fila del CSV y su código, y el archivo queda
  `parcial`. Un `E400` que no entiendes → `administrar-casos-de-borde-odoo`.
- `E300` / `E320`: el archivo queda `diferido`. No apartes filas — vuelve a intentarlo entero cuando su
  dependencia esté cargada.
- `E500` → detén la carga completa y devuelve el control.

Traduce siempre el `record` del mensaje (índice 0-based **dentro del lote**) a número de fila del CSV
antes de apartar o reportar: apartar la fila equivocada carga datos malos y rechaza datos buenos. **Esa
aritmética no la hagas a ojo**: pega los `messages` en el script S2 de
`scripts-verificados-de-carga-odoo` y te devuelve las filas del CSV, y además decide lo que se confunde
seguido — si todas las filas rechazan la misma columna no obligatoria, el defecto es de la columna y se
recarga el archivo **completo** sin ella, en vez de perder el archivo fila por fila.

### `Value 'X' not found in selection field` — resuelve la clave, o descarta la columna

Un `selection` de Odoo tiene **clave** (invariable, en inglés) y **etiqueta** (traducida al idioma de
la instancia). El CSV casi siempre trae la etiqueta, o una clave de una versión anterior. `fields_get`
con `attributes: ["selection"]` te da los pares, y ahí se resuelve:

1. Compara contra las **claves** primero, normalizando (minúsculas, `_` y espacios equivalentes).
2. Después contra las **etiquetas**. Si la instancia está en español y el valor del CSV está en
   inglés, pide las etiquetas en inglés: `kwargs={"context": {"lang": "en_US"}}`. Sin eso, el match
   por etiqueta no encuentra nada aunque exista.
3. `one_step` → `ship_only` sale de esa comparación: la etiqueta de `ship_only` habla de "1 step".
   Las claves de entrada y salida **no son simétricas** — `reception_steps` sí tiene `one_step`.

**Un match tiene que ser único, y un código corto no se resuelve por parecido.** Un valor de 2 o 3
caracteres (`AT`, `US`, `01`) que no calza exacto con ninguna clave ni etiqueta es un pendiente, no un
candidato: el parecido con una etiqueta cualquiera produce una clave plausible y equivocada, que Odoo
acepta sin protestar. Eso es peor que el rechazo.

**Columna intoxicada: si todas las filas rechazan la misma columna con el mismo motivo, el problema es
la columna, no las filas.** El caso visto: el CSV trae la columna `type` de `res.partner` llena con el
valor del tipo de contribuyente (`1`), que no pertenece a ese `selection`. Descartar 11 filas buenas
por una columna mal llenada es la decisión equivocada. Si la columna **no es obligatoria** (`fields_get`
lo dice), quítala del lote, carga el archivo sin ella, y repórtala como `E220` de columna con el valor
literal y la lista de claves válidas. Nunca hagas esto con una columna obligatoria, y nunca inventes un
valor "razonable" para rellenarla.

### El objeto que ya existe no se carga: se enlaza

Los singletons de configuración (la compañía) y los registros que Odoo **crea solo** (la ubicación de
stock de un almacén, el diario que nace con una cuenta) ya existen sin tu xmlid. Cargarlos con `load()`
crea un duplicado — una segunda compañía es de las cosas más caras de deshacer en Odoo.

- Compañía: `search_read` de `res.company`. Si ya está, enlaza tu xmlid al registro existente con un
  `ir.model.data.create` (`{module, name, model, res_id}`) y **después** usa `load()` con ese `id`:
  actualiza la que hay en vez de crear otra.
- Hijo autocreado: lee el campo que lo apunta (`stock.warehouse.lot_stock_id`) y enlaza el xmlid a ese
  `res_id`. Alternativa sin enlazar: referenciarlo por nombre, con la cabecera sin `/id`.

**Este es el único caso en que escribir `ir.model.data` a mano es correcto**, y es correcto porque el
registro ya existe. Escribirlo después de un `create` para "registrar" lo que acabas de crear es el
antipatrón que produce el `duplicate key … "ir_model_data_module_name_uniq_index"`.

Bitácora, una línea JSON por lote en `08-carga/bitacora-<modelo>.jsonl`:

```json
{"archivo":"20_res.partner.csv","lote":1,"filas":300,"desde":2,"hasta":301,"ids":[1042,1043],"creados":298,"actualizados":2,"messages":[]}
```

Con `desde`/`hasta` en números de fila del CSV, la bitácora es auditable contra el archivo original.

## Paso 3 — Verificar con read-back (obligatorio)

Un `load` sin errores no prueba que los registros quedaron como querías: prueba que Odoo aceptó la
escritura. Por archivo cargado, una consulta en bloque:

```
model="ir.model.data", method="search_read",
domain=[["module","=","adv_acme"],["model","=","res.partner"]],
fields=["name","res_id"], limit=1000
```

Compara el conteo y el conjunto de `name` contra los `id` del CSV. Diferencia → repórtala; no la
expliques como "probablemente el filtro". Con más de 1000 registros, pagina con `offset`.

Para los modelos con campos calculados que importan (impuestos en un producto, cuentas en un diario),
un `read` de muestra de 3-5 registros con `fields` mínimos. No de todos: el objetivo es detectar un
mapeo sistemáticamente mal, y eso se ve en tres filas.

## Paso 4 — Escribir el resumen de carga

`08-carga/resumen-carga.md`: por modelo, filas del archivo, creados, actualizados, rango de xmlids, y
errores con su código. Referencia por **xmlid**, no por id numérico: el id numérico de staging no
significa nada en producción, y este resumen es lo que se lee al replicar la carga.

**`actualizados > 0` en una primera carga no es normal.** Significa que esos xmlids ya existían: o es
una recarga, o el prefijo colisiona con otro proyecto. Dilo explícitamente en el resumen; no lo
reportes como éxito silencioso.

## Paso 5 — Ejecutar el QA

Genera `09-qa/casos.yaml` desde los casos canónicos de la referencia de cada flujo, cruzados con los
`criterios_aceptacion` de `00-entrada/historias.csv`. Un caso por criterio verificable.

```yaml
- id: QA-007
  hu: [HU-014]
  flujo: ventas
  descripcion: Cotización a cliente mayorista aplica lista de precios
  pasos:
    - modelo: sale.order
      metodo: create
      valores: {partner_id_xmlid: adv_acme.partner_761234567, order_line: [...]}
    - modelo: sale.order
      metodo: action_confirm
  aserciones:
    - "pricelist_id == adv_acme.pricelist_mayorista"
    - "amount_total == 119000"
    - "len(picking_ids) == 1"
```

Ejecución:

- **Solo en staging.** El QA crea documentos reales — órdenes, entregas, facturas, movimientos
  contables. Si `entorno_objetivo` es `production`, **no ejecutes el QA**: repórtalo como no ejecutado
  y por qué. Staging está neutralizado (correo saliente, crons y pagos deshabilitados) y eso es
  exactamente lo que lo hace seguro.
- Resuelve los xmlids a ids con `ir.model.data` antes de cada `create`.
- Métodos de acción (`action_confirm`, `action_post`, `button_validate`) con `method="call"` +
  `method_name` + `args=[[<id>]]`. **Muchos devuelven `False` incluso cuando hubo errores por
  registro**, así que después de cada acción **relee** el estado (`state`, y el campo que la aserción
  mira). Una acción que "no falló" no significa que hizo lo que esperabas.
- Un caso rojo no detiene el QA: sigue con los demás. Un caso rojo es configuración incompleta, y hay
  que saber cuántas y cuáles.

`09-qa/resultados-<flujo>.md` por flujo: caso, verde/rojo, aserción que falló, valor obtenido vs.
esperado. `09-qa/evidencia/` con los ids de los documentos creados, para que alguien pueda abrirlos.

Un caso rojo se reporta como **caso**, con su `id` y qué aserción falló — nunca como "hubo un problema
en ventas".

## Paso 6 — El ensayo completo (dilo, aunque no lo hayas hecho)

Una carga incremental sobre una base ya ensuciada por intentos previos **no prueba que el orden de
carga sea correcto**. El ensayo válido es reconstruir staging desde cero y repetir la carga entera; es
el paso que todos se saltan y el único que detecta las dependencias ocultas entre archivos.

No puedes reconstruir staging tú (es una operación de Odoo.sh, no de RPC). Lo que sí tienes que hacer
es **reportar si se hizo o no**. Sin ese dato, el informe de cierre se lee como "listo para
producción" y no lo es.

## Salida (un resultado al COORD)

```json
{
  "resultado_carga": {
    "rondas": 3,
    "cierre_bucle": "todo_cargado",
    "archivos_ok": 6,
    "archivos_error": 1,
    "archivos_parciales": 1,
    "registros_creados": 1689,
    "registros_actualizados": 4,
    "por_modelo": [
      {"modelo": "res.partner", "creados": 306, "actualizados": 4,
       "rango_xmlid": "adv_acme.partner_*", "errores": {}}
    ],
    "errores": [
      {"codigo": "E400", "archivo": "31_product.template.csv", "fila": 412,
       "columna": "uom_po_id", "mensaje": "UoM de compra en otra categoría que la UoM"}
    ],
    "bitacoras": ["08-carga/bitacora-res.partner.jsonl"],
    "plan": "08-carga/plan-carga.json",
    "estado": "08-carga/estado-carga.json",
    "capacidades": "02-instancia/capacidades-instancia.json",
    "resumen": "08-carga/resumen-carga.md"
  },
  "resultado_qa": {
    "entorno": "staging",
    "casos_total": 16,
    "casos_ok": 14,
    "casos_fallidos": [
      {"id": "QA-007", "flujo": "ventas", "motivo": "pricelist_id quedó en la lista pública; falta property_product_pricelist en el partner"}
    ],
    "resultados": ["09-qa/resultados-ventas.md"]
  },
  "ensayo_desde_cero": false,
  "carga_completa": false,
  "pendientes": []
}
```

`carga_completa: false` si hay un solo archivo en error o un caso de QA rojo. Nunca reportes carga
parcial como completa.

`cierre_bucle` es uno de `todo_cargado` | `sin_progreso` | `tope_rondas` | `detenido_E500`, y es el
dato que dice si vale la pena volver a ejecutar A5. `todo_cargado` cierra la etapa. `sin_progreso`
significa que lo que falta necesita una decisión del consultor: volver a ejecutar sin cambiar nada da
exactamente el mismo resultado y cuesta lo mismo. `tope_rondas` sí se reanuda tal cual — el estado
está en `estado-carga.json` y la siguiente corrida sigue desde ahí.

## Nunca

- No cargues un archivo que no está en `cargables`.
- No escribas en producción sin confirmación explícita de base de datos y rama.
- No ejecutes el QA en producción.
- No uses `create` en bucle donde va `load()`: pierdes el xmlid y la idempotencia.
- No intentes leer un CSV con `require('fs')`, `require('csv-parse')` ni `import csv`: ninguno existe
  en ningún sandbox. Un `require is not defined` no se arregla probando otro módulo — se arregla
  usando `sandboxed_python` con `capabilities: ["workspace_read"]`.
- No adivines nombres de campo. Un `Invalid field ...` se resuelve con `fields_get` sobre ese modelo
  (`E110`), no probando una segunda variante: dos rechazos seguidos por campo inexistente significan
  que no hiciste la introspección.
- No declares éxito por `ok: true` sin haber leído `messages`.
- No devuelvas el control en el primer rechazo corregible. `E110`, `E220`, `E300` y `E320` son tuyos:
  se corrigen y se reintentan dentro del bucle. Devolver el control ahí deja la base a medias y
  convierte una carga de una corrida en tres.
- No intentes instalar un módulo por RPC, y no detengas el plan completo porque falte uno. Verifica el
  `state`, detén solo los archivos de ese módulo, escala el `modulo_faltante`, y sigue.
- No reintentes sin haber cambiado algo verificable (un campo confirmado, una dependencia cargada, un
  orden distinto, unas filas apartadas). Dos rechazos idénticos seguidos son un bucle, no un
  reintento — y una ronda sin progreso cierra el bucle, no lo reinicia.
- No pierdas un lote por una fila mala: recárgalo sin las filas rechazadas y repórtalas.
- No infieras el orden de carga del nombre del archivo cuando no hay prefijo `NN`, y no cargues dos
  variantes del mismo modelo (`res.partner.csv` y `res_partner.csv`) como si fueran dos archivos.
- No reintentes ciegamente un rechazo de negocio; pasa por `administrar-casos-de-borde-odoo`.
- No crees datos maestros que no estaban en el blueprint para que una referencia resuelva.
- No reportes carga parcial como completa, ni omitas el estado del ensayo desde cero.
