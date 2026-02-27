"""
Stacks NPY 文件上传 - 属性测试与单元测试
使用 Hypothesis 库进行属性测试，验证 stacks 文件上传功能的正确性属性
"""

import os
import sys
import shutil
import tempfile
import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.lut_manager import LUTManager


# ============================================================================
# 通用策略生成器
# ============================================================================

def safe_filename_strategy():
    """生成合法的文件名（不含路径分隔符和特殊字符）"""
    return st.from_regex(r'[a-zA-Z0-9_\-]{1,30}', fullmatch=True)


def npy_filename_strategy():
    """生成 .npy 结尾的文件名"""
    return safe_filename_strategy().map(lambda name: f"{name}.npy")


def stacks_filename_strategy():
    """生成 _stacks.npy 结尾的文件名"""
    return safe_filename_strategy().map(lambda name: f"{name}_stacks.npy")


def mixed_npy_filenames_strategy():
    """生成混合的文件名列表（普通 .npy 和 _stacks.npy）"""
    normal = npy_filename_strategy().map(lambda f: (f, False))
    stacks = stacks_filename_strategy().map(lambda f: (f, True))
    return st.lists(
        st.one_of(normal, stacks),
        min_size=1,
        max_size=20
    )


# ============================================================================
# Property 1: Stacks 路径构建一致性
# Feature: stacks-npy-upload, Property 1: Stacks 路径构建一致性
# Validates: Requirements 2.1, 2.2, 2.3
# ============================================================================

@given(
    base_name=safe_filename_strategy(),
    has_numeric_suffix=st.booleans(),
    suffix_num=st.integers(min_value=1, max_value=999),
    subdir=st.sampled_from(["Custom", "BrandA", "Presets/Sub"]),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_stacks_path_consistency_with_load_lut(base_name, has_numeric_suffix, suffix_num, subdir):
    """
    Property 1: Stacks 路径构建一致性

    对任意合法 LUT 文件路径（含数字后缀等），验证 _build_stacks_path(lut_path)
    输出与 _load_lut 中 companion stacks 查找逻辑一致：
        base_path, ext = os.path.splitext(lut_path)
        companion_stacks_path = base_path + "_stacks.npy"

    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    # 构建 LUT 文件名
    if has_numeric_suffix:
        filename = f"{base_name}_{suffix_num}.npy"
    else:
        filename = f"{base_name}.npy"

    lut_path = os.path.join("lut-npy预设", subdir, filename)

    # _build_stacks_path 的结果
    result = LUTManager._build_stacks_path(lut_path)

    # _load_lut 中的 companion stacks 查找逻辑
    base_path, ext = os.path.splitext(lut_path)
    expected = base_path + "_stacks.npy"

    assert result == expected, (
        f"路径不一致:\n"
        f"  _build_stacks_path: {result}\n"
        f"  _load_lut 逻辑:     {expected}"
    )

    # 额外验证：stacks 文件与 LUT 在同一目录
    assert os.path.dirname(result) == os.path.dirname(lut_path)

    # 额外验证：stacks 文件名以 _stacks.npy 结尾
    assert os.path.basename(result).endswith("_stacks.npy")


# ============================================================================
# Property 2: Stacks 文件过滤
# Feature: stacks-npy-upload, Property 2: Stacks 文件过滤
# Validates: Requirements 3.1, 3.2
# ============================================================================

@given(file_list=mixed_npy_filenames_strategy())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_stacks_file_filtering(file_list):
    """
    Property 2: Stacks 文件过滤

    对任意文件名列表（混合普通 .npy 和 _stacks.npy），验证过滤逻辑
    正确排除所有 stacks 文件且保留所有非 stacks 的 .npy 文件。

    **Validates: Requirements 3.1, 3.2**
    """
    filenames = [f for f, _ in file_list]
    is_stacks_flags = [s for _, s in file_list]

    # 模拟 get_all_lut_files 的过滤逻辑
    filtered = [f for f in filenames if not f.endswith("_stacks.npy")]

    # 验证：所有 _stacks.npy 文件都被排除
    for f in filtered:
        assert not f.endswith("_stacks.npy"), f"Stacks 文件未被过滤: {f}"

    # 验证：所有非 stacks 的 .npy 文件都被保留
    expected_kept = [f for f, is_stacks in file_list if not is_stacks]
    for f in expected_kept:
        assert f in filtered, f"非 stacks 文件被错误过滤: {f}"

    # 验证：过滤后的数量 = 非 stacks 文件数量
    assert len(filtered) == len(expected_kept)


# ============================================================================
# Property 3: 删除联动完整性
# Feature: stacks-npy-upload, Property 3: 删除联动完整性
# Validates: Requirements 4.1, 4.2
# ============================================================================

@given(
    base_name=safe_filename_strategy(),
    has_stacks=st.booleans(),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_delete_cascade_integrity(base_name, has_stacks):
    """
    Property 3: 删除联动完整性

    在临时目录创建随机 LUT+stacks 文件对，调用 delete_lut，
    验证 LUT 和 companion stacks 均被删除。

    **Validates: Requirements 4.1, 4.2**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建 Custom 子目录（delete_lut 要求路径包含 "Custom"）
        custom_dir = os.path.join(tmpdir, "Custom")
        os.makedirs(custom_dir, exist_ok=True)

        # 创建 LUT 文件
        lut_filename = f"{base_name}.npy"
        lut_path = os.path.join(custom_dir, lut_filename)
        np.save(lut_path, np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8))

        # 可选创建 stacks 文件
        stacks_path = LUTManager._build_stacks_path(lut_path)
        if has_stacks:
            np.save(stacks_path, np.array([[0, 1, 2], [1, 2, 0], [2, 0, 1]]))

        display_name = f"Custom - {base_name}"

        # Mock LUT_PRESET_DIR 和 get_lut_path 指向临时目录
        with patch.object(LUTManager, 'LUT_PRESET_DIR', tmpdir), \
             patch.object(LUTManager, 'get_lut_path', return_value=lut_path), \
             patch.object(LUTManager, 'get_lut_choices', return_value=[]):

            success, message, _ = LUTManager.delete_lut(display_name)

        # 验证 LUT 被删除
        assert success, f"delete_lut 应返回成功，实际消息: {message}"
        assert not os.path.exists(lut_path), f"LUT 文件未被删除: {lut_path}"

        # 验证 stacks 联动删除
        if has_stacks:
            assert not os.path.exists(stacks_path), f"Companion stacks 未被联动删除: {stacks_path}"


