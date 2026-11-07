"""Unit test for the batch worker output contract.
批量 worker 输出契约的单元测试。

This test exercises the new ``worker_batch_convert_item`` contract
defined by ``batch-mode-merged-3mf`` task 7. It calls the worker once
with a tiny real input (one small PNG plus a mocked
``core.converter.convert_image_to_3d`` that emits a real Bambu 3MF and a
real GLB), then asserts:

1. The returned dict contains exactly the 5 expected keys.
2. ``threemf_path``, ``preview_glb_path``, ``metadata_sidecar_path`` all
   point to distinct files whose basenames start with the supplied
   ``artifact_prefix``.
3. The sidecar JSON supplies the merge writer's ``MaterialSlot`` values,
   ``slots`` has length >= 1 and every material identity 4-tuple
   (``slot_id`` / ``slot_name`` / ``preview_color`` / ``material_id``)
   is non-empty.
4. ``xy_bbox_mm`` in the returned dict matches the sidecar's
   ``xy_bbox_mm``.
5. The returned dict does not carry a ``trimesh.Scene`` instance or
   raw bytes payload (the worker boundary stays at "file paths +
   scalars" only).

**Validates: Requirements 1.3, 6.1, 6.2**
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import trimesh
from PIL import Image

from api.workers.converter_workers import (
    worker_batch_convert_item,
)
from config import MODELS_DIR, OUTPUT_DIR, TEMP_DIR
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata
from utils.merged_bambu_3mf_writer import MaterialSlot


# ---------------------------------------------------------------------------
# Fixtures: tiny real artifacts the mocked convert_image_to_3d will return
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("mode", ["vector", "high-fidelity"])
@pytest.mark.parametrize("source", ["lut", "material_archive"])
def test_batch_worker_forwards_coating(enabled, mode, source):
    with patch("core.converter.convert_image_to_3d", return_value=(None, None, None, "test", None)) as convert:
        worker_batch_convert_item(
            image_path="test.svg", lut_path="test.npy", target_width_mm=60,
            spacer_thick=1.2, structure_mode="Single-sided", color_mode="4-Color (RYBW)",
            modeling_mode_value=mode, color_layers=5, layer_height_mm=0.08,
            quantize_colors=48, enable_cleanup=True, artifact_prefix="test-",
            material_source=source, enable_coating=enabled, coating_height_mm=0.12,
            coating_material={"source": "palette", "key": "White"},
            svg_hole_compensation_enabled=mode == "vector",
            svg_hole_max_area_mm2=0.75, svg_hole_max_width_mm=0.21,
        )
    assert convert.call_args.kwargs["enable_coating"] is enabled
    assert convert.call_args.kwargs["coating_height_mm"] == 0.12
    assert convert.call_args.kwargs["coating_material"] == {"source": "palette", "key": "White"}
    assert convert.call_args.kwargs["svg_hole_compensation_enabled"] is (mode == "vector")
    assert convert.call_args.kwargs["svg_hole_max_area_mm2"] == 0.75
    assert convert.call_args.kwargs["svg_hole_max_width_mm"] == 0.21


@pytest.mark.parametrize("mode", ["vector", "high-fidelity"])
@pytest.mark.parametrize("enabled", [True, False])
def test_two_svg_batch_exports_keep_coating(tmp_path, monkeypatch, mode, enabled):
    """Verify real conversion and merging preserve each item's coating mesh."""
    import xml.etree.ElementTree as ET
    import zipfile

    import config
    from core.pipeline import s09_export_3mf, s11_glb_preview
    from utils.merged_bambu_3mf_writer import (
        MaterialSlot, MergedBambu3MFWriter, MergedItem,
    )

    for name in ("MODELS_DIR", "OUTPUT_DIR", "TEMP_DIR"):
        monkeypatch.setattr(config, name, str(tmp_path))
    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(s11_glb_preview, "OUTPUT_DIR", str(tmp_path))
    lut_path = tmp_path / "colors.npy"
    np.save(lut_path, np.tile(np.array([[255, 255, 255]], dtype=np.uint8), (1024, 1)))
    items = []
    for index in range(2):
        svg_path = tmp_path / f"shape-{index}.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            '<path fill="white" fill-rule="evenodd" '
            'd="M0 0H10V10H0Z M3 3V7H7V3Z"/></svg>', encoding="utf-8",
        )
        result = worker_batch_convert_item(
            str(svg_path), str(lut_path), 10, 1.2, "Single-sided",
            "4-Color (RYBW)", mode, 5, 0.08, 4, False, "coating-test-",
            enable_coating=enabled, coating_height_mm=0.12,
        )
        assert result["threemf_path"], result["status_msg"]
        sidecar = json.loads(Path(result["metadata_sidecar_path"]).read_text(encoding="utf-8"))
        slots = tuple(MaterialSlot(**slot) for slot in sidecar["slots"])
        assert any(slot.slot_name == "Coating" for slot in slots) is enabled
        assert any(slot.slot_name == "White" for slot in slots)
        items.append(MergedItem(
            source_filename=svg_path.name, source_3mf_path=Path(result["threemf_path"]),
            slots=slots, tx_mm=40 + index * 15, ty_mm=40,
        ))
    merged = tmp_path / "merged.3mf"
    MergedBambu3MFWriter().write(items, merged, plate_width_mm=256, plate_depth_mm=256)
    with zipfile.ZipFile(merged) as archive:
        model_objects = {}
        for name in archive.namelist():
            if name.endswith(".model"):
                root = ET.fromstring(archive.read(name))
                for mesh_object in root.findall(".//{*}object"):
                    if mesh_object.find("{*}mesh") is not None:
                        model_objects[mesh_object.get("id")] = mesh_object
        settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
        objects = settings.findall("object")
        assert len(objects) == 2
        for obj in objects:
            coating_parts = [part for part in obj.findall("part") if any(
                meta.get("key") == "name" and meta.get("value") == "Coating"
                for meta in part.findall("metadata")
            )]
            assert len(coating_parts) == int(enabled)
            for part in coating_parts:
                assert any(meta.get("key") == "extruder" and int(meta.get("value")) > 0
                           for meta in part.findall("metadata"))
                mesh_object = model_objects[part.get("id")]
                z_values = [float(vertex.get("z")) for vertex in
                            mesh_object.findall(".//{*}vertex")]
                # Coating uses the existing single-image layer quantization.
                expected_height = max(1, round(0.12 / config.PrinterConfig.LAYER_HEIGHT)) * config.PrinterConfig.LAYER_HEIGHT
                assert max(z_values) - min(z_values) == pytest.approx(expected_height)


