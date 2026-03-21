"""Property-based tests for LUT API endpoints.

Feature: lut-manager-merger

Property 6: LUT Info API 往返一致性
  **Validates: Requirements 2.4**

Property 7: 合并统计一致性（后端）
  **Validates: Requirements 6.5, 6.6**
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
from hypothesis import given, settings, assume
import hypothesis.strategies as st
import pytest

from core.lut_merger import LUTMerger


# ═══════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════

VALID_MODES = ["BW", "4-Color", "6-Color", "8-Color", "Merged"]
HIGH_MODES = ["6-Color", "8-Color"]
LOW_MODES = ["BW", "4-Color"]


@st.composite
def rgb_array_st(draw: st.DrawFn, min_size: int = 2, max_size: int = 30) -> np.ndarray:
    """Generate a deterministic RGB array via Hypothesis."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    data = draw(
        st.lists(
            st.tuples(
                st.integers(0, 255),
                st.integers(0, 255),
                st.integers(0, 255),
            ),
            min_size=n,
            max_size=n,
        )
    )
    return np.array(data, dtype=np.uint8)


@st.composite
def stacks_for_rgb(draw: st.DrawFn, rgb: np.ndarray, max_id: int = 7) -> np.ndarray:
    """Generate a stacks array matching the size of an RGB array."""
    n = rgb.shape[0]
    data = draw(
        st.lists(
            st.tuples(*[st.integers(0, max_id) for _ in range(5)]),
            min_size=n,
            max_size=n,
        )
    )
    return np.array(data, dtype=np.int32)


@st.composite
def lut_entry(draw: st.DrawFn, mode: str | None = None, min_size: int = 2, max_size: int = 30):
    """Generate a single (rgb, stacks, mode) LUT entry."""
    if mode is None:
        mode = draw(st.sampled_from(LOW_MODES + HIGH_MODES))
    rgb = draw(rgb_array_st(min_size=min_size, max_size=max_size))
    max_id = {"BW": 1, "4-Color": 3, "6-Color": 5, "8-Color": 7}.get(mode, 7)
    stacks = draw(stacks_for_rgb(rgb, max_id=max_id))
    return (rgb, stacks, mode)


@st.composite
def merge_input(draw: st.DrawFn):
    """Generate a valid merge input: at least 2 entries, one being 6-Color or 8-Color."""
    primary_mode = draw(st.sampled_from(HIGH_MODES))
    primary = draw(lut_entry(mode=primary_mode, min_size=2, max_size=20))

    n_secondary = draw(st.integers(min_value=1, max_value=3))
    secondaries = []
    for _ in range(n_secondary):
        sec_mode = draw(st.sampled_from(LOW_MODES))
        sec = draw(lut_entry(mode=sec_mode, min_size=2, max_size=20))
        secondaries.append(sec)

    return [primary] + secondaries


@st.composite
def merge_input_small(draw: st.DrawFn):
    """Generate a small merge input for Delta-E tests (2-5 colors per entry)."""
    primary_mode = draw(st.sampled_from(HIGH_MODES))
    primary = draw(lut_entry(mode=primary_mode, min_size=2, max_size=5))

    sec_mode = draw(st.sampled_from(LOW_MODES))
    sec = draw(lut_entry(mode=sec_mode, min_size=2, max_size=5))

    return [primary, sec]


# ═══════════════════════════════════════════════════════════════
# Property 6: LUT Info API 往返一致性
# Tag: Feature: lut-manager-merger, Property 6: LUT Info API 往返一致性
# **Validates: Requirements 2.4**
# ═══════════════════════════════════════════════════════════════


