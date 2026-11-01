"""Public registry failover preserves identity and validation boundaries."""
import hashlib

import httpx
import pytest

from api.services import lut_registry_sync as lut
from core.registry_transport import fallback_base, fetch_catalog, map_package_url
from core.single_stage import material_files, material_registry_client
from core import registry_transport


PRIMARY = "https://primary.test/api/material-registry/v1"
BACKUP = "https://backup.test/api/material-registry/v1"


@pytest.fixture(autouse=True)
def registry_env(monkeypatch):
    monkeypatch.setattr(registry_transport, "sleep", lambda seconds: None)
    for family in ("MATERIAL", "LUT"):
        monkeypatch.setenv(f"LUMINA_{family}_REGISTRY_URL", PRIMARY)
        monkeypatch.setenv(f"LUMINA_{family}_REGISTRY_FALLBACK_URL", BACKUP)
        monkeypatch.delenv(f"LUMINA_{family}_REGISTRY_TOKEN", raising=False)
        monkeypatch.setenv(f"LUMINA_{family}_REGISTRY_CHANNELS", "official")
    material_registry_client.invalidate_material_registry_remote_catalog_cache()


@pytest.mark.parametrize("family", ["material", "lut"])
@pytest.mark.parametrize("failure", [502, 503, 504, "connect", "read", "eof"])
def test_catalog_recovers_from_one_transient_failure_without_a_backup(monkeypatch, family, failure):
    monkeypatch.delenv(f"LUMINA_{family.upper()}_REGISTRY_FALLBACK_URL")
    # LUT can inherit the material fallback when its primary is shared.
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_FALLBACK_URL", raising=False)
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            if isinstance(failure, int):
                return httpx.Response(failure)
            errors = {"connect": httpx.ConnectError, "read": httpx.ReadError, "eof": httpx.RemoteProtocolError}
            raise errors[failure]("connection interrupted", request=request)
        return httpx.Response(200, json={"materials": [], "items": []})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = fetch_catalog(client=client, primary=PRIMARY, family=family.upper(),
                               suffix="/materials/catalog", channels=["official"],
                               headers={}, params={"q": "白色", "offset": 20}, etag='"catalog-1"')
    assert result.status_code == 200
    assert len(calls) == 2
    assert calls[0].url == calls[1].url
    assert calls[1].headers["If-None-Match"] == '"catalog-1"'


def test_catalog_stops_after_one_same_origin_retry(monkeypatch):
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_FALLBACK_URL")
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadError("connection reset", request=request)

    with pytest.raises(RuntimeError, match="catalog request failed"):
        material_registry_client.list_material_registry_catalog(transport=httpx.MockTransport(handle), use_cache=False)
    assert len(calls) == 2


@pytest.mark.parametrize("family", ["material", "lut"])
@pytest.mark.parametrize("status", [408, 429, 500, 503, "timeout"])
def test_catalog_fails_over_and_canonicalizes_package_identity(family, status):
    calls = []
    package_path = "/packages/a.zip" if family == "material" else "/luts/packages/a.zip"
    entry = {"material_id": "m", "revision_id": "r", "package_sha256": "a" * 64,
             "package_url": BACKUP + package_path}
    def handle(request):
        calls.append(request)
        if request.url.host == "primary.test":
            if status == "timeout":
                raise httpx.ReadTimeout("offline", request=request)
            return httpx.Response(status)
        return httpx.Response(200, json={"materials" if family == "material" else "items": [entry]})
    transport = httpx.MockTransport(handle)
    if family == "material":
        result = material_registry_client.list_material_registry_catalog(transport=transport, use_cache=False)
        entries = result["materials"]
    else:
        with httpx.Client(transport=transport) as client:
            entries = lut.fetch_remote_catalog(client=client)["items"]
    assert entries[0]["package_url"] == PRIMARY + package_path
    assert entries[0]["revision_id"] == "r"
    assert len(calls) == 2


