#!/usr/bin/env bash
#
# OpenCompany -- open a shell on the EC2 host FROM your machine.
#
# Same transport as deploy.sh and users.sh: EC2 Instance Connect pushes an
# ephemeral public key (valid ~60s) instead of relying on a long-lived .pem in
# the instance's authorized_keys. The 60s window only gates *opening* the
# connection -- an interactive session stays alive as long as you keep it.
#
#   ./deploy/ec2/ssh.sh                          # interactive shell as ubuntu
#   ./deploy/ec2/ssh.sh --logs                   # tail the app log
#   ./deploy/ec2/ssh.sh --errors                 # tail the error log
#   ./deploy/ec2/ssh.sh --status                 # supervisor program + nginx
#   ./deploy/ec2/ssh.sh --restart                # restart the app
#   ./deploy/ec2/ssh.sh --health                 # /health from inside the host
#   ./deploy/ec2/ssh.sh --app                    # shell as oc-app-user, in /opt
#   ./deploy/ec2/ssh.sh 'sudo supervisorctl status opencompany'
#
# Any trailing arguments are run as a remote command instead of opening a
# shell. Requires a valid AWS session (`aws login`). Environment overrides
# match the sibling scripts: OC_INSTANCE_ID (required), OC_HOST, OC_REGION,
# OC_SSH_KEY, OC_SSH_USER.
#
set -euo pipefail

# Required, and deliberately without a default -- the sibling scripts run
# privileged commands (supervisorctl restart, .env rewrites) through this one.
INSTANCE_ID=${OC_INSTANCE_ID:-}
[[ -n "$INSTANCE_ID" ]] || {
    echo "OC_INSTANCE_ID is required (the dedicated OpenCompany instance)." >&2
    echo "  export OC_INSTANCE_ID=i-0123456789abcdef0" >&2
    exit 2; }
# Deliberately empty: unless the instance carries an Elastic IP its public
# address changes on every stop/start (a resize is one). Resolved from the
# instance id below instead of pinned here, where it would go stale silently.
# Setting OC_HOST skips the lookup.
HOST=${OC_HOST:-}
REGION=${OC_REGION:-us-east-1}
SSH_KEY=${OC_SSH_KEY:-$HOME/.ssh/opencompany-ec2}
SSH_USER=${OC_SSH_USER:-ubuntu}

APP=opencompany
APP_DIR=/opt/${APP}
LOG_DIR=/var/log/${APP}
# The unprivileged service account bootstrap.sh creates; keep in step with
# APP_USER there. These developer-machine scripts each carry their own copy
# because they never read the host's bootstrap.sh; on the host itself the name is
# written once and reaches the supervisor config by substitution.
APP_USER=oc-app-user

# The app runs under supervisor (bootstrap.sh writes
# /etc/supervisor/conf.d/opencompany.conf); only nginx is a systemd unit.
REMOTE_CMD=""

# The port is read from the host's own .env at call time rather than written
# here: .env.template is the single place port numbers live, and a copy in this
# script would silently disagree with the deployment after a port change.
#
# `tail -1` is load-bearing, not defensive: the deployed .env is the template
# followed by the production overrides, so every overridden key appears twice.
# Without it curl gets two port values on two lines and fails with "URL using
# bad/illegal format". Last assignment wins, which is also what
# python-dotenv/pydantic-settings do.
PORT_FROM_ENV="\$(sudo grep -E '^PYTHON_BACKEND_PORT=' ${APP_DIR}/.env | tail -1 | cut -d= -f2 | tr -d '\r')"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --logs)    REMOTE_CMD="sudo tail -f -n 120 ${LOG_DIR}/app.log"; shift ;;
        --errors)  REMOTE_CMD="sudo tail -f -n 120 ${LOG_DIR}/error.log"; shift ;;
        --restart) REMOTE_CMD="sudo supervisorctl restart ${APP} && sudo supervisorctl status ${APP}"; shift ;;
        --health)  REMOTE_CMD="curl -fsS \"http://127.0.0.1:${PORT_FROM_ENV}/health\"; echo"; shift ;;
        --status)  REMOTE_CMD="sudo supervisorctl status ${APP}; systemctl is-active nginx"; shift ;;
        # The service account owns the 0600 .env that Settings reads and the
        # DATA_DIR the server writes, so anything touching those must run as
        # that user rather than as ubuntu with sudo (which would leave
        # root-owned files the service can no longer write). HOME comes from
        # passwd on the host, like everywhere else: DATA_DIR sits under it, and
        # a wrong HOME here would silently open an empty database.
        --app)    REMOTE_CMD="cd ${APP_DIR} && sudo -u ${APP_USER} env HOME=\"\$(getent passwd ${APP_USER} | cut -d: -f6)\" bash -l"; shift ;;
        -h|--help)
            # Print the header comment block verbatim, stopping at the first
            # non-comment line so the usage text and this file cannot drift.
            awk 'NR>1 && !/^#/ {exit} NR>1 {sub(/^# ?/, ""); print}' "$0"
            exit 0 ;;
        *) REMOTE_CMD="$*"; break ;;
    esac
done

AWS=$(command -v aws || echo "$HOME/.local/bin/aws")

[[ -f "$SSH_KEY" ]] || {
    echo "SSH key not found: ${SSH_KEY}" >&2
    echo "Generate one with: ssh-keygen -t ed25519 -N '' -f ${SSH_KEY}" >&2
    exit 1; }

"$AWS" sts get-caller-identity >/dev/null || {
    echo "AWS session invalid. Run: aws login" >&2; exit 1; }

[[ -n "$HOST" ]] || HOST=$("$AWS" ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" --region "$REGION" \
    --query 'Reservations[].Instances[].PublicIpAddress' --output text)
[[ -n "$HOST" && "$HOST" != "None" ]] || {
    echo "instance ${INSTANCE_ID} has no public IP (stopped?)" >&2; exit 1; }

"$AWS" ec2-instance-connect send-ssh-public-key \
    --instance-id "$INSTANCE_ID" \
    --instance-os-user "$SSH_USER" \
    --ssh-public-key "$(ssh-keygen -y -f "$SSH_KEY")" \
    --region "$REGION" >/dev/null

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=25 -i "$SSH_KEY")

if [[ -n "$REMOTE_CMD" ]]; then
    # -t forces a TTY so `tail -f`, `systemctl status`'s pager-less output and
    # an interactive `sudo -u oc-app-user bash -l` all behave, and so Ctrl-C
    # reaches the remote process instead of only killing the local ssh.
    exec ssh -t "${SSH_OPTS[@]}" "${SSH_USER}@${HOST}" "$REMOTE_CMD"
fi

exec ssh "${SSH_OPTS[@]}" "${SSH_USER}@${HOST}"
