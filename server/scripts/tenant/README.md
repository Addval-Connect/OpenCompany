# Multi-Tenant Admin Scripts

Scripts for managing login accounts and Temporal namespace isolation in OpenCompany when `MULTI_TENANT_NAMESPACES=true`.

## Prerequisites

- `company build` (or `uv sync`) must have run at least once so the `.venv` exists.
- Temporal must be running (`company dev` or `company start`) when provisioning or re-enabling a namespace.
- Run scripts from anywhere — they resolve their own paths.

## DATA_DIR

Scripts automatically detect the active database:

| Environment | DATA_DIR |
|---|---|
| Dev (`company dev`) | `<repo>/.opencompany/` (from `.env.dev`) |
| Prod (EC2) | `~/.opencompany/` (from `.env`) |
| Custom override | Set `OC_DATA_DIR=/path/to/.opencompany` |

```bash
# Override for EC2 or a non-standard path:
OC_DATA_DIR=/home/oc-app-user/.opencompany ./scripts/tenant/status.sh
```

---

## Scripts

### `status.sh` — Current state

```bash
./scripts/tenant/status.sh
```

Shows all accounts, their namespace assignments, and whether `MULTI_TENANT_NAMESPACES` is active.

---

### `onboard-tenant.sh` — Full onboarding (create + assign)

```bash
./scripts/tenant/onboard-tenant.sh \
  --email user@company.com \
  --name "Company Name" \
  --namespace tenant-company
```

Options:
- `--password PASSWORD` — set a specific password (omit to auto-generate)
- `--retention-days N` — Temporal workflow retention in days (default: 7)

After running, **restart the backend** so it starts a worker for the new namespace:
```bash
company stop && company dev
```

---

### `create-user.sh` — Create account only

```bash
./scripts/tenant/create-user.sh --email user@company.com --name "Full Name"
./scripts/tenant/create-user.sh --email user@company.com --name "Full Name" --password secret123
```

Creates a login account without a namespace. The account uses the default namespace until one is assigned.

---

### `assign-namespace.sh` — Assign namespace to existing account

```bash
./scripts/tenant/assign-namespace.sh \
  --email user@company.com \
  --namespace tenant-company
```

Options:
- `--retention-days N` — Temporal workflow retention in days (default: 7)

Re-running this command is safe (idempotent) — if the namespace already exists in Temporal it is reused.

---

### `disable-namespace.sh` / `enable-namespace.sh`

Temporarily route a user's workflows to the default namespace without deleting anything:

```bash
# Disable (user falls back to default namespace)
./scripts/tenant/disable-namespace.sh --email user@company.com

# Re-enable (re-provisions namespace + marks ready)
./scripts/tenant/enable-namespace.sh --email user@company.com
```

The namespace, its Temporal history, and the name reservation are all preserved. Restart the backend after re-enabling.

---

### `disable-account.sh` / `enable-account.sh`

Block or restore login access:

```bash
./scripts/tenant/disable-account.sh --email user@company.com
./scripts/tenant/enable-account.sh  --email user@company.com
```

The account's workflows and credentials are not deleted. Existing JWT sessions stay valid until expiry (~7 days).

---

### `reset-password.sh`

```bash
./scripts/tenant/reset-password.sh --email user@company.com
./scripts/tenant/reset-password.sh --email user@company.com --password newpassword
```

Omit `--password` to generate a strong one and print it once.

---

## Common Workflows

### Add a new tenant from scratch

```bash
./scripts/tenant/onboard-tenant.sh \
  --email admin@acme.com \
  --name "Acme Corp" \
  --namespace tenant-acme

company stop && company dev
```

### Add a user to an existing account without their own namespace

```bash
# They share the default namespace — fine for internal/test accounts
./scripts/tenant/create-user.sh --email intern@company.com --name "Intern"
```

### Temporarily take a tenant offline

```bash
./scripts/tenant/disable-namespace.sh --email admin@acme.com
# No restart needed — next workflow start falls back to default namespace
```

### Restore a disabled tenant

```bash
./scripts/tenant/enable-namespace.sh --email admin@acme.com
company stop && company dev
```

### Check everything at once

```bash
./scripts/tenant/status.sh
```

---

## .env flags

| Flag | Default | Effect |
|---|---|---|
| `MULTI_TENANT_NAMESPACES` | `false` | `true` activates namespace routing; `false` is single-tenant (no DB read, no isolation) |
| `TEMPORAL_TENANT_WORKER_POOL` | `false` | Required `true` when `MULTI_TENANT_NAMESPACES=true` and `TEMPORAL_WORKER_POOL_ENABLED=true` |
| `VITE_AUTH_ENABLED` | `false` | Must be `true` for tenant isolation to apply (without auth all principals resolve to `owner`) |
| `AUTH_MODE` | `single` | `multi` opens registration; `single` closes it after the first account |

Minimum `.env` for multi-tenant dev:

```ini
MULTI_TENANT_NAMESPACES=true
TEMPORAL_TENANT_WORKER_POOL=true
VITE_AUTH_ENABLED=true
AUTH_MODE=multi
```

---

## Isolation guarantees

| Resource | Isolation mechanism |
|---|---|
| Workflows | `owner_user_id` DB column — each user sees only their own |
| Credentials (API keys) | `t:{user_id}:` key prefix — keys are physically separate in `credentials.db` |
| Temporal executions | Separate namespace — controllers, trigger listeners, and activity workers are namespace-scoped |
| WS broadcasts | Per-connection `tenant_id` — trigger events (chat, Telegram, webhook) only reach the owner's browser tabs |

Operator-level integrations (Telegram bot token, Stripe secret, WhatsApp session) are **shared** by design — the operator configures them once for the whole instance.
