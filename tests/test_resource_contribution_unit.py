import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.contributions import router
from core.resource_contribution import contribution_package, prepare_contribution
from core.single_stage import material_files
from utils.lut_manager import LUTManager


@pytest.fixture(autouse=True)
def isolated_source_lookup(monkeypatch):
    monkeypatch.setattr("api.routers.contributions.local_resource_origin", lambda *_: None)


def test_material_package_keeps_calibration_but_not_local_evidence(tmp_path, monkeypatch):
    directory = tmp_path / "Brand" / "Red"
    directory.mkdir(parents=True)
    params = {"param_type": "stage_A", "parameters": {"channels": [{"E": [1, .2, .3], "k": [2, 3, 4]}]},
              "meta": {"schema_version": "1", "source_image": "/private/photo.jpg"},
              "source": {"spec": {"layer_height_mm": .08}, "image_path": "/private/photo.jpg"}}
    (directory / "stage_A_parameters.json").write_text(json.dumps(params))
    (directory / "material.json").write_text(json.dumps({
        "kind": "lumina_stage_a_material", "schema_version": "1.1", "brand": "Brand",
        "material_name": "Red", "stage_a_params_file": "stage_A_parameters.json",
        "source": {"image_path": "/private/photo.jpg"}, "verification_runs": [{"secret": "private"}],
    }))
    (directory / "photo.jpg").write_bytes(b"private-photo")
    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(tmp_path))
    prepared = prepare_contribution("materials", "Brand/Red")
    package, _, _ = contribution_package(prepared, {"brand": "Brand", "material_name": "Red", "material_type": "PLA"}, "user1")
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert len(archive.namelist()) == 3
        all_data = b"".join(archive.read(name) for name in archive.namelist())
        assert b"/private" not in all_data and b"private-photo" not in all_data and b"secret" not in all_data
        exported = json.loads(archive.read(next(name for name in archive.namelist() if name.endswith("stage_A_parameters.json"))))
        assert exported["parameters"] == params["parameters"]
        assert exported["source"]["spec"]["layer_height_mm"] == .08
    with pytest.raises(ValueError):
        prepare_contribution("materials", "../outside")


def test_lut_package_preserves_bytes_and_contributor_identity(tmp_path, monkeypatch):
    path = tmp_path / "BW.npy"
    np.save(path, np.arange(96, dtype=np.uint8).reshape(32, 3))
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda key: str(path) if key == "BW" else None)
    prepared = prepare_contribution("luts", "BW")
    display = {"name": "Black and white", "brand": "Brand", "material_type": "PLA",
               "attribution": {"relationship": "original"}}
    first, resource_id, revision = contribution_package(prepared, display, "user1")
    second, other_id, _ = contribution_package(prepared, display, "user2")
    assert resource_id != other_id and first != second
    assert contribution_package(prepared, display, "user1")[1:] == (resource_id, revision)
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.read("calibration.npy") == path.read_bytes()
        metadata = json.loads(archive.read("lumina_lut_bundle.json"))
        assert metadata["display"]["license"] == "LicenseRef-Lumina-Data-1.0"
    legacy, _, _ = contribution_package(prepared, {**display, "license": "CC-BY-4.0"}, "user1")
    with zipfile.ZipFile(io.BytesIO(legacy)) as archive:
        assert json.loads(archive.read("lumina_lut_bundle.json"))["display"]["license"] == "CC-BY-4.0"
    with pytest.raises(FileNotFoundError):
        prepare_contribution("luts", str(path))


