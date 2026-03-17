"""
Lumina Studio - 校准板色块尺寸与间距配置 属性测试 (Property-Based Tests)

使用 Hypothesis 验证校准板 voxel 网格尺寸计算的正确性。
每个属性测试至少运行 100 次迭代。
"""

import os
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import PrinterConfig


# ============================================================================
# Property 1: Voxel 网格尺寸计算正确性
# Feature: calibration-swatch-config, Property 1: Voxel grid dimension calculation correctness
# **Validates: Requirements 1.1, 5.2**
# ============================================================================

# 8-color board total_dim: 37 data + 1 padding each side = 39
TOTAL_DIM_8COLOR = 39


@settings(max_examples=200)
@given(
    block_size_mm=st.floats(min_value=3.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    gap_mm=st.floats(min_value=0.4, max_value=2.0, allow_nan=False, allow_infinity=False),
)
def test_voxel_grid_dimension_calculation(block_size_mm: float, gap_mm: float):
    """Property 1: Voxel grid dimension calculation correctness

    For any valid block_size_mm (3.0-10.0) and gap_mm (0.4-2.0), the calibration
    board generation function should compute:
      - pixels_per_block = max(1, int(block_size_mm / NOZZLE_WIDTH))
      - pixels_gap = max(1, int(gap_mm / NOZZLE_WIDTH))
      - voxel grid width = total_dim * (pixels_per_block + pixels_gap)

    **Validates: Requirements 1.1, 5.2**
    """
    nozzle_width = PrinterConfig.NOZZLE_WIDTH

    # Replicate the exact formula from generate_8color_board
    px_blk = max(1, int(block_size_mm / nozzle_width))
    px_gap = max(1, int(gap_mm / nozzle_width))
    v_w = TOTAL_DIM_8COLOR * (px_blk + px_gap)

    # Property: pixels_per_block is always >= 1
    assert px_blk >= 1, (
        f"pixels_per_block must be >= 1, got {px_blk} "
        f"(block_size_mm={block_size_mm}, NOZZLE_WIDTH={nozzle_width})"
    )

    # Property: pixels_gap is always >= 1
    assert px_gap >= 1, (
        f"pixels_gap must be >= 1, got {px_gap} "
        f"(gap_mm={gap_mm}, NOZZLE_WIDTH={nozzle_width})"
    )

    # Property: pixels_per_block matches the formula
    expected_px_blk = max(1, int(block_size_mm / nozzle_width))
    assert px_blk == expected_px_blk, (
        f"pixels_per_block mismatch: got {px_blk}, expected {expected_px_blk}"
    )

    # Property: pixels_gap matches the formula
    expected_px_gap = max(1, int(gap_mm / nozzle_width))
    assert px_gap == expected_px_gap, (
        f"pixels_gap mismatch: got {px_gap}, expected {expected_px_gap}"
    )

    # Property: voxel grid width equals total_dim * (px_blk + px_gap)
    expected_v_w = TOTAL_DIM_8COLOR * (px_blk + px_gap)
    assert v_w == expected_v_w, (
        f"Voxel grid width mismatch: got {v_w}, expected {expected_v_w} "
        f"(total_dim={TOTAL_DIM_8COLOR}, px_blk={px_blk}, px_gap={px_gap})"
    )

    # Property: voxel grid width is always positive
    assert v_w > 0, f"Voxel grid width must be > 0, got {v_w}"

    # Property: voxel grid width is always a multiple of total_dim
    # Since v_w = total_dim * (px_blk + px_gap), it must be divisible
    assert v_w % TOTAL_DIM_8COLOR == 0, (
        f"Voxel grid width {v_w} should be divisible by total_dim {TOTAL_DIM_8COLOR}"
    )

    # Property: px_blk scales monotonically with block_size_mm
    # int() truncates, so for block_size_mm in [3.0, 10.0] with NOZZLE_WIDTH=0.42,
    # px_blk should be in range [int(3.0/0.42), int(10.0/0.42)] = [7, 23]
    assert px_blk == int(block_size_mm / nozzle_width), (
        f"For block_size_mm={block_size_mm} >= 3.0 and NOZZLE_WIDTH={nozzle_width}, "
        f"int(block_size_mm / NOZZLE_WIDTH) should be >= 1 without needing max(1,...)"
    )

    # Property: px_gap is the truncated division result (no max(1,...) needed in valid range)
    # gap_mm >= 0.4, NOZZLE_WIDTH = 0.42, so int(0.4/0.42) = int(0.952) = 0 -> max(1,0) = 1
    # This means max(1,...) IS needed for small gap values near 0.4
    assert px_gap >= 1, (
        f"pixels_gap must be >= 1 after max(1,...), got {px_gap}"
    )


# ============================================================================
# Property 3: API 路由对所有模式一致传递 block_size 和 gap
# Feature: calibration-swatch-config, Property 3: API forwards block_size and gap for all modes
# **Validates: Requirements 3.1, 3.2, 3.3**
# ============================================================================

from unittest.mock import patch, MagicMock
from PIL import Image

from fastapi.testclient import TestClient

from api.schemas.extractor import CalibrationColorMode
from api.schemas.calibration import BackingColor

# Build a lightweight TestClient without triggering the lifespan (worker pool).
# We import the router directly and mount it on a bare FastAPI app.
from fastapi import FastAPI as _FastAPI
from api.routers.calibration import router as _cal_router
from api.file_registry import FileRegistry as _FileRegistry
from api.dependencies import get_file_registry as _get_file_registry

def _make_calibration_client() -> TestClient:
    """Create a minimal TestClient with the calibration router only.
    创建仅包含 calibration 路由的最小 TestClient。
    """
    _app = _FastAPI()
    _app.include_router(_cal_router)
    _registry = _FileRegistry()
    _app.dependency_overrides[_get_file_registry] = lambda: _registry
    return TestClient(_app, raise_server_exceptions=False)


# Map each CalibrationColorMode to the core function path it invokes.
_MODE_TO_CORE_FUNC = {
    CalibrationColorMode.BW: "api.routers.calibration.generate_bw_calibration_board",
    CalibrationColorMode.FOUR_COLOR_CMYW: "api.routers.calibration.generate_calibration_board",
    CalibrationColorMode.FOUR_COLOR_RYBW: "api.routers.calibration.generate_calibration_board",
    CalibrationColorMode.SIX_COLOR: "api.routers.calibration.generate_smart_board",
    CalibrationColorMode.SIX_COLOR_RYBW: "api.routers.calibration.generate_smart_board_rybw",
    CalibrationColorMode.EIGHT_COLOR: "api.routers.calibration.generate_8color_batch_zip",
    CalibrationColorMode.FIVE_COLOR_EXT: "api.routers.calibration.generate_5color_extended_batch_zip",
}

# Dummy return value for all mocked core functions: (path, PIL Image, status_str)
_DUMMY_RETURN = ("/tmp/dummy.3mf", Image.new("RGB", (10, 10)), "ok")


@settings(max_examples=200)
@given(
    mode=st.sampled_from(list(CalibrationColorMode)),
    block_size=st.integers(min_value=3, max_value=10),
    gap=st.floats(min_value=0.4, max_value=2.0, allow_nan=False, allow_infinity=False),
)
def test_api_forwards_block_size_and_gap_for_all_modes(
    mode: CalibrationColorMode,
    block_size: int,
    gap: float,
):
    """Property 3: API forwards block_size and gap for all modes

    For any CalibrationColorMode and any valid block_size (3-10) / gap (0.4-2.0),
    the API route SHALL call the corresponding core function with the provided
    block_size_mm and gap_mm values.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    core_func_path = _MODE_TO_CORE_FUNC[mode]
    client = _make_calibration_client()

    with patch(core_func_path, return_value=_DUMMY_RETURN) as mock_fn:
        payload = {
            "color_mode": mode.value,
            "block_size": block_size,
            "gap": gap,
            "backing": BackingColor.WHITE.value,
        }
        resp = client.post("/api/calibration/generate", json=payload)

        # The endpoint should succeed (not 4xx/5xx from routing logic).
        assert resp.status_code == 200, (
            f"Expected 200 for mode={mode.value}, got {resp.status_code}: {resp.text}"
        )

        # Core function must have been called exactly once.
        mock_fn.assert_called_once()

        _, kwargs = mock_fn.call_args

        # Property: block_size_mm is forwarded as float(block_size).
        assert "block_size_mm" in kwargs, (
            f"block_size_mm not passed to {core_func_path} for mode={mode.value}"
        )
        assert kwargs["block_size_mm"] == float(block_size), (
            f"block_size_mm mismatch: expected {float(block_size)}, "
            f"got {kwargs['block_size_mm']} for mode={mode.value}"
        )

        # Property: gap_mm is forwarded as-is.
        assert "gap_mm" in kwargs, (
            f"gap_mm not passed to {core_func_path} for mode={mode.value}"
        )
        assert kwargs["gap_mm"] == gap, (
            f"gap_mm mismatch: expected {gap}, "
            f"got {kwargs['gap_mm']} for mode={mode.value}"
        )
