#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Property-based tests for NPY to JSON Migration.

Uses Hypothesis to verify correctness properties across arbitrary inputs.
Feature: npy-to-json-migration
"""

import os
import tempfile

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from config import LUTMetadata, PaletteEntry, ColorSystem


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

# LUTMetadata strategy（非空 palette，颜色名唯一）
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


# ---------------------------------------------------------------------------
# Strategies — RGB + Stacks 生成器
# ---------------------------------------------------------------------------

def _rgb_stacks_strategy(min_n=1, max_n=30):
    """Generate (rgb, stacks) with matching row count.
    RGB: (N, 3) uint8, values 0-255
    Stacks: (N, L) int32, L ∈ [0, 6], values 0-7
    """
    return st.integers(min_value=min_n, max_value=max_n).flatmap(
        lambda n: st.tuples(
            # RGB array (N, 3) uint8
            st.lists(
                st.tuples(
                    st.integers(0, 255),
                    st.integers(0, 255),
                    st.integers(0, 255),
                ),
                min_size=n,
                max_size=n,
            ).map(lambda rows: np.array(rows, dtype=np.uint8)),
            # Stacks array (N, L) int32, L ∈ [0, 6], values 0-7
            st.integers(min_value=0, max_value=6).flatmap(
                lambda cols: st.lists(
                    st.lists(
                        st.integers(0, 7),
                        min_size=cols,
                        max_size=cols,
                    ),
                    min_size=n,
                    max_size=n,
                ).map(lambda rows: np.array(rows, dtype=np.int32).reshape(n, cols))
            ),
        )
    )


# 组合 strategy: (rgb, stacks, metadata)
# 确保 stacks 值在 palette 索引范围内，且 palette 颜色名唯一
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
            st.integers(min_value=0, max_value=6).flatmap(
                lambda cols: st.lists(
                    st.lists(
                        st.integers(0, palette_size - 1),
                        min_size=cols,
                        max_size=cols,
                    ),
                    min_size=n,
                    max_size=n,
                ).map(lambda rows: np.array(rows, dtype=np.int32).reshape(n, cols))
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
# Feature: npy-to-json-migration, Property 1: Keyed JSON data roundtrip
# **Validates: Requirements 11.1, 11.3**
# ---------------------------------------------------------------------------
@given(data=_rgb_stacks_metadata)
@settings(max_examples=100, deadline=None)
def test_keyed_json_data_roundtrip(data):
    """Property 1: 对于所有有效 RGB 数组 (N, 3) uint8 和 stacks 数组 (N, L) int32，
    save_keyed_json() 后 load_lut_with_metadata() 加载，
    RGB 数组应逐元素相等，recipe 数组应逐元素相等。
    """
    from utils.lut_manager import LUTManager

    rgb, stacks, metadata = data

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_data_roundtrip.json")
        LUTManager.save_keyed_json(path, rgb, stacks, metadata)
        loaded_rgb, loaded_stacks, _ = LUTManager.load_lut_with_metadata(path)

    # RGB 应逐元素相等（save_keyed_json 存储原始 RGB 整数值）
    assert loaded_rgb.shape == rgb.shape, (
        f"RGB shape 不一致: {loaded_rgb.shape} != {rgb.shape}"
    )
    assert np.array_equal(loaded_rgb, rgb), (
        f"RGB 值不一致, 最大差异: {np.abs(loaded_rgb.astype(int) - rgb.astype(int)).max()}"
    )

    # Stacks/recipe 应逐元素相等
    assert loaded_stacks is not None, "stacks 不应为 None"
    assert loaded_stacks.shape == stacks.shape, (
        f"stacks shape 不一致: {loaded_stacks.shape} != {stacks.shape}"
    )
    assert np.array_equal(loaded_stacks, stacks), "stacks 值不一致"



# ---------------------------------------------------------------------------
# Feature: npy-to-json-migration, Property 2: Keyed JSON metadata roundtrip
# **Validates: Requirements 11.2**
# ---------------------------------------------------------------------------
@given(data=_rgb_stacks_metadata)
@settings(max_examples=100, deadline=None)
def test_keyed_json_metadata_roundtrip(data):
    """Property 2: 对于所有有效 LUTMetadata 对象（非空 palette + 合法打印参数），
    save 后 load 的 palette 条目数量和内容应一致，
    layer_height_mm、line_width_mm 等打印参数应相等。
    """
    from utils.lut_manager import LUTManager

    rgb, stacks, metadata = data

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_meta_roundtrip.json")
        LUTManager.save_keyed_json(path, rgb, stacks, metadata)
        _, _, loaded_metadata = LUTManager.load_lut_with_metadata(path)

    # Palette 条目数量一致
    assert len(loaded_metadata.palette) == len(metadata.palette), (
        f"palette 长度不一致: {len(loaded_metadata.palette)} != {len(metadata.palette)}"
    )

    # Palette 内容一致
    for i, (orig, rest) in enumerate(zip(metadata.palette, loaded_metadata.palette)):
        assert rest.color == orig.color, (
            f"palette[{i}].color 不一致: {rest.color!r} != {orig.color!r}"
        )
        assert rest.material == orig.material, (
            f"palette[{i}].material 不一致: {rest.material!r} != {orig.material!r}"
        )
        assert rest.hex_color == orig.hex_color, (
            f"palette[{i}].hex_color 不一致: {rest.hex_color!r} != {orig.hex_color!r}"
        )

    # 打印参数一致
    assert loaded_metadata.max_color_layers == metadata.max_color_layers, (
        f"max_color_layers 不一致: {loaded_metadata.max_color_layers} != {metadata.max_color_layers}"
    )
    assert loaded_metadata.layer_height_mm == metadata.layer_height_mm, (
        f"layer_height_mm 不一致: {loaded_metadata.layer_height_mm} != {metadata.layer_height_mm}"
    )
    assert loaded_metadata.line_width_mm == metadata.line_width_mm, (
        f"line_width_mm 不一致: {loaded_metadata.line_width_mm} != {metadata.line_width_mm}"
    )
    assert loaded_metadata.base_layers == metadata.base_layers, (
        f"base_layers 不一致: {loaded_metadata.base_layers} != {metadata.base_layers}"
    )
    assert loaded_metadata.base_channel_idx == metadata.base_channel_idx, (
        f"base_channel_idx 不一致: {loaded_metadata.base_channel_idx} != {metadata.base_channel_idx}"
    )
    assert loaded_metadata.layer_order == metadata.layer_order, (
        f"layer_order 不一致: {loaded_metadata.layer_order!r} != {metadata.layer_order!r}"
    )


# ---------------------------------------------------------------------------
# Feature: npy-to-json-migration, Property 3: Multi-format load equivalence
# **Validates: Requirements 3.1, 8.1**
# ---------------------------------------------------------------------------
@given(data=_rgb_stacks_strategy(min_n=1, max_n=30))
@settings(max_examples=100, deadline=None)
def test_multi_format_load_equivalence(data):
    """Property 3: 同一份数据分别保存为 .npy（np.save）和 .json（save_keyed_json），
    分别通过 load_lut_with_metadata() 加载，
    两者返回的 RGB 数组应逐元素相等。
    """
    from utils.lut_manager import LUTManager

    rgb, stacks = data

    # 为 .npy 保存需要的默认 metadata
    metadata = LUTManager.infer_default_metadata("test", "/tmp/test.json", len(rgb))

    with tempfile.TemporaryDirectory() as tmpdir:
        # 保存为 .npy
        npy_path = os.path.join(tmpdir, "test_equiv.npy")
        np.save(npy_path, rgb)

        # 保存为 .json
        json_path = os.path.join(tmpdir, "test_equiv.json")
        LUTManager.save_keyed_json(json_path, rgb, stacks, metadata)

        # 分别加载
        npy_rgb, _, _ = LUTManager.load_lut_with_metadata(npy_path)
        json_rgb, _, _ = LUTManager.load_lut_with_metadata(json_path)

    # 两者 RGB 应逐元素相等
    assert npy_rgb.shape == json_rgb.shape, (
        f"RGB shape 不一致: npy={npy_rgb.shape}, json={json_rgb.shape}"
    )
    assert np.array_equal(npy_rgb, json_rgb), (
        f"RGB 值不一致, 最大差异: {np.abs(npy_rgb.astype(int) - json_rgb.astype(int)).max()}"
    )


# ---------------------------------------------------------------------------
# Feature: npy-to-json-migration, Property 4: Metadata inference correctness
# **Validates: Requirements 2.2**
# ---------------------------------------------------------------------------

# 所有可测试的颜色模式及其对应的 display_name 和 ColorSystem 配置
_COLOR_MODE_CONFIGS = [
    ("BW (Black & White)", "/tmp/test_BW.npy", ColorSystem.BW),
    ("4-Color (RYBW)", "/tmp/test_4-Color_RYBW.npy", ColorSystem.RYBW),
    ("4-Color (CMYW)", "/tmp/test_4-Color_CMYW.npy", ColorSystem.CMYW),
    ("6-Color (Smart 1296)", "/tmp/test_6-Color.npy", ColorSystem.SIX_COLOR),
    ("5-Color Extended", "/tmp/test_5-Color.npy", ColorSystem.FIVE_COLOR_EXTENDED),
    ("8-Color Max", "/tmp/test_8-Color.npy", ColorSystem.EIGHT_COLOR),
    ("Merged", "/tmp/test_Merged.npz", ColorSystem.EIGHT_COLOR),
]


@given(
    mode_idx=st.integers(min_value=0, max_value=len(_COLOR_MODE_CONFIGS) - 1),
    color_count=st.integers(min_value=1, max_value=2000),
)
@settings(max_examples=100)
def test_metadata_inference_correctness(mode_idx, color_count):
    """Property 4: 对于所有有效 color_mode（从 ColorSystem 支持的模式集合中选取），
    infer_default_metadata() 返回的 palette 条目数量应等于该模式的 slots 数量，
    每个条目的 color 字段应与对应 slot 名称一致。
    """
    from utils.lut_manager import LUTManager

    display_name, file_path, expected_config = _COLOR_MODE_CONFIGS[mode_idx]
    expected_slots = expected_config["slots"]

    metadata = LUTManager.infer_default_metadata(
        display_name=display_name,
        file_path=file_path,
        color_count=color_count,
    )

    # Palette 条目数量应等于 slots 数量
    assert len(metadata.palette) == len(expected_slots), (
        f"模式 {display_name}: palette 长度 {len(metadata.palette)} != "
        f"slots 长度 {len(expected_slots)}"
    )

    # 每个条目的 color 字段应与对应 slot 名称一致
    actual_names = [e.color for e in metadata.palette]
    assert actual_names == expected_slots, (
        f"模式 {display_name}: palette 颜色名称 {actual_names} != "
        f"slots {expected_slots}"
    )
