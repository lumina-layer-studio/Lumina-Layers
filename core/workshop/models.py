"""Immutable Creative Workshop package models."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .constants import (
    ALLOWED_PERMISSION_NAMES,
    BACKEND_CAPABILITY_NAMES,
    BACKEND_IDLE_TIMEOUT_MAX_SECONDS,
    BACKEND_IDLE_TIMEOUT_MIN_SECONDS,
    BACKEND_PACKAGE_PREFIX,
    BACKEND_PLATFORMS,
    BACKEND_PYTHON_VERSIONS,
    MAX_BACKEND_CAPABILITIES,
    MAX_BACKEND_MODEL_BYTES,
    MAX_BACKEND_MODELS,
    MAX_BACKEND_VARIANTS,
    WORKSHOP_BACKEND_API_VERSION,
    WORKSHOP_BACKEND_MANIFEST_VERSION,
    WORKSHOP_MANIFEST_VERSION,
)


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-"
    r"(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*"
    r")?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
MODULE_ID_PATTERN = re.compile(
    r"^[a-z0-9]+(?:[.-][a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)*$"
)


def validate_semver(value: str) -> str:
    """Return one exact SemVer string or raise a validation error.

    返回一个精确的 SemVer 字符串，否则抛出校验错误。
    """

    if SEMVER_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be valid SemVer")
    return value


class StrictFrozenModel(BaseModel):
    """Base for immutable manifest models with closed schemas."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=False,
    )


class LocalizedText(StrictFrozenModel):
    zh_cn: str = Field(alias="zh-CN", min_length=1, max_length=200)
    en_us: str = Field(alias="en-US", min_length=1, max_length=200)

    @field_validator("zh_cn", "en_us")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("localized text must not be blank")
        return normalized


class WorkshopApiRange(StrictFrozenModel):
    minimum: str = Field(alias="min")
    max_exclusive: str = Field(alias="maxExclusive")

    @field_validator("minimum", "max_exclusive")
    @classmethod
    def versions_are_semver(cls, value: str) -> str:
        return validate_semver(value)

    @model_validator(mode="after")
    def maximum_is_after_minimum(self) -> "WorkshopApiRange":
        if compare_semver(self.max_exclusive, self.minimum) <= 0:
            raise ValueError("Workshop API maxExclusive must exceed min")
        return self


class LuminaVersionRange(StrictFrozenModel):
    minimum: str = Field(alias="min")

    @field_validator("minimum")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        return validate_semver(value)


class WorkshopEntrypoints(StrictFrozenModel):
    ui: str

    @field_validator("ui")
    @classmethod
    def entry_is_fixed(cls, value: str) -> str:
        if value != "ui/index.html":
            raise ValueError("UI entrypoint must be ui/index.html")
        return value


class WorkshopPermission(StrictFrozenModel):
    name: str
    reason: str = Field(max_length=500)

    @field_validator("name")
    @classmethod
    def permission_is_known(cls, value: str) -> str:
        if value not in ALLOWED_PERMISSION_NAMES:
            raise ValueError(f"unknown permission: {value}")
        return value

    @field_validator("reason")
    @classmethod
    def reason_is_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("permission reason must not be blank")
        return normalized


class WorkshopProjectSnapshots(StrictFrozenModel):
    protocol: Literal[1]
    schemas: tuple[str, ...] = Field(min_length=1, max_length=32)

    @field_validator("schemas")
    @classmethod
    def schemas_are_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(not item or len(item) > 128 for item in value):
            raise ValueError("invalid project snapshot schemas")
        return value


