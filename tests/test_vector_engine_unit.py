"""Unit tests for the Chroma-aligned vector engine (core/vector_engine.py).

Covers:
    1. Occlusion clipping: reverse-order accumulative difference
    2. Run-length extrusion: consecutive same-channel layers merged
    3. Output ordering: meshes_by_slot sorted by material ID
    4. Public API: analyze_svg, build_mesh, render_preview, svg_to_mesh backward compat
"""

import sys
import os
import types
import importlib.util
import inspect
from unittest.mock import patch

import pytest
import numpy as np
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from config import PrinterConfig

# Load vector_engine under a private test-only name to avoid the heavy
# core.__init__ import chain without replacing the canonical module used by
# other test files during collection.
_TEST_VECTOR_ENGINE_MODULE = "_lumina_test_vector_engine"
_spec = importlib.util.spec_from_file_location(
    _TEST_VECTOR_ENGINE_MODULE,
    os.path.join(_ROOT, "core", "vector_engine.py"),
)
_ve = importlib.util.module_from_spec(_spec)
# Provide a minimal 'core' parent package so relative imports resolve
if "core" not in sys.modules:
    _pkg = types.ModuleType("core")
    _pkg.__path__ = [os.path.join(_ROOT, "core")]
    sys.modules["core"] = _pkg
sys.modules[_TEST_VECTOR_ENGINE_MODULE] = _ve
_spec.loader.exec_module(_ve)
VectorProcessor = _ve.VectorProcessor
VectorAnalysis = _ve.VectorAnalysis


# =====================================================================
# Helpers
# =====================================================================


def _rect(x0, y0, x1, y1, color=(255, 0, 0)):
    """Create a shape_data dict compatible with _clip_occlusion input."""
    return {"poly": box(x0, y0, x1, y1), "color": color}


def _make_parse_only_processor(sampling_precision=0.05):
    """Create a VectorProcessor instance without running heavy __init__."""
    vp = object.__new__(VectorProcessor)
    vp.sampling_precision = sampling_precision
    vp.color_mode = "4-Color"
    vp.last_stage_timings = {}
    vp.parse_warnings = []
    vp.enable_fridge_magnet = False
    vp.fridge_magnets = []
    return vp


# =====================================================================
# 1. Occlusion clipping
# =====================================================================


class TestClipOcclusion:
    """Verify ChromaPrint3D-style reverse-order occlusion clipping."""

    def test_no_overlap_preserves_all(self):
        """Non-overlapping shapes should pass through unchanged."""
        shapes = [
            _rect(0, 0, 10, 10, color=(255, 0, 0)),
            _rect(20, 0, 30, 10, color=(0, 255, 0)),
        ]
        result = VectorProcessor._clip_occlusion(shapes)
        assert len(result) == 2
        for r in result:
            assert not r["geometry"].is_empty

    def test_later_shape_covers_earlier(self):
        """Later shape fully covering earlier → earlier completely removed."""
        shapes = [
            _rect(0, 0, 10, 10, color=(255, 0, 0)),  # bottom (draw order 0)
            _rect(0, 0, 10, 10, color=(0, 255, 0)),  # top    (draw order 1)
        ]
        result = VectorProcessor._clip_occlusion(shapes)
        top = [r for r in result if r["color"] == (0, 255, 0)]
        bottom = [r for r in result if r["color"] == (255, 0, 0)]
        assert len(top) == 1
        assert not top[0]["geometry"].is_empty
        assert len(bottom) == 0  # fully occluded

    def test_partial_overlap(self):
        """Partial overlap: earlier shape trimmed, later shape full."""
        shapes = [
            _rect(0, 0, 20, 10, color=(255, 0, 0)),  # bottom, wider
            _rect(5, 0, 15, 10, color=(0, 255, 0)),  # top, narrower overlap
        ]
        result = VectorProcessor._clip_occlusion(shapes)

        top = [r for r in result if r["color"] == (0, 255, 0)]
        bottom = [r for r in result if r["color"] == (255, 0, 0)]

        assert len(top) == 1
        assert len(bottom) == 1

        # Top shape should be fully preserved
        assert abs(top[0]["geometry"].area - 100.0) < 1e-6

        # Bottom shape should be trimmed: original 200 minus overlap 100
        assert abs(bottom[0]["geometry"].area - 100.0) < 1.0

    def test_draw_order_preserved(self):
        """Result list should be in original draw order (bottom → top)."""
        shapes = [
            _rect(0, 0, 10, 10, color=(1, 0, 0)),
            _rect(5, 0, 15, 10, color=(0, 1, 0)),
            _rect(10, 0, 20, 10, color=(0, 0, 1)),
        ]
        result = VectorProcessor._clip_occlusion(shapes)
        orders = [r["draw_order"] for r in result]
        assert orders == sorted(orders), "draw_order should be monotonically increasing"

    def test_empty_input(self):
        result = VectorProcessor._clip_occlusion([])
        assert result == []

    def test_return_silhouette_when_requested(self):
        """When requested, occlusion returns accumulated silhouette geometry."""
        shapes = [
            _rect(0, 0, 10, 10, color=(255, 0, 0)),
            _rect(5, 0, 15, 10, color=(0, 255, 0)),
        ]
        result, silhouette = VectorProcessor._clip_occlusion(shapes, return_silhouette=True)
        assert len(result) == 2
        assert silhouette is not None
        assert not silhouette.is_empty
        # silhouette is union of both input rectangles: 100 + 100 - 50 overlap
        assert abs(silhouette.area - 150.0) < 1e-6

    def test_three_stacked_shapes(self):
        """Three fully stacked shapes: only topmost survives."""
        shapes = [
            _rect(0, 0, 10, 10, color=(1, 0, 0)),
            _rect(0, 0, 10, 10, color=(0, 1, 0)),
            _rect(0, 0, 10, 10, color=(0, 0, 1)),
        ]
        result = VectorProcessor._clip_occlusion(shapes)
        assert len(result) == 1
        assert result[0]["color"] == (0, 0, 1)

    def test_no_small_feature_exemption(self):
        """Even tiny shapes are subject to occlusion — no special exemption."""
        shapes = [
            _rect(0, 0, 1, 1, color=(255, 0, 0)),  # tiny bottom
            _rect(0, 0, 100, 100, color=(0, 255, 0)),  # large top covering it
        ]
        result = VectorProcessor._clip_occlusion(shapes)
        reds = [r for r in result if r["color"] == (255, 0, 0)]
        assert len(reds) == 0, "small feature should be fully occluded"


# =====================================================================
# 2. Run-length extrusion
# =====================================================================


