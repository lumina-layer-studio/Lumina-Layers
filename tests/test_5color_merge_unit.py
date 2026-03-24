"""Unit tests for 5-Color Extended merge endpoint and calibration generation.

Validates:
- merge-5color-extended endpoint success scenario (Requirement 2.1, 2.2, 2.3)
- merge-5color-extended returns HTTP 400 when temp files missing (Requirement 1.5)
- Calibration board generation for 5-Color Extended mode (Requirement 3.3, 3.4)
"""

from __future__ import annotations

import os
import tempfile
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app

client: TestClient = TestClient(app)

# Shared mock preview image for calibration tests
_mock_preview: Image.Image = Image.fromarray(
    np.zeros((10, 10, 3), dtype=np.uint8)
)

# Save real os.path.join to avoid recursion when patching
_real_path_join = os.path.join


def _make_join_redirector(assets_dir: str):
    """Create an os.path.join side_effect that redirects temp_5c files to assets_dir."""
    def _join(*args: Any) -> str:
        last = args[-1] if args else ""
        if isinstance(last, str) and ("temp_5c" in last or "lumina_lut" in last):
            return _real_path_join(assets_dir, last)
        return _real_path_join(*args)
    return _join


# =========================================================================
# 1. merge-5color-extended endpoint — success scenario
#    Requirements: 2.1, 2.2, 2.3
# =========================================================================


