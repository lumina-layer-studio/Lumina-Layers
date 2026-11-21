import base64
import io
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.env_loader import load_env_local
from api.routers.contributions import router
from core.resource_contribution import contribution_package, prepare_contribution
from core.single_stage import material_files
from utils.lut_manager import LUTManager


def _sample_print_photo() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (210, 48, 48)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


SAMPLE_PRINT_PHOTO = _sample_print_photo()


@pytest.fixture(autouse=True)
def isolated_source_lookup(monkeypatch):
    monkeypatch.setattr("api.routers.contributions.local_resource_origin", lambda *_: None)


@pytest.mark.parametrize(("origin", "referer", "expected"), [
    ("http://127.0.0.1:4174", None, 200),
    ("http://localhost:4174", None, 200),
    ("http://[::1]:4174", None, 200),
    ("http://studio.localhost:4174", None, 200),
    ("https://studio.example.test:8443", None, 200),
    (None, "https://studio.example.test:8443/", 200),
    ("https://studio.example.test:8444", None, 403),
    ("https://unrelated.example.test", None, 403),
    (None, "https://unrelated.example.test/", 403),
    ("null", None, 403),
    ("http://[", None, 403),
])
def test_connect_from_local_or_trusted_studio_page(monkeypatch, origin, referer, expected):
    monkeypatch.setenv("LUMINA_CONTRIBUTION_ALLOWED_ORIGINS", "https://studio.example.test:8443/")
    monkeypatch.setattr("api.routers.contributions.connection.start", lambda: {"state": "pending"})
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-Lumina-Contribution": "1"}
    if origin is not None:
        headers["Origin"] = origin
    if referer is not None:
        headers["Referer"] = referer

    response = client.post("/api/contributions/connection", headers=headers, json={})

    assert response.status_code == expected
    if expected == 200:
        assert response.json()["state"] == "pending"


def test_contribution_server_endpoint_uses_the_backend_env_file(tmp_path, monkeypatch):
    key = "LUMINA_CONTRIBUTION_REGISTRY_URL"
    monkeypatch.setenv(key, "")
    monkeypatch.delenv(key)
    env_file = tmp_path / ".env.local"
    registry = "http://localhost:8018/materials/api/material-registry/v1"
    env_file.write_text(f"{key}={registry}/\n", encoding="utf-8")
    load_env_local(env_file)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/api/contributions/connection/server", headers={"X-Lumina-Contribution": "1"})

    assert response.status_code == 200
    assert response.json() == {"server": registry}


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


