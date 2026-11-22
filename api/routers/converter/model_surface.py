from __future__ import annotations

from dataclasses import asdict
import json
import os
import tempfile
from threading import Lock
import uuid
from pathlib import Path

import anyio
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.routers.converter.common import public_model_surface_error_detail
from api.schemas.model_surface import (
    ModelSurfaceSelectRequest,
    ModelSurfaceSelectResponse,
    ModelSurfaceUploadResponse,
)
from api.structured_logging import get_logger
from config import TEMP_DIR
from core.model_surface.artwork import render_surface_artwork
from core.model_surface.footprint import build_surface_footprint
from core.model_surface.loader import load_model_surface_mesh
from core.model_surface.selection import (
    face_index_from_surface_candidate_id,
    list_planar_surface_candidates,
    select_planar_component,
)
from core.model_surface.serialization import (
    surface_placement_from_payload,
)
from core.model_surface.types import ModelSurfaceError
from core.model_surface.types import SurfaceCandidate, SurfaceFootprint, SurfaceSelection
from core.model_surface.validation import (
    MODEL_SURFACE_INVALID_FILE,
    validate_model_surface_mesh_for_boolean,
)

router = APIRouter(prefix="/model-surface")
log = get_logger(__name__)
_SUPPORTED_MODEL_EXTENSIONS = {".stl", ".obj"}
_MODEL_SURFACE_FILE_TTL_SECONDS = 3600
_MODEL_SURFACE_UPLOAD_LIMIT_BYTES = 256 * 1024 * 1024
_MODEL_SURFACE_UPLOAD_CHUNK_BYTES = 1024 * 1024
_SURFACE_CANDIDATE_CACHE_LIMIT = 128
_SURFACE_CANDIDATE_CACHE_LOCK = Lock()
_SURFACE_CANDIDATE_CACHE: dict[str, tuple[str, tuple[SurfaceCandidate, ...]]] = {}
_SURFACE_SELECTION_CACHE: dict[
    tuple[str, tuple[int, ...]],
    tuple[str, SurfaceFootprint],
] = {}


@router.post("/upload", response_model=ModelSurfaceUploadResponse)
async def upload_model_surface(
    model: UploadFile = File(...),
    registry: FileRegistry = Depends(get_file_registry),
) -> ModelSurfaceUploadResponse:
    """Upload an STL/OBJ model for surface-overlay selection.

    上传用于覆面选区的 STL/OBJ 模型。
    """

    suffix = Path(model.filename or "").suffix.lower()
    if suffix not in _SUPPORTED_MODEL_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail="Only STL and OBJ model files are supported.",
        )

    fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
    os.close(fd)
    registered = False
    try:
        total_bytes = 0
        with open(temp_path, "wb") as handle:
            while True:
                chunk = await model.read(_MODEL_SURFACE_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > _MODEL_SURFACE_UPLOAD_LIMIT_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Model file exceeds the 256 MB upload limit.",
                    )
                handle.write(chunk)
        loaded, surface_candidates = await anyio.to_thread.run_sync(
            _analyze_uploaded_model_surface,
            temp_path,
        )
        validate_model_surface_mesh_for_boolean(loaded.mesh)
        file_id = registry.register_path(
            session_id=f"model-surface-{uuid.uuid4()}",
            path=temp_path,
            filename=model.filename or f"model{suffix}",
            ttl_seconds=_MODEL_SURFACE_FILE_TTL_SECONDS,
            is_public=False,
            purpose="model_surface_source",
        )
        _cache_surface_candidates(file_id, temp_path, surface_candidates)
        registered = True
    except ModelSurfaceError as exc:
        detail = public_model_surface_error_detail(exc)
        if detail is None:
            detail = public_model_surface_error_detail(MODEL_SURFACE_INVALID_FILE)
        raise HTTPException(
            status_code=422,
            detail=detail,
        ) from exc
    finally:
        if not registered:
            Path(temp_path).unlink(missing_ok=True)

    warnings = [loaded.summary.unit_warning] if loaded.summary.unit_warning else []
    log.info(
        "Model surface source uploaded",
        extra={
            "event": "model_surface_upload_done",
            "model_file_id": file_id,
            "upload_filename": model.filename or "",
            "vertex_count": loaded.summary.vertex_count,
            "face_count": loaded.summary.face_count,
            "surface_candidate_count": len(surface_candidates),
            "warning_count": len(warnings),
        },
    )
    return ModelSurfaceUploadResponse(
        status="ok",
        model_file_id=file_id,
        summary=loaded.summary.to_public_dict(),
        surface_candidates=[
            _surface_candidate_to_public_dict(candidate)
            for candidate in surface_candidates
        ],
        warnings=warnings,
    )


