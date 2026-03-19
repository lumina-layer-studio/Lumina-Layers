"""Unit tests for LUTMerger subtype detection with metadata priority.
LUTMerger 子类型检测与 metadata 优先级单元测试。

Tests _detect_4color_subtype and _detect_6color_subtype behavior
with and without metadata, verifying metadata takes priority over filename.

Requirements: 5.1, 5.2, 5.3, 5.4
"""

import pytest
from config import LUTMetadata
from core.lut_merger import _detect_4color_subtype, _detect_6color_subtype


# ---------------------------------------------------------------------------
# _detect_4color_subtype tests
# ---------------------------------------------------------------------------

class TestDetect4ColorSubtype:
    """Tests for _detect_4color_subtype."""

    def test_metadata_rybw_returns_rybw(self):
        """Metadata containing '4-Color (RYBW)' → returns '4-Color-RYBW'."""
        meta = LUTMetadata(color_mode="4-Color (RYBW)")
        result = _detect_4color_subtype("/any/path/lut.npy", metadata=meta)
        assert result == "4-Color-RYBW"

    def test_metadata_cmyw_returns_cmyw(self):
        """Metadata containing '4-Color (CMYW)' → returns '4-Color-CMYW'."""
        meta = LUTMetadata(color_mode="4-Color (CMYW)")
        result = _detect_4color_subtype("/any/path/lut.npy", metadata=meta)
        assert result == "4-Color-CMYW"

    def test_no_metadata_filename_cmyw_returns_cmyw(self):
        """No metadata, filename contains 'CMYW' → returns '4-Color-CMYW'."""
        result = _detect_4color_subtype("/some/path/my_CMYW_lut.npy")
        assert result == "4-Color-CMYW"

    def test_no_metadata_filename_no_cmyw_returns_rybw_default(self):
        """No metadata, filename without 'CMYW' → returns '4-Color-RYBW' (default)."""
        result = _detect_4color_subtype("/some/path/generic_lut.npy")
        assert result == "4-Color-RYBW"

    def test_metadata_rybw_overrides_cmyw_filename(self):
        """Metadata says RYBW but filename says CMYW → metadata wins."""
        meta = LUTMetadata(color_mode="4-Color (RYBW)")
        result = _detect_4color_subtype("/path/CMYW_calibration.npy", metadata=meta)
        assert result == "4-Color-RYBW"


# ---------------------------------------------------------------------------
# _detect_6color_subtype tests
# ---------------------------------------------------------------------------

class TestDetect6ColorSubtype:
    """Tests for _detect_6color_subtype."""

    def test_metadata_rybw_returns_rybwgk(self):
        """Metadata containing '6-Color (RYBW 1296)' → returns '6-Color-RYBWGK'."""
        meta = LUTMetadata(color_mode="6-Color (RYBW 1296)")
        result = _detect_6color_subtype("/any/path/lut.npy", metadata=meta)
        assert result == "6-Color-RYBWGK"

    def test_metadata_cmyw_returns_cmywgk(self):
        """Metadata containing '6-Color (Smart 1296)' → returns '6-Color-CMYWGK'."""
        meta = LUTMetadata(color_mode="6-Color (Smart 1296)")
        result = _detect_6color_subtype("/any/path/lut.npy", metadata=meta)
        assert result == "6-Color-CMYWGK"

    def test_no_metadata_filename_rybw_returns_rybwgk(self):
        """No metadata, filename contains 'RYBW' → returns '6-Color-RYBWGK'."""
        result = _detect_6color_subtype("/some/path/my_RYBW_lut.npy")
        assert result == "6-Color-RYBWGK"

    def test_no_metadata_filename_no_rybw_returns_cmywgk_default(self):
        """No metadata, filename without 'RYBW' → returns '6-Color-CMYWGK' (default)."""
        result = _detect_6color_subtype("/some/path/generic_lut.npy")
        assert result == "6-Color-CMYWGK"

    def test_metadata_rybw_overrides_non_rybw_filename(self):
        """Metadata says RYBW but filename has no RYBW → metadata wins."""
        meta = LUTMetadata(color_mode="6-Color (RYBW 1296)")
        result = _detect_6color_subtype("/path/smart_1296_lut.npy", metadata=meta)
        assert result == "6-Color-RYBWGK"


# ---------------------------------------------------------------------------
# 向后兼容性：旧格式 LUT 文件加载兼容性测试
# Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
# ---------------------------------------------------------------------------

import json
import os
import tempfile
import numpy as np
from utils.lut_manager import LUTManager


