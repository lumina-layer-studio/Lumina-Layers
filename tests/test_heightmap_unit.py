"""
Lumina Studio - 高度图浮雕模式单元测试

测试 HeightmapLoader 的灰度映射、彩色图转灰度、尺寸缩放、
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


# ========== 9.1 灰度映射边界条件 (需求 3.1) ==========

class TestGrayscaleMapping:
    """灰度映射边界条件测试"""

    def test_pure_black_maps_to_max_height(self):
        """纯黑图（全 0）映射为最大高度"""
        grayscale = np.zeros((10, 10), dtype=np.uint8)
        max_height = 5.0
        base_thickness = 1.0

        result = HeightmapLoader._map_grayscale_to_height(grayscale, max_height, base_thickness)

        np.testing.assert_allclose(result, max_height, atol=1e-5)
        assert result.dtype == np.float32

    def test_pure_white_maps_to_base_thickness(self):
        """纯白图（全 255）映射为底板厚度"""
        grayscale = np.full((10, 10), 255, dtype=np.uint8)
        max_height = 5.0
        base_thickness = 1.0

        result = HeightmapLoader._map_grayscale_to_height(grayscale, max_height, base_thickness)

        np.testing.assert_allclose(result, base_thickness, atol=1e-5)

    def test_mid_gray_maps_to_middle_value(self):
        """中灰图（128）映射为中间值"""
        grayscale = np.full((10, 10), 128, dtype=np.uint8)
        max_height = 5.0
        base_thickness = 1.0

        result = HeightmapLoader._map_grayscale_to_height(grayscale, max_height, base_thickness)

        # 公式: height = 5.0 - (128/255) * (5.0 - 1.0)
        expected = max_height - (128.0 / 255.0) * (max_height - base_thickness)
        np.testing.assert_allclose(result, expected, atol=1e-4)


# ========== 9.2 彩色图转灰度 (需求 1.2) ==========

class TestColorToGrayscale:
    """彩色图转灰度测试"""

    def test_rgb_image_converts_to_grayscale(self):
        """验证 RGB 图像正确转换为灰度"""
        # 创建一个简单的 BGR 图像（cv2 默认格式）
        bgr_image = np.zeros((10, 10, 3), dtype=np.uint8)
        bgr_image[:, :, 0] = 100  # B
        bgr_image[:, :, 1] = 150  # G
        bgr_image[:, :, 2] = 200  # R

        result = HeightmapLoader._to_grayscale(bgr_image)

        assert result.ndim == 2
        assert result.shape == (10, 10)
        assert result.dtype == np.uint8
        # 灰度值应该是 BGR 加权平均，不应全为 0
        assert np.mean(result) > 0

    def test_rgba_image_converts_to_grayscale(self):
        """验证 RGBA 图像正确处理 alpha 通道"""
        # 创建 RGBA 图像
        rgba_image = np.zeros((10, 10, 4), dtype=np.uint8)
        rgba_image[:, :, 0] = 100  # R (在 RGBA 格式中)
        rgba_image[:, :, 1] = 150  # G
        rgba_image[:, :, 2] = 200  # B
        rgba_image[:, :, 3] = 255  # A (完全不透明)

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

    def test_height_below_optical_thickness_is_clamped(self):
        """验证高度值小于 OPTICAL_LAYERS 厚度（0.4mm）时被钳制为最小值"""
        from core.converter import _build_relief_voxel_matrix

        # 创建一个 3x3 的简单场景
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
        # 高度图 100x50 (ratio=2.0), 目标 100x100 (ratio=1.0)
        # 偏差 = |2.0 - 1.0| / 1.0 = 1.0 = 100% > 20%
        warning = HeightmapLoader._check_aspect_ratio(100, 50, 100, 100)
        assert warning is not None
        assert "⚠️" in warning

    def test_aspect_ratio_no_warning_when_close(self):
        """验证宽高比偏差小于 20% 时不返回警告"""
        # 高度图 100x100 (ratio=1.0), 目标 110x100 (ratio=1.1)
        # 偏差 = |1.0 - 1.1| / 1.1 ≈ 0.09 = 9% < 20%
        warning = HeightmapLoader._check_aspect_ratio(100, 100, 110, 100)
        assert warning is None

    def test_low_contrast_warning(self):
        """验证低对比度（标准差 < 1.0）时返回警告 (需求 8.3)"""
        # 全黑图，标准差 = 0
        grayscale = np.zeros((10, 10), dtype=np.uint8)
        warning = HeightmapLoader._check_contrast(grayscale)
        assert warning is not None
        assert "⚠️" in warning

    def test_no_contrast_warning_for_normal_image(self):
        """验证正常对比度图像不返回警告"""
        # 创建有足够对比度的图像
        grayscale = np.zeros((10, 10), dtype=np.uint8)
        grayscale[:5, :] = 0
        grayscale[5:, :] = 255
        warning = HeightmapLoader._check_contrast(grayscale)
        assert warning is None
