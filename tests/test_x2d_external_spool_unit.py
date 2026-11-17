"""External spool head assignment in final X2D projects."""

from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile
import json

import pytest
import trimesh

from core.errors import CoreValidationError
from utils.bambu_3mf_writer import Slicer3MFWriter, export_scene_with_slicer_metadata
from utils.fatcat_metadata import select_metadata_target
from utils.merged_bambu_3mf_writer import (
    MaterialSlot, MergedItem, MergedSlicer3MFWriter, read_merge_source_info,
)


COLORS = {"Black": (12, 12, 12), "White": (250, 250, 250), "Red": (255, 30, 30)}
DEVICE = dict(printer_id="bambu-lab-x2d", slicer="BambuStudio", nozzle_size="0.4",
              device_profile_id="BambuStudio:bbl:bambu-lab-x2d:0.4", build_plate_id="textured-pei-plate")


def _export(path, names, used, material=None):
    writer = Slicer3MFWriter(
        str(path), **DEVICE, enable_wipe_tower_auto_placement=False, external_spool_material=material,
        native_filament_profiles=dict.fromkeys(names, "Bambu PETG Basic @BBL X2D 0.4 nozzle"),
        material_types=dict.fromkeys(names, "PETG"),
    )
    writer._set_project_palette(names, {index: COLORS[name] for index, name in enumerate(names)})
    for index, name in enumerate(used):
        mesh = trimesh.creation.box(extents=(4, 4, 1))
        mesh.apply_translation((4 * index, 0, 0.5))
        mesh.metadata["bambu_material_name"] = name
        writer.add_mesh(mesh, "part " + name, COLORS[name])
    writer.export()


def _assert_plate(path, expected_colors, expected_map):
    with ZipFile(path) as archive:
        settings = json.loads(archive.read("Metadata/project_settings.config"))
        assert settings["filament_colour"] == expected_colors
        plate = ET.fromstring(archive.read("Metadata/model_settings.config")).find("plate")
        modes = [row.get("value") for row in plate.findall("metadata[@key='filament_map_mode']")]
        maps = [row.get("value") for row in plate.findall("metadata[@key='filament_maps']")]
        if expected_map is None:
            assert modes == ["Auto For Flush"]
            assert maps == []
        else:
            assert modes == ["Manual"]
            assert maps == [expected_map]


@pytest.mark.parametrize(("material", "mapping"), [(None, None), ("White", "1 1 2"), ("Black", "2 1 1")])
def test_single_uses_complete_palette_even_if_external_material_has_no_mesh(tmp_path, material, mapping):
    path = tmp_path / "single.3mf"
    _export(path, ["Black", "Red", "White"], ["Red", "Black"], material)
    _assert_plate(path, ["#0C0C0C", "#FF1E1E", "#FAFAFA"], mapping)


def test_merged_sparse_objects_assign_unused_slot_by_canonical_material_name(tmp_path):
    target = select_metadata_target(**DEVICE)
    names = ["Red", "White", "Black"]
    items = []
    for index, used in enumerate([["Black"], ["Red"]]):
        path = tmp_path / f"source-{index}.3mf"
        _export(path, names, used)
        _, slots = read_merge_source_info(path, metadata_target=target, use_base_material_names=True)
        assert [slot["slot_name"] for slot in slots] == names
        items.append(MergedItem(path.stem, path, tuple(MaterialSlot(**slot) for slot in slots), 50 * index, 0))
    merged = tmp_path / "merged.3mf"
    MergedSlicer3MFWriter().write(
        items, merged, metadata_target=target, plate_width_mm=256, plate_depth_mm=256,
        enable_wipe_tower_auto_placement=False, external_spool_material="White",
    )
    _assert_plate(merged, ["#FF1E1E", "#FAFAFA", "#0C0C0C"], "1 2 1")
    with ZipFile(merged) as archive:
        root = ET.fromstring(archive.read("Metadata/model_settings.config"))
        assert len(root.findall("object")) == 2


