#!/usr/bin/env bash
#
# OpenCompany -- server-side install / update, run ON the EC2 host as ubuntu.
#
# The strategy: app tree under /opt/<app> owned by an unprivileged service
# account (oc-app-user), a supervisor program running uvicorn on loopback, an
# nginx vhost in front of it, certbot for TLS, and the artifact delivered as a
# tarball.
#
# Idempotent: safe to re-run for every deploy. It never rewrites an existing
# /opt/opencompany/.env (secret rotation is a data-loss event, see the template)
# and never overwrites an existing nginx vhost (certbot owns it after the first
# --nginx run).
#
#   sudo /tmp/opencompany-deploy/deploy/ec2/bootstrap.sh \
#        --domain company.example.com --tarball /tmp/opencompany.tar.gz
#
# --aws-region sets AWS_REGION in the supervisor program's environment for the
# Bedrock LLM provider. Optional: it defaults to the instance's own region from
# IMDS, and is omitted entirely if that is unavailable.
#
set -euo pipefail

APP=opencompany
APP_DIR=/opt/${APP}
LOG_DIR=/var/log/${APP}
APP_USER=oc-app-user
DOMAIN=""
TARBALL=""
SKIP_NGINX=0
AWS_REGION_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)   DOMAIN="$2"; shift 2 ;;
        --tarball)  TARBALL="$2"; shift 2 ;;
        --aws-region) AWS_REGION_ARG="$2"; shift 2 ;;
        --skip-nginx) SKIP_NGINX=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

[[ -n "$TARBALL" ]] || { echo "--tarball is required" >&2; exit 2; }
[[ -f "$TARBALL" ]] || { echo "tarball not found: $TARBALL" >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 2; }

say() { printf '\n==> %s\n' "$*"; }

# ---------------------------------------------------------------------------
# 1. system packages
# ---------------------------------------------------------------------------
say "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# certbot + its nginx plugin are installed here, not left to the operator: on a
# dedicated instance nothing else has put them there, and the final message of
# this script tells the operator to run `certbot --nginx`. Installing certbot
# does not obtain or install a certificate -- that stays a deliberate manual
# step, because it needs the domain's A record to already resolve here.
apt-get install -y -qq nginx supervisor curl ca-certificates git openssl \
    certbot python3-certbot-nginx >/dev/null

