"""Single-stage workflow API routes."""

from __future__ import annotations

import json
import os
from ipaddress import ip_address
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import threading
import tempfile
import uuid
import zipfile
from typing import Any, Callable
from urllib.parse import urlparse

import anyio
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

from config import TEMP_DIR
from api.colorchecker_artifacts import load_colorchecker_full_rgb, scale_corner_points
from api.dependencies import get_file_registry, get_session_store
from api.export_device_validation import validate_export_device_selection
from api.file_bridge import ndarray_to_png_bytes, upload_to_ndarray, upload_to_tempfile
from api.file_registry import FileRegistry
from api.local_origin_guard import require_local_app_origin
from api.schemas.single_stage import (
    GradientCardMaterialUpdateRequest,
    MaterialLibraryBulkExportRequest,
    MaterialRecipePreviewRequest,
    MaterialRecipeSwatchRequest,
    MaterialRecipeSwatchResponse,
)
from api.schemas.responses import (
    GradientCardMaterialBulkExportResponse,
    GradientCardMaterialBulkImportResponse,
    GradientCardMaterialDeleteResponse,
    GradientCardMaterialLibraryResponse,
    GradientCardMaterialSaveResponse,
    GradientCardMaterialUpdateResponse,
    GradientCardStageAExtractResponse,
    MaterialColorSuggestionItem,
    MaterialColorSuggestionsResponse,
    MaterialRecipeLayerResponse,
    MaterialRecipePreviewResponse,
    MaterialSolverCacheBuildResponse,
    MaterialSolverCacheDeleteResponse,
    MaterialSolverCacheDetailsResponse,
    MaterialSolverCacheEntryResponse,
    MaterialSolverCacheListResponse,
    MaterialSolverCacheStatusResponse,
    MaterialSolverRuntimeBuildResponse,
    MaterialSolverRuntimeDeleteResponse,
    MaterialSolverRuntimeDetailsResponse,
    MaterialSolverRuntimeEntryResponse,
    MaterialSolverRuntimeStatusResponse,
    SingleStageExtractResponse,
    StageAFitResponse,
    public_material_response_item,
)
from api.schemas.lut import (
    LutAxisRange,
    LutCoverageStatsResponse,
    LutHullPoint,
    LutPlotPoint,
    LutPlotPoint3D,
)
from api.session_store import SessionStore
from api.structured_logging import bind_session_id, get_logger
from core.material_cache import (
    ALLOWED_GRID_RESOLUTIONS,
    ALLOWED_LAYER_HEIGHTS_MM as _CACHE_ALLOWED_LAYER_HEIGHTS,  # noqa: N811
    DEFAULT_GRID_RESOLUTION,
    build_material_solver_cache,
    cache_file_path,
    delete_cached_entry,
    describe_palette,
    list_cached_entries,
    load_material_solver_cache,
    load_material_solver_cache_with_fallback,
    save_material_solver_cache,
)
from core.material_cache_visualization import (
    build_material_cache_details,
    build_material_runtime_details,
)
from core.material_candidate_cache import (
    DEFAULT_PERSISTED_CANDIDATE_BUDGET,
    MAX_PERSISTED_CANDIDATE_BUDGET,
    MaterialCandidateCacheConfig,
    MaterialCandidateRuntimeMetadata,
    build_material_candidate_runtime,
    delete_material_candidate_runtime,
    load_material_candidate_runtime,
    load_material_candidate_runtime_metadata,
    save_material_candidate_runtime,
)
from core.material_color_solver import (
    DEFAULT_SUGGEST_MIN_SPACING,
    DEFAULT_SUGGEST_TOP_K,
    MAX_LAYER_COUNT as _SOLVER_MAX_LAYER_COUNT,  # noqa: N811
    MITM_MAX_LAYER_COUNT as _SOLVER_MITM_MAX_LAYER_COUNT,  # noqa: N811
    MIN_LAYER_COUNT as _SOLVER_MIN_LAYER_COUNT,  # noqa: N811
    ColorSuggestion,
    MaterialParams,
    predict_material_recipe_srgb,
    suggest_colors_for_target,
)
from core.material_lut_synthesis import load_multiple_materials
from core.lut_details.identity import canonicalize_lut_manufacturer
from core.single_stage import (
    material_files,
    delete_saved_stage_a_material_archive,
    export_saved_stage_a_material_archives,
    extract_single_stage_dataset,
    extract_stage_a_material_from_gradient_cards,
    fit_stage_a_from_stage_json,
    import_saved_stage_a_material_archives,
    list_saved_stage_a_material_archives,
    save_stage_a_material_archive,
    update_saved_stage_a_material_archive_metadata,
)

router = APIRouter(prefix="/api/extractor", tags=["Extractor"])
log = get_logger(__name__)
GRADIENT_CARD_PREVIEW_TTL_SECONDS = 600
STAGE_A_PARAMS_DOWNLOAD_TTL_SECONDS = 8 * 60 * 60
MATERIAL_LIBRARY_FILE_TTL_SECONDS = 600
MATERIAL_SWATCH_EXPORT_TTL_SECONDS = 8 * 60 * 60
FIT_STAGE_A_EXPIRED_STAGE_JSON_DETAIL = (
    "Extracted single-stage dataset has expired. "
    "Re-run extraction before fitting Stage A."
)
SINGLE_STAGE_DATASET_MALFORMED_ZIP_DETAIL = "Malformed ZIP archive"
SINGLE_STAGE_DATASET_INVALID_LAYOUT_DETAIL = (
    "Dataset zip must contain {substrate_id}/{color_name}/ directories."
)
SINGLE_STAGE_DATASET_UNSAFE_ZIP_DETAIL = (
    "Dataset ZIP contains an unsafe file path."
)
SINGLE_STAGE_DATASET_MISSING_LABELME_PREFIX = (
    "Missing LabelMe JSON files in dataset directory: "
)
SINGLE_STAGE_DATASET_MISSING_LABELME_DETAIL = (
    "Dataset ZIP is missing LabelMe JSON files."
)
MATERIAL_SOLVER_CACHE_LIST_FAILED_DETAIL = (
    "Material solver caches could not be listed. "
    "Check cache storage and try again."
)
GRADIENT_CARD_MATERIAL_LIBRARY_LIST_FAILED_DETAIL = (
    "Gradient-card material library could not be loaded. "
    "Check saved material storage and try again."
)
GRADIENT_CARD_MATERIAL_LIBRARY_FORBIDDEN_DETAIL = (
    "Material library management is only available from the Lumina Studio local app."
)
GRADIENT_CARD_MATERIAL_IMPORT_UNSAFE_PATH_DETAIL = (
    "Material import ZIP contains an unsafe file path."
)
GRADIENT_CARD_MATERIAL_IMPORT_FAILED_DETAIL = (
    "Material import failed. Check the server log for details."
)
GRADIENT_CARD_MATERIAL_SAVE_FAILED_DETAIL = (
    "Gradient card material save failed. Check the server log for details."
)
_MATERIAL_LIBRARY_DEFAULT_LOCAL_PORTS = frozenset({8000, 4174, 5174, 5173})
_MATERIAL_LIBRARY_ALLOWED_LOCAL_PORTS_ENV = (
    "LUMINA_MATERIAL_LIBRARY_ALLOWED_LOCAL_PORTS"
)
_MATERIAL_LIBRARY_ALLOWED_ORIGINS_ENV = "LUMINA_MATERIAL_LIBRARY_ALLOWED_ORIGINS"
MATERIAL_SOLVER_CACHE_BUILD_FAILED_DETAIL = (
    "Material solver cache could not be built. "
    "Check material inputs and cache storage, then try again."
)
MATERIAL_SOLVER_RUNTIME_BUILD_FAILED_DETAIL = (
    "Material solver runtime could not be built. "
    "Check material inputs and cache storage, then try again."
)
MATERIAL_SWATCH_EXPORT_FAILED_DETAIL = (
    "Material swatch export failed. Check the selected material recipes and "
    "export settings, then try again."
)
_RUNTIME_BUILD_LOCKS_GUARD = threading.Lock()
_RUNTIME_BUILD_LOCKS: dict[tuple[str, int, str, str, int], threading.Lock] = {}
_RUNTIME_BUILD_GLOBAL_SEMAPHORE = threading.BoundedSemaphore(1)


def _is_missing_stage_json_path(path: str | None) -> bool:
    return not isinstance(path, str) or not path.strip() or not os.path.exists(path)


def _expired_stage_json_exception() -> HTTPException:
    return HTTPException(status_code=409, detail=FIT_STAGE_A_EXPIRED_STAGE_JSON_DETAIL)


def _is_safe_relative_detail_fragment(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return False
    if cleaned.startswith(("/", "\\", "file://")):
        return False
    if "\\" in cleaned or "://" in cleaned:
        return False
    if PureWindowsPath(cleaned).drive:
        return False
    parts = PurePosixPath(cleaned).parts
    return all(part not in {"", ".", ".."} for part in parts)


def _single_stage_dataset_input_error_detail(exc: ValueError) -> str | None:
    message = str(exc).strip()
    if message == SINGLE_STAGE_DATASET_MALFORMED_ZIP_DETAIL:
        return SINGLE_STAGE_DATASET_MALFORMED_ZIP_DETAIL
    if message == SINGLE_STAGE_DATASET_INVALID_LAYOUT_DETAIL:
        return SINGLE_STAGE_DATASET_INVALID_LAYOUT_DETAIL
    if message.startswith("Unsafe zip entry:"):
        return SINGLE_STAGE_DATASET_UNSAFE_ZIP_DETAIL
    if message.startswith(SINGLE_STAGE_DATASET_MISSING_LABELME_PREFIX):
        missing_dir = message[len(SINGLE_STAGE_DATASET_MISSING_LABELME_PREFIX):]
        if _is_safe_relative_detail_fragment(missing_dir):
            return f"{SINGLE_STAGE_DATASET_MISSING_LABELME_PREFIX}{missing_dir.strip()}"
        return SINGLE_STAGE_DATASET_MISSING_LABELME_DETAIL
    return None


def _gradient_card_material_import_error_detail(exc: ValueError) -> str | None:
    message = str(exc).strip()
    if message.startswith("Unsafe zip entry:"):
        return GRADIENT_CARD_MATERIAL_IMPORT_UNSAFE_PATH_DETAIL
    if message.startswith("Unsafe material bundle file path:"):
        return GRADIENT_CARD_MATERIAL_IMPORT_UNSAFE_PATH_DETAIL
    if message.startswith("Material bundle file is outside material directory:"):
        return GRADIENT_CARD_MATERIAL_IMPORT_UNSAFE_PATH_DETAIL
    return None


def _gradient_card_material_save_error_detail(exc: Exception) -> str:
    message = str(exc).strip()
    if message == "material_name is required":
        return message
    if message == "Existing material archive is not valid UTF-8 JSON":
        return message
    if message.startswith(
        "Cannot merge gradient-card captures from different image sources:"
    ):
        return message
    for prefix in (
        "Saved material directory not found:",
        "Saved material archive not found:",
    ):
        if message.startswith(prefix):
            target = message[len(prefix):].strip()
            if _is_safe_relative_detail_fragment(target):
                return message
    return GRADIENT_CARD_MATERIAL_SAVE_FAILED_DETAIL


def _raise_gradient_card_material_save_client_error(
    exc: Exception,
    *,
    status_code: int,
    session_id: str,
) -> None:
    detail = _gradient_card_material_save_error_detail(exc)
    log.warning(
        "Gradient card material save failed",
        extra={
            "event": "extractor_save_gradient_card_material_failed",
            "context": "Gradient card material save",
            "status_code": status_code,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "session_id": session_id,
        },
    )
    raise HTTPException(status_code=status_code, detail=detail) from exc


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


def _material_library_allowed_local_ports() -> set[int]:
    ports = set(_MATERIAL_LIBRARY_DEFAULT_LOCAL_PORTS)
    raw_ports = os.environ.get(_MATERIAL_LIBRARY_ALLOWED_LOCAL_PORTS_ENV, "")
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


def _material_library_allowed_origin_keys() -> set[str]:
    allowed: set[str] = set()
    raw_origins = os.environ.get(_MATERIAL_LIBRARY_ALLOWED_ORIGINS_ENV, "")
    for raw_origin in raw_origins.split(","):
        parsed = _parse_origin(raw_origin)
        if parsed is None:
            continue
        _, _, origin_key = parsed
        allowed.add(origin_key)
    return allowed


def _is_trusted_material_library_request(request: Request) -> tuple[bool, str]:
    raw_host = request.headers.get("host")
    parsed_host = _parse_host_header(raw_host)
    if parsed_host is None:
        return False, "invalid_host"
    host, _host_port = parsed_host
    if not _is_loopback_host(host):
        return False, "untrusted_host"

    raw_origin = request.headers.get("origin")
    if raw_origin is None:
        sec_fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
        if sec_fetch_site == "cross-site":
            return False, "cross_site_fetch"
        return True, "no_origin"

    parsed_origin = _parse_origin(raw_origin)
    if parsed_origin is None:
        return False, "invalid_origin"

    origin_host, origin_port, origin_key_value = parsed_origin
    if origin_key_value in _material_library_allowed_origin_keys():
        return True, "explicit_origin_allowlist"

    if not _is_loopback_host(origin_host):
        return False, "untrusted_origin_host"
    if origin_port not in _material_library_allowed_local_ports():
        return False, "untrusted_origin_port"

    return True, "local_origin"


def _enforce_material_library_request(request: Request) -> None:
    trusted, reason = _is_trusted_material_library_request(request)
    if trusted:
        return

    origin = request.headers.get("origin", "")
    host = request.headers.get("host", "")
    sec_fetch_site = request.headers.get("sec-fetch-site", "")
    log.warning(
        "Material library management blocked for untrusted request origin",
        extra={
            "event": "extractor_gradient_card_material_library_forbidden",
            "origin": origin,
            "host": host,
            "sec_fetch_site": sec_fetch_site,
            "reason": reason,
            "error_type": "ForbiddenMaterialLibraryOrigin",
            "error_message": GRADIENT_CARD_MATERIAL_LIBRARY_FORBIDDEN_DETAIL,
        },
    )
    raise HTTPException(
        status_code=403,
        detail=GRADIENT_CARD_MATERIAL_LIBRARY_FORBIDDEN_DETAIL,
    )


def _saved_material_directory_name(material_summary: Any, fallback: str) -> str:
    """Return the normalized saved-material directory name from a result.
    从结果摘要中返回规范化的已保存耗材目录名。
    """
    if isinstance(material_summary, dict):
        directory_name = material_summary.get("directory_name")
        if isinstance(directory_name, str) and directory_name.strip():
            return directory_name.strip()
    return fallback


def _canonicalize_saved_material_brand(item: dict[str, object]) -> dict[str, object]:
    """Return a response item with the LUT-canonical brand label."""

    brand = item.get("brand")
    if isinstance(brand, str) and brand.strip():
        return {**item, "brand": canonicalize_lut_manufacturer(brand)}
    return item


def _parse_corner_points(raw_points: str, field_name: str) -> list[list[float]]:
    try:
        points = json.loads(raw_points)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field_name} JSON: {exc}")
    if not isinstance(points, list) or len(points) != 4:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must contain exactly 4 points",
        )
    return points


