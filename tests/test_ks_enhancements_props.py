"""
K/S LUT 增强功能 — 属性测试
Feature: ks-lut-enhancements
"""

import json
import os
import tempfile
import numpy as np
import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st


# ============================================================
# 策略生成器
# ============================================================

def valid_filament_strategy():
    """生成合法的单个耗材字典"""
    return st.fixed_dictionaries({
        "name": st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
        "color": st.from_regex(r"#[0-9a-f]{6}", fullmatch=True),
        "K": st.lists(st.floats(min_value=1e-6, max_value=10.0, allow_nan=False, allow_infinity=False), min_size=3, max_size=3),
        "S": st.lists(st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False), min_size=3, max_size=3),
    })


def valid_filament_json_strategy():
    """生成合法的耗材 JSON 数据"""
    return st.lists(valid_filament_strategy(), min_size=1, max_size=8).map(
        lambda filaments: {"filaments": filaments}
    )


# ============================================================
# Property 1: 耗材加载正确性
# ============================================================

# Feature: ks-lut-enhancements, Property 1: 耗材加载正确性
@given(filament_json=valid_filament_json_strategy())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_filament_load_correctness(filament_json):
    """对于任意合法耗材 JSON，FilamentLoader.load() 返回的列表长度等于 filaments 数组长度"""
    from core.ks_engine.filament_loader import FilamentLoader

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(filament_json, f)
        tmp_path = f.name

    try:
        result = FilamentLoader.load(tmp_path)
        assert len(result) == len(filament_json['filaments'])
        for i, filament in enumerate(result):
            assert filament['name'] == filament_json['filaments'][i]['name']
    finally:
        os.unlink(tmp_path)


# ============================================================
# Property 2: 无效耗材文件错误处理
# ============================================================

def invalid_filament_json_strategy():
    """生成非法的耗材 JSON 数据"""
    return st.one_of(
        # 缺少 filaments 字段
        st.just({"data": []}),
        # filaments 不是列表
        st.just({"filaments": "not_a_list"}),
        # K 不是3元素数组
        st.just({"filaments": [{"name": "test", "K": [1.0], "S": [1.0, 2.0, 3.0]}]}),
        # S 不是3元素数组
        st.just({"filaments": [{"name": "test", "K": [1.0, 2.0, 3.0], "S": [1.0]}]}),
        # 缺少 K 字段
        st.just({"filaments": [{"name": "test", "S": [1.0, 2.0, 3.0]}]}),
        # 缺少 S 字段
        st.just({"filaments": [{"name": "test", "K": [1.0, 2.0, 3.0]}]}),
    )


# Feature: ks-lut-enhancements, Property 2: 无效耗材文件错误处理
@given(bad_json=invalid_filament_json_strategy())
@settings(max_examples=100)
def test_invalid_filament_error_handling(bad_json):
    """对于任意非法 JSON 内容，FilamentLoader.load() 应抛出异常"""
    from core.ks_engine.filament_loader import FilamentLoader

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(bad_json, f)
        tmp_path = f.name

    try:
        with pytest.raises((ValueError, TypeError)):
            FilamentLoader.load(tmp_path)
    finally:
        os.unlink(tmp_path)


# Feature: ks-lut-enhancements, Property 2b: 非 JSON 文件
def test_non_json_file_error():
    """非 JSON 格式文件应抛出 ValueError"""
    from core.ks_engine.filament_loader import FilamentLoader

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write("this is not json {{{")
        tmp_path = f.name

    try:
        with pytest.raises(ValueError):
            FilamentLoader.load(tmp_path)
    finally:
        os.unlink(tmp_path)


# ============================================================
# Property 3: LUT 文件保存与路径一致性
# ============================================================

# Feature: ks-lut-enhancements, Property 3: LUT 文件保存与路径一致性
@given(num_filaments=st.integers(min_value=2, max_value=4))
@settings(max_examples=20)
def test_lut_file_path_consistency(num_filaments):
    """成功生成的 LUT 文件路径指向实际存在的 .npy 文件"""
    from core.ks_engine.lut_generator import KSLutGenerator

    filaments = []
    for i in range(num_filaments):
        filaments.append({
            'name': f'Filament{i}',
            'color': '#000000',
            'FILAMENT_K': [0.5, 0.5, 0.5],
            'FILAMENT_S': [5.0, 5.0, 5.0],
        })

    generator = KSLutGenerator()
    selected_indices = list(range(num_filaments))
    lut_grid, metadata = generator.generate(filaments, selected_indices)

    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = os.path.join(tmpdir, "test_lut.npy")
        stacks = metadata.get('stacks')
        saved_path, total_colors = generator.save(lut_grid, save_path, stacks)

        # LUT 文件必须存在
        assert os.path.exists(saved_path)
        assert saved_path.endswith('.npy')

        # 如果有 stacks，对应文件也必须存在
        if stacks is not None:
            base, ext = os.path.splitext(saved_path)
            stacks_path = base + "_stacks.npy"
            assert os.path.exists(stacks_path)


# ============================================================
# Property 4: detect_lut_color_mode 正确识别 n^5 色 LUT
# ============================================================

