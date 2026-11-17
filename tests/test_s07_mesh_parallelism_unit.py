"""Unit coverage for bounded parallel mesh generation in pipeline stage S07."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
import logging
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from hypothesis import given, settings, strategies as st

from config import ModelingMode, PrinterConfig
from core.pipeline import s07_mesh_generation
from core.task_parallelism import AdaptiveParallelismPlan


class _DelayedBoxMesher:
    """Return deterministic boxes while completing higher IDs first."""

    def generate_mesh(
        self,
        _full_matrix: np.ndarray,
        mat_id: int,
        _target_h: int,
    ) -> trimesh.Trimesh:
        time.sleep(0.003 * (4 - mat_id))
        return trimesh.creation.box(extents=(float(mat_id + 1), 1.0, 1.0))


class _RecordingMesher:
    """Record worker identity and optionally fail one material."""

    def __init__(self, *, failing_material: int | None = None) -> None:
        self.failing_material = failing_material
        self.thread_ids: list[int] = []

    def generate_mesh(
        self,
        _full_matrix: np.ndarray,
        mat_id: int,
        _target_h: int,
    ) -> trimesh.Trimesh:
        self.thread_ids.append(threading.get_ident())
        if mat_id == self.failing_material:
            raise RuntimeError(f"material-{mat_id}-failed")
        return trimesh.creation.box(extents=(float(mat_id + 1), 1.0, 1.0))


def _parallelism_plan(
    workers: int,
    *,
    requested_ceiling: int | None = None,
    effective_cpu_capacity: int | None = None,
    outer_demand: int = 1,
    cpu_fair_share_ceiling: int | None = None,
    limiting_reason: str = "requested",
    demand_snapshot_fallback: bool = False,
    cpu_topology: str = "unknown",
    cpu_scheduling_policy: str = "injected_or_unknown",
    performance_cpu_capacity: int | None = None,
) -> AdaptiveParallelismPlan:
    """Build a coherent deterministic plan for stage-adoption tests."""

    requested = requested_ceiling or max(1, workers)
    effective_cpu = effective_cpu_capacity or max(1, workers * outer_demand)
    cpu_share = cpu_fair_share_ceiling or max(
        1,
        effective_cpu // max(1, outer_demand),
    )
    return AdaptiveParallelismPlan(
        workers=workers,
        requested_ceiling=requested,
        effective_cpu_capacity=effective_cpu,
        outer_demand=outer_demand,
        cpu_fair_share_ceiling=cpu_share,
        work_item_ceiling=4,
        work_unit_ceiling=4,
        stage_ceiling=4,
        limiting_reason=limiting_reason,
        demand_snapshot_fallback=demand_snapshot_fallback,
        cpu_topology=cpu_topology,
        cpu_scheduling_policy=cpu_scheduling_policy,
        performance_cpu_capacity=performance_cpu_capacity,
    )


def _make_context(material_count: int) -> dict:
    return {
        "full_matrix": np.zeros((1, 2, 2), dtype=np.int16),
        "slot_names": [f"Material {index}" for index in range(material_count)],
        "preview_colors": {
            index: (index * 20, 100, 200, 255)
            for index in range(material_count)
        },
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "target_h": 2,
        "pixel_scale": 1.0,
        "_bench_enabled": True,
    }


def test_s07_uses_bounded_policy_and_restores_material_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Thread completion order must not affect scene or material ordering."""

    policy_calls: list[dict[str, int | str | None]] = []
    pool_workers: list[int] = []

    def _resolve(
        workload: str,
        *,
        work_items: int,
        min_parallel_items: int,
        hard_max_workers: int | None,
        work_units: int,
        min_parallel_work_units: int,
    ) -> AdaptiveParallelismPlan:
        policy_calls.append(
            {
                "workload": workload,
                "work_items": work_items,
                "min_parallel_items": min_parallel_items,
                "hard_max_workers": hard_max_workers,
                "work_units": work_units,
                "min_parallel_work_units": min_parallel_work_units,
            },
        )
        return _parallelism_plan(
            2,
            requested_ceiling=4,
            effective_cpu_capacity=4,
            outer_demand=2,
            cpu_fair_share_ceiling=2,
            limiting_reason="cpu_fair_share",
            cpu_topology="heterogeneous",
            cpu_scheduling_policy="apple_performance_budget",
            performance_cpu_capacity=4,
        )

    def _pool(*, max_workers: int) -> RealThreadPoolExecutor:
        pool_workers.append(max_workers)
        return RealThreadPoolExecutor(max_workers=max_workers)

    monkeypatch.setattr(s07_mesh_generation, "get_mesher", lambda *args, **kwargs: _DelayedBoxMesher())
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        _resolve,
    )
    monkeypatch.setattr(s07_mesh_generation, "ThreadPoolExecutor", _pool)
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(4))

    assert policy_calls == [
        {
            "workload": "raster",
            "work_items": 4,
            "min_parallel_items": 2,
            "hard_max_workers": None,
            "work_units": 4,
            "min_parallel_work_units": 100_000,
        }
    ]
    assert pool_workers == [2]
    assert result["valid_slot_names"] == [
        "Material 0",
        "Material 1",
        "Material 2",
        "Material 3",
    ]
    assert list(result["scene"].geometry) == result["valid_slot_names"]
    assert result["_hifi_timings"]["mesh_parallelism_requested"] == "auto"
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 2
    assert (
        result["_hifi_timings"]["mesh_parallelism_limit"]
        == "cpu_fair_share"
    )
    assert result["_hifi_timings"]["mesh_parallelism_effective_cpu"] == 4
    assert result["_hifi_timings"]["mesh_parallelism_cpu_topology"] == (
        "heterogeneous"
    )
    assert result["_hifi_timings"][
        "mesh_parallelism_cpu_scheduling_policy"
    ] == "apple_performance_budget"
    assert result["_hifi_timings"]["mesh_parallelism_performance_cpu"] == 4
    assert result["_hifi_timings"]["mesh_parallelism_outer_demand"] == 2
    assert result["_hifi_timings"]["mesh_parallelism_cpu_fair_share"] == 2
    assert result["_hifi_timings"]["mesh_parallelism_demand_fallback"] is False


