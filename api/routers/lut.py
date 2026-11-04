"""Lumina Studio API — LUT Management Router.
Lumina Studio API — LUT 管理路由。

Provides endpoints for LUT preset listing, information queries, and merge operations.
提供 LUT 预设列表、信息查询和合并操作端点。
"""

import json
import os
import shutil
import threading
import tempfile
import time
from pathlib import Path, PureWindowsPath
from typing import Annotated, Any

import msgpack
import numpy as np
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import Response

from api.dependencies import get_session_store
from api.project_workflows import resolve_project_lut

ProjectContext = Annotated[str | None, Header(alias="X-Lumina-Project-Context")]
from api.preview_cache_artifacts import is_preview_cache_artifact_ref
from api.session_store import SessionStore
from api.services.lut_presentation import (
    build_lut_info_from_path as _build_lut_info_from_path,
    cached_preview_color_hex as _cached_preview_color_hex,
    canonical_primary_hex as _canonical_primary_hex,
    canonicalize_public_color_mode as _canonicalize_public_color_mode,
    canonicalize_public_color_mode_fields as _canonicalize_public_color_mode_fields,
    canonicalize_source_catalog_color_modes as _canonicalize_source_catalog_color_modes,
    dedupe_warnings as _dedupe_warnings,
    preview_color_to_hex as _preview_color_to_hex,
    pure_channel_hex as _pure_channel_hex,
    public_lut_path_reference as _public_lut_path_reference,
    public_lut_source_catalog_paths as _public_lut_source_catalog_paths,
    recipe_matches_pattern as _recipe_matches_pattern,
)
from api.schemas.lut import (
    CompareDiffItem,
    CompareRequest,
    CompareResponse,
    CompareStats,
    LutAxisRange,
    LutCoverageStatsResponse,
    LutDetailsCatalogGroup,
    LutDetailsCatalogItem,
    LutDetailsCatalogResponse,
    LutDetailsResponse,
    LutHullPoint,
    LutInfoResponseV2,
    LutPlotPoint,
    LutPlotPoint3D,
    LutSourceCatalogResponse,
    LutSourceSelection,
    MergeRequest,
    MergeResponse,
    MergeStats,
    PaletteEntrySchema,
    RecipeColorPredictRequest,
    RecipeColorPredictResponse,
    RecipeSearchItem,
    RecipeSearchRequest,
    RecipeSearchResponse,
)
from api.schemas.responses import LUTListResponse, LutInfo, LutColorsResponse, LutColorEntry
from api.structured_logging import get_logger
from config import LUTMetadata, get_capabilities, get_schema_version, get_source_kind, get_supported_modes
from core.lut_card_layout import resolve_lut_layout
from core.lut_details.service import get_lut_details_service
from core.lut_merger import LUTMerger
from core.material_lut_synthesis import infer_material_archive_base_channel_idx
from core.native_reference import build_model_package_runtime_payload
from core.predictive_lut import opencv_lab_to_rgb_uint8, predict_recipe_color, resolve_predictive_runtime
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/lut", tags=["LUT"])
log = get_logger(__name__)

_VALID_PRIMARY_MODES = {"6-Color", "8-Color", "8-Color Max"}
_lut_details_service = None
_LUT_LIST_SIGNATURE_TTL_SECONDS = 5.0
_lut_list_cache_lock = threading.Lock()
_lut_list_cache_checked_at: float | None = None
_lut_list_cache_file_map: tuple[tuple[str, str], ...] | None = None
_lut_list_cache_response: LUTListResponse | None = None
_ALLOWED_LUT_EXTENSIONS = {".npy", ".json", ".npz", ".msgpack"}
_LUT_MERGE_FAILED_DETAIL = (
    "Unable to merge the selected LUTs. Check that each LUT uses a "
    "supported format and compatible color mode."
)
_LUT_COMPARE_FAILED_DETAIL = (
    "Unable to compare the selected LUTs. Check that both LUTs use "
    "supported formats with comparable recipes."
)
_LUT_DETAILS_CATALOG_FAILED_DETAIL = (
    "Unable to load the LUT catalog. Check that LUT presets are available and try again."
)
_LUT_DETAILS_FAILED_DETAIL = (
    "Unable to load LUT details. Check that the selected LUT is valid and try again."
)
_LUT_UPLOAD_INVALID_DETAIL = (
    "Invalid LUT file. Use a supported LUT format with readable color entries."
)
_LUT_UPLOAD_FAILED_DETAIL = (
    "Unable to save the LUT upload. Check server storage permissions and try again."
)
_LUT_RECIPE_COLOR_PREDICTION_FAILED_DETAIL = (
    "Unable to predict the recipe color. Check that the LUT supports "
    "recipe prediction and the recipe parameters are valid."
)
_LUT_RECIPE_SEARCH_FAILED_DETAIL = (
    "Unable to search LUT recipes. Check that the LUT supports recipe "
    "search and the search parameters are valid."
)
_LUT_NOT_FOUND_DETAIL = "Selected LUT was not found or is unavailable."


def _is_lut_sync_index_path(path: str) -> bool:
    try:
        resolved = Path(path).resolve()
        preset_root = Path(LUTManager.LUT_PRESET_DIR).resolve()
        sync_root = LUTManager.cloud_lut_sync_dir().resolve()
    except (OSError, ValueError):
        return False
    try:
        resolved.relative_to(sync_root)
        return True
    except ValueError:
        pass
    try:
        relative = resolved.relative_to(preset_root)
    except ValueError:
        return False
    return bool(relative.parts and relative.parts[0] == "_sync")


def _lut_error_fields(exc: Exception) -> dict[str, str]:
    return {
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }


def _build_lut_list_file_map(lut_dict: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((display_name, file_path) for display_name, file_path in lut_dict.items()))


def _build_lut_list_signature(lut_dict: dict[str, str]) -> tuple[tuple[str, str, int, int], ...]:
    """Build a cheap file-state signature for the LUT list response cache.
    为 LUT 列表响应缓存构建轻量文件状态签名。
    """

    signature: list[tuple[str, str, int, int]] = []
    for display_name, file_path in sorted(lut_dict.items()):
        try:
            stat = Path(file_path).stat()
            mtime_ns = int(stat.st_mtime_ns)
            size = int(stat.st_size)
        except OSError:
            mtime_ns = -1
            size = -1
        signature.append((display_name, file_path, mtime_ns, size))
    return tuple(signature)


