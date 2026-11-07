"""Unit tests for puzzle layout construction."""

from __future__ import annotations

import json
import numpy as np
import pytest
from shapely.affinity import translate
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from core.puzzle import (
    PuzzleLayoutConfig,
    PuzzlePiece,
    _build_connector_points,
    build_puzzle_layout,
    export_piece_boundary_geometry,
    rasterize_piece_mask,
    render_puzzle_overlay,
    resolve_puzzle_mask_geometry,
)


def _make_config(seed: int) -> PuzzleLayoutConfig:
    return PuzzleLayoutConfig(
        width_px=120,
        height_px=80,
        total_width_mm=90.0,
        total_height_mm=60.0,
        style="irregular",
        sizing_mode="grid",
        rows=2,
        cols=3,
        seed=seed,
        connector_style="classic",
        irregularity_strength=0.35,
        min_neck_width_mm=1.2,
    )


def test_irregular_layout_is_deterministic_for_same_seed() -> None:
    """Identical seeds should produce identical piece polygons."""

    layout_a = build_puzzle_layout(_make_config(seed=17))
    layout_b = build_puzzle_layout(_make_config(seed=17))

    assert layout_a.rows == layout_b.rows == 2
    assert layout_a.cols == layout_b.cols == 3
    assert tuple(piece.label for piece in layout_a.pieces) == tuple(
        piece.label for piece in layout_b.pieces
    )
    assert tuple(piece.polygon_px for piece in layout_a.pieces) == tuple(
        piece.polygon_px for piece in layout_b.pieces
    )


def test_irregular_layout_changes_when_seed_changes() -> None:
    """Different seeds should perturb the layout geometry."""

    layout_a = build_puzzle_layout(_make_config(seed=17))
    layout_b = build_puzzle_layout(_make_config(seed=18))

    assert layout_a.rows == layout_b.rows == 2
    assert layout_a.cols == layout_b.cols == 3
    assert tuple(piece.polygon_px for piece in layout_a.pieces) != tuple(
        piece.polygon_px for piece in layout_b.pieces
    )


def test_piece_labels_use_spreadsheet_style_names() -> None:
    """Piece labels should use A1/B2-style names for UI and export stability."""

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=160,
            height_px=120,
            total_width_mm=80.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=2,
            cols=3,
            seed=3,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )

    assert [piece.label for piece in layout.pieces] == ["A1", "A2", "A3", "B1", "B2", "B3"]


def test_render_puzzle_overlay_respects_visibility_mask() -> None:
    """Overlay pixels outside the solid alpha mask should remain transparent."""

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=80,
            total_width_mm=90.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=2,
            cols=2,
            seed=5,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )

    visibility_mask = np.zeros((80, 120), dtype=bool)
    visibility_mask[:, 60:] = True

    overlay = render_puzzle_overlay(layout, visibility_mask=visibility_mask)
    overlay_rgba = np.array(overlay)

    assert np.all(overlay_rgba[:, :60, 3] == 0)
    assert np.any(overlay_rgba[:, 60:, 3] > 0)


def test_render_puzzle_overlay_keeps_mask_boundary_line_visible() -> None:
    """Visibility mask must not shave the line drawn on the solid boundary."""

    visibility_mask = np.zeros((320, 640), dtype=bool)
    visibility_mask[40:280, 60:580] = True

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=640,
            height_px=320,
            total_width_mm=120.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=1,
            cols=1,
            seed=5,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
            solid_mask=visibility_mask,
        )
    )

    overlay = render_puzzle_overlay(layout, visibility_mask=visibility_mask)
    overlay_rgba = np.array(overlay)

    assert layout.layout_mode == "mask_aware"
    assert np.any(overlay_rgba[39, 60:580, 3] > 0)
    assert np.any(overlay_rgba[280, 60:580, 3] > 0)
    assert np.any(overlay_rgba[40:280, 60, 3] > 0)
    assert np.any(overlay_rgba[40:280, 579, 3] > 0)
    assert np.all(overlay_rgba[:37, :, 3] == 0)
    assert np.all(overlay_rgba[:, :57, 3] == 0)


