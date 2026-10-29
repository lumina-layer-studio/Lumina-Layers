"""Converter router replace module."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
import os
import sys
import time
from typing import Any, NoReturn

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from api.editor_project import (
    EDITOR_PROJECT_MAX_BYTES, build_editor_project, decode_editor_project,
)
from api.dependencies import get_file_registry, get_session_store
from api.dynamic_material_response import dynamic_material_result_from_cache
from api.editor_commit import (
    advance_editor_content_revision,
    begin_editor_commit,
    EditorCommitReplayError,
    fail_editor_commit,
    get_editor_commit_receipt,
    get_editor_content_revision,
    publish_editor_commit,
)
from api.file_registry import FileRegistry
from api.schemas.converter import (
    ColorHighlightRequest,
    ColorHighlightResponse,
    ColorMergePreviewRequest,
    ColorReplaceBatchRequest,
    ColorReplaceRequest,
    FreeColorMutationRequest,
    FreeColorMutationResponse,
    RecipeOverrideApplyRequest,
    RecipePredictRequest,
    RegionDetectRequest,
    RegionDetectResponse,
    RegionRecipeRequest,
    RegionReplaceBatchItem,
    RegionReplaceBatchRequest,
    RegionReplaceRequest,
    RegionReplaceResponse,
    RegionRequantizeRequest,
    ReplacementHistoryRequest,
    ReplacementHistoryResponse,
    ResetReplacementsRequest,
    SelectionDocumentResponse,
    SelectionMutationRequest,
    EditorCommitStatusResponse,
    SourceColorPickRequest,
    SourceColorPickResponse,
    VirtualMaterial,
)
from api.schemas.responses import (
    ColorReplaceResponse,
    MergePreviewResponse,
    RecipeOverrideApplyResponse,
    RecipePredictResponse,
    RegionRecipeEntry,
    RegionRecipeResponse,
    ResetReplacementsResponse,
)
from api.session_store import SessionStore
from api.visible_region_cache import (
    VISIBLE_REGION_CACHE_KEY,
    build_visible_region_component_cache,
    component_mask,
    detect_single_component_at_point,
    ensure_component_contours,
    get_component_at,
    get_valid_visible_region_cache,
    get_visible_region_cache_build_lock,
    get_visible_region_generation,
    invalidate_visible_region_cache,
    schedule_visible_region_cache_prewarm,
    store_visible_region_component_cache,
)
from config import LUTMetadata, OUTPUT_DIR, PaletteEntry
from core.color_merger import ColorMerger
from core.color_replacement import ColorReplacementManager
from core.gradient_group_analyzer import REGION_ID_ENCODING_MULTIPLIER
from core.gradient_region_requantize import requantize_gradient_regions
from core.converter import (
    extract_color_palette,
    generate_segmented_glb,
)
from core.naming import generate_segmented_glb_filename
from core.material_cache import DEFAULT_GRID_RESOLUTION, load_material_solver_cache_with_fallback
from core.material_lut_synthesis import (
    infer_material_archive_base_channel_idx,
    load_multiple_materials,
    solve_image_colors_optimal,
)
from core.material_color_solver import predict_material_recipe_srgb
from core.material_dynamic_replacement import (
    rebuild_dynamic_material_after_replacement,
)
from core.pipeline.material_dynamic_layers import (
    recompute_dynamic_material_benefit_curve,
    solve_dynamic_material_targets,
)
from core.predictive_lut import predict_recipe_color
from core.recipe_order import (
    convert_recipe_between_orders,
    normalize_layer_order,
    pad_recipe_to_layer_count,
)
from utils.lut_manager import LUTManager
from api.preview_cache_artifacts import (
    PreviewCacheRevisionConflict,
    get_preview_cache_metadata,
    hydrate_preview_cache,
    is_preview_cache_artifact_ref,
    persist_preview_cache,
    preview_cache_transaction,
)
from api.replacement_history import (
    REPLACEMENT_CACHE_METADATA_FIELDS as _REPLACEMENT_CACHE_METADATA_FIELDS,
    can_redo as replacement_can_redo,
    can_undo as replacement_can_undo,
    push_replacement_checkpoint,
    replacement_history_lock,
    restore_from_history,
    restore_replacement_checkpoint,
    snapshot_replacement_state,
    snapshot_selection_state,
)
from api.selection_state import (
    get_selection_mask,
    get_selection_revision,
    mutate_brush_add,
    mutate_color_range_toggle,
    mutate_point_toggle,
    mutate_same_color_toggle,
    pack_applied_region_mask,
    persist_selection_mask,
    resolve_selection_mask,
    resolve_recipe_override_masks,
    selection_lock,
    selection_summary,
    sync_selection_content_generation,
)
from api.structured_logging import get_logger

from .common import (
    GRADIENT_REGION_METADATA_STALE_DETAIL,
    GRADIENT_REGION_METADATA_UNAVAILABLE_DETAIL,
    MATCHED_COLORS_UNAVAILABLE_DETAIL,
    MATERIAL_SOLVER_CACHE_UNAVAILABLE_DETAIL,
    NON_FATAL_GLB_ERRORS,
    PREVIEW_CACHE_INVALID_DETAIL,
    PREVIEW_CACHE_UNAVAILABLE_DETAIL,
    RECIPE_OVERRIDE_APPLIED_MASKS_KEY,
    REGION_SELECTION_REQUIRED_DETAIL,
    ROUTER_HANDLED_ERRORS,
    _ensure_material_matrix_signed_capacity,
    _handle_core_error,
    _image_to_png_bytes,
    _require_preview_cache,
    _require_session,
    _resolve_material_backing_index,
    load_session_lut_runtime,
    lut_row_indices_for_colors,
    recompute_gradient_groups_into_session,
)
from .async_glb import schedule_glb_build

router = APIRouter()
log = get_logger(__name__)
# Compatibility seam for focused tests of the synchronous core adapter. Product
# routes call the public solver through ``core.material_dynamic_replacement``.
_solve_dynamic_material_targets = solve_dynamic_material_targets
_DEFAULT_GENERATE_SEGMENTED_GLB = generate_segmented_glb
_SELECT_ALL_COLOR_REGION_PREFIX = "__select_all_color__:"
_PREVIEW_CACHE_TRANSACTION_ENTER_ERRORS = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    EOFError,
)
_PREVIEW_CACHE_TRANSACTION_UNAVAILABLE_DETAIL = (
    "Preview cache is unavailable. "
    "Re-run preview before changing replacement colors."
)
CONVERTER_REPLACE_CACHE_CONFLICT_DETAIL = (
    "Preview cache changed while replacement tools were running. "
    "Re-run preview and try again."
)
REGION_REQUANTIZE_MATERIALS_UNAVAILABLE_DETAIL = (
    "Region re-quantisation cannot load the selected material archives. "
    "Re-select the materials and run preview again."
)
REGION_REQUANTIZE_SOURCE_IMAGE_UNAVAILABLE_DETAIL = (
    "Region re-quantisation cannot read the original source image. "
    "Re-upload the image and run preview again."
)
REGION_REQUANTIZE_REQUEST_INVALID_DETAIL = (
    "Region re-quantisation could not process the selected region. "
    "Refresh preview and try again."
)
REGION_REQUANTIZE_CACHE_CONFLICT_DETAIL = (
    "Preview cache changed while region re-quantisation was running. "
    "Refresh preview and try again."
)
RECIPE_OVERRIDE_APPLY_FAILED_DETAIL = (
    "Recipe override could not be applied. Check the server log for details."
)
def _require_preview_cache_fields(
    session_data: dict,
    *,
    fields: set[str],
) -> dict:
    """Load only selected preview-cache fields for replace routes.

    只为替换相关路由加载指定 preview-cache 字段。
    """
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(
            status_code=409,
            detail=PREVIEW_CACHE_UNAVAILABLE_DETAIL,
        )
    if not isinstance(cache, dict):
        raise HTTPException(
            status_code=409,
            detail=PREVIEW_CACHE_INVALID_DETAIL,
        )
    if not is_preview_cache_artifact_ref(cache):
        return cache
    loaded = get_preview_cache_metadata(cache)
    try:
        loaded.update(
            hydrate_preview_cache(
                cache,
                fields=fields,
                mmap_mode="r",
            )
        )
    except (OSError, ValueError, TypeError, KeyError, EOFError) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Preview cache is unavailable. "
                "Re-run preview before using replacement tools."
            ),
        ) from exc
    return loaded


def _dirty_array_fields(cache: dict, *field_names: str) -> set[str]:
    return {
        field_name
        for field_name in field_names
        if isinstance(cache.get(field_name), np.ndarray)
    }


def _raise_region_requantize_error(
    exc: Exception,
    *,
    status_code: int,
    detail: str,
    session_id: str,
    stage: str,
) -> None:
    log_method = log.error if status_code >= 500 else log.warning
    log_method(
        "Region re-quantisation failed",
        extra={
            "event": "converter_region_requantize_failed",
            "session_id": session_id,
            "stage": stage,
            "status_code": status_code,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
    )
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _raise_replace_cache_conflict(
    exc: PreviewCacheRevisionConflict,
    *,
    session_id: str,
    operation: str,
) -> NoReturn:
    log.warning(
        "Preview cache conflict during replacement tool",
        extra={
            "event": "converter_replace_cache_conflict",
            "session_id": session_id,
            "operation": operation,
            "status_code": 409,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
    )
    raise HTTPException(
        status_code=409,
        detail=CONVERTER_REPLACE_CACHE_CONFLICT_DETAIL,
    ) from exc


def _mark_editor_commit_failed_if_unpublished(
    *,
    session_id: str,
    store: SessionStore,
    session_data: dict | None,
    operation_id: str | None,
    cache_published: bool,
    error_type: str,
) -> None:
    """Record a known pre-publication failure without masking its error.

    仅在缓存尚未发布时确认“未提交”；一旦缓存已经发布，后续异常仍保持
    pending/unknown，避免把部分提交误报成失败。
    """
    if (
        session_data is None
        or not operation_id
        or cache_published
        or error_type == EditorCommitReplayError.__name__
    ):
        return
    try:
        fail_editor_commit(
            session_id,
            store,
            session_data,
            operation_id=operation_id,
            error_type=error_type,
        )
    except Exception as exc:  # pragma: no cover - defensive error boundary
        log.warning(
            "Could not persist failed editor receipt",
            extra={
                "event": "converter_editor_commit_receipt_failed",
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "operation_id": operation_id,
            },
        )


@contextmanager
def _replacement_selection_lock(session_id: str):
    """Acquire replacement history and selection locks in one order.

    内容提交与选区变更都可能同时更新历史快照。统一采用
    ``replacement_history -> selection`` 的顺序，避免选区路由在持有选区锁时
    等待历史锁，而内容路由持有历史锁时反向等待选区锁。
    """
    with replacement_history_lock(session_id):
        with selection_lock(session_id):
            yield


@contextmanager
def _preview_cache_transaction(
    session_id: str,
    store: SessionStore,
    session_data: dict,
    *,
    fields: set[str],
):
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(
            status_code=409,
            detail=PREVIEW_CACHE_UNAVAILABLE_DETAIL,
        )
    if not isinstance(cache, dict):
        raise HTTPException(
            status_code=409,
            detail=PREVIEW_CACHE_INVALID_DETAIL,
        )
    # The field-level preview-cache CAS protects individual arrays, but the
    # surrounding session fields (replacement records, history, selection
    # summary, and the unified editor receipt) must publish in the same
    # per-session order. Reuse the existing history lock rather than adding a
    # second editor-state lock. The lock is session-scoped and is released
    # before the route returns to any derived GLB scheduling code.
    transaction_lock = replacement_history_lock(session_id)
    transaction_lock.acquire()
    inner = preview_cache_transaction(session_id, store, session_data, fields=fields)
    try:
        try:
            cache_view = inner.__enter__()
        except _PREVIEW_CACHE_TRANSACTION_ENTER_ERRORS as exc:
            raise HTTPException(
                status_code=409,
                detail=_PREVIEW_CACHE_TRANSACTION_UNAVAILABLE_DETAIL,
            ) from exc

        rollback_fields = set(fields) | {
            "color_palette",
            "color_layers",
            "layer_height_mm",
            "material_dynamic_layer_info",
            "material_solver_info",
        }
        missing_value = object()
        rollback_snapshot: dict[str, object] = {}
        for field_name in rollback_fields:
            if field_name not in cache_view:
                rollback_snapshot[field_name] = missing_value
                continue
            value = cache_view[field_name]
            rollback_snapshot[field_name] = (
                value.copy() if isinstance(value, np.ndarray) else deepcopy(value)
            )

        try:
            yield cache_view
        except BaseException:
            # Once the cache transaction has published, its working view is
            # the committed in-memory cache (or the source of the committed
            # artifact fields). Restoring the pre-commit snapshot here would
            # create a mixed state: new session/history metadata with old
            # RGB/material arrays. Only pre-publication failures may roll the
            # private working copy back.
            if not getattr(cache_view, "published", False):
                for field_name, value in rollback_snapshot.items():
                    if value is missing_value:
                        cache_view.pop(field_name, None)
                    else:
                        cache_view[field_name] = value
            if not inner.__exit__(*sys.exc_info()):
                raise
        else:
            inner.__exit__(None, None, None)
    finally:
        transaction_lock.release()


@contextmanager
def _preview_cache_transaction_with_history(
    session_id: str,
    store: SessionStore,
    session_data: dict,
    *,
    fields: set[str],
    history_label: str,
    operation_id: str | None = None,
):
    """Capture the undo checkpoint under the same lock as cache publication.

    在与缓存发布相同的会话锁内捕获撤销快照，确保并发编辑不会把错误的
    ``previous state`` 记录到当前操作的历史中。
    """
    with replacement_history_lock(session_id):
        try:
            history_checkpoint = snapshot_replacement_state(
                session_data,
                label=history_label,
            )
        except BaseException as exc:
            if operation_id:
                _mark_editor_commit_failed_if_unpublished(
                    session_id=session_id,
                    store=store,
                    session_data=session_data,
                    operation_id=operation_id,
                    cache_published=False,
                    error_type=type(exc).__name__,
                )
            raise

        transaction = _preview_cache_transaction(
            session_id,
            store,
            session_data,
            fields=fields,
        )
        try:
            cache = transaction.__enter__()
        except BaseException as exc:
            if operation_id:
                _mark_editor_commit_failed_if_unpublished(
                    session_id=session_id,
                    store=store,
                    session_data=session_data,
                    operation_id=operation_id,
                    cache_published=False,
                    error_type=type(exc).__name__,
                )
            raise

        try:
            yield cache, history_checkpoint
        except BaseException:
            if not transaction.__exit__(*sys.exc_info()):
                raise
        else:
            transaction.__exit__(None, None, None)


def _recalc_matched_rgb_for_padded_pixels(
    *,
    updated_rgb,
    material_matrix,
    non_override_mask,
    session_data: dict,
    layer_height_mm: float,
    substrate: str,
) -> None:
    import numpy as np
    selected_materials = session_data.get('selected_materials') or []
    try:
        materials = load_multiple_materials(selected_materials)
    except Exception:
        return
    recipes = material_matrix[non_override_mask, :]
    if recipes.size == 0:
        return
    recipes_i32 = recipes.astype(np.int32)
    unique_rows, inverse = np.unique(recipes_i32, axis=0, return_inverse=True)
    flat_y, flat_x = np.where(non_override_mask)
    cached = {}
    for u_idx in range(unique_rows.shape[0]):
        idxs = np.where(inverse == u_idx)[0]
        if len(idxs) == 0:
            continue
        recipe_row = unique_rows[u_idx]
        if np.any(recipe_row < 0):
            continue
        try:
            # material_matrix Top2Bottom（[0]=顶层），统一预测器接收 Bottom2Top。
            pred_u8 = predict_material_recipe_srgb(
                recipe_row[::-1],
                materials,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
            )
        except Exception:
            continue
        cached[u_idx] = pred_u8
    for i in range(len(flat_y)):
        u = inverse[i]
        if u in cached:
            updated_rgb[flat_y[i], flat_x[i]] = cached[u]


def _render_styled_preview_bytes(replaced_rgb: np.ndarray, cache: dict) -> bytes:
    """Render a raw RGBA preview from replaced_rgb with transparency.
    从替换后的 matched_rgb 生成带透明通道的原始 RGBA 预览。

    Returns raw RGBA so that pixel coordinates match previewPixelWidth ×
    previewPixelHeight exactly, keeping SVG contour overlays and
    click-to-pixel mapping correctly aligned in ColorPreview2D.

    Args:
        replaced_rgb: Updated matched_rgb array (H, W, 3) after color replacement.
        cache: Preview cache dict containing mask_solid, etc.

    Returns:
        PNG bytes of the raw RGBA preview image.
    """
    mask_solid: np.ndarray | None = cache.get("mask_solid")
    h, w = replaced_rgb.shape[:2]

    # Reconstruct RGBA from replaced_rgb + mask_solid
    preview_rgba = np.zeros((h, w, 4), dtype=np.uint8)
    if mask_solid is not None:
        preview_rgba[mask_solid, :3] = replaced_rgb[mask_solid]
        preview_rgba[mask_solid, 3] = 255
    else:
        preview_rgba[..., :3] = replaced_rgb
        preview_rgba[..., 3] = 255

    # Update cache's preview_rgba for consistency
    cache["preview_rgba"] = preview_rgba.copy()

    return _image_to_png_bytes(preview_rgba)


def _render_masked_preview_bytes(rgb: np.ndarray, mask_solid: np.ndarray) -> bytes:
    """Render RGB pixels with alpha derived from ``mask_solid``.

    Args:
        rgb: Preview RGB image, shape ``(H, W, 3)``.
        mask_solid: Solid-pixel mask, shape ``(H, W)``.

    Returns:
        PNG bytes with transparent background outside ``mask_solid``.
    """
    rgb_arr = np.asarray(rgb, dtype=np.uint8)
    mask_arr = np.asarray(mask_solid, dtype=bool)
    h, w = rgb_arr.shape[:2]
    if mask_arr.shape != (h, w):
        raise ValueError("mask_solid shape must match RGB preview dimensions.")

    preview_rgba = np.zeros((h, w, 4), dtype=np.uint8)
    preview_rgba[mask_arr, :3] = rgb_arr[mask_arr]
    preview_rgba[mask_arr, 3] = 255
    return _image_to_png_bytes(preview_rgba)


def _schedule_or_run_overridden_glb_build(
    session_id: str,
    store: SessionStore,
    registry: FileRegistry,
    cache: dict,
    filename: str,
) -> str | None:
    """Schedule the normal GLB build, or run an overridden builder inline."""
    if generate_segmented_glb is _DEFAULT_GENERATE_SEGMENTED_GLB:
        persisted_cache = persist_preview_cache(session_id, store, cache)
        _schedule_glb_build_best_effort(
            session_id,
            store,
            registry,
            persisted_cache,
        )
        return None

    target_path = os.path.join(
        OUTPUT_DIR,
        generate_segmented_glb_filename(session_id),
    )
    try:
        glb_path = generate_segmented_glb(cache, output_path=target_path)
    except NON_FATAL_GLB_ERRORS as exc:
        log.warning(
            "Overridden GLB build failed",
            extra={
                "event": "converter_region_replace_overridden_glb_failed",
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None

    if not glb_path:
        return None

    persist_preview_cache(session_id, store, cache)
    glb_id = registry.register_path(session_id, glb_path, filename)
    return f"/api/files/{glb_id}"


def _schedule_glb_build_best_effort(
    session_id: str,
    store: SessionStore,
    registry: FileRegistry,
    persisted_cache: dict,
) -> str | None:
    """Keep a committed 2D edit successful when GLB scheduling fails.

    The preview cache and replacement history are committed before this
    boundary. A GLB is a derived artifact, so an unexpected scheduler error
    must be logged and surfaced through GLB polling without restoring the
    previous RGB/material state or asking the frontend to roll it back.
    已提交的二维内容先于此边界完成；GLB 属于派生工件，因此调度异常只能
    记录并交给 GLB 状态查询，不能恢复旧的 RGB/材料矩阵或让前端回滚。
    """
    try:
        return schedule_glb_build(session_id, store, registry, persisted_cache)
    except Exception as exc:  # Explicit derived-artifact boundary guard.
        log.warning(
            "GLB build scheduling failed after content commit",
            extra={
                "event": "converter_glb_schedule_failed",
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "artifact_kind": "derived_glb",
                "content_commit": "committed",
            },
        )
        return None


def _select_all_color_mask_for_region_id(
    session_data: dict,
    region_id: str,
) -> np.ndarray | None:
    if not isinstance(region_id, str):
        return None
    if not region_id.startswith(_SELECT_ALL_COLOR_REGION_PREFIX):
        return None

    color_hex = region_id[len(_SELECT_ALL_COLOR_REGION_PREFIX):].strip().lstrip("#")
    if len(color_hex) != 6:
        return None
    try:
        target_rgb = np.asarray(
            [
                int(color_hex[0:2], 16),
                int(color_hex[2:4], 16),
                int(color_hex[4:6], 16),
            ],
            dtype=np.uint8,
        )
    except ValueError:
        return None

    cache = session_data.get("preview_cache")
    if not isinstance(cache, dict):
        return None
    if is_preview_cache_artifact_ref(cache):
        cache = hydrate_preview_cache(
            cache,
            fields={"matched_rgb", "mask_solid"},
        )
    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    if matched_rgb is None or mask_solid is None:
        return None

    matched_arr = np.asarray(matched_rgb)
    if matched_arr.ndim != 3 or matched_arr.shape[2] < 3:
        return None
    mask_solid_arr = np.asarray(mask_solid, dtype=bool)
    if mask_solid_arr.shape != matched_arr.shape[:2]:
        return None

    color_mask = np.all(matched_arr[..., :3] == target_rgb, axis=-1) & mask_solid_arr
    if not np.any(color_mask):
        return None
    return color_mask


def _get_region_mask_items_for_ids(
    session_data: dict,
    region_ids: list[str],
) -> list[tuple[str, np.ndarray]]:
    region_masks = session_data.get("selected_region_masks") or {}
    if not isinstance(region_masks, dict):
        region_masks = {}
    session_data["selected_region_masks"] = region_masks

    masks: list[tuple[str, np.ndarray]] = []
    seen_region_ids: set[str] = set()
    for region_id in region_ids:
        mask = region_masks.get(region_id)
        if not isinstance(mask, np.ndarray):
            generated_mask = _get_cached_visible_region_mask(session_data, region_id)
            if generated_mask is None:
                generated_mask = _select_all_color_mask_for_region_id(session_data, region_id)
            if generated_mask is not None:
                region_masks[region_id] = generated_mask
                mask = generated_mask
        if isinstance(region_id, str) and isinstance(mask, np.ndarray) and region_id not in seen_region_ids:
            masks.append((region_id, mask))
            seen_region_ids.add(region_id)

    if not masks:
        fallback_mask = session_data.get("selected_region_mask")
        fallback_id = session_data.get("selected_region_id")
        if not isinstance(fallback_mask, np.ndarray):
            fallback_mask = _get_cached_visible_region_mask(session_data, fallback_id)
            if isinstance(fallback_id, str) and isinstance(fallback_mask, np.ndarray):
                region_masks[fallback_id] = fallback_mask
        if isinstance(fallback_id, str) and isinstance(fallback_mask, np.ndarray) and (
            not region_ids or fallback_id in region_ids
        ):
            masks.append((fallback_id, fallback_mask))
    return masks


def _get_visible_region_source_rgb(cache: dict) -> np.ndarray:
    """Return the RGB image used for click-visible connected regions.
    返回用于“点击当前可见色块”的连通域 RGB 图。

    Region selection must follow the colour the user currently sees in the
    preview. Using the upstream ``quantized_image`` can split one visible
    matched-colour block into several tiny source-quantized islands.
    区域选择必须按用户当前看到的预览色计算；如果继续用上游
    ``quantized_image``，同一个可见匹配色块可能被拆成多个很小的原始量化块。
    """
    matched_rgb = cache.get("matched_rgb")
    if matched_rgb is None:
        raise HTTPException(
            status_code=409,
            detail="Preview cache missing matched_rgb.",
        )
    matched_arr = np.asarray(matched_rgb)
    if matched_arr.ndim != 3 or matched_arr.shape[2] < 3:
        raise HTTPException(
            status_code=409,
            detail="Preview cache matched_rgb has invalid shape.",
        )
    visible_rgb = matched_arr[:, :, :3]
    if visible_rgb.dtype != np.uint8:
        return np.asarray(visible_rgb, dtype=np.uint8)
    return visible_rgb


def _ensure_visible_region_component_cache(
    session_id: str,
    store: SessionStore,
    session_data: dict,
    preview_cache: dict,
) -> tuple[dict, bool]:
    cached = get_valid_visible_region_cache(session_data)
    if cached is not None:
        return cached, True
    with get_visible_region_cache_build_lock(session_id):
        latest_session = store.get(session_id) or session_data
        cached = get_valid_visible_region_cache(latest_session)
        if cached is not None:
            session_data[VISIBLE_REGION_CACHE_KEY] = cached
            return cached, True
        component_cache = build_visible_region_component_cache(
            preview_cache,
            generation=get_visible_region_generation(latest_session),
        )
        store_visible_region_component_cache(session_id, store, component_cache)
        session_data[VISIBLE_REGION_CACHE_KEY] = component_cache
        latest_session[VISIBLE_REGION_CACHE_KEY] = component_cache
        return component_cache, False


def _invalidate_and_prewarm_visible_region_cache(
    session_id: str,
    store: SessionStore,
    session_data: dict,
    preview_cache: dict | None,
) -> None:
    invalidate_visible_region_cache(session_id, store, session_data)
    generation = get_visible_region_generation(session_data)
    if preview_cache is not None:
        schedule_visible_region_cache_prewarm(
            session_id,
            store,
            preview_cache,
            generation=generation,
        )


def _history_flags(session_data: dict | None) -> dict[str, bool]:
    return {
        "can_undo": replacement_can_undo(session_data),
        "can_redo": replacement_can_redo(session_data),
    }


def _push_history_checkpoint(
    session_id: str,
    store: SessionStore,
    session_data: dict,
    checkpoint: dict | None,
) -> dict[str, bool]:
    push_replacement_checkpoint(session_id, store, session_data, checkpoint)
    return _history_flags(session_data)


def _current_replacement_regions(session_data: dict) -> list[dict]:
    regions = session_data.get("replacement_regions") or []
    if not isinstance(regions, list):
        return []
    return [dict(item) for item in regions if isinstance(item, dict)]


def _current_recipe_overrides(session_data: dict) -> list[dict]:
    overrides = session_data.get("recipe_overrides") or []
    if not isinstance(overrides, list):
        return []
    return [dict(item) for item in overrides if isinstance(item, dict)]


_UNSET_EDITOR_COMMIT_RESULT_VALUE = object()


def _editor_commit_result(
    session_data: dict,
    *,
    cache: Mapping[str, Any] | None = None,
    preview_url: str | None = None,
    preview_glb_url: str | None | object = _UNSET_EDITOR_COMMIT_RESULT_VALUE,
) -> dict:
    """Build the bounded business projection stored in an editor receipt.

    构建写入编辑回执的有限业务状态投影。

    The projection is assembled from the already-published session/cache
    state. It contains the same small fields the editor responses expose, but
    never copies image arrays, selection masks, or history checkpoints.
    投影直接读取已发布的 session/cache 状态，只保存编辑响应所需的小字段，
    不复制图像数组、选区 mask 或历史 checkpoint。
    """
    replacement_regions: list[dict] = []
    for item in _current_replacement_regions(session_data):
        matched_hex = (
            item.get("matched_hex")
            or item.get("selected_color")
            or item.get("quantized_hex")
        )
        replacement_hex = item.get("replacement_hex") or item.get(
            "replacement_color"
        )
        if not isinstance(matched_hex, str) or not isinstance(replacement_hex, str):
            continue
        quantized_hex = item.get("quantized_hex") or matched_hex
        replacement_regions.append(
            {
                "quantized_hex": str(quantized_hex),
                "matched_hex": matched_hex,
                "replacement_hex": replacement_hex,
            }
        )
    result: dict = {
        "replacement_regions": replacement_regions,
        "recipe_overrides": _current_recipe_overrides(session_data),
        "recipe_override_count": int(session_data.get("recipe_override_count") or 0),
        "region_replacement_count": int(
            session_data.get("region_replacement_count") or 0
        ),
        "free_color_set": sorted(
            str(value).replace("#", "").lower()
            for value in (session_data.get("free_color_set") or set())
        ),
        "can_undo": replacement_can_undo(session_data),
        "can_redo": replacement_can_redo(session_data),
    }
    if preview_url is not None:
        result["preview_url"] = preview_url
    if preview_glb_url is not _UNSET_EDITOR_COMMIT_RESULT_VALUE:
        result["preview_glb_url"] = preview_glb_url

    if isinstance(cache, Mapping):
        result.update(
            dynamic_material_result_from_cache(cache).model_dump(exclude_none=True)
        )
    # The cache may expose the material matrix's actual/derived depth after a
    # recipe edit. Base input fields must remain the session values so a lost
    # recipe response cannot turn a derived depth into a new auto-preview input.
    if session_data.get("color_layers") is not None:
        result["color_layers"] = int(session_data["color_layers"])
    if session_data.get("layer_height_mm") is not None:
        result["layer_height_mm"] = float(session_data["layer_height_mm"])
    if "gradient_groups" in session_data:
        result["gradient_groups"] = session_data.get("gradient_groups")
    return result


def _bump_region_replacement_count(
    session_id: str,
    store: SessionStore,
    session_data: dict,
    amount: int = 1,
) -> int:
    try:
        current = int(session_data.get("region_replacement_count") or 0)
    except (TypeError, ValueError):
        current = 0
    next_count = max(0, current + int(amount))
    session_data["region_replacement_count"] = next_count
    store.put(session_id, "region_replacement_count", next_count)
    return next_count


def _replacement_history_response(
    *,
    action: str,
    checkpoint: dict | None,
    session_data: dict,
    preview_url: str,
) -> ReplacementHistoryResponse:
    restored_kind = (
        str(checkpoint.get("kind", "content"))
        if isinstance(checkpoint, dict)
        else "content"
    )
    return ReplacementHistoryResponse(
        status="ok",
        action=action,  # type: ignore[arg-type]
        label=str(checkpoint.get("label")) if isinstance(checkpoint, dict) else None,
        entry_kind=restored_kind,
        message="Replacement history restored",
        preview_url=preview_url,
        preview_glb_url=None,
        replacement_regions=_current_replacement_regions(session_data),
        recipe_overrides=_current_recipe_overrides(session_data),
        recipe_override_count=int(session_data.get("recipe_override_count") or 0),
        region_replacement_count=int(session_data.get("region_replacement_count") or 0),
        color_layers=(
            int(session_data["color_layers"])
            if session_data.get("color_layers") is not None
            else None
        ),
        layer_height_mm=(
            float(session_data["layer_height_mm"])
            if session_data.get("layer_height_mm") is not None
            else None
        ),
        gradient_groups=session_data.get("gradient_groups"),
        free_color_set=sorted(
            str(value).replace("#", "").lower()
            for value in (session_data.get("free_color_set") or set())
        ),
        **_history_flags(session_data),
    )



def _get_cached_visible_region_mask(
    session_data: dict,
    region_id: str | None,
) -> np.ndarray | None:
    if not isinstance(region_id, str) or not region_id:
        return None
    component_refs = session_data.get("selected_region_component_refs") or {}
    if not isinstance(component_refs, dict):
        return None
    component_ref = component_refs.get(region_id)
    if not isinstance(component_ref, dict):
        return None
    try:
        label = int(component_ref.get("label"))
        generation = int(component_ref.get("generation"))
    except (TypeError, ValueError):
        return None
    if generation != get_visible_region_generation(session_data):
        return None
    component_cache = get_valid_visible_region_cache(session_data)
    if component_cache is None:
        return None
    try:
        return component_mask(component_cache, label)
    except (KeyError, TypeError, ValueError):
        return None


def _upgrade_material_matrix_layers(
    material_matrix: np.ndarray,
    target_layers: int,
) -> np.ndarray:
    if material_matrix.shape[2] >= target_layers:
        return material_matrix.copy()
    pad = np.zeros(
        (*material_matrix.shape[:2], target_layers - material_matrix.shape[2]),
        dtype=material_matrix.dtype,
    )
    return np.concatenate([material_matrix.copy(), pad], axis=2)


def _sync_lut_material_matrix_for_diff(
    session_data: dict,
    cache: dict,
    diff_mask: np.ndarray,
    updated_rgb: np.ndarray,
) -> None:
    material_matrix = cache.get("material_matrix")
    if material_matrix is None:
        return
    target_layers = int(
        cache.get("color_layers")
        or session_data.get("color_layers")
        or material_matrix.shape[2]
    )
    layer_height_mm = float(
        cache.get("layer_height_mm")
        or session_data.get("layer_height_mm")
        or 0.08
    )
    try:
        lut_data = load_session_lut_runtime(
            session_data,
            color_layers=target_layers,
            layer_height_mm=layer_height_mm,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        log.warning(
            "LUT replacement stack sync failed",
            extra={
                "event": "converter_replace_lut_stack_sync_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return
    if lut_data is None:
        return

    ref_stacks = np.asarray(lut_data.get("ref_stacks"))
    kdtree = lut_data.get("kdtree")
    if ref_stacks.ndim != 2 or ref_stacks.shape[0] == 0 or kdtree is None:
        return

    new_material_matrix = _upgrade_material_matrix_layers(
        np.asarray(material_matrix),
        int(ref_stacks.shape[1]),
    )
    unique_colors = np.unique(updated_rgb[diff_mask], axis=0)
    lut_rows = lut_row_indices_for_colors(lut_data, unique_colors)
    for color, lut_row in zip(unique_colors, lut_rows):
        color_mask = np.all(updated_rgb == color, axis=-1) & diff_mask
        stack = ref_stacks[int(lut_row)]
        new_material_matrix[color_mask] = np.asarray(
            stack,
            dtype=new_material_matrix.dtype,
        )
    cache["material_matrix"] = new_material_matrix
    cache["color_layers"] = int(new_material_matrix.shape[2])


def _sync_material_archive_matrix_for_diff(
    session_data: dict,
    cache: dict,
    diff_mask: np.ndarray,
    updated_rgb: np.ndarray,
) -> None:
    material_matrix = cache.get("material_matrix")
    if material_matrix is None:
        return
    dynamic_enabled = bool(
        session_data.get("material_dynamic_layer_count_enabled", False)
    )
    selected_materials = session_data.get("selected_materials") or []
    if not isinstance(selected_materials, list) or len(selected_materials) == 0:
        if dynamic_enabled:
            from core.material_dynamic_solver import DynamicMaterialCandidateError

            raise DynamicMaterialCandidateError(
                "selected material archives are unavailable",
                layer_count=int(session_data.get("material_max_layer_count") or 10),
                phase="runtime_load",
            )
        return

    try:
        materials = load_multiple_materials(selected_materials)
    except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
        if dynamic_enabled:
            from core.material_dynamic_solver import DynamicMaterialCandidateError

            raise DynamicMaterialCandidateError(
                "selected material archives could not be loaded",
                layer_count=int(session_data.get("material_max_layer_count") or 10),
                phase="runtime_load",
            ) from exc
        log.warning(
            "Material-archive replacement stack sync failed during material load",
            extra={
                "event": "converter_replace_material_stack_load_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return

    layer_count = int(
        session_data.get("material_layer_count")
        or cache.get("color_layers")
        or material_matrix.shape[2]
    )
    layer_height_mm = float(
        session_data.get("material_layer_height_mm")
        or cache.get("layer_height_mm")
        or session_data.get("layer_height_mm")
        or 0.08
    )
    substrate = str(
        cache.get("material_substrate")
        or session_data.get("material_substrate")
        or "white"
    )
    target_rgbs = np.unique(updated_rgb[diff_mask], axis=0).astype(np.uint8, copy=False)

    if dynamic_enabled:
        from core.material_dynamic_solver import DynamicMaterialCandidateError

        max_layer_count = int(session_data.get("material_max_layer_count") or 10)
        target_rgb_map = cache.get("quantized_image")
        if (
            not isinstance(target_rgb_map, np.ndarray)
            or target_rgb_map.shape != updated_rgb.shape
        ):
            raise DynamicMaterialCandidateError(
                "dynamic target RGB map is unavailable or inconsistent",
                layer_count=max_layer_count,
                phase="target_map",
            )
        backing_index = _resolve_material_backing_index(
            selected_materials,
            session_data.get("material_backing_material_index"),
        )
        min_layer_count = int(session_data.get("material_min_layer_count") or 5)
        tolerance = float(session_data.get("material_delta_e00_tolerance", 0.5))
        try:
            resolved_recipe_masks = resolve_recipe_override_masks(
                session_data,
                session_data.get("recipe_overrides"),
                tuple(np.asarray(updated_rgb).shape[:2]),
            )
        except ValueError as exc:
            raise DynamicMaterialCandidateError(
                "Committed recipe override masks are missing or invalid",
                layer_count=max_layer_count,
                phase="manual_mask",
            ) from exc
        result = rebuild_dynamic_material_after_replacement(
            updated_rgb=np.asarray(updated_rgb, dtype=np.uint8),
            diff_mask=np.asarray(diff_mask, dtype=bool),
            target_rgb_map=target_rgb_map,
            solid_mask=np.asarray(cache.get("mask_solid"), dtype=bool),
            material_matrix=np.asarray(material_matrix),
            materials=materials,
            backing_material_index=backing_index,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            min_layer_count=min_layer_count,
            max_layer_count=max_layer_count,
            delta_e00_tolerance=tolerance,
            region_masks=resolved_recipe_masks,
            recipe_overrides=session_data.get("recipe_overrides"),
            existing_solver_info=cache.get("material_solver_info"),
            solver=_solve_dynamic_material_targets,
        )
        updated_rgb[...] = result.matched_rgb
        cache["material_matrix"] = result.material_matrix
        cache["quantized_image"] = result.target_rgb_map
        cache["color_layers"] = max_layer_count
        cache["layer_height_mm"] = float(layer_height_mm)
        cache["material_dynamic_layer_info"] = result.dynamic_layer_info
        cache["material_solver_info"] = result.solver_info
        return

    grid_resolution = int(
        session_data.get("material_grid_resolution")
        or DEFAULT_GRID_RESOLUTION
    )
    log.debug(
        "material-archive matrix sync: solving",
        extra={
            "event": "converter_replace_material_sync_solve",
            "target_rgb_count": int(target_rgbs.shape[0]),
            "target_rgbs_sample": target_rgbs[:3].tolist(),
            "grid_resolution": grid_resolution,
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "material_count": len(materials),
        },
    )
    try:
        solver_cache, _actual_grid = load_material_solver_cache_with_fallback(
            materials=materials,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            grid_resolution=grid_resolution,
        )
        _solve_path = "cache" if solver_cache is not None else "mitm"
        if solver_cache is not None:
            resolved_rgb, recipes, _delta_e = solver_cache.lookup(target_rgbs, materials)
        else:
            resolved_rgb, recipes, _delta_e = solve_image_colors_optimal(
                target_rgbs,
                materials,
                layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
            )
        log.debug(
            "material-archive matrix sync: solved",
            extra={
                "event": "converter_replace_material_sync_solved",
                "solve_path": _solve_path,
                "actual_grid": _actual_grid,
                "target_rgbs_sample": target_rgbs[:3].tolist(),
                "resolved_rgbs_sample": resolved_rgb[:3].tolist() if resolved_rgb is not None else None,
            },
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        log.warning(
            "Material-archive replacement stack sync solve failed",
            extra={
                "event": "converter_replace_material_stack_solve_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return

    if recipes.shape[1] > 1:
        recipes = np.ascontiguousarray(recipes[:, ::-1])

    recipe_layers = int(recipes.shape[1])
    material_matrix_arr = np.asarray(material_matrix)
    if material_matrix_arr.shape[2] > recipe_layers:
        new_material_matrix = material_matrix_arr[:, :, :recipe_layers].copy()
    else:
        new_material_matrix = _upgrade_material_matrix_layers(
            material_matrix_arr,
            recipe_layers,
        )
    color_masks = [
        np.all(updated_rgb == color, axis=-1) & diff_mask for color in target_rgbs
    ]
    for idx, color_mask in enumerate(color_masks):
        if not np.any(color_mask):
            continue
        updated_rgb[color_mask] = resolved_rgb[idx].astype(np.uint8, copy=False)
        new_material_matrix[color_mask] = recipes[idx].astype(
            new_material_matrix.dtype,
            copy=False,
        )
    cache["material_matrix"] = new_material_matrix
    cache["color_layers"] = int(new_material_matrix.shape[2])
    cache["layer_height_mm"] = float(layer_height_mm)


def _sync_material_matrix_after_rgb_change(
    session_data: dict,
    cache: dict,
    previous_rgb: np.ndarray,
    updated_rgb: np.ndarray,
) -> None:
    material_matrix = cache.get("material_matrix")
    mask_solid = cache.get("mask_solid")
    if material_matrix is None or mask_solid is None:
        return

    diff_mask = np.any(previous_rgb != updated_rgb, axis=-1) & np.asarray(
        mask_solid,
        dtype=bool,
    )
    if not np.any(diff_mask):
        return

    if str(session_data.get("material_source") or "lut") == "material_archive":
        _sync_material_archive_matrix_for_diff(session_data, cache, diff_mask, updated_rgb)
    else:
        _sync_lut_material_matrix_for_diff(session_data, cache, diff_mask, updated_rgb)
    cache["color_palette"] = extract_color_palette(cache)


# Extend base tuple with IndexError for array-index operations
# in region-detect / region-replace endpoints.
REPLACE_HANDLED_ERRORS = ROUTER_HANDLED_ERRORS + (IndexError,)


def _rgb_pixel_to_hex(pixel: np.ndarray) -> str:
    rgb = np.asarray(pixel).reshape(-1)
    if rgb.size < 3:
        raise ValueError("RGB pixel must contain at least three channels.")
    r, g, b = (int(np.clip(value, 0, 255)) for value in rgb[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


@router.post("/replace-color")
def replace_color(
    request: ColorReplaceRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ColorReplaceResponse:
    """Replace one colour and keep the dynamic matrix/cache coherent.
    替换一个颜色，并保持动态矩阵与缓存一致。

    Args:
        request (ColorReplaceRequest): Color replacement parameters. (颜色替换参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        ColorReplaceResponse: Replacement result with preview URL. (替换结果及预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    selection_response: SelectionDocumentResponse | None = None
    operation_id = request.operation_id
    editor_content_revision: int | None = None
    cache_published = False
    session_data: dict | None = None
    try:
        session_data = _require_session(store, request.session_id)
        operation_id = begin_editor_commit(
            request.session_id,
            store,
            session_data,
            operation_id=request.operation_id,
            operation="replace_color",
        )
        with _preview_cache_transaction(
            request.session_id,
            store,
            session_data,
            fields={
                "matched_rgb",
                "material_matrix",
                "mask_solid",
                "quantized_image",
            },
        ) as cache:
            # The transaction already owns the per-session editor lock. Take
            # the undo checkpoint here so it is the state immediately before
            # this cache/session publication, not a racing earlier snapshot.
            history_checkpoint = snapshot_replacement_state(
                session_data,
                label="replace_color",
            )
            # Parse hex colors to RGB tuples
            selected_rgb = ColorReplacementManager._hex_to_color(request.selected_color)
            replacement_rgb = ColorReplacementManager._hex_to_color(request.replacement_color)

            # Build manager from all existing replacement_regions
            manager = ColorReplacementManager()
            for record in session_data.get("replacement_regions", []):
                orig = ColorReplacementManager._hex_to_color(record["selected_color"])
                repl = ColorReplacementManager._hex_to_color(record["replacement_color"])
                manager.add_replacement(orig, repl)

            # Add the new replacement
            manager.add_replacement(selected_rgb, replacement_rgb)

            # Apply all replacements to the original matched_rgb
            matched_rgb: np.ndarray = cache["matched_rgb"]
            previous_rgb = matched_rgb.copy()
            replaced_rgb = manager.apply_to_image(matched_rgb)

            # --- diagnostic logging ---
            diff_pixels = int(np.any(previous_rgb != replaced_rgb, axis=-1).sum())
            log.debug(
                "replace-color diag",
                extra={
                    "event": "converter_replace_color_diag",
                    "selected_color": request.selected_color,
                    "replacement_color": request.replacement_color,
                    "material_source": session_data.get("material_source"),
                    "matched_rgb_shape": list(matched_rgb.shape),
                    "diff_pixel_count": diff_pixels,
                    "replacement_region_count": len(session_data.get("replacement_regions", [])),
                    "has_material_matrix": cache.get("material_matrix") is not None,
                    "has_mask_solid": cache.get("mask_solid") is not None,
                },
            )
            # --- end diagnostic logging ---

            # Update cache so 3D preview reflects replacements
            cache["matched_rgb"] = replaced_rgb
            _sync_material_matrix_after_rgb_change(
                session_data, cache, previous_rgb, replaced_rgb
            )

            # Generate styled preview PNG (with bed grid and transparency)
            preview_bytes = _render_styled_preview_bytes(replaced_rgb, cache)
            preview_id = registry.register_bytes(request.session_id, preview_bytes, "preview_replaced.png")
            persisted_cache = cache.commit(
                _dirty_array_fields(
                    cache,
                    "matched_rgb",
                    "material_matrix",
                    "quantized_image",
                    "preview_rgba",
                ),
                metadata_fields=_REPLACEMENT_CACHE_METADATA_FIELDS,
            )
            cache_published = True
            _invalidate_and_prewarm_visible_region_cache(request.session_id, store, session_data, cache)

            # Publish the replacement record before exposing the operation as
            # committed. A lost HTTP response can therefore query one receipt
            # instead of inferring state from a visible-cache generation delta.
            current_regions = session_data.get("replacement_regions", [])
            if not isinstance(current_regions, list):
                current_regions = []
            current_regions = [*current_regions, {
                "selected_color": request.selected_color,
                "replacement_color": request.replacement_color,
            }]
            session_data["replacement_regions"] = current_regions
            store.put(request.session_id, "replacement_regions", current_regions)
            editor_content_revision = advance_editor_content_revision(
                request.session_id,
                store,
                session_data,
            )
            selection_response = _selection_after_content_commit(
                request.session_id,
                store,
                session_data,
                cache,
            )
            history_flags = _push_history_checkpoint(
                request.session_id,
                store,
                session_data,
                history_checkpoint,
            )
            publish_editor_commit(
                request.session_id,
                store,
                session_data,
                operation_id=operation_id,
                editor_content_revision=editor_content_revision,
                selection_revision=get_selection_revision(session_data),
                result=_editor_commit_result(
                    session_data,
                    cache=cache,
                    preview_url=f"/api/files/{preview_id}",
                ),
            )

        # Schedule async segmented-GLB rebuild so this response returns
        # immediately after the PNG is ready. Frontend polls
        # /api/convert/glb-status/{session_id} to pick up the new GLB URL.
        # 异步重建分段 GLB：响应在 PNG 就绪后立即返回，前端轮询 glb-status。
        _schedule_glb_build_best_effort(
            request.session_id,
            store,
            registry,
            persisted_cache,
        )
        glb_url: str | None = None

    except HTTPException as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        raise
    except PreviewCacheRevisionConflict as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _raise_replace_cache_conflict(
            e,
            session_id=request.session_id,
            operation="replace_color",
        )
    except REPLACE_HANDLED_ERRORS as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _handle_core_error(e, "Color replacement")

    log.info(
        "replace-color completed",
        extra={
            "event": "converter_replace_color_done",
            "session_id": request.session_id,
            "selected_color": request.selected_color,
            "replacement_color": request.replacement_color,
            "replacement_count": len(current_regions),
            "diff_pixel_count": diff_pixels,
        },
    )
    return ColorReplaceResponse(
        status="ok",
        message="Color replaced successfully",
        preview_url=f"/api/files/{preview_id}",
        preview_3d_url=glb_url,
        replacement_count=len(current_regions),
        **dynamic_material_result_from_cache(cache).model_dump(
            exclude={"operation_id", "editor_content_revision"}
        ),
        **history_flags,
        operation_id=operation_id,
        editor_content_revision=editor_content_revision,
        selection=selection_response,
    )


@router.post("/free-colors", response_model=FreeColorMutationResponse)
def mutate_free_colors(
    request: FreeColorMutationRequest,
    store: SessionStore = Depends(get_session_store),
) -> FreeColorMutationResponse:
    """Apply free-colour flags as a checkpointed content operation."""
    session_data: dict | None = None
    operation_id: str | None = None
    # Once the free-colour field is written, a later exception must remain
    # unknown rather than being reported as a known pre-commit failure.
    commit_boundary_crossed = False
    try:
        with replacement_history_lock(request.session_id):
            session_data = _require_session(store, request.session_id)
            operation_id = begin_editor_commit(
                request.session_id,
                store,
                session_data,
                operation_id=request.operation_id,
                operation="free_colors",
            )
            checkpoint = snapshot_replacement_state(session_data, label="free_colors")
            current = {
                str(value).replace("#", "").lower()
                for value in (session_data.get("free_color_set") or set())
            }
            if request.action == "clear":
                next_colors: set[str] = set()
            elif request.action == "replace":
                next_colors = {
                    str(value).replace("#", "").lower()
                    for value in request.color_hexes
                    if str(value).replace("#", "")
                }
            else:
                next_colors = set(current)
                for raw in request.color_hexes:
                    normalized = str(raw).replace("#", "").lower()
                    if normalized in next_colors:
                        next_colors.remove(normalized)
                    elif normalized:
                        next_colors.add(normalized)
            editor_content_revision = get_editor_content_revision(session_data)
            if next_colors != current:
                commit_boundary_crossed = True
                session_data["free_color_set"] = next_colors
                store.put(request.session_id, "free_color_set", next_colors)
                push_replacement_checkpoint(
                    request.session_id,
                    store,
                    session_data,
                    checkpoint,
                )
                editor_content_revision = advance_editor_content_revision(
                    request.session_id,
                    store,
                    session_data,
                )
            publish_editor_commit(
                request.session_id,
                store,
                session_data,
                operation_id=operation_id,
                editor_content_revision=editor_content_revision,
                selection_revision=get_selection_revision(session_data),
                result=_editor_commit_result(session_data),
            )
            return FreeColorMutationResponse(
                free_color_set=sorted(next_colors),
                operation_id=operation_id,
                editor_content_revision=editor_content_revision,
                **_history_flags(session_data),
            )
    except HTTPException as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=commit_boundary_crossed,
            error_type=type(exc).__name__,
        )
        raise
    except REPLACE_HANDLED_ERRORS as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=commit_boundary_crossed,
            error_type=type(exc).__name__,
        )
        _handle_core_error(exc, "Free color mutation")