def test_s07_effective_one_executes_on_calling_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serial policy must not create an executor or move work off-thread."""

    mesher = _RecordingMesher()
    calling_thread = threading.get_ident()
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: mesher,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(
            1,
            limiting_reason="insufficient_work_units",
        ),
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("serial policy must not create a pool"),
    )
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "1")
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(3))

    assert mesher.thread_ids == [calling_thread, calling_thread, calling_thread]
    assert result["_hifi_timings"]["mesh_parallelism_requested"] == "1"
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 1


@pytest.mark.parametrize(
    ("worker_count", "material_count"),
    [(2, 4), (4, 4), (12, 12)],
)
def test_s07_uses_exact_effective_worker_limit(
    monkeypatch: pytest.MonkeyPatch,
    worker_count: int,
    material_count: int,
) -> None:
    """The executor limit must equal the bounded policy decision."""

    observed_workers: list[int] = []

    def _pool(*, max_workers: int) -> RealThreadPoolExecutor:
        observed_workers.append(max_workers)
        return RealThreadPoolExecutor(max_workers=max_workers)

    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: _RecordingMesher(),
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(
            worker_count,
            requested_ceiling=worker_count,
        ),
    )
    monkeypatch.setattr(s07_mesh_generation, "ThreadPoolExecutor", _pool)
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", str(worker_count))
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(material_count))

    assert observed_workers == [worker_count]
    assert result["_hifi_timings"]["mesh_parallelism_requested"] == str(
        worker_count
    )
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == worker_count


def test_s07_worker_exception_fails_closed_with_original_material_context(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed future must not shift names, colors, or later materials."""

    mesher = _RecordingMesher(failing_material=1)
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: mesher,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(2),
    )
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)
    caplog.set_level(logging.WARNING)
    target_logger = logging.getLogger(
        "lumina.core.pipeline.s07_mesh_generation"
    )
    monkeypatch.setattr(target_logger, "propagate", False)
    target_logger.addHandler(caplog.handler)
    try:
        with pytest.raises(ValueError, match="refusing partial model export"):
            s07_mesh_generation.run(_make_context(3))
    finally:
        target_logger.removeHandler(caplog.handler)

    failure_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "s07_material_mesh_failed"
    ]
    assert len(failure_records) == 1
    assert failure_records[0].material_id == 1
    assert failure_records[0].material == "Material 1"
    assert failure_records[0].error_message == "material-1-failed"


def test_s07_single_material_stays_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One material must remain on the caller even under a high request."""

    mesher = _RecordingMesher()
    calling_thread = threading.get_ident()
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: mesher,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("one material must not create a pool"),
    )
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "8")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(1))

    assert mesher.thread_ids == [calling_thread]
    assert result["_hifi_timings"]["mesh_parallelism_requested"] == "8"
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 1


def test_s07_tiny_two_material_workload_stays_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two 1x2 materials are not enough work to amortize a thread pool."""

    mesher = _RecordingMesher()
    calling_thread = threading.get_ident()
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: mesher,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("tiny workload must not create a pool"),
    )
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "8")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(2))

    assert mesher.thread_ids == [calling_thread, calling_thread]
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 1


