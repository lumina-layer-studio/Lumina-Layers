"""Process isolation and async admission for material-workbench requests."""

from __future__ import annotations

import asyncio
import os
import threading
from functools import partial
from pathlib import Path

import anyio
import pytest

from api.routers import single_stage
from api.worker_pool import WorkerPoolManager
from api.app import create_app
from fastapi.testclient import TestClient
from core.material_dynamic_solver import DynamicMaterialCandidateError
from core.material_lut_synthesis import load_multiple_materials


def _combo() -> single_stage._MaterialComboRequest:
    return single_stage._MaterialComboRequest(
        dir_names=["white", "red"], materials=[], layer_mode="fixed",
        layer_count=5, min_layer_count=None, layer_height_mm=0.08,
        substrate="white", backing_index=None,
    )


async def _compute_pid() -> int:
    return await single_stage._run_material_compute(
        os.getpid, combo=_combo(), failed_event="material_test_failed",
        failed_detail="Material test failed", serialize_builds=True,
    )


@pytest.mark.asyncio
async def test_material_computation_runs_in_a_worker_process(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = WorkerPoolManager(max_workers=1)
    pool.start()
    monkeypatch.setattr(single_stage, "get_worker_pool", lambda: pool, raising=False)
    try:
        assert await _compute_pid() != os.getpid()
    finally:
        pool.shutdown(wait=True)


def _raise_candidate_error() -> None:
    raise DynamicMaterialCandidateError("internal detail", layer_count=6, phase="dynamic_catalog_cache_lock")


@pytest.mark.asyncio
async def test_worker_domain_error_keeps_its_safe_http_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    pool = WorkerPoolManager(max_workers=1)
    pool.start()
    monkeypatch.setattr(single_stage, "get_worker_pool", lambda: pool)
    try:
        with pytest.raises(HTTPException) as caught:
            await single_stage._run_material_compute(
                _raise_candidate_error, combo=_combo(), failed_event="material_test_failed",
                failed_detail="Material test failed", serialize_builds=True,
            )
        assert caught.value.status_code == 503
        assert caught.value.detail["stage"] == "dynamic_catalog_cache_lock"
        assert "internal detail" not in str(caught.value.detail)
    finally:
        pool.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_cancelled_request_keeps_its_slot_until_worker_completion(
    monkeypatch: pytest.MonkeyPatch, fail: bool,
) -> None:
    started, finish = asyncio.Event(), asyncio.Event()
    semaphore = threading.BoundedSemaphore(1)

    class ControlledPool:
        async def submit(self, _work, *_args):
            started.set()
            await finish.wait()
            if fail:
                raise RuntimeError("late worker failure")
            return os.getpid()

    monkeypatch.setattr(single_stage, "get_worker_pool", ControlledPool)
    monkeypatch.setattr(single_stage, "_RUNTIME_BUILD_GLOBAL_SEMAPHORE", semaphore)
    caller = asyncio.create_task(_compute_pid())
    await asyncio.wait_for(started.wait(), timeout=1)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert not semaphore.acquire(blocking=False), "disconnect must not admit another heavy job"
    finish.set()
    async with asyncio.timeout(1):
        while single_stage._MATERIAL_COMPUTE_TASKS:
            await asyncio.sleep(0)
    assert semaphore.acquire(blocking=False)
    semaphore.release()


@pytest.mark.parametrize("max_layer_count, expected_budget", [(6, 1_048_576), (30, 241_979)])
def test_material_api_round_trip_with_real_process_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, max_layer_count: int,
    expected_budget: int,
) -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "dynamic_material_materials"
    monkeypatch.setenv("LUMINA_RUNTIME_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(single_stage, "MATERIALS_DIR", str(fixture_root))
    monkeypatch.setattr(single_stage, "load_multiple_materials", partial(load_multiple_materials, materials_dir=str(fixture_root)))
    pool = WorkerPoolManager(max_workers=1)
    pool.start()
    monkeypatch.setattr(single_stage, "get_worker_pool", lambda: pool)
    client = TestClient(create_app())
    form = {
        "material_directory_names": '["white", "red"]', "layer_mode": "dynamic",
        "min_layer_count": "5", "max_layer_count": str(max_layer_count), "layer_height_mm": "0.08",
        "substrate": "white", "backing_material_directory_name": "white", "max_points": "128",
    }
    try:
        fixed_form = {**form, "layer_mode": "fixed", "layer_count": "5"}
        legacy = client.post("/api/extractor/material-solver-cache/build", data=fixed_form)
        assert legacy.status_code == 200, legacy.text
        manual_files = set(tmp_path.rglob("*.npz"))
        fixed_coverage = client.post("/api/extractor/material-gamut/coverage", data=fixed_form)
        assert fixed_coverage.status_code == 200, fixed_coverage.text
        assert fixed_coverage.json()["source"]["kind"] == "exhaustive_cache"
        coverage = client.post("/api/extractor/material-gamut/coverage", data=form)
        assert coverage.status_code == 200, coverage.text
        assert coverage.json()["source"]["kind"] == "dynamic_catalog"
        assert coverage.json()["source"]["candidate_budget"] == expected_budget
        warm = client.post("/api/extractor/material-gamut/coverage", data=form)
        assert warm.status_code == 200, warm.text
        cold_result, warm_result = coverage.json(), warm.json()
        assert cold_result["source"]["was_cached"] is False
        assert warm_result["source"]["was_cached"] is True
        for key in ("coverage", "layer_cap_coverage", "accuracy", "color_count", "lab_hull", "lab_points"):
            assert cold_result[key] == warm_result[key]
        contributions = client.post("/api/extractor/material-gamut/contributions", data=form)
        assert contributions.status_code == 200, contributions.text
        assert len(contributions.json()["items"]) == 2
        prepared = client.post("/api/extractor/material-dynamic-cache/prepare", data=form)
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["dynamic"]["is_ready"]
        assert prepared.json()["dynamic"]["candidate_budget"] == expected_budget
        shared_overview = client.post("/api/extractor/material-cache/overview", data=form)
        assert shared_overview.json()["dynamic"]["is_ready"], "conversion and overview must see the worker's prepared catalog"
        assert list(tmp_path.rglob("*.npz"))
        assert not (tmp_path / "_solver_cache" / "_solver_cache").exists()
        deleted = client.post("/api/extractor/material-dynamic-cache/delete", data=form)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted"]
        overview = client.post("/api/extractor/material-cache/overview", data=form)
        assert not overview.json()["dynamic"]["is_ready"]
        assert set(tmp_path.rglob("*.npz")) == manual_files
    finally:
        client.close()
        pool.shutdown(wait=True)


@pytest.mark.asyncio
async def test_queued_material_requests_do_not_borrow_shared_request_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    attempted = 0
    count_lock = threading.Lock()

    class BusyGate:
        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            nonlocal attempted
            with count_lock:
                attempted += 1
            if blocking:
                release.wait(5)
            return False

    monkeypatch.setattr(single_stage, "_RUNTIME_BUILD_GLOBAL_SEMAPHORE", BusyGate())
    tasks = [asyncio.create_task(_compute_pid()) for _ in range(40)]
    try:
        async with asyncio.timeout(4):
            while attempted < 40:
                await asyncio.sleep(0.01)
        assert anyio.to_thread.current_default_thread_limiter().borrowed_tokens == 0
        assert await asyncio.wait_for(anyio.to_thread.run_sync(os.getpid), timeout=1) == os.getpid()
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
