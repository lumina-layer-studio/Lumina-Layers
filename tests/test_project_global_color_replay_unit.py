"""Portable whole-image project color replay tests.
项目级全图改色重放测试。
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from core.pipeline.p03_core_processing import run as process_preview
from core.pipeline.s03_color_replacement import (
    _resolve_replayed_color_replacement_jobs,
    run as apply_color_replacements,
)
from core.vector_engine import (
    _normalise_vector_replacement_input,
    _project_dynamic_replacement_targets,
    _rematch_static_vector_replacement_records,
)


def _saved_replacement() -> list[dict[str, str]]:
    return [
        {
            "quantized_hex": "#aa0000",
            "matched_hex": "#112233",
            "replacement_hex": "#44cc55",
        }
    ]


class _RasterTree:
    def query(self, _colour: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return np.array([0.0]), np.array([0])


class _RasterProcessor:
    def __init__(self) -> None:
        self.kdtree = _RasterTree()
        self.ref_stacks = np.array([[7]], dtype=np.int32)
        self.lut_rgb = np.array([[0x44, 0xCC, 0x55]], dtype=np.uint8)

    def _rgb_to_lab(self, colours: np.ndarray) -> np.ndarray:
        return np.zeros((colours.shape[0], 3), dtype=np.float64)


class _PreviewRasterProcessor(_RasterProcessor):
    def __init__(self, quantized: np.ndarray, matched: np.ndarray) -> None:
        super().__init__()
        self.quantized = quantized
        self.matched = matched
        self.last_match_info = None

    def process_image(self, **_kwargs: object) -> dict[str, object]:
        return {
            "matched_rgb": self.matched.copy(),
            "material_matrix": np.zeros(
                (*self.matched.shape[:2], 1),
                dtype=np.int32,
            ),
            "mask_solid": np.ones(self.matched.shape[:2], dtype=bool),
            "dimensions": (self.matched.shape[1], self.matched.shape[0]),
            "quantized_image": self.quantized.copy(),
        }


def test_raster_replay_resolves_saved_source_against_current_match() -> None:
    """A changed material match is located through the stable source color.
    更换耗材后，应通过稳定源色定位当前匹配色。
    """
    quantized = np.array([[[0xAA, 0x00, 0x00]]], dtype=np.uint8)
    matched = np.array([[[0xFE, 0xDC, 0xBA]]], dtype=np.uint8)

    resolved = _resolve_replayed_color_replacement_jobs(
        _saved_replacement(),
        matched,
        quantized,
        np.ones((1, 1), dtype=bool),
    )

    assert len(resolved) == 1
    assert resolved[0][0] == "#44cc55"
    np.testing.assert_array_equal(resolved[0][1], [[True]])


def test_lut_preview_rebuild_applies_portable_global_replacement() -> None:
    """Preview and its pristine reset arrays stay distinct after replay.
    预览重放后，当前数组与可重置的原始数组必须保持分离。
    """
    quantized = np.array([[[0xAA, 0x00, 0x00]]], dtype=np.uint8)
    matched = np.array([[[0xFE, 0xDC, 0xBA]]], dtype=np.uint8)
    processor = _PreviewRasterProcessor(quantized, matched)

    with patch("core.image_processing.LuminaImageProcessor", return_value=processor):
        result = process_preview(
            {
                "actual_lut_path": "test.npy",
                "color_mode": "4-Color RYBW",
                "image_path": "source.png",
                "target_width_mm": 100.0,
                "modeling_mode": "high-fidelity",
                "quantize_colors": 8,
                "replacement_regions": _saved_replacement(),
            }
        )

    np.testing.assert_array_equal(
        result["matched_rgb"],
        np.array([[[0x44, 0xCC, 0x55]]], dtype=np.uint8),
    )
    np.testing.assert_array_equal(result["original_matched_rgb"], matched)
    np.testing.assert_array_equal(result["material_matrix"], [[[7]]])
    np.testing.assert_array_equal(result["original_material_matrix"], [[[0]]])


def test_lut_preview_without_replay_keeps_zero_copy_original_aliases() -> None:
    """The ordinary preview path must not duplicate its large pixel arrays.
    普通预览链路不得额外复制大尺寸像素数组。
    """
    quantized = np.array([[[0xAA, 0x00, 0x00]]], dtype=np.uint8)
    matched = np.array([[[0xFE, 0xDC, 0xBA]]], dtype=np.uint8)
    processor = _PreviewRasterProcessor(quantized, matched)

    with patch("core.image_processing.LuminaImageProcessor", return_value=processor):
        result = process_preview(
            {
                "actual_lut_path": "test.npy",
                "color_mode": "4-Color RYBW",
                "image_path": "source.png",
                "target_width_mm": 100.0,
                "modeling_mode": "high-fidelity",
                "quantize_colors": 8,
            }
        )

    assert np.shares_memory(result["matched_rgb"], result["original_matched_rgb"])
    assert np.shares_memory(
        result["material_matrix"],
        result["original_material_matrix"],
    )


def test_generation_replay_uses_current_raster_match() -> None:
    """The final raster pipeline uses the same rematching contract.
    最终栅格生成链路应使用同一套重匹配契约。
    """
    result = apply_color_replacements(
        {
            "matched_rgb": np.array([[[0xFE, 0xDC, 0xBA]]], dtype=np.uint8),
            "material_matrix": np.zeros((1, 1, 1), dtype=np.int32),
            "mask_solid": np.ones((1, 1), dtype=bool),
            "quantized_image": np.array([[[0xAA, 0x00, 0x00]]], dtype=np.uint8),
            "processor": _RasterProcessor(),
            "replacement_regions": _saved_replacement(),
        }
    )

    np.testing.assert_array_equal(
        result["matched_rgb"],
        np.array([[[0x44, 0xCC, 0x55]]], dtype=np.uint8),
    )


def test_generation_replay_keeps_transparent_pixels_without_material() -> None:
    """Transparent pixels sharing a replaced color must not gain printable stacks.
    与被替换颜色相同的透明像素不得获得可打印的材料堆叠。
    """
    result = apply_color_replacements(
        {
            "matched_rgb": np.array(
                [[[0xFE, 0xDC, 0xBA], [0xFE, 0xDC, 0xBA]]],
                dtype=np.uint8,
            ),
            "material_matrix": np.array([[[0], [-1]]], dtype=np.int32),
            "mask_solid": np.array([[True, False]]),
            "quantized_image": np.array(
                [[[0xAA, 0x00, 0x00], [0xAA, 0x00, 0x00]]],
                dtype=np.uint8,
            ),
            "processor": _RasterProcessor(),
            "replacement_regions": _saved_replacement(),
        }
    )

    np.testing.assert_array_equal(result["material_matrix"], [[[7], [-1]]])


@pytest.mark.parametrize("source_match_survives", [False, True])
def test_replay_does_not_promote_cleanup_neighbors_to_global_replacements(
    source_match_survives: bool,
) -> None:
    source_match = [0x11, 0x22, 0x33] if source_match_survives else [0xFE, 0xDC, 0xBA]
    neighbor = [0x20, 0x90, 0xE0]
    matched = np.array([[source_match, neighbor, neighbor]], dtype=np.uint8)
    result = apply_color_replacements(
        {
            "matched_rgb": matched.copy(),
            "material_matrix": np.array([[[0], [1], [1]]], dtype=np.int32),
            "mask_solid": np.ones((1, 3), dtype=bool),
            # Cleanup merged one source pixel into its blue neighbor.
            "quantized_image": np.array(
                [[[0xAA, 0, 0], [0xAA, 0, 0], [0, 0, 0xFF]]], dtype=np.uint8
            ),
            "processor": _RasterProcessor(),
            "replacement_regions": _saved_replacement(),
        }
    )

    np.testing.assert_array_equal(result["matched_rgb"][0, 0], [0x44, 0xCC, 0x55])
    np.testing.assert_array_equal(result["matched_rgb"][0, 2], neighbor)
    np.testing.assert_array_equal(result["material_matrix"][0, 2], [1])
    if source_match_survives:
        np.testing.assert_array_equal(result["matched_rgb"][0, 1], neighbor)


def test_replay_keeps_distinct_source_edits_when_new_materials_match_them_equally() -> None:
    result = apply_color_replacements(
        {
            "matched_rgb": np.full((1, 2, 3), 100, dtype=np.uint8),
            "material_matrix": np.zeros((1, 2, 1), dtype=np.int32),
            "mask_solid": np.ones((1, 2), dtype=bool),
            "quantized_image": np.array([[[0xAA, 0, 0], [0, 0, 0xBB]]], dtype=np.uint8),
            "processor": _RasterProcessor(),
            "replacement_regions": [
                *_saved_replacement(),
                {
                    "quantized_hex": "#0000bb",
                    "matched_hex": "#112244",
                    "replacement_hex": "#ff6600",
                },
            ],
        }
    )
    np.testing.assert_array_equal(
        result["matched_rgb"], [[[0x44, 0xCC, 0x55], [0xFF, 0x66, 0]]]
    )


def test_material_change_does_not_select_old_match_found_outside_source_region() -> None:
    result = apply_color_replacements(
        {
            "matched_rgb": np.array([[[100, 100, 100], [0x11, 0x22, 0x33]]], dtype=np.uint8),
            "material_matrix": np.zeros((1, 2, 1), dtype=np.int32),
            "mask_solid": np.ones((1, 2), dtype=bool),
            "quantized_image": np.array([[[0xAA, 0, 0], [0, 0, 0xBB]]], dtype=np.uint8),
            "processor": _RasterProcessor(),
            "replacement_regions": _saved_replacement(),
        }
    )
    np.testing.assert_array_equal(
        result["matched_rgb"], [[[0x44, 0xCC, 0x55], [0x11, 0x22, 0x33]]]
    )


class _VectorMatcher:
    def __init__(self) -> None:
        self.lut_rgb = np.array([[0x12, 0xAB, 0x34]], dtype=np.uint8)
        self.solved_colours: list[tuple[int, int, int]] = []

    def solve_for_fills(self, colours: list[tuple[int, int, int]]) -> None:
        self.solved_colours = colours


class _VectorProcessor:
    def __init__(self) -> None:
        self.img_processor = _VectorMatcher()
        self.matched_query: tuple[int, int, int] | None = None

    def _match_lut_index_for_rgb(
        self,
        rgb: tuple[int, int, int],
    ) -> tuple[int, float]:
        self.matched_query = rgb
        return 0, 0.0


def test_vector_replay_rewrites_only_the_current_matched_identity() -> None:
    """Native SVG retains structured records but updates their matched key.
    原生 SVG 保留结构化记录，只更新其当前匹配色身份。
    """
    processor = _VectorProcessor()

    resolved = _rematch_static_vector_replacement_records(
        _saved_replacement(),
        processor,
    )

    assert processor.img_processor.solved_colours == [(0xAA, 0x00, 0x00)]
    assert processor.matched_query == (0xAA, 0x00, 0x00)
    assert resolved == [
        {
            "quantized_hex": "#aa0000",
            "matched_hex": "#12ab34",
            "replacement_hex": "#44cc55",
        }
    ]


def test_dynamic_vector_replay_prefers_stable_source_identity() -> None:
    """Dynamic SVG replay survives a changed preflight material match.
    动态 SVG 在预匹配耗材色变化后仍应按稳定源色重放。
    """
    by_matched, by_source, _legacy = _normalise_vector_replacement_input(
        _saved_replacement()
    )
    shapes, count = _project_dynamic_replacement_targets(
        [{"color": (0xAA, 0x00, 0x00)}],
        [{"matched_rgb": (0xFE, 0xDC, 0xBA)}],
        by_matched,
        by_source,
    )

    assert count == 1
    assert shapes[0]["match_color"] == (0x44, 0xCC, 0x55)