@pytest.mark.parametrize("catalog_channel", [None, "manual", "community", "studio-team"])
def test_restored_material_keeps_its_original_provenance(tmp_path, monkeypatch, catalog_channel):
    from api.routers.resource_activity import router as activity_router
    from api.services.resource_activity import local_resource_origin
    from core.single_stage.material_library import (
        export_saved_stage_a_material_archives,
        import_saved_stage_a_material_archives,
        save_stage_a_material_archive,
    )

    original = tmp_path / "first-library"
    restored = tmp_path / "restored-library"
    catalog_source = catalog_channel is not None
    saved = save_stage_a_material_archive(
        material_name="灰阶校白后-品红", brand="Lumina-Box", materials_dir=str(original),
        params_payload={"param_type": "stage_A", "parameters": {
            "channels": [{"color_name": "品红", "E": [.4, .1, .3], "k": [8, 7, 9]}],
            "substrates": [{"substrate_id": "white", "C0": [.9, .9, .9]},
                           {"substrate_id": "black", "C0": [.025, .025, .025]}],
        }, "meta": {"schema_version": "1"}, "source": {"spec": {"layer_height_mm": .04}}},
        fit_summary={"mean_delta_e": 2.4}, source_summary={}, material_summary={},
    )
    key = saved.material_summary["directory_name"]
    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(original))
    assert local_resource_origin("materials", key) is None

    archive = export_saved_stage_a_material_archives(
        directory_names=[key], materials_dir=str(original), output_path=str(tmp_path / "backup.zip"),
    )
    if catalog_source:
        with zipfile.ZipFile(archive.archive_path) as zipped:
            manifest = json.loads(zipped.read("lumina_material_bundle.json"))["packages"][0]
        assert manifest["channel"] == "manual"
        catalog = tmp_path / "catalog-library"
        installed, = import_saved_stage_a_material_archives(
            archive_path=archive.archive_path, materials_dir=str(catalog),
            selected_material_id=manifest["material_id"], selected_revision_id=manifest["revision_id"],
            selected_channel=catalog_channel,
        ).imported_materials
        monkeypatch.setattr(material_files, "MATERIALS_DIR", str(catalog))
        assert local_resource_origin("materials", installed["directory_name"])["reference"]["resource_id"] == manifest["material_id"]
        archive = export_saved_stage_a_material_archives(
            directory_names=[installed["directory_name"]], materials_dir=str(catalog),
            output_path=str(tmp_path / "catalog-backup.zip"),
        )
    imported = import_saved_stage_a_material_archives(
        archive_path=archive.archive_path, materials_dir=str(restored),
    )
    material, = imported.imported_materials
    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(restored))
    monkeypatch.setattr("api.routers.contributions.local_resource_origin", local_resource_origin)
    monkeypatch.setattr("api.routers.contributions.connection.owns_original_source", lambda **_: False)
    received = []
    monkeypatch.setattr("api.routers.contributions.connection.submit", lambda _, display, **kw:
                        received.append(display["attribution"]) or {"status": "pending"})
    app = FastAPI()
    app.include_router(router)
    app.include_router(activity_router)
    client = TestClient(app)
    headers = {"X-Lumina-Contribution": "1"}
    selection = {"kind": "materials", "key": material["directory_name"]}
    prepared = client.post("/api/contributions/prepare", headers=headers, json=selection)
    assert prepared.status_code == 200, prepared.text
    origin = prepared.json()["origin"]
    refs = client.get("/api/community/materials/local-references", headers=headers)
    assert refs.status_code == 200, refs.text
    reference = refs.json()["items"].get(material["directory_name"])
    if catalog_source:
        assert origin["reference"]["resource_id"] == manifest["material_id"]
        assert reference == {
            field: origin["reference"][field] for field in ("resource_id", "revision_id", "content_hash")
        }
    else:
        assert origin is None and reference is None
    response = client.post("/api/contributions/submit", headers=headers, json={
        **selection, "name": material["material_name"], "fingerprint": prepared.json()["fingerprint"],
        "product": {"brand": "Lumina-Box", "material_type": "PLA"}, "account_id": "maker",
        "attribution": {"relationship": "original"}, "consent": True,
        "print_images": [SAMPLE_PRINT_PHOTO],
    })
    assert response.status_code == (422 if catalog_source else 200), response.text
    assert received == ([] if catalog_source else [{"relationship": "original"}])