class TestRunLengthExtrude:
    """Verify consecutive same-channel layers are merged into single volumes."""

    LAYER_H = PrinterConfig.LAYER_HEIGHT  # 0.08
    SLOT_NAMES = ["White", "Cyan", "Magenta", "Yellow"]

    def _make_matched(self, geometry, recipe):
        return [{"geometry": geometry, "recipe": recipe, "color": (0, 0, 0)}]

    def test_single_channel_all_layers(self):
        """All 5 layers mapped to channel 1 → single run for channel 1."""
        geom = box(0, 0, 10, 10)
        matched = self._make_matched(geom, [1, 1, 1, 1, 1])

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=self.LAYER_H,
            num_channels=4,
            slot_names=self.SLOT_NAMES,
            scale_factor=1.0,
        )

        assert "Cyan" in result
        assert len(result["Cyan"]["meshes"]) == 1  # single merged volume

    def test_alternating_channels_stay_one_object_per_material(self):
        """Alternating runs remain distinct shells inside one material object."""
        geom = box(0, 0, 10, 10)
        matched = self._make_matched(geom, [0, 1, 0, 1, 0])

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=self.LAYER_H,
            num_channels=4,
            slot_names=self.SLOT_NAMES,
            scale_factor=1.0,
        )

        white_meshes = result.get("White", {}).get("meshes", [])
        cyan_meshes = result.get("Cyan", {}).get("meshes", [])
        assert len(white_meshes) == 1
        assert len(cyan_meshes) == 1
        assert len(white_meshes[0].split(only_watertight=False)) == 3
        assert len(cyan_meshes[0].split(only_watertight=False)) == 2

    def test_run_merges_consecutive(self):
        """Recipe [2,2,2,0,0] → channel 2 gets one run (layers 0-2),
        channel 0 gets one run (layers 3-4)."""
        geom = box(0, 0, 10, 10)
        matched = self._make_matched(geom, [2, 2, 2, 0, 0])

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=self.LAYER_H,
            num_channels=4,
            slot_names=self.SLOT_NAMES,
            scale_factor=1.0,
        )

        assert len(result["Magenta"]["meshes"]) == 1
        assert len(result["White"]["meshes"]) == 1

    def test_material_id_in_result(self):
        """Each slot entry should carry correct mat_id."""
        geom = box(0, 0, 5, 5)
        matched = self._make_matched(geom, [3, 3, 3, 3, 3])

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=self.LAYER_H,
            num_channels=4,
            slot_names=self.SLOT_NAMES,
            scale_factor=1.0,
        )

        assert result["Yellow"]["mat_id"] == 3

    def test_empty_geometry_skipped(self):
        """Empty geometry should produce no meshes."""
        geom = Polygon()
        matched = self._make_matched(geom, [0, 0, 0, 0, 0])

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=5,
            layer_h=self.LAYER_H,
            num_channels=4,
            slot_names=self.SLOT_NAMES,
            scale_factor=1.0,
        )

        assert len(result) == 0

    def test_five_color_air_padded_base_recipe_extrudes_full_faceup_height(self):
        """Solid 5-color base LUT rows use -1 padding but need solid layers."""
        geom = box(0, 0, 10, 10)
        vp = object.__new__(VectorProcessor)
        vp.img_processor = types.SimpleNamespace(
            lut_rgb=np.array([[255, 255, 255]], dtype=np.uint8),
            ref_stacks=np.array([[-1, 0, 0, 0, 0, 0]], dtype=np.int32),
        )

        with patch.object(VectorProcessor, "_match_lut_index_for_rgb", return_value=(0, 0.0)):
            matched = vp._match_colors(
                [{"geometry": geom, "color": (255, 255, 255)}],
                replacement_manager=None,
                num_channels=5,
                num_layers=6,
            )

        assert matched[0]["recipe"] == [0, 0, 0, 0, 0, 0]

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=6,
            layer_h=self.LAYER_H,
            num_channels=5,
            slot_names=["White", "Red", "Yellow", "Blue", "Black"],
            scale_factor=1.0,
            face_up=True,
            optical_z_base=0.24,
        )

        assert len(result["White"]["meshes"]) == 1
        z_min, z_max = result["White"]["meshes"][0].bounds[:, 2]
        assert z_min == pytest.approx(0.24)
        assert z_max == pytest.approx(0.24 + 6 * self.LAYER_H)

    def test_five_color_mixed_base_recipe_preserves_air_padding(self):
        """Mixed 5-color base LUT rows keep their documented leading air layer."""
        geom = box(0, 0, 10, 10)
        vp = object.__new__(VectorProcessor)
        vp.img_processor = types.SimpleNamespace(
            lut_rgb=np.array([[240, 230, 220]], dtype=np.uint8),
            ref_stacks=np.array([[-1, 0, 0, 0, 0, 1]], dtype=np.int32),
        )

        with patch.object(VectorProcessor, "_match_lut_index_for_rgb", return_value=(0, 0.0)):
            matched = vp._match_colors(
                [{"geometry": geom, "color": (240, 230, 220)}],
                replacement_manager=None,
                num_channels=5,
                num_layers=6,
            )

        assert matched[0]["recipe"] == [-1, 0, 0, 0, 0, 1]

        result = VectorProcessor._run_length_extrude(
            matched,
            num_layers=6,
            layer_h=self.LAYER_H,
            num_channels=5,
            slot_names=["White", "Red", "Yellow", "Blue", "Black"],
            scale_factor=1.0,
            face_up=True,
            optical_z_base=0.24,
        )

        assert len(result["Red"]["meshes"]) == 1
        red_z_min, red_z_max = result["Red"]["meshes"][0].bounds[:, 2]
        assert red_z_min == pytest.approx(0.24)
        assert red_z_max == pytest.approx(0.24 + self.LAYER_H)

        assert len(result["White"]["meshes"]) == 1
        white_z_min, white_z_max = result["White"]["meshes"][0].bounds[:, 2]
        assert white_z_min == pytest.approx(0.24 + self.LAYER_H)
        assert white_z_max == pytest.approx(0.24 + 5 * self.LAYER_H)


# =====================================================================
# 3. Output ordering
# =====================================================================


class TestOutputOrdering:
    """Verify meshes_by_slot is sorted by material ID when assembling scene."""

    def test_sorted_by_mat_id(self):
        """Simulated meshes_by_slot should sort by mat_id."""
        meshes_by_slot = {
            "Yellow": {"meshes": ["m"], "mat_id": 3},
            "White": {"meshes": ["m"], "mat_id": 0},
            "Cyan": {"meshes": ["m"], "mat_id": 1},
        }
        sorted_items = sorted(meshes_by_slot.items(), key=lambda x: x[1]["mat_id"])
        names = [name for name, _ in sorted_items]
        assert names == ["White", "Cyan", "Yellow"]


# =====================================================================
# 5. Fridge magnet cavity helpers
# =====================================================================


