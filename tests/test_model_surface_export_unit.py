from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import shapely.geometry as sg
import trimesh

from core.model_surface.assembly import PreparedSurfacePattern
from core.model_surface.pipeline import build_surface_overlay_scene
from core.model_surface.types import ModelSurfaceError, PlaneFrame, SurfaceFootprint
from core.model_surface.validation import prepare_surface_base_for_export
from utils.bambu_3mf_writer import _materialize_n3mf_mesh_view_arrays


@pytest.mark.parametrize("orientation", ["up", "down"])
def test_surface_base_remains_closed_when_boolean_edges_collapse_in_writer(
    monkeypatch: pytest.MonkeyPatch, orientation: str,
) -> None:
    # A microscopic bevel remains valid in the Boolean's float64 domain, but
    # its two endpoints coincide at bed-scale float32 coordinates.
    outline = sg.Polygon([
        (190, 95), (210, 95), (210, 105 - 1e-6),
        (210 - 1e-6, 105), (190, 105),
    ])
    base = trimesh.creation.extrude_polygon(outline, 3, engine="earcut")
    base.metadata["bambu_material_name"] = "White"
    artwork = trimesh.creation.box(extents=(2, 2, 0.4))
    artwork.apply_translation((1, 1, 0.2))
    pattern = PreparedSurfacePattern(trimesh.Scene({"Red": artwork}), sg.box(0, 0, 2, 2))
    footprint = SurfaceFootprint(
        frame=PlaneFrame((200, 100, 3), (0, 0, 1), (1, 0, 0), (0, 1, 0)),
        outer=((-1, -1), (1, -1), (1, 1), (-1, 1)),
        holes=(), bounds_min=(-1, -1), bounds_max=(1, 1),
        bounds_width_mm=2, bounds_height_mm=2, area_mm2=4, hole_count=0,
    )
    monkeypatch.setattr(
        "core.model_surface.pipeline.load_model_surface_mesh",
        lambda _: SimpleNamespace(mesh=base),
    )
    monkeypatch.setattr(
        "core.model_surface.pipeline.build_image_model_context",
        lambda **_: {"bambu_face_orientation": orientation},
    )
    monkeypatch.setattr(
        "core.model_surface.pipeline._build_pattern_scene", lambda *_, **__: pattern,
    )

    result = build_surface_overlay_scene(
        model_path="base.stl", artwork_image_path="art.svg", lut_path="palette.npy",
        converter_params={}, footprint=footprint, pocket_depth_mm=0.4,
    )
    source = result.scene.geometry["surface_base"]
    vertices, faces = _materialize_n3mf_mesh_view_arrays(source)
    written = trimesh.Trimesh(vertices.astype(np.float64), faces, process=False)

    assert np.all(written.area_faces > 0)
    assert written.is_watertight
    assert written.is_winding_consistent
    assert written.volume == pytest.approx(base.volume - 4 * 0.42, abs=1e-4)
    np.testing.assert_allclose(written.bounds, base.bounds, atol=1e-5)
    assert source.metadata["bambu_material_name"] == "White"
    assert result.slot_names == ["surface_base", "Red"]
    # The cavity floor survives; the artwork remains a separate material.
    assert np.any(np.isclose(written.vertices[:, 2], 2.58 if orientation == "up" else 0.42))
    assert result.scene.geometry["Red"].volume == pytest.approx(1.6)


def test_export_contraction_preserves_reversed_inner_shell() -> None:
    outline = sg.Polygon([
        (190, 95), (210, 95), (210, 105 - 1e-6),
        (210 - 1e-6, 105), (190, 105),
    ])
    outer = trimesh.creation.extrude_polygon(outline, 3, engine="earcut")
    cavity = trimesh.creation.box(extents=(18, 8, 2))
    cavity.apply_translation((200, 100, 1.5))
    cavity.invert()
    source = trimesh.util.concatenate((outer, cavity))
    original_vertices = source.vertices.copy()

    result = prepare_surface_base_for_export(source)

    assert result.is_volume
    assert np.all(result.area_faces > 0)
    assert result.volume == pytest.approx(600 - 288, abs=1e-4)
    assert sorted(part.volume for part in result.split()) == pytest.approx([-288, 600])
    np.testing.assert_array_equal(source.vertices, original_vertices)
    np.testing.assert_array_equal(
        result.vertices, result.vertices.astype(np.float32).astype(np.float64),
    )


def test_export_rejects_a_solid_that_cannot_fit_the_writer_domain() -> None:
    source = trimesh.creation.box(extents=(1e-6, 10, 3))
    source.apply_translation((200, 100, 1.5))
    assert source.is_volume

    with pytest.raises(ModelSurfaceError, match="model_surface_boolean_failed"):
        prepare_surface_base_for_export(source)


def test_export_retriangulates_a_collinear_face_retained_by_manifold() -> None:
    # A closed local fragment of the failing phone-case Boolean. The original
    # artwork/model is not needed: one collinear face survives Mesh64 cleanup.
    data = json.loads((
        Path(__file__).parent / "fixtures/surface_collinear_export.json"
    ).read_text())
    source = trimesh.Trimesh(data["vertices"], data["faces"], process=False)
    source.metadata["bambu_material_name"] = "White"
    original_vertices = source.vertices.copy()
    original_faces = source.faces.copy()
    assert source.is_volume

    result = prepare_surface_base_for_export(source)
    vertices, faces = _materialize_n3mf_mesh_view_arrays(result)
    written = trimesh.Trimesh(vertices.astype(np.float64), faces, process=False)

    assert written.is_volume
    assert written.is_winding_consistent
    assert np.all(written.area_faces > 0)
    assert written.volume == pytest.approx(source.volume, abs=1e-4)
    np.testing.assert_allclose(written.bounds, source.bounds, atol=1e-5)
    assert result.metadata["bambu_material_name"] == "White"
    np.testing.assert_array_equal(source.vertices, original_vertices)
    np.testing.assert_array_equal(source.faces, original_faces)
