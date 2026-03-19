"""Property-Based Tests for Printer Profile Registry and Templates.
打印机配置注册表与模板的 Property-Based 测试。

Uses Hypothesis to verify correctness properties across all printer profiles.
使用 Hypothesis 验证所有打印机配置的正确性属性。
"""

import pytest
from hypothesis import given, assume, settings
from hypothesis import strategies as st

from config import PRINTER_PROFILES, get_printer_profile, DEFAULT_PRINTER_ID
from utils.bambu_3mf_writer import load_printer_template, _PRINTER_TEMPLATE_CACHE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_template_cache():
    """Clear the printer template cache before each test to avoid stale data.
    每个测试前清除模板缓存，避免脏数据。
    """
    _PRINTER_TEMPLATE_CACHE.clear()
    yield
    _PRINTER_TEMPLATE_CACHE.clear()


# ---------------------------------------------------------------------------
# P1: 打印机注册表完整性 (Registry Integrity)
# ---------------------------------------------------------------------------

class TestP1RegistryIntegrity:
    """**Validates: Requirements 4.1**

    For any printer in the registry, it must have all required metadata fields
    and positive physical dimensions.
    """

    @given(profile=st.sampled_from(list(PRINTER_PROFILES.values())))
    def test_all_required_fields_present(self, profile):
        """Every printer profile has all required metadata fields.
        每个打印机配置必须包含所有必需的元数据字段。

        **Validates: Requirements 4.1**
        """
        assert isinstance(profile.id, str) and len(profile.id) > 0
        assert isinstance(profile.display_name, str) and len(profile.display_name) > 0
        assert isinstance(profile.bed_width, int)
        assert isinstance(profile.bed_depth, int)
        assert isinstance(profile.bed_height, int)
        assert isinstance(profile.nozzle_count, int)

    @given(profile=st.sampled_from(list(PRINTER_PROFILES.values())))
    def test_physical_dimensions_positive(self, profile):
        """Bed dimensions must be positive and nozzle count >= 1.
        打印床尺寸必须为正值，喷头数量 >= 1。

        **Validates: Requirements 4.1**
        """
        assert profile.bed_width > 0, f"{profile.id}: bed_width must be > 0"
        assert profile.bed_depth > 0, f"{profile.id}: bed_depth must be > 0"
        assert profile.bed_height > 0, f"{profile.id}: bed_height must be > 0"
        assert profile.nozzle_count >= 1, f"{profile.id}: nozzle_count must be >= 1"


# ---------------------------------------------------------------------------
# P2: 模板加载一致性 (Template Loading Consistency)
# ---------------------------------------------------------------------------

class TestP2TemplateLoadingConsistency:
    """**Validates: Requirements 3.1, 3.2**

    For any printer ID in the registry, load_printer_template returns a JSON
    where printer_model matches the registry's display_name.
    """

    @given(printer_id=st.sampled_from(list(PRINTER_PROFILES.keys())))
    @settings(max_examples=len(PRINTER_PROFILES))
    def test_template_printer_model_matches_display_name(self, printer_id):
        """Template printer_model must match registry display_name.
        模板中的 printer_model 必须与注册表中的 display_name 一致。

        **Validates: Requirements 3.1, 3.2**
        """
        profile = PRINTER_PROFILES[printer_id]
        template = load_printer_template(printer_id)

        assert "printer_model" in template, (
            f"Template for '{printer_id}' missing 'printer_model' field"
        )
        assert template["printer_model"] == profile.display_name, (
            f"Template printer_model '{template['printer_model']}' != "
            f"registry display_name '{profile.display_name}' for '{printer_id}'"
        )


# ---------------------------------------------------------------------------
# P3: 无效机型回退 (Invalid Printer ID Fallback)
# ---------------------------------------------------------------------------

class TestP3InvalidPrinterFallback:
    """**Validates: Requirements 2.3**

    For any string NOT in the registry, get_printer_profile must return
    the default printer (H2D).
    """

    @given(s=st.text(min_size=1, max_size=50))
    def test_unknown_id_returns_default(self, s):
        """Any unknown printer ID must fall back to default H2D.
        任何未知的打印机 ID 必须回退到默认机型 H2D。

        **Validates: Requirements 2.3**
        """
        assume(s not in PRINTER_PROFILES)

        result = get_printer_profile(s)
        assert result.id == DEFAULT_PRINTER_ID, (
            f"get_printer_profile('{s}') returned '{result.id}', "
            f"expected default '{DEFAULT_PRINTER_ID}'"
        )


# ---------------------------------------------------------------------------
# P4: 打印床尺寸一致性 (Bed Size Consistency)
# ---------------------------------------------------------------------------

class TestP4BedSizeConsistency:
    """**Validates: Requirements 3.3, 7.1**

    For any printer in the registry, the template's printable_area parsed
    width and depth must match the registry's bed_width and bed_depth.
    """

    @given(printer_id=st.sampled_from(list(PRINTER_PROFILES.keys())))
    @settings(max_examples=len(PRINTER_PROFILES))
    def test_printable_area_matches_bed_dimensions(self, printer_id):
        """Template printable_area dimensions must match registry bed size.
        模板中 printable_area 的尺寸必须与注册表中的打印床尺寸一致。

        **Validates: Requirements 3.3, 7.1**
        """
        profile = PRINTER_PROFILES[printer_id]
        template = load_printer_template(printer_id)

        assert "printable_area" in template, (
            f"Template for '{printer_id}' missing 'printable_area' field"
        )

        # printable_area format: ["0x0", "WIDTHx0", "WIDTHxDEPTH", "0xDEPTH"]
        # Some printers use float offsets (e.g. "0.5x1", "270.5x271")
        # so we parse as float and compute span from min/max coordinates.
        area = template["printable_area"]
        assert len(area) == 4, (
            f"printable_area for '{printer_id}' has {len(area)} points, expected 4"
        )

        xs = [float(pt.split("x")[0]) for pt in area]
        ys = [float(pt.split("x")[1]) for pt in area]
        parsed_width = round(max(xs) - min(xs))
        parsed_depth = round(max(ys) - min(ys))

        assert parsed_width == profile.bed_width, (
            f"printable_area width {parsed_width} != registry bed_width "
            f"{profile.bed_width} for '{printer_id}'"
        )
        assert parsed_depth == profile.bed_depth, (
            f"printable_area depth {parsed_depth} != registry bed_depth "
            f"{profile.bed_depth} for '{printer_id}'"
        )
