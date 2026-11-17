"""Browse locally packaged public resources and install a selected revision."""

import zipfile
import httpx
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.lut_seed import install_lut_seed_revision, lut_seed_catalog, lut_seed_status, restore_lut_seed
from api.material_seed import (
    install_material_seed_revision, material_seed_catalog, material_seed_status, restore_material_seed,
)
from api.routers.lut import invalidate_lut_details_service_cache
from api.structured_logging import get_logger
from api.routers.contributions import local_client
from core.public_resources import default_registry_url, is_static_catalog, lut_registry_url, material_registry_url, resource_provider
from core.resource_sources import save_source_preferences, source_settings_status
from core.resource_seed import SeedBusyError

router = APIRouter(prefix="/api/resources", tags=["Resources"])
log = get_logger(__name__)
ResourceKind = Literal["materials", "luts"]


class OfflineInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resource_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)


@contextmanager
def _resource_errors(kind: ResourceKind, action: str) -> Iterator[None]:
    try:
        yield
    except SeedBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        # The material and LUT registry installers also hold exclusive writer locks.
        if isinstance(exc.__cause__, FileExistsError):
            raise HTTPException(status_code=409, detail="Another resource installation is in progress") from exc
        log.warning("Offline resource operation failed", extra={
            "event": "resource_seed_operation_failed", "resource_kind": kind, "operation": action,
            "error_type": type(exc).__name__, "error_message": str(exc),
        })
        raise HTTPException(status_code=422, detail="Verify the offline resource collection and try again.") from exc


@router.get("/status")
def resource_status() -> dict[str, Any]:
    return {
        "materials": {"configured": bool(material_registry_url()), "provider": resource_provider("MATERIAL"), "seed": material_seed_status()},
        "luts": {"configured": bool(lut_registry_url()), "provider": resource_provider("LUT"), "seed": lut_seed_status()},
        "source_repository": "https://github.com/lumina-layer-studio/Lumina-materials",
        "source_settings": {
            **source_settings_status(),
            "urls": {"materials": material_registry_url(), "luts": lut_registry_url()},
            "default_urls": {"materials": default_registry_url("MATERIAL"), "luts": default_registry_url("LUT")},
            "default_provider": "github" if is_static_catalog(default_registry_url("MATERIAL")) else "registry",
        },
    }


class SourceSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["default", "github", "mirror"]
    mirror_url: str = Field(default="", max_length=2048)


@router.put("/source", dependencies=[Depends(local_client)])
def change_resource_source(request: SourceSettingsRequest) -> dict[str, Any]:
    try:
        save_source_preferences(request.mode, request.mirror_url)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, "Resource source settings could not be saved. Check local storage and retry.") from exc
    return resource_status()


class SourceCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ResourceKind
    expected_url: str = Field(max_length=2048)


@router.post("/source/check", dependencies=[Depends(local_client)])
def check_resource_source(request: SourceCheckRequest) -> dict[str, Any]:
    from api.services.lut_registry_sync import LutRegistryError, fetch_remote_catalog
    from core.single_stage.material_registry_client import list_material_registry_catalog

    url = material_registry_url if request.kind == "materials" else lut_registry_url
    source = url()
    if source != request.expected_url:
        raise HTTPException(409, "The resource source changed. Reload the source settings and retry.")
    if not source:
        raise HTTPException(503, "The resource source is not configured.")
    try:
        result = (list_material_registry_catalog(limit=1, use_cache=False) if request.kind == "materials"
                  else fetch_remote_catalog(limit=1, refresh=True))
    except (LutRegistryError, httpx.HTTPError, ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(502, "The catalog could not be reached. Retry, choose another source or browse an offline pack.") from exc
    if source != url():
        raise HTTPException(409, "The resource source changed. Retry the check.")
    return {"sourceUrl": source, "state": "cached" if result.get("cached") else "ready", "fetchedAt": result.get("fetched_at")}


@router.get("/{kind}/catalog")
def catalog(kind: ResourceKind) -> dict[str, Any]:
    with _resource_errors(kind, "catalog"):
        return material_seed_catalog() if kind == "materials" else lut_seed_catalog()


@router.post("/{kind}/install")
def install(kind: ResourceKind, request: OfflineInstallRequest) -> dict[str, int]:
    with _resource_errors(kind, "install"):
        if kind == "materials":
            return install_material_seed_revision(request.resource_id, request.revision_id)
        result = install_lut_seed_revision(request.resource_id, request.revision_id)
        if result["installed_count"]:
            invalidate_lut_details_service_cache()
        return result


@router.post("/{kind}/restore")
def restore(kind: ResourceKind) -> dict[str, Any]:
    with _resource_errors(kind, "restore"):
        result = restore_material_seed() if kind == "materials" else restore_lut_seed()
        if kind == "luts":
            invalidate_lut_details_service_cache()
        return result
