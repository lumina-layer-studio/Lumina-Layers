"""Persistent user project templates. / 持久化用户项目模板。"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any, Mapping
from uuid import UUID, uuid4
import zipfile

if TYPE_CHECKING:
    from utils.fatcat_metadata import MetadataTarget


def _root() -> Path:
    from config import _desktop_user_data_dir

    return Path(_desktop_user_data_dir()) / "3mf-templates"


def _path(template_id: str) -> Path:
    project_local = template_id.startswith("project:") if isinstance(template_id, str) else False
    if project_local:
        template_id = template_id.removeprefix("project:")
    try:
        canonical = UUID(template_id).hex
    except (ValueError, AttributeError) as error:
        raise ValueError("Invalid custom 3MF template ID") from error
    if project_local:
        from config import TEMP_DIR
        return Path(TEMP_DIR) / "project_3mf_templates" / f"{canonical}.json"
    return _root() / f"{canonical}.json"


def _optional_text(package: zipfile.ZipFile, part: str) -> str | None:
    if part not in package.namelist():
        return None
    return package.read(part).decode("utf-8")


def import_template(payload: bytes, name: str, *, slicer_hint: str | None = None) -> dict[str, Any]:
    """Store project settings, excluding source geometry. / 保存项目配置，不保存来源模型。"""
    from utils.fatcat_metadata import (
        detect_template_source,
        import_template_metadata,
        template_import_parts,
    )

    selected = None
    if slicer_hint:
        from config import SUPPORTED_SLICERS, normalize_slicer_software_id

        selected = normalize_slicer_software_id(slicer_hint)
        if selected not in {item["id"] for item in SUPPORTED_SLICERS}:
            raise ValueError("Selected slicer is not supported for custom templates")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as package:
            source_paths = template_import_parts("BambuStudio")
            source_model = _optional_text(package, source_paths["source_model"])
            slice_info = _optional_text(package, source_paths["slice_info"])
            source = detect_template_source(source_model, slice_info)
            source_slicer = source["source_slicer"]
            target_slicer = selected or source_slicer
            if target_slicer is None:
                raise ValueError("Save the template as a project in a supported slicer first")
            paths = template_import_parts(target_slicer)
            result = import_template_metadata(
                package.read(paths["project_settings"]).decode("utf-8"),
                _optional_text(package, paths["source_model"]),
                _optional_text(package, paths["slice_info"]),
                _optional_text(package, paths["model_settings"]),
                _optional_text(package, paths["plate_sidecar"]),
                slicer_id=target_slicer,
                explicit_slicer_hint=selected is not None,
            )
            settings = result["settings"]
            if result["plate_value"] is not None:
                settings["_lumina_template_plate_value"] = result["plate_value"]
            if result["sidecar_bed"] is not None:
                settings["_lumina_template_sidecar_bed"] = result["sidecar_bed"]
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("Import a project 3MF containing printer and material settings, not a geometry-only 3MF") from error
    template_id = uuid4().hex
    metadata = {
        "id": template_id, "name": name.strip() or "3MF template",
        "printer_model": result["printer_model"], "slicer": result["selected_slicer"],
        "nozzle_diameter": result["nozzle_diameter"], "filament_count": result["filament_count"],
        "source_slicer": result["source_slicer"], "source_version": result["source_version"],
    }
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump({"metadata": metadata, "settings": settings}, temporary, ensure_ascii=False)
        os.replace(temporary_path, _path(template_id))
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return metadata


def list_templates() -> list[dict[str, Any]]:
    """List saved templates. / 列出已保存模板。"""
    result = []
    for path in sorted(_root().glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            result.append(document["metadata"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def load_template(template_id: str) -> dict[str, Any]:
    """Load saved settings with source slicer identity. / 加载配置及来源切片软件标识。"""
    document = json.loads(_path(template_id).read_text(encoding="utf-8"))
    return {**document["settings"], "_lumina_template_slicer": document["metadata"]["slicer"]}


def require_template_slot_capacity(
    template: Mapping[str, Any], required_slots: int, *, target: MetadataTarget,
) -> int:
    """Return native capacity, rejecting material slots the template cannot supply."""
    from core.errors import TemplateSlotCapacityError
    from utils.fatcat_metadata import read_project_material_slots

    available_slots = len(read_project_material_slots(template, target=target))
    if required_slots > available_slots:
        raise TemplateSlotCapacityError(required_slots, available_slots)
    return available_slots


def delete_template(template_id: str) -> None:
    """Remove one explicitly selected template. / 删除指定模板。"""
    _path(template_id).unlink()
