#!/usr/bin/env bash
#
# OpenCompany -- deploy to a dedicated EC2 host FROM the developer machine.
#
# Transport is EC2 Instance Connect: it pushes an ephemeral public key, then scp
# delivers a tarball and ssh runs the server-side bootstrap. No long-lived .pem
# is required or stored anywhere.
#
# The React client is built HERE and shipped as dist/ on purpose: `vite build`
# peaks well above what is free on a 2 GB instance, and an OOM-killed build
# leaves a half-written dist that the server will happily serve.
#
#   OC_INSTANCE_ID=i-0123456789abcdef0 \
#     ./deploy/ec2/deploy.sh --domain company.example.com
#
# OC_INSTANCE_ID is REQUIRED and has no default: this instance is dedicated to
# OpenCompany, and bootstrap.sh installs a supervisor program, an nginx vhost and
# a swapfile on whatever it is pointed at. A wrong-but-plausible default here
# would reconfigure someone else's box.
#
# Environment overrides:
#   OC_INSTANCE_ID (required), OC_HOST, OC_REGION, OC_SSH_KEY, OC_SSH_USER,
#   OC_BEDROCK_REGION
#
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$REPO_ROOT"

INSTANCE_ID=${OC_INSTANCE_ID:-}
[[ -n "$INSTANCE_ID" ]] || {
    echo "OC_INSTANCE_ID is required (the dedicated OpenCompany instance)." >&2
    echo "  export OC_INSTANCE_ID=i-0123456789abcdef0" >&2
    echo "See deploy/ec2/README.md for provisioning the instance." >&2
    exit 2; }
# Empty on purpose -- unless the instance carries an Elastic IP its address
# changes on every stop/start, so it is resolved from the instance id in the
# preflight below rather than pinned here where it would go stale silently.
# Setting OC_HOST (an Elastic IP, or a DNS name) skips the lookup.
HOST=${OC_HOST:-}
REGION=${OC_REGION:-us-east-1}
# Same default as ssh.sh / users.sh, deliberately not id_rsa: the
# key is consumed unattended by `ssh-keygen -y -f` to derive the public half for
# Instance Connect, so a passphrase-protected key cannot work here. With no
# askpass in the environment ssh-keygen prints nothing and the failure surfaces
# as a confusing AWS param error ("Invalid length for parameter SSHPublicKey,
# value: 0") rather than "your key is encrypted".
SSH_KEY=${OC_SSH_KEY:-$HOME/.ssh/opencompany-ec2}
SSH_USER=${OC_SSH_USER:-ubuntu}
# The region the Bedrock provider invokes in, which is a separate decision from
# where the instance runs: Claude model access is granted per region in the
# Bedrock console, so an account enabled only in us-east-1 must invoke there
# even from an instance elsewhere. Defaults to the instance's region because
# that is the common case and keeps in-region traffic in-region.
BEDROCK_REGION=${OC_BEDROCK_REGION:-$REGION}
DOMAIN=""
SKIP_BUILD=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain) DOMAIN="$2"; shift 2 ;;
        --skip-build) SKIP_BUILD=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

say() { printf '\n==> %s\n' "$*"; }

AWS=$(command -v aws || echo "$HOME/.local/bin/aws")

# ---------------------------------------------------------------------------
# 1. preflight
# ---------------------------------------------------------------------------
say "Checking AWS session"
"$AWS" sts get-caller-identity >/dev/null || {
    echo "AWS session invalid. Run: aws login" >&2; exit 1; }

