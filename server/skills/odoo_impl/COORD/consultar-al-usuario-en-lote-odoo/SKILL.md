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
Proyecto acme — Instancia staging — Etapa: carga A5
Tengo 4 puntos antes de seguir. Para cada uno te indico qué pasó y qué propongo — solo necesito tu
confirmación o ajuste.

BLOQUEANTES (detienen la etapa completa)

1) Módulo no instalado — l10n_cl_edi
   El blueprint necesita `l10n_cl_edi` para tipos de documento electrónico, pero la instancia lo
   reporta `uninstalled`.
   ► PROPUESTA: Instalarlo desde Configuración → Apps en la instancia staging antes de continuar.
     Cuando esté instalado, avísame y relanzo A1 (introspección puntual) + A5 en los archivos detenidos.
   ¿Confirmas que lo instalarás, o el alcance excluye facturación electrónica?

2) Xmlid de empresa faltante — plan de cuentas (10_account.account.csv)
   El CSV usa `adv_ecominera.company_ecominera` en company_ids para las 268 cuentas, pero ese xmlid
   no existe en la instancia. Con `load()` transaccional, el batch completo falla.
   ► PROPUESTA A (recomendada): Crear el xmlid apuntando a la empresa principal:
       ir.model.data.create({module:"adv_ecominera", name:"company_ecominera", model:"res.company", res_id:1})
     Después cargo las 268 cuentas sin tocar el CSV.
   ► PROPUESTA B: Reemplazar en el CSV `adv_ecominera.company_ecominera` → `base.main_company`.
   ¿Confirmas Propuesta A, o hay una empresa distinta a id=1 que corresponde?

CONSTRAINT (detiene un archivo)

3) Cuenta "Resultado del ejercicio" colisiona con l10n_cl (10_account.account.csv, código 999999)
   Odoo solo permite una cuenta con tipo `current_year_earnings` por compañía. `l10n_cl` ya creó la
   cuenta 891000 "Utilidades del ejercicio". El CSV trae 999999 con el mismo tipo → batch rechazado.
   ► PROPUESTA A (recomendada): Excluir 999999 del CSV. La cuenta 891000 de l10n_cl ya cumple la función.
   ► PROPUESTA B: Reclasificar 999999 a tipo `income` o `equity` en el CSV.
   ► PROPUESTA C: Reemplazar 891000 con 999999 (requiere write en la cuenta existente + ajuste de xmlid).
   ¿Cuál aplica para este cliente?

FILAS (errores de dato del consultor)

4) RUT con DV incorrecto (20_res.partner.csv, filas 14, 67, 203)
   Fila 14: 76.543.210-K (DV calculado: 3)  Fila 67: 77.891.234-5 (DV calculado: 9)  Fila 203: 12.345.678-0 (DV calculado: 8)
   Las otras 233 filas están ok y ya las cargué.
   ► PROPUESTA: Corriges los 3 RUT en el archivo fuente y me mandas la versión corregida. Recargo solo
     esas filas.
   ¿Ok?
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