class TestMerge5ColorExtendedSuccess:
    """Verify merge endpoint reads two temp files, vstacks, and returns ExtractResponse."""

    def test_merge_success_returns_200_with_extract_response(self) -> None:
        """Both temp files exist → merge produces correct result and returns 200."""
        from utils.lut_manager import LUTManager
        from config import LUTMetadata, PaletteEntry

        lut1 = np.random.randint(0, 256, (100, 3), dtype=np.uint8)
        lut2 = np.random.randint(0, 256, (80, 3), dtype=np.uint8)
        metadata = LUTMetadata(palette=[
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="Cyan", material="PLA Basic"),
            PaletteEntry(color="Magenta", material="PLA Basic"),
            PaletteEntry(color="Yellow", material="PLA Basic"),
            PaletteEntry(color="Black", material="PLA Basic"),
        ])

        with tempfile.TemporaryDirectory() as tmpdir:
            LUTManager.save_keyed_json(
                _real_path_join(tmpdir, "temp_5c_ext_page_1.json"),
                lut1, np.zeros((100, 5), dtype=np.int32), metadata)
            LUTManager.save_keyed_json(
                _real_path_join(tmpdir, "temp_5c_ext_page_2.json"),
                lut2, np.zeros((80, 5), dtype=np.int32), metadata)
            merged_path = _real_path_join(tmpdir, "lumina_lut.json")

            with (
                patch("api.routers.extractor.os.path.join", side_effect=_make_join_redirector(tmpdir)),
                patch("config.LUT_FILE_PATH", merged_path),
            ):
                response = client.post("/api/extractor/merge-5color-extended")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["session_id"]
            assert "/api/files/" in data["lut_download_url"]
            assert "5-Color Extended" in data["message"]

    def test_merge_produces_correct_shape(self) -> None:
        """Merged LUT shape should be (N+M, 3) after reshape + vstack."""
        from utils.lut_manager import LUTManager
        from config import LUTMetadata, PaletteEntry

        lut1 = np.random.randint(0, 256, (50, 3), dtype=np.uint8)
        lut2 = np.random.randint(0, 256, (70, 3), dtype=np.uint8)
        metadata = LUTMetadata(palette=[
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="Cyan", material="PLA Basic"),
            PaletteEntry(color="Magenta", material="PLA Basic"),
            PaletteEntry(color="Yellow", material="PLA Basic"),
            PaletteEntry(color="Black", material="PLA Basic"),
        ])

        with tempfile.TemporaryDirectory() as tmpdir:
            LUTManager.save_keyed_json(
                _real_path_join(tmpdir, "temp_5c_ext_page_1.json"),
                lut1, np.zeros((50, 5), dtype=np.int32), metadata)
            LUTManager.save_keyed_json(
                _real_path_join(tmpdir, "temp_5c_ext_page_2.json"),
                lut2, np.zeros((70, 5), dtype=np.int32), metadata)
            merged_path = _real_path_join(tmpdir, "lumina_lut.json")

            with (
                patch("api.routers.extractor.os.path.join", side_effect=_make_join_redirector(tmpdir)),
                patch("config.LUT_FILE_PATH", merged_path),
            ):
                response = client.post("/api/extractor/merge-5color-extended")

            assert response.status_code == 200
            merged_rgb, _, _ = LUTManager.load_lut_with_metadata(merged_path)
            assert merged_rgb.shape == (120, 3)
            np.testing.assert_array_equal(merged_rgb[:50], lut1)
            np.testing.assert_array_equal(merged_rgb[50:], lut2)

    def test_merge_preserves_colordb_metadata_from_temp_pages(self) -> None:
        """Merged LUT should preserve manufacturer, type, and palette color_name metadata."""
        from utils.lut_manager import LUTManager
        from config import LUTMetadata, PaletteEntry

        lut1 = np.random.randint(0, 256, (20, 3), dtype=np.uint8)
        lut2 = np.random.randint(0, 256, (30, 3), dtype=np.uint8)
        metadata = LUTMetadata(
            palette=[
                PaletteEntry(color="White", material="PLA Basic", color_name="Jade White"),
                PaletteEntry(color="Cyan", material="PLA Basic", color_name="Ocean Cyan"),
                PaletteEntry(color="Magenta", material="PLA Basic", color_name="Rose Magenta"),
                PaletteEntry(color="Yellow", material="PLA Basic", color_name="Sun Yellow"),
                PaletteEntry(color="Black", material="PLA Basic", color_name="Carbon Black"),
            ],
            manufacturer="Bambu Lab",
            type="PLA Basic",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            LUTManager.save_keyed_json(
                _real_path_join(tmpdir, "temp_5c_ext_page_1.json"),
                lut1,
                np.zeros((20, 5), dtype=np.int32),
                metadata,
            )
            LUTManager.save_keyed_json(
                _real_path_join(tmpdir, "temp_5c_ext_page_2.json"),
                lut2,
                np.zeros((30, 5), dtype=np.int32),
                metadata,
            )
            merged_path = _real_path_join(tmpdir, "lumina_lut.json")

            with (
                patch("api.routers.extractor.os.path.join", side_effect=_make_join_redirector(tmpdir)),
                patch("config.LUT_FILE_PATH", merged_path),
            ):
                response = client.post("/api/extractor/merge-5color-extended")

            assert response.status_code == 200
            _, _, merged_meta = LUTManager.load_lut_with_metadata(merged_path)
            assert merged_meta.manufacturer == "Bambu Lab"
            assert merged_meta.type == "PLA Basic"
            assert [entry.color_name for entry in merged_meta.palette] == [
                "Jade White",
                "Ocean Cyan",
                "Rose Magenta",
                "Sun Yellow",
                "Carbon Black",
            ]


# =========================================================================
# 2. merge-5color-extended endpoint — missing temp files → HTTP 400
#    Requirements: 1.5
# =========================================================================


class TestMerge5ColorExtendedMissingFiles:
    """Verify merge returns 400 when temp page files are missing."""

    def test_missing_both_pages_returns_400(self) -> None:
        """Neither page file exists → HTTP 400."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "api.routers.extractor.os.path.join",
                side_effect=_make_join_redirector(tmpdir),
            ):
                response = client.post("/api/extractor/merge-5color-extended")

        assert response.status_code == 400
        assert "Missing temp pages" in response.json()["detail"]

    def test_missing_page2_returns_400(self) -> None:
        """Only page 1 exists → HTTP 400."""
        lut1 = np.random.randint(0, 256, (50, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmpdir:
            np.save(_real_path_join(tmpdir, "temp_5c_ext_page_1.npy"), lut1)

            with patch(
                "api.routers.extractor.os.path.join",
                side_effect=_make_join_redirector(tmpdir),
            ):
                response = client.post("/api/extractor/merge-5color-extended")

        assert response.status_code == 400
        assert "Missing temp pages" in response.json()["detail"]

    def test_missing_page1_returns_400(self) -> None:
        """Only page 2 exists → HTTP 400."""
        lut2 = np.random.randint(0, 256, (50, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmpdir:
            np.save(_real_path_join(tmpdir, "temp_5c_ext_page_2.npy"), lut2)

            with patch(
                "api.routers.extractor.os.path.join",
                side_effect=_make_join_redirector(tmpdir),
            ):
                response = client.post("/api/extractor/merge-5color-extended")

        assert response.status_code == 400
        assert "Missing temp pages" in response.json()["detail"]


# =========================================================================
# 3. Calibration generation — 5-Color Extended mode
#    Requirements: 3.3, 3.4
# =========================================================================


class TestCalibration5ColorExtended:
    """Verify calibration generate endpoint dispatches to correct core function for 5-Color Extended."""

    def test_5color_extended_routes_to_generate_5color_extended_batch_zip(self) -> None:
        """5-Color Extended (1444) mode dispatches to generate_5color_extended_batch_zip()."""
        mock_return = ("/tmp/fake_5c.zip", _mock_preview, "OK")
        with patch(
            "api.routers.calibration.generate_5color_extended_batch_zip",
            return_value=mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "5-Color Extended (1444)",
                    "block_size": 5,
                    "gap": 0.82,
                    "backing": "White",
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once_with(block_size_mm=5.0, gap_mm=0.82)

    def test_5color_extended_response_contains_download_and_preview_urls(self) -> None:
        """Response should contain download_url and preview_url."""
        mock_return = ("/tmp/fake_5c.zip", _mock_preview, "5-Color Extended OK")
        with patch(
            "api.routers.calibration.generate_5color_extended_batch_zip",
            return_value=mock_return,
        ):
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "5-Color Extended (1444)",
                    "block_size": 5,
                    "gap": 0.82,
                    "backing": "White",
                },
            )
            data = response.json()
            assert data["status"] == "ok"
            assert "/api/files/" in data["download_url"]
            assert "/api/files/" in data["preview_url"]
            assert data["message"] == "5-Color Extended OK"

    def test_5color_extended_core_error_returns_500(self) -> None:
        """Core function exception → HTTP 500."""
        with patch(
            "api.routers.calibration.generate_5color_extended_batch_zip",
            side_effect=RuntimeError("generation failed"),
        ):
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "5-Color Extended (1444)",
                    "block_size": 5,
                    "gap": 0.82,
                    "backing": "White",
                },
            )
            assert response.status_code == 500
            assert "generation failed" in response.json()["detail"]