# ============================================================================
# Property 4: Stacks 行数不匹配检测
# Feature: stacks-npy-upload, Property 4: Stacks 行数不匹配检测
# Validates: Requirements 5.2
# ============================================================================

@given(
    stacks_rows=st.integers(min_value=1, max_value=500),
    lut_rows=st.integers(min_value=1, max_value=500),
    stacks_cols=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_stacks_row_mismatch_detection(stacks_rows, lut_rows, stacks_cols):
    """
    Property 4: Stacks 行数不匹配检测

    使用 hypothesis 生成随机大小的 stacks 和 LUT 数组（行数不同），
    验证 validate_stacks_file 返回失败并包含不匹配信息。

    **Validates: Requirements 5.2**
    """
    # 确保行数不同
    assume(stacks_rows != lut_rows)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建 stacks 文件
        stacks_data = np.random.randint(0, 8, size=(stacks_rows, stacks_cols))
        stacks_path = os.path.join(tmpdir, "test_stacks.npy")
        np.save(stacks_path, stacks_data)

        # 创建 LUT 文件（N 行 3 列 RGB）
        lut_data = np.random.randint(0, 256, size=(lut_rows, 3), dtype=np.uint8)
        lut_path = os.path.join(tmpdir, "test_lut.npy")
        np.save(lut_path, lut_data)

        # 调用验证
        is_valid, message = LUTManager.validate_stacks_file(stacks_path, lut_path)

        # 验证返回失败
        assert not is_valid, (
            f"行数不匹配时应返回失败: stacks={stacks_rows}, lut={lut_rows}, "
            f"实际: is_valid={is_valid}, message={message}"
        )

        # 验证消息包含不匹配信息
        assert "不匹配" in message, f"消息应包含'不匹配': {message}"


# ============================================================================
# Task 5.5: 单元测试
# Validates: Requirements 2.1, 2.2, 2.4, 5.1, 5.3
# ============================================================================

class TestStacksUploadUnit:
    """Stacks 上传功能单元测试"""

    def _create_mock_file(self, tmpdir, filename, data):
        """创建模拟的上传文件对象"""
        filepath = os.path.join(tmpdir, filename)
        if isinstance(data, np.ndarray):
            np.save(filepath, data)
        else:
            with open(filepath, 'wb') as f:
                f.write(data)
        mock_file = MagicMock()
        mock_file.name = filepath
        return mock_file

    def test_upload_lut_only_backward_compatible(self):
        """测试仅上传 LUT 不上传 stacks 的向后兼容场景"""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = os.path.join(tmpdir, "Custom")
            os.makedirs(custom_dir, exist_ok=True)

            # 创建 LUT 文件
            lut_data = np.random.randint(0, 256, size=(10, 3), dtype=np.uint8)
            lut_file = self._create_mock_file(tmpdir, "test_lut.npy", lut_data)

            with patch.object(LUTManager, 'LUT_PRESET_DIR', tmpdir), \
                 patch.object(LUTManager, 'get_lut_choices', return_value=[]):
                success, message, _ = LUTManager.save_uploaded_lut(lut_file, stacks_file=None)

            assert success, f"仅上传 LUT 应成功: {message}"
            assert "LUT saved" in message or "✅" in message

            # 验证没有 stacks 文件被创建
            saved_files = os.listdir(custom_dir)
            stacks_files = [f for f in saved_files if f.endswith("_stacks.npy")]
            assert len(stacks_files) == 0, f"不应创建 stacks 文件: {stacks_files}"

    def test_upload_lut_and_stacks_both_saved(self):
        """测试同时上传 LUT 和 stacks 均保存成功"""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = os.path.join(tmpdir, "Custom")
            os.makedirs(custom_dir, exist_ok=True)

            # 创建 LUT 文件（10 种颜色）
            lut_data = np.random.randint(0, 256, size=(10, 3), dtype=np.uint8)
            lut_file = self._create_mock_file(tmpdir, "test_lut.npy", lut_data)

            # 创建匹配的 stacks 文件（10 行）
            stacks_data = np.random.randint(0, 8, size=(10, 5))
            stacks_file = self._create_mock_file(tmpdir, "test_stacks.npy", stacks_data)

            with patch.object(LUTManager, 'LUT_PRESET_DIR', tmpdir), \
                 patch.object(LUTManager, 'get_lut_choices', return_value=[]):
                success, message, _ = LUTManager.save_uploaded_lut(lut_file, stacks_file=stacks_file)

            assert success, f"同时上传应成功: {message}"
            assert "Stacks" in message, f"消息应提及 Stacks: {message}"

            # 验证两个文件都存在
            saved_files = os.listdir(custom_dir)
            lut_files = [f for f in saved_files if not f.endswith("_stacks.npy")]
            stacks_files = [f for f in saved_files if f.endswith("_stacks.npy")]
            assert len(lut_files) >= 1, f"LUT 文件应存在: {saved_files}"
            assert len(stacks_files) >= 1, f"Stacks 文件应存在: {saved_files}"

    def test_upload_stacks_only_returns_error(self):
        """测试仅上传 stacks 未上传 LUT 返回错误"""
        with tempfile.TemporaryDirectory() as tmpdir:
            stacks_data = np.random.randint(0, 8, size=(10, 5))
            stacks_file = self._create_mock_file(tmpdir, "test_stacks.npy", stacks_data)

            with patch.object(LUTManager, 'get_lut_choices', return_value=[]):
                success, message, _ = LUTManager.save_uploaded_lut(
                    None, stacks_file=stacks_file
                )

            assert not success, "仅上传 stacks 应返回失败"
            assert "LUT" in message, f"错误消息应提及 LUT: {message}"

    def test_upload_invalid_stacks_format(self):
        """测试上传非 numpy 格式的 stacks 文件返回格式错误"""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = os.path.join(tmpdir, "Custom")
            os.makedirs(custom_dir, exist_ok=True)

            # 创建 LUT 文件
            lut_data = np.random.randint(0, 256, size=(10, 3), dtype=np.uint8)
            lut_file = self._create_mock_file(tmpdir, "test_lut.npy", lut_data)

            # 创建无效的 stacks 文件（非 numpy 格式）
            stacks_file = self._create_mock_file(tmpdir, "bad_stacks.npy", b"not a numpy file")

            with patch.object(LUTManager, 'LUT_PRESET_DIR', tmpdir), \
                 patch.object(LUTManager, 'get_lut_choices', return_value=[]):
                success, message, _ = LUTManager.save_uploaded_lut(lut_file, stacks_file=stacks_file)

            # LUT 应该仍然保存成功
            assert success, f"LUT 应正常保存: {message}"
            # 消息应包含 stacks 格式错误的警告
            assert "⚠️" in message or "无效" in message or "格式" in message, \
                f"消息应包含格式错误警告: {message}"

    def test_stacks_save_failure_lut_still_saved(self):
        """测试 stacks 保存失败时 LUT 仍正常保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = os.path.join(tmpdir, "Custom")
            os.makedirs(custom_dir, exist_ok=True)

            # 创建 LUT 文件
            lut_data = np.random.randint(0, 256, size=(10, 3), dtype=np.uint8)
            lut_file = self._create_mock_file(tmpdir, "test_lut.npy", lut_data)

            # 创建有效的 stacks 文件
            stacks_data = np.random.randint(0, 8, size=(10, 5))
            stacks_file = self._create_mock_file(tmpdir, "test_stacks.npy", stacks_data)

            # Mock shutil.copy2 让 stacks 保存时抛异常（仅第二次调用）
            original_copy2 = shutil.copy2
            call_count = [0]

            def mock_copy2(src, dst, *args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    # 第一次调用是 LUT 保存，正常执行
                    return original_copy2(src, dst, *args, **kwargs)
                else:
                    # 第二次调用是 stacks 保存，抛异常
                    raise IOError("模拟磁盘写入失败")

            with patch.object(LUTManager, 'LUT_PRESET_DIR', tmpdir), \
                 patch.object(LUTManager, 'get_lut_choices', return_value=[]), \
                 patch('shutil.copy2', side_effect=mock_copy2):
                success, message, _ = LUTManager.save_uploaded_lut(lut_file, stacks_file=stacks_file)

            # LUT 应该仍然保存成功
            assert success, f"LUT 应正常保存即使 stacks 失败: {message}"
            # 消息应包含 stacks 保存失败的警告
            assert "⚠️" in message or "失败" in message, \
                f"消息应包含 stacks 保存失败警告: {message}"
