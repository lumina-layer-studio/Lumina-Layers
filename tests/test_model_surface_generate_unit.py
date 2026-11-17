from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from httpx import Response
import numpy as np
from PIL import Image
import pytest
import trimesh

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.routers.converter.generate import (
    MODEL_GENERATION_FAILED_DETAIL,
    _prepare_model_surface_overlay_worker_params,
    _should_use_model_surface_overlay,
)
from api.session_store import SessionStore
from config import ModelingMode as CoreModelingMode, PrinterConfig
from core.model_surface.assembly import OverlaySceneResult
from core.model_surface.types import ModelSurfaceError
from core.pipeline.s06_voxel_building import _build_voxel_matrix


def _mesh_from_3mf_object(
    node: ET.Element,
    namespace: dict[str, str],
) -> trimesh.Trimesh:
    vertices = np.asarray(
        [
            (
                float(vertex.attrib["x"]),
                float(vertex.attrib["y"]),
                float(vertex.attrib["z"]),
            )
            for vertex in node.findall(
                "m:mesh/m:vertices/m:vertex",
                namespace,
            )
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [
            (
                int(triangle.attrib["v1"]),
                int(triangle.attrib["v2"]),
                int(triangle.attrib["v3"]),
            )
            for triangle in node.findall(
                "m:mesh/m:triangles/m:triangle",
                namespace,
            )
        ],
        dtype=np.int64,
    )
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def _coplanar_xy_area(mesh: trimesh.Trimesh, z_mm: float) -> float:
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    on_plane = np.all(np.isclose(triangles[:, :, 2], z_mm, atol=1e-6), axis=1)
    edge_a = triangles[on_plane, 1, :2] - triangles[on_plane, 0, :2]
    edge_b = triangles[on_plane, 2, :2] - triangles[on_plane, 0, :2]
    return float(
        np.abs(edge_a[:, 0] * edge_b[:, 1] - edge_a[:, 1] * edge_b[:, 0]).sum()
        * 0.5
    )


@pytest.fixture()
def generate_state():
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = type("FakePool", (), {})()
    previous = {
        get_session_store: app.dependency_overrides.get(get_session_store),
        get_file_registry: app.dependency_overrides.get(get_file_registry),
        get_worker_pool: app.dependency_overrides.get(get_worker_pool),
    }
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool
    try:
        yield store, registry, pool
    finally:
        store.clear_all()
        registry.clear_all()
        for dependency, old_override in previous.items():
            if old_override is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = old_override


def _seed_model_surface_generate_session(
    tmp_path: Path,
    store: SessionStore,
) -> str:
    rendered_surface_art_path = tmp_path / "surface-error-art.svg"
    lut_path = tmp_path / "surface-error-lut.npy"
    model_path = tmp_path / "surface-error-plate.stl"
    rendered_surface_art_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">'
        '<path d="M0 0H20V10H0Z" fill="#ff0000"/>'
        "</svg>",
        encoding="utf-8",
    )
    lut_path.write_bytes(b"lut")
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)

    session_id = store.create()
    store.put(
        session_id,
        "preview_cache",
        {"target_w": 20, "target_h": 10, "target_width_mm": 20.0},
    )
    store.put(session_id, "image_path", str(rendered_surface_art_path))
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "surface_overlay_enabled", True)
    store.put(session_id, "surface_model_path", str(model_path))
    store.put(
        session_id,
        "surface_artwork_path",
        str(rendered_surface_art_path),
    )
    store.put(
        session_id,
        "surface_footprint",
        {
            "frame": {
                "origin": [0.0, 0.0, 1.0],
                "normal": [0.0, 0.0, 1.0],
                "u_axis": [1.0, 0.0, 0.0],
                "v_axis": [0.0, 1.0, 0.0],
            },
            "outer": [
                [-10.0, -5.0],
                [10.0, -5.0],
                [10.0, 5.0],
                [-10.0, 5.0],
                [-10.0, -5.0],
            ],
            "holes": [],
            "bounds_width_mm": 20.0,
            "bounds_height_mm": 10.0,
        },
    )
    return session_id


