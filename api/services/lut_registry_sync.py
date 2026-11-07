"""Cloud LUT registry catalog and install service.

This module keeps remote registry IO and package validation out of FastAPI
routers so tests can exercise the security boundary directly.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx
import msgpack
import numpy as np

from core.native_reference import build_model_package_runtime_payload
from core.registry_transport import (
    RegistryCatalogNotFoundError,
    fallback_base,
    fetch_catalog,
    map_package_url,
    read_with_fallback,
)
from utils.lut_manager import LUTManager

MANIFEST_NAME = "lumina_lut_bundle.json"
ALLOWED_LUT_EXTENSIONS = {".json", ".npy", ".npz", ".msgpack"}
DEFAULT_CHANNELS = ("official", "community")
MAX_CATALOG_LIMIT = 200
MAX_LUT_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_LUT_FILE_BYTES = 256 * 1024 * 1024
MAX_LUT_MANIFEST_BYTES = 2 * 1024 * 1024
_INSTALL_LOCK_FILENAME = "install.lock"
_INSTALL_LOCK_STALE_SECONDS = 300.0
_HEX_CHARS = set("0123456789abcdef")
_INSTALL_LOCK = threading.Lock()


class LutRegistryError(RuntimeError):
    """Base error for LUT registry sync failures."""

    status_code = 500


class LutRegistryConfigError(LutRegistryError):
    """Raised when registry sync is not configured."""

    status_code = 503


class LutRegistryRemoteError(LutRegistryError):
    """Raised when a remote registry request fails."""

    status_code = 502


class LutRegistryPackageError(LutRegistryError):
    """Raised when a downloaded LUT package is invalid or unsafe."""

    status_code = 422


@dataclass(frozen=True)
class LutRegistryConfig:
    """Resolved LUT registry configuration."""

    base_url: str | None
    channels: tuple[str, ...]
    token: str | None

    @property
    def configured(self) -> bool:
        return bool(self.base_url)


def _env_csv(name: str) -> tuple[str, ...]:
    value = os.environ.get(name, "")
    return tuple(part.strip() for part in value.split(",") if part.strip())


def get_registry_config() -> LutRegistryConfig:
    """Resolve registry sync configuration from environment variables.
    从环境变量解析同步配置，显式空地址禁用同步。
    """

    base_url = os.environ.get(
        "LUMINA_LUT_REGISTRY_URL", os.environ.get("LUMINA_MATERIAL_REGISTRY_URL", "")
    ).strip()
    channels = (
        _env_csv("LUMINA_LUT_REGISTRY_CHANNELS")
        or _env_csv("LUMINA_MATERIAL_REGISTRY_CHANNELS")
        or DEFAULT_CHANNELS
    )
    token = (
        os.environ.get("LUMINA_LUT_REGISTRY_TOKEN")
        or os.environ.get("LUMINA_MATERIAL_REGISTRY_TOKEN")
        or ""
    ).strip()
    return LutRegistryConfig(
        base_url=base_url.rstrip("/") or None,
        channels=tuple(channels),
        token=token or None,
    )


def _make_http_client() -> httpx.Client:
    return httpx.Client(timeout=20.0, follow_redirects=False)


def _headers(config: LutRegistryConfig) -> dict[str, str]:
    if not config.token:
        return {}
    return {"Authorization": f"Bearer {config.token}"}


def _require_base_url(config: LutRegistryConfig) -> str:
    if not config.base_url:
        raise LutRegistryConfigError("LUT registry base URL is not configured")
    parsed = urlparse(config.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LutRegistryConfigError("LUT registry base URL must be an HTTP(S) URL")
    if parsed.username or parsed.password:
        raise LutRegistryConfigError("LUT registry base URL must not contain userinfo credentials")
    return config.base_url


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_CATALOG_LIMIT))


def _bounded_offset(offset: int) -> int:
    return max(0, int(offset))


_DISPLAY_NAME_KEYS = ("name", "display_name", "lut_name", "title")


def _clean_display_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _catalog_item_display_name(item: dict[str, Any]) -> str | None:
    display = item.get("display")
    if isinstance(display, dict):
        for key in _DISPLAY_NAME_KEYS:
            text = _clean_display_text(display.get(key))
            if text:
                return text

    for key in _DISPLAY_NAME_KEYS:
        text = _clean_display_text(item.get(key))
        if text:
            return text

    local_path = _clean_display_text(item.get("local_path"))
    if local_path:
        path = PurePosixPath(local_path.replace("\\", "/"))
        return path.stem or path.name

    return _clean_display_text(item.get("lut_id"))


def _record_key_from_item(item: dict[str, Any]) -> str | None:
    lut_id = str(item.get("lut_id") or "").strip()
    revision_id = str(item.get("revision_id") or "").strip()
    if not lut_id or not revision_id:
        return None
    return f"{lut_id}@{revision_id}"


def _normalized_lut_local_parts(local_path: Any, *, strip_cloud_prefix: bool) -> tuple[str, ...] | None:
    if not isinstance(local_path, str) or not local_path.strip():
        return None
    normalized = local_path.strip()
    if not _is_safe_zip_path(normalized):
        return None
    if Path(normalized).suffix.lower() not in ALLOWED_LUT_EXTENSIONS:
        return None
    parts = PurePosixPath(normalized).parts
    if not parts:
        return None
    if strip_cloud_prefix and parts[0].lower() == "cloud":
        parts = parts[1:]
    if not parts or parts[0] == "_sync":
        return None
    return tuple(parts)


def _canonical_cloud_local_path(local_path: Any) -> str | None:
    parts = _normalized_lut_local_parts(local_path, strip_cloud_prefix=True)
    if not parts:
        return None
    return PurePosixPath(*parts).as_posix()


def _safe_lut_path_under_root(local_path: Any, *, cloud: bool) -> Path | None:
    parts = _normalized_lut_local_parts(local_path, strip_cloud_prefix=cloud)
    if not parts:
        return None
    if cloud:
        target_root = LUTManager.cloud_lut_dir().resolve()
    elif parts[0].lower() == "custom":
        target_root = LUTManager.custom_lut_dir().resolve()
        parts = parts[1:]
    elif parts[0].lower() == "cloud":
        target_root = LUTManager.cloud_lut_dir().resolve()
        parts = parts[1:]
    else:
        target_root = Path(LUTManager.LUT_PRESET_DIR).resolve()
    if not parts:
        return None
    try:
        target = (target_root / Path(*parts)).resolve()
        target.relative_to(target_root)
    except (OSError, ValueError):
        return None
    return target


def _existing_lut_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        if path.is_file() and path.suffix.lower() in ALLOWED_LUT_EXTENSIONS:
            return path
    except OSError:
        return None
    return None


def _safe_index_installed_path(record: dict[str, Any]) -> Path | None:
    raw_path = record.get("installed_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    try:
        candidate = Path(raw_path)
        if candidate.is_absolute():
            path = candidate.resolve()
            if LUTManager.logical_lut_path(path) is None:
                return None
        else:
            path = _safe_lut_path_under_root(raw_path, cloud=False)
            if path is None:
                return None
    except (OSError, ValueError):
        return None
    return _existing_lut_path(path)


def _read_installed_index_safe() -> dict[str, Any]:
    try:
        return read_installed_index()
    except LutRegistryPackageError:
        return {"luts": {}}


def _relative_lut_preset_path(path: Path) -> str | None:
    return LUTManager.logical_lut_path(path)


def _catalog_item_local_presence(
    item: dict[str, Any],
    index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    index = index if index is not None else _read_installed_index_safe()
    luts = index.get("luts") if isinstance(index.get("luts"), dict) else {}
    record_key = _record_key_from_item(item)
    if record_key:
        record = luts.get(record_key)
        if isinstance(record, dict):
            installed_path = _safe_index_installed_path(record)
            if installed_path is not None:
                relative_installed_path = _relative_lut_preset_path(installed_path)
                return {
                    "local_state": "installed",
                    "local_exists": True,
                    "local_match_path": relative_installed_path,
                    "installed_path": relative_installed_path,
                    "installed_at": record.get("installed_at"),
                }

    local_path = _existing_lut_path(
        _safe_lut_path_under_root(item.get("local_path"), cloud=False)
    )
    if local_path is None:
        local_path = _existing_lut_path(
            _safe_lut_path_under_root(item.get("local_path"), cloud=True)
        )
    if local_path is not None:
        expected_hash = _hex_digest(item.get("content_hash"))
        local_hash = _local_lut_content_hash(local_path, item.get("local_path"))
        if expected_hash and local_hash != expected_hash:
            return {
                "local_state": "not_installed",
                "local_exists": False,
                "local_match_path": _relative_lut_preset_path(local_path),
            }
        return {
            "local_state": "local_available",
            "local_exists": True,
            "local_match_path": _relative_lut_preset_path(local_path),
        }

    return {
        "local_state": "not_installed",
        "local_exists": False,
        "local_match_path": None,
    }


def _local_lut_content_hash(path: Path, catalog_local_path: Any) -> str | None:
    try:
        file_hash = _sha256(path.read_bytes())
    except OSError:
        return None
    logical_name = PurePosixPath(str(catalog_local_path or path.name).replace("\\", "/")).name
    return _sha256(f"{logical_name}:{file_hash}".encode("utf-8"))


def _normalize_catalog_item(
    item: dict[str, Any],
    index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = dict(item)
    display = normalized.get("display")
    display_record = dict(display) if isinstance(display, dict) else {}
    display_name = _catalog_item_display_name(normalized)
    if display_name:
        if not _clean_display_text(normalized.get("name")):
            normalized["name"] = display_name
        if not _clean_display_text(display_record.get("name")):
            display_record["name"] = display_name
    normalized["display"] = display_record
    normalized.update(_catalog_item_local_presence(normalized, index))
    return normalized


def _normalize_catalog_response(payload: Any, config: LutRegistryConfig) -> dict[str, Any]:
    if isinstance(payload, list):
        items = payload
        total = len(items)
    elif isinstance(payload, dict):
        raw_items = payload.get("items", payload.get("luts", []))
        items = raw_items if isinstance(raw_items, list) else []
        total = payload.get("total", payload.get("total_count", len(items)))
    else:
        raise LutRegistryRemoteError("LUT catalog response must be a JSON object or list")

    index = _read_installed_index_safe()
    normalized_items = [
        _normalize_catalog_item(item, index)
        for item in items[:MAX_CATALOG_LIMIT]
        if isinstance(item, dict)
    ]
    return {
        "configured": config.configured,
        "channels": list(config.channels),
        "items": normalized_items,
        "total": total,
    }


def fetch_remote_catalog(
    *,
    channels: list[str] | tuple[str, ...] | None = None,
    limit: int = MAX_CATALOG_LIMIT,
    offset: int = 0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch a bounded LUT catalog payload from the configured registry.
    从配置的主库读取有界 LUT 目录，临时故障时可尝试公开备用库。
    """

    config = get_registry_config()
    base_url = _require_base_url(config)
    selected_channels = tuple(channels or config.channels)
    params: list[tuple[str, str]] = [
        *[("channel", channel) for channel in selected_channels],
        ("limit", str(_bounded_limit(limit))),
        ("offset", str(_bounded_offset(offset))),
    ]
    owns_client = client is None
    active_client = client or _make_http_client()
    try:
        response = fetch_catalog(
            client=active_client, primary=base_url, family="LUT", suffix="/luts/catalog",
            channels=selected_channels,
            params=params,
            headers=_headers(config),
        )
    except RegistryCatalogNotFoundError as exc:
        raise LutRegistryRemoteError(
            "LUT Registry catalog endpoint was not found (HTTP 404). "
            "Check LUMINA_LUT_REGISTRY_URL, or LUMINA_MATERIAL_REGISTRY_URL "
            "when inherited, and use a Registry service that provides /luts/catalog."
        ) from exc
    except httpx.HTTPError as exc:
        raise LutRegistryRemoteError(f"Failed to fetch LUT catalog: {exc}") from exc
    except ValueError as exc:
        raise LutRegistryRemoteError("LUT catalog response is invalid") from exc
    finally:
        if owns_client:
            active_client.close()

    if 300 <= response.status_code < 400:
        raise LutRegistryRemoteError("LUT catalog request was redirected")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LutRegistryRemoteError(
            f"LUT catalog request failed with status {response.status_code}"
        ) from exc
    try:
        return _normalize_catalog_response(response.json(), config)
    except ValueError as exc:
        raise LutRegistryRemoteError("LUT catalog response is not valid JSON") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex_digest(value: Any) -> str:
    digest = str(value or "").strip().lower()
    if digest.startswith("sha256:"):
        digest = digest.split(":", 1)[1]
    return digest