@router.post("/reset-replacements", response_model=ResetReplacementsResponse)
def reset_replacements(
    request: ResetReplacementsRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ResetReplacementsResponse:
    """Reset all color replacements and restore original preview.
    重置所有颜色替换并恢复原始预览。

    Clears replacement and manual-recipe state from the session, then
    regenerates the preview from the original matched_rgb cache. A manual
    override cannot remain active after its matrix has been restored to the
    preview snapshot, otherwise a later generate request would silently
    re-apply it.
    清空 session 中的替换和手工配方状态，然后从原始 matched_rgb 缓存重新生成
    预览。矩阵已恢复到预览快照后，手工覆盖不能继续保留，否则后续 generate
    会静默把它重新应用。

    Args:
        request (ResetReplacementsRequest): Reset request with session_id. (重置请求)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        ResetReplacementsResponse: Reset result with original preview URL. (重置结果及原始预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    selection_response: SelectionDocumentResponse | None = None
    operation_id: str | None = None
    editor_content_revision: int | None = None
    cache_published = False
    session_data: dict | None = None
    try:
        session_data = _require_session(store, request.session_id)
        operation_id = begin_editor_commit(
            request.session_id,
            store,
            session_data,
            operation_id=request.operation_id,
            operation="reset_replacements",
        )
        with _preview_cache_transaction(
            request.session_id,
            store,
            session_data,
            fields={
                "matched_rgb",
                "material_matrix",
                "original_matched_rgb",
                "original_material_matrix",
                "quantized_image",
                "original_quantized_image",
                "mask_solid",
            },
        ) as cache:
            history_checkpoint = snapshot_replacement_state(
                session_data,
                label="reset_replacements",
            )
            regions_cleared = len(session_data.get("replacement_regions", []))
            recipe_overrides_cleared = len(
                session_data.get("recipe_overrides") or []
            )
            history_truncated = 0
            previous_rgb = np.asarray(cache.get("matched_rgb")).copy()

            # Restore matched_rgb from the pristine original saved at preview time.
            # region-replace mutates cache["matched_rgb"] in-place, so we must
            # use the untouched copy to truly reset.
            original_rgb: np.ndarray | None = session_data.get(
                "original_matched_rgb"
            )
            if original_rgb is None:
                original_rgb = cache.get("original_matched_rgb")
            if original_rgb is not None:
                # Restore cache to original state
                cache["matched_rgb"] = original_rgb.copy()
                source_rgb = original_rgb
            else:
                # Fallback: no original saved (legacy session), use current cache
                source_rgb = cache["matched_rgb"]

            original_material_matrix: np.ndarray | None = session_data.get(
                "original_material_matrix"
            )
            if original_material_matrix is None:
                original_material_matrix = cache.get("original_material_matrix")
            if original_material_matrix is not None:
                cache["material_matrix"] = original_material_matrix.copy()
            elif original_rgb is not None:
                _sync_material_matrix_after_rgb_change(
                    session_data,
                    cache,
                    previous_rgb,
                    cache["matched_rgb"],
                )
            original_quantized_image: np.ndarray | None = session_data.get(
                "original_quantized_image"
            )
            if original_quantized_image is None:
                original_quantized_image = cache.get(
                    "original_quantized_image"
                )
            if original_quantized_image is not None:
                cache["quantized_image"] = original_quantized_image.copy()
            original_dynamic_info = cache.get(
                "original_material_dynamic_layer_info"
            )
            original_solver_info = cache.get("original_material_solver_info")
            if isinstance(original_dynamic_info, dict):
                cache["material_dynamic_layer_info"] = deepcopy(
                    original_dynamic_info
                )
            elif bool(
                session_data.get("material_dynamic_layer_count_enabled", False)
            ):
                # Legacy sessions did not snapshot the original dynamic
                # metadata. Returning the post-edit curve after restoring the
                # original RGB/matrix would be incorrect, so make absence
                # explicit and let the next preview rebuild authoritative data.
                cache.pop("material_dynamic_layer_info", None)
            if isinstance(original_solver_info, dict):
                cache["material_solver_info"] = deepcopy(original_solver_info)
            elif bool(
                session_data.get("material_dynamic_layer_count_enabled", False)
            ):
                cache.pop("material_solver_info", None)
            cache["color_palette"] = extract_color_palette(cache)
            persisted_cache = cache.commit(
                _dirty_array_fields(
                    cache,
                    "matched_rgb",
                    "material_matrix",
                    "quantized_image",
                ),
                metadata_fields=_REPLACEMENT_CACHE_METADATA_FIELDS,
            )
            cache_published = True
            # Clear session edit state only after the cache transaction has
            # committed. A failed commit must leave the prior work recoverable.
            # 只有缓存事务提交成功后才清理会话编辑状态；提交失败时必须保留
            # 用户上一份可恢复作品。
            store.put(request.session_id, "replacement_regions", [])
            session_data["replacement_regions"] = []
            store.put(request.session_id, "replacement_history", [])
            session_data["replacement_history"] = []
            store.put(request.session_id, "global_replacement_base_matched_rgb", None)
            session_data["global_replacement_base_matched_rgb"] = None
            store.put(
                request.session_id,
                "global_replacement_base_material_matrix",
                None,
            )
            session_data["global_replacement_base_material_matrix"] = None
            store.put(request.session_id, "recipe_overrides", [])
            session_data["recipe_overrides"] = []
            store.put(request.session_id, "recipe_override_count", 0)
            session_data["recipe_override_count"] = 0
            session_data[RECIPE_OVERRIDE_APPLIED_MASKS_KEY] = {}
            store.put(request.session_id, RECIPE_OVERRIDE_APPLIED_MASKS_KEY, {})
            _invalidate_and_prewarm_visible_region_cache(request.session_id, store, session_data, cache)
            editor_content_revision = advance_editor_content_revision(
                request.session_id,
                store,
                session_data,
            )
            selection_response = _selection_after_content_commit(
                request.session_id,
                store,
                session_data,
                cache,
            )
            history_flags = _push_history_checkpoint(
                request.session_id,
                store,
                session_data,
                history_checkpoint,
            )
            # Register the committed preview before publishing the receipt so
            # a lost reset response can restore the same preview identity.
            preview_bytes = _image_to_png_bytes(source_rgb)
            preview_id = registry.register_bytes(
                request.session_id,
                preview_bytes,
                "preview_reset.png",
            )
            publish_editor_commit(
                request.session_id,
                store,
                session_data,
                operation_id=operation_id,
                editor_content_revision=editor_content_revision,
                selection_revision=get_selection_revision(session_data),
                result=_editor_commit_result(
                    session_data,
                    cache=cache,
                    preview_url=f"/api/files/{preview_id}",
                    preview_glb_url=None,
                ),
            )

        # Regenerate preview from original matched_rgb (no replacements applied)
        # Async GLB rebuild from restored matched_rgb. Same rationale as
        # /replace-color: keep HTTP response snappy, let the frontend poll.
        # 异步 GLB 重建，理由同 /replace-color。
        _schedule_glb_build_best_effort(
            request.session_id,
            store,
            registry,
            persisted_cache,
        )
        glb_url: str | None = None
    except HTTPException as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        raise
    except PreviewCacheRevisionConflict as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _raise_replace_cache_conflict(
            e,
            session_id=request.session_id,
            operation="reset_replacements",
        )
    except REPLACE_HANDLED_ERRORS as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _handle_core_error(e, "Reset replacements")

    log.info(
        "reset-replacements completed",
        extra={
            "event": "converter_reset_replacements_done",
            "session_id": request.session_id,
            "regions_cleared": regions_cleared,
            "recipe_overrides_cleared": recipe_overrides_cleared,
            "history_truncated": history_truncated,
        },
    )
    return ResetReplacementsResponse(
        status="ok",
        message="All replacements cleared",
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=glb_url,
        **dynamic_material_result_from_cache(cache).model_dump(
            exclude={"operation_id", "editor_content_revision"}
        ),
        **history_flags,
        operation_id=operation_id,
        editor_content_revision=editor_content_revision,
        selection=selection_response,
    )


@router.post("/replacement-history", response_model=ReplacementHistoryResponse)
def replacement_history(
    request: ReplacementHistoryRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ReplacementHistoryResponse:
    """Undo or redo one color-adjustment operation.
    撤销或重做一次颜色调整操作。
    """
    session_data: dict | None = None
    operation_id: str | None = request.operation_id
    # This flag means that the route has crossed the point where the session
    # or cache may have been mutated.  From that point on an exception must
    # remain pending/unknown; marking the receipt as "failed" would lie about
    # a partially restored undo/redo state.
    # 该标记表示路由已经越过会话或缓存可能发生变更的边界；越过后只能保持
    # pending/unknown，不能把可能部分恢复的撤销/重做伪报为 failed。
    cache_published = False
    try:
        with replacement_history_lock(request.session_id):
            session_data = _require_session(store, request.session_id)
            operation_id = begin_editor_commit(
                request.session_id,
                store,
                session_data,
                operation_id=request.operation_id,
                operation=f"replacement_history_{request.action}",
            )
            try:
                checkpoint = restore_from_history(
                    request.session_id,
                    store,
                    session_data,
                    action=request.action,
                )
            except IndexError as exc:
                fail_editor_commit(
                    request.session_id,
                    store,
                    session_data,
                    operation_id=operation_id,
                    error_type=type(exc).__name__,
                )
                raise HTTPException(
                    status_code=409,
                    detail=f"No replacement {request.action} history available.",
                ) from exc

            # restore_from_history has already moved session fields and the
            # undo/redo stacks.  Even the subsequent cache step fails, the
            # result is no longer a known pre-commit failure.
            # restore_from_history 已经改动会话字段与撤销/重做栈；即使后续
            # 缓存步骤失败，也不能再把结果认定为确定的提交前失败。
            cache_published = True

            if checkpoint.get("kind") == "selection":
                cache = _require_preview_cache_fields(
                    session_data,
                    fields={"matched_rgb", "mask_solid"},
                )
                component_cache, _cache_hit = _ensure_visible_region_component_cache(
                    request.session_id,
                    store,
                    session_data,
                    cache,
                )
                response = _replacement_history_response(
                    action=request.action,
                    checkpoint=checkpoint,
                    session_data=session_data,
                    preview_url=str(
                        session_data.get("preview_url")
                        or session_data.get("original_preview_url")
                        or ""
                    ),
                )
                response.selection = _selection_document_response(
                    session_data,
                    component_cache,
                    _get_visible_region_source_rgb(cache),
                )
                publish_editor_commit(
                    request.session_id,
                    store,
                    session_data,
                    operation_id=operation_id,
                    editor_content_revision=get_editor_content_revision(session_data),
                    selection_revision=response.selection.selection_revision,
                    result=_editor_commit_result(
                        session_data,
                        cache=cache,
                        preview_url=response.preview_url,
                    ),
                )
                response.operation_id = operation_id
                response.editor_content_revision = get_editor_content_revision(
                    session_data
                )
                return response

            with _preview_cache_transaction(
                request.session_id,
                store,
                session_data,
                fields={"matched_rgb", "mask_solid"},
            ) as cache:
                matched_rgb = cache.get("matched_rgb")
                if matched_rgb is None:
                    raise HTTPException(
                        status_code=409,
                        detail="Preview cache missing matched_rgb.",
                    )
                preview_bytes = _render_styled_preview_bytes(
                    np.asarray(matched_rgb, dtype=np.uint8),
                    cache,
                )
                preview_id = registry.register_bytes(
                    request.session_id,
                    preview_bytes,
                    f"preview_replacement_{request.action}.png",
                )
                persisted_cache = cache.commit(
                    _dirty_array_fields(cache, "preview_rgba"),
                    metadata_fields={"color_palette", "color_layers", "layer_height_mm"},
                )
                cache_published = True
                _invalidate_and_prewarm_visible_region_cache(
                    request.session_id,
                    store,
                    session_data,
                    cache,
                )
                editor_content_revision = advance_editor_content_revision(
                    request.session_id,
                    store,
                    session_data,
                )
                restored_selection = _selection_after_content_commit(
                    request.session_id,
                    store,
                    session_data,
                    cache,
                )
                publish_editor_commit(
                    request.session_id,
                    store,
                    session_data,
                    operation_id=operation_id,
                    editor_content_revision=editor_content_revision,
                    selection_revision=get_selection_revision(session_data),
                    result=_editor_commit_result(
                        session_data,
                        cache=cache,
                        preview_url=f"/api/files/{preview_id}",
                    ),
                )

            _schedule_glb_build_best_effort(
                request.session_id,
                store,
                registry,
                persisted_cache,
            )
            preview_url = f"/api/files/{preview_id}"
            response = _replacement_history_response(
                action=request.action,
                checkpoint=checkpoint,
                session_data=session_data,
                preview_url=preview_url,
            )
            response.selection = restored_selection
            response.operation_id = operation_id
            response.editor_content_revision = editor_content_revision
    except HTTPException as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        raise
    except PreviewCacheRevisionConflict as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _raise_replace_cache_conflict(
            e,
            session_id=request.session_id,
            operation=f"replacement_history_{request.action}",
        )
    except REPLACE_HANDLED_ERRORS as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _handle_core_error(e, "Replacement history")

    log.info(
        "replacement-history completed",
        extra={
            "event": "converter_replacement_history_done",
            "session_id": request.session_id,
            "action": request.action,
            "can_undo": response.can_undo,
            "can_redo": response.can_redo,
        },
    )
    return response


@router.post("/source-color-pick", response_model=SourceColorPickResponse)
def source_color_pick(
    request: SourceColorPickRequest,
    store: SessionStore = Depends(get_session_store),
) -> SourceColorPickResponse:
    """Resolve the current matched colour at a preview pixel.
    解析预览像素位置的当前匹配色。

    Select-all clicks are based on the current matched colour visible in the
    preview. This intentionally follows user edits such as colour replacement
    and custom recipe overrides instead of going back to the first preview's
    ``original_matched_rgb``.
    全选点图按当前预览实际匹配色选中；这会跟随颜色替换和自定义配方等
    用户编辑，而不是回到第一次预览的 ``original_matched_rgb``。

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): Preview cache is incomplete or inconsistent.
            (预览缓存缺失或尺寸不一致)
        HTTPException(400): Coordinates are out of bounds or background.
            (坐标越界或点在背景上)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache_fields(
        session_data,
        fields={
            "matched_rgb",
            "quantized_image",
            "mask_solid",
        },
    )

    try:
        source_rgb = cache.get("matched_rgb")

        quantized_image = cache.get("quantized_image")
        mask_solid = cache.get("mask_solid")
        if source_rgb is None or quantized_image is None or mask_solid is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Preview cache missing matched_rgb, "
                    "quantized_image, or mask_solid."
                ),
            )

        source_arr = np.asarray(source_rgb)
        quantized_arr = np.asarray(quantized_image)
        mask_arr = np.asarray(mask_solid, dtype=bool)
        if source_arr.ndim != 3 or source_arr.shape[2] < 3:
            raise HTTPException(
                status_code=409,
                detail="Preview source matched RGB cache has invalid shape.",
            )
        if quantized_arr.ndim != 3 or quantized_arr.shape[2] < 3:
            raise HTTPException(
                status_code=409,
                detail="Preview quantized image cache has invalid shape.",
            )

        height, width = source_arr.shape[:2]
        if quantized_arr.shape[:2] != (height, width) or mask_arr.shape != (
            height,
            width,
        ):
            raise HTTPException(
                status_code=409,
                detail="Preview cache dimensions are inconsistent.",
            )

        x, y = request.x, request.y
        if not (0 <= x < width and 0 <= y < height):
            raise HTTPException(
                status_code=400,
                detail=f"Coordinates ({x}, {y}) out of bounds for image {width}x{height}.",
            )
        if not bool(mask_arr[y, x]):
            raise HTTPException(
                status_code=400,
                detail="Clicked on background area.",
            )

        picked_color = _rgb_pixel_to_hex(source_arr[y, x])
        quantized_hex = _rgb_pixel_to_hex(quantized_arr[y, x])
    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as exc:
        _handle_core_error(exc, "Source color pick")

    log.info(
        "source-color-pick completed",
        extra={
            "event": "converter_source_color_pick_done",
            "session_id": request.session_id,
            "picked_color": picked_color,
            "pick_x": request.x,
            "pick_y": request.y,
        },
    )
    return SourceColorPickResponse(
        source_matched_hex=picked_color,
        quantized_hex=quantized_hex,
    )