def _prepare_two_material_sources(tmp_path, monkeypatch, mode, kinds):
    import config
    from config import LUTMetadata, PaletteEntry
    from core import material_lut_provider, material_lut_synthesis
    from core.pipeline import s09_export_3mf, s11_glb_preview
    from utils.lut_manager import LUTManager

    for name in ("MODELS_DIR", "OUTPUT_DIR", "TEMP_DIR"):
        monkeypatch.setattr(config, name, str(tmp_path))
    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(s11_glb_preview, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("LUMINA_RUNTIME_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(material_lut_provider, "MATERIALS_DIR", str(tmp_path))
    monkeypatch.setattr(material_lut_synthesis, "MATERIALS_DIR", str(tmp_path))

    for name, kind, level in zip(("White", "Black"), kinds, (1.0, 0.01)):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "material.json").write_text(json.dumps({
            "material_name": name, "material_type": kind,
        }), encoding="utf-8")
        (directory / "stage_A_parameters.json").write_text(json.dumps({
            "parameters": {
                "channels": [{"E": [level] * 3, "k": [1.0] * 3}],
                "substrates": [{"substrate_id": "white", "C0": [1.0] * 3}],
            },
        }), encoding="utf-8")

    lut_path = tmp_path / "colors.npz"
    LUTManager.save_npz_with_metadata(
        str(lut_path), np.array([[255, 255, 255]], dtype=np.uint8),
        np.zeros((1, 5), dtype=np.int32), LUTMetadata(palette=[
            PaletteEntry(color=name, material=kind)
            for name, kind in zip(("White", "Black"), kinds)
        ]),
    )
    if mode == "vector":
        image_path = tmp_path / "source.svg"
        image_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="5" height="5">'
            '<rect width="5" height="5" fill="white"/></svg>', encoding="utf-8",
        )
    else:
        image_path = tmp_path / "source.png"
        Image.new("RGB", (5, 5), "white").save(image_path)
    return image_path, lut_path


