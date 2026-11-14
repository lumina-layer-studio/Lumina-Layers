"""Material-solver disk cache — 128³ Lab-grid bucketed recipe lookup.
耗材求解器磁盘缓存 —— 128³ Lab 网格分桶的配方查询。

This module provides a persistent, per-palette cache of optimal Beer-Lambert
recipes, built by enumerating every ``M**N`` ordered layer sequence, bucketing
each combination's output color into a 3-D Lab grid, and keeping the
bucket-center-closest recipe per occupied cell.

Runtime lookup: given target sRGB colors, a KD-Tree over occupied bucket
centers finds the nearest stored recipe. Worst-case ΔE(target, achieved) is
bounded by a cell's half-diagonal; typical error is ~1-2 ΔE for the 128³ default.

Each cache uses an opaque record filename and a small ``.meta.json`` sidecar.
Reuse compares the saved material identities, effective optical parameters,
layer settings, grid and solver version directly. Older entries without these
descriptors remain on disk but are not reused.

Public API:
    - ``MaterialSolverCache``          — loaded cache with ``lookup()``
    - ``build_material_solver_cache``  — enumerate + bucket + return in-memory cache
    - ``save_material_solver_cache``   — persist to disk
    - ``load_material_solver_cache``   — load from disk
    - ``cache_file_path``              — canonical on-disk path for parameters
    - ``default_cache_directory``      — cache root (launcher override or materials fallback)
    - ``describe_palette``             — canonical effective material descriptors
    - ``list_cached_entries``          — enumerate cached combinations
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Any, Callable, Iterator

import cv2
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.distance import cdist

from config import MATERIALS_DIR
from api.structured_logging import get_logger
from core.material_color_solver import (
    ALLOWED_LAYER_HEIGHTS_MM,
    DEFAULT_SUGGEST_MIN_SPACING,
    DEFAULT_SUGGEST_TOP_K,
    MITM_MAX_LAYER_COUNT as MAX_LAYER_COUNT,  # legacy exhaustive builder cap
    MIN_LAYER_COUNT,
    ColorSuggestion,
    MaterialParams,
    _compute_material_affines,
    _enumerate_cumulative_affines,
    _greedy_lab_spacing_dedup,
    forward_model,
    linear_to_srgb_float,
    linear_to_srgb_uint8,
    rgb_to_lab,
)
from core.task_parallelism import task_parallelism_worker_scope

_log = get_logger(__name__)

# Maximum CIE76 ΔE penalty tolerated when switching from the CIE76-best
# candidate to a hue-aware candidate.  If the hue pick's ΔE exceeds the
# CIE76-best by more than this, we fall back to the CIE76-best to avoid
# major luminance/chroma regressions on deeply out-of-gamut colours.
# 色相保护允许的最大 CIE76 ΔE 惩罚；超出时回退到 CIE76 最优。
HUE_RERANK_MAX_DE_PENALTY: float = 5.0

# ---------------------------------------------------------------------------
# Constants & schema
# ---------------------------------------------------------------------------

EXACT_MODE_MAX_MATERIALS: int = 10
"""Maximum number of materials for exact (exhaustive) mode.
精确穷举模式最大耗材数。当 M ≤ 此值且 N ≤ EXACT_MODE_MAX_LAYERS 时
自动走精确模式，跳过 Lab 网格分桶，保留全量 M^N 配方表实现零精度损失。"""

EXACT_MODE_MAX_LAYERS: int = 5
"""Maximum layer count for exact (exhaustive) mode.
精确穷举模式最大层数。"""

EXACT_MODE_MAX_COMBINATIONS: int = 100_000
"""Hard cap on total combinations allowed in exact mode.
精确模式组合数上限，作为最终安全阀。"""

DEFAULT_GRID_RESOLUTION: int = 64
"""Lab grid cells per axis. Total cell count is ``grid_resolution ** 3``.

Default 64 (`low`) keeps compressed caches around ~4 MB, with a
worst-case bucket-diagonal ΔE of ~5.5 — visible but acceptable for the
default preview-grade workflow. Users who want tighter color accuracy
can opt in via the "Exhaustive density" setting and pick a higher tier
— see :data:`ALLOWED_GRID_RESOLUTIONS` for the full ladder.

Higher tiers reduce *bucket-collision loss* (the number of distinct
recipes that get discarded because they fall into the same Lab bucket
as another recipe). At very high tiers virtually every reachable
recipe lands in its own bucket, so the cache surfaces the full set of
physically achievable colours.

默认 64（低档）压缩后缓存约 4 MB，最坏桶对角 ΔE ~5.5，对默认预览
工作流是可以接受的折衷。需要更严格色彩精度的用户可以在"穷举数量"
设置里开启自定义并选择更高档位，完整阶梯见
:data:`ALLOWED_GRID_RESOLUTIONS`。更高档主要降低"桶碰撞损失"（多个
配方落入同一 Lab 桶时只保留一个）；极致档下几乎每条可达配方都独占
一个桶，缓存就能完整暴露物理可达色集。
"""

ALLOWED_GRID_RESOLUTIONS: tuple[int, ...] = (64, 128, 256, 512, 1024, 2048)
"""Whitelist of user-facing grid resolutions exposed through the UI/API.

Each tier doubles the per-axis cell count. Since
:func:`build_material_solver_cache` uses sparse per-bucket storage,
build memory does *not* scale with ``grid_resolution ** 3``; it scales
with the number of physically reachable recipes
(``materials ** layers``), bounded above by ``valid_cell_count``. So
the high tiers are limited by lookup-time and cache-file size rather
than RAM:

================  ============  ===============================
grid_resolution   total buckets  notes / 备注
================  ============  ===============================
64                ~262 K         default / 默认；ΔE ~5.5
128               ~2.1 M         medium / 中；ΔE ~2.7
256               ~16.8 M        high / 高；ΔE ~1.4
512               ~134 M         very high / 极高
1024              ~1.07 B        ultra / 极致
2048              ~8.59 B        ultra+ / 极致+；几乎无桶碰撞
================  ============  ===============================

``core`` does not enforce the whitelist — build/save/load remain
flexible for tests and internal callers — but API routes and pipeline
adapters must reject unknown values with a 4xx error.

