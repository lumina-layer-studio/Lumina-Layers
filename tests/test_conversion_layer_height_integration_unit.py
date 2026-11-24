"""Exercise actual model geometry and the native 3MF project layer schedule."""

import json
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import numpy as np
import pytest
import trimesh
from PIL import Image

from config import ModelingMode
from core.export_materials import resolve_coating_material
from core.pipeline import s06_voxel_building, s07_mesh_generation, s08_auxiliary_meshes, s09_export_3mf, s11_glb_preview


def _assert_serialized_coating(archive, thickness, *, count):
    config = ElementTree.fromstring(archive.read("Metadata/model_settings.config"))
    coating_ids = {
        part.get("id") for part in config.findall("./object/part")
        if any(meta.get("value", "").startswith("Coating")
               for meta in part.findall("./metadata[@key='name']"))
    }
    boundaries = set()
    for member in archive.namelist():
        if not member.startswith("3D/") or not member.endswith(".model"):
            continue
        for obj in ElementTree.fromstring(archive.read(member)).findall("./{*}resources/{*}object"):
            if obj.get("id") not in coating_ids:
                continue
            boundaries.update(
                round(float(v.get("z")), 6) for v in obj.findall("./{*}mesh/{*}vertices/{*}vertex")
            )
    layers = sorted(boundaries)
    assert len(layers) == 2 * count
    assert [high - low for low, high in zip(layers[::2], layers[1::2])] == pytest.approx([thickness] * count)


def _raster_context(layer_height, coating_height, tmp_path, *, mode=ModelingMode.PIXEL):
    image = tmp_path / "art.png"
    Image.new("RGB", (4, 4), "red").save(image)
    colors = {0: [255, 255, 255, 255], 1: [255, 0, 0, 255]}
    return {
        "image_path": str(image), "modeling_mode": mode, "color_mode": "4-Color RYBW",
        "material_matrix": np.broadcast_to([1, 0, 1], (4, 4, 3)).copy(),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "matched_rgb": np.full((4, 4, 3), [255, 0, 0], dtype=np.uint8),
        "target_w": 4, "target_h": 4, "pixel_scale": 3.0,
        "slot_names": ["White", "Red"], "preview_colors": colors,
        "backing_color_id": 0, "structure_mode": "Single-sided",
        "spacer_thick": 1.0, "layer_height_mm": layer_height,
        "enable_coating": coating_height is not None,
        "coating_height_mm": coating_height,
        "resolved_coating_material": resolve_coating_material(
            None, slot_names=["White", "Red"], preview_colors=colors, material_types={},
        ),
        "printer_id": "bambu-a1-mini", "nozzle_size": "0.2",
        "enable_wipe_tower_auto_placement": False,
    }


