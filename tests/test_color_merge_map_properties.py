"""Property-based tests for ColorMerger.build_merge_map() consistency.

**Validates: Requirements 7.1, 7.2**

Property 9: Color merge map consistency
For all merge_map = build_merge_map(palette, threshold, max_distance),
  for all (src, tgt) in merge_map:
    src != tgt                          (source and target differ)
    tgt not in low_usage_colors         (target is a high-usage color)
    (tgt, src) not in merge_map         (no cycles / reverse mappings)
"""

from __future__ import annotations

from typing import List, Tuple

import cv2
import numpy as np
import hypothesis.strategies as st
from hypothesis import given, settings

from core.color_merger import ColorMerger


# ---------------------------------------------------------------------------
# Helper: RGB to LAB conversion using OpenCV
# ---------------------------------------------------------------------------

def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
    """Convert RGB uint8 array (N,3) to LAB float64 array (N,3)."""
    rgb_2d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
    lab_2d = cv2.cvtColor(rgb_2d, cv2.COLOR_RGB2LAB)
    return lab_2d.reshape(-1, 3).astype(np.float64)


# ---------------------------------------------------------------------------
# Hypothesis strategy: random palette with 2-10 unique colors
# ---------------------------------------------------------------------------

@st.composite
def st_palette(draw: st.DrawFn) -> List[dict]:
    """Generate a random color palette with 2-10 unique colors."""
    n = draw(st.integers(min_value=2, max_value=10))
    colors: List[Tuple[int, int, int]] = []
    for _ in range(n):
        r = draw(st.integers(0, 255))
        g = draw(st.integers(0, 255))
        b = draw(st.integers(0, 255))
        colors.append((r, g, b))

    # Deduplicate
    unique_colors = list(dict.fromkeys(colors))
    if len(unique_colors) < 2:
        alt = ((unique_colors[0][0] + 128) % 256,
               unique_colors[0][1],
               unique_colors[0][2])
        unique_colors.append(alt)

    # Random percentages, normalized to sum to 100
    raw_pcts = [
        draw(st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False))
        for _ in unique_colors
    ]
    total = sum(raw_pcts)
    pcts = [p / total * 100.0 for p in raw_pcts]

    palette: List[dict] = []
    for (r, g, b), pct in zip(unique_colors, pcts):
        palette.append({
            "hex": f"#{r:02x}{g:02x}{b:02x}",
            "color": (r, g, b),
            "percentage": round(pct, 2),
            "count": max(1, int(pct * 10)),
        })
    return palette


# ---------------------------------------------------------------------------
# Property 9 test
# ---------------------------------------------------------------------------

class TestMergeMapConsistency:
    """Property 9: merge_map structural invariants."""

    @given(
        palette=st_palette(),
        threshold_percent=st.floats(min_value=0.1, max_value=5.0,
                                    allow_nan=False, allow_infinity=False),
        max_distance=st.floats(min_value=5.0, max_value=50.0,
                               allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_merge_map_invariants(
        self,
        palette: List[dict],
        threshold_percent: float,
        max_distance: float,
    ) -> None:
        """**Validates: Requirements 7.1, 7.2**

        For every (src, tgt) in merge_map:
          1. src != tgt
          2. tgt is NOT a low-usage color
          3. No reverse mapping (tgt, src) exists (no cycles)
        """
        merger = ColorMerger(_rgb_to_lab)
        merge_map = merger.build_merge_map(palette, threshold_percent, max_distance)

        # Clamped threshold (same logic as build_merge_map)
        clamped_threshold = max(0.1, min(5.0, threshold_percent))
        low_usage = set(merger.identify_low_usage_colors(palette, clamped_threshold))

        for src, tgt in merge_map.items():
            # 1. Source and target must differ
            assert src != tgt, (
                f"Source equals target: {src} -> {tgt}"
            )

            # 2. Target must NOT be a low-usage color
            assert tgt not in low_usage, (
                f"Target {tgt} is in low_usage set {low_usage}"
            )

            # 3. No reverse mapping (no cycles)
            assert merge_map.get(tgt) != src, (
                f"Cycle detected: {src} -> {tgt} and {tgt} -> {src}"
            )