class TestFridgeMagnetCavityHelpers:

    def test_centered_mm_to_vector_coords_uses_bbox_and_flips_y(self):
        x, y = VectorProcessor._centered_mm_to_vector_coords(
            center_x_mm=10.0,
            center_y_mm=-5.0,
            bbox=(0.0, 0.0, 40.0, 20.0),
            scale_factor=2.0,
        )

        assert x == pytest.approx(25.0)
        assert y == pytest.approx(12.5)

    def test_build_backing_cavity_slabs_keeps_blind_shell_for_high_outer_side(self):
        backing = box(0, 0, 20, 10)
        cavity = box(8, 3, 12, 7)

        slabs = VectorProcessor._build_backing_cavity_slabs(
            backing_sil=backing,
            backing_z_start=1.0,
            backing_height=2.0,
            cavity_specs=[{"geometry": cavity, "depth_mm": 0.8}],
            outer_side="high",
            shell_thickness_mm=0.4,
        )

        assert [(round(s["z_offset"], 3), round(s["height"], 3)) for s in slabs] == [
            (1.0, 0.8),
            (1.8, 0.8),
            (2.6, 0.4),
        ]
        assert slabs[0]["geometry"].area == pytest.approx(backing.area)
        assert slabs[1]["geometry"].area < backing.area
        assert slabs[2]["geometry"].area == pytest.approx(backing.area)

    def test_build_backing_cavity_slabs_splits_multiple_cavity_depth_bands(self):
        backing = box(0, 0, 20, 10)
        shallow = box(2, 2, 6, 6)
        deep = box(12, 2, 18, 8)

        slabs = VectorProcessor._build_backing_cavity_slabs(
            backing_sil=backing,
            backing_z_start=0.0,
            backing_height=2.0,
            cavity_specs=[
                {"geometry": shallow, "depth_mm": 0.8},
                {"geometry": deep, "depth_mm": 1.2},
            ],
            outer_side="high",
            shell_thickness_mm=0.4,
        )

        reduced_slabs = [slab for slab in slabs if slab["geometry"].area < backing.area]
        assert len(reduced_slabs) == 2
        reduced_areas = [slab["geometry"].area for slab in reduced_slabs]
        assert reduced_areas == pytest.approx(
            [
                backing.difference(deep).area,
                backing.difference(shallow.union(deep)).area,
            ]
        )

    def test_build_vector_fridge_cavity_specs_centers_on_backing_bounds_not_svg_viewbox(self):
        backing = box(5, 5, 15, 15)

        specs = VectorProcessor._build_vector_fridge_cavity_specs(
            backing_sil=backing,
            fridge_magnets=[
                {
                    "id": "magnet-round",
                    "shape": "round",
                    "preset_key": "round-4",
                    "diameter_mm": 4.0,
                    "width_mm": None,
                    "height_mm": None,
                    "thickness_mm": 1.2,
                    "center_x_mm": 0.0,
                    "center_y_mm": 0.0,
                }
            ],
            bbox=(0.0, 0.0, 40.0, 20.0),
            scale_factor=1.0,
            backing_height=2.0,
        )

        assert len(specs) == 1
        assert specs[0]["geometry"].centroid.x == pytest.approx(10.0)
        assert specs[0]["geometry"].centroid.y == pytest.approx(10.0)


class TestVectorPublicApiCompatibility:

    def test_build_mesh_signature_remains_backward_compatible(self):
        params = inspect.signature(VectorProcessor.build_mesh).parameters
        assert list(params) == [
            "self",
            "analysis",
            "thickness_mm",
            "structure_mode",
            "progress_fn",
            "backing_color_id",
            "enable_relief",
            "height_mode",
            "color_height_map",
            "heightmap_path",
            "heightmap_max_height",
        ]
        assert params["backing_color_id"].default == 0
        assert params["enable_relief"].default is False
        assert params["height_mode"].default == "color"

    def test_svg_to_mesh_signature_remains_backward_compatible(self):
        params = inspect.signature(VectorProcessor.svg_to_mesh).parameters
        assert list(params) == [
            "self",
            "svg_path",
            "target_width_mm",
            "thickness_mm",
            "structure_mode",
            "color_replacements",
            "progress_fn",
        ]

    def test_build_mesh_uses_processor_layer_height_override(self):
        processor = _make_parse_only_processor()
        processor.layer_height_mm = 0.12
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[
                {
                    "geometry": box(0, 0, 10, 10),
                    "color": (255, 0, 0),
                    "draw_order": 0,
                }
            ],
            matched_shapes=[
                {
                    "geometry": box(0, 0, 10, 10),
                    "recipe": [1, 1, 1, 1, 1],
                    "color": (255, 0, 0),
                }
            ],
            silhouette=box(0, 0, 10, 10),
            scale_factor=1.0,
            bbox=(0.0, 0.0, 10.0, 10.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={
                0: [255, 255, 255, 255],
                1: [0, 255, 255, 255],
            },
            stage_timings={},
        )

        scene = processor.build_mesh(
            analysis=analysis,
            thickness_mm=0.0,
            structure_mode="Single-sided",
        )

        assert scene.geometry["Cyan"].extents[2] == pytest.approx(0.6)


