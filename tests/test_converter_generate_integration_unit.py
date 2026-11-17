"""Integration tests for converter generate router log canaries."""

from __future__ import annotations

import io
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.routers.converter import generate as generate_router
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager


@pytest.fixture()
def generate_harness(monkeypatch):
    """Create an isolated generate-router test client."""

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit = AsyncMock()
    # These canary tests use sentinel worker output, not native file fixtures.
    monkeypatch.setattr(generate_router, "require_material_selection", lambda *args, **kwargs: {"materials": []})
    monkeypatch.setattr(generate_router, "read_wipe_tower_placement_warnings", lambda path: [])
    monkeypatch.setattr(generate_router, "_resolve_batch_plate_dimensions", lambda *args, **kwargs: (256.0, 256.0))

    test_app = FastAPI()
    test_app.include_router(generate_router.router, prefix="/api/convert")
    test_app.dependency_overrides[get_session_store] = lambda: store
    test_app.dependency_overrides[get_file_registry] = lambda: registry
    test_app.dependency_overrides[get_worker_pool] = lambda: pool

    with TestClient(test_app, raise_server_exceptions=False) as client:
        yield {"client": client, "store": store, "registry": registry, "pool": pool}

    store.clear_all()


def _capture_generate_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    logger = logging.getLogger("lumina.api.routers.converter.generate")
    logger.addHandler(caplog.handler)
    logger.propagate = False
    caplog.set_level(logging.INFO, logger=logger.name)
    return logger


def _seed_large_format_session(store: SessionStore, tmp_path) -> str:
    image_path = tmp_path / "poster.png"
    lut_path = tmp_path / "palette.npy"
    Image.fromarray(np.zeros((20, 20, 3), dtype=np.uint8)).save(image_path)
    np.save(lut_path, np.zeros((1,), dtype=np.uint8))

    session_id = store.create()
    store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 20,
            "target_h": 20,
            "target_width_mm": 20.0,
        },
    )
    store.put(session_id, "image_path", str(image_path))
    store.put(session_id, "source_basename", "poster")
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "replacement_regions", [])
    store.put(session_id, "free_color_set", set())
    return session_id


def _fake_3mf(tmp_path, name: str = "tile.3mf") -> str:
    path = tmp_path / name
    path.write_bytes(b"fake-3mf")
    return str(path)


def _fake_glb(tmp_path, name: str = "preview.glb") -> str:
    path = tmp_path / name
    path.write_bytes(b"fake-glb")
    return str(path)


def _fake_batch_sidecar(tmp_path, name: str = "batch.json") -> str:
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_filename": "batch.png",
                "xy_bbox_mm": {"width_mm": 30.0, "depth_mm": 20.0},
                "slots": [
                    {
                        "slot_id": 0,
                        "slot_name": "White",
                        "preview_color": "#ffffff",
                        "material_id": "GFL00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def _make_png_upload(name: str = "input.png") -> tuple[str, io.BytesIO, str]:
    image = Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return (name, buffer, "image/png")


class TestGenerateLargeFormatCanary:
    """Successful generate-large-format requests emit the structured done canary."""

    def test_generate_large_format_emits_contract_canary(
        self,
        generate_harness,
        tmp_path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = generate_harness["store"]
        pool: MagicMock = generate_harness["pool"]
        client: TestClient = generate_harness["client"]
        session_id = _seed_large_format_session(store, tmp_path)
        pool.submit = AsyncMock(
            return_value={
                "threemf_path": _fake_3mf(tmp_path),
                "glb_path": None,
                "status_msg": "ok",
            },
        )

        target_logger = _capture_generate_logger(caplog)
        try:
            response = client.post(
                "/api/convert/generate-large-format",
                json={
                    "session_id": session_id,
                    "params": {
                        "target_height_mm": 20.0,
                        "tile_width_mm": 20.0,
                        "tile_height_mm": 20.0,
                        "params": {
                            "lut_name": "test_lut",
                            "target_width_mm": 20.0,
                            "modeling_mode": "high-fidelity",
                            "color_mode": "4-Color (RYBW)",
                        },
                    },
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["tile_count"] == 1

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_generate_large_format_done"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.total_width_mm == 20.0
        assert record.total_height_mm == 20.0
        assert record.tile_width_mm == 20.0
        assert record.tile_height_mm == 20.0
        assert record.is_svg_vector is False
        assert record.prefer_raster_svg is False
        assert record.recipe_override_count == 0
        assert record.warning_count == 0


class TestBatchCanary:
    """Batch endpoint canary verifies merged-artifact logging contract."""

    def test_batch_emits_sessionless_contract_canary(
        self,
        generate_harness,
        tmp_path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        pool: MagicMock = generate_harness["pool"]
        client: TestClient = generate_harness["client"]
        pool.submit = AsyncMock(
            return_value={
                "threemf_path": _fake_3mf(tmp_path, "batch.3mf"),
                "preview_glb_path": _fake_glb(tmp_path, "batch.glb"),
                "metadata_sidecar_path": _fake_batch_sidecar(tmp_path),
                "xy_bbox_mm": (30.0, 20.0),
                "status_msg": "ok",
            },
        )

        target_logger = _capture_generate_logger(caplog)
        try:
            with (
                patch(
                    "api.routers.converter.generate.LUTManager.get_lut_path",
                    return_value=str(tmp_path / "palette.npy"),
                ),
                patch(
                    "api.routers.converter.generate.ensure_png_tempfile",
                    new=AsyncMock(return_value=str(tmp_path / "uploaded.png")),
                ),
                patch(
                    "api.routers.converter.generate.MergedBambu3MFWriter.write",
                    side_effect=lambda _items, output_path, **_kwargs: output_path.write_bytes(
                        b"fake-merged-3mf"
                    ),
                ),
            ):
                response = client.post(
                    "/api/convert/batch",
                    files=[("images", _make_png_upload("batch.png"))],
                    data={
                        "lut_name": "test_lut",
                        "color_mode": "4-Color (RYBW)",
                        "modeling_mode": "high-fidelity",
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["results"][0]["status"] == "success"

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "batch_merge_3mf_done"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert isinstance(record.session_id, str)
        assert len(record.session_id) == 32
        assert record.model_count == 1
        assert record.success_count == 1
        assert record.failure_count == 0
        assert record.exceeds_plate is False
