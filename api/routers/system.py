"""Lumina Studio API — System Management Router.
Lumina Studio API — 系统管理路由。

Provides cache cleanup utilities and the ``POST /api/system/clear-cache``
endpoint (endpoint registered in a later task).
提供缓存清理工具函数，以及 ``POST /api/system/clear-cache`` 端点
（端点在后续任务中注册）。
"""

import json
import os
import re
import uuid
import cv2
from collections.abc import Mapping
from contextlib import suppress
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from starlette.concurrency import run_in_threadpool

import config
from api.dependencies import get_file_registry, get_session_store
from api.file_bridge import ensure_png_tempfile, upload_to_tempfile
from api.file_registry import FileRegistry
from api.local_origin_guard import require_local_app_origin
from api.preview_resources import (
    register_preview_for_artifact,
    register_preview_resource_upload,
    validate_preview_context,
)
from api.schemas.system import (
    CacheCleanupDetails,
    ClearCacheResponse,
    ClearCacheResult,
    DeviceProfileInfo,
    PrinterInfo,
    PrinterListResponse,
    SaveSettingsResponse,
    SlicerInfo,
    SlicerListResponse,
    StatsResponse,
    UserSettings,
    UserSettingsResponse,
)
from api.session_store import SessionStore
from api.structured_logging import get_logger
from core.machine_registry import (
    resolve_installed_bed_model,
    resolve_machine_registry_root,
)
from core.heightmap_loader import HeightmapLoader

router = APIRouter(prefix="/api/system", tags=["System"])
log = get_logger(__name__)

CLEANABLE_EXTENSIONS: set[str] = {".3mf", ".glb", ".png", ".jpg", ".txt"}
PROTECTED_FILES: set[str] = {"lumina_stats.txt", "lumina_lut.json"}
EPHEMERAL_PREVIEW_TTL_SECONDS = 600
_HEIGHTMAP_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
_HEIGHTMAP_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/bmp", "image/tiff"}
_HEIGHTMAP_UNREADABLE_DETAIL = "Invalid or damaged heightmap image."
IMAGE_PREVIEW_PREPARATION_FAILED_DETAIL = (
    "Image preview could not be prepared. Please try again."
)
CLEAR_CACHE_FORBIDDEN_DETAIL = (
    "Cache cleanup is only available from the Lumina Studio local app."
)
_CLEAR_CACHE_DEFAULT_LOCAL_PORTS = frozenset({8000, 4174, 5174, 5173})
_CLEAR_CACHE_ALLOWED_ORIGINS_ENV = "LUMINA_CLEAR_CACHE_ALLOWED_ORIGINS"
_CLEAR_CACHE_ALLOWED_LOCAL_PORTS_ENV = "LUMINA_CLEAR_CACHE_ALLOWED_LOCAL_PORTS"
MACHINE_REGISTRY_ASSET_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


@router.get("/3mf-templates", dependencies=[Depends(require_local_app_origin)])
def list_custom_3mf_templates() -> dict:
    """List saved 3MF template metadata. 列出已保存的 3MF 模板信息。"""
    from core.custom_3mf_templates import list_templates

    return {"templates": list_templates()}


