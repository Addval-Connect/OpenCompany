#!/usr/bin/env bash
# Shared helpers for tenant admin scripts.
# Source this file; do not run it directly.
#
# DATA_DIR resolution order:
#   1. OC_DATA_DIR env var (explicit override, useful for EC2 / custom paths)
#   2. .env.dev in the repo root (company dev mode -> DATA_DIR=.opencompany)
#   3. .env in the repo root                     (default DATA_DIR=~/.opencompany)
#
# The resolved value is exported as DATA_DIR so manage_users.py picks it up
# via pydantic-settings without any command-line flag.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$SERVER_DIR/.." && pwd)"
MANAGE="$SERVER_DIR/.venv/bin/python $SERVER_DIR/scripts/manage_users.py"

# ── DATA_DIR detection ──────────────────────────────────────────────────────
if [[ -n "${OC_DATA_DIR:-}" ]]; then
    export DATA_DIR="$OC_DATA_DIR"
elif [[ -f "$REPO_ROOT/.env.dev" ]]; then
    # Extract DATA_DIR from .env.dev (strips comments, whitespace)
    _devval=$(grep -E '^DATA_DIR=' "$REPO_ROOT/.env.dev" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')
    if [[ -n "$_devval" ]]; then
        # Resolve relative paths from repo root
        if [[ "$_devval" == /* ]]; then
            export DATA_DIR="$_devval"
        else
            export DATA_DIR="$REPO_ROOT/$_devval"
        fi
    fi
elif [[ -f "$REPO_ROOT/.env" ]]; then
    _envval=$(grep -E '^DATA_DIR=' "$REPO_ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')
    if [[ -n "$_envval" ]]; then
        export DATA_DIR="${_envval/#\~/$HOME}"
    fi
fi

DATA_DIR="${DATA_DIR:-$HOME/.opencompany}"
export DATA_DIR

# ── Helpers ─────────────────────────────────────────────────────────────────
oc_header() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
oc_ok()     { printf '  \033[1;32m✓\033[0m  %s\n' "$*"; }
oc_warn()   { printf '  \033[1;33m!\033[0m  %s\n' "$*" >&2; }
oc_err()    { printf '  \033[1;31m✗\033[0m  %s\n' "$*" >&2; }

check_venv() {
    if [[ ! -x "$SERVER_DIR/.venv/bin/python" ]]; then
        oc_err "Python venv not found at $SERVER_DIR/.venv"
        oc_err "Run 'company build' or 'uv sync' from the server directory first."
        exit 1
    fi
}

show_data_dir() {
    echo "  DATA_DIR: $DATA_DIR"
    if [[ ! -f "$DATA_DIR/workflow.db" ]]; then
        oc_warn "workflow.db not found in $DATA_DIR — DB may not exist yet."
    fi
}
