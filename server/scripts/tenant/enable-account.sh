#!/usr/bin/env bash
# Restore sign-in for a previously disabled account.
#
# Usage:
#   ./enable-account.sh --email user@example.com

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

oc_header "Re-enabling account: $EMAIL"
show_data_dir
echo
$MANAGE enable --email "$EMAIL"
