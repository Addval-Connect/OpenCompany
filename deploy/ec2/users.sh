#!/usr/bin/env bash
#
# OpenCompany -- manage login accounts on the EC2 host FROM your machine.
#
# Thin wrapper over `server/scripts/manage_users.py` on the host: pushes an
# ephemeral SSH key via EC2 Instance Connect (valid ~60s, so nothing long-lived
# is stored), then runs the script as the `oc-app-user` service account -- the
# owner of the 0600 .env that Settings reads.
#
# Every argument is forwarded verbatim:
#
#   ./deploy/ec2/users.sh list
#   ./deploy/ec2/users.sh add --email person@example.com --name "Person Name"
#   ./deploy/ec2/users.sh passwd  --email person@example.com
#   ./deploy/ec2/users.sh rename  --email person@example.com --name "New Name"
#   ./deploy/ec2/users.sh disable --email person@example.com
#   ./deploy/ec2/users.sh remove  --email person@example.com
#
# Requires a valid AWS session (`aws login`). Environment overrides match
# deploy.sh: OC_INSTANCE_ID (required), OC_HOST, OC_REGION, OC_SSH_KEY,
# OC_SSH_USER.
#
# Adding an account here grants access to EVERY workflow and EVERY stored API
# key -- there is no per-user isolation. See deploy/ec2/README.md.
#
set -euo pipefail

INSTANCE_ID=${OC_INSTANCE_ID:-}
[[ -n "$INSTANCE_ID" ]] || {
    echo "OC_INSTANCE_ID is required (the dedicated OpenCompany instance)." >&2
    echo "  export OC_INSTANCE_ID=i-0123456789abcdef0" >&2
    exit 2; }
# Empty on purpose -- without an Elastic IP the address changes on every
# stop/start; resolved from the instance id after the session check.
HOST=${OC_HOST:-}
REGION=${OC_REGION:-us-east-1}
SSH_KEY=${OC_SSH_KEY:-$HOME/.ssh/opencompany-ec2}
SSH_USER=${OC_SSH_USER:-ubuntu}
# The unprivileged service account bootstrap.sh creates; keep in step with
# APP_USER there.
APP_USER=oc-app-user

[[ $# -gt 0 ]] || {
    echo "usage: $0 <list|add|passwd|rename|disable|enable|remove> [options]" >&2
    echo "       $0 add --email person@example.com --name \"Person Name\"" >&2
    exit 2
}

AWS=$(command -v aws || echo "$HOME/.local/bin/aws")

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

# Arguments are re-quoted with printf %q so a display name with spaces survives
# the extra shell hop; the ssh command string is parsed by the remote shell.
REMOTE_ARGS=$(printf ' %q' "$@")

ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=25 -i "$SSH_KEY" \
    "${SSH_USER}@${HOST}" \
    "cd /opt/opencompany/server && sudo -u ${APP_USER} \
     env HOME=\"\$(getent passwd ${APP_USER} | cut -d: -f6)\" \
     .venv/bin/python scripts/manage_users.py${REMOTE_ARGS}"