# Node 22 -- required by the on-demand JS/TS code-execution sidecar
# (server/nodejs), which the backend spawns itself. No Ubuntu LTS ships anything
# recent enough (22.04 has Node 12, 24.04 has 18), so NodeSource is not optional.
#
# The floor is 22, not a pin: the guard below skips the install when the host
# already has 22 or newer. One bundled binary wants more -- `agent-browser`
# declares engines: node >=24 -- and npm treats engines as a warning rather than
# an error, so the browser plugin installs and runs here without 24 being
# provisioned for it. See deploy/ec2/README.md -> Sizing.
NODE_MAJOR=$(node -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/' || echo 0)
if [[ "${NODE_MAJOR:-0}" -lt 22 ]]; then
    say "Installing Node.js 22 (found major: ${NODE_MAJOR:-none})"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
    apt-get install -y -qq nodejs >/dev/null
fi
node -v

# uv into /usr/local/bin so oc-app-user and root resolve the same binary. The
# backend venv is built with a uv-managed CPython: server/ requires
# >=3.11,<3.13 and the distro's own interpreter is not used either way (22.04
# ships 3.10, 24.04 ships 3.12).
if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh >/dev/null
fi
uv --version

# ---------------------------------------------------------------------------
# 2. user + directories
# ---------------------------------------------------------------------------
id -u "$APP_USER" >/dev/null 2>&1 || {
    say "Creating ${APP_USER}"
    useradd --system --create-home --shell /bin/bash "$APP_USER"
}
# DATA_DIR is deliberately NOT created here -- it is resolved from the
# deployment's own .env in step 3b, not assumed to be $APP_DIR/data.
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"
install -d -o "$APP_USER" -g "$APP_USER" "$LOG_DIR"

# ---------------------------------------------------------------------------
# 2b. swapfile -- headroom for the Temporal dev server
# ---------------------------------------------------------------------------
# env.production.template enables Temporal, which adds a ~200 MB Go dev server
# and nine per-queue in-process workers on top of the backend. On a 2 GB
# instance with no swap there is no elastic band: a transient spike goes
# straight to the OOM killer, whose usual pick is the backend itself.
# swappiness=10 keeps the file as an emergency reserve rather than a routine
# page store.
#
# deploy/ec2/temporal.sh repeats this check, because hosts provisioned before
# this step existed have no swap and are flipped without a redeploy.
if [[ -z "$(swapon --show --noheadings 2>/dev/null)" ]]; then
    say "No swap configured -- creating a 2G swapfile"
    # fallocate fails on some filesystems (notably ext4 with certain mount
    # options and on ZFS); dd always works, just slower.
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile[[:space:]]' /etc/fstab || printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
    printf 'vm.swappiness=10\n' > /etc/sysctl.d/60-${APP}-swappiness.conf
    sysctl -q -w vm.swappiness=10
fi
swapon --show

# ---------------------------------------------------------------------------
# 3. stop the app before swapping the tree
# ---------------------------------------------------------------------------
if supervisorctl status "$APP" >/dev/null 2>&1; then
    say "Stopping ${APP}"
    supervisorctl stop "$APP" || true
fi

# ---------------------------------------------------------------------------
# 3b. state directories -- resolved from the deployment, never relocated
# ---------------------------------------------------------------------------
# DATA_DIR and WORKSPACE_BASE_DIR decide where everything stateful lives:
# workflow.db, credentials.db, packages/, and the per-workflow workspaces. An
# update must never move them. Moving them does not fail loudly -- it silently
# brings up an empty deployment while the real databases sit untouched next to
# it, which looks like data loss and is the worst possible failure mode here.
#
# So both are READ, never written. On a re-deploy they come from the deployed
# .env, so the operator's value wins even if this release's template has since
# changed. On a first install they come from the template that is about to
# render that .env.
#
# tail -1 is load-bearing: the deployed .env is .env.template followed by the
# override block, so an overridden key appears twice and the LAST assignment is
# the effective one -- the same rule python-dotenv and pydantic-settings apply.
#
# `|| true` on the grep is required, not defensive: `set -e` aborts on a failing
# command substitution, so without it an absent key kills the deploy here instead
# of falling through to the default below.
read_env_key() {   # <file> <key>
    { grep -E "^$2=" "$1" 2>/dev/null || true; } | tail -1 | cut -d= -f2- \
        | tr -d '"'"'"'\r' | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'
}

# oc-app-user's real home, from passwd rather than assumed to be /home/<user>.
# Everything about the default state location hangs off this.
APP_USER_HOME=$(getent passwd "$APP_USER" | cut -d: -f6)
[[ -n "$APP_USER_HOME" ]] || APP_USER_HOME="/home/${APP_USER}"

# State lives in the service account's home by default. Two reasons, both
# structural rather than cosmetic: the account that reads and writes it owns the
# whole path, so no step here has to grant permissions on a directory it does not
# own; and it is outside APP_DIR, which puts it beyond the reach of the deploy
# tarball entirely (see the extraction guard in step 4 -- with this default it
# cannot even apply).
DEFAULT_DATA_DIR="${APP_USER_HOME}/.opencompany"

# ``~`` is expanded against APP_USER's home, NOT root's. This script runs as
# root, so a bare shell expansion of ~/.opencompany here would give
# /root/.opencompany while the service -- which supervisor starts with
# HOME=/home/oc-app-user -- would open /home/oc-app-user/.opencompany. Two
# directories, one of them empty, and nothing would report an error. The app's
# own resolution is Path(base).expanduser()
# (core/paths.py:_resolve_data_path), which is exactly this against the running
# process's HOME.
expand_user_home() {   # <path>
    case "$1" in
        "~")               printf '%s\n' "$APP_USER_HOME" ;;
        "~/"*)             printf '%s\n' "${APP_USER_HOME}/${1#\~/}" ;;
        "~${APP_USER}")    printf '%s\n' "$APP_USER_HOME" ;;
        "~${APP_USER}/"*)  printf '%s\n' "${APP_USER_HOME}/${1#\~"${APP_USER}"/}" ;;
        *)                 printf '%s\n' "$1" ;;
    esac
}

TEMPLATE_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.production.template"
if [[ -f "$APP_DIR/.env" ]]; then
    ENV_SOURCE="$APP_DIR/.env"
else
    ENV_SOURCE="$TEMPLATE_ENV"
fi
[[ -f "$ENV_SOURCE" ]] || { echo "cannot read state config: ${ENV_SOURCE} missing" >&2; exit 1; }

