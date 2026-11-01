"""Regression: SVG-native vector generate must honour recipe overrides.

Covers the user-reported bug "经典 LUT 矢量图 + 自定义配色添加多层：
前端预览能看到，3MF 模型里没有". The vector branch used to call
``analyze_svg`` → ``build_mesh`` from scratch and silently ignored
``recipe_overrides`` / the user-extended ``color_layers``, so edits made
in the CustomRecipeDialog only ever surfaced in the 2D preview + segmented
GLB (which read ``cache["material_matrix"]`` after
``/convert/apply-recipe-override``). This test locks down the fix:
``apply_recipe_overrides_to_analysis`` must rewrite every overridden
shape's recipe, extend ``analysis.num_layers`` when layers were added,
and register user-declared virtual materials.

回归测试：锁定 "矢量 3MF 生成无视自定义配方 + 加层" 的修复。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import numpy as np
import pytest
from shapely.geometry import box


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Load core.vector_engine directly only when the suite has not loaded it yet.
# Replacing an existing module leaves ``core.vector_engine`` on the package
# pointing at the old object, so later monkeypatches can silently target a
# different module from ``VectorProcessor`` during combined test runs.
# 仅在测试进程尚未加载时直接载入，避免组合执行时产生两个模块对象。
if "core.vector_engine" in sys.modules:
    _ve = sys.modules["core.vector_engine"]
else:
    _spec = importlib.util.spec_from_file_location(
        "core.vector_engine", os.path.join(_ROOT, "core", "vector_engine.py")
    )
    _ve = importlib.util.module_from_spec(_spec)
    if "core" not in sys.modules:
        _pkg = types.ModuleType("core")
        _pkg.__path__ = [os.path.join(_ROOT, "core")]
        sys.modules["core"] = _pkg
    sys.modules["core.vector_engine"] = _ve
    setattr(sys.modules["core"], "vector_engine", _ve)
    assert _spec.loader is not None
    _spec.loader.exec_module(_ve)

VectorAnalysis = _ve.VectorAnalysis
apply_recipe_overrides_to_analysis = _ve.apply_recipe_overrides_to_analysis


# --- Helpers -----------------------------------------------------------------


def _make_analysis(shapes, *, bbox=(0.0, 0.0, 10.0, 10.0), scale_factor=1.0,
                   slot_names=None, num_channels=4, num_layers=3):
    """Build a minimal VectorAnalysis whose bbox/scale match the preview grid."""
    if slot_names is None:
        slot_names = ["White", "Cyan", "Magenta", "Yellow"]
    preview_colors = {
        0: [255, 255, 255, 255],
        1: [0, 183, 235, 255],
        2: [230, 0, 126, 255],
        3: [255, 212, 0, 255],
    }
    return VectorAnalysis(
        shape_data=[],
        clipped_shapes=[],
        matched_shapes=shapes,
        silhouette=None,
        scale_factor=scale_factor,
        bbox=bbox,
        color_conf={"slots": list(slot_names), "preview": dict(preview_colors)},
        slot_names=list(slot_names),
        num_channels=num_channels,
        num_layers=num_layers,
        preview_colors=dict(preview_colors),
    )


def _preview_grid_shape(bbox, scale_factor, pixels_per_mm=10.0, max_width_px=1600):
    """Mirror the size calc inside ``build_preview_cache`` / the helper."""
    w_mm = bbox[2] * scale_factor
    h_mm = bbox[3] * scale_factor
    ppm = pixels_per_mm
    w_px = max(1, int(round(w_mm * ppm)))
    h_px = max(1, int(round(h_mm * ppm)))
    if w_px > max_width_px:
        ratio = max_width_px / w_px
        w_px = max_width_px
        h_px = max(1, int(round(h_px * ratio)))
    return h_px, w_px


# --- Tests -------------------------------------------------------------------


class TestApplyRecipeOverridesToAnalysis:
    """Vector branch must honour custom recipe overrides from the dialog."""

    def test_noop_when_overrides_empty(self):
        original_recipe = [2, 2, 2]
        shape = {"geometry": box(1, 1, 4, 4), "recipe": list(original_recipe)}
        analysis = _make_analysis([shape])

        apply_recipe_overrides_to_analysis(
            analysis,
            recipe_overrides=[],
            region_masks={},
        )

        assert analysis.matched_shapes[0]["recipe"] == original_recipe
        assert analysis.num_layers == 3

    def test_overridden_shape_recipe_replaced(self):
        """Shape whose pixels sit inside a region mask gets the user's recipe."""
        shape_inside = {"geometry": box(1, 1, 4, 4), "recipe": [2, 2, 2]}
        shape_outside = {"geometry": box(6, 6, 9, 9), "recipe": [1, 1, 1]}
        analysis = _make_analysis([shape_inside, shape_outside])

        h_px, w_px = _preview_grid_shape(analysis.bbox, analysis.scale_factor)
        mask = np.zeros((h_px, w_px), dtype=bool)
        # Region covers the "inside" shape's footprint (x=1..4, y=1..4).
        mask[10:40, 10:40] = True

        overrides = [
            {
                "region_id": "region-A",
                "recipe": [0, 3, 3],
                "layer_order": "Top2Bottom",
            }
        ]

        apply_recipe_overrides_to_analysis(
            analysis,
            recipe_overrides=overrides,
            region_masks={"region-A": mask},
            target_layers=3,
        )

        assert analysis.matched_shapes[0]["recipe"] == [0, 3, 3]
        # Shape outside the region keeps its LUT-matched recipe (padded only
        # if layers were added — here target == num_layers so no padding).
        assert analysis.matched_shapes[1]["recipe"] == [1, 1, 1]

    @pytest.mark.parametrize("region_order", [("old", "new"), ("new", "old")])
    @pytest.mark.parametrize("revisit_old", [False, True])
    def test_reselected_footprint_uses_last_edit(
        self, region_order: tuple[str, str], revisit_old: bool,
    ) -> None:
        """Selection IDs and mask storage order must not override edit history."""
        analysis = _make_analysis([
            {"geometry": box(1, 1, 4, 4), "recipe": [0, 0, 0]},
            {"geometry": box(6, 6, 9, 9), "recipe": [2, 2, 2]},
        ])
        mask = np.zeros((100, 100), dtype=bool)
        mask[10:41, 10:41] = True
        masks = {region: mask.copy() for region in region_order}
        overrides = [
            {"region_id": "old", "recipe": [1, 1, 1]},
            {"region_id": "new", "recipe": [0, 3, 2]},
        ]
        if revisit_old:
            overrides.append({"region_id": "old", "recipe": [3, 2, 1]})

        apply_recipe_overrides_to_analysis(
            analysis, recipe_overrides=overrides, region_masks=masks,
        )

        assert analysis.matched_shapes[0]["recipe"] == overrides[-1]["recipe"]
        assert analysis.matched_shapes[1]["recipe"] == [2, 2, 2]
        for saved_mask in masks.values():
            np.testing.assert_array_equal(saved_mask, mask)

    @pytest.mark.parametrize(
        "latest_width, expected",
        [(60, [0, 3, 2]), (50, [0, 3, 2]), (40, [1, 1, 1])],
    )
    def test_overlapping_edits_count_only_pixels_not_superseded(
        self, latest_width: int, expected: list[int],
    ) -> None:
        """An older large mask cannot reclaim pixels painted by a later edit."""
        analysis = _make_analysis([
            {"geometry": box(0, 0, 10, 10), "recipe": [0, 0, 0]},
        ])
        first_mask = np.ones((100, 100), dtype=bool)
        latest_mask = np.zeros_like(first_mask)
        latest_mask[:, :latest_width] = True
        apply_recipe_overrides_to_analysis(
            analysis,
            recipe_overrides=[
                {"region_id": "first", "recipe": [1, 1, 1]},
                {"region_id": "latest", "recipe": [0, 3, 2]},
            ],
            region_masks={"first": first_mask, "latest": latest_mask},
        )

        assert analysis.matched_shapes[0]["recipe"] == expected
        assert first_mask.all()
        assert int(latest_mask.sum()) == latest_width * 100

    @pytest.mark.parametrize("base_channel_idx", [0, 2])
    def test_added_layers_extend_num_layers_and_pad_non_overrides(self, base_channel_idx):
        """target_layers > num_layers must extend every shape's recipe."""
        shape_inside = {"geometry": box(1, 1, 4, 4), "recipe": [2, 2, 2]}
        shape_outside = {"geometry": box(6, 6, 9, 9), "recipe": [1, 1, 1]}
        analysis = _make_analysis([shape_inside, shape_outside])

        h_px, w_px = _preview_grid_shape(analysis.bbox, analysis.scale_factor)
        mask = np.zeros((h_px, w_px), dtype=bool)
        mask[10:40, 10:40] = True

        overrides = [
            {
                "region_id": "region-A",
                "recipe": [0, 3, 3, 2, 2],  # user appended 2 layers
                "layer_order": "Top2Bottom",
            }
        ]

        apply_recipe_overrides_to_analysis(
            analysis,
            recipe_overrides=overrides,
            region_masks={"region-A": mask},
            target_layers=5,
            base_channel_idx=base_channel_idx,
        )

        assert analysis.num_layers == 5
        # Overridden shape: full 5-layer recipe as the user wrote it.
        assert analysis.matched_shapes[0]["recipe"] == [0, 3, 3, 2, 2]
        # Non-override shape: original LUT recipe padded at the bottom
        # (Top2Bottom tail) with the base channel so the backing slab stays
        # continuous across the added depth.
        assert analysis.matched_shapes[1]["recipe"] == [1, 1, 1, base_channel_idx, base_channel_idx]

    def test_virtual_materials_extend_slot_names_and_preview_colors(self):
        """User-declared non-native primaries must land in the palette tail."""
        shape_inside = {"geometry": box(1, 1, 4, 4), "recipe": [2, 2, 2]}
        analysis = _make_analysis([shape_inside])
        lut_palette_length = analysis.num_channels  # 4 (CMYW)

        h_px, w_px = _preview_grid_shape(analysis.bbox, analysis.scale_factor)
        mask = np.zeros((h_px, w_px), dtype=bool)
        mask[10:40, 10:40] = True

        # local index 0 -> palette[LUT.N + 0], referenced in recipe as 4.
        overrides = [
            {
                "region_id": "region-A",
                "recipe": [lut_palette_length, 3, 3],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Gold", "hex": "#CFA13A"}],
            }
        ]

        apply_recipe_overrides_to_analysis(
            analysis,
            recipe_overrides=overrides,
            region_masks={"region-A": mask},
            target_layers=3,
        )

        assert len(analysis.slot_names) == lut_palette_length + 1
        assert analysis.slot_names[lut_palette_length] == "Gold"
        rgba = analysis.preview_colors[lut_palette_length]
        assert rgba[:3] == [0xCF, 0xA1, 0x3A]
        # Recipe should reference the virtual material's global channel idx.
        assert analysis.matched_shapes[0]["recipe"][0] == lut_palette_length

    def test_layer_order_conversion_bottom_to_top(self):
        """Bottom2Top recipes must be reversed into vector-internal Top2Bottom."""
        shape_inside = {"geometry": box(1, 1, 4, 4), "recipe": [2, 2, 2]}
        analysis = _make_analysis([shape_inside])

        h_px, w_px = _preview_grid_shape(analysis.bbox, analysis.scale_factor)
        mask = np.zeros((h_px, w_px), dtype=bool)
        mask[10:40, 10:40] = True

        overrides = [
            {
                "region_id": "region-A",
                "recipe": [3, 1, 0],  # Bottom2Top: [0]=bottom, [2]=top
                "layer_order": "Bottom2Top",
            }
        ]

        apply_recipe_overrides_to_analysis(
            analysis,
            recipe_overrides=overrides,
            region_masks={"region-A": mask},
            target_layers=3,
        )

        # After conversion: recipe[0] = top = 0, recipe[2] = bottom = 3.
        assert analysis.matched_shapes[0]["recipe"] == [0, 1, 3]

    def test_shape_below_overlap_threshold_is_not_overridden(self):
        """A shape that barely clips a region mask keeps its LUT recipe."""
        # Shape covers 30x30 preview pixels (x=1..4, y=1..4 @ ppm=10).
        shape = {"geometry": box(1, 1, 4, 4), "recipe": [2, 2, 2]}
        analysis = _make_analysis([shape])

        h_px, w_px = _preview_grid_shape(analysis.bbox, analysis.scale_factor)
        mask = np.zeros((h_px, w_px), dtype=bool)
        # Mask only touches ~4% of the shape (6x6 px in a corner).
        mask[10:16, 10:16] = True

        overrides = [
            {"region_id": "region-A", "recipe": [0, 3, 3], "layer_order": "Top2Bottom"}
        ]

        apply_recipe_overrides_to_analysis(
            analysis,
            recipe_overrides=overrides,
            region_masks={"region-A": mask},
            target_layers=3,
        )

        # Below 50% overlap → shape keeps original LUT recipe.
        assert analysis.matched_shapes[0]["recipe"] == [2, 2, 2]

    def test_mismatched_mask_shape_is_skipped_not_crashed(self):
        """A region mask at the wrong resolution is dropped with a warning."""
        shape = {"geometry": box(1, 1, 4, 4), "recipe": [2, 2, 2]}
        analysis = _make_analysis([shape])

        # Deliberately wrong shape: should be (100, 100) at ppm=10 for 10x10mm.
        bad_mask = np.ones((50, 50), dtype=bool)

        overrides = [
            {"region_id": "region-A", "recipe": [0, 3, 3], "layer_order": "Top2Bottom"}
        ]

        apply_recipe_overrides_to_analysis(
            analysis,
            recipe_overrides=overrides,
            region_masks={"region-A": bad_mask},
            target_layers=3,
        )

        # All masks rejected → overrides skipped, recipe untouched.
        assert analysis.matched_shapes[0]["recipe"] == [2, 2, 2]

    def test_dimension_change_maps_recipe_mask_to_fresh_vector_geometry(self):
        """Recipe footprints stay normalized when current physical size changes."""

        shape_inside = {"geometry": box(1, 1, 4, 4), "recipe": [2, 2, 2]}
        shape_outside = {"geometry": box(6, 6, 9, 9), "recipe": [1, 1, 1]}
        analysis = _make_analysis(
            [shape_inside, shape_outside],
            scale_factor=2.0,
        )
        source_mask = np.zeros((100, 100), dtype=bool)
        source_mask[10:41, 10:41] = True

        apply_recipe_overrides_to_analysis(
            analysis,
            recipe_overrides=[
                {
                    "region_id": "region-A",
                    "recipe": [0, 3, 3],
                    "layer_order": "Top2Bottom",
                }
            ],
            region_masks={"region-A": source_mask},
            target_layers=3,
            source_grid_shape=(100, 100),
        )

        assert analysis.matched_shapes[0]["recipe"] == [0, 3, 3]
        assert analysis.matched_shapes[1]["recipe"] == [1, 1, 1]
