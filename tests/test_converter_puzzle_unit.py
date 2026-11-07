"""Unit tests for converter puzzle endpoints.

Validates:
- Layout preview returns an overlay and resolved grid summary
- Puzzle generation crops per-piece matched RGB inputs
- Puzzle generation assembles a single 3MF output instead of a ZIP archive
"""

from __future__ import annotations

from dataclasses import replace
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app import create_app
import config as runtime_config
from api.workers.converter_workers import worker_generate_model
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import externalize_preview_cache
from api.schemas.converter import ConvertGenerateRequest
from api.routers.converter import puzzle as puzzle_router
from api.routers.converter.puzzle import _crop_piece_arrays, _submit_puzzle_worker
from api.routers.converter.common import BATCH_DOWNLOAD_TTL_SECONDS
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from config import ModelingMode
from core.converter import generate_preview_cached
from core.puzzle import (
    PuzzleLayoutConfig,
    build_puzzle_layout,
    export_piece_boundary_geometry,
    rasterize_piece_mask,
)

_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()
_mock_pool = MagicMock(spec=WorkerPoolManager)
_mock_pool.max_workers = 2
_TEST_TEMP_DIR = tempfile.gettempdir()
_ORIGINAL_RUNTIME_TEMP_DIR = runtime_config.TEMP_DIR
_ORIGINAL_PUZZLE_TEMP_DIR = puzzle_router.TEMP_DIR


def setup_module(module) -> None:
    runtime_config.TEMP_DIR = _TEST_TEMP_DIR
    puzzle_router.TEMP_DIR = _TEST_TEMP_DIR


def teardown_module(module) -> None:
    runtime_config.TEMP_DIR = _ORIGINAL_RUNTIME_TEMP_DIR
    puzzle_router.TEMP_DIR = _ORIGINAL_PUZZLE_TEMP_DIR
    _test_registry.clear_all()
    _test_store.clear_all()


def _make_puzzle_client() -> TestClient:
    """Create a puzzle-only API client without app lifespan side effects.
    创建不触发完整应用 lifespan 副作用的拼图专用测试客户端。

    Returns:
        TestClient: Lightweight puzzle endpoint client. (轻量拼图接口测试客户端)
    """

    test_app = FastAPI()
    test_app.include_router(puzzle_router.router, prefix="/api/convert")
    test_app.dependency_overrides[get_session_store] = lambda: _test_store
    test_app.dependency_overrides[get_file_registry] = lambda: _test_registry
    test_app.dependency_overrides[get_worker_pool] = lambda: _mock_pool
    return TestClient(test_app, raise_server_exceptions=False)


client = _make_puzzle_client()


@pytest.fixture(autouse=True)
def stub_material_slots_for_sentinel_worker_packages(monkeypatch) -> None:
    """Keep route scheduling independent of the fake worker's sentinel bytes.

    路由调度用的 worker 假文件不是 3MF；真实槽位读回由 writer 集成测试覆盖。
    """
    monkeypatch.setattr(
        puzzle_router,
        "_batch_extract_slots_from_3mf",
        lambda *_args, **_kwargs: [
            {"slot_id": 0, "slot_name": "White", "preview_color": "#FFFFFF", "material_id": "PLA"},
        ],
    )


def _make_session() -> tuple[str, dict[str, Any]]:
    """Create a preview-ready session for puzzle endpoint tests.

    Returns:
        tuple[str, dict[str, Any]]: Session ID and the preview cache.
            (Session ID 与预览缓存)
    """

    session_id = _test_store.create()

    matched_rgb = np.zeros((80, 120, 3), dtype=np.uint8)
    matched_rgb[:40, :, :] = (255, 0, 0)
    matched_rgb[40:, :, :] = (0, 255, 0)
    mask_solid = np.ones((80, 120), dtype=bool)
    preview_rgba = np.zeros((80, 120, 4), dtype=np.uint8)
    preview_rgba[..., :3] = matched_rgb
    preview_rgba[..., 3] = 255

    fd_img, image_path = tempfile.mkstemp(suffix=".png")
    os.close(fd_img)
    fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
    os.close(fd_lut)
    # The route's native material preflight reads this LUT before scheduling.
    # Use a valid standard-size RGB table, even though workers are stubbed.
    np.save(lut_path, np.zeros((32, 3), dtype=np.uint8))

    preview_cache = {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "preview_rgba": preview_rgba,
        "preview_colors": {"White": (255, 255, 255, 255)},
        "slot_names": ["White"],
    }

    _test_store.put(session_id, "image_path", image_path)
    _test_store.put(session_id, "lut_path", lut_path)
    _test_store.put(session_id, "preview_cache", preview_cache)
    _test_store.register_temp_file(session_id, image_path)
    _test_store.register_temp_file(session_id, lut_path)
    return session_id, preview_cache


def _make_artifact_session(tmp_path: Path) -> tuple[str, dict[str, Any]]:
    session_id, preview_cache = _make_session()
    cache_ref = externalize_preview_cache(
        session_id,
        _test_store,
        preview_cache,
        root_dir=tmp_path,
    )
    _test_store.put(session_id, "preview_cache", cache_ref)
    return session_id, preview_cache


def _seed_puzzle_session(store: SessionStore, tmp_path: Path) -> str:
    """Create a preview-ready puzzle session in the provided store.
    在指定 store 中创建可用于拼图生成的预览 session。
    """

    session_id = store.create()
    matched_rgb = np.zeros((80, 120, 3), dtype=np.uint8)
    matched_rgb[:40, :, :] = (255, 0, 0)
    matched_rgb[40:, :, :] = (0, 255, 0)
    mask_solid = np.ones((80, 120), dtype=bool)
    preview_rgba = np.zeros((80, 120, 4), dtype=np.uint8)
    preview_rgba[..., :3] = matched_rgb
    preview_rgba[..., 3] = 255

    image_path = tmp_path / "puzzle.png"
    lut_path = tmp_path / "palette.npy"
    Image.fromarray(matched_rgb).save(image_path)
    np.save(lut_path, np.zeros((32, 3), dtype=np.uint8))

    store.put(session_id, "image_path", str(image_path))
    store.put(session_id, "lut_path", str(lut_path))
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
    store.register_temp_file(session_id, str(image_path))
    store.register_temp_file(session_id, str(lut_path))
    return session_id


def _build_generate_body(session_id: str) -> dict[str, Any]:
    """Build a valid puzzle generate request body.

    Args:
        session_id: Active session ID. (当前 Session ID)

    Returns:
        dict[str, Any]: JSON payload for the generate endpoint. (生成接口请求体)
    """

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
            "params": {
                "lut_name": "test_lut",
                "target_width_mm": 90,
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "high-fidelity",
                "quantize_colors": 48,
                "enable_cleanup": True,
                "hue_weight": 0.0,
                "chroma_gate": 0,
                "is_dark": False,
                "spacer_thick": 1.2,
                "structure_mode": "Double-sided",
                "separate_backing": False,
                "add_loop": False,
                "loop_width": 4.0,
                "loop_length": 8.0,
                "loop_hole": 2.5,
                "loop_angle": 0,
                "loop_offset_x": 0,
                "loop_offset_y": 0,
                "loop_position_preset": "top-center",
                "enable_relief": False,
                "heightmap_max_height": 3.0,
                "enable_outline": False,
                "outline_width": 2.0,
                "enable_cloisonne": False,
                "wire_width_mm": 0.4,
                "wire_height_mm": 0.4,
                "enable_coating": False,
                "coating_height_mm": 0.08,
                "printer_id": "bambu-h2d",
                "slicer": "BambuStudio",
                "nozzle_size": "0.2",
                "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.2",
                "build_plate_id": "smooth-pei-plate",
            },
        },
    }


