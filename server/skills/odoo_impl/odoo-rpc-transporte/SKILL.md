---
name: odoo-rpc-transporte
description: Transporte JSON-RPC y load() — la herramienta odoo_jsonrpc, sus métodos por rol y la economía de llamadas.
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "1.0"
  category: compartidos

---

# Odoo RPC: transporte y `load()`

Cómo se habla con Odoo desde `odoo_jsonrpc`. Lo cargan los agentes de flujo (solo lectura) y CARGA (lectura y escritura). La taxonomía de errores está en `taxonomia-errores-odoo`, el bucle de corrección en `bucle-de-correccion`, los ajustes en `ajustes-de-aplicacion` y las reglas de entorno en `entornos-y-seguridad`.

## Qué puede cada rol

| Rol | Métodos |
|---|---|
| Agentes de flujo | `search_read`, `read`, `search`, `search_count`, `fields_get`; `call` solo con métodos de lectura (`default_get`) |
| CARGA | Todo lo anterior, más `load`, `create`, `write`, `unlink` y `call` de acciones |

Un agente de flujo nunca llama a `load`, `create`, `write` ni `unlink`, aunque su credencial lo permita.

## La herramienta

Toda llamada a Odoo pasa por `odoo_jsonrpc`.

```
model        "res.partner", "product.template", "ir.model.data", …
method       search_read | read | search | search_count | create | write | unlink | fields_get | load | call
method_name  obligatorio cuando method="call"
domain       para search / search_read / search_count
fields       para read / search_read (pide SIEMPRE el mínimo); para load, la cabecera
ids          obligatorio para read / write / unlink
values       obligatorio para create / write; para load, las filas
limit        ≤ 1000    offset, order
args, kwargs posicionales / nombrados cuando method="call"
```

Devuelve `{ok: true, result: …}` o `{ok: false, error: {...}}`. El esquema es cerrado: un argumento inventado se rechaza antes de salir a la red.

### Override de instancia por llamada (opcional, todo o nada)

Por defecto la llamada corre contra la instancia configurada en el nodo. Para apuntar a **otra** instancia, pasa la conexión completa en la llamada: `host` (sin esquema ni ruta), `db`, `username` y `api_key` — **los cuatro juntos o ninguno**; un override parcial se rechaza antes de salir a la red, porque emparejaría un host con las credenciales de otra instancia. Nunca mezcles un override con las credenciales guardadas del nodo. Usos legítimos: credenciales entregadas explícitamente por el consultor en la sesión y verificación de instancia; para el trabajo planificado del proyecto manda `entornos-y-seguridad`.

## Transporte legacy, no JSON-2

Odoo 19 introdujo la API JSON-2 y anunció la eliminación de `/xmlrpc`, `/xmlrpc/2` y `/jsonrpc` para Odoo 20. La herramienta habla el transporte antiguo (`/jsonrpc`, handshake `common.login` → `object.execute_kw`) por decisión consciente: Odoo 19 lo sigue soportando y el modelo de objetos es el mismo. Todo lo que se dice de modelos, campos, cabeceras y `load()` aplica sin cambios. Cuando Odoo 20 retire `/jsonrpc`, el cambio es en el nodo, no en estos skills.

Consecuencias para ti:

- Los errores no llegan como códigos HTTP semánticos, sino dentro del `error` del JSON-RPC. Un registro inexistente y una regla de negocio violada llegan con la misma forma: clasifica por el **texto** (`taxonomia-errores-odoo`).
- No hay endpoint por modelo: siempre `model` + `method`.
- Cualquier método del ORM que no esté en la lista corta se alcanza con `method="call"` + `method_name`.

## `load()` (solo CARGA)

`load(fields, data)` es el método del importador nativo: respeta las cabeceras `<campo>/id`, resuelve xmlids y **actualiza** en vez de duplicar cuando el `id` ya existe.

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

`fields` es la cabecera y `values` son las filas. La forma antigua (`call` + `method_name="load"` + `args`) funciona pero no la uses: la directa valida que cada fila tenga tantos valores como cabeceras y te dice qué fila está mal antes de tocar Odoo.

Reglas duras:

