"""Material ownership regressions for continuous coating and structural outline."""

from types import SimpleNamespace

import numpy as np
import pytest
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from core.pipeline.vector_branch import _generate_vector_outline_mesh
from core.pipeline.vector_glb_preview import build_vector_preview_parts_from_analysis
from core.vector_engine import VectorProcessor
from core.export_materials import ExportMaterial


def _analysis():
    silhouette = box(0, 0, 20, 30)
    # Optical region seams must not become structural outline islands.
    colors = silhouette.difference(box(9.99, 5, 10.01, 25))
    shapes = [{"geometry": colors, "recipe": [0, 0], "color": (255, 0, 0)}]
    return SimpleNamespace(
        silhouette=silhouette, image_vectorizer_bounds=None,
        matched_shapes=shapes, clipped_shapes=shapes, shape_data=[],
        scale_factor=1.0, bbox=(0, 0, 20, 30), num_layers=2,
        num_channels=1, slot_names=["Red"], color_conf={},
        material_dynamic_layer_info=None, material_solver_info=None,
        preview_colors={0: [255, 0, 0, 255]}, stage_timings={},
    )


def _top_footprint(mesh):
    vertices = np.asarray(mesh.vertices)
    triangles = vertices[np.asarray(mesh.faces)]
    top = triangles[np.all(np.isclose(triangles[:, :, 2], mesh.bounds[1, 2]), axis=1)]
    return unary_union([Polygon(triangle[:, :2]) for triangle in top])


def _scene_and_outline(analysis, coating=True):
    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor.color_mode = "Material Archive"
    processor.enable_outline = True
    processor.outline_width_mm = 2.0
    processor.enable_coating = coating
    processor.coating_height_mm = 0.08
    processor.coating_material = ExportMaterial("White PETG", "PETG", (246, 247, 248))
    scene = processor.build_mesh(analysis, thickness_mm=1.2)
    outline = _generate_vector_outline_mesh(
        analysis, 2.0, [255, 255, 255, 255], "White",
        {"spacer_thick": 1.2, "structure_mode": "Single-sided",
         "enable_coating": coating, "coating_height_mm": 0.08},
        export_color_mode="Material Archive",
    )
    return scene, outline


@pytest.mark.parametrize("coating", [False, True])
def test_vector_outline_uses_structure_not_optical_seams(coating):
    scene, outline = _scene_and_outline(_analysis(), coating)
    assert outline is not None
    assert outline.is_watertight
    assert len(outline.split()) == 1
    assert _top_footprint(outline).intersection(_top_footprint(scene.geometry["Board"])).area < 1e-8


def test_vector_coating_and_outline_share_surface_not_volume():
    scene, outline = _scene_and_outline(_analysis())
    coating = scene.geometry["Coating"]
    assert coating.metadata["bambu_material_name"] == "White PETG"
    assert coating.visual.face_colors[0].tolist() == [246, 247, 248, 255]
    assert outline.bounds[0, 2] == pytest.approx(coating.bounds[1, 2])
    assert _top_footprint(outline).difference(_top_footprint(coating)).area < 1e-8


def test_vector_preview_uses_same_structure_partition_as_export():
    analysis = _analysis()
    parts = build_vector_preview_parts_from_analysis(
        analysis=analysis, preview_colors=analysis.preview_colors,
        slot_list=analysis.slot_names, structure_mode="Single-sided",
        color_mode="Material Archive", thickness_mm=1.2,
        separate_backing=False, include_backing=True,
        include_outline=True, outline_width_mm=2.0,
    )
    footprints = {p.source_name: p.extrusions[0].footprint for p in parts}
    assert footprints["Board"].intersection(footprints["Outline"]).area < 1e-8
    scene, outline = _scene_and_outline(analysis)
    writer_footprint = affinity.scale(footprints["Outline"], -1, -1, origin=(0, 0))
    assert writer_footprint.symmetric_difference(_top_footprint(outline)).area < 1e-8


def test_tiles_clip_global_structure_without_outlining_cut_edges():
    from core.vector_large_format import slice_vector_analysis_into_tiles
    from core.vector_structure import resolve_structure_plan

    analysis = _analysis()
    analysis.structure_plan = resolve_structure_plan(analysis, 2.0)
    tiles = slice_vector_analysis_into_tiles(
        analysis=analysis, total_width_mm=20, total_height_mm=30,
        tile_width_mm=10, tile_height_mm=30,
    )
    assert len(tiles) == 2
    for tile in tiles:
        plan = resolve_structure_plan(tile.analysis, 2.0)
        cut_x = 10.0 if tile.spec.x0_mm == 0 else 0.0
        assert plan.outline.intersection(box(cut_x - 0.01, 3, cut_x + 0.01, 27)).area == 0
        assert plan.body.bounds[2 if tile.spec.x0_mm == 0 else 0] == pytest.approx(cut_x)


