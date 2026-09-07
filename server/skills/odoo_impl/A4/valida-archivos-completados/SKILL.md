---
name: valida-archivos-completados
description: >-
  Runbook completo del Agente A4: valida los archivos que el consultor devolvió en 06-completadas/
  (estructura, obligatorios, formatos, catálogos, xmlids, referencias y orden) y produce el informe de
  errores por archivo. Ejecuta los pasos en orden y no vuelvas al Coordinador entre ellos.
allowed-tools: odoo_jsonrpc file_read file_modify fs_search sandboxed_python javascript_code
metadata:
  agente: A4
  tipo: DET
  prioridad: P0
  depende_de: genera-plantillas-de-carga
  siguiente_agente: COORD
  icon: "✅"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Validar archivos completados (runbook A4)

Última barrera antes de escribir en Odoo. Todo error que pasa de acá se convierte en un registro
cargado, y deshacer una carga significa restaurar la base de datos.

Tu principio de diseño es uno: **detectar TODOS los errores en una pasada.** El consultor va a corregir
una vez; si le entregas los tres primeros errores y él corrige y devuelve, y entonces aparecen los
siguientes doce, has gastado dos ciclos humanos para nada.

Lee `contrato-implementacion-odoo`, `convencion-ids-externos`, `orden-de-carga-odoo`,
`odoo-rpc-en-opencompany` (la taxonomía de errores está ahí) y `sandbox-de-codigo-en-opencompany`
(**obligatoria antes del paso 3** — qué sandbox puede abrir un CSV y cuál no). De
`flujos-de-referencia`, abre solo los
flujos del proyecto: sus "reglas de validación propias" son validaciones adicionales a las genéricas.

**No corriges datos.** Reportas el error con el código, la ubicación exacta y —cuando el valor
erróneo se parece a uno válido— el candidato. Escribes en `07-validacion/`, en ninguna otra carpeta.

Precondición: hay archivos en `06-completadas/`. Si está vacío, el consultor no devolvió nada: no es
un error, es un pendiente de handoff. Devuelve el control.

## Paso 1 — Inventariar

`fs_search` en `06-completadas/` y comparar contra `05-plantillas/`. Por cada archivo esperado:

- **Falta el CSV** → no es error de validación; anótalo como faltante en el resultado.
- **Falta el `.meta.json`** → `E100`. Sin el sidecar no tienes catálogos ni referencias, y validar sin
  ellos daría un falso "todo bien".
- **Archivo inesperado** → anótalo; puede ser un renombre del consultor o un objeto que no correspondía.

## Paso 2 — Validar estructura (`E100`, y detiene el archivo)

Por archivo, antes de mirar una sola fila de datos:

1. El CSV se parsea. Comillas desbalanceadas o número de columnas inconsistente entre filas → `E100`.
2. La primera columna es `id`.
3. La cabecera es **idéntica** a la de `05-plantillas/`: mismos nombres, mismo orden. Una columna
   agregada, quitada o renombrada → `E100`. No intentes adivinar el mapeo: una cabecera cambiada
   significa que no sabes qué contiene esa columna.
4. Existe el sidecar y su `modelo` coincide con el nombre del archivo.
5. **Cada columna existe en el modelo real.** Un `fields_get` por modelo (uno, cacheado en
   `02-instancia/introspeccion.json`) y cruzas la cabecera contra él. Que la cabecera coincida con la
   plantilla no significa que exista en Odoo: la plantilla puede estar escrita contra una versión
   anterior, y ese es el defecto que A5 descubre a mitad de la carga si tú no lo reportas antes. Una
   columna sin campo se reporta como `E100` **con los campos candidatos** que `fields_get` sí trae —
   eso es lo que permite que A3 corrija la plantilla en el origen en vez de que A5 adivine.
   La columna del xmlid es la excepción: `xmlid` es un nombre humano, y A5 la convierte en `id`.

Un `E100` **detiene el archivo completo**: no reportes las filas de un archivo cuya estructura no
entiendes, porque los números de fila y las columnas que informes serán de otro archivo del que crees.
Igual produces el `informe-<modelo>.md` diciendo qué está mal en la estructura.

## Paso 3 — Validar filas (todas, sin cortar)

Recorre las filas con `sandboxed_python` y `capabilities: ["workspace_read"]` — es el **único** sandbox
que puede abrir el CSV. `javascript_code` no tiene `require('fs')` y `python_code` no tiene `import`:
ninguno ve el disco, y un `require is not defined` no se arregla probando otro módulo ni pegando el
archivo en el prompt. Lee `sandbox-de-codigo-en-opencompany` antes del primer script: el resultado es
la **última expresión** del programa, y no hay `with` ni módulo `csv`.

