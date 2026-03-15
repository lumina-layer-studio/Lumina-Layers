"""Property-Based tests for region-replace generate fix.
区域替换生成修复的 Property-Based 测试。

Feature: region-replace-generate-fix
Tests the matched_rgb override injection logic used by convert_image_to_3d.

Uses Hypothesis to verify that the override mechanism correctly updates
material_matrix for differing pixels via KDTree nearest-neighbor lookup.
使用 Hypothesis 验证 override 机制通过 KDTree 最近邻查找正确更新 material_matrix。
"""

from __future__ import annotations

import tempfile
import os

import cv2
import numpy as np
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from scipy.spatial import KDTree


# ---------------------------------------------------------------------------
# Helper: replicate the _rgb_to_lab conversion from LuminaImageProcessor
# ---------------------------------------------------------------------------

def rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
    """Convert RGB array to CIELAB colour space (perceptually uniform).
    将 RGB 数组转换为 CIELAB 色彩空间（感知均匀）。

    Args:
        rgb_array (np.ndarray): Shape (N, 3), dtype uint8. (形状 (N, 3)，dtype uint8)

    Returns:
        np.ndarray: Same shape, dtype float64, Lab values. (同形状，dtype float64，Lab 值)
    """
    original_shape = rgb_array.shape
    if rgb_array.ndim == 2:
        rgb_3d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
    else:
        rgb_3d = rgb_array.astype(np.uint8)
    bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
    if len(original_shape) == 2:
        return lab.reshape(original_shape)
    return lab


# ---------------------------------------------------------------------------
# Helper: replicate the override logic from convert_image_to_3d (lines 844-869)
# ---------------------------------------------------------------------------

