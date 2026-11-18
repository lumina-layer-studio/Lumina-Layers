"""Independent shared libraries, explicit restoration and interrupted boots."""

import json
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api import material_seed
from core.resource_seed import initialize_seed, read_seed_state, seed_lock
from core.single_stage import material_files, material_package
from utils.lut_manager import LUTManager
from test_lut_registry_sync_unit import _bundle_bytes, _DEFAULT_LUT_BYTES, _entry
from test_material_sync_api_unit import _write_v2_multi_material_package


def test_bundled_seed_checks_paired_release_before_install(monkeypatch, tmp_path):
    from api.lut_seed import _verified_packages
    resources = tmp_path / "resources"
    seed = resources / "luts/lumina-luts-seed.zip"
    seed.parent.mkdir(parents=True)
    seed.write_bytes(b"tampered")
    (resources / "resource-release.json").write_text(json.dumps({
        "kind": "lumina_resource_release", "schema_version": 1, "dataset_version": "test.1",
        "artifacts": {"luts": {"path": seed.name, "bytes": 8, "sha256": hashlib.sha256(b"original").hexdigest()}},
    }))
    monkeypatch.delenv("LUMINA_LUTS_SEED_SHA256", raising=False)
    with pytest.raises(ValueError, match="does not match"):
        _verified_packages(seed)


def test_shared_library_initialization_excludes_other_processes(tmp_path):
    state_dir = tmp_path / "shared" / "_sync"
    script = """import sys
from pathlib import Path
from core.resource_seed import seed_lock, SeedBusyError
try:
    with seed_lock(Path(sys.argv[1])): pass
except SeedBusyError:
    sys.exit(23)
"""
    with seed_lock(state_dir):
        competing = subprocess.run([sys.executable, "-c", script, str(state_dir)], capture_output=True, timeout=10)
        assert competing.returncode == 23, competing.stderr.decode()
    after_release = subprocess.run([sys.executable, "-c", script, str(state_dir)], capture_output=True, timeout=10)
    assert after_release.returncode == 0, after_release.stderr.decode()


def test_interrupted_install_retries_but_corrupt_state_requires_explicit_restore(tmp_path):
    state = tmp_path / "_sync"
    state.mkdir()
    (state / "seed.json").write_text('{"state":"initializing"}')
    calls = []
    def install():
        calls.append(True)
        return {"installed_count": 1}
    assert initialize_seed(state_dir=state, has_content=lambda: True, install=install)["installed_count"] == 1
    (state / "seed.json").write_text("damaged")
    assert initialize_seed(state_dir=state, has_content=lambda: False, install=install) is None
    assert len(calls) == 1
    assert initialize_seed(state_dir=state, has_content=lambda: False, install=install, restore=True)["installed_count"] == 1


def test_resource_status_does_not_initialize_and_only_offers_existing_seeds(monkeypatch, tmp_path):
    root = tmp_path / "materials"
    monkeypatch.setattr(material_seed, "MATERIALS_DIR", str(root))
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(tmp_path / "luts/Cloud_sync"))
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(tmp_path / "absent-materials.zip"))
    monkeypatch.setenv("LUMINA_LUTS_SEED_PATH", str(tmp_path / "absent-luts.zip"))
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "")
    client = TestClient(create_app())
    status = client.get("/api/resources/status")
    assert status.status_code == 200
    assert status.json()["materials"] == {
        "configured": False, "provider": "disabled",
        "seed": {"state": "uninitialized", "available": False},
    }
    assert not root.exists()
    assert client.post("/api/resources/luts/restore").status_code == 404
    assert not status.json()["luts"]["seed"]["available"]
    assert read_seed_state(LUTManager.cloud_lut_sync_dir())["state"] == "failed"