@pytest.mark.parametrize("source", ["lut", "material_archive"])
@pytest.mark.parametrize("mode", ["vector", "high-fidelity"])
def test_x2d_single_generation_uses_preflight_identity_for_raster_and_svg(tmp_path, monkeypatch, source, mode):
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile
    from api.workers.converter_workers import worker_generate_model
    from config import ModelingMode
    from core.export_material_selection import require_export_material_selection

    image, lut = _prepare_two_material_sources(tmp_path, monkeypatch, mode, ("PETG", "PETG"))
    params = dict(printer_id="bambu-lab-x2d", slicer="BambuStudio", nozzle_size="0.4",
                  device_profile_id="BambuStudio:bbl:bambu-lab-x2d:0.4",
                  build_plate_id="textured-pei-plate", enable_coating=True,
                  external_spool_material="Coating", material_source=source,
                  selected_materials=["White", "Black"] if source == "material_archive" else None)
    selection = require_export_material_selection({**params, "lut_path": str(lut)})
    names = [slot["name"] for slot in selection["materials"]]
    params.update(target_width_mm=5, spacer_thick=1.2, structure_mode="Single-sided",
                  color_mode="4-Color (RYBW)", add_loop=False, loop_width=1, loop_length=1,
                  loop_hole=1, loop_pos=None, modeling_mode=ModelingMode(mode),
                  color_layers=5, layer_height_mm=0.08)
    output = worker_generate_model(str(image), str(lut), params)
    assert output["threemf_path"], output["status_msg"]
    with ZipFile(output["threemf_path"]) as package:
        root = ET.fromstring(package.read("Metadata/model_settings.config"))
        mapping = root.find("plate/metadata[@key='filament_maps']").get("value").split()
        assert len(mapping) == len(names)
        assert mapping.count("2") == 1
        coating = next(part for part in root.findall(".//part")
                       if part.find("metadata[@key='name']").get("value") == "Coating")
        coating_slot = int(coating.find("metadata[@key='extruder']").get("value")) - 1
        assert mapping[coating_slot] == "2"


@pytest.mark.parametrize("source", ["lut", "material_archive"])
@pytest.mark.parametrize("mode", ["vector", "high-fidelity"])
@pytest.mark.parametrize(("kinds", "expected"), [
    (("PLA", "PLA"), "PLA"),
    (("PETG", "PETG"), "PETG"),
    (("PETG", "PLA"), "PLA"),
])
def test_automatic_coating_type_survives_real_export(tmp_path, monkeypatch, source, mode, kinds, expected):
    from core.export_material_selection import require_export_material_selection
    import zipfile

    image_path, lut_path = _prepare_two_material_sources(tmp_path, monkeypatch, mode, kinds)
    selection = require_export_material_selection(
        {"enable_coating": True}, source_context={
            "material_source": source, "selected_materials": ["White", "Black"],
            "lut_path": str(lut_path),
        },
    )
    assert next(item for item in selection["materials"] if item["name"] == "Coating")["material_type"] == expected
    result = worker_batch_convert_item(
        str(image_path), str(lut_path), 5, 1.2, "Single-sided", "4-Color (RYBW)",
        mode, 5, 0.08, 4, False, "automatic-coating-", material_source=source,
        selected_materials=["White", "Black"] if source == "material_archive" else None,
        enable_coating=True, coating_height_mm=0.08,
    )
    assert result["threemf_path"], result["status_msg"]
    sidecar = json.loads(Path(result["metadata_sidecar_path"]).read_text(encoding="utf-8"))
    coating = next(slot for slot in sidecar["slots"] if slot["slot_name"] == "Coating")
    with zipfile.ZipFile(result["threemf_path"]) as archive:
        settings = json.loads(archive.read("Metadata/project_settings.config"))
    assert settings["filament_type"][int(coating["slot_id"])] == expected


