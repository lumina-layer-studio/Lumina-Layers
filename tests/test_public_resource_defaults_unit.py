"""Public resource defaults never turn a catalog check into a download."""

import httpx

from core.single_stage.material_registry_client import list_material_registry_catalog
from api.services.lut_registry_sync import get_registry_config
from core.public_resources import GITHUB_CATALOG_URL, PUBLIC_REGISTRY_URL, registry_read_token


def test_unconfigured_source_reads_public_channels_without_old_token(monkeypatch):
    for key in ("LUMINA_MATERIAL_REGISTRY_URL", "LUMINA_MATERIAL_REGISTRY_CHANNELS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_TOKEN", "old-private-token")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"schema_version": 1, "materials": []})

    result = list_material_registry_catalog(transport=httpx.MockTransport(respond), use_cache=False)
    assert result["materials"] == []
    assert len(requests) == 1
    assert str(requests[0].url) == GITHUB_CATALOG_URL + "/materials/catalog.json"
    assert result["channels"] == ["official", "community"]
    assert "authorization" not in requests[0].headers


def test_lut_default_and_explicit_disable(monkeypatch):
    for key in ("LUMINA_MATERIAL_REGISTRY_URL", "LUMINA_LUT_REGISTRY_URL"):
        monkeypatch.delenv(key, raising=False)
    assert get_registry_config().base_url == GITHUB_CATALOG_URL
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "")
    assert not get_registry_config().configured


def test_distribution_injected_service_remains_separate(monkeypatch):
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", PUBLIC_REGISTRY_URL)
    monkeypatch.delenv("LUMINA_LUT_REGISTRY_URL", raising=False)
    assert get_registry_config().base_url == PUBLIC_REGISTRY_URL
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://custom.test/api")
    assert get_registry_config().base_url == "https://custom.test/api"
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "")
    assert not get_registry_config().configured


def test_private_lut_source_inherits_credentials_only_for_the_same_origin(monkeypatch):
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "https://private.test/api")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_TOKEN", "private-token")
    monkeypatch.delenv("LUMINA_LUT_REGISTRY_TOKEN", raising=False)
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://private.test/api/")
    assert registry_read_token("LUT") == "private-token"
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://another.test/api")
    assert registry_read_token("LUT") == ""
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_TOKEN", "lut-token")
    assert registry_read_token("LUT") == "lut-token"
    monkeypatch.delenv("LUMINA_LUT_REGISTRY_URL")
    assert registry_read_token("LUT") == "lut-token"
