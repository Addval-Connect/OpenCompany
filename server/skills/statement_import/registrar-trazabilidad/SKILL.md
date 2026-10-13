---
name: "registrar-trazabilidad"
description: "Ante \"¿por qué este movimiento se cargó con esta cantidad, cliente y clasificación?\", la respuesta"
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"
  icon: "🧾"
  color: "#6366F1"

---

# Registrar trazabilidad

Ante "¿por qué este movimiento se cargó con esta cantidad, cliente y clasificación?", la respuesta
debe ser una cadena verificable de eventos, no "porque el modelo lo decidió".

## Dónde vive la traza (dos soportes)

1. **Registro durable de la tarea (TeamTask) — el audit trail de verdad.** Cada delegación crea un
   TeamTask con historial durable (`queued → running → submitted → accepted`, con reintentos,
   reasignaciones y timestamps). El resultado que un worker devuelve es parte de ese registro:
   sobrevive reinicios y es el que se consulta en auditoría.
2. **Nodo `console` + `writeTodos` — visibilidad en vivo.** Cada evento se emite al `console` y, en
   trabajo multi-paso, como checklist con `writeTodos`. La auditoría no depende de él.

Un agente NO reescribe un arreglo JSON compartido: **agrega** eventos (al console y al resultado de
su tarea). El historial es append-only por construcción del TeamTask.

## Cuándo se activa

Después de cualquiera de estas acciones, sin excepción:

- El Coordinador abre un nuevo `assign_task`.
- Se identifica un custodio o se recupera un diccionario (con su versión exacta).
- Se clasifica una línea en uno de los cuatro destinos de extracción.
- Se resuelve un emparejamiento de cliente o instrumento contra Odoo.
- Se calcula un total o fee, o se detecta una inconsistencia.
- Se genera, responde o aplica un pendiente.
- Se inserta, rechaza o reintenta una línea en el Kárdex (`kardex.import.log.create`).
- Se propone un cambio de diccionario (`proponer-actualizacion-diccionario`), y por separado cuando
  se aprueba o rechaza.

## Procedimiento

1. Tras la acción, emite un evento al `console` con timestamp, agente, skill y descripción breve y
   específica. Inclúyelo también en el resultado de la tarea (registro durable).
2. Si involucra una versión de diccionario, cítala (`"aplicado diccionario-ameris-v1 a 12
   movimientos"`), no solo el custodio.
3. Si involucra una decisión humana (respuesta a un pendiente, aprobación de un cambio de
   diccionario), registra quién y cuándo — nunca solo "usuario respondió".
4. Nunca reescribas ni borres un evento emitido. Si algo posterior lo corrige o revierte, emite un
   evento nuevo que lo explique; el historial completo queda visible.
5. Al insertar en el Kárdex, registra el **id entero** devuelto por `kardex.import.log.create`, no el
   campo `name` (literal "..."). La identidad de la carga es ese id; la clave natural es la tripleta
   `(custodian_id, account, kardex_period)`.
6. Cada evento breve pero específico: suficiente para reconstruir la secuencia sin releer el
   `cartola.json`.

## Salida

Eventos emitidos al `console` y acumulados en el resultado de la tarea (el registro durable es el
rastro de auditoría; esto es la proyección legible):

```json
{
  "eventos": [
    { "ts": "2026-08-06T20:11:00Z", "agente": "A2", "skill": "interpreta-cartola", "evento": "custodio=BANCHILE, confianza=alta (pagina 1 via file_read)" },
    { "ts": "2026-08-06T20:15:00Z", "agente": "A3", "skill": "consolida-informacion", "evento": "cliente_id=42 por match de RUT (Odoo search_read), confianza=alta" },
    { "ts": "2026-08-06T21:05:00Z", "agente": "A3", "skill": "aplicar-respuestas-al-json", "evento": "P-001 respondido por usuario:maria.jose, aplicado a cartola.json" },
    { "ts": "2026-08-06T21:10:00Z", "agente": "A4", "skill": "importa-a-odoo", "evento": "kardex.import.log.create ok, log_id=318, 14 lineas, 0 error" }
  ]
}
```

## Casos de borde

- **Acción que falla y se reintenta**: emite ambos eventos — el intento fallido con su motivo y el
  reintento — no sobrescribas el primero. El TeamTask conserva los reintentos por diseño.
- **Alta frecuencia de eventos**: no omitas eventos por volumen. Si la traza en el console molesta,
  es una decisión de infraestructura (paginación, filtrado), no razón para dejar de registrar en el
  resultado durable.