class TestVectorFridgeMagnetBuildMeshRegression:

    def test_build_mesh_reduces_board_volume_when_fridge_magnet_mode_enabled(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "4-Color"
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[{"geometry": box(0, 0, 20, 20), "color": (255, 0, 0), "draw_order": 0}],
            matched_shapes=[{"geometry": box(0, 0, 20, 20), "recipe": [1, 1, 1, 1, 1], "color": (255, 0, 0)}],
            silhouette=box(0, 0, 20, 20),
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
        )

        processor.enable_fridge_magnet = False
        processor.fridge_magnets = []
        scene_without_cavity = processor.build_mesh(analysis=analysis, thickness_mm=1.2, structure_mode="Single-sided")
        board_without_cavity = scene_without_cavity.geometry["Board"]

        processor.enable_fridge_magnet = True
        processor.fridge_magnets = [
            {
                "id": "magnet-round",
                "shape": "round",
                "preset_key": "round-8",
                "diameter_mm": 8.0,
                "width_mm": None,
                "height_mm": None,
                "thickness_mm": 0.4,
                "center_x_mm": 0.0,
                "center_y_mm": 0.0,
            }
        ]
        scene_with_cavity = processor.build_mesh(analysis=analysis, thickness_mm=1.2, structure_mode="Single-sided")
        board_with_cavity = scene_with_cavity.geometry["Board"]

        assert board_with_cavity.volume < board_without_cavity.volume
        assert board_with_cavity.bounds[0][0] == pytest.approx(board_without_cavity.bounds[0][0])
        assert board_with_cavity.bounds[1][0] == pytest.approx(board_without_cavity.bounds[1][0])

    @pytest.mark.parametrize(
        ("magnet", "expected_footprint_area"),
        [
            (
                {
                    "id": "magnet-round",
                    "shape": "round",
                    "preset_key": "round-8",
                    "diameter_mm": 8.0,
                    "width_mm": None,
                    "height_mm": None,
                    "thickness_mm": 0.4,
                    "center_x_mm": 3.0,
                    "center_y_mm": -2.0,
                },
                Point(0, 0).buffer(4.0, resolution=32).area,
            ),
            (
                {
                    "id": "magnet-rect",
                    "shape": "rect",
                    "preset_key": "rect-custom",
                    "diameter_mm": None,
                    "width_mm": 6.0,
                    "height_mm": 4.0,
                    "thickness_mm": 0.4,
                    "center_x_mm": -3.0,
                    "center_y_mm": 2.0,
                },
                24.0,
            ),
        ],
    )
    def test_relief_build_mesh_preserves_fridge_cavity_geometry(
        self,
        magnet,
        expected_footprint_area,
    ):
        """Relief changes backing height without dropping cavity settings."""
        processor = _make_parse_only_processor()
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[
                {
                    "geometry": box(0, 0, 20, 20),
                    "color": (255, 0, 0),
                    "draw_order": 0,
                }
            ],
            matched_shapes=[
                {
                    "geometry": box(0, 0, 20, 20),
                    "recipe": [1, 1, 1, 1, 1],
                    "color": (255, 0, 0),
                }
            ],
            silhouette=box(0, 0, 20, 20),
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={
                0: [255, 255, 255, 255],
                1: [0, 255, 255, 255],
            },
            stage_timings={},
        )

        processor.enable_fridge_magnet = False
        board_without_cavity = processor.build_mesh(
            analysis=analysis,
            thickness_mm=1.2,
            structure_mode="Single-sided",
            enable_relief=True,
        ).geometry["Board"]

        processor.enable_fridge_magnet = True
        processor.fridge_magnets = [magnet]
        board_with_cavity = processor.build_mesh(
            analysis=analysis,
            thickness_mm=1.2,
            structure_mode="Single-sided",
            enable_relief=True,
        ).geometry["Board"]

        assert board_without_cavity.volume == pytest.approx(480.0)
        assert board_with_cavity.volume == pytest.approx(
            board_without_cavity.volume - expected_footprint_area * magnet["thickness_mm"],
            abs=1e-3,
        )
        assert board_with_cavity.bounds[0][2] == pytest.approx(0.0)
        assert board_with_cavity.bounds[1][2] == pytest.approx(1.2)

    def test_relief_cavity_uses_global_xy_origin_and_non_optical_z_side(self):
        """Variable backing groups share one footprint and open away from optics."""
        processor = _make_parse_only_processor()
        processor.enable_fridge_magnet = True
        processor.fridge_magnets = [
            {
                "id": "offset-round",
                "shape": "round",
                "diameter_mm": 4.0,
                "thickness_mm": 0.4,
                "center_x_mm": 3.0,
                "center_y_mm": -2.0,
            }
        ]
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[
                {
                    "geometry": box(0, 0, 13, 20),
                    "recipe": [1, 1, 1, 1, 1],
                    "color": (255, 0, 0),
                },
                {
                    "geometry": box(13, 0, 20, 20),
                    "recipe": [1, 1, 1, 1, 1],
                    "color": (0, 255, 0),
                },
            ],
            silhouette=box(0, 0, 20, 20),
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
        )

        original_specs = VectorProcessor._build_vector_fridge_cavity_specs
        original_slabs = VectorProcessor._build_backing_cavity_slabs
        specs_calls = []
        slab_calls = []

        def _capture_specs(*args, **kwargs):
            result = original_specs(*args, **kwargs)
            specs_calls.append((kwargs, result))
            return result

        def _capture_slabs(*args, **kwargs):
            result = original_slabs(*args, **kwargs)
            slab_calls.append((kwargs, result))
            return result

        with (
            patch.object(
                VectorProcessor,
                "_build_vector_fridge_cavity_specs",
                side_effect=_capture_specs,
            ),
            patch.object(
                VectorProcessor,
                "_build_backing_cavity_slabs",
                side_effect=_capture_slabs,
            ),
        ):
            processor.build_mesh(
                analysis=analysis,
                thickness_mm=1.2,
                structure_mode="Single-sided",
                enable_relief=True,
                color_height_map={"#ff0000": 1.6, "#00ff00": 2.4},
            )

        assert len(specs_calls) == 1
        specs_kwargs, cavity_specs = specs_calls[0]
        assert specs_kwargs["backing_sil"].bounds == pytest.approx((0.0, 0.0, 20.0, 20.0))
        assert len(cavity_specs) == 1
        assert cavity_specs[0]["geometry"].centroid.x == pytest.approx(13.0)
        assert cavity_specs[0]["geometry"].centroid.y == pytest.approx(12.0)

        affected_calls = [
            (kwargs, slabs)
            for kwargs, slabs in slab_calls
            if kwargs["cavity_specs"]
        ]
        assert len(affected_calls) == 2
        clipped_footprints = sorted(
            [kwargs["cavity_specs"][0]["geometry"] for kwargs, _ in affected_calls],
            key=lambda geometry: geometry.bounds[0],
        )
        assert clipped_footprints[0].bounds == pytest.approx(
            (11.0, 10.0, 13.0, 14.0)
        )
        assert clipped_footprints[1].bounds == pytest.approx(
            (13.0, 10.0, 15.0, 14.0)
        )
        reassembled_footprint = unary_union(clipped_footprints)
        assert reassembled_footprint.symmetric_difference(
            cavity_specs[0]["geometry"]
        ).area == pytest.approx(0.0, abs=1e-9)
        assert reassembled_footprint.centroid.x == pytest.approx(13.0)
        assert reassembled_footprint.centroid.y == pytest.approx(12.0)

        for slab_kwargs, slabs in affected_calls:
            assert slab_kwargs["outer_side"] == "low"
            footprint_probe = slab_kwargs["cavity_specs"][0][
                "geometry"
            ].representative_point()
            outer_shell = next(
                slab for slab in slabs if slab["kind"] == "outer_shell"
            )
            cavity_band = next(
                slab for slab in slabs if slab["kind"] == "cavity_band"
            )
            inner_backing = next(
                slab for slab in slabs if slab["kind"] == "inner_backing"
            )
            assert outer_shell["z_offset"] == pytest.approx(0.0)
            assert outer_shell["height"] == pytest.approx(0.4)
            assert cavity_band["z_offset"] == pytest.approx(0.4)
            assert cavity_band["height"] == pytest.approx(0.4)
            assert not cavity_band["geometry"].contains(footprint_probe)
            assert inner_backing["z_offset"] == pytest.approx(0.8)
            assert inner_backing["geometry"].contains(footprint_probe)


