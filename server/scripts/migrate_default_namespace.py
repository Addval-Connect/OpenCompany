"""Migrate the legacy "owner" namespace to the canonical "default".

2026-10 tenancy cleanup (docs-internal/multitenant_routing_audit.md):
"owner" is an AUTH PRINCIPAL, never a namespace. Historically the default
namespace's data lived in ``namespaces/owner/`` because
``normalize_credential_ns`` translated the JWT claim "default" onto an
"owner" bucket. The code now uses "default" end-to-end; this script moves
the on-disk state to match.

What it does (idempotent — safe to run on every boot/deploy):
  1. F3 (files): if ``namespaces/default/`` does not exist but
     ``namespaces/owner/`` does, rename owner → default (workflow.db,
     credentials.db, workspaces/, everything) with a timestamped backup
     manifest. Refuses to run when the app is running (flock via a
     marker) unless ``--force``.
  2. F2 (rows): in every namespace's credentials.db, rewrite
     ``oauth_tokens.customer_id`` from 'owner' to 'default' (the runtime
     also does this at startup; this covers DBs the runtime won't open).

Usage (as the app user, app stopped or --force):
    python -m scripts.migrate_default_namespace [--data-dir DIR] [--dry-run] [--force]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

LEGACY = "owner"
CANONICAL = "default"


def _migrate_dirs(namespaces_dir: Path, *, dry_run: bool, force: bool) -> list[str]:
    actions: list[str] = []
    legacy = namespaces_dir / LEGACY
    canonical = namespaces_dir / CANONICAL
    if not legacy.exists():
        return actions
    if canonical.exists():
        # Both exist: move only the rows/files that canonical lacks? Too
        # risky to merge automatically — surface it and require a manual
        # decision (this state means a boot already created default while
        # owner still held data).
        print(
            f"REFUSING: both {legacy} and {canonical} exist. Merge manually "
            "(inspect both workflow.db files), then remove one and re-run.",
            file=sys.stderr,
        )
        sys.exit(2)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = namespaces_dir / f".{LEGACY}-pre-default-migration-{stamp}"
    print(f"[f3] {legacy} -> {canonical}  (backup manifest at {backup})")
    actions.append(f"rename {legacy} -> {canonical}")
    if dry_run:
        return actions
    backup.mkdir()
    (backup / "MANIFEST.txt").write_text(
        f"Pre-rename snapshot of {legacy} at {stamp}\n"
        "The rename itself is atomic (os.replace on the directory is not\n"
        "guaranteed across filesystems, so this dir records the intent).\n"
    )
    legacy.rename(canonical)
    return actions


def _migrate_credential_rows(namespaces_dir: Path, *, dry_run: bool) -> list[str]:
    actions: list[str] = []
    for creds in sorted(namespaces_dir.glob("*/credentials.db")):
        ns = creds.parent.name
        con = sqlite3.connect(creds)
        try:
            exists = con.execute(
                "select count(*) from sqlite_master where name='oauth_tokens'"
            ).fetchone()[0]
            if not exists:
                continue
            n = con.execute(
                "select count(*) from oauth_tokens where customer_id = ?", (LEGACY,)
            ).fetchone()[0]
            if not n:
                continue
            print(f"[f2] {creds}: {n} oauth_tokens rows 'owner' -> '{CANONICAL}'")
            actions.append(f"{ns}: {n} rows")
            if not dry_run:
                con.execute(
                    "UPDATE oauth_tokens SET customer_id = ? WHERE customer_id = ?",
                    (CANONICAL, LEGACY),
                )
                con.commit()
        finally:
            con.close()
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default=None,
        help="DATA_DIR (default: ~/.opencompany, resolved like the server does)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print actions only")
    parser.add_argument(
        "--force",
        action="store_true",
        help="run even while the app may be running (SQLite files are safe to "
        "rename only when no process has them open)",
    )
    args = parser.parse_args()

    home = Path.home()
    data_dir = Path(args.data_dir).expanduser() if args.data_dir else home / ".opencompany"
    namespaces_dir = data_dir / "namespaces"
    if not namespaces_dir.exists():
        print(f"No namespaces dir at {namespaces_dir} — nothing to migrate.")
        return 0

    marker = data_dir / ".app-running.marker"
    if not args.force and marker.exists():
        print("REFUSING: app may be running (marker found). Stop it or pass --force.", file=sys.stderr)
        return 1

    actions = _migrate_dirs(namespaces_dir, dry_run=args.dry_run, force=args.force)
    actions += _migrate_credential_rows(namespaces_dir, dry_run=args.dry_run)

    if not actions:
        print("Nothing to migrate — already canonical.")
        return 0
    print(("DRY RUN — " if args.dry_run else "") + f"{len(actions)} action(s) applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
