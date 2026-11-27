"""Unit tests for Calibration endpoint integration.

Validates:
- 4 color_mode routing dispatches to correct core functions (Requirement 3.1-3.4)
- Parameter mapping from Pydantic fields to core function args (Requirement 3.5)
- Core exception returns HTTP 500 (Requirement 3.6)
"""

import io
import json
import logging
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.routers.calibration import (
    CALIBRATION_GENERATION_FAILED_DETAIL,
    CALIBRATION_OUTPUT_PREPARATION_FAILED_DETAIL,
)
from config import DEFAULT_PRINTER_ID, DEFAULT_SLICER_ID

client: TestClient = TestClient(create_app())

# Shared mock return value: (file_path, PIL preview image, status string)
_mock_preview: Image.Image = Image.fromarray(
    np.zeros((10, 10, 3), dtype=np.uint8)
)
_mock_return = ("/tmp/fake.3mf", _mock_preview, "OK")

class _RegisterPathFailingRegistry(FileRegistry):
    """Registry stub that records the generated path before failing."""

    def __init__(self) -> None:
        super().__init__()
        self.generated_path: str | None = None

    def register_path(self, *args: object, **kwargs: object) -> str:
        if "path" in kwargs:
            self.generated_path = str(kwargs["path"])
        elif len(args) >= 2:
            self.generated_path = str(args[1])
        raise RuntimeError("registry backend unavailable")


class _RegisterBytesFailingRegistry(FileRegistry):
    """Registry stub that fails after the generated export is registered."""

    def __init__(self) -> None:
        super().__init__()
        self.path_file_ids: list[str] = []

    def register_path(self, *args: object, **kwargs: object) -> str:
        file_id = super().register_path(*args, **kwargs)
        self.path_file_ids.append(file_id)
        return file_id

    def register_bytes(self, *args: object, **kwargs: object) -> str:
        raise RuntimeError(
            "registry byte storage unavailable at /Users/min/private/preview.png"
        )


class _SecondRegisterBytesFailingRegistry(FileRegistry):
    """Registry stub that fails after one preview image is registered."""

    def __init__(self) -> None:
        super().__init__()
        self.path_file_ids: list[str] = []
        self.byte_file_ids: list[str] = []
        self._byte_calls = 0
        self._registering_bytes = False

    def register_path(self, *args: object, **kwargs: object) -> str:
        file_id = super().register_path(*args, **kwargs)
        if self._registering_bytes:
            self.byte_file_ids.append(file_id)
        else:
            self.path_file_ids.append(file_id)
        return file_id

    def register_bytes(self, *args: object, **kwargs: object) -> str:
        self._byte_calls += 1
        if self._byte_calls == 2:
            raise RuntimeError(
                "registry layer storage unavailable at /Users/min/private/layer.png"
            )
        self._registering_bytes = True
        try:
            return super().register_bytes(*args, **kwargs)
        finally:
            self._registering_bytes = False


def _assert_default_device_kwargs(kwargs: dict) -> None:
    assert kwargs["printer_id"] == DEFAULT_PRINTER_ID
    assert kwargs["slicer"] == DEFAULT_SLICER_ID
    assert kwargs["nozzle_size"] == "0.4"


# =========================================================================
# 1. Color mode routing - Requirement 3
# =========================================================================