def test_render_puzzle_overlay_keeps_rectangular_outer_edges_visible() -> None:
    """Rectangular puzzle overlay should keep all four outer edges on-canvas."""

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=600,
            height_px=600,
            total_width_mm=60.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=3,
            cols=3,
            seed=5,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )

    overlay = render_puzzle_overlay(layout)
    alpha = np.array(overlay)[..., 3] > 0

    assert alpha[0, :].sum() == 600
    assert alpha[-1, :].sum() == 600
    assert alpha[:, 0].sum() == 600
    assert alpha[:, -1].sum() == 600


def test_export_piece_boundary_geometry_round_trips_absolute_coordinates() -> None:
    """Boundary export should preserve the original absolute polygon after roundtrip."""

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=80,
            total_width_mm=90.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=1,
            cols=2,
            seed=5,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )
    piece = layout.pieces[0]

    payload = export_piece_boundary_geometry(piece)
    assert json.loads(json.dumps(payload)) == payload
    assert payload["bbox_px"] == list(piece.bbox_px)
    assert payload["holes_px"] == []

    x0, y0, x1, y1 = payload["bbox_px"]
    local_width = x1 - x0
    local_height = y1 - y0

    for px, py in payload["polygon_px"]:
        assert 0.0 <= px <= local_width
        assert 0.0 <= py <= local_height

    reconstructed = [(px + x0, py + y0) for px, py in payload["polygon_px"]]
    assert np.allclose(reconstructed, piece.polygon_px)


def test_export_piece_boundary_geometry_is_stable_for_every_piece() -> None:
    """Every generated piece should export crop-local JSON that round-trips cleanly."""

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=160,
            height_px=120,
            total_width_mm=80.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=2,
            cols=3,
            seed=3,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )

    for piece in layout.pieces:
        payload = export_piece_boundary_geometry(piece)
        assert json.loads(json.dumps(payload)) == payload
        assert payload["bbox_px"] == list(piece.bbox_px)
        assert set(payload) == {"bbox_px", "polygon_px", "holes_px"}

        x0, y0, x1, y1 = payload["bbox_px"]
        local_width = x1 - x0
        local_height = y1 - y0
        assert len(payload["polygon_px"]) >= 3
        for px, py in payload["polygon_px"]:
            assert 0.0 <= px <= local_width
            assert 0.0 <= py <= local_height
        for hole in payload["holes_px"]:
            for px, py in hole:
                assert 0.0 <= px <= local_width
                assert 0.0 <= py <= local_height


def test_export_piece_boundary_geometry_preserves_holes_in_crop_local_space() -> None:
    """Hole rings should be exported relative to the crop origin, not world origin."""

    piece = PuzzlePiece(
        row=1,
        col=1,
        label="A1",
        polygon_px=((10.0, 20.0), (34.0, 20.0), (34.0, 44.0), (10.0, 44.0)),
        bbox_px=(10, 20, 36, 46),
        bbox_mm=(1.0, 2.0, 3.0, 4.0),
        centroid_mm=(2.0, 3.0),
        holes_px=(((14.0, 24.0), (30.0, 24.0), (30.0, 40.0), (14.0, 40.0)),),
    )

    payload = export_piece_boundary_geometry(piece)
    assert payload["bbox_px"] == [10, 20, 36, 46]
    assert len(payload["holes_px"]) == 1

    outer_local = payload["polygon_px"]
    hole_local = payload["holes_px"][0]
    assert outer_local == [[0.0, 0.0], [24.0, 0.0], [24.0, 24.0], [0.0, 24.0]]
    assert hole_local == [[4.0, 4.0], [20.0, 4.0], [20.0, 20.0], [4.0, 20.0]]

    roundtrip_outer = [(px + 10.0, py + 20.0) for px, py in outer_local]
    roundtrip_hole = [(px + 10.0, py + 20.0) for px, py in hole_local]
    assert np.allclose(roundtrip_outer, piece.polygon_px)
    assert np.allclose(roundtrip_hole, piece.holes_px[0])
    assert Polygon(roundtrip_outer, holes=(roundtrip_hole,)).is_valid


def test_mask_aware_layout_is_deterministic_for_same_seed() -> None:
    """Transparent-boundary layouts should stay deterministic for identical inputs."""

    yy, xx = np.ogrid[:120, :120]
    solid_mask = (xx - 60) ** 2 + (yy - 60) ** 2 <= 42**2
    config = PuzzleLayoutConfig(
        width_px=120,
        height_px=120,
        total_width_mm=90.0,
        total_height_mm=90.0,
        style="irregular",
        sizing_mode="grid",
        rows=3,
        cols=3,
        seed=13,
        connector_style="classic",
        irregularity_strength=0.35,
        min_neck_width_mm=1.2,
        solid_mask=solid_mask,
    )

    layout_a = build_puzzle_layout(config)
    layout_b = build_puzzle_layout(config)

    assert layout_a.layout_mode == "mask_aware"
    assert layout_a.actual_piece_count == layout_b.actual_piece_count
    assert tuple(piece.polygon_px for piece in layout_a.pieces) == tuple(
        piece.polygon_px for piece in layout_b.pieces
    )


