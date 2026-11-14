"""The clean-install gate must inspect the actual generated download."""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest


def archive(*, triangles: bool = True, settings: bool = True) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as package:
        package.writestr("3D/3dmodel.model", '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"/>')
        triangle = '<triangle v1="0" v2="1" v3="2"/>' if triangles else ""
        package.writestr("3D/Objects/object.model", '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1"><mesh><triangles>' + triangle + '</triangles></mesh></object></resources></model>')
        if settings:
            package.writestr("Metadata/project_settings.config", '{"printer_settings_id":"test"}')
    return output.getvalue()


def test_accepts_geometry_in_a_production_extension_member() -> None:
    from scripts.verify_source_install import verify_3mf

    verify_3mf(archive())


@pytest.mark.parametrize(
    "payload", [b"<html>200 OK</html>", archive(triangles=False), archive(settings=False)],
    ids=["html-response", "no-triangles", "no-native-settings"],
)
def test_rejects_downloads_without_real_geometry_and_native_settings(payload: bytes) -> None:
    from scripts.verify_source_install import verify_3mf

    with pytest.raises((ValueError, zipfile.BadZipFile)):
        verify_3mf(payload)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup; Windows uses taskkill /T")
def test_timeout_cleanup_stops_a_backend_and_its_unresponsive_worker(tmp_path: Path) -> None:
    import psutil
    from scripts.verify_source_install import _stop_server

    pid_file = tmp_path / "worker.pid"
    worker = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready',flush=True); time.sleep(300)"
    parent = (
        "import signal,subprocess,sys,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"worker=subprocess.Popen([sys.executable,'-c',{worker!r}],stdout=subprocess.PIPE); "
        "worker.stdout.readline(); "
        f"Path({str(pid_file)!r}).write_text(str(worker.pid)); time.sleep(300)"
    )
    proc = subprocess.Popen([sys.executable, "-c", parent], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pid_file.exists(), "Test backend never spawned its worker"
        worker_pid = int(pid_file.read_text())

        _stop_server(proc, timeout=0.1)

        assert proc.poll() is not None
        deadline = time.monotonic() + 5
        while psutil.pid_exists(worker_pid) and time.monotonic() < deadline:
            if psutil.Process(worker_pid).status() == psutil.STATUS_ZOMBIE:
                break
            time.sleep(0.02)
        assert not psutil.pid_exists(worker_pid) or psutil.Process(worker_pid).status() == psutil.STATUS_ZOMBIE
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)