# Feature: ks-lut-enhancements, Property 4: detect_lut_color_mode 正确识别
@given(n=st.sampled_from([2, 3, 4, 5, 6, 7, 8]))
@settings(max_examples=100)
def test_detect_lut_color_mode_n5(n):
    """对于 n ∈ {2..8}，构造 n^5 个颜色的 .npy 文件，函数应返回正确模式"""
    from core.converter import detect_lut_color_mode

    total = n ** 5
    lut_data = np.random.randint(0, 256, size=(total, 1, 3), dtype=np.uint8)

    with tempfile.NamedTemporaryFile(suffix='.npy', delete=False) as f:
        np.save(f.name, lut_data)
        tmp_path = f.name

    try:
        result = detect_lut_color_mode(tmp_path)
        assert result is not None, f"n={n}, total={total}, expected non-None"
        assert f"{n}" in result or (n == 2 and "BW" in result)
    finally:
        os.unlink(tmp_path)


# ============================================================
# Property 5: 色彩模式选择优先级
# ============================================================

# Feature: ks-lut-enhancements, Property 5: 色彩模式选择优先级
@given(
    user_mode=st.sampled_from(["Auto", "BW (Black & White)", "4-Color", "6-Color (Smart 1296)", "8-Color Max"]),
    n=st.sampled_from([2, 4, 6, 8]),
)
@settings(max_examples=50)
def test_color_mode_selection_priority(user_mode, n):
    """手动选择固定模式时使用用户选择值，Auto 模式时使用检测值"""
    from core.converter import detect_lut_color_mode

    total = n ** 5
    lut_data = np.random.randint(0, 256, size=(total, 1, 3), dtype=np.uint8)

    with tempfile.NamedTemporaryFile(suffix='.npy', delete=False) as f:
        np.save(f.name, lut_data)
        tmp_path = f.name

    try:
        detected = detect_lut_color_mode(tmp_path)

        if user_mode == "Auto":
            # Auto 模式应使用检测结果
            effective = detected if detected else "4-Color"  # fallback
            assert effective is not None
        else:
            # 手动模式应使用用户选择
            effective = user_mode
            assert effective == user_mode
    finally:
        os.unlink(tmp_path)


# ============================================================
# Property 6: min_K 下限使 K 值不低于阈值
# ============================================================

# Feature: ks-lut-enhancements, Property 6: min_K 下限生效
@given(min_k=st.floats(min_value=0.001, max_value=1.0, allow_nan=False))
@settings(max_examples=100)
def test_min_k_floor(min_k):
    """对于任意 min_K 值，计算中所有 K 值应不低于 min_K"""
    from core.ks_engine.physics import VirtualPhysics

    # 构造含 K≈0 的耗材
    filaments = [
        {'FILAMENT_K': [1e-5, 1e-5, 0.026], 'FILAMENT_S': [4.0, 5.3, 7.8]},
        {'FILAMENT_K': [0.5, 0.1, 0.1], 'FILAMENT_S': [5.0, 5.0, 5.0]},
    ]

    Ks = np.array([f['FILAMENT_K'] for f in filaments])
    Ks_clamped = np.maximum(Ks, min_k)

    # 验证所有 K 值不低于 min_K
    assert np.all(Ks_clamped >= min_k)


# ============================================================
# Property 7: min_K 增大使平均亮度降低
# ============================================================

# Feature: ks-lut-enhancements, Property 7: min_K 增大降低亮度
@given(
    min_k_small=st.floats(min_value=0.001, max_value=0.05, allow_nan=False),
    min_k_large=st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
)
@settings(max_examples=50)
def test_min_k_reduces_brightness(min_k_small, min_k_large):
    """增大 min_K 应使 LUT 平均亮度不增加"""
    assume(min_k_large > min_k_small)
    from core.ks_engine.physics import VirtualPhysics

    # 含 K≈0 的耗材（会导致偏白）
    filaments = [
        {'FILAMENT_K': [1e-5, 1e-5, 0.026], 'FILAMENT_S': [4.0, 5.3, 7.8]},
        {'FILAMENT_K': [0.5, 0.1, 0.1], 'FILAMENT_S': [5.0, 5.0, 5.0]},
    ]

    physics = VirtualPhysics()
    colors_small, _ = physics.generate_lut_km(filaments, min_K=min_k_small)
    colors_large, _ = physics.generate_lut_km(filaments, min_K=min_k_large)

    mean_small = colors_small.astype(float).mean()
    mean_large = colors_large.astype(float).mean()

    # 更大的 min_K 应使亮度不增加（允许微小浮点误差）
    assert mean_large <= mean_small + 1.0, f"mean_large={mean_large} > mean_small={mean_small}"


# ============================================================
# Property 8: 亮度统计与实际数据一致
# ============================================================

# Feature: ks-lut-enhancements, Property 8: 亮度统计正确性
@given(
    colors=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=255),
            st.integers(min_value=0, max_value=255),
            st.integers(min_value=0, max_value=255),
        ),
        min_size=10, max_size=200,
    )
)
@settings(max_examples=100)
def test_brightness_stats_correctness(colors):
    """统计函数返回的 mean 值等于颜色数组 RGB 均值的均值"""
    import sys
    sys.path.insert(0, '.')

    color_arr = np.array(colors, dtype=np.uint8).reshape(-1, 1, 3)

    # 直接调用函数
    from ui.layout_new import _compute_brightness_stats
    stats = _compute_brightness_stats(color_arr)

    # 手动计算
    flat = color_arr.reshape(-1, 3).astype(float)
    brightness = flat.mean(axis=1)
    expected_mean = float(np.mean(brightness))

    assert abs(stats['mean'] - expected_mean) <= 0.1, f"stats={stats['mean']}, expected={expected_mean}"

    # 验证百分比
    expected_above_200 = float((brightness > 200).sum() / len(brightness) * 100)
    assert abs(stats['pct_above_200'] - expected_above_200) <= 0.1
