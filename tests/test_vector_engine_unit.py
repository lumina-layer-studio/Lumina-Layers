"""Unit tests for the Chroma-aligned vector engine (core/vector_engine.py).

Covers:
    1. Occlusion clipping: reverse-order accumulative difference
    2. Run-length extrusion: consecutive same-channel layers merged
    3. Output ordering: meshes_by_slot sorted by material ID
"""

import sys
import os
import types
import importlib.util
from unittest.mock import patch

import pytest
from shapely.geometry import Polygon, box

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from config import PrinterConfig

# Load core.vector_engine directly from its file to avoid the heavy
# core.__init__ import chain (which pulls in gradio, etc.).
_spec = importlib.util.spec_from_file_location(
    "core.vector_engine", os.path.join(_ROOT, "core", "vector_engine.py")
)
_ve = importlib.util.module_from_spec(_spec)
# Provide a minimal 'core' parent package so relative imports resolve
if "core" not in sys.modules:
    _pkg = types.ModuleType("core")
    _pkg.__path__ = [os.path.join(_ROOT, "core")]
    sys.modules["core"] = _pkg
sys.modules["core.vector_engine"] = _ve
_spec.loader.exec_module(_ve)
VectorProcessor = _ve.VectorProcessor


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
            _rect(0, 0, 10, 10, color=(255, 0, 0)),   # bottom (draw order 0)
            _rect(0, 0, 10, 10, color=(0, 255, 0)),    # top    (draw order 1)
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
            _rect(5, 0, 15, 10, color=(0, 255, 0)),   # top, narrower overlap
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
            _rect(0, 0, 1, 1, color=(255, 0, 0)),     # tiny bottom
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

    LAYER_H = PrinterConfig.LAYER_HEIGHT   # 0.08
    SLOT_NAMES = ["White", "Cyan", "Magenta", "Yellow"]

    def _make_matched(self, geometry, recipe):
        return [{"geometry": geometry, "recipe": recipe, "color": (0, 0, 0)}]

    def test_single_channel_all_layers(self):
        """All 5 layers mapped to channel 1 → single run for channel 1."""
        geom = box(0, 0, 10, 10)
        matched = self._make_matched(geom, [1, 1, 1, 1, 1])

        result = VectorProcessor._run_length_extrude(
            matched, num_layers=5, layer_h=self.LAYER_H,
            num_channels=4, slot_names=self.SLOT_NAMES, scale_factor=1.0,
        )

        assert "Cyan" in result
        assert len(result["Cyan"]["meshes"]) == 1  # single merged volume

    def test_alternating_channels_no_merge(self):
        """Alternating recipe [0,1,0,1,0] → no channel gets consecutive layers."""
        geom = box(0, 0, 10, 10)
        matched = self._make_matched(geom, [0, 1, 0, 1, 0])

        result = VectorProcessor._run_length_extrude(
            matched, num_layers=5, layer_h=self.LAYER_H,
            num_channels=4, slot_names=self.SLOT_NAMES, scale_factor=1.0,
        )

        white_count = len(result.get("White", {}).get("meshes", []))
        cyan_count = len(result.get("Cyan", {}).get("meshes", []))
        assert white_count == 3  # layers 0, 2, 4 → three separate runs
        assert cyan_count == 2   # layers 1, 3 → two separate runs

    def test_run_merges_consecutive(self):
        """Recipe [2,2,2,0,0] → channel 2 gets one run (layers 0-2),
        channel 0 gets one run (layers 3-4)."""
        geom = box(0, 0, 10, 10)
        matched = self._make_matched(geom, [2, 2, 2, 0, 0])

        result = VectorProcessor._run_length_extrude(
            matched, num_layers=5, layer_h=self.LAYER_H,
            num_channels=4, slot_names=self.SLOT_NAMES, scale_factor=1.0,
        )

        assert len(result["Magenta"]["meshes"]) == 1
        assert len(result["White"]["meshes"]) == 1

    def test_material_id_in_result(self):
        """Each slot entry should carry correct mat_id."""
        geom = box(0, 0, 5, 5)
        matched = self._make_matched(geom, [3, 3, 3, 3, 3])

        result = VectorProcessor._run_length_extrude(
            matched, num_layers=5, layer_h=self.LAYER_H,
            num_channels=4, slot_names=self.SLOT_NAMES, scale_factor=1.0,
        )

        assert result["Yellow"]["mat_id"] == 3

    def test_empty_geometry_skipped(self):
        """Empty geometry should produce no meshes."""
        geom = Polygon()
        matched = self._make_matched(geom, [0, 0, 0, 0, 0])

        result = VectorProcessor._run_length_extrude(
            matched, num_layers=5, layer_h=self.LAYER_H,
            num_channels=4, slot_names=self.SLOT_NAMES, scale_factor=1.0,
        )

        assert len(result) == 0


