"""Native SVG dynamic-material edit lifecycle regression coverage."""

from __future__ import annotations

import io
import importlib
import inspect
import json
import pickle
import time
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import hydrate_preview_cache
from api.session_store import SessionStore
from api.routers.converter import generate as generate_router
from api.routers.converter import replace as replace_router
from api.workers import converter_workers
from core import material_lut_synthesis
from core.pipeline import vector_glb_preview
from utils import bambu_3mf_writer


_FIXTURE_SVG = Path(__file__).parent / "fixtures" / "svg_vector" / (
    "dynamic_material_lifecycle.svg"
)
_FIXTURE_MATERIALS = Path(__file__).parent / "fixtures" / (
    "dynamic_material_materials"
)
_MATERIALS = ["white", "red", "blue", "yellow"]
_EXPECTED_MAX_LAYERS = 7
_LAYER_HEIGHT_MM = 0.08
_BACKING_THICKNESS_MM = 1.2


def _wait_for_lightweight_glb(
    client: TestClient,
    session_id: str,
    *,
    timeout_s: float = 5.0,
) -> str:
    """Return the async lightweight preview URL once it becomes ready."""

    deadline = time.perf_counter() + timeout_s
    last_status: dict[str, object] = {}
    while time.perf_counter() < deadline:
        response = client.get(f"/api/convert/glb-status/{session_id}")
        assert response.status_code == 200, response.text
        last_status = response.json()
        if last_status.get("status") == "ready":
            glb_url = last_status.get("glb_url")
            assert isinstance(glb_url, str)
            return glb_url
        time.sleep(0.02)
    raise AssertionError(
        f"lightweight GLB did not become ready: {last_status}"
    )


