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
import logging
from pathlib import Path
import shutil
import sys
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.routers.system import SETTINGS_SAVE_FAILED_DETAIL

client: TestClient = TestClient(app)
UNTRUSTED_ORIGIN_HEADERS = {"Origin": "https://attacker.example"}
LOCAL_FRONTEND_ORIGIN_HEADERS = {"Origin": "http://localhost:5174"}


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event_name: str,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event_name
    ]

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
        assert settings["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"
        assert settings["build_plate_id"] == ""
        assert settings["build_plate_selections"] == {}
        assert settings["external_spool_selections"] == {}
        assert settings["nozzle_size"] == "0.4"
        assert settings["enable_wipe_tower_auto_placement"] is True
        assert settings["header_nav_alignment"] == "center"

    @pytest.mark.parametrize("legacy_env_value", ["", "1"])
    def test_get_settings_rejects_untrusted_origin(
        self,
        monkeypatch: pytest.MonkeyPatch,
        legacy_env_value: str,
    ) -> None:
        """拒绝外部网页读取持久设置，旧部署开关不能绕过限制。"""
        monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", legacy_env_value)
        mock_file = MagicMock()
        mock_file.exists.return_value = False

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.get(
                "/api/system/settings",
                headers=UNTRUSTED_ORIGIN_HEADERS,
            )

        assert response.status_code == 403
        mock_file.exists.assert_not_called()

    def test_get_settings_file_exists(self) -> None:
        """文件存在时返回正确数据。"""
        custom_settings = {
            "last_lut": "MyLUT",
            "last_modeling_mode": "pixel",
            "last_color_mode": "6-Color",
            "last_slicer": "bambu",
            "palette_mode": "grid",
            "enable_crop_modal": False,
            "device_profile_id": "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
            "build_plate_id": "smooth-high-temp-plate",
            "build_plate_selections": {
                "OrcaSlicer:bbl:bambu-lab-p1s": "smooth-high-temp-plate"
            },
            "nozzle_size": "0.2",
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
        assert settings["device_profile_id"] == "OrcaSlicer:bbl:bambu-lab-p1s:0.2"
        assert settings["build_plate_id"] == "smooth-high-temp-plate"
        assert settings["build_plate_selections"] == {
            "OrcaSlicer:bbl:bambu-lab-p1s": "smooth-high-temp-plate"
        }
        assert settings["nozzle_size"] == "0.2"

    def test_get_settings_allows_local_frontend_origin(self) -> None:
        """本地前端仍可读取设置。"""
        custom_settings = {
            "last_lut": "LocalLUT",
            "last_modeling_mode": "vector",
            "last_color_mode": "4-Color (RYBW)",
            "palette_mode": "swatch",
            "enable_crop_modal": True,
            "custom_slicer_path": "/Applications/Bambu Studio.app",
        }
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = json.dumps(custom_settings)

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.get(
                "/api/system/settings",
                headers=LOCAL_FRONTEND_ORIGIN_HEADERS,
            )

        assert response.status_code == 200
        assert response.json()["settings"]["last_lut"] == "LocalLUT"

    @pytest.mark.parametrize("raw_json", ["[]", "null", '"oops"', "123", "true", "1.5"])
    def test_get_settings_non_object_json_returns_defaults(self, raw_json: str) -> None:
        """合法 JSON 但顶层不是对象时返回默认值，不让设置 API 500。"""
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = raw_json
        client_no_raise = TestClient(app, raise_server_exceptions=False)

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client_no_raise.get("/api/system/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        settings = data["settings"]
        assert settings["last_lut"] == ""
        assert settings["last_modeling_mode"] == "high-fidelity"
        assert settings["last_color_mode"] == "4-Color (RYBW)"
        assert settings["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"

    def test_get_settings_read_error_returns_defaults_without_unhandled_exception(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """I/O read failures fall back to defaults without app-level 500."""
        mock_file = MagicMock()
        private_path = "/Users/min/private/user_settings.json"
        mock_file.exists.return_value = True
        mock_file.read_text.side_effect = OSError(
            f"permission denied: {private_path}"
        )
        client_no_raise = TestClient(app, raise_server_exceptions=False)
        system_logger = logging.getLogger("lumina.api.routers.system")
        app_logger = logging.getLogger("lumina.api.app")
        monkeypatch.setattr(system_logger, "propagate", False)
        monkeypatch.setattr(app_logger, "propagate", False)
        system_logger.addHandler(caplog.handler)
        app_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=system_logger.name)
        caplog.set_level(logging.WARNING, logger=app_logger.name)

        try:
            with patch("api.routers.system.SETTINGS_FILE", mock_file):
                response = client_no_raise.get("/api/system/settings")
        finally:
            system_logger.removeHandler(caplog.handler)
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        assert private_path not in response.text
        data = response.json()
        assert data["status"] == "success"
        settings = data["settings"]
        assert settings["last_lut"] == ""
        assert settings["last_modeling_mode"] == "high-fidelity"
        assert settings["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"
        records = _records_for_event(caplog, "system_settings_load_failed")
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert records[0].error_type == "OSError"
        assert records[0].settings_path == str(mock_file)
        assert private_path in records[0].error_message
        assert _records_for_event(caplog, "api_unhandled_exception") == []

    def test_get_settings_exists_error_returns_defaults(self) -> None:
        """Even checking for settings file presence is a recoverable read failure."""
        mock_file = MagicMock()
        private_path = "/Users/min/private/user_settings.json"
        mock_file.exists.side_effect = OSError(f"stat failed: {private_path}")
        client_no_raise = TestClient(app, raise_server_exceptions=False)

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client_no_raise.get("/api/system/settings")

        assert response.status_code == 200
        assert private_path not in response.text
        settings = response.json()["settings"]
        assert settings["last_lut"] == ""
        assert settings["last_modeling_mode"] == "high-fidelity"
        assert settings["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"


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
            "device_profile_id": "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
            "nozzle_size": "0.2",
            "enable_wipe_tower_auto_placement": False,
        }
        mock_file = MagicMock()
        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.post("/api/system/settings", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == "Settings saved"
        mock_file.write_text.assert_called_once()
        written = json.loads(mock_file.write_text.call_args.args[0])
        assert written["device_profile_id"] == "OrcaSlicer:bbl:bambu-lab-p1s:0.2"
        assert written["enable_wipe_tower_auto_placement"] is False

    @pytest.mark.parametrize("alignment", ["center", "left"])
    def test_post_then_get_round_trips_header_nav_alignment(
        self,
        tmp_path: Path,
        alignment: str,
    ) -> None:
        """Top navigation alignment survives a save and reload."""
        settings_file = tmp_path / "user_settings.json"

        with patch("api.routers.system.SETTINGS_FILE", settings_file):
            saved = client.post(
                "/api/system/settings",
                json={"header_nav_alignment": alignment, "external_spool_selections": {"rybw": "Black"}},
            )
            loaded = client.get("/api/system/settings")

        assert saved.status_code == 200, saved.text
        assert loaded.json()["settings"]["header_nav_alignment"] == alignment
        assert loaded.json()["settings"]["external_spool_selections"] == {"rybw": "Black"}
        assert json.loads(settings_file.read_text(encoding="utf-8"))[
            "header_nav_alignment"
        ] == alignment

    @pytest.mark.parametrize("alignment", ["right", "", 1, None])
    def test_post_settings_rejects_unknown_header_nav_alignment(
        self,
        alignment: object,
    ) -> None:
        response = client.post(
            "/api/system/settings",
            json={"header_nav_alignment": alignment},
        )

        assert response.status_code == 422

    def test_post_settings_preserves_fields_owned_by_newer_runtime_versions(
        self,
        tmp_path: Path,
    ) -> None:
        """旧运行版本保存设置时不删除未来版本新增字段。"""
        settings_path = tmp_path / "settings" / "common.json"
        settings_path.parent.mkdir()
        settings_path.write_text(
            json.dumps({"future_runtime_setting": {"schema": 2}}),
            encoding="utf-8",
        )
        payload = {
            "theme": "dark",
            "last_lut": "Shared",
        }

        with patch("api.routers.system.SETTINGS_FILE", settings_path):
            response = client.post("/api/system/settings", json=payload)

        assert response.status_code == 200
        stored = json.loads(settings_path.read_text(encoding="utf-8"))
        assert stored["theme"] == "dark"
        assert stored["future_runtime_setting"] == {"schema": 2}

    @pytest.mark.parametrize("legacy_env_value", ["", "1"])
    def test_post_settings_rejects_untrusted_origin(
        self,
        monkeypatch: pytest.MonkeyPatch,
        legacy_env_value: str,
    ) -> None:
        """拒绝外部网页保存设置，旧部署开关不能绕过限制。"""
        monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", legacy_env_value)
        payload = {
            "last_lut": "attacker-lut",
            "last_modeling_mode": "vector",
            "last_color_mode": "8-Color Max",
            "last_slicer": "attacker",
            "palette_mode": "swatch",
            "enable_crop_modal": False,
            "printer_model": "attacker-printer",
            "slicer_software": "AttackerSlicer",
            "device_profile_id": "Attacker:profile:0.8",
            "custom_slicer_path": "/tmp/attacker.app",
            "custom_slicer_id": "attacker-custom",
            "nozzle_size": "0.8",
            "enable_base_layer_height_modifier": False,
        }
        mock_file = MagicMock()

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.post(
                "/api/system/settings",
                json=payload,
                headers=UNTRUSTED_ORIGIN_HEADERS,
            )

        assert response.status_code == 403
        mock_file.write_text.assert_not_called()

    def test_post_settings_io_error(self) -> None:
        """I/O 错误返回 500，但不暴露本机路径或底层异常。"""
        payload = {
            "last_lut": "",
            "last_modeling_mode": "high-fidelity",
            "last_color_mode": "4-Color",
            "last_slicer": "",
            "palette_mode": "swatch",
            "enable_crop_modal": True,
            "nozzle_size": "0.4",
        }
        mock_file = MagicMock()
        private_path = "/Users/min/private/user_settings.json"
        mock_file.write_text.side_effect = OSError(
            f"cannot write {private_path}: disk full"
        )

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.post("/api/system/settings", json=payload)

        assert response.status_code == 500
        assert response.json()["detail"] == SETTINGS_SAVE_FAILED_DETAIL
        assert private_path not in response.text
        assert "disk full" not in response.text


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


class TestGetPrinters:
    """Verify GET /api/system/printers exposes nozzle-size metadata."""

    def test_get_printers_exposes_supported_nozzle_sizes(self) -> None:
        response = client.get("/api/system/printers")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["printers"]
        first = data["printers"][0]
        assert "supported_nozzle_sizes" in first
        assert "nozzle_count" not in first
        assert "is_dual_head" not in first

    def test_get_printers_exposes_flashforge_multicolor_registry_profiles(self) -> None:
        response = client.get("/api/system/printers")

        assert response.status_code == 200
        printers = response.json()["printers"]
        expected_nozzles = {
            "flashforge-ad5x": ["0.25", "0.4"],
            "flashforge-creator-5": ["0.25", "0.4"],
            "flashforge-creator-5-pro": ["0.25", "0.4"],
            "flashforge-guider-3-ultra": ["0.4"],
            "flashforge-guider4": ["0.25", "0.4"],
            "flashforge-guider4-pro": ["0.25", "0.4"],
        }
        flashforge_printers = {
            printer["id"]: printer
            for printer in printers
            if printer["id"] in expected_nozzles
        }
        assert set(flashforge_printers) == set(expected_nozzles)
        for printer_id, nozzle_sizes in expected_nozzles.items():
            printer = flashforge_printers[printer_id]
            assert printer["supported_slicers"] == ["FlashStudio"]
            assert [
                profile["nozzle_size"]
                for profile in printer["device_profiles"]
                if profile["slicer_id"] == "FlashStudio"
            ] == nozzle_sizes
        ad5x = flashforge_printers["flashforge-ad5x"]
        assert ad5x["thumbnail"].endswith("flashforge-ad5x_cover.png")

    def test_get_slicers_exposes_flash_studio_desktop(self) -> None:
        response = client.get("/api/system/slicers")

        assert response.status_code == 200
        assert {
            "id": "FlashStudio",
            "display_name": "Flash Studio Desktop",
        } in response.json()["slicers"]

    def test_get_printers_and_slicers_expose_qidi_studio_profiles(self) -> None:
        printers_response = client.get("/api/system/printers")
        slicers_response = client.get("/api/system/slicers")

        assert printers_response.status_code == 200
        assert slicers_response.status_code == 200
        assert {
            "id": "QIDIStudio",
            "display_name": "QIDI Studio",
        } in slicers_response.json()["slicers"]
        expected_nozzles = {
            "qidi-q2": ["0.2", "0.4"],
            "qidi-q2c": ["0.2", "0.4"],
            "qidi-x-max-4": ["0.2", "0.4"],
            "qidi-x-plus-5": ["0.4"],
        }
        printers = {
            printer["id"]: printer
            for printer in printers_response.json()["printers"]
            if printer["id"] in expected_nozzles
        }
        assert set(printers) == set(expected_nozzles)
        for printer_id, nozzles in expected_nozzles.items():
            printer = printers[printer_id]
            assert printer["supported_slicers"] == ["QIDIStudio"]
            assert [
                profile["nozzle_size"]
                for profile in printer["device_profiles"]
                if profile["slicer_id"] == "QIDIStudio"
            ] == nozzles

    def test_get_printers_attaches_registry_device_profiles(self, tmp_path, monkeypatch) -> None:
        registry_root = tmp_path / "machine_registry"
        registry_root.mkdir()
        thumbnail_path = registry_root / "slicers/BambuStudio/assets/h2d.png"
        thumbnail_path.parent.mkdir(parents=True)
        thumbnail_path.write_bytes(b"h2d-thumbnail")
        (registry_root / "registry.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": "2026-06-09T00:00:00+08:00",
                    "slicers": [
                        {
                            "slicer_id": "BambuStudio",
                            "display_name": "Bambu Studio",
                            "source_kind": "local_install",
                            "source_version": "02.07.01.57",
                            "profile_format": "bambu_orca",
                            "build_plates": [
                                {
                                    "id": "textured-pei-plate",
                                    "display_name": "Textured PEI Plate",
                                    "display_name_zh": "纹理PEI打印板",
                                    "image": "slicers/BambuStudio/build_plates/bed_pei.png",
                                    "source_path": "resources/images/bed_pei.png",
                                    "source_version": "02.07.01.57",
                                    "revision": "sha256:plate",
                                }
                            ],
                            "machines": [
                                {
                                    "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
                                    "display_name": "Bambu Lab H2D",
                                    "brand": "Bambu Lab",
                                    "vendor_key": "BBL",
                                    "bed_width": 350,
                                    "bed_depth": 320,
                                    "bed_height": 325,
                                    "thumbnail": "slicers/BambuStudio/assets/h2d.png",
                                    "supported_build_plate_ids": ["textured-pei-plate"],
                                    "default_build_plate_id": "textured-pei-plate",
                                    "nozzles": [
                                        {
                                            "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                                            "nozzle_size": "0.4",
                                            "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                                            "revision": "sha256:abc",
                                            "supported": True,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

        response = client.get("/api/system/printers")

        assert response.status_code == 200
        printers = response.json()["printers"]
        h2d = next(printer for printer in printers if printer["id"] == "bambu-h2d")
        assert h2d["thumbnail"] == "slicers/BambuStudio/assets/h2d.png"
        assert h2d["device_profiles"] == [
            {
                "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
                "slicer_id": "BambuStudio",
                "nozzle_size": "0.4",
                "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                "revision": "sha256:abc",
                "supported": True,
                "build_plates": [
                    {
                        "id": "textured-pei-plate",
                        "display_name": "Textured PEI Plate",
                        "display_name_zh": "纹理PEI打印板",
                        "image_url": "/api/system/machine-registry/assets/slicers/BambuStudio/build_plates/bed_pei.png",
                    }
                ],
                "default_build_plate_id": "textured-pei-plate",
            }
        ]

    def test_get_printers_includes_registry_only_orca_multicolor_machine(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        registry_root = tmp_path / "machine_registry"
        registry_root.mkdir()
        thumbnail_path = (
            registry_root / "slicers/OrcaSlicer/assets/snapmaker-artisan.png"
        )
        thumbnail_path.parent.mkdir(parents=True)
        thumbnail_path.write_bytes(b"snapmaker-thumbnail")
        (registry_root / "registry.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": "2026-06-09T00:00:00+08:00",
                    "slicers": [
                        {
                            "slicer_id": "OrcaSlicer",
                            "display_name": "OrcaSlicer",
                            "source_kind": "local_install",
                            "source_version": "02.04.00.00",
                            "profile_format": "bambu_orca",
                            "machines": [
                                {
                                    "machine_profile_id": "OrcaSlicer:snapmaker:snapmaker-artisan",
                                    "display_name": "Snapmaker Artisan",
                                    "brand": "Snapmaker",
                                    "vendor_key": "Snapmaker",
                                    "bed_width": 400,
                                    "bed_depth": 400,
                                    "bed_height": 400,
                                    "thumbnail": "slicers/OrcaSlicer/assets/snapmaker-artisan.png",
                                    "nozzles": [
                                        {
                                            "device_profile_id": "OrcaSlicer:snapmaker:snapmaker-artisan:0.4",
                                            "nozzle_size": "0.4",
                                            "source_profile_name": "Snapmaker Artisan 0.4 nozzle",
                                            "revision": "sha256:artisan",
                                            "supported": True,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

        response = client.get("/api/system/printers")

        assert response.status_code == 200
        printers = response.json()["printers"]
        snapmaker_artisan = next(printer for printer in printers if printer["id"] == "snapmaker-artisan")
        assert snapmaker_artisan["display_name"] == "Snapmaker Artisan"
        assert snapmaker_artisan["supported_slicers"] == ["OrcaSlicer"]
        assert snapmaker_artisan["supported_nozzle_sizes"] == ["0.4"]
        assert snapmaker_artisan["thumbnail"] == "slicers/OrcaSlicer/assets/snapmaker-artisan.png"
        assert snapmaker_artisan["device_profiles"][0]["device_profile_id"] == (
            "OrcaSlicer:snapmaker:snapmaker-artisan:0.4"
        )

    def test_machine_registry_asset_serves_thumbnail_inside_registry(self, tmp_path, monkeypatch) -> None:
        registry_root = tmp_path / "machine_registry"
        asset_path = registry_root / "slicers" / "BambuStudio" / "assets" / "h2d.png"
        asset_path.parent.mkdir(parents=True)
        asset_path.write_bytes(b"fake-thumbnail")
        monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

        response = client.get("/api/system/machine-registry/assets/slicers/BambuStudio/assets/h2d.png")

        assert response.status_code == 200
        assert response.content == b"fake-thumbnail"
        assert response.headers["content-type"].startswith("image/png")

    def test_machine_registry_serves_selected_device_native_bed_model(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        installed_model = tmp_path / "installed-slicer" / "a1-mini.stl"
        installed_model.parent.mkdir(parents=True)
        installed_model.write_bytes(b"native-bed-model")
        monkeypatch.setattr(
            "api.routers.system.resolve_installed_bed_model",
            lambda _profile: installed_model,
        )

        response = client.get(
            "/api/system/machine-registry/bed-model",
            params={
                "device_profile_id": (
                    "OrcaSlicer:bbl:bambu-lab-a1-mini:0.4"
                )
            },
        )

        assert response.status_code == 200
        assert response.content
        assert response.headers["content-type"].startswith("model/stl")

    def test_machine_registry_bed_model_is_optional_without_installed_slicer(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            "api.routers.system.resolve_installed_bed_model",
            lambda _profile: None,
        )

        response = client.get(
            "/api/system/machine-registry/bed-model",
            params={
                "device_profile_id": (
                    "OrcaSlicer:bbl:bambu-lab-a1-mini:0.4"
                )
            },
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Bed model not found"

    def test_machine_registry_bed_model_rejects_untrusted_web_origin(
        self,
        monkeypatch,
    ) -> None:
        def fail_if_resolver_runs(_profile):
            raise AssertionError("Untrusted requests must be rejected before file lookup")

        monkeypatch.setattr(
            "api.routers.system.resolve_installed_bed_model",
            fail_if_resolver_runs,
        )

        response = client.get(
            "/api/system/machine-registry/bed-model",
            params={
                "device_profile_id": (
                    "OrcaSlicer:bbl:bambu-lab-a1-mini:0.4"
                )
            },
            headers={
                "Origin": "https://attacker.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )

        assert response.status_code == 403
        assert "local Lumina Studio app" in response.json()["detail"]

    def test_machine_registry_asset_serves_from_configured_root(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        registry_root = tmp_path / "machine_registry"
        asset_path = registry_root / "build_plates" / "bed_pei.png"
        asset_path.parent.mkdir(parents=True)
        asset_path.write_bytes(b"neutral-plate")
        unrelated_cwd = tmp_path / "cwd"
        unrelated_cwd.mkdir()
        monkeypatch.chdir(unrelated_cwd)
        monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

        response = client.get(
            "/api/system/machine-registry/assets/build_plates/bed_pei.png"
        )

        assert response.status_code == 200
        assert response.content == b"neutral-plate"

    def test_minimal_registry_keeps_profiles_and_omits_thumbnails(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        from core.machine_registry import load_machine_registry

        source_root = Path(__file__).resolve().parents[1] / "machine_registry"
        source_registry = load_machine_registry(source_root / "registry.json")
        source_data = json.loads(
            (source_root / "registry.json").read_text(encoding="utf-8")
        )
        registry_root = tmp_path / "machine_registry"
        registry_root.mkdir(parents=True)
        shutil.copy2(source_root / "registry.json", registry_root / "registry.json")

        runtime_paths = {
            str(plate["image"])
            for slicer in source_data["slicers"]
            for plate in slicer.get("build_plates", [])
        }
        for relative_path in runtime_paths:
            destination = registry_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_root / relative_path, destination)

        unrelated_cwd = tmp_path / "elsewhere"
        unrelated_cwd.mkdir()
        monkeypatch.chdir(unrelated_cwd)
        monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

        response = client.get("/api/system/printers")

        assert response.status_code == 200
        printers = response.json()["printers"]
        actual_profiles = {
            profile["device_profile_id"]: profile
            for printer in printers
            for profile in printer["device_profiles"]
        }
        expected_profiles = {
            device.device_profile_id: {
                "build_plate_ids": [plate.id for plate in device.build_plates],
                "default_build_plate_id": device.default_build_plate_id,
            }
            for device in source_registry.devices_by_id.values()
        }
        assert set(actual_profiles) == set(expected_profiles)
        for profile_id, expected in expected_profiles.items():
            actual = actual_profiles[profile_id]
            assert [plate["id"] for plate in actual["build_plates"]] == expected[
                "build_plate_ids"
            ]
            assert actual["default_build_plate_id"] == expected[
                "default_build_plate_id"
            ]
        assert all(printer["thumbnail"] == "" for printer in printers)

        plate_path = next(iter(sorted(
            str(plate["image"])
            for slicer in source_data["slicers"]
            for plate in slicer.get("build_plates", [])
        )))
        plate_response = client.get(
            f"/api/system/machine-registry/assets/{plate_path}"
        )
        assert plate_response.status_code == 200

        old_thumbnail = next(
            str(machine["thumbnail"])
            for slicer in source_data["slicers"]
            for machine in slicer["machines"]
            if machine.get("thumbnail")
        )
        thumbnail_response = client.get(
            f"/api/system/machine-registry/assets/{old_thumbnail}"
        )
        assert thumbnail_response.status_code == 404

    def test_machine_registry_asset_rejects_path_traversal(self, tmp_path, monkeypatch) -> None:
        registry_root = tmp_path / "machine_registry"
        registry_root.mkdir()
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"outside")
        monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

        response = client.get("/api/system/machine-registry/assets/../outside.png")

        assert response.status_code in {400, 404}