def test_mask_aware_layout_merges_tiny_boundary_fragments() -> None:
    """Tiny transparent-boundary fragments should be merged away before export."""

    yy, xx = np.ogrid[:120, :120]
    solid_mask = (xx - 60) ** 2 + (yy - 60) ** 2 <= 42**2
    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=120,
            total_width_mm=90.0,
            total_height_mm=90.0,
            style="regular",
            sizing_mode="grid",
            rows=3,
            cols=3,
            seed=5,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
            solid_mask=solid_mask,
        )
    )

    assert layout.layout_mode == "mask_aware"
    assert layout.actual_piece_count <= 9
    min_piece_area = min(
        Polygon(piece.polygon_px, holes=piece.holes_px).area for piece in layout.pieces
    )
    assert min_piece_area >= float(np.count_nonzero(solid_mask)) / 9 * 0.12


def test_regular_layout_internal_edge_uses_interlocking_tab_geometry() -> None:
    """Regular layouts should let one side protrude beyond the raw cell divider."""

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=80,
            total_width_mm=90.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=1,
            cols=2,
            seed=5,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )

    divider_x = 60.0
    left_piece = layout.pieces[0]
    right_piece = layout.pieces[1]
    left_max_x = max(point[0] for point in left_piece.polygon_px)
    right_min_x = min(point[0] for point in right_piece.polygon_px)

    assert left_max_x > divider_x + 1.0 or right_min_x < divider_x - 1.0


def test_adjacent_interlocking_pieces_share_boundary_without_overlap() -> None:
    """Two neighboring pieces should still tile the original rectangle exactly."""

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=80,
            total_width_mm=90.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=1,
            cols=2,
            seed=5,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )

    left_polygon = Polygon(layout.pieces[0].polygon_px)
    right_polygon = Polygon(layout.pieces[1].polygon_px)
    tiled_union = unary_union((left_polygon, right_polygon))
    bounding_rect = Polygon(((0.0, 0.0), (120.0, 0.0), (120.0, 80.0), (0.0, 80.0)))

    assert left_polygon.intersection(right_polygon).area <= 1e-6
    assert tiled_union.symmetric_difference(bounding_rect).area <= 1e-6


def test_classic_connector_protrudes_more_than_easy_cut() -> None:
    """Classic connector profile should create a larger tab than easy-cut."""

    classic_points, classic_used = _build_connector_points(
        (0.0, 0.0),
        (100.0, 0.0),
        1,
        "classic",
        3.0,
    )
    easy_points, easy_used = _build_connector_points(
        (0.0, 0.0),
        (100.0, 0.0),
        1,
        "easy_cut",
        3.0,
    )

    assert classic_used
    assert easy_used
    classic_peak = max(point[1] for point in classic_points)
    easy_peak = max(point[1] for point in easy_points)

    assert classic_peak > easy_peak > 0.0


def test_too_short_edge_degrades_to_straight_with_warning() -> None:
    """Short internal edges should fall back to straight boundaries with a warning."""

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=60,
            height_px=36,
            total_width_mm=60.0,
            total_height_mm=36.0,
            style="regular",
            sizing_mode="grid",
            rows=1,
            cols=2,
            seed=0,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=10.0,
        )
    )

    left_piece = layout.pieces[0]
    right_piece = layout.pieces[1]

    assert max(point[0] for point in left_piece.polygon_px) == pytest.approx(30.0)
    assert min(point[0] for point in right_piece.polygon_px) == pytest.approx(30.0)
    assert any("too small for interlocking tabs" in warning for warning in layout.warnings)


