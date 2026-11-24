"""Integration tests for converter puzzle layouts, generated meshes and worker scheduling."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pickle
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from xml.etree import ElementTree
from zipfile import ZipFile

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest
import shapely
import trimesh

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import externalize_preview_cache
from api.schemas.converter import ConvertGenerateRequest
from api.routers.converter import puzzle as puzzle_router
from api.selection_state import RECIPE_OVERRIDE_APPLIED_MASKS_KEY
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from core.errors import CoatingLayerHeightError
from core.material_dynamic_solver import DynamicMaterialSolverError
from core.puzzle import PuzzlePiece


@pytest.fixture()
def puzzle_harness(tmp_path, monkeypatch):
    """Create an isolated puzzle-router test client."""

    monkeypatch.setattr(puzzle_router, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("api.file_registry.TEMP_DIR", str(tmp_path))
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = MagicMock(spec=WorkerPoolManager)
    pool.max_workers = 2

    test_app = FastAPI()
    test_app.include_router(puzzle_router.router, prefix="/api/convert")
    test_app.dependency_overrides[get_session_store] = lambda: store
    test_app.dependency_overrides[get_file_registry] = lambda: registry
    test_app.dependency_overrides[get_worker_pool] = lambda: pool

    with TestClient(test_app, raise_server_exceptions=False) as client:
        yield {"client": client, "store": store, "registry": registry, "pool": pool}

    store.clear_all()
    registry.clear_all()


@pytest.fixture(autouse=True)
def stub_metadata_reads_for_stub_worker_packages(monkeypatch):
    """These route tests use sentinel bytes, not real source packages.

    Real source interpretation and assembly are exercised separately by the
    writer integration tests; keep these worker scheduling tests independent.
    """
    monkeypatch.setattr(puzzle_router, '_batch_extract_slots_from_3mf', lambda *args, **kwargs: [
        {'slot_id': 0, 'slot_name': 'White', 'preview_color': '#FFFFFF', 'material_id': 'PLA'},
    ])
    monkeypatch.setattr(puzzle_router, 'read_wipe_tower_placement_warnings', lambda path: [])
    # Scheduling fixtures have sentinel LUTs/material names, not native files.
    monkeypatch.setattr(puzzle_router, 'require_material_selection', lambda *args, **kwargs: {"materials": [
        {"name": name, "material_type": "PLA", "selected_profile_name": None} for name in ["White", "Red", "Blue"]
    ]})
    # Canary tests attach caplog directly, so do not deliver each record again
    # through pytest's root handler.
    monkeypatch.setattr(logging.getLogger("lumina.api.routers.converter.puzzle"), "propagate", False)


def _capture_puzzle_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    logger = logging.getLogger("lumina.api.routers.converter.puzzle")
    logger.addHandler(caplog.handler)
    logger.propagate = False
    caplog.set_level(logging.INFO, logger=logger.name)
    return logger


def _seed_puzzle_preview_session(store: SessionStore) -> str:
    session_id = store.create()
    matched_rgb = np.zeros((80, 120, 3), dtype=np.uint8)
    matched_rgb[:40, :, :] = [255, 0, 0]
    matched_rgb[40:, :, :] = [0, 255, 0]
    mask_solid = np.ones((80, 120), dtype=bool)
    preview_rgba = np.zeros((80, 120, 4), dtype=np.uint8)
    preview_rgba[..., :3] = matched_rgb
    preview_rgba[..., 3] = 255
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched_rgb,
            "mask_solid": mask_solid,
            "preview_rgba": preview_rgba,
            "preview_colors": {"White": (255, 255, 255, 255)},
            "slot_names": ["White"],
        },
    )
    return session_id


def _seed_puzzle_generate_session(store: SessionStore, tmp_path) -> str:
    session_id = _seed_puzzle_preview_session(store)
    image_path = tmp_path / "puzzle.png"
    lut_path = tmp_path / "palette.npy"
    image_data = np.zeros((80, 120, 3), dtype=np.uint8)
    image_data[:, :60, :] = [255, 0, 0]
    image_data[:, 60:, :] = [0, 255, 0]
    Image.fromarray(image_data).save(image_path)
    np.save(lut_path, np.zeros((1,), dtype=np.uint8))
    store.put(session_id, "image_path", str(image_path))
    store.put(session_id, "lut_path", str(lut_path))
    store.register_temp_file(session_id, str(image_path))
    store.register_temp_file(session_id, str(lut_path))
    return session_id


def _seed_dynamic_puzzle_generate_session(store: SessionStore, tmp_path) -> str:
    """Seed a material-archive puzzle preview with authority dynamic arrays."""

    session_id = _seed_puzzle_generate_session(store, tmp_path)
    session_data = store.get(session_id)
    assert session_data is not None
    cache = dict(session_data["preview_cache"])
    matched_rgb = cache["matched_rgb"]
    mask_solid = cache["mask_solid"]
    max_layers = 6
    material_matrix = np.full(
        (*mask_solid.shape, max_layers),
        -1,
        dtype=np.int32,
    )
    material_matrix[mask_solid] = [2, 1, 2, 1, 0, 0]
    cache["quantized_image"] = np.array(matched_rgb, copy=True)
    cache["material_matrix"] = material_matrix
    cache["material_dynamic_layer_info"] = {"enabled": True}
    cache.update(ConvertGenerateRequest.model_validate(
        _generate_puzzle_body(session_id)["params"]["params"],
    ).model_dump())
    cache.update(material_source="material_archive", color_layers=max_layers, layer_height_mm=0.08)
    store.put(session_id, "preview_cache", cache)
    store.put(session_id, "material_source", "material_archive")
    store.put(session_id, "selected_materials", ["White", "Red", "Blue"])
    store.put(session_id, "material_layer_count", max_layers)
    store.put(session_id, "material_layer_height_mm", 0.08)
    store.put(session_id, "material_backing_material_index", 0)
    store.put(session_id, "material_dynamic_layer_count_enabled", True)
    store.put(session_id, "material_min_layer_count", 5)
    store.put(session_id, "material_max_layer_count", max_layers)
    store.put(session_id, "material_delta_e00_tolerance", 0.5)
    return session_id


def _delete_externalized_preview_cache_field(
    store: SessionStore,
    session_id: str,
    tmp_path,
    field_name: str,
) -> Path:
    session_data = store.get(session_id)
    cache = session_data["preview_cache"]
    cache_ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", cache_ref)
    field_path = Path(cache_ref["fields"][field_name]["path"])
    field_path.unlink()
    return field_path


def _layout_preview_body(session_id: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "params": {
            "target_height_mm": 60.0,
            "puzzle_style": "regular",
            "sizing_mode": "grid",
            "piece_width_mm": 20.0,
            "piece_height_mm": 20.0,
            "rows": 2,
            "cols": 3,
            "target_piece_count": 6,
            "seed": 7,
            "connector_style": "classic",
            "labels_enabled": True,
            "engrave_back_labels": False,
            "irregularity_strength": 0.35,
            "min_neck_width_mm": 1.2,
        },
    }


def _generate_puzzle_body(session_id: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "params": {
            "target_height_mm": 60.0,
            "puzzle_style": "regular",
            "sizing_mode": "grid",
            "piece_width_mm": 20.0,
            "piece_height_mm": 20.0,
            "rows": 2,
            "cols": 2,
            "target_piece_count": 4,
            "seed": 7,
            "connector_style": "classic",
            "labels_enabled": False,
            "engrave_back_labels": False,
            "irregularity_strength": 0.35,
            "min_neck_width_mm": 1.2,
            "params": {
                "lut_name": "test_lut",
                "target_width_mm": 90.0,
                "modeling_mode": "high-fidelity",
                "color_mode": "4-Color (RYBW)",
                "add_loop": False,
                "enable_fridge_magnet": False,
                "enable_relief": False,
            },
        },
    }


def test_prepare_piece_worker_assets_adds_actual_cut_clearance() -> None:
    """Puzzle worker boundaries should remove 0.1mm total kerf from generated geometry."""

    source_rgba = np.full((40, 40, 4), 255, dtype=np.uint8)
    matched_rgb = np.full((40, 40, 3), 127, dtype=np.uint8)
    piece = PuzzlePiece(
        row=1,
        col=1,
        label="A1",
        polygon_px=((0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)),
        bbox_px=(0, 0, 40, 40),
        bbox_mm=(0.0, 0.0, 4.0, 4.0),
        centroid_mm=(2.0, 2.0),
    )

    assets = puzzle_router._prepare_piece_worker_assets(
        source_rgba,
        matched_rgb,
        piece,
    )
    boundary_payload = assets.boundary_payload

    polygon = boundary_payload["polygon_px"]
    x_values = [point[0] for point in polygon]
    y_values = [point[1] for point in polygon]

    assert min(x_values) == pytest.approx(0.5)
    assert min(y_values) == pytest.approx(0.5)
    assert max(x_values) == pytest.approx(39.5)
    assert max(y_values) == pytest.approx(39.5)
    assert boundary_payload["bbox_px"] == [0, 0, 40, 40]


def test_thin_mask_aware_piece_keeps_its_last_printable_cells() -> None:
    """The 0.05 mm inset must not remove the cells of a backing-only edge piece."""
    from core.mesh_generators import rasterize_boundary_geometry

    piece = PuzzlePiece(
        row=1,
        col=1,
        label="A1",
        polygon_px=((0.1, 0.0), (0.8, 0.0), (0.8, 10.0), (0.1, 10.0)),
        bbox_px=(0, 0, 1, 10),
        bbox_mm=(0.0, 0.0, 0.1, 1.0),
        centroid_mm=(0.05, 0.5),
        cut_edges_px=shapely.LineString([(0.1, 0.0), (0.1, 10.0)]),
    )
    rgba = np.zeros((10, 1, 4), dtype=np.uint8)
    backing = np.ones((10, 1), dtype=bool)
    assets = puzzle_router._prepare_piece_worker_assets(
        rgba, rgba[..., :3], piece, backing_mask=backing,
    )
    payload = assets.boundary_payload
    boundary = shapely.Polygon(payload["polygon_px"], payload["holes_px"])
    worker_cells = rasterize_boundary_geometry(boundary, height_px=10, width_px=1)
    np.testing.assert_array_equal(worker_cells & assets.backing_mask, backing)


def test_puzzle_does_not_submit_a_piece_with_no_cells_on_worker_grid(
    puzzle_harness, tmp_path, monkeypatch,
) -> None:
    """A subcell fragment can have source alpha and still produce no mesh."""
    session_id = _seed_puzzle_generate_session(puzzle_harness["store"], tmp_path)
    piece = PuzzlePiece(
        row=1,
        col=1,
        label="A1",
        polygon_px=((0.0, 0.0), (0.6, 0.0), (0.6, 10.0), (0.0, 10.0)),
        bbox_px=(0, 0, 3, 10),
        bbox_mm=(0.0, 0.0, 0.2, 1.0),
        centroid_mm=(0.05, 0.5),
    )
    resolve_layout = puzzle_router._resolve_layout

    def isolated_fragment(**kwargs):
        layout, key = resolve_layout(**kwargs)
        return replace(layout, pieces=(piece,), actual_piece_count=1), key

    monkeypatch.setattr(puzzle_router, "_resolve_layout", isolated_fragment)
    response = puzzle_harness["client"].post(
        "/api/convert/generate-puzzle", json=_generate_puzzle_body(session_id),
    )

    assert response.status_code == 422, response.text
    assert "no printable pieces" in response.json()["detail"]
    puzzle_harness["pool"].submit.assert_not_awaited()


@pytest.mark.parametrize("dtype", [np.int8, np.int16, np.int32, np.int64])
@pytest.mark.parametrize("target_size", [(3, 2), (8, 7)])
def test_recipe_resampling_keeps_integer_values_on_the_rgb_sampling_grid(dtype, target_size) -> None:
    """Recipe channels must follow RGB pixels without interpolation or truncation."""
    pixels = np.arange(15, dtype=np.uint8).reshape(3, 5)
    offset = 2**40 if dtype == np.int64 else 0
    recipes = pixels[..., None].astype(dtype) * 3 + np.arange(7, dtype=dtype) + offset
    rgb_reference = np.asarray(Image.fromarray(pixels).resize(target_size, Image.Resampling.NEAREST))

    result = puzzle_router._resize_piece_array_nearest(recipes, target_size)

    assert result.dtype == recipes.dtype
    assert np.array_equal(result, rgb_reference[..., None].astype(dtype) * 3 + np.arange(7, dtype=dtype) + offset)


def test_layout_overlay_updates_when_the_backing_covers_a_color_gap(puzzle_harness, tmp_path) -> None:
    store = puzzle_harness["store"]
    session_id = _seed_puzzle_preview_session(store)
    cache = store.get(session_id)["preview_cache"]
    color = cache["mask_solid"]
    color[20:38, 18:36] = False  # A through-hole in the design.
    color[20:38, 74:92] = False  # An unpainted patch over the backing.
    color[58:] = False
    body = _layout_preview_body(session_id)
    body["params"].update(rows=1, cols=1, labels_enabled=False)

    def preview_alpha() -> np.ndarray:
        response = puzzle_harness["client"].post("/api/convert/puzzle-layout-preview", json=body)
        assert response.status_code == 200, response.text
        file_id = response.json()["overlay_url"].rsplit("/", 1)[-1]
        path, _ = puzzle_harness["registry"].resolve(file_id)
        with Image.open(path) as overlay:
            return np.asarray(overlay.getchannel("A"))

    # Older sessions have only a color mask, so both patches have cut lines.
    legacy = preview_alpha()
    assert legacy[17:41, 15:39].any()
    assert legacy[17:41, 71:95].any()
    assert not legacy[-1].any()

    cache["backing_mask"] = color.copy()
    np.testing.assert_array_equal(preview_alpha(), legacy)
    backing = np.ones_like(color)
    backing[20:38, 18:36] = False
    cache["backing_mask"] = backing
    cache_ref = externalize_preview_cache(session_id, store, cache, root_dir=tmp_path)
    store.put(session_id, "preview_cache", cache_ref)
    current = preview_alpha()

    assert current[17:41, 15:39].any(), "the real hole needs a cut line"
    assert not current[17:41, 71:95].any(), "the color gap has continuous backing"
    assert current[-1, 45:65].any(), "the overlay must reach the unpainted edge of the backing"


def _seed_backed_puzzle(
    store: SessionStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> tuple[str, int, str]:
    """Prepare printable source materials and a preview with separately defined optical and backing layers."""
    from config import LUTMetadata, PaletteEntry
    from utils.lut_manager import LUTManager

    colors = {"White": (255, 255, 255), "Red": (255, 0, 0)}
    if case == "cloisonne":
        colors["Wire"] = (218, 165, 32)
    palette = list(colors)
    uses_material_archive = case in {"fixed_material", "dynamic_material"}
    layers = 6 if uses_material_archive or case == "five_color" else 5
    color_mode = "5-Color Extended" if case == "five_color" else "4-Color (RYBW)"
    if not uses_material_archive:
        session_id = _seed_puzzle_generate_session(store, tmp_path)
        lut_path = tmp_path / "colors.npz"
        rgb = np.array([colors["White"], colors["Red"]], dtype=np.uint8)
        LUTManager.save_npz_with_metadata(
            str(lut_path), rgb, np.array([[0] * layers, [1] * layers], dtype=np.int32),
            LUTMetadata(
                color_mode=color_mode, max_color_layers=layers,
                palette=[PaletteEntry(color=name, material="PLA") for name in palette],
            ),
        )
        store.put(session_id, "lut_path", str(lut_path))
    else:
        session_id = _seed_dynamic_puzzle_generate_session(store, tmp_path)
        store.put(session_id, "selected_materials", palette)
        store.put(session_id, "material_dynamic_layer_count_enabled", case == "dynamic_material")
        for module in ("core.material_lut_provider", "core.material_lut_synthesis"):
            monkeypatch.setattr(f"{module}.MATERIALS_DIR", str(tmp_path))
        fixture_materials = Path(__file__).parent / "fixtures" / "dynamic_material_materials"
        for name in palette:
            material_dir = tmp_path / name
            material_dir.mkdir()
            (material_dir / "material.json").write_text(
                json.dumps({"material_name": name, "material_type": "PLA"}), encoding="utf-8",
            )
            stage = fixture_materials / name.lower() / "stage_A_parameters.json"
            (material_dir / stage.name).write_bytes(stage.read_bytes())

    cache = store.get(session_id)["preview_cache"]
    if case == "lut_inherited_fine_layers":
        cache.update(color_layers=layers, layer_height_mm=0.04)
    cache["slot_names"] = palette
    cache["preview_colors"] = {name: [*value, 255] for name, value in colors.items()}
    color = cache["mask_solid"]
    color[:, 37:] = False  # The entire right-hand piece has backing alone.
    color[15:29, 9:23] = False
    color[48:62, 9:23] = False
    backing = np.ones_like(color)
    backing[15:29, 9:23] = False
    cache["backing_mask"] = backing
    cache["matched_rgb"][:] = colors["Red"]
    cache["preview_rgba"][..., :3] = colors["Red"]
    cache["preview_rgba"][..., 3] = color.astype(np.uint8) * 255
    if uses_material_archive:
        cache["quantized_image"][:] = cache["matched_rgb"]
        cache["material_matrix"][color] = 1
        cache["material_matrix"][~color] = -1
    Image.fromarray(cache["preview_rgba"]).save(store.get(session_id)["image_path"])
    cache_ref = externalize_preview_cache(session_id, store, cache, root_dir=tmp_path)
    store.put(session_id, "preview_cache", cache_ref)
    return session_id, layers, color_mode


@pytest.mark.parametrize("case", [
    "lut", "five_color", "cloisonne", "fixed_material", "dynamic_material", "color_relief", "heightmap_relief",
    "lut_fine_layers", "lut_inherited_fine_layers",
])
def test_puzzle_3mf_preserves_backing_only_regions_and_through_holes(
    puzzle_harness, tmp_path, monkeypatch, case: str,
) -> None:
    """Probe the physical layers of both pieces after route, worker and assembly."""
    from api.routers.converter.export_materials import require_material_selection
    from api.workers.converter_workers import _batch_extract_slots_from_3mf

    for field in (
        "config.TEMP_DIR", "core.pipeline.s04_debug_preview.OUTPUT_DIR", "core.pipeline.s09_export_3mf.MODELS_DIR",
        "core.pipeline.s10_color_recipe.OUTPUT_DIR", "core.pipeline.s11_glb_preview.OUTPUT_DIR",
    ):
        monkeypatch.setattr(field, str(tmp_path))
    monkeypatch.setattr("utils.stats.Stats._file", str(tmp_path / "stats.txt"))
    monkeypatch.setattr(puzzle_router, "_batch_extract_slots_from_3mf", _batch_extract_slots_from_3mf)
    monkeypatch.setattr(puzzle_router, "require_material_selection", require_material_selection)
    session_id, layers, color_mode = _seed_backed_puzzle(puzzle_harness["store"], tmp_path, monkeypatch, case)
    puzzle_harness["pool"].submit = AsyncMock(side_effect=lambda worker, *args: worker(*args))
    body = _generate_puzzle_body(session_id)
    body["params"].update(rows=1, cols=2, target_height_mm=6.4)
    body["params"]["params"].update(
        target_width_mm=9.6, color_mode=color_mode, enable_cloisonne=case == "cloisonne",
        enable_wipe_tower_auto_placement=False,
    )
    if case == "lut_fine_layers":
        body["params"]["params"].update(color_layers=layers, layer_height_mm=0.04)
    if case == "color_relief":
        body["params"]["params"].update(
            enable_relief=True, structure_mode="Single-sided", height_mode="color", color_height_map={"#ff0000": 2.0},
        )
    elif case == "heightmap_relief":
        heights = np.zeros((80, 120), dtype=np.uint8)
        heights[:, :37] = 255
        puzzle_harness["store"].put(session_id, "heightmap_grayscale", heights)
        body["params"]["params"].update(
            enable_relief=True, structure_mode="Single-sided", height_mode="heightmap",
            spacer_thick=0.8, heightmap_max_height=2.0,
        )
    response = puzzle_harness["client"].post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 200, response.text
    file_id = response.json()["download_url"].rsplit("/", 1)[-1]
    path, _ = puzzle_harness["registry"].resolve(file_id)
    triangles = trimesh.load_scene(path, process=False).to_geometry().triangles
    horizontal = triangles[np.ptp(triangles[:, :, 2], axis=1) < 1e-6]
    faces = shapely.polygons(horizontal[:, :, :2])

    def surface_heights(x: float, y: float) -> np.ndarray:
        return np.unique(horizontal[shapely.intersects_xy(faces, x, y), 0, 2].round(4))

    # The same 120 x 80 preview is exported at 0.08 mm per source pixel.
    assert surface_heights(1.31, 4.65).size == 0, "the design hole must remain open"
    layer_height = 0.04 if case in {"lut_fine_layers", "lut_inherited_fine_layers"} else 0.08
    optical_depth = layer_height * layers
    if case in {"color_relief", "heightmap_relief"}:
        painted_limits = [0, 2.0 - optical_depth, 2.0]
        unpainted_limits = [0, 1.2 if case == "color_relief" else 2.0]
        bare_piece_limits = [0, 1.2 if case == "color_relief" else 0.8]
        with ZipFile(path) as model:
            assembly = ElementTree.fromstring(model.read("3D/3dmodel.model"))
            settings = ElementTree.fromstring(model.read("Metadata/model_settings.config"))
        labels = {obj.attrib["id"]: obj.attrib["name"] for obj in assembly.findall("{*}resources/{*}object")}
        piece_slots = {
            labels[piece.attrib["id"]]: {int(slot.attrib["value"]) for slot in piece.findall("part/metadata[@key='extruder']")}
            for piece in settings.findall("object")
        }
        assert piece_slots == {"A1": {1, 2}, "A2": {1}}, "only the painted piece may use red filament"
    elif case in {"five_color", "cloisonne"}:
        unpainted_limits = bare_piece_limits = [0, 1.2]
        painted_limits = [0, 1.2, 1.2 + optical_depth]
    else:
        unpainted_limits = bare_piece_limits = [optical_depth, optical_depth + 1.2]
        painted_limits = [0, *unpainted_limits, 2 * optical_depth + 1.2]
    assert surface_heights(1.31, 2.03) == pytest.approx(unpainted_limits), "unpainted patch"
    assert surface_heights(7.71, 3.23) == pytest.approx(bare_piece_limits), "backing-only piece"
    assert surface_heights(2.51, 4.65) == pytest.approx(painted_limits), "red optical layers over white backing"
    assert response.json()["piece_count"] == 2


def test_puzzle_worker_export_does_not_depend_on_glb_preview(
    puzzle_harness, tmp_path, monkeypatch,
) -> None:
    """A preview failure after writing a piece must not fail a puzzle download."""
    from api.routers.converter.export_materials import require_material_selection
    from api.workers.converter_workers import _batch_extract_slots_from_3mf
    from core.pipeline import s11_glb_preview

    def fail_glb(_ctx):
        raise RuntimeError("simulated failure after writing the piece 3MF")

    monkeypatch.setattr(s11_glb_preview, "run", fail_glb)
    monkeypatch.setattr(puzzle_router, "_batch_extract_slots_from_3mf", _batch_extract_slots_from_3mf)
    monkeypatch.setattr(puzzle_router, "require_material_selection", require_material_selection)
    for field in ("s04_debug_preview.OUTPUT_DIR", "s09_export_3mf.MODELS_DIR", "s10_color_recipe.OUTPUT_DIR"):
        monkeypatch.setattr(f"core.pipeline.{field}", str(tmp_path))
    session_id, _, color_mode = _seed_backed_puzzle(puzzle_harness["store"], tmp_path, monkeypatch, "lut")
    pool = puzzle_harness["pool"]
    pool.submit = AsyncMock(side_effect=lambda worker, *args: worker(*args))
    body = _generate_puzzle_body(session_id)
    body["params"].update(rows=1, cols=2, target_height_mm=6.4)
    body["params"]["params"].update(target_width_mm=9.6, color_mode=color_mode)

    response = puzzle_harness["client"].post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["piece_count"] == 2
    puzzle_harness["store"].close(session_id)
    download_id = response.json()["download_url"].rsplit("/", 1)[-1]
    final_path, _ = puzzle_harness["registry"].resolve(download_id)
    with ZipFile(final_path) as archive:
        assert archive.testzip() is None
        build = ElementTree.fromstring(archive.read("3D/3dmodel.model"))
        assert len(build.findall("./{*}build/{*}item")) == 2
    assert list(tmp_path.glob("puzzle_*")) == [Path(final_path)]


@pytest.mark.parametrize("coating_profile", [None, "Bambu PLA Matte @BBL P1S 0.4 nozzle"])
def test_puzzle_merge_keeps_coating_material_and_native_layer_ranges(
    puzzle_harness, tmp_path, monkeypatch, coating_profile,
) -> None:
    from api.routers.converter.export_materials import require_material_selection
    from api.workers.converter_workers import _batch_extract_slots_from_3mf
    from utils.fatcat_metadata import read_source_metadata, select_metadata_target

    monkeypatch.setattr(puzzle_router, "_batch_extract_slots_from_3mf", _batch_extract_slots_from_3mf)
    monkeypatch.setattr(puzzle_router, "require_material_selection", require_material_selection)
    session_id, _, color_mode = _seed_backed_puzzle(puzzle_harness["store"], tmp_path, monkeypatch, "lut")
    puzzle_harness["pool"].submit = AsyncMock(side_effect=lambda worker, *args: worker(*args))
    body = _generate_puzzle_body(session_id)
    body["params"].update(rows=1, cols=2, target_height_mm=6.4)
    params = body["params"]["params"]
    params.update(
        target_width_mm=9.6, color_mode=color_mode, printer_id="bambu-p1s", nozzle_size="0.4",
        enable_coating=True, coating_height_mm=0.04, layer_height_mm=0.08, structure_mode="Double-sided",
        enable_base_layer_height_modifier=False, enable_wipe_tower_auto_placement=False,
    )
    if coating_profile is not None:
        params["native_filament_profiles"] = {"Coating": coating_profile}

    response = puzzle_harness["client"].post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 200, response.text
    file_id = response.json()["download_url"].rsplit("/", 1)[-1]
    path, _ = puzzle_harness["registry"].resolve(file_id)
    target = select_metadata_target(
        slicer="BambuStudio", printer_id="bambu-p1s", nozzle_size="0.4",
        device_profile_id=None, build_plate_id=None,
    )
    metadata = read_source_metadata(path, target=target)
    coating_slot = next(slot for slot in metadata["slots"] if slot["slot_name"] == "Coating")
    assert coating_slot["slot_id"] == 2
    assert coating_slot["preview_color"] == "#C8C8C8"
    assert metadata["layout"]["layer_height"] == 0.08
    assert metadata["layout"]["initial_layer_height"] == 0.04
    assert metadata["layout"]["min_layer_height"] == 0.04
    with ZipFile(path) as package:
        project = json.loads(package.read("Metadata/project_settings.config"))
        assert project["filament_type"][2] == "PLA"
        assert project["filament_settings_id"][2] == (
            coating_profile or "Bambu PLA Basic @BBL P1S 0.4 nozzle"
        )
        model = ElementTree.fromstring(package.read("Metadata/model_settings.config"))
        ranges = ElementTree.fromstring(package.read("Metadata/layer_config_ranges.xml"))
        root_model = ElementTree.fromstring(package.read("3D/3dmodel.model"))
        root_objects = {obj.get("id"): obj for obj in root_model.findall("./{*}resources/{*}object")}
        for item in root_model.findall("./{*}build/{*}item"):
            dz = float((item.get("transform") or "0").split()[-1])
            components = root_objects[item.get("objectid")].findall("./{*}components/{*}component")
            component_path = components[0].get("{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path")
            geometry = ElementTree.fromstring(package.read(component_path.lstrip("/")))
            z_coordinates = [float(vertex.get("z")) for vertex in geometry.findall(".//{*}vertex")]
            assert dz == pytest.approx(0.04)
            assert dz + min(z_coordinates) == pytest.approx(0.0, abs=1e-7)
    assert len(model.findall("./object/part/metadata[@key='extruder'][@value='3']")) == 2
    assert len(ranges.findall("./object")) == 2
    for obj in ranges.findall("./object"):
        assert any(float(option.text) == 0.04 for option in obj.findall("./range/option[@opt_key='layer_height']"))


class TestPuzzleLayoutPreviewCanary:
    """Successful puzzle-layout-preview requests emit the renamed done canary."""

    def test_stale_artifact_cache_returns_repreview_error(
        self,
        puzzle_harness,
        tmp_path,
    ) -> None:
        store: SessionStore = puzzle_harness["store"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_puzzle_preview_session(store)
        stale_path = _delete_externalized_preview_cache_field(
            store,
            session_id,
            tmp_path,
            "matched_rgb",
        )

        response = client.post(
            "/api/convert/puzzle-layout-preview",
            json=_layout_preview_body(session_id),
        )

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "Re-run preview" in detail
        assert str(stale_path) not in detail

    def test_puzzle_layout_preview_emits_renamed_contract_canary(
        self,
        puzzle_harness,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = puzzle_harness["store"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_puzzle_preview_session(store)

        target_logger = _capture_puzzle_logger(caplog)
        try:
            response = client.post(
                "/api/convert/puzzle-layout-preview",
                json=_layout_preview_body(session_id),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["overlay_url"].startswith("/api/files/")

        old_event = "converter_puzzle_layout" + "_preview"
        old_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == old_event
        ]
        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_puzzle_layout_preview_done"
        ]
        assert old_records == []
        assert len(records) == 1

        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.piece_count == body["piece_count"]
        assert record.grid_cols == body["grid_cols"]
        assert record.grid_rows == body["grid_rows"]
        assert record.derived_piece_width_mm == body["derived_piece_width_mm"]
        assert record.derived_piece_height_mm == body["derived_piece_height_mm"]
        assert record.warning_count == len(body["warnings"])
        assert record.labels_enabled is True


class TestGeneratePuzzleCanary:
    """Successful generate-puzzle requests emit the full structured contract."""

    def test_stale_artifact_cache_returns_repreview_error_before_worker(
        self,
        puzzle_harness,
        tmp_path,
    ) -> None:
        store: SessionStore = puzzle_harness["store"]
        pool: MagicMock = puzzle_harness["pool"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_puzzle_generate_session(store, tmp_path)
        stale_path = _delete_externalized_preview_cache_field(
            store,
            session_id,
            tmp_path,
            "preview_rgba",
        )

        response = client.post(
            "/api/convert/generate-puzzle",
            json=_generate_puzzle_body(session_id),
        )

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "Re-run preview" in detail
        assert str(stale_path) not in detail
        pool.submit.assert_not_called()

    def test_generate_puzzle_emits_extended_contract_canary(
        self,
        puzzle_harness,
        tmp_path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = puzzle_harness["store"]
        pool: MagicMock = puzzle_harness["pool"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_puzzle_generate_session(store, tmp_path)
        piece_index = 0

        async def _submit_stub(*_args, **_kwargs) -> dict[str, object]:
            nonlocal piece_index
            piece_index += 1
            path = tmp_path / f"piece-{piece_index}.3mf"
            path.write_bytes(b"piece-3mf")
            return {
                "threemf_path": str(path),
                "glb_path": None,
                "status_msg": "ok",
                "x_mirrored": False,
                "mirror_span_mm": 1.0,
            }

        def _assemble_stub(*, output_path: str, **_kwargs) -> str:
            with open(output_path, "wb") as handle:
                handle.write(b"combined-3mf")
            return output_path

        pool.submit = AsyncMock(side_effect=_submit_stub)
        target_logger = _capture_puzzle_logger(caplog)
        try:
            with patch(
                "api.routers.converter.puzzle.assemble_puzzle_3mf",
                side_effect=_assemble_stub,
            ):
                response = client.post(
                    "/api/convert/generate-puzzle",
                    json=_generate_puzzle_body(session_id),
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["piece_count"] == 4
        download_id = body["download_url"].rsplit("/", 1)[-1]

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_puzzle_generate_done"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.piece_count == body["piece_count"]
        assert record.grid_cols == body["grid_cols"]
        assert record.grid_rows == body["grid_rows"]
        assert record.warning_count == len(body["warnings"])
        assert record.skipped_transparent_count == 0
        assert record.download_id == download_id
        started_records = [
            record for record in caplog.records
            if getattr(record, "event", None) == "converter_puzzle_generate_init"
        ]
        assert len(started_records) == 1
        assert started_records[0].piece_count == body["piece_count"]
        assert started_records[0].max_workers == pool.max_workers
        assert len([
            record for record in caplog.records
            if record.name == target_logger.name and record.levelno == logging.INFO
        ]) == 2


@pytest.mark.parametrize("source", ["lut", "material_archive", "dynamic_material"])
def test_generate_puzzle_runs_bounded_parallel_pieces_in_layout_order(
    puzzle_harness, tmp_path, source: str,
) -> None:
    """Independent pieces must overlap without exceeding the worker capacity."""

    store = puzzle_harness["store"]
    pool = puzzle_harness["pool"]
    if source in {"dynamic_material", "material_archive"}:
        session_id = _seed_dynamic_puzzle_generate_session(store, tmp_path)
        if source == "material_archive":
            store.put(session_id, "material_dynamic_layer_count_enabled", False)
    else:
        session_id = _seed_puzzle_generate_session(store, tmp_path)

    active = 0
    peak_active = 0
    completed_labels: list[str] = []
    assembled_labels: list[str] = []
    pair_started: asyncio.Event | None = None

    async def submit_piece(_fn, image_path, _lut_path, params):
        nonlocal active, peak_active, pair_started
        assert params['backing_infill_density_percent'] == 20
        assert params['enable_base_layer_height_modifier'] is False
        label = Path(image_path).stem.split("_")[1]
        active += 1
        peak_active = max(peak_active, active)
        if pair_started is None:
            pair_started = asyncio.Event()
        current_pair = pair_started
        if active == 2:
            pair_started = None
            current_pair.set()
        try:
            await asyncio.wait_for(current_pair.wait(), timeout=0.5)
            # Complete each second piece first to exercise output association.
            if label.endswith("1"):
                await asyncio.sleep(0.01)
            path = tmp_path / f"piece-{label}.3mf"
            path.write_bytes(b"piece-3mf")
            completed_labels.append(label)
            return {
                "threemf_path": str(path),
                "glb_path": None,
                "status_msg": "ok",
                "x_mirrored": False,
                "mirror_span_mm": float(params["target_width_mm"]),
            }
        finally:
            active -= 1

    def assemble_pieces(*, piece_sources, output_path, **_kwargs):
        for piece in piece_sources:
            assert Path(piece.threemf_path).stem == f"piece-{piece.label}"
            assembled_labels.append(piece.label)
        Path(output_path).write_bytes(b"combined-3mf")
        return output_path

    pool.submit = AsyncMock(side_effect=submit_piece)
    body = _generate_puzzle_body(session_id)
    body["params"]["params"]["modeling_mode"] = "vector"
    if source != "lut":
        store.get(session_id)["preview_cache"]["modeling_mode"] = "vector"
    body['params']['params']['backing_infill_density_percent'] = 20
    body['params']['params']['enable_base_layer_height_modifier'] = False
    with patch.object(puzzle_router, "assemble_puzzle_3mf", side_effect=assemble_pieces):
        response = puzzle_harness["client"].post(
            "/api/convert/generate-puzzle", json=body,
        )

    assert response.status_code == 200, response.text
    assert response.json()["piece_count"] == 4
    assert peak_active == pool.max_workers
    assert active == 0
    assert completed_labels == ["A2", "A1", "B2", "B1"]
    assert assembled_labels == ["A1", "A2", "B1", "B2"]


def test_generate_puzzle_drains_failed_batch_and_removes_piece_outputs(
    puzzle_harness, tmp_path,
) -> None:
    """A typed failure must not strand sibling outputs or launch later batches."""

    store = puzzle_harness["store"]
    pool = puzzle_harness["pool"]
    session_id = _seed_puzzle_generate_session(store, tmp_path)
    outputs: list[Path] = []

    async def submit_piece(_fn, image_path, _lut_path, params):
        path = Path(params["export_only_3mf_path"])
        if Path(image_path).stem.split("_")[1] == "A1":
            path.write_bytes(b"partial output from the failed worker")
            outputs.append(path)
            raise DynamicMaterialSolverError("test solver failure")
        await asyncio.sleep(0.01)
        path.write_bytes(b"sibling output")
        outputs.append(path)
        return {
            "threemf_path": str(path),
            "x_mirrored": False,
            "mirror_span_mm": 1.0,
        }

    pool.submit = AsyncMock(side_effect=submit_piece)
    with patch.object(puzzle_router, "assemble_puzzle_3mf") as assemble:
        response = puzzle_harness["client"].post(
            "/api/convert/generate-puzzle",
            json=_generate_puzzle_body(session_id),
        )

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "dynamic_material_solver_unavailable"
    assert pool.submit.await_count == 2
    assemble.assert_not_called()
    assert len(outputs) == 2
    assert all(not path.exists() for path in outputs)


def _crash_puzzle_worker_at_voxel_stage(image_path: str, lut_path: str, params: dict) -> dict:
    from api.workers.converter_workers import _submit_puzzle_worker
    from core.pipeline import s06_voxel_building

    s06_voxel_building.run = lambda _ctx: os._exit(23)
    return _submit_puzzle_worker(image_path, lut_path, params)


def test_broken_puzzle_worker_pool_reports_unavailable_with_worker_details(
    puzzle_harness, tmp_path, monkeypatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A crashed child reports the active piece and actual pipeline stage."""
    session_id, _, _ = _seed_backed_puzzle(puzzle_harness["store"], tmp_path, monkeypatch, "lut")
    pool = puzzle_harness["pool"]
    real_pool = WorkerPoolManager(max_workers=1)
    pool.max_workers = real_pool.max_workers
    pool.submit = AsyncMock(side_effect=real_pool.submit)
    monkeypatch.setattr(puzzle_router, "_submit_puzzle_worker", _crash_puzzle_worker_at_voxel_stage)
    body = _generate_puzzle_body(session_id)
    body["params"].update(rows=1, cols=2, target_height_mm=6.4)
    body["params"]["params"].update(target_width_mm=9.6)

    target_logger = _capture_puzzle_logger(caplog)
    pool_logger = logging.getLogger("lumina.api.worker_pool")
    pool_logger.addHandler(caplog.handler)
    real_pool.start()
    try:
        response = puzzle_harness["client"].post("/api/convert/generate-puzzle", json=body)
    finally:
        real_pool.shutdown(wait=True)
        pool_logger.removeHandler(caplog.handler)
        target_logger.removeHandler(caplog.handler)

    assert response.status_code == 503, response.text
    assert pool.submit.await_count == pool.max_workers
    failed = [rec for rec in caplog.records if getattr(rec, "event", "") == "converter_puzzle_generate_failed"]
    assert len(failed) == 1
    assert failed[0].piece_label == "A1"
    assert failed[0].stage == "generate_piece"
    assert failed[0].error_type == "BrokenProcessPool"
    assert failed[0].error_message
    exited, = [rec for rec in caplog.records if getattr(rec, "event", "") == "worker_process_failed"]
    assert exited.worker_piece_label == "A1"
    assert exited.worker_phase == "S06"
    assert exited.worker_exit_code == 23


