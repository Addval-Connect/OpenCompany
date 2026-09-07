---
name: sandbox-de-codigo-en-opencompany
description: >-
  Contrato exacto de los tres sandboxes de código (sandboxed_python, javascript_code, python_code):
  qué módulos existen, cómo entra un archivo al sandbox y cómo sale el resultado. Lee esto ANTES de
  escribir código que toque un archivo del workspace; contiene el parser CSV verificado.
allowed-tools: sandboxed_python javascript_code python_code
metadata:
  agente: TODOS
  tipo: DET
  prioridad: P0
  uso: referencia_compartida
  icon: "🧮"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Ejecutar código en OpenCompany

Los tres ejecutores son **sandboxes cerrados**. Ninguno tiene `require`, ninguno tiene acceso libre a
`import`, y ninguno lee un archivo por el simple hecho de que le pases una ruta. Casi todo el tiempo
perdido en este proyecto viene de asumir que sí.

**La regla que resuelve el 90% de los casos:**

| Lo que necesitas | La tool | Por qué |
|---|---|---|
| Convertir un **archivo** del workspace en estructura (CSV → `fields`+`data`) | **`sandboxed_python`** con `capabilities: ["workspace_read"]` | Es el único sandbox que puede **abrir el archivo**. |
| Aritmética / comparación sobre datos **que ya están en tu contexto** | `javascript_code` | No necesita tocar disco. |
| Escribir un archivo derivado desde el sandbox | `sandboxed_python` con `["workspace_write"]` | — |

## `sandboxed_python` (nodo `montyExecutor`) — el que lee archivos

Python real, intérprete Monty (Rust), con límites de tiempo y memoria **efectivamente aplicados**.

- **`capabilities: ["workspace_read"]` monta el workspace del workflow en `/workspace`.** La ruta
  `06-completadas/20_res.partner.csv` del contrato se abre como
  `/workspace/06-completadas/20_res.partner.csv`.
- **Abre y cierra a mano.** `with` no está soportado:

  ```python
  f = open("/workspace/06-completadas/20_res.partner.csv")
  raw = f.read()
  f.close()
  ```

- **El resultado es la ÚLTIMA EXPRESIÓN**, no una variable `output`. Una última línea `output` que no
  sea una expresión devuelve `None` y parece que el sandbox falló. Termina con la expresión, o con
  `json.dumps(...)`.
- `import math`, `import json`, `import re` sí. `import csv`, `import os`, `import collections`,
  `import random` **no** — y `csv` es justo el que ibas a pedir. Usa el parser de abajo.
- Sin `class`, sin generadores/`yield`, sin `with`, sin `match`.
- `print(...)` se captura en `console_output`; úsalo para depurar, no para devolver el resultado.

## `javascript_code` (nodo `javascriptExecutor`) — sin `require`, sin disco

El sandbox expone **solo** esto: `console`, `input_data`, `output`, `JSON`, `Math`, `Date`, `Array`,
`Object`, `String`, `Number`, `Boolean`, `RegExp`, `Map`, `Set`, `Promise`, `setTimeout` /
`setInterval` / `clearTimeout` / `clearInterval`.

**No existen `require`, `import`, `fs`, `path`, `Buffer`, `process`, `TextDecoder` ni `fetch`.**
`require('fs')` falla con `require is not defined`, y ese error no te dice qué hacer en su lugar: no
hay paquete que instalar ni ruta alternativa. **No lo reintentes con otro módulo.**

- El resultado se devuelve asignando **`output`** (al revés que `sandboxed_python`).
- `input_data` trae las salidas de nodos conectados aguas arriba. **Cuando te llaman como tool de un
  agente, viene esencialmente vacío**: no es un canal para pasarle un archivo.
- Consecuencia: para que `javascript_code` procese datos, los datos tienen que estar **escritos
  literalmente dentro del `code`**. Para un CSV de cientos de filas eso significa transcribir el
  archivo a mano — costoso y con riesgo de alterar valores. Para eso está `sandboxed_python`.

## `python_code` (nodo `pythonExecutor`) — sin `import`, y sin `csv`

CPython con builtins restringidos. **`import` está prohibido por completo**; hay nombres
pre-inyectados que se usan directo: `math`, `json`, `datetime`, `timedelta`, `re`, `random`,
`Counter`, `defaultdict`. Escribe `json.dumps(x)`, nunca `import json`.

No hay `csv`, no hay `open` útil, no hay red. Si el error dice "does not allow `import` statements",
la respuesta **no** es cambiar de módulo: es cambiar de tool.

## Parser CSV (verificado, cópialo tal cual)

Para `sandboxed_python` con `["workspace_read"]`. Respeta comillas, comas dentro de comillas y
comillas escapadas (`""`) — los tres casos que una transcripción a ojo corrompe en silencio:

```python
import json

def parse_csv(raw):
    rows = []
    row = []
    cell = ""
    inq = False
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if inq:
            if ch == '"':
                if i + 1 < n and raw[i + 1] == '"':
                    cell = cell + '"'
                    i = i + 2
                    continue
                inq = False
                i = i + 1
                continue
            cell = cell + ch
            i = i + 1
            continue
        if ch == '"':
            inq = True
            i = i + 1
            continue
        if ch == ',':
            row.append(cell)
            cell = ""
            i = i + 1
            continue
        if ch == '\n':
            row.append(cell)
            rows.append(row)
            row = []
            cell = ""
            i = i + 1
            continue
        if ch == '\r':
            i = i + 1
            continue
        cell = cell + ch
        i = i + 1
    if cell != "" or len(row) > 0:
        row.append(cell)
        rows.append(row)
    return rows

f = open("/workspace/06-completadas/20_res.partner.csv")
raw = f.read()
f.close()
rows = parse_csv(raw)
fields = rows[0]
data = rows[1:]
json.dumps({"fields": fields, "data": data, "filas": len(data)})
```

Devuelve exactamente la forma que `load()` espera: `fields` es la cabecera, `data` son listas de
strings, celda vacía = `""`. Trocea con `data[0:300]`, `data[300:600]`, … dentro del mismo llamado y
devuelve solo el lote que vas a cargar, para no arrastrar el archivo completo por el historial.

Si el archivo tiene una fila final vacía, el parser no la emite. Compara siempre `filas` contra las
filas que esperabas del archivo antes de cargar.

## YAML y JSON del proyecto

**No existe `yaml` en ningún sandbox.** `blueprint.yaml`, `casos.yaml` y los `.meta.json` son
archivos chicos: léelos con `file_read` y razona sobre el texto directamente. No intentes parsearlos
en un sandbox — `import yaml` no está y no hay reemplazo.

Un `.json` sí se parsea en `sandboxed_python` con `json.loads(...)` si te conviene tenerlo
estructurado, pero para un sidecar de 20 líneas `file_read` basta y cuesta menos.

## Nunca

- No uses `require(...)` en `javascript_code`, ni `import` en `python_code`. No hay variante que
  funcione; cambia de tool.
- No pidas `capabilities` que no necesitas: `workspace_read` para leer, `workspace_write` solo si
  escribes.
- No devuelvas el resultado con `output = ...` en `sandboxed_python` (es la última expresión) ni con
  una última expresión en `javascript_code` (es `output = ...`).
- No transcribas un CSV dentro del `code` para que `javascript_code` lo procese: usa
  `sandboxed_python` con `workspace_read`.
- No conviertas un archivo a `fields`/`data` "a mano" leyendo el `file_read` y escribiendo el JSON tú:
  es exactamente donde se pierden los valores con comas y comillas.
