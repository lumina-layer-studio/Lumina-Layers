import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.resource_activity import router
from api.services.resource_contribution import ContributionConnection, ContributionError


@pytest.mark.parametrize("kind", ["materials", "luts"])
@pytest.mark.parametrize("static", [True, False])
def test_public_stats_wait_does_not_block_account_history(monkeypatch, tmp_path, kind, static):
    from core import public_resources
    from core.single_stage import material_files
    from utils.lut_manager import LUTManager

    server = "https://accounts.example/api/material-registry/v1"
    monkeypatch.setenv("LUMINA_CONTRIBUTION_REGISTRY_URL", server)
    source = "https://public.example/public/v1" if static else server
    monkeypatch.setattr(public_resources, "material_registry_url", lambda: source)
    monkeypatch.setattr(public_resources, "lut_registry_url", lambda: source)
    monkeypatch.setattr(public_resources, "is_static_catalog", lambda _: static)
    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(tmp_path))
    monkeypatch.setattr(LUTManager, "cloud_lut_sync_dir", lambda: tmp_path)
    connection = ContributionConnection()
    connection.source()
    connection.subject, connection._token = "maker", "studio_current"
    monkeypatch.setattr(connection, "status", lambda: {"state": "connected", "subject": "maker"})
    entered, release, history_started = Event(), Event(), Event()
    public_requests = []

    def handler(request):
        if request.url.path.endswith("/me/resource-reports"):
            return httpx.Response(200, json={"items": [], "subject": "maker"})
        public_requests.append(request)
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, json={"schema_version": 1, "items": [], "subject": None})

    client_class = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_class(
        transport=httpx.MockTransport(handler), **kwargs))

    def history():
        history_started.set()
        return connection.feedback_history(0)

    with ThreadPoolExecutor(2) as pool:
        stats = pool.submit(connection.activity, kind, ["fixture"])
        assert entered.wait(3)
        account = pool.submit(history)
        assert history_started.wait(3)
        try:
            assert account.result(timeout=1) == {"items": [], "subject": "maker"}
        finally:
            release.set()
            result = stats.result(timeout=5)
            account.result(timeout=5)
    assert result["subject"] == "maker"
    assert len(public_requests) == 1
    assert not public_requests[0].headers.get("authorization")


@pytest.mark.parametrize("static", [True, False])
def test_public_stats_ignore_a_stale_subject_without_credentials(monkeypatch, tmp_path, static):
    from core import public_resources
    from core.single_stage import material_files

    monkeypatch.setattr(public_resources, "material_registry_url", lambda: "https://public.example/public/v1")
    monkeypatch.setattr(public_resources, "is_static_catalog", lambda _: static)
    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(tmp_path))
    connection = ContributionConnection()
    connection.source()
    connection.subject = "previous-account"
    monkeypatch.setattr(connection, "status", lambda: pytest.fail("Public stats must not verify the account"))
    client_class = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_class(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"schema_version": 1, "items": [], "subject": None})),
        **kwargs))
    assert connection.activity("materials", ["fixture"])["subject"] is None


@pytest.mark.parametrize("http_status", [401, 403, 500])
def test_public_stats_failure_keeps_the_account_connected(monkeypatch, http_status):
    from core import public_resources

    monkeypatch.setattr(public_resources, "is_static_catalog", lambda _: False)
    connection = ContributionConnection()
    connection.source()
    connection.subject, connection._token = "maker", "studio_current"
    client_class = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_class(
        transport=httpx.MockTransport(lambda _: httpx.Response(http_status)), **kwargs))
    with pytest.raises(ContributionError) as error:
        connection.activity("materials", ["fixture"])
    assert error.value.status == 502
    assert connection._token == "studio_current" and connection.subject == "maker"


def test_local_proxy_requires_local_header_and_never_exposes_download_increment():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/community/materials/mine").status_code == 403
    assert client.get("/api/community/materials/mine", headers={
        "X-Lumina-Contribution": "1", "Origin": "https://unrelated.invalid",
    }).status_code == 403
    payload = {"resource_id": "mat", "revision_id": "rev", "content_hash": "abc",
               "action": "downloaded", "enabled": True, "account_id": "maker"}
    assert client.put("/api/community/materials/activity", json=payload,
                      headers={"X-Lumina-Contribution": "1"}).status_code == 422


def test_activity_writes_keep_account_identity_and_download_failure_is_nonfatal(monkeypatch):
    connection = ContributionConnection()
    monkeypatch.setattr(connection, "status", lambda: {"state": "connected", "subject": "maker"})
    writes = []
    monkeypatch.setattr(connection, "_request", lambda *args, **kwargs: writes.append(kwargs["json"]) or {})
    row = {"lut_id": "lut", "revision_id": "rev", "content_hash": "abc"}
    assert connection.record_download("luts", row, None) is None
    assert connection.record_download("luts", row, "different-account") is False
    assert not writes
    assert connection.record_download("luts", row, "maker")
    assert writes[0]["action"] == "downloaded"
    assert writes[0]["account_id"] == "maker"
    def offline(*args, **kwargs):
        raise ContributionError(502, "offline")
    monkeypatch.setattr(connection, "_request", offline)
    assert connection.record_download("luts", row, "maker") is False


