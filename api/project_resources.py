"""Session-owned project resources; never install into the user's library."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
import zipfile

from fastapi import HTTPException, UploadFile

from config import TEMP_DIR
from core.material_lut_synthesis import load_multiple_materials
from core.projects.dependencies import MAX_DEPENDENCY_BYTES, unpack_lut_source
from core.single_stage import import_saved_stage_a_material_archives


@dataclass(frozen=True)
class ProjectResources:
    root: str
    lut_path: str | None
    materials_dir: str | None


async def _read_resource(upload: UploadFile) -> bytes:
    data = await upload.read(MAX_DEPENDENCY_BYTES + 1)
    if len(data) > MAX_DEPENDENCY_BYTES:
        raise HTTPException(413, "Project resource exceeds its size limit")
    return data


async def stage_project_resources(
    lut: UploadFile | None,
    materials: UploadFile | None,
    selected_materials: list[str],
) -> ProjectResources | None:
    if lut is None and materials is None:
        return None
    root = Path(tempfile.mkdtemp(prefix="project_resources_", dir=TEMP_DIR))
    try:
        lut_path = None
        materials_dir = None
        if lut is not None:
            lut_path = await asyncio.to_thread(unpack_lut_source, await _read_resource(lut), root / "lut")
        if materials is not None:
            archive = root / "materials.zip"
            archive.write_bytes(await _read_resource(materials))
            materials_dir = str(root / "materials")
            await asyncio.to_thread(import_saved_stage_a_material_archives, archive_path=str(archive), materials_dir=materials_dir)
            await asyncio.to_thread(load_multiple_materials, selected_materials, materials_dir=materials_dir)
        return ProjectResources(str(root), lut_path, materials_dir)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(422, f"Invalid project color resources: {exc}") from exc
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def discard_project_resources(resources: ProjectResources | None) -> None:
    if resources is not None:
        shutil.rmtree(resources.root, ignore_errors=True)