class TestColorModeRouting:
    """Verify each color_mode dispatches to the correct core function."""

    def test_generate_cleans_output_when_registry_fails(
        self,
        tmp_path: Path,
    ) -> None:
        output_path = tmp_path / "calibration.3mf"
        output_path.write_bytes(b"placeholder-3mf")
        registry = _RegisterPathFailingRegistry()
        app = create_app()
        app.dependency_overrides[get_file_registry] = lambda: registry
        failing_client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "api.routers.calibration.generate_bw_calibration_board",
            return_value=(str(output_path), None, "OK"),
        ):
            response = failing_client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "BW (Black & White)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )

        assert response.status_code == 500
        assert registry.generated_path == str(output_path)
        assert not output_path.exists()

    def test_generate_preserves_download_when_preview_registration_fails(
        self,
        tmp_path: Path,
        caplog,
    ) -> None:
        output_path = tmp_path / "calibration.3mf"
        output_path.write_bytes(b"placeholder-3mf")
        registry = _RegisterBytesFailingRegistry()
        app = create_app()
        app.dependency_overrides[get_file_registry] = lambda: registry
        failing_client = TestClient(app, raise_server_exceptions=False)
        target_logger = logging.getLogger("lumina.api.routers.calibration")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        try:
            with patch(
                "api.routers.calibration.generate_calibration_board",
                return_value=(str(output_path), _mock_preview, "OK"),
            ):
                response = failing_client.post(
                    "/api/calibration/generate",
                    json={
                        "color_mode": "4-Color (RYBW)",
                        "block_size": 5,
                        "gap": 0.84,
                        "backing_thickness": 1.6,
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["download_url"].startswith("/api/files/")
        assert body["preview_url"] is None
        assert body["layer_urls"] is None
        assert len(registry.path_file_ids) == 1
        download_id = registry.path_file_ids[0]
        assert body["download_url"].endswith(download_id)
        assert registry.get_entry(download_id) is not None
        resolved_download = registry.resolve(download_id)
        assert resolved_download is not None
        assert resolved_download[0] == str(output_path)
        download_response = failing_client.get(body["download_url"])
        assert download_response.status_code == 200
        assert download_response.content == b"placeholder-3mf"
        assert output_path.exists()
        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "calibration_preview_registration_failed"
        ]
        assert len(records) == 1
        assert records[0].context == "Calibration preview registration"
        assert records[0].export_ids == [download_id]
        assert records[0].error_type == "RuntimeError"
        assert "registry byte storage unavailable" in records[0].error_message

    def test_generate_cleans_preview_when_layer_registration_fails(
        self,
        tmp_path: Path,
    ) -> None:
        output_path = tmp_path / "calibration.3mf"
        output_path.write_bytes(b"placeholder-3mf")
        registry = _SecondRegisterBytesFailingRegistry()
        app = create_app()
        app.dependency_overrides[get_file_registry] = lambda: registry
        failing_client = TestClient(app, raise_server_exceptions=False)
        preview_imgs = [
            Image.new("RGB", (8, 8), (255, 255, 255)),
            Image.new("RGB", (8, 8), (0, 0, 0)),
        ]

        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=(str(output_path), preview_imgs, "OK"),
        ):
            response = failing_client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["download_url"].startswith("/api/files/")
        assert body["preview_url"] is None
        assert body["layer_urls"] is None
        assert len(registry.path_file_ids) == 1
        assert len(registry.byte_file_ids) == 1
        download_id = registry.path_file_ids[0]
        preview_id = registry.byte_file_ids[0]
        assert registry.get_entry(download_id) is not None
        assert registry.get_entry(preview_id) is None
        assert registry.resolve(preview_id) is None
        assert failing_client.get(body["download_url"]).status_code == 200
        assert output_path.exists()

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
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_color"] == "White"
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.6
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_four_color_mode_routes_to_generate_calibration_board(self) -> None:
        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["color_mode"] == "RYBW"
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_color"] == "White"
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.6
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_six_color_mode_routes_to_generate_smart_board(self) -> None:
        with patch(
            "api.routers.calibration.generate_smart_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "6-Color (CMYWGK 1296)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.6
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_eight_color_full_export_routes_to_generate_8color_full_batch_zip(self) -> None:
        with patch(
            "api.routers.calibration.generate_8color_full_batch_zip",
            return_value=("/tmp/fake_full.zip", _mock_preview, "OK"),
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "8-Color Max",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                    "eight_color_full_export": True,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.6
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

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
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.6
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)


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
                    "backing_thickness": 2.4,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["block_size_mm"] == 8.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 1.5
            assert mock_fn.call_args.kwargs["backing_color"] == "White"
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 2.4
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)
            # Verify block_size is passed as float and backing color is hard-coded.
            call_kwargs = mock_fn.call_args.kwargs
            assert isinstance(call_kwargs["block_size_mm"], float)
            assert call_kwargs["backing_color"] == "White"

    def test_fractional_block_size_is_accepted(self) -> None:
        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5.5,
                    "gap": 0.84,
                    "backing_thickness": 1.2,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["color_mode"] == "RYBW"
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.5
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_color"] == "White"
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.2
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_backing_thickness_defaults_when_omitted(self) -> None:
        """Omitting backing_thickness in the payload should fall back to the schema default (1.2 mm)."""
        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["color_mode"] == "RYBW"
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_color"] == "White"
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.2
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_device_settings_are_forwarded_to_core_generator(self) -> None:
        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.2,
                    "printer_id": "bambu-p1s",
                    "slicer": "OrcaSlicer",
                    "nozzle_size": "0.2",
                },
            )

        assert response.status_code == 200
        assert response.json()["threemf_disk_path"] is None
        assert "/tmp/fake.3mf" not in response.text
        mock_fn.assert_called_once()
        kwargs = mock_fn.call_args.kwargs
        assert kwargs["printer_id"] == "bambu-p1s"
        assert kwargs["slicer"] == "OrcaSlicer"
        assert kwargs["nozzle_size"] == "0.2"


