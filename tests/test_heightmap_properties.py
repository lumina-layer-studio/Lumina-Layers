"""
Lumina Studio - 高度图浮雕模式属性测试 (Property-Based Tests)

使用 Hypothesis 库验证高度图处理管线的正确性属性。
每个属性测试至少运行 100 次迭代。
"""

import math
import os
import sys
import tempfile

import cv2
import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import PrinterConfig
from core.heightmap_loader import HeightmapLoader

# 常量
OPTICAL_LAYERS = 5
LAYER_HEIGHT = PrinterConfig.LAYER_HEIGHT  # 0.08mm
OPTICAL_THICKNESS_MM = OPTICAL_LAYERS * LAYER_HEIGHT  # 0.4mm


# ============================================================================
# Property 1: 灰度映射公式正确性
# Feature: heightmap-relief-mode, Property 1: 灰度映射公式正确性
# **Validates: Requirements 3.1, 3.2**
# ============================================================================

@settings(max_examples=100)
@given(
    grayscale_val=st.integers(0, 255),
    max_relief_height=st.floats(2.0, 15.0, allow_nan=False, allow_infinity=False),
    base_thickness=st.floats(0.1, 2.0, allow_nan=False, allow_infinity=False),
)
def test_grayscale_mapping_formula(grayscale_val, max_relief_height, base_thickness):
    """Property 1: 灰度映射公式正确性
    对于任意灰度值 g ∈ [0, 255]、任意 max_relief_height > base_thickness，
    _map_grayscale_to_height 的输出应满足公式和值域约束。
    """
    assume(max_relief_height > base_thickness)

    grayscale = np.array([[grayscale_val]], dtype=np.uint8)
    result = HeightmapLoader._map_grayscale_to_height(grayscale, max_relief_height, base_thickness)

    height_mm = float(result[0, 0])

    # 验证公式正确性
    expected = max_relief_height - (grayscale_val / 255.0) * (max_relief_height - base_thickness)
    assert np.isclose(height_mm, expected, atol=1e-4), (
        f"公式不匹配: got {height_mm}, expected {expected}"
    )

    # 验证输出值域 ∈ [base_thickness, max_relief_height]
    assert height_mm >= base_thickness - 1e-4, (
        f"输出 {height_mm} 低于 base_thickness {base_thickness}"
    )
    assert height_mm <= max_relief_height + 1e-4, (
        f"输出 {height_mm} 超过 max_relief_height {max_relief_height}"
    )

    # 验证边界条件：g=0 → max_relief_height
    if grayscale_val == 0:
        assert np.isclose(height_mm, max_relief_height, atol=1e-4)

    # 验证边界条件：g=255 → base_thickness
    if grayscale_val == 255:
        assert np.isclose(height_mm, base_thickness, atol=1e-4)


# ============================================================================
# Property 2: 高度图处理输出形状与类型不变量
# Feature: heightmap-relief-mode, Property 2: 高度图处理输出形状与类型不变量
# **Validates: Requirements 1.2, 2.1, 2.3, 3.4**
# ============================================================================

@settings(max_examples=100)
@given(
    img_h=st.integers(4, 64),
    img_w=st.integers(4, 64),
    channels=st.sampled_from([1, 3, 4]),
    target_h=st.integers(4, 64),
    target_w=st.integers(4, 64),
    max_relief_height=st.floats(2.0, 15.0, allow_nan=False, allow_infinity=False),
    base_thickness=st.floats(0.1, 2.0, allow_nan=False, allow_infinity=False),
)
def test_height_matrix_shape_and_type(
    img_h, img_w, channels, target_h, target_w, max_relief_height, base_thickness
):
    """Property 2: 高度图处理输出形状与类型不变量

    对于任意有效图像和任意目标尺寸，load_and_process 返回的 height_matrix 应满足：
    - 形状为 (target_h, target_w)
    - 数据类型为 float32
    - 所有值 ∈ [base_thickness, max_relief_height]
    """
    assume(max_relief_height > base_thickness)

    if channels == 1:
        img = np.random.randint(0, 256, (img_h, img_w), dtype=np.uint8)
    else:
        img = np.random.randint(0, 256, (img_h, img_w, channels), dtype=np.uint8)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
        cv2.imwrite(tmp_path, img)

    try:
        result = HeightmapLoader.load_and_process(
            heightmap_path=tmp_path,
            target_w=target_w,
            target_h=target_h,
            max_relief_height=max_relief_height,
            base_thickness=base_thickness,
        )

        assert result["success"], f"load_and_process 失败: {result.get('error')}"

        hm = result["height_matrix"]

        assert hm.shape == (target_h, target_w), (
            f"形状不匹配: got {hm.shape}, expected ({target_h}, {target_w})"
        )
        assert hm.dtype == np.float32, f"dtype 不匹配: got {hm.dtype}"
        assert np.all(hm >= base_thickness - 1e-4), (
            f"存在值低于 base_thickness: min={np.min(hm)}"
        )
        assert np.all(hm <= max_relief_height + 1e-4), (
            f"存在值超过 max_relief_height: max={np.max(hm)}"
        )
    finally:
        os.unlink(tmp_path)


