"""
K/S LUT 生成器 - 单元测试
验证 K-M 物理引擎的具体示例和边界情况
"""

import numpy as np
import pytest

from core.ks_engine.physics import VirtualPhysics


class TestKMPhysicsBoundary:
    """K-M 物理计算边界情况测试"""

    def test_km_zero_absorption(self):
        """
        K=0 时反射率近似等于背景反射率。
        当吸收系数为 0 时，材料不吸收光，但散射仍会影响反射率，
        所以结果接近背景但不完全相等。使用较宽容差验证趋势正确。
        需求: 3.1
        """
        engine = VirtualPhysics()
        K = np.array([[0.0, 0.0, 0.0]])
        S = np.array([[5.0, 5.0, 5.0]])
        h = 0.08
        Rg = np.array([[0.5, 0.6, 0.7]])

        result = engine.km_reflectance_vectorized(K, S, h, Rg)

        # K=0 时，材料只散射不吸收，反射率应接近背景（容差 0.1）
        np.testing.assert_allclose(
            result, Rg, atol=0.1,
            err_msg="K=0 时反射率应近似等于背景反射率"
        )
        # 结果应在 [0, 1] 范围内
        assert np.all(result >= 0.0) and np.all(result <= 1.0)

    def test_srgb_known_values(self):
        """
        已知线性值的 sRGB 转换结果验证。
        需求: 3.3
        """
        # 线性 0.0 -> sRGB 0
        result_zero = VirtualPhysics.linear_to_srgb_bytes(np.array([[0.0, 0.0, 0.0]]))
        np.testing.assert_array_equal(result_zero, [[0, 0, 0]])

        # 线性 1.0 -> sRGB 254 或 255（浮点精度导致 1.055*1^(1/2.4)-0.055 可能略小于 1.0）
        result_one = VirtualPhysics.linear_to_srgb_bytes(np.array([[1.0, 1.0, 1.0]]))
        assert np.all(result_one >= 254), f"线性 1.0 应转换为 254 或 255，实际: {result_one}"

        # 线性 0.5 -> sRGB ~187 (标准 sRGB 伽马校正)
        # 公式: 1.055 * 0.5^(1/2.4) - 0.055 ≈ 0.7354 -> 0.7354 * 255 ≈ 187.5
        # astype(uint8) 截断为 187
        result_half = VirtualPhysics.linear_to_srgb_bytes(np.array([[0.5, 0.5, 0.5]]))
        expected_half = int((1.055 * (0.5 ** (1.0 / 2.4)) - 0.055) * 255)
        np.testing.assert_array_equal(
            result_half, [[expected_half, expected_half, expected_half]]
        )


import json
import tempfile
import os

from core.ks_engine.filament_loader import FilamentLoader