@pytest.fixture
def offline_library(tmp_path, monkeypatch):
    materials = tmp_path / "library/materials"
    cloud = tmp_path / "library/luts/Cloud"
    seeds = tmp_path / "sources"
    seeds.mkdir()
    monkeypatch.setattr(material_seed, "MATERIALS_DIR", str(materials))
    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(materials))
    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(tmp_path / "presets"))
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(cloud))
    monkeypatch.setenv("LUMINA_CUSTOM_LUT_DIR", str(cloud.parent / "Custom"))
    for kind in ("materials", "luts"):
        monkeypatch.setenv(f"LUMINA_{kind.upper()}_SEED_PATH", str(seeds / f"{kind}.zip"))
        monkeypatch.delenv(f"LUMINA_{kind.upper()}_SEED_SHA256", raising=False)
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "")
    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(tmp_path / "feedback"))
    return seeds, materials, cloud


def _write_picker_seeds(seeds: Path) -> None:
    original = seeds / "materials-source.zip"
    _write_v2_multi_material_package(original)
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(seeds / "materials.zip", "w") as output:
        manifest_name = "lumina_material_bundle.json"
        manifest = json.loads(source.read(manifest_name))
        for package in manifest["packages"]:
            package.update(channel="official", visibility="official", display={})
        selected = manifest["packages"][0]
        selected["display"] = {"aliases": ["Future packaging alias"], "profile_data": "omit"}
        for name in source.namelist():
            if name == manifest_name:
                continue
            data = source.read(name)
            if name == "materials/BrandA/pla-selected/material.json":
                payload = json.loads(data)
                payload.update(
                    sku="FUTURE-37", market_names={"CN": "星岚", "INTL": {"en": "Starlit Pale"}},
                    display={"localized_names": {"zh-CN": "星岚样品"}, "solver_params": "omit"},
                    source={"kit_manifest": {"spec": {"base_mm": 1, "layer_height_mm": .08, "max_step_layers": 25}}},
                    verification_runs=[{"samples": {
                        "thickness_mm": [round(i * .08, 2) for i in reversed(range(8))],
                        "black_linear": [[i * .02, 0, 0] for i in reversed(range(8))],
                        "white_linear": [[1, 1 - .1 * i, 1] for i in reversed(range(8))],
                    }}],
                )
                data = json.dumps(payload).encode()
                record = next(file for file in selected["files"] if file["role"] == "material_archive")
                record.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                selected["content_hash"] = material_package._material_content_hash_from_file_records(selected["files"])
            output.writestr(name, data)
        output.writestr(manifest_name, json.dumps(manifest))

    entries = []
    with zipfile.ZipFile(seeds / "luts.zip", "w") as output:
        for suffix in ("selected", "other"):
            lut = _DEFAULT_LUT_BYTES
            if suffix == "selected":
                payload = json.loads(lut)
                payload["palette"] = {
                    "White": {"material": "PLA", "hex_color": "#efe3cf"},
                    "Moonstone": {"material": "PETG", "hex_color": "#bc415a"},
                    "Custom Slot 3": {"material": "PLA", "hex_color": "#15c599"},
                }
                lut = json.dumps(payload).encode()
            identity = {
                "lut_id": f"lut_{suffix}", "revision_id": f"rev_{suffix}", "channel": "community",
                "content_hash": hashlib.sha256(lut).hexdigest(),
                "local_path": f"BrandA/PLA/{suffix}.json",
            }
            package = _bundle_bytes(lut, package_extra={
                **identity, "display": {
                    "name": f"LUT {suffix.title()}", "manufacturer": "BrandA", "sku": "FUTURE-37",
                    "market_names": {"CN": "星岚", "INTL": {"en": "Starlit Pale"}},
                    "localized_names": {"zh-CN": "星岚样品"}, "solver_params": "omit",
                },
                "compatibility": {"color_mode": "4-color"},
            })
            entry = _entry(package, **identity, path=f"packages/{suffix}.zip")
            for key in ("display", "compatibility", "package_url"):
                entry.pop(key)
            if suffix == "selected":
                entry["display"] = {"aliases": ["Future packaging alias"], "profile_data": "omit"}
            output.writestr(entry["path"], package)
            entries.append(entry)
        output.writestr("lumina_lut_seed.json", json.dumps({
            "kind": "lumina_lut_seed", "schema_version": "1.0", "dataset_version": "test.1",
            "packages": entries,
        }))