def _required_content_hash(value: Any, label: str) -> str:
    content_hash = _hex_digest(value)
    if not content_hash:
        raise LutRegistryPackageError(f"{label} content_hash is required")
    if len(content_hash) != 64 or any(char not in _HEX_CHARS for char in content_hash):
        raise LutRegistryPackageError(
            f"{label} content_hash must be a 64-character hex sha256"
        )
    return content_hash


def _validate_expected_bytes(data: bytes, expected: Any, label: str) -> None:
    if expected is None:
        return
    try:
        expected_int = int(expected)
    except (TypeError, ValueError) as exc:
        raise LutRegistryPackageError(f"{label} bytes must be an integer") from exc
    if len(data) != expected_int:
        raise LutRegistryPackageError(
            f"{label} bytes mismatch: expected {expected_int}, got {len(data)}"
        )


def _validate_size_limit(value: int, limit: int, label: str) -> None:
    if value > limit:
        raise LutRegistryPackageError(
            f"{label} exceeds maximum size: {value} > {limit}"
        )


def _required_package_bytes(entry: dict[str, Any]) -> int:
    raw_value = entry.get("package_bytes")
    if raw_value is None:
        raise LutRegistryPackageError("package_bytes is required")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise LutRegistryPackageError("package_bytes must be an integer") from exc
    if value < 0:
        raise LutRegistryPackageError("package_bytes must be non-negative")
    _validate_size_limit(value, MAX_LUT_PACKAGE_BYTES, "LUT package")
    return value