class TestVectorBackingColorIdRegression:
    """Regression: ``build_mesh(backing_color_id=N)`` must colour Board via slot N.

    Historically the Board geometry was hardcoded to ``mat_id=0``, which made
    the Material Archive / 耗材管理 mode's "底板颜色" selector a visual no-op —
    the backing always inherited the first palette entry regardless of the
    user's choice. The fix threads ``backing_color_id`` through both
    ``VectorProcessor.build_mesh`` and the pipeline's post-processing so the
    selected slot actually drives the exported material id and preview colour.

    历史上 Board 的 ``mat_id`` 硬编码为 0，导致耗材管理模式下用户选择的
    「底板颜色」始终被忽略，底板只会取第一条耗材。此回归保证 ``backing_color_id``
    真正贯穿 ``build_mesh`` 与后续流程。
    """

    def _make_analysis(self):
        return VectorAnalysis(
            shape_data=[],
            clipped_shapes=[
                {"geometry": box(0, 0, 20, 20), "color": (255, 0, 0), "draw_order": 0}
            ],
            matched_shapes=[
                {"geometry": box(0, 0, 20, 20), "recipe": [1, 1, 1, 1, 1], "color": (255, 0, 0)}
            ],
            silhouette=box(0, 0, 20, 20),
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Cyan", "Magenta"],
            num_channels=3,
            num_layers=5,
            preview_colors={
                0: [255, 255, 255, 255],
                1: [0, 255, 255, 255],
                2: [255, 0, 255, 255],
            },
            stage_timings={},
        )

    def test_board_inherits_default_slot_zero_when_backing_color_id_omitted(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "4-Color"

        scene = processor.build_mesh(
            analysis=self._make_analysis(),
            thickness_mm=1.2,
            structure_mode="Single-sided",
        )

        board = scene.geometry["Board"]
        assert list(board.visual.face_colors[0]) == [255, 255, 255, 255]

    def test_board_uses_requested_backing_color_id(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "4-Color"

        scene = processor.build_mesh(
            analysis=self._make_analysis(),
            thickness_mm=1.2,
            structure_mode="Single-sided",
            backing_color_id=2,
        )

        board = scene.geometry["Board"]
        assert list(board.visual.face_colors[0]) == [255, 0, 255, 255]

    def test_board_clamps_out_of_range_backing_color_id_to_zero(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "4-Color"

        scene = processor.build_mesh(
            analysis=self._make_analysis(),
            thickness_mm=1.2,
            structure_mode="Single-sided",
            backing_color_id=42,
        )

        board = scene.geometry["Board"]
        assert list(board.visual.face_colors[0]) == [255, 255, 255, 255]


class TestVectorPreviewBackingMaskRegression:
    """Preview cache must preserve the backing footprint used by build_mesh."""

    def test_preview_cache_backing_mask_excludes_transparent_canvas(self):
        visible_shape = box(4, 4, 16, 16)
        full_backing = box(0, 0, 20, 20)
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[
                {"geometry": visible_shape, "color": (255, 0, 0), "draw_order": 0}
            ],
            matched_shapes=[
                {
                    "geometry": visible_shape,
                    "recipe": [1, 1, 1, 1, 1],
                    "color": (255, 0, 0),
                    "matched_rgb": (255, 0, 0),
                }
            ],
            silhouette=visible_shape,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Red"],
            num_channels=2,
            num_layers=5,
            preview_colors={
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
            },
            stage_timings={},
            image_vectorizer_bounds=full_backing,
        )

        cache = VectorProcessor.build_preview_cache(analysis, pixels_per_mm=10.0)

        assert "backing_mask" in cache
        assert cache["backing_mask"].shape == cache["mask_solid"].shape
        assert cache["backing_mask"][100, 100]
        assert not cache["backing_mask"][10, 10]

    def test_preview_cache_rasterizes_shape_masks_without_full_canvas_allocations(self, monkeypatch):
        shape_a = box(2, 2, 8, 8)
        shape_b = box(20, 2, 26, 8)
        shape_c = box(2, 20, 8, 26)
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[
                {"geometry": shape_a, "color": (255, 0, 0), "draw_order": 0},
                {"geometry": shape_b, "color": (0, 255, 0), "draw_order": 1},
                {"geometry": shape_c, "color": (0, 0, 255), "draw_order": 2},
            ],
            matched_shapes=[
                {
                    "geometry": shape_a,
                    "recipe": [1, 1, 1, 1, 1],
                    "color": (255, 0, 0),
                    "matched_rgb": (255, 0, 0),
                },
                {
                    "geometry": shape_b,
                    "recipe": [2, 2, 2, 2, 2],
                    "color": (0, 255, 0),
                    "matched_rgb": (0, 255, 0),
                },
                {
                    "geometry": shape_c,
                    "recipe": [3, 3, 3, 3, 3],
                    "color": (0, 0, 255),
                    "matched_rgb": (0, 0, 255),
                },
            ],
            silhouette=shape_a.union(shape_b).union(shape_c),
            scale_factor=1.0,
            bbox=(0.0, 0.0, 40.0, 40.0),
            color_conf={},
            slot_names=["White", "Red", "Green", "Blue"],
            num_channels=4,
            num_layers=5,
            preview_colors={
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
                2: [0, 255, 0, 255],
                3: [0, 0, 255, 255],
            },
            stage_timings={},
        )
        original_zeros = _ve.np.zeros
        full_bool_allocations = []

        def spy_zeros(shape, *args, **kwargs):
            dtype = kwargs.get("dtype")
            if dtype is None and args:
                dtype = args[0]
            if tuple(shape) == (40, 40) and dtype is bool:
                full_bool_allocations.append(shape)
            return original_zeros(shape, *args, **kwargs)

        monkeypatch.setattr(_ve.np, "zeros", spy_zeros)

        cache = VectorProcessor.build_preview_cache(
            analysis,
            pixels_per_mm=1.0,
            supersample_preview=1,
        )

        assert np.count_nonzero(cache["mask_solid"]) > 0
        assert int(cache["material_matrix"][3, 3, 0]) == 1
        assert int(cache["material_matrix"][3, 23, 0]) == 2
        assert int(cache["material_matrix"][23, 3, 0]) == 3
        assert len(full_bool_allocations) <= 2

    def test_preview_cache_uses_compact_signed_material_matrix_dtype(self):
        shape = box(0, 0, 10, 10)
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[
                {"geometry": shape, "color": (255, 0, 0), "draw_order": 0}
            ],
            matched_shapes=[
                {
                    "geometry": shape,
                    "recipe": [-1, 0, 1, 7],
                    "color": (255, 0, 0),
                    "matched_rgb": (255, 0, 0),
                }
            ],
            silhouette=shape,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 10.0, 10.0),
            color_conf={},
            slot_names=[
                "Air",
                "White",
                "Red",
                "Green",
                "Blue",
                "Yellow",
                "Cyan",
                "Black",
            ],
            num_channels=8,
            num_layers=4,
            preview_colors={},
            stage_timings={},
        )

        cache = VectorProcessor.build_preview_cache(
            analysis,
            pixels_per_mm=1.0,
            supersample_preview=1,
        )

        assert cache["material_matrix"].dtype == np.dtype(np.int8)
        np.testing.assert_array_equal(
            cache["material_matrix"][1, 1],
            np.asarray([-1, 0, 1, 7], dtype=np.int8),
        )

    def test_preview_cache_promotes_material_matrix_dtype_for_large_indices(self):
        shape = box(0, 0, 10, 10)
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[
                {"geometry": shape, "color": (255, 0, 0), "draw_order": 0}
            ],
            matched_shapes=[
                {
                    "geometry": shape,
                    "recipe": [0, 128],
                    "color": (255, 0, 0),
                    "matched_rgb": (255, 0, 0),
                }
            ],
            silhouette=shape,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 10.0, 10.0),
            color_conf={},
            slot_names=["0", "128"],
            num_channels=129,
            num_layers=2,
            preview_colors={},
            stage_timings={},
        )

        cache = VectorProcessor.build_preview_cache(
            analysis,
            pixels_per_mm=1.0,
            supersample_preview=1,
        )

        assert cache["material_matrix"].dtype == np.dtype(np.int16)
        np.testing.assert_array_equal(
            cache["material_matrix"][1, 1],
            np.asarray([0, 128], dtype=np.int16),
        )


