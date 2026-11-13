"""Bounded preview resource helpers.
小尺寸预览资源辅助函数。
"""

from __future__ import annotations

import os
import tempfile
import uuid
from contextlib import suppress
from dataclasses import dataclass

import cv2
import numpy as np
from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from api.colorchecker_artifacts import (
    COLORCHECKER_FULL_PENDING_PURPOSE,
    COLORCHECKER_FULL_PURPOSE,
    COLORCHECKER_SOURCE_PURPOSE,
    resolve_colorchecker_source_file,
)
from api.file_registry import FileRegistry
from api.structured_logging import get_logger
from core.preview_sizing import preview_dimensions as _preview_dimensions
from config import (
    COLORCHECKER_TEMP_TTL_SECONDS,
    IMAGE_PREVIEW_JPEG_QUALITY,
    IMAGE_PREVIEW_MAX_EDGE,
    TEMP_DIR,
)

PREVIEW_CONTEXT_COLORCHECKER = "colorchecker"
PREVIEW_PUBLIC_PURPOSE = "bounded_preview"
_PREVIEW_OWNER_SESSION_PREFIX = "bounded-preview-owner:"
log = get_logger(__name__)

_SUPPORTED_CONTEXTS = {PREVIEW_CONTEXT_COLORCHECKER}
_COLORCHECKER_STANDARD_MIME_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/heic": ".heic",
    "image/heic-sequence": ".heic",
    "image/heif": ".heif",
    "image/heif-sequence": ".heif",
    "image/tiff": ".tif",
    "image/x-tiff": ".tif",
}
_COLORCHECKER_STANDARD_SUFFIXES = set(_COLORCHECKER_STANDARD_MIME_SUFFIXES.values()) | {
    ".jpeg",
    ".tiff",
}
_COLORCHECKER_PREVIEW_ROLES = (
    None,
    "source",
    "warp",
    "calibrated",
    "overlay",
    "artifact",
)
_COLORCHECKER_PREVIEW_UNREADABLE_DETAIL = (
    "ColorChecker preview is unavailable or unreadable. "
    "Re-run ColorChecker calibration and try again."
)
_COLORCHECKER_PREVIEW_GENERATION_FAILED_DETAIL = (
    "ColorChecker preview could not be generated from this image. "
    "Choose a supported image file and try again."
)
_COLORCHECKER_PREVIEW_SERVICE_UNAVAILABLE_DETAIL = (
    "ColorChecker preview service is unavailable. "
    "Check the server ColorChecker dependencies and try again."
)
_COLORCHECKER_PREVIEW_PREPARATION_FAILED_DETAIL = (
    "ColorChecker preview could not be prepared. Please try again."
)
_PREVIEW_ARTIFACT_UNREADABLE_DETAIL = (
    "Preview artifact is unavailable or unreadable. "
    "Re-run the previous step and try again."
)


@dataclass(frozen=True)
class PreviewResourceRegistration:
    """Registered private source plus its bounded preview."""

    resource_id: str
    preview_id: str
    preview_url: str
    full_width: int
    full_height: int
    preview_width: int
    preview_height: int
    source_type: str


@dataclass(frozen=True)
class PreviewArtifactRegistration:
    """Registered bounded preview for an existing server-side artifact."""

    preview_id: str
    preview_url: str
    preview_width: int
    preview_height: int


@dataclass(frozen=True)
class PreviewFileSnapshot:
    """In-memory copy of one validated public preview file.
    已校验公开预览文件的内存副本。
    """

    data: bytes
    preview_width: int
    preview_height: int


def validate_preview_context(context: str) -> str:
    """Validate a preview resource context.
    校验小预览资源上下文。
    """
    value = (context or "").strip().lower()
    if value not in _SUPPORTED_CONTEXTS:
        raise HTTPException(status_code=422, detail=f"Unsupported preview context: {context}")
    return value


def _write_all(fd: int, data: bytes) -> None:
    """Write all bytes to a raw file descriptor, retrying short writes."""
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("Failed to write preview upload chunk")
        offset += written