def _required_package_sha256(entry: dict[str, Any]) -> str:
    value = _hex_digest(entry.get("package_sha256"))
    if not value:
        raise LutRegistryPackageError("package_sha256 is required")
    if len(value) != 64 or any(char not in _HEX_CHARS for char in value):
        raise LutRegistryPackageError("package_sha256 must be a 64-character hex digest")
    return value


def _required_lut_file_sha256(file_entry: dict[str, Any]) -> str:
    value = _hex_digest(file_entry.get("sha256"))
    if not value:
        raise LutRegistryPackageError("LUT file sha256 is required")
    if len(value) != 64 or any(char not in _HEX_CHARS for char in value):
        raise LutRegistryPackageError("LUT file sha256 must be a 64-character hex digest")
    return value


def _required_lut_file_bytes(file_entry: dict[str, Any]) -> int:
    raw_value = file_entry.get("bytes")
    if raw_value is None:
        raw_value = file_entry.get("size")
    if raw_value is None:
        raise LutRegistryPackageError("LUT file bytes is required")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise LutRegistryPackageError("LUT file bytes must be an integer") from exc
    if value < 0:
        raise LutRegistryPackageError("LUT file bytes must be non-negative")
    _validate_size_limit(value, MAX_LUT_FILE_BYTES, "LUT file")
    return value


