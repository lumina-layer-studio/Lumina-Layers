"""Lumina Studio API — Five-Color Query Router.
Lumina Studio API — 五色组合查询路由。

Provides endpoints for querying base colors from a LUT and
performing five-color combination lookups.
提供从 LUT 获取基础颜色和执行五色组合查询的端点。
"""

import os
import threading
import uuid
from dataclasses import asdict
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, Header, HTTPException, Query

from api.dependencies import get_file_registry
from api.project_workflows import resolve_project_lut

ProjectContext = Annotated[str | None, Header(alias="X-Lumina-Project-Context")]
from api.export_device_validation import validate_export_device_selection
from api.file_registry import FileRegistry
from api.schemas.five_color import (
    BaseColorEntry,
    BaseColorsResponse,
    FiveColorMatchRequest,
    FiveColorMatchResponse,
    FiveColorQueryRequest,
    FiveColorQueryResponse,
    RecipeSwatchRequest,
    RecipeSwatchResponse,
)
from api.structured_logging import get_logger, get_request_id
from core.five_color_combination import (
    ColorCountDetector,
    ColorQueryEngine,
    StackFileManager,
    StackLUTLoader,
    rgb_to_hex,
)
from core.pipeline.preview_color_utils import build_lut_material_types
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/five-color", tags=["Five-Color"])
STATELESS_EXPORT_TTL_SECONDS = 8 * 60 * 60
log = get_logger(__name__)
_LUT_LOAD_FAILED_DETAIL = (
    "Unable to load the selected LUT. Check that the file exists and uses a "
    "supported LUT format."
)
_JSON_LUT_MISSING_RGB_DETAIL = (
    "The selected JSON LUT does not include readable RGB color data."
)
_LUT_NOT_FOUND_DETAIL = "Selected LUT was not found or is unavailable."
SWATCH_EXPORT_FAILED_DETAIL = (
    "Five-color swatch export failed. Check the selected recipes and export "
    "settings, then try again."
)
SWATCH_DOWNLOAD_REGISTRATION_FAILED_DETAIL = (
    "Five-color swatch download could not be prepared. "
    "Try generating the swatch again."
)

# ---- LUT Engine 内存缓存 ----
_engine_cache: dict[str, ColorQueryEngine] = {}
_engine_cache_lock = threading.Lock()


