"""Installable Creative Workshop host routes.
可安装式创意工坊宿主接口。
"""

from __future__ import annotations

import hmac
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Annotated, NoReturn
from urllib.parse import quote

import httpx
from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from api.file_bridge import UploadTooLargeError, upload_to_tempfile
from api.schemas.workshop import (
    GithubInstallRequest,
    InstalledWorkshopModuleResponse,
    InstalledWorkshopVersionResponse,
    LocalizedTextResponse,
    ModuleActivateRequest,
    ModuleEnabledRequest,
    ModuleUninstallRequest,
    RegistryInstallRequest,
    WorkshopCatalogModuleResponse,
    WorkshopCatalogResponse,
    WorkshopCatalogVersionResponse,
    WorkshopModuleDetailsResponse,
    WorkshopModuleMutationResponse,
    WorkshopModulesResponse,
    WorkshopPermissionResponse,
    WorkshopRevocationResponse,
)
from api.structured_logging import get_logger
from api.workshop_seed import restore_official_workshop_seed
from config import get_asset_path, get_workshop_data_dir
from core.workshop import (
    InstalledModuleState,
    RegistryClient,
    WorkshopInstallError,
    WorkshopInstaller,
    WorkshopPackageError,
    WorkshopRegistryError,
    WorkshopReleaseError,
    download_registry_package,
    is_browser_trusted_workshop_module,
    load_registry_keys,
    resolve_github_release_package,
)
from core.workshop.constants import (
    MAX_GALLERY_FILES,
    MAX_MANIFEST_BYTES,
    MAX_PACKAGE_BYTES,
    MAX_TEXT_DOCUMENT_BYTES,
    WORKSHOP_API_VERSION,
)
from core.workshop.models import (
    RegistryIndex,
    RegistryModule,
    RegistryRefreshResult,
    RegistryVersion,
    WorkshopManifestV1,
)
from core.workshop.registry_client import select_install_candidate


router = APIRouter(prefix="/api/workshop/v1", tags=["Creative Workshop"])
log = get_logger(__name__)

LUMINA_VERSION = "2.0.1"
_PUBLIC_ASSET_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".webp"}
)
_RUNTIME_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data: blob:; "
    "font-src data:; "
    "media-src data: blob:; "
    "worker-src data: blob:; "
    "connect-src 'none'; "
    "object-src 'none'; "
    "frame-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)
_RUNTIME_HEADERS = {
    "Content-Security-Policy": _RUNTIME_CSP,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), "
        "usb=(), serial=(), bluetooth=(), "
        "clipboard-read=(), clipboard-write=()"
    ),
}
_PUBLIC_ASSET_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def get_workshop_installer() -> WorkshopInstaller:
    """Build a filesystem-scoped Workshop installer.

    创建限定在创意工坊数据目录内的安装器。
    """

    return WorkshopInstaller(data_dir=get_workshop_data_dir())


def get_workshop_registry_client() -> RegistryClient:
    """Build the signed Registry client from app-owned trust roots.

    使用应用内置的信任根创建签名 Registry 客户端。
    """

    data_dir = Path(get_workshop_data_dir())
    return RegistryClient(
        keys=load_registry_keys(
            get_asset_path("workshop-registry/keys.json")
        ),
        cache_dir=data_dir / "cache",
        snapshot_path=get_asset_path(
            "workshop-registry/registry-v1.json"
        ),
    )


def _raise_workshop_http_error(
    *,
    event: str,
    exc: Exception,
    status_code: int,
    detail: str,
    module_id: str | None = None,
    version: str | None = None,
    log_error_message: str | None = None,
) -> NoReturn:
    log.warning(
        "Creative Workshop request failed",
        extra={
            "event": event,
            "status_code": status_code,
            "error_type": type(exc).__name__,
            "error_message": log_error_message or str(exc),
            "module_id": module_id,
            "version": version,
        },
    )
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _install_error_status(exc: WorkshopInstallError) -> int:
    message = str(exc).casefold()
    if (
        "not installed" in message
        or "is not installed" in message
        or "module is not installed" in message
    ):
        return 404
    if (
        "already installed" in message
        or "cannot change" in message
        or "no rollback version" in message
    ):
        return 409
    return 422


def _module_version_for_assets(
    state: InstalledModuleState,
) -> str | None:
    if state.active_version is not None:
        return state.active_version
    if state.candidate_version is not None:
        return state.candidate_version
    if state.previous_version is not None:
        return state.previous_version
    if state.versions:
        return state.versions[-1]
    return None