@pytest.mark.parametrize("configure_url", [False, True])
def test_real_startup_leaves_library_empty_even_with_starter_sources(offline_library, monkeypatch, configure_url):
    seeds, materials, cloud = offline_library
    _write_picker_seeds(seeds)
    requests = []
    if configure_url:
        monkeypatch.delenv("LUMINA_MATERIALS_SEED_PATH")
        monkeypatch.setenv("LUMINA_MATERIALS_SEED_URL", "https://example.test/materials.zip")

        def reject_download(*args, **kwargs):
            requests.append(args)
            raise OSError("Unexpected seed download")

        monkeypatch.setattr(material_seed.urllib.request, "urlopen", reject_download)
    with TestClient(create_app()) as client:
        assert client.get("/api/health").is_success
    assert not requests
    assert not materials.exists()
    assert not cloud.parent.exists()


@pytest.mark.parametrize("kind", ["materials", "luts"])
def test_offline_picker_installs_only_the_chosen_revision(offline_library, kind):
    seeds, materials, cloud = offline_library
    _write_picker_seeds(seeds)
    client = TestClient(create_app())
    route = f"/api/resources/{kind}"
    catalog = client.get(route + "/catalog")
    assert catalog.status_code == 200, catalog.text
    items = catalog.json()["items"]
    assert len(items) == 2
    selected = items[0]
    is_material = kind == "materials"
    assert selected["name"] == ("PLA Selected" if is_material else "LUT Selected")
    assert selected["brand"] == "BrandA"
    assert selected["material_type"] == "PLA"
    assert selected["color_mode"] == (None if is_material else "4-color")
    assert catalog.json()["dataset_version"] == (None if is_material else "test.1")
    assert not any(item["installed"] for item in items)
    assert not materials.parent.exists()
    request = {key: selected[key] for key in ("resource_id", "revision_id")}
    assert client.post(route + "/install", json={**request, "revision_id": items[1]["revision_id"]}).status_code == 404
    assert client.post(route + "/install", json={**request, "package_url": "https://example.test/extra"}).status_code == 422
    assert not materials.parent.exists()
    with seed_lock((materials / "_sync") if is_material else LUTManager.cloud_lut_sync_dir()):
        assert client.post(route + "/install", json=request).status_code == 409
    assert client.post(route + "/install", json=request).json() == {"installed_count": 1}
    assert client.post(route + "/install", json=request).json() == {"installed_count": 0}
    assert [row["installed"] for row in client.get(route + "/catalog").json()["items"]] == [True, False]
    if is_material:
        installed = list(materials.rglob("material.json"))
        assert installed == [materials / "BrandA/pla-selected/material.json"]
    else:
        installed = list(cloud.rglob("*.json"))
        assert installed == [cloud / "BrandA/PLA/selected.json"]
    edited = installed[0]
    edited.write_text('{"name": "personal edit"}', encoding="utf-8")
    assert not client.get(route + "/catalog").json()["items"][0]["installed"]
    assert client.post(route + "/install", json=request).json() == {"installed_count": 1}
    assert edited.read_text(encoding="utf-8") == '{"name": "personal edit"}'


@pytest.mark.parametrize("kind", ["materials", "luts"])
def test_offline_picker_handles_absent_and_corrupted_sources(offline_library, kind):
    seeds, materials, cloud = offline_library
    client = TestClient(create_app())
    route = f"/api/resources/{kind}"
    assert client.get(route + "/catalog").json() == {"items": [], "dataset_version": None}
    request = {"resource_id": "unused", "revision_id": "missing"}
    assert client.post(route + "/install", json=request).status_code == 404
    (seeds / f"{kind}.zip").write_bytes(b"damaged collection")
    assert client.get(route + "/catalog").status_code == 422
    assert client.post(route + "/install", json=request).status_code == 422
    assert not list(materials.rglob("material.json"))
    assert not list(cloud.rglob("*.json"))