class _WorkshopManifestBase(StrictFrozenModel):
    manifest_version: int = Field(alias="manifestVersion")
    id: str = Field(min_length=3, max_length=128)
    version: str
    name: LocalizedText
    description: LocalizedText
    publisher: str = Field(min_length=1, max_length=200)
    workshop_api: WorkshopApiRange = Field(alias="workshopApi")
    lumina_version: LuminaVersionRange = Field(alias="luminaVersion")
    entrypoints: WorkshopEntrypoints
    permissions: tuple[WorkshopPermission, ...] = Field(max_length=32)
    project_snapshots: WorkshopProjectSnapshots | None = Field(default=None, alias="projectSnapshots")

    @field_validator("id")
    @classmethod
    def module_id_is_safe(cls, value: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("module id must be lowercase reverse-domain style")
        return value

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        return validate_semver(value)

    @field_validator("publisher")
    @classmethod
    def publisher_is_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("publisher must not be blank")
        return normalized

    @model_validator(mode="after")
    def permissions_are_unique(self) -> "_WorkshopManifestBase":
        names = [permission.name for permission in self.permissions]
        if len(names) != len(set(names)):
            raise ValueError("manifest contains duplicate permission entries")
        if self.project_snapshots and "project.storage" not in names:
            raise ValueError("project snapshots require project.storage permission")
        return self


class WorkshopManifestV1(_WorkshopManifestBase):
    """Frontend-only module manifest."""

    @field_validator("manifest_version")
    @classmethod
    def manifest_version_is_supported(cls, value: int) -> int:
        if value != WORKSHOP_MANIFEST_VERSION:
            raise ValueError("unsupported manifest version")
        return value


_BACKEND_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_MODEL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE_FILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_BACKEND_PATH_PATTERN = re.compile(
    r"^backend/(?:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}/){0,8}"
    r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$"
)


_PYLOCK_NAME_PATTERN = re.compile(r"^pylock(?:\.[A-Za-z0-9_-]+)?\.toml$")


def _backend_path(value: str, *, suffix: str) -> str:
    if (
        not value.startswith(BACKEND_PACKAGE_PREFIX)
        or _BACKEND_PATH_PATTERN.fullmatch(value) is None
        or ".." in value.split("/")
        or not value.endswith(suffix)
    ):
        raise ValueError(f"backend path must be backend/...{suffix}")
    return value


def _backend_lock_path(value: str) -> str:
    _backend_path(value, suffix=".toml")
    if _PYLOCK_NAME_PATTERN.fullmatch(value.rsplit("/", 1)[-1]) is None:
        raise ValueError(
            "backend lock must be named pylock.toml or pylock.<name>.toml"
        )
    return value


def _https_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("URL must be credential-free HTTPS")
    return value


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class BackendCapability(StrictFrozenModel):
    """A declared, informational backend behavior shown before consent."""

    name: str
    reason: str = Field(max_length=500)

    @field_validator("name")
    @classmethod
    def capability_is_known(cls, value: str) -> str:
        if value not in BACKEND_CAPABILITY_NAMES:
            raise ValueError(f"unknown backend capability: {value}")
        return value

    @field_validator("reason")
    @classmethod
    def capability_reason_is_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("capability reason must not be blank")
        return normalized


class BackendModelFile(StrictFrozenModel):
    """One hash-pinned model file downloaded into the host content store."""

    id: str
    file_name: str = Field(alias="fileName")
    url: str = Field(max_length=2048)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(alias="bytes", gt=0, le=MAX_BACKEND_MODEL_BYTES)
    license: str = Field(min_length=1, max_length=200)

    @field_validator("id")
    @classmethod
    def model_id_is_safe(cls, value: str) -> str:
        if _MODEL_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("model id is invalid")
        return value

    @field_validator("file_name")
    @classmethod
    def file_name_is_one_safe_segment(cls, value: str) -> str:
        if (
            _SAFE_FILE_NAME_PATTERN.fullmatch(value) is None
            or value.endswith(".")
        ):
            raise ValueError("model fileName must be one safe file name")
        return value

    @field_validator("url")
    @classmethod
    def model_url_is_https(cls, value: str) -> str:
        return _https_url(value)


class BackendVariant(StrictFrozenModel):
    """An optional dependency variant, such as GPU acceleration."""

    id: str
    name: LocalizedText
    description: LocalizedText
    lock: str
    platforms: tuple[str, ...] = Field(min_length=1, max_length=8)

    @field_validator("id")
    @classmethod
    def variant_id_is_safe(cls, value: str) -> str:
        if _BACKEND_ID_PATTERN.fullmatch(value) is None or value == "cpu":
            raise ValueError("variant id is invalid or reserved")
        return value

    @field_validator("lock")
    @classmethod
    def variant_lock_is_backend_toml(cls, value: str) -> str:
        return _backend_lock_path(value)

    @field_validator("platforms")
    @classmethod
    def variant_platforms_are_known(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if any(platform not in BACKEND_PLATFORMS for platform in value):
            raise ValueError("variant declares an unknown platform")
        _unique(list(value), "variant platforms")
        return value


class BackendDeclaration(StrictFrozenModel):
    """Manifest v2 backend contract; the host never imports this code."""

    entry: str
    python: str
    lock: str
    platforms: tuple[str, ...] = Field(min_length=1, max_length=8)
    capabilities: tuple[BackendCapability, ...] = Field(
        default=(),
        max_length=MAX_BACKEND_CAPABILITIES,
    )
    models: tuple[BackendModelFile, ...] = Field(
        default=(),
        max_length=MAX_BACKEND_MODELS,
    )
    variants: tuple[BackendVariant, ...] = Field(
        default=(),
        max_length=MAX_BACKEND_VARIANTS,
    )
    idle_timeout_seconds: int | None = Field(
        default=None,
        alias="idleTimeoutSeconds",
        ge=BACKEND_IDLE_TIMEOUT_MIN_SECONDS,
        le=BACKEND_IDLE_TIMEOUT_MAX_SECONDS,
    )

    @field_validator("entry")
    @classmethod
    def entry_is_backend_python(cls, value: str) -> str:
        return _backend_path(value, suffix=".py")

    @field_validator("lock")
    @classmethod
    def lock_is_backend_toml(cls, value: str) -> str:
        return _backend_lock_path(value)

    @field_validator("python")
    @classmethod
    def python_is_supported(cls, value: str) -> str:
        if value not in BACKEND_PYTHON_VERSIONS:
            raise ValueError("backend Python version is not supported")
        return value

    @field_validator("platforms")
    @classmethod
    def platforms_are_known(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(platform not in BACKEND_PLATFORMS for platform in value):
            raise ValueError("backend declares an unknown platform")
        _unique(list(value), "backend platforms")
        return value

    @model_validator(mode="after")
    def references_are_consistent(self) -> "BackendDeclaration":
        _unique([item.name for item in self.capabilities], "capabilities")
        _unique([item.id for item in self.models], "model ids")
        _unique(
            [item.file_name.casefold() for item in self.models],
            "model file names",
        )
        _unique([item.id for item in self.variants], "variant ids")
        locks = [self.lock, *(variant.lock for variant in self.variants)]
        _unique(locks, "backend locks")
        for variant in self.variants:
            if not set(variant.platforms) <= set(self.platforms):
                raise ValueError(
                    "variant platforms must be backend platforms"
                )
        return self

    def referenced_files(self) -> tuple[str, ...]:
        """Return package files the declaration requires to exist."""

        return tuple(
            sorted(
                {
                    self.entry,
                    self.lock,
                    *(variant.lock for variant in self.variants),
                }
            )
        )


class WorkshopManifestV2(_WorkshopManifestBase):
    """Module manifest with a host-managed backend declaration."""

    backend: BackendDeclaration

    @field_validator("manifest_version")
    @classmethod
    def manifest_version_is_backend(cls, value: int) -> int:
        if value != WORKSHOP_BACKEND_MANIFEST_VERSION:
            raise ValueError("unsupported manifest version")
        return value

    @model_validator(mode="after")
    def backend_requires_backend_api(self) -> "WorkshopManifestV2":
        # Older hosts filter Registry candidates by workshopApi.min, so a
        # backend module must not claim compatibility with API 1.0.x hosts.
        if compare_semver(
            self.workshop_api.minimum,
            WORKSHOP_BACKEND_API_VERSION,
        ) < 0:
            raise ValueError(
                "backend modules require workshopApi.min >= "
                f"{WORKSHOP_BACKEND_API_VERSION}"
            )
        return self


WorkshopManifest = WorkshopManifestV1 | WorkshopManifestV2


def parse_workshop_manifest(raw: dict[str, Any]) -> WorkshopManifest:
    """Validate a manifest object against its declared closed schema.

    按清单声明的版本，使用对应的封闭结构校验清单对象。
    """

    version = raw.get("manifestVersion")
    if version == WORKSHOP_BACKEND_MANIFEST_VERSION:
        return WorkshopManifestV2.model_validate(raw)
    return WorkshopManifestV1.model_validate(raw)


def parse_workshop_manifest_json(text: str) -> WorkshopManifest:
    """Parse installed manifest JSON as v1 or v2.

    将已安装的清单 JSON 解析为 v1 或 v2 结构。
    """

    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("manifest root must be an object")
    return parse_workshop_manifest(raw)


def semver_sort_key(
    value: str,
) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
    """Return a SemVer precedence key that ignores build metadata.

    返回忽略构建元数据的 SemVer 优先级键。
    """

    validate_semver(value)
    without_build = value.split("+", 1)[0]
    core, separator, prerelease = without_build.partition("-")
    major, minor, patch = (int(part) for part in core.split("."))
    if not separator:
        return major, minor, patch, 1, ()
    identifiers: list[tuple[int, int | str]] = []
    for identifier in prerelease.split("."):
        if identifier.isdigit():
            identifiers.append((0, int(identifier)))
        else:
            identifiers.append((1, identifier))
    return major, minor, patch, 0, tuple(identifiers)


def compare_semver(left: str, right: str) -> int:
    """Compare two valid SemVer values by precedence.

    按优先级比较两个有效的 SemVer 值。
    """

    left_key = semver_sort_key(left)
    right_key = semver_sort_key(right)
    return (left_key > right_key) - (left_key < right_key)


class RegistryRevocation(StrictFrozenModel):
    reason_code: str = Field(
        alias="reasonCode",
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
        min_length=2,
        max_length=80,
    )
    severity: Literal["low", "medium", "high", "critical"]
    message: LocalizedText


class RegistryVersion(StrictFrozenModel):
    version: str
    release_tag: str = Field(alias="releaseTag", min_length=2, max_length=160)
    asset_name: str = Field(alias="assetName", min_length=1, max_length=240)
    download_url: str = Field(alias="downloadUrl", min_length=1, max_length=2048)
    asset_bytes: int = Field(
        alias="assetBytes",
        gt=0,
        le=100 * 1024 * 1024,
    )
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(
        alias="manifestSha256",
        pattern=r"^[0-9a-f]{64}$",
    )
    workshop_api: WorkshopApiRange = Field(alias="workshopApi")
    lumina_version: LuminaVersionRange = Field(alias="luminaVersion")
    permissions: tuple[WorkshopPermission, ...] = Field(max_length=32)
    state: Literal["active", "deprecated", "blocked"]
    revocation: RegistryRevocation | None

    @field_validator("version")
    @classmethod
    def registry_version_is_semver(cls, value: str) -> str:
        return validate_semver(value)

    @field_validator("download_url")
    @classmethod
    def download_is_an_exact_github_https_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("downloadUrl must be an HTTPS GitHub URL")
        return value

    @model_validator(mode="after")
    def identity_and_revocation_are_consistent(self) -> "RegistryVersion":
        if self.release_tag != f"v{self.version}":
            raise ValueError("releaseTag must equal v<version>")
        if self.state == "blocked" and self.revocation is None:
            raise ValueError("blocked version requires revocation")
        if self.state != "blocked" and self.revocation is not None:
            raise ValueError("only blocked versions may carry revocation")
        permission_names = [
            permission.name for permission in self.permissions
        ]
        if len(permission_names) != len(set(permission_names)):
            raise ValueError("Registry version has duplicate permissions")
        return self


class RegistryModule(StrictFrozenModel):
    module_id: str = Field(alias="moduleId", min_length=3, max_length=128)
    repository: str = Field(min_length=1, max_length=500)
    official: bool
    publisher: str = Field(min_length=1, max_length=200)
    name: LocalizedText
    description: LocalizedText
    versions: tuple[RegistryVersion, ...] = Field(
        min_length=1,
        max_length=100,
    )

    @field_validator("module_id")
    @classmethod
    def registry_module_id_is_safe(cls, value: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("moduleId must be lowercase reverse-domain style")
        return value

    @field_validator("repository")
    @classmethod
    def repository_is_github_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        parts = tuple(part for part in parsed.path.split("/") if part)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or value.endswith("/")
            or len(parts) != 2
            or parts[1].endswith(".git")
        ):
            raise ValueError(
                "repository must be an exact HTTPS GitHub repository URL"
            )
        return value

    @field_validator("publisher")
    @classmethod
    def registry_publisher_is_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("publisher must not be blank")
        return normalized

    @model_validator(mode="after")
    def versions_match_module_identity(self) -> "RegistryModule":
        previous: str | None = None
        for version in self.versions:
            if previous is not None and compare_semver(
                version.version,
                previous,
            ) <= 0:
                raise ValueError(
                    "duplicate module version or versions not increasing"
                )
            previous = version.version
            expected_asset = (
                f"{self.module_id}-{version.version}.lumina-workshop"
            )
            if version.asset_name != expected_asset:
                raise ValueError(
                    "assetName must match moduleId and version"
                )
            expected_download = (
                f"{self.repository}/releases/download/"
                f"{version.release_tag}/{version.asset_name}"
            )
            if version.download_url != expected_download:
                raise ValueError(
                    "downloadUrl must match repository release identity"
                )
        return self


class RegistryIndex(StrictFrozenModel):
    schema_version: int = Field(alias="schemaVersion")
    generated_at: datetime = Field(alias="generatedAt")
    modules: tuple[RegistryModule, ...] = Field(max_length=5_000)

    @field_validator("schema_version")
    @classmethod
    def registry_schema_is_supported(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported Registry schema version")
        return value

    @field_validator("generated_at")
    @classmethod
    def generated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generatedAt must include a timezone")
        return value

    @model_validator(mode="after")
    def module_ids_are_unique(self) -> "RegistryIndex":
        module_ids = [module.module_id for module in self.modules]
        if len(module_ids) != len(set(module_ids)):
            raise ValueError("duplicate module id in Registry")
        return self


class RegistryRefreshResult(StrictFrozenModel):
    source: Literal["remote", "cache", "snapshot"]
    verified: bool
    index: RegistryIndex


class InspectedWorkshopPackage(StrictFrozenModel):
    archive_path: Path
    manifest: WorkshopManifestV1 | WorkshopManifestV2
    entry_html: str
    compressed_bytes: int = Field(ge=0)
    unpacked_bytes: int = Field(ge=0)
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    member_names: tuple[str, ...]


class PackageInspectionSummary(StrictFrozenModel):
    module_id: str = Field(alias="moduleId")
    version: str
    manifest_sha256: str = Field(alias="manifestSha256")
    archive_sha256: str = Field(alias="archiveSha256")
    compressed_bytes: int = Field(alias="compressedBytes")
    unpacked_bytes: int = Field(alias="unpackedBytes")

    @classmethod
    def from_inspected(
        cls,
        inspected: InspectedWorkshopPackage,
    ) -> "PackageInspectionSummary":
        return cls.model_validate(
            {
                "moduleId": inspected.manifest.id,
                "version": inspected.manifest.version,
                "manifestSha256": inspected.manifest_sha256,
                "archiveSha256": inspected.archive_sha256,
                "compressedBytes": inspected.compressed_bytes,
                "unpackedBytes": inspected.unpacked_bytes,
            }
        )

    def as_json_object(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)
