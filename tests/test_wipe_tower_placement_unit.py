from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import replace
from typing import Iterator
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import core.wipe_tower_placement as wipe_tower_placement
from core.wipe_tower_placement import (
    Rect,
    WipeTowerPlacementRequest,
    estimate_wipe_tower_depth,
    solve_wipe_tower_placement,
    _tower_footprint_dimensions,
)


def _request(
    *,
    model_size: tuple[float, float] = (100.0, 100.0),
    bed_size: tuple[float, float] = (180.0, 180.0),
    tower_x: float = 5.0,
    tower_y: float = 145.0,
    tower_width: float = 170.0,
    tower_rotation: float = 0.0,
    material_count: int = 4,
    purge_volume: float = 140.0,
    model_height: float = 2.0,
    model_brim: float = 5.0,
    tower_brim: float = 3.0,
    edge_clearance: float = 2.0,
    minimum_tower_footprint_width: float = 0.0,
    minimum_tower_depth: float = 0.0,
    model_tower_clearance: float = 8.0,
    exclusions: tuple[tuple[tuple[float, float], ...], ...] = (),
    extruder_areas: tuple[tuple[tuple[float, float], ...], ...] = (),
) -> WipeTowerPlacementRequest:
    width, height = model_size
    bed_width, bed_height = bed_size
    return WipeTowerPlacementRequest(
        printable_area=((0.0, 0.0), (bed_width, 0.0), (bed_width, bed_height), (0.0, bed_height)),
        bed_exclusions=exclusions,
        extruder_printable_areas=extruder_areas,
        model_bounds=Rect(0.0, 0.0, width, height),
        model_height=model_height,
        model_brim=model_brim,
        material_count=material_count,
        layer_height=0.08,
        nozzle_diameter=0.4,
        purge_volume=purge_volume,
        tower_x=tower_x,
        tower_y=tower_y,
        tower_width=tower_width,
        tower_rotation=tower_rotation,
        tower_brim=tower_brim,
        edge_clearance=edge_clearance,
        minimum_tower_footprint_width=minimum_tower_footprint_width,
        minimum_tower_depth=minimum_tower_depth,
        model_tower_clearance=model_tower_clearance,
    )


def _assert_safe(result) -> None:
    assert result.requires_manual_adjustment is False
    assert result.model_outer_bounds.intersection_area(result.tower_outer_bounds) == pytest.approx(0.0)
    assert result.model_outer_bounds.width > 0
    assert result.model_outer_bounds.height > 0


@pytest.mark.parametrize("extruder_count", [2, 4, 6])
def test_every_physical_tool_transition_reserves_custom_ramming(extruder_count) -> None:
    arguments = dict(
        width=30.0, model_height=0.24, material_count=4, layer_height=0.08,
        nozzle_diameter=0.4, purge_volume=30.0, cyclic_toolchanges=True,
        extruder_count=extruder_count,
    )
    ordinary = estimate_wipe_tower_depth(**arguments)
    ramming_volume = 100.0 * math.pi * 1.75**2 / 4.0
    with_ramming = estimate_wipe_tower_depth(
        **arguments, filament_change_volume=ramming_volume,
    )
    # Four possible nozzle changes each need this extra physical volume.
    assert (with_ramming - ordinary) * 30.0 * 0.08 >= 4 * ramming_volume
    assert estimate_wipe_tower_depth(
        **{**arguments, "extruder_count": 1}, filament_change_volume=ramming_volume,
    ) == ordinary


def test_four_nozzle_ramming_reserves_native_squared_body() -> None:
    request = replace(
        _request(bed_size=(256, 256), model_size=(6, 6), tower_width=30,
                 material_count=4, purge_volume=30, model_height=0.24),
        extruder_count=4, cyclic_toolchanges=True, tower_square_rib_body=True,
        tower_infill_spacing_ratio=1.65,
        filament_change_volume=100.0 * math.pi * 1.75**2 / 4.0,
    )
    depth = wipe_tower_placement._estimate_request_tower_depth(request, request.tower_width)
    width, height = _tower_footprint_dimensions(request, request.tower_width, depth)
    # Flash WipeTower::plan_tower_new for these inputs produces a 156.5 mm
    # square body, using 1 mm nozzle-change paths and rounded cross-sections.
    # Keep the setting width fixed: the layout solver may choose another width.
    assert width >= 156.5
    assert height >= 156.5