def test_puzzle_layout_preview_returns_overlay_and_grid_summary() -> None:
    """The layout preview endpoint should emit a transparent overlay resource."""

    session_id, _preview_cache = _make_session()
    response = client.post(
        "/api/convert/puzzle-layout-preview",
        json={
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
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overlay_url"].startswith("/api/files/")
    assert body["piece_count"] == 6
    assert body["grid_rows"] == 2
    assert body["grid_cols"] == 3


def test_puzzle_layout_preview_artifact_cache_avoids_common_full_hydrate(
    tmp_path: Path,
) -> None:
    session_id, _preview_cache = _make_artifact_session(tmp_path)

    with patch(
        "api.routers.converter.common.hydrate_preview_cache",
        side_effect=AssertionError("puzzle layout must not fully hydrate artifact cache"),
    ):
        response = client.post(
            "/api/convert/puzzle-layout-preview",
            json={
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
            },
        )

    assert response.status_code == 200, response.text


def test_puzzle_layout_preview_reuses_cached_layout_and_overlay() -> None:
    """Repeated preview requests with identical params should reuse cached preview assets."""

    session_id, _preview_cache = _make_session()
    preview_body = {
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

    first_response = client.post("/api/convert/puzzle-layout-preview", json=preview_body)

    assert first_response.status_code == 200

    with patch("api.routers.converter.puzzle.build_puzzle_layout", side_effect=AssertionError("layout cache missed")), patch(
        "api.routers.converter.puzzle.render_puzzle_overlay",
        side_effect=AssertionError("overlay cache missed"),
    ):
        second_response = client.post("/api/convert/puzzle-layout-preview", json=preview_body)

    assert second_response.status_code == 200
    assert first_response.json()["overlay_url"] == second_response.json()["overlay_url"]


def test_generate_puzzle_worker_missing_output_uses_public_error_detail(tmp_path: Path) -> None:
    """Worker diagnostics should stay in logs, not the user-visible 500 detail."""

    session_id, _preview_cache = _make_session()
    private_path = str(tmp_path / "missing-private-piece.3mf")
    assert not os.path.exists(private_path)
    raw_status = f"cannot write {private_path}: permission denied"
    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": private_path,
            "glb_path": None,
            "status_msg": raw_status,
        }
    )

    try:
        with patch.object(puzzle_router.log, "error") as log_error:
            response = client.post(
                "/api/convert/generate-puzzle",
                json=_build_generate_body(session_id),
            )
    finally:
        _test_store.close(session_id)

    assert response.status_code == 500
    assert response.json()["detail"] == puzzle_router._PUZZLE_PIECE_GENERATION_FAILED_DETAIL
    assert private_path not in response.text
    assert "permission denied" not in response.text
    assert "cannot write" not in response.text
    assert log_error.call_args is not None
    logged_error = log_error.call_args.kwargs["extra"]["error_message"]
    assert private_path in logged_error
    assert raw_status in logged_error


def test_generate_puzzle_rejects_piece_missing_export_transform_metadata(
    tmp_path: Path,
) -> None:
    """A successful piece file without S09 transform metadata is unsafe to assemble."""

    session_id, _preview_cache = _make_session()
    piece_path = tmp_path / "piece-without-transform-metadata.3mf"
    piece_path.write_bytes(b"piece-3mf")
    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(piece_path),
            "glb_path": None,
            "status_msg": "ok",
        }
    )

    try:
        with patch.object(puzzle_router.log, "error") as log_error:
            response = client.post(
                "/api/convert/generate-puzzle",
                json=_build_generate_body(session_id),
            )
    finally:
        _test_store.close(session_id)

    assert response.status_code == 500
    assert response.json()["detail"] == puzzle_router._PUZZLE_PIECE_GENERATION_FAILED_DETAIL
    logged_error = log_error.call_args.kwargs["extra"]["error_message"]
    assert "export transform metadata unavailable" in logged_error