class TestLutInfoApiRoundTrip:
    """Property 6: For any LUT returned by GET /api/lut/list,
    calling GET /api/lut/{name}/info should return a consistent
    color_mode and a positive color_count."""

    @given(
        names_and_modes=st.lists(
            st.tuples(
                st.from_regex(r"[A-Za-z0-9][A-Za-z0-9 _\-]{0,29}", fullmatch=True),
                st.sampled_from(VALID_MODES),
                st.integers(min_value=1, max_value=5000),
            ),
            min_size=1,
            max_size=10,
            unique_by=lambda x: x[0],
        )
    )
    @settings(max_examples=100)
    def test_info_consistent_with_list(self, names_and_modes):
        """**Validates: Requirements 2.4**

        For each LUT in the list, the info endpoint returns the same
        color_mode and a positive color_count.
        """
        from fastapi.testclient import TestClient
        from api.app import app

        client = TestClient(app)

        # Build mock data: display_name → (path, mode, count)
        lut_files: dict[str, str] = {}
        mode_map: dict[str, tuple[str, int]] = {}
        for name, mode, count in names_and_modes:
            fake_path = f"/fake/{name}.npy"
            lut_files[name] = fake_path
            mode_map[fake_path] = (mode, count)

        def mock_get_all_lut_files():
            return dict(lut_files)

        def mock_get_lut_path(display_name: str):
            return lut_files.get(display_name)

        def mock_infer_color_mode(display_name: str, file_path: str):
            return mode_map[file_path][0]

        def mock_detect_color_mode(lut_path: str):
            return mode_map[lut_path]

        with (
            patch("api.routers.lut.LUTManager.get_all_lut_files", side_effect=mock_get_all_lut_files),
            patch("api.routers.lut.LUTManager.get_lut_path", side_effect=mock_get_lut_path),
            patch("api.routers.lut.LUTManager.infer_color_mode", side_effect=mock_infer_color_mode),
            patch("api.routers.lut.LUTMerger.detect_color_mode", side_effect=mock_detect_color_mode),
        ):
            # Step 1: Get the list
            list_resp = client.get("/api/lut/list")
            assert list_resp.status_code == 200
            lut_list = list_resp.json()["luts"]

            # Step 2: For each entry, call info and verify consistency
            for entry in lut_list:
                name = entry["name"]
                list_mode = entry["color_mode"]

                info_resp = client.get(f"/api/lut/{name}/info")
                assert info_resp.status_code == 200, (
                    f"Info endpoint failed for '{name}': {info_resp.status_code}"
                )
                info_data = info_resp.json()

                # color_mode from info should match the mode we set
                assert info_data["color_mode"] == mode_map[lut_files[name]][0], (
                    f"Mode mismatch for '{name}': "
                    f"list={list_mode}, info={info_data['color_mode']}"
                )
                # color_count must be a positive integer
                assert info_data["color_count"] > 0, (
                    f"color_count should be positive for '{name}', "
                    f"got {info_data['color_count']}"
                )


# ═══════════════════════════════════════════════════════════════
# Property 7: 合并统计一致性（后端）
# Tag: Feature: lut-manager-merger, Property 7: 合并统计一致性
# **Validates: Requirements 6.5, 6.6**
# ═══════════════════════════════════════════════════════════════


class TestMergeStatsConsistencyBackend:
    """Property 7: For any valid merge input (≥2 LUTs, including one
    6-Color or 8-Color), LUTMerger.merge_luts stats satisfy:
    - total_before == sum of input color counts
    - total_after == merged_rgb.shape[0]
    - total_before >= total_after
    - exact_dupes + similar_removed == total_before - total_after
    """

    @given(entries=merge_input())
    @settings(max_examples=100)
    def test_stats_invariants_no_dedup(self, entries):
        """**Validates: Requirements 6.5, 6.6**

        With dedup_threshold=0, verify all stats invariants hold.
        """
        total_input = sum(rgb.shape[0] for rgb, _, _ in entries)

        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(
            entries, dedup_threshold=0
        )

        # total_before == sum of input color counts
        assert stats["total_before"] == total_input, (
            f"total_before={stats['total_before']} != sum={total_input}"
        )

        # total_after == merged_rgb.shape[0]
        assert stats["total_after"] == merged_rgb.shape[0], (
            f"total_after={stats['total_after']} != "
            f"merged_rgb.shape[0]={merged_rgb.shape[0]}"
        )

        # total_before >= total_after
        assert stats["total_before"] >= stats["total_after"], (
            f"total_before={stats['total_before']} < "
            f"total_after={stats['total_after']}"
        )

        # exact_dupes + similar_removed == total_before - total_after
        removed = stats["exact_dupes"] + stats["similar_removed"]
        expected_removed = stats["total_before"] - stats["total_after"]
        assert removed == expected_removed, (
            f"exact_dupes({stats['exact_dupes']}) + "
            f"similar_removed({stats['similar_removed']}) = {removed} != "
            f"total_before - total_after = {expected_removed}"
        )

        # merged_stacks shape must match merged_rgb
        assert merged_stacks.shape[0] == merged_rgb.shape[0]

    @given(entries=merge_input_small())
    @settings(max_examples=100, deadline=None)
    def test_stats_invariants_with_small_threshold(self, entries):
        """**Validates: Requirements 6.5, 6.6**

        With a small positive dedup_threshold, verify all stats invariants hold.
        Using threshold=0.5 to keep tests fast while exercising Delta-E path.
        Uses smaller arrays to avoid slow Delta-E computation.
        """
        total_input = sum(rgb.shape[0] for rgb, _, _ in entries)

        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(
            entries, dedup_threshold=0.5
        )

        assert stats["total_before"] == total_input
        assert stats["total_after"] == merged_rgb.shape[0]
        assert stats["total_before"] >= stats["total_after"]

        removed = stats["exact_dupes"] + stats["similar_removed"]
        expected_removed = stats["total_before"] - stats["total_after"]
        assert removed == expected_removed

        assert merged_stacks.shape[0] == merged_rgb.shape[0]