def _is_lut_list_signature_cacheable(signature: tuple[tuple[str, str, int, int], ...]) -> bool:
    return all(mtime_ns >= 0 and size >= 0 for _display_name, _file_path, mtime_ns, size in signature)


def _clear_lut_list_cache() -> None:
    """Drop the route-level LUT list response cache. (清空 LUT 列表响应缓存)"""

    global _lut_list_cache_checked_at, _lut_list_cache_file_map
    global _lut_list_cache_response
    with _lut_list_cache_lock:
        _lut_list_cache_checked_at = None
        _lut_list_cache_file_map = None
        _lut_list_cache_response = None


def _validate_uploaded_lut_filename(filename: str) -> tuple[str, str]:
    """Return safe upload stem and extension for a Custom LUT filename.
    返回可用于 Custom LUT 目录的安全上传文件名主干与扩展名。
    """
    raw_filename = filename.strip()
    if not raw_filename:
        raise ValueError("Invalid LUT filename")
    if (
        "/" in raw_filename
        or "\\" in raw_filename
        or raw_filename in {".", ".."}
        or Path(raw_filename).is_absolute()
        or PureWindowsPath(raw_filename).drive
    ):
        raise ValueError("Invalid LUT filename: path components are not allowed")

    path = Path(raw_filename)
    stem = path.stem
    ext = path.suffix.lower()
    if not stem or stem in {".", ".."}:
        raise ValueError("Invalid LUT filename")
    if ext not in _ALLOWED_LUT_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的文件类型: {ext}，仅支持 .npy/.json/.npz/.msgpack",
        )
    return stem, ext


def _custom_lut_destination(custom_dir: str, stem: str, ext: str) -> Path:
    custom_root = Path(custom_dir).resolve()
    counter = 0
    while True:
        suffix = "" if counter == 0 else f"_{counter}"
        dest_path = (custom_root / f"{stem}{suffix}{ext}").resolve(strict=False)
        try:
            dest_path.relative_to(custom_root)
        except ValueError as exc:
            raise RuntimeError("Resolved LUT destination escaped Custom directory") from exc
        if not dest_path.exists():
            return dest_path
        counter += 1


def _resolve_lut_details_service():
    """Lazily initialize the LUT details service.
    延迟初始化 LUT 详情服务。
    """

    global _lut_details_service
    if _lut_details_service is None:
        _lut_details_service = get_lut_details_service()
    return _lut_details_service


def invalidate_lut_details_service_cache() -> None:
    """Drop cached LUT catalog/list state after LUT files change.
    在 LUT 文件变更后丢弃 LUT 目录/列表缓存状态。
    """

    global _lut_details_service
    _lut_details_service = None
    _clear_lut_list_cache()
    LUTManager.invalidate_preset_cache()
    LUTManager.invalidate_source_catalog_cache()
    LUTManager.invalidate_native_source_index_cache()
    get_lut_details_service.cache_clear()


def _invalidate_lut_details_service_cache() -> None:
    invalidate_lut_details_service_cache()


@router.get("/list")
def list_luts() -> LUTListResponse:
    """Return all available LUT presets as a list of LutInfo objects.
    返回所有可用 LUT 预设，以 LutInfo 对象列表形式返回。
    """
    global _lut_list_cache_checked_at, _lut_list_cache_file_map
    global _lut_list_cache_response

    lut_dict: dict[str, str] = LUTManager.get_all_lut_files()
    lut_file_map = _build_lut_list_file_map(lut_dict)
    now = time.monotonic()
    with _lut_list_cache_lock:
        if (
            _lut_list_cache_response is not None
            and _lut_list_cache_checked_at is not None
            and _lut_list_cache_file_map == lut_file_map
            and now - _lut_list_cache_checked_at <= _LUT_LIST_SIGNATURE_TTL_SECONDS
        ):
            return _lut_list_cache_response.model_copy(deep=True)

    signature = _build_lut_list_signature(lut_dict)
    cacheable = _is_lut_list_signature_cacheable(signature)
    lut_list: list[LutInfo] = []
    for display_name, file_path in lut_dict.items():
        lut_list.append(
            LutInfo(
                name=display_name,
                color_mode=_canonicalize_public_color_mode(
                    LUTManager.infer_color_mode(display_name, file_path)
                ),
                path=_public_lut_path_reference(file_path),
            )
        )
    response = LUTListResponse(luts=lut_list)
    with _lut_list_cache_lock:
        if cacheable:
            _lut_list_cache_checked_at = now
            _lut_list_cache_file_map = lut_file_map
            _lut_list_cache_response = response
        else:
            _lut_list_cache_checked_at = None
            _lut_list_cache_file_map = None
            _lut_list_cache_response = None
    return response


@router.get("/catalog", response_model=LutSourceCatalogResponse)
def get_source_catalog() -> LutSourceCatalogResponse:
    """Return legacy and native source catalog groupings.
    返回传统源与原生源的分组目录。
    """

    catalog = _public_lut_source_catalog_paths(
        _canonicalize_source_catalog_color_modes(LUTManager.get_source_catalog())
    )
    return LutSourceCatalogResponse.model_validate(catalog)


@router.post("/project-source")
def project_lut_source(selection: LutSourceSelection, project_context: ProjectContext = None) -> Response:
    """Freeze the selected source and native dependencies for a portable project."""
    from core.projects.dependencies import pack_lut_source
    from config import TEMP_DIR

    path: str | None = None
    try:
        if project_context and selection.source_kind == "legacy_single":
            path = resolve_project_lut(selection.lut_name, project_context)
            if not path:
                raise HTTPException(404, _LUT_NOT_FOUND_DETAIL)
        else:
            path, _ = LUTManager.resolve_source_selection(**selection.model_dump())
        return Response(
            pack_lut_source(path),
            media_type="application/zip",
            headers={"X-Project-Filename": "source.lut.zip"},
        )
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        if path and selection.source_kind in {"native_bundle", "legacy_multi"}:
            candidate = Path(path).resolve()
            if candidate.is_relative_to(Path(TEMP_DIR).resolve()):
                candidate.unlink(missing_ok=True)


