"""Product-workflow integration coverage for native SVG analysis results."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from core import vector_engine
from core.pipeline import vector_glb_preview
from core.layered_coordinate_domain import (
    LAYERED_COORDINATE_DOMAIN_KEY,
    LayeredCoordinateDomain,
)
from core.native_svg_adapter import NativeSvgGeometry, analyze_native_svg
from core.keychain_attachment import vector_keychain_body
from core.pipeline.vector_branch import (
    _generate_vector_outline_mesh,
    _inject_vector_keychain_loop,
)
from core.pipeline.vector_glb_preview import (
    build_vector_preview_parts_from_analysis,
    export_vector_glb_preview_v2,
)
from core.puzzle import PuzzleLayoutConfig, build_puzzle_layout
from core.vector_engine import (
    VectorProcessor,
    apply_recipe_overrides_to_analysis,
)
from core.vector_large_format import slice_vector_analysis_into_tiles
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "native_svg"
PALETTE_RGB = np.asarray(
    [
        [255, 255, 255],
        [220, 20, 60],
        [255, 230, 0],
        [0, 100, 240],
    ],
    dtype=np.uint8,
)


@pytest.fixture(autouse=True)
def _isolate_vector_parse_clip_cache():
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()
    try:
        yield
    finally:
        vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()


def _processor(*, matcher: object | None = None) -> VectorProcessor:
    if matcher is None:
        matcher = SimpleNamespace(
            lut_rgb=PALETTE_RGB,
            lut_path="native-workflow-direct.npy",
        )
    processor = VectorProcessor.from_img_processor(
        matcher,
        "4-Color (RYBW)",
    )

    def match_colors(
        clipped_shapes,
        *_args,
        num_layers=5,
        **_kwargs,
    ):
        matched = []
        for index, item in enumerate(clipped_shapes):
            channel = index % 3 + 1
            matched.append(
                {
                    "geometry": item["geometry"],
                    "recipe": [channel] * int(num_layers),
                    "color": item["color"],
                    "matched_rgb": tuple(int(value) for value in PALETTE_RGB[channel]),
                }
            )
        return matched

    processor._match_colors = match_colors
    return processor


def _analyze(
    filename: str = "clip_inherited_fill.svg",
    *,
    target_width_mm: float = 40.0,
    matcher: object | None = None,
):
    pytest.importorskip("lumina_svg_core")
    processor = _processor(matcher=matcher)
    analysis = processor.analyze_svg(
        str(FIXTURES / filename),
        target_width_mm,
    )
    assert analysis.stage_timings["geometry_backend"] == "native"
    return processor, analysis


def _magnet() -> dict[str, object]:
    return {
        "id": "native-round",
        "shape": "round",
        "preset_key": "round-4",
        "diameter_mm": 4.0,
        "width_mm": None,
        "height_mm": None,
        "thickness_mm": 0.4,
        "center_x_mm": 0.0,
        "center_y_mm": 0.0,
    }


def _preview_colors_with_names(analysis) -> dict:
    colors = dict(analysis.preview_colors)
    for index, name in enumerate(analysis.slot_names):
        colors[name] = colors[index]
    colors["Board"] = colors[0]
    return colors


def _package_part_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as package:
        root = ET.fromstring(package.read("Metadata/model_settings.config"))
    names = set()
    for part in root.findall(".//part"):
        for metadata in part.findall("metadata"):
            if metadata.attrib.get("key") == "name":
                names.add(metadata.attrib.get("value", ""))
    return names


def _world_node_mesh(scene: trimesh.Scene, node_name: str) -> trimesh.Trimesh:
    transform, geometry_name = scene.graph.get(node_name)
    mesh = scene.geometry[geometry_name].copy()
    mesh.apply_transform(transform)
    return mesh


@pytest.mark.parametrize(
    "svg",
    [
        "<svg><path d='M0 0H10V10Z'>",
        "<svg><path d='M0 0H10V10Z' fill='red&bogus;'/></svg>",
        "<svg><path d='M0 0H10V10Z&bogus;' fill='red'/></svg>",
        "<svg><path d='M0 0H10V10Z' fill='red' fill='blue'/></svg>",
    ],
)
def test_lumina_public_analysis_rejects_malformed_xml(
    svg: str,
    tmp_path: Path,
) -> None:
    pytest.importorskip("lumina_svg_core")
    svg_path = tmp_path / "malformed.svg"
    svg_path.write_text(svg, encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid SVG"):
        _processor().analyze_svg(str(svg_path), 20.0)


def test_native_analysis_preserves_component_hierarchy_without_geos_normalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native output must not be partially replaced by legacy GEOS cleanup."""

    pytest.importorskip("lumina_svg_core")
    # Prove this contract cannot pass merely because the exact key was warm.
    _analyze("component_hierarchy.svg", target_width_mm=5.0)
    assert vector_engine._VECTOR_PARSE_CLIP_CACHE
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()
    native_adapter_calls = 0
    native_analyze_svg = vector_engine.native_svg_adapter.analyze_native_svg

    def record_native_adapter_call(*args, **kwargs):
        nonlocal native_adapter_calls
        native_adapter_calls += 1
        return native_analyze_svg(*args, **kwargs)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("native analysis re-entered _normalize_contours_many")

    monkeypatch.setattr(
        vector_engine.native_svg_adapter,
        "analyze_native_svg",
        record_native_adapter_call,
    )
    monkeypatch.setattr(
        "core.vector_engine._normalize_contours_many",
        fail_if_called,
    )
    _processor_instance, analysis = _analyze(
        "component_hierarchy.svg",
        target_width_mm=5.0,
    )

    assert native_adapter_calls == 1
    assert analysis.stage_timings["contour_normalize_s"] == 0.0
    assert len(analysis.shape_data) == 1
    raw_geometry = analysis.shape_data[0]["poly"]
    assert raw_geometry.geom_type == "MultiPolygon"
    assert len(raw_geometry.geoms) == 2
    assert sum(len(component.interiors) for component in raw_geometry.geoms) == 1

    assert len(analysis.clipped_shapes) == 2
    assert {
        item["native_component_index"] for item in analysis.clipped_shapes
    } == {0, 1}
    assert {
        item["native_paint_id"] for item in analysis.clipped_shapes
    } == {(1, 0)}
    assert all(
        item["rgba"] == (18, 52, 86, 255)
        and item["geometry_normalized"] is True
        for item in analysis.clipped_shapes
    )
    assert sorted(
        len(item["geometry"].interiors)
        for item in analysis.clipped_shapes
    ) == [0, 1]