class TestVectorCoatingBuildMeshRegression:

    def test_build_mesh_adds_coating_when_enabled(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "4-Color"
        processor.enable_coating = True
        processor.coating_height_mm = PrinterConfig.LAYER_HEIGHT * 2
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[{"geometry": box(0, 0, 20, 20), "color": (255, 0, 0), "draw_order": 0}],
            matched_shapes=[{"geometry": box(0, 0, 20, 20), "recipe": [1, 1, 1, 1, 1], "color": (255, 0, 0)}],
            silhouette=box(0, 0, 20, 20),
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
        )

        scene = processor.build_mesh(analysis=analysis, thickness_mm=1.2, structure_mode="Single-sided")
        coating = scene.geometry["Coating"]

        assert "Coating" in scene.geometry
        assert coating.bounds[0][2] == pytest.approx(-PrinterConfig.LAYER_HEIGHT * 2)
        assert coating.bounds[1][2] == pytest.approx(0.0)
        assert analysis.preview_colors["Coating"] == [200, 200, 200, 80]

    def test_build_mesh_adds_coating_to_both_double_sided_faces(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "4-Color"
        processor.layer_height_mm = 0.10
        processor.enable_coating = True
        processor.coating_height_mm = processor.layer_height_mm * 2
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[
                {
                    "geometry": box(0, 0, 20, 20),
                    "color": (255, 0, 0),
                    "draw_order": 0,
                },
            ],
            matched_shapes=[
                {
                    "geometry": box(0, 0, 20, 20),
                    "recipe": [1, 1, 1, 1, 1],
                    "color": (255, 0, 0),
                },
            ],
            silhouette=box(0, 0, 20, 20),
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={
                0: [255, 255, 255, 255],
                1: [0, 255, 255, 255],
            },
            stage_timings={},
        )

        thickness_mm = 1.2
        scene = processor.build_mesh(
            analysis=analysis,
            thickness_mm=thickness_mm,
            structure_mode="Double-sided",
        )
        coating = scene.geometry["Coating"]
        coating_height = processor.layer_height_mm * 2
        expected_top = (
            thickness_mm
            + analysis.num_layers * processor.layer_height_mm * 2
            + coating_height
        )

        assert len(coating.split(only_watertight=False)) == 2
        assert coating.bounds[0][2] == pytest.approx(-coating_height)
        assert coating.bounds[1][2] == pytest.approx(expected_top)

    def test_image_vectorizer_bounds_do_not_fill_transparent_board_or_coating(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "4-Color"
        processor.enable_coating = True
        left = box(0, 0, 4, 20)
        right = box(16, 0, 20, 20)
        visible_silhouette = left.union(right)
        full_bounds = box(0, 0, 20, 20)
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[
                {"geometry": left, "color": (255, 0, 0), "draw_order": 0},
                {"geometry": right, "color": (0, 255, 255), "draw_order": 1},
            ],
            matched_shapes=[
                {"geometry": left, "recipe": [1, 1, 1, 1, 1], "color": (255, 0, 0)},
                {"geometry": right, "recipe": [1, 1, 1, 1, 1], "color": (0, 255, 255)},
            ],
            silhouette=visible_silhouette,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
            image_vectorizer_bounds=full_bounds,
        )

        scene = processor.build_mesh(
            analysis=analysis,
            thickness_mm=1.2,
            structure_mode="Single-sided",
        )
        board = scene.geometry["Board"]
        coating = scene.geometry["Coating"]

        assert len(board.split(only_watertight=False)) == 2
        assert len(coating.split(only_watertight=False)) == 2
        assert board.volume < 250.0
        assert coating.volume < 25.0

    def test_regular_svg_keeps_visible_silhouette_for_board(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "4-Color"
        left = box(0, 0, 4, 20)
        right = box(16, 0, 20, 20)
        visible_silhouette = left.union(right)
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[
                {"geometry": left, "color": (255, 0, 0), "draw_order": 0},
                {"geometry": right, "color": (0, 255, 255), "draw_order": 1},
            ],
            matched_shapes=[
                {"geometry": left, "recipe": [1, 1, 1, 1, 1], "color": (255, 0, 0)},
                {"geometry": right, "recipe": [1, 1, 1, 1, 1], "color": (0, 255, 255)},
            ],
            silhouette=visible_silhouette,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
        )

        scene = processor.build_mesh(analysis=analysis, thickness_mm=1.2, structure_mode="Single-sided")
        board = scene.geometry["Board"]

        assert board.volume < 250


