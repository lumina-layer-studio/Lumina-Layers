"""Real process exits must affect only the task running in that process."""
from __future__ import annotations

import asyncio
from concurrent.futures.process import BrokenProcessPool
import gc
import io
import json
import logging
import os
from pathlib import Path
import time
import weakref

import pytest

from api.worker_pool import WorkerPoolManager


class _PreviewPayload:
    def __init__(self) -> None:
        self.pixels = bytearray(1024 * 1024)


def _preview_payload() -> _PreviewPayload:
    return _PreviewPayload()


def test_idle_dispatcher_does_not_retain_the_last_preview() -> None:
    pool = WorkerPoolManager(max_workers=1)
    pool.start()

    async def run() -> None:
        result = await pool.submit(_preview_payload)
        reference = weakref.ref(result)
        del result
        for _ in range(10):
            await asyncio.sleep(0.01)
            gc.collect()
            if reference() is None:
                break
        assert reference() is None

    try:
        asyncio.run(run())
    finally:
        pool.shutdown(wait=True)


def _blocked_read(source_path: str, marker: str, *, crash: bool = False) -> tuple[bytes, int]:
    started = Path(marker + ".started")
    # Exclusive creation also detects an unwanted replay of the same job.
    with started.open("x", encoding="utf-8") as output:
        output.write(str(os.getpid()))
    deadline = time.monotonic() + 20
    while not Path(marker + ".release").exists():
        if time.monotonic() > deadline:
            raise TimeoutError("Parent did not release the test worker")
        time.sleep(0.01)
    if crash:
        os._exit(23)
    return Path(source_path).read_bytes(), os.getpid()


def _blocked_crash(source_path: str, marker: str) -> None:
    _blocked_read(source_path, marker, crash=True)


async def _started(marker: Path) -> int:
    async with asyncio.timeout(20):
        while True:
            try:
                return int(Path(str(marker) + ".started").read_text())
            except (FileNotFoundError, ValueError):
                pass
            await asyncio.sleep(0.01)


def _release(marker: Path) -> None:
    Path(str(marker) + ".release").touch()