@router.get("/details/catalog", response_model=LutDetailsCatalogResponse)
def get_lut_details_catalog() -> LutDetailsCatalogResponse:
    """Return the LUT details catalog grouped by manufacturer.
    返回按厂商分组的 LUT 详情目录。
    """

    try:
        catalog = _resolve_lut_details_service().get_catalog()
    except Exception as exc:
        log.error(
            "LUT details catalog failed",
            extra={
                "event": "lut_details_catalog_failed",
                **_lut_error_fields(exc),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=_LUT_DETAILS_CATALOG_FAILED_DETAIL,
        ) from exc
    return LutDetailsCatalogResponse(
        groups=[
            LutDetailsCatalogGroup(
                manufacturer=group.manufacturer,
                items=[
                    LutDetailsCatalogItem(
                        name=item.name,
                        path=_public_lut_path_reference(item.path),
                        color_mode=_canonicalize_public_color_mode(item.color_mode),
                        source_kind=item.source_kind,
                        compatibility_key=getattr(item, "compatibility_key", ""),
                        manufacturer=item.manufacturer,
                        material_type=item.material_type,
                        manufacturer_source=item.manufacturer_source,
                        material_source=item.material_source,
                        search_tokens=list(item.search_tokens),
                        revision=item.revision,
                    )
                    for item in group.items
                    if not _is_lut_sync_index_path(item.path)
                ],
            )
            for group in catalog.groups
            if any(not _is_lut_sync_index_path(item.path) for item in group.items)
        ]
    )


class _UploadedLutValidationError(ValueError):
    """Raised when an uploaded file is not a usable LUT preset."""


def _uploaded_lut_error(message: str) -> _UploadedLutValidationError:
    return _UploadedLutValidationError(f"Invalid LUT file: {message}")


def _numeric_triplet(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return False
    try:
        values = np.asarray([float(component) for component in value], dtype=np.float64)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(values).all())


def _rgb_triplet(value: Any) -> bool:
    if not _numeric_triplet(value):
        return False
    values = [float(component) for component in value]
    return all(0.0 <= component <= 255.0 for component in values)


def _json_entry_has_real_color(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    return _rgb_triplet(entry.get("rgb")) or _numeric_triplet(entry.get("lab"))


def _require_rgb_rows(value: Any, label: str) -> np.ndarray:
    try:
        rgb = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise _uploaded_lut_error(f"{label} RGB values must be numeric") from exc

    if rgb.size == 0:
        raise _uploaded_lut_error(f"{label} contains no RGB rows")

    if rgb.ndim == 2 and rgb.shape[1] == 3:
        rows = rgb
    elif rgb.ndim in {1, 3}:
        if rgb.size % 3 != 0:
            raise _uploaded_lut_error(
                f"{label} RGB data is not divisible into RGB triplets"
            )
        rows = rgb.reshape(-1, 3)
    else:
        raise _uploaded_lut_error(f"{label} RGB data must be shaped as N x 3")

    if rows.shape[0] == 0:
        raise _uploaded_lut_error(f"{label} contains no RGB rows")
    if not np.isfinite(rows).all():
        raise _uploaded_lut_error(f"{label} RGB data contains non-finite values")
    if np.any((rows < 0.0) | (rows > 255.0)):
        raise _uploaded_lut_error(f"{label} RGB values must be between 0 and 255")
    return rows


def _validate_uploaded_npy_lut(path: str) -> None:
    try:
        rgb = np.load(path, allow_pickle=False)
    except (OSError, ValueError, TypeError, EOFError) as exc:
        raise _uploaded_lut_error(f"unable to parse NPY data: {exc}") from exc
    _require_rgb_rows(rgb, "NPY LUT")


def _validate_uploaded_json_lut(path: str) -> None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError) as exc:
        raise _uploaded_lut_error(f"unable to parse JSON data: {exc}") from exc

    display_name = Path(path).stem
    if isinstance(payload, list):
        if not any(_json_entry_has_real_color(entry) for entry in payload):
            raise _uploaded_lut_error("JSON LUT contains no valid rgb or lab entries")
        try:
            rgb, _stacks, _metadata = LUTManager._load_keyed_json_flat_list(
                payload,
                display_name,
                path,
            )
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, ImportError) as exc:
            raise _uploaded_lut_error(f"invalid JSON LUT payload: {exc}") from exc
        _require_rgb_rows(rgb, "JSON LUT")
        return

    if isinstance(payload, dict):
        try:
            rgb, _stacks, metadata = LUTManager._load_keyed_payload(
                payload,
                display_name,
                path,
                skip_malformed_recipes=True,
            )
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, ImportError) as exc:
            raise _uploaded_lut_error(f"invalid JSON LUT payload: {exc}") from exc
        _require_rgb_rows(rgb, "JSON LUT")
        return

    raise _uploaded_lut_error("JSON LUT root must be an object or list")


def _validate_uploaded_npz_lut(path: str) -> None:
    try:
        with np.load(path, allow_pickle=False) as payload:
            if "rgb" not in payload.files:
                raise _uploaded_lut_error("NPZ LUT is missing rgb data")
            rgb_rows = _require_rgb_rows(payload["rgb"], "NPZ LUT")
            if "stacks" in payload.files:
                stacks = np.asarray(payload["stacks"])
                if stacks.ndim < 2:
                    raise _uploaded_lut_error("NPZ stacks must be a 2D array")
                if int(stacks.shape[0]) != int(rgb_rows.shape[0]):
                    raise _uploaded_lut_error("NPZ stacks row count does not match rgb")
    except _UploadedLutValidationError:
        raise
    except (OSError, ValueError, TypeError, EOFError) as exc:
        raise _uploaded_lut_error(f"unable to parse NPZ data: {exc}") from exc


