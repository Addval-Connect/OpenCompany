#!/usr/bin/env bash
# Block sign-in for an account (reversible — keeps the row and all data).
#
# Use this instead of reset-password when access must stop immediately.
# The account's workflows and credentials are preserved.
#
# Usage:
#   ./disable-account.sh --email user@example.com

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

oc_header "Disabling account: $EMAIL"
show_data_dir
echo
$MANAGE disable --email "$EMAIL"
echo
oc_warn "Existing JWT sessions stay valid until they expire."
oc_warn "To restore access: ./enable-account.sh --email $EMAIL"