def _post_model_surface_generate(
    session_id: str,
    *,
    backing_infill_density_percent: int = 100,
) -> Response:
    return TestClient(app, raise_server_exceptions=False).post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "target_width_mm": 20.0,
                "lut_name": "default",
                "modeling_mode": CoreModelingMode.VECTOR.value,
                "model_enable": True,
                "backing_infill_density_percent": backing_infill_density_percent,
            },
        },
    )


def test_should_use_model_surface_overlay_requires_session_flag():
    assert _should_use_model_surface_overlay({"surface_overlay_enabled": True}) is True
    assert _should_use_model_surface_overlay({"surface_overlay_enabled": False}) is False
    assert _should_use_model_surface_overlay({}) is False


def test_generate_rejects_sparse_backing_for_model_surface(
    tmp_path: Path,
    generate_state,
) -> None:
    store, _registry, pool = generate_state
    session_id = _seed_model_surface_generate_session(tmp_path, store)
    pool.submit_timed = AsyncMock()

    response = _post_model_surface_generate(
        session_id,
        backing_infill_density_percent=20,
    )

    assert response.status_code == 422
    assert "model surface" in response.json()["detail"].lower()
    pool.submit_timed.assert_not_awaited()


def test_generate_routes_model_surface_session_to_overlay_worker(
    tmp_path,
    generate_state,
):
    store, registry, pool = generate_state
    original_image_path = tmp_path / "uploaded-art.png"
    rendered_surface_art_path = tmp_path / "surface-rendered-art.svg"
    lut_path = tmp_path / "lut.npy"
    model_path = tmp_path / "plate.stl"
    Image.new("RGB", (20, 10), (0, 0, 255)).save(original_image_path)
    rendered_surface_art_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">'
        '<path d="M0 0H20V10H0Z" fill="#ff0000"/>'
        "</svg>",
        encoding="utf-8",
    )
    lut_path.write_bytes(b"lut")
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)

    sid = store.create()
    store.put(
        sid,
        "preview_cache",
        {
            "target_w": 20,
            "target_h": 10,
            "target_width_mm": 20.0,
        },
    )
    store.put(sid, "image_path", str(rendered_surface_art_path))
    store.put(sid, "lut_path", str(lut_path))
    store.put(sid, "surface_overlay_enabled", True)
    store.put(sid, "surface_model_path", str(model_path))
    store.put(sid, "surface_artwork_path", str(rendered_surface_art_path))
    store.put(
        sid,
        "surface_model_transform",
        {"rotation_deg": {"x": 10, "y": 20, "z": 30}},
    )
    store.put(
        sid,
        "surface_footprint",
        {
            "frame": {
                "origin": [0.0, 0.0, 1.0],
                "normal": [0.0, 0.0, 1.0],
                "u_axis": [1.0, 0.0, 0.0],
                "v_axis": [0.0, 1.0, 0.0],
            },
            "outer": [[-10.0, -5.0], [10.0, -5.0], [10.0, 5.0], [-10.0, 5.0], [-10.0, -5.0]],
            "holes": [],
            "bounds_width_mm": 20.0,
            "bounds_height_mm": 10.0,
        },
    )

    async def fake_submit(_fn, *_args, **_kwargs):
        out_path = tmp_path / "surface.3mf"
        glb_path = tmp_path / "surface.glb"
        out_path.write_bytes(b"3mf")
        glb_path.write_bytes(b"generated surface glb")
        return (
            {
                "threemf_path": str(out_path),
                "glb_path": str(glb_path),
                "status_msg": "Surface OK",
            },
            {
                "queue_wait_s": 0.0,
                "worker_execution_s": 0.0,
                "result_delivery_s": 0.0,
            },
        )

    pool.submit_timed = AsyncMock(side_effect=fake_submit)

    client = TestClient(app)
    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": sid,
            "params": {
                "target_width_mm": 20.0,
                "lut_name": "default",
                "modeling_mode": CoreModelingMode.VECTOR.value,
                "add_loop": True,
                "enable_fridge_magnet": True,
                "model_enable": True,
            },
        },
    )

    assert response.status_code == 200, response.text
    from api.workers.converter_workers import worker_generate_model_surface_overlay

    worker_fn, submitted_image, submitted_lut, submitted_params = (
        pool.submit_timed.call_args.args
    )
    assert worker_fn is worker_generate_model_surface_overlay
    assert submitted_image == str(rendered_surface_art_path)
    assert submitted_image != str(original_image_path)
    assert submitted_lut == str(lut_path)
    assert submitted_params["surface_model_path"] == str(model_path)
    assert submitted_params["surface_model_transform"] == {
        "rotation_deg": {"x": 10, "y": 20, "z": 30}
    }
    assert submitted_params["surface_pocket_depth_mm"] == pytest.approx(0.4)
    assert submitted_params["surface_footprint"]["bounds_width_mm"] == 20.0
    assert submitted_params["converter_params"]["target_width_mm"] == 20.0
    assert (
        submitted_params["converter_params"]["modeling_mode"]
        == CoreModelingMode.VECTOR.value
    )
    assert submitted_params["converter_params"]["structure_mode"] == "Single-sided"
    assert submitted_params["converter_params"]["add_loop"] is False
    assert submitted_params["converter_params"]["enable_fridge_magnet"] is False
    assert submitted_params["converter_params"]["model_enable"] is True
    assert (
        submitted_params["converter_params"]["backing_infill_density_percent"]
        == 100
    )
    assert "surface_model_path" not in submitted_params["converter_params"]
    assert response.json()["preview_3d_url"] is None
    assert not (tmp_path / "surface.glb").exists()

    download_url = response.json()["download_url"]
    download_file_id = download_url.rsplit("/", 1)[-1]
    entry = registry.get_entry(download_file_id)
    assert entry is not None
    assert entry["lifecycle"] == "ephemeral"
    assert entry["session_id"] != sid

    close_response = client.post(
        "/api/session/close",
        json={"session_id": sid},
    )
    assert close_response.status_code == 200

    download_response = client.get(download_url)
    assert download_response.status_code == 200
    assert download_response.content == b"3mf"


