"""End-to-end runtime behavior with real uv, real processes, synthetic wheels.

These tests drive the public runtime facade the API uses. They need the
pinned uv binary from requirements.txt and run fully offline.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psutil
import pytest

from core.workshop.backend import runtime as runtime_module
from core.workshop.backend import store as store_module
from core.workshop.backend.locks import WheelSourcePolicy
from core.workshop.backend.review import ReviewContext
from core.workshop.backend.runtime import RuntimeSettings, TaskInputFile, WorkshopBackendRuntime
from core.workshop.backend.tooling import locate_uv_executable
from core.workshop.errors import WorkshopBackendError, WorkshopInstallError
from core.workshop.installer import WorkshopInstaller
from workshop_backend_fixture import (
    FIXTURE_BACKEND_MAIN,
    SHARED_PAYLOAD_BYTES,
    backend_manifest,
    build_fixture_wheelhouse,
    decode_png_rgba,
    encode_png_rgba,
    lock_text,
    write_backend_package,
)

UV = locate_uv_executable()
pytestmark = pytest.mark.skipif(UV is None, reason="pinned uv from requirements.txt is not installed")
MODEL_BYTES = b"synthetic-model-weights-" * 4096


class FakeModelFetcher:
    """Serve declared model bytes from memory and count real downloads."""

    def __init__(self, files: dict[str, bytes], *, block: threading.Event | None = None) -> None:
        self.files = files
        self.calls: list[str] = []
        self.block = block

    def fetch(self, url, destination, *, expected_bytes, cancel, progress):  # noqa: ANN001
        self.calls.append(url)
        if self.block is not None:
            while not self.block.is_set():
                if cancel is not None:
                    cancel.raise_if_cancelled()
                time.sleep(0.05)
        data = self.files[url]
        destination.write_bytes(data)
        progress(len(data))


class HoldingFetcher(FakeModelFetcher):
    """Write the whole file, then keep the download open until released."""

    def __init__(self, files: dict[str, bytes]) -> None:
        super().__init__(files)
        self.written = threading.Event()
        self.release = threading.Event()
        self.destination: Path | None = None

    def fetch(self, url, destination, *, expected_bytes, cancel, progress):  # noqa: ANN001
        self.calls.append(url)
        destination.write_bytes(self.files[url])
        self.destination = destination
        progress(len(self.files[url]))
        self.written.set()
        while not self.release.wait(0.05):
            if cancel is not None:
                cancel.raise_if_cancelled()


def model_spec(url: str, file_name: str) -> dict[str, object]:
    return {
        "id": file_name.split(".", 1)[0],
        "fileName": file_name,
        "url": url,
        "sha256": hashlib.sha256(MODEL_BYTES).hexdigest(),
        "bytes": len(MODEL_BYTES),
        "license": "CC0-1.0",
    }


class Harness:
    def __init__(self, tmp_path: Path, *, fetcher: FakeModelFetcher | None = None,
                 review: ReviewContext | None = None, idle: float = 60.0) -> None:
        self.tmp_path = tmp_path
        self.data_dir = tmp_path / "workshop"
        self.packages = tmp_path / "packages"
        self.wheels = build_fixture_wheelhouse(tmp_path / "wheelhouse")
        self.fetcher = fetcher or FakeModelFetcher({})
        self.review = review or ReviewContext(registry=None, attestations=None)
        self.runtime = self._make_runtime(idle)

    def _make_runtime(self, idle: float) -> WorkshopBackendRuntime:
        holder: dict[str, WorkshopBackendRuntime] = {}

        def installer() -> WorkshopInstaller:
            runtime = holder["runtime"]
            return WorkshopInstaller(
                data_dir=self.data_dir,
                after_extract=runtime.record_package,
                version_in_use=runtime.version_in_use,
            )

        runtime = WorkshopBackendRuntime(
            data_dir=self.data_dir,
            installer_factory=installer,
            uv_executable=UV,
            model_fetcher=self.fetcher,
            review_context=lambda: self.review,
            wheel_sources=WheelSourcePolicy(wheelhouse=self.tmp_path / "wheelhouse", offline=True),
            external_python=Path(sys._base_executable),
            settings=RuntimeSettings(
                idle_timeout_seconds=idle,
                cancel_grace_seconds=1.0,
                start_timeout_seconds=60.0,
            ),
        )
        holder["runtime"] = runtime
        return runtime

    def installer(self) -> WorkshopInstaller:
        return self.runtime._installer()  # noqa: SLF001 - same factory as the API

    def install(self, module_id: str, version: str, lock: str, **manifest_options) -> None:  # noqa: ANN003
        manifest = backend_manifest(module_id, version, **manifest_options)
        package = write_backend_package(
            self.packages / f"{module_id}-{version}",
            module_id=module_id,
            version=version,
            lock=lock,
            manifest=manifest,
        )
        self.installer().install_candidate(package, source="local", source_repository="local", official=False)

    def prepare(self, module_id: str, version: str, *, activate: bool = True) -> dict:
        self.runtime.authorize(module_id, version, acknowledge_unreviewed=True)
        task = self.runtime.start_preparation(module_id, version)
        finished = wait_terminal(self.runtime, module_id, task.task_id, timeout=180)
        assert finished.status == "succeeded", finished.error
        if activate:
            self.runtime.require_activatable(module_id, version)
            self.installer().activate(module_id, version)
        return self.runtime.describe(module_id, version)

    def run(self, module_id: str, version: str, operation: str, params: dict | None = None,
            inputs: list[TaskInputFile] | None = None):  # noqa: ANN201
        task = self.runtime.submit(module_id, version, operation=operation, params=params or {},
                                   inputs=inputs or [], idempotency_key=None)
        return wait_terminal(self.runtime, module_id, task.task_id)

    def output_json(self, record, name: str) -> dict:  # noqa: ANN001
        path, _entry = self.runtime.output_file(record.module_id, record.task_id, name)
        return json.loads(path.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.runtime.shutdown()


def wait_terminal(runtime: WorkshopBackendRuntime, module_id: str, task_id: str, timeout: float = 60):  # noqa: ANN201
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = runtime.get_task(module_id, task_id)
        if record.terminal:
            return record
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish: {runtime.get_task(module_id, task_id)}")


def wait_until(predicate, timeout: float = 30.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not reached")


def env_file(runtime: WorkshopBackendRuntime, key: str, relative: str) -> Path:
    root = runtime.environments.path(key)
    matches = list(root.rglob(relative))
    assert matches, f"{relative} not found in environment {key}"
    return matches[0]


@pytest.fixture
def harness(tmp_path: Path):  # noqa: ANN201
    value = Harness(tmp_path)
    yield value
    value.close()


def two_module_locks(h: Harness) -> tuple[str, str]:
    lock_a = lock_text([h.wheels["shared"], h.wheels["conflict-1"]])
    lock_b = lock_text([h.wheels["shared"], h.wheels["conflict-2"]])
    return lock_a, lock_b


def test_shared_dependency_is_stored_once_and_conflicting_versions_coexist(harness: Harness) -> None:
    lock_a, lock_b = two_module_locks(harness)
    harness.install("fixture.alpha", "1.0.0", lock_a)
    harness.install("fixture.beta", "1.0.0", lock_b)
    alpha = harness.prepare("fixture.alpha", "1.0.0")
    preview_b = harness.runtime.describe("fixture.beta", "1.0.0")
    # Preview before preparation: the shared package is already present.
    assert preview_b["dependencies"]["shared_package_count"] == 1
    assert preview_b["dependencies"]["package_count"] == 2
    beta = harness.prepare("fixture.beta", "1.0.0")

    key_a = alpha["dependencies"]["environment_key"]
    key_b = beta["dependencies"]["environment_key"]
    assert key_a != key_b
    payload_a = env_file(harness.runtime, key_a, "lumina_fixture_shared/payload.bin").stat()
    payload_b = env_file(harness.runtime, key_b, "lumina_fixture_shared/payload.bin").stat()
    assert (payload_a.st_dev, payload_a.st_ino) == (payload_b.st_dev, payload_b.st_ino)
    footprint = beta["footprint"]
    assert footprint["environment_shared_bytes"] >= SHARED_PAYLOAD_BYTES
    # Second environment adds only its differing files, not the shared payload.
    assert footprint["environment_new_bytes"] < alpha["footprint"]["environment_new_bytes"]

    result_a = harness.run("fixture.alpha", "1.0.0", "versions")
    result_b = harness.run("fixture.beta", "1.0.0", "versions")
    assert harness.output_json(result_a, "versions")["versions"]["lumina_fixture_conflict"] == "1.0.0"
    assert harness.output_json(result_b, "versions")["versions"]["lumina_fixture_conflict"] == "2.0.0"


def test_identical_locks_share_one_environment(harness: Harness) -> None:
    lock = lock_text([harness.wheels["shared"]])
    harness.install("fixture.alpha", "1.0.0", lock)
    harness.install("fixture.beta", "1.0.0", lock)
    alpha = harness.prepare("fixture.alpha", "1.0.0")
    beta = harness.prepare("fixture.beta", "1.0.0")
    assert alpha["dependencies"]["environment_key"] == beta["dependencies"]["environment_key"]
    assert beta["footprint"]["reused_environment"] is True
    assert beta["footprint"]["environment_new_bytes"] == 0
    assert len(harness.runtime.environments.list()) == 1


def test_task_result_outlives_backend_stop_and_keeps_png_alpha(harness: Harness) -> None:
    harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"]]))
    harness.prepare("fixture.alpha", "1.0.0")
    width, height = 7, 5
    pixels = bytes(
        value
        for index in range(width * height)
        for value in (index * 7 % 256, 40, 200, index * 11 % 256)
    )
    source = harness.tmp_path / "input.png"
    source.write_bytes(encode_png_rgba(width, height, pixels))
    record = harness.run(
        "fixture.alpha",
        "1.0.0",
        "alpha-invert",
        inputs=[TaskInputFile(name="image", file_name="input.png", mime_type="image/png", path=source)],
    )
    assert record.status == "succeeded", record.error
    harness.runtime.stop_backend_process("fixture.alpha")
    wait_until(lambda: harness.runtime.describe("fixture.alpha", "1.0.0")["runtime"]["pid"] is None)
    path, entry = harness.runtime.output_file("fixture.alpha", record.task_id, "image")
    assert entry.mime_type == "image/png"
    out_width, out_height, out_pixels = decode_png_rgba(path.read_bytes())
    assert (out_width, out_height) == (width, height)
    assert out_pixels[3::4] == bytes(255 - value for value in pixels[3::4])
    assert out_pixels[0::4] == pixels[0::4]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry.sha256


def test_inputs_keep_their_names_and_never_overwrite_each_other(harness: Harness) -> None:
    harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"]]))
    harness.prepare("fixture.alpha", "1.0.0")
    file_name = "a" * 124 + ".png"  # the longest name the public contract accepts
    first, second = harness.tmp_path / "first.bin", harness.tmp_path / "second.bin"
    first.write_bytes(b"first input")
    second.write_bytes(b"second input")
    record = harness.run(
        "fixture.alpha",
        "1.0.0",
        "inputs",
        inputs=[
            TaskInputFile(name="left", file_name=file_name, mime_type="image/png", path=first),
            TaskInputFile(name="right", file_name=file_name, mime_type="image/png", path=second),
        ],
    )
    assert record.status == "succeeded", record.error
    assert [item.file_name for item in record.inputs] == [file_name, file_name]
    seen = {item["name"]: item for item in harness.output_json(record, "inputs")}
    assert seen["left"]["fileName"] == seen["right"]["fileName"] == file_name
    assert seen["left"]["path"] != seen["right"]["path"]
    assert seen["left"]["sha256"] == hashlib.sha256(b"first input").hexdigest()
    assert seen["right"]["sha256"] == hashlib.sha256(b"second input").hexdigest()


def test_cancel_ends_backend_that_ignores_cooperative_cancel(harness: Harness) -> None:
    harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"]]))
    harness.prepare("fixture.alpha", "1.0.0")
    task = harness.runtime.submit("fixture.alpha", "1.0.0", operation="stubborn", params={}, inputs=[], idempotency_key=None)
    work = harness.runtime.tasks.work_dir(harness.runtime.get_task("fixture.alpha", task.task_id))
    wait_until(lambda: (work / "helper.pid").is_file())
    helper_pid = int((work / "helper.pid").read_text(encoding="utf-8"))
    backend_pid = harness.runtime.describe("fixture.alpha", "1.0.0")["runtime"]["pid"]
    identities = {pid: psutil.Process(pid).create_time() for pid in (backend_pid, helper_pid)}
    harness.runtime.cancel_task("fixture.alpha", task.task_id)
    final = wait_terminal(harness.runtime, "fixture.alpha", task.task_id, timeout=30)
    assert final.status == "cancelled"

    def gone(pid: int, created: float) -> bool:
        try:
            return psutil.Process(pid).create_time() != created
        except psutil.NoSuchProcess:
            return True

    wait_until(lambda: all(gone(pid, created) for pid, created in identities.items()))
    time.sleep(0.5)
    assert harness.runtime.get_task("fixture.alpha", task.task_id).status == "cancelled"
    # The next task starts a fresh backend and succeeds.
    assert harness.run("fixture.alpha", "1.0.0", "echo").status == "succeeded"


def test_cooperative_cancel_keeps_backend_and_progress_is_visible(harness: Harness) -> None:
    harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"]]))
    harness.prepare("fixture.alpha", "1.0.0")
    task = harness.runtime.submit("fixture.alpha", "1.0.0", operation="slow", params={"steps": 400, "delay": 0.05}, inputs=[], idempotency_key="key-1")
    wait_until(lambda: harness.runtime.get_task("fixture.alpha", task.task_id).progress is not None)
    again = harness.runtime.submit("fixture.alpha", "1.0.0", operation="slow", params={}, inputs=[], idempotency_key="key-1")
    assert again.task_id == task.task_id
    pid = harness.runtime.describe("fixture.alpha", "1.0.0")["runtime"]["pid"]
    harness.runtime.cancel_task("fixture.alpha", task.task_id)
    assert wait_terminal(harness.runtime, "fixture.alpha", task.task_id).status == "cancelled"
    assert harness.run("fixture.alpha", "1.0.0", "echo").status == "succeeded"
    assert harness.runtime.describe("fixture.alpha", "1.0.0")["runtime"]["pid"] == pid


def test_failure_and_noise_do_not_break_the_control_channel(harness: Harness) -> None:
    harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"]]))
    harness.prepare("fixture.alpha", "1.0.0")
    failed = harness.run("fixture.alpha", "1.0.0", "fail")
    assert failed.status == "failed"
    assert failed.error is not None and failed.error.code == "fixture-failure"
    assert harness.run("fixture.alpha", "1.0.0", "noisy").status == "succeeded"


def test_disable_cancels_tasks_and_stops_process(harness: Harness) -> None:
    harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"]]))
    harness.prepare("fixture.alpha", "1.0.0")
    task = harness.runtime.submit("fixture.alpha", "1.0.0", operation="slow", params={"steps": 1000}, inputs=[], idempotency_key=None)
    wait_until(lambda: harness.runtime.get_task("fixture.alpha", task.task_id).status == "running")
    pid = harness.runtime.describe("fixture.alpha", "1.0.0")["runtime"]["pid"]
    harness.installer().set_enabled("fixture.alpha", False)
    harness.runtime.module_disabled("fixture.alpha")
    final = harness.runtime.get_task("fixture.alpha", task.task_id)
    assert final.status == "cancelled" and final.error is not None
    assert final.error.code == "module-disabled"
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    with pytest.raises(WorkshopBackendError) as error:
        harness.runtime.submit("fixture.alpha", "1.0.0", operation="echo", params={}, inputs=[], idempotency_key=None)
    assert error.value.code == "module-disabled"


def test_idle_backend_is_released(tmp_path: Path) -> None:
    harness = Harness(tmp_path, idle=1.0)
    try:
        harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"]]))
        harness.prepare("fixture.alpha", "1.0.0")
        assert harness.run("fixture.alpha", "1.0.0", "echo").status == "succeeded"
        pid = harness.runtime.describe("fixture.alpha", "1.0.0")["runtime"]["pid"]
        assert pid is not None
        wait_until(lambda: harness.runtime.describe("fixture.alpha", "1.0.0")["runtime"]["state"] == "stopped", timeout=20)
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    finally:
        harness.close()


def _runtime_program_bytes(runtime: WorkshopBackendRuntime) -> int:
    """Physical bytes of program content (envs, store, cache, models, scratch)."""

    seen: set[tuple[int, int]] = set()
    total = 0
    for name in ("envs", "store", "uv-cache", "python", "models", "scratch"):
        root = runtime.root / name
        if not root.exists():
            continue
        for directory, _dirs, files in os.walk(root):
            for file_name in files:
                info = (Path(directory) / file_name).lstat()
                key = (info.st_dev, info.st_ino)
                if key not in seen:
                    seen.add(key)
                    total += info.st_size
    return total


def test_uninstall_keeps_other_module_and_last_user_reclaims_everything(harness: Harness) -> None:
    lock_a, lock_b = two_module_locks(harness)
    harness.install("fixture.alpha", "1.0.0", lock_a)
    harness.install("fixture.beta", "1.0.0", lock_b)
    harness.prepare("fixture.alpha", "1.0.0")
    beta = harness.prepare("fixture.beta", "1.0.0")
    kept_result = harness.run("fixture.alpha", "1.0.0", "echo")
    assert kept_result.status == "succeeded"

    _state, report = harness.runtime.uninstall_module("fixture.alpha", delete_projects=False, delete_task_data=False, retain_models=False)
    kinds = {item["kind"] for item in report.cleared}
    assert {"module-code", "environments"} <= kinds
    assert any(item["kind"] == "task-data" for item in report.retained)
    assert any(item["kind"] == "shared-files" and item["users"] == ["fixture.beta"] for item in report.shared)
    # Module B still runs with its shared payload intact.
    result = harness.run("fixture.beta", "1.0.0", "versions")
    assert harness.output_json(result, "versions")["versions"]["lumina_fixture_shared"] == "1.0.0"
    assert env_file(harness.runtime, beta["dependencies"]["environment_key"], "lumina_fixture_shared/payload.bin").is_file()
    # Retained task results do not keep the uninstalled module's program files.
    assert len(harness.runtime.environments.list()) == 1

    _state, report = harness.runtime.uninstall_module("fixture.beta", delete_projects=False, delete_task_data=True, retain_models=False)
    assert harness.runtime.environments.list() == ()
    assert harness.runtime.store.usage() == (0, 0)
    assert _runtime_program_bytes(harness.runtime) == 0
    assert harness.runtime.tasks.module_usage().get("fixture.beta") is None
    # Retained results of the first module are still readable.
    path, _entry = harness.runtime.output_file("fixture.alpha", kept_result.task_id, "echo")
    assert path.is_file()
    assert not report.failed


def test_retained_model_is_reused_after_reinstall_and_can_be_deleted(tmp_path: Path) -> None:
    url = "https://models.example.invalid/fixture/matte.bin"
    fetcher = FakeModelFetcher({url: MODEL_BYTES})
    harness = Harness(tmp_path, fetcher=fetcher)
    model = {
        "id": "matte",
        "fileName": "matte.bin",
        "url": url,
        "sha256": hashlib.sha256(MODEL_BYTES).hexdigest(),
        "bytes": len(MODEL_BYTES),
        "license": "CC0-1.0",
    }
    try:
        lock = lock_text([harness.wheels["shared"]])
        harness.install("fixture.alpha", "1.0.0", lock, models=[model])
        harness.prepare("fixture.alpha", "1.0.0")
        result = harness.run("fixture.alpha", "1.0.0", "versions")
        model_path = Path(harness.output_json(result, "versions")["models"]["matte"])
        assert model_path.read_bytes() == MODEL_BYTES
        assert len(fetcher.calls) == 1

        _state, report = harness.runtime.uninstall_module("fixture.alpha", delete_projects=False, delete_task_data=True, retain_models=True)
        assert any(item["kind"] == "model" for item in report.retained)
        assert harness.runtime.store.has(model["sha256"])

        harness.install("fixture.alpha", "1.0.0", lock, models=[model])
        reinstalled = harness.prepare("fixture.alpha", "1.0.0")
        assert len(fetcher.calls) == 1
        assert reinstalled["footprint"]["model_shared_bytes"] == len(MODEL_BYTES)

        harness.runtime.uninstall_module("fixture.alpha", delete_projects=False, delete_task_data=True, retain_models=False)
        assert harness.runtime.store.has(model["sha256"])  # still retained by the user
        harness.runtime.delete_retained_model(model["sha256"])
        assert not harness.runtime.store.has(model["sha256"])
        assert _runtime_program_bytes(harness.runtime) == 0
    finally:
        harness.close()


def test_acceleration_variant_is_prepared_on_demand_and_released(harness: Harness) -> None:
    base = lock_text([harness.wheels["shared"]])
    accelerated = lock_text([harness.wheels["shared"], harness.wheels["accel"]])
    variant = {
        "id": "accel",
        "name": {"zh-CN": "合成加速", "en-US": "Synthetic acceleration"},
        "description": {"zh-CN": "仅用于测试", "en-US": "Test only"},
        "lock": "backend/pylock.accel.toml",
        "platforms": ["windows-x86_64", "linux-x86_64", "macos-arm64"],
    }
    manifest = backend_manifest("fixture.alpha", "1.0.0", variants=[variant])
    package = write_backend_package(
        harness.packages / "accel",
        module_id="fixture.alpha",
        version="1.0.0",
        lock=base,
        manifest=manifest,
        extra_files={"backend/pylock.accel.toml": accelerated.encode("utf-8")},
    )
    harness.installer().install_candidate(package, source="local", source_repository="local", official=False)
    prepared = harness.prepare("fixture.alpha", "1.0.0")
    assert len(harness.runtime.environments.list()) == 1
    assert prepared["variants"][0]["prepared"] is False
    cpu = harness.run("fixture.alpha", "1.0.0", "versions")
    assert harness.output_json(cpu, "versions")["variant"] == "cpu"

    described = harness.runtime.set_acceleration("fixture.alpha", "accel")
    task_id = described["preparation_task_id"]
    assert wait_terminal(harness.runtime, "fixture.alpha", task_id, timeout=120).status == "succeeded"
    assert len(harness.runtime.environments.list()) == 2
    accelerated_run = harness.run("fixture.alpha", "1.0.0", "versions")
    output = harness.output_json(accelerated_run, "versions")
    assert output["variant"] == "accel"
    assert output["versions"]["lumina_fixture_accel"] == "1.0.0"

    harness.runtime.set_acceleration("fixture.alpha", None)
    assert len(harness.runtime.environments.list()) == 1
    assert harness.output_json(harness.run("fixture.alpha", "1.0.0", "versions"), "versions")["variant"] == "cpu"


def test_broken_acceleration_falls_back_to_cpu(harness: Harness) -> None:
    variant = {
        "id": "accel",
        "name": {"zh-CN": "合成加速", "en-US": "Synthetic acceleration"},
        "description": {"zh-CN": "仅用于测试", "en-US": "Test only"},
        "lock": "backend/pylock.accel.toml",
        "platforms": ["windows-x86_64", "linux-x86_64", "macos-arm64"],
    }
    broken = lock_text([harness.wheels["shared"], harness.wheels["accel-broken"]])
    package = write_backend_package(
        harness.packages / "broken",
        module_id="fixture.alpha",
        version="1.0.0",
        lock=lock_text([harness.wheels["shared"]]),
        manifest=backend_manifest("fixture.alpha", "1.0.0", variants=[variant]),
        extra_files={"backend/pylock.accel.toml": broken.encode("utf-8")},
    )
    harness.installer().install_candidate(package, source="local", source_repository="local", official=False)
    harness.runtime.state.set_settings(
        harness.runtime.state.settings_for("fixture.alpha").model_copy(update={"acceleration": "accel"}),
        "fixture.alpha",
    )
    prepared = harness.prepare("fixture.alpha", "1.0.0")
    assert prepared["preparation"] == "prepared"
    assert prepared["variants"][0]["failure_code"] == "backend-self-check-failed"
    result = harness.run("fixture.alpha", "1.0.0", "versions")
    assert harness.output_json(result, "versions")["variant"] == "cpu"
    # The failed variant environment was not kept.
    assert len(harness.runtime.environments.list()) == 1


def test_failed_preparation_rolls_back_and_is_not_activatable(harness: Harness, tmp_path: Path) -> None:
    missing = build_fixture_wheelhouse(tmp_path / "elsewhere")["conflict-2"]
    (tmp_path / "wheelhouse" / missing.path.name).unlink(missing_ok=True)
    harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"], missing]))
    harness.runtime.authorize("fixture.alpha", "1.0.0", acknowledge_unreviewed=True)
    task = harness.runtime.start_preparation("fixture.alpha", "1.0.0")
    final = wait_terminal(harness.runtime, "fixture.alpha", task.task_id, timeout=120)
    assert final.status == "failed" and final.error is not None
    assert final.error.code == "dependency-install-failed"
    assert harness.runtime.describe("fixture.alpha", "1.0.0")["preparation"] == "failed"
    assert harness.runtime.environments.list() == ()
    assert harness.runtime.store.usage() == (0, 0)
    with pytest.raises(WorkshopBackendError) as error:
        harness.runtime.require_activatable("fixture.alpha", "1.0.0")
    assert error.value.code == "backend-not-prepared"


def test_cancelled_preparation_leaves_no_environment(tmp_path: Path) -> None:
    url = "https://models.example.invalid/fixture/slow.bin"
    block = threading.Event()
    harness = Harness(tmp_path, fetcher=FakeModelFetcher({url: MODEL_BYTES}, block=block))
    try:
        model = {
            "id": "slow",
            "fileName": "slow.bin",
            "url": url,
            "sha256": hashlib.sha256(MODEL_BYTES).hexdigest(),
            "bytes": len(MODEL_BYTES),
            "license": "CC0-1.0",
        }
        harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"]]), models=[model])
        harness.runtime.authorize("fixture.alpha", "1.0.0", acknowledge_unreviewed=True)
        task = harness.runtime.start_preparation("fixture.alpha", "1.0.0")
        wait_until(lambda: harness.fetcher.calls, timeout=120)
        harness.runtime.cancel_task("fixture.alpha", task.task_id)
        assert wait_terminal(harness.runtime, "fixture.alpha", task.task_id).status == "cancelled"
        assert harness.runtime.environments.list() == ()
        assert _runtime_program_bytes(harness.runtime) == 0
    finally:
        block.set()
        harness.close()


def test_other_modules_finishing_or_uninstalling_never_break_a_running_preparation(tmp_path: Path) -> None:
    url = "https://models.example.invalid/fixture/held.bin"
    fetcher = HoldingFetcher({url: MODEL_BYTES})
    harness = Harness(tmp_path, fetcher=fetcher)
    model = model_spec(url, "held.bin")
    try:
        lock = lock_text([harness.wheels["shared"]])
        harness.install("fixture.alpha", "1.0.0", lock, models=[model])
        harness.install("fixture.beta", "1.0.0", lock_text([harness.wheels["shared"], harness.wheels["conflict-1"]]))
        harness.install("fixture.gamma", "1.0.0", lock)
        harness.runtime.authorize("fixture.alpha", "1.0.0", acknowledge_unreviewed=True)
        task = harness.runtime.start_preparation("fixture.alpha", "1.0.0")
        assert fetcher.written.wait(180), "model download did not start"
        # While alpha's verified bytes sit in the temporary download, two
        # modules finish preparing and one is uninstalled; each of these
        # runs a full collection.
        harness.prepare("fixture.beta", "1.0.0")
        harness.prepare("fixture.gamma", "1.0.0")
        harness.runtime.uninstall_module("fixture.beta", delete_projects=False, delete_task_data=True, retain_models=False)
        assert fetcher.destination is not None and fetcher.destination.read_bytes() == MODEL_BYTES
        fetcher.release.set()
        final = wait_terminal(harness.runtime, "fixture.alpha", task.task_id, timeout=180)
        assert final.status == "succeeded", final.error
        view = harness.runtime.models.view_dir("fixture.alpha", "1.0.0") / "held.bin"
        assert view.stat().st_nlink >= 2  # linked to the shared store object
        result = harness.run("fixture.alpha", "1.0.0", "versions")
        assert Path(harness.output_json(result, "versions")["models"]["held"]).read_bytes() == MODEL_BYTES
        # Once no preparation works, transient files are cleaned as usual.
        assert list(harness.runtime.store.temporary_dir.iterdir()) == []
        assert list(harness.runtime.environments.staging_dir.iterdir()) == []
    finally:
        fetcher.release.set()
        harness.close()


def test_cancelled_model_download_releases_files_and_references(tmp_path: Path) -> None:
    url = "https://models.example.invalid/fixture/cancelled.bin"
    fetcher = HoldingFetcher({url: MODEL_BYTES})
    harness = Harness(tmp_path, fetcher=fetcher)
    model = model_spec(url, "cancelled.bin")
    try:
        harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"]]), models=[model])
        harness.install("fixture.beta", "1.0.0", lock_text([harness.wheels["shared"], harness.wheels["conflict-1"]]))
        harness.runtime.authorize("fixture.alpha", "1.0.0", acknowledge_unreviewed=True)
        task = harness.runtime.start_preparation("fixture.alpha", "1.0.0")
        assert fetcher.written.wait(180), "model download did not start"
        harness.prepare("fixture.beta", "1.0.0")  # collection while alpha downloads
        harness.runtime.cancel_task("fixture.alpha", task.task_id)
        assert wait_terminal(harness.runtime, "fixture.alpha", task.task_id).status == "cancelled"
        assert fetcher.destination is not None and not fetcher.destination.exists()
        assert list(harness.runtime.store.temporary_dir.iterdir()) == []
        assert not harness.runtime.store.has(model["sha256"])
        assert harness.runtime.store._pins == {}  # noqa: SLF001 - no lingering reference
        assert harness.runtime.describe("fixture.alpha", "1.0.0")["preparation"] != "prepared"
        harness.runtime.uninstall_module("fixture.beta", delete_projects=False, delete_task_data=True, retain_models=False)
        assert _runtime_program_bytes(harness.runtime) == 0
    finally:
        fetcher.release.set()
        harness.close()


def test_files_that_were_in_use_are_reclaimed_by_current_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://models.example.invalid/fixture/locked.bin"
    harness = Harness(tmp_path, fetcher=FakeModelFetcher({url: MODEL_BYTES}))
    runtime = harness.runtime
    model = model_spec(url, "locked.bin")
    lock = lock_text([harness.wheels["shared"]])
    real_unlink = store_module.unlink_with_retry
    in_use: set[Path] = set()

    def unlink(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        # A name another process still holds open cannot be deleted yet.
        return False if Path(path).resolve() in in_use else real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(store_module, "unlink_with_retry", unlink)

    def uninstall_while_files_are_in_use() -> str:
        harness.install("fixture.alpha", "1.0.0", lock, models=[model])
        key = harness.prepare("fixture.alpha", "1.0.0")["dependencies"]["environment_key"]
        in_use.update({
            runtime.store.object_path(model["sha256"]).resolve(),
            env_file(runtime, key, "lumina_fixture_shared/payload.bin").resolve(),
        })
        runtime.uninstall_module("fixture.alpha", delete_projects=False, delete_task_data=True, retain_models=False)
        assert in_use <= {Path(item.path).resolve() for item in runtime.state.read().pending}
        assert runtime.store.has(model["sha256"])
        assert runtime.environments.path(key).is_dir() and runtime.environments.list() == ()
        return key

    try:
        # Released leftovers that nothing uses again go with the next pass.
        uninstall_while_files_are_in_use()
        in_use.clear()
        runtime.collect_garbage()
        assert not runtime.store.has(model["sha256"])
        assert runtime.state.read().pending == ()
        assert _runtime_program_bytes(runtime) == 0

        # The same content and environment key are needed again: an earlier
        # failed deletion must not remove what the new version now uses.
        key = uninstall_while_files_are_in_use()
        harness.install("fixture.alpha", "1.0.0", lock, models=[model])
        runtime.authorize("fixture.alpha", "1.0.0", acknowledge_unreviewed=True)
        blocked = wait_terminal(runtime, "fixture.alpha", runtime.start_preparation("fixture.alpha", "1.0.0").task_id, timeout=120)
        assert blocked.status == "failed" and blocked.error is not None
        assert blocked.error.code == "environment-busy"  # actionable, not a generic failure
        in_use.clear()
        harness.prepare("fixture.alpha", "1.0.0")
        runtime.collect_garbage()
        assert runtime.environments.get(key) is not None
        assert runtime.store.has(model["sha256"])
        assert runtime.state.read().pending == ()
        result = harness.run("fixture.alpha", "1.0.0", "versions")
        assert Path(harness.output_json(result, "versions")["models"]["locked"]).read_bytes() == MODEL_BYTES

        # The user's retention choice still works for the reused model.
        runtime.uninstall_module("fixture.alpha", delete_projects=False, delete_task_data=True, retain_models=True)
        assert [item.sha256 for item in runtime.state.read().retained_models] == [model["sha256"]]
        runtime.delete_retained_model(model["sha256"])
        assert _runtime_program_bytes(runtime) == 0
    finally:
        harness.close()


def test_concurrent_uninstalls_keep_every_retained_model(tmp_path: Path) -> None:
    files = {
        f"https://models.example.invalid/fixture/{name}.bin": name.encode("ascii") * 16384
        for name in ("alpha", "beta")
    }
    harness = Harness(tmp_path, fetcher=FakeModelFetcher(files))
    runtime = harness.runtime
    specs: dict[str, dict[str, object]] = {}
    try:
        for module_id, (url, data) in zip(("fixture.alpha", "fixture.beta"), files.items()):
            specs[module_id] = {
                "id": "model",
                "fileName": "model.bin",
                "url": url,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "license": "CC0-1.0",
            }
            harness.install(module_id, "1.0.0", lock_text([harness.wheels["shared"]]), models=[specs[module_id]])
            harness.prepare(module_id, "1.0.0")
        # Each uninstall waits inside its retention step for the other (or
        # 1 s): two edits built from one old snapshot would lose a choice,
        # while a serialized edit simply waits its turn.
        arrived = threading.Barrier(2)
        real_has = runtime.store.has

        def has(sha256: str) -> bool:
            try:
                arrived.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
            return real_has(sha256)

        def uninstall(module_id: str):  # noqa: ANN202
            return runtime.uninstall_module(module_id, delete_projects=False, delete_task_data=True, retain_models=True)[1]

        with patch.object(runtime.store, "has", has), ThreadPoolExecutor(max_workers=2) as pool:
            reports = list(pool.map(uninstall, specs))
        runtime.collect_garbage()
        expected = {spec["sha256"] for spec in specs.values()}
        assert {item.sha256 for item in runtime.state.read().retained_models} == expected
        assert all(runtime.store.has(sha256) for sha256 in expected)
        assert all([item["kind"] for item in report.retained].count("model") == 1 for report in reports)
    finally:
        harness.close()


def test_failed_uninstall_never_withdraws_another_modules_retention(tmp_path: Path) -> None:
    url = "https://models.example.invalid/fixture/shared-model.bin"
    harness = Harness(tmp_path, fetcher=FakeModelFetcher({url: MODEL_BYTES}))
    runtime = harness.runtime
    model = model_spec(url, "shared-model.bin")
    real_uninstall = WorkshopInstaller.uninstall
    alpha_removing_code = threading.Event()
    beta_finished = threading.Event()

    def uninstall(installer, module_id, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if module_id == "fixture.alpha":
            alpha_removing_code.set()
            # Beta may finish first if the runtime lets it; a runtime that
            # serializes this step makes beta wait instead.
            beta_finished.wait(1)
            # Like a module file another program holds open.
            raise WorkshopInstallError("module code could not be staged for uninstall")
        return real_uninstall(installer, module_id, *args, **kwargs)

    def remove(module_id: str, keep: bool):  # noqa: ANN202
        return runtime.uninstall_module(module_id, delete_projects=False, delete_task_data=True, retain_models=keep)

    try:
        for module_id in ("fixture.alpha", "fixture.beta"):
            harness.install(module_id, "1.0.0", lock_text([harness.wheels["shared"]]), models=[model])
            harness.prepare(module_id, "1.0.0")
        with patch.object(WorkshopInstaller, "uninstall", uninstall), ThreadPoolExecutor(max_workers=1) as pool:
            alpha = pool.submit(remove, "fixture.alpha", True)
            assert alpha_removing_code.wait(30)
            try:
                _state, beta_report = remove("fixture.beta", True)
            finally:
                beta_finished.set()
            with pytest.raises(WorkshopInstallError):
                alpha.result(timeout=60)
        # Beta asked to keep the shared model and its uninstall succeeded.
        assert [item["label"] for item in beta_report.retained if item["kind"] == "model"] == ["shared-model.bin"]
        assert [item.sha256 for item in runtime.state.read().retained_models] == [model["sha256"]]
        # Alpha is still installed; removing it later without keeping models
        # must not take beta's choice with it.
        remove("fixture.alpha", False)
        runtime.collect_garbage()
        assert runtime.store.has(model["sha256"])
    finally:
        harness.close()


def test_acceleration_failure_stays_with_its_module(harness: Harness) -> None:
    variant = {
        "id": "accel",
        "name": {"zh-CN": "合成加速", "en-US": "Synthetic acceleration"},
        "description": {"zh-CN": "仅用于测试", "en-US": "Test only"},
        "lock": "backend/pylock.accel.toml",
        "platforms": ["windows-x86_64", "linux-x86_64", "macos-arm64"],
    }
    # The accelerator can disappear after a successful install (driver
    # update, device removed); the backend then fails to start in that mode.
    source = FIXTURE_BACKEND_MAIN.replace(
        'if VARIANT != "cpu":\n',
        'if VARIANT != "cpu":\n'
        "    from pathlib import Path\n"
        '    if (Path(os.environ["TMP"]) / "deny-accel").exists():\n'
        '        raise RuntimeError("synthetic accelerator unavailable")\n',
        1,
    )
    assert source != FIXTURE_BACKEND_MAIN
    accelerated = lock_text([harness.wheels["shared"], harness.wheels["accel"]])
    for module_id in ("fixture.alpha", "fixture.beta"):
        package = write_backend_package(
            harness.packages / module_id,
            module_id=module_id,
            version="1.0.0",
            lock=lock_text([harness.wheels["shared"]]),
            manifest=backend_manifest(module_id, "1.0.0", variants=[variant]),
            extra_files={
                "backend/main.py": source.encode("utf-8"),
                "backend/pylock.accel.toml": accelerated.encode("utf-8"),
            },
        )
        harness.installer().install_candidate(package, source="local", source_repository="local", official=False)
        harness.prepare(module_id, "1.0.0")
        pending = harness.runtime.set_acceleration(module_id, "accel")
        assert wait_terminal(harness.runtime, module_id, pending["preparation_task_id"], timeout=180).status == "succeeded"
    marker = harness.runtime.root / "scratch" / "fixture.alpha" / "tmp" / "deny-accel"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("accelerator unavailable", encoding="utf-8")

    alpha = harness.run("fixture.alpha", "1.0.0", "versions")
    assert harness.output_json(alpha, "versions")["variant"] == "cpu"
    assert harness.runtime.describe("fixture.alpha", "1.0.0")["variants"][0]["failure_code"] == "variant-start-failed"
    # Same version number and variant name, but another module: unaffected.
    assert harness.runtime.describe("fixture.beta", "1.0.0")["variants"][0]["failure_code"] is None
    beta = harness.run("fixture.beta", "1.0.0", "versions")
    assert harness.output_json(beta, "versions")["variant"] == "accel"


def test_models_on_volumes_without_hard_links_stay_owned_and_retainable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://models.example.invalid/fixture/copied.bin"
    fetcher = FakeModelFetcher({url: MODEL_BYTES})
    harness = Harness(tmp_path, fetcher=fetcher)
    model = model_spec(url, "copied.bin")
    real_link = os.link
    views = harness.runtime.models.views_dir.resolve()

    def link(source, target, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if Path(target).resolve().is_relative_to(views):
            raise OSError(1, "this volume has no hard links")
        return real_link(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "link", link)
    try:
        lock = lock_text([harness.wheels["shared"]])
        harness.install("fixture.alpha", "1.0.0", lock, models=[model])
        alpha = harness.prepare("fixture.alpha", "1.0.0")
        view = harness.runtime.models.view_dir("fixture.alpha", "1.0.0") / "copied.bin"
        assert view.read_bytes() == MODEL_BYTES and view.stat().st_nlink == 1
        # Nothing links to the stored object, yet the installed version owns it.
        assert harness.runtime.store.has(model["sha256"])
        # Real disk use: the stored object plus the copied view.
        assert alpha["footprint"]["model_new_bytes"] == 2 * len(MODEL_BYTES)
        assert alpha["footprint"]["model_shared_bytes"] == 0
        assert harness.runtime.storage_overview()["model_copies"] == {"files": 1, "bytes": len(MODEL_BYTES)}

        # Another module copies the stored model instead of downloading it.
        harness.install("fixture.beta", "1.0.0", lock, models=[model])
        beta = harness.prepare("fixture.beta", "1.0.0")
        assert len(fetcher.calls) == 1
        assert beta["footprint"]["model_new_bytes"] == len(MODEL_BYTES)
        harness.runtime.uninstall_module("fixture.beta", delete_projects=False, delete_task_data=True, retain_models=False)
        assert harness.runtime.store.has(model["sha256"])  # alpha still uses it

        _state, report = harness.runtime.uninstall_module(
            "fixture.alpha", delete_projects=False, delete_task_data=True, retain_models=True
        )
        assert [item["label"] for item in report.retained if item["kind"] == "model"] == ["copied.bin"]
        assert any(item["kind"] == "model-files" and item["bytes"] == len(MODEL_BYTES) for item in report.cleared)
        assert [item.sha256 for item in harness.runtime.state.read().retained_models] == [model["sha256"]]
        assert harness.runtime.store.has(model["sha256"])
        assert harness.runtime.storage_overview()["model_copies"] == {"files": 0, "bytes": 0}

        # Reinstalling reuses the kept model without downloading again.
        harness.install("fixture.alpha", "1.0.0", lock, models=[model])
        harness.prepare("fixture.alpha", "1.0.0")
        assert len(fetcher.calls) == 1
        harness.runtime.uninstall_module("fixture.alpha", delete_projects=False, delete_task_data=True, retain_models=False)
        assert harness.runtime.store.has(model["sha256"])  # still kept by the user

        # Deleting the kept model drops the last reference.
        harness.runtime.delete_retained_model(model["sha256"])
        assert not harness.runtime.store.has(model["sha256"])
        assert _runtime_program_bytes(harness.runtime) == 0
    finally:
        harness.close()


def test_unreviewed_backend_requires_confirmation_before_any_preparation(harness: Harness) -> None:
    harness.install("fixture.alpha", "1.0.0", lock_text([harness.wheels["shared"]]))
    described = harness.runtime.describe("fixture.alpha", "1.0.0")
    assert described["review_level"] == "unreviewed"
    assert described["requires_unreviewed_confirmation"] is True
    with pytest.raises(WorkshopBackendError) as error:
        harness.runtime.start_preparation("fixture.alpha", "1.0.0")
    assert error.value.code == "backend-authorization-required"
    with pytest.raises(WorkshopBackendError) as error:
        harness.runtime.authorize("fixture.alpha", "1.0.0", acknowledge_unreviewed=False)
    assert error.value.code == "unreviewed-confirmation-required"
    assert harness.runtime.environments.list() == ()


def _registry_for(module_id: str, packages: dict[str, Path], *, blocked: set[str] = frozenset()):  # noqa: ANN202
    from core.workshop.models import RegistryIndex

    repository = "https://github.com/acme/backend-module"
    versions = []
    for version, package in packages.items():
        is_blocked = version in blocked
        versions.append(
            {
                "version": version,
                "releaseTag": f"v{version}",
                "assetName": f"{module_id}-{version}.lumina-workshop",
                "downloadUrl": f"{repository}/releases/download/v{version}/{module_id}-{version}.lumina-workshop",
                "assetBytes": package.stat().st_size,
                "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                "manifestSha256": "e" * 64,
                "workshopApi": {"min": "1.1.0", "maxExclusive": "2.0.0"},
                "luminaVersion": {"min": "2.0.0"},
                "permissions": [],
                "state": "blocked" if is_blocked else "active",
                "revocation": (
                    {"reasonCode": "abuse", "severity": "high", "message": {"zh-CN": "阻止", "en-US": "Blocked"}}
                    if is_blocked
                    else None
                ),
            }
        )
    return RegistryIndex.model_validate(
        {
            "schemaVersion": 1,
            "generatedAt": "2026-11-04T00:00:00Z",
            "modules": [
                {
                    "moduleId": module_id,
                    "repository": repository,
                    "official": False,
                    "publisher": "Lumina Layer Studio",
                    "name": {"zh-CN": "后端测试模块", "en-US": "Backend fixture"},
                    "description": {"zh-CN": "用于验证通用后端运行时", "en-US": "Verifies the generic backend runtime"},
                    "versions": versions,
                }
            ],
        }
    )


def test_reviewed_update_reuses_consent_unless_capabilities_expand(harness: Harness) -> None:
    module_id = "fixture.reviewed"
    lock = lock_text([harness.wheels["shared"]])
    network = [{"name": "network", "reason": "Downloads public sample data."}]
    plans = {
        "1.0.0": backend_manifest(module_id, "1.0.0", capabilities=network),
        "1.1.0": backend_manifest(module_id, "1.1.0", capabilities=network),
        "1.2.0": backend_manifest(
            module_id,
            "1.2.0",
            capabilities=[*network, {"name": "external-files", "reason": "Reads a folder you choose."}],
        ),
    }
    packages = {
        version: write_backend_package(
            harness.packages / f"reviewed-{version}", module_id=module_id, version=version, lock=lock, manifest=manifest
        )
        for version, manifest in plans.items()
    }
    shas = {version: hashlib.sha256(path.read_bytes()).hexdigest() for version, path in packages.items()}
    harness.review = ReviewContext(
        registry=_registry_for(module_id, packages),
        attestations=frozenset((module_id, version, sha) for version, sha in shas.items()),
    )

    def install(version: str) -> None:
        harness.installer().install_candidate(
            packages[version],
            source="registry",
            source_repository="https://github.com/acme/backend-module",
            official=False,
        )

    install("1.0.0")
    first = harness.runtime.describe(module_id, "1.0.0")
    assert first["review_level"] == "reviewed"
    assert first["requires_unreviewed_confirmation"] is False
    harness.runtime.authorize(module_id, "1.0.0", acknowledge_unreviewed=False)
    harness.prepare(module_id, "1.0.0")

    install("1.1.0")
    assert harness.runtime.describe(module_id, "1.1.0")["authorization"] == "inherited"
    task = harness.runtime.start_preparation(module_id, "1.1.0")  # no new consent needed
    assert wait_terminal(harness.runtime, module_id, task.task_id, timeout=120).status == "succeeded"
    harness.installer().activate(module_id, "1.1.0")

    install("1.2.0")
    assert harness.runtime.describe(module_id, "1.2.0")["authorization"] == "required"

    # Review withdrawn for the active version: run again only after confirming risk.
    harness.review = ReviewContext(
        registry=harness.review.registry,
        attestations=frozenset({(module_id, "1.0.0", shas["1.0.0"])}),
    )
    withdrawn = harness.runtime.describe(module_id, "1.1.0")
    assert withdrawn["review_level"] == "unreviewed"
    assert withdrawn["requires_unreviewed_confirmation"] is True
    with pytest.raises(WorkshopBackendError) as error:
        harness.runtime.submit(module_id, "1.1.0", operation="echo", params={}, inputs=[], idempotency_key=None)
    assert error.value.code == "backend-authorization-required"
    harness.runtime.authorize(module_id, "1.1.0", acknowledge_unreviewed=True)
    assert harness.run(module_id, "1.1.0", "echo").status == "succeeded"

    # A Registry block refuses the next start; finished data stays.
    harness.review = ReviewContext(registry=_registry_for(module_id, packages, blocked={"1.1.0"}), attestations=None)
    with pytest.raises(WorkshopBackendError) as error:
        harness.runtime.submit(module_id, "1.1.0", operation="echo", params={}, inputs=[], idempotency_key=None)
    assert error.value.code == "module-version-blocked"


def test_queued_task_rechecks_review_and_registry_before_it_runs(harness: Harness) -> None:
    module_id = "fixture.revoked"
    package = write_backend_package(
        harness.packages / "revoked",
        module_id=module_id,
        version="1.0.0",
        lock=lock_text([harness.wheels["shared"]]),
        manifest=backend_manifest(module_id, "1.0.0"),
    )
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    registry = _registry_for(module_id, {"1.0.0": package})
    harness.review = ReviewContext(registry=registry, attestations=frozenset({(module_id, "1.0.0", sha)}))
    harness.installer().install_candidate(
        package, source="registry", source_repository="https://github.com/acme/backend-module", official=False
    )
    harness.prepare(module_id, "1.0.0")

    def queue_behind_running_task():  # noqa: ANN202
        running = harness.runtime.submit(
            module_id, "1.0.0", operation="slow", params={"steps": 400, "delay": 0.05}, inputs=[], idempotency_key=None
        )
        wait_until(lambda: harness.runtime.get_task(module_id, running.task_id).status == "running")
        queued = harness.runtime.submit(module_id, "1.0.0", operation="echo", params={}, inputs=[], idempotency_key=None)
        return running, queued

    # Review withdrawn while the task waits: it needs a new confirmation first.
    running, queued = queue_behind_running_task()
    harness.review = ReviewContext(registry=registry, attestations=frozenset())
    harness.runtime.cancel_task(module_id, running.task_id)
    refused = wait_terminal(harness.runtime, module_id, queued.task_id)
    assert refused.status == "failed" and refused.error is not None
    assert refused.error.code == "backend-authorization-required"
    assert refused.started_at is None and refused.outputs == ()

    # Registry block while the task waits: it never runs.
    harness.runtime.authorize(module_id, "1.0.0", acknowledge_unreviewed=True)
    running, queued = queue_behind_running_task()
    harness.review = ReviewContext(registry=_registry_for(module_id, {"1.0.0": package}, blocked={"1.0.0"}), attestations=None)
    harness.runtime.cancel_task(module_id, running.task_id)
    refused = wait_terminal(harness.runtime, module_id, queued.task_id)
    assert refused.status == "failed" and refused.error is not None
    assert refused.error.code == "module-version-blocked"
    assert refused.started_at is None and refused.outputs == ()


def test_version_needed_by_running_task_survives_pruning(harness: Harness) -> None:
    lock = lock_text([harness.wheels["shared"]])
    harness.install("fixture.alpha", "1.0.0", lock)
    harness.prepare("fixture.alpha", "1.0.0")
    running = harness.runtime.submit("fixture.alpha", "1.0.0", operation="slow", params={"steps": 2000}, inputs=[], idempotency_key=None)
    wait_until(lambda: harness.runtime.get_task("fixture.alpha", running.task_id).status == "running")
    # Two updates: rollback retention alone would now prune 1.0.0.
    for version in ("1.1.0", "1.2.0"):
        harness.install("fixture.alpha", version, lock)
        harness.prepare("fixture.alpha", version)
    state = harness.installer().get("fixture.alpha")
    assert state is not None and state.active_version == "1.2.0"
    assert "1.0.0" in state.versions  # kept for the running task
    assert harness.installer().version_path("fixture.alpha", "1.0.0").is_dir()
    harness.runtime.cancel_task("fixture.alpha", running.task_id)
    wait_terminal(harness.runtime, "fixture.alpha", running.task_id)
    retired = harness.installer().version_path("fixture.alpha", "1.0.0")
    # Pruning records the new state first and then deletes the files.
    wait_until(
        lambda: "1.0.0" not in harness.installer().get("fixture.alpha").versions and not retired.exists(),
        timeout=30,
    )


class _CleanupFinishesFirst(threading.Thread):
    """Run a runtime cleanup thread to completion before its starter continues.

    A legal schedule: the worker reporting a finished task may be preempted
    before it lets go of that task or starts the next one.
    """

    def start(self) -> None:
        super().start()
        self.join(timeout=120)


@pytest.mark.parametrize("next_task", [False, True], ids=["nothing-queued", "new-version-queued"])
def test_retired_version_is_released_whatever_runs_first(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    next_task: bool,
) -> None:
    lock = lock_text([harness.wheels["shared"]])
    harness.install("fixture.alpha", "1.0.0", lock)
    harness.prepare("fixture.alpha", "1.0.0")
    running = harness.runtime.submit("fixture.alpha", "1.0.0", operation="slow", params={"steps": 2000}, inputs=[], idempotency_key=None)
    wait_until(lambda: harness.runtime.get_task("fixture.alpha", running.task_id).status == "running")
    for version in ("1.1.0", "1.2.0"):
        harness.install("fixture.alpha", version, lock)
        harness.prepare("fixture.alpha", version)
    queued = (
        harness.runtime.submit("fixture.alpha", "1.2.0", operation="echo", params={}, inputs=[], idempotency_key=None)
        if next_task
        else None
    )
    # Only threads the runtime starts (its cleanups) change; workers do not.
    monkeypatch.setattr(runtime_module, "threading", SimpleNamespace(**{**vars(threading), "Thread": _CleanupFinishesFirst}))
    harness.runtime.cancel_task("fixture.alpha", running.task_id)
    wait_terminal(harness.runtime, "fixture.alpha", running.task_id)
    retired = harness.installer().version_path("fixture.alpha", "1.0.0")
    wait_until(
        lambda: "1.0.0" not in harness.installer().get("fixture.alpha").versions and not retired.exists(),
        timeout=30,
    )
    if queued is not None:
        assert wait_terminal(harness.runtime, "fixture.alpha", queued.task_id).status == "succeeded"
    # The retired version's process does not linger until the idle timeout.
    assert harness.runtime.describe("fixture.alpha", "1.2.0")["runtime"]["version"] != "1.0.0"


def test_startup_marks_interrupted_tasks_and_kills_leftover_backend(tmp_path: Path) -> None:
    first = Harness(tmp_path)
    first.install("fixture.alpha", "1.0.0", lock_text([first.wheels["shared"]]))
    first.prepare("fixture.alpha", "1.0.0")
    task = first.runtime.submit("fixture.alpha", "1.0.0", operation="slow", params={"steps": 5000}, inputs=[], idempotency_key=None)
    wait_until(lambda: first.runtime.get_task("fixture.alpha", task.task_id).status == "running")
    pid = first.runtime.describe("fixture.alpha", "1.0.0")["runtime"]["pid"]
    created = psutil.Process(pid).create_time()
    # Simulate an abrupt host exit: a new runtime starts without shutdown().
    second = Harness.__new__(Harness)
    second.tmp_path = tmp_path
    second.data_dir = first.data_dir
    second.packages = first.packages
    second.wheels = first.wheels
    second.fetcher = first.fetcher
    second.review = first.review
    second.runtime = second._make_runtime(60.0)
    second.runtime.startup()
    record = second.runtime.get_task("fixture.alpha", task.task_id)
    assert record.status == "interrupted"
    assert record.error is not None and record.error.code == "host-restarted"

    def gone() -> bool:
        try:
            return psutil.Process(pid).create_time() != created
        except psutil.NoSuchProcess:
            return True

    wait_until(gone)
    first.close()
    second.close()