DATA_DIR_VALUE=$(read_env_key "$ENV_SOURCE" DATA_DIR)
WORKSPACE_VALUE=$(read_env_key "$ENV_SOURCE" WORKSPACE_BASE_DIR)
# On a first install the template still carries its placeholder -- substitution
# happens in step 5, which needs the value resolved here.
[[ "$DATA_DIR_VALUE" == "__OC_DATA_DIR__" ]] && DATA_DIR_VALUE=""
: "${DATA_DIR_VALUE:=$DEFAULT_DATA_DIR}"
: "${WORKSPACE_VALUE:=workspaces}"

DATA_DIR_VALUE=$(expand_user_home "$DATA_DIR_VALUE")
WORKSPACE_VALUE=$(expand_user_home "$WORKSPACE_VALUE")

# After tilde expansion, still absolute or it is a config error: a relative
# DATA_DIR resolves against project_root() at runtime, i.e. inside the code tree
# the next deploy overwrites.
case "$DATA_DIR_VALUE" in
    /*) ;;
    *) echo "DATA_DIR must be an absolute path or ~/..., got: ${DATA_DIR_VALUE}" >&2
       echo "  (source: ${ENV_SOURCE})" >&2
       exit 1 ;;
esac

# Settings.workspace_base_dir resolves relative values under DATA_DIR and honours
# absolute ones as-is (core/config.py: workspace_base_resolved). Mirrored here so
# the directory this script creates is the one the app will actually open.
case "$WORKSPACE_VALUE" in
    /*) WORKSPACE_RESOLVED="$WORKSPACE_VALUE" ;;
    *)  WORKSPACE_RESOLVED="${DATA_DIR_VALUE}/${WORKSPACE_VALUE}" ;;
esac

say "State directories (read from $(basename "$ENV_SOURCE"), not rewritten)"
echo "  DATA_DIR        ${DATA_DIR_VALUE}"
echo "  workspaces      ${WORKSPACE_RESOLVED}"

# A template that has moved on while the deployment has not is worth saying out
# loud -- it is exactly the case where someone edits env.production.template,
# re-deploys, and cannot explain why nothing moved. Reported, never acted on.
if [[ "$ENV_SOURCE" != "$TEMPLATE_ENV" && -f "$TEMPLATE_ENV" ]]; then
    TEMPLATE_DATA_DIR=$(read_env_key "$TEMPLATE_ENV" DATA_DIR)
    TEMPLATE_WORKSPACE=$(read_env_key "$TEMPLATE_ENV" WORKSPACE_BASE_DIR)
    if [[ -n "$TEMPLATE_DATA_DIR" && "$TEMPLATE_DATA_DIR" != "$DATA_DIR_VALUE" ]]; then
        echo "NOTE: env.production.template says DATA_DIR=${TEMPLATE_DATA_DIR}; the" >&2
        echo "      deployment keeps ${DATA_DIR_VALUE}. Relocating state is a manual" >&2
        echo "      migration, never a side effect of a deploy." >&2
    fi
    if [[ -n "$TEMPLATE_WORKSPACE" && "$TEMPLATE_WORKSPACE" != "$WORKSPACE_VALUE" ]]; then
        echo "NOTE: env.production.template says WORKSPACE_BASE_DIR=${TEMPLATE_WORKSPACE};" >&2
        echo "      the deployment keeps ${WORKSPACE_VALUE}." >&2
    fi
fi

install -d -o "$APP_USER" -g "$APP_USER" "$DATA_DIR_VALUE" "$WORKSPACE_RESOLVED"

# Prove the service account can actually write there, as that account, before the
# app depends on it. `install -d` above sets ownership on the leaf only, and
# ownership is not the whole story: the service also needs execute (traverse) on
# every parent, so a DATA_DIR under another account's 0700 home creates and chowns
# fine here and then fails at runtime. Cheaper to fail the deploy than to debug a
# backend that starts and cannot open its database.
for dir in "$DATA_DIR_VALUE" "$WORKSPACE_RESOLVED"; do
    sudo -u "$APP_USER" env HOME="$APP_USER_HOME" \
        sh -c 'd=$1; t=$d/.write-check.$$; touch "$t" && rm -f "$t"' _ "$dir" || {
        echo "${APP_USER} cannot write to ${dir}" >&2
        echo "Check ownership and that ${APP_USER} has execute on every parent:" >&2
        namei -l "$dir" >&2 || true
        exit 1; }
done

# ---------------------------------------------------------------------------
# 4. unpack the artifact
# ---------------------------------------------------------------------------
# Code only. --keep-newer-files is deliberately NOT used: the tarball is
# authoritative for code.
#
# That state survives the untar is asserted, not trusted. deploy.sh packages
# `server client/dist .opencompany/workflows .env.template deploy/ec2`, none of
# which reaches DATA_DIR -- but that invariant lives in a different file on a
# different machine, and a future path added there would overwrite a database
# with no warning at all. Checked here, where the consequence is.
#
# awk rather than `grep -q`, and it matches literally rather than as a regex.
# Both matter. `grep -q` exits at the first match, so `tar` upstream dies of
# SIGPIPE and `pipefail` turns the whole pipeline non-zero -- the `if` would then
# be FALSE and the guard would silently not fire, on exactly the large listings
# where it is needed. awk reads to EOF. And a path is not a regex: a `.` in a
# directory name would otherwise match any character.
if [[ "$DATA_DIR_VALUE" == "$APP_DIR"/* ]]; then
    STATE_REL="${DATA_DIR_VALUE#"$APP_DIR"/}"
    if tar tzf "$TARBALL" | sed 's|^\./||' \
        | awk -v p="$STATE_REL" 'index($0, p "/") == 1 || $0 == p { hit = 1 } END { exit !hit }'; then
        echo "REFUSING TO UNPACK: the artifact contains paths under the state" >&2
        echo "directory (${DATA_DIR_VALUE}). Extracting it would overwrite" >&2
        echo "workflow.db / credentials.db. Fix the tar paths in deploy.sh." >&2
        exit 1
    fi
fi

say "Unpacking $(basename "$TARBALL")"
tar xzf "$TARBALL" -C "$APP_DIR"

# Scoped to the top-level paths the tarball actually delivered, NOT
# `chown -R $APP_DIR`: that walks DATA_DIR too. On a deployment with real
# workspaces that is a long recursive pass over state this step has no business
# touching -- and if DATA_DIR is on a slower or larger volume, the pass is the
# most expensive thing in the deploy.
while IFS= read -r top; do
    [[ -n "$top" && "$top" != "." && -e "$APP_DIR/$top" ]] || continue
    chown -R "$APP_USER":"$APP_USER" "$APP_DIR/$top"
done < <(tar tzf "$TARBALL" | sed 's|^\./||' | awk -F/ 'NF && $1 != "" {print $1}' | sort -u)

# ---------------------------------------------------------------------------
# 5. .env -- rendered once, never rewritten
# ---------------------------------------------------------------------------
# The single place port numbers live is .env.template; read it rather than
# repeating a literal here.
PORT_VALUE=$(sed -nE 's/^PYTHON_BACKEND_PORT=([0-9]+).*/\1/p' "$APP_DIR/.env.template" | head -1)
[[ -n "$PORT_VALUE" ]] || { echo "could not read PYTHON_BACKEND_PORT from .env.template" >&2; exit 1; }