def _read_bounded_utf8(
    root: Path,
    relative_path: str,
    *,
    maximum_bytes: int,
) -> str:
    """Read one expected regular UTF-8 file without following symlinks."""

    if maximum_bytes < 1:
        raise ValueError("maximum_bytes must be positive")
    if root.is_symlink() or not root.is_dir():
        raise OSError("Workshop version root is unavailable")
    path = root / relative_path
    current = root
    for part in Path(relative_path).parts:
        if part in {"", ".", ".."}:
            raise OSError("Workshop document path is invalid")
        current = current / part
        if current.is_symlink():
            raise OSError("Workshop document cannot be a symlink")
    if not path.is_file():
        raise OSError("Workshop document is unavailable")
    stat = path.stat()
    if stat.st_size > maximum_bytes:
        raise OSError("Workshop document exceeds its size limit")
    content = path.read_bytes()
    if len(content) > maximum_bytes:
        raise OSError("Workshop document exceeds its size limit")
    return content.decode("utf-8")


def _installed_version_response(
    installer: WorkshopInstaller,
    state: InstalledModuleState,
    version: str,
) -> InstalledWorkshopVersionResponse | None:
    root = installer.version_path(state.module_id, version)
    try:
        manifest_text = _read_bounded_utf8(
            root,
            "manifest.json",
            maximum_bytes=MAX_MANIFEST_BYTES,
        )
        manifest = WorkshopManifestV1.model_validate_json(manifest_text)
        if manifest.id != state.module_id or manifest.version != version:
            raise ValueError("installed manifest identity mismatch")
    except (OSError, UnicodeError, ValueError, ValidationError) as exc:
        log.warning(
            "Installed Workshop manifest could not be read",
            extra={
                "event": "workshop_module_manifest_read_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "module_id": state.module_id,
                "version": version,
            },
        )
        return None

    module_id = quote(state.module_id, safe="")
    encoded_version = quote(version, safe="")
    version_base = (
        f"/api/workshop/v1/modules/{module_id}/{encoded_version}"
    )
    asset_base_url = f"{version_base}/assets"
    return InstalledWorkshopVersionResponse(
        version=version,
        name=_localized_response(manifest.name),
        description=_localized_response(manifest.description),
        publisher=manifest.publisher,
        workshop_api_min=manifest.workshop_api.minimum,
        workshop_api_max_exclusive=(
            manifest.workshop_api.max_exclusive
        ),
        lumina_version_min=manifest.lumina_version.minimum,
        permissions=tuple(
            WorkshopPermissionResponse(
                name=permission.name,
                reason=permission.reason,
            )
            for permission in manifest.permissions
        ),
        runtime_url=f"{version_base}/runtime",
        details_url=f"{version_base}/details",
        icon_url=f"{asset_base_url}/icon.png",
        asset_base_url=asset_base_url,
    )


def _state_response(
    state: InstalledModuleState,
    installer: WorkshopInstaller | None = None,
) -> InstalledWorkshopModuleResponse:
    installer = installer or get_workshop_installer()
    module_id = quote(state.module_id, safe="")
    asset_version = _module_version_for_assets(state)
    asset_base_url = None
    icon_url = None
    if asset_version is not None:
        encoded_version = quote(asset_version, safe="")
        asset_base_url = (
            f"/api/workshop/v1/modules/{module_id}/"
            f"{encoded_version}/assets"
        )
        icon_url = f"{asset_base_url}/icon.png"

    runtime_url = None
    if state.enabled and state.active_version is not None:
        runtime_url = (
            f"/api/workshop/v1/modules/{module_id}/"
            f"{quote(state.active_version, safe='')}/runtime"
        )
    return InstalledWorkshopModuleResponse(
        module_id=state.module_id,
        source=state.source,
        source_repository=state.source_repository,
        official=state.official,
        enabled=state.enabled,
        active_version=state.active_version,
        previous_version=state.previous_version,
        candidate_version=state.candidate_version,
        versions=state.versions,
        official_uninstalled=state.official_uninstalled,
        consecutive_start_failures=state.consecutive_start_failures,
        runtime_url=runtime_url,
        icon_url=icon_url,
        asset_base_url=asset_base_url,
        version_details=tuple(
            detail
            for version in state.versions
            if (
                detail := _installed_version_response(
                    installer,
                    state,
                    version,
                )
            )
            is not None
        ),
    )


def _localized_response(value: object) -> LocalizedTextResponse:
    return LocalizedTextResponse(
        zh_cn=str(getattr(value, "zh_cn")),
        en_us=str(getattr(value, "en_us")),
    )