def test_puzzle_reports_unsupported_coating_as_input_error(puzzle_harness, tmp_path) -> None:
    session_id = _seed_puzzle_generate_session(puzzle_harness["store"], tmp_path)
    message = "The selected nozzle cannot slice this coating thickness."
    puzzle_harness["pool"].submit = AsyncMock(side_effect=CoatingLayerHeightError(message))

    response = puzzle_harness["client"].post(
        "/api/convert/generate-puzzle", json=_generate_puzzle_body(session_id),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == message


@pytest.mark.asyncio
async def test_cancelled_puzzle_drains_active_batch_without_starting_more_pieces(
    puzzle_harness, tmp_path,
) -> None:
    """Already running processes keep output ownership after request cancellation."""

    store = puzzle_harness["store"]
    pool = puzzle_harness["pool"]
    session_id = _seed_puzzle_generate_session(store, tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()
    active_count = 0
    outputs: list[Path] = []

    async def submit_piece(_fn, _image_path, _lut_path, params):
        nonlocal active_count
        active_count += 1
        if active_count == pool.max_workers:
            started.set()
        await release.wait()
        path = Path(params["export_only_3mf_path"])
        path.write_bytes(b"piece output")
        outputs.append(path)
        active_count -= 1
        return {"threemf_path": str(path), "glb_path": None}

    pool.submit = AsyncMock(side_effect=submit_piece)
    task = asyncio.create_task(puzzle_router.generate_puzzle(
        puzzle_router._PuzzleGenerateBody.model_validate(_generate_puzzle_body(session_id)),
        store=store,
        registry=puzzle_harness["registry"],
        pool=pool,
    ))
    try:
        await asyncio.wait_for(started.wait(), timeout=2.0)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        if not task.done():
            with pytest.raises(asyncio.CancelledError):
                await task

    assert task.cancelled()
    assert pool.submit.await_count == 2
    assert active_count == 0
    assert len(outputs) == 2
    assert all(not path.exists() for path in outputs)


@pytest.mark.asyncio
async def test_puzzle_inputs_survive_idle_cleanup_and_source_close(
    puzzle_harness, tmp_path, monkeypatch,
) -> None:
    from api import session_store as session_store_module
    from api.app import _run_cleanup_pass
    from api.routers.session import close_session, heartbeat
    from api.schemas.session import SessionRequest

    store = puzzle_harness["store"]
    registry = puzzle_harness["registry"]
    pool = puzzle_harness["pool"]
    session_id = _seed_puzzle_generate_session(store, tmp_path)
    original_lut = Path(store.get(session_id)["lut_path"])
    lut_bytes = original_lut.read_bytes()
    idle_session = store.create()
    started = asyncio.Event()
    release = asyncio.Event()
    inputs = []

    async def submit_piece(_worker, image_path, lut_path, params):
        inputs.append((Path(image_path), Path(lut_path)))
        if len(inputs) == pool.max_workers:
            started.set()
        await release.wait()
        assert Path(image_path).is_file()
        assert Path(lut_path).read_bytes() == lut_bytes
        piece = Path(params["export_only_3mf_path"])
        piece.write_bytes(b"piece 3mf")
        return {"threemf_path": str(piece), "x_mirrored": False, "mirror_span_mm": 1.0}

    def assemble_pieces(*, output_path, **kwargs):
        Path(output_path).write_bytes(b"assembled 3mf")

    pool.submit = AsyncMock(side_effect=submit_piece)
    monkeypatch.setattr(puzzle_router, "assemble_puzzle_3mf", assemble_pieces)
    body = _generate_puzzle_body(session_id)
    body["params"].update(rows=1, cols=2)
    session_request = SessionRequest(session_id=session_id)
    task = asyncio.create_task(puzzle_router.generate_puzzle(
        puzzle_router._PuzzleGenerateBody.model_validate(body),
        store=store,
        registry=registry,
        pool=pool,
    ))
    try:
        await asyncio.wait_for(started.wait(), timeout=2.0)
        origin = time.time()
        elapsed = 1740
        with monkeypatch.context() as clock:
            clock.setattr(session_store_module, "time", SimpleNamespace(time=lambda: origin + elapsed))
            assert heartbeat(session_request, store=store).status == "ok"
            elapsed = 1820
            expired, _, _ = _run_cleanup_pass(store, registry)
            assert expired == [idle_session]
        assert all(image.is_file() for image, _ in inputs)
        close_session(session_request, store=store, registry=registry)
        assert not original_lut.exists()
        assert all(lut.is_file() for _, lut in inputs)
    except BaseException:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        raise
    release.set()
    response = await task
    assert all(not file.exists() for pair in inputs for file in pair)
    download, _ = registry.resolve(response.download_url.rsplit("/", 1)[-1])
    assert Path(download).read_bytes() == b"assembled 3mf"


class TestMaterialPuzzlePreviewReuse:
    """Fixed and dynamic puzzle pieces must load confirmed recipes through S02."""

    @pytest.mark.parametrize("externalized", [False, True])
    @pytest.mark.parametrize("session_layers,confirmed_layers,layer_height,explicit", [
        (6, 6, 0.08, False),
        (5, 8, 0.08, False),
        (5, 8, 0.08, True),
        (None, 5, 0.08, False),
        (5, 5, 0.12, False),
        (5, 5, 0.12, True),
    ])
    def test_fixed_material_pieces_keep_preview_recipes_without_resolving(
        self, puzzle_harness, tmp_path, monkeypatch, externalized: bool,
        session_layers: int | None, confirmed_layers: int, layer_height: float, explicit: bool,
    ) -> None:
        """Splitting a confirmed preview must not solve new recipes per piece."""
        from core.pipeline import p03_core_processing, s02_image_processing

        store = puzzle_harness["store"]
        pool = puzzle_harness["pool"]
        session_id = _seed_dynamic_puzzle_generate_session(store, tmp_path)
        store.put(session_id, "material_dynamic_layer_count_enabled", False)
        store.put(session_id, "material_layer_count", session_layers)
        store.put(session_id, "color_layers", session_layers)
        store.put(session_id, "layer_height_mm", 0.08)
        expected_recipe = [2, 1, 2, 1, 0, 0, 0, 0][:confirmed_layers]
        cache = dict(store.get(session_id)["preview_cache"])
        cache["material_matrix"] = np.broadcast_to(
            np.asarray(expected_recipe, dtype=np.int16),
            (*cache["mask_solid"].shape, confirmed_layers),
        ).copy()
        cache["color_layers"] = len(expected_recipe)
        cache["layer_height_mm"] = layer_height
        cache["material_dynamic_layer_info"] = {"enabled": False}
        store.put(session_id, "preview_cache", cache)
        if externalized:
            store.put(session_id, "preview_cache", externalize_preview_cache(
                session_id, store, cache, root_dir=tmp_path,
            ))
        solver_calls = []

        def unexpected_resolve(ctx):
            solver_calls.append(ctx)
            raise AssertionError("a puzzle piece must not rerun the material solver")

        monkeypatch.setattr(p03_core_processing, "_run_material_archive_branch", unexpected_resolve)
        checked_pieces = []

        async def submit_piece(_fn, image_path, _lut_path, params):
            result = s02_image_processing.run(dict(params))
            mask = result["mask_solid"]
            matrix = result["material_matrix"]
            assert np.any(mask)
            assert params["material_layer_count"] == len(expected_recipe)
            assert params["material_layer_height_mm"] == layer_height
            assert matrix.shape == (*mask.shape, len(expected_recipe))
            assert np.all(matrix[mask] == expected_recipe)
            assert np.all(matrix[~mask] == -1)
            checked_pieces.append(Path(image_path).stem.split("_")[1])
            output = tmp_path / f"piece-{len(checked_pieces)}.3mf"
            output.write_bytes(b"piece-3mf")
            return {"threemf_path": str(output), "glb_path": None,
                    "status_msg": "ok", "x_mirrored": False, "mirror_span_mm": 1.0}

        def assemble(*, output_path: str, **_kwargs):
            Path(output_path).write_bytes(b"combined-3mf")
            return output_path

        pool.submit = AsyncMock(side_effect=submit_piece)
        monkeypatch.setattr(puzzle_router, "assemble_puzzle_3mf", assemble)
        body = _generate_puzzle_body(session_id)
        body["params"]["target_height_mm"] = 8.0
        body["params"]["params"]["target_width_mm"] = 12.0
        if explicit:
            body["params"]["params"].update(color_layers=confirmed_layers, layer_height_mm=layer_height)
        response = puzzle_harness["client"].post("/api/convert/generate-puzzle", json=body)

        assert not solver_calls, "puzzle pieces solved new recipes instead of reusing the preview"
        assert response.status_code == 200, response.text
        assert checked_pieces == ["A1", "A2", "B1", "B2"]

    def test_dynamic_puzzle_accepts_externalized_int32_authority_assets(
        self,
        puzzle_harness,
        tmp_path,
    ) -> None:
        """Artifact persistence must not compact the dynamic authority matrix."""

        store: SessionStore = puzzle_harness["store"]
        client: TestClient = puzzle_harness["client"]
        pool: MagicMock = puzzle_harness["pool"]
        session_id = _seed_dynamic_puzzle_generate_session(store, tmp_path)
        session_data = store.get(session_id)
        assert session_data is not None
        cache_ref = externalize_preview_cache(
            session_id,
            store,
            session_data["preview_cache"],
            root_dir=tmp_path,
        )
        store.put(session_id, "preview_cache", cache_ref)
        assert np.load(
            cache_ref["fields"]["material_matrix"]["path"],
            allow_pickle=False,
        ).dtype == np.int32

        piece_index = 0

        async def _submit_stub(*args, **_kwargs) -> dict[str, object]:
            nonlocal piece_index
            piece_index += 1
            path = tmp_path / f"externalized-dynamic-piece-{piece_index}.3mf"
            path.write_bytes(b"piece-3mf")
            return {
                "threemf_path": str(path),
                "glb_path": None,
                "status_msg": "ok",
                "x_mirrored": False,
                "mirror_span_mm": 1.0,
            }

        def _assemble_stub(*, output_path: str, **_kwargs) -> str:
            Path(output_path).write_bytes(b"combined-3mf")
            return output_path

        pool.submit = AsyncMock(side_effect=_submit_stub)
        with patch(
            "api.routers.converter.puzzle.assemble_puzzle_3mf",
            side_effect=_assemble_stub,
        ):
            response = client.post(
                "/api/convert/generate-puzzle",
                json=_generate_puzzle_body(session_id),
            )

        assert response.status_code == 200, response.text
        assert pool.submit.await_count == 4

    def test_dynamic_puzzle_crops_and_resamples_authority_assets(
        self,
        puzzle_harness,
        tmp_path,
    ) -> None:
        store: SessionStore = puzzle_harness["store"]
        pool: MagicMock = puzzle_harness["pool"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_dynamic_puzzle_generate_session(store, tmp_path)
        captured_inputs: list[tuple[dict[str, object], dict[str, np.ndarray]]] = []

        async def _submit_stub(_func, _source, _lut, params) -> dict[str, object]:
            arrays = {
                key: np.load(params[f"{key}_path"], allow_pickle=False)
                for key in ("matched_rgb", "mask_solid", "quantized_image", "material_matrix")
            }
            captured_inputs.append((params, arrays))
            path = Path(params["export_only_3mf_path"])
            path.write_bytes(b"piece-3mf")
            return {
                "threemf_path": str(path),
                "glb_path": None,
                "status_msg": "ok",
                "x_mirrored": False,
                "mirror_span_mm": 1.0,
            }

        def _assemble_stub(*, output_path: str, **_kwargs) -> str:
            Path(output_path).write_bytes(b"combined-3mf")
            return output_path

        pool.submit = AsyncMock(side_effect=_submit_stub)
        with patch(
            "api.routers.converter.puzzle.assemble_puzzle_3mf",
            side_effect=_assemble_stub,
        ):
            response = client.post(
                "/api/convert/generate-puzzle",
                json=_generate_puzzle_body(session_id),
            )

        assert response.status_code == 200, response.text
        assert len(captured_inputs) == 4
        for params, arrays in captured_inputs:
            assert params["reuse_preview_analysis"] == "required"
            assert params["material_dynamic_layer_count_enabled"] is True
            assert params["material_max_layer_count"] == 6
            matched = arrays["matched_rgb"]
            mask_solid = arrays["mask_solid"]
            quantized = arrays["quantized_image"]
            matrix = arrays["material_matrix"]
            assert matched.dtype == np.uint8
            assert mask_solid.dtype == np.bool_
            assert quantized.dtype == np.uint8
            assert matrix.dtype == np.int32
            assert matched.shape[:2] == mask_solid.shape
            assert quantized.shape == matched.shape
            assert matrix.shape == (*mask_solid.shape, 6)
            assert np.all(matrix[~mask_solid] == -1)

    @pytest.mark.parametrize("dynamic", [False, True])
    @pytest.mark.parametrize("broken_asset", ["missing", "float_matrix", "wrong_depth"])
    def test_material_puzzle_rejects_incomplete_preview_before_scheduling(
        self,
        puzzle_harness,
        tmp_path,
        dynamic: bool,
        broken_asset: str,
    ) -> None:
        store: SessionStore = puzzle_harness["store"]
        pool: MagicMock = puzzle_harness["pool"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_dynamic_puzzle_generate_session(store, tmp_path)
        store.put(session_id, "material_dynamic_layer_count_enabled", dynamic)
        session_data = store.get(session_id)
        assert session_data is not None
        cache = dict(session_data["preview_cache"])
        if broken_asset == "missing":
            cache.pop("material_matrix")
        elif broken_asset == "float_matrix":
            cache["material_matrix"] = cache["material_matrix"].astype(np.float64)
        else:
            cache["material_matrix"] = cache["material_matrix"][..., :-1 if dynamic else 0]
        store.put(session_id, "preview_cache", cache)

        response = client.post(
            "/api/convert/generate-puzzle",
            json=_generate_puzzle_body(session_id),
        )

        assert response.status_code == 409
        assert "Re-run preview" in response.json()["detail"]
        pool.submit.assert_not_called()

    @pytest.mark.parametrize("dynamic", [False, True])
    @pytest.mark.parametrize("changed", [{"quantize_colors": 12}, {"enable_cleanup": False}])
    def test_material_puzzle_rejects_analysis_changes_before_scheduling(
        self, puzzle_harness, tmp_path, dynamic: bool, changed: dict[str, object],
    ) -> None:
        session_id = _seed_dynamic_puzzle_generate_session(puzzle_harness["store"], tmp_path)
        puzzle_harness["store"].put(session_id, "material_dynamic_layer_count_enabled", dynamic)
        puzzle_harness["pool"].submit = AsyncMock(return_value={"threemf_path": None})
        body = _generate_puzzle_body(session_id)
        body["params"]["params"].update(changed)

        response = puzzle_harness["client"].post("/api/convert/generate-puzzle", json=body)

        assert response.status_code == 409, response.text
        assert "preview" in response.json()["detail"].lower()
        puzzle_harness["pool"].submit.assert_not_called()

    @pytest.mark.parametrize("dynamic", [False, True])
    def test_material_puzzle_forwards_manual_virtual_recipe_context(
        self,
        puzzle_harness,
        tmp_path,
        dynamic: bool,
    ) -> None:
        """A copied dynamic matrix must retain its virtual-palette definition."""

        store: SessionStore = puzzle_harness["store"]
        pool: MagicMock = puzzle_harness["pool"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_dynamic_puzzle_generate_session(store, tmp_path)
        store.put(session_id, "material_dynamic_layer_count_enabled", dynamic)
        session_data = store.get(session_id)
        assert session_data is not None
        assert RECIPE_OVERRIDE_APPLIED_MASKS_KEY not in session_data
        cache = dict(session_data["preview_cache"])
        virtual_mask = np.zeros((80, 120), dtype=bool)
        virtual_mask[:40, :60] = True
        cache["material_matrix"][virtual_mask] = [3, 1, 0, 1, 0, 0]
        store.put(session_id, "preview_cache", cache)
        store.put(
            session_id,
            "recipe_overrides",
            [
                {
                    "region_id": "virtual-region",
                    "recipe": [3, 1, 0, 1, 0],
                    "layer_order": "Top2Bottom",
                    "actual_recipe_top_to_bottom": [3, 1, 0, 1, 0],
                    "print_recipe_top_to_bottom": [3, 1, 0, 1, 0, 0],
                    "actual_layer_count": 5,
                    "padding_layer_count": 1,
                    "virtual_materials": [
                        {"name": "Custom Violet", "hex": "#8A2BE2"}
                    ],
                }
            ],
        )
        store.put(session_id, "selected_region_masks", {"virtual-region": virtual_mask})

        captured_overrides: list[tuple[list, dict[str, np.ndarray], tuple[int, ...]]] = []

        async def _submit_stub(_func, _source, _lut, params) -> dict[str, object]:
            if masks_path := params.get("recipe_override_masks_path"):
                with open(masks_path, "rb") as handle:
                    masks = pickle.load(handle)
                solid_shape = np.load(params["mask_solid_path"], allow_pickle=False).shape
                captured_overrides.append((params["recipe_overrides"], masks, solid_shape))
            path = Path(params["export_only_3mf_path"])
            path.write_bytes(b"piece-3mf")
            return {
                "threemf_path": str(path),
                "glb_path": None,
                "status_msg": "ok",
                "x_mirrored": False,
                "mirror_span_mm": 1.0,
            }

        def _assemble_stub(*, output_path: str, **_kwargs) -> str:
            Path(output_path).write_bytes(b"combined-3mf")
            return output_path

        pool.submit = AsyncMock(side_effect=_submit_stub)
        with patch(
            "api.routers.converter.puzzle.assemble_puzzle_3mf",
            side_effect=_assemble_stub,
        ):
            response = client.post(
                "/api/convert/generate-puzzle",
                json=_generate_puzzle_body(session_id),
            )

        assert response.status_code == 200, response.text
        assert captured_overrides
        overrides, masks, solid_shape = captured_overrides[0]
        assert overrides[0]["virtual_materials"] == [
            {"name": "Custom Violet", "hex": "#8A2BE2"}
        ]
        assert "virtual-region" in masks
        assert masks["virtual-region"].dtype == np.bool_
        assert masks["virtual-region"].shape == solid_shape

    @pytest.mark.parametrize(
        "snapshot_container",
        [{}, None, "corrupt-container"],
        ids=["empty", "none", "corrupt"],
    )
    def test_dynamic_puzzle_present_snapshot_key_never_uses_live_mask(
        self,
        puzzle_harness,
        tmp_path,
        snapshot_container,
    ) -> None:
        """Modern puzzle sessions reject unusable snapshots before workers run."""

        store: SessionStore = puzzle_harness["store"]
        pool: MagicMock = puzzle_harness["pool"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_dynamic_puzzle_generate_session(store, tmp_path)
        session_data = store.get(session_id)
        assert session_data is not None
        region_id = "virtual-region"
        live_mask = np.zeros((80, 120), dtype=bool)
        live_mask[:40, :60] = True
        store.put(
            session_id,
            "recipe_overrides",
            [{
                "region_id": region_id,
                "recipe": [2, 1, 2, 1, 0, 0],
                "layer_order": "Top2Bottom",
            }],
        )
        store.put(session_id, "selected_region_masks", {region_id: live_mask})
        store.put(
            session_id,
            RECIPE_OVERRIDE_APPLIED_MASKS_KEY,
            snapshot_container,
        )

        piece_index = 0

        async def _submit_stub(*_args, **_kwargs) -> dict[str, object]:
            nonlocal piece_index
            piece_index += 1
            path = tmp_path / f"strict-snapshot-piece-{piece_index}.3mf"
            path.write_bytes(b"piece-3mf")
            return {
                "threemf_path": str(path),
                "glb_path": None,
                "status_msg": "ok",
                "x_mirrored": False,
                "mirror_span_mm": 1.0,
            }

        def _assemble_stub(*, output_path: str, **_kwargs) -> str:
            Path(output_path).write_bytes(b"combined-3mf")
            return output_path

        pool.submit = AsyncMock(side_effect=_submit_stub)
        with patch(
            "api.routers.converter.puzzle.assemble_puzzle_3mf",
            side_effect=_assemble_stub,
        ):
            response = client.post(
                "/api/convert/generate-puzzle",
                json=_generate_puzzle_body(session_id),
            )

        assert response.status_code == 409
        assert "Re-run preview" in response.json()["detail"]
        pool.submit.assert_not_called()

    def test_dynamic_puzzle_rejects_backing_override_mismatch(
        self,
        puzzle_harness,
        tmp_path,
    ) -> None:
        store: SessionStore = puzzle_harness["store"]
        pool: MagicMock = puzzle_harness["pool"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_dynamic_puzzle_generate_session(store, tmp_path)
        body = _generate_puzzle_body(session_id)
        body["params"]["params"]["material_backing_material_index"] = 1

        response = client.post("/api/convert/generate-puzzle", json=body)

        assert response.status_code == 409
        assert "material_backing_material_index" in response.json()["detail"]["fields"]
        pool.submit.assert_not_called()
