"""Unit tests for Settings and Stats API endpoints.

Validates:
- GET /api/system/settings returns defaults when file missing (Requirement 5.1, 5.2)
- GET /api/system/settings returns correct data when file exists (Requirement 5.1)
- POST /api/system/settings writes successfully (Requirement 5.3)
- POST /api/system/settings returns 500 on I/O error (Requirement 5.5)
- GET /api/system/stats returns correct data (Requirement 6.1)
- GET /api/system/stats returns zeros when stats file missing (Requirement 6.2)
"""

import json
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from api.app import app

client: TestClient = TestClient(app)


# =========================================================================
# 1. GET /api/system/settings — Requirements 5.1, 5.2
# =========================================================================


class TestGetSettings:
    """Verify GET /api/system/settings returns correct data."""

    def test_get_settings_file_not_exists(self) -> None:
        """文件不存在时返回默认值。"""
        with patch("api.routers.system.SETTINGS_FILE") as mock_file:
            mock_file.exists.return_value = False
            response = client.get("/api/system/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        settings = data["settings"]
        assert settings["last_lut"] == ""
        assert settings["last_modeling_mode"] == "high-fidelity"
        assert settings["last_color_mode"] == "4-Color (RYBW)"
        assert settings["last_slicer"] == ""
        assert settings["palette_mode"] == "swatch"
        assert settings["enable_crop_modal"] is True

    def test_get_settings_file_exists(self) -> None:
        """文件存在时返回正确数据。"""
        custom_settings = {
            "last_lut": "MyLUT",
            "last_modeling_mode": "pixel",
            "last_color_mode": "6-Color",
            "last_slicer": "bambu",
            "palette_mode": "grid",
            "enable_crop_modal": False,
        }
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = json.dumps(custom_settings)

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.get("/api/system/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        settings = data["settings"]
        assert settings["last_lut"] == "MyLUT"
        assert settings["last_modeling_mode"] == "pixel"
        assert settings["last_color_mode"] == "6-Color"
        assert settings["last_slicer"] == "bambu"
        assert settings["palette_mode"] == "grid"
        assert settings["enable_crop_modal"] is False


# =========================================================================
# 2. POST /api/system/settings — Requirements 5.3, 5.5
# =========================================================================


class TestPostSettings:
    """Verify POST /api/system/settings writes and handles errors."""

    def test_post_settings_success(self) -> None:
        """写入成功返回 200。"""
        payload = {
            "last_lut": "TestLUT",
            "last_modeling_mode": "vector",
            "last_color_mode": "8-Color Max",
            "last_slicer": "orca",
            "palette_mode": "swatch",
            "enable_crop_modal": True,
        }
        mock_file = MagicMock()
        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.post("/api/system/settings", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == "Settings saved"
        mock_file.write_text.assert_called_once()

    def test_post_settings_io_error(self) -> None:
        """I/O 错误返回 500。"""
        payload = {
            "last_lut": "",
            "last_modeling_mode": "high-fidelity",
            "last_color_mode": "4-Color",
            "last_slicer": "",
            "palette_mode": "swatch",
            "enable_crop_modal": True,
        }
        mock_file = MagicMock()
        mock_file.write_text.side_effect = OSError("disk full")

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.post("/api/system/settings", json=payload)

        assert response.status_code == 500
        assert "Failed to save settings" in response.json()["detail"]


# =========================================================================
# 3. GET /api/system/stats — Requirements 6.1, 6.2
# =========================================================================


class TestGetStats:
    """Verify GET /api/system/stats returns correct data."""

    def test_get_stats_success(self) -> None:
        """Stats.get_all() 返回数据时正确映射。"""
        mock_data = {"calibrations": 10, "extractions": 5, "conversions": 20}
        with patch("utils.stats.Stats.get_all", return_value=mock_data):
            response = client.get("/api/system/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["calibrations"] == 10
        assert data["extractions"] == 5
        assert data["conversions"] == 20

    def test_get_stats_no_file(self) -> None:
        """统计文件不存在时返回零值。"""
        mock_data: dict = {"calibrations": 0, "extractions": 0, "conversions": 0}
        with patch("utils.stats.Stats.get_all", return_value=mock_data):
            response = client.get("/api/system/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["calibrations"] == 0
        assert data["extractions"] == 0
        assert data["conversions"] == 0
