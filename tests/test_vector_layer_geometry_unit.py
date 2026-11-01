"""Constructive mesh contracts for native Vector layer runs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box

import core.vector_layer_geometry as vector_layer_geometry
from core.vector_layer_geometry import (
    VectorLayerGeometryPolicy,
    build_vector_layered_volume,
    resolve_vector_writer_grid_mm,
    snap_vector_writer_coordinate_mm,
)


def _edge_incidence_counts(mesh) -> np.ndarray:
    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    _unique, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


def _assert_closed_volume(
    mesh,
    expected_volume: float,
    *,
    volume_tolerance: float = 1e-3,
) -> None:
    assert mesh is not None
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(
        expected_volume,
        abs=volume_tolerance,
    )
    writer_vertices = np.asarray(mesh.vertices, dtype=np.float32)
    writer_faces = np.asarray(mesh.faces, dtype=np.int64)
    writer_triangles = writer_vertices[writer_faces]
    writer_cross = np.cross(
        writer_triangles[:, 1] - writer_triangles[:, 0],
        writer_triangles[:, 2] - writer_triangles[:, 0],
    )
    assert not np.any(np.all(writer_cross == 0.0, axis=1))


def test_writer_grid_is_at_least_four_float32_ulps() -> None:
    grid = resolve_vector_writer_grid_mm(200.0)

    assert 0.0001 <= grid < 0.0002
    assert grid >= abs(float(np.spacing(np.float32(200.0)))) * 4.0
    snapped = snap_vector_writer_coordinate_mm(1.23456, grid_mm=grid)
    assert snapped / grid == pytest.approx(round(snapped / grid), abs=1e-9)


@pytest.mark.parametrize("extent_mm", [1.0, 200.0, 230.0, 1024.0, 10000.0])
def test_print_grid_coordinates_survive_writer_without_rounding(
    extent_mm: float,
) -> None:
    grid = resolve_vector_writer_grid_mm(extent_mm)
    limit = int(extent_mm / grid)
    units = np.asarray([0, 1, -1, limit // 3, limit - 1, limit, -limit])
    coordinates = units * grid

    assert np.array_equal(coordinates, coordinates.astype(np.float32).astype(np.float64))


def test_thin_positive_cap_at_large_xy_survives_export_grid() -> None:
    # Minimal three-point ear from a failing 230 mm SVG, without the artwork.
    source = np.asarray(
        [(1480096, 2269274), (1479777, 2268888), (1479664, 2268751)],
        dtype=np.float64,
    ) * 0.0001
    grid = resolve_vector_writer_grid_mm(230.0)
    projected = np.floor(source / grid + 0.5) * grid
    faces = vector_layer_geometry._expand_writer_degenerate_cap_faces(
        projected, np.asarray([(0, 1, 2)]), grid_mm=grid,
    )

    written = projected.astype(np.float32).astype(np.float64)
    assert np.array_equal(written, projected)
    assert Polygon(written[faces[0]]).area > 0


def test_exact_writer_triangle_is_not_rejected_by_float32_area_arithmetic() -> None:
    grid = 2.0 ** -13
    vertices = np.asarray(
        [(0, 0), (2000000, 1999999), (1999999, 1999998)], dtype=np.float64,
    ) * grid
    faces = np.asarray([(0, 1, 2)], dtype=np.int64)
    assert np.array_equal(vertices, vertices.astype(np.float32).astype(np.float64))
    assert Polygon(vertices).area > 0

    result = vector_layer_geometry._expand_writer_degenerate_cap_faces(
        vertices, faces, grid_mm=grid,
    )

    assert np.array_equal(result, faces)


def test_single_polygon_with_hole_is_one_closed_prism() -> None:
    source = Polygon(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        holes=[[(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)]],
    )

    mesh = build_vector_layered_volume(
        [{"geometry": source, "z_offset": 0.4, "height": 0.2}],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, source.area * 0.2, volume_tolerance=1e-8)
    assert mesh.metadata["vector_layer_geometry"]["component_count"] == 1


def test_canonical_cap_preserves_touching_holes_when_geos_ear_scan_stalls() -> None:
    # Reduced integer rings from a failing cap, without the source SVG. Keep
    # their canonical start/order: GEOS's failure depends on ring traversal.
    source = shapely.from_wkt((
        Path(__file__).parent / "fixtures/svg_regression/touching_holes_cap.wkt"
    ).read_text())
    assert source.is_valid
    polygon = vector_layer_geometry._IndexedPolygon(
        np.asarray(source.exterior.coords[:-1], dtype=np.int64),
        tuple(np.asarray(hole.coords[:-1], dtype=np.int64) for hole in source.interiors),
    )
    polygon = vector_layer_geometry._node_indexed_polygon_ring_contacts(polygon)
    prepared = vector_layer_geometry._IndexedRunGroup(
        (polygon,), 1.0, source.area,
        len(polygon.exterior_units) + sum(map(len, polygon.hole_units)),
        len(polygon.hole_units),
    )

    mesh = vector_layer_geometry._extrude_indexed_run_group(
        prepared, height_mm=0.08, z_offset_mm=0.4,
    )

    _assert_closed_volume(mesh, source.area * 0.08, volume_tolerance=1e-8)
    triangles = mesh.triangles
    top = triangles[
        np.all(np.isclose(triangles[:, :, 2], 0.48, rtol=0, atol=1e-12), axis=1), :, :2
    ]
    assert shapely.union_all([Polygon(triangle) for triangle in top]).equals(source)


def test_svg_scale_is_applied_before_integer_grid_conversion() -> None:
    source = box(10.0, 20.0, 30.0, 50.0)

    mesh = build_vector_layered_volume(
        [{"geometry": source, "z_offset": 0.0, "height": 0.08}],
        scale_mm_per_svg_unit=0.5,
    )

    _assert_closed_volume(mesh, source.area * 0.25 * 0.08)
    assert mesh.bounds == pytest.approx(
        np.asarray([[5.0, 10.0, 0.0], [15.0, 25.0, 0.08]]),
        abs=1e-7,
    )


def test_equal_adjacent_runs_fold_into_one_taller_prism() -> None:
    source = box(0.0, 0.0, 4.0, 3.0)

    mesh = build_vector_layered_volume(
        [
            {"geometry": source, "z_offset": 0.0, "height": 0.08},
            {"geometry": source, "z_offset": 0.08, "height": 0.08},
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, source.area * 0.16, volume_tolerance=1e-8)
    triangles = np.asarray(mesh.vertices)[np.asarray(mesh.faces, dtype=np.int64)]
    internal_caps = np.all(
        np.isclose(triangles[:, :, 2], 0.08, rtol=0.0, atol=1e-12),
        axis=1,
    )
    assert not np.any(internal_caps)
    assert mesh.metadata["vector_layer_geometry"]["component_count"] == 1


def test_prepared_fragments_remain_independent_closed_shells() -> None:
    left = box(0.0, 0.0, 2.0, 2.0)
    right = box(2.0, 0.0, 4.0, 2.0)

    mesh = build_vector_layered_volume(
        [
            {"geometry": left, "z_offset": 0.0, "height": 0.08},
            {"geometry": right, "z_offset": 0.0, "height": 0.08},
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, (left.area + right.area) * 0.08)
    assert len(mesh.split(only_watertight=False)) == 2


def test_remote_islands_stay_in_one_material_object_as_independent_shells() -> None:
    body = box(0.0, 0.0, 200.0, 200.0)
    island = box(210.0, 0.0, 215.0, 5.0)

    mesh = build_vector_layered_volume(
        [
            {
                "geometry": MultiPolygon([body, island]),
                "z_offset": 0.0,
                "height": 0.2,
            }
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, (body.area + island.area) * 0.2)
    assert len(mesh.split(only_watertight=False)) == 2


def test_corner_touching_shells_keep_independent_indices_without_motion() -> None:
    mesh = build_vector_layered_volume(
        [
            {"geometry": box(0.0, 0.0, 1.0, 1.0), "z_offset": 0.0, "height": 1.0},
            {"geometry": box(1.0, 1.0, 2.0, 2.0), "z_offset": 0.0, "height": 1.8},
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, 2.8)
    assert len(mesh.split(only_watertight=False)) == 2
    writer_vertices = np.asarray(mesh.vertices, dtype=np.float32)
    shared_bottom_corner = np.all(
        writer_vertices == np.asarray([1.0, 1.0, 0.0], dtype=np.float32),
        axis=1,
    )
    assert np.count_nonzero(shared_bottom_corner) == 2


def test_submicron_island_may_snap_to_other_shell_edge_without_welding() -> None:
    float32_gap = 9.5367431640625e-7
    body = box(0.0, 0.0, 200.0, 200.0)
    island = Polygon(
        [
            (200.0 + float32_gap, 100.0),
            (201.0, 99.0),
            (201.0, 101.0),
        ]
    )

    mesh = build_vector_layered_volume(
        [
            {
                "geometry": MultiPolygon([body, island]),
                "z_offset": 0.0,
                "height": 0.08,
            }
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, (body.area + island.area) * 0.08)
    writer_vertices = np.asarray(mesh.vertices, dtype=np.float32)
    snapped_contact = np.all(
        writer_vertices == np.asarray([200.0, 100.0, 0.0], dtype=np.float32),
        axis=1,
    )
    assert np.count_nonzero(snapped_contact) == 1
    assert len(mesh.split(only_watertight=False)) == 2


def test_layered_cavity_preserves_every_run_volume() -> None:
    outer = box(0.0, 0.0, 10.0, 10.0)
    cavity = box(4.0, 4.0, 6.0, 6.0)

    mesh = build_vector_layered_volume(
        [
            {"geometry": outer, "z_offset": 0.0, "height": 0.4},
            {"geometry": outer.difference(cavity), "z_offset": 0.4, "height": 0.6},
            {"geometry": outer, "z_offset": 1.0, "height": 0.4},
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, 137.6)


def test_prepared_overlapping_slabs_remain_independent_closed_shells() -> None:
    first = box(0.0, 0.0, 2.0, 2.0)
    second = box(1.0, 0.0, 3.0, 2.0)

    mesh = build_vector_layered_volume(
        [
            {"geometry": first, "z_offset": 0.0, "height": 0.16},
            {"geometry": second, "z_offset": 0.08, "height": 0.16},
        ],
        scale_mm_per_svg_unit=1.0,
    )

    expected = first.area * 0.16 + second.area * 0.16
    _assert_closed_volume(mesh, expected)
    assert len(mesh.split(only_watertight=False)) == 2
    assert mesh.metadata["vector_layer_geometry"]["component_count"] == 2


def test_different_run_bounds_remain_independently_closed() -> None:
    left = Polygon([(0.0, 0.0), (5.0, 0.0), (6.0, 10.0), (0.0, 10.0)])
    shared = (5.5 + 1e-12, 5.0)
    right_lower = Polygon([(5.0, 0.0), (10.0, 0.0), (10.0, 5.0), shared])
    right_upper = Polygon([shared, (10.0, 5.0), (10.0, 10.0), (6.0, 10.0)])

    mesh = build_vector_layered_volume(
        [
            {"geometry": left, "z_offset": 0.0, "height": 1.8},
            {"geometry": right_lower, "z_offset": 0.0, "height": 0.8},
            {"geometry": right_upper, "z_offset": 0.0, "height": 1.4},
        ],
        scale_mm_per_svg_unit=1.0,
    )

    expected = left.area * 1.8 + right_lower.area * 0.8 + right_upper.area * 1.4
    _assert_closed_volume(mesh, expected)


@pytest.mark.parametrize(
    ("source", "contact"),
    [
        (
            Polygon(
                [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
                holes=[[(5.0, 0.0), (6.0, 1.0), (4.0, 1.0)]],
            ),
            (5.0, 0.0),
        ),
        (
            Polygon(
                [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
                holes=[
                    [(2.0, 2.0), (5.0, 5.0), (2.0, 8.0)],
                    [(8.0, 2.0), (8.0, 8.0), (5.0, 5.0)],
                ],
            ),
            (5.0, 5.0),
        ),
    ],
    ids=("hole_touches_shell", "holes_touch_each_other"),
)
def test_point_touching_rings_split_cap_fans_without_moving_geometry(
    source: Polygon,
    contact: tuple[float, float],
) -> None:
    mesh = build_vector_layered_volume(
        [{"geometry": source, "z_offset": 0.0, "height": 0.2}],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, source.area * 0.2)
    contact_units = np.rint(np.asarray(contact) / 0.0001).astype(np.int64)
    vertex_units = np.rint(
        np.asarray(mesh.vertices)[:, :2] / 0.0001
    ).astype(np.int64)
    contact_vertices = np.all(vertex_units == contact_units, axis=1)
    # Each material fan owns an independent top/bottom index at the exact
    # source contact. No ring is translated to manufacture a gap.
    assert int(np.count_nonzero(contact_vertices)) >= 4


def test_real_touching_hole_fixture_stays_closed() -> None:
    shell = [
        (0.6686, 0.0246), (0.6629, 0.0251), (0.0081, 0.3528),
        (0.0081, 2.4854), (0.0378, 2.4928), (2.2483, 0.7548),
        (2.2681, 0.7229), (2.2604, 0.6535), (2.2239, 0.6203),
        (2.1627, 0.6230), (2.0140, 0.6883), (1.9758, 0.6796),
        (1.9614, 0.6663), (1.9471, 0.6529), (1.9357, 0.6155),
        (1.9446, 0.5775), (2.0617, 0.3575), (2.0588, 0.3211),
        (2.0402, 0.2898), (2.0193, 0.2824), (1.9985, 0.2749),
        (1.5769, 0.3303), (1.5311, 0.2770), (1.5154, 0.1532),
        (1.4682, 0.1183), (1.4329, 0.1263), (0.5746, 0.6397),
        (0.5415, 0.6453), (0.5372, 0.6426), (0.5133, 0.6272),
        (0.5094, 0.6122), (0.5041, 0.6053), (0.5048, 0.5946),
        (0.5016, 0.5821), (0.5070, 0.5652), (0.5082, 0.5477),
        (0.5145, 0.5417), (0.5192, 0.5270), (0.6242, 0.4359),
        (0.6622, 0.3992), (0.7574, 0.2684), (0.8182, 0.0894),
        (0.8328, 0.0260), (0.8096, 0.0), (0.7400, 0.0),
        (0.7216, 0.0202),
    ]
    hole = [(0.5333, 0.6429), (0.5289, 0.6373), (0.5372, 0.6426)]
    source = Polygon(shell, holes=[hole])

    mesh = build_vector_layered_volume(
        [{"geometry": source, "z_offset": 0.0, "height": 0.08}],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, source.area * 0.08)


def test_holed_cap_is_independent_of_arbitrary_ring_starts() -> None:
    shell = [
        (-2.54, -56.96),
        (-1.62, -58.47),
        (25.44, 100.77),
        (0.16, 76.39),
    ]
    holes = [
        [(2.65, 1.67), (2.39, 1.54), (0.58, 0.64), (1.6, 1.15)],
        [(0.49, 2.95), (1.6, 1.15), (0.5, 2.93)],
        [(0.65, 0.74), (0.58, 0.64), (0.64, 0.73)],
        [(0.1, 0.43), (0.58, 0.64), (0.02, 0.38)],
        [(0.66, 1.47), (0.96, 1.26), (0.63, 1.49)],
    ]
    source = Polygon(shell, holes=holes)
    rotated_source = Polygon(
        shell[1:] + shell[:1],
        holes=[ring[1:] + ring[:1] for ring in holes],
    )

    assert source.is_valid
    assert rotated_source.equals(source)

    meshes = [
        build_vector_layered_volume(
            [{"geometry": geometry, "z_offset": 0.0, "height": 0.08}],
            scale_mm_per_svg_unit=1.0,
        )
        for geometry in (source, rotated_source)
    ]

    for mesh in meshes:
        _assert_closed_volume(mesh, source.area * 0.08)


def test_collinear_ear_keeps_every_boundary_segment() -> None:
    source = Polygon(
        [
            (1.6296, 152.8639),
            (1.6443, 152.8972),
            (1.6590, 152.9305),
            (0.9335, 151.9195),
        ]
    )

    mesh = build_vector_layered_volume(
        [{"geometry": source, "z_offset": 0.0, "height": 0.08}],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, source.area * 0.08)


def test_integer_ring_compaction_removes_only_straight_interior_nodes() -> None:
    units = np.asarray(
        [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1), (0, 1)],
        dtype=np.int64,
    )

    compact = vector_layer_geometry._remove_redundant_ring_units(units)

    assert compact.tolist() == [[0, 0], [2, 0], [2, 1], [0, 1]]


def test_exact_integer_zero_area_ear_is_replaced_by_positive_faces() -> None:
    vertices = np.asarray(
        [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)],
        dtype=np.float64,
    )
    faces = np.asarray([(0, 1, 2), (0, 2, 4), (2, 3, 4)], dtype=np.int64)
    ring_ends = np.asarray([5], dtype=np.uint32)

    restored = vector_layer_geometry._restore_noded_cap_boundary(
        vertices,
        faces,
        ring_ends,
        grid_mm=1.0,
    )
    validated = vector_layer_geometry._validate_cap_indices(
        vertices,
        restored,
        ring_ends,
        expected_area_mm2=2.0,
        grid_mm=1.0,
    )

    assert len(validated.faces) == 3
    assert np.all(
        vector_layer_geometry._integer_triangle_signed_twice_area(
            vertices,
            validated.faces,
            grid_mm=1.0,
        )
        != 0
    )


def test_chained_zero_area_ears_are_expanded_from_the_supported_end() -> None:
    vertices = np.asarray(
        [
            (462519, 209568),
            (462442, 209645),
            (462201, 209886),
            (462153, 209934),
            (461034, 208843),
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [(1, 2, 3), (0, 1, 3), (0, 3, 4)],
        dtype=np.int64,
    )

    expanded = vector_layer_geometry._expand_writer_degenerate_cap_faces(
        vertices,
        faces,
        grid_mm=1.0,
    )
    areas = vector_layer_geometry._integer_triangle_signed_twice_area(
        vertices,
        expanded,
        grid_mm=1.0,
    )
    edges = np.sort(
        expanded[:, [[0, 1], [1, 2], [2, 0]]].reshape((-1, 2)),
        axis=1,
    )
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = unique_edges[counts == 1]

    assert np.all(areas != 0)
    assert [1, 2] in boundary.tolist()


def test_decimal_cap_preserves_area_without_float32_determinant_cancellation() -> None:
    units = np.asarray(
        [
            (816468, 368506),
            (816497, 368531),
            (819780, 371812),
            (817579, 369615),
        ],
        dtype=np.int64,
    )
    vertices = units.astype(np.float64) * 0.0001
    faces = np.asarray([(0, 1, 2), (0, 2, 3)], dtype=np.int64)
    source_area = np.sum(
        np.abs(
            vector_layer_geometry._integer_triangle_signed_twice_area(
                vertices,
                faces,
                grid_mm=0.0001,
            )
        ),
        dtype=np.int64,
    )
    assert vector_layer_geometry._triangle_signed_twice_area(
        vertices.astype(np.float32)[faces]
    )[1] == 0.0

    expanded = vector_layer_geometry._expand_writer_degenerate_cap_faces(
        vertices,
        faces,
        grid_mm=0.0001,
    )

    writer_areas = vector_layer_geometry._triangle_signed_twice_area(
        vertices.astype(np.float32).astype(np.float64)[expanded]
    )
    output_area = np.sum(
        np.abs(
            vector_layer_geometry._integer_triangle_signed_twice_area(
                vertices,
                expanded,
                grid_mm=0.0001,
            )
        ),
        dtype=np.int64,
    )
    assert np.all(writer_areas != 0.0)
    assert output_area == source_area


def test_writer_zero_residue_does_not_remove_a_printable_body() -> None:
    printable = box(0.0, 0.0, 10.0, 10.0)
    residue = Polygon([(11.0, 5.0), (11.00001, 5.0), (11.0, 5.00001)])

    mesh = build_vector_layered_volume(
        [
            {
                "geometry": MultiPolygon([printable, residue]),
                "z_offset": 0.0,
                "height": 0.08,
            }
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, printable.area * 0.08)


def test_make_valid_line_residue_does_not_reject_printable_collection() -> None:
    printable = box(0.0, 0.0, 10.0, 10.0)
    zero_area_residue = Polygon(
        [
            (11.0, 5.0),
            (11.0, 5.0 + 1e-15),
            (11.0, 5.0 + 2e-15),
            (11.0, 5.0),
        ]
    )
    assert not zero_area_residue.is_valid
    assert zero_area_residue.area == 0.0

    mesh = build_vector_layered_volume(
        [
            {
                "geometry": GeometryCollection(
                    [printable, zero_area_residue]
                ),
                "z_offset": 0.0,
                "height": 0.08,
            }
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, printable.area * 0.08)


def test_roundoff_self_intersection_after_scaling_is_recovered() -> None:
    source = Polygon(
        [
            (1395.9968859143326, 326.98215340313453),
            (1395.352412326555, 325.37419180162914),
            (1395.4469531249997, 324.4318164062503),
            (1397.7680468750002, 321.26999999999936),
            (1401.008046875, 313.02000000000004),
            (1399.998046875, 301.01000000000005),
            (1398.018046875, 302.02000000000004),
            (1397.3122381591795, 297.512028503418),
            (1396.4626806640615, 296.65283447265574),
            (1395.008046875, 296.02000000000004),
            (1395.026642064728, 297.0407941276575),
            (1395.7118969726564, 297.80708251953126),
            (1396.05306640625, 298.89119140625),
            (1396.008046875, 303.02000000000004),
            (1396.2063281249998, 319.180625),
            (1395.9121640396118, 321.8818746948243),
            (1395.25736328125, 322.09666015625004),
            (1394.008046875, 322.02000000000004),
        ]
    )
    scale = 0.07324046925016066

    mesh = build_vector_layered_volume(
        [{"geometry": source, "z_offset": 0.0, "height": 0.08}],
        scale_mm_per_svg_unit=scale,
    )

    _assert_closed_volume(mesh, source.area * scale**2 * 0.08)


@pytest.mark.parametrize(
    ("slabs", "scale", "message"),
    [
        ([{"geometry": box(0.0, 0.0, 1.0, 1.0), "height": 0.08}], 0.0, "scale"),
        (["not-a-mapping"], 1.0, "mappings"),
        ([{"geometry": box(0.0, 0.0, 1.0, 1.0), "height": "bad"}], 1.0, "height"),
    ],
)
def test_invalid_inputs_fail_before_mesh_allocation(slabs, scale, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_vector_layered_volume(
            slabs,
            scale_mm_per_svg_unit=scale,
            policy=VectorLayerGeometryPolicy(),
        )


def test_empty_or_zero_height_slabs_return_no_mesh() -> None:
    assert (
        build_vector_layered_volume(
            [
                {"geometry": Polygon(), "height": 0.08},
                {"geometry": box(0.0, 0.0, 1.0, 1.0), "height": 0.0},
            ],
            scale_mm_per_svg_unit=1.0,
        )
        is None
    )
