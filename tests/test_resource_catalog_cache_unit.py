import httpx
import pytest

from core.registry_transport import fetch_catalog


def test_public_catalog_survives_restart_and_uses_etag(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_FALLBACK_URL", "")
    calls = []
    state = ["online"]
    def handler(request):
        calls.append(request)
        if state[0] == "offline":
            raise httpx.ConnectError("offline", request=request)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, headers={"etag": '"v1"'}, json={"materials": [], "total_count": 0})
    def read():
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return fetch_catalog(client=client, primary="https://public.test/v1", family="MATERIAL",
                                 suffix="/materials/catalog", channels=["official"], headers={}, params=[], cache_dir=tmp_path)
    assert read().status_code == 200
    assert read().json() == {"materials": [], "total_count": 0}
    assert calls[-1].headers["if-none-match"] == '"v1"'
    state[0] = "offline"
    cached = read()
    assert cached.headers["x-lumina-catalog-cached"] == "true"
    assert cached.headers["x-lumina-catalog-fetched-at"]


@pytest.mark.parametrize("status", [401, 403, 302])
def test_cache_does_not_hide_auth_or_redirect_failures(tmp_path, status):
    def read(code):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(code, json={"materials": []}))) as client:
            return fetch_catalog(client=client, primary="https://public.test/v1", family="MATERIAL",
                                 suffix="/materials/catalog", channels=["official"], headers={}, params=[], cache_dir=tmp_path)
    read(200)
    try:
        response = read(status)
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == status
    else:
        assert response.status_code == status
        assert "x-lumina-catalog-cached" not in response.headers


def test_private_catalog_is_not_persisted(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"materials": []}))) as client:
        fetch_catalog(client=client, primary="https://private.test/v1", family="MATERIAL",
                      suffix="/materials/catalog", channels=["team"], headers={"Authorization": "Bearer secret"},
                      params=[], cache_dir=tmp_path)
    assert not list(tmp_path.iterdir())


def test_catalog_scope_tracks_source_channels_and_credentials_without_exposing_them():
    from core.registry_catalog_cache import catalog_source_scope
    scope = catalog_source_scope("https://one.test", ["team", "official"], "user-A")
    assert scope == catalog_source_scope("https://one.test", ["official", "team"], "user-A")
    assert "user-A" not in scope
    assert scope != catalog_source_scope("https://two.test", ["team", "official"], "user-A")
    assert scope != catalog_source_scope("https://one.test", ["team"], "user-A")
    assert scope != catalog_source_scope("https://one.test", ["team", "official"], "user-B")


def test_background_full_snapshot_supplies_offline_pagination_and_search(tmp_path, monkeypatch):
    from core.single_stage import material_files
    from core.single_stage.material_registry_client import list_material_registry_catalog
    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(tmp_path))
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "https://public.test/v1")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_FALLBACK_URL", "")
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_TOKEN", raising=False)
    status = [200]
    entries = [{"material_id": f"mat_{i}", "revision_id": "v1", "display": {"name": f"Sample {i}"}} for i in range(30)]
    def handler(request):
        if status[0] == 0:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(status[0], json={"materials": entries, "total_count": len(entries), "offset": 0})
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))
    assert list_material_registry_catalog(use_cache=False)["count"] == 30
    status[0] = 0
    page = list_material_registry_catalog(limit=24, offset=24, use_cache=False)
    assert page["cached"] is True
    assert page["total_count"] == 30
    assert page["count"] == 6
    assert page["materials"][0]["material_id"] == "mat_24"
    filtered = list_material_registry_catalog(limit=24, query="Sample 29", use_cache=False)
    assert [entry["material_id"] for entry in filtered["materials"]] == ["mat_29"]
    status[0] = 403
    with pytest.raises(RuntimeError, match="request failed"):
        list_material_registry_catalog(limit=24, offset=0, use_cache=False)


def test_background_lut_snapshot_supplies_offline_ui_pages(tmp_path, monkeypatch):
    from api.services import lut_registry_sync as sync
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(tmp_path / "Cloud"))
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://public.test/v1")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_FALLBACK_URL", "")
    monkeypatch.delenv("LUMINA_LUT_REGISTRY_TOKEN", raising=False)
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_TOKEN", raising=False)
    status = [200]
    items = [{"lut_id": f"lut_{i}", "revision_id": "v1"} for i in range(136)]
    def handler(request):
        if not status[0]:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(status[0], json={"items": items, "total": len(items)})
    monkeypatch.setattr(sync, "_make_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert sync.fetch_remote_catalog()["total"] == 136
    status[0] = 0
    first = sync.fetch_remote_catalog(limit=100)
    last = sync.fetch_remote_catalog(limit=100, offset=100)
    assert first["cached"] and last["cached"]
    assert len(first["items"]) == 100 and len(last["items"]) == 36
    assert last["items"][0]["lut_id"] == "lut_100"
    status[0] = 403
    with pytest.raises(sync.LutRegistryRemoteError, match="403"):
        sync.fetch_remote_catalog(limit=100)