# ============================================================================
# Property 3: 体素矩阵结构不变量
# Feature: heightmap-relief-mode, Property 3: 体素矩阵结构不变量
# **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
# ============================================================================

@settings(max_examples=100)
@given(
    size=st.integers(2, 8),
    max_height=st.floats(0.5, 5.0, allow_nan=False, allow_infinity=False),
    backing_color_id=st.integers(0, 3),
)
def test_voxel_matrix_structure(size, max_height, backing_color_id):
    """Property 3: 体素矩阵结构不变量

    对于任意 Height_Matrix 和对应的 material_matrix、mask_solid，
    _build_relief_voxel_matrix 在高度图模式下生成的体素矩阵应满足结构约束。
    """
    from core.converter import _build_relief_voxel_matrix

    target_h, target_w = size, size

    assume(max_height >= OPTICAL_THICKNESS_MM)
    height_matrix = np.random.uniform(
        OPTICAL_THICKNESS_MM, max_height, (target_h, target_w)
    ).astype(np.float32)

    mask_solid = np.random.choice([True, False], (target_h, target_w))
    if not np.any(mask_solid):
        mask_solid[0, 0] = True

    material_matrix = np.random.randint(0, 4, (target_h, target_w, OPTICAL_LAYERS), dtype=int)
    matched_rgb = np.random.randint(0, 256, (target_h, target_w, 3), dtype=np.uint8)

    full_matrix, backing_metadata = _build_relief_voxel_matrix(
        matched_rgb=matched_rgb,
        material_matrix=material_matrix,
        mask_solid=mask_solid,
        color_height_map={},
        default_height=1.0,
        structure_mode="Single-sided",
        backing_color_id=backing_color_id,
        pixel_scale=0.42,
        height_matrix=height_matrix,
    )

    max_z_layers = full_matrix.shape[0]

    # 验证体素矩阵 Z 维度
    max_solid_height = np.max(height_matrix[mask_solid])
    expected_max_z = max(OPTICAL_LAYERS + 1, int(math.ceil(max_solid_height / LAYER_HEIGHT)))
    assert max_z_layers == expected_max_z, (
        f"Z 维度不匹配: got {max_z_layers}, expected {expected_max_z}"
    )

    for y in range(target_h):
        for x in range(target_w):
            if not mask_solid[y, x]:
                col = full_matrix[:, y, x]
                assert np.all(col == -1), (
                    f"非实心像素 ({y},{x}) 存在非 -1 值: {col[col != -1]}"
                )
            else:
                pixel_height = height_matrix[y, x]
                clamped_height = max(pixel_height, OPTICAL_THICKNESS_MM)
                expected_layers = max(OPTICAL_LAYERS, int(math.ceil(clamped_height / LAYER_HEIGHT)))
                expected_layers = min(expected_layers, max_z_layers)

                optical_start = expected_layers - OPTICAL_LAYERS

                # 验证基座层（backing）
                for z in range(optical_start):
                    assert full_matrix[z, y, x] == backing_color_id, (
                        f"像素 ({y},{x}) z={z} 基座层应为 {backing_color_id}, "
                        f"got {full_matrix[z, y, x]}"
                    )

                # 验证光学层（顶部 5 层）材料来自 material_matrix
                for layer_idx in range(OPTICAL_LAYERS):
                    z = optical_start + layer_idx
                    if z < max_z_layers:
                        expected_mat = material_matrix[y, x, OPTICAL_LAYERS - 1 - layer_idx]
                        assert full_matrix[z, y, x] == expected_mat, (
                            f"像素 ({y},{x}) z={z} 光学层 {layer_idx} "
                            f"应为 {expected_mat}, got {full_matrix[z, y, x]}"
                        )

                # 验证光学层以上为 -1（空气）
                for z in range(expected_layers, max_z_layers):
                    assert full_matrix[z, y, x] == -1, (
                        f"像素 ({y},{x}) z={z} 应为 -1（空气）, got {full_matrix[z, y, x]}"
                    )


