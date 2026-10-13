---
name: "politica-de-escalamiento"
description: "Un criterio único para que \"confianza alta\" signifique lo mismo en todo el pipeline."
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"
  icon: "🚨"
  color: "#6366F1"

---

# Política de escalamiento

Un criterio único para que "confianza alta" signifique lo mismo en todo el pipeline.

## Principio rector: el sistema propone, el usuario confirma

Ningún agente carga al Kárdex un dato sin evidencia directa de la cartola. Si la evidencia es
indirecta, incompleta o admite más de una lectura, la decisión final es del equipo Tax, no del
modelo.

## Cómo se materializa un escalamiento

Al escalar, el worker agrega el pendiente estructurado a `pendientes[]` de su **resultado de tarea**
(el TeamTask que el Coordinador observa vía `taskTrigger`) y termina su turno; no abre un canal con
el usuario ni resuelve la duda. El Coordinador consolida los pendientes de todos los workers en UN
lote y los presenta al usuario Tax por el chat del workflow (`chatTrigger`). Las respuestas vuelven
por chat y el Coordinador reasigna al worker con las respuestas en el `context` del nuevo
`assign_task`. El worker propone; nunca decide el salto.

## Cuándo decide solo (no escala)

- Dato explícito y sin ambigüedad, con el diccionario confirmando cómo leerlo.
- Emparejamiento por identificador externo único (ISIN, CUSIP, nemotécnico), con un solo candidato.
- Cálculo puramente aritmético sobre valores confirmados (total = cuotas × precio).
- El diccionario contempla el patrón y le asigna destino sin condicionales.

## Cuándo debe escalar (crea un pendiente, no decide)

- **Confianza de emparejamiento distinta de alta** — instrumento identificado solo por similitud de
  nombre. Incluye el caso Odoo en que un `default_code` no es reproducible desde `product.name`: si
  la resolución por `financial_instrument_id` + `financial_instrument_name` (segmento del
  `default_code`) + serie + moneda no devuelve exactamente un candidato, se escala, nunca se adivina.
- **Más de un candidato plausible** para cliente o instrumento, sin desempate objetivo.
- **Código o descripción no documentado** en el diccionario — nunca infieras su significado. Ameris
  es explícito para códigos de caja no documentados: no asignar subtipo por inferencia.
- **Valor derivado en lugar de informado** (ej. precio unitario calculado por ausencia de columna en
  Santander) — se deriva pero se marca para confirmación, nunca como dato original.
- **Ambigüedad de clasificación de negocio** (disminución de capital que podría ser dividendo o
  venta; reinversión de dividendo que mueve cuotas pero se origina fuera de scope).
- **Inconsistencia numérica** entre lo extraído y los totales de control de la cartola, no explicada
  por un fee identificado.
- **Riesgo de doble contabilización** entre custodios en cartolas consolidadas, sin fuente de verdad
  definida.
- **Cualquier rechazo de negocio al cargar a Odoo** que no sea error de formato (producto
  inexistente, serie no configurada, período cerrado): se propone resolución, nunca se crea el
  maestro faltante.

## Regla de no reversión

Ningún agente sube la confianza de un resultado para evitar un pendiente. Si el método usado produce
objetivamente confianza media o baja, ese es el valor que se registra.

## Salida de un escalamiento

Produce un pendiente completo y accionable en `pendientes[]`: motivo, pregunta, referencia a
página/línea, opciones cerradas si el diccionario las define. El worker no continúa procesando la
línea escalada; devuelve el control.

## Casos de borde

- **La misma ambigüedad en muchas líneas** (ej. un código no documentado 15 veces): no generes 15
  pendientes; agrúpalos en uno que liste todas las líneas afectadas (en `referencia`).
- **La ambigüedad se repite entre sesiones del mismo custodio**: escalar sigue siendo correcto, pero
  es señal de proponer una actualización del diccionario para dejar de escalar ese patrón.