def test_generate_maps_model_surface_known_error_to_422(
    tmp_path: Path,
    generate_state,
) -> None:
    store, _registry, pool = generate_state
    session_id = _seed_model_surface_generate_session(tmp_path, store)
    pool.submit_timed = AsyncMock(
        side_effect=ModelSurfaceError(
            "model_surface_insufficient_thickness: "
            "pattern=0.400000, available=0.200000"
        )
    )

    response = _post_model_surface_generate(session_id)

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error": "model_surface_insufficient_thickness",
        "message": (
            "The selected surface is too thin for the current colour stack. "
            "Use fewer layers, a smaller layer height, or a thicker surface."
        ),
    }


def test_generate_maps_model_surface_unknown_error_to_generic_500(
    tmp_path: Path,
    generate_state,
) -> None:
    store, _registry, pool = generate_state
    session_id = _seed_model_surface_generate_session(tmp_path, store)
    pool.submit_timed = AsyncMock(
        side_effect=ModelSurfaceError("private_unclassified_surface_error")
    )

    response = _post_model_surface_generate(session_id)

    assert response.status_code == 500
    assert response.json()["detail"] == MODEL_GENERATION_FAILED_DETAIL


def test_model_surface_vector_request_is_never_silently_downgraded(tmp_path):
    image_path = tmp_path / "surface-art.svg"
    model_path = tmp_path / "plate.stl"
    image_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">'
        '<path d="M0 0H20V10H0Z" fill="#ff0000"/>'
        "</svg>",
        encoding="utf-8",
    )
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)

    worker_params = _prepare_model_surface_overlay_worker_params(
        {
            "surface_model_path": str(model_path),
            "surface_artwork_path": str(image_path),
            "surface_footprint": {
                "frame": {
                    "origin": [0.0, 0.0, 1.0],
                    "normal": [0.0, 0.0, 1.0],
                    "u_axis": [1.0, 0.0, 0.0],
                    "v_axis": [0.0, 1.0, 0.0],
                },
                "outer": [
                    [-10.0, -5.0],
                    [10.0, -5.0],
                    [10.0, 5.0],
                    [-10.0, 5.0],
                    [-10.0, -5.0],
                ],
                "holes": [],
                "bounds_width_mm": 20.0,
                "bounds_height_mm": 10.0,
            },
        },
        {
            "target_width_mm": 20.0,
            "spacer_thick": 1.2,
            "structure_mode": "Double-sided",
            "color_mode": "4-Color (RYBW)",
            "modeling_mode": CoreModelingMode.VECTOR,
            "enable_relief": True,
            "enable_cloisonne": True,
            "enable_coating": True,
            "add_loop": True,
            "loop_pos": "top",
        },
    )

    assert worker_params["converter_params"]["modeling_mode"] == CoreModelingMode.VECTOR
    assert worker_params["converter_params"]["structure_mode"] == "Single-sided"
    assert worker_params["converter_params"]["enable_relief"] is False
    assert worker_params["converter_params"]["enable_cloisonne"] is False
    assert worker_params["converter_params"]["enable_coating"] is False
    assert worker_params["converter_params"]["backing_infill_density_percent"] == 100

    optical_layers = 4
    material_matrix = np.ones((2, 3, optical_layers), dtype=np.int16)
    full_matrix, _backing = _build_voxel_matrix(
        material_matrix,
        np.ones((2, 3), dtype=bool),
        1.2,
        worker_params["converter_params"]["structure_mode"],
        backing_color_id=0,
    )
    spacer_layers = max(1, round(1.2 / PrinterConfig.LAYER_HEIGHT))
    assert full_matrix.shape[0] == optical_layers + spacer_layers
    assert np.count_nonzero(full_matrix[optical_layers:] == 1) == 0


