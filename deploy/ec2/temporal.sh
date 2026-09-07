#!/usr/bin/env bash
#
# OpenCompany -- turn Temporal on or off on the EC2 host, FROM your machine.
#
#   ./deploy/ec2/temporal.sh status              # what the host runs right now
#   ./deploy/ec2/temporal.sh on                  # durable execution (Temporal)
#   ./deploy/ec2/temporal.sh off                 # in-process sequential executor
#
# Why a script instead of "edit .env": bootstrap.sh renders /opt/opencompany/.env
# once and never rewrites it -- the file holds API_KEY_ENCRYPTION_KEY, and
# rotating that orphans every stored credential -- so a live deployment does not
# pick up a changed env.production.template. This rewrites ONLY a marked block
# appended at the end of .env, which wins because python-dotenv and
# pydantic-settings both take the last assignment of a key. The rest of the file,
# secrets included, is copied through byte for byte, and the previous version is
# kept as .env.bak.
#
# The keys written by `on` are read out of env.production.template rather than
# repeated here, so a live host and a fresh deploy cannot drift apart.
#
# Transport is ssh.sh (EC2 Instance Connect), so the same environment overrides
# apply: OC_INSTANCE_ID (required), OC_HOST, OC_REGION, OC_SSH_KEY, OC_SSH_USER.
# Requires a valid AWS session (`aws login`).
#
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SSH="${SCRIPT_DIR}/ssh.sh"

APP=opencompany
ENV_FILE=/opt/${APP}/.env
# The unprivileged service account bootstrap.sh creates; keep in step with
# APP_USER there. .env must stay owned by it -- root-owned and the backend
# cannot read the key that decrypts credentials.db.
APP_USER=oc-app-user

# Sentinel for the managed block. Kept free of quote characters: it travels
# through an ssh command string and an awk program.
MARK="# --- Temporal toggle: managed by deploy/ec2/temporal.sh, edits here are lost ---"

ACTION=${1:-status}

# Idempotent swap provisioning, the same step bootstrap.sh runs -- repeated
# because hosts deployed before that step exists have no swap, and Temporal is
# what makes swap matter: a ~200 MB dev server plus nine per-queue workers on a
# 2 GB box leaves an unswapped kernel no option but the OOM killer, whose usual
# pick is the backend itself.
read -r -d '' ENSURE_SWAP <<'SWAP' || true
if [ -z "$(swapon --show --noheadings 2>/dev/null)" ]; then
    echo "==> No swap configured -- creating a 2G swapfile"
    sudo sh -c 'fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none'
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null
    sudo swapon /swapfile
    grep -q "^/swapfile[[:space:]]" /etc/fstab || echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
    echo "vm.swappiness=10" | sudo tee /etc/sysctl.d/60-opencompany-swappiness.conf >/dev/null
    sudo sysctl -q -w vm.swappiness=10
fi
SWAP

block_on() {
    printf '%s\n' "$MARK"
    # Every TEMPORAL_ key the production template sets, verbatim -- one source
    # of truth for what "on" means, whether it arrives by deploy or by flip.
    grep -E '^TEMPORAL_[A-Z_]+=' "${SCRIPT_DIR}/env.production.template"
}

block_off() {
    printf '%s\n%s\n' "$MARK" "TEMPORAL_ENABLED=false"
}

# Reads the deployed .env for both ports. `tail -1` is load-bearing: the file is
# .env.template followed by the production overrides, so overridden keys appear
# twice and the last one is what the server uses.
read -r -d '' READ_PORTS <<'PORTS' || true
PORT=$(sudo grep -E "^PYTHON_BACKEND_PORT=" /opt/opencompany/.env | tail -1 | cut -d= -f2 | tr -d "\r")
GRPC=$(sudo grep -E "^TEMPORAL_FRONTEND_GRPC_PORT=" /opt/opencompany/.env | tail -1 | cut -d= -f2 | tr -d "\r")
UI=$(sudo grep -E "^TEMPORAL_UI_PORT=" /opt/opencompany/.env | tail -1 | cut -d= -f2 | tr -d "\r")
PORTS

report() {
    "$SSH" "
${READ_PORTS}
echo '--- .env (effective, last assignment wins) ---'
sudo grep -E '^(TEMPORAL_ENABLED|DEPLOYMENT_MODE)=' ${ENV_FILE} | tail -2
echo '--- supervisor ---'
sudo supervisorctl status ${APP}
echo '--- listeners (loopback only by design) ---'
ss -ltn | grep -E \":(\$GRPC|\$UI)\" || echo 'temporal: not listening'
echo '--- memory ---'
free -m
swapon --show || echo 'no swap'
echo '--- health ---'
curl -fsS --max-time 10 \"http://127.0.0.1:\$PORT/health\"; echo
"
}

case "$ACTION" in
    status)
        report
        ;;
    on|off)
        if [[ "$ACTION" == "on" ]]; then
            STATE=true
            BLOCK=$(block_on)
            SWAP_STEP="$ENSURE_SWAP"
        else
            STATE=false
            BLOCK=$(block_off)
            SWAP_STEP=""   # swap is harmless and stays; only the toggle reverts
        fi

        echo "==> Applying TEMPORAL_ENABLED=${STATE}" >&2
        "$SSH" "
set -e
${SWAP_STEP}
tmp=\$(mktemp)
# Copy everything above the marker verbatim, then re-append the block. awk can
# simply stop at the marker because the managed block is always last.
sudo awk '/^# --- Temporal toggle:/{exit} {print}' ${ENV_FILE} > \"\$tmp\"
printf '\n%s\n' \"${BLOCK}\" >> \"\$tmp\"
# One rolling backup: this file holds the only key that can decrypt
# credentials.db, so it never gets replaced without a copy on disk first.
sudo cp -a ${ENV_FILE} ${ENV_FILE}.bak
sudo install -o ${APP_USER} -g ${APP_USER} -m 600 \"\$tmp\" ${ENV_FILE}
rm -f \"\$tmp\"
echo '==> Restarting ${APP}'
sudo supervisorctl restart ${APP}
"
        # Second connection on purpose: the first boot with Temporal on
        # downloads the ~170 MB temporal CLI into data/packages/temporal/ before
        # the dev server can start, so readiness is polled rather than assumed.
        echo "==> Waiting for the backend to report its execution engine" >&2
        # /health carries {\"temporal\":{\"enabled\":X,\"connected\":X}} and that
        # pair appears nowhere else in the payload, so it is an exact probe for
        # both directions of the toggle.
        "$SSH" "
${READ_PORTS}
for i in \$(seq 1 60); do
    curl -fsS --max-time 5 \"http://127.0.0.1:\$PORT/health\" 2>/dev/null \
        | grep -q '\"enabled\":${STATE},\"connected\":${STATE}' \
        && { echo \"ready after \$((i*5))s\"; break; }
    sleep 5
done
" || true
        report
        ;;
    -h|--help)
        awk 'NR>1 && !/^#/ {exit} NR>1 {sub(/^# ?/, ""); print}' "$0"
        ;;
    *)
        echo "unknown action: ${ACTION} (expected: on | off | status)" >&2
        exit 2
        ;;
esac
