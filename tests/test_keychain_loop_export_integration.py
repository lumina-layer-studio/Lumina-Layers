"""Verify keychain behavior in the actual packaged 3MF geometry."""

from io import BytesIO
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest
from scipy.spatial import cKDTree
from shapely.affinity import rotate, scale, translate
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union
import trimesh

import config
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import externalize_preview_cache
from api.routers.converter import generate as generate_router, preview as preview_router
from api.session_store import SessionStore
from api.workers.converter_workers import worker_generate_model
from core.converter import generate_preview_cached
from core.geometry_utils import keychain_loop_footprint
from core.pipeline import s09_export_3mf, s11_glb_preview

ANGLES = (-90, -45, 0, 37, 45, 90, 180)
PRESETS = ("top-center", "top-left", "top-right", "left-center", "right-center", "bottom-center")
CONTRACT = json.loads((Path(__file__).parent / "fixtures/keychain_rotation_reference.json").read_text())
# The default fit aims for a 0.4 mm wide solid patch. Allow 0.005 mm²
# variation between the prepared outline and the serialized print layers.
MIN_JOINT_MM2 = np.pi * 0.2 ** 2 - 0.005


def _transform_points(points: np.ndarray, element: ET.Element) -> np.ndarray:
    transform = element.get("transform")
    if transform is None:
        return points
    matrix = np.fromstring(transform, sep=" ").reshape(4, 3)
    return points @ matrix[:3] + matrix[3]


def _read_print_meshes(path: Path) -> tuple[list[trimesh.Trimesh], trimesh.Trimesh]:
    """Read the serialized mesh parts with all assembly and build transforms."""
    groups = {"body": [], "loop": []}
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
                faces = [
                    [int(face.attrib[key]) for key in ("v1", "v2", "v3")]
                    for face in mesh.findall("{*}triangles/{*}triangle")
                ]
                groups[group].append(trimesh.Trimesh(points, faces, process=False))
    assert groups["body"] and len(groups["loop"]) == 1
    return groups["body"], groups["loop"][0]


def _projection(meshes: list[trimesh.Trimesh]) -> BaseGeometry:
    return unary_union([
        triangle for mesh in meshes
        for xy in mesh.triangles[:, :, :2]
        if (triangle := Polygon(xy)).area > 1e-9
    ])


def _read_print_footprints(path: Path) -> tuple[BaseGeometry, BaseGeometry, tuple[float, float], tuple[float, float]]:
    bodies, ring = _read_print_meshes(path)
    body_z = min(mesh.bounds[0, 2] for mesh in bodies), max(mesh.bounds[1, 2] for mesh in bodies)
    return _projection(bodies), _projection([ring]), body_z, tuple(ring.bounds[:, 2])


def _section(mesh: trimesh.Trimesh, z: float) -> BaseGeometry:
    """Cut the actual triangles and fill their closed loops by even/odd parity."""
    if z <= mesh.bounds[0, 2] or z >= mesh.bounds[1, 2]:
        return Polygon()
    segments = trimesh.intersections.mesh_plane(mesh, [0, 0, 1], [0, 0, z])[:, :, :2]
    if not len(segments):
        return Polygon()
    points = segments.reshape(-1, 2).copy()
    neighbors = cKDTree(points).query_ball_point(points, 1e-7)
    closed_segments = points[[min(group) for group in neighbors]].reshape(-1, 2, 2)
    polygons = polygonize(LineString(edge) for edge in closed_segments if np.any(edge[0] != edge[1]))
    section = Polygon()
    for ring in sorted((Polygon(poly.exterior) for poly in polygons), key=lambda poly: -poly.area):
        section = section.symmetric_difference(ring)
    assert not section.is_empty, z
    return section


def _measure_print_sections(path: Path) -> tuple[float, float, float]:
    bodies, ring = _read_print_meshes(path)
    assert ring.is_volume
    heights = np.unique(np.round(np.concatenate([mesh.vertices[:, 2] for mesh in [ring, *bodies]]), 6))
    joints = []
    body_slices = []
    nominal_hole = None
    for low, high in zip(heights, heights[1:]):
        body = unary_union([_section(mesh, (low + high) / 2) for mesh in bodies])
        loop = _section(ring, (low + high) / 2)
        body_slices.append(body)
        if loop.is_empty:
            continue
        assert isinstance(loop, Polygon) and len(loop.interiors) == 1
        nominal_hole = Polygon(loop.interiors[0])
        if not body.is_empty:
            joints.append(loop.intersection(body).area)
    assert joints and nominal_hole is not None
    return min(joints), nominal_hole.difference(unary_union(body_slices)).area, nominal_hole.area


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


class _InlinePool:
    async def submit(self, worker, *args):
        return worker(*args)

    async def submit_timed(self, worker, *args):
        return await self.submit(worker, *args), {}