async def save_upload_to_tempfile(file: UploadFile) -> str:
    """Stream an uploaded image to a temporary file.
    以流式方式保存上传图像，避免长期保留上传字节。
    """
    suffix = os.path.splitext(file.filename or "")[1] or ".tmp"
    fd, path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            _write_all(fd, chunk)
    except Exception:
        os.close(fd)
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    os.close(fd)
    return path


def preview_dimensions(width: int, height: int) -> tuple[int, int]:
    """Return bounded preview dimensions for a full-size image."""
    return _preview_dimensions(width, height, max_edge=IMAGE_PREVIEW_MAX_EDGE)


def resize_bgr_for_preview(image_bgr: np.ndarray) -> np.ndarray:
    """Return a display copy constrained by preview config."""
    from core.colorchecker.image_io import image_to_uint8_display

    display = image_to_uint8_display(image_bgr)
    h, w = display.shape[:2]
    preview_w, preview_h = preview_dimensions(w, h)
    if preview_w == w and preview_h == h:
        return display
    return cv2.resize(display, (preview_w, preview_h), interpolation=cv2.INTER_AREA)


def encode_preview_jpeg(image_bgr: np.ndarray) -> tuple[bytes, int, int]:
    """Encode a bounded JPEG preview and return bytes plus dimensions."""
    from core.colorchecker.image_io import encode_jpeg_bytes

    preview = resize_bgr_for_preview(image_bgr)
    h, w = preview.shape[:2]
    return (
        encode_jpeg_bytes(preview, quality=int(IMAGE_PREVIEW_JPEG_QUALITY)),
        int(w),
        int(h),
    )


def register_preview_bytes(
    registry: FileRegistry,
    data: bytes,
    filename: str,
    *,
    ttl_seconds: int = COLORCHECKER_TEMP_TTL_SECONDS,
    owner_file_id: str | None = None,
    preview_role: str | None = None,
) -> str:
    """Register public bounded preview bytes."""
    return registry.register_bytes(
        _preview_owner_session_id(owner_file_id, preview_role=preview_role)
        if owner_file_id
        else f"preview:{uuid.uuid4()}",
        data,
        filename,
        ttl_seconds=ttl_seconds,
        is_public=True,
        purpose=PREVIEW_PUBLIC_PURPOSE,
    )


def register_preview_jpeg(
    registry: FileRegistry,
    image_bgr: np.ndarray,
    filename: str,
    *,
    ttl_seconds: int = COLORCHECKER_TEMP_TTL_SECONDS,
    owner_file_id: str | None = None,
    preview_role: str | None = None,
) -> PreviewArtifactRegistration:
    """Encode and register one bounded public JPEG preview."""
    preview_bytes, preview_w, preview_h = encode_preview_jpeg(image_bgr)
    preview_id = register_preview_bytes(
        registry,
        preview_bytes,
        filename,
        ttl_seconds=ttl_seconds,
        owner_file_id=owner_file_id,
        preview_role=preview_role,
    )
    return PreviewArtifactRegistration(
        preview_id=preview_id,
        preview_url=f"/api/files/{preview_id}",
        preview_width=preview_w,
        preview_height=preview_h,
    )


def colorchecker_source_registry_filename(
    file: UploadFile,
    source_path: str,
    source_type: str,
) -> str:
    """Return an internal filename that preserves ColorChecker type hints."""
    original_name = (file.filename or "").strip()
    content_type = (file.content_type or "").split(";", 1)[0].lower()
    suffix = os.path.splitext(original_name)[1].lower() if original_name else ""
    if source_type != "standard":
        return original_name or os.path.basename(source_path)
    if suffix in _COLORCHECKER_STANDARD_SUFFIXES:
        return original_name
    if suffix:
        from core.colorchecker.image_io import RAW_EXTENSIONS

        if suffix in RAW_EXTENSIONS:
            return original_name
    inferred_suffix = _COLORCHECKER_STANDARD_MIME_SUFFIXES.get(content_type)
    if inferred_suffix:
        root = os.path.splitext(original_name or os.path.basename(source_path))[0]
        return f"{root or 'preview-source'}{inferred_suffix}"
    return original_name or os.path.basename(source_path)


