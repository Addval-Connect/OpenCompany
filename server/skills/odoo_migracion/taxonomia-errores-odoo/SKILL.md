---
name: taxonomia-errores-odoo
description: Definición única de los códigos de error E1xx a E5xx — clasificación por texto y quién corrige cada uno.
allowed-tools: odoo_jsonrpc
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# Taxonomía de errores

Clasificación común del Transformador y el Auditor (validación) y de CARGA. **Es la única definición de los códigos**: los demás skills los citan, no los repiten. El código determina **quién** corrige y **qué se detiene**.

## Códigos

| Código | Qué es | Corrige | Efecto |
|---|---|---|---|
| `E100` | Estructura del archivo: falta la columna `id`, cabecera desconocida, CSV ilegible, sidecar ausente | Agente | **Detiene el archivo completo** |
| `E110` | **Campo inexistente en el modelo**: `Invalid field 'X' in 'Y'`, `Invalid field Y.X in condition (...)` | Agente, con `fields_get` | Reintenta **una** vez con el campo verificado |
| `E200` | Campo obligatorio vacío | Consultor | Fila rechazada |
| `E210` | Formato inválido: fecha, número, booleano, identificador con dígito verificador incorrecto | Consultor | Fila rechazada |
| `E220` | Valor fuera del catálogo (`selection`, `catalogos` del sidecar) | Consultor | Fila rechazada |
| `E300` | Referencia no resuelta: el xmlid de un `<campo>/id` no existe | Consultor o agente según el caso | En validación: fila rechazada. En carga: el archivo se **difiere** si lo produce otro archivo del plan |
| `E310` | xmlid duplicado dentro del archivo | Consultor | Ambas filas rechazadas |
| `E320` | Dependencia fuera de orden: referencia a un registro que, por el orden de las fases de carga, se carga después | Agente | **Detiene el archivo completo** (en carga se reordena el plan, una vez) |
| `E400` | Regla de negocio de Odoo (constraint, validación del modelo) | Consultor con criterio funcional | Fila rechazada |
| `E500` | Error de instancia: caída, timeout, permisos, login | Agente / infraestructura | **Detiene la carga completa** |
| `E510` | **Modelo o módulo ausente**: `Object <modelo> doesn't exist`, `Model not found`, un campo que solo existe con un módulo instalado | Persona, instalando el módulo a mano | **Detiene los archivos de ese módulo** |
| `E520` | **Método no invocable remotamente**: `The method '<X>' cannot be called remotely` | Nadie por RPC: es acción manual | No se reintenta |

`E100` y `E320` detienen el archivo entero; `E500` detiene la carga completa. No son fallas de fila: significan que el archivo o la instancia no están en condiciones, y seguir produce un estado a medias imposible de auditar. Todo lo demás se reporta por fila y el archivo continúa, para que el consultor reciba **todos** los problemas en una pasada y no de uno en uno.

`E510` no es un error de instancia aunque comparta la familia 5xx: la instancia está sana, le falta un módulo.

## Clasificar por el texto del mensaje

Los errores llegan todos con la misma forma (ver `odoo-rpc-transporte`), así que se clasifican por lo que dicen:

| El mensaje dice | Es | Acción |
|---|---|---|
| `No matching record found for external id …` | `E300` | ¿Lo produce otro archivo del plan? → difiere. Si no, ver `bucle-de-correccion` |
| …lo mismo, pero el valor **no tiene forma de xmlid** (`CPO/Stock`) | tu error | Cabecera con `/id` de más: quítale el `/id` y Odoo lo busca por nombre |
| `Invalid field 'X' in 'Y'` / `Invalid field Y.X in condition (...)` | `E110` | `fields_get`, corrige y reintenta una vez |
| Cabecera desconocida que `fields_get` tampoco explica | `E100` | Defecto de plantilla |
| `Value 'X' not found in selection field` | `E220` | Resuelve con las claves de `fields_get` |
| `Object … doesn't exist` / un campo que solo trae un módulo | `E510` | Verifica el módulo; no lo instales |
| `The method '…' cannot be called remotely` | `E520` | No hay reintento |
| `duplicate key … "ir_model_data_module_name_uniq_index"` | tu error | Usaste `create` donde va `load` |
| `already exists` / `duplicate key` en otro unique | `E400` o recarga | Ver `bucle-de-correccion` |
| Texto de un `_constraint` o de un `ValidationError` | `E400` | Regla de negocio |
| `Access Denied` / `not allowed to` | `E500` | Permisos del usuario de integración: detén |
| Timeout, 502/503, conexión cerrada | `E500` | Verifica antes de reintentar |
| `uid is false` / login | `E500` | Credenciales del nodo. **No pruebes otro host** |

Si no encaja en ninguna, es `E400` con criterio funcional desconocido: definición con el mensaje literal. **Nunca resumas ni parafrasees un mensaje de error de Odoo al escalarlo**: el texto exacto es lo que un consultor funcional reconoce.

**Clasifica por lo que Odoo rechaza, no por lo que a ti te parece mal.** Un dato que la instancia aceptó no es un error, aunque contradiga una regla que tú conoces: la validación de la localización puede estar desactivada, el módulo que la impone puede no estar instalado, o el campo puede ser libre en esta versión. Nunca rechaces una fila con una comprobación tuya que Odoo no aplica: bloquea una carga correcta y es indistinguible de un error real en el informe.

## Formato de un error reportado

Una fila de `07-auditoria/errores-<lote>.csv`:

```csv
codigo,archivo,fila,columna,valor,mensaje,corrige
E210,res.partner.csv,14,vat,76.123.456-8,"DV incorrecto: para 76.123.456 el DV es 7",consultor
E300,product.template.csv,7,categ_id/id,adv_acme.categ_insumo,"xmlid no existe; ¿adv_acme.categ_insumos?",consultor
```

Un mensaje sin `archivo` + `fila` + `columna` es inútil para quien corrige. Cuando el valor erróneo se parece a uno válido, **sugiere el candidato**: es la diferencia entre una corrección de un minuto y una de media hora.

Un `record` de un `load` es un índice 0-based **dentro del lote**: tradúcelo a número de fila del CSV antes de reportar o apartar.