def test_worker_generate_model_surface_overlay_exports_bambu_3mf(tmp_path):
    image_path = tmp_path / "surface-art.png"
    lut_path = tmp_path / "lut.npy"
    model_path = tmp_path / "plate.stl"
    Image.new("RGB", (20, 10), (255, 0, 0)).save(image_path)
    lut_path.write_bytes(b"lut")
    model_path.write_bytes(b"solid plate\nendsolid plate\n")

    scene = trimesh.Scene()
    scene.add_geometry(
        trimesh.creation.box(extents=(20.0, 10.0, 1.0)),
        node_name="surface_base",
        geom_name="surface_base",
    )
    scene.metadata["model_surface_display_layer_heights_mm"] = (0.04,) * 7
    overlay = OverlaySceneResult(
        scene=scene,
        slot_names=["surface_base", "red"],
        preview_colors={"surface_base": (245, 245, 245), "red": (255, 0, 0)},
    )
    captured: dict[str, object] = {}

    def fake_export_scene_with_bambu_metadata(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"3mf")
        captured.update(kwargs)
        return kwargs["output_path"]

    def fake_build_surface_overlay_scene(**kwargs):
        assert kwargs["model_path"] == str(model_path)
        assert kwargs["artwork_image_path"] == str(image_path)
        assert kwargs["lut_path"] == str(lut_path)
        assert kwargs["pocket_depth_mm"] == pytest.approx(0.35)
        assert kwargs["model_transform"] == {"rotation_deg": {"x": 0, "y": 0, "z": 90}}
        assert kwargs["footprint"].bounds_width_mm == pytest.approx(20.0)
        assert kwargs["converter_params"]["target_width_mm"] == 20.0
        assert kwargs["converter_params"]["structure_mode"] == "Single-sided"
        assert kwargs["converter_params"]["enable_relief"] is False
        assert kwargs["converter_params"]["enable_cloisonne"] is False
        assert kwargs["converter_params"]["enable_coating"] is False
        return overlay

    from api.workers.converter_workers import worker_generate_model_surface_overlay

    with (
        patch(
            "core.model_surface.pipeline.build_surface_overlay_scene",
            side_effect=fake_build_surface_overlay_scene,
        ),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=fake_export_scene_with_bambu_metadata,
        ),
    ):
        result = worker_generate_model_surface_overlay(
            str(image_path),
            str(lut_path),
            {
                "surface_model_path": str(model_path),
                "surface_footprint": {
                    "frame": {
                        "origin": [0.0, 0.0, 1.0],
                        "normal": [0.0, 0.0, 1.0],
                        "u_axis": [1.0, 0.0, 0.0],
                        "v_axis": [0.0, 1.0, 0.0],
                    },
                    "outer": [
                        [-10.0, -5.0],
                        [10.0, -5.0],
                        [10.0, 5.0],
                        [-10.0, 5.0],
                        [-10.0, -5.0],
                    ],
                    "holes": [],
                    "bounds_width_mm": 20.0,
                    "bounds_height_mm": 10.0,
                },
                "surface_model_transform": {
                    "rotation_deg": {
                        "x": 0,
                        "y": 0,
                        "z": 90,
                    }
                },
                "surface_pocket_depth_mm": 0.35,
                "converter_params": {
                    "target_width_mm": 20.0,
                    "spacer_thick": 1.2,
                    "structure_mode": "Double-sided",
                    "color_mode": "4-Color (RYBW)",
                    "material_source": "material_archive",
                    "material_layer_height_mm": 0.08,
                    "enable_relief": True,
                    "enable_cloisonne": True,
                    "enable_coating": True,
                    "enable_wipe_tower_auto_placement": False,
                    "add_loop": False,
                    "loop_width": 4.0,
                    "loop_length": 8.0,
                    "loop_hole": 2.5,
                    "loop_pos": None,
                },
                "printer_id": "bambu-p1s",
                "slicer": "OrcaSlicer",
                "nozzle_size": "0.4",
                "device_profile_id": "OrcaSlicer:bbl:bambu-lab-p1s:0.4",
            },
        )

    assert Path(result["threemf_path"]).exists()
    assert result["glb_path"] is None
    assert result["status_msg"] == "Surface overlay model generated"
    assert captured["scene"] is scene
    assert captured["slot_names"] == ["surface_base", "red"]
    assert captured["project_slot_names"] == ["surface_base", "red"]
    assert captured["preserve_template_filament_slots"] is False
    assert captured["preview_colors"] == overlay.preview_colors
    assert captured["cover_source"] == str(image_path)
    assert captured["settings"] == {"layer_height": "0.04"}
    assert captured["enable_base_layer_height_modifier"] is False
    assert captured["enable_wipe_tower_auto_placement"] is False
    assert captured["device_profile_id"] == "OrcaSlicer:bbl:bambu-lab-p1s:0.4"
    Path(result["threemf_path"]).unlink(missing_ok=True)
    assert not list(tmp_path.glob("*.glb"))


