"""API-boundary contracts for dynamic material layer counts.

动态耗材层数的 API 边界契约测试。
"""

from __future__ import annotations

import pickle
import math
import os

import numpy as np
import pytest
from fastapi import HTTPException


def test_shared_dynamic_material_validator_normalizes_and_rejects_conflicts() -> None:
    from api.routers.converter import common

    validator = getattr(common, "_validate_dynamic_material_settings")
    assert validator(
        material_source="material_archive",
        enabled=True,
        min_layer_count=5,
        max_layer_count=10,
        delta_e00_tolerance=0.5,
        hue_weight=0.0,
    ) == (True, 5, 10, 0.5)

    with pytest.raises(HTTPException) as exc_info:
        validator(
            material_source="lut",
            enabled=True,
            min_layer_count=5,
            max_layer_count=10,
            delta_e00_tolerance=0.5,
            hue_weight=0.0,
        )
    assert exc_info.value.status_code == 422

    assert validator(
        material_source="lut",
        enabled=False,
        min_layer_count=5,
        max_layer_count=10,
        delta_e00_tolerance=0.5,
        hue_weight=1.0,
    ) == (False, 5, 10, 0.5)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_layer_count", 4),
        ("min_layer_count", True),
        ("max_layer_count", 31),
        ("delta_e00_tolerance", -0.1),
        ("delta_e00_tolerance", 5.1),
        ("delta_e00_tolerance", math.nan),
    ],
)
def test_shared_dynamic_material_validator_rejects_invalid_ranges(
    field: str,
    value: object,
) -> None:
    from api.routers.converter.common import _validate_dynamic_material_settings

    kwargs = {
        "material_source": "material_archive",
        "enabled": True,
        "min_layer_count": 5,
        "max_layer_count": 10,
        "delta_e00_tolerance": 0.5,
        "hue_weight": 0.0,
    }
    kwargs[field] = value
    with pytest.raises(HTTPException) as exc_info:
        _validate_dynamic_material_settings(**kwargs)
    assert exc_info.value.status_code == 422


def test_shared_dynamic_material_validator_rejects_order_and_hue_but_allows_native_vector() -> None:
    from api.routers.converter.common import _validate_dynamic_material_settings

    base = {
        "material_source": "material_archive",
        "enabled": True,
        "min_layer_count": 5,
        "max_layer_count": 10,
        "delta_e00_tolerance": 0.5,
        "hue_weight": 0.0,
    }
    for changes in (
        {"min_layer_count": 8, "max_layer_count": 7},
        {"hue_weight": 0.01},
    ):
        with pytest.raises(HTTPException) as exc_info:
            _validate_dynamic_material_settings(**(base | changes))
        assert exc_info.value.status_code == 422

    assert _validate_dynamic_material_settings(
        **(base | {"native_svg_vector": True})
    ) == (True, 5, 10, 0.5)


def test_dynamic_candidate_error_is_pickle_safe_with_context() -> None:
    from core.material_dynamic_solver import DynamicMaterialCandidateError

    original = DynamicMaterialCandidateError(
        "no candidate",
        target_srgb=(12, 34, 56),
        layer_count=6,
        phase="exact_search",
    )

    restored = pickle.loads(pickle.dumps(original))

    assert isinstance(restored, DynamicMaterialCandidateError)
    assert restored.target_srgb == (12, 34, 56)
    assert restored.layer_count == 6
    assert restored.phase == "exact_search"
    assert str(restored) == str(original)


def test_preview_response_dynamic_fields_are_optional_for_old_clients() -> None:
    from api.schemas.responses import PreviewResponse

    recipes = PreviewResponse.model_fields["material_dynamic_recipes"]
    benefit = PreviewResponse.model_fields["material_layer_benefit_curve"]

    assert recipes.default is None
    assert benefit.default is None
    assert recipes.is_required() is False
    assert benefit.is_required() is False