def _remove_generated_path(path: str | None) -> None:
    """Best-effort delete for route-owned generated swatch exports."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _rollback_swatch_registration(
    registry: FileRegistry,
    *,
    file_ids: list[str | None],
    generated_path: str | None,
) -> None:
    """Best-effort cleanup for failed swatch registration."""
    for file_id in file_ids:
        if not file_id:
            continue
        try:
            registry.cleanup_file(file_id)
        except (OSError, RuntimeError, ValueError):
            pass
    _remove_generated_path(generated_path)


def _load_npz_color_count(path: str, rgb_data) -> int | None:
    try:
        with np.load(path, allow_pickle=False) as data:
            has_metadata = "metadata_json" in data.files
    except (OSError, ValueError):
        has_metadata = False

    if has_metadata:
        _, _, metadata = LUTManager.load_lut_with_metadata(path)
        return len(metadata.palette) if metadata.palette else None

    detected_count, _ = ColorCountDetector.detect_color_count(rgb_data)
    return detected_count if detected_count > 0 else None


def clear_engine_cache():
    """Clear the LUT engine cache.
    清空 LUT 引擎缓存。
    """
    with _engine_cache_lock:
        _engine_cache.clear()
    log.info("Five-color engine cache cleared", extra={"event": "five_color_engine_cache_cleared"})


@router.post("/clear-cache")
def clear_cache():
    """Clear the LUT engine cache.
    清空 LUT 引擎缓存，强制重新加载所有 LUT。
    """
    clear_engine_cache()
    return {"success": True, "message": "Cache cleared successfully"}


def _extract_sources_from_keyed_json(json_path: str) -> list[str]:
    """Extract per-entry 'source' fields from a Keyed JSON LUT file.
    从 Keyed JSON LUT 文件中提取每条记录的 source 字段。
    """
    import json as _json
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if isinstance(data, list):
            entries: list = data
        elif isinstance(data, dict):
            entries = data.get("entries", [])
        else:
            return []
        return [e.get("source", "") if isinstance(e, dict) else "" for e in entries]
    except (OSError, TypeError, ValueError):
        return []


def _load_engine(lut_name: str, project_context: str | None = None) -> tuple[ColorQueryEngine, str]:
    """Load a LUT and create a ColorQueryEngine (with in-memory cache).
    加载 LUT 并创建 ColorQueryEngine（带内存缓存）。

    Args:
        lut_name: LUT 显示名称。

    Returns:
        (engine, lut_display_name)

    Raises:
        HTTPException 404: LUT 不存在。
        HTTPException 400: LUT 格式无法识别。
        HTTPException 500: 加载失败。
    """
    path: str | None = resolve_project_lut(lut_name, project_context)
    cache_key = path if project_context else lut_name
    with _engine_cache_lock:
        if cache_key in _engine_cache:
            return _engine_cache[cache_key], lut_name
    if path is None:
        raise HTTPException(status_code=404, detail=_LUT_NOT_FOUND_DETAIL)

    try:
        if path.endswith(".npz"):
            success, _msg, stack_data, rgb_data = StackLUTLoader.load_npz_file(path)
            if not success:
                raise HTTPException(status_code=500, detail=_LUT_LOAD_FAILED_DETAIL)
            sources = StackLUTLoader.load_sources_from_json(path)
            engine = ColorQueryEngine(
                stack_lut=stack_data,
                lut_rgb=rgb_data,
                color_count=_load_npz_color_count(path, rgb_data),
                sources=sources,
            )
        elif path.endswith(".json"):
            # Keyed JSON format — use LUTManager unified loader
            rgb_data, stack_data, metadata = LUTManager.load_lut_with_metadata(path)
            if rgb_data is None or len(rgb_data) == 0:
                raise HTTPException(status_code=500, detail=_JSON_LUT_MISSING_RGB_DETAIL)
            # Use palette names for color_count
            color_count = len(metadata.palette) if metadata.palette else None
            if color_count is None:
                inferred_color_count = metadata.extensions.get("inferred_color_count")
                if isinstance(inferred_color_count, int):
                    color_count = inferred_color_count
            # Extract per-entry sources from JSON
            sources = _extract_sources_from_keyed_json(path)
            stack_recipe_widths = metadata.extensions.get("stack_recipe_widths")
            if not isinstance(stack_recipe_widths, list):
                stack_recipe_widths = None
            engine = ColorQueryEngine(
                stack_lut=stack_data, lut_rgb=rgb_data, color_count=color_count,
                sources=sources,
                stack_recipe_widths=stack_recipe_widths,
            )
            engine._lut_metadata = metadata
            # Override base_colors from palette hex_color
            if metadata.palette:
                engine._palette_names = [e.color for e in metadata.palette]
                base_from_palette = []
                for e in metadata.palette:
                    if e.hex_color:
                        h = e.hex_color.lstrip("#")
                        if len(h) == 6:
                            base_from_palette.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
                        else:
                            base_from_palette.append((128, 128, 128))
                    else:
                        base_from_palette.append((128, 128, 128))
                engine.base_colors = base_from_palette
        else:
            # .npy file
            success, _msg, rgb_data = StackLUTLoader.load_lut_rgb(path)
            if not success:
                raise HTTPException(status_code=500, detail=_LUT_LOAD_FAILED_DETAIL)

            color_count, combination_count = ColorCountDetector.detect_color_count(rgb_data)
            if color_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unrecognized LUT format: {combination_count} combinations",
                )

            stack_path = StackFileManager.find_stack_file(color_count)
            stack_data = None
            if stack_path is not None:
                ok, _, loaded_stack = StackLUTLoader.load_stack_lut(stack_path)
                if ok:
                    stack_data = loaded_stack

            engine = ColorQueryEngine(
                stack_lut=stack_data, lut_rgb=rgb_data, color_count=color_count,
                sources=StackLUTLoader.load_sources_from_json(path)
            )

        with _engine_cache_lock:
            _engine_cache[cache_key] = engine

        return engine, lut_name

    except HTTPException:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=500, detail=_LUT_LOAD_FAILED_DETAIL
        ) from exc


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a normalized #RRGGBB string to an RGB tuple."""
    value = hex_color.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _validate_recipe_width(
    selected_indices: list[int],
    expected_length: int | tuple[int, ...],
    *,
    loc: str,
) -> None:
    actual_length = len(selected_indices)
    expected_lengths = (
        (expected_length,)
        if isinstance(expected_length, int)
        else tuple(sorted(set(int(value) for value in expected_length)))
    )
    if actual_length in expected_lengths:
        return
    expected_detail: int | list[int]
    expected_message: str
    if len(expected_lengths) == 1:
        expected_detail = expected_lengths[0]
        expected_message = str(expected_lengths[0])
    else:
        expected_detail = list(expected_lengths)
        expected_message = " or ".join(str(value) for value in expected_lengths)
    raise HTTPException(
        status_code=422,
        detail={
            "reason": "recipe_length_mismatch",
            "loc": loc,
            "expected_length": expected_detail,
            "actual_length": actual_length,
            "message": (
                f"Expected {expected_message} color indices for this LUT, "
                f"got {actual_length}."
            ),
        },
    )