def _catalog_module_response(
    module: RegistryModule,
) -> WorkshopCatalogModuleResponse:
    versions: list[WorkshopCatalogVersionResponse] = []
    for version in module.versions:
        revocation = None
        if version.revocation is not None:
            revocation = WorkshopRevocationResponse(
                reason_code=version.revocation.reason_code,
                severity=version.revocation.severity,
                message=_localized_response(
                    version.revocation.message
                ),
            )
        versions.append(
            WorkshopCatalogVersionResponse(
                version=version.version,
                state=version.state,
                permissions=tuple(
                    WorkshopPermissionResponse(
                        name=permission.name,
                        reason=permission.reason,
                    )
                    for permission in version.permissions
                ),
                revocation=revocation,
            )
        )
    return WorkshopCatalogModuleResponse(
        module_id=module.module_id,
        repository=module.repository,
        official=module.official,
        publisher=module.publisher,
        name=_localized_response(module.name),
        description=_localized_response(module.description),
        versions=tuple(versions),
    )


def _catalog_response(
    result: RegistryRefreshResult,
) -> WorkshopCatalogResponse:
    return WorkshopCatalogResponse(
        source=result.source,
        verified=result.verified,
        generated_at=result.index.generated_at,
        modules=tuple(
            _catalog_module_response(module)
            for module in result.index.modules
        ),
    )


def _find_registry_module(
    index: RegistryIndex,
    module_id: str,
) -> RegistryModule | None:
    return next(
        (
            module
            for module in index.modules
            if module.module_id == module_id
        ),
        None,
    )


def _remove_temporary_package(path: str | Path | None) -> None:
    if path is None:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        log.warning(
            "Temporary Workshop package cleanup failed",
            extra={
                "event": "workshop_temp_package_cleanup_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": "<temporary-workshop-package>",
            },
        )


@router.get("/catalog", response_model=WorkshopCatalogResponse)
def workshop_catalog() -> WorkshopCatalogResponse:
    """Return public metadata from a trusted Registry source.

    返回可信 Registry 中的公开模块元数据。
    """

    try:
        result = get_workshop_registry_client().refresh()
    except (WorkshopRegistryError, OSError) as exc:
        _raise_workshop_http_error(
            event="workshop_catalog_refresh_failed",
            exc=exc,
            status_code=503,
            detail="No trusted Creative Workshop catalog is available.",
        )
    log.info(
        "Creative Workshop catalog refreshed",
        extra={
            "event": "workshop_catalog_refresh_done",
            "catalog_source": result.source,
            "verified": result.verified,
            "module_count": len(result.index.modules),
        },
    )
    return _catalog_response(result)


@router.get("/modules", response_model=WorkshopModulesResponse)
def workshop_modules() -> WorkshopModulesResponse:
    """Return installed module state without private filesystem paths.

    返回不含私有文件系统路径的已安装模块状态。
    """

    try:
        installer = get_workshop_installer()
        return WorkshopModulesResponse(
            modules=tuple(
                _state_response(state, installer)
                for state in installer.list()
            )
        )
    except OSError as exc:
        _raise_workshop_http_error(
            event="workshop_modules_list_failed",
            exc=exc,
            status_code=503,
            detail=(
                "Creative Workshop storage is unavailable. "
                "Check the app data folder permissions and available disk space, then retry."
            ),
        )


@router.post(
    "/install/local",
    response_model=WorkshopModuleMutationResponse,
)
async def workshop_install_local(
    archive: Annotated[UploadFile, File()],
) -> WorkshopModuleMutationResponse:
    """Install a validated local package as an inactive candidate.

    将本地安装包校验后安装为未激活候选版本。
    """

    filename = archive.filename or ""
    if not filename.lower().endswith(".lumina-workshop"):
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=WorkshopPackageError(
                "local package must use .lumina-workshop"
            ),
            status_code=422,
            detail="Select a .lumina-workshop package.",
        )
    archive_path: str | None = None
    try:
        archive_path = await upload_to_tempfile(
            archive,
            suffix=".lumina-workshop",
            max_bytes=MAX_PACKAGE_BYTES,
        )
        state = get_workshop_installer().install_candidate(
            archive_path,
            source="local",
            source_repository="local",
            official=False,
        )
    except UploadTooLargeError as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=413,
            detail="The Creative Workshop package is too large.",
        )
    except WorkshopPackageError as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=422,
            detail="The Creative Workshop package is invalid.",
        )
    except WorkshopInstallError as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=_install_error_status(exc),
            detail=str(exc),
        )
    except OSError as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=503,
            detail="Creative Workshop storage is unavailable.",
        )
    finally:
        _remove_temporary_package(archive_path)
    log.info(
        "Creative Workshop module installed",
        extra={
            "event": "workshop_module_install_done",
            "module_id": state.module_id,
            "version": state.candidate_version,
            "install_source": "local",
            "official": False,
        },
    )
    return WorkshopModuleMutationResponse(module=_state_response(state))