@pytest.mark.parametrize(
    "bed_size,model_size",
    [((256, 256), (188, 260)), ((180, 180), (100, 185)), ((220, 200), (225, 100))],
)
def test_oversized_model_envelope_is_distinguished_from_tower_search_failure(bed_size, model_size):
    from utils.slicer_3mf_support import build_wipe_tower_patch_settings

    request = _request(bed_size=bed_size, model_size=model_size)
    result = solve_wipe_tower_placement(request)
    assert result.reason == "model_envelope_exceeds_printable_bounds"
    assert result.model_bounds.width == pytest.approx(model_size[0])
    assert result.model_bounds.height == pytest.approx(model_size[1])
    assert build_wipe_tower_patch_settings(result) == {}
    assert result.requires_manual_adjustment is True
    assert result.warning_code == "wipe_tower_manual_adjustment_required"


@pytest.mark.parametrize("model_size", [(188.0, 250.7), (250.7, 188.0)])
def test_brim_estimate_does_not_discard_a_valid_side_strip(model_size) -> None:
    request = replace(
        _request(
            bed_size=(256, 256), model_size=model_size, material_count=7,
            purge_volume=45, model_height=0.8, tower_width=35,
        ),
        tower_infill_spacing_ratio=1.5, tower_square_rib_body=True,
        tower_rib_width=8, tower_wall_types=("rib", "rectangle"),
    )
    result = solve_wipe_tower_placement(request)

    assert result.placement_available is True
    assert result.model_brim_requires_review is True
    assert result.requires_manual_adjustment is True
    assert result.model_bounds.width == pytest.approx(model_size[0])
    assert result.model_bounds.height == pytest.approx(model_size[1])
    assert result.tower_wall_type == "rectangle"
    assert result.model_bounds.expanded(request.edge_clearance).left >= 0
    assert result.model_bounds.expanded(request.edge_clearance).bottom >= 0
    assert result.model_bounds.expanded(request.edge_clearance).right <= 256
    assert result.model_bounds.expanded(request.edge_clearance).top <= 256
    assert result.tower_outer_bounds.left >= 0
    assert result.tower_outer_bounds.bottom >= 0
    assert result.tower_outer_bounds.right <= 256
    assert result.tower_outer_bounds.top <= 256
    assert result.model_outer_bounds.intersection_area(result.tower_outer_bounds) == 0


@pytest.mark.parametrize("extra_length", [0.0, 6.0, -6.0])
def test_native_rib_tower_reserves_wall_overhang_without_scaling(extra_length) -> None:
    request = replace(
        _request(bed_size=(256.0, 256.0), model_size=(18.6, 13.2),
                 tower_width=30.0, material_count=8, purge_volume=45.0,
                 model_height=1.2),
        nozzle_diameter=0.6,
        tower_infill_spacing_ratio=1.5,
        tower_rib_width=8.0,
        tower_extra_rib_length=extra_length,
    )
    result = solve_wipe_tower_placement(request)
    _assert_safe(result)
    # Native diagonal ribs extend by half the positive extra length at each
    # end and half their width sideways; reserve both outside the tower body.
    margin = 3.0 + 2.0 + 4.0 + max(0.0, extra_length) / 2.0
    assert result.tower_outer_bounds == result.tower_bounds.expanded(margin)
    assert result.tower_outer_bounds.left >= 0.0
    assert result.tower_outer_bounds.right <= 256.0
    assert result.tower_outer_bounds.bottom >= 0.0
    assert result.tower_outer_bounds.top <= 256.0
    assert result.model_bounds.width == pytest.approx(18.6)
    assert result.model_bounds.height == pytest.approx(13.2)


