---
name: migracion-carga
description: "Runbook de CARGA: fases preparacion→apertura→partidas_abiertas→historicos→conciliaciones; cada lote borrador→verificar→publicar; único escritor."
allowed-tools: odoo_jsonrpc process_manager data
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# CARGA · Carga de la migración

Misiones `carga <fase>`. CARGA es el **único** agente que escribe en Odoo. Cargas también `contrato-migracion`, `dominio-migracion`, `bucle-de-correccion-migracion` (reintentos y corrección), `odoo-rpc-transporte` (`load()`), `taxonomia-errores-odoo`, `entornos-y-seguridad`, `localizacion-chile`, `odoo19-diferencias` y `scripts-verificados-de-carga-odoo` (conversión CSV→payload).

**Lo que se publica en contabilidad no se deshace con un archivo corregido.** Un asiento publicado no se borra: se revierte con un asiento inverso o se restaura la base `[hipótesis: verifícalo en staging]`. Por eso cada lote pasa por **borrador → verificación → publicación**, y nada avanza sin verificarse.

## Fases

`preparacion` → `apertura` → `partidas_abiertas` → `historicos <periodo>` → `conciliaciones`. Nunca se salta una fase ni se invierte el orden.

## Precondiciones

Compruébalas en archivos y en el `context` antes de la primera escritura de cada misión:

1. **Veredicto** `cargable` para cada lote de la fase en `07-auditoria/veredicto.json`.
2. **Autorización de publicación vigente.** En este despliegue (staging), la autorización del consultor 2026-11-09 permite publicar cada lote apenas pase verificación. En el despliegue de producción real rige el ítem `aprobacion_cuadratura` respondido en `07-auditoria/definiciones-auditoria.md` (sin él: solo borrador y verificación).
3. **Fase anterior terminada** según `estado-carga.json`.
4. **Entorno** (`estrategia.yaml`). Si es `production`: `autorizacion_produccion` en el `context` con base y rama que **coincidan literalmente** con `estrategia.yaml`, ensayo en staging verde constatado en `capacidades-instancia.json` → `resultado_ultimo_ensayo`, y respaldo previo informado por el Coordinador. **Sin ensayo exitoso, no se migra a producción.**
5. **Diarios de migración verificados**, releyéndolos de Odoo **ahora**: existen, son los de la estrategia y **no tienen formato de documento electrónico ni exigen tipo de documento** `[VERIFICAR campos]`. Si no puedes demostrarlo, no cargues.
6. **Fechas de bloqueo** de la compañía leídas: ningún lote cae en un período bloqueado.
7. **Módulos** del plan verificados con un solo `search_read`.
8. Cero definiciones abiertas que afecten a los lotes de la fase.

Si una precondición falla, no ejecutes a medias: definición en `preguntas-abiertas.md` y `detenida_por_precondicion`.

## Procedimiento por fase

### `preparacion`

Crea, con `load()` y xmlid, solo lo que el consultor aprobó en P3: diarios de migración (con las propiedades de la estrategia), cuentas faltantes y terceros faltantes. **No crees nada que no esté en `06-lotes/`.** Verifica con read-back. Un tercero que ya existe se enlaza, no se duplica (`bucle-de-correccion-migracion`, "ya existe"). Una fila de prueba en staging confirma, antes de seguir, lo que el diseño dejó `[VERIFICAR]` (nombre del asiento, secuencia).

### Fases de asientos (`apertura`, `partidas_abiertas`, `historicos`)

**1. Cargar en borrador.** `load()` por lote, **respetando los asientos completos**: nunca cortes un lote entre las líneas de un mismo asiento (las líneas anidadas llevan el `id` vacío; si cortas, las huérfanas se rechazan). **Rodaja ≤ 50 asientos por tarea** (o el `lote_optimo` si fuera menor; nunca más de 300 filas): una misión grande se ejecuta como cadena de rodajas — una tarea por rodaja, checkpoint entre rodajas —, nunca una tarea para el lote completo. Lee `messages` en cada respuesta: un `error` significa que el lote no escribió nada. Los asientos quedan en **borrador**.

**2. Verificar cada lote antes de publicar.** Read-back: conteo de asientos y líneas contra `manifiesto.json`; suma de debe y haber contra el manifiesto; todos los asientos en diarios de migración; cuadratura del lote con la tolerancia aprobada. Cualquier diferencia: el lote no se publica, y reportas el detalle por asiento.