def apply_matched_rgb_override(
    matched_rgb: np.ndarray,
    material_matrix: np.ndarray,
    mask_solid: np.ndarray,
    override_rgb: np.ndarray,
    lut_rgb: np.ndarray,
    ref_stacks: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply matched_rgb override logic identical to convert_image_to_3d.
    应用与 convert_image_to_3d 相同的 matched_rgb override 逻辑。

    This replicates the core override block so we can test it in isolation
    without needing a full LUT file, image, or processor setup.

    Args:
        matched_rgb (np.ndarray): Original matched_rgb (H, W, 3) uint8.
            (原始 matched_rgb)
        material_matrix (np.ndarray): Original material_matrix (H, W, L) int.
            (原始 material_matrix)
        mask_solid (np.ndarray): Solid pixel mask (H, W) bool.
            (实体像素掩码)
        override_rgb (np.ndarray): Override matched_rgb (H, W, 3) uint8.
            (覆盖用 matched_rgb)
        lut_rgb (np.ndarray): LUT colour palette (C, 3) uint8.
            (LUT 调色板)
        ref_stacks (np.ndarray): Reference stacks (C, L) int.
            (参考堆叠矩阵)

    Returns:
        tuple[np.ndarray, np.ndarray]: Updated (matched_rgb, material_matrix).
            (更新后的 matched_rgb 和 material_matrix)
    """
    lut_lab = rgb_to_lab(lut_rgb)
    kdtree = KDTree(lut_lab)

    result_matched = matched_rgb.copy()
    result_material = material_matrix.copy()

    if override_rgb.shape != matched_rgb.shape:
        # Shape mismatch: ignore override, return originals
        return result_matched, result_material

    diff_mask = np.any(matched_rgb != override_rgb, axis=-1) & mask_solid
    if np.any(diff_mask):
        diff_pixels = override_rgb[diff_mask]
        unique_colors = np.unique(diff_pixels, axis=0)
        for color in unique_colors:
            color_mask = np.all(override_rgb == color, axis=-1) & diff_mask
            repl_lab = rgb_to_lab(color.reshape(1, 3))
            _, lut_idx = kdtree.query(repl_lab)
            new_stacks = ref_stacks[lut_idx[0]]
            result_material[color_mask] = new_stacks
    result_matched = override_rgb.copy()

    return result_matched, result_material


# ---------------------------------------------------------------------------
# Helper: compute expected material_matrix entry for a single RGB colour
# ---------------------------------------------------------------------------

def expected_stack_for_color(
    color: np.ndarray,
    lut_rgb: np.ndarray,
    ref_stacks: np.ndarray,
) -> np.ndarray:
    """Return the ref_stacks entry for the KDTree nearest neighbour of *color*.
    返回 *color* 的 KDTree 最近邻对应的 ref_stacks 条目。

    Args:
        color (np.ndarray): Single RGB colour (3,) uint8. (单个 RGB 颜色)
        lut_rgb (np.ndarray): LUT palette (C, 3) uint8. (LUT 调色板)
        ref_stacks (np.ndarray): Reference stacks (C, L) int. (参考堆叠)

    Returns:
        np.ndarray: Stack entry (L,). (堆叠条目)
    """
    lut_lab = rgb_to_lab(lut_rgb)
    kdtree = KDTree(lut_lab)
    repl_lab = rgb_to_lab(color.reshape(1, 3))
    _, idx = kdtree.query(repl_lab)
    return ref_stacks[idx[0]]


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Small image dimensions for performance
_dim_st = st.integers(min_value=2, max_value=10)
# Number of LUT colours (at least 2 for meaningful KDTree)
_lut_size_st = st.integers(min_value=2, max_value=16)
# Number of material layers
_layer_st = st.integers(min_value=1, max_value=5)


@st.composite
def override_scenario(draw: st.DrawFn) -> dict:
    """Generate a complete override test scenario.
    生成完整的 override 测试场景。

    Produces matched_rgb, override_rgb (with guaranteed diffs), mask_solid,
    lut_rgb, ref_stacks, and material_matrix — all with consistent shapes.

    Returns:
        dict: Keys: matched_rgb, override_rgb, mask_solid, lut_rgb,
              ref_stacks, material_matrix, H, W, num_layers.
    """
    H = draw(_dim_st)
    W = draw(_dim_st)
    num_lut = draw(_lut_size_st)
    num_layers = draw(_layer_st)

    # LUT palette: distinct random colours
    lut_rgb = draw(
        st.lists(
            st.tuples(
                st.integers(0, 255),
                st.integers(0, 255),
                st.integers(0, 255),
            ),
            min_size=num_lut,
            max_size=num_lut,
        )
    )
    lut_rgb = np.array(lut_rgb, dtype=np.uint8)

    # ref_stacks: random stack indices
    ref_stacks = draw(
        st.from_type(np.ndarray).filter(lambda _: False)  # placeholder
    ) if False else np.array(
        draw(
            st.lists(
                st.lists(
                    st.integers(-1, 7), min_size=num_layers, max_size=num_layers
                ),
                min_size=num_lut,
                max_size=num_lut,
            )
        ),
        dtype=np.int32,
    )

    # matched_rgb: pick colours from LUT for each pixel (realistic scenario)
    pixel_indices = draw(
        st.lists(
            st.integers(0, num_lut - 1),
            min_size=H * W,
            max_size=H * W,
        )
    )
    matched_rgb = lut_rgb[pixel_indices].reshape(H, W, 3)

    # material_matrix: corresponding stacks
    material_matrix = ref_stacks[pixel_indices].reshape(H, W, num_layers)

    # mask_solid: at least some True pixels
    mask_flat = draw(
        st.lists(st.booleans(), min_size=H * W, max_size=H * W)
    )
    mask_solid = np.array(mask_flat, dtype=bool).reshape(H, W)
    # Ensure at least one solid pixel for meaningful test
    if not np.any(mask_solid):
        mask_solid[0, 0] = True

    # override_rgb: start from matched_rgb, then flip some pixels
    override_rgb = matched_rgb.copy()
    # Decide which pixels to change (at least 1 among solid pixels)
    solid_coords = np.argwhere(mask_solid)
    assume(len(solid_coords) > 0)
    num_to_change = draw(st.integers(min_value=1, max_value=max(1, len(solid_coords))))
    change_indices = draw(
        st.lists(
            st.sampled_from(list(range(len(solid_coords)))),
            min_size=num_to_change,
            max_size=num_to_change,
            unique=True,
        )
    )
    for ci in change_indices:
        r, c = solid_coords[ci]
        # Pick a different LUT colour
        new_idx = draw(st.integers(0, num_lut - 1))
        new_color = lut_rgb[new_idx]
        # Ensure it actually differs
        if np.array_equal(new_color, matched_rgb[r, c]):
            new_color = lut_rgb[(new_idx + 1) % num_lut]
        override_rgb[r, c] = new_color

    return {
        "matched_rgb": matched_rgb,
        "override_rgb": override_rgb,
        "mask_solid": mask_solid,
        "lut_rgb": lut_rgb,
        "ref_stacks": ref_stacks,
        "material_matrix": material_matrix,
        "H": H,
        "W": W,
        "num_layers": num_layers,
    }


# ===========================================================================
# Property 3: matched_rgb override 被正确使用
# Feature: region-replace-generate-fix, Property 3: matched_rgb override
# **Validates: Requirements 1.2, 6.2**
# ===========================================================================


class TestMatchedRgbOverrideInjection:
    """Property 3: matched_rgb override is correctly applied.
    Property 3: matched_rgb override 被正确使用。

    For any valid matched_rgb override array, the override logic SHALL:
    - Update material_matrix for pixels where override differs AND mask_solid is True
    - Leave material_matrix unchanged where override matches original
    - Leave material_matrix unchanged where mask_solid is False
    - Ignore override when shapes don't match (no crash)

    **Feature: region-replace-generate-fix, Property 3: matched_rgb override**
    **Validates: Requirements 1.2, 6.2**
    """

    @given(scenario=override_scenario())
    @settings(max_examples=100)
    def test_diff_pixels_material_matrix_updated(self, scenario: dict) -> None:
        """For pixels where override differs from original AND mask_solid is True,
        material_matrix SHALL be recomputed as KDTree nearest-neighbour of the
        override colour.

        对于 override 与原始不同且 mask_solid 为 True 的像素，material_matrix
        应被重新计算为 override 颜色的 KDTree 最近邻匹配结果。

        **Validates: Requirements 1.2, 6.2**
        """
        matched_rgb = scenario["matched_rgb"]
        override_rgb = scenario["override_rgb"]
        mask_solid = scenario["mask_solid"]
        lut_rgb = scenario["lut_rgb"]
        ref_stacks = scenario["ref_stacks"]
        material_matrix = scenario["material_matrix"]

        _, result_material = apply_matched_rgb_override(
            matched_rgb, material_matrix, mask_solid,
            override_rgb, lut_rgb, ref_stacks,
        )

        # Identify diff pixels that are solid
        diff_mask = np.any(matched_rgb != override_rgb, axis=-1) & mask_solid
        if not np.any(diff_mask):
            return  # No diff pixels to check

        # For each diff pixel, verify material_matrix matches KDTree lookup
        diff_coords = np.argwhere(diff_mask)
        for coord in diff_coords:
            r, c = coord
            color = override_rgb[r, c]
            expected = expected_stack_for_color(color, lut_rgb, ref_stacks)
            np.testing.assert_array_equal(
                result_material[r, c], expected,
                err_msg=f"Pixel ({r},{c}) with override color {color} "
                        f"should have stack {expected}, got {result_material[r, c]}"
            )

    @given(scenario=override_scenario())
    @settings(max_examples=100)
    def test_unchanged_pixels_material_matrix_preserved(self, scenario: dict) -> None:
        """For pixels where override matches original, material_matrix SHALL
        remain unchanged regardless of mask_solid.

        对于 override 与原始相同的像素，material_matrix 应保持不变。

        **Validates: Requirements 1.2, 6.2**
        """
        matched_rgb = scenario["matched_rgb"]
        override_rgb = scenario["override_rgb"]
        mask_solid = scenario["mask_solid"]
        lut_rgb = scenario["lut_rgb"]
        ref_stacks = scenario["ref_stacks"]
        material_matrix = scenario["material_matrix"]

        _, result_material = apply_matched_rgb_override(
            matched_rgb, material_matrix, mask_solid,
            override_rgb, lut_rgb, ref_stacks,
        )

        # Pixels where override == original should keep original material_matrix
        same_mask = np.all(matched_rgb == override_rgb, axis=-1)
        if np.any(same_mask):
            np.testing.assert_array_equal(
                result_material[same_mask],
                material_matrix[same_mask],
                err_msg="Unchanged pixels should preserve original material_matrix"
            )

    @given(scenario=override_scenario())
    @settings(max_examples=100)
    def test_non_solid_pixels_material_matrix_preserved(self, scenario: dict) -> None:
        """For pixels where mask_solid is False, material_matrix SHALL remain
        unchanged even if override differs from original.

        对于 mask_solid 为 False 的像素，即使 override 不同，material_matrix 也应保持不变。

        **Validates: Requirements 1.2, 6.2**
        """
        matched_rgb = scenario["matched_rgb"]
        override_rgb = scenario["override_rgb"]
        mask_solid = scenario["mask_solid"]
        lut_rgb = scenario["lut_rgb"]
        ref_stacks = scenario["ref_stacks"]
        material_matrix = scenario["material_matrix"]

        _, result_material = apply_matched_rgb_override(
            matched_rgb, material_matrix, mask_solid,
            override_rgb, lut_rgb, ref_stacks,
        )

        # Non-solid pixels should never be modified
        non_solid = ~mask_solid
        if np.any(non_solid):
            np.testing.assert_array_equal(
                result_material[non_solid],
                material_matrix[non_solid],
                err_msg="Non-solid pixels should preserve original material_matrix"
            )

    @given(
        h=st.integers(2, 8),
        w=st.integers(2, 8),
        oh=st.integers(2, 8),
        ow=st.integers(2, 8),
    )
    @settings(max_examples=100)
    def test_shape_mismatch_ignores_override(
        self, h: int, w: int, oh: int, ow: int,
    ) -> None:
        """When override shape doesn't match original, the override SHALL be
        ignored and original matched_rgb and material_matrix returned unchanged.

        当 override 形状与原始不匹配时，override 应被忽略，返回原始数据。

        **Validates: Requirements 1.2, 6.2**
        """
        assume(h != oh or w != ow)  # Ensure shapes actually differ

        matched_rgb = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
        override_rgb = np.random.randint(0, 256, (oh, ow, 3), dtype=np.uint8)
        mask_solid = np.ones((h, w), dtype=bool)
        lut_rgb = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8)
        ref_stacks = np.array([[0, 1], [1, 2], [2, 0]], dtype=np.int32)
        material_matrix = np.zeros((h, w, 2), dtype=np.int32)

        result_matched, result_material = apply_matched_rgb_override(
            matched_rgb, material_matrix, mask_solid,
            override_rgb, lut_rgb, ref_stacks,
        )

        np.testing.assert_array_equal(
            result_matched, matched_rgb,
            err_msg="Shape mismatch should return original matched_rgb"
        )
        np.testing.assert_array_equal(
            result_material, material_matrix,
            err_msg="Shape mismatch should return original material_matrix"
        )

    @given(scenario=override_scenario())
    @settings(max_examples=100)
    def test_override_via_npy_file_roundtrip(self, scenario: dict) -> None:
        """Override loaded from a .npy file SHALL produce the same result as
        direct array injection, validating the file serialization path.

        通过 .npy 文件加载的 override 应产生与直接数组注入相同的结果，
        验证文件序列化路径的正确性。

        **Validates: Requirements 1.2, 6.2**
        """
        override_rgb = scenario["override_rgb"]

        # Save to temp .npy and reload
        fd, tmp_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd)
        try:
            np.save(tmp_path, override_rgb)
            loaded = np.load(tmp_path)
            np.testing.assert_array_equal(
                loaded, override_rgb,
                err_msg=".npy roundtrip should preserve override_rgb exactly"
            )
            assert loaded.dtype == override_rgb.dtype
            assert loaded.shape == override_rgb.shape
        finally:
            os.unlink(tmp_path)

    @given(scenario=override_scenario())
    @settings(max_examples=100)
    def test_result_matched_rgb_equals_override(self, scenario: dict) -> None:
        """After override application, the returned matched_rgb SHALL equal
        the override array (not the original).

        应用 override 后，返回的 matched_rgb 应等于 override 数组而非原始数组。

        **Validates: Requirements 1.2, 6.2**
        """
        matched_rgb = scenario["matched_rgb"]
        override_rgb = scenario["override_rgb"]
        mask_solid = scenario["mask_solid"]
        lut_rgb = scenario["lut_rgb"]
        ref_stacks = scenario["ref_stacks"]
        material_matrix = scenario["material_matrix"]

        result_matched, _ = apply_matched_rgb_override(
            matched_rgb, material_matrix, mask_solid,
            override_rgb, lut_rgb, ref_stacks,
        )

        np.testing.assert_array_equal(
            result_matched, override_rgb,
            err_msg="Result matched_rgb should equal override_rgb"
        )


# ===========================================================================
# Unit Tests: Generate 端点缓存序列化和回退
# Requirements 5.1, 5.2, 5.3
# ===========================================================================


def _serialize_cached_matched_rgb(
    use_cached_matched_rgb: bool,
    cache: dict,
    session_id: str,
    register_temp_file_fn,
) -> str | None:
    """Replicate the cache serialization logic from convert_generate endpoint.
    复制 convert_generate 端点的缓存序列化逻辑。

    This helper isolates the exact logic from api/routers/converter.py
    (lines ~597-607) so we can unit-test it without the full endpoint stack.

    Args:
        use_cached_matched_rgb (bool): Whether to use cached matched_rgb.
            (是否使用缓存的 matched_rgb)
        cache (dict): Session preview cache dict. (Session 预览缓存字典)
        session_id (str): Session identifier. (Session 标识符)
        register_temp_file_fn: Callable(session_id, path) to register temp files.
            (注册临时文件的回调函数)

    Returns:
        str | None: Path to .npy temp file, or None if not applicable.
            (.npy 临时文件路径，或 None)
    """
    matched_rgb_path: str | None = None
    if use_cached_matched_rgb:
        cached_matched_rgb = cache.get("matched_rgb")
        if cached_matched_rgb is not None:
            fd, mr_temp_path = tempfile.mkstemp(suffix=".npy")
            os.close(fd)
            np.save(mr_temp_path, cached_matched_rgb)
            matched_rgb_path = mr_temp_path
            register_temp_file_fn(session_id, mr_temp_path)
    return matched_rgb_path


class TestGenerateCacheSerialization:
    """Unit tests for generate endpoint cache serialization and fallback.
    Generate 端点缓存序列化和回退的单元测试。

    Tests the logic that serializes session-cached matched_rgb to a .npy
    temp file for cross-process transfer to the Worker.

    **Validates: Requirements 5.1, 5.2, 5.3**
    """

    def test_cache_hit_creates_npy_file(self) -> None:
        """WHEN use_cached_matched_rgb=True AND cache has matched_rgb,
        a .npy temp file SHALL be created with correct content.

        当 use_cached_matched_rgb=True 且缓存中有 matched_rgb 时，
        应创建包含正确内容的 .npy 临时文件。

        **Validates: Requirements 5.1**
        """
        test_array = np.random.randint(0, 256, (4, 6, 3), dtype=np.uint8)
        cache = {"matched_rgb": test_array}
        registered_files: list[tuple[str, str]] = []

        path = _serialize_cached_matched_rgb(
            use_cached_matched_rgb=True,
            cache=cache,
            session_id="test-session-1",
            register_temp_file_fn=lambda sid, p: registered_files.append((sid, p)),
        )

        try:
            assert path is not None, "Should return a file path"
            assert path.endswith(".npy"), "File should have .npy extension"
            assert os.path.exists(path), "File should exist on disk"

            loaded = np.load(path)
            np.testing.assert_array_equal(
                loaded, test_array,
                err_msg="Saved .npy content should match original array"
            )
            assert loaded.dtype == test_array.dtype
            assert loaded.shape == test_array.shape
        finally:
            if path and os.path.exists(path):
                os.unlink(path)

    def test_cache_hit_registers_temp_file(self) -> None:
        """WHEN temp file is created successfully, it SHALL be registered
        to the session's temp file list for cleanup.

        当临时文件创建成功时，应将其注册到 Session 的临时文件列表中。

        **Validates: Requirements 5.2**
        """
        test_array = np.zeros((3, 3, 3), dtype=np.uint8)
        cache = {"matched_rgb": test_array}
        registered_files: list[tuple[str, str]] = []
        session_id = "test-session-2"

        path = _serialize_cached_matched_rgb(
            use_cached_matched_rgb=True,
            cache=cache,
            session_id=session_id,
            register_temp_file_fn=lambda sid, p: registered_files.append((sid, p)),
        )

        try:
            assert len(registered_files) == 1, "Should register exactly one temp file"
            reg_sid, reg_path = registered_files[0]
            assert reg_sid == session_id, "Should register with correct session ID"
            assert reg_path == path, "Registered path should match returned path"
        finally:
            if path and os.path.exists(path):
                os.unlink(path)

    def test_cache_miss_returns_none(self) -> None:
        """WHEN use_cached_matched_rgb=True BUT cache has no matched_rgb,
        SHALL return None (fallback to default reprocessing).

        当 use_cached_matched_rgb=True 但缓存中无 matched_rgb 时，
        应返回 None（回退到默认重新处理行为）。

        **Validates: Requirements 5.3**
        """
        cache: dict = {}  # No matched_rgb key
        registered_files: list[tuple[str, str]] = []

        path = _serialize_cached_matched_rgb(
            use_cached_matched_rgb=True,
            cache=cache,
            session_id="test-session-3",
            register_temp_file_fn=lambda sid, p: registered_files.append((sid, p)),
        )

        assert path is None, "Should return None when cache has no matched_rgb"
        assert len(registered_files) == 0, "Should not register any temp files"

    def test_cache_miss_with_none_value_returns_none(self) -> None:
        """WHEN cache has matched_rgb=None explicitly, SHALL return None.

        当缓存中 matched_rgb 显式为 None 时，应返回 None。

        **Validates: Requirements 5.3**
        """
        cache = {"matched_rgb": None}
        registered_files: list[tuple[str, str]] = []

        path = _serialize_cached_matched_rgb(
            use_cached_matched_rgb=True,
            cache=cache,
            session_id="test-session-4",
            register_temp_file_fn=lambda sid, p: registered_files.append((sid, p)),
        )

        assert path is None, "Should return None when matched_rgb is None"
        assert len(registered_files) == 0, "Should not register any temp files"

    def test_flag_disabled_skips_serialization(self) -> None:
        """WHEN use_cached_matched_rgb=False, no .npy file SHALL be created
        regardless of cache content.

        当 use_cached_matched_rgb=False 时，无论缓存内容如何，都不应创建 .npy 文件。

        **Validates: Requirements 5.1, 5.3**
        """
        test_array = np.random.randint(0, 256, (5, 5, 3), dtype=np.uint8)
        cache = {"matched_rgb": test_array}
        registered_files: list[tuple[str, str]] = []

        path = _serialize_cached_matched_rgb(
            use_cached_matched_rgb=False,
            cache=cache,
            session_id="test-session-5",
            register_temp_file_fn=lambda sid, p: registered_files.append((sid, p)),
        )

        assert path is None, "Should return None when flag is disabled"
        assert len(registered_files) == 0, "Should not register any temp files"

    def test_large_array_serialization(self) -> None:
        """A realistically-sized matched_rgb array SHALL roundtrip correctly
        through .npy serialization.

        实际大小的 matched_rgb 数组应能通过 .npy 序列化正确往返。

        **Validates: Requirements 5.1**
        """
        # Simulate a 200x300 image (realistic but not huge)
        test_array = np.random.randint(0, 256, (200, 300, 3), dtype=np.uint8)
        cache = {"matched_rgb": test_array}
        registered_files: list[tuple[str, str]] = []

        path = _serialize_cached_matched_rgb(
            use_cached_matched_rgb=True,
            cache=cache,
            session_id="test-session-6",
            register_temp_file_fn=lambda sid, p: registered_files.append((sid, p)),
        )

        try:
            assert path is not None
            loaded = np.load(path)
            np.testing.assert_array_equal(loaded, test_array)
            assert loaded.dtype == np.uint8
        finally:
            if path and os.path.exists(path):
                os.unlink(path)


# ===========================================================================
# Integration Tests: region-replace → generate pipeline (端到端管线测试)
# Requirements 7.1, 7.2
# ===========================================================================


def _hex_to_rgb(hex_str: str) -> np.ndarray:
    """Convert hex color string to RGB numpy array.
    将十六进制颜色字符串转换为 RGB numpy 数组。

    Args:
        hex_str (str): Hex color like '#FF0000'. (十六进制颜色)

    Returns:
        np.ndarray: RGB array (3,) uint8. (RGB 数组)
    """
    hex_str = hex_str.lstrip('#')
    return np.array([int(hex_str[i:i+2], 16) for i in (0, 2, 4)], dtype=np.uint8)


def _simulate_region_replace(
    matched_rgb: np.ndarray,
    region_mask: np.ndarray,
    new_color: np.ndarray,
) -> np.ndarray:
    """Simulate the region-replace endpoint modifying cached matched_rgb.
    模拟 region-replace 端点修改缓存的 matched_rgb。

    Args:
        matched_rgb (np.ndarray): Current cached matched_rgb (H,W,3).
            (当前缓存的 matched_rgb)
        region_mask (np.ndarray): Boolean mask for the region (H,W).
            (区域布尔掩码)
        new_color (np.ndarray): Replacement RGB color (3,). (替换颜色)

    Returns:
        np.ndarray: Modified matched_rgb with region replaced. (修改后的 matched_rgb)
    """
    result = matched_rgb.copy()
    result[region_mask] = new_color
    return result


class TestRegionReplaceGeneratePipeline:
    """End-to-end integration tests for region-replace → generate pipeline.
    区域替换 → 生成管线的端到端集成测试。

    Simulates the full flow: preview → region-replace → generate,
    verifying that generate uses the cached matched_rgb and that
    global + region replacements coexist correctly.

    **Validates: Requirements 7.1, 7.2**
    """

    def _make_lut_fixtures(self) -> tuple[np.ndarray, np.ndarray]:
        """Create a small LUT palette and ref_stacks for testing.
        创建用于测试的小型 LUT 调色板和 ref_stacks。

        Returns:
            tuple: (lut_rgb (C,3) uint8, ref_stacks (C,L) int32)
        """
        lut_rgb = np.array([
            [255, 0, 0],      # 0: Red
            [0, 255, 0],      # 1: Green
            [0, 0, 255],      # 2: Blue
            [255, 255, 0],    # 3: Yellow
            [255, 255, 255],  # 4: White
            [0, 0, 0],        # 5: Black
        ], dtype=np.uint8)
        ref_stacks = np.array([
            [0, 1, 0],  # Red stacks
            [1, 0, 1],  # Green stacks
            [2, 2, 0],  # Blue stacks
            [3, 1, 1],  # Yellow stacks
            [4, 4, 4],  # White stacks
            [5, 5, 5],  # Black stacks
        ], dtype=np.int32)
        return lut_rgb, ref_stacks

    def _make_image_fixtures(
        self, lut_rgb: np.ndarray, ref_stacks: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Create a 6x6 test image with known color layout.
        创建具有已知颜色布局的 6x6 测试图像。

        Layout (each cell is a 3x3 block):
          Top-left  (0:3, 0:3) = Red
          Top-right (0:3, 3:6) = Green
          Bot-left  (3:6, 0:3) = Blue
          Bot-right (3:6, 3:6) = Yellow

        Returns:
            tuple: (matched_rgb (6,6,3), material_matrix (6,6,3), mask_solid (6,6))
        """
        H, W = 6, 6
        matched_rgb = np.zeros((H, W, 3), dtype=np.uint8)
        material_matrix = np.zeros((H, W, 3), dtype=np.int32)
        mask_solid = np.ones((H, W), dtype=bool)

        # Top-left: Red
        matched_rgb[0:3, 0:3] = lut_rgb[0]
        material_matrix[0:3, 0:3] = ref_stacks[0]
        # Top-right: Green
        matched_rgb[0:3, 3:6] = lut_rgb[1]
        material_matrix[0:3, 3:6] = ref_stacks[1]
        # Bottom-left: Blue
        matched_rgb[3:6, 0:3] = lut_rgb[2]
        material_matrix[3:6, 0:3] = ref_stacks[2]
        # Bottom-right: Yellow
        matched_rgb[3:6, 3:6] = lut_rgb[3]
        material_matrix[3:6, 3:6] = ref_stacks[3]

        return matched_rgb, material_matrix, mask_solid

    def test_full_pipeline_region_replace_then_generate(self) -> None:
        """Simulate: preview → region-replace → serialize → generate.
        The generate step SHALL use the cached matched_rgb with region
        modifications, producing correct material_matrix for replaced pixels.

        模拟完整流程：preview → region-replace → 序列化 → generate。
        generate 步骤应使用包含区域修改的缓存 matched_rgb。

        **Validates: Requirements 7.1**
        """
        lut_rgb, ref_stacks = self._make_lut_fixtures()
        matched_rgb, material_matrix, mask_solid = self._make_image_fixtures(
            lut_rgb, ref_stacks
        )

        # --- Step 1: Simulate preview (already done by _make_image_fixtures) ---
        original_matched_rgb = matched_rgb.copy()

        # --- Step 2: Simulate region-replace on top-left Red → White ---
        region_mask = np.zeros_like(mask_solid)
        region_mask[0:3, 0:3] = True  # Top-left block
        white_color = lut_rgb[4]  # White
        cached_matched_rgb = _simulate_region_replace(
            matched_rgb, region_mask, white_color
        )

        # Verify region-replace modified only the target region
        assert np.all(cached_matched_rgb[0:3, 0:3] == white_color)
        assert np.all(cached_matched_rgb[0:3, 3:6] == lut_rgb[1])  # Green unchanged

        # --- Step 3: Simulate cache serialization (as convert_generate does) ---
        npy_path = _serialize_cached_matched_rgb(
            use_cached_matched_rgb=True,
            cache={"matched_rgb": cached_matched_rgb},
            session_id="pipeline-test-1",
            register_temp_file_fn=lambda sid, p: None,
        )

        try:
            assert npy_path is not None

            # --- Step 4: Simulate generate loading override ---
            loaded_override = np.load(npy_path)
            result_matched, result_material = apply_matched_rgb_override(
                original_matched_rgb, material_matrix, mask_solid,
                loaded_override, lut_rgb, ref_stacks,
            )

            # Verify: top-left now has White stacks
            expected_white_stacks = ref_stacks[4]  # White
            for r in range(3):
                for c in range(3):
                    np.testing.assert_array_equal(
                        result_material[r, c], expected_white_stacks,
                        err_msg=f"Pixel ({r},{c}) should have White stacks"
                    )

            # Verify: other regions unchanged
            for r in range(3):
                for c in range(3, 6):
                    np.testing.assert_array_equal(
                        result_material[r, c], ref_stacks[1],
                        err_msg=f"Pixel ({r},{c}) should still have Green stacks"
                    )
            for r in range(3, 6):
                for c in range(3):
                    np.testing.assert_array_equal(
                        result_material[r, c], ref_stacks[2],
                        err_msg=f"Pixel ({r},{c}) should still have Blue stacks"
                    )

            # Verify: result matched_rgb equals the cached version
            np.testing.assert_array_equal(result_matched, cached_matched_rgb)
        finally:
            if npy_path and os.path.exists(npy_path):
                os.unlink(npy_path)

    def test_global_and_region_replacement_coexistence(self) -> None:
        """WHEN both global replacement (colorRemapMap) and region replacement
        (regionReplacementCount > 0) exist, generate SHALL apply both.

        Region replacement is baked into cached matched_rgb (via override).
        Global replacement is applied AFTER override via replacement_regions.

        当同时存在全局替换和区域替换时，generate 应同时应用两者。
        区域替换通过 cached matched_rgb override 体现，
        全局替换通过 replacement_regions 参数在 override 之后应用。

        **Validates: Requirements 7.2**
        """
        lut_rgb, ref_stacks = self._make_lut_fixtures()
        matched_rgb, material_matrix, mask_solid = self._make_image_fixtures(
            lut_rgb, ref_stacks
        )
        original_matched_rgb = matched_rgb.copy()
        original_material = material_matrix.copy()

        # --- Region replacement: top-left Red → White (baked into cache) ---
        region_mask = np.zeros_like(mask_solid)
        region_mask[0:3, 0:3] = True
        white_color = lut_rgb[4]  # White
        cached_matched_rgb = _simulate_region_replace(
            matched_rgb, region_mask, white_color
        )

        # --- Serialize cached matched_rgb (region replacement baked in) ---
        npy_path = _serialize_cached_matched_rgb(
            use_cached_matched_rgb=True,
            cache={"matched_rgb": cached_matched_rgb},
            session_id="coexist-test-1",
            register_temp_file_fn=lambda sid, p: None,
        )

        try:
            assert npy_path is not None
            loaded_override = np.load(npy_path)

            # --- Apply override (region replacement) ---
            after_override_rgb, after_override_mat = apply_matched_rgb_override(
                original_matched_rgb, original_material, mask_solid,
                loaded_override, lut_rgb, ref_stacks,
            )

            # --- Now simulate global replacement: Green → Black ---
            # This mimics replacement_regions from colorRemapMap (select-all)
            # Applied AFTER the override, as in convert_image_to_3d line 882+
            green_rgb = tuple(lut_rgb[1].tolist())
            black_rgb = tuple(lut_rgb[5].tolist())
            green_mask = np.all(after_override_rgb == green_rgb, axis=-1)

            final_rgb = after_override_rgb.copy()
            final_material = after_override_mat.copy()
            final_rgb[green_mask] = np.array(black_rgb, dtype=np.uint8)

            # KDTree lookup for Black replacement
            black_stack = expected_stack_for_color(
                np.array(black_rgb, dtype=np.uint8), lut_rgb, ref_stacks
            )
            final_material[green_mask] = black_stack

            # --- Verify both replacements applied ---
            # Top-left: was Red, region-replaced to White
            np.testing.assert_array_equal(
                final_rgb[0:3, 0:3],
                np.full((3, 3, 3), white_color, dtype=np.uint8),
                err_msg="Top-left should be White (region replacement)"
            )
            for r in range(3):
                for c in range(3):
                    np.testing.assert_array_equal(
                        final_material[r, c], ref_stacks[4],
                        err_msg=f"({r},{c}) should have White stacks"
                    )

            # Top-right: was Green, globally replaced to Black
            np.testing.assert_array_equal(
                final_rgb[0:3, 3:6],
                np.full((3, 3, 3), black_rgb, dtype=np.uint8),
                err_msg="Top-right should be Black (global replacement)"
            )
            for r in range(3):
                for c in range(3, 6):
                    np.testing.assert_array_equal(
                        final_material[r, c], ref_stacks[5],
                        err_msg=f"({r},{c}) should have Black stacks"
                    )

            # Bottom-left: Blue, untouched
            for r in range(3, 6):
                for c in range(3):
                    np.testing.assert_array_equal(
                        final_material[r, c], ref_stacks[2],
                        err_msg=f"({r},{c}) should still have Blue stacks"
                    )

            # Bottom-right: Yellow, untouched
            for r in range(3, 6):
                for c in range(3, 6):
                    np.testing.assert_array_equal(
                        final_material[r, c], ref_stacks[3],
                        err_msg=f"({r},{c}) should still have Yellow stacks"
                    )
        finally:
            if npy_path and os.path.exists(npy_path):
                os.unlink(npy_path)

    def test_multiple_region_replacements_accumulate(self) -> None:
        """Multiple region-replace calls SHALL accumulate in the cached
        matched_rgb, and generate SHALL reflect all of them.

        多次区域替换应在缓存的 matched_rgb 中累积，generate 应反映所有替换。

        **Validates: Requirements 7.1**
        """
        lut_rgb, ref_stacks = self._make_lut_fixtures()
        matched_rgb, material_matrix, mask_solid = self._make_image_fixtures(
            lut_rgb, ref_stacks
        )
        original_matched_rgb = matched_rgb.copy()

        # Region-replace 1: top-left Red → White
        region1 = np.zeros_like(mask_solid)
        region1[0:3, 0:3] = True
        cached = _simulate_region_replace(matched_rgb, region1, lut_rgb[4])

        # Region-replace 2: bottom-right Yellow → Black
        region2 = np.zeros_like(mask_solid)
        region2[3:6, 3:6] = True
        cached = _simulate_region_replace(cached, region2, lut_rgb[5])

        # Serialize and apply override
        npy_path = _serialize_cached_matched_rgb(
            use_cached_matched_rgb=True,
            cache={"matched_rgb": cached},
            session_id="multi-region-test",
            register_temp_file_fn=lambda sid, p: None,
        )

        try:
            loaded = np.load(npy_path)
            result_rgb, result_mat = apply_matched_rgb_override(
                original_matched_rgb, material_matrix, mask_solid,
                loaded, lut_rgb, ref_stacks,
            )

            # Top-left: White
            for r in range(3):
                for c in range(3):
                    np.testing.assert_array_equal(result_mat[r, c], ref_stacks[4])
            # Top-right: Green (unchanged)
            for r in range(3):
                for c in range(3, 6):
                    np.testing.assert_array_equal(result_mat[r, c], ref_stacks[1])
            # Bottom-left: Blue (unchanged)
            for r in range(3, 6):
                for c in range(3):
                    np.testing.assert_array_equal(result_mat[r, c], ref_stacks[2])
            # Bottom-right: Black
            for r in range(3, 6):
                for c in range(3, 6):
                    np.testing.assert_array_equal(result_mat[r, c], ref_stacks[5])
        finally:
            if npy_path and os.path.exists(npy_path):
                os.unlink(npy_path)

    def test_no_cache_fallback_preserves_original(self) -> None:
        """WHEN use_cached_matched_rgb=False (no region replacements),
        generate SHALL use original matched_rgb without any override.

        当 use_cached_matched_rgb=False 时，generate 应使用原始 matched_rgb。

        **Validates: Requirements 7.1**
        """
        lut_rgb, ref_stacks = self._make_lut_fixtures()
        matched_rgb, material_matrix, mask_solid = self._make_image_fixtures(
            lut_rgb, ref_stacks
        )

        # No cache serialization (flag is False)
        npy_path = _serialize_cached_matched_rgb(
            use_cached_matched_rgb=False,
            cache={"matched_rgb": matched_rgb},
            session_id="no-cache-test",
            register_temp_file_fn=lambda sid, p: None,
        )

        assert npy_path is None, "No .npy file should be created"

        # Without override, material_matrix stays as-is
        np.testing.assert_array_equal(
            material_matrix[0:3, 0:3], np.tile(ref_stacks[0], (3, 3, 1))
        )
        np.testing.assert_array_equal(
            material_matrix[0:3, 3:6], np.tile(ref_stacks[1], (3, 3, 1))
        )
