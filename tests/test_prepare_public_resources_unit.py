import hashlib
import json

import pytest

from scripts.prepare_public_resources import prepare_resources


def release(tmp_path):
    source = tmp_path / "release"
    source.mkdir()
    artifacts = {}
    for kind in ("materials", "luts"):
        payload = f"verified {kind} fixture".encode()
        filename = f"lumina-{kind}-seed.zip"
        (source / filename).write_bytes(payload)
        artifacts[kind] = {"path": filename, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                           "download_url": f"https://github.com/lumina-layer-studio/Lumina-materials/releases/download/vtest.1/{filename}"}
    lock = source / "resource-release.json"
    lock.write_text(json.dumps({"kind": "lumina_resource_release", "schema_version": 1,
                               "dataset_version": "test.1", "artifacts": artifacts}))
    return source, lock


def test_offline_pair_is_staged_to_runtime_paths(tmp_path):
    source, lock = release(tmp_path)
    output = tmp_path / "resources"
    prepare_resources(lock, output, source_dir=source)
    for kind in ("materials", "luts"):
        assert (output / kind / f"lumina-{kind}-seed.zip").read_bytes() == (source / f"lumina-{kind}-seed.zip").read_bytes()
    assert json.loads((output / "resource-release.json").read_text())["dataset_version"] == "test.1"


def test_bad_pair_never_replaces_existing_staged_resources(tmp_path):
    source, lock = release(tmp_path)
    output = tmp_path / "resources"
    prepare_resources(lock, output, source_dir=source)
    previous = (output / "materials/lumina-materials-seed.zip").read_bytes()
    (source / "lumina-luts-seed.zip").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="size|sha256"):
        prepare_resources(lock, output, source_dir=source)
    assert (output / "materials/lumina-materials-seed.zip").read_bytes() == previous


def test_manifest_cannot_escape_stage_directory(tmp_path):
    source, lock = release(tmp_path)
    payload = json.loads(lock.read_text())
    payload["artifacts"]["luts"]["path"] = "../outside.zip"
    lock.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="filename"):
        prepare_resources(lock, tmp_path / "output", source_dir=source)