@pytest.mark.parametrize(("device", "names", "message"), [
    ("bambu-lab:x2d", ["Black", "White"], "missing"),
    ("bambu-lab:x2d", ["Red", "Red"], "multiple"),
    ("bambu-lab:h2d", ["Red"], "X2D"),
    ("", [], "X2D"),
])
def test_generate_preflight_rejects_invalid_choice_as_http_422(monkeypatch, device, names, message):
    from fastapi import HTTPException
    from api.routers.converter.export_materials import require_material_selection
    from core import export_material_selection

    monkeypatch.setattr(export_material_selection, "resolve_export_material_selection",
                        lambda *args, **kwargs: {"ready": True, "materials": [{"name": name} for name in names],
                                                 "slicer_id": "BambuStudio", "machine_uid": device})
    with pytest.raises(HTTPException) as error:
        require_material_selection({"lut_name": "example", "external_spool_material": "Red"})
    assert error.value.status_code == 422
    assert message in error.value.detail


def test_final_export_rejects_material_dropped_after_preflight(tmp_path):
    with pytest.raises(CoreValidationError, match="missing"):
        _export(tmp_path / "invalid.3mf", ["White", "Black"], ["Black"], "Red")
    assert not (tmp_path / "invalid.3mf").exists()


def test_direct_writer_rejects_duplicate_chosen_slot(tmp_path):
    with pytest.raises(CoreValidationError, match="multiple"):
        _export(tmp_path / "ambiguous.3mf", ["Red", "Red"], ["Red"], "Red")

def test_independent_backing_keeps_one_head_assignment_per_compact_project(tmp_path):
    scene = trimesh.Scene()
    for name in ("Red", "Black"):
        mesh = trimesh.creation.box(extents=(4, 4, 0.8))
        mesh.metadata["bambu_material_name"] = name
        if name == "Black":
            mesh.metadata["lumina_print_role"] = "backing"
        scene.add_geometry(mesh, geom_name=name)
    path = export_scene_with_slicer_metadata(
        scene, str(tmp_path / "split.3mf"), list(scene.geometry), COLORS,
        project_slot_names=["Black", "Red"], backing_output="separate_project",
        native_filament_profiles=dict.fromkeys(COLORS, "Bambu PETG Basic @BBL X2D 0.4 nozzle"),
        material_types=dict.fromkeys(COLORS, "PETG"), external_spool_material="Black", **DEVICE,
    )
    with ZipFile(path) as archive:
        _assert_plate(BytesIO(archive.read("plate_1_model.3mf")), ["#FF1E1E"], "1")
        _assert_plate(BytesIO(archive.read("plate_2_backing.3mf")), ["#0C0C0C"], "2")


def test_puzzle_reprojects_external_spool_after_palette_reordering(tmp_path):
    from core.puzzle_3mf import PuzzlePiece3MFSource, assemble_puzzle_3mf

    target = select_metadata_target(**DEVICE)
    native_names = ["Red", "Black", "White"]
    puzzle_names = ["White", "Red", "Black"]
    paths = [tmp_path / "left.3mf", tmp_path / "right.3mf"]
    piece_slots = []
    for path, used in zip(paths, (["Black"], ["White"])):
        _export(path, native_names, used)
        _, slots = read_merge_source_info(path, metadata_target=target)
        piece_slots.append([MaterialSlot(**slot) for slot in slots])
    path = tmp_path / "puzzle.3mf"
    assemble_puzzle_3mf(
        [PuzzlePiece3MFSource(p.stem, str(p), x * 8, 0) for x, p in enumerate(paths)],
        piece_slots, str(path), puzzle_names, COLORS,
        {name: index for index, name in enumerate(native_names)}, DEVICE["printer_id"],
        DEVICE["nozzle_size"], DEVICE["device_profile_id"], DEVICE["build_plate_id"], None,
        target, enable_wipe_tower_auto_placement=False, material_types=dict.fromkeys(puzzle_names, "PETG"),
        native_filament_profiles=dict.fromkeys(puzzle_names, "Bambu PETG Basic @BBL X2D 0.4 nozzle"),
        external_spool_material="Black",
    )
    _assert_plate(path, ["#FAFAFA", "#FF1E1E", "#0C0C0C"], "1 1 2")