if [[ -f "$APP_DIR/.env" ]]; then
    say ".env exists -- leaving it untouched"
else
    [[ -n "$DOMAIN" ]] || { echo "--domain is required on first install" >&2; exit 2; }
    say "Rendering .env"
    # .env.template FIRST, then the production overrides. Many Settings fields
    # are declared without a Python default, so a .env holding only the
    # overrides fails startup with "Field required" on a dozen Temporal keys --
    # the template is not documentation, it is the defaults file.
    #
    # Duplicate keys are safe and intentional: python-dotenv and
    # pydantic-settings both take the LAST assignment, so the appended block
    # wins over the template's dev values. Verified, not assumed.
    {
        cat "$APP_DIR/.env.template"
        printf '\n\n# ===================================================================\n'
        printf '# Production overrides (deploy/ec2/env.production.template).\n'
        printf '# Appended last on purpose: the last assignment of a key wins.\n'
        printf '# ===================================================================\n'
        sed -e "s|__OC_DOMAIN__|${DOMAIN}|g" \
            -e "s|__OC_PORT__|${PORT_VALUE}|g" \
            -e "s|__OC_DATA_DIR__|${DATA_DIR_VALUE}|g" \
            -e "s|__GENERATED_SECRET_KEY__|$(openssl rand -hex 32)|" \
            -e "s|__GENERATED_JWT_SECRET_KEY__|$(openssl rand -hex 32)|" \
            -e "s|__GENERATED_API_KEY_ENCRYPTION_KEY__|$(openssl rand -hex 32)|" \
            "$APP_DIR/deploy/ec2/env.production.template"
    } > "$APP_DIR/.env"
    # 0600: the file holds the credential-encryption key.
    chown "$APP_USER":"$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
