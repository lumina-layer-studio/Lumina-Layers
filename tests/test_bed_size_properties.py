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

# Collect valid labels from BedManager.BEDS for filtering
_VALID_BED_LABELS = {label for label, _, _ in BedManager.BEDS}


@given(label=st.text(min_size=0, max_size=200))
@settings(max_examples=200)
def test_invalid_bed_label_returns_fallback(label: str) -> None:
    """Property 3: For any string NOT in BedManager.BEDS label list,
    get_bed_size() should return the fallback value (256, 256).

    **Validates: Requirements 1.4**
    """
    from hypothesis import assume

    assume(label not in _VALID_BED_LABELS)

    result = BedManager.get_bed_size(label)
    assert result == (256, 256), (
        f"get_bed_size({label!r}) = {result}, expected (256, 256)"
    )