# Placement part as written for the X2D 0.2 / 5-Color Extended Page1 no-fit case.
_MANUAL_PLACEMENT_JSON = json.dumps(
    {
        "adapted": False,
        "available": True,
        "enabled": True,
        "envelope_policy": "axis_aligned_bounds_with_full_brim_allowance",
        "model_size_mm": [218.4, 218.4],
        "placement_applied": False,
        "printable_bounds_mm": [235.5, 256.0],
        "reason": "no_safe_layout_without_scaling_or_disabling_tower",
        "requires_manual_adjustment": True,
        "reserved_envelope_mm": [232.4, 232.4],
        "schema_version": 1,
        "warning_code": "wipe_tower_manual_adjustment_required",
    },
    indent=2,
)


def _project_bytes(placement_json: str | None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as project:
        project.writestr("3D/3dmodel.model", "<model/>")
        if placement_json is not None:
            project.writestr("Metadata/lumina_wipe_tower_placement.json", placement_json)
    return buffer.getvalue()


class TestPlacementWarnings:
    """Generated wipe-tower warnings must reach the calibration response."""

    def test_zip_kit_reports_manual_layout_warning_from_each_page(
        self,
        tmp_path: Path,
    ) -> None:
        kit_path = tmp_path / "Lumina_Calibration_Kit_5C.zip"
        with zipfile.ZipFile(kit_path, "w") as kit:
            kit.writestr("Page1_5C.3mf", _project_bytes(_MANUAL_PLACEMENT_JSON))
            kit.writestr("Page2_5C.3mf", _project_bytes(_MANUAL_PLACEMENT_JSON))
        kit_bytes = kit_path.read_bytes()

        with patch(
            "api.routers.calibration.generate_5color_extended_batch_zip",
            return_value=(str(kit_path), _mock_preview, "OK"),
        ):
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "5-Color Extended (1444)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.2,
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["warnings"] == ["wipe_tower_manual_adjustment_required"]
        download = client.get(body["download_url"])
        assert download.status_code == 200
        assert download.content == kit_bytes

    def test_project_without_placement_part_reports_no_warnings(
        self,
        tmp_path: Path,
    ) -> None:
        project_path = tmp_path / "calibration.3mf"
        project_path.write_bytes(_project_bytes(None))

        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=(str(project_path), _mock_preview, "OK"),
        ):
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.2,
                },
            )

        assert response.status_code == 200
        assert response.json()["warnings"] == []



# =========================================================================
# 3. Error handling - Requirement 3.6
# =========================================================================


