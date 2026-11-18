import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.resources import router
from api.services.lut_registry_sync import get_registry_config
from api.services.resource_contribution import ContributionConnection
from core.public_resources import (
    GITHUB_CATALOG_URL, is_static_catalog, lut_registry_url, material_registry_url, registry_read_token,
)
from core.resource_sources import save_source_preferences, source_preferences, sources_path
from core.single_stage.material_registry_client import list_material_registry_catalog


@pytest.fixture(autouse=True)
def isolated_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_SETTINGS_PATH", str(tmp_path / "user_settings.json"))


def test_switching_static_sources_preserves_default_and_never_forwards_private_credentials(monkeypatch):
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "https://private.test/api")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_TOKEN", "private-secret")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://lut.test/api")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_TOKEN", "lut-secret")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", "team")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_CHANNELS", "team")
    account_server = ContributionConnection().source()
    for mode, mirror, expected in [
        ("github", "", GITHUB_CATALOG_URL),
        ("mirror", "https://mirror.test/public/v1/", "https://mirror.test/public/v1"),
    ]:
        save_source_preferences(mode, mirror)
        assert material_registry_url() == lut_registry_url() == expected
        assert is_static_catalog(expected)
        assert registry_read_token("MATERIAL") == registry_read_token("LUT") == ""
        assert get_registry_config().channels == ("official", "community")
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"schema_version": 1, "materials": []})
        list_material_registry_catalog(transport=httpx.MockTransport(handler), use_cache=False)
        assert str(requests[0].url) == expected + "/materials/catalog.json"
        assert "authorization" not in requests[0].headers
        assert ContributionConnection().source() == account_server
    save_source_preferences("default")
    assert material_registry_url() == "https://private.test/api"
    assert lut_registry_url() == "https://lut.test/api"
    assert registry_read_token("MATERIAL") == "private-secret"
    assert registry_read_token("LUT") == "lut-secret"


def test_preferences_survive_reload_and_are_workspace_local(tmp_path, monkeypatch):
    save_source_preferences("mirror", "https://mirror.test/public/v1")
    assert source_preferences() == {"mode": "mirror", "mirror_url": "https://mirror.test/public/v1"}
    assert not list(tmp_path.glob("*.tmp"))
    monkeypatch.setenv("LUMINA_SETTINGS_PATH", str(tmp_path / "another" / "user_settings.json"))
    assert source_preferences()["mode"] == "default"
    monkeypatch.setenv("LUMINA_SETTINGS_PATH", str(tmp_path / "user_settings.json"))
    assert source_preferences()["mode"] == "mirror"


@pytest.mark.parametrize("url", [
    "http://remote.test/v1", "https://user:pass@mirror.test/v1", "https://mirror.test/v1?token=secret",
    "https://mirror.test/v1#x", "https://mirror.test/a/../v1", "https://mirror.test/%2e/v1",
    "file:///tmp/v1", "https://mirror.test:bad/v1", "https://mirror.test/\nv1",
])
def test_invalid_mirror_does_not_replace_valid_settings(url):
    save_source_preferences("github")
    before = sources_path().read_bytes()
    with pytest.raises(ValueError):
        save_source_preferences("mirror", url)
    assert sources_path().read_bytes() == before


def test_source_changes_require_local_header_and_do_not_fetch_or_install(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    import api.routers.resources as routes
    monkeypatch.setattr(routes, "material_seed_status", lambda: {"available": False})
    monkeypatch.setattr(routes, "lut_seed_status", lambda: {"available": False})
    with TestClient(app) as client:
        assert client.put("/api/resources/source", json={"mode": "github"}).status_code == 403
        assert client.put("/api/resources/source", headers={"X-Lumina-Contribution": "1", "Origin": "https://unrelated.test"}, json={"mode": "github"}).status_code == 403
        response = client.put("/api/resources/source", headers={"X-Lumina-Contribution": "1"}, json={"mode": "github"})
    assert response.status_code == 200
    assert response.json()["source_settings"]["urls"]["luts"] == GITHUB_CATALOG_URL
    assert list(tmp_path.iterdir()) == [sources_path()]


def test_newer_settings_are_preserved_and_default_remains_usable(monkeypatch):
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "https://default.test/api")
    sources_path().write_text(json.dumps({"schema_version": 99, "mode": "new"}))
    before = sources_path().read_bytes()
    assert material_registry_url() == "https://default.test/api"
    with pytest.raises(ValueError, match="Unsupported"):
        save_source_preferences("github")
    assert sources_path().read_bytes() == before
