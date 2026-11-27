"""Calibration domain API router.
Calibration 领域 API 路由模块。
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_file_registry
from api.errors import to_http_exception
from api.export_device_validation import validate_export_device_selection
from api.file_bridge import pil_to_png_bytes
from api.file_registry import FileRegistry
from api.schemas.calibration import CalibrationGenerateRequest
from api.schemas.responses import CalibrationResponse, SingleStageKitResponse
from api.schemas.single_stage import SingleStageKitGenerateRequest
from api.structured_logging import get_logger, get_request_id
from config import PaletteEntry
from core.calibration import (
    generate_5color_extended_batch_zip,
    generate_8color_batch_zip,
    generate_8color_full_batch_zip,
    generate_bw_calibration_board,
    generate_calibration_board,
    generate_smart_board,
    generate_smart_board_rybw,
)
from core.errors import CoreError, CoreValidationError
from core.single_stage import generate_single_stage_kit
from utils.bambu_3mf_writer import read_wipe_tower_placement_warnings

router = APIRouter(prefix="/api/calibration", tags=["Calibration"])
STATELESS_EXPORT_TTL_SECONDS = 8 * 60 * 60
CALIBRATION_GENERATION_FAILED_DETAIL = (
    "Calibration board could not be generated. "
    "Check calibration settings and try again."
)
CALIBRATION_OUTPUT_PREPARATION_FAILED_DETAIL = (
    "Calibration board output could not be prepared. Please try again."
)
SINGLE_STAGE_KIT_GENERATION_FAILED_DETAIL = (
    "Single-stage calibration kit could not be generated. "
    "Check material and device settings and try again."
)
SINGLE_STAGE_KIT_OUTPUT_PREPARATION_FAILED_DETAIL = (
    "Single-stage calibration kit output could not be prepared. Please try again."
)
log = get_logger(__name__)


def _remove_generated_path(path: str | None) -> None:
    """Best-effort delete for route-owned generated exports."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _rollback_stateless_export_registration(
    registry: FileRegistry,
    *,
    file_ids: list[str | None],
    generated_paths: list[str | None],
) -> None:
    """Best-effort cleanup for failed multi-file stateless exports.
    多文件无状态导出失败时，尽力回滚已注册和未注册的生成文件。
    """
    for file_id in file_ids:
        if not file_id:
            continue
        try:
            registry.cleanup_file(file_id)
        except (OSError, RuntimeError, ValueError):
            pass
    for path in generated_paths:
        _remove_generated_path(path)


def _handle_core_error(
    e: Exception,
    *,
    context: str,
    public_detail: str,
) -> None:
    """Map core exceptions to sanitized HTTP 500 errors.
    将 core 模块异常转换为脱敏的 HTTP 500 错误。
    """
    log.error(
        "Calibration core operation failed",
        extra={
            "event": "calibration_core_operation_failed",
            "context": context,
            "error_type": type(e).__name__,
            "error_message": str(e),
        },
    )
    raise HTTPException(status_code=500, detail=public_detail)


def _handle_output_preparation_error(
    e: Exception,
    *,
    context: str,
    public_detail: str,
) -> None:
    """Map FileRegistry/export handoff failures to readable HTTP errors.
    将 FileRegistry / 导出交接失败转换为可读的 HTTP 错误。
    """
    log.error(
        "Calibration output preparation failed",
        extra={
            "event": "calibration_output_preparation_failed",
            "context": context,
            "error_type": type(e).__name__,
            "error_message": str(e),
        },
    )
    raise HTTPException(status_code=500, detail=public_detail)


def _log_optional_preview_registration_failure(
    e: Exception,
    *,
    context: str,
    export_ids: list[str | None],
) -> None:
    """Record a degraded optional preview without failing the export."""
    log.warning(
        "Calibration optional preview registration failed",
        extra={
            "event": "calibration_preview_registration_failed",
            "context": context,
            "export_ids": [file_id for file_id in export_ids if file_id],
            "error_type": type(e).__name__,
            "error_message": str(e),
        },
    )


def _new_stateless_export_sid(prefix: str) -> str:
    """Create a per-request registry owner id for stateless TTL exports."""

    request_id = get_request_id()
    unique_suffix = uuid.uuid4().hex
    if request_id:
        return f"{prefix}:{request_id}:{unique_suffix}"
    return f"{prefix}:{unique_suffix}"