def test_generate_puzzle_inherits_dynamic_settings_and_maps_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.material_dynamic_solver import DynamicMaterialCandidateError
    from core import material_lut_provider, material_lut_synthesis

    materials_dir = str(Path(__file__).parent / "fixtures" / "dynamic_material_materials")
    monkeypatch.setattr(material_lut_provider, "MATERIALS_DIR", materials_dir)
    monkeypatch.setattr(material_lut_synthesis, "MATERIALS_DIR", materials_dir)

    session_id, preview_cache = _make_session()
    preview_cache["quantized_image"] = np.array(preview_cache["matched_rgb"], copy=True)
    preview_cache["material_matrix"] = np.zeros(
        (*preview_cache["mask_solid"].shape, 8),
        dtype=np.int32,
    )
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(session_id, "selected_materials", ["white", "blue"])
    _test_store.put(session_id, "material_layer_count", 10)
    _test_store.put(session_id, "material_dynamic_layer_count_enabled", True)
    _test_store.put(session_id, "material_min_layer_count", 6)
    _test_store.put(session_id, "material_max_layer_count", 8)
    _test_store.put(session_id, "material_delta_e00_tolerance", 0.4)
    captured: dict[str, object] = {}

    async def _raise_typed(
        _func: object,
        _piece_image_path: str,
        _lut_path: str,
        worker_params: dict[str, object],
    ) -> dict[str, object]:
        captured.update(worker_params)
        raise DynamicMaterialCandidateError(
            "no candidate",
            target_srgb=(12, 34, 56),
            layer_count=6,
            phase="exact_search",
        )

    _mock_pool.submit = AsyncMock(side_effect=_raise_typed)
    body = _build_generate_body(session_id)
    body["params"]["rows"] = 1
    body["params"]["cols"] = 1
    body["params"]["target_piece_count"] = 1
    body["params"]["params"]["lut_name"] = "__material_archive__"

    preview_cache.update(ConvertGenerateRequest.model_validate(body["params"]["params"]).model_dump())
    preview_cache.update(material_source="material_archive", color_layers=8, layer_height_mm=0.08)

    try:
        response = client.post("/api/convert/generate-puzzle", json=body)
    finally:
        _test_store.close(session_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dynamic_material_no_candidate"
    assert captured["material_dynamic_layer_count_enabled"] is True
    assert captured["material_min_layer_count"] == 6
    assert captured["material_max_layer_count"] == 8
    assert captured["material_delta_e00_tolerance"] == 0.4


def test_puzzle_requires_fresh_preview_after_compensation_changes(tmp_path) -> None:
    session_id, cache = _make_session()
    path = tmp_path / "picture.svg"
    path.write_text("<svg/>", encoding="utf-8")
    _test_store.put(session_id, "image_path", str(path))
    cache["svg_hole_compensation_enabled"] = False
    body = _build_generate_body(session_id)
    body["params"]["params"].update(
        modeling_mode="vector", svg_hole_compensation_enabled=True,
    )
    _mock_pool.submit = AsyncMock()
    response = client.post("/api/convert/generate-puzzle", json=body)
    assert response.status_code == 409
    assert "compensation" in response.json()["detail"]
    _mock_pool.submit.assert_not_called()


@pytest.mark.parametrize("compensation_enabled", [False, True])
def test_generate_puzzle_assembles_single_3mf_and_passes_piece_matched_rgb(compensation_enabled) -> None:
    """Puzzle generation should align per-piece helper assets to the worker raster grid."""

    session_id, preview_cache = _make_session()
    submitted_params: list[dict[str, Any]] = []
    assembled_calls: list[dict[str, Any]] = []
    async def _submit_stub(
        func: object,
        piece_image_path: str,
        lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        submitted_params.append(worker_params)
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        with open(piece_path, "wb") as handle:
            handle.write(b"piece-3mf")
        return {
            "threemf_path": piece_path,
            "glb_path": None,
            "status_msg": "ok",
            "x_mirrored": False,
            "mirror_span_mm": round(float(worker_params["target_width_mm"]) * 10.0) / 10.0,
        }

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        piece_slots: list[Any],
        output_path: str,
        preview_colors: dict[object, object] | None,
        slot_names: list[str] | None,
        slot_index_by_name: dict[str, int],
        printer_id: str,
        metadata_target: Any,
        nozzle_size: str = "0.4",
        device_profile_id: str | None = None,
        build_plate_id: str | None = None,
        overview_png_bytes: bytes | None = None,
        material_types: dict[str, str | None],
        external_spool_material: str | None,
        native_filament_profiles: dict[str, str],
        enable_wipe_tower_auto_placement: bool = True,
    ) -> str:
        assembled_calls.append(
            {
                "piece_count": len(piece_sources),
                "offsets_x_mm": [source.offset_x_mm for source in piece_sources],
                "printer_id": printer_id,
                "slicer": metadata_target.slicer_id,
                "piece_slots": piece_slots,
                "slot_index_by_name": slot_index_by_name,
                "nozzle_size": nozzle_size,
                "build_plate_id": build_plate_id,
                "enable_wipe_tower_auto_placement": (
                    enable_wipe_tower_auto_placement
                ),
                "slot_names": slot_names,
                "overview_bytes": overview_png_bytes,
                "material_types": material_types,
                "native_filament_profiles": native_filament_profiles,
            }
        )
        with open(output_path, "wb") as handle:
            handle.write(b"combined-3mf")
        return output_path

    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)

    generate_body = _build_generate_body(session_id)
    generate_body["params"]["params"].update(
        {
            "modeling_mode": "vector",
            "structure_mode": "Single-sided",
            "enable_relief": True,
            "height_mode": "color",
            "color_height_map": {"#ff0000": 2.2, "#00ff00": 2.6},
            "enable_wipe_tower_auto_placement": False,
        }
    )
    if compensation_enabled:
        from api.schemas.converter import ConvertGenerateRequest

        generate_body["params"]["params"]["svg_hole_compensation_enabled"] = True
        preview_cache.update(ConvertGenerateRequest(**generate_body["params"]["params"]).model_dump())
        preview_cache["material_source"] = "lut"
        path = Path(_test_store.get(session_id)["image_path"]).with_suffix(".svg")
        path.write_text("<svg/>", encoding="utf-8")
        _test_store.put(session_id, "image_path", str(path))
        _test_store.register_temp_file(session_id, str(path))

    with patch(
        "api.routers.converter.puzzle.assemble_puzzle_3mf",
        side_effect=_assemble_stub,
    ):
        response = client.post(
            "/api/convert/generate-puzzle",
            json=generate_body,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["piece_count"] == 6
    assert body["download_url"].startswith("/api/files/")
    assert body["threemf_disk_path"] is None
    assert len(submitted_params) == 6
    assert all(os.path.exists(params["piece_boundary_geometry_path"]) for params in submitted_params)
    assert all(params["disable_material_dilation"] is True for params in submitted_params)
    assert all(params["center_on_bed"] is False for params in submitted_params)
    assert all(params["add_loop"] is False for params in submitted_params)
    assert all(params["enable_fridge_magnet"] is False for params in submitted_params)
    assert all(params["fridge_magnets"] == [] for params in submitted_params)
    assert all(params["modeling_mode"] == ModelingMode.HIGH_FIDELITY for params in submitted_params)
    # These piece PNGs already contain compensation from the confirmed preview.
    assert all(params.get("svg_hole_compensation_enabled", False) is False for params in submitted_params)
    assert all(params["enable_relief"] is True for params in submitted_params)
    assert all(
        params["enable_wipe_tower_auto_placement"] is False
        for params in submitted_params
    )
    assert all(params["height_mode"] == "color" for params in submitted_params)
    assert all(
        params["color_height_map"] == {"#ff0000": 2.2, "#00ff00": 2.6}
        for params in submitted_params
    )
    assert len(assembled_calls) == 1
    assert assembled_calls[0]["material_types"] == {
        name: "PLA BASIC" for name in ("White", "Cyan", "Magenta", "Yellow")
    }
    assert assembled_calls[0]["native_filament_profiles"] == {
        name: "Bambu PLA Basic @BBL H2D 0.2 nozzle"
        for name in ("White", "Cyan", "Magenta", "Yellow")
    }
    assert assembled_calls[0]["piece_count"] == 6
    assert assembled_calls[0]["printer_id"] == "bambu-h2d"
    assert assembled_calls[0]["slicer"] == "BambuStudio"
    assert assembled_calls[0]["nozzle_size"] == "0.2"
    assert assembled_calls[0]["build_plate_id"] == "smooth-pei-plate"
    assert (
        assembled_calls[0]["enable_wipe_tower_auto_placement"] is False
    )
    assert assembled_calls[0]["slot_names"] == ["White"]
    assert len(assembled_calls[0]["piece_slots"]) == 6
    assert all(slots[0].slot_name == "White" for slots in assembled_calls[0]["piece_slots"])
    assert assembled_calls[0]["slot_index_by_name"] == {"White": 0}
    assert isinstance(assembled_calls[0]["overview_bytes"], bytes)
    assert assembled_calls[0]["overview_bytes"].startswith(b"\x89PNG")

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=80,
            total_width_mm=90.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=2,
            cols=3,
            seed=7,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )
    first_piece = layout.pieces[0]
    assert np.allclose(
        assembled_calls[0]["offsets_x_mm"],
        [piece.bbox_mm[0] for piece in layout.pieces],
        atol=1e-9,
    )
    first_boundary_path = Path(submitted_params[0]["piece_boundary_geometry_path"])
    with first_boundary_path.open("r", encoding="utf-8") as handle:
        boundary = json.load(handle)

    assert boundary["bbox_px"] == list(first_piece.bbox_px)
    assert len(boundary["polygon_px"]) >= 3
    assert len(boundary["holes_px"]) == len(first_piece.holes_px)
    first_matched_path = Path(submitted_params[0]["matched_rgb_path"])
    saved_matched = np.load(first_matched_path)
    bbox_px, local_mask = rasterize_piece_mask(first_piece)
    x0, y0, x1, y1 = bbox_px
    expected_worker_w = max(1, int(round((first_piece.bbox_mm[2] - first_piece.bbox_mm[0]) * 10.0)))
    expected_worker_h = max(1, int(round((first_piece.bbox_mm[3] - first_piece.bbox_mm[1]) * 10.0)))
    assert saved_matched.shape == (expected_worker_h, expected_worker_w, 3)

    expected_matched = np.array(preview_cache["matched_rgb"][y0:y1, x0:x1], copy=True)
    expected_matched[local_mask == 0] = 0
    expected_matched = np.array(
        Image.fromarray(expected_matched).resize((expected_worker_w, expected_worker_h), Image.Resampling.NEAREST),
        copy=False,
    )
    assert np.array_equal(saved_matched, expected_matched)
    assert np.any(saved_matched != 0)

    boundary_x_values = [point[0] for point in boundary["polygon_px"]]
    boundary_y_values = [point[1] for point in boundary["polygon_px"]]
    assert min(boundary_x_values) >= 0.5 - 1e-6
    assert min(boundary_y_values) >= 0.5 - 1e-6
    assert max(boundary_x_values) <= expected_worker_w - 0.5 + 1e-6
    assert max(boundary_y_values) <= expected_worker_h - 0.5 + 1e-6


