"""Read the portable public catalog without querying a Registry or GitHub API.

Catalogs are small JSON indexes. Previews and immutable packages stay separate.
Static hosts never receive account credentials and redirects remain forbidden.
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import httpx

from core.registry_catalog_cache import CatalogSnapshot

MAX_JSON_BYTES = 8 * 1024 * 1024
PUBLIC_CHANNELS = {"official", "community"}


def read_document(
    client: httpx.Client, base: str, suffix: str, cache_dir: Path | None,
    *, refresh: bool = False, immutable: bool = False, expected_sha256: str | None = None,
) -> httpx.Response:
    """One bounded, anonymous conditional request; reuse a complete cached file."""
    from core.registry_transport import _public_client, _retryable, _valid_base

    if not _valid_base(base) or not _public_client(client, {}, ["official"]):
        raise ValueError("Public snapshots require an anonymous HTTP(S) connection")
    snapshot = CatalogSnapshot(cache_dir, base, suffix, []) if cache_dir else None
    cached = snapshot.response(offline=False) if snapshot else None
    if cached is not None:
        try:
            _validate_document(cached.json(), suffix, expected_sha256)
        except ValueError:
            snapshot.payload = None
            cached = None
    if cached is not None and not refresh:
        try:
            fetched = datetime.fromisoformat(cached.headers["x-lumina-catalog-fetched-at"])
            age = (datetime.now(timezone.utc) - fetched).total_seconds()
            if immutable or 0 <= age < 300:
                return cached
        except (ValueError, KeyError, TypeError):
            pass
    headers = {"If-None-Match": snapshot.etag} if snapshot and snapshot.etag else {}
    try:
        with client.stream("GET", base + suffix, headers=headers, follow_redirects=False) as response:
            if response.status_code == 304 and cached is not None:
                # Renew the local validation time while preserving the source validator.
                if snapshot.etag:
                    cached.headers["ETag"] = snapshot.etag
                snapshot.store(cached)
                return snapshot.response(offline=False)
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_JSON_BYTES:
                    raise ValueError("Public catalog document exceeds maximum size")
                chunks.append(chunk)
            result = httpx.Response(200, content=b"".join(chunks), request=response.request,
                                    headers={"ETag": response.headers["etag"]} if "etag" in response.headers else {})
        body = result.json()
        _validate_document(body, suffix, expected_sha256)
        if snapshot:
            snapshot.store(result)
            return snapshot.response(offline=False) or result
        return result
    except httpx.HTTPError as exc:
        if snapshot and _retryable(exc):
            offline = snapshot.response(offline=True)
            if offline is not None:
                return offline
        raise


def _validate_document(body: Any, suffix: str, expected_sha256: str | None) -> None:
    if not isinstance(body, dict) or body.get("schema_version") != 1:
        raise ValueError("Unsupported public catalog document")
    if suffix.endswith(("/catalog.json", "/activity.json")):
        key = "materials" if suffix == "/materials/catalog.json" else "items"
        rows = body.get(key)
        if not isinstance(rows, list) or len(rows) > 20_000 or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Invalid public catalog entries")
        if suffix.endswith("/activity.json"):
            for row in rows:
                if (not isinstance(row.get("resource_id"), str)
                        or any(type(row.get(key)) is not int or row[key] < 0 for key in ("likes", "saves", "downloads"))
                        or not isinstance(row.get("revisions"), list)
                        or any(not isinstance(revision, dict) or not all(isinstance(revision.get(key), str)
                               for key in ("revision_id", "content_hash")) for revision in row["revisions"])):
                    raise ValueError("Invalid public activity snapshot")
    if expected_sha256:
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(canonical).hexdigest() != expected_sha256:
            raise ValueError("Public LUT preview checksum mismatch")


def fetch_static_catalog(
    *, client: httpx.Client, primary: str, family: str, channels: Sequence[str],
    params: Any, cache_dir: Path | None, refresh: bool = False,
) -> httpx.Response:
    """Adapt a complete static index to the existing paged catalog contract."""
    if not set(channels) <= PUBLIC_CHANNELS:
        raise ValueError("Public snapshots only contain public channels")
    kind, key = ("materials", "materials") if family == "MATERIAL" else ("luts", "items")
    response = read_document(client, primary, f"/{kind}/catalog.json", cache_dir, refresh=refresh)
    body = response.json()
    entries = body.get(key)
    values = httpx.QueryParams(params)
    entries = [row for row in entries if row.get("channel") in channels]
    query = " ".join(values.get("q", "").casefold().split())
    if query:
        entries = [row for row in entries if all(word in json.dumps(
            {name: row.get(name) for name in ("material_id", "lut_id", "display", "compatibility")},
            ensure_ascii=False,
        ).casefold() for word in query.split())]
    preview_ids = set(values.get_list("preview_id"))
    if preview_ids:
        if len(preview_ids) > 24:
            raise ValueError("A public preview request supports at most 24 LUTs")

        def load_preview(row: dict[str, Any]) -> dict[str, Any] | None:
            digest = row.get("preview_sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                return None
            preview_cache = cache_dir / "public-previews" if cache_dir else None
            preview = read_document(client, primary, f"/luts/previews/{digest}.json", preview_cache,
                                    immutable=True, expected_sha256=digest)
            artwork = preview.json()
            if any(artwork.get(name) != row.get(name) for name in ("lut_id", "revision_id", "content_hash")):
                raise ValueError("Public LUT preview identity mismatch")
            return artwork

        visible = [row for row in entries if row.get("lut_id") in preview_ids]
        # httpx.Client is shared across threads; cap concurrency independently of
        # grid width so a screenful of cards does not create a request burst.
        with ThreadPoolExecutor(max_workers=4) as pool:
            payload = {"previews": [item for item in pool.map(load_preview, visible) if item is not None]}
    else:
        start = max(0, int(values.get("offset", "0")))
        limit = int(values["limit"]) if "limit" in values else None
        page = entries[start:] if limit is None else entries[start:start + limit]
        payload = {key: page, "total": len(entries), "total_count": len(entries), "count": len(page),
                   "offset": start, "limit": limit, "schema_version": "1.0", "channels": list(channels)}
    payload.update(provider="github", snapshot_at=body.get("generated_at"))
    return httpx.Response(200, json=payload, request=response.request, headers=response.headers)


def snapshot_activity(
    *, client: httpx.Client, base: str, kind: str, ids: list[str], cache_dir: Path | None,
) -> dict[str, Any]:
    response = read_document(client, base, f"/{kind}/activity.json", cache_dir)
    payload = response.json()
    rows = payload.get("items")
    selected = []
    for row in rows:
        if not isinstance(row, dict) or row.get("resource_id") not in ids:
            continue
        selected.append({name: row[name] for name in ("resource_id", "likes", "saves", "downloads", "revisions")} | {
            "liked": False, "saved": False, "downloaded": False,
            "snapshot_at": payload.get("generated_at"), "stats_source": "snapshot",
        })
    return {"items": selected, "subject": None}
