#!/usr/bin/env python3
"""Materialize skills_config inline instructions as SKILL.md files.

Why: workflow export/import carries ``node_parameters`` (including every
masterSkill node's ``skills_config`` with full inline ``instructions``) but
NOT the skill files on disk. After importing a workflow into a fresh host,
the Master Skill editor lists nothing because its catalogue comes from
``scan_skill_folder`` (a ``server/skills/<folder>/`` directory scan) plus
the ``user_skills`` table — it never reads ``skills_config``. The agent
panels still show the skills (they read ``skills_config``), so the workflow
runs fine while the editor looks empty.

This script closes the gap: it reads every masterSkill ``skills_config``
from the namespace's ``workflow.db`` and writes one
``server/skills/<skill_folder>/<skill-name>/SKILL.md`` per entry that has
inline instructions and no directory on disk yet. Idempotent: existing
skills (built-ins or re-runs) are skipped, so it is safe to run after every
workflow import.

Usage (on the host, from /opt/opencompany/server):

    sudo -u oc-app-user env HOME=/home/oc-app-user \\
        .venv/bin/python scripts/materialize_skills_config.py \\
        --namespace addval-tax

    add --dry-run to list what would be written without writing.

DATA_DIR comes from the environment (the server's .env sets it); it defaults
to ``~/.opencompany``. A JSON snapshot of the processed ``skills_config``
rows is left under ``{DATA_DIR}/backups/`` before any write.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), ".opencompany")
DEFAULT_SKILLS_DIR = "/opt/opencompany/server/skills"
APP_USER = "oc-app-user"

_FRONTMATTER = "---\n{}\n---\n\n{}\n"


def _yaml_str(value: str) -> str:
    """Quote a string for YAML frontmatter (JSON strings are valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def _derive_description(instructions: str, name: str) -> str:
    """First prose line of the instructions, or a fallback sentence."""
    for line in instructions.splitlines():
        text = line.strip()
        if not text or text.startswith("#") or text.startswith(">"):
            continue
        text = re.sub(r"[*_`]", "", text)
        return text[:200]
    return f"Skill {name} (regenerado desde skills_config)."


def _master_skill_rows(db_path: Path) -> list[tuple[str, dict]]:
    """Rows from node_parameters that look like a masterSkill node's params."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = []
        for r in con.execute("SELECT node_id, parameters FROM node_parameters"):
            try:
                params = json.loads(r["parameters"])
            except (TypeError, ValueError):
                continue
            if isinstance(params.get("skills_config"), dict):
                rows.append((r["node_id"], params))
        return rows
    finally:
        con.close()


def _existing_skill_names(skills_dir: Path) -> set[str]:
    """Names of every skill already materialized anywhere under skills_dir."""
    names: set[str] = set()
    if skills_dir.is_dir():
        for md in skills_dir.rglob("SKILL.md"):
            names.add(md.parent.name)
    return names


def _dump_backup(db_path: Path, rows: list[tuple[str, dict]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"node_parameters-{db_path.parent.name}-{ts}.json"
    payload = {nid: params for nid, params in rows}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _fix_ownership(root: Path) -> None:
    """When run as root, hand written files to the service account."""
    if os.geteuid() != 0:
        return
    import pwd

    try:
        entry = pwd.getpwnam(APP_USER)
    except KeyError:
        return
    for p in [root, *root.rglob("*")]:
        p.chmod(0o755 if p.is_dir() else 0o644)
        os.chown(p, entry.pw_uid, entry.pw_gid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--namespace", required=True, help="namespace name (workflow.db owner)")
    parser.add_argument("--skills-dir", default=DEFAULT_SKILLS_DIR, help="server skills base dir")
    parser.add_argument("--dry-run", action="store_true", help="list, do not write")
    args = parser.parse_args()

    data_dir = Path(os.environ.get("DATA_DIR", DEFAULT_DATA_DIR))
    db_path = data_dir / "namespaces" / args.namespace / "workflow.db"
    skills_dir = Path(args.skills_dir)

    if not db_path.exists():
        print(f"FAILED: no existe {db_path}", file=sys.stderr)
        return 1

    rows = _master_skill_rows(db_path)
    if not rows:
        print("Sin filas de masterSkill en node_parameters; nada que hacer.")
        return 0

    backup = _dump_backup(db_path, rows, data_dir / "backups")
    print(f"Backup de node_parameters: {backup}")

    existing = _existing_skill_names(skills_dir)
    written: list[str] = []
    skipped: list[str] = []

    for node_id, params in rows:
        folder = params.get("skill_folder") or "assistant"
        for name, cfg in (params.get("skills_config") or {}).items():
            if not isinstance(cfg, dict):
                continue
            instructions = (cfg.get("instructions") or "").strip()
            if not instructions:
                skipped.append(f"{name} (sin instructions inline)")
                continue
            if name in existing:
                skipped.append(f"{name} (ya existe en disco)")
                continue

            target = skills_dir / folder / name
            md_path = target / "SKILL.md"
            frontmatter = (
                f"name: {_yaml_str(name)}\n"
                f"description: {_yaml_str(_derive_description(instructions, name))}\n"
                "metadata:\n"
                "  author: opencompany\n"
                '  version: "1.0"\n'
                f"  category: {_yaml_str(folder)}\n"
            )
            content = _FRONTMATTER.format(frontmatter, instructions)

            if args.dry_run:
                print(f"[dry-run] escribiría {md_path}")
            else:
                target.mkdir(parents=True, exist_ok=True)
                md_path.write_text(content, encoding="utf-8")
                _fix_ownership(target)
                print(f"Escrito: {md_path}")
            existing.add(name)
            written.append(f"{folder}/{name}")

    print(f"\nResumen: {len(written)} escritos, {len(skipped)} omitidos")
    for s in skipped:
        print(f"  - {s}")
    if written and not args.dry_run:
        print("\nSiguiente paso: reinicia el backend (sudo supervisorctl restart "
              "opencompany) para que el SkillLoader registre los nuevos skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
