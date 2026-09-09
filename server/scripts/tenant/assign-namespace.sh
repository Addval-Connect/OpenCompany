#!/usr/bin/env bash
# Assign a Temporal namespace to a user and provision it on the server.
#
# Registers the namespace (hot — no Temporal restart needed), waits for
# it to be ready, registers the 7 required Search Attributes, and marks
# the assignment as ready in the DB.
#
# Usage:
#   ./assign-namespace.sh --email user@example.com --namespace tenant-acme
#   ./assign-namespace.sh --email user@example.com --namespace tenant-acme --retention-days 14
#
# After running: restart the backend so it connects a client and starts
# workers for the new namespace.
#
# Namespace naming rules:
#   - 3–63 chars, lowercase letters / digits / hyphens
#   - Must not start with a digit or end with a hyphen
#   - "default" and "temporal-system" are reserved

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
check_venv

EMAIL=""
NAMESPACE=""
RETENTION_ARGS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --email)          EMAIL="$2";                    shift 2 ;;
        --namespace)      NAMESPACE="$2";                shift 2 ;;
        --retention-days) RETENTION_ARGS="--retention-days $2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 --email EMAIL --namespace NAME [--retention-days N]"
            exit 0 ;;
        *) oc_err "Unknown argument: $1"; exit 2 ;;
    esac
done

[[ -n "$EMAIL"     ]] || { oc_err "--email is required";     exit 2; }
[[ -n "$NAMESPACE" ]] || { oc_err "--namespace is required"; exit 2; }

oc_header "Assigning namespace '$NAMESPACE' → $EMAIL"
show_data_dir
echo
oc_warn "Temporal must be running (localhost:5681) for namespace registration."
echo
# shellcheck disable=SC2086
$MANAGE namespace --email "$EMAIL" --namespace "$NAMESPACE" $RETENTION_ARGS
echo
oc_ok "Done. Restart the backend to activate the new namespace workers:"
echo "      company stop && company dev"
