# Multi-Tenant Namespaces — the normative reference

One Temporal namespace per tenant, with per-namespace state: databases,
credentials, workspaces. This document is the contract every change to
the tenancy layer is held against: what is physically isolated, what
travels through which channel, and what a new flow must do — and must
NOT do — to stay tenant-correct.

---

## 1. The model: namespace scope travels as context, not as data

A namespace identity crosses two boundaries, and each has exactly one
channel:

```
┌────────────────────────────────────────────────────────────────┐
│  JWT (active_namespace claim, minted at login/switch)          │
└──────────────┬─────────────────────────────────────────────────┘
               │ HTTP middleware / WS connect handler
               │   set_active_namespace(<tenant>)        ← the ONLY edge setter
               ▼
        core.namespace_context ContextVar (active_ns)
               │
     ┌─────────┴──────────────────────────────────────┐
     │  in-process reads (pools, services, routers)   │
     │  get_active_namespace()                        │
     └─────────┬──────────────────────────────────────┘
               │ Temporal boundary: the ContextVar does NOT cross
               │ (activities run on worker threads, HTTP dies)
               ▼
        payload key `credential_customer_id`
               │ Activity interceptor (worker side)
               │   set_active_namespace(<from payload>)  ← the ONLY worker setter
               ▼
        ContextVar again — the activity body and everything it calls
```

Two rules fall out of this shape, and both are enforced by the two
single setters:

1. **Nobody sets the ContextVar by hand.** `set_active_namespace` is
   called from exactly two places: the HTTP/WS edge and the Temporal
   activity interceptor. Every other call site is a bug in waiting —
   the failure mode is a silent read of the wrong tenant's database
   (see §6: this exact bug produced four production incidents).
2. **The payload key exists for one reason**: the ContextVar cannot
   cross the Temporal async boundary. `credential_customer_id` rides
   in the workflow payload, and the interceptor turns it back into a
   ContextVar on the worker side. It is transport, not an API — service
   and node code never reads it directly.

## 2. What is physically isolated (not simulated)

The namespaces are real Temporal namespaces — separate histories,
queues, Visibility stores, and worker pools. Isolation per layer:

| Layer | Isolation | Decided by |
|---|---|---|
| Temporal server | Physical namespace (histories/queues/visibility/workers) | The `Client` connection's `namespace=`; one connected client per tenant in `services/temporal/client_registry.py` |
| Workflow/execution DBs | `namespaces/<ns>/workflow.db` — a separate SQLite file | `DatabasePool.get(get_active_namespace())` |
| Credentials DBs | `namespaces/<ns>/credentials.db` + per-DB salt → distinct Fernet keys | `CredentialsPool` + `NamespacedCredentialsDatabase` |
| Workspaces | `namespaces/<ns>/workspaces/<slug>/` | `services/workspace_locator.py` (namespace-aware since #25) |
| OAuth tokens | Per-namespace store; a tenant connects its own integrations | `NamespacedCredentialsDatabase` (no auth special-casing) |

The activity interceptor does not simulate any of this — it is the
translator at the boundary: "this activity was dispatched for tenant X"
→ "the ContextVar says X, so every pool read below opens X's files".
The Temporal side is already isolated; without the translation, the
isolation breaks at the DB layer, which is where the production
incidents in §6 happened.

## 3. Database layout (stable)

```
{DATA_DIR}/                          ← persistent, OUTSIDE the app tree
  namespaces/
    owner/                           ← shared auth + single-tenant default
      workflow.db                    ← users, namespaces, teams, workflows…
      credentials.db                 ← owner's credentials (per-DB salt)
      workspaces/
    addval-tax/                      ← one dir per tenant
      workflow.db / credentials.db / workspaces/
  packages/temporal/                 ← shared (temporal CLI)
  temporal.db                        ← dev-server state (one, not per-ns)
```

Hard rules:

- **Auth is global.** `users`, `namespaces`, `user_namespaces`,
  `tenant_namespaces`, invite tokens — always the `owner` DB, whatever
  the ContextVar says (`_AUTH_METHODS` in `core/namespaced_db.py`).
  Ownership/assignment never duplicates per tenant.
- **Execution data is per namespace.** Workflows, executions, teams,
  tasks, node parameters, conversations — the tenant's own DB.
- **Subagent permits live in the owner DB on purpose** — keyed by the
  globally-unique `root_execution_id`; routing them per tenant would
  split a run's permit state across databases.
- **Workflow identity.** The DB row id is the stable application key
  (`int`, fork-compatible — it predates the Temporal work and must not
  need UUIDs). Temporal workflow IDs are derived per *execution*
  (`<slug>-<execution_uuid8>`), which is what dedup/identity on the
  Temporal side actually needs. The namespace is never inferred from
  any id — it comes from the mapping (`resolve_tenant_namespace`) or
  the JWT claim.

## 4. Non-multi-tenant compatibility (the off switch)

`MULTI_TENANT_NAMESPACES=false` is byte-identical to the pre-feature
behaviour:

- `resolve_tenant_namespace` returns `Settings.temporal_namespace`
  without touching the database.
- The ContextVar defaults to `"owner"`, so every pool read opens the
  single-tenant files exactly as before.
- The event dispatcher targets the default namespace; the client
  registry is bypassed entirely.
- No node, service, or activity branches on the flag outside
  `services/tenancy.py` and the two edge setters.

A change is only "done" when the flag-off path is unchanged — run the
flag-off tests before and after touching any tenancy surface.

## 5. Provisioning and operations

- Namespaces are **operator-provisioned**, never self-service:
  `scripts/manage_users.py namespace --email <email> --namespace <name>`
  (idempotent: registers on the Temporal server, waits for
  convergence, registers search attributes, upserts the mapping row).
  `assign-namespace` covers many-to-many. Unmapped accounts execute in
  the default namespace.
- Startup **refuses** `MULTI_TENANT_NAMESPACES=true` without
  `TEMPORAL_TENANT_WORKER_POOL=true` when the worker pool is enabled —
  tenant-namespace activities would be scheduled on queues only the
  default pool polls and hang forever without error.
- RAM budget: ~200–370 MB idle per ready namespace (own worker
  manager + pool). 5–7 namespaces per 8 GB of host RAM.
- Deploy invariants live in `deploy/ec2/README.md`: persistent
  `DATA_DIR` in the service account's home, hand-managed-host adoption,
  server-side namespace re-registration after a state migration, and
  the per-namespace encryption-key story (same passphrase, per-DB
  salts — rotating the key orphans every stored credential).

## 6. Production incidents — the case for the middleware

Every incident below is the same structural failure: a place in the
execution path that had to remember to set or pass the namespace, and
didn't. They are kept here as anti-regression cases; each maps to the
layer the refactor removed.

| Incident | What read the wrong scope | Structural hole |
|---|---|---|
| `task_manager` assign failed: "No team exists for this lead execution" (twice: legacy + Temporal paths) | The per-type activity body read the OWNER DB while `prepare_payload` had created the team in the tenant DB | No interceptor; per-activity manual sets missed one activity type |
| `finalize_agent_team` failed: "Failed to finalize team as completed" ×3 → run failed | Read tasks from owner (empty → "nothing pending"), then updated the team status in owner (row absent) | Same — finalize had no namespace context |
| taskTrigger review leg never fired (canvas) | Producer dispatched only through Temporal Visibility (deployed consumers); the canvas waiter resolves only via `event_waiter.dispatch` | Producer-side event fan-out was not namespace/two-paths aware |
| Task-event dispatch missed tenant listeners | `dispatch.emit` queried the DEFAULT namespace's Visibility | `emit` had no namespace parameter plumbed from the producer |
| OAuth 401 `Invalid token lifetime` on `msMailReceive` | The tenant's credential store was empty; the only Microsoft token lived in the owner store | Credential isolation is per namespace (intended) — operator must connect OAuth **in the tenant's namespace**; documented, not code |

The refactor's promise: a new activity, node, or flow cannot reintroduce
these classes of bug, because there is no per-site decision left to get
wrong.

## 7. The middleware model (target architecture)

### Edge (HTTP + WS) — one setter
`middleware/auth.py` and the WS connect handler stamp the ContextVar
from the JWT's `active_namespace` claim (normalized). The claim is
minted at login/switch from the user's namespace assignments; the hot
path never round-trips the DB (`resolve_namespace_from_state`).

### Temporal worker — one interceptor
`services/temporal/_interceptors.py` gains the tenant duty: the
activity inbound interceptor reads `credential_customer_id` from the
activity input and stamps the ContextVar before the activity body runs
— once, for every activity type (per-type `node.*` wrappers, prepare,
llm-step, finalize, delegation lifecycle, permits, polls, stores).
Activity interceptors run only on live executions, so there is no
replay-determinism concern. The observability interceptor already
registered on both workers is the vehicle.

### Propagation rules (unchanged, now explicit)
- `credential_customer_id` must be present in activity payloads —
  workflows stamp it from the run context at scheduling time.
- `_INHERITED_SCOPE_KEYS` carries it to delegated children.
- Auth methods ignore the ContextVar entirely (they always hit owner).

## 8. PR checklist — how not to break multi-tenant

Run this list on any PR that touches execution, events, scheduling, or
credentials:

- [ ] No new `set_active_namespace(` outside the two edges (HTTP/WS
      middleware + Temporal activity interceptor).
- [ ] No service or node code reads `credential_customer_id` directly —
      it reads `get_active_namespace()` or nothing at all.
- [ ] New activity payload includes `credential_customer_id` if the
      body touches namespaced state; new child-workflow args inherit it
      via `_INHERITED_SCOPE_KEYS`.
- [ ] New event producer: dispatched through `dispatch.emit` with the
      namespace resolved from context — and if a canvas-Run waiter
      exists for the event type, through `event_waiter.dispatch` too
      (the two-paths pattern; see twitter/whatsapp_business).
- [ ] New workflow/activity touching team tables: verified against the
      TENANT DB (auth tables are the only owner-routed exception).
- [ ] `MULTI_TENANT_NAMESPACES=false` suite passes unchanged.
- [ ] Credentials/OAuth: per namespace by design — a 401/missing-token
      in tenant X is an operator action in X's namespace, not a bug to
      "fix" by falling back to owner.

## 9. Refactor phases (this document is Phase 1)

| Phase | Scope | Delivered |
|---|---|---|
| 1 | This document — contract, inventory, incident log, PR checklist | ✔ |
| 2 | Edge consolidation: one setter path in auth middleware + WS connect | |
| 3 | Temporal interceptor seals the ContextVar; per-activity manual sets removed | |
| 4 | Node de-invasion: the 5 namespace-aware nodes read the ContextVar | |
| 5 | Event dispatch resolves namespace from context at the edge | |
| 6 | Cleanup: normalize the credential-ns helpers; final pass | |

Each phase ships and deploys independently; the flag-off guarantee
(§4) gates every phase.
