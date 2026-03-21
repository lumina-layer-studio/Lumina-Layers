"""
Lumina Studio - 按颜色分组 GLB 预览模型属性测试 (Property-Based Tests)

使用 Hypothesis 验证 generate_segmented_glb() 的正确性属性。
每个属性测试至少运行 100 次迭代。
"""

import os
import re
import sys

import numpy as np
import pytest
import trimesh
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.converter import generate_segmented_glb

# Regex for valid color_<hex> node names
COLOR_NODE_RE = re.compile(r"^color_([0-9a-f]{6})$")


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert 6-digit lowercase hex string to (R, G, B) ints."""
    return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


def _make_cache(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
) -> dict:
    """Build a minimal preview cache dict accepted by generate_segmented_glb."""
    h, w = matched_rgb.shape[:2]
    return {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "target_w": w,
        "target_h": h,
        "target_width_mm": w * 0.42,  # reasonable pixel scale
    }


# ---------------------------------------------------------------------------
# Hypothesis strategy: generate a small matched_rgb with 1-8 unique colors
# ---------------------------------------------------------------------------
@st.composite
def matched_rgb_strategy(draw: st.DrawFn):
    """Generate a small matched_rgb array with a controlled number of unique colors.

    Returns (matched_rgb, mask_solid, expected_unique_colors).
    """
    h = draw(st.integers(min_value=4, max_value=16))
    w = draw(st.integers(min_value=4, max_value=16))
    n_colors = draw(st.integers(min_value=1, max_value=8))

    # Generate n_colors distinct RGB triples
    colors = set()
    while len(colors) < n_colors:
        c = (
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
        )
        colors.add(c)
    color_list = list(colors)

    # Fill the image by randomly assigning each pixel one of the colors
    matched_rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            idx = draw(st.integers(0, n_colors - 1))
            matched_rgb[y, x] = color_list[idx]

    # mask_solid: at least one pixel must be solid; make most pixels solid
    mask_solid = np.ones((h, w), dtype=bool)
    # Optionally mark a few pixels as non-solid
    n_transparent = draw(st.integers(0, min(h * w // 4, 8)))
    for _ in range(n_transparent):
        ty = draw(st.integers(0, h - 1))
        tx = draw(st.integers(0, w - 1))
        mask_solid[ty, tx] = False

    # Ensure at least one solid pixel
    if not np.any(mask_solid):
        mask_solid[0, 0] = True

    # Compute actual unique colors present in solid pixels
    solid_pixels = matched_rgb[mask_solid]
    unique_colors = np.unique(solid_pixels, axis=0)

    return matched_rgb, mask_solid, unique_colors


# ============================================================================
# Property 1: GLB 分段正确性
# Feature: color-remap-relief-linkage, Property 1: GLB 分段正确性
# **Validates: Requirements 1.1, 1.2, 1.4**
# ============================================================================

@settings(max_examples=100)
@given(data=matched_rgb_strategy())
def test_glb_segmentation_correctness(data):
    """Property 1: GLB 分段正确性

    For any valid preview cache (with matched_rgb and mask_solid),
    generate_segmented_glb() should produce a GLB file satisfying:
    (a) Each unique color maps to exactly one Mesh node
    (b) Each Mesh is named color_<hex> (6-digit lowercase hex)
    (c) Each Mesh's face color matches the hex in its name
    (d) Each Mesh's vertex min Z = 0 (Pivot Point constraint)
    """
    matched_rgb, mask_solid, expected_unique_colors = data
    cache = _make_cache(matched_rgb, mask_solid)

    glb_path = generate_segmented_glb(cache)

    # Function should succeed for valid input with solid pixels
    assert glb_path is not None, "generate_segmented_glb returned None for valid input"
    assert os.path.isfile(glb_path), f"GLB file not found: {glb_path}"

    # Load the GLB scene
    scene = trimesh.load(glb_path)
    assert isinstance(scene, trimesh.Scene), "Loaded GLB is not a trimesh.Scene"

    # Collect all color_<hex> nodes from the scene graph
    color_nodes: dict[str, trimesh.Trimesh] = {}
    for node_name in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph[node_name]
        geom = scene.geometry[geom_name]
        m = COLOR_NODE_RE.match(node_name)
        if m:
            color_nodes[node_name] = geom

    n_expected = len(expected_unique_colors)

    # (a) Each unique color corresponds to exactly one Mesh node
    assert len(color_nodes) == n_expected, (
        f"Expected {n_expected} color meshes, got {len(color_nodes)}. "
        f"Nodes: {list(color_nodes.keys())}"
    )

    # Build set of expected hex names from unique colors
    expected_hex_set = set()
    for rgb in expected_unique_colors:
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        expected_hex_set.add(f"color_{r:02x}{g:02x}{b:02x}")

    assert set(color_nodes.keys()) == expected_hex_set, (
        f"Mesh names mismatch.\n"
        f"  Expected: {sorted(expected_hex_set)}\n"
        f"  Got:      {sorted(color_nodes.keys())}"
    )

    for node_name, mesh in color_nodes.items():
        m = COLOR_NODE_RE.match(node_name)
        hex_str = m.group(1)
        expected_r, expected_g, expected_b = _hex_to_rgb(hex_str)

        # (b) Name format already validated by regex match above

        # (c) Face color matches the hex in the name
        face_colors = mesh.visual.face_colors  # (N, 4) RGBA
        assert face_colors is not None and len(face_colors) > 0, (
            f"Mesh {node_name} has no face colors"
        )
        # All faces should share the same RGB (alpha may vary)
        unique_face_rgb = np.unique(face_colors[:, :3], axis=0)
        assert len(unique_face_rgb) == 1, (
            f"Mesh {node_name} has {len(unique_face_rgb)} distinct face RGB values, expected 1"
        )
        actual_r, actual_g, actual_b = unique_face_rgb[0]
        assert (actual_r, actual_g, actual_b) == (expected_r, expected_g, expected_b), (
            f"Mesh {node_name} face color ({actual_r},{actual_g},{actual_b}) "
            f"does not match name hex ({expected_r},{expected_g},{expected_b})"
        )

        # (d) Vertex min Z = 0 (Pivot Point constraint)
        min_z = mesh.vertices[:, 2].min()
        assert np.isclose(min_z, 0.0, atol=1e-6), (
            f"Mesh {node_name} min_z = {min_z}, expected 0.0"
        )


# ---------------------------------------------------------------------------
# Hypothesis strategy: generate matched_rgb with MORE colors than max_meshes
# Uses bulk draws to keep the base example small.
# ---------------------------------------------------------------------------
@st.composite
def many_colors_strategy(draw: st.DrawFn):
    """Generate a matched_rgb array with more unique colors than max_meshes.

    Returns (matched_rgb, mask_solid, max_meshes).
    """
    max_meshes = draw(st.integers(min_value=3, max_value=8))
    n_colors = draw(st.integers(min_value=max_meshes + 2, max_value=max_meshes + 12))

    h = draw(st.integers(min_value=8, max_value=16))
    w = draw(st.integers(min_value=8, max_value=16))

    # Generate n_colors distinct RGB triples using a single bulk draw
    color_bytes = draw(
        st.lists(
            st.tuples(st.integers(0, 255), st.integers(0, 255), st.integers(0, 255)),
            min_size=n_colors * 2,
            max_size=n_colors * 3,
        )
    )
    # Deduplicate and take first n_colors
    seen: set[tuple[int, int, int]] = set()
    color_list: list[tuple[int, int, int]] = []
    for c in color_bytes:
        if c not in seen:
            seen.add(c)
            color_list.append(c)
        if len(color_list) == n_colors:
            break
    assume(len(color_list) == n_colors)

    # Build index array: one bulk draw for all pixel assignments
    # First n_colors pixels get one of each color; rest are random indices
    total_px = h * w
    assume(total_px >= n_colors)

    # Guaranteed placement indices (0..n_colors-1) + random fill
    random_fill = draw(
        st.lists(
            st.integers(0, n_colors - 1),
            min_size=total_px - n_colors,
            max_size=total_px - n_colors,
        )
    )
    indices = list(range(n_colors)) + random_fill

    # Shuffle via a drawn permutation seed
    seed = draw(st.integers(0, 2**32 - 1))
    rng = np.random.RandomState(seed)
    idx_arr = np.array(indices, dtype=np.int32)
    rng.shuffle(idx_arr)

    color_arr = np.array(color_list, dtype=np.uint8)  # (n_colors, 3)
    matched_rgb = color_arr[idx_arr].reshape(h, w, 3)
    mask_solid = np.ones((h, w), dtype=bool)

    return matched_rgb, mask_solid, max_meshes


# ============================================================================
# Property 2: GLB Mesh 数量上限
# Feature: color-remap-relief-linkage, Property 2: GLB Mesh 数量上限
# **Validates: Requirements 1.5**
# ============================================================================

@settings(max_examples=100)
@given(data=many_colors_strategy())
def test_glb_mesh_count_limit(data):
    """Property 2: GLB Mesh 数量上限

    For any matched_rgb with more unique colors than max_meshes,
    generate_segmented_glb(cache, max_meshes) should produce a GLB where:
    (a) The number of Mesh nodes <= max_meshes
    (b) All original solid pixels are still covered by some Mesh (no pixel loss)
    """
    matched_rgb, mask_solid, max_meshes = data
    cache = _make_cache(matched_rgb, mask_solid)

    glb_path = generate_segmented_glb(cache, max_meshes=max_meshes)

    # Should succeed for valid input with solid pixels
    assert glb_path is not None, "generate_segmented_glb returned None for valid input"
    assert os.path.isfile(glb_path), f"GLB file not found: {glb_path}"

    # Load the GLB scene
    scene = trimesh.load(glb_path)
    assert isinstance(scene, trimesh.Scene), "Loaded GLB is not a trimesh.Scene"

    # Collect color_<hex> nodes
    color_nodes: list[str] = []
    for node_name in scene.graph.nodes_geometry:
        if COLOR_NODE_RE.match(node_name):
            color_nodes.append(node_name)

    # (a) Mesh count <= max_meshes
    assert len(color_nodes) <= max_meshes, (
        f"Mesh count {len(color_nodes)} exceeds max_meshes={max_meshes}. "
        f"Nodes: {color_nodes}"
    )

    # (b) All original solid pixels are covered by some Mesh (no pixel loss).
    # Each solid pixel becomes exactly one voxel box (8 vertices, 12 faces).
    # Total voxels across all meshes must equal total solid pixels.
    total_solid_pixels = int(np.count_nonzero(mask_solid))
    total_voxels_in_glb = 0
    for node_name in color_nodes:
        transform, geom_name = scene.graph[node_name]
        geom = scene.geometry[geom_name]
        # Each voxel box has 8 vertices
        n_verts = len(geom.vertices)
        total_voxels_in_glb += n_verts // 8

    assert total_voxels_in_glb == total_solid_pixels, (
        f"Pixel coverage mismatch: {total_solid_pixels} solid pixels but "
        f"{total_voxels_in_glb} voxels in GLB (no pixel should be lost)"
    )
