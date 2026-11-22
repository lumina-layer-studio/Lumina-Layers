"""Downstream consumers preserve physical Z and independent optical layers."""

from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from shapely.geometry import box

from config import PrinterConfig
from core.mesh_generators import HighFidelityMesher
from core.model_surface.pipeline import _build_pattern_scene
from core.model_surface.types import ModelSurfaceError
from core.pipeline import s06_voxel_building, s08_auxiliary_meshes


def test_auxiliary_materials_use_volume_intervals_without_stretching_coating() -> None:
    compact = np.array([[[0, -2], [-3, -1]], [[1, -2], [-3, -1]]], dtype=np.int16)
    edges = np.array([0, 1, 126])

    def build(matrix: np.ndarray, z_edges: np.ndarray | None) -> trimesh.Scene:
        return s08_auxiliary_meshes.run({
            "scene": trimesh.Scene(), "valid_slot_names": [], "full_matrix": matrix,
            "voxel_z_edges": z_edges, "mask_solid": np.ones((2, 2), dtype=bool),
            "matched_rgb": np.full((2, 2, 3), [255, 0, 0], dtype=np.uint8),
            "target_h": 2, "pixel_scale": 1.0, "total_layers": 126,
            "preview_colors": {0: [255, 255, 255, 255]}, "transform": np.eye(4),
            "mesher": HighFidelityMesher(disable_material_dilation=True), "separate_backing": True,
            "enable_cloisonne": True, "backing_metadata": {"is_cloisonne": True},
            "free_color_set": {"#ff0000"}, "enable_coating": True,
            "coating_height_mm": 0.16,
            "resolved_coating_material": SimpleNamespace(name="Clear", rgb=(200, 200, 200)),
        })["scene"]

    actual = build(compact, edges)
    expected = build(np.repeat(compact, np.diff(edges), axis=0), None)
    assert set(actual.geometry) == {"Backing", "Wire", "Free_ff0000", "Coating"}
    for name, mesh in actual.geometry.items():
        assert mesh.is_watertight
        assert mesh.volume == pytest.approx(expected.geometry[name].volume)
        np.testing.assert_allclose(mesh.bounds, expected.geometry[name].bounds)
    assert actual.geometry["Free_ff0000"].volume == pytest.approx(126)
    assert actual.geometry["Backing"].volume == pytest.approx(126)
    assert actual.geometry["Coating"].volume == pytest.approx(4 * 0.16)
    assert actual.geometry["Coating"].metadata["bambu_material_name"] == "Clear"


@pytest.mark.parametrize("with_boundary", [False, True])
def test_face_up_coating_follows_the_padded_five_color_surface(with_boundary: bool) -> None:
    layer_height = PrinterConfig.LAYER_HEIGHT
    # The two regions use the same backing, but the first omits the outermost
    # optical layer. Both must carry exactly one layer of clear filament.
    material_matrix = np.tile([[[0, 1], [0, 1], [-1, 1], [-1, 1]]], (3, 1, 1))
    mask = np.ones(material_matrix.shape[:2], dtype=bool)
    context = s06_voxel_building.run({
        "material_matrix": material_matrix,
        "mask_solid": mask,
        "matched_rgb": np.zeros((*mask.shape, 3), dtype=np.uint8),
        "spacer_thick": 1.6,
        "structure_mode": "Single-sided",
        "color_mode": "5-Color Extended",
        "pixel_scale": 1.0,
    })
    context.update(
        scene=trimesh.Scene(),
        valid_slot_names=[],
        target_h=mask.shape[0],
        preview_colors={0: [255, 255, 255, 255]},
        transform=np.eye(4),
        mesher=HighFidelityMesher(disable_material_dilation=True),
        enable_coating=True,
        coating_height_mm=layer_height,
        resolved_coating_material=SimpleNamespace(name="Clear", rgb=(200, 200, 200)),
        boundary_geometry=box(0.2, 0.2, 3.0, 2.8) if with_boundary else None,
    )

    coating = s08_auxiliary_meshes.run(context)["scene"].geometry["Coating"]
    assert coating.bounds[:, 2] == pytest.approx([1.68, 1.84])
    lower, higher = sorted(coating.split(), key=lambda mesh: mesh.bounds[0, 2])
    np.testing.assert_allclose(lower.bounds, [[2, 0, 1.68], [3 if with_boundary else 4, 3, 1.76]])
    np.testing.assert_allclose(higher.bounds, [[0, 0, 1.76], [2, 3, 1.84]])
    assert coating.volume == pytest.approx((9 if with_boundary else 12) * layer_height)


