"""Signed Creative Workshop Registry verification and cache fallback."""

from __future__ import annotations

import base64
import binascii
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import WorkshopRegistryError
from .mirror import WorkshopMirror, WorkshopMirrorUnavailable
from .models import (
    RegistryIndex,
    RegistryRefreshResult,
    RegistryVersion,
    compare_semver,
    validate_semver,
)


DEFAULT_REGISTRY_INDEX_URL = (
    "https://lumina-layer-studio.github.io/"
    "Lumina-Workshop-Registry/registry-v1.json"
)
DEFAULT_REGISTRY_SIGNATURE_URL = (
    "https://lumina-layer-studio.github.io/"
    "Lumina-Workshop-Registry/registry-v1.sig"
)
MAX_REGISTRY_BYTES = 5 * 1024 * 1024
MAX_SIGNATURE_METADATA_BYTES = 16 * 1024
MAX_KEY_SET_BYTES = 64 * 1024
MAX_ETAG_BYTES = 1024
CONNECT_TIMEOUT_SECONDS = 15.0
INACTIVITY_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class RegistryFetchResponse:
    """One bounded HTTP-like response supplied to the Registry client."""

    status_code: int
    body: bytes
    etag: str | None


RegistryFetcher = Callable[[str, str | None], RegistryFetchResponse]


@dataclass(frozen=True, slots=True)
class _VerifiedCache:
    index: RegistryIndex
    payload: bytes
    signature: bytes
    etag: str | None


class _SignatureMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: str
    key_id: str = Field(alias="keyId", min_length=1, max_length=128)
    signature: str = Field(min_length=1, max_length=512)


class _TrustedKeyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key_id: str = Field(alias="keyId", min_length=1, max_length=128)
    algorithm: str
    public_key: str = Field(alias="publicKey", min_length=1, max_length=512)


class _TrustedKeySet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(alias="schemaVersion")
    keys: tuple[_TrustedKeyRecord, ...] = Field(max_length=32)


def _json_object_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise WorkshopRegistryError(
                f"duplicate JSON field in Registry data: {key!r}"
            )
        value[key] = item
    return value


