"""
S03 — Color replacement (global + region + matched_rgb override).
S03 — 颜色替换（全局替换 + 区域替换 + matched_rgb 覆盖）。

从 converter.py 搬入的颜色替换逻辑和辅助函数：
- _normalize_color_replacements_input: 统一替换输入格式
- _apply_region_replacement: 区域替换
- _apply_regions_to_raster_outputs: 按区域覆盖 raster 输出
- _compute_connected_region_mask_4n: 4 邻接连通域掩码计算
- matched_rgb_path 覆盖逻辑
- _apply_material_archive_color_replacements: 材料档案模式下的全局色替换
"""

from api.structured_logging import get_logger
import time
from collections import deque
from copy import deepcopy
import pickle
import cv2
import numpy as np

from core.edit_projection import EditProjectionGrid
from core.errors import CachedPreviewAnalysisError
from core.pipeline.material_dynamic_layers import (
    _record_dynamic_material_error,
    _solve_dynamic_material_targets,
)
from core.pipeline.pipeline_utils import _hex_to_rgb_tuple

_log = get_logger(__name__)


def _load_required_edit_array(path: object, *, field_name: str) -> np.ndarray:
    """Load one fail-closed preview edit artifact."""

    if not isinstance(path, (str, bytes)) or not path:
        raise CachedPreviewAnalysisError(
            f"Required preview edit artifact is missing: {field_name}"
        )
    try:
        loaded = np.load(path, allow_pickle=False)
    except (OSError, ValueError, TypeError) as exc:
        raise CachedPreviewAnalysisError(
            f"Required preview edit artifact is unreadable: {field_name}"
        ) from exc
    if not isinstance(loaded, np.ndarray):
        raise CachedPreviewAnalysisError(
            f"Required preview edit artifact is invalid: {field_name}"
        )
    return loaded


def _resolve_edit_projection_grid(
    ctx: dict,
    *,
    target_shape: tuple[int, int],
) -> tuple[EditProjectionGrid, str]:
    """Validate edit projection metadata and return its discrete grid."""

    projection = ctx.get("edit_projection")
    if not isinstance(projection, dict):
        raise CachedPreviewAnalysisError(
            "Required edit projection metadata is invalid"
        )
    source_shape_raw = projection.get("source_shape")
    mode = str(projection.get("mode") or "")
    if (
        not isinstance(source_shape_raw, (list, tuple))
        or len(source_shape_raw) != 2
        or mode not in {"delta", "recipe_masks"}
    ):
        raise CachedPreviewAnalysisError(
            "Required edit projection source grid is invalid"
        )
    try:
        source_shape = (int(source_shape_raw[0]), int(source_shape_raw[1]))
        grid = EditProjectionGrid(source_shape, target_shape)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CachedPreviewAnalysisError(
            "Required edit projection grid is invalid"
        ) from exc
    return grid, mode


def _replay_projected_preview_edits(
    ctx: dict,
    *,
    fresh_matched_rgb: np.ndarray,
    fresh_material_matrix: np.ndarray,
    target_mask_solid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, EditProjectionGrid]:
    """Replay only committed preview deltas onto a fresh current-size grid.

    仅把预览期真正修改过的像素投影到当前尺寸的新分析；未编辑像素及
    浮雕高度身份继续以当前尺寸的重新分析结果为准。
    """

    grid, mode = _resolve_edit_projection_grid(
        ctx,
        target_shape=tuple(int(value) for value in target_mask_solid.shape),
    )
    if mode != "delta":
        raise CachedPreviewAnalysisError("Preview edit projection mode is not delta")
    source_shape = grid.source_shape

    edited_rgb = _load_required_edit_array(
        ctx.get("matched_rgb_path"),
        field_name="matched_rgb",
    )
    pristine_rgb = _load_required_edit_array(
        ctx.get("original_matched_rgb_path"),
        field_name="original_matched_rgb",
    )
    source_solid_raw = _load_required_edit_array(
        ctx.get("mask_solid_path"),
        field_name="mask_solid",
    )
    edited_material = _load_required_edit_array(
        ctx.get("material_matrix_path"),
        field_name="material_matrix",
    )
    pristine_material = _load_required_edit_array(
        ctx.get("original_material_matrix_path"),
        field_name="original_material_matrix",
    )

    fresh_rgb = np.asarray(fresh_matched_rgb)
    fresh_material = np.asarray(fresh_material_matrix)
    target_solid = np.asarray(target_mask_solid, dtype=bool)
    source_solid = np.asarray(source_solid_raw, dtype=bool)
    arrays_are_valid = (
        edited_rgb.shape == (*source_shape, 3)
        and pristine_rgb.shape == edited_rgb.shape
        and edited_rgb.dtype == np.uint8
        and pristine_rgb.dtype == np.uint8
        and source_solid_raw.shape == source_shape
        and source_solid_raw.dtype == np.bool_
        and edited_material.ndim == 3
        and pristine_material.ndim == 3
        and edited_material.shape[:2] == source_shape
        and pristine_material.shape[:2] == source_shape
        and edited_material.shape[2] > 0
        and pristine_material.shape[2] > 0
        and np.issubdtype(edited_material.dtype, np.integer)
        and np.issubdtype(pristine_material.dtype, np.integer)
        and fresh_rgb.ndim == 3
        and fresh_rgb.shape == (*grid.target_shape, 3)
        and fresh_material.ndim == 3
        and fresh_material.shape[:2] == grid.target_shape
        and fresh_material.shape[2] > 0
        and target_solid.shape == grid.target_shape
    )
    if not arrays_are_valid:
        raise CachedPreviewAnalysisError(
            "Required preview edit artifacts are structurally incompatible"
        )

    rgb_change_mask = grid.project_change_mask(
        edited_rgb,
        pristine_rgb,
        source_solid=source_solid,
        target_solid=target_solid,
    )
    replayed_rgb = np.asarray(fresh_rgb, dtype=np.uint8).copy()
    replayed_rgb[rgb_change_mask] = grid.sample_target_mask(
        edited_rgb,
        rgb_change_mask,
    )

    common_source_layers = min(
        int(edited_material.shape[2]),
        int(pristine_material.shape[2]),
    )
    material_source_change = np.any(
        edited_material[..., :common_source_layers]
        != pristine_material[..., :common_source_layers],
        axis=-1,
    )
    material_source_change &= source_solid
    material_change_mask = grid.project_mask(
        material_source_change,
        target_solid=target_solid,
    )
    replayed_material = np.array(fresh_material, copy=True)
    copied_layers = min(
        int(edited_material.shape[2]),
        int(replayed_material.shape[2]),
    )
    replayed_material_slice = replayed_material[..., :copied_layers]
    replayed_material_slice[material_change_mask] = grid.sample_target_mask(
        edited_material[..., :copied_layers],
        material_change_mask,
    )

    _log.debug(
        "Preview edit deltas projected onto fresh analysis",
        extra={
            "event": "preview_edit_projection_applied",
            "source_shape": list(grid.source_shape),
            "target_shape": list(grid.target_shape),
            "rgb_changed_pixels": int(np.count_nonzero(rgb_change_mask)),
            "material_changed_pixels": int(
                np.count_nonzero(material_change_mask)
            ),
        },
    )
    return (
        replayed_rgb,
        replayed_material,
        np.asarray(fresh_rgb, dtype=np.uint8).copy(),
        grid,
    )


def _resize_spatial_nearest(
    values: np.ndarray,
    target_shape: tuple[int, int],
) -> np.ndarray:
    """Resize the first two axes with pixel-center nearest-neighbor sampling."""

    source = np.asarray(values)
    if source.ndim < 2:
        raise ValueError("Authoritative recipe artifact must have spatial axes")
    source_h, source_w = source.shape[:2]
    target_h, target_w = target_shape
    if source_h <= 0 or source_w <= 0 or target_h <= 0 or target_w <= 0:
        raise ValueError("Authoritative recipe artifact has an empty spatial grid")
    if (source_h, source_w) == (target_h, target_w):
        return source

    y_indices = np.minimum(
        ((np.arange(target_h, dtype=np.float64) + 0.5) * source_h / target_h).astype(
            np.intp
        ),
        source_h - 1,
    )
    x_indices = np.minimum(
        ((np.arange(target_w, dtype=np.float64) + 0.5) * source_w / target_w).astype(
            np.intp
        ),
        source_w - 1,
    )
    return source[y_indices[:, None], x_indices[None, :], ...]