def _valid_dynamic_recipe_payload() -> dict:
    return {
        "target_srgb": [10, 20, 30],
        "matched_srgb": [11, 22, 33],
        "actual_layer_count": 5,
        "padding_layer_count": 2,
        "actual_recipe_top_to_bottom": [0, 1, 2, 3, 0],
        "print_recipe_top_to_bottom": [0, 1, 2, 3, 0, 4, 4],
        "selected_delta_e00": 0.2,
        "best_range_delta_e00": 0.1,
        "fixed_max_delta_e00": 0.3,
        "delta_e00_sacrifice": 0.1,
        "layer_cap_options": [
            {
                "max_effective_layer_count": cap,
                "actual_layer_count": 5,
                "matched_srgb": [11, 22, 33],
                "actual_recipe_top_to_bottom": [0, 1, 2, 3, 0],
                "print_recipe_top_to_bottom": [0, 1, 2, 3, 0, 4, 4],
                "delta_e00": 0.2,
            }
            for cap in (5, 6, 7)
        ],
    }


def test_dynamic_response_models_validate_nested_public_contract() -> None:
    from pydantic import ValidationError

    from api.schemas.dynamic_material import DynamicMaterialResultResponse

    payload = _valid_dynamic_recipe_payload()
    result = DynamicMaterialResultResponse.model_validate(
        {
            "material_dynamic_recipes": [payload],
                "material_layer_benefit_curve": [
                    {
                        "max_effective_layer_count": cap,
                        "weighted_mean_delta_e00": 0.2,
                        "marginal_delta_e00_reduction": 0.0,
                    }
                    for cap in (5, 6, 7)
                ],
        }
    )
    assert result.material_dynamic_recipes is not None
    assert result.material_dynamic_recipes[0].target_srgb == (10, 20, 30)

    invalid_rgb = dict(payload)
    invalid_rgb["target_srgb"] = [10, 20, 999]
    with pytest.raises(ValidationError):
        DynamicMaterialResultResponse.model_validate(
            {"material_dynamic_recipes": [invalid_rgb]}
        )

    invalid_length = dict(payload)
    invalid_length["actual_recipe_top_to_bottom"] = [0, 1]
    with pytest.raises(ValidationError):
        DynamicMaterialResultResponse.model_validate(
            {"material_dynamic_recipes": [invalid_length]}
        )


def test_edit_responses_share_typed_dynamic_result_fields() -> None:
    from api.schemas.converter import RegionReplaceResponse
    from api.schemas.responses import (
        ColorReplaceResponse,
        RecipeOverrideApplyResponse,
        ResetReplacementsResponse,
    )

    for model_type in (
        ColorReplaceResponse,
        RegionReplaceResponse,
        RecipeOverrideApplyResponse,
        ResetReplacementsResponse,
    ):
        assert "material_dynamic_recipes" in model_type.model_fields
        assert "material_layer_benefit_curve" in model_type.model_fields


def test_request_schema_defaults_and_dynamic_hue_validation() -> None:
    from pydantic import ValidationError

    from api.schemas.converter import ConvertGenerateRequest, ConvertPreviewRequest

    for model_type in (ConvertPreviewRequest, ConvertGenerateRequest):
        fields = model_type.model_fields
        assert fields["material_dynamic_layer_count_enabled"].default is False
        assert fields["material_min_layer_count"].default == 5
        assert fields["material_max_layer_count"].default == 10
        assert fields["material_delta_e00_tolerance"].default == pytest.approx(0.5)

        with pytest.raises(ValidationError):
            model_type.model_validate(
                {
                    "material_dynamic_layer_count_enabled": True,
                    "hue_weight": 0.5,
                }
            )


def test_generate_request_inherits_dynamic_settings_from_preview_session() -> None:
    from api.routers.converter.common import (
        _resolve_session_dynamic_material_settings,
    )
    from api.schemas.converter import ConvertGenerateRequest

    request = ConvertGenerateRequest.model_validate({"lut_name": "test-lut"})
    session_data = {
        "material_dynamic_layer_count_enabled": True,
        "material_min_layer_count": 6,
        "material_max_layer_count": 9,
        "material_delta_e00_tolerance": 0.4,
    }

    resolved = _resolve_session_dynamic_material_settings(
        session_data=session_data,
        request=request,
        material_source="material_archive",
    )

    assert resolved == (True, 6, 9, pytest.approx(0.4))


