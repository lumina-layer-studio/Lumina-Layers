import numpy as np
import pytest

from core.color_replacement import (
    apply_replacements_with_selection,
    build_selection_mask,
    make_group_selection_token,
    make_region_selection_token,
)


@pytest.mark.unit
def test_build_selection_mask_region_only_returns_connected_component():
    quantized = np.array(
        [
            [[10, 10, 10], [10, 10, 10], [20, 20, 20]],
            [[10, 10, 10], [20, 20, 20], [20, 20, 20]],
            [[10, 10, 10], [10, 10, 10], [20, 20, 20]],
        ],
        dtype=np.uint8,
    )
    mask_solid = np.ones((3, 3), dtype=bool)
    token = make_region_selection_token("#0a0a0a", "#111111", 0, 0)

    mask = build_selection_mask(quantized, mask_solid, token)

    assert mask[0, 0]
    assert mask[1, 0]
    assert mask[2, 0]
    assert mask[2, 1]
    assert not mask[0, 2]


@pytest.mark.unit
def test_apply_replacements_with_selection_supports_group_and_region():
    quantized = np.array(
        [
            [[10, 10, 10], [10, 10, 10], [20, 20, 20]],
            [[10, 10, 10], [20, 20, 20], [20, 20, 20]],
            [[10, 10, 10], [10, 10, 10], [20, 20, 20]],
        ],
        dtype=np.uint8,
    )
    matched = np.array(
        [
            [[30, 30, 30], [30, 30, 30], [40, 40, 40]],
            [[30, 30, 30], [40, 40, 40], [40, 40, 40]],
            [[30, 30, 30], [30, 30, 30], [40, 40, 40]],
        ],
        dtype=np.uint8,
    )
    mask_solid = np.ones((3, 3), dtype=bool)

    replacements = {
        make_region_selection_token("#0a0a0a", "#1e1e1e", 0, 0): "#999999",
        make_group_selection_token("#141414", "#282828"): "#777777",
    }

    out = apply_replacements_with_selection(
        matched, quantized, mask_solid, replacements
    )

    assert np.all(out[0, 0] == np.array([153, 153, 153], dtype=np.uint8))
    assert np.all(out[0, 2] == np.array([119, 119, 119], dtype=np.uint8))
