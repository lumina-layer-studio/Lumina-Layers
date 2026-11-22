"""Regression tests for vector keychain loop placement."""

import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import numpy as np
import pytest
import trimesh

import config
from api.workers.converter_workers import worker_generate_model
from core.pipeline.vector_branch import _vector_loop_attach_point


def _irregular_scene() -> trimesh.Scene:
    scene = trimesh.Scene()
    body = trimesh.creation.box(extents=(24.0, 58.0, 1.0))
    body.apply_translation((30.0, 29.0, 0.5))
    spike = trimesh.creation.box(extents=(4.0, 60.0, 1.0))
    spike.apply_translation((2.0, 30.0, 0.5))
    scene.add_geometry(body, geom_name="body")
    scene.add_geometry(spike, geom_name="spike")
    return scene


@pytest.mark.parametrize("captured_offset_y", [-6.5, -10.5])
def test_vector_top_center_clamps_inward_offset_to_local_contact_edge(
    captured_offset_y: float,
) -> None:
    scene = _irregular_scene()
    bounds = np.asarray(scene.bounds, dtype=np.float64)

    attach_x, attach_y = _vector_loop_attach_point(
        {
            "loop_position_preset": "top-center",
            "loop_width": 8.0,
            "loop_offset_x": 0.0,
            "loop_offset_y": captured_offset_y,
        },
        bounds,
        scene,
    )

    assert attach_x == 21.0
    assert attach_y == 58.0


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