_REGISTRY_DOWNLOAD_MAX_ATTEMPTS = 2
_REGISTRY_DOWNLOAD_RETRY_DELAY_SECONDS = 0.25


def _download_registry_package_with_retry(
    candidate: RegistryVersion,
    *,
    module_id: str,
) -> Path:
    """Retry one idempotent download after a connection or read timeout."""

    for attempt in range(1, _REGISTRY_DOWNLOAD_MAX_ATTEMPTS + 1):
        try:
            return download_registry_package(candidate)
        except (httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            if attempt >= _REGISTRY_DOWNLOAD_MAX_ATTEMPTS:
                raise
            log.warning(
                "Creative Workshop Registry download timed out; retrying",
                extra={
                    "event": "workshop_registry_download_retry",
                    "error_type": type(exc).__name__,
                    "error_message": "Registry package download timed out",
                    "module_id": module_id,
                    "version": candidate.version,
                    "attempt": attempt,
                    "max_attempts": _REGISTRY_DOWNLOAD_MAX_ATTEMPTS,
                    "delay_ms": int(
                        _REGISTRY_DOWNLOAD_RETRY_DELAY_SECONDS * 1000
                    ),
                },
            )
            time.sleep(_REGISTRY_DOWNLOAD_RETRY_DELAY_SECONDS)

    raise RuntimeError("Registry download retry loop exhausted")


@router.post(
    "/install/registry",
    response_model=WorkshopModuleMutationResponse,
)
def workshop_install_registry(
    payload: RegistryInstallRequest,
) -> WorkshopModuleMutationResponse:
    """Install one exact candidate selected from a trusted Registry.

    安装从可信 Registry 中选出的精确候选版本。
    """

    archive_path: Path | None = None
    try:
        result = get_workshop_registry_client().refresh()
        module = _find_registry_module(
            result.index,
            payload.module_id,
        )
        if module is None:
            raise WorkshopInstallError(
                "Workshop module is not present in the Registry"
            )
        candidate = select_install_candidate(
            result.index,
            payload.module_id,
            lumina_version=LUMINA_VERSION,
            workshop_api_version=WORKSHOP_API_VERSION,
            requested_version=payload.version,
        )
        if candidate is None:
            raise WorkshopInstallError(
                "No compatible installable Workshop version is available"
            )
        archive_path = _download_registry_package_with_retry(
            candidate,
            module_id=payload.module_id,
        )
        state = get_workshop_installer().install_candidate(
            archive_path,
            source="registry",
            source_repository=module.repository,
            official=module.official,
        )
    except WorkshopRegistryError as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=503,
            detail="No trusted Creative Workshop catalog is available.",
            module_id=payload.module_id,
            version=payload.version,
        )
    except WorkshopReleaseError as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=502,
            detail="The Registry package could not be downloaded safely.",
            module_id=payload.module_id,
            version=payload.version,
        )
    except WorkshopPackageError as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=502,
            detail="The Registry package is invalid.",
            module_id=payload.module_id,
            version=payload.version,
        )
    except WorkshopInstallError as exc:
        status_code = (
            404
            if "not present" in str(exc).casefold()
            else _install_error_status(exc)
        )
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=status_code,
            detail=str(exc),
            module_id=payload.module_id,
            version=payload.version,
        )
    except httpx.TimeoutException as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=504,
            detail=(
                "The Registry package download timed out. "
                "Check your network or proxy settings, then retry."
            ),
            module_id=payload.module_id,
            version=payload.version,
            log_error_message="Registry package download timed out",
        )
    except (httpx.HTTPError, OSError) as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=502,
            detail="The Registry package could not be downloaded.",
            module_id=payload.module_id,
            version=payload.version,
        )
    finally:
        _remove_temporary_package(archive_path)
    log.info(
        "Creative Workshop module installed",
        extra={
            "event": "workshop_module_install_done",
            "module_id": state.module_id,
            "version": state.candidate_version,
            "install_source": "registry",
            "official": state.official,
        },
    )
    return WorkshopModuleMutationResponse(module=_state_response(state))


