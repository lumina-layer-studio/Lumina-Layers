"""Unit tests for Converter Preview endpoint integration.

Validates:
- LUT name resolution failure returns 404 (Requirement 5.4)
- Session contains preview_cache after successful preview (Requirement 5.2)
- Response includes palette and dimensions fields (Requirement 5.3)
- asyncio.TimeoutError returns HTTP 504 (Requirement 2.3)
- General exception returns HTTP 500 (Requirement 1.4)
"""

from __future__ import annotations

import io
import os
import pickle
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_session_store, get_file_registry, get_worker_pool
from api.session_store import SessionStore
from api.file_registry import FileRegistry
from api.worker_pool import WorkerPoolManager

# Isolated store/registry per test module to avoid cross-test pollution
_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()


# Mock WorkerPoolManager for dependency override
_mock_pool = MagicMock(spec=WorkerPoolManager)

def setup_module(module):
    """Re-apply dependency overrides before this module's tests run.
    在本模块测试运行前重新设置依赖覆盖，确保跨文件测试隔离。
    """
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry
    app.dependency_overrides[get_worker_pool] = lambda: _mock_pool


def teardown_module(module):
    """Remove this module's dependency overrides after all tests complete.
    本模块所有测试完成后移除依赖覆盖。
    """
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)
    app.dependency_overrides.pop(get_worker_pool, None)


# Apply overrides immediately for module-level client creation
setup_module(None)

client: TestClient = TestClient(app)

# Mock cache_data returned by generate_preview_cached
_mock_matched_rgb: np.ndarray = np.zeros((80, 120, 3), dtype=np.uint8)
_mock_matched_rgb[:40, :, :] = [255, 0, 0]   # top half red (50 rows * 120 cols = 4800 but we use 40 rows)
_mock_matched_rgb[40:, :, :] = [0, 255, 0]   # bottom half green

_mock_mask_solid: np.ndarray = np.ones((80, 120), dtype=bool)

_mock_quantized_image: np.ndarray = _mock_matched_rgb.copy()

_mock_palette: list[dict] = [
    {"hex": "#00ff00", "color": (0, 255, 0), "count": 4800, "percentage": 50.0},
    {"hex": "#ff0000", "color": (255, 0, 0), "count": 4800, "percentage": 50.0},
]
_mock_cache: dict = {
    "target_w": 120,
    "target_h": 80,
    "target_width_mm": 60.0,
    "color_palette": _mock_palette,
    "matched_rgb": _mock_matched_rgb,
    "mask_solid": _mock_mask_solid,
    "quantized_image": _mock_quantized_image,
}
_mock_preview_img: np.ndarray = np.zeros((80, 120, 3), dtype=np.uint8)


def _create_worker_result_files() -> dict:
    """Create temp files simulating worker_generate_preview output.
    创建模拟 worker_generate_preview 输出的临时文件。

    Returns:
        dict: Worker result dict with preview_png_path, cache_data_path, status_msg.
    """
    # Write preview PNG
    fd, png_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    Image.fromarray(_mock_preview_img).save(png_path)

    # Write cache pickle
    fd, cache_path = tempfile.mkstemp(suffix=".pkl")
    os.close(fd)
    with open(cache_path, "wb") as f:
        pickle.dump(_mock_cache, f)

    return {
        "status_msg": "Preview OK",
        "preview_png_path": png_path,
        "cache_data_path": cache_path,
    }


def _make_test_image_buf() -> io.BytesIO:
    """Create a minimal PNG image buffer for upload."""
    img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# =========================================================================
# 1. LUT name resolution failure returns 404 - Requirement 5.4
# =========================================================================


class TestLutNotFoundReturns404:
    """Verify unresolvable lut_name returns HTTP 404."""

    def test_preview_unknown_lut_returns_404(self) -> None:
        """Send a non-existent lut_name, expect 404."""
        buf = _make_test_image_buf()
        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value=None,
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "nonexistent_lut",
                    "color_mode": "4-Color",
                },
            )
        assert response.status_code == 404
        assert "LUT" in response.json()["detail"]


