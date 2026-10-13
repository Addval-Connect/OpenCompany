---
name: "orquestar-sesion-cartola"
description: "No lleves un enum de estados propio (RECIBIDA, NORMALIZADA, etc.) ni un"
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"
  icon: "🧭"
  color: "#6366F1"

---

# Orquestar sesión de cartola

## El Task Manager ES la máquina de estados (no inventes una)

No lleves un enum de estados propio (`RECIBIDA`, `NORMALIZADA`, etc.) ni un
objeto `sesion_importacion` en memoria. El estado de avance **es** el estado de
las TeamTasks que creas con `task_manager`: `queued → running → submitted →
accepted`. Tú solo decides **quién ejecuta el siguiente paso** según el
resultado del último worker; el Task Manager persiste el resto.

- No mantengas ni cites campos como `estado`, `estado_previo`, `agente_actual`.
- No busques archivos de estados (no existe `estados.md` ni similar).
- Para saber en qué punto va la sesión, usa `task_manager(operation="list_tasks")`
  y lee el resultado de la última task `submitted`/`accepted`.

## La secuencia normal

Pipeline lineal. Tras aceptar el resultado de un worker, delega el siguiente:

```
(cartola nueva) → A1 Procesa Archivos → A2 Interpreta Cartola
                → A3 Consolida Información → A4 Importa a Odoo → fin
```

Delegar = `task_manager(operation="assign_task", assignee_node_id=<worker>,
title=..., mission=..., context={...}, acceptance_criteria={...})`. El COORD
NUNCA llama `delegate_to_*` directamente. En `context` pasa el `sesion_id` (la
carpeta `sesiones/<sesion_id>/`), las rutas de artefactos vigentes y un resumen
de lo conocido. Refleja el avance con **writeTodos** (un ítem por worker) y deja
constancia en **console**.

## Cuándo NO avanzas al siguiente worker

Decisiones sobre el **resultado del último TeamTask**, no estados de un enum.
Cuando el resultado indica una de estas, detente y consulta al usuario por chat:

- **A1 reporta duplicado** (`duplicado: true`): informa y NO sigas. Si el
  usuario pide procesarla igual, re-`assign_task` a A1 con
  `context.forzar_reproceso: true`.
- **A1 reporta sin capa de texto legible** y la visión falló: consulta al
  usuario (hace falta mejor copia / OCR previo).
- **A2 no identificó el custodio** o no recuperó su diccionario: consulta al
  usuario (revisión humana íntegra).
- **A3 devolvió pendientes** (`pendientes[]` no vacío): consolida el lote y
  preséntalo (ver `consultar-al-usuario-en-lote`), que lo manda por correo como
  `reply` al hilo de la cartola. La respuesta te llega después, como un disparo
  nuevo de **Outlook Mail Receive** — reconócela por `conversation_id`: si
  coincide con el hilo de una sesión en `REQUIERE_USUARIO`, es la respuesta al
  lote (re-`assign_task` al worker de `estado_previo` con las respuestas en
  `context`); si no coincide con ningún hilo abierto, es una cartola nueva y
  entra por el camino normal (paso 1).
- **A4 reportó líneas en error** (carga parcial): preséntalas como casos de
  borde; no reintentes ciegamente.

En cualquier otro caso (el worker terminó bien y hay insumo para el siguiente
paso), delega inmediatamente al siguiente worker sin esperar al usuario.

## Reglas de responsabilidad

- **A2 nunca consulta Odoo.** Si necesita saber si un instrumento existe, marca
  confianza y sigue — el cruce contra maestros (javascriptExecutor + JSON-RPC)
  es exclusivo de A3.
- **A3 nunca reinterpreta la cartola.** Si sospecha mala extracción, levanta un
  pendiente; no corrige el JSON él mismo.
- **A4 nunca decide de negocio.** Si falta un producto o serie en Odoo, es un
  pendiente que vuelve al usuario; no lo crea por su cuenta.
- **Cartola consolidada** (ej. Ameris): antes de delegar a A4, verifica que A3
  no dejó abierto un pendiente de doble contabilización entre custodios.

## Procedimiento

1. Cartola nueva → `assign_task` a A1 con `sesion_id` y ruta del PDF en `context`.
2. Worker devolvió el control (`taskTrigger` o `submitted` en `list_tasks`): lee
   su resultado. Si cae en un caso de "NO avanzas", consulta al usuario. Si no,
   `assign_task` al siguiente worker con el resultado/rutas del paso anterior.
3. Para confirmar un dato (ej. si el JSON trae ≥1 movimiento), léelo del
   workspace con **fileRead**; no lo supongas.
4. Marca el avance con `writeTodos` y registra cada delegación en `console`.
5. Al terminar (A4 completó o la sesión requiere usuario), resume: custodio, nº
   de movimientos, resultado de carga y pendientes abiertos.

## Casos de borde

- **Dos resultados casi simultáneos para la misma sesión**: procesa en orden de
  llegada; no delegues sobre un resultado más antiguo que el ya consolidado.
- **No sabes qué paso sigue** (resultado ambiguo): no adivines. Registra la duda
  en `console` y consulta al usuario.
