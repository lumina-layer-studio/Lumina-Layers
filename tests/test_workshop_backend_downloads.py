import httpx
import pytest

from core.workshop.backend import downloads
from core.workshop.backend.downloads import DownloadBatch, DownloadPreferences, ordered_sources, source_options
from core.workshop.backend.locks import BackendLock, LockedPackage, LockedWheel, current_platform_key
from core.workshop.backend.preview import estimate_dependencies, estimate_download_total
from core.workshop.backend.tooling import CancelToken
from core.workshop.backend.wheel_files import select_locked_wheels
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


def _wheel(name: str, digest: str, size: int, build: str = "") -> LockedWheel:
    path = f"{name}-1.0{build}-py3-none-any.whl"
    return LockedWheel(path, f"https://example.com/{path}", digest * 64, size)


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