def _validate_uploaded_msgpack_lut(path: str) -> None:
    try:
        payload = msgpack.unpackb(Path(path).read_bytes(), raw=False)
    except (OSError, ValueError, TypeError, msgpack.UnpackException) as exc:
        raise _uploaded_lut_error(f"unable to parse msgpack data: {exc}") from exc

    display_name = Path(path).stem
    if LUTManager._is_model_package_payload(payload):
        try:
            build_model_package_runtime_payload(path, payload=payload)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise _uploaded_lut_error(
                f"model package contains no usable runtime modes: {exc}"
            ) from exc
        return

    if isinstance(payload, list):
        if not any(_json_entry_has_real_color(entry) for entry in payload):
            raise _uploaded_lut_error("msgpack LUT contains no valid rgb or lab entries")
        try:
            rgb, _stacks, _metadata = LUTManager._load_keyed_json_flat_list(
                payload,
                display_name,
                path,
            )
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, ImportError) as exc:
            raise _uploaded_lut_error(f"invalid msgpack LUT payload: {exc}") from exc
        _require_rgb_rows(rgb, "msgpack LUT")
        return

    if isinstance(payload, dict):
        try:
            rgb, _stacks, metadata = LUTManager._load_keyed_payload(
                payload,
                display_name,
                path,
                skip_malformed_recipes=True,
            )
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, ImportError) as exc:
            raise _uploaded_lut_error(f"invalid msgpack LUT payload: {exc}") from exc
        _require_rgb_rows(rgb, "msgpack LUT")
        return

    raise _uploaded_lut_error("msgpack LUT root must be an object or list")


def _validate_uploaded_lut_file(path: str, ext: str) -> None:
    if ext == ".npy":
        _validate_uploaded_npy_lut(path)
        return
    if ext == ".json":
        _validate_uploaded_json_lut(path)
        return
    if ext == ".npz":
        _validate_uploaded_npz_lut(path)
        return
    if ext == ".msgpack":
        _validate_uploaded_msgpack_lut(path)
        return
    raise _uploaded_lut_error(f"unsupported extension: {ext}")


@router.post("/upload")
async def upload_lut(file: UploadFile = File(..., description="LUT 文件 (.npy/.json/.npz)")) -> dict:
    """Upload a LUT file to the Custom preset directory.
    上传 LUT 文件到 Custom 预设目录。
    """
    filename = file.filename or "unknown"
    try:
        stem, ext = _validate_uploaded_lut_filename(filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    # Save to temp file first (chunked read with size limit)
    from config import TEMP_DIR

    MAX_LUT_SIZE = 50 * 1024 * 1024  # 50 MB
    total_read = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=TEMP_DIR) as tmp:
        while True:
            chunk = await file.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > MAX_LUT_SIZE:
                tmp_path = tmp.name
                os.unlink(tmp_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"文件过大，最大允许 {MAX_LUT_SIZE // (1024*1024)} MB",
                )
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        _validate_uploaded_lut_file(tmp_path, ext)

        custom_dir = str(LUTManager.custom_lut_dir())
        os.makedirs(custom_dir, exist_ok=True)

        # Auto-convert .npy to Keyed JSON
        if ext == ".npy":
            dest_ext = ".json"
            rgb = np.load(tmp_path)
            if rgb.ndim == 3:
                rgb = rgb.reshape(-1, 3)
            elif rgb.ndim == 1:
                rgb = rgb.reshape(-1, 3)
            metadata = LUTManager.infer_default_metadata(stem, tmp_path, len(rgb))
            stacks = np.zeros((len(rgb), 0), dtype=np.int32)
            dest_path = _custom_lut_destination(custom_dir, stem, dest_ext)
            LUTManager.save_keyed_json(str(dest_path), rgb, stacks, metadata)
        else:
            dest_path = _custom_lut_destination(custom_dir, stem, ext)
            shutil.copy2(tmp_path, dest_path)

        _invalidate_lut_details_service_cache()
        display_name = f"Custom - {Path(dest_path).stem}"
        dest_filename = Path(dest_path).name
        log.info(
            "LUT upload complete",
            extra={
                "event": "lut_upload_done",
                "original_filename": filename,
                "file_extension": ext,
                "dest_filename": dest_filename,
                "display_name": display_name,
                "file_size_bytes": int(total_read),
                "was_converted": ext == ".npy",
            },
        )
        return {"status": "ok", "message": f"LUT 已保存: {display_name}", "name": display_name}
    except _UploadedLutValidationError as exc:
        log.warning(
            "LUT upload validation failed",
            extra={
                "event": "lut_upload_validation_failed",
                "original_filename": filename,
                "file_extension": ext,
                "file_size_bytes": int(total_read),
                **_lut_error_fields(exc),
            },
        )
        raise HTTPException(status_code=422, detail=_LUT_UPLOAD_INVALID_DETAIL) from exc
    except Exception as exc:
        log.error(
            "LUT upload failed",
            extra={
                "event": "lut_upload_failed",
                "original_filename": filename,
                "file_extension": ext,
                "file_size_bytes": int(total_read),
                **_lut_error_fields(exc),
            },
        )
        raise HTTPException(status_code=500, detail=_LUT_UPLOAD_FAILED_DETAIL) from exc
    finally:
        os.unlink(tmp_path)


