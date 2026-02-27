"""
Property-based tests for LUT Merger engine.

Tests correctness properties defined in the design document for
the lut-merge feature.
"""

import os
import tempfile
import numpy as np
from hypothesis import given, settings, assume
import hypothesis.strategies as st
import pytest

from core.lut_merger import LUTMerger, _SIZE_TO_MODE, _MODE_PRIORITY


# ═══════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════

standard_sizes = st.sampled_from([32, 1024, 1296, 2738])
non_standard_sizes = st.integers(min_value=1, max_value=5000).filter(
    lambda x: x not in {32, 1024, 1296, 2738} and not (30 <= x <= 36)
)
color_modes = st.sampled_from(["BW", "4-Color", "6-Color", "8-Color"])
all_modes_with_low = st.sampled_from(["BW", "4-Color"])
high_modes = st.sampled_from(["6-Color", "8-Color"])

# Small RGB arrays for fast testing
def rgb_array(size):
    return np.random.randint(0, 256, size=(size, 3), dtype=np.uint8)

def stack_array(size, max_id=7):
    return np.random.randint(0, max_id + 1, size=(size, 5), dtype=np.int32)


# ═══════════════════════════════════════════════════════════════
# Property 1: 色彩模式检测正确性
# ═══════════════════════════════════════════════════════════════

class TestColorModeDetection:
    """
    **Feature: lut-merge, Property 1: 色彩模式检测正确性**
    **Validates: Requirements 2.2**
    """

    @given(size=standard_sizes)
    @settings(max_examples=100)
    def test_standard_size_detection(self, size):
        """For any standard LUT size, detect_color_mode returns the correct mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.npy")
            np.save(path, rgb_array(size))
            mode, count = LUTMerger.detect_color_mode(path)
            assert count == size
            assert mode == _SIZE_TO_MODE[size], (
                f"Expected {_SIZE_TO_MODE[size]} for size {size}, got {mode}"
            )

    @given(size=non_standard_sizes)
    @settings(max_examples=100)
    def test_non_standard_size_returns_merged(self, size):
        """For any non-standard LUT size, detect_color_mode returns 'Merged'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.npy")
            np.save(path, rgb_array(size))
            mode, count = LUTMerger.detect_color_mode(path)
            assert count == size
            assert mode == "Merged", (
                f"Expected 'Merged' for non-standard size {size}, got {mode}"
            )

    def test_npz_detection(self):
        """A .npz file with rgb and stacks keys is detected as 'Merged'."""
        rgb = rgb_array(500)
        stacks = stack_array(500)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.npz")
            np.savez(path, rgb=rgb, stacks=stacks)
            mode, count = LUTMerger.detect_color_mode(path)
            assert mode == "Merged"
            assert count == 500


# ═══════════════════════════════════════════════════════════════
# Property 2: 兼容性校验正确性
# ═══════════════════════════════════════════════════════════════

class TestCompatibilityValidation:
    """
    **Feature: lut-merge, Property 2: 兼容性校验正确性**
    **Validates: Requirements 2.3, 2.4, 2.5**
    """

    @given(
        low_modes=st.lists(all_modes_with_low, min_size=1, max_size=3),
        high_mode=high_modes,
    )
    @settings(max_examples=100)
    def test_valid_with_high_mode(self, low_modes, high_mode):
        """Any combination containing a 6-Color or 8-Color LUT is valid
        (assuming 6-Color max only has BW/4-Color/6-Color)."""
        modes = low_modes + [high_mode]
        valid, msg = LUTMerger.validate_compatibility(modes)

        if high_mode == "8-Color":
            assert valid, f"8-Color combo should be valid: {modes}, msg={msg}"
        else:
            # 6-Color max: only BW/4-Color/6-Color allowed
            has_invalid = any(m not in {"BW", "4-Color", "6-Color"} for m in modes)
            if has_invalid:
                assert not valid
            else:
                assert valid, f"6-Color combo should be valid: {modes}, msg={msg}"

    @given(modes=st.lists(all_modes_with_low, min_size=2, max_size=4))
    @settings(max_examples=100)
    def test_invalid_without_high_mode(self, modes):
        """A combination without any 6-Color or 8-Color LUT is invalid."""
        # Ensure no high modes
        assume("6-Color" not in modes and "8-Color" not in modes)
        valid, msg = LUTMerger.validate_compatibility(modes)
        assert not valid, f"Should be invalid without high mode: {modes}"

    def test_single_lut_invalid(self):
        """A single LUT is not enough for merging."""
        valid, msg = LUTMerger.validate_compatibility(["6-Color"])
        assert not valid

    def test_8color_allows_all(self):
        """8-Color mode allows any combination."""
        modes = ["BW", "4-Color", "6-Color", "8-Color"]
        valid, msg = LUTMerger.validate_compatibility(modes)
        assert valid


# ═══════════════════════════════════════════════════════════════
# Property 3: 合并拼接完整性
# ═══════════════════════════════════════════════════════════════

