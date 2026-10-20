---
name: genera-plantillas-de-carga
description: >-
  Runbook completo del Agente A3: genera un CSV con cabeceras nativas de Odoo más su sidecar
  .meta.json por cada objeto fuente=plantilla del blueprint, con el instructivo para el consultor.
  Ejecuta los pasos en orden y no vuelvas al Coordinador entre ellos.
allowed-tools: odoo_jsonrpc file_read file_modify fs_search sandboxed_python javascript_code
metadata:
  agente: A3
  tipo: DET
  prioridad: P0
  depende_de: disena-blueprint-y-backlog
  siguiente_agente: COORD
  icon: "📝"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Generar plantillas de carga (runbook A3)

Produces los archivos que el consultor va a llenar. Es el único entregable del pipeline que sale de la
máquina y vuelve: si una columna está mal nombrada, mal explicada o no debía existir, el costo no es
una iteración de agente sino un ciclo humano completo.

Lee `contrato-implementacion-odoo`, `convencion-ids-externos`, `orden-de-carga-odoo` y
`sandbox-de-codigo-en-opencompany` (**obligatoria antes del paso 6** — qué sandbox puede abrir un
archivo y cuál no). De
`flujos-de-referencia`, abre solo los flujos del proyecto: sus secciones de "objetos de carga (campos
mínimos + trampas)" son la materia prima de las columnas y del instructivo.

**Consultas Odoo solo para leer campos y catálogos, y no escribes nunca.** `02-instancia/introspeccion.json`
es tu punto de partida, no tu autoridad: A1 introspeccionó antes de que existiera el blueprint, así que
no cubre necesariamente los modelos que tú vas a plantillar. La autoridad de cada columna es un
`fields_get` del modelo (paso 2b). Escribes en `05-plantillas/`, en ninguna otra carpeta; el único punto
de escritura en Odoo es A5.

Precondición: `blueprint.yaml` existe y no hay pendientes abiertos sobre los modelos a plantillar. Un
objeto con `[VERIFICAR]` sin resolver no se plantilla: no generes la columna dudosa "por si acaso".

## Paso 1 — Leer el blueprint y la introspección

`file_read` de `03-blueprint/blueprint.yaml` y `02-instancia/introspeccion.json`. Toma solo los
objetos con `fuente: plantilla`. Los `configuracion` los ejecuta A5 por RPC y los `derivado` no llevan
archivo — generar uno para un `derivado` hace que el consultor llene datos que Odoo va a sobrescribir.

Ordena por el `nn` del blueprint. Los archivos se generan y se cargan en ese orden.

## Paso 2 — Elegir las columnas de cada plantilla

Tres fuentes, en este orden de precedencia:

1. **El `fields_get` del modelo (paso 2b)** — el campo existe, su `type`, su `required` y, si es
   `selection`, sus claves. Si no está ahí, la columna **no se genera**. Ni siquiera si la referencia
   del flujo la menciona o `introspeccion.json` la trae: la referencia está escrita para una familia de
   versiones y la introspección puede ser de antes del blueprint.
2. **La referencia del flujo** — cuáles de los campos existentes son los mínimos útiles, y sus
   trampas.
3. **El blueprint** — qué HU cubre el objeto, que puede exigir un campo opcional.

Reglas de columnas:

- **`id` primero, siempre.** Es la columna que hace la carga repetible. Sin ella, la segunda corrida
  duplica todo.
- **Solo los `required: true` del `fields_get` + los mínimos del flujo + los que el blueprint pide.**
  Una plantilla de 40 columnas para un modelo que necesita 8 se llena mal: el consultor completa lo
  que entiende y deja basura en el resto.
