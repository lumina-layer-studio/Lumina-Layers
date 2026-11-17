"""Static indexes preserve Registry identity without calling the hosted service."""

import hashlib
import json

import httpx
import pytest

from core.public_catalog import fetch_static_catalog, read_document, snapshot_activity
from core.public_resources import registry_read_token
from core.registry_transport import fallback_base, fetch_catalog

BASE = "https://raw.githubusercontent.com/example/materials/master/public/v1"


@pytest.fixture
def static_source(monkeypatch):
    monkeypatch.setenv("LUMINA_PUBLIC_CATALOG_URL", BASE)
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_URL", raising=False)
    monkeypatch.delenv("LUMINA_LUT_REGISTRY_URL", raising=False)


def test_search_paging_and_refresh_use_one_cached_index_without_packages(static_source, tmp_path):
    requests = []
    rows = [{"material_id": f"m{i}", "revision_id": "r1", "channel": "community",
             "display": {"brand": "Aliz", "series": "PLA Basic", "color_code": str(i)}} for i in range(10)]
    def handler(request):
        requests.append(request)
        assert str(request.url) == BASE + "/materials/catalog.json"
        assert not request.headers.get("authorization")
        if request.headers.get("if-none-match") == '"one"':
            return httpx.Response(304)
        return httpx.Response(200, headers={"etag": '"one"'}, json={
            "schema_version": 1, "generated_at": "2026-11-16T00:00:00Z", "materials": rows,
        })
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        def read(params, refresh=False):
            return fetch_catalog(client=client, primary=BASE, family="MATERIAL", suffix="/materials/catalog",
                                 channels=["community"], headers={}, params=params, cache_dir=tmp_path, force_refresh=refresh)
        assert read({"limit": 3}).json()["total_count"] == 10
        assert [row["material_id"] for row in read({"offset": 9}).json()["materials"]] == ["m9"]
        assert read({"q": "aliz 6"}).json()["materials"][0]["material_id"] == "m6"
        assert len(requests) == 1
        assert read({}, True).json()["count"] == 10
        assert len(requests) == 2
        assert requests[-1].headers["if-none-match"] == '"one"'
        assert read({}).json()["count"] == 10
        assert len(requests) == 2


@pytest.mark.parametrize("status", [401, 403, 302, 404, 503])
def test_refresh_does_not_hide_denial_or_redirect_and_keeps_offline_cache(tmp_path, status):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, json={"schema_version": 1, "materials": []},
    ))) as client:
        read_document(client, BASE, "/materials/catalog.json", tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status))) as client:
        if status == 503:
            assert read_document(client, BASE, "/materials/catalog.json", tmp_path, refresh=True).headers["x-lumina-catalog-cached"] == "true"
        else:
            with pytest.raises(httpx.HTTPStatusError):
                read_document(client, BASE, "/materials/catalog.json", tmp_path, refresh=True)


def test_static_source_never_inherits_tokens_or_falls_back_to_official_cloud(static_source, monkeypatch):
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", BASE)
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_TOKEN", "stale-token")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_TOKEN", "another-token")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_FALLBACK_URL", "https://official.example/api")
    assert registry_read_token("MATERIAL") == registry_read_token("LUT") == ""
    assert fallback_base(BASE, "MATERIAL") is None
    with httpx.Client(headers={"Authorization": "Bearer inherited"}) as client:
        with pytest.raises(ValueError, match="anonymous"):
            read_document(client, BASE, "/materials/catalog.json", None)
    with httpx.Client() as client:
        with pytest.raises(ValueError, match="public channels"):
            fetch_static_catalog(client=client, primary=BASE, family="MATERIAL", channels=["team"], params=[], cache_dir=None)