async def register_preview_resource_upload(
    registry: FileRegistry,
    file: UploadFile,
    *,
    context: str,
) -> PreviewResourceRegistration:
    """Register one private source resource and public bounded preview."""
    context = validate_preview_context(context)
    if context != PREVIEW_CONTEXT_COLORCHECKER:
        raise HTTPException(status_code=422, detail=f"Unsupported preview context: {context}")

    from core.colorchecker_adapter import (
        ColorCheckerCalibrationError,
        ColorCheckerUnavailableError,
        decode_colorchecker_file,
    )

    source_path: str | None = None
    resource_id: str | None = None
    preview_id: str | None = None
    try:
        source_path = await save_upload_to_tempfile(file)
        decoded = decode_colorchecker_file(
            source_path,
            file_name=file.filename or os.path.basename(source_path),
            mime_type=file.content_type or "application/octet-stream",
        )
        full_h, full_w = decoded.image_bgr.shape[:2]
        registry_filename = colorchecker_source_registry_filename(
            file,
            source_path,
            decoded.source_type,
        )
        resource_id = registry.register_path(
            f"preview-source:{context}:{uuid.uuid4()}",
            source_path,
            registry_filename,
            ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
            is_public=False,
            purpose=COLORCHECKER_SOURCE_PURPOSE,
        )
        source_path = None
        preview = register_preview_jpeg(
            registry,
            decoded.image_bgr,
            "preview_source.jpg",
            owner_file_id=resource_id,
            preview_role="source",
        )
        preview_id = preview.preview_id
        return PreviewResourceRegistration(
            resource_id=resource_id,
            preview_id=preview.preview_id,
            preview_url=preview.preview_url,
            full_width=int(full_w),
            full_height=int(full_h),
            preview_width=preview.preview_width,
            preview_height=preview.preview_height,
            source_type=str(decoded.source_type),
        )
    except ColorCheckerUnavailableError as exc:
        raise HTTPException(
            status_code=500,
            detail=_COLORCHECKER_PREVIEW_SERVICE_UNAVAILABLE_DETAIL,
        ) from exc
    except ColorCheckerCalibrationError as exc:
        raise HTTPException(
            status_code=422,
            detail=_COLORCHECKER_PREVIEW_GENERATION_FAILED_DETAIL,
        ) from exc
    except (cv2.error, OSError, RuntimeError, TypeError, ValueError) as exc:
        if resource_id:
            with suppress(OSError, RuntimeError, ValueError):
                registry.cleanup_file(resource_id)
        if preview_id:
            with suppress(OSError, RuntimeError, ValueError):
                registry.cleanup_file(preview_id)
        log.error(
            "ColorChecker preview resource preparation failed",
            extra={
                "event": "preview_resource_registration_failed",
                "context": context,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=_COLORCHECKER_PREVIEW_PREPARATION_FAILED_DETAIL,
        ) from exc
    finally:
        if source_path is not None:
            try:
                os.remove(source_path)
            except OSError:
                pass
        try:
            del decoded
        except UnboundLocalError:
            pass


def register_preview_for_artifact(
    registry: FileRegistry,
    *,
    context: str,
    resource_id: str,
) -> PreviewArtifactRegistration:
    """Generate a bounded public preview for a private resource/artifact."""
    context = validate_preview_context(context)
    if context != PREVIEW_CONTEXT_COLORCHECKER:
        raise HTTPException(status_code=422, detail=f"Unsupported preview context: {context}")
    entry = registry.get_entry(resource_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Preview resource not found or expired")
    purpose = entry.get("purpose")
    if purpose == COLORCHECKER_SOURCE_PURPOSE:
        from core.colorchecker_adapter import (
            ColorCheckerCalibrationError,
            ColorCheckerUnavailableError,
            decode_colorchecker_file,
        )

        path, filename = resolve_colorchecker_source_file(registry, resource_id)
        try:
            decoded = decode_colorchecker_file(
                path,
                file_name=filename,
                mime_type="application/octet-stream",
            )
        except ColorCheckerUnavailableError as exc:
            raise HTTPException(
                status_code=500,
                detail=_COLORCHECKER_PREVIEW_SERVICE_UNAVAILABLE_DETAIL,
            ) from exc
        except ColorCheckerCalibrationError as exc:
            raise HTTPException(
                status_code=422,
                detail=_COLORCHECKER_PREVIEW_GENERATION_FAILED_DETAIL,
            ) from exc
        return register_preview_jpeg(
            registry,
            decoded.image_bgr,
            "preview_source.jpg",
            owner_file_id=resource_id,
            preview_role="source",
        )

    if purpose in {COLORCHECKER_FULL_PENDING_PURPOSE, COLORCHECKER_FULL_PURPOSE}:
        if entry.get("is_public") is not False:
            raise HTTPException(status_code=404, detail="Preview resource not found or expired")
        resolved = registry.resolve(resource_id)
        if resolved is None:
            raise HTTPException(status_code=404, detail="Preview resource not found or expired")
        path, _filename = resolved
        try:
            with Image.open(path) as image:
                rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=_PREVIEW_ARTIFACT_UNREADABLE_DETAIL) from exc
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return register_preview_jpeg(
            registry,
            bgr,
            "preview_artifact.jpg",
            owner_file_id=resource_id,
            preview_role="artifact",
        )

    raise HTTPException(status_code=404, detail="Preview resource not found or expired")


def validate_public_preview_file(
    registry: FileRegistry,
    preview_file_id: str,
    *,
    owner_file_id: str | None = None,
    preview_role: str | None = None,
) -> tuple[str, int | None, int | None] | None:
    """Validate an existing bounded public preview and return URL/dimensions."""
    if not preview_file_id:
        return None
    entry = registry.get_entry(preview_file_id)
    if (
        entry is None
        or entry.get("is_public") is not True
        or entry.get("purpose") != PREVIEW_PUBLIC_PURPOSE
    ):
        return None
    if owner_file_id and entry.get("session_id") != _preview_owner_session_id(
        owner_file_id,
        preview_role=preview_role,
    ):
        return None
    resolved = registry.resolve(preview_file_id)
    if resolved is None:
        return None
    path, _filename = resolved
    width: int | None = None
    height: int | None = None
    try:
        with Image.open(path) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError):
        pass
    return f"/api/files/{preview_file_id}", width, height


