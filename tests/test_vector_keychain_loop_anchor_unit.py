"""Regression tests for vector keychain loop placement."""

import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import numpy as np
import pytest

import config
from api.workers.converter_workers import worker_generate_model


def _read_exported_loop_xy(path: Path) -> np.ndarray:
    namespace = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    with ZipFile(path) as archive:
        settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
        loop = settings.find(".//part/metadata[@key='name'][@value='Keychain_Loop']/..")
        assert loop is not None
        mesh_file = next(
            name for name in archive.namelist() if name.startswith("3D/Objects/") and name.endswith(".model")
        )
        model = ET.fromstring(archive.read(mesh_file))
        vertices = model.findall(f".//m:object[@id='{loop.attrib['id']}']//m:vertex", namespace)
    return np.unique([[float(vertex.attrib[axis]) for axis in "xy"] for vertex in vertices], axis=0)


def test_face_down_vector_ring_is_mirrored_with_artwork(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("LUMINA_VECTOR_SKIP_2D_PREVIEW", "1")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    svg = tmp_path / "shape.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 24">'
        '<path fill="#dc143c" d="M 0 0 H 12 V 24 H 0 Z"/>'
        '<path fill="#0064f0" d="M 12 0 H 34 V 7 H 40 V 24 H 12 Z"/>'
        '</svg>',
        encoding="utf-8",
    )
    lut = tmp_path / "palette.json"
    lut.write_text(json.dumps({
        "palette": ["White", "Red", "Yellow", "Blue"],
        "color_mode": "4-Color (RYBW)",
        "layer_order": "Top2Bottom",
        "max_color_layers": 5,
        "layer_height_mm": 0.08,
        "entries": [
            {"rgb": [220, 20, 60], "recipe": ["Red"] * 5},
            {"rgb": [0, 100, 240], "recipe": ["Blue"] * 5},
        ],
    }), encoding="utf-8")
    params = {
        "modeling_mode": config.ModelingMode.VECTOR,
        "target_width_mm": 40,
        "spacer_thick": 1.2,
        "color_mode": "4-Color (RYBW)",
        "add_loop": True,
        "loop_position_preset": "top-left",
        "loop_offset_x": 7.0,
        "loop_offset_y": -1.5,
        "loop_angle": 30.0,
        "loop_width": 6.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_pos": None,
        "printer_id": "bambu-a1",
        "enable_wipe_tower_auto_placement": False,
    }
    rings = {}
    for structure in ("Double-sided", "Single-sided"):
        result = worker_generate_model(str(svg), str(lut), {**params, "structure_mode": structure})
        assert result["threemf_path"], result["status_msg"]
        rings[structure] = _read_exported_loop_xy(Path(result["threemf_path"]))

    # Reflect the complete profile, which checks the anchor, signed offset
    # and rotation together. Ignore Z because the two bodies differ in height.
    expected = np.unique(rings["Double-sided"] * [-1, 1], axis=0)
    np.testing.assert_allclose(rings["Single-sided"], expected, atol=5e-6)


def _read_named_exported_parts(path: Path) -> dict[str, list[tuple[np.ndarray, np.ndarray]]]:
    namespace = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    parts: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
        names = {
            part.attrib["id"]: part.find("metadata[@key='name']").attrib["value"]
            for part in settings.findall(".//part")
        }
        model = ET.fromstring(archive.read("3D/3dmodel.model"))
        for item in model.findall("{*}build/{*}item"):
            item_matrix = (
                np.fromstring(item.attrib["transform"], sep=" ").reshape(4, 3)
                if "transform" in item.attrib
                else None
            )
            assembly = model.find(f"{{*}}resources/{{*}}object[@id='{item.attrib['objectid']}']")
            assert assembly is not None
            for component in assembly.findall("{*}components/{*}component"):
                mesh_id = component.attrib["objectid"]
                mesh_path = next(
                    value for key, value in component.attrib.items() if key.endswith("}path")
                )
                source = ET.fromstring(archive.read(mesh_path.lstrip("/")))
                mesh = source.find(f".//m:object[@id='{mesh_id}']//m:mesh", namespace)
                assert mesh is not None
                points = np.array([
                    [float(vertex.attrib[axis]) for axis in "xyz"]
                    for vertex in mesh.findall("m:vertices/m:vertex", namespace)
                ])
                if "transform" in component.attrib:
                    comp_matrix = np.fromstring(component.attrib["transform"], sep=" ").reshape(4, 3)
                    points = points @ comp_matrix[:3] + comp_matrix[3]
                if item_matrix is not None:
                    points = points @ item_matrix[:3] + item_matrix[3]
                faces = np.array([
                    [int(face.attrib[key]) for key in ("v1", "v2", "v3")]
                    for face in mesh.findall("m:triangles/m:triangle", namespace)
                ])
                parts.setdefault(names[mesh_id], []).append((points, faces))
    return parts