def test_s07_legacy_disable_override_forces_serial_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy emergency switch remains a strict serial override."""

    monkeypatch.setattr(s07_mesh_generation, "get_mesher", lambda *args, **kwargs: _DelayedBoxMesher())
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(4),
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("serial override must not create a pool"),
    )
    monkeypatch.setenv("LUMINA_DISABLE_PARALLEL_MESH", "1")
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "4")

    result = s07_mesh_generation.run(_make_context(3))

    assert result["valid_slot_names"] == [
        "Material 0",
        "Material 1",
        "Material 2",
    ]
    assert result["_hifi_timings"]["mesh_parallelism_requested"] == "4"
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 1
    assert result["_hifi_timings"]["mesh_parallelism_limit"] == "legacy_disable"


def test_s07_serial_and_parallel_mesh_outputs_are_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduling must not change geometry, colors, names, or ordering."""

    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: _DelayedBoxMesher(),
    )
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(
            1,
            limiting_reason="requested",
        ),
    )
    serial_result = s07_mesh_generation.run(_make_context(4))

    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(
            4,
            requested_ceiling=4,
        ),
    )
    parallel_result = s07_mesh_generation.run(_make_context(4))

    def _scene_signature(result: dict) -> tuple:
        scene = result["scene"]
        return tuple(
            (
                name,
                scene.geometry[name].vertices.tobytes(),
                scene.geometry[name].faces.tobytes(),
                scene.geometry[name].visual.face_colors.tobytes(),
                scene.geometry[name].metadata["name"],
            )
            for name in result["valid_slot_names"]
        )

    assert serial_result["valid_slot_names"] == parallel_result["valid_slot_names"]
    assert _scene_signature(serial_result) == _scene_signature(parallel_result)


@pytest.mark.parametrize("available_bytes", [None, 0, 32 * 1024 * 1024])
def test_s07_memory_pressure_prevents_overlapping_material_working_sets(
    monkeypatch: pytest.MonkeyPatch,
    available_bytes: int | None,
) -> None:
    """Large volumes stay exact while memory pressure limits concurrency."""

    mesher = _RecordingMesher()
    context = _make_context(4)
    z, y, x = np.indices((4, 128, 128))
    context["full_matrix"] = ((x + y + z) % 4).astype(np.int16)
    context["target_h"] = 128
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: mesher,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(4),
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_effective_memory_capacity",
        lambda: SimpleNamespace(available_bytes=available_bytes),
        raising=False,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("material working sets must not overlap"),
    )
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(context)

    assert mesher.thread_ids == [threading.get_ident()] * 4
    assert result["valid_slot_names"] == context["slot_names"]
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 1
    assert result["_hifi_timings"]["mesh_parallelism_limit"] == "memory_budget"
    for index, name in enumerate(result["valid_slot_names"]):
        mesh = result["scene"].geometry[name]
        assert float(mesh.volume) == pytest.approx((index + 1) * PrinterConfig.LAYER_HEIGHT)
        np.testing.assert_array_equal(mesh.visual.face_colors[0], context["preview_colors"][index])


@pytest.mark.parametrize("sparse", [False, True])
def test_s07_smooth_large_volumes_keep_useful_material_parallelism(
    monkeypatch: pytest.MonkeyPatch,
    sparse: bool,
) -> None:
    """Array size alone must not serialize smooth or sparse surfaces."""

    context = _make_context(4)
    labels = np.full((4, 1024, 1024), -1, dtype=np.int16)
    for mat_id in range(4):
        if sparse:
            labels[:, 4:12, mat_id * 16 : mat_id * 16 + 8] = mat_id
        else:
            labels[:, :, mat_id * 256 : (mat_id + 1) * 256] = mat_id
    context["full_matrix"] = labels
    context["target_h"] = 1024
    pool_workers: list[int] = []

    def pool(*, max_workers: int) -> RealThreadPoolExecutor:
        pool_workers.append(max_workers)
        return RealThreadPoolExecutor(max_workers=max_workers)

    monkeypatch.setattr(s07_mesh_generation, "get_mesher", lambda *args, **kwargs: _RecordingMesher())
    monkeypatch.setattr(s07_mesh_generation, "resolve_task_parallelism_plan", lambda *args, **kwargs: _parallelism_plan(4))
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_effective_memory_capacity",
        lambda: SimpleNamespace(available_bytes=512 * 1024 * 1024),
    )
    monkeypatch.setattr(s07_mesh_generation, "ThreadPoolExecutor", pool)
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(context)

    assert pool_workers == [4]
    assert result["valid_slot_names"] == context["slot_names"]
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 4


@settings(max_examples=60, deadline=None)
@given(st.lists(st.integers(-1, 3), min_size=24, max_size=24))
def test_surface_budget_upper_bound_covers_all_material_face_runs(
    values: list[int],
) -> None:
    """The fast path must cover every orientation, material, and air border."""

    labels = np.asarray(values, dtype=np.int16).reshape((2, 3, 4))
    actual_runs = 0
    for material_id in range(4):
        selected = labels == material_id
        for normal_axis in range(3):
            run_axis = 1 if normal_axis == 2 else 2
            for direction in (-1, 1):
                neighbor = np.roll(selected, direction, axis=normal_axis)
                boundary = [slice(None)] * 3
                boundary[normal_axis] = 0 if direction == 1 else -1
                neighbor[tuple(boundary)] = False
                exposed = selected & ~neighbor
                preceding = np.roll(exposed, 1, axis=run_axis)
                boundary = [slice(None)] * 3
                boundary[run_axis] = 0
                preceding[tuple(boundary)] = False
                actual_runs += int(np.count_nonzero(exposed & ~preceding))

    assert s07_mesh_generation._mesh_surface_run_upper_bound(labels) >= actual_runs