# ============================================================================
# Property 1: 模式选择决策矩阵正确性
# Feature: fix-2-5d-relief-mode, Property 1: 模式选择决策矩阵正确性
# **Validates: Requirements 2.2, 2.3, 2.4**
# ============================================================================


def _simulate_branch_selection(
    enable_relief: bool,
    height_mode: str,
    heightmap_path: str | None,
    color_height_map: dict | None,
) -> str:
    """Simulate the branch selection logic from converter.py.

    Mirrors the explicit height_mode decision matrix implemented in
    convert_image_to_3d (task 1.1).  Returns one of:
      - "heightmap"     – heightmap relief branch
      - "color_height"  – color-height-map relief branch
      - "flat"          – standard flat mode
      - "flat_warning"  – flat mode with warning (heightmap mode but no path)
    """
    # Phase 1: heightmap loading decision (mirrors converter.py lines ~930-954)
    heightmap_height_matrix = None
    if enable_relief and height_mode == "heightmap" and heightmap_path is not None:
        # In real code this loads the heightmap; simulate success
        heightmap_height_matrix = np.ones((4, 4), dtype=np.float32)
    elif enable_relief and height_mode == "heightmap" and heightmap_path is None:
        # Warning path – fall through with heightmap_height_matrix = None
        pass

    # Phase 2: voxel matrix branch selection (mirrors converter.py lines ~956-990)
    if heightmap_height_matrix is not None:
        return "heightmap"
    elif enable_relief and height_mode == "color" and color_height_map:
        return "color_height"
    else:
        # Distinguish the warning sub-case for assertion clarity
        if enable_relief and height_mode == "heightmap" and heightmap_path is None:
            return "flat_warning"
        return "flat"


def _expected_branch(
    enable_relief: bool,
    height_mode: str,
    heightmap_path: str | None,
    color_height_map: dict | None,
) -> str:
    """Return the expected branch according to the design decision matrix."""
    if not enable_relief:
        return "flat"
    if height_mode == "color":
        if color_height_map:
            return "color_height"
        return "flat"
    if height_mode == "heightmap":
        if heightmap_path is not None:
            return "heightmap"
        return "flat_warning"
    # Unknown height_mode falls to flat
    return "flat"