- **`create` no es alternativa a `load` para cargar un archivo.** `create` no registra el xmlid: la corrida siguiente no reconoce el registro y lo duplica. Si intentas registrarlo insertando en `ir.model.data`, la segunda corrida muere con `duplicate key value violates unique constraint "ir_model_data_module_name_uniq_index"`. Eso no es un problema de datos: es haber usado `create`. `create` queda para el objeto único de configuración que no lleva xmlid.
- **`"id"` debe estar entre las cabeceras.** Sin esa columna la carga duplica en cada corrida. Si no está, no llames: es `E100`.
- **La forma de una columna relacional la decide el valor, no el campo.** Valor `modulo.nombre` (`base.cl`) → cabecera `campo/id`, búsqueda por xmlid. Valor legible (`CPO/Stock`, `Insumos y Materiales`) → cabecera `campo` a secas, búsqueda por nombre. `/id` sobre un valor que no es xmlid devuelve `No matching record found for external id 'CPO/Stock'`: parece referencia faltante y es una cabecera equivocada.
- `data` son **listas de strings**, en el mismo orden que `fields`. Celda vacía = `""`, no `null`.
- Lotes de 200 a 500 filas. Más grande, un error obliga a repetir todo; más chico, multiplica las llamadas.

**Respuesta:** `{"ids": [...], "messages": [...]}`. `messages` no vacío significa que algo falló, aunque `ok` sea `true` y `ids` traiga elementos. Cada mensaje trae `type`, `message`, y a menudo `record` (índice de fila 0-based **dentro del lote**) y `field`. Un `load` con mensajes de tipo `error` **no escribió nada** de ese lote: es transaccional. Lee siempre `messages` antes de declarar éxito.

## Lecturas que se usan siempre

```
# ¿Existe este xmlid?
model="ir.model.data", method="search_read",
domain=[["module","=","adv_acme"],["name","=","partner_761234567"]],
fields=["module","name","model","res_id"]

# ¿Qué campos tiene realmente este modelo?  (la autoridad, no la memoria)
model="res.partner", method="fields_get", args=[[]],
kwargs={"attributes": ["type","required","selection","relation","string"]}

# ¿Está instalado este módulo?
model="ir.module.module", method="search_read",
domain=[["name","in",["l10n_cl","l10n_cl_edi"]]], fields=["name","state"]

# Versión de la instancia
model="ir.module.module", method="search_read",
domain=[["name","=","base"]], fields=["latest_version"]
```

`fields_get` es la **única** autoridad sobre qué campos existen. Ninguna lista escrita en un skill lo es. Todo lo marcado `[VERIFICAR]` se confirma contra la instancia y el resultado se guarda en `02-instancia/introspeccion-<flujo>.json`.

## Métodos que no se invocan por RPC (`E520`)

Odoo bloquea la invocación remota de los métodos administrativos de los modelos `ir.*`:

```
"error": "Odoo error: The method 'ir.module.module.get_module_info' cannot be called remotely."
```

Lo mismo aplica a `button_immediate_install`, `button_upgrade`, `button_uninstall` y a los métodos de `ir.model` / `ir.model.fields` que crean o alteran modelos y campos. **No es un problema de permisos y no se arregla con otra credencial ni con otro host**: la instancia no expone esos métodos por este transporte.

- Lo que sí funciona sobre `ir.*` es la lectura (`search_read`, `read`, `fields_get`): con eso verificas el estado de un módulo, y ahí se acaba tu alcance.
- **Los módulos los instala una persona, a mano, desde la UI de Odoo.** El agente verifica y reporta; no instala ni lo intenta "por si acaso".
- Un `E520` no se reintenta nunca, con ningún argumento. Si lo que necesitabas era leer, usa la vía de lectura; si era una acción administrativa, es trabajo humano: definición abierta con el nombre exacto del módulo o campo.
- La lista de módulos requeridos se verifica **al principio**, no se descubre a la mitad.

## Economía de llamadas

Cada resultado de herramienta queda en el historial y se re-lee en cada iteración siguiente: el costo crece de forma casi cuadrática.

- **`fields` mínimo, siempre.** Un `search_read` sin `fields` arrastra decenas de columnas por fila el resto del turno.
- **En bloque, no por fila.** Un `search_read` con `["name","in",[...]]`, no N llamadas; un `load` de 300 filas, no 300 `create`.
- **Cachea a archivo.** Introspección y maestros van a `02-instancia/*.json`; los pasos siguientes leen el archivo, no repiten la consulta.
- **`limit` explícito en toda exploración.** Sin él, una tabla grande inunda el contexto.
