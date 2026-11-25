"""Vectorizer domain API router.
Vectorizer 领域 API 路由模块。

Provides endpoints for image-to-SVG vectorization using
the neroued_vectorizer library.
提供基于 neroued_vectorizer 库的图像转 SVG 矢量化端点。
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from api.dependencies import get_file_registry, get_worker_pool
from api.file_bridge import ensure_png_tempfile
from api.file_registry import FileRegistry
from api.schemas.vectorizer import (
    VectorizeDefaultsResponse,
    VectorizeParams,
    VectorizeResponse,
)
from api.worker_pool import WorkerPoolManager
from api.workers.vectorizer_workers import worker_vectorize
from api.structured_logging import get_logger

router = APIRouter(prefix="/api/vectorize", tags=["Vectorizer"])
VECTORIZER_OUTPUT_TTL_SECONDS = 1200
VECTORIZER_FAILURE_DETAIL = "Vectorization failed. Check server logs for details."
VECTORIZER_OUTPUT_FAILURE_DETAIL = (
    "Vectorization output could not be prepared. Check server logs for details."
)
VECTORIZER_PARAMS_JSON_DETAIL = (
    "Invalid vectorizer parameters JSON. Check the form value and try again."
)
_VECTORIZER_BOUNDARY_ERRORS: tuple[type[Exception], ...] = (
    ValueError,
    TypeError,
    KeyError,
    OSError,
    RuntimeError,
)
log = get_logger(__name__)


def _sanitize_vectorizer_validation_errors(
    exc: ValidationError,
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for error in exc.errors():
        detail: dict[str, Any] = {}
        loc = error.get("loc")
        if isinstance(loc, (list, tuple)):
            detail["loc"] = list(loc)
        message = error.get("msg")
        if isinstance(message, str):
            detail["msg"] = message
        error_type = error.get("type")
        if isinstance(error_type, str):
            detail["type"] = error_type
        if detail:
            sanitized.append(detail)
    return sanitized or [
        {
            "msg": "Vectorizer parameters are invalid.",
            "type": "value_error",
        }
    ]


def _cleanup_vectorize_temp_paths(*paths: str | None) -> None:
    """Best-effort cleanup for vectorize files without registry ownership."""

    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError as exc:
            log.warning(
                "Failed to clean vectorize temp file",
                extra={
                    "event": "vectorize_temp_cleanup_failed",
                    "temp_path": path,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )


def _palette_for_response(palette: object) -> list[str]:
    """Normalize worker palette entries to response hex strings."""

    if not isinstance(palette, list):
        return []
    normalized: list[str] = []
    for entry in palette:
        if isinstance(entry, str):
            normalized.append(entry)
            continue
        try:
            r, g, b = entry
            normalized.append(f"#{int(r):02x}{int(g):02x}{int(b):02x}")
        except (TypeError, ValueError):
            normalized.append(str(entry))
    return normalized


def _log_vectorize_failure(stage: str, exc: Exception) -> None:
    log.exception(
        "Vectorization failed",
        extra={
            "event": "vectorize_image_failed",
            "stage": stage,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
    )


@router.get("/defaults")
def vectorize_defaults() -> VectorizeDefaultsResponse:
    """Return default vectorization parameters.
    返回默认矢量化参数。
    """
    return VectorizeDefaultsResponse()


@router.post("")
async def vectorize_image(
    image: UploadFile = File(...),
    params: str = Form("{}"),
    pool: WorkerPoolManager = Depends(get_worker_pool),
    registry: FileRegistry = Depends(get_file_registry),
) -> VectorizeResponse:
    """Vectorize an uploaded image to SVG.
    将上传的图像矢量化为 SVG。

    Accepts a multipart form with an image file and a JSON string
    of vectorization parameters. Runs the CPU-intensive vectorization
    in a worker process and returns the SVG download URL with statistics.
    接受包含图像文件和矢量化参数 JSON 字符串的 multipart 表单。
    在工作进程中运行 CPU 密集型矢量化，返回 SVG 下载 URL 和统计信息。

    Args:
        image: Uploaded image file. (上传的图像文件)
        params: JSON-encoded VectorizeParams. (JSON 编码的矢量化参数)
        pool: Worker pool dependency. (工作进程池)
        registry: File registry dependency. (文件注册表)

    Returns:
        VectorizeResponse with SVG URL and statistics. (包含 SVG URL 和统计信息的响应)
    """
    import json

    try:
        params_dict = json.loads(params)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=VECTORIZER_PARAMS_JSON_DETAIL) from e
    if not isinstance(params_dict, dict):
        raise HTTPException(status_code=422, detail="params must be a JSON object")

    try:
        validated = VectorizeParams(**params_dict)
    except ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail=_sanitize_vectorizer_validation_errors(e),
        ) from e
    params_clean = validated.model_dump()

    image_path: str | None = None
    svg_path: str | None = None
    svg_registered = False
    try:
        image_path = await ensure_png_tempfile(image)

        try:
            result = await pool.submit(
                worker_vectorize, image_path, params_clean, macos_runtime="neroued_vectorizer",
            )
        except _VECTORIZER_BOUNDARY_ERRORS as e:
            _log_vectorize_failure("worker", e)
            raise HTTPException(
                status_code=500,
                detail=VECTORIZER_FAILURE_DETAIL,
            ) from e

        try:
            svg_path_value = result["svg_path"]
            if not isinstance(svg_path_value, str) or not svg_path_value:
                raise ValueError("worker result missing svg_path")
            svg_path = svg_path_value
            num_shapes = int(result["num_shapes"])
            num_colors = int(result["num_colors"])
            width = int(result["width"])
            height = int(result["height"])
            palette = result["palette"]
        except _VECTORIZER_BOUNDARY_ERRORS as exc:
            _log_vectorize_failure("worker_result", exc)
            raise HTTPException(
                status_code=500,
                detail=VECTORIZER_FAILURE_DETAIL,
            ) from exc

        try:
            svg_file_id = registry.register_path(
                str(uuid.uuid4()),
                svg_path,
                "output.svg",
                ttl_seconds=VECTORIZER_OUTPUT_TTL_SECONDS,
            )
        except _VECTORIZER_BOUNDARY_ERRORS as exc:
            _log_vectorize_failure("register_output", exc)
            raise HTTPException(
                status_code=500,
                detail=VECTORIZER_OUTPUT_FAILURE_DETAIL,
            ) from exc
        svg_registered = True
        palette_size = len(palette) if isinstance(palette, list) else 0

        log.info(
            "Image vectorized",
            extra={
                "event": "vectorize_image_done",
                "svg_file_id": svg_file_id,
                "num_shapes": num_shapes,
                "num_colors": num_colors,
                "width": width,
                "height": height,
                "palette_size": palette_size,
            },
        )

        return VectorizeResponse(
            status="ok",
            message=f"Vectorized: {num_shapes} shapes, {num_colors} colors",
            svg_url=f"/api/files/{svg_file_id}",
            width=width,
            height=height,
            num_shapes=num_shapes,
            num_colors=num_colors,
            palette=_palette_for_response(palette),
        )
    finally:
        _cleanup_vectorize_temp_paths(
            image_path,
            None if svg_registered else svg_path,
        )
