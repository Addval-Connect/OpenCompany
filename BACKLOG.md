# Backlog — OpenCompany (fork Addval)

**Última revisión:** 2026-11-18 · **Dueño:** equipo Addval Connect

Este archivo existe porque GitHub Issues está **desactivado** en
`Addval-Connect/OpenCompany` y el repo no tiene un tracker configurado. Es el
registro de pendientes hasta que se active uno; cuando eso pase, se vuelca ahí y
este archivo se borra.

Regla de mantenimiento: cada pendiente que se cierre se marca acá en el mismo PR
que lo cierra, y cada pendiente nuevo se agrega con su fuente. Si un pendiente
no tiene fuente ni dueño, no es un pendiente: es una idea.

## Abiertos

| # | Pendiente | Área | Prioridad | Estado / siguiente paso | Fuente |
|---|---|---|---|---|---|
| 1 | **Fidelidad de versiones 17/18 con datos reales.** El sandbox con datos es Odoo 19; los clientes corren 17 y 18. Los stacks 17/18 existen pero vacíos: sólo validan nombres de campos, no flujos con datos. | Entorno de pruebas | **Alta** | Bloqueado: espera un dump de un 17 y un 18 de la flota (devops). Al llegar: `createdb` → `pg_restore` → filestore → `make users17`/`users18`. | `OpenCompany-sandbox/MIGRACION-OMARCHY.md` §5 |
| 2 | **H1, parte D.** La protección principal ya está mergeada/PR; falta el chunking de generaciones largas (`json_patch`) y la decisión de modelo para turnos largos (R2: modelo más robusto en tool-calling o *thinking* acotado). | Producto | Media | Abierto. R2 es decisión de negocio; D1–D2 es código. | `HANDOFF.md` (residual) e `informe-hallazgos-2026-11-11.md` §8 |
| 3 | **La app no corre en la máquina nueva.** Sólo está arriba el sandbox de Odoo; no hay unidad systemd de `opencompany` ni proceso en `127.0.0.1:5678`. | Entorno local | Media | Abierto: instalar el servicio o documentar el arranque manual. | Verificación de migración, 2026-11-18 |
| 4 | **PRs abiertos sin mergear.** #82 (Microsoft mail, checks verdes), #76 (skills de migración, checks verdes) y #84 (guard H1 + skills Odoo). | Proceso | Baja | Abierto: revisión humana. El merge no lo hace el agente. | GitHub |
| 5 | **Tracker formal.** Activar Issues (requiere admin del repo) o configurar el tracker de T3 para este proyecto. | Proceso | Baja | Abierto. Mientras tanto, este archivo. | Este documento |

## Cerrado (para no reabrirlo)

- **Migración Ubuntu → Omarchy:** cerrada y verificada (GitHub/SSH, skills,
  dependencias, Docker rootless, historial de OpenCode, sandbox de Odoo con
  reset determinístico). No queda nada que bloquee.
- **H1, partes A+B+C:** frontera del proveedor, silla de seguridad y
  observabilidad. 159 tests verdes y ruff limpio (2026-11-18).
- **H2, escrituras no atómicas:** el backend de archivos escribe con reemplazo
  atómico (`server/nodes/filesystem/_backend.py`, `os.replace`), así que la
  clase de corrupción observada queda cubierta en ese camino.
- **T3 y OpenCode:** no se restauró `statev2.sqlite` ni se reescribió el
  historial para "revivir" proyectos. Decisión cerrada, no reabrir sin motivo
  nuevo.

## Decisiones que no se reabren

- OpenCompany habla con Odoo por JSON-RPC con credenciales de sólo lectura; sólo
  el nodo CARGA escribe, con otra credencial.
- `fields_get` es la única autoridad sobre campos; ninguna tabla escrita vale
  como fuente.
- El sandbox con datos es Odoo 19; 17 y 18 son fixtures de esquema hasta que
  llegue el dump (pendiente #1).
