#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Property-based tests for LUT Palette Integration.

Uses Hypothesis to verify correctness properties across arbitrary inputs.
Feature: lut-palette-integration
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from config import LUTMetadata, PaletteEntry

# ---------------------------------------------------------------------------
# Strategies — 生成随机 PaletteEntry 和 LUTMetadata
# ---------------------------------------------------------------------------

# 颜色名称：非空可打印字符串
_color_names = st.text(
    st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

# 材料名称：非空可打印字符串
_material_names = st.text(
    st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

# hex_color：可选，格式 #RRGGBB
_hex_colors = st.one_of(
    st.none(),
    st.from_regex(r"#[0-9A-Fa-f]{6}", fullmatch=True),
)

# PaletteEntry strategy
palette_entry_strategy = st.builds(
    PaletteEntry,
    color=_color_names,
    material=_material_names,
    hex_color=_hex_colors,
)

# LUTMetadata strategy（palette 颜色名唯一，新对象格式要求）
lut_metadata_strategy = st.builds(
    LUTMetadata,
    palette=st.lists(palette_entry_strategy, min_size=0, max_size=8).filter(
        lambda entries: len(set(e.color for e in entries)) == len(entries)
    ),
    max_color_layers=st.integers(min_value=1, max_value=20),
    layer_height_mm=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    line_width_mm=st.floats(min_value=0.1, max_value=2.0, allow_nan=False, allow_infinity=False),
    base_layers=st.integers(min_value=1, max_value=100),
    base_channel_idx=st.integers(min_value=0, max_value=7),
    layer_order=st.sampled_from(["Top2Bottom", "Bottom2Top"]),
)

# 序列化字典必须包含的所有顶层字段
REQUIRED_TOP_LEVEL_FIELDS = {
    "palette",
    "max_color_layers",
    "layer_height_mm",
    "line_width_mm",
    "base_layers",
    "base_channel_idx",
    "layer_order",
}


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 1: LUTMetadata 序列化往返一致性
# **Validates: Requirements 1.1, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 6.1, 6.2, 6.3**
# ---------------------------------------------------------------------------
@given(metadata=lut_metadata_strategy)
@settings(max_examples=100)
def test_metadata_roundtrip(metadata: LUTMetadata):
    """Property 1: 对于任意有效的 LUTMetadata 对象，to_dict() → from_dict()
    往返后应产生等价的对象，且序列化字典包含所有必需顶层字段。
    """
    serialized = metadata.to_dict()

    # 验证序列化字典包含所有必需顶层字段
    missing = REQUIRED_TOP_LEVEL_FIELDS - set(serialized.keys())
    assert not missing, f"序列化字典缺少必需字段: {missing}"

    # 往返反序列化
    restored = LUTMetadata.from_dict(serialized)

    # 验证打印参数等价
    assert restored.max_color_layers == metadata.max_color_layers, (
        f"max_color_layers 不一致: {restored.max_color_layers} != {metadata.max_color_layers}"
    )
    assert restored.layer_height_mm == metadata.layer_height_mm, (
        f"layer_height_mm 不一致: {restored.layer_height_mm} != {metadata.layer_height_mm}"
    )
    assert restored.line_width_mm == metadata.line_width_mm, (
        f"line_width_mm 不一致: {restored.line_width_mm} != {metadata.line_width_mm}"
    )
    assert restored.base_layers == metadata.base_layers, (
        f"base_layers 不一致: {restored.base_layers} != {metadata.base_layers}"
    )
    assert restored.base_channel_idx == metadata.base_channel_idx, (
        f"base_channel_idx 不一致: {restored.base_channel_idx} != {metadata.base_channel_idx}"
    )
    assert restored.layer_order == metadata.layer_order, (
        f"layer_order 不一致: {restored.layer_order!r} != {metadata.layer_order!r}"
    )

    # 验证 palette 长度一致
    assert len(restored.palette) == len(metadata.palette), (
        f"palette 长度不一致: {len(restored.palette)} != {len(metadata.palette)}"
    )

    # 验证每个 PaletteEntry 等价
    for i, (orig, rest) in enumerate(zip(metadata.palette, restored.palette)):
        assert rest.color == orig.color, (
            f"palette[{i}].color 不一致: {rest.color!r} != {orig.color!r}"
        )
        assert rest.material == orig.material, (
            f"palette[{i}].material 不一致: {rest.material!r} != {orig.material!r}"
        )
        assert rest.hex_color == orig.hex_color, (
            f"palette[{i}].hex_color 不一致: {rest.hex_color!r} != {orig.hex_color!r}"
        )


# ---------------------------------------------------------------------------
# Strategies — 旧版格式测试用生成器
# ---------------------------------------------------------------------------

# 打印参数字段名列表（用于部分缺失测试）
_PRINT_PARAM_FIELDS = [
    "max_color_layers",
    "layer_height_mm",
    "line_width_mm",
    "base_layers",
    "base_channel_idx",
    "layer_order",
]

# 所有 LUTMetadata 相关字段（生成无关字段时需排除）
_ALL_METADATA_FIELDS = set(_PRINT_PARAM_FIELDS) | {"palette"}

# 无关字段的键名：非空可打印字符串，排除 metadata 字段名
_extra_keys = st.text(
    st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in _ALL_METADATA_FIELDS)

# 无关字段的值：简单 JSON 兼容值
_extra_values = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.text(max_size=20),
    st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
    st.booleans(),
)

# 完全缺失 palette 和打印参数的旧版字典（只含无关字段）
_legacy_dict_no_metadata = st.dictionaries(
    keys=_extra_keys,
    values=_extra_values,
    min_size=0,
    max_size=5,
)

# 部分打印参数子集 strategy（随机选择 1~5 个字段缺失）
_partial_subset = st.lists(
    st.sampled_from(_PRINT_PARAM_FIELDS),
    min_size=1,
    max_size=len(_PRINT_PARAM_FIELDS) - 1,
    unique=True,
)


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 5: 旧版格式向后兼容
# **Validates: Requirements 1.3, 1.12**
# ---------------------------------------------------------------------------
@given(extra_data=_legacy_dict_no_metadata)
@settings(max_examples=100)
def test_legacy_format_backward_compat(extra_data: dict):
    """Property 5: 对于任意不含 palette 和打印参数字段的旧版 JSON 数据，
    通过 LUTMetadata.from_dict() 加载后，应自动填充 PrinterConfig 默认值。

    同时测试部分字段缺失的情况。
    """
    # --- 场景 1: 完全缺失所有 metadata 字段 ---
    result = LUTMetadata.from_dict(extra_data)

    # 验证默认打印参数
    assert result.max_color_layers == 5, (
        f"max_color_layers 应为 5，实际: {result.max_color_layers}"
    )
    assert result.layer_height_mm == 0.08, (
        f"layer_height_mm 应为 0.08，实际: {result.layer_height_mm}"
    )
    assert result.line_width_mm == 0.42, (
        f"line_width_mm 应为 0.42，实际: {result.line_width_mm}"
    )
    assert result.base_layers == 10, (
        f"base_layers 应为 10，实际: {result.base_layers}"
    )
    assert result.base_channel_idx == 0, (
        f"base_channel_idx 应为 0，实际: {result.base_channel_idx}"
    )
    assert result.layer_order == "Top2Bottom", (
        f"layer_order 应为 'Top2Bottom'，实际: {result.layer_order!r}"
    )
    # palette 应为空列表
    assert result.palette == [], (
        f"palette 应为空列表，实际: {result.palette}"
    )

    # --- 场景 2: 部分打印参数存在，其余缺失 ---
    # 构造一个只包含部分打印参数的字典
    partial_data = dict(extra_data)
    # 设置一些非默认值用于验证保留
    partial_data["max_color_layers"] = 10
    partial_data["layer_height_mm"] = 0.12
    # 不设置 line_width_mm, base_layers, base_channel_idx, layer_order

    partial_result = LUTMetadata.from_dict(partial_data)

    # 已设置的字段应保留用户值
    assert partial_result.max_color_layers == 10, (
        f"已设置的 max_color_layers 应为 10，实际: {partial_result.max_color_layers}"
    )
    assert partial_result.layer_height_mm == 0.12, (
        f"已设置的 layer_height_mm 应为 0.12，实际: {partial_result.layer_height_mm}"
    )
    # 缺失的字段应使用默认值
    assert partial_result.line_width_mm == 0.42, (
        f"缺失的 line_width_mm 应为 0.42，实际: {partial_result.line_width_mm}"
    )
    assert partial_result.base_layers == 10, (
        f"缺失的 base_layers 应为 10，实际: {partial_result.base_layers}"
    )
    assert partial_result.base_channel_idx == 0, (
        f"缺失的 base_channel_idx 应为 0，实际: {partial_result.base_channel_idx}"
    )
    assert partial_result.layer_order == "Top2Bottom", (
        f"缺失的 layer_order 应为 'Top2Bottom'，实际: {partial_result.layer_order!r}"
    )
    # palette 仍应为空列表
    assert partial_result.palette == [], (
        f"palette 应为空列表，实际: {partial_result.palette}"
    )


# ---------------------------------------------------------------------------
# Strategies — 空白字符串生成器（Property 6 用）
# ---------------------------------------------------------------------------

# 仅由空白字符组成的字符串（空格、制表符、换行等），包含空字符串
_whitespace_only = st.from_regex(r"[\s]*", fullmatch=True).filter(
    lambda s: s.strip() == ""
)

# 非空字符串（strip 后至少有一个字符）
_non_empty_names = st.text(
    st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 6: 颜色名称非空校验
# **Validates: Requirements 2.8**
# ---------------------------------------------------------------------------
@given(whitespace_name=_whitespace_only)
@settings(max_examples=100)
def test_color_name_whitespace_rejected(whitespace_name: str):
    """Property 6: 对于任意仅由空白字符组成的字符串（包括空字符串），
    LUTMetadata.validate_color_name() 应返回 False（拒绝）。
    同时验证非空字符串返回 True（正向对照）。
    """
    # 空白字符串应被拒绝
    assert LUTMetadata.validate_color_name(whitespace_name) is False, (
        f"空白字符串 {whitespace_name!r} 应被 validate_color_name 拒绝，但返回了 True"
    )


@given(valid_name=_non_empty_names)
@settings(max_examples=100)
def test_color_name_non_empty_accepted(valid_name: str):
    """Property 6 正向对照: 对于任意 strip 后非空的字符串，
    LUTMetadata.validate_color_name() 应返回 True（接受）。
    """
    assert LUTMetadata.validate_color_name(valid_name) is True, (
        f"非空字符串 {valid_name!r} 应被 validate_color_name 接受，但返回了 False"
    )


# ---------------------------------------------------------------------------
# Strategies — RGB / stacks / metadata 生成器（Property 2, 3 用）
# ---------------------------------------------------------------------------

import os
import tempfile
import numpy as np

# RGB 数组 strategy: (N, 3) uint8, N ∈ [1, 50]
_rgb_array_strategy = st.integers(min_value=1, max_value=50).flatmap(
    lambda n: st.lists(
        st.tuples(
            st.integers(0, 255),
            st.integers(0, 255),
            st.integers(0, 255),
        ),
        min_size=n,
        max_size=n,
    ).map(lambda rows: np.array(rows, dtype=np.uint8))
)

# stacks 数组 strategy: (N, L) int32, L ∈ [1, 8], 值 ∈ [0, 7]
def _stacks_for_n(n: int):
    """Generate stacks array with N rows and random column count."""
    return st.integers(min_value=1, max_value=8).flatmap(
        lambda cols: st.lists(
            st.lists(
                st.integers(0, 7),
                min_size=cols,
                max_size=cols,
            ),
            min_size=n,
            max_size=n,
        ).map(lambda rows: np.array(rows, dtype=np.int32))
    )


# 组合 strategy: (rgb, stacks, metadata) 保证 rgb 和 stacks 行数一致
# 注意：Keyed JSON roundtrip 需要非空 palette，否则加载时会推断默认值
# palette 颜色名必须唯一（新对象格式以颜色名为 key）
_lut_metadata_with_palette = st.builds(
    LUTMetadata,
    palette=st.lists(palette_entry_strategy, min_size=1, max_size=8).filter(
        lambda entries: len(set(e.color for e in entries)) == len(entries)
    ),
    max_color_layers=st.integers(min_value=1, max_value=20),
    layer_height_mm=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    line_width_mm=st.floats(min_value=0.1, max_value=2.0, allow_nan=False, allow_infinity=False),
    base_layers=st.integers(min_value=1, max_value=100),
    base_channel_idx=st.integers(min_value=0, max_value=7),
    layer_order=st.sampled_from(["Top2Bottom", "Bottom2Top"]),
)

# 组合 strategy: (rgb, stacks, metadata) 保证 stacks 值在 palette 索引范围内
_rgb_stacks_metadata = st.integers(min_value=1, max_value=30).flatmap(
    lambda n: st.integers(min_value=1, max_value=8).flatmap(
        lambda palette_size: st.tuples(
            st.lists(
                st.tuples(
                    st.integers(0, 255),
                    st.integers(0, 255),
                    st.integers(0, 255),
                ),
                min_size=n,
                max_size=n,
            ).map(lambda rows: np.array(rows, dtype=np.uint8)),
            st.integers(min_value=1, max_value=8).flatmap(
                lambda cols: st.lists(
                    st.lists(
                        st.integers(0, palette_size - 1),
                        min_size=cols,
                        max_size=cols,
                    ),
                    min_size=n,
                    max_size=n,
                ).map(lambda rows: np.array(rows, dtype=np.int32))
            ),
            st.lists(
                palette_entry_strategy,
                min_size=palette_size,
                max_size=palette_size,
            ).filter(
                lambda entries: len(set(e.color for e in entries)) == len(entries)
            ).map(
                lambda entries: LUTMetadata(
                    palette=entries,
                    max_color_layers=5,
                    layer_height_mm=0.08,
                    line_width_mm=0.42,
                    base_layers=10,
                    base_channel_idx=0,
                    layer_order="Top2Bottom",
                )
            ),
        )
    )
)


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 2: Keyed JSON 文件往返一致性
# **Validates: Requirements 1.5, 6.1, 6.2, 6.3**
# ---------------------------------------------------------------------------
@given(data=_rgb_stacks_metadata)
@settings(max_examples=50, deadline=None)
def test_keyed_json_file_roundtrip(data):
    """Property 2: 对于任意有效的 LUT 数据（RGB + stacks + metadata），
    通过 save_keyed_json() 保存后再通过 load_lut_with_metadata() 加载，
    应还原出等价的 RGB 数组、stacks 数组和 LUTMetadata。
    """
    from utils.lut_manager import LUTManager

    rgb, stacks, metadata = data

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_roundtrip.json")
        LUTManager.save_keyed_json(path, rgb, stacks, metadata)

        loaded_rgb, loaded_stacks, loaded_metadata = LUTManager.load_lut_with_metadata(path)

    # --- 验证 RGB 往返一致性 ---
    # RGB→Lab→RGB 转换有精度损失（sRGB gamma + Lab 量化），容差 ±2
    assert loaded_rgb.shape == rgb.shape, (
        f"RGB shape 不一致: {loaded_rgb.shape} != {rgb.shape}"
    )
    diff = np.abs(loaded_rgb.astype(int) - rgb.astype(int))
    assert np.all(diff <= 2), (
        f"RGB 值差异超过容差 2, 最大差异: {diff.max()}"
    )

    # --- 验证 stacks 往返一致性 ---
    assert loaded_stacks is not None, "stacks 不应为 None"
    assert loaded_stacks.shape == stacks.shape, (
        f"stacks shape 不一致: {loaded_stacks.shape} != {stacks.shape}"
    )
    assert np.array_equal(loaded_stacks, stacks), "stacks 值不一致"

    # --- 验证 metadata 往返一致性 ---
    assert loaded_metadata.max_color_layers == metadata.max_color_layers
    assert loaded_metadata.layer_height_mm == metadata.layer_height_mm
    assert loaded_metadata.line_width_mm == metadata.line_width_mm
    assert loaded_metadata.base_layers == metadata.base_layers
    assert loaded_metadata.base_channel_idx == metadata.base_channel_idx
    assert loaded_metadata.layer_order == metadata.layer_order

    # palette 长度一致
    assert len(loaded_metadata.palette) == len(metadata.palette), (
        f"palette 长度不一致: {len(loaded_metadata.palette)} != {len(metadata.palette)}"
    )
    for i, (orig, rest) in enumerate(zip(metadata.palette, loaded_metadata.palette)):
        assert rest.color == orig.color, f"palette[{i}].color 不一致"
        assert rest.material == orig.material, f"palette[{i}].material 不一致"
        assert rest.hex_color == orig.hex_color, f"palette[{i}].hex_color 不一致"


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 3: .npz 元数据往返一致性
# **Validates: Requirements 6.4, 6.5, 3.4**
# ---------------------------------------------------------------------------
@given(data=_rgb_stacks_metadata)
@settings(max_examples=50, deadline=None)
def test_npz_metadata_roundtrip(data):
    """Property 3: 对于任意有效的 LUT 数据（RGB + stacks + metadata），
    通过 save_npz_with_metadata() 保存后再通过 load_lut_with_metadata() 加载，
    应还原出等价的 RGB 数组、stacks 数组和 LUTMetadata。
    且 .npz 文件中应包含 metadata_json 键。
    """
    from utils.lut_manager import LUTManager

    rgb, stacks, metadata = data

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_roundtrip.npz")
        LUTManager.save_npz_with_metadata(path, rgb, stacks, metadata)

        # 验证 .npz 包含 metadata_json 键
        npz = np.load(path, allow_pickle=False)
        assert "metadata_json" in npz, ".npz 文件应包含 metadata_json 键"
        assert "rgb" in npz, ".npz 文件应包含 rgb 键"
        assert "stacks" in npz, ".npz 文件应包含 stacks 键"
        npz.close()

        loaded_rgb, loaded_stacks, loaded_metadata = LUTManager.load_lut_with_metadata(path)

    # --- 验证 RGB 往返一致性 ---
    assert np.array_equal(loaded_rgb, rgb), "RGB 值不一致"

    # --- 验证 stacks 往返一致性 ---
    assert loaded_stacks is not None, "stacks 不应为 None"
    assert np.array_equal(loaded_stacks, stacks), "stacks 值不一致"

    # --- 验证 metadata 往返一致性 ---
    assert loaded_metadata.max_color_layers == metadata.max_color_layers
    assert loaded_metadata.layer_height_mm == metadata.layer_height_mm
    assert loaded_metadata.line_width_mm == metadata.line_width_mm
    assert loaded_metadata.base_layers == metadata.base_layers
    assert loaded_metadata.base_channel_idx == metadata.base_channel_idx
    assert loaded_metadata.layer_order == metadata.layer_order

    # palette 长度一致
    assert len(loaded_metadata.palette) == len(metadata.palette), (
        f"palette 长度不一致: {len(loaded_metadata.palette)} != {len(metadata.palette)}"
    )
    for i, (orig, rest) in enumerate(zip(metadata.palette, loaded_metadata.palette)):
        assert rest.color == orig.color, f"palette[{i}].color 不一致"
        assert rest.material == orig.material, f"palette[{i}].material 不一致"
        assert rest.hex_color == orig.hex_color, f"palette[{i}].hex_color 不一致"


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 4: 调色板长度与颜色模式通道数一致
# **Validates: Requirements 1.2, 2.7**
# ---------------------------------------------------------------------------
def test_palette_length_matches_color_mode():
    """Property 4: 对于所有颜色模式，infer_default_metadata() 返回的调色板长度
    应等于 ColorSystem 中该模式定义的通道数（slots 列表长度）。
    """
    from utils.lut_manager import LUTManager
    from config import ColorSystem

    # 所有需要测试的颜色模式及其对应的 ColorSystem 配置
    test_modes = [
        ("BW", "BW (Black & White)", "/tmp/test_BW.npy", ColorSystem.BW),
        ("4-Color (RYBW)", "4-Color (RYBW)", "/tmp/test_4-Color_RYBW.npy", ColorSystem.RYBW),
        ("4-Color (CMYW)", "4-Color (CMYW)", "/tmp/test_4-Color_CMYW.npy", ColorSystem.CMYW),
        ("6-Color", "6-Color (Smart 1296)", "/tmp/test_6-Color.npy", ColorSystem.SIX_COLOR),
        ("5-Color Extended", "5-Color Extended", "/tmp/test_5-Color.npy", ColorSystem.FIVE_COLOR_EXTENDED),
        ("8-Color", "8-Color Max", "/tmp/test_8-Color.npy", ColorSystem.EIGHT_COLOR),
        # Merged 模式仅对 .npz 文件触发
        ("Merged", "Merged", "/tmp/test_Merged.npz", ColorSystem.EIGHT_COLOR),
    ]

    for mode_label, display_hint, file_path, expected_config in test_modes:
        # 构造一个能被 infer_color_mode 识别的 display_name
        metadata = LUTManager.infer_default_metadata(
            display_name=display_hint,
            file_path=file_path,
            color_count=100,
        )
        expected_len = len(expected_config["slots"])
        actual_len = len(metadata.palette)
        assert actual_len == expected_len, (
            f"模式 {mode_label}: palette 长度 {actual_len} != "
            f"ColorSystem slots 长度 {expected_len}"
        )
        # 验证颜色名称与 slots 一致
        expected_names = expected_config["slots"]
        actual_names = [e.color for e in metadata.palette]
        assert actual_names == expected_names, (
            f"模式 {mode_label}: palette 颜色名称 {actual_names} != "
            f"ColorSystem slots {expected_names}"
        )


# ---------------------------------------------------------------------------
# Strategies — 合并测试用生成器（Property 7-11 用）
# ---------------------------------------------------------------------------

from core.lut_merger import LUTMerger, _STANDARD_SLOT_ORDER, _MODE_PRIORITY

# 标准颜色名称 strategy
_standard_color_names = st.sampled_from(_STANDARD_SLOT_ORDER)

# 自定义颜色名称 strategy（排除标准名称）
_custom_color_names = st.text(
    st.characters(whitelist_categories=("L", "N")),
    min_size=2,
    max_size=20,
).filter(lambda s: s.strip() != "" and s not in _STANDARD_SLOT_ORDER)

# 带指定颜色名称的 PaletteEntry strategy
def _palette_entry_with_name(name_strategy):
    return st.builds(
        PaletteEntry,
        color=name_strategy,
        material=_material_names,
        hex_color=_hex_colors,
    )


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 7: 合并时以 Color_Name 匹配且优先级正确
# **Validates: Requirements 3.1, 3.2, 3.3**
# ---------------------------------------------------------------------------
@given(
    shared_name=_standard_color_names,
    hex1=st.from_regex(r"#[0-9A-Fa-f]{6}", fullmatch=True),
    hex2=st.from_regex(r"#[0-9A-Fa-f]{6}", fullmatch=True),
    mat1=_material_names,
    mat2=_material_names,
    priority_low=st.integers(min_value=0, max_value=5),
    priority_high=st.integers(min_value=6, max_value=10),
)
@settings(max_examples=100)
def test_merge_priority_resolution(shared_name, hex1, hex2, mat1, mat2,
                                   priority_low, priority_high):
    """Property 7: 对于两组包含相同 Color_Name 但不同 hex_color/material 的调色板，
    merge_palettes() 应保留优先级更高的 LUT 的 hex_color 和 material 值。
    """
    # 低优先级 metadata
    meta_low = LUTMetadata(
        palette=[PaletteEntry(color=shared_name, material=mat1, hex_color=hex1)]
    )
    # 高优先级 metadata
    meta_high = LUTMetadata(
        palette=[PaletteEntry(color=shared_name, material=mat2, hex_color=hex2)]
    )

    merged = LUTMerger.merge_palettes(
        [meta_low, meta_high],
        [priority_low, priority_high],
    )

    # 应只有一个条目（同名合并）
    matching = [e for e in merged if e.color == shared_name]
    assert len(matching) == 1, (
        f"合并后应只有一个 {shared_name} 条目，实际: {len(matching)}"
    )

    winner = matching[0]
    # 高优先级的值应被保留
    assert winner.hex_color == hex2, (
        f"hex_color 应为高优先级值 {hex2!r}，实际: {winner.hex_color!r}"
    )
    assert winner.material == mat2, (
        f"material 应为高优先级值 {mat2!r}，实际: {winner.material!r}"
    )


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 8: 合并调色板排序正确
# **Validates: Requirements 3.6, 3.7**
# ---------------------------------------------------------------------------
@given(
    standard_subset=st.lists(
        _standard_color_names, min_size=1, max_size=8, unique=True
    ),
    custom_names=st.lists(
        _custom_color_names, min_size=0, max_size=3, unique=True
    ),
)
@settings(max_examples=100)
def test_merged_palette_ordering(standard_subset, custom_names):
    """Property 8: 合并后的调色板中，标准颜色按 8-Color 槽位顺序排列在前，
    自定义颜色追加在标准颜色之后。
    """
    # 构建 palette entries（混合标准和自定义）
    all_names = standard_subset + custom_names
    palette = [
        PaletteEntry(color=name, material="PLA Basic")
        for name in all_names
    ]
    meta = LUTMetadata(palette=palette)

    merged = LUTMerger.merge_palettes([meta], [1])

    merged_names = [e.color for e in merged]

    # 验证总数正确（无重复名称）
    assert len(merged_names) == len(set(all_names)), (
        f"合并后条目数 {len(merged_names)} != 去重后输入数 {len(set(all_names))}"
    )

    # 分离标准和自定义
    standard_in_result = [n for n in merged_names if n in _STANDARD_SLOT_ORDER]
    custom_in_result = [n for n in merged_names if n not in _STANDARD_SLOT_ORDER]

    # 标准颜色应在自定义颜色之前
    if standard_in_result and custom_in_result:
        last_standard_idx = max(merged_names.index(n) for n in standard_in_result)
        first_custom_idx = min(merged_names.index(n) for n in custom_in_result)
        assert last_standard_idx < first_custom_idx, (
            f"标准颜色应在自定义颜色之前: 最后标准索引 {last_standard_idx}, "
            f"首个自定义索引 {first_custom_idx}"
        )

    # 标准颜色应按 _STANDARD_SLOT_ORDER 的相对顺序排列
    if len(standard_in_result) > 1:
        slot_indices = [_STANDARD_SLOT_ORDER.index(n) for n in standard_in_result]
        assert slot_indices == sorted(slot_indices), (
            f"标准颜色顺序不正确: {standard_in_result}, "
            f"期望按 _STANDARD_SLOT_ORDER 排列"
        )


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 9: 缺失调色板的 LUT 合并时自动推断
# **Validates: Requirements 3.5**
# ---------------------------------------------------------------------------
@given(
    color_mode=st.sampled_from(["BW", "4-Color", "6-Color", "8-Color"]),
    explicit_palette=st.lists(
        st.builds(
            PaletteEntry,
            color=_standard_color_names,
            material=st.just("PLA Basic"),
        ),
        min_size=1,
        max_size=4,
        unique_by=lambda e: e.color,
    ),
)
@settings(max_examples=100)
def test_merge_infers_missing_palette(color_mode, explicit_palette):
    """Property 9: 当合并的 LUT 中有部分不含调色板信息时，
    merge_luts() 应为缺失调色板的 LUT 自动推断默认调色板，
    合并结果的调色板应包含所有颜色名称（推断 + 显式）。
    """
    from config import ColorSystem as CS

    # metadata with explicit palette
    meta_with = LUTMetadata(palette=list(explicit_palette))
    # metadata with empty palette (should be auto-inferred)
    meta_empty = LUTMetadata(palette=[])

    # Build minimal LUT entries for merge_luts
    rgb1 = np.array([[255, 0, 0]], dtype=np.uint8)
    stacks1 = np.array([[0, 0, 0, 0, 0]], dtype=np.int32)
    rgb2 = np.array([[0, 255, 0]], dtype=np.uint8)
    stacks2 = np.array([[1, 1, 1, 1, 1]], dtype=np.int32)

    lut_entries = [
        (rgb1, stacks1, "8-Color"),
        (rgb2, stacks2, color_mode),
    ]

    _, _, stats = LUTMerger.merge_luts(
        lut_entries,
        dedup_threshold=0,
        metadata_list=[meta_with, meta_empty],
    )

    merged_meta = stats.get("merged_metadata")
    assert merged_meta is not None, "merged_metadata 不应为 None"

    merged_names = {e.color for e in merged_meta.palette}

    # 显式 palette 的颜色名称应在合并结果中
    for entry in explicit_palette:
        assert entry.color in merged_names, (
            f"显式颜色 {entry.color!r} 应在合并结果中，实际: {merged_names}"
        )

    # 自动推断的颜色名称也应在合并结果中
    inferred_conf = CS.get(color_mode)
    inferred_slots = inferred_conf.get("slots", [])
    for slot_name in inferred_slots:
        assert slot_name in merged_names, (
            f"推断颜色 {slot_name!r} 应在合并结果中，实际: {merged_names}"
        )


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 10: 打印参数兼容性校验
# **Validates: Requirements 7.1, 7.2, 7.3, 7.4**
# ---------------------------------------------------------------------------
@given(
    height1=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    height2=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    width1=st.floats(min_value=0.1, max_value=2.0, allow_nan=False, allow_infinity=False),
    width2=st.floats(min_value=0.1, max_value=2.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_print_param_validation(height1, height2, width1, width2):
    """Property 10: 当 layer_height_mm 或 line_width_mm 不一致时，
    validate_print_params() 应返回不兼容状态并生成包含具体差异值的警告信息。
    当所有值一致时，应返回兼容状态且无警告。
    """
    meta1 = LUTMetadata(layer_height_mm=height1, line_width_mm=width1)
    meta2 = LUTMetadata(layer_height_mm=height2, line_width_mm=width2)

    compatible, warnings = LUTMerger.validate_print_params([meta1, meta2])

    heights_match = round(height1, 4) == round(height2, 4)
    widths_match = round(width1, 4) == round(width2, 4)

    if heights_match and widths_match:
        assert compatible is True, (
            f"参数一致时应返回兼容: h1={height1}, h2={height2}, w1={width1}, w2={width2}"
        )
        assert warnings == [], (
            f"参数一致时不应有警告，实际: {warnings}"
        )
    else:
        assert compatible is False, (
            f"参数不一致时应返回不兼容: h1={height1}, h2={height2}, w1={width1}, w2={width2}"
        )
        assert len(warnings) > 0, "参数不一致时应有警告信息"

        if not heights_match:
            height_warnings = [w for w in warnings if "layer_height_mm" in w]
            assert len(height_warnings) > 0, (
                f"layer_height_mm 不一致时应有对应警告"
            )

        if not widths_match:
            width_warnings = [w for w in warnings if "line_width_mm" in w]
            assert len(width_warnings) > 0, (
                f"line_width_mm 不一致时应有对应警告"
            )


# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 11: 合并后打印参数取最高优先级
# **Validates: Requirements 7.5**
# ---------------------------------------------------------------------------
@given(
    meta_low=st.builds(
        LUTMetadata,
        palette=st.just([PaletteEntry(color="White", material="PLA Basic")]),
        layer_height_mm=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
        line_width_mm=st.floats(min_value=0.1, max_value=2.0, allow_nan=False, allow_infinity=False),
        max_color_layers=st.integers(min_value=1, max_value=20),
        base_layers=st.integers(min_value=1, max_value=100),
        base_channel_idx=st.integers(min_value=0, max_value=7),
        layer_order=st.sampled_from(["Top2Bottom", "Bottom2Top"]),
    ),
    meta_high=st.builds(
        LUTMetadata,
        palette=st.just([PaletteEntry(color="White", material="PLA Basic")]),
        layer_height_mm=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
        line_width_mm=st.floats(min_value=0.1, max_value=2.0, allow_nan=False, allow_infinity=False),
        max_color_layers=st.integers(min_value=1, max_value=20),
        base_layers=st.integers(min_value=1, max_value=100),
        base_channel_idx=st.integers(min_value=0, max_value=7),
        layer_order=st.sampled_from(["Top2Bottom", "Bottom2Top"]),
    ),
)
@settings(max_examples=100)
def test_merge_print_params_priority(meta_low, meta_high):
    """Property 11: 合并后的打印参数应等于优先级最高的 LUT 的打印参数值。
    """
    # 低优先级 LUT: BW (priority 0)
    rgb_low = np.array([[100, 100, 100]], dtype=np.uint8)
    stacks_low = np.array([[0, 0, 0, 0, 0]], dtype=np.int32)

    # 高优先级 LUT: 8-Color (priority 3)
    rgb_high = np.array([[200, 200, 200]], dtype=np.uint8)
    stacks_high = np.array([[1, 1, 1, 1, 1]], dtype=np.int32)

    lut_entries = [
        (rgb_low, stacks_low, "BW"),
        (rgb_high, stacks_high, "8-Color"),
    ]

    _, _, stats = LUTMerger.merge_luts(
        lut_entries,
        dedup_threshold=0,
        metadata_list=[meta_low, meta_high],
    )

    merged_meta = stats.get("merged_metadata")
    assert merged_meta is not None, "merged_metadata 不应为 None"

    # 8-Color 优先级最高，应使用 meta_high 的打印参数
    assert merged_meta.layer_height_mm == meta_high.layer_height_mm, (
        f"layer_height_mm 应为高优先级值 {meta_high.layer_height_mm}，"
        f"实际: {merged_meta.layer_height_mm}"
    )
    assert merged_meta.line_width_mm == meta_high.line_width_mm, (
        f"line_width_mm 应为高优先级值 {meta_high.line_width_mm}，"
        f"实际: {merged_meta.line_width_mm}"
    )
    assert merged_meta.max_color_layers == meta_high.max_color_layers, (
        f"max_color_layers 应为高优先级值 {meta_high.max_color_layers}，"
        f"实际: {merged_meta.max_color_layers}"
    )
    assert merged_meta.base_layers == meta_high.base_layers, (
        f"base_layers 应为高优先级值 {meta_high.base_layers}，"
        f"实际: {merged_meta.base_layers}"
    )
    assert merged_meta.base_channel_idx == meta_high.base_channel_idx, (
        f"base_channel_idx 应为高优先级值 {meta_high.base_channel_idx}，"
        f"实际: {merged_meta.base_channel_idx}"
    )
    assert merged_meta.layer_order == meta_high.layer_order, (
        f"layer_order 应为高优先级值 {meta_high.layer_order!r}，"
        f"实际: {merged_meta.layer_order!r}"
    )

# ---------------------------------------------------------------------------
# Feature: lut-palette-integration, Property 12: ColorRecipeLogger 使用调色板颜色名称
# **Validates: Requirements 5.1, 5.2**
# ---------------------------------------------------------------------------
@given(
    palette=st.lists(palette_entry_strategy, min_size=1, max_size=8),
    material_id_offset=st.integers(min_value=0, max_value=7),
)
@settings(max_examples=100)
def test_recipe_logger_uses_palette_names(palette, material_id_offset):
    """Property 12: 对于任意包含调色板元数据的 ColorRecipeLogger，
    _get_color_name(material_id) 返回的名称应等于调色板中对应索引的
    color 字段值，而非通过 RGB 推断的通用名称。
    """
    from utils.color_recipe_logger import ColorRecipeLogger

    # Clamp material_id to valid palette range
    material_id = material_id_offset % len(palette)

    metadata = LUTMetadata(palette=palette)

    # Create a minimal ColorRecipeLogger with metadata
    dummy_rgb = np.array([[0, 0, 0]] * max(8, len(palette)), dtype=np.uint8)
    dummy_stacks = np.array([[0, 0, 0, 0, 0]] * max(8, len(palette)), dtype=np.int32)

    logger = ColorRecipeLogger(
        lut_path="/tmp/test.npy",
        lut_rgb=dummy_rgb,
        ref_stacks=dummy_stacks,
        color_mode="4-Color",
        metadata=metadata,
    )

    result = logger._get_color_name(material_id)
    expected = palette[material_id].color
    assert result == expected, (
        f"material_id={material_id}: 期望 {expected!r}，实际 {result!r}"
    )
