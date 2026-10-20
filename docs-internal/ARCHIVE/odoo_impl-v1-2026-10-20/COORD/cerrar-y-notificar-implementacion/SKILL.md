---
name: cerrar-y-notificar-implementacion
description: >-
  Genera el informe final de la implementación (objetos cargados, filas en error, casos de QA,
  pendientes resueltos, tareas de desarrollo abiertas) y cierra la sesión. Úsala en cualquier estado
  terminal, incluida una implementación detenida antes de la carga.
allowed-tools: file_read write_todos
metadata:
  agente: COORD
  tipo: MIX
  prioridad: P1
  depende_de: orquestar-implementacion-odoo
  icon: "🏁"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Cerrar y notificar la implementación

A5 conoce el detalle de la carga y del QA, pero una implementación puede cerrarse sin llegar a A5 —
detenida en brechas, sin plantillas devueltas, o abortada por instancia inaccesible. Centralizar el
cierre en el Coordinador garantiza que **toda** sesión termina con un informe, no en silencio.

## Estados terminales

- **`CARGADA`** — todos los archivos cargados sin errores de fila y QA verde.
- **`CARGADA_PARCIAL`** — cargó con filas en error, o con casos de QA fallidos. Es el caso más común y
  el que más importa reportar bien.
- **`DETENIDA`** — no se llegó a cargar: instancia inaccesible (`E5xx`), plantillas nunca devueltas,
  pendientes bloqueantes sin respuesta, o falta de confirmación de entorno productivo.

## Procedimiento

1. **Reconstruye desde los artefactos, no desde tu memoria de la conversación.** Con `file_read`:
   `08-carga/resumen-carga.md` y las `bitacora-<modelo>.jsonl`, los `07-validacion/informe-*.md`,
   `09-qa/resultados-<flujo>.md`, y `04-backlog/tareas.yaml` para las tareas que quedan abiertas. El
   registro durable de los TeamTask (`task_manager(operation="list_tasks")`) es la pista de auditoría
   de qué etapa hizo qué.
2. **Referencia registros reales, no solo conteos.** Por modelo cargado, incluye el rango de xmlids y
   la cantidad de creados vs. actualizados. Los xmlids son la referencia estable entre entornos: un
   id numérico de staging no significa nada en producción.
3. **Las filas en error van con su código y quién corrige** (`E200` consultor, `E320` agente…), no
   como "hubo algunos problemas". Es la lista de trabajo del consultor para la siguiente iteración.
4. **QA fallido se reporta como caso**, con el `id` del caso y el motivo. Un caso de QA rojo no es un
   error de carga: es una configuración incompleta, y hay que decir cuál.
5. **Tareas de desarrollo e integración quedan abiertas por diseño.** Las HU clasificadas como
   `desarrollo`, `integracion` o `fuera_de_alcance` en la matriz de brechas no se implementaron acá;
   lístalas para que no se confundan con omisiones.
6. **Si fue `DETENIDA`**, no reconstruyas resumen de carga: céntrate en dónde se detuvo, por qué, y
   qué se necesita para reanudar. Una sesión detenida con informe claro se reanuda; una sin informe se
   reinicia desde cero.
7. **Estado del entorno, siempre explícito.** Qué base de datos, qué rama, y si el ensayo completo en
   staging (reconstruir desde cero y repetir la carga entera) se hizo o no. Si no se hizo, dilo — es
   la diferencia entre "listo para producción" y "funcionó una vez sobre una base ya ensuciada".
8. Entrega por el chat, marca los TeamTask como cerrados y refleja el cierre con `write_todos`. La
   sesión no se re-delega salvo reapertura explícita del usuario.

## Salida

```
Implementación acme — Instancia staging (acme-staging-19, rama staging)
Resultado: CARGADA_PARCIAL

CARGADO
  05 account.account          142 creados,   0 actualizados   adv_acme.account_*
  07 account.tax               18 creados,   0 actualizados   adv_acme.tax_*
  20 res.partner              310 creados,   4 actualizados   adv_acme.partner_*
  27 product.category          25 creados,   0 actualizados   adv_acme.categ_*
  31 product.template       1.204 creados,   0 actualizados   adv_acme.prod_tmpl_*

FILAS EN ERROR (12) — corrige el consultor
  E210  20_res.partner.csv        7 filas   DV de RUT incorrecto
  E220  31_product.template.csv   3 filas   type fuera de catálogo
  E400  31_product.template.csv   2 filas   UoM incompatible con la categoría de UoM

ARCHIVOS NO CARGADOS (1)
  E320  64_mrp.bom.csv    referencia adv_acme.prod_tmpl_subconjunto, definido en 31 pero ausente

QA
  14 de 16 casos verdes
  QA-007  rojo   La cotización no aplica la lista mayorista: falta pricelist_id en el partner
  QA-011  rojo   Sin folios CAF cargados para el documento tipo 33 en certificación

PENDIENTES RESUELTOS (3)
  P-001  modulo_faltante        l10n_cl_edi instalado en staging el 2026-08-08
  P-002  clasificacion_dudosa   HU-021 clasificada como desarrollo
  P-003  campo_inexistente      Columna l10n_cl_activity_description omitida

ABIERTO POR DISEÑO — no forma parte de esta carga
  desarrollo    HU-021 aprobación de orden de venta por margen
  integracion   HU-034 sincronización con el ERP de bodega externa

ENSAYO EN STAGING
  Carga incremental sobre staging: sí.  Reconstrucción desde cero + recarga completa: NO ejecutada.
  Hasta hacerla, no hay evidencia de que el orden de carga sea correcto sobre una base limpia.
```

## Casos de borde

- **Cero filas en error y QA verde**: igual reporta el estado del ensayo en staging y las tareas
  abiertas por diseño. "Todo bien" sin esos dos datos se lee como "listo para producción" y no lo es.
- **La implementación se detuvo antes de A3**: el informe es la matriz de brechas y el blueprint como
  entregables, más qué falta para generar plantillas. Sigue siendo un cierre válido con valor
  entregado.
- **Se cargó en producción**: registra la confirmación de base + rama que autorizó la escritura, y
  quién la dio. Sin eso el informe no está completo.
- **Un modelo aparece con actualizados > 0 en la primera carga**: no lo reportes como normal. Significa
  que esos xmlids ya existían, y eso o es una recarga o es una colisión de prefijo. Dilo
  explícitamente.
