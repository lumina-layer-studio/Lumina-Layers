"""Property-based tests for Naming_Service (core/naming.py).

Uses Hypothesis to verify correctness properties across arbitrary inputs.
"""

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from config import ModelingMode
from core.naming import (
    COLOR_MODE_TAGS,
    MODELING_MODE_TAGS,
    generate_batch_filename,
    generate_calibration_filename,
    generate_model_filename,
    generate_preview_filename,
    parse_filename,
)

# Strategies — generate realistic filename characters (letters, numbers,
# punctuation, symbols, spaces) but exclude control chars and newlines.
_filename_chars = st.characters(
    whitelist_categories=("L", "N", "P", "S", "Zs"),
    blacklist_characters='<>:"/\\|?*',
)
valid_base_names = st.text(_filename_chars, min_size=1).filter(lambda s: s.strip() != "")
valid_modeling_modes = st.sampled_from(list(ModelingMode))
valid_color_modes = st.sampled_from(list(COLOR_MODE_TAGS.keys()))

# Expected regex for model filenames
MODEL_FILENAME_RE = re.compile(
    r"^.+_Lumina_(HiFi|Pixel|Vector)_(4C|6C|8C|BW|Merged)_\d{8}_\d{6}\.3mf$"
)


# Feature: model-naming-convention, Property 1: 模型文件名格式正确性
# **Validates: Requirements 4.1, 2.1, 3.1-3.7**
@given(
    base_name=valid_base_names,
    modeling_mode=valid_modeling_modes,
    color_mode=valid_color_modes,
)
@settings(max_examples=200)
def test_model_filename_format_correctness(base_name, modeling_mode, color_mode):
    """Property 1: For any valid base_name, ModelingMode, and color_mode from
    COLOR_MODE_TAGS, generate_model_filename produces a filename matching the
    standard pattern: {base}_Lumina_{HiFi|Pixel|Vector}_{4C|6C|8C|BW}_{YYYYMMDD}_{HHmmss}.3mf
    """
    filename = generate_model_filename(base_name, modeling_mode, color_mode)
    assert MODEL_FILENAME_RE.match(filename), (
        f"Filename '{filename}' does not match expected pattern. "
        f"Inputs: base_name={base_name!r}, mode={modeling_mode}, color={color_mode}"
    )


# Forbidden characters that must never appear in generated filenames
FORBIDDEN_CHARS = set('<>:"/\\|?*')

# Strategy: arbitrary text including forbidden chars, control chars, unicode
arbitrary_strings = st.text(min_size=0)


# Feature: model-naming-convention, Property 4: 文件名无禁止字符
# **Validates: Requirements 4.5**
@given(
    base_name=arbitrary_strings,
    modeling_mode=valid_modeling_modes,
    color_mode=valid_color_modes,
    calibration_type=arbitrary_strings,
)
@settings(max_examples=200)
def test_no_forbidden_characters_in_filenames(
    base_name, modeling_mode, color_mode, calibration_type
):
    """Property 4: For any input strings (including those with forbidden chars
    like <>:"/\\|?*), all generated filenames SHALL NOT contain any OS-forbidden
    characters.
    """
    filenames = [
        generate_model_filename(base_name, modeling_mode, color_mode),
        generate_preview_filename(base_name),
        generate_calibration_filename(color_mode, calibration_type),
        generate_batch_filename(),
    ]
    for filename in filenames:
        violations = FORBIDDEN_CHARS.intersection(filename)
        assert not violations, (
            f"Filename '{filename}' contains forbidden characters: {violations}. "
            f"Inputs: base_name={base_name!r}, mode={modeling_mode}, "
            f"color={color_mode}, cal_type={calibration_type!r}"
        )


# Strategy: simple alphanumeric base names to avoid substrings like "_Lumina_"
# that could confuse the regex parser during round-trip parsing.
simple_base_names = st.from_regex(r"[a-zA-Z0-9]+", fullmatch=True)


