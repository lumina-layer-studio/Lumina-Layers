"""Bounded anonymous catalog snapshots, scoped to one source and query."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_MAX_BYTES = 8 * 1024 * 1024
_MAX_ENTRIES = 32
_SCOPE_KEY = secrets.token_bytes(32)


def catalog_source_scope(source: str, channels: Sequence[str], token: str | None) -> str:
    """Opaque identity for pages served from the same source and credential scope."""
    data = json.dumps([source, sorted(channels), token or ""]).encode("utf-8")
    return hmac.digest(_SCOPE_KEY, data, "sha256").hex()


class CatalogAccessDenied(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"Registry catalog request failed with status {status_code}")
        self.status_code = status_code


class CatalogSnapshot:
    def __init__(self, directory: Path, source: str, suffix: str, params: Any) -> None:
        self.url = source + suffix
        key = json.dumps([self.url, params], sort_keys=True, ensure_ascii=False)
        self.path = directory / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")
        self.payload: dict[str, Any] | None = None
        try:
            if self.path.stat().st_size <= _MAX_BYTES:
                cached = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached.get("url") == self.url and isinstance(cached.get("body"), (dict, list)):
                    self.payload = cached
        except (OSError, ValueError):
            pass

    @property
    def etag(self) -> str | None:
        value = (self.payload or {}).get("etag")
        return value if isinstance(value, str) and len(value) <= 1024 and "\r" not in value and "\n" not in value else None

    def response(self, *, offline: bool) -> httpx.Response | None:
        if self.payload is None:
            return None
        return httpx.Response(200, json=self.payload["body"], request=httpx.Request("GET", self.url), headers={
            "x-lumina-catalog-cached": str(offline).lower(),
            "x-lumina-catalog-fetched-at": str(self.payload.get("fetched_at", "")),
        })

    def store(self, response: httpx.Response) -> None:
        if response.status_code != 200 or len(response.content) > _MAX_BYTES:
            return
        try:
            body = response.json()
            if not isinstance(body, (dict, list)):
                return
            self.payload = {"url": self.url, "etag": response.headers.get("etag"), "body": body,
                            "fetched_at": datetime.now(timezone.utc).isoformat()}
            serialized = json.dumps(self.payload, ensure_ascii=False)
            if len(serialized.encode("utf-8")) > _MAX_BYTES:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(serialized, encoding="utf-8")
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
            snapshots = sorted(self.path.parent.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
            for expired in snapshots[_MAX_ENTRIES:]:
                expired.unlink(missing_ok=True)
        except (OSError, ValueError):
            # Cache persistence cannot turn a usable response into a failure.
            return