def test_generate_puzzle_response_merges_only_embedded_wipe_tower_warnings(
    tmp_path: Path,
) -> None:
    """Puzzle responses expose final-assembly warnings without duplicates."""

    _test_store.clear_all()
    _test_registry.clear_all()
    warning_code = "wipe_tower_manual_adjustment_required"
    original_resolve_layout = puzzle_router._resolve_layout

    cases = (
        ("manual", True, False, [warning_code]),
        ("manual-existing", True, True, [warning_code]),
        ("safe", False, False, []),
    )
    for case_name, requires_manual_adjustment, seed_existing, expected_warnings in cases:
        session_id, _preview_cache = _make_session()
        piece_counter = 0

        async def _submit_stub(
            _func: object,
            _piece_image_path: str,
            _lut_path: str,
            _worker_params: dict[str, Any],
        ) -> dict[str, Any]:
            nonlocal piece_counter
            piece_counter += 1
            piece_path = tmp_path / f"piece-{case_name}-{piece_counter}.3mf"
            piece_path.write_bytes(b"piece-3mf")
            return {
                "threemf_path": str(piece_path),
                "glb_path": None,
                "status_msg": "ok",
                "x_mirrored": False,
                "mirror_span_mm": 90.0,
            }

        def _assemble_stub(*, output_path: str, **_kwargs: Any) -> str:
            with zipfile.ZipFile(output_path, "w") as package:
                package.writestr(
                    "Metadata/lumina_wipe_tower_placement.json",
                    json.dumps(
                        {
                            "requires_manual_adjustment": (
                                requires_manual_adjustment
                            ),
                            "warning_code": (
                                warning_code
                                if requires_manual_adjustment
                                else None
                            ),
                        }
                    ),
                )
            return output_path

        def _resolve_layout_stub(
            **kwargs: Any,
        ) -> tuple[PuzzleLayout, tuple[Any, ...]]:
            layout, cache_key = original_resolve_layout(**kwargs)
            if seed_existing:
                layout = replace(
                    layout,
                    warnings=(*layout.warnings, warning_code),
                )
            return layout, cache_key

        body = _build_generate_body(session_id)
        body["params"].update(
            {"rows": 1, "cols": 1, "target_piece_count": 1}
        )
        _mock_pool.submit = AsyncMock(side_effect=_submit_stub)

        try:
            with patch(
                "api.routers.converter.puzzle.assemble_puzzle_3mf",
                side_effect=_assemble_stub,
            ), patch(
                "api.routers.converter.puzzle._resolve_layout",
                side_effect=_resolve_layout_stub,
            ):
                response = client.post(
                    "/api/convert/generate-puzzle",
                    json=body,
                )

            assert response.status_code == 200, response.text
            assert response.json()["warnings"] == expected_warnings
            assert response.json()["warnings"].count(warning_code) <= 1
        finally:
            _test_store.close(session_id)
            _test_registry.clear_all()


def test_generate_puzzle_places_face_down_single_sided_pieces_with_actual_mirror_span() -> None:
    """Assembly placement should use the exact X-mirror span reported by S09."""

    session_id, _preview_cache = _make_session()
    assembled_sources: list[Any] = []

    async def _submit_stub(
        _func: object,
        _piece_image_path: str,
        _lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        Path(piece_path).write_bytes(b"piece-3mf")
        mirror_span_mm = round(float(worker_params["target_width_mm"]) * 10.0) / 10.0
        return {
            "threemf_path": piece_path,
            "glb_path": None,
            "status_msg": "ok",
            "x_mirrored": True,
            "mirror_span_mm": mirror_span_mm,
        }

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        output_path: str,
        **_kwargs: object,
    ) -> str:
        assembled_sources.extend(piece_sources)
        Path(output_path).write_bytes(b"combined-3mf")
        return output_path

    body = _build_generate_body(session_id)
    body["params"]["params"]["structure_mode"] = "Single-sided"
    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)

    try:
        with patch(
            "api.routers.converter.puzzle.assemble_puzzle_3mf",
            side_effect=_assemble_stub,
        ):
            response = client.post("/api/convert/generate-puzzle", json=body)
    finally:
        _test_store.close(session_id)

    assert response.status_code == 200, response.text
    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=80,
            total_width_mm=90.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=2,
            cols=3,
            seed=7,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )
    expected_offsets = [
        layout.total_width_mm
        - piece.bbox_mm[0]
        - round((piece.bbox_mm[2] - piece.bbox_mm[0]) * 10.0) / 10.0
        for piece in layout.pieces
    ]
    actual_offsets = [source.offset_x_mm for source in assembled_sources]

    assert len(actual_offsets) == len(expected_offsets)
    assert np.allclose(actual_offsets, expected_offsets, atol=1e-9)


