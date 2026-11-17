"""
S07 — Multi-material 3D mesh generation (parallel ThreadPoolExecutor).
S07 — 多材质 3D 网格生成（支持并行 ThreadPoolExecutor）。

从 converter.py 搬入的网格生成逻辑：
- get_mesher() 调用
- ThreadPoolExecutor 并行网格生成
- scene 构建与 transform 应用
"""

from api.structured_logging import get_logger
import os
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import trimesh
from shapely.geometry import Polygon

from config import PrinterConfig
from core.mesh_generators import get_mesher
from core.system_capacity import get_effective_memory_capacity
from core.task_parallelism import (
    resolve_task_parallelism_plan,
    task_parallelism_worker_scope,
)

_log = get_logger(__name__)
_MIN_PARALLEL_MESH_WORK_UNITS = 100_000
_MESH_GRID_WORKING_BYTES_PER_VOXEL = 10
# The 256px connected checkerboard needs <512 bytes per exposed face run for
# patch splitting, exact token coordinates, sorting, and sparse connectivity.
_MESH_WORKING_BYTES_PER_FACE_RUN = 512
_MESH_ESTIMATE_BLOCK_VOXELS = 65_536


def _mesh_surface_run_upper_bound(volume: np.ndarray) -> int:
    """Bound all materials' face runs from label transitions in two axes."""

    label_runs: list[int] = []
    for axis in (2, 1):
        first = [slice(None)] * 3
        second = [slice(None)] * 3
        first[axis] = slice(None, -1)
        second[axis] = slice(1, None)
        run_count = int(volume.size) // volume.shape[axis]
        for left, right in np.nditer(
            [volume[tuple(first)], volume[tuple(second)]],
            flags=["external_loop", "buffered", "zerosize_ok"],
            op_flags=["readonly"],
            buffersize=_MESH_ESTIMATE_BLOCK_VOXELS,
        ):
            run_count += int(np.count_nonzero(left != right))
        label_runs.append(run_count)
    # A pair of adjacent label runs creates at most two oriented face runs.
    # Each row meets at most two neighbors. Z/Y faces run along X; X along Y.
    return min(6 * int(volume.size), 8 * label_runs[0] + 4 * label_runs[1])


def _estimate_material_mesh_working_bytes(
    volume: np.ndarray,
    material_count: int,
) -> np.ndarray:
    """Estimate grid buffers plus surface complexity without building meshes.

    Count contiguous material runs on exposed face planes. Unlike face area,
    these stay small on smooth slabs whose pixel faces merge into rectangles.
    All temporary comparisons and histogram input casts fit one bounded block.
    """

    face_runs = np.zeros(material_count, dtype=np.int64)

    def add_runs(values: np.ndarray, selected: np.ndarray) -> None:
        labels = values[selected]
        labels = labels[(labels >= 0) & (labels < material_count)]
        if len(labels):
            face_runs[:] += np.bincount(
                labels.astype(np.intp, copy=False),
                minlength=material_count,
            )

    def count_face_runs(
        first: np.ndarray,
        second: np.ndarray,
        run_axis: int,
        *,
        both_sides: bool,
    ) -> None:
        first_column = [slice(None)] * 3
        first_column[run_axis] = slice(0, 1)
        operands = [first[tuple(first_column)], second[tuple(first_column)]]
        iterator_options = {
            "flags": ["external_loop", "buffered", "zerosize_ok"],
            "op_flags": ["readonly"],
            "buffersize": _MESH_ESTIMATE_BLOCK_VOXELS,
        }
        for left, right in np.nditer(operands, **iterator_options):
            exposed = left != right
            add_runs(left, exposed)
            if both_sides:
                add_runs(right, exposed)

        following = [slice(None)] * 3
        previous = [slice(None)] * 3
        following[run_axis] = slice(1, None)
        previous[run_axis] = slice(None, -1)
        operands = [
            first[tuple(following)], second[tuple(following)],
            first[tuple(previous)], second[tuple(previous)],
        ]
        for left, right, before_left, before_right in np.nditer(operands, **iterator_options):
            exposed = left != right
            previous_hidden = before_left == before_right
            add_runs(left, exposed & ((left != before_left) | previous_hidden))
            if both_sides:
                add_runs(right, exposed & ((right != before_right) | previous_hidden))

    for normal_axis in range(3):
        run_axis = 1 if normal_axis == 2 else 2
        first = [slice(None)] * 3
        second = [slice(None)] * 3
        first[normal_axis] = slice(None, -1)
        second[normal_axis] = slice(1, None)
        count_face_runs(volume[tuple(first)], volume[tuple(second)], run_axis, both_sides=True)
        for boundary in (slice(0, 1), slice(-1, None)):
            first[normal_axis] = boundary
            boundary_values = volume[tuple(first)]
            outside = np.broadcast_to(np.int8(-1), boundary_values.shape)
            count_face_runs(boundary_values, outside, run_axis, both_sides=False)

    # selected, int32 component labels, contact masks, and patch-extraction
    # masks share the full grid; absent materials only allocate selected.
    grid_bytes = int(volume.size) * np.where(
        face_runs > 0, _MESH_GRID_WORKING_BYTES_PER_VOXEL, 1,
    )
    return grid_bytes + face_runs * _MESH_WORKING_BYTES_PER_FACE_RUN