class TestVectorSingleSidedMirrorRegression:

    @pytest.mark.parametrize(
        ("color_mode", "structure_mode", "height_mode", "mirror_x"),
        [
            ("Material Archive", "Single-sided", "color", False),
            ("Material Archive", "Single-sided", "heightmap", False),
            ("4-Color", "单面", "color", False),
            ("Material Archive", "Single-sided", None, True),
            ("5-Color Extended", "Single-sided", None, False),
            ("4-Color", "Double-sided", None, False),
        ],
    )
    def test_outline_surrounds_body_in_the_same_export_coordinates(
        self, tmp_path, color_mode, structure_mode, height_mode, mirror_x
    ):
        from PIL import Image
        from shapely import affinity
        from shapely.ops import unary_union
        from core.pipeline.vector_branch import _generate_vector_outline_mesh

        processor = _make_parse_only_processor()
        processor.color_mode = color_mode
        # Offset and asymmetry expose both accidental translation and mirroring.
        shape = Polygon([(2, 3), (18, 3), (18, 9), (8, 9), (8, 17), (2, 17)])
        layers = 6 if color_mode == "5-Color Extended" else 5
        records = [{"geometry": shape, "recipe": [1] * layers, "color": (0, 255, 255)}]
        analysis = VectorAnalysis(
            shape_data=records,
            clipped_shapes=records,
            matched_shapes=records,
            silhouette=shape,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 20.0, 20.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=layers,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
        )
        relief_options = {}
        if height_mode is not None:
            relief_options = {"enable_relief": True, "height_mode": height_mode}
        if height_mode == "heightmap":
            heightmap = tmp_path / "heightmap.png"
            Image.fromarray(np.arange(64, dtype=np.uint8).reshape(8, 8) * 4).save(heightmap)
            relief_options.update(heightmap_path=str(heightmap), heightmap_max_height=3.0)
        scene = processor.build_mesh(
            analysis=analysis,
            thickness_mm=1.2,
            structure_mode=structure_mode,
            **relief_options,
        )
        outline = _generate_vector_outline_mesh(
            analysis, 1.0, [255, 255, 255, 255], "White",
            {
                "structure_mode": structure_mode,
                "spacer_thick": 1.2,
                "color_mode": "5-Color Extended",
                **relief_options,
            },
            export_color_mode=color_mode,
        )
        assert outline is not None

        def footprint(mesh):
            triangles = np.asarray(mesh.triangles)[:, :, :2]
            polygons = [Polygon(triangle) for triangle in triangles]
            return unary_union([polygon for polygon in polygons if polygon.area > 1e-10])

        expected = affinity.scale(shape, xfact=-1 if mirror_x else 1, yfact=-1, origin=(0, 0))
        body = footprint(scene.geometry["Cyan"])
        assert body.symmetric_difference(expected).area < 1e-6
        assert expected.difference(footprint(scene.geometry["Board"])).area < 1e-6
        ring = footprint(outline)
        ring_parts = tuple(ring.geoms) if ring.geom_type == "MultiPolygon" else (ring,)
        envelope = unary_union([Polygon(part.exterior) for part in ring_parts])
        assert body.difference(envelope).area < 1e-6
        assert np.max(scene.bounds[:, 0]) - np.min(scene.bounds[:, 0]) < 20

    def test_build_mesh_mirrors_non_5color_without_vertex_translation(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "8-Color Max"
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[{"geometry": box(0, 0, 4, 10), "recipe": [1, 1, 1, 1, 1], "color": (0, 255, 255)}],
            silhouette=None,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 10.0, 10.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=5,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
        )

        scene = processor.build_mesh(analysis=analysis, thickness_mm=0.0, structure_mode="Single-sided")
        bounds = scene.geometry["Cyan"].bounds

        # The X sign flip preserves viewing orientation.  Placement is kept
        # out of vertex coordinates and emitted as a 3MF build transform.
        assert bounds[0][0] == pytest.approx(-4.0)
        assert bounds[1][0] == pytest.approx(0.0)

    def test_build_mesh_does_not_mirror_5color_single_sided_x_coordinates(self):
        processor = _make_parse_only_processor()
        processor.color_mode = "5-Color Extended"
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[{"geometry": box(0, 0, 4, 10), "recipe": [1, 1, 1, 1, 1, 1], "color": (0, 255, 255)}],
            silhouette=None,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 10.0, 10.0),
            color_conf={},
            slot_names=["White", "Cyan"],
            num_channels=2,
            num_layers=6,
            preview_colors={0: [255, 255, 255, 255], 1: [0, 255, 255, 255]},
            stage_timings={},
        )

        scene = processor.build_mesh(analysis=analysis, thickness_mm=0.0, structure_mode="Single-sided")
        bounds = scene.geometry["Cyan"].bounds

        assert bounds[0][0] == pytest.approx(0.0)
        assert bounds[1][0] == pytest.approx(4.0)


# =====================================================================
# 5. SVG parse regression (multi-subpath)
# =====================================================================


class TestParseSvgSubpaths:
    def test_nested_svg_rotation_transform_reaches_vector_geometry(self, tmp_path):
        """Rotated SVG files generated by the frontend must affect vector geometry."""
        svg_file = tmp_path / "rotated_nested.svg"
        svg_file.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 80">\n'
                '  <g transform="translate(40 0) rotate(90)">\n'
                '    <svg x="0" y="0" width="80" height="40" viewBox="0 0 80 40" preserveAspectRatio="none">\n'
                '      <rect x="0" y="0" width="80" height="40" fill="#ff0000"/>\n'
                "    </svg>\n"
                "  </g>\n"
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, _scale, bbox = vp._parse_svg(str(svg_file), target_width_mm=40.0)

        assert len(shapes) == 1
        min_x, min_y, max_x, max_y = shapes[0]["poly"].bounds
        assert min_x == pytest.approx(0.0, abs=0.1)
        assert min_y == pytest.approx(0.0, abs=0.1)
        assert max_x == pytest.approx(40.0, abs=0.1)
        assert max_y == pytest.approx(80.0, abs=0.1)
        assert bbox[2] == pytest.approx(40.0, abs=0.1)
        assert bbox[3] == pytest.approx(80.0, abs=0.1)

    def test_split_multi_subpath_path_into_multiple_polygons(self, tmp_path):
        """Single <path> with two non-overlapping subpaths: _parse_svg
        returns 1 MultiPolygon; splitting happens post-clip in svg_to_mesh."""
        svg_file = tmp_path / "multi_subpath.svg"
        svg_file.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 120">\n'
                '  <path fill="#ff0000" d="'
                "M0,0 L100,0 L100,100 L0,100 Z "
                'M200,0 L300,0 L300,100 L200,100 Z"/>\n'
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, scale, bbox = vp._parse_svg(str(svg_file), target_width_mm=100.0)

        assert len(shapes) == 1
        total_area = sum(s["poly"].area for s in shapes)
        assert abs(total_area - 20000.0) < 100.0
        assert all(s["color"] == (255, 0, 0) for s in shapes)
        assert scale > 0
        assert bbox[2] > 0

    def test_parse_falls_back_when_subpath_split_unavailable(self, tmp_path):
        """If as_subpaths fails, parser should still sample whole path."""
        svg_file = tmp_path / "fallback.svg"
        svg_file.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">\n'
                '  <path fill="#00ff00" d="M0,0 L100,0 L100,100 L0,100 Z"/>\n'
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        with patch.object(_ve.Path, "as_subpaths", side_effect=RuntimeError("boom")):
            shapes, _, _ = vp._parse_svg(str(svg_file), target_width_mm=100.0)

        assert len(shapes) == 1
        assert shapes[0]["poly"].area > 0

    def test_occlusion_keeps_uncovered_large_block(self, tmp_path):
        """Top shape covering only one subpath must not erase the other block."""
        svg_file = tmp_path / "occlusion_regression.svg"
        svg_file.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 120">\n'
                '  <path fill="#ff0000" d="'
                "M0,0 L100,0 L100,100 L0,100 Z "
                'M200,0 L300,0 L300,100 L200,100 Z"/>\n'
                '  <path fill="#0000ff" d="M0,0 L100,0 L100,100 L0,100 Z"/>\n'
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, _, _ = vp._parse_svg(str(svg_file), target_width_mm=100.0)
        clipped = VectorProcessor._clip_occlusion(shapes)

        red_area = sum(item["geometry"].area for item in clipped if item["color"] == (255, 0, 0))
        blue_area = sum(item["geometry"].area for item in clipped if item["color"] == (0, 0, 255))

        assert abs(red_area - 10000.0) < 5.0
        assert abs(blue_area - 10000.0) < 5.0