def test_generate_puzzle_download_survives_source_session_close(tmp_path: Path) -> None:
    """Final puzzle 3MF downloads should outlive the source session.
    拼图最终 3MF 下载应在源 session 关闭后仍可访问。
    """

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = MagicMock(spec=WorkerPoolManager)
    full_app = create_app()
    full_app.dependency_overrides[get_session_store] = lambda: store
    full_app.dependency_overrides[get_file_registry] = lambda: registry
    full_app.dependency_overrides[get_worker_pool] = lambda: pool
    full_client = TestClient(full_app, raise_server_exceptions=False)
    session_id = _seed_puzzle_session(store, tmp_path)
    piece_index = 0

    async def _submit_stub(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal piece_index
        piece_index += 1
        piece_path = tmp_path / f"piece-{piece_index}.3mf"
        piece_path.write_bytes(b"piece-3mf")
        return {
            "threemf_path": str(piece_path),
            "glb_path": None,
            "status_msg": "ok",
            "x_mirrored": False,
            "mirror_span_mm": 1.0,
        }

    def _assemble_stub(*, output_path: str, **_kwargs: object) -> str:
        Path(output_path).write_bytes(b"combined-3mf")
        return output_path

    pool.submit = AsyncMock(side_effect=_submit_stub)

    try:
        with patch(
            "api.routers.converter.puzzle.assemble_puzzle_3mf",
            side_effect=_assemble_stub,
        ):
            response = full_client.post(
                "/api/convert/generate-puzzle",
                json=_build_generate_body(session_id),
            )

        assert response.status_code == 200, response.text
        body = response.json()
        download_url = body["download_url"]
        download_file_id = download_url.rsplit("/", 1)[-1]
        entry = registry.get_entry(download_file_id)
        assert entry is not None
        assert entry["lifecycle"] == "ephemeral"
        assert entry["session_id"] != session_id
        assert entry["ttl_seconds"] == BATCH_DOWNLOAD_TTL_SECONDS
        assert body["threemf_disk_path"] is None

        close_response = full_client.post(
            "/api/session/close",
            json={"session_id": session_id},
        )
        assert close_response.status_code == 200

        download_response = full_client.get(download_url)
        assert download_response.status_code == 200
        assert download_response.content == b"combined-3mf"
    finally:
        registry.clear_all()
        store.clear_all()
        full_app.dependency_overrides.clear()


def test_generate_puzzle_deletes_combined_output_when_assembly_fails(tmp_path: Path) -> None:
    """Unregistered final puzzle outputs should be removed on assembly failure.
    拼图组装失败时应删除尚未注册的最终输出文件。
    """

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = MagicMock(spec=WorkerPoolManager)
    full_app = create_app()
    full_app.dependency_overrides[get_session_store] = lambda: store
    full_app.dependency_overrides[get_file_registry] = lambda: registry
    full_app.dependency_overrides[get_worker_pool] = lambda: pool
    full_client = TestClient(full_app, raise_server_exceptions=False)
    session_id = _seed_puzzle_session(store, tmp_path)
    piece_index = 0
    combined_paths: list[str] = []
    private_path = "/Users/min/private/puzzle-piece.3mf"

    async def _submit_stub(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal piece_index
        piece_index += 1
        piece_path = tmp_path / f"piece-{piece_index}.3mf"
        piece_path.write_bytes(b"piece-3mf")
        return {
            "threemf_path": str(piece_path),
            "glb_path": None,
            "status_msg": "ok",
            "x_mirrored": False,
            "mirror_span_mm": 1.0,
        }

    def _assemble_failure_stub(*, output_path: str, **_kwargs: object) -> str:
        combined_paths.append(output_path)
        Path(output_path).write_bytes(b"partial-combined-3mf")
        raise RuntimeError(f"cannot rewrite {private_path}: invalid archive")

    pool.submit = AsyncMock(side_effect=_submit_stub)

    try:
        with (
            patch(
                "api.routers.converter.puzzle.assemble_puzzle_3mf",
                side_effect=_assemble_failure_stub,
            ),
            patch.object(puzzle_router.log, "error") as log_error,
        ):
            response = full_client.post(
                "/api/convert/generate-puzzle",
                json=_build_generate_body(session_id),
            )

        assert response.status_code == 500
        assert response.json()["detail"] == (
            "Puzzle 3MF assembly failed. The generated pieces could not be "
            "combined into a downloadable file. Try generating the puzzle again."
        )
        assert private_path not in response.text
        log_error.assert_called_once()
        log_extra = log_error.call_args.kwargs["extra"]
        assert log_extra["error_type"] == "RuntimeError"
        assert log_extra["error_message"] == response.json()["detail"]
        assert private_path not in log_extra["error_message"]
        assert combined_paths
        assert os.path.exists(combined_paths[0]) is False
    finally:
        registry.clear_all()
        store.clear_all()
        full_app.dependency_overrides.clear()


def test_generate_puzzle_rejects_fridge_magnet_mode() -> None:
    """Puzzle generation should reject fridge-magnet mode instead of duplicating cavities per piece."""

    session_id, _preview_cache = _make_session()
    body = _build_generate_body(session_id)
    body["params"]["params"]["enable_fridge_magnet"] = True
    body["params"]["params"]["fridge_magnets"] = [
        {
            "id": "magnet-round",
            "shape": "round",
            "preset_key": "round-18",
            "diameter_mm": 18.0,
            "width_mm": None,
            "height_mm": None,
            "thickness_mm": 2.0,
            "center_x_mm": 0.0,
            "center_y_mm": 0.0,
        }
    ]

    response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 422
    assert "fridge magnet" in response.json()["detail"].lower()


def test_generate_puzzle_rejects_fridge_magnet_flag_even_with_empty_list() -> None:
    """Puzzle generation should reject the opt-in flag even when no cavity list is supplied."""

    session_id, _preview_cache = _make_session()
    body = _build_generate_body(session_id)
    body["params"]["params"]["enable_fridge_magnet"] = True
    body["params"]["params"]["fridge_magnets"] = []

    response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 422
    assert "fridge magnet" in response.json()["detail"].lower()


def test_generate_puzzle_artifact_cache_rejects_relief_height_below_manifest_depth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core import material_lut_provider, material_lut_synthesis

    materials_dir = str(Path(__file__).parent / "fixtures" / "dynamic_material_materials")
    monkeypatch.setattr(material_lut_provider, "MATERIALS_DIR", materials_dir)
    monkeypatch.setattr(material_lut_synthesis, "MATERIALS_DIR", materials_dir)
    _test_store.clear_all()
    session_id, preview_cache = _make_session()
    preview_cache["material_matrix"] = np.zeros((80, 120, 10), dtype=np.uint8)
    cache_ref = externalize_preview_cache(
        session_id,
        _test_store,
        preview_cache,
        root_dir=tmp_path,
    )
    _test_store.put(session_id, "preview_cache", cache_ref)
    _test_store.put(session_id, "lut_path", "__material_archive__")
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(session_id, "selected_materials", ["white", "blue"])
    _test_store.put(session_id, "material_layer_count", 5)
    _test_store.put(session_id, "material_layer_height_mm", 0.08)
    _mock_pool.submit = AsyncMock()

    body = _build_generate_body(session_id)
    body["params"]["params"]["lut_name"] = "__material_archive__"
    body["params"]["params"]["enable_relief"] = True
    body["params"]["params"]["height_mode"] = "color"
    body["params"]["params"]["color_height_map"] = {"#111111": 0.6}
    body["params"]["params"]["heightmap_max_height"] = 0.6

    response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 422, response.text
    assert "0.80 mm" in response.json()["detail"]
    _mock_pool.submit.assert_not_called()


def test_generate_puzzle_resizes_heightmap_crop_to_worker_grid() -> None:
    """Heightmap relief inputs should stay aligned with the worker raster grid."""

    session_id, _preview_cache = _make_session()
    submitted_params: list[dict[str, Any]] = []
    heightmap = np.tile(np.arange(120, dtype=np.uint8), (80, 1))
    _test_store.put(session_id, "heightmap_grayscale", heightmap)

    async def _submit_stub(
        func: object,
        piece_image_path: str,
        lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        submitted_params.append(worker_params)
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        with open(piece_path, "wb") as handle:
            handle.write(b"piece-3mf")
        return {
            "threemf_path": piece_path,
            "glb_path": None,
            "status_msg": "ok",
            "x_mirrored": False,
            "mirror_span_mm": 1.0,
        }

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        piece_slots: list[Any],
        output_path: str,
        preview_colors: dict[object, object] | None,
        slot_names: list[str] | None,
        slot_index_by_name: dict[str, int],
        printer_id: str,
        metadata_target: Any,
        nozzle_size: str = "0.4",
        device_profile_id: str | None = None,
        build_plate_id: str | None = None,
        overview_png_bytes: bytes | None = None,
        material_types: dict[str, str | None],
        external_spool_material: str | None,
        native_filament_profiles: dict[str, str],
        enable_wipe_tower_auto_placement: bool = True,
    ) -> str:
        with open(output_path, "wb") as handle:
            handle.write(b"combined-3mf")
        return output_path

    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)
    body = _build_generate_body(session_id)
    body["params"]["params"]["modeling_mode"] = "vector"
    body["params"]["params"]["enable_relief"] = True
    body["params"]["params"]["height_mode"] = "heightmap"
    body["params"]["params"]["heightmap_max_height"] = 4.0

    with patch(
        "api.routers.converter.puzzle.assemble_puzzle_3mf",
        side_effect=_assemble_stub,
    ):
        response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 200
    assert submitted_params
    assert all("heightmap_path" in params for params in submitted_params)
    assert all(
        params["modeling_mode"] == ModelingMode.HIGH_FIDELITY
        for params in submitted_params
    )

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=80,
            total_width_mm=90.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=2,
            cols=3,
            seed=7,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )
    first_piece = layout.pieces[0]
    expected_worker_w = max(1, int(round((first_piece.bbox_mm[2] - first_piece.bbox_mm[0]) * 10.0)))
    expected_worker_h = max(1, int(round((first_piece.bbox_mm[3] - first_piece.bbox_mm[1]) * 10.0)))
    saved_heightmap = np.array(Image.open(submitted_params[0]["heightmap_path"]))

    assert saved_heightmap.shape == (expected_worker_h, expected_worker_w)
    assert np.any(saved_heightmap != 0)


