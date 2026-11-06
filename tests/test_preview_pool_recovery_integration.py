"""Exercise preview recovery across an actual worker process exit."""
from __future__ import annotations

import asyncio
from concurrent.futures.process import BrokenProcessPool
import os
from pathlib import Path
import time

import pytest

from api.routers.converter import preview
from api.worker_pool import WorkerPoolManager


def _preview_interrupted_once(source_path: str, crash_kind: str) -> dict:
    """Exit in the first worker; let its replacement read the same input."""
    source = Path(source_path)
    marker = source.with_suffix(".first-worker")
    try:
        with marker.open("x", encoding="utf-8") as first:
            first.write(str(os.getpid()))
    except FileExistsError:
        return {"source": source.read_bytes(), "pid": os.getpid()}
    if crash_kind == "sibling":
        time.sleep(20)
        raise TimeoutError("Sibling failed to interrupt the preview")
    os._exit(23)


def _crash_after_preview_starts(source_path: str) -> None:
    marker = Path(source_path).with_suffix(".first-worker")
    deadline = time.monotonic() + 20
    while not marker.exists():
        if time.monotonic() > deadline:
            raise TimeoutError("Preview worker did not start")
        time.sleep(0.01)
    os._exit(23)


@pytest.mark.parametrize("crash_kind", ["preview", "sibling"])
def test_preview_replays_in_a_rebuilt_process_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, crash_kind: str,
) -> None:
    source = tmp_path / "original.png"
    source.write_bytes(b"original preview input")
    monkeypatch.setattr(preview, "worker_generate_preview", _preview_interrupted_once)
    # Reproduce an established shared pool, as on the ticket's Linux runtime.
    monkeypatch.setenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", "20")
    pool = WorkerPoolManager(max_workers=2 if crash_kind == "sibling" else 1)
    pool.start()

    async def run_preview() -> tuple[dict, dict[str, float]]:
        await asyncio.gather(*(
            pool.submit(time.sleep, 0.05) for _ in range(pool.max_workers)
        ))
        sibling = (
            asyncio.create_task(pool.submit(_crash_after_preview_starts, str(source)))
            if crash_kind == "sibling" else None
        )
        try:
            return await asyncio.wait_for(
                preview._generate_preview_with_pool_recovery(
                    pool, str(source), crash_kind,
                ),
                timeout=30,
            )
        finally:
            if sibling is not None:
                errors = await asyncio.gather(sibling, return_exceptions=True)
                assert isinstance(errors[0], BrokenProcessPool)

    try:
        result, timing = asyncio.run(run_preview())
        assert result["source"] == source.read_bytes()
        assert result["pid"] != int(source.with_suffix(".first-worker").read_text())
        assert timing["worker_execution_s"] >= 0
        assert pool.outstanding_tasks == 0
    finally:
        pool.shutdown(wait=True)