def test_lut_products_follow_original_palette_channels(tmp_path, monkeypatch):
    from config import LUTMetadata, PaletteEntry
    path = tmp_path / "BW.json"
    colors = np.arange(96, dtype=np.uint8).reshape(32, 3)
    stacks = np.array([[index >> bit & 1 for bit in range(5)] for index in range(32)], dtype=np.int32)
    metadata = LUTMetadata(color_mode="BW (Black & White)",
                           palette=[PaletteEntry(color="White"), PaletteEntry(color="Black")])
    LUTManager.save_keyed_json(str(path), colors, stacks, metadata)
    document = json.loads(path.read_text())
    document["filaments"] = [{"slot": 1, "brand": "Black Brand", "color_code": "B1"},
                             {"slot": 0, "brand": "White Brand", "color_code": "W1"}]
    path.write_text(json.dumps(document))
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda _: str(path))
    slots = prepare_contribution("luts", "BW").display["filaments"]
    assert [(row["slot"], row["color_name"], row["color_code"]) for row in slots] == [
        (0, "White", "W1"), (1, "Black", "B1"),
    ]
    document["filaments"][0]["slot"] = 0  # Ambiguous metadata must not swap actual channels.
    path.write_text(json.dumps(document))
    slots = prepare_contribution("luts", "BW").display["filaments"]
    assert [row["color_name"] for row in slots] == ["White", "Black"]
    assert all("color_code" not in row for row in slots)


def test_submit_requires_confirmation_and_current_local_data(tmp_path, monkeypatch):
    path = tmp_path / "BW.npy"
    np.save(path, np.arange(96, dtype=np.uint8).reshape(32, 3))
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda _: str(path))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {"X-Lumina-Contribution": "1"}
    assert client.post("/api/contributions/prepare", json={"kind": "luts", "key": "BW"}).status_code == 403
    assert client.post("/api/contributions/prepare", headers={**headers, "Origin": "https://unrelated.invalid"},
                       json={"kind": "luts", "key": "BW"}).status_code == 403
    prepared = client.post("/api/contributions/prepare", headers=headers, json={"kind": "luts", "key": "BW"}).json()
    request = {"kind": "luts", "key": "BW", "name": "BW", "fingerprint": prepared["fingerprint"],
               "product": {"brand": "Brand", "material_type": "PLA"}, "consent": False, "account_id": "maker",
               "attribution": {"relationship": "original"}}
    assert client.post("/api/contributions/submit", headers=headers, json=request).status_code == 422
    request["consent"] = True
    np.save(path, np.ones((32, 3), dtype=np.uint8))
    assert client.post("/api/contributions/submit", headers=headers, json=request).status_code == 409


@pytest.mark.parametrize("kind", ["materials", "luts"])
def test_retry_recovers_server_receipt_without_reupload(kind, tmp_path, monkeypatch):
    from api.services.resource_contribution import ContributionConnection, ContributionError
    from core.resource_contribution import PreparedContribution
    prepared = PreparedContribution(kind, "fixture", "a" * 64, {}, {},
                                    {"material.json": b"{}", "stage_A_parameters.json": b"{}"} if kind == "materials" else {"calibration.npy": b"data"})
    display = {"brand": "Brand", "material_name": "Test", "material_type": "PLA"}
    service = ContributionConnection()
    rows, uploads = [], []
    monkeypatch.setattr(service, "status", lambda: {"state": "connected", "subject": "maker"})
    monkeypatch.setattr(service, "history", lambda: rows)

    def request(method, path, **kwargs):
        if path.endswith("/submit"):
            rows[0]["status"] = "pending"
            return rows[0]
        assert method == "POST"
        uploads.append(kwargs["files"]["archive"][1])
        _, resource_id, revision_id = contribution_package(prepared, display, "maker")
        rows.append({"kind": kind, "submission_id": "submission1",
                     "material_id" if kind == "materials" else "lut_id": resource_id,
                     "revision_id": revision_id, "status": "draft" if kind == "materials" else "pending"})
        raise ContributionError(502, "response lost")
    monkeypatch.setattr(service, "_request", request)
    with pytest.raises(ContributionError, match="account changed"):
        service.submit(prepared, display, expected_subject="another-account")
    assert not uploads
    with pytest.raises(ContributionError):
        service.submit(prepared, display)
    receipt = service.submit(prepared, display)
    assert receipt["status"] == "pending"
    assert len(uploads) == 1