def snapshot_public_preview_file(
    registry: FileRegistry,
    preview_file_id: str,
    *,
    owner_file_id: str | None = None,
    preview_role: str | None = None,
) -> PreviewFileSnapshot | None:
    """Copy one validated public preview into memory before owner cleanup.
    在 owner 被清理前，将已校验的公开预览复制到内存。
    """
    existing = validate_public_preview_file(
        registry,
        preview_file_id,
        owner_file_id=owner_file_id,
        preview_role=preview_role,
    )
    if existing is None:
        return None
    resolved = registry.resolve(preview_file_id)
    if resolved is None:
        return None
    path, _filename = resolved
    try:
        width = existing[1]
        height = existing[2]
        if width is None or height is None:
            with Image.open(path) as image:
                width, height = image.size
        with open(path, "rb") as preview_file:
            data = preview_file.read()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=_COLORCHECKER_PREVIEW_UNREADABLE_DETAIL,
        ) from exc
    return PreviewFileSnapshot(
        data=data,
        preview_width=int(width),
        preview_height=int(height),
    )


def cleanup_previews_for_owner(registry: FileRegistry, owner_file_id: str) -> int:
    """Delete public bounded previews attached to one private artifact.
    删除绑定到一个内部私有产物的小预览。
    """
    if not owner_file_id:
        return 0
    removed = 0
    for role in _COLORCHECKER_PREVIEW_ROLES:
        removed += registry.cleanup_session(
            _preview_owner_session_id(owner_file_id, preview_role=role)
        )
    return removed


def _preview_owner_session_id(
    owner_file_id: str,
    *,
    preview_role: str | None = None,
) -> str:
    suffix = f":role:{preview_role}" if preview_role else ""
    return f"{_PREVIEW_OWNER_SESSION_PREFIX}{owner_file_id}{suffix}"
