#!/usr/bin/env bash
# Create a new login account.
#
# Usage:
#   ./create-user.sh --email user@example.com --name "Full Name"
#   ./create-user.sh --email user@example.com --name "Full Name" --password secret123
#
# Without --password a strong password is generated and printed once.
# The account becomes owner if it is the first one registered.

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
check_venv

EMAIL=""
NAME=""
PASSWORD_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --email)    EMAIL="$2";    shift 2 ;;
        --name)     NAME="$2";     shift 2 ;;
        --password) PASSWORD_ARG="--password $2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 --email EMAIL --name NAME [--password PASSWORD]"
            exit 0 ;;
        *) oc_err "Unknown argument: $1"; exit 2 ;;
    esac
done

[[ -n "$EMAIL" ]] || { oc_err "--email is required"; exit 2; }
[[ -n "$NAME"  ]] || { oc_err "--name is required";  exit 2; }

oc_header "Creating account: $EMAIL"
show_data_dir
echo
# shellcheck disable=SC2086
$MANAGE add --email "$EMAIL" --name "$NAME" $PASSWORD_ARG
