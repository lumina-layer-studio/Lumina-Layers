"""Registry catalog errors identify a missing service endpoint without exposing URLs."""

from collections.abc import Iterator
from functools import partial

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from api.routers import lut_registry, material_sync
from api.services import lut_registry_sync
from core.single_stage import material_registry_client


@pytest.fixture
def registry_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    for family in ("MATERIAL", "LUT"):
        for suffix in ("URL", "TOKEN", "FALLBACK_URL"):
            monkeypatch.delenv(f"LUMINA_{family}_REGISTRY_{suffix}", raising=False)
        monkeypatch.setenv(f"LUMINA_{family}_REGISTRY_CHANNELS", "official")
    app = FastAPI()
    app.include_router(lut_registry.router)
    app.include_router(material_sync.router)
    with TestClient(app) as client:
        yield client


def _use_registry_transport(
    monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport,
) -> None:
    monkeypatch.setattr(
        lut_registry_sync,
        "_make_http_client",
        lambda: httpx.Client(transport=transport),
    )
    monkeypatch.setattr(
        material_sync,
        "list_material_registry_catalog",
        partial(
            material_registry_client.list_material_registry_catalog,
            transport=transport,
            use_cache=False,
        ),
    )


@pytest.mark.parametrize("family", ["LUT", "MATERIAL"])
@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8000/api/material-registry/v1",
        "https://private-registry.example/confidential/tenant",
    ],
)
def test_catalog_404_identifies_registry_configuration_without_retrying(
    registry_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    base_url: str,
) -> None:
    requests: list[httpx.Request] = []

    def missing_endpoint(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(404, json={"detail": "Not Found"})

    # The LUT client inherits the material Registry address when no separate
    # LUT address is configured, including the original localhost failure.
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", base_url)
    monkeypatch.setenv(f"LUMINA_{family}_REGISTRY_FALLBACK_URL", "https://backup.example/v1")
    _use_registry_transport(monkeypatch, httpx.MockTransport(missing_endpoint))
    route = "/api/lut-registry/catalog" if family == "LUT" else "/api/material-sync/catalog"
    response = registry_client.get(route, params={"limit": 100, "offset": 0})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "404" in detail
    assert f"LUMINA_{family}_REGISTRY_URL" in detail
    assert "Registry service" in detail
    assert httpx.URL(base_url).host not in detail
    assert "confidential/tenant" not in detail
    assert len(requests) == 1
    expected_path = "/luts/catalog" if family == "LUT" else "/materials/catalog"
    assert str(requests[0].url).startswith(base_url + expected_path + "?")


@pytest.mark.parametrize("family", ["LUT", "MATERIAL"])
def test_configured_local_registry_catalog_remains_usable(
    registry_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
) -> None:
    monkeypatch.setenv(
        "LUMINA_MATERIAL_REGISTRY_URL",
        "http://127.0.0.1:8000/api/material-registry/v1",
    )
    _use_registry_transport(
        monkeypatch,
        httpx.MockTransport(
            lambda request: httpx.Response(200, json={"items": [], "materials": []}),
        ),
    )
    route = "/api/lut-registry/catalog" if family == "LUT" else "/api/material-sync/catalog"
    response = registry_client.get(route)

    assert response.status_code == 200
    assert response.json()["items" if family == "LUT" else "materials"] == []