@router.post(
    "/install/github",
    response_model=WorkshopModuleMutationResponse,
)
def workshop_install_github(
    payload: GithubInstallRequest,
) -> WorkshopModuleMutationResponse:
    """Install a standard package from one exact GitHub Release.

    从精确指定的 GitHub Release 安装标准模块包。
    """

    archive_path: Path | None = None
    try:
        archive_path = resolve_github_release_package(
            payload.repository_url,
            payload.version,
        )
        state = get_workshop_installer().install_candidate(
            archive_path,
            source="github",
            source_repository=payload.repository_url,
            official=False,
        )
    except WorkshopReleaseError as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=502,
            detail="The GitHub Release could not be downloaded safely.",
            version=payload.version,
        )
    except WorkshopPackageError as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=502,
            detail="The GitHub Release package is invalid.",
            version=payload.version,
        )
    except WorkshopInstallError as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=_install_error_status(exc),
            detail=str(exc),
            version=payload.version,
        )
    except (httpx.HTTPError, OSError) as exc:
        _raise_workshop_http_error(
            event="workshop_module_install_failed",
            exc=exc,
            status_code=502,
            detail="The GitHub Release could not be downloaded.",
            version=payload.version,
        )
    finally:
        _remove_temporary_package(archive_path)
    log.info(
        "Creative Workshop module installed",
        extra={
            "event": "workshop_module_install_done",
            "module_id": state.module_id,
            "version": state.candidate_version,
            "install_source": "github",
            "official": False,
        },
    )
    return WorkshopModuleMutationResponse(module=_state_response(state))


def _run_install_mutation(
    *,
    event: str,
    module_id: str,
    version: str | None,
    operation: object,
) -> InstalledModuleState:
    try:
        if not callable(operation):
            raise TypeError("Workshop mutation is not callable")
        state = operation()
    except WorkshopInstallError as exc:
        _raise_workshop_http_error(
            event=event,
            exc=exc,
            status_code=_install_error_status(exc),
            detail=str(exc),
            module_id=module_id,
            version=version,
        )
    except OSError as exc:
        _raise_workshop_http_error(
            event=event,
            exc=exc,
            status_code=503,
            detail="Creative Workshop storage is unavailable.",
            module_id=module_id,
            version=version,
        )
    if not isinstance(state, InstalledModuleState):
        raise RuntimeError("Workshop mutation returned invalid state")
    return state


@router.post(
    "/modules/{module_id}/activate",
    response_model=WorkshopModuleMutationResponse,
)
def workshop_activate_module(
    module_id: str,
    payload: ModuleActivateRequest,
) -> WorkshopModuleMutationResponse:
    installer = get_workshop_installer()
    state = _run_install_mutation(
        event="workshop_module_activate_failed",
        module_id=module_id,
        version=payload.version,
        operation=lambda: installer.activate(module_id, payload.version),
    )
    log.info(
        "Creative Workshop module activated",
        extra={
            "event": "workshop_module_activate_done",
            "module_id": module_id,
            "version": payload.version,
        },
    )
    return WorkshopModuleMutationResponse(module=_state_response(state))


@router.post(
    "/modules/{module_id}/rollback",
    response_model=WorkshopModuleMutationResponse,
)
def workshop_rollback_module(
    module_id: str,
) -> WorkshopModuleMutationResponse:
    installer = get_workshop_installer()
    state = _run_install_mutation(
        event="workshop_module_rollback_failed",
        module_id=module_id,
        version=None,
        operation=lambda: installer.rollback(module_id),
    )
    log.info(
        "Creative Workshop module rolled back",
        extra={
            "event": "workshop_module_rollback_done",
            "module_id": module_id,
            "version": state.active_version,
        },
    )
    return WorkshopModuleMutationResponse(module=_state_response(state))


@router.patch(
    "/modules/{module_id}/enabled",
    response_model=WorkshopModuleMutationResponse,
)
def workshop_set_module_enabled(
    module_id: str,
    payload: ModuleEnabledRequest,
) -> WorkshopModuleMutationResponse:
    installer = get_workshop_installer()
    state = _run_install_mutation(
        event="workshop_module_enabled_failed",
        module_id=module_id,
        version=None,
        operation=lambda: installer.set_enabled(
            module_id,
            payload.enabled,
        ),
    )
    log.info(
        "Creative Workshop module enabled state changed",
        extra={
            "event": "workshop_module_enabled_done",
            "module_id": module_id,
            "version": state.active_version,
            "enabled": state.enabled,
        },
    )
    return WorkshopModuleMutationResponse(module=_state_response(state))


@router.delete(
    "/modules/{module_id}",
    response_model=WorkshopModuleMutationResponse,
)
def workshop_uninstall_module(
    module_id: str,
    payload: ModuleUninstallRequest,
) -> WorkshopModuleMutationResponse:
    installer = get_workshop_installer()
    try:
        state = installer.uninstall(
            module_id,
            delete_projects=payload.delete_projects,
        )
    except WorkshopInstallError as exc:
        _raise_workshop_http_error(
            event="workshop_module_uninstall_failed",
            exc=exc,
            status_code=_install_error_status(exc),
            detail=str(exc),
            module_id=module_id,
        )
    except OSError as exc:
        _raise_workshop_http_error(
            event="workshop_module_uninstall_failed",
            exc=exc,
            status_code=503,
            detail="Creative Workshop storage is unavailable.",
            module_id=module_id,
        )
    log.info(
        "Creative Workshop module uninstalled",
        extra={
            "event": "workshop_module_uninstall_done",
            "module_id": module_id,
            "delete_projects": payload.delete_projects,
            "tombstone_retained": state is not None,
        },
    )
    return WorkshopModuleMutationResponse(
        module=(
            _state_response(state, installer)
            if state is not None
            else None
        )
    )