@router.get("/base-colors")
def get_base_colors(lut_name: str = Query(..., description="LUT 显示名称"), project_context: ProjectContext = None) -> BaseColorsResponse:
    """Return the base colors of a LUT.
    返回指定 LUT 的基础颜色列表。
    """
    engine, display_name = _load_engine(lut_name, project_context) if project_context else _load_engine(lut_name)
    base_colors = engine.get_base_colors()
    color_names = engine.get_color_names()

    colors: list[BaseColorEntry] = [
        BaseColorEntry(
            index=i,
            rgb=rgb,
            name=color_names[i] if i < len(color_names) else "",
            hex=rgb_to_hex(rgb),
        )
        for i, rgb in enumerate(base_colors)
    ]

    combinations = engine.get_combinations()
    stack_present = engine.stack_lut is not None
    combination_count = len(combinations) if combinations is not None else 0

    if stack_present:
        log.debug(
            "Five-color base colors loaded",
            extra={
                "event": "five_color_base_colors_loaded",
                "lut_name": lut_name,
                "combination_count": combination_count,
                "color_count": len(colors),
            },
        )
    else:
        log.warning(
            "Five-color stack LUT missing",
            extra={
                "event": "five_color_stack_lut_missing",
                "lut_name": lut_name,
                "color_count": len(colors),
            },
        )
    log.info(
        "Five-color base colors returned",
        extra={
            "event": "five_color_base_colors_done",
            "lut_name": lut_name,
            "color_count": len(colors),
            "combination_count": combination_count,
            "stack_present": stack_present,
        },
    )

    return BaseColorsResponse(
        lut_name=display_name,
        color_count=len(colors),
        colors=colors,
        combinations=combinations,
    )


