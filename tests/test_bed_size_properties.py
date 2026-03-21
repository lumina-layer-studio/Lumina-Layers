"""Property-based tests for BedManager (config.py).

Uses Hypothesis to verify correctness properties across arbitrary inputs.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from config import BedManager


# ---------------------------------------------------------------------------
# Feature: bed-size-selector, Property 1: compute_scale 缩放计算正确性
# **Validates: Requirements 4.2**
# ---------------------------------------------------------------------------

@given(
    width_mm=st.integers(min_value=1, max_value=10_000),
    height_mm=st.integers(min_value=1, max_value=10_000),
)
@settings(max_examples=200)
def test_compute_scale_equals_target_over_max(width_mm: int, height_mm: int) -> None:
    """Property 1: For any positive integers (width_mm, height_mm),
    BedManager.compute_scale returns _TARGET_CANVAS_PX / max(width_mm, height_mm).

    **Validates: Requirements 4.2**
    """
    expected = BedManager._TARGET_CANVAS_PX / max(width_mm, height_mm)
    result = BedManager.compute_scale(width_mm, height_mm)
    assert result == expected, (
        f"compute_scale({width_mm}, {height_mm}) = {result}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# Feature: bed-size-selector, Property 3: 无效热床标签拒绝
# **Validates: Requirements 1.4**
# ---------------------------------------------------------------------------

# Collect valid labels from BedManager.BEDS and printer profiles for filtering
_VALID_BED_LABELS = {label for label, _, _ in BedManager.BEDS}


@given(label=st.text(min_size=0, max_size=200))
@settings(max_examples=200)
def test_invalid_bed_label_returns_fallback(label: str) -> None:
    """Property 3: For any string NOT in BedManager.BEDS label list or printer display names,
    get_bed_size() should return the fallback value (256, 256).

    **Validates: Requirements 1.4**
    """
    from hypothesis import assume
    from config import PRINTER_PROFILES

    # Collect valid printer display names
    valid_printer_names = {profile.display_name for profile in PRINTER_PROFILES.values()}
    
    # Assume label is neither a bed size nor a printer name
    assume(label not in _VALID_BED_LABELS)
    assume(label not in valid_printer_names)

    result = BedManager.get_bed_size(label)
    assert result == (256, 256), (
        f"get_bed_size({label!r}) = {result}, expected (256, 256)"
    )


# ---------------------------------------------------------------------------
# Feature: bed-size-selector, Property 4: 打印机型号热床尺寸正确性
# **Validates: Requirements 1.5**
# ---------------------------------------------------------------------------

@given(profile=st.sampled_from(list(BedManager.get_all_bed_options())))
@settings(max_examples=50)
def test_printer_model_bed_size_matches_profile(profile: tuple) -> None:
    """Property 4: For any printer model in get_all_bed_options(),
    get_bed_size(display_name) should return the correct (bed_width, bed_depth).

    **Validates: Requirements 1.5**
    """
    label, expected_width, expected_height, printer_id = profile
    
    result = BedManager.get_bed_size(label)
    assert result == (expected_width, expected_height), (
        f"get_bed_size({label!r}) = {result}, expected ({expected_width}, {expected_height})"
    )
