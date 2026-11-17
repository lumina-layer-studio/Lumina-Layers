"""
Lumina Studio - 高度图浮雕模式单元测试
测试 HeightmapLoader 的灰度映射、彩色图转灰度、尺寸缩放，
以及 _build_relief_voxel_matrix 的高度钳制逻辑和错误处理。
"""

import os
import tempfile
import numpy as np
import cv2
import pytest

from core.heightmap_loader import HeightmapLoader
from config import PrinterConfig


# ========== 常量 ==========
OPTICAL_LAYERS = 5
LAYER_HEIGHT = PrinterConfig.LAYER_HEIGHT  # 0.08mm
OPTICAL_THICKNESS_MM = OPTICAL_LAYERS * LAYER_HEIGHT  # 0.4mm


@pytest.mark.parametrize("channels", [1, 3, 4])
def test_uint16_png_preserves_smooth_absolute_heights(tmp_path, channels):
    # Exercise decoding, not just an array helper: uploaded PNGs retain bit depth.
    row = np.linspace(0, 65535, 600).astype(np.uint16)
    image = np.tile(row, (8, 1))
    if channels > 1:
        image = np.repeat(image[..., None], channels, axis=2)
        if channels == 4:
            image[..., 3] = 65535
    path = tmp_path / "heightmap16.png"
    assert cv2.imwrite(str(path), image)

    result = HeightmapLoader.load_and_validate(str(path))
    expected = np.rint(row / 257.0).astype(np.uint8)
    assert result["success"]
    np.testing.assert_array_equal(result["grayscale"][0], expected)
    assert np.all(np.diff(result["thumbnail"][0].astype(int)) >= 0)

    processed = HeightmapLoader.load_and_process(str(path), 600, 8, 3.0, 0.08)
    np.testing.assert_allclose(
        processed["height_matrix"][0], 0.08 + expected / 255.0 * 2.92,
        atol=1e-6,
    )


@pytest.mark.parametrize("values", [[32768, 32768], [16384, 16448]])
def test_uint16_heightmap_does_not_stretch_image_contrast(tmp_path, values):
    path = tmp_path / "low_contrast16.png"
    image = np.array([values], dtype=np.uint16)
    assert cv2.imwrite(str(path), image)
    result = HeightmapLoader.load_and_validate(str(path))
    np.testing.assert_array_equal(
        result["grayscale"], np.rint(image / 257.0).astype(np.uint8),
    )


@pytest.mark.parametrize("channels", [1, 3, 4])
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_heightmap_retains_existing_channel_interpretation(channels, dtype):
    image = np.arange(24, dtype=np.uint8).reshape(2, 4, 3) * 10
    if channels == 1:
        image = image[..., 0]
    elif channels == 4:
        image = np.concatenate([image, np.full((2, 4, 1), 255, np.uint8)], axis=2)
    image = image.astype(dtype)
    if dtype == np.uint16:
        image *= 257
    if channels == 1:
        expected = image
    elif channels == 3:
        expected = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        expected = cv2.cvtColor(
            cv2.cvtColor(image, cv2.COLOR_RGBA2BGR), cv2.COLOR_BGR2GRAY,
        )
    if dtype == np.uint16:
        expected = np.rint(expected / 257.0).astype(np.uint8)
    np.testing.assert_array_equal(HeightmapLoader._to_grayscale(image), expected)


# ========== 9.1 灰度映射边界条件 (需求 3.1) ==========

class TestGrayscaleMapping:
    """灰度映射边界条件测试"""

    def test_pure_black_maps_to_base_thickness(self):
        """纯黑图（全 0）映射为底板厚度"""
        grayscale = np.zeros((10, 10), dtype=np.uint8)
        max_height = 5.0
        base_thickness = 1.0

        result = HeightmapLoader._map_grayscale_to_height(grayscale, max_height, base_thickness)

        np.testing.assert_allclose(result, base_thickness, atol=1e-5)
        assert result.dtype == np.float32

    def test_pure_white_maps_to_max_height(self):
        """纯白图（全 255）映射为最大高度"""
        grayscale = np.full((10, 10), 255, dtype=np.uint8)
        max_height = 5.0
        base_thickness = 1.0

        result = HeightmapLoader._map_grayscale_to_height(grayscale, max_height, base_thickness)

        np.testing.assert_allclose(result, max_height, atol=1e-5)

    def test_mid_gray_maps_to_middle_value(self):
        """中灰图（128）映射为中间值"""
        grayscale = np.full((10, 10), 128, dtype=np.uint8)
        max_height = 5.0
        base_thickness = 1.0

        result = HeightmapLoader._map_grayscale_to_height(grayscale, max_height, base_thickness)

        # 公式: height = 1.0 + (128/255) * (5.0 - 1.0)
        expected = base_thickness + (128.0 / 255.0) * (max_height - base_thickness)
        np.testing.assert_allclose(result, expected, atol=1e-4)