**3. Publicar** (con la autorización vigente del consultor: 2026-11-09 para staging —cada lote verificado se publica de inmediato—; en el despliegue de producción real, solo con P4 aprobado). La publicación es una llamada de acción por lote (`action_post` `[hipótesis]`); **no devuelve errores por registro de forma confiable**, así que después relee el estado de los asientos. **Control de seguridad inmediato tras cada publicación:** cuenta los documentos electrónicos generados y los folios consumidos `[VERIFICAR modelo y campo]`. **Si alguno es mayor que cero, detén toda la carga**: es un fallo crítico, igual que un `E500`; repórtalo con los identificadores. **Una vez publicado, el lote es definitivo.** **Autorización vigente del consultor (2026-11-09, staging):** cada lote que pase la verificación del paso 2 se publica de inmediato, sin esperar a la cuadratura final; la re-auditoría y la cuadratura final siguen como controles globales posteriores.

### `conciliaciones`

Ejecuta `plan-conciliaciones.csv` por grupos, solo sobre líneas **ya publicadas** (`reconcile` `[hipótesis]`). Verifica por grupo que el residual quedó en cero o en el esperado. Un grupo que Odoo rechaza (cuenta no conciliable, terceros o compañías distintas) se aparta y se reporta: **nunca fuerces una conciliación**.

## Estado y reanudación

- `estado-carga.json`, un objeto por fase y lote: `estado` ∈ `pendiente` | `borrador` | `verificado` | `publicado` | `conciliado` | `detenido`. **Se escribe al final de cada rodaja (≤ 50 asientos), no solo al final del lote.** Si se corta el turno, retomas desde ahí con verificación DB-primero —el estado real de los xmlids en Odoo manda sobre el informe—: un lote `publicado` no se toca. **Write-first:** los informes se escriben en disco antes de la respuesta final, y la respuesta final es corta (< 1500 caracteres); nunca termines el turno sin respuesta final ni con el checkpoint atrasado.
- Bitácora por fase (`bitacora-<fase>.jsonl`): desde y hasta (xmlids), conteos, totales debe y haber, resultado de verificación, publicación y control de documentos electrónicos.
- Lo aprendido sobre la instancia (nombre del asiento, secuencia consumida, `lote_optimo`, campos reales) va a `capacidades-instancia.json` con su evidencia.

## Reglas

- **Nunca publiques un lote que no verificaste.** (El P4 formal rige en el despliegue de producción real; acá manda la autorización del consultor 2026-11-09 para staging.)
- **Un lote publicado no se vuelve a cargar ni a editar.** Un error en uno publicado es una definición (asiento inverso o restauración).
- **Nunca concilies por parecido**: solo lo que está en el plan.
- **No crees datos maestros** que no estén en `06-lotes/` para que una referencia resuelva.
- Producción: cada publicación es una escritura irreversible; no hay "probar con un lote".
- `module_*` nunca va en un payload; un módulo faltante es una definición.
- **Entorno único (2026-11-09):** este despliegue opera exclusivamente contra la base conectada en los nodos `odooJsonRpc` (`ecominera-consultores-40765102`, rama dev de Odoo.sh); la lógica de producción queda fuera de alcance y `ensayo_desde_cero` se reporta como `no_aplica_local`.

## Resultado

```json
{"mision": "carga <fase>", "ronda": 1, "estado": "completada | detenida_por_precondicion",
 "fase": "historicos", "lotes": {"total": 12, "borrador": 0, "verificado": 0, "publicado": 12, "conciliado": 0},
 "documentos_electronicos_generados": 0, "folios_consumidos": 0,
 "ensayo_desde_cero": false, "carga_completa": false,
 "estado_archivo": "08-carga/estado-carga.json", "resumen": "08-carga/resumen-carga.md",
 "definiciones_abiertas": [], "alertas": []}
```

`carga_completa: false` si hay un lote sin publicar, una conciliación rechazada o un control rojo. **Declara siempre el estado del ensayo desde cero** (no puedes reconstruir staging tú). `actualizados > 0` en una primera carga no es normal: significa que esos xmlids ya existían; dilo explícitamente.

## Nunca

- Publicar sin verificación del lote y sin P4 aprobado, o seguir tras detectar un documento electrónico generado.
- Cargar contra un diario cuya configuración no pudiste releer y demostrar.
- Migrar a producción sin ensayo en staging exitoso ni respaldo informado.
- Recargar o editar un asiento publicado.
- Ajustar un monto, repartir una diferencia o crear una cuenta puente para que cuadre.
- Usar `create` en bucle donde va `load()`.
