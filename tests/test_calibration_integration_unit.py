"""Unit tests for Calibration endpoint integration.

Validates:
- 4 color_mode routing dispatches to correct core functions (Requirement 3.1-3.4)
- Parameter mapping from Pydantic fields to core function args (Requirement 3.5)
- Core exception returns HTTP 500 (Requirement 3.6)
"""

from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app

client: TestClient = TestClient(app)

# Shared mock return value: (file_path, PIL preview image, status string)
_mock_preview: Image.Image = Image.fromarray(
    np.zeros((10, 10, 3), dtype=np.uint8)
)
_mock_return = ("/tmp/fake.3mf", _mock_preview, "OK")


# =========================================================================
# 1. Color mode routing - Requirement 3
# =========================================================================


class TestColorModeRouting:
    """Verify each color_mode dispatches to the correct core function."""

    def test_bw_mode_routes_to_generate_bw(self) -> None:
        with patch(
            "api.routers.calibration.generate_bw_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "BW (Black & White)",
                    "block_size": 5,
                    "gap": 0.82,
                    "backing": "White",
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once_with(
                block_size_mm=5.0,
                gap_mm=0.82,
                backing_color="White",
            )

    def test_four_color_mode_routes_to_generate_calibration_board(self) -> None:
        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color",
                    "block_size": 5,
                    "gap": 0.82,
                    "backing": "White",
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once_with(
                color_mode="RYBW",
                block_size_mm=5.0,
                gap_mm=0.82,
                backing_color="White",
            )

    def test_six_color_mode_routes_to_generate_smart_board(self) -> None:
        with patch(
            "api.routers.calibration.generate_smart_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "6-Color (Smart 1296)",
                    "block_size": 5,
                    "gap": 0.82,
                    "backing": "White",
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once_with(
                block_size_mm=5.0,
                gap_mm=0.82,
            )

    def test_eight_color_mode_routes_to_generate_8color_batch_zip(self) -> None:
        with patch(
            "api.routers.calibration.generate_8color_batch_zip",
            return_value=("/tmp/fake.zip", _mock_preview, "OK"),
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "8-Color Max",
                    "block_size": 5,
                    "gap": 0.82,
                    "backing": "White",
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once_with()


# =========================================================================
# 2. Parameter mapping - Requirement 3.5
# =========================================================================


class TestParameterMapping:
    """Verify Pydantic request fields map correctly to core function args."""

    def test_block_size_and_gap_mapped_correctly(self) -> None:
        with patch(
            "api.routers.calibration.generate_bw_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "BW (Black & White)",
                    "block_size": 8,
                    "gap": 1.5,
                    "backing": "Cyan",
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once_with(
                block_size_mm=8.0,
                gap_mm=1.5,
                backing_color="Cyan",
            )
            # Verify block_size is passed as float
            call_kwargs = mock_fn.call_args.kwargs
            assert isinstance(call_kwargs["block_size_mm"], float)


# =========================================================================
# 3. Error handling - Requirement 3.6
# =========================================================================


class TestErrorHandling:
    """Verify core exceptions are translated to HTTP 500 responses."""

    def test_core_exception_returns_500(self) -> None:
        with patch(
            "api.routers.calibration.generate_calibration_board",
            side_effect=RuntimeError("disk full"),
        ):
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color",
                    "block_size": 5,
                    "gap": 0.82,
                    "backing": "White",
                },
            )
            assert response.status_code == 500
            assert "disk full" in response.json()["detail"]