def _validate_expected_sha256(data: bytes, expected: Any, label: str) -> None:
    expected_hash = _hex_digest(expected)
    if not expected_hash:
        return
    actual_hash = _sha256(data)
    if actual_hash != expected_hash:
        raise LutRegistryPackageError(
            f"{label} sha256 mismatch: expected {expected_hash}, got {actual_hash}"
        )


def _is_safe_zip_path(name: str) -> bool:
    if not name or "\\" in name or "//" in name:
        return False
    if name.startswith("/"):
        return False
    path_body = name[:-1] if name.endswith("/") else name
    if not path_body:
        return False
    parts = path_body.split("/")
    if any(not part or part in {".", ".."} or ":" in part for part in parts):
        return False
    pure = PurePosixPath(path_body)
    if pure.is_absolute():
        return False
    return True


def _is_special_zip_entry(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode in {0o120000, 0o020000, 0o060000, 0o010000}


def _normalized_zip_entry_name(info: zipfile.ZipInfo) -> str:
    name = info.filename.replace("\\", "/")
    if info.is_dir():
        name = name.rstrip("/") + "/"
    return name


def _required_parent_dirs(path: str) -> set[str]:
    parts = PurePosixPath(path).parts[:-1]
    return {"/".join(parts[:index]) + "/" for index in range(1, len(parts) + 1)}


def _manifest_lut_file(manifest: dict[str, Any]) -> dict[str, Any]:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise LutRegistryPackageError("LUT package manifest files must be a list")
    lut_files = [item for item in files if isinstance(item, dict) and item.get("role") == "lut_file"]
    if len(lut_files) != 1:
        raise LutRegistryPackageError("LUT package manifest must contain exactly one lut_file")
    return lut_files[0]


def _file_entry_path(file_entry: dict[str, Any]) -> str:
    raw_path = file_entry.get("path") or file_entry.get("name") or file_entry.get("filename")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise LutRegistryPackageError("LUT package lut_file path is required")
    normalized = raw_path.strip()
    if not _is_safe_zip_path(normalized):
        raise LutRegistryPackageError("LUT package contains unsafe lut_file path")
    if Path(normalized).suffix.lower() not in ALLOWED_LUT_EXTENSIONS:
        raise LutRegistryPackageError("LUT package lut_file extension is not supported")
    return normalized


def _zip_info_by_name(zf: zipfile.ZipFile, name: str) -> zipfile.ZipInfo:
    try:
        return zf.getinfo(name)
    except KeyError as exc:
        raise LutRegistryPackageError(f"LUT package entry is missing: {name}") from exc


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
        raise LutRegistryPackageError(f"{label} RGB values must be numeric") from exc

    if rgb.size == 0:
        raise LutRegistryPackageError(f"{label} contains no RGB rows")

    if rgb.ndim == 2 and rgb.shape[1] == 3:
        rows = rgb
    elif rgb.ndim in {1, 3}:
        if rgb.size % 3 != 0:
            raise LutRegistryPackageError(
                f"{label} RGB data is not divisible into RGB triplets"
            )
        rows = rgb.reshape(-1, 3)
    else:
        raise LutRegistryPackageError(f"{label} RGB data must be shaped as N x 3")

    if rows.shape[0] == 0:
        raise LutRegistryPackageError(f"{label} contains no RGB rows")
    if not np.isfinite(rows).all():
        raise LutRegistryPackageError(f"{label} RGB data contains non-finite values")
    if np.any((rows < 0.0) | (rows > 255.0)):
        raise LutRegistryPackageError(f"{label} RGB values must be between 0 and 255")
    return rows


def _validate_lut_payload_file(path: Path) -> None:
    ext = path.suffix.lower()
    display_name = path.stem
    if ext == ".npy":
        try:
            rgb = np.load(path, allow_pickle=False)
        except (OSError, ValueError, TypeError, EOFError) as exc:
            raise LutRegistryPackageError(f"unable to parse NPY data: {exc}") from exc
        _require_rgb_rows(rgb, "NPY LUT")
        return

    if ext == ".npz":
        try:
            with np.load(path, allow_pickle=False) as payload:
                if "rgb" not in payload.files:
                    raise LutRegistryPackageError("NPZ LUT is missing rgb data")
                rgb_rows = _require_rgb_rows(payload["rgb"], "NPZ LUT")
                if "stacks" in payload.files:
                    stacks = np.asarray(payload["stacks"])
                    if stacks.ndim < 2:
                        raise LutRegistryPackageError("NPZ stacks must be a 2D array")
                    if int(stacks.shape[0]) != int(rgb_rows.shape[0]):
                        raise LutRegistryPackageError("NPZ stacks row count does not match rgb")
        except LutRegistryPackageError:
            raise
        except (OSError, ValueError, TypeError, EOFError) as exc:
            raise LutRegistryPackageError(f"unable to parse NPZ data: {exc}") from exc
        return

    if ext == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise LutRegistryPackageError(f"unable to parse JSON data: {exc}") from exc
        _validate_keyed_lut_payload(payload, display_name, str(path), "JSON LUT")
        return

    if ext == ".msgpack":
        try:
            payload = msgpack.unpackb(path.read_bytes(), raw=False)
        except (OSError, ValueError, TypeError, msgpack.UnpackException) as exc:
            raise LutRegistryPackageError(f"unable to parse msgpack data: {exc}") from exc
        if LUTManager._is_model_package_payload(payload):
            try:
                build_model_package_runtime_payload(str(path), payload=payload)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise LutRegistryPackageError(
                    f"model package contains no usable runtime modes: {exc}"
                ) from exc
            return
        _validate_keyed_lut_payload(payload, display_name, str(path), "msgpack LUT")
        return

    raise LutRegistryPackageError(f"unsupported LUT extension: {ext}")


def _validate_keyed_lut_payload(
    payload: Any,
    display_name: str,
    path: str,
    label: str,
) -> None:
    if isinstance(payload, list):
        if not any(_json_entry_has_real_color(entry) for entry in payload):
            raise LutRegistryPackageError(f"{label} contains no valid rgb or lab entries")
        try:
            rgb, _stacks, _metadata = LUTManager._load_keyed_json_flat_list(
                payload,
                display_name,
                path,
            )
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, ImportError) as exc:
            raise LutRegistryPackageError(f"invalid {label} payload: {exc}") from exc
        _require_rgb_rows(rgb, label)
        return

    if isinstance(payload, dict):
        try:
            rgb, _stacks, _metadata = LUTManager._load_keyed_payload(
                payload,
                display_name,
                path,
                skip_malformed_recipes=True,
            )
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, ImportError) as exc:
            raise LutRegistryPackageError(f"invalid {label} payload: {exc}") from exc
        _require_rgb_rows(rgb, label)
        return

    raise LutRegistryPackageError(f"{label} root must be an object or list")


