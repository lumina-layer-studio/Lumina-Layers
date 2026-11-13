"""Real-boundary lifecycle coverage for dynamic material layers.

动态耗材层数的真实边界生命周期覆盖。
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import hydrate_preview_cache
from api.session_store import SessionStore


_MATERIALS = [
    "white",
    "red",
    "blue",
    "yellow",
]
_FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "dynamic_material_lifecycle.ppm"
_FIXTURE_MATERIALS = Path(__file__).parent / "fixtures" / "dynamic_material_materials"


class _InlineWorkerPool:
    """Execute production worker entry points inline at their real file boundary."""

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


def _png_upload_from_fixture() -> tuple[str, io.BytesIO, str]:
    with Image.open(_FIXTURE_IMAGE) as fixture:
        buffer = io.BytesIO()
        fixture.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return ("dynamic-material-lifecycle.png", buffer, "image/png")


def _hex(rgb: list[int]) -> str:
    return "#" + "".join(f"{int(channel):02x}" for channel in rgb)


def _assert_dynamic_quality_contract(
    recipes: list[dict],
    *,
    maximum: int,
    backing_index: int,
    tolerance: float,
) -> None:
    assert len({int(item["actual_layer_count"]) for item in recipes}) >= 2
    for item in recipes:
        actual_count = int(item["actual_layer_count"])
        padding_count = int(item["padding_layer_count"])
        actual = [int(value) for value in item["actual_recipe_top_to_bottom"]]
        printable = [int(value) for value in item["print_recipe_top_to_bottom"]]

        assert len(actual) == actual_count
        assert len(printable) == maximum
        assert padding_count == maximum - actual_count
        assert printable[:actual_count] == actual
        # Top-to-Bottom stores the viewing surface first, so backing padding
        # belongs only at the tail (the non-viewing side).
        assert printable[actual_count:] == [backing_index] * padding_count
        assert float(item["selected_delta_e00"]) <= (
            float(item["best_range_delta_e00"]) + tolerance + 1e-12
        )
        assert float(item["selected_delta_e00"]) <= (
            float(item["fixed_max_delta_e00"]) + tolerance + 1e-12
        )


def test_real_preview_replace_manual_generate_and_close_download_lifecycle() -> None:
    """Exercise real solver/workers across the converter HTTP lifecycle.

    预览与最终 3MF 调用真实生产 worker；替换在路由同步路径中复用同一份
    精确求解逻辑。仅禁用异步 GLB 副产物，以免与本测试验证的主下载生命周期
    产生无关后台竞争。
    """

    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = _InlineWorkerPool()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool
    client = TestClient(app, raise_server_exceptions=False)

    try:
        with (
            patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value=None,
            ),
            patch(
                "api.routers.converter.generate._record_material_archive_usage_safe",
                return_value=None,
            ),
            patch(
                "core.material_lut_synthesis.MATERIALS_DIR",
                str(_FIXTURE_MATERIALS),
            ),
        ):
            preview_response = client.post(
                "/api/convert/preview",
                files={"image": _png_upload_from_fixture()},
                data={
                    "target_width_mm": "10",
                    "modeling_mode": "high-fidelity",
                    "quantize_colors": "8",
                    "enable_cleanup": "false",
                    "material_source": "material_archive",
                    "selected_materials": json.dumps(
                        _MATERIALS,
                        ensure_ascii=False,
                    ),
                    "material_layer_height_mm": "0.08",
                    "material_backing_material_index": "0",
                    "material_dynamic_layer_count_enabled": "true",
                    "material_min_layer_count": "5",
                    "material_max_layer_count": "7",
                    "material_delta_e00_tolerance": "0.5",
                    "hue_weight": "0",
                },
            )

            assert preview_response.status_code == 200, preview_response.text
            preview = preview_response.json()
            session_id = preview["session_id"]
            recipes = preview["material_dynamic_recipes"]
            curve = preview["material_layer_benefit_curve"]
            assert recipes
            assert curve
            _assert_dynamic_quality_contract(
                recipes,
                maximum=7,
                backing_index=0,
                tolerance=0.5,
            )

            session_data = store.get(session_id)
            cache = hydrate_preview_cache(session_data["preview_cache"])
            initial_matrix = np.asarray(cache["material_matrix"]).copy()
            initial_target_map = np.asarray(cache["quantized_image"]).copy()
            target_map = np.asarray(cache["quantized_image"], dtype=np.uint8)
            solid = np.asarray(cache["mask_solid"], dtype=bool)
            weighted_selected = 0.0
            weighted_fixed = 0.0
            weighted_pixels = 0
            for item in recipes:
                target = np.asarray(item["target_srgb"], dtype=np.uint8)
                count = int(np.count_nonzero(np.all(target_map == target, axis=-1) & solid))
                weighted_selected += count * float(item["selected_delta_e00"])
                weighted_fixed += count * float(item["fixed_max_delta_e00"])
                weighted_pixels += count
            assert weighted_pixels == int(np.count_nonzero(solid))
            assert weighted_selected / weighted_pixels <= (
                weighted_fixed / weighted_pixels + 0.5 + 1e-12
            )

            selected_recipe = recipes[0]
            selected_hex = _hex(selected_recipe["matched_srgb"])
            replacement_response = client.post(
                "/api/convert/replace-color",
                json={
                    "session_id": session_id,
                    "selected_color": selected_hex,
                    "replacement_color": "#787878",
                },
            )
            assert replacement_response.status_code == 200, replacement_response.text
            replacement = replacement_response.json()
            assert replacement["material_dynamic_recipes"]
            assert replacement["material_layer_benefit_curve"]

            replaced_cache = hydrate_preview_cache(
                store.get(session_id)["preview_cache"],
            )
            np.testing.assert_equal(
                replacement["material_dynamic_recipes"],
                replaced_cache["material_dynamic_layer_info"]["colors"],
            )
            np.testing.assert_equal(
                replacement["material_layer_benefit_curve"],
                replaced_cache["material_dynamic_layer_info"]["benefit_curve"],
            )

            region_response = client.post(
                "/api/convert/region-detect",
                json={"session_id": session_id, "x": 1, "y": 1},
            )
            assert region_response.status_code == 200, region_response.text
            region_id = region_response.json()["region_id"]
            manual_recipe = replacement["material_dynamic_recipes"][0][
                "actual_recipe_top_to_bottom"
            ]
            manual_response = client.post(
                "/api/convert/apply-recipe-override",
                json={
                    "session_id": session_id,
                    "region_ids": [region_id],
                    "recipe": manual_recipe,
                    "layer_order": "Top2Bottom",
                    "color_layers": len(manual_recipe),
                    "layer_height_mm": 0.08,
                },
            )
            assert manual_response.status_code == 200, manual_response.text
            persisted_override = store.get(session_id)["recipe_overrides"][-1]
            assert persisted_override["actual_recipe_top_to_bottom"] == manual_recipe
            assert len(persisted_override["print_recipe_top_to_bottom"]) == 7
            assert persisted_override["print_recipe_top_to_bottom"][len(manual_recipe):] == (
                [0] * (7 - len(manual_recipe))
            )

            def reselect_manual_region() -> list[str]:
                for operation in ("clear", "point-toggle"):
                    state = store.get(session_id)
                    response = client.post(
                        "/api/convert/selection/mutate",
                        json={
                            "session_id": session_id,
                            "operation": operation,
                            "base_selection_revision": state.get("editor_selection_revision", 0),
                            "content_revision": state.get("visible_region_cache_generation", 0),
                            "x": 1,
                            "y": 1,
                        },
                    )
                    assert response.status_code == 200, response.text
                return response.json()["region_ids"]

            def assert_selected_recipe(ids: list[str], expected: list[int]) -> None:
                response = client.post(
                    "/api/convert/region-recipe",
                    json={"session_id": session_id, "region_ids": ids},
                )
                assert response.status_code == 200, response.text
                assert response.json()["recipes"][0]["recipe"] == expected

            # A new gesture creates a different synthetic ID for the same
            # pixels. Reads must retain the saved actual depth across edits
            # and history restoration, including real backing-colour layers.
            reselected_ids = reselect_manual_region()
            assert reselected_ids != [region_id]
            assert_selected_recipe(reselected_ids, manual_recipe)
            second_recipe = [2, 1, 0, 1, 0, 0]
            second_apply = client.post(
                "/api/convert/apply-recipe-override",
                json={
                    "session_id": session_id,
                    "region_ids": reselected_ids,
                    "recipe": second_recipe,
                    "layer_order": "Top2Bottom",
                    "color_layers": len(second_recipe),
                    "layer_height_mm": 0.08,
                },
            )
            assert second_apply.status_code == 200, second_apply.text
            for action, expected in (("undo", manual_recipe), ("redo", second_recipe)):
                restored = client.post(
                    "/api/convert/replacement-history",
                    json={"session_id": session_id, "action": action},
                )
                assert restored.status_code == 200, restored.text
                assert_selected_recipe(restored.json()["selection"]["region_ids"], expected)
            assert_selected_recipe(reselect_manual_region(), second_recipe)

            reset_response = client.post(
                "/api/convert/reset-replacements",
                json={"session_id": session_id},
            )
            assert reset_response.status_code == 200, reset_response.text
            reset = reset_response.json()
            assert reset["material_dynamic_recipes"] == recipes
            assert reset["material_layer_benefit_curve"] == curve
            assert reset["material_layer_benefit_scope"] == "all_printable_pixels"
            assert reset["material_layer_benefit_pixel_count"] == weighted_pixels
            reset_session = store.get(session_id)
            assert reset_session["recipe_overrides"] == []
            assert reset_session["recipe_override_count"] == 0
            reset_cache = hydrate_preview_cache(reset_session["preview_cache"])
            np.testing.assert_array_equal(
                reset_cache["material_matrix"], initial_matrix
            )
            np.testing.assert_array_equal(
                reset_cache["quantized_image"], initial_target_map
            )

            # A subsequent automatic edit must operate on the restored
            # preview authority, not retain the reset manual override.
            follow_up_response = client.post(
                "/api/convert/replace-color",
                json={
                    "session_id": session_id,
                    "selected_color": selected_hex,
                    "replacement_color": "#686868",
                },
            )
            assert follow_up_response.status_code == 200, follow_up_response.text
            follow_up = follow_up_response.json()
            assert follow_up["material_dynamic_recipes"]
            assert follow_up["material_layer_benefit_curve"]
            assert follow_up["material_layer_benefit_scope"] == "all_printable_pixels"

            generate_response = client.post(
                "/api/convert/generate",
                json={
                    "session_id": session_id,
                    "params": {
                        "lut_name": "__material_archive__",
                        "target_width_mm": 10,
                        "modeling_mode": "high-fidelity",
                        "quantize_colors": 8,
                        "enable_cleanup": False,
                        "color_layers": 7,
                        "layer_height_mm": 0.08,
                        "material_backing_material_index": 0,
                        "material_dynamic_layer_count_enabled": True,
                        "material_min_layer_count": 5,
                        "material_max_layer_count": 7,
                        "material_delta_e00_tolerance": 0.5,
                        "hue_weight": 0,
                    },
                },
            )
            assert generate_response.status_code == 200, generate_response.text
            download_url = generate_response.json()["download_url"]

            close_response = client.post(
                "/api/session/close",
                json={"session_id": session_id},
            )
            assert close_response.status_code == 200, close_response.text
            assert store.get(session_id) is None

            download_response = client.get(download_url)
            assert download_response.status_code == 200, download_response.text
            assert download_response.content.startswith(b"PK")

        assert pool.calls.count("worker_generate_preview") == 1
        assert pool.calls.count("worker_rebuild_dynamic_material_replacement") == 0
        assert pool.calls.count("worker_generate_model") == 1
    finally:
        client.close()
        store.clear_all()
        registry.clear_all()
        app.dependency_overrides.clear()
