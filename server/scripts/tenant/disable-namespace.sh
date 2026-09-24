#!/usr/bin/env bash
# Disable a user's Temporal namespace.
#
# The account remains active and can still log in; it falls back to the
# default namespace for workflow execution. The namespace name stays
# reserved in the DB so it can be re-enabled without re-provisioning.
# History in Temporal is preserved.
#
# Usage:
#   ./disable-namespace.sh --email user@example.com

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
check_venv

EMAIL=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --email) EMAIL="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 --email EMAIL"
            exit 0 ;;
        *) oc_err "Unknown argument: $1"; exit 2 ;;
    esac
done

[[ -n "$EMAIL" ]] || { oc_err "--email is required"; exit 2; }

oc_header "Disabling namespace for $EMAIL"
show_data_dir
echo
$MANAGE namespace --email "$EMAIL" --disable
echo
oc_warn "No restart needed — the account falls back to the default namespace immediately."
oc_warn "To re-enable: ./enable-namespace.sh --email $EMAIL"