def _validate_lut_bytes_are_loadable(lut_bytes: bytes, lut_path: str) -> None:
    suffix = Path(lut_path).suffix.lower()
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    temp_file = Path(temp_path)
    try:
        temp_file.write_bytes(lut_bytes)
        _validate_lut_payload_file(temp_file)
    finally:
        try:
            temp_file.unlink()
        except OSError:
            pass


def _read_lut_from_package(package_data: bytes, entry_content_hash: str) -> bytes:
    try:
        with zipfile.ZipFile(BytesIO(package_data)) as zf:
            infos = zf.infolist()
            for info in infos:
                if _is_special_zip_entry(info):
                    raise LutRegistryPackageError("LUT package contains special entry")
                if not _is_safe_zip_path(info.filename):
                    raise LutRegistryPackageError("LUT package contains unsafe path")
            normalized_names = [_normalized_zip_entry_name(info) for info in infos]
            if len(normalized_names) != len(set(normalized_names)):
                raise LutRegistryPackageError("LUT package contains duplicate entry")

            manifest_info = _zip_info_by_name(zf, MANIFEST_NAME)
            _validate_size_limit(
                int(manifest_info.file_size),
                MAX_LUT_MANIFEST_BYTES,
                "LUT package manifest",
            )
            try:
                manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
            except KeyError as exc:
                raise LutRegistryPackageError("LUT package manifest is missing") from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LutRegistryPackageError("LUT package manifest is not valid JSON") from exc
            if not isinstance(manifest, dict):
                raise LutRegistryPackageError("LUT package manifest must be a JSON object")

            file_entry = _manifest_lut_file(manifest)
            lut_path = _file_entry_path(file_entry)
            required_names = {MANIFEST_NAME, lut_path}
            allowed_names = {MANIFEST_NAME, lut_path, *_required_parent_dirs(lut_path)}
            actual_names = set(normalized_names)
            extra = sorted(actual_names - allowed_names)
            missing = sorted(required_names - actual_names)
            if extra or missing:
                raise LutRegistryPackageError(
                    f"LUT package contains unexpected payload entries: {extra}"
                )
            lut_info = _zip_info_by_name(zf, lut_path)
            expected_lut_bytes = _required_lut_file_bytes(file_entry)
            _validate_size_limit(int(lut_info.file_size), MAX_LUT_FILE_BYTES, "LUT file")
            if int(lut_info.file_size) != expected_lut_bytes:
                raise LutRegistryPackageError(
                    f"LUT file bytes mismatch: expected {expected_lut_bytes}, got {lut_info.file_size}"
                )
            lut_bytes = zf.read(lut_path)
    except zipfile.BadZipFile as exc:
        raise LutRegistryPackageError("LUT package is not a valid ZIP archive") from exc

    lut_file_sha256 = _required_lut_file_sha256(file_entry)
    _validate_expected_sha256(lut_bytes, lut_file_sha256, "LUT file")
    _validate_expected_bytes(lut_bytes, expected_lut_bytes, "LUT file")
    _validate_lut_bytes_are_loadable(lut_bytes, lut_path)

    manifest_content_hash: str | None = None
    if manifest.get("content_hash") is not None:
        manifest_content_hash = _required_content_hash(
            manifest.get("content_hash"),
            "manifest",
        )
        if manifest_content_hash != entry_content_hash:
            raise LutRegistryPackageError("LUT package content_hash mismatch")

    if file_entry.get("content_hash") is not None:
        file_content_hash = _required_content_hash(
            file_entry.get("content_hash"),
            "manifest lut_file",
        )
        if file_content_hash != lut_file_sha256:
            raise LutRegistryPackageError("LUT file content_hash mismatch")
        if manifest_content_hash is None and file_content_hash != entry_content_hash:
            raise LutRegistryPackageError("LUT file content_hash mismatch")

    if manifest_content_hash is None and file_entry.get("content_hash") is None:
        raise LutRegistryPackageError("LUT package content_hash is required")

    return lut_bytes


