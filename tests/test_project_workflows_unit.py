from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import shutil
import zipfile

from fastapi import UploadFile
import numpy as np
from PIL import Image
import pytest

from api.colorchecker_artifacts import load_colorchecker_full_rgb
from api.file_registry import FileRegistry
from api.project_workflows import pack_workflow_session, resolve_project_lut, unpack_workflow_session
from api.routers.projects import capture_colorchecker, restore_colorchecker, restore_workflow
from api.session_store import SessionStore
from config import LUTMetadata, PaletteEntry
from utils.lut_manager import LUTManager


def save_lut(path: Path, color=(10, 20, 30)):
    LUTManager.save_keyed_json(str(path), np.array([color], dtype=np.uint8), np.array([[0, 1, 0, 1, 0]]), LUTMetadata(
        color_mode="5-Color Extended", palette=[PaletteEntry(color="White", material="PETG"), PaletteEntry(color="Blue", material="PETG")],
    ))


def test_extractor_checkpoint_preserves_edited_pages_and_rebinds_merge_inputs(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    first = original / "temp_5c_ext_page_1.json"
    second = original / "temp_5c_ext_page_2.json"
    save_lut(first)
    save_lut(second, (90, 80, 70))
    state = {"lut_path": str(second), "color_mode": "5-Color Extended", "page": "Page 2", "project_extractor_pages_dir": str(original)}
    archive = pack_workflow_session("extractor", state)
    shutil.rmtree(original)
    restored = unpack_workflow_session("extractor", archive, tmp_path / "restored")
    assert Path(restored["lut_path"]).parent == Path(restored["project_extractor_pages_dir"])
    assert Path(restored["project_extractor_pages_dir"], first.name).is_file()
    np.testing.assert_array_equal(LUTManager.load_lut_with_metadata(restored["lut_path"])[0], [[90, 80, 70]])
    # A later edit changes the same file that the merge owner consumes.
    save_lut(Path(restored["lut_path"]), (44, 55, 66))
    again = unpack_workflow_session("extractor", pack_workflow_session("extractor", restored), tmp_path / "again")
    np.testing.assert_array_equal(LUTManager.load_lut_with_metadata(again["lut_path"])[0], [[44, 55, 66]])


def test_merged_extraction_stays_merged_when_reopened(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    save_lut(pages / "temp_5c_ext_page_1.json")
    save_lut(pages / "merged.json", (99, 88, 77))
    source = {"lut_path": str(pages / "merged.json"), "color_mode": "5-Color Extended", "project_extractor_pages_dir": str(pages), "project_extractor_merged": True}
    result = unpack_workflow_session("extractor", pack_workflow_session("extractor", source), tmp_path / "restore")
    np.testing.assert_array_equal(LUTManager.load_lut_with_metadata(result["lut_path"])[0], [[99, 88, 77]])


def test_gradient_checkpoint_restores_real_fit_data_into_fresh_owned_session(tmp_path):
    params = {"parameters": {"channels": [{"color_name": "Cyan", "E": [0.2, 0.4, 0.6], "k": [1, 2, 3]}]}}
    stage = tmp_path / "stage.json"
    stage.write_text(json.dumps({"samples": [1, 2, 3]}))
    source = {"gradient_card_stage_a_params": params, "gradient_card_material_summary": {"estimated_rgb": [50, 100, 150]}, "single_stage_stage_json_path": str(stage)}
    data = pack_workflow_session("single-stage", source)
    stage.unlink()
    store, registry = SessionStore(), FileRegistry()
    result = asyncio.run(restore_workflow("single-stage", UploadFile(file=io.BytesIO(data), filename="checkpoint.zip"), store, registry))
    restored = store.get(result["session_id"])
    assert restored["gradient_card_stage_a_params"] == params
    path = Path(restored["single_stage_stage_json_path"])
    assert json.loads(path.read_text()) == {"samples": [1, 2, 3]}
    registry.cleanup_session(result["session_id"])
    store.close(result["session_id"])
    assert not path.parent.exists()


def test_colorchecker_pixels_survive_private_resource_roundtrip():
    registry = FileRegistry()
    stream = io.BytesIO()
    Image.new("RGB", (10, 20), (12, 34, 56)).save(stream, "PNG")
    result = asyncio.run(restore_colorchecker(UploadFile(file=io.BytesIO(stream.getvalue()), filename="image.png"), registry))
    file_id = result["file_id"]
    try:
        assert registry.get_entry(file_id)["is_public"] is False
        assert capture_colorchecker(file_id, registry).body == stream.getvalue()
        np.testing.assert_array_equal(load_colorchecker_full_rgb(registry, file_id)[0, 0], [12, 34, 56])
    finally:
        registry.cleanup_file(file_id)


def test_project_lut_wins_over_same_named_global_lut(tmp_path, monkeypatch):
    local, project = tmp_path / "local.json", tmp_path / "project.json"
    save_lut(local)
    save_lut(project, (91, 92, 93))
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda name: str(local))
    store = SessionStore()
    sid = store.create()
    store.put(sid, "project_luts", {"same name": str(project)})
    assert resolve_project_lut("same name", sid, store) == str(project)
    assert resolve_project_lut("other newly selected LUT", sid, store) == str(local)


@pytest.mark.parametrize("member", ["../escape", "pages/../../escape", "lut_path.exe", "pages/not-a-page.json"])
def test_workflow_checkpoint_rejects_unexpected_members(tmp_path, member):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("checkpoint.json", json.dumps({"version": 1, "kind": "extractor", "fields": {}, "files": {}}))
        archive.writestr(member, b"untrusted")
    with pytest.raises(ValueError):
        unpack_workflow_session("extractor", stream.getvalue(), tmp_path / "restore")
    assert not (tmp_path / "escape").exists()