- **Referencias por xmlid siempre que el destino lo tenga**: `categ_id/id`, no `categ_id`. Un `name`
  ambiguo empareja el registro equivocado **sin dar error**, que es la peor forma de fallar. La
  excepción es el destino que **no tiene xmlid** — registros que Odoo creó solo, como la ubicación
  `CPO/Stock` de un almacén. Ahí la cabecera va sin `/id` y el instructivo pide el nombre exacto tal
  como aparece en la UI. Poner `/id` sobre un valor que no es un xmlid produce
  `No matching record found for external id`, que parece una referencia faltante y no lo es.
- **many2many por xmlid separado por comas**: `taxes_id/id`.
- **Nada de `<campo>/.id`** (id numérico de base de datos): rompe la portabilidad entre staging y
  producción, que es justo lo que el proceso necesita conservar.
- **one2many anidado solo si es inevitable.** Ocupa varias filas con el `id` del padre vacío en las
  siguientes, y basta que el consultor ordene el CSV para romper la relación. Cuando el modelo hijo
  puede ir en su propio archivo con `<padre>_id/id`, hazlo así (`mrp.bom` y `mrp.bom.line` en 64 y
  65). Si no hay alternativa, el instructivo lo advierte en negrita.

## Paso 2b — Verificar cada columna contra la instancia (una llamada por modelo)

Antes de escribir un solo CSV, un `fields_get` por modelo con la tool `odoo_jsonrpc`. Es **solo
lectura**, es una llamada, y es lo que separa una plantilla que carga de una que hace perder un ciclo
humano y tres rondas de A5:

```
model="product.template", method="fields_get",
kwargs={"attributes": ["type", "required", "relation", "selection", "string"]}
```

Qué haces con el resultado, y ninguna de las tres es opcional:

1. **Una columna sin campo no se escribe.** Lo que tú recuerdas de Odoo puede ser de otra versión. En
   19 no existen `uom_po_id`, `property_stock_account_input_categ_id` ni `product.category.valuation`
   (es `property_valuation`), y `groups_id` es `group_ids`. Si el blueprint pide ese dato y no hay
   campo que lo sostenga, es una observación para A2 — no una columna inventada ni una columna
   "parecida".
2. **Los catálogos salen de `selection`, no de tu memoria.** `product.template.type` en 19 es
   `consu` / `service` / `combo`, y "almacenable" es `consu` + `is_storable`; `property_valuation` es
   `periodic` / `real_time`, no `manual`. Un `catalogos` inventado hace que A4 valide contra un
   catálogo falso y apruebe filas que Odoo va a rechazar. Si necesitas las etiquetas para el
   instructivo y la instancia está traducida, pide `kwargs={"context": {"lang": "en_US"}}` en una
   segunda lectura: **las claves no se traducen, las etiquetas sí**.
3. **`required` de la instancia manda sobre `required` de la referencia.** Es lo que va a `obligatorios`
   del sidecar, y es lo que A4 usa para emitir `E200`.

**Cachea el resultado en `05-plantillas/campos-<modelo>.json`, con ese nombre exacto**, y anota en el
sidecar la fecha: un `fields_get` por modelo, no uno por columna ni uno por archivo. El nombre es parte
del contrato, no una preferencia: el script de carga de A5
(`scripts-verificados-de-carga-odoo`) lee ese archivo en vez de volver a llamar a Odoo, así que la
introspección que haces acá es la que le ahorra a A5 una llamada por modelo. Forma:
`{"modelo": "...", "obtenido": "<fecha>", "campos": {<lo que devolvió fields_get>}}`.

Si el login falla, **no pruebes otro host**: es base de datos, usuario o api_key, y va como pendiente.
Y si la instancia no está alcanzable, genera las plantillas desde `introspeccion.json` pero **dilo en el
resultado** como riesgo — el consultor tiene que saber que sus columnas no se verificaron.

## Paso 3 — Escribir el CSV

`05-plantillas/NN_<modelo>.csv` con `file_modify`. Cabecera + **una fila de ejemplo realista**, nada
más. La fila de ejemplo es lo que el consultor va a copiar: si el ejemplo tiene un RUT inventado sin
dígito verificador válido o un xmlid que no cumple la convención, 300 filas van a repetir el error.

