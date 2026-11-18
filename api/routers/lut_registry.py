"""Lumina Studio API — Cloud LUT Registry Router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.lut_seed import add_matching_seed_previews
from api.services.lut_registry_sync import (
    LutRegistryConfigError,
    LutRegistryError,
    LutRegistryPackageError,
    LutRegistryRemoteError,
    fetch_remote_catalog,
    install_lut_package,
    registry_status,
    restore_lut_revision,
)
from api.routers.lut import invalidate_lut_details_service_cache
from api.structured_logging import get_logger
from api.services.resource_contribution import connection

router = APIRouter(prefix="/api/lut-registry", tags=["LUT Registry"])
log = get_logger(__name__)


class LutRegistryInstallRequest(BaseModel):
    """Request body for installing one server-resolved cloud LUT revision."""

    lut_id: str = Field(..., min_length=1)
    revision_id: str = Field(..., min_length=1)
    channels: list[str] | None = None
    account_id: str | None = Field(default=None, max_length=200)


class LutRegistryRestoreRequest(BaseModel):
    lut_id: str = Field(..., min_length=1, max_length=500)
    revision_id: str = Field(..., min_length=1, max_length=500)


def _to_http_exception(exc: LutRegistryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/catalog")
def catalog(
    channel: list[str] | None = Query(default=None),
    limit: int = Query(default=200, ge=1),
    offset: int = Query(default=0, ge=0),
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    """Return the remote LUT catalog for configured or requested channels."""

    try:
        return add_matching_seed_previews(fetch_remote_catalog(
            channels=channel, limit=limit, offset=offset, **({"refresh": True} if refresh else {}),
        ))
    except LutRegistryError as exc:
        raise _to_http_exception(exc) from exc


@router.post("/install")
def install(request: LutRegistryInstallRequest) -> dict[str, Any]:
    """Install one cloud LUT package resolved from the server-side catalog."""

    try:
        record = install_lut_package(
            lut_id=request.lut_id,
            revision_id=request.revision_id,
            channels=request.channels,
        )
        invalidate_lut_details_service_cache()
    except (LutRegistryConfigError, LutRegistryRemoteError, LutRegistryPackageError) as exc:
        raise _to_http_exception(exc) from exc

    log.info(
        "Cloud LUT installed",
        extra={
            "event": "lut_registry_install_done",
            "lut_id": record.get("lut_id"),
            "revision_id": record.get("revision_id"),
            "content_hash": record.get("content_hash"),
        },
    )
    return {**record, "activity_recorded": connection.record_download("luts", record, request.account_id)}


@router.get("/previews")
def previews(
    lut_id: list[str] = Query(min_length=1, max_length=24),
    channel: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    """Fetch only the authorized catalog artwork for the displayed page."""
    try:
        return fetch_remote_catalog(channels=channel, preview_ids=lut_id, limit=len(lut_id))
    except LutRegistryError as exc:
        raise _to_http_exception(exc) from exc


@router.post("/restore")
def restore(request: LutRegistryRestoreRequest) -> dict[str, Any]:
    try:
        record = restore_lut_revision(lut_id=request.lut_id, revision_id=request.revision_id)
        invalidate_lut_details_service_cache()
    except LutRegistryError as exc:
        raise _to_http_exception(exc) from exc
    log.info("Local LUT revision restored", extra={
        "event": "lut_registry_restore_done", "lut_id": request.lut_id, "revision_id": request.revision_id,
    })
    return record


@router.get("/status")
def status() -> dict[str, Any]:
    """Return local cloud LUT registry sync status."""

    return registry_status()