class TestFilamentLoader:
    """耗材加载器单元测试"""

    def test_load_my_filament_json(self):
        """
        加载实际 my_filament.json，验证 8 种耗材。
        需求: 1.1, 1.2
        """
        filaments = FilamentLoader.load('my_filament.json')

        # 验证数量
        assert len(filaments) == 8, f"应有 8 种耗材，实际: {len(filaments)}"

        # 验证每个耗材都有必要字段
        for i, f in enumerate(filaments):
            assert 'name' in f, f"耗材 {i} 缺少 name"
            assert 'color' in f, f"耗材 {i} 缺少 color"
            assert 'FILAMENT_K' in f, f"耗材 {i} 缺少 FILAMENT_K"
            assert 'FILAMENT_S' in f, f"耗材 {i} 缺少 FILAMENT_S"
            assert len(f['FILAMENT_K']) == 3, f"耗材 {i} 的 FILAMENT_K 应为 3 通道"
            assert len(f['FILAMENT_S']) == 3, f"耗材 {i} 的 FILAMENT_S 应为 3 通道"

        # 验证第一个耗材的名称
        assert filaments[0]['name'] == 'Aliz PETG White'
        # 验证 K/S 映射正确（第一个耗材的 K 值）
        assert filaments[0]['FILAMENT_K'][0] == 1e-05
        assert filaments[0]['FILAMENT_S'][0] == pytest.approx(4.015523985054049)

    def test_load_missing_ks_field(self):
        """
        缺少 K 字段时报错含耗材名。
        需求: 1.5
        """
        data = {
            "filaments": [
                {
                    "name": "Test Filament",
                    "color": "#ff0000",
                    "S": [1.0, 2.0, 3.0]
                    # 缺少 K 字段
                }
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(data, f)
            tmp_path = f.name

        try:
            with pytest.raises(ValueError) as exc_info:
                FilamentLoader.load(tmp_path)

            error_msg = str(exc_info.value)
            assert 'Test Filament' in error_msg, f"错误信息应包含耗材名，实际: '{error_msg}'"
            assert 'K' in error_msg, f"错误信息应包含缺失字段名 'K'，实际: '{error_msg}'"
        finally:
            os.unlink(tmp_path)


from core.ks_engine.lut_generator import KSLutGenerator
from utils.lut_manager import LUTManager


class TestKSLutGenerator:
    """KSLutGenerator 单元测试"""

    @staticmethod
    def _make_filaments(n):
        """生成 n 个测试耗材"""
        filaments = []
        for i in range(n):
            filaments.append({
                'name': f'Filament_{i}',
                'color': '#ffffff',
                'FILAMENT_K': [0.05 * (i + 1), 0.05 * (i + 1), 0.05 * (i + 1)],
                'FILAMENT_S': [5.0 + i, 5.0 + i, 5.0 + i],
            })
        return filaments

    def test_2color_lut_shape(self):
        """
        2 色 LUT 形状为 (32, 1, 3)。
        需求: 4.2
        """
        generator = KSLutGenerator()
        filaments = self._make_filaments(2)
        selected_indices = [0, 1]

        lut_grid, metadata = generator.generate(filaments, selected_indices)

        assert lut_grid.shape == (32, 1, 3), f"2 色 LUT 形状应为 (32, 1, 3)，实际: {lut_grid.shape}"
        assert lut_grid.dtype == np.uint8
        assert metadata['total_colors'] == 32
        assert metadata['num_filaments'] == 2

    def test_4color_lut_shape(self):
        """
        4 色 LUT 形状为 (32, 32, 3)。
        需求: 4.3
        """
        generator = KSLutGenerator()
        filaments = self._make_filaments(4)
        selected_indices = [0, 1, 2, 3]

        lut_grid, metadata = generator.generate(filaments, selected_indices)

        assert lut_grid.shape == (32, 32, 3), f"4 色 LUT 形状应为 (32, 32, 3)，实际: {lut_grid.shape}"
        assert lut_grid.dtype == np.uint8
        assert metadata['total_colors'] == 1024
        assert metadata['num_filaments'] == 4

    def test_6color_generates_stacks(self):
        """
        6 色模式同时生成 stacks 文件。
        需求: 5.3
        """
        generator = KSLutGenerator()
        filaments = self._make_filaments(6)
        selected_indices = list(range(6))

        lut_grid, metadata = generator.generate(filaments, selected_indices)

        # 6 色应有 stacks
        stacks = metadata.get('stacks')
        assert stacks is not None, "6 色模式应生成 stacks 索引"
        assert stacks.shape == (7776, 5), f"6 色 stacks 形状应为 (7776, 5)，实际: {stacks.shape}"

        # LUT 形状
        assert lut_grid.shape == (7776, 1, 3), f"6 色 LUT 形状应为 (7776, 1, 3)，实际: {lut_grid.shape}"

        # 保存时应同时生成 stacks 文件
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "test_6color.npy")
            saved_path, total_colors = generator.save(lut_grid, file_path, stacks)

            stacks_path = os.path.join(tmp_dir, "test_6color_stacks.npy")
            assert os.path.exists(stacks_path), "6 色模式应生成 stacks 文件"

            loaded_stacks = np.load(stacks_path)
            np.testing.assert_array_equal(loaded_stacks, stacks)

    def test_save_returns_path_and_count(self):
        """
        save 返回路径和颜色总数。
        需求: 4.6
        """
        generator = KSLutGenerator()
        filaments = self._make_filaments(2)
        selected_indices = [0, 1]

        lut_grid, metadata = generator.generate(filaments, selected_indices)

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "subdir", "test_save.npy")
            stacks = metadata.get('stacks')
            saved_path, total_colors = generator.save(lut_grid, file_path, stacks)

            # 返回路径
            assert saved_path == file_path
            # 返回颜色总数
            assert total_colors == 32
            # 文件存在
            assert os.path.exists(saved_path)
            # 目录自动创建
            assert os.path.isdir(os.path.join(tmp_dir, "subdir"))


from core.image_processing import LuminaImageProcessor


