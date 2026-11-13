"""Batch placement must describe the exported assembly consumed by the merger."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pytest
import trimesh
from PIL import Image

from api.workers.converter_workers import worker_batch_convert_item
from core.batch_layout import XYBBox, layout_shelf_by_row
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata
from utils.merged_bambu_3mf_writer import MaterialSlot, MergedBambu3MFWriter, MergedItem


def _source_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    image_path = tmp_path / "artwork.png"
    Image.new("RGB", (40, 30), "white").save(image_path)
    scene = trimesh.Scene()
    artwork = trimesh.creation.box(extents=[10, 10, 2])
    artwork.metadata["bambu_material_name"] = "Black"
    scene.add_geometry(artwork, geom_name="Black")
    # An auxiliary component extends beyond the artwork footprint.
    auxiliary = trimesh.creation.box(extents=[8, 8, 1])
    auxiliary.apply_translation([12, 0, 0])
    auxiliary.metadata["bambu_material_name"] = "White"
    scene.add_geometry(auxiliary, geom_name="White")
    threemf_path = tmp_path / "converted.3mf"
    export_scene_with_bambu_metadata(
        scene=scene, output_path=str(threemf_path), slot_names=["Black", "White"],
        preview_colors={"Black": (0, 0, 0, 255), "White": (255, 255, 255, 255)},
        settings={}, color_mode="4-Color", enable_wipe_tower_auto_placement=False,
    )
    glb_path = tmp_path / "converted.glb"
    scene.export(glb_path)
    return image_path, threemf_path, glb_path


def _set_component_transform(path: Path, transform: str) -> None:
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    root = ET.fromstring(members["3D/3dmodel.model"])
    for component in root.findall(".//{*}component"):
        component.set("transform", transform)
    members["3D/3dmodel.model"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def _run_worker(image_path: Path, threemf_path: Path, glb_path: Path) -> dict:
    # Only conversion is replaced: source 3MF, worker postprocessing, layout,
    # native merged export and the independent Trimesh reader are real.
    with patch("core.converter.convert_image_to_3d", return_value=(
        str(threemf_path), str(glb_path), None, "Converted", None,
    )):
        return worker_batch_convert_item(
            str(image_path), "unused.npy", 80, 1.2, "Single-sided", "4-Color (RYBW)",
            "high-fidelity", 5, 0.08, 4, False, "batch-geometry-",
            enable_wipe_tower_auto_placement=False,
        )


@pytest.mark.parametrize(("transform", "expected_xy"), [
    ("", (21, 10)),
    (" \t\n ", (21, 10)),
    ("1 0 0 0 1 0 0 0 1 20 10 0", (21, 10)),
    # 3MF uses row vectors: x'=-y+20, y'=2x+10. This is deliberately
    # asymmetric so transposing the linear transform changes both extents.
    ("0 2 0 -1 0 0 0 0 1 20 10 0", (10, 42)),
    ("\t-1e0 0 0\n0 1e0 0 0 0 1 2e1 1e1 0 ", (21, 10)),
    ("1 0 0 0.5 1 0 0 0 1 20 10 0", (25.5, 10)),
])
def test_batch_uses_complete_exported_geometry_for_placement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transform: str, expected_xy: tuple[float, float],
) -> None:
    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
    image_path, source, glb = _source_artifacts(tmp_path)
    _set_component_transform(source, transform)
    if transform.strip():
        assert trimesh.load_scene(source, process=False).extents[:2] == pytest.approx(expected_xy)
    from utils.fatcat_metadata import read_source_metadata
    source_slots = read_source_metadata(source)["slots"]

    result = _run_worker(image_path, source, glb)

    assert result["xy_bbox_mm"] == pytest.approx(expected_xy)
    sidecar = json.loads(Path(result["metadata_sidecar_path"]).read_text(encoding="utf-8"))
    assert sidecar["slots"] == source_slots
    layout = layout_shelf_by_row([XYBBox(*result["xy_bbox_mm"])] * 2, 350, 320)
    items = [MergedItem(
        image_path.name, Path(result["threemf_path"]),
        tuple(MaterialSlot(**slot) for slot in sidecar["slots"]), p.tx_mm, p.ty_mm,
    ) for p in layout.placements]
    merged_path = tmp_path / "merged.3mf"
    MergedBambu3MFWriter().write(
        items, merged_path, plate_width_mm=350, plate_depth_mm=320,
        enable_wipe_tower_auto_placement=False,
    )
    # Trimesh applies the emitted build and component transforms independently.
    scene = trimesh.load_scene(merged_path, process=False)
    assert scene.bounds[0, :2] == pytest.approx([
        layout.placements[0].tx_mm, layout.placements[0].ty_mm,
    ], abs=1e-5)
    assert scene.extents[:2] == pytest.approx([2 * expected_xy[0] + 2, expected_xy[1]], abs=1e-5)


@pytest.mark.parametrize("transform", [
    "invalid", "bad 0 0 0 1 0 0 0 1 0 0 0", "nan 0 0 0 1 0 0 0 1 0 0 0",
    "1 0 0 0 inf 0 0 0 1 0 0 0", "0 0 0 0 0 0 0 0 0 0 0 0",
])
def test_unreadable_export_fails_only_its_batch_item_and_cleans_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transform: str,
) -> None:
    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
    image_path, source, glb = _source_artifacts(tmp_path)
    _set_component_transform(source, transform)
    other_download = tmp_path / "existing-final.3mf"
    other_download.write_bytes(b"previous successful download")

    result = _run_worker(image_path, source, glb)

    assert result["threemf_path"] is None
    assert result["preview_glb_path"] is None
    assert result["metadata_sidecar_path"] is None
    assert result["xy_bbox_mm"] == (0.0, 0.0)
    assert "footprint" in result["status_msg"].lower()
    assert not source.exists()
    assert not glb.exists()
    assert not list(tmp_path.glob("batch-geometry-*"))
    assert other_download.read_bytes() == b"previous successful download"


def test_merge_places_rotated_scaled_components_at_requested_minimum(tmp_path: Path) -> None:
    _image, source, _glb = _source_artifacts(tmp_path)
    _set_component_transform(source, "0 2 0 -1 0 0 0 0 1 20 10 0")
    from utils.fatcat_metadata import read_source_metadata
    slots = tuple(MaterialSlot(**slot) for slot in read_source_metadata(source)["slots"])
    merged_path = tmp_path / "merged.3mf"
    MergedBambu3MFWriter().write(
        [MergedItem("transformed.svg", source, slots, 100, 50)], merged_path,
        plate_width_mm=350, plate_depth_mm=320, enable_wipe_tower_auto_placement=False,
    )

    scene = trimesh.load_scene(merged_path, process=False)
    assert scene.bounds[0, :2] == pytest.approx([100, 50], abs=1e-5)
    assert scene.extents[:2] == pytest.approx([10, 42], abs=1e-5)


@pytest.mark.parametrize(("image_kind", "mode", "color_mode", "source"), [
    ("margined-svg", "high-fidelity", "4-Color (RYBW)", "lut"),
    ("margined-svg", "pixel", "4-Color (RYBW)", "lut"),
    ("margined-svg", "vector", "4-Color (RYBW)", "lut"),
    ("translucent-svg", "vector", "5-Color Extended", "lut"),
    ("full-svg", "high-fidelity", "4-Color (RYBW)", "lut"),
    ("transparent-png", "high-fidelity", "4-Color (RYBW)", "lut"),
    ("margined-svg", "high-fidelity", "4-Color (RYBW)", "material_archive"),
])
def test_real_batch_footprint_matches_export_across_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    image_kind: str, mode: str, color_mode: str, source: str,
) -> None:
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

    extended = color_mode == "5-Color Extended"
    lut_path = tmp_path / "white.npy"
    np.save(lut_path, np.full((2468 if extended else 1024, 3), 255, dtype=np.uint8))
    if image_kind == "transparent-png":
        image_path = tmp_path / "image.png"
        image = Image.new("RGBA", (100, 80))
        image.paste((255, 255, 255, 255), (25, 20, 75, 60))
        image.save(image_path)
    else:
        image_path = tmp_path / "image.svg"
        x, y, width, height = (0, 0, 100, 80) if image_kind == "full-svg" else (25, 20, 50, 40)
        opacity = ' fill-opacity="0.5"' if image_kind == "translucent-svg" else ""
        image_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80" viewBox="0 0 100 80">'
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="white"{opacity}/></svg>',
            encoding="utf-8",
        )
    result = worker_batch_convert_item(
        str(image_path), str(lut_path), 20, 1.2, "Single-sided", color_mode,
        mode, 6 if extended else 5, 0.08, 4, False, "real-geometry-",
        material_source=source, selected_materials=["White", "Black"] if source == "material_archive" else None,
        enable_wipe_tower_auto_placement=False,
    )

    assert result["threemf_path"], result["status_msg"]
    actual = trimesh.load_scene(result["threemf_path"], process=False).extents[:2]
    assert result["xy_bbox_mm"] == pytest.approx(actual, abs=1e-5)
    if image_kind == "transparent-png":
        assert actual == pytest.approx([10, 8], abs=1e-5)
    elif mode == "vector" and not extended:
        # Native meshing can add a narrow outline; it retains canvas scale.
        assert actual == pytest.approx([10, 8], abs=0.1)
    else:
        assert actual[0] > 19


@pytest.mark.parametrize("external_spool", [None, "Red"])
def test_api_footprint_failure_keeps_successful_download_after_session_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, external_spool: str | None,
) -> None:
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_file_registry, get_session_store, get_worker_pool
    from api.file_registry import FileRegistry
    from api.session_store import SessionStore
    from core.pipeline import s09_export_3mf, s11_glb_preview
    from utils import merged_bambu_3mf_writer

    for name in ("MODELS_DIR", "OUTPUT_DIR", "TEMP_DIR"):
        monkeypatch.setattr(f"config.{name}", str(tmp_path))
    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(s11_glb_preview, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("LUMINA_RUNTIME_CACHE_DIR", str(tmp_path / "cache"))

    class InlinePool:
        """Run the real worker in process so only inspection can be faulted."""
        max_workers = 1
        is_alive = True

        async def submit(self, function, *args):
            return function(*args)

    registry, store = FileRegistry(), SessionStore()
    monkeypatch.setitem(app.dependency_overrides, get_worker_pool, lambda: InlinePool())
    monkeypatch.setitem(app.dependency_overrides, get_file_registry, lambda: registry)
    monkeypatch.setitem(app.dependency_overrides, get_session_store, lambda: store)
    inspection = merged_bambu_3mf_writer.read_merge_source_info
    failure_count = 1
    failed_paths: list[Path] = []

    def failing_inspection(path, **kwargs):
        nonlocal failure_count
        if failure_count:
            failure_count -= 1
            failed_paths.append(Path(path))
            raise RuntimeError("injected unreadable batch footprint")
        return inspection(path, **kwargs)

    monkeypatch.setattr(merged_bambu_3mf_writer, "read_merge_source_info", failing_inspection)
    image = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80"><rect x="25" y="20" width="50" height="40" fill="white"/></svg>'
    data = {
        "lut_name": "bambulab - bambulab_pla_basic_rybw", "target_width_mm": "20",
        "modeling_mode": "high-fidelity", "structure_mode": "Single-sided",
        "enable_wipe_tower_auto_placement": "false",
        "native_filament_profiles": json.dumps({
            name: "Bambu PLA Basic @BBL H2D" for name in ("White", "Red", "Yellow", "Blue")
        }),
    }
    if external_spool is not None:
        data.update(
            printer_id="bambu-lab-x2d", external_spool_material=external_spool,
            native_filament_profiles=json.dumps(dict.fromkeys(
                ["White", "Red", "Yellow", "Blue"], "Bambu PLA Basic @BBL X2D 0.4 nozzle",
            )),
        )
    files = [("images", (f"image-{i}.svg", image, "image/svg+xml")) for i in range(2)]
    client = TestClient(app, raise_server_exceptions=False)
    session_id = store.create()

    partial = client.post("/api/convert/batch", data=data, files=files)
    assert partial.status_code == 200, partial.text
    assert [item["status"] for item in partial.json()["results"]] == ["failed", "success"]
    assert "injected" not in partial.text
    download_url = partial.json()["download_url"]
    downloaded = client.get(download_url)
    assert downloaded.status_code == 200
    artifact = tmp_path / "downloaded.3mf"
    artifact.write_bytes(downloaded.content)
    if external_spool is not None:
        from xml.etree import ElementTree as ET
        from zipfile import ZipFile

        with ZipFile(artifact) as package:
            root = ET.fromstring(package.read("Metadata/model_settings.config"))
            assert root.find("plate/metadata[@key='filament_maps']").get("value") == "1 2 1 1"
            assert root.find("plate/metadata[@key='filament_map_mode']").get("value") == "Manual"
    assert 19 < trimesh.load_scene(artifact, process=False).extents[0] <= 20

    failure_count = 2
    failed = client.post("/api/convert/batch", data=data, files=files)
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"
    assert failed.json()["download_url"] is None
    assert [item["status"] for item in failed.json()["results"]] == ["failed", "failed"]
    assert len(failed_paths) == 3
    assert all(not path.exists() for path in failed_paths)
    closed = client.post("/api/session/close", json={"session_id": session_id})
    assert closed.status_code == 200
    still_downloadable = client.get(download_url)
    assert still_downloadable.status_code == 200
    assert still_downloadable.content == downloaded.content


@pytest.mark.parametrize("failure", [MemoryError("bad allocation"), OSError("Failed to write to 3MF file")])
def test_failed_merge_preserves_completed_models_after_session_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception,
) -> None:
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_file_registry, get_session_store, get_worker_pool
    from api.file_registry import FileRegistry
    from api.session_store import SessionStore
    from core.pipeline import s09_export_3mf, s11_glb_preview

    for name in ("MODELS_DIR", "OUTPUT_DIR", "TEMP_DIR"):
        monkeypatch.setattr(f"config.{name}", str(tmp_path))
    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(s11_glb_preview, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("LUMINA_RUNTIME_CACHE_DIR", str(tmp_path / "cache"))

    class InlinePool:
        max_workers = 1
        is_alive = True

        async def submit(self, function, *args):
            return function(*args)

    registry, store = FileRegistry(), SessionStore()
    monkeypatch.setitem(app.dependency_overrides, get_worker_pool, lambda: InlinePool())
    monkeypatch.setitem(app.dependency_overrides, get_file_registry, lambda: registry)
    monkeypatch.setitem(app.dependency_overrides, get_session_store, lambda: store)
    failed_outputs: list[Path] = []

    def fail_merge(self, items, output_path, **kwargs):
        output_path.write_bytes(b"incomplete merged archive")
        failed_outputs.append(output_path)
        raise failure

    monkeypatch.setattr(MergedBambu3MFWriter, "write", fail_merge)
    image = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="8"><rect width="10" height="8" fill="white"/></svg>'
    with TestClient(app, raise_server_exceptions=False) as client:
        session_id = store.create()
        response = client.post("/api/convert/batch", data={
            "lut_name": "bambulab - bambulab_pla_basic_rybw", "target_width_mm": "10",
            "enable_wipe_tower_auto_placement": "false",
        }, files=[("images", (f"art-{i}.svg", image, "image/svg+xml")) for i in range(2)])
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "partial"
        assert data["download_url"] is None
        assert [warning["code"] for warning in data["warnings"]] == ["merge-unavailable"]
        urls = [item["download_url"] for item in data["results"]]
        assert len(set(urls)) == 2
        assert client.post("/api/session/close", json={"session_id": session_id}).status_code == 200
        for url in urls:
            downloaded = client.get(url)
            assert downloaded.status_code == 200
            import io
            with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
                assert archive.testzip() is None
                assert "3D/3dmodel.model" in archive.namelist()
        assert all(not path.exists() for path in failed_outputs)