@router.post("/3mf-templates", dependencies=[Depends(require_local_app_origin)])
async def import_custom_3mf_template(
    file: UploadFile = File(...), name: str = Form(""), slicer: str | None = Form(None)
) -> dict:
    """Import printer settings from a 3MF. 从 3MF 导入打印机设置。"""
    from core.custom_3mf_templates import import_template

    try:
        metadata = await run_in_threadpool(
            import_template,
            await file.read(), name.strip() or Path(file.filename or "Template").stem,
            **({"slicer_hint": slicer} if slicer else {}),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info(
        "Custom 3MF template imported",
        extra={"event": "system_3mf_template_import_done", "template_id": metadata["id"]},
    )
    return metadata


@router.delete(
    "/3mf-templates/{template_id}", dependencies=[Depends(require_local_app_origin)]
)
def delete_custom_3mf_template(template_id: str) -> dict:
    """Delete a saved 3MF template. 删除已保存的 3MF 模板。"""
    from core.custom_3mf_templates import delete_template

    try:
        delete_template(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Custom 3MF template was not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info(
        "Custom 3MF template deleted",
        extra={"event": "system_3mf_template_delete_done", "template_id": template_id},
    )
    return {"status": "ok"}


def _normalize_host(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().strip("[]").rstrip(".").lower()
    return normalized or None


def _is_loopback_host(value: str | None) -> bool:
    host = _normalize_host(value)
    if host is None:
        return False
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _parse_port(raw_value: str) -> int | None:
    try:
        port = int(raw_value)
    except ValueError:
        return None
    if 1 <= port <= 65535:
        return port
    return None


def _clear_cache_allowed_local_ports() -> set[int]:
    ports = set(_CLEAR_CACHE_DEFAULT_LOCAL_PORTS)
    raw_ports = os.environ.get(_CLEAR_CACHE_ALLOWED_LOCAL_PORTS_ENV, "")
    for raw_port in raw_ports.split(","):
        port = _parse_port(raw_port.strip())
        if port is not None:
            ports.add(port)
    return ports


def _parse_host_header(value: str | None) -> tuple[str, int | None] | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = urlparse(f"//{value.strip()}")
        hostname = _normalize_host(parsed.hostname)
        port = parsed.port
    except ValueError:
        return None
    if hostname is None:
        return None
    return hostname, port


def _origin_host_for_key(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def _origin_default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _origin_key(
    *,
    scheme: str,
    host: str,
    port: int,
) -> str:
    normalized_host = _origin_host_for_key(_normalize_host(host) or host)
    default_port = _origin_default_port(scheme)
    if port == default_port:
        return f"{scheme}://{normalized_host}"
    return f"{scheme}://{normalized_host}:{port}"


def _parse_origin(value: str | None) -> tuple[str, int, str] | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = urlparse(value.strip())
        scheme = parsed.scheme.lower()
        hostname = _normalize_host(parsed.hostname)
        port = parsed.port
    except ValueError:
        return None
    if scheme not in {"http", "https"} or hostname is None:
        return None
    if parsed.params or parsed.query or parsed.fragment:
        return None
    if parsed.path not in {"", "/"}:
        return None
    resolved_port = port if port is not None else _origin_default_port(scheme)
    return hostname, resolved_port, _origin_key(
        scheme=scheme,
        host=hostname,
        port=resolved_port,
    )


def _clear_cache_allowed_origin_keys() -> set[str]:
    allowed: set[str] = set()
    raw_origins = os.environ.get(_CLEAR_CACHE_ALLOWED_ORIGINS_ENV, "")
    for raw_origin in raw_origins.split(","):
        parsed = _parse_origin(raw_origin)
        if parsed is None:
            continue
        _, _, origin_key = parsed
        allowed.add(origin_key)
    return allowed


def _is_trusted_clear_cache_request(request: Request) -> tuple[bool, str]:
    raw_origin = request.headers.get("origin")
    raw_host = request.headers.get("host")
    parsed_host = _parse_host_header(raw_host)
    if parsed_host is None:
        return False, "invalid_host"
    host, _host_port = parsed_host
    if not _is_loopback_host(host):
        return False, "untrusted_host"

    if raw_origin is None:
        return True, "no_origin"

    parsed_origin = _parse_origin(raw_origin)
    if parsed_origin is None:
        return False, "invalid_origin"

    origin_host, origin_port, origin_key_value = parsed_origin
    if origin_key_value in _clear_cache_allowed_origin_keys():
        return True, "explicit_origin_allowlist"

    if not _is_loopback_host(origin_host):
        return False, "untrusted_origin_host"
    if origin_port not in _clear_cache_allowed_local_ports():
        return False, "untrusted_origin_port"

    return True, "local_origin"


def _enforce_clear_cache_origin(request: Request) -> None:
    trusted, reason = _is_trusted_clear_cache_request(request)
    if trusted:
        return

    origin = request.headers.get("origin", "")
    host = request.headers.get("host", "")
    log.warning(
        "Cache cleanup blocked for untrusted request origin",
        extra={
            "event": "system_clear_cache_forbidden",
            "origin": origin,
            "host": host,
            "reason": reason,
            "error_type": "ForbiddenCacheCleanupOrigin",
            "error_message": CLEAR_CACHE_FORBIDDEN_DETAIL,
        },
    )
    raise HTTPException(status_code=403, detail=CLEAR_CACHE_FORBIDDEN_DETAIL)


def _try_load_machine_registry():
    """Load optional generated machine registry, returning None on absence/failure.
    加载可选的生成机器注册表；不存在或读取失败时返回 None。
    """
    registry_root = resolve_machine_registry_root()
    registry_path = registry_root / "registry.json"
    if not registry_path.exists():
        return None
    try:
        from core.machine_registry import load_machine_registry

        return load_machine_registry(registry_path)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        log.warning(
            "Machine registry could not be loaded; using legacy printer profiles",
            extra={
                "event": "system_machine_registry_load_failed",
                "path": str(registry_path),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None


def _slug_machine_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _registry_printer_id(
    *,
    display_name: str,
    brand: str,
    existing_ids: set[str],
) -> str:
    base = _slug_machine_id(display_name) or _slug_machine_id(f"{brand}-{display_name}")
    candidate = base or "registry-printer"
    if candidate not in existing_ids:
        return candidate
    branded = _slug_machine_id(f"{brand}-{display_name}")
    if branded and branded not in existing_ids:
        return branded
    suffix = 2
    while f"{candidate}-{suffix}" in existing_ids:
        suffix += 1
    return f"{candidate}-{suffix}"


def _registry_machines_by_key() -> dict[tuple[str, str], dict[str, object]]:
    registry = _try_load_machine_registry()
    if registry is None:
        return {}

    machines_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for device in sorted(
        registry.devices_by_id.values(),
        key=lambda item: (item.display_name, item.brand, item.slicer_id, item.nozzle_size),
    ):
        key = (device.display_name.casefold(), device.brand.casefold())
        machine = machines_by_key.setdefault(
            key,
            {
                "display_name": device.display_name,
                "brand": device.brand,
                "bed_width": device.bed_width,
                "bed_depth": device.bed_depth,
                "bed_height": device.bed_height,
                "thumbnail": device.thumbnail,
                "profiles": [],
            },
        )
        if device.thumbnail and not machine["thumbnail"]:
            machine["thumbnail"] = device.thumbnail
        profiles = machine["profiles"]
        assert isinstance(profiles, list)
        profiles.append(
            DeviceProfileInfo(
                device_profile_id=device.device_profile_id,
                machine_profile_id=device.machine_profile_id,
                slicer_id=device.slicer_id,
                nozzle_size=device.nozzle_size,
                source_profile_name=device.source_profile_name,
                revision=device.revision,
                supported=device.supported,
                build_plates=[
                    {
                        "id": plate.id,
                        "display_name": plate.display_name,
                        "display_name_zh": plate.display_name_zh,
                        "image_url": (
                            "/api/system/machine-registry/assets/" + plate.image
                            if plate.image else ""
                        ),
                    }
                    for plate in device.build_plates
                ],
                default_build_plate_id=device.default_build_plate_id,
            )
        )
    return machines_by_key


def _machine_registry_root() -> Path:
    return resolve_machine_registry_root()


def _first_existing_registry_thumbnail(*candidates: object) -> str:
    registry_root = _machine_registry_root().resolve()
    for candidate in candidates:
        relative_value = str(candidate or "").strip()
        if not relative_value:
            continue
        relative_path = Path(relative_value)
        if relative_path.is_absolute():
            continue
        requested = (registry_root / relative_path).resolve()
        try:
            inside_registry = (
                os.path.commonpath([str(registry_root), str(requested)])
                == str(registry_root)
            )
        except ValueError:
            inside_registry = False
        if not inside_registry:
            continue
        if requested.suffix.lower() not in MACHINE_REGISTRY_ASSET_MEDIA_TYPES:
            continue
        if requested.is_file():
            return relative_path.as_posix()
    return ""


def _purge_subdir(subdir: str) -> tuple[int, int]:
    """Delete all files in *subdir*, return ``(count, bytes)``."""
    count = 0
    freed = 0
    if not os.path.isdir(subdir):
        return count, freed
    for entry in os.scandir(subdir):
        if not entry.is_file():
            continue
        try:
            size = entry.stat().st_size
            os.remove(entry.path)
            count += 1
            freed += size
        except OSError:
            pass
    return count, freed


def _remove_preview_path(path: str | None) -> None:
    """Best-effort cleanup for preview files not owned by FileRegistry."""
    if not path:
        return
    with suppress(OSError):
        if os.path.exists(path):
            os.unlink(path)


def _raise_image_preview_preparation_error(
    exc: Exception,
    *,
    original_filename: str,
) -> None:
    log.error(
        "Image preview registration failed",
        extra={
            "event": "system_image_preview_registration_failed",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "original_filename": original_filename,
        },
    )
    raise HTTPException(
        status_code=500,
        detail=IMAGE_PREVIEW_PREPARATION_FAILED_DETAIL,
    ) from exc


def cleanup_output_dir(output_dir: str) -> tuple[int, int]:
    """Scan *output_dir* and its ``temp/`` / ``models/`` subdirectories,
    deleting transient files.

    扫描 *output_dir* 及其 ``temp/``、``models/`` 子目录，删除临时文件。

    - ``temp/`` and ``models/`` sub-directories: **all** files are deleted.
    - Main *output_dir*: only files whose extension is in
      :data:`CLEANABLE_EXTENSIONS` are deleted, **except** files listed in
      :data:`PROTECTED_FILES`.

    Returns:
        ``(deleted_count, freed_bytes)``。
        If *output_dir* does not exist, returns ``(0, 0)`` without raising.
    """
    if not os.path.isdir(output_dir):
        return 0, 0

    deleted_count = 0
    freed_bytes = 0

    for sub in ("temp", "models"):
        c, b = _purge_subdir(os.path.join(output_dir, sub))
        deleted_count += c
        freed_bytes += b

    for entry in os.scandir(output_dir):
        if not entry.is_file():
            continue
        if entry.name in PROTECTED_FILES:
            continue
        _, ext = os.path.splitext(entry.name)
        if ext.lower() not in CLEANABLE_EXTENSIONS:
            continue
        try:
            size = entry.stat().st_size
            os.remove(entry.path)
            deleted_count += 1
            freed_bytes += size
        except OSError:
            pass

    return deleted_count, freed_bytes


def perform_cache_cleanup(
    file_registry: FileRegistry,
    session_store: SessionStore,
    output_dir: str,
) -> ClearCacheResult:
    """Coordinate a full cache cleanup across all subsystems.

    执行缓存清理，依次清理 FileRegistry、SessionStore 和 OUTPUT_DIR，
    返回汇总统计结果。

    Steps:
        1. ``FileRegistry.clear_all()`` — clear registry & delete files
        2. ``SessionStore.clear_all()`` — clear sessions & temp files
        3. ``cleanup_output_dir()`` — delete matching files in OUTPUT_DIR
    """
    registry_cleaned: int = file_registry.clear_all()
    sessions_cleaned: int = session_store.clear_all()
    output_files_cleaned, freed_bytes = cleanup_output_dir(output_dir)

    return ClearCacheResult(
        registry_cleaned=registry_cleaned,
        sessions_cleaned=sessions_cleaned,
        output_files_cleaned=output_files_cleaned,
        total_freed_bytes=freed_bytes,
    )


@router.post("/validate-heightmap")
async def validate_heightmap(file: UploadFile = File(...)) -> dict[str, int]:
    """Decode original heightmap bytes without altering any session or asset.
    解码高度图原始字节，不修改任何会话或素材。

    Args:
        file: Original PNG/JPEG/BMP/TIFF upload. (原始高度图上传文件。)

    Returns:
        dict[str, int]: Decoded width and height. (解码后的宽高。)

    Raises:
        HTTPException: Invalid image. (无效图像。)
    """
    suffix = Path(file.filename or "").suffix.lower()
    if (
        suffix not in _HEIGHTMAP_IMAGE_SUFFIXES
        or file.content_type not in _HEIGHTMAP_IMAGE_MIME_TYPES
    ):
        raise HTTPException(status_code=422, detail=_HEIGHTMAP_UNREADABLE_DETAIL)
    temp_path = await upload_to_tempfile(file)
    try:
        result = await run_in_threadpool(HeightmapLoader.load_and_validate, temp_path)
        if not result["success"] or not result["original_size"]:
            raise HTTPException(status_code=422, detail=_HEIGHTMAP_UNREADABLE_DETAIL)
        width, height = result["original_size"]
        if width <= 0 or height <= 0:
            raise HTTPException(status_code=422, detail=_HEIGHTMAP_UNREADABLE_DETAIL)
        return {"width": int(width), "height": int(height)}
    except (OSError, ValueError, TypeError, RuntimeError, cv2.error) as exc:
        raise HTTPException(status_code=422, detail=_HEIGHTMAP_UNREADABLE_DETAIL) from exc
    finally:
        with suppress(OSError):
            os.unlink(temp_path)


def _prepare_browser_preview(path: str) -> tuple[int, int]:
    """Decode the actual file format and provide browser-readable PNG bytes."""
    from PIL import ImageOps

    with Image.open(path) as source:
        needs_conversion = source.format != "PNG" or source.getexif().get(274, 1) != 1
        if not needs_conversion:
            return source.size
        image = ImageOps.exif_transpose(source)
        if image.mode not in {"RGB", "RGBA", "L", "LA", "P", "1", "I", "I;16"}:
            image = image.convert("RGB")
    try:
        image.save(path, format="PNG")
        return image.size
    finally:
        image.close()


@router.post("/image-preview")
async def image_preview(
    file: UploadFile,
    file_registry: FileRegistry = Depends(get_file_registry),
) -> dict:
    """Convert any image (including RAW/HEIC) to PNG and return a preview URL.
    将任意图片（包括 RAW/HEIC）转为 PNG 并返回预览 URL。

    Args:
        file: 上传的图片文件
        file_registry: 文件注册表依赖

    Returns:
        dict: {preview_url, width, height}
    """
    original_filename = file.filename or "unknown"
    png_path = await ensure_png_tempfile(file)
    try:
        width, height = await run_in_threadpool(_prepare_browser_preview, png_path)
    except (OSError, ValueError) as exc:
        with suppress(OSError):
            if os.path.exists(png_path):
                os.unlink(png_path)
        raise HTTPException(
            status_code=422,
            detail="无法读取图片尺寸：无效或损坏的图片文件",
        ) from exc
    file_id: str | None = None
    try:
        file_id = file_registry.register_path(
            str(uuid.uuid4()),
            png_path,
            "preview.png",
            ttl_seconds=EPHEMERAL_PREVIEW_TTL_SECONDS,
        )
        file_size_bytes = os.path.getsize(png_path)
        log.info(
            "Image preview generated",
            extra={
                "event": "system_image_preview_done",
                "original_filename": original_filename,
                "file_id": file_id,
                "image_width": int(width),
                "image_height": int(height),
                "file_size_bytes": int(file_size_bytes),
            },
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        if file_id is not None:
            with suppress(OSError, RuntimeError, ValueError):
                file_registry.cleanup_file(file_id)
        else:
            _remove_preview_path(png_path)
        _raise_image_preview_preparation_error(
            exc,
            original_filename=original_filename,
        )
    return {"preview_url": f"/api/files/{file_id}", "width": width, "height": height}


@router.post("/preview-resources")
async def preview_resources(
    file: UploadFile = File(...),
    context: str = Form(...),
    file_registry: FileRegistry = Depends(get_file_registry),
) -> dict:
    """Register a private image resource and return a bounded public preview.
    注册私有图像资源，并只返回受尺寸限制的小预览。
    """
    context_value = validate_preview_context(context)
    result = await register_preview_resource_upload(
        file_registry,
        file,
        context=context_value,
    )
    log.info(
        "Preview resource registered",
        extra={
            "event": "system_preview_resource_done",
            "context": context_value,
            "full_width": result.full_width,
            "full_height": result.full_height,
            "preview_width": result.preview_width,
            "preview_height": result.preview_height,
            "source_type": result.source_type,
        },
    )
    return {
        "resource_id": result.resource_id,
        "preview_id": result.preview_id,
        "preview_url": result.preview_url,
        "full_width": result.full_width,
        "full_height": result.full_height,
        "preview_width": result.preview_width,
        "preview_height": result.preview_height,
        "source_type": result.source_type,
    }


@router.post("/preview-artifacts")
async def preview_artifacts(
    resource_id: str = Form(...),
    context: str = Form(...),
    file_registry: FileRegistry = Depends(get_file_registry),
) -> dict:
    """Return a bounded public preview for an existing private artifact.
    基于已有私有资源返回受尺寸限制的小预览。
    """
    context_value = validate_preview_context(context)
    result = register_preview_for_artifact(
        file_registry,
        context=context_value,
        resource_id=resource_id,
    )
    log.info(
        "Preview artifact registered",
        extra={
            "event": "system_preview_artifact_done",
            "context": context_value,
            "preview_width": result.preview_width,
            "preview_height": result.preview_height,
        },
    )
    return {
        "preview_id": result.preview_id,
        "preview_url": result.preview_url,
        "preview_width": result.preview_width,
        "preview_height": result.preview_height,
    }


@router.post("/clear-cache")
def clear_cache(
    request: Request,
    file_registry: FileRegistry = Depends(get_file_registry),
    session_store: SessionStore = Depends(get_session_store),
) -> ClearCacheResponse:
    """Clear all cached/temporary files across subsystems.

    清除所有子系统中的缓存和临时文件，返回清理统计信息。
    """
    _enforce_clear_cache_origin(request)
    result: ClearCacheResult = perform_cache_cleanup(file_registry, session_store, config.OUTPUT_DIR)
    total_deleted: int = result.registry_cleaned + result.sessions_cleaned + result.output_files_cleaned
    return ClearCacheResponse(
        status="success",
        message=f"Cache cleared: {total_deleted} files deleted",
        deleted_files=total_deleted,
        freed_bytes=result.total_freed_bytes,
        details=CacheCleanupDetails(
            registry_cleaned=result.registry_cleaned,
            sessions_cleaned=result.sessions_cleaned,
            output_files_cleaned=result.output_files_cleaned,
        ),
    )


# ---------------------------------------------------------------------------
# Printers endpoint
# ---------------------------------------------------------------------------


@router.get("/printers")
def get_printers() -> PrinterListResponse:
    """Return all supported printer models.
    返回所有支持的打印机型号列表。

    Returns:
        PrinterListResponse: List of printer metadata. (打印机元数据列表)
    """
    profiles = config.list_printer_profiles()
    registry_machines = _registry_machines_by_key()
    printers = []
    existing_ids = {profile.id for profile in profiles}
    attached_registry_keys: set[tuple[str, str]] = set()
    for p in profiles:
        key = (p.display_name.casefold(), p.brand.casefold())
        registry_machine = registry_machines.get(key, {})
        registry_device_profiles = registry_machine.get("profiles", [])
        assert isinstance(registry_device_profiles, list)
        registry_slicers = [
            profile.slicer_id
            for profile in registry_device_profiles
            if isinstance(profile, DeviceProfileInfo)
        ]
        registry_nozzles = [
            profile.nozzle_size
            for profile in registry_device_profiles
            if isinstance(profile, DeviceProfileInfo)
        ]
        unique_slicers = _unique_preserve_order(registry_slicers)
        if config.DEFAULT_SLICER_ID in unique_slicers:
            unique_slicers.remove(config.DEFAULT_SLICER_ID)
            unique_slicers.insert(0, config.DEFAULT_SLICER_ID)
        unique_nozzles = _unique_preserve_order([*p.supported_nozzle_sizes, *registry_nozzles])
        attached_registry_keys.add(key)
        printers.append(
            PrinterInfo(
                id=p.id,
                display_name=p.display_name,
                brand=p.brand,
                bed_width=p.bed_width,
                bed_depth=p.bed_depth,
                bed_height=p.bed_height,
                supported_nozzle_sizes=unique_nozzles,
                supported_slicers=unique_slicers,
                thumbnail=_first_existing_registry_thumbnail(
                    registry_machine.get("thumbnail"),
                    p.thumbnail,
                ),
                device_profiles=registry_device_profiles,
            )
        )
    for key, registry_machine in registry_machines.items():
        if key in attached_registry_keys:
            continue
        profiles_for_machine = registry_machine.get("profiles", [])
        assert isinstance(profiles_for_machine, list)
        device_profiles = [
            profile
            for profile in profiles_for_machine
            if isinstance(profile, DeviceProfileInfo)
        ]
        display_name = str(registry_machine["display_name"])
        brand = str(registry_machine["brand"])
        printer_id = _registry_printer_id(
            display_name=display_name,
            brand=brand,
            existing_ids=existing_ids,
        )
        existing_ids.add(printer_id)
        printers.append(
            PrinterInfo(
                id=printer_id,
                display_name=display_name,
                brand=brand,
                bed_width=int(registry_machine["bed_width"]),
                bed_depth=int(registry_machine["bed_depth"]),
                bed_height=int(registry_machine["bed_height"]),
                supported_nozzle_sizes=_unique_preserve_order(
                    [profile.nozzle_size for profile in device_profiles]
                ),
                supported_slicers=_unique_preserve_order(
                    [profile.slicer_id for profile in device_profiles]
                ),
                thumbnail=_first_existing_registry_thumbnail(
                    registry_machine.get("thumbnail"),
                ),
                device_profiles=device_profiles,
            )
        )
    return PrinterListResponse(status="success", printers=printers)


@router.get("/machine-registry/assets/{asset_path:path}")
def get_machine_registry_asset(asset_path: str) -> FileResponse:
    """Serve a generated machine-registry image asset.
    返回生成机器注册表中的图片资产。
    """
    registry_root = _machine_registry_root()
    requested = (registry_root / asset_path).resolve()
    try:
        inside_registry = os.path.commonpath([str(registry_root), str(requested)]) == str(registry_root)
    except ValueError:
        inside_registry = False
    if not inside_registry:
        raise HTTPException(status_code=400, detail="Invalid machine registry asset path")

    media_type = MACHINE_REGISTRY_ASSET_MEDIA_TYPES.get(requested.suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="Machine registry asset not found")
    if not requested.exists() or not requested.is_file():
        raise HTTPException(status_code=404, detail="Machine registry asset not found")
    return FileResponse(path=requested, media_type=media_type)


@router.get(
    "/machine-registry/bed-model",
    dependencies=[Depends(require_local_app_origin)],
)
def get_machine_registry_bed_model(device_profile_id: str) -> FileResponse:
    """Serve an installed slicer's native bed model for one device profile.

    返回指定设备配置对应的本机切片软件原生热床模型。
    """

    registry = _try_load_machine_registry()
    if registry is None:
        raise HTTPException(status_code=404, detail="Machine registry not found")
    try:
        profile = registry.get_device_profile(device_profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Device profile not found") from exc
    model_path = resolve_installed_bed_model(profile)
    if model_path is None:
        raise HTTPException(status_code=404, detail="Bed model not found")
    return FileResponse(path=model_path, media_type="model/stl")


# ---------------------------------------------------------------------------
# Slicers endpoint
# ---------------------------------------------------------------------------


@router.get("/slicers")
def get_slicers() -> SlicerListResponse:
    """Return all supported slicer software options.
    返回所有支持的切片器软件列表。

    Returns:
        SlicerListResponse: List of slicer metadata. (切片器元数据列表)
    """
    slicers = [SlicerInfo(id=s["id"], display_name=s["display_name"]) for s in config.SUPPORTED_SLICERS]
    return SlicerListResponse(status="success", slicers=slicers)


# ---------------------------------------------------------------------------
# Settings & Stats endpoints
# ---------------------------------------------------------------------------

def resolve_settings_file(env: Mapping[str, str]) -> Path:
    """Resolve the user-settings file for development or launcher runtimes.

    为开发环境或启动器运行时解析用户设置文件。

    Args:
        env: Process environment mapping. 进程环境变量映射。

    Returns:
        The legacy relative file or an absolute launcher-owned path.
        旧版相对路径，或启动器托管的绝对路径。

    Raises:
        ValueError: If a launcher override is not absolute.
            启动器覆盖路径不是绝对路径时抛出。
    """

    override = env.get("LUMINA_SETTINGS_PATH", "").strip()
    if not override:
        return Path("user_settings.json")
    settings_path = Path(override).expanduser()
    if not settings_path.is_absolute():
        raise ValueError("LUMINA_SETTINGS_PATH must be an absolute file path")
    return settings_path


SETTINGS_FILE: Path = resolve_settings_file(os.environ)
SETTINGS_SAVE_FAILED_DETAIL = (
    "Settings could not be saved. Check disk permissions or free space and try again."
)


@router.get(
    "/settings",
    dependencies=[Depends(require_local_app_origin)],
)
def get_settings() -> UserSettingsResponse:
    """Read persisted user settings with safe fallback.

    读取 user_settings.json 并返回 UserSettings；文件缺失、损坏或顶层结构
    非对象时返回默认值。

    Returns:
        UserSettingsResponse: Current settings or defaults.
            当前设置；无法安全读取时返回默认设置。
    """
    try:
        if not SETTINGS_FILE.exists():
            return UserSettingsResponse(status="success", settings=UserSettings())
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return UserSettingsResponse(status="success", settings=UserSettings())
        return UserSettingsResponse(status="success", settings=UserSettings(**data))
    except OSError as exc:
        log.warning(
            "User settings could not be loaded; using defaults",
            extra={
                "event": "system_settings_load_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "settings_path": str(SETTINGS_FILE),
            },
        )
        return UserSettingsResponse(status="success", settings=UserSettings())
    except (json.JSONDecodeError, ValueError):
        return UserSettingsResponse(status="success", settings=UserSettings())


@router.post(
    "/settings",
    dependencies=[Depends(require_local_app_origin)],
)
def save_settings(settings: UserSettings) -> SaveSettingsResponse:
    """Save validated settings while preserving fields owned by newer versions.

    保存已校验的用户设置，同时保留较新版本拥有的未知字段。

    Args:
        settings: Validated user preferences. 已校验的用户偏好。

    Returns:
        Save confirmation. 保存成功确认。

    Raises:
        HTTPException: If the settings cannot be written. 设置无法写入时抛出。
    """
    try:
        settings_payload = settings.model_dump()
        if "conversion_preferences" not in settings.model_fields_set:
            settings_payload.pop("conversion_preferences", None)
        stored_payload: dict[str, object] = {}
        try:
            if SETTINGS_FILE.exists():
                existing = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    stored_payload.update(existing)
        except (OSError, TypeError, UnicodeError, json.JSONDecodeError):
            # A broken legacy file must not prevent the validated current
            # settings from repairing it.
            stored_payload = {}
        stored_payload.update(settings_payload)
        serialized = json.dumps(stored_payload, indent=2, ensure_ascii=False)
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(serialized, encoding="utf-8")
        log.info(
            "User settings saved",
            extra={
                "event": "system_save_settings_done",
                "settings_field_count": len(stored_payload),
                "bytes_written": len(serialized.encode("utf-8")),
                "settings_path": str(SETTINGS_FILE),
            },
        )
        return SaveSettingsResponse(status="success", message="Settings saved")
    except OSError as exc:
        log.error(
            "User settings save failed",
            extra={
                "event": "system_save_settings_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "settings_path": str(SETTINGS_FILE),
            },
        )
        raise HTTPException(status_code=500, detail=SETTINGS_SAVE_FAILED_DETAIL) from exc


@router.get("/stats")
def get_stats() -> StatsResponse:
    """获取使用统计数据。"""
    from utils.stats import Stats

    data: dict = Stats.get_all()
    return StatsResponse(
        calibrations=data.get("calibrations", 0),
        extractions=data.get("extractions", 0),
        conversions=data.get("conversions", 0),
    )