def _analyze_uploaded_model_surface(temp_path: str):
    loaded = load_model_surface_mesh(temp_path)
    return loaded, list_planar_surface_candidates(loaded.mesh)


@router.post("/select", response_model=ModelSurfaceSelectResponse)
def select_model_surface(
    request: ModelSurfaceSelectRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> ModelSurfaceSelectResponse:
    """Select a connected planar face area on an uploaded model.

    在已上传模型上选择连通平面区域。
    """

    resolved = registry.resolve(request.model_file_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Uploaded model file is unavailable.")
    model_path, _filename = resolved

    try:
        if request.hit.candidate_id:
            candidate = _resolve_cached_surface_candidate(
                model_file_id=request.model_file_id,
                model_path=model_path,
                candidate_id=request.hit.candidate_id,
            )
            if candidate is None:
                loaded = load_model_surface_mesh(model_path)
                candidate = _resolve_surface_candidate(
                    model_file_id=request.model_file_id,
                    model_path=model_path,
                    candidate_id=request.hit.candidate_id,
                    loaded_mesh=loaded.mesh,
                )
            selection = _selection_from_candidate(candidate)
            footprint = candidate.footprint
        else:
            loaded = load_model_surface_mesh(model_path)
            face_index = request.hit.face_index
            if face_index is None:
                raise ModelSurfaceError(
                    "A face_index is required for model-surface selection."
                )
            selection = select_planar_component(loaded.mesh, int(face_index))
            footprint = build_surface_footprint(loaded.mesh, selection.face_indices)
    except ModelSurfaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    selection_id = str(uuid.uuid4())
    _cache_surface_selection(
        model_file_id=request.model_file_id,
        model_path=model_path,
        face_indices=selection.face_indices,
        footprint=footprint,
    )
    log.info(
        "Model surface selected",
        extra={
            "event": "model_surface_select_done",
            "model_file_id": request.model_file_id,
            "selection_id": selection_id,
            "face_count": selection.face_count,
            "area_mm2": round(float(selection.area_mm2), 6),
            "footprint_hole_count": footprint.hole_count,
        },
    )
    return ModelSurfaceSelectResponse(
        status="ok",
        selection_id=selection_id,
        selection=asdict(selection),
        footprint=asdict(footprint),
        warnings=[],
    )


def _surface_candidate_to_public_dict(candidate) -> dict:
    payload = asdict(candidate)
    payload.pop("face_indices", None)
    return payload


def _cache_surface_candidates(
    model_file_id: str,
    model_path: str,
    candidates: tuple[SurfaceCandidate, ...],
) -> None:
    with _SURFACE_CANDIDATE_CACHE_LOCK:
        _SURFACE_CANDIDATE_CACHE[model_file_id] = (str(model_path), candidates)
        while len(_SURFACE_CANDIDATE_CACHE) > _SURFACE_CANDIDATE_CACHE_LIMIT:
            oldest_key = next(iter(_SURFACE_CANDIDATE_CACHE))
            _SURFACE_CANDIDATE_CACHE.pop(oldest_key, None)
            stale_selection_keys = [
                key for key in _SURFACE_SELECTION_CACHE if key[0] == oldest_key
            ]
            for key in stale_selection_keys:
                _SURFACE_SELECTION_CACHE.pop(key, None)


def _cache_surface_selection(
    *,
    model_file_id: str,
    model_path: str,
    face_indices: tuple[int, ...],
    footprint: SurfaceFootprint,
) -> None:
    with _SURFACE_CANDIDATE_CACHE_LOCK:
        _SURFACE_SELECTION_CACHE[(model_file_id, face_indices)] = (
            str(model_path),
            footprint,
        )


def _resolve_surface_candidate(
    *,
    model_file_id: str,
    model_path: str,
    candidate_id: str,
    loaded_mesh,
) -> SurfaceCandidate:
    face_index_from_surface_candidate_id(candidate_id)
    candidates = _get_cached_surface_candidates(model_file_id, model_path)
    if candidates is None:
        candidates = list_planar_surface_candidates(loaded_mesh)
        _cache_surface_candidates(model_file_id, model_path, candidates)
    for candidate in candidates:
        if candidate.id == candidate_id:
            return candidate
    raise ModelSurfaceError("Selected surface candidate is unavailable.")


def _resolve_cached_surface_candidate(
    *,
    model_file_id: str,
    model_path: str,
    candidate_id: str,
) -> SurfaceCandidate | None:
    face_index_from_surface_candidate_id(candidate_id)
    candidates = _get_cached_surface_candidates(model_file_id, model_path)
    if candidates is None:
        return None
    for candidate in candidates:
        if candidate.id == candidate_id:
            return candidate
    raise ModelSurfaceError("Selected surface candidate is unavailable.")


def _get_cached_surface_candidates(
    model_file_id: str,
    model_path: str,
) -> tuple[SurfaceCandidate, ...] | None:
    with _SURFACE_CANDIDATE_CACHE_LOCK:
        cached = _SURFACE_CANDIDATE_CACHE.get(model_file_id)
    if cached is None:
        return None
    cached_path, candidates = cached
    if cached_path != str(model_path):
        return None
    return candidates


def _selection_from_candidate(candidate: SurfaceCandidate) -> SurfaceSelection:
    return SurfaceSelection(
        face_indices=candidate.face_indices,
        normal=candidate.normal,
        plane_origin=candidate.plane_origin,
        area_mm2=candidate.area_mm2,
        face_count=candidate.face_count,
    )


def resolve_surface_preview_config(
    *,
    registry: FileRegistry,
    model_file_id: str | None,
    selection_json: str | None,
    footprint_json: str | None,
    placement_json: str | None,
    source_path: str,
    transform_json: str | None = None,
) -> dict | None:
    """Resolve and render optional model-surface preview config.

    解析并渲染可选的模型覆面预览配置。
    """

    required_supplied = [model_file_id, selection_json, footprint_json, placement_json]
    supplied = [*required_supplied, transform_json]
    if not any(supplied):
        return None
    if not all(required_supplied):
        raise HTTPException(
            status_code=422,
            detail="Model surface preview requires model, selection, footprint, and placement.",
        )

    assert model_file_id is not None
    resolved = registry.resolve(model_file_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Uploaded model file is unavailable.")
    model_path, _filename = resolved

    try:
        selection_payload = _loads_object(selection_json)
        _loads_object(footprint_json)
        placement_payload = _loads_object(placement_json)
        transform_payload = (
            _surface_model_transform_from_payload(_loads_object(transform_json))
            if transform_json
            else _default_surface_model_transform()
        )
        footprint = _canonical_surface_footprint(
            model_file_id=model_file_id,
            model_path=model_path,
            selection_payload=selection_payload,
        )
        placement = surface_placement_from_payload(placement_payload)
        rendered = render_surface_artwork(
            source_path=source_path,
            footprint=footprint,
            placement=placement,
            output_dir=TEMP_DIR,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ModelSurfaceError) as exc:
        raise HTTPException(
            status_code=422,
            detail=public_model_surface_error_detail(exc)
            or f"Invalid model surface preview configuration: {exc}",
        ) from exc

    placement_public = asdict(placement)
    placement_public["mode"] = placement.mode.value
    return {
        "surface_model_file_id": model_file_id,
        "surface_model_path": model_path,
        "surface_selection": selection_payload,
        "surface_footprint": asdict(footprint),
        "surface_placement": placement_public,
        "surface_model_transform": transform_payload,
        "surface_artwork_path": str(rendered.output_path),
        "target_width_mm": rendered.target_width_mm,
        "target_height_mm": rendered.target_height_mm,
    }


def _canonical_surface_footprint(
    *,
    model_file_id: str,
    model_path: str,
    selection_payload: dict,
) -> SurfaceFootprint:
    raw_face_indices = selection_payload.get("face_indices")
    if not isinstance(raw_face_indices, list | tuple) or not raw_face_indices:
        raise ModelSurfaceError("Surface selection must contain face_indices.")
    if any(
        not isinstance(index, int) or isinstance(index, bool)
        for index in raw_face_indices
    ):
        raise ModelSurfaceError("Surface selection face_indices must be integers.")
    face_indices = tuple(raw_face_indices)
    if any(index < 0 for index in face_indices):
        raise ModelSurfaceError("Surface selection face_indices must be non-negative.")

    with _SURFACE_CANDIDATE_CACHE_LOCK:
        cached = _SURFACE_SELECTION_CACHE.get((model_file_id, face_indices))
    if cached is None or cached[0] != str(model_path):
        raise ModelSurfaceError(
            "Surface selection does not belong to the uploaded model."
        )
    return cached[1]


def _loads_object(raw: str | None) -> dict:
    if raw is None:
        raise ValueError("missing JSON payload")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def _default_surface_model_transform() -> dict:
    return {"rotation_deg": {"x": 0.0, "y": 0.0, "z": 0.0}}


def _surface_model_transform_from_payload(payload: dict) -> dict:
    rotation = payload.get("rotation_deg", {})
    if not isinstance(rotation, dict):
        raise ValueError("rotation_deg must be a JSON object")
    normalized: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        raw_value = rotation.get(axis, 0.0)
        try:
            normalized[axis] = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"rotation_deg.{axis} must be a number") from exc
    return {"rotation_deg": normalized}