def test_disabled_rib_wall_leaves_existing_rectangle_layout_unchanged() -> None:
    request = _request(purge_volume=45.0)
    assert solve_wipe_tower_placement(request) == solve_wipe_tower_placement(
        replace(request, tower_rib_width=0.0, tower_extra_rib_length=100.0)
    )


def test_bambu_style_native_rib_tower_is_squared_before_placement() -> None:
    request = replace(
        _request(bed_size=(256, 256), model_size=(18.6, 13.2),
                 tower_width=30, material_count=8, purge_volume=45,
                 model_height=1.2),
        nozzle_diameter=0.6, tower_infill_spacing_ratio=1.5,
        tower_rib_width=8, tower_square_rib_body=True,
    )
    result = solve_wipe_tower_placement(request)
    _assert_safe(result)
    width, depth = _tower_footprint_dimensions(request, 30.0, 229.125)
    assert width == pytest.approx(83.25)
    assert depth >= 83.25
    # Native Orca 2.4.2 X1 .6 readback from the same model: tower bbox relative
    # to origin was [-2.933116, -2.951885, 60.215549, 58.41137]. The actual
    # square body, not merely the configured 30 mm width, must fit on the bed.
    assert result.tower_x + 60.215549 <= 256.0
    assert result.tower_y + 58.41137 <= 256.0
    assert result.tower_outer_bounds.right <= 256.0
    assert result.tower_outer_bounds.top <= 256.0


def test_zero_width_ribs_still_use_the_native_square_body() -> None:
    request = replace(
        _request(bed_size=(256, 256), model_size=(18.6, 13.2),
                 tower_width=30, material_count=8, purge_volume=45,
                 model_height=1.2),
        nozzle_diameter=0.6, tower_infill_spacing_ratio=1.5,
        tower_rib_width=0, tower_square_rib_body=True,
    )
    # Wall mode, not rib thickness, selects the native square-body algorithm.
    assert _tower_footprint_dimensions(request, 30.0, 229.125)[0] == pytest.approx(83.25)
    result = solve_wipe_tower_placement(request)
    _assert_safe(result)
    assert result.tower_bounds.width > 30.0
    assert result.tower_outer_bounds.right <= 256.0


def test_estimated_depth_decreases_when_long_strip_grows() -> None:
    short = estimate_wipe_tower_depth(
        width=35.0,
        model_height=2.0,
        material_count=4,
        layer_height=0.08,
        nozzle_diameter=0.4,
        purge_volume=140.0,
    )
    long = estimate_wipe_tower_depth(
        width=200.0,
        model_height=2.0,
        material_count=4,
        layer_height=0.08,
        nozzle_diameter=0.4,
        purge_volume=140.0,
    )

    assert short > long
    assert long >= 5.0


def test_estimated_depth_reserves_native_discrete_paths_and_block_walls() -> None:
    depth = estimate_wipe_tower_depth(
        width=22.0,
        model_height=1.2,
        material_count=4,
        layer_height=0.08,
        nozzle_diameter=0.4,
        purge_volume=45.0,
        tower_infill_spacing_ratio=1.5,
    )

    # Native Bambu/Orca generation discretises each transition into 0.5 mm
    # paths and adds two structural lines per material block.  A continuous
    # volume estimate gives only 115.06 mm here, while the sliced tower is
    # 126.5 mm deep before its brim.
    assert depth == pytest.approx(126.5)


def test_auto_layout_replans_tower_even_when_template_layout_is_safe() -> None:
    request = _request(
        bed_size=(256.0, 256.0),
        model_size=(100.0, 100.0),
        tower_x=18.5216,
        tower_y=214.154,
        tower_width=220.0,
    )

    result = solve_wipe_tower_placement(request)

    assert result.adapted is True
    assert result.reason in {
        "adapted_top",
        "adapted_bottom",
        "adapted_right",
        "adapted_left",
    }
    assert (
        result.tower_x,
        result.tower_y,
        result.tower_width,
        result.tower_rotation,
    ) != pytest.approx(
        (
            request.tower_x,
            request.tower_y,
            request.tower_width,
            request.tower_rotation,
        )
    )
    assert result.model_translation == pytest.approx((78.0, 78.0))
    _assert_safe(result)