@pytest.mark.parametrize("family", ["material", "lut"])
@pytest.mark.parametrize("status", [200, 301, 400, 401, 403, 404])
def test_catalog_does_not_retry_success_or_permanent_failure(family, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"materials": [], "items": []})
    transport = httpx.MockTransport(handle)
    try:
        if family == "material":
            material_registry_client.list_material_registry_catalog(transport=transport, use_cache=False)
        else:
            with httpx.Client(transport=transport) as client:
                lut.fetch_remote_catalog(client=client)
    except (RuntimeError, lut.LutRegistryRemoteError):
        assert status != 200
    assert len(calls) == 1


def test_material_stream_failure_discards_partial_before_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(material_files, "TEMP_DIR", str(tmp_path))
    data = b"complete package"
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial"
            raise httpx.ReadTimeout("interrupted")
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.host == "primary.test":
            return httpx.Response(200, stream=Broken())
        assert list(tmp_path.iterdir()) == []
        return httpx.Response(200, content=data)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        path = material_registry_client._download_material_registry_package_to_tempfile(
            client=client, package_url=PRIMARY + "/packages/a.zip", headers={},
            expected_package_sha256=hashlib.sha256(data).hexdigest(), identity_label="m/r")
    assert path.read_bytes() == data
    assert list(tmp_path.iterdir()) == [path]
    assert len(calls) == 2


def test_lut_stream_failure_discards_partial_before_fallback():
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b"part"
            raise httpx.ReadTimeout("interrupted")
    def handle(request):
        return (httpx.Response(200, stream=Broken()) if request.url.host == "primary.test"
                else httpx.Response(200, content=b"whole"))
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert lut._download_limited_package(client=client,
            package_url=PRIMARY + "/luts/packages/a.zip", headers={}, expected_bytes=5) == b"whole"


def test_custom_lut_primary_does_not_inherit_material_fallback(monkeypatch):
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://custom.test/registry")
    monkeypatch.delenv("LUMINA_LUT_REGISTRY_FALLBACK_URL")
    assert fallback_base("https://custom.test/registry", "LUT") is None


def test_remote_http_fallback_is_rejected(monkeypatch):
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_FALLBACK_URL", "http://backup.test/registry")
    assert fallback_base(PRIMARY, "MATERIAL") is None


def test_explicit_empty_lut_primary_disables_registry(monkeypatch):
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "")
    assert not lut.get_registry_config().configured


@pytest.mark.parametrize("family", ["material", "lut"])
@pytest.mark.parametrize("guard", ["token", "private", "cookie", "auth", "header", "set-cookie"])
def test_private_credentials_never_reach_backup(monkeypatch, family, guard):
    kind = family.upper()
    if guard == "token":
        monkeypatch.setenv(f"LUMINA_{kind}_REGISTRY_TOKEN", "secret")
    if guard == "private":
        monkeypatch.setenv(f"LUMINA_{kind}_REGISTRY_CHANNELS", "team")
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(503, headers={"set-cookie": "session=secret; Path=/"}
                              if guard == "set-cookie" else {})
    if family == "material" and guard in {"cookie", "auth", "header"}:
        # Material public entry points create their own clean clients; exercise
        # the shared download boundary for externally supplied client state.
        with httpx.Client(transport=httpx.MockTransport(handle),
                          cookies={"session": "secret"} if guard == "cookie" else None,
                          auth=("user", "secret") if guard == "auth" else None,
                          headers={"Authorization": "secret"} if guard == "header" else None) as client:
            with pytest.raises(httpx.HTTPError):
                material_registry_client._download_material_registry_package_to_tempfile(
                    client=client, package_url=PRIMARY + "/packages/a.zip", headers={},
                    expected_package_sha256="a" * 64, identity_label="m/r")
    elif family == "material":
        with pytest.raises(RuntimeError):
            material_registry_client.list_material_registry_catalog(transport=httpx.MockTransport(handle), use_cache=False)
    else:
        with httpx.Client(transport=httpx.MockTransport(handle),
                          cookies={"session": "secret"} if guard == "cookie" else None,
                          auth=("user", "secret") if guard == "auth" else None,
                          headers={"Authorization": "secret"} if guard == "header" else None) as client:
            with pytest.raises(lut.LutRegistryRemoteError):
                lut.fetch_remote_catalog(client=client)
    is_package_read = family == "material" and guard in {"cookie", "auth", "header"}
    assert [request.url.host for request in calls] == ["primary.test"] * (1 if is_package_read else 2)


