#!/usr/bin/env bash
# Re-enable a previously disabled Temporal namespace.
#
# Re-provisions the namespace on the Temporal server (re-registers Search
# Attributes if missing) and marks the assignment as ready.
#
# Usage:
#   ./enable-namespace.sh --email user@example.com

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
check_venv

EMAIL=""
RETENTION_ARGS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --email)          EMAIL="$2";                    shift 2 ;;
        --retention-days) RETENTION_ARGS="--retention-days $2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 --email EMAIL [--retention-days N]"
            exit 0 ;;
        *) oc_err "Unknown argument: $1"; exit 2 ;;
    esac
done

[[ -n "$EMAIL" ]] || { oc_err "--email is required"; exit 2; }

oc_header "Re-enabling namespace for $EMAIL"
show_data_dir
echo
oc_warn "Temporal must be running (localhost:5681) for namespace re-provisioning."
echo
# shellcheck disable=SC2086
$MANAGE namespace --email "$EMAIL" --enable $RETENTION_ARGS
echo
oc_ok "Namespace re-enabled. Restart the backend to reconnect the namespace client:"
echo "      company stop && company dev"