@router.post("/merge")
def merge_luts_endpoint(request: MergeRequest, project_context: ProjectContext = None) -> MergeResponse:
    """Execute LUT merge: primary + multiple secondary LUTs.
    执行 LUT 合并：主 LUT + 多个辅助 LUT。

    Replicates the flow of ``ui/callbacks.py::on_merge_execute``:
    resolve paths → detect modes → validate compatibility →
    load data → skip Merged secondaries → merge → save to Custom dir.
    复刻 ``ui/callbacks.py::on_merge_execute`` 的完整流程：
    解析路径 → 检测模式 → 验证兼容性 → 加载数据 → 跳过 Merged Secondary → 合并 → 保存到 Custom 目录。
    """
    # 1. Validate secondary list not empty / 验证 Secondary 列表非空
    if not request.secondary_names:
        raise HTTPException(
            status_code=400,
            detail="At least one secondary LUT is required",
        )

    # 2. Resolve primary path / 解析主 LUT 路径
    primary_path: str | None = resolve_project_lut(request.primary_name, project_context)
    if primary_path is None:
        raise HTTPException(
            status_code=404,
            detail=_LUT_NOT_FOUND_DETAIL,
        )

    try:
        # 3. Detect primary mode / 检测主 LUT 模式
        primary_mode, _ = LUTMerger.detect_color_mode(primary_path)
        if primary_mode not in _VALID_PRIMARY_MODES:
            raise HTTPException(
                status_code=400,
                detail="Primary LUT must be 6-Color or 8-Color",
            )

        # 4. Load primary data / 加载主 LUT 数据
        primary_rgb, primary_stacks = LUTMerger.load_lut_with_stacks(primary_path, primary_mode)
        entries = [(primary_rgb, primary_stacks, primary_mode)]
        all_modes: list[str] = [primary_mode]
        all_paths: list[str] = [primary_path]  # 记录所有输入路径，用于判断输出格式
        all_names: list[str] = [request.primary_name]  # 记录来源 LUT 显示名称

        # 5. Load each secondary, skip Merged / 加载辅助 LUT，跳过 Merged
        for sec_name in request.secondary_names:
            sec_path: str | None = resolve_project_lut(sec_name, project_context)
            if sec_path is None:
                continue
            sec_mode, _ = LUTMerger.detect_color_mode(sec_path)
            if sec_mode == "Merged":
                continue
            sec_rgb, sec_stacks = LUTMerger.load_lut_with_stacks(sec_path, sec_mode)
            entries.append((sec_rgb, sec_stacks, sec_mode))
            all_modes.append(sec_mode)
            all_paths.append(sec_path)
            all_names.append(sec_name)

        # 6. Need at least 2 entries / 至少需要 2 个有效条目
        if len(entries) < 2:
            raise HTTPException(
                status_code=400,
                detail="At least one secondary LUT is required",
            )

        # 7. Validate compatibility / 验证兼容性
        valid, err_msg = LUTMerger.validate_compatibility(all_modes)
        if not valid:
            raise HTTPException(status_code=400, detail=err_msg)

        # 判断输出格式：所有输入都是 .json 时输出 JSON，否则输出 .npz
        all_json = all(p.lower().endswith(".json") for p in all_paths)

        # 8. Merge / 执行合并
        # 如果输出 JSON，加载 metadata 以便保存完整的 Keyed JSON
        metadata_list: list[LUTMetadata] | None = None
        if all_json:
            metadata_list = []
            for p in all_paths:
                _, _, meta = LUTManager.load_lut_with_metadata(p)
                metadata_list.append(meta)

        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(
            entries,
            dedup_threshold=request.dedup_threshold,
            metadata_list=metadata_list,
            source_names=all_names,
        )

        # 9. Save to Custom dir / 保存到 Custom 目录
        timestamp: str = time.strftime("%Y%m%d_%H%M%S")
        mode_str: str = "+".join(all_modes)
        output_ext: str = ".json" if all_json else ".npz"
        output_name: str = f"Merged_{mode_str}_{timestamp}{output_ext}"
        custom_dir: str = str(LUTManager.custom_lut_dir())
        os.makedirs(custom_dir, exist_ok=True)
        output_path: str = os.path.join(custom_dir, output_name)

        merged_metadata = stats.get("merged_metadata")
        if all_json:
            # 输出 Keyed JSON 格式，保留 palette 和打印参数
            if merged_metadata is None:
                # 回退：使用主 LUT 的 metadata
                _, _, merged_metadata = LUTManager.load_lut_with_metadata(primary_path)
            entry_sources = stats.get("entry_sources")
            json_stacks = LUTMerger.reindex_canonical_stacks_for_palette(
                merged_stacks,
                merged_metadata.palette,
            )
            LUTManager.save_keyed_json(
                output_path,
                merged_rgb,
                json_stacks,
                merged_metadata,
                sources=entry_sources,
            )
        else:
            LUTMerger.save_merged_lut(merged_rgb, merged_stacks, output_path)

        _invalidate_lut_details_service_cache()
        log.info(
            "LUT merge complete",
            extra={
                "event": "lut_merge_done",
                "primary_lut_name": request.primary_name,
                "secondary_count": len(request.secondary_names),
                "merged_filename": output_name,
                "total_before": int(stats["total_before"]),
                "total_after": int(stats["total_after"]),
                "exact_dupes": int(stats["exact_dupes"]),
                "similar_removed": int(stats["similar_removed"]),
                "palette_size": len(merged_metadata.palette) if merged_metadata else 0,
                "warning_count": len(stats.get("warnings") or []),
            },
        )
        # 10. Return response / 返回响应
        # 注意：validate_print_params() 和 merge_palettes() 尚未实现（任务 6），暂时使用空列表
        return MergeResponse(
            status="success",
            message=f"Merged {stats['total_before']} colors → {stats['total_after']} colors",
            filename=output_name,
            stats=MergeStats(
                total_before=stats["total_before"],
                total_after=stats["total_after"],
                exact_dupes=stats["exact_dupes"],
                similar_removed=stats["similar_removed"],
            ),
            palette=[
                PaletteEntrySchema(
                    color=entry.color,
                    material=entry.material,
                    hex_color=entry.hex_color,
                    color_name=entry.color_name,
                )
                for entry in ((stats.get("merged_metadata").palette) if stats.get("merged_metadata") else [])
            ],
            warnings=_dedupe_warnings(list(stats.get("warnings", []))),
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_LUT_MERGE_FAILED_DETAIL,
        ) from exc


