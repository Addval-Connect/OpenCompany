"""Windows only: ``core.desktop.install_job_object`` makes children die with us.

The backend enrolls ITSELF in a kill-on-close Job Object; children inherit
membership, so when the backend is terminated by any means the kernel
kills Temporal / node / edgymeow too. Verified in a subprocess (enrolling
the pytest process itself would kill the test runner's children on exit):

    launcher -> install_job_object() -> spawn grandchild sleeper
             -> print grandchild pid -> os._exit(0)

After the launcher exits, the grandchild must be gone.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]

pytestmark = [pytest.mark.unit, pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")]

_LAUNCHER = r"""
import importlib.util, os, subprocess, sys, time
spec = importlib.util.spec_from_file_location("core.desktop", sys.argv[1])
# core.desktop imports core.logging at module load; stub it with a no-op logger.
import types
core = types.ModuleType("core"); core.__path__ = []
logging_stub = types.ModuleType("core.logging")
class _L:
    def __getattr__(self, name):
        return lambda *a, **k: None
logging_stub.get_logger = lambda name: _L()
sys.modules["core"] = core; sys.modules["core.logging"] = logging_stub
mod = importlib.util.module_from_spec(spec); sys.modules["core.desktop"] = mod
spec.loader.exec_module(mod)
ok = mod.install_job_object()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(f"{int(ok)} {child.pid}", flush=True)
time.sleep(0.5)
os._exit(0)
"""


def _pid_alive(pid: int) -> bool:
    import psutil

    try:
        return psutil.Process(pid).is_running() and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_children_die_when_the_enrolled_parent_exits():
    out = subprocess.run(
        [sys.executable, "-c", _LAUNCHER, str(SERVER_DIR / "core" / "desktop.py")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    ok, child_pid = out.stdout.strip().split()
    child_pid = int(child_pid)
    if ok != "1":
        pytest.skip(f"Job Object refused on this host (already in a non-nestable job?): {out.stderr.strip()}")
    deadline = time.time() + 10
    while time.time() < deadline and _pid_alive(child_pid):
        time.sleep(0.1)
    alive = _pid_alive(child_pid)
    if alive:
        import psutil

        psutil.Process(child_pid).kill()
    assert not alive, "grandchild survived its Job-Object-enrolled parent"


def test_install_is_idempotent_in_process():
    """Calling twice returns True without creating a second job. Runs in a
    subprocess for the same reason as above."""
    script = _LAUNCHER.replace("ok = mod.install_job_object()", "ok = mod.install_job_object() and mod.install_job_object()")
    out = subprocess.run(
        [sys.executable, "-c", script, str(SERVER_DIR / "core" / "desktop.py")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    ok, child_pid = out.stdout.strip().split()
    if ok != "1":
        pytest.skip("Job Object refused on this host")
    deadline = time.time() + 10
    while time.time() < deadline and _pid_alive(int(child_pid)):
        time.sleep(0.1)
    assert not _pid_alive(int(child_pid))