def test_locked_model_translation_preserves_batch_coordinates() -> None:
    request = replace(
        _request(
            bed_size=(350.0, 320.0),
            model_size=(10.0, 8.0),
            tower_x=80.0,
            tower_y=250.0,
            tower_width=230.0,
        ),
        model_bounds=Rect(100.0, 50.0, 110.0, 58.0),
        model_translation_locked=True,
    )

    result = solve_wipe_tower_placement(request)

    assert result.model_translation == pytest.approx((0.0, 0.0))
    assert result.model_bounds == request.model_bounds
    _assert_safe(result)


def test_a1_mini_caps_orca_tower_that_is_longer_than_the_bed() -> None:
    request = _request(
        model_size=(120.0, 100.0),
        tower_x=7.45573,
        tower_y=219.877,
        tower_width=240.0,
    )

    result = solve_wipe_tower_placement(request)

    assert result.adapted is True
    assert result.tower_width <= 174.0
    assert result.tower_rotation == pytest.approx(0.0)
    _assert_safe(result)


def test_tall_model_selects_vertical_strip() -> None:
    result = solve_wipe_tower_placement(
        _request(
            model_size=(100.0, 155.0),
            tower_x=7.45573,
            tower_y=219.877,
            tower_width=240.0,
            purge_volume=30.0,
        )
    )

    assert result.adapted is True
    assert result.tower_rotation == pytest.approx(0.0)
    assert result.tower_bounds.height > result.tower_bounds.width
    assert result.tower_width == pytest.approx(30.0)
    assert result.reason in {"adapted_right", "adapted_left"}
    # Native slicers can generate tower/brim paths slightly beyond the visual
    # footprint. Keep a real 2 mm path margin inside the printable boundary.
    assert result.tower_bounds.right + 3.0 <= 178.0 + 1e-6
    _assert_safe(result)


def test_vertical_strip_reserves_a_native_minimum_footprint() -> None:
    result = solve_wipe_tower_placement(
        _request(
            bed_size=(256.0, 256.0),
            model_size=(180.0, 203.0),
            tower_x=26.7243,
            tower_y=220.0,
            tower_width=35.0,
            purge_volume=30.0,
            tower_brim=0.0,
            edge_clearance=0.0,
            minimum_tower_footprint_width=58.5,
            minimum_tower_depth=61.0,
            model_tower_clearance=7.5,
        )
    )

    assert result.requires_manual_adjustment is False
    assert result.reason in {"adapted_right", "adapted_left"}
    assert result.tower_width == pytest.approx(30.0)
    assert result.tower_bounds.width == pytest.approx(58.5)
    assert result.tower_bounds.height >= 61.0
    assert result.model_bounds.width == pytest.approx(180.0)
    assert result.model_bounds.left == pytest.approx(5.0)
    assert result.model_bounds.right == pytest.approx(185.0)
    assert result.tower_bounds.left - result.model_outer_bounds.right >= 7.5 - 1e-6
    _assert_safe(result)


def test_wide_model_selects_horizontal_strip() -> None:
    result = solve_wipe_tower_placement(
        _request(
            model_size=(155.0, 100.0),
            tower_x=7.45573,
            tower_y=219.877,
            tower_width=240.0,
        )
    )

    assert result.adapted is True
    assert result.tower_rotation == pytest.approx(0.0)
    _assert_safe(result)


def test_model_is_translated_without_changing_its_size() -> None:
    request = _request(
        bed_size=(256.0, 256.0),
        model_size=(200.0, 200.0),
        tower_x=18.5216,
        tower_y=214.154,
        tower_width=220.0,
    )

    result = solve_wipe_tower_placement(request)

    assert result.adapted is True
    assert result.model_bounds.width == pytest.approx(request.model_bounds.width)
    assert result.model_bounds.height == pytest.approx(request.model_bounds.height)
    assert math.isclose(result.model_translation[0], 28.0, abs_tol=30.0)
    assert result.model_translation != pytest.approx((28.0, 28.0))
    _assert_safe(result)


