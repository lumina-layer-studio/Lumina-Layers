"""Batch outlines must survive the API, preview, layout and native 3MF export."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterator
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from fastapi.testclient import TestClient
from PIL import Image
import pytest
import trimesh

from api.session_store import SessionStore
from config import PrinterConfig


@pytest.fixture
def batch_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, SessionStore]]:
    from api.app import create_app
    from api.dependencies import get_file_registry, get_session_store, get_worker_pool
    from api.file_registry import FileRegistry
    from core import material_lut_provider, material_lut_synthesis
    from core.pipeline import s09_export_3mf, s11_glb_preview

    for name in ("MODELS_DIR", "OUTPUT_DIR", "TEMP_DIR"):
        monkeypatch.setattr(f"config.{name}", str(tmp_path))
    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(s11_glb_preview, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("LUMINA_RUNTIME_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(material_lut_provider, "MATERIALS_DIR", str(tmp_path))
    monkeypatch.setattr(material_lut_synthesis, "MATERIALS_DIR", str(tmp_path))
    for name, level in (("White", 1.0), ("Black", 0.01)):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "material.json").write_text(json.dumps({
            "material_name": name, "material_type": "PLA",
        }), encoding="utf-8")
        (directory / "stage_A_parameters.json").write_text(json.dumps({
            "parameters": {
                "channels": [{"E": [level] * 3, "k": [1.0] * 3}],
                "substrates": [{"substrate_id": "white", "C0": [1.0] * 3}],
            },
        }), encoding="utf-8")

    class InlinePool:
        """Keep generation and export real; replace process scheduling only."""
        max_workers = 1
        is_alive = True

        async def submit(self, function: Callable[..., dict], *args: object) -> dict:
            return function(*args)

    app = create_app()
    registry, store = FileRegistry(), SessionStore()
    app.dependency_overrides[get_worker_pool] = lambda: InlinePool()
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_session_store] = lambda: store
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, store


@pytest.mark.parametrize("source", ["lut", "material_archive"])
@pytest.mark.parametrize(("extension", "mode", "transparent"), [
    ("png", "high-fidelity", False), ("png", "high-fidelity", True),
    ("png", "pixel", False), ("svg", "high-fidelity", False), ("svg", "vector", False),
])
@pytest.mark.parametrize("enabled", [False, True])
def test_batch_outline_matches_preview_and_download(
    batch_client: tuple[TestClient, SessionStore], tmp_path: Path,
    source: str, extension: str, mode: str, transparent: bool, enabled: bool,
) -> None:
    client, store = batch_client
    if extension == "svg":
        content_type = "image/svg+xml"
        image = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="30"><rect width="40" height="30" fill="white"/></svg>'
    else:
        content_type = "image/png"
        buffer = io.BytesIO()
        artwork = Image.new(
            "RGBA" if transparent else "RGB", (40, 30),
            (0, 0, 0, 0) if transparent else "white",
        )
        if transparent:
            # Asymmetric silhouette with transparent margins, not a canvas rectangle.
            artwork.paste("white", (10, 5, 20, 25))
            artwork.paste("white", (10, 15, 35, 25))
        artwork.save(buffer, format="PNG")
        image = buffer.getvalue()
    data = {
        "lut_name": "bambulab - bambulab_pla_basic_rybw",
        "target_width_mm": "20", "spacer_thick": "1.2", "modeling_mode": mode,
        "structure_mode": "Single-sided", "enable_cleanup": "false",
        "enable_wipe_tower_auto_placement": "false",
        "native_filament_profiles": json.dumps({
            name: "Bambu PLA Basic @BBL H2D" for name in ("White", "Red", "Yellow", "Blue", "Black")
        }),
    }
    outline_width = 1.5 if transparent else 2.0
    # Omitting both fields exercises compatibility with existing batch clients.
    if enabled:
        data.update(enable_outline="true", outline_width=str(outline_width))
        if extension == "svg" and mode == "high-fidelity":
            data.update(enable_coating="true", coating_height_mm="0.08")
    if source == "material_archive":
        data.update(material_source=source, selected_materials=json.dumps(["Black", "White"]),
                    material_backing_material_index="1")
    files = [("images", (f"image-{i}.{extension}", image, content_type)) for i in range(2)]
    session_id = store.create()

    response = client.post("/api/convert/batch", data=data, files=files)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["status"] for item in payload["results"]] == ["success", "success"], payload
    expected_xy = [12.5, 10] if transparent else [20, 15]
    outline_expansion = 2 * outline_width
    if mode == "pixel" and source == "lut":
        # Pixel models and outline widths snap to the nozzle pitch.
        pitch = PrinterConfig.NOZZLE_WIDTH
        pixel_width = int(20 / pitch)
        expected_xy = [pixel_width * pitch, int(pixel_width * 30 / 40) * pitch]
        outline_expansion = 2 * round(outline_width / pitch) * pitch
    if enabled:
        expected_xy = [dimension + outline_expansion for dimension in expected_xy]
    # The native vector pipeline has no generated GLB without a reusable
    # session preview. Batch uploads currently have no such session.
    assert len(payload["preview_items"]) == (0 if mode == "vector" else 2)
    for item in payload["preview_items"]:
        assert [item["width_mm"], item["depth_mm"]] == pytest.approx(expected_xy, abs=0.1)
        preview = client.get(item["url"])
        assert preview.status_code == 200
        scene = trimesh.load_scene(io.BytesIO(preview.content), file_type="glb", process=False)
        # The viewer excludes this invisible alignment anchor from model bounds.
        for node in list(scene.graph.nodes_geometry):
            if node == "preview_canvas_bounds":
                scene.delete_geometry(scene.graph[node][1])
        assert scene.extents[:2] == pytest.approx(expected_xy, abs=0.1)
        assert ("Outline" in scene.geometry) is enabled
    if payload["preview_items"]:
        first, second = payload["preview_items"]
        assert second["tx_mm"] - first["tx_mm"] == pytest.approx(first["width_mm"] + 2)

    downloaded = client.get(payload["download_url"])
    assert downloaded.status_code == 200
    artifact = tmp_path / "downloaded.3mf"
    artifact.write_bytes(downloaded.content)
    merged = trimesh.load_scene(artifact, process=False)
    # Native SVG meshing includes a sub-0.1 mm expansion on each side.
    tolerance = 0.35 if mode == "vector" else 0.2
    assert merged.extents[:2] == pytest.approx([2 * expected_xy[0] + 2, expected_xy[1]], abs=tolerance)
    with zipfile.ZipFile(artifact) as archive:
        settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
        project = json.loads(archive.read("Metadata/project_settings.config"))
    outlines = [part for part in settings.findall(".//part") if any(
        meta.get("key") == "name" and meta.get("value") == "Outline" for meta in part.findall("metadata")
    )]
    assert len(outlines) == (2 if enabled else 0)
    for part in outlines:
        extruder = next(meta.get("value") for meta in part.findall("metadata") if meta.get("key") == "extruder")
        # Native exporters may deduplicate or add material slots. Check the
        # selected material identity, not a hard-coded extruder number.
        index = int(extruder) - 1
        assert project["filament_colour"][index].upper() == "#FFFFFF"
        assert project["filament_settings_id"][index] == "Bambu PLA Basic @BBL H2D"

    assert client.post("/api/session/close", json={"session_id": session_id}).status_code == 200
    assert client.get(payload["download_url"]).content == downloaded.content