def test_selected_material_import_rejects_an_unindexed_legacy_archive(offline_library):
    from core.single_stage.material_library import import_saved_stage_a_material_archives

    seeds, materials, _ = offline_library
    original = seeds / "legacy-source.zip"
    _write_v2_multi_material_package(original)
    legacy = seeds / "materials.zip"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(legacy, "w") as output:
        for name in source.namelist():
            if name != "lumina_material_bundle.json":
                output.writestr(name, source.read(name))
    with pytest.raises(ValueError, match="(?i)selected|selectable"):
        import_saved_stage_a_material_archives(
            archive_path=str(legacy), materials_dir=str(materials),
            selected_material_id="mat_selected", selected_revision_id="rev_selected",
        )
    client = TestClient(create_app())
    assert client.post("/api/resources/materials/install", json={
        "resource_id": "mat_selected", "revision_id": "rev_selected",
    }).status_code == 422
    assert not list(materials.rglob("material.json"))


@pytest.mark.parametrize("kind", ["materials", "luts"])
def test_selected_revision_with_a_missing_declared_file_rejects_damaged_collection(offline_library, kind):
    seeds, materials, cloud = offline_library
    _write_picker_seeds(seeds)
    path = seeds / f"{kind}.zip"
    with zipfile.ZipFile(path) as original:
        contents = {name: original.read(name) for name in original.namelist()}
    missing = "materials/BrandA/pla-selected/stage_A_parameters.json" if kind == "materials" else "packages/selected.zip"
    del contents[missing]
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    route = f"/api/resources/{kind}"
    response = TestClient(create_app()).post(route + "/install", json={
        "resource_id": "mat_selected" if kind == "materials" else "lut_selected",
        "revision_id": "rev_selected",
    })
    assert response.status_code == 422, response.text
    assert not list(materials.rglob("material.json"))
    assert not list(cloud.rglob("*.json"))


@pytest.mark.parametrize("kind", ["materials", "luts"])
def test_unknown_packaging_identity_survives_offline_selection_and_installation(offline_library, kind):
    seeds, _, _ = offline_library
    _write_picker_seeds(seeds)
    client = TestClient(create_app(), base_url="http://127.0.0.1")
    route = f"/api/resources/{kind}"
    row = client.get(route + "/catalog").json()["items"][0]
    display = row.get("display")
    assert isinstance(display, dict)
    assert display["market_names"] == {"CN": "星岚", "INTL": {"en": "Starlit Pale"}}
    assert display["localized_names"] == {"zh-CN": "星岚样品"}
    assert display["aliases"] == ["Future packaging alias"]
    assert display["sku"] == "FUTURE-37"
    assert "solver_params" not in display and "profile_data" not in display
    assert client.post(route + "/install", json={
        key: row[key] for key in ("resource_id", "revision_id")
    }).json() == {"installed_count": 1}
    if kind == "materials":
        saved = client.get("/api/extractor/gradient-card-materials")
        assert saved.status_code == 200, saved.text
        assert saved.json()["materials"][0]["display"] == display
    else:
        saved = client.get("/api/lut/details/catalog")
        assert saved.status_code == 200, saved.text
        local = [item for group in saved.json()["groups"] for item in group["items"]]
        assert [item["display"] for item in local] == [display]


