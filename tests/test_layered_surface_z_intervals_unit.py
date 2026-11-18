"""Physical Z intervals must preserve the expanded volume's geometry and counts."""

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
from trimesh import Trimesh

import core.layered_meshing as layered_meshing
from core.layered_meshing import LayeredMeshPolicy, build_labeled_surface_mesh
from core.mesh_generators import HighFidelityMesher


SOURCE_COUNTS = (
    "source_voxel_count", "component_count", "exposed_unit_face_count",
    "source_contact_edge_pair_count", "source_contact_point_pair_count",
)


def assert_matches_expanded(
    labels: np.ndarray, widths: list[int], material: int,
) -> Trimesh | None:
    expanded = np.repeat(labels, widths, axis=0)
    expected = build_labeled_surface_mesh(expanded, material_id=material, height_px=labels.shape[1])
    actual = build_labeled_surface_mesh(
        labels, material_id=material, height_px=labels.shape[1],
        z_edges=np.r_[0, np.cumsum(widths)], policy=LayeredMeshPolicy(validate_output=True),
    )
    if expected is None:
        assert actual is None
        return None
    assert actual is not None
    assert actual.is_watertight
    np.testing.assert_allclose(actual.bounds, expected.bounds, rtol=0, atol=1e-9)
    assert actual.volume == pytest.approx(expected.volume, abs=1e-9)
    assert len(actual.split(only_watertight=False)) == len(expected.split(only_watertight=False))
    for key in SOURCE_COUNTS:
        assert actual.metadata["layered_mesh_stats"][key] == expected.metadata["layered_mesh_stats"][key]
    return actual


@pytest.mark.parametrize("repeat", [1, 2, 5])
def test_repeated_diagonal_contacts_keep_logical_counts(repeat: int) -> None:
    labels = np.array([[[0, -1], [-1, 0]]], dtype=np.int16)
    assert_matches_expanded(labels, [repeat], 0)


@pytest.mark.parametrize("block_voxels", [2, 8, 16], ids=["columns", "rows", "planes"])
def test_diagonal_contacts_keep_counts_across_block_edges(
    monkeypatch: pytest.MonkeyPatch, block_voxels: int,
) -> None:
    labels = np.full((3, 4, 4), -1, dtype=np.int16)
    labels[0, 0, 0] = labels[0, 1, 1] = 0
    labels[1, 2, 2] = 0
    labels[2, 3, 1] = labels[2, 2, 3] = 0
    monkeypatch.setattr(layered_meshing, "_CONTACT_COUNT_BLOCK_VOXELS", block_voxels)

    mesh = assert_matches_expanded(labels, [3, 1, 5], 0)

    assert mesh is not None
    assert mesh.volume == pytest.approx(17.0)
    stats = mesh.metadata["layered_mesh_stats"]
    assert stats["source_contact_edge_pair_count"] == 4
    assert stats["source_contact_point_pair_count"] == 6


@pytest.mark.parametrize("material", [-3, -2, 0, 1])
def test_air_gaps_holes_and_different_width_component_templates(material: int) -> None:
    labels = np.array([
        [[0, 0, 0], [0, -1, 0], [0, 0, 0]],
        [[-1, -1, -1], [-1, -1, -1], [-1, -1, -1]],
        [[0, 0, 0], [0, -1, 0], [0, 0, 0]],
        [[1, -2, -3], [-1, 1, -1], [-3, -2, 1]],
    ], dtype=np.int16)
    assert_matches_expanded(labels, [2, 3, 7, 1], material)


@settings(max_examples=40, deadline=None)
@given(st.lists(st.integers(-1, 2), min_size=18, max_size=18),
       st.lists(st.integers(1, 5), min_size=3, max_size=3), st.integers(0, 2))
def test_interval_mesh_matches_small_expanded_label_volumes(values, widths, material) -> None:
    assert_matches_expanded(np.asarray(values, dtype=np.int16).reshape(3, 2, 3), widths, material)


@pytest.mark.parametrize("edges", [[0, 0], [0, -1], [1, 2], [0, 1, 2], [0, 1.5], [0, np.nan]])
def test_invalid_z_edges_fail_deterministically(edges) -> None:
    with pytest.raises(ValueError, match="[Zz]"):
        build_labeled_surface_mesh(np.zeros((1, 1, 1)), material_id=0, height_px=1, z_edges=edges)


def test_z_edges_belong_to_one_mesher_call_not_the_instance() -> None:
    mesher = HighFidelityMesher(disable_material_dilation=True)
    labels = np.zeros((1, 1, 1), dtype=np.int16)
    thick = mesher.generate_mesh(labels, 0, 1, z_edges=np.array([0, 125]))
    coating = mesher.generate_mesh(labels, 0, 1)
    assert thick.volume == 125
    assert coating.volume == 1


def test_physical_z_coordinates_receive_the_float32_collision_audit() -> None:
    labels = np.array([[[0]], [[1]]], dtype=np.int16)
    with pytest.raises(ValueError, match="float32.*collision"):
        build_labeled_surface_mesh(labels, material_id=1, height_px=1, z_edges=[0, 2**24, 2**24 + 1])


@pytest.mark.parametrize("dilation", [False, True])
def test_boundary_and_dilation_keep_real_z_intervals(dilation: bool) -> None:
    from shapely.geometry import Polygon
    boundary = Polygon([(0, 0), (4, 0), (0, 4)])
    labels = np.array([[[0, -1, -1, -1]] * 4], dtype=np.int16)
    mesher = HighFidelityMesher(disable_material_dilation=not dilation, boundary_geometry=boundary)
    actual = mesher.generate_mesh(labels, 0, 4, z_edges=np.array([0, 9]))
    expected = mesher.generate_mesh(np.repeat(labels, 9, axis=0), 0, 4)
    assert actual.is_watertight
    assert actual.volume == expected.volume
    np.testing.assert_allclose(actual.bounds, expected.bounds)