class TestMergeConcatenation:
    """
    **Feature: lut-merge, Property 3: 合并拼接完整性**
    **Validates: Requirements 3.2**
    """

    @given(
        n1=st.integers(min_value=1, max_value=20),
        n2=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100)
    def test_no_dedup_preserves_all(self, n1, n2):
        """With threshold=0 and no exact duplicates, merged count = sum of inputs."""
        # Generate unique RGB values to avoid exact duplicates
        total = n1 + n2
        all_colors = set()
        rgb1_list = []
        rgb2_list = []

        for _ in range(n1):
            while True:
                c = tuple(np.random.randint(0, 256, 3))
                if c not in all_colors:
                    all_colors.add(c)
                    rgb1_list.append(c)
                    break

        for _ in range(n2):
            while True:
                c = tuple(np.random.randint(0, 256, 3))
                if c not in all_colors:
                    all_colors.add(c)
                    rgb2_list.append(c)
                    break

        rgb1 = np.array(rgb1_list, dtype=np.uint8)
        rgb2 = np.array(rgb2_list, dtype=np.uint8)
        stacks1 = stack_array(n1, max_id=5)
        stacks2 = stack_array(n2, max_id=7)

        entries = [
            (rgb1, stacks1, "6-Color"),
            (rgb2, stacks2, "8-Color"),
        ]

        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(entries, dedup_threshold=0)

        assert stats['total_before'] == total
        assert stats['total_after'] == total
        assert merged_rgb.shape[0] == total


# ═══════════════════════════════════════════════════════════════
# Property 4: 材料 ID 范围不变量
# ═══════════════════════════════════════════════════════════════

class TestMaterialIDRange:
    """
    **Feature: lut-merge, Property 4: 材料 ID 范围不变量**
    **Validates: Requirements 3.3**
    """

    @given(
        n=st.integers(min_value=2, max_value=20),
    )
    @settings(max_examples=100)
    def test_material_ids_in_range(self, n):
        """All material IDs in merged stacks are within valid range."""
        # Mix BW (0-1) and 6-Color (0-5)
        rgb_bw = rgb_array(min(n, 5))
        stacks_bw = np.random.randint(0, 2, size=(min(n, 5), 5), dtype=np.int32)

        rgb_6c = rgb_array(n)
        stacks_6c = np.random.randint(0, 6, size=(n, 5), dtype=np.int32)

        entries = [
            (rgb_bw, stacks_bw, "BW"),
            (rgb_6c, stacks_6c, "6-Color"),
        ]

        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(entries, dedup_threshold=0)

        # BW max=1, 6-Color max=5 → overall max should be 5
        assert merged_stacks.min() >= 0
        assert merged_stacks.max() <= 5


# ═══════════════════════════════════════════════════════════════
# Property 5: 去重后无相近色
# ═══════════════════════════════════════════════════════════════

