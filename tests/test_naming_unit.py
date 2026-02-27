"""Unit tests for Naming_Service (core/naming.py).

Validates specific examples, mode/color mappings, and edge cases.
Requirements: 3.1-3.7
"""

import re
from unittest.mock import patch

import pytest

from config import ModelingMode
from core.naming import (
    COLOR_MODE_TAGS,
    MODELING_MODE_TAGS,
    _sanitize,
    generate_batch_filename,
    generate_calibration_filename,
    generate_model_filename,
    generate_preview_filename,
    parse_filename,
)

# Timestamp pattern used across tests
TS_RE = r"\d{8}_\d{6}"


# =========================================================================
# 1. ModelingMode enum → tag mapping (Requirements 3.1, 3.2, 3.3)
# =========================================================================

class TestModelingModeTags:
    """Verify every ModelingMode enum value maps to the correct tag."""

    def test_high_fidelity_maps_to_hifi(self):
        assert MODELING_MODE_TAGS[ModelingMode.HIGH_FIDELITY] == "HiFi"

    def test_pixel_maps_to_pixel(self):
        assert MODELING_MODE_TAGS[ModelingMode.PIXEL] == "Pixel"

    def test_vector_maps_to_vector(self):
        assert MODELING_MODE_TAGS[ModelingMode.VECTOR] == "Vector"

    def test_all_enum_members_have_mapping(self):
        for mode in ModelingMode:
            assert mode in MODELING_MODE_TAGS, f"{mode} missing from MODELING_MODE_TAGS"


# =========================================================================
# 2. Color mode string → tag mapping (Requirements 3.4, 3.5, 3.6, 3.7)
# =========================================================================

class TestColorModeTags:
    """Verify every known color mode string maps to the correct tag."""

    @pytest.mark.parametrize("color_mode", ["4-Color", "CMYW", "RYBW"])
    def test_4color_variants_map_to_4c(self, color_mode):
        assert COLOR_MODE_TAGS[color_mode] == "4C"

    def test_6color_maps_to_6c(self):
        assert COLOR_MODE_TAGS["6-Color"] == "6C"

    @pytest.mark.parametrize("color_mode", ["8-Color Max", "8-Color"])
    def test_8color_variants_map_to_8c(self, color_mode):
        assert COLOR_MODE_TAGS[color_mode] == "8C"

    @pytest.mark.parametrize("color_mode", ["BW", "BW (Black & White)"])
    def test_bw_variants_map_to_bw(self, color_mode):
        assert COLOR_MODE_TAGS[color_mode] == "BW"


# =========================================================================
# 3. Edge cases (Requirements 3.1-3.7, 4.5)
# =========================================================================

class TestEdgeCases:
    """Edge cases: empty strings, special characters, unicode, unknown modes."""

    def test_empty_base_name_uses_untitled(self):
        filename = generate_model_filename("", ModelingMode.PIXEL, "4-Color")
        assert filename.startswith("untitled_Lumina_")

    def test_whitespace_only_base_name_uses_untitled(self):
        filename = generate_model_filename("   ", ModelingMode.PIXEL, "BW")
        assert filename.startswith("untitled_Lumina_")

    def test_special_characters_sanitized(self):
        filename = generate_model_filename(
            'my<file>:name', ModelingMode.HIGH_FIDELITY, "6-Color"
        )
        # Forbidden chars replaced with underscores
        assert "<" not in filename
        assert ">" not in filename
        assert ":" not in filename

    def test_all_forbidden_chars_sanitized(self):
        forbidden = '<>:"/\\|?*'
        filename = generate_model_filename(
            f"test{forbidden}name", ModelingMode.PIXEL, "BW"
        )
        for ch in forbidden:
            assert ch not in filename

    def test_unicode_base_name(self):
        filename = generate_model_filename("日本語テスト", ModelingMode.VECTOR, "4-Color")
        assert "日本語テスト" in filename
        assert "_Lumina_Vector_4C_" in filename

    def test_unicode_emoji_base_name(self):
        filename = generate_model_filename("🎨art", ModelingMode.PIXEL, "BW")
        assert "_Lumina_Pixel_BW_" in filename

    def test_unknown_modeling_mode_uses_unknown(self):
        # Simulate an unknown mode by passing a value not in the mapping
        # We use a mock enum value that isn't in MODELING_MODE_TAGS
        filename = generate_model_filename("test", "not_a_real_mode", "4-Color")
        assert "_Unknown_" in filename

    def test_unknown_color_mode_uses_unknown(self):
        filename = generate_model_filename("test", ModelingMode.PIXEL, "NonExistent")
        assert "_Unknown_" in filename

    def test_sanitize_preserves_normal_chars(self):
        assert _sanitize("hello_world-123") == "hello_world-123"

    def test_sanitize_replaces_forbidden(self):
        result = _sanitize('a<b>c:d"e/f\\g|h?i*j')
        assert result == "a_b_c_d_e_f_g_h_i_j"


