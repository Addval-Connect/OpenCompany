---
name: introspeccion-odoo-solo-lectura
description: Protocolo de lectura de la instancia con odoo_jsonrpc para los agentes de flujo — escribir en Odoo es exclusivo de CARGA.
allowed-tools: odoo_jsonrpc
metadata:
  author: opencompany
  version: "1.0"
  category: flujos

---

# Introspección de Odoo (solo lectura)

Cómo los agentes de flujo leen la instancia con `odoo_jsonrpc`. Los usan las misiones `analisis`, `cerrar G1` y `plantillas`. **Escribir en Odoo es trabajo exclusivo de CARGA**: aquí solo se lee. El transporte, `load()` y la taxonomía de errores están en `odoo-rpc-transporte`; este skill fija el protocolo de lectura.

## Qué puedes llamar

| Permitido | Prohibido |
|---|---|
| `search_read`, `read`, `search`, `search_count`, `fields_get` | `create`, `write`, `unlink`, `load` |
| `call` solo con métodos de lectura (`default_get`) | `call` con cualquier método que escriba o instale (`execute`, `button_*`, `try_loading`) |

Si una llamada devuelve `cannot be called remotely` (`E520`), no la reintentes con ningún argumento: si lo que necesitabas era leer, usa la vía de lectura; si era una acción, es trabajo humano y va como definición abierta. Un módulo ausente (`E510`) no lo instalas: lo reportas. `Access Denied`, login o timeout repetido (`E500`) detienen tu misión con una definición `otro`; nunca pruebes otro host ni otra credencial.

## Economía de llamadas

Cada resultado queda en tu historial y se re-lee en cada iteración, así que el costo crece rápido.

- `fields` mínimo siempre; `limit` explícito siempre.
- En bloque: un `search_read` con `["name","in",[...]]`, no una llamada por fila.
- Cachea a archivo: lo introspectado va a `02-instancia/introspeccion-<flujo>.json` y los pasos siguientes lo leen con `data`.

## Protocolo

1. **Entorno.** Lee `03-blueprint/proyecto.yaml` → `entorno_objetivo`, `odoo_version`. Introspecciona solo ese entorno.
2. **Módulos.** Un `search_read` de `ir.module.module` con los módulos que tus historias y tu skill de dominio requieren (`fields=["name","state"]`). Todo estado distinto de `installed` (incluidos `to install` y `to upgrade`) es módulo faltante.
3. **Modelos y campos.** `fields_get` por cada modelo clave de tu mapa de dominio, con `attributes: ["type","required","selection","relation","string"]`. **`fields_get` es la única autoridad sobre qué campos existen**: ninguna lista escrita en un skill lo es.
4. **Catálogos.** Las claves de cada `selection` salen de `fields_get`; las etiquetas, con `context: {"lang": "en_US"}` si la instancia está traducida y el valor viene en inglés. Estas claves alimentan el `catalogos` del `.meta.json`.
5. **Ajustes.** `default_get` de `res.config.settings` con los `group_*` que tu dominio necesita, para saber qué está encendido. No los enciendas.
6. **Lo que ya existe.** `search_count` y muestras mínimas de lo que la localización o la instancia ya crearon (plan de cuentas, impuestos, diarios, bodegas). Es lo que evita plantillar un objeto que ya está.
7. **xmlids nativos.** Un `search_read` de `ir.model.data` por los xmlids que tu diseño va a referenciar (`base.*`, `uom.*`, los que el skill de localización mencione). El nombre exacto se confirma aquí, nunca de memoria.
8. **Hechos de la instancia.** Lee `08-carga/capacidades-instancia.json` si existe (`metodos_bloqueados`, `remapeos_confirmados`, `xmlids_resueltos`, `modulos`…). Es memoria de esta instancia; si contradice lo que Odoo responde ahora, gana Odoo.

## Archivo de salida

`02-instancia/introspeccion-<flujo>.json`:

```json
{
  "flujo": "financiero",
  "version": 1,
  "introspeccion_fecha": "<iso8601>",
  "entorno": "staging",
  "odoo_version": "19.0",
  "confianza": "alta",
  "modulos": {"<modulo>": "installed"},
  "modulos_faltantes": ["<modulo>"],
  "modelos": {
    "<modelo>": {
      "existe": true,
      "campos": {"<campo>": {"type": "char", "required": true, "relation": null}},
      "selecciones": {"<campo>": ["<clave>", "<clave>"]}
    }
  },
  "ajustes": {"<group_algo>": false},
  "preexistente": {"<modelo>": {"cantidad": 0}},
  "xmlids_nativos": {"<modulo.nombre>": true},
  "verificar": [{"modelo": "<modelo>", "campo": "<campo>", "motivo": "no aparece en fields_get"}]
}
```

**`confianza`**: `alta` = introspeccionaste todos tus modelos en esta misión; `media` = reutilizas una introspección anterior sin vencer; `baja` = no pudiste acceder a la instancia y trabajas con el skill de dominio como hipótesis. Con `baja`, todo lo que dependa de un campo queda `[VERIFICAR]` y es una definición abierta.

## Marcar `[VERIFICAR]`

Todo campo, modelo o xmlid que tu diseño necesita y que **no** apareció en la introspección va a `verificar` con su motivo, y de ahí a una definición de G1: omitir la columna, instalar el módulo que lo trae, o usar el campo alternativo. **Nunca pruebes un segundo nombre a ojo ni escribas el dato en un campo "parecido".** Si el dato pertenece a otro modelo (la compañía delega su contacto en `partner_id`), anótalo y busca ahí.

## Vigencia

La introspección vence cuando: pasa mucho tiempo, cambia la versión de Odoo, o una respuesta de G1 indica que instalaron un módulo o agregaron un campo. En ese caso `cerrar G1` re-introspecciona esos modelos, incrementa `version` y las plantillas derivadas quedan vencidas (`basado_en`).

## Nunca

- Escribir en Odoo, ni "solo para probar".
- Dar por existente un campo que no viste en `fields_get`.
- Copiar a tu archivo datos pesados (tablas completas): guarda conteos y las muestras mínimas que el diseño usa.
- Usar un `id` numérico como referencia: solo xmlids.