def _make_test_image(tmp_dir: str) -> Path:
    """Write a source PNG whose size deliberately differs from the export."""
    img = Image.new("RGB", (40, 30), (200, 100, 50))
    fd, path = tempfile.mkstemp(prefix="batch_worker_unit_image_", suffix=".png", dir=tmp_dir)
    os.close(fd)
    img.save(path)
    return Path(path)


def _make_real_bambu_3mf(out_path: Path) -> None:
    """Write a small real Bambu 3MF with two named slots.

    用 trimesh + ``export_scene_with_bambu_metadata`` 写出一个最小但真实的
    Bambu 3MF；该文件的 ``Metadata/model_settings.config`` /
    ``Metadata/project_settings.config`` 可被 worker 的
    ``_batch_extract_slots_from_3mf`` 解出 2 个 slot。
    """
    scene = trimesh.Scene()

    box1 = trimesh.creation.box(extents=[10.0, 10.0, 2.0])
    box1.metadata["bambu_material_name"] = "Bambu PLA Black"
    scene.add_geometry(box1, geom_name="Bambu PLA Black")

    box2 = trimesh.creation.box(extents=[8.0, 8.0, 2.0])
    box2.apply_translation([12.0, 0.0, 0.0])
    box2.metadata["bambu_material_name"] = "Bambu PLA White"
    scene.add_geometry(box2, geom_name="Bambu PLA White")

    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=str(out_path),
        slot_names=["Bambu PLA Black", "Bambu PLA White"],
        preview_colors={
            "Bambu PLA Black": (16, 16, 16, 255),
            "Bambu PLA White": (240, 240, 240, 255),
        },
        settings={},
        color_mode="4-Color",
    )