class _InlineWorkerPool:
    """Execute production workers inline while retaining their call boundary."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def submit(self, function, *args, **kwargs):
        del kwargs
        self.calls.append(function.__name__)
        return function(*args)

    async def submit_timed(self, function, *args, timeout=None, **kwargs):
        del timeout, kwargs
        self.calls.append(function.__name__)
        return function(*args), {}


def _recipe_signature(analysis: object) -> Counter[tuple[int, ...]]:
    """Return the recipe multiset that reaches one native vector consumer."""

    recipes: list[tuple[int, ...]] = []
    for shape in getattr(analysis, "matched_shapes", []) or []:
        if not isinstance(shape, dict):
            continue
        recipe = shape.get("recipe")
        geometry = shape.get("geometry")
        if not recipe or geometry is None or getattr(geometry, "is_empty", True):
            continue
        recipes.append(tuple(int(value) for value in recipe))
    return Counter(recipes)


def _scene_z_span(scene: object) -> float:
    """Return the physical Z span of a generated scene."""

    bounds = np.asarray(getattr(scene, "bounds"), dtype=np.float64)
    assert bounds.shape == (2, 3)
    return float(bounds[1, 2] - bounds[0, 2])


def _scene_xy_geometry_signature(
    scene: object,
    *,
    translation_xy: tuple[float, float] = (0.0, 0.0),
) -> Counter[tuple[object, ...]]:
    """Describe final XY geometry after an optional scene-root translation."""

    signature: Counter[tuple[object, ...]] = Counter()
    translation = np.asarray(translation_xy, dtype=np.float64)
    assert translation.shape == (2,)
    for name, geometry in getattr(scene, "geometry", {}).items():
        vertices = np.asarray(getattr(geometry, "vertices"), dtype=np.float64)
        faces = np.asarray(getattr(geometry, "faces"))
        bounds = np.asarray(getattr(geometry, "bounds"), dtype=np.float64)
        world_bounds = bounds[:, :2] + translation
        signature[
            (
                str(name),
                int(len(vertices)),
                int(len(faces)),
                tuple(np.round(world_bounds.reshape(-1), 6)),
            )
        ] += 1
    return signature


def _threemf_build_xy_translation(path: str) -> tuple[float, float]:
    """Read the standard 3MF build-item XY placement transform."""

    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("3D/3dmodel.model"))
    build_item = next(
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "item"
    )
    values = [float(value) for value in build_item.attrib["transform"].split()]
    assert len(values) == 12
    return values[9], values[10]


def _threemf_z_span(payload: bytes) -> float:
    """Read the emitted 3MF model XML and return its physical Z span."""

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        model_payloads = [
            archive.read(name)
            for name in archive.namelist()
            if name.lower().endswith(".model")
        ]

    z_values: list[float] = []
    for model_payload in model_payloads:
        root = ET.fromstring(model_payload)
        z_values.extend(
            float(element.attrib["z"])
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "vertex"
        )
    assert z_values
    return max(z_values) - min(z_values)


def _preview_form_data() -> dict[str, str]:
    return {
        "target_width_mm": "60",
        "color_mode": "4-Color (RYBW)",
        "modeling_mode": "vector",
        "quantize_colors": "32",
        "enable_cleanup": "false",
        "material_source": "material_archive",
        "selected_materials": json.dumps(_MATERIALS),
        "material_layer_count": str(_EXPECTED_MAX_LAYERS),
        "material_layer_height_mm": str(_LAYER_HEIGHT_MM),
        "material_backing_material_index": "0",
        "material_dynamic_layer_count_enabled": "true",
        "material_min_layer_count": "5",
        "material_max_layer_count": str(_EXPECTED_MAX_LAYERS),
        "material_delta_e00_tolerance": "0.5",
        "hue_weight": "0",
    }


def _generate_params() -> dict[str, object]:
    return {
        "lut_name": "__material_archive__",
        "target_width_mm": 60,
        "spacer_thick": _BACKING_THICKNESS_MM,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color (RYBW)",
        "modeling_mode": "vector",
        "quantize_colors": 32,
        "enable_cleanup": False,
        "color_layers": _EXPECTED_MAX_LAYERS,
        "layer_height_mm": _LAYER_HEIGHT_MM,
        "material_backing_material_index": 0,
        "material_dynamic_layer_count_enabled": True,
        "material_min_layer_count": 5,
        "material_max_layer_count": _EXPECTED_MAX_LAYERS,
        "material_delta_e00_tolerance": 0.5,
        "hue_weight": 0,
        "use_cached_matched_rgb": True,
    }


@pytest.mark.parametrize("batch_regions", [False, True], ids=["single", "batch"])
def test_dynamic_svg_edit_lifecycle_keeps_native_geometry_and_export_recipes(
    monkeypatch,
    batch_regions: bool,
) -> None:
    """Keep dynamic SVG recipes consistent through edit, GLB, 3MF and tiles.

    The fixture includes original paths, a compound path, and a true SVG
    gradient.  The test makes one spatial replacement, one gradient-region
    replacement, and one short custom recipe before exercising both normal and
    native large-format cached generation.
    """

    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = _InlineWorkerPool()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool
    client = TestClient(app, raise_server_exceptions=False)

    build_snapshots: list[dict[str, object]] = []
    glb_snapshots: list[dict[str, object]] = []
    threemf_snapshots: list[dict[str, object]] = []
    # Several isolated vector-engine unit modules install their module under
    # ``core.vector_engine`` during collection.  Patch the runtime class that
    # production workers import, rather than a stale collection-time alias.
    vector_engine = importlib.import_module("core.vector_engine")
    vector_processor_class = vector_engine.VectorProcessor
    real_build_mesh = vector_processor_class.build_mesh
    real_glb_export = vector_glb_preview.export_vector_glb_preview
    real_threemf_export = bambu_3mf_writer.export_scene_with_bambu_metadata

    def capture_build_mesh(processor, *args, **kwargs):
        analysis = kwargs.get("analysis")
        if analysis is None and args:
            analysis = args[0]
        assert analysis is not None
        scene = real_build_mesh(processor, *args, **kwargs)
        dynamic_info = getattr(analysis, "material_dynamic_layer_info", None)
        build_snapshots.append(
            {
                "recipes": _recipe_signature(analysis),
                "num_layers": int(getattr(analysis, "num_layers", 0)),
                "dynamic_enabled": bool(
                    isinstance(dynamic_info, dict) and dynamic_info.get("enabled")
                ),
                "z_span": _scene_z_span(scene),
            }
        )
        return scene

    # The vector branch inspects this callable before it forwards optional
    # mesh arguments.  Keep the production signature visible to that guard.
    capture_build_mesh.__signature__ = inspect.signature(real_build_mesh)

    def capture_glb_export(*args, **kwargs):
        analysis = kwargs["analysis"]
        glb_snapshots.append(
            {
                "analysis_is_lightweight": not hasattr(analysis, "matched_shapes"),
                "geometry_signature": _scene_xy_geometry_signature(kwargs["scene"]),
                "z_span": _scene_z_span(kwargs["scene"]),
            }
        )
        return real_glb_export(*args, **kwargs)

    def capture_threemf_export(*args, **kwargs):
        output_path = real_threemf_export(*args, **kwargs)
        threemf_snapshots.append(
            {
                "slot_names": tuple(str(name) for name in kwargs["slot_names"]),
                "geometry_signature": _scene_xy_geometry_signature(
                    kwargs["scene"],
                    translation_xy=_threemf_build_xy_translation(output_path),
                ),
                "z_span": _scene_z_span(kwargs["scene"]),
            }
        )
        return output_path

    monkeypatch.setattr(
        material_lut_synthesis,
        "MATERIALS_DIR",
        str(_FIXTURE_MATERIALS),
    )
    monkeypatch.setattr(
        vector_processor_class,
        "build_mesh",
        capture_build_mesh,
    )
    monkeypatch.setattr(
        vector_glb_preview,
        "export_vector_glb_preview",
        capture_glb_export,
    )
    monkeypatch.setattr(
        bambu_3mf_writer,
        "export_scene_with_bambu_metadata",
        capture_threemf_export,
    )
    monkeypatch.setattr(
        generate_router,
        "_record_material_archive_usage_safe",
        lambda *_args, **_kwargs: None,
    )
    # Tile covers are optional, independent raster thumbnails.  Keep this test
    # focused on native vector geometry and avoid spawning a cover subprocess.
    monkeypatch.setattr(
        converter_workers,
        "_rasterize_tile_for_cover",
        lambda *_args, **_kwargs: None,
    )

    try:
        preview_response = client.post(
            "/api/convert/preview",
            files={
                "image": (
                    _FIXTURE_SVG.name,
                    io.BytesIO(_FIXTURE_SVG.read_bytes()),
                    "image/svg+xml",
                ),
            },
            data=_preview_form_data(),
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        session_id = preview["session_id"]
        recipes = preview["material_dynamic_recipes"]
        actual_counts = {int(item["actual_layer_count"]) for item in recipes}
        assert min(actual_counts) == 5
        assert max(actual_counts) == _EXPECTED_MAX_LAYERS
        for recipe in recipes:
            actual_count = int(recipe["actual_layer_count"])
            assert 5 <= actual_count <= _EXPECTED_MAX_LAYERS
            assert len(recipe["actual_recipe_top_to_bottom"]) == actual_count
            assert len(recipe["print_recipe_top_to_bottom"]) == _EXPECTED_MAX_LAYERS

        session_data = store.get(session_id)
        assert session_data is not None
        assert session_data["svg_large_format_policy"]["native_tiling_supported"]
        vector_cache_path = session_data["preview_cache"]["metadata"][
            "vector_parse_clip_cache_path"
        ]
        with open(vector_cache_path, "rb") as cache_file:
            parse_cache = pickle.load(cache_file)
        clipped_shapes = parse_cache["entry"]["clipped_shapes"]
        assert len(clipped_shapes) >= 10
        assert all(
            shape["geometry"].geom_type in {"Polygon", "MultiPolygon"}
            for shape in clipped_shapes
        )

        cache = hydrate_preview_cache(session_data["preview_cache"])
        assert cache["material_matrix"].dtype == np.int32
        assert cache["material_matrix"].shape[-1] == _EXPECTED_MAX_LAYERS
        dynamic_info = cache["material_dynamic_layer_info"]
        assert dynamic_info["coverage_source"] == "native_svg_geometry"
        assert dynamic_info["benefit_curve_scope"] == "visible_svg_geometry"
        initial_matrix = np.asarray(cache["material_matrix"]).copy()

        gradient_groups_response = client.get(
            f"/api/convert/gradient-groups/{session_id}"
        )
        assert gradient_groups_response.status_code == 200
        gradient_groups = gradient_groups_response.json()["groups"]
        gradient_group = next(
            group
            for group in gradient_groups
            if int(group["boundary_pair_count"]) >= 2
        )

        spatial_region = client.post(
            "/api/convert/region-detect",
            json={"session_id": session_id, "x": 150, "y": 100},
        )
        assert spatial_region.status_code == 200, spatial_region.text
        target_map_before = np.asarray(cache["quantized_image"]).copy()
        replace_endpoint = (
            "/api/convert/region-replace-batch"
            if batch_regions else "/api/convert/region-replace"
        )
        spatial_item = {
            "replacement_color": "#686868", "click_x": 150, "click_y": 100,
        }
        spatial_replace = client.post(
            replace_endpoint,
            json={
                "session_id": session_id,
                **({"items": [spatial_item]} if batch_regions else {
                    "replacement_color": spatial_item["replacement_color"],
                }),
            },
        )
        assert spatial_replace.status_code == 200, spatial_replace.text
        assert spatial_replace.json()["material_dynamic_recipes"]

        after_spatial = hydrate_preview_cache(
            store.get(session_id)["preview_cache"]
        )
        assert not np.array_equal(
            initial_matrix,
            after_spatial["material_matrix"],
        )
        assert not np.array_equal(target_map_before, after_spatial["quantized_image"])

        gradient_item = {
            "replacement_color": "#787878",
            "gradient_group_index": gradient_group["group_index"],
            "gradient_region_index": gradient_group["regions"][0]["region_index"],
        }
        gradient_replace = client.post(
            replace_endpoint,
            json={
                "session_id": session_id,
                **({"items": [gradient_item]} if batch_regions else gradient_item),
            },
        )
        assert gradient_replace.status_code == 200, gradient_replace.text
        assert gradient_replace.json()["material_dynamic_recipes"]

        after_gradient = hydrate_preview_cache(
            store.get(session_id)["preview_cache"]
        )
        assert not np.array_equal(
            after_spatial["material_matrix"],
            after_gradient["material_matrix"],
        )

        custom_region = client.post(
            "/api/convert/region-detect",
            json={"session_id": session_id, "x": 150, "y": 100},
        )
        assert custom_region.status_code == 200, custom_region.text
        custom_recipe = [0, 1, 2, 3, 0]
        custom_apply = client.post(
            "/api/convert/apply-recipe-override",
            json={
                "session_id": session_id,
                "region_ids": [custom_region.json()["region_id"]],
                "recipe": custom_recipe,
                "layer_order": "Top2Bottom",
                "color_layers": len(custom_recipe),
                "layer_height_mm": _LAYER_HEIGHT_MM,
            },
        )
        assert custom_apply.status_code == 200, custom_apply.text

        session_data = store.get(session_id)
        assert session_data is not None
        persisted_override = session_data["recipe_overrides"][-1]
        print_recipe = tuple(persisted_override["print_recipe_top_to_bottom"])
        assert print_recipe == (0, 1, 2, 3, 0, 0, 0)
        final_cache = hydrate_preview_cache(session_data["preview_cache"])
        assert np.any(
            np.all(
                final_cache["material_matrix"] == np.asarray(print_recipe),
                axis=-1,
            )
        )

        # Edits invalidate the previous preview. Let the real scheduler finish
        # the latest edit before measuring the independent exact-3MF export.
        edited_glb_url = _wait_for_lightweight_glb(client, session_id)
        edited_glb = client.get(edited_glb_url)
        assert edited_glb.status_code == 200
        assert edited_glb.content.startswith(b"glTF")

        build_snapshots.clear()
        glb_snapshots.clear()
        threemf_snapshots.clear()
        normal_response = client.post(
            "/api/convert/generate",
            json={"session_id": session_id, "params": _generate_params()},
        )
        assert normal_response.status_code == 200, normal_response.text
        normal_payload = normal_response.json()
        normal_threemf = client.get(normal_payload["download_url"])
        normal_glb_url = normal_payload["preview_3d_url"] or (
            _wait_for_lightweight_glb(client, session_id)
        )
        normal_glb = client.get(normal_glb_url)
        assert normal_threemf.status_code == 200
        assert normal_threemf.content.startswith(b"PK")
        assert normal_glb.status_code == 200
        assert normal_glb.content.startswith(b"glTF")
        assert len(build_snapshots) == 1
        # Generate exports the exact 3MF only. Browser geometry stays on the
        # independently built lightweight preview asset.
        assert glb_snapshots == []
        assert len(threemf_snapshots) == 1

        normal_build = build_snapshots[0]
        normal_threemf_snapshot = threemf_snapshots[0]
        assert normal_build["dynamic_enabled"]
        assert normal_build["num_layers"] == _EXPECTED_MAX_LAYERS
        assert print_recipe in normal_build["recipes"]
        normal_z_span = _threemf_z_span(normal_threemf.content)
        assert normal_z_span == pytest.approx(
            normal_threemf_snapshot["z_span"],
            abs=1e-6,
        )
        assert normal_z_span >= _BACKING_THICKNESS_MM + (
            _EXPECTED_MAX_LAYERS * _LAYER_HEIGHT_MM
        )

        build_snapshots.clear()
        threemf_snapshots.clear()
        large_response = client.post(
            "/api/convert/generate-large-format",
            json={
                "session_id": session_id,
                "params": {
                    "target_height_mm": 40,
                    "tile_width_mm": 40,
                    "tile_height_mm": 40,
                    "params": _generate_params(),
                },
            },
        )
        assert large_response.status_code == 200, large_response.text
        large_payload = large_response.json()
        assert large_payload["tile_count"] == 2
        assert large_payload["warnings"] == []
        assert pool.calls.count("worker_generate_large_format_svg_native") == 1
        assert not any(
            call.startswith("worker_generate_large_format")
            and call != "worker_generate_large_format_svg_native"
            for call in pool.calls
        )

        large_download = client.get(large_payload["download_url"])
        assert large_download.status_code == 200
        assert large_download.content.startswith(b"PK")
        with zipfile.ZipFile(io.BytesIO(large_download.content)) as archive:
            tile_payloads = [
                archive.read(name)
                for name in archive.namelist()
                if name.lower().endswith(".3mf")
            ]
        assert len(tile_payloads) == 2
        assert len(build_snapshots) == 2
        assert len(threemf_snapshots) == 2
        assert any(
            print_recipe in snapshot["recipes"] for snapshot in build_snapshots
        )
        for snapshot in build_snapshots:
            assert snapshot["dynamic_enabled"]
            assert snapshot["num_layers"] == _EXPECTED_MAX_LAYERS
        for snapshot, tile_payload in zip(threemf_snapshots, tile_payloads):
            tile_z_span = _threemf_z_span(tile_payload)
            assert tile_z_span == pytest.approx(snapshot["z_span"], abs=1e-6)
            assert tile_z_span == pytest.approx(normal_z_span, abs=1e-6)
    finally:
        client.close()
        store.clear_all()
        registry.clear_all()
        app.dependency_overrides.clear()


def test_dynamic_svg_global_replacement_rebuilds_exact_recipe_after_fresh_preview(
    monkeypatch,
) -> None:
    """A replayed native SVG remap keeps its exact target through exports."""

    target_srgb = (137, 181, 59)  # #89B53B, absent from the source SVG.
    source_srgb = (249, 164, 180)  # #F9A4B4
    svg_payload = b"""<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 80\">