# =========================================================================
# 2. Session contains preview_cache - Requirement 5.2
# =========================================================================


class TestSessionContainsPreviewCache:
    """Verify session stores preview_cache after successful preview."""

    def test_preview_stores_cache_in_session(self) -> None:
        """Mock worker pool submit, verify session has preview_cache."""
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ), patch(
            "api.routers.converter.upload_to_tempfile",
            return_value="/tmp/uploaded.png",
        ), patch(
            "api.routers.converter.generate_segmented_glb",
            return_value=None,
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )
        assert response.status_code == 200
        body = response.json()
        session_id: str = body["session_id"]
        assert session_id

        session_data = _test_store.get(session_id)
        assert session_data is not None
        assert "preview_cache" in session_data
        # Verify cache_data was loaded from pickle (values match)
        loaded_cache = session_data["preview_cache"]
        assert loaded_cache["target_w"] == 120
        assert loaded_cache["target_h"] == 80


# =========================================================================
# 3. Response includes palette and dimensions - Requirement 5.3
# =========================================================================


class TestResponseContainsPaletteAndDimensions:
    """Verify response JSON includes palette and dimensions fields."""

    def test_preview_response_has_palette_and_dimensions(self) -> None:
        """Mock worker pool submit, verify palette and dimensions in response."""
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ), patch(
            "api.routers.converter.upload_to_tempfile",
            return_value="/tmp/uploaded.png",
        ), patch(
            "api.routers.converter.generate_segmented_glb",
            return_value=None,
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )
        assert response.status_code == 200
        body = response.json()

        # palette — new format with quantized_hex, matched_hex, pixel_count, percentage
        assert "palette" in body
        assert isinstance(body["palette"], list)
        assert len(body["palette"]) == 2
        hex_values = {e["matched_hex"] for e in body["palette"]}
        assert "#00ff00" in hex_values
        assert "#ff0000" in hex_values
        for entry in body["palette"]:
            assert "quantized_hex" in entry
            assert "matched_hex" in entry
            assert "pixel_count" in entry
            assert "percentage" in entry

        # preview_glb_url — None when generate_segmented_glb returns None
        assert "preview_glb_url" in body
        assert body["preview_glb_url"] is None

        # dimensions
        assert "dimensions" in body
        assert body["dimensions"]["width"] == 120
        assert body["dimensions"]["height"] == 80


# =========================================================================
# 4. Timeout returns HTTP 504 - Requirement 2.3
# =========================================================================


class TestTimeoutReturns504:
    """Verify asyncio.TimeoutError from pool.submit returns HTTP 504."""

    def test_preview_timeout_returns_504(self) -> None:
        """Simulate pool.submit raising TimeoutError, expect 504."""
        import asyncio

        buf = _make_test_image_buf()
        _mock_pool.submit = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ), patch(
            "api.routers.converter.upload_to_tempfile",
            return_value="/tmp/uploaded.png",
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )
        assert response.status_code == 504
        assert "timed out" in response.json()["detail"].lower()


# =========================================================================
# 5. General exception returns HTTP 500 - Requirement 1.4
# =========================================================================


class TestGeneralExceptionReturns500:
    """Verify general Exception from pool.submit returns HTTP 500."""

    def test_preview_exception_returns_500(self) -> None:
        """Simulate pool.submit raising RuntimeError, expect 500."""
        buf = _make_test_image_buf()
        _mock_pool.submit = AsyncMock(side_effect=RuntimeError("Worker crashed"))

        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ), patch(
            "api.routers.converter.upload_to_tempfile",
            return_value="/tmp/uploaded.png",
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )
        assert response.status_code == 500
        assert "Worker crashed" in response.json()["detail"]