面向用户的网格分辨率白名单；构建期内存随实际可达配方数增长，与档位
无关（稀疏存储），所以高档位的真实代价主要落在查找时间与缓存文件大小，
而非内存。``core`` 层保持灵活（便于测试与内部调用），API 路由与
pipeline 适配层必须拒绝白名单之外的值并返回 4xx。
"""

CACHE_SCHEMA_VERSION: str = "2.0"
CACHE_SOLVER_VERSION: str = "continuous-lab-v2"
CACHE_SUBDIR: str = "_solver_cache"

_PARAMETER_DECIMALS: int = 6

_CHUNK_TARGET_BYTES: int = 64 * 1024 * 1024
"""Local temporary-array target for one build chunk."""


def _is_exact_mode_eligible(num_materials: int, layer_count: int) -> bool:
    """Check whether the palette/layer combination qualifies for exact mode.
    判断该耗材数/层数组合是否满足精确穷举条件。

    Exact mode stores the complete M^N formula table (no bucketing) and does
    brute-force ΔE lookup, guaranteeing zero precision loss. The eligibility
    thresholds (M≤10, N≤5, M^N≤100K) keep memory and build time manageable.
    """
    if num_materials > EXACT_MODE_MAX_MATERIALS:
        return False
    if layer_count > EXACT_MODE_MAX_LAYERS:
        return False
    if num_materials ** layer_count > EXACT_MODE_MAX_COMBINATIONS:
        return False
    return True


# ---------------------------------------------------------------------------
# Effective material descriptors
# ---------------------------------------------------------------------------


def describe_material(mat: MaterialParams) -> dict[str, Any]:
    """Describe stable identity and effective Beer-Lambert parameters.
    描述稳定耗材身份与有效 Beer-Lambert 参数。

    Preserve the existing six-decimal cache equivalence for fitted parameters.
    保留拟合参数现有的六位小数缓存等价规则。

    Args:
        mat: Material identity and optical parameters. 耗材身份与光学参数。

    Returns:
        dict[str, Any]: JSON-compatible effective descriptor.
            可 JSON 序列化的有效参数描述。
    """
    return {
        "directory_name": str(mat.directory_name),
        "name": str(mat.name),
        "E": [round(float(v), _PARAMETER_DECIMALS) for v in mat.E.tolist()],
        "k": [round(float(v), _PARAMETER_DECIMALS) for v in mat.k.tolist()],
        "C0_white": [
            round(float(v), _PARAMETER_DECIMALS) for v in mat.C0_white.tolist()
        ],
    }


def describe_palette(materials: list[MaterialParams]) -> list[dict[str, Any]]:
    """Return directly comparable descriptors in established recipe order.
    按既有配方顺序返回可直接比较的耗材描述。

    Materials with equal optical parameters keep their original input order.
    光学参数相同的耗材保持原输入顺序。

    Args:
        materials: Non-empty material palette. 非空耗材列表。

    Returns:
        list[dict[str, Any]]: Descriptors in canonical recipe-column order.
            按规范配方列顺序排列的耗材描述。
    """
    if not materials:
        raise ValueError("Cannot describe an empty palette")
    return [describe_material(materials[i]) for i in canonical_palette_order(materials)]


def _legacy_material_enumeration_key(mat: MaterialParams) -> str:
    """Preserve the numerical algorithm's established material ordering only.

    Bounded sampling and equal-color recipe choices depend on this historical
    order. It is never a cache identity, filename, or equality check.
    """
    descriptor = describe_material(mat)
    optical_parameters = {
        field: descriptor[field] for field in ("E", "k", "C0_white")
    }
    serialized = json.dumps(optical_parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def canonical_palette_order(materials: list[MaterialParams]) -> list[int]:
    """Return the established enumeration and sampling order of material indices.
    返回既有枚举与采样算法使用的耗材索引顺序。

    Preserve historical optical-parameter ordering and stable input ties so
    existing color results and physical recipes remain unchanged. Cache reuse
    separately compares full material descriptors directly.
    保留历史光学参数排序与输入顺序并列规则，使颜色结果和物理配方保持不变。
    缓存复用另行直接比较完整耗材描述。
    """
    enumeration_keys = [_legacy_material_enumeration_key(material) for material in materials]
    return sorted(range(len(materials)), key=lambda i: enumeration_keys[i])


# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------


def default_cache_directory(cache_root: str | Path | None = None) -> Path:
    """Return the default cache directory.
    返回默认缓存目录。

    An explicit ``cache_root`` takes priority. Otherwise launcher runtimes can
    isolate derived data with the absolute ``LUMINA_RUNTIME_CACHE_DIR`` path;
    source deployments keep the legacy ``<MATERIALS_DIR>/_solver_cache/``
    location.

    显式传入的 ``cache_root`` 优先。否则，启动器运行包可通过绝对路径环境变量
    ``LUMINA_RUNTIME_CACHE_DIR`` 隔离派生缓存；源码部署继续使用旧的
    ``<MATERIALS_DIR>/_solver_cache/`` 位置。

    Raises:
        ValueError: If the launcher override is not absolute.
            启动器覆盖路径不是绝对路径时抛出。
    """
    if cache_root is not None:
        root = Path(cache_root)
    else:
        launcher_root = os.environ.get("LUMINA_RUNTIME_CACHE_DIR", "").strip()
        if launcher_root:
            root = Path(launcher_root).expanduser()
            if not root.is_absolute():
                raise ValueError(
                    "LUMINA_RUNTIME_CACHE_DIR must be an absolute directory path"
                )
        else:
            root = Path(MATERIALS_DIR)
    return root / CACHE_SUBDIR


def _find_cache_record(directory: Path, expected: dict[str, Any]) -> Path | None:
    records = []
    for meta_path in sorted(directory.glob("*.meta.json")):
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(metadata, dict) and metadata.get("cache_id") and all(
            metadata.get(key) == value for key, value in expected.items()
        ):
            records.append(meta_path.with_name(
                meta_path.name.removesuffix(".meta.json") + ".npz"
            ))
    return records[0] if records else None


def _solver_cache_parameters(
    materials: list[MaterialParams], layer_count: int, layer_height_mm: float,
    substrate: str, grid_resolution: int | None = None,
) -> dict[str, Any]:
    expected = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "solver_version": CACHE_SOLVER_VERSION,
        "canonical_materials": describe_palette(materials),
        "layer_count": int(layer_count),
        "layer_height_mm": float(layer_height_mm),
        "substrate": str(substrate),
    }
    if grid_resolution is not None:
        expected["grid_resolution"] = int(grid_resolution)
    return expected


def cache_file_path(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    cache_root: str | Path | None = None,
) -> Path:
    """Find a matching record, or allocate an opaque path for a new entry.
    查找匹配记录，或为新条目分配不透明路径。

    Args:
        materials: Palette used for enumeration. (枚举用耗材列表)
        layer_count: Number of layers per pixel. (每像素层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        grid_resolution: Expected Lab cells per axis; zero selects exact mode.
            期望的 Lab 每轴格数；零表示精确模式。
        cache_root: Optional override for the cache directory. (可选缓存根目录)
    """
    directory = default_cache_directory(cache_root)
    existing = _find_cache_record(directory, _solver_cache_parameters(
        materials, layer_count, layer_height_mm, substrate, grid_resolution
    ))
    return existing or directory / f"solver-{uuid.uuid4().hex}.npz"


def _cache_meta_path_for(npz_path: Path) -> Path:
    """Return the ``.meta.json`` sidecar path next to ``npz_path``."""
    return npz_path.with_name(npz_path.stem + ".meta.json")


# ---------------------------------------------------------------------------
# Hue-aware reranking helpers
# ---------------------------------------------------------------------------


def _lab_to_lch(lab: np.ndarray) -> np.ndarray:
    """Convert standard Lab ``(…, 3)`` to LCH ``(…, 3)``.

    Standard Lab scale: L 0-100, a/b -128..127 (as returned by
    :func:`rgb_to_lab`).  Output: L unchanged, C = chroma,
    H = hue angle in degrees [0, 360).

    标准 Lab → LCH；L 不变，C = 彩度，H = 色相角（度）。
    """
    L = lab[..., 0]
    a = lab[..., 1]
    b = lab[..., 2]
    C = np.sqrt(a ** 2 + b ** 2)
    H = np.degrees(np.arctan2(b, a)) % 360
    return np.stack([L, C, H], axis=-1)


def _hue_aware_rerank(
    target_lab: np.ndarray,
    candidate_lab: np.ndarray,
    candidate_delta_e: np.ndarray,
    hue_weight: float,
) -> np.ndarray:
    """Select the best candidate per target using LCH hue-aware distance.

    Falls back to the CIE76-best candidate when the hue-aware pick
    would incur a CIE76 ΔE penalty larger than
    :data:`HUE_RERANK_MAX_DE_PENALTY`.

    对每个目标色用 LCH 加权距离挑选候选；若色相候选的 CIE76 ΔE 超出
    CIE76 最优太多（超过 ``HUE_RERANK_MAX_DE_PENALTY``）则安全回退。

    Args:
        target_lab: ``(C, 3)`` float64 target colours in Lab.
        candidate_lab: ``(C, K, 3)`` float64 candidate colours in Lab.
        candidate_delta_e: ``(C, K)`` pre-computed CIE76 ΔE.
        hue_weight: 0.0–1.0 slider value from the UI; mapped to
            ``w_H`` via the same exponential curve as
            :class:`core.color_matching_hue_aware.HueAwareColorMatcher`.

    Returns:
        ``(C,)`` int64 array of per-target best-candidate column indices.
    """
    C_count, K = candidate_delta_e.shape

    # Map hue_weight 0–1 → w_H via the same exponential curve used by
    # HueAwareColorMatcher so the UI slider behaves identically.
    hw = float(np.clip(hue_weight, 0.0, 1.0))
    w_H = 0.15 + 0.85 * (1.0 - hw) ** 3

    # Convert to LCH
    target_lch = _lab_to_lch(target_lab)                       # (C, 3)
    cand_lch = _lab_to_lch(candidate_lab.reshape(-1, 3))       # (C*K, 3)
    cand_lch = cand_lch.reshape(C_count, K, 3)

    # Weighted distance components
    dL = cand_lch[..., 0] - target_lch[:, None, 0]            # (C, K)
    dC = cand_lch[..., 1] - target_lch[:, None, 1]            # (C, K)

    # ΔH = 2 * min(C_target, C_candidate) * sin(Δh / 2)
    dh_deg = cand_lch[..., 2] - target_lch[:, None, 2]
    dh_deg = (dh_deg + 180.0) % 360.0 - 180.0
    dh_rad = np.radians(dh_deg)
    delta_H = (
        2.0
        * np.minimum(target_lch[:, None, 1], cand_lch[..., 1])
        * np.sin(dh_rad / 2.0)
    )

    hue_dist = np.sqrt(dL ** 2 + dC ** 2 + (delta_H / w_H) ** 2)  # (C, K)
    hue_best_pos = np.argmin(hue_dist, axis=1)                     # (C,)

    # Safety cap: fall back to CIE76-best when ΔE penalty exceeds threshold
    cie76_best_pos = np.argmin(candidate_delta_e, axis=1)
    row_idx = np.arange(C_count, dtype=np.int64)
    cie76_best_de = candidate_delta_e[row_idx, cie76_best_pos]
    hue_pick_de = candidate_delta_e[row_idx, hue_best_pos]
    penalty = hue_pick_de - cie76_best_de
    fallback_mask = penalty > HUE_RERANK_MAX_DE_PENALTY
    result = hue_best_pos.copy()
    result[fallback_mask] = cie76_best_pos[fallback_mask]
    return result


# ---------------------------------------------------------------------------
# Neighbor coherence refinement
# ---------------------------------------------------------------------------

# Maximum absolute ΔE penalty tolerated when switching from the per-color
# CIE76-best to a neighbor-coherent candidate. If the coherent pick's ΔE
# exceeds the original best by more than this, we keep the original.
# 邻近色一致性修正允许的最大 ΔE 惩罚；超出时保留原始最优匹配。
_NEIGHBOR_COHERENCE_MAX_DE_PENALTY: float = 8.0

# Lab distance threshold below which two source colours are considered
# "neighbours" for coherence purposes.
# 两个源色在 Lab 中的距离低于此阈值时被视为邻近色对。
_NEIGHBOR_COHERENCE_PROXIMITY_THRESHOLD: float = 20.0

# Number of top candidates to consider per target during refinement.
# 修正时每个目标色考察的候选数。
_NEIGHBOR_COHERENCE_TOP_K: int = 8

_NEIGHBOR_COHERENCE_DEFAULT_BLOCK_ROWS: int = 256
"""Local target-row block size for exact distance calculations."""


def _iter_neighbor_pairs_with_distances(
    target_lab: np.ndarray,
    *,
    threshold: float,
) -> Iterator[tuple[int, int, np.floating]]:
    """Yield strict-threshold Lab pairs and their exact discovery distance.

    Querying one target row at a time bounds candidate-neighbour storage to
    ``O(C)`` even when all colors are mutually close. 按目标行查询，避免
    ``query_pairs`` 在稠密颜色集上一次物化 ``O(C²)`` 候选对。
    """

    targets = np.asarray(target_lab, dtype=np.float64)
    if targets.shape[0] < 2 or float(threshold) <= 0.0:
        return

    query_radius = np.nextafter(float(threshold), np.inf)
    tree = cKDTree(targets)
    for row_index in range(targets.shape[0]):
        neighbor_indices = np.asarray(
            sorted(
                int(index)
                for index in tree.query_ball_point(
                    targets[row_index],
                    query_radius,
                )
                if int(index) > row_index
            ),
            dtype=np.intp,
        )
        if neighbor_indices.size == 0:
            continue
        differences = (
            targets[row_index][None, :]
            - targets[neighbor_indices]
        )
        exact_distances = np.sqrt(
            np.sum(differences * differences, axis=1),
        )
        valid_mask = exact_distances < float(threshold)
        for column_index in neighbor_indices[valid_mask]:
            # Recompute with the coherence pass's own norm: the vectorized sum
            # above can differ by one ULP from ``dot`` on some BLAS builds.
            distance = _real_vector_norm(
                targets[column_index] - targets[row_index]
            )
            yield row_index, int(column_index), distance


def _iter_neighbor_pairs(
    target_lab: np.ndarray,
    *,
    threshold: float,
) -> Iterator[tuple[int, int]]:
    """Yield strict-threshold Lab pairs in legacy lexicographic order."""

    for row_index, column_index, _distance in (
        _iter_neighbor_pairs_with_distances(
            target_lab,
            threshold=threshold,
        )
    ):
        yield row_index, column_index


def _find_neighbor_pairs(
    target_lab: np.ndarray,
    *,
    threshold: float,
) -> np.ndarray:
    """Materialize neighbor pairs for diagnostics and exactness tests."""

    return np.asarray(
        list(_iter_neighbor_pairs(target_lab, threshold=threshold)),
        dtype=np.intp,
    ).reshape(-1, 2)


def _top_k_candidate_block(
    target_block: np.ndarray,
    candidate_lab: np.ndarray,
    top_k: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute legacy top-K candidate rows for one target block."""

    with task_parallelism_worker_scope():
        distances = cdist(target_block, candidate_lab, metric="euclidean")
        candidate_count = candidate_lab.shape[0]
        if top_k >= candidate_count:
            indices = np.broadcast_to(
                np.arange(candidate_count, dtype=np.intp)[None, :],
                (target_block.shape[0], candidate_count),
            ).copy()
        else:
            indices = np.argpartition(
                distances,
                top_k,
                axis=1,
            )[:, :top_k]
        selected_distances = np.take_along_axis(distances, indices, axis=1)
        return indices, selected_distances


def _top_k_candidate_rows_blockwise(
    *,
    target_lab: np.ndarray,
    candidate_lab: np.ndarray,
    top_k: int,
    block_size: int | None = None,
    parallelism: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute exact legacy top-K rows without retaining a full ``C × K`` matrix.

    按目标色分块计算与旧实现完全相同的 ``cdist`` 和 ``argpartition`` 结果。
    并行时会将总临时矩阵预算均分给 worker，结果按原目标行切片写回。

    Args:
        target_lab: ``(C, 3)`` target Lab rows. (目标 Lab)
        candidate_lab: ``(K, 3)`` candidate Lab rows. (候选 Lab)
        top_k: Maximum candidates retained per target. (每个目标保留数)
        block_size: Optional explicit target rows per block. (显式分块行数)
        parallelism: Maximum independent blocks processed together. (并行块数)
        block_size: Target rows processed by one local distance block. (单个
            距离计算块的目标行数)

    Returns:
        ``(indices, distances)`` arrays with shape ``(C, min(top_k, K))``.
        返回索引和对应距离数组。
    """

    targets = np.asarray(target_lab)
    candidates = np.asarray(candidate_lab)
    target_count = targets.shape[0]
    candidate_count = candidates.shape[0]
    effective_top_k = min(max(0, int(top_k)), candidate_count)
    if target_count == 0 or candidate_count == 0:
        return (
            np.empty((target_count, effective_top_k), dtype=np.intp),
            np.empty((target_count, effective_top_k), dtype=np.float64),
        )

    requested_workers = max(1, int(parallelism))
    resolved_block_size = min(
        target_count,
        max(1, int(block_size or _NEIGHBOR_COHERENCE_DEFAULT_BLOCK_ROWS)),
    )

    slices = [
        (start, min(start + resolved_block_size, target_count))
        for start in range(0, target_count, resolved_block_size)
    ]
    worker_count = min(
        requested_workers,
        len(slices),
    )
    if worker_count > 1:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(
                    _top_k_candidate_block,
                    targets[start:end],
                    candidates,
                    effective_top_k,
                )
                for start, end in slices
            ]
            block_results = [future.result() for future in futures]
    else:
        block_results = [
            _top_k_candidate_block(
                targets[start:end],
                candidates,
                effective_top_k,
            )
            for start, end in slices
        ]

    selected_indices = np.empty(
        (target_count, effective_top_k),
        dtype=np.intp,
    )
    selected_distances = np.empty(
        (target_count, effective_top_k),
        dtype=np.float64,
    )
    for (start, end), (block_indices, block_distances) in zip(
        slices,
        block_results,
        strict=True,
    ):
        selected_indices[start:end] = block_indices
        selected_distances[start:end] = block_distances
    return selected_indices, selected_distances


@dataclass
class _ExactTopKRowCache:
    """Request-local exact Top-K rows for serial coherence refinement.

    串行邻近一致性修正使用的请求级精确 Top-K 行缓存。
    """

    target_lab: np.ndarray
    candidate_lab: np.ndarray
    top_k: int
    indices: np.ndarray
    distances: np.ndarray
    ready: np.ndarray

    @classmethod
    def create(
        cls,
        *,
        target_lab: np.ndarray,
        candidate_lab: np.ndarray,
        top_k: int,
    ) -> "_ExactTopKRowCache":
        """Allocate an empty cache without computing candidate rows.

        分配空缓存，不提前计算任何候选行。
        """

        targets = np.asarray(target_lab)
        candidates = np.asarray(candidate_lab)
        effective_top_k = min(max(0, int(top_k)), candidates.shape[0])
        return cls(
            target_lab=targets,
            candidate_lab=candidates,
            top_k=effective_top_k,
            indices=np.empty(
                (targets.shape[0], effective_top_k),
                dtype=np.intp,
            ),
            distances=np.empty(
                (targets.shape[0], effective_top_k),
                dtype=np.float64,
            ),
            ready=np.zeros(targets.shape[0], dtype=bool),
        )

    def get(self, row_index: int) -> tuple[np.ndarray, np.ndarray]:
        """Return one exact legacy Top-K row, computing it at most once.

        返回一行与旧实现完全一致的 Top-K，每行最多计算一次。
        """

        target_row = self.target_lab[row_index]
        if not self.ready[row_index]:
            block_indices, block_distances = _top_k_candidate_block(
                target_row[None, :],
                self.candidate_lab,
                self.top_k,
            )
            self.indices[row_index] = block_indices[0]
            self.distances[row_index] = block_distances[0]
            self.ready[row_index] = True
        return self.indices[row_index], self.distances[row_index]


def _real_vector_norm(vector: np.ndarray) -> np.floating:
    """Return the exact NumPy real 1-D fast-path norm for a known vector."""

    return np.sqrt(vector.dot(vector))


def _neighbor_coherence_refine(
    *,
    target_lab: np.ndarray,
    matched_rgb: np.ndarray,
    recipes_user_order: np.ndarray,
    delta_e: np.ndarray,
    all_lab: np.ndarray,
    all_srgb: np.ndarray,
    all_recipes: np.ndarray,
    user_mapping: np.ndarray,
    coherence_weight: float,
    layer_count: int,
    uniform_lab: np.ndarray | None,
    uniform_srgb: np.ndarray | None,
    uniform_recipes: np.ndarray | None,
    candidate_block_size: int | None = None,
    parallelism: int = 1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Refine per-color best picks to preserve gradient coherence among neighbours.
    对初始逐色最优匹配做邻近色一致性修正，保持相邻色之间的梯度方向与间距比例。

    Algorithm:
      1. Build an adjacency graph: pairs (i, j) where ΔE(target_i, target_j) < threshold.
      2. For each pair, compute the source direction vector in Lab: d_src = target_j - target_i.
      3. Check if the matched direction d_matched = matched_j_lab - matched_i_lab preserves
         the same direction (cosine similarity) and proportional spacing.
      4. When coherence is broken, try swapping one of the pair's picks to a top-K candidate
         that restores direction while staying within the absolute ΔE penalty cap.

    算法：
      1. 建立邻接图：源色 Lab 距离 < 阈值的所有颜色对 (i, j)。
      2. 对每对计算源方向向量 d_src = target_j - target_i。
      3. 检查匹配后方向 d_matched 是否保持了同向性（余弦相似度）和比例间距。
      4. 当一致性被破坏时，从 top-K 候选里为该对中的某一色选一个更一致的替代，
         前提是绝对 ΔE 惩罚不超过阈值。

    Returns the (potentially refined) matched_rgb, recipes, delta_e arrays.
    """
    C_count = target_lab.shape[0]
    if C_count < 2:
        return matched_rgb, recipes_user_order, delta_e

    # 1. Find neighbor pairs
    pair_iterator = _iter_neighbor_pairs_with_distances(
        target_lab,
        threshold=_NEIGHBOR_COHERENCE_PROXIMITY_THRESHOLD,
    )
    first_pair = next(pair_iterator, None)
    if first_pair is None:
        return matched_rgb, recipes_user_order, delta_e

    # 2. Get top-K candidates for each target (computed once)
    K_total = all_lab.shape[0]
    top_k = min(_NEIGHBOR_COHERENCE_TOP_K, K_total)
    topk_row_cache: _ExactTopKRowCache | None = None
    topk_indices: np.ndarray | None = None
    topk_distances: np.ndarray | None = None
    if int(parallelism) <= 1:
        topk_row_cache = _ExactTopKRowCache.create(
            target_lab=target_lab,
            candidate_lab=all_lab,
            top_k=top_k,
        )
    else:
        topk_indices, topk_distances = _top_k_candidate_rows_blockwise(
            target_lab=target_lab,
            candidate_lab=all_lab,
            top_k=top_k,
            block_size=candidate_block_size,
            parallelism=parallelism,
        )

    # Current matched Lab (from matched_rgb)
    matched_lab = rgb_to_lab(matched_rgb).astype(np.float64)

    # Track which targets have been refined (to avoid cascading conflicts)
    refined = np.zeros(C_count, dtype=bool)
    new_matched_rgb = matched_rgb.copy()
    new_recipes = recipes_user_order.copy()
    new_de = delta_e.copy()
    refinement_count = 0
    pair_count = 0

    # 3. For each pair, check coherence and refine if needed
    for i, j, d_src_norm in chain((first_pair,), pair_iterator):
        pair_count += 1
        # Source direction vector
        d_src = target_lab[j] - target_lab[i]
        if d_src_norm < 1e-6:
            continue  # identical colours, skip

        # Current matched direction
        d_matched = matched_lab[j] - matched_lab[i]
        d_matched_norm = _real_vector_norm(d_matched)

        # Cosine similarity between source and matched direction
        if d_matched_norm < 1e-6:
            cos_sim = 0.0
        else:
            cos_sim = float(np.dot(d_src, d_matched) / (d_src_norm * d_matched_norm))

        # Spacing ratio: how much the relative distance changed
        spacing_ratio = d_matched_norm / d_src_norm if d_src_norm > 0 else 1.0

        # Coherence score: 1.0 = perfect preservation, 0.0 = completely broken
        # Combines direction (cosine) and spacing (penalise extreme stretching)
        direction_score = max(0.0, cos_sim)  # negative cos = reversed direction
        spacing_penalty = 1.0 - min(1.0, abs(np.log(max(spacing_ratio, 0.01))) / 2.0)
        coherence_score = direction_score * spacing_penalty

        # If coherence is already good enough, skip
        threshold = 1.0 - coherence_weight  # higher weight = stricter requirement
        if coherence_score >= threshold:
            continue

        # 4. Try to find better candidates for one of the pair members
        # Prefer to adjust the one with higher initial ΔE (less optimal original pick)
        if refined[i] and refined[j]:
            continue  # Both already touched, avoid cascade

        # Choose which to adjust: the one with larger ΔE (more room to improve)
        adjust_idx = j if new_de[j] >= new_de[i] else i
        anchor_idx = i if adjust_idx == j else j

        if refined[adjust_idx]:
            # Try the other one
            adjust_idx, anchor_idx = anchor_idx, adjust_idx
            if refined[adjust_idx]:
                continue

        # Direction from anchor to adjust in source space
        if adjust_idx == j:
            d_src_to_adjust = d_src  # i -> j
        else:
            d_src_to_adjust = -d_src  # j -> i
        d_src_to_adjust_norm = d_src_norm
        d_src_unit = d_src_to_adjust / d_src_to_adjust_norm

        # Get top-K candidates for the adjust target
        if topk_row_cache is not None:
            cand_indices, cand_des = topk_row_cache.get(adjust_idx)
        else:
            assert topk_indices is not None
            assert topk_distances is not None
            cand_indices = topk_indices[adjust_idx]
            cand_des = topk_distances[adjust_idx]
        cand_labs = all_lab[cand_indices]  # (top_k, 3)

        # Current anchor matched Lab
        anchor_lab = matched_lab[anchor_idx]

        # Evaluate each candidate's coherence with the anchor
        best_combined_score = -np.inf
        best_cand_pos = -1
        original_de = new_de[adjust_idx]

        for k_pos in range(top_k):
            cand_de = cand_des[k_pos]
            # Reject if ΔE penalty too large
            if cand_de - original_de > _NEIGHBOR_COHERENCE_MAX_DE_PENALTY:
                continue

            cand_lab = cand_labs[k_pos]
            # Direction from anchor to this candidate
            d_cand = cand_lab - anchor_lab
            d_cand_norm = _real_vector_norm(d_cand)
            if d_cand_norm < 1e-6:
                cand_cos = 0.0
            else:
                cand_cos = float(np.dot(d_src_unit, d_cand / d_cand_norm))

            cand_spacing = d_cand_norm / d_src_to_adjust_norm
            cand_spacing_penalty = 1.0 - min(1.0, abs(np.log(max(cand_spacing, 0.01))) / 2.0)
            cand_coherence = max(0.0, cand_cos) * cand_spacing_penalty

            # Combined score: coherence improvement vs ΔE cost
            de_penalty_fraction = (cand_de - original_de) / max(_NEIGHBOR_COHERENCE_MAX_DE_PENALTY, 1e-6)
            combined = cand_coherence - de_penalty_fraction * 0.5

            if combined > best_combined_score:
                best_combined_score = combined
                best_cand_pos = k_pos

        # Accept refinement only if it actually improves coherence
        if best_cand_pos >= 0 and best_combined_score > coherence_score:
            cand_row = int(cand_indices[best_cand_pos])
            new_matched_rgb[adjust_idx] = all_srgb[cand_row]
            new_recipes[adjust_idx] = user_mapping[all_recipes[cand_row]]
            new_de[adjust_idx] = cand_des[best_cand_pos]
            matched_lab[adjust_idx] = all_lab[cand_row]
            refined[adjust_idx] = True
            refinement_count += 1

    if refinement_count > 0:
        _log.info(
            "Neighbor coherence refined %d/%d targets (pairs=%d, weight=%.2f)",
            refinement_count, C_count, pair_count, coherence_weight,
            extra={
                "event": "neighbor_coherence_refined",
                "refined_count": refinement_count,
                "total_targets": C_count,
                "pair_count": pair_count,
                "coherence_weight": coherence_weight,
            },
        )

    return new_matched_rgb, new_recipes, new_de


# ---------------------------------------------------------------------------
# Cache data class
# ---------------------------------------------------------------------------


@dataclass
class MaterialSolverCache:
    """Loaded Lab-grid material-recipe cache (default 128³).
    已加载的 Lab 网格耗材配方缓存（默认 128³）。

    Attributes:
        lab_centers: (K, 3) float32 Lab bucket centers that were reached by
            at least one enumerated recipe. (被枚举触达的 Lab 网格中心)
        recipes: (K, N) uint8 best recipe per reached bucket, with column 0
            as the bottom layer. Indices refer to the canonically-ordered
            palette; callers must rebind to their own order via
            :meth:`reindex_to_user_order`. (每桶最优配方)
        achieved_srgb: (K, 3) uint8 predicted sRGB when the stored recipe is
            applied, used to compute ΔE to targets at lookup time.
            (配方实际达成的 sRGB)
        achieved_lab: (K, 3) float32 continuous-model Lab for the stored recipe.
            (配方连续模型 Lab)
        center_delta_e: (K,) float32 ΔE between bucket center and the stored
            recipe's achieved Lab. Diagnostic only — lookup ΔE is recomputed
            against the caller's target. (配方与桶心的 ΔE，仅诊断用)
        uniform_recipes: (M, N) uint8 pure-colour recipes (all layers the same
            material), one per palette entry. Always kept regardless of bucket
            collisions so every material's identity colour is queryable.
            (纯色配方，每种耗材一条，不受桶碰撞剔除)
        uniform_achieved_srgb: (M, 3) uint8 predicted sRGB for each pure-colour
            recipe. (每条纯色配方的预测 sRGB)
        metadata: JSON-serialisable dictionary with material descriptors,
            parameters, build stats, and timestamps. (元数据)
    """

    lab_centers: np.ndarray
    recipes: np.ndarray
    achieved_srgb: np.ndarray
    achieved_lab: np.ndarray
    center_delta_e: np.ndarray
    uniform_recipes: np.ndarray
    uniform_achieved_srgb: np.ndarray
    metadata: dict[str, Any]

    def __post_init__(self):
        """Backward-compat: legacy caches lack uniform fields, fill with empties.
        旧缓存兼容：缺 uniform 字段时回填空数组，下次重建自动升级。"""
        if self.uniform_recipes.size == 0 and self.uniform_recipes.ndim == 0:
            object.__setattr__(self, "uniform_recipes",
                               np.zeros((0, 0), dtype=np.uint8))
        if self.uniform_achieved_srgb.size == 0 and self.uniform_achieved_srgb.ndim == 0:
            object.__setattr__(self, "uniform_achieved_srgb",
                               np.zeros((0, 3), dtype=np.uint8))

    @property
    def layer_count(self) -> int:
        return int(self.metadata["layer_count"])

    @property
    def layer_height_mm(self) -> float:
        return float(self.metadata["layer_height_mm"])

    @property
    def substrate(self) -> str:
        return str(self.metadata["substrate"])

    @property
    def cache_id(self) -> str:
        """Return this opaque cache record ID.
        返回不透明缓存记录 ID。
        """
        return str(self.metadata["cache_id"])

    @property
    def palette_hash(self) -> str:
        """Expose the record ID through the historic public API name.
        通过历史公开 API 名返回记录 ID。
        """
        return self.cache_id

    @property
    def grid_resolution(self) -> int:
        return int(self.metadata.get("grid_resolution", DEFAULT_GRID_RESOLUTION))

    @property
    def mode(self) -> str:
        """Cache mode: ``"exact"`` (full formula table) or ``"bucketed"`` (Lab grid).
        缓存模式：精确穷举 / 分桶。"""
        return str(self.metadata.get("mode", "bucketed"))

    @property
    def is_exact(self) -> bool:
        """Whether this cache uses exact (exhaustive) lookup — no bucketing loss."""
        return self.mode == "exact"

    @property
    def valid_cell_count(self) -> int:
        return int(self.lab_centers.shape[0])

    def reindex_to_user_order(self, user_order: list[int]) -> np.ndarray:
        """Remap ``recipes`` (in canonical order) back to the caller's order.
        将规范顺序的 ``recipes`` 重映射回调用方的顺序。

        ``user_order`` is the list produced by
        :func:`canonical_palette_order(user_materials)`: for each canonical
        position ``c``, ``user_order[c]`` is the index into the caller's
        material list whose material equals the cache's canonical material
        at position ``c``.  The rebinding is therefore
        ``user_recipe = user_order[stored_canonical_recipe]``.
        """
        mapping = np.asarray(user_order, dtype=np.int32)
        return mapping[self.recipes]

    def lookup(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
        *,
        hue_weight: float = 0.0,
        neighbor_coherence: float = 0.5,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Find the best stored recipe for each target color.
        为每个目标颜色查找最优存档配方。

        The cache quantizes the exhaustive solver output onto a fixed Lab grid
        and keeps one representative recipe per occupied bucket. A naive
        nearest-bucket-center lookup can be suboptimal because a bucket's
        representative may not be the closest achievable colour to a specific
        target inside that bucket. To mitigate this, the lookup queries up to
        ``min(64, grid_resolution, valid_cell_count)`` nearest buckets per
        target, rehydrates their stored ``achieved_srgb``, converts those back
        to Lab, and selects the candidate with the smallest actual CIE76 ΔE to
        the target. This keeps the O(1)-style query cost while greatly reducing
        bucket-collision error when many recipes land in the same cell.

        缓存在构建时将穷举求解结果压缩到固定 Lab 网格，每个被占用的分桶只保留
        一条代表配方。直接取最近桶中心可能并不最优，因为该桶的代表色与桶内某
        个目标色之间仍可能有较大偏差。为缓解这种近似误差，本方法一次性查询
        ``min(64, grid_resolution, valid_cell_count)`` 个最近分桶，对各自存档
        的 ``achieved_srgb`` 重新计算相对目标色的 CIE76 ΔE，并选择 ΔE 最小的
        候选，在保持近常数级查询成本的同时明显降低桶内碰撞误差。

        Args:
            target_srgb (np.ndarray): ``(C, 3)`` uint8 unique target colours in
                sRGB. (目标 sRGB 唯一色)
            user_materials (list[MaterialParams]): The caller's ordered material
                list. Used to re-bind recipe indices from canonical storage
                order to the caller's order. (调用方耗材顺序)

        Returns:
            tuple[np.ndarray, np.ndarray, np.ndarray]: A triple of
                ``(matched_rgb, recipes_user_order, delta_e)``.

                - ``matched_rgb`` (``(C, 3)`` uint8): predicted sRGB for each
                  target, taken from the re-ranked best candidate bucket.
                - ``recipes_user_order`` (``(C, N)`` int32): recipes rewritten
                  in the caller's material order.
                - ``delta_e`` (``(C,)`` float64): CIE76 ΔE between target and
                  the selected achieved colour (not the bucket centre).

        Raises:
            ValueError: If ``target_srgb`` is not shaped ``(C, 3)``, the
                caller's material descriptors does not match the cache, or the
                cache contains no populated cells.
        """
        if target_srgb.ndim != 2 or target_srgb.shape[1] != 3:
            raise ValueError("target_srgb must be shaped (C, 3)")
        if target_srgb.shape[0] == 0:
            N = self.layer_count
            return (
                np.zeros((0, 3), dtype=np.uint8),
                np.zeros((0, N), dtype=np.int32),
                np.zeros((0,), dtype=np.float64),
            )
        if int(self.valid_cell_count) == 0:
            raise ValueError(
                "MaterialSolverCache has no populated cells; rebuild the cache "
                "before lookup. (缓存不含任何有效分桶，请先重建缓存)"
            )
        if describe_palette(user_materials) != self.metadata["canonical_materials"]:
            raise ValueError("User material descriptors do not match the cached palette")

        # ---- Exact mode: brute-force vectorised ΔE over full formula table ----
        # 精确模式：对全量配方表做向量化暴力 ΔE 搜索，零精度损失。
        if self.is_exact:
            return self._lookup_exact(
                target_srgb, user_materials,
                hue_weight=hue_weight,
                neighbor_coherence=neighbor_coherence,
            )

        # ---- Bucketed mode: KDTree nearest-bucket lookup ----
        _log.debug(
            "BUCKETED lookup: %d targets, grid=%d, cells=%d",
            target_srgb.shape[0], self.grid_resolution, self.valid_cell_count,
        )
        # Build KDTree over achieved Lab (lazily; expected small cost).
        tree = cKDTree(self.achieved_lab.astype(np.float64))
        target_lab = rgb_to_lab(target_srgb).astype(np.float64)
        query_k = min(64, int(self.valid_cell_count))
        _, nearest_idx = tree.query(target_lab, k=query_k)
        nearest_idx = np.asarray(nearest_idx)
        if nearest_idx.ndim == 1:
            # cKDTree squeezes the last dim when k == 1.
            nearest_idx = nearest_idx.reshape(-1, 1)
        candidate_lab = self.achieved_lab[nearest_idx].astype(np.float64)
        candidate_lab = candidate_lab.reshape(target_lab.shape[0], nearest_idx.shape[1], 3)
        candidate_delta_e = np.linalg.norm(
            candidate_lab - target_lab[:, None, :], axis=2
        )
        # --- Merge uniform (pure-colour) recipes into candidate pool ---
        # Pure-colour recipes are always pinned so every material's identity
        # colour stays queryable even when its recipe would otherwise be
        # culled by a bucket collision.
        # 将纯色配方并入候选池，确保每种耗材的本色可被查到。
        C_count = target_lab.shape[0]
        bucket_count = nearest_idx.shape[1]
        uniform_count = int(self.uniform_recipes.shape[0])
        if uniform_count > 0:
            uniform_lab = rgb_to_lab(self.uniform_achieved_srgb).astype(np.float64)
            uniform_lab_tiled = np.broadcast_to(
                uniform_lab[None, :, :], (C_count, uniform_count, 3)
            )
            uniform_de = np.linalg.norm(
                uniform_lab_tiled - target_lab[:, None, :], axis=2
            )
            candidate_lab = np.concatenate([candidate_lab, uniform_lab_tiled], axis=1)
            candidate_delta_e = np.concatenate([candidate_delta_e, uniform_de], axis=1)
        # --- Hue-aware reranking (when hue_weight > 0) ---
        # Uses LCH weighted distance to prefer same-hue candidates,
        # with a safety cap that falls back to CIE76-best when the
        # hue pick causes too large a ΔE penalty.
        # 色相保护 reranking：偏好同色相候选，但对超色域色设安全阈值。
        if hue_weight > 0.0:
            best_pos = _hue_aware_rerank(
                target_lab, candidate_lab, candidate_delta_e, hue_weight,
            )
        else:
            best_pos = np.argmin(candidate_delta_e, axis=1)
        row_index = np.arange(C_count, dtype=np.int64)
        best_de = candidate_delta_e[row_index, best_pos]

        # Split hits: bucket pool vs uniform (pure-colour) pool.
        is_uniform = best_pos >= bucket_count
        uniform_best_idx = best_pos - bucket_count  # valid only when is_uniform True
        bucket_best_pos = best_pos  # valid when is_uniform False

        matched_rgb = np.empty((C_count, 3), dtype=np.uint8)
        recipes_canonical = np.zeros((C_count, self.layer_count), dtype=np.uint8)
        user_order = canonical_palette_order(user_materials)
        mapping = np.asarray(user_order, dtype=np.int32)

        if np.any(is_uniform):
            uni_idx = np.where(is_uniform)[0]
            u_col = uniform_best_idx[uni_idx]
            matched_rgb[uni_idx] = self.uniform_achieved_srgb[u_col]
            recipes_canonical[uni_idx] = self.uniform_recipes[u_col]
        if np.any(~is_uniform):
            bkt_idx = np.where(~is_uniform)[0]
            b_pos = bucket_best_pos[bkt_idx]
            best_rows = nearest_idx[bkt_idx, b_pos]
            matched_rgb[bkt_idx] = self.achieved_srgb[best_rows]
            recipes_canonical[bkt_idx] = self.recipes[best_rows]

        recipes_user_order = mapping[recipes_canonical].astype(np.int32)
        return matched_rgb, recipes_user_order, best_de

    # ------------------------------------------------------------------
    # Exact-mode lookup (brute-force over full formula table)
    # ------------------------------------------------------------------

    def _lookup_exact(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
        *,
        hue_weight: float = 0.0,
        neighbor_coherence: float = 0.5,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Brute-force lookup against the full M^N formula table.
        对全量 M^N 配方表做暴力 ΔE 匹配，无精度损失。

        For each target colour, computes CIE76 ΔE to every stored recipe's
        achieved Lab, then selects the minimum. Since exact-mode caches have
        at most 100K entries, this vectorised broadcast is fast (~ms for
        typical image palettes of 8-64 unique colours).

        When ``neighbor_coherence > 0``, a post-processing step refines the
        initial best picks to preserve gradient direction and spacing between
        neighbouring target colours in Lab space, preventing the case where
        two close input colours diverge after matching.

        每个目标色与全部配方的 Lab 值做向量化 ΔE 计算后取最小值。精确模式
        上限 100K 条配方，对典型 8-64 种唯一色的图像仅耗时毫秒级。

        当 ``neighbor_coherence > 0`` 时，在初始最优匹配之后做邻近色一致性
        修正：确保相邻源色匹配后的梯度方向和间距比例不被扭曲。
        """
        from scipy.spatial.distance import cdist

        C_count = target_srgb.shape[0]
        N = self.layer_count
        target_lab = rgb_to_lab(target_srgb).astype(np.float64)

        # achieved_lab: (K, 3) — full formula table
        all_lab = self.achieved_lab.astype(np.float64)  # (K, 3)
        K = all_lab.shape[0]

        _log.info(
            "EXACT lookup: %d targets × %d recipes (brute-force ΔE, zero loss)",
            C_count, K,
            extra={
                "event": "material_solver_exact_lookup",
                "target_count": C_count,
                "recipe_count": K,
            },
        )

        # Use scipy cdist for efficient pairwise distance computation.
        # cdist uses optimised C code and is much faster than broadcast norm
        # for the (C, K) shape. For C=256 K=100K this runs in ~50ms vs ~900ms.
        # 使用 scipy cdist 高效计算成对距离——底层是 C 实现，远快于 broadcast norm。
        _CHUNK_C = 2048  # chunk targets to cap memory: 2048*100K*8B = 1.6 GB max
        best_idx = np.empty(C_count, dtype=np.int64)
        best_de = np.empty(C_count, dtype=np.float64)

        for c_start in range(0, C_count, _CHUNK_C):
            c_end = min(c_start + _CHUNK_C, C_count)
            chunk_target = target_lab[c_start:c_end]  # (chunk, 3)
            # cdist returns (chunk, K) distance matrix
            dist_matrix = cdist(chunk_target, all_lab, metric="euclidean")
            chunk_best_idx = np.argmin(dist_matrix, axis=1)
            chunk_best_de = dist_matrix[np.arange(c_end - c_start), chunk_best_idx]
            best_idx[c_start:c_end] = chunk_best_idx
            best_de[c_start:c_end] = chunk_best_de

        # --- Hue-aware reranking (optional) ---
        if hue_weight > 0.0:
            # For hue reranking, gather top-64 candidates per target via cdist
            top_k_for_hue = min(64, K)
            for c_start in range(0, C_count, _CHUNK_C):
                c_end = min(c_start + _CHUNK_C, C_count)
                chunk_target = target_lab[c_start:c_end]
                dist_matrix = cdist(chunk_target, all_lab, metric="euclidean")
                # Get top-k indices per row
                chunk_size = c_end - c_start
                if top_k_for_hue >= K:
                    # All recipes fit; no partial sort needed.
                    topk_idx = np.broadcast_to(
                        np.arange(K, dtype=np.intp)[None, :], (chunk_size, K)
                    ).copy()
                else:
                    topk_idx = np.argpartition(dist_matrix, top_k_for_hue, axis=1)[:, :top_k_for_hue]
                row_idx = np.arange(c_end - c_start)[:, None]
                topk_lab = all_lab[topk_idx]  # (chunk, top_k, 3)
                topk_de = dist_matrix[row_idx, topk_idx]  # (chunk, top_k)
                reranked_pos = _hue_aware_rerank(
                    chunk_target, topk_lab, topk_de, hue_weight
                )
                for i, pos in enumerate(reranked_pos):
                    c_global = c_start + i
                    best_idx[c_global] = topk_idx[i, pos]
                    best_de[c_global] = topk_de[i, pos]

        # --- Also check uniform (pure-colour) recipes ---
        uniform_count = int(self.uniform_recipes.shape[0])
        if uniform_count > 0:
            uniform_lab = rgb_to_lab(self.uniform_achieved_srgb).astype(np.float64)
            uniform_de = np.linalg.norm(
                target_lab[:, None, :] - uniform_lab[None, :, :], axis=2
            )  # (C, M)
            uniform_best_per_c = np.min(uniform_de, axis=1)  # (C,)
            uniform_best_idx_per_c = np.argmin(uniform_de, axis=1)  # (C,)
            # Replace where uniform is better
            improved = uniform_best_per_c < best_de
            if np.any(improved):
                best_de[improved] = uniform_best_per_c[improved]
                # Mark with negative index to distinguish from formula table
                best_idx[improved] = -(uniform_best_idx_per_c[improved] + 1)

        # --- Assemble output ---
        user_order = canonical_palette_order(user_materials)
        mapping = np.asarray(user_order, dtype=np.int32)

        matched_rgb = np.empty((C_count, 3), dtype=np.uint8)
        recipes_canonical = np.zeros((C_count, N), dtype=np.uint8)

        is_uniform = best_idx < 0
        if np.any(is_uniform):
            uni_idx = np.where(is_uniform)[0]
            u_col = -(best_idx[uni_idx] + 1).astype(np.int64)
            matched_rgb[uni_idx] = self.uniform_achieved_srgb[u_col]
            recipes_canonical[uni_idx] = self.uniform_recipes[u_col]
        if np.any(~is_uniform):
            bkt_idx = np.where(~is_uniform)[0]
            rows = best_idx[bkt_idx].astype(np.int64)
            matched_rgb[bkt_idx] = self.achieved_srgb[rows]
            recipes_canonical[bkt_idx] = self.recipes[rows]

        recipes_user_order = mapping[recipes_canonical].astype(np.int32)

        # --- Neighbor coherence post-processing ---
        # When enabled, refine picks so that close source colours map to
        # results that preserve relative direction and spacing in Lab.
        # 邻近色一致性修正：保持相近源色匹配后的梯度方向与间距比例。
        if neighbor_coherence > 0.0 and C_count >= 2:
            matched_rgb, recipes_user_order, best_de = _neighbor_coherence_refine(
                target_lab=target_lab,
                matched_rgb=matched_rgb,
                recipes_user_order=recipes_user_order,
                delta_e=best_de,
                all_lab=all_lab,
                all_srgb=self.achieved_srgb,
                all_recipes=self.recipes,
                user_mapping=mapping,
                coherence_weight=neighbor_coherence,
                layer_count=N,
                uniform_lab=rgb_to_lab(self.uniform_achieved_srgb).astype(np.float64) if uniform_count > 0 else None,
                uniform_srgb=self.uniform_achieved_srgb if uniform_count > 0 else None,
                uniform_recipes=self.uniform_recipes if uniform_count > 0 else None,
            )

        return matched_rgb, recipes_user_order, best_de

    def lookup_top_k(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
        *,
        top_k: int = DEFAULT_SUGGEST_TOP_K,
        min_spacing: float = DEFAULT_SUGGEST_MIN_SPACING,
    ) -> list[ColorSuggestion]:
        """Return the ``top_k`` cached recipes closest in Lab to one target.
        返回 Lab 空间中最接近单一目标色的 ``top_k`` 条缓存配方。

        The cache stores one recipe per reached bucket centre, so the entire
        enumerated gamut is already deduplicated at the grid resolution. A
        ``cKDTree`` query picks the nearest-cell neighbours, then a greedy
        ``min_spacing`` filter enforces perceptually distinct suggestions.

        Args:
            target_srgb: (3,) uint8 target colour in sRGB. (目标 sRGB)
            user_materials: Caller's ordered material list (for recipe
                rebinding). (调用方耗材顺序)
            top_k: Maximum number of suggestions to return. (返回候选数上限)
            min_spacing: Minimum Lab ΔE between returned candidates.
                (候选间最小 Lab ΔE)

        Returns:
            List of :class:`ColorSuggestion` ordered by ΔE ascending. Recipe
            indices refer to ``user_materials`` (not the canonical cache order).
            (按 ΔE 升序的候选列表；``recipe`` 使用调用方耗材索引)

        Raises:
            ValueError: ``target_srgb`` shape is wrong or ``top_k <= 0`` or
                the caller's material descriptors does not match the cache.
        """
        target_srgb = np.asarray(target_srgb, dtype=np.uint8)
        if target_srgb.shape != (3,):
            raise ValueError(
                f"target_srgb must be shaped (3,), got {target_srgb.shape}"
            )
        if top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")
        if min_spacing < 0.0:
            raise ValueError(f"min_spacing must be non-negative, got {min_spacing}")
        if describe_palette(user_materials) != self.metadata["canonical_materials"]:
            raise ValueError("User material descriptors do not match the cached palette")
        if self.lab_centers.shape[0] == 0 and self.uniform_recipes.shape[0] == 0:
            return []

        target_lab = rgb_to_lab(target_srgb.reshape(1, 3))[0].astype(np.float64)
        oversample = max(1, int(top_k) * 4)
        query_k = min(oversample, int(self.achieved_lab.shape[0]))

        # --- Bucket pool ---
        bucket_k = query_k
        bucket_lab = np.zeros((0, 3), dtype=np.float64)
        bucket_srgb = np.zeros((0, 3), dtype=np.uint8)
        bucket_delta_e = np.zeros(0, dtype=np.float64)
        bucket_cache_rows = np.zeros(0, dtype=np.int64)
        is_bucket = np.zeros(0, dtype=bool)

        if bucket_k > 0 and self.achieved_lab.shape[0] > 0:
            tree = cKDTree(self.achieved_lab.astype(np.float64))
            _, nearest_idx = tree.query(target_lab, k=bucket_k)
            nearest_idx = np.atleast_1d(nearest_idx).astype(np.int64)
            bucket_srgb = self.achieved_srgb[nearest_idx]
            bucket_lab = self.achieved_lab[nearest_idx].astype(np.float64)
            bucket_delta_e = np.linalg.norm(bucket_lab - target_lab, axis=1)
            bucket_cache_rows = nearest_idx
            is_bucket = np.ones(int(nearest_idx.shape[0]), dtype=bool)

        # --- Uniform (pure-colour) pool ---
        uniform_count = int(self.uniform_recipes.shape[0])
        uniform_lab = np.zeros((0, 3), dtype=np.float64)
        uniform_srgb = np.zeros((0, 3), dtype=np.uint8)
        uniform_delta_e = np.zeros(0, dtype=np.float64)
        uniform_rows = np.zeros(0, dtype=np.int64)
        is_uniform = np.zeros(0, dtype=bool)

        if uniform_count > 0:
            uniform_srgb = self.uniform_achieved_srgb
            uniform_lab = rgb_to_lab(uniform_srgb).astype(np.float64)
            uniform_delta_e = np.linalg.norm(uniform_lab - target_lab, axis=1)
            uniform_rows = np.arange(uniform_count, dtype=np.int64)
            is_uniform = np.ones(uniform_count, dtype=bool)

        # --- Merge pools ---
        all_lab = np.concatenate([bucket_lab, uniform_lab], axis=0)
        all_srgb = np.concatenate([bucket_srgb, uniform_srgb], axis=0)
        all_de = np.concatenate([bucket_delta_e, uniform_delta_e], axis=0)
        all_is_uniform = np.concatenate([is_bucket, is_uniform], axis=0)

        # Sort ascending by ΔE before the greedy spacing filter.
        sort_order = np.argsort(all_de, kind="stable")
        sorted_lab = all_lab[sort_order]
        sorted_srgb = all_srgb[sort_order]
        sorted_de = all_de[sort_order]
        sorted_is_uniform = all_is_uniform[sort_order]
        # Row index into either bucket_cache_rows or uniform_rows, keyed by is_uniform.
        sorted_uni_rows = np.concatenate(
            [np.zeros_like(bucket_cache_rows, dtype=np.int64), uniform_rows], axis=0
        )[sort_order]
        sorted_bkt_rows = np.concatenate(
            [bucket_cache_rows, np.zeros(uniform_count, dtype=np.int64)], axis=0
        )[sort_order]

        kept_idx = _greedy_lab_spacing_dedup(
            sorted_lab, min_spacing=min_spacing, limit=int(top_k)
        )
        if kept_idx.size == 0:
            return []

        user_order = canonical_palette_order(user_materials)
        mapping = np.asarray(user_order, dtype=np.int32)
        suggestions: list[ColorSuggestion] = []
        for i in kept_idx:
            if sorted_is_uniform[i]:
                recipe = self.uniform_recipes[sorted_uni_rows[i]]
            else:
                recipe = self.recipes[sorted_bkt_rows[i]]
            suggestions.append(ColorSuggestion(
                matched_rgb=sorted_srgb[i].copy(),
                recipe=mapping[recipe].astype(np.int32, copy=True),
                delta_e=float(sorted_de[i]),
            ))
        return suggestions

    def lookup_candidates(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
        *,
        k: int = 16,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return top-k candidates per target for palette-aware reranking.
        为每个目标色返回 top-k 候选，供保形重排使用。

        Merges bucket-pool and uniform-pool candidates, sorts per-target by
        ΔE ascending, and returns the top-k slice. Recipes are returned in
        the caller's material order.

        合并分桶池和纯色池候选，按每个目标色的 ΔE 升序排列，取 top-k。
        配方返回调用方耗材顺序。

        Args:
            target_srgb: ``(C, 3)`` uint8 target colours in sRGB.
                (目标 sRGB 唯一色)
            user_materials: The caller's ordered material list.
                (调用方耗材顺序)
            k: Number of candidates per target. (每色候选数)

        Returns:
            Tuple of four arrays:

            - ``cands_rgb``: ``(C, K, 3)`` uint8 — each candidate's sRGB.
            - ``cands_lab``: ``(C, K, 3)`` float64 — each candidate's Lab.
            - ``cands_recipes``: ``(C, K, N)`` int32 — recipes in user order.
            - ``cands_delta_e``: ``(C, K)`` float64 — CIE76 ΔE per candidate.

            Where ``K = min(k, available_candidates)``.

        Raises:
            ValueError: Shape or material descriptor mismatch.
        """
        if target_srgb.ndim != 2 or target_srgb.shape[1] != 3:
            raise ValueError("target_srgb must be shaped (C, 3)")
        C_count = target_srgb.shape[0]
        N = self.layer_count
        if C_count == 0:
            return (
                np.zeros((0, 0, 3), dtype=np.uint8),
                np.zeros((0, 0, 3), dtype=np.float64),
                np.zeros((0, 0, N), dtype=np.int32),
                np.zeros((0, 0), dtype=np.float64),
            )
        if int(self.valid_cell_count) == 0:
            raise ValueError(
                "MaterialSolverCache has no populated cells; rebuild the cache "
                "before lookup_candidates. (缓存不含任何有效分桶)"
            )
        if describe_palette(user_materials) != self.metadata["canonical_materials"]:
            raise ValueError("User material descriptors do not match the cached palette")

        # Query more from KDTree than k to have room after merging uniform pool.
        tree = cKDTree(self.achieved_lab.astype(np.float64))
        target_lab = rgb_to_lab(target_srgb).astype(np.float64)
        query_k = min(max(k, 64), int(self.valid_cell_count))
        _, nearest_idx = tree.query(target_lab, k=query_k)
        nearest_idx = np.asarray(nearest_idx)
        if nearest_idx.ndim == 1:
            nearest_idx = nearest_idx.reshape(-1, 1)

        bucket_count = nearest_idx.shape[1]
        candidate_lab = self.achieved_lab[nearest_idx].astype(np.float64)
        candidate_lab = candidate_lab.reshape(C_count, bucket_count, 3)
        candidate_srgb = self.achieved_srgb[nearest_idx].reshape(C_count, bucket_count, 3)
        candidate_delta_e = np.linalg.norm(
            candidate_lab - target_lab[:, None, :], axis=2
        )

        # Merge uniform (pure-colour) pool.
        uniform_count = int(self.uniform_recipes.shape[0])
        if uniform_count > 0:
            uniform_lab = rgb_to_lab(self.uniform_achieved_srgb).astype(np.float64)
            uniform_lab_tiled = np.broadcast_to(
                uniform_lab[None, :, :], (C_count, uniform_count, 3)
            )
            uniform_srgb_tiled = np.broadcast_to(
                self.uniform_achieved_srgb[None, :, :], (C_count, uniform_count, 3)
            )
            uniform_de = np.linalg.norm(
                uniform_lab_tiled - target_lab[:, None, :], axis=2
            )
            candidate_lab = np.concatenate(
                [candidate_lab, uniform_lab_tiled], axis=1
            )
            candidate_srgb = np.concatenate(
                [candidate_srgb, np.ascontiguousarray(uniform_srgb_tiled)], axis=1
            )
            candidate_delta_e = np.concatenate(
                [candidate_delta_e, uniform_de], axis=1
            )

        # Sort per-target by ΔE and take top-k.
        total_pool = candidate_delta_e.shape[1]
        actual_k = min(k, total_pool)
        sort_idx = np.argsort(candidate_delta_e, axis=1)[:, :actual_k]  # (C, K)

        row_idx = np.arange(C_count)[:, None]
        out_lab = candidate_lab[row_idx, sort_idx]           # (C, K, 3)
        out_srgb = candidate_srgb[row_idx, sort_idx]         # (C, K, 3)
        out_de = candidate_delta_e[row_idx, sort_idx]        # (C, K)

        # Build recipes for selected candidates.
        user_order = canonical_palette_order(user_materials)
        mapping = np.asarray(user_order, dtype=np.int32)
        out_recipes = np.zeros((C_count, actual_k, N), dtype=np.int32)

        for c in range(C_count):
            for ki in range(actual_k):
                pool_col = int(sort_idx[c, ki])
                if pool_col < bucket_count:
                    cache_row = int(nearest_idx[c, pool_col])
                    recipe_canonical = self.recipes[cache_row]
                else:
                    uni_idx = pool_col - bucket_count
                    recipe_canonical = self.uniform_recipes[uni_idx]
                out_recipes[c, ki] = mapping[recipe_canonical]

        return (
            out_srgb.astype(np.uint8),
            out_lab,
            out_recipes,
            out_de,
        )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _lab_to_bucket_index(
    lab: np.ndarray,
    grid_resolution: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Map an ``(N, 3)`` Lab array to (flat_bucket_idx, bucket_center).
    将 ``(N, 3)`` 的 Lab 数组映射为 (桶索引, 桶心 Lab)。
    """
    # L in [0, 100], a/b in [-128, 127]. Clip to valid range before binning.
    L = np.clip(lab[:, 0], 0.0, 100.0)
    a = np.clip(lab[:, 1], -128.0, 127.0)
    b = np.clip(lab[:, 2], -128.0, 127.0)
    # Quantize each axis into [0, grid_resolution - 1].
    L_step = 100.0 / grid_resolution
    ab_step = 256.0 / grid_resolution
    L_idx = np.clip((L / L_step).astype(np.int32), 0, grid_resolution - 1)
    a_idx = np.clip(((a + 128.0) / ab_step).astype(np.int32), 0, grid_resolution - 1)
    b_idx = np.clip(((b + 128.0) / ab_step).astype(np.int32), 0, grid_resolution - 1)
    flat_idx = (
        L_idx * (grid_resolution * grid_resolution)
        + a_idx * grid_resolution
        + b_idx
    )
    # Bucket center = lower bound + half-step (so the bucket's representative
    # point is at the cell's geometric centre).
    center = np.empty_like(lab, dtype=np.float64)
    center[:, 0] = L_idx * L_step + L_step * 0.5
    center[:, 1] = a_idx * ab_step + ab_step * 0.5 - 128.0
    center[:, 2] = b_idx * ab_step + ab_step * 0.5 - 128.0
    return flat_idx, center


def _linear_to_lab(linear_rgb: np.ndarray) -> np.ndarray:
    srgb = linear_to_srgb_float(linear_rgb).astype(np.float32, copy=False)
    lab = cv2.cvtColor(srgb.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)
    return lab.reshape(-1, 3).astype(np.float64, copy=False)


def _pack_srgb(srgb: np.ndarray) -> np.ndarray:
    values = srgb.astype(np.uint64, copy=False)
    return (values[:, 0] << 16) | (values[:, 1] << 8) | values[:, 2]


def _groupby_argmin(
    bucket_idx: np.ndarray,
    delta: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-bucket argmin over (bucket_idx, delta) without pandas.
    不依赖 pandas 的分桶 argmin。

    Returns (unique_buckets, row_indices_into_original_arrays) where
    ``row_indices[i]`` is the index of the minimum-delta row for
    ``unique_buckets[i]``.
    """
    # Lexsort: primary bucket (ascending), secondary delta (ascending).
    # The first occurrence of each bucket in the sorted order has the min delta.
    order = np.lexsort((delta, bucket_idx))
    sorted_buckets = bucket_idx[order]
    # First-occurrence mask: True where bucket differs from previous.
    if sorted_buckets.size == 0:
        return (
            np.zeros(0, dtype=bucket_idx.dtype),
            np.zeros(0, dtype=np.int64),
        )
    first_mask = np.empty(sorted_buckets.shape, dtype=bool)
    first_mask[0] = True
    np.not_equal(sorted_buckets[1:], sorted_buckets[:-1], out=first_mask[1:])
    unique_buckets = sorted_buckets[first_mask]
    row_indices = order[first_mask]
    return unique_buckets, row_indices


def _compute_uniform_recipes(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute pure-colour recipes (all N layers the same material) for each palette entry.
    计算调色板每种耗材的纯色配方（N 层全用同一种耗材）和对应的预测 sRGB。

    Uses the Beer-Lambert forward model to predict the final colour of a
    ``[i, i, ..., i]`` stack for each material index ``i``, keeping the
        recipes in established canonical order so they align with the
    rest of the cache arrays.

    对每种耗材 ``i``，用 Beer-Lambert 前向模型计算 N 层同样耗材叠加后的颜色，
    配方按既有规范顺序排列以对齐缓存其它数组。

    Args:
        materials: Palette in canonical order. (规范序耗材列表)
        layer_count: Number of layers. (层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)

    Returns:
        uniform_recipes: ``(M, N)`` uint8, row ``i`` is ``[i, i, ..., i]``.
            (纯色配方矩阵)
        uniform_achieved_srgb: ``(M, 3)`` uint8 predicted sRGB per pure recipe.
            (纯色配方预测 sRGB)
    """
    M = len(materials)
    uniform_recipes = np.empty((M, layer_count), dtype=np.uint8)
    for i in range(M):
        uniform_recipes[i, :] = i  # [i, i, ..., i]

    substrate_linear = (
        np.zeros(3, dtype=np.float64)
        if substrate == "black"
        else np.ones(3, dtype=np.float64)
    )
    uniform_achieved_srgb = np.empty((M, 3), dtype=np.uint8)
    for i in range(M):
        recipe = np.full(layer_count, i, dtype=np.int32)
        linear = forward_model(recipe, materials, layer_height_mm, substrate_linear)
        uniform_achieved_srgb[i] = linear_to_srgb_uint8(linear.reshape(1, 3))[0]

    return uniform_recipes, uniform_achieved_srgb


def _build_exact_cache(
    canonical_materials: list[MaterialParams],
    canonical_order: list[int],
    cache_id: str,
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    *,
    progress_callback: Callable[[float, dict[str, Any]], None] | None = None,
    start_time: float,
) -> MaterialSolverCache:
    """Build an exact (full-enumeration) cache with zero bucketing loss.
    构建精确穷举缓存：存储全量 M^N 配方表，查询时暴力 ΔE 匹配。

    Stores every single recipe and its predicted colour so that lookup can
    do a brute-force nearest-neighbour search with guaranteed global
    optimality. Only called when M^N ≤ 100K (e.g. 10 colours × 5 layers).

    全量存储每条配方及其预测颜色，查询时暴力搜索保证全局最优。
    仅当 M^N ≤ 100K 时被调用（如 10 色 5 层）。
    """
    M = len(canonical_materials)
    affines = _compute_material_affines(canonical_materials, layer_height_mm)
    substrate_linear = (
        np.zeros(3, dtype=np.float64)
        if substrate == "black"
        else np.ones(3, dtype=np.float64)
    )

    top_depth = (layer_count + 1) // 2
    bottom_depth = layer_count - top_depth

    # Enumerate halves via MITM decomposition (reuse existing infrastructure).
    bot_alpha, bot_beta, bot_recipes = _enumerate_cumulative_affines(
        affines, bottom_depth
    )
    bot_colors = bot_alpha * substrate_linear + bot_beta  # (K_bot, 3)
    top_alpha, top_beta, top_recipes = _enumerate_cumulative_affines(
        affines, top_depth
    )
    K_bot = bot_colors.shape[0]
    K_top = top_alpha.shape[0]
    total_combinations = int(K_top) * int(K_bot)

    # Pre-allocate output arrays for all M^N recipes.
    all_recipes = np.empty((total_combinations, layer_count), dtype=np.int8)
    all_srgb = np.empty((total_combinations, 3), dtype=np.uint8)
    all_lab = np.empty((total_combinations, 3), dtype=np.float32)

    # Process in chunks to keep memory comfortable.
    per_row_bytes = K_bot * 24
    chunk_size = max(1, min(K_top, _CHUNK_TARGET_BYTES // max(per_row_bytes, 1)))
    num_chunks = (K_top + chunk_size - 1) // chunk_size
    write_offset = 0

    for chunk_idx, chunk_start in enumerate(range(0, K_top, chunk_size)):
        chunk_end = min(chunk_start + chunk_size, K_top)
        sub = chunk_end - chunk_start
        chunk_alpha = top_alpha[chunk_start:chunk_end]
        chunk_beta = top_beta[chunk_start:chunk_end]
        chunk_recipes_top = top_recipes[chunk_start:chunk_end]

        # final_linear: (sub, K_bot, 3)
        final_linear = (
            chunk_alpha[:, None, :] * bot_colors[None, :, :]
            + chunk_beta[:, None, :]
        )
        flat_linear = final_linear.reshape(-1, 3)  # (sub*K_bot, 3)
        flat_srgb = linear_to_srgb_uint8(flat_linear)
        flat_lab = _linear_to_lab(flat_linear).astype(np.float32)  # (sub*K_bot, 3)

        # Build recipes: bottom-then-top column order.
        chunk_count = sub * K_bot
        chunk_recipes = np.empty((chunk_count, layer_count), dtype=np.int8)
        # Expand: top_idx = flat_row // K_bot, bot_idx = flat_row % K_bot
        top_idx = np.repeat(np.arange(sub), K_bot)
        bot_idx = np.tile(np.arange(K_bot), sub)
        if bottom_depth > 0:
            chunk_recipes[:, :bottom_depth] = bot_recipes[bot_idx]
        if top_depth > 0:
            chunk_recipes[:, bottom_depth:] = chunk_recipes_top[top_idx]

        # Write to output arrays.
        all_recipes[write_offset:write_offset + chunk_count] = chunk_recipes
        all_srgb[write_offset:write_offset + chunk_count] = flat_srgb
        all_lab[write_offset:write_offset + chunk_count] = flat_lab
        write_offset += chunk_count

        if progress_callback is not None:
            fraction = (chunk_idx + 1) / max(num_chunks, 1)
            progress_callback(
                fraction,
                {
                    "chunk_index": chunk_idx + 1,
                    "total_chunks": num_chunks,
                    "valid_bucket_count": write_offset,
                    "elapsed_seconds": time.time() - start_time,
                },
            )

    # Trim in case of rounding (shouldn't happen, but defensive).
    all_recipes = all_recipes[:write_offset]
    all_srgb = all_srgb[:write_offset]
    all_lab = all_lab[:write_offset]

    # center_delta_e: not meaningful for exact mode, but keep shape contract.
    # Store zeros since there's no bucket centre concept.
    center_delta_e = np.zeros(write_offset, dtype=np.float32)

    build_time = time.time() - start_time

    metadata = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "color_precision": "continuous_lab",
        "mode": "exact",
        "cache_id": cache_id,
        "solver_version": CACHE_SOLVER_VERSION,
        "canonical_materials": describe_palette(canonical_materials),
        "layer_count": int(layer_count),
        "layer_height_mm": float(layer_height_mm),
        "substrate": substrate,
        "grid_resolution": 0,  # Not applicable for exact mode
        "total_combinations": total_combinations,
        "valid_cell_count": write_offset,
        "total_cell_count": total_combinations,
        "mean_delta_e": 0.0,  # Exact mode has no bucketing error
        "max_delta_e": 0.0,
        "build_time_seconds": build_time,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    _log.info(
        "Built EXACT material solver cache: palette=%s M=%d N=%d "
        "combinations=%d build=%.1fs",
        cache_id,
        M,
        layer_count,
        total_combinations,
        build_time,
        extra={
            "event": "material_solver_cache_built",
            "cache_id": cache_id,
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "mode": "exact",
            "total_combinations": total_combinations,
            "valid_cell_count": write_offset,
            "build_time_seconds": build_time,
        },
    )

    # Pure-colour recipes (always pinned).
    uniform_recipes, uniform_achieved_srgb = _compute_uniform_recipes(
        canonical_materials, layer_count, layer_height_mm, substrate,
    )
    metadata["uniform_recipe_count"] = int(uniform_recipes.shape[0])

    return MaterialSolverCache(
        lab_centers=all_lab,  # In exact mode, these are achieved Labs (not bucket centers)
        recipes=all_recipes,
        achieved_srgb=all_srgb,
        achieved_lab=all_lab,
        center_delta_e=center_delta_e,
        uniform_recipes=uniform_recipes,
        uniform_achieved_srgb=uniform_achieved_srgb,
        metadata=metadata,
    )


def build_material_solver_cache(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    progress_callback: Callable[[float, dict[str, Any]], None] | None = None,
    mode: str = "auto",
) -> MaterialSolverCache:
    """Exhaustively enumerate every recipe and build a lookup cache.
    穷举所有配方并构建查询缓存。

    The build pass uses the MITM decomposition from
    :mod:`core.material_color_solver`: the top and bottom halves are
    enumerated into cumulative-affine tables once, then combined chunk-by-chunk
    to produce every ``M**N`` final color.

    When ``mode="auto"`` (default) and the palette is small enough (M≤10,
    N≤5, M^N≤100K), the builder stores the *complete* formula table without
    bucketing — guaranteeing zero precision loss at lookup time. Larger
    palettes fall back to Lab-grid bucketing. Pass ``mode="bucketed"`` to
    force the traditional bucketing path regardless of palette size.

    当 ``mode="auto"``（默认）且调色板足够小（M≤10, N≤5, M^N≤100K）时，
    构建器存储完整配方表，查询时零精度损失。更大的调色板回退到 Lab 网格分桶。
    传 ``mode="bucketed"`` 可强制走分桶路径。

    Args:
        materials: Palette used for enumeration. The solver internally reorders
            to established canonical order and stores recipes in that
            order; :meth:`MaterialSolverCache.lookup` rebinds indices to the
            caller's order at query time. (枚举用耗材列表)
        layer_count: Number of layers (5-10). (层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        grid_resolution: Lab grid cells per axis. Default 128.
            Ignored in exact mode. (Lab 网格分辨率，精确模式下忽略)
        progress_callback: Optional callback invoked as
            ``cb(progress_fraction, info)`` where ``progress_fraction`` is in
            ``[0, 1]`` and ``info`` carries build stats. (进度回调)
        mode: ``"auto"`` (default), ``"exact"``, or ``"bucketed"``.
            ``"auto"`` chooses exact when eligible, else bucketed.
            (模式选择：auto/exact/bucketed)

    Returns:
        MaterialSolverCache with populated arrays and metadata.
    """
    if layer_count < MIN_LAYER_COUNT or layer_count > MAX_LAYER_COUNT:
        raise ValueError(
            f"layer_count must be {MIN_LAYER_COUNT}-{MAX_LAYER_COUNT}, got {layer_count}"
        )
    if not materials:
        raise ValueError("At least one material must be provided")
    if layer_height_mm not in ALLOWED_LAYER_HEIGHTS_MM:
        raise ValueError(
            f"layer_height_mm must be one of {ALLOWED_LAYER_HEIGHTS_MM}, got {layer_height_mm}"
        )
    if substrate not in ("white", "black"):
        raise ValueError(f"substrate must be 'white' or 'black', got {substrate!r}")
    if grid_resolution < 8 or grid_resolution > 2048:
        raise ValueError(
            f"grid_resolution must be in [8, 2048], got {grid_resolution}"
        )

    start_time = time.time()

    # Re-order materials to canonical order for storage.
    canonical_order = canonical_palette_order(materials)
    canonical_materials = [materials[i] for i in canonical_order]
    cache_id = uuid.uuid4().hex

    # ---- Exact mode shortcut: M≤10 and N≤5 → store full formula table ----
    # 精确模式快速路径：小规模调色板直接存全量配方表，零精度损失。
    _use_exact = (
        mode == "exact"
        or (mode == "auto" and _is_exact_mode_eligible(len(materials), layer_count))
    )
    if _use_exact:
        return _build_exact_cache(
            canonical_materials,
            canonical_order,
            cache_id,
            layer_count,
            layer_height_mm,
            substrate,
            progress_callback=progress_callback,
            start_time=start_time,
        )

    affines = _compute_material_affines(canonical_materials, layer_height_mm)
    substrate_linear = (
        np.zeros(3, dtype=np.float64)
        if substrate == "black"
        else np.ones(3, dtype=np.float64)
    )

    top_depth = (layer_count + 1) // 2
    bottom_depth = layer_count - top_depth

    # Enumerate halves.
    bot_alpha, bot_beta, bot_recipes = _enumerate_cumulative_affines(
        affines, bottom_depth
    )
    bot_colors = bot_alpha * substrate_linear + bot_beta          # (K_bot, 3)
    top_alpha, top_beta, top_recipes = _enumerate_cumulative_affines(
        affines, top_depth
    )
    K_bot = bot_colors.shape[0]
    K_top = top_alpha.shape[0]
    total_combinations = int(K_top) * int(K_bot)

    # Sparse per-bucket state.
    # ``best`` maps (flat_bucket_idx, srgb_key) -> (delta, recipe_int8, srgb_u8, lab_f64, center_f64).
    # Only buckets that have actually been reached by some recipe consume
    # memory, so the build cost scales with ``min(total_combinations,
    # valid_cell_count)`` instead of ``grid_resolution ** 3``. This is what
    # makes 1024 / 2048 tiers physically feasible: at 8 mats × 5 layers the
    # dict holds at most 32 768 entries (~2.5 MB) regardless of the grid
    # tier, while the dense equivalent at 2048 would have demanded ~560 GB.
    # 稀疏每桶状态：``best`` 仅为真正命中的桶分配空间，因此构建期内存
    # 取决于 ``min(总配方数, 有效桶数)`` 而非 ``grid_resolution ** 3``，
    # 这是 1024/2048 档真正可用的关键。
    total_buckets = grid_resolution ** 3
    best: dict[
        tuple[int, int],
        tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    ] = {}

    # Chunk tops so each temporary matrix stays at the existing local block size.
    # 顶/底分桶分块，单块 (sub × K_bot × 24B) 受既有局部块大小限制。
    per_row_bytes = K_bot * 24
    chunk_size = max(1, min(K_top, _CHUNK_TARGET_BYTES // max(per_row_bytes, 1)))
    num_chunks = (K_top + chunk_size - 1) // chunk_size

    for chunk_idx, chunk_start in enumerate(range(0, K_top, chunk_size)):
        chunk_end = min(chunk_start + chunk_size, K_top)
        sub = chunk_end - chunk_start
        chunk_alpha = top_alpha[chunk_start:chunk_end]             # (sub, 3)
        chunk_beta = top_beta[chunk_start:chunk_end]               # (sub, 3)
        chunk_recipes_top = top_recipes[chunk_start:chunk_end]     # (sub, top_depth)

        # final_linear: (sub, K_bot, 3).
        final_linear = (
            chunk_alpha[:, None, :] * bot_colors[None, :, :]
            + chunk_beta[:, None, :]
        )
        flat_linear = final_linear.reshape(-1, 3)                  # (sub*K_bot, 3)
        flat_srgb = linear_to_srgb_uint8(flat_linear)
        flat_lab = _linear_to_lab(flat_linear)                     # (sub*K_bot, 3)

        bucket_idx, bucket_center = _lab_to_bucket_index(flat_lab, grid_resolution)
        visible_bucket_idx = (
            bucket_idx.astype(np.uint64) << np.uint64(24)
        ) | _pack_srgb(flat_srgb)
        delta_to_center = np.linalg.norm(flat_lab - bucket_center, axis=1)

        # Find min-delta row per bucket within this chunk.
        unique_visible_buckets, row_indices = _groupby_argmin(
            visible_bucket_idx, delta_to_center
        )
        if unique_visible_buckets.size == 0:
            continue

        chunk_best_deltas = delta_to_center[row_indices]
        chunk_best_srgb = flat_srgb[row_indices]
        chunk_best_lab = flat_lab[row_indices]
        chunk_best_centers = bucket_center[row_indices]

        # Rebuild recipes for these rows. Each row index is a flat index into
        # (sub, K_bot): top_i = row // K_bot, bot_i = row % K_bot.
        # 还原配方：每个 row 在 (sub, K_bot) 中的二维位置。
        top_idx_in_chunk = row_indices // K_bot
        bot_idx_in_chunk = row_indices % K_bot
        chunk_bot_recipes = bot_recipes[bot_idx_in_chunk]          # (K_hit, bottom_depth)
        chunk_top_recipes = chunk_recipes_top[top_idx_in_chunk]    # (K_hit, top_depth)
        # Stack into a single (K_hit, layer_count) recipe matrix in canonical
        # bottom-then-top column order so the on-disk layout stays identical.
        # 拼成 (K_hit, layer_count) 的 int8 配方矩阵，列序仍是先底后顶。
        chunk_recipes = np.empty(
            (row_indices.size, layer_count), dtype=np.int8
        )
        if bottom_depth > 0:
            chunk_recipes[:, :bottom_depth] = chunk_bot_recipes
        if top_depth > 0:
            chunk_recipes[:, bottom_depth:] = chunk_top_recipes

        # Vectorised lookup of previous-best deltas; missing buckets default
        # to +inf so the first hit always wins.
        # 向量化拉出旧最优 delta；未命中桶默认 +inf，保证首发必胜。
        unique_bucket_idx = bucket_idx[row_indices]
        unique_srgb_key = _pack_srgb(chunk_best_srgb)
        unique_keys = [
            (int(b), int(s))
            for b, s in zip(unique_bucket_idx, unique_srgb_key)
        ]
        prev_deltas = np.fromiter(
            (best[key][0] if key in best else np.inf for key in unique_keys),
            dtype=np.float64,
            count=len(unique_keys),
        )
        improved = chunk_best_deltas < prev_deltas
        if not np.any(improved):
            if progress_callback is not None:
                fraction = (chunk_idx + 1) / max(num_chunks, 1)
                progress_callback(
                    fraction,
                    {
                        "chunk_index": chunk_idx + 1,
                        "total_chunks": num_chunks,
                        "valid_bucket_count": len(best),
                        "elapsed_seconds": time.time() - start_time,
                    },
                )
            continue

        # Write back the improved entries. The per-row arrays are tiny
        # (3-9 ints / floats per entry), so the Python-level loop here is
        # negligible vs the chunk-wide vectorised numpy work above.
        # 回写改进项；每条记录非常小，Python 循环开销可忽略。
        for i in np.flatnonzero(improved):
            key = unique_keys[i]
            best[key] = (
                float(chunk_best_deltas[i]),
                chunk_recipes[i].copy(),
                chunk_best_srgb[i].copy(),
                chunk_best_lab[i].copy(),
                chunk_best_centers[i].copy(),
            )

        if progress_callback is not None:
            fraction = (chunk_idx + 1) / max(num_chunks, 1)
            progress_callback(
                fraction,
                {
                    "chunk_index": chunk_idx + 1,
                    "total_chunks": num_chunks,
                    "valid_bucket_count": len(best),
                    "elapsed_seconds": time.time() - start_time,
                },
            )

    # Materialize sparse output in canonical (ascending bucket_idx) order so
    # downstream lookups can rely on a stable layout. The dense build path
    # used to extract via ``np.isfinite(best_delta)``, which preserved the
    # natural array order (== ascending bucket_idx); ``sorted(best)`` here
    # reproduces that same order so existing on-disk caches and any caller
    # that depends on row order keep working unchanged.
    # 按桶号升序输出，与原密集路径的 np.isfinite 抽取序列一致，保证旧缓存
    # 与依赖行序的下游代码无需改动。
    sorted_keys = sorted(best.keys())
    valid_count = len(sorted_keys)
    if valid_count > 0:
        lab_centers = np.empty((valid_count, 3), dtype=np.float32)
        recipes = np.empty((valid_count, layer_count), dtype=np.int8)
        achieved_srgb = np.empty((valid_count, 3), dtype=np.uint8)
        achieved_lab = np.empty((valid_count, 3), dtype=np.float32)
        center_delta_e = np.empty(valid_count, dtype=np.float32)
        for row_idx, key in enumerate(sorted_keys):
            delta_e, recipe, srgb, lab, center = best[key]
            center_delta_e[row_idx] = float(delta_e)
            recipes[row_idx] = recipe
            achieved_srgb[row_idx] = srgb
            achieved_lab[row_idx] = lab
            lab_centers[row_idx] = center
    else:
        lab_centers = np.zeros((0, 3), dtype=np.float32)
        recipes = np.zeros((0, layer_count), dtype=np.int8)
        achieved_srgb = np.zeros((0, 3), dtype=np.uint8)
        achieved_lab = np.zeros((0, 3), dtype=np.float32)
        center_delta_e = np.zeros(0, dtype=np.float32)

    build_time = time.time() - start_time

    metadata = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "color_precision": "continuous_lab",
        "cache_id": cache_id,
        "solver_version": CACHE_SOLVER_VERSION,
        "canonical_materials": describe_palette(canonical_materials),
        "layer_count": int(layer_count),
        "layer_height_mm": float(layer_height_mm),
        "substrate": substrate,
        "grid_resolution": int(grid_resolution),
        "total_combinations": total_combinations,
        "valid_cell_count": valid_count,
        "total_cell_count": total_buckets,
        "mean_delta_e": float(center_delta_e.mean()) if valid_count > 0 else 0.0,
        "max_delta_e": float(center_delta_e.max()) if valid_count > 0 else 0.0,
        "build_time_seconds": build_time,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    _log.info(
        "Built material solver cache: palette=%s N=%d t=%.2f substrate=%s "
        "valid_cells=%d/%d mean_ΔE=%.2f build=%.1fs",
        cache_id,
        layer_count,
        layer_height_mm,
        substrate,
        valid_count,
        total_buckets,
        metadata["mean_delta_e"],
        build_time,
        extra={
            "event": "material_solver_cache_built",
            "cache_id": cache_id,
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "valid_cell_count": valid_count,
            "total_cell_count": total_buckets,
            "mean_delta_e": metadata["mean_delta_e"],
            "build_time_seconds": build_time,
        },
    )

    # ---- Compute and attach pure-colour recipes (pinned, never culled) ----
    uniform_recipes, uniform_achieved_srgb = _compute_uniform_recipes(
        canonical_materials, layer_count, layer_height_mm, substrate,
    )
    metadata["uniform_recipe_count"] = int(uniform_recipes.shape[0])

    return MaterialSolverCache(
        lab_centers=lab_centers,
        recipes=recipes,
        achieved_srgb=achieved_srgb,
        achieved_lab=achieved_lab,
        center_delta_e=center_delta_e,
        uniform_recipes=uniform_recipes,
        uniform_achieved_srgb=uniform_achieved_srgb,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_material_solver_cache(
    cache: MaterialSolverCache,
    *,
    cache_root: str | Path | None = None,
) -> Path:
    """Write ``cache`` to disk at its canonical path.
    将 ``cache`` 写入其规范磁盘路径。
    """
    directory = default_cache_directory(cache_root)
    directory.mkdir(parents=True, exist_ok=True)
    expected = {key: cache.metadata[key] for key in (
        "schema_version", "solver_version", "canonical_materials", "layer_count",
        "layer_height_mm", "substrate", "grid_resolution",
    )}
    npz_path = _find_cache_record(directory, expected)
    if npz_path is None:
        npz_path = directory / f"solver-{cache.cache_id}.npz"
    else:
        stored_metadata = json.loads(_cache_meta_path_for(npz_path).read_text(encoding="utf-8"))
        cache.metadata["cache_id"] = stored_metadata["cache_id"]
    meta_path = _cache_meta_path_for(npz_path)

    # Write arrays atomically. np.savez_compressed appends ``.npz`` when the
    # path lacks one, so we hand it a binary file handle to keep the tmp name
    # predictable; then an atomic rename promotes it to the final path.
    tmp_npz = npz_path.with_name(npz_path.name + ".tmp")
    with tmp_npz.open("wb") as handle:
        np.savez_compressed(
            handle,
            lab_centers=cache.lab_centers,
            recipes=cache.recipes,
            achieved_srgb=cache.achieved_srgb,
            achieved_lab=cache.achieved_lab,
            center_delta_e=cache.center_delta_e,
            uniform_recipes=cache.uniform_recipes,
            uniform_achieved_srgb=cache.uniform_achieved_srgb,
        )
    tmp_npz.replace(npz_path)

    meta_path.write_text(
        json.dumps(cache.metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cache_size_mb = npz_path.stat().st_size / (1024 * 1024)
    _log.info(
        "Saved material solver cache %s (%.2f MB)",
        npz_path.name,
        cache_size_mb,
        extra={
            "event": "material_solver_cache_saved",
            "cache_file": npz_path.name,
            "cache_size_mb": round(cache_size_mb, 3),
        },
    )
    return npz_path


def load_material_solver_cache(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    cache_root: str | Path | None = None,
) -> MaterialSolverCache | None:
    """Load a cached solver from disk, or ``None`` if absent/corrupt.
    从磁盘加载缓存；不存在或损坏时返回 ``None``。

    Args:
        materials: Current palette, compared with saved effective descriptors.
            调用方耗材列表，用于直接比较保存的有效参数描述。
        layer_count: Number of layers per pixel. (每像素层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        grid_resolution: Expected Lab grid resolution; zero selects exact mode.
            期望的 Lab 网格分辨率；零表示精确模式。
        cache_root: Optional override for the cache directory.
    """
    npz_path = cache_file_path(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        grid_resolution=grid_resolution,
        cache_root=cache_root,
    )
    meta_path = _cache_meta_path_for(npz_path)

    if not npz_path.exists() or not meta_path.exists():
        return None

    try:
        with np.load(npz_path) as loaded:
            lab_centers = loaded["lab_centers"].astype(np.float32)
            recipes = loaded["recipes"].astype(np.uint8)
            achieved_srgb = loaded["achieved_srgb"].astype(np.uint8)
            if "achieved_lab" in loaded:
                has_achieved_lab = True
                achieved_lab = loaded["achieved_lab"].astype(np.float32)
            else:
                has_achieved_lab = False
                achieved_lab = np.zeros_like(lab_centers, dtype=np.float32)
            center_delta_e = loaded["center_delta_e"].astype(np.float32)
            # uniform_* fields are optional — legacy caches lack them.
            uniform_recipes = loaded.get("uniform_recipes",
                                         np.zeros((0, 0), dtype=np.uint8))
            uniform_achieved_srgb = loaded.get("uniform_achieved_srgb",
                                                np.zeros((0, 3), dtype=np.uint8))
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        _log.warning(
            "Failed to load material solver cache %s: %s",
            npz_path.name, exc,
            extra={
                "event": "material_solver_cache_load_failed",
                "cache_file": npz_path.name,
                "error_type": type(exc).__name__,
            },
        )
        return None

    if (
        not has_achieved_lab
        or metadata.get("color_precision") != "continuous_lab"
    ):
        return None

    # Validate array contracts before exposing the loaded runtime.
    if (
        recipes.ndim != 2
        or lab_centers.ndim != 2
        or center_delta_e.ndim != 1
        or recipes.shape[0] != lab_centers.shape[0]
        or recipes.shape[1] != int(metadata.get("layer_count", -1))
        or achieved_srgb.shape != lab_centers.shape
        or achieved_lab.shape != lab_centers.shape
        or center_delta_e.shape[0] != lab_centers.shape[0]
    ):
        _log.warning(
            "Material solver cache has inconsistent shapes",
            extra={"event": "material_solver_cache_shape_mismatch", "cache_file": npz_path.name},
        )
        return None
    expected = _solver_cache_parameters(
        materials, layer_count, layer_height_mm, substrate, grid_resolution
    )
    if any(metadata.get(key) != value for key, value in expected.items()):
        return None
    return MaterialSolverCache(
        lab_centers=lab_centers,
        recipes=recipes,
        achieved_srgb=achieved_srgb,
        achieved_lab=achieved_lab,
        center_delta_e=center_delta_e,
        uniform_recipes=uniform_recipes,
        uniform_achieved_srgb=uniform_achieved_srgb,
        metadata=metadata,
    )


def find_any_cached_grid(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    cache_root: str | Path | None = None,
) -> list[tuple[int, Path]]:
    """Return every ``(grid_resolution, npz_path)`` cache on disk for this key.

    Compare small metadata sidecars with the material and layer descriptors,
    returning available grid records in descending resolution order. Array
    validation is deferred to :func:`load_material_solver_cache`.

    扫描缓存目录下所有与调用方 ``(palette, N, 层高, 基底)`` 匹配、不同
    ``grid_resolution`` 的缓存文件，按分辨率降序返回 ``(grid, path)`` 列表。
    文件内容不在此处校验，调用方仍需通过 :func:`load_material_solver_cache`
    完成参数与数组形状检查。

    Args:
        materials: Palette to match. (调色板)
        layer_count: Number of layers per pixel. (每像素层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        cache_root: Optional override for the cache directory. (缓存根目录)

    Returns:
        A list of ``(grid_resolution, npz_path)`` tuples sorted by
        resolution descending. Empty when the cache directory is missing or
        no matching file exists.
    """
    cache_dir = default_cache_directory(cache_root)
    if not cache_dir.is_dir():
        return []

    expected = _solver_cache_parameters(materials, layer_count, layer_height_mm, substrate)
    by_grid: dict[int, Path] = {}
    for meta_path in sorted(cache_dir.glob("*.meta.json")):
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if any(metadata.get(key) != value for key, value in expected.items()):
                continue
            grid = int(metadata["grid_resolution"])
        except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError):
            continue
        path = meta_path.with_name(meta_path.name.removesuffix(".meta.json") + ".npz")
        if path.exists():
            by_grid.setdefault(grid, path)
    return sorted(by_grid.items(), key=lambda item: item[0], reverse=True)


def load_material_solver_cache_with_fallback(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    cache_root: str | Path | None = None,
) -> tuple["MaterialSolverCache | None", int | None]:
    """Load the requested grid; on miss, retry any other grid on disk.

    This wraps :func:`load_material_solver_cache` with a "finer grid first"
    fallback: if the caller-requested resolution has no valid cache file, the
    helper enumerates every cached resolution on disk for the same palette
    /layer/substrate via :func:`find_any_cached_grid` and tries each (highest
    first) until one loads. This keeps the hot pipeline path off the slow
    MITM solver even when the UI's currently-selected grid does not match
    what the user actually built.

    先按 ``grid_resolution`` 加载；未命中时按磁盘上其它已存分辨率（由密到疏）
    依次回退，直到成功或全部失败。确保 UI 所选网格与用户实际构建的缓存不一致
    时也能命中持久化结果，而不是回落到 MITM 求解器。

    Args:
        materials: Palette to match. (调色板)
        layer_count: Number of layers per pixel. (每像素层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        grid_resolution: Preferred Lab grid resolution to try first.
            (优先尝试的 Lab 网格分辨率)
        cache_root: Optional override for the cache directory. (缓存根目录)

    Returns:
        ``(cache, actual_grid)`` where ``actual_grid`` is the resolution of
        the cache that was successfully loaded (may differ from the
        requested one). Returns ``(None, None)`` when no usable cache file
        exists on disk.
    """
    # ---- Try exact-mode cache first (grid=0) when palette is eligible ----
    # Exact caches are strictly superior to any bucketed tier, so we always
    # prefer them when available. The grid_resolution=0 convention signals
    # "exact mode" on disk.
    # 先尝试精确模式缓存（grid=0），若存在则无条件使用——精确模式严格优于
    # 任何分桶分辨率。
    if _is_exact_mode_eligible(len(materials), layer_count):
        try:
            exact_cache = load_material_solver_cache(
                materials, layer_count, layer_height_mm, substrate,
                grid_resolution=0, cache_root=cache_root,
            )
        except (AttributeError, TypeError):
            # Defensive: if materials are not proper MaterialParams instances
            # (e.g. test mocks), skip the exact path gracefully.
            exact_cache = None
        if exact_cache is not None:
            return exact_cache, 0

    cache = load_material_solver_cache(
        materials, layer_count, layer_height_mm, substrate,
        grid_resolution=grid_resolution, cache_root=cache_root,
    )
    if cache is not None:
        return cache, int(grid_resolution)

    candidates = find_any_cached_grid(
        materials, layer_count, layer_height_mm, substrate,
        cache_root=cache_root,
    )
    for candidate_grid, _path in candidates:
        if candidate_grid == int(grid_resolution):
            # Already tried and missed above; avoid redundant disk read.
            continue
        fallback = load_material_solver_cache(
            materials, layer_count, layer_height_mm, substrate,
            grid_resolution=candidate_grid, cache_root=cache_root,
        )
        if fallback is not None:
            _log.info(
                "Requested grid=%d has no usable material solver cache; "
                "falling back to grid=%d found on disk.",
                int(grid_resolution), int(candidate_grid),
                extra={
                    "event": "material_solver_cache_fallback_used",
                    "requested_grid_resolution": int(grid_resolution),
                    "fallback_grid_resolution": int(candidate_grid),
                },
            )
            return fallback, int(candidate_grid)

    return None, None


# ---------------------------------------------------------------------------
# Listing & introspection
# ---------------------------------------------------------------------------


def list_cached_entries(
    cache_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """List every cached palette combination with its metadata.
    列出所有已缓存的调色板组合及其元数据。
    """
    directory = default_cache_directory(cache_root)
    if not directory.exists():
        return []
    entries: list[dict[str, Any]] = []
    for npz_path in sorted(directory.glob("*.npz")):
        meta_path = _cache_meta_path_for(npz_path)
        if not meta_path.exists():
            continue
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not metadata.get("cache_id"):
            continue
        try:
            file_size = npz_path.stat().st_size
        except OSError:
            file_size = 0
        entries.append(
            {
                **metadata,
                "cache_file_path": str(npz_path),
                "cache_meta_path": str(meta_path),
                "cache_file_size_bytes": int(file_size),
            }
        )
    return entries


def delete_cached_entry(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    cache_root: str | Path | None = None,
) -> bool:
    """Remove the cache entry for the given parameters. Returns ``True`` on hit.
    删除指定参数的缓存条目；命中返回 ``True``。

    Only directly matching records are removed. Unsafe older entries remain.
    When eligible, the palette's exact-mode record is also targeted.
    仅删除描述直接匹配的记录；无法安全匹配的旧条目保留。
    若调色板支持精确模式，同时删除对应的精确缓存记录。
    """
    npz_path = cache_file_path(
        materials, layer_count, layer_height_mm, substrate,
        grid_resolution=grid_resolution,
        cache_root=cache_root,
    )
    meta_path = _cache_meta_path_for(npz_path)
    targets: list[Path] = [npz_path, meta_path]

    # Also target the exact-mode cache (-g000) when palette is eligible.
    # 当调色板满足精确模式条件时，同时删除精确缓存。
    if _is_exact_mode_eligible(len(materials), layer_count) and grid_resolution != 0:
        exact_npz = cache_file_path(
            materials, layer_count, layer_height_mm, substrate,
            grid_resolution=0,
            cache_root=cache_root,
        )
        exact_meta = _cache_meta_path_for(exact_npz)
        targets.extend((exact_npz, exact_meta))

    removed_any = False
    for path in targets:
        if path.exists():
            try:
                path.unlink()
                removed_any = True
            except OSError as exc:
                _log.warning(
                    "Failed to remove material solver cache file %s: %s",
                    path,
                    exc,
                    extra={
                        "event": "material_solver_cache_remove_failed",
                        "path": str(path),
                        "error_type": type(exc).__name__,
                    },
                )
    return removed_any