@router.post("/query")
def query_five_color(request: FiveColorQueryRequest, project_context: ProjectContext = None) -> FiveColorQueryResponse:
    """Query a five-color combination result.
    查询五色组合结果。
    """
    engine, _ = _load_engine(request.lut_name, project_context) if project_context else _load_engine(request.lut_name)
    _validate_recipe_width(
        request.selected_indices,
        engine.accepted_selection_lengths(),
        loc="body.selected_indices",
    )

    # Validate index range
    for idx in request.selected_indices:
        if idx < 0 or idx >= engine.color_count:
            raise HTTPException(
                status_code=400,
                detail=f"Index {idx} out of range [0, {engine.color_count})",
            )

    result = engine.query(request.selected_indices)
    result_hex = rgb_to_hex(result.result_rgb) if result.result_rgb else None

    log.info(
        "Five-color query returned",
        extra={
            "event": "five_color_query_done",
            "lut_name": request.lut_name,
            "selected_indices_count": len(request.selected_indices),
            "found": result.found,
            "result_hex": result_hex,
            "source": result.source,
        },
    )

    return FiveColorQueryResponse(
        found=result.found,
        selected_indices=result.selected_indices,
        result_rgb=result.result_rgb,
        result_hex=result_hex,
        row_index=result.row_index,
        message=result.message,
        source=result.source,
    )


@router.post("/match-color")
def match_color_by_hex(request: FiveColorMatchRequest, project_context: ProjectContext = None) -> FiveColorMatchResponse:
    """Match a target Hex color to the nearest LUT row and five-layer recipe.
    按目标 Hex 色值匹配最近 LUT 行，并返回五层配方与色卡位置。
    """
    engine, _ = _load_engine(request.lut_name, project_context) if project_context else _load_engine(request.lut_name)
    result = engine.match_color(
        _hex_to_rgb(request.target_hex),
        neighborhood_radius=request.neighborhood_radius,
    )

    return FiveColorMatchResponse(
        found=result.found,
        selected_indices=result.selected_indices,
        result_rgb=result.result_rgb,
        result_hex=rgb_to_hex(result.result_rgb) if result.result_rgb else None,
        row_index=result.row_index,
        message=result.message,
        source=result.source,
        reason=result.reason,
        target_rgb=result.target_rgb,
        target_hex=rgb_to_hex(result.target_rgb),
        matched_rgb=result.matched_rgb,
        matched_hex=rgb_to_hex(result.matched_rgb) if result.matched_rgb else None,
        delta_e=round(result.delta_e, 6) if result.delta_e is not None else None,
        coordinate=asdict(result.coordinate),
        neighborhood=[[asdict(cell) for cell in row] for row in result.neighborhood],
    )