def test_catalog_thumbnails_preserve_measured_steps_and_custom_lut_slot_order(offline_library):
    seeds, _, _ = offline_library
    _write_picker_seeds(seeds)
    client = TestClient(create_app(), base_url="http://127.0.0.1")
    materials = client.get("/api/resources/materials/catalog").json()["items"]
    swatches = materials[0]["display"].get("preview_swatches")
    assert isinstance(swatches, dict)
    assert swatches["source"] == "measured"
    assert len(swatches["black"]) == len(swatches["white"]) == 8
    assert swatches["board_thickness_mm"] == 2.96
    assert swatches["black"][0] == [0, 0, 0]
    assert swatches["black"][-1] == [105, 0, 0]
    assert swatches["white"][0] == [255, 255, 255]
    assert swatches["white"][-1] == [255, 149, 255]
    assert "preview_swatches" not in materials[1]["display"]
    luts = client.get("/api/resources/luts/catalog").json()["items"]
    assert luts[0]["display"].get("palette_rgb") == [[239, 227, 207], [188, 65, 90], [21, 197, 153]]
    assert "palette_rgb" not in luts[1]["display"]


def test_online_thumbnails_use_only_published_catalog_fields(offline_library, monkeypatch):
    from api.services.lut_registry_sync import fetch_remote_catalog
    from core.single_stage.material_registry_client import list_material_registry_catalog

    base = "https://catalog.test/api/material-registry/v1"
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", base)
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("/materials/catalog"):
            return httpx.Response(200, json={"materials": [{
                "material_id": "capture",
                "card_metadata": {"preview_swatches": {
                    "source": "model", "board_thickness_mm": 2.0, "white": [[255 - i] * 3 for i in range(12)],
                    "black": [[i] * 3 for i in range(12)],
                }},
            }, {"material_id": "empty", "display": {"brand": "BrandA"}}]})
        assert request.url.path.endswith("/luts/catalog"), request.url
        return httpx.Response(200, json={"items": [{
            "lut_id": "custom", "revision_id": "1", "display": {"manufacturer": "BrandA"},
            "compatibility": {"ordered_channels": [
                {"name": "Moonstone", "hex_color": "#03afba"}, {"name": "White", "rgb": [9, 8, 7]},
            ]},
        }, {"lut_id": "empty", "revision_id": "1", "display": {"name": "4-color"}}]})

    transport = httpx.MockTransport(respond)
    materials = list_material_registry_catalog(registry_url=base, transport=transport, use_cache=False)
    with httpx.Client(transport=transport) as client:
        luts = fetch_remote_catalog(client=client)
    assert requests == ["/api/material-registry/v1/materials/catalog", "/api/material-registry/v1/luts/catalog"]
    swatches = materials["materials"][0].get("display", {}).get("preview_swatches")
    assert swatches and swatches["source"] == "model"
    assert len(swatches["white"]) == len(swatches["black"]) == 12
    assert swatches["board_thickness_mm"] == 2.0
    assert swatches["black"][0] == [0, 0, 0] and swatches["black"][-1] == [11, 11, 11]
    assert "preview_swatches" not in materials["materials"][1]["display"]
    assert luts["items"][0]["display"]["palette_rgb"] == [[3, 175, 186], [9, 8, 7]]
    assert "palette_rgb" not in luts["items"][1]["display"]


def test_wide_and_bgr_palettes_preserve_both_endpoint_slots():
    from core.filament_display import filament_preview

    palette = [[i, 75, 255] for i in range(27)]
    colors = filament_preview({"palette_rgb": palette}).get("palette_rgb")
    assert colors and len(colors) == 16
    assert colors[0] == palette[0] and colors[-1] == palette[-1]
    assert colors == sorted(colors) and all(color in palette for color in colors)
    assert filament_preview({"palette_bgr": [[45, 2, 238], [94, 41, 7]]}) == {
        "palette_rgb": [[238, 2, 45], [7, 41, 94]],
    }
    assert filament_preview({
        "palette": {"slot_a": {"hex_color": "#0a1b2c"}, "slot_b": {"bgr": [56, 34, 12]}},
        "ordered_channels": ["slot_b", "slot_a"],
    }) == {"palette_rgb": [[12, 34, 56], [10, 27, 44]]}


