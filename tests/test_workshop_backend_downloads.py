import hashlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from packaging.tags import cpython_tags

from core.workshop.backend import downloads
from core.workshop.backend.downloads import (
    DownloadBatch, DownloadPreferences, DownloadProgress, ordered_sources, source_options, summarize_source_routes,
)
from core.workshop.backend.locks import BackendLock, LockedPackage, LockedWheel, WheelSourcePolicy, current_platform_key
from core.workshop.backend.preview import estimate_dependencies, estimate_download_total, needs_target_python_version
from core.workshop.backend.state import BackendStateStore, BackendVersionRecord
from core.workshop.backend.tasks import TaskProgress, TaskStore
from core.workshop.backend.tooling import BackendInterpreter, CancelToken, ManagedInterpreterProvider
from core.workshop.backend.wheel_files import WheelArchiveCache, select_locked_wheels, wheel_download_urls
from core.workshop.errors import WorkshopBackendError


def test_source_preference_preserves_candidate_order_and_original_option() -> None:
    primary = "https://huggingface.co/example/model.bin"
    first_mirror = "https://www.modelscope.cn/example/model.bin"
    second_mirror = "https://modelscope.ai/example/model.bin"
    mirrors = (first_mirror, second_mirror)

    assert ordered_sources(primary, mirrors, "auto") == (primary, *mirrors)
    assert ordered_sources(primary, mirrors, "modelscope.cn") == (*mirrors, primary)
    assert ordered_sources(primary, mirrors, "original") == (primary,)


def test_internationalized_source_can_be_selected() -> None:
    original = "https://example.com/model.bin"
    mirror = "https://例子.example/model.bin"
    source = source_options((mirror,))[0]
    selected = DownloadPreferences(models=source)
    assert selected.models == "xn--fsqu00a.example"
    assert ordered_sources(original, (mirror,), selected.models) == (mirror, original)


def test_source_routes_preserve_known_bytes_with_unknown_files() -> None:
    original = "https://files.pythonhosted.org/packages/demo.whl"
    mirror = "https://pypi.tuna.tsinghua.edu.cn/packages/demo.whl"
    pytorch = "https://download.pytorch.org/whl/torch.whl"
    assert summarize_source_routes([
        (original, (mirror, original), 4096),
        (original, (mirror, original), None),
        (pytorch, (pytorch,), 8192),
    ]) == [
        {
            "original": "files.pythonhosted.org",
            "sources": ["pypi.tuna.tsinghua.edu.cn", "files.pythonhosted.org"],
            "count": 2, "bytes": 4096, "unknown_size_count": 1,
        },
        {
            "original": "download.pytorch.org",
            "sources": ["download.pytorch.org"],
            "count": 1, "bytes": 8192, "unknown_size_count": 0,
        },
    ]


def test_managed_runtime_status_and_cancel_stay_available_during_install(tmp_path) -> None:
    started = threading.Event()
    release = threading.Event()
    installation = threading.Event()
    executable = tmp_path / "python"

    def install_python(*_args, **_kwargs) -> None:
        started.set()
        assert release.wait(10)
        installation.set()

    uv = SimpleNamespace(
        python_install_dir=tmp_path,
        find_python=lambda version: executable if version == "3.12" and installation.is_set() else None,
        install_python=install_python,
    )
    provider = ManagedInterpreterProvider(uv)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(provider.ensure, "3.12", CancelToken())
        try:
            assert started.wait(5)
            assert pool.submit(provider.installed).result(timeout=3) == ()
            token = CancelToken()
            other = pool.submit(provider.ensure, "3.12", token)
            token.cancel()
            with pytest.raises(WorkshopBackendError) as failure:
                other.result(timeout=3)
            assert failure.value.code == "cancelled"
        finally:
            release.set()
        assert first.result(timeout=5).executable == executable
    assert [item.executable for item in provider.installed()] == [executable]


