"""
Lumina Studio - 按颜色分组 GLB 预览模型单元测试 (Unit Tests)

验证 generate_segmented_glb() 的具体示例和边界条件。
Requirements: 1.1, 1.5
"""

import os
import re
import sys

import numpy as np
import pytest
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.converter import generate_segmented_glb

COLOR_NODE_RE = re.compile(r"^color_([0-9a-f]{6})$")


def _make_cache(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    target_width_mm: float = 10.0,
) -> dict:
    """Build a minimal preview cache dict."""
    h, w = matched_rgb.shape[:2]
    return {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "target_w": w,
        "target_h": h,
        "target_width_mm": target_width_mm,
    }


def _get_color_nodes(scene: trimesh.Scene) -> dict[str, trimesh.Trimesh]:
    """Extract color_<hex> named nodes from a loaded GLB scene."""
    nodes: dict[str, trimesh.Trimesh] = {}
    for node_name in scene.graph.nodes_geometry:
        m = COLOR_NODE_RE.match(node_name)
        if m:
            _, geom_name = scene.graph[node_name]
            nodes[node_name] = scene.geometry[geom_name]
    return nodes


# ============================================================================
# Test 1: None cache returns None
# ============================================================================

class TestEmptyAndNoneInputs:
    """Tests for empty/None inputs returning None."""

    def test_none_cache_returns_none(self) -> None:
        """None cache should return None immediately."""
        result = generate_segmented_glb(None)
        assert result is None

    def test_empty_image_all_transparent_returns_none(self) -> None:
        """All mask_solid=False (no solid pixels) should return None."""
        h, w = 8, 8
        matched_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        mask_solid = np.zeros((h, w), dtype=bool)  # all transparent
        cache = _make_cache(matched_rgb, mask_solid)

        result = generate_segmented_glb(cache)
        assert result is None

    def test_missing_matched_rgb_returns_none(self) -> None:
        """Cache without matched_rgb key should return None."""
        cache = {
            "mask_solid": np.ones((4, 4), dtype=bool),
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 4.0,
        }
        result = generate_segmented_glb(cache)
        assert result is None

    def test_missing_mask_solid_returns_none(self) -> None:
        """Cache without mask_solid key should return None."""
        cache = {
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 4.0,
        }
        result = generate_segmented_glb(cache)
        assert result is None


# ============================================================================
# Test 2: Single color image generates exactly 1 Mesh
# ============================================================================

class TestSingleColorImage:
    """Tests for single-color images producing exactly 1 Mesh."""

    def test_single_color_generates_one_mesh(self) -> None:
        """A uniform red image should produce exactly 1 Mesh named color_ff0000."""
        h, w = 6, 6
        red = np.array([255, 0, 0], dtype=np.uint8)
        matched_rgb = np.full((h, w, 3), red, dtype=np.uint8)
        mask_solid = np.ones((h, w), dtype=bool)
        cache = _make_cache(matched_rgb, mask_solid)

        glb_path = generate_segmented_glb(cache)

        assert glb_path is not None
        assert os.path.isfile(glb_path)

        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        assert len(color_nodes) == 1
        assert "color_ff0000" in color_nodes

        # Verify face color matches
        mesh = color_nodes["color_ff0000"]
        face_rgb = np.unique(mesh.visual.face_colors[:, :3], axis=0)
        assert len(face_rgb) == 1
        assert tuple(face_rgb[0]) == (255, 0, 0)

        # Verify Pivot Point constraint: min_z = 0
        assert np.isclose(mesh.vertices[:, 2].min(), 0.0, atol=1e-6)

    def test_single_color_with_partial_mask(self) -> None:
        """Single color with some transparent pixels still produces 1 Mesh."""
        h, w = 8, 8
        blue = np.array([0, 0, 255], dtype=np.uint8)
        matched_rgb = np.full((h, w, 3), blue, dtype=np.uint8)
        mask_solid = np.ones((h, w), dtype=bool)
        # Mark corners as transparent
        mask_solid[0, 0] = False
        mask_solid[0, -1] = False
        mask_solid[-1, 0] = False
        mask_solid[-1, -1] = False
        cache = _make_cache(matched_rgb, mask_solid)

        glb_path = generate_segmented_glb(cache)

        assert glb_path is not None
        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        assert len(color_nodes) == 1
        assert "color_0000ff" in color_nodes


# ============================================================================
# Test 3: Exactly 64 unique colors does NOT trigger merging
# ============================================================================

class TestExactly64Colors:
    """Tests for exactly 64 colors not triggering merge logic."""

    def test_64_colors_no_merge(self) -> None:
        """Exactly 64 unique colors with default max_meshes=64 should produce 64 Meshes."""
        # Generate 64 distinct colors spread across the RGB cube
        colors = []
        for r_idx in range(4):
            for g_idx in range(4):
                for b_idx in range(4):
                    colors.append([r_idx * 85, g_idx * 85, b_idx * 85])
        assert len(colors) == 64

        # Build an image where each row of pixels uses one color
        # 64 colors, each gets at least 1 pixel in a 64x4 image
        h, w = 64, 4
        matched_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        for i, c in enumerate(colors):
            matched_rgb[i, :, :] = c

        mask_solid = np.ones((h, w), dtype=bool)
        cache = _make_cache(matched_rgb, mask_solid)

        glb_path = generate_segmented_glb(cache, max_meshes=64)

        assert glb_path is not None
        assert os.path.isfile(glb_path)

        scene = trimesh.load(glb_path)
        color_nodes = _get_color_nodes(scene)

        # Exactly 64 meshes, no merging
        assert len(color_nodes) == 64

        # Every mesh name should be valid color_<hex>
        for name in color_nodes:
            assert COLOR_NODE_RE.match(name), f"Invalid mesh name: {name}"

        # Every mesh should satisfy Pivot Point constraint
        for name, mesh in color_nodes.items():
            min_z = mesh.vertices[:, 2].min()
            assert np.isclose(min_z, 0.0, atol=1e-6), (
                f"Mesh {name} min_z={min_z}, expected 0.0"
            )
