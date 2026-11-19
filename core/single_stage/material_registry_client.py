"""Read-only Registry catalog, package downloads, and synchronization.

Installation imports the library locally so archive listing can use catalog
metadata without a circular module import.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urljoin, urlsplit

from api.structured_logging import get_logger
from core.filament_display import catalog_thumbnail_metadata
from core.public_resources import PUBLIC_REGISTRY_URL, material_registry_url, registry_read_token, is_static_catalog
from core.registry_catalog_cache import CatalogAccessDenied, CatalogSnapshot, catalog_source_scope
from core.registry_transport import (
    fallback_base,
    fetch_catalog,
    map_package_url,
    read_with_fallback,
)

from . import material_files, material_package, material_sync

# Keep the existing log identity across the source split.
_log = get_logger("core.single_stage.materials")

_MATERIAL_PACKAGE_DOWNLOAD_CHUNK_BYTES = 1024 * 1024

_MATERIAL_REGISTRY_REFRESH_PACKAGE_FAILURE_DETAIL = (
    "Material registry package could not be installed. "
    "Check the package and try refreshing again."
)

_MATERIAL_REGISTRY_AMBIGUOUS_REVISION_FAILURE_DETAIL = (
    "ambiguous_revision: Registry returned multiple revisions for one material; "
    "automatic installation was skipped."
)

_MATERIAL_REGISTRY_REFRESH_PUBLIC_ERROR_PREFIXES = {
    "ambiguous_revision:": _MATERIAL_REGISTRY_AMBIGUOUS_REVISION_FAILURE_DETAIL,
    "ambiguous_local_match:": material_sync._MATERIAL_REGISTRY_AMBIGUOUS_LOCAL_MATCH_FAILURE_DETAIL,
    "Material registry package exceeds maximum size": (
        "Material registry package exceeds maximum size."
    ),
    "Material registry package_url must be http:// or https://": (
        "Material registry package_url must be http:// or https://."
    ),
    "Material registry package_url must use the same origin": (
        "Material registry package_url must use the same origin."
    ),
    "Material registry package redirects are not allowed": (
        "Material registry package redirects are not allowed."
    ),
    "Material registry package_sha256 is invalid": (
        "Material registry package_sha256 is invalid."
    ),
    "Material registry package_sha256 mismatch": (
        "Material registry package_sha256 mismatch."
    ),
    "Material registry catalog entry is missing material identity": (
        "Material registry catalog entry is missing material identity."
    ),
    "Material package ZIP has too many entries": (
        "Material registry package ZIP has too many entries."
    ),
    "Material package ZIP entry exceeds maximum size": (
        "Material registry package ZIP entry exceeds maximum size."
    ),
    "Material package ZIP uncompressed size exceeds maximum": (
        "Material registry package ZIP contents exceed the supported size."
    ),
    "Material package ZIP compression ratio is too high": (
        "Material registry package ZIP compression ratio is too high."
    ),
}

_MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_TTL_S = 5 * 60

_MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_LOCK = threading.RLock()

_MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE: dict[
    tuple[str, tuple[str, ...], str, Any, int | None, int, str],
    dict[str, Any],
] = {}


def _official_material_registry_metadata_by_signature() -> dict[tuple[str, str], dict[str, Any]]:
    try:
        catalog = list_material_registry_catalog(
            channels=["official"],
            limit=None,
            offset=0,
        )
    except Exception:
        return {}
    metadata: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in _material_registry_catalog_entries(catalog):
        if str(entry.get("channel") or "") != "official":
            continue
        signature = material_sync._material_sync_signature(entry)
        if signature is None:
            continue
        metadata[signature] = {
            "sync_material_id": str(entry.get("material_id") or ""),
            "sync_revision_id": str(entry.get("revision_id") or ""),
            "sync_channel": "official",
            "sync_official": True,
        }
    return metadata


def _apply_official_registry_metadata(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    official_by_signature = _official_material_registry_metadata_by_signature()
    if not official_by_signature:
        return items
    for item in items:
        if bool(item.get("sync_official")):
            continue
        signature = material_sync._material_sync_signature(
            {
                "local_directory": item.get("directory_name"),
                "content_hash": item.get("content_hash"),
            }
        )
        if signature is None:
            continue
        official_metadata = official_by_signature.get(signature)
        if official_metadata:
            item.update(official_metadata)
    return items


def _material_registry_catalog_is_locally_converged(
    *,
    target_root: Path,
    catalog_entries: Sequence[dict[str, Any]],
) -> bool:
    for entry in catalog_entries:
        if not all(
            str(entry.get(field) or "").strip()
            for field in ("material_id", "revision_id", "content_hash")
        ):
            return False
        if material_sync._installed_material_bundle_revision_path(
            target_root=target_root,
            package=entry,
            include_revision_history=True,
        ) is None:
            return False
    return True


def _normalize_material_registry_url(registry_url: str | None) -> str:
    raw_url = str(
        registry_url
        if registry_url is not None
        else material_registry_url()
    ).strip()
    if not raw_url:
        raise ValueError("Material registry URL is not configured")
    if not raw_url.startswith(("http://", "https://")):
        raise ValueError("Material registry URL must be http:// or https://")
    return raw_url.rstrip("/")


def _normalize_material_registry_channels(
    channels: Sequence[str] | None, *, registry_url: str | None = None,
) -> list[str]:
    if channels is None:
        source = registry_url or material_registry_url()
        defaults = "official,community" if source == PUBLIC_REGISTRY_URL or is_static_catalog(source) else "official"
        raw_channels = defaults if is_static_catalog(source) else os.environ.get("LUMINA_MATERIAL_REGISTRY_CHANNELS", defaults)
        candidates = re.split(r"[,;\s]+", raw_channels)
    else:
        candidates = [str(channel) for channel in channels]
    normalized: list[str] = []
    for raw_channel in candidates:
        channel = str(raw_channel).strip()
        if not channel:
            continue
        if not re.fullmatch(r"[a-z0-9_-]+", channel):
            raise ValueError(f"Material registry channel is invalid: {channel}")
        if channel not in normalized:
            normalized.append(channel)
    return normalized or ["official"]


def configured_material_catalog_scope() -> str:
    """Identify the current read scope even if the registry is unreachable."""
    try:
        source = _normalize_material_registry_url(None)
        channels = _normalize_material_registry_channels(None, registry_url=source)
    except ValueError:
        return catalog_source_scope("", [], None)
    return catalog_source_scope(source, channels, registry_read_token("MATERIAL", source))


def _sha256_hex_from_catalog(value: Any) -> str:
    raw_value = str(value or "").strip().lower()
    if raw_value.startswith("sha256:"):
        raw_value = raw_value.split(":", 1)[1]
    if not re.fullmatch(r"[0-9a-f]{64}", raw_value):
        raise ValueError("Material registry package_sha256 is invalid")
    return raw_value


def _material_registry_catalog_entries(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Material registry catalog response must be a JSON object")
    entries = payload.get("materials")
    if entries is None:
        entries = payload.get("packages")
    if not isinstance(entries, list):
        raise ValueError("Material registry catalog response is missing materials")
    normalized_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Material registry catalog contains invalid entry")
        normalized_entries.append(catalog_thumbnail_metadata(entry))
    return normalized_entries


def _material_registry_catalog_url(registry_url: str) -> str:
    return f"{registry_url}/materials/catalog"


def _material_registry_url_origin_key(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port is None and scheme == "https":
        port = 443
    elif port is None and scheme == "http":
        port = 80
    return scheme, hostname, port


def _material_registry_package_url(registry_url: str, raw_package_url: Any) -> str:
    package_url = str(raw_package_url or "").strip()
    if not package_url:
        raise ValueError("Material registry catalog entry is missing package_url")
    resolved_url = urljoin(f"{registry_url}/", package_url)
    if is_static_catalog(registry_url):
        return map_package_url(package_url, registry_url, registry_url)
    if not resolved_url.startswith(("http://", "https://")):
        raise ValueError("Material registry package_url must be http:// or https://")
    if _material_registry_url_origin_key(resolved_url) != _material_registry_url_origin_key(
        registry_url
    ):
        raise ValueError("Material registry package_url must use the same origin")
    return resolved_url


def _reject_material_registry_package_redirect(response: Any) -> None:
    if bool(getattr(response, "is_redirect", False)):
        raise ValueError("Material registry package redirects are not allowed")


def _reject_material_registry_catalog_redirect(response: Any) -> None:
    if (
        int(getattr(response, "status_code", 0)) != 304
        and bool(getattr(response, "is_redirect", False))
    ):
        raise RuntimeError("Material registry catalog redirects are not allowed")


def _request_material_registry_refresh_catalog(
    *,
    client: Any,
    registry_url: str,
    channels: Sequence[str],
    headers: dict[str, str],
    etag: str | None,
) -> Any:
    response = fetch_catalog(
        client=client, primary=registry_url, family="MATERIAL", suffix="/materials/catalog",
        channels=channels, etag=etag,
        params=[("channel", channel) for channel in channels],
        headers=headers,
    )
    _reject_material_registry_catalog_redirect(response)
    if int(response.status_code) != 304:
        response.raise_for_status()
    return response


def _public_material_registry_refresh_failure_error(exc: BaseException) -> str:
    message = str(exc).strip()
    for prefix, public_error in _MATERIAL_REGISTRY_REFRESH_PUBLIC_ERROR_PREFIXES.items():
        if message.startswith(prefix):
            return public_error
    return _MATERIAL_REGISTRY_REFRESH_PACKAGE_FAILURE_DETAIL


def _new_temp_material_registry_package_path() -> tuple[int, Path]:
    temp_root = Path(material_files.TEMP_DIR)
    temp_root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="material_registry_package_",
        suffix=".zip",
        dir=temp_root,
    )
    return fd, Path(temp_name)


def _download_material_registry_package_to_tempfile(
    *,
    client: Any,
    package_url: str,
    headers: dict[str, str],
    expected_package_sha256: str,
    identity_label: str,
    max_archive_bytes: int | None = None,
    registry_url: str | None = None,
    channels: Sequence[str] | None = None,
) -> Path:
    primary = str(registry_url if registry_url is not None else material_registry_url()).rstrip("/")
    fallback = fallback_base(primary, "MATERIAL")
    try:
        backup_package = map_package_url(package_url, primary, fallback) if fallback else None
    except ValueError:
        backup_package = None
    return read_with_fallback(
        client=client, primary=primary, fallback=fallback if backup_package else None,
        headers=headers, channels=_normalize_material_registry_channels(channels),
        action=lambda base: _download_material_registry_package_once(
            client=client, package_url=package_url if base == primary else backup_package,
            headers=headers, expected_package_sha256=expected_package_sha256,
            identity_label=identity_label, max_archive_bytes=max_archive_bytes),
    )


def _download_material_registry_package_once(
    *, client: Any, package_url: str, headers: dict[str, str],
    expected_package_sha256: str, identity_label: str,
    max_archive_bytes: int | None = None,
) -> Path:
    if max_archive_bytes is None:
        max_archive_bytes = material_package.material_package_max_archive_bytes()
    with client.stream(
        "GET",
        package_url,
        headers=headers,
        follow_redirects=False,
    ) as response:
        _reject_material_registry_package_redirect(response)
        response.raise_for_status()
        content_length = str(response.headers.get("content-length") or "").strip()
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = 0
            if declared_length > max_archive_bytes:
                raise ValueError(
                    "Material registry package exceeds maximum size: "
                    f"{declared_length} > {max_archive_bytes}"
                )
        fd, temp_package_path = _new_temp_material_registry_package_path()
        digest = hashlib.sha256()
        total_bytes = 0
        try:
            with os.fdopen(fd, "wb") as handle:
                for chunk in response.iter_bytes(
                    chunk_size=_MATERIAL_PACKAGE_DOWNLOAD_CHUNK_BYTES
                ):
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > max_archive_bytes:
                        raise ValueError(
                            "Material registry package exceeds maximum size: "
                            f"{total_bytes} > {max_archive_bytes}"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
            actual_package_sha256 = digest.hexdigest()
            if actual_package_sha256 != expected_package_sha256:
                raise ValueError(
                    "Material registry package_sha256 mismatch: "
                    f"{identity_label}"
                )
            return temp_package_path
        except Exception:
            try:
                temp_package_path.unlink()
            except OSError:
                pass
            raise


def _material_registry_remote_catalog_cache_key(
    *,
    registry_url: str,
    channels: Sequence[str],
    token: str,
    transport: Any,
    limit: int | None,
    offset: int,
    query: str,
) -> tuple[str, tuple[str, ...], str, Any, int | None, int, str]:
    transport_identity = transport if transport is not None else None
    return (
        registry_url,
        tuple(channels),
        token,
        transport_identity,
        limit,
        offset,
        query,
    )


def _normalize_material_registry_catalog_pagination(
    *,
    limit: int | None = None,
    offset: int | None = 0,
) -> tuple[int | None, int]:
    normalized_offset = 0 if offset is None else int(offset)
    if normalized_offset < 0:
        raise ValueError("Material registry catalog offset must be non-negative")
    if limit is None:
        return None, normalized_offset
    normalized_limit = int(limit)
    if normalized_limit <= 0:
        raise ValueError("Material registry catalog limit must be positive")
    return normalized_limit, normalized_offset


def _page_material_registry_catalog_entries(
    entries: list[dict[str, Any]],
    *,
    limit: int | None,
    offset: int,
) -> list[dict[str, Any]]:
    if limit is None:
        return entries[offset:]
    return entries[offset : offset + limit]


def _page_material_registry_catalog(
    catalog: dict[str, Any],
    *,
    limit: int | None,
    offset: int,
) -> dict[str, Any]:
    raw_entries = catalog.get("materials")
    entries = raw_entries if isinstance(raw_entries, list) else []
    paged_entries = _page_material_registry_catalog_entries(
        entries,
        limit=limit,
        offset=offset,
    )
    payload = dict(catalog)
    payload["count"] = len(paged_entries)
    payload["total_count"] = int(catalog.get("total_count") or len(entries))
    payload["offset"] = offset
    payload["limit"] = limit
    payload["materials"] = paged_entries
    return material_files._json_clone(payload)


def _normalize_material_registry_catalog_query(query: str | None = None) -> str:
    return " ".join(str(query or "").casefold().split())


def _material_registry_catalog_entry_matches_query(
    entry: dict[str, Any],
    query: str,
) -> bool:
    if not query:
        return True
    searchable_values: list[str] = [
        str(entry.get("material_id") or ""),
        str(entry.get("revision_id") or ""),
        str(entry.get("content_hash") or ""),
        str(entry.get("channel") or ""),
        str(entry.get("visibility") or ""),
        str(entry.get("local_directory") or ""),
    ]
    for key in ("display", "compatibility"):
        value = entry.get(key)
        if isinstance(value, dict):
            searchable_values.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    haystack = " ".join(searchable_values).casefold()
    return all(token in haystack for token in query.split())


def _filter_material_registry_catalog(
    catalog: dict[str, Any],
    *,
    query: str,
) -> dict[str, Any]:
    if not query:
        return material_files._json_clone(catalog)
    raw_entries = catalog.get("materials")
    entries = raw_entries if isinstance(raw_entries, list) else []
    filtered_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and _material_registry_catalog_entry_matches_query(entry, query)
    ]
    payload = dict(catalog)
    payload["materials"] = filtered_entries
    payload["count"] = len(filtered_entries)
    payload["total_count"] = len(filtered_entries)
    payload["offset"] = 0
    payload["limit"] = None
    return material_files._json_clone(payload)


def _cached_material_registry_remote_catalog(
    *,
    registry_url: str,
    channels: Sequence[str],
    token: str,
    transport: Any,
    limit: int | None,
    offset: int,
    query: str,
) -> dict[str, Any] | None:
    cache_key = _material_registry_remote_catalog_cache_key(
        registry_url=registry_url,
        channels=channels,
        token=token,
        transport=transport,
        limit=limit,
        offset=offset,
        query=query,
    )
    now = time.monotonic()
    with _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_LOCK:
        cached = _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE.get(cache_key)
        if not cached:
            return None
        cached_at = float(cached.get("cached_at") or 0.0)
        if now - cached_at > _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_TTL_S:
            _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE.pop(cache_key, None)
            return None
        payload = cached.get("payload")
        if not isinstance(payload, dict):
            return None
        return material_files._json_clone(payload)


def _store_material_registry_remote_catalog_cache(
    *,
    registry_url: str,
    channels: Sequence[str],
    token: str,
    transport: Any,
    limit: int | None,
    offset: int,
    query: str,
    payload: dict[str, Any],
) -> None:
    cache_key = _material_registry_remote_catalog_cache_key(
        registry_url=registry_url,
        channels=channels,
        token=token,
        transport=transport,
        limit=limit,
        offset=offset,
        query=query,
    )
    with _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_LOCK:
        _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE[cache_key] = {
            "cached_at": time.monotonic(),
            "payload": material_files._json_clone(payload),
        }


def invalidate_material_registry_remote_catalog_cache(
    *,
    registry_url: str | None = None,
) -> None:
    """Clear cached remote material Registry catalog payloads.
    清理远端耗材 Registry catalog 缓存。
    """
    normalized_registry_url = (
        _normalize_material_registry_url(registry_url)
        if registry_url is not None
        else None
    )
    with _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_LOCK:
        if normalized_registry_url is None:
            _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE.clear()
            return
        stale_keys = [
            cache_key
            for cache_key in _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE
            if cache_key[0] == normalized_registry_url
        ]
        for cache_key in stale_keys:
            _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE.pop(cache_key, None)


def list_material_registry_catalog(
    *,
    registry_url: str | None = None,
    channels: Sequence[str] | None = None,
    query: str | None = None,
    token: str | None = None,
    timeout_s: float | None = None,
    transport: Any = None,
    use_cache: bool = True,
    limit: int | None = None,
    offset: int | None = 0,
) -> dict[str, Any]:
    """Fetch the remote material Registry catalog without installing packages.
    只读取远程耗材 Registry catalog，不安装任何耗材包。
    """
    import httpx

    normalized_registry_url = _normalize_material_registry_url(registry_url)
    normalized_channels = _normalize_material_registry_channels(channels, registry_url=normalized_registry_url)
    normalized_limit, normalized_offset = _normalize_material_registry_catalog_pagination(
        limit=limit,
        offset=offset,
    )
    normalized_query = _normalize_material_registry_catalog_query(query)
    auth_token = str(
        token
        if token is not None
        else registry_read_token("MATERIAL", normalized_registry_url)
    ).strip()
    if use_cache:
        cached_catalog = _cached_material_registry_remote_catalog(
            registry_url=normalized_registry_url,
            channels=normalized_channels,
            token=auth_token,
            transport=transport,
            limit=normalized_limit,
            offset=normalized_offset,
            query=normalized_query,
        )
        if cached_catalog is not None:
            return cached_catalog
        if normalized_limit is not None or normalized_offset:
            cached_full_catalog = _cached_material_registry_remote_catalog(
                registry_url=normalized_registry_url,
                channels=normalized_channels,
                token=auth_token,
                transport=transport,
                limit=None,
                offset=0,
                query=normalized_query,
            )
            if cached_full_catalog is not None:
                return _page_material_registry_catalog(
                    cached_full_catalog,
                    limit=normalized_limit,
                    offset=normalized_offset,
                )

    if timeout_s is None:
        raw_timeout = os.environ.get("LUMINA_MATERIAL_REGISTRY_TIMEOUT_S", "30")
        try:
            timeout_s = float(raw_timeout)
        except ValueError:
            timeout_s = 30.0

    headers = {"User-Agent": "LuminaStudioMaterialSync/1"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    client_kwargs: dict[str, Any] = {
        "timeout": float(timeout_s),
        "follow_redirects": True,
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    catalog_params: list[tuple[str, str | int]] = [
        ("channel", channel) for channel in normalized_channels
    ]
    if normalized_query:
        catalog_params.append(("q", normalized_query))
    if normalized_limit is not None or normalized_offset:
        catalog_params.append(("offset", normalized_offset))
    if normalized_limit is not None:
        catalog_params.append(("limit", normalized_limit))

    cache_dir = Path(material_files.MATERIALS_DIR) / "_sync/catalogs" if transport is None else None

    def offline_full_page() -> httpx.Response | None:
        """A complete public snapshot can also satisfy a new page or search."""
        if cache_dir is None:
            return None
        full_params = [("channel", channel) for channel in normalized_channels]
        full_response = CatalogSnapshot(cache_dir, normalized_registry_url, "/materials/catalog", full_params).response(offline=True)
        if full_response is None:
            return None
        payload = full_response.json()
        entries = _material_registry_catalog_entries(payload)
        if isinstance(payload, dict) and (payload.get("offset", 0) != 0 or payload.get("total_count", len(entries)) != len(entries)):
            return None  # A capped server response is not a complete catalog.
        full_catalog = {"schema_version": payload.get("schema_version", "1.0") if isinstance(payload, dict) else "1.0",
                        "channels": normalized_channels, "materials": entries, "count": len(entries),
                        "total_count": len(entries), "offset": 0, "limit": None}
        page = _page_material_registry_catalog(_filter_material_registry_catalog(full_catalog, query=normalized_query),
                                               limit=normalized_limit, offset=normalized_offset)
        return httpx.Response(200, json=page, headers=full_response.headers, request=full_response.request)

    with httpx.Client(**client_kwargs) as client:
        try:
            catalog_response = fetch_catalog(
                client=client, primary=normalized_registry_url, family="MATERIAL",
                suffix="/materials/catalog", channels=normalized_channels,
                params=catalog_params,
                headers=headers,
                cache_dir=cache_dir, offline_fallback=offline_full_page,
                force_refresh=not use_cache,
            )
            _reject_material_registry_catalog_redirect(catalog_response)
            catalog_response.raise_for_status()
            catalog_payload = catalog_response.json()
            catalog_entries = _material_registry_catalog_entries(catalog_payload)
        except httpx.HTTPError as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}:
                raise CatalogAccessDenied(exc.response.status_code) from exc
            raise RuntimeError("Material registry catalog request failed") from exc
        except ValueError as exc:
            raise ValueError("Material registry catalog response is invalid") from exc

    remote_has_pagination = (
        isinstance(catalog_payload, dict)
        and (
            "total_count" in catalog_payload
            or "offset" in catalog_payload
            or "limit" in catalog_payload
        )
    )
    source_scope = catalog_source_scope(normalized_registry_url, normalized_channels, auth_token)
    if remote_has_pagination:
        paged_entries = catalog_entries
        total_count = int(catalog_payload.get("total_count") or len(catalog_entries))
        response_offset = int(catalog_payload.get("offset", normalized_offset))
        response_limit = (
            None
            if catalog_payload.get("limit") is None
            else int(catalog_payload.get("limit"))
        )
        catalog = {
            "source_scope": source_scope,
            "cached": catalog_response.headers.get("x-lumina-catalog-cached") == "true",
            "fetched_at": catalog_response.headers.get("x-lumina-catalog-fetched-at"),
            "schema_version": str(
                catalog_payload.get("schema_version")
                if isinstance(catalog_payload, dict)
                else "1.0"
            )
            or "1.0",
            "channels": normalized_channels,
            "count": len(paged_entries),
            "total_count": total_count,
            "offset": response_offset,
            "limit": response_limit,
            "materials": paged_entries,
        }
        if use_cache and (normalized_limit is not None or normalized_offset or total_count == len(paged_entries)):
            _store_material_registry_remote_catalog_cache(
                registry_url=normalized_registry_url,
                channels=normalized_channels,
                token=auth_token,
                transport=transport,
                limit=normalized_limit,
                offset=normalized_offset,
                query=normalized_query,
                payload=catalog,
            )
        return material_files._json_clone(catalog)

    full_catalog = {
        "source_scope": source_scope,
        "cached": catalog_response.headers.get("x-lumina-catalog-cached") == "true",
        "fetched_at": catalog_response.headers.get("x-lumina-catalog-fetched-at"),
        "schema_version": str(
            catalog_payload.get("schema_version")
            if isinstance(catalog_payload, dict)
            else "1.0"
        )
        or "1.0",
        "channels": normalized_channels,
        "count": len(catalog_entries),
        "total_count": len(catalog_entries),
        "offset": 0,
        "limit": None,
        "materials": catalog_entries,
    }
    filtered_full_catalog = _filter_material_registry_catalog(
        full_catalog,
        query=normalized_query,
    )
    if use_cache:
        _store_material_registry_remote_catalog_cache(
            registry_url=normalized_registry_url,
            channels=normalized_channels,
            token=auth_token,
            transport=transport,
            limit=None,
            offset=0,
            query=normalized_query,
            payload=filtered_full_catalog,
        )
    return _page_material_registry_catalog(
        filtered_full_catalog,
        limit=normalized_limit,
        offset=normalized_offset,
    )


def install_material_registry_package(
    *,
    package_url: str,
    package_sha256: str,
    material_id: str,
    revision_id: str,
    registry_url: str | None = None,
    token: str | None = None,
    materials_dir: str | None = None,
    timeout_s: float | None = None,
    transport: Any = None,
    display: dict[str, Any] | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    """Install one selected Registry package into the local material library.
    将用户选择的单个 Registry 耗材包安装到本地耗材库。
    """
    from . import material_library

    import httpx

    normalized_registry_url = _normalize_material_registry_url(registry_url)
    material_id = str(material_id or "").strip()
    revision_id = str(revision_id or "").strip()
    if not material_id or not revision_id:
        raise ValueError("Material registry package identity is required")
    resolved_package_url = _material_registry_package_url(
        normalized_registry_url,
        package_url,
    )
    expected_package_sha256 = _sha256_hex_from_catalog(package_sha256)
    auth_token = str(
        token
        if token is not None
        else registry_read_token("MATERIAL", normalized_registry_url)
    ).strip()
    if timeout_s is None:
        raw_timeout = os.environ.get("LUMINA_MATERIAL_REGISTRY_TIMEOUT_S", "30")
        try:
            timeout_s = float(raw_timeout)
        except ValueError:
            timeout_s = 30.0
    target_root = Path(materials_dir or material_files.MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": "LuminaStudioMaterialSync/1"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    client_kwargs: dict[str, Any] = {
        "timeout": float(timeout_s),
        "follow_redirects": True,
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    with material_sync._MaterialSyncRefreshFileLock(target_root):
        with httpx.Client(**client_kwargs) as client:
            try:
                temp_package_path = _download_material_registry_package_to_tempfile(
                    client=client,
                    package_url=resolved_package_url,
                    headers=headers,
                    expected_package_sha256=expected_package_sha256,
                    identity_label=f"{material_id}/{revision_id}",
                    registry_url=normalized_registry_url,
                )
            except httpx.HTTPError as exc:
                raise RuntimeError("Material registry package request failed") from exc
        try:
            import_result = material_library.import_saved_stage_a_material_archives(
                archive_path=str(temp_package_path),
                materials_dir=str(target_root),
                selected_material_id=material_id,
                selected_revision_id=revision_id,
                selected_display=display,
                selected_channel=channel,
            )
        finally:
            try:
                temp_package_path.unlink()
            except OSError:
                pass

    return {
        "registry_url": normalized_registry_url,
        "material_id": material_id,
        "revision_id": revision_id,
        "installed_count": len(import_result.imported_materials),
        "installed_materials": import_result.imported_materials,
    }


def refresh_material_sync_from_registry(
    *,
    registry_url: str | None = None,
    channels: Sequence[str] | None = None,
    token: str | None = None,
    materials_dir: str | None = None,
    timeout_s: float | None = None,
    transport: Any = None,
) -> dict[str, Any]:
    """Pull read-only material package revisions from a configured Registry.
    从配置的 Registry 只读拉取耗材包 revision 并安装到本地库。

    The Registry is only a download source in this MVP: no publish/upload
    capability is exposed here, so ordinary clients remain read-only.
    MVP 阶段该 Registry 只作为下载源；这里不提供发布/上传能力，普通客户端保持只读。
    """
    from . import material_library

    import httpx

    normalized_registry_url = _normalize_material_registry_url(registry_url)
    normalized_channels = _normalize_material_registry_channels(channels, registry_url=normalized_registry_url)
    auth_token = str(
        token
        if token is not None
        else registry_read_token("MATERIAL", normalized_registry_url)
    ).strip()
    if timeout_s is None:
        raw_timeout = os.environ.get("LUMINA_MATERIAL_REGISTRY_TIMEOUT_S", "30")
        try:
            timeout_s = float(raw_timeout)
        except ValueError:
            timeout_s = 30.0
    target_root = Path(materials_dir or material_files.MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)
    with material_sync._MaterialSyncRefreshFileLock(target_root):
        headers = {"User-Agent": "LuminaStudioMaterialSync/1"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        pre_request_state_hash = material_sync._material_sync_local_state_descriptor(target_root)
        sync_index = material_sync._load_material_sync_index(target_root)
        stored_validator = material_sync._material_sync_catalog_validator(
            index=sync_index,
            registry_url=normalized_registry_url,
            channels=normalized_channels,
        )
        conditional_etag = (
            str(stored_validator["etag"])
            if stored_validator is not None
            and stored_validator["local_state_hash"] == pre_request_state_hash
            else None
        )
        client_kwargs: dict[str, Any] = {
            "timeout": float(timeout_s),
            "follow_redirects": True,
        }
        if transport is not None:
            client_kwargs["transport"] = transport

        with httpx.Client(**client_kwargs) as client:
            try:
                catalog_response = _request_material_registry_refresh_catalog(
                    client=client,
                    registry_url=normalized_registry_url,
                    channels=normalized_channels,
                    headers=headers,
                    etag=conditional_etag,
                )
                if int(catalog_response.status_code) == 304:
                    if conditional_etag is None or stored_validator is None:
                        raise ValueError(
                            "Material registry returned 304 without a usable validator"
                        )
                    post_response_state_hash = material_sync._material_sync_local_state_descriptor(
                        target_root
                    )
                    if post_response_state_hash == pre_request_state_hash:
                        response_etag = material_sync._normalize_material_registry_etag(
                            catalog_response.headers.get("etag")
                        )
                        checked_count = int(stored_validator["checked_count"])
                        registry_state = (
                            sync_index.get("registries", {}).get(
                                normalized_registry_url
                            )
                            if isinstance(sync_index.get("registries"), dict)
                            else None
                        )
                        cursor = (
                            registry_state.get("last_cursor")
                            if isinstance(registry_state, dict)
                            and registry_state.get("channels")
                            == normalized_channels
                            else None
                        )
                        material_sync._record_material_registry_refresh(
                            target_root=target_root,
                            registry_url=normalized_registry_url,
                            channels=normalized_channels,
                            cursor=cursor,
                            checked_count=checked_count,
                            installed_count=0,
                            skipped_count=checked_count,
                            failed_count=0,
                            catalog_validator={
                                "etag": response_etag or conditional_etag,
                                "local_state_hash": pre_request_state_hash,
                                "checked_count": checked_count,
                            },
                        )
                        return {
                            "registry_url": normalized_registry_url,
                            "channels": normalized_channels,
                            "checked_count": checked_count,
                            "installed_count": 0,
                            "skipped_count": checked_count,
                            "failed_count": 0,
                            "installed_materials": [],
                            "failures": [],
                            "catalog_not_modified": True,
                        }

                    catalog_response = _request_material_registry_refresh_catalog(
                        client=client,
                        registry_url=normalized_registry_url,
                        channels=normalized_channels,
                        headers=headers,
                        etag=None,
                    )
                    if int(catalog_response.status_code) == 304:
                        raise ValueError(
                            "Material registry returned 304 to an unconditional request"
                        )

                catalog_payload = catalog_response.json()
                catalog_entries = _material_registry_catalog_entries(catalog_payload)
                catalog_etag = material_sync._normalize_material_registry_etag(
                    catalog_response.headers.get("etag")
                )
            except httpx.HTTPError as exc:
                raise RuntimeError("Material registry catalog request failed") from exc
            except ValueError as exc:
                raise ValueError("Material registry catalog response is invalid") from exc

            revisions_by_material: dict[str, set[str]] = {}
            for entry in catalog_entries:
                material_id = str(entry.get("material_id") or "").strip()
                revision_id = str(entry.get("revision_id") or "").strip()
                if material_id and revision_id:
                    revisions_by_material.setdefault(material_id, set()).add(revision_id)
            ambiguous_material_ids = {
                material_id
                for material_id, revision_ids in revisions_by_material.items()
                if len(revision_ids) > 1
            }
            material_ids_by_signature: dict[tuple[str, str], set[str]] = {}
            for entry in catalog_entries:
                material_id = str(entry.get("material_id") or "").strip()
                revision_id = str(entry.get("revision_id") or "").strip()
                signature = material_sync._material_sync_signature(entry)
                if material_id and revision_id and signature is not None:
                    material_ids_by_signature.setdefault(signature, set()).add(
                        material_id
                    )
            ambiguous_catalog_signatures = {
                signature
                for signature, material_ids in material_ids_by_signature.items()
                if len(material_ids) > 1
            }
            local_paths_by_signature = material_sync._local_material_paths_by_sync_signature(target_root)
            installed_index = sync_index.get("installed")
            unlinked_material_ids = {
                material_id for material_id, row in installed_index.items()
                if isinstance(row, dict) and material_sync.catalog_material_source(row) is None
            } if isinstance(installed_index, dict) else set()

            installed_materials: list[dict[str, Any]] = []
            existing_catalog_matches: list[tuple[dict[str, Any], Path]] = []
            failures: list[dict[str, str]] = []
            skipped_count = 0
            for entry in catalog_entries:
                material_id = str(entry.get("material_id") or "").strip()
                revision_id = str(entry.get("revision_id") or "").strip()
                package_url = str(entry.get("package_url") or "").strip()
                try:
                    content_hash = str(entry.get("content_hash") or "").strip()
                    if not material_id or not revision_id or not content_hash:
                        raise ValueError(
                            "Material registry catalog entry is missing material identity"
                        )
                    entry_signature = material_sync._material_sync_signature(entry)
                    installed_path = material_sync._installed_material_bundle_revision_path(
                        target_root=target_root,
                        package={
                            "material_id": material_id,
                            "revision_id": revision_id,
                            "content_hash": content_hash,
                        },
                        include_revision_history=True,
                    )
                    if installed_path is not None:
                        if (
                            material_id in unlinked_material_ids
                            and material_id not in ambiguous_material_ids
                            and entry_signature not in ambiguous_catalog_signatures
                        ):
                            existing_catalog_matches.append((entry, installed_path))
                        skipped_count += 1
                        continue
                    if material_id in ambiguous_material_ids:
                        raise ValueError(
                            _MATERIAL_REGISTRY_AMBIGUOUS_REVISION_FAILURE_DETAIL
                        )
                    if (
                        entry_signature in ambiguous_catalog_signatures
                        and local_paths_by_signature.get(entry_signature)
                    ):
                        raise ValueError(
                            material_sync._MATERIAL_REGISTRY_AMBIGUOUS_LOCAL_MATCH_FAILURE_DETAIL
                        )

                    adopted_path = material_sync._adopt_existing_local_material_bundle_revision(
                        target_root=target_root,
                        package=entry,
                        local_paths_by_signature=local_paths_by_signature,
                    )
                    if adopted_path is not None:
                        skipped_count += 1
                        continue

                    resolved_package_url = _material_registry_package_url(
                        normalized_registry_url,
                        package_url,
                    )
                    expected_package_sha256 = _sha256_hex_from_catalog(
                        entry.get("package_sha256")
                    )
                    temp_package_path = _download_material_registry_package_to_tempfile(
                        client=client,
                        package_url=resolved_package_url,
                        headers=headers,
                        expected_package_sha256=expected_package_sha256,
                        identity_label=f"{material_id}/{revision_id}",
                        registry_url=normalized_registry_url,
                        channels=normalized_channels,
                    )
                    try:
                        import_result = material_library.import_saved_stage_a_material_archives(
                            archive_path=str(temp_package_path),
                            materials_dir=str(target_root),
                            selected_material_id=material_id,
                            selected_revision_id=revision_id,
                            selected_display=entry.get("display"),
                            selected_channel=entry.get("channel"),
                        )
                    finally:
                        try:
                            temp_package_path.unlink()
                        except OSError:
                            pass
                    installed_materials.extend(import_result.imported_materials)
                except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
                    public_error = _public_material_registry_refresh_failure_error(exc)
                    _log.warning(
                        "Material registry package refresh failed",
                        extra={
                            "event": "material_sync_package_refresh_failed",
                            "material_id": material_id,
                            "revision_id": revision_id,
                            "package_url": package_url,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        },
                    )
                    failures.append(
                        {
                            "material_id": material_id,
                            "revision_id": revision_id,
                            "package_url": package_url,
                            "error": public_error,
                        }
                    )

        material_sync._link_existing_catalog_revisions(target_root=target_root, matches=existing_catalog_matches)
        checked_count = len(catalog_entries)
        installed_count = len(installed_materials)
        failed_count = len(failures)
        cursor = (
            catalog_payload.get("cursor")
            if isinstance(catalog_payload, dict)
            else None
        )
        local_state_hash = material_sync._material_sync_local_state_descriptor(target_root)
        catalog_is_converged = (
            failed_count == 0
            and _material_registry_catalog_is_locally_converged(
                target_root=target_root,
                catalog_entries=catalog_entries,
            )
        )
        verified_state_hash = (
            material_sync._material_sync_local_state_descriptor(target_root)
            if catalog_is_converged
            else None
        )
        catalog_validator = (
            {
                "etag": catalog_etag,
                "local_state_hash": local_state_hash,
                "checked_count": checked_count,
            }
            if catalog_etag is not None
            and catalog_is_converged
            and verified_state_hash == local_state_hash
            else None
        )
        material_sync._record_material_registry_refresh(
            target_root=target_root,
            registry_url=normalized_registry_url,
            channels=normalized_channels,
            cursor=cursor,
            checked_count=checked_count,
            installed_count=installed_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            catalog_validator=catalog_validator,
        )
        return {
            "registry_url": normalized_registry_url,
            "channels": normalized_channels,
            "checked_count": checked_count,
            "installed_count": installed_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "installed_materials": installed_materials,
            "failures": failures,
            "catalog_not_modified": False,
        }
