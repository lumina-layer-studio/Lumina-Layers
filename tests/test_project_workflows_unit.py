from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import shutil
import zipfile

from fastapi import UploadFile
from fastapi.testclient import TestClient
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


@pytest.fixture
def project_api(monkeypatch):
    from api.app import app
    from api.dependencies import get_file_registry, get_session_store

    store, registry = SessionStore(), FileRegistry()
    monkeypatch.setitem(app.dependency_overrides, get_session_store, lambda: store)
    monkeypatch.setitem(app.dependency_overrides, get_file_registry, lambda: registry)
    try:
        yield TestClient(app), store, registry
    finally:
        registry.clear_all()
        store.clear_all()


def save_lut(path: Path, color=(10, 20, 30)):
    LUTManager.save_keyed_json(str(path), np.array([color], dtype=np.uint8), np.array([[0, 1, 0, 1, 0]]), LUTMetadata(
        color_mode="5-Color Extended", palette=[PaletteEntry(color="White", material="PETG"), PaletteEntry(color="Blue", material="PETG")],
    ))


def test_confirmed_extractor_checkpoint_reopens_for_editing_and_merge(tmp_path, project_api):
    client, store, _registry = project_api
    pages = tmp_path / "original"
    pages.mkdir()
    first, second = (pages / f"temp_5c_ext_page_{number}.json" for number in (1, 2))
    save_lut(first)
    save_lut(second, (90, 80, 70))
    session_id = store.create()
    store.register_temp_file(session_id, str(pages))
    for key, value in {
        "lut_path": str(second), "color_mode": "5-Color Extended", "page": "Page 2",
        "project_extractor_pages_dir": str(pages),
    }.items():
        store.put(session_id, key, value)
    confirmed = client.post("/api/extractor/confirm-palette", json={
        "session_id": session_id, "manufacturer": "Bambu Lab", "type": "PETG",
        "palette": [
            {"color": "White", "material": "PETG", "hex_color": "#fefefe", "color_name": "玉石白"},
            {"color": "Blue", "material": "PETG", "hex_color": "#0064f0", "color_name": "湖蓝"},
        ],
    })
    assert confirmed.status_code == 200
    metadata = store.get(session_id)["lut_metadata"].to_dict()

    saved = client.get(f"/api/projects/workflows/extractor/{session_id}")
    assert saved.status_code == 200
    with zipfile.ZipFile(io.BytesIO(saved.content)) as archive:
        header = json.loads(archive.read("checkpoint.json"))
        assert header["fields"]["lut_metadata"] == metadata
    assert client.post("/api/session/close", json={"session_id": session_id}).status_code == 200
    assert not pages.exists()

    opened = client.post("/api/projects/workflows/extractor", files={"checkpoint": ("checkpoint.zip", saved.content)})
    assert opened.status_code == 200
    restored_id = opened.json()["session_id"]
    state = store.get(restored_id)
    assert restored_id != session_id
    assert isinstance(state["lut_metadata"], LUTMetadata)
    assert state["lut_metadata"].to_dict() == metadata
    assert Path(state["lut_path"]) == Path(state["project_extractor_pages_dir"], second.name)
    edited = client.post("/api/extractor/manual-fix", json={
        "session_id": restored_id, "row_index": 0, "override_color": "#010203",
    })
    assert edited.status_code == 200
    assert LUTManager.load_lut_with_metadata(state["lut_path"])[2].to_dict() == metadata
    merged = client.post("/api/extractor/merge-5color-extended", params={"workspace_session_id": restored_id})
    assert merged.status_code == 200
    merged_state = store.get(merged.json()["session_id"])
    rgb, _stacks, _merged_metadata = LUTManager.load_lut_with_metadata(merged_state["lut_path"])
    np.testing.assert_array_equal(rgb, [[10, 20, 30], [1, 2, 3]])
    assert client.get(f"/api/projects/workflows/extractor/{restored_id}").status_code == 200


def test_restored_extractor_download_is_stable_after_edit_and_session_close(tmp_path, project_api):
    client, store, _registry = project_api
    lut = tmp_path / "source.json"
    save_lut(lut)
    data = pack_workflow_session("extractor", {"lut_path": str(lut), "color_mode": "5-Color Extended", "page": "Page 1"})
    opened = client.post("/api/projects/workflows/extractor", files={"checkpoint": ("checkpoint.zip", data)})
    assert opened.status_code == 200
    session_id = opened.json()["session_id"]
    url = opened.json()["urls"]["lut_path"]
    original_bytes = client.get(url).content
    assert client.post("/api/extractor/manual-fix", json={
        "session_id": session_id, "row_index": 0, "override_color": "#010203",
    }).status_code == 200
    assert client.get(url).content == original_bytes
    editable_root = Path(store.get(session_id)["lut_path"]).parent
    assert client.post("/api/session/close", json={"session_id": session_id}).status_code == 200
    assert not editable_root.exists()
    download = client.get(url)
    assert download.status_code == 200
    assert download.content == original_bytes