def test_worker_does_not_export_print_scene_as_surface_preview_glb(tmp_path):
    image_path = tmp_path / "surface-art.png"
    lut_path = tmp_path / "lut.npy"
    model_path = tmp_path / "plate.stl"
    Image.new("RGB", (2, 2), (255, 0, 0)).save(image_path)
    lut_path.write_bytes(b"lut")
    model_path.write_bytes(b"solid plate\nendsolid plate\n")

    scene = trimesh.Scene(
        {"surface_base": trimesh.creation.box(extents=(2.0, 2.0, 1.0))}
    )
    overlay = OverlaySceneResult(
        scene=scene,
        slot_names=["surface_base"],
        preview_colors={"surface_base": (245, 245, 245)},
    )

    def fake_export_scene_with_bambu_metadata(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"3mf")
        return kwargs["output_path"]

    from api.workers.converter_workers import worker_generate_model_surface_overlay

    with (
        patch("config.TEMP_DIR", str(tmp_path)),
        patch(
            "core.model_surface.pipeline.build_surface_overlay_scene",
            return_value=overlay,
        ),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=fake_export_scene_with_bambu_metadata,
        ),
        patch.object(
            trimesh.Scene,
            "export",
            side_effect=AssertionError("print scene must not become browser GLB"),
        ) as export_glb,
    ):
        result = worker_generate_model_surface_overlay(
            str(image_path),
            str(lut_path),
            {
                "surface_model_path": str(model_path),
                "surface_footprint": {
                    "frame": {
                        "origin": [0.0, 0.0, 1.0],
                        "normal": [0.0, 0.0, 1.0],
                        "u_axis": [1.0, 0.0, 0.0],
                        "v_axis": [0.0, 1.0, 0.0],
                    },
                    "outer": [
                        [-1.0, -1.0],
                        [1.0, -1.0],
                        [1.0, 1.0],
                        [-1.0, 1.0],
                        [-1.0, -1.0],
                    ],
                    "holes": [],
                    "bounds_width_mm": 2.0,
                    "bounds_height_mm": 2.0,
                },
                "surface_pocket_depth_mm": 0.08,
                "converter_params": {
                    "target_width_mm": 2.0,
                    "backing_infill_density_percent": 100,
                },
            },
        )

    output_path = Path(result["threemf_path"])
    try:
        assert output_path.read_bytes() == b"3mf"
        assert result["glb_path"] is None
        export_glb.assert_not_called()
        assert not list(tmp_path.glob("*.glb"))
    finally:
        output_path.unlink(missing_ok=True)