def test_native_adjacent_triangle_preserves_large_component_hole_and_shells() -> None:
    """Native adaptation must not repeat the destructive GEOS normalizer."""

    pytest.importorskip("lumina_svg_core")
    outcome = analyze_native_svg(
        str(FIXTURES / "legacy_normalizer_adjacent_triangle.svg"),
        target_width_mm=40.0,
        tolerance_mm=0.02,
    )

    assert isinstance(outcome, NativeSvgGeometry)
    assert len(outcome.shape_data) == 1
    raw_geometry = outcome.shape_data[0]["poly"]
    assert raw_geometry.geom_type == "MultiPolygon"
    assert len(raw_geometry.geoms) == 3
    assert sum(len(component.interiors) for component in raw_geometry.geoms) == 1
    source_scale = outcome.svg_coordinate_domain.source_units_per_unit
    assert raw_geometry.area * source_scale**2 == pytest.approx(301.3, abs=0.001)
    assert len(outcome.clipped_shapes) == 3
    assert sorted(
        item["geometry"].area * source_scale**2 for item in outcome.clipped_shapes
    ) == pytest.approx([0.5, 16.0, 284.8], abs=0.001)


def test_native_image_vectorizer_preserves_preview_canvas_glb_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    svg_path = tmp_path / "image-vectorizer.svg"
    svg_path.write_text(
        "<?xml version='1.0'?><!-- leading comment -->"
        "<svg xmlns='http://www.w3.org/2000/svg' aria-label='1 > 0' "
        "viewBox='0 0 20 20' "
        "data-lumina-origin='image&#45;vectorizer'>"
        "<rect x='0' y='0' width='4' height='20' fill='#dc143c'/>"
        "<rect x='16' y='0' width='4' height='20' fill='#0064f0'/>"
        "</svg>",
        encoding="utf-8",
    )
    processor = _processor()
    analysis = processor.analyze_svg(str(svg_path), 20.0)

    assert analysis.stage_timings["geometry_backend"] == "native"
    assert analysis.image_vectorizer_bounds is not None
    assert np.asarray(analysis.image_vectorizer_bounds.bounds) * analysis.scale_factor == pytest.approx(
        (0.0, 0.0, 20.0, 20.0)
    )

    scene = processor.build_mesh(
        analysis,
        thickness_mm=1.2,
        structure_mode="Single-sided",
    )
    output_path = tmp_path / "image-vectorizer-preview.glb"
    monkeypatch.setenv("LUMINA_VECTOR_GLB_KERNEL", "v2")
    vector_glb_preview.export_vector_glb_preview(
        scene=scene,
        output_path=str(output_path),
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
        preview_colors=_preview_colors_with_names(analysis),
        slot_list=list(analysis.slot_names),
        analysis=analysis,
        ctx={},
    )

    loaded = trimesh.load(output_path, force="scene")
    anchor = _world_node_mesh(
        loaded,
        vector_glb_preview.PREVIEW_CANVAS_BOUNDS_NODE_NAME,
    )
    np.testing.assert_allclose(
        anchor.bounds,
        np.asarray([[0.0, 0.0, 0.0], [20.0, 20.0, 0.0]]),
    )


