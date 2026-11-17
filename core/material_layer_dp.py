"""Layer-by-layer dynamic-programming recipe generator for deep stacks.
深叠层（>10 层）配方的逐层动态规划生成器。

Why this exists / 为什么需要它
-----------------------------
Every Beer-Lambert layer is an affine map on the colour underneath it::

    C_new = a_m * C_prev + b_m,   a_m = exp(-k_m * t),   b_m = E_m * (1 - a_m)

Because the substrate colour is fixed (white or black), the colour after the
first ``n`` layers fully determines which colours the remaining layers can
reach. Two partial stacks that land on (almost) the same colour are therefore
interchangeable for everything built on top of them. We exploit that by
building the stack bottom-up and, after every layer, merging partial stacks
whose colours fall into the same small Lab cell.

The state count is bounded by the number of reachable Lab cells instead of
``M ** n``, so the cost grows *linearly* with layer count: 30 layers costs
roughly three times 10 layers, while full enumeration of 5 materials × 30
layers (~9e20 recipes) is impossible.

Merging error does not accumulate: every layer is a contraction
(``0 < a_m < 1``), so a small difference between two merged partial stacks
shrinks as more layers are stacked on top. The colours returned are the exact
forward-model colours of the returned recipes — merging only affects which
recipes survive, never the reported colour.

When several partial stacks share a cell, the one with the fewest material
changes is kept (ties: lowest key order), which favours recipes that are
cheaper to print on single-nozzle multi-material systems.

每层 Beer-Lambert 都是作用在下层颜色上的仿射变换；基底固定时，前 n 层得到的颜色
完全决定了后续能到达的颜色集合。因此逐层自底向上构建，每加一层把落在同一 Lab
小格内的部分配方合并，状态数受可达 Lab 格数约束而不是 M**n，复杂度随层数线性增长。
每层都是压缩映射，合并误差不会累积；返回的颜色是所返回配方的精确正向模型颜色。
同格冲突时保留换料次数最少的配方，对单喷头多色打印更友好。
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from core.material_color_solver import MaterialParams, linear_to_srgb_float

_log = logging.getLogger(__name__)

DEFAULT_STATE_CELL_LAB: float = 0.5
"""Lab cell edge used to merge partial stacks. 0.5 keeps merge error well
below 1 ΔE76 (measured: mean 0.11, max 0.81 vs. exhaustive at 5×8)."""

DEFAULT_MAX_STATES: int = 4_000_000
"""Upper bound on surviving partial stacks per layer. When exceeded the cell
is coarsened for the rest of the build (memory guard)."""

_CELL_GROWTH: float = 1.26  # ~2**(1/3): halves state count per step in 3-D
_CANDIDATE_CHUNK: int = 2_000_000
_KEY_BITS: int = 21
_KEY_MASK: int = (1 << _KEY_BITS) - 1


@dataclass(frozen=True)
class LayerDpResult:
    """Output of :func:`generate_layer_dp_recipes`.
    逐层 DP 输出。

    Attributes:
        recipes: ``(K, N)`` bottom-to-top material indices. (自底向上配方)
        linear_rgb: ``(K, 3)`` exact forward-model linear RGB. (精确线性 RGB)
        switch_counts: ``(K,)`` number of material changes per recipe.
            (每条配方的换料次数)
        state_cell_lab: Final Lab merge-cell edge actually used.
            (实际使用的 Lab 合并格边长)
        states_per_layer: Surviving state count after each layer.
            (每层合并后的状态数)
    """

    recipes: np.ndarray
    linear_rgb: np.ndarray
    switch_counts: np.ndarray
    state_cell_lab: float
    states_per_layer: tuple[int, ...]

    def metadata(self) -> dict[str, Any]:
        return {
            "algorithm": "layer_dp",
            "state_cell_lab": float(self.state_cell_lab),
            "state_count": int(self.recipes.shape[0]),
            "states_per_layer": [int(v) for v in self.states_per_layer],
        }


def _linear_to_lab(linear_rgb: np.ndarray) -> np.ndarray:
    srgb = linear_to_srgb_float(linear_rgb).astype(np.float32, copy=False)
    lab = cv2.cvtColor(srgb.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)
    return lab.reshape(-1, 3)


def _cell_keys(lab: np.ndarray, cell: float) -> np.ndarray:
    """Pack Lab cell coordinates into one int64 key (21 bits per axis)."""
    inv = 1.0 / float(cell)
    l_idx = np.floor(np.clip(lab[:, 0], 0.0, 100.0) * inv).astype(np.int64)
    a_idx = np.floor((np.clip(lab[:, 1], -128.0, 128.0) + 128.0) * inv).astype(np.int64)
    b_idx = np.floor((np.clip(lab[:, 2], -128.0, 128.0) + 128.0) * inv).astype(np.int64)
    return (
        ((l_idx & _KEY_MASK) << (2 * _KEY_BITS))
        | ((a_idx & _KEY_MASK) << _KEY_BITS)
        | (b_idx & _KEY_MASK)
    )


def _substrate_linear(substrate: str) -> np.ndarray:
    normalized = str(substrate).lower()
    if normalized == "white":
        return np.ones(3, dtype=np.float64)
    if normalized == "black":
        return np.zeros(3, dtype=np.float64)
    raise ValueError("substrate must be 'white' or 'black'")


def generate_layer_dp_recipes(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    state_cell_lab: float = DEFAULT_STATE_CELL_LAB,
    max_states: int = DEFAULT_MAX_STATES,
    recipe_dtype: np.dtype | type = np.uint8,
    progress_callback: Callable[[float, dict[str, Any]], None] | None = None,
) -> LayerDpResult:
    """Generate diverse exactly-``layer_count`` recipes by layer-wise DP.
    用逐层 DP 生成覆盖充分的恰好 ``layer_count`` 层配方。

    Args:
        materials: Palette (any order; returned indices refer to this list).
            (耗材列表；返回索引对应此列表)
        layer_count: Exact recipe length. (配方层数)
        layer_height_mm: Thickness of one layer in mm. (单层厚度 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        state_cell_lab: Initial Lab merge-cell edge. (初始 Lab 合并格边长)
        max_states: Max surviving states per layer; the cell is coarsened
            when exceeded. (每层最大状态数，超出时放大合并格)
        recipe_dtype: Integer dtype for returned recipes. (配方整数类型)
        progress_callback: Optional ``cb(fraction, info)``. (进度回调)

    Returns:
        LayerDpResult with recipes sorted by Lab cell key.
    """
    if not materials:
        raise ValueError("materials must not be empty")
    n_layers = int(layer_count)
    if n_layers <= 0:
        raise ValueError("layer_count must be positive")
    if state_cell_lab <= 0:
        raise ValueError("state_cell_lab must be positive")
    if max_states < len(materials):
        raise ValueError("max_states must be at least the material count")
    dtype = np.dtype(recipe_dtype)
    if len(materials) - 1 > np.iinfo(dtype).max:
        raise ValueError("recipe_dtype cannot hold every material index")

    k_stack = np.stack([np.asarray(m.k, dtype=np.float64) for m in materials])
    e_stack = np.stack([np.asarray(m.E, dtype=np.float64) for m in materials])
    a = np.exp(-k_stack * float(layer_height_mm))  # (M, 3)
    b = e_stack * (1.0 - a)  # (M, 3)
    m_count = a.shape[0]

    colors = _substrate_linear(substrate)[None, :].copy()
    recipes = np.zeros((1, 0), dtype=dtype)
    switches = np.zeros(1, dtype=np.int16)
    cell = float(state_cell_lab)
    states_per_layer: list[int] = []
    mat_ids = np.arange(m_count, dtype=np.int64)

    for depth in range(n_layers):
        s_count = colors.shape[0]
        # Candidate (parent, material) pairs are indexed as parent*M + material.
        cand_total = s_count * m_count
        if depth == 0:
            cand_switch = np.zeros(cand_total, dtype=np.int16)
        else:
            last = recipes[:, -1].astype(np.int64)
            changed = last[:, None] != mat_ids[None, :]
            cand_switch = (switches[:, None] + changed).reshape(-1).astype(np.int16)

        # Lab of every candidate, computed in chunks of parents.
        cand_lab = np.empty((cand_total, 3), dtype=np.float32)
        parents_per_chunk = max(1, _CANDIDATE_CHUNK // m_count)
        for start in range(0, s_count, parents_per_chunk):
            end = min(start + parents_per_chunk, s_count)
            nxt = colors[start:end, None, :] * a[None] + b[None]
            cand_lab[start * m_count : end * m_count] = _linear_to_lab(
                nxt.reshape(-1, 3)
            )

        while True:
            keys = _cell_keys(cand_lab, cell)
            # Primary: key; secondary: fewest switches; tertiary: stable index.
            order = np.lexsort((cand_switch, keys))
            sorted_keys = keys[order]
            first = np.empty(sorted_keys.shape, dtype=bool)
            first[0] = True
            np.not_equal(sorted_keys[1:], sorted_keys[:-1], out=first[1:])
            winners = order[first]
            if winners.size <= max_states:
                break
            cell *= _CELL_GROWTH
            _log.debug(
                "layer_dp: %d states > max %d at depth %d, coarsening cell to %.3f",
                winners.size,
                max_states,
                depth + 1,
                cell,
            )
        del cand_lab, keys, order, sorted_keys, first

        parent = winners // m_count
        mat = (winners % m_count).astype(np.int64)
        colors = a[mat] * colors[parent] + b[mat]
        new_recipes = np.empty((winners.size, depth + 1), dtype=dtype)
        if depth > 0:
            new_recipes[:, :depth] = recipes[parent]
        new_recipes[:, depth] = mat.astype(dtype)
        recipes = new_recipes
        switches = cand_switch[winners]
        states_per_layer.append(int(winners.size))

        if progress_callback is not None:
            progress_callback(
                (depth + 1) / n_layers,
                {"layer": depth + 1, "states": int(winners.size), "cell": cell},
            )

    return LayerDpResult(
        recipes=recipes,
        linear_rgb=np.clip(colors, 0.0, 1.0),
        switch_counts=switches,
        state_cell_lab=cell,
        states_per_layer=tuple(states_per_layer),
    )


# ---------------------------------------------------------------------------
# In-process memo
# ---------------------------------------------------------------------------
# Preview requests rebuild an in-memory candidate runtime on every call; for
# deep stacks the DP is the expensive part, so keep the last few results.
# 预览每次都会重建内存候选运行时；深叠层下 DP 是主要耗时，缓存最近几次结果。

_MEMO_MAX_ENTRIES: int = 4
_memo: "OrderedDict[str, LayerDpResult]" = OrderedDict()
_memo_lock = threading.Lock()


def _memo_key(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    state_cell_lab: float,
    max_states: int,
    recipe_dtype: np.dtype,
) -> str:
    h = hashlib.sha256()
    for m in materials:
        h.update(np.asarray(m.E, dtype=np.float64).tobytes())
        h.update(np.asarray(m.k, dtype=np.float64).tobytes())
    h.update(
        repr(
            (
                int(layer_count),
                float(layer_height_mm),
                str(substrate),
                float(state_cell_lab),
                int(max_states),
                np.dtype(recipe_dtype).str,
            )
        ).encode()
    )
    return h.hexdigest()


def generate_layer_dp_recipes_cached(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    state_cell_lab: float = DEFAULT_STATE_CELL_LAB,
    max_states: int = DEFAULT_MAX_STATES,
    recipe_dtype: np.dtype | type = np.uint8,
) -> LayerDpResult:
    """Memoized :func:`generate_layer_dp_recipes` (last few palettes).
    带进程内缓存的 :func:`generate_layer_dp_recipes`。"""
    key = _memo_key(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        state_cell_lab,
        max_states,
        np.dtype(recipe_dtype),
    )
    with _memo_lock:
        hit = _memo.get(key)
        if hit is not None:
            _memo.move_to_end(key)
            return hit
    result = generate_layer_dp_recipes(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        state_cell_lab=state_cell_lab,
        max_states=max_states,
        recipe_dtype=recipe_dtype,
    )
    with _memo_lock:
        _memo[key] = result
        _memo.move_to_end(key)
        while len(_memo) > _MEMO_MAX_ENTRIES:
            _memo.popitem(last=False)
    return result


def clear_layer_dp_memo() -> None:
    with _memo_lock:
        _memo.clear()