def test_local_capture_takes_priority_over_a_catalog_model_preview(offline_library):
    from core.single_stage.material_library import import_saved_stage_a_material_archives

    seeds, materials, _ = offline_library
    _write_picker_seeds(seeds)
    import_saved_stage_a_material_archives(
        archive_path=str(seeds / "materials.zip"), materials_dir=str(materials),
        selected_material_id="mat_selected", selected_revision_id="rev_selected",
        selected_display={"preview_swatches": {
            "source": "model", "white": [[240, 0, 0], [230, 0, 0]],
            "black": [[10, 0, 0], [20, 0, 0]],
        }},
    )
    client = TestClient(create_app(), base_url="http://127.0.0.1")
    row = client.get("/api/extractor/gradient-card-materials").json()["materials"][0]
    assert row["display"]["preview_swatches"]["source"] == "measured"
    assert row["display"]["preview_swatches"]["white"][0] == [255, 255, 255]


@pytest.mark.parametrize("suffix", ["npz", "msgpack", "npy"])
def test_offline_lut_binary_formats_only_use_explicit_slot_colors(offline_library, suffix):
    from io import BytesIO

    import msgpack
    import numpy as np

    seeds, _, _ = offline_library
    palette = {"B": {"hex_color": "#afbc81"}, "A": {"hex_color": "#05bf34"}}
    if suffix == "msgpack":
        payload = msgpack.packb({"palette": palette})
    else:
        buf = BytesIO()
        colors = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)
        if suffix == "npz":
            np.savez(buf, rgb=colors, metadata_json=json.dumps({"palette": palette}))
        else:
            np.save(buf, colors)
        payload = buf.getvalue()
    identity = {"lut_id": "binary", "revision_id": "one", "channel": "community",
                "local_path": f"Brand/Custom.{suffix}", "content_hash": hashlib.sha256(payload).hexdigest()}
    package = _bundle_bytes(payload, lut_path=f"payload/Custom.{suffix}", package_extra=identity)
    entry = _entry(package, **identity, path="packages/binary.zip")
    with zipfile.ZipFile(seeds / "luts.zip", "w") as bundle:
        bundle.writestr(entry["path"], package)
        bundle.writestr("lumina_lut_seed.json", json.dumps({
            "kind": "lumina_lut_seed", "schema_version": "1.0", "packages": [entry],
        }))
    row = TestClient(create_app()).get("/api/resources/luts/catalog").json()["items"][0]
    expected = None if suffix == "npy" else [[175, 188, 129], [5, 191, 52]]
    assert row["display"].get("palette_rgb") == expected
    if suffix != "msgpack":
        assert row["display"]["lut_board_preview"]["pages"][0]["count"] == 2


def test_online_lut_only_reuses_artwork_for_matching_file_bytes(offline_library, monkeypatch):
    from api.routers import lut_registry

    seeds, _, _ = offline_library
    _write_picker_seeds(seeds)
    digest = hashlib.sha256(_DEFAULT_LUT_BYTES).hexdigest()
    base = {"lut_id": "lut_other", "revision_id": "rev_other", "display": {"name": "Registry title"}}
    online = [{**base, "content_hash": digest}, {**base, "content_hash": "b" * 64}]
    monkeypatch.setattr(lut_registry, "fetch_remote_catalog", lambda **kwargs: {"items": online, "total": 2})
    client = TestClient(create_app())
    rows = client.get("/api/lut-registry/catalog").json()["items"]
    assert rows[0]["display"]["lut_board_preview"]["pages"][0]["count"] == 1
    assert rows[1] == online[1]
    assert online[0]["display"] == {"name": "Registry title"}
    (seeds / "luts.zip").write_bytes(b"unavailable offline bundle")
    assert client.get("/api/lut-registry/catalog").json()["items"] == online
