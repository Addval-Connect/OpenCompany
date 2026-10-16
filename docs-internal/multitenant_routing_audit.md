# Auditoría: enrutamiento multi-tenant y el sentinel "owner"

*2026-10-16 — pedido tras la cascada de bugs owner/namespace (data_mounts,
conversaciones globales, mounts). Este documento mapea cómo funciona el
enrutamiento HOY, inventaría cada uso de "owner", clasifica qué es
legítimo y qué no, y propone el diseño objetivo + plan de migración.*

---

## 1. Cómo funciona el enrutamiento HOY

### 1.1 Tres identificadores distintos, actualmente confundidos

| Identificador | Debería significar | Dónde vive hoy |
|---|---|---|
| **`user_id` / principal** | La cuenta autenticada (auth) | JWT `sub`; tabla `users`; `OWNER_PRINCIPAL_ID="owner"` cuando auth está deshabilitada |
| **`namespace`** | El tenant (límite de datos) | JWT claim `active_namespace`; ContextVar; subcarpetas `namespaces/{ns}/` |
| **`customer_id` de credenciales** | El bucket de credenciales | Columna `customer_id` en `credentials.db`; **hoy colisiona con "owner"** |

El problema de fondo: **"owner" significa tres cosas distintas según el
archivo** — principal de auth, nombre de namespace en disco, y bucket de
credenciales. Cada bug que cazamos esta semana salió de esa colisión.

### 1.2 Flujo HTTP (request)

```
JWT (claim active_namespace: "default" | "cartola-tax" | ...)
  → middleware/auth.py
      set_active_namespace(normalize_credential_ns(claim))
      └─ normalize_credential_ns: "default" → "owner"   ← LA COLISIÓN
  → ContextVar core.namespace_context (default "owner")
      → DatabasePool.get(ns)      → {DATA_DIR}/namespaces/{ns}/workflow.db
      → CredentialsPool.get(ns)   → {DATA_DIR}/namespaces/{ns}/credentials.db
      → workspace_base_dir()      → {DATA_DIR}/namespaces/{ns}/workspaces/
```

**Consecuencia observable**: el usuario ve la namespace "default" en la UI
(`GET /namespaces` devuelve el claim crudo), pero sus workflows,
credenciales y workspaces viven físicamente en `namespaces/owner/`.
Verificado en el box: `namespaces/default` no existe; `namespaces/owner`
tiene 10 workflows.

### 1.3 Flujo WebSocket

- **Socket autenticado** (`/ws`): al conectar, JWT → `state.active_namespace`
  → `set_active_namespace(normalize_credential_ns(...))`. El contexto
  hereda a los handler tasks.
- **Socket interno** (`/ws/internal`, worker Temporal): por mensaje,
  `_set_ns(data.get("credential_customer_id") or "owner")` — fail-open
  con fallback "owner".

### 1.4 Flujo de ejecución de nodos

```
context dict {user_id, credential_customer_id, workflow_id, ...}
  → Connection factory (credenciales declaradas del plugin)
      → Credential.resolve(user_id="owner")        ← default sentinel
      → auth_service → credentials_db (ContextVar)
  → ctx.workspace_dir inyectado por el executor (namespace-aware, OK)
```

### 1.5 Flujo Temporal

Interceptores + executor propagan `user_id` / `credential_customer_id`
en el contexto de actividad, con defaults `"owner"` en varias firmas.
`events/dispatch.py` trata `("default", "owner")` como "sin tenant".

### 1.6 Qué YA está bien ruteado (métodos de Database vía `__getattr__`)

Todo lo que llama **métodos** de `Database` (no sesiones directas) rutea
al namespace activo automáticamente: workflows, node_outputs, console
logs, agent_memory, ejecuciones, node_parameters. Sin cambios.

---

## 2. Inventario clasificado de "owner"

### A. Legítimo — auth / cuenta de usuario (NO tocar)

`_AUTH_METHODS` (users CRUD, user_settings, invites, namespace
assignments, tenant namespaces), migraciones, `is_owner`, tui.py
(admin de usuarios), `core/health.py`. `OWNER_PRINCIPAL_ID` **como
principal** cuando auth está deshabilitada — sigue existiendo, pero solo
en el dominio auth.

### B. "owner" como namespace / bucket de datos — ELIMINAR

| Ubicación | Qué hace |
|---|---|
| `core/namespace_context.py` | ContextVar default `"owner"`; `set_active_namespace(ns or "owner")` |
| `constants.py` `DEFAULT_CREDENTIAL_CUSTOMER_ID="owner"` | Bucket de credenciales para el namespace default |
| `constants.py` `normalize_credential_ns` | Mapea el claim "default" → bucket "owner" |
| `core/credentials_database.py` | `customer_id default "owner"` en 6+ firmas |
| `core/db_pool.py` (vía ContextVar) | Crea/usa `namespaces/owner/workflow.db` |
| `middleware/auth.py` | Auth-disabled → principal "owner" + context "owner" |
| Disco: `namespaces/owner/` | Los datos reales del namespace "default" |

### C. Fallbacks silenciosos fail-open — FAIL-CLOSED

