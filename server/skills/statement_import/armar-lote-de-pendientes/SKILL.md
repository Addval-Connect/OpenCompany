---
name: "armar-lote-de-pendientes"
description: "Preguntar línea por línea agota al equipo Tax. Agrupar por motivo, con contexto"
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"

---

# Armar lote de pendientes

Preguntar línea por línea agota al equipo Tax. Agrupar por motivo, con contexto
suficiente para responder sin reabrir la cartola, hace sostenible la revisión.

## Dónde viven los pendientes

Cada skill de A3 que topa con ambigüedad NO decide: devuelve su pendiente
estructurado en el resultado de su tarea (`task_manager`). Esta skill los
recolecta desde el JSON de la cartola (leído con **fileRead**, `file_read`) y
desde los resultados de tareas acumulados por el COORD, y escribe el lote a
`cartola/pendientes.json` con **fileModify** (`file_modify`). Usa **writeTodos**
(`write_todos`) para el avance del armado cuando haya muchos motivos.

El envío NO lo hace esta skill: el lote vuelve al COORD, que lo surface al
usuario por chat (chatTrigger). Las respuestas regresan por chat y el COORD
re-asigna la skill afectada con las respuestas en `context` (ver
`aplicar-respuestas-al-json`).

## Procedimiento

1. Recolecta todos los pendientes de la sesión: cliente ambiguo, instrumento
   sin match, disminución de capital, reinversión, código no documentado,
   inconsistencia de totales, duplicado no resuelto entre custodios.
2. Agrupa por `motivo`, no por orden de aparición.
3. Redacta cada pregunta para responder sin abrir el PDF: cita página, línea,
   monto y fecha.
4. Con opciones cerradas conocidas, ofrécelas en el mismo orden que el
   diccionario del custodio, sin sugerir. Ej. (Ameris, código no documentado):
   "¿A qué concepto corresponde el código '`<código>`': dividendo, interés,
   devolución de capital u otro?"
5. Para disminución de capital, usa siempre el texto fijo `disminucion_capital`
   del diccionario del custodio; no lo reformules (que el equipo reconozca el
   patrón).
6. Para el caso espejado entre cuentas del mismo titular (documentado en
   Banchile entre "CUENTA 0" y "CUENTA 700"), usa motivo `otro` preguntando si
   es traspaso interno o venta+compra a cargar por separado.
7. Ordena: primero los pendientes bloqueantes de sesión (ej. `cliente_ambiguo`),
   luego los que afectan líneas específicas.

## Salida

Escrita a `cartola/pendientes.json` y retornada al COORD:

```json
{
  "pendientes": [
    {
      "id": "P-001",
      "origen": "A3",
      "motivo": "codigo_no_documentado",
      "pregunta": "Cartola Ameris julio 2024, página 4, línea 'REUS CFIAMG3R-E' por $XXX. ¿A qué concepto corresponde el código 'REUS': dividendo, interés, devolución de capital u otro?",
      "opciones": ["dividendo", "interes", "devolucion_de_capital", "otro"],
      "referencia": { "movimiento_idx": 12, "campo": "movimiento" },
      "respuesta": null
    }
  ],
  "requiere_usuario": true
}
```

## Casos de borde

- **Varios motivos sobre la misma línea** (instrumento sin match Y monto
  inconsistente): consolídalos en un solo ítem con ambas preguntas; no dupliques
  la referencia.
- **Sesión con un único pendiente**: igual pasa por esta skill para mantener
  formato uniforme.
