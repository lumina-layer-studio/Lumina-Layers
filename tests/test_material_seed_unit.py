"""Material seed bootstrap tests."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
import shutil
from pathlib import Path

import pytest

from api.material_seed import install_material_seed_if_needed
from core.single_stage import material_files, material_library, material_package
from core.single_stage.material_package import (
    _verify_material_bundle_package,
)


def _write_seed_archive(zip_path: Path) -> str:
    material_payload = json.dumps(
        {
            "brand": "SeedBrand",
            "material_name": "Seed PLA",
            "stage_a_params_file": "stage_A_parameters.json",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    stage_a_payload = json.dumps(
        {
            "parameters": {
                "channels": [
                    {
                        "color_name": "Seed PLA",
                        "E": [0.1, 0.2, 0.3],
                        "k": [1.0, 1.1, 1.2],
                    }
                ],
                "substrates": [
                    {
                        "substrate_id": "white",
                        "C0": [1.0, 1.0, 1.0],
                    }
                ],
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    material_hash = hashlib.sha256(material_payload).hexdigest()
    stage_a_hash = hashlib.sha256(stage_a_payload).hexdigest()
    content_hash = hashlib.sha256(
        f"material.json:{material_hash}\nstage_A_parameters.json:{stage_a_hash}".encode(
            "utf-8"
        )
    ).hexdigest()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("materials/SeedBrand/seed-pla/material.json", material_payload)
        archive.writestr(
            "materials/SeedBrand/seed-pla/stage_A_parameters.json",
            stage_a_payload,
        )
        archive.writestr(
            "lumina_material_bundle.json",
            json.dumps(
                {
                    "kind": "lumina_material_bundle",
                    "schema_version": "2.0",
                    "packages": [
                        {
                            "material_id": "mat_seed",
                            "revision_id": "rev_seed",
                            "content_hash": f"sha256:{content_hash}",
                            "channel": "official",
                            "visibility": "official",
                            "local_directory": "SeedBrand/seed-pla",
                            "display": {
                                "brand": "SeedBrand",
                                "material_name": "Seed PLA",
                            },
                            "files": [
                                {
                                    "path": "materials/SeedBrand/seed-pla/material.json",
                                    "role": "material_archive",
                                    "sha256": material_hash,
                                    "bytes": len(material_payload),
                                    "required": True,
                                },
                                {
                                    "path": "materials/SeedBrand/seed-pla/stage_A_parameters.json",
                                    "role": "stage_a_parameters",
                                    "sha256": stage_a_hash,
                                    "bytes": len(stage_a_payload),
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
    return hashlib.sha256(zip_path.read_bytes()).hexdigest()


def test_nested_collection_keeps_colliding_names_separate_and_installs_only_selection(tmp_path, monkeypatch):
    from api.material_seed import material_seed_catalog, install_material_seed_revision
    original = tmp_path / "original.zip"
    _write_seed_archive(original)
    entries = []
    collection = tmp_path / "collection.zip"
    with zipfile.ZipFile(collection, "w") as outer:
        for suffix in ("one", "two"):
            buffer = io.BytesIO()
            with zipfile.ZipFile(original) as source, zipfile.ZipFile(buffer, "w") as target:
                manifest = json.loads(source.read("lumina_material_bundle.json"))
                package = manifest["packages"][0]
                package["material_id"] = "mat_" + suffix
                for name in source.namelist():
                    target.writestr(name, json.dumps(manifest) if name == "lumina_material_bundle.json" else source.read(name))
            payload = buffer.getvalue()
            path = "packages/" + suffix + ".zip"
            outer.writestr(path, payload)
            entries.append({**package, "path": path, "package_bytes": len(payload),
                            "package_sha256": hashlib.sha256(payload).hexdigest()})
        outer.writestr("DATA-LICENSE.md", "Retain each resource's original license.")
        outer.writestr("lumina_material_seed.json", json.dumps({"kind": "lumina_material_seed",
            "schema_version": "1.0", "dataset_version": "nested.1", "packages": entries}))
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(collection))
    root = tmp_path / "library"
    catalog = material_seed_catalog(materials_dir=str(root))
    assert catalog["dataset_version"] == "nested.1"
    assert [r["resource_id"] for r in catalog["items"]] == ["mat_one", "mat_two"]
    assert not root.exists()
    assert install_material_seed_revision("mat_two", "rev_seed", materials_dir=str(root)) == {"installed_count": 1}
    assert len(list(root.rglob("material.json"))) == 1
    assert [r["installed"] for r in material_seed_catalog(materials_dir=str(root))["items"]] == [False, True]
    assert install_material_seed_revision("mat_one", "rev_seed", materials_dir=str(root)) == {"installed_count": 1}
    assert len(list(root.rglob("material.json"))) == 2


def test_material_seed_installs_when_runtime_materials_are_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "lumina-materials-seed.zip"
    seed_sha256 = _write_seed_archive(seed_path)
    materials_root = tmp_path / "materials"
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed_path))
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_SHA256", seed_sha256)

    result = install_material_seed_if_needed(materials_dir=str(materials_root))

    assert result is not None
    assert result["installed_count"] == 1
    assert (materials_root / "SeedBrand" / "seed-pla" / "material.json").is_file()
    assert (materials_root / "_sync" / "index.json").is_file()


def test_material_seed_does_not_overwrite_existing_runtime_materials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "lumina-materials-seed.zip"
    _write_seed_archive(seed_path)
    materials_root = tmp_path / "materials"
    existing_material = materials_root / "UserBrand" / "local-pla" / "material.json"
    existing_material.parent.mkdir(parents=True)
    existing_material.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed_path))

    result = install_material_seed_if_needed(materials_dir=str(materials_root))

    assert result is None
    assert existing_material.read_text(encoding="utf-8") == "{}"
    assert not (materials_root / "SeedBrand" / "seed-pla").exists()


def test_material_seed_rejects_sha256_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "lumina-materials-seed.zip"
    _write_seed_archive(seed_path)
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed_path))
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_SHA256", "0" * 64)

    with pytest.raises(ValueError, match="sha256 mismatch"):
        install_material_seed_if_needed(materials_dir=str(tmp_path / "materials"))


def test_seed_does_not_return_after_user_deletes_library(monkeypatch, tmp_path):
    seed = tmp_path / "seed.zip"
    _write_seed_archive(seed)
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed))
    root = tmp_path / "materials"
    assert install_material_seed_if_needed(materials_dir=str(root))["installed_count"] == 1
    shutil.rmtree(root / "SeedBrand")
    assert install_material_seed_if_needed(materials_dir=str(root)) is None
    assert not (root / "SeedBrand").exists()


def test_existing_library_is_remembered_after_user_deletes_it(monkeypatch, tmp_path):
    seed = tmp_path / "seed.zip"
    _write_seed_archive(seed)
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed))
    root = tmp_path / "materials"
    material = root / "personal" / "material.json"
    material.parent.mkdir(parents=True)
    material.write_text("{}", encoding="utf-8")
    assert install_material_seed_if_needed(materials_dir=str(root)) is None
    shutil.rmtree(material.parent)
    assert install_material_seed_if_needed(materials_dir=str(root)) is None


def test_explicit_restore_is_idempotent_and_keeps_personal_changes(monkeypatch, tmp_path):
    from api.material_seed import restore_material_seed
    seed = tmp_path / "seed.zip"
    _write_seed_archive(seed)
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed))
    root = tmp_path / "materials"
    install_material_seed_if_needed(materials_dir=str(root))
    assert restore_material_seed(materials_dir=str(root))["installed_count"] == 0
    personal = root / "SeedBrand/seed-pla/material.json"
    payload = json.loads(personal.read_text())
    payload["material_name"] = "My modified filament"
    personal.write_text(json.dumps(payload), encoding="utf-8")
    before = personal.read_bytes()
    restore_material_seed(materials_dir=str(root))
    assert personal.read_bytes() == before


def test_failed_seed_can_retry_after_correcting_hash(monkeypatch, tmp_path):
    seed = tmp_path / "seed.zip"
    expected = _write_seed_archive(seed)
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed))
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_SHA256", "0" * 64)
    root = tmp_path / "materials"
    with pytest.raises(ValueError):
        install_material_seed_if_needed(materials_dir=str(root))
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_SHA256", expected)
    assert install_material_seed_if_needed(materials_dir=str(root))["installed_count"] == 1


def test_material_bundle_accepts_resolved_directory_alias(tmp_path: Path) -> None:
    """A directory alias and its canonical path must identify the same bundle."""
    seed_path = tmp_path / "seed.zip"
    _write_seed_archive(seed_path)
    extracted = tmp_path / "canonical"
    with zipfile.ZipFile(seed_path) as archive:
        archive.extractall(extracted)
        manifest = json.loads(archive.read("lumina_material_bundle.json"))
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(extracted, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink creation is unavailable")

    _verify_material_bundle_package(
        extracted_root=alias, package=manifest["packages"][0]
    )


def test_material_bundle_still_rejects_stage_file_outside_root(tmp_path: Path) -> None:
    """Canonicalization must not permit a parameter file outside its material."""
    seed_path = tmp_path / "seed.zip"
    _write_seed_archive(seed_path)
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(seed_path) as archive:
        archive.extractall(extracted)
        manifest = json.loads(archive.read("lumina_material_bundle.json"))
    stage_file = extracted / "materials/SeedBrand/seed-pla/stage_A_parameters.json"
    outside = tmp_path / "outside.json"
    stage_file.rename(outside)
    try:
        stage_file.symlink_to(outside)
    except OSError:
        pytest.skip("File symlink creation is unavailable")

    with pytest.raises(ValueError, match="inside the material directory"):
        _verify_material_bundle_package(
            extracted_root=extracted, package=manifest["packages"][0]
        )


@pytest.mark.parametrize("alias_library", [False, True])
def test_material_seed_full_install_and_export_with_temp_directory_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, alias_library: bool,
) -> None:
    """Exercise seed import, sync index, export, and reimport through an alias."""
    canonical = tmp_path / "long-directory-name"
    canonical.mkdir()
    alias = tmp_path / "SHORT~1"
    try:
        alias.symlink_to(canonical, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink creation is unavailable")
    monkeypatch.setattr(material_files, "TEMP_DIR", str(alias))
    seed_path = tmp_path / "seed.zip"
    seed_sha256 = _write_seed_archive(seed_path)
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed_path))
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_SHA256", seed_sha256)
    library_root = (alias if alias_library else tmp_path) / "library"

    result = install_material_seed_if_needed(materials_dir=str(library_root))

    assert result is not None
    assert result["installed_count"] == 1
    material_dir = library_root / "SeedBrand" / "seed-pla"
    with zipfile.ZipFile(seed_path) as archive:
        for filename in ("material.json", "stage_A_parameters.json"):
            assert (material_dir / filename).read_bytes() == archive.read(
                f"materials/SeedBrand/seed-pla/{filename}"
            )
    sync_index = json.loads((library_root / "_sync" / "index.json").read_text(encoding="utf-8"))
    assert sync_index["installed"]["mat_seed"]["revision_id"] == "rev_seed"
    assert install_material_seed_if_needed(materials_dir=str(library_root)) is None
    exported = material_library.export_saved_stage_a_material_archives(
        directory_names=["SeedBrand/seed-pla"], materials_dir=str(library_root),
    )
    reimported_root = tmp_path / "reimported"
    imported = material_library.import_saved_stage_a_material_archives(
        archive_path=exported.archive_path, materials_dir=str(reimported_root),
    )
    assert len(imported.imported_materials) == 1
    assert (reimported_root / "SeedBrand/seed-pla/material.json").read_bytes() == (
        material_dir / "material.json"
    ).read_bytes()
    assert not list(canonical.glob("material_archive_import_*"))


@pytest.mark.parametrize("escape_kind", ["sibling", "file_symlink", "directory_symlink"])
def test_material_bundle_copy_rejects_files_outside_canonical_material(
    tmp_path: Path, escape_kind: str,
) -> None:
    """The copy boundary must reject lexical and resolved filesystem escapes."""
    manifest_root = tmp_path / "manifest"
    material_dir = manifest_root / "materials" / "brand" / "material"
    material_dir.mkdir(parents=True)
    outside = manifest_root / "outside"
    outside.mkdir()
    (outside / "secret.json").write_bytes(b"must not be copied")
    if escape_kind == "sibling":
        relative_path = "outside/secret.json"
    else:
        link = material_dir / "linked"
        try:
            link.symlink_to(outside if escape_kind == "directory_symlink" else outside / "secret.json",
                            target_is_directory=escape_kind == "directory_symlink")
        except OSError:
            pytest.skip("Symlink creation is unavailable")
        relative_path = "materials/brand/material/linked"
        if escape_kind == "directory_symlink":
            relative_path += "/secret.json"
    destination = tmp_path / "destination"
    with pytest.raises(ValueError, match="outside material directory"):
        material_package._copy_material_bundle_package_files(
            manifest_root=manifest_root, staged_material_dir=material_dir,
            destination_dir=destination, package={"files": [{"path": relative_path}]},
        )
    assert not any(path.is_file() for path in destination.rglob("*"))