# =====================================================================
# 5b. SVG parse regression (Line → Bezier junction)
# =====================================================================


class TestLineToBezierJunction:
    """Regression: Line→CubicBezier/QuadraticBezier junction point must
    not be silently dropped, which would distort or destroy geometry."""

    def test_rounded_rect_preserves_area(self, tmp_path):
        """Rounded rectangle (lines + cubic-bezier corners) must keep
        nearly the full area of its bounding box."""
        # A 200×100 rounded rect with r=20 corner radii.
        # k ≈ 0.5523 is the standard cubic Bézier kappa for quarter circles.
        k = 0.5523
        r = 20
        w, h = 200, 100
        d = (
            f"M{r},0 L{w - r},0 "
            f"C{w - r + r * k},0 {w},{r - r * k} {w},{r} "
            f"L{w},{h - r} "
            f"C{w},{h - r + r * k} {w - r + r * k},{h} {w - r},{h} "
            f"L{r},{h} "
            f"C{r - r * k},{h} 0,{h - r + r * k} 0,{h - r} "
            f"L0,{r} "
            f"C0,{r - r * k} {r - r * k},0 {r},0 Z"
        )
        svg_file = tmp_path / "rounded_rect.svg"
        svg_file.write_text(
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">\n'
                f'  <path fill="#ff0000" d="{d}"/>\n'
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, scale, bbox = vp._parse_svg(str(svg_file), target_width_mm=100.0)

        assert len(shapes) >= 1
        total_area = sum(s["poly"].area for s in shapes)
        bbox_area = w * h  # 20000
        # A rounded rect with r=20 loses about 4*(r^2 - pi*r^2/4) ≈ 343
        # from its bounding rect, so the expected area ≈ 19657.
        expected_area = w * h - 4 * (r * r - np.pi * r * r / 4.0)
        assert total_area > expected_area * 0.95, (
            f"Rounded rect area {total_area:.1f} is too small "
            f"(expected ~{expected_area:.1f}, bbox={bbox_area})"
        )

    def test_line_to_quadratic_bezier_junction(self, tmp_path):
        """Path with Line→QuadraticBezier must preserve the junction point."""
        # A shape: straight left edge, quadratic-curved right edge.
        svg_file = tmp_path / "line_quad.svg"
        svg_file.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">\n'
                '  <path fill="#00ff00" d="M0,0 L100,0 Q100,50 100,100 L0,100 Z"/>\n'
                "</svg>\n"
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, _, _ = vp._parse_svg(str(svg_file), target_width_mm=100.0)

        assert len(shapes) >= 1
        total_area = sum(s["poly"].area for s in shapes)
        # The shape is a 100x100 square (the Q curve is actually a straight
        # line from (100,0) to (100,100) with control at (100,50)).
        assert total_area > 9000.0, (
            f"Line→QuadBezier shape area {total_area:.1f} is too small "
            "(expected ~10000)"
        )


# =====================================================================
# 6. VectorAnalysis dataclass
# =====================================================================

class TestVectorAnalysis:
    """Verify VectorAnalysis dataclass construction and defaults."""

    def test_dataclass_fields(self):
        a = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[],
            silhouette=None,
            scale_factor=0.5,
            bbox=(0, 0, 100, 100),
            color_conf={},
            slot_names=["White"],
            num_channels=1,
            num_layers=4,
            preview_colors={0: [255, 255, 255, 255]},
        )
        assert a.scale_factor == 0.5
        assert a.num_channels == 1
        assert a.stage_timings == {}

    def test_stage_timings_default(self):
        a = VectorAnalysis(
            shape_data=[], clipped_shapes=[], matched_shapes=[], silhouette=None,
            scale_factor=1.0, bbox=(0, 0, 10, 10), color_conf={},
            slot_names=[], num_channels=0, num_layers=0, preview_colors={},
        )
        a.stage_timings["test"] = 1.23
        assert a.stage_timings == {"test": 1.23}


# =====================================================================
# 7. render_preview
# =====================================================================

class TestRenderPreview:
    """Verify render_preview produces correct output."""

    def _make_analysis(self, shapes, silhouette=None, w=100, h=100, sf=1.0):
        return VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=shapes,
            silhouette=silhouette,
            scale_factor=sf,
            bbox=(0, 0, w, h),
            color_conf={},
            slot_names=["White", "Red"],
            num_channels=2,
            num_layers=4,
            preview_colors={0: [255, 255, 255, 255], 1: [255, 0, 0, 255]},
        )

    def test_empty_shapes_returns_white(self):
        analysis = self._make_analysis([], w=10, h=10)
        img = VectorProcessor.render_preview(analysis, pixels_per_mm=1.0)
        assert img.shape[2] == 4
        assert img.dtype == np.uint8
        assert np.all(img[:, :, :3] == 255)

    def test_basic_shape_rendered(self):
        shape = {
            "geometry": box(2, 2, 8, 8),
            "recipe": [1, 1, 0, 0],
            "color": (255, 0, 0),
        }
        analysis = self._make_analysis([shape], w=10, h=10, sf=1.0)
        img = VectorProcessor.render_preview(analysis, pixels_per_mm=10.0)
        assert img.shape == (100, 100, 4)
        center = img[50, 50, :3]
        assert not np.all(center == 255), "Center should be colored, not white"

    def test_max_width_clamping(self):
        shape = {
            "geometry": box(0, 0, 200, 100),
            "recipe": [1, 1, 0, 0],
            "color": (255, 0, 0),
        }
        analysis = self._make_analysis([shape], w=200, h=100, sf=1.0)
        img = VectorProcessor.render_preview(analysis, pixels_per_mm=20.0, max_width_px=500)
        assert img.shape[1] <= 500

    def test_rgba_output_dtype(self):
        analysis = self._make_analysis([], w=5, h=5, sf=1.0)
        img = VectorProcessor.render_preview(analysis, pixels_per_mm=2.0)
        assert img.dtype == np.uint8
        assert img.shape[2] == 4