def test_connection_token_is_source_bound_and_not_persisted(monkeypatch):
    from api.services.resource_contribution import ContributionConnection
    service = ContributionConnection()
    monkeypatch.setenv("LUMINA_CONTRIBUTION_REGISTRY_URL", "https://one.invalid/api/material-registry/v1")
    service.source()
    service._token = "studio_test"
    monkeypatch.setenv("LUMINA_CONTRIBUTION_REGISTRY_URL", "https://two.invalid/api/material-registry/v1")
    assert service.status()["state"] == "disconnected"
    assert not service._token
    service._token = "studio_test"
    monkeypatch.setenv("LUMINA_CONTRIBUTION_REGISTRY_URL", "")
    assert service.status()["state"] == "unavailable"
    assert not service._token


def test_public_origin_cannot_be_removed_or_relabelled_as_original(tmp_path, monkeypatch):
    path = tmp_path / "BW.npy"
    np.save(path, np.arange(96, dtype=np.uint8).reshape(32, 3))
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda _: str(path))
    reference = {"kind": "luts", "resource_id": "lut_source", "revision_id": "rev_source",
                 "content_hash": "sha256:" + "f" * 64}
    origin = {"reference": reference, "modified": False, "original_author": "Original maker", "rights_basis": "CC-BY-4.0"}
    monkeypatch.setattr("api.routers.contributions.local_resource_origin", lambda *_: origin)
    submitted = []
    monkeypatch.setattr("api.routers.contributions.connection.submit",
                        lambda prepared, display, **_: submitted.append(display) or {"status": "pending"})
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {"X-Lumina-Contribution": "1"}
    prepared = client.post("/api/contributions/prepare", headers=headers, json={"kind": "luts", "key": "BW"}).json()
    assert prepared["origin"] == origin
    payload = {"kind": "luts", "key": "BW", "name": "BW", "fingerprint": prepared["fingerprint"],
               "product": {}, "consent": True, "account_id": "maker", "attribution": {"relationship": "original"},
               "filaments": [{"brand": "Brand", "material_type": "PLA", "color_name": row["color_name"]}
                             for row in prepared["display"]["filaments"]]}
    assert client.post("/api/contributions/submit", headers=headers, json=payload).status_code == 422
    payload["attribution"] = {"relationship": "redistributed", "original_author": "Original maker",
                              "rights_basis": "CC-BY-4.0"}
    result = client.post("/api/contributions/submit", headers=headers, json=payload)
    assert result.status_code == 200, result.text
    assert submitted[0]["attribution"]["source"] == reference
    assert submitted[0]["attribution"]["original_author"] == "Original maker"
    payload["attribution"]["source"] = {**reference, "resource_id": "forged"}
    assert client.post("/api/contributions/submit", headers=headers, json=payload).status_code == 422
    del payload["attribution"]
    assert client.post("/api/contributions/submit", headers=headers, json=payload).status_code == 422


