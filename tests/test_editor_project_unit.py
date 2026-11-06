"""Portable editor checkpoints preserve editable data without session paths."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from api.preview_cache_artifacts import externalize_preview_cache
from api.selection_state import pack_applied_region_mask, resolve_recipe_override_masks
from api.session_store import SessionStore
from config import LUTMetadata, PaletteEntry


@pytest.fixture
def source_image(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    Image.new("RGB", (6, 4), (210, 20, 30)).save(path)
    return path


def _session(image_path: Path | None = None) -> dict:
    rgb = np.full((4, 6, 3), [210, 20, 30], dtype=np.uint8)
    matrix = np.zeros((4, 6, 3), dtype=np.int16)
    selected = np.zeros((4, 6), dtype=bool)
    selected[1, 1] = selected[2, 4] = True
    return {
        "image_path": str(image_path) if image_path is not None else None,
        "material_source": "lut",
        "lut_source_kind": "legacy_single",
        "lut_name": "example",
        "lut_path": "/tmp/old-source-colours.npy",
        "preview_cache": {
            "matched_rgb": rgb,
            "material_matrix": matrix,
            "original_matched_rgb": rgb.copy(),
            "original_material_matrix": matrix.copy(),
            "mask_solid": np.ones((4, 6), dtype=bool),
            "quantized_image": rgb.copy(),
            "original_quantized_image": rgb.copy(),
            "target_w": 6,
            "target_h": 4,
            "target_width_mm": 0.6,
            "pixel_scale": 0.1,
            "modeling_mode": "high-fidelity",
            "lut_metadata": LUTMetadata(palette=[PaletteEntry("Red", "PETG")]),
            "vector_parse_clip_cache_path": "/tmp/old-source-geometry.pkl",
        },
        "editor_selection_mask": selected,
        "editor_selection_revision": 8,
        "editor_selection_content_generation": 3,
        "replacement_regions": [],
        "recipe_overrides": [],
        "free_color_set": set(),
        "region_replacement_count": 0,
    }


def test_portable_editor_restores_disjoint_pixels_selection_and_recipe(source_image: Path) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session(source_image)
    mask = source["editor_selection_mask"]
    source["preview_cache"]["matched_rgb"][mask] = [20, 210, 40]
    source["preview_cache"]["material_matrix"][mask] = [1, 0, 1]
    source["region_replacement_count"] = 1
    source["recipe_overrides"] = [{"region_id": "region-8", "recipe": [1, 0, 1], "layer_order": "Top2Bottom"}]
    source["recipe_override_applied_masks"] = {"region-8": pack_applied_region_mask(mask)}

    payload = build_editor_project(source)
    fresh = _session(source_image)
    fresh["preview_cache"]["vector_parse_clip_cache_path"] = "/tmp/new-geometry.pkl"
    checkpoint = decode_editor_project(payload, fresh)

    np.testing.assert_array_equal(checkpoint["preview_cache_arrays"]["matched_rgb"], source["preview_cache"]["matched_rgb"])
    np.testing.assert_array_equal(checkpoint["preview_cache_arrays"]["material_matrix"], source["preview_cache"]["material_matrix"])
    np.testing.assert_array_equal(checkpoint["session_fields"]["editor_selection_mask"], mask)
    resolved = resolve_recipe_override_masks(checkpoint["session_fields"], source["recipe_overrides"], mask.shape)
    np.testing.assert_array_equal(resolved["region-8"], mask)
    assert checkpoint["preview_cache_arrays"]["vector_parse_clip_cache_path"] == "/tmp/new-geometry.pkl"
    assert b"/tmp/old-" not in gzip.decompress(payload)


def test_editor_asset_survives_artifact_source_session_cleanup(source_image: Path) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session(source_image)
    fresh_source = source_image.with_name("fresh-source.png")
    fresh_source.write_bytes(source_image.read_bytes())
    store = SessionStore(ttl=1800)
    sid = store.create()
    store.register_temp_file(sid, str(source_image))
    source["preview_cache"] = externalize_preview_cache(sid, store, source["preview_cache"])
    try:
        payload = build_editor_project(source)
    finally:
        store.close(sid)
    assert not source_image.exists()
    restored = decode_editor_project(payload, _session(fresh_source))
    np.testing.assert_array_equal(
        restored["session_fields"]["editor_selection_mask"], _session(fresh_source)["editor_selection_mask"],
    )


def test_material_project_binding_uses_source_channels_before_and_after_recipe_edit(source_image: Path) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session(source_image)
    source.update({
        "material_source": "material_archive",
        "selected_materials": ["red", "white"],
        "material_backing_material_index": 1,
    })
    source["preview_cache"]["slot_names"] = ["Red PETG", "White PETG", "Virtual Clear"]
    source["preview_cache"]["lut_metadata"] = LUTMetadata(
        palette=[
            PaletteEntry("Red PETG", "red"), PaletteEntry("White PETG", "white"),
            PaletteEntry("Virtual Clear", "virtual"),
        ],
        base_channel_idx=1,
    )
    source["recipe_overrides"] = [{
        "region_id": "virtual", "recipe": [2, 0, 1], "layer_order": "Top2Bottom",
    }]
    source["recipe_override_applied_masks"] = {
        "virtual": pack_applied_region_mask(source["editor_selection_mask"]),
    }
    source["preview_cache"]["material_matrix"][source["editor_selection_mask"]] = [2, 0, 1]
    fresh = _session(source_image)
    fresh.update({key: source[key] for key in (
        "material_source", "selected_materials", "material_backing_material_index",
    )})
    fresh["preview_cache"]["slot_names"] = ["Red PETG", "White PETG"]
    # Material previews acquire LUTMetadata only after a custom recipe is applied.
    fresh["preview_cache"].pop("lut_metadata")

    checkpoint = decode_editor_project(build_editor_project(source), fresh)

    np.testing.assert_array_equal(
        checkpoint["preview_cache_arrays"]["matched_rgb"],
        source["preview_cache"]["matched_rgb"],
    )
    assert checkpoint["session_fields"]["recipe_overrides"] == source["recipe_overrides"]


@pytest.mark.parametrize("suffix", ["png", "svg"])
def test_editor_project_binds_source_content_independently_of_path(
    tmp_path: Path, suffix: str,
) -> None:
    from api.editor_project import build_editor_project, decode_editor_project
    from api.session_value_codec import encode_session_value

    original = tmp_path / f"original.{suffix}"
    renamed = tmp_path / f"renamed.{suffix}"
    different = tmp_path / "elsewhere" / original.name
    different.parent.mkdir()
    if suffix == "png":
        Image.new("RGB", (6, 4), (210, 20, 30)).save(original)
        Image.new("RGB", (6, 4), (10, 40, 220)).save(different)
    else:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="6" height="4">'
            '<path d="M0 0H6V4H0Z" fill="{}"/></svg>'
        )
        original.write_text(svg.format("#d2141e"), encoding="utf-8")
        different.write_text(svg.format("#0a28dc"), encoding="utf-8")
    renamed.write_bytes(original.read_bytes())
    source = _session(original)
    source["preview_cache"]["matched_rgb"][source["editor_selection_mask"]] = [110, 30, 125]
    payload = build_editor_project(source)

    restored = decode_editor_project(payload, _session(renamed))
    np.testing.assert_array_equal(
        restored["preview_cache_arrays"]["matched_rgb"], source["preview_cache"]["matched_rgb"],
    )
    fresh = _session(different)
    before = encode_session_value(fresh)
    with pytest.raises(ValueError, match="source.*match"):
        decode_editor_project(payload, fresh)
    assert encode_session_value(fresh) == before


@pytest.mark.parametrize("transform", ["rotate", "crop"])
def test_editor_project_rejects_changed_working_source_transform(
    source_image: Path, transform: str,
) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    with Image.open(source_image) as image:
        image.putpixel((0, 0), (10, 40, 220))
        image.save(source_image)
        changed = (
            image.rotate(180) if transform == "rotate"
            else image.crop((1, 0, 6, 4)).resize(image.size)
        )
    payload = build_editor_project(_session(source_image))
    # The name and preview dimensions stay the same; only the working input changes.
    changed.save(source_image)
    with pytest.raises(ValueError, match="source.*match"):
        decode_editor_project(payload, _session(source_image))


@pytest.mark.parametrize("field,value", [
    ("target_width_mm", 0.7), ("pixel_scale", 0.2), ("modeling_mode", "vector"),
])
def test_editor_project_rejects_changed_working_grid(
    source_image: Path, field: str, value: object,
) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    payload = build_editor_project(_session(source_image))
    fresh = _session(source_image)
    fresh["preview_cache"][field] = value
    with pytest.raises(ValueError, match="coordinates.*match"):
        decode_editor_project(payload, fresh)


@pytest.mark.parametrize("missing", [False, True])
def test_editor_project_requires_available_source_content(source_image: Path, missing: bool) -> None:
    from api.editor_project import build_editor_project

    source = _session(source_image if missing else None)
    if missing:
        source_image.unlink()
    with pytest.raises(ValueError, match="source.*unavailable"):
        build_editor_project(source)


@pytest.mark.parametrize("mismatch", ["shape", "material"])
def test_editor_asset_rejects_an_incompatible_preview_without_mutation(source_image: Path, mismatch: str) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    payload = build_editor_project(_session(source_image))
    fresh = _session(source_image)
    if mismatch == "shape":
        fresh["preview_cache"]["target_w"] = 7
    else:
        fresh["preview_cache"]["lut_metadata"].palette[0].material = "PLA"
    before = fresh["preview_cache"]["matched_rgb"].copy()
    with pytest.raises(ValueError, match="match|compatible"):
        decode_editor_project(payload, fresh)
    np.testing.assert_array_equal(fresh["preview_cache"]["matched_rgb"], before)


def test_editor_export_rejects_missing_applied_recipe_mask(source_image: Path) -> None:
    from api.editor_project import build_editor_project

    source = _session(source_image)
    source["recipe_overrides"] = [{"region_id": "missing", "recipe": [0, 0, 0], "layer_order": "Top2Bottom"}]
    source["recipe_override_applied_masks"] = {}
    with pytest.raises(ValueError, match="mask"):
        build_editor_project(source)


def test_editor_import_rejects_pickle_and_corrupt_compression() -> None:
    from api.editor_project import decode_editor_project

    unsafe = gzip.compress(json.dumps({"__lumina_session_type__": "pickle", "data": "AA=="}).encode())
    for payload in (unsafe, b"not gzip"):
        with pytest.raises(ValueError):
            decode_editor_project(payload, _session())


@pytest.mark.parametrize("resize", [False, True])
def test_editor_routes_restore_a_fresh_session_with_committed_selection(
    source_image: Path, monkeypatch: pytest.MonkeyPatch, resize: bool,
) -> None:
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_file_registry, get_session_store
    from api.file_registry import FileRegistry

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    source = _session(source_image)
    mask = source["editor_selection_mask"]
    source["preview_cache"]["matched_rgb"][mask] = [20, 210, 40]
    source["preview_cache"]["material_matrix"][mask] = [1, 0, 1]
    source["recipe_overrides"] = [{"region_id": "saved-region", "recipe": [1, 0, 1], "layer_order": "Top2Bottom"}]
    source["recipe_override_applied_masks"] = {"saved-region": pack_applied_region_mask(mask)}
    source["region_replacement_count"] = 1
    original = store.create()
    fresh = store.create()
    for key, value in source.items():
        store.put(original, key, value)
    target = _session(source_image)
    if resize:
        cache = target["preview_cache"]
        for key, value in list(cache.items()):
            if isinstance(value, np.ndarray):
                cache[key] = value.repeat(2, axis=0).repeat(2, axis=1)
        cache.update(target_w=12, target_h=8, target_width_mm=1.2)
        # A new-size preview has its own unedited analysis and geometry.
        cache["matched_rgb"][:] = [190, 20, 30]
        cache["original_matched_rgb"] = cache["matched_rgb"].copy()
    for key, value in target.items():
        store.put(fresh, key, value)
    store.put(fresh, "editor_selection_revision", 0)
    store.put(fresh, "editor_selection_mask", None)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    monkeypatch.setattr("api.routers.converter.replace._schedule_or_run_overridden_glb_build", lambda *args, **kwargs: None)
    client = TestClient(app)
    try:
        exported = client.get(f"/api/convert/editor-project/{original}", params={"selection_revision": 8})
        assert exported.status_code == 200, exported.text
        store.close(original)
        restored = client.post(
            f"/api/convert/editor-project/{fresh}/restore",
            files={"file": ("editor.json.gz", exported.content, "application/gzip")},
            data={"operation_id": "restore-project-1"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "committed"
        assert restored.json()["result"]["region_replacement_count"] == 1
        selection = client.get(f"/api/convert/selection/{fresh}")
        assert selection.status_code == 200, selection.text
        expected_mask = mask.repeat(2, axis=0).repeat(2, axis=1) if resize else mask
        assert selection.json()["selected_pixel_count"] == int(expected_mask.sum())
        from api.preview_cache_artifacts import hydrate_preview_cache_for_worker
        session = store.get(fresh)
        cache = hydrate_preview_cache_for_worker(session["preview_cache"], mmap=False)
        np.testing.assert_array_equal(cache["matched_rgb"][expected_mask], np.tile([20, 210, 40], (expected_mask.sum(), 1)))
        np.testing.assert_array_equal(cache["material_matrix"][expected_mask], np.tile([1, 0, 1], (expected_mask.sum(), 1)))
        np.testing.assert_array_equal(cache["matched_rgb"][~expected_mask], target["preview_cache"]["matched_rgb"][~expected_mask])
        assert cache["target_width_mm"] == (1.2 if resize else 0.6)
        resolved = resolve_recipe_override_masks(session, session["recipe_overrides"], expected_mask.shape)
        np.testing.assert_array_equal(resolved["saved-region"], expected_mask)
        assert selection.json()["editor_content_revision"] == restored.json()["editor_content_revision"]
        assert selection.json()["editor_content_revision"] > 0
        again = client.post(
            f"/api/convert/editor-project/{fresh}/restore",
            files={"file": ("editor.json.gz", exported.content, "application/gzip")},
            data={"operation_id": "restore-project-2"},
        )
        assert again.status_code == 409
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        store.close(fresh)
        client.close()


@pytest.mark.parametrize("resize", [False, True])
def test_imported_project_recipe_masks_survive_next_recipe_application(
    source_image: Path,
    monkeypatch: pytest.MonkeyPatch,
    resize: bool,
) -> None:
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_file_registry, get_session_store
    from api.file_registry import FileRegistry

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    metadata = LUTMetadata(
        palette=[PaletteEntry("Red", "PETG"), PaletteEntry("White", "PETG")],
        max_color_layers=3,
        layer_height_mm=0.08,
    )
    lut_path = source_image.with_suffix(".msgpack")
    lut_path.write_bytes(b"fixture")
    original, fresh = store.create(), store.create()
    for session_id in (original, fresh):
        session = _session(source_image)
        cache = session["preview_cache"]
        cache["matched_rgb"][:2] = [255, 255, 255]
        cache["quantized_image"] = cache["matched_rgb"].copy()
        cache["lut_metadata"] = metadata
        if resize and session_id == fresh:
            for key, value in list(cache.items()):
                if isinstance(value, np.ndarray):
                    cache[key] = value.repeat(2, axis=0).repeat(2, axis=1)
            cache.update(target_w=12, target_h=8, target_width_mm=1.2)
        session.update({
            "lut_path": str(lut_path),
            "editor_selection_mask": None,
            "editor_selection_revision": 0,
            "editor_selection_content_generation": 0,
        })
        for key, value in session.items():
            store.put(session_id, key, value)
    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (np.zeros((0, 3), dtype=np.uint8), None, metadata),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        lambda *args, **kwargs: {
            "rgb": [20, 210, 40], "lab": [55.0, 2.0, 3.0],
            "source": "stage_model", "runtime_mode_key": "0.08x3",
        },
    )
    monkeypatch.setattr("api.routers.converter.replace.schedule_glb_build", lambda *args, **kwargs: None)
    monkeypatch.setattr("api.routers.converter.replace._schedule_or_run_overridden_glb_build", lambda *args, **kwargs: None)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    client = TestClient(app)

    def mutate(operation: str, **fields: object) -> dict:
        document = client.get(f"/api/convert/selection/{original}").json()
        response = client.post("/api/convert/selection/mutate", json={
            "session_id": original, "operation": operation,
            "base_selection_revision": document["selection_revision"],
            "content_revision": document["content_revision"], **fields,
        })
        assert response.status_code == 200, response.text
        return response.json()

    def apply_recipe(session_id: str, region_id: str, channel: int) -> None:
        response = client.post("/api/convert/apply-recipe-override", json={
            "session_id": session_id, "region_ids": [region_id],
            "recipe": [channel] * 3, "layer_order": "Top2Bottom",
            "color_layers": 3, "layer_height_mm": 0.08,
        })
        assert response.status_code == 200, response.text

    try:
        first_region = mutate("point-toggle", x=0, y=0)["region_ids"][0]
        apply_recipe(original, first_region, 1)
        mutate("clear")
        saved_selection = mutate("point-toggle", x=0, y=3)
        exported = client.get(f"/api/convert/editor-project/{original}")
        assert exported.status_code == 200, exported.text
        restored = client.post(
            f"/api/convert/editor-project/{fresh}/restore",
            files={"file": ("editor.json.gz", exported.content, "application/gzip")},
            data={"operation_id": "restore-then-recipe"},
        )
        assert restored.status_code == 200, restored.text
        document = client.get(f"/api/convert/selection/{fresh}").json()
        new_region = document["region_ids"][0]
        apply_recipe(fresh, new_region, 0)

        session = store.get(fresh)
        shape = (8, 12) if resize else (4, 6)
        resolved = resolve_recipe_override_masks(session, session["recipe_overrides"], shape)
        first_mask = np.zeros(shape, dtype=bool)
        first_mask[:shape[0] // 2] = True
        np.testing.assert_array_equal(resolved[first_region], first_mask)
        np.testing.assert_array_equal(resolved[new_region], ~first_mask)
        assert document["selection_revision"] > saved_selection["selection_revision"]
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        store.close(original)
        store.close(fresh)
        client.close()


@pytest.mark.parametrize("scale", [0.5, 1, 2])
@pytest.mark.parametrize("layer_order", ["Top2Bottom", "Bottom2Top"])
def test_resize_replays_deltas_and_global_bases_without_replacing_fresh_analysis(
    source_image: Path, scale: float, layer_order: str,
) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session(source_image)
    old = source["preview_cache"]
    old["lut_metadata"].layer_order = layer_order
    mask = source["editor_selection_mask"]
    old["matched_rgb"][mask] = [20, 210, 40]
    old["quantized_image"][mask] = [10, 200, 30]
    # A four-layer manual recipe on a three-layer preview; the added backing
    # layer must survive, including Bottom2Top stacking and transparent edges.
    old["material_matrix"] = np.zeros((4, 6, 4), dtype=np.int16)
    old["material_matrix"][mask] = [1, 0, 1, 1]
    source["global_replacement_base_matched_rgb"] = old["matched_rgb"].copy()
    source["global_replacement_base_material_matrix"] = old["material_matrix"].copy()
    fresh = _session(source_image)
    cache = fresh["preview_cache"]
    shape = (int(4 * scale), int(6 * scale))
    for key, value in list(cache.items()):
        if isinstance(value, np.ndarray):
            cache[key] = np.ones(shape, dtype=bool) if value.ndim == 2 else np.zeros((*shape, value.shape[2]), dtype=value.dtype)
    cache.update(target_w=shape[1], target_h=shape[0], target_width_mm=0.6 * scale + 0.01)
    cache["lut_metadata"].layer_order = layer_order
    for key in ("matched_rgb", "original_matched_rgb", "quantized_image", "original_quantized_image"):
        cache[key][:] = [180, 40, 50]
    cache["height_identity_rgb"] = cache["matched_rgb"].copy()
    cache["mask_solid"][-1, -1] = False
    if scale == 2:
        cache["mask_solid"][2, 2] = False
    cache["material_matrix"][~cache["mask_solid"]] = -1
    cache["original_material_matrix"] = cache["material_matrix"].copy()
    expected = mask.repeat(2, axis=0).repeat(2, axis=1) if scale == 2 else mask[1::2, 1::2] if scale == 0.5 else mask.copy()
    expected &= cache["mask_solid"]

    restored = decode_editor_project(build_editor_project(source), fresh, allow_resize=True)
    arrays, fields = restored["preview_cache_arrays"], restored["session_fields"]
    for key in ("original_matched_rgb", "original_material_matrix", "original_quantized_image", "height_identity_rgb", "mask_solid"):
        np.testing.assert_array_equal(arrays[key], cache[key])
    np.testing.assert_array_equal(arrays["matched_rgb"][~expected], cache["matched_rgb"][~expected])
    np.testing.assert_array_equal(arrays["matched_rgb"][expected], np.tile([20, 210, 40], (expected.sum(), 1)))
    np.testing.assert_array_equal(arrays["quantized_image"][expected], np.tile([10, 200, 30], (expected.sum(), 1)))
    np.testing.assert_array_equal(arrays["material_matrix"][expected], np.tile([1, 0, 1, 1], (expected.sum(), 1)))
    np.testing.assert_array_equal(arrays["material_matrix"][-1, -1], [-1] * 4)
    np.testing.assert_array_equal(fields["editor_selection_mask"], expected)
    for name in ("matched_rgb", "material_matrix"):
        np.testing.assert_array_equal(fields[f"global_replacement_base_{name}"], arrays[name])
    # Resaving the migrated session establishes the new grid as its binding.
    reopened = {**fresh, **fields, "preview_cache": arrays}
    again = decode_editor_project(build_editor_project(reopened), fresh)
    np.testing.assert_array_equal(again["preview_cache_arrays"]["material_matrix"], arrays["material_matrix"])


def test_resize_keeps_global_base_compatible_with_extended_recipe_layers(source_image: Path) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session(source_image)
    source["global_replacement_base_material_matrix"] = source["preview_cache"]["material_matrix"].copy()
    source["preview_cache"]["material_matrix"] = np.ones((4, 6, 4), dtype=np.int16)
    fresh = _session(source_image)
    fresh["preview_cache"]["target_width_mm"] = 0.7
    restored = decode_editor_project(build_editor_project(source), fresh, allow_resize=True)
    base = restored["session_fields"]["global_replacement_base_material_matrix"]
    assert base.shape == restored["preview_cache_arrays"]["material_matrix"].shape == (4, 6, 4)
    np.testing.assert_array_equal(base, np.zeros((4, 6, 4), dtype=np.int16))


def test_resize_rejects_recipe_masks_that_vanish_before_publishing(source_image: Path) -> None:
    from api.editor_project import build_editor_project, decode_editor_project
    from api.session_value_codec import encode_session_value

    source = _session(source_image)
    mask = np.zeros((4, 6), dtype=bool)
    mask[0, 0] = True
    source["recipe_overrides"] = [{"region_id": "tiny", "recipe": [1, 0, 1], "layer_order": "Top2Bottom"}]
    source["recipe_override_applied_masks"] = {"tiny": pack_applied_region_mask(mask)}
    fresh = _session(source_image)
    cache = fresh["preview_cache"]
    for key, value in list(cache.items()):
        if isinstance(value, np.ndarray):
            cache[key] = value[1::2, 1::2].copy()
    cache.update(target_w=3, target_h=2, target_width_mm=0.3)
    before = encode_session_value(fresh)
    with pytest.raises(ValueError, match="mask"):
        decode_editor_project(build_editor_project(source), fresh, allow_resize=True)
    assert encode_session_value(fresh) == before


@pytest.mark.parametrize("mismatch", ["image", "mode", "material", "grid", "scale"])
def test_resize_still_rejects_incompatible_or_malformed_bindings(
    source_image: Path, mismatch: str,
) -> None:
    from api.editor_project import build_editor_project, decode_editor_project
    from api.session_value_codec import encode_session_value

    payload = build_editor_project(_session(source_image))
    fresh = _session(source_image)
    fresh["preview_cache"]["target_width_mm"] = 0.7
    if mismatch == "image":
        Image.new("RGB", (6, 4), (10, 40, 220)).save(source_image)
    elif mismatch == "mode":
        fresh["preview_cache"]["modeling_mode"] = "vector"
    elif mismatch == "material":
        fresh["preview_cache"]["lut_metadata"].palette[0].material = "PLA"
    else:
        document = json.loads(gzip.decompress(payload))
        document["binding"]["width" if mismatch == "grid" else "pixel_scale"] = 7 if mismatch == "grid" else 0
        payload = gzip.compress(json.dumps(document).encode())
    before = encode_session_value(fresh)
    with pytest.raises(ValueError):
        decode_editor_project(payload, fresh, allow_resize=True)
    assert encode_session_value(fresh) == before


def test_editor_restore_route_rejects_different_source_before_session_mutation(source_image: Path) -> None:
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_session_store
    from api.editor_project import build_editor_project
    from api.session_value_codec import encode_session_value

    payload = build_editor_project(_session(source_image))
    different = source_image.with_name("different.png")
    Image.new("RGB", (6, 4), (10, 40, 220)).save(different)
    fresh = _session(different)
    fresh["editor_selection_revision"] = 0
    fresh["editor_selection_mask"] = None
    store = SessionStore(ttl=1800)
    sid = store.create()
    for key, value in fresh.items():
        store.put(sid, key, value)
    before = encode_session_value(store.get(sid))
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session_store] = lambda: store
    client = TestClient(app)
    try:
        response = client.post(
            f"/api/convert/editor-project/{sid}/restore",
            files={"file": ("editor.json.gz", payload, "application/gzip")},
            data={"operation_id": "wrong-source"},
        )
        assert response.status_code == 422, response.text
        assert "source" in response.json()["detail"]
        assert encode_session_value(store.get(sid)) == before
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        store.close(sid)
        client.close()
