"""Unit tests for puzzle hybrid-boundary pipeline integration."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from config import ModelingMode, PrinterConfig
from core.export_materials import resolve_coating_material
from core.mesh_generators import HighFidelityMesher
from core.pipeline import s07_mesh_generation, s08_auxiliary_meshes


def _write_boundary_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_s08_outline_case(
    *,
    mask_solid: np.ndarray,
    mesher: HighFidelityMesher,
    pixel_scale: float,
    total_layers: int,
    coating_height_mm: float,
    outline_width: float,
    boundary_geometry: Polygon | None,
    structure_mode: str = "Single-sided",
) -> dict:
    target_h, target_w = mask_solid.shape
    return s08_auxiliary_meshes.run(
        {
            "scene": trimesh.Scene(),
            "valid_slot_names": [],
            "full_matrix": np.zeros((1, target_h, target_w), dtype=int),
            "mask_solid": mask_solid,
            "matched_rgb": np.zeros((target_h, target_w, 3), dtype=np.uint8),
            "target_h": target_h,
            "target_w": target_w,
            "pixel_scale": pixel_scale,
            "total_layers": total_layers,
            "preview_colors": {0: [255, 255, 255, 255]},
            "transform": np.eye(4),
            "mesher": mesher,
            "separate_backing": False,
            "enable_cloisonne": False,
            "backing_metadata": {},
            "enable_coating": True,
            "resolved_coating_material": resolve_coating_material(None, slot_names=[], preview_colors={}, material_types={}),
            "coating_height_mm": coating_height_mm,
            "enable_outline": True,
            "outline_width": outline_width,
            "structure_mode": structure_mode,
            "free_color_set": None,
            "add_loop": False,
            "loop_info": None,
            "boundary_geometry": boundary_geometry,
        }
    )


def test_s07_mesh_generation_loads_boundary_geometry_and_disables_dilation() -> None:
    """S07 should load puzzle boundary geometry and configure the mesher accordingly."""

    with NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        boundary_path = Path(handle.name)
        boundary_path = _write_boundary_json(
            boundary_path,
            {
                "bbox_px": [0, 0, 5, 5],
                "polygon_px": [[0.0, 0.0], [3.0, 0.0], [0.0, 5.0]],
                "holes_px": [],
            },
        )
        full_matrix = np.zeros((1, 5, 5), dtype=int)

        ctx = s07_mesh_generation.run(
            {
                "full_matrix": full_matrix,
                "slot_names": ["White"],
                "preview_colors": {0: [255, 255, 255, 255]},
                "modeling_mode": ModelingMode.HIGH_FIDELITY,
                "target_h": 5,
                "pixel_scale": 1.0,
                "disable_material_dilation": True,
                "piece_boundary_geometry_path": str(boundary_path),
                "_bench_enabled": False,
            }
        )

    mesher = ctx["mesher"]
    assert isinstance(mesher, HighFidelityMesher)
    assert mesher.disable_material_dilation is True
    assert mesher.boundary_geometry is not None
    assert mesher.boundary_geometry.equals(Polygon([(0.0, 0.0), (3.0, 0.0), (0.0, 5.0)]))
    exported_mesh = ctx["scene"].geometry["White"]
    assert exported_mesh.bounds[1, 0] == pytest.approx(3.0)


def test_s08_aux_meshes_use_boundary_geometry_for_coating_and_outline() -> None:
    """S08 coating should cover the complete boundary-aware outline footprint."""

    boundary_geometry = Polygon([(2.0, 2.0), (7.0, 2.0), (7.0, 7.0), (2.0, 7.0)])
    mesher = HighFidelityMesher(disable_material_dilation=True, boundary_geometry=boundary_geometry)

    ctx = s08_auxiliary_meshes.run(
        {
            "scene": trimesh.Scene(),
            "valid_slot_names": [],
            "full_matrix": np.zeros((3, 10, 10), dtype=int),
            "mask_solid": np.ones((10, 10), dtype=bool),
            "matched_rgb": np.zeros((10, 10, 3), dtype=np.uint8),
            "target_h": 10,
            "target_w": 10,
            "pixel_scale": 1.0,
            "total_layers": 3,
            "preview_colors": {0: [255, 255, 255, 255]},
            "transform": np.eye(4),
            "mesher": mesher,
            "separate_backing": False,
            "enable_cloisonne": False,
            "backing_metadata": {},
            "enable_coating": True,
            "resolved_coating_material": resolve_coating_material(None, slot_names=[], preview_colors={}, material_types={}),
            "coating_height_mm": PrinterConfig.LAYER_HEIGHT,
            "enable_outline": True,
            "outline_width": 1.0,
            "structure_mode": "Double-sided",
            "free_color_set": None,
            "add_loop": False,
            "loop_info": None,
            "boundary_geometry": boundary_geometry,
        }
    )

    coating = ctx["scene"].geometry["Coating"]
    outline = ctx["scene"].geometry["Outline"]

    assert coating.bounds[:, :2] == pytest.approx(outline.bounds[:, :2])
    assert len(coating.split(only_watertight=False)) == 2
    assert coating.bounds[0, 2] == pytest.approx(-PrinterConfig.LAYER_HEIGHT)
    assert coating.bounds[1, 2] == pytest.approx(4 * PrinterConfig.LAYER_HEIGHT)

    assert outline.bounds[0, 0] == pytest.approx(1.0)
    assert outline.bounds[1, 0] == pytest.approx(8.0)
    assert outline.bounds[0, 1] == pytest.approx(2.0)
    assert outline.bounds[1, 1] == pytest.approx(9.0)


def _mesh_xy_footprint(mesh: trimesh.Trimesh) -> BaseGeometry:
    """Project horizontal mesh faces into one planar coverage geometry."""

    projected_faces = []
    for triangle in mesh.vertices[mesh.faces][:, :, :2]:
        projected = Polygon(triangle)
        if projected.is_valid and projected.area > 1e-9:
            projected_faces.append(projected)
    return unary_union(projected_faces)


def test_s08_boundary_coating_covers_concave_outline_with_hole() -> None:
    """Double-sided boundary coating should cover concave and hole outline rings."""

    boundary_geometry = Polygon(
        [(0.0, 0.0), (8.0, 0.0), (8.0, 3.0), (4.0, 3.0), (4.0, 8.0), (0.0, 8.0)],
        holes=[[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]],
    )
    result = _run_s08_outline_case(
        mask_solid=np.ones((10, 10), dtype=bool),
        mesher=HighFidelityMesher(
            disable_material_dilation=True,
            boundary_geometry=boundary_geometry,
        ),
        pixel_scale=1.0,
        total_layers=4,
        coating_height_mm=PrinterConfig.LAYER_HEIGHT,
        outline_width=1.0,
        boundary_geometry=boundary_geometry,
        structure_mode="Double-sided",
    )

    coating = result["scene"].geometry["Coating"]
    outline = result["scene"].geometry["Outline"]
    coating_footprint = _mesh_xy_footprint(coating)
    outline_footprint = _mesh_xy_footprint(outline)

    assert len(coating.split(only_watertight=False)) == 2
    assert coating.bounds[0, 2] == pytest.approx(-PrinterConfig.LAYER_HEIGHT)
    assert coating.bounds[1, 2] == pytest.approx(5 * PrinterConfig.LAYER_HEIGHT)
    assert outline_footprint.difference(coating_footprint).area == pytest.approx(
        0.0,
        abs=1e-9,
    )


def test_s08_boundary_outline_matches_legacy_padding_and_transform() -> None:
    """Boundary-aware outlines should keep legacy scaling, Z, and edge padding semantics."""

    mask_solid = np.zeros((10, 10), dtype=bool)
    mask_solid[2:7, 0:3] = True
    boundary_geometry = Polygon([(0.0, 2.0), (3.0, 2.0), (3.0, 7.0), (0.0, 7.0)])
    pixel_scale = 0.5
    total_layers = 2
    coating_height_mm = PrinterConfig.LAYER_HEIGHT * 2
    outline_width = 1.0

    boundary_ctx = _run_s08_outline_case(
        mask_solid=mask_solid,
        mesher=HighFidelityMesher(disable_material_dilation=True, boundary_geometry=boundary_geometry),
        pixel_scale=pixel_scale,
        total_layers=total_layers,
        coating_height_mm=coating_height_mm,
        outline_width=outline_width,
        boundary_geometry=boundary_geometry,
    )
    legacy_ctx = _run_s08_outline_case(
        mask_solid=mask_solid,
        mesher=HighFidelityMesher(disable_material_dilation=True),
        pixel_scale=pixel_scale,
        total_layers=total_layers,
        coating_height_mm=coating_height_mm,
        outline_width=outline_width,
        boundary_geometry=None,
    )

    boundary_outline = boundary_ctx["scene"].geometry["Outline"]
    legacy_outline = legacy_ctx["scene"].geometry["Outline"]

    assert legacy_outline.bounds[0, 0] < 0.0
    assert boundary_outline.bounds == pytest.approx(legacy_outline.bounds)
    assert boundary_outline.bounds[0, 2] == pytest.approx(0.0)
    assert boundary_outline.bounds[1, 2] == pytest.approx(total_layers * PrinterConfig.LAYER_HEIGHT)
    for ctx in (boundary_ctx, legacy_ctx):
        assert ctx["scene"].geometry["Coating"].bounds[1, 2] == pytest.approx(0.0)
        coat = ctx["scene"].geometry["Coating"]
        outline = ctx["scene"].geometry["Outline"]
        assert np.all(coat.bounds[0, :2] <= outline.bounds[0, :2] + 1e-6)
        assert np.all(coat.bounds[1, :2] >= outline.bounds[1, :2] - 1e-6)
