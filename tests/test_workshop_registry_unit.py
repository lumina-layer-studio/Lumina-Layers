from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Callable

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from core.workshop import (
    RegistryClient,
    RegistryFetchResponse,
    WorkshopRegistryError,
    load_registry_keys,
)
from core.workshop.registry_client import (
    DEFAULT_REGISTRY_INDEX_URL,
    DEFAULT_REGISTRY_SIGNATURE_URL,
    parse_registry_index,
    select_install_candidate,
    verify_registry_signature,
)


def canonical_registry_bytes(value: dict[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def registry_fixture(
    *,
    version: str = "1.0.0",
    state: str = "active",
) -> dict[str, object]:
    asset_name = f"fixture.hello-{version}.lumina-workshop"
    revocation = None
    if state == "blocked":
        revocation = {
            "reasonCode": "malware",
            "severity": "critical",
            "message": {
                "zh-CN": "此版本已被阻止。",
                "en-US": "This version has been blocked.",
            },
        }
    return {
        "schemaVersion": 1,
        "generatedAt": "2026-07-30T00:00:00Z",
        "modules": [
            {
                "moduleId": "fixture.hello",
                "repository": (
                    "https://github.com/lumina-layer-studio/"
                    "Fixture-Workshop"
                ),
                "official": False,
                "publisher": "Fixture Publisher",
                "name": {
                    "zh-CN": "测试模块",
                    "en-US": "Fixture module",
                },
                "description": {
                    "zh-CN": "用于 Registry 测试",
                    "en-US": "Used for Registry tests",
                },
                "versions": [
                    {
                        "version": version,
                        "releaseTag": f"v{version}",
                        "assetName": asset_name,
                        "downloadUrl": (
                            "https://github.com/lumina-layer-studio/"
                            "Fixture-Workshop/releases/download/"
                            f"v{version}/{asset_name}"
                        ),
                        "assetBytes": 12345,
                        "sha256": "a" * 64,
                        "manifestSha256": "b" * 64,
                        "workshopApi": {
                            "min": "1.0.0",
                            "maxExclusive": "2.0.0",
                        },
                        "luminaVersion": {
                            "min": "1.0.0",
                        },
                        "permissions": [
                            {
                                "name": "image.pick",
                                "reason": "Select a fixture image.",
                            }
                        ],
                        "state": state,
                        "revocation": revocation,
                    }
                ],
            }
        ],
    }


def signature_bytes(
    payload: bytes,
    private_key: Ed25519PrivateKey,
    *,
    key_id: str = "test-key",
    algorithm: str = "Ed25519",
    extra: dict[str, object] | None = None,
) -> bytes:
    value: dict[str, object] = {
        "algorithm": algorithm,
        "keyId": key_id,
        "signature": base64.b64encode(
            private_key.sign(payload)
        ).decode("ascii"),
    }
    if extra:
        value.update(extra)
    return canonical_registry_bytes(value)


def write_snapshot(
    tmp_path: Path,
    value: dict[str, object] | None = None,
) -> Path:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_bytes(
        canonical_registry_bytes(
            value
            or {
                "schemaVersion": 1,
                "generatedAt": "2026-07-30T00:00:00Z",
                "modules": [],
            }
        )
    )
    return snapshot


def fake_fetch(
    payload: bytes,
    signature: bytes,
    *,
    etag: str = '"registry-v1"',
) -> Callable[[str, str | None], RegistryFetchResponse]:
    def fetch(url: str, previous_etag: str | None) -> RegistryFetchResponse:
        del previous_etag
        if url.endswith(".sig"):
            return RegistryFetchResponse(
                status_code=200,
                body=signature,
                etag=None,
            )
        return RegistryFetchResponse(
            status_code=200,
            body=payload,
            etag=etag,
        )

    return fetch


def client_for(
    tmp_path: Path,
    *,
    private_key: Ed25519PrivateKey,
    payload: bytes,
    signature: bytes | None = None,
    fetcher: Callable[[str, str | None], RegistryFetchResponse] | None = None,
) -> RegistryClient:
    return RegistryClient(
        keys={"test-key": private_key.public_key()},
        cache_dir=tmp_path / "cache",
        snapshot_path=write_snapshot(tmp_path),
        fetch_bytes=fetcher
        or fake_fetch(
            payload,
            signature or signature_bytes(payload, private_key),
        ),
    )


def test_verified_index_replaces_cache(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = canonical_registry_bytes(registry_fixture())
    client = client_for(
        tmp_path,
        private_key=private_key,
        payload=payload,
    )

    result = client.refresh()

    assert result.source == "remote"
    assert result.verified is True
    assert result.index.modules[0].module_id == "fixture.hello"
    assert (tmp_path / "cache" / "registry-v1.json").read_bytes() == payload
    assert (
        tmp_path / "cache" / "registry-v1.sig"
    ).read_bytes().startswith(b"{")
    assert (
        tmp_path / "cache" / "registry-v1.etag"
    ).read_text(encoding="utf-8") == '"registry-v1"'
    assert (
        tmp_path / "cache" / "registry-v1.verified-at"
    ).read_text(encoding="utf-8").endswith("Z")


def test_app_owned_key_set_loads_exact_ed25519_public_keys(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    path = tmp_path / "keys.json"
    path.write_bytes(
        canonical_registry_bytes(
            {
                "schemaVersion": 1,
                "keys": [
                    {
                        "keyId": "registry-2026-01",
                        "algorithm": "Ed25519",
                        "publicKey": base64.b64encode(public_bytes).decode(
                            "ascii"
                        ),
                    }
                ],
            }
        )
    )

    keys = load_registry_keys(path)

    assert tuple(keys) == ("registry-2026-01",)
    keys["registry-2026-01"].verify(
        private_key.sign(b"fixture"),
        b"fixture",
    )


@pytest.mark.parametrize(
    "mutation",
    ["wrong-algorithm", "bad-key-size", "duplicate-id", "extra-field"],
)
def test_app_owned_key_set_is_strict(mutation: str, tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    record: dict[str, object] = {
        "keyId": "registry-2026-01",
        "algorithm": "Ed25519",
        "publicKey": base64.b64encode(public_bytes).decode("ascii"),
    }
    value: dict[str, object] = {
        "schemaVersion": 1,
        "keys": [record],
    }
    if mutation == "wrong-algorithm":
        record["algorithm"] = "RSA"
    elif mutation == "bad-key-size":
        record["publicKey"] = base64.b64encode(b"short").decode("ascii")
    elif mutation == "duplicate-id":
        value["keys"].append(copy.deepcopy(record))
    else:
        record["trusted"] = True
    path = tmp_path / "keys.json"
    path.write_bytes(canonical_registry_bytes(value))

    with pytest.raises(WorkshopRegistryError):
        load_registry_keys(path)


def test_bad_signature_keeps_previous_verified_cache(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = canonical_registry_bytes(registry_fixture(version="1.0.0"))
    first = client_for(
        tmp_path,
        private_key=private_key,
        payload=payload,
    ).refresh()
    replacement = canonical_registry_bytes(
        registry_fixture(version="1.1.0")
    )
    attacker = Ed25519PrivateKey.generate()
    client = client_for(
        tmp_path,
        private_key=private_key,
        payload=replacement,
        signature=signature_bytes(replacement, attacker),
    )

    result = client.refresh()

    assert result.source == "cache"
    assert result.index == first.index
    assert (
        tmp_path / "cache" / "registry-v1.json"
    ).read_bytes() == payload


def test_unsigned_official_upgrade_keeps_verified_community_cache(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    community = registry_fixture()
    payload = canonical_registry_bytes(community)
    first = client_for(
        tmp_path,
        private_key=private_key,
        payload=payload,
    ).refresh()
    tampered = copy.deepcopy(community)
    tampered["modules"][0]["official"] = True
    replacement = canonical_registry_bytes(tampered)
    client = client_for(
        tmp_path,
        private_key=private_key,
        payload=replacement,
        signature=signature_bytes(payload, private_key),
    )

    result = client.refresh()

    assert result.source == "cache"
    assert result.index == first.index
    assert result.index.modules[0].official is False


def test_etag_304_reuses_verified_cache_without_fetching_signature(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = canonical_registry_bytes(registry_fixture())
    client_for(
        tmp_path,
        private_key=private_key,
        payload=payload,
    ).refresh()
    calls: list[tuple[str, str | None]] = []

    def not_modified(
        url: str,
        previous_etag: str | None,
    ) -> RegistryFetchResponse:
        calls.append((url, previous_etag))
        if url.endswith(".sig"):
            raise AssertionError("signature must not be fetched after 304")
        return RegistryFetchResponse(
            status_code=304,
            body=b"",
            etag=previous_etag,
        )

    result = client_for(
        tmp_path,
        private_key=private_key,
        payload=payload,
        fetcher=not_modified,
    ).refresh()

    assert result.source == "cache"
    assert calls == [
        (
            "https://lumina-layer-studio.github.io/"
            "Lumina-Workshop-Registry/registry-v1.json",
            '"registry-v1"',
        )
    ]


def test_network_failure_uses_bundled_snapshot(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = canonical_registry_bytes(registry_fixture())

    def unavailable(
        _url: str,
        _etag: str | None,
    ) -> RegistryFetchResponse:
        raise OSError("offline")

    result = client_for(
        tmp_path,
        private_key=private_key,
        payload=payload,
        fetcher=unavailable,
    ).refresh()

    assert result.source == "snapshot"
    assert result.verified is True
    assert result.index.modules == ()


@pytest.mark.parametrize(
    "scenario",
    ["mirror", "anonymous", "index-timeout", "signature-503", "redirect", "tampered", "unset", "github-alias"],
)
def test_signed_registry_prefers_mirror_and_falls_back_as_a_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str,
) -> None:
    mirror = "https://mirror.example/api/workshop-mirror/v1"
    mirror_index = f"{mirror}/registry-v1.json"
    mirror_signature = f"{mirror}/registry-v1.sig"
    if scenario == "unset":
        monkeypatch.delenv("LUMINA_WORKSHOP_MIRROR_URL", raising=False)
    elif scenario == "github-alias":
        monkeypatch.setenv("LUMINA_WORKSHOP_MIRROR_URL", DEFAULT_REGISTRY_INDEX_URL.rsplit("/", 1)[0])
    else:
        monkeypatch.setenv("LUMINA_WORKSHOP_MIRROR_URL", f" {mirror}/ ")
    if scenario == "anonymous":
        monkeypatch.delenv("LUMINA_WORKSHOP_MIRROR_TOKEN", raising=False)
    else:
        monkeypatch.setenv("LUMINA_WORKSHOP_MIRROR_TOKEN", "mirror-test-token")
    key = Ed25519PrivateKey.generate()
    mirror_payload = canonical_registry_bytes(registry_fixture(version="1.1.0"))
    upstream_payload = canonical_registry_bytes(registry_fixture())
    calls: list[tuple[str, str | None]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append((url, request.headers.get("Authorization")))
        if url == mirror_index:
            if scenario == "index-timeout":
                raise httpx.ConnectTimeout("mirror timed out", request=request)
            if scenario == "redirect":
                return httpx.Response(302, headers={"Location": DEFAULT_REGISTRY_INDEX_URL})
            return httpx.Response(200, content=mirror_payload, headers={"ETag": '"mirror"'})
        if url == mirror_signature:
            if scenario == "signature-503":
                return httpx.Response(503)
            signed_bytes = upstream_payload if scenario == "tampered" else mirror_payload
            return httpx.Response(200, content=signature_bytes(signed_bytes, key))
        if url == DEFAULT_REGISTRY_INDEX_URL:
            assert "If-None-Match" not in request.headers
            return httpx.Response(200, content=upstream_payload, headers={"ETag": '"upstream"'})
        assert url == DEFAULT_REGISTRY_SIGNATURE_URL
        return httpx.Response(200, content=signature_bytes(upstream_payload, key))

    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    client = RegistryClient(
        keys={"test-key": key.public_key()},
        cache_dir=tmp_path / "cache",
        snapshot_path=write_snapshot(tmp_path),
    )
    result = client.refresh()

    mirror_token = None if scenario == "anonymous" else "Bearer mirror-test-token"
    expected = [] if scenario in {"unset", "github-alias"} else [(mirror_index, mirror_token)]
    if scenario in {"mirror", "anonymous", "signature-503", "tampered"}:
        expected.append((mirror_signature, mirror_token))
    if scenario in {"index-timeout", "signature-503", "redirect", "unset", "github-alias"}:
        expected.extend([(DEFAULT_REGISTRY_INDEX_URL, None), (DEFAULT_REGISTRY_SIGNATURE_URL, None)])
    assert calls == expected
    assert result.verified is True
    if scenario == "tampered":
        assert result.source == "snapshot" and not result.index.modules
        assert not (tmp_path / "cache" / "registry-v1.json").exists()
    else:
        expected_version = "1.1.0" if scenario in {"mirror", "anonymous"} else "1.0.0"
        assert result.source == "remote"
        assert client.last_error is None
        assert result.index.modules[0].versions[0].version == expected_version


def test_tampered_cache_is_not_used(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = canonical_registry_bytes(registry_fixture())
    client_for(
        tmp_path,
        private_key=private_key,
        payload=payload,
    ).refresh()
    (tmp_path / "cache" / "registry-v1.json").write_bytes(
        canonical_registry_bytes(registry_fixture(version="9.9.9"))
    )

    def unavailable(
        _url: str,
        _etag: str | None,
    ) -> RegistryFetchResponse:
        raise OSError("offline")

    result = client_for(
        tmp_path,
        private_key=private_key,
        payload=payload,
        fetcher=unavailable,
    ).refresh()

    assert result.source == "snapshot"
    assert result.index.modules == ()


@pytest.mark.parametrize(
    "signature_mutation",
    [
        "unknown-key",
        "wrong-algorithm",
        "short-signature",
        "extra-field",
    ],
)
def test_signature_metadata_fails_closed(
    signature_mutation: str,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = canonical_registry_bytes(registry_fixture())
    if signature_mutation == "unknown-key":
        signature = signature_bytes(
            payload,
            private_key,
            key_id="other-key",
        )
    elif signature_mutation == "wrong-algorithm":
        signature = signature_bytes(
            payload,
            private_key,
            algorithm="RSA",
        )
    elif signature_mutation == "short-signature":
        signature = canonical_registry_bytes(
            {
                "algorithm": "Ed25519",
                "keyId": "test-key",
                "signature": base64.b64encode(b"short").decode("ascii"),
            }
        )
    else:
        signature = signature_bytes(
            payload,
            private_key,
            extra={"publicKey": "must-not-be-trusted"},
        )

    with pytest.raises(WorkshopRegistryError):
        verify_registry_signature(
            payload,
            signature,
            {"test-key": private_key.public_key()},
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "malformed-json",
        "duplicate-module",
        "duplicate-version",
        "invalid-sha256",
        "registry-key-injection",
        "blocked-without-revocation",
        "active-with-revocation",
    ],
)
def test_registry_index_is_strictly_validated(mutation: str) -> None:
    fixture = registry_fixture()
    if mutation == "malformed-json":
        payload = b"{"
    elif mutation == "duplicate-module":
        fixture["modules"].append(copy.deepcopy(fixture["modules"][0]))
        payload = canonical_registry_bytes(fixture)
    elif mutation == "duplicate-version":
        versions = fixture["modules"][0]["versions"]
        versions.append(copy.deepcopy(versions[0]))
        payload = canonical_registry_bytes(fixture)
    elif mutation == "invalid-sha256":
        fixture["modules"][0]["versions"][0]["sha256"] = "ABC"
        payload = canonical_registry_bytes(fixture)
    elif mutation == "registry-key-injection":
        fixture["keys"] = [{"keyId": "attacker"}]
        payload = canonical_registry_bytes(fixture)
    elif mutation == "blocked-without-revocation":
        fixture["modules"][0]["versions"][0]["state"] = "blocked"
        payload = canonical_registry_bytes(fixture)
    else:
        fixture["modules"][0]["versions"][0]["revocation"] = {
            "reasonCode": "malware",
            "severity": "critical",
            "message": {
                "zh-CN": "阻止",
                "en-US": "Blocked",
            },
        }
        payload = canonical_registry_bytes(fixture)

    with pytest.raises(WorkshopRegistryError):
        parse_registry_index(payload)


def test_blocked_version_is_never_an_install_candidate() -> None:
    index = parse_registry_index(
        canonical_registry_bytes(
            registry_fixture(state="blocked")
        )
    )

    assert (
        select_install_candidate(
            index,
            "fixture.hello",
            lumina_version="1.0.0",
            workshop_api_version="1.0.0",
        )
        is None
    )
    assert (
        select_install_candidate(
            index,
            "fixture.hello",
            lumina_version="1.0.0",
            workshop_api_version="1.0.0",
            requested_version="1.0.0",
        )
        is None
    )


def test_deprecated_version_requires_an_explicit_request() -> None:
    index = parse_registry_index(
        canonical_registry_bytes(
            registry_fixture(state="deprecated")
        )
    )

    assert (
        select_install_candidate(
            index,
            "fixture.hello",
            lumina_version="1.0.0",
            workshop_api_version="1.0.0",
        )
        is None
    )
    explicit = select_install_candidate(
        index,
        "fixture.hello",
        lumina_version="1.0.0",
        workshop_api_version="1.0.0",
        requested_version="1.0.0",
    )
    assert explicit is not None
    assert explicit.version == "1.0.0"


def test_latest_compatible_active_version_is_selected() -> None:
    fixture = registry_fixture(version="1.0.0")
    newer = copy.deepcopy(fixture["modules"][0]["versions"][0])
    newer["version"] = "1.1.0"
    newer["releaseTag"] = "v1.1.0"
    newer["assetName"] = "fixture.hello-1.1.0.lumina-workshop"
    newer["downloadUrl"] = (
        "https://github.com/lumina-layer-studio/Fixture-Workshop/"
        "releases/download/v1.1.0/"
        "fixture.hello-1.1.0.lumina-workshop"
    )
    fixture["modules"][0]["versions"].append(newer)
    index = parse_registry_index(canonical_registry_bytes(fixture))

    selected = select_install_candidate(
        index,
        "fixture.hello",
        lumina_version="1.0.0",
        workshop_api_version="1.0.0",
    )

    assert selected is not None
    assert selected.version == "1.1.0"
