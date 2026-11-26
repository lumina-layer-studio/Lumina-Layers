"""The clean-install gate must inspect the actual generated download."""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest


def _active(process: psutil.Process) -> bool:
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


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


def test_clean_install_uses_frozen_lut_without_touching_user_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import log_quality_check, verify_source_install

    personal = tmp_path / "personal-luts"
    personal.mkdir()
    marker = personal / "keep.txt"
    marker.write_text("personal data")
    monkeypatch.setenv("LUMINA_CUSTOM_LUT_DIR", str(personal))
    monkeypatch.setattr(verify_source_install.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(verify_source_install.metadata, "distribution", lambda name: SimpleNamespace(
        version="test", read_text=lambda filename: None,
    ))
    selected_library: list[Path] = []

    @contextmanager
    def inspect_backend(script: Path, *, env: dict[str, str], stdout):
        library = Path(env["LUMINA_CUSTOM_LUT_DIR"])
        assert library != personal
        frozen = verify_source_install.ROOT / "tests/fixtures/frozen_assets/luts/4c" / f"{log_quality_check.DEFAULT_LUT_STEM}.npy"
        assert (library / frozen.name).read_bytes() == frozen.read_bytes()
        selected_library.append(library)
        yield None

    class BackendInputVerified(Exception):
        pass

    def stop_before_network(*args, **kwargs):
        raise BackendInputVerified

    monkeypatch.setattr(verify_source_install, "_server_process", inspect_backend)
    monkeypatch.setattr(log_quality_check, "_wait_for_server", stop_before_network)
    with pytest.raises(BackendInputVerified):
        verify_source_install.verify_install(tmp_path / "report")
    assert os.environ["LUMINA_CUSTOM_LUT_DIR"] == str(personal)
    assert marker.read_text() == "personal data"
    assert selected_library and not selected_library[0].exists()


@pytest.mark.parametrize(
    "payload", [b"<html>200 OK</html>", archive(triangles=False), archive(settings=False)],
    ids=["html-response", "no-triangles", "no-native-settings"],
)
def test_rejects_downloads_without_real_geometry_and_native_settings(payload: bytes) -> None:
    from scripts.verify_source_install import verify_3mf

    with pytest.raises((ValueError, zipfile.BadZipFile)):
        verify_3mf(payload)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal/process-group regression")
def test_timeout_cleanup_stops_a_backend_and_its_unresponsive_worker(tmp_path: Path) -> None:
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
        owned_worker = psutil.Process(worker_pid)

        _stop_server(proc, timeout=0.1)

        assert proc.poll() is not None
        deadline = time.monotonic() + 5
        while _active(owned_worker) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _active(owned_worker)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


@pytest.mark.parametrize("parent_exits_first", [True, False], ids=["parent-already-exited", "parent-still-running"])
def test_server_cleanup_keeps_an_outside_process_alive(tmp_path: Path, parent_exits_first: bool) -> None:
    from scripts.verify_source_install import _server_process

    pid_file = tmp_path / "owned-worker.pid"
    worker = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(300)"
    backend = tmp_path / "backend.py"
    backend.write_text(
        "import os,subprocess,sys,time\nfrom pathlib import Path\n"
        f"worker=subprocess.Popen([sys.executable,'-c',{worker!r}],stdout=subprocess.PIPE)\n"
        "assert worker.stdout.readline().strip()==b'ready'\n"
        f"pending=Path({str(pid_file.with_suffix('.pending'))!r})\n"
        f"pending.write_text(str(worker.pid)); pending.replace({str(pid_file)!r})\n"
        + ("os._exit(7)\n" if parent_exits_first else "time.sleep(300)\n"),
        encoding="utf-8",
    )
    outside = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"],
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )
    owned_worker = None

    try:
        with _server_process(backend, stdout=subprocess.DEVNULL) as proc:
            deadline = time.monotonic() + 10
            while not pid_file.exists() and time.monotonic() < deadline:
                if proc.poll() is not None:
                    assert pid_file.exists(), "Backend exited before spawning its worker"
                    break
                time.sleep(0.02)
            assert pid_file.exists(), "Backend never spawned its worker"
            owned_worker = psutil.Process(int(pid_file.read_text()))
            assert _active(owned_worker)
            if parent_exits_first:
                assert proc.wait(timeout=5) == 7
        assert proc.poll() is not None
        deadline = time.monotonic() + 5
        while _active(owned_worker) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _active(owned_worker)
        assert outside.poll() is None
    finally:
        if owned_worker is not None and _active(owned_worker):
            try:
                owned_worker.kill()
            except psutil.NoSuchProcess:
                pass
        outside.terminate()
        outside.wait(timeout=5)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup")