@router.post("/generate-swatch")
def generate_swatch(
    request: RecipeSwatchRequest,
    registry: FileRegistry = Depends(get_file_registry),
    project_context: ProjectContext = None,
) -> RecipeSwatchResponse:
    """Generate a 3MF swatch file from collected recipes.
    根据收集的配方列表生成 3MF 色块验证文件。
    """
    validate_export_device_selection(
        printer_id=request.printer_id,
        slicer=request.slicer,
        nozzle_size=request.nozzle_size,
        device_profile_id=request.device_profile_id,
        build_plate_id=request.build_plate_id,
        custom_3mf_template_id=request.custom_3mf_template_id,
    )
    from api.file_bridge import pil_to_png_bytes
    from core.recipe_swatch import RecipeSwatchItem, generate_recipe_swatch

    engine, _ = _load_engine(request.lut_name, project_context) if project_context else _load_engine(request.lut_name)
    base_color_names = engine.get_color_names()
    base_color_hexes = [rgb_to_hex(rgb) for rgb in engine.get_base_colors()]
    metadata = getattr(engine, "_lut_metadata", None)
    if metadata is None:
        _, _, metadata = LUTManager.load_lut_with_metadata(
            resolve_project_lut(request.lut_name, project_context)
        )
    palette_names = (
        [entry.color for entry in metadata.palette]
        if metadata.palette else base_color_names
    )
    types_by_name = build_lut_material_types(metadata, palette_names)
    material_types = [
        types_by_name.get(palette_names[index]) if index < len(palette_names) else None
        for index in range(len(base_color_names))
    ]

    items: list[RecipeSwatchItem] = []
    expected_length = engine.accepted_selection_lengths()
    for recipe_index, recipe_request in enumerate(request.recipes):
        _validate_recipe_width(
            recipe_request.selected_indices,
            expected_length,
            loc=f"body.recipes.{recipe_index}.selected_indices",
        )
        for idx in recipe_request.selected_indices:
            if idx < 0 or idx >= engine.color_count:
                raise HTTPException(
                    status_code=400,
                    detail=f"Index {idx} out of range [0, {engine.color_count})",
                )
        query_result = engine.query(recipe_request.selected_indices)
        if not query_result.found or query_result.result_rgb is None:
            raise HTTPException(
                status_code=400,
                detail=f"No LUT match for selected indices: {recipe_request.selected_indices}",
            )
        items.append(
            RecipeSwatchItem(
                selected_indices=recipe_request.selected_indices,
                result_hex=rgb_to_hex(query_result.result_rgb),
                base_color_names=base_color_names,
                base_color_hexes=base_color_hexes,
                material_types=material_types,
            )
        )

    output_path, legend_img, status_msg = generate_recipe_swatch(
        recipes=items,
        block_size_mm=request.block_size_mm,
        gap_mm=request.gap_mm,
        cols=request.cols,
        structure_mode=request.structure_mode,
        printer_id=request.printer_id,
        slicer=request.slicer,
        nozzle_size=request.nozzle_size,
        device_profile_id=request.device_profile_id,
        build_plate_id=request.build_plate_id,
    )

    if not output_path:
        log.warning(
            "Five-color swatch export failed",
            extra={
                "event": "five_color_generate_swatch_failed",
                "lut_name": request.lut_name,
                "recipe_count": len(items),
                "status_code": 500,
                "error_type": "SwatchGenerationFailed",
                "error_message": status_msg or "Swatch generation failed",
            },
        )
        raise HTTPException(status_code=500, detail=SWATCH_EXPORT_FAILED_DETAIL)

    request_id = get_request_id()
    unique_suffix = uuid.uuid4().hex
    sid = (
        f"recipe-swatch:{request_id}:{unique_suffix}"
        if request_id
        else f"recipe-swatch:{unique_suffix}"
    )
    preview_url: str | None = None
    preview_id: str | None = None
    try:
        download_id = registry.register_path(
            sid,
            output_path,
            ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        _rollback_swatch_registration(
            registry,
            file_ids=[],
            generated_path=output_path,
        )
        log.error(
            "Five-color swatch registration failed",
            extra={
                "event": "five_color_generate_swatch_registration_failed",
                "status_code": 500,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "lut_name": request.lut_name,
                "recipe_count": len(items),
                "registration_stage": "download",
            },
        )
        raise HTTPException(
            status_code=500,
            detail=SWATCH_DOWNLOAD_REGISTRATION_FAILED_DETAIL,
        ) from exc

    if legend_img is not None:
        try:
            preview_bytes = pil_to_png_bytes(legend_img)
            preview_id = registry.register_bytes(
                sid,
                preview_bytes,
                "swatch_legend.png",
                ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
            )
            preview_url = f"/api/files/{preview_id}"
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            log.warning(
                "Five-color swatch preview registration failed",
                extra={
                    "event": "five_color_generate_swatch_registration_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "lut_name": request.lut_name,
                    "recipe_count": len(items),
                    "registration_stage": "preview",
                    "download_id": download_id,
                },
            )
    preview_id_for_log = preview_id if legend_img is not None else None

    log.info(
        "Five-color swatch generated",
        extra={
            "event": "five_color_generate_swatch_done",
            "lut_name": request.lut_name,
            "recipe_count": len(items),
            "download_id": download_id,
            "preview_id": preview_id_for_log,
            "block_size_mm": request.block_size_mm,
            "gap_mm": request.gap_mm,
            "cols": request.cols,
        },
    )

    return RecipeSwatchResponse(
        status="ok",
        message=status_msg,
        download_url=f"/api/files/{download_id}",
        preview_url=preview_url,
        recipe_count=len(items),
    )
