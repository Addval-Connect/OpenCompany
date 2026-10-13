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
     └────────────────────────────────────────────────┘

               Temporal boundary: the ContextVar does NOT cross
               (activities run on worker threads, HTTP dies)

        ┌────────────────────────────────────────────────────────┐
        │  ACTIVITY INTERCEPTOR (the only worker setter)         │
        │  Source of truth: activity.info().namespace — the      │
        │  Temporal isolation boundary ITSELF. An activity is    │
        │  dispatched by the workers of the namespace its        │
        │  workflow lives in, so the boundary says where the     │
        │  execution runs with NO help from the scheduler:       │
        │  polling-spawn, chat, canvas, a feature that forgot    │
        │  the namespace — all route correctly by construction.  │
        │                                                        │
        │  credential_customer_id in the payload = explicit      │
        │  OVERRIDE (rare; e.g. credential scope differing       │
        │  from the Temporal namespace). Not a requirement.      │
        └────────────────────────────────────────────────────────┘
               │
               ▼
        ContextVar — the activity body and everything it calls
```

Two rules fall out of this shape, and both are enforced by the two
single setters:

1. **Nobody sets the ContextVar by hand.** `set_active_namespace` is
   called from exactly two places: the HTTP/WS edge and the Temporal
   activity interceptor. Every other call site is a bug in waiting —
   the failure mode is a silent read of the wrong tenant's database
   (see §6: this exact bug produced four production incidents).
2. **The Temporal namespace is the source of truth on the worker
   side** — not a payload key. The original design derived the
   namespace from `credential_customer_id` in the payload, which
   required every spawn site to plumb it; each missed site was a
   production incident (§6), and the polling-trigger's spawned-run
   payload was the last one. Deriving from `activity.info().namespace`
   makes spawn-site gaps impossible by construction. The payload key
   survives only as an explicit override.

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
| Email-triggered runs failed: "API key for provider 'openai' required" (×6 per mailbox batch) | The `PollingTriggerWorkflow` spawned the run without the namespace key → activities stamped "owner" → `prepare` read the OWNER DB, where the node does not exist → the provider fell back to its hard-coded default (`'openai'`, agent_activities.py) → owner's empty store | The spawn-site plumbing class — the LAST one. Eliminated by deriving the namespace from `activity.info().namespace` (§7): the Temporal boundary is the source, spawn sites cannot miss it |

The refactor's promise, now structural: a new activity, node, or flow
cannot reintroduce these classes of bug, because there is no per-site
decision left to get wrong — the Temporal isolation boundary decides.

## 7. The middleware model (target architecture)

### Edge (HTTP + WS) — one setter
`middleware/auth.py` and the WS connect handler stamp the ContextVar
from the JWT's `active_namespace` claim (normalized). The claim is
minted at login/switch from the user's namespace assignments; the hot
path never round-trips the DB (`resolve_namespace_from_state`).

### Temporal worker — one interceptor
`services/temporal/_interceptors.py` carries the tenant duty: the
activity inbound interceptor resolves the namespace from
`activity.info().namespace` — the Temporal isolation boundary — with
the payload's `credential_customer_id` as an explicit override, and
stamps the ContextVar before the activity body runs — once, for every
activity type (per-type `node.*` wrappers, prepare, llm-step, finalize,
delegation lifecycle, permits, polls, stores). Activity interceptors
run only on live executions, so there is no replay-determinism
concern. The observability interceptor already registered on both
workers is the vehicle.

### Propagation rules (radically simpler)
- **Nothing must carry the namespace for routing to be correct** — the
  Temporal boundary guarantees it. Spawn sites (polling trigger, chat,
  canvas, delegation, upstream features) cannot produce a
  wrong-namespace run.
- `credential_customer_id` may still ride in payloads as an explicit
  override; `_INHERITED_SCOPE_KEYS` carries it to delegated children.
- Auth methods ignore the ContextVar entirely (they always hit owner).
- Permits route per namespace like everything else: a run and all its
  children live in one namespace, so the permit rows for a
  `root_execution_id` land in that namespace's DB consistently.

## 8. PR checklist — how not to break multi-tenant

Run this list on any PR that touches execution, events, scheduling, or
credentials:

- [ ] No new `set_active_namespace(` outside the two edges (HTTP/WS
      middleware + Temporal activity interceptor).
- [ ] No service or node code reads `credential_customer_id` directly —
      it reads `get_active_namespace()` or nothing at all.
- [ ] `credential_customer_id` in payloads is OPTIONAL (the Temporal
      boundary is the default source) — include it only as an explicit
      override when the credential scope must differ from the Temporal
      namespace.
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
| 2 | Edge consolidation — verified: the HTTP middleware + WS connect handler were already the only in-process setters (plus the operator CLI's own process edge) | ✔ (no code change needed) |
| 3 | Temporal interceptor seals the ContextVar; per-activity manual sets removed (11 sites + the `_set_payload_namespace` helper); controlled-poll payload gap fixed | ✔ |
| 4 | Node de-invasion: microsoft.mail_receive, google.gmail_receive, tikhub_action read the ContextVar; the poll pipeline stopped injecting the per-instance attribute; the Connection factory scopes by ContextVar | ✔ |
| 5 | `dispatch.emit` resolves the namespace from the ContextVar when not passed — every push producer (telegram, whatsapp, discord, webhook, email, twitter, chat, todos, agent tasks) gets tenant-scoped delivery from one change | ✔ |
| 6 | Cleanup pass: direct `credential_customer_id` reads in the plugin path replaced by the ContextVar; contract tests assert the single-setter shape | ✔ |
| 7 | **The Temporal boundary becomes the source of truth**: the interceptor resolves from `activity.info().namespace` (payload key demoted to explicit override); permits route per namespace; spawn-site plumbing eliminated by construction (the email-trigger incident, §6) | ✔ |

Each phase shipped independently; the flag-off guarantee (§4) gates
every phase.