def _parse_json_object(value: bytes, *, label: str) -> dict[str, Any]:
    try:
        text = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkshopRegistryError(
            f"{label} must be valid UTF-8"
        ) from exc
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_json_object_without_duplicates,
        )
    except WorkshopRegistryError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise WorkshopRegistryError(f"{label} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise WorkshopRegistryError(f"{label} root must be an object")
    return parsed


def parse_registry_index(payload: bytes) -> RegistryIndex:
    """Parse one bounded, strict Registry index.

    解析一份有界且严格的 Registry 索引。
    """

    if len(payload) > MAX_REGISTRY_BYTES:
        raise WorkshopRegistryError("Registry index exceeds size limit")
    raw = _parse_json_object(payload, label="Registry index")
    try:
        return RegistryIndex.model_validate(raw)
    except ValidationError as exc:
        raise WorkshopRegistryError(
            f"Registry index failed validation: {exc}"
        ) from exc


def verify_registry_signature(
    payload: bytes,
    signature_metadata: bytes,
    keys: Mapping[str, Ed25519PublicKey],
) -> str:
    """Verify exact Registry bytes and return the trusted key ID.

    校验 Registry 的精确字节并返回可信密钥 ID。
    """

    if len(payload) > MAX_REGISTRY_BYTES:
        raise WorkshopRegistryError("Registry index exceeds size limit")
    if len(signature_metadata) > MAX_SIGNATURE_METADATA_BYTES:
        raise WorkshopRegistryError(
            "Registry signature metadata exceeds size limit"
        )
    raw = _parse_json_object(
        signature_metadata,
        label="Registry signature metadata",
    )
    try:
        metadata = _SignatureMetadata.model_validate(raw)
    except ValidationError as exc:
        raise WorkshopRegistryError(
            f"Registry signature metadata failed validation: {exc}"
        ) from exc
    if metadata.algorithm != "Ed25519":
        raise WorkshopRegistryError(
            "Registry signature algorithm must be Ed25519"
        )

    public_key = keys.get(metadata.key_id)
    if public_key is None or not isinstance(public_key, Ed25519PublicKey):
        raise WorkshopRegistryError("Registry signature key is not trusted")
    try:
        signature = base64.b64decode(
            metadata.signature.encode("ascii"),
            validate=True,
        )
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise WorkshopRegistryError(
            "Registry signature is not canonical base64"
        ) from exc
    if (
        len(signature) != 64
        or base64.b64encode(signature).decode("ascii")
        != metadata.signature
    ):
        raise WorkshopRegistryError(
            "Registry signature must contain exactly 64 bytes"
        )
    try:
        public_key.verify(signature, payload)
    except InvalidSignature as exc:
        raise WorkshopRegistryError(
            "Registry signature verification failed"
        ) from exc
    return metadata.key_id


def load_registry_keys(
    path: str | Path,
) -> dict[str, Ed25519PublicKey]:
    """Load the app-owned, closed-schema Ed25519 verification key set.

    加载由应用持有且结构封闭的 Ed25519 验证公钥集合。
    """

    payload = _read_bounded(
        Path(path),
        MAX_KEY_SET_BYTES,
        label="Workshop Registry key set",
    )
    raw = _parse_json_object(payload, label="Workshop Registry key set")
    try:
        key_set = _TrustedKeySet.model_validate(raw)
    except ValidationError as exc:
        raise WorkshopRegistryError(
            f"Workshop Registry key set failed validation: {exc}"
        ) from exc
    if key_set.schema_version != 1:
        raise WorkshopRegistryError(
            "unsupported Workshop Registry key-set schema"
        )

    keys: dict[str, Ed25519PublicKey] = {}
    for record in key_set.keys:
        if record.algorithm != "Ed25519":
            raise WorkshopRegistryError(
                "Workshop Registry keys must use Ed25519"
            )
        if record.key_id in keys:
            raise WorkshopRegistryError(
                "Workshop Registry key IDs must be unique"
            )
        try:
            public_bytes = base64.b64decode(
                record.public_key.encode("ascii"),
                validate=True,
            )
        except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
            raise WorkshopRegistryError(
                "Workshop Registry public key is not canonical base64"
            ) from exc
        if (
            len(public_bytes) != 32
            or base64.b64encode(public_bytes).decode("ascii")
            != record.public_key
        ):
            raise WorkshopRegistryError(
                "Workshop Registry Ed25519 public key must be 32 bytes"
            )
        try:
            keys[record.key_id] = Ed25519PublicKey.from_public_bytes(
                public_bytes
            )
        except ValueError as exc:
            raise WorkshopRegistryError(
                "Workshop Registry Ed25519 public key is invalid"
            ) from exc
    return keys


def _validate_registry_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise WorkshopRegistryError(
            "Registry endpoints must be credential-free HTTPS URLs"
        )
    return url


def _response_body_limit(url: str) -> int:
    if url.endswith(".sig"):
        return MAX_SIGNATURE_METADATA_BYTES
    return MAX_REGISTRY_BYTES


def _default_fetch_bytes(
    url: str,
    etag: str | None,
) -> RegistryFetchResponse:
    headers = {
        "Accept": "application/json",
        "User-Agent": "Lumina-Studio-Workshop/1",
    }
    if etag:
        headers["If-None-Match"] = etag
    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT_SECONDS,
        read=INACTIVITY_TIMEOUT_SECONDS,
        write=INACTIVITY_TIMEOUT_SECONDS,
        pool=CONNECT_TIMEOUT_SECONDS,
    )
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        with client.stream("GET", url, headers=headers) as response:
            if response.status_code == 304:
                return RegistryFetchResponse(
                    status_code=304,
                    body=b"",
                    etag=response.headers.get("ETag") or etag,
                )
            if response.status_code != 200:
                raise WorkshopRegistryError(
                    "Registry request failed with status "
                    f"{response.status_code}"
                )
            return RegistryFetchResponse(
                status_code=200,
                body=_read_registry_response(response, _response_body_limit(url)),
                etag=response.headers.get("ETag"),
            )