```csv
id,name,vat,l10n_cl_sii_taxpayer_type,is_company,property_payment_term_id/id
adv_acme.partner_761234567,ACME SpA,76.123.456-7,1,1,adv_acme.payment_term_30d
```

El `id` del ejemplo debe ser derivable de la clave natural de su propia fila (RUT `76.123.456-7` →
`partner_761234567`), para que la regla se lea sola. Un ejemplo con `partner_001` enseña exactamente
la práctica que la convención prohíbe.

CSV: coma como separador, UTF-8, comillas dobles solo cuando el valor contiene coma o comilla, sin BOM.

## Paso 4 — Escribir el sidecar `.meta.json`

`05-plantillas/NN_<modelo>.meta.json`. Transporta lo que un `.xlsx` llevaría en desplegables y
comentarios; el validador (A4) lo lee para rechazar valores fuera de catálogo.

```json
{
  "modelo": "res.partner",
  "prefijo_xmlid": "adv_acme",
  "version_plantilla": "1.0",
  "generado": "2026-08-10",
  "orden_carga": 20,
  "obligatorios": ["id", "name", "vat"],
  "catalogos": {
    "l10n_cl_sii_taxpayer_type": ["1", "2", "3", "4"],
    "is_company": ["0", "1"]
  },
  "referencias": {
    "property_payment_term_id/id": "15_account.payment.term.csv"
  },
  "fila_ejemplo": 2,
  "introspeccion_fecha": "2026-08-10",
  "odoo_version": "19.0"
}
```

- `obligatorios`: `id` + los `required: true` del `fields_get` del paso 2b. A4 emite `E200` si están
  vacíos.
- `catalogos`: **las claves** de cada `selection` tal como las devolvió `fields_get` — nunca las
  etiquetas traducidas ni un catálogo recordado. `out_invoice`, no "Factura de cliente". A4 emite `E220`
  si el valor no está, y valida contra la instancia: un catálogo desactualizado acá no le hace pasar
  nada, solo hace que tu sidecar contradiga a Odoo.
- `referencias`: por cada `<campo>/id`, en qué archivo se definen los xmlids destino. Es lo que
  permite a A4 detectar `E300` (no existe) y `E320` (existe pero en un archivo posterior).
- `introspeccion_fecha`: si la instancia cambia después, esta fecha delata que la plantilla quedó
  vencida.

Como el CSV no tiene desplegables, la restricción se aplica más tarde (en la validación) en vez de en
el momento de escribir. El instructivo tiene que compensarlo: es la única barrera antes de que el
consultor complete 300 filas con un valor inválido.

## Paso 5 — Escribir el INSTRUCTIVO.md

`05-plantillas/INSTRUCTIVO.md`, un solo archivo para todo el lote. Es el entregable más importante de
esta etapa porque es el que lee la persona.

Contenido obligatorio:

1. **Cómo llenar la columna `id`** — la convención con dos ejemplos del proyecto real, y la razón:
   permite corregir y recargar sin duplicar. Explicita que **no se cambia una vez entregado**.
2. **Prohibido usar contadores** (`partner_001`) y por qué: al reordenar filas, el id apunta a otro
   registro y la recarga renombra registros existentes en silencio.
3. **No reordenar ni filtrar** los archivos con one2many anidado, indicando cuáles son.
4. **Formatos**: fechas `YYYY-MM-DD`, decimales con punto, booleanos `1`/`0`, RUT con puntos y guion
   en `vat` pero sin ellos en el `id`. Dos que Odoo valida y rechazan la fila completa: el **dígito
   verificador** del RUT tiene que ser el correcto (módulo 11) cuando la localización chilena está
   activa, y el **código de cuenta contable** acepta solo alfanuméricos y puntos — `1.1.2.05`, nunca
   `1-1-2-05`.
