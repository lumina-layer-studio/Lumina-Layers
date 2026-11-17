"""Shared input-validation helpers for S01 (raster) and P01 (preview).
S01（光栅生成）与 P01（预览）输入验证共享辅助函数。

This module hosts the bits of validation logic that ``s01_input_validation``
and ``p01_preview_validation`` previously duplicated verbatim — most notably
the entire ``material_archive`` branch (~50 LOC) plus the small LUT-path
resolution and quantize-colors clamp helpers — extracted in Phase 0 Sub-PR C
(see design doc §14.2.3).

Helpers do **not** emit structured-logging events directly with hard-coded
names; they accept the caller's logger and an ``event_prefix`` so the
caller's existing event taxonomy (``s01_*`` vs ``p01_*``) is preserved
so raster and preview diagnostics remain searchable by their workflow.

公共点：
- ``_validate_vector_svg_input(ctx, *, image_path, modeling_mode)``
- ``_resolve_lut_path_or_error(ctx, *, error_prefix)``
- ``_apply_material_archive_branch(ctx, *, log, event_prefix, ...)``
- ``_clamp_quantize_colors(value)``
"""

from __future__ import annotations

import logging
from typing import Any

from config import ModelingMode
from core.material_cache import ALLOWED_GRID_RESOLUTIONS, DEFAULT_GRID_RESOLUTION
from core.material_lut_provider import load_materials
from core.material_lut_synthesis import (
    build_material_preview_colors,
    build_material_slot_names,
    infer_material_archive_base_channel_idx,
)


__all__ = [
    "VECTOR_NATIVE_REQUIRES_SVG_DETAIL",
    "_clamp_quantize_colors",
    "_resolve_lut_path_or_error",
    "_apply_material_archive_branch",
    "_validate_vector_svg_input",
]


VECTOR_NATIVE_REQUIRES_SVG_DETAIL = (
    "⚠️ Vector Native mode requires SVG files!\n\n"
    "Your file is not an SVG. Please either:\n"
    "• Upload an SVG file, or\n"
    "• Switch to 'High-Fidelity' or 'Pixel Art' mode"
)


def _validate_vector_svg_input(
    ctx: dict,
    *,
    image_path: object,
    modeling_mode: ModelingMode,
) -> bool:
    """Validate and record whether an input can use native vector modeling.
    校验并记录输入是否可以使用原生矢量建模。

    Args:
        ctx: Pipeline context updated with ``is_svg_vector`` and, on mismatch,
            a user-facing ``error``.
        image_path: Source image path.
        modeling_mode: Normalized modeling mode.

    Returns:
        Whether the input is an SVG using native vector mode.
    """
    is_svg_vector = (
        modeling_mode == ModelingMode.VECTOR
        and isinstance(image_path, str)
        and image_path.lower().endswith(".svg")
    )
    ctx["is_svg_vector"] = is_svg_vector
    if (
        modeling_mode == ModelingMode.VECTOR
        and not is_svg_vector
        and isinstance(image_path, str)
        and not image_path.lower().endswith(".svg")
    ):
        ctx["error"] = VECTOR_NATIVE_REQUIRES_SVG_DETAIL
    return is_svg_vector


def _clamp_quantize_colors(value: int) -> int:
    """Clamp the K-Means colour count to the supported [8, 8192] range.
    将量化颜色数夹紧到支持的 [8, 8192] 范围内。

    The ceiling matches ``ConvertPreviewRequest.quantize_colors`` /
    ``ConvertGenerateRequest.quantize_colors`` (``le=8192``) and the
    frontend "unlock quantize colors" slider upper bound, so an unlocked
    request is no longer silently compressed back to 256.
    上限与 Pydantic 请求模型（``le=8192``）及前端"解锁量化颜色数"滑条
    对齐，勾选解锁后不会再被静默压回 256。

    Args:
        value: Requested K-Means colour count.

    Returns:
        Clamped integer in [8, 8192].
    """
    return max(8, min(8192, int(value)))


def _resolve_lut_path_or_error(
    ctx: dict,
    *,
    error_prefix: str,
) -> tuple[str | None, str | None]:
    """Resolve ``ctx['lut_path']`` to an actual filesystem path string.
    将 ``ctx['lut_path']`` 规整为实际的文件系统路径字符串。

    Accepts:
        - ``None`` -> returns ``(None, "<error_prefix>... select or upload ...")``.
        - ``str`` -> returns ``(value, None)``.
        - file-like with ``.name`` attribute -> returns ``(value.name, None)``.
        - anything else -> returns ``(None, "[ERROR] Invalid LUT file format")``.

    Args:
        ctx: Pipeline context carrying ``lut_path``.
        error_prefix: Caller-specific prefix for the "no path provided" error
            message. ``s01`` historically used
            ``"[WARNING] Please select or upload a .npy calibration file!"``;
            ``p01`` used ``"[WARNING] Please select or upload calibration file"``.
            Pass the literal full string the caller wants.

    Returns:
        Tuple ``(actual_lut_path, error_message)``. Exactly one is non-None.
    """
    lut_path = ctx.get("lut_path")
    if lut_path is None:
        return None, error_prefix
    if isinstance(lut_path, str):
        return lut_path, None
    if hasattr(lut_path, "name"):
        return lut_path.name, None
    return None, "[ERROR] Invalid LUT file format"