_VALID_MANUAL_ORIENTATION_LABELS: frozenset[str] = frozenset(
    {
        "identity",
        "rotate_90_cw",
        "rotate_180",
        "rotate_90_ccw",
        "flip_horizontal",
        "flip_vertical",
        "transpose",
        "transverse",
    }
)


_GRADIENT_CARD_ALLOWED_IMAGE_SOURCES: tuple[str, ...] = ("raw", "restored")


def _normalize_image_source(raw: str | None) -> str | None:
    """Normalize and validate the gradient-card ``image_source`` form value.
    规范化并校验梯度卡 ``image_source`` 表单值。

    Stage A accepts ``"raw"`` direct camera/scanner captures by default and
    ``"restored"`` only when the caller explicitly labels the inputs as
    restored/calibrated renders. The core layer records the source tag and
    prevents accidental raw/restored archive mixing.

    Stage A 默认使用 ``"raw"``。只有调用方明确传入 ``"restored"`` 时，才把已校色
    或修复后的图像作为 restored 来源记录，避免静默当作 raw 原图。

    Args:
        raw (str | None): Raw form value, possibly ``None`` or whitespace.

    Returns:
        str | None: ``None`` if the input is empty/blank (lets the core layer
        apply its ``raw`` default); otherwise the validated lowercase tag.

    Raises:
        HTTPException: ``422`` for any non-empty value outside the whitelist.
    """
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned:
        return None
    if cleaned not in _GRADIENT_CARD_ALLOWED_IMAGE_SOURCES:
        allowed = ", ".join(repr(s) for s in _GRADIENT_CARD_ALLOWED_IMAGE_SOURCES)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported image_source '{raw}'. Stage A accepts {allowed}."
            ),
        )
    return cleaned


def _normalize_manual_orientation(raw: str | None) -> str | None:
    """Normalize an optional manual orientation form value.
    规范化可选的手动方向表单值。

    Treats empty/blank/``"auto"``/``"none"`` as "no override". Validates the
    label against the canonical orientation enum and raises ``HTTPException``
    on unknown labels.
    """
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned or cleaned in {"auto", "none", "null"}:
        return None
    if cleaned not in _VALID_MANUAL_ORIENTATION_LABELS:
        valid = ", ".join(sorted(_VALID_MANUAL_ORIENTATION_LABELS))
        raise HTTPException(
            status_code=422,
            detail=f"Invalid manual orientation label {raw!r}; expected one of: {valid}",
        )
    return cleaned


def _rollback_imported_materials(directory_names: list[str]) -> None:
    for directory_name in reversed(directory_names):
        try:
            delete_saved_stage_a_material_archive(directory_name=directory_name)
        except (FileNotFoundError, ValueError, TypeError, OSError, RuntimeError):
            pass


MaterialDirectoryBackup = tuple[Path, Path, Path]
NewMaterialCandidateSnapshot = tuple[Path, str, set[Path]]


def _candidate_material_dir_name_matches(name: str, stem: str) -> bool:
    return name == stem or name.startswith(f"{stem}_")


def _create_new_material_candidate_snapshot(
    *,
    material_name: str,
    brand: str | None,
) -> NewMaterialCandidateSnapshot:
    materials_root = Path(material_files.MATERIALS_DIR)
    stem = material_files._sanitize_material_dirname(material_name)
    parent_dir = materials_root
    if brand is not None:
        parent_dir = materials_root / material_files._sanitize_material_dirname(brand)
    existing_candidates: set[Path] = set()
    try:
        children = list(parent_dir.iterdir()) if parent_dir.exists() else []
    except OSError:
        children = []
    for child in children:
        if child.is_dir() and _candidate_material_dir_name_matches(child.name, stem):
            try:
                existing_candidates.add(child.resolve())
            except OSError:
                existing_candidates.add(child.absolute())
    return parent_dir, stem, existing_candidates


def _create_material_directory_backup(directory_name: str) -> MaterialDirectoryBackup:
    materials_root = Path(material_files.MATERIALS_DIR)
    material_dir = material_files.resolve_saved_material_dir(
        materials_root,
        directory_name,
    )
    backup_root = Path(tempfile.mkdtemp(prefix="lumina_material_backup_"))
    backup_dir = backup_root / "material"
    try:
        shutil.copytree(material_dir, backup_dir)
    except (OSError, shutil.Error):
        shutil.rmtree(backup_root, ignore_errors=True)
        raise
    return material_dir, backup_dir, backup_root


def _create_material_directory_backup_or_raise(
    directory_name: str,
    *,
    event: str,
    session_id: str | None = None,
) -> MaterialDirectoryBackup:
    try:
        return _create_material_directory_backup(directory_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, RuntimeError, shutil.Error) as exc:
        _raise_internal_route_error(
            exc,
            context="Gradient card material backup",
            event=event,
            session_id=session_id,
        )


def _discard_material_directory_backup(
    backup: MaterialDirectoryBackup | None,
) -> None:
    if backup is None:
        return
    _, _, backup_root = backup
    shutil.rmtree(backup_root, ignore_errors=True)


def _restore_material_directory_backup(
    backup: MaterialDirectoryBackup | None,
) -> None:
    if backup is None:
        return
    material_dir, backup_dir, _ = backup
    restore_dir = material_dir.parent / f".{material_dir.name}.restore-{uuid.uuid4().hex}"
    try:
        shutil.copytree(backup_dir, restore_dir)
        shutil.rmtree(material_dir, ignore_errors=True)
        material_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(restore_dir, material_dir)
    finally:
        shutil.rmtree(restore_dir, ignore_errors=True)


def _path_is_inside_materials_root(path: Path) -> bool:
    try:
        resolved_path = path.resolve()
        materials_root = Path(material_files.MATERIALS_DIR).resolve()
        resolved_path.relative_to(materials_root)
    except (OSError, ValueError):
        return False
    return resolved_path != materials_root


def _prune_empty_material_parents(start_dir: Path) -> None:
    try:
        materials_root = Path(material_files.MATERIALS_DIR).resolve()
        current = start_dir.resolve()
    except OSError:
        return
    while current != materials_root:
        try:
            current.relative_to(materials_root)
        except ValueError:
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _remove_saved_material_directory_safely(
    *,
    directory_name: str | None,
    archive_path: str,
) -> None:
    if directory_name:
        try:
            delete_saved_stage_a_material_archive(directory_name=directory_name)
            return
        except (FileNotFoundError, ValueError, TypeError, OSError, RuntimeError):
            pass
    material_dir = Path(archive_path).parent
    if not _path_is_inside_materials_root(material_dir):
        return
    parent_dir = material_dir.parent
    shutil.rmtree(material_dir, ignore_errors=True)
    _prune_empty_material_parents(parent_dir)