@pytest.mark.parametrize("legacy_backup", [False, True], ids=["current-backup", "legacy-backup"])
def test_catalog_match_preserves_the_local_source_and_public_reference(tmp_path, monkeypatch, legacy_backup):
    import httpx

    from api.routers.resource_activity import router as activity_router
    from api.services.resource_activity import local_resource_origin
    from core.single_stage.material_library import (
        export_saved_stage_a_material_archives,
        import_saved_stage_a_material_archives,
        save_stage_a_material_archive,
    )
    from core.single_stage.material_package import _build_material_bundle_package_manifest
    from core.single_stage.material_registry_client import refresh_material_sync_from_registry

    materials = tmp_path / "materials"
    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(materials))
    monkeypatch.setattr("api.routers.contributions.local_resource_origin", local_resource_origin)
    saved = save_stage_a_material_archive(
        material_name="Magenta", brand="Lumina-Box", materials_dir=str(materials),
        params_payload={"param_type": "stage_A", "parameters": {
            "channels": [{"color_name": "Magenta", "E": [.4, .1, .3], "k": [8, 7, 9]}],
            "substrates": [{"substrate_id": "white", "C0": [.9, .9, .9]},
                           {"substrate_id": "black", "C0": [.025, .025, .025]}],
        }, "meta": {"schema_version": "1"}, "source": {"spec": {"layer_height_mm": .04}}},
        fit_summary={}, source_summary={}, material_summary={},
    )
    key = saved.material_summary["directory_name"]
    manifest, _ = _build_material_bundle_package_manifest(target_root=materials, material_dir=materials / key)
    entry = {**manifest, "channel": "community", "package_url": "/v1/packages/magenta.zip",
             "package_sha256": "0" * 64}
    if legacy_backup:
        old_backup = export_saved_stage_a_material_archives(
            directory_names=[key], materials_dir=str(materials), output_path=str(tmp_path / "legacy.zip"),
        )
    else:
        entry.update(material_id="mat_public", revision_id="rev_public")

    def catalog(request):
        assert request.url.path == "/v1/materials/catalog"
        return httpx.Response(200, json={"schema_version": "1.0", "materials": [entry]})

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.example.test/v1", channels=["community"],
        materials_dir=str(materials), transport=httpx.MockTransport(catalog),
    )
    assert result["skipped_count"] == 1 and result["installed_count"] == 0

    submitted = []
    monkeypatch.setattr("api.routers.contributions.connection.submit", lambda _, display, **kwargs:
                        submitted.append(display["attribution"]) or {"status": "pending"})
    app = FastAPI()
    app.include_router(router)
    app.include_router(activity_router)
    client = TestClient(app)
    headers = {"X-Lumina-Contribution": "1"}
    selection = {"kind": "materials", "key": key}
    response = client.post("/api/contributions/prepare", headers=headers, json=selection)
    assert response.status_code == 200, response.text
    prepared = response.json()
    assert prepared["origin"] is None
    response = client.post("/api/contributions/submit", headers=headers, json={
        **selection, "name": "Magenta", "fingerprint": prepared["fingerprint"],
        "product": {"brand": "Lumina-Box", "material_type": "PLA"}, "account_id": "maker",
        "attribution": {"relationship": "original"}, "consent": True,
        "print_images": [SAMPLE_PRINT_PHOTO],
    })
    assert response.status_code == 200, response.text
    assert submitted == [{"relationship": "original"}]
    expected_reference = {field: entry[field] for field in ("revision_id", "content_hash")}
    expected_reference["resource_id"] = entry["material_id"]

    def references():
        response = client.get("/api/community/materials/local-references", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()["items"]

    assert references()[key] == expected_reference
    backup = old_backup if legacy_backup else export_saved_stage_a_material_archives(
        directory_names=[key], materials_dir=str(materials), output_path=str(tmp_path / "backup.zip"),
    )
    with zipfile.ZipFile(backup.archive_path) as zipped:
        package, = json.loads(zipped.read("lumina_material_bundle.json"))["packages"]
    assert (package["material_id"], package["revision_id"]) == (entry["material_id"], entry["revision_id"])
    restored = tmp_path / "restored"
    restored_archive, = import_saved_stage_a_material_archives(
        archive_path=backup.archive_path, materials_dir=str(restored),
    ).imported_materials
    restored_key = restored_archive["directory_name"]
    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(restored))
    if legacy_backup:
        assert references() == {}
        refreshed = refresh_material_sync_from_registry(
            registry_url="https://registry.example.test/v1", channels=["community"],
            materials_dir=str(restored), transport=httpx.MockTransport(catalog),
        )
        assert refreshed["skipped_count"] == 1 and refreshed["installed_count"] == 0
    assert references()[restored_key] == expected_reference
    response = client.post("/api/contributions/prepare", headers=headers,
                           json={"kind": "materials", "key": restored_key})
    assert response.status_code == 200, response.text
    assert response.json()["origin"] is None


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
               "print_images": [SAMPLE_PRINT_PHOTO],
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


