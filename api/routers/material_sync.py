"""Material registry sync API routes.
耗材 Registry 同步 API 路由。
"""

from __future__ import annotations

import asyncio
import os
from typing import NoReturn

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from api.file_bridge import UploadTooLargeError, upload_to_tempfile
from api.schemas.single_stage import (
    MaterialRegistryInstallRequest,
    MaterialSyncRollbackRequest,
)
from api.schemas.responses import (
    MaterialRegistryCatalogResponse,
    MaterialSyncInstallResponse,
    MaterialSyncRefreshResponse,
    MaterialSyncRollbackResponse,
    MaterialSyncStatusResponse,
    public_material_response_item,
)
from api.structured_logging import get_logger
from core.registry_transport import RegistryCatalogNotFoundError, map_package_url
from core.single_stage import (
    get_material_sync_status,
    import_saved_stage_a_material_archives,
    install_material_registry_package,
    list_material_registry_catalog,
    material_package_max_archive_bytes,
    refresh_material_sync_from_registry,
    rollback_material_sync_revision,
)

router = APIRouter(prefix="/api/material-sync", tags=["Material Sync"])
log = get_logger(__name__)
MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL = (
    "Material registry catalog is unavailable. Check registry settings and try again."
)
MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL = (
    "Material package install failed. Check the material package and try again."
)
MATERIAL_SYNC_REFRESH_UNAVAILABLE_DETAIL = (
    "Material registry refresh failed. Check registry settings and try again."
)
MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL = (
    "Material sync rollback failed. Check the installed revision and try again."
)
MATERIAL_SYNC_STATUS_UNAVAILABLE_DETAIL = (
    "Material sync status is unavailable. Check the material library and try again."
)
MATERIAL_REGISTRY_URL_NOT_CONFIGURED_DETAIL = "Material registry URL is not configured"
MATERIAL_REGISTRY_PACKAGE_NOT_IN_CATALOG_DETAIL = (
    "Selected material registry package is not in current material registry catalog"
)


def _raise_material_sync_error(
    *,
    event: str,
    exc: Exception,
    status_code: int,
    detail: str,
    **fields: object,
) -> NoReturn:
    log.warning(
        "Material sync request failed",
        extra={
            "event": event,
            "status_code": status_code,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **fields,
        },
    )
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _canonical_package_sha256(value: object) -> str:
    raw_value = str(value or "").strip().lower()
    if raw_value.startswith("sha256:"):
        raw_value = raw_value.split(":", 1)[1]
    return raw_value


def _catalog_value_error_detail(exc: ValueError) -> str:
    return _material_sync_value_error_detail(
        exc,
        fallback=MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL,
    )


def _material_sync_value_error_detail(exc: ValueError, *, fallback: str) -> str:
    raw_detail = str(exc).strip()
    if raw_detail in {
        MATERIAL_REGISTRY_URL_NOT_CONFIGURED_DETAIL,
        MATERIAL_REGISTRY_PACKAGE_NOT_IN_CATALOG_DETAIL,
    }:
        return raw_detail
    return fallback


def _select_catalog_install_entry(
    catalog: dict[str, object],
    payload: MaterialRegistryInstallRequest,
) -> dict[str, object]:
    entries = catalog.get("materials")
    if not isinstance(entries, list):
        raise ValueError("Material registry catalog response is invalid")

    requested_package_url = payload.package_url.strip()
    requested_package_sha256 = _canonical_package_sha256(payload.package_sha256)
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        if str(raw_entry.get("material_id") or "").strip() != payload.material_id:
            continue
        if str(raw_entry.get("revision_id") or "").strip() != payload.revision_id:
            continue
        catalog_package_url = str(raw_entry.get("package_url") or "").strip()
        if catalog_package_url != requested_package_url:
            primary = os.environ.get("LUMINA_MATERIAL_REGISTRY_URL", "").strip().rstrip("/")
            if not primary:
                continue
            try:
                if map_package_url(catalog_package_url, primary, primary) != map_package_url(
                    requested_package_url, primary, primary
                ):
                    continue
            except ValueError:
                continue
        if (
            _canonical_package_sha256(raw_entry.get("package_sha256"))
            != requested_package_sha256
        ):
            continue
        return raw_entry

    raise ValueError(
        "Selected material registry package is not in current material registry catalog"
    )


