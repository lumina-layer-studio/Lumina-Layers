from core.workshop.backend import downloads
from core.workshop.backend.downloads import DownloadBatch, ordered_sources


def test_source_preference_preserves_candidate_order_and_original_option() -> None:
    primary = "https://huggingface.co/example/model.bin"
    first_mirror = "https://www.modelscope.cn/example/model.bin"
    second_mirror = "https://modelscope.ai/example/model.bin"
    mirrors = (first_mirror, second_mirror)

    assert ordered_sources(primary, mirrors, "auto") == (primary, *mirrors)
    assert ordered_sources(primary, mirrors, "modelscope.cn") == (*mirrors, primary)
    assert ordered_sources(primary, mirrors, "original") == (primary,)


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