def test_vector_keychain_loop_with_outline_exports_both_parts_and_open_bore(
    tmp_path, monkeypatch,
) -> None:
    """Enabling both keychain loop and vector outline must share one structure plan."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    monkeypatch.setattr(config, "MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("LUMINA_VECTOR_SKIP_2D_PREVIEW", "1")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    svg = tmp_path / "badge.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 22">'
        '<rect x="2" y="2" width="46" height="18" rx="3" fill="#dc143c"/>'
        '<circle cx="16" cy="11" r="5" fill="#f0c800"/>'
        '<path fill="#0064f0" d="M28 5 H44 V17 H28 Z"/>'
        "</svg>",
        encoding="utf-8",
    )
    lut = tmp_path / "palette.json"
    lut.write_text(
        json.dumps(
            {
                "palette": ["White", "Red", "Yellow", "Blue"],
                "color_mode": "4-Color (RYBW)",
                "layer_order": "Top2Bottom",
                "max_color_layers": 5,
                "layer_height_mm": 0.08,
                "entries": [
                    {"rgb": [255, 255, 255], "recipe": ["White"] * 5},
                    {"rgb": [220, 20, 60], "recipe": ["Red"] * 5},
                    {"rgb": [240, 200, 0], "recipe": ["Yellow"] * 5},
                    {"rgb": [0, 100, 240], "recipe": ["Blue"] * 5},
                ],
            }
        ),
        encoding="utf-8",
    )
    base_params = {
        "modeling_mode": config.ModelingMode.VECTOR,
        "target_width_mm": 50.0,
        "spacer_thick": 1.2,
        "color_mode": "4-Color (RYBW)",
        "add_loop": True,
        "loop_position_preset": "top-center",
        "loop_width": 4.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_angle": 0.0,
        "loop_pos": None,
        "enable_outline": True,
        "outline_width": 2.0,
        "printer_id": "bambu-a1",
        "enable_wipe_tower_auto_placement": False,
    }

    for extra in (
        {"structure_mode": "Single-sided"},
        {"structure_mode": "Double-sided"},
        {"structure_mode": "Single-sided", "enable_relief": True, "height_mode": "color"},
    ):
        result = worker_generate_model(str(svg), str(lut), {**base_params, **extra})
        assert result["threemf_path"], result["status_msg"]
        parts = _read_named_exported_parts(Path(result["threemf_path"]))
        assert "Outline" in parts
        assert "Keychain_Loop" in parts

        loop_pts, loop_faces = parts["Keychain_Loop"][0]
        loop_footprint = unary_union([
            poly
            for tri in loop_pts[loop_faces][:, :, :2]
            if (poly := Polygon(tri)).area > 1e-9
        ]).buffer(0)
        assert isinstance(loop_footprint, Polygon) and len(loop_footprint.interiors) == 1
        bore = Polygon(loop_footprint.interiors[0])

        non_loop_footprint = unary_union([
            poly
            for name, entries in parts.items()
            if name != "Keychain_Loop"
            for pts, faces in entries
            for tri in pts[faces][:, :, :2]
            if (poly := Polygon(tri)).area > 1e-9
        ]).buffer(0)
        assert loop_footprint.intersection(non_loop_footprint).area > 0.1
        assert bore.difference(non_loop_footprint).area == pytest.approx(bore.area, abs=1e-9)


def test_vector_keychain_loop_blocked_by_wide_outline_raises_validation_error(
    tmp_path, monkeypatch,
) -> None:
    """An outline wide enough to cover the keychain bore must raise KeychainPlacementError."""
    import pytest
    from core.errors import KeychainPlacementError

    monkeypatch.setattr(config, "MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("LUMINA_VECTOR_SKIP_2D_PREVIEW", "1")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    svg = tmp_path / "box.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
        '<rect x="0" y="0" width="40" height="20" fill="#dc143c"/>'
        "</svg>",
        encoding="utf-8",
    )
    lut = tmp_path / "palette.json"
    lut.write_text(
        json.dumps(
            {
                "palette": ["White", "Red", "Yellow", "Blue"],
                "color_mode": "4-Color (RYBW)",
                "layer_order": "Top2Bottom",
                "max_color_layers": 5,
                "layer_height_mm": 0.08,
                "entries": [{"rgb": [220, 20, 60], "recipe": ["Red"] * 5}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(KeychainPlacementError, match="完全堵住"):
        worker_generate_model(
            str(svg),
            str(lut),
            {
                "modeling_mode": config.ModelingMode.VECTOR,
                "target_width_mm": 40.0,
                "spacer_thick": 1.2,
                "structure_mode": "Single-sided",
                "color_mode": "4-Color (RYBW)",
                "add_loop": True,
                "loop_position_preset": "top-center",
                "loop_width": 4.0,
                "loop_length": 6.0,
                "loop_hole": 2.0,
                "loop_angle": 0.0,
                "loop_pos": None,
                "enable_outline": True,
                "outline_width": 8.0,
                "printer_id": "bambu-a1",
                "enable_wipe_tower_auto_placement": False,
            },
        )
