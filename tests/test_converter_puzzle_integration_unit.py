"""Integration tests for converter puzzle router log canaries."""

from __future__ import annotations

import asyncio
import logging
import pickle
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import externalize_preview_cache
from api.schemas.converter import ConvertGenerateRequest
from api.routers.converter import puzzle as puzzle_router
from api.selection_state import RECIPE_OVERRIDE_APPLIED_MASKS_KEY
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from core.material_dynamic_solver import DynamicMaterialSolverError
from core.puzzle import PuzzlePiece


@pytest.fixture()
def puzzle_harness():
    """Create an isolated puzzle-router test client."""

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


def test_generate_puzzle_drains_failed_batch_and_tracks_successful_outputs(
    puzzle_harness, tmp_path,
) -> None:
    """A typed failure must not strand sibling outputs or launch later batches."""

    store = puzzle_harness["store"]
    pool = puzzle_harness["pool"]
    session_id = _seed_puzzle_generate_session(store, tmp_path)
    outputs = [tmp_path / "sibling.3mf", tmp_path / "sibling.glb"]

    async def submit_piece(_fn, image_path, _lut_path, _params):
        if Path(image_path).stem.split("_")[1] == "A1":
            raise DynamicMaterialSolverError("test solver failure")
        await asyncio.sleep(0.01)
        for path in outputs:
            path.write_bytes(b"sibling output")
        return {
            "threemf_path": str(outputs[0]),
            "glb_path": str(outputs[1]),
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
    assert all(path.exists() for path in outputs)
    store.close(session_id)
    assert all(not path.exists() for path in outputs)


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

    async def submit_piece(_fn, image_path, _lut_path, _params):
        nonlocal active_count
        active_count += 1
        if active_count == pool.max_workers:
            started.set()
        await release.wait()
        path = tmp_path / f"{Path(image_path).stem}.3mf"
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
    assert all(path.exists() for path in outputs)
    store.close(session_id)
    assert all(not path.exists() for path in outputs)


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
        captured_params: list[dict[str, object]] = []
        piece_index = 0

        async def _submit_stub(*args, **_kwargs) -> dict[str, object]:
            nonlocal piece_index
            piece_index += 1
            captured_params.append(args[3])
            path = tmp_path / f"dynamic-piece-{piece_index}.3mf"
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
        assert len(captured_params) == 4
        for params in captured_params:
            assert params["reuse_preview_analysis"] == "required"
            assert params["material_dynamic_layer_count_enabled"] is True
            assert params["material_max_layer_count"] == 6
            matched = np.load(params["matched_rgb_path"], allow_pickle=False)
            mask_solid = np.load(params["mask_solid_path"], allow_pickle=False)
            quantized = np.load(params["quantized_image_path"], allow_pickle=False)
            matrix = np.load(params["material_matrix_path"], allow_pickle=False)
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

        captured_params: list[dict[str, object]] = []
        piece_index = 0

        async def _submit_stub(*args, **_kwargs) -> dict[str, object]:
            nonlocal piece_index
            piece_index += 1
            captured_params.append(args[3])
            path = tmp_path / f"virtual-piece-{piece_index}.3mf"
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
        params_with_virtual_region = [
            params
            for params in captured_params
            if params.get("recipe_override_masks_path")
        ]
        assert params_with_virtual_region
        params = params_with_virtual_region[0]
        overrides = params["recipe_overrides"]
        assert isinstance(overrides, list)
        assert overrides[0]["virtual_materials"] == [
            {"name": "Custom Violet", "hex": "#8A2BE2"}
        ]
        with open(params["recipe_override_masks_path"], "rb") as handle:
            masks = pickle.load(handle)
        assert "virtual-region" in masks
        assert masks["virtual-region"].dtype == np.bool_
        assert masks["virtual-region"].shape == np.load(
            params["mask_solid_path"], allow_pickle=False
        ).shape

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