<path d=\"M0 0H120V80H0Z\" fill=\"#f9a4b4\"/>
<path d=\"M42 12H78V68H42Z\" fill=\"#0a141e\"/>
</svg>"""

    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = _InlineWorkerPool()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool
    client = TestClient(app, raise_server_exceptions=False)

    build_recipes: list[Counter[tuple[int, ...]]] = []
    glb_geometry_signatures: list[Counter[tuple[object, ...]]] = []
    threemf_geometry_signatures: list[Counter[tuple[object, ...]]] = []
    threemf_recipes: list[Counter[tuple[int, ...]]] = []
    recipe_by_scene_id: dict[int, Counter[tuple[int, ...]]] = {}
    vector_engine = importlib.import_module("core.vector_engine")
    vector_processor_class = vector_engine.VectorProcessor
    real_build_mesh = vector_processor_class.build_mesh
    real_glb_export = vector_glb_preview.export_vector_glb_preview
    real_threemf_export = bambu_3mf_writer.export_scene_with_bambu_metadata

    def capture_build_mesh(processor, *args, **kwargs):
        analysis = kwargs.get("analysis")
        if analysis is None and args:
            analysis = args[0]
        assert analysis is not None
        scene = real_build_mesh(processor, *args, **kwargs)
        recipe = _recipe_signature(analysis)
        build_recipes.append(recipe)
        recipe_by_scene_id[id(scene)] = recipe
        return scene

    capture_build_mesh.__signature__ = inspect.signature(real_build_mesh)

    def capture_glb_export(*args, **kwargs):
        assert not hasattr(kwargs["analysis"], "matched_shapes")
        glb_geometry_signatures.append(
            _scene_xy_geometry_signature(kwargs["scene"])
        )
        return real_glb_export(*args, **kwargs)

    def capture_threemf_export(*args, **kwargs):
        recipe = recipe_by_scene_id.get(id(kwargs["scene"]))
        assert recipe is not None
        threemf_recipes.append(recipe)
        output_path = real_threemf_export(*args, **kwargs)
        threemf_geometry_signatures.append(
            _scene_xy_geometry_signature(
                kwargs["scene"],
                translation_xy=_threemf_build_xy_translation(output_path),
            )
        )
        return output_path

    def post_preview(form_data: dict[str, str]):
        return client.post(
            "/api/convert/preview",
            files={
                "image": (
                    "dynamic_global_replacement.svg",
                    io.BytesIO(svg_payload),
                    "image/svg+xml",
                )
            },
            data=form_data,
        )

    monkeypatch.setattr(
        material_lut_synthesis,
        "MATERIALS_DIR",
        str(_FIXTURE_MATERIALS),
    )
    monkeypatch.setattr(vector_processor_class, "build_mesh", capture_build_mesh)
    monkeypatch.setattr(
        vector_glb_preview,
        "export_vector_glb_preview",
        capture_glb_export,
    )
    monkeypatch.setattr(
        bambu_3mf_writer,
        "export_scene_with_bambu_metadata",
        capture_threemf_export,
    )
    monkeypatch.setattr(
        generate_router,
        "_record_material_archive_usage_safe",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        converter_workers,
        "_rasterize_tile_for_cover",
        lambda *_args, **_kwargs: None,
    )

    try:
        initial_response = post_preview(_preview_form_data())
        assert initial_response.status_code == 200, initial_response.text
        initial_payload = initial_response.json()
        source_entry = next(
            entry
            for entry in initial_payload["palette"]
            if entry["quantized_hex"].lower() == "#f9a4b4"
        )
        replacement_regions = [
            {
                "quantized_hex": source_entry["quantized_hex"],
                "matched_hex": source_entry["matched_hex"],
                "replacement_hex": "#89b53b",
            }
        ]

        replaced_form = _preview_form_data()
        replaced_form["replacement_regions"] = json.dumps(replacement_regions)
        replacement_response = post_preview(replaced_form)
        assert replacement_response.status_code == 200, replacement_response.text
        replacement_payload = replacement_response.json()

        fresh_form = dict(replaced_form)
        fresh_form["target_width_mm"] = "61"
        fresh_response = post_preview(fresh_form)
        assert fresh_response.status_code == 200, fresh_response.text
        fresh_payload = fresh_response.json()
        fresh_recipes = fresh_payload["material_dynamic_recipes"]
        fresh_target = next(
            recipe
            for recipe in fresh_recipes
            if recipe["target_srgb"] == list(target_srgb)
        )
        assert tuple(fresh_target["actual_recipe_top_to_bottom"])
        assert len(fresh_target["print_recipe_top_to_bottom"]) == _EXPECTED_MAX_LAYERS
        assert all(
            recipe["target_srgb"] != list(source_srgb)
            for recipe in fresh_recipes
        )
        replacement_target = next(
            recipe
            for recipe in replacement_payload["material_dynamic_recipes"]
            if recipe["target_srgb"] == list(target_srgb)
        )
        expected_recipe = (
            tuple(replacement_target["actual_recipe_top_to_bottom"]),
            tuple(replacement_target["print_recipe_top_to_bottom"]),
        )
        assert expected_recipe == (
            tuple(fresh_target["actual_recipe_top_to_bottom"]),
            tuple(fresh_target["print_recipe_top_to_bottom"]),
        )
        expected_print_recipe = expected_recipe[1]

        session_id = fresh_payload["session_id"]
        normal_params = _generate_params()
        normal_params["target_width_mm"] = 61
        normal_response = client.post(
            "/api/convert/generate",
            json={"session_id": session_id, "params": normal_params},
        )
        assert normal_response.status_code == 200, normal_response.text
        normal_payload = normal_response.json()
        assert client.get(normal_payload["download_url"]).content.startswith(b"PK")
        preview_url = normal_payload["preview_3d_url"] or (
            _wait_for_lightweight_glb(client, session_id)
        )
        assert client.get(preview_url).content.startswith(b"glTF")
        assert len(build_recipes) == 1
        assert expected_print_recipe in build_recipes[0]
        assert glb_geometry_signatures == []
        assert threemf_geometry_signatures
        assert threemf_recipes == build_recipes

        build_recipes.clear()
        threemf_recipes.clear()
        large_params = dict(normal_params)
        large_params["use_cached_matched_rgb"] = False
        large_response = client.post(
            "/api/convert/generate-large-format",
            json={
                "session_id": session_id,
                "params": {
                    "target_height_mm": 40,
                    "tile_width_mm": 40,
                    "tile_height_mm": 40,
                    "params": large_params,
                },
            },
        )
        assert large_response.status_code == 200, large_response.text
        large_payload = large_response.json()
        assert large_payload["tile_count"] >= 1
        assert pool.calls.count("worker_generate_large_format_svg_native") == 1
        large_download = client.get(large_payload["download_url"])
        assert large_download.status_code == 200
        assert large_download.content.startswith(b"PK")
        assert build_recipes
        assert threemf_recipes
        assert all(expected_print_recipe in recipes for recipes in build_recipes)
        assert threemf_recipes == build_recipes
    finally:
        client.close()
        store.clear_all()
        registry.clear_all()
        app.dependency_overrides.clear()