@pytest.mark.parametrize(("relationship", "owns_revision", "same_content", "allowed"), [
    ("original", True, True, True),
    (None, True, True, True),
    ("redistributed", True, True, False),
    ("adapted", True, True, False),
    ("original", False, True, False),
    ("original", True, False, False),
])
def test_public_source_can_update_only_the_current_accounts_original(
    tmp_path, monkeypatch, relationship, owns_revision, same_content, allowed,
):
    from api.services.resource_contribution import ContributionError, connection

    path = tmp_path / "BW.npy"
    np.save(path, np.arange(96, dtype=np.uint8).reshape(32, 3))
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda _: str(path))
    reference = {"kind": "luts", "resource_id": "lut_source", "revision_id": "rev_source",
                 "content_hash": "sha256:" + "f" * 64}
    origin = {"reference": reference, "modified": True, "license": "CC-BY-4.0"}
    monkeypatch.setattr("api.routers.contributions.local_resource_origin", lambda *_: origin)
    monkeypatch.setattr(connection, "status", lambda: {"state": "connected", "subject": "maker"})
    row = {"kind": "luts", "lut_id": "lut_source", "revision_id": "rev_source",
           "display": {"attribution": {"relationship": relationship}} if relationship else {}}
    monkeypatch.setattr(connection, "history", lambda: [row] if owns_revision else [])

    def lookup(kind, payload, action):
        assert (kind, action) == ("luts", "contributor")
        assert payload == {key: reference[key] for key in ("resource_id", "revision_id", "content_hash")}
        if not same_content:
            raise ContributionError(404, "Revision unavailable")
        return {"contributor": None}

    monkeypatch.setattr(connection, "resource_feedback", lookup)
    submitted = []
    monkeypatch.setattr(connection, "submit", lambda prepared, display, **_:
                        submitted.append((prepared.resource_id, display)) or {"status": "pending"})
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {"X-Lumina-Contribution": "1"}
    ownership = client.post("/api/contributions/original-source", headers=headers,
                            json={**reference, "account_id": "maker"})
    assert ownership.status_code == 200
    assert ownership.json() == {"eligible": allowed}
    prepared = client.post("/api/contributions/prepare", headers=headers, json={"kind": "luts", "key": "BW"}).json()
    payload = {"kind": "luts", "key": "BW", "name": "Updated BW", "fingerprint": prepared["fingerprint"],
               "product": {}, "consent": True, "account_id": "maker", "attribution": {"relationship": "original"},
               "filaments": [{"brand": "Brand", "material_type": "PLA", "color_name": slot["color_name"]}
                             for slot in prepared["display"]["filaments"]]}
    response = client.post("/api/contributions/submit", headers=headers, json=payload)
    assert response.status_code == (200 if allowed else 422), response.text
    if allowed:
        resource_id, display = submitted.pop()
        assert resource_id == reference["resource_id"]
        assert display["attribution"] == {"relationship": "original"}
        assert prepared["display"]["license"] == "CC-BY-4.0"
        assert client.post("/api/contributions/submit", headers=headers,
                           json={**payload, "updates_resource_id": "lut_other"}).status_code == 422
    assert not submitted


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
        def receive(prepared, display, *, expected_subject, **kwargs):
            assert kwargs["print_images"] == [SAMPLE_PRINT_PHOTO]
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
                "print_images": [SAMPLE_PRINT_PHOTO],
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