**El script ya está escrito: usa S1 de `scripts-verificados-de-carga-odoo`** con las tres primeras
líneas apuntando a `06-completadas/<archivo>`. Es el mismo que va a usar A5 para cargar, y ahí está la
ventaja: sus `avisos` son exactamente los `E200` / `E210` / `E220` de este paso, calculados contra el
`fields_get` real, así que validas con el criterio con que se va a cargar y no con uno paralelo que
pueda diferir. Su `filas_a_apartar_antes_de_enviar` es tu lista de filas rechazadas, y sus
`descartes_columna` son los `E100` de columna del paso 2.

Es aritmética y comparación de strings, no razonamiento: no valides fila por fila en el prompt. Acumula
**todos** los hallazgos en una pasada. La fila de ejemplo (`fila_ejemplo` del sidecar) se ignora si sigue
intacta; si el consultor la sobrescribió con datos reales, se valida como cualquier otra.

**`E200` — obligatorio vacío.** Cada campo de `obligatorios` del sidecar, no vacío. Una celda con
espacios es vacía.

**`E210` — formato inválido.**

| Tipo | Regla | Sugerencia a emitir |
|---|---|---|
| `date` | `YYYY-MM-DD` | Si es `DD/MM/YYYY` o `DD-MM-YYYY` sin ambigüedad, sugiere la conversión |
| `datetime` | `YYYY-MM-DD HH:MM:SS` (UTC) | idem |
| `float` / `monetary` | punto decimal, sin separador de miles | Si trae `1.234,56`, sugiere `1234.56` |
| `integer` | dígitos, sin decimales | |
| `boolean` | `1`/`0`/`True`/`False`/vacío | Un `"sí"` o `"x"` es error |
| `vat` (CL) | RUT con dígito verificador correcto (mód. 11) | **Emite el DV correcto** |
| `account.account.code` | solo alfanumérico y puntos | `1-1-2-05` se rechaza; sugiere `1.1.2.05` |

El DV del RUT se calcula, no se estima: es el chequeo con mejor retorno de todo el paso, porque un RUT
con DV malo pasa la carga y produce un partner que el SII rechaza mucho después.

**`E220` — fuera de catálogo.** Contra las claves reales del `selection` que trae `fields_get`, no
contra el `catalogos` del sidecar: el sidecar lo escribió A3 y puede estar desactualizado igual que la
cabecera. Compara el **valor técnico**. Si el consultor escribió la etiqueta ("Factura de cliente" en
vez de `out_invoice`), sugiere el valor técnico correspondiente: es el error más frecuente y el más
fácil de resolver bien.

Dos casos que se ven distintos y son el mismo: una clave que existía en una versión anterior
(`product.template.type = 'product'`, que en 19 es `consu` + `is_storable`) y una columna llena con el
valor de otra columna (`res.partner.type = '1'`, que es el tipo de contribuyente). Ambos son `E220`,
pero el segundo afecta a **todas** las filas: dilo así en el informe, porque la corrección es una sola
sobre la columna y no una por fila.

**`E310` — xmlid duplicado.** Dos filas con el mismo `id` en el mismo archivo. Reporta **ambas** filas;
quien corrige necesita ver las dos para saber cuál sobra.

**Formato del `id`** (también `E210`): `^<prefijo>\.[a-z0-9_]+$` con el `prefijo_xmlid` del sidecar.
Mayúsculas, acentos, espacios o guiones → error con la versión normalizada como sugerencia. Y si el
`id` es un contador (`partner_001`, `categ_1`) → error explícito citando la razón: al reordenar filas
el id apunta a otro registro y la recarga renombra registros existentes en silencio.

**Jerarquía interna.** En archivos con `parent_id/id` al mismo archivo (`product.category`,
`stock.location`, partners padre/hijo), el padre debe estar en una fila **anterior**. Si está después
→ `E320`.

## Paso 4 — Resolver referencias (`E300`, `E320`)

Por cada columna `<campo>/id` y cada celda no vacía, el xmlid destino tiene que existir. Tres lugares
donde buscar, en este orden:

1. **En los `id` de otro archivo del lote.** Construye primero el índice completo de todos los xmlids
   de todos los archivos de `06-completadas/` (un solo recorrido), y resuelve contra el índice en
   memoria. Si el destino está en un archivo con `NN` **mayor** al del archivo que lo referencia →
   `E320`, y detiene ese archivo.
2. **En la instancia** (xmlids nativos de Odoo o de cargas anteriores). Una consulta en **bloque**,
   nunca una por celda:

```
model="ir.model.data", method="search_read",
domain=[["complete_name","in",["adv_acme.payment_term_30d","base.CL","uom.product_uom_unit"]]],
fields=["complete_name","model","res_id"]
```

   Si `complete_name` no está disponible en la instancia, usa
   `domain=[["module","in",[...]],["name","in",[...]]]` y cruza los pares localmente. Trocea en lotes
   de ~200 valores.
3. **En ningún lado** → `E300`. Cuando el valor se parece a un xmlid existente (una `s` de diferencia,
   un guion en vez de guion bajo), **sugiere el candidato**: es la diferencia entre una corrección de
   un minuto y una de media hora.

Esta es la única razón por la que A4 toca Odoo, y es solo lectura. `fields` mínimos, en bloque, y
cachea el resultado a `07-validacion/` si vas a reusarlo.

## Paso 5 — Reglas del flujo (`E400` anticipado)

Las "reglas de validación propias" de la referencia del flujo, que Odoo aplicaría como constraint. Es
más barato detectarlas acá que recibir el rechazo en la carga:

- UoM del producto en la misma `uom.category` que la UoM de compra.
- Impuestos coherentes con el tipo (venta vs. compra) y con la posición fiscal.
- Cuenta contable del tipo correcto para el uso (por cobrar / por pagar / ingreso / gasto).
- En Chile: cada tipo de documento electrónico con su diario; la comuna como entidad, no texto libre.
- BoM multinivel sin ciclos y con los componentes definidos antes.

Lo que no puedas verificar sin escribir, no lo verifiques: no hagas un `create` de prueba. Anótalo en
el informe como riesgo a confirmar en la carga.

## Paso 6 — Escribir informes

Por archivo, `07-validacion/errores-<modelo>.csv`:

```csv
codigo,archivo,fila,columna,valor,mensaje,corrige
E210,20_res.partner.csv,14,vat,76.123.456-8,"DV incorrecto: para 76.123.456 el DV es 7",consultor
E220,31_product.template.csv,7,type,Almacenable,"Valor de catálogo esperado: 'product' (Almacenable)",consultor
E300,31_product.template.csv,9,categ_id/id,adv_acme.categ_insumo,"No existe. ¿adv_acme.categ_insumos (27_product.category.csv, fila 4)?",consultor
```

Sin `archivo` + `fila` + `columna` el error es inútil para quien corrige. La columna `corrige`
(`consultor` | `agente`) sale de la taxonomía y determina a quién vuelve el trabajo.

Y `07-validacion/informe-<modelo>.md`: filas totales, filas válidas, conteo por código, si el archivo
quedó detenido y por qué, y los riesgos no verificables. En lenguaje del consultor, no de agente.

## Paso 7 — Veredicto por archivo

Tres estados, y confundirlos es el error caro:

- **`LIMPIO`** — cero errores. A5 puede cargarlo.
- **`CON_ERRORES`** — errores de fila. A5 **no** carga este archivo; vuelve al consultor. Los demás
  archivos limpios sí avanzan: la carga es por archivo, no todo o nada.
- **`DETENIDO`** — `E100` o `E320`. El archivo no se procesó completo. No es una falla de dato: el
  archivo o su lugar en el orden están mal.

## Salida (un resultado al COORD)

```json
{
  "validacion": {
    "archivos_total": 9,
    "limpios": 6,
    "con_errores": 2,
    "detenidos": 1,
    "faltantes": ["35_product.supplierinfo.csv"],
    "detalle": [
      {"archivo": "20_res.partner.csv", "modelo": "res.partner", "veredicto": "CON_ERRORES",
       "filas": 310, "filas_validas": 303,
       "errores": {"E210": 7},
       "informe": "07-validacion/informe-res.partner.md",
       "errores_csv": "07-validacion/errores-res.partner.csv"},
      {"archivo": "64_mrp.bom.csv", "modelo": "mrp.bom", "veredicto": "DETENIDO",
       "motivo": "E320: referencia adv_acme.prod_tmpl_subconjunto definido en 31 pero ausente del archivo"}
    ]
  },
  "cargables": ["27_product.category.csv", "15_account.payment.term.csv"],
  "riesgos_no_verificados": ["Folios CAF para documento 33: no verificable sin escribir"],
  "pendientes": []
}
```

`cargables` es la lista que A5 va a usar. Que sea explícita, y no derivada de "los que no tienen
errores", evita que un archivo detenido se cargue por omisión.

## Nunca

- No corrijas datos en `06-completadas/`. Esa carpeta es del consultor.
- No escribas en Odoo. Solo lectura, y solo para resolver referencias.
- No cortes la validación en el primer error de fila.
- No reportes un error sin archivo, fila y columna.
- No declares `LIMPIO` un archivo cuyo sidecar falta: sin catálogos no validaste catálogos.
- No hagas una consulta a Odoo por celda.