def test_native_analysis_builds_single_double_and_auxiliary_meshes() -> None:
    processor, analysis = _analyze()

    processor.enable_fridge_magnet = False
    processor.enable_coating = False
    baseline = processor.build_mesh(
        analysis,
        thickness_mm=1.2,
        structure_mode="Single-sided",
    )
    baseline_board_volume = abs(float(baseline.geometry["Board"].volume))

    processor.enable_fridge_magnet = True
    processor.fridge_magnets = [_magnet()]
    processor.enable_coating = True
    processor.coating_height_mm = 0.08
    processor.enable_outline = True
    processor.outline_width_mm = 0.5
    single = processor.build_mesh(
        analysis,
        thickness_mm=1.2,
        structure_mode="Single-sided",
    )
    single_color_volumes = {
        name: abs(float(mesh.volume))
        for name, mesh in single.geometry.items()
        if name in analysis.slot_names
    }
    double = processor.build_mesh(
        analysis,
        thickness_mm=1.2,
        structure_mode="Double-sided",
    )

    assert {"Board", "Coating"}.issubset(single.geometry)
    assert abs(float(single.geometry["Board"].volume)) < baseline_board_volume
    assert len(single.geometry["Coating"].split(only_watertight=False)) == 1
    assert len(double.geometry["Coating"].split(only_watertight=False)) == 2
    assert all(mesh.is_watertight for mesh in single.geometry.values())
    assert all(mesh.is_watertight for mesh in double.geometry.values())
    for name, volume in single_color_volumes.items():
        assert abs(float(double.geometry[name].volume)) == pytest.approx(
            2.0 * volume,
            rel=1e-6,
        )

    domain = LayeredCoordinateDomain.from_metadata(
        double.metadata[LAYERED_COORDINATE_DOMAIN_KEY]
    )
    assert analysis.coordinate_domain == domain
    canvas_bounds = domain.writer_canvas_bounds_mm
    assert canvas_bounds[2] - canvas_bounds[0] == pytest.approx(
        40.0,
        abs=0.001,
    )
    assert canvas_bounds[3] - canvas_bounds[1] == pytest.approx(
        24.0,
        abs=0.001,
    )