def _make_real_glb(out_path: Path) -> None:
    """Write a small real GLB so the worker can rename it as preview."""
    box = trimesh.creation.box(extents=[10.0, 10.0, 2.0])
    scene = trimesh.Scene()
    scene.add_geometry(box, geom_name="preview")
    scene.export(str(out_path))


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.fixture
def batch_worker_artifacts(tmp_path):
    """Create source 3MF / GLB / image and yield the worker result.

    The worker moves the source 3MF / GLB into ``TEMP_DIR`` under the
    prefixed name; this fixture tracks every path produced so cleanup
    runs even on assertion failure.

    在 fixture teardown 中清理 worker 输出 + 任何残留的源文件，避免
    污染 ``TEMP_DIR`` / ``MODELS_DIR`` / ``OUTPUT_DIR``。
    """
    artifact_prefix = "batch-test1234-"

    image_path = _make_test_image(str(tmp_path))

    fd, threemf_path = tempfile.mkstemp(
        prefix="batch_worker_unit_pre_", suffix=".3mf", dir=MODELS_DIR
    )
    os.close(fd)
    _make_real_bambu_3mf(Path(threemf_path))

    fd, glb_path = tempfile.mkstemp(
        prefix="batch_worker_unit_pre_", suffix=".glb", dir=OUTPUT_DIR
    )
    os.close(fd)
    _make_real_glb(Path(glb_path))

    fake_return = (
        threemf_path,
        glb_path,
        np.zeros((1, 1, 4), dtype=np.uint8),
        "OK",
        None,
    )

    result: dict | None = None
    try:
        with patch(
            "core.converter.convert_image_to_3d",
            return_value=fake_return,
        ) as convert_mock:
            result = worker_batch_convert_item(
                image_path=str(image_path),
                lut_path="dummy_lut.npy",
                target_width_mm=80.0,
                spacer_thick=1.2,
                structure_mode="Single-sided",
                color_mode="4-Color (RYBW)",
                modeling_mode_value="high-fidelity",
                color_layers=5,
                layer_height_mm=0.08,
                quantize_colors=64,
                enable_cleanup=True,
                artifact_prefix=artifact_prefix,
                printer_id="bambu-p1s",
                slicer="OrcaSlicer",
                nozzle_size="0.2",
                enable_base_layer_height_modifier=False,
                enable_wipe_tower_auto_placement=False,
                backing_infill_density_percent=25,
            )
            forwarded = convert_mock.call_args.kwargs
            assert forwarded["printer_id"] == "bambu-p1s"
            assert forwarded["slicer"] == "OrcaSlicer"
            assert forwarded["nozzle_size"] == "0.2"
            assert forwarded["enable_base_layer_height_modifier"] is False
            assert forwarded["enable_wipe_tower_auto_placement"] is False
            assert forwarded["backing_infill_density_percent"] == 25
            assert forwarded["enable_coating"] is False
            assert forwarded["coating_height_mm"] == 0.08

        yield artifact_prefix, image_path, result
    finally:
        # Best-effort cleanup. The worker should have moved the source
        # 3MF / GLB into TEMP_DIR; if it did not (e.g. error path), unlink
        # the leftovers so reruns stay idempotent.
        for cleanup in (image_path, Path(threemf_path), Path(glb_path)):
            try:
                if cleanup.exists():
                    cleanup.unlink()
            except OSError:
                pass
        # Worker outputs.
        for key in ("threemf_path", "preview_glb_path", "metadata_sidecar_path"):
            value = (result or {}).get(key)
            if isinstance(value, str):
                try:
                    Path(value).unlink(missing_ok=True)
                except OSError:
                    pass


def test_worker_batch_convert_item_returns_full_five_key_contract(
    batch_worker_artifacts,
) -> None:
    """Returned dict contains exactly the 5 documented keys (R1.3, R6.1)."""
    _, _, result = batch_worker_artifacts

    expected_keys = {
        "threemf_path",
        "preview_glb_path",
        "metadata_sidecar_path",
        "xy_bbox_mm",
        "status_msg",
    }
    assert set(result.keys()) == expected_keys, (
        f"worker result keys {sorted(result.keys())!r} != "
        f"expected {sorted(expected_keys)!r}"
    )


def test_worker_batch_convert_item_three_paths_distinct_and_prefixed(
    batch_worker_artifacts,
) -> None:
    """3MF / preview GLB / sidecar paths are distinct and prefixed (R1.3, R6.1)."""
    artifact_prefix, _, result = batch_worker_artifacts

    threemf_out = result["threemf_path"]
    glb_out = result["preview_glb_path"]
    sidecar_out = result["metadata_sidecar_path"]

    # All three are real on-disk files.
    for path_value, label in (
        (threemf_out, "threemf_path"),
        (glb_out, "preview_glb_path"),
        (sidecar_out, "metadata_sidecar_path"),
    ):
        assert isinstance(path_value, str) and path_value, f"{label} is empty"
        assert os.path.exists(path_value), (
            f"{label} missing on disk: {path_value!r}"
        )
        base = os.path.basename(path_value)
        assert base.startswith(artifact_prefix), (
            f"{label} basename {base!r} does not start with "
            f"{artifact_prefix!r}"
        )

    # Pairwise distinct (both lexically and after realpath resolution).
    paths = [threemf_out, glb_out, sidecar_out]
    assert len(set(paths)) == 3, (
        f"expected 3 distinct artifact paths, got {paths!r}"
    )
    real_paths = [os.path.realpath(p) for p in paths]
    assert len(set(real_paths)) == 3, (
        f"artifact paths collide after realpath resolution: {real_paths!r}"
    )