def test_worker_generate_model_surface_overlay_rejects_sparse_backing(tmp_path):
    from api.workers.converter_workers import worker_generate_model_surface_overlay

    with pytest.raises(ValueError, match="model surface"):
        worker_generate_model_surface_overlay(
            str(tmp_path / "art.png"),
            str(tmp_path / "lut.npy"),
            {
                "converter_params": {
                    "backing_infill_density_percent": 20,
                },
            },
        )


def test_worker_generates_native_vector_surface_3mf_without_board_or_margin_stretch(
    tmp_path,
):
    """Real SVG worker path keeps native color meshes and logical canvas margins."""

    image_path = tmp_path / "surface-art.svg"
    model_path = tmp_path / "plate.stl"
    image_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">'
        '<path d="M2 2H5V8H2Z" fill="#ff0000"/>'
        '<path d="M6 2H9V8H6Z" fill="#0000ff"/>'
        "</svg>",
        encoding="utf-8",
    )
    plate = trimesh.creation.box(extents=(20.0, 10.0, 2.0))
    plate.export(model_path)
    lut_path = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/lut_regression/赛纳&8色PLA-红-黄-蓝-品红-青-白-绿-黑.npy"
    )

    from api.workers.converter_workers import worker_generate_model_surface_overlay

    result = worker_generate_model_surface_overlay(
        str(image_path),
        str(lut_path),
        {
            "surface_model_path": str(model_path),
            "surface_footprint": {
                "frame": {
                    "origin": [0.0, 0.0, 1.0],
                    "normal": [0.0, 0.0, 1.0],
                    "u_axis": [1.0, 0.0, 0.0],
                    "v_axis": [0.0, 1.0, 0.0],
                },
                "outer": [
                    [-10.0, -5.0],
                    [10.0, -5.0],
                    [10.0, 5.0],
                    [-10.0, 5.0],
                    [-10.0, -5.0],
                ],
                "holes": [],
                "bounds_width_mm": 20.0,
                "bounds_height_mm": 10.0,
            },
            "surface_pocket_depth_mm": 0.4,
            "converter_params": {
                "target_width_mm": 20.0,
                "spacer_thick": 1.2,
                "structure_mode": "Single-sided",
                "color_mode": "8-Color Max",
                "modeling_mode": CoreModelingMode.VECTOR,
                "material_source": "lut",
                "color_layers": 7,
                "layer_height_mm": 0.08,
                "backing_color_id": 0,
                "separate_backing": False,
                "add_loop": False,
                "enable_relief": False,
                "enable_cloisonne": False,
                "enable_coating": False,
                "enable_outline": False,
                "center_on_bed": False,
            },
            "printer_id": "flashforge-ad5x",
            "slicer": "FlashStudio",
            "nozzle_size": "0.4",
        },
    )

    output_path = Path(result["threemf_path"])
    assert result["glb_path"] is None
    try:
        assert output_path.exists()
        core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
        with zipfile.ZipFile(output_path, "r") as archive:
            object_model = ET.fromstring(
                archive.read("3D/Objects/object_1.model")
            )
            cover_thumbnail = np.asarray(
                Image.open(
                    BytesIO(
                        archive.read(
                            "Auxiliaries/.thumbnails/thumbnail_middle.png"
                        )
                    )
                ).convert("RGB")
            )
        assert np.any(cover_thumbnail < 250)
        objects = object_model.findall("m:resources/m:object", core_ns)
        names = [str(node.attrib.get("name") or "") for node in objects]
        assert names.count("surface_base") == 1
        assert "Board" not in names
        color_objects = [
            node for node in objects if node.attrib.get("name") != "surface_base"
        ]
        assert len(color_objects) >= 2
        base_object = next(
            node
            for node in objects
            if node.attrib.get("name") == "surface_base"
        )
        base_mesh = _mesh_from_3mf_object(base_object, core_ns)

        color_vertices = [
            (
                float(vertex.attrib["x"]),
                float(vertex.attrib["y"]),
                float(vertex.attrib["z"]),
            )
            for node in color_objects
            for vertex in node.findall("m:mesh/m:vertices/m:vertex", core_ns)
        ]
        base_vertices = [
            (
                float(vertex.attrib["x"]),
                float(vertex.attrib["y"]),
                float(vertex.attrib["z"]),
            )
            for vertex in objects[0].findall(
                "m:mesh/m:vertices/m:vertex",
                core_ns,
            )
        ]
        color_x = [vertex[0] for vertex in color_vertices]
        color_y = [vertex[1] for vertex in color_vertices]
        color_z = [vertex[2] for vertex in color_vertices]
        base_z = [vertex[2] for vertex in base_vertices]
        assert max(color_x) - min(color_x) == pytest.approx(7.0, abs=0.05)
        assert max(color_y) - min(color_y) == pytest.approx(6.0, abs=0.05)
        assert (min(color_x) + max(color_x)) / 2.0 > 0.5
        assert min(base_z) == pytest.approx(min(color_z), abs=1e-6)
        assert _coplanar_xy_area(base_mesh, min(color_z)) == pytest.approx(
            164.0,
            abs=0.1,
        )
        assert max(color_z) < max(base_z)
    finally:
        output_path.unlink(missing_ok=True)