@pytest.mark.parametrize("color_mode,count,second_start,second_side,eight_color_full_export", [
    ("5-Color Extended", 2468, 1024, 38, False),
    ("8-Color Max", 2738, 1369, 37, False),
    ("8-Color Max", 32768, 31487, 37, True),
])
def test_restored_merged_lut_edits_both_cards_and_resolves_preview_clicks(
    color_mode, count, second_start, second_side, eight_color_full_export, tmp_path, project_api,
):
    client, store, _registry = project_api
    lut = tmp_path / "merged.json"
    rgb = np.full((count, 3), (20, 40, 60), dtype=np.uint8)
    stacks = np.tile(np.array([0, 1, 0, 1, 0, 1], dtype=np.int32), (count, 1))
    metadata = LUTMetadata(color_mode=color_mode, max_color_layers=6, palette=[
        PaletteEntry(color="White", material="PETG"), PaletteEntry(color="Blue", material="PETG"),
    ])
    LUTManager.save_keyed_json(str(lut), rgb, stacks, metadata)
    data = pack_workflow_session("extractor", {
        "lut_path": str(lut), "color_mode": color_mode, "project_extractor_merged": True,
        "lut_metadata": metadata, "eight_color_full_export": eight_color_full_export,
    })
    opened = client.post("/api/projects/workflows/extractor", files={"checkpoint": ("checkpoint.zip", data)})
    assert opened.status_code == 200
    session_id = opened.json()["session_id"]
    for index, color in ((0, "#010203"), (count - 1, "#040506")):
        edited = client.post("/api/extractor/manual-fix", json={
            "session_id": session_id, "row_index": index, "override_color": color,
        })
        assert edited.status_code == 200
        preview = client.get(edited.json()["lut_preview_url"])
        assert preview.status_code == 200
        image = np.asarray(Image.open(io.BytesIO(preview.content)))
        if index == 0:
            np.testing.assert_array_equal(image[0, 0], [1, 2, 3])
        else:
            page = edited.json()["lut_layout"]["pages"][0]
            assert page["start_index"] == second_start
            assert page["item_count"] == count - second_start
            assert page["data_cols"] == second_side
            last_row, last_col = divmod(count - second_start - 1, second_side)
            x, y = (last_col + 0.5) / second_side, (last_row + 0.5) / second_side
            np.testing.assert_array_equal(image[int(y * 512), int(x * 512)], [4, 5, 6])
            clicked = client.post("/api/extractor/resolve-cell", json={
                "session_id": session_id, "x": x, "y": y,
            })
            assert clicked.status_code == 200
            assert clicked.json()["cell"]["row_index"] == count - 1
            assert clicked.json()["rgb"] == [4, 5, 6]
            explicit_card = client.post("/api/extractor/resolve-cell", json={
                "session_id": session_id, "x": x, "y": y, "card_index": page["page_index"],
            })
            assert explicit_card.status_code == 200
            assert explicit_card.json()["cell"]["row_index"] == count - 1
    state = store.get(session_id)
    final_rgb, final_stacks, final_metadata = LUTManager.load_lut_with_metadata(state["lut_path"])
    assert final_rgb.shape == (count, 3)
    np.testing.assert_array_equal(final_rgb[[0, -1]], [[1, 2, 3], [4, 5, 6]])
    np.testing.assert_array_equal(final_stacks, stacks)
    assert final_metadata.max_color_layers == metadata.max_color_layers
    assert client.get(f"/api/projects/workflows/extractor/{session_id}").status_code == 200


@pytest.mark.parametrize("metadata", [[], "metadata", {"base_channel_idx": []}, {"max_color_layers": None}])
def test_invalid_extractor_metadata_checkpoint_is_rejected_without_leaking_workspace(metadata, tmp_path, project_api, monkeypatch):
    from api.routers import projects

    client, _store, _registry = project_api
    monkeypatch.setattr(projects, "TEMP_DIR", str(tmp_path))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("checkpoint.json", json.dumps({
            "version": 1, "kind": "extractor", "fields": {"lut_metadata": metadata}, "files": {},
        }))
    response = client.post("/api/projects/workflows/extractor", files={"checkpoint": ("checkpoint.zip", stream.getvalue())})
    assert response.status_code == 422
    assert not list(tmp_path.iterdir())


def test_workflow_restore_registration_failure_cleans_partial_downloads(tmp_path, project_api, monkeypatch):
    from api.dependencies import get_file_registry
    from api.routers import projects
    from api.app import app

    client, store, _registry = project_api
    source = tmp_path / "source.json"
    source.write_text('{"samples": [1, 2, 3]}', encoding="utf-8")
    data = pack_workflow_session("single-stage", {
        "single_stage_stage_json_path": str(source), "stage_a_params_path": str(source),
    })
    workspace = tmp_path / "restored"
    workspace.mkdir()
    monkeypatch.setattr(projects, "TEMP_DIR", str(workspace))
    monkeypatch.setattr("api.file_registry.TEMP_DIR", str(workspace))

    class FailingRegistry(FileRegistry):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def register_path(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise OSError("Output storage unavailable")
            return super().register_path(*args, **kwargs)

    registry = FailingRegistry()
    monkeypatch.setitem(app.dependency_overrides, get_file_registry, lambda: registry)
    try:
        response = client.post("/api/projects/workflows/single-stage", files={"checkpoint": ("checkpoint.zip", data)})
        assert response.status_code == 500
        assert not list(workspace.iterdir())
        assert registry.clear_all() == 0
        assert store.clear_all() == 0
        assert source.read_text(encoding="utf-8") == '{"samples": [1, 2, 3]}'
    finally:
        registry.clear_all()


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
    registry.clear_all()


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