# =========================================================================
# 4. Generated filenames contain correct mode and color tags
# =========================================================================

FIXED_TS = "20250101_120000"


class TestGeneratedFilenameFormat:
    """Verify generated filenames contain the correct mode/color tags and structure."""

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_model_filename_structure(self, _mock_ts):
        result = generate_model_filename(
            "photo", ModelingMode.HIGH_FIDELITY, "4-Color"
        )
        assert result == f"photo_Lumina_HiFi_4C_{FIXED_TS}.3mf"

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_model_filename_pixel_6c(self, _mock_ts):
        result = generate_model_filename("img", ModelingMode.PIXEL, "6-Color")
        assert result == f"img_Lumina_Pixel_6C_{FIXED_TS}.3mf"

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_model_filename_vector_8c(self, _mock_ts):
        result = generate_model_filename(
            "design", ModelingMode.VECTOR, "8-Color Max"
        )
        assert result == f"design_Lumina_Vector_8C_{FIXED_TS}.3mf"

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_model_filename_bw(self, _mock_ts):
        result = generate_model_filename("sketch", ModelingMode.PIXEL, "BW")
        assert result == f"sketch_Lumina_Pixel_BW_{FIXED_TS}.3mf"

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_preview_filename_structure(self, _mock_ts):
        result = generate_preview_filename("photo")
        assert result == f"photo_Preview_{FIXED_TS}.glb"

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_calibration_filename_structure(self, _mock_ts):
        result = generate_calibration_filename("4-Color", "Standard")
        assert result == f"Lumina_Calibration_Standard_4C_{FIXED_TS}.3mf"

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_batch_filename_structure(self, _mock_ts):
        result = generate_batch_filename()
        assert result == f"Lumina_Batch_{FIXED_TS}.zip"

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_custom_extension(self, _mock_ts):
        result = generate_model_filename(
            "test", ModelingMode.PIXEL, "BW", extension=".stl"
        )
        assert result.endswith(".stl")

    def test_model_filename_matches_regex(self):
        pattern = re.compile(
            rf"^.+_Lumina_(HiFi|Pixel|Vector)_(4C|6C|8C|BW)_{TS_RE}\.3mf$"
        )
        for mode in ModelingMode:
            for color in ["4-Color", "6-Color", "8-Color Max", "BW"]:
                filename = generate_model_filename("test", mode, color)
                assert pattern.match(filename), f"No match: {filename}"


# =========================================================================
# 5. parse_filename edge cases
# =========================================================================

class TestParseFilename:
    """Verify parse_filename handles standard and non-standard inputs."""

    def test_parse_returns_none_for_empty_string(self):
        assert parse_filename("") is None

    def test_parse_returns_none_for_random_string(self):
        assert parse_filename("random_file.txt") is None

    def test_parse_returns_none_for_none_input(self):
        assert parse_filename(None) is None

    def test_parse_returns_none_for_non_string(self):
        assert parse_filename(12345) is None

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_parse_model_filename(self, _mock_ts):
        filename = generate_model_filename("photo", ModelingMode.HIGH_FIDELITY, "4-Color")
        parsed = parse_filename(filename)
        assert parsed is not None
        assert parsed["base_name"] == "photo"
        assert parsed["modeling_mode"] == "HiFi"
        assert parsed["color_mode"] == "4C"
        assert parsed["timestamp"] == FIXED_TS
        assert parsed["file_type"] == "model"

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_parse_preview_filename(self, _mock_ts):
        filename = generate_preview_filename("photo")
        parsed = parse_filename(filename)
        assert parsed is not None
        assert parsed["base_name"] == "photo"
        assert parsed["file_type"] == "preview"

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_parse_calibration_filename(self, _mock_ts):
        filename = generate_calibration_filename("6-Color", "Standard")
        parsed = parse_filename(filename)
        assert parsed is not None
        assert parsed["color_mode"] == "6C"
        assert parsed["file_type"] == "calibration"

    @patch("core.naming._get_timestamp", return_value=FIXED_TS)
    def test_parse_batch_filename(self, _mock_ts):
        filename = generate_batch_filename()
        parsed = parse_filename(filename)
        assert parsed is not None
        assert parsed["file_type"] == "batch"
