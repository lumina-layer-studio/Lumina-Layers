"""Local sync index, revision history, refresh lock, and status cache."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from core.filament_display import filament_display
from . import material_files, material_package

_MATERIAL_REGISTRY_AMBIGUOUS_LOCAL_MATCH_FAILURE_DETAIL = (
    "ambiguous_local_match: Local content cannot be matched to one Registry material "
    "unambiguously; automatic installation was skipped."
)

_MATERIAL_SYNC_INDEX_SCHEMA_VERSION = "1.0"

_MATERIAL_SYNC_REFRESH_LOCK_FILENAME = "refresh.lock"

_MATERIAL_SYNC_LOCK_STALE_SECONDS = 2 * 60 * 60

_MATERIAL_SYNC_STATUS_CACHE_TTL_S = 5 * 60

_MATERIAL_REGISTRY_ETAG_MAX_BYTES = 1024

_MATERIAL_SYNC_STATUS_CACHE_LOCK = threading.RLock()

_MATERIAL_SYNC_STATUS_CACHE: dict[str, dict[str, Any]] = {}


def _empty_material_sync_index() -> dict[str, Any]:
    return {
        "schema_version": _MATERIAL_SYNC_INDEX_SCHEMA_VERSION,
        "last_sync_at": None,
        "registries": {},
        "installed": {},
        "revisions": {},
        "local_overrides": {},
        "catalog_validators": {},
    }


def _load_material_sync_index_with_state(target_root: Path) -> tuple[dict[str, Any], str]:
    index_path = target_root / "_sync" / "index.json"
    if not index_path.is_file():
        return _empty_material_sync_index(), "missing"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _empty_material_sync_index(), "invalid"
    if not isinstance(index, dict):
        return _empty_material_sync_index(), "invalid"
    index.setdefault("schema_version", _MATERIAL_SYNC_INDEX_SCHEMA_VERSION)
    index.setdefault("registries", {})
    index.setdefault("installed", {})
    index.setdefault("revisions", {})
    index.setdefault("local_overrides", {})
    index.setdefault("catalog_validators", {})
    return index, "ready"


def _load_material_sync_index(target_root: Path) -> dict[str, Any]:
    index, _index_state = _load_material_sync_index_with_state(target_root)
    return index


def _material_sync_signature(entry: dict[str, Any]) -> tuple[str, str] | None:
    local_directory = str(entry.get("local_directory") or "").strip()
    content_hash = str(entry.get("content_hash") or "").strip()
    if not local_directory or not content_hash:
        return None
    try:
        local_directory = material_files._normalize_relative_directory_name(local_directory)
    except ValueError:
        return None
    return local_directory, content_hash


def _installed_package_identities(target_root: Path) -> dict[tuple[str, str], tuple[str, str]]:
    """Return installed IDs and revisions keyed by their directory and content."""
    installed = _load_material_sync_index(target_root).get("installed")
    if not isinstance(installed, dict):
        return {}

    identities: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for material_id, entry in installed.items():
        if not isinstance(entry, dict):
            continue
        signature = _material_sync_signature(entry)
        revision_id = entry.get("revision_id")
        if signature and material_id.strip() and isinstance(revision_id, str) and revision_id.strip():
            identities.setdefault(signature, set()).add((material_id, revision_id))
    return {
        signature: next(iter(matches))
        for signature, matches in identities.items()
        if len(matches) == 1
    }


def _local_material_sync_entries(target_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not target_root.exists():
        return entries
    root_resolved = target_root.resolve()
    for material_dir in material_files._discover_saved_material_dirs(target_root):
        try:
            package_manifest, _files_to_write = material_package._build_material_bundle_package_manifest(
                target_root=target_root,
                material_dir=material_dir,
            )
            local_directory = material_files._normalize_relative_directory_name(
                str(package_manifest.get("local_directory") or "")
            )
            resolved_material_dir = (target_root / Path(local_directory)).resolve()
            resolved_material_dir.relative_to(root_resolved)
        except (
            FileNotFoundError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            continue
        display = package_manifest.get("display")
        display_payload = display if isinstance(display, dict) else {}
        revision_id = str(package_manifest.get("revision_id") or "")
        entries.append(
            {
                "material_id": str(package_manifest.get("material_id") or ""),
                "revision_id": revision_id,
                "content_hash": str(package_manifest.get("content_hash") or ""),
                "channel": "local",
                "source": "local",
                "local_directory": local_directory,
                "display_brand": str(display_payload.get("brand") or ""),
                "display_name": str(display_payload.get("material_name") or material_dir.name),
                "installed_at": None,
                "updated_at": None,
                "local_exists": resolved_material_dir.is_dir(),
                "material_file_exists": (resolved_material_dir / "material.json").is_file(),
                "available_revisions": [revision_id] if revision_id else [],
            }
        )
    return entries


def _material_sync_binding_projection(index: dict[str, Any]) -> dict[str, Any]:
    def project_entry(
        material_id: str,
        raw_entry: Any,
        *,
        revision_key: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(raw_entry, dict):
            return {
                "material_id": material_id,
                "revision_key": revision_key,
                "invalid_entry": raw_entry,
            }
        return {
            "material_id": material_id,
            "revision_key": revision_key,
            "revision_id": str(raw_entry.get("revision_id") or ""),
            "content_hash": str(raw_entry.get("content_hash") or ""),
            "channel": str(raw_entry.get("channel") or ""),
            "source": str(raw_entry.get("source") or ""),
            "local_directory": str(raw_entry.get("local_directory") or ""),
        }

    installed = index.get("installed")
    installed_projection = [
        project_entry(str(material_id), raw_entry)
        for material_id, raw_entry in (
            installed.items() if isinstance(installed, dict) else ()
        )
    ]
    installed_projection.sort(
        key=lambda entry: str(entry.get("material_id") or "").casefold()
    )

    revisions = index.get("revisions")
    revision_projection: list[dict[str, Any]] = []
    for material_id, raw_revisions in (
        revisions.items() if isinstance(revisions, dict) else ()
    ):
        if not isinstance(raw_revisions, dict):
            revision_projection.append(
                {
                    "material_id": str(material_id),
                    "invalid_revisions": raw_revisions,
                }
            )
            continue
        for revision_id, raw_entry in raw_revisions.items():
            revision_projection.append(
                project_entry(
                    str(material_id),
                    raw_entry,
                    revision_key=str(revision_id),
                )
            )
    revision_projection.sort(
        key=lambda entry: (
            str(entry.get("material_id") or "").casefold(),
            str(entry.get("revision_key") or "").casefold(),
        )
    )
    local_overrides = index.get("local_overrides")
    return {
        "installed": installed_projection,
        "revisions": revision_projection,
        "local_overrides": (
            local_overrides if isinstance(local_overrides, dict) else {}
        ),
    }


def _material_sync_local_state_descriptor(target_root: Path) -> str:
    index = _load_material_sync_index(target_root)
    local_entries: list[dict[str, Any]] = []
    if target_root.exists():
        for material_dir in material_files._discover_saved_material_dirs(target_root):
            try:
                package_manifest, _files_to_write = (
                    material_package._build_material_bundle_package_manifest(
                        target_root=target_root,
                        material_dir=material_dir,
                    )
                )
            except (
                FileNotFoundError,
                OSError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                UnicodeDecodeError,
            ):
                continue
            raw_files = package_manifest.get("files")
            file_records = [
                {
                    "path": str(record.get("path") or ""),
                    "role": str(record.get("role") or ""),
                    "sha256": str(record.get("sha256") or ""),
                    "bytes": int(record.get("bytes") or 0),
                }
                for record in (raw_files if isinstance(raw_files, list) else [])
                if isinstance(record, dict)
            ]
            file_records.sort(key=lambda record: str(record["path"]).casefold())
            local_entries.append(
                {
                    "material_id": str(package_manifest.get("material_id") or ""),
                    "revision_id": str(package_manifest.get("revision_id") or ""),
                    "content_hash": str(package_manifest.get("content_hash") or ""),
                    "local_directory": str(
                        package_manifest.get("local_directory") or ""
                    ),
                    "files": file_records,
                }
            )
    local_entries.sort(
        key=lambda entry: (
            str(entry["local_directory"]).casefold(),
            str(entry["material_id"]),
            str(entry["revision_id"]),
            str(entry["content_hash"]),
        )
    )
    state_payload = {
        "materials": local_entries,
        "bindings": _material_sync_binding_projection(index),
    }
    canonical_state = json.dumps(
        state_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return canonical_state


def _local_material_paths_by_sync_signature(
    target_root: Path,
) -> dict[tuple[str, str], list[Path]]:
    paths_by_signature: dict[tuple[str, str], list[Path]] = {}
    for entry in _local_material_sync_entries(target_root):
        signature = _material_sync_signature(entry)
        local_directory = str(entry.get("local_directory") or "")
        if signature is None or not local_directory:
            continue
        material_dir = target_root / Path(local_directory)
        paths_by_signature.setdefault(signature, []).append(material_dir)
    for material_paths in paths_by_signature.values():
        material_paths.sort(key=lambda path: str(path).casefold())
    return paths_by_signature


def _material_sync_status_cache_key(target_root: Path) -> str:
    try:
        return str(target_root.resolve())
    except OSError:
        return str(target_root.absolute())


def _material_sync_index_marker(target_root: Path) -> tuple[int, int]:
    index_path = target_root / "_sync" / "index.json"
    try:
        stat = index_path.stat()
    except OSError:
        return (0, -1)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _cached_material_sync_status(
    target_root: Path,
    index_marker: tuple[int, int],
) -> dict[str, Any] | None:
    cache_key = _material_sync_status_cache_key(target_root)
    now = time.monotonic()
    with _MATERIAL_SYNC_STATUS_CACHE_LOCK:
        cached = _MATERIAL_SYNC_STATUS_CACHE.get(cache_key)
        if not cached:
            return None
        if cached.get("index_marker") != index_marker:
            return None
        cached_at = float(cached.get("cached_at") or 0.0)
        if now - cached_at > _MATERIAL_SYNC_STATUS_CACHE_TTL_S:
            return None
        payload = cached.get("payload")
        if not isinstance(payload, dict):
            return None
        return material_files._json_clone(payload)


def _store_material_sync_status_cache(
    target_root: Path,
    index_marker: tuple[int, int],
    payload: dict[str, Any],
) -> None:
    cache_key = _material_sync_status_cache_key(target_root)
    with _MATERIAL_SYNC_STATUS_CACHE_LOCK:
        _MATERIAL_SYNC_STATUS_CACHE[cache_key] = {
            "cached_at": time.monotonic(),
            "index_marker": index_marker,
            "payload": material_files._json_clone(payload),
        }


def _invalidate_material_sync_status_cache(target_root: Path) -> None:
    cache_key = _material_sync_status_cache_key(target_root)
    with _MATERIAL_SYNC_STATUS_CACHE_LOCK:
        _MATERIAL_SYNC_STATUS_CACHE.pop(cache_key, None)


def get_material_sync_status(*, materials_dir: str | None = None) -> dict[str, Any]:
    """Return local material sync-index status for API and future cloud sync.
    返回本地耗材同步索引状态，供 API 与后续云同步流程使用。

    Args:
        materials_dir: Optional materials root override. (可选的耗材根目录覆盖)

    Returns:
        dict[str, Any]: Stable status payload with index health and installed
            package presence flags. (包含索引健康状态和已安装包本地存在标记的稳定载荷)
    """
    target_root = Path(materials_dir or material_files.MATERIALS_DIR)
    index_marker = _material_sync_index_marker(target_root)
    cached_status = _cached_material_sync_status(target_root, index_marker)
    if cached_status is not None:
        return cached_status
    index, index_state = _load_material_sync_index_with_state(target_root)
    raw_installed = index.get("installed")
    installed_map = raw_installed if isinstance(raw_installed, dict) else {}
    raw_revisions = index.get("revisions")
    revision_map = raw_revisions if isinstance(raw_revisions, dict) else {}
    installed_entries: list[dict[str, Any]] = []
    seen_signatures: set[tuple[str, str]] = set()
    for raw_material_id, raw_entry in installed_map.items():
        if not isinstance(raw_entry, dict):
            continue
        material_id = str(raw_material_id)
        raw_local_directory = str(raw_entry.get("local_directory") or "").strip()
        local_directory = raw_local_directory
        local_exists = False
        material_file_exists = False
        if raw_local_directory:
            try:
                local_directory = material_files._normalize_relative_directory_name(raw_local_directory)
                root_resolved = target_root.resolve()
                material_dir = (target_root / Path(local_directory)).resolve()
                material_dir.relative_to(root_resolved)
                local_exists = material_dir.is_dir()
                material_file_exists = (material_dir / "material.json").is_file()
            except (OSError, ValueError):
                local_exists = False
                material_file_exists = False
        entry = {
            "material_id": material_id,
            "revision_id": str(raw_entry.get("revision_id") or ""),
            "content_hash": str(raw_entry.get("content_hash") or ""),
            "channel": str(raw_entry.get("channel") or "manual"),
            "source": str(raw_entry.get("source") or "package"),
            "local_directory": local_directory,
            "display_brand": str(raw_entry.get("display_brand") or ""),
            "display_name": str(raw_entry.get("display_name") or ""),
            "installed_at": raw_entry.get("installed_at"),
            "updated_at": raw_entry.get("updated_at"),
            "local_exists": local_exists,
            "material_file_exists": material_file_exists,
            "revision_history": [
                {
                    "revision_id": str(revision_id),
                    "installed_at": revision_entry.get("installed_at"),
                }
                for revision_id, revision_entry in (
                    revision_map.get(material_id, {})
                    if isinstance(revision_map.get(material_id), dict)
                    else {}
                ).items()
                if isinstance(revision_entry, dict)
            ],
            "available_revisions": sorted(
                str(revision_id)
                for revision_id in (
                    revision_map.get(material_id, {})
                    if isinstance(revision_map.get(material_id), dict)
                    else {}
                ).keys()
            ),
        }
        signature = _material_sync_signature(entry)
        if signature is not None:
            seen_signatures.add(signature)
        installed_entries.append(entry)

    for local_entry in _local_material_sync_entries(target_root):
        signature = _material_sync_signature(local_entry)
        if signature is not None and signature in seen_signatures:
            continue
        if signature is not None:
            seen_signatures.add(signature)
        installed_entries.append(local_entry)

    installed_entries.sort(
        key=lambda entry: (
            str(entry["display_brand"]).casefold(),
            str(entry["display_name"]).casefold(),
            str(entry["material_id"]),
        )
    )
    registries = index.get("registries") if isinstance(index.get("registries"), dict) else {}
    local_overrides = (
        index.get("local_overrides")
        if isinstance(index.get("local_overrides"), dict)
        else {}
    )
    status_payload = {
        "schema_version": str(index.get("schema_version") or _MATERIAL_SYNC_INDEX_SCHEMA_VERSION),
        "index_state": index_state,
        "last_sync_at": index.get("last_sync_at"),
        "registries": registries,
        "installed_count": sum(
            1
            for entry in installed_entries
            if bool(entry.get("local_exists")) and bool(entry.get("material_file_exists"))
        ),
        "installed": installed_entries,
        "local_overrides_count": len(local_overrides),
    }
    _store_material_sync_status_cache(target_root, index_marker, status_payload)
    return material_files._json_clone(status_payload)


def _material_sync_metadata_by_directory(target_root: Path) -> dict[str, dict[str, Any]]:
    index = _load_material_sync_index(target_root)
    installed = index.get("installed")
    if not isinstance(installed, dict):
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    for material_id, raw_entry in installed.items():
        if not isinstance(raw_entry, dict):
            continue
        local_directory_raw = str(raw_entry.get("local_directory") or "").strip()
        if not local_directory_raw:
            continue
        try:
            local_directory = material_files._normalize_relative_directory_name(local_directory_raw)
        except ValueError:
            continue
        channel = str(raw_entry.get("channel") or "")
        metadata[local_directory] = {
            "sync_material_id": str(material_id),
            "sync_revision_id": str(raw_entry.get("revision_id") or ""),
            "sync_channel": channel,
            "sync_official": channel == "official",
        }
        if display := filament_display(raw_entry.get("display")):
            metadata[local_directory].update(display=display, display_hash=raw_entry.get("content_hash"))
    return metadata


def _write_material_sync_index(target_root: Path, index: dict[str, Any]) -> None:
    sync_dir = target_root / "_sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    index_path = sync_dir / "index.json"
    tmp_path = sync_dir / f"index.json.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    tmp_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(index_path)
    _invalidate_material_sync_status_cache(target_root)
    material_files._invalidate_material_library_cache(target_root)


def _record_material_sync_entries(
    *,
    target_root: Path,
    installed_packages: list[tuple[dict[str, Any], Path]],
    source: str = "package",
) -> None:
    if not installed_packages:
        return
    now = material_files._now_iso()
    index = _load_material_sync_index(target_root)
    installed = index.setdefault("installed", {})
    if not isinstance(installed, dict):
        installed = {}
        index["installed"] = installed
    revisions = index.setdefault("revisions", {})
    if not isinstance(revisions, dict):
        revisions = {}
        index["revisions"] = revisions
    for package, destination_dir in installed_packages:
        material_id = str(package["material_id"])
        display = package.get("display") if isinstance(package.get("display"), dict) else {}
        material_revisions = revisions.setdefault(material_id, {})
        if not isinstance(material_revisions, dict):
            material_revisions = {}
            revisions[material_id] = material_revisions
        previous_entry = installed.get(material_id)
        if isinstance(previous_entry, dict):
            previous_revision_id = str(previous_entry.get("revision_id") or "")
            if previous_revision_id:
                material_revisions[previous_revision_id] = dict(previous_entry)
        next_entry = {
            "revision_id": str(package["revision_id"]),
            "content_hash": str(package["content_hash"]),
            "channel": str(package.get("channel") or "manual"),
            "source": source,
            "local_directory": material_files._relative_directory_name(target_root, destination_dir),
            "display_brand": str(display.get("brand") or ""),
            "display_name": str(display.get("material_name") or destination_dir.name),
            "display": filament_display(display),
            "installed_at": now,
            "updated_at": now,
        }
        material_revisions[str(next_entry["revision_id"])] = dict(next_entry)
        installed[material_id] = next_entry
    index["last_sync_at"] = now
    _write_material_sync_index(target_root, index)


def _adopt_existing_local_material_bundle_revision(
    *,
    target_root: Path,
    package: dict[str, Any],
    local_paths_by_signature: dict[tuple[str, str], list[Path]],
) -> Path | None:
    signature = _material_sync_signature(package)
    if signature is None:
        return None
    candidate_paths = local_paths_by_signature.get(signature, [])
    if not candidate_paths:
        return None
    if len(candidate_paths) > 1:
        raise ValueError(_MATERIAL_REGISTRY_AMBIGUOUS_LOCAL_MATCH_FAILURE_DETAIL)

    material_id = str(package.get("material_id") or "")
    index = _load_material_sync_index(target_root)
    installed = index.get("installed")
    if isinstance(installed, dict):
        for indexed_material_id, raw_entry in installed.items():
            if str(indexed_material_id) == material_id or not isinstance(raw_entry, dict):
                continue
            if _material_sync_signature(raw_entry) == signature:
                raise ValueError(_MATERIAL_REGISTRY_AMBIGUOUS_LOCAL_MATCH_FAILURE_DETAIL)

    candidate_path = candidate_paths[0]
    try:
        local_package, _files_to_write = material_package._build_material_bundle_package_manifest(
            target_root=target_root,
            material_dir=candidate_path,
        )
    except (
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return None
    if _material_sync_signature(local_package) != signature:
        return None

    _record_material_sync_entries(
        target_root=target_root,
        installed_packages=[(package, candidate_path)],
        source="registry_adopted",
    )
    return candidate_path


def _normalize_material_registry_etag(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    etag = value.strip()
    if (
        not etag
        or len(etag.encode("utf-8")) > _MATERIAL_REGISTRY_ETAG_MAX_BYTES
        or re.fullmatch(r'(?:W/)?"[\x21\x23-\x7e]+"', etag) is None
    ):
        return None
    return etag


def _material_sync_catalog_validator_key(channels: Sequence[str]) -> str:
    return ",".join(channels)


def _material_sync_catalog_validator(
    *,
    index: dict[str, Any],
    registry_url: str,
    channels: Sequence[str],
) -> dict[str, Any] | None:
    validators = index.get("catalog_validators")
    if not isinstance(validators, dict):
        return None
    registry_validators = validators.get(registry_url)
    if not isinstance(registry_validators, dict):
        return None
    raw_validator = registry_validators.get(
        _material_sync_catalog_validator_key(channels)
    )
    if not isinstance(raw_validator, dict):
        return None
    etag = _normalize_material_registry_etag(raw_validator.get("etag"))
    local_state_hash = str(raw_validator.get("local_state_hash") or "")
    checked_count = raw_validator.get("checked_count")
    if (
        etag is None
        or not local_state_hash
        or isinstance(checked_count, bool)
        or not isinstance(checked_count, int)
        or checked_count < 0
        or raw_validator.get("channels") != list(channels)
    ):
        return None
    return {
        "etag": etag,
        "local_state_hash": local_state_hash,
        "checked_count": checked_count,
        "channels": list(channels),
    }


def _update_material_sync_catalog_validator(
    *,
    index: dict[str, Any],
    registry_url: str,
    channels: Sequence[str],
    validator: dict[str, Any] | None,
    now: str,
) -> None:
    validators = index.setdefault("catalog_validators", {})
    if not isinstance(validators, dict):
        validators = {}
        index["catalog_validators"] = validators
    channel_key = _material_sync_catalog_validator_key(channels)
    if validator is None:
        registry_validators = validators.get(registry_url)
        if isinstance(registry_validators, dict):
            registry_validators.pop(channel_key, None)
            if not registry_validators:
                validators.pop(registry_url, None)
        return

    registry_validators = validators.setdefault(registry_url, {})
    if not isinstance(registry_validators, dict):
        registry_validators = {}
        validators[registry_url] = registry_validators
    registry_validators[channel_key] = {
        "etag": str(validator["etag"]),
        "local_state_hash": str(validator["local_state_hash"]),
        "checked_count": int(validator["checked_count"]),
        "channels": list(channels),
        "updated_at": now,
    }


def _record_material_registry_refresh(
    *,
    target_root: Path,
    registry_url: str,
    channels: list[str],
    cursor: Any,
    checked_count: int,
    installed_count: int,
    skipped_count: int,
    failed_count: int,
    catalog_validator: dict[str, Any] | None,
) -> None:
    now = material_files._now_iso()
    index = _load_material_sync_index(target_root)
    registries = index.setdefault("registries", {})
    if not isinstance(registries, dict):
        registries = {}
        index["registries"] = registries
    registries[registry_url] = {
        "url": registry_url,
        "channels": list(channels),
        "last_refresh_at": now,
        "last_cursor": str(cursor) if cursor is not None else None,
        "checked_count": checked_count,
        "installed_count": installed_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
    }
    _update_material_sync_catalog_validator(
        index=index,
        registry_url=registry_url,
        channels=channels,
        validator=catalog_validator,
        now=now,
    )
    index["last_sync_at"] = now
    _write_material_sync_index(target_root, index)


def _installed_material_bundle_revision_path(
    *,
    target_root: Path,
    package: dict[str, Any],
    include_revision_history: bool = False,
    index: dict[str, Any] | None = None,
) -> Path | None:
    material_id = str(package.get("material_id") or "")
    if not material_id:
        return None
    if index is None:
        index = _load_material_sync_index(target_root)
    installed = index.get("installed")
    if not isinstance(installed, dict):
        return None
    entry = installed.get(material_id)
    if isinstance(entry, dict):
        material_dir = _material_sync_revision_entry_path(
            target_root=target_root,
            entry=entry,
            package=package,
        )
        if material_dir is not None:
            return material_dir
    if include_revision_history:
        revisions = index.get("revisions")
        material_revisions = (
            revisions.get(material_id)
            if isinstance(revisions, dict)
            else None
        )
        revision_entry = (
            material_revisions.get(str(package.get("revision_id") or ""))
            if isinstance(material_revisions, dict)
            else None
        )
        if isinstance(revision_entry, dict):
            material_dir = _material_sync_revision_entry_path(
                target_root=target_root,
                entry=revision_entry,
                package=package,
            )
            if material_dir is not None:
                return material_dir
    return None


def _material_sync_revision_entry_path(
    *,
    target_root: Path,
    entry: dict[str, Any],
    package: dict[str, Any],
) -> Path | None:
    if str(entry.get("revision_id") or "") != str(package.get("revision_id") or ""):
        return None
    if str(entry.get("content_hash") or "") != str(package.get("content_hash") or ""):
        return None
    local_directory = entry.get("local_directory")
    if not isinstance(local_directory, str) or not local_directory.strip():
        return None
    try:
        material_dir = material_files.resolve_saved_material_dir(target_root, local_directory)
        archive_path = material_dir / "material.json"
        archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
        if not isinstance(archive_payload, dict):
            return None
        actual_content_hash = material_package._local_material_content_hash(
            material_dir,
            archive_payload,
        )
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return None
    if actual_content_hash == str(package.get("content_hash") or ""):
        return material_dir
    return None


class _MaterialSyncRefreshFileLock:
    """Best-effort cross-process lock for one materials root refresh.
    单个 materials 根目录刷新用的跨进程锁。
    """

    def __init__(self, target_root: Path) -> None:
        self._sync_dir = target_root / "_sync"
        self._lock_path = self._sync_dir / _MATERIAL_SYNC_REFRESH_LOCK_FILENAME
        self._fd: int | None = None

    def __enter__(self) -> "_MaterialSyncRefreshFileLock":
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
                    raise RuntimeError(
                        "Material sync refresh is already running"
                    ) from unlink_exc
                return self.__enter__()
            raise RuntimeError("Material sync refresh is already running") from exc
        lock_payload = json.dumps(
            {"pid": os.getpid(), "created_at": material_files._now_iso()},
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
                "LUMINA_MATERIAL_SYNC_LOCK_STALE_S",
                str(_MATERIAL_SYNC_LOCK_STALE_SECONDS),
            )
            stale_seconds = max(1.0, float(raw_stale_seconds))
        except ValueError:
            stale_seconds = float(_MATERIAL_SYNC_LOCK_STALE_SECONDS)
        try:
            lock_age = datetime.now(timezone.utc).timestamp() - self._lock_path.stat().st_mtime
        except OSError:
            return False
        return lock_age > stale_seconds


def rollback_material_sync_revision(
    *,
    material_id: str,
    revision_id: str,
    materials_dir: str | None = None,
) -> dict[str, Any]:
    """Make a previously installed material revision current again.
    将历史耗材 revision 重新设为当前版本。

    Args:
        material_id: Stable synced material identity. (稳定耗材身份)
        revision_id: Revision to restore. (要恢复的 revision)
        materials_dir: Optional materials root override. (可选耗材根目录覆盖)

    Returns:
        dict[str, Any]: Current installed sync entry after rollback.
            回滚后的当前同步条目。
    """
    cleaned_material_id = str(material_id or "").strip()
    cleaned_revision_id = str(revision_id or "").strip()
    if not cleaned_material_id or not cleaned_revision_id:
        raise ValueError("material_id and revision_id are required")
    target_root = Path(materials_dir or material_files.MATERIALS_DIR)
    index = _load_material_sync_index(target_root)
    installed = index.setdefault("installed", {})
    revisions = index.setdefault("revisions", {})
    if not isinstance(installed, dict) or not isinstance(revisions, dict):
        raise ValueError("Material sync index is invalid")
    material_revisions = revisions.get(cleaned_material_id)
    if not isinstance(material_revisions, dict):
        raise FileNotFoundError(
            f"Material sync revision not found: {cleaned_material_id}/{cleaned_revision_id}"
        )
    target_entry = material_revisions.get(cleaned_revision_id)
    if not isinstance(target_entry, dict):
        raise FileNotFoundError(
            f"Material sync revision not found: {cleaned_material_id}/{cleaned_revision_id}"
        )
    local_directory = material_files._normalize_relative_directory_name(
        str(target_entry.get("local_directory") or "")
    )
    material_dir = target_root / local_directory
    if not (material_dir / "material.json").is_file():
        raise FileNotFoundError(
            f"Material sync rollback target is missing material.json: {local_directory}"
        )

    current_entry = installed.get(cleaned_material_id)
    if isinstance(current_entry, dict):
        current_revision_id = str(current_entry.get("revision_id") or "")
        if current_revision_id:
            material_revisions[current_revision_id] = dict(current_entry)

    next_entry = dict(target_entry)
    next_entry["revision_id"] = cleaned_revision_id
    next_entry["updated_at"] = material_files._now_iso()
    material_revisions[cleaned_revision_id] = dict(next_entry)
    installed[cleaned_material_id] = next_entry
    index["last_sync_at"] = next_entry["updated_at"]
    _write_material_sync_index(target_root, index)
    return {
        "material_id": cleaned_material_id,
        "revision_id": cleaned_revision_id,
        "content_hash": str(next_entry.get("content_hash") or ""),
        "channel": str(next_entry.get("channel") or ""),
        "local_directory": local_directory,
    }