@router.post("/color-highlight", response_model=ColorHighlightResponse)
def color_highlight(
    request: ColorHighlightRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ColorHighlightResponse:
    """Highlight all pixels matching any of the given colors in the preview.
    在预览图中高亮所有匹配给定颜色的像素。

    Generates a preview image with semi-transparent cyan overlay on every
    pixel whose color matches any entry in ``color_hexes``.  Uses the same
    highlight style as ``region-detect`` (cyan ``[0, 200, 255]``, alpha 0.45).
    生成预览图，对颜色匹配 ``color_hexes`` 中任意条目的所有像素施加
    半透明青色叠加，样式与 ``region-detect`` 一致。

    Args:
        request: Color highlight parameters. (颜色高亮参数)
        store: Session store dependency. (会话存储依赖)
        registry: File registry dependency. (文件注册表依赖)

    Returns:
        ColorHighlightResponse: Highlighted preview URL. (高亮预览图 URL)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache_fields(
        session_data,
        fields={"matched_rgb", "mask_solid"},
    )

    try:
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")
        mask_solid: np.ndarray | None = cache.get("mask_solid")

        if matched_rgb is None or mask_solid is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing matched_rgb or mask_solid.",
            )

        # Parse color hex strings → RGB tuples
        target_rgbs: list[np.ndarray] = []
        for hex_str in request.color_hexes:
            h = hex_str.lstrip("#")
            if len(h) != 6:
                continue
            target_rgbs.append(np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], dtype=np.uint8))

        if not target_rgbs:
            raise HTTPException(status_code=400, detail="No valid color hex values provided.")

        # Optional region-scope constraint. When the Gradient Groups panel
        # asks us to highlight the colours inside one specific sub-region,
        # we clip the scan to the *exact* pixel mask of that sub-region so
        # unrelated same-colour pixels elsewhere on the canvas stay dark —
        # fixes the "clicking a sub-region lights up the whole group" UX
        # bug. Preferred path: ``gradient_group_index`` + ``gradient_region_index``
        # pair (uses the cached per-pixel region_id_map). Legacy fallback:
        # ``region_bbox`` rectangular scope.
        # 可选区域裁剪：最优先使用渐变分组/子区域编号精确裁剪，回退到
        # 矩形 bbox。修复"点小分组把整组都点亮"的 UX 问题。
        img_h, img_w = matched_rgb.shape[:2]
        region_scope_mask: np.ndarray | None = None

        group_idx = request.gradient_group_index
        region_idx = request.gradient_region_index
        # Diagnostic: capture which scope path the endpoint actually takes
        # given the request payload it actually received. This is the most
        # reliable way to tell apart "frontend forgot to send identifiers"
        # from "backend silently dropped them because the process wasn't
        # restarted after the schema change".
        # 诊断日志：明确记录 endpoint 真正收到的 scope 字段与分支走向，
        # 便于区分"前端未传"与"后端未重启（静默丢弃字段）"。
        log.debug(
            "color_highlight_invoked",
            extra={
                "event": "color_highlight_invoked",
                "session_id": request.session_id,
                "color_hex_count": len(request.color_hexes),
                "received_gradient_group_index": group_idx,
                "received_gradient_region_index": region_idx,
                "received_region_bbox": request.region_bbox,
                "image_shape": [img_h, img_w],
            },
        )
        if (group_idx is None) != (region_idx is None):
            raise HTTPException(
                status_code=400,
                detail=(
                    "gradient_group_index and gradient_region_index must be "
                    "provided together."
                ),
            )
        if group_idx is not None and region_idx is not None:
            # region_id_map is stored alongside ``gradient_groups`` at the
            # session-data top level (not inside ``preview_cache``) because
            # it's derived metadata computed *after* the preview cache is
            # finalised. Mirror that layout here for consistency.
            # region_id_map 与 gradient_groups 并列存于 session_data 顶层，
            # 与 preview_cache 分离。
            region_id_map = session_data.get("gradient_region_id_map")
            if region_id_map is None:
                raise HTTPException(
                    status_code=409,
                    detail=GRADIENT_REGION_METADATA_UNAVAILABLE_DETAIL,
                )
            region_id_arr = np.asarray(region_id_map)
            if region_id_arr.shape != (img_h, img_w):
                raise HTTPException(
                    status_code=409,
                    detail=GRADIENT_REGION_METADATA_STALE_DETAIL,
                )
            encoded_id = (
                int(group_idx) * REGION_ID_ENCODING_MULTIPLIER + int(region_idx)
            )
            region_scope_mask = region_id_arr == np.uint32(encoded_id)
            region_pixel_count = int(region_scope_mask.sum())
            log.debug(
                "color_highlight_using_region_mask",
                extra={
                    "event": "color_highlight_scope_region_mask",
                    "group_index": int(group_idx),
                    "region_index": int(region_idx),
                    "encoded_id": int(encoded_id),
                    "region_pixel_count": region_pixel_count,
                    "region_id_map_nonzero_count": int(
                        (region_id_arr != 0).sum()
                    ),
                },
            )
            if region_pixel_count == 0:
                # The analyser intentionally keeps regions in ``regions[]``
                # whose CC label could not be resolved back to any pixel
                # (centroid/bbox sampling missed all foreground samples,
                # see core/gradient_group_analyzer.py:_resolve_region_cc_label_for_regions).
                # Those regions still surface in the UI with a working
                # eye-button, so the contract here is to fall back to the
                # *group*-level mask when the group itself has any pixels,
                # and only return 404 when the group is genuinely absent.
                # 分析器对无法定位的 region 会保留在 regions[] 中（注释明确
                # 说调用方应回退到整组/整图），因此这里只在整组也找不到
                # 像素时才返回 404；否则回退到整组 mask，避免子区域眼睛
                # 按钮硬性 404。
                group_of_pixel = region_id_arr // np.uint32(
                    REGION_ID_ENCODING_MULTIPLIER
                )
                group_scope_mask = group_of_pixel == np.uint32(int(group_idx))
                group_pixel_count = int(group_scope_mask.sum())
                if group_pixel_count == 0:
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"No pixels found for gradient group "
                            f"{group_idx}, region {region_idx}."
                        ),
                    )
                log.warning(
                    "color_highlight_region_unmapped_group_fallback",
                    extra={
                        "event": "color_highlight_region_unmapped_group_fallback",
                        "error_type": "GradientRegionMaskMissing",
                        "error_message": (
                            "Gradient region mask was empty; using the parent group mask."
                        ),
                        "fallback_action": "use_group_mask",
                        "group_index": int(group_idx),
                        "region_index": int(region_idx),
                        "encoded_id": int(encoded_id),
                        "group_pixel_count": group_pixel_count,
                    },
                )
                region_scope_mask = group_scope_mask
        elif request.region_bbox is not None:
            x0, y0, x1, y1 = request.region_bbox
            if not (0 <= x0 < x1 <= img_w and 0 <= y0 < y1 <= img_h):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"region_bbox {request.region_bbox} out of bounds for "
                        f"image {img_w}x{img_h}."
                    ),
                )
            region_scope_mask = np.zeros((img_h, img_w), dtype=bool)
            region_scope_mask[y0:y1, x0:x1] = True

        # Build combined mask: pixels matching ANY of the given colors
        combined_mask = np.zeros((img_h, img_w), dtype=bool)
        for rgb in target_rgbs:
            combined_mask |= np.all(matched_rgb == rgb, axis=-1) & mask_solid
        if region_scope_mask is not None:
            combined_mask &= region_scope_mask
        highlighted_pixel_count = int(np.count_nonzero(combined_mask))
        highlighted_color = request.color_hexes[0]

        # Apply cyan highlight (same style as region-detect)
        highlight_color = np.array([0, 200, 255], dtype=np.uint8)
        alpha = 0.45
        preview_img: np.ndarray = matched_rgb.copy()
        preview_img[combined_mask] = (
            preview_img[combined_mask].astype(np.float32) * (1 - alpha)
            + highlight_color.astype(np.float32) * alpha
        ).astype(np.uint8)

        preview_bytes: bytes = _render_masked_preview_bytes(preview_img, mask_solid)
        preview_id: str = registry.register_bytes(
            request.session_id, preview_bytes, "color_highlight.png",
        )

    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Color highlight")

    log.info(
        "color-highlight completed",
        extra={
            "event": "converter_color_highlight_done",
            "session_id": request.session_id,
            "highlighted_color": highlighted_color,
            "highlighted_pixel_count": highlighted_pixel_count,
        },
    )
    return ColorHighlightResponse(preview_url=f"/api/files/{preview_id}")


@router.post("/region-detect", response_model=RegionDetectResponse)
def region_detect(
    request: RegionDetectRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RegionDetectResponse:
    """Detect a connected region of same-colored pixels at the click position.
    检测点击位置处同色像素的连通区域。

    This endpoint is synchronous because the flood-fill on the current
    visible preview colour image is lightweight. The heavy image processing
    was already completed in the /preview step.
    此端点同步执行，因为在当前可见预览色图上的洪水填充计算量很小。
    繁重的图像处理已在 /preview 步骤中完成。

    Args:
        request (RegionDetectRequest): Region detection parameters. (区域检测参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        RegionDetectResponse: Detected region metadata with preview URL. (检测到的区域元数据及预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(400): Click coordinates out of bounds or on background. (点击坐标越界或在背景上)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    started_at = time.perf_counter()
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache_fields(
        session_data,
        fields={"mask_solid", "matched_rgb"},
    )
    cache_ms = (time.perf_counter() - started_at) * 1000
    flood_fill_ms = 0.0
    contour_ms = 0.0
    preview_png_ms = 0.0
    preview_url: str | None = None

    try:
        x, y = request.x, request.y
        # Fast path: reuse a valid full component cache when one is already
        # built. Slow path (cache invalidated by a recent replacement): build
        # only the clicked colour's connected component ("click-lazy") instead
        # of the full per-colour index (~1s on large previews), so the click
        # returns in the ~300ms class. The full index keeps building in the
        # background prewarm for box-select / select-all / restore flows.
        # 快路径：已有全图缓存直接复用。慢路径（替换后缓存失效）：只对点击色做
        # 一次连通域（点击懒计算），不做全图逐色索引，让点击在约 300ms 级返回；
        # 全图索引由后台预热继续构建，供框选/全选/恢复使用。
        component_cache = get_valid_visible_region_cache(session_data)
        component_cache_hit = component_cache is not None
        click_lazy_mask: np.ndarray | None = None
        if component_cache is None:
            generation = get_visible_region_generation(session_data)
            try:
                component_cache = detect_single_component_at_point(
                    cache,
                    generation=generation,
                    x=request.x,
                    y=request.y,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except KeyError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Clicked on background area.",
                ) from exc
            # Build the full boolean mask for this component up-front so the
            # mutating endpoints can use it directly without depending on a
            # label that the background full-cache rebuild would invalidate.
            # 预先构建该块的完整 bool mask，替换端点可直接使用，避免依赖会被
            # 后台全图重建失效的 label。
            click_lazy_mask = component_mask(component_cache, 1)
            # Keep building the full index in the background for later flows.
            # 后台继续构建全图索引，供后续流程使用。
            schedule_visible_region_cache_prewarm(
                request.session_id,
                store,
                cache,
                generation=generation,
            )

        h = int(component_cache["height"])
        w = int(component_cache["width"])

        if not (0 <= x < w and 0 <= y < h):
            raise HTTPException(
                status_code=400,
                detail=f"Coordinates ({x}, {y}) out of bounds for image {w}x{h}.",
            )

        try:
            component_label, component = get_component_at(component_cache, x, y)
        except KeyError as exc:
            raise HTTPException(
                status_code=400,
                detail="Clicked on background area.",
            ) from exc

        pixel_count: int = int(component["pixel_count"])
        color_hex: str = str(component["color_hex"])
        region_id: str = str(component["region_id"])
        bbox_raw = component.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            bbox: tuple[int, int, int, int] | None = None
        else:
            bbox = tuple(int(value) for value in bbox_raw)

        # Store a lightweight component reference for subsequent replace /
        # recipe operations. The full boolean mask is rebuilt from label_map
        # only when a mutating endpoint actually needs it.
        # 点击阶段只存轻量引用，避免大图每次点击都构造整张 bool mask。
        store.put(request.session_id, "selected_region_id", region_id)
        if click_lazy_mask is not None:
            # Preserve the precise lazy mask under its stable region id for
            # recipe/content operations, but do not keep the legacy single-mask
            # slot alive. This avoids a large hidden one-shot state and lets the
            # background full cache replace only the lookup implementation.
            region_masks = session_data.get("selected_region_masks") or {}
            if not isinstance(region_masks, dict):
                region_masks = {}
            region_masks[region_id] = click_lazy_mask
            store.put(request.session_id, "selected_region_masks", region_masks)
            session_data["selected_region_masks"] = region_masks
            store.put(request.session_id, "selected_region_mask", None)
            session_data["selected_region_mask"] = None
            # Drop any stale label ref for this region so the mutating endpoint
            # falls back to selected_region_mask instead of a wrong label.
            # 清掉该区域可能存在的旧 label 引用，确保替换端点回退到现成 mask。
            component_refs = session_data.get("selected_region_component_refs") or {}
            if isinstance(component_refs, dict) and region_id in component_refs:
                component_refs.pop(region_id, None)
                store.put(request.session_id, "selected_region_component_refs", component_refs)
                session_data["selected_region_component_refs"] = component_refs
        else:
            store.put(request.session_id, "selected_region_mask", None)
            component_refs = session_data.get("selected_region_component_refs") or {}
            if not isinstance(component_refs, dict):
                component_refs = {}
            component_refs[region_id] = {
                "generation": get_visible_region_generation(session_data),
                "label": int(component_label),
            }
            store.put(request.session_id, "selected_region_component_refs", component_refs)

        # Return contours for frontend RGB outline rendering. The component
        # cache computes this lazily only for the clicked region and reuses it
        # on repeated clicks.
        # 轮廓只对当前点击块懒计算，并在重复点击时复用。
        contour_started_at = time.perf_counter()
        region_contours: list[list[list[float]]] | None = ensure_component_contours(
            component_cache,
            component_label,
        )
        contour_ms = (time.perf_counter() - contour_started_at) * 1000

        if request.include_preview:
            # Generate highlighted preview only for explicit debug/legacy
            # callers. The default click path uses contours and avoids the
            # expensive full-image copy + PNG encode + browser image reload.
            # 仅显式请求时生成高亮 PNG；默认点击路径由前端轮廓叠加显示。
            preview_started_at = time.perf_counter()
            matched_rgb: np.ndarray = _get_visible_region_source_rgb(cache)
            region_mask = component_mask(component_cache, component_label)
            highlight_color = np.array([0, 200, 255], dtype=np.uint8)  # cyan highlight
            alpha = 0.45
            preview_img: np.ndarray = matched_rgb.copy()
            preview_img[region_mask] = (
                preview_img[region_mask].astype(np.float32) * (1 - alpha) + highlight_color.astype(np.float32) * alpha
            ).astype(np.uint8)

            preview_bytes: bytes = _render_masked_preview_bytes(preview_img, cache["mask_solid"])
            preview_id: str = registry.register_bytes(request.session_id, preview_bytes, "region_highlight.png")
            preview_url = f"/api/files/{preview_id}"
            preview_png_ms = (time.perf_counter() - preview_started_at) * 1000

    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Region detection")

    log.info(
        "region-detect completed",
        extra={
            "event": "converter_region_detect_done",
            "session_id": request.session_id,
            "click_x": request.x,
            "click_y": request.y,
            "region_id": region_id,
            "component_cache_hit": component_cache_hit,
            "detected_pixel_count": pixel_count,
            "detected_dominant_color": color_hex,
            "contour_count": len(region_contours or []),
            "bbox": bbox,
            "include_preview": request.include_preview,
            "cache_ms": round(cache_ms, 2),
            "flood_fill_ms": round(flood_fill_ms, 2),
            "contour_ms": round(contour_ms, 2),
            "preview_png_ms": round(preview_png_ms, 2),
            "total_ms": round((time.perf_counter() - started_at) * 1000, 2),
        },
    )
    return RegionDetectResponse(
        region_id=region_id,
        color_hex=color_hex,
        pixel_count=pixel_count,
        preview_url=preview_url,
        contours=region_contours,
        bbox=bbox,
    )


def _selection_document_response(
    session_data: dict,
    component_cache: dict,
    matched_rgb: np.ndarray,
    *,
    brush_hit_component_count: int | None = None,
) -> SelectionDocumentResponse:
    payload = selection_summary(session_data, component_cache, matched_rgb)
    if brush_hit_component_count is not None:
        payload["brush_hit_component_count"] = brush_hit_component_count
    return SelectionDocumentResponse(
        **payload,
        **_history_flags(session_data),
        editor_content_revision=get_editor_content_revision(session_data),
    )


def _selection_after_content_commit(
    session_id: str,
    store: SessionStore,
    session_data: dict,
    preview_cache: dict,
) -> SelectionDocumentResponse | None:
    """Return selection state after a content commit and refresh its binding.
    返回内容提交后的选区状态，并刷新选区与内容版本的绑定。

    A colour edit invalidates the visible-component cache, but it does not
    necessarily invalidate the pixel geometry of the shared selection. Rebuild
    the component cache from the committed cache before returning so the client
    receives the server's actual content revision instead of guessing ``+1``.
    颜色编辑会使可见组件缓存失效，但不一定使共享选区的像素几何失效。
    这里从已提交缓存重建组件缓存，再返回服务端真实内容版本，避免客户端猜测
    ``+1``。
    """
    # Content publication owns replacement_history_lock; take the selection
    # lock in the same history -> selection order used by generation. This
    # keeps the returned document's revision/content binding from straddling
    # a concurrent selection gesture.
    with selection_lock(session_id):
        try:
            component_cache, _cache_hit = _ensure_visible_region_component_cache(
                session_id,
                store,
                session_data,
                preview_cache,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            # A content edit can be committed even when a legacy/minimal session
            # lacks the optional ``mask_solid`` needed to rebuild selection
            # components. Do not turn a successful content commit into a 500, and
            # do not fabricate a full-image selection; the next selection GET can
            # hydrate once the preview cache is complete.
            log.warning(
                "Selection summary unavailable after content commit",
                extra={
                    "event": "converter_selection_summary_unavailable",
                    "session_id": session_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "content_commit": "committed",
                },
            )
            return None
        content_generation = int(component_cache["generation"])
        sync_selection_content_generation(
            session_id,
            store,
            session_data,
            content_generation,
        )
        return _selection_document_response(
            session_data,
            component_cache,
            _get_visible_region_source_rgb(preview_cache),
        )


@router.get("/editor-project/{session_id}")
def export_editor_project(
    session_id: str,
    editor_content_revision: int | None = None,
    selection_revision: int | None = None,
    store: SessionStore = Depends(get_session_store),
) -> Response:
    """Capture a portable checkpoint at the confirmed editor/selection revision.

    在已确认的内容与选区版本下保存可携带快照，避免保存进行中的局部操作。
    """
    with _replacement_selection_lock(session_id):
        session = _require_session(store, session_id)
        if (
            editor_content_revision is not None
            and editor_content_revision != get_editor_content_revision(session)
        ) or (
            selection_revision is not None
            and selection_revision != get_selection_revision(session)
        ):
            raise HTTPException(status_code=409, detail="Editor changed while saving; wait for editing to finish and save again.")
        try:
            payload = build_editor_project(session)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    log.info("Project edits exported", extra={
        "event": "converter_project_edits_exported", "session_id": session_id,
        "asset_bytes": len(payload),
    })
    return Response(payload, media_type="application/gzip", headers={"Cache-Control": "no-store"})


@router.post("/editor-project/{session_id}/restore", response_model=EditorCommitStatusResponse)
def restore_editor_project(
    session_id: str,
    file: UploadFile = File(...),
    operation_id: str = Form(...),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> EditorCommitStatusResponse:
    """Initialize a fresh preview with saved editable pixels and spatial masks.

    将项目编辑内容与真实空间掩码恢复到新预览；不覆盖已有编辑会话。
    """
    try:
        payload = file.file.read(EDITOR_PROJECT_MAX_BYTES + 1)
    finally:
        file.file.close()
    with _replacement_selection_lock(session_id):
        session = _require_session(store, session_id)
        if get_editor_content_revision(session) != 0 or get_selection_revision(session) != 0:
            raise HTTPException(status_code=409, detail="Project edits can only initialize a fresh preview session.")
        try:
            checkpoint = decode_editor_project(payload, session)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        begin_editor_commit(session_id, store, session, operation_id=operation_id, operation="project_restore")
        cache = checkpoint.pop("preview_cache_arrays")
        restore_replacement_checkpoint(session_id, store, session, checkpoint)
        persisted = persist_preview_cache(session_id, store, cache)
        session["preview_cache"] = persisted
        _invalidate_and_prewarm_visible_region_cache(session_id, store, session, cache)
        mask = session.get("editor_selection_mask")
        if isinstance(mask, np.ndarray):
            persist_selection_mask(
                session_id, store, session, mask,
                content_generation=get_visible_region_generation(session),
                revision=get_selection_revision(session),
            )
        preview_id = registry.register_bytes(
            session_id, _render_styled_preview_bytes(cache["matched_rgb"], cache), "preview_project_restored.png",
        )
        revision = advance_editor_content_revision(session_id, store, session)
        _selection_after_content_commit(session_id, store, session, cache)
        result = _editor_commit_result(session, cache=cache, preview_url=f"/api/files/{preview_id}", preview_glb_url=None)
        publish_editor_commit(
            session_id, store, session, operation_id=operation_id,
            editor_content_revision=revision, selection_revision=get_selection_revision(session), result=result,
        )
    _schedule_or_run_overridden_glb_build(session_id, store, registry, cache, "preview_project_restored.glb")
    log.info("Project edits restored", extra={
        "event": "converter_project_edits_restored", "session_id": session_id,
        "editor_content_revision": revision,
    })
    return get_editor_commit_status(session_id, operation_id, store)


@router.get(
    "/selection/{session_id}",
    response_model=SelectionDocumentResponse,
)
def get_editor_selection(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> SelectionDocumentResponse:
    """Return the shared selection document for the current visible content."""
    with selection_lock(session_id):
        session_data = _require_session(store, session_id)
        cache = _require_preview_cache_fields(
            session_data,
            fields={"matched_rgb", "mask_solid"},
        )
        component_cache, _hit = _ensure_visible_region_component_cache(
            session_id,
            store,
            session_data,
            cache,
        )
        return _selection_document_response(
            session_data,
            component_cache,
            _get_visible_region_source_rgb(cache),
        )


@router.get(
    "/editor-commit/{session_id}/{operation_id}",
    response_model=EditorCommitStatusResponse,
)
def get_editor_commit_status(
    session_id: str,
    operation_id: str,
    store: SessionStore = Depends(get_session_store),
) -> EditorCommitStatusResponse:
    """Return the confirmation state for one editor operation.

    返回单个编辑操作的确认状态。不存在的记录保持为 ``unknown``，不能由
    当前内容版本差值推断为失败或成功。
    """
    with replacement_history_lock(session_id):
        session_data = _require_session(store, session_id)
        receipt = get_editor_commit_receipt(session_data, operation_id)
        if receipt is None:
            return EditorCommitStatusResponse(
                status="unknown",
                operation_id=operation_id,
                editor_content_revision=get_editor_content_revision(session_data),
                visible_content_revision=get_visible_region_generation(session_data),
            )
        return EditorCommitStatusResponse(
            status=receipt.get("status", "unknown"),
            operation_id=operation_id,
            operation=receipt.get("operation"),
            editor_content_revision=int(
                receipt.get(
                    "editor_content_revision",
                    get_editor_content_revision(session_data),
                )
            ),
            visible_content_revision=int(
                receipt.get(
                    "visible_content_revision",
                    get_visible_region_generation(session_data),
                )
            ),
            selection_revision=(
                int(receipt["selection_revision"])
                if receipt.get("selection_revision") is not None
                else None
            ),
            result=receipt.get("result"),
        )


@router.post(
    "/selection/mutate",
    response_model=SelectionDocumentResponse,
)
def mutate_editor_selection(
    request: SelectionMutationRequest,
    store: SessionStore = Depends(get_session_store),
) -> SelectionDocumentResponse:
    """Apply one revision-checked tool gesture to the shared selection mask."""
    started_at = time.perf_counter()
    with _replacement_selection_lock(request.session_id):
        session_data = _require_session(store, request.session_id)
        current_revision = get_selection_revision(session_data)
        if current_revision != request.base_selection_revision:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Selection changed while the tool was running "
                    f"(expected {request.base_selection_revision}, current {current_revision})."
                ),
            )
        cache = _require_preview_cache_fields(
            session_data,
            fields={"matched_rgb", "mask_solid"},
        )
        component_cache, cache_hit = _ensure_visible_region_component_cache(
            request.session_id,
            store,
            session_data,
            cache,
        )
        content_revision = int(component_cache["generation"])
        if request.operation != "clear" and request.content_revision != content_revision:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Visible content changed while the selection tool was running "
                    f"(expected {request.content_revision}, current {content_revision})."
                ),
            )
        shape = (int(component_cache["height"]), int(component_cache["width"]))
        current = get_selection_mask(session_data, shape)
        checkpoint = snapshot_selection_state(
            session_data,
            label=f"selection_{request.operation.replace('-', '_')}",
        )
        brush_hits: int | None = None
        try:
            if request.operation == "point-toggle":
                if request.x is None or request.y is None:
                    raise ValueError("Point selection requires x and y.")
                next_mask = mutate_point_toggle(
                    component_cache, current, request.x, request.y
                )
            elif request.operation == "same-color-toggle":
                next_mask = mutate_same_color_toggle(
                    component_cache,
                    current,
                    x=request.x,
                    y=request.y,
                    color_hex=request.color_hex,
                )
            elif request.operation == "color-range-toggle":
                if request.color_tolerance is None:
                    raise ValueError("Colour-range selection requires color_tolerance.")
                next_mask = mutate_color_range_toggle(
                    component_cache,
                    current,
                    x=request.x,
                    y=request.y,
                    color_hex=request.color_hex,
                    tolerance=request.color_tolerance,
                )
            elif request.operation == "brush-add":
                if request.brush_radius is None:
                    raise ValueError("Brush selection requires brush_radius.")
                next_mask, brush_hits = mutate_brush_add(
                    component_cache,
                    current,
                    [(point.x, point.y) for point in request.brush_points],
                    request.brush_radius,
                )
            else:
                next_mask = np.zeros(shape, dtype=bool)
        except (IndexError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if np.array_equal(next_mask, current):
            return _selection_document_response(
                session_data,
                component_cache,
                _get_visible_region_source_rgb(cache),
                brush_hit_component_count=brush_hits,
            )
        persist_selection_mask(
            request.session_id,
            store,
            session_data,
            next_mask,
            content_generation=content_revision,
        )
        push_replacement_checkpoint(
            request.session_id,
            store,
            session_data,
            checkpoint,
        )
        response = _selection_document_response(
            session_data,
            component_cache,
            _get_visible_region_source_rgb(cache),
            brush_hit_component_count=brush_hits,
        )
    log.debug(
        "editor selection mutated",
        extra={
            "event": "converter_selection_mutated",
            "session_id": request.session_id,
            "operation": request.operation,
            "selection_revision": response.selection_revision,
            "selected_component_count": response.selected_component_count,
            "selected_pixel_count": response.selected_pixel_count,
            "component_cache_hit": cache_hit,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
        },
    )
    return response


@router.post("/region-replace", response_model=RegionReplaceResponse)
def region_replace(
    request: RegionReplaceRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RegionReplaceResponse:
    """Replace color only within the previously detected connected region.
    仅替换先前检测到的连通区域内的颜色。

    Fixed-layer edits perform a simple masked assignment. Dynamic material
    edits re-solve the complete automatic target map before committing.
    固定层数编辑只执行简单掩码赋值；动态耗材编辑会在提交前重求解完整自动目标图。

    Args:
        request (RegionReplaceRequest): Region replacement parameters. (区域替换参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        RegionReplaceResponse: Replacement result with preview URL. (替换结果及预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache or no region selected. (无预览缓存或未选中区域)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    operation_id = begin_editor_commit(
        request.session_id,
        store,
        session_data,
        operation_id=request.operation_id,
        operation="region_replace",
    )
    cache_context = _preview_cache_transaction_with_history(
        request.session_id,
        store,
        session_data,
        history_label="region_replace",
        operation_id=operation_id,
        fields={
            "matched_rgb",
            "material_matrix",
            "mask_solid",
            "original_matched_rgb",
            "original_material_matrix",
            "quantized_image",
        },
    )
    cache, history_checkpoint = cache_context.__enter__()
    selection_response: SelectionDocumentResponse | None = None
    editor_content_revision: int | None = None
    cache_published = False

    try:
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")
        if matched_rgb is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing matched_rgb.",
            )

        # Two mask sources are supported. When the Gradient Groups panel
        # routes a "replace inside this banded region only" click, the
        # payload carries ``gradient_group_index`` + ``gradient_region_index``
        # and we rebuild the mask from the cached per-pixel region_id_map.
        # Otherwise we fall back to the legacy click-detected flood-fill mask
        # that ``region_detect`` stashed under ``selected_region_mask``.
        # Rebuilding from region_id_map lets one gradient sub-region be
        # edited without touching other regions that happen to share the
        # same quantised hex — that was the "replace cyan band → whole body
        # turns red" bug we are fixing.
        # 支持两种 mask 来源：渐变区域（优先，使用缓存 region_id_map）和
        # 点击检测区域（legacy）。渐变区域路径让单个子区域换色不会污染
        # 共用同一量化 hex 的其它区域——修复"换一条 cyan 带 → 全身皮肤
        # 变色"的 bug。
        img_h, img_w = matched_rgb.shape[:2]
        region_mask: np.ndarray | None = None
        mask_source: str = "click"
        gradient_group_idx = request.gradient_group_index
        gradient_region_idx = request.gradient_region_index
        if request.selection_revision is not None:
            mask_source = "selection"
            try:
                region_mask = resolve_selection_mask(
                    session_data,
                    (img_h, img_w),
                    request.selection_revision,
                )
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        elif gradient_group_idx is not None:
            region_id_map = session_data.get("gradient_region_id_map")
            if region_id_map is None:
                raise HTTPException(
                    status_code=409,
                    detail=GRADIENT_REGION_METADATA_UNAVAILABLE_DETAIL,
                )
            region_id_arr = np.asarray(region_id_map)
            if region_id_arr.shape != (img_h, img_w):
                raise HTTPException(
                    status_code=409,
                    detail=GRADIENT_REGION_METADATA_STALE_DETAIL,
                )
            if gradient_region_idx is not None:
                # Single region within the group
                mask_source = "gradient_region"
                encoded_id = (
                    int(gradient_group_idx) * REGION_ID_ENCODING_MULTIPLIER
                    + int(gradient_region_idx)
                )
                region_mask = region_id_arr == np.uint32(encoded_id)
                if not np.any(region_mask):
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"No pixels found for gradient group "
                            f"{gradient_group_idx}, region "
                            f"{gradient_region_idx}."
                        ),
                    )
            else:
                # Whole group: mask all pixels whose encoded group matches
                # 整组去海带纹：mask 覆盖该组所有像素
                mask_source = "gradient_group"
                group_of_pixel = region_id_arr // np.uint32(
                    REGION_ID_ENCODING_MULTIPLIER
                )
                region_mask = group_of_pixel == np.uint32(
                    int(gradient_group_idx)
                )
                if not np.any(region_mask):
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"No pixels found for gradient group "
                            f"{gradient_group_idx}."
                        ),
                    )
        else:
            region_mask = _get_region_mask_items_for_ids(
                session_data,
                [str(session_data.get("selected_region_id") or "")],
            )
            region_mask = region_mask[0][1] if region_mask else None
            if region_mask is None:
                raise HTTPException(
                    status_code=409,
                    detail=REGION_SELECTION_REQUIRED_DETAIL,
                )

        # Parse replacement hex to RGB tuple
        replacement_rgb = np.array(
            ColorReplacementManager._hex_to_color(request.replacement_color),
            dtype=np.uint8,
        )

        # Apply region replacement: only modify pixels within the mask
        replaced_rgb: np.ndarray = matched_rgb.copy()
        replaced_rgb[region_mask] = replacement_rgb

        import time as _time
        _region_pixels = int(region_mask.sum())
        _diff_before_sync = int(np.any(matched_rgb != replaced_rgb, axis=-1).sum())
        log.debug(
            "region-replace diag: before sync",
            extra={
                "event": "converter_region_replace_diag_pre",
                "replacement_color": request.replacement_color,
                "material_source": session_data.get("material_source"),
                "region_mask_pixels": _region_pixels,
                "diff_pixel_count": _diff_before_sync,
                "has_material_matrix": cache.get("material_matrix") is not None,
                "has_mask_solid": cache.get("mask_solid") is not None,
                "matched_rgb_shape": list(matched_rgb.shape),
            },
        )

        # Update matched_rgb in session cache
        cache["matched_rgb"] = replaced_rgb
        _t_sync = _time.perf_counter()
        _sync_material_matrix_after_rgb_change(
            session_data, cache, matched_rgb, replaced_rgb
        )
        _sync_ms = (_time.perf_counter() - _t_sync) * 1000

        _diff_after_sync = int(np.any(matched_rgb != replaced_rgb, axis=-1).sum())
        log.debug(
            "region-replace diag: after sync",
            extra={
                "event": "converter_region_replace_diag_post",
                "sync_ms": round(_sync_ms, 1),
                "diff_pixel_count_after_sync": _diff_after_sync,
                "replaced_rgb_sample": replaced_rgb[region_mask][0].tolist() if _region_pixels > 0 else None,
                "original_rgb_sample": matched_rgb[region_mask][0].tolist() if _region_pixels > 0 else None,
            },
        )
        # Generate styled preview PNG (with bed grid and transparency)
        _t_png = _time.perf_counter()
        preview_bytes: bytes = _render_styled_preview_bytes(replaced_rgb, cache)
        preview_id: str = registry.register_bytes(request.session_id, preview_bytes, "preview_region_replaced.png")
        _png_ms = (_time.perf_counter() - _t_png) * 1000
        persisted_cache = cache.commit(
            _dirty_array_fields(
                cache,
                "matched_rgb",
                "material_matrix",
                "quantized_image",
                "preview_rgba",
            ),
            metadata_fields=_REPLACEMENT_CACHE_METADATA_FIELDS,
        )
        cache_published = True
        # Content history intentionally preserves the execution-time selection.
        # Refresh its content-generation stamp after the visible-region cache moves
        # to a new generation, so the user can immediately reuse the same mask.
        _invalidate_and_prewarm_visible_region_cache(request.session_id, store, session_data, cache)
        if mask_source == "selection":
            # Serialise with selection gestures: persist_selection_mask writes
            # the revision + mask non-atomically, so without the lock a concurrent
            # gesture could be overwritten by this older mask and the revision
            # regressed (breaking monotonicity and silently reselecting old pixels).
            # 与选区手势串行化：persist 对 revision/mask 非原子写入，不持锁时
            # 并发手势可能被这份更旧的 mask 覆盖且 revision 回退。
            with selection_lock(request.session_id):
                persist_selection_mask(
                    request.session_id,
                    store,
                    session_data,
                    region_mask,
                content_generation=get_visible_region_generation(session_data),
                revision=get_selection_revision(session_data),
            )
        _bump_region_replacement_count(request.session_id, store, session_data, 1)
        history_flags = _push_history_checkpoint(
            request.session_id,
            store,
            session_data,
            history_checkpoint,
        )
        editor_content_revision = advance_editor_content_revision(
            request.session_id,
            store,
            session_data,
        )
        # Rebuild the response after advancing the unified editor revision so
        # the selection document and receipt describe the same committed state.
        selection_response = _selection_after_content_commit(
            request.session_id,
            store,
            session_data,
            cache,
        )
        publish_editor_commit(
            request.session_id,
            store,
            session_data,
            operation_id=operation_id,
            editor_content_revision=editor_content_revision,
            selection_revision=get_selection_revision(session_data),
            result=_editor_commit_result(
                session_data,
                cache=cache,
                preview_url=f"/api/files/{preview_id}",
            ),
        )
        # Async GLB rebuild: /region-replace previously spent ~77% of its
        # wall time here; now the HTTP response returns in ~10s (sync +
        # PNG) and the GLB arrives via /glb-status polling afterwards.
        # 异步 GLB 重建：以往 /region-replace 77% 的耗时在这里；现在只
        # 等 sync + PNG 即可响应，GLB 通过 glb-status 轮询取回。
        glb_url: str | None = _schedule_or_run_overridden_glb_build(
            request.session_id,
            store,
            registry,
            persisted_cache,
            "preview_region_replaced.glb",
        )

        # Per-step timing so the frontend-perceived latency can be attributed
        # to mask building / material sync / PNG render. The heavy GLB step
        # no longer blocks this response — see converter_glb_completed in
        # async_glb.py for its separate timing log.
        # 每步耗时日志；GLB 现已脱离本响应，改为 async_glb 中单独打点。
        log.info(
            "region-replace timing",
            extra={
                "event": "converter_region_replace_timing",
                "sync_ms": round(_sync_ms, 1),
                "png_ms": round(_png_ms, 1),
                "mask_source": mask_source,
                "region_mask_pixels": _region_pixels,
                "matched_rgb_shape": list(matched_rgb.shape),
            },
        )

        # Extract updated color_contours from cache
        contours_data: dict | None = cache.get("color_contours")

        # Only clear the one-shot click-detected region mask, and only when
        # that was the actual source we consumed. The cached
        # ``gradient_region_id_map`` is derived reusable metadata and must
        # survive so the user can replace several banded regions in a row
        # without re-running ``/preview`` between each one.
        # 仅在 click 模式下清理一次性 mask；gradient region 路径复用缓存
        # 的 region_id_map，保留以便连续替换多个区域。
        if mask_source == "click":
            store.put(request.session_id, "selected_region_mask", None)
            store.put(request.session_id, "selected_region_id", None)

    except HTTPException as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        raise
    except PreviewCacheRevisionConflict as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _raise_replace_cache_conflict(
            e,
            session_id=request.session_id,
            operation="region_replace",
        )
    except REPLACE_HANDLED_ERRORS as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _handle_core_error(e, "Region replacement")
    finally:
        cache_context.__exit__(*sys.exc_info())

    return RegionReplaceResponse(
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=glb_url,
        color_contours=contours_data,
        message="Region color replaced successfully",
        selection=selection_response,
        **dynamic_material_result_from_cache(cache).model_dump(
            exclude={"operation_id", "editor_content_revision"}
        ),
        **history_flags,
        operation_id=operation_id,
        editor_content_revision=editor_content_revision,
    )


# ---------------------------------------------------------------------------
# Per-region secondary re-quantisation (material-archive mode only)
# ---------------------------------------------------------------------------


@router.post("/region-requantize", response_model=RegionReplaceResponse)
def region_requantize(
    request: RegionRequantizeRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RegionReplaceResponse:
    """Per-region secondary re-quantisation for the gradient-groups panel.
    渐变分组面板的区域级二次量化接口。

    For every ``(gradient_group_index, gradient_region_index)`` in
    ``request.targets``, the endpoint extracts the ORIGINAL source pixels
    inside the region's mask, runs a local K-Means with the user-chosen
    ``local_quantize_colors`` budget, and re-matches those locally
    quantised colours through the same :class:`MaterialSolverCache` the
    preview pipeline used. The resulting per-pixel material colours
    overwrite those regions in ``matched_rgb`` while leaving the rest of
    the canvas untouched.

    对每个选中的渐变 region，取原图像素独立做一次 K-Means 量化，再经
    管线同款材料求解器重匹配，只写回这些区域的 ``matched_rgb``。其它
    像素保持不变。

    Material-archive mode only — LUT mode has a completely different
    matching path that does not use :class:`MaterialSolverCache`. Callers
    get HTTP 409 if they attempt this on an LUT session.
    仅支持耗材档案模式；LUT 模式走另一套匹配逻辑，此端点不适用。

    Raises:
        HTTPException(404): Session not found.
        HTTPException(409): Preview cache missing, ``material_source`` is
            not ``"material_archive"``, ``gradient_region_id_map`` is
            absent/stale, or the material solver cache cannot be loaded.
        HTTPException(422): Validation failure on ``local_quantize_colors``
            or ``targets`` (handled by Pydantic before reaching here).
        HTTPException(500): Unexpected processing error.
    """
    import time as _time
    from PIL import Image

    session_data = _require_session(store, request.session_id)
    operation_id = begin_editor_commit(
        request.session_id,
        store,
        session_data,
        operation_id=request.operation_id,
        operation="region_requantize",
    )
    cache_context = _preview_cache_transaction_with_history(
        request.session_id,
        store,
        session_data,
        history_label="region_requantize",
        operation_id=operation_id,
        fields={
            "matched_rgb",
            "material_matrix",
            "mask_solid",
            "quantized_image",
        },
    )
    cache, history_checkpoint = cache_context.__enter__()
    selection_response: SelectionDocumentResponse | None = None
    editor_content_revision: int | None = None
    cache_published = False

    try:
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")
        if matched_rgb is None:
            raise HTTPException(
                status_code=409,
                detail=MATCHED_COLORS_UNAVAILABLE_DETAIL,
            )

        material_source = str(session_data.get("material_source") or "lut")
        if material_source != "material_archive":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Region re-quantisation is only available in material-archive "
                    "mode; current material_source is "
                    f"'{material_source}'."
                ),
            )

        region_id_map = session_data.get("gradient_region_id_map")
        if region_id_map is None:
            raise HTTPException(
                status_code=409,
                detail=GRADIENT_REGION_METADATA_UNAVAILABLE_DETAIL,
            )
        region_id_arr = np.asarray(region_id_map)
        img_h, img_w = matched_rgb.shape[:2]
        if region_id_arr.shape != (img_h, img_w):
            raise HTTPException(
                status_code=409,
                detail=GRADIENT_REGION_METADATA_STALE_DETAIL,
            )

        # Materials list → MaterialParams → solver cache.
        selected_materials = session_data.get("selected_materials") or []
        if not isinstance(selected_materials, list) or not selected_materials:
            raise HTTPException(
                status_code=409,
                detail="Session has no selected materials for material-archive mode.",
            )
        try:
            materials = load_multiple_materials(list(selected_materials))
        except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
            _raise_region_requantize_error(
                exc,
                status_code=409,
                detail=REGION_REQUANTIZE_MATERIALS_UNAVAILABLE_DETAIL,
                session_id=request.session_id,
                stage="load_materials",
            )

        layer_count = int(
            session_data.get("material_layer_count")
            or cache.get("color_layers")
            or 10
        )
        layer_height_mm = float(
            session_data.get("material_layer_height_mm")
            or cache.get("layer_height_mm")
            or session_data.get("layer_height_mm")
            or 0.08
        )
        substrate = str(
            cache.get("material_substrate")
            or session_data.get("material_substrate")
            or "white"
        )
        grid_resolution = int(
            session_data.get("material_grid_resolution")
            or DEFAULT_GRID_RESOLUTION
        )
        solver_cache, _grid = load_material_solver_cache_with_fallback(
            materials=materials,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            grid_resolution=grid_resolution,
        )
        if solver_cache is None:
            raise HTTPException(
                status_code=409,
                detail=MATERIAL_SOLVER_CACHE_UNAVAILABLE_DETAIL,
            )

        # Load the ORIGINAL source image and resize to preview resolution so
        # the region_mask indexes the right pixels. The preview pipeline
        # performs the same resize; resampling with LANCZOS is acceptable
        # here because k-means is robust to sub-pixel smoothing.
        # 原图加载并缩放至预览分辨率，mask 索引才能对齐。
        image_path = session_data.get("image_path")
        if not image_path or not os.path.exists(image_path):
            raise HTTPException(
                status_code=409,
                detail="Session has no original image_path on disk; re-upload.",
            )
        try:
            original_pil = Image.open(image_path).convert("RGB")
            if original_pil.size != (img_w, img_h):
                original_pil = original_pil.resize(
                    (img_w, img_h), Image.LANCZOS
                )
            original_source_rgb = np.asarray(original_pil, dtype=np.uint8)
        except (OSError, ValueError) as exc:
            _raise_region_requantize_error(
                exc,
                status_code=500,
                detail=REGION_REQUANTIZE_SOURCE_IMAGE_UNAVAILABLE_DETAIL,
                session_id=request.session_id,
                stage="load_source_image",
            )

        # Convert Pydantic targets to plain tuples for the core function.
        target_pairs = [
            (t.gradient_group_index, t.gradient_region_index)
            for t in request.targets
        ]

        # Group-level fallback for targets whose exact (group, region) mask
        # is empty in region_id_map. This mirrors the analogous fallback
        # in /color-highlight: the gradient analyser keeps unmappable
        # regions in ``regions[]`` (their CC label could not be resolved),
        # so the UI surfaces working buttons for them; without this
        # widening, ``requantize_gradient_regions`` silently skips them
        # and the user sees "click did nothing" because matched_rgb
        # never changes. We stamp each unmappable target's encoding
        # across its parent group's pixels in a *working copy* of
        # region_id_map so the core function picks them up. The on-disk
        # session map is left untouched.
        # 整组回退：当 target 的精确 region mask 为空但所在 group 有像素
        # 时，在工作副本里把整组像素盖章成该 target；解决用户点了一个
        # 分析器静默跳过的 region 时"完全没变化"的失联感。
        working_region_id_arr = region_id_arr.astype(np.uint32, copy=False)
        group_of_pixel = working_region_id_arr // np.uint32(
            REGION_ID_ENCODING_MULTIPLIER
        )
        fallback_targets: list[tuple[int, int]] = []
        already_widened_groups: set[int] = set()
        for g, r in target_pairs:
            g_int = int(g)
            r_int = int(r)
            encoded = np.uint32(
                g_int * REGION_ID_ENCODING_MULTIPLIER + r_int
            )
            if np.any(working_region_id_arr == encoded):
                continue
            group_mask = group_of_pixel == np.uint32(g_int)
            if not np.any(group_mask):
                continue
            # Multiple unmappable targets inside the same group would
            # otherwise overwrite each other; collapse to the first
            # fallback target seen so semantics stay deterministic.
            # 同一 group 内多个不可定位 target 时只保留首个回退编码，
            # 避免互相覆盖造成结果依赖循环顺序。
            if g_int in already_widened_groups:
                continue
            # Lazy materialise an actual copy only when we are about to
            # mutate it.
            if working_region_id_arr is region_id_arr:
                working_region_id_arr = region_id_arr.astype(
                    np.uint32, copy=True
                )
                group_of_pixel = working_region_id_arr // np.uint32(
                    REGION_ID_ENCODING_MULTIPLIER
                )
                group_mask = group_of_pixel == np.uint32(g_int)
            working_region_id_arr[group_mask] = encoded
            fallback_targets.append((g_int, r_int))
            already_widened_groups.add(g_int)
        if fallback_targets:
            log.warning(
                "region_requantize_unmapped_target_group_fallback",
                extra={
                    "event": "region_requantize_unmapped_target_group_fallback",
                    "error_type": "GradientRegionMaskMissing",
                    "error_message": (
                        "One or more target region masks were empty; "
                        "widening them to their parent group mask."
                    ),
                    "fallback_action": "widen_to_group_mask",
                    "fallback_targets": fallback_targets,
                    "total_targets": len(target_pairs),
                },
            )

        _t_core = _time.perf_counter()
        try:
            new_matched_rgb, rewritten_px = requantize_gradient_regions(
                matched_rgb=np.asarray(matched_rgb, dtype=np.uint8),
                original_source_rgb=original_source_rgb,
                region_id_map=working_region_id_arr,
                targets=target_pairs,
                materials=materials,
                material_solver_cache=solver_cache,
                local_quantize_colors=request.local_quantize_colors,
            )
        except (ValueError, TypeError) as exc:
            _raise_region_requantize_error(
                exc,
                status_code=409,
                detail=REGION_REQUANTIZE_REQUEST_INVALID_DETAIL,
                session_id=request.session_id,
                stage="requantize_core",
            )
        _core_ms = (_time.perf_counter() - _t_core) * 1000

        # Sync material matrix for the changed pixels, then commit to cache.
        cache["matched_rgb"] = new_matched_rgb
        _t_sync = _time.perf_counter()
        _sync_material_matrix_after_rgb_change(
            session_data,
            cache,
            np.asarray(matched_rgb),
            new_matched_rgb,
        )
        _sync_ms = (_time.perf_counter() - _t_sync) * 1000

        # Refresh the palette derived from matched_rgb so downstream
        # consumers (``/layer-images`` iterates over it; Palette Panel
        # surfaces it in the UI) see every new material colour the local
        # k-means produced. Without this the palette still reflects the
        # pre-quantise colours and ``/layer-images`` would only generate
        # slices for the old set.
        # 重算从 matched_rgb 派生的调色板，保证 /layer-images 与面板
        # 能看到二次量化新增的材料色；不补会导致分层图缺色。
        _t_palette = _time.perf_counter()
        cache["color_palette"] = extract_color_palette(cache)
        _palette_ms = (_time.perf_counter() - _t_palette) * 1000

        # The default segmented-GLB merge cap is 64 unique colours. Local
        # re-quantisation deliberately introduces low-frequency colours
        # inside small regions; if those exceed the cap they get merged
        # into the dominant palette, which makes the 3D preview look
        # identical to the pre-quantise state even though the 2D PNG
        # already shows the new colours. Track the actual unique-colour
        # count in the (post-sync) matched_rgb solid mask and bump the
        # GLB cap so every new colour survives into the segmented mesh.
        # 默认 GLB 合并上限 64 会把二次量化引入的低频新色合并掉，导致 3D
        # 看起来没变化。这里按 sync 之后真实的唯一色数把上限抬高，确保
        # 二次量化后 3D 预览能显现 2D 同步可见的新色。
        mask_solid_arr = cache.get("mask_solid")
        if mask_solid_arr is not None:
            mask_bool = np.asarray(mask_solid_arr, dtype=bool)
            solid_pixels = new_matched_rgb[mask_bool] if mask_bool.shape == new_matched_rgb.shape[:2] else new_matched_rgb.reshape(-1, 3)
        else:
            solid_pixels = new_matched_rgb.reshape(-1, 3)
        unique_color_count = int(np.unique(solid_pixels.reshape(-1, 3), axis=0).shape[0])
        previous_cap = int(cache.get("glb_max_meshes") or 0)
        new_cap = max(previous_cap, unique_color_count)
        if new_cap > previous_cap:
            cache["glb_max_meshes"] = new_cap

        # Re-run gradient-group analysis so the Gradient Groups panel and
        # the cached ``gradient_region_id_map`` both reflect the new
        # ``matched_rgb``. Without this the panel still shows the pre-
        # quantize groups and subsequent /region-requantize or /region-
        # replace calls would address stale region ids. Best-effort: a
        # failure here is logged inside the helper and we ship an empty
        # ``gradient_groups`` so the client can keep going.
        # 二次量化后 matched_rgb 分布变了，必须重跑 gradient-group 分析
        # 让面板与 region_id_map 同步刷新，否则面板显示旧分组，后续再量化
        # 会按旧 region 定位，造成点不中的错觉。
        _t_groups = _time.perf_counter()
        refreshed_groups = recompute_gradient_groups_into_session(
            cache, request.session_id, store
        )
        _groups_ms = (_time.perf_counter() - _t_groups) * 1000

        # Re-render styled preview PNG and schedule GLB rebuild.
        _t_png = _time.perf_counter()
        preview_bytes: bytes = _render_styled_preview_bytes(new_matched_rgb, cache)
        preview_id: str = registry.register_bytes(
            request.session_id,
            preview_bytes,
            "preview_region_requantized.png",
        )
        _png_ms = (_time.perf_counter() - _t_png) * 1000
        persisted_cache = cache.commit(
            _dirty_array_fields(
                cache,
                "matched_rgb",
                "material_matrix",
                "quantized_image",
                "preview_rgba",
            ),
            metadata_fields={
                *_REPLACEMENT_CACHE_METADATA_FIELDS,
                "glb_max_meshes",
            },
        )
        cache_published = True
        _invalidate_and_prewarm_visible_region_cache(request.session_id, store, session_data, cache)
        _bump_region_replacement_count(request.session_id, store, session_data, len(request.targets))
        history_flags = _push_history_checkpoint(
            request.session_id,
            store,
            session_data,
            history_checkpoint,
        )
        editor_content_revision = advance_editor_content_revision(
            request.session_id,
            store,
            session_data,
        )
        selection_response = _selection_after_content_commit(
            request.session_id,
            store,
            session_data,
            cache,
        )
        publish_editor_commit(
            request.session_id,
            store,
            session_data,
            operation_id=operation_id,
            editor_content_revision=editor_content_revision,
            selection_revision=get_selection_revision(session_data),
            result=_editor_commit_result(
                session_data,
                cache=cache,
                preview_url=f"/api/files/{preview_id}",
            ),
        )
        _schedule_glb_build_best_effort(
            request.session_id,
            store,
            registry,
            persisted_cache,
        )

        log.info(
            "region-requantize done",
            extra={
                "event": "converter_region_requantize_done",
                "session_id": request.session_id,
                "target_lut": str(session_data.get("lut_name") or "__material_archive__"),
                "region_pixel_count": int(rewritten_px),
                "output_color_count": unique_color_count,
                "target_count": len(target_pairs),
                "local_quantize_colors": int(request.local_quantize_colors),
                "rewritten_pixels": int(rewritten_px),
                "unique_color_count_after": unique_color_count,
                "glb_max_meshes_previous": previous_cap,
                "glb_max_meshes_new": new_cap,
                "core_ms": round(_core_ms, 1),
                "sync_ms": round(_sync_ms, 1),
                "palette_ms": round(_palette_ms, 1),
                "palette_entry_count": len(cache.get("color_palette") or []),
                "groups_ms": round(_groups_ms, 1),
                "png_ms": round(_png_ms, 1),
                "refreshed_group_count": (
                    len(refreshed_groups) if refreshed_groups is not None else None
                ),
                "matched_rgb_shape": list(matched_rgb.shape),
            },
        )

        contours_data: dict | None = cache.get("color_contours")
    except HTTPException as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        raise
    except PreviewCacheRevisionConflict as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        _raise_region_requantize_error(
            exc,
            status_code=409,
            detail=REGION_REQUANTIZE_CACHE_CONFLICT_DETAIL,
            session_id=request.session_id,
            stage="preview_cache_commit",
        )
    except REPLACE_HANDLED_ERRORS as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        _handle_core_error(exc, "Region re-quantisation")
    finally:
        cache_context.__exit__(*sys.exc_info())

    return RegionReplaceResponse(
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=None,
        color_contours=contours_data,
        message=(
            f"Re-quantised {len(request.targets)} region(s) with "
            f"{request.local_quantize_colors} colours; rewrote {rewritten_px} pixels."
        ),
        gradient_groups=refreshed_groups,
        **dynamic_material_result_from_cache(cache).model_dump(
            exclude={"operation_id", "editor_content_revision"}
        ),
        **history_flags,
        operation_id=operation_id,
        editor_content_revision=editor_content_revision,
        selection=selection_response,
    )


# ---------------------------------------------------------------------------
# Batch endpoints
# ---------------------------------------------------------------------------
#
# Why these exist: the legacy per-colour / per-region endpoints regenerate
# the styled preview PNG, the segmented GLB, and run the material-matrix
# sync on *every* request. When the frontend loops over N replacements
# (multi-colour swap, colour-remap preview rebuild, multi-region click,
# whole-group gradient flatten) that's N * (GLB + PNG + sync) — and GLB
# is expensive. These batch endpoints apply all N changes cumulatively to
# the cached ``matched_rgb``, then do PNG + GLB + sync exactly once at
# the end. Semantically equivalent to the loop, but O(N) faster on the
# heavy steps.
# 批量端点存在的原因：老的单色/单区域端点每次都会重渲染 PNG、重建 GLB、
# 做一次物料矩阵 sync。前端循环 N 次就等于 N × (GLB + PNG + sync)，GLB
# 又最贵。这里把 N 次改动累积到 matched_rgb，最后统一做一次 PNG+GLB+sync。
# 语义上等价于循环，重活只做一次。


def _build_mask_for_region_batch_item(
    session_id: str,
    store: SessionStore,
    session_data: dict,
    item: RegionReplaceBatchItem,
    img_h: int,
    img_w: int,
    cache: dict,
) -> tuple[np.ndarray, str]:
    """Build a boolean mask for one batch region-replace item.
    为单条批量 region-replace 条目构建 mask。

    Mirrors :func:`region_replace` mask-selection logic: gradient group/region
    indices take precedence (re-derived from the cached region_id_map); else
    ``click_x`` / ``click_y`` resolve through the cached current-visible
    connected-component label map.
    与 :func:`region_replace` 的 mask 选择逻辑一致：优先渐变索引（现场从
    缓存的 region_id_map 重建），否则使用 click_x/click_y 查询当前可见色块
    分块缓存。

    Raises:
        HTTPException(400/404/409): Same error codes and messages as the
            single-item /region-replace endpoint.
    """
    gradient_group_idx = item.gradient_group_index
    gradient_region_idx = item.gradient_region_index

    if gradient_group_idx is not None:
        region_id_map = session_data.get("gradient_region_id_map")
        if region_id_map is None:
            raise HTTPException(
                status_code=409,
                detail=GRADIENT_REGION_METADATA_UNAVAILABLE_DETAIL,
            )
        region_id_arr = np.asarray(region_id_map)
        if region_id_arr.shape != (img_h, img_w):
            raise HTTPException(
                status_code=409,
                detail=GRADIENT_REGION_METADATA_STALE_DETAIL,
            )
        if gradient_region_idx is not None:
            encoded_id = (
                int(gradient_group_idx) * REGION_ID_ENCODING_MULTIPLIER
                + int(gradient_region_idx)
            )
            mask = region_id_arr == np.uint32(encoded_id)
            if not np.any(mask):
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"No pixels found for gradient group "
                        f"{gradient_group_idx}, region "
                        f"{gradient_region_idx}."
                    ),
                )
            return mask, "gradient_region"
        group_of_pixel = region_id_arr // np.uint32(REGION_ID_ENCODING_MULTIPLIER)
        mask = group_of_pixel == np.uint32(int(gradient_group_idx))
        if not np.any(mask):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No pixels found for gradient group {gradient_group_idx}."
                ),
            )
        return mask, "gradient_group"

    # Click-detected path: resolve (click_x, click_y) through the same cached
    # visible-component label map as /region-detect.
    if item.click_x is None or item.click_y is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Each batch item must supply either gradient_group_index "
                "(+ optional gradient_region_index) or click_x + click_y."
            ),
        )

    x, y = int(item.click_x), int(item.click_y)
    if not (0 <= x < img_w and 0 <= y < img_h):
        raise HTTPException(
            status_code=400,
            detail=f"Coordinates ({x}, {y}) out of bounds for image {img_w}x{img_h}.",
        )
    component_cache, _component_cache_hit = _ensure_visible_region_component_cache(
        session_id,
        store,
        session_data,
        cache,
    )
    try:
        component_label, _component = get_component_at(component_cache, x, y)
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Click ({x}, {y}) fell on background.",
        ) from exc
    mask = component_mask(component_cache, component_label)
    if not np.any(mask):
        raise HTTPException(
            status_code=400,
            detail=f"No connected region at ({x}, {y}).",
        )
    return mask, "click"


@router.post("/replace-colors-batch", response_model=ColorReplaceResponse)
def replace_colors_batch(
    request: ColorReplaceBatchRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ColorReplaceResponse:
    """Batch-replace multiple colours in one round-trip.
    一次调用批量替换多个颜色。

    Semantically equivalent to calling /replace-color for each pair in
    ``request.replacements`` in order, but the heavy per-call work (styled
    PNG render, segmented GLB rebuild, material-matrix sync) runs exactly
    once at the end, making batch colour swaps O(N) cheaper on those
    dominant cost centres.
    语义等价于顺序调用 N 次 /replace-color，但重活（PNG 渲染、GLB 重建、
    物料矩阵 sync）只跑 1 次，批量颜色替换 N× 提速。

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache. (无预览缓存)
    """
    session_data = _require_session(store, request.session_id)
    operation_id = begin_editor_commit(
        request.session_id,
        store,
        session_data,
        operation_id=request.operation_id,
        operation="replace_colors_batch",
    )
    selection_response: SelectionDocumentResponse | None = None
    editor_content_revision: int | None = None
    cache_context = _preview_cache_transaction_with_history(
        request.session_id,
        store,
        session_data,
        history_label="replace_colors_batch",
        operation_id=operation_id,
        fields={
            "matched_rgb",
            "material_matrix",
            "mask_solid",
            "quantized_image",
        },
    )
    cache, history_checkpoint = cache_context.__enter__()
    cache_published = False

    try:
        matched_rgb: np.ndarray = cache["matched_rgb"]
        previous_rgb = matched_rgb.copy()
        material_matrix = cache.get("material_matrix")
        current_regions = list(session_data.get("replacement_regions", []))
        base_rgb = session_data.get("global_replacement_base_matched_rgb")
        base_material_matrix = session_data.get(
            "global_replacement_base_material_matrix"
        )
        if base_rgb is not None:
            source_rgb = np.asarray(base_rgb).copy()
            source_material_matrix = (
                np.asarray(base_material_matrix).copy()
                if base_material_matrix is not None
                else None
            )
        elif current_regions:
            original_rgb = session_data.get("original_matched_rgb")
            if original_rgb is None:
                original_rgb = cache.get("original_matched_rgb")
            original_material_matrix = session_data.get("original_material_matrix")
            if original_material_matrix is None:
                original_material_matrix = cache.get("original_material_matrix")
            source_rgb = (
                np.asarray(original_rgb).copy()
                if original_rgb is not None
                else matched_rgb.copy()
            )
            source_material_matrix = (
                np.asarray(original_material_matrix).copy()
                if original_material_matrix is not None
                else (
                    np.asarray(material_matrix).copy()
                    if material_matrix is not None
                    else None
                )
            )
        else:
            source_rgb = matched_rgb.copy()
            source_material_matrix = (
                np.asarray(material_matrix).copy()
                if material_matrix is not None
                else None
            )
        if source_rgb.shape != matched_rgb.shape:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Global replacement base shape does not match matched_rgb; "
                    "re-run preview before replacing colours."
                ),
            )
        if (
            source_material_matrix is not None
            and material_matrix is not None
            and source_material_matrix.shape != np.asarray(material_matrix).shape
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Global replacement material base shape does not match "
                    "material_matrix; re-run preview before replacing colours."
                ),
            )
        if request.replacements and not current_regions:
            store.put(
                request.session_id,
                "global_replacement_base_matched_rgb",
                source_rgb.copy(),
            )
            if source_material_matrix is not None:
                store.put(
                    request.session_id,
                    "global_replacement_base_material_matrix",
                    source_material_matrix.copy(),
                )

        # Rebuild from the pristine source using exactly the replacement
        # pairs supplied by the client. This makes undo/redo deterministic:
        # removing one mapping from the frontend history no longer leaves its
        # pixels stuck in the already-mutated backend cache.
        # 按前端当前完整映射从原始 matched_rgb 重放。这样撤销/重做时删掉
        # 一条映射不会在已变异的后端缓存里留下旧色。
        manager = ColorReplacementManager()
        for pair in request.replacements:
            manager.add_replacement(
                ColorReplacementManager._hex_to_color(pair.selected_color),
                ColorReplacementManager._hex_to_color(pair.replacement_color),
            )

        replaced_rgb = manager.apply_to_image(source_rgb)
        diff_pixel_count = int(np.any(previous_rgb != replaced_rgb, axis=-1).sum())

        log.debug(
            "replace-colors-batch diag",
            extra={
                "event": "converter_replace_colors_batch_diag",
                "pair_count": len(request.replacements),
                "diff_pixel_count": diff_pixel_count,
                "material_source": session_data.get("material_source"),
            },
        )

        cache["matched_rgb"] = replaced_rgb
        if source_material_matrix is not None:
            cache["material_matrix"] = source_material_matrix.copy()
        _sync_material_matrix_after_rgb_change(
            session_data, cache, source_rgb, replaced_rgb
        )

        # One PNG render + one GLB rebuild for the whole batch.
        # 整个批次只渲染一次 PNG、重建一次 GLB。
        preview_bytes = _render_styled_preview_bytes(replaced_rgb, cache)
        preview_id = registry.register_bytes(
            request.session_id, preview_bytes, "preview_batch_replaced.png"
        )
        persisted_cache = cache.commit(
            _dirty_array_fields(
                cache,
                "matched_rgb",
                "material_matrix",
                "quantized_image",
                "preview_rgba",
            ),
            metadata_fields=_REPLACEMENT_CACHE_METADATA_FIELDS,
        )
        cache_published = True
        _invalidate_and_prewarm_visible_region_cache(request.session_id, store, session_data, cache)
        history_flags = _push_history_checkpoint(
            request.session_id,
            store,
            session_data,
            history_checkpoint,
        )

        current_regions = [
            {
                "selected_color": pair.selected_color,
                "replacement_color": pair.replacement_color,
            }
            for pair in request.replacements
        ]
        store.put(request.session_id, "replacement_regions", current_regions)
        if not current_regions:
            store.put(request.session_id, "global_replacement_base_matched_rgb", None)
            store.put(
                request.session_id,
                "global_replacement_base_material_matrix",
                None,
            )
        editor_content_revision = advance_editor_content_revision(
            request.session_id,
            store,
            session_data,
        )
        selection_response = _selection_after_content_commit(
            request.session_id,
            store,
            session_data,
            cache,
        )
        publish_editor_commit(
            request.session_id,
            store,
            session_data,
            operation_id=operation_id,
            editor_content_revision=editor_content_revision,
            selection_revision=get_selection_revision(session_data),
            result=_editor_commit_result(
                session_data,
                cache=cache,
                preview_url=f"/api/files/{preview_id}",
            ),
        )

        # Async GLB rebuild starts only after cache, session fields, history,
        # selection binding, and the editor receipt have converged. GLB is a
        # derived artifact and must never observe the half-committed batch.
        # 批量颜色替换的 GLB 只在完整提交收敛后异步重建。
        _schedule_glb_build_best_effort(
            request.session_id,
            store,
            registry,
            persisted_cache,
        )
        glb_url: str | None = None

    except HTTPException as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        raise
    except PreviewCacheRevisionConflict as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _raise_replace_cache_conflict(
            e,
            session_id=request.session_id,
            operation="replace_colors_batch",
        )
    except REPLACE_HANDLED_ERRORS as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _handle_core_error(e, "Batch color replacement")
    finally:
        cache_context.__exit__(*sys.exc_info())

    log.info(
        "replace-colors-batch completed",
        extra={
            "event": "converter_replace_colors_batch_done",
            "session_id": request.session_id,
            "pair_count": len(request.replacements),
            "diff_pixel_count": diff_pixel_count,
            "replacement_count": len(current_regions),
        },
    )
    return ColorReplaceResponse(
        status="ok",
        message=f"Replaced {len(request.replacements)} colors in batch",
        preview_url=f"/api/files/{preview_id}",
        preview_3d_url=glb_url,
        replacement_count=len(request.replacements),
        **dynamic_material_result_from_cache(cache).model_dump(
            exclude={"operation_id", "editor_content_revision"}
        ),
        **history_flags,
        operation_id=operation_id,
        editor_content_revision=editor_content_revision,
        selection=selection_response,
    )


@router.post("/region-replace-batch", response_model=RegionReplaceResponse)
def region_replace_batch(
    request: RegionReplaceBatchRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RegionReplaceResponse:
    """Batch region-replacement: multiple masks + target colours in one call.
    批量区域替换：一次调用里处理多个区域（混合 click 和 gradient 来源）。

    Each item independently resolves its mask (gradient indices or click
    coordinates), then the target colour is applied on top of the running
    ``matched_rgb``. Material-matrix sync, styled PNG render and segmented
    GLB rebuild all run exactly once at the end — the expensive steps are
    amortised across the whole batch.
    每条 item 独立解析 mask（渐变索引或点击坐标），目标色逐条累加应用到
    ``matched_rgb``。物料矩阵 sync、PNG、GLB 各只跑 1 次，重活在整个批次
    内摊薄。
    """
    session_data = _require_session(store, request.session_id)
    operation_id = begin_editor_commit(
        request.session_id,
        store,
        session_data,
        operation_id=request.operation_id,
        operation="region_replace_batch",
    )
    cache_context = _preview_cache_transaction_with_history(
        request.session_id,
        store,
        session_data,
        history_label="region_replace_batch",
        operation_id=operation_id,
        fields={
            "matched_rgb",
            "material_matrix",
            "mask_solid",
            "quantized_image",
        },
    )
    cache, history_checkpoint = cache_context.__enter__()
    editor_content_revision: int | None = None
    cache_published = False

    try:
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")
        if matched_rgb is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing matched_rgb.",
            )

        img_h, img_w = matched_rgb.shape[:2]
        previous_rgb = matched_rgb.copy()
        working_rgb = matched_rgb.copy()

        any_click_mask_used = False
        for item in request.items:
            mask, mask_source = _build_mask_for_region_batch_item(
                request.session_id,
                store,
                session_data,
                item,
                img_h,
                img_w,
                cache,
            )
            replacement_rgb = np.array(
                ColorReplacementManager._hex_to_color(item.replacement_color),
                dtype=np.uint8,
            )
            working_rgb[mask] = replacement_rgb
            if mask_source == "click":
                any_click_mask_used = True

        # Commit + single sync + single PNG + single GLB.
        # 一次性提交到 cache，sync/PNG/GLB 各跑一次。
        cache["matched_rgb"] = working_rgb
        _sync_material_matrix_after_rgb_change(
            session_data, cache, previous_rgb, working_rgb
        )

        preview_bytes = _render_styled_preview_bytes(working_rgb, cache)
        preview_id = registry.register_bytes(
            request.session_id, preview_bytes, "preview_region_batch_replaced.png"
        )
        persisted_cache = cache.commit(
            _dirty_array_fields(
                cache,
                "matched_rgb",
                "material_matrix",
                "quantized_image",
                "preview_rgba",
            ),
            metadata_fields=_REPLACEMENT_CACHE_METADATA_FIELDS,
        )
        cache_published = True
        _invalidate_and_prewarm_visible_region_cache(request.session_id, store, session_data, cache)
        _bump_region_replacement_count(request.session_id, store, session_data, len(request.items))
        history_flags = _push_history_checkpoint(
            request.session_id,
            store,
            session_data,
            history_checkpoint,
        )
        editor_content_revision = advance_editor_content_revision(
            request.session_id,
            store,
            session_data,
        )
        selection_response = _selection_after_content_commit(
            request.session_id,
            store,
            session_data,
            cache,
        )
        publish_editor_commit(
            request.session_id,
            store,
            session_data,
            operation_id=operation_id,
            editor_content_revision=editor_content_revision,
            selection_revision=get_selection_revision(session_data),
            result=_editor_commit_result(
                session_data,
                cache=cache,
                preview_url=f"/api/files/{preview_id}",
            ),
        )

        # Async GLB rebuild for the whole batch of region edits. See
        # schedule_glb_build for job-token semantics when a newer replace
        # arrives before the background thread finishes.
        # 批量区域替换的 GLB 重建改为异步；重入竞争由 job_token 守护。
        _schedule_glb_build_best_effort(
            request.session_id,
            store,
            registry,
            persisted_cache,
        )
        glb_url: str | None = None

        contours_data: dict | None = cache.get("color_contours")

        # Legacy one-shot click mask gets cleared just like the per-item
        # endpoint does, but only if at least one click-sourced item was
        # consumed. Gradient masks are reusable metadata and survive.
        # 批次里消费过 click mask 的话清理一次性 mask；gradient 元数据保留。
        if any_click_mask_used:
            store.put(request.session_id, "selected_region_mask", None)
            store.put(request.session_id, "selected_region_id", None)

        diff_pixel_count = int(np.any(previous_rgb != working_rgb, axis=-1).sum())
        log.debug(
            "region-replace-batch diag",
            extra={
                "event": "converter_region_replace_batch_diag",
                "item_count": len(request.items),
                "diff_pixel_count": diff_pixel_count,
                "material_source": session_data.get("material_source"),
            },
        )

    except HTTPException as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        raise
    except PreviewCacheRevisionConflict as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _raise_replace_cache_conflict(
            e,
            session_id=request.session_id,
            operation="region_replace_batch",
        )
    except REPLACE_HANDLED_ERRORS as e:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(e).__name__,
        )
        _handle_core_error(e, "Batch region replacement")
    finally:
        cache_context.__exit__(*sys.exc_info())

    log.info(
        "region-replace-batch completed",
        extra={
            "event": "converter_region_replace_batch_done",
            "session_id": request.session_id,
            "item_count": len(request.items),
            "diff_pixel_count": diff_pixel_count,
            "any_click_mask_used": any_click_mask_used,
        },
    )
    return RegionReplaceResponse(
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=glb_url,
        color_contours=contours_data,
        message=f"Batch replaced {len(request.items)} regions successfully",
        **dynamic_material_result_from_cache(cache).model_dump(
            exclude={"operation_id", "editor_content_revision"}
        ),
        **history_flags,
        operation_id=operation_id,
        editor_content_revision=editor_content_revision,
        selection=selection_response,
    )


def _resolve_recipe_source_metadata(
    session_data: dict,
    cache: dict,
) -> tuple[LUTMetadata, np.ndarray | None, np.ndarray | None]:
    """Return ``(metadata, lut_rgb, lut_stacks)`` for a recipe endpoint.

    Bridges ``/predict-recipe`` and ``/apply-recipe-override`` over two source
    kinds:

    - **LUT-backed sessions** — ``session_data["lut_path"]`` points to a real
      calibration file. We resolve it via
      :meth:`LUTManager.load_lut_with_metadata` and return the real
      palette + pure-stack arrays so downstream forward-model prediction and
      pure-stack fallbacks work as they always have.
    - **Material-archive sessions** — ``session_data["material_source"] ==
      "material_archive"`` and ``lut_path`` is the sentinel literal
      ``"__material_archive__"`` (no file on disk). We synthesise a stub
      :class:`LUTMetadata` from ``selected_materials`` /
      ``material_layer_count`` / ``material_layer_height_mm`` so the
      apply / predict endpoints still get a palette length, layer order, and
      ``base_channel_idx`` to drive virtual-material validation, top-layer
      selection, and pad-slab growth. ``lut_rgb`` / ``lut_stacks`` are
      returned as ``None`` — callers must derive display RGB from
      ``cache["preview_colors"]`` (see :func:`_cache_preview_rgb`) because
      material archives have no LUT pure-stack mapping.

    耗材档案模式下 ``session_data["lut_path"]`` 是
    ``"__material_archive__"`` 这种 sentinel 字符串，没法 open，所以两种
    来源统一到这里：LUT 会话照旧走 ``LUTManager.load_lut_with_metadata``；
    耗材档案会话按 ``selected_materials`` / ``material_layer_count`` 拼出
    stub :class:`LUTMetadata`，``lut_rgb`` / ``lut_stacks`` 返回 ``None``，
    让上游自然退化到 cache preview colors 兜底。

    Raises:
        HTTPException(409): LUT session has no LUT file, or material-archive
            session is missing ``selected_materials``. Surfaces the same
            "Preview again first." hint the legacy code used.
    """
    material_source = str(session_data.get("material_source") or "lut")

    if material_source == "material_archive":
        selected_materials = session_data.get("selected_materials") or []
        if not isinstance(selected_materials, list) or not selected_materials:
            raise HTTPException(
                status_code=409,
                detail="Material-archive session missing selected_materials. Preview again first.",
            )
        # Stub palette: one ``PaletteEntry`` per selected material. The
        # ``color`` attribute is only consumed by
        # ``_canonical_apply_rgb(palette[idx].color)`` in the existing apply
        # fallback chain and by palette-length checks; use the slot name when
        # cache already has one (keeps downstream logs readable), otherwise
        # fall back to the material directory name.
        # stub 调色板：每个选中的耗材给一个 PaletteEntry。color 字段仅用于
        # ``_canonical_apply_rgb`` 的通道名兜底和长度校验；尽量用 cache 里
        # 已有的 slot_name，退而用目录名，保持日志/错误信息可读。
        slot_names_raw = cache.get("slot_names")
        slot_names = list(slot_names_raw) if isinstance(slot_names_raw, (list, tuple)) else []
        base_channel_idx = infer_material_archive_base_channel_idx(
            selected_materials,
            slot_names,
            cache.get("preview_colors") or {},
        )
        palette_entries: list[PaletteEntry] = []
        for idx, dir_name in enumerate(selected_materials):
            raw_slot = slot_names[idx] if idx < len(slot_names) else None
            label = str(raw_slot) if raw_slot else str(dir_name)
            palette_entries.append(
                PaletteEntry(color=label, material=str(dir_name))
            )
        try:
            layer_count = int(
                session_data.get("material_layer_count") or len(palette_entries) or 1
            )
            layer_height_mm = float(
                session_data.get("material_layer_height_mm") or 0.08
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Material-archive layer metadata invalid: {exc}",
            ) from exc
        metadata = LUTMetadata(
            palette=palette_entries,
            max_color_layers=layer_count,
            layer_height_mm=layer_height_mm,
            base_channel_idx=base_channel_idx,
            layer_order="Top2Bottom",
        )
        return metadata, None, None

    # LUT-backed session: the path must be a real file on disk.
    # LUT 会话：lut_path 必须是真实存在的文件。
    lut_path = session_data.get("lut_path")
    if not isinstance(lut_path, str) or not lut_path or not os.path.exists(lut_path):
        raise HTTPException(
            status_code=409,
            detail="LUT/source file missing. Preview again first.",
        )
    lut_rgb, lut_stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
    return metadata, lut_rgb, lut_stacks


def _cache_preview_rgb(cache: dict, channel_idx: int) -> np.ndarray | None:
    """Return the cached preview RGB for ``channel_idx`` or ``None``.

    Reads ``cache["preview_colors"]`` first (populated for merged LUTs and
    after ``_extend_cache_palette_with_virtuals``), then falls back to
    ``cache["color_conf"]["preview"]`` (the standard-color-mode canonical
    source). Used by the recipe endpoints as the material-archive fallback
    when ``_pure_stack_rgb`` cannot resolve a colour — material archives
    have no LUT pure-stack table but always publish a ``preview_colors``
    entry per selected material in ``p04_cache_building`` / P01.

    从 cache 读通道预览色，优先 ``preview_colors``，再回退
    ``color_conf.preview``。耗材档案模式没有 LUT 纯堆叠表，但 cache 里每
    个选中耗材一定有 ``preview_colors`` 条目，所以这是它的兜底色源。
    """
    if channel_idx < 0:
        return None
    for source in (
        cache.get("preview_colors"),
        (cache.get("color_conf") or {}).get("preview"),
    ):
        if not isinstance(source, dict):
            continue
        rgba = source.get(channel_idx)
        if rgba is None:
            rgba = source.get(str(channel_idx))
        if rgba is None:
            continue
        arr = np.asarray(rgba, dtype=np.uint8)
        if arr.ndim == 1 and arr.shape[0] >= 3:
            return arr[:3].copy()
    return None


@router.post("/predict-recipe", response_model=RecipePredictResponse)
def predict_recipe(
    request: RecipePredictRequest,
    store: SessionStore = Depends(get_session_store),
) -> RecipePredictResponse:
    """Predict the display color of a custom recipe for the active source."""
    session_data = _require_session(store, request.session_id)
    cache = session_data.get("preview_cache") or {}
    is_material_archive = (
        str(session_data.get("material_source") or "lut") == "material_archive"
    )
    metadata, _lut_rgb, _lut_stacks = _resolve_recipe_source_metadata(
        session_data, cache
    )

    try:
        if not is_material_archive:
            # LUT-backed session: keep the predictive forward model path.
            # LUT 会话：走前向模型预测。
            prediction = predict_recipe_color(
                metadata,
                recipe=request.recipe,
                layer_height_mm=request.layer_height_mm,
                color_layers=request.color_layers,
                layer_order=request.layer_order,
            )
        else:
            # Material-archive session: use Beer-Lambert forward model to
            # compute the true stacked colour from the selected materials'
            # fitted E/k parameters. This replaces the previous "top layer only"
            # fallback so multi-layer recipes predict correctly.
            # 耗材档案会话：使用 Beer-Lambert 前向模型计算多层叠层后的真实颜色，
            # 替代之前仅返回最顶层颜色的简单兜底。
            selected_materials = session_data.get("selected_materials") or []
            try:
                materials = load_multiple_materials(selected_materials)
                prediction_recipe = list(request.recipe)
                prediction_recipe_order = request.layer_order
                if bool(
                    session_data.get(
                        "material_dynamic_layer_count_enabled",
                        False,
                    )
                ):
                    prepared = _prepare_dynamic_manual_recipe(
                        session_data=session_data,
                        recipe=list(request.recipe),
                        layer_order=request.layer_order,
                        color_layers=request.color_layers,
                    )
                    prediction_recipe = list(
                        prepared["print_recipe_top_to_bottom"]
                    )
                    prediction_recipe_order = "Top2Bottom"
                recipe_bottom_to_top = convert_recipe_between_orders(
                    prediction_recipe,
                    prediction_recipe_order,
                    "Bottom2Top",
                )
                substrate = str(
                    cache.get("material_substrate")
                    or session_data.get("material_substrate")
                    or "white"
                )
                predicted_rgb_uint8 = predict_material_recipe_srgb(
                    np.asarray(recipe_bottom_to_top, dtype=np.int32),
                    materials,
                    layer_height_mm=request.layer_height_mm,
                    substrate=substrate,
                )
                prediction = {
                    "rgb": [int(v) for v in predicted_rgb_uint8.tolist()],
                    "lab": [
                        float(v)
                        for v in _rgb_to_lab(
                            predicted_rgb_uint8.reshape(1, 1, 3)
                        )
                        .reshape(3)
                        .tolist()
                    ],
                    "source": "material_archive_forward_model",
                    "runtime_mode_key": None,
                }
            except (FileNotFoundError, ValueError, OSError) as _exc:
                # If material params are missing (e.g. test fixtures without
                # real material archives), degrade to the previous top-layer
                # preview colour fallback so the endpoint stays usable.
                # 若材料参数缺失（如测试环境没有真实耗材档案），退化到旧的最
                # 顶层 preview 色兜底，保证端点仍可用。
                top_channel = _top_layer_channel(
                    list(request.recipe), request.layer_order
                )
                preview_rgb = (
                    _cache_preview_rgb(cache, top_channel)
                    if top_channel is not None
                    else None
                )
                if preview_rgb is None:
                    preview_rgb = np.asarray((128, 128, 128), dtype=np.uint8)
                prediction = {
                    "rgb": [int(v) for v in preview_rgb.tolist()],
                    "lab": [
                        float(v)
                        for v in _rgb_to_lab(preview_rgb.reshape(1, 1, 3))
                        .reshape(3)
                        .tolist()
                    ],
                    "source": "material_archive_preview",
                    "runtime_mode_key": None,
                }
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    prediction_source = str(prediction.get("source", "unknown"))
    log.info(
        "predict-recipe completed",
        extra={
            "event": "converter_predict_recipe_done",
            "session_id": request.session_id,
            "recipe_layer_count": len(request.recipe),
            "prediction_source": prediction_source,
            "is_material_archive": is_material_archive,
        },
    )
    return RecipePredictResponse(
        status="ok",
        message="Recipe color predicted",
        rgb=[int(v) for v in prediction.get("rgb", [])],
        lab=[float(v) for v in prediction.get("lab", [])],
        source=prediction_source,
        runtime_mode_key=(
            str(prediction["runtime_mode_key"])
            if prediction.get("runtime_mode_key") is not None
            else None
        ),
    )


# Canonical primary-name -> RGB fallback for apply's preview colour when the
# LUT has neither a forward model nor a pure-channel stack to sample. Keeping
# the dict in sync with the one in ``api/routers/lut.py`` is deliberate: both
# locations need the same visual shorthand so users never see "apply failed"
# just because a particular bundle happens to be sparse.
# 当 LUT 既没前向模型也没纯通道堆叠时，应用自定义配方的预览色走此兜底：
# 按通道名映射到 CMYK / RGB 经典原色，和 ``api/routers/lut.py`` 保持同步，
# 避免"某个 bundle 太稀疏"就让应用失败。
_APPLY_CANONICAL_RGB: dict[str, tuple[int, int, int]] = {
    "cyan": (0, 183, 235),
    "magenta": (230, 0, 126),
    "yellow": (255, 212, 0),
    "black": (17, 17, 17),
    "white": (245, 245, 245),
    "red": (229, 57, 53),
    "green": (67, 160, 71),
    "blue": (30, 136, 229),
    "orange": (251, 140, 0),
    "purple": (142, 36, 170),
    "pink": (236, 64, 122),
    "gray": (158, 158, 158),
    "grey": (158, 158, 158),
    "brown": (121, 85, 72),
}


def _canonical_apply_rgb(color_name: str | None) -> np.ndarray | None:
    """Map a channel name to a canonical primary RGB triplet.

    按通道名返回经典原色 RGB 三元组；找不到返回 ``None``。
    """
    if not color_name:
        return None
    hit = _APPLY_CANONICAL_RGB.get(color_name.strip().lower())
    if hit is None:
        return None
    return np.asarray(hit, dtype=np.uint8)


def _recipe_apply_can_fallback_from_prediction_error(exc: ValueError) -> bool:
    """Return whether apply can continue with a deterministic color fallback.

    这些错误只代表“无法精确预测预览色”，不代表用户配方不能写入选区；
    应用接口可以继续用纯色栈 / 缓存预览色 / 标准色兜底。
    """
    message = str(exc)
    return (
        "No predictive runtime" in message
        or "not present in the runtime package" in message
        or "exact prediction unavailable" in message
    )


def _recipe_apply_runtime_package_fallback_source(exc: ValueError) -> str:
    """Classify fallback source for custom recipe apply telemetry.

    区分“没有前向模型”和“runtime 包外配方”，方便前端/日志看出兜底原因。
    """
    message = str(exc)
    if (
        "not present in the runtime package" in message
        or "exact prediction unavailable" in message
    ):
        return "runtime_package_fallback"
    return "pure_stack_fallback"


def _hex_to_rgb_triple(hex_value: str) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` into an ``(r, g, b)`` uint8 triple.

    将 ``#RRGGBB`` 解析为 ``(r, g, b)`` uint8 三元组；非法输入抛 ``ValueError``。
    """
    raw = hex_value.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"Invalid virtual material hex: {hex_value!r}")
    value = int(raw, 16)
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def _extend_cache_palette_with_virtuals(
    cache: dict,
    lut_palette_length: int,
    virtual_materials: list[VirtualMaterial] | None,
) -> list[tuple[int, tuple[int, int, int], str]]:
    """Append user-declared virtual materials into the preview cache palette.

    把用户声明的虚拟耗材追加到预览缓存的调色板，保证 material_matrix 里
    ``>= LUT.N`` 的索引能被 preview/3MF 正确解析。Returns the list of
    ``(cache_index, rgb, name)`` triples that were written so callers can
    honour the user's per-layer intent when computing the overall preview
    colour.

    Virtual materials are indexed strictly above the LUT palette so LUT-native
    channels stay at their canonical positions; the ``cache_index`` returned
    is ``lut_palette_length + virtual_position``.
    """
    if not virtual_materials:
        return []
    # CRITICAL: ``cache["color_conf"]`` / ``cache["preview_colors"]`` /
    # ``cache["slot_names"]`` may be direct references into the process-wide
    # ``ColorSystem.get(color_mode)`` dict (populated by ``p01`` +
    # ``p04_cache_building``). Appending to them in place permanently pollutes
    # every subsequent request handled by this worker: 透明通道被额外槽位顶掉、
    # s07 按错误的 ``num_materials`` 生成方块、非 override 区域丢配方。
    # 所以必须先做 copy-on-write，把 cache 里的引用换成独立副本，再追加。
    color_conf_src = cache.get("color_conf")
    color_conf = (
        dict(color_conf_src) if isinstance(color_conf_src, dict) else {}
    )
    cache["color_conf"] = color_conf
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

    # Standard color modes (CMYW / RYBW / BW) don't pre-populate
    # ``cache["preview_colors"]`` or ``cache["slot_names"]`` — those keys are
    # only populated for Merged LUTs. The ``/layer-images`` endpoint reads
    # ``preview_colors`` with priority and only falls back to
    # ``color_conf.preview`` when it's missing. If we seeded ``preview_colors``
    # with a fresh empty dict here and only wrote virtuals into it, the
    # endpoint would switch from the complete ``color_conf`` fallback to an
    # incomplete virtuals-only ``preview_colors`` mid-session, and every
    # native layer would render as background grey — exactly the "分层预览
    # 只显示改过配方的那几层，原预览变灰" regression. Seed both keys from the
    # already-copied ``conf_preview`` / ``conf_slots`` so the cache always
    # reflects the FULL palette (natives + upcoming virtuals) after apply.
    # 标准色模式（CMYW / RYBW / BW）下 cache 没有 preview_colors / slot_names，
    # 只有 Merged LUT 才会预置这两个键。/layer-images 端点优先读 preview_colors，
    # 缺失时才回退到 color_conf.preview。如果这里新建空字典只塞虚拟耗材，
    # 端点就会从完整的 color_conf 兜底切换到只有虚拟耗材的残缺字典，native
    # 层全部变灰（就是分层预览只剩配方层的现象）。用已复制的 conf_preview /
    # conf_slots 做种子，保证 apply 后 cache 里的调色板始终是 native + 虚拟
    # 的完整集合。
    preview_colors_src = cache.get("preview_colors")
    if isinstance(preview_colors_src, dict):
        preview_colors = dict(preview_colors_src)
    else:
        preview_colors = dict(conf_preview)
    cache["preview_colors"] = preview_colors
    slot_names_src = cache.get("slot_names")
    if isinstance(slot_names_src, (list, tuple)):
        slot_names = list(slot_names_src)
    else:
        slot_names = list(conf_slots)
    cache["slot_names"] = slot_names

    written: list[tuple[int, tuple[int, int, int], str]] = []
    for offset, material in enumerate(virtual_materials):
        cache_index = lut_palette_length + offset
        r, g, b = _hex_to_rgb_triple(material.hex)
        rgba = [int(r), int(g), int(b), 255]
        preview_colors[cache_index] = rgba
        # slot_names is addressed by int index; pad with None placeholders if
        # the current list is shorter (shouldn't happen in practice but keeps
        # behaviour deterministic for sparse caches).
        while len(slot_names) < cache_index:
            slot_names.append(f"Slot_{len(slot_names)}")
        if len(slot_names) == cache_index:
            slot_names.append(material.name)
        else:
            slot_names[cache_index] = material.name
        # color_conf mirrors preview_colors/slot_names for downstream helpers
        # (e.g. pipeline color configuration). Keep them in lockstep so any
        # path that reads color_conf[*] sees the virtual entry.
        conf_preview[cache_index] = rgba
        while len(conf_slots) < cache_index:
            conf_slots.append(f"Slot_{len(conf_slots)}")
        if len(conf_slots) == cache_index:
            conf_slots.append(material.name)
        else:
            conf_slots[cache_index] = material.name
        written.append((cache_index, (int(r), int(g), int(b)), material.name))
    return written


def _top_layer_channel(recipe: list[int], layer_order: str) -> int | None:
    """Return the channel index of the visually topmost layer in ``recipe``.

    返回 ``recipe`` 中视觉上最顶层那一层的通道索引；空配方返回 ``None``。
    """
    if not recipe:
        return None
    return int(recipe[0] if layer_order == "Top2Bottom" else recipe[-1])


def _prepare_dynamic_manual_recipe(
    *,
    session_data: dict,
    recipe: list[int],
    layer_order: str,
    color_layers: int | None,
) -> dict[str, object]:
    """Validate and pad an authoritative dynamic manual recipe.

    校验动态手工实际配方，并用显式基板耗材补齐打印配方。

    Args:
        session_data: Canonical preview session settings. / 标准预览会话设置。
        recipe: User-submitted actual recipe. / 用户提交的实际配方。
        layer_order: Submitted recipe order. / 提交配方的层序。
        color_layers: Explicit submitted actual count. / 显式提交的实际层数。

    Returns:
        Actual and padded print recipe metadata in Top-to-Bottom order.
        / Top-to-Bottom 实际与补齐打印配方元数据。

    Raises:
        HTTPException: With 422 for invalid length, order, or material indices.
            / 长度、层序或耗材索引无效时返回 422。
    """
    normalized_order = normalize_layer_order(layer_order)
    actual_input = [int(value) for value in recipe]
    if color_layers is not None and int(color_layers) != len(actual_input):
        raise HTTPException(
            status_code=422,
            detail="color_layers must equal the submitted dynamic recipe length.",
        )
    minimum = int(session_data.get("material_min_layer_count") or 5)
    maximum = int(session_data.get("material_max_layer_count") or 10)
    if not minimum <= len(actual_input) <= maximum:
        raise HTTPException(
            status_code=422,
            detail=(
                "Dynamic actual recipe length must be within the preview "
                f"range {minimum}-{maximum}."
            ),
        )
    selected_materials = session_data.get("selected_materials") or []
    backing_index = _resolve_material_backing_index(
        selected_materials,
        session_data.get("material_backing_material_index"),
    )
    if any(
        value < 0 or value >= len(selected_materials) for value in actual_input
    ):
        raise HTTPException(
            status_code=422,
            detail="Dynamic recipe contains a material index outside selected_materials.",
        )
    actual_top_to_bottom = convert_recipe_between_orders(
        actual_input,
        normalized_order,
        "Top2Bottom",
    )
    print_top_to_bottom = pad_recipe_to_layer_count(
        actual_top_to_bottom,
        maximum,
        backing_index,
        "Top2Bottom",
    )
    return {
        "actual_recipe_top_to_bottom": actual_top_to_bottom,
        "print_recipe_top_to_bottom": print_top_to_bottom,
        "actual_layer_count": len(actual_top_to_bottom),
        "padding_layer_count": maximum - len(actual_top_to_bottom),
        "backing_material_index": backing_index,
    }


def _resolve_dynamic_region_actual_recipe(
    *,
    session_data: dict,
    cache: dict,
    region_id: str,
    print_recipe_top_to_bottom: list[int],
) -> list[int]:
    """Resolve an actual recipe only from authoritative dynamic metadata.

    仅从权威动态元数据解析区域实际配方，绝不裁剪基板尾层推断深度。

    Args:
        session_data: Current session state. / 当前会话状态。
        cache: Preview cache metadata. / 预览缓存元数据。
        region_id: Region identifier. / 区域标识。
        print_recipe_top_to_bottom: Sampled full print stack. / 采样的完整打印栈。

    Returns:
        Saved actual Top-to-Bottom recipe. / 保存的 Top-to-Bottom 实际配方。

    Raises:
        HTTPException: With 409 when metadata is absent or inconsistent.
            / 元数据缺失或不一致时返回 409。
    """
    def metadata_conflict(detail: str) -> NoReturn:
        raise HTTPException(status_code=409, detail=detail)

    try:
        minimum = int(session_data.get("material_min_layer_count") or 5)
        maximum = int(session_data.get("material_max_layer_count") or 10)
    except (TypeError, ValueError):
        metadata_conflict(
            "Dynamic layer range metadata is inconsistent. Re-run preview."
        )
    selected_materials = session_data.get("selected_materials") or []
    if not isinstance(selected_materials, list) or not selected_materials:
        metadata_conflict(
            "Dynamic backing material metadata is unavailable. Re-run preview."
        )
    try:
        backing_index = _resolve_material_backing_index(
            selected_materials,
            session_data.get("material_backing_material_index"),
        )
    except HTTPException:
        metadata_conflict(
            "Dynamic backing material metadata is inconsistent. Re-run preview."
        )

    sampled_print = [int(value) for value in print_recipe_top_to_bottom]

    def validate_entry(item: dict) -> list[int]:
        actual = item.get("actual_recipe_top_to_bottom")
        saved_print = item.get("print_recipe_top_to_bottom")
        actual_count = item.get("actual_layer_count")
        padding_count = item.get("padding_layer_count")
        try:
            actual_values = [int(value) for value in actual]
            print_values = [int(value) for value in saved_print]
            actual_count_value = int(actual_count)
            padding_count_value = int(padding_count)
        except (TypeError, ValueError):
            metadata_conflict(
                "Dynamic region recipe metadata is inconsistent. Re-run preview."
            )
        if (
            not minimum <= actual_count_value <= maximum
            or actual_count_value != len(actual_values)
            or len(print_values) != maximum
            or padding_count_value != maximum - actual_count_value
            or print_values[:actual_count_value] != actual_values
            or any(
                value != backing_index
                for value in print_values[actual_count_value:]
            )
            or print_values != sampled_print
        ):
            metadata_conflict(
                "Dynamic region recipe metadata is inconsistent. Re-run preview."
            )
        return actual_values

    for item in reversed(list(session_data.get("recipe_overrides") or [])):
        if not isinstance(item, dict) or str(item.get("region_id")) != region_id:
            continue
        return validate_entry(item)

    dynamic_info = cache.get("material_dynamic_layer_info")
    colors = dynamic_info.get("colors") if isinstance(dynamic_info, dict) else None
    for item in colors if isinstance(colors, list) else []:
        if not isinstance(item, dict):
            continue
        saved_print = item.get("print_recipe_top_to_bottom")
        if not isinstance(saved_print, list) or [int(value) for value in saved_print] != [
            int(value) for value in print_recipe_top_to_bottom
        ]:
            continue
        return validate_entry(item)
    raise HTTPException(
        status_code=409,
        detail="Dynamic actual recipe metadata is unavailable. Re-run preview.",
    )


def _pure_stack_rgb(
    rgb: np.ndarray | None,
    stacks: np.ndarray | None,
    channel_idx: int,
) -> np.ndarray | None:
    """Return the LUT's RGB for the pure-channel stack ``[c, c, ..., c]``.

    查找 LUT 中纯通道堆叠配方（每层都是同一通道）对应的 RGB，
    用作缺少前向模型时自定义配方应用的兜底颜色。

    Args:
        rgb: ``(N, 3)`` uint8 array of per-recipe RGB, or ``None``.
        stacks: ``(N, layers)`` int array of per-recipe channel indices, or ``None``.
        channel_idx: Palette channel index to resolve. 调色板通道索引。

    Returns:
        ``(3,)`` uint8 array when a matching pure stack exists, else ``None``.
    """
    if rgb is None or stacks is None:
        return None
    rgb_arr = np.asarray(rgb)
    stacks_arr = np.asarray(stacks)
    if rgb_arr.ndim != 2 or stacks_arr.ndim != 2:
        return None
    if stacks_arr.shape[0] != rgb_arr.shape[0] or stacks_arr.shape[1] == 0:
        return None
    target = np.full(stacks_arr.shape[1], channel_idx, dtype=stacks_arr.dtype)
    matches = np.where(np.all(stacks_arr == target, axis=1))[0]
    if matches.size == 0:
        return None
    row = rgb_arr[int(matches[0])]
    if row.shape[-1] < 3:
        return None
    return np.asarray(row[:3], dtype=np.uint8)


@router.post("/apply-recipe-override", response_model=RecipeOverrideApplyResponse)
def apply_recipe_override(
    request: RecipeOverrideApplyRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RecipeOverrideApplyResponse:
    """Apply a custom recipe override to the selected regions and update preview cache."""
    session_data = _require_session(store, request.session_id)
    operation_id = begin_editor_commit(
        request.session_id,
        store,
        session_data,
        operation_id=request.operation_id,
        operation="apply_recipe_override",
    )
    missing_session_value = object()
    rollback_snapshot: dict[str, object] = {}

    def restore_session_state() -> None:
        for key, value in rollback_snapshot.items():
            if value is missing_session_value:
                session_data.pop(key, None)
            else:
                session_data[key] = deepcopy(value)

    cache_context = _preview_cache_transaction_with_history(
        request.session_id,
        store,
        session_data,
        history_label="apply_recipe_override",
        operation_id=operation_id,
        fields={
            "matched_rgb",
            "material_matrix",
            "mask_solid",
            "quantized_image",
        },
    )
    cache, history_checkpoint = cache_context.__enter__()
    selection_response: SelectionDocumentResponse | None = None
    editor_content_revision: int | None = None
    cache_published = False

    def abort_before_recipe_commit(exc: BaseException) -> NoReturn:
        """Close the manually-entered transaction for pre-commit failures.

        手动进入事务后、业务 ``try`` 开始前若校验失败，也必须释放事务并
        写入确定的 failed receipt，避免生成器由垃圾回收关闭时重复释放锁。
        """
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=False,
            error_type=type(exc).__name__,
        )
        cache_context.__exit__(type(exc), exc, exc.__traceback__)
        raise exc

    # Capture rollback state only after the cache transaction has acquired the
    # same per-session lock as history. This keeps the cache/session snapshot
    # aligned with the undo checkpoint and avoids restoring a racing edit.
    rollback_snapshot.update({
        key: (
            deepcopy(session_data[key])
            if key in session_data
            else missing_session_value
        )
        for key in (
            "preview_cache",
            "recipe_overrides",
            "recipe_override_count",
            # Symmetric with the success-path write below: if a failure lands
            # between persisting the snapshot and the history push, the
            # rollback must not leave an orphan applied-mask entry behind.
            # 与成功路径的写入保持对称：若在快照落盘之后、历史入栈之前失败，
            # 回滚不能留下孤儿掩码快照。
            RECIPE_OVERRIDE_APPLIED_MASKS_KEY,
        )
    })

    matched_rgb: np.ndarray | None = cache.get("matched_rgb")
    material_matrix: np.ndarray | None = cache.get("material_matrix")
    if matched_rgb is None or material_matrix is None:
        abort_before_recipe_commit(
            HTTPException(
                status_code=409,
                detail="Preview cache missing matched_rgb or material_matrix.",
            )
        )

    region_mask_items = _get_region_mask_items_for_ids(session_data, request.region_ids)
    if not region_mask_items:
        abort_before_recipe_commit(
            HTTPException(
                status_code=409,
                detail="No selected regions available for recipe override.",
            )
        )

    # Snapshot the exact masks this override is applied to. The synthetic
    # ``__editor_selection__:<rev>`` entries in ``selected_region_masks`` are
    # pruned on every selection gesture (including the automatic clear after
    # this apply succeeds), so /generate must be able to resolve the override
    # footprint from this snapshot instead of the live selection state.
    # 快照本次覆盖实际使用的掩码。selected_region_masks 里的
    # __editor_selection__:<rev> 合成条目会在每次选区手势时被清理（包括
    # 本次 apply 成功后前端的自动清空），/generate 必须能从这份快照解析
    # 覆盖区域，而不是依赖易失的实时选区状态。
    applied_override_masks = session_data.get(RECIPE_OVERRIDE_APPLIED_MASKS_KEY)
    applied_override_masks = dict(applied_override_masks) if isinstance(applied_override_masks, dict) else {}
    for _snapshot_region_id, _snapshot_mask in region_mask_items:
        applied_override_masks[str(_snapshot_region_id)] = pack_applied_region_mask(
            _snapshot_mask
        )
    existing_overrides = list(session_data.get("recipe_overrides") or [])

    # Resolve source metadata: real LUT for LUT-backed sessions, stub
    # metadata + ``(None, None)`` arrays for material-archive sessions
    # (whose ``lut_path`` is the ``"__material_archive__"`` sentinel and
    # cannot be opened). The fallback chain below reads
    # ``cache["preview_colors"]`` via :func:`_cache_preview_rgb` when the
    # LUT pure-stack arrays are unavailable.
    # 解析来源元数据：LUT 会话走真实 LUT；耗材档案会话返回 stub metadata
    # 和 (None, None) 数组，下面的兜底链用 cache preview_colors 取色。
    is_material_archive = (
        str(session_data.get("material_source") or "lut") == "material_archive"
    )
    try:
        metadata, _rgb, _stacks = _resolve_recipe_source_metadata(session_data, cache)
    except BaseException as exc:
        abort_before_recipe_commit(exc)

    try:
        lut_palette_length = len(metadata.palette)
        virtual_materials = list(request.virtual_materials or [])
        allowed_upper = lut_palette_length + len(virtual_materials)
        dynamic_manual_recipe: dict[str, object] | None = None
        if is_material_archive and bool(
            session_data.get("material_dynamic_layer_count_enabled", False)
        ):
            if virtual_materials:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Dynamic material recipes may only reference the "
                        "selected material archives."
                    ),
                )
            dynamic_manual_recipe = _prepare_dynamic_manual_recipe(
                session_data=session_data,
                recipe=list(request.recipe),
                layer_order=request.layer_order,
                color_layers=request.color_layers,
            )

        # A non-empty runtime palette is the authoritative material-ID range,
        # whether or not the caller declares virtual materials. Letting an
        # index past this boundary into ``material_matrix`` defers the failure
        # to S05/S08 and can break loop material identity. Legacy callers whose
        # LUT metadata exposes no palette retain their raw-index compatibility
        # unless they explicitly opt into virtual materials.
        # 只要运行时调色板非空，它就是材料 ID 的权威范围，无论调用方是否
        # 声明虚拟耗材。越界值若进入 material_matrix，会延迟到 S05/S08 才
        # 失败并破坏挂环材料身份。仅 metadata.palette 为空的旧调用方保留
        # 原始索引兼容；一旦显式使用虚拟耗材仍严格校验。
        if lut_palette_length > 0 or virtual_materials:
            for idx, channel in enumerate(request.recipe):
                if channel < 0 or channel >= allowed_upper:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"recipe[{idx}]={channel} out of range; LUT has "
                            f"{lut_palette_length} channel(s) and "
                            f"{len(virtual_materials)} virtual material(s) "
                            f"were supplied."
                        ),
                    )

        top_channel_idx = _top_layer_channel(
            list(request.recipe), request.layer_order
        )

        # Custom recipes must still apply when the bundle has no forward model
        # (e.g. material archives / native LUTs). In that case we synthesise a
        # deterministic preview color from the LUT's pure-stack recipe of the
        # topmost visible layer so the material_matrix update still produces
        # visible feedback instead of hard-failing the whole request.
        # 自定义配方在缺少前向模型（例如材料包 / 原生 LUT）时也必须能应用。
        # 此时用 LUT 里"最顶层通道"对应的纯堆叠配方颜色作为兜底预测色，
        # 保证 material_matrix 更新依旧能给用户可见的反馈，而不是整单报错。
        used_virtual_preview = False
        # When the topmost layer is a user-declared virtual material, trust the
        # user's intent colour directly — this is the whole point of the
        # virtual-material feature and keeps the 2D preview honest instead of
        # rendering the LUT substitute channel.
        # 顶层若是用户声明的虚拟耗材，直接用该耗材的 hex 作为 2D 预览色，
        # 保证所见即所得，而不是 LUT 里代用通道的色。
        if (
            top_channel_idx is not None
            and top_channel_idx >= lut_palette_length
            and virtual_materials
        ):
            offset = top_channel_idx - lut_palette_length
            if 0 <= offset < len(virtual_materials):
                material = virtual_materials[offset]
                predicted_rgb = np.asarray(
                    _hex_to_rgb_triple(material.hex), dtype=np.uint8
                )
                predicted_lab = [
                    float(v)
                    for v in _rgb_to_lab(
                        predicted_rgb.reshape(1, 1, 3)
                    ).reshape(3).tolist()
                ]
                prediction_source = "virtual_material"
                runtime_mode_key = None
                match_mode = "virtual_material"
                used_virtual_preview = True

        if not used_virtual_preview:
            # For predictive runtimes we can only call in when every recipe
            # index actually lives in the LUT's palette; virtual indices have
            # no forward-model representation yet, so we fall through to the
            # user-intent / pure-stack fallback instead of erroring out.
            # 前向模型只认识真实 LUT 通道；recipe 含虚拟索引时直接走兜底。
            # Only treat an index as "virtual" when the caller explicitly
            # supplied a virtual materials list; otherwise legacy callers with
            # empty ``metadata.palette`` but valid channel indices keep their
            # old predictive path (empty palette makes ``>= lut_palette_length``
            # match every index, which would wrongly bypass the forward model).
            # 仅当调用方显式提供 virtual_materials 时才把索引当作"虚拟"；
            # 否则保持老调用方的兼容性（空 palette 下每个索引都会大于等于 0，
            # 若不加这层判断会错把所有普通请求甩到兜底路径）。
            recipe_has_virtual = bool(virtual_materials) and any(
                ch >= lut_palette_length for ch in request.recipe
            )
            # Material-archive sessions have no LUT file and therefore no
            # forward-model runtime. Skipping ``predict_recipe_color`` for
            # these sessions avoids a stub-metadata round-trip that would
            # ValueError inside the predictive runtime loader and lets the
            # fallback chain pick a deterministic preview colour from
            # ``preview_colors``. ``is_material_archive`` is the source-of-
            # truth here (driven by ``session_data["material_source"]``);
            # we cannot infer the source from ``_rgb`` / ``_stacks`` being
            # ``None`` because legacy tests legitimately monkeypatch the
            # LUT loader to return ``stacks=None`` while still wiring the
            # predictive path.
            # 耗材档案会话没有 LUT 文件也没有前向模型 runtime，此处跳过
            # 在耗材档案模式下先尝试 forward_model 做物理预测，
            # 与 /predict-recipe 保持一致；失败后才走兜底链。
            # 用 session 的 material_source 作为唯一信号——不能靠 _rgb/_stacks 是否为
            # None 来推断，老 LUT 测试会合法地 mock stacks=None 但仍然
            # 走预测路径。
            try:
                if recipe_has_virtual:
                    raise ValueError(
                        "No predictive runtime is available for virtual materials"
                    )
                if is_material_archive:
                    selected_materials = session_data.get("selected_materials") or []
                    try:
                        materials = load_multiple_materials(selected_materials)
                        prediction_recipe = (
                            dynamic_manual_recipe["print_recipe_top_to_bottom"]
                            if dynamic_manual_recipe is not None
                            else request.recipe
                        )
                        prediction_recipe_order = (
                            "Top2Bottom"
                            if dynamic_manual_recipe is not None
                            else request.layer_order
                        )
                        recipe_bottom_to_top = convert_recipe_between_orders(
                            prediction_recipe,
                            prediction_recipe_order,
                            "Bottom2Top",
                        )
                        substrate = str(
                            cache.get("material_substrate")
                            or session_data.get("material_substrate")
                            or "white"
                        )
                        predicted_rgb = predict_material_recipe_srgb(
                            np.asarray(recipe_bottom_to_top, dtype=np.int32),
                            materials,
                            layer_height_mm=request.layer_height_mm,
                            substrate=substrate,
                        )
                        predicted_lab = [
                            float(v)
                            for v in _rgb_to_lab(
                                predicted_rgb.reshape(1, 1, 3)
                            ).reshape(3).tolist()
                        ]
                        prediction_source = "material_archive_forward_model"
                        runtime_mode_key = None
                        match_mode = "predictive"
                    except (FileNotFoundError, ValueError, OSError) as mat_exc:
                        raise ValueError(
                            "No predictive runtime is available for material archive: "
                            + str(mat_exc)
                        ) from mat_exc
                else:
                    prediction = predict_recipe_color(
                        metadata,
                        recipe=request.recipe,
                        layer_height_mm=request.layer_height_mm,
                        color_layers=request.color_layers,
                        layer_order=request.layer_order,
                    )
                    predicted_rgb = np.asarray(prediction.get("rgb", []), dtype=np.uint8)
                    if predicted_rgb.shape != (3,):
                        raise ValueError("Predicted RGB payload is invalid")
                    predicted_lab = [float(v) for v in prediction.get("lab", [])]
                    prediction_source = prediction.get("source")
                    runtime_mode_key = prediction.get("runtime_mode_key")
                    match_mode = "predictive"
            except ValueError as predict_exc:
                if not _recipe_apply_can_fallback_from_prediction_error(
                    predict_exc
                ):
                    raise
                top_channel = top_channel_idx if top_channel_idx is not None else 0
                # Multi-tier fallback so apply never 422s for lack of colour data:
                # (1) LUT pure-stack, (2) cached preview_colors entry for the
                # top channel (covers material-archive sessions whose selected
                # materials publish preview RGB into the cache during preview),
                # (3) canonical primary by channel name (LUT-side sparse
                # palettes like BW without explicit RGB), (4) neutral grey.
                # The material_matrix update is the real work here; the
                # preview colour is only for painting the cached region.
                # 多级兜底：LUT 纯堆叠 → cache preview_colors 的通道预览色
                # （覆盖耗材档案模式）→ 通道名对应的原色 → 中性灰。真正的
                # 工作是 material_matrix 更新，预览色只是给缓存区域着色。
                fallback_rgb = _pure_stack_rgb(_rgb, _stacks, top_channel)
                if fallback_rgb is None:
                    fallback_rgb = _cache_preview_rgb(cache, top_channel)
                if (
                    fallback_rgb is None
                    and 0 <= top_channel < lut_palette_length
                ):
                    fallback_rgb = _canonical_apply_rgb(
                        metadata.palette[top_channel].color
                    )
                if fallback_rgb is None:
                    fallback_rgb = np.asarray((128, 128, 128), dtype=np.uint8)
                predicted_rgb = fallback_rgb
                predicted_lab = [
                    float(v)
                    for v in _rgb_to_lab(
                        predicted_rgb.reshape(1, 1, 3)
                    ).reshape(3).tolist()
                ]
                # Distinguish the material-archive cache-backed fallback from
                # the LUT pure-stack fallback so downstream logs and the UI
                # can differentiate "no forward model, used archive preview"
                # from "LUT exists but the recipe was outside the predictive
                # grid". 区分耗材档案兜底与 LUT 纯堆叠兜底，方便日志/前端
                # 分辨"没前向模型走档案"和"LUT 不在预测格"两种来源。
                prediction_source = (
                    "material_archive_preview"
                    if is_material_archive
                    else _recipe_apply_runtime_package_fallback_source(
                        predict_exc
                    )
                )
                runtime_mode_key = None
                match_mode = prediction_source

        # Extend the preview cache with any user-declared virtual materials so
        # downstream GLB rendering / 3MF export (which index preview_colors and
        # slot_names by material id) can resolve indices beyond LUT.N.
        # 扩展预览缓存里的 preview_colors / slot_names / color_conf，让下游
        # GLB 渲染和 3MF 导出按索引读 preview_colors 时能解析到虚拟耗材。
        _extend_cache_palette_with_virtuals(
            cache,
            lut_palette_length,
            virtual_materials or None,
        )

        current_layers = int(material_matrix.shape[2])
        target_layers = int(request.color_layers)
        if dynamic_manual_recipe is not None:
            configured_maximum = int(
                session_data.get("material_max_layer_count") or 10
            )
            if current_layers != configured_maximum:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Dynamic material matrix width does not match the "
                        "preview maximum. Re-run preview."
                    ),
                )
            target_layers = configured_maximum
        if target_layers > current_layers:
            pad_count = target_layers - current_layers
            # Growing ``material_matrix`` beyond its current depth has two
            # conflicting constraints that must be satisfied at the same time:
            #
            #   (a) Pixels OUTSIDE the object silhouette (``~mask_solid``,
            #       i.e., the transparent background p03 has already marked
            #       with ``-1``) must NOT gain any material at the new
            #       layers. Otherwise S06 copies them into ``full_matrix``
            #       and S07 emits a White mesh ringing the model at the
            #       extended Z — the "整块白矩形包裹 / 透明通道失效" bug.
            #
            #   (b) Pixels INSIDE the object silhouette (``mask_solid``) that
            #       the user did not override must keep a real material at
            #       the new layers so the extended region stays continuous
            #       with the backing slab. If we pad them with ``-1`` too
            #       they become "air" and the user sees their 6th layer
            #       collapse into an empty silhouette outside the override
            #       — the "第 6 层空层" bug.
            #
            # Both constraints collapse into a single rule: the pad slab is
            # ``-1`` everywhere except the ``mask_solid`` interior, which
            # gets the LUT's base channel (normally White on CMYW). The
            # override region is then overwritten by the user's recipe a
            # few lines down, so this pad only affects non-override pixels.
            # 扩展 material_matrix 必须同时满足两条约束：(a) 物体轮廓外
            # (~mask_solid，p03 已经标记为 -1 的透明背景) 新增的层上绝不能
            # 产生材料，否则 S07 会围着模型生成一圈白色 mesh（"整块白矩形
            # / 透明通道失效"）；(b) 物体轮廓内但未被 override 的像素在新
            # 增层上要保留实体材料，跟下方背板连续，否则用户的第 6 层会
            # 塌成空层（"第 6 层空层"）。所以 pad slab 整体置 -1，再只在
            # mask_solid 位置写 LUT base channel（CMYW 下就是白色）；接下
            # 来几行再把 override 区域覆盖成用户配方。
            mask_solid: np.ndarray | None = cache.get("mask_solid")
            if mask_solid is None:
                raise HTTPException(
                    status_code=409,
                    detail="Preview cache missing mask_solid; re-run preview before applying recipe override.",
                )
            mask_solid_arr = np.asarray(mask_solid, dtype=bool)
            if mask_solid_arr.shape != material_matrix.shape[:2]:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "mask_solid shape does not match material_matrix; "
                        "re-run preview before applying recipe override."
                    ),
                )
            material_matrix = _ensure_material_matrix_signed_capacity(
                material_matrix,
                -1,
                int(metadata.base_channel_idx),
            )
            pad_slab = np.full(
                (material_matrix.shape[0], material_matrix.shape[1], pad_count),
                -1,
                dtype=material_matrix.dtype,
            )
            pad_slab[mask_solid_arr] = int(metadata.base_channel_idx)
            if metadata.layer_order == "Bottom2Top":
                material_matrix = np.concatenate([pad_slab, material_matrix], axis=2)
            else:
                material_matrix = np.concatenate([material_matrix, pad_slab], axis=2)

        if dynamic_manual_recipe is not None:
            recipe_full = np.asarray(
                dynamic_manual_recipe["print_recipe_top_to_bottom"],
                dtype=np.int32,
            )
        else:
            recipe_top_to_bottom = convert_recipe_between_orders(
                request.recipe,
                request.layer_order,
                "Top2Bottom",
            )
            recipe_full = np.asarray(
                pad_recipe_to_layer_count(
                    recipe_top_to_bottom,
                    int(material_matrix.shape[2]),
                    int(metadata.base_channel_idx),
                    "Top2Bottom",
                ),
                dtype=np.int32,
            )
        material_matrix = _ensure_material_matrix_signed_capacity(
            material_matrix,
            recipe_full,
            int(metadata.base_channel_idx),
        )

        updated_rgb = matched_rgb.copy()
        combined_override_mask = np.zeros(updated_rgb.shape[:2], dtype=bool)
        for _region_id, region_mask in region_mask_items:
            effective_mask = np.asarray(region_mask, dtype=bool)
            if effective_mask.shape != updated_rgb.shape[:2]:
                log.warning(
                    "Region mask shape %s does not match matched_rgb shape %s; "
                    "rejecting the recipe override.",
                    effective_mask.shape, updated_rgb.shape[:2],
                    extra={
                        "event": "recipe_override_shape_mismatch",
                        "error_type": "RecipeOverrideMaskShapeMismatch",
                        "error_message": (
                            "A recipe override region mask shape did not match "
                            "the preview image; the override was not committed."
                        ),
                        "fallback_action": "reject_request",
                        "recovery_action": "reselect_region_and_apply_again",
                        "region_id": str(_region_id),
                        "mask_shape": list(effective_mask.shape),
                        "matched_rgb_shape": list(updated_rgb.shape[:2]),
                    },
                )
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Recipe override region mask shape does not match the "
                        f"current preview for region {_region_id}; reselect the "
                        "region and apply the recipe again."
                    ),
                )
            combined_override_mask |= effective_mask
            updated_rgb[effective_mask] = predicted_rgb
            material_matrix[effective_mask] = recipe_full

        if target_layers > current_layers and mask_solid_arr is not None:
            non_override = mask_solid_arr & (~combined_override_mask)
            if np.any(non_override) and is_material_archive:
                _recalc_matched_rgb_for_padded_pixels(
                    updated_rgb=updated_rgb,
                    material_matrix=material_matrix,
                    non_override_mask=non_override,
                    session_data=session_data,
                    layer_height_mm=float(request.layer_height_mm),
                    substrate=str(
                        cache.get("material_substrate")
                        or session_data.get("material_substrate")
                        or "white"
                    ),
                )

        if dynamic_manual_recipe is not None:
            target_rgb_map = cache.get("quantized_image")
            if (
                not isinstance(target_rgb_map, np.ndarray)
                or target_rgb_map.shape != updated_rgb.shape
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Dynamic target RGB map is unavailable. "
                        "Re-run preview."
                    ),
                )
            updated_target_map = np.asarray(
                target_rgb_map,
                dtype=np.uint8,
            ).copy()
            updated_target_map[combined_override_mask] = predicted_rgb
            cache["quantized_image"] = updated_target_map
            dynamic_info = cache.get("material_dynamic_layer_info")
            if isinstance(dynamic_info, dict):
                dynamic_info = deepcopy(dynamic_info)
                colors = dynamic_info.get("colors")
                solid_mask = np.asarray(cache.get("mask_solid"), dtype=bool)
                if solid_mask.shape != updated_target_map.shape[:2]:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Dynamic printable mask is inconsistent. "
                        "Re-run preview."
                        ),
                    )
                manual_mask = np.zeros(solid_mask.shape, dtype=bool)
                resolver_session_data = dict(session_data)
                resolver_session_data[RECIPE_OVERRIDE_APPLIED_MASKS_KEY] = (
                    applied_override_masks
                )
                try:
                    resolved_existing_masks = resolve_recipe_override_masks(
                        resolver_session_data,
                        existing_overrides,
                        tuple(solid_mask.shape),
                    )
                except ValueError as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "Committed recipe override mask is missing or invalid. "
                            "Re-apply the color replacement, then try again."
                        ),
                    ) from exc
                for region_mask in resolved_existing_masks.values():
                    manual_mask |= region_mask
                manual_mask |= combined_override_mask & solid_mask
                automatic_mask = solid_mask & ~manual_mask
                dynamic_info["benefit_curve"] = (
                    recompute_dynamic_material_benefit_curve(
                        colors if isinstance(colors, list) else [],
                        updated_target_map,
                        automatic_mask,
                    )
                )
                dynamic_info["benefit_curve_scope"] = "automatic_pixels"
                dynamic_info["benefit_curve_pixel_count"] = int(
                    np.count_nonzero(automatic_mask)
                )
                cache["material_dynamic_layer_info"] = dynamic_info

        cache["matched_rgb"] = updated_rgb
        cache["material_matrix"] = material_matrix
        cache["color_layers"] = int(material_matrix.shape[2])
        cache["layer_height_mm"] = float(request.layer_height_mm)
        cache["lut_metadata"] = metadata
        cache["lut_match_info"] = {
            "match_mode": match_mode,
            "runtime_mode_key": runtime_mode_key,
            "override": True,
            "source": prediction_source,
        }

        # Persist the per-region virtual materials alongside the recipe so the
        # generate endpoint can rebuild the extended palette for the 3MF
        # pipeline even in a fresh worker process. Use plain dicts (not
        # pydantic models) so the session store stays JSON-serialisable.
        # 把 per-region 的虚拟耗材和 recipe 一并持久化到会话里，让 generate
        # 端点在新 worker 进程里也能重建扩展调色板；存 dict 保证 JSON 可序列化。
        virtual_materials_payload = (
            [
                {"name": material.name, "hex": material.hex}
                for material in virtual_materials
            ]
            if virtual_materials
            else None
        )
        existing_overrides.extend(
            {
                "region_id": region_id,
                "recipe": list(request.recipe),
                "layer_order": request.layer_order,
                "color_layers": (
                    int(dynamic_manual_recipe["actual_layer_count"])
                    if dynamic_manual_recipe is not None
                    else int(material_matrix.shape[2])
                ),
                "layer_height_mm": float(request.layer_height_mm),
                **(
                    {
                        "actual_recipe_top_to_bottom": list(
                            dynamic_manual_recipe[
                                "actual_recipe_top_to_bottom"
                            ]
                        ),
                        "print_recipe_top_to_bottom": list(
                            dynamic_manual_recipe[
                                "print_recipe_top_to_bottom"
                            ]
                        ),
                        "actual_layer_count": int(
                            dynamic_manual_recipe["actual_layer_count"]
                        ),
                        "padding_layer_count": int(
                            dynamic_manual_recipe["padding_layer_count"]
                        ),
                    }
                    if dynamic_manual_recipe is not None
                    else {}
                ),
                **(
                    {"virtual_materials": virtual_materials_payload}
                    if virtual_materials_payload
                    else {}
                ),
            }
            for region_id, _region_mask in region_mask_items
        )

        preview_bytes = _render_styled_preview_bytes(updated_rgb, cache)
        preview_id = registry.register_bytes(
            request.session_id,
            preview_bytes,
            "preview_recipe_override.png",
        )
        persisted_cache = cache.commit(
            _dirty_array_fields(
                cache,
                "matched_rgb",
                "material_matrix",
                "quantized_image",
                "preview_rgba",
            ),
            metadata_fields={
                "color_layers",
                "layer_height_mm",
                "lut_metadata",
                "lut_match_info",
                "preview_colors",
                "slot_names",
                "color_conf",
                "material_dynamic_layer_info",
            },
        )
        cache_published = True
        store.put(request.session_id, "recipe_overrides", existing_overrides)
        store.put(request.session_id, "recipe_override_count", len(existing_overrides))
        session_data[RECIPE_OVERRIDE_APPLIED_MASKS_KEY] = applied_override_masks
        store.put(request.session_id, RECIPE_OVERRIDE_APPLIED_MASKS_KEY, applied_override_masks)
        _invalidate_and_prewarm_visible_region_cache(request.session_id, store, session_data, cache)
        history_flags = _push_history_checkpoint(
            request.session_id,
            store,
            session_data,
            history_checkpoint,
        )
        editor_content_revision = advance_editor_content_revision(
            request.session_id,
            store,
            session_data,
        )
        selection_response = _selection_after_content_commit(
            request.session_id,
            store,
            session_data,
            cache,
        )
        publish_editor_commit(
            request.session_id,
            store,
            session_data,
            operation_id=operation_id,
            editor_content_revision=editor_content_revision,
            selection_revision=get_selection_revision(session_data),
            result=_editor_commit_result(
                session_data,
                cache=cache,
                preview_url=f"/api/files/{preview_id}",
            ),
        )

        # Async GLB rebuild for the newly applied recipe override. Keeps
        # the override response fast; GLB arrives via /glb-status polling.
        # 配方覆盖也走异步 GLB 重建，保持响应延迟与其他 replace 端点一致。
        _schedule_glb_build_best_effort(
            request.session_id,
            store,
            registry,
            persisted_cache,
        )
        glb_url: str | None = None
    except HTTPException as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        raise
    except PreviewCacheRevisionConflict as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        if not cache_published:
            restore_session_state()
        _raise_replace_cache_conflict(
            exc,
            session_id=request.session_id,
            operation="apply_recipe_override",
        )
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        _mark_editor_commit_failed_if_unpublished(
            session_id=request.session_id,
            store=store,
            session_data=session_data,
            operation_id=operation_id,
            cache_published=cache_published,
            error_type=type(exc).__name__,
        )
        if not cache_published:
            restore_session_state()
        log.error(
            "Recipe override apply failed",
            extra={
                "event": "converter_apply_recipe_override_error",
                "session_id": request.session_id,
                "status_code": 422,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise HTTPException(
            status_code=422,
            detail=RECIPE_OVERRIDE_APPLY_FAILED_DETAIL,
        ) from exc
    finally:
        cache_context.__exit__(*sys.exc_info())

    log.info(
        "apply-recipe-override completed",
        extra={
            "event": "converter_apply_recipe_override_done",
            "session_id": request.session_id,
            "region_count": len(region_mask_items),
            "recipe_layer_count": len(request.recipe),
            "override_count": len(existing_overrides),
            "prediction_source": str(prediction_source or "unknown"),
        },
    )
    return RecipeOverrideApplyResponse(
        status="ok",
        message="Recipe override applied",
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=glb_url,
        rgb=[int(v) for v in predicted_rgb.tolist()],
        lab=predicted_lab,
        source=str(prediction_source or "unknown"),
        runtime_mode_key=(
            str(runtime_mode_key) if runtime_mode_key is not None else None
        ),
        override_count=len(existing_overrides),
        recipe_overrides=existing_overrides,
        **dynamic_material_result_from_cache(cache).model_dump(
            exclude={"operation_id", "editor_content_revision"}
        ),
        **history_flags,
        operation_id=operation_id,
        editor_content_revision=editor_content_revision,
        selection=selection_response,
    )


def _sample_region_recipe_top2bottom(
    material_matrix: np.ndarray,
    region_mask: np.ndarray,
) -> list[int] | None:
    """Sample the current per-layer material stack for a region mask.

    Reads the first solid pixel inside ``region_mask`` and returns its
    ``material_matrix`` stack in the pipeline's native ``Top2Bottom``
    convention (index 0 = viewing surface). Regions are connected components
    of a single ``matched_hex`` so every pixel in the mask shares the same
    stack; picking any one pixel is therefore correct and O(H·W) cheap.
    ``-1`` air sentinels (present in layers grown past the original depth
    outside ``mask_solid``) are stripped so the returned recipe contains
    only valid material indices — callers can use its length as the "real"
    solid-layer count.

    从区域掩码里采样一个实体像素，返回该像素在 ``material_matrix`` 中的
    堆叠（Top2Bottom，索引 0 = 观察面）。区域内每个像素共享同一个 matched_hex
    → 同一个堆叠，所以取任意一个即可。过滤 -1（空气哨兵，发生在 grown
    后不在 mask_solid 内的层），返回的 recipe 里只含合法材料索引，其长度
    就是该区域的真实实体层数。

    Returns:
        Recipe list or ``None`` when the mask is empty / shape mismatched /
        stack contains no solid layers.
    """
    if material_matrix.ndim != 3:
        return None
    mask_arr = np.asarray(region_mask, dtype=bool)
    if mask_arr.shape != material_matrix.shape[:2]:
        return None
    ys, xs = np.where(mask_arr)
    if ys.size == 0:
        return None
    stack = material_matrix[int(ys[0]), int(xs[0]), :]
    recipe = [int(v) for v in stack.tolist() if int(v) >= 0]
    if not recipe:
        return None
    return recipe


@router.post("/region-recipe", response_model=RegionRecipeResponse)
def region_recipe(
    request: RegionRecipeRequest,
    store: SessionStore = Depends(get_session_store),
) -> RegionRecipeResponse:
    """Return each requested region's current per-layer material stack.

    The Custom Recipe dialog calls this on open so the per-layer dropdowns
    pre-populate with the region's *actual* matched recipe instead of the
    all-White default. Without this the dialog silently overwrites the
    user's current stack on "Apply" if they only wanted to tweak a single
    layer — the user-reported "永远默认全白" bug.

    自定义配方对话框打开时调用，让逐层下拉预设为该区域的真实配方，而不
    是默认的全白。否则用户只想改一层也会把整个配方覆盖成白色，正是用户
    报告的 "永远默认全白" bug。

    ``material_matrix`` is stored in ``Top2Bottom`` convention (layer 0 =
    viewing surface) everywhere in the pipeline; we sample directly and
    reorder only when the caller asks for ``Bottom2Top``.

    Raises:
        HTTPException(404): Session not found.
        HTTPException(409): Missing preview cache, missing material_matrix,
            or no regions to sample.
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache_fields(
        session_data,
        fields={"material_matrix"},
    )

    material_matrix: np.ndarray | None = cache.get("material_matrix")
    if material_matrix is None:
        raise HTTPException(
            status_code=409,
            detail="Preview cache missing material_matrix. Preview again first.",
        )

    region_mask_items = _get_region_mask_items_for_ids(
        session_data, list(request.region_ids)
    )
    if not region_mask_items:
        raise HTTPException(
            status_code=409,
            detail="No selected regions available for recipe sampling.",
        )

    target_order = normalize_layer_order(request.layer_order)
    dynamic_enabled = bool(
        session_data.get("material_dynamic_layer_count_enabled", False)
    )
    layer_height_mm = float(
        cache.get("layer_height_mm") or session_data.get("material_layer_height_mm") or 0.08
    )

    entries: list[RegionRecipeEntry] = []
    for region_id, region_mask in region_mask_items:
        # ``material_matrix`` storage is always Top2Bottom (s03 docstring is
        # the canonical reference). Convert only when the caller asks for
        # the reversed view; empty samples degrade to an empty recipe so
        # the frontend can still fall back to its built-in default without
        # crashing on ``recipe[0]``.
        # material_matrix 恒为 Top2Bottom 存储，调用方要 Bottom2Top 时才反
        # 序；空样本退化为空 recipe，让前端能安全回退到默认配方。
        recipe_t2b = _sample_region_recipe_top2bottom(material_matrix, region_mask)
        if recipe_t2b is None:
            if dynamic_enabled:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Dynamic region print recipe is unavailable. "
                        "Re-run preview."
                    ),
                )
            entries.append(
                RegionRecipeEntry(
                    region_id=region_id,
                    recipe=[],
                    color_layers=int(material_matrix.shape[2]),
                    layer_height_mm=layer_height_mm,
                    layer_order=target_order,
                )
            )
            continue
        if dynamic_enabled:
            recipe_t2b = _resolve_dynamic_region_actual_recipe(
                session_data=session_data,
                cache=cache,
                region_id=region_id,
                print_recipe_top_to_bottom=recipe_t2b,
            )
        recipe_out = convert_recipe_between_orders(recipe_t2b, "Top2Bottom", target_order)
        entries.append(
            RegionRecipeEntry(
                region_id=region_id,
                recipe=recipe_out,
                color_layers=len(recipe_out),
                layer_height_mm=layer_height_mm,
                layer_order=target_order,
            )
        )

    log.info(
        "region-recipe completed",
        extra={
            "event": "converter_region_recipe_done",
            "session_id": request.session_id,
            "requested_region_count": len(request.region_ids),
            "resolved_region_count": len(entries),
            "layer_order": request.layer_order,
        },
    )
    return RegionRecipeResponse(
        status="ok",
        message="Region recipes resolved",
        recipes=entries,
    )


def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
    """Convert RGB array to CIELAB color space via OpenCV.
    通过 OpenCV 将 RGB 数组转换为 CIELAB 色彩空间。

    Args:
        rgb_array (np.ndarray): RGB values of shape (N, 3), dtype uint8. (RGB 值，形状 (N, 3))

    Returns:
        np.ndarray: LAB values of shape (N, 3), dtype float64. (LAB 值，形状 (N, 3))
    """
    rgb_2d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
    lab_2d = cv2.cvtColor(rgb_2d, cv2.COLOR_RGB2LAB)
    return lab_2d.reshape(-1, 3).astype(np.float64)


@router.post("/merge-colors")
def merge_colors(
    request: ColorMergePreviewRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> MergePreviewResponse:
    """Preview the effect of merging similar colors (synchronous).
    预览合并相似颜色的效果（同步执行）。

    This endpoint is intentionally kept synchronous (no process pool offload)
    because the computation is lightweight: it operates on the cached palette
    (typically 3-64 colors) and the cached matched_rgb array from the /preview
    step. Delta-E calculations involve small NumPy arrays (palette-sized, not
    image-sized), and pixel replacement uses simple mask operations.
    The heavy image processing was already completed in the /preview step.
    此端点有意保持同步执行（不卸载到进程池），因为计算量很小：
    仅对缓存的调色板（通常 3-64 色）和 /preview 步骤缓存的 matched_rgb 数组操作。
    Delta-E 计算涉及小型 NumPy 数组（调色板级别，非图像级别），
    像素替换使用简单的掩码操作。
    繁重的图像处理已在 /preview 步骤中完成。

    Args:
        request (ColorMergePreviewRequest): Merge parameters. (合并参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        MergePreviewResponse: Merge result with preview URL and quality metric.
                              (合并结果及预览 URL 和质量指标)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache_fields(
        session_data,
        fields={"matched_rgb", "mask_solid"},
    )

    try:
        # Extract palette from preview cache
        palette = extract_color_palette(cache)
        colors_before = len(palette)
        matched_rgb: np.ndarray = cache["matched_rgb"]
        merged_rgb = matched_rgb
        merge_map = {}
        quality = 100.0
        colors_after = colors_before
        message = "Color merging disabled"

        if request.merge_enable:
            # Build merge map using ColorMerger
            merger = ColorMerger(rgb_to_lab_func=_rgb_to_lab)
            merge_map = merger.build_merge_map(
                palette,
                threshold_percent=request.merge_threshold,
                max_distance=float(request.merge_max_distance),
            )

            # Apply merging to matched_rgb
            merged_rgb = merger.apply_color_merging(matched_rgb, merge_map)

            # Calculate quality metric
            merged_palette = extract_color_palette(
                {
                    "matched_rgb": merged_rgb,
                    "mask_solid": cache["mask_solid"],
                }
            )
            quality = merger.calculate_quality_metric(palette, merged_palette, merge_map)
            colors_after = len(merged_palette)
            message = f"Merged {len(merge_map)} colors"

        # Generate preview PNG
        preview_bytes = _image_to_png_bytes(merged_rgb)
        preview_id = registry.register_bytes(request.session_id, preview_bytes, "preview_merged.png")

        # Store merge_map in session
        store.put(request.session_id, "merge_map", merge_map)

    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Color merging")

    quality_metric = round(quality, 2)
    log.info(
        "merge-colors completed",
        extra={
            "event": "converter_merge_colors_done",
            "session_id": request.session_id,
            "merge_enabled": request.merge_enable,
            "colors_before": colors_before,
            "colors_after": colors_after,
            "merge_map_count": len(merge_map),
            "quality_metric": quality_metric,
        },
    )
    return MergePreviewResponse(
        status="ok",
        message=message,
        preview_url=f"/api/files/{preview_id}",
        merge_map=merge_map,
        quality_metric=quality_metric,
        colors_before=colors_before,
        colors_after=colors_after,
    )


# ---------------------------------------------------------------------------
# Cleanup intermediate files after download
# ---------------------------------------------------------------------------