def test_new_submission_requires_valid_print_photo_and_forwards_to_registry(tmp_path, monkeypatch):
    from api.services.resource_contribution import ContributionConnection
    from core.resource_contribution import PreparedContribution

    path = tmp_path / "BW.npy"
    np.save(path, np.arange(96, dtype=np.uint8).reshape(32, 3))
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda _: str(path))
    received_kwargs = []
    monkeypatch.setattr(
        "api.routers.contributions.connection.submit",
        lambda prepared, display, **kwargs: received_kwargs.append(kwargs) or {"status": "pending"},
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {"X-Lumina-Contribution": "1"}
    prepared = client.post("/api/contributions/prepare", headers=headers, json={"kind": "luts", "key": "BW"}).json()
    base_payload = {
        "kind": "luts",
        "key": "BW",
        "name": "BW",
        "fingerprint": prepared["fingerprint"],
        "product": {},
        "consent": True,
        "account_id": "maker",
        "attribution": {"relationship": "original"},
        "filaments": [
            {"brand": "Brand", "material_type": "PLA", "color_name": slot["color_name"]}
            for slot in prepared["display"]["filaments"]
        ],
    }
    missing = client.post("/api/contributions/submit", headers=headers, json=base_payload)
    assert missing.status_code == 422
    assert "print photo" in missing.json()["detail"].lower()

    corrupt = client.post("/api/contributions/submit", headers=headers, json={**base_payload, "print_images": ["bm90LWFuLWltYWdl"]})
    assert corrupt.status_code == 422

    accepted = client.post(
        "/api/contributions/submit",
        headers=headers,
        json={**base_payload, "print_images": [f"data:image/png;base64,{SAMPLE_PRINT_PHOTO}"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert received_kwargs[-1]["print_images"] == [SAMPLE_PRINT_PHOTO]

    service = ContributionConnection()
    monkeypatch.setattr(service, "status", lambda: {"state": "connected", "subject": "maker"})
    monkeypatch.setattr(service, "history", lambda: [])
    calls = []

    def fake_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if endpoint == "/me/material-submissions":
            return {"submission_id": "sub_1", "status": "draft"}
        return {"submission_id": "sub_1", "status": "pending"}

    monkeypatch.setattr(service, "_request", fake_request)
    mat_prepared = PreparedContribution(
        "materials", "fixture", "a" * 64, {}, {}, {"material.json": b"{}", "stage_A_parameters.json": b"{}"}
    )
    service.submit(mat_prepared, {"brand": "B", "material_name": "Red", "material_type": "PLA"}, print_images=[SAMPLE_PRINT_PHOTO])
    assert calls[-1][1] == "/me/material-submissions/sub_1/submit"
    assert calls[-1][2]["json"] == {"print_images": [SAMPLE_PRINT_PHOTO]}

    calls.clear()
    lut_prepared = PreparedContribution("luts", "fixture", "b" * 64, {}, {}, {"calibration.npy": b"data"})
    service.submit(lut_prepared, {"brand": "B", "name": "BW", "material_type": "PLA"}, print_images=[SAMPLE_PRINT_PHOTO])
    assert calls[-1][1] == "/me/lut-submissions"
    assert json.loads(calls[-1][2]["data"]["print_images"]) == [SAMPLE_PRINT_PHOTO]


def test_structured_print_image_slots_enforced_for_materials_and_luts(tmp_path, monkeypatch):
    from core.single_stage import material_files
    from core.single_stage.material_library import save_stage_a_material_archive

    mat_dir = tmp_path / "structured-materials"
    saved = save_stage_a_material_archive(
        material_name="Red",
        brand="Brand",
        materials_dir=str(mat_dir),
        params_payload={
            "param_type": "stage_A",
            "parameters": {
                "channels": [{"color_name": "Red", "E": [0.4, 0.1, 0.3], "k": [8, 7, 9]}],
                "substrates": [
                    {"substrate_id": "white", "C0": [0.9, 0.9, 0.9]},
                    {"substrate_id": "black", "C0": [0.025, 0.025, 0.025]},
                ],
            },
            "meta": {"schema_version": "1"},
            "source": {"spec": {"layer_height_mm": 0.08}},
        },
        fit_summary={"mean_delta_e": 1.8},
        source_summary={},
        material_summary={},
    )
    mat_key = saved.material_summary["directory_name"]
    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(mat_dir))

    lut_path = tmp_path / "BW.npy"
    np.save(lut_path, np.arange(96, dtype=np.uint8).reshape(32, 3))
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda _: str(lut_path))

    received_kwargs = []
    monkeypatch.setattr(
        "api.routers.contributions.connection.submit",
        lambda prepared, display, **kwargs: (
            received_kwargs.append(kwargs) or {"kind": prepared.kind, "status": "pending"}
        ),
    )

    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)
    headers = {"X-Lumina-Contribution": "1"}

    mat_prep = client.post("/api/contributions/prepare", headers=headers, json={"kind": "materials", "key": mat_key}).json()
    mat_base = {
        "kind": "materials",
        "key": mat_key,
        "fingerprint": mat_prep["fingerprint"],
        "name": "Red",
        "description": "",
        "consent": True,
        "account_id": "maker",
        "attribution": {"relationship": "original"},
        "product": {"brand": "Brand", "material_type": "PLA"},
        "filaments": [],
    }
    missing_finished = client.post(
        "/api/contributions/submit",
        headers=headers,
        json={
            **mat_base,
            "print_images": [
                {"role": "white_card", "data": SAMPLE_PRINT_PHOTO},
                {"role": "black_card", "data": SAMPLE_PRINT_PHOTO},
            ],
        },
    )
    assert missing_finished.status_code == 422
    assert "finished print" in missing_finished.json()["detail"].lower()

    wrong_slot = client.post(
        "/api/contributions/submit",
        headers=headers,
        json={
            **mat_base,
            "print_images": [
                {"role": "calibration_board", "data": SAMPLE_PRINT_PHOTO},
                {"role": "finished_print", "data": SAMPLE_PRINT_PHOTO},
            ],
        },
    )
    assert wrong_slot.status_code == 422

    mat_full = [
        {"role": "white_card", "data": SAMPLE_PRINT_PHOTO},
        {"role": "black_card", "data": SAMPLE_PRINT_PHOTO},
        {"role": "finished_print", "data": SAMPLE_PRINT_PHOTO},
    ]
    mat_ok = client.post(
        "/api/contributions/submit",
        headers=headers,
        json={**mat_base, "print_images": mat_full},
    )
    assert mat_ok.status_code == 200, mat_ok.text
    assert received_kwargs[-1]["print_images"] == mat_full

    lut_prep = client.post("/api/contributions/prepare", headers=headers, json={"kind": "luts", "key": "BW"}).json()
    lut_base = {
        "kind": "luts",
        "key": "BW",
        "fingerprint": lut_prep["fingerprint"],
        "name": "BW",
        "description": "",
        "consent": True,
        "account_id": "maker",
        "attribution": {"relationship": "original"},
        "product": {},
        "filaments": [
            {"brand": "Brand", "material_type": "PLA", "color_name": slot["color_name"]}
            for slot in lut_prep["display"]["filaments"]
        ],
    }
    lut_missing_finished = client.post(
        "/api/contributions/submit",
        headers=headers,
        json={**lut_base, "print_images": [{"role": "calibration_board", "data": SAMPLE_PRINT_PHOTO}]},
    )
    assert lut_missing_finished.status_code == 422

    lut_dual_boards = [
        {"role": "calibration_board", "data": SAMPLE_PRINT_PHOTO},
        {"role": "calibration_board", "data": SAMPLE_PRINT_PHOTO},
        {"role": "finished_print", "data": SAMPLE_PRINT_PHOTO},
        {"role": "finished_print", "data": SAMPLE_PRINT_PHOTO},
    ]
    lut_ok = client.post(
        "/api/contributions/submit",
        headers=headers,
        json={**lut_base, "print_images": lut_dual_boards},
    )
    assert lut_ok.status_code == 200, lut_ok.text
    assert received_kwargs[-1]["print_images"] == lut_dual_boards