fi

# ---------------------------------------------------------------------------
# 6. Python venv
# ---------------------------------------------------------------------------
say "Syncing Python dependencies"
# No --frozen, deliberately. server/uv.lock is intentionally NOT committed (see
# the mcp pin's comment in server/pyproject.toml), so a clean clone has no
# lockfile at all and `uv sync --frozen` fails outright with "Unable to find
# lockfile at `uv.lock`, but `--frozen` was provided" -- a deploy would only
# work from a tree that happened to have a local one, because tar does not read
# .gitignore. The quieter half is worse: --frozen does not verify the lock
# against pyproject.toml (that is --locked), so a stale lock riding along in the
# tarball installs yesterday's dependency set with no warning, and a dependency
# added upstream is simply missing until something imports it. Resolving here
# matches what CI already does on every run.
#
# --no-dev keeps pytest-asyncio/pytest-cov/pytest-mock/coverage/respx/ruff off
# the box. It does not keep pytest itself off: rlms declares pytest as a runtime
# dependency, so it arrives as a transitive of a main dep.
sudo -u "$APP_USER" env HOME="$APP_USER_HOME" \
    uv sync --no-dev --project "$APP_DIR/server"

# The code sidecar's bundle is prebuilt and shipped; only its runtime
# dependency (express) is installed here. Dev deps (esbuild/tsx/typescript)
# stay off the box.
if [[ -f "$APP_DIR/server/nodejs/dist/index.js" ]]; then
    say "Installing sidecar runtime deps"
    sudo -u "$APP_USER" env HOME="$APP_USER_HOME" \
        npm install --omit=dev --no-audit --no-fund --prefix "$APP_DIR/server/nodejs" >/dev/null
else
    echo "WARNING: server/nodejs/dist/index.js missing -- Code nodes will fail" >&2
fi

# ---------------------------------------------------------------------------
# 7. supervisor
# ---------------------------------------------------------------------------
say "Installing supervisor program"