# =====================================================================
# 3. Output ordering
# =====================================================================

class TestOutputOrdering:
    """Verify meshes_by_slot is sorted by material ID when assembling scene."""

    def test_sorted_by_mat_id(self):
        """Simulated meshes_by_slot should sort by mat_id."""
        meshes_by_slot = {
            "Yellow": {"meshes": ["m"], "mat_id": 3},
            "White":  {"meshes": ["m"], "mat_id": 0},
            "Cyan":   {"meshes": ["m"], "mat_id": 1},
        }
        sorted_items = sorted(meshes_by_slot.items(), key=lambda x: x[1]["mat_id"])
        names = [name for name, _ in sorted_items]
        assert names == ["White", "Cyan", "Yellow"]


# =====================================================================
# 4. Extrude geometry helper
# =====================================================================

class TestExtrudeGeometry:

    def test_polygon_produces_mesh(self):
        poly = box(0, 0, 10, 10)
        meshes = VectorProcessor._extrude_geometry(poly, height=1.0, z_offset=0, scale=1.0)
        assert len(meshes) == 1
        assert meshes[0].vertices.shape[0] > 0

    def test_multipolygon(self):
        from shapely.ops import unary_union
        mp = unary_union([box(0, 0, 5, 5), box(10, 0, 15, 5)])
        meshes = VectorProcessor._extrude_geometry(mp, height=0.5, z_offset=0, scale=1.0)
        assert len(meshes) == 2

    def test_empty_returns_empty(self):
        meshes = VectorProcessor._extrude_geometry(Polygon(), height=1.0, z_offset=0, scale=1.0)
        assert meshes == []

    def test_none_returns_empty(self):
        meshes = VectorProcessor._extrude_geometry(None, height=1.0, z_offset=0, scale=1.0)
        assert meshes == []

    def test_extrude_cache_reuses_base_mesh(self):
        """Same polygon/height/scale should hit cache and only extrude once."""
        poly = box(0, 0, 10, 10)
        cache = {}

        call_count = {"n": 0}
        real_box = _ve.trimesh.creation.box

        def fake_extrude_polygon(_poly, height):
            call_count["n"] += 1
            # return any valid mesh; dimensions are irrelevant for cache count check
            return real_box(extents=[1, 1, max(height, 1e-6)])

        with patch.object(_ve.trimesh.creation, "extrude_polygon", side_effect=fake_extrude_polygon):
            meshes1 = VectorProcessor._extrude_geometry(
                poly, height=1.0, z_offset=0.0, scale=1.0, extrude_cache=cache
            )
            meshes2 = VectorProcessor._extrude_geometry(
                poly, height=1.0, z_offset=2.0, scale=1.0, extrude_cache=cache
            )

        assert len(meshes1) == 1
        assert len(meshes2) == 1
        assert call_count["n"] == 1


# =====================================================================
# 5. SVG parse regression (multi-subpath)
# =====================================================================

class TestParseSvgSubpaths:

    def test_split_multi_subpath_path_into_multiple_polygons(self, tmp_path):
        """Single <path> with two subpaths should yield two polygons."""
        svg_file = tmp_path / "multi_subpath.svg"
        svg_file.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 120">\n'
                '  <path fill="#ff0000" d="'
                'M0,0 L100,0 L100,100 L0,100 Z '
                'M200,0 L300,0 L300,100 L200,100 Z"/>\n'
                '</svg>\n'
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, scale, bbox = vp._parse_svg(str(svg_file), target_width_mm=100.0)

        assert len(shapes) == 2
        areas = sorted(s["poly"].area for s in shapes)
        assert abs(areas[0] - 10000.0) < 5.0
        assert abs(areas[1] - 10000.0) < 5.0
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
                '</svg>\n'
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
                'M0,0 L100,0 L100,100 L0,100 Z '
                'M200,0 L300,0 L300,100 L200,100 Z"/>\n'
                '  <path fill="#0000ff" d="M0,0 L100,0 L100,100 L0,100 Z"/>\n'
                '</svg>\n'
            ),
            encoding="utf-8",
        )

        vp = _make_parse_only_processor()
        shapes, _, _ = vp._parse_svg(str(svg_file), target_width_mm=100.0)
        clipped = VectorProcessor._clip_occlusion(shapes)

        red_area = sum(
            item["geometry"].area for item in clipped if item["color"] == (255, 0, 0)
        )
        blue_area = sum(
            item["geometry"].area for item in clipped if item["color"] == (0, 0, 255)
        )

        assert abs(red_area - 10000.0) < 5.0
        assert abs(blue_area - 10000.0) < 5.0