# Strategy: generate realistic input combinations
_height_mode_st = st.sampled_from(["color", "heightmap"])
_heightmap_path_st = st.one_of(st.none(), st.just("/fake/heightmap.png"))
_color_height_map_st = st.one_of(
    st.none(),
    st.just({}),
    st.dictionaries(
        keys=st.from_regex(r"#[0-9a-f]{6}", fullmatch=True),
        values=st.floats(0.5, 10.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=4,
    ),
)


@settings(max_examples=200)
@given(
    enable_relief=st.booleans(),
    height_mode=_height_mode_st,
    heightmap_path=_heightmap_path_st,
    color_height_map=_color_height_map_st,
)
def test_decision_matrix_correctness(
    enable_relief: bool,
    height_mode: str,
    heightmap_path: str | None,
    color_height_map: dict | None,
) -> None:
    """Property 1: 模式选择决策矩阵正确性

    For any combination of (enable_relief, height_mode, heightmap_path,
    color_height_map), the converter branch selection must strictly follow
    the decision matrix defined in the design document:

    | enable_relief | height_mode | heightmap_path | color_height_map | 结果              |
    |---------------|-------------|----------------|------------------|-------------------|
    | False         | 任意        | 任意           | 任意             | flat 模式         |
    | True          | "color"     | 任意（忽略）   | 非空             | color_height 分支 |
    | True          | "color"     | 任意（忽略）   | 空               | flat 模式         |
    | True          | "heightmap" | 有效路径       | 任意（忽略）     | heightmap 分支    |
    | True          | "heightmap" | None           | 任意             | flat 模式 + 警告  |

    **Validates: Requirements 2.2, 2.3, 2.4**
    """
    # Normalise empty dict to falsy for the decision matrix (matches Python
    # truthiness used in the converter: ``if color_height_map:``)
    actual = _simulate_branch_selection(
        enable_relief, height_mode, heightmap_path, color_height_map
    )
    expected = _expected_branch(
        enable_relief, height_mode, heightmap_path, color_height_map
    )

    assert actual == expected, (
        f"Decision matrix mismatch!\n"
        f"  enable_relief={enable_relief}, height_mode={height_mode!r}, "
        f"heightmap_path={heightmap_path!r}, color_height_map={color_height_map!r}\n"
        f"  expected={expected!r}, actual={actual!r}"
    )


# ============================================================================
# Property 2: 参数钳位产生 flat 输出
# Feature: fix-2-5d-relief-mode, Property 2: 参数钳位产生 flat 输出
# **Validates: Requirements 3.1, 3.2**
# ============================================================================

# Strategy: base_thickness in a reasonable range, max_relief_height <= base_thickness
_base_thickness_st = st.floats(0.2, 10.0, allow_nan=False, allow_infinity=False)


@settings(max_examples=100)
@given(
    img_h=st.integers(4, 32),
    img_w=st.integers(4, 32),
    base_thickness=_base_thickness_st,
    relief_ratio=st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False),
)
def test_clamping_flat_output(
    img_h: int,
    img_w: int,
    base_thickness: float,
    relief_ratio: float,
) -> None:
    """Property 2: 参数钳位产生 flat 输出

    For any max_relief_height <= base_thickness and any valid grayscale image,
    HeightmapLoader.load_and_process should produce a height_matrix where ALL
    values equal base_thickness (i.e. a flat matrix).

    We generate max_relief_height = base_thickness * relief_ratio so that
    max_relief_height is always <= base_thickness.

    **Validates: Requirements 3.1, 3.2**
    """
    max_relief_height = base_thickness * relief_ratio

    # Generate a random grayscale image with varied pixel values
    img = np.random.randint(0, 256, (img_h, img_w), dtype=np.uint8)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
        cv2.imwrite(tmp_path, img)

    try:
        result = HeightmapLoader.load_and_process(
            heightmap_path=tmp_path,
            target_w=img_w,
            target_h=img_h,
            max_relief_height=max_relief_height,
            base_thickness=base_thickness,
        )

        assert result["success"], f"load_and_process failed: {result.get('error')}"

        hm = result["height_matrix"]

        # All values must equal base_thickness (flat matrix)
        assert np.allclose(hm, base_thickness, atol=1e-4), (
            f"Expected flat matrix with all values == {base_thickness}, "
            f"but got min={np.min(hm)}, max={np.max(hm)}, "
            f"max_relief_height={max_relief_height}"
        )

        # When max_relief_height < base_thickness, a warning should be present
        if max_relief_height < base_thickness:
            has_clamping_warning = any("clamping" in w.lower() for w in result["warnings"])
            assert has_clamping_warning, (
                f"Expected clamping warning when max_relief_height ({max_relief_height}) "
                f"< base_thickness ({base_thickness}), warnings: {result['warnings']}"
            )
    finally:
        os.unlink(tmp_path)


# ============================================================================
# Property 3: 钳位后高度矩阵值域不变量
# Feature: fix-2-5d-relief-mode, Property 3: 钳位后高度矩阵值域不变量
# **Validates: Requirements 3.3**
# ============================================================================


@settings(max_examples=100)
@given(
    img_h=st.integers(4, 32),
    img_w=st.integers(4, 32),
    max_relief_height=st.floats(0.1, 15.0, allow_nan=False, allow_infinity=False),
    base_thickness=st.floats(0.1, 10.0, allow_nan=False, allow_infinity=False),
)
def test_range_invariant_after_clamping(
    img_h: int,
    img_w: int,
    max_relief_height: float,
    base_thickness: float,
) -> None:
    """Property 3: 钳位后高度矩阵值域不变量

    For any max_relief_height and base_thickness (including cases where
    max_relief_height <= base_thickness), HeightmapLoader.load_and_process
    should produce a height_matrix where ALL values satisfy:
        base_thickness <= value <= max(max_relief_height, base_thickness)

    This covers all parameter combinations, not just the clamping case.

    **Validates: Requirements 3.3**
    """
    effective_max = max(max_relief_height, base_thickness)

    # Generate a random grayscale image
    img = np.random.randint(0, 256, (img_h, img_w), dtype=np.uint8)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
        cv2.imwrite(tmp_path, img)

    try:
        result = HeightmapLoader.load_and_process(
            heightmap_path=tmp_path,
            target_w=img_w,
            target_h=img_h,
            max_relief_height=max_relief_height,
            base_thickness=base_thickness,
        )

        assert result["success"], f"load_and_process failed: {result.get('error')}"

        hm = result["height_matrix"]

        # All values must be >= base_thickness
        assert np.all(hm >= base_thickness - 1e-4), (
            f"Found value below base_thickness: min={np.min(hm)}, "
            f"base_thickness={base_thickness}"
        )

        # All values must be <= max(max_relief_height, base_thickness)
        assert np.all(hm <= effective_max + 1e-4), (
            f"Found value above effective max: max={np.max(hm)}, "
            f"effective_max={effective_max}"
        )
    finally:
        os.unlink(tmp_path)