def test_task_progress_preserves_unknown_download_totals(tmp_path) -> None:
    store = TaskStore(tmp_path)
    module = "fixture.progress"
    task, _ = store.create(module_id=module, module_version="1.0.0", kind="prepare", operation="prepare")
    store.update(module, task.task_id, progress=TaskProgress(completed=0, total=5, phase="python"))
    task_file = store.task_dir(module, task.task_id) / "task.json"
    assert json.loads(task_file.read_text(encoding="utf-8"))["progress"] == {
        "completed": 0, "total": 5, "phase": "python",
    }

    observation = DownloadProgress(
        file_name="runtime.tar.gz", source="downloads.example", file_index=1, file_count=1,
        file_received_bytes=42, file_total_bytes=None, received_bytes=42, total_bytes=None,
        bytes_per_second=None, eta_seconds=None,
    )
    store.update(module, task.task_id, progress=TaskProgress(
        completed=0, total=5, phase="python-download", download=observation, downloaded_bytes=42,
    ))
    assert store.require(module, task.task_id).progress.download == observation


def test_backend_state_writes_only_explicit_source_preferences(tmp_path: Path) -> None:
    path = tmp_path / "backend-state.json"
    store = BackendStateStore(path)
    record = BackendVersionRecord(
        module_id="fixture.sources", version="1.0.0", package_sha256="a" * 64,
        manifest_sha256="b" * 64, declaration_sha256="c" * 64,
        recorded_at="2026-11-26T00:00:00+00:00",
    )
    store.upsert_version(record)
    assert "download_preferences" not in json.loads(path.read_text(encoding="utf-8"))["versions"][0]

    preferences = {"models": "modelscope.cn"}
    store.update_version(record.module_id, record.version, download_preferences=preferences)
    persisted = store.get_version(record.module_id, record.version)
    assert persisted is not None and persisted.download_preferences == preferences


def _wheel(name: str, digest: str, size: int, build: str = "") -> LockedWheel:
    path = f"{name}-1.0{build}-py3-none-any.whl"
    return LockedWheel(path, f"https://example.com/{path}", digest * 64, size)


def test_automatic_wheel_sources_preserve_the_distinction_between_pypi_and_pytorch() -> None:
    name = "demo-1.0-py3-none-any.whl"
    suffix = f"packages/ab/cd/{name}"
    pypi = LockedWheel(name, f"https://files.pythonhosted.org/{suffix}", "a" * 64, 10)
    pytorch = LockedWheel(name, f"https://download.pytorch.org/whl/cpu/{name}", "b" * 64, 10)
    signed = LockedWheel(name, pypi.url + "?signature=example", "c" * 64, 10)
    tuna = f"https://pypi.tuna.tsinghua.edu.cn/{suffix}"
    policy = WheelSourcePolicy()

    assert wheel_download_urls(pypi, policy, {}, "auto") == (tuna, pypi.url)
    assert wheel_download_urls(pypi, policy, {}, "pypi.tuna.tsinghua.edu.cn") == (tuna, pypi.url)
    assert wheel_download_urls(pypi, policy, {}, "original") == (pypi.url,)
    assert wheel_download_urls(pytorch, policy, {}, "auto") == (pytorch.url,)
    assert wheel_download_urls(pytorch, policy, {}, "pypi.tuna.tsinghua.edu.cn") == (pytorch.url,)
    assert wheel_download_urls(signed, policy, {}, "auto") == (signed.url,)

    override = WheelSourcePolicy(mirror_prefix="https://regional.example/pypi")
    assert wheel_download_urls(pypi, override, {}, "auto") == (
        f"https://regional.example/pypi/{suffix}", pypi.url,
    )