# ========== 9.2 彩色图转灰度 (需求 1.2) ==========

class TestColorToGrayscale:
    """彩色图转灰度测试"""

    def test_rgb_image_converts_to_grayscale(self):
        """验证 RGB 图像正确转换为灰度"""
        bgr_image = np.zeros((10, 10, 3), dtype=np.uint8)
        bgr_image[:, :, 0] = 100  # B
        bgr_image[:, :, 1] = 150  # G
        bgr_image[:, :, 2] = 200  # R

        result = HeightmapLoader._to_grayscale(bgr_image)

        assert result.ndim == 2
        assert result.shape == (10, 10)
        assert result.dtype == np.uint8
        assert np.mean(result) > 0

    def test_rgba_image_converts_to_grayscale(self):
        """验证 RGBA 图像正确处理 alpha 通道"""
        rgba_image = np.zeros((10, 10, 4), dtype=np.uint8)
        rgba_image[:, :, 0] = 100  # R
        rgba_image[:, :, 1] = 150  # G
        rgba_image[:, :, 2] = 200  # B
        rgba_image[:, :, 3] = 255  # A

        result = HeightmapLoader._to_grayscale(rgba_image)

        assert result.ndim == 2
        assert result.shape == (10, 10)
        assert result.dtype == np.uint8
        assert np.mean(result) > 0

    def test_grayscale_image_passthrough(self):
        """验证灰度图直接返回"""
        gray_image = np.full((10, 10), 128, dtype=np.uint8)

        result = HeightmapLoader._to_grayscale(gray_image)

        assert result.ndim == 2
        np.testing.assert_array_equal(result, gray_image)


# ========== 9.3 尺寸缩放 (需求 2.1, 2.3) ==========

class TestResizeToTarget:
    """尺寸缩放测试"""

    def test_resize_different_sizes(self):
        """验证不同尺寸高度图正确缩放至目标尺寸"""
        grayscale = np.random.randint(0, 256, (100, 200), dtype=np.uint8)
        target_w, target_h = 50, 30

        result = HeightmapLoader._resize_to_target(grayscale, target_w, target_h)

        assert result.shape == (target_h, target_w)
        assert result.dtype == np.uint8

    def test_resize_upscale(self):
        """验证小图放大到目标尺寸"""
        grayscale = np.random.randint(0, 256, (10, 10), dtype=np.uint8)
        target_w, target_h = 100, 80

        result = HeightmapLoader._resize_to_target(grayscale, target_w, target_h)

        assert result.shape == (target_h, target_w)

    def test_resize_preserves_shape(self):
        """验证缩放后形状为 (target_h, target_w)"""
        grayscale = np.random.randint(0, 256, (64, 48), dtype=np.uint8)
        target_w, target_h = 32, 24

        result = HeightmapLoader._resize_to_target(grayscale, target_w, target_h)

        assert result.shape == (target_h, target_w)
        assert result.shape[0] == target_h
        assert result.shape[1] == target_w


# ========== 9.4 高度钳制 (需求 4.5) ==========

