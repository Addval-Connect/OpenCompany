"""``company version sync`` -- replaces ``scripts/sync-version.js``.

Reads the latest git tag (or one supplied on the command line), strips the
``v`` prefix, and writes the resulting semver into every file that carries
the package version -- see ``targets()``:

- ``package.json``: the single source of truth at runtime. The backend's
  ``/health`` and OpenAPI document, the client's persisted-query buster and
  workflow-export stamp, and ``company --version`` all read it.
- ``client/package.json``: workspace member.
- ``desktop/package.json``: electron-builder artifact names and the
  electron-updater feed. CI copies the root version into it as well
  (``bun run sync-version``), but the tag-triggered desktop build ships
  whatever the release commit left here and refuses to build when that
  differs from the tag, so the commit must carry it.
- ``pyproject.toml``: the ``opencompany-cli`` Python package.
- ``cli/__init__.py``: ``__version__``.

``server/pyproject.toml`` is deliberately left alone: ``server/uv.lock``
records that project's version, so a bump fails ``uv lock --check`` until
the lock is regenerated and changes the desktop provisioning stamp on every
release, for a version nothing reads (the server is a virtual project, never
installed as a package).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import typer

from cli.colors import console
from cli.platform_ import project_root
from cli.run import capture


app = typer.Typer(
    name="version",
    help="Version-management subcommands.",
    no_args_is_help=True,
    add_completion=False,
)


_VALID_VERSION = re.compile(r"^\d+\.\d+\.\d+")
# First `version = "..."` assignment in a pyproject: the [project] table
# leads the file, so tool tables further down are never touched.
_PYPROJECT_VERSION = re.compile(r'^(version\s*=\s*")([^"]*)(")', re.MULTILINE)
_DUNDER_VERSION = re.compile(r'^(__version__\s*=\s*")([^"]*)(")', re.MULTILINE)

Writer = Callable[[Path, str], bool]


def _git_describe(root: Path) -> str | None:
    """``git describe --tags --abbrev=0``; falls back to sorted ``git tag -l``."""
    described = capture(["git", "describe", "--tags", "--abbrev=0"], cwd=root)
    if described:
        return described
    listed = capture(["git", "tag", "-l", "--sort=-version:refname"], cwd=root)
    if listed:
        return next(
            (line.strip() for line in listed.splitlines() if line.strip()), None
        )
    return None


def _tag_to_version(tag: str) -> str:
    return tag.lstrip("v")


def _update_package_json(path: Path, new_version: str) -> bool:
    pkg = json.loads(path.read_text(encoding="utf-8"))
    old = pkg.get("version")
    if old == new_version:
        console.print(f"  {path}: already at {new_version}")
        return False
    pkg["version"] = new_version
    # Match the existing 2-space indent + trailing newline of the JS writer.
    path.write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
    console.print(f"  {path}: {old} -> {new_version}")
    return True


def _update_assignment(path: Path, pattern: re.Pattern[str], new_version: str) -> bool:
    """Rewrite the value of a ``version = "..."``-style assignment in place."""
    text = path.read_text(encoding="utf-8")
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"no version assignment found in {path}")
    old = match.group(2)
    if old == new_version:
        console.print(f"  {path}: already at {new_version}")
        return False
    path.write_text(
        text[: match.start(2)] + new_version + text[match.end(2) :],
        encoding="utf-8",
    )
    console.print(f"  {path}: {old} -> {new_version}")
    return True


def _update_pyproject(path: Path, new_version: str) -> bool:
    return _update_assignment(path, _PYPROJECT_VERSION, new_version)


def _update_python_dunder(path: Path, new_version: str) -> bool:
    return _update_assignment(path, _DUNDER_VERSION, new_version)


def targets(root: Path) -> list[tuple[Path, Writer]]:
    """Every file ``sync`` writes, paired with the writer for its format."""
    return [
        (root / "package.json", _update_package_json),
        (root / "client" / "package.json", _update_package_json),
        (root / "desktop" / "package.json", _update_package_json),
        (root / "pyproject.toml", _update_pyproject),
        (root / "cli" / "__init__.py", _update_python_dunder),
    ]


@app.command("sync", help="Sync every version file from a git tag (default: the latest).")
def sync(
    tag: str | None = typer.Argument(None, help="Git tag to use (defaults to latest)."),
) -> None:
    root = project_root()
    resolved_tag = tag or _git_describe(root)
    if not resolved_tag:
        console.print("[red]Error: No git tags found and no tag provided.[/]")
        raise typer.Exit(code=1)

    version = _tag_to_version(resolved_tag)
    if not _VALID_VERSION.match(version):
        console.print(
            f"[red]Error: Invalid version from tag {resolved_tag!r}: {version!r}[/]"
        )
        console.print("Expected semver format (e.g. v0.0.11 or 0.0.11).")
        raise typer.Exit(code=1)

    console.print(f"Syncing version from tag: {resolved_tag} -> {version}\n")

    updated = 0
    for path, write in targets(root):
        try:
            if write(path, version):
                updated += 1
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            console.print(f"[red]  Error updating {path}: {exc}[/]")

    console.print()
    if updated:
        console.print(f"Updated {updated} file(s). Don't forget to commit the changes.")
    else:
        console.print("All version files already at the correct version.")