def _prepare_authoritative_material_override(
    override_material_matrix: np.ndarray,
    processed_material_matrix: np.ndarray,
    mask_solid: np.ndarray,
    authority_mask_path: str | None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Validate and align a final material matrix to the fresh S02 grid.

    Recipe-only large-format workers run S02 on a freshly cropped tile. Its
    integer pixel grid can differ by one pixel from the corresponding preview
    cache crop. In that case the final recipe matrix and its authority mask are
    sampled together onto S02's canonical grid. A complete cached trio has no
    authority mask and must already match exactly.
    """

    override = np.asarray(override_material_matrix)
    processed = np.asarray(processed_material_matrix)
    solid = np.asarray(mask_solid)
    if override.ndim != 3 or processed.ndim != 3:
        raise ValueError("Authoritative material matrix must be 3-dimensional")
    if not np.issubdtype(override.dtype, np.integer):
        raise ValueError("Authoritative material matrix must use an integer dtype")
    if override.shape[2] != processed.shape[2]:
        raise ValueError(
            "Authoritative material matrix layer count does not match "
            "processed material matrix"
        )
    if solid.ndim != 2 or solid.shape != processed.shape[:2]:
        raise ValueError(
            "Processed solid mask shape does not match processed material matrix"
        )

    if authority_mask_path is None:
        if override.shape != processed.shape:
            raise ValueError(
                "Complete authoritative material matrix shape does not match "
                "processed material matrix"
            )
        return np.array(override, copy=True), None

    try:
        loaded_mask = np.load(authority_mask_path, allow_pickle=False)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("Failed to load final material matrix authority mask") from exc
    authority_mask = np.asarray(loaded_mask)
    if authority_mask.ndim != 2:
        raise ValueError("Final material matrix authority mask must be 2-dimensional")
    if authority_mask.shape != override.shape[:2]:
        raise ValueError(
            "Final material matrix authority mask shape does not match "
            "authoritative material matrix"
        )

    target_shape = processed.shape[:2]
    aligned_override = _resize_spatial_nearest(override, target_shape)
    aligned_mask = _resize_spatial_nearest(authority_mask, target_shape)
    return (
        np.array(aligned_override, copy=True),
        np.asarray(aligned_mask, dtype=bool) & np.asarray(solid, dtype=bool),
    )


def _extend_ctx_palette_with_virtuals(
    ctx: dict,
    lut_palette_length: int,
    virtual_registry: list[dict[str, str]],
) -> None:
    """Append user-declared virtual materials to the pipeline palette.

    把用户声明的虚拟耗材追加进 pipeline 的 ``slot_names`` /
    ``preview_colors`` / ``color_conf``，让下游 s07 / s08 / s09 按新索引渲染。

    The registry is a list of ``{"name", "hex"}`` dicts; the ``k``-th entry
    lands at channel index ``lut_palette_length + k`` so the material_matrix
    writes in s03 stay consistent with the palette the meshers read later.

    Args:
        ctx: Pipeline context; mutated in place.
        lut_palette_length: Native LUT palette length; virtuals start after.
        virtual_registry: Deduped ordered list of virtual materials.
    """
    if not virtual_registry:
        return
    # CRITICAL: in the raster pipeline ``ctx["color_conf"]`` /
    # ``ctx["preview_colors"]`` / ``ctx["slot_names"]`` may be direct
    # references into ``ColorSystem.get(color_mode)`` (see
    # ``p01_preview_validation`` and ``s01_input_validation``). Appending in
    # place would permanently pollute the process-wide ColorSystem dict for
    # every subsequent request handled by this worker — manifesting as
    # transparent channels collapsing into opaque blocks, s07 over-counting
    # materials, and non-override regions losing their recipes. Copy-on-write
    # the containers before we extend them.
    # 栅格管线里这三个 ctx 键常常直接指向进程级共享的 ColorSystem dict，
    # 就地 ``append`` 会永久污染后续请求（表现为透明失效、模型变方块、
    # 非 override 区域丢配方）。先 copy-on-write 再追加。
    slot_names_src = ctx.get("slot_names")
    slot_names = (
        list(slot_names_src)
        if isinstance(slot_names_src, (list, tuple))
        else []
    )
    ctx["slot_names"] = slot_names
    preview_colors_src = ctx.get("preview_colors")
    preview_colors = (
        dict(preview_colors_src) if isinstance(preview_colors_src, dict) else {}
    )
    ctx["preview_colors"] = preview_colors
    color_conf_src = ctx.get("color_conf")
    color_conf = (
        dict(color_conf_src) if isinstance(color_conf_src, dict) else {}
    )
    ctx["color_conf"] = color_conf
    conf_preview_src = color_conf.get("preview")
    conf_preview = (
        dict(conf_preview_src) if isinstance(conf_preview_src, dict) else {}
    )
    color_conf["preview"] = conf_preview
    conf_slots_src = color_conf.get("slots")
    conf_slots = (
        list(conf_slots_src)
        if isinstance(conf_slots_src, (list, tuple))
        else []
    )
    color_conf["slots"] = conf_slots

    for offset, material in enumerate(virtual_registry):
        cache_index = lut_palette_length + offset
        try:
            r, g, b = _hex_to_rgb_tuple(material["hex"])
        except (ValueError, TypeError, KeyError):
            continue
        rgba = [int(r), int(g), int(b), 255]
        preview_colors[cache_index] = rgba
        conf_preview[cache_index] = rgba
        name = str(material.get("name") or f"Virtual_{offset}")
        while len(slot_names) < cache_index:
            slot_names.append(f"Slot_{len(slot_names)}")
        if len(slot_names) == cache_index:
            slot_names.append(name)
        else:
            slot_names[cache_index] = name
        while len(conf_slots) < cache_index:
            conf_slots.append(f"Slot_{len(conf_slots)}")
        if len(conf_slots) == cache_index:
            conf_slots.append(name)
        else:
            conf_slots[cache_index] = name


def _resolve_recipe_native_palette_length(
    ctx: dict,
    lut_metadata: object | None,
) -> int:
    """Return the number of real source channels before virtual materials.

    In normal LUT sessions this is ``len(lut_metadata.palette)``. In
    material-archive sessions there is no LUT metadata in the generation
    worker, so the selected material count is the native palette length and
    user-declared virtual materials must start after it.

    普通 LUT 会话用 ``lut_metadata.palette`` 的长度；耗材档案生成 worker
    没有 LUT metadata，此时已选耗材数量就是原生通道数，虚拟耗材必须从
    这个数量之后开始编号。
    """
    palette = getattr(lut_metadata, "palette", None) if lut_metadata is not None else None
    if palette:
        return len(palette)

    material_params = ctx.get("_material_params")
    if isinstance(material_params, (list, tuple)) and material_params:
        return len(material_params)

    selected_materials = ctx.get("selected_materials")
    if isinstance(selected_materials, (list, tuple)) and selected_materials:
        return len(selected_materials)

    slot_names = ctx.get("slot_names")
    if isinstance(slot_names, (list, tuple)):
        return len(slot_names)

    return 0


def _apply_material_archive_color_replacements(
    matched_rgb: np.ndarray,
    material_matrix: np.ndarray,
    mask_solid: np.ndarray,
    color_replacements: dict[str, str],
    materials: list,
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    grid_resolution: int | None = None,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Apply ``{orig_hex: repl_hex}`` replacements using the material solver.
    使用耗材求解器在材料档案模式下应用 ``{orig_hex: repl_hex}`` 全局替换。

    For each ``(orig, repl)`` pair this locates the pixels whose current
    ``matched_rgb`` equals ``orig``, solves a fresh ``repl`` recipe via the
    persisted :class:`core.material_cache.MaterialSolverCache` when available
    (falling back to :func:`core.material_color_solver.solve_image_colors_optimal`
    otherwise), and writes the achieved sRGB plus per-layer recipe back into
    ``matched_rgb`` and ``material_matrix``.

    Unlike the LUT-backed path in :func:`run`, there is no KD-Tree over a
    fixed palette: every replacement target is re-solved against the same
    ``materials`` / ``layer_count`` / ``substrate`` the image was originally
    quantised against.

    Args:
        matched_rgb: (H, W, 3) uint8 current matched sRGB image. (当前匹配 RGB)
        material_matrix: (H, W, N) int current per-pixel layer recipe matrix.
            Uses the pipeline ``Top2Bottom`` convention (layer 0 = viewing
            surface). (材料矩阵，Top2Bottom)
        mask_solid: (H, W) bool solid-pixel mask. (实体像素掩码)
        color_replacements: ``{orig_hex: repl_hex}`` mapping in ``#rrggbb``
            lowercase form. (颜色替换字典)
        materials: Ordered :class:`core.material_color_solver.MaterialParams`
            list the image was quantised against. (耗材列表)
        layer_count: Number of layers per pixel. (每像素层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)

    Returns:
        ``(new_matched_rgb, new_material_matrix, applied_count)`` where
        ``applied_count`` is the number of replacements that actually
        touched any pixel. Array references may alias the inputs when no
        applicable replacement was found.
        返回新的匹配 RGB、材料矩阵以及实际生效的替换条数。
    """
    if not color_replacements or not materials:
        return matched_rgb, material_matrix, 0

    # Gather the original hex → target rgb pairs that actually touch pixels.
    # Solving is the bulk cost; skip any (orig, repl) whose orig pixels are
    # already gone from the image (e.g. earlier override removed them).
    # 先筛选出当前图像里确实存在的 orig → repl 对，避免无谓求解。
    jobs: list[tuple[str, tuple[int, int, int], np.ndarray]] = []
    repl_rgbs: list[tuple[int, int, int]] = []
    for orig_hex, repl_hex in color_replacements.items():
        try:
            orig_rgb_tuple = _hex_to_rgb_tuple(orig_hex)
            repl_rgb_tuple = _hex_to_rgb_tuple(repl_hex)
        except ValueError as exc:
            _log.warning("Skipping invalid hex pair %s→%s: %s",
                         orig_hex, repl_hex, exc)
            continue
        orig_mask = np.all(matched_rgb == np.asarray(orig_rgb_tuple, dtype=np.uint8), axis=-1)
        orig_mask &= mask_solid
        if not np.any(orig_mask):
            continue
        jobs.append((orig_hex, repl_rgb_tuple, orig_mask))
        repl_rgbs.append(repl_rgb_tuple)

    if not jobs:
        return matched_rgb, material_matrix, 0

    unique_repl_srgb = np.asarray(repl_rgbs, dtype=np.uint8)

    # Prefer the persisted cache for O(log K) lookups per target; fall back
    # to the strict MITM solver otherwise.
    # 优先走持久化缓存；无缓存时退回严格 MITM 求解器。
    try:
        from core.material_cache import DEFAULT_GRID_RESOLUTION
        from core.material_color_solver import MITM_MAX_LAYER_COUNT
        from core.material_lut_provider import load_solver_cache, load_solver_runtime
        from core.material_lut_synthesis import (
            ensure_not_worse_than_smaller_N,
            solve_image_colors_optimal,
        )
    except ImportError as exc:
        _log.warning(
            "Solver modules unavailable (%s); replacements skipped",
            exc,
        )
        return matched_rgb, material_matrix, 0

    effective_grid = int(grid_resolution or DEFAULT_GRID_RESOLUTION)
    cache, _actual_grid = load_solver_cache(
        materials=materials,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        grid_resolution=effective_grid,
    )
    try:
        if cache is not None:
            matched_rgb_unique, recipes_unique, delta_e = cache.lookup(
                unique_repl_srgb, materials
            )
            solver_path = "cache"
        elif int(layer_count) > MITM_MAX_LAYER_COUNT:
            # Deep stacks: MITM is infeasible; use the candidate runtime
            # (layer-wise DP). 深叠层：MITM 不可行，改用候选运行时（逐层 DP）。
            runtime, _runtime_grid = load_solver_runtime(
                materials=materials,
                layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
                grid_resolution=effective_grid,
            )
            matched_rgb_unique, recipes_unique, delta_e = runtime.lookup(
                unique_repl_srgb, materials
            )
            solver_path = "runtime"
        else:
            matched_rgb_unique, recipes_unique, delta_e = solve_image_colors_optimal(
                unique_repl_srgb,
                materials,
                layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
            )
            solver_path = "mitm"
    except (ValueError, TypeError, RuntimeError, OSError) as exc:
        _log.warning(
            "Solver call failed (%s); %d replacements skipped",
            exc, len(jobs),
        )
        return matched_rgb, material_matrix, 0

    # Enforce "N-layer recipe not worse than any k<N + white padding" on the
    # replacement solves, mirroring the P03 guarantee. Failure here must not
    # block replacements; on exception we keep the baseline recipes and log.
    # (按 P03 的方式，对替换求解结果施加跨 N 不劣保证；若 fallback 失败
    # 则保留基线 recipe 并记录日志，确保替换流程不被中断。)
    try:
        matched_rgb_unique, recipes_unique, delta_e, fallback_stats = (
            ensure_not_worse_than_smaller_N(
                unique_repl_srgb,
                materials,
                matched_rgb_unique,
                recipes_unique,
                delta_e,
                target_layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
            )
        )
        if fallback_stats["applied"] and fallback_stats["improved_pixels"] > 0:
            _log.debug(
                "Not-worse fallback replaced %d/%d replacement "
                "colours (mean ΔE %.2f→%.2f, max ΔE %.2f→%.2f)",
                fallback_stats["improved_pixels"],
                int(unique_repl_srgb.shape[0]),
                fallback_stats["mean_delta_e_before"],
                fallback_stats["mean_delta_e_after"],
                fallback_stats["max_delta_e_before"],
                fallback_stats["max_delta_e_after"],
            )
    except (ValueError, TypeError, RuntimeError) as exc:
        _log.warning(
            "Not-worse fallback failed (%s); keeping baseline recipes",
            exc,
        )

    # Solver output is Bottom2Top; the pipeline stores Top2Bottom. Mirror the
    # same reversal used by P03 (see core/pipeline/p03_core_processing.py) so
    # the material_matrix convention is preserved.
    # 求解器输出 Bottom2Top，流水线统一 Top2Bottom；按 P03 的同一方式反转。
    if recipes_unique.shape[1] > 1:
        recipes_unique = np.ascontiguousarray(recipes_unique[:, ::-1])

    new_matched_rgb = matched_rgb.copy()
    recipe_layers = int(recipes_unique.shape[1])
    new_material_matrix = material_matrix.copy()

    # Resize material_matrix to the solver's layer count before per-pixel
    # writes. Short source matrices need padding; longer cached matrices need
    # trimming so boolean-index writes do not broadcast-error.
    # 写入前把 material_matrix 调整到求解器层数：短矩阵补齐，长矩阵裁剪。
    if new_material_matrix.shape[2] < recipe_layers:
        pad_layers = recipe_layers - new_material_matrix.shape[2]
        pad = np.zeros(
            (*new_material_matrix.shape[:2], pad_layers),
            dtype=new_material_matrix.dtype,
        )
        new_material_matrix = np.concatenate([new_material_matrix, pad], axis=2)
    elif new_material_matrix.shape[2] > recipe_layers:
        new_material_matrix = new_material_matrix[:, :, :recipe_layers].copy()

    applied = 0
    for job_idx, (orig_hex, _repl_rgb, orig_mask) in enumerate(jobs):
        achieved_rgb = matched_rgb_unique[job_idx]
        recipe = recipes_unique[job_idx]
        new_matched_rgb[orig_mask] = achieved_rgb
        new_material_matrix[orig_mask] = recipe.astype(
            new_material_matrix.dtype, copy=False
        )
        applied += 1
        _log.debug(
            "%s %s → rgb(%d,%d,%d) ΔE=%.2f recipe=%s",
            solver_path,
            orig_hex,
            int(achieved_rgb[0]), int(achieved_rgb[1]), int(achieved_rgb[2]),
            float(delta_e[job_idx]),
            recipe.tolist(),
        )

    return new_matched_rgb, new_material_matrix, applied


def _apply_dynamic_material_archive_color_replacements(
    matched_rgb: np.ndarray,
    material_matrix: np.ndarray,
    mask_solid: np.ndarray,
    target_rgb_map: np.ndarray,
    color_replacements: dict[str, str],
    materials: list,
    *,
    backing_material_index: int,
    min_layer_count: int,
    max_layer_count: int,
    delta_e00_tolerance: float,
    layer_height_mm: float,
    substrate: str,
    dynamic_layer_info: dict | None,
    material_solver_info: dict | None,
) -> tuple[np.ndarray, np.ndarray, int, dict, dict, np.ndarray]:
    """Apply replacements through the exact dynamic material solver.

    Re-solves the complete current target set because the fixed-maximum
    comparison uses request-local target coherence. Every automatic target is
    then rebuilt from the same solve, preserving the configured print width.

    重新求解当前完整目标集合，因为固定最大层数基线使用请求内目标色一致性；
    随后用同一次求解重建全部自动目标，并保持最大宽度打印矩阵。
    """

    from core.material_dynamic_solver import DynamicMaterialCandidateError

    current_info = deepcopy(dynamic_layer_info or {})
    current_solver_info = deepcopy(material_solver_info or {})
    if not isinstance(target_rgb_map, np.ndarray):
        raise DynamicMaterialCandidateError(
            "dynamic target RGB map is unavailable or inconsistent",
            layer_count=int(max_layer_count),
            phase="target_map",
        )
    target_map = np.asarray(target_rgb_map, dtype=np.uint8)
    if target_map.shape != np.asarray(matched_rgb).shape:
        raise DynamicMaterialCandidateError(
            "dynamic target RGB map is unavailable or inconsistent",
            layer_count=int(max_layer_count),
            phase="target_map",
        )
    if not color_replacements:
        return (
            matched_rgb,
            material_matrix,
            0,
            current_info,
            current_solver_info,
            target_map,
        )
    if not materials:
        raise DynamicMaterialCandidateError(
            "selected material parameters are unavailable",
            layer_count=int(max_layer_count),
            phase="runtime_load",
        )
    matrix = np.asarray(material_matrix)
    if matrix.ndim != 3 or matrix.shape[2] != int(max_layer_count):
        raise DynamicMaterialCandidateError(
            "dynamic material matrix width does not match configured maximum",
            layer_count=int(max_layer_count),
            phase="result_validation",
        )

    jobs: list[tuple[tuple[int, int, int], np.ndarray]] = []
    solid_mask = np.asarray(mask_solid, dtype=bool)
    updated_target_map = target_map.copy()
    for orig_hex, replacement_hex in color_replacements.items():
        try:
            original = _hex_to_rgb_tuple(orig_hex)
            target = _hex_to_rgb_tuple(replacement_hex)
        except ValueError as exc:
            _log.warning(
                "Invalid dynamic material replacement skipped",
                extra={
                    "event": "dynamic_material_replacement_invalid_hex",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "original_hex": str(orig_hex),
                    "replacement_hex": str(replacement_hex),
                },
            )
            continue
        original_mask = (
            np.all(
                np.asarray(matched_rgb) == np.asarray(original, dtype=np.uint8),
                axis=-1,
            )
            & solid_mask
        )
        if not np.any(original_mask):
            continue
        target_key = tuple(int(value) for value in target)
        jobs.append((target_key, original_mask))
        updated_target_map[original_mask] = np.asarray(
            target_key,
            dtype=np.uint8,
        )

    if not jobs:
        return (
            matched_rgb,
            material_matrix,
            0,
            current_info,
            current_solver_info,
            target_map,
        )

    target_rows, target_counts = np.unique(
        updated_target_map[solid_mask],
        axis=0,
        return_counts=True,
    )
    if target_rows.shape[0] == 0:
        raise DynamicMaterialCandidateError(
            "dynamic replacement target image contains no printable colours",
            target_srgb=jobs[0][0],
            layer_count=int(max_layer_count),
            phase="target_map",
        )
    (
        _resolved,
        _recipes,
        _delta_e00,
        new_info,
        new_solver_info,
    ) = _solve_dynamic_material_targets(
        unique_colors=np.asarray(target_rows, dtype=np.uint8),
        pixel_counts=np.asarray(target_counts, dtype=np.int64),
        materials=materials,
        backing_material_index=int(backing_material_index),
        layer_height_mm=float(layer_height_mm),
        substrate=str(substrate),
        min_layer_count=int(min_layer_count),
        max_layer_count=int(max_layer_count),
        delta_e00_tolerance=float(delta_e00_tolerance),
    )
    solved_colors = new_info.get("colors") if isinstance(new_info, dict) else None
    entries_by_target: dict[tuple[int, int, int], dict] = {}
    for entry in solved_colors if isinstance(solved_colors, list) else []:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target_srgb")
        if isinstance(target, (list, tuple)) and len(target) == 3:
            entries_by_target[tuple(int(value) for value in target)] = entry

    new_rgb = np.asarray(matched_rgb).copy()
    new_matrix = matrix.copy()
    for target_row in target_rows:
        target = tuple(int(value) for value in target_row)
        entry = entries_by_target.get(target)
        if entry is None:
            raise DynamicMaterialCandidateError(
                "no dynamic metadata entry is available for a replacement target",
                target_srgb=target,
                layer_count=int(max_layer_count),
                phase="exact_search",
            )
        achieved = entry.get("matched_srgb")
        print_recipe = entry.get("print_recipe_top_to_bottom")
        if (
            not isinstance(achieved, (list, tuple))
            or len(achieved) != 3
            or not isinstance(print_recipe, (list, tuple))
            or len(print_recipe) != int(max_layer_count)
        ):
            raise DynamicMaterialCandidateError(
                "dynamic replacement metadata is inconsistent",
                target_srgb=target,
                layer_count=int(max_layer_count),
                phase="result_validation",
            )
        target_mask = np.all(updated_target_map == target_row, axis=-1) & solid_mask
        new_rgb[target_mask] = np.asarray(achieved, dtype=np.uint8)
        new_matrix[target_mask] = np.asarray(
            print_recipe,
            dtype=new_matrix.dtype,
        )

    merged_solver_info = current_solver_info
    merged_solver_info.update(new_solver_info)
    return (
        new_rgb,
        new_matrix,
        len(jobs),
        new_info,
        merged_solver_info,
        updated_target_map,
    )


def _normalize_color_replacements_input(color_replacements):
    """Normalize color replacement input to unified {hex: hex} dict.
    兼容 dict / replacement_regions(list) 两种替换输入，统一为 {hex: hex}。

    Args:
        color_replacements: dict 或 list 格式的颜色替换输入

    Returns:
        dict: 统一格式的 {src_hex: dst_hex} 映射
    """
    if not color_replacements:
        return {}

    if isinstance(color_replacements, dict):
        out = {}
        for src, dst in color_replacements.items():
            if not isinstance(src, str) or not isinstance(dst, str):
                continue
            s = src.strip().lower()
            d = dst.strip().lower()
            if s and d:
                out[s] = d
        return out

    if isinstance(color_replacements, list):
        out = {}
        for item in color_replacements:
            if not isinstance(item, dict):
                continue
            src = (
                (
                    item.get("matched")
                    or item.get("matched_hex")
                    or item.get("source")
                    or item.get("quantized")
                    or item.get("quantized_hex")
                    or item.get("selected_color")
                    or ""
                )
                .strip()
                .lower()
            )
            dst = (
                (item.get("replacement") or item.get("replacement_hex") or item.get("replacement_color") or "")
                .strip()
                .lower()
            )
            if src and dst:
                out[src] = dst
        return out

    return {}


def _normalize_replayed_color_replacements_input(
    replacement_records: object,
    matched_rgb: np.ndarray | None,
    quantized_image: np.ndarray | None,
    mask_solid: np.ndarray | None,
) -> dict[str, str]:
    """Resolve portable whole-image edits against the active material map.
    按当前耗材映射重新解析项目中的全图改色。

    ``matched_hex`` belongs to the material set used when a project was
    saved. ``quantized_hex`` identifies the stable source-image color, so it
    can locate the corresponding current matches after a LUT or material
    change. Malformed or legacy records retain the historical matched-color
    fallback.

    Args:
        replacement_records: Saved API-format replacement records.
            (保存的 API 格式替换记录。)
        matched_rgb: Current material-matched RGB image. (当前匹配图。)
        quantized_image: Current quantized source image. (当前量化源图。)
        mask_solid: Current printable-pixel mask. (当前实体像素掩码。)

    Returns:
        Current matched-color to target-color mappings.
        (当前匹配色到目标色的映射。)
    """
    fallback = _normalize_color_replacements_input(replacement_records)
    if not isinstance(replacement_records, list):
        return fallback
    if matched_rgb is None or quantized_image is None:
        return fallback

    matched = np.asarray(matched_rgb)
    quantized = np.asarray(quantized_image)
    if matched.ndim != 3 or matched.shape[-1] != 3:
        return fallback
    if quantized.shape != matched.shape:
        return fallback

    solid = np.asarray(mask_solid, dtype=bool)
    if solid.shape != matched.shape[:2]:
        solid = np.ones(matched.shape[:2], dtype=bool)

    resolved: dict[str, str] = {}
    for item in replacement_records:
        if not isinstance(item, dict):
            continue
        item_fallback = _normalize_color_replacements_input([item])
        if not item_fallback:
            continue
        fallback_source, replacement_hex = next(iter(item_fallback.items()))
        quantized_hex = item.get("quantized") or item.get("quantized_hex")
        if not isinstance(quantized_hex, str):
            resolved[fallback_source] = replacement_hex
            continue
        try:
            quantized_rgb = np.asarray(
                _hex_to_rgb_tuple(quantized_hex),
                dtype=quantized.dtype,
            )
        except (TypeError, ValueError):
            resolved[fallback_source] = replacement_hex
            continue

        source_mask = np.all(quantized == quantized_rgb, axis=-1) & solid
        if not np.any(source_mask):
            resolved[fallback_source] = replacement_hex
            continue

        current_matches = np.unique(matched[source_mask], axis=0)
        if current_matches.size == 0:
            resolved[fallback_source] = replacement_hex
            continue
        for current_rgb in current_matches:
            current_hex = "#{:02x}{:02x}{:02x}".format(
                int(current_rgb[0]),
                int(current_rgb[1]),
                int(current_rgb[2]),
            )
            resolved[current_hex] = replacement_hex

    return resolved


def _apply_region_replacement(image_rgb, region_mask, replacement_rgb):
    """Apply replacement color only within region_mask coverage area.
    仅在 region_mask 覆盖区域应用替换色。

    Args:
        image_rgb (np.ndarray): (H, W, 3) uint8 RGB 图像
        region_mask (np.ndarray): (H, W) bool 区域掩码
        replacement_rgb: (R, G, B) 替换颜色

    Returns:
        np.ndarray: 替换后的 RGB 图像副本
    """
    out = image_rgb.copy()
    out[region_mask] = np.array(replacement_rgb, dtype=np.uint8)
    return out


def _apply_regions_to_raster_outputs(
    matched_rgb, material_matrix, mask_solid, replacement_regions, lut_index_resolver, ref_stacks
):
    """Apply region replacements in order to raster outputs (matched_rgb + material_matrix).
    按 regions 顺序覆盖 raster 输出（matched_rgb + material_matrix）。

    Args:
        matched_rgb (np.ndarray): (H, W, 3) uint8 匹配后的 RGB
        material_matrix (np.ndarray): (H, W, N) int 材料矩阵
        mask_solid (np.ndarray): (H, W) bool 实体掩码
        replacement_regions (list): 区域替换列表
        lut_index_resolver (callable): RGB → LUT 索引的解析函数
        ref_stacks (np.ndarray): LUT 参考堆叠数组

    Returns:
        tuple: (out_rgb, out_mat) 更新后的 RGB 和材料矩阵
    """
    out_rgb = matched_rgb.copy()
    out_mat = material_matrix.copy()

    for item in replacement_regions or []:
        region_mask = item.get("mask")
        replacement_hex = item.get("replacement")
        if region_mask is None or not replacement_hex:
            continue

        effective_mask = region_mask & mask_solid
        if not np.any(effective_mask):
            continue

        replacement_rgb = _hex_to_rgb_tuple(replacement_hex)
        out_rgb[effective_mask] = np.array(replacement_rgb, dtype=np.uint8)

        lut_idx = int(lut_index_resolver(replacement_rgb))
        out_mat[effective_mask] = ref_stacks[lut_idx]

    return out_rgb, out_mat


def _compute_connected_region_mask_4n(quantized_image, mask_solid, x, y):
    """Compute connected region mask using 4-neighbor connectivity from click point.
    基于 4 邻接计算点击像素所属连通域掩码。

    Args:
        quantized_image (np.ndarray): (H, W, 3) uint8 量化图像
        mask_solid (np.ndarray): (H, W) bool 实体掩码
        x (int): 点击 X 坐标
        y (int): 点击 Y 坐标

    Returns:
        np.ndarray: (H, W) bool 连通域掩码
    """
    h, w = quantized_image.shape[:2]
    if not (0 <= x < w and 0 <= y < h) or not mask_solid[y, x]:
        return np.zeros((h, w), dtype=bool)

    target = quantized_image[y, x]
    eligible = (
        np.all(quantized_image == target, axis=-1)
        & np.asarray(mask_solid, dtype=bool)
    )
    if not eligible[y, x]:
        return np.zeros((h, w), dtype=bool)

    # Fast path: OpenCV's native flood fill is much faster than a Python
    # deque loop on large previews while preserving 4-neighbour semantics.
    try:
        fill = np.ascontiguousarray(eligible.astype(np.uint8))
        cv2.floodFill(fill, None, (int(x), int(y)), 2, flags=4)
        return fill == 2
    except cv2.error:
        # Keep the previous pure-Python path as a conservative fallback for
        # unusual OpenCV builds or unexpected array layouts.
        pass

    out = np.zeros((h, w), dtype=bool)
    q = deque([(x, y)])
    out[y, x] = True

    while q:
        cx, cy = q.popleft()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < w and 0 <= ny < h and not out[ny, nx]:
                if eligible[ny, nx]:
                    out[ny, nx] = True
                    q.append((nx, ny))

    return out


def _pad_recipe_to_layers(
    recipe: list[int],
    target_layers: int,
    base_channel_idx: int,
    layer_order: str,
) -> list[int]:
    if len(recipe) >= target_layers:
        return recipe[:target_layers]
    pad_count = target_layers - len(recipe)
    if layer_order == "Bottom2Top":
        return [int(base_channel_idx)] * pad_count + [int(v) for v in recipe]
    return [int(v) for v in recipe] + [int(base_channel_idx)] * pad_count


def _upgrade_material_matrix_layers(
    material_matrix: np.ndarray,
    target_layers: int,
    base_channel_idx: int,
    layer_order: str,
    mask_solid: np.ndarray | None = None,
) -> np.ndarray:
    """Grow ``material_matrix`` to ``target_layers`` using ``mask_solid`` aware pads.

    The new layers must satisfy two contradictory constraints:

    - ``~mask_solid`` (transparent background already marked ``-1`` by
      ``p03_core_processing``) must stay ``-1`` so ``s06_voxel_building`` /
      ``s07_mesh_generation`` do not emit a ring-shaped mesh around the
      silhouette at the extended Z ("整块白矩形包裹 / 透明通道失效"
      regression).
    - ``mask_solid`` non-override pixels must keep a real material so the
      extended columns stay continuous with the backing slab. Padding them
      with ``-1`` leaves the user's grown layers visually empty outside the
      override ("第 6 层空层" regression).

    The pad slab starts at ``-1`` everywhere and ``mask_solid`` interior
    cells are written to ``base_channel_idx`` (the LUT's base material,
    normally White on CMYW). ``mask_solid=None`` means "caller didn't provide
    solidity info" (rare; legacy callers) — fall back to the old all-base
    behaviour but still honour the dtype promotion so ``-1`` cells written
    by earlier stages survive.

    扩展层必须同时满足两件事：(a) ~mask_solid (p03 标成 -1 的透明背景)
    保持 -1 空气，否则 S07 会围着模型生成白色 mesh；(b) mask_solid 内
    非 override 像素保留 base channel，避免第 6 层塌成空层。pad slab
    整体置 -1，只在 mask_solid 位置写 base_channel_idx。mask_solid
    缺省时兼容老调用方：全部填 base_channel_idx。
    """

    current_layers = int(material_matrix.shape[2])
    if current_layers >= target_layers:
        return material_matrix
    # uint dtypes would wrap ``-1`` into ``255`` and reintroduce the exact
    # mesh-explosion bug under a different channel id, so promote to a
    # signed dtype before padding.
    # uint 类型会把 ``-1`` 绕回 255 把同一个 bug 换个编号重来，所以先升
    # 到 signed 类型再 pad。
    if np.issubdtype(material_matrix.dtype, np.unsignedinteger):
        material_matrix = material_matrix.astype(np.int32)
    pad_shape = (*material_matrix.shape[:2], target_layers - current_layers)
    if mask_solid is None:
        pad = np.full(pad_shape, int(base_channel_idx), dtype=material_matrix.dtype)
    else:
        mask_solid_arr = np.asarray(mask_solid, dtype=bool)
        if mask_solid_arr.shape != material_matrix.shape[:2]:
            # Shape mismatch would silently paint the whole slab with base;
            # callers always pass a matching mask, so treat this as a
            # programming error rather than silently degrading.
            # 形状不匹配说明调用方传错了，直接报错避免静默污染扩展层。
            raise ValueError(
                f"mask_solid shape {mask_solid_arr.shape} does not match "
                f"material_matrix spatial shape {material_matrix.shape[:2]}"
            )
        pad = np.full(pad_shape, -1, dtype=material_matrix.dtype)
        pad[mask_solid_arr] = int(base_channel_idx)
    if layer_order == "Bottom2Top":
        return np.concatenate([pad, material_matrix], axis=2)
    return np.concatenate([material_matrix, pad], axis=2)


def run(ctx: dict) -> dict:
    """Apply color replacements: global, region, and matched_rgb override.
    应用颜色替换：全局替换、区域替换、matched_rgb 覆盖。

    PipelineContext 输入键 / Input keys:
        - matched_rgb (np.ndarray): (H, W, 3) uint8 匹配后的 RGB
        - material_matrix (np.ndarray): (H, W, N) int 材料矩阵
        - mask_solid (np.ndarray): (H, W) bool 实体掩码
        - processor (LuminaImageProcessor): 处理器实例（用于 KDTree 查询）
        - color_replacements (dict | None): 全局颜色替换映射
        - replacement_regions (list | None): 区域替换列表
        - matched_rgb_path (str | None): 预计算 matched_rgb .npy 文件路径
        - height_identity_rgb_path (str | None): 稳定高度身份 RGB .npy 路径
        - material_matrix_path (str | None): 预计算 material_matrix .npy 文件路径
        - final_material_matrix_is_authoritative (bool): 颜色映射后保留最终材料矩阵
        - final_material_matrix_authority_mask_path (str | None): 最终矩阵权威区域

    PipelineContext 输出键 / Output keys:
        - matched_rgb (np.ndarray): 更新后的 RGB（如有替换）
        - material_matrix (np.ndarray): 更新后的材料矩阵（如有替换）
        - height_identity_rgb (np.ndarray): 替换前的稳定逐像素高度身份
    """
    _t0 = time.perf_counter()

    matched_rgb = ctx["matched_rgb"]
    material_matrix = ctx["material_matrix"]
    mask_solid = ctx["mask_solid"]
    # processor is unset in material-archive mode (S02 short-circuits and never
    # constructs a LuminaImageProcessor). All processor-dependent paths below
    # guard with `if processor is not None` and skip with a warning when absent.
    processor = ctx.get("processor")
    color_replacements = ctx.get("color_replacements")
    replacement_regions = ctx.get("replacement_regions")
    matched_rgb_path = ctx.get("matched_rgb_path")
    height_identity_rgb_path = ctx.get("height_identity_rgb_path")
    material_matrix_path = ctx.get("material_matrix_path")
    final_material_matrix_is_authoritative = bool(
        ctx.get("final_material_matrix_is_authoritative", False)
    )
    final_material_matrix_authority_mask_path = ctx.get(
        "final_material_matrix_authority_mask_path"
    )
    authoritative_material_matrix = None
    authoritative_material_mask = None
    recipe_overrides = ctx.get("recipe_overrides") or []
    recipe_override_masks_path = ctx.get("recipe_override_masks_path")
    lut_metadata = ctx.get("lut_metadata")
    requested_color_layers = ctx.get("color_layers")
    requested_layer_height_mm = ctx.get("layer_height_mm")
    dynamic_material_enabled = bool(
        ctx.get("material_dynamic_layer_count_enabled", False)
    )

    edit_projection_grid = None
    height_identity_rgb = None
    if ctx.get("edit_projection") is not None:
        edit_projection_grid, edit_projection_mode = (
            _resolve_edit_projection_grid(
                ctx,
                target_shape=tuple(int(value) for value in mask_solid.shape),
            )
        )
        if edit_projection_mode == "delta":
            (
                matched_rgb,
                material_matrix,
                height_identity_rgb,
                edit_projection_grid,
            ) = _replay_projected_preview_edits(
                ctx,
                fresh_matched_rgb=matched_rgb,
                fresh_material_matrix=material_matrix,
                target_mask_solid=mask_solid,
            )
        else:
            # Recipe masks are self-describing edit deltas. They need only the
            # normalized source grid; RGB/material baselines are unnecessary.
            height_identity_rgb = np.asarray(
                matched_rgb,
                dtype=np.uint8,
            ).copy()

    # ---- Override matched_rgb with pre-computed array if provided ----
    if matched_rgb_path is not None and edit_projection_grid is None:
        try:
            override_rgb = np.asarray(
                np.load(matched_rgb_path, allow_pickle=False),
                dtype=np.uint8,
            )
            override_has_valid_rank = (
                override_rgb.ndim == 3 and override_rgb.shape[2] == 3
            )
            override_matches_spatial_grid = (
                override_has_valid_rank
                and override_rgb.shape[:2] == mask_solid.shape
                and override_rgb.shape[:2] == material_matrix.shape[:2]
            )
            if not override_matches_spatial_grid:
                error_message = (
                    f"matched_rgb_path shape {override_rgb.shape} does not "
                    "match the material/mask grid"
                )
                _log.warning(
                    "Ignoring matched RGB artifact with an incompatible grid",
                    extra={
                        "event": "matched_rgb_artifact_shape_mismatch",
                        "error_type": "ValueError",
                        "error_message": error_message,
                        "path": str(matched_rgb_path),
                    },
                )
            else:
                if override_rgb.shape == matched_rgb.shape:
                    # Detect pixels that differ between original and override.
                    diff_mask = np.any(matched_rgb != override_rgb, axis=-1) & mask_solid
                    if np.any(diff_mask) and processor is not None:
                        diff_pixels = override_rgb[diff_mask]  # (N, 3)
                        unique_colors = np.unique(diff_pixels, axis=0)
                        for color in unique_colors:
                            color_mask = np.all(override_rgb == color, axis=-1) & diff_mask
                            repl_lab = processor._rgb_to_lab(color.reshape(1, 3))
                            _, lut_idx = processor.kdtree.query(repl_lab)
                            new_stacks = processor.ref_stacks[lut_idx[0]]
                            material_matrix[color_mask] = new_stacks
                        _log.debug(
                            f"matched_rgb override applied: "
                            f"{np.sum(diff_mask)} pixels updated across {len(unique_colors)} colors"
                        )
                    elif np.any(diff_mask):
                        _log.debug(
                            "matched_rgb override: %d differing pixels skipped "
                            "(no LUT processor in material-archive mode)",
                            int(np.sum(diff_mask)),
                        )
                else:
                    _log.debug(
                        "matched_rgb override replaced the provisional S02 grid: %s -> %s",
                        tuple(matched_rgb.shape),
                        tuple(override_rgb.shape),
                    )
                matched_rgb = override_rgb
        except (OSError, ValueError, TypeError) as e:
            _log.warning(
                "Failed to load matched RGB artifact; using S02 result",
                extra={
                    "event": "matched_rgb_artifact_load_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "path": str(matched_rgb_path),
                },
            )

    # Relief height identity is independent from display colour, but its
    # spatial contract is defined by the final pre-replacement matched RGB.
    # Resolve cached matched_rgb first; then load the explicit identity or,
    # for legacy callers, snapshot that final matched plane.
    if height_identity_rgb_path is not None and edit_projection_grid is None:
        try:
            loaded_identity = np.load(
                height_identity_rgb_path,
                allow_pickle=False,
            )
            if loaded_identity.shape != matched_rgb.shape:
                raise ValueError(
                    "height identity shape does not match final matched RGB"
                )
            height_identity_rgb = np.asarray(
                loaded_identity,
                dtype=np.uint8,
            )
        except (OSError, ValueError, TypeError) as exc:
            _log.warning(
                "Failed to load height identity artifact; using final matched RGB",
                extra={
                    "event": "height_identity_artifact_load_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "path": str(height_identity_rgb_path),
                },
            )
    if height_identity_rgb is None:
        height_identity_rgb = np.asarray(matched_rgb, dtype=np.uint8).copy()

    if material_matrix_path is not None and edit_projection_grid is None:
        try:
            override_material_matrix = np.load(
                material_matrix_path,
                allow_pickle=False,
            )
            if final_material_matrix_is_authoritative:
                (
                    authoritative_material_matrix,
                    authoritative_material_mask,
                ) = _prepare_authoritative_material_override(
                    override_material_matrix,
                    material_matrix,
                    mask_solid,
                    final_material_matrix_authority_mask_path,
                )
                material_matrix = np.array(
                    authoritative_material_matrix,
                    copy=True,
                )
            elif override_material_matrix.shape != material_matrix.shape:
                _log.warning(
                    f"material_matrix_path shape {override_material_matrix.shape} "
                    f"does not match processed shape {material_matrix.shape}, ignoring override"
                )
            else:
                material_matrix = override_material_matrix
        except (OSError, ValueError, TypeError) as e:
            if final_material_matrix_is_authoritative:
                raise ValueError(
                    f"Invalid authoritative material matrix artifact: {e}"
                ) from e
            _log.warning(
                f"Failed to load material_matrix_path '{material_matrix_path}': {e}, "
                f"using original processed result"
            )

    # ---- Apply global color replacements ----
    effective_color_replacements = _normalize_color_replacements_input(color_replacements)
    if replacement_regions:
        api_format_replacements = _normalize_replayed_color_replacements_input(
            replacement_regions,
            matched_rgb,
            ctx.get("quantized_image"),
            mask_solid,
        )
        if api_format_replacements:
            effective_color_replacements.update(api_format_replacements)
            # Remove API-format items (no mask) from replacement_regions to avoid
            # _apply_regions_to_raster_outputs skipping them silently
            replacement_regions = [r for r in replacement_regions if r.get("mask") is not None]

    is_material_archive = (
        ctx.get("material_source") == "material_archive"
        and ctx.get("_material_params")
    )
    if effective_color_replacements and processor is None and not is_material_archive:
        _log.warning(
            "%d color replacements skipped (no LUT processor in material-archive mode)",
            len(effective_color_replacements),
        )
        effective_color_replacements = {}
    if effective_color_replacements and is_material_archive:
        # Material-archive mode re-solves every replacement target against
        # the saved MaterialParams palette (cache-first, MITM fallback) so
        # both matched_rgb and material_matrix stay internally consistent.
        # 材料档案模式：优先走持久化缓存，缓存未命中时 MITM 求解，保持 RGB
        # 与 material_matrix 同步。
        mats = ctx.get("_material_params") or []
        layer_count_mat = int(ctx.get("color_layers") or material_matrix.shape[2])
        layer_height_mat = float(ctx.get("layer_height_mm") or 0.08)
        substrate_mat = str(ctx.get("material_substrate") or "white")
        grid_res = ctx.get("grid_resolution")
        if bool(ctx.get("material_dynamic_layer_count_enabled", False)):
            from core.material_dynamic_solver import (
                DynamicMaterialCandidateError,
                DynamicMaterialSolverError,
            )

            backing_index = ctx.get("material_backing_material_index")
            if backing_index is None:
                backing_index = ctx.get("material_base_channel_idx", 0)
            try:
                (
                    matched_rgb,
                    material_matrix,
                    applied,
                    dynamic_layer_info,
                    material_solver_info,
                    quantized_image,
                ) = _apply_dynamic_material_archive_color_replacements(
                    matched_rgb,
                    material_matrix,
                    mask_solid,
                    ctx.get("quantized_image"),
                    effective_color_replacements,
                    mats,
                    backing_material_index=int(backing_index),
                    min_layer_count=int(
                        ctx.get("material_min_layer_count") or 5
                    ),
                    max_layer_count=int(
                        ctx.get("material_max_layer_count") or 10
                    ),
                    delta_e00_tolerance=float(
                        ctx.get("material_delta_e00_tolerance", 0.5)
                    ),
                    layer_height_mm=layer_height_mat,
                    substrate=substrate_mat,
                    dynamic_layer_info=ctx.get("material_dynamic_layer_info"),
                    material_solver_info=ctx.get("material_solver_info"),
                )
            except (
                DynamicMaterialCandidateError,
                DynamicMaterialSolverError,
                TypeError,
                ValueError,
            ) as exc:
                return _record_dynamic_material_error(ctx, exc)
            ctx["material_dynamic_layer_info"] = dynamic_layer_info
            ctx["material_solver_info"] = material_solver_info
            ctx["quantized_image"] = quantized_image
            ctx["color_layers"] = int(material_matrix.shape[2])
        else:
            matched_rgb, material_matrix, applied = (
                _apply_material_archive_color_replacements(
                    matched_rgb,
                    material_matrix,
                    mask_solid,
                    effective_color_replacements,
                    mats,
                    layer_count_mat,
                    layer_height_mat,
                    substrate_mat,
                    grid_resolution=grid_res,
                )
            )
        _log.debug("Applied %d material-archive color replacements", applied)
    elif effective_color_replacements:
        from core.color_replacement import ColorReplacementManager

        manager = ColorReplacementManager.from_dict(effective_color_replacements)
        old_rgb = matched_rgb.copy()
        matched_rgb = manager.apply_to_image(matched_rgb)
        _log.debug(f"Applied {len(manager)} color replacements")

        # Update material_matrix: find the replacement color's LUT entry
        for orig_hex, repl_hex in effective_color_replacements.items():
            orig_rgb_tuple = ColorReplacementManager._hex_to_color(orig_hex)
            repl_rgb_tuple = ColorReplacementManager._hex_to_color(repl_hex)
            orig_mask = np.all(old_rgb == orig_rgb_tuple, axis=-1) & np.asarray(
                mask_solid, dtype=bool
            )
            if not np.any(orig_mask):
                continue
            repl_lab = processor._rgb_to_lab(np.array([repl_rgb_tuple], dtype=np.uint8))
            _, lut_idx = processor.kdtree.query(repl_lab)
            lut_idx = lut_idx[0]
            new_stacks = processor.ref_stacks[lut_idx]
            material_matrix[orig_mask] = new_stacks
            lut_color = processor.lut_rgb[lut_idx]
            _log.debug(
                f"material_matrix: {orig_hex} -> LUT#{lut_idx} "
                f"rgb({lut_color[0]},{lut_color[1]},{lut_color[2]}) stacks={new_stacks}"
            )

    # ---- Apply explicit recipe overrides by region_id ----
    if recipe_overrides and recipe_override_masks_path:
        try:
            with open(recipe_override_masks_path, "rb") as f:
                region_masks = pickle.load(f)
        except (OSError, ValueError, TypeError, pickle.PickleError) as exc:
            _log.warning("Failed to load recipe override masks: %s", exc)
            region_masks = {}

        if isinstance(region_masks, dict):
            if edit_projection_grid is not None:
                try:
                    region_masks = {
                        str(region_id): edit_projection_grid.project_mask(
                            np.asarray(region_mask, dtype=bool),
                            target_solid=mask_solid,
                        )
                        for region_id, region_mask in region_masks.items()
                    }
                except (TypeError, ValueError) as exc:
                    raise CachedPreviewAnalysisError(
                        "Required recipe edit mask could not be projected"
                    ) from exc
            target_order = (
                getattr(lut_metadata, "layer_order", "Top2Bottom")
                if lut_metadata is not None
                else "Top2Bottom"
            )
            if lut_metadata is not None:
                base_channel_idx = int(getattr(lut_metadata, "base_channel_idx", 0) or 0)
            else:
                base_channel_idx = int(ctx.get("material_base_channel_idx", 0) or 0)
            if dynamic_material_enabled:
                from core.material_dynamic_solver import (
                    DynamicMaterialCandidateError,
                )

                target_layers = int(
                    ctx.get("material_max_layer_count") or 10
                )
                if int(material_matrix.shape[2]) != target_layers:
                    raise DynamicMaterialCandidateError(
                        "dynamic material matrix width does not match configured maximum",
                        layer_count=target_layers,
                        phase="recipe_overrides",
                    )
            else:
                target_layers = max(
                    int(material_matrix.shape[2]),
                    max((len(item.get("recipe", [])) for item in recipe_overrides if isinstance(item, dict)), default=0),
                )
                if requested_color_layers is not None:
                    target_layers = max(target_layers, int(requested_color_layers))
                material_matrix = _upgrade_material_matrix_layers(
                    material_matrix,
                    int(target_layers),
                    base_channel_idx,
                    target_order,
                    mask_solid=mask_solid,
                )
            try:
                from core.predictive_lut import predict_recipe_color
                from core.recipe_order import convert_recipe_between_orders
            except (ImportError, ModuleNotFoundError):
                predict_recipe_color = None
                convert_recipe_between_orders = None

            # Build a global virtual-material registry by deduping every
            # per-region virtual_materials list across all overrides; assign
            # each unique (name, hex) a stable global channel index starting
            # at ``lut_palette_length``. Each region's local virtual indices
            # are then remapped through this registry so the material_matrix
            # writes consistent channel ids no matter which region a given
            # virtual appeared in first.
            # 跨所有覆盖条目聚合 virtual_materials 并按 (name, hex) 去重，从
            # ``lut_palette_length`` 开始给每条虚拟耗材分配稳定的全局通道索引；
            # 各 region 的本地虚拟索引再统一重映射到该全局表，保证
            # material_matrix 里的通道 id 跨 region 一致。
            lut_palette_length = _resolve_recipe_native_palette_length(ctx, lut_metadata)
            from core.recipe_virtual_materials import build_virtual_material_registry

            virtual_registry, per_region_virtual_maps = build_virtual_material_registry(
                recipe_overrides, lut_palette_length,
            )

            if virtual_registry:
                _extend_ctx_palette_with_virtuals(
                    ctx,
                    lut_palette_length,
                    virtual_registry,
                )

            for item in recipe_overrides:
                if not isinstance(item, dict):
                    continue
                region_id = str(item.get("region_id", "")).strip()
                region_mask = region_masks.get(region_id)
                if region_mask is None:
                    continue
                effective_mask = np.asarray(region_mask, dtype=bool) & mask_solid
                if not np.any(effective_mask):
                    continue

                recipe_raw = [int(v) for v in item.get("recipe", [])]
                dynamic_print_recipe: list[int] | None = None
                if dynamic_material_enabled:
                    from core.material_dynamic_solver import (
                        DynamicMaterialCandidateError,
                    )

                    actual = item.get("actual_recipe_top_to_bottom")
                    saved_print = item.get("print_recipe_top_to_bottom")
                    actual_count = item.get("actual_layer_count")
                    padding_count = item.get("padding_layer_count")
                    minimum_layers = int(
                        ctx.get("material_min_layer_count") or 5
                    )
                    backing_index = ctx.get("material_backing_material_index")
                    if backing_index is None:
                        backing_index = ctx.get("material_base_channel_idx", 0)
                    actual_length = len(actual) if isinstance(actual, list) else -1
                    if (
                        not isinstance(actual, list)
                        or int(actual_count or -1) != actual_length
                        or not minimum_layers <= actual_length <= int(target_layers)
                        or not isinstance(saved_print, list)
                        or len(saved_print) != int(target_layers)
                        or int(padding_count or 0)
                        != int(target_layers) - actual_length
                        or [int(value) for value in saved_print[:actual_length]]
                        != [int(value) for value in actual]
                        or any(
                            int(value) != int(backing_index)
                            for value in saved_print[actual_length:]
                        )
                    ):
                        raise DynamicMaterialCandidateError(
                            "dynamic recipe override metadata is inconsistent",
                            layer_count=int(target_layers),
                            phase="recipe_overrides",
                        )
                    recipe_raw = [int(value) for value in actual]
                    dynamic_print_recipe = [
                        int(value) for value in saved_print
                    ]
                # Rewrite any local virtual indices into the deduped global
                # registry so every region speaks the same channel vocabulary.
                # 把本 region 的本地虚拟索引改写为全局虚拟索引。
                local_map = per_region_virtual_maps.get(region_id) or {}
                if local_map:
                    recipe_raw = [
                        int(local_map.get(int(v), int(v))) for v in recipe_raw
                    ]
                    if dynamic_print_recipe is not None:
                        dynamic_print_recipe = [
                            int(local_map.get(int(v), int(v)))
                            for v in dynamic_print_recipe
                        ]
                recipe_order = str(item.get("layer_order", target_order))
                if dynamic_print_recipe is not None:
                    normalized_recipe = dynamic_print_recipe
                    recipe_order = "Top2Bottom"
                else:
                    normalized_recipe = recipe_raw
                    if convert_recipe_between_orders is not None:
                        normalized_recipe = convert_recipe_between_orders(recipe_raw, recipe_order, target_order)
                    normalized_recipe = _pad_recipe_to_layers(
                        normalized_recipe,
                        int(material_matrix.shape[2]),
                        base_channel_idx,
                        target_order,
                    )
                # material_matrix dtype may be uint8 (capacity 256) which is
                # plenty for LUT.N + a handful of virtuals; upgrade on demand
                # if a virtual index would overflow.
                # material_matrix 通常是 uint8，虚拟耗材加起来远小于 256；
                # 真遇到越界再升 dtype。
                max_index = max(normalized_recipe) if normalized_recipe else 0
                if (
                    max_index > np.iinfo(material_matrix.dtype).max
                    if np.issubdtype(material_matrix.dtype, np.integer)
                    else False
                ):
                    material_matrix = material_matrix.astype(np.int32)
                material_matrix[effective_mask] = np.asarray(normalized_recipe, dtype=material_matrix.dtype)

                # The forward model only understands real LUT channels. Skip
                # prediction when the recipe carries virtual indices and let
                # the apply endpoint's preview colour (already baked into
                # ``matched_rgb`` via the cached preview) stand.
                # 前向模型只认真实 LUT 通道；recipe 里带虚拟索引时跳过预测，
                # 保留 apply 端点兜底得到的预览色。
                recipe_has_virtual = any(
                    ch >= lut_palette_length for ch in recipe_raw
                )
                if (
                    lut_metadata is not None
                    and predict_recipe_color is not None
                    and not recipe_has_virtual
                ):
                    try:
                        predicted = predict_recipe_color(
                            lut_metadata,
                            recipe_raw,
                            float(requested_layer_height_mm or getattr(lut_metadata, "layer_height_mm", 0.08)),
                            int(material_matrix.shape[2]),
                            recipe_order,
                        )
                        rgb = np.asarray(predicted.get("rgb", []), dtype=np.uint8)
                        if rgb.shape == (3,):
                            matched_rgb[effective_mask] = rgb
                    except (AttributeError, ImportError, ModuleNotFoundError, TypeError, ValueError) as exc:
                        _log.warning("Recipe color prediction failed for %s: %s", region_id, exc)
                elif recipe_has_virtual:
                    # Paint the region with the topmost virtual material hex so
                    # the 2D preview and downstream stages see the user's
                    # intent even without a forward model call.
                    # 顶层若是虚拟耗材，直接按其 hex 给 region 上色，保证 2D
                    # 预览与后续阶段都看到用户意图色。
                    top_channel = (
                        recipe_raw[0] if target_order == "Top2Bottom" else recipe_raw[-1]
                    )
                    if top_channel >= lut_palette_length and virtual_registry:
                        offset = top_channel - lut_palette_length
                        if 0 <= offset < len(virtual_registry):
                            intent_hex = virtual_registry[offset]["hex"]
                            try:
                                matched_rgb[effective_mask] = np.asarray(
                                    _hex_to_rgb_tuple(intent_hex), dtype=np.uint8
                                )
                            except (ValueError, TypeError) as exc:
                                _log.warning(
                                    "Virtual material hex %s unreadable for %s: %s",
                                    intent_hex,
                                    region_id,
                                    exc,
                                )

    # ---- Apply region replacements in-order ----
    if replacement_regions and processor is None:
        _log.warning(
            "%d replacement regions skipped (no LUT processor in material-archive mode)",
            len(replacement_regions),
        )
    elif replacement_regions:

        def _resolve_lut_index_for_rgb(replacement_rgb):
            repl_lab = processor._rgb_to_lab(np.array([replacement_rgb], dtype=np.uint8))
            _, lut_idx = processor.kdtree.query(repl_lab)
            return lut_idx[0]

        matched_rgb, material_matrix = _apply_regions_to_raster_outputs(
            matched_rgb,
            material_matrix,
            mask_solid,
            replacement_regions,
            _resolve_lut_index_for_rgb,
            processor.ref_stacks,
        )

    if authoritative_material_matrix is not None:
        # Complete cached analysis owns the whole matrix. Recipe-only
        # large-format inputs own only the union of their recipe regions:
        # global/scoped mappings must remain physically effective everywhere
        # else, even when an imported replacement list was never baked into
        # the preview cache used by the route helper.
        # 完整缓存分析拥有整张矩阵；recipe-only 大画幅只在配方区域
        # union 内拥有最终权威。其他像素保留本轮全局/区域替色的实体矩阵。
        if authoritative_material_mask is None:
            material_matrix = authoritative_material_matrix
        else:
            material_matrix[authoritative_material_mask] = (
                authoritative_material_matrix[authoritative_material_mask]
            )

    ctx["matched_rgb"] = matched_rgb
    ctx["material_matrix"] = material_matrix
    ctx["height_identity_rgb"] = height_identity_rgb

    _elapsed = time.perf_counter() - _t0
    _hifi_timings = ctx.get("_hifi_timings", {})
    _hifi_timings["color_replace_s"] = _elapsed
    ctx["_hifi_timings"] = _hifi_timings
    _log.debug(f"color_replace done: {_elapsed:.3f}s")
    return ctx
