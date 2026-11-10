"""Review levels come only from trusted records bound to exact package bytes."""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.workshop.backend.review import (
    ReviewAttestationClient,
    ReviewContext,
    determine_review_level,
)
from core.workshop.models import RegistryIndex
from core.workshop.registry_client import RegistryFetchResponse

SHA = "1" * 63 + "2"
OTHER = "3" * 63 + "4"


def registry(*, official: bool, state: str = "active", sha: str = SHA) -> RegistryIndex:
    version = {
        "version": "1.1.0",
        "releaseTag": "v1.1.0",
        "assetName": "fixture.mod-1.1.0.lumina-workshop",
        "downloadUrl": "https://github.com/acme/mod/releases/download/v1.1.0/fixture.mod-1.1.0.lumina-workshop",
        "assetBytes": 10,
        "sha256": sha,
        "manifestSha256": OTHER,
        "workshopApi": {"min": "1.1.0", "maxExclusive": "2.0.0"},
        "luminaVersion": {"min": "2.0.0"},
        "permissions": [],
        "state": state,
        "revocation": (
            None
            if state != "blocked"
            else {"reasonCode": "abuse", "severity": "high", "message": {"zh-CN": "阻止", "en-US": "Blocked"}}
        ),
    }
    return RegistryIndex.model_validate(
        {
            "schemaVersion": 1,
            "generatedAt": "2026-11-04T00:00:00Z",
            "modules": [
                {
                    "moduleId": "fixture.mod",
                    "repository": "https://github.com/acme/mod",
                    "official": official,
                    "publisher": "Acme",
                    "name": {"zh-CN": "模块", "en-US": "Module"},
                    "description": {"zh-CN": "说明", "en-US": "Description"},
                    "versions": [version],
                }
            ],
        }
    )


def level(source: str, official: bool, context: ReviewContext, *, sha: str = SHA, recorded=None) -> str:  # noqa: ANN001
    return determine_review_level(
        source=source,
        official=official,
        module_id="fixture.mod",
        version="1.1.0",
        package_sha256=sha,
        context=context,
        recorded_level=recorded,
    )


def test_official_requires_signed_registry_bytes_match() -> None:
    context = ReviewContext(registry=registry(official=True), attestations=frozenset())
    assert level("registry", True, context) == "official"
    assert level("registry", True, context, sha=OTHER) == "unreviewed"
    assert level("seed", True, context) == "official"


def test_community_needs_exact_attestation_and_withdrawal_downgrades() -> None:
    attested = ReviewContext(
        registry=registry(official=False),
        attestations=frozenset({("fixture.mod", "1.1.0", SHA)}),
    )
    assert level("registry", False, attested) == "reviewed"
    withdrawn = ReviewContext(registry=registry(official=False), attestations=frozenset())
    assert level("registry", False, withdrawn, recorded="reviewed") == "unreviewed"
    # Unavailable evidence keeps an earlier level but never grants a new one.
    offline = ReviewContext(registry=registry(official=False), attestations=None)
    assert level("registry", False, offline, recorded="reviewed") == "reviewed"
    assert level("registry", False, offline) == "unreviewed"


def test_local_and_github_packages_are_unreviewed_even_with_matching_bytes() -> None:
    context = ReviewContext(
        registry=registry(official=True),
        attestations=frozenset({("fixture.mod", "1.1.0", SHA)}),
    )
    assert level("local", False, context) == "unreviewed"
    assert level("github", False, context) == "unreviewed"


def _signed(payload: bytes, key: Ed25519PrivateKey) -> bytes:
    return json.dumps(
        {
            "algorithm": "Ed25519",
            "keyId": "test-key",
            "signature": base64.b64encode(key.sign(payload)).decode("ascii"),
        }
    ).encode("utf-8")


def test_attestations_are_signature_verified_and_cached(tmp_path) -> None:  # noqa: ANN001
    key = Ed25519PrivateKey.generate()
    payload = json.dumps(
        {
            "schemaVersion": 1,
            "generatedAt": "2026-11-04T00:00:00Z",
            "reviews": [
                {
                    "moduleId": "fixture.mod",
                    "version": "1.1.0",
                    "sha256": SHA,
                    "manifestSha256": OTHER,
                    "scope": "backend-code",
                    "reviewedAt": "2026-11-03",
                }
            ],
        }
    ).encode("utf-8")
    responses = {
        "index": RegistryFetchResponse(200, payload, None),
        "sig": RegistryFetchResponse(200, _signed(payload, key), None),
    }

    def fetch(url: str, _etag):  # noqa: ANN001, ANN202
        return responses["sig" if url.endswith(".sig") else "index"]

    client = ReviewAttestationClient(keys={"test-key": key.public_key()}, cache_dir=tmp_path, fetch_bytes=fetch)
    index = client.refresh()
    assert index is not None and index.reviews[0].sha256 == SHA

    forged = ReviewAttestationClient(
        keys={"test-key": Ed25519PrivateKey.generate().public_key()},
        cache_dir=tmp_path / "other",
        fetch_bytes=fetch,
    )
    assert forged.refresh() is None

    def offline(_url: str, _etag):  # noqa: ANN001, ANN202
        raise OSError("offline")

    cached = ReviewAttestationClient(keys={"test-key": key.public_key()}, cache_dir=tmp_path, fetch_bytes=offline)
    assert cached.refresh() is not None


@pytest.mark.parametrize("state", ["blocked"])
def test_blocked_state_is_visible_from_registry(state: str) -> None:
    from core.workshop.backend.review import registry_version_state

    found, sha, official = registry_version_state(
        ReviewContext(registry=registry(official=False, state=state), attestations=None),
        "fixture.mod",
        "1.1.0",
    )
    assert (found, sha, official) == ("blocked", SHA, False)