def _timed_generate_mesh(mesher, full_matrix, mat_id, target_h, z_edges: np.ndarray | None = None):
    """Wrapper that returns (mesh, elapsed_s) measured inside the worker thread."""
    with task_parallelism_worker_scope():
        _t = time.perf_counter()
        kwargs = {"z_edges": z_edges} if z_edges is not None else {}
        result = mesher.generate_mesh(full_matrix, mat_id, target_h, **kwargs)
        return result, time.perf_counter() - _t


def _load_boundary_geometry(boundary_path: str | None):
    """Load optional puzzle boundary geometry from a JSON payload.
    从 JSON 载荷加载可选的拼图边界几何。
    """
    if not boundary_path:
        return None

    with open(boundary_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    polygon_px = payload.get("polygon_px") or []
    holes_px = payload.get("holes_px") or []
    if len(polygon_px) < 3:
        raise ValueError("piece_boundary_geometry_path is missing a valid polygon_px ring.")

    geometry = Polygon(polygon_px, holes=holes_px)
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    if geometry.is_empty:
        raise ValueError("Loaded piece boundary geometry is empty after normalization.")
    return geometry


def run(ctx: dict) -> dict:
    """Generate multi-material 3D meshes with optional parallel execution.
    生成多材质 3D 网格，支持可选的并行执行。

    PipelineContext 输入键 / Input keys:
        - full_matrix (np.ndarray): (Z, H, W) signed material label planes.
        - voxel_z_edges (np.ndarray | None): Z+1 logical layer boundaries for
          representative planes; None means each plane spans one layer.
        - slot_names (list[str]): 材料槽位名称列表
        - preview_colors (dict): 材料预览颜色
        - modeling_mode (ModelingMode): 建模模式
        - target_h (int): 图像高度（像素）
        - pixel_scale (float): mm/px 缩放因子

    PipelineContext 输出键 / Output keys:
        - scene (trimesh.Scene): 包含所有材质网格的 3D 场景
        - valid_slot_names (list[str]): 成功生成网格的材料名称列表
        - transform (np.ndarray): 4x4 变换矩阵（像素→mm）
    """
    full_matrix = ctx["full_matrix"]
    slot_names = ctx["slot_names"]
    preview_colors = ctx["preview_colors"]
    modeling_mode = ctx["modeling_mode"]
    target_h = ctx["target_h"]
    pixel_scale = ctx["pixel_scale"]
    piece_boundary_geometry_path = ctx.get("piece_boundary_geometry_path")
    disable_material_dilation = bool(ctx.get("disable_material_dilation", True))
    boundary_geometry = _load_boundary_geometry(piece_boundary_geometry_path)

    _bench_enabled = ctx.get("_bench_enabled", True)
    _mesh_t0 = time.perf_counter() if _bench_enabled else None

    # Build transform matrix: pixel/voxel coords → mm
    scene = trimesh.Scene()

    transform = np.eye(4)
    transform[0, 0] = pixel_scale
    transform[1, 1] = pixel_scale
    transform[2, 2] = PrinterConfig.LAYER_HEIGHT

    _log.debug(
        "Transform: XY=%smm/px, Z=%smm/layer",
        pixel_scale,
        PrinterConfig.LAYER_HEIGHT,
        extra={
            "event": "s07_transform_resolved",
            "pixel_scale": float(pixel_scale),
            "layer_height_mm": float(PrinterConfig.LAYER_HEIGHT),
        },
    )

    mesher = get_mesher(
        modeling_mode,
        disable_material_dilation=disable_material_dilation,
        boundary_geometry=boundary_geometry,
    )
    _log.debug(
        "Using mesher: %s",
        mesher.__class__.__name__,
        extra={"event": "s07_mesher_resolved", "mesher": mesher.__class__.__name__},
    )

    valid_slot_names = []
    num_materials = len(slot_names)
    _log.debug(
        "Generating meshes for %s materials...",
        num_materials,
        extra={"event": "s07_mesh_generation_started", "count": num_materials},
    )

    raw_parallelism_request = os.getenv("LUMINA_RASTER_PARALLELISM")
    normalized_parallelism_request = (
        raw_parallelism_request.strip().lower()
        if raw_parallelism_request is not None
        else ""
    )
    parallelism_requested = normalized_parallelism_request or "auto"
    parallelism_plan = resolve_task_parallelism_plan(
        "raster",
        work_items=num_materials,
        min_parallel_items=2,
        hard_max_workers=None,
        work_units=int(np.asarray(full_matrix).size),
        min_parallel_work_units=_MIN_PARALLEL_MESH_WORK_UNITS,
    )
    max_workers = parallelism_plan.workers
    legacy_parallelism_disabled = (
        os.getenv("LUMINA_DISABLE_PARALLEL_MESH", "0") == "1"
    )
    if legacy_parallelism_disabled:
        max_workers = 1
    parallelism_limit = (
        "legacy_disable"
        if legacy_parallelism_disabled
        else parallelism_plan.limiting_reason
    )
    if max_workers > 1:
        available_bytes = get_effective_memory_capacity().available_bytes
        memory_workers = 1
        if available_bytes is not None:
            memory_budget = max(0, int(available_bytes)) // 2
            volume = np.asarray(full_matrix)
            grid_working_bytes = (
                int(volume.size) * _MESH_GRID_WORKING_BYTES_PER_VOXEL * max_workers
            )
            # Skip the statistics pass when even six exposed runs per voxel
            # across all materials fit alongside concurrent grid buffers.
            maximum_surface_bytes = (
                int(volume.size) * 6 * _MESH_WORKING_BYTES_PER_FACE_RUN
            )
            if grid_working_bytes + maximum_surface_bytes <= memory_budget:
                memory_workers = max_workers
            elif memory_budget >= 2 * int(volume.size):
                surface_bytes = (
                    _mesh_surface_run_upper_bound(volume) * _MESH_WORKING_BYTES_PER_FACE_RUN
                )
                if grid_working_bytes + surface_bytes <= memory_budget:
                    memory_workers = max_workers
                else:
                    working_bytes = _estimate_material_mesh_working_bytes(volume, num_materials)
                    concurrent_bytes = np.cumsum(np.sort(working_bytes)[::-1])
                    memory_workers = max(1, int(np.count_nonzero(concurrent_bytes <= memory_budget)))
        if memory_workers < max_workers:
            max_workers = memory_workers
            parallelism_limit = "memory_budget"
    parallel_enabled = max_workers > 1
    mesh_results = {}
    mesh_errors = {}
    mat_timings = {}
    mesh_compute_elapsed = 0.0
    mesh_apply_elapsed = 0.0
    if parallel_enabled:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(
                    _timed_generate_mesh,
                    mesher,
                    full_matrix,
                    mat_id,
                    target_h,
                    ctx.get("voxel_z_edges"),
                ): mat_id
                for mat_id in range(num_materials)
            }
            for future in as_completed(future_map):
                mat_id = future_map[future]
                try:
                    mesh_results[mat_id], mat_timings[mat_id] = future.result()
                    mesh_compute_elapsed += mat_timings[mat_id]
                except (ValueError, TypeError, RuntimeError, OSError) as e:
                    mesh_errors[mat_id] = e
    else:
        for mat_id in range(num_materials):
            try:
                mesh_results[mat_id], mat_timings[mat_id] = _timed_generate_mesh(
                    mesher,
                    full_matrix,
                    mat_id,
                    target_h,
                    ctx.get("voxel_z_edges"),
                )
                mesh_compute_elapsed += mat_timings[mat_id]
            except (ValueError, TypeError, RuntimeError, OSError) as e:
                mesh_errors[mat_id] = e

    if mesh_errors:
        for mat_id in sorted(mesh_errors):
            error = mesh_errors[mat_id]
            _log.warning(
                "Error generating mesh for material %s (%s): %s",
                mat_id,
                slot_names[mat_id],
                error,
                extra={
                    "event": "s07_material_mesh_failed",
                    "material_id": int(mat_id),
                    "material": slot_names[mat_id],
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                },
            )
        raise ValueError(
            "Material mesh generation failed; refusing partial model export"
        ) from mesh_errors[min(mesh_errors)]

    log_detail = num_materials <= 8
    preview_color_cache = {idx: preview_colors[idx] for idx in range(num_materials)}
    for mat_id in range(num_materials):
        mesh = mesh_results.get(mat_id)
        if mesh:
            _apply_t0 = time.perf_counter()
            mesh.apply_transform(transform)
            mesh.visual.face_colors = preview_color_cache[mat_id]
            name = slot_names[mat_id]
            mesh.metadata["name"] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)
            mesh_apply_elapsed += time.perf_counter() - _apply_t0
            valid_slot_names.append(name)
            _mt = mat_timings.get(mat_id, 0.0)
            if log_detail:
                _log.debug(
                    "%s: %sv %sf  %.3fs",
                    name,
                    len(mesh.vertices),
                    len(mesh.faces),
                    _mt,
                    extra={
                        "event": "s07_material_mesh_generated",
                        "material_id": int(mat_id),
                        "material": name,
                        "vertex_count": int(len(mesh.vertices)),
                        "face_count": int(len(mesh.faces)),
                        "duration_ms": round(_mt * 1000, 3),
                    },
                )

    if _bench_enabled and _mesh_t0 is not None:
        _mesh_elapsed = time.perf_counter() - _mesh_t0
        _hifi_timings = ctx.setdefault("_hifi_timings", {})
        _hifi_timings["mesh_gen_s"] = _mesh_elapsed
        _hifi_timings["mesh_compute_s"] = mesh_compute_elapsed
        _hifi_timings["mesh_apply_transform_s"] = mesh_apply_elapsed
        _hifi_timings["mesh_parallelism_requested"] = parallelism_requested
        _hifi_timings["mesh_parallelism_workers"] = int(max_workers)
        _hifi_timings["mesh_parallelism_limit"] = parallelism_limit
        _hifi_timings["mesh_parallelism_effective_cpu"] = int(
            parallelism_plan.effective_cpu_capacity,
        )
        _hifi_timings["mesh_parallelism_cpu_topology"] = str(
            parallelism_plan.cpu_topology,
        )[:64]
        _hifi_timings["mesh_parallelism_cpu_scheduling_policy"] = str(
            parallelism_plan.cpu_scheduling_policy,
        )[:64]
        if parallelism_plan.performance_cpu_capacity is not None:
            _hifi_timings["mesh_parallelism_performance_cpu"] = int(
                parallelism_plan.performance_cpu_capacity,
            )
        _hifi_timings["mesh_parallelism_outer_demand"] = int(
            parallelism_plan.outer_demand,
        )
        _hifi_timings["mesh_parallelism_cpu_fair_share"] = int(
            parallelism_plan.cpu_fair_share_ceiling,
        )
        _hifi_timings["mesh_parallelism_demand_fallback"] = bool(
            parallelism_plan.demand_snapshot_fallback,
        )
        _log.debug(
            "mesh_gen done: %.3fs",
            _mesh_elapsed,
            extra={
                "event": "s07_mesh_gen_done",
                "duration_ms": round(_mesh_elapsed * 1000, 3),
                "count": len(valid_slot_names),
                "material_count": num_materials,
                "error_count": len(mesh_errors),
                "parallel_enabled": bool(parallel_enabled),
                "parallelism_requested": parallelism_requested,
                "worker_count": int(max_workers),
                "parallelism_limit": parallelism_limit,
                "effective_cpu_capacity": int(
                    parallelism_plan.effective_cpu_capacity,
                ),
                "cpu_topology": str(parallelism_plan.cpu_topology)[:64],
                "cpu_scheduling_policy": str(
                    parallelism_plan.cpu_scheduling_policy,
                )[:64],
                "performance_cpu_capacity": (
                    int(parallelism_plan.performance_cpu_capacity)
                    if parallelism_plan.performance_cpu_capacity is not None
                    else None
                ),
                "outer_demand": int(parallelism_plan.outer_demand),
                "cpu_fair_share_ceiling": int(
                    parallelism_plan.cpu_fair_share_ceiling,
                ),
                "demand_snapshot_fallback": bool(
                    parallelism_plan.demand_snapshot_fallback,
                ),
            },
        )

    ctx["scene"] = scene
    ctx["valid_slot_names"] = valid_slot_names
    ctx["transform"] = transform
    ctx["mesher"] = mesher
    ctx["boundary_geometry"] = boundary_geometry
    ctx["disable_material_dilation"] = disable_material_dilation

    return ctx