@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGKILL"])
def test_darwin_cleanup_accepts_eperm_only_after_the_group_disappears(
    monkeypatch: pytest.MonkeyPatch, signal_name: str,
) -> None:
    from scripts import verify_source_install

    denied_signal = getattr(signal, signal_name)
    monkeypatch.setattr(verify_source_install.sys, "platform", "darwin")
    signals: list[int] = []
    waits: list[float] = []
    probes = 0

    def killpg(pid: int, sig: int) -> None:
        nonlocal probes
        assert pid == 12345
        signals.append(sig)
        if sig == denied_signal:
            raise PermissionError(1, "group is exiting")
        if sig == 0:
            probes += 1
            if probes == 1:
                raise PermissionError(1, "group is still exiting")
            raise ProcessLookupError(3, "group disappeared")

    monkeypatch.setattr(verify_source_install.os, "killpg", killpg)
    proc = SimpleNamespace(pid=12345, poll=lambda: 0, wait=lambda *, timeout: waits.append(timeout))

    verify_source_install._stop_server(proc, timeout=0.1)

    assert probes >= 2
    assert signal.SIGKILL in signals, "successful parent exit must not skip worker cleanup"
    assert len(waits) == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup")
@pytest.mark.parametrize("probe_denied", [True, False], ids=["permission-denied", "still-exists"])
def test_darwin_cleanup_propagates_permission_errors_for_a_remaining_group(
    monkeypatch: pytest.MonkeyPatch, probe_denied: bool,
) -> None:
    from scripts import verify_source_install

    monkeypatch.setattr(verify_source_install.sys, "platform", "darwin")
    failure = PermissionError(1, "cannot signal this group")
    ticks = iter(range(100))
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks) / 10)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    def killpg(_pid: int, sig: int) -> None:
        if sig != 0 or probe_denied:
            raise failure

    monkeypatch.setattr(verify_source_install.os, "killpg", killpg)
    proc = SimpleNamespace(pid=12345, poll=lambda: 0, wait=lambda *, timeout: 0)

    with pytest.raises(PermissionError) as error:
        verify_source_install._stop_server(proc, timeout=0.1)
    assert error.value is failure


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup")
def test_non_darwin_cleanup_does_not_retry_permission_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import verify_source_install

    monkeypatch.setattr(verify_source_install.sys, "platform", "linux")
    signals: list[int] = []

    def killpg(_pid: int, sig: int) -> None:
        signals.append(sig)
        raise PermissionError(1, "cannot signal this group")

    monkeypatch.setattr(verify_source_install.os, "killpg", killpg)
    proc = SimpleNamespace(pid=12345, poll=lambda: 0, wait=lambda *, timeout: 0)

    with pytest.raises(PermissionError):
        verify_source_install._stop_server(proc, timeout=0.1)
    assert signals == [signal.SIGTERM]


@pytest.mark.skipif(os.name == "nt", reason="POSIX exited-but-unreaped parent")
def test_cleanup_reaps_a_parent_that_exited_before_the_first_signal() -> None:
    from scripts.verify_source_install import _stop_server

    proc = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    parent = psutil.Process(proc.pid)
    try:
        deadline = time.monotonic() + 5
        while parent.status() != psutil.STATUS_ZOMBIE and time.monotonic() < deadline:
            time.sleep(0.01)
        assert parent.status() == psutil.STATUS_ZOMBIE
        assert proc.returncode is None, "test must not poll or wait before cleanup"

        _stop_server(proc, timeout=0.2)

        assert proc.returncode == 0
        with pytest.raises(ProcessLookupError):
            os.killpg(proc.pid, 0)
    finally:
        proc.wait(timeout=5)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup")
@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGKILL"])
def test_cleanup_propagates_other_signal_errors(
    monkeypatch: pytest.MonkeyPatch, signal_name: str,
) -> None:
    from scripts import verify_source_install

    failed_signal = getattr(signal, signal_name)
    failure = OSError(22, "invalid signal request")

    def killpg(_pid: int, sig: int) -> None:
        if sig == failed_signal:
            raise failure

    monkeypatch.setattr(verify_source_install.os, "killpg", killpg)
    proc = SimpleNamespace(pid=12345, poll=lambda: 0, wait=lambda *, timeout: 0)
    with pytest.raises(OSError) as error:
        verify_source_install._stop_server(proc, timeout=0.1)
    assert error.value is failure
