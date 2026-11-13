"""Property tests: vectorized dynamic catalog dedup matches the reference loop.

动态候选目录向量化去重与参考循环实现等价的性质测试。
"""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from core.material_dynamic_solver import build_dynamic_candidate_catalog


def _reference_dedup(
    rgb: np.ndarray, counts: np.ndarray, max_layer_count: int
) -> tuple[list[int], list[int], list[bool]]:
    """The original per-row loop, kept verbatim as the behavioral oracle."""
    packed = (
        (rgb[:, 0].astype(np.uint32) << 16)
        | (rgb[:, 1].astype(np.uint32) << 8)
        | rgb[:, 2].astype(np.uint32)
    )
    catalog_positions: dict[int, int] = {}
    retained_sources: list[int] = []
    minimum_counts: list[int] = []
    max_reachable: list[bool] = []
    for source_index, packed_rgb in enumerate(packed):
        key = int(packed_rgb)
        catalog_index = catalog_positions.get(key)
        actual_count = int(counts[source_index])
        if catalog_index is None:
            catalog_positions[key] = len(retained_sources)
            retained_sources.append(source_index)
            minimum_counts.append(actual_count)
            max_reachable.append(actual_count == max_layer_count)
            continue
        if actual_count == max_layer_count:
            max_reachable[catalog_index] = True
        if actual_count < minimum_counts[catalog_index]:
            retained_sources[catalog_index] = source_index
            minimum_counts[catalog_index] = actual_count
    return retained_sources, minimum_counts, max_reachable


@st.composite
def _catalog_rows(draw):
    max_layer_count = draw(st.integers(min_value=5, max_value=10))
    row_count = draw(st.integers(min_value=1, max_value=120))
    # A tiny color pool forces many duplicate colors and tie cases.
    palette_size = draw(st.integers(min_value=1, max_value=6))
    palette = np.asarray(
        draw(
            st.lists(
                st.tuples(*(st.integers(0, 255),) * 3),
                min_size=palette_size,
                max_size=palette_size,
            )
        ),
        dtype=np.uint8,
    )
    color_ids = draw(
        st.lists(st.integers(0, palette_size - 1), min_size=row_count, max_size=row_count)
    )
    counts = draw(
        st.lists(
            st.integers(5, max_layer_count), min_size=row_count, max_size=row_count
        )
    )
    return (
        palette[np.asarray(color_ids)],
        np.asarray(counts, dtype=np.int16),
        max_layer_count,
    )


@settings(max_examples=300, deadline=None)
@given(_catalog_rows())
def test_vectorized_dedup_matches_reference_loop(rows) -> None:
    rgb, counts, max_layer_count = rows
    recipes = np.zeros((rgb.shape[0], max_layer_count), dtype=np.int32)
    recipes[:, 0] = np.arange(rgb.shape[0])  # make every source row distinguishable

    catalog = build_dynamic_candidate_catalog(rgb, recipes, counts, max_layer_count)
    expected_sources, expected_counts, expected_reachable = _reference_dedup(
        rgb, counts, max_layer_count
    )

    assert catalog.source_indices.dtype == np.int64
    assert catalog.source_indices.tolist() == expected_sources
    assert catalog.minimum_actual_layer_counts.dtype == np.int16
    assert catalog.minimum_actual_layer_counts.tolist() == expected_counts
    assert catalog.max_layer_reachable.dtype == np.bool_
    assert catalog.max_layer_reachable.tolist() == expected_reachable
    assert np.array_equal(catalog.score_srgb, rgb[expected_sources])
    assert np.array_equal(catalog.print_recipes, recipes[expected_sources])