def test_generate_puzzle_emits_hybrid_boundary_log_for_each_piece() -> None:
    """Each submitted puzzle piece should emit the structured hybrid-boundary log."""

    session_id, _preview_cache = _make_session()
    submitted_params: list[dict[str, Any]] = []

    async def _submit_stub(
        func: object,
        piece_image_path: str,
        lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        submitted_params.append(worker_params)
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        with open(piece_path, "wb") as handle:
            handle.write(b"piece-3mf")
        return {
            "threemf_path": piece_path,
            "glb_path": None,
            "status_msg": "ok",
            "x_mirrored": False,
            "mirror_span_mm": 1.0,
        }

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        piece_slots: list[Any],
        output_path: str,
        preview_colors: dict[object, object] | None,
        slot_names: list[str] | None,
        slot_index_by_name: dict[str, int],
        printer_id: str,
        metadata_target: Any,
        nozzle_size: str = "0.4",
        device_profile_id: str | None = None,
        build_plate_id: str | None = None,
        overview_png_bytes: bytes | None = None,
        material_types: dict[str, str | None],
        external_spool_material: str | None,
        native_filament_profiles: dict[str, str],
        enable_wipe_tower_auto_placement: bool = True,
    ) -> str:
        with open(output_path, "wb") as handle:
            handle.write(b"combined-3mf")
        return output_path

    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)

    body = _build_generate_body(session_id)
    with patch("api.routers.converter.puzzle.assemble_puzzle_3mf", side_effect=_assemble_stub), patch.object(
        puzzle_router.log,
        "debug",
    ) as log_debug:
        response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 200
    assert len(submitted_params) == 6
    hybrid_boundary_calls = [
        call for call in log_debug.call_args_list if call.kwargs["extra"]["event"] == "converter_puzzle_hybrid_boundary_enabled"
    ]
    assert len(hybrid_boundary_calls) == 6

    logged_piece_labels = {
        call.kwargs["extra"]["piece_label"]
        for call in hybrid_boundary_calls
    }
    assert logged_piece_labels == {"A1", "A2", "A3", "B1", "B2", "B3"}
    assert all(call.kwargs["extra"]["session_id"] == session_id for call in hybrid_boundary_calls)


def test_submit_puzzle_worker_preserves_boundary_params() -> None:
    """The worker submission shim should forward puzzle boundary params unchanged."""

    captured: dict[str, Any] = {}

    def _worker_stub(image_path: str, lut_path: str, params: dict[str, Any]) -> dict[str, Any]:
        captured["image_path"] = image_path
        captured["lut_path"] = lut_path
        captured["params"] = params
        return {"status_msg": "ok"}

    with patch("api.routers.converter.puzzle.worker_generate_model", side_effect=_worker_stub):
        result = _submit_puzzle_worker(
            "piece.png",
            "lut.npy",
            {
                "piece_boundary_geometry_path": "boundary.json",
                "disable_material_dilation": True,
                "center_on_bed": False,
            },
        )

    assert result["status_msg"] == "ok"
    assert captured["image_path"] == "piece.png"
    assert captured["lut_path"] == "lut.npy"
    assert captured["params"]["piece_boundary_geometry_path"] == "boundary.json"
    assert captured["params"]["disable_material_dilation"] is True
    assert captured["params"]["center_on_bed"] is False


def test_generate_puzzle_reuses_cached_layout_after_preview() -> None:
    """Generate should reuse the authoritative preview layout instead of rebuilding it."""

    session_id, _preview_cache = _make_session()

    async def _submit_stub(
        func: object,
        piece_image_path: str,
        lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        with open(piece_path, "wb") as handle:
            handle.write(b"piece-3mf")
        return {
            "threemf_path": piece_path,
            "glb_path": None,
            "status_msg": "ok",
            "x_mirrored": False,
            "mirror_span_mm": 1.0,
        }

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        piece_slots: list[Any],
        output_path: str,
        preview_colors: dict[object, object] | None,
        slot_names: list[str] | None,
        slot_index_by_name: dict[str, int],
        printer_id: str,
        metadata_target: Any,
        nozzle_size: str = "0.4",
        device_profile_id: str | None = None,
        build_plate_id: str | None = None,
        overview_png_bytes: bytes | None = None,
        material_types: dict[str, str | None],
        external_spool_material: str | None,
        native_filament_profiles: dict[str, str],
        enable_wipe_tower_auto_placement: bool = True,
    ) -> str:
        with open(output_path, "wb") as handle:
            handle.write(b"combined-3mf")
        return output_path

    preview_body = {
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
    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)

    preview_response = client.post("/api/convert/puzzle-layout-preview", json=preview_body)
    assert preview_response.status_code == 200

    with patch("api.routers.converter.puzzle.build_puzzle_layout", side_effect=AssertionError("layout cache missed")), patch(
        "api.routers.converter.puzzle.assemble_puzzle_3mf",
        side_effect=_assemble_stub,
    ):
        generate_response = client.post(
            "/api/convert/generate-puzzle",
            json=_build_generate_body(session_id),
        )

    assert generate_response.status_code == 200