class TestDedupNoSimilarColors:
    """
    **Feature: lut-merge, Property 5: 去重后无相近色**
    **Validates: Requirements 3.4, 4.2, 4.4**
    """

    def test_exact_dedup_removes_duplicates(self):
        """With threshold=0, exact RGB duplicates are removed."""
        rgb1 = np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)
        rgb2 = np.array([[255, 0, 0], [0, 0, 255]], dtype=np.uint8)
        stacks1 = np.array([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32)
        stacks2 = np.array([[2, 2, 2, 2, 2], [3, 3, 3, 3, 3]], dtype=np.int32)

        entries = [
            (rgb1, stacks1, "6-Color"),
            (rgb2, stacks2, "8-Color"),
        ]

        merged_rgb, _, stats = LUTMerger.merge_luts(entries, dedup_threshold=0)

        assert stats['exact_dupes'] == 1
        assert stats['total_after'] == 3  # 4 - 1 duplicate

    def test_threshold_dedup_removes_similar(self):
        """With threshold > 0, similar colors (Delta-E < threshold) are removed."""
        # Two identical reds — guaranteed Delta-E = 0
        rgb1 = np.array([[255, 0, 0]], dtype=np.uint8)
        rgb2 = np.array([[255, 0, 0]], dtype=np.uint8)
        stacks1 = np.array([[0, 0, 0, 0, 0]], dtype=np.int32)
        stacks2 = np.array([[1, 1, 1, 1, 1]], dtype=np.int32)

        entries = [
            (rgb1, stacks1, "8-Color"),
            (rgb2, stacks2, "6-Color"),
        ]

        merged_rgb, _, stats = LUTMerger.merge_luts(entries, dedup_threshold=5.0)

        # Exact duplicate removed first, then no similar left
        assert stats['total_after'] == 1
        # The 8-Color one should be kept (higher priority)
        assert tuple(merged_rgb[0]) == (255, 0, 0)


# ═══════════════════════════════════════════════════════════════
# Property 6: 去重优先级正确性
# ═══════════════════════════════════════════════════════════════

class TestDedupPriority:
    """
    **Feature: lut-merge, Property 6: 去重优先级正确性**
    **Validates: Requirements 4.3**
    """

    def test_higher_mode_preserved(self):
        """When deduping similar colors, the higher mode color is kept."""
        # Same color in both modes
        rgb_4c = np.array([[128, 64, 32]], dtype=np.uint8)
        rgb_8c = np.array([[128, 64, 32]], dtype=np.uint8)
        stacks_4c = np.array([[0, 1, 2, 3, 0]], dtype=np.int32)
        stacks_8c = np.array([[0, 1, 2, 3, 4]], dtype=np.int32)

        entries = [
            (rgb_4c, stacks_4c, "4-Color"),
            (rgb_8c, stacks_8c, "8-Color"),
        ]

        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(entries, dedup_threshold=0)

        assert stats['total_after'] == 1
        # 8-Color has higher priority, so its stack should be kept
        assert list(merged_stacks[0]) == [0, 1, 2, 3, 4]


# ═══════════════════════════════════════════════════════════════
# Property 9: 合并统计一致性
# ═══════════════════════════════════════════════════════════════

class TestMergeStatsConsistency:
    """
    **Feature: lut-merge, Property 9: 合并统计一致性**
    **Validates: Requirements 8.2**
    """

    @given(
        n1=st.integers(min_value=1, max_value=15),
        n2=st.integers(min_value=1, max_value=15),
    )
    @settings(max_examples=100)
    def test_stats_add_up(self, n1, n2):
        """total_before >= total_after, and exact_dupes + similar_removed = total_before - total_after."""
        rgb1 = rgb_array(n1)
        rgb2 = rgb_array(n2)
        stacks1 = stack_array(n1, max_id=5)
        stacks2 = stack_array(n2, max_id=7)

        entries = [
            (rgb1, stacks1, "6-Color"),
            (rgb2, stacks2, "8-Color"),
        ]

        _, _, stats = LUTMerger.merge_luts(entries, dedup_threshold=0)

        assert stats['total_before'] == n1 + n2
        assert stats['total_before'] >= stats['total_after']
        assert stats['exact_dupes'] + stats['similar_removed'] == stats['total_before'] - stats['total_after']


# ═══════════════════════════════════════════════════════════════
# Property 7: 保存/加载往返一致性
# ═══════════════════════════════════════════════════════════════

class TestSaveLoadRoundTrip:
    """
    **Feature: lut-merge, Property 7: 保存/加载往返一致性**
    **Validates: Requirements 5.2**
    """

    @given(n=st.integers(min_value=1, max_value=100))
    @settings(max_examples=100)
    def test_roundtrip(self, n):
        """save_merged_lut then load produces identical arrays."""
        rgb = rgb_array(n)
        stacks = stack_array(n)

        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "test_merged.npz")
        saved_path = LUTMerger.save_merged_lut(rgb, stacks, path)

        assert saved_path.endswith('.npz')
        assert os.path.exists(saved_path)

        data = np.load(saved_path)
        loaded_rgb = data['rgb'].copy()
        loaded_stacks = data['stacks'].copy()
        data.close()

        np.testing.assert_array_equal(loaded_rgb, rgb)
        np.testing.assert_array_equal(loaded_stacks, stacks)

    def test_npz_extension_enforced(self):
        """Output path always ends with .npz even if .npy is given."""
        rgb = rgb_array(5)
        stacks = stack_array(5)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.npy")
            saved_path = LUTMerger.save_merged_lut(rgb, stacks, path)
            assert saved_path.endswith('.npz')


# ═══════════════════════════════════════════════════════════════
# Property 8: 非标准尺寸检测
# ═══════════════════════════════════════════════════════════════

class TestNonStandardSizeDetection:
    """
    **Feature: lut-merge, Property 8: 非标准尺寸检测**
    **Validates: Requirements 5.4, 6.2**
    """

    def test_npz_detected_as_merged(self):
        """A .npz LUT file is detected as 'Merged' by converter's detect_lut_color_mode."""
        from core.converter import detect_lut_color_mode

        rgb = rgb_array(500)
        stacks = stack_array(500)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "merged.npz")
            np.savez(path, rgb=rgb, stacks=stacks)
            result = detect_lut_color_mode(path)
            assert result == "Merged", f"Expected 'Merged' for .npz, got {result}"

    @given(size=non_standard_sizes.filter(lambda x: x > 35 and (x < 900 or x > 2800)))
    @settings(max_examples=100)
    def test_non_standard_npy_detected_as_merged(self, size):
        """For any .npy with non-standard color count (outside known ranges),
        detect_lut_color_mode returns 'Merged'."""
        from core.converter import detect_lut_color_mode

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.npy")
            np.save(path, rgb_array(size))
            result = detect_lut_color_mode(path)
            assert result == "Merged", (
                f"Expected 'Merged' for non-standard size {size}, got {result}"
            )
