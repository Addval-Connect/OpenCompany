---
name: jev-decisiones-coordinador
description: Usos de JEV en el Coordinador — filtrar respuestas del consultor con decisiones tipadas; nunca para decidir criterio funcional.
allowed-tools: jev
metadata:
  author: opencompany
  version: "1.0"
  category: coordinador

---

# JEV en el Coordinador

JEV (TypeSafe) devuelve decisiones tipadas con probabilidad y confianza. No genera texto y no razona entre preguntas. Aquí se usa para **filtrar** las respuestas del consultor, nunca para decidir criterio funcional, cerrar un punto de control ni autorizar producción. La mecánica general (contrato de `questions`, tipos, respuesta) está en el skill de plataforma `jev`; este skill fija los usos del proyecto.

## Reglas de uso

- Llamada: `jev(state, questions)`, con `questions` como JSON string. Una llamada por unidad evaluada (una historia, una respuesta de un ítem): las preguntas de una llamada se responden de forma independiente y sobre el mismo `state`.
- **Preguntas atómicas**, una por juicio, con `instructions` completas y opciones mutuamente excluyentes. Combina las respuestas tú.
- `state` es solo material factual (la fila de la historia, la pregunta y la respuesta del consultor), sin tu opinión ni tu sugerencia.
- **Umbrales** (puntos de partida; ajústalos con el log):

| `confidence` | Acción |
|---|---|
| ≥ 0,8 | Actúas |
| 0,5 a 0,8 | Registras y lo confirmas con el consultor en el próximo correo |
| < 0,5 | Va al consultor sin propuesta |

- Para `noul` (probabilidad de sí) fija un umbral por pregunta, indicado abajo.
- Una casi-empate en `probabilities` es "ambigua": no actúes por la etiqueta.
- **Registra cada llamada** en `proyecto/coordinador/jev-log.jsonl`: `{ts, uso, ref, decisions, confidence, accion}`. Es lo que permite ajustar umbrales después.
- **Si `jev` falla o no está disponible:** la clasificación va al consultor sin propuesta; toda respuesta del consultor se trata como ambigua salvo coincidencia exacta con una opción citada por número.

## Clasificación de historias

La clasificación de historias por flujo la hace D0 al producir `propuesta-historias.csv` (skill `jev-decisiones-agentes`, uso `descubrimiento`). El Coordinador no la repite: en G0 solo recibe la propuesta ya clasificada y las preguntas `D-00-NN` que D0 dejó por confianza baja.

## Uso · Leer la respuesta del consultor a un ítem

Una llamada por ítem `D-NN` respondido. `state` = `{"pregunta": ..., "opciones": [...], "respuesta": ...}` con el texto literal.

```json
{
  "estado_respuesta": {
    "type": "choice",
    "instructions": "Decide si la respuesta del consultor resuelve la pregunta planteada",
    "criteria": {
      "elige_opcion": "Elige una de las opciones listadas sin condiciones",
      "respuesta_libre_valida": "No usa las opciones pero define con claridad qué hacer",
      "ambigua": "Admite más de una interpretación o depende de algo que no dice",
      "sin_respuesta": "No contesta la pregunta, la posterga o la rechaza"
    }
  },
  "ambigua_contable": {
    "type": "noul",
    "instructions": "La respuesta deja dudas sobre cuentas contables, impuestos, tasas o saldos"
  }
}
```

Lectura:
- `elige_opcion` o `respuesta_libre_valida` con confianza ≥ 0,8 **y** `ambigua_contable` < 0,3: transcribes el texto literal del consultor y cierras el ítem.
- `ambigua`, `sin_respuesta`, confianza < 0,8 o `ambigua_contable` ≥ 0,3: no transcribes. Pides aclaración en el mismo hilo, citando el `D-NN`.
- En ítems de contabilidad, impuestos o saldos, ante cualquier duda gana la aclaración: un error ahí se propaga hasta la contabilidad del cliente.

## Límites

- JEV **nunca** escribe en `respuesta:`. Lo que se transcribe son las palabras del consultor.
- JEV **no** interviene en la autorización de producción (regla fija en `correo-consultor`), ni en aceptar tareas, ni en decidir qué tareas están listas: son reglas deterministas sobre archivos.
- La salida de JEV es una propuesta o un filtro; la autoridad sigue siendo el archivo y la persona.
