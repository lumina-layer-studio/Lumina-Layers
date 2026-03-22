"""Unit tests for Extractor endpoint integration.

Validates:
- Corner points count validation returns 422 (Requirement 4.5)
- Session state persistence after extraction (Requirement 4.4)
- Field name mapping: distortion->barrel, vignette_correction->bright (Requirement 4.2)
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import session_store

client: TestClient = TestClient(app)

# Shared mock return value: (vis_img, preview_img, lut_path, status_msg)
_mock_vis: np.ndarray = np.zeros((10, 10, 3), dtype=np.uint8)
_mock_preview: np.ndarray = np.zeros((10, 10, 3), dtype=np.uint8)
_mock_return = (_mock_vis, _mock_preview, "/tmp/test.npy", "OK")


def _make_test_image_buf() -> io.BytesIO:
    """Create a minimal PNG image buffer for upload."""
    img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# =========================================================================
# 1. Corner points validation - Requirement 4.5
# =========================================================================


class TestCornerPointsValidation:
    """Verify corner_points count != 4 returns HTTP 422."""

    def test_extract_invalid_corner_points_count_returns_422(self) -> None:
        """Send corner_points with 3 points, expect 422."""
        buf = _make_test_image_buf()
        response = client.post(
            "/api/extractor/extract",
            files={"image": ("test.png", buf, "image/png")},
            data={
                "corner_points": json.dumps([[0, 0], [100, 0], [100, 100]]),
                "color_mode": "4-Color",
                "distortion": "0.0",
                "vignette_correction": "false",
            },
        )
        assert response.status_code == 422
        assert "4 points" in response.json()["detail"]


# =========================================================================
# 2. Session state persistence - Requirement 4.4
# =========================================================================


class TestSessionStatePersistence:
    """Verify extraction stores session state with lut_path and color_mode."""

    def test_extract_stores_session_state(self) -> None:
        """Mock run_extraction, verify session contains lut_path and color_mode."""
        buf = _make_test_image_buf()
        with patch(
            "api.routers.extractor.run_extraction",
            return_value=_mock_return,
        ):
            response = client.post(
                "/api/extractor/extract",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "corner_points": json.dumps([[0, 0], [100, 0], [100, 100], [0, 100]]),
                    "color_mode": "4-Color",
                    "distortion": "0.0",
                    "vignette_correction": "false",
                },
            )
        assert response.status_code == 200
        body = response.json()
        session_id: str = body["session_id"]
        assert session_id

        # Verify session data in store
        session_data = session_store.get(session_id)
        assert session_data is not None
        assert session_data["lut_path"] == "/tmp/test.npy"
        assert session_data["color_mode"] == "4-Color"


# =========================================================================
# 3. Field name mapping - Requirement 4.2
# =========================================================================


class TestFieldNameMapping:
    """Verify API field names map to core function parameter names."""

    def test_extract_field_name_mapping(self) -> None:
        """Verify distortion->barrel, vignette_correction->bright."""
        buf = _make_test_image_buf()
        with patch(
            "api.routers.extractor.run_extraction",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/extractor/extract",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "corner_points": json.dumps([[0, 0], [100, 0], [100, 100], [0, 100]]),
                    "color_mode": "4-Color",
                    "distortion": "0.1",
                    "vignette_correction": "true",
                },
            )
        assert response.status_code == 200
        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args.kwargs
        # distortion -> barrel
        assert call_kwargs["barrel"] == 0.1
        # vignette_correction -> bright
        assert call_kwargs["bright"] is True