@pytest.mark.parametrize(("surface", "expected"), [
    ("relief", [[0.8, 0.88], [1.6, 1.68]]),
    ("cloisonne", [[1.6, 1.68], [1.76, 1.84]]),
])
def test_face_up_coating_covers_the_raised_surface(surface: str, expected: list[list[float]]) -> None:
    mask = np.ones((3, 4), dtype=bool)
    raised = np.zeros_like(mask)
    raised[:, :2] = True
    rgb = np.full((*mask.shape, 3), 255, dtype=np.uint8)
    rgb[raised] = [0, 0, 255]
    context = s06_voxel_building.run({
        "material_matrix": np.ones((*mask.shape, 5), dtype=np.int16),
        "mask_solid": mask,
        "matched_rgb": rgb,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "pixel_scale": 1.0,
        "enable_relief": surface == "relief",
        "color_height_map": {"#0000ff": 1.6, "#ffffff": 0.8},
        "enable_cloisonne": surface == "cloisonne",
        "wire_height_mm": 0.16,
        "processor": SimpleNamespace(_extract_wireframe_mask=lambda *_: raised),
    })
    context.update(
        scene=trimesh.Scene(),
        valid_slot_names=[],
        target_h=mask.shape[0],
        preview_colors={0: [255, 255, 255, 255]},
        transform=np.eye(4),
        mesher=HighFidelityMesher(disable_material_dilation=True),
        enable_coating=True,
        coating_height_mm=0.08,
        resolved_coating_material=SimpleNamespace(name="Clear", rgb=(200, 200, 200)),
    )

    coating = s08_auxiliary_meshes.run(context)["scene"].geometry["Coating"]
    assert coating.bounds[:, 2] == pytest.approx([expected[0][0], expected[1][1]])
    sections = sorted(coating.split(), key=lambda mesh: mesh.bounds[0, 2])
    np.testing.assert_allclose([mesh.bounds[:, 2] for mesh in sections], expected)


@pytest.mark.parametrize("color_mode", ["4-Color", "5-Color Extended"])
def test_surface_pattern_resets_backing_intervals_to_optical_stack(color_mode: str) -> None:
    material = np.array([[[0, 1], [1, 0]]], dtype=np.int16)
    ctx = s06_voxel_building.run({
        "material_matrix": material, "mask_solid": np.ones((1, 2), dtype=bool),
        "matched_rgb": np.zeros((1, 2, 3), dtype=np.uint8), "spacer_thick": 10,
        "structure_mode": "Single-sided", "color_mode": color_mode,
        "backing_color_id": 1, "pixel_scale": 1.0,
    })
    ctx.update(target_h=1, slot_names=["White", "Red"], preview_colors={
        0: [255, 255, 255, 255], 1: [255, 0, 0, 255],
    }, layer_height_mm=0.08)
    actual = _build_pattern_scene(ctx)
    dense_ctx = dict(ctx, full_matrix=np.repeat(ctx["full_matrix"], np.diff(ctx["voxel_z_edges"]), axis=0))
    dense_ctx.pop("voxel_z_edges")
    expected = _build_pattern_scene(dense_ctx)
    for name, mesh in actual.geometry.items():
        assert mesh.volume == pytest.approx(expected.geometry[name].volume)
        np.testing.assert_allclose(mesh.bounds, expected.geometry[name].bounds)
        assert mesh.bounds[1, 2] == pytest.approx(0.16)


@pytest.mark.parametrize("orientation,edges,error", [
    ("double", [0, 1, 126, 127], "single display face"),
    ("down", [0, 125, 126, 127], "individual Z intervals"),
    ("up", [0, 1, 2, 127], "individual Z intervals"),
])
def test_surface_pattern_rejects_invalid_display_intervals(orientation, edges, error) -> None:
    with pytest.raises(ModelSurfaceError, match=error):
        _build_pattern_scene({
            "full_matrix": np.zeros((3, 1, 1), dtype=np.int16),
            "voxel_z_edges": edges, "color_layers": 1,
            "bambu_face_orientation": orientation, "slot_names": ["White"],
            "preview_colors": {0: [255, 255, 255, 255]},
            "target_h": 1, "pixel_scale": 1.0,
        })
