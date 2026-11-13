"""Portable checkpoints for the editable extraction owners and scoped LUTs.

Only explicit JSON fields and data files cross this boundary. Runtime IDs and
server paths are reconstructed, never deserialized from a project.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import re
import zipfile

from fastapi import HTTPException

from api.dependencies import get_session_store
from api.session_store import SessionStore
from utils.lut_manager import LUTManager
from core.projects.dependencies import validate_npz_budget

MAX_CHECKPOINT_BYTES = 256 * 1024 * 1024
SESSION_FIELDS = {
    "extractor": {"color_mode", "page", "eight_color_full_export", "lut_metadata", "project_extractor_merged"},
    "single-stage": {
        "single_stage_dataset_summary", "single_stage_warnings", "stage_a_fit_summary",
        "gradient_card_stage_a_params", "gradient_card_fit_summary",
        "gradient_card_material_summary", "gradient_card_source_summary",
    },
}
FILE_FIELDS = {
    "extractor": {"lut_path"},
    "single-stage": {"single_stage_stage_json_path", "stage_a_params_path"},
}
PAGE_NAME = re.compile(r"temp_(?:5c_ext|8c(?:_full)?)_page_\d+\.json\Z")


def clean_json(value):
    if isinstance(value, dict):
        return {
            key: clean_json(item) for key, item in value.items()
            if not key.endswith(("_path", "_paths")) and key not in {"source_references", "path_hint"}
        }
    if isinstance(value, list):
        return [clean_json(item) for item in value]
    return value


def pack_workflow_session(kind: str, session: dict) -> bytes:
    if kind not in SESSION_FIELDS:
        raise ValueError("Unsupported checkpoint workflow")
    entries: dict[str, bytes] = {}
    fields = clean_json({key: session[key] for key in SESSION_FIELDS[kind] if key in session})
    files = {}
    for key in FILE_FIELDS[kind]:
        if session.get(key):
            path = Path(session[key])
            name = key + path.suffix.lower()
            entries[name] = path.read_bytes()
            files[key] = name
    pages = session.get("project_extractor_pages_dir")
    if kind == "extractor" and pages:
        for path in Path(pages).iterdir():
            if PAGE_NAME.fullmatch(path.name) and path.is_file():
                entries["pages/" + path.name] = path.read_bytes()
    entries["checkpoint.json"] = json.dumps({"version": 1, "kind": kind, "fields": fields, "files": files}, allow_nan=False).encode()
    if sum(map(len, entries.values())) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Workflow checkpoint is too large")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return output.getvalue()


def unpack_workflow_session(kind: str, data: bytes, root: Path) -> dict:
    if kind not in SESSION_FIELDS or len(data) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Invalid workflow checkpoint")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        items = archive.infolist()
        names = [item.filename for item in items]
        if len(names) > 256 or len(set(names)) != len(names) or sum(item.file_size for item in items) > MAX_CHECKPOINT_BYTES:
            raise ValueError("Workflow checkpoint exceeds its limits")
        if "checkpoint.json" not in names or archive.getinfo("checkpoint.json").file_size > 16 * 1024 * 1024:
            raise ValueError("Invalid workflow checkpoint header")
        header = json.loads(archive.read("checkpoint.json"))
        if header.get("version") != 1 or header.get("kind") != kind:
            raise ValueError("Unsupported workflow checkpoint")
        fields, files = header.get("fields"), header.get("files")
        if not isinstance(fields, dict) or not isinstance(files, dict) or set(fields) - SESSION_FIELDS[kind] or set(files) - FILE_FIELDS[kind]:
            raise ValueError("Invalid workflow checkpoint fields")
        session = clean_json(fields)
        allowed = {"checkpoint.json"}
        root.mkdir(parents=True, exist_ok=True)
        for key, name in files.items():
            if name not in {key + ext for ext in (".json", ".npz", ".npy")}:
                raise ValueError("Invalid workflow checkpoint filename")
            path = root / name
            content = archive.read(name)
            if path.suffix == ".npz":
                validate_npz_budget(content)
            path.write_bytes(content)
            if key == "lut_path":
                LUTManager.load_lut_with_metadata(str(path))
            else:
                json.loads(path.read_text())
            session[key] = str(path)
            allowed.add(name)
        if kind == "extractor":
            page_root = root / "pages"
            page_root.mkdir()
            session["project_extractor_pages_dir"] = str(page_root)
            for name in names:
                if name.startswith("pages/") and PAGE_NAME.fullmatch(name[6:]):
                    path = page_root / name[6:]
                    path.write_bytes(archive.read(name))
                    LUTManager.load_lut_with_metadata(str(path))
                    allowed.add(name)
            # The currently editable LUT must be the same page that merge reads.
            page = re.search(r"\d+", str(session.get("page", "1")))
            number = int(page.group()) if page else 1
            mode = str(session.get("color_mode", ""))
            if "5-Color" in mode:
                current = page_root / f"temp_5c_ext_page_{number}.json"
            elif "8-Color" in mode:
                suffix = "8c_full" if session.get("eight_color_full_export") else "8c"
                current = page_root / f"temp_{suffix}_page_{number}.json"
            else:
                current = None
            if current is not None and current.is_file() and not session.get("project_extractor_merged"):
                session["lut_path"] = str(current)
        if set(names) != allowed:
            raise ValueError("Unexpected workflow checkpoint member")
        return session


def resolve_project_lut(name: str, context_id: str | None, store: SessionStore | None = None) -> str | None:
    if context_id:
        session = (store or get_session_store()).get(context_id)
        if session is None or "project_luts" not in session:
            raise HTTPException(404, "Project color resources have expired; reopen the project")
        if name in session["project_luts"]:
            return session["project_luts"][name]
    return LUTManager.get_lut_path(name)


def extractor_pages_dir(store: SessionStore, session_id: str | None) -> str | None:
    if not session_id:
        return None
    session = store.get(session_id)
    if not session or not session.get("project_extractor_pages_dir"):
        raise HTTPException(404, "Extraction workspace has expired; reopen the project")
    return session["project_extractor_pages_dir"]
