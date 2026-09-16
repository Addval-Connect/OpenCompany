"""Tests for ``cli.commands.version``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cli.commands import version


def test_tag_to_version_strips_v_prefix():
    assert version._tag_to_version("v1.2.3") == "1.2.3"
    assert version._tag_to_version("0.0.11") == "0.0.11"


def test_update_package_json_writes_new_version(tmp_path: Path):
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"name": "x", "version": "0.0.1"}, indent=2) + "\n")
    assert version._update_package_json(pkg, "0.0.2") is True
    contents = json.loads(pkg.read_text())
    assert contents["version"] == "0.0.2"


def test_update_package_json_no_op_when_already_correct(tmp_path: Path):
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"name": "x", "version": "1.0.0"}) + "\n")
    assert version._update_package_json(pkg, "1.0.0") is False


def test_update_package_json_preserves_trailing_newline(tmp_path: Path):
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"name": "x", "version": "0.0.1"}) + "\n")
    version._update_package_json(pkg, "0.0.2")
    assert pkg.read_text(encoding="utf-8").endswith("\n")


def test_git_describe_returns_none_without_git():
    with patch.object(version, "capture", return_value=None):
        assert version._git_describe(Path(".")) is None


def test_update_pyproject_rewrites_only_the_project_version(tmp_path: Path):
    py = tmp_path / "pyproject.toml"
    py.write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\n\n[tool.other]\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    assert version._update_pyproject(py, "0.2.0") is True
    text = py.read_text(encoding="utf-8")
    assert text.startswith('[project]\nname = "x"\nversion = "0.2.0"\n')
    assert 'version = "9.9.9"' in text


def test_update_pyproject_no_op_when_already_correct(tmp_path: Path):
    py = tmp_path / "pyproject.toml"
    py.write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    assert version._update_pyproject(py, "1.0.0") is False


def test_update_python_dunder_rewrites_the_assignment(tmp_path: Path):
    init = tmp_path / "__init__.py"
    init.write_text('"""Doc."""\n\n__version__ = "0.1.0"\n', encoding="utf-8")
    assert version._update_python_dunder(init, "0.2.0") is True
    assert init.read_text(encoding="utf-8") == '"""Doc."""\n\n__version__ = "0.2.0"\n'


def test_assignment_writer_refuses_a_file_without_a_version(tmp_path: Path):
    py = tmp_path / "pyproject.toml"
    py.write_text('[project]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        version._update_pyproject(py, "0.2.0")


def test_targets_cover_every_version_file_but_the_server_pyproject(tmp_path: Path):
    """``server/pyproject.toml`` is recorded in ``server/uv.lock``: bumping it
    would fail ``uv lock --check`` and re-provision every desktop install for
    a version nothing reads."""
    relative = {
        path.relative_to(tmp_path).as_posix() for path, _ in version.targets(tmp_path)
    }
    assert relative == {
        "package.json",
        "client/package.json",
        "desktop/package.json",
        "pyproject.toml",
        "cli/__init__.py",
    }


def test_checked_in_version_files_agree(root: Path):
    """A release commit must bump every file ``sync`` writes: the desktop
    build ships the committed desktop version, so one straggler ships the
    previous release's number."""
    seen: dict[str, str] = {}
    for path, writer in version.targets(root):
        text = path.read_text(encoding="utf-8")
        if writer is version._update_package_json:
            seen[path.name] = json.loads(text)["version"]
        elif writer is version._update_pyproject:
            seen[path.name] = version._PYPROJECT_VERSION.search(text).group(2)
        else:
            seen[path.name] = version._DUNDER_VERSION.search(text).group(2)
    assert len(set(seen.values())) == 1, seen
