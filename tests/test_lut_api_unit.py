"""Unit tests for LUT info and merge API endpoints.

Validates:
- GET /api/lut/{name}/info returns correct info or 404 (Requirement 6.7)
- POST /api/lut/merge returns 400 for invalid requests (Requirement 6.8)
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app

client: TestClient = TestClient(app)


# =========================================================================
# 1. GET /api/lut/{name}/info — success scenario (Requirement 6.7)
# =========================================================================


class TestLutInfoSuccess:
    """Verify the info endpoint returns correct mode and count."""

    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("8-Color", 2738))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/path.npy")
    def test_info_returns_200_with_correct_fields(
        self, mock_path, mock_detect
    ) -> None:
        response = client.get("/api/lut/TestLUT/info")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "TestLUT"
        assert data["color_mode"] == "8-Color"
        assert data["color_count"] == 2738


# =========================================================================
# 2. GET /api/lut/{name}/info — 404 scenario (Requirement 6.7)
# =========================================================================


class TestLutInfoNotFound:
    """Verify the info endpoint returns 404 for non-existent LUT."""

    @patch("api.routers.lut.LUTManager.get_lut_path", return_value=None)
    def test_info_returns_404_when_lut_not_found(self, mock_path) -> None:
        response = client.get("/api/lut/NonExistent/info")
        assert response.status_code == 404
        assert "LUT not found" in response.json()["detail"]


# =========================================================================
# 3. POST /api/lut/merge — empty secondary list (Requirement 6.8)
# =========================================================================


class TestMergeEmptySecondary:
    """Verify merge returns 400 when secondary_names is empty."""

    def test_merge_empty_secondary_returns_400(self) -> None:
        payload = {
            "primary_name": "SomeLUT",
            "secondary_names": [],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "At least one secondary LUT" in response.json()["detail"]


# =========================================================================
# 4. POST /api/lut/merge — Primary mode not 6/8-Color (Requirement 6.8)
# =========================================================================


class TestMergePrimaryModeInvalid:
    """Verify merge returns 400 when primary LUT is not 6-Color or 8-Color."""

    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("4-Color", 1024))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/primary.npy")
    def test_merge_4color_primary_returns_400(self, mock_path, mock_detect) -> None:
        payload = {
            "primary_name": "FourColorLUT",
            "secondary_names": ["SecondaryLUT"],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "Primary LUT must be 6-Color or 8-Color" in response.json()["detail"]


# =========================================================================
# 5. POST /api/lut/merge — compatibility failure (Requirement 6.8)
# =========================================================================


class TestMergeCompatibilityFailure:
    """Verify merge returns 400 when LUT modes are incompatible."""

    @patch(
        "api.routers.lut.LUTMerger.validate_compatibility",
        return_value=(False, "Incompatible color modes"),
    )
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_merge_incompatible_modes_returns_400(
        self, mock_path, mock_detect, mock_load, mock_validate
    ) -> None:
        import numpy as np

        # get_lut_path returns a path for both primary and secondary
        mock_path.side_effect = ["/fake/primary.npy", "/fake/secondary.npy"]
        # detect_color_mode: primary is 8-Color, secondary is 8-Color (incompatible)
        mock_detect.side_effect = [("8-Color", 2738), ("8-Color", 2738)]
        # load_lut_with_stacks returns dummy data
        dummy_rgb = np.zeros((10, 3), dtype=np.uint8)
        dummy_stacks = np.zeros((10, 5), dtype=np.int32)
        mock_load.return_value = (dummy_rgb, dummy_stacks)

        payload = {
            "primary_name": "PrimaryLUT",
            "secondary_names": ["SecondaryLUT"],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "Incompatible" in response.json()["detail"]