def test_common_extruder_area_is_respected_for_edge_limited_machine() -> None:
    request = _request(
        bed_size=(350.0, 320.0),
        model_size=(280.0, 120.0),
        tower_x=80.0,
        tower_y=250.0,
        tower_width=230.0,
        extruder_areas=(
            ((0.0, 0.0), (325.0, 0.0), (325.0, 320.0), (0.0, 320.0)),
            ((25.0, 0.0), (350.0, 0.0), (350.0, 320.0), (25.0, 320.0)),
        ),
    )

    result = solve_wipe_tower_placement(request)

    assert result.model_outer_bounds.left >= 25.0
    assert result.model_outer_bounds.right <= 325.0
    _assert_safe(result)


def test_bed_exclusion_forces_relayout() -> None:
    exclusion = (((0.0, 140.0), (180.0, 140.0), (180.0, 180.0), (0.0, 180.0)),)
    request = _request(
        model_size=(80.0, 80.0),
        tower_x=5.0,
        tower_y=145.0,
        tower_width=170.0,
        exclusions=exclusion,
    )

    result = solve_wipe_tower_placement(request)

    assert result.adapted is True
    assert result.tower_outer_bounds.bottom < 140.0
    _assert_safe(result)


def test_zero_area_bed_exclusions_do_not_block_automatic_layout() -> None:
    request = _request(
        bed_size=(426.0, 420.0),
        model_size=(60.0, 60.0),
        tower_x=20.0,
        tower_y=250.0,
        tower_width=200.0,
        minimum_tower_footprint_width=50.0,
        minimum_tower_depth=57.5,
        exclusions=(
            ((0.0, 420.0), (426.0, 420.0), (426.0, 420.0), (0.0, 420.0)),
            ((0.0, 0.0), (0.0, 0.0), (426.0, 0.0), (426.0, 0.0)),
        ),
    )

    result = solve_wipe_tower_placement(request)

    assert result.adapted is True
    assert result.requires_manual_adjustment is False
    _assert_safe(result)


def test_impossible_layout_keeps_model_scale_and_requires_manual_adjustment() -> None:
    request = _request(
        model_size=(179.0, 179.0),
        tower_x=7.45573,
        tower_y=219.877,
        tower_width=240.0,
    )

    result = solve_wipe_tower_placement(request)

    assert result.requires_manual_adjustment is True
    assert result.warning_code == "wipe_tower_manual_adjustment_required"
    assert result.model_bounds.width == pytest.approx(179.0)
    assert result.model_bounds.height == pytest.approx(179.0)
    assert result.tower_width > 0.0


# ---------------------------------------------------------------------------
# Search pruning and containment caching must not change the selected layout
# ---------------------------------------------------------------------------


class _UncachedRectAllowance:
    """Reference stand-in for ``_RectAllowanceCache`` that never memoizes."""

    def __init__(self, request: WipeTowerPlacementRequest) -> None:
        self._request = request

    def __call__(self, rect: Rect) -> bool:
        return wipe_tower_placement._rect_allowed(rect, self._request)


@contextmanager
def _exhaustive_search() -> Iterator[None]:
    """Run the solver without width pruning or containment caching."""

    with patch.object(wipe_tower_placement, "_width_can_still_win", lambda *_args, **_kwargs: True), patch.object(
        wipe_tower_placement, "_RectAllowanceCache", _UncachedRectAllowance
    ):
        yield


def _solve_exhaustively(request: WipeTowerPlacementRequest):
    with _exhaustive_search():
        return solve_wipe_tower_placement(request)


def test_width_can_still_win_until_a_better_rank_is_proven() -> None:
    can_still_win = wipe_tower_placement._width_can_still_win

    assert can_still_win(None, width_rank=40, clearance_rank=1) is True
    assert can_still_win((3, 0), width_rank=3, clearance_rank=0) is True
    assert can_still_win((3, 1), width_rank=2, clearance_rank=1) is True
    assert can_still_win((3, 0), width_rank=3, clearance_rank=1) is False
    assert can_still_win((3, 0), width_rank=4, clearance_rank=0) is False


