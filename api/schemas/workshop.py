"""Creative Workshop HTTP schemas.
创意工坊 HTTP 接口模型。
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.workshop.models import MODULE_ID_PATTERN, validate_semver


class WorkshopHttpModel(BaseModel):
    """Closed HTTP model shared by Workshop requests and responses."""

    model_config = ConfigDict(extra="forbid")


class RegistryInstallRequest(WorkshopHttpModel):
    module_id: str = Field(min_length=3, max_length=128)
    version: str | None = None

    @field_validator("module_id")
    @classmethod
    def module_id_is_safe(cls, value: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("module_id is invalid")
        return value

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, value: str | None) -> str | None:
        if value is not None:
            validate_semver(value)
        return value


class GithubInstallRequest(WorkshopHttpModel):
    repository_url: str = Field(min_length=1, max_length=500)
    version: str

    @field_validator("repository_url")
    @classmethod
    def repository_is_exact_github_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        parts = tuple(part for part in parsed.path.split("/") if part)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
            or value.endswith("/")
            or len(parts) != 2
            or any(
                re.fullmatch(r"[A-Za-z0-9_.-]+", part) is None
                for part in parts
            )
            or parts[1].endswith(".git")
        ):
            raise ValueError(
                "repository_url must be https://github.com/<owner>/<repo>"
            )
        return value

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        return validate_semver(value)


class ModuleActivateRequest(WorkshopHttpModel):
    version: str

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        return validate_semver(value)


class ModuleEnabledRequest(WorkshopHttpModel):
    enabled: bool


class ModuleUninstallRequest(WorkshopHttpModel):
    delete_projects: bool = False
    # Backend data categories; defaults keep user data and reclaim programs.
    delete_task_data: bool = False
    retain_models: bool = False


class LocalizedTextResponse(WorkshopHttpModel):
    zh_cn: str
    en_us: str


class WorkshopPermissionResponse(WorkshopHttpModel):
    name: str
    reason: str


class WorkshopRevocationResponse(WorkshopHttpModel):
    reason_code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: LocalizedTextResponse


class WorkshopCatalogVersionResponse(WorkshopHttpModel):
    version: str
    state: Literal["active", "deprecated", "blocked"]
    permissions: tuple[WorkshopPermissionResponse, ...]
    revocation: WorkshopRevocationResponse | None


class WorkshopCatalogModuleResponse(WorkshopHttpModel):
    module_id: str
    repository: str
    official: bool
    publisher: str
    name: LocalizedTextResponse
    description: LocalizedTextResponse
    versions: tuple[WorkshopCatalogVersionResponse, ...]


class WorkshopCatalogResponse(WorkshopHttpModel):
    source: Literal["remote", "cache", "snapshot"]
    verified: bool
    generated_at: datetime
    modules: tuple[WorkshopCatalogModuleResponse, ...]


class WorkshopBackendCapabilityResponse(WorkshopHttpModel):
    name: str
    reason: str


class WorkshopBackendVariantSummary(WorkshopHttpModel):
    id: str
    name: LocalizedTextResponse
    description: LocalizedTextResponse
    platforms: tuple[str, ...]


class WorkshopBackendSummaryResponse(WorkshopHttpModel):
    """Static backend declaration of one installed version (manifest v2)."""

    python: str
    platforms: tuple[str, ...]
    capabilities: tuple[WorkshopBackendCapabilityResponse, ...]
    model_count: int
    variants: tuple[WorkshopBackendVariantSummary, ...]


class InstalledWorkshopVersionResponse(WorkshopHttpModel):
    version: str
    name: LocalizedTextResponse
    description: LocalizedTextResponse
    publisher: str
    workshop_api_min: str
    workshop_api_max_exclusive: str
    lumina_version_min: str
    permissions: tuple[WorkshopPermissionResponse, ...]
    runtime_url: str
    details_url: str
    icon_url: str
    asset_base_url: str
    manifest_version: int = 1
    backend: WorkshopBackendSummaryResponse | None = None
    project_snapshot_protocol: int | None = None
    project_snapshot_schemas: tuple[str, ...] = ()


class InstalledWorkshopModuleResponse(WorkshopHttpModel):
    module_id: str
    source: Literal["registry", "github", "local", "seed"]
    source_repository: str
    official: bool
    enabled: bool
    active_version: str | None
    previous_version: str | None
    candidate_version: str | None
    versions: tuple[str, ...]
    official_uninstalled: bool
    consecutive_start_failures: int
    runtime_url: str | None
    icon_url: str | None
    asset_base_url: str | None
    version_details: tuple[InstalledWorkshopVersionResponse, ...]


class WorkshopModuleDetailsResponse(WorkshopHttpModel):
    module_id: str
    version: str
    readme_markdown: str
    license_text: str
    gallery_urls: tuple[str, ...]


class WorkshopModulesResponse(WorkshopHttpModel):
    modules: tuple[InstalledWorkshopModuleResponse, ...]


class WorkshopUninstallReportResponse(WorkshopHttpModel):
    """Cleared, still-shared, user-retained, and not-yet-deleted content."""

    cleared: tuple[dict[str, object], ...]
    shared: tuple[dict[str, object], ...]
    retained: tuple[dict[str, object], ...]
    failed: tuple[dict[str, object], ...]


class WorkshopModuleMutationResponse(WorkshopHttpModel):
    status: Literal["ok"] = "ok"
    module: InstalledWorkshopModuleResponse | None
    uninstall_report: WorkshopUninstallReportResponse | None = None