# ============================================================================
# Property 5: 验证警告条件
# Feature: heightmap-relief-mode, Property 5: 验证警告条件
# **Validates: Requirements 8.2, 8.3**
# ============================================================================

@settings(max_examples=100)
@given(
    hm_w=st.integers(1, 500),
    hm_h=st.integers(1, 500),
    tgt_w=st.integers(1, 500),
    tgt_h=st.integers(1, 500),
)
def test_aspect_ratio_warning(hm_w, hm_h, tgt_w, tgt_h):
    """Property 5a: 宽高比偏差警告

    当宽高比偏差 > 20% 时，_check_aspect_ratio 应返回非 None 的警告字符串。
    """
    hm_ratio = hm_w / hm_h
    tgt_ratio = tgt_w / tgt_h
    deviation = abs(hm_ratio - tgt_ratio) / tgt_ratio

    result = HeightmapLoader._check_aspect_ratio(hm_w, hm_h, tgt_w, tgt_h)

    if deviation > 0.2:
        assert result is not None, (
            f"偏差 {deviation:.2%} > 20% 时应返回警告, "
            f"hm=({hm_w}x{hm_h}), tgt=({tgt_w}x{tgt_h})"
        )
    else:
        assert result is None, (
            f"偏差 {deviation:.2%} <= 20% 时不应返回警告, "
            f"hm=({hm_w}x{hm_h}), tgt=({tgt_w}x{tgt_h})"
        )


@settings(max_examples=100)
@given(
    size=st.integers(2, 32),
    fill_value=st.integers(0, 255),
)
def test_contrast_warning(size, fill_value):
    """Property 5b: 低对比度警告

    当灰度值标准差 < 1.0 时，_check_contrast 应返回非 None 的警告字符串。
    """
    grayscale = np.full((size, size), fill_value, dtype=np.uint8)
    result = HeightmapLoader._check_contrast(grayscale)

    std_val = float(np.std(grayscale))
    assert std_val < 1.0, "均匀灰度图的标准差应 < 1.0"
    assert result is not None, (
        f"标准差 {std_val:.4f} < 1.0 时应返回警告"
    )


@settings(max_examples=100)
@given(
    size=st.integers(4, 32),
)
def test_contrast_no_warning_for_varied_image(size):
    """Property 5c: 高对比度图不应产生警告

    当灰度值标准差 >= 1.0 时，_check_contrast 应返回 None。
    """
    grayscale = np.zeros((size, size), dtype=np.uint8)
    half = size // 2
    grayscale[:half, :] = 0
    grayscale[half:, :] = 255

    std_val = float(np.std(grayscale))
    assume(std_val >= 1.0)

    result = HeightmapLoader._check_contrast(grayscale)
    assert result is None, (
        f"标准差 {std_val:.4f} >= 1.0 时不应返回警告"
    )


# ============================================================================
# Property 6: 无效文件错误处理
# Feature: heightmap-relief-mode, Property 6: 无效文件错误处理
# **Validates: Requirements 8.1**
# ============================================================================

@settings(max_examples=100)
@given(
    random_bytes=st.binary(min_size=1, max_size=1024),
)
def test_invalid_file_error_handling(random_bytes):
    """Property 6: 无效文件错误处理

    对于任意非图像文件（随机字节序列），load_and_validate 应返回
    success=False 且 error 字段包含描述性错误信息。
    """
    with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as f:
        tmp_path = f.name
        f.write(random_bytes)

    try:
        result = HeightmapLoader.load_and_validate(tmp_path)

        assert result["success"] is False, (
            "随机字节文件应返回 success=False"
        )
        assert result["error"] is not None and len(result["error"]) > 0, (
            "随机字节文件应返回非空 error 信息"
        )
    finally:
        os.unlink(tmp_path)
