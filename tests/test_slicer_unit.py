# -*- coding: utf-8 -*-
"""Unit tests for slicer detection and launch (core/slicer.py, api/routers/slicer.py).

Validates registry scanning, slicer detection, launch logic,
Pydantic schema validation, and REST endpoint behaviour.
Requirements: 1.3, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.6
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.schemas.slicer import (
    SlicerDetectResponse,
    SlicerInfo,
    SlicerLaunchRequest,
    SlicerLaunchResponse,
)
from core.slicer import (
    DetectedSlicer,
    detect_installed_slicers,
    launch_slicer,
    scan_registry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    """Build a minimal FastAPI app with only the slicer router."""
    from fastapi import FastAPI
    from api.routers.slicer import router
    app = FastAPI()
    app.include_router(router)
    return app


def _make_client() -> TestClient:
    return TestClient(_make_app())


# =========================================================================
# 1. scan_registry — non-Windows returns empty list (Requirement 1.3)
# =========================================================================

class TestScanRegistry:
    """scan_registry() must return [] on non-Windows platforms."""

    @patch("core.slicer.platform.system", return_value="Linux")
    def test_scan_registry_non_windows_linux(self, _mock_sys):
        assert scan_registry() == []

    @patch("core.slicer.platform.system", return_value="Darwin")
    def test_scan_registry_non_windows_darwin(self, _mock_sys):
        assert scan_registry() == []


# =========================================================================
# 2. detect_installed_slicers — mock data (Requirement 1.3, 1.5)
# =========================================================================

class TestDetectInstalledSlicers:
    """detect_installed_slicers() filters out entries with invalid exe_path."""

    def test_filters_invalid_paths(self, tmp_path):
        real_exe = tmp_path / "bambu.exe"
        real_exe.write_text("fake")

        mock_results = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path=str(real_exe)),
            DetectedSlicer(id="orca_slicer", display_name="OrcaSlicer", exe_path="/nonexistent/orca.exe"),
        ]

        with patch("core.slicer.scan_registry", return_value=mock_results):
            result = detect_installed_slicers()

        assert len(result) == 1
        assert result[0].id == "bambu_studio"

    def test_returns_empty_when_all_invalid(self):
        mock_results = [
            DetectedSlicer(id="x", display_name="X", exe_path="/no/such/file.exe"),
        ]
        with patch("core.slicer.scan_registry", return_value=mock_results):
            result = detect_installed_slicers()
        assert result == []

    def test_returns_empty_when_scan_empty(self):
        with patch("core.slicer.scan_registry", return_value=[]):
            result = detect_installed_slicers()
        assert result == []


# =========================================================================
# 3. launch_slicer — success / failure scenarios (Requirements 2.2-2.5)
# =========================================================================

class TestLaunchSlicer:
    """launch_slicer() success and failure paths."""

    def test_success(self, tmp_path):
        """Mock Popen, verify (True, message). Requirement 2.4"""
        f = tmp_path / "model.3mf"
        f.write_text("data")
        slicers = [DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe")]

        with patch("core.slicer.subprocess.Popen") as mock_popen:
            ok, msg = launch_slicer("bambu_studio", str(f), slicers)

        assert ok is True
        assert "Bambu Studio" in msg
        mock_popen.assert_called_once()

    def test_unknown_slicer_id(self, tmp_path):
        """Unknown slicer_id → (False, error). Requirement 2.2"""
        f = tmp_path / "model.3mf"
        f.write_text("data")
        slicers = [DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe")]

        ok, msg = launch_slicer("unknown_slicer", str(f), slicers)
        assert ok is False
        assert "not found" in msg.lower()

    def test_file_not_found(self):
        """Non-existent file_path → (False, error). Requirement 2.3"""
        slicers = [DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe")]
        ok, msg = launch_slicer("bambu_studio", "/no/such/file.3mf", slicers)
        assert ok is False
        assert "does not exist" in msg.lower() or "not exist" in msg.lower()

    def test_process_error(self, tmp_path):
        """Popen raises exception → (False, error). Requirement 2.5"""
        f = tmp_path / "model.3mf"
        f.write_text("data")
        slicers = [DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe")]

        with patch("core.slicer.subprocess.Popen", side_effect=OSError("permission denied")):
            ok, msg = launch_slicer("bambu_studio", str(f), slicers)

        assert ok is False
        assert "permission denied" in msg.lower() or "failed" in msg.lower()


# =========================================================================
# 4. Pydantic model validation (Requirements 6.1-6.6)
# =========================================================================

class TestPydanticModels:
    """Pydantic schema validation for slicer models."""

    def test_slicer_info_valid(self):
        info = SlicerInfo(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe")
        assert info.id == "bambu_studio"
        assert info.display_name == "Bambu Studio"

    def test_slicer_info_empty_id_rejected(self):
        """id with min_length=1 rejects empty string. Requirement 6.5"""
        with pytest.raises(ValidationError):
            SlicerInfo(id="", display_name="X", exe_path="C:\\x.exe")

    def test_launch_request_valid(self):
        req = SlicerLaunchRequest(slicer_id="bambu_studio", file_path="/tmp/model.3mf")
        assert req.slicer_id == "bambu_studio"

    def test_launch_request_empty_path_rejected(self):
        """file_path with min_length=1 rejects empty string. Requirement 6.6"""
        with pytest.raises(ValidationError):
            SlicerLaunchRequest(slicer_id="bambu_studio", file_path="")

    def test_detect_response_defaults_to_empty_list(self):
        resp = SlicerDetectResponse()
        assert resp.slicers == []

    def test_launch_response_valid(self):
        resp = SlicerLaunchResponse(status="success", message="ok")
        assert resp.status == "success"


# =========================================================================
# 5. Router endpoint tests (Requirements 3.1, 3.2, 3.6)
# =========================================================================

class TestRouterEndpoints:
    """FastAPI TestClient tests for slicer router."""

    def test_detect_endpoint_returns_200(self):
        """GET /api/slicer/detect returns 200 with slicer list. Requirement 3.1"""
        client = _make_client()
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]
        with patch("api.routers.slicer.detect_installed_slicers", return_value=mock_slicers):
            resp = client.get("/api/slicer/detect")

        assert resp.status_code == 200
        data = resp.json()
        assert "slicers" in data
        assert len(data["slicers"]) == 1
        assert data["slicers"][0]["id"] == "bambu_studio"

    def test_detect_endpoint_empty(self):
        """GET /api/slicer/detect with no slicers returns empty list."""
        client = _make_client()
        with patch("api.routers.slicer.detect_installed_slicers", return_value=[]):
            resp = client.get("/api/slicer/detect")

        assert resp.status_code == 200
        assert resp.json()["slicers"] == []

    def test_launch_success(self, tmp_path):
        """POST /api/slicer/launch with valid data returns success. Requirement 3.2"""
        f = tmp_path / "model.3mf"
        f.write_text("data")

        client = _make_client()
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]
        with patch("api.routers.slicer.detect_installed_slicers", return_value=mock_slicers), \
             patch("api.routers.slicer.launch_slicer", return_value=(True, "Opened in Bambu Studio")):
            resp = client.post("/api/slicer/launch", json={
                "slicer_id": "bambu_studio",
                "file_path": str(f),
            })

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_launch_file_not_found(self):
        """POST with non-existent file returns 400. Requirement 2.3"""
        client = _make_client()
        resp = client.post("/api/slicer/launch", json={
            "slicer_id": "bambu_studio",
            "file_path": "/nonexistent/model.3mf",
        })
        assert resp.status_code == 400
        assert resp.json()["status"] == "error"

    def test_launch_invalid_body_returns_422(self):
        """POST with invalid body returns 422. Requirement 3.6"""
        client = _make_client()
        resp = client.post("/api/slicer/launch", json={"bad_field": "value"})
        assert resp.status_code == 422

    def test_launch_empty_body_returns_422(self):
        """POST with empty body returns 422. Requirement 3.6"""
        client = _make_client()
        resp = client.post("/api/slicer/launch", json={})
        assert resp.status_code == 422

    def test_launch_slicer_not_found_returns_404(self, tmp_path):
        """POST with unknown slicer_id returns 404. Requirement 2.2"""
        f = tmp_path / "model.3mf"
        f.write_text("data")

        client = _make_client()
        with patch("api.routers.slicer.detect_installed_slicers", return_value=[]), \
             patch("api.routers.slicer.launch_slicer", return_value=(False, "Slicer not found: unknown")):
            resp = client.post("/api/slicer/launch", json={
                "slicer_id": "unknown",
                "file_path": str(f),
            })

        assert resp.status_code == 404
        assert resp.json()["status"] == "error"
