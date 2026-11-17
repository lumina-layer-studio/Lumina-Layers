"""Confirmed calibration can be used without importing a stale download."""
import numpy as np
from pathlib import Path
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_session_store
from api.session_store import SessionStore
from config import LUTMetadata, PaletteEntry
from utils.lut_manager import LUTManager


def test_explicit_install_keeps_confirmed_metadata_and_survives_session_close(tmp_path, monkeypatch):
    captured = []
    def capture(kind, key):
        captured.append((kind, key))
        return {"id": "a" * 32, "state": "needs_review"}
    monkeypatch.setattr("api.services.contribution_queue.capture_calibration", capture)
    monkeypatch.setenv("LUMINA_CUSTOM_LUT_DIR", str(tmp_path / "Custom"))
    store = SessionStore(ttl=1800)
    app = create_app()
    app.dependency_overrides[get_session_store] = lambda: store
    session_id = store.create()
    source = tmp_path / "extracted.json"
    metadata = LUTMetadata(color_mode="BW (Black & White)", manufacturer="Before",
                           palette=[PaletteEntry(color="White", material="PLA"), PaletteEntry(color="Black", material="PLA")])
    rgb = np.array([[255,255,255],[0,0,0]], dtype=np.uint8)
    stacks = np.array([[0,0],[1,0]], dtype=np.int32)
    LUTManager.save_keyed_json(str(source), rgb, stacks, metadata)
    store.put(session_id, "lut_path", str(source))
    store.register_temp_file(session_id, str(source))
    store.put(session_id, "color_mode", "BW (Black & White)")
    client = TestClient(app)
    assert client.post(f"/api/extractor/{session_id}/install-lut").status_code == 409
    # Confirmed metadata is authoritative even if the older output file still
    # contains the pre-confirmation palette (e.g. recoverable persistence error).
    metadata.manufacturer = "Confirmed Brand"
    metadata.palette[0].color_name = "Calibrated white"
    store.put(session_id, "lut_metadata", metadata)
    response = client.post(f"/api/extractor/{session_id}/install-lut")
    assert response.status_code == 200, response.text
    assert response.json()["contribution"]["id"] == "a" * 32
    assert captured == [("luts", response.json()["name"])]
    path = LUTManager.get_lut_path(response.json()["name"])
    loaded_rgb, loaded_stacks, loaded = LUTManager.load_lut_with_metadata(path)
    np.testing.assert_array_equal(loaded_rgb, rgb)
    np.testing.assert_array_equal(loaded_stacks, stacks)
    assert loaded.manufacturer == "Confirmed Brand"
    assert loaded.palette[0].color_name == "Calibrated white"
    assert client.post(f"/api/extractor/{session_id}/install-lut").json()["name"] == response.json()["name"]
    assert len(captured) == 1
    Path(path).write_text("personal edit", encoding="utf-8")
    alternate = client.post(f"/api/extractor/{session_id}/install-lut").json()["name"]
    assert alternate != response.json()["name"]
    assert client.post(f"/api/extractor/{session_id}/install-lut").json()["name"] == alternate
    assert Path(path).read_text(encoding="utf-8") == "personal edit"
    store.close(session_id)
    assert not source.exists()
    assert Path(path).is_file()
    assert LUTManager.get_lut_path(response.json()["name"]) == path
    assert client.post(f"/api/extractor/{session_id}/install-lut").status_code == 404


def test_failed_confirmation_write_retains_print_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_CUSTOM_LUT_DIR", str(tmp_path / "Custom"))
    store = SessionStore(ttl=1800)
    app = create_app()
    app.dependency_overrides[get_session_store] = lambda: store
    session_id = store.create()
    source = tmp_path / "extracted.json"
    original = LUTMetadata(color_mode="BW (Black & White)", base_channel_idx=1,
                           layer_order="Bottom2Top", layer_height_mm=.12, base_layers=6,
                           palette=[PaletteEntry(color="White"), PaletteEntry(color="Black")])
    rgb = np.array([[255, 255, 255], [0, 0, 0]], dtype=np.uint8)
    stacks = np.array([[0, 1], [1, 1]], dtype=np.int32)
    LUTManager.save_keyed_json(str(source), rgb, stacks, original)
    store.put(session_id, "lut_path", str(source))
    store.put(session_id, "color_mode", original.color_mode)
    client = TestClient(app)
    with monkeypatch.context() as patch:
        def failed_write(*args, **kwargs):
            raise OSError("temporary write failure")
        patch.setattr(LUTManager, "save_keyed_json", failed_write)
        confirmed = client.post("/api/extractor/confirm-palette", json={
            "session_id": session_id, "manufacturer": "Confirmed Brand", "type": "PLA",
            "palette": [{"color": "White", "material": "PLA"}, {"color": "Black", "material": "PLA"}],
        })
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "warning"
    installed = client.post(f"/api/extractor/{session_id}/install-lut")
    assert installed.status_code == 200, installed.text
    _, actual_stacks, metadata = LUTManager.load_lut_with_metadata(LUTManager.get_lut_path(installed.json()["name"]))
    np.testing.assert_array_equal(actual_stacks, stacks)
    assert metadata.manufacturer == "Confirmed Brand"
    assert (metadata.base_channel_idx, metadata.layer_order, metadata.layer_height_mm, metadata.base_layers) == (1, "Bottom2Top", .12, 6)
