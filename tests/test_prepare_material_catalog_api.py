import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.dependencies import get_worker_pool
from api.project_resources import ProjectResources
from api.routers.converter import preview


@pytest.mark.parametrize("override", [
    {"selected_materials": ["red", "red"]},
    {"material_min_layer_count": 10, "material_max_layer_count": 5},
    {"material_backing_material_index": 2},
    {"material_layer_height_mm": 0},
])
def test_invalid_palette_rejected_before_scheduling(override: dict) -> None:
    app = FastAPI()
    app.include_router(preview.router)
    app.dependency_overrides[get_worker_pool] = lambda: None
    data = dict(selected_materials=["red", "white"], material_min_layer_count=5,
                material_max_layer_count=10, material_layer_height_mm=0.08)
    with TestClient(app) as client:
        response = client.post("/prepare-material-catalog", data={**data, **override})
    assert response.status_code == 422


def test_cancelled_request_keeps_project_materials_until_worker_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    embedded = root / "materials"
    embedded.mkdir()

    async def stage(_lut, _upload, names):
        assert names == ["red", "white"]
        return ProjectResources(str(root), None, str(embedded))

    monkeypatch.setattr(preview, "stage_project_resources", stage)

    async def run() -> None:
        started, finish = asyncio.Event(), asyncio.Event()

        class Pool:
            async def submit(self, worker, *args):
                assert worker is preview.worker_prepare_material_catalog
                assert args == (["red", "white"], 1, 0.08, 5, 9, str(embedded))
                started.set()
                await finish.wait()
                assert embedded.is_dir()
                return False

        request = asyncio.create_task(preview.prepare_material_catalog(
            ["red", "white"], 5, 9, 0.08, 1, None, Pool(),
        ))
        await asyncio.wait_for(started.wait(), timeout=3)
        request.cancel()
        await asyncio.sleep(0)
        assert embedded.is_dir()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert not root.exists()

    asyncio.run(run())