def test_native_svg_build_mesh_retains_per_material_optical_volume() -> None:
    processor, analysis = _analyze("clip_inherited_fill.svg")
    processor.enable_fridge_magnet = False
    processor.enable_coating = False
    processor.enable_outline = False

    scene = processor.build_mesh(
        analysis,
        thickness_mm=1.2,
        structure_mode="Single-sided",
    )
    expected_by_slot = {name: 0.0 for name in analysis.slot_names}
    for item in analysis.matched_shapes:
        area_mm2 = item["geometry"].area * analysis.scale_factor**2
        for channel in set(item["recipe"]):
            expected_by_slot[analysis.slot_names[channel]] += (
                area_mm2 * processor.layer_height_mm * item["recipe"].count(channel)
            )
    expected_by_slot = {
        name: volume for name, volume in expected_by_slot.items() if volume > 0.0
    }
    actual_by_slot = {
        name: abs(float(scene.geometry[name].volume))
        for name in expected_by_slot
        if name in scene.geometry
    }

    assert actual_by_slot.keys() == expected_by_slot.keys()
    assert actual_by_slot == pytest.approx(expected_by_slot, rel=1e-6)
    assert all(scene.geometry[name].is_watertight for name in expected_by_slot)


def test_native_analysis_drives_outline_keychain_glb_and_cross_slicer_3mf(
    tmp_path: Path,
) -> None:
    pytest.importorskip("rasterio")
    processor, analysis = _analyze(
        "fill_rules_transforms.svg",
        target_width_mm=12.0,
    )
    preview_colors = _preview_colors_with_names(analysis)
    scene = processor.build_mesh(
        analysis,
        thickness_mm=0.8,
        structure_mode="Single-sided",
    )
    context = {
        "add_loop": True,
        "loop_width": 4.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_angle": 0.0,
        "loop_position": "top",
        "backing_color_id": 0,
        "spacer_thick": 0.8,
        "structure_mode": "Single-sided",
        "enable_coating": False,
    }
    assert _inject_vector_keychain_loop(
        context,
        scene,
        preview_colors,
        analysis.slot_names,
        vector_keychain_body(analysis),
        x_mirrored=True,
    )
    outline = _generate_vector_outline_mesh(
        analysis,
        0.5,
        preview_colors[0],
        analysis.slot_names[0],
        context,
        export_color_mode=processor.color_mode,
    )
    assert outline is not None and outline.is_watertight
    scene.add_geometry(outline, geom_name="Outline", node_name="Outline")
    preview_colors["Outline"] = preview_colors[0]

    assert scene.geometry["Keychain_Loop"].is_watertight
    assert scene.geometry["Keychain_Loop"].metadata[
        "bambu_material_name"
    ] in analysis.slot_names
    assert scene.geometry["Outline"].metadata[
        "bambu_material_name"
    ] in analysis.slot_names

    parts = build_vector_preview_parts_from_analysis(
        analysis=analysis,
        preview_colors=preview_colors,
        slot_list=list(analysis.slot_names),
        structure_mode="Single-sided",
        color_mode=processor.color_mode,
        thickness_mm=0.8,
        separate_backing=True,
        include_backing=True,
        include_outline=True,
        outline_width_mm=0.5,
    )
    assert {part.role for part in parts} == {"color", "backing", "outline"}
    glb_path = tmp_path / "native-workflow.glb"
    export_vector_glb_preview_v2(
        parts,
        output_path=str(glb_path),
        pixels_per_mm=1.0,
    )
    glb_scene = trimesh.load(glb_path, force="scene")
    assert {part.export_name for part in parts} == set(glb_scene.geometry)

    used_names = list(scene.geometry)
    for slicer in ("BambuStudio", "OrcaSlicer"):
        output_path = tmp_path / f"native-{slicer}.3mf"
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=str(output_path),
            slot_names=used_names,
            preview_colors=preview_colors,
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer=slicer,
            nozzle_size="0.4",
            project_slot_names=analysis.slot_names,
        )
        with zipfile.ZipFile(output_path) as package:
            names = set(package.namelist())
            assert "3D/3dmodel.model" in names
            assert "Metadata/project_settings.config" in names
            assert "Metadata/model_settings.config" in names
        assert set(used_names).issubset(_package_part_names(output_path))


