"""Hot-path data provider for local material-archive + solver-cache access.
本地耗材档案与求解缓存访问的热路径数据提供者。

The staged pipeline calls this module instead of importing
``core.material_lut_synthesis`` / ``core.material_cache`` directly. It keeps
the useful local optimization from the split experiment: a process-local memo
cache keyed by request parameters and material archive contents, so repeated
loads within a preview/generate run hit memory while edits on disk invalidate
the memo automatically.

分阶段管线通过本模块访问耗材与求解缓存，而不是直接 import
``core.material_lut_synthesis`` / ``core.material_cache``。这里保留拆分实验中
有价值的本地优化：按请求参数和耗材档案内容 建键的进程内 memo 缓存，使一次
预览/生成内的重复加载命中内存，同时磁盘编辑会自动使 memo 失效。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from api.structured_logging import get_logger
from config import MATERIALS_DIR
from core import material_cache as _material_cache
from core import material_lut_synthesis as _material_lut_synthesis
from core.material_cache import DEFAULT_GRID_RESOLUTION
from core.material_candidate_cache import (
    MaterialCandidateCacheConfig,
    DEFAULT_PERSISTED_CANDIDATE_BUDGET,
    LEGACY_PERSISTED_CANDIDATE_BUDGET,
    MAX_PERSISTED_CANDIDATE_BUDGET,
    PREVIEW_SAFE_CANDIDATE_BUDGET,
    QUALITY_8M_CANDIDATE_BUDGET,
    build_material_candidate_runtime,
    load_material_candidate_runtime,
    save_material_candidate_runtime,
)
from core.material_color_solver import MaterialParams

_log = get_logger(__name__)

# Per-layer runtimes saved by dynamic Prepare live in this subfolder of the
# solver cache. Fixed-layer lookups only scan the top-level folder, so saving
# them here can never change fixed-layer color matching.
# 动态预构建保存的逐层运行时放在求解缓存的该子目录中；固定层数查找只扫描顶层目录，
# 因此保存它们绝不会改变固定层数的颜色匹配。
DYNAMIC_LAYER_RUNTIME_SUBDIRECTORY = "dynamic-layer-runtimes"

# Saved smart-cache budgets probed by fixed-layer lookups, largest first.
# 固定层数查找时探测的已保存智能缓存预算，按从大到小顺序。
PERSISTED_RUNTIME_PROBE_BUDGETS: tuple[int, ...] = (
    MAX_PERSISTED_CANDIDATE_BUDGET,
    DEFAULT_PERSISTED_CANDIDATE_BUDGET,
    QUALITY_8M_CANDIDATE_BUDGET,
    LEGACY_PERSISTED_CANDIDATE_BUDGET,
    PREVIEW_SAFE_CANDIDATE_BUDGET,
)

if TYPE_CHECKING:
    from core.material_cache import MaterialSolverCache
    from core.material_candidate_cache import MaterialCandidateRuntime

# ---------------------------------------------------------------------------
# Process-local memo caches
# 进程内 memo 缓存
# ---------------------------------------------------------------------------

_materials_lock = threading.Lock()
_materials_memo: dict[tuple, list[MaterialParams]] = {}


def _material_archive_state(
    directory_names: list[str],
    materials_dir: str | None,
) -> tuple:
    """Read the small archive inputs so same-path replacements invalidate reuse.
    读取小型档案输入，确保同路径覆盖也会使复用失效。
    """
    root = Path(materials_dir or MATERIALS_DIR)
    states = []
    for directory_name in directory_names:
        material_dir = root / directory_name
        for filename in ("material.json", "stage_A_parameters.json"):
            try:
                path = material_dir / filename
                states.append((path.stat().st_mtime_ns, path.read_bytes()))
            except OSError:
                states.append(None)
    return tuple(states)


def _materials_key(
    directory_names: list[str],
    materials_dir: str | None,
) -> tuple:
    """Build the memo key for a material-load request.
    为一次耗材加载请求构建 memo 键，直接比较档案内容。
    """
    return (
        str(materials_dir or ""),
        tuple(directory_names),
        _material_archive_state(directory_names, materials_dir),
    )


def load_materials(
    directory_names: list[str],
    *,
    materials_dir: str | None = None,
    use_cache: bool = True,
) -> list[MaterialParams]:
    """Load material archives for the hot path (memoized).
    为热路径加载耗材档案（带 memo 缓存）。

    Mirrors :func:`core.material_lut_synthesis.load_multiple_materials` exactly,
    adding a process-local memo so repeated loads of the same palette within a
    request hit memory. The returned list and its :class:`MaterialParams` are
    treated as immutable by the pipeline; callers must not mutate them.

    精确镜像 ``load_multiple_materials``，叠加进程内 memo；返回的列表与
    ``MaterialParams`` 在管线中按不可变对待，调用方不得修改。

    Args:
        directory_names: Material directory names in user-selected order.
            (按用户选择顺序的耗材目录名)
        materials_dir: Optional materials root override. (可选耗材根目录覆盖)
        use_cache: Set ``False`` to bypass and refresh the memo. (是否使用缓存)

    Returns:
        list[MaterialParams]: Loaded material parameters in order. (按序的耗材参数)
    """
    key = _materials_key(directory_names, materials_dir)
    if use_cache:
        with _materials_lock:
            cached = _materials_memo.get(key)
        if cached is not None:
            return cached

    loaded = _material_lut_synthesis.load_multiple_materials(
        directory_names, materials_dir=materials_dir
    )

    with _materials_lock:
        _materials_memo[key] = loaded
    return loaded


def load_solver_cache(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    cache_root: str | Path | None = None,
) -> tuple["MaterialSolverCache | None", int | None]:
    """Load the persisted solver cache for the hot path.
    为热路径加载持久化求解缓存。

    Thin pass-through to
    :func:`core.material_cache.load_material_solver_cache_with_fallback`. It is
    intentionally NOT memoized: solver caches are large NumPy-backed objects
    and the fallback loader already does its own efficient disk resolution, so
    memoizing here would only add memory pressure without a latency win on the
    typical single-lookup-per-request path.

    透传到 ``load_material_solver_cache_with_fallback``。有意不做 memo：求解
    缓存是大型 NumPy 对象，回退加载器自身已高效解析磁盘，且典型路径每请求只查
    一次，memo 只会增加内存压力而无延迟收益。

    Args:
        materials: Palette to match. (调色板)
        layer_count: Number of layers per pixel. (每像素层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        grid_resolution: Preferred Lab grid resolution to try first. (优先网格分辨率)
        cache_root: Optional cache directory override. (可选缓存根目录覆盖)

    Returns:
        ``(cache, actual_grid)`` — see the wrapped loader. (见被包装加载器)
    """
    return _material_cache.load_material_solver_cache_with_fallback(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        grid_resolution=grid_resolution,
        cache_root=cache_root,
    )


def load_solver_runtime(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    cache_root: str | Path | None = None,
    candidate_budget: int | None = None,
) -> tuple["MaterialSolverCache | MaterialCandidateRuntime | None", int | None]:
    """Load a lookup-compatible material solver runtime for hot paths.
    为热路径加载一个与求解缓存 ``lookup`` 兼容的运行时。

    Existing persisted :class:`MaterialSolverCache` files still take priority.
    When none is available, this builds a bounded
    :class:`MaterialCandidateRuntime` instead of falling back to the legacy
    low-grid exhaustive builder.

    已有持久化 ``MaterialSolverCache`` 优先；缺失时构建有候选数量上限的
    ``MaterialCandidateRuntime``，不再回退到旧的低 grid 穷举构建器。

    Args:
        materials: Palette to match. (调色板)
        layer_count: Number of layers per pixel. (每像素层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        grid_resolution: Preferred legacy cache grid resolution. (旧缓存优先网格)
        cache_root: Optional legacy cache directory override. (旧缓存目录覆盖)
        candidate_budget: Optional runtime candidate budget override.
            (可选候选数量覆盖)

    Returns:
        tuple: ``(runtime, actual_grid)`` where runtime exposes ``lookup``.
            (运行时与实际诊断分辨率)
    """
    cache, actual_grid = load_solver_cache(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        grid_resolution=grid_resolution,
        cache_root=cache_root,
    )
    if cache is not None:
        return cache, actual_grid

    if candidate_budget is None:
        for budget in PERSISTED_RUNTIME_PROBE_BUDGETS:
            persisted_runtime = load_material_candidate_runtime(
                materials,
                layer_count,
                layer_height_mm,
                substrate,
                candidate_budget=int(budget),
                cache_root=cache_root,
            )
            if persisted_runtime is not None:
                return persisted_runtime, persisted_runtime.grid_resolution
        config = MaterialCandidateCacheConfig.preview_safe()
    else:
        config = MaterialCandidateCacheConfig.persisted_for_budget(
            int(candidate_budget)
        )
        persisted_runtime = load_material_candidate_runtime(
            materials,
            layer_count,
            layer_height_mm,
            substrate,
            candidate_budget=int(config.candidate_budget),
            cache_root=cache_root,
        )
        if persisted_runtime is not None:
            return persisted_runtime, persisted_runtime.grid_resolution

    runtime = build_material_candidate_runtime(
        materials=materials,
        layer_count=int(layer_count),
        layer_height_mm=float(layer_height_mm),
        substrate=str(substrate),
        config=config,
    )
    return runtime, runtime.grid_resolution


def dynamic_layer_runtime_root(cache_root: str | Path | None = None) -> Path:
    """Cache root holding per-layer runtimes saved by dynamic Prepare.
    动态预构建所保存逐层运行时的缓存根目录。

    Pass the result as ``cache_root`` to the candidate-runtime load/save/delete
    helpers. It sits inside the solver cache folder but is never scanned by
    fixed-layer lookups, smart-cache listings, or status checks.

    将返回值作为 ``cache_root`` 传给候选运行时的加载/保存/删除函数。该目录位于
    求解缓存目录内，但固定层数查找、智能缓存列表与状态查询都不会扫描它。

    Args:
        cache_root: Optional solver cache root override. 可选求解缓存根目录。

    Returns:
        Path: Isolated root for prepared dynamic runtimes. 动态预构建运行时的独立根目录。
    """
    return _material_cache.default_cache_directory(cache_root) / DYNAMIC_LAYER_RUNTIME_SUBDIRECTORY


def load_dynamic_candidate_runtime(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    candidate_budget: int = PREVIEW_SAFE_CANDIDATE_BUDGET,
    cache_root: str | Path | None = None,
    persist: bool = False,
) -> tuple["MaterialCandidateRuntime", int | None]:
    """Load/build one pinned-budget candidate runtime for dynamic solving.

    为动态求解加载或构建一个固定预算的候选运行时。

    Unlike :func:`load_solver_runtime`, this function never probes a legacy
    fixed-grid :class:`MaterialSolverCache`. A single explicit candidate budget
    therefore identifies the same bounded universe at every effective layer,
    even if legacy cache files are added later. Palettes containing duplicate
    optical parameters remain distinct because persisted runtimes compare material
    identities and parameters directly.

    与 :func:`load_solver_runtime` 不同，本函数绝不探测旧的固定网格
    :class:`MaterialSolverCache`。因此同一个显式候选预算在每个有效层数上始终
    对应同一个有界候选宇宙，不会因后来新增旧缓存而改变。持久运行时直接比较
    耗材身份与参数，即使光学参数相同也能正确重绑当前耗材顺序。

    Args:
        materials: Material palette. 耗材调色板。
        layer_count: Effective recipe layer count. 有效配方层数。
        layer_height_mm: Physical layer height in millimeters. 物理层高。
        substrate: Optical substrate, ``white`` or ``black``. 光学基底。
        candidate_budget: Explicit candidate budget used for this layer.
            本层使用的显式候选预算。
        cache_root: Optional candidate-runtime cache root. 可选候选缓存根目录。
        persist: Save a freshly built runtime under
            :func:`dynamic_layer_runtime_root` so later catalog rebuilds (a new
            layer range or backing material) reuse it without fixed-layer
            lookups ever seeing it. Save failures are logged and never fail
            the build. 将新构建的运行时保存到 :func:`dynamic_layer_runtime_root`，
            使之后的目录重建可直接复用，且固定层数查找永远看不到它；保存失败仅记录
            日志，不影响构建。

    Returns:
        tuple[MaterialCandidateRuntime, int | None]: Candidate runtime and its
        diagnostic grid resolution. 候选运行时及诊断网格分辨率。
    """

    config = MaterialCandidateCacheConfig.persisted_for_budget(
        int(candidate_budget)
    )
    persisted_runtime = load_material_candidate_runtime(
        materials,
        int(layer_count),
        float(layer_height_mm),
        str(substrate),
        candidate_budget=int(config.candidate_budget),
        cache_root=cache_root,
    )
    if persisted_runtime is not None:
        return persisted_runtime, persisted_runtime.grid_resolution

    prepared_root = dynamic_layer_runtime_root(cache_root)
    prepared_runtime = load_material_candidate_runtime(
        materials,
        int(layer_count),
        float(layer_height_mm),
        str(substrate),
        candidate_budget=int(config.candidate_budget),
        cache_root=prepared_root,
    )
    if prepared_runtime is not None:
        return prepared_runtime, prepared_runtime.grid_resolution

    runtime = build_material_candidate_runtime(
        materials=materials,
        layer_count=int(layer_count),
        layer_height_mm=float(layer_height_mm),
        substrate=str(substrate),
        config=config,
    )
    if persist:
        _persist_runtime_best_effort(runtime, cache_root=prepared_root)
    return runtime, runtime.grid_resolution


def _persist_runtime_best_effort(
    runtime: "MaterialCandidateRuntime",
    *,
    cache_root: str | Path | None,
) -> None:
    """Save a runtime, logging instead of raising when the disk write fails."""
    try:
        save_material_candidate_runtime(runtime, cache_root=cache_root)
    except OSError as exc:
        _log.warning(
            "Dynamic layer runtime could not be saved",
            extra={
                "event": "dynamic_layer_runtime_save_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "layer_count": int(runtime.metadata.get("layer_count", 0)),
                "candidate_budget": int(runtime.metadata.get("candidate_budget", 0)),
            },
        )


def clear_memo_caches() -> None:
    """Drop all process-local memo caches.
    清空所有进程内 memo 缓存。

    Call this when material archives change on disk during a process lifetime
    (imports, deletes, edits) so the next load re-reads fresh data.

    当进程生命周期内磁盘上的耗材档案发生变化（导入/删除/编辑）时调用，使下次
    加载读取最新数据。
    """
    with _materials_lock:
        _materials_memo.clear()