@pytest.mark.parametrize("connection_failure", [True, False], ids=["unreachable", "wrong-hash"])
def test_wheel_cache_falls_back_to_pypi_and_keeps_verified_bytes(tmp_path, monkeypatch, connection_failure) -> None:
    payloads = [b"first verified wheel", b"second verified wheel"]
    wheels = [
        LockedWheel(name, f"https://files.pythonhosted.org/packages/ab/cd/{name}", hashlib.sha256(data).hexdigest(), len(data))
        for name, data in zip(("alpha-1.0-py3-none-any.whl", "beta-1.0-py3-none-any.whl"), payloads, strict=True)
    ]
    requests = []
    original_client = httpx.Client

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.host, Path(request.url.path).name))
        for index, wheel in enumerate(wheels):
            if request.url.path.endswith(wheel.file_name):
                if request.url.host == "pypi.tuna.tsinghua.edu.cn" and index == 0:
                    if connection_failure:
                        raise httpx.ConnectTimeout("mirror unreachable", request=request)
                    return httpx.Response(200, content=b"X" * len(payloads[index]))
                return httpx.Response(200, content=payloads[index])
        pytest.fail("unexpected wheel request")

    transport = httpx.MockTransport(serve)
    monkeypatch.setattr(downloads.httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    lock = BackendLock(tuple(
        LockedPackage(name, "1.0", None, (wheel,))
        for name, wheel in zip(("alpha", "beta"), wheels, strict=True)
    ), None, "test")
    python = BackendInterpreter("test", f"{sys.version_info.major}.{sys.version_info.minor}", Path(sys.executable), False)
    cache = WheelArchiveCache(tmp_path)
    samples = []
    cache.prepare(lock, python, WheelSourcePolicy(), {}, "auto", CancelToken(), samples.append)

    assert requests == [
        ("pypi.tuna.tsinghua.edu.cn", wheels[0].file_name),
        ("files.pythonhosted.org", wheels[0].file_name),
        ("files.pythonhosted.org" if connection_failure else "pypi.tuna.tsinghua.edu.cn", wheels[1].file_name),
    ]
    for wheel, expected in zip(wheels, payloads, strict=True):
        assert (tmp_path / wheel.sha256 / wheel.file_name).read_bytes() == expected
    assert samples[-1].received_bytes == sum(map(len, payloads))


def test_selection_uses_lock_markers_and_prefers_the_newest_equal_tag_build() -> None:
    older, newer = _wheel("demo", "a", 10, "-1"), _wheel("demo", "b", 20, "-2")
    main = LockedPackage("demo", "1.0", None, (older, newer))
    packages = (
        main,
        LockedPackage("extra", "1.0", "'docs' in extras", (_wheel("extra", "c", 30),)),
        LockedPackage("test", "1.0", "'test' in dependency_groups", (_wheel("test", "d", 40),)),
    )
    selected = select_locked_wheels(BackendLock(packages, None, ""), "3.12", "3.12.9")
    assert [(package.name, package.wheels[0]) for package in selected.packages] == [("demo", newer)]
    broken = LockedPackage("demo", "1.0", "invalid marker", (older,))
    with pytest.raises(WorkshopBackendError, match="Invalid marker"):
        select_locked_wheels(BackendLock((broken,), None, ""), "3.12", "3.12.9")


def test_total_counts_a_shared_wheel_once_and_omits_inactive_packages() -> None:
    shared = LockedPackage("shared", "1.0", None, (_wheel("shared", "a", 20),))
    inactive = LockedPackage("test", "1.0", "'test' in dependency_groups", (_wheel("test", "b", 30),))
    gpu = LockedPackage("gpu", "1.0", None, (_wheel("gpu", "c", 50),))
    cpu_lock = BackendLock((shared, inactive), None, "cpu")
    gpu_lock = BackendLock((shared, gpu), None, "gpu")
    estimates = [
        estimate_dependencies(
            lock, environment_key=lock.digest, environment_exists=False, package_users={},
            platform_key=current_platform_key(), python_version="3.12",
        )
        for lock in (cpu_lock, gpu_lock)
    ]
    assert [item.new_download_bytes for item in estimates] == [20, 70]
    assert estimate_download_total(estimates, (), set(), 0) == {"bytes": 70, "incomplete": False}


def test_patch_dependent_download_plan_is_marked_incomplete() -> None:
    item = LockedPackage("demo", "1.0", "python_full_version >= '3.12.15'", (_wheel("demo", "a", 500_000_000),))
    lock = BackendLock((item,), None, "patch")
    estimate = estimate_dependencies(
        lock, environment_key=lock.digest, environment_exists=False, package_users={},
        platform_key=current_platform_key(), python_version="3.12",
    )
    assert estimate_download_total([estimate], (), set(), 0) == {"bytes": 0, "incomplete": True}
    assert estimate.source_wheels == item.wheels
    known_target = estimate_dependencies(
        lock, environment_key=lock.digest, environment_exists=False, package_users={},
        platform_key=current_platform_key(), python_version="3.12", target_python_version="3.12.16",
    )
    assert estimate_download_total([known_target], (), set(), 0) == {"bytes": 500_000_000, "incomplete": False}
    assert known_target.source_wheels == item.wheels


def test_unknown_patch_preserves_native_build_ranking_and_known_platform_constraints() -> None:
    native_tag = next(cpython_tags((3, 12), abis=["cp312"]))
    native_name = f"demo-1.0-2-{native_tag}.whl"
    older_name = f"demo-1.0-1-{native_tag}.whl"
    native = LockedWheel(native_name, f"https://native.example/{native_name}", "a" * 64, 10)
    older = LockedWheel(older_name, f"https://older.example/{older_name}", "b" * 64, 100)
    universal = _wheel("demo", "c", 500)
    available = LockedPackage(
        "demo", "1.0", f"python_full_version >= '3.12.16' and sys_platform == '{sys.platform}'",
        (native, older, universal),
    )
    other_platform = "linux" if sys.platform != "linux" else "win32"
    foreign = LockedPackage(
        "foreign", "1.0",
        f"sys_platform == '{other_platform}' and (python_full_version >= '3.12.16' or os_name == 'a and b')",
        (_wheel("foreign", "d", 20),),
    )
    lock = BackendLock((available, foreign), ">=3.12.16,<3.13", "patch")
    estimate = estimate_dependencies(
        lock, environment_key=lock.digest, environment_exists=False, package_users={},
        platform_key=current_platform_key(), python_version="3.12",
    )
    assert estimate.source_wheels == (native,)
    assert estimate.uncertain_selection


def test_lock_python_requirement_triggers_target_version_probe() -> None:
    package = LockedPackage("demo", "1.0", None, (_wheel("demo", "a", 10),))
    assert needs_target_python_version(BackendLock((package,), ">=3.12.16,<3.13", "patch"))


def test_download_observes_cancellation_between_transport_chunks(tmp_path, monkeypatch) -> None:
    token = CancelToken()
    original_client = httpx.Client

    class SmallChunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b"first"
            token.cancel()
            yield b"second"
            pytest.fail("the downloader kept reading after cancellation")

    transport = httpx.MockTransport(lambda _request: httpx.Response(200, stream=SmallChunks()))
    monkeypatch.setattr(downloads.httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    path = tmp_path / "asset.bin"
    with pytest.raises(WorkshopBackendError) as failed:
        downloads.download_https("https://example.com/asset.bin", path, cancel=token, progress=lambda *_: None)
    assert failed.value.code == "cancelled"
    assert path.read_bytes() == b"first"


def test_progress_tracks_completed_batch_bytes_and_restarts_failed_attempts(monkeypatch) -> None:
    clock = iter((0.0, 1.0, 2.0, 2.1, 3.0, 4.0, 5.0))
    monkeypatch.setattr(downloads.time, "monotonic", lambda: next(clock))
    samples = []
    batch = DownloadBatch((10, None), samples.append)
    first = batch.attempt(0, "first.whl", "https://example.test/first.whl")
    first(10, 10)
    batch.finish(0, 10)

    second = batch.attempt(1, "second.whl", "https://mirror.test/second.whl")
    second(0, 40)
    second(10, 40)
    assert samples[-1].received_bytes == 20
    assert samples[-1].total_bytes == 50
    assert samples[-1].bytes_per_second > 0
    assert samples[-1].eta_seconds > 0

    retry = batch.attempt(1, "second.whl", "https://example.test/second.whl")
    assert samples[-1].received_bytes == 10
    assert samples[-1].total_bytes is None
    retry(20, 20)
    assert samples[-1].received_bytes == samples[-1].total_bytes == 30
    assert samples[-1].eta_seconds == 0


def test_progress_keeps_the_rate_across_files_at_the_same_source(monkeypatch) -> None:
    now = 0.0
    monkeypatch.setattr(downloads.time, "monotonic", lambda: now)
    samples: list[DownloadProgress] = []
    batch = DownloadBatch((100, 100, 100), samples.append)
    first = batch.attempt(0, "first.whl", "https://mirror.example/first.whl")
    now = 0.5
    first(100, 100)
    batch.finish(0, 100)

    now = 0.6
    batch.attempt(1, "second.whl", "https://mirror.example/second.whl")
    assert samples[-1].file_received_bytes == 0
    assert samples[-1].received_bytes == 100
    assert samples[-1].bytes_per_second == 200
    assert samples[-1].eta_seconds == 1

    batch.attempt(1, "second.whl", "https://another.example/second.whl")
    assert samples[-1].received_bytes == 100
    assert samples[-1].bytes_per_second is None
    assert samples[-1].eta_seconds is None
