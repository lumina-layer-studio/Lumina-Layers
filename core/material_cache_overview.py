"""Read-only cache overview and dynamic-cache preparation for a combination.
材料组合的只读缓存概览与动态缓存预构建。

The converter and the Material > Solver Cache page both need to answer
"what is already saved for these settings, and what will the first conversion
have to build?". This module answers that from small metadata sidecars only,
and owns the explicit "prepare" action for dynamic layer counts.

转换器与"耗材 > 求解缓存"页面都需要回答"这些设置已保存了什么、首次转换
还需构建什么"。本模块只读取小型元数据侧文件来回答，并负责动态层数的显式
"预构建"操作。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from core import material_lut_provider
from core.material_cache import find_any_cached_grid
from core.material_candidate_cache import (
    PREVIEW_SAFE_CANDIDATE_BUDGET,
    delete_material_candidate_runtime,
    load_material_candidate_runtime_metadata,
)
from core.material_color_solver import MaterialParams
from core.material_dynamic_catalog_cache import (
    DynamicCatalogCacheKey,
    build_dynamic_catalog_cache_key,
    delete_dynamic_candidate_catalog,
    dynamic_material_canonical_order,
    find_dynamic_candidate_catalog_file,
)
from core.material_dynamic_solver import (
    DynamicMaterialSolveConfig,
    load_or_build_persistent_dynamic_catalog,
)
from core.material_lut_provider import (
    dynamic_layer_runtime_root,
    load_dynamic_candidate_runtime,
)

DYNAMIC_CANDIDATE_BUDGET: int = PREVIEW_SAFE_CANDIDATE_BUDGET
"""Candidate budget dynamic conversion pins for every layer count.
动态转换为每个层数固定使用的候选预算。"""


@dataclass(frozen=True)
class SavedFileInfo:
    """Size and modification time of one saved cache file.
    单个已保存缓存文件的大小与修改时间。
    """

    size_bytes: int
    modified_at: str | None


@dataclass(frozen=True)
class FixedLayerCacheOverview:
    """Saved caches a fixed-layer conversion can use.
    固定层数转换可用的已保存缓存。

    Attributes:
        exhaustive_grid_resolutions: Grids of saved exhaustive caches.
            已保存穷举缓存的网格分辨率。
        saved_runtime_budgets: Budgets of saved smart caches, largest first.
            已保存智能缓存的预算，从大到小。
    """

    exhaustive_grid_resolutions: tuple[int, ...]
    saved_runtime_budgets: tuple[int, ...]


@dataclass(frozen=True)
class DynamicLayerCacheOverview:
    """Saved data a dynamic-layer conversion can use.
    动态层数转换可用的已保存数据。

    Attributes:
        candidate_budget: Budget pinned for every layer count. 每层固定预算。
        catalog: Saved merged catalog for exactly these settings, if any.
            与当前设置完全一致的已保存合并目录。
        saved_layer_counts: Layer counts whose candidates are saved.
            候选已保存的层数。
        missing_layer_counts: Layer counts that would be built from scratch.
            需要从头构建的层数。
    """

    candidate_budget: int
    catalog: SavedFileInfo | None
    saved_layer_counts: tuple[int, ...]
    missing_layer_counts: tuple[int, ...]
    prepared_layer_counts: tuple[int, ...] = ()

    @property
    def is_ready(self) -> bool:
        """Whether a conversion can skip all candidate building. 是否可跳过全部构建。"""
        return self.catalog is not None


@dataclass(frozen=True)
class DynamicLayerCachePrepareResult:
    """Outcome of an explicit dynamic-cache preparation.
    显式动态缓存预构建结果。
    """

    overview: DynamicLayerCacheOverview
    built: bool
    elapsed_seconds: float


def _file_info(path: Path) -> SavedFileInfo | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    modified = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime))
    return SavedFileInfo(size_bytes=int(stat.st_size), modified_at=modified)


def describe_fixed_layer_caches(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    cache_root: str | Path | None = None,
) -> FixedLayerCacheOverview:
    """List saved caches for a fixed-layer combination without loading them.
    不加载数据，列出固定层数组合的已保存缓存。

    Args:
        materials: Palette in user order. 用户顺序耗材。
        layer_count: Color layers per stack. 每个叠层的颜色层数。
        layer_height_mm: Physical layer height. 物理层高。
        substrate: ``white`` or ``black``. 基底。
        cache_root: Optional cache root override. 可选缓存根目录。

    Returns:
        FixedLayerCacheOverview: Saved exhaustive grids and smart-cache budgets.
            已保存的穷举网格与智能缓存预算。
    """
    grids = tuple(
        grid
        for grid, _path in find_any_cached_grid(
            materials, layer_count, layer_height_mm, substrate, cache_root=cache_root
        )
    )
    budgets = tuple(
        int(budget)
        for budget in material_lut_provider.PERSISTED_RUNTIME_PROBE_BUDGETS
        if load_material_candidate_runtime_metadata(
            materials, layer_count, layer_height_mm, substrate,
            candidate_budget=int(budget), cache_root=cache_root,
        )
        is not None
    )
    return FixedLayerCacheOverview(grids, budgets)


def _dynamic_key(
    materials: list[MaterialParams],
    backing_index: int,
    layer_height_mm: float,
    substrate: str,
    config: DynamicMaterialSolveConfig,
) -> DynamicCatalogCacheKey:
    return build_dynamic_catalog_cache_key(
        materials,
        backing_material_index=int(backing_index),
        layer_height_mm=float(layer_height_mm),
        substrate=str(substrate),
        min_layer_count=config.min_layer_count,
        max_layer_count=config.max_layer_count,
        candidate_budget=DYNAMIC_CANDIDATE_BUDGET,
    )


def _canonical_dynamic_palette(materials: list[MaterialParams]) -> list[MaterialParams]:
    """Material order dynamic conversion uses when loading per-layer runtimes."""
    return [materials[index] for index in dynamic_material_canonical_order(materials)]


def _dynamic_layer_runtime_sources(
    canonical: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    cache_root: str | Path | None,
) -> tuple[bool, bool]:
    """Whether candidates are reusable and whether Prepare owns a saved copy.

    Dynamic conversion checks the shared solver cache (a manually built 1M
    smart cache) first and the isolated Prepare folder second.
    """
    available: list[bool] = []
    for root in (cache_root, dynamic_layer_runtime_root(cache_root)):
        record = load_material_candidate_runtime_metadata(
            canonical, layer_count, float(layer_height_mm), str(substrate),
            candidate_budget=DYNAMIC_CANDIDATE_BUDGET, cache_root=root,
        )
        available.append(record is not None)
    return any(available), available[1]


def describe_dynamic_layer_caches(
    materials: list[MaterialParams],
    backing_index: int,
    layer_height_mm: float,
    substrate: str,
    min_layer_count: int,
    max_layer_count: int,
    *,
    cache_root: str | Path | None = None,
) -> DynamicLayerCacheOverview:
    """Report saved dynamic-mode data without loading or building anything.
    不加载也不构建，报告动态模式已保存的数据。

    Args:
        materials: Palette in user order. 用户顺序耗材。
        backing_index: Backing material used for padding. 用于补位的基板耗材。
        layer_height_mm: Physical layer height. 物理层高。
        substrate: ``white`` or ``black``. 基底。
        min_layer_count: Smallest effective layer count. 最小有效层数。
        max_layer_count: Largest effective layer count. 最大有效层数。
        cache_root: Optional cache root override. 可选缓存根目录。

    Returns:
        DynamicLayerCacheOverview: Catalog and per-layer save state.
            目录与逐层保存状态。
    """
    config = DynamicMaterialSolveConfig(int(min_layer_count), int(max_layer_count), 0.0)
    key = _dynamic_key(materials, backing_index, layer_height_mm, substrate, config)
    catalog_path = find_dynamic_candidate_catalog_file(key, cache_root=cache_root)
    canonical = _canonical_dynamic_palette(materials)
    saved: list[int] = []
    missing: list[int] = []
    prepared: list[int] = []
    for layer_count in range(config.min_layer_count, config.max_layer_count + 1):
        is_saved, is_prepared = _dynamic_layer_runtime_sources(
            canonical, layer_count, layer_height_mm, substrate, cache_root
        )
        (saved if is_saved else missing).append(layer_count)
        if is_prepared:
            prepared.append(layer_count)
    return DynamicLayerCacheOverview(
        candidate_budget=DYNAMIC_CANDIDATE_BUDGET,
        catalog=_file_info(catalog_path) if catalog_path is not None else None,
        saved_layer_counts=tuple(saved),
        missing_layer_counts=tuple(missing),
        prepared_layer_counts=tuple(prepared),
    )


def prepare_dynamic_layer_cache(
    materials: list[MaterialParams],
    backing_index: int,
    layer_height_mm: float,
    substrate: str,
    min_layer_count: int,
    max_layer_count: int,
    *,
    cache_root: str | Path | None = None,
) -> DynamicLayerCachePrepareResult:
    """Build and save everything a dynamic conversion needs, ahead of time.
    提前构建并保存动态转换所需的全部数据。

    Saves each per-layer candidate set (in an isolated folder that fixed-layer
    lookups never read) as well as the merged catalog, so a later change of
    layer range or backing material only redoes the merge.
    Per-layer sets are built and saved *before* the catalog lock is taken, so
    the locked merge stays short and concurrent conversions do not time out
    waiting for disk writes.

    同时保存逐层候选集与合并目录，之后更换层数范围或基板耗材时只需重做合并。
    逐层候选在获取目录锁之前构建并保存，使加锁的合并步骤保持很短，并发转换
    不会因等待写盘而超时。

    Args:
        materials: Palette in user order. 用户顺序耗材。
        backing_index: Backing material used for padding. 用于补位的基板耗材。
        layer_height_mm: Physical layer height. 物理层高。
        substrate: ``white`` or ``black``. 基底。
        min_layer_count: Smallest effective layer count. 最小有效层数。
        max_layer_count: Largest effective layer count. 最大有效层数。
        cache_root: Optional cache root override. 可选缓存根目录。

    Returns:
        DynamicLayerCachePrepareResult: Final overview, whether anything was
            built, and elapsed time. 最终概览、是否发生构建及耗时。
    """
    config = DynamicMaterialSolveConfig(int(min_layer_count), int(max_layer_count), 0.0)
    before = describe_dynamic_layer_caches(
        materials, backing_index, layer_height_mm, substrate,
        config.min_layer_count, config.max_layer_count, cache_root=cache_root,
    )
    if before.is_ready and not before.missing_layer_counts:
        return DynamicLayerCachePrepareResult(overview=before, built=False, elapsed_seconds=0.0)

    started = time.perf_counter()
    # Same canonical order dynamic conversion uses, so the saved files match.
    canonical = _canonical_dynamic_palette(materials)
    for layer_count in before.missing_layer_counts:
        load_dynamic_candidate_runtime(
            canonical,
            layer_count,
            float(layer_height_mm),
            str(substrate),
            candidate_budget=DYNAMIC_CANDIDATE_BUDGET,
            cache_root=cache_root,
            persist=True,
        )
    load_or_build_persistent_dynamic_catalog(
        materials,
        int(backing_index),
        float(layer_height_mm),
        str(substrate),
        config,
        candidate_budget=DYNAMIC_CANDIDATE_BUDGET,
        cache_root=cache_root,
    )
    elapsed = time.perf_counter() - started
    overview = describe_dynamic_layer_caches(
        materials, backing_index, layer_height_mm, substrate,
        config.min_layer_count, config.max_layer_count, cache_root=cache_root,
    )
    return DynamicLayerCachePrepareResult(
        overview=overview,
        built=True,
        elapsed_seconds=round(elapsed, 3),
    )


def delete_dynamic_layer_cache(
    materials: list[MaterialParams],
    backing_index: int,
    layer_height_mm: float,
    substrate: str,
    min_layer_count: int,
    max_layer_count: int,
    *,
    cache_root: str | Path | None = None,
) -> bool:
    """Delete what Prepare saved for these settings.
    删除预构建为当前设置保存的数据。

    Removes the merged catalog and the per-layer candidates in the isolated
    Prepare folder for every layer count in the range. Manually built smart
    caches in the shared folder are never touched. Conversion rebuilds
    anything it needs on its next run.

    删除合并目录，以及独立预构建目录中该范围内每个层数的逐层候选；共享目录中
    手动构建的智能缓存不会被触碰。下次转换会按需重新构建。

    Returns:
        bool: Whether any saved file was removed. 是否删除了任何已保存文件。
    """
    config = DynamicMaterialSolveConfig(int(min_layer_count), int(max_layer_count), 0.0)
    key = _dynamic_key(materials, backing_index, layer_height_mm, substrate, config)
    removed = delete_dynamic_candidate_catalog(key, cache_root=cache_root)
    canonical = _canonical_dynamic_palette(materials)
    prepared_root = dynamic_layer_runtime_root(cache_root)
    for layer_count in range(config.min_layer_count, config.max_layer_count + 1):
        removed = delete_material_candidate_runtime(
            canonical, layer_count, float(layer_height_mm), str(substrate),
            candidate_budget=DYNAMIC_CANDIDATE_BUDGET, cache_root=prepared_root,
        ) or removed
    return removed
