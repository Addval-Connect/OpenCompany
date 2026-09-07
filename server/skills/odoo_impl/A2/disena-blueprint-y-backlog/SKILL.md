---
name: disena-blueprint-y-backlog
description: >-
  Runbook completo del Agente A2: convierte la matriz de brechas y la introspección en el blueprint
  de objetos (con fuente, dependencias y prefijo de xmlid) y en el backlog de tareas ejecutable.
  Ejecuta los pasos en orden y no vuelvas al Coordinador entre ellos.
allowed-tools: file_read file_modify fs_search javascript_code
metadata:
  agente: A2
  tipo: LLM
  prioridad: P0
  depende_de: analiza-brechas-e-introspecciona
  siguiente_agente: COORD
  icon: "📐"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Diseñar blueprint y backlog (runbook A2)

Traduces "qué pide el cliente" a "qué objetos de Odoo, en qué orden, cargados cómo". Es la etapa
donde se decide el trabajo de todas las siguientes: un objeto mal clasificado como `plantilla` genera
un archivo que nadie debía llenar, y uno mal marcado como `derivado` deja un hueco que se descubre en
el QA.

Lee `contrato-implementacion-odoo`, `convencion-ids-externos` y `orden-de-carga-odoo`. De
`flujos-de-referencia`, abre con `read_resource` solo los flujos del proyecto más `l10n-cl.md` si el
país es CL.

**No consultas Odoo.** Tu autoridad sobre qué existe es `02-instancia/introspeccion.json`, que A1 ya
generó. Escribes en `03-blueprint/` y `04-backlog/`, en ninguna otra carpeta.

Precondición: `introspeccion.json` con fecha vigente y `confianza ≠ baja`. Si la confianza es baja, no
diseñes: devuelve un pendiente `otro` — el Coordinador debe re-delegar la introspección primero.

## Paso 1 — Leer las entradas y cuestionar los supuestos

`file_read` de `01-analisis/matriz-brechas.csv`, `01-analisis/supuestos.md`,
`01-analisis/preguntas-abiertas.md` y `02-instancia/introspeccion.json`.

Los supuestos de A1 son lo primero que revisas, no lo último. A1 clasificó bajo presión de no
detenerse; tú tienes la instancia leída y el grafo de dependencias delante. Si un supuesto no
sobrevive, es un pendiente, no una corrección silenciosa.

Filtra: las filas `desarrollo`, `integracion` y `fuera_de_alcance` **no entran en el blueprint de
objetos**. Entran en el backlog como tareas de su tipo, para que queden trazadas y no se confundan con
omisiones al cerrar.

## Paso 2 — Fijar el prefijo de xmlid

Un solo `prefijo_xmlid` para todo el proyecto, declarado en el blueprint. Formato `<org>_<proyecto>`
en minúsculas, solo `[a-z0-9_]`: `adv_acme`. Nunca `base`, nunca el nombre de un módulo de Odoo
(colisiona con sus propios registros y los sobrescribe).

Esta decisión es irreversible en la práctica: cambiar el prefijo después de la primera carga no
renombra nada, crea un universo paralelo de registros y deja el anterior huérfano.

## Paso 3 — Diseñar los objetos

Un entry en `objetos:` por modelo a poblar. El campo que decide todo es `fuente`:

| `fuente` | Cuándo | Quién lo materializa |
|---|---|---|
| `plantilla` | Volumen de datos que solo el cliente conoce (partners, productos, BoM) | A3 genera el CSV, el consultor lo llena |
| `configuracion` | Pocos registros, decididos en el diseño (diarios, posiciones fiscales, bodegas) | A5 los escribe directo por RPC |
| `derivado` | Odoo los crea solo | **Nadie.** No lleva archivo |

Los tres errores que se cometen acá:

- **`plantilla` para algo que son 3 registros.** Un archivo CSV de 3 filas cuesta un ciclo humano
  completo de handoff. Si el diseño ya sabe los valores, es `configuracion`.
- **`plantilla` para un objeto `derivado`.** `product.product` es el caso clásico: Odoo genera las
  variantes desde `product.attribute`. Solo lleva archivo si hay variantes con **datos propios**
  (código interno, código de barras, precio extra), y entonces el archivo actualiza, no crea.
- **`depende_de` incompleto.** Es lo que A5 usa para ordenar y lo que A4 usa para detectar `E320`. Un
  `depende_de` vacío en un modelo que referencia impuestos hace que el archivo se cargue antes que
  los impuestos y falle a la mitad.

Cada objeto lleva su `NN` del orden canónico (`orden-de-carga-odoo`). El número no es decorativo: el
cargador procesa por orden alfabético de archivo, así que el `NN` **es** la garantía de orden.

`03-blueprint/blueprint.yaml`:

```yaml
proyecto: acme
prefijo_xmlid: adv_acme
entorno_objetivo: staging
compania:
  nombre: ACME SpA
  pais: CL
  moneda: CLP
  localizacion: [l10n_cl]           # l10n_cl_edi pendiente P-001
flujos: [ventas, contabilidad]
objetos:
  - modelo: account.account
    nn: "05"
    fuente: configuracion
    cantidad_estimada: 142
    depende_de: []
    hu: [HU-050]
    nota: "l10n_cl ya instaló el plan; revisar antes de crear para no duplicar"
  - modelo: product.category
    nn: "27"
    fuente: plantilla
    cantidad_estimada: 25
    depende_de: []
    hu: [HU-014, HU-031]
  - modelo: product.template
    nn: "31"
    fuente: plantilla
    cantidad_estimada: 1200
    depende_de: [product.category, uom.uom, account.tax]
    hu: [HU-014]
  - modelo: product.product
    nn: "33"
    fuente: derivado
    depende_de: [product.template, product.attribute]
    nota: "Odoo genera variantes; sin archivo"
```

Todo campo o módulo que la introspección no confirmó va marcado `[VERIFICAR]` en la `nota` **y**
levanta un pendiente. No dejes un `[VERIFICAR]` silencioso: A3 lo convertiría en una columna de un
CSV que el consultor va a llenar para nada.

`03-blueprint/decisiones.md` registra el **por qué** de cada decisión no obvia: por qué un objeto es
`configuracion` y no `plantilla`, por qué se reutiliza el plan de cuentas de `l10n_cl` en vez de
cargar uno propio, qué alternativa se descartó. Es lo que evita que alguien "arregle" la decisión tres
semanas después.

## Paso 4 — Derivar el backlog

Una tarea por unidad de trabajo ejecutable. Deriva mecánicamente del blueprint, no lo reinventes:

- Objeto `fuente: plantilla` → tarea `carga` con `agente: A5`, **más** una tarea `carga` con
  `agente: "humano:<rol>"` para completar el archivo. El handoff humano es una tarea explícita del
  backlog, no un implícito; es el único punto donde el pipeline espera a una persona.
- Objeto `fuente: configuracion` → tarea `configuracion` con `agente: A5`.
- Objeto `fuente: derivado` → **ninguna tarea**.
- Fila `desarrollo` / `integracion` de la matriz → tarea de su tipo, `agente: "humano:desarrollo"`.
- Por flujo en alcance → una tarea `qa` con `agente: A5`.

`depende_de` entre tareas replica el `depende_de` entre modelos. El `dod` es verificable o no sirve:
"todas las filas con xmlid resuelto y 0 errores en 07-validacion", no "categorías cargadas
correctamente".

```yaml
- id: T-012
  titulo: Completar plantilla de categorías de producto
  tipo: carga
  flujo: ventas
  modelo: product.category
  depende_de: []
  agente: "humano:consultor funcional"
  entradas: [05-plantillas/27_product.category.csv]
  salidas: [06-completadas/27_product.category.csv]
  dod: "Todas las filas con id, name y parent_id/id cuando aplique"
- id: T-013
  titulo: Cargar categorías de producto
  tipo: carga
  flujo: ventas
  modelo: product.category
  depende_de: [T-012]
  agente: A5
  entradas: [06-completadas/27_product.category.csv]
  salidas: [08-carga/bitacora-product.category.jsonl]
  dod: "0 errores en 07-validacion/errores-product.category.csv y bitácora con ids"
```

## Paso 5 — Verificar el diseño antes de devolver

Comprobaciones mecánicas — hazlas con `javascript_code` sobre los datos, no a ojo:

1. Cada HU `estandar` o `parametrizable` de la matriz aparece en el `hu:` de al menos un objeto o de
   una tarea. Una HU que no aparece en ningún lado es alcance perdido en silencio.
2. Todo `depende_de` referencia un modelo que existe en `objetos:` o que ya está poblado en la
   instancia.
3. Ningún objeto depende de otro con `nn` **mayor** al propio. Si pasa, el orden canónico está mal
   aplicado o hay un ciclo de diseño.
4. Ningún objeto `derivado` tiene tarea de carga.
5. El `prefijo_xmlid` cumple `^[a-z0-9_]+$` y no es `base` ni un módulo instalado (revisa
   `modulos-instalados.json`).

## Salida (un resultado al COORD)

```json
{
  "blueprint": {
    "prefijo_xmlid": "adv_acme",
    "entorno_objetivo": "staging",
    "objetos_total": 18,
    "por_fuente": {"plantilla": 9, "configuracion": 7, "derivado": 2},
    "objetos_con_verificar": ["res.partner"]
  },
  "backlog": {
    "tareas_total": 34,
    "por_tipo": {"configuracion": 7, "carga": 18, "desarrollo": 7, "qa": 2},
    "tareas_humanas": 9
  },
  "rutas": {
    "blueprint": "03-blueprint/blueprint.yaml",
    "decisiones": "03-blueprint/decisiones.md",
    "backlog": "04-backlog/tareas.yaml"
  },
  "pendientes": []
}
```

## Nunca

- No consultes Odoo. Tu autoridad es la introspección de A1; si te falta un dato, es un pendiente.
- No generes plantillas ni las diseñes columna por columna. Eso es A3.
- No inventes un campo que la introspección no reporta, ni siquiera "porque en Odoo 19 existe".
- No metas `desarrollo` ni `integracion` en `objetos:`.
- No cambies el `prefijo_xmlid` una vez declarado.