def test_local_lut_identity_requires_matching_bytes_and_rejects_ambiguous_content(tmp_path, monkeypatch):
    from api.services.resource_activity import local_resource_references
    from api.services import lut_registry_sync
    from utils.lut_manager import LUTManager
    path = tmp_path / "same-name.npy"
    path.write_bytes(b"example")
    digest = hashlib.sha256(b"example").hexdigest()
    index = {"luts": {"one": {"lut_id": "one", "revision_id": "rev", "content_hash": "sha256:" + digest}}}
    monkeypatch.setattr(lut_registry_sync, "read_installed_index", lambda: index)
    monkeypatch.setattr(LUTManager, "get_all_lut_files", lambda: {"Same name": str(path)})
    assert local_resource_references("luts")["items"]["Same name"]["resource_id"] == "one"
    index["luts"]["two"] = {**index["luts"]["one"], "lut_id": "two"}
    assert local_resource_references("luts")["items"] == {}
    del index["luts"]["two"]
    path.write_bytes(b"locally-edited")
    assert local_resource_references("luts")["items"] == {}


def test_contribution_origin_survives_lut_copy_and_edit_without_guessing_an_author(tmp_path, monkeypatch):
    from api.services.resource_activity import local_resource_origin
    from api.services import lut_registry_sync
    from utils.lut_manager import LUTManager
    path = tmp_path / "renamed.npy"
    path.write_bytes(b"calibration")
    content_hash = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    row = {"lut_id": "lut_one", "revision_id": "rev_one", "content_hash": content_hash,
           "installed_path": "old-name.npy", "display": {"contributor_name": "Jane", "license": "CC-BY-4.0"}}
    index = {"luts": {"one": row}}
    monkeypatch.setattr(lut_registry_sync, "read_installed_index", lambda: index)
    monkeypatch.setattr(lut_registry_sync, "_safe_index_installed_path", lambda row: tmp_path / row["installed_path"])
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda _: str(path))
    copied = local_resource_origin("luts", "Renamed")
    assert copied["reference"]["resource_id"] == "lut_one"
    assert copied["original_author"] == "Jane"
    row["installed_path"] = path.name
    path.write_bytes(b"edited-calibration")
    edited = local_resource_origin("luts", "Renamed")
    assert edited["modified"] is True
    assert edited["reference"]["content_hash"] == content_hash
    row["installed_path"] = "old-name.npy"
    path.write_bytes(b"calibration")
    index["luts"]["two"] = {**row, "lut_id": "lut_two", "display": {"contributor_name": "Pat"}}
    ambiguous = local_resource_origin("luts", "Renamed")
    assert ambiguous["reference"] is None and ambiguous["original_author"] == ""


@pytest.mark.parametrize("success", [True, False])
def test_lut_download_record_occurs_only_after_successful_install(monkeypatch, success):
    from api.routers import lut_registry
    calls = []
    row = {"lut_id": "lut", "revision_id": "rev", "content_hash": "abc"}
    def install(**kwargs):
        if not success:
            raise lut_registry.LutRegistryPackageError("damaged")
        calls.append("installed")
        return row
    monkeypatch.setattr(lut_registry, "install_lut_package", install)
    monkeypatch.setattr(lut_registry, "invalidate_lut_details_service_cache", lambda: None)
    monkeypatch.setattr(lut_registry.connection, "record_download", lambda *args: calls.append("recorded") or True)
    app = FastAPI()
    app.include_router(lut_registry.router)
    response = TestClient(app).post("/api/lut-registry/install", json={"lut_id": "lut", "revision_id": "rev", "account_id": "maker"})
    assert calls == (["installed", "recorded"] if success else [])
    if success:
        assert response.json()["activity_recorded"] is True
    else:
        assert response.status_code != 200


@pytest.mark.parametrize("success", [True, False])
def test_material_download_record_occurs_only_after_successful_install(monkeypatch, success):
    from api.routers import material_sync
    calls = []
    row = {"material_id": "mat", "revision_id": "rev", "content_hash": "abc"}
    monkeypatch.setattr(material_sync, "_find_catalog_install_entry", lambda payload: row)
    def install(**kwargs):
        if not success:
            raise ValueError("damaged")
        calls.append("installed")
        return {**row, "installed_materials": [{"material_name": "Test PLA", "directory_name": "test/pla"}]}
    monkeypatch.setattr(material_sync, "install_material_registry_package", install)
    monkeypatch.setattr(material_sync.connection, "record_download", lambda *args: calls.append("recorded") or False)
    app = FastAPI()
    app.include_router(material_sync.router)
    response = TestClient(app).post("/api/material-sync/install-from-registry", json={
        "material_id": "mat", "revision_id": "rev", "account_id": "maker",
        "package_url": "/packages/mat.zip", "package_sha256": "a" * 64,
    })
    assert calls == (["installed", "recorded"] if success else [])
    if success:
        assert response.status_code == 200
        assert response.json()["activity_recorded"] is False
        assert response.json()["installed_count"] == 1
    else:
        assert response.status_code != 200
