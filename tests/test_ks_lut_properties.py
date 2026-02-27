"""
K/S LUT 生成器 - 属性测试
使用 Hypothesis 库进行属性测试，验证 K-M 物理引擎的正确性属性
"""

import numpy as np
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from core.ks_engine.physics import VirtualPhysics


# ============================================================================
# 通用策略生成器
# ============================================================================

def ks_value_strategy():
    """生成合法的 K/S 参数值（RGB 三通道）"""
    return st.lists(
        st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        min_size=3, max_size=3
    )


def filament_strategy():
    """生成一个合法的耗材参数"""
    return st.fixed_dictionaries({
        'FILAMENT_K': ks_value_strategy(),
        'FILAMENT_S': ks_value_strategy(),
    })


# ============================================================================
# Property 5: 叠层计算顺序正确性
# Feature: ks-lut-generator, Property 5: 叠层计算顺序正确性
# Validates: Requirements 3.2
# ============================================================================

@given(
    filament_a=filament_strategy(),
    filament_b=filament_strategy(),
)
@settings(max_examples=100)
def test_layer_order_correctness(filament_a, filament_b):
    """
    Property 5: 叠层计算顺序正确性

    对 2 种不同耗材和 2 层叠层配置，验证 generate_lut_km 对组合 [A, B]
    （A 在顶层，B 在底层）的计算结果等于手动逐层计算结果：
    先以 backing 为背景计算 B 层反射率，再以 B 层反射率为背景计算 A 层反射率，
    最后转换为 sRGB。

    **Validates: Requirements 3.2**
    """
    engine = VirtualPhysics()
    backing = np.array([0.94, 0.94, 0.94])
    layer_height = 0.08
    total_layers = 2

    filaments = [filament_a, filament_b]

    # 使用 generate_lut_km 计算
    lut_colors, indices = engine.generate_lut_km(
        filaments, layer_height=layer_height,
        total_layers=total_layers, backing_reflectance=backing
    )

    # 找到组合 [A=0, B=1] 的索引（A 在顶层 indices[:,0]，B 在底层 indices[:,1]）
    # itertools.product(range(2), repeat=2) 生成: (0,0), (0,1), (1,0), (1,1)
    # 组合 [0, 1] 即 A 在顶层、B 在底层，对应 indices 中 (0, 1)，索引为 1
    target_idx = None
    for i, idx in enumerate(indices):
        if idx[0] == 0 and idx[1] == 1:
            target_idx = i
            break
    assert target_idx is not None

    lut_result = lut_colors[target_idx]

    # 手动逐层计算：先底层 B，再顶层 A
    K_b = np.array(filament_b['FILAMENT_K'])
    S_b = np.array(filament_b['FILAMENT_S'])
    K_a = np.array(filament_a['FILAMENT_K'])
    S_a = np.array(filament_a['FILAMENT_S'])

    # 第一步：底层 B，背景为 backing
    R_after_b = engine.km_reflectance_vectorized(
        K_b.reshape(1, 3), S_b.reshape(1, 3), layer_height, backing.reshape(1, 3)
    )
    # 第二步：顶层 A，背景为 B 层的反射率
    R_after_a = engine.km_reflectance_vectorized(
        K_a.reshape(1, 3), S_a.reshape(1, 3), layer_height, R_after_b
    )
    # 转换为 sRGB
    manual_result = engine.linear_to_srgb_bytes(R_after_a)[0]

    np.testing.assert_array_equal(
        lut_result, manual_result,
        err_msg="generate_lut_km 的叠层计算顺序与手动逐层计算结果不一致"
    )


# ============================================================================
# Property 4: K-M 反射率输出范围不变量
# Feature: ks-lut-generator, Property 4: K-M 反射率输出范围不变量
# Validates: Requirements 3.1, 3.4, 3.5
# ============================================================================