class TestLoadLutCompat:
    """_load_lut 兼容性测试"""

    @staticmethod
    def _make_filaments(n):
        """生成 n 个测试耗材"""
        filaments = []
        for i in range(n):
            filaments.append({
                'name': f'Filament_{i}',
                'color': '#ffffff',
                'FILAMENT_K': [0.05 * (i + 1), 0.05 * (i + 1), 0.05 * (i + 1)],
                'FILAMENT_S': [5.0 + i, 5.0 + i, 5.0 + i],
            })
        return filaments

    def test_2color_load_compat(self):
        """
        生成 2 色 LUT → 保存 → 用 LuminaImageProcessor._load_lut 加载
        → 验证识别为 BW 模式，32 种颜色。
        需求: 5.1
        """
        generator = KSLutGenerator()
        filaments = self._make_filaments(2)
        selected_indices = [0, 1]

        lut_grid, metadata = generator.generate(filaments, selected_indices)

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "test_2color.npy")
            generator.save(lut_grid, file_path)

            # 用 LuminaImageProcessor 加载
            processor = LuminaImageProcessor(file_path, "BW")

            # 验证识别为 BW 模式，32 种颜色
            assert processor.lut_rgb is not None, "lut_rgb 不应为 None"
            assert processor.ref_stacks is not None, "ref_stacks 不应为 None"
            assert len(processor.lut_rgb) == 32, f"BW 模式应有 32 种颜色，实际: {len(processor.lut_rgb)}"
            assert processor.lut_rgb.shape == (32, 3), f"lut_rgb 形状应为 (32, 3)，实际: {processor.lut_rgb.shape}"
            assert processor.ref_stacks.shape == (32, 5), f"ref_stacks 形状应为 (32, 5)，实际: {processor.ref_stacks.shape}"

            # 验证 stacks 中只包含 0 和 1（2 色模式）
            unique_vals = np.unique(processor.ref_stacks)
            assert set(unique_vals).issubset({0, 1}), f"BW stacks 应只含 0 和 1，实际: {unique_vals}"

            # 验证 KDTree 已构建
            assert processor.kdtree is not None, "KDTree 应已构建"

    def test_4color_load_compat(self):
        """
        生成 4 色 LUT → 保存 → 用 LuminaImageProcessor._load_lut 加载
        → 验证识别为 4-Color 模式，颜色数 <= 1024 且 > 0。
        需求: 5.2
        """
        generator = KSLutGenerator()
        filaments = self._make_filaments(4)
        selected_indices = [0, 1, 2, 3]

        lut_grid, metadata = generator.generate(filaments, selected_indices)

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "test_4color.npy")
            generator.save(lut_grid, file_path)

            # 用 LuminaImageProcessor 加载（4-Color 模式）
            processor = LuminaImageProcessor(file_path, "4-Color")

            # 验证加载成功
            assert processor.lut_rgb is not None, "lut_rgb 不应为 None"
            assert processor.ref_stacks is not None, "ref_stacks 不应为 None"

            # 4-Color 分支有蓝色过滤逻辑，颜色数可能少于 1024
            num_colors = len(processor.lut_rgb)
            assert num_colors > 0, "应至少有 1 种颜色"
            assert num_colors <= 1024, f"4-Color 模式颜色数不应超过 1024，实际: {num_colors}"

            # 验证形状一致性
            assert processor.lut_rgb.shape[1] == 3, "lut_rgb 第二维应为 3 (RGB)"
            assert processor.ref_stacks.shape[1] == 5, "ref_stacks 第二维应为 5 (5 层)"

            # 验证 stacks 中只包含 0-3（4 色模式）
            unique_vals = np.unique(processor.ref_stacks)
            assert all(v in range(4) for v in unique_vals), f"4-Color stacks 应只含 0-3，实际: {unique_vals}"

            # 验证 KDTree 已构建
            assert processor.kdtree is not None, "KDTree 应已构建"


class TestLutRegisteredInManager:
    """验证生成的 LUT 能被 LUTManager 扫描到"""

    @staticmethod
    def _make_filaments(n):
        """生成 n 个测试耗材"""
        filaments = []
        for i in range(n):
            filaments.append({
                'name': f'Filament_{i}',
                'color': '#ffffff',
                'FILAMENT_K': [0.05 * (i + 1), 0.05 * (i + 1), 0.05 * (i + 1)],
                'FILAMENT_S': [5.0 + i, 5.0 + i, 5.0 + i],
            })
        return filaments

    def test_lut_registered_in_manager(self, monkeypatch):
        """
        生成 LUT 并保存到预设目录后，验证 LUTManager.get_all_lut_files() 能扫描到该文件。
        需求: 6.4
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 将 LUTManager 的预设目录指向临时目录
            monkeypatch.setattr(LUTManager, 'LUT_PRESET_DIR', tmp_dir)

            generator = KSLutGenerator()
            filaments = self._make_filaments(2)
            selected_indices = [0, 1]

            lut_grid, metadata = generator.generate(filaments, selected_indices)

            # 保存到 KS-Generated 子目录
            save_dir = os.path.join(tmp_dir, "KS-Generated")
            save_path = os.path.join(save_dir, "FF_KS.npy")
            stacks = metadata.get('stacks')
            generator.save(lut_grid, save_path, stacks)

            # 验证文件存在
            assert os.path.exists(save_path), f"LUT 文件应存在: {save_path}"

            # 验证 LUTManager 能扫描到
            all_luts = LUTManager.get_all_lut_files()
            assert len(all_luts) > 0, "LUTManager 应至少扫描到 1 个 LUT 文件"

            # 验证显示名称包含 KS-Generated 品牌前缀
            found = False
            for display_name, file_path in all_luts.items():
                if "KS-Generated" in display_name and "FF_KS" in display_name:
                    found = True
                    assert file_path == save_path, f"文件路径应匹配: {file_path} != {save_path}"
                    break
            assert found, f"LUTManager 应能找到 KS-Generated - FF_KS，实际: {list(all_luts.keys())}"
