"""Regression tests: a top-center loop must stay connected on sloped edges.

The reviewer repro uses a 90 mm body whose top edge falls 0.75 mm per mm to
the right. Anchoring the loop at the highest contour point under the band
left it tangent at one corner; the loop must instead overlap the body across
its width while the hole stays outside the body.
"""

import numpy as np
import pytest
import trimesh
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from core.geometry_utils import create_keychain_loop, keychain_loop_hole_clearance
from core.pipeline.s05_preview_generation import _calculate_loop_position
from core.pipeline.vector_branch import _vector_loop_attach_point

LOOP_WIDTH = 7.0
LOOP_LENGTH = 13.5
LOOP_HOLE = 2.5
BODY_THICKNESS = 1.2
# Minimum shared area for a usable joint; a corner tangent is ~1e-13 mm^2.
MIN_CONNECTION_AREA_MM2 = 5.0


def _slope_body() -> Polygon:
    # SVG path M0 0 L120 90 V120 H0Z scaled to 90 mm, Y pointing up.
    return Polygon([(0.0, 0.0), (90.0, 0.0), (90.0, 22.5), (0.0, 90.0)])


def _slope_scene() -> trimesh.Scene:
    scene = trimesh.Scene()
    body = trimesh.creation.extrude_polygon(_slope_body(), BODY_THICKNESS)
    scene.add_geometry(body, geom_name="body")
    return scene


def _loop_footprint(attach_x: float, attach_y: float) -> tuple[Polygon, Polygon]:
    """Return the loop's solid XY cross-section and its hole disk."""
    mesh = create_keychain_loop(
        LOOP_WIDTH, LOOP_LENGTH, LOOP_HOLE, BODY_THICKNESS, attach_x, attach_y
    )
    section = mesh.section(
        plane_origin=[0.0, 0.0, BODY_THICKNESS / 2.0], plane_normal=[0.0, 0.0, 1.0]
    )
    # Even-odd fill: the hole ring cancels the outer ring's interior.
    solid = Polygon()
    for curve in section.discrete:
        solid = solid.symmetric_difference(Polygon(curve[:, :2]))
    hole_center_y = attach_y + (LOOP_LENGTH - LOOP_WIDTH / 2.0)
    hole = Point(attach_x, hole_center_y).buffer(LOOP_HOLE / 2.0, 64)
    return solid, hole


def _assert_connected_and_hole_clear(
    body: Polygon, attach_x: float, attach_y: float
) -> None:
    solid, hole = _loop_footprint(attach_x, attach_y)
    assert solid.intersection(body).area >= MIN_CONNECTION_AREA_MM2
    assert hole.intersection(body).area <= 1e-9


@pytest.mark.parametrize("offset_y", [0.0, -35.0])
def test_vector_loop_overlaps_sloped_edge_instead_of_touching_a_corner(
    offset_y: float,
) -> None:
    scene = _slope_scene()
    attach_x, attach_y = _vector_loop_attach_point(
        {
            "loop_position_preset": "top-center",
            "loop_width": LOOP_WIDTH,
            "loop_length": LOOP_LENGTH,
            "loop_hole": LOOP_HOLE,
            "loop_offset_x": 0.0,
            "loop_offset_y": offset_y,
        },
        np.asarray(scene.bounds, dtype=np.float64),
        scene,
    )

    # Lowest contour point under the band x in [41.5, 48.5] is 90 - 0.75 * 48.5.
    assert attach_x == pytest.approx(45.0)
    assert attach_y == pytest.approx(53.225)
    _assert_connected_and_hole_clear(_slope_body(), attach_x, attach_y)


def test_vector_loop_on_steep_edge_sinks_only_until_the_hole_clearance() -> None:
    steep = Polygon([(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (10.0, 40.0), (0.0, 40.0)])
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.extrude_polygon(steep, BODY_THICKNESS))
    attach_x, attach_y = _vector_loop_attach_point(
        {
            "loop_position_preset": "top-center",
            "loop_width": LOOP_WIDTH,
            "loop_length": LOOP_LENGTH,
            "loop_hole": LOOP_HOLE,
            "loop_offset_x": 0.0,
        },
        np.asarray(scene.bounds, dtype=np.float64),
        scene,
    )

    # Band [6.5, 13.5] spans top Y 40 .. 29.5; sinking to 29.5 would push the
    # hole into the body, so the loop stops one hole clearance below 40.
    clearance = keychain_loop_hole_clearance(LOOP_WIDTH, LOOP_LENGTH, LOOP_HOLE)
    assert attach_y == pytest.approx(40.0 - clearance)
    _assert_connected_and_hole_clear(steep, attach_x, attach_y)


def _slope_mask(size: int) -> np.ndarray:
    rows = np.arange(size)[:, None]
    cols = np.arange(size)[None, :]
    # Image row 0 is the top; the solid top edge drops 0.75 px per column.
    return rows >= np.floor(0.75 * cols)


def _mask_polygon(mask: np.ndarray, pixel_scale: float) -> Polygon:
    height = mask.shape[0]
    cells = [
        box(col * pixel_scale, (height - row - 1) * pixel_scale,
            (col + 1) * pixel_scale, (height - row) * pixel_scale)
        for row, col in zip(*np.nonzero(mask))
    ]
    return unary_union(cells)


@pytest.mark.parametrize("offset_y", [0.0, -35.0])
def test_raster_loop_overlaps_sloped_edge_instead_of_touching_a_corner(
    offset_y: float,
) -> None:
    mask = _slope_mask(60)
    pixel_scale = 1.5
    attach_x, attach_y = _calculate_loop_position(
        "top-center",
        0.0,
        offset_y,
        mask,
        60,
        60,
        pixel_scale,
        contact_width_mm=LOOP_WIDTH,
        hole_clearance_mm=keychain_loop_hole_clearance(
            LOOP_WIDTH, LOOP_LENGTH, LOOP_HOLE
        ),
    )

    _assert_connected_and_hole_clear(
        _mask_polygon(mask, pixel_scale), attach_x, attach_y
    )