@router.get("/status", response_model=MaterialSyncStatusResponse)
async def material_sync_status() -> MaterialSyncStatusResponse:
    """Return local material sync-index health and installed package presence.
    返回本地耗材同步索引健康状态与已安装包存在性信息。

    Returns:
        MaterialSyncStatusResponse: Status payload for local/cloud sync UI.
            （用于本地/云同步 UI 的状态载荷）
    """
    try:
        status_payload = get_material_sync_status()
    except OSError as exc:
        _raise_material_sync_error(
            event="material_sync_status_failed",
            exc=exc,
            status_code=500,
            detail=MATERIAL_SYNC_STATUS_UNAVAILABLE_DETAIL,
        )
    response = MaterialSyncStatusResponse(
        status="ok",
        message="Material sync status loaded",
        **status_payload,
    )
    log.info(
        "Material sync status loaded",
        extra={
            "event": "material_sync_status_done",
            "index_state": response.index_state,
            "installed_count": response.installed_count,
        },
    )
    return response


@router.get("/catalog", response_model=MaterialRegistryCatalogResponse)
async def material_sync_catalog(
    q: str | None = Query(default=None, max_length=200),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> MaterialRegistryCatalogResponse:
    """Return the configured remote Registry catalog without installing.
    返回已配置远程 Registry catalog，不安装耗材。
    """
    try:
        catalog = await asyncio.to_thread(
            list_material_registry_catalog, query=q, limit=limit, offset=offset
        )
    except ValueError as exc:
        _raise_material_sync_error(
            event="material_sync_catalog_failed",
            exc=exc,
            status_code=422,
            detail=_catalog_value_error_detail(exc),
        )
    except RegistryCatalogNotFoundError as exc:
        _raise_material_sync_error(
            event="material_sync_catalog_failed",
            exc=exc,
            status_code=502,
            detail=(
                "Material Registry catalog endpoint was not found (HTTP 404). "
                "Check LUMINA_MATERIAL_REGISTRY_URL and use a Registry service "
                "that provides /materials/catalog."
            ),
        )
    except RuntimeError as exc:
        _raise_material_sync_error(
            event="material_sync_catalog_failed",
            exc=exc,
            status_code=502,
            detail=MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL,
        )
    except FileNotFoundError as exc:
        _raise_material_sync_error(
            event="material_sync_catalog_failed",
            exc=exc,
            status_code=502,
            detail=MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL,
        )
    except OSError as exc:
        _raise_material_sync_error(
            event="material_sync_catalog_failed",
            exc=exc,
            status_code=500,
            detail=MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL,
        )

    response = MaterialRegistryCatalogResponse(**catalog)
    log.info(
        "Material registry catalog fetched for library",
        extra={
            "event": "material_sync_catalog_done",
            "channels": response.channels,
            "material_count": response.count,
            "total_count": response.total_count,
            "offset": response.offset,
            "limit": response.limit,
            "query": q,
        },
    )
    return response


@router.post("/install", response_model=MaterialSyncInstallResponse)
async def material_sync_install(
    archive: UploadFile = File(...),
) -> MaterialSyncInstallResponse:
    """Install one uploaded material package into the local material library.
    将上传的耗材包安装到本地耗材库。

    Args:
        archive: ZIP package produced by material export/registry download.
            （由耗材导出或 Registry 下载得到的 ZIP 包）

    Returns:
        MaterialSyncInstallResponse: Installed material summaries.
            （已安装耗材摘要）
    """
    filename = archive.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=422,
            detail=f"Uploaded file must be a ZIP archive: {filename or '<unnamed>'}",
        )
    archive_path: str | None = None
    try:
        archive_path = await upload_to_tempfile(
            archive,
            suffix=".zip",
            max_bytes=material_package_max_archive_bytes(),
        )
        result = import_saved_stage_a_material_archives(archive_path=archive_path)
    except FileNotFoundError as exc:
        _raise_material_sync_error(
            event="material_sync_install_failed",
            exc=exc,
            status_code=404,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        )
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except OSError as exc:
        _raise_material_sync_error(
            event="material_sync_install_failed",
            exc=exc,
            status_code=422,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        )
    except RuntimeError as exc:
        _raise_material_sync_error(
            event="material_sync_install_failed",
            exc=exc,
            status_code=422,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        )
    except (ValueError, TypeError) as exc:
        _raise_material_sync_error(
            event="material_sync_install_failed",
            exc=exc,
            status_code=422,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        )
    finally:
        if archive_path is not None:
            try:
                os.remove(archive_path)
            except OSError:
                pass

    log.info(
        "Material package installed",
        extra={
            "event": "material_sync_install_done",
            "installed_count": len(result.imported_materials),
        },
    )
    return MaterialSyncInstallResponse(
        status="ok",
        message=f"Installed {len(result.imported_materials)} material packages",
        installed_count=len(result.imported_materials),
        installed_materials=[
            public_material_response_item(item) for item in result.imported_materials
        ],
    )


