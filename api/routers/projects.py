"""Data-only resources used by portable projects."""
from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError

from api.colorchecker_artifacts import COLORCHECKER_FULL_PURPOSE, resolve_colorchecker_full_path
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.project_resources import _read_resource
from api.project_workflows import pack_workflow_session, unpack_workflow_session
from api.session_store import SessionStore
from config import TEMP_DIR
from core.projects.dependencies import unpack_lut_source

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/templates/{template_id}")
def capture_template(template_id: str):
    from core.custom_3mf_templates import load_template
    try:
        return load_template(template_id)
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(404, "The project's custom 3MF template is unavailable") from exc


@router.post("/templates")
async def restore_template(template: UploadFile = File(...), store: SessionStore = Depends(get_session_store)):
    from uuid import uuid4
    from config import SUPPORTED_SLICERS
    from core.custom_3mf_templates import _path
    data = await template.read(4 * 1024 * 1024 + 1)
    try:
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("Template too large")
        settings = json.loads(data)
        if not isinstance(settings, dict) or settings.get("_lumina_template_slicer") not in {item["id"] for item in SUPPORTED_SLICERS}:
            raise ValueError("Invalid template slicer")
        payload = json.dumps({"metadata": {"slicer": settings["_lumina_template_slicer"]}, "settings": settings}, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Invalid project 3MF template") from exc
    template_id = "project:" + uuid4().hex
    target = _path(template_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    session_id = store.create()
    store.register_temp_file(session_id, str(target))
    return {"template_id": template_id, "session_id": session_id}


@router.post("/revisions")
async def freeze_revision(project: UploadFile = File(...), registry: FileRegistry = Depends(get_file_registry)):
    from core.projects import read_project
    from core.projects.errors import ProjectError
    data = await _read_resource(project)
    try:
        snapshot = read_project(data)
    except (ValueError, ProjectError) as exc:
        raise HTTPException(422, "Invalid project revision") from exc
    file_id = registry.register_bytes("", data, "revision.lum", ttl_seconds=8 * 60 * 60, is_public=False, purpose="project_revision")
    return {"file_id": file_id, "project_id": snapshot.project_id, "revision_id": snapshot.revision_id}


@router.get("/workflows/{kind}/{session_id}")
def capture_workflow(kind: str, session_id: str, store: SessionStore = Depends(get_session_store)):
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, "Workflow session has expired")
    try:
        return Response(pack_workflow_session(kind, session), media_type="application/zip")
    except (ValueError, OSError) as exc:
        raise HTTPException(422, "Could not capture this workflow checkpoint") from exc


@router.post("/workflows/{kind}")
async def restore_workflow(kind: str, checkpoint: UploadFile = File(...), store: SessionStore = Depends(get_session_store), registry: FileRegistry = Depends(get_file_registry)):
    root = Path(tempfile.mkdtemp(prefix="project_workflow_", dir=TEMP_DIR))
    session_id = None
    download_ids: list[str] = []
    try:
        try:
            state = unpack_workflow_session(kind, await _read_resource(checkpoint), root)
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, "Invalid workflow checkpoint") from exc
        session_id = store.create()
        store.register_temp_file(session_id, str(root))
        for key, value in state.items():
            store.put(session_id, key, value)
        urls = {}
        for key in ("lut_path", "single_stage_stage_json_path", "stage_a_params_path"):
            if state.get(key):
                path = Path(state[key])
                # Downloads outlive the editable checkpoint and keep its saved bytes.
                file_id = registry.register_bytes(
                    f"project-workflow:{session_id}", path.read_bytes(), path.name,
                    ttl_seconds=8 * 60 * 60,
                )
                download_ids.append(file_id)
                urls[key] = f"/api/files/{file_id}"
        return {"session_id": session_id, "urls": urls}
    except BaseException:
        for file_id in download_ids:
            registry.cleanup_file(file_id)
        if session_id:
            registry.cleanup_session(session_id)
            store.close(session_id)
        shutil.rmtree(root, ignore_errors=True)
        raise


@router.post("/lut-context")
async def restore_lut_context(names: str = Form(...), files: list[UploadFile] = File(...), store: SessionStore = Depends(get_session_store)):
    root = Path(tempfile.mkdtemp(prefix="project_luts_", dir=TEMP_DIR))
    try:
        labels = json.loads(names)
        if not isinstance(labels, list) or len(labels) != len(files) or len(labels) > 64 or any(not isinstance(label, str) or not label or len(label) > 512 for label in labels) or len(set(labels)) != len(labels):
            raise ValueError("Invalid project LUT names")
        luts = {}
        total = 0
        for index, (label, upload) in enumerate(zip(labels, files)):
            data = await _read_resource(upload)
            total += len(data)
            if total > 512 * 1024 * 1024:
                raise ValueError("Project LUTs exceed their size limit")
            luts[label] = unpack_lut_source(data, root / str(index))
        session_id = store.create()
        store.register_temp_file(session_id, str(root))
        store.put(session_id, "project_luts", luts)
        return {"session_id": session_id}
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(422, "Invalid project LUT resources") from exc
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


@router.get("/colorchecker/{file_id}")
def capture_colorchecker(file_id: str, registry: FileRegistry = Depends(get_file_registry)):
    path = resolve_colorchecker_full_path(registry, file_id)
    return Response(Path(path).read_bytes(), media_type="image/png")


@router.post("/colorchecker")
async def restore_colorchecker(image: UploadFile = File(...), registry: FileRegistry = Depends(get_file_registry)):
    data = await _read_resource(image)
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format != "PNG" or source.width * source.height > 100_000_000:
                raise ValueError("Invalid calibrated image")
            source.verify()
        file_id = registry.register_bytes("", data, "calibrated.png", ttl_seconds=8 * 60 * 60, is_public=False, purpose=COLORCHECKER_FULL_PURPOSE)
        return {"file_id": file_id}
    except (ValueError, OSError, UnidentifiedImageError) as exc:
        raise HTTPException(422, "Invalid calibrated image") from exc