def _read_registry_response(response: httpx.Response, maximum: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise WorkshopRegistryError("Registry response has invalid Content-Length") from exc
        if declared_length < 0 or declared_length > maximum:
            raise WorkshopRegistryError("Registry response exceeds size limit")
    chunks: list[bytes] = []
    received = 0
    for chunk in response.iter_bytes():
        received += len(chunk)
        if received > maximum:
            raise WorkshopRegistryError("Registry response exceeds size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch_mirror_bytes(
    mirror: WorkshopMirror, asset_name: str, _etag: str | None,
) -> RegistryFetchResponse:
    with mirror.stream(asset_name, accept="application/json") as response:
        body = _read_registry_response(response, _response_body_limit(asset_name))
    # The next upstream refresh may only send ETags issued by the upstream.
    return RegistryFetchResponse(status_code=200, body=body, etag=None)


def _clean_etag(value: str | None) -> str | None:
    if value is None or not value:
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WorkshopRegistryError("Registry ETag is invalid") from exc
    if (
        len(encoded) > MAX_ETAG_BYTES
        or any(character in value for character in ("\r", "\n", "\x00"))
    ):
        raise WorkshopRegistryError("Registry ETag is invalid")
    return value


def _read_bounded(path: Path, maximum: int, *, label: str) -> bytes:
    try:
        if path.stat().st_size > maximum:
            raise WorkshopRegistryError(f"{label} exceeds size limit")
        return path.read_bytes()
    except WorkshopRegistryError:
        raise
    except OSError as exc:
        raise WorkshopRegistryError(f"{label} is not readable") from exc


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _utc_now_text() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_verified_at(value: str) -> None:
    normalized = value.strip()
    if not normalized.endswith("Z"):
        raise WorkshopRegistryError(
            "Registry cache verification timestamp is invalid"
        )
    try:
        parsed = datetime.fromisoformat(
            normalized.removesuffix("Z") + "+00:00"
        )
    except ValueError as exc:
        raise WorkshopRegistryError(
            "Registry cache verification timestamp is invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise WorkshopRegistryError(
            "Registry cache verification timestamp is invalid"
        )


class RegistryClient:
    """Refresh one signed Registry while preserving trusted fallback state.

    刷新签名 Registry，并保留可信的回退状态。
    """

    def __init__(
        self,
        *,
        keys: Mapping[str, Ed25519PublicKey],
        cache_dir: str | Path,
        snapshot_path: str | Path,
        fetch_bytes: RegistryFetcher | None = None,
        index_url: str = DEFAULT_REGISTRY_INDEX_URL,
        signature_url: str = DEFAULT_REGISTRY_SIGNATURE_URL,
    ) -> None:
        self._keys = dict(keys)
        self._cache_dir = Path(cache_dir)
        self._snapshot_path = Path(snapshot_path)
        self._fetch_bytes = fetch_bytes or _default_fetch_bytes
        self._mirror = WorkshopMirror.from_environment() if fetch_bytes is None else None
        self._index_url = _validate_registry_url(index_url)
        self._signature_url = _validate_registry_url(signature_url)
        self.last_error: str | None = None

    @property
    def _index_cache_path(self) -> Path:
        return self._cache_dir / "registry-v1.json"

    @property
    def _signature_cache_path(self) -> Path:
        return self._cache_dir / "registry-v1.sig"

    @property
    def _etag_cache_path(self) -> Path:
        return self._cache_dir / "registry-v1.etag"

    @property
    def _verified_at_cache_path(self) -> Path:
        return self._cache_dir / "registry-v1.verified-at"

    def _load_verified_cache(self) -> _VerifiedCache | None:
        try:
            payload = _read_bounded(
                self._index_cache_path,
                MAX_REGISTRY_BYTES,
                label="Registry cache",
            )
            signature = _read_bounded(
                self._signature_cache_path,
                MAX_SIGNATURE_METADATA_BYTES,
                label="Registry signature cache",
            )
            verify_registry_signature(payload, signature, self._keys)
            index = parse_registry_index(payload)
            verified_at = _read_bounded(
                self._verified_at_cache_path,
                128,
                label="Registry verification timestamp",
            ).decode("utf-8", errors="strict")
            _parse_verified_at(verified_at)
            etag_text = _read_bounded(
                self._etag_cache_path,
                MAX_ETAG_BYTES,
                label="Registry ETag cache",
            ).decode("utf-8", errors="strict")
            etag = _clean_etag(etag_text)
            return _VerifiedCache(
                index=index,
                payload=payload,
                signature=signature,
                etag=etag,
            )
        except (WorkshopRegistryError, OSError, UnicodeDecodeError):
            return None

    def _write_verified_cache(
        self,
        *,
        payload: bytes,
        signature: bytes,
        etag: str | None,
    ) -> None:
        clean_etag = _clean_etag(etag)
        _atomic_write(self._index_cache_path, payload)
        _atomic_write(self._signature_cache_path, signature)
        _atomic_write(
            self._etag_cache_path,
            (clean_etag or "").encode("utf-8"),
        )
        _atomic_write(
            self._verified_at_cache_path,
            _utc_now_text().encode("utf-8"),
        )

    def _load_snapshot(self) -> RegistryIndex:
        payload = _read_bounded(
            self._snapshot_path,
            MAX_REGISTRY_BYTES,
            label="bundled Registry snapshot",
        )
        return parse_registry_index(payload)

    def _refresh_from(
        self,
        fetch_bytes: RegistryFetcher,
        index_url: str,
        signature_url: str,
        cache: _VerifiedCache | None,
    ) -> RegistryRefreshResult:
        index_response = fetch_bytes(index_url, cache.etag if cache is not None else None)
        if not isinstance(index_response, RegistryFetchResponse):
            raise WorkshopRegistryError("Registry fetcher returned an invalid response")
        if index_response.status_code == 304:
            if cache is None:
                raise WorkshopRegistryError("Registry returned 304 without a verified cache")
            return RegistryRefreshResult(source="cache", verified=True, index=cache.index)
        if index_response.status_code != 200:
            raise WorkshopRegistryError("Registry index request did not return 200")
        if len(index_response.body) > MAX_REGISTRY_BYTES:
            raise WorkshopRegistryError("Registry index exceeds size limit")

        signature_response = fetch_bytes(signature_url, None)
        if (
            not isinstance(signature_response, RegistryFetchResponse)
            or signature_response.status_code != 200
        ):
            raise WorkshopRegistryError("Registry signature request did not return 200")
        if len(signature_response.body) > MAX_SIGNATURE_METADATA_BYTES:
            raise WorkshopRegistryError("Registry signature metadata exceeds size limit")

        verify_registry_signature(index_response.body, signature_response.body, self._keys)
        index = parse_registry_index(index_response.body)
        self._write_verified_cache(
            payload=index_response.body,
            signature=signature_response.body,
            etag=index_response.etag,
        )
        return RegistryRefreshResult(source="remote", verified=True, index=index)

    def refresh(self) -> RegistryRefreshResult:
        """Fetch, verify, cache, and select the safest available index.

        获取、校验并缓存索引，然后选择最安全的可用版本。
        """

        cache = self._load_verified_cache()
        self.last_error = None
        try:
            if self._mirror is not None:
                try:
                    return self._refresh_from(
                        partial(_fetch_mirror_bytes, self._mirror),
                        "registry-v1.json", "registry-v1.sig", None,
                    )
                except WorkshopMirrorUnavailable:
                    # Never verify a mirror index against the upstream signature or vice versa.
                    pass
            return self._refresh_from(
                self._fetch_bytes, self._index_url, self._signature_url, cache,
            )
        except Exception as exc:
            # This is the explicit remote/cache boundary. Any malformed or
            # unavailable remote state must converge on the last verified
            # cache or the app-owned snapshot.
            self.last_error = f"{type(exc).__name__}: {exc}"[:500]
            if cache is not None:
                return RegistryRefreshResult(
                    source="cache",
                    verified=True,
                    index=cache.index,
                )
            try:
                snapshot = self._load_snapshot()
            except WorkshopRegistryError as snapshot_error:
                raise WorkshopRegistryError(
                    "no trusted Workshop Registry is available"
                ) from snapshot_error
            return RegistryRefreshResult(
                source="snapshot",
                verified=True,
                index=snapshot,
            )


def _is_compatible(
    version: RegistryVersion,
    *,
    lumina_version: str,
    workshop_api_version: str,
) -> bool:
    return (
        compare_semver(
            lumina_version,
            version.lumina_version.minimum,
        )
        >= 0
        and compare_semver(
            workshop_api_version,
            version.workshop_api.minimum,
        )
        >= 0
        and compare_semver(
            workshop_api_version,
            version.workshop_api.max_exclusive,
        )
        < 0
    )


def select_install_candidate(
    index: RegistryIndex,
    module_id: str,
    *,
    lumina_version: str,
    workshop_api_version: str,
    requested_version: str | None = None,
) -> RegistryVersion | None:
    """Select one compatible non-blocked version from a verified index.

    从已验证索引中选择一个兼容且未被阻止的版本。
    """

    validate_semver(lumina_version)
    validate_semver(workshop_api_version)
    if requested_version is not None:
        validate_semver(requested_version)

    module = next(
        (
            candidate
            for candidate in index.modules
            if candidate.module_id == module_id
        ),
        None,
    )
    if module is None:
        return None
    for version in reversed(module.versions):
        if version.state == "blocked":
            continue
        if (
            requested_version is not None
            and version.version != requested_version
        ):
            continue
        if requested_version is None and version.state != "active":
            continue
        if _is_compatible(
            version,
            lumina_version=lumina_version,
            workshop_api_version=workshop_api_version,
        ):
            return version
    return None
