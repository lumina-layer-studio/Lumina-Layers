from __future__ import annotations

import asyncio
import io
import json
import shutil
import zipfile
from pathlib import Path

import msgpack
import numpy as np
import pytest
from fastapi import UploadFile

from api.project_resources import discard_project_resources, stage_project_resources
from api.session_store import SessionStore
from config import LUTMetadata, PaletteEntry
from core.material_lut_provider import load_materials
from core.projects import build_project_bytes, read_project
from core.projects.dependencies import pack_lut_source, unpack_lut_source
from core.projects.schema import AssetBlob, ProjectSnapshot, WorkflowDocument
from core.single_stage import export_saved_stage_a_material_archives
from utils.lut_manager import LUTManager


@pytest.mark.parametrize("count", [32, 1024, 1296, 2468, 2738])
def test_classic_lut_project_preserves_runtime_recipes_without_original_file(tmp_path, count):
    from core.pipeline.processing_ops.lut_loader import load_lut

    source = tmp_path / "classic.npy"
    rgb = np.random.default_rng(9).integers(0, 256, (count, 3), dtype=np.uint8)
    np.save(source, rgb, allow_pickle=False)
    _, _, metadata = LUTManager.load_lut_with_metadata(str(source))
    expected = load_lut(str(source), metadata.color_mode)
    data = pack_lut_source(str(source))
    source.unlink()

    restored = unpack_lut_source(data, tmp_path / "private")
    actual = load_lut(restored, metadata.color_mode)
    np.testing.assert_array_equal(actual["lut_rgb"], expected["lut_rgb"])
    np.testing.assert_array_equal(actual["ref_stacks"], expected["ref_stacks"])
    assert actual["layer_order"] == expected["layer_order"]


@pytest.mark.parametrize("direct_npz", [False, True])
def test_older_project_lut_without_recipes_reuses_classic_loader(tmp_path, direct_npz):
    from core.pipeline.processing_ops.lut_loader import load_lut

    source = tmp_path / "classic.npy"
    rgb = np.random.default_rng(9).integers(0, 256, (1024, 3), dtype=np.uint8)
    np.save(source, rgb, allow_pickle=False)
    _, _, metadata = LUTManager.load_lut_with_metadata(str(source))
    expected = load_lut(str(source), metadata.color_mode)
    npz = io.BytesIO()
    np.savez_compressed(npz, rgb=rgb, metadata_json=np.array(json.dumps(metadata.to_dict())))
    if direct_npz:
        data = npz.getvalue()
    else:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("source.json", '{"format":"lumina-lut-source","version":1}')
            z.writestr("lut.npz", npz.getvalue())
        data = archive.getvalue()
    source.unlink()

    restored = unpack_lut_source(data, tmp_path / "private")
    actual = load_lut(restored, metadata.color_mode)
    np.testing.assert_array_equal(actual["lut_rgb"], expected["lut_rgb"])
    np.testing.assert_array_equal(actual["ref_stacks"], expected["ref_stacks"])


def test_legacy_direct_npz_migrates_without_global_library(tmp_path):
    source = tmp_path / "old.npz"
    LUTManager.save_npz_with_metadata(str(source), np.array([[1, 2, 3]], dtype=np.uint8), np.array([[0, 1, 0, 1, 0]]), LUTMetadata())
    data = source.read_bytes()
    source.unlink()
    path = unpack_lut_source(data, tmp_path / "private")
    rgb, stacks, _ = LUTManager.load_lut_with_metadata(path)
    np.testing.assert_array_equal(rgb, [[1, 2, 3]])
    np.testing.assert_array_equal(stacks, [[0, 1, 0, 1, 0]])


def test_project_npz_rejects_small_archive_declaring_huge_array(tmp_path):
    from core.projects.dependencies import validate_npz_budget
    header = io.BytesIO()
    np.lib.format.write_array_header_1_0(header, {"descr": "<f8", "fortran_order": False, "shape": (2**40,)})
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("rgb.npy", header.getvalue())
    with pytest.raises(ValueError, match="dimensions"):
        validate_npz_budget(archive.getvalue())


