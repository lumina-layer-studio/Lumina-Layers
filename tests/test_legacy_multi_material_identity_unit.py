"""Merged LUTs must retain every material channel after serialization."""

from pathlib import Path
import json
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pytest
import trimesh

from config import LUTMetadata, ModelingMode, PaletteEntry
from core.pipeline import s01_input_validation, s05_preview_generation
from utils.lut_manager import LUTManager
from utils.bambu_3mf_writer import export_scene_with_slicer_metadata


@pytest.mark.parametrize("second_material", ["PLA", "PETG (matte)"])
def test_multi_lut_roundtrip_preserves_same_color_different_materials(
    tmp_path: Path, second_material: str,
) -> None:
    paths = []
    materials = ["PLA Basic", second_material]
    colors = [("Red", "#e02030"), ("White", "#fff8f0")]
    for index, material in enumerate(materials):
        path = tmp_path / f"source-{index}.npz"
        LUTManager.save_npz_with_metadata(
            str(path),
            np.array([[120 + index, 30, 20]], dtype=np.uint8),
            np.array([[0, 1, 0, 1, 0]], dtype=np.int32),
            LUTMetadata(
                palette=[PaletteEntry(name, material, color) for name, color in colors],
                base_channel_idx=1,
            ),
        )
        paths.append(str(path))

    runtime = Path(LUTManager._legacy_multi_runtime_path(["first", "second"], paths))
    try:
        rgb, stacks, metadata = LUTManager.load_lut_with_metadata(str(runtime))
        assert len(metadata.palette) == 4
        assert len({entry.color for entry in metadata.palette}) == 4
        np.testing.assert_array_equal(rgb, [[120, 30, 20], [121, 30, 20]])
        for row, material in zip(stacks, materials):
            assert [metadata.palette[i].material for i in row] == [material] * 5
            assert [metadata.palette[i].hex_color for i in row] == [
                "#e02030", "#fff8f0", "#e02030", "#fff8f0", "#e02030",
            ]
        backing = metadata.palette[metadata.base_channel_idx]
        assert (backing.material, backing.hex_color) == ("PLA Basic", "#fff8f0")

        # The real generation stages must resolve the selected loop channel,
        # including indices above the palette size before the fix.
        ctx = s01_input_validation.run({
            "image_path": str(tmp_path / "image.png"),
            "lut_path": str(runtime),
            "color_mode": "4-Color (RYBW)",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
        })
        ctx.update(
            matched_rgb=np.full((10, 10, 3), 120, dtype=np.uint8),
            mask_solid=np.ones((10, 10), dtype=bool),
            material_matrix=np.tile(stacks[0], (10, 10, 1)),
            target_w=10, target_h=10, pixel_scale=1.0, add_loop=True,
        )
        ctx = s05_preview_generation.run(ctx)
        selected = metadata.palette[ctx["loop_info"]["color_id"]]
        assert selected.material == "PLA Basic"
        assert ctx["loop_info"]["material_name"] == selected.color

        # A merged LUT remains a valid input; labels must not create new channels.
        remixed = Path(LUTManager._legacy_multi_runtime_path(["merged"], [str(runtime)]))
        try:
            _, remixed_stacks, remixed_metadata = LUTManager.load_lut_with_metadata(str(remixed))
            assert remixed_metadata.palette == metadata.palette
            assert remixed_metadata.base_channel_idx == metadata.base_channel_idx
            np.testing.assert_array_equal(remixed_stacks, stacks)
        finally:
            remixed.unlink()
    finally:
        runtime.unlink()


@pytest.mark.parametrize("sparse_scene", [False, True])
def test_merged_lut_exports_each_source_colour_and_auxiliary_binding(
    tmp_path: Path, sparse_scene: bool,
) -> None:
    colours = [
        ("White", "#ffffff"), ("Cyan", "#0086d6"),
        ("Magenta", "#ec008c"), ("Yellow", "#f4ee2a"),
        ("Red", "#c12e1f"), ("Deep Blue", "#0a2989"),
    ]
    paths = []
    for material, count in [("PLA Basic", 6), ("PLA", 4)]:
        path = tmp_path / f"{material}.npz"
        LUTManager.save_npz_with_metadata(
            str(path), np.array([[60, 80, 90]], dtype=np.uint8),
            np.array([[0, 1, 2, 3, count - 1]], dtype=np.int32),
            LUTMetadata(palette=[PaletteEntry(name, material, hex_colour)
                                 for name, hex_colour in colours[:count]]),
        )
        paths.append(str(path))
    runtime = Path(LUTManager._legacy_multi_runtime_path(["first", "second"], paths))
    try:
        _, _, metadata = LUTManager.load_lut_with_metadata(str(runtime))
        ctx = s01_input_validation.run({
            "image_path": str(tmp_path / "image.png"), "lut_path": str(runtime),
            "color_mode": "8-Color Max", "modeling_mode": ModelingMode.HIGH_FIDELITY,
        })
        names = ctx["slot_names"]
        assert len(names) == 10
        expected_colours = [entry.hex_color.upper() for entry in metadata.palette]
        scene = trimesh.Scene()
        indices = [8, 9] if sparse_scene else range(len(names))
        for index in indices:
            mesh = trimesh.creation.box(extents=(1, 1, 1))
            mesh.apply_translation((index * 2, 0, 0))
            scene.add_geometry(mesh, geom_name=names[index])
        for object_name, index in [("Backing", 0), ("Keychain_Loop", 8)]:
            mesh = trimesh.creation.box(extents=(1, 1, 1))
            mesh.apply_translation((index * 2, 3, 0))
            mesh.metadata["bambu_material_name"] = names[index]
            scene.add_geometry(mesh, geom_name=object_name)
        output = tmp_path / "merged.3mf"
        export_scene_with_slicer_metadata(
            scene, str(output), list(scene.geometry), ctx["preview_colors"],
            project_slot_names=names, material_types=ctx["material_types"],
            printer_id="bambu-p1s", slicer="BambuStudio",
            enable_wipe_tower_auto_placement=False,
            enable_base_layer_height_modifier=False,
        )
        with zipfile.ZipFile(output) as archive:
            settings = json.loads(archive.read("Metadata/project_settings.config"))
            model = ET.fromstring(archive.read("Metadata/model_settings.config"))
        assert settings["filament_colour"] == expected_colours
        part_slots = {}
        for part in model.findall(".//part"):
            values = {item.attrib["key"]: item.attrib["value"] for item in part.findall("metadata")}
            part_slots[values["name"]] = int(values["extruder"]) - 1
        for index in indices:
            assert part_slots[names[index]] == index
            assert settings["filament_colour"][part_slots[names[index]]] == expected_colours[index]
        assert part_slots["Backing"] == 0
        assert part_slots["Keychain_Loop"] == 8
        assert settings["filament_colour"][part_slots["Keychain_Loop"]] == "#C12E1F"
    finally:
        runtime.unlink()
