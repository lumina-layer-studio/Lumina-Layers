"""Immutable Creative Workshop package models."""

from __future__ import annotations

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

from .constants import ALLOWED_PERMISSION_NAMES, WORKSHOP_MANIFEST_VERSION


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


class WorkshopManifestV1(StrictFrozenModel):
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

    @field_validator("manifest_version")
    @classmethod
    def manifest_version_is_supported(cls, value: int) -> int:
        if value != WORKSHOP_MANIFEST_VERSION:
            raise ValueError("unsupported manifest version")
        return value

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
    def permissions_are_unique(self) -> "WorkshopManifestV1":
        names = [permission.name for permission in self.permissions]
        if len(names) != len(set(names)):
            raise ValueError("manifest contains duplicate permission entries")
        if self.project_snapshots and "project.storage" not in names:
            raise ValueError("project snapshots require project.storage permission")
        return self


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
    manifest: WorkshopManifestV1
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
