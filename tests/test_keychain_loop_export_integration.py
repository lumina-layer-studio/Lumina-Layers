"""Measure the keychain joint in the actual packaged 3MF geometry."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np
from PIL import Image
import pytest
from shapely.affinity import rotate, scale, translate
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

import config
from api.workers.converter_workers import worker_generate_model
from core.pipeline import s09_export_3mf, s11_glb_preview

ANGLES = (-90, -45, 0, 37, 45, 90, 180)
PRESETS = ("top-center", "top-left", "top-right", "left-center", "right-center", "bottom-center")
CONTRACT = json.loads((Path(__file__).parent / "fixtures/keychain_rotation_reference.json").read_text())


def _transform_points(points: np.ndarray, element: ET.Element) -> np.ndarray:
    transform = element.get("transform")
    if transform is None:
        return points
    matrix = np.fromstring(transform, sep=" ").reshape(4, 3)
    return points @ matrix[:3] + matrix[3]


def _read_print_footprints(path: Path) -> tuple[BaseGeometry, BaseGeometry, tuple[float, float], tuple[float, float]]:
    """Read triangle projections and their Z spans in printer coordinates."""
    groups = {"body": [], "loop": []}
    heights = {"body": [], "loop": []}
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
        names = {
            part.attrib["id"]: part.find("metadata[@key='name']").attrib["value"]
            for part in settings.findall(".//part")
        }
        model = ET.fromstring(archive.read("3D/3dmodel.model"))
        for item in model.findall("{*}build/{*}item"):
            assembly = model.find(f"{{*}}resources/{{*}}object[@id='{item.attrib['objectid']}']")
            for component in assembly.findall("{*}components/{*}component"):
                mesh_id = component.attrib["objectid"]
                mesh_path = next(value for key, value in component.attrib.items() if key.endswith("}path"))
                source = ET.fromstring(archive.read(mesh_path.lstrip("/")))
                mesh = source.find(f"{{*}}resources/{{*}}object[@id='{mesh_id}']/{{*}}mesh")
                points = np.array([
                    [float(vertex.attrib[axis]) for axis in "xyz"]
                    for vertex in mesh.findall("{*}vertices/{*}vertex")
                ])
                points = _transform_points(_transform_points(points, component), item)
                group = "loop" if names[mesh_id] == "Keychain_Loop" else "body"
                heights[group].extend(points[:, 2])
                for face in mesh.findall("{*}triangles/{*}triangle"):
                    triangle = Polygon(points[[int(face.attrib[key]) for key in ("v1", "v2", "v3")], :2])
                    if triangle.area > 1e-9:
                        groups[group].append(triangle)
    assert all(groups.values())
    body_z = min(heights["body"]), max(heights["body"])
    loop_z = min(heights["loop"]), max(heights["loop"])
    return unary_union(groups["body"]), unary_union(groups["loop"]), body_z, loop_z


@pytest.fixture
def ring_export_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[config.ModelingMode, Path], Path]:
    monkeypatch.setattr(config, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(s11_glb_preview, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("LUMINA_VECTOR_SKIP_2D_PREVIEW", "1")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    svg = tmp_path / "offset.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="52" viewBox="0 0 80 52">'
        '<path fill="#dc143c" d="M9 5 H28 V39 H9Z"/>'
        '<path fill="#0064f0" d="M28 5 H44 V14 H58 V39 H28Z"/></svg>',
        encoding="utf-8",
    )
    png = tmp_path / "offset.png"
    rgba = np.zeros((52, 80, 4), dtype=np.uint8)
    rgba[5:39, 9:28] = (220, 20, 60, 255)
    rgba[5:39, 28:44] = (0, 100, 240, 255)
    rgba[14:39, 44:58] = (0, 100, 240, 255)
    Image.fromarray(rgba).save(png)
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
    return {
        config.ModelingMode.VECTOR: svg,
        config.ModelingMode.PIXEL: png,
        config.ModelingMode.HIGH_FIDELITY: png,
    }, lut


@pytest.mark.parametrize("mode", [config.ModelingMode.VECTOR, config.ModelingMode.PIXEL, config.ModelingMode.HIGH_FIDELITY])
@pytest.mark.parametrize("structure", ["Single-sided", "Double-sided"])
@pytest.mark.parametrize("preset", PRESETS)
def test_exported_ring_rotates_about_its_attached_foot(ring_export_source, mode, structure, preset) -> None:
    sources, lut = ring_export_source
    params = {
        "modeling_mode": mode,
        "target_width_mm": 40,
        "spacer_thick": 1.2,
        "structure_mode": structure,
        "color_mode": "4-Color (RYBW)",
        "add_loop": True,
        "loop_position_preset": preset,
        "loop_pos": None,
        "loop_width": CONTRACT["widthMm"],
        "loop_length": CONTRACT["lengthMm"],
        "loop_hole": CONTRACT["holeMm"],
        "printer_id": "bambu-a1",
        "enable_wipe_tower_auto_placement": False,
    }
    artwork_rings = {}
    for angle in ANGLES:
        result = worker_generate_model(str(sources[mode]), str(lut), {**params, "loop_angle": angle})
        assert result["threemf_path"], result["status_msg"]
        body, loop, body_z, loop_z = _read_print_footprints(Path(result["threemf_path"]))
        # The printed ring is a solid extrusion. Its Z interval covers the
        # body, so overlapping area represents an actual volume joint.
        assert loop_z[0] <= body_z[0] + 1e-6 and loop_z[1] >= body_z[1] - 1e-6, angle
        assert body.intersection(loop).area > 0.5, f"{angle}°: separation {body.distance(loop):.6f} mm"
        min_x, min_y, max_x, max_y = body.bounds
        centered = translate(loop, -(min_x + max_x) / 2, -(min_y + max_y) / 2)
        artwork_rings[angle] = scale(centered, xfact=-1, origin=(0, 0)) if structure == "Single-sided" else centered

    unrotated = artwork_rings[0]
    min_x, min_y, max_x, _ = unrotated.bounds
    foot = ((min_x + max_x) / 2, min_y)
    if mode == config.ModelingMode.VECTOR and preset == "top-center":
        # The unrotated 3MF and the rendered preview share this artwork-space reference.
        assert foot == pytest.approx(CONTRACT["footMm"], abs=5e-4)
    for angle, ring in artwork_rings.items():
        expected = rotate(unrotated, angle, origin=foot)
        # Compare the entire outer silhouette and hole of the serialized mesh.
        assert ring.hausdorff_distance(expected) < 1e-4, angle
        assert ring.symmetric_difference(expected).area < 1e-3, angle