@router.post(
    "/modules/{module_id}/restore-seed",
    response_model=WorkshopModuleMutationResponse,
)
def workshop_restore_official_seed(
    module_id: str,
) -> WorkshopModuleMutationResponse:
    """Restore a user-uninstalled official module from bundled bytes.

    使用应用内置且已校验的安装包恢复被用户卸载的官方模块。
    """

    installer = get_workshop_installer()
    try:
        result = restore_official_workshop_seed(
            module_id,
            installer=installer,
        )
    except FileNotFoundError as exc:
        _raise_workshop_http_error(
            event="workshop_module_seed_restore_failed",
            exc=exc,
            status_code=503,
            detail="The bundled official Workshop module is unavailable.",
            module_id=module_id,
            log_error_message=(
                "bundled official Workshop seed is not configured"
            ),
        )
    except (WorkshopPackageError, ValueError) as exc:
        _raise_workshop_http_error(
            event="workshop_module_seed_restore_failed",
            exc=exc,
            status_code=503,
            detail="The bundled official Workshop module failed validation.",
            module_id=module_id,
            log_error_message=(
                "bundled official Workshop seed failed validation"
            ),
        )
    except WorkshopInstallError as exc:
        _raise_workshop_http_error(
            event="workshop_module_seed_restore_failed",
            exc=exc,
            status_code=409,
            detail=str(exc),
            module_id=module_id,
        )
    except OSError as exc:
        _raise_workshop_http_error(
            event="workshop_module_seed_restore_failed",
            exc=exc,
            status_code=503,
            detail="Creative Workshop storage is unavailable.",
            module_id=module_id,
            log_error_message=(
                "Workshop seed restore storage transaction failed"
            ),
        )

    state = result.state
    if state is None:
        raise RuntimeError("Workshop seed restore returned invalid state")
    log.info(
        "Creative Workshop official seed restored",
        extra={
            "event": "workshop_module_seed_restore_done",
            "module_id": result.module_id,
            "version": result.version,
            "install_source": "seed",
            "official": True,
        },
    )
    return WorkshopModuleMutationResponse(
        module=_state_response(state, installer)
    )


def _require_runtime_state(
    installer: WorkshopInstaller,
    module_id: str,
    version: str,
    *,
    require_enabled: bool = True,
) -> InstalledModuleState:
    try:
        state = installer.get(module_id)
        version_path = installer.version_path(module_id, version)
    except WorkshopInstallError as exc:
        _raise_workshop_http_error(
            event="workshop_module_runtime_failed",
            exc=exc,
            status_code=422,
            detail="The Workshop module identity is invalid.",
            module_id=module_id,
            version=version,
        )
    if (
        state is None
        or version not in state.versions
        or not version_path.is_dir()
    ):
        _raise_workshop_http_error(
            event="workshop_module_runtime_failed",
            exc=WorkshopInstallError(
                "Workshop module version is not installed"
            ),
            status_code=404,
            detail="The Workshop module version is not installed.",
            module_id=module_id,
            version=version,
        )
    if require_enabled and not state.enabled:
        _raise_workshop_http_error(
            event="workshop_module_runtime_failed",
            exc=WorkshopInstallError("Workshop module is disabled"),
            status_code=409,
            detail="The Workshop module is disabled.",
            module_id=module_id,
            version=version,
        )
    return state


def _verify_runtime_token(
    state: InstalledModuleState,
    supplied_token: str | None,
    *,
    module_id: str,
    version: str,
) -> None:
    if is_browser_trusted_workshop_module(
        state.source,
        state.official,
    ):
        return
    expected = os.environ.get(
        "LUMINA_WORKSHOP_DESKTOP_TOKEN",
        "",
    )
    if not expected:
        _raise_workshop_http_error(
            event="workshop_module_runtime_failed",
            exc=WorkshopInstallError(
                "desktop Workshop runtime token is unavailable"
            ),
            status_code=503,
            detail=(
                "Community Workshop modules require the Lumina desktop "
                "sandbox."
            ),
            module_id=module_id,
            version=version,
        )
    if supplied_token is None or not hmac.compare_digest(
        supplied_token,
        expected,
    ):
        _raise_workshop_http_error(
            event="workshop_module_runtime_failed",
            exc=PermissionError("Workshop desktop token mismatch"),
            status_code=403,
            detail="Workshop runtime access was denied.",
            module_id=module_id,
            version=version,
        )