def test_project_lut_retains_recipes_and_material_identity_after_source_deleted(tmp_path: Path) -> None:
    source = tmp_path / "source.npz"
    rgb = np.array([[20, 120, 220], [250, 240, 230]], dtype=np.uint8)
    recipes = np.array([[0, 1, 0, 1, 0], [1, 1, 1, 1, 1]], dtype=np.int32)
    metadata = LUTMetadata(
        palette=[PaletteEntry(color="青", material="PETG"), PaletteEntry(color="暖白", material="PETG")],
        base_channel_idx=1, layer_order="Bottom2Top", color_mode="Merged", max_color_layers=5,
    )
    LUTManager.save_npz_with_metadata(str(source), rgb, recipes, metadata)
    resource = pack_lut_source(str(source))
    snapshot = ProjectSnapshot.new(name="Portable LUT", workflow_kinds=("converter",), documents=(
        WorkflowDocument(document_id="converter.main", kind="converter", schema_version=2, payload={}, resource_refs=("lut",)),
    ), assets=(AssetBlob(asset_id="lut", data=resource, filename="source.lut.zip", media_type="application/zip"),))
    package = build_project_bytes(snapshot)
    source.unlink()
    restored_path = unpack_lut_source(read_project(package).assets["lut"].data, tmp_path / "empty-computer")
    actual_rgb, actual_recipes, actual_metadata = LUTManager.load_lut_with_metadata(restored_path)
    np.testing.assert_array_equal(actual_rgb, rgb)
    np.testing.assert_array_equal(actual_recipes, recipes)
    assert actual_metadata.base_channel_idx == 1
    assert actual_metadata.layer_order == "Bottom2Top"
    assert [(item.color, item.material) for item in actual_metadata.palette] == [("青", "PETG"), ("暖白", "PETG")]


def test_native_snapshot_rebinds_model_and_exact_database_without_original_paths(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    db = original / "db.json"
    db.write_text(json.dumps({"palette": [{"color": "White", "material": "PLA"}], "layer_height_mm": 0.08, "max_color_layers": 5, "entries": [{"rgb": [255, 255, 255], "recipe": [0] * 5}]}))
    model = original / "model.msgpack"
    model.write_bytes(msgpack.packb({
        "version": 2, "channel_keys": ["White|PLA"], "scope": {"vendor": "Portable", "material_type": "PLA"}, "selected_db_paths": [str(db)],
        "modes": [{"color_layers": 5, "layer_height_mm": 0.08, "num_candidates": 1, "candidate_recipes": bytes([0] * 5), "pred_lab": np.array([[100, 0, 0]], dtype="<f4").tobytes()}],
    }, use_bin_type=True))
    package = pack_lut_source(str(model))
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert all(str(original).encode() not in archive.read(name) for name in archive.namelist())
    shutil.rmtree(original)
    restored_path = unpack_lut_source(package, tmp_path / "restored")
    _, _, metadata = LUTManager.load_lut_with_metadata(restored_path)
    assert Path(metadata.extensions["native_model_package_path"]).is_file()
    assert all(Path(name).is_file() for name in metadata.extensions["native_db_paths"])
    exact = LUTManager.load_native_bundle_exact_lookup(metadata, color_layers=5, layer_height_mm=0.08, layer_order="Top2Bottom")
    assert exact is not None
    np.testing.assert_array_equal(exact[1], [[0] * 5])


def test_material_resources_use_session_directory_and_are_cleaned_with_session(tmp_path: Path) -> None:
    library = tmp_path / "source-library"
    material = library / "Brand" / "cyan"
    material.mkdir(parents=True)
    (material / "material.json").write_text(json.dumps({
        "brand": "Brand", "material_name": "Cyan", "material_summary": {"estimated_rgb": [20, 120, 220]}, "stage_a_params_file": "stage_A_parameters.json",
    }))
    (material / "stage_A_parameters.json").write_text(json.dumps({"parameters": {
        "channels": [{"color_name": "Cyan", "E": [0.1, 0.2, 0.3], "k": [1.0, 1.1, 1.2]}],
        "substrates": [{"substrate_id": "white", "C0": [1.0, 1.0, 1.0]}],
    }}))
    exported = export_saved_stage_a_material_archives(directory_names=["Brand/cyan"], materials_dir=str(library), output_path=str(tmp_path / "materials.zip"))
    data = Path(exported.archive_path).read_bytes()
    shutil.rmtree(library)
    resources = asyncio.run(stage_project_resources(None, UploadFile(file=io.BytesIO(data), filename="materials.zip"), ["Brand/cyan"]))
    assert resources is not None
    try:
        actual = load_materials(["Brand/cyan"], materials_dir=resources.materials_dir, use_cache=False)
        assert actual[0].name == "Cyan"
        np.testing.assert_allclose(actual[0].E, [0.1, 0.2, 0.3])
        store = SessionStore()
        sid = store.create()
        store.register_temp_file(sid, resources.root)
        store.close(sid)
        assert not Path(resources.root).exists()
        assert not library.exists()
    finally:
        discard_project_resources(resources)


@pytest.mark.parametrize("name", ["../escape", "/outside", "dependencies/../../escape", "dependencies\\outside"])
def test_lut_snapshot_rejects_external_paths(tmp_path: Path, name: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, b"no")
    with pytest.raises(ValueError):
        unpack_lut_source(buffer.getvalue(), tmp_path / "import")
    assert not (tmp_path / "escape").exists()