def test_generate_puzzle_rejects_unimplemented_back_label_engraving() -> None:
    """Puzzle generation should fail fast when back-label engraving is requested."""

    session_id, _preview_cache = _make_session()
    body = _build_generate_body(session_id)
    body["params"]["engrave_back_labels"] = True

    response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 422
    assert "not implemented yet" in response.json()["detail"]


def test_crop_piece_arrays_preserves_source_transparency_inside_piece_mask() -> None:
    """Puzzle crops should preserve alpha instead of turning transparent regions into white tiles."""

    source_rgba = np.zeros((90, 120, 4), dtype=np.uint8)
    matched_rgb = np.zeros((90, 120, 3), dtype=np.uint8)
    source_rgba[45:80, 60:110, :3] = (20, 80, 200)
    source_rgba[45:80, 60:110, 3] = 255
    matched_rgb[45:80, 60:110] = (20, 80, 200)

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=90,
            total_width_mm=80.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=3,
            cols=3,
            seed=5,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )
    source_transparent_inside_piece: np.ndarray | None = None
    source_opaque_inside_piece: np.ndarray | None = None
    piece_rgba: np.ndarray | None = None
    piece_matched: np.ndarray | None = None
    for candidate in layout.pieces:
        bbox_px, local_mask = rasterize_piece_mask(candidate)
        x0, y0, x1, y1 = bbox_px
        source_alpha_crop = source_rgba[y0:y1, x0:x1, 3]
        inside_piece = local_mask > 0
        candidate_source_transparent_inside = inside_piece & (source_alpha_crop == 0)
        candidate_source_opaque_inside = inside_piece & (source_alpha_crop > 0)
        if np.any(candidate_source_transparent_inside) and np.any(candidate_source_opaque_inside):
            _bbox_px, candidate_rgba, candidate_matched = _crop_piece_arrays(source_rgba, matched_rgb, candidate)
            piece_rgba = candidate_rgba
            piece_matched = candidate_matched
            source_transparent_inside_piece = candidate_source_transparent_inside
            source_opaque_inside_piece = candidate_source_opaque_inside
            break

    assert piece_rgba is not None
    assert piece_matched is not None
    assert source_transparent_inside_piece is not None
    assert source_opaque_inside_piece is not None

    assert np.any(source_transparent_inside_piece)
    assert np.any(source_opaque_inside_piece)
    assert np.all(piece_rgba[source_transparent_inside_piece] == 0)
    assert np.all(piece_matched[source_transparent_inside_piece] == 0)
    assert np.any(piece_rgba[..., 3][source_opaque_inside_piece] > 0)
    assert np.any(piece_matched[source_opaque_inside_piece] != 0)