def test_generate_request_rejects_explicit_dynamic_preview_mismatch() -> None:
    from api.routers.converter.common import (
        _resolve_session_dynamic_material_settings,
    )
    from api.schemas.converter import ConvertGenerateRequest

    request = ConvertGenerateRequest.model_validate(
        {
            "lut_name": "test-lut",
            "material_dynamic_layer_count_enabled": False,
        }
    )
    session_data = {
        "material_dynamic_layer_count_enabled": True,
        "material_min_layer_count": 5,
        "material_max_layer_count": 10,
        "material_delta_e00_tolerance": 0.5,
    }

    with pytest.raises(HTTPException) as exc_info:
        _resolve_session_dynamic_material_settings(
            session_data=session_data,
            request=request,
            material_source="material_archive",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "dynamic_material_preview_mismatch"
    assert exc_info.value.detail["fields"] == [
        "material_dynamic_layer_count_enabled"
    ]


def test_generate_request_rejects_dynamic_backing_mismatch_with_field_name() -> None:
    """A cached dynamic matrix cannot be reused with another backing slot."""

    from api.routers.converter.common import (
        _resolve_session_dynamic_material_settings,
    )
    from api.schemas.converter import ConvertGenerateRequest

    request = ConvertGenerateRequest.model_validate(
        {
            "lut_name": "test-lut",
            "material_backing_material_index": 1,
        }
    )
    session_data = {
        "selected_materials": ["base", "red"],
        "material_backing_material_index": 0,
        "material_dynamic_layer_count_enabled": True,
        "material_min_layer_count": 5,
        "material_max_layer_count": 7,
        "material_delta_e00_tolerance": 0.5,
    }

    with pytest.raises(HTTPException) as exc_info:
        _resolve_session_dynamic_material_settings(
            session_data=session_data,
            request=request,
            material_source="material_archive",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "dynamic_material_preview_mismatch"
    assert exc_info.value.detail["fields"] == [
        "material_backing_material_index"
    ]


def test_dynamic_material_selection_rejects_duplicate_cache_identities() -> None:
    from api.routers.converter.common import _validate_unique_dynamic_material_selection

    _validate_unique_dynamic_material_selection(["brand/base", "brand/red"])

    with pytest.raises(HTTPException) as exc_info:
        _validate_unique_dynamic_material_selection(
            ["Brand/Base", " brand/base "]
        )

    assert exc_info.value.status_code == 422
    assert "duplicate" in str(exc_info.value.detail).lower()


def test_generate_request_allows_dynamic_native_svg_derived_flow() -> None:
    from api.routers.converter.common import (
        _resolve_session_dynamic_material_settings,
    )
    from api.schemas.converter import ConvertGenerateRequest

    request = ConvertGenerateRequest.model_validate({"lut_name": "test-lut"})

    assert _resolve_session_dynamic_material_settings(
        session_data={"material_dynamic_layer_count_enabled": True},
        request=request,
        material_source="material_archive",
        native_svg_vector=True,
    ) == (True, 5, 10, 0.5)


def test_dynamic_relief_depth_ignores_legacy_fixed_layer_count() -> None:
    from api.routers.converter.common import (
        _resolve_material_archive_optical_layer_count,
    )

    resolved = _resolve_material_archive_optical_layer_count(
        session_data={
            "material_dynamic_layer_count_enabled": True,
            "material_min_layer_count": 5,
            "material_max_layer_count": 6,
            "material_layer_count": 10,
        },
        material_layer_count=10,
    )

    assert resolved == 6


@pytest.mark.parametrize(
    ("phase", "expected_status", "expected_code"),
    [
        ("exact_search", 409, "dynamic_material_no_candidate"),
        ("fixed_max_baseline", 409, "dynamic_material_no_candidate"),
        ("runtime_load", 503, "dynamic_material_solver_unavailable"),
        ("full_stack_simulation", 503, "dynamic_material_solver_unavailable"),
    ],
)
def test_dynamic_candidate_error_maps_to_structured_http_detail(
    phase: str,
    expected_status: int,
    expected_code: str,
) -> None:
    from api.errors import to_http_exception
    from core.material_dynamic_solver import DynamicMaterialCandidateError

    error = DynamicMaterialCandidateError(
        "local details must not leak",
        target_srgb=(12, 34, 56),
        layer_count=6,
        phase=phase,
    )

    mapped = to_http_exception(error, "preview")

    assert mapped.status_code == expected_status
    assert mapped.detail == {
        "code": expected_code,
        "message": (
            "No exact dynamic material candidate is available for this target."
            if expected_status == 409
            else "The exact dynamic material solver is temporarily unavailable."
        ),
        "target_srgb": [12, 34, 56],
        "layer_count": 6,
        "stage": phase,
    }


def test_dynamic_solver_error_maps_to_structured_503() -> None:
    from api.errors import to_http_exception
    from core.material_dynamic_solver import DynamicMaterialSolverError

    mapped = to_http_exception(
        DynamicMaterialSolverError("engine internals"),
        "preview",
    )

    assert mapped.status_code == 503
    assert mapped.detail["code"] == "dynamic_material_solver_unavailable"
    assert "engine internals" not in mapped.detail["message"]


def test_core_wrapper_reraises_original_typed_dynamic_failure() -> None:
    from core import converter
    from core.material_dynamic_solver import DynamicMaterialCandidateError

    failure = DynamicMaterialCandidateError(
        "no candidate",
        target_srgb=(12, 34, 56),
        layer_count=6,
        phase="exact_search",
    )
    ctx = {
        "error": "generic pipeline status",
        "material_dynamic_layer_error": {"exception": failure},
    }

    reraise = getattr(converter, "_raise_dynamic_material_pipeline_error")
    with pytest.raises(DynamicMaterialCandidateError) as exc_info:
        reraise(ctx)
    assert exc_info.value is failure


def test_preview_worker_forwards_dynamic_settings_to_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.workers.converter_workers import worker_generate_preview
    from core import converter

    captured: dict[str, object] = {}

    def fake_generate_preview_cached(**kwargs: object):
        captured.update(kwargs)
        return np.zeros((2, 2, 3), dtype=np.uint8), {}, "ok"

    monkeypatch.setattr(
        converter,
        "generate_preview_cached",
        fake_generate_preview_cached,
    )

    result = worker_generate_preview(
        "input.png",
        "__material_archive__",
        60.0,
        "4-Color (RYBW)",
        "high-fidelity",
        None,
        None,
        48,
        True,
        material_source="material_archive",
        selected_materials=["base", "red"],
        material_backing_material_index=1,
        material_dynamic_layer_count_enabled=True,
        material_min_layer_count=6,
        material_max_layer_count=9,
        material_delta_e00_tolerance=0.4,
    )
    try:
        assert captured["material_backing_material_index"] == 1
        assert captured["material_dynamic_layer_count_enabled"] is True
        assert captured["material_min_layer_count"] == 6
        assert captured["material_max_layer_count"] == 9
        assert captured["material_delta_e00_tolerance"] == pytest.approx(0.4)
    finally:
        for key in (
            "preview_png_path",
            "raw_preview_png_path",
            "cache_data_path",
            "vector_parse_clip_cache_path",
            "gradient_region_id_map_path",
        ):
            path = result.get(key)
            if isinstance(path, str) and os.path.exists(path):
                os.unlink(path)


def test_batch_worker_forwards_dynamic_settings_to_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.workers.converter_workers import worker_batch_convert_item
    from core import converter

    captured: dict[str, object] = {}

    def fake_convert_image_to_3d(**kwargs: object):
        captured.update(kwargs)
        return None, None, None, "expected test stop", None

    monkeypatch.setattr(converter, "convert_image_to_3d", fake_convert_image_to_3d)

    result = worker_batch_convert_item(
        "input.png",
        "__material_archive__",
        60.0,
        0.8,
        "Double-sided",
        "4-Color (RYBW)",
        "high-fidelity",
        None,
        None,
        48,
        True,
        "batch-contract-",
        material_source="material_archive",
        selected_materials=["base", "red"],
        material_backing_material_index=1,
        material_dynamic_layer_count_enabled=True,
        material_min_layer_count=6,
        material_max_layer_count=9,
        material_delta_e00_tolerance=0.4,
    )

    assert result["threemf_path"] is None
    assert captured["material_backing_material_index"] == 1
    assert captured["material_dynamic_layer_count_enabled"] is True
    assert captured["material_min_layer_count"] == 6
    assert captured["material_max_layer_count"] == 9
    assert captured["material_delta_e00_tolerance"] == pytest.approx(0.4)