def test_worker_batch_convert_item_sidecar_validates_with_full_slots(
    batch_worker_artifacts,
) -> None:
    """Worker JSON supplies complete material identities to the merge writer."""
    _, image_path, result = batch_worker_artifacts

    sidecar_out = result["metadata_sidecar_path"]
    with open(sidecar_out, "r", encoding="utf-8") as fh:
        sidecar_payload = json.load(fh)

    assert set(sidecar_payload) == {
        "schema_version", "source_filename", "xy_bbox_mm", "slots",
    }
    assert sidecar_payload["schema_version"] == 1
    assert sidecar_payload["source_filename"] == os.path.basename(image_path)
    assert set(sidecar_payload["xy_bbox_mm"]) == {"width_mm", "depth_mm"}
    assert sidecar_payload["xy_bbox_mm"]["width_mm"] > 0
    assert sidecar_payload["xy_bbox_mm"]["depth_mm"] > 0

    slots = [MaterialSlot(**slot) for slot in sidecar_payload["slots"]]
    assert slots
    assert len({slot.slot_id for slot in slots}) == len(slots)
    for slot in slots:
        assert isinstance(slot.slot_id, int) and slot.slot_id >= 0
        assert isinstance(slot.slot_name, str) and slot.slot_name
        assert isinstance(slot.preview_color, str)
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", slot.preview_color)
        assert isinstance(slot.material_id, str) and slot.material_id


def test_worker_batch_convert_item_xy_bbox_matches_sidecar(
    batch_worker_artifacts,
) -> None:
    """Returned ``xy_bbox_mm`` matches the sidecar's xy_bbox_mm (R1.3)."""
    _, _, result = batch_worker_artifacts

    sidecar_out = result["metadata_sidecar_path"]
    with open(sidecar_out, "r", encoding="utf-8") as fh:
        sidecar_payload = json.load(fh)

    bbox_tuple = result["xy_bbox_mm"]
    assert isinstance(bbox_tuple, tuple), (
        f"xy_bbox_mm must be a tuple; got {type(bbox_tuple).__name__}"
    )
    assert len(bbox_tuple) == 2, (
        f"xy_bbox_mm must be a 2-tuple (width_mm, depth_mm); got "
        f"{bbox_tuple!r}"
    )

    width_mm, depth_mm = bbox_tuple
    assert width_mm == sidecar_payload["xy_bbox_mm"]["width_mm"], (
        f"width_mm mismatch: tuple={width_mm!r} sidecar="
        f"{sidecar_payload['xy_bbox_mm']['width_mm']!r}"
    )
    assert depth_mm == sidecar_payload["xy_bbox_mm"]["depth_mm"], (
        f"depth_mm mismatch: tuple={depth_mm!r} sidecar="
        f"{sidecar_payload['xy_bbox_mm']['depth_mm']!r}"
    )


def test_worker_batch_convert_item_no_scene_or_bytes_payload(
    batch_worker_artifacts,
) -> None:
    """Returned dict carries no ``trimesh.Scene`` / bytes payload (R6.1).

    The worker boundary is "file paths + scalars". A regression here
    means a future change accidentally pickled a heavy Scene / bytes
    blob across the process boundary, breaking the picklability +
    minimal-boundary contract that the spec calls out explicitly
    (design.md §Components 5).
    """
    _, _, result = batch_worker_artifacts

    for key, value in result.items():
        # No trimesh Scene anywhere in the result.
        assert not isinstance(value, trimesh.Scene), (
            f"result[{key!r}] is a trimesh.Scene; the worker must only "
            "return file paths + scalars"
        )
        # No bytes / bytearray / memoryview payload anywhere either.
        assert not isinstance(value, (bytes, bytearray, memoryview)), (
            f"result[{key!r}] is a {type(value).__name__} payload; the "
            "worker must only return file paths + scalars"
        )