def test_generate_puzzle_filters_fully_transparent_pieces_during_layout() -> None:
    """Transparent-only tiles should be removed by layout resolution before worker submission."""

    session_id, preview_cache = _make_session()
    preview_rgba = np.array(preview_cache["preview_rgba"], copy=True)
    preview_rgba[:, :90] = 0
    matched_rgb = np.array(preview_cache["matched_rgb"], copy=True)
    matched_rgb[:, :90] = 0
    preview_cache["preview_rgba"] = preview_rgba
    preview_cache["matched_rgb"] = matched_rgb
    preview_cache["mask_solid"] = preview_rgba[..., 3] > 0
    _test_store.put(session_id, "preview_cache", preview_cache)

    submitted_params: list[dict[str, Any]] = []

    async def _submit_stub(
        func: object,
        piece_image_path: str,
        lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        submitted_params.append(worker_params)
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        with open(piece_path, "wb") as handle:
            handle.write(b"piece-3mf")
        return {
            "threemf_path": piece_path,
            "glb_path": None,
            "status_msg": "ok",
            "x_mirrored": False,
            "mirror_span_mm": 1.0,
        }

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        piece_slots: list[Any],
        output_path: str,
        preview_colors: dict[object, object] | None,
        slot_names: list[str] | None,
        slot_index_by_name: dict[str, int],
        printer_id: str,
        metadata_target: Any,
        nozzle_size: str = "0.4",
        device_profile_id: str | None = None,
        build_plate_id: str | None = None,
        overview_png_bytes: bytes | None = None,
        material_types: dict[str, str | None],
        external_spool_material: str | None,
        native_filament_profiles: dict[str, str],
        enable_wipe_tower_auto_placement: bool = True,
    ) -> str:
        with open(output_path, "wb") as handle:
            handle.write(b"combined-3mf")
        return output_path

    body = _build_generate_body(session_id)
    body["params"]["rows"] = 1
    body["params"]["cols"] = 2
    body["params"]["target_piece_count"] = 2

    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)

    with patch(
        "api.routers.converter.puzzle.assemble_puzzle_3mf",
        side_effect=_assemble_stub,
    ):
        response = client.post(
            "/api/convert/generate-puzzle",
            json=body,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["piece_count"] == 1
    assert len(submitted_params) == 1
    assert not any("Skipped" in warning for warning in payload["warnings"])


def test_worker_generate_model_handles_tiny_piece_with_large_quantize_request() -> None:
    """Tiny puzzle-piece rasters should not fail when quantize_colors exceeds pixel count.

    This reproduces the reported SVG+puzzle failure mode at the real worker/model
    path: the rasterized piece is tiny, but the request still carries the normal
    UI quantization value (e.g. 48).
    """

    fd_image, image_path_str = tempfile.mkstemp(prefix="tiny_piece_worker_", suffix=".png", dir=str(Path.cwd()))
    os.close(fd_image)
    fd_lut, lut_path_str = tempfile.mkstemp(prefix="tiny_piece_worker_", suffix=".npz", dir=str(Path.cwd()))
    os.close(fd_lut)
    image_path = Path(image_path_str)
    lut_path = Path(lut_path_str)

    rgb = np.array(
        [
            [[255, 0, 0], [0, 255, 0]],
            [[0, 0, 255], [255, 255, 0]],
        ],
        dtype=np.uint8,
    )
    Image.fromarray(rgb).save(image_path)

    lut_rgb = np.array(
        [
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
            [255, 255, 0],
        ],
        dtype=np.uint8,
    )
    ref_stacks = np.array(
        [
            [0, 0, 0, 0, 0],
            [1, 1, 1, 1, 1],
            [2, 2, 2, 2, 2],
            [3, 3, 3, 3, 3],
        ],
        dtype=np.int16,
    )
    np.savez(lut_path, rgb=lut_rgb, stacks=ref_stacks)

    params = {
        "target_width_mm": 10.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color (RYBW)",
        "add_loop": False,
        "loop_width": 4.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_pos": None,
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "quantize_colors": 48,
        "enable_cleanup": True,
        "hue_weight": 0.0,
        "chroma_gate": 0.0,
        "separate_backing": False,
        "enable_relief": False,
        "height_mode": "color",
        "color_height_map": None,
        "heightmap_max_height": 3.0,
        "enable_outline": False,
        "outline_width": 2.0,
        "enable_cloisonne": False,
        "wire_width_mm": 0.4,
        "wire_height_mm": 0.4,
        "free_color_set": set(),
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "matched_rgb_path": None,
        "loop_angle": 0.0,
        "loop_offset_x": 0.0,
        "loop_offset_y": 0.0,
        "loop_position_preset": "top-center",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.2",
        "relief_global_max_height": None,
    }

    with patch("core.pipeline.s09_export_3mf.export_scene_with_bambu_metadata", return_value=None), patch(
        "core.pipeline.s11_glb_preview.generate_segmented_glb",
        return_value=None,
    ):
        result = worker_generate_model(str(image_path), str(lut_path), params)

    try:
        assert isinstance(result["threemf_path"], str)
        assert result["threemf_path"].endswith(".3mf")
        assert isinstance(result["status_msg"], str)
        assert result["status_msg"]
        assert result["x_mirrored"] is True
        assert result["mirror_span_mm"] == 10.0
    finally:
        for path in (image_path, lut_path):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass


def test_worker_generate_model_preserves_svg_puzzle_piece_dimensions_for_matched_override() -> None:
    """SVG puzzle pieces should keep their exact crop dimensions in the worker.

    The puzzle route passes ``target_width_mm`` using piece metadata, and some
    SVG-derived widths are represented as values like ``7.799999999999997``.
    If the worker truncates instead of rounding, the piece shrinks by one pixel,
    ``matched_rgb_path`` is ignored due to a shape mismatch, and thin SVG detail
    can disappear completely.
    """

    with tempfile.TemporaryDirectory(prefix="svg_puzzle_piece_") as temp_dir:
        tmp_path = Path(temp_dir)
        svg_path = tmp_path / "thin.svg"
        svg_path.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80">'
                '<path d="M9.5 10.9 L10.5 9.1 L110.5 69.1 L109.5 70.9 Z" fill="#ff0000"/>'
                '<path d="M10.5 70.9 L9.5 69.1 L109.5 9.1 L110.5 10.9 Z" fill="#0000ff"/>'
                '<circle cx="60" cy="40" r="6" fill="#00ff00"/>'
                "</svg>"
            ),
            encoding="utf-8",
        )

        lut_path = tmp_path / "test_lut.npz"
        lut_rgb = np.array(
            [
                [255, 0, 0],
                [0, 255, 0],
                [0, 0, 255],
                [255, 255, 255],
            ],
            dtype=np.uint8,
        )
        ref_stacks = np.array(
            [
                [0, 0, 0, 0, 0],
                [1, 1, 1, 1, 1],
                [2, 2, 2, 2, 2],
                [3, 3, 3, 3, 3],
            ],
            dtype=np.int16,
        )
        np.savez(lut_path, rgb=lut_rgb, stacks=ref_stacks)

        _preview_img, cache, status = generate_preview_cached(
            image_path=str(svg_path),
            lut_path=str(lut_path),
            target_width_mm=120.0,
            color_mode="4-Color (RYBW)",
            modeling_mode=ModelingMode.VECTOR,
            quantize_colors=48,
            enable_cleanup=True,
            is_dark=False,
            hue_weight=0.0,
            chroma_gate=0.0,
        )
        assert status.startswith("[OK]")

        layout = build_puzzle_layout(
            PuzzleLayoutConfig(
                width_px=cache["matched_rgb"].shape[1],
                height_px=cache["matched_rgb"].shape[0],
                total_width_mm=120.0,
                total_height_mm=80.0,
                style="regular",
                sizing_mode="grid",
                rows=3,
                cols=6,
                target_piece_count=18,
                seed=7,
                connector_style="classic",
                irregularity_strength=0.35,
                min_neck_width_mm=1.2,
                solid_mask=cache["mask_solid"],
            )
        )

        piece = next(
            candidate
            for candidate in layout.pieces
            if int((candidate.bbox_mm[2] - candidate.bbox_mm[0]) * 10) != (candidate.bbox_px[2] - candidate.bbox_px[0])
        )
        _bbox_px, piece_rgba, piece_matched = _crop_piece_arrays(cache["preview_rgba"], cache["matched_rgb"], piece)
        assert piece_matched.shape[1] > 0

        piece_image_path = tmp_path / f"{piece.label}.png"
        piece_matched_path = tmp_path / f"{piece.label}.npy"
        piece_boundary_path = tmp_path / f"{piece.label}.json"
        Image.fromarray(piece_rgba).save(piece_image_path)
        np.save(piece_matched_path, piece_matched)
        piece_boundary_path.write_text(
            json.dumps(export_piece_boundary_geometry(piece), ensure_ascii=False),
            encoding="utf-8",
        )

        params = {
            "target_width_mm": piece.bbox_mm[2] - piece.bbox_mm[0],
            "spacer_thick": 1.2,
            "structure_mode": "Double-sided",
            "color_mode": "4-Color (RYBW)",
            "add_loop": False,
            "loop_width": 4.0,
            "loop_length": 8.0,
            "loop_hole": 2.5,
            "loop_pos": None,
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "quantize_colors": 48,
            "enable_cleanup": True,
            "hue_weight": 0.0,
            "chroma_gate": 0.0,
            "separate_backing": False,
            "enable_relief": False,
            "height_mode": "color",
            "color_height_map": None,
            "heightmap_max_height": 3.0,
            "enable_outline": False,
            "outline_width": 2.0,
            "enable_cloisonne": False,
            "wire_width_mm": 0.4,
            "wire_height_mm": 0.4,
            "free_color_set": set(),
            "enable_coating": False,
            "coating_height_mm": 0.08,
            "matched_rgb_path": str(piece_matched_path),
            "piece_boundary_geometry_path": str(piece_boundary_path),
            "disable_material_dilation": True,
            "loop_angle": 0.0,
            "loop_offset_x": 0.0,
            "loop_offset_y": 0.0,
            "loop_position_preset": "top-center",
            "printer_id": "bambu-h2d",
            "slicer": "BambuStudio",
            "nozzle_size": "0.2",
            "relief_global_max_height": None,
        }

        with patch("core.pipeline.s09_export_3mf.export_scene_with_bambu_metadata", return_value=None), patch(
            "core.pipeline.s11_glb_preview.generate_segmented_glb",
            return_value=None,
        ), patch("core.pipeline.s03_color_replacement._log.warning") as warning_mock:
            result = worker_generate_model(str(piece_image_path), str(lut_path), params)

        assert isinstance(result["threemf_path"], str)
        assert result["threemf_path"].endswith(".3mf")
        assert result["x_mirrored"] is False
        assert np.isclose(
            result["mirror_span_mm"],
            round(float(params["target_width_mm"]) * 10.0) / 10.0,
        )
        assert not any("matched_rgb_path shape" in str(call.args[0]) for call in warning_mock.call_args_list)
