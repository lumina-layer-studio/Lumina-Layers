"""Calibration domain API router.
Calibration 领域 API 路由模块。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_file_registry
from api.file_bridge import pil_to_png_bytes
from api.file_registry import FileRegistry
from api.schemas.calibration import CalibrationGenerateRequest
from api.schemas.responses import CalibrationResponse
from core.calibration import (
    generate_5color_extended_batch_zip,
    generate_8color_batch_zip,
    generate_bw_calibration_board,
    generate_calibration_board,
    generate_smart_board,
)

router = APIRouter(prefix="/api/calibration", tags=["Calibration"])


def _handle_core_error(e: Exception, context: str) -> None:
    """将 core 模块异常转换为 HTTP 500 错误。"""
    print(f"[API] {context} error: {e}")
    raise HTTPException(status_code=500, detail=f"{context} failed: {str(e)}")


@router.post("/generate")
def calibration_generate(
    request: CalibrationGenerateRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> CalibrationResponse:
    """Generate a printable calibration board.
    生成可打印的校准板。
    """
    mode = request.color_mode.value
    try:
        if mode == "BW (Black & White)":
            path, preview_img, status = generate_bw_calibration_board(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_color=request.backing.value,
            )
        elif mode in ("4-Color", "CMYW", "RYBW"):
            path, preview_img, status = generate_calibration_board(
                color_mode=mode if mode in ("CMYW", "RYBW") else "RYBW",
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_color=request.backing.value,
            )
        elif mode == "6-Color (Smart 1296)":
            path, preview_img, status = generate_smart_board(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
            )
        elif mode == "8-Color Max":
            path, preview_img, status = generate_8color_batch_zip()
        elif mode == "5-Color Extended (1444)":
            path, preview_img, status = generate_5color_extended_batch_zip(
                float(request.block_size), float(request.gap)
            )
        else:
            raise HTTPException(
                status_code=422, detail=f"Unsupported color mode: {mode}"
            )
    except HTTPException:
        raise
    except Exception as e:
        _handle_core_error(e, "Calibration generation")

    # Register files via FileRegistry
    sid = "calibration"  # Stateless endpoint uses fixed session identifier
    download_id = registry.register_path(sid, path)
    preview_bytes = pil_to_png_bytes(preview_img)
    preview_id = registry.register_bytes(sid, preview_bytes, "preview.png")

    return CalibrationResponse(
        status="ok",
        message=status,
        download_url=f"/api/files/{download_id}",
        preview_url=f"/api/files/{preview_id}",
    )