class TestHeightClamping:
    """高度钳制测试：验证高度值小于 OPTICAL_LAYERS 厚度时被钳制为最小值"""

    @pytest.mark.parametrize("mode", ["color", "heightmap"])
    def test_bare_relief_has_no_optical_layers_and_uses_its_own_height(self, mode: str) -> None:
        from core.converter import _build_relief_voxel_matrix

        # Paint on backing, thin backing, true hole, paint alone and tall backing.
        color = np.array([[True, False, False, True, False]])
        backing = np.array([[True, True, False, False, True]])
        heights = np.array([[0.64, 0.16, 2.4, 0.64, 1.12]], dtype=np.float32)
        voxels, metadata = _build_relief_voxel_matrix(
            matched_rgb=np.zeros((1, 5, 3), dtype=np.uint8),
            material_matrix=np.full((1, 5, 5), 3), mask_solid=color, backing_mask=backing,
            color_height_map={"#000000": 0.64}, default_height=1.2,
            structure_mode="Single-sided", backing_color_id=7, pixel_scale=0.1,
            height_matrix=heights if mode == "heightmap" else None,
            global_max_height=None if mode == "heightmap" else 0.64,
        )
        thin_layers, tall_layers = (2, 14) if mode == "heightmap" else (15, 15)
        np.testing.assert_array_equal(voxels[:8, 0, 0], [7, 7, 7, 3, 3, 3, 3, 3])
        np.testing.assert_array_equal(voxels[:, 0, 1], np.where(np.arange(len(voxels)) < thin_layers, 7, -1))
        assert np.all(voxels[:, 0, 2] == -1)
        np.testing.assert_array_equal(voxels[:8, 0, 3], [-1, -1, -1, 3, 3, 3, 3, 3])
        assert len(voxels) == tall_layers and np.all(voxels[:, 0, 4] == 7)
        assert metadata["backing_z_range"] == (0, tall_layers - 1)
        np.testing.assert_array_equal(metadata["backing_z_max_map"], [[2, thin_layers - 1, -1, -1, tall_layers - 1]])
        np.testing.assert_array_equal(metadata["backing_z_min_map"], [[0, 0, -1, -1, 0]])

    def test_height_below_optical_thickness_is_clamped(self):
        """验证高度值小于 OPTICAL_LAYERS 厚度（0.4mm）时被钳制为最小值"""
        from core.converter import _build_relief_voxel_matrix

        h, w = 3, 3
        matched_rgb = np.full((h, w, 3), 128, dtype=np.uint8)
        material_matrix = np.zeros((h, w, 5), dtype=int)
        for layer in range(5):
            material_matrix[:, :, layer] = layer % 4
        mask_solid = np.ones((h, w), dtype=bool)

        # 高度矩阵：所有值都低于 OPTICAL_THICKNESS_MM (0.4mm)
        height_matrix = np.full((h, w), 0.1, dtype=np.float32)

        full_matrix, metadata = _build_relief_voxel_matrix(
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            color_height_map={},
            default_height=1.0,
            structure_mode="Single-sided",
            backing_color_id=0,
            pixel_scale=0.5,
            height_matrix=height_matrix
        )

        # 验证体素矩阵至少有 OPTICAL_LAYERS 层
        assert full_matrix.shape[0] >= OPTICAL_LAYERS

        # 验证每个实心像素至少有 OPTICAL_LAYERS 层被填充（非 -1）
        for y in range(h):
            for x in range(w):
                filled_layers = np.sum(full_matrix[:, y, x] != -1)
                assert filled_layers >= OPTICAL_LAYERS, (
                    f"像素 ({y},{x}) 只有 {filled_layers} 层被填充，"
                    f"应至少有 {OPTICAL_LAYERS} 层"
                )

    def test_relief_preserves_material_archive_layers_above_five(self):
        """Material-archive relief must preserve every optical layer.

        耗材档案浮雕不能把 6 层以上的叠色截断为传统 5 层。
        """
        from core.converter import _build_relief_voxel_matrix

        matched_rgb = np.array([[[255, 0, 0]]], dtype=np.uint8)
        material_matrix = np.arange(10, dtype=np.int32).reshape(1, 1, 10)
        mask_solid = np.array([[True]])

        full_matrix, _metadata = _build_relief_voxel_matrix(
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            color_height_map={"ff0000": 1.2},
            default_height=0.4,
            structure_mode="Single-sided",
            backing_color_id=99,
            pixel_scale=0.5,
        )

        filled_column = full_matrix[:, 0, 0]
        optical_layers = [
            int(value)
            for value in filled_column
            if value not in (-1, 99)
        ]

        assert optical_layers == list(reversed(range(10)))

    def test_relief_preserves_material_archive_layers_in_heightmap_mode(self):
        """Heightmap relief uses the same dynamic optical layer depth."""
        from core.converter import _build_relief_voxel_matrix

        matched_rgb = np.array([[[255, 0, 0]]], dtype=np.uint8)
        material_matrix = np.arange(10, dtype=np.int32).reshape(1, 1, 10)
        mask_solid = np.array([[True]])
        height_matrix = np.array([[1.2]], dtype=np.float32)

        full_matrix, _metadata = _build_relief_voxel_matrix(
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            color_height_map={},
            default_height=0.4,
            structure_mode="Single-sided",
            backing_color_id=99,
            pixel_scale=0.5,
            height_matrix=height_matrix,
        )

        filled_column = full_matrix[:, 0, 0]
        optical_layers = [
            int(value)
            for value in filled_column
            if value not in (-1, 99)
        ]

        assert optical_layers == list(reversed(range(10)))

    def test_relief_keeps_legacy_five_layer_order(self):
        """Legacy five-layer relief still writes top-to-bottom as 4..0."""
        from core.converter import _build_relief_voxel_matrix

        matched_rgb = np.array([[[255, 0, 0]]], dtype=np.uint8)
        material_matrix = np.arange(5, dtype=np.int32).reshape(1, 1, 5)
        mask_solid = np.array([[True]])

        full_matrix, _metadata = _build_relief_voxel_matrix(
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            color_height_map={"ff0000": 0.6},
            default_height=0.4,
            structure_mode="Single-sided",
            backing_color_id=99,
            pixel_scale=0.5,
        )

        filled_column = full_matrix[:, 0, 0]
        optical_layers = [
            int(value)
            for value in filled_column
            if value not in (-1, 99)
        ]

        assert optical_layers == [4, 3, 2, 1, 0]

    def test_relief_uses_stable_height_identity_when_two_sources_share_achieved_rgb(self):
        """Display-colour collisions must not collapse distinct source heights."""
        from core.converter import _build_relief_voxel_matrix

        achieved_rgb = np.array([244, 100, 41], dtype=np.uint8)
        source_low = np.array([190, 230, 248], dtype=np.uint8)
        source_high = np.array([17, 34, 51], dtype=np.uint8)
        matched_rgb = np.array([[achieved_rgb, achieved_rgb]], dtype=np.uint8)
        height_identity_rgb = np.array(
            [[source_low, source_high]],
            dtype=np.uint8,
        )
        material_matrix = np.zeros((1, 2, 5), dtype=np.int32)
        mask_solid = np.ones((1, 2), dtype=bool)

        full_matrix, _metadata = _build_relief_voxel_matrix(
            matched_rgb=matched_rgb,
            height_identity_rgb=height_identity_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            color_height_map={"bee6f8": 0.48, "112233": 2.0},
            default_height=0.4,
            structure_mode="Single-sided",
            backing_color_id=9,
            pixel_scale=0.5,
        )

        assert np.count_nonzero(full_matrix[:, 0, 0] != -1) == 6
        assert np.count_nonzero(full_matrix[:, 0, 1] != -1) == 25

    def test_relief_region_replace_keeps_source_identity_for_changed_and_unchanged_pixels(self):
        """Replacing one region must leave both pixels on their original height."""
        from core.converter import _build_relief_voxel_matrix

        source_rgb = np.array([190, 230, 248], dtype=np.uint8)
        achieved_rgb = np.array([244, 100, 41], dtype=np.uint8)
        matched_rgb = np.array([[achieved_rgb, source_rgb]], dtype=np.uint8)
        height_identity_rgb = np.array([[source_rgb, source_rgb]], dtype=np.uint8)
        material_matrix = np.zeros((1, 2, 5), dtype=np.int32)
        mask_solid = np.ones((1, 2), dtype=bool)

        full_matrix, _metadata = _build_relief_voxel_matrix(
            matched_rgb=matched_rgb,
            height_identity_rgb=height_identity_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            color_height_map={"bee6f8": 0.48},
            default_height=0.4,
            structure_mode="Single-sided",
            backing_color_id=9,
            pixel_scale=0.5,
        )

        filled_heights = [
            np.count_nonzero(full_matrix[:, 0, x] != -1) for x in range(2)
        ]
        assert filled_heights == [6, 6]


