"""Native material and build-plate preflight API."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Mapping

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_session_store
from api.errors import to_http_exception
from api.export_device_validation import validate_export_device_selection
from api.schemas.converter import ConvertGenerateRequest
from api.session_store import SessionStore
from api.project_resources import stage_project_resources, discard_project_resources
from api.preview_cache_artifacts import get_preview_cache_metadata
from api.recipe_override_resolution import resolve_recipe_overrides
from core.errors import CoreValidationError
from core.export_material_selection import (
    require_export_material_selection,
    resolve_export_material_selection,
)
from .common import _require_session

router = APIRouter()


class ExportMaterialsParams(ConvertGenerateRequest):
    material_source: Literal["lut", "material_archive"] = "lut"
    selected_materials: list[str] = Field(default_factory=list)


class ExportMaterialsRequest(BaseModel):
    session_id: str | None = None
    params: ExportMaterialsParams


@router.post("/project-export-materials")
async def resolve_project_export_materials(
    request_json: Annotated[str, Form()],
    project_lut: Annotated[UploadFile | None, File()] = None,
    project_materials: Annotated[UploadFile | None, File()] = None,
) -> dict:
    """Use project-owned inputs for batch material preflight without a session."""
    from pydantic import ValidationError

    resources = None
    try:
        request = ExportMaterialsRequest.model_validate_json(request_json)
        params = request.params.model_dump(mode="json")
        resources = await stage_project_resources(project_lut, project_materials, request.params.selected_materials)
        if resources:
            params["lut_path"] = resources.lut_path
            params["materials_dir"] = resources.materials_dir
        return resolve_export_material_selection(params)
    except CoreValidationError as exc:
        raise to_http_exception(exc, "Native material selection") from exc
    except (ValidationError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        discard_project_resources(resources)


def _material_source_context(
    session: Mapping[str, Any] | None, request: ConvertGenerateRequest,
) -> dict[str, Any] | None:
    if session is None:
        return None
    cache = get_preview_cache_metadata(dict(session.get("preview_cache") or {}))
    return {
        "material_source": session.get("material_source", "lut"),
        "selected_materials": session.get("selected_materials") or [],
        "materials_dir": session.get("project_materials_dir"),
        "lut_path": session.get("lut_path"),
        "lut_metadata": cache.get("lut_metadata"),
        "slot_names": cache.get("slot_names"),
        "preview_colors": cache.get("preview_colors"),
        "color_conf": cache.get("color_conf"),
        "recipe_overrides": resolve_recipe_overrides(dict(session), request),
    }


def require_material_selection(
    request: ConvertGenerateRequest | Mapping[str, Any],
    session_data: dict | None = None,
) -> dict[str, Any]:
    """Enforce the same native choices for API clients before generation.

    在生成前为所有 API 调用方执行同一原生材料选择校验。
    """
    try:
        params = (
            request.model_dump(mode="json")
            if isinstance(request, ConvertGenerateRequest) else request
        )
        selection_request = (
            request if isinstance(request, ConvertGenerateRequest)
            else ConvertGenerateRequest.model_validate(params)
        )
        source_context = _material_source_context(session_data, selection_request)
        return require_export_material_selection(params, source_context=source_context)
    except CoreValidationError as exc:
        raise to_http_exception(exc, "Native material selection") from exc
    except (ValueError, FileNotFoundError) as exc:
        raise to_http_exception(
            CoreValidationError(str(exc)), "Native material selection",
        ) from exc


@router.post("/export-materials")
def resolve_export_materials(
    body: ExportMaterialsRequest, store: SessionStore = Depends(get_session_store),
) -> dict:
    """Return native choices and compatible plates for the actual generation input.

    返回实际生成输入对应的原生耗材候选和共同兼容打印板。
    """
    request = body.params
    validate_export_device_selection(
        printer_id=request.printer_id, slicer=request.slicer,
        nozzle_size=request.nozzle_size, device_profile_id=request.device_profile_id,
        build_plate_id=request.build_plate_id,
        custom_3mf_template_id=request.custom_3mf_template_id,
        supports_custom_template=True,
    )
    session = _require_session(store, body.session_id) if body.session_id else None
    try:
        return resolve_export_material_selection(
            request.model_dump(mode="json"),
            source_context=_material_source_context(session, request),
        )
    except CoreValidationError as exc:
        raise to_http_exception(exc, "Native material selection") from exc
    except (ValueError, FileNotFoundError) as exc:
        raise to_http_exception(
            CoreValidationError(str(exc)), "Native material selection",
        ) from exc
