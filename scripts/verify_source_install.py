"""Exercise a README/PyPI source installation through its real backend process."""

from __future__ import annotations

import argparse
import io
import json
import os
import signal
import socket
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from typing import IO, TYPE_CHECKING
from xml.etree import ElementTree as ET

if TYPE_CHECKING:
    from core.workshop.backend.win_job import WindowsJob

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def verify_3mf(payload: bytes) -> None:
    """Require native project settings and real triangles in the downloaded ZIP."""
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        if "3D/3dmodel.model" not in package.namelist():
            raise ValueError("Downloaded 3MF has no root model")
        settings = "Metadata/project_settings.config"
        if settings not in package.namelist() or not json.loads(package.read(settings)):
            raise ValueError("Downloaded 3MF has no native project settings")
        triangle = ".//{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}triangle"
        if not any(
            ET.fromstring(package.read(name)).find(triangle) is not None
            for name in package.namelist() if name.endswith(".model")
        ):
            raise ValueError("Downloaded 3MF has no triangle geometry")


def _stop_server(
    proc: subprocess.Popen, *, timeout: float = 10.0,
    windows_job: WindowsJob | None = None,
) -> None:
    """Stop only this verifier's owned backend tree, including surviving workers."""
    if os.name == "nt":
        from scripts.log_quality_check import _terminate_server_process

        if windows_job is None:
            raise ValueError("Windows source verification requires an owned job")
        try:
            _terminate_server_process(proc)
        finally:
            # Parent exit does not end ownership of workers that are still in
            # the job. The PID-based helper alone returns early in that case.
            windows_job.terminate()
            proc.wait(timeout=timeout)
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # The parent may have exited while a worker ignored TERM. The group is
        # owned by start_new_session below and never includes the calling shell.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


@contextmanager
def _server_process(
    script: Path, *, env: dict[str, str] | None = None,
    stdout: int | IO[str] | None = None,
) -> Iterator[subprocess.Popen]:
    """Own the verifier's backend tree from before its first instruction."""
    job = None
    proc = None
    flags = 0
    if os.name == "nt":
        from core.workshop.backend.win_job import CREATE_SUSPENDED, WindowsJob

        job = WindowsJob()
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED
    try:
        proc = subprocess.Popen(
            [sys.executable, str(script)], cwd=ROOT, env=env,
            stdout=stdout, stderr=subprocess.STDOUT,
            creationflags=flags, start_new_session=os.name != "nt",
        )
        if job is not None:
            import psutil

            try:
                job.assign(proc.pid)
                psutil.Process(proc.pid).resume()
            except BaseException:
                # It is still suspended if assignment/resume fails, so no
                # application worker could have escaped the job.
                proc.kill()
                proc.wait(timeout=5)
                raise
        yield proc
    finally:
        try:
            if proc is not None:
                _stop_server(proc, windows_job=job)
        finally:
            if job is not None:
                job.close()


def verify_install(report_dir: Path) -> dict[str, object]:
    """Check the selected interpreter, boot the API, then export and fetch a 3MF."""
    subprocess.run(
        [sys.executable, "start_all.py", "--check-dependencies"],
        cwd=ROOT, check=True, timeout=120,
    )
    versions: dict[str, str] = {}
    for name in ("fatcat-metadata", "neroued-3mf", "lumina-svg-core", "neroued-vectorizer"):
        distribution = metadata.distribution(name)
        if distribution.read_text("direct_url.json") is not None:
            raise ValueError(f"{name} was installed from a local/direct source instead of the PyPI index")
        versions[name] = distribution.version

    import httpx
    from scripts.log_quality_check import (
        DEFAULT_LUT_NAME, _generate_payload, _post_preview, _select_lut_name,
        _wait_for_server,
    )

    report_dir.mkdir(parents=True, exist_ok=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = dict(os.environ)
    env.update(
        LUMINA_API_HOST="127.0.0.1", LUMINA_API_PORT=str(port),
        LUMINA_LOG_PATH=str((report_dir / "backend.jsonl").resolve()),
        LUMINA_FEEDBACK_SERVER_URL="off",
        LUMINA_WORKSHOP_DATA_DIR=str((report_dir / "workshop").resolve()),
    )
    with (report_dir / "backend-console.log").open("w", encoding="utf-8") as console:
        with _server_process(ROOT / "api_server.py", env=env, stdout=console) as proc:
            base_url = f"http://127.0.0.1:{port}"
            _wait_for_server(base_url, 90.0, proc)
            with httpx.Client(base_url=base_url, timeout=120.0, trust_env=False) as client:
                response = client.get("/api/lut/list")
                response.raise_for_status()
                lut_name = _select_lut_name(response.json(), fallback=DEFAULT_LUT_NAME)
                session_id = _post_preview(client, lut_name)
                response = client.post("/api/convert/generate", json=_generate_payload(session_id, lut_name))
                response.raise_for_status()
                download_url = response.json()["download_url"]
                response = client.post("/api/session/close", json={"session_id": session_id})
                response.raise_for_status()
                response = client.get(download_url)
                response.raise_for_status()
                verify_3mf(response.content)
                size = len(response.content)
                (report_dir / "source-install.3mf").write_bytes(response.content)
    return {"python": sys.version, "dependencies": versions, "download_bytes": size}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_install(args.report_dir)
    except Exception as exc:  # CLI boundary: preserve logs and fail the CI job.
        print(f"Source installation verification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"Backend diagnostics: {args.report_dir}", file=sys.stderr)
        return 1
    (args.report_dir / "source-install.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
