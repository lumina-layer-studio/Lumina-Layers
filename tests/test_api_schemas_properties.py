"""Property-based tests for API Schema models (api/schemas/).

Uses Hypothesis to verify correctness properties across arbitrary inputs.
验证 Pydantic Schema 模型的通用正确性属性。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple, Type

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from api.schemas import (
    # Enums
    BackingColor,
    CalibrationColorMode,
    ColorMode,
    ExtractorPage,
    ModelingMode,
    StructureMode,
    AutoHeightMode,
    # Models
    CalibrationGenerateRequest,
    ColorMergePreviewRequest,
    ColorReplaceRequest,
    ColorReplacementItem,
    ConvertBatchRequest,
    ConvertGenerateRequest,
    ConvertPreviewRequest,
    ExtractorExtractRequest,
    ExtractorManualFixRequest,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies for enum types
# ---------------------------------------------------------------------------

st_color_mode = st.sampled_from(list(ColorMode))
st_modeling_mode = st.sampled_from(list(ModelingMode))
st_structure_mode = st.sampled_from(list(StructureMode))
st_auto_height_mode = st.sampled_from(list(AutoHeightMode))
st_calibration_color_mode = st.sampled_from(list(CalibrationColorMode))
st_extractor_page = st.sampled_from(list(ExtractorPage))
st_backing_color = st.sampled_from(list(BackingColor))

# ---------------------------------------------------------------------------
# Hypothesis strategies for hex color strings
# ---------------------------------------------------------------------------

st_hex_color = st.from_regex(r"#[0-9a-f]{6}", fullmatch=True)

# ---------------------------------------------------------------------------
# Hypothesis strategies for valid model instances
# ---------------------------------------------------------------------------

st_non_empty_str = st.text(min_size=1, max_size=50).filter(lambda s: s.strip() != "")


@st.composite
def st_convert_preview_request(draw: st.DrawFn) -> ConvertPreviewRequest:
    """Generate a valid ConvertPreviewRequest instance."""
    return ConvertPreviewRequest(
        lut_name=draw(st_non_empty_str),
        target_width_mm=draw(st.floats(min_value=10, max_value=400, allow_nan=False)),
        auto_bg=draw(st.booleans()),
        bg_tol=draw(st.integers(min_value=0, max_value=150)),
        color_mode=draw(st_color_mode),
        modeling_mode=draw(st_modeling_mode),
        quantize_colors=draw(st.integers(min_value=8, max_value=256)),
        enable_cleanup=draw(st.booleans()),
    )


@st.composite
def st_color_replacement_item(draw: st.DrawFn) -> ColorReplacementItem:
    """Generate a valid ColorReplacementItem instance."""
    return ColorReplacementItem(
        quantized_hex=draw(st_hex_color),
        matched_hex=draw(st_hex_color),
        replacement_hex=draw(st_hex_color),
    )


@st.composite
def st_convert_generate_request(draw: st.DrawFn) -> ConvertGenerateRequest:
    """Generate a valid ConvertGenerateRequest instance."""
    return ConvertGenerateRequest(
        lut_name=draw(st_non_empty_str),
        target_width_mm=draw(st.floats(min_value=10, max_value=400, allow_nan=False)),
        spacer_thick=draw(st.floats(min_value=0.2, max_value=3.5, allow_nan=False)),
        structure_mode=draw(st_structure_mode),
        auto_bg=draw(st.booleans()),
        bg_tol=draw(st.integers(min_value=0, max_value=150)),
        color_mode=draw(st_color_mode),
        modeling_mode=draw(st_modeling_mode),
        quantize_colors=draw(st.integers(min_value=8, max_value=256)),
        enable_cleanup=draw(st.booleans()),
        separate_backing=draw(st.booleans()),
        add_loop=draw(st.booleans()),
        loop_width=draw(st.floats(min_value=2, max_value=10, allow_nan=False)),
        loop_length=draw(st.floats(min_value=4, max_value=15, allow_nan=False)),
        loop_hole=draw(st.floats(min_value=1, max_value=5, allow_nan=False)),
        loop_pos=draw(st.none() | st.tuples(
            st.floats(allow_nan=False, allow_infinity=False),
            st.floats(allow_nan=False, allow_infinity=False),
        )),
        enable_relief=draw(st.booleans()),
        color_height_map=draw(st.none() | st.dictionaries(
            st_hex_color,
            st.floats(min_value=0, max_value=20, allow_nan=False),
            max_size=5,
        )),
        heightmap_max_height=draw(st.floats(min_value=0.08, max_value=15.0, allow_nan=False)),
        enable_outline=draw(st.booleans()),
        outline_width=draw(st.floats(min_value=0.5, max_value=10.0, allow_nan=False)),
        enable_cloisonne=draw(st.booleans()),
        wire_width_mm=draw(st.floats(min_value=0.2, max_value=1.2, allow_nan=False)),
        wire_height_mm=draw(st.floats(min_value=0.04, max_value=1.0, allow_nan=False)),
        enable_coating=draw(st.booleans()),
        coating_height_mm=draw(st.floats(min_value=0.04, max_value=0.12, allow_nan=False)),
        replacement_regions=draw(st.none() | st.lists(
            st_color_replacement_item(), max_size=3,
        )),
        free_color_set=draw(st.none() | st.frozensets(st_hex_color, max_size=3)),
    )


@st.composite
def st_convert_batch_request(draw: st.DrawFn) -> ConvertBatchRequest:
    """Generate a valid ConvertBatchRequest instance."""
    return ConvertBatchRequest(params=draw(st_convert_generate_request()))


@st.composite
def st_color_replace_request(draw: st.DrawFn) -> ColorReplaceRequest:
    """Generate a valid ColorReplaceRequest instance."""
    return ColorReplaceRequest(
        session_id=draw(st_non_empty_str),
        selected_color=draw(st_hex_color),
        replacement_color=draw(st_hex_color),
    )


@st.composite
def st_color_merge_preview_request(draw: st.DrawFn) -> ColorMergePreviewRequest:
    """Generate a valid ColorMergePreviewRequest instance."""
    return ColorMergePreviewRequest(
        session_id=draw(st_non_empty_str),
        merge_enable=draw(st.booleans()),
        merge_threshold=draw(st.floats(min_value=0.1, max_value=5.0, allow_nan=False)),
        merge_max_distance=draw(st.integers(min_value=5, max_value=50)),
    )


@st.composite
def st_extractor_extract_request(draw: st.DrawFn) -> ExtractorExtractRequest:
    """Generate a valid ExtractorExtractRequest instance."""
    corner_points = [
        draw(st.tuples(st.integers(min_value=0, max_value=5000),
                        st.integers(min_value=0, max_value=5000)))
        for _ in range(4)
    ]
    return ExtractorExtractRequest(
        color_mode=draw(st_calibration_color_mode),
        corner_points=corner_points,
        offset_x=draw(st.integers(min_value=-30, max_value=30)),
        offset_y=draw(st.integers(min_value=-30, max_value=30)),
        zoom=draw(st.floats(min_value=0.8, max_value=1.2, allow_nan=False)),
        distortion=draw(st.floats(min_value=-0.2, max_value=0.2, allow_nan=False)),
        white_balance=draw(st.booleans()),
        vignette_correction=draw(st.booleans()),
        page=draw(st_extractor_page),
    )


@st.composite
def st_extractor_manual_fix_request(draw: st.DrawFn) -> ExtractorManualFixRequest:
    """Generate a valid ExtractorManualFixRequest instance."""
    return ExtractorManualFixRequest(
        lut_path=draw(st_non_empty_str),
        cell_coord=draw(st.tuples(
            st.integers(min_value=0, max_value=100),
            st.integers(min_value=0, max_value=100),
        )),
        override_color=draw(st_hex_color),
    )


@st.composite
def st_calibration_generate_request(draw: st.DrawFn) -> CalibrationGenerateRequest:
    """Generate a valid CalibrationGenerateRequest instance."""
    return CalibrationGenerateRequest(
        color_mode=draw(st_calibration_color_mode),
        block_size=draw(st.integers(min_value=3, max_value=10)),
        gap=draw(st.floats(min_value=0.4, max_value=2.0, allow_nan=False)),
        backing=draw(st_backing_color),
    )


# ---------------------------------------------------------------------------
# Combined strategy: any valid schema instance
# ---------------------------------------------------------------------------

st_any_schema = (
    st_convert_preview_request()
    | st_convert_generate_request()
    | st_convert_batch_request()
    | st_color_replace_request()
    | st_color_merge_preview_request()
    | st_extractor_extract_request()
    | st_extractor_manual_fix_request()
    | st_calibration_generate_request()
    | st_color_replacement_item()
)


# ===========================================================================
# Property 1: Schema Serialization Round-Trip
# Feature: fastapi-backend-scaffold, Property 1: Schema 序列化 Round-Trip
# ===========================================================================


# **Validates: Requirements 11.1**
@given(instance=st_any_schema)
@settings(max_examples=100)
def test_schema_serialization_round_trip(instance: BaseModel) -> None:
    """Property 1: For any valid Schema instance, serializing to JSON via
    model_dump_json() and deserializing via model_validate_json() should
    produce an equivalent model object.

    **Validates: Requirements 11.1**
    """
    json_str = instance.model_dump_json()
    restored = type(instance).model_validate_json(json_str)
    assert instance == restored, (
        f"Round-trip failed for {type(instance).__name__}: "
        f"original={instance!r}, restored={restored!r}"
    )


# ===========================================================================
# Property 2: Valid Data Passes Validation
# Feature: fastapi-backend-scaffold, Property 2: 有效数据验证通过
# ===========================================================================


# **Validates: Requirements 3.6**
@given(instance=st_any_schema)
@settings(max_examples=100)
def test_valid_data_passes_validation(instance: BaseModel) -> None:
    """Property 2: For any randomly generated data dict that conforms to field
    constraints (type, range, enum values), instantiating any Schema model
    should succeed without raising ValidationError.

    **Validates: Requirements 3.6**
    """
    # The instance was already created successfully by the strategy.
    # Re-validate from dict to confirm model_validate also works.
    data = instance.model_dump()
    try:
        restored = type(instance).model_validate(data)
    except ValidationError as exc:
        raise AssertionError(
            f"Valid data rejected for {type(instance).__name__}: {exc}"
        ) from exc
    assert restored == instance


# ===========================================================================
# Property 3: Out-of-Range Values Are Rejected
# Feature: fastapi-backend-scaffold, Property 3: 超出范围值被拒绝
# ===========================================================================

# Table of (Model, field_name, min_val, max_val) for constrained numeric fields
CONSTRAINED_FIELDS: List[Tuple[Type[BaseModel], str, float, float]] = [
    (ConvertPreviewRequest, "target_width_mm", 10, 400),
    (ConvertPreviewRequest, "bg_tol", 0, 150),
    (ConvertPreviewRequest, "quantize_colors", 8, 256),
    (ConvertGenerateRequest, "spacer_thick", 0.2, 3.5),
    (ConvertGenerateRequest, "loop_width", 2, 10),
    (ConvertGenerateRequest, "loop_length", 4, 15),
    (ConvertGenerateRequest, "loop_hole", 1, 5),
    (ConvertGenerateRequest, "heightmap_max_height", 0.08, 15.0),
    (ConvertGenerateRequest, "outline_width", 0.5, 10.0),
    (ConvertGenerateRequest, "wire_width_mm", 0.2, 1.2),
    (ConvertGenerateRequest, "wire_height_mm", 0.04, 1.0),
    (ConvertGenerateRequest, "coating_height_mm", 0.04, 0.12),
    (ColorMergePreviewRequest, "merge_threshold", 0.1, 5.0),
    (ColorMergePreviewRequest, "merge_max_distance", 5, 50),
    (ExtractorExtractRequest, "zoom", 0.8, 1.2),
    (ExtractorExtractRequest, "distortion", -0.2, 0.2),
    (ExtractorExtractRequest, "offset_x", -30, 30),
    (ExtractorExtractRequest, "offset_y", -30, 30),
    (CalibrationGenerateRequest, "block_size", 3, 10),
    (CalibrationGenerateRequest, "gap", 0.4, 2.0),
]


def _build_minimal_valid_data(model_cls: Type[BaseModel]) -> Dict[str, Any]:
    """Build a minimal valid data dict for a model using only required fields
    and sensible defaults for the rest.
    """
    if model_cls is ConvertPreviewRequest:
        return {"lut_name": "test_lut"}
    elif model_cls is ConvertGenerateRequest:
        return {"lut_name": "test_lut"}
    elif model_cls is ColorMergePreviewRequest:
        return {"session_id": "test_session"}
    elif model_cls is ExtractorExtractRequest:
        return {"corner_points": [(0, 0), (100, 0), (100, 100), (0, 100)]}
    elif model_cls is CalibrationGenerateRequest:
        return {}
    return {}


# **Validates: Requirements 3.7, 5.3**
@given(data=st.data())
@settings(max_examples=100)
def test_out_of_range_values_rejected(data: st.DataObject) -> None:
    """Property 3: For any numeric field with ge/le constraints, providing a
    value outside that range should raise ValidationError.

    **Validates: Requirements 3.7, 5.3**
    """
    model_cls, field_name, min_val, max_val = data.draw(
        st.sampled_from(CONSTRAINED_FIELDS)
    )

    # Decide whether to go below min or above max
    go_below = data.draw(st.booleans())

    if go_below:
        # Generate a value strictly below min_val
        if isinstance(min_val, float):
            bad_value = data.draw(
                st.floats(max_value=min_val, exclude_max=True,
                          allow_nan=False, allow_infinity=False)
            )
        else:
            bad_value = data.draw(st.integers(max_value=int(min_val) - 1))
    else:
        # Generate a value strictly above max_val
        if isinstance(max_val, float):
            bad_value = data.draw(
                st.floats(min_value=max_val, exclude_min=True,
                          allow_nan=False, allow_infinity=False)
            )
        else:
            bad_value = data.draw(st.integers(min_value=int(max_val) + 1))

    valid_data = _build_minimal_valid_data(model_cls)
    valid_data[field_name] = bad_value

    with pytest.raises(ValidationError):
        model_cls(**valid_data)


# ===========================================================================
# Property 5: Enum Field String Serialization
# Feature: fastapi-backend-scaffold, Property 5: 枚举字段字符串序列化
# ===========================================================================

# Models that contain enum fields and their enum field names
ENUM_FIELD_MAP: Dict[str, List[str]] = {
    "ConvertPreviewRequest": ["color_mode", "modeling_mode"],
    "ConvertGenerateRequest": ["color_mode", "modeling_mode", "structure_mode"],
    "ExtractorExtractRequest": ["color_mode", "page"],
    "CalibrationGenerateRequest": ["color_mode", "backing"],
}

# Strategies for models with enum fields
st_models_with_enums = (
    st_convert_preview_request()
    | st_convert_generate_request()
    | st_extractor_extract_request()
    | st_calibration_generate_request()
)


# **Validates: Requirements 11.2**
@given(instance=st_models_with_enums)
@settings(max_examples=100)
def test_enum_field_string_serialization(instance: BaseModel) -> None:
    """Property 5: For any Schema instance containing enum fields, the
    serialized JSON should have string values for enum fields (not integers
    or enum names).

    **Validates: Requirements 11.2**
    """
    json_str = instance.model_dump_json()
    parsed = json.loads(json_str)

    model_name = type(instance).__name__
    enum_fields = ENUM_FIELD_MAP.get(model_name, [])

    for field_name in enum_fields:
        value = parsed[field_name]
        assert isinstance(value, str), (
            f"{model_name}.{field_name} serialized as {type(value).__name__} "
            f"({value!r}), expected str"
        )
        # Ensure it's the enum *value* (e.g. "4-Color"), not the enum *name*
        # (e.g. "FOUR_COLOR")
        field_obj = instance.__class__.model_fields[field_name]
        enum_cls = field_obj.annotation
        # Check value is one of the enum's string values
        valid_values = [e.value for e in enum_cls]
        assert value in valid_values, (
            f"{model_name}.{field_name} = {value!r} is not a valid enum value. "
            f"Expected one of: {valid_values}"
        )


# ===========================================================================
# Property 6: Optional Field Default Values
# Feature: fastapi-backend-scaffold, Property 6: Optional 字段默认值填充
# ===========================================================================

# (model_class, required_only_kwargs, field_name, expected_default)
OPTIONAL_DEFAULTS: List[Tuple[Type[BaseModel], Dict[str, Any], str, Any]] = [
    # ConvertPreviewRequest
    (ConvertPreviewRequest, {"lut_name": "x"}, "target_width_mm", 60.0),
    (ConvertPreviewRequest, {"lut_name": "x"}, "auto_bg", False),
    (ConvertPreviewRequest, {"lut_name": "x"}, "bg_tol", 40),
    (ConvertPreviewRequest, {"lut_name": "x"}, "quantize_colors", 48),
    (ConvertPreviewRequest, {"lut_name": "x"}, "enable_cleanup", True),
    # ConvertGenerateRequest
    (ConvertGenerateRequest, {"lut_name": "x"}, "target_width_mm", 60.0),
    (ConvertGenerateRequest, {"lut_name": "x"}, "spacer_thick", 1.2),
    (ConvertGenerateRequest, {"lut_name": "x"}, "add_loop", False),
    (ConvertGenerateRequest, {"lut_name": "x"}, "loop_width", 4.0),
    (ConvertGenerateRequest, {"lut_name": "x"}, "loop_length", 8.0),
    (ConvertGenerateRequest, {"lut_name": "x"}, "loop_hole", 2.5),
    (ConvertGenerateRequest, {"lut_name": "x"}, "loop_pos", None),
    (ConvertGenerateRequest, {"lut_name": "x"}, "enable_relief", False),
    (ConvertGenerateRequest, {"lut_name": "x"}, "heightmap_max_height", 5.0),
    (ConvertGenerateRequest, {"lut_name": "x"}, "enable_outline", False),
    (ConvertGenerateRequest, {"lut_name": "x"}, "outline_width", 2.0),
    (ConvertGenerateRequest, {"lut_name": "x"}, "enable_cloisonne", False),
    (ConvertGenerateRequest, {"lut_name": "x"}, "wire_width_mm", 0.4),
    (ConvertGenerateRequest, {"lut_name": "x"}, "wire_height_mm", 0.4),
    (ConvertGenerateRequest, {"lut_name": "x"}, "enable_coating", False),
    (ConvertGenerateRequest, {"lut_name": "x"}, "coating_height_mm", 0.08),
    (ConvertGenerateRequest, {"lut_name": "x"}, "replacement_regions", None),
    (ConvertGenerateRequest, {"lut_name": "x"}, "free_color_set", None),
    # ColorMergePreviewRequest
    (ColorMergePreviewRequest, {"session_id": "s"}, "merge_enable", True),
    (ColorMergePreviewRequest, {"session_id": "s"}, "merge_threshold", 0.5),
    (ColorMergePreviewRequest, {"session_id": "s"}, "merge_max_distance", 20),
    # CalibrationGenerateRequest
    (CalibrationGenerateRequest, {}, "block_size", 5),
    (CalibrationGenerateRequest, {}, "gap", 0.82),
]


# **Validates: Requirements 11.3**
@given(data=st.data())
@settings(max_examples=100)
def test_optional_field_default_values(data: st.DataObject) -> None:
    """Property 6: For any Schema model, creating an instance with only
    required fields should fill all Optional fields with their defined
    default values.

    **Validates: Requirements 11.3**
    """
    model_cls, required_kwargs, field_name, expected = data.draw(
        st.sampled_from(OPTIONAL_DEFAULTS)
    )

    # Randomize the required field values to add variety
    if "lut_name" in required_kwargs:
        required_kwargs = {
            "lut_name": data.draw(st_non_empty_str),
        }
    elif "session_id" in required_kwargs:
        required_kwargs = {
            "session_id": data.draw(st_non_empty_str),
        }

    instance = model_cls(**required_kwargs)
    actual = getattr(instance, field_name)

    assert actual == expected, (
        f"{model_cls.__name__}.{field_name}: expected default {expected!r}, "
        f"got {actual!r}"
    )