def test_mask_aware_layout_keeps_outer_boundary_inside_solid_mask() -> None:
    """Transparent-boundary layouts should not protrude tabs beyond the solid silhouette."""

    yy, xx = np.ogrid[:120, :120]
    solid_mask = (xx - 60) ** 2 + (yy - 60) ** 2 <= 42**2
    config = PuzzleLayoutConfig(
        width_px=120,
        height_px=120,
        total_width_mm=90.0,
        total_height_mm=90.0,
        style="regular",
        sizing_mode="grid",
        rows=3,
        cols=3,
        seed=0,
        connector_style="classic",
        irregularity_strength=0.35,
        min_neck_width_mm=1.2,
        solid_mask=solid_mask,
    )

    layout = build_puzzle_layout(config)
    mask_geometry = resolve_puzzle_mask_geometry(config)
    piece_union = unary_union(
        [Polygon(piece.polygon_px, holes=piece.holes_px) for piece in layout.pieces]
    )

    assert mask_geometry is not None
    assert piece_union.difference(mask_geometry).area <= 1e-6


def test_cut_clearance_preserves_outline_and_holes_even_where_a_joint_crosses_one() -> None:
    mask = np.ones((24, 40), dtype=bool)
    mask[8:16, 16:24] = False  # The vertical cut crosses this opening.
    mask[3:6, 5:8] = False  # This one belongs entirely to the left piece.
    layout = build_puzzle_layout(PuzzleLayoutConfig(
        width_px=40, height_px=24, total_width_mm=4, total_height_mm=2.4,
        sizing_mode="grid", rows=1, cols=2, solid_mask=mask,
    ))
    printed = []
    for piece in layout.pieces:
        boundary = export_piece_boundary_geometry(piece, inset_px=0.5)
        printed.append(translate(
            Polygon(boundary["polygon_px"], boundary["holes_px"]),
            xoff=piece.bbox_px[0], yoff=piece.bbox_px[1],
        ))

    # At 10 pixels/mm the only missing material is the 0.10 mm joint.
    source = box(0, 0, 40, 24).difference(box(16, 8, 24, 16)).difference(box(5, 3, 8, 6))
    expected = source.difference(box(19.5, 0, 20.5, 24))
    assert len(printed) == 2
    assert printed[0].distance(printed[1]) == pytest.approx(1.0)
    assert unary_union(printed).symmetric_difference(expected).area == pytest.approx(0.0)


def test_pixel_ownership_round_trips_holes_and_disconnected_islands() -> None:
    mask = np.zeros((40, 40), dtype=bool)
    mask[2:32, 3:31] = True
    mask[9:17, 10:20] = False
    mask[12:15, 13:17] = True  # An independent island surrounded by the hole.
    mask[32:35, 31:34] = True  # This island touches the first at one corner.
    layout = build_puzzle_layout(PuzzleLayoutConfig(
        width_px=40, height_px=40, total_width_mm=4, total_height_mm=4,
        sizing_mode="grid", rows=1, cols=1, solid_mask=mask,
    ))
    owners = np.zeros(mask.shape, dtype=np.uint8)
    for piece in layout.pieces:
        (x0, y0, x1, y1), owned = rasterize_piece_mask(piece)
        owners[y0:y1, x0:x1] += owned != 0
    np.testing.assert_array_equal(owners, mask)


def test_regular_layout_stabilizes_invalid_connector_combinations() -> None:
    """Regular grids should not emit self-intersecting piece polygons."""

    for seed in range(6):
        layout = build_puzzle_layout(
            PuzzleLayoutConfig(
                width_px=160,
                height_px=120,
                total_width_mm=80.0,
                total_height_mm=60.0,
                style="regular",
                sizing_mode="grid",
                rows=3,
                cols=4,
                seed=seed,
                connector_style="classic",
                irregularity_strength=0.35,
                min_neck_width_mm=1.2,
            )
        )
        for piece in layout.pieces:
            polygon = Polygon(piece.polygon_px, holes=piece.holes_px)
            assert polygon.is_valid, piece.label


def test_rasterized_piece_mask_preserves_connector_protrusion() -> None:
    """Rasterized masks should preserve the sampled tab geometry."""

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=80,
            total_width_mm=90.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=1,
            cols=2,
            seed=0,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )

    _bbox, left_mask = rasterize_piece_mask(layout.pieces[0])
    assert _bbox == layout.pieces[0].bbox_px

    filled_rows = np.any(left_mask > 0, axis=1)
    rightmost_by_row = left_mask.shape[1] - np.argmax(left_mask[:, ::-1] > 0, axis=1) - 1
    curved_rows = rightmost_by_row[filled_rows]

    assert len(np.unique(curved_rows)) >= 4