# Feature: model-naming-convention, Property 5: 生成-解析 Round-Trip
# **Validates: Requirements 5.1, 5.2**
@given(
    base_name=simple_base_names,
    modeling_mode=valid_modeling_modes,
    color_mode=valid_color_modes,
)
@settings(max_examples=200)
def test_generate_parse_round_trip(base_name, modeling_mode, color_mode):
    """Property 5: For any valid base_name, ModelingMode, and color_mode from
    COLOR_MODE_TAGS, calling parse_filename on the output of
    generate_model_filename SHALL return a non-None result whose
    modeling_mode matches MODELING_MODE_TAGS[modeling_mode] and whose
    color_mode matches COLOR_MODE_TAGS[color_mode].
    """
    filename = generate_model_filename(base_name, modeling_mode, color_mode)
    parsed = parse_filename(filename)

    assert parsed is not None, (
        f"parse_filename returned None for '{filename}'. "
        f"Inputs: base_name={base_name!r}, mode={modeling_mode}, color={color_mode}"
    )

    expected_mode_tag = MODELING_MODE_TAGS[modeling_mode]
    expected_color_tag = COLOR_MODE_TAGS[color_mode]

    assert parsed["modeling_mode"] == expected_mode_tag, (
        f"Expected modeling_mode '{expected_mode_tag}', got '{parsed['modeling_mode']}'. "
        f"Filename: '{filename}'"
    )
    assert parsed["color_mode"] == expected_color_tag, (
        f"Expected color_mode '{expected_color_tag}', got '{parsed['color_mode']}'. "
        f"Filename: '{filename}'"
    )


# ---------------------------------------------------------------------------
# Strategy: arbitrary text that does NOT match any standard filename pattern.
# We filter out strings that happen to match model, preview, calibration, or
# batch patterns so we only test truly non-standard inputs.
# ---------------------------------------------------------------------------
_MODEL_PATTERN = re.compile(
    r"^.+_Lumina_(HiFi|Pixel|Vector)_(4C|6C|8C|BW|Merged)_\d{8}_\d{6}\.[\w]+$"
)
_PREVIEW_PATTERN = re.compile(r"^.+_Preview_\d{8}_\d{6}\.[\w]+$")
_CALIBRATION_PATTERN = re.compile(
    r"^Lumina_Calibration_.+?_(4C|6C|8C|BW|Merged)_\d{8}_\d{6}\.[\w]+$"
)
_BATCH_PATTERN = re.compile(r"^Lumina_Batch_\d{8}_\d{6}\.[\w]+$")


def _is_standard_filename(s: str) -> bool:
    """Return True if *s* matches any of the four standard naming patterns."""
    return bool(
        _MODEL_PATTERN.match(s)
        or _PREVIEW_PATTERN.match(s)
        or _CALIBRATION_PATTERN.match(s)
        or _BATCH_PATTERN.match(s)
    )


non_standard_strings = st.text(min_size=0).filter(lambda s: not _is_standard_filename(s))


# Feature: model-naming-convention, Property 6: 非标准文件名解析安全性
# **Validates: Requirements 5.3**
@given(arbitrary=non_standard_strings)
@settings(max_examples=200)
def test_non_standard_filename_parse_safety(arbitrary):
    """Property 6: For any string that does NOT match a standard naming format,
    parse_filename SHALL return None and SHALL NOT raise any exception.
    """
    result = parse_filename(arbitrary)
    assert result is None, (
        f"parse_filename returned {result!r} for non-standard input {arbitrary!r}; "
        f"expected None"
    )


# Supplementary: parse_filename never raises for ANY input
# Feature: model-naming-convention, Property 6: 非标准文件名解析安全性 (no-exception guarantee)
# **Validates: Requirements 5.3**
@given(arbitrary=st.text(min_size=0))
@settings(max_examples=200)
def test_parse_filename_never_raises(arbitrary):
    """Property 6 (supplementary): parse_filename SHALL NOT raise any exception
    for ANY arbitrary input string, regardless of whether it matches a standard
    pattern or not.
    """
    try:
        parse_filename(arbitrary)
    except Exception as exc:
        raise AssertionError(
            f"parse_filename raised {type(exc).__name__}: {exc} "
            f"for input {arbitrary!r}"
        )