def _verify_registry_runtime_status(
    state: InstalledModuleState,
    *,
    module_id: str,
    version: str,
) -> None:
    if state.source != "registry":
        return
    try:
        result = get_workshop_registry_client().refresh()
        if not result.verified:
            raise WorkshopRegistryError(
                "Workshop Registry result is not verified"
            )
    except (WorkshopRegistryError, OSError) as exc:
        _raise_workshop_http_error(
            event="workshop_module_runtime_failed",
            exc=exc,
            status_code=503,
            detail="No trusted Creative Workshop catalog is available.",
            module_id=module_id,
            version=version,
        )
    module = _find_registry_module(result.index, module_id)
    registry_version = (
        next(
            (
                candidate
                for candidate in module.versions
                if candidate.version == version
            ),
            None,
        )
        if module is not None
        else None
    )
    if registry_version is not None and (
        registry_version.state == "blocked"
        or registry_version.revocation is not None
    ):
        _raise_workshop_http_error(
            event="workshop_module_runtime_failed",
            exc=WorkshopInstallError(
                "Workshop module version is blocked"
            ),
            status_code=409,
            detail="The Workshop module version is blocked.",
            module_id=module_id,
            version=version,
        )


@router.post(
    "/modules/{module_id}/runtime-success",
    response_model=WorkshopModuleMutationResponse,
)
def workshop_record_runtime_success(
    module_id: str,
) -> WorkshopModuleMutationResponse:
    """Persist a successful sandbox start for one installed module."""

    installer = get_workshop_installer()
    state = _run_install_mutation(
        event="workshop_module_runtime_health_failed",
        module_id=module_id,
        version=None,
        operation=lambda: installer.record_start_success(module_id),
    )
    log.info(
        "Creative Workshop runtime health changed",
        extra={
            "event": "workshop_module_runtime_health_done",
            "module_id": module_id,
            "version": state.active_version,
            "runtime_outcome": "success",
            "consecutive_start_failures": (
                state.consecutive_start_failures
            ),
        },
    )
    return WorkshopModuleMutationResponse(
        module=_state_response(state, installer)
    )


@router.post(
    "/modules/{module_id}/runtime-failure",
    response_model=WorkshopModuleMutationResponse,
)
def workshop_record_runtime_failure(
    module_id: str,
) -> WorkshopModuleMutationResponse:
    """Persist a failed sandbox start and apply the rollback policy."""

    installer = get_workshop_installer()
    state = _run_install_mutation(
        event="workshop_module_runtime_health_failed",
        module_id=module_id,
        version=None,
        operation=lambda: installer.record_start_failure(module_id),
    )
    log.info(
        "Creative Workshop runtime health changed",
        extra={
            "event": "workshop_module_runtime_health_done",
            "module_id": module_id,
            "version": state.active_version,
            "runtime_outcome": "failure",
            "consecutive_start_failures": (
                state.consecutive_start_failures
            ),
        },
    )
    return WorkshopModuleMutationResponse(
        module=_state_response(state, installer)
    )