class TestErrorHandling:
    """Verify core exceptions are translated to HTTP 500 responses."""

    def test_missing_8color_data_keeps_output_error_boundary(self, caplog) -> None:
        failing_client = TestClient(create_app(), raise_server_exceptions=False)
        target_logger = logging.getLogger("lumina")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.ERROR, logger=target_logger.name)

        try:
            with patch(
                "core.calibration._load_selected_8color_stacks",
                side_effect=FileNotFoundError("selected 8-color stacks unavailable"),
            ):
                response = failing_client.post(
                    "/api/calibration/generate",
                    json={"color_mode": "8-Color Max", "eight_color_full_export": False},
                )
        finally:
            failing_client.close()
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 500
        assert response.json() == {
            "detail": CALIBRATION_OUTPUT_PREPARATION_FAILED_DETAIL,
        }
        events = {getattr(record, "event", None) for record in caplog.records}
        assert "calibration_output_preparation_failed" in events
        assert "api_unhandled_exception" not in events

    def test_core_exception_returns_500(self) -> None:
        private_path = "/Users/min/private/calibration.3mf"

        with patch(
            "api.routers.calibration.generate_calibration_board",
            side_effect=RuntimeError(f"disk full while writing {private_path}"),
        ):
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )
            assert response.status_code == 500
            assert response.json()["detail"] == CALIBRATION_GENERATION_FAILED_DETAIL
            assert "disk full" not in response.text
            assert private_path not in response.text

    def test_single_stage_kit_preserves_downloads_when_preview_registration_fails(
        self,
        tmp_path: Path,
        caplog,
    ) -> None:
        zip_path = tmp_path / "single-stage.zip"
        manifest_path = tmp_path / "manifest.json"
        zip_path.write_bytes(b"zip")
        manifest_path.write_text("{}", encoding="utf-8")
        registry = _RegisterBytesFailingRegistry()
        app = create_app()
        app.dependency_overrides[get_file_registry] = lambda: registry
        failing_client = TestClient(app, raise_server_exceptions=False)
        target_logger = logging.getLogger("lumina.api.routers.calibration")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        try:
            with patch(
                "api.routers.calibration.generate_single_stage_kit",
                return_value=SimpleNamespace(
                    zip_path=str(zip_path),
                    manifest_path=str(manifest_path),
                    preview_image=Image.new("RGB", (8, 8), (255, 255, 255)),
                    jobs=[],
                    message="OK",
                ),
            ):
                response = failing_client.post(
                    "/api/calibration/generate-single-stage-kit",
                    json={
                        "palette": [
                            {
                                "color": "White",
                                "material": "PLA Basic",
                                "hex_color": "#FFFFFF",
                                "color_name": "White",
                            }
                        ],
                        "substrate_id": "white",
                        "substrate_display_name": "White",
                        "material_default": "PLA Basic",
                        "layer_height_mm": 0.04,
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["kit_download_url"].startswith("/api/files/")
        assert body["manifest_url"].startswith("/api/files/")
        assert body["preview_url"] is None
        assert len(registry.path_file_ids) == 2
        kit_id, manifest_id = registry.path_file_ids
        assert body["kit_download_url"].endswith(kit_id)
        assert body["manifest_url"].endswith(manifest_id)
        assert registry.get_entry(kit_id) is not None
        assert registry.get_entry(manifest_id) is not None
        resolved_kit = registry.resolve(kit_id)
        resolved_manifest = registry.resolve(manifest_id)
        assert resolved_kit is not None
        assert resolved_manifest is not None
        assert resolved_kit[0] == str(zip_path)
        assert resolved_manifest[0] == str(manifest_path)
        kit_response = failing_client.get(body["kit_download_url"])
        manifest_response = failing_client.get(body["manifest_url"])
        assert kit_response.status_code == 200
        assert manifest_response.status_code == 200
        assert kit_response.content == b"zip"
        assert manifest_response.content == b"{}"
        assert zip_path.exists()
        assert manifest_path.exists()
        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "calibration_preview_registration_failed"
        ]
        assert len(records) == 1
        assert records[0].context == "Single-stage kit preview registration"
        assert records[0].export_ids == [kit_id, manifest_id]
        assert records[0].error_type == "RuntimeError"

    def test_single_stage_kit_incompatible_build_plate_returns_422_not_500(
        self,
        caplog,
    ) -> None:
        failing_client = TestClient(create_app(), raise_server_exceptions=False)
        target_logger = logging.getLogger("lumina")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)
        try:
            response = failing_client.post(
                "/api/calibration/generate-single-stage-kit",
                json={
                    "palette": [
                        {
                            "color": "Sample",
                            "material": "PLA Basic",
                            "hex_color": "#808080",
                            "color_name": "Sample",
                        }
                    ],
                    "substrate_id": "white",
                    "substrate_display_name": "White",
                    "material_default": "PLA Basic",
                    "layer_height_mm": 0.08,
                    "printer_id": "bambu-x1c",
                    "slicer": "BambuStudio",
                    "nozzle_size": "0.4",
                    "device_profile_id": "BambuStudio:bbl:bambu-lab-x1-carbon:0.4",
                    "build_plate_id": "engineering-plate",
                },
            )
        finally:
            failing_client.close()
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["error"] == "native_material_selection_required"
        assert "Engineering Plate" in detail["message"]
        events = {getattr(record, "event", None) for record in caplog.records}
        assert "api_unhandled_exception" not in events
        assert "calibration_core_operation_failed" not in events

    def test_legacy_calibration_incompatible_build_plate_returns_422_not_500(
        self,
        caplog,
    ) -> None:
        failing_client = TestClient(create_app(), raise_server_exceptions=False)
        target_logger = logging.getLogger("lumina")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)
        try:
            response = failing_client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "BW (Black & White)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.2,
                    "printer_id": "bambu-x1c",
                    "slicer": "BambuStudio",
                    "nozzle_size": "0.4",
                    "device_profile_id": "BambuStudio:bbl:bambu-lab-x1-carbon:0.4",
                    "build_plate_id": "engineering-plate",
                },
            )
        finally:
            failing_client.close()
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["error"] == "native_material_selection_required"
        assert "Engineering Plate" in detail["message"]
        events = {getattr(record, "event", None) for record in caplog.records}
        assert "api_unhandled_exception" not in events

    def test_calibration_core_processing_error_returns_sanitized_500(self) -> None:
        from core.errors import CoreProcessingError

        private_path = "/Users/min/private/single_stage.3mf"
        with patch(
            "api.routers.calibration.generate_single_stage_kit",
            side_effect=CoreProcessingError(f"failed writing {private_path}"),
        ):
            response = client.post(
                "/api/calibration/generate-single-stage-kit",
                json={
                    "palette": [
                        {
                            "color": "White",
                            "material": "PLA Basic",
                            "hex_color": "#FFFFFF",
                            "color_name": "White",
                        }
                    ],
                    "substrate_id": "white",
                    "substrate_display_name": "White",
                    "material_default": "PLA Basic",
                    "layer_height_mm": 0.08,
                },
            )

        assert response.status_code == 500
        assert private_path not in response.text