@router.post("/generate")
def calibration_generate(
    request: CalibrationGenerateRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> CalibrationResponse:
    """Generate a printable calibration board.
    生成可打印的校准板。
    """
    validate_export_device_selection(
        printer_id=request.printer_id,
        slicer=request.slicer,
        nozzle_size=request.nozzle_size,
        device_profile_id=request.device_profile_id,
        build_plate_id=request.build_plate_id,
        custom_3mf_template_id=request.custom_3mf_template_id,
    )
    mode = request.color_mode.value
    backing_thickness_mm = float(request.backing_thickness)
    device_kwargs = {
        "printer_id": request.printer_id,
        "slicer": request.slicer,
        "nozzle_size": request.nozzle_size,
        "device_profile_id": request.device_profile_id,
        "build_plate_id": request.build_plate_id,
    }
    try:
        if mode == "BW (Black & White)":
            path, preview_imgs, status = generate_bw_calibration_board(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_color="White",
                backing_thickness_mm=backing_thickness_mm,
                **device_kwargs,
            )
        elif mode == "4-Color (RYBW)":
            path, preview_imgs, status = generate_calibration_board(
                color_mode="RYBW",
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_color="White",
                backing_thickness_mm=backing_thickness_mm,
                **device_kwargs,
            )
        elif mode == "4-Color (CMYW)":
            path, preview_imgs, status = generate_calibration_board(
                color_mode="CMYW",
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_color="White",
                backing_thickness_mm=backing_thickness_mm,
                **device_kwargs,
            )
        elif mode == "6-Color (CMYWGK 1296)":
            path, preview_imgs, status = generate_smart_board(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_thickness_mm=backing_thickness_mm,
                **device_kwargs,
            )
        elif mode == "6-Color (RYBWGK 1296)":
            path, preview_imgs, status = generate_smart_board_rybw(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_thickness_mm=backing_thickness_mm,
                **device_kwargs,
            )
        elif mode == "8-Color Max":
            if request.eight_color_full_export:
                path, preview_imgs, status = generate_8color_full_batch_zip(
                    block_size_mm=float(request.block_size),
                    gap_mm=request.gap,
                    backing_thickness_mm=backing_thickness_mm,
                    **device_kwargs,
                )
            else:
                path, preview_imgs, status = generate_8color_batch_zip(
                    block_size_mm=float(request.block_size),
                    gap_mm=request.gap,
                    backing_thickness_mm=backing_thickness_mm,
                    **device_kwargs,
                )
        elif mode == "5-Color Extended (1444)":
            path, preview_imgs, status = generate_5color_extended_batch_zip(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_thickness_mm=backing_thickness_mm,
                **device_kwargs,
            )
        else:
            raise HTTPException(
                status_code=422, detail=f"Unsupported color mode: {mode}"
            )
    except HTTPException:
        raise
    except CoreValidationError as e:
        raise to_http_exception(e, "Calibration generation") from e
    except (CoreError, OSError, RuntimeError, TypeError, ValueError) as e:
        _handle_core_error(
            e,
            context="Calibration generation",
            public_detail=CALIBRATION_GENERATION_FAILED_DETAIL,
        )

    # Register files via FileRegistry
    sid = _new_stateless_export_sid("calibration")
    preview_url = None
    preview_id = None
    layer_urls = []
    download_id = None
    try:
        placement_warnings = read_wipe_tower_placement_warnings(path)
        download_id = registry.register_path(
            sid,
            path,
            ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as e:
        _rollback_stateless_export_registration(
            registry,
            file_ids=[download_id],
            generated_paths=[path],
        )
        _handle_output_preparation_error(
            e,
            context="Calibration output registration",
            public_detail=CALIBRATION_OUTPUT_PREPARATION_FAILED_DETAIL,
        )

    preview_file_ids: list[str | None] = []
    try:
        if isinstance(preview_imgs, list) and len(preview_imgs) > 0:
            main_preview = preview_imgs[0]
            preview_id = registry.register_bytes(
                sid,
                pil_to_png_bytes(main_preview),
                "preview.png",
                ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
            )
            preview_file_ids.append(preview_id)
            preview_url = f"/api/files/{preview_id}"

            for idx, layer_img in enumerate(preview_imgs[1:]):
                layer_id = registry.register_bytes(
                    sid,
                    pil_to_png_bytes(layer_img),
                    f"layer_{idx+1}.png",
                    ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
                )
                preview_file_ids.append(layer_id)
                layer_urls.append(f"/api/files/{layer_id}")
        elif preview_imgs is not None:
            # Fallback for single image
            preview_id = registry.register_bytes(
                sid,
                pil_to_png_bytes(preview_imgs),
                "preview.png",
                ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
            )
            preview_file_ids.append(preview_id)
            preview_url = f"/api/files/{preview_id}"
    except (OSError, RuntimeError, TypeError, ValueError) as e:
        _rollback_stateless_export_registration(
            registry,
            file_ids=preview_file_ids,
            generated_paths=[],
        )
        preview_url = None
        preview_id = None
        layer_urls = []
        _log_optional_preview_registration_failure(
            e,
            context="Calibration preview registration",
            export_ids=[download_id],
        )

    backing_color_for_log = (
        "White"
        if mode in {"BW (Black & White)", "4-Color (RYBW)", "4-Color (CMYW)"}
        else "n/a"
    )

    log.info(
        "Calibration board generated",
        extra={
            "event": "calibration_generate_done",
            "color_mode": mode,
            "download_id": download_id,
            "preview_id": preview_id,
            "block_size_mm": float(request.block_size),
            "gap_mm": request.gap,
            "backing_color": backing_color_for_log,
            "printer_id": request.printer_id,
            "slicer": request.slicer,
            "nozzle_size": request.nozzle_size,
        },
    )

    return CalibrationResponse(
        status="ok",
        message=status,
        download_url=f"/api/files/{download_id}",
        preview_url=preview_url,
        layer_urls=layer_urls if layer_urls else None,
        threemf_disk_path=None,
        warnings=placement_warnings,
    )


@router.post("/generate-single-stage-kit")
def calibration_generate_single_stage_kit(
    request: SingleStageKitGenerateRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> SingleStageKitResponse:
    """Generate a ChromaPrint3D-compatible single-stage kit."""
    validate_export_device_selection(
        printer_id=request.printer_id,
        slicer=request.slicer,
        nozzle_size=request.nozzle_size,
        device_profile_id=request.device_profile_id,
        build_plate_id=request.build_plate_id,
        custom_3mf_template_id=request.custom_3mf_template_id,
    )
    try:
        palette = [
            PaletteEntry(
                color=entry.color,
                material=entry.material,
                hex_color=entry.hex_color,
                color_name=entry.color_name,
            )
            for entry in request.palette
        ]
        result = generate_single_stage_kit(
            palette=palette,
            substrate_id=request.substrate_id,
            substrate_display_name=request.substrate_display_name,
            material_default=request.material_default,
            layer_height_mm=request.layer_height_mm,
            printer_id=request.printer_id,
            slicer=request.slicer,
            nozzle_size=request.nozzle_size,
            device_profile_id=request.device_profile_id,
            build_plate_id=request.build_plate_id,
        )
    except CoreValidationError as e:
        raise to_http_exception(e, "Single-stage kit generation") from e
    except (CoreError, OSError, RuntimeError, TypeError, ValueError) as e:
        _handle_core_error(
            e,
            context="Single-stage kit generation",
            public_detail=SINGLE_STAGE_KIT_GENERATION_FAILED_DETAIL,
        )

    sid = _new_stateless_export_sid("single-stage-kit")
    kit_id = None
    manifest_id = None
    try:
        kit_id = registry.register_path(
            sid,
            result.zip_path,
            ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
        )
        manifest_id = registry.register_path(
            sid,
            result.manifest_path,
            ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as e:
        _rollback_stateless_export_registration(
            registry,
            file_ids=[kit_id, manifest_id],
            generated_paths=[result.zip_path, result.manifest_path],
        )
        _handle_output_preparation_error(
            e,
            context="Single-stage kit output registration",
            public_detail=SINGLE_STAGE_KIT_OUTPUT_PREPARATION_FAILED_DETAIL,
        )

    preview_id = None
    try:
        preview_id = registry.register_bytes(
            sid,
            pil_to_png_bytes(result.preview_image),
            "single_stage_preview.png",
            ttl_seconds=STATELESS_EXPORT_TTL_SECONDS,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as e:
        _rollback_stateless_export_registration(
            registry,
            file_ids=[preview_id],
            generated_paths=[],
        )
        preview_id = None
        _log_optional_preview_registration_failure(
            e,
            context="Single-stage kit preview registration",
            export_ids=[kit_id, manifest_id],
        )
    log.info(
        "Single-stage calibration kit generated",
        extra={
            "event": "calibration_generate_single_stage_kit_done",
            "kit_id": kit_id,
            "manifest_id": manifest_id,
            "preview_id": preview_id,
            "palette_size": len(request.palette),
            "substrate_id": request.substrate_id,
            "layer_height_mm": request.layer_height_mm,
            "jobs_count": len(result.jobs),
        },
    )
    return SingleStageKitResponse(
        status="ok",
        message=result.message,
        kit_download_url=f"/api/files/{kit_id}",
        preview_url=f"/api/files/{preview_id}" if preview_id else None,
        manifest_url=f"/api/files/{manifest_id}",
        jobs=result.jobs,
    )
