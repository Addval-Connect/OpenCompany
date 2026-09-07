---
name: consultar-al-usuario-en-lote-odoo
description: >-
  Agrupa todos los pendientes abiertos de la implementación en una sola consulta al consultor, con
  contexto suficiente (archivo, fila, columna, opciones) para responder sin abrir la instancia. Es el
  único punto donde el pipeline interrumpe a una persona además de completar plantillas.
allowed-tools: file_read write_todos
metadata:
  agente: COORD
  tipo: LLM
  prioridad: P0
  depende_de: orquestar-implementacion-odoo
  icon: "❓"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Consultar al usuario en lote

Una implementación levanta dudas en cinco etapas distintas. Preguntar de a una agota al consultor y
degrada sus respuestas justo donde el criterio funcional importa más: impuestos, diarios, folios,
clasificación de brechas. Este es el único punto donde se interrumpe a una persona además del
handoff de plantillas, y concentra la disciplina de hacerlo bien.

El "usuario" es el consultor al otro lado del **chatTrigger** del workflow. Solo el Coordinador habla
con él; A1-A5 nunca preguntan, solo devuelven `pendientes[]` en el resultado de su TeamTask.

## Entrada

- `pendientes[]` acumulados en el `context` de la sesión, provenientes de los TeamTask de los
  workers.
- Las rutas del `context`, para completar el contexto de un pendiente incompleto con `file_read`
  (leer la fila del CSV, el objeto del blueprint, el campo de la introspección).

## Procedimiento

1. **Verifica que cada pendiente traiga lo mínimo**: `motivo`, `pregunta` cerrada, `opciones` cuando
   existan, y `referencia` con archivo + fila + columna. Si llega incompleto, complétalo con
   `file_read` antes de mostrarlo — un pendiente que obliga al consultor a investigar duplica el
   ciclo.
2. **Agrupa por `motivo`**, no por orden de llegada, y dentro de cada grupo ordena por archivo y
   fila. Diez `campo_inexistente` juntos se responden en un minuto; diez intercalados con otros
   motivos, no.
3. **Prioriza los bloqueantes**: `modulo_faltante` y `entorno_produccion` primero (detienen la etapa
   siguiente completa), luego `clasificacion_dudosa` y `campo_inexistente` (bloquean un objeto), al
   final los de fila concreta. Refleja el lote con `write_todos`.
4. **Cuando hay opciones cerradas, ofrécelas en su orden y no las reformules ni sugieras una.** En
   una decisión de impuestos o de plan de cuentas, la sugerencia del agente se convierte en la
   respuesta por defecto y nadie la revisa.
5. **Un único mensaje** con todos los pendientes, por el chat. No lo dividas salvo límite técnico de
   longitud.
6. **Espera por el mismo canal.** No reintentes preguntar de otra forma: el TeamTask sigue abierto
   hasta que contesten. Al llegar la respuesta, llena `respuesta` / `respondido_por` /
   `respondido_en` en cada pendiente y re-delega la etapa correspondiente con las respuestas en el
   `context`.

## Salida

```
Proyecto acme — Instancia staging — Etapa: diseño de blueprint (A2)
Tengo 4 dudas antes de seguir:

BLOQUEANTES

1) Módulo no instalado
   El blueprint necesita `l10n_cl_edi` para los tipos de documento electrónico, pero la
   introspección del 2026-08-10 no lo reporta instalado.
   ¿Lo instalamos en staging antes de seguir, o el alcance excluye facturación electrónica?

2) Campo inexistente (05-plantillas/20_res.partner.csv, columna l10n_cl_activity_description)
   `fields_get` de res.partner no reporta ese campo.
   Opciones: (a) omitir la columna  (b) instalar l10n_cl_edi y reintroducirla  (c) usar otro campo

CLASIFICACIÓN

3) HU-021 "Aprobación de orden de venta por margen" (01-analisis/matriz-brechas.csv, fila 21)
   No hay configuración estándar que cubra aprobación por margen calculado.
   Opciones: (a) desarrollo  (b) parametrizable con reglas de aprobación estándar  (c) fuera de alcance

FILAS

4) Referencia no resuelta (31_product.template.csv, fila 7, columna categ_id/id)
   `adv_acme.categ_insumo` no existe. El archivo 27 define `adv_acme.categ_insumos` (plural).
   ¿Es un typo del archivo, o falta la categoría?
```

## Casos de borde

- **Un único pendiente**: igual pasa por esta skill y el mismo canal, para mantener formato y tono.
- **El consultor responde algo fuera del lote** (corrige una decisión ya aplicada): no lo apliques
  como respuesta a un pendiente abierto. Aclara a qué pendiente corresponde; si es un cambio de
  decisión sobre un artefacto ya producido, re-delega la etapa que lo produjo — no parchees el
  artefacto.
- **El consultor pide más contexto** (ver el CSV, ver qué reportó `fields_get`): esta skill lo
  provee con `file_read` y no cuenta como segunda interrupción.
- **La respuesta obliga a re-introspeccionar** (instalaron un módulo, agregaron un campo en Studio):
  re-delega A1 para introspección puntual antes de continuar. Una plantilla generada contra una
  introspección vencida se cae en la carga.
- **La respuesta autoriza escribir en producción**: exige base de datos y rama explícitas en el
  texto de la respuesta, y guárdalas. "Sí, dale" no es una confirmación de entorno.