@pytest.mark.parametrize("recycle_after", ["1", "20"])
def test_crash_preserves_running_and_queued_jobs_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recycle_after: str,
) -> None:
    monkeypatch.setenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", recycle_after)
    source = tmp_path / "original.png"
    source.write_bytes(b"original preview input")
    healthy, failing, queued = (tmp_path / name for name in ("preview", "generate", "queued"))
    pool = WorkerPoolManager(max_workers=2)
    pool.start()

    async def run() -> None:
        preview = asyncio.create_task(pool.submit_timed(_blocked_read, str(source), str(healthy)))
        generate = asyncio.create_task(pool.submit(_blocked_crash, str(source), str(failing)))
        later: asyncio.Task | None = None
        try:
            original_pid = await _started(healthy)
            await _started(failing)
            later = asyncio.create_task(pool.submit(_blocked_read, str(source), str(queued)))
            await asyncio.sleep(0.05)
            assert not Path(str(queued) + ".started").exists()
            _release(failing)
            with pytest.raises(BrokenProcessPool):
                await asyncio.wait_for(generate, 20)
            _release(healthy)
            _release(queued)
            (content, pid), timing = await asyncio.wait_for(preview, 20)
            assert (content, pid) == (source.read_bytes(), original_pid)
            assert timing["worker_execution_s"] >= 0
            assert (await asyncio.wait_for(later, 20))[0] == source.read_bytes()
            assert pool.outstanding_tasks == 0
        finally:
            for marker in (healthy, failing, queued):
                _release(marker)
            await asyncio.gather(preview, generate, *([later] if later else []), return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        pool.shutdown(wait=True)


def test_crash_log_identifies_the_original_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api import worker_pool
    from api.structured_logging import (
        _JsonFormatter, reset_request_id, reset_session_id, set_request_id, set_session_id,
    )
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(_JsonFormatter())
    logger = logging.Logger("test.worker_failure")
    logger.addHandler(handler)
    monkeypatch.setattr(worker_pool, "_log", logger)
    pool = WorkerPoolManager(max_workers=1)
    pool.start()
    failing = tmp_path / "crash"
    _release(failing)
    request_token = set_request_id("preview-request")
    session_token = set_session_id("preview-session")
    try:
        with pytest.raises(BrokenProcessPool):
            asyncio.run(pool.submit(_blocked_crash, "unused", str(failing)))
        payload = json.loads(output.getvalue())
        assert payload["request_id"] == "preview-request"
        assert payload["session_id"] == "preview-session"
        assert payload["worker_name"] == "_blocked_crash"
        assert payload["surviving_workers"] == 0
    finally:
        reset_request_id(request_token)
        reset_session_id(session_token)
        pool.shutdown(wait=True)


def test_cancelled_caller_does_not_prevent_crash_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", "20")
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    failing, later = tmp_path / "failing", tmp_path / "later"
    pool = WorkerPoolManager(max_workers=1)
    pool.start()

    async def run() -> None:
        failed = asyncio.create_task(pool.submit(_blocked_crash, str(source), str(failing)))
        await _started(failing)
        failed.cancel()
        with pytest.raises(asyncio.CancelledError):
            await failed
        assert pool.outstanding_tasks == 1
        _release(failing)
        _release(later)
        result = await asyncio.wait_for(pool.submit(_blocked_read, str(source), str(later)), 20)
        assert result[0] == source.read_bytes()
        assert pool.outstanding_tasks == 0

    try:
        asyncio.run(run())
    finally:
        _release(failing)
        pool.shutdown(wait=True)


def test_cancelled_queued_job_never_runs(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    running, queued = tmp_path / "running", tmp_path / "queued"
    pool = WorkerPoolManager(max_workers=1)
    pool.start()

    async def run() -> None:
        first = asyncio.create_task(pool.submit(_blocked_read, str(source), str(running)))
        try:
            await _started(running)
            waiting = asyncio.create_task(pool.submit(_blocked_read, str(source), str(queued)))
            await asyncio.sleep(0)
            assert pool.outstanding_tasks == 2
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert pool.outstanding_tasks == 1
            _release(running)
            assert (await first)[0] == source.read_bytes()
            assert not Path(str(queued) + ".started").exists()
            assert pool.outstanding_tasks == 0
        finally:
            _release(running)
            _release(queued)
            await asyncio.gather(first, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        pool.shutdown(wait=True)


def test_shutdown_cancels_queue_without_moving_jobs_into_restarted_service(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    running, queued, fresh = (tmp_path / name for name in ("running", "queued", "fresh"))
    pool = WorkerPoolManager(max_workers=1)
    pool.start()
    old_snapshot = pool.demand_snapshot_path

    async def run() -> None:
        first = asyncio.create_task(pool.submit(_blocked_read, str(source), str(running)))
        waiting: asyncio.Task | None = None
        try:
            await _started(running)
            waiting = asyncio.create_task(pool.submit(_blocked_read, str(source), str(queued)))
            await asyncio.sleep(0)
            pool.shutdown(wait=False)
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert old_snapshot.is_file()  # Running child still uses this generation.
            pool.start()
            new_snapshot = pool.demand_snapshot_path
            assert new_snapshot != old_snapshot
            _release(fresh)
            assert (await pool.submit(_blocked_read, str(source), str(fresh)))[0] == b"source"
            assert not Path(str(queued) + ".started").exists()
            _release(running)
            assert (await first)[0] == b"source"
            assert not old_snapshot.exists()
            assert new_snapshot.is_file()
            assert pool.outstanding_tasks == 0
        finally:
            for marker in (running, queued, fresh):
                _release(marker)
            await asyncio.gather(first, *([waiting] if waiting else []), return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        pool.shutdown(wait=True)


def test_graceful_shutdown_drains_accepted_queue(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    markers = [tmp_path / f"job-{i}" for i in range(4)]
    pool = WorkerPoolManager(max_workers=1)
    pool.start()
    snapshot = pool.demand_snapshot_path

    async def run() -> None:
        jobs = [asyncio.create_task(pool.submit(_blocked_read, str(source), str(marker))) for marker in markers]
        try:
            await _started(markers[0])
            assert pool.outstanding_tasks == 4
            for marker in markers:
                _release(marker)
            # Shutdown is synchronous, so queued scheduling must not require
            # this event loop to advance in order to drain accepted work.
            pool.shutdown(wait=True)
            assert all(result[0] == b"source" for result in await asyncio.gather(*jobs))
            assert pool.outstanding_tasks == 0
            assert not snapshot.exists()
        finally:
            for marker in markers:
                _release(marker)
            await asyncio.gather(*jobs, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        pool.shutdown(wait=True)