# AWS_REGION for the Bedrock LLM provider. Needed regardless of how Bedrock
# authenticates: BedrockProvider resolves the region BEFORE it looks at the
# credential, because the endpoint is regional
# (bedrock-runtime.<region>.amazonaws.com) and an ABSK bearer token carries no
# region. With nothing set the Anthropic SDK logs "No AWS region specified,
# defaulting to us-east-1" and a model family enabled only elsewhere returns a
# 404 that reads like a bad key.
#
# It belongs in the supervisor program's environment, not in .env:
# BedrockProvider.resolve_region reads os.environ, and this program runs uvicorn
# directly, so nothing exports .env into the process (see the conf template and
# README).
#
# Precedence: --aws-region (passed by deploy.sh from OC_BEDROCK_REGION /
# OC_REGION) > the instance's own region via IMDSv2 > omit the variable.
# Omitting is the correct fallback, not an error: BedrockProvider then falls
# back to providers.bedrock.aws_region in server/config/llm_defaults.json.
# A blank AWS_REGION would NOT do that -- botocore reads it as a configured
# empty region -- which is why the whole assignment is what gets substituted.
AWS_REGION_VALUE="$AWS_REGION_ARG"
if [[ -z "$AWS_REGION_VALUE" ]]; then
    # IMDSv2: token first, and fully best-effort. A host that is not EC2, or
    # one with the metadata endpoint disabled, must not fail the deploy.
    IMDS_TOKEN=$(curl -fsS --max-time 3 -X PUT \
        -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
        http://169.254.169.254/latest/api/token 2>/dev/null || true)
    if [[ -n "$IMDS_TOKEN" ]]; then
        AWS_REGION_VALUE=$(curl -fsS --max-time 3 \
            -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" \
            http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || true)
    fi
fi

if [[ -n "$AWS_REGION_VALUE" ]]; then
    say "Bedrock region for the service process: ${AWS_REGION_VALUE}"
    AWS_ENV_FRAGMENT=",AWS_REGION=\"${AWS_REGION_VALUE}\""
else
    echo "NOTE: no AWS region resolved -- omitting AWS_REGION; Bedrock will use" >&2
    echo "      providers.bedrock.aws_region from server/config/llm_defaults.json" >&2
    AWS_ENV_FRAGMENT=""
fi

sed -e "s|__OC_PORT__|${PORT_VALUE}|g" \
    -e "s|__OC_AWS_ENV__|${AWS_ENV_FRAGMENT}|g" \
    -e "s|__OC_APP_USER__|${APP_USER}|g" \
    -e "s|__OC_APP_HOME__|${APP_USER_HOME}|g" \
    "$APP_DIR/deploy/ec2/conf/${APP}.supervisor.conf" > "/etc/supervisor/conf.d/${APP}.conf"
supervisorctl reread
supervisorctl update

# ---------------------------------------------------------------------------
# 8. nginx
# ---------------------------------------------------------------------------
if [[ $SKIP_NGINX -eq 0 ]]; then
    if [[ -f "/etc/nginx/sites-available/${APP}" ]]; then
        # Certbot rewrites this file in place to add the 443 listener; a blind
        # overwrite would drop the TLS block and break the site.
        say "nginx vhost exists -- leaving it untouched (certbot may own it)"
    else
        [[ -n "$DOMAIN" ]] || { echo "--domain is required to write the vhost" >&2; exit 2; }
        say "Installing nginx vhost for ${DOMAIN}"
        sed -e "s|__OC_DOMAIN__|${DOMAIN}|g" -e "s|__OC_PORT__|${PORT_VALUE}|g" \
            "$APP_DIR/deploy/ec2/conf/${APP}.nginx.conf" > "/etc/nginx/sites-available/${APP}"
        ln -sfn "/etc/nginx/sites-available/${APP}" "/etc/nginx/sites-enabled/${APP}"
        # Ubuntu's packaged site is also `listen 80 default_server`, and nginx
        # refuses to start with two -- so `nginx -t` below would fail the deploy
        # rather than merely warn. Only the symlink is removed; the file stays in
        # sites-available for anyone who wants it back.
        if [[ -e /etc/nginx/sites-enabled/default ]]; then
            say "Disabling nginx's packaged default site"
            rm -f /etc/nginx/sites-enabled/default
        fi
    fi
    nginx -t
    systemctl reload nginx
fi

# ---------------------------------------------------------------------------
# 9. start + verify
# ---------------------------------------------------------------------------
# restart, not start: `supervisorctl update` already autostarted the program,
# so `start` would answer "ERROR (already started)" and skip the reload of a
# re-deployed tree.
say "Starting ${APP}"
# `restart` is stop+start, and this script already stopped the program further up,
# so on every update the stop half answers "ERROR (not running)" -- benign by
# construction, but it reads as a failed deploy in the transcript. Dropped by
# exact match only, so anything else supervisor has to say still comes through;
# the status line and the health check below are what actually gate the deploy.
supervisorctl restart "$APP" 2>&1 | grep -v "^${APP}: ERROR (not running)\$" || true
sleep 10
supervisorctl status "$APP" || true

say "Health check"
if curl -fsS --max-time 10 "http://127.0.0.1:${PORT_VALUE}/health" >/dev/null; then
    echo "OK: backend answering on 127.0.0.1:${PORT_VALUE}"
else
    echo "FAILED: no /health response. Last error log:" >&2
    tail -40 "${LOG_DIR}/error.log" >&2 || true
    exit 1
fi

# Read back from the deployed .env rather than from $DOMAIN, which is empty on a
# re-deploy (the .env is rendered once and never rewritten, so the domain the
# site actually serves lives there). tail -1: overridden keys appear twice.
DEPLOYED_DOMAIN=$(sed -nE 's|^CORS_ORIGINS=\["https://([^"]+)".*|\1|p' "$APP_DIR/.env" | tail -1)

cat <<EOF

Done.
  App tree   ${APP_DIR}
  State      ${DATA_DIR_VALUE}   (workflow.db, credentials.db, workspaces/)
  Logs       ${LOG_DIR}/app.log, ${LOG_DIR}/error.log
  Restart    sudo supervisorctl restart ${APP}
EOF

# Only prompt for TLS when there is no certificate yet. Printed unconditionally,
# this line reads as an outstanding step on every subsequent update -- and an
# operator who takes it at face value re-runs certbot against Let's Encrypt's
# duplicate-certificate rate limit for no benefit.
if [[ -n "$DEPLOYED_DOMAIN" && -s "/etc/letsencrypt/live/${DEPLOYED_DOMAIN}/fullchain.pem" ]]; then
    echo ""
    echo "  TLS        certificate installed for ${DEPLOYED_DOMAIN} (certbot renews it on a timer)"
else
    cat <<EOF

Next, once the DNS A record for the domain resolves to this host:
  sudo certbot --nginx -d ${DEPLOYED_DOMAIN:-<domain>}
EOF
fi