5. **Los catálogos de cada archivo**, con los valores técnicos y su significado en castellano. Es lo
   que sustituye a la desplegable.
6. **Las referencias entre archivos**: qué columna de qué archivo apunta a qué archivo, y que el
   archivo referenciado se llena primero.
7. **Qué NO tocar**: la fila de ejemplo se puede borrar o sobrescribir; la cabecera no se toca; no se
   agregan columnas (una columna nueva es `E100` y detiene el archivo completo).
8. **Dónde devolverlo**: `06-completadas/`, con el mismo nombre de archivo. El sidecar `.meta.json`
   se copia tal cual, sin editar.
9. **Las trampas del flujo**, tomadas de la referencia: en Chile, que la comuna es una entidad y no
   texto libre; que el `vat` lleva dígito verificador; que las categorías padre van en filas
   anteriores a sus hijas.

Escrito para una persona que sabe de Odoo funcional y no de este pipeline. Sin jerga de agentes, sin
códigos de error internos.

## Paso 6 — Verificar antes de devolver

Sobre los archivos generados, con `sandboxed_python` y `capabilities: ["workspace_read"]` — es el
**único** sandbox que puede abrir un archivo. `javascript_code` no tiene `require('fs')` y
`python_code` no tiene `import`: ninguno de los dos ve el disco, y un `require is not defined` no se
arregla probando otro módulo. Los detalles (qué expresión devuelve el resultado, por qué no hay `with`
ni `csv`) están en `sandbox-de-codigo-en-opencompany`; léela antes de escribir el primer script.
`javascript_code` sigue sirviendo para aritmética sobre datos que ya tienes en el prompt.

1. Todo archivo tiene `id` como primera columna.
2. Todo `<campo>/id` está en `referencias` del sidecar, y el archivo destino tiene `NN` **menor o
   igual**. Si es mayor, el orden del blueprint está mal: pendiente, no lo generes así.
3. Todo `selection` de la introspección presente como columna está en `catalogos`.
4. El `id` de la fila de ejemplo cumple `^<prefijo>\.[a-z0-9_]+$` y no es un contador.
5. Hay exactamente un archivo por objeto `fuente: plantilla` del blueprint, y ninguno para
   `configuracion` o `derivado`.
6. `fs_search` en `05-plantillas/` confirma el conteo: `2N + 1` archivos para N objetos.

## Salida (un resultado al COORD)

```json
{
  "plantillas": {
    "total": 9,
    "archivos": [
      {"modelo": "product.category", "csv": "05-plantillas/27_product.category.csv",
       "meta": "05-plantillas/27_product.category.meta.json",
       "columnas": 4, "obligatorias": 2, "filas_estimadas": 25}
    ],
    "instructivo": "05-plantillas/INSTRUCTIVO.md"
  },
  "handoff": {
    "destino": "06-completadas/",
    "orden_de_llenado": ["15_account.payment.term.csv", "20_res.partner.csv", "27_product.category.csv", "31_product.template.csv"]
  },
  "pendientes": []
}
```

`orden_de_llenado` es el orden de dependencias, no el alfabético inverso: el consultor tiene que
llenar primero los archivos que otros referencian, o no sabrá qué xmlid escribir en la columna de
referencia.

## Nunca

- No generes una columna para un campo que `fields_get` no reporta, ni la generes solo porque la trae
  `introspeccion.json` o la menciona la referencia del flujo.
- No generes archivo para un objeto `configuracion` o `derivado`.
- No uses contadores en el `id` del ejemplo.
- No pongas etiquetas traducidas en `catalogos`; van las claves del `selection`.
- No pongas `/id` en una columna cuyo destino no tiene xmlid.
- No escribas en Odoo. Tu acceso es solo lectura, y solo para `fields_get`.
- No entregues plantillas sin `INSTRUCTIVO.md`. Un CSV sin instructivo vuelve mal llenado.
