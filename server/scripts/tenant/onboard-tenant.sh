#!/usr/bin/env bash
# Full tenant onboarding: create account + assign namespace in one command.
#
# Usage:
#   ./onboard-tenant.sh --email user@example.com --name "Acme Corp" \
#                       --namespace tenant-acme
#   ./onboard-tenant.sh --email user@example.com --name "Acme Corp" \
#                       --namespace tenant-acme --password secret123 \
#                       --retention-days 14
#
# Steps performed:
#   1. Create the login account (generates a password if --password is omitted)
#   2. Assign and provision the Temporal namespace
#
# Requires Temporal to be running for namespace provisioning (step 2).
# After running: restart the backend.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
check_venv

EMAIL=""
NAME=""
NAMESPACE=""
PASSWORD_ARG=""
RETENTION_ARGS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --email)          EMAIL="$2";                    shift 2 ;;
        --name)           NAME="$2";                     shift 2 ;;
        --namespace)      NAMESPACE="$2";                shift 2 ;;
        --password)       PASSWORD_ARG="--password $2";  shift 2 ;;
        --retention-days) RETENTION_ARGS="--retention-days $2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 --email EMAIL --name NAME --namespace NS [--password PW] [--retention-days N]"
            exit 0 ;;
        *) oc_err "Unknown argument: $1"; exit 2 ;;
    esac
done

[[ -n "$EMAIL"     ]] || { oc_err "--email is required";     exit 2; }
[[ -n "$NAME"      ]] || { oc_err "--name is required";      exit 2; }
[[ -n "$NAMESPACE" ]] || { oc_err "--namespace is required"; exit 2; }

oc_header "Onboarding tenant: $EMAIL → $NAMESPACE"
show_data_dir
echo

# Step 1 — create account
oc_header "[1/2] Creating account"
# shellcheck disable=SC2086
$MANAGE add --email "$EMAIL" --name "$NAME" $PASSWORD_ARG
echo

# Step 2 — assign namespace
oc_header "[2/2] Assigning namespace '$NAMESPACE'"
oc_warn "Temporal must be running (localhost:5681)."
echo
# shellcheck disable=SC2086
$MANAGE namespace --email "$EMAIL" --namespace "$NAMESPACE" $RETENTION_ARGS
echo
oc_ok "Tenant onboarded. Restart the backend to activate namespace workers:"
echo "      company stop && company dev"