def _resolve_same_origin_package_url(raw_url: Any, base_url: str) -> str:
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise LutRegistryPackageError("package_url is required")
    resolved = urljoin(f"{base_url}/", raw_url.strip())
    base = urlparse(base_url)
    parsed = urlparse(resolved)
    if parsed.scheme not in {"http", "https"}:
        raise LutRegistryPackageError("package_url must be HTTP(S)")
    if parsed.query or parsed.fragment:
        raise LutRegistryPackageError("package_url must not contain query or fragment")
    if parsed.username or parsed.password:
        raise LutRegistryPackageError("package_url must not contain userinfo credentials")
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        raise LutRegistryPackageError("package_url origin does not match registry")
    package_path = _validated_url_path(parsed.path, "package_url")
    base_path = _validated_url_path(
        base.path or "/",
        "registry base URL",
        allow_root=True,
    ).rstrip("/")
    base_package_path = f"{base_path}/luts/packages/"
    if not package_path.startswith(base_package_path):
        raise LutRegistryPackageError("package_url must stay under registry luts/packages path")
    return parsed._replace(path=package_path, params="", query="", fragment="").geturl()


def _validated_url_path(path: str, label: str, *, allow_root: bool = False) -> str:
    if allow_root and path in {"", "/"}:
        return "/"
    if not path or "\\" in path or not path.startswith("/") or "//" in path:
        raise LutRegistryPackageError(f"{label} path is unsafe")
    raw_segments = path.lstrip("/").split("/")
    if not raw_segments or any(segment == "" for segment in raw_segments):
        raise LutRegistryPackageError(f"{label} path is unsafe")

    decoded_segments: list[str] = []
    for segment in raw_segments:
        decoded = unquote(segment)
        if (
            not decoded
            or decoded in {".", ".."}
            or ":" in decoded
            or "/" in decoded
            or "\\" in decoded
        ):
            raise LutRegistryPackageError(f"{label} path contains unsafe segment")
        decoded_segments.append(decoded)
    return "/" + "/".join(decoded_segments)


def _safe_cloud_target(local_path: Any) -> Path:
    if not isinstance(local_path, str) or not local_path.strip():
        raise LutRegistryPackageError("local_path is required")
    normalized = local_path.strip()
    if not _is_safe_zip_path(normalized):
        raise LutRegistryPackageError("local_path is unsafe")
    if Path(normalized).suffix.lower() not in ALLOWED_LUT_EXTENSIONS:
        raise LutRegistryPackageError("local_path extension is not supported")
    parts = _normalized_lut_local_parts(local_path, strip_cloud_prefix=True)
    if not parts:
        raise LutRegistryPackageError("local_path is unsafe")

    cloud_root = LUTManager.cloud_lut_dir().resolve()
    target = (cloud_root / Path(*parts)).resolve()
    if target != cloud_root and cloud_root not in target.parents:
        raise LutRegistryPackageError("local_path must stay within Cloud")
    return target


def _index_path() -> Path:
    return LUTManager.cloud_lut_sync_dir() / "index.json"