@router.post("/compare")
def compare_luts_endpoint(request: CompareRequest, project_context: ProjectContext = None) -> CompareResponse:
    """Compare two LUTs by shared recipe keys.
    按共享配方键比较两个 LUT。
    """
    path_a: str | None = resolve_project_lut(request.lut_a_name, project_context)
    if path_a is None:
        raise HTTPException(status_code=404, detail=_LUT_NOT_FOUND_DETAIL)

    path_b: str | None = resolve_project_lut(request.lut_b_name, project_context)
    if path_b is None:
        raise HTTPException(status_code=404, detail=_LUT_NOT_FOUND_DETAIL)

    try:
        mode_a, _count_a = LUTMerger.detect_color_mode(path_a)
        mode_b, _count_b = LUTMerger.detect_color_mode(path_b)

        rgb_a, stacks_a = LUTMerger.load_lut_with_stacks(path_a, mode_a)
        rgb_b, stacks_b = LUTMerger.load_lut_with_stacks(path_b, mode_b)

        try:
            _, _, metadata_a = LUTManager.load_lut_with_metadata(path_a)
        except Exception:
            metadata_a = LUTMetadata(color_mode=mode_a)

        try:
            _, _, metadata_b = LUTManager.load_lut_with_metadata(path_b)
        except Exception:
            metadata_b = LUTMetadata(color_mode=mode_b)

        compare_result = LUTMerger.compare_luts_by_recipe(
            rgb_a,
            stacks_a,
            rgb_b,
            stacks_b,
            top_n=request.top_n,
        )

        warnings = list(compare_result.get("warnings", []))

        if mode_a != mode_b:
            warnings.append(f"color_mode 不一致: {mode_a} vs {mode_b}")

        if stacks_a.ndim == 2 and stacks_b.ndim == 2:
            if stacks_a.shape[1] != stacks_b.shape[1]:
                warnings.append(
                    f"recipe layer count differs: {stacks_a.shape[1]} vs {stacks_b.shape[1]}"
                )

        _compatible, param_warnings = LUTMerger.validate_print_params([metadata_a, metadata_b])
        warnings.extend(param_warnings)
        if get_schema_version(metadata_a) != get_schema_version(metadata_b):
            warnings.append(
                f"schema_version differs: {get_schema_version(metadata_a)} vs {get_schema_version(metadata_b)}"
            )
        if metadata_a.supports_predictive_match() != metadata_b.supports_predictive_match():
            warnings.append(
                "predictive support differs: "
                f"{metadata_a.supports_predictive_match()} vs {metadata_b.supports_predictive_match()}"
            )
        if metadata_a.supports_dynamic_layer_height() != metadata_b.supports_dynamic_layer_height():
            warnings.append(
                "dynamic_layer_height support differs: "
                f"{metadata_a.supports_dynamic_layer_height()} vs {metadata_b.supports_dynamic_layer_height()}"
            )

        stats_dict = compare_result["stats"]
        if stats_dict["matched_recipe_count"] == 0:
            warnings.append("No shared recipes found; comparison metrics are zeroed.")

        warnings = _dedupe_warnings(warnings)
        log.info(
            "LUT compare complete",
            extra={
                "event": "lut_compare_done",
                "lut_a_name": request.lut_a_name,
                "lut_b_name": request.lut_b_name,
                "lut_a_mode": mode_a,
                "lut_b_mode": mode_b,
                "matched_recipe_count": int(stats_dict["matched_recipe_count"]),
                "warning_count": len(warnings),
                "top_n": int(request.top_n),
                "worst_diffs_count": len(compare_result["worst_diffs"]),
            },
        )
        message = (
            f"Compared {stats_dict['matched_recipe_count']} shared recipes between "
            f"{request.lut_a_name} and {request.lut_b_name}"
        )

        return CompareResponse(
            status="success",
            message=message,
            lut_a_name=request.lut_a_name,
            lut_b_name=request.lut_b_name,
            lut_a_mode=mode_a,
            lut_b_mode=mode_b,
            stats=CompareStats(**stats_dict),
            warnings=warnings,
            worst_diffs=[CompareDiffItem(**item) for item in compare_result["worst_diffs"]],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_LUT_COMPARE_FAILED_DETAIL,
        ) from exc


@router.get("/{lut_name}/colors")
def get_lut_colors(lut_name: str, session_id: str | None = None, store: SessionStore = Depends(get_session_store)) -> LutColorsResponse:
    """Return all unique colors available in a LUT file.
    返回 LUT 文件中所有可用的唯一颜色。
    """
    if session_id:
        session = store.get(session_id)
        if session is None:
            raise HTTPException(404, "Project preview session expired")
        path = session.get("lut_path")
    else:
        path = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=_LUT_NOT_FOUND_DETAIL)

    from core.converter import extract_lut_available_colors

    raw_colors: list[dict] = extract_lut_available_colors(path)
    entries: list[LutColorEntry] = [LutColorEntry(hex=c["hex"], rgb=c["color"]) for c in raw_colors]

    layout = None
    cards = []
    try:
        rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)
        rgb_rows = np.asarray(rgb).reshape(-1, 3)
        mode = _canonicalize_public_color_mode(getattr(metadata, "color_mode", None)) or ""
        layout = resolve_lut_layout(mode, int(rgb_rows.shape[0]))
        row_entries = [
            LutColorEntry(
                hex=f"#{int(color[0]):02x}{int(color[1]):02x}{int(color[2]):02x}",
                rgb=(int(color[0]), int(color[1]), int(color[2])),
            )
            for color in rgb_rows
        ]
        cards = [
            {
                "page": page.to_dict(),
                "colors": row_entries[page.start_index : page.start_index + page.item_count],
            }
            for page in layout.pages
        ]
    except (ValueError, OSError, KeyError, TypeError, RuntimeError):
        layout = None
        cards = []

    return LutColorsResponse(
        lut_name=lut_name,
        total=len(entries),
        colors=entries,
        layout=layout.to_dict() if layout is not None else None,
        cards=cards,
    )