def test_native_analysis_preserves_recipe_tiling_puzzle_and_material_metadata() -> None:
    solve_calls: list[list[tuple[int, int, int]]] = []

    class MaterialMatcher:
        lut_path = "material-archive-runtime"
        lut_rgb = PALETTE_RGB
        dynamic_layer_info = {"enabled": True, "max_layers": 6}
        material_solver_info = {"source": "material_archive", "base_channel_idx": 2}

        def solve_for_clipped_shapes(self, shapes, *, scale_factor):
            assert scale_factor > 0
            solve_calls.append([tuple(item["color"]) for item in shapes])

    processor, analysis = _analyze(matcher=MaterialMatcher())
    assert solve_calls and len(solve_calls[0]) == len(analysis.clipped_shapes)
    assert analysis.material_dynamic_layer_info == {
        "enabled": True,
        "max_layers": 6,
    }
    assert analysis.material_solver_info == {
        "source": "material_archive",
        "base_channel_idx": 2,
    }

    width_px = int(round(analysis.bbox[2] * analysis.scale_factor))
    height_px = int(round(analysis.bbox[3] * analysis.scale_factor))
    region_mask = np.ones((height_px, width_px), dtype=bool)
    apply_recipe_overrides_to_analysis(
        analysis,
        recipe_overrides=[
            {
                "region_id": "whole-document",
                "recipe": [3, 3, 3, 3, 3, 3],
                "layer_order": "Top2Bottom",
            }
        ],
        region_masks={"whole-document": region_mask},
        target_layers=6,
        base_channel_idx=2,
        pixels_per_mm=1.0,
    )
    assert analysis.num_layers == 6
    assert all(shape["recipe"] == [3, 3, 3, 3, 3, 3] for shape in analysis.matched_shapes)

    tiles = slice_vector_analysis_into_tiles(
        analysis=analysis,
        total_width_mm=40.0,
        total_height_mm=24.0,
        tile_width_mm=20.0,
        tile_height_mm=24.0,
    )
    assert [tile.label for tile in tiles] == ["R1C1", "R1C2"]
    assert all(tile.analysis.num_layers == 6 for tile in tiles)
    assert all(
        shape["recipe"] == [3, 3, 3, 3, 3, 3]
        for tile in tiles
        for shape in tile.analysis.matched_shapes
    )
    assert all(
        shape["geometry"].bounds[0] >= 0.0
        and shape["geometry"].bounds[2] <= 50.0 + 1e-9
        for tile in tiles
        for shape in tile.analysis.matched_shapes
    )

    _, puzzle_analysis = _analyze(
        "irregular_silhouette.svg",
        target_width_mm=12.0,
    )
    preview_cache = VectorProcessor.build_preview_cache(
        puzzle_analysis,
        pixels_per_mm=2.0,
        supersample_preview=1,
    )
    solid_mask = preview_cache["mask_solid"]
    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=solid_mask.shape[1],
            height_px=solid_mask.shape[0],
            total_width_mm=12.0,
            total_height_mm=8.0,
            style="regular",
            sizing_mode="grid",
            rows=2,
            cols=2,
            seed=7,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
            solid_mask=solid_mask,
        )
    )
    assert layout.layout_mode == "mask_aware"
    assert layout.pieces
    assert all(piece.polygon_px for piece in layout.pieces)