# ========== 9.5 错误处理 (需求 8.1, 8.2, 8.3) ==========

class TestErrorHandling:
    """错误处理测试"""

    def test_invalid_file_returns_error(self):
        """验证无效文件返回描述性错误 (需求 8.1)"""
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(b'this is not a valid image file')
            tmp_path = f.name

        try:
            result = HeightmapLoader.load_and_validate(tmp_path)
            assert result['success'] is False
            assert result['error'] is not None
            assert len(result['error']) > 0
        finally:
            os.unlink(tmp_path)

    def test_nonexistent_file_returns_error(self):
        """验证不存在的文件返回描述性错误"""
        result = HeightmapLoader.load_and_validate('/nonexistent/path/image.png')
        assert result['success'] is False
        assert result['error'] is not None

    def test_aspect_ratio_deviation_warning(self):
        """验证宽高比偏差超过 20% 时返回警告 (需求 8.2)"""
        warning = HeightmapLoader._check_aspect_ratio(100, 50, 100, 100)
        assert warning is not None
        assert "⚠️" in warning

    def test_aspect_ratio_no_warning_when_close(self):
        """验证宽高比偏差小于 20% 时不返回警告"""
        warning = HeightmapLoader._check_aspect_ratio(100, 100, 110, 100)
        assert warning is None

    def test_low_contrast_warning(self):
        """验证低对比度（标准差 < 1.0）时返回警告 (需求 8.3)"""
        grayscale = np.zeros((10, 10), dtype=np.uint8)
        warning = HeightmapLoader._check_contrast(grayscale)
        assert warning is not None
        assert "[WARNING]" in warning

    def test_no_contrast_warning_for_normal_image(self):
        """验证正常对比度图像不返回警告"""
        grayscale = np.zeros((10, 10), dtype=np.uint8)
        grayscale[:5, :] = 0
        grayscale[5:, :] = 255
        warning = HeightmapLoader._check_contrast(grayscale)
        assert warning is None