@router.get(
    "/modules/{module_id}/{version}/details",
    response_model=WorkshopModuleDetailsResponse,
)
def workshop_module_details(
    module_id: str,
    version: str,
) -> WorkshopModuleDetailsResponse:
    """Return bounded public documentation for an installed version."""

    installer = get_workshop_installer()
    _require_runtime_state(
        installer,
        module_id,
        version,
        require_enabled=False,
    )
    try:
        root = installer.version_path(module_id, version)
        readme_markdown = _read_bounded_utf8(
            root,
            "README.md",
            maximum_bytes=MAX_TEXT_DOCUMENT_BYTES,
        )
        license_text = _read_bounded_utf8(
            root,
            "LICENSE",
            maximum_bytes=MAX_TEXT_DOCUMENT_BYTES,
        )
        gallery_root = root / "assets" / "gallery"
        gallery_assets: list[str] = []
        if gallery_root.is_dir() and not gallery_root.is_symlink():
            for path in sorted(gallery_root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(root / "assets").as_posix()
                if (
                    _resolve_public_asset(
                        installer,
                        module_id,
                        version,
                        relative,
                    )
                    is None
                ):
                    continue
                gallery_assets.append(relative)
                if len(gallery_assets) > MAX_GALLERY_FILES:
                    raise OSError(
                        "Workshop gallery exceeds its file limit"
                    )
    except (WorkshopInstallError, OSError, UnicodeError) as exc:
        _raise_workshop_http_error(
            event="workshop_module_details_failed",
            exc=exc,
            status_code=503,
            detail="The Workshop module details are unavailable.",
            module_id=module_id,
            version=version,
        )

    module_url = quote(module_id, safe="")
    version_url = quote(version, safe="")
    asset_base = (
        f"/api/workshop/v1/modules/{module_url}/"
        f"{version_url}/assets"
    )
    return WorkshopModuleDetailsResponse(
        module_id=module_id,
        version=version,
        readme_markdown=readme_markdown,
        license_text=license_text,
        gallery_urls=tuple(
            f"{asset_base}/"
            + "/".join(
                quote(part, safe="")
                for part in relative.split("/")
            )
            for relative in gallery_assets
        ),
    )


def _inject_runtime_csp(html: str) -> str:
    meta = (
        '<meta http-equiv="Content-Security-Policy" '
        f'content="{_RUNTIME_CSP}">'
    )
    head = re.search(r"<head\b[^>]*>", html, flags=re.IGNORECASE)
    if head is None:
        return f"{meta}{html}"
    return f"{html[:head.end()]}{meta}{html[head.end():]}"


@router.get("/modules/{module_id}/{version}/runtime")
def workshop_module_runtime(
    module_id: str,
    version: str,
    desktop_token: Annotated[
        str | None,
        Header(alias="X-Lumina-Workshop-Desktop-Token"),
    ] = None,
) -> Response:
    """Serve one module entrypoint under fixed sandbox headers.

    在固定沙箱响应头下提供模块入口页面。
    """

    installer = get_workshop_installer()
    state = _require_runtime_state(
        installer,
        module_id,
        version,
    )
    _verify_runtime_token(
        state,
        desktop_token,
        module_id=module_id,
        version=version,
    )
    _verify_registry_runtime_status(
        state,
        module_id=module_id,
        version=version,
    )
    runtime_path = installer.version_path(
        module_id,
        version,
    ) / "ui" / "index.html"
    try:
        html = runtime_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        _raise_workshop_http_error(
            event="workshop_module_runtime_failed",
            exc=exc,
            status_code=503,
            detail="The Workshop module runtime is unavailable.",
            module_id=module_id,
            version=version,
        )
    return Response(
        content=_inject_runtime_csp(html),
        media_type="text/html",
        headers=_RUNTIME_HEADERS,
    )


def _resolve_public_asset(
    installer: WorkshopInstaller,
    module_id: str,
    version: str,
    asset_path: str,
) -> Path | None:
    root = (
        installer.version_path(module_id, version) / "assets"
    ).resolve()
    candidate = (root / asset_path).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None
    parts = relative.parts
    if (
        not parts
        or any(part in {"", ".", ".."} for part in parts)
        or candidate.suffix.lower() not in _PUBLIC_ASSET_EXTENSIONS
        or not (
            parts == ("icon.png",)
            or (parts[0] == "gallery" and len(parts) >= 2)
        )
        or not candidate.is_file()
        or candidate.is_symlink()
    ):
        return None
    return candidate


@router.get(
    "/modules/{module_id}/{version}/assets/{asset_path:path}"
)
def workshop_module_public_asset(
    module_id: str,
    version: str,
    asset_path: str,
) -> Response:
    """Serve only immutable public icon and gallery assets.

    仅提供不可变的公开图标与图库资源。
    """

    installer = get_workshop_installer()
    _require_runtime_state(
        installer,
        module_id,
        version,
        require_enabled=False,
    )
    try:
        requested = _resolve_public_asset(
            installer,
            module_id,
            version,
            asset_path,
        )
    except WorkshopInstallError as exc:
        _raise_workshop_http_error(
            event="workshop_module_asset_failed",
            exc=exc,
            status_code=422,
            detail="The Workshop asset identity is invalid.",
            module_id=module_id,
            version=version,
        )
    if requested is None:
        _raise_workshop_http_error(
            event="workshop_module_asset_failed",
            exc=FileNotFoundError("Workshop public asset not found"),
            status_code=404,
            detail="Workshop public asset not found.",
            module_id=module_id,
            version=version,
        )
    try:
        content = requested.read_bytes()
    except OSError as exc:
        _raise_workshop_http_error(
            event="workshop_module_asset_failed",
            exc=exc,
            status_code=503,
            detail="The Workshop public asset is unavailable.",
            module_id=module_id,
            version=version,
        )
    media_type = (
        mimetypes.guess_type(requested.name)[0]
        or "application/octet-stream"
    )
    return Response(
        content=content,
        media_type=media_type,
        headers=_PUBLIC_ASSET_HEADERS,
    )
