# EC2 deployment (dedicated instance)

Deploys OpenCompany onto a **dedicated** Ubuntu LTS EC2 instance — nothing else
runs on it, so the app owns the box's memory and its nginx default vhost.

| Concern | Convention |
|---|---|
| App tree | `/opt/opencompany`, owned by `oc-app-user` |
| State | `/home/oc-app-user/.opencompany` — the service account's own home, outside the app tree |
| Process supervision | `supervisor` program `opencompany` |
| Public entrypoint | `nginx` vhost → `127.0.0.1:<PYTHON_BACKEND_PORT>` |
| TLS | `certbot --nginx` (Let's Encrypt, auto-renew via `certbot.timer`) |
| Artifact transport | tarball over `scp`, key pushed by EC2 Instance Connect |
| Logs | `/var/log/opencompany/{app,error}.log` |

This is not `company deploy`. That path provisions a GCP VM with Terraform and
installs the published npm package; this one ships the working tree to an EC2
instance you already own, under supervisor + nginx. They do not share state and
neither knows about the other.

## Files

- `deploy.sh` — run on your machine. Builds, packages, uploads, invokes bootstrap.
- `bootstrap.sh` — runs on the host. Installs Node 22 + uv + certbot, creates
  `oc-app-user`, unpacks, `uv sync`, writes supervisor + nginx config, starts,
  health-checks.
- `users.sh` — run on your machine. Manages login accounts on the host, see
  [Adding users](#adding-users).
- `ssh.sh` — run on your machine. Opens a shell on the host through the same
  Instance Connect flow, with shortcuts for the operations below
  (`--logs`, `--errors`, `--status`, `--restart`, `--health`, `--app`) and
  `--tunnel <ssh -L spec>` for anything the host binds to loopback.
- `temporal.sh` — run on your machine. `on` / `off` / `status` for durable
  execution on a live host, plus `ui` to tunnel the Temporal Web UI, see
  [Execution engine](#execution-engine) and
  [The Temporal Web UI](#the-temporal-web-ui).
- `conf/opencompany.supervisor.conf`, `conf/opencompany.nginx.conf` — templates
  with `__OC_PORT__` / `__OC_DOMAIN__` / `__OC_AWS_ENV__` placeholders.
- `env.production.template` — rendered once to `/opt/opencompany/.env`.

Outside this directory, `server/scripts/manage_users.py` is the host-side half of
`users.sh` — the operator CLI that adds logins on an `AUTH_MODE=single`
deployment where public registration has closed.

## Provision the instance

Anything that gets you a current Ubuntu LTS instance works — console, CLI,
Terraform. What the scripts assume:

| | |
|---|---|
| AMI | **Ubuntu 24.04 LTS** (`bootstrap.sh` uses `apt-get` and NodeSource; 22.04 also works, but its standard support ends April 2027) |
| Size | **t4g.medium (2 vCPU / 4 GB, Graviton)** — see [Sizing](#sizing) for the measurements behind that, and for when to pick x86 instead |
| Disk | **30 GB gp3.** 20 GB boots and runs, but the venv is ~570 MB, the `temporal` CLI is 171 MB extracted, supervisor logs cap at 200 MB, and `workspaces/` grows with use |
| Security group | inbound **80** and **443** from anywhere; **22** from your address or via Instance Connect's [service prefix list](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-connect-setup.html) |
| SSH | no key pair needed at launch — EC2 Instance Connect pushes an ephemeral key per command. See [A plain SSH key for ops](#a-plain-ssh-key-for-ops) if you also want `ssh -i` to work without an AWS session |
| IAM | no instance profile needed — every provider credential, Bedrock's included, is a key stored in the app |

Launch it in the region where **Bedrock model access is enabled for the account**,
if you use Bedrock. `deploy.sh` defaults `OC_BEDROCK_REGION` to the instance's own
region, and Claude access is granted per account *per region* — an instance in a
region you have not opted into returns a 404 that reads like a bad API key. See
[AWS Bedrock: the region](#aws-bedrock-the-region).

Two things worth deciding before the first deploy:

- **Elastic IP.** Without one the public address changes on every stop/start
  (a resize is a stop/start), and the A record has to be re-pointed each time.
  Allocate and associate one unless you have a reason not to.
- **The DNS A record**, pointed at that address. It has to resolve *before*
  `certbot` can issue a certificate.

Then export the instance id — every script requires it and none of them has a
default, because they run privileged commands (`apt-get`, `supervisorctl`,
`install` into `/opt` and `/etc`) against whatever they are pointed at:

```bash
export OC_INSTANCE_ID=i-0123456789abcdef0
export OC_REGION=us-east-1                     # default
ssh-keygen -t ed25519 -N '' -f ~/.ssh/opencompany-ec2   # OC_SSH_KEY default
```

The key must have **no passphrase**: `deploy.sh` derives the public half
unattended with `ssh-keygen -y -P ''` for Instance Connect.

### Sizing

**4 GB is the floor worth paying for, and the numbers are measurable rather than
guessed.** The backend imports at **~193 MB RSS** with all node plugins, FastAPI,
the DI container and the LLM registry loaded — reproduce it with:

```bash
cd server && uv run python -c "
import resource, nodes, main
print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024, 'MB')"
```

`import main` logs a page of INFO lines on the way up; the figure is the last
line of output.

Add the Temporal dev server (a ~200 MB Go process), nginx and the Ubuntu base and
the idle floor is around 600 MB, which is why `bootstrap.sh` provisions a 2 G
swapfile. The per-queue slot ceilings in `TemporalWorkerPool.DEFAULT_CONCURRENCY`
(`rest-api=50`, `triggers-poll=100`, …) are ceilings, not preallocated memory, and
the two queues whose activities are genuinely heavy — `ai-heavy` and `browser` —
are in `RESOURCE_TUNED_QUEUES`, so they size themselves against 80% of host
CPU/memory instead of a fixed count. They adapt to the box; the box is the
decision. 2 GB runs with `temporal.sh off`, and needs
`TEMPORAL_AI_HEAVY_CONCURRENCY` / `TEMPORAL_BROWSER_CONCURRENCY` pinned otherwise.

**Graviton (`t4g`) is ~20% cheaper than `t3` and the stack is arm64-clean.** Worth
stating what that is based on, since it is checkable:

- The dependency set resolves to the **same 149 packages on `aarch64-manylinux_2_28`
  as on `x86_64-manylinux_2_28`** — nothing needs a source build on arm that does
  not already need one on x86 (`googlemaps` is sdist-only on both; it is pure
  Python and needs no compiler):

  ```bash
  cd server
  for p in aarch64 x86_64; do
      uv pip compile pyproject.toml --python-platform $p-manylinux_2_28 \
          --python-version 3.12 --no-header -q -o /tmp/res-$p.txt
  done
  diff /tmp/res-aarch64.txt /tmp/res-x86_64.txt   # expect no output
  ```

  `--no-header` matters: without it uv writes its own invocation into each file,
  so the two differ on that line by construction and the `diff` looks like a
  real disagreement.
- Every lazy binary installer carries an explicit `Linux/aarch64` mapping — the
  `temporal` CLI (`services/temporal/_install.py`), `gh`, `gcloud` (`linux-arm`),
  `stripe` — and `agent-browser` ships a real `bin/agent-browser-linux-arm64`.
- `pydantic-monty`, the one pinned Rust-backed dependency, publishes
  `manylinux_2_17_aarch64` wheels.

**Pick x86 (`t3.medium`) if the browser nodes are load-bearing for you.** Nothing
in the browser stack is known-broken on arm64, but it is the one part that is not
verified above: the harness wants a dedicated Chrome with remote debugging, and on
arm64 Linux that means distro Chromium rather than Google's Chrome `.deb`. About
$6/mo buys away the unknown.

Two notes on that stack either way, unrelated to architecture:

- `agent-browser` declares `engines: node >= 24`, while `bootstrap.sh` installs
  Node 22 (the version the JS/TS code-execution sidecar targets). npm treats
  `engines` as a warning, so the install does not hard-fail — but it is the one
  bundled binary aimed at a newer runtime than the host has.
- Both `agent-browser` (npm) and `browser-harness` (a `uv tool`) install **on
  first use**, into `DATA_DIR/packages/`, not during the deploy. They cost nothing
  until a browser node runs.

## Deploy

```bash
aws login                                          # session must be valid
./deploy/ec2/deploy.sh --domain company.example.com
```

Re-deploys (code only, config and state preserved):

```bash
./deploy/ec2/deploy.sh                             # --domain not needed again
./deploy/ec2/deploy.sh --skip-build                # reuse the existing dist
```

## TLS

`deploy.sh` writes a port-80 vhost and installs `certbot` + the nginx plugin, but
does **not** obtain a certificate — that needs the domain's **A record** to
already resolve to the instance. Once it does:

```bash
./deploy/ec2/ssh.sh 'sudo certbot --nginx -d company.example.com'
```

Certbot rewrites `/etc/nginx/sites-available/opencompany` in place to add the
443 listener. `bootstrap.sh` detects an existing vhost and leaves it alone from
then on, so later deploys cannot clobber the TLS block.

Until certbot has run, `JWT_COOKIE_SECURE=true` in the rendered `.env` means the
browser will refuse the login cookie over plain http — so log in only after TLS
is up, or the form will appear to accept your password and bounce you back.

Both scripts suppress the "run certbot" hint once a certificate exists —
`bootstrap.sh` by looking for `/etc/letsencrypt/live/<domain>/fullchain.pem`,
`deploy.sh` by probing `https://<domain>/`. Printed unconditionally it reads as an
outstanding step on every later update, and acting on it spends Let's Encrypt's
duplicate-certificate rate limit for nothing.

## Runtime shape

- **Dedicated host.** The nginx vhost claims `default_server`, so a request with
  an unknown `Host` header (the bare IP, a stale name) reaches OpenCompany rather
  than nginx's welcome page; `bootstrap.sh` removes Ubuntu's packaged `default`
  site symlink when it installs ours, because two `default_server` vhosts is an
  nginx startup error, not a warning.
- **Client built locally.** `vite build` peaks above what a 2–4 GB instance can
  spare, and an OOM-killed build leaves a half-written `dist/` the server will
  happily serve. The prebuilt `client/dist` is shipped and served by the backend
  itself (`SERVE_STATIC_CLIENT`), so there is one public port, not two.
- **`REDIS_ENABLED=false`** → the cache falls back to SQLite under `DATA_DIR`.
- **2 G swapfile, `vm.swappiness=10`** (`bootstrap.sh` step 2b, idempotent).
  A reserve, not a page store: with no swap a transient spike is not a slowdown,
  it is the OOM killer picking a victim — and on this box the biggest victim
  available is the backend.
- **Auth is on** (`VITE_AUTH_ENABLED=true`, `AUTH_MODE=single`): the first
  account registered becomes the owner and registration then closes. Register
  immediately after the first deploy — until you do, the form is open to anyone
  who finds the host. Further logins come from the operator CLI, see
  [Adding users](#adding-users).
- **Python.** `server/` requires 3.11–3.12, and `uv sync` provisions a uv-managed
  CPython rather than using the system one — so the distro's Python version is not
  a constraint on the AMI choice (22.04 ships 3.10, 24.04 ships 3.12; neither is
  what runs).
- **Dependencies are `uv sync --no-dev`, without `--frozen`.** `server/uv.lock` is
  intentionally not committed, so a clean clone has no lockfile and `--frozen`
  would fail outright — and, worse, a stale lock that happened to ride along in
  the tarball would install yesterday's dependency set silently, because
  `--frozen` does not check the lock against `pyproject.toml` (that is `--locked`).
  Resolving on the host matches what CI does per run. **149 packages**; `--no-dev`
  drops ruff and the pytest plugins, but not `pytest` itself, which `rlms`
  declares as a runtime dependency. No extras are requested, so
  `local-embeddings` (and its torch stack) stays off the box — the embedding and
  long-term-memory paths detect its absence and say so.
- **The public IP is resolved, not pinned.** Every script looks it up from
  `OC_INSTANCE_ID` on each run, so an instance without an Elastic IP keeps
  working after a stop/start without editing anything here. Set `OC_HOST` to
  skip the lookup.

## Adding users

Registration is closed once the owner account exists, and there is no admin UI.
Add further logins from your machine with `users.sh` (needs a valid `aws login`
session; it pushes an ephemeral key and runs the CLI on the host):

```bash
./deploy/ec2/users.sh list
./deploy/ec2/users.sh add --email person@example.com --name "Person Name"
```

The equivalent directly on the host — as `oc-app-user`, because
`/opt/opencompany/.env` is `0600` and owned by it:

```bash
cd /opt/opencompany/server
sudo -u oc-app-user env HOME=/home/oc-app-user .venv/bin/python scripts/manage_users.py list
```

`add` prints a generated password once (only the bcrypt hash is stored); pass
`--password` to set your own. The other subcommands are `passwd`, `rename`,
`disable` / `enable` (reversible, keeps the row) and `remove` (drops the row).
No restart needed — accounts are read per request.

Ownership is not grantable: `provision_user` sets `is_owner` only when the table
is empty, exactly as `/register` does, so the CLI can bootstrap an empty
deployment but can never mint a second owner. For the same reason it refuses to
disable or delete the owner — that would leave a box nobody can administer.

The address must be one the login form accepts — `LoginRequest.email` is an
`EmailStr`, so reserved domains like `example.invalid` or a bare `localhost` are
refused at creation time rather than producing an account that cannot sign in.

**This adds a login, not a tenant.** Every account shares one workflow store and
one credential store, so a new user can see and edit every workflow and use
every API key stored in the Credentials panel. Only add people who should have
that. `AUTH_MODE=multi` (open self-registration) has exactly the same sharing
plus no gate on who signs up — see
[authentication.md](../../docs-internal/authentication.md) Known Limitations.

## State and backups

Everything stateful is under `DATA_DIR`, which defaults to
**`/home/oc-app-user/.opencompany`** — the service account's own home, read from
`passwd` rather than assumed:

```
workflow.db        workflows, settings, executions
credentials.db     Fernet-encrypted API keys and OAuth tokens
workspaces/        per-workflow files written by nodes
packages/          downloaded service binaries
```

Putting it in the service account's home is structural, not tidiness. The account
that reads and writes state owns every component of the path, so no step in the
deploy has to grant permissions on a directory it does not own — and the location
is **outside the app tree**, which puts it beyond the reach of the deploy tarball
entirely rather than one `tar` path away from it.

`bootstrap.sh` verifies this rather than assuming it: after creating the
directories it writes and removes a probe file **as `oc-app-user`**, and fails the
deploy if that does not work. Ownership on the leaf is not sufficient on its own —
the service also needs execute (traverse) on every parent, so a `DATA_DIR` under
another account's `0700` home would create and `chown` fine here and then fail at
runtime. On failure it prints `namei -l` for the path so the offending component
is visible immediately.

`API_KEY_ENCRYPTION_KEY` in `/opt/opencompany/.env` is the only key that can
decrypt `credentials.db`. A backup of the DB without that key is useless, and
rotating the key orphans every stored credential — there is no re-encryption
path. `bootstrap.sh` therefore never rewrites an existing `.env`.

### A deploy never moves state

`DATA_DIR` and `WORKSPACE_BASE_DIR` are set on the **first** install and are
**read, never written**, on every deploy after it. An update cannot relocate
state, and that matters more than it sounds: a moved `DATA_DIR` does not fail —
it brings up a working, *empty* deployment while the real `workflow.db` and
`credentials.db` sit untouched next to it. That looks exactly like data loss.

So on a re-deploy `bootstrap.sh` reads both keys out of the deployed `.env` and
prints what it found. The operator's value always wins; if this release's
`env.production.template` disagrees, it says so and changes nothing:

```
==> State directories (read from .env, not rewritten)
  DATA_DIR        /home/oc-app-user/.opencompany
  workspaces      /home/oc-app-user/.opencompany/workspaces
```

Three consequences worth knowing:

- **The directories it creates are the ones the app will open.** It resolves
  `WORKSPACE_BASE_DIR` the same way `Settings.workspace_base_resolved` does —
  relative under `DATA_DIR`, absolute as-is — instead of assuming
  `<DATA_DIR>/workspaces`. Point it at a separate EBS volume and that is where
  workspaces are created.
- **The untar is checked, not trusted.** `deploy.sh` packages only code paths, so
  nothing in the artifact reaches `DATA_DIR` — but that invariant lives in a
  different file on a different machine, so `bootstrap.sh` refuses to extract an
  artifact containing any path under the state directory rather than discovering
  it by overwriting a database.
- **The post-untar `chown` is scoped to the delivered paths**, not `chown -R
  /opt/opencompany`, which would walk the whole workspaces tree on every deploy.

`DATA_DIR` is written as an **absolute** path, not as `~/.opencompany`. The app
does expand `~` (`Path(base).expanduser()`), against the running process's `HOME`,
which the supervisor program sets correctly — but any operator command run without
it (a root shell, a cron entry, a forgotten `sudo -u oc-app-user`) expands to a
different home and quietly opens an *empty* database. An absolute path cannot be
misread. A hand-edited `~/...` in `.env` is still accepted and is expanded against
`oc-app-user`'s home, never root's — which is the trap worth naming, since
`bootstrap.sh` itself runs as root.

`WORKSPACE_BASE_DIR` is pinned in `env.production.template` even though its value
matches the default. Unpinned, it is inherited from `.env.template` — which ships
*inside the deploy tarball* and is overwritten on every upload — so the location
of every per-workflow file would be decided by whatever upstream last set that
default to.

**Relocating state is a deliberate migration, not a redeploy:** stop the app, move
the tree, edit `/opt/opencompany/.env`, restart.

```bash
./deploy/ec2/ssh.sh --status                       # confirm what is running
./deploy/ec2/ssh.sh 'sudo supervisorctl stop opencompany'
./deploy/ec2/ssh.sh 'sudo mv /home/oc-app-user/.opencompany /mnt/oc-data'
./deploy/ec2/ssh.sh 'sudo chown -R oc-app-user:oc-app-user /mnt/oc-data'
./deploy/ec2/ssh.sh 'sudo -u oc-app-user sed -i "s|^DATA_DIR=.*|DATA_DIR=/mnt/oc-data|" /opt/opencompany/.env'
./deploy/ec2/ssh.sh --restart
```

Append the `DATA_DIR` line rather than editing in place if you would rather not
touch existing lines — last assignment wins.

### Renaming the service account

`APP_USER` in `bootstrap.sh` is the only place the account name is written for the
deploy proper: the supervisor config carries `__OC_APP_USER__` / `__OC_APP_HOME__`
placeholders rather than literals, so the program cannot end up pointing at an
account that no longer exists. (`ssh.sh`, `users.sh` and `temporal.sh` each hold
one `APP_USER=` of their own, since they run from the developer machine and never
read the host's `bootstrap.sh`.)

Changing it on a **live** host is a migration, not a redeploy, for the same reason
moving `DATA_DIR` is: the deployed `.env` still names the old account's home, and
the new account cannot write it. That fails loudly — the step 3b write probe exits
non-zero and prints `namei -l` — rather than silently starting on an empty
database, which is the intended behaviour, but it does mean the deploy stops
half-done. Move the state and the ownership first, then redeploy:

```bash
./deploy/ec2/ssh.sh 'sudo supervisorctl stop opencompany'
./deploy/ec2/ssh.sh 'sudo mv /home/<old>/.opencompany /home/<new>/.opencompany'
./deploy/ec2/ssh.sh 'sudo chown -R <new>:<new> /home/<new>/.opencompany /opt/opencompany'
./deploy/ec2/ssh.sh 'sudo -u <new> sed -i "s|^DATA_DIR=.*|DATA_DIR=/home/<new>/.opencompany|" /opt/opencompany/.env'
```

On a host that has no state worth keeping, the shorter path is to remove
`/opt/opencompany` and the old home and deploy fresh.

## Execution engine

`TEMPORAL_ENABLED=true` by default: durable execution, per-node retries, and
deployments that keep running across a restart. The dev server is spawned by the
backend itself (`services/temporal/lifecycle.py`), binds **loopback only** on
`TEMPORAL_FRONTEND_GRPC_PORT` / `TEMPORAL_UI_PORT`, and persists to
`data/temporal.db`. First boot downloads the 41 MB `temporal` CLI archive into
`data/packages/temporal/` (171 MB extracted) — expect that once, in
`error.log`, as a pooch progress bar.

`bootstrap.sh` renders `.env` once and never rewrites it, so a live host does not
pick up a changed `env.production.template`. Flip it without a redeploy:

```bash
./deploy/ec2/temporal.sh status
./deploy/ec2/temporal.sh on        # ensures swap, rewrites the block, restarts, waits for /health
./deploy/ec2/temporal.sh off       # back to the in-process sequential executor
```

The script rewrites only a marked block appended at the **end** of `.env` (last
assignment wins for python-dotenv and pydantic-settings), copies everything above
it through untouched, and leaves the previous file as `.env.bak` — that file holds
the only key that can decrypt `credentials.db`.

Verify with `/health`: `"temporal":{"enabled":true,"connected":true}`.
`"execution_engine":{"enabled":false}` next to it is **not** a problem — that
field reports `REDIS_ENABLED`, not Temporal.

### The Temporal Web UI

Same console as local development (`:5680` there), reached over an SSH
port-forward rather than an opened port:

```bash
./deploy/ec2/temporal.sh ui        # then open http://localhost:15680
```

Ctrl-C closes it. Nothing to configure on the host — the UI port is read out of
the deployed `.env` at call time, so a port change needs no edit here. No AWS
session is needed either, provided an
[ops key](#a-plain-ssh-key-for-ops) is installed and the host's address has been
cached once.

**It is a tunnel because it must never be published.** The Temporal Web UI ships
**no authentication** and can terminate running workflows, so exposing it would
be strictly worse than exposing the app itself, which at least has a login. Two
things keep it private and both should stay that way: the dev server passes no
`--ip` to `temporal server start-dev`, so it binds `127.0.0.1` only, and the
security group admits nothing but 80/443. A tunnel needs neither relaxed.

**The local port is deliberately not the same number.** It defaults to the host's
UI port + 10000 (`5680` → `15680`) because a local dev stack usually already owns
`5680`; the forward would fail, the browser would answer from the local server,
and you would be reading a real, plausible Temporal UI of the **wrong cluster**.
`ssh.sh --tunnel` passes `ExitOnForwardFailure=yes` so that collision is a hard
error instead of a silent one, but the offset means it does not normally happen.
Override with `OC_UI_LOCAL_PORT=18080` if 15680 is taken too.

The forward is a thin wrapper over a generic primitive, usable for anything else
the host keeps on loopback:

```bash
./deploy/ec2/ssh.sh --tunnel 15680:127.0.0.1:5680
```

Instance Connect's ephemeral key is checked only when the connection is
*established*, so the ~60 s validity window does not cap how long you hold the
tunnel open.

Both are `ssh -L` underneath, so the raw equivalent works from anywhere the ops
key does — worth knowing because it is the form a GUI client wants:

```bash
ssh -i ~/.ssh/opencompany-ops.pem -N -o ExitOnForwardFailure=yes \
    -L 15680:127.0.0.1:5680 ubuntu@<host>
```

`-N` means *forward only, no shell*, so a working tunnel prints **nothing at
all** and looks hung — the only sign it worked is that the browser answers. Add
`-f` to send it to the background instead, and close it with
`pkill -f 'L 15680:127.0.0.1:5680'` since there is then no Ctrl-C to give. Prefer
the script anyway when the port or the address may have changed: the raw command
pins both, and after a `TEMPORAL_UI_PORT` change it keeps forwarding a port
nothing listens on.

**Trap worth knowing:** the supervisor program runs `python -m uvicorn` directly,
not `company serve`, so nothing exports `.env` into the process environment. Keys
read through `Settings` (`TEMPORAL_ENABLED`, ports, auth, `DATA_DIR`, …) work
because pydantic-settings reads the file itself. Keys read from `os.environ` —
`TEMPORAL_<QUEUE>_CONCURRENCY` / `_RATE_LIMIT`, `AWS_*`, and everything
`.env.template` marks as plugin-owned rather than a Settings field — are silently
ignored there. Put those in the supervisor program's `environment=` line instead.
The per-queue defaults that apply are therefore the `DEPLOYMENT_MODE=cloud`
ones, with `ai-heavy` and `browser` resource-tuned against host CPU/memory; on
anything smaller than 4 GB, pin `TEMPORAL_AI_HEAVY_CONCURRENCY` and
`TEMPORAL_BROWSER_CONCURRENCY` down on that line.
`AWS_REGION` is the one such key the deploy sets for you — `bootstrap.sh`
substitutes it into that line, see [AWS Bedrock: the region](#aws-bedrock-the-region).

## AWS Bedrock: the region

The `bedrock` LLM provider reaches the same Claude models as `anthropic`, billed
through your AWS account. **The credential is a Bedrock API key** — the `ABSK…`
bearer token from the Bedrock console, pasted into the Bedrock slot of the
Credentials panel like any other provider key. It is encrypted into
`credentials.db` and this deployment config never sees or handles it.

The one thing the deploy *does* have to supply is the **region**, and it is easy
to miss why: a bearer token carries no region, and Bedrock's endpoint is
regional (`bedrock-runtime.<region>.amazonaws.com`). `BedrockProvider` resolves
the region before it looks at the credential at all, so this applies no matter
how you authenticate. With nothing set, the Anthropic SDK logs
`No AWS region specified, defaulting to us-east-1` and a model family enabled
only elsewhere returns a **404 that reads like a bad key**.

`bootstrap.sh` therefore writes `AWS_REGION` into the supervisor program's
`environment=` line, not into `.env`, and that is not a style choice:
`BedrockProvider.resolve_region` reads `os.environ`, while the supervisor program
runs `uvicorn` directly and nothing exports `.env` into the process. An
`AWS_REGION` in `.env` reaches `Settings` (where only the Secrets Manager
credential backend would read it) and the SDK never sees it.

The value is `OC_BEDROCK_REGION` → `OC_REGION` → the instance's own region from
IMDSv2. If none resolve, the **whole assignment is omitted** rather than written
empty — botocore reads a blank `AWS_REGION` as a configured-but-empty region,
which is not the same as an absent one — and `providers.bedrock.aws_region` in
`server/config/llm_defaults.json` applies instead.

Changing regions is therefore a redeploy, not an `.env` edit:

```bash
OC_BEDROCK_REGION=us-west-2 ./deploy/ec2/deploy.sh --skip-build
```

The region is a separate decision from where the instance runs: Claude model
access is granted **per account per region** in the Bedrock console, so an
account enabled only in `us-east-1` must invoke there even from an instance
elsewhere. That console opt-in is the one step nothing here can do for you.
Until it is done, a valid key still 404s on `us.anthropic.claude-opus-5` —
model ids are cross-region **inference profile** ids, and the profile exists
without being enabled for your account.

> Instance-role auth (`aws-sigv4`) is the provider's other mode: leave the
> credential slot empty and botocore signs with the host's own AWS credentials,
> so no secret is stored anywhere. It needs `bedrock:InvokeModel` on an instance
> profile, which this deploy does **not** set up — nothing here creates or
> attaches an IAM role. See `server/services/llm/providers/bedrock.py` if you
> want that instead.

## Operations

From your machine (`ssh.sh` pushes the ephemeral key first):

```bash
./deploy/ec2/ssh.sh --status
./deploy/ec2/ssh.sh --logs
./deploy/ec2/ssh.sh --restart
./deploy/ec2/ssh.sh --health
./deploy/ec2/ssh.sh                               # plain shell
./deploy/ec2/temporal.sh status                   # execution engine + memory
./deploy/ec2/temporal.sh ui                       # Temporal Web UI on localhost
```

The Bedrock region the service process actually has (it lives in the supervisor
program's environment, not `.env`):

```bash
./deploy/ec2/ssh.sh "sudo grep -o 'AWS_REGION=\"[^\"]*\"' /etc/supervisor/conf.d/opencompany.conf"
```

If the instance has **no Elastic IP**, re-point the A record after any
stop/start (a resize is one):

```bash
aws ec2 describe-instances --instance-ids "$OC_INSTANCE_ID" \
    --query 'Reservations[].Instances[].PublicIpAddress' --output text
# then UPSERT the A record for your domain (TTL 300 keeps the window short)
```

The scripts themselves need no update — they resolve the address from
`OC_INSTANCE_ID` on every run.

On the host:

```bash
sudo supervisorctl status opencompany
sudo supervisorctl restart opencompany
sudo tail -f /var/log/opencompany/app.log
sudo tail -f /var/log/opencompany/error.log
curl -fsS http://127.0.0.1:<port>/health          # on the host
```

### A plain SSH key for ops

Every script here reaches the host through EC2 Instance Connect, which needs a
valid AWS session and the AWS CLI on the machine you are sitting at. That is the
right default — nothing long-lived to leak — but it is the wrong tool from a
laptop without credentials, a jump box, or a GUI client.

Once such a key exists at `~/.ssh/opencompany-ops.pem` (override with
`OC_OPS_KEY`), `ssh.sh` uses it **automatically whenever there is no AWS
session** — so `--logs`, `--status`, `temporal.sh ui` and the rest keep working
without `aws login`. It stays a fallback rather than a preference: a long-lived
key in `authorized_keys` is the thing Instance Connect exists to avoid.

The one thing the fallback cannot do is resolve the host's address, since that
lookup is itself an AWS call. So every session-backed call caches the address at
`~/.cache/opencompany/ec2-host-<instance-id>` and the fallback reads it back —
run any command once with a session and the offline path works from then on, or
set `OC_HOST=<ip>` and skip the cache entirely. The cache is keyed by instance id
deliberately: one shared file that outlived its instance would aim privileged
commands (`supervisorctl restart`, `.env` rewrites) at whatever host answered
next.

Two things to know before reaching for the instance's `.pem`: an instance launched
this way **has no key pair** (`KeyName` is null), and AWS only accepts `KeyName` at
launch, so **a key pair cannot be attached to a running instance**. There is no
`.pem` to download, and creating one means replacing the instance. Note also that
`/home/ubuntu/.ssh/authorized_keys` starts **empty** — Instance Connect serves its
ephemeral keys through sshd's `AuthorizedKeysCommand`, not that file — so anything
you add there is the host's only persistent credential.

Generate a key and install it yourself instead. RSA in traditional PEM rather than
ed25519, because that is what every GUI client will load:

```bash
ssh-keygen -t rsa -b 4096 -m PEM -N '' -C "opencompany-ops" \
    -f ~/.ssh/opencompany-ops.pem
chmod 400 ~/.ssh/opencompany-ops.pem
mv ~/.ssh/opencompany-ops.pem.pub ~/.ssh/opencompany-ops.pub

# Installed over Instance Connect, which is still how you bootstrap trust.
# grep -qF first: appending unconditionally duplicates the line on every re-run.
PUBKEY=$(cat ~/.ssh/opencompany-ops.pub)
./deploy/ec2/ssh.sh "
  sudo grep -qF '$PUBKEY' /home/ubuntu/.ssh/authorized_keys \
    || echo '$PUBKEY' | sudo tee -a /home/ubuntu/.ssh/authorized_keys >/dev/null
  sudo chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys
  sudo chmod 600 /home/ubuntu/.ssh/authorized_keys"

ssh -i ~/.ssh/opencompany-ops.pem -o IdentitiesOnly=yes ubuntu@<host>
```

`-N ''` leaves it passphrase-less, which is what an AWS-issued `.pem` is too. Add
one with `ssh-keygen -p -f ~/.ssh/opencompany-ops.pem` — safe for interactive ops,
but do **not** point `OC_SSH_KEY` at a passphrase-protected key: the scripts derive
its public half unattended with `ssh-keygen -y -P ''`, which cannot prompt.

Keep it distinct from the deploy key (`OC_SSH_KEY`, ed25519 by default) so either
can be revoked without breaking the other. It grants **passwordless sudo** as
`ubuntu`, and the only thing standing in front of it is the security group's port
22 rule — so keep that scoped to an address you control, never `0.0.0.0/0`. Revoke
by deleting the line:

```bash
./deploy/ec2/ssh.sh "sudo sed -i '/opencompany-ops/d' /home/ubuntu/.ssh/authorized_keys"
```

Keep the key outside the repo anyway (`~/.ssh/` above). `.gitignore` does cover
`**/*.pem` and `**/*.key`, but that protection is keyed on the *extension* — the
same key saved as `opencompany-ops` or `ops-key.txt` is not ignored, and is one
`git add -A` from being published.

### One log line that looks like a failure and is not

Every cold boot logs a Temporal connection failure before it succeeds:

```
[warning] Temporal connection attempt 1/1 failed: ... ConnectionRefused
[error  ] Failed to connect to Temporal server at localhost:<port> after 1 attempts
  [Temporal] Connect attempt 1 failed for localhost:<port> (ns=default); retrying in 3s
  [Temporal] Worker started, execution engine ready (attempt 2)
```

The backend and its embedded Temporal server come up in the same process, and the
first client connect races the server's listener. It retries 3s later and
succeeds — note the `attempt 2` line, and confirm with `"temporal":
{"connected": true}` in `/health`. The `error` level on a self-healing retry is
the application's own logging, not something the deploy configures; do not chase
it, and do not alert on it.
