"""Review levels for module backends from host-trusted records.

``official``: signed Registry marks the module official and the installed
package SHA-256 equals that Registry version (or it is the verified seed).
``reviewed``: a signed review attestation lists the exact module, version,
and package SHA-256. Attestations are published as a separate signed
``reviews-v1.json`` so v1 Registry indexes stay parseable by older hosts.
``unreviewed``: everything else, including local and GitHub packages.
A package signature or self-description never upgrades a level.

审核等级只来自宿主可信记录并绑定精确版本与包摘要。审核记录单独签名发布，保持
v1 目录对旧宿主可解析。包签名或包内自述都不会提升审核等级。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..errors import WorkshopRegistryError
from ..models import MODULE_ID_PATTERN, RegistryIndex, validate_semver
from ..registry_client import (
    MAX_SIGNATURE_METADATA_BYTES,
    RegistryFetchResponse,
    RegistryFetcher,
    _atomic_write,
    _default_fetch_bytes,
    _parse_json_object,
    _read_bounded,
    verify_registry_signature,
)
from .state import ReviewLevel


DEFAULT_REVIEWS_URL = (
    "https://lumina-layer-studio.github.io/"
    "Lumina-Workshop-Registry/reviews-v1.json"
)
DEFAULT_REVIEWS_SIGNATURE_URL = (
    "https://lumina-layer-studio.github.io/"
    "Lumina-Workshop-Registry/reviews-v1.sig"
)
MAX_REVIEWS_BYTES = 2 * 1024 * 1024


class _ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=False)


class ReviewAttestation(_ReviewModel):
    module_id: str = Field(alias="moduleId", min_length=3, max_length=128)
    version: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(alias="manifestSha256", pattern=r"^[0-9a-f]{64}$")
    scope: str = Field(pattern=r"^backend-code$")
    reviewed_at: str = Field(alias="reviewedAt", pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("module_id")
    @classmethod
    def module_id_is_safe(cls, value: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("moduleId is invalid")
        return value

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        return validate_semver(value)


class ReviewAttestationIndex(_ReviewModel):
    schema_version: int = Field(alias="schemaVersion")
    generated_at: datetime = Field(alias="generatedAt")
    reviews: tuple[ReviewAttestation, ...] = Field(max_length=20_000)

    @field_validator("schema_version")
    @classmethod
    def schema_is_supported(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported review attestation schema")
        return value


def parse_review_index(payload: bytes) -> ReviewAttestationIndex:
    if len(payload) > MAX_REVIEWS_BYTES:
        raise WorkshopRegistryError("review attestations exceed size limit")
    raw = _parse_json_object(payload, label="Review attestations")
    try:
        return ReviewAttestationIndex.model_validate(raw)
    except ValidationError as exc:
        raise WorkshopRegistryError(f"Review attestations failed validation: {exc}") from exc


class ReviewAttestationClient:
    """Fetch and verify signed review attestations with cache fallback.

    获取并校验签名审核记录；远端不可用时回退到已验证缓存。
    """

    def __init__(
        self,
        *,
        keys: Mapping[str, Ed25519PublicKey],
        cache_dir: Path,
        fetch_bytes: RegistryFetcher | None = None,
        index_url: str = DEFAULT_REVIEWS_URL,
        signature_url: str = DEFAULT_REVIEWS_SIGNATURE_URL,
    ) -> None:
        self._keys = dict(keys)
        self._cache_dir = Path(cache_dir)
        self._fetch = fetch_bytes or _default_fetch_bytes
        self._index_url = index_url
        self._signature_url = signature_url

    @property
    def _cache_index(self) -> Path:
        return self._cache_dir / "reviews-v1.json"

    @property
    def _cache_signature(self) -> Path:
        return self._cache_dir / "reviews-v1.sig"

    def _load_cache(self) -> ReviewAttestationIndex | None:
        try:
            payload = _read_bounded(self._cache_index, MAX_REVIEWS_BYTES, label="Review cache")
            signature = _read_bounded(
                self._cache_signature,
                MAX_SIGNATURE_METADATA_BYTES,
                label="Review signature cache",
            )
            verify_registry_signature(payload, signature, self._keys)
            return parse_review_index(payload)
        except (WorkshopRegistryError, OSError):
            return None

    def refresh(self) -> ReviewAttestationIndex | None:
        """Return verified attestations, or ``None`` when none is available."""

        try:
            index_response = self._fetch(self._index_url, None)
            signature_response = self._fetch(self._signature_url, None)
            if not (
                isinstance(index_response, RegistryFetchResponse)
                and isinstance(signature_response, RegistryFetchResponse)
                and index_response.status_code == 200
                and signature_response.status_code == 200
            ):
                raise WorkshopRegistryError("review attestation request failed")
            verify_registry_signature(index_response.body, signature_response.body, self._keys)
            index = parse_review_index(index_response.body)
            _atomic_write(self._cache_index, index_response.body)
            _atomic_write(self._cache_signature, signature_response.body)
            return index
        except Exception:  # noqa: BLE001 - remote/cache trust boundary
            return self._load_cache()


@dataclass(frozen=True, slots=True)
class ReviewContext:
    """Host-trusted review evidence; ``None`` fields mean unavailable."""

    registry: RegistryIndex | None
    attestations: frozenset[tuple[str, str, str]] | None

    @classmethod
    def from_sources(
        cls,
        registry: RegistryIndex | None,
        reviews: ReviewAttestationIndex | None,
    ) -> "ReviewContext":
        return cls(
            registry=registry,
            attestations=(
                None
                if reviews is None
                else frozenset((item.module_id, item.version, item.sha256) for item in reviews.reviews)
            ),
        )


ReviewContextSource = Callable[[], ReviewContext]
LEVEL_RANK: dict[ReviewLevel, int] = {"unreviewed": 0, "reviewed": 1, "official": 2}


def registry_version_state(
    context: ReviewContext,
    module_id: str,
    version: str,
) -> tuple[str | None, str | None, bool]:
    """Return ``(state, sha256, module_official)`` for a Registry version."""

    if context.registry is None:
        return None, None, False
    module = next((item for item in context.registry.modules if item.module_id == module_id), None)
    if module is None:
        return None, None, False
    entry = next((item for item in module.versions if item.version == version), None)
    if entry is None:
        return None, None, module.official
    return entry.state, entry.sha256, module.official


def determine_review_level(
    *,
    source: str,
    official: bool,
    module_id: str,
    version: str,
    package_sha256: str,
    context: ReviewContext,
    recorded_level: ReviewLevel | None = None,
) -> ReviewLevel:
    """Compute the current review level for exact installed bytes.

    Missing evidence never upgrades a level; it only keeps an earlier
    recorded level when the trusted source is temporarily unavailable.
    """

    if source == "seed":
        return "official" if official else "unreviewed"
    if source != "registry":
        return "unreviewed"
    state, registry_sha, module_official = registry_version_state(context, module_id, version)
    if registry_sha is not None and registry_sha != package_sha256:
        return "unreviewed"
    if official:
        if registry_sha is not None and module_official:
            return "official"
        if context.registry is None or registry_sha is None:
            # Installed from a verified Registry; the current snapshot may
            # predate this version. Official identity is install-bound.
            return "official"
        return "unreviewed"
    if context.attestations is None or registry_sha is None:
        if recorded_level == "reviewed":
            return "reviewed"
        return "unreviewed"
    if (module_id, version, package_sha256) in context.attestations:
        return "reviewed"
    return "unreviewed"