[[ -n "$HOST" ]] || HOST=$("$AWS" ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" --region "$REGION" \
    --query 'Reservations[].Instances[].PublicIpAddress' --output text)
[[ -n "$HOST" && "$HOST" != "None" ]] || {
    echo "instance ${INSTANCE_ID} has no public IP (stopped?)" >&2; exit 1; }
say "Target host ${HOST}"

# ---------------------------------------------------------------------------
# 2. build locally
# ---------------------------------------------------------------------------
if [[ $SKIP_BUILD -eq 0 ]]; then
    say "Building client + sidecar locally"
    bun run build
fi
[[ -f client/dist/index.html ]] || { echo "client/dist missing -- run bun run build" >&2; exit 1; }
[[ -f server/nodejs/dist/index.js ]] || { echo "server/nodejs/dist missing -- run bun run build" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 3. package
# ---------------------------------------------------------------------------
# Ships: backend source + lockfile, the prebuilt SPA, the prebuilt sidecar
# bundle, the git-tracked example workflows (core.paths reads them from
# <repo>/.opencompany/workflows, NOT from DATA_DIR), .env.template (the
# authoritative port source read by bootstrap), and deploy/ec2 itself.
# Excludes tests, caches, and every venv/node_modules -- the server rebuilds
# those.
#
# Adding a path here: it must not resolve under the host's DATA_DIR. bootstrap.sh
# refuses to extract an artifact that contains one, because extracting it would
# overwrite workflow.db / credentials.db.
TARBALL=/tmp/opencompany-deploy.tar.gz
say "Packaging"
tar czf "$TARBALL" \
    --exclude='.venv' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='.ruff_cache' \
    --exclude='server/tests' \
    server client/dist .opencompany/workflows .env.template deploy/ec2
du -h "$TARBALL"

# ---------------------------------------------------------------------------
# 4. push an ephemeral SSH key (valid ~60s) and upload
# ---------------------------------------------------------------------------
say "Authorizing SSH key via EC2 Instance Connect"
[[ -f "$SSH_KEY" ]] || {
    echo "SSH key not found: ${SSH_KEY}" >&2
    echo "Generate one with: ssh-keygen -t ed25519 -N '' -f ${SSH_KEY}" >&2
    exit 1; }

# Derived up front, with an empty passphrase, and checked before the API call.
# -P '' makes an encrypted key fail here instead of blocking on an askpass that
# may not exist; the explicit emptiness check turns what AWS would otherwise
# report as "Invalid length for parameter SSHPublicKey, value: 0" into the
# actual problem.
PUBKEY=$(ssh-keygen -y -P '' -f "$SSH_KEY" 2>/dev/null || true)
[[ -n "$PUBKEY" ]] || {
    echo "could not derive a public key from ${SSH_KEY}" >&2
    echo "It is probably passphrase-protected. Instance Connect needs an" >&2
    echo "unattended key -- point OC_SSH_KEY at one without a passphrase." >&2
    exit 1; }

"$AWS" ec2-instance-connect send-ssh-public-key \
    --instance-id "$INSTANCE_ID" \
    --instance-os-user "$SSH_USER" \
    --ssh-public-key "$PUBKEY" \
    --region "$REGION" >/dev/null

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i "$SSH_KEY")

say "Uploading artifact"
scp "${SSH_OPTS[@]}" "$TARBALL" "${SSH_USER}@${HOST}:/tmp/opencompany-deploy.tar.gz"

# ---------------------------------------------------------------------------
# 5. run the server-side bootstrap
# ---------------------------------------------------------------------------
# bootstrap.sh lives inside the tarball, so extract just it first, then let it
# unpack the rest into /opt/opencompany.
say "Running bootstrap on ${HOST}"
DOMAIN_ARG=""
[[ -n "$DOMAIN" ]] && DOMAIN_ARG="--domain ${DOMAIN}"
# Whole flag or nothing: a bare `--aws-region` with an empty value would eat the
# next flag as its argument. Empty is legitimate (OC_REGION="" explicitly), and
# bootstrap.sh then falls back to the instance's own region via IMDS.
AWS_REGION_ARG=""
[[ -n "$BEDROCK_REGION" ]] && AWS_REGION_ARG="--aws-region ${BEDROCK_REGION}"
ssh "${SSH_OPTS[@]}" "${SSH_USER}@${HOST}" bash -s <<EOF
set -euo pipefail
rm -rf /tmp/opencompany-bootstrap
mkdir -p /tmp/opencompany-bootstrap
tar xzf /tmp/opencompany-deploy.tar.gz -C /tmp/opencompany-bootstrap deploy/ec2
chmod +x /tmp/opencompany-bootstrap/deploy/ec2/bootstrap.sh
sudo /tmp/opencompany-bootstrap/deploy/ec2/bootstrap.sh ${DOMAIN_ARG} ${AWS_REGION_ARG} --tarball /tmp/opencompany-deploy.tar.gz
EOF

say "Deployed"
# Probe the public endpoint rather than always appending the certbot caveat: on
# every deploy after the first, TLS is already installed and the parenthetical
# reads as an outstanding step that is not. -f so a 4xx/5xx counts as not-ready,
# and a short timeout so an unreachable host costs seconds, not the whole script.
#
# A GET discarded to /dev/null, NOT -I: the backend declares its routes GET-only,
# so a HEAD gets 405 from Starlette and -f treats a perfectly good TLS setup as
# missing -- which is exactly what the first version of this check did. The body
# is the ~4 KB SPA shell.
if [[ -n "$DOMAIN" ]]; then
    if curl -sf --max-time 8 -o /dev/null "https://${DOMAIN}/" 2>/dev/null; then
        echo "  https://${DOMAIN}"
    else
        echo "  https://${DOMAIN}  (after: sudo certbot --nginx -d ${DOMAIN})"
    fi
fi
echo "  Logs: ssh ${SSH_USER}@${HOST} 'sudo tail -f /var/log/opencompany/app.log'"
