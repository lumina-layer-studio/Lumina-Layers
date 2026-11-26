"""Host runtime against the public Python backend SDK (cross-repository check).

Set ``LUMINA_WORKSHOP_SDK_PYTHON_SRC`` to the SDK checkout's ``python/src``
directory (or an unpacked SDK wheel) to run. The module package vendors that
SDK copy under ``backend/`` exactly as module authors are told to.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from core.workshop.backend import model_files, wheel_files
from core.workshop.backend.downloads import DownloadPreferences
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
    WHEEL_URL_BASE,
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


@backend.operation("labels")
def labels(task):
    task.write_output("labels", "labels.json", "application/json", task.artifacts["labels"].read_bytes())


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


def test_python_dependency_only_packages_prepare_and_run_with_the_public_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheels = build_fixture_wheelhouse(tmp_path / "wheelhouse")
    wheel = wheels["shared"]
    wheel_path = f"packages/ab/cd/{wheel.path.name}"
    origin = f"https://files.pythonhosted.org/{wheel_path}"
    downloaded_from: list[str] = []

    def fetch(url, target, *, cancel, progress, **_kwargs):
        downloaded_from.append(url)
        target.write_bytes(wheel.path.read_bytes())
        progress(wheel.size, wheel.size)

    monkeypatch.setattr(wheel_files, "download_https", fetch)
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
        track_downloads=True,
        external_python=Path(sys._base_executable),
        settings=RuntimeSettings(cancel_grace_seconds=2.0, start_timeout_seconds=60.0),
    )
    holder["runtime"] = runtime
    files = {**_vendored_sdk(), "backend/png_codec.py": _png_codec_source().encode("utf-8")}

    def stage(module_id: str) -> dict:
        manifest = backend_manifest(module_id, "1.0.0")
        del manifest["backend"]["models"]
        package = write_backend_package(
            tmp_path / "package",
            module_id=module_id,
            version="1.0.0",
            lock=lock_text([wheel]).replace(WHEEL_URL_BASE + wheel.path.name, origin),
            manifest=manifest,
            extra_files={**files, "backend/main.py": SDK_MODULE_MAIN.encode("utf-8")},
        )
        installer().install_candidate(package, source="local", source_repository="local", official=False)
        return runtime.describe(module_id, "1.0.0")

    try:
        module_id = "fixture.public-sdk"
        before = stage(module_id)
        assert before["download_plan"] == {
            "python": [], "models": [], "artifacts": [],
            "wheels": [{
                "original": "files.pythonhosted.org",
                "sources": ["pypi.tuna.tsinghua.edu.cn", "files.pythonhosted.org"],
                "count": 1, "bytes": wheel.size, "unknown_size_count": 0,
            }],
        }
        assert before["download_estimate"] == {"bytes": wheel.size, "incomplete": False}
        runtime.authorize(module_id, "1.0.0", acknowledge_unreviewed=True)
        prepared = _wait(runtime, module_id, runtime.start_preparation(module_id, "1.0.0").task_id)
        assert prepared.status == "succeeded", prepared.error
        assert prepared.progress is not None and prepared.progress.downloaded_bytes == wheel.size
        assert downloaded_from == [f"https://pypi.tuna.tsinghua.edu.cn/{wheel_path}"]

        second = "fixture.other-python-module"
        shared = stage(second)
        assert shared["download_plan"] == {"python": [], "wheels": [], "models": [], "artifacts": []}
        assert shared["dependencies"]["environment_reused"]
        runtime.authorize(second, "1.0.0", acknowledge_unreviewed=True)
        prepared = _wait(runtime, second, runtime.start_preparation(second, "1.0.0").task_id)
        assert prepared.status == "succeeded", prepared.error
        assert prepared.progress is not None and prepared.progress.downloaded_bytes == 0
        assert downloaded_from == [f"https://pypi.tuna.tsinghua.edu.cn/{wheel_path}"]

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


def test_download_selection_verifies_mirrors_and_reuses_bytes_across_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheels = build_fixture_wheelhouse(tmp_path / "fixtures")
    shared, extra = wheels["shared"], wheels["conflict-1"]
    inactive = wheels["accel"]
    target_version = ".".join(str(part) for part in sys.version_info[:3])
    shared_origin = "https://files.pythonhosted.org/packages/ab/cd/" + shared.path.name
    extra_origin = WHEEL_URL_BASE + extra.path.name
    mirror = f"https://wheel-mirror.example/{shared.path.name}"
    labels = b'["dog", "cat"]'
    labels_origin = "https://huggingface.co/example/labels.json"
    labels_mirror = "https://modelscope.cn/example/labels.json"
    payloads = {
        mirror: b"x" * shared.size,
        shared_origin: shared.path.read_bytes(),
        extra_origin: extra.path.read_bytes(),
        labels_mirror: labels,
    }
    fetched: list[str] = []

    def fetch(url, target, *, cancel, progress, **_kwargs):
        fetched.append(url)
        data = payloads[url]
        progress(0, len(data))
        target.write_bytes(data)
        progress(len(data), len(data))

    monkeypatch.setattr(wheel_files, "download_https", fetch)
    monkeypatch.setattr(model_files, "download_https", fetch)
    data_dir = tmp_path / "workshop"

    def installer() -> WorkshopInstaller:
        return WorkshopInstaller(data_dir=data_dir, after_extract=runtime.record_package)

    def start_runtime(*, offline: bool = False) -> WorkshopBackendRuntime:
        return WorkshopBackendRuntime(
            data_dir=data_dir,
            installer_factory=installer,
            uv_executable=locate_uv_executable(),
            model_fetcher=model_files.HttpsModelFetcher(),
            review_context=lambda: ReviewContext(registry=None, attestations=None),
            external_python=Path(sys._base_executable),
            wheel_sources=WheelSourcePolicy(offline=offline),
            track_downloads=True,
        )

    runtime = start_runtime()

    def install(module_id, lock, expected_bytes):
        manifest = backend_manifest(module_id, "1.0.0")
        manifest["workshopApi"]["min"] = "1.2.0"
        manifest["backend"].update(
            artifacts=[{
                "id": "labels", "fileName": "labels.json", "url": labels_origin,
                "mirrors": [labels_mirror], "license": "CC0-1.0", "bytes": len(labels),
                "sha256": hashlib.sha256(labels).hexdigest(),
            }],
        )
        mirrors = {inactive.sha256: ["https://unavailable-platform.example/unused.whl"]}
        if shared in lock:
            mirrors[shared.sha256] = [mirror]
        manifest["backend"]["downloadSources"] = {"wheels": mirrors}
        declared_lock = lock_text([*lock, inactive]).replace(
            f'name = "{inactive.name}"\n', f'name = "{inactive.name}"\nmarker = "sys_platform == \'unavailable\'"\n',
        )
        if shared in lock:
            declared_lock = declared_lock.replace(
                f'name = "{shared.name}"\n',
                f'name = "{shared.name}"\nmarker = "python_full_version == \'{target_version}\'"\n',
            ).replace(WHEEL_URL_BASE + shared.path.name, shared_origin)
        package = write_backend_package(
            tmp_path / module_id, module_id=module_id, version="1.0.0",
            lock=declared_lock, manifest=manifest,
            extra_files={**_vendored_sdk(), "backend/main.py": SDK_MODULE_MAIN.encode("utf-8")},
        )
        installer().install_candidate(package, source="local", source_repository="local", official=False)
        description = runtime.describe(module_id, "1.0.0")
        assert description["download_sources"]["artifacts"] == ["huggingface.co", "modelscope.cn"]
        assert description["download_estimate"] == {"bytes": expected_bytes, "incomplete": False}
        assert "unavailable-platform.example" not in description["download_sources"]["wheels"]
        if shared in lock:
            assert "wheel-mirror.example" in description["download_sources"]["wheels"]
        plan = description["download_plan"]
        if expected_bytes == shared.size + len(labels):
            assert plan["wheels"] == [{
                "original": "files.pythonhosted.org",
                "sources": ["pypi.tuna.tsinghua.edu.cn", "files.pythonhosted.org", "wheel-mirror.example"],
                "count": 1, "bytes": shared.size, "unknown_size_count": 0,
            }]
            assert plan["artifacts"] == [{
                "original": "huggingface.co", "sources": ["modelscope.cn", "huggingface.co"], "count": 1,
                "bytes": len(labels), "unknown_size_count": 0,
            }]
        else:
            assert plan["artifacts"] == []
            assert plan["wheels"] == (
                [{
                    "original": "files.example.invalid", "sources": ["files.example.invalid"],
                    "count": 1, "bytes": extra.size, "unknown_size_count": 0,
                }]
                if expected_bytes else []
            )
        runtime.authorize(module_id, "1.0.0", acknowledge_unreviewed=True)
        task = runtime.start_preparation(
            module_id, "1.0.0",
            sources=DownloadPreferences(wheels="wheel-mirror.example"),
        )
        prepared = _wait(runtime, module_id, task.task_id)
        assert prepared.status == "succeeded", prepared.error
        assert prepared.progress is not None
        assert (prepared.progress.phase, prepared.progress.downloaded_bytes) == ("complete", expected_bytes)
        final_description = runtime.describe(module_id, "1.0.0")
        assert final_description["download_preferences"]["wheels"] == "wheel-mirror.example"
        assert final_description["download_plan"] == {"python": [], "wheels": [], "models": [], "artifacts": []}

    try:
        first_module = "fixture.download-one"
        install(first_module, [shared], shared.size + len(labels))
        assert fetched == [mirror, shared_origin, labels_mirror]
        install("fixture.download-two", [shared, extra], extra.size)
        assert fetched == [mirror, shared_origin, labels_mirror, extra_origin]

        task = runtime.submit(
            first_module, "1.0.0", operation="labels", params={}, inputs=[], idempotency_key=None,
        )
        done = _wait(runtime, first_module, task.task_id)
        assert done.status == "succeeded", done.error
        output, _entry = runtime.output_file(first_module, done.task_id, "labels")
        assert output.read_bytes() == labels
        runtime.shutdown()

        alternative_name = extra.path.name.replace("lumina_fixture_conflict", "lumina.fixture.conflict", 1)
        assert alternative_name != extra.path.name
        aliased = replace(extra, path=extra.path.with_name(alternative_name))
        aliased.path.write_bytes(extra.path.read_bytes())
        leftover = runtime.root / "wheels" / extra.sha256 / ".old-download.part"
        leftover.write_bytes(b"leftover")
        runtime = start_runtime(offline=True)
        runtime.startup()
        assert not leftover.exists()
        install("fixture.download-three", [aliased], 0)
        assert fetched == [mirror, shared_origin, labels_mirror, extra_origin]
        assert runtime.storage_overview()["wheel_cache"] == {"files": 2, "bytes": shared.size + extra.size}
        # The declared lock is non-empty, but its only dependency belongs to
        # another platform. The selected empty lock must remain valid for uv.
        install("fixture.download-no-platform-wheels", [], 0)
        assert fetched == [mirror, shared_origin, labels_mirror, extra_origin]
    finally:
        runtime.shutdown()