@pytest.mark.parametrize("mode", [ModelingMode.PIXEL, ModelingMode.HIGH_FIDELITY])
def test_raster_004_keeps_backing_and_individual_optical_layers(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    ctx = _raster_context(0.04, None, tmp_path, mode=mode)
    for stage in (s06_voxel_building, s07_mesh_generation, s08_auxiliary_meshes, s09_export_3mf):
        ctx = stage.run(ctx)
        assert not ctx.get("error")
    assert ctx["total_layers"] == 28  # Three optical layers and 25 backing layers.
    assert ctx["scene"].bounds[:, 2] == pytest.approx([0, 1.12])
    assert np.unique(ctx["scene"].geometry["Red"].vertices[:, 2]) == pytest.approx(
        [0, 0.04, 0.08, 0.12],
    )
    with ZipFile(ctx["out_path"]) as archive:
        project = json.loads(archive.read("Metadata/project_settings.config"))
    assert float(project["layer_height"]) == pytest.approx(0.04)
    assert float(project["initial_layer_print_height"]) == pytest.approx(0.04)


@pytest.mark.parametrize("main_height", [0.04, 0.08, 0.10])
@pytest.mark.parametrize("coat_height", [0.04, 0.08, 0.12])
def test_double_sided_raster_exports_exact_coats_and_layer_settings(
    tmp_path, monkeypatch, main_height, coat_height,
):
    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    ctx = _raster_context(main_height, coat_height, tmp_path)
    ctx["structure_mode"] = "Double-sided"
    ctx["enable_outline"] = True
    for stage in (s06_voxel_building, s07_mesh_generation, s08_auxiliary_meshes, s09_export_3mf):
        ctx = stage.run(ctx)
        assert not ctx.get("error")
    body_top = (6 + round(1.0 / main_height)) * main_height
    coat = ctx["scene"].geometry["Coating"]
    assert np.unique(coat.vertices[:, 2]) == pytest.approx(
        [-coat_height, 0.0, body_top, body_top + coat_height],
    )
    assert ctx["scene"].geometry["Outline"].bounds[:, 2] == pytest.approx([0, body_top])
    assert ctx["bambu_color_height_mm"] == pytest.approx(3 * main_height + coat_height)

    with ZipFile(ctx["out_path"]) as archive:
        _assert_serialized_coating(archive, coat_height, count=2)
        project = json.loads(archive.read("Metadata/project_settings.config"))
        ranges = ElementTree.fromstring(archive.read("Metadata/layer_config_ranges.xml"))
    layer = float(project["layer_height"])
    first = float(project["initial_layer_print_height"])
    assert layer == pytest.approx(main_height)
    assert 0 < first <= coat_height + 1e-9
    remaining_coat = (coat_height - first) / layer
    assert remaining_coat == pytest.approx(round(remaining_coat))
    top_z = body_top + coat_height
    top_range = next(r for r in ranges.iter("range") if float(r.get("min_z")) == pytest.approx(top_z))
    assert float(top_range.get("max_z")) == pytest.approx(top_z + coat_height)
    top_layer = float(top_range.findtext("option[@opt_key='layer_height']"))
    assert coat_height / top_layer == pytest.approx(round(coat_height / top_layer))
    assert float(project["min_layer_height"][0]) <= top_layer <= float(project["max_layer_height"][0])


@pytest.mark.parametrize("main_height,coat_height", [(0.04, 0.12), (0.08, 0.04), (0.10, 0.12)])
def test_raster_coats_each_stepped_face_up_roof(tmp_path, main_height, coat_height):
    ctx = _raster_context(main_height, coat_height, tmp_path)
    ctx["color_mode"] = "5-Color Extended"
    ctx["material_matrix"][:, :2, 0] = -1
    for stage in (s06_voxel_building, s07_mesh_generation, s08_auxiliary_meshes):
        ctx = stage.run(ctx)
        assert not ctx.get("error")

    coat = ctx["scene"].geometry["Coating"]
    # The left side is one authored layer shorter; both have the same film thickness.
    bottom_left = (round(1 / main_height) + 2) * main_height
    bottom_right = bottom_left + main_height
    assert coat.volume == pytest.approx(12 * 12 * coat_height)
    assert coat.bounds[:, 2] == pytest.approx([bottom_left, bottom_right + coat_height])
    assert coat.is_watertight
    assert coat.section([0, 0, 1], [0, 0, bottom_left - 0.001]) is None


@pytest.mark.parametrize("coat_height", [0.04, 0.12])
def test_stepped_face_up_3mf_schedules_both_films_and_keeps_the_body_layer(coat_height, tmp_path, monkeypatch):
    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    ctx = _raster_context(0.08, coat_height, tmp_path)
    ctx["color_mode"] = "5-Color Extended"
    ctx["material_matrix"][:, :2, 0] = -1
    for stage in (s06_voxel_building, s07_mesh_generation, s08_auxiliary_meshes, s09_export_3mf):
        ctx = stage.run(ctx)
        assert not ctx.get("error")

    with ZipFile(ctx["out_path"]) as archive:
        project = json.loads(archive.read("Metadata/project_settings.config"))
        root = ElementTree.fromstring(archive.read("Metadata/layer_config_ranges.xml"))
    main = float(project["layer_height"])
    minimum = float(project["min_layer_height"][0])
    assert main == pytest.approx(0.08)
    assert minimum == pytest.approx(0.04)
    ranges = [
        (float(span.get("min_z")), float(span.get("max_z")), float(height))
        for span in root.iter("range")
        if (height := span.findtext("option[@opt_key='layer_height']")) is not None
    ]
    coat = ctx["scene"].geometry["Coating"]
    roof_bottom = float(coat.bounds[0, 2])
    roof_above = roof_bottom + main
    # Check whether a slicer following the native range schedule can reach both
    # mesh roofs and their endpoints, including the body step between them.
    z = float(project["initial_layer_print_height"])
    boundaries = {round(z, 6)}
    while z < coat.bounds[1, 2] - 1e-7:
        sample_z = z + minimum / 2
        z += next((height for start, end, height in ranges if start <= sample_z < end), main)
        boundaries.add(round(z, 6))
    assert {round(edge, 6) for edge in (
        roof_bottom, roof_bottom + coat_height, roof_above, roof_above + coat_height,
    )} <= boundaries


def test_raster_004_quantizes_magnet_depth_on_the_authored_lattice(tmp_path):
    ctx = _raster_context(0.04, None, tmp_path)
    ctx.update(spacer_thick=0.4, enable_fridge_magnet=True, fridge_magnets=[{
        "shape": "rect", "width_mm": 6, "height_mm": 6, "thickness_mm": 0.44,
    }])
    result = s06_voxel_building.run(ctx)
    assert not result.get("error")
    assert result["bambu_base_height_mm"] == pytest.approx(0.84)
    assert np.count_nonzero(result["full_matrix"][:, 1, 1] == -1) == 11
    assert np.count_nonzero(result["full_matrix"][:, 0, 0] == -1) == 0


def test_raster_004_uses_the_full_recipe_under_the_wire(tmp_path):
    from types import SimpleNamespace

    ctx = _raster_context(0.04, None, tmp_path)
    ctx.update(
        enable_cloisonne=True, wire_height_mm=0.20,
        material_matrix=np.broadcast_to([1, 0, 1, 0, 1, 0, 1], (4, 4, 7)).copy(),
        processor=SimpleNamespace(_extract_wireframe_mask=lambda *_: np.ones((4, 4), dtype=bool)),
    )
    result = s06_voxel_building.run(ctx)
    assert not result.get("error")
    assert result["total_layers"] == 25 + 7 + 5
    assert result["backing_metadata"]["wire_layers"] == 5
    assert result["bambu_color_height_mm"] == pytest.approx(0.28)


def test_004_preview_uses_the_authored_z_scale(tmp_path):
    cache = _raster_context(0.04, None, tmp_path)
    cache["target_width_mm"] = 12
    path = str(tmp_path / "preview.glb")
    assert s11_glb_preview.generate_segmented_glb(cache, output_path=path, total_layers=3) == path
    preview = trimesh.load_scene(path)
    assert preview.bounds[:, 2] == pytest.approx([0, 0.12])


@pytest.mark.parametrize("main_height,coat_height", [(0.04, 0.12), (0.08, 0.04)])
def test_vector_route_writes_exact_native_coating(tmp_path, monkeypatch, main_height, coat_height):
    import config
    from core.converter import generate_final_model

    monkeypatch.setattr(config, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
    svg = tmp_path / "tile.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 16">'
        '<path fill="#ab5566" d="M0 0H24V16H0Z"/></svg>', encoding="utf-8",
    )
    lut = Path(__file__).parent / "fixtures/lut_regression/bambulab_pla_basic_rybw.npy"
    path, _, _, status, _ = generate_final_model(
        str(svg), str(lut), 24, 1, "Double-sided", "4-Color (RYBW)", False, 4, 8, 2.5, None,
        modeling_mode=ModelingMode.VECTOR, color_layers=5, layer_height_mm=main_height,
        enable_coating=True, coating_height_mm=coat_height, printer_id="bambu-p1s",
        nozzle_size="0.4", enable_wipe_tower_auto_placement=False,
    )
    assert path, status
    with ZipFile(path) as archive:
        _assert_serialized_coating(archive, coat_height, count=2)
        project = json.loads(archive.read("Metadata/project_settings.config"))
        ranges = ElementTree.fromstring(archive.read("Metadata/layer_config_ranges.xml"))
    assert float(project["layer_height"]) == pytest.approx(main_height)
    assert float(project["initial_layer_print_height"]) == pytest.approx(0.04)
    top = max(ranges.iter("range"), key=lambda span: float(span.get("max_z")))
    assert float(top.get("max_z")) - float(top.get("min_z")) == pytest.approx(coat_height)
    assert float(top.findtext("option[@opt_key='layer_height']")) == pytest.approx(0.04)