@pytest.mark.parametrize("status,headers", [(429, {}), (503, {"retry-after": "30"})])
def test_catalog_does_not_retry_a_same_origin_rate_limit(monkeypatch, status, headers):
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_FALLBACK_URL")
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers=headers)

    with pytest.raises(RuntimeError, match="catalog request failed"):
        material_registry_client.list_material_registry_catalog(transport=httpx.MockTransport(handle), use_cache=False)
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["https://evil.test/packages/a.zip", "../secret", "/admin",
                                  "/api/material-registry/v1/packages/%2e%2e/secret",
                                  "/api/material-registry/v1/packages/a.zip?token=secret",
                                  "https://user:secret@backup.test/api/material-registry/v1/packages/a.zip"])
def test_fallback_catalog_cannot_expand_trusted_package_paths(url):
    with pytest.raises(ValueError):
        map_package_url(url, BACKUP, PRIMARY)


@pytest.mark.parametrize("family", ["material", "lut"])
def test_invalid_json_does_not_fallback(family):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, text="invalid JSON")
    with pytest.raises((ValueError, lut.LutRegistryRemoteError)):
        if family == "material":
            material_registry_client.list_material_registry_catalog(transport=httpx.MockTransport(handle), use_cache=False)
        else:
            with httpx.Client(transport=httpx.MockTransport(handle)) as client:
                lut.fetch_remote_catalog(client=client)
    assert len(calls) == 1


@pytest.mark.parametrize("family", ["material", "lut"])
def test_all_sources_fail_after_two_requests(family):
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ConnectError("offline", request=request)
    with pytest.raises(RuntimeError):
        if family == "material":
            material_registry_client.list_material_registry_catalog(transport=httpx.MockTransport(handle), use_cache=False)
        else:
            with httpx.Client(transport=httpx.MockTransport(handle)) as client:
                lut.fetch_remote_catalog(client=client)
    assert [request.url.host for request in calls] == ["primary.test", "backup.test"]


def test_material_sha_mismatch_does_not_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(material_files, "TEMP_DIR", str(tmp_path))
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=b"tampered")
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="sha256 mismatch"):
            material_registry_client._download_material_registry_package_to_tempfile(
                client=client, package_url=PRIMARY + "/packages/a.zip", headers={},
                expected_package_sha256="a" * 64, identity_label="m/r")
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_lut_size_mismatch_does_not_fallback():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=b"oversized")
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(lut.LutRegistryPackageError):
            lut._download_limited_package(client=client, package_url=PRIMARY + "/luts/packages/a.zip",
                                         headers={}, expected_bytes=2)
    assert len(calls) == 1


@pytest.mark.parametrize("fallback", ["", PRIMARY, PRIMARY + "/different-path", "file:///tmp/a"])
def test_empty_duplicate_same_origin_or_invalid_backup_is_disabled(monkeypatch, fallback):
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_FALLBACK_URL", fallback)
    assert fallback_base(PRIMARY, "MATERIAL") is None


def test_inherited_lut_fallback_and_explicit_empty_override(monkeypatch):
    monkeypatch.delenv("LUMINA_LUT_REGISTRY_URL")
    monkeypatch.delenv("LUMINA_LUT_REGISTRY_FALLBACK_URL")
    assert fallback_base(lut.get_registry_config().base_url, "LUT") == BACKUP
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_FALLBACK_URL", "")
    assert fallback_base(PRIMARY, "LUT") is None


