"""Real offline package installation, identity and library lifecycle."""

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from utils.lut_manager import LUTManager
from api.services import lut_registry_sync as sync
from test_lut_registry_sync_unit import _bundle_bytes, _DEFAULT_LUT_BYTES, _entry


def make_seed(path: Path, *, channel="community", corrupt=False, local_path="Brand/PLA/seed.json") -> dict:
    identity = {"lut_id": "lut_seed", "revision_id": "rev_seed", "channel": channel,
                "local_path": local_path, "content_hash": hashlib.sha256(_DEFAULT_LUT_BYTES).hexdigest()}
    package = _bundle_bytes(package_extra=identity)
    entry = _entry(package, **identity)
    entry["path"] = "lut-packages/seed.zip"
    if corrupt:
        entry["package_sha256"] = "0" * 64
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(entry["path"], package)
        archive.writestr("lumina_lut_seed.json", json.dumps({
            "kind": "lumina_lut_seed", "schema_version": "1.0", "dataset_version": "test.1",
            "packages": [entry],
        }))
    return entry


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(tmp_path / "presets"))
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(tmp_path / "shared/luts/Cloud_sync"))
    monkeypatch.setenv("LUMINA_CUSTOM_LUT_DIR", str(tmp_path / "shared/luts/Custom"))
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "")
    LUTManager.invalidate_preset_cache()
    yield
    LUTManager.invalidate_preset_cache()


def test_seed_and_shared_installer_reject_target_format_mismatch(monkeypatch, tmp_path):
    from api.lut_seed import install_lut_seed_if_needed
    seed = tmp_path / "seed.zip"
    entry = make_seed(seed, local_path="Brand/PLA/seed.npy")
    monkeypatch.setenv("LUMINA_LUTS_SEED_PATH", str(seed))
    with pytest.raises(sync.LutRegistryPackageError, match="extension"):
        install_lut_seed_if_needed()
    with zipfile.ZipFile(seed) as archive:
        package = archive.read(entry["path"])
    with pytest.raises(sync.LutRegistryPackageError, match="extension"):
        sync.install_lut_archive_bytes(entry, package, source_url="https://public.test/package.zip")
    assert not list(LUTManager.cloud_lut_dir().rglob("*.npy"))


def test_offline_seed_keeps_public_identity_and_deleted_library_empty(monkeypatch, tmp_path):
    from api.lut_seed import install_lut_seed_if_needed, restore_lut_seed
    seed = tmp_path / "seed.zip"
    make_seed(seed)
    monkeypatch.setenv("LUMINA_LUTS_SEED_PATH", str(seed))
    result = install_lut_seed_if_needed()
    assert result["installed_count"] == 1
    installed = LUTManager.cloud_lut_dir() / "Brand/PLA/seed.json"
    assert installed.read_bytes() == _DEFAULT_LUT_BYTES
    record = sync.read_installed_index()["luts"]["lut_seed@rev_seed"]
    assert record["channel"] == "community"
    assert record["installed_path"] == "Cloud/Brand/PLA/seed.json"
    assert restore_lut_seed()["installed_count"] == 0
    shutil.rmtree(LUTManager.cloud_lut_dir())
    assert install_lut_seed_if_needed() is None
    assert not installed.exists()
    assert restore_lut_seed()["installed_count"] == 1


@pytest.mark.parametrize("channel,corrupt", [("team", False), ("community", True)])
def test_invalid_seed_writes_no_lut(monkeypatch, tmp_path, channel, corrupt):
    from api.lut_seed import install_lut_seed_if_needed
    seed = tmp_path / "seed.zip"
    make_seed(seed, channel=channel, corrupt=corrupt)
    monkeypatch.setenv("LUMINA_LUTS_SEED_PATH", str(seed))
    with pytest.raises((ValueError, sync.LutRegistryPackageError)):
        install_lut_seed_if_needed()
    assert not list(LUTManager.cloud_lut_dir().rglob("*.json"))


