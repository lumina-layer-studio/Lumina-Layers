"""Exercise SVG export when the running worker pool's temp directory is removed."""

from __future__ import annotations

from functools import partial
from io import BytesIO
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.routers.converter import generate as generate_router, preview as preview_router
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import worker_generate_model
from core.task_parallelism_runtime import (
    current_worker_lease_path,
    read_worker_leases,
    worker_lease_lock_path,
)


def _generate_after_temp_cleanup(image_path: str, lut_path: str, params: dict) -> dict:
    from core import vector_material_meshing
    from core.pipeline import s09_export_3mf, s11_glb_preview

    lease_path = current_worker_lease_path()
    assert lease_path is not None and lease_path.parent.name.startswith("lumina-parallelism-")
    assert (lease_path.parent / "demand.json").is_file()
    # Delete after the pool publishes demand, so that only the lock path can
    # repair the directory before the SVG stage reserves its workers.
    shutil.rmtree(lease_path.parent)
    output_dir = str(Path(lut_path).parent)
    plan = partial(vector_material_meshing.resolve_task_parallelism_plan, effective_cpu_capacity=2)
    with (
        patch.object(vector_material_meshing, "resolve_task_parallelism_plan", plan),
        patch.object(s09_export_3mf, "MODELS_DIR", output_dir),
        patch.object(s11_glb_preview, "OUTPUT_DIR", output_dir),
    ):
        return worker_generate_model(image_path, lut_path, params)


def test_svg_generate_recovers_after_worker_coordination_directory_is_pruned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
        '<path fill="#dc143c" d="M0 0H20V20H0Z"/>'
        '<path fill="#0064f0" d="M20 0H40V20H20Z"/></svg>'
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
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "2")
    monkeypatch.setattr(preview_router.LUTManager, "get_lut_path", lambda _name: str(lut))
    monkeypatch.setattr(generate_router, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(generate_router, "worker_generate_model", _generate_after_temp_cleanup)

    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = WorkerPoolManager(max_workers=1)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool
    client = TestClient(app, raise_server_exceptions=False)
    pool.start()
    snapshot = pool.demand_snapshot_path
    assert snapshot is not None
    try:
        preview = client.post(
            "/api/convert/preview",
            files={"image": ("two-colors.svg", svg, "image/svg+xml")},
            data={
                "lut_name": "parallelism-recovery",
                "target_width_mm": "40",
                "modeling_mode": "vector",
                "color_mode": "4-Color (RYBW)",
            },
        )
        assert preview.status_code == 200, preview.text
        generated = client.post("/api/convert/generate", json={
            "session_id": preview.json()["session_id"],
            "params": {
                "lut_name": "parallelism-recovery", "target_width_mm": 40,
                "modeling_mode": "vector", "color_mode": "4-Color (RYBW)",
                "spacer_thick": 1.2, "layer_height_mm": 0.08, "color_layers": 5,
                "printer_id": "bambu-a1", "enable_wipe_tower_auto_placement": False,
            },
        })
        assert generated.status_code == 200, generated.text

        lease = snapshot.with_name("workers.json")
        assert worker_lease_lock_path(lease).is_file()
        assert lease.is_file() and read_worker_leases(lease) == ({}, False)
        assert json.loads(snapshot.read_text(encoding="utf-8"))["outstanding"] == 0
        download = client.get(generated.json()["download_url"])
        assert download.status_code == 200, download.text
        with ZipFile(BytesIO(download.content)) as archive:
            assert archive.testzip() is None
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
            assert root.findall("{*}build/{*}item")
            assert any(
                ET.fromstring(archive.read(name)).find(".//{*}triangle") is not None
                for name in archive.namelist() if name.endswith(".model")
            )
    finally:
        pool.shutdown(wait=True)
        store.clear_all()
        registry.clear_all()
        client.close()