@pytest.mark.parametrize("scale", [0.1, 1.0, 2.5])
def test_structure_partition_retains_holes_and_separate_components(scale):
    from core.vector_structure import resolve_structure_plan
    from shapely.geometry import Point

    analysis = _analysis()
    analysis.scale_factor = scale
    analysis.silhouette = box(0, 0, 20, 30).difference(box(5, 5, 15, 25)).union(box(40, 0, 45, 30))
    plan = resolve_structure_plan(analysis, 0.5 * scale)
    hole_center = Point(10 * scale, 15 * scale)
    assert not plan.body.covers(hole_center)
    assert not plan.envelope.covers(hole_center)
    assert len(plan.body.geoms) == 2
    assert len(plan.envelope.geoms) == 2
    assert plan.body.intersection(plan.outline).area == pytest.approx(0.0, abs=1e-8)
    assert plan.body.union(plan.outline).symmetric_difference(plan.envelope).area < 1e-8


@pytest.mark.parametrize("structure_mode", ["Single-sided", "Double-sided"])
@pytest.mark.parametrize("color_mode", ["Material Archive", "4-Color RYBW", "5-Color Extended"])
def test_coating_material_interval_is_independent_of_mode(structure_mode, color_mode):
    analysis = _analysis()
    mesh = _generate_vector_outline_mesh(
        analysis, 2.0, [255, 255, 255, 255], "White",
        {"structure_mode": structure_mode, "color_mode": color_mode,
         "spacer_thick": 1.2, "enable_coating": True, "coating_height_mm": 0.08},
    )
    assert mesh.bounds[0, 2] == pytest.approx(0.0)
    assert mesh.section([0, 0, 1], [0, 0, -0.04]) is None


def test_outline_uses_requested_material_layer_height():
    analysis = _analysis()
    mesh = _generate_vector_outline_mesh(
        analysis, 2.0, [255, 255, 255, 255], "White",
        {"structure_mode": "Single-sided", "material_source": "material_archive",
         "spacer_thick": 1.2, "layer_height_mm": 0.12,
         "enable_coating": True, "coating_height_mm": 0.12},
    )
    assert mesh.bounds[1, 2] == pytest.approx(1.2 + analysis.num_layers * 0.12)


@pytest.mark.parametrize("layer_height", [0.04, 0.08, 0.10])
@pytest.mark.parametrize("coating_height", [0.04, 0.08, 0.12])
@pytest.mark.parametrize("structure_mode", ["Single-sided", "Double-sided"])
def test_native_vector_film_is_independent_of_optical_layer_height(
    layer_height, coating_height, structure_mode,
):
    analysis = _analysis()
    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor.color_mode = "Material Archive"
    processor.layer_height_mm = layer_height
    processor.enable_coating = True
    processor.coating_height_mm = coating_height
    scene = processor.build_mesh(analysis, thickness_mm=1.2, structure_mode=structure_mode)

    coating = scene.geometry["Coating"]
    bottom = [-coating_height, 0.0]
    if structure_mode == "Double-sided":
        body_top = round(1.2 / layer_height) * layer_height + 4 * layer_height
        bottom += [body_top, body_top + coating_height]
    assert np.unique(np.round(coating.vertices[:, 2], 9)) == pytest.approx(bottom)
    assert coating.is_watertight
    assert scene.geometry["Board"].bounds[:, 2] == pytest.approx(
        [2 * layer_height, (2 + round(1.2 / layer_height)) * layer_height],
    )


def test_backing_only_tile_keeps_declared_structure_without_new_cut_margins():
    from core.vector_large_format import slice_vector_analysis_into_tiles
    from core.vector_structure import resolve_structure_plan

    analysis = _analysis()
    analysis.silhouette = box(0, 0, 30, 30)
    colors = box(0, 0, 5, 30).union(box(25, 0, 30, 30))
    analysis.matched_shapes = [{"geometry": colors, "recipe": [0, 0]}]
    analysis.clipped_shapes = analysis.matched_shapes
    analysis.structure_plan = resolve_structure_plan(analysis, 2.0)
    tiles = slice_vector_analysis_into_tiles(
        analysis=analysis, total_width_mm=30, total_height_mm=30,
        tile_width_mm=10, tile_height_mm=30,
    )
    assert len(tiles) == 3
    middle = tiles[1].analysis
    assert not middle.matched_shapes
    for width in (0.0, 2.0):
        body = resolve_structure_plan(middle, width).body
        assert body.bounds[0] == pytest.approx(0.0)
        assert body.bounds[2] == pytest.approx(10.0)