@pytest.mark.parametrize("reverse", [False, True])
def test_material_install_identity_survives_relative_to_canonical_catalog_switch(reverse):
    from api.routers.material_sync import _select_catalog_install_entry
    from api.routers.material_sync import MaterialRegistryInstallRequest
    entry = {"material_id": "m", "revision_id": "r", "package_sha256": "a" * 64,
             "package_url": PRIMARY + "/packages/a.zip"}
    payload = MaterialRegistryInstallRequest(**{**entry, "package_url": "/api/material-registry/v1/packages/a.zip"})
    if reverse:
        entry["package_url"], payload.package_url = payload.package_url, entry["package_url"]
    assert _select_catalog_install_entry({"materials": [entry]}, payload) == entry


@pytest.mark.parametrize("url", [BACKUP + "/packages/a.zip", "https://evil.test/api/material-registry/v1/packages/a.zip"])
def test_material_catalog_identity_does_not_accept_other_origins(url):
    from api.routers.material_sync import _select_catalog_install_entry, MaterialRegistryInstallRequest
    entry = {"material_id": "m", "revision_id": "r", "package_sha256": "a" * 64,
             "package_url": PRIMARY + "/packages/a.zip"}
    payload = MaterialRegistryInstallRequest(**{**entry, "package_url": url})
    with pytest.raises(ValueError):
        _select_catalog_install_entry({"materials": [entry]}, payload)


def test_refresh_fallback_does_not_reuse_primary_etag():
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.host == "primary.test":
            assert request.headers["if-none-match"] == '"primary-etag"'
            return httpx.Response(503)
        assert "if-none-match" not in request.headers
        return httpx.Response(200, headers={"etag": '"backup-etag"'}, json={"materials": []})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        response = material_registry_client._request_material_registry_refresh_catalog(
            client=client, registry_url=PRIMARY, channels=["official"], headers={}, etag='"primary-etag"')
    assert "etag" not in response.headers
    assert len(calls) == 2


@pytest.mark.parametrize("body", ["invalid", '{"items":[{"package_url":"https://evil.test/a"}]}',
                                  '{"items":[{"package_url":123}]}'])
def test_lut_malformed_backup_is_reported_as_remote_error(body):
    def handle(request):
        return httpx.Response(503) if request.url.host == "primary.test" else httpx.Response(200, text=body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(lut.LutRegistryRemoteError):
            lut.fetch_remote_catalog(client=client)


def test_lut_download_rejects_redirect_even_when_client_follows_redirects():
    calls = []

    def handle(request):
        calls.append(str(request.url))
        if str(request.url) == PRIMARY + "/luts/packages/a.zip":
            return httpx.Response(302, headers={"location": "https://redirect.test/package.zip"})
        if request.url.host == "redirect.test":
            return httpx.Response(503)
        return httpx.Response(200, content=b"valid")

    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        with pytest.raises(lut.LutRegistryRemoteError, match="redirected"):
            lut._download_limited_package(
                client=client, package_url=PRIMARY + "/luts/packages/a.zip",
                headers={}, expected_bytes=5,
            )
    assert calls == [PRIMARY + "/luts/packages/a.zip"]


@pytest.mark.parametrize("header", ["If-None-Match", "If-Modified-Since"])
@pytest.mark.parametrize("location", ["client", "request"])
def test_external_conditional_headers_disable_fallback_without_mutating_client(header, location):
    calls = []
    condition = '"primary-version"' if header == "If-None-Match" else "Fri, 11 Sep 2026 00:00:00 GMT"
    supplied_headers = {header: condition}

    def handle(request):
        calls.append(request)
        return httpx.Response(503) if request.url.host == "primary.test" else httpx.Response(200, json={"items": []})

    with httpx.Client(
        transport=httpx.MockTransport(handle),
        headers=supplied_headers if location == "client" else None,
    ) as client:
        original_headers = dict(client.headers)
        with pytest.raises(httpx.HTTPStatusError):
            fetch_catalog(
                client=client, primary=PRIMARY, family="LUT", suffix="/luts/catalog",
                channels=["official"], params=[],
                headers=supplied_headers if location == "request" else {},
            )
        assert dict(client.headers) == original_headers
    assert supplied_headers == {header: condition}
    assert [request.url.host for request in calls] == ["primary.test", "primary.test"]
    assert all(request.headers[header] == condition for request in calls)