def test_visible_lut_previews_are_separate_and_verified(static_source, tmp_path):
    artwork = {"schema_version": 1, "lut_id": "lut", "revision_id": "r1", "content_hash": "abc",
               "display": {"lut_board_preview": {"kind": "test-artwork"}}}
    raw = json.dumps(artwork, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    row = {"lut_id": "lut", "revision_id": "r1", "content_hash": "abc", "channel": "official", "preview_sha256": digest}
    requests = []
    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={"schema_version": 1, "items": [row]}) if request.url.path.endswith("catalog.json") else httpx.Response(200, content=raw)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        def read(params):
            return fetch_static_catalog(client=client, primary=BASE, family="LUT", channels=["official"], params=params, cache_dir=tmp_path)
        assert read({}).json()["total"] == 1
        assert len(requests) == 1
        assert read([("preview_id", "lut")]).json()["previews"][0]["revision_id"] == "r1"
        assert requests[-1].endswith(f"/luts/previews/{digest}.json")
        assert len(requests) == 2
        read([("preview_id", "lut")])
        assert len(requests) == 2
    raw = b'{"schema_version":1,"lut_id":"other"}'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="checksum"):
            fetch_static_catalog(client=client, primary=BASE, family="LUT", channels=["official"],
                                 params=[("preview_id", "lut")], cache_dir=None)


def test_public_counts_are_not_user_state_and_missing_is_not_zero(tmp_path):
    payload = {"schema_version": 1, "generated_at": "2026-11-16T00:00:00Z", "items": [
        {"resource_id": "one", "likes": 0, "saves": 2, "downloads": 10,
         "liked": True, "user_email": "must-not-pass@example.com",
         "revisions": [{"revision_id": "r1", "content_hash": "abc"}]},
    ]}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        result = snapshot_activity(client=client, base=BASE, kind="materials", ids=["one", "missing"], cache_dir=tmp_path)
    assert result["subject"] is None
    assert len(result["items"]) == 1
    row = result["items"][0]
    assert row["likes"] == 0 and row["saves"] == 2
    assert row["liked"] is False and row["saved"] is False
    assert row["snapshot_at"] == payload["generated_at"]
    assert "user_email" not in row


def test_static_packages_cannot_leave_the_selected_repository(static_source):
    from core.single_stage.material_registry_client import _material_registry_package_url
    from api.services.lut_registry_sync import _resolve_same_origin_package_url, LutRegistryPackageError
    assert _material_registry_package_url(BASE, "packages/example.zip") == BASE + "/packages/example.zip"
    with pytest.raises(ValueError):
        _material_registry_package_url(BASE, "https://raw.githubusercontent.com/other/repo/main/packages/evil.zip")
    with pytest.raises(LutRegistryPackageError):
        _resolve_same_origin_package_url("https://raw.githubusercontent.com/other/repo/main/luts/packages/evil.zip", BASE)


def test_invalid_document_does_not_poison_a_valid_snapshot(tmp_path):
    payload = {"schema_version": 1, "materials": [{"channel": "official"}]}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        read_document(client, BASE, "/materials/catalog.json", tmp_path)
        payload["materials"] = "broken index"
        with pytest.raises(ValueError):
            read_document(client, BASE, "/materials/catalog.json", tmp_path, refresh=True)
        assert read_document(client, BASE, "/materials/catalog.json", tmp_path).json()["materials"] == [{"channel": "official"}]


def test_damaged_preview_is_not_cached_forever(tmp_path):
    good = {"schema_version": 1, "lut_id": "lut"}
    digest = hashlib.sha256(json.dumps(good, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload = {"schema_version": 1, "lut_id": "bad"}
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="checksum"):
            read_document(client, BASE, "/luts/previews/example.json", tmp_path, immutable=True, expected_sha256=digest)
        payload = good
        assert read_document(client, BASE, "/luts/previews/example.json", tmp_path,
                             immutable=True, expected_sha256=digest).json() == good
    assert len(calls) == 2


def test_anonymous_snapshot_stats_do_not_contact_the_account_server(static_source, monkeypatch, tmp_path):
    from api.services.resource_contribution import ContributionConnection
    from core.single_stage import material_files

    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(tmp_path))
    monkeypatch.setenv("LUMINA_CONTRIBUTION_REGISTRY_URL", "https://accounts.example/api/material-registry/v1")
    connection = ContributionConnection()
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"schema_version": 1, "items": []})
    client_class = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    assert connection.activity("materials", ["absent"]) == {"items": [], "subject": None}
    assert len(requests) == 1
    assert str(requests[0].url) == BASE + "/materials/activity.json"
    assert not requests[0].headers.get("authorization")