def _apply_material_archive_branch(
    ctx: dict,
    *,
    log: logging.Logger,
    event_prefix: str,
    default_layer_count: int = 5,
    default_layer_height_mm: float = 0.08,
) -> dict | str | None:
    """Apply the shared ``material_source == "material_archive"`` validation block.
    处理共享的 ``material_source == "material_archive"`` 验证分支。

    On success this updates ``ctx`` in place with the canonical material-archive
    keys (``actual_lut_path`` = ``"__material_archive__"``, ``color_conf``,
    ``slot_names``, ``preview_colors``, ``color_layers``, ``layer_height_mm``,
    ``_material_params``, ``material_source``, ``grid_resolution``) and emits a
    single ``f"{event_prefix}_material_archive_validated"`` debug event so the
    caller's existing event taxonomy is preserved byte-for-byte.

    On error this writes ``ctx['error']`` and returns ``"error"`` so the caller
    can early-return.

    Args:
        ctx: Pipeline context updated in place.
        log: Caller's structured logger (so log records carry the caller's
            module name, e.g. ``lumina.core.pipeline.s01_input_validation``).
        event_prefix: ``"s01"`` or ``"p01"``; used to compose event names.
        default_layer_count: Fallback color-layer count when not specified.
        default_layer_height_mm: Fallback layer height when not specified.

    Returns:
        - ``"error"`` if validation failed (``ctx['error']`` written).
        - ``"validated"`` if the material-archive branch was applied successfully.

        Note that this helper never returns ``None``; the typed signature is
        ``str`` for both outcomes so the caller can branch with a single check.
    """
    selected_materials = ctx.get("selected_materials") or []
    if not selected_materials:
        ctx["error"] = "[ERROR] No materials selected for material-archive mode"
        return "error"

    try:
        materials = load_materials(selected_materials, **({"materials_dir": ctx["materials_dir"]} if ctx.get("materials_dir") else {}))
    except (FileNotFoundError, ValueError) as exc:
        ctx["error"] = f"[ERROR] Failed to load materials: {exc}"
        return "error"

    slot_names = build_material_slot_names(materials)
    preview_colors = build_material_preview_colors(materials)
    base_channel_idx = infer_material_archive_base_channel_idx(
        selected_materials,
        slot_names,
        preview_colors,
    )
    color_conf = {
        "name": "Material",
        "slots": slot_names,
        "preview": preview_colors,
        "map": {name: idx for idx, name in enumerate(slot_names)},
    }
    fixed_material_layer_count = int(
        ctx.get("material_layer_count") or default_layer_count
    )
    material_layer_count = (
        int(ctx.get("material_max_layer_count") or 10)
        if bool(ctx.get("material_dynamic_layer_count_enabled", False))
        else fixed_material_layer_count
    )
    material_layer_height = float(ctx.get("material_layer_height_mm") or default_layer_height_mm)

    ctx["actual_lut_path"] = "__material_archive__"
    ctx["color_conf"] = color_conf
    ctx["slot_names"] = slot_names
    ctx["material_types"] = {
        name: material.material_type
        for name, material in zip(slot_names, materials)
    }
    ctx["preview_colors"] = preview_colors
    ctx["color_layers"] = material_layer_count
    ctx["layer_height_mm"] = material_layer_height
    ctx["material_base_channel_idx"] = base_channel_idx
    ctx["_material_params"] = materials
    ctx["material_source"] = "material_archive"

    # Normalise the opt-in exhaustive-cache grid_resolution onto the ctx.
    # 将选入式穷举缓存网格分辨率规整进 ctx：None 或未知值回落到默认；
    # 非白名单值同样回落并打印告警，避免用不能构建的分辨率跑整条流程。
    requested_grid: Any = ctx.get("material_grid_resolution")
    if requested_grid is None:
        resolved_grid = int(DEFAULT_GRID_RESOLUTION)
    else:
        try:
            requested_grid_int = int(requested_grid)
        except (TypeError, ValueError):
            requested_grid_int = None
        if requested_grid_int in ALLOWED_GRID_RESOLUTIONS:
            resolved_grid = requested_grid_int
        else:
            log.warning(
                "material_archive mode: ignoring unsupported "
                "material_grid_resolution=%r, falling back to default=%d",
                requested_grid,
                int(DEFAULT_GRID_RESOLUTION),
            )
            resolved_grid = int(DEFAULT_GRID_RESOLUTION)
    ctx["grid_resolution"] = resolved_grid

    log.debug(
        "material_archive mode: %d materials, %d layers, %.2f mm/layer, grid=%d",
        len(materials),
        material_layer_count,
        material_layer_height,
        resolved_grid,
        extra={
            "event": f"{event_prefix}_material_archive_validated",
            "count": len(materials),
            "layer_count": material_layer_count,
            "layer_height_mm": material_layer_height,
            "grid_resolution": resolved_grid,
        },
    )
    return "validated"
