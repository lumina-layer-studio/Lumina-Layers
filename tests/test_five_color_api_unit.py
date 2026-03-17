"""Unit tests for the Five-Color Query API endpoints.
五色组合查询 API 端点的单元测试。

Tests cover:
- NPZ file loading returns correct base colors (Req 1.2)
- NPY file loading returns correct base colors (Req 1.3)
- Non-existent LUT returns 404 (Req 1.4)
- Successful query returns correct result (Req 2.1)
- Query with no match returns found=false (Req 2.4)
"""

from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routers.five_color import _engine_cache

client = TestClient(create_app())


@pytest.fixture(autouse=True)
def _clear_engine_cache():
    """Clear the five-color engine cache before each test."""
    _engine_cache.clear()
    yield
    _engine_cache.clear()

# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _make_npz_data():
    """Create synthetic NPZ-style stack_lut and rgb_data arrays."""
    stack_lut = np.array(
        [[0, 1, 2, 3, 4], [1, 2, 3, 4, 0], [0, 0, 0, 0, 0]],
        dtype=np.int64,
    )
    rgb_data = np.array(
        [[255, 128, 64], [100, 200, 50], [10, 20, 30]],
        dtype=np.int64,
    )
    return stack_lut, rgb_data


# ---------------------------------------------------------------------------
# GET /api/five-color/base-colors
# ---------------------------------------------------------------------------

def test_get_base_colors_npz():
    """NPZ file loading returns correct base colors."""
    stack_lut, rgb_data = _make_npz_data()

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npz",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_npz_file",
            return_value=(True, "ok", stack_lut, rgb_data),
        ),
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "test_lut"})

    assert resp.status_code == 200
    body = resp.json()
    # ColorQueryEngine infers color_count from max(stack_lut)+1 = 5
    assert body["color_count"] == 5
    assert len(body["colors"]) == 5

    first = body["colors"][0]
    assert first["index"] == 0
    assert first["rgb"] == [255, 128, 64]
    assert first["hex"] == "#FF8040"


def test_get_base_colors_npy():
    """NPY file loading returns correct base colors."""
    rgb_data = np.array(
        [[200, 50, 50], [50, 200, 50], [50, 50, 200], [240, 240, 240]] * 256,
        dtype=np.uint8,
    )  # 1024 rows → detected as 4-color

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npy",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_lut_rgb",
            return_value=(True, "ok", rgb_data),
        ),
        patch(
            "api.routers.five_color.ColorCountDetector.detect_color_count",
            return_value=(4, 1024),
        ),
        patch(
            "api.routers.five_color.StackFileManager.find_stack_file",
            return_value=None,
        ),
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "test_lut"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["color_count"] == 4
    assert len(body["colors"]) == 4


def test_get_base_colors_not_found():
    """Non-existent LUT returns 404."""
    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=None,
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "nonexistent"})

    assert resp.status_code == 404
    assert "LUT not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/five-color/query
# ---------------------------------------------------------------------------

def test_query_success():
    """Successful query returns correct RGB and hex."""
    stack_lut, rgb_data = _make_npz_data()

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npz",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_npz_file",
            return_value=(True, "ok", stack_lut, rgb_data),
        ),
    ):
        resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [0, 1, 2, 3, 4]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["result_rgb"] == [255, 128, 64]
    assert body["result_hex"] == "#FF8040"


def test_query_no_match():
    """Query with non-matching indices returns found=false."""
    stack_lut, rgb_data = _make_npz_data()

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npz",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_npz_file",
            return_value=(True, "ok", stack_lut, rgb_data),
        ),
    ):
        resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [4, 4, 4, 4, 4]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
