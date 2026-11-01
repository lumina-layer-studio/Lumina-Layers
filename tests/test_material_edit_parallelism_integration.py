"""Exercise the default synchronous edit budget through real HTTP routes."""

from __future__ import annotations

import io
import json
from contextlib import closing
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import hydrate_preview_cache
from api.routers.converter import preview, replace
from api.session_store import SessionStore
from config import ModelingMode
from core import material_dynamic_solver, material_lut_synthesis
from core.task_parallelism import resolve_task_parallelism_plan
from core.task_parallelism_runtime import current_demand_snapshot_path


class _InlinePreviewPool:
    async def submit_timed(self, function, *args, **kwargs):
        return function(*args), {}


@pytest.mark.parametrize("endpoint", ["replace-color", "replace-colors-batch"])
def test_default_synchronous_edit_uses_single_task_cpu_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, endpoint: str,
) -> None:
    """A lone edit uses available cores instead of four imagined outer jobs."""
    monkeypatch.delenv("LUMINA_MATERIAL_PARALLELISM", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "4")
    monkeypatch.setenv("LUMINA_RUNTIME_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(material_lut_synthesis, "MATERIALS_DIR", str(
        Path(__file__).parent / "fixtures" / "dynamic_material_materials"
    ))
    # GLB scheduling is independent of the synchronous colour solve.
    for module in (preview, replace):
        monkeypatch.setattr(module, "schedule_glb_build", lambda *args, **kwargs: "unused")
    app = create_app()
    store, registry = SessionStore(ttl=1800), FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = _InlinePreviewPool
    source = np.random.default_rng(276).integers(0, 256, (6, 8, 3), dtype=np.uint8)
    image = io.BytesIO()
    Image.fromarray(source).save(image, format="PNG")
    try:
        with closing(TestClient(app, raise_server_exceptions=False)) as client:
            response = client.post("/api/convert/preview", files={
                "image": ("colours.png", image.getvalue(), "image/png"),
            }, data={
                "target_width_mm": "8", "color_mode": "4-Color (RYBW)",
                "modeling_mode": ModelingMode.HIGH_FIDELITY.value, "quantize_colors": "48",
                "enable_cleanup": "false", "hue_weight": "0",
                "material_source": "material_archive",
                "selected_materials": json.dumps(["white", "red", "blue", "yellow"]),
                "material_layer_count": "7", "material_layer_height_mm": "0.08",
                "material_backing_material_index": "0",
                "material_dynamic_layer_count_enabled": "true",
                "material_min_layer_count": "5", "material_max_layer_count": "7",
                "material_delta_e00_tolerance": "0.5",
            })
            assert response.status_code == 200, response.text
            session_id = response.json()["session_id"]
            cache = hydrate_preview_cache(store.get(session_id)["preview_cache"])
            before = cache["matched_rgb"].copy()
            plans = []

            def capture_plan(workload, **kwargs):
                assert current_demand_snapshot_path() is None
                plan = resolve_task_parallelism_plan(workload, **kwargs, effective_cpu_capacity=4)
                plans.append(plan)
                return plan

            monkeypatch.setattr(material_dynamic_solver, "resolve_task_parallelism_plan", capture_plan)
            pair = {"selected_color": "#%02X%02X%02X" % tuple(before[0, 0]),
                    "replacement_color": "#E02080"}
            payload = pair if endpoint == "replace-color" else {"replacements": [pair]}
            response = client.post(f"/api/convert/{endpoint}", json={"session_id": session_id, **payload})
            assert response.status_code == 200, response.text
            assert plans
            assert all(plan.outer_demand == 1 and plan.workers == 4 for plan in plans)
            after = hydrate_preview_cache(store.get(session_id)["preview_cache"])
            assert np.any(after["matched_rgb"] != before)
            assert after["material_matrix"].shape == (*before.shape[:2], 7)
    finally:
        store.clear_all()
        registry.clear_all()