@given(
    K=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    S=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    h=st.floats(min_value=0.001, max_value=1.0, allow_nan=False, allow_infinity=False),
    Rg=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_km_reflectance_output_range(K, S, h, Rg):
    """
    Property 4: K-M 反射率输出范围不变量

    对任意合法 K(≥0)、S(≥0)、h(>0)、Rg(∈[0,1])，验证输出满足：
    (a) 所有值在 [0, 1] 范围内
    (b) 不包含 NaN 或 Inf
    (c) 即使 S=0 也不会抛出异常

    **Validates: Requirements 3.1, 3.4, 3.5**
    """
    engine = VirtualPhysics()

    # 构造 RGB 三通道输入（每通道使用相同值简化测试）
    K_arr = np.array([[K, K, K]])
    S_arr = np.array([[S, S, S]])
    Rg_arr = np.array([[Rg, Rg, Rg]])

    # 不应抛出异常（包括 S=0 的情况）
    result = engine.km_reflectance_vectorized(K_arr, S_arr, h, Rg_arr)

    # (a) 所有值在 [0, 1] 范围内
    assert np.all(result >= 0.0), f"反射率包含负值: {result}"
    assert np.all(result <= 1.0), f"反射率超过 1.0: {result}"

    # (b) 不包含 NaN 或 Inf
    assert not np.any(np.isnan(result)), f"反射率包含 NaN: {result}"
    assert not np.any(np.isinf(result)), f"反射率包含 Inf: {result}"


# ============================================================================
# Property 6: sRGB 转换单调性
# Feature: ks-lut-generator, Property 6: sRGB 转换单调性
# Validates: Requirements 3.3
# ============================================================================

@given(
    r_lo=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    g_lo=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    b_lo=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    r_delta=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    g_delta=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    b_delta=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_srgb_conversion_monotonicity(r_lo, g_lo, b_lo, r_delta, g_delta, b_delta):
    """
    Property 6: sRGB 转换单调性

    对任意两个线性 RGB 值 a ≤ b（逐通道），验证
    linear_to_srgb_bytes(a) ≤ linear_to_srgb_bytes(b)（逐通道）。

    **Validates: Requirements 3.3**
    """
    # 构造 a ≤ b（逐通道），通过 a + delta 确保 b >= a
    a = np.array([[r_lo, g_lo, b_lo]])
    b = np.array([[
        min(r_lo + r_delta, 1.0),
        min(g_lo + g_delta, 1.0),
        min(b_lo + b_delta, 1.0),
    ]])

    srgb_a = VirtualPhysics.linear_to_srgb_bytes(a)
    srgb_b = VirtualPhysics.linear_to_srgb_bytes(b)

    assert np.all(srgb_a <= srgb_b), (
        f"sRGB 转换不满足单调性: a={a}, b={b}, "
        f"srgb(a)={srgb_a}, srgb(b)={srgb_b}"
    )


# ============================================================================
# FilamentLoader 属性测试
# ============================================================================

import json
import tempfile
import os

from core.ks_engine.filament_loader import FilamentLoader


def json_filament_strategy():
    """生成一个合法的 JSON 格式耗材（使用 K/S 字段名）"""
    return st.fixed_dictionaries({
        'name': st.text(min_size=1, max_size=20, alphabet=st.characters(
            whitelist_categories=('L', 'N'), whitelist_characters=' -_'
        )),
        'color': st.from_regex(r'#[0-9a-f]{6}', fullmatch=True),
        'K': st.lists(
            st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
            min_size=3, max_size=3
        ),
        'S': st.lists(
            st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
            min_size=3, max_size=3
        ),
    })


# ============================================================================
# Property 1: 耗材加载字段映射往返
# Feature: ks-lut-generator, Property 1: 耗材加载字段映射往返
# Validates: Requirements 1.1, 1.2, 1.3
# ============================================================================

@given(filaments=st.lists(json_filament_strategy(), min_size=1, max_size=8))
@settings(max_examples=100)
def test_filament_load_roundtrip(filaments):
    """
    Property 1: 耗材加载字段映射往返

    对任意合法耗材 JSON（包含 name、color、K、S），加载后验证
    FILAMENT_K/FILAMENT_S 与原始 K/S 值完全相等。

    **Validates: Requirements 1.1, 1.2, 1.3**
    """
    # 构造临时 JSON 文件
    data = {"filaments": filaments}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(data, f)
        tmp_path = f.name

    try:
        loaded = FilamentLoader.load(tmp_path)

        # 验证数量一致
        assert len(loaded) == len(filaments)

        # 验证每个耗材的字段映射
        for original, result in zip(filaments, loaded):
            assert result['name'] == original['name']
            assert result['color'] == original['color']
            assert result['FILAMENT_K'] == original['K'], (
                f"FILAMENT_K {result['FILAMENT_K']} != 原始 K {original['K']}"
            )
            assert result['FILAMENT_S'] == original['S'], (
                f"FILAMENT_S {result['FILAMENT_S']} != 原始 S {original['S']}"
            )
    finally:
        os.unlink(tmp_path)


# ============================================================================
# Property 2: 无效输入产生描述性错误
# Feature: ks-lut-generator, Property 2: 无效输入产生描述性错误
# Validates: Requirements 1.4
# ============================================================================

@given(
    path_suffix=st.text(min_size=1, max_size=30, alphabet=st.characters(
        whitelist_categories=('L', 'N'), whitelist_characters='_-'
    ))
)
@settings(max_examples=100)
def test_invalid_input_descriptive_error(path_suffix):
    """
    Property 2: 无效输入产生描述性错误

    对不存在的文件路径，验证抛出包含文件路径信息的异常，
    且异常消息长度大于 0。

    **Validates: Requirements 1.4**
    """
    fake_path = f"/tmp/nonexistent_{path_suffix}.json"
    # 确保文件确实不存在
    assume(not os.path.exists(fake_path))

    with pytest.raises(FileNotFoundError) as exc_info:
        FilamentLoader.load(fake_path)

    error_msg = str(exc_info.value)
    assert len(error_msg) > 0, "错误信息不应为空"
    assert fake_path in error_msg, f"错误信息应包含文件路径 '{fake_path}'，实际: '{error_msg}'"


@given(
    invalid_content=st.text(min_size=1, max_size=100).filter(lambda s: not s.strip().startswith('{'))
)
@settings(max_examples=100)
def test_invalid_json_descriptive_error(invalid_content):
    """
    Property 2 (补充): 格式无效的 JSON 产生描述性错误

    对格式无效的 JSON 内容，验证抛出包含文件路径信息的异常。

    **Validates: Requirements 1.4**
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        f.write(invalid_content)
        tmp_path = f.name

    try:
        with pytest.raises(ValueError) as exc_info:
            FilamentLoader.load(tmp_path)

        error_msg = str(exc_info.value)
        assert len(error_msg) > 0, "错误信息不应为空"
        assert tmp_path in error_msg, f"错误信息应包含文件路径 '{tmp_path}'，实际: '{error_msg}'"
    finally:
        os.unlink(tmp_path)


# ============================================================================
# KSLutGenerator 属性测试
# ============================================================================

from core.ks_engine.lut_generator import KSLutGenerator


# ============================================================================
# Property 3: 耗材选择验证与颜色总数计算
# Feature: ks-lut-generator, Property 3: 耗材选择验证与颜色总数计算
# Validates: Requirements 2.2, 2.4
# ============================================================================

@given(n=st.integers(min_value=1, max_value=10))
@settings(max_examples=100)
def test_filament_selection_validation(n):
    """
    Property 3: 耗材选择验证与颜色总数计算

    对任意整数 n (1≤n≤10)，n∈[2,8] 时接受并计算 n^5；n<2 时拒绝。

    **Validates: Requirements 2.2, 2.4**
    """
    is_valid, total_colors, message = KSLutGenerator.validate_selection(n)

    if n < 2:
        assert not is_valid, f"n={n} 应被拒绝"
        assert total_colors == 0
    elif n > 8:
        assert not is_valid, f"n={n} 应被拒绝（超过 8 种）"
        assert total_colors == 0
    else:
        assert is_valid, f"n={n} 应被接受"
        assert total_colors == n ** 5, f"n={n} 时颜色总数应为 {n**5}，实际: {total_colors}"


# ============================================================================
# Property 7: LUT 生成-保存-加载往返一致性
# Feature: ks-lut-generator, Property 7: LUT 生成-保存-加载往返一致性
# Validates: Requirements 4.1, 4.4, 4.5, 5.4
# ============================================================================

@given(
    filaments=st.lists(
        st.fixed_dictionaries({
            'name': st.just('TestFilament'),
            'color': st.just('#ffffff'),
            'FILAMENT_K': st.lists(
                st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False),
                min_size=3, max_size=3,
            ),
            'FILAMENT_S': st.lists(
                st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False),
                min_size=3, max_size=3,
            ),
        }),
        min_size=2, max_size=4,
    ).filter(lambda fs: len(fs) in (2, 4)),
)
@settings(max_examples=100, deadline=None)
def test_lut_roundtrip_consistency(filaments):
    """
    Property 7: LUT 生成-保存-加载往返一致性

    对 2 或 4 种耗材的合法 K/S 参数，生成→保存→加载→展平后
    与原始计算结果逐元素相等。

    **Validates: Requirements 4.1, 4.4, 4.5, 5.4**
    """
    generator = KSLutGenerator()
    selected_indices = list(range(len(filaments)))

    # 生成 LUT
    lut_grid, metadata = generator.generate(filaments, selected_indices)

    # 保存到临时文件
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "test_lut.npy")
        stacks = metadata.get("stacks")
        saved_path, total_colors = generator.save(lut_grid, file_path, stacks)

        # 加载并展平
        loaded = np.load(saved_path)
        loaded_flat = loaded.reshape(-1, 3)

        # 原始展平
        original_flat = lut_grid.reshape(-1, 3)

        # 逐元素相等
        np.testing.assert_array_equal(
            loaded_flat, original_flat,
            err_msg="LUT 保存-加载往返不一致"
        )

        # 颜色总数一致
        assert total_colors == metadata["total_colors"], (
            f"颜色总数不一致: save 返回 {total_colors}, metadata 为 {metadata['total_colors']}"
        )


# ============================================================================
# Property 8: 元数据与实际数据一致性
# Feature: ks-lut-generator, Property 8: 元数据与实际数据一致性
# Validates: Requirements 7.2
# ============================================================================

@given(
    filaments=st.lists(
        st.fixed_dictionaries({
            'name': st.just('MetaTest'),
            'color': st.just('#000000'),
            'FILAMENT_K': st.lists(
                st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False),
                min_size=3, max_size=3,
            ),
            'FILAMENT_S': st.lists(
                st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False),
                min_size=3, max_size=3,
            ),
        }),
        min_size=2, max_size=4,
    ),
)
@settings(max_examples=100, deadline=None)
def test_metadata_consistency(filaments):
    """
    Property 8: 元数据与实际数据一致性

    验证 metadata 中 total_colors 等于 LUT 展平后行数，
    num_filaments 等于实际耗材数，shape 等于实际形状。

    **Validates: Requirements 7.2**
    """
    assume(len(filaments) >= 2)

    generator = KSLutGenerator()
    selected_indices = list(range(len(filaments)))

    lut_grid, metadata = generator.generate(filaments, selected_indices)

    # total_colors 等于 LUT 展平后行数
    flat_rows = lut_grid.reshape(-1, 3).shape[0]
    assert metadata["total_colors"] == flat_rows, (
        f"total_colors {metadata['total_colors']} != 展平行数 {flat_rows}"
    )

    # num_filaments 等于实际耗材数
    assert metadata["num_filaments"] == len(filaments), (
        f"num_filaments {metadata['num_filaments']} != 实际耗材数 {len(filaments)}"
    )

    # shape 等于实际形状
    assert metadata["shape"] == lut_grid.shape, (
        f"shape {metadata['shape']} != 实际形状 {lut_grid.shape}"
    )