@router.post("/install-from-registry", response_model=MaterialSyncInstallResponse)
async def material_sync_install_from_registry(
    payload: MaterialRegistryInstallRequest,
) -> MaterialSyncInstallResponse:
    """Install one selected remote Registry package into the local library.
    将用户选中的单个远程 Registry 耗材包安装到本地耗材库。
    """
    try:
        catalog = await asyncio.to_thread(list_material_registry_catalog)
        catalog_entry = _select_catalog_install_entry(catalog, payload)
    except ValueError as exc:
        _raise_material_sync_error(
            event="material_sync_install_from_registry_failed",
            exc=exc,
            status_code=422,
            detail=_material_sync_value_error_detail(
                exc,
                fallback=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
            ),
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except RuntimeError as exc:
        _raise_material_sync_error(
            event="material_sync_install_from_registry_failed",
            exc=exc,
            status_code=502,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except FileNotFoundError as exc:
        _raise_material_sync_error(
            event="material_sync_install_from_registry_failed",
            exc=exc,
            status_code=502,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except OSError as exc:
        _raise_material_sync_error(
            event="material_sync_install_from_registry_failed",
            exc=exc,
            status_code=500,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )

    try:
        result = await asyncio.to_thread(
            install_material_registry_package,
            package_url=str(catalog_entry.get("package_url") or ""),
            package_sha256=str(catalog_entry.get("package_sha256") or ""),
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except (ValueError, TypeError) as exc:
        _raise_material_sync_error(
            event="material_sync_install_from_registry_failed",
            exc=exc,
            status_code=502,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except RuntimeError as exc:
        _raise_material_sync_error(
            event="material_sync_install_from_registry_failed",
            exc=exc,
            status_code=502,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except FileNotFoundError as exc:
        _raise_material_sync_error(
            event="material_sync_install_from_registry_failed",
            exc=exc,
            status_code=502,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except OSError as exc:
        _raise_material_sync_error(
            event="material_sync_install_from_registry_failed",
            exc=exc,
            status_code=500,
            detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )

    installed_materials = result["installed_materials"]
    log.info(
        "Material registry package installed from catalog",
        extra={
            "event": "material_sync_install_from_registry_done",
            "material_id": result["material_id"],
            "revision_id": result["revision_id"],
            "installed_count": len(installed_materials),
        },
    )
    return MaterialSyncInstallResponse(
        status="ok",
        message=f"Installed {len(installed_materials)} material packages",
        installed_count=len(installed_materials),
        installed_materials=[
            public_material_response_item(item)
            for item in installed_materials
            if isinstance(item, dict)
        ],
    )


@router.post("/refresh", response_model=MaterialSyncRefreshResponse)
async def material_sync_refresh(
) -> MaterialSyncRefreshResponse:
    """Pull read-only material package updates from the configured Registry.
    从已配置 Registry 只读拉取耗材包更新。

    Returns:
        MaterialSyncRefreshResponse: Refresh summary and per-package failures.
            （刷新摘要与包级失败明细）
    """
    try:
        result = await asyncio.to_thread(refresh_material_sync_from_registry)
    except ValueError as exc:
        _raise_material_sync_error(
            event="material_sync_refresh_failed",
            exc=exc,
            status_code=422,
            detail=_material_sync_value_error_detail(
                exc,
                fallback=MATERIAL_SYNC_REFRESH_UNAVAILABLE_DETAIL,
            ),
        )
    except RuntimeError as exc:
        _raise_material_sync_error(
            event="material_sync_refresh_failed",
            exc=exc,
            status_code=502,
            detail=MATERIAL_SYNC_REFRESH_UNAVAILABLE_DETAIL,
        )
    except OSError as exc:
        _raise_material_sync_error(
            event="material_sync_refresh_failed",
            exc=exc,
            status_code=500,
            detail=MATERIAL_SYNC_REFRESH_UNAVAILABLE_DETAIL,
        )

    log.info(
        "Material registry refresh completed",
        extra={
            "event": "material_sync_refresh_done",
            "registry_url": result["registry_url"],
            "channels": result["channels"],
            "checked_count": result["checked_count"],
            "installed_count": result["installed_count"],
            "skipped_count": result["skipped_count"],
            "failed_count": result["failed_count"],
            "catalog_not_modified": bool(
                result.get("catalog_not_modified", False)
            ),
        },
    )
    return MaterialSyncRefreshResponse(
        status="ok" if int(result["failed_count"]) == 0 else "partial",
        message=(
            f"Installed {result['installed_count']} material packages; "
            f"skipped {result['skipped_count']}; failed {result['failed_count']}"
        ),
        registry_url=str(result["registry_url"]),
        channels=list(result["channels"]),
        checked_count=int(result["checked_count"]),
        installed_count=int(result["installed_count"]),
        skipped_count=int(result["skipped_count"]),
        failed_count=int(result["failed_count"]),
        installed_materials=[
            public_material_response_item(item)
            for item in list(result.get("installed_materials") or [])
            if isinstance(item, dict)
        ],
        failures=list(result.get("failures") or []),
    )


@router.post("/rollback", response_model=MaterialSyncRollbackResponse)
async def material_sync_rollback(
    payload: MaterialSyncRollbackRequest,
) -> MaterialSyncRollbackResponse:
    """Rollback one synced material to a previously installed revision.
    将一个已同步耗材回滚到历史 revision。
    """
    try:
        result = rollback_material_sync_revision(
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except FileNotFoundError as exc:
        _raise_material_sync_error(
            event="material_sync_rollback_failed",
            exc=exc,
            status_code=404,
            detail=MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL,
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except ValueError as exc:
        _raise_material_sync_error(
            event="material_sync_rollback_failed",
            exc=exc,
            status_code=422,
            detail=MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL,
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )
    except OSError as exc:
        _raise_material_sync_error(
            event="material_sync_rollback_failed",
            exc=exc,
            status_code=500,
            detail=MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL,
            material_id=payload.material_id,
            revision_id=payload.revision_id,
        )

    log.info(
        "Material sync rollback completed",
        extra={
            "event": "material_sync_rollback_done",
            "material_id": result["material_id"],
            "revision_id": result["revision_id"],
            "channel": result["channel"],
        },
    )
    return MaterialSyncRollbackResponse(
        status="ok",
        message=f"Rolled back {result['material_id']} to {result['revision_id']}",
        **result,
    )