@pytest.mark.parametrize("source_license", ["CC-BY-4.0", "CC-BY-SA-4.0", None])
def test_installed_manifest_license_survives_prepare_and_real_submission_packaging(tmp_path, monkeypatch, source_license):
    import hashlib
    from api.services import lut_registry_sync as sync
    from api.services.resource_activity import local_resource_origin
    from test_lut_registry_sync_unit import _bundle_bytes, _entry

    cloud = tmp_path / "presets/Cloud"
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(cloud))
    monkeypatch.setenv("LUMINA_CUSTOM_LUT_DIR", str(tmp_path / "presets/Custom"))
    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(LUTManager, "_scan_legacy_roots", lambda: [("Cloud", str(cloud))])
    monkeypatch.setattr("api.routers.contributions.local_resource_origin", local_resource_origin)
    buffer = io.BytesIO()
    np.save(buffer, np.arange(96, dtype=np.uint8).reshape(32, 3))
    calibration = buffer.getvalue()
    source_display = {"name": "Source BW", "contributor_name": "Original maker"}
    if source_license:
        source_display["license"] = source_license
    identity = {"lut_id": "lut_source", "revision_id": "rev_source", "channel": "community",
                "local_path": "Brand/PLA/source.npy", "content_hash": "sha256:" + hashlib.sha256(calibration).hexdigest(),
                "display": source_display, "compatibility": {"color_mode": "BW (Black & White)"}}
    package = _bundle_bytes(calibration, lut_path="calibration.npy", package_extra=identity)
    installed = sync.install_lut_archive_bytes(_entry(package, **identity), package,
                                               source_url="https://example.test/source.zip")
    LUTManager.invalidate_preset_cache()
    try:
        expected_path = (tmp_path / "presets" / installed["installed_path"]).resolve()
        key = next(name for name, path in LUTManager.get_all_lut_files().items() if Path(path).resolve() == expected_path)
        captured = {}
        def receive(prepared, display, *, expected_subject):
            payload, _, _ = contribution_package(prepared, display, expected_subject)
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                captured.update(json.loads(archive.read("lumina_lut_bundle.json"))["display"])
                assert archive.read("calibration.npy") == calibration
            return {"status": "pending"}
        monkeypatch.setattr("api.routers.contributions.connection.submit", receive)
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            headers = {"X-Lumina-Contribution": "1"}
            response = client.post("/api/contributions/prepare", headers=headers, json={"kind": "luts", "key": key})
            assert response.status_code == 200, response.text
            prepared = response.json()
            assert prepared["display"].get("license") == source_license
            origin = prepared["origin"]
            assert origin["original_author"] == "Original maker"
            result = client.post("/api/contributions/submit", headers=headers, json={
                "kind": "luts", "key": key, "name": "Redistributed BW", "product": {},
                "fingerprint": prepared["fingerprint"], "consent": True, "account_id": "submitter",
                "attribution": {"relationship": "redistributed", "original_author": origin["original_author"],
                                "rights_basis": source_license or "Author permits redistribution"},
                "filaments": [{"brand": "Brand", "material_type": "PLA", "color_name": slot["color_name"]}
                              for slot in prepared["display"]["filaments"]],
            })
            assert result.status_code == 200, result.text
        assert captured.get("license") == source_license
        assert captured["attribution"]["source"] == origin["reference"]
        assert captured["attribution"]["original_author"] == "Original maker"
    finally:
        LUTManager.invalidate_preset_cache()


def test_attribution_and_raw_lut_survive_packaging_and_display_projection(tmp_path, monkeypatch):
    from core.filament_display import filament_display
    path = tmp_path / "BW.npy"
    np.save(path, np.arange(96, dtype=np.uint8).reshape(32, 3))
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda _: str(path))
    declaration = {"relationship": "adapted", "original_author": "Jane",
                   "rights_basis": "CC-BY-4.0", "source_url": "https://example.org/calibration"}
    prepared = prepare_contribution("luts", "BW")
    package, _, first_revision = contribution_package(prepared, {"attribution": declaration}, "maker")
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert archive.read("calibration.npy") == path.read_bytes()
        display = json.loads(archive.read("lumina_lut_bundle.json"))["display"]
        assert filament_display(display)["attribution"] == declaration
    _, _, other_revision = contribution_package(prepared, {"attribution": {**declaration, "original_author": "Pat"}}, "maker")
    assert first_revision != other_revision


@pytest.mark.parametrize("value", [
    {"relationship": []},
    {"relationship": "adapted", "original_author": "Jane", "rights_basis": "CC-BY-4.0", "source_url": "javascript:alert(1)"},
    {"relationship": "redistributed", "original_author": "", "rights_basis": "CC-BY-4.0", "source_url": "https://example.org"},
    {"relationship": "redistributed", "original_author": "Jane", "rights_basis": "", "source_url": "https://example.org"},
    {"relationship": "adapted", "original_author": "Jane", "rights_basis": "CC-BY-4.0"},
])
def test_invalid_source_declarations_are_rejected(value):
    from core.resource_attribution import normalize_attribution
    with pytest.raises(ValueError):
        normalize_attribution(value)