class _LutRegistryInstallFileLock:
    """Best-effort cross-process lock for cloud LUT install writes."""

    def __init__(self) -> None:
        self._sync_dir = _index_path().parent
        self._lock_path = self._sync_dir / _INSTALL_LOCK_FILENAME
        self._fd: int | None = None

    def __enter__(self) -> "_LutRegistryInstallFileLock":
        self._sync_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(
                str(self._lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            if self._is_stale_lock():
                try:
                    self._lock_path.unlink()
                except OSError as unlink_exc:
                    raise LutRegistryPackageError(
                        "LUT registry install is already running"
                    ) from unlink_exc
                return self.__enter__()
            raise LutRegistryPackageError("LUT registry install is already running") from exc
        lock_payload = json.dumps(
            {"pid": os.getpid(), "created_at": _now_iso()},
            ensure_ascii=False,
        ).encode("utf-8")
        os.write(self._fd, lock_payload)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            pass

    def _is_stale_lock(self) -> bool:
        try:
            raw_stale_seconds = os.environ.get(
                "LUMINA_LUT_REGISTRY_LOCK_STALE_S",
                str(_INSTALL_LOCK_STALE_SECONDS),
            )
            stale_seconds = max(1.0, float(raw_stale_seconds))
        except ValueError:
            stale_seconds = float(_INSTALL_LOCK_STALE_SECONDS)
        try:
            lock_age = time.time() - self._lock_path.stat().st_mtime
        except OSError:
            return False
        return lock_age > stale_seconds


def read_installed_index() -> dict[str, Any]:
    """Read the cloud LUT sync index, returning an empty index when absent."""

    path = _index_path()
    if not path.exists():
        return {"version": 1, "luts": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LutRegistryPackageError("LUT sync index is not readable JSON") from exc
    if not isinstance(payload, dict):
        raise LutRegistryPackageError("LUT sync index must be a JSON object")
    luts = payload.get("luts")
    if not isinstance(luts, dict):
        payload["luts"] = {}
    payload.setdefault("version", 1)
    return payload


def _write_installed_index(payload: dict[str, Any]) -> None:
    path = _index_path()
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError as exc:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise LutRegistryPackageError(f"LUT sync index write failed: {exc}") from exc


def _record_key(entry: dict[str, Any]) -> str:
    lut_id = str(entry.get("lut_id") or "").strip()
    revision_id = str(entry.get("revision_id") or "").strip()
    if not lut_id or not revision_id:
        raise LutRegistryPackageError("lut_id and revision_id are required")
    return f"{lut_id}@{revision_id}"


def _download_limited_package(
    *,
    client: httpx.Client,
    package_url: str,
    headers: dict[str, str],
    expected_bytes: int,
    channels: list[str] | tuple[str, ...] | None = None,
) -> bytes:
    config = get_registry_config()
    primary = config.base_url or ""
    fallback = fallback_base(primary, "LUT")
    try:
        backup_package = map_package_url(package_url, primary, fallback) if fallback else None
    except ValueError:
        backup_package = None
    return read_with_fallback(
        client=client, primary=primary, fallback=fallback if backup_package else None,
        headers=headers, channels=channels or config.channels,
        action=lambda base: _download_limited_package_once(
            client=client, package_url=package_url if base == primary else backup_package,
            headers=headers, expected_bytes=expected_bytes),
    )


def _download_limited_package_once(
    *, client: httpx.Client, package_url: str, headers: dict[str, str], expected_bytes: int,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        with client.stream(
            "GET", package_url, headers=headers, follow_redirects=False
        ) as response:
            if 300 <= response.status_code < 400:
                raise LutRegistryRemoteError("LUT package download was redirected")
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise LutRegistryRemoteError(
                    f"LUT package download failed with status {response.status_code}"
                ) from exc

            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    content_length_int = int(content_length)
                except ValueError as exc:
                    raise LutRegistryPackageError("LUT package Content-Length is invalid") from exc
                _validate_size_limit(
                    content_length_int,
                    MAX_LUT_PACKAGE_BYTES,
                    "LUT package",
                )
                if content_length_int != expected_bytes:
                    raise LutRegistryPackageError(
                        "LUT package Content-Length does not match package_bytes"
                    )

            for chunk in response.iter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_LUT_PACKAGE_BYTES:
                    raise LutRegistryPackageError("LUT package exceeds maximum size")
                if total > expected_bytes:
                    raise LutRegistryPackageError("LUT package bytes exceed package_bytes")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise LutRegistryRemoteError(f"Failed to download LUT package: {exc}") from exc

    package_data = b"".join(chunks)
    _validate_expected_bytes(package_data, expected_bytes, "LUT package")
    return package_data


def _catalog_item_matches(
    item: dict[str, Any],
    *,
    lut_id: str,
    revision_id: str,
) -> bool:
    return (
        str(item.get("lut_id") or "").strip() == lut_id
        and str(item.get("revision_id") or "").strip() == revision_id
    )


def _resolve_catalog_entry_for_install(
    *,
    lut_id: str,
    revision_id: str,
    channels: list[str] | tuple[str, ...] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    if not lut_id or not revision_id:
        raise LutRegistryPackageError("lut_id and revision_id are required")

    offset = 0
    while True:
        catalog = fetch_remote_catalog(
            channels=channels,
            limit=MAX_CATALOG_LIMIT,
            offset=offset,
            client=client,
        )
        items = catalog.get("items") if isinstance(catalog.get("items"), list) else []
        for item in items:
            if isinstance(item, dict) and _catalog_item_matches(
                item,
                lut_id=lut_id,
                revision_id=revision_id,
            ):
                return dict(item)
        loaded_count = len(items)
        try:
            total = int(catalog.get("total", loaded_count))
        except (TypeError, ValueError):
            total = loaded_count
        if loaded_count == 0 or offset + loaded_count >= total:
            break
        offset += loaded_count

    raise LutRegistryPackageError("LUT registry catalog entry was not found")


def _install_verified_catalog_entry(
    entry: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    channels: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Download, validate, and install a cloud LUT package under Cloud/."""

    if not isinstance(entry, dict):
        raise LutRegistryPackageError("Install payload must be a JSON object")
    config = get_registry_config()
    base_url = _require_base_url(config)
    package_url = _resolve_same_origin_package_url(entry.get("package_url"), base_url)
    target = _safe_cloud_target(entry.get("local_path"))
    canonical_local_path = _canonical_cloud_local_path(entry.get("local_path"))
    if canonical_local_path is None:
        raise LutRegistryPackageError("local_path is unsafe")
    package_sha256 = _required_package_sha256(entry)
    package_bytes = _required_package_bytes(entry)
    content_hash = _required_content_hash(entry.get("content_hash"), "catalog entry")

    owns_client = client is None
    active_client = client or _make_http_client()
    try:
        package_data = _download_limited_package(
            client=active_client,
            package_url=package_url,
            headers=_headers(config),
            expected_bytes=package_bytes,
            channels=channels or config.channels,
        )
    finally:
        if owns_client:
            active_client.close()

    _validate_expected_sha256(package_data, package_sha256, "LUT package")
    lut_bytes = _read_lut_from_package(package_data, content_hash)
    target_relative_path = _relative_lut_preset_path(target)
    if target_relative_path is None:
        raise LutRegistryPackageError("LUT install target is outside preset root")

    installed_at = _now_iso()
    record = {
        "lut_id": str(entry.get("lut_id")),
        "revision_id": str(entry.get("revision_id")),
        "content_hash": content_hash,
        "local_path": canonical_local_path,
        "installed_path": target_relative_path,
        "package_sha256": package_sha256,
        "package_bytes": package_bytes,
        "source_url": package_url,
        "installed_at": installed_at,
        "channel": entry.get("channel"),
        "visibility": entry.get("visibility"),
        "display": entry.get("display"),
        "compatibility": entry.get("compatibility"),
    }

    with _INSTALL_LOCK:
        with _LutRegistryInstallFileLock():
            index = read_installed_index()
            index["updated_at"] = installed_at
            index.setdefault("luts", {})[_record_key(entry)] = record
            temp_target = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            backup_target: Path | None = None
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    backup_target = target.with_name(f".{target.name}.{uuid.uuid4().hex}.bak")
                    target.replace(backup_target)
                temp_target.write_bytes(lut_bytes)
                temp_target.replace(target)
                _write_installed_index(index)
            except (OSError, LutRegistryPackageError) as exc:
                try:
                    if temp_target.exists():
                        temp_target.unlink()
                    if target.exists():
                        target.unlink()
                    if backup_target is not None and backup_target.exists():
                        backup_target.replace(target)
                except OSError:
                    pass
                if isinstance(exc, LutRegistryPackageError):
                    raise LutRegistryPackageError(f"LUT install failed: {exc}") from exc
                raise LutRegistryPackageError(f"LUT install failed: {exc}") from exc
            else:
                if backup_target is not None:
                    try:
                        backup_target.unlink()
                    except OSError:
                        pass
    LUTManager.invalidate_preset_cache()
    return record


def install_lut_package(
    *,
    lut_id: str,
    revision_id: str,
    channels: list[str] | tuple[str, ...] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Resolve a registry catalog entry server-side and install its package.
    在服务端校验目录条目后安装，下载回退保留所选频道的权限边界。
    """

    if not isinstance(lut_id, str) or not lut_id.strip():
        raise LutRegistryPackageError("lut_id is required")
    if not isinstance(revision_id, str) or not revision_id.strip():
        raise LutRegistryPackageError("revision_id is required")

    owns_client = client is None
    active_client = client or _make_http_client()
    try:
        entry = _resolve_catalog_entry_for_install(
            lut_id=lut_id.strip(),
            revision_id=revision_id.strip(),
            channels=channels,
            client=active_client,
        )
        return _install_verified_catalog_entry(entry, client=active_client, channels=channels)
    finally:
        if owns_client:
            active_client.close()


def _local_lut_status_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        lut_files = LUTManager.get_all_lut_files()
    except (OSError, RuntimeError, ValueError):
        return entries

    for display_name, raw_path in sorted(lut_files.items(), key=lambda item: item[0].casefold()):
        try:
            path = Path(raw_path).resolve()
            relative_path = LUTManager.logical_lut_path(path)
        except (OSError, ValueError):
            continue
        if relative_path is None:
            continue
        if "_sync" in PurePosixPath(relative_path).parts:
            continue
        entries.append(
            {
                "display_name": display_name,
                "local_path": relative_path,
                "local_exists": path.is_file(),
                "source": "local",
            }
        )
    return entries


def registry_status() -> dict[str, Any]:
    """Return local cloud LUT registry sync status."""

    config = get_registry_config()
    try:
        base_url = _require_base_url(config)
    except LutRegistryConfigError:
        base_url = None
    try:
        index = read_installed_index()
    except LutRegistryPackageError:
        index = {"luts": {}}
    local_entries = _local_lut_status_entries()
    raw_luts = index.get("luts")
    synced_records = raw_luts if isinstance(raw_luts, dict) else {}
    synced_installed_count = sum(
        1
        for record in synced_records.values()
        if isinstance(record, dict) and _safe_index_installed_path(record) is not None
    )
    return {
        "configured": base_url is not None,
        "base_url": base_url,
        "channels": list(config.channels),
        "installed_count": synced_installed_count,
        "local_lut_count": sum(1 for entry in local_entries if bool(entry.get("local_exists"))),
        "local_luts": local_entries,
        "installed": local_entries,
        "synced_count": len(synced_records),
    }