@pytest.mark.parametrize(
    ("request_kwargs", "overrides"),
    [
        pytest.param(
            {
                "model_size": (100.0, 155.0),
                "tower_x": 7.45573,
                "tower_y": 219.877,
                "tower_width": 240.0,
                "purge_volume": 30.0,
            },
            {},
            id="vertical-strip",
        ),
        pytest.param(
            {
                "model_size": (80.0, 80.0),
                "exclusions": (((0.0, 140.0), (180.0, 140.0), (180.0, 180.0), (0.0, 180.0)),),
            },
            {},
            id="bed-exclusion",
        ),
        pytest.param(
            {
                "model_size": (179.0, 179.0),
                "tower_x": 7.45573,
                "tower_y": 219.877,
                "tower_width": 240.0,
            },
            {},
            id="impossible",
        ),
        pytest.param(
            {
                "model_size": (130.0, 146.6),
                "tower_x": 5.70098,
                "tower_y": 149.411,
                "purge_volume": 45.0,
            },
            {"prefer_vertical_strip": True, "tower_infill_spacing_ratio": 1.5},
            # The preferred 4 mm clearance only fits a far width; the 2 mm
            # fallback clearance fits a nearer one, which must still win.
            id="fallback-clearance-finds-nearer-width",
        ),
    ],
)
def test_pruned_search_matches_exhaustive_search(request_kwargs: dict, overrides: dict) -> None:
    request = replace(_request(**request_kwargs), **overrides)

    assert solve_wipe_tower_placement(request) == _solve_exhaustively(request)


@settings(max_examples=15, deadline=None)
@given(
    bed_side=st.floats(min_value=120.0, max_value=180.0),
    model_width_ratio=st.floats(min_value=0.1, max_value=0.95),
    model_depth_ratio=st.floats(min_value=0.1, max_value=0.95),
    model_height=st.floats(min_value=1.0, max_value=200.0),
    material_count=st.integers(min_value=2, max_value=8),
    purge_volume=st.floats(min_value=20.0, max_value=300.0),
    prefer_vertical_strip=st.booleans(),
)
def test_pruned_search_matches_exhaustive_search_for_generated_requests(
    bed_side: float,
    model_width_ratio: float,
    model_depth_ratio: float,
    model_height: float,
    material_count: int,
    purge_volume: float,
    prefer_vertical_strip: bool,
) -> None:
    request = replace(
        _request(
            bed_size=(bed_side, bed_side),
            model_size=(bed_side * model_width_ratio, bed_side * model_depth_ratio),
            model_height=model_height,
            material_count=material_count,
            purge_volume=purge_volume,
        ),
        prefer_vertical_strip=prefer_vertical_strip,
    )

    assert solve_wipe_tower_placement(request) == _solve_exhaustively(request)


def test_vertical_strip_search_stops_after_the_preferred_safe_width() -> None:
    request = _request(
        model_size=(100.0, 155.0),
        tower_x=7.45573,
        tower_y=219.877,
        tower_width=240.0,
        purge_volume=30.0,
    )
    containment_checks = {"pruned": 0, "exhaustive": 0}
    original_rect_allowed = wipe_tower_placement._rect_allowed

    def _counting(mode: str):
        def _rect_allowed(rect: Rect, request: WipeTowerPlacementRequest) -> bool:
            containment_checks[mode] += 1
            return original_rect_allowed(rect, request)

        return _rect_allowed

    with patch.object(wipe_tower_placement, "_rect_allowed", _counting("pruned")):
        solve_wipe_tower_placement(request)
    with patch.object(wipe_tower_placement, "_rect_allowed", _counting("exhaustive")), _exhaustive_search():
        solve_wipe_tower_placement(request)

    # Guard the export hot path: every Bambu 3MF export runs this solver.
    assert containment_checks["pruned"] * 10 <= containment_checks["exhaustive"]