def _write_temp_json(data: dict | list) -> str:
    """Write data to a temporary JSON file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


class TestOldFormatLUTLoadCompatibility:
    """Tests for backward compatibility with old LUT files lacking color_mode."""

    # --- Requirement 7.1: old JSON without color_mode loads with None ---

    def test_old_json_without_color_mode_loads_metadata_none(self):
        """Loading old keyed JSON without color_mode → metadata.color_mode is None."""
        data = {
            "palette": {
                "White": {"material": "PLA Basic"},
                "Red": {"material": "PLA Basic"},
                "Yellow": {"material": "PLA Basic"},
                "Blue": {"material": "PLA Basic"},
            },
            "max_color_layers": 5,
            "entries": [{"rgb": [255, 255, 255], "recipe": ["White"]}],
        }
        path = _write_temp_json(data)
        try:
            _rgb, _stacks, metadata = LUTManager._load_keyed_json(path, "test_lut")
            assert metadata.color_mode is None
        finally:
            os.unlink(path)

    # --- Requirement 7.3: old 1024-entry RYBW palette → "4-Color (RYBW)" ---

    def test_old_1024_rybw_palette_inferred_as_rybw(self):
        """Old 1024-entry LUT with RYBW palette → inferred as '4-Color (RYBW)'."""
        entries = [{"rgb": [i, i, i], "recipe": ["White"]} for i in range(1024)]
        data = {
            "palette": {
                "White": {"material": "PLA Basic"},
                "Red": {"material": "PLA Basic"},
                "Yellow": {"material": "PLA Basic"},
                "Blue": {"material": "PLA Basic"},
            },
            "entries": entries,
        }
        path = _write_temp_json(data)
        try:
            result = LUTManager._infer_color_mode_from_json(path)
            assert result == "4-Color (RYBW)"
        finally:
            os.unlink(path)

    # --- Requirement 7.4: old 1024-entry CMYW palette → "4-Color (CMYW)" ---

    def test_old_1024_cmyw_palette_inferred_as_cmyw(self):
        """Old 1024-entry LUT with CMYW palette → inferred as '4-Color (CMYW)'."""
        entries = [{"rgb": [i, i, i], "recipe": ["White"]} for i in range(1024)]
        data = {
            "palette": {
                "White": {"material": "PLA Basic"},
                "Cyan": {"material": "PLA Basic"},
                "Magenta": {"material": "PLA Basic"},
                "Yellow": {"material": "PLA Basic"},
            },
            "entries": entries,
        }
        path = _write_temp_json(data)
        try:
            result = LUTManager._infer_color_mode_from_json(path)
            assert result == "4-Color (CMYW)"
        finally:
            os.unlink(path)

    # --- Requirement 7.5: old 1296-entry RYBW 6-color → "6-Color (RYBW 1296)" ---

    def test_old_1296_rybw_palette_inferred_as_6color_rybw(self):
        """Old 1296-entry LUT with RYBW 6-color palette → inferred as '6-Color (RYBW 1296)'."""
        entries = [{"rgb": [0, 0, 0], "recipe": ["White"]} for _ in range(1296)]
        data = {
            "palette": {
                "White": {"material": "PLA Basic"},
                "Red": {"material": "PLA Basic"},
                "Yellow": {"material": "PLA Basic"},
                "Blue": {"material": "PLA Basic"},
                "Green": {"material": "PLA Basic"},
                "Black": {"material": "PLA Basic"},
            },
            "entries": entries,
        }
        path = _write_temp_json(data)
        try:
            result = LUTManager._infer_color_mode_from_json(path)
            assert result == "6-Color (RYBW 1296)"
        finally:
            os.unlink(path)

    # --- Requirement 7.6: old 1296-entry CMYW 6-color → "6-Color (Smart 1296)" ---

    def test_old_1296_cmyw_palette_inferred_as_6color_smart(self):
        """Old 1296-entry LUT with CMYW 6-color palette → inferred as '6-Color (Smart 1296)'."""
        entries = [{"rgb": [0, 0, 0], "recipe": ["White"]} for _ in range(1296)]
        data = {
            "palette": {
                "White": {"material": "PLA Basic"},
                "Cyan": {"material": "PLA Basic"},
                "Magenta": {"material": "PLA Basic"},
                "Green": {"material": "PLA Basic"},
                "Yellow": {"material": "PLA Basic"},
                "Black": {"material": "PLA Basic"},
            },
            "entries": entries,
        }
        path = _write_temp_json(data)
        try:
            result = LUTManager._infer_color_mode_from_json(path)
            assert result == "6-Color (Smart 1296)"
        finally:
            os.unlink(path)

    # --- Requirement 7.2: old 32-entry LUT → "BW (Black & White)" ---

    def test_old_32_entry_inferred_as_bw(self):
        """Old 32-entry LUT → inferred as 'BW (Black & White)'."""
        entries = [{"rgb": [i * 8, i * 8, i * 8], "recipe": ["White"]} for i in range(32)]
        data = {
            "palette": {
                "White": {"material": "PLA Basic"},
                "Black": {"material": "PLA Basic"},
            },
            "entries": entries,
        }
        path = _write_temp_json(data)
        try:
            result = LUTManager._infer_color_mode_from_json(path)
            assert result == "BW (Black & White)"
        finally:
            os.unlink(path)

    # --- Requirement 7.7: flat-list format (no palette) → size-based inference ---

    def test_flat_list_1024_uses_size_based_inference(self):
        """Old flat-list JSON (top-level array, no palette info) with 1024 entries → 'Merged'.

        Flat-list format is a top-level array with no palette dict. Since 1024
        was removed from _JSON_SIZE_TO_MODE (ambiguous between RYBW/CMYW) and
        flat-list has no palette to inspect, it falls through to 'Merged'.
        """
        data = [
            {"rgb": [i, i, i], "recipe": ["White", "Air", "Air", "Air", "Air"]}
            for i in range(1024)
        ]
        path = _write_temp_json(data)
        try:
            result = LUTManager._infer_color_mode_from_json(path)
            assert result == "Merged"
        finally:
            os.unlink(path)

    def test_flat_list_32_uses_size_based_inference(self):
        """Old flat-list JSON with 32 entries → BW."""
        data = [
            {"rgb": [i * 8, i * 8, i * 8], "recipe": ["White", "Black"]}
            for i in range(32)
        ]
        path = _write_temp_json(data)
        try:
            result = LUTManager._infer_color_mode_from_json(path)
            assert result == "BW (Black & White)"
        finally:
            os.unlink(path)
