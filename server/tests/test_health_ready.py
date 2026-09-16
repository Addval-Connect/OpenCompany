"""``/health/ready`` verdict — ``core.health.readiness_report``.

``/health`` is liveness: it answers as soon as uvicorn serves HTTP, seconds
before Temporal is connected and the workers poll. The desktop shell waits
on readiness instead, so the first Run after the window appears can
actually execute. The verdict is a pure function so it is tested without
booting the app.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def health():
    spec = importlib.util.spec_from_file_location("_real_core_health", SERVER_DIR / "core" / "health.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(health, **overrides):
    kwargs = dict(
        db_ok=True,
        temporal_enabled=True,
        phase="starting",
        worker_ready=False,
        pool_ready=False,
        client_connected=False,
        version="1.2.3",
    )
    kwargs.update(overrides)
    return health.readiness_report(**kwargs)


def test_not_ready_while_workers_are_down(health):
    code, body = _report(health, client_connected=True, phase="connecting")
    assert code == 503
    assert body["ready"] is False
    assert body["phase"] == "connecting", "a connected client is not readiness"
    assert body["temporal"]["worker_ready"] is False


def test_ready_once_the_worker_manager_started(health):
    code, body = _report(health, worker_ready=True, pool_ready=True, client_connected=True, phase="ready")
    assert code == 200
    assert body["ready"] is True
    assert body["phase"] == "ready"
    assert body["version"] == "1.2.3"


def test_temporal_disabled_short_circuits(health):
    code, body = _report(health, temporal_enabled=False, phase="disabled")
    assert code == 200
    assert body["ready"] is True
    assert body["temporal"]["enabled"] is False


def test_database_down_is_never_ready(health):
    code, body = _report(health, db_ok=False, worker_ready=True)
    assert code == 503
    assert body["database"] is False


@pytest.mark.parametrize("phase", ["installing_temporal", "starting_temporal", "connecting", "starting_workers"])
def test_phase_is_surfaced_for_the_splash(health, phase):
    code, body = _report(health, phase=phase)
    assert code == 503
    assert body["phase"] == phase
    assert body["temporal"]["phase"] == phase


def test_lifecycle_writes_every_phase_the_splash_expects():
    src = (SERVER_DIR / "services" / "temporal" / "lifecycle.py").read_text(encoding="utf-8")
    for phase in ("installing_temporal", "starting_temporal", "connecting", "starting_workers", "ready"):
        assert f'"{phase}"' in src, phase


def test_ready_route_is_public_and_wired():
    auth_src = (SERVER_DIR / "middleware" / "auth.py").read_text(encoding="utf-8")
    assert '"/health/ready"' in auth_src
    main_src = (SERVER_DIR / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/health/ready")' in main_src
    assert "readiness_report(" in main_src