def test_worker_preserves_surface_under_transparent_png(tmp_path):
    image_path = tmp_path / "surface-art.png"
    model_path = tmp_path / "plate.stl"
    rgba = np.zeros((10, 20, 4), dtype=np.uint8)
    rgba[2:8, 2:5] = (255, 0, 0, 255)
    rgba[2:8, 6:9] = (0, 0, 255, 255)
    Image.fromarray(rgba, mode="RGBA").save(image_path)
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)
    lut_path = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/lut_regression/快造&4色PLA&RYBW.npy"
    )

    from api.workers.converter_workers import worker_generate_model_surface_overlay

    result = worker_generate_model_surface_overlay(
        str(image_path),
        str(lut_path),
        {
            "surface_model_path": str(model_path),
            "surface_footprint": {
                "frame": {
                    "origin": [0.0, 0.0, 1.0],
                    "normal": [0.0, 0.0, 1.0],
                    "u_axis": [1.0, 0.0, 0.0],
                    "v_axis": [0.0, 1.0, 0.0],
                },
                "outer": [
                    [-10.0, -5.0],
                    [10.0, -5.0],
                    [10.0, 5.0],
                    [-10.0, 5.0],
                    [-10.0, -5.0],
                ],
                "holes": [],
                "bounds_width_mm": 20.0,
                "bounds_height_mm": 10.0,
            },
            "surface_pocket_depth_mm": 0.4,
            "converter_params": {
                "target_width_mm": 20.0,
                "spacer_thick": 1.2,
                "structure_mode": "Single-sided",
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": CoreModelingMode.HIGH_FIDELITY,
                "material_source": "lut",
                "color_layers": 7,
                "layer_height_mm": 0.08,
                "backing_color_id": 0,
                "separate_backing": False,
                "add_loop": False,
                "enable_relief": False,
                "enable_cloisonne": False,
                "enable_coating": False,
                "enable_outline": False,
                "center_on_bed": False,
            },
            "printer_id": "snapmaker-u1",
            "slicer": "OrcaSlicer",
            "nozzle_size": "0.4",
        },
    )

    output_path = Path(result["threemf_path"])
    assert result["glb_path"] is None
    try:
        core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
        with zipfile.ZipFile(output_path, "r") as archive:
            object_model = ET.fromstring(archive.read("3D/Objects/object_1.model"))
        objects = object_model.findall("m:resources/m:object", core_ns)
        base_object = next(
            node
            for node in objects
            if node.attrib.get("name") == "surface_base"
        )
        color_objects = [
            node
            for node in objects
            if node.attrib.get("name") != "surface_base"
        ]
        base_mesh = _mesh_from_3mf_object(base_object, core_ns)
        color_meshes = [
            _mesh_from_3mf_object(node, core_ns)
            for node in color_objects
        ]
        visible_z = min(
            float(mesh.bounds[0, 2])
            for mesh in color_meshes
        )
        base_surface_area = _coplanar_xy_area(base_mesh, visible_z)
        artwork_surface_area = sum(
            _coplanar_xy_area(mesh, visible_z)
            for mesh in color_meshes
        )

        assert base_mesh.bounds[0, 2] == pytest.approx(visible_z, abs=1e-6)
        assert base_surface_area > 100.0
        assert base_surface_area + artwork_surface_area == pytest.approx(
            200.0,
            abs=0.2,
        )
    finally:
        output_path.unlink(missing_ok=True)


def test_model_surface_layer_height_rejects_nonuniform_dynamic_schedule():
    from api.workers.converter_workers import (
        _resolve_model_surface_display_layer_height_mm,
    )

    with pytest.raises(ValueError, match="non-uniform display layer heights"):
        _resolve_model_surface_display_layer_height_mm(
            {
                "material_source": "material_archive",
                "material_layer_height_mm": 0.08,
                "display_layer_heights_mm": [0.04, 0.08, 0.10],
            }
        )


def test_model_surface_layer_height_rejects_invalid_archive_height():
    from api.workers.converter_workers import (
        _resolve_model_surface_display_layer_height_mm,
    )

    with pytest.raises(ValueError, match="positive and finite"):
        _resolve_model_surface_display_layer_height_mm(
            {
                "material_source": "material_archive",
                "material_layer_height_mm": 0.0,
            }
        )