def _build_material_archive_lut_info(session_data: dict) -> LutInfoResponseV2:
    """Build session-scoped LUT info for material-archive sources.

    耗材档案没有真实 LUT 文件；这里从 session 的耗材顺序和 preview cache
    组装与 LUT info 相同形状的通道 palette，供自定义配方编辑器使用。
    """
    selected_materials = session_data.get("selected_materials") or []
    if not isinstance(selected_materials, list) or not selected_materials:
        raise HTTPException(
            status_code=409,
            detail=(
                "Material archive session is missing selected materials. "
                "Run preview again first."
            ),
        )

    cache = session_data.get("preview_cache") or {}
    if is_preview_cache_artifact_ref(cache):
        cache = cache.get("metadata") or {}
    if not isinstance(cache, dict):
        cache = {}
    raw_slot_names = cache.get("slot_names") or []
    slot_names = raw_slot_names if isinstance(raw_slot_names, list) else []
    preview_colors = cache.get("preview_colors") or {}
    base_channel_idx = infer_material_archive_base_channel_idx(
        selected_materials,
        slot_names,
        preview_colors,
    )

    palette_schema: list[PaletteEntrySchema] = []
    for idx, dir_name in enumerate(selected_materials):
        raw_slot = slot_names[idx] if idx < len(slot_names) else None
        label = str(raw_slot) if raw_slot else str(dir_name)
        palette_schema.append(
            PaletteEntrySchema(
                color=label,
                material=str(dir_name),
                hex_color=_cached_preview_color_hex(preview_colors, idx),
                color_name=label,
            )
        )

    color_layers = int(
        session_data.get("material_layer_count")
        or cache.get("color_layers")
        or len(palette_schema)
        or 5
    )
    layer_height_mm = float(
        session_data.get("material_layer_height_mm")
        or cache.get("layer_height_mm")
        or 0.08
    )
    metadata = LUTMetadata(
        max_color_layers=color_layers,
        layer_height_mm=layer_height_mm,
        color_mode="Material Archive",
        base_channel_idx=base_channel_idx,
        capabilities=["custom_recipe"],
        extensions={
            "source_kind": "material_archive",
            "custom_recipe_supported": True,
            "supported_modes": [
                {
                    "color_layers": color_layers,
                    "layer_height_mm": layer_height_mm,
                }
            ],
        },
    )
    display_name = str(session_data.get("lut_name") or "__material_archive__")
    return LutInfoResponseV2(
        name=display_name,
        color_mode="Material Archive",
        color_count=len(palette_schema),
        palette=palette_schema,
        max_color_layers=metadata.max_color_layers,
        layer_height_mm=metadata.layer_height_mm,
        line_width_mm=metadata.line_width_mm,
        base_layers=metadata.base_layers,
        base_channel_idx=metadata.base_channel_idx,
        layer_order=metadata.layer_order,
        schema_version=get_schema_version(metadata),
        capabilities=get_capabilities(metadata),
        supports_predictive_match=metadata.supports_predictive_match(),
        supports_dynamic_layer_height=metadata.supports_dynamic_layer_height(),
        supports_dynamic_layer_count=metadata.supports_dynamic_layer_count(),
        supports_custom_recipe=metadata.supports_custom_recipe(),
        source_kind=metadata.get_source_kind(),
        supported_modes=metadata.get_supported_modes(),
    )


@router.get("/{lut_name}/info")
def get_lut_info(lut_name: str, project_context: ProjectContext = None) -> LutInfoResponseV2:
    """Return color mode and color count for a specific LUT.
    返回指定 LUT 的颜色模式和颜色数量。
    """
    path: str | None = resolve_project_lut(lut_name, project_context)
    if path is None:
        raise HTTPException(status_code=404, detail=_LUT_NOT_FOUND_DETAIL)
    return _build_lut_info_from_path(path, lut_name)