| Ubicación | Fallback |
|---|---|
| `routers/websocket.py:1839` (socket interno) | `credential_customer_id or "owner"` |
| `nodes/context/_handlers.py:_authenticated_owner` | `return OWNER_PRINCIPAL_ID` |
| idem `canvas`, `simple_memory`, `data_source` handlers | idem |
| `services/workflow.py` (14 ocurrencias) | `user_id or "owner"`, `credential_customer_id or "owner"` |
| `services/plugin/context.py`, `credential.py` | `resolve(user_id="owner")`, `context.get("user_id", "owner")` |
| `services/temporal/executor.py`, `deployment/*`, `ai.py`, `base.py`, `cli_agent/service.py` | `user_id or "owner"` |
| `nodes/tool/{canvas,data_source,simple_memory}/__init__.py` | `ctx.user_id or "owner"` |
| `services/events/dispatch.py:100` | `("default","owner") == sin tenant` |

Estos fallbacks convierten "contexto perdido" en "datos del owner" —
exactamente la clase de bug silencioso que queremos erradicar.

### D. Corregidos esta semana (contexto)

`data_mounts`/Canvas/Memory stores + conversaciones (PR #43): sesión
directa → `active_db()`. Queda pendiente migrar las 7 conversaciones
históricas del owner DB.

---

## 3. Diseño objetivo

1. **"owner" solo existe como principal de autenticación.** Nunca es
   namespace, nunca bucket de credenciales, nunca fallback de datos.
2. **Namespace canónico del default: "default"** end-to-end — es el nombre
   que la UI y Temporal ya usan. El ContextVar, los DB files
   (`namespaces/default/`), los buckets de credenciales y los workspaces
   se llaman igual que el claim del JWT. Sin traducciones.
3. **Fail-closed en rutas de datos**: si el contexto de namespace no está
   seteado, la operación de datos falla con error explícito. Los únicos
   fallbacks permitidos: modo auth-disabled (principal+namespace fijos)
   y los métodos de `_AUTH_METHODS` (owner DB por diseño).
4. **Credenciales**: la columna `customer_id` pasa a valer el namespace
   (string idéntico al claim). `normalize_credential_ns` se elimina.

---

## 4. Plan de migración (fases, cada una con tests y deploy seguro)

- **F1 — Fail-closed + unificación del nombre**: ContextVar default
  `"default"`; `set_active_namespace()` sin coercion a owner; eliminar
  `normalize_credential_ns` (identity); reemplazar fallbacks (C) por
  error explícito o resolución real del contexto. Los lectores que hoy
  hacen `get_active_namespace() or "owner"` pasan a exigir contexto.
- **F2 — Migración de credenciales**: en cada `credentials.db`,
  `UPDATE ... SET customer_id='default' WHERE customer_id='owner'`
  (script idempotente, backup previo). Corre en el boot post-deploy.
- **F3 — Migración de archivos**: renombrar
  `namespaces/owner/ → namespaces/default/` (workflow.db, credentials.db,
  workspaces/) con backup `namespaces.owner.pre-f3.bak/`. Script en el
  box durante ventana de deploy.
- **F4 — Limpieza de sentinels restantes**: firmas `user_id="owner"` →
  parámetro requerido o `None` explícito con falla temprana; la
  constante `OWNER_PRINCIPAL_ID` queda documentada como
  *auth-disabled principal only*.
- **F5 — Tests de invariantes**: nueva suite que falle si aparece
  `or "owner"`/`default "owner"` en rutas de datos (grep-contract), más
  los tests funcionales de cada fase.

## 5. Decisiones (confirmadas 2026-10-16) y estado de implementación

1. **Nombre canónico: `"default"`** ✅ — ContextVar, buckets de
   credenciales, `_AUTH_METHODS` → DB global = `namespaces/default/`.
2. **Fail-closed con `MULTI_TENANT_NAMESPACES=true`** ✅ — HTTP: token sin
   claim `active_namespace` → 401 (middleware). WS interno: mensaje sin
   `credential_customer_id` → descartado con `NAMESPACE_REQUIRED`. Con
   multi-tenant off, todo resuelve "default" (comportamiento actual).
3. **Migración a `namespaces/default/`** ✅ script listo:
   `python -m scripts.migrate_default_namespace` (F3 rename owner→default
   con backup + F2 rows `customer_id`), idempotente, `--dry-run`,
   `--force`. Corre con la app detenida, en la ventana de deploy.

### Implementado en esta fase (F1+F2 código)

- `constants.py`: `DEFAULT_CREDENTIAL_CUSTOMER_ID="default"`;
  `normalize_credential_ns` identity; `OWNER_PRINCIPAL_ID` documentado
  como principal-only.
- `core/namespace_context.py`: default "default".
- `core/namespaced_db.py`: el DB global (auth) es `namespaces/default/`
  (`GLOBAL_NAMESPACE`).
- `middleware/auth.py`: fail-closed HTTP + auth-disabled → "default".
- `routers/websocket.py`: fail-closed socket interno.
- `core/credentials_database.py`: migración idempotente de filas
  `customer_id='owner' → 'default'` en `initialize()` + defaults nuevos.
- `services/auth.py`, `services/workflow.py`, `plugin/context.py`,
  `credential_backends.py`, google/twitter helpers, `workspace_locator`:
  buckets y defaults "owner" → "default". Los `user_id` (principal) que
  quedan son dominio auth.
- Tests: `test_identity_namespaces` actualizado al nuevo contrato +
  fail-closed middleware + 3974 passed full suite.

### Pendiente (ventana de deploy, manual)

- Correr `scripts/migrate_default_namespace.py` en el box (F3).
- Migrar las 7 conversaciones históricas del owner DB (script puntual).
