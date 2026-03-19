"""Unit tests for printer profile registry and template loading.
打印机配置注册表与模板加载单元测试。

Covers:
  - Task 7.1: Registry queries, default fallback, template loading
  - Task 7.2: 3MF export uses correct template (printer_model key, cache)
"""

import pytest

from config import (
    PrinterProfile,
    PRINTER_PROFILES,
    DEFAULT_PRINTER_ID,
    get_printer_profile,
    list_printer_profiles,
)
from utils.bambu_3mf_writer import load_printer_template, _PRINTER_TEMPLATE_CACHE


# ── Required fields every PrinterProfile must have ──

REQUIRED_FIELDS = (
    "id", "display_name", "brand",
    "bed_width", "bed_depth", "bed_height",
    "nozzle_count", "is_dual_head", "template_file",
)


# ====================================================================
# Task 7.1 — Registry queries, default fallback, template loading
# ====================================================================


class TestListPrinterProfiles:
    """list_printer_profiles() returns all registered printers."""

    def test_returns_all_printers(self) -> None:
        profiles = list_printer_profiles()
        assert len(profiles) == len(PRINTER_PROFILES)

    def test_returns_list_of_printer_profiles(self) -> None:
        profiles = list_printer_profiles()
        for p in profiles:
            assert isinstance(p, PrinterProfile)


class TestGetPrinterProfile:
    """get_printer_profile() returns correct profile or falls back."""

    def test_h2d_returns_correct_profile(self) -> None:
        profile = get_printer_profile("bambu-h2d")
        assert profile.id == "bambu-h2d"
        assert profile.display_name == "Bambu Lab H2D"
        assert profile.bed_width == 350
        assert profile.bed_depth == 320
        assert profile.bed_height == 325
        assert profile.nozzle_count == 2
        assert profile.is_dual_head is True

    def test_invalid_id_falls_back_to_h2d(self) -> None:
        profile = get_printer_profile("invalid-id")
        assert profile.id == DEFAULT_PRINTER_ID
        assert profile.id == "bambu-h2d"

    def test_a1_mini_returns_correct_profile(self) -> None:
        profile = get_printer_profile("bambu-a1-mini")
        assert profile.id == "bambu-a1-mini"
        assert profile.display_name == "Bambu Lab A1 mini"
        assert profile.bed_width == 180
        assert profile.bed_depth == 180
        assert profile.bed_height == 180
        assert profile.nozzle_count == 1
        assert profile.is_dual_head is False


class TestProfileRequiredFields:
    """Every profile has all required fields."""

    @pytest.mark.parametrize("printer_id", list(PRINTER_PROFILES.keys()))
    def test_profile_has_all_required_fields(self, printer_id: str) -> None:
        profile = PRINTER_PROFILES[printer_id]
        for field in REQUIRED_FIELDS:
            assert hasattr(profile, field), f"{printer_id} missing field: {field}"
            assert getattr(profile, field) is not None, f"{printer_id}.{field} is None"


class TestLoadPrinterTemplate:
    """load_printer_template() returns non-empty dicts."""

    def test_h2d_template_non_empty(self) -> None:
        template = load_printer_template("bambu-h2d")
        assert isinstance(template, dict)
        assert len(template) > 0

    def test_a1_mini_template_non_empty(self) -> None:
        template = load_printer_template("bambu-a1-mini")
        assert isinstance(template, dict)
        assert len(template) > 0


# ====================================================================
# Task 7.2 — 3MF export uses correct template
# ====================================================================


class TestTemplatePrinterModelKey:
    """Templates contain correct printer_model key."""

    def test_h2d_template_has_printer_model(self) -> None:
        template = load_printer_template("bambu-h2d")
        assert "printer_model" in template

    def test_p1s_template_has_correct_printer_model(self) -> None:
        template = load_printer_template("bambu-p1s")
        assert "printer_model" in template
        # The template's printer_model should identify the P1S
        assert "P1S" in template["printer_model"]

    def test_invalid_id_falls_back_to_valid_template(self) -> None:
        template = load_printer_template("invalid-id")
        assert isinstance(template, dict)
        assert len(template) > 0


class TestTemplateCache:
    """Template cache returns same data on repeated calls."""

    def test_cache_returns_same_data(self) -> None:
        first = load_printer_template("bambu-h2d")
        second = load_printer_template("bambu-h2d")
        assert first == second