def _preview_anchor(client: TestClient, session: str, angle: float, preset: str) -> dict[str, float]:
    response = client.post("/api/convert/keychain-anchor", json={
        "session_id": session, "width": 6, "length": 8, "hole": 2.5,
        "angle": angle, "preset": preset,
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def keychain_api(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_router, "TEMP_DIR", str(tmp_path))
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app = FastAPI()
    app.include_router(preview_router.router, prefix="/api/convert")
    app.include_router(generate_router.router, prefix="/api/convert")
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = _InlinePool

    def create_session(source, lut, mode, width_mm=40):
        _, cache, status = generate_preview_cached(str(source), str(lut), width_mm, "4-Color (RYBW)", mode)
        assert cache is not None, status
        session = store.create()
        store.put(session, "preview_cache", externalize_preview_cache(session, store, cache, root_dir=tmp_path))
        store.put(session, "image_path", str(source))
        store.put(session, "lut_path", str(lut))
        return session

    with TestClient(app) as client:
        yield client, create_session, registry
    store.clear_all()
    registry.clear_all()


@pytest.mark.parametrize("mode", [config.ModelingMode.VECTOR, config.ModelingMode.PIXEL, config.ModelingMode.HIGH_FIDELITY])
@pytest.mark.parametrize("structure", ["Single-sided", "Double-sided"])
@pytest.mark.parametrize("preset", PRESETS)
def test_exported_ring_preserves_its_whole_profile_after_fitting(
    ring_export_source, keychain_api, mode, structure, preset,
) -> None:
    sources, lut = ring_export_source
    client, create_session, _ = keychain_api
    session = create_session(sources[mode], lut, mode)
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
        assert body.intersection(loop).area > MIN_JOINT_MM2, f"{angle}°: separation {body.distance(loop):.6f} mm"
        bore = Polygon(loop.interiors[0])
        assert bore.difference(body).area > bore.area - 0.005
        min_x, min_y, max_x, max_y = body.bounds
        centered = translate(loop, -(min_x + max_x) / 2, -(min_y + max_y) / 2)
        artwork_rings[angle] = scale(centered, xfact=-1, origin=(0, 0)) if structure == "Single-sided" else centered
        anchor = _preview_anchor(client, session, angle, preset)
        preview_ring = keychain_loop_footprint(6, 8, 2.5, anchor["x"], anchor["y"], angle)
        assert artwork_rings[angle].hausdorff_distance(preview_ring) < 0.01, angle

    unrotated = artwork_rings[0]
    min_x, min_y, max_x, _ = unrotated.bounds
    foot = ((min_x + max_x) / 2, min_y)
    if mode == config.ModelingMode.VECTOR and preset == "top-center":
        # The unrotated 3MF and the rendered preview share this artwork-space reference.
        assert foot == pytest.approx(CONTRACT["footMm"], abs=5e-4)
    for angle, ring in artwork_rings.items():
        expected = rotate(unrotated, angle, origin=foot)
        expected = translate(expected, ring.centroid.x - expected.centroid.x, ring.centroid.y - expected.centroid.y)
        # Fitting can move the foot. Comparing the complete aligned profiles
        # still catches an incorrect sign, rotation or bore deformation.
        assert ring.hausdorff_distance(expected) < 1e-4, angle
        assert ring.symmetric_difference(expected).area < 1e-3, angle


def _review_source(ring_export_source, mode, outline):
    sources, lut = ring_export_source
    source = sources[mode].with_stem(outline)
    if mode == config.ModelingMode.VECTOR:
        path = {"notch": "M0 0H18V14H33V0H40V30H0Z", "slope": "M0 0H16L24 24H40V30H0Z"}[outline]
        source.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="30mm" viewBox="0 0 40 30">'
            f'<path fill="#dc143c" d="{path}"/></svg>', encoding="utf-8",
        )
    else:
        y, x = (np.indices((150, 200)) + 0.5) / 5
        occupied = (x < 18) | (x > 33) | (y > 14) if outline == "notch" else y >= np.clip((x - 16) * 3, 0, 24)
        rgba = np.zeros((150, 200, 4), dtype=np.uint8)
        rgba[occupied] = (220, 20, 60, 255)
        Image.fromarray(rgba).save(source)
    return source, lut


def _review_parameters(mode, structure, angle, offset_y, offset_x=0):
    return {
        "modeling_mode": mode.value, "target_width_mm": 40, "spacer_thick": 1.2,
        "lut_name": "review-palette",
        "structure_mode": structure, "color_mode": "4-Color (RYBW)",
        "add_loop": True, "loop_position_preset": "top-center", "loop_pos": None,
        "loop_width": 6, "loop_length": 8, "loop_hole": 2.5, "loop_angle": angle,
        "loop_offset_x": offset_x, "loop_offset_y": offset_y,
        "printer_id": "bambu-a1", "enable_wipe_tower_auto_placement": False,
    }


@pytest.mark.parametrize("outline,angle,offset_y,offset_x", [
    ("notch", -90, 0, 0), ("notch", -90, -4, 0), ("notch", 90, 0, 0),
    ("slope", -90, 0, 0), ("slope", 90, 0, 0), ("notch", -90, -4, -0.75),
])
@pytest.mark.parametrize("mode", [config.ModelingMode.VECTOR, config.ModelingMode.PIXEL, config.ModelingMode.HIGH_FIDELITY])
@pytest.mark.parametrize("structure", ["Single-sided", "Double-sided"])
def test_review_outlines_have_a_joint_and_open_bore(
    ring_export_source, keychain_api, mode, structure, outline, angle, offset_y, offset_x,
):
    source, lut = _review_source(ring_export_source, mode, outline)
    client, create_session, registry = keychain_api
    session = create_session(source, lut, mode)
    anchor = _preview_anchor(client, session, angle, "top-center")
    exported = client.post("/api/convert/generate", json={
        "session_id": session, "params": _review_parameters(mode, structure, angle, offset_y, offset_x),
    })
    assert exported.status_code == 200, exported.text
    output = registry.resolve(exported.json()["download_url"].rsplit("/", 1)[-1])
    assert output is not None
    file = Path(output[0])
    joint, through_bore, nominal_bore = _measure_print_sections(file)
    assert joint > MIN_JOINT_MM2, "The serialized ring must overlap the model through its build layers"
    assert nominal_bore == pytest.approx(4.877258, abs=1e-4)
    assert through_bore == pytest.approx(nominal_bore, abs=0.005), "The 2.5 mm bore must remain open through the print"

    body, loop, _, _ = _read_print_footprints(file)
    x0, y0, x1, y1 = body.bounds
    ring = translate(loop, -(x0 + x1) / 2, -(y0 + y1) / 2)
    if structure == "Single-sided":
        ring = scale(ring, xfact=-1, origin=(0, 0))
    preview_ring = keychain_loop_footprint(6, 8, 2.5, anchor["x"] + offset_x, anchor["y"] + offset_y, angle)
    assert ring.hausdorff_distance(preview_ring) < 0.01


@pytest.mark.parametrize("mode", [config.ModelingMode.VECTOR, config.ModelingMode.PIXEL, config.ModelingMode.HIGH_FIDELITY])
@pytest.mark.parametrize("offset_y,detail", [(30, "没有实体接合"), (-26, "完全堵住")])
def test_invalid_manual_placement_returns_422_without_a_file(ring_export_source, keychain_api, mode, offset_y, detail):
    source, lut = _review_source(ring_export_source, mode, "notch")
    client, create_session, _ = keychain_api
    session = create_session(source, lut, mode)
    response = client.post("/api/convert/generate", json={
        "session_id": session, "params": _review_parameters(mode, "Single-sided", 0, offset_y),
    })
    assert response.status_code == 422, response.text
    message = response.json()["detail"]
    assert detail in message
    assert "Adjust" in message
    assert not list(source.parent.glob("*.3mf"))


@pytest.mark.parametrize("width_mm,expected_tiles", [(40, 1), (80, 2)])
def test_large_format_archives_contain_no_keychain_part(ring_export_source, keychain_api, width_mm, expected_tiles):
    mode = config.ModelingMode.HIGH_FIDELITY
    source, lut = _review_source(ring_export_source, mode, "notch")
    client, create_session, registry = keychain_api
    session = create_session(source, lut, mode, width_mm)
    params = {
        **_review_parameters(mode, "Single-sided", -90, -4),
        "target_width_mm": width_mm, "add_loop": False,
    }
    exported = client.post("/api/convert/generate-large-format", json={
        "session_id": session,
        "params": {"tile_width_mm": 50, "tile_height_mm": 100, "params": params},
    })
    assert exported.status_code == 200, exported.text
    result = exported.json()
    assert result["tile_count"] == expected_tiles
    assert result["failed_tiles"] == []
    output = registry.resolve(result["download_url"].rsplit("/", 1)[-1])
    assert output is not None
    with ZipFile(output[0]) as bundle:
        assert bundle.testzip() is None
        tiles = [name for name in bundle.namelist() if name.endswith(".3mf")]
        assert len(tiles) == expected_tiles
        for name in tiles:
            with ZipFile(BytesIO(bundle.read(name))) as tile:
                settings = ET.fromstring(tile.read("Metadata/model_settings.config"))
                parts = settings.findall(".//part/metadata[@key='name']")
                assert parts
                assert all(part.get("value") != "Keychain_Loop" for part in parts), name