def _rollback_saved_material_write(
    *,
    directory_name: str,
    archive_path: str,
    backup: MaterialDirectoryBackup | None,
) -> None:
    try:
        if backup is not None:
            _restore_material_directory_backup(backup)
        else:
            _remove_saved_material_directory_safely(
                directory_name=directory_name,
                archive_path=archive_path,
            )
        material_files.invalidate_material_library_cache()
    except (FileNotFoundError, ValueError, TypeError, OSError, RuntimeError) as exc:
        log.exception(
            "Gradient card material rollback failed",
            extra={
                "event": "extractor_gradient_card_material_rollback_failed",
                "directory_name": directory_name,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )


def _rollback_existing_material_write(
    *,
    directory_name: str | None,
    backup: MaterialDirectoryBackup | None,
) -> None:
    if backup is None:
        return
    if directory_name is None:
        material_dir, _, _ = backup
        directory_name = _saved_material_directory_name({}, material_dir.name)
    _rollback_saved_material_write(
        directory_name=directory_name,
        archive_path=str(backup[0] / "material.json"),
        backup=backup,
    )


def _rollback_new_material_write(
    *,
    snapshot: NewMaterialCandidateSnapshot | None,
) -> None:
    if snapshot is None:
        return
    parent_dir, stem, existing_candidates = snapshot
    try:
        children = list(parent_dir.iterdir()) if parent_dir.exists() else []
    except OSError:
        return
    for child in children:
        if not child.is_dir() or not _candidate_material_dir_name_matches(child.name, stem):
            continue
        try:
            resolved_child = child.resolve()
        except OSError:
            resolved_child = child.absolute()
        if resolved_child in existing_candidates:
            continue
        if not _path_is_inside_materials_root(child):
            continue
        shutil.rmtree(child, ignore_errors=True)
    _prune_empty_material_parents(parent_dir)


def _register_gradient_card_material_files(
    *,
    registry: FileRegistry,
    registry_session: str,
    archive_path: str,
    stage_a_params_path: str,
    rollback: Callable[[], None],
    event: str,
    session_id: str | None = None,
) -> tuple[str, str]:
    registered_file_ids: list[str] = []
    try:
        material_id = registry.register_path(
            registry_session,
            archive_path,
            ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
        )
        registered_file_ids.append(material_id)
        stage_a_id = registry.register_path(
            registry_session,
            stage_a_params_path,
            ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
        )
    except Exception as exc:
        for file_id in reversed(registered_file_ids):
            try:
                registry.cleanup_file(file_id)
            except Exception:
                pass
        rollback()
        _raise_file_registration_error(
            exc,
            context="Gradient card material file registration",
            event=event,
            session_id=session_id,
        )
    return material_id, stage_a_id


def _remove_path_safely(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _register_stage_a_params_download(
    registry: FileRegistry,
    source_path: str,
) -> str:
    suffix = Path(source_path).suffix or ".json"
    fd, download_path = tempfile.mkstemp(
        prefix="stage_a_params_",
        suffix=suffix,
        dir=TEMP_DIR,
    )
    os.close(fd)
    try:
        shutil.copy2(source_path, download_path)
        return registry.register_path(
            f"stage-a-params:{uuid.uuid4().hex}",
            download_path,
            filename=os.path.basename(source_path) or "stage_A_parameters.json",
            ttl_seconds=STAGE_A_PARAMS_DOWNLOAD_TTL_SECONDS,
            purpose="stage_a_params_download",
        )
    except Exception:
        _remove_path_safely(download_path)
        raise


def _close_session_safely(store: SessionStore, session_id: str | None) -> None:
    if not session_id:
        return
    try:
        store.close(session_id)
    except (ValueError, TypeError, OSError, RuntimeError):
        pass


def _cleanup_registry_session_safely(
    registry: FileRegistry,
    session_id: str | None,
) -> None:
    if not session_id:
        return
    try:
        registry.cleanup_session(session_id)
    except Exception:
        pass


def _raise_internal_route_error(
    exc: Exception,
    *,
    context: str,
    event: str,
    session_id: str | None = None,
) -> None:
    extra: dict[str, object] = {
        "event": event,
        "context": context,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }
    if session_id:
        extra["session_id"] = session_id
    log.exception("Single-stage workflow failed", extra=extra)
    raise HTTPException(
        status_code=500,
        detail=f"{context} failed. Check the server log for details.",
    ) from exc


def _raise_file_registration_error(
    exc: Exception,
    *,
    context: str,
    event: str,
    session_id: str | None = None,
) -> None:
    extra: dict[str, object] = {
        "event": event,
        "context": context,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }
    if session_id:
        extra["session_id"] = session_id
    log.exception("Single-stage file registration failed", extra=extra)
    raise HTTPException(
        status_code=500,
        detail=f"{context} failed. Check the server log for details.",
    ) from exc


@router.post("/extract-single-stage")
async def extractor_extract_single_stage(
    dataset_zip: UploadFile = File(..., description="Single-stage dataset ZIP"),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> SingleStageExtractResponse:
    """Extract a single-stage dataset zip into stage JSON."""
    if not (dataset_zip.filename or "").lower().endswith(".zip"):
        raise HTTPException(
            status_code=422,
            detail="Single-stage dataset must be uploaded as a ZIP file",
        )

    zip_path: str | None = None
    session_id: str | None = None
    try:
        zip_path = await upload_to_tempfile(dataset_zip, suffix=".zip")
        result = extract_single_stage_dataset(zip_path)
        session_id = store.create()
        store.register_temp_file(session_id, zip_path)
        store.register_temp_file(session_id, result.stage_json_path)
        store.put(session_id, "single_stage_stage_json_path", result.stage_json_path)
        store.put(session_id, "single_stage_dataset_summary", result.dataset_summary)
        store.put(session_id, "single_stage_warnings", result.warnings)
    except FileNotFoundError as e:
        _raise_internal_route_error(
            e,
            context="Single-stage dataset extraction",
            event="extractor_extract_single_stage_failed",
            session_id=session_id,
        )
    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=422,
            detail=SINGLE_STAGE_DATASET_MALFORMED_ZIP_DETAIL,
        )
    except ValueError as e:
        detail = _single_stage_dataset_input_error_detail(e)
        if detail is not None:
            raise HTTPException(status_code=422, detail=detail) from e
        _raise_internal_route_error(
            e,
            context="Single-stage dataset extraction",
            event="extractor_extract_single_stage_failed",
            session_id=session_id,
        )
    except (TypeError, OSError, RuntimeError) as e:
        _raise_internal_route_error(
            e,
            context="Single-stage dataset extraction",
            event="extractor_extract_single_stage_failed",
            session_id=session_id,
        )
    finally:
        if zip_path is not None and session_id is None:
            try:
                os.remove(zip_path)
            except OSError:
                pass

    try:
        stage_json_id = registry.register_path(session_id, result.stage_json_path)
    except Exception as exc:
        _cleanup_registry_session_safely(registry, session_id)
        _close_session_safely(store, session_id)
        _raise_file_registration_error(
            exc,
            context="Single-stage dataset file registration",
            event="extractor_extract_single_stage_registration_failed",
            session_id=session_id,
        )
    log.info(
        "Single-stage dataset extracted",
        extra={
            "event": "extractor_extract_single_stage_done",
            "session_id": session_id,
            "dataset_summary_count": (
                len(result.dataset_summary)
                if isinstance(result.dataset_summary, dict)
                else 0
            ),
            "warning_count": len(result.warnings),
            "stage_json_id": stage_json_id,
        },
    )
    return SingleStageExtractResponse(
        session_id=session_id,
        status="ok",
        message=f"Single-stage dataset extracted with {len(result.warnings)} warnings.",
        stage_json_url=f"/api/files/{stage_json_id}",
        warnings=result.warnings,
        dataset_summary=result.dataset_summary,
    )


@router.post("/fit-stage-a")
async def extractor_fit_stage_a(
    session_id: str | None = Form(None),
    stage_json: UploadFile | None = File(None),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> StageAFitResponse:
    """Fit Stage A parameters from single-stage JSON or session state."""
    stage_json_path: str | None = None
    sid_for_registry: str | None = None
    source_mode: str
    created_session_for_upload = False

    if session_id:
        bind_session_id(session_id)
        session_data = store.get(session_id)
        if session_data is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        stage_json_path = session_data.get("single_stage_stage_json_path")
        if not stage_json_path:
            raise HTTPException(
                status_code=400,
                detail="Session does not contain an extracted single-stage dataset",
            )
        if _is_missing_stage_json_path(stage_json_path):
            raise _expired_stage_json_exception()
        sid_for_registry = session_id
        source_mode = "session"
    elif stage_json is not None:
        stage_json_path = await upload_to_tempfile(stage_json, suffix=".json")
        sid_for_registry = store.create()
        created_session_for_upload = True
        store.register_temp_file(sid_for_registry, stage_json_path)
        store.put(sid_for_registry, "single_stage_stage_json_path", stage_json_path)
        source_mode = "upload"
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either session_id or a stage_json upload",
        )

    try:
        result = fit_stage_a_from_stage_json(stage_json_path)
    except FileNotFoundError as e:
        if source_mode == "session" and _is_missing_stage_json_path(stage_json_path):
            raise _expired_stage_json_exception() from e
        if created_session_for_upload:
            _close_session_safely(store, sid_for_registry)
        _raise_internal_route_error(
            e,
            context="Stage A fitting",
            event="extractor_fit_stage_a_failed",
            session_id=sid_for_registry,
        )
    except (ValueError, TypeError, OSError, RuntimeError) as e:
        if created_session_for_upload:
            _close_session_safely(store, sid_for_registry)
        _raise_internal_route_error(
            e,
            context="Stage A fitting",
            event="extractor_fit_stage_a_failed",
            session_id=sid_for_registry,
        )

    try:
        params_id = _register_stage_a_params_download(registry, result.params_path)
    except Exception as exc:
        _remove_path_safely(result.params_path)
        if created_session_for_upload:
            _cleanup_registry_session_safely(registry, sid_for_registry)
            _close_session_safely(store, sid_for_registry)
        _raise_file_registration_error(
            exc,
            context="Stage A parameter file registration",
            event="extractor_fit_stage_a_registration_failed",
            session_id=sid_for_registry,
        )

    store.register_temp_file(sid_for_registry, result.params_path)
    store.put(sid_for_registry, "stage_a_params_path", result.params_path)
    store.put(sid_for_registry, "stage_a_fit_summary", result.fit_summary)

    log.info(
        "Stage A parameters fitted",
        extra={
            "event": "extractor_fit_stage_a_done",
            "session_id": sid_for_registry,
            "params_id": params_id,
            "source_mode": source_mode,
            "fit_summary_count": (
                len(result.fit_summary)
                if isinstance(result.fit_summary, dict)
                else 0
            ),
        },
    )
    return StageAFitResponse(
        status="ok",
        message="Stage A parameters fitted successfully",
        stage_a_params_url=f"/api/files/{params_id}",
        fit_summary=result.fit_summary,
    )


@router.post("/extract-gradient-card-stage-a")
async def extractor_extract_gradient_card_stage_a(
    white_image: UploadFile | None = File(None, description="White-substrate gradient card image"),
    black_image: UploadFile | None = File(None, description="Black-substrate gradient card image"),
    dataset_zip: UploadFile = File(..., description="Generated gradient card kit ZIP"),
    white_corner_points: str = Form(..., description="White image corners JSON [[x,y], ...]"),
    black_corner_points: str = Form(..., description="Black image corners JSON [[x,y], ...]"),
    white_colorchecker_file_id: str | None = Form(
        None,
        description="Private ColorChecker full-image id for the white capture",
    ),
    black_colorchecker_file_id: str | None = Form(
        None,
        description="Private ColorChecker full-image id for the black capture",
    ),
    white_corner_points_width: float | None = Form(
        None,
        description="Width of the white corner coordinate space",
    ),
    white_corner_points_height: float | None = Form(
        None,
        description="Height of the white corner coordinate space",
    ),
    black_corner_points_width: float | None = Form(
        None,
        description="Width of the black corner coordinate space",
    ),
    black_corner_points_height: float | None = Form(
        None,
        description="Height of the black corner coordinate space",
    ),
    manual_white_orientation: str | None = Form(
        None,
        description=(
            "Optional manual orientation label for the white capture; "
            "one of identity, rotate_90_cw, rotate_180, rotate_90_ccw, "
            "flip_horizontal, flip_vertical, transpose, transverse"
        ),
    ),
    manual_black_orientation: str | None = Form(
        None,
        description="Optional manual orientation label for the black capture (same enum as white)",
    ),
    image_source: str | None = Form(
        None,
        description=(
            "Optional gradient-card capture origin tag. Use 'raw' for direct "
            "camera/scanner captures (default) and 'restored' only when the "
            "caller explicitly uses calibrated/restored images."
        ),
    ),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardStageAExtractResponse:
    """Extract Stage A material data from dual gradient-card images."""
    if not (dataset_zip.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="Gradient card kit must be uploaded as a ZIP file")

    white_points = _parse_corner_points(white_corner_points, "white_corner_points")
    black_points = _parse_corner_points(black_corner_points, "black_corner_points")
    manual_white = _normalize_manual_orientation(manual_white_orientation)
    manual_black = _normalize_manual_orientation(manual_black_orientation)
    validated_image_source = _normalize_image_source(image_source)
    has_white_colorchecker = bool(white_colorchecker_file_id)
    has_black_colorchecker = bool(black_colorchecker_file_id)
    if validated_image_source == "restored" and not (
        has_white_colorchecker and has_black_colorchecker
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "image_source='restored' requires both white_colorchecker_file_id "
                "and black_colorchecker_file_id"
            ),
        )
    if (has_white_colorchecker or has_black_colorchecker) and validated_image_source != "restored":
        raise HTTPException(
            status_code=422,
            detail="ColorChecker calibrated images require image_source='restored'",
        )
    zip_path: str | None = None
    session_id: str | None = None
    try:
        if white_colorchecker_file_id:
            white_rgb = load_colorchecker_full_rgb(registry, white_colorchecker_file_id)
            white_points = scale_corner_points(
                white_points,
                source_width=white_corner_points_width,
                source_height=white_corner_points_height,
                target_width=int(white_rgb.shape[1]),
                target_height=int(white_rgb.shape[0]),
            )
        else:
            if white_image is None:
                raise HTTPException(status_code=422, detail="white_image is required")
            white_rgb = await upload_to_ndarray(white_image)
        if black_colorchecker_file_id:
            black_rgb = load_colorchecker_full_rgb(registry, black_colorchecker_file_id)
            black_points = scale_corner_points(
                black_points,
                source_width=black_corner_points_width,
                source_height=black_corner_points_height,
                target_width=int(black_rgb.shape[1]),
                target_height=int(black_rgb.shape[0]),
            )
        else:
            if black_image is None:
                raise HTTPException(status_code=422, detail="black_image is required")
            black_rgb = await upload_to_ndarray(black_image)

        zip_path = await upload_to_tempfile(dataset_zip, suffix=".zip")
        result = extract_stage_a_material_from_gradient_cards(
            white_rgb,
            black_rgb,
            white_points,
            black_points,
            zip_path,
            manual_white_orientation=manual_white,
            manual_black_orientation=manual_black,
            image_source=validated_image_source,
        )
        session_id = store.create()
        bind_session_id(session_id)
        store.register_temp_file(session_id, zip_path)
        store.register_temp_file(session_id, result.params_path)
        store.put(session_id, "gradient_card_stage_a_params", result.params_payload)
        store.put(session_id, "gradient_card_fit_summary", result.fit_summary)
        store.put(session_id, "gradient_card_material_summary", result.material_summary)
        store.put(session_id, "gradient_card_source_summary", result.source_summary)
    except FileNotFoundError as exc:
        _raise_internal_route_error(
            exc,
            context="Gradient card Stage A extraction",
            event="extractor_extract_gradient_card_stage_a_failed",
            session_id=session_id,
        )
    except (TypeError, OSError, RuntimeError) as exc:
        _raise_internal_route_error(
            exc,
            context="Gradient card Stage A extraction",
            event="extractor_extract_gradient_card_stage_a_failed",
            session_id=session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if zip_path is not None and session_id is None:
            try:
                os.remove(zip_path)
            except OSError:
                pass

    try:
        white_warp_id = registry.register_bytes(
            session_id,
            ndarray_to_png_bytes(result.white_warp_rgb),
            "white_gradient_warp.png",
            ttl_seconds=GRADIENT_CARD_PREVIEW_TTL_SECONDS,
        )
        black_warp_id = registry.register_bytes(
            session_id,
            ndarray_to_png_bytes(result.black_warp_rgb),
            "black_gradient_warp.png",
            ttl_seconds=GRADIENT_CARD_PREVIEW_TTL_SECONDS,
        )
        stage_a_id = _register_stage_a_params_download(registry, result.params_path)
    except Exception as exc:
        _cleanup_registry_session_safely(registry, session_id)
        _close_session_safely(store, session_id)
        _raise_file_registration_error(
            exc,
            context="Gradient card Stage A file registration",
            event="extractor_extract_gradient_card_stage_a_registration_failed",
            session_id=session_id,
        )

    log.info(
        "Gradient card Stage A material extracted",
        extra={
            "event": "extractor_extract_gradient_card_stage_a_done",
            "session_id": session_id,
            "warning_count": len(result.warnings),
            "material_summary_count": (
                len(result.material_summary)
                if isinstance(result.material_summary, dict)
                else 0
            ),
            "manual_white_orientation": manual_white,
            "manual_black_orientation": manual_black,
            "stage_a_id": stage_a_id,
        },
    )
    return GradientCardStageAExtractResponse(
        session_id=session_id,
        status="ok",
        message="Gradient card Stage A material extracted successfully",
        stage_a_params_url=f"/api/files/{stage_a_id}",
        white_warp_preview_url=f"/api/files/{white_warp_id}",
        black_warp_preview_url=f"/api/files/{black_warp_id}",
        fit_summary=result.fit_summary,
        material_summary=result.material_summary,
        orientation_ranking=result.fit_summary.get("orientation_ranking"),
        warnings=result.warnings,
    )


@router.post("/save-gradient-card-material")
async def extractor_save_gradient_card_material(
    request: Request,
    session_id: str = Form(...),
    material_name: str = Form(...),
    target_directory_name: str | None = Form(None),
    save_mode: str = Form("merge"),
    brand: str | None = Form(None),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialSaveResponse:
    """Persist a computed gradient-card Stage A material archive."""
    _enforce_material_library_request(request)
    bind_session_id(session_id)
    session_data = store.get(session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    cleaned_material_name = material_name.strip()
    if not cleaned_material_name:
        raise HTTPException(status_code=422, detail="material_name is required")

    params_payload = session_data.get("gradient_card_stage_a_params")
    fit_summary = session_data.get("gradient_card_fit_summary")
    material_summary = session_data.get("gradient_card_material_summary")
    source_summary = session_data.get("gradient_card_source_summary")
    if not isinstance(params_payload, dict) or not isinstance(fit_summary, dict) or not isinstance(material_summary, dict) or not isinstance(source_summary, dict):
        raise HTTPException(
            status_code=400,
            detail="Session does not contain a computed gradient-card Stage A result",
        )

    material_backup: MaterialDirectoryBackup | None = None
    new_material_snapshot: NewMaterialCandidateSnapshot | None = None
    validated_save_mode = save_mode.strip().lower() if isinstance(save_mode, str) else "merge"
    if validated_save_mode not in ("merge", "override"):
        validated_save_mode = "merge"
    existing_directory_name = (
        target_directory_name.strip()
        if isinstance(target_directory_name, str) and target_directory_name.strip()
        else None
    )
    cleaned_brand = brand.strip() if isinstance(brand, str) and brand.strip() else None
    if existing_directory_name is not None:
        material_backup = _create_material_directory_backup_or_raise(
            existing_directory_name,
            event="extractor_save_gradient_card_material_backup_failed",
            session_id=session_id,
        )
    else:
        new_material_snapshot = _create_new_material_candidate_snapshot(
            material_name=cleaned_material_name,
            brand=cleaned_brand,
        )
    try:
        result = save_stage_a_material_archive(
            material_name=cleaned_material_name,
            params_payload=params_payload,
            fit_summary=fit_summary,
            source_summary=source_summary,
            material_summary=material_summary,
            existing_directory_name=existing_directory_name,
            save_mode=validated_save_mode,
            brand=cleaned_brand,
        )
    except FileNotFoundError as exc:
        _rollback_existing_material_write(
            directory_name=existing_directory_name,
            backup=material_backup,
        )
        _rollback_new_material_write(
            snapshot=new_material_snapshot,
        )
        _discard_material_directory_backup(material_backup)
        _raise_gradient_card_material_save_client_error(
            exc,
            status_code=404,
            session_id=session_id,
        )
    except (ValueError, TypeError) as exc:
        _rollback_existing_material_write(
            directory_name=existing_directory_name,
            backup=material_backup,
        )
        _rollback_new_material_write(
            snapshot=new_material_snapshot,
        )
        _discard_material_directory_backup(material_backup)
        _raise_gradient_card_material_save_client_error(
            exc,
            status_code=422,
            session_id=session_id,
        )
    except (OSError, RuntimeError) as exc:
        _rollback_existing_material_write(
            directory_name=existing_directory_name,
            backup=material_backup,
        )
        _rollback_new_material_write(
            snapshot=new_material_snapshot,
        )
        _discard_material_directory_backup(material_backup)
        _raise_internal_route_error(
            exc,
            context="Gradient card material save",
            event="extractor_save_gradient_card_material_failed",
            session_id=session_id,
        )

    try:
        persistent_registry_session = f"material:{uuid.uuid4().hex}"
        verification_count = int(result.material_summary.get("verification_count") or 1)
        directory_name = _saved_material_directory_name(
            result.material_summary,
            str(os.path.splitext(os.path.basename(result.archive_path))[0]),
        )
        material_id, stage_a_id = _register_gradient_card_material_files(
            registry=registry,
            registry_session=persistent_registry_session,
            archive_path=result.archive_path,
            stage_a_params_path=result.stage_a_params_path,
            rollback=lambda: _rollback_saved_material_write(
                directory_name=directory_name,
                archive_path=result.archive_path,
                backup=material_backup,
            ),
            event="extractor_save_gradient_card_material_registration_failed",
            session_id=session_id,
        )
    finally:
        _discard_material_directory_backup(material_backup)

    log.info(
        "Gradient card material saved",
        extra={
            "event": "extractor_save_gradient_card_material_done",
            "session_id": session_id,
            "material_name": cleaned_material_name,
            "directory_name": directory_name,
            "verification_count": verification_count,
            "save_mode": validated_save_mode,
            "material_id": material_id,
        },
    )
    return GradientCardMaterialSaveResponse(
        status="ok",
        message=(
            f"Gradient card verification saved successfully ({verification_count} runs aggregated)"
            if verification_count > 1
            else "Gradient card material saved successfully"
        ),
        material_file_url=f"/api/files/{material_id}",
        stage_a_params_url=f"/api/files/{stage_a_id}",
        material_summary=public_material_response_item(result.material_summary),
    )


@router.delete("/gradient-card-materials/{directory_name:path}")
async def extractor_delete_gradient_card_material(
    request: Request,
    directory_name: str,
) -> GradientCardMaterialDeleteResponse:
    """Delete a saved gradient-card material archive.
    删除已保存的梯度卡耗材档案。
    """
    _enforce_material_library_request(request)
    try:
        result = delete_saved_stage_a_material_archive(directory_name=directory_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, OSError, RuntimeError) as exc:
        _raise_internal_route_error(
            exc,
            context="Gradient card material delete",
            event="extractor_delete_gradient_card_material_failed",
        )

    log.info(
        "Gradient card material deleted",
        extra={
            "event": "extractor_delete_gradient_card_material_done",
            "directory_name": result.directory_name,
            "material_name": result.material_name,
        },
    )
    return GradientCardMaterialDeleteResponse(
        status="ok",
        message="Gradient card material deleted successfully",
        directory_name=result.directory_name,
        material_name=result.material_name,
    )


@router.patch("/gradient-card-materials/{directory_name:path}")
async def extractor_update_gradient_card_material(
    request: Request,
    directory_name: str,
    payload: GradientCardMaterialUpdateRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialUpdateResponse:
    """Update saved gradient-card material metadata.
    更新已保存的梯度卡耗材元数据。
    """
    _enforce_material_library_request(request)
    update_kwargs: dict[str, Any] = {
        "directory_name": directory_name,
        "material_name": payload.material_name,
        "brand": payload.brand,
    }
    if payload.estimated_rgb is not None:
        update_kwargs["estimated_rgb"] = payload.estimated_rgb
    material_backup: MaterialDirectoryBackup | None = None
    material_backup = _create_material_directory_backup_or_raise(
        directory_name,
        event="extractor_update_gradient_card_material_backup_failed",
    )
    try:
        result = update_saved_stage_a_material_archive_metadata(**update_kwargs)
    except FileNotFoundError as exc:
        _rollback_existing_material_write(
            directory_name=directory_name,
            backup=material_backup,
        )
        _discard_material_directory_backup(material_backup)
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError) as exc:
        _rollback_existing_material_write(
            directory_name=directory_name,
            backup=material_backup,
        )
        _discard_material_directory_backup(material_backup)
        raise HTTPException(status_code=422, detail=str(exc))
    except (OSError, RuntimeError) as exc:
        _rollback_existing_material_write(
            directory_name=directory_name,
            backup=material_backup,
        )
        _discard_material_directory_backup(material_backup)
        _raise_internal_route_error(
            exc,
            context="Gradient card material update",
            event="extractor_update_gradient_card_material_failed",
        )

    try:
        persistent_registry_session = f"material-library:{uuid.uuid4().hex}"
        normalized_directory_name = _saved_material_directory_name(
            result.material_summary,
            directory_name,
        )
        material_id, stage_a_id = _register_gradient_card_material_files(
            registry=registry,
            registry_session=persistent_registry_session,
            archive_path=result.archive_path,
            stage_a_params_path=result.stage_a_params_path,
            rollback=lambda: _rollback_saved_material_write(
                directory_name=normalized_directory_name,
                archive_path=result.archive_path,
                backup=material_backup,
            ),
            event="extractor_update_gradient_card_material_registration_failed",
        )
    finally:
        _discard_material_directory_backup(material_backup)
    material_file_url = f"/api/files/{material_id}"
    stage_a_params_url = f"/api/files/{stage_a_id}"
    material_name = (
        payload.material_name
        if payload.material_name is not None
        else str(
            result.material_summary.get("material_name")
            or result.material_summary.get("name")
            or ""
        )
    )
    metadata_keys_updated = sum(
        1
        for value in (payload.material_name, payload.brand, payload.estimated_rgb)
        if value is not None
    )
    log.info(
        "Gradient card material metadata updated",
        extra={
            "event": "extractor_update_gradient_card_material_done",
            "directory_name": normalized_directory_name,
            "material_name": material_name,
            "metadata_keys_updated": metadata_keys_updated,
        },
    )
    return GradientCardMaterialUpdateResponse(
        status="ok",
        message="Gradient card material updated successfully",
        material={
            **public_material_response_item(result.material_summary),
            "material_file_url": material_file_url,
            "stage_a_params_url": stage_a_params_url,
        },
    )


@router.post("/gradient-card-materials/export")
async def extractor_export_gradient_card_materials(
    request: Request,
    payload: MaterialLibraryBulkExportRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialBulkExportResponse:
    """Export multiple saved gradient-card materials as one ZIP archive.
    将多个已保存的梯度卡耗材导出为一个 ZIP 归档。
    """
    _enforce_material_library_request(request)
    try:
        result = export_saved_stage_a_material_archives(
            directory_names=payload.directory_names,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, OSError, RuntimeError) as exc:
        _raise_internal_route_error(
            exc,
            context="Gradient card material export",
            event="extractor_export_gradient_card_materials_failed",
        )

    persistent_registry_session = f"material-export:{uuid.uuid4().hex}"
    archive_registered = False
    try:
        try:
            download_id = registry.register_path(
                persistent_registry_session,
                result.archive_path,
                filename=result.download_filename,
                ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            _raise_file_registration_error(
                exc,
                context="Gradient card material export file registration",
                event="extractor_export_gradient_card_materials_registration_failed",
                session_id=persistent_registry_session,
            )
        archive_registered = True
    finally:
        if not archive_registered:
            try:
                os.unlink(result.archive_path)
            except OSError:
                pass
    log.info(
        "Gradient card materials exported",
        extra={
            "event": "extractor_export_gradient_card_materials_done",
            "exported_count": len(result.exported_directory_names),
            "download_id": download_id,
            "download_filename": result.download_filename,
        },
    )
    return GradientCardMaterialBulkExportResponse(
        status="ok",
        message=f"Exported {len(result.exported_directory_names)} saved materials",
        download_url=f"/api/files/{download_id}",
        filename=result.download_filename,
        exported_count=len(result.exported_directory_names),
        exported_directory_names=result.exported_directory_names,
    )


@router.post("/gradient-card-materials/import")
async def extractor_import_gradient_card_materials(
    request: Request,
    archives: list[UploadFile] = File(...),
) -> GradientCardMaterialBulkImportResponse:
    """Import one or more saved-material ZIP archives into the material library.
    导入一个或多个已保存耗材 ZIP 归档到耗材库。
    """
    _enforce_material_library_request(request)
    if not archives:
        raise HTTPException(status_code=422, detail="At least one archive must be uploaded")

    uploaded_archive_paths: list[str] = []
    imported_materials: list[dict[str, object]] = []
    imported_directory_names: list[str] = []
    try:
        for archive in archives:
            filename = archive.filename or ""
            if not filename.lower().endswith(".zip"):
                raise HTTPException(
                    status_code=422,
                    detail=f"Uploaded file must be a ZIP archive: {filename or '<unnamed>'}",
                )
            archive_path = await upload_to_tempfile(archive, suffix=".zip")
            uploaded_archive_paths.append(archive_path)
            result = import_saved_stage_a_material_archives(archive_path=archive_path)
            imported_materials.extend(result.imported_materials)
            imported_directory_names.extend(
                str(item.get("directory_name") or "")
                for item in result.imported_materials
                if isinstance(item.get("directory_name"), str)
                and str(item.get("directory_name") or "").strip()
            )
    except HTTPException:
        _rollback_imported_materials(imported_directory_names)
        raise
    except FileNotFoundError as exc:
        _rollback_imported_materials(imported_directory_names)
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        _rollback_imported_materials(imported_directory_names)
        safe_detail = _gradient_card_material_import_error_detail(exc)
        if safe_detail is not None:
            log.warning(
                "Gradient card materials import failed",
                extra={
                    "event": "extractor_import_gradient_card_materials_failed",
                    "status_code": 422,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "archives_received": len(archives),
                    "imported_directory_names_count": len(imported_directory_names),
                },
            )
            raise HTTPException(status_code=422, detail=safe_detail) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, OSError, RuntimeError) as exc:
        _rollback_imported_materials(imported_directory_names)
        log.warning(
            "Gradient card materials import failed",
            extra={
                "event": "extractor_import_gradient_card_materials_failed",
                "status_code": 500,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "archives_received": len(archives),
                "imported_directory_names_count": len(imported_directory_names),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=GRADIENT_CARD_MATERIAL_IMPORT_FAILED_DETAIL,
        ) from exc
    finally:
        for archive_path in uploaded_archive_paths:
            try:
                os.remove(archive_path)
            except OSError:
                pass

    log.info(
        "Gradient card materials imported",
        extra={
            "event": "extractor_import_gradient_card_materials_done",
            "imported_count": len(imported_materials),
            "imported_directory_names_count": len(imported_directory_names),
            "archives_received": len(archives),
        },
    )
    return GradientCardMaterialBulkImportResponse(
        status="ok",
        message=f"Imported {len(imported_materials)} saved materials",
        imported_count=len(imported_materials),
        imported_materials=[
            public_material_response_item(item) for item in imported_materials
        ],
    )


@router.get("/gradient-card-materials")
async def extractor_list_gradient_card_materials(
    request: Request,
    include_file_urls: bool = Query(
        False,
        description="Register temporary /api/files URLs for each material archive.",
    ),
    registry: FileRegistry = Depends(get_file_registry),
) -> GradientCardMaterialLibraryResponse:
    """List saved gradient-card material archives.
    列出已保存的梯度卡耗材档案。
    """
    _enforce_material_library_request(request)
    try:
        materials = list_saved_stage_a_material_archives()
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        log.error(
            "Gradient card material library failed",
            extra={
                "event": "extractor_gradient_card_material_library_failed",
                "include_file_urls": bool(include_file_urls),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=GRADIENT_CARD_MATERIAL_LIBRARY_LIST_FAILED_DETAIL,
        ) from exc

    persistent_registry_session = (
        f"material-library:{uuid.uuid4().hex}"
        if include_file_urls
        else None
    )
    response_items: list[dict[str, object]] = []
    try:
        for item in materials:
            material_file_url = (
                f"/api/files/{registry.register_path(
                    persistent_registry_session,
                    str(item['archive_path']),
                    ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
                )}"
                if persistent_registry_session is not None
                else None
            )
            stage_a_path = item.get("stage_a_params_path")
            stage_a_params_url = (
                f"/api/files/{registry.register_path(
                    persistent_registry_session,
                    str(stage_a_path),
                    ttl_seconds=MATERIAL_LIBRARY_FILE_TTL_SECONDS,
                )}"
                if persistent_registry_session is not None
                and isinstance(stage_a_path, str)
                and stage_a_path
                else None
            )
            response_items.append(
                _canonicalize_saved_material_brand(
                    {
                        **public_material_response_item(item),
                        "material_file_url": material_file_url,
                        "stage_a_params_url": stage_a_params_url,
                    }
                )
            )
    except Exception as exc:
        log.error(
            "Gradient card material library file registration failed",
            extra={
                "event": "extractor_gradient_card_material_library_registration_failed",
                "include_file_urls": bool(include_file_urls),
                "material_count": len(materials),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=GRADIENT_CARD_MATERIAL_LIBRARY_LIST_FAILED_DETAIL,
        ) from exc

    return GradientCardMaterialLibraryResponse(
        status="ok",
        message=f"Loaded {len(response_items)} saved materials",
        materials=response_items,
    )


# ---------------------------------------------------------------------------
# Material-solver cache (64³ Lab-grid persistent recipe lookup)
# 耗材求解器缓存（64³ Lab 网格持久化配方查询）
# ---------------------------------------------------------------------------


def _parse_material_directory_names(raw: str) -> list[str]:
    """Parse the ``material_directory_names`` JSON-encoded form field.
    解析 JSON 编码的 ``material_directory_names`` 表单字段。
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid material_directory_names JSON: {exc}",
        )
    if not isinstance(parsed, list) or not all(
        isinstance(name, str) and name.strip() for name in parsed
    ):
        raise HTTPException(
            status_code=422,
            detail="material_directory_names must be a JSON array of non-empty strings",
        )
    cleaned = [name.strip() for name in parsed]
    if not cleaned:
        raise HTTPException(
            status_code=422,
            detail="material_directory_names must contain at least one entry",
        )
    return cleaned


def _validate_cache_parameters(
    layer_count: int, layer_height_mm: float, substrate: str
) -> None:
    if layer_count < _SOLVER_MIN_LAYER_COUNT or layer_count > _SOLVER_MAX_LAYER_COUNT:
        raise HTTPException(
            status_code=422,
            detail=(
                f"layer_count must be in [{_SOLVER_MIN_LAYER_COUNT}, "
                f"{_SOLVER_MAX_LAYER_COUNT}], got {layer_count}"
            ),
        )
    if layer_height_mm not in _CACHE_ALLOWED_LAYER_HEIGHTS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"layer_height_mm must be one of {list(_CACHE_ALLOWED_LAYER_HEIGHTS)}, "
                f"got {layer_height_mm}"
            ),
        )
    if substrate not in ("white", "black"):
        raise HTTPException(
            status_code=422,
            detail=f"substrate must be 'white' or 'black', got {substrate!r}",
        )


def _validate_grid_resolution(grid_resolution: int) -> None:
    """Reject grid resolutions outside the user-facing whitelist.
    拒绝白名单之外的网格分辨率。

    The whitelist is enforced at the API boundary so every shipped value
    has matching UI/docs/build-size expectations. ``core`` keeps looser
    constraints (positive integer) so tests and internal callers can
    still exercise arbitrary resolutions.
    """
    if int(grid_resolution) not in ALLOWED_GRID_RESOLUTIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"grid_resolution must be one of {list(ALLOWED_GRID_RESOLUTIONS)}, "
                f"got {grid_resolution}"
            ),
        )


def _load_palette_or_raise(directory_names: list[str]):
    """Load MaterialParams for the given directory names with API-friendly errors."""
    try:
        return load_multiple_materials(directory_names)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _remove_generated_path(path: str | None) -> None:
    """Best-effort delete for route-owned generated exports."""
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
        except Exception:
            pass
    _remove_generated_path(generated_path)


@router.post("/material-recipe-preview")
async def material_recipe_preview(
    payload: MaterialRecipePreviewRequest,
) -> MaterialRecipePreviewResponse:
    """Forward-simulate a stacked-material recipe to predict its visible color.
    根据选定耗材按顺序叠层，使用 Beer-Lambert 正向模型预测可见颜色。

    Layer count is intentionally unconstrained beyond the schema's
    ``max_length`` so users can preview any depth (the 5-layer limits in
    :data:`MIN_LAYER_COUNT` / :data:`MAX_LAYER_COUNT` only apply to the
    inverse solver, not this forward query).

    层数仅受 schema 上限限制；求解器的 5 层下限不约束本接口。
    """
    materials = _load_palette_or_raise(payload.directory_names)
    recipe = np.arange(len(materials), dtype=np.int32)
    predicted_srgb = predict_material_recipe_srgb(
        recipe=recipe,
        materials=materials,
        layer_height_mm=float(payload.layer_height_mm),
        substrate=payload.substrate,
    )
    predicted_rgb = [int(c) for c in predicted_srgb.tolist()]
    predicted_hex = "#{:02X}{:02X}{:02X}".format(*predicted_rgb)

    layers: list[MaterialRecipeLayerResponse] = []
    for idx, mat in enumerate(materials):
        rgb = [int(c) for c in np.asarray(mat.estimated_rgb).reshape(3).tolist()]
        layers.append(
            MaterialRecipeLayerResponse(
                layer_index=idx,
                directory_name=mat.directory_name,
                material_name=mat.name,
                estimated_rgb=rgb,
                estimated_hex="#{:02X}{:02X}{:02X}".format(*rgb),
            )
        )

    log.info(
        "Material recipe preview computed",
        extra={
            "event": "extractor_material_recipe_preview_done",
            "layer_count": len(materials),
            "layer_height_mm": float(payload.layer_height_mm),
            "substrate": payload.substrate,
            "predicted_hex": predicted_hex,
        },
    )

    return MaterialRecipePreviewResponse(
        status="ok",
        layer_count=len(materials),
        layer_height_mm=float(payload.layer_height_mm),
        substrate=payload.substrate,
        predicted_rgb=predicted_rgb,
        predicted_hex=predicted_hex,
        layers=layers,
    )


@router.post("/generate-material-swatch")
async def generate_material_swatch(
    payload: MaterialRecipeSwatchRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> MaterialRecipeSwatchResponse:
    """Generate a 3MF swatch file from collected material-archive recipes.
    根据收集的耗材档案配方列表生成 3MF 色块验证文件。
    """
    validate_export_device_selection(
        printer_id=payload.printer_id,
        slicer=payload.slicer,
        nozzle_size=payload.nozzle_size,
        device_profile_id=payload.device_profile_id,
        build_plate_id=payload.build_plate_id,
        custom_3mf_template_id=payload.custom_3mf_template_id,
    )
    from api.file_bridge import pil_to_png_bytes
    from api.structured_logging import get_request_id
    from core.material_recipe_swatch import (
        MaterialRecipeSwatchItem,
        generate_material_recipe_swatch,
    )

    items: list[MaterialRecipeSwatchItem] = []
    for recipe_req in payload.recipes:
        materials = _load_palette_or_raise(recipe_req.directory_names)
        mat_names = [m.name for m in materials]
        mat_hexes = [
            "#{:02X}{:02X}{:02X}".format(
                *[int(c) for c in np.asarray(m.estimated_rgb).reshape(3).tolist()]
            )
            for m in materials
        ]
        items.append(
            MaterialRecipeSwatchItem(
                directory_names=recipe_req.directory_names,
                material_names=mat_names,
                material_hexes=mat_hexes,
                result_hex=recipe_req.result_hex,
                layer_height_mm=float(recipe_req.layer_height_mm),
                substrate=recipe_req.substrate,
                material_types=[material.material_type for material in materials],
            )
        )

    output_path, legend_img, status_msg = generate_material_recipe_swatch(
        recipes=items,
        block_size_mm=payload.block_size_mm,
        gap_mm=payload.gap_mm,
        cols=payload.cols,
        structure_mode=payload.structure_mode,
        printer_id=payload.printer_id,
        slicer=payload.slicer,
        nozzle_size=payload.nozzle_size,
        device_profile_id=payload.device_profile_id,
        build_plate_id=payload.build_plate_id,
    )

    if not output_path:
        log.warning(
            "Material recipe swatch export failed",
            extra={
                "event": "extractor_material_swatch_failed",
                "recipe_count": len(items),
                "status_code": 500,
                "error_type": "MaterialSwatchGenerationFailed",
                "error_message": status_msg or "Material swatch generation failed",
            },
        )
        raise HTTPException(
            status_code=500,
            detail=MATERIAL_SWATCH_EXPORT_FAILED_DETAIL,
        )

    request_id = get_request_id()
    unique_suffix = uuid.uuid4().hex
    sid = (
        f"material-recipe-swatch:{request_id}:{unique_suffix}"
        if request_id
        else f"material-recipe-swatch:{unique_suffix}"
    )
    preview_url: str | None = None
    try:
        download_id = registry.register_path(
            sid,
            output_path,
            ttl_seconds=MATERIAL_SWATCH_EXPORT_TTL_SECONDS,
        )
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        _rollback_swatch_registration(
            registry,
            file_ids=[],
            generated_path=output_path,
        )
        _raise_file_registration_error(
            exc,
            context="Material swatch file registration",
            event="extractor_material_swatch_registration_failed",
            session_id=sid,
        )

    if legend_img is not None:
        try:
            preview_bytes = pil_to_png_bytes(legend_img)
            preview_id = registry.register_bytes(
                sid,
                preview_bytes,
                "material_swatch_legend.png",
                ttl_seconds=MATERIAL_SWATCH_EXPORT_TTL_SECONDS,
            )
            preview_url = f"/api/files/{preview_id}"
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            log.warning(
                "Material swatch preview registration failed",
                extra={
                    "event": "extractor_material_swatch_registration_failed",
                    "context": "Material swatch preview registration",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "registration_stage": "preview",
                    "download_id": download_id,
                    "recipe_count": len(items),
                    "session_id": sid,
                },
            )

    log.info(
        "Material recipe swatch generated",
        extra={
            "event": "extractor_material_swatch_done",
            "recipe_count": len(items),
            "download_id": download_id,
            "block_size_mm": payload.block_size_mm,
            "gap_mm": payload.gap_mm,
            "cols": payload.cols,
        },
    )

    return MaterialRecipeSwatchResponse(
        status="ok",
        message=status_msg,
        download_url=f"/api/files/{download_id}",
        preview_url=preview_url,
        recipe_count=len(items),
    )


def _cache_entry_from_metadata(
    metadata: dict,
    *,
    cache_file_size_bytes: int,
) -> MaterialSolverCacheEntryResponse:
    canonical_materials = metadata.get("canonical_materials") or []
    material_dir_names = [
        str(entry.get("directory_name"))
        for entry in canonical_materials
        if isinstance(entry, dict) and entry.get("directory_name")
    ]
    return MaterialSolverCacheEntryResponse(
        palette_hash=str(metadata["cache_id"]),
        material_directory_names=material_dir_names,
        layer_count=int(metadata.get("layer_count", 0)),
        layer_height_mm=float(metadata.get("layer_height_mm", 0.0)),
        substrate=str(metadata.get("substrate", "white")),
        grid_resolution=int(metadata.get("grid_resolution", DEFAULT_GRID_RESOLUTION)),
        total_combinations=int(metadata.get("total_combinations", 0)),
        valid_cell_count=int(metadata.get("valid_cell_count", 0)),
        total_cell_count=int(metadata.get("total_cell_count", 0)),
        mean_delta_e=float(metadata.get("mean_delta_e", 0.0)),
        max_delta_e=float(metadata.get("max_delta_e", 0.0)),
        build_time_seconds=float(metadata.get("build_time_seconds", 0.0)),
        built_at=metadata.get("built_at"),
        cache_file_size_bytes=int(cache_file_size_bytes),
    )


def _validate_candidate_budget(candidate_budget: int) -> None:
    if candidate_budget <= 0 or candidate_budget > MAX_PERSISTED_CANDIDATE_BUDGET:
        raise HTTPException(
            status_code=422,
            detail=(
                "candidate_budget must be in "
                f"[1, {MAX_PERSISTED_CANDIDATE_BUDGET}], got {candidate_budget}"
            ),
        )


def _runtime_entry_from_metadata(
    metadata: dict,
    *,
    cache_file_size_bytes: int,
) -> MaterialSolverRuntimeEntryResponse:
    canonical_materials = metadata.get("canonical_materials") or []
    material_dir_names = [
        str(entry.get("directory_name"))
        for entry in canonical_materials
        if isinstance(entry, dict) and entry.get("directory_name")
    ]
    inverse = metadata.get("inverse_refinement") or {}
    return MaterialSolverRuntimeEntryResponse(
        palette_hash=str(metadata["cache_id"]),
        material_directory_names=material_dir_names,
        layer_count=int(metadata.get("layer_count", 0)),
        layer_height_mm=float(metadata.get("layer_height_mm", 0.0)),
        substrate=str(metadata.get("substrate", "white")),
        mode=str(metadata.get("mode", "candidate_hybrid")),
        candidate_budget=int(metadata.get("candidate_budget", 0)),
        candidate_count=int(
            metadata.get("candidate_count", metadata.get("valid_cell_count", 0))
        ),
        candidate_pool_multiplier=int(metadata.get("candidate_pool_multiplier", 8)),
        batch_recipe_count=int(metadata.get("batch_recipe_count", 0)),
        lab_grid_resolution=int(
            metadata.get("lab_grid_resolution", metadata.get("grid_resolution", 64))
        ),
        seed=int(metadata.get("seed", 0)),
        inverse_refinement_enabled=bool(inverse.get("enabled", False)),
        built_at=metadata.get("built_at"),
        cache_file_size_bytes=int(cache_file_size_bytes),
    )


def _runtime_entry_from_metadata_record(record: Any) -> MaterialSolverRuntimeEntryResponse:
    return _runtime_entry_from_metadata(
        record.metadata,
        cache_file_size_bytes=int(record.cache_file_size_bytes),
    )


def _palette_cache_identity(materials: list[MaterialParams]) -> str:
    return json.dumps(describe_palette(materials), sort_keys=True, separators=(",", ":"))


def _runtime_build_key(
    *,
    palette_hash: str,
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    candidate_budget: int,
) -> tuple[str, int, str, str, int]:
    return (
        str(palette_hash),
        int(layer_count),
        f"{float(layer_height_mm):.12g}",
        str(substrate),
        int(candidate_budget),
    )


def _get_runtime_build_lock(
    key: tuple[str, int, str, str, int],
) -> threading.Lock:
    with _RUNTIME_BUILD_LOCKS_GUARD:
        lock = _RUNTIME_BUILD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _RUNTIME_BUILD_LOCKS[key] = lock
        return lock


@router.get(
    "/material-solver-caches",
    dependencies=[Depends(require_local_app_origin)],
)
async def material_solver_cache_list() -> MaterialSolverCacheListResponse:
    """List every persisted solver-cache entry with its metadata.
    列出所有已持久化的求解器缓存条目及其元数据。
    """
    try:
        raw_entries = list_cached_entries()
    except (OSError, ValueError) as exc:
        log.error(
            "Material solver cache list failed",
            extra={
                "event": "material_solver_cache_list_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=MATERIAL_SOLVER_CACHE_LIST_FAILED_DETAIL,
        ) from exc
    entries = [
        _cache_entry_from_metadata(
            entry,
            cache_file_size_bytes=int(entry.get("cache_file_size_bytes", 0)),
        )
        for entry in raw_entries
    ]
    return MaterialSolverCacheListResponse(
        status="ok",
        message=f"Loaded {len(entries)} cache entries",
        entries=entries,
    )


@router.post(
    "/material-solver-cache/status",
    dependencies=[Depends(require_local_app_origin)],
)
async def material_solver_cache_status(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialSolverCacheStatusResponse:
    """Check whether a cache exists for the given palette & parameters.
    查询指定调色板与参数组合的缓存是否存在。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_grid_resolution(grid_resolution)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = _palette_cache_identity(materials)
    # Use the fallback loader so exact-mode caches (grid=0) and any-grid
    # bucketed caches are discoverable regardless of the caller's requested
    # grid_resolution. Without this, an exact-mode cache (saved as -g000)
    # would be invisible when the UI requests grid_resolution=256.
    # 使用 fallback 加载器，确保精确模式缓存（-g000）和其它分辨率的分桶
    # 缓存都能被发现，不受前端请求的 grid_resolution 限制。
    cache, actual_grid = load_material_solver_cache_with_fallback(
        materials, layer_count, layer_height_mm, substrate,
        grid_resolution=grid_resolution,
    )
    cached_flag = cache is not None
    if cache is not None:
        palette_hash = str(cache.metadata["cache_id"])
    # Resolve the actual npz_path for file size reporting.
    if cache is not None:
        npz_path = cache_file_path(
            materials, layer_count, layer_height_mm, substrate,
            grid_resolution=actual_grid if actual_grid is not None else grid_resolution,
        )
    else:
        npz_path = cache_file_path(
            materials, layer_count, layer_height_mm, substrate,
            grid_resolution=grid_resolution,
        )
    log.info(
        "Material solver cache status checked",
        extra={
            "event": "material_solver_cache_status_done",
            "cached": cached_flag,
            "palette_hash": palette_hash,
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "grid_resolution": grid_resolution,
            "actual_grid_resolution": actual_grid,
        },
    )
    if cache is None:
        return MaterialSolverCacheStatusResponse(
            status="ok",
            message="No cache found for this combination",
            cached=False,
            palette_hash=palette_hash,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            entry=None,
        )
    try:
        file_size = npz_path.stat().st_size
    except OSError:
        file_size = 0
    entry = _cache_entry_from_metadata(
        cache.metadata,
        cache_file_size_bytes=file_size,
    )
    return MaterialSolverCacheStatusResponse(
        status="ok",
        message="Cache found",
        cached=True,
        palette_hash=palette_hash,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        entry=entry,
    )


@router.post(
    "/material-solver-cache/build",
    dependencies=[Depends(require_local_app_origin)],
)
async def material_solver_cache_build(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialSolverCacheBuildResponse:
    """Build and persist a solver cache synchronously.
    同步构建并持久化求解器缓存。

    Build time is roughly ``M**N`` combinations times a few tens of FLOPs per
    combo. For 10 materials × 10 layers this can take 30-180 seconds; callers
    should treat the request as long-running and surface a progress indicator.
    The build itself is executed on a worker thread to keep the event loop free.
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    if layer_count > _SOLVER_MITM_MAX_LAYER_COUNT:
        raise HTTPException(
            status_code=422,
            detail=(
                f"穷举求解缓存最多支持 {_SOLVER_MITM_MAX_LAYER_COUNT} 层；更深的叠层请构建"
                "候选运行时（/material-solver-runtime/build），它使用逐层 DP。"
                f" / The exhaustive solver cache supports at most "
                f"{_SOLVER_MITM_MAX_LAYER_COUNT} layers; build the candidate runtime "
                "(/material-solver-runtime/build) for deeper stacks."
            ),
        )
    _validate_grid_resolution(grid_resolution)
    materials = _load_palette_or_raise(dir_names)
    def _run_build():
        return build_material_solver_cache(
            materials,
            layer_count,
            layer_height_mm,
            substrate,
            grid_resolution=grid_resolution,
        )

    try:
        cache = await anyio.to_thread.run_sync(_run_build)
    except (ValueError, TypeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        log.error(
            "Material solver cache build failed",
            extra={
                "event": "material_solver_cache_build_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "material_count": len(dir_names),
                "layer_count": layer_count,
                "layer_height_mm": layer_height_mm,
                "substrate": substrate,
                "grid_resolution": grid_resolution,
            },
        )
        raise HTTPException(
            status_code=500,
            detail=MATERIAL_SOLVER_CACHE_BUILD_FAILED_DETAIL,
        ) from exc

    try:
        npz_path = await anyio.to_thread.run_sync(save_material_solver_cache, cache)
    except OSError as exc:
        log.error(
            "Material solver cache save failed",
            extra={
                "event": "material_solver_cache_build_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "material_count": len(dir_names),
                "layer_count": layer_count,
                "layer_height_mm": layer_height_mm,
                "substrate": substrate,
                "grid_resolution": grid_resolution,
            },
        )
        raise HTTPException(
            status_code=500,
            detail=MATERIAL_SOLVER_CACHE_BUILD_FAILED_DETAIL,
        ) from exc

    try:
        file_size = npz_path.stat().st_size
    except OSError:
        file_size = 0
    entry = _cache_entry_from_metadata(
        cache.metadata,
        cache_file_size_bytes=file_size,
    )
    log.info(
        "Material solver cache built",
        extra={
            "event": "material_solver_cache_build_done",
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "grid_resolution": grid_resolution,
            "valid_cell_count": entry.valid_cell_count,
            "total_cell_count": entry.total_cell_count,
            "mean_delta_e": entry.mean_delta_e,
            "cache_file_size_bytes": file_size,
        },
    )
    return MaterialSolverCacheBuildResponse(
        status="ok",
        message=(
            f"Built material solver cache for {len(dir_names)} materials, "
            f"N={layer_count}, t={layer_height_mm} mm, substrate={substrate} "
            f"({entry.valid_cell_count}/{entry.total_cell_count} cells, "
            f"mean ΔE={entry.mean_delta_e:.2f})"
        ),
        entry=entry,
    )


@router.post(
    "/material-solver-cache/delete",
    dependencies=[Depends(require_local_app_origin)],
)
async def material_solver_cache_delete(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialSolverCacheDeleteResponse:
    """Delete a persisted solver cache entry.
    删除已持久化的求解器缓存条目。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_grid_resolution(grid_resolution)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = _palette_cache_identity(materials)
    deleted = delete_cached_entry(
        materials, layer_count, layer_height_mm, substrate,
        grid_resolution=grid_resolution,
    )
    log.info(
        "Material solver cache delete checked",
        extra={
            "event": "material_solver_cache_delete_done",
            "deleted": bool(deleted),
            "palette_hash": palette_hash,
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "grid_resolution": grid_resolution,
        },
    )
    return MaterialSolverCacheDeleteResponse(
        status="ok",
        message=(
            "Cache deleted" if deleted else "No cache entry found for the given parameters"
        ),
        deleted=bool(deleted),
        palette_hash=palette_hash,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
    )


@router.post(
    "/material-solver-runtime/status",
    dependencies=[Depends(require_local_app_origin)],
)
async def material_solver_runtime_status(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    candidate_budget: int = Form(DEFAULT_PERSISTED_CANDIDATE_BUDGET),
) -> MaterialSolverRuntimeStatusResponse:
    """Check whether a persisted hybrid candidate runtime exists.
    查询指定组合是否已有持久化 hybrid candidate runtime。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_candidate_budget(candidate_budget)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = _palette_cache_identity(materials)
    metadata_record = load_material_candidate_runtime_metadata(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        candidate_budget=candidate_budget,
    )
    cached_flag = metadata_record is not None
    if metadata_record is not None:
        palette_hash = str(metadata_record.metadata["cache_id"])
    log.info(
        "Material solver runtime status checked",
        extra={
            "event": "material_solver_runtime_status_done",
            "cached": cached_flag,
            "palette_hash": palette_hash,
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "candidate_budget": candidate_budget,
        },
    )
    if metadata_record is None:
        return MaterialSolverRuntimeStatusResponse(
            status="ok",
            message="No hybrid runtime found for this combination",
            cached=False,
            palette_hash=palette_hash,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            candidate_budget=candidate_budget,
            entry=None,
        )

    entry = _runtime_entry_from_metadata_record(metadata_record)
    return MaterialSolverRuntimeStatusResponse(
        status="ok",
        message="Hybrid runtime found",
        cached=True,
        palette_hash=palette_hash,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        candidate_budget=candidate_budget,
        entry=entry,
    )


@router.post(
    "/material-solver-runtime/build",
    dependencies=[Depends(require_local_app_origin)],
)
async def material_solver_runtime_build(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    candidate_budget: int = Form(DEFAULT_PERSISTED_CANDIDATE_BUDGET),
) -> MaterialSolverRuntimeBuildResponse:
    """Build and persist a hybrid candidate runtime synchronously.
    同步构建并持久化 hybrid candidate runtime。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_candidate_budget(candidate_budget)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = _palette_cache_identity(materials)
    config = MaterialCandidateCacheConfig.persisted_for_budget(
        int(candidate_budget)
    )
    build_key = _runtime_build_key(
        palette_hash=palette_hash,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        candidate_budget=candidate_budget,
    )

    def _load_existing_metadata():
        return load_material_candidate_runtime_metadata(
            materials,
            layer_count,
            layer_height_mm,
            substrate,
            candidate_budget=candidate_budget,
        )

    def _run_build_or_reuse():
        key_lock = _get_runtime_build_lock(build_key)
        with key_lock:
            metadata_record = _load_existing_metadata()
            if metadata_record is not None:
                return metadata_record, False
            with _RUNTIME_BUILD_GLOBAL_SEMAPHORE:
                metadata_record = _load_existing_metadata()
                if metadata_record is not None:
                    return metadata_record, False
                runtime = build_material_candidate_runtime(
                    materials=materials,
                    layer_count=layer_count,
                    layer_height_mm=layer_height_mm,
                    substrate=substrate,
                    config=config,
                )
                try:
                    npz_path = save_material_candidate_runtime(runtime)
                except OSError as exc:
                    raise RuntimeError(f"Failed to save runtime: {exc}") from exc
                try:
                    file_size = npz_path.stat().st_size
                except OSError:
                    file_size = 0
                return (
                    MaterialCandidateRuntimeMetadata(
                        metadata=runtime.metadata,
                        cache_file_path=npz_path,
                        cache_file_size_bytes=file_size,
                    ),
                    True,
                )

    try:
        metadata_record, built = await anyio.to_thread.run_sync(_run_build_or_reuse)
    except (ValueError, TypeError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        log.error(
            "Material solver runtime build failed",
            extra={
                "event": "material_solver_runtime_build_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "material_count": len(dir_names),
                "layer_count": layer_count,
                "layer_height_mm": layer_height_mm,
                "substrate": substrate,
                "candidate_budget": candidate_budget,
            },
        )
        raise HTTPException(
            status_code=500,
            detail=MATERIAL_SOLVER_RUNTIME_BUILD_FAILED_DETAIL,
        ) from exc

    entry = _runtime_entry_from_metadata_record(metadata_record)
    log.info(
        "Material solver runtime build checked",
        extra={
            "event": "material_solver_runtime_build_done",
            "built": bool(built),
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "candidate_budget": candidate_budget,
            "candidate_count": entry.candidate_count,
            "cache_file_size_bytes": entry.cache_file_size_bytes,
        },
    )
    return MaterialSolverRuntimeBuildResponse(
        status="ok",
        message=(
            (
                f"Built hybrid material solver runtime for {len(dir_names)} materials"
                if built
                else f"Hybrid material solver runtime already exists for {len(dir_names)} materials"
            )
            + (
                f", N={layer_count}, t={layer_height_mm} mm, "
                f"substrate={substrate}, budget={candidate_budget} "
                f"({entry.candidate_count} candidates)"
            )
        ),
        entry=entry,
    )


@router.post(
    "/material-solver-runtime/delete",
    dependencies=[Depends(require_local_app_origin)],
)
async def material_solver_runtime_delete(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    candidate_budget: int = Form(DEFAULT_PERSISTED_CANDIDATE_BUDGET),
) -> MaterialSolverRuntimeDeleteResponse:
    """Delete a persisted hybrid candidate runtime entry.
    删除持久化 hybrid candidate runtime 条目。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_candidate_budget(candidate_budget)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = _palette_cache_identity(materials)
    deleted = delete_material_candidate_runtime(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        candidate_budget=candidate_budget,
    )
    log.info(
        "Material solver runtime delete checked",
        extra={
            "event": "material_solver_runtime_delete_done",
            "deleted": bool(deleted),
            "palette_hash": palette_hash,
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "candidate_budget": candidate_budget,
        },
    )
    return MaterialSolverRuntimeDeleteResponse(
        status="ok",
        message=(
            "Hybrid runtime deleted"
            if deleted
            else "No hybrid runtime entry found for the given parameters"
        ),
        deleted=bool(deleted),
        palette_hash=palette_hash,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        candidate_budget=candidate_budget,
    )


@router.post(
    "/material-solver-runtime/details",
    dependencies=[Depends(require_local_app_origin)],
)
async def material_solver_runtime_details(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    candidate_budget: int = Form(DEFAULT_PERSISTED_CANDIDATE_BUDGET),
    max_points: int = Form(8000, ge=128, le=50000),
) -> MaterialSolverRuntimeDetailsResponse:
    """Return a LUT-details-shaped payload for a built hybrid runtime.
    返回已构建 hybrid runtime 的 LUT 详情同构可视化载荷。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_candidate_budget(candidate_budget)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = _palette_cache_identity(materials)
    runtime = load_material_candidate_runtime(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        candidate_budget=candidate_budget,
    )
    if runtime is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No hybrid runtime found for this combination. Build the "
                "runtime first via /material-solver-runtime/build."
            ),
        )

    details = build_material_runtime_details(runtime, max_points=int(max_points))
    palette_hash = str(runtime.metadata["cache_id"])
    log.info(
        "Material solver runtime details rendered",
        extra={
            "event": "material_solver_runtime_details_done",
            "palette_hash": palette_hash,
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "candidate_budget": candidate_budget,
            "candidate_count": details.candidate_count,
            "plotted_point_count": details.coverage_stats.plotted_point_count,
        },
    )

    coverage = LutCoverageStatsResponse(
        entry_count=details.coverage_stats.entry_count,
        plotted_point_count=details.coverage_stats.plotted_point_count,
        l_range=LutAxisRange(
            min=details.coverage_stats.l_range.min,
            max=details.coverage_stats.l_range.max,
        ),
        a_range=LutAxisRange(
            min=details.coverage_stats.a_range.min,
            max=details.coverage_stats.a_range.max,
        ),
        b_range=LutAxisRange(
            min=details.coverage_stats.b_range.min,
            max=details.coverage_stats.b_range.max,
        ),
        r_range=LutAxisRange(
            min=details.coverage_stats.r_range.min,
            max=details.coverage_stats.r_range.max,
        ),
        g_range=LutAxisRange(
            min=details.coverage_stats.g_range.min,
            max=details.coverage_stats.g_range.max,
        ),
        b_rgb_range=LutAxisRange(
            min=details.coverage_stats.b_rgb_range.min,
            max=details.coverage_stats.b_rgb_range.max,
        ),
    )
    return MaterialSolverRuntimeDetailsResponse(
        status="ok",
        message=(
            f"Runtime details for {len(dir_names)} materials, "
            f"budget={candidate_budget}"
        ),
        palette_hash=palette_hash,
        material_directory_names=list(dir_names),
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        grid_resolution=details.grid_resolution,
        valid_cell_count=details.valid_cell_count,
        total_cell_count=details.total_cell_count,
        candidate_budget=details.candidate_budget,
        candidate_count=details.candidate_count,
        coverage_stats=coverage,
        lab_points=[
            LutPlotPoint(
                x=point.x,
                y=point.y,
                hex_color=point.hex_color,
                rgb=point.rgb,
                label=point.label,
            )
            for point in details.lab_points
        ],
        lab_points_3d=[
            LutPlotPoint3D(
                l=point.l,
                a=point.a,
                b=point.b,
                hex_color=point.hex_color,
                rgb=point.rgb,
                label=point.label,
            )
            for point in details.lab_points_3d
        ],
        lab_hull=[LutHullPoint(x=x, y=y) for x, y in details.lab_hull],
        rgb_points=[
            LutPlotPoint(
                x=point.x,
                y=point.y,
                hex_color=point.hex_color,
                rgb=point.rgb,
                label=point.label,
            )
            for point in details.rgb_points
        ],
    )


# ---------------------------------------------------------------------------
# Material color suggestions (picker support for material-archive mode)
# 耗材颜色建议（材料档案模式取色器支持）
# ---------------------------------------------------------------------------


def _parse_target_hex(raw: str) -> tuple[str, tuple[int, int, int]]:
    """Normalise a user-supplied hex color to ``(hex_noprefix, (r,g,b))``.
    将用户输入的 hex 颜色规范化为 ``(去前缀 hex, (r,g,b))``。

    Accepts ``#RRGGBB`` / ``RRGGBB`` (case-insensitive) and the 3-digit short
    form ``#RGB``. Rejects malformed inputs with HTTP 422 so the frontend can
    surface a validation error without leaking tracebacks.
    """
    if not isinstance(raw, str):
        raise HTTPException(status_code=422, detail="target_hex must be a string")
    cleaned = raw.strip().lstrip("#").lower()
    if len(cleaned) == 3:
        cleaned = "".join(ch * 2 for ch in cleaned)
    if len(cleaned) != 6 or any(c not in "0123456789abcdef" for c in cleaned):
        raise HTTPException(
            status_code=422,
            detail=f"target_hex must be #RRGGBB or #RGB, got {raw!r}",
        )
    r = int(cleaned[0:2], 16)
    g = int(cleaned[2:4], 16)
    b = int(cleaned[4:6], 16)
    return cleaned, (r, g, b)


def _validate_suggest_parameters(top_k: int, min_spacing: float) -> None:
    if top_k <= 0 or top_k > 100:
        raise HTTPException(
            status_code=422,
            detail=f"top_k must be in [1, 100], got {top_k}",
        )
    if min_spacing < 0.0 or min_spacing > 50.0:
        raise HTTPException(
            status_code=422,
            detail=f"min_spacing must be in [0, 50], got {min_spacing}",
        )

def _suggestions_to_response_items(
    suggestions: list[ColorSuggestion],
) -> list[MaterialColorSuggestionItem]:
    items: list[MaterialColorSuggestionItem] = []
    for suggestion in suggestions:
        rgb = [int(v) for v in suggestion.matched_rgb.tolist()]
        recipe = [int(v) for v in suggestion.recipe.tolist()]
        items.append(
            MaterialColorSuggestionItem(
                hex="#{:02X}{:02X}{:02X}".format(*rgb),
                rgb=rgb,
                delta_e=float(suggestion.delta_e),
                recipe=recipe,
                recipe_display="[" + ",".join(str(v) for v in recipe) + "]",
            )
        )
    return items


@router.post(
    "/material-solver-cache/details",
    dependencies=[Depends(require_local_app_origin)],
)
async def material_solver_cache_details(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
    max_points: int = Form(8000, ge=128, le=50000),
) -> MaterialSolverCacheDetailsResponse:
    """Return a LUT-details-shaped visualization payload for a built cache.
    返回与 LUT 详情同构的可视化载荷，用于已构建的求解器缓存。

    HTTP semantics note: this endpoint is registered as ``POST`` to keep
    its parameter style aligned with the sibling ``status`` / ``build`` /
    ``delete`` / ``suggest-colors`` endpoints (form-encoded, including a
    JSON-encoded ``material_directory_names`` array). It is **semantically
    read-only**: it loads the cache, computes derived statistics, and never
    mutates disk state.

    HTTP 语义说明：本端点用 ``POST`` 是为了与 ``status`` / ``build`` /
    ``delete`` / ``suggest-colors`` 兄弟端点保持参数风格一致（form-encoded，
    含 JSON 编码数组）。**语义上是只读的**：加载缓存并计算派生统计，从不改盘。

    Loads the cache for the given ``(palette, layer_count, layer_height_mm,
    substrate, grid_resolution)`` combination, projects its bucket centers
    into the four chart spaces (Lab a*/b*, Lab 3D, isometric RGB, hull),
    and returns the same field layout the LUT details endpoint uses. The
    frontend can therefore reuse the existing scatter chart components.

    加载指定组合的缓存，把每个被占用桶投影到四个图表空间，返回与 LUT 详情端点
    同构的字段布局；前端可直接复用既有散点图组件。

    Args:
        material_directory_names: JSON-encoded list of material directory
            names. (JSON 编码的耗材目录名列表)
        layer_count: Recipe layer count. (配方层数)
        layer_height_mm: Layer thickness in millimetres. (层厚 mm)
        substrate: Substrate id ("white" or "black"). (基底)
        grid_resolution: Lab-grid resolution that produced the cache.
            (该缓存的 Lab 网格分辨率)
        max_points: Maximum scatter points returned; values above are
            uniformly downsampled deterministically. (散点数上限)

    Returns:
        :class:`MaterialSolverCacheDetailsResponse` ready for chart rendering.

    Raises:
        HTTPException: 404 when no cache exists; 422 on invalid params.
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_grid_resolution(grid_resolution)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = _palette_cache_identity(materials)

    cache, actual_grid = load_material_solver_cache_with_fallback(
        materials, layer_count, layer_height_mm, substrate,
        grid_resolution=grid_resolution,
    )
    if cache is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No solver cache found for this combination. Build the "
                "cache first via /material-solver-cache/build."
            ),
        )

    effective_grid = int(actual_grid) if actual_grid is not None else int(grid_resolution)
    palette_hash = str(cache.metadata["cache_id"])
    details = build_material_cache_details(
        cache,
        palette_hash=palette_hash,
        grid_resolution=effective_grid,
        max_points=int(max_points),
    )
    log.info(
        "Material solver cache details rendered",
        extra={
            "event": "material_solver_cache_details_done",
            "palette_hash": palette_hash,
            "material_count": len(dir_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "grid_resolution": effective_grid,
            "valid_cell_count": details.valid_cell_count,
            "plotted_point_count": details.coverage_stats.plotted_point_count,
        },
    )

    coverage = LutCoverageStatsResponse(
        entry_count=details.coverage_stats.entry_count,
        plotted_point_count=details.coverage_stats.plotted_point_count,
        l_range=LutAxisRange(
            min=details.coverage_stats.l_range.min,
            max=details.coverage_stats.l_range.max,
        ),
        a_range=LutAxisRange(
            min=details.coverage_stats.a_range.min,
            max=details.coverage_stats.a_range.max,
        ),
        b_range=LutAxisRange(
            min=details.coverage_stats.b_range.min,
            max=details.coverage_stats.b_range.max,
        ),
        r_range=LutAxisRange(
            min=details.coverage_stats.r_range.min,
            max=details.coverage_stats.r_range.max,
        ),
        g_range=LutAxisRange(
            min=details.coverage_stats.g_range.min,
            max=details.coverage_stats.g_range.max,
        ),
        b_rgb_range=LutAxisRange(
            min=details.coverage_stats.b_rgb_range.min,
            max=details.coverage_stats.b_rgb_range.max,
        ),
    )
    return MaterialSolverCacheDetailsResponse(
        status="ok",
        message=f"Cache details for {len(dir_names)} materials, grid={effective_grid}",
        palette_hash=palette_hash,
        material_directory_names=list(dir_names),
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        grid_resolution=effective_grid,
        valid_cell_count=details.valid_cell_count,
        total_cell_count=details.total_cell_count,
        coverage_stats=coverage,
        lab_points=[
            LutPlotPoint(
                x=point.x,
                y=point.y,
                hex_color=point.hex_color,
                rgb=list(point.rgb),
                label=point.label,
            )
            for point in details.lab_points
        ],
        lab_points_3d=[
            LutPlotPoint3D(
                l=point.l,
                a=point.a,
                b=point.b,
                hex_color=point.hex_color,
                rgb=list(point.rgb),
                label=point.label,
            )
            for point in details.lab_points_3d
        ],
        lab_hull=[LutHullPoint(x=point[0], y=point[1]) for point in details.lab_hull],
        rgb_points=[
            LutPlotPoint(
                x=point.x,
                y=point.y,
                hex_color=point.hex_color,
                rgb=list(point.rgb),
                label=point.label,
            )
            for point in details.rgb_points
        ],
    )


@router.post(
    "/material-solver-cache/suggest-colors",
    dependencies=[Depends(require_local_app_origin)],
)
async def material_solver_cache_suggest_colors(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    target_hex: str = Form(...),
    top_k: int = Form(DEFAULT_SUGGEST_TOP_K),
    min_spacing: float = Form(DEFAULT_SUGGEST_MIN_SPACING),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialColorSuggestionsResponse:
    """Return up to ``top_k`` achievable colors near ``target_hex``.
    为 ``target_hex`` 返回至多 ``top_k`` 个可达近似色建议。

    Fast path: when a persisted :class:`core.material_cache.MaterialSolverCache`
    matches the ``(palette, N, t, substrate)`` parameters the response is
    served from the KDTree-over-Lab-buckets lookup (microseconds per query).
    Runtime path: when the exact cache is absent but a persisted hybrid
    candidate runtime exists, query that bounded runtime instead of falling
    back to exhaustive MITM. Fallback: no reusable solver data available → runs
    :func:`core.material_color_solver.suggest_colors_for_target` in a worker
    thread until it completes, is cancelled, or fails.

    The frontend reports ``source`` in the response so it can explain whether
    the suggestion came from exact cache, hybrid runtime, or live MITM fallback.
    前端会根据 ``source`` 判断结果来自精确缓存、hybrid runtime 还是实时 MITM。
    """
    dir_names = _parse_material_directory_names(material_directory_names)
    _validate_cache_parameters(layer_count, layer_height_mm, substrate)
    _validate_grid_resolution(grid_resolution)
    _validate_suggest_parameters(top_k, min_spacing)
    target_hex_clean, target_rgb_tuple = _parse_target_hex(target_hex)
    materials = _load_palette_or_raise(dir_names)
    palette_hash = _palette_cache_identity(materials)

    target_rgb_arr = np.asarray(target_rgb_tuple, dtype=np.uint8)

    cache = load_material_solver_cache(
        materials, layer_count, layer_height_mm, substrate,
        grid_resolution=grid_resolution,
    )
    if cache is not None:
        try:
            suggestions = cache.lookup_top_k(
                target_rgb_arr,
                materials,
                top_k=top_k,
                min_spacing=min_spacing,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        source = "cache"
        message = (
            f"Returned {len(suggestions)} achievable colors "
            f"(via solver cache, {cache.valid_cell_count} cells)."
        )
    else:
        runtime = load_material_candidate_runtime(
            materials,
            layer_count,
            layer_height_mm,
            substrate,
            candidate_budget=DEFAULT_PERSISTED_CANDIDATE_BUDGET,
        )
        if runtime is None and layer_count > _SOLVER_MITM_MAX_LAYER_COUNT:
            # MITM cannot enumerate deep stacks; build a preview runtime
            # (layer-wise DP, memoized in-process) instead.
            # MITM 无法枚举深叠层，改为构建预览运行时（逐层 DP，进程内缓存）。
            def _build_preview_runtime():
                return build_material_candidate_runtime(
                    materials=materials,
                    layer_count=layer_count,
                    layer_height_mm=layer_height_mm,
                    substrate=substrate,
                    config=MaterialCandidateCacheConfig.preview_safe(),
                )

            runtime = await anyio.to_thread.run_sync(_build_preview_runtime)
        if runtime is not None:
            try:
                suggestions = runtime.lookup_top_k(
                    target_rgb_arr,
                    materials,
                    top_k=top_k,
                    min_spacing=min_spacing,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            source = "runtime"
            message = (
                f"Returned {len(suggestions)} achievable colors "
                f"(via hybrid runtime, {runtime.valid_cell_count} candidates)."
            )
        else:
            def _run_suggest() -> list[ColorSuggestion]:
                return suggest_colors_for_target(
                    target_rgb_arr,
                    materials,
                    layer_count=layer_count,
                    layer_height_mm=layer_height_mm,
                    substrate=substrate,
                    top_k=top_k,
                    min_spacing=min_spacing,
                )

            try:
                suggestions = await anyio.to_thread.run_sync(_run_suggest)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            source = "mitm"
            message = (
                f"Returned {len(suggestions)} achievable colors "
                f"(via MITM fallback)."
            )

    log.info(
        "Material solver cache color suggestions returned",
        extra={
            "event": "material_solver_cache_suggest_colors_done",
            "source": source,
            "palette_hash": palette_hash,
            "material_count": len(dir_names),
            "target_hex": f"#{target_hex_clean.upper()}",
            "suggestions_count": len(suggestions),
            "top_k": top_k,
        },
    )
    return MaterialColorSuggestionsResponse(
        status="ok",
        message=message,
        source=source,
        palette_hash=palette_hash,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        target_hex=f"#{target_hex_clean.upper()}",
        target_rgb=[int(v) for v in target_rgb_tuple],
        suggestions=_suggestions_to_response_items(suggestions),
    )