def test_reinstall_preserves_personal_file_and_previous_revision(tmp_path):
    original = _DEFAULT_LUT_BYTES
    first_package = _bundle_bytes(original)
    first = _entry(first_package)
    old = sync.install_lut_archive_bytes(first, first_package, source_url="bundled")
    old_path = LUTManager.cloud_lut_dir() / first["local_path"]
    new_bytes = original.replace(b"255", b"240")
    new_package = _bundle_bytes(new_bytes)
    new = _entry(new_package, revision_id="rev-2", content_hash=hashlib.sha256(new_bytes).hexdigest())
    newer = sync.install_lut_archive_bytes(new, new_package, source_url="bundled")
    assert old_path.read_bytes() == original
    assert newer["installed_path"] != old["installed_path"]
    assert sync._safe_index_installed_path(newer).read_bytes() == new_bytes
    old_path.write_bytes(b"personal edits")
    restored = sync.install_lut_archive_bytes(first, first_package, source_url="bundled")
    assert old_path.read_bytes() == b"personal edits"
    assert sync._safe_index_installed_path(restored).read_bytes() == original


def test_migrated_preset_lookup_requires_exact_historical_bytes(monkeypatch, tmp_path):
    from utils import lut_manager
    manifest = tmp_path / "migration.json"
    manifest.write_text(json.dumps({"luts": [{"name": "Brand - PLA - seed", "path": "Brand/PLA/seed.json",
                                             "sha256": hashlib.sha256(_DEFAULT_LUT_BYTES).hexdigest()}]}))
    monkeypatch.setattr(lut_manager, "_LEGACY_LUT_MIGRATION_PATH", manifest)
    target = LUTManager.cloud_lut_dir() / "Brand/PLA/seed.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(_DEFAULT_LUT_BYTES)
    assert LUTManager.get_lut_path("Brand - PLA - seed") == str(target.resolve())
    from api.routers.lut import list_luts, get_source_catalog
    assert list_luts().legacy_aliases == {"Brand - PLA - seed": "Cloud - Brand - PLA - seed"}
    assert get_source_catalog().legacy_aliases == {"Brand - PLA - seed": "Cloud - Brand - PLA - seed"}
    target.write_bytes(_DEFAULT_LUT_BYTES + b" ")
    assert LUTManager.get_lut_path("Brand - PLA - seed") is None
    assert LUTManager.migrated_preset_aliases() == {}


def test_migrated_names_follow_verified_bytes_at_a_different_installed_path(monkeypatch, tmp_path):
    from utils import lut_manager
    old_names = ["通用LUT[有色差]RYBW General for personal use", "Custom - Bambulab&PLA&RYBW&红-黄-蓝-白"]
    digest = hashlib.sha256(_DEFAULT_LUT_BYTES).hexdigest()
    manifest = tmp_path / "migration.json"
    manifest.write_text(json.dumps({"luts": [
        {"name": name, "path": f"Custom/legacy-{index}.json", "sha256": digest}
        for index, name in enumerate(old_names)
    ] + [{"name": "Unavailable legacy", "path": "Missing/old.json", "sha256": "0" * 64}]}))
    monkeypatch.setattr(lut_manager, "_LEGACY_LUT_MIGRATION_PATH", manifest)
    identity = {"lut_id": "lut_elegoo", "revision_id": "rev_elegoo", "channel": "official",
                "local_path": "Elegoo/Elegoo_pla_RYBW.json", "content_hash": digest}
    package = _bundle_bytes(package_extra=identity)
    record = sync.install_lut_archive_bytes(_entry(package, **identity), package, source_url="bundled")
    target = sync._safe_index_installed_path(record)
    LUTManager.invalidate_preset_cache()
    for name in old_names:
        assert LUTManager.get_lut_path(name) == str(target.resolve())
    aliases = LUTManager.migrated_preset_aliases()
    assert set(aliases) == set(old_names)
    assert len(set(aliases.values())) == 1
    assert LUTManager.get_lut_path("Unavailable legacy") is None
    assert LUTManager.get_lut_path("Bambu approximate name") is None
    target.write_bytes(_DEFAULT_LUT_BYTES + b" ")
    assert all(LUTManager.get_lut_path(name) is None for name in old_names)
    assert LUTManager.migrated_preset_aliases() == {}