@router.get("/session/{session_id}/info")
def get_session_lut_info(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> LutInfoResponseV2:
    """Return channel palette and capabilities for the LUT bound to a session.

    返回当前会话所绑定 LUT 的通道调色板与能力标志。

    Unlike :func:`get_lut_info`, this endpoint works for material-archive and
    native-bundle sessions that don't have a globally-known LUT name, letting
    the UI surface channel-ordered materials for custom recipe editing.

    Args:
        session_id: Active converter session id. 当前转换会话 id。
        store: Injected :class:`SessionStore`. 会话存储依赖。

    Returns:
        LutInfoResponseV2: Same shape as :func:`get_lut_info`.
            与 ``get_lut_info`` 相同的响应结构。

    Raises:
        HTTPException(404): Session not found. 会话不存在。
        HTTPException(409): Session has no LUT bound yet or the file is
            missing. 会话未绑定 LUT 或文件缺失。
    """
    session_data = store.get(session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if str(session_data.get("material_source") or "lut") == "material_archive":
        info = _build_material_archive_lut_info(session_data)
        source_kind = "material_archive"
    else:
        lut_path = session_data.get("lut_path")
        if not isinstance(lut_path, str) or not lut_path or not os.path.exists(lut_path):
            raise HTTPException(
                status_code=409,
                detail="Session has no LUT bound yet. Run preview/generate first.",
            )
        display_name = session_data.get("lut_name") or Path(lut_path).stem
        info = _build_lut_info_from_path(lut_path, str(display_name))
        source_kind = info.source_kind

    log.info(
        "Session LUT info returned",
        extra={
            "event": "lut_session_info_done",
            "session_id": session_id,
            "lut_name": info.name,
            "color_mode": info.color_mode,
            "color_count": int(info.color_count),
            "source_kind": source_kind,
            "palette_size": len(info.palette),
        },
    )
    return info


@router.get("/{lut_name}/details", response_model=LutDetailsResponse)
def get_lut_details(lut_name: str, project_context: ProjectContext = None) -> LutDetailsResponse:
    """Return the detailed LUT metadata and visualization payload.
    返回 LUT 的详细元数据和可视化载荷。
    """

    try:
        if project_context:
            source = resolve_project_lut(lut_name, project_context)
            if source is None:
                raise KeyError(lut_name)
            detail = _resolve_lut_details_service().get_lut_details_from_path(lut_name, Path(source))
        else:
            detail = _resolve_lut_details_service().get_lut_details(lut_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_LUT_NOT_FOUND_DETAIL) from exc
    except Exception as exc:
        log.error(
            "LUT details failed",
            extra={
                "event": "lut_details_failed",
                "lut_name": lut_name,
                **_lut_error_fields(exc),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=_LUT_DETAILS_FAILED_DETAIL,
        ) from exc

    log.info(
        "LUT details returned",
        extra={
            "event": "lut_details_done",
            "lut_name": detail.name,
            "color_mode": detail.color_mode,
            "color_count": int(detail.color_count),
            "entry_count": int(detail.coverage_stats.entry_count),
            "lab_points_count": len(detail.lab_points),
            "rgb_points_count": len(detail.rgb_points),
            "manufacturer": detail.manufacturer or "",
            "source_kind": detail.source_kind,
        },
    )
    return LutDetailsResponse(
        name=detail.name,
        path=_public_lut_path_reference(detail.path),
        manufacturer=detail.manufacturer,
        manufacturer_source=detail.manufacturer_source,
        material_type=detail.material_type,
        material_source=detail.material_source,
        color_mode=_canonicalize_public_color_mode(detail.color_mode),
        color_count=detail.color_count,
        source_kind=detail.source_kind,
        schema_version=detail.schema_version,
        capabilities=list(detail.capabilities),
        supported_modes=list(detail.supported_modes),
        raw_metadata=_canonicalize_public_color_mode_fields(detail.raw_metadata),
        palette=[
            PaletteEntrySchema(
                color=str(entry["color"]),
                material=str(entry["material"]),
                hex_color=entry.get("hex_color"),
                color_name=entry.get("color_name"),
            )
            for entry in detail.palette
        ],
        coverage_stats=LutCoverageStatsResponse(
            entry_count=detail.coverage_stats.entry_count,
            plotted_point_count=detail.coverage_stats.plotted_point_count,
            l_range=LutAxisRange(min=detail.coverage_stats.l_range.min, max=detail.coverage_stats.l_range.max),
            a_range=LutAxisRange(min=detail.coverage_stats.a_range.min, max=detail.coverage_stats.a_range.max),
            b_range=LutAxisRange(min=detail.coverage_stats.b_range.min, max=detail.coverage_stats.b_range.max),
            r_range=LutAxisRange(min=detail.coverage_stats.r_range.min, max=detail.coverage_stats.r_range.max),
            g_range=LutAxisRange(min=detail.coverage_stats.g_range.min, max=detail.coverage_stats.g_range.max),
            b_rgb_range=LutAxisRange(min=detail.coverage_stats.b_rgb_range.min, max=detail.coverage_stats.b_rgb_range.max),
        ),
        lab_points=[
            LutPlotPoint(
                x=point.x,
                y=point.y,
                hex_color=point.hex_color,
                rgb=list(point.rgb),
                label=point.label,
            )
            for point in detail.lab_points
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
            for point in detail.lab_points_3d
        ],
        lab_hull=[LutHullPoint(x=point[0], y=point[1]) for point in detail.lab_hull],
        rgb_points=[
            LutPlotPoint(
                x=point.x,
                y=point.y,
                hex_color=point.hex_color,
                rgb=list(point.rgb),
                label=point.label,
            )
            for point in detail.rgb_points
        ],
        max_color_layers=detail.max_color_layers,
        layer_height_mm=detail.layer_height_mm,
        line_width_mm=detail.line_width_mm,
        base_layers=detail.base_layers,
        base_channel_idx=detail.base_channel_idx,
        layer_order=detail.layer_order,
    )


@router.post("/{lut_name}/predict-recipe-color")
def predict_recipe_color_endpoint(
    lut_name: str,
    request: RecipeColorPredictRequest,
) -> RecipeColorPredictResponse:
    """Predict a custom recipe color for the selected source."""
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=_LUT_NOT_FOUND_DETAIL)

    try:
        _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)
        payload = predict_recipe_color(
            metadata,
            recipe=list(request.recipe),
            layer_height_mm=float(request.layer_height_mm),
            color_layers=int(request.color_layers),
            layer_order=str(request.layer_order),
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.warning(
            "LUT recipe color prediction failed",
            extra={
                "event": "lut_recipe_color_prediction_failed",
                "lut_name": lut_name,
                **_lut_error_fields(exc),
            },
        )
        raise HTTPException(
            status_code=422,
            detail=_LUT_RECIPE_COLOR_PREDICTION_FAILED_DETAIL,
        ) from exc

    return RecipeColorPredictResponse(
        status="ok",
        rgb=[int(v) for v in payload["rgb"]],
        lab=[float(v) for v in payload["lab"]],
        runtime_mode_key=str(payload["runtime_mode_key"]),
        source=str(payload["source"]),
    )


@router.post("/{lut_name}/search-recipes")
def search_recipes_endpoint(
    lut_name: str,
    request: RecipeSearchRequest,
) -> RecipeSearchResponse:
    """Search predictive candidate recipes by a simple layer pattern."""
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=_LUT_NOT_FOUND_DETAIL)

    try:
        _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)
        runtime = resolve_predictive_runtime(
            metadata,
            float(request.layer_height_mm),
            int(request.color_layers),
            str(request.layer_order),
        )
        if runtime is None:
            raise ValueError("No predictive runtime available for the requested mode")

        palette_letters = [
            (entry.color_name or entry.color or "?")[:1].upper()
            for entry in metadata.palette
        ]
        matches: list[RecipeSearchItem] = []
        for idx, recipe in enumerate(runtime.candidate_recipes.tolist()):
            if not _recipe_matches_pattern(recipe, palette_letters, request.pattern):
                continue
            rgb = opencv_lab_to_rgb_uint8(runtime.pred_lab[idx : idx + 1])[0].astype(int).tolist()
            lab = runtime.pred_lab[idx].astype(float).tolist()
            matches.append(RecipeSearchItem(recipe=[int(v) for v in recipe], rgb=rgb, lab=lab))
            if len(matches) >= int(request.limit):
                break
    except HTTPException:
        raise
    except Exception as exc:
        log.warning(
            "LUT recipe search failed",
            extra={
                "event": "lut_recipe_search_failed",
                "lut_name": lut_name,
                **_lut_error_fields(exc),
            },
        )
        raise HTTPException(
            status_code=422,
            detail=_LUT_RECIPE_SEARCH_FAILED_DETAIL,
        ) from exc

    return RecipeSearchResponse(
        status="ok",
        runtime_mode_key=runtime.mode_key,
        items=matches,
    )
