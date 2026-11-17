"""Host runtime against the public Python backend SDK (cross-repository check).

Set ``LUMINA_WORKSHOP_SDK_PYTHON_SRC`` to the SDK checkout's ``python/src``
directory (or an unpacked SDK wheel) to run. The module package vendors that
SDK copy under ``backend/`` exactly as module authors are told to.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from core.workshop.backend.locks import WheelSourcePolicy
from core.workshop.backend.review import ReviewContext
from core.workshop.backend.runtime import RuntimeSettings, TaskInputFile, WorkshopBackendRuntime
from core.workshop.backend.tooling import locate_uv_executable
from core.workshop.installer import WorkshopInstaller
from workshop_backend_fixture import (
    backend_manifest,
    build_fixture_wheelhouse,
    decode_png_rgba,
    encode_png_rgba,
    lock_text,
    write_backend_package,
)

SDK_SOURCE = os.environ.get("LUMINA_WORKSHOP_SDK_PYTHON_SRC", "")
pytestmark = pytest.mark.skipif(
    not SDK_SOURCE or locate_uv_executable() is None,
    reason="set LUMINA_WORKSHOP_SDK_PYTHON_SRC to the public SDK python/src",
)

SDK_MODULE_MAIN = '''
from lumina_workshop_backend import Backend, TaskFailure

backend = Backend()


@backend.operation("alpha-invert")
def alpha_invert(task):
    from png_codec import decode, encode

    width, height, pixels = decode(task.inputs["image"].read_bytes())
    task.progress(1, 2, "invert")
    inverted = bytearray(pixels)
    for index in range(3, len(inverted), 4):
        inverted[index] = 255 - inverted[index]
    task.check_cancelled()
    task.write_output("image", "result.png", "image/png", encode(width, height, bytes(inverted)))


@backend.operation("long")
def long_running(task):
    import time

    for step in range(10_000):
        task.check_cancelled()
        task.progress(step, 10_000, "waiting")
        time.sleep(0.01)


@backend.operation("reject")
def reject(task):
    raise TaskFailure("sample-rejected", "The sample was rejected.")


if __name__ == "__main__":
    backend.serve()
'''


def _png_codec_source() -> str:
    from workshop_backend_fixture import FIXTURE_BACKEND_MAIN

    start = FIXTURE_BACKEND_MAIN.index("def decode_png(")
    end = FIXTURE_BACKEND_MAIN.index("def dependency_versions(")
    codec = FIXTURE_BACKEND_MAIN[start:end]
    return "import struct\nimport zlib\n\n" + codec.replace("decode_png", "decode").replace("encode_png", "encode")


def _vendored_sdk() -> dict[str, bytes]:
    root = Path(SDK_SOURCE) / "lumina_workshop_backend"
    return {
        f"backend/lumina_workshop_backend/{path.relative_to(root).as_posix()}": path.read_bytes()
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def _wait(runtime: WorkshopBackendRuntime, module_id: str, task_id: str, timeout: float = 120):  # noqa: ANN202
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = runtime.get_task(module_id, task_id)
        if record.terminal:
            return record
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def test_public_python_sdk_runs_through_the_host_runtime(tmp_path: Path) -> None:
    wheels = build_fixture_wheelhouse(tmp_path / "wheelhouse")
    data_dir = tmp_path / "workshop"
    holder: dict[str, WorkshopBackendRuntime] = {}

    def installer() -> WorkshopInstaller:
        runtime = holder["runtime"]
        return WorkshopInstaller(data_dir=data_dir, after_extract=runtime.record_package, version_in_use=runtime.version_in_use)

    runtime = WorkshopBackendRuntime(
        data_dir=data_dir,
        installer_factory=installer,
        uv_executable=locate_uv_executable(),
        model_fetcher=None,  # type: ignore[arg-type]
        review_context=lambda: ReviewContext(registry=None, attestations=None),
        wheel_sources=WheelSourcePolicy(wheelhouse=tmp_path / "wheelhouse", offline=True),
        external_python=Path(sys._base_executable),
        settings=RuntimeSettings(cancel_grace_seconds=2.0, start_timeout_seconds=60.0),
    )
    holder["runtime"] = runtime
    module_id = "fixture.public-sdk"
    files = {**_vendored_sdk(), "backend/png_codec.py": _png_codec_source().encode("utf-8")}
    package = write_backend_package(
        tmp_path / "package",
        module_id=module_id,
        version="1.0.0",
        lock=lock_text([wheels["shared"]]),
        manifest=backend_manifest(module_id, "1.0.0"),
        extra_files={**files, "backend/main.py": SDK_MODULE_MAIN.encode("utf-8")},
    )
    try:
        installer().install_candidate(package, source="local", source_repository="local", official=False)
        runtime.authorize(module_id, "1.0.0", acknowledge_unreviewed=True)
        prepared = _wait(runtime, module_id, runtime.start_preparation(module_id, "1.0.0").task_id)
        assert prepared.status == "succeeded", prepared.error

        width, height = 6, 3
        pixels = bytes(value for index in range(width * height) for value in (10, 20, 30, index * 13 % 256))
        source = tmp_path / "in.png"
        source.write_bytes(encode_png_rgba(width, height, pixels))
        task = runtime.submit(
            module_id,
            "1.0.0",
            operation="alpha-invert",
            params={},
            inputs=[TaskInputFile(name="image", file_name="in.png", mime_type="image/png", path=source)],
            idempotency_key=None,
        )
        done = _wait(runtime, module_id, task.task_id)
        assert done.status == "succeeded", done.error
        path, _entry = runtime.output_file(module_id, done.task_id, "image")
        assert decode_png_rgba(path.read_bytes())[2][3::4] == bytes(255 - value for value in pixels[3::4])

        failed = _wait(runtime, module_id, runtime.submit(module_id, "1.0.0", operation="reject", params={}, inputs=[], idempotency_key=None).task_id)
        assert failed.error is not None and failed.error.code == "sample-rejected"

        long_task = runtime.submit(module_id, "1.0.0", operation="long", params={}, inputs=[], idempotency_key=None)
        deadline = time.monotonic() + 30
        while runtime.get_task(module_id, long_task.task_id).progress is None:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        pid = runtime.describe(module_id, "1.0.0")["runtime"]["pid"]
        runtime.cancel_task(module_id, long_task.task_id)
        assert _wait(runtime, module_id, long_task.task_id).status == "cancelled"
        # Cooperative cancellation through the SDK keeps the process alive.
        assert runtime.describe(module_id, "1.0.0")["runtime"]["pid"] == pid
    finally:
        runtime.shutdown()
