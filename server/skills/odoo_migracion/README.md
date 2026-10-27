# odoo_migracion — skills del flujo ArmandoMigrador

Skills del flujo **ArmandoMigrador** (`addval-connect`): migración contable de un sistema de
origen a Odoo 19. La fuente del diseño es el paquete `skills-migracion-odoo` versionado en
`docs-internal/paquete-migracion/` (original + `adaptado/` con las adaptaciones de plataforma).

## Relación con lo que corre

El flujo en canvas lleva estos skills **inline** en los `skills_config` de sus 5 nodos
`masterSkill`, marcados `isCustomized: true`. Este folder es el espejo SSOT de ese contenido:
mismo cuerpo, con frontmatter. Si corriges un hecho aquí, actualiza también el snapshot inline
(en la próxima sesión de mutación) y viceversa.

## Distribución por agente

| Agente | Skills propios | Compartidos |
|---|---|---|
| Coordinador | `orquestacion-migracion`, `puntos-de-control-migracion`, `correo-consultor-migracion`, `jev-migracion` | `contrato-migracion` |
| Analista | `migracion-analisis`, `migracion-diseno` | `dominio-migracion`, `contrato-migracion`, `jev-migracion`, `odoo-rpc-transporte`, `taxonomia-errores-odoo`, `localizacion-chile`, `convencion-ids-externos` |
| Transformador | `migracion-transformacion` | `dominio-migracion`, `contrato-migracion`, `convencion-ids-externos`, `localizacion-chile` |
| Auditor | `migracion-auditoria` | `dominio-migracion`, `contrato-migracion`, `taxonomia-errores-odoo`, `odoo-rpc-transporte`, `localizacion-chile` |
| CARGA | `migracion-carga`, `bucle-de-correccion` | `odoo-rpc-transporte`, `taxonomia-errores-odoo`, `entornos-y-seguridad`, `contrato-migracion`, `dominio-migracion`, `localizacion-chile`, `odoo19-diferencias`, `scripts-verificados-de-carga-odoo` |

Más los skills de plataforma que refleja cada nodo: `skill`, `task-manager`, `write-todos-skill`,
`ms-mail-skill`, `jev-decisions`, `process-manager-skill`.

## Nota sobre duplicados con odoo_impl

Seis skills técnicos (`odoo-rpc-transporte`, `taxonomia-errores-odoo`, `bucle-de-correccion`,
`entornos-y-seguridad`, `localizacion-chile`, `odoo19-diferencias`) y dos de biblioteca
(`convencion-ids-externos`, `scripts-verificados-de-carga-odoo`) existen también en
`server/skills/odoo_impl/`. **No son copias exactas**: están adaptados al dominio migración
(rutas `07-auditoria/` en vez de `07-validacion/`, roles Transformador/Analista, fases de carga
en vez del grafo `depende_de`, `06-lotes/` en vez de `05-plantillas/`). Regla de sincronización:
un hecho de Odoo (campo, método, versión) se corrige en AMBOS folders — el paquete original ya
traía la misma advertencia.

## Adaptaciones de plataforma aplicadas (21-oct-2026)

- `sandboxed_python` / `sandbox-de-codigo-en-opencompany` (retirados el 20-oct) →
  **`process_manager` + `data`**: script escrito con `data` en el workspace, `python3` real vía
  `process_manager`, salida por stdout en una línea JSON. El Transformador escribe `06-lotes/`
  así.
- `archivos` / `fileRead` → `data` (dataSource: CSV/JSON/XLSX/PDF/HTML paginado).
- `odoo-rpc-transporte` ganó la sección **Override de instancia por llamada** (PR #50), ausente
  en el paquete; y su ruta de introspección alineada al contrato migración
  (`02-instancia/introspeccion.json`).
- `convencion-ids-externos`: validador → Auditor (`migracion-auditoria`), abreviaturas
  `account.move` → `move` y `account.move.line` → `move_line`.
- `scripts-verificados-de-carga-odoo`: rutas al contrato migración
  (`06-lotes/lotes/…`, `08-carga/capacidades-instancia.json`).
