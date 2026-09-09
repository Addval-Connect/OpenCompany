#!/usr/bin/env bash
# Reset a user's password.
#
# Usage:
#   ./reset-password.sh --email user@example.com
#   ./reset-password.sh --email user@example.com --password newpassword123
#
# Without --password a strong password is generated and printed once.
# Existing sessions stay valid until their JWT expires (~7 days default).
# Use disable-account.sh if access must stop immediately.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
check_venv

EMAIL=""
PASSWORD_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --email)    EMAIL="$2";    shift 2 ;;
        --password) PASSWORD_ARG="--password $2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 --email EMAIL [--password PASSWORD]"
            exit 0 ;;
        *) oc_err "Unknown argument: $1"; exit 2 ;;
    esac
done

[[ -n "$EMAIL" ]] || { oc_err "--email is required"; exit 2; }

oc_header "Resetting password for $EMAIL"
show_data_dir
echo
# shellcheck disable=SC2086
$MANAGE passwd --email "$EMAIL" $PASSWORD_ARG
