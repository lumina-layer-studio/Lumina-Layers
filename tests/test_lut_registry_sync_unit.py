"""Unit tests for cloud LUT registry sync.

These tests cover the local security boundary for catalog/install without
calling the production registry service.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
import msgpack
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routers import lut as lut_router
from api.services import lut_registry_sync as sync
from utils.lut_manager import LUTManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _registry_lut_content_hash(lut_path: str, lut_bytes: bytes) -> str:
    lut_sha = _sha256(lut_bytes)
    logical_name = PurePosixPath(lut_path).name
    return hashlib.sha256(f"{logical_name}:{lut_sha}".encode("utf-8")).hexdigest()


_DEFAULT_LUT_BYTES = json.dumps(
    {
        "color_mode": "4-Color (RYBW)",
        "entries": [
            {
                "recipe": ["White", "White", "White", "White", "White"],
                "rgb": [255, 255, 255],
            }
        ],
    },
    separators=(",", ":"),
).encode("utf-8")


def _npy_lut_bytes() -> bytes:
    output = io.BytesIO()
    np.save(output, np.array([[255, 255, 255]], dtype=np.uint8))
    return output.getvalue()


def _npz_lut_bytes() -> bytes:
    output = io.BytesIO()
    np.savez(
        output,
        rgb=np.array([[255, 255, 255]], dtype=np.uint8),
        stacks=np.array([[0, 0, 0, 0, 0]], dtype=np.int32),
    )
    return output.getvalue()


def _msgpack_lut_bytes() -> bytes:
    return msgpack.packb(
        [
            {
                "recipe": ["White", "White", "White", "White", "White"],
                "rgb": [255, 255, 255],
            }
        ],
        use_bin_type=True,
    )


def _bundle_bytes(
    lut_bytes: bytes = _DEFAULT_LUT_BYTES,
    *,
    lut_path: str = "payload/cloud_lut.json",
    package_extra: dict[str, Any] | None = None,
    file_extra: dict[str, Any] | None = None,
    extra_file: str | None = None,
    extra_dir: str | None = None,
    include_parent_dirs: bool = False,
    symlink_file: str | None = None,
    omit_lut_file: bool = False,
    duplicate_lut_file: bool = False,
    omit_content_hash: bool = False,
) -> bytes:
    file_entry = {
        "role": "lut_file",
        "path": lut_path,
        "sha256": _sha256(lut_bytes),
        "bytes": len(lut_bytes),
        "content_hash": _sha256(lut_bytes),
    }
    if omit_content_hash:
        file_entry.pop("content_hash")
    if file_extra:
        file_entry.update(file_extra)
    files = [] if omit_lut_file else [file_entry]
    if duplicate_lut_file:
        files.append({**file_entry, "path": "payload/second.json"})
    manifest = {
        "schema_version": "1.0",
        "files": files,
    }
    if package_extra:
        manifest.update(package_extra)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        if include_parent_dirs:
            parent = PurePosixPath(lut_path).parent
            parts = parent.parts
            for index in range(1, len(parts) + 1):
                zf.writestr("/".join(parts[:index]) + "/", b"")
        zf.writestr("lumina_lut_bundle.json", json.dumps(manifest))
        if not omit_lut_file:
            zf.writestr(lut_path, lut_bytes)
        if duplicate_lut_file:
            zf.writestr("payload/second.json", lut_bytes)
        if extra_file is not None:
            zf.writestr(extra_file, b"extra")
        if extra_dir is not None:
            zf.writestr(extra_dir.rstrip("/") + "/", b"")
        if symlink_file is not None:
            info = zipfile.ZipInfo(symlink_file)
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, b"target")
    return output.getvalue()


def _entry(package_data: bytes, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "lut_id": "official/test-lut",
        "revision_id": "rev-1",
        "content_hash": _sha256(_DEFAULT_LUT_BYTES),
        "channel": "official",
        "visibility": "public",
        "local_path": "Official/Test/test_lut.json",
        "display": {"name": "Test LUT"},
        "compatibility": {"color_modes": ["4-Color (RYBW)"]},
        "package_url": "/api/material-registry/v1/luts/packages/test.zip",
        "package_sha256": _sha256(package_data),
        "package_bytes": len(package_data),
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("private_channels", [False, True])
def test_install_failover_keeps_verified_identity_and_private_channel_boundary(monkeypatch, private_channels):
    primary = "https://primary.test/api/material-registry/v1"
    backup = "https://backup.test/api/material-registry/v1"
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", primary)
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_FALLBACK_URL", backup)
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_CHANNELS", "official")
    monkeypatch.delenv("LUMINA_LUT_REGISTRY_TOKEN", raising=False)
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_TOKEN", raising=False)
    package = _bundle_bytes()
    entry = _entry(package, package_url=backup + "/luts/packages/test.zip")
    calls = []
    def handle(request):
        calls.append((request.url.host, request.url.path))
        if request.url.path.endswith("/catalog"):
            if private_channels:
                return httpx.Response(200, json={"items": [{**entry, "package_url": primary + "/luts/packages/test.zip"}]})
            if request.url.host == "primary.test":
                return httpx.Response(503)
            return httpx.Response(200, json={"items": [entry]})
        if request.url.host == "primary.test":
            return httpx.Response(503)
        return httpx.Response(200, content=package)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        if private_channels:
            with pytest.raises(sync.LutRegistryRemoteError):
                sync.install_lut_package(lut_id=entry["lut_id"], revision_id=entry["revision_id"],
                                         channels=["team"], client=client)
            assert all(host == "primary.test" for host, _ in calls)
        else:
            record = sync.install_lut_package(lut_id=entry["lut_id"], revision_id=entry["revision_id"], client=client)
            assert record["revision_id"] == entry["revision_id"]
            assert (Path(LUTManager.LUT_PRESET_DIR) / record["installed_path"]).read_bytes() == _DEFAULT_LUT_BYTES
            assert [host for host, _ in calls] == ["primary.test", "backup.test", "primary.test", "backup.test"]


def _catalog_install_client(
    entry: dict[str, Any],
    package: bytes,
    *,
    requests: list[httpx.Request] | None = None,
    package_status: int = 200,
    package_headers: dict[str, str] | None = None,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if request.url.path.endswith("/luts/catalog"):
            return httpx.Response(200, json={"items": [entry], "total": 1})
        return httpx.Response(
            package_status,
            content=package,
            headers=package_headers,
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def _install_catalog_entry(
    entry: dict[str, Any],
    package: bytes,
    *,
    requests: list[httpx.Request] | None = None,
    package_status: int = 200,
    package_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    client = _catalog_install_client(
        entry,
        package,
        requests=requests,
        package_status=package_status,
        package_headers=package_headers,
    )
    return sync.install_lut_package(
        lut_id=str(entry["lut_id"]),
        revision_id=str(entry["revision_id"]),
        client=client,
    )


@pytest.fixture(autouse=True)
def _isolated_lut_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original = LUTManager.LUT_PRESET_DIR
    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(tmp_path / "lut-preset"))
    LUTManager.invalidate_preset_cache()
    try:
        yield Path(LUTManager.LUT_PRESET_DIR)
    finally:
        monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", original)
        LUTManager.invalidate_preset_cache()


def test_lut_scan_skips_sync_index(_isolated_lut_dir: Path) -> None:
    sync_index = _isolated_lut_dir / "_sync" / "luts" / "index.json"
    sync_index.parent.mkdir(parents=True)
    sync_index.write_text('{"luts": []}', encoding="utf-8")
    real_lut = _isolated_lut_dir / "Cloud" / "Official" / "Test" / "test_lut.json"
    real_lut.parent.mkdir(parents=True)
    real_lut.write_text('{"color_mode":"4-Color (RYBW)","entries":[]}', encoding="utf-8")

    files = LUTManager.get_all_lut_files()

    assert "Cloud - Official - Test - test_lut" in files
    assert all("_sync" not in Path(path).parts for path in files.values())


def test_catalog_uses_configured_channels_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "items": [{"lut_id": "one", "package_url": "/packages/one.zip"}],
                "total": 1,
            },
        )

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_CHANNELS", "official, community")
    client = httpx.Client(transport=httpx.MockTransport(handler))

    payload = sync.fetch_remote_catalog(client=client, limit=5000, offset=-1)

    assert payload["configured"] is True
    assert payload["channels"] == ["official", "community"]
    assert payload["items"][0]["lut_id"] == "one"
    assert requests[0].url.path == "/api/material-registry/v1/luts/catalog"
    assert requests[0].url.params.multi_items() == [
        ("channel", "official"),
        ("channel", "community"),
        ("limit", "200"),
        ("offset", "0"),
    ]


def test_catalog_accepts_registry_service_luts_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "1.0",
                "channels": ["official"],
                "count": 1,
                "total_count": 1,
                "offset": 0,
                "limit": 200,
                "luts": [
                    {
                        "lut_id": "registry-lut",
                        "local_path": "Official/Test/Readable LUT.json",
                        "package_url": "/packages/one.zip",
                    }
                ],
            },
        )

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    payload = sync.fetch_remote_catalog(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    assert payload["items"][0]["lut_id"] == "registry-lut"
    assert payload["items"][0]["name"] == "Readable LUT"
    assert payload["items"][0]["display"]["name"] == "Readable LUT"
    assert payload["total"] == 1


def test_catalog_marks_existing_local_lut_available(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_lut = _isolated_lut_dir / "Official" / "Test" / "Readable LUT.json"
    local_lut.parent.mkdir(parents=True)
    lut_bytes = b'{"color_mode":"4-Color (RYBW)","entries":[]}'
    local_lut.write_bytes(lut_bytes)
    content_hash = _registry_lut_content_hash("Official/Test/Readable LUT.json", lut_bytes)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "lut_id": "registry-lut",
                        "revision_id": "rev-1",
                        "content_hash": "sha256:" + content_hash,
                        "local_path": "Official/Test/Readable LUT.json",
                        "package_url": "/packages/one.zip",
                    }
                ],
                "total": 1,
            },
        )

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    payload = sync.fetch_remote_catalog(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    item = payload["items"][0]
    assert item["local_state"] == "local_available"
    assert item["local_exists"] is True
    assert item["local_match_path"] == "Official/Test/Readable LUT.json"


def _install_history_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    old_bundle = _bundle_bytes()
    old_entry = _entry(old_bundle)
    old = sync.install_lut_archive_bytes(old_entry, old_bundle, source_url="offline:old")
    new_bytes = _DEFAULT_LUT_BYTES.replace(b"255,255,255", b"220,220,220")
    new_bundle = _bundle_bytes(new_bytes)
    new_entry = _entry(new_bundle, revision_id="rev-2", content_hash=_sha256(new_bytes))
    new = sync.install_lut_archive_bytes(new_entry, new_bundle, source_url="offline:new")
    return old, new


def test_lut_versions_update_restore_and_reinstall_preserve_project_files(_isolated_lut_dir: Path) -> None:
    old, new = _install_history_pair()
    old_path = _isolated_lut_dir / old["installed_path"]
    new_path = _isolated_lut_dir / new["installed_path"]
    old_bytes, new_bytes = old_path.read_bytes(), new_path.read_bytes()
    assert old_path != new_path
    assert sync._catalog_item_local_presence(new)["local_state"] == "installed"
    assert sync._catalog_item_local_presence(old)["local_state"] == "local_available"
    unseen = {**new, "revision_id": "rev-unseen", "content_hash": "sha256:" + "b" * 64}
    assert sync._catalog_item_local_presence(unseen)["local_state"] == "update_available"
    # The restore boundary needs no registry credentials or network download.
    client = TestClient(create_app())
    response = client.post("/api/lut-registry/restore", json={"lut_id": old["lut_id"], "revision_id": old["revision_id"]})
    assert response.status_code == 200
    assert sync._catalog_item_local_presence(old)["local_state"] == "installed"
    assert sync._catalog_item_local_presence(new)["local_state"] == "local_available"
    history = client.get("/api/lut-registry/status").json()["history"][0]
    assert history["current_revision"] == old["revision_id"]
    assert len(history["revisions"]) == 2
    assert all(row["available"] for row in history["revisions"])
    local_catalog = client.get("/api/lut/details/catalog").json()
    versions = {row["path"]: row["local_version"] for group in local_catalog["groups"] for row in group["items"]}
    assert versions[f'lut-preset/{old["installed_path"]}']["current"] is True
    assert versions[f'lut-preset/{new["installed_path"]}']["current"] is False
    assert old_path.read_bytes() == old_bytes and new_path.read_bytes() == new_bytes
    files = LUTManager.get_all_lut_files()
    assert str(old_path) in files.values() and str(new_path) in files.values()
    # An idempotent re-install can make a stored version current again.
    bundle = _bundle_bytes(new_bytes)
    sync.install_lut_archive_bytes(_entry(bundle, revision_id="rev-2", content_hash=_sha256(new_bytes)), bundle, source_url="offline:new")
    assert sync.registry_status()["history"][0]["current_revision"] == "rev-2"
    local_catalog = client.get("/api/lut/details/catalog").json()
    versions = {row["path"]: row["local_version"] for group in local_catalog["groups"] for row in group["items"]}
    assert versions[f'lut-preset/{old["installed_path"]}']["current"] is False
    assert versions[f'lut-preset/{new["installed_path"]}']["current"] is True


@pytest.mark.parametrize("failure", ["missing", "modified"])
def test_lut_history_rejects_unusable_versions_and_download_recovers_without_overwriting(
    _isolated_lut_dir: Path, failure: str,
) -> None:
    old, new = _install_history_pair()
    path = _isolated_lut_dir / new["installed_path"]
    original = path.read_bytes()
    if failure == "missing":
        path.unlink()
    else:
        path.write_bytes(b"user changes")
    assert sync._catalog_item_local_presence(new)["local_state"] == f"local_{failure}"
    before = sync.read_installed_index()
    response = TestClient(create_app()).post("/api/lut-registry/restore", json={"lut_id": new["lut_id"], "revision_id": new["revision_id"]})
    assert response.status_code == 422
    assert sync.read_installed_index() == before
    history = sync.registry_status()["history"][0]
    assert not next(row for row in history["revisions"] if row["revision_id"] == new["revision_id"])["available"]
    bundle = _bundle_bytes(original)
    restored = sync.install_lut_archive_bytes(
        _entry(bundle, revision_id=new["revision_id"], content_hash=_sha256(original)), bundle, source_url="offline:repair",
    )
    assert (_isolated_lut_dir / restored["installed_path"]).read_bytes() == original
    if failure == "modified":
        assert path.read_bytes() == b"user changes"
    assert (_isolated_lut_dir / old["installed_path"]).read_bytes() == _DEFAULT_LUT_BYTES
    assert sync._catalog_item_local_presence(new)["local_state"] == "installed"


def test_lut_legacy_history_uses_last_install_without_rewriting_index() -> None:
    old, new = _install_history_pair()
    index = sync.read_installed_index()
    index.pop("current_revisions")
    index["luts"][sync._record_key(old)]["installed_at"] = "2026-01-01T00:00:00Z"
    index["luts"][sync._record_key(new)]["installed_at"] = "2026-02-01T00:00:00Z"
    sync._write_installed_index(index)
    assert sync.registry_status()["history"][0]["current_revision"] == new["revision_id"]
    assert sync.read_installed_index() == index


def test_catalog_does_not_mark_path_match_available_when_content_hash_differs(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_lut = _isolated_lut_dir / "Official" / "Test" / "Readable LUT.json"
    local_lut.parent.mkdir(parents=True)
    local_lut.write_bytes(b'{"color_mode":"4-Color (RYBW)","entries":[]}')

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "lut_id": "registry-lut",
                        "revision_id": "rev-1",
                        "content_hash": "sha256:" + "a" * 64,
                        "local_path": "Official/Test/Readable LUT.json",
                        "package_url": "/packages/one.zip",
                    }
                ],
                "total": 1,
            },
        )

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    payload = sync.fetch_remote_catalog(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    item = payload["items"][0]
    assert item["local_state"] == "not_installed"
    assert item["local_exists"] is False
    assert item["local_match_path"] == "Official/Test/Readable LUT.json"


def test_registry_status_counts_existing_local_luts(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_lut = _isolated_lut_dir / "Official" / "Test" / "Readable LUT.json"
    local_lut.parent.mkdir(parents=True)
    local_lut.write_text('{"color_mode":"4-Color (RYBW)","entries":[]}', encoding="utf-8")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    payload = sync.registry_status()

    assert payload["local_lut_count"] == 1
    assert payload["installed_count"] == 0
    assert payload["local_luts"][0]["local_path"] == "Official/Test/Readable LUT.json"


def test_catalog_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "")
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_URL", raising=False)

    with pytest.raises(sync.LutRegistryConfigError):
        sync.fetch_remote_catalog(client=httpx.Client(transport=httpx.MockTransport(lambda request: None)))


def test_catalog_rejects_base_url_userinfo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LUMINA_LUT_REGISTRY_URL",
        "https://user:pass@registry.example/api/material-registry/v1",
    )

    with pytest.raises(sync.LutRegistryConfigError, match="userinfo|credentials"):
        sync.fetch_remote_catalog(client=httpx.Client(transport=httpx.MockTransport(lambda request: None)))


def test_catalog_falls_back_to_material_registry_url_and_default_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": [], "total": 0})

    monkeypatch.delenv("LUMINA_LUT_REGISTRY_URL", raising=False)
    monkeypatch.delenv("LUMINA_LUT_REGISTRY_CHANNELS", raising=False)
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", raising=False)
    monkeypatch.setenv(
        "LUMINA_MATERIAL_REGISTRY_URL",
        "https://material.example/api/material-registry/v1/",
    )

    payload = sync.fetch_remote_catalog(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    assert payload["configured"] is True
    assert payload["channels"] == ["official", "community"]
    assert requests[0].url.host == "material.example"
    assert requests[0].url.params.multi_items()[:2] == [
        ("channel", "official"),
        ("channel", "community"),
    ]


def test_install_valid_package_writes_cloud_lut_index_and_invalidates_scan(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    display = {"name": "Test LUT", "manufacturer": "Brand", "market_names": {"INTL": "US LUT"}, "sku": "IMG-1"}
    entry = _entry(bundle, display=display)
    requests: list[httpx.Request] = []

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    result = _install_catalog_entry(entry, bundle, requests=requests)

    installed_path = _isolated_lut_dir / Path(result["installed_path"])
    assert installed_path == _isolated_lut_dir / "Cloud" / "Official" / "Test" / "test_lut.json"
    assert installed_path.read_bytes() == _DEFAULT_LUT_BYTES
    index = json.loads((_isolated_lut_dir / "_sync" / "luts" / "index.json").read_text(encoding="utf-8"))
    assert index["luts"]["official/test-lut@rev-1"]["content_hash"] == entry["content_hash"]
    assert index["luts"]["official/test-lut@rev-1"]["installed_path"] == "Cloud/Official/Test/test_lut.json"
    assert requests[0].url.path.endswith("/luts/catalog")
    assert requests[1].headers.get("authorization") is None
    assert "Cloud - Official - Test - test_lut" in LUTManager.get_all_lut_files()
    monkeypatch.setattr(lut_router, "_lut_details_service", None)
    lut_router.get_lut_details_service.cache_clear()
    local = lut_router.get_lut_details_catalog().groups[0].items[0]
    assert {k: v for k, v in local.display.items() if k != "lut_board_preview"} == display
    board = local.display["lut_board_preview"]
    assert board["pages"][0]["count"] == 1
    assert local.name == "Cloud - Official - Test - test_lut"
    assert local.path.endswith("Cloud/Official/Test/test_lut.json")
    installed_path.write_bytes(_DEFAULT_LUT_BYTES + b"\n")
    assert lut_router.get_lut_details_catalog().groups[0].items[0].display == {"lut_board_preview": board}


def test_install_accepts_registry_service_sha256_prefixed_content_hash(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lut_bytes = json.dumps(
        {
            "color_mode": "4-Color (RYBW)",
            "entries": [{"recipe": [0, 0, 0, 0, 0], "rgb": [10, 20, 30]}],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    lut_path = "luts/test/registry_lut.json"
    logical_content_hash = _registry_lut_content_hash(lut_path, lut_bytes)
    bundle = _bundle_bytes(
        lut_bytes,
        lut_path=lut_path,
        omit_content_hash=True,
        package_extra={"content_hash": f"sha256:{logical_content_hash}"},
    )
    entry = _entry(
        bundle,
        content_hash=f"sha256:{logical_content_hash}",
        local_path="Official/Test/registry_lut.json",
    )

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    result = _install_catalog_entry(entry, bundle)

    installed_path = _isolated_lut_dir / Path(result["installed_path"])
    assert installed_path == _isolated_lut_dir / "Cloud" / "Official" / "Test" / "registry_lut.json"
    assert installed_path.read_bytes() == lut_bytes
    assert result["content_hash"] == logical_content_hash


def test_source_catalog_skips_sync_index(_isolated_lut_dir: Path) -> None:
    sync_index = _isolated_lut_dir / "_sync" / "luts" / "index.json"
    sync_index.parent.mkdir(parents=True)
    sync_index.write_text('{"color_mode":"4-Color (RYBW)","entries":[]}', encoding="utf-8")

    LUTManager.invalidate_source_catalog_cache()
    catalog = LUTManager.get_source_catalog()

    legacy_items = [
        item
        for group in catalog["legacy_groups"]
        for item in group["items"]
    ]
    assert legacy_items == []


def test_details_catalog_skips_sync_index(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_index = _isolated_lut_dir / "_sync" / "luts" / "index.json"
    sync_index.parent.mkdir(parents=True)
    sync_index.write_text('{"color_mode":"4-Color (RYBW)","entries":[]}', encoding="utf-8")
    real_lut = _isolated_lut_dir / "Cloud" / "Official" / "Test" / "test_lut.json"
    real_lut.parent.mkdir(parents=True)
    real_lut.write_text('{"color_mode":"4-Color (RYBW)","entries":[]}', encoding="utf-8")
    monkeypatch.setattr(lut_router, "_lut_details_service", None)
    lut_router.get_lut_details_service.cache_clear()

    response = TestClient(create_app()).get("/api/lut/details/catalog")

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload)
    assert "_sync" not in serialized
    assert "test_lut" in serialized


def test_install_allows_required_parent_directory_entries(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes(include_parent_dirs=True)
    entry = _entry(bundle)

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    result = _install_catalog_entry(entry, bundle)

    assert (_isolated_lut_dir / Path(result["installed_path"])).is_file()


def test_install_rejects_extra_directory_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _bundle_bytes(include_parent_dirs=True, extra_dir="payload/extra_dir")
    entry = _entry(bundle)

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    with pytest.raises(sync.LutRegistryPackageError, match="unexpected|extra|package"):
        _install_catalog_entry(entry, bundle)


def test_install_rolls_back_lut_when_index_write_fails(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    entry = _entry(bundle)
    target = _isolated_lut_dir / "Cloud" / "Official" / "Test" / "test_lut.json"
    target.parent.mkdir(parents=True)
    target.write_text("previous", encoding="utf-8")

    def fail_index_write(payload: dict[str, Any]) -> None:
        raise OSError("index locked")

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    monkeypatch.setattr(sync, "_write_installed_index", fail_index_write)

    with pytest.raises(sync.LutRegistryPackageError, match="index|install"):
        _install_catalog_entry(entry, bundle)

    assert target.read_text(encoding="utf-8") == "previous"


@pytest.mark.parametrize(
    ("extension", "lut_bytes"),
    [
        (".npy", _npy_lut_bytes()),
        (".npz", _npz_lut_bytes()),
        (".msgpack", _msgpack_lut_bytes()),
    ],
)
def test_install_accepts_supported_lut_extensions(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    extension: str,
    lut_bytes: bytes,
) -> None:
    bundle = _bundle_bytes(lut_bytes, lut_path=f"payload/cloud_lut{extension}")
    entry = _entry(
        bundle,
        content_hash=_sha256(lut_bytes),
        local_path=f"Official/Test/test_lut{extension}",
    )

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    result = _install_catalog_entry(entry, bundle)

    installed_path = _isolated_lut_dir / Path(result["installed_path"])
    assert installed_path.suffix == extension
    assert installed_path.read_bytes() == lut_bytes


@pytest.mark.parametrize(
    ("make_candidate", "message"),
    [
        (lambda package, entry: ({**entry, "package_sha256": "0" * 64}, package), "sha256"),
        (lambda package, entry: ({**entry, "package_bytes": len(package) + 1}, package), "bytes"),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(file_extra={"sha256": "f" * 64}),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "sha256",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(file_extra={"sha256": None}),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "sha256",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(file_extra={"bytes": 999}),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "bytes",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(
                        file_extra={"bytes": None, "size": None}
                    ),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "bytes",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(file_extra={"content_hash": "different"}),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "content_hash",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(lut_path="../escape.json"),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "unsafe",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(lut_path="payload/a:b.json"),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "unsafe",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(lut_path="payload/./cloud_lut.json"),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "unsafe",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(lut_path="payload//cloud_lut.json"),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "unsafe",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(extra_file="unexpected.txt"),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "unexpected",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(symlink_file="payload/link.json"),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "special",
        ),
        (
            lambda package, entry: (
                {**entry, "content_hash": ""},
                package,
            ),
            "content_hash",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(omit_content_hash=True),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "content_hash",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(
                        file_extra={"content_hash": "f" * 64}
                    ),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "content_hash",
        ),
        (
            lambda package, entry: (
                {**entry, "content_hash": "not-a-sha256"},
                package,
            ),
            "content_hash",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(
                        json.dumps(
                            {
                                "color_mode": "4-Color (RYBW)",
                                "entries": [
                                    {"recipe": [0, 0, 0, 0, 0], "rgb": [1, 2, 3]}
                                ],
                            },
                            separators=(",", ":"),
                        ).encode("utf-8"),
                        file_extra={
                            "sha256": _sha256(
                                json.dumps(
                                    {
                                        "color_mode": "4-Color (RYBW)",
                                        "entries": [
                                            {"recipe": [0, 0, 0, 0, 0], "rgb": [1, 2, 3]}
                                        ],
                                    },
                                    separators=(",", ":"),
                                ).encode("utf-8")
                            ),
                            "content_hash": entry["content_hash"],
                        },
                    ),
                    package_url=entry["package_url"],
                    content_hash=entry["content_hash"],
                ),
                bad_package,
            ),
            "content_hash",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(
                        file_extra={"content_hash": "not-a-sha256"}
                    ),
                    package_url=entry["package_url"],
                    content_hash="not-a-sha256",
                ),
                bad_package,
            ),
            "content_hash",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(omit_lut_file=True),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "lut_file",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(duplicate_lut_file=True),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "lut_file",
        ),
        (
            lambda package, entry: (
                _entry(
                    bad_package := _bundle_bytes(lut_path="payload/cloud_lut.txt"),
                    package_url=entry["package_url"],
                ),
                bad_package,
            ),
            "extension",
        ),
        (
            lambda package, entry: (
                {
                    **entry,
                    "package_url": "https://evil.example/api/material-registry/v1/luts/packages/test.zip",
                },
                package,
            ),
            "origin",
        ),
        (
            lambda package, entry: (
                {
                    **entry,
                    "package_url": "https://user:pass@registry.example/api/material-registry/v1/luts/packages/test.zip",
                },
                package,
            ),
            "userinfo|credentials",
        ),
        (
            lambda package, entry: (
                {**entry, "package_url": "/admin/debug"},
                package,
            ),
            "package",
        ),
        (
            lambda package, entry: (
                {**entry, "package_url": "/packages/test.zip"},
                package,
            ),
            "package",
        ),
        (
            lambda package, entry: (
                {**entry, "package_url": "/api/material-registry/v1/luts/packages/%2e%2e/test.zip"},
                package,
            ),
            "package_url",
        ),
        (
            lambda package, entry: (
                {**entry, "package_url": "/api/material-registry/v1/luts/packages/%2E%2E/test.zip"},
                package,
            ),
            "package_url",
        ),
        (
            lambda package, entry: (
                {**entry, "package_url": "/api/material-registry/v1/luts/packages/foo%2ftest.zip"},
                package,
            ),
            "package_url",
        ),
        (
            lambda package, entry: (
                {**entry, "package_url": "/api/material-registry/v1/luts/packages/foo%5ctest.zip"},
                package,
            ),
            "package_url",
        ),
        (
            lambda package, entry: (
                {**entry, "package_url": "/api/material-registry/v1/luts/packages/test.zip?token=secret"},
                package,
            ),
            "query|fragment",
        ),
        (
            lambda package, entry: (
                {**entry, "package_url": "/api/material-registry/v1/luts/packages/test.zip#secret"},
                package,
            ),
            "query|fragment",
        ),
        (
            lambda package, entry: (
                {**entry, "package_url": "ftp://registry.example/test.zip"},
                package,
            ),
            "HTTP",
        ),
        (
            lambda package, entry: (
                {**entry, "local_path": "../escape.json"},
                package,
            ),
            "local_path",
        ),
        (
            lambda package, entry: (
                {**entry, "local_path": "Official/Test/a:b.json"},
                package,
            ),
            "local_path",
        ),
        (
            lambda package, entry: (
                {**entry, "local_path": "Official/./Test/test.json"},
                package,
            ),
            "local_path",
        ),
        (
            lambda package, entry: (
                {**entry, "local_path": "Official//Test/test.json"},
                package,
            ),
            "local_path",
        ),
        (
            lambda package, entry: (
                {**entry, "local_path": "Official/Test/test_lut.txt"},
                package,
            ),
            "extension",
        ),
    ],
)
def test_install_rejects_invalid_packages(
    monkeypatch: pytest.MonkeyPatch,
    make_candidate,
    message: str,
) -> None:
    base_package = _bundle_bytes()
    base_entry = _entry(base_package)
    candidate, package = make_candidate(base_package, base_entry)

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    with pytest.raises(sync.LutRegistryPackageError, match=message):
        _install_catalog_entry(candidate, package)


def test_install_rejects_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    package = _bundle_bytes()
    entry = _entry(package)

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    with pytest.raises(sync.LutRegistryRemoteError, match="redirect"):
        _install_catalog_entry(entry, package, package_status=302)


def test_install_accepts_absolute_package_url_under_registry_package_path(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    entry = _entry(
        bundle,
        package_url="https://registry.example/api/material-registry/v1/luts/packages/test.zip",
    )

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    result = _install_catalog_entry(entry, bundle)

    assert (_isolated_lut_dir / Path(result["installed_path"])).is_file()
    assert result["source_url"] == entry["package_url"]


def test_install_accepts_registry_base_url_without_path(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    entry = _entry(
        bundle,
        package_url="/luts/packages/test.zip",
    )
    requests: list[httpx.Request] = []

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example")
    result = _install_catalog_entry(entry, bundle, requests=requests)

    assert (_isolated_lut_dir / Path(result["installed_path"])).is_file()
    assert requests[0].url.path == "/luts/catalog"
    assert requests[1].url.path == "/luts/packages/test.zip"


def test_install_normalizes_catalog_local_path_with_cloud_prefix(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    entry = _entry(bundle, local_path="Cloud/Official/Test/test_lut.json")

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    result = _install_catalog_entry(entry, bundle)

    assert result["local_path"] == "Official/Test/test_lut.json"
    assert result["installed_path"] == "Cloud/Official/Test/test_lut.json"
    assert (_isolated_lut_dir / "Cloud" / "Official" / "Test" / "test_lut.json").is_file()


def test_install_rejects_catalog_package_larger_than_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    entry = _entry(bundle, package_bytes=len(bundle) + 1024)
    monkeypatch.setattr(sync, "MAX_LUT_PACKAGE_BYTES", len(bundle) - 1)
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    with pytest.raises(sync.LutRegistryPackageError, match="maximum size"):
        _install_catalog_entry(entry, bundle)


def test_install_rejects_package_content_length_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    entry = _entry(bundle)
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    with pytest.raises(sync.LutRegistryPackageError, match="Content-Length"):
        _install_catalog_entry(
            entry,
            bundle,
            package_headers={"content-length": str(len(bundle) + 1)},
        )


def test_install_rejects_lut_file_larger_than_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    entry = _entry(bundle)
    monkeypatch.setattr(sync, "MAX_LUT_FILE_BYTES", 1)
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    with pytest.raises(sync.LutRegistryPackageError, match="maximum size"):
        _install_catalog_entry(entry, bundle)


def test_install_rejects_unloadable_lut_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_lut_bytes = b'{"color_mode":"4-Color (RYBW)","entries":[]}'
    bundle = _bundle_bytes(bad_lut_bytes)
    entry = _entry(
        bundle,
        content_hash=_sha256(bad_lut_bytes),
    )
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    with pytest.raises(sync.LutRegistryPackageError, match="RGB|valid rgb|contains no"):
        _install_catalog_entry(entry, bundle)


def test_install_rejects_when_cross_process_lock_exists(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    entry = _entry(bundle)
    lock_path = _isolated_lut_dir / "_sync" / "luts" / "install.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("active", encoding="utf-8")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_LOCK_STALE_S", "3600")

    with pytest.raises(sync.LutRegistryPackageError, match="already running"):
        _install_catalog_entry(entry, bundle)

    assert lock_path.exists()


def test_install_removes_stale_cross_process_lock(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    entry = _entry(bundle)
    lock_path = _isolated_lut_dir / "_sync" / "luts" / "install.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("stale", encoding="utf-8")
    old_time = time.time() - 3600
    os.utime(lock_path, (old_time, old_time))
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_LOCK_STALE_S", "1")

    result = _install_catalog_entry(entry, bundle)

    assert (_isolated_lut_dir / Path(result["installed_path"])).is_file()
    assert not lock_path.exists()


def test_router_install_ignores_client_supplied_catalog_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle_bytes()
    server_entry = _entry(bundle, package_url="/api/material-registry/v1/luts/packages/good.zip")
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/luts/catalog"):
            return httpx.Response(200, json={"items": [server_entry], "total": 1})
        return httpx.Response(200, content=bundle)

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    monkeypatch.setattr(sync, "_make_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    client = TestClient(create_app())

    response = client.post(
        "/api/lut-registry/install",
        json={
            "lut_id": server_entry["lut_id"],
            "revision_id": server_entry["revision_id"],
            "package_url": "/api/material-registry/v1/luts/packages/bad.zip",
            "local_path": "../escape.json",
        },
    )

    assert response.status_code == 200
    assert requested_paths[-1].endswith("/luts/packages/good.zip")


@pytest.mark.parametrize(
    "package_url",
    [
        "/api/material-registry/v1/luts/packages/test.zip?token=secret",
        "/api/material-registry/v1/luts/packages/test.zip#secret",
    ],
)
def test_install_rejects_package_url_query_fragment_without_writing_index(
    _isolated_lut_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    package_url: str,
) -> None:
    bundle = _bundle_bytes()
    entry = _entry(bundle, package_url=package_url)
    requests: list[httpx.Request] = []

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")

    with pytest.raises(sync.LutRegistryPackageError, match="query|fragment"):
        _install_catalog_entry(entry, bundle, requests=requests)

    assert len(requests) == 1
    assert requests[0].url.path.endswith("/luts/catalog")
    assert not (_isolated_lut_dir / "_sync" / "luts" / "index.json").exists()


@pytest.mark.parametrize("missing_field", ["package_sha256", "package_bytes"])
def test_install_requires_package_integrity_fields(
    monkeypatch: pytest.MonkeyPatch,
    missing_field: str,
) -> None:
    package = _bundle_bytes()
    entry = _entry(package)
    entry.pop(missing_field)

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    with pytest.raises(sync.LutRegistryPackageError, match=missing_field):
        _install_catalog_entry(entry, package)


def test_router_catalog_status_install_success(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _bundle_bytes()
    entry = _entry(bundle)
    invalidations: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/luts/catalog"):
            return httpx.Response(200, json={"items": [entry], "total": 1})
        return httpx.Response(200, content=bundle)

    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    monkeypatch.setattr(sync, "_make_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(
        "api.routers.lut_registry.invalidate_lut_details_service_cache",
        lambda: invalidations.append(True),
    )
    client = TestClient(create_app())

    catalog = client.get("/api/lut-registry/catalog")
    status = client.get("/api/lut-registry/status")
    installed = client.post(
        "/api/lut-registry/install",
        json={"lut_id": entry["lut_id"], "revision_id": entry["revision_id"]},
    )

    assert catalog.status_code == 200
    assert catalog.json()["items"][0]["lut_id"] == entry["lut_id"]
    assert status.status_code == 200
    assert status.json()["configured"] is True
    assert installed.status_code == 200
    assert installed.json()["lut_id"] == entry["lut_id"]
    assert invalidations == [True]


def test_router_maps_config_and_package_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "")
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_URL", raising=False)
    client = TestClient(create_app())

    missing_config = client.get("/api/lut-registry/catalog")
    assert missing_config.status_code == 503

    bundle = _bundle_bytes()
    entry = _entry(bundle, package_sha256="0" * 64)
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://registry.example/api/material-registry/v1")
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/luts/catalog"):
            return httpx.Response(200, json={"items": [entry], "total": 1})
        return httpx.Response(200, content=bundle)

    monkeypatch.setattr(
        sync,
        "_make_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    invalid_package = client.post(
        "/api/lut-registry/install",
        json={"lut_id": entry["lut_id"], "revision_id": entry["revision_id"]},
    )
    assert invalid_package.status_code == 422
    assert "sha256" in invalid_package.json()["detail"]


@pytest.mark.parametrize("denied", [401, 403])
def test_lut_catalog_route_forwards_denied_access(monkeypatch, denied: int) -> None:
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "https://private.test/v1")
    transport = httpx.MockTransport(lambda _: httpx.Response(denied))
    monkeypatch.setattr(sync, "_make_http_client", lambda: httpx.Client(transport=transport))
    assert TestClient(create_app()).get("/api/lut-registry/catalog").status_code == denied
