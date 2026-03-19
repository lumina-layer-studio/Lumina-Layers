"""Property-based tests for color_mode propagation (config.py LUTMetadata).

Uses Hypothesis to verify round-trip correctness properties across arbitrary inputs.
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from config import LUTMetadata, PaletteEntry


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Known valid color_mode strings from the design doc
_VALID_COLOR_MODES = [
    "BW (Black & White)",
    "4-Color (CMYW)",
    "4-Color (RYBW)",
    "6-Color (Smart 1296)",
    "6-Color (RYBW 1296)",
    "5-Color Extended",
    "8-Color Max",
]

# Color names used across all color systems
_COLOR_NAMES = [
    "White", "Cyan", "Magenta", "Yellow", "Red", "Blue",
    "Green", "Black", "Deep Blue",
]

# Material names
_MATERIALS = ["PLA Basic", "PLA Matte", "PETG Basic", "ABS", "PLA Silk"]


def hex_color_st() -> st.SearchStrategy:
    """Generate valid hex color strings like '#RRGGBB' or None."""
    return st.one_of(
        st.none(),
        st.tuples(
            st.integers(0, 255),
            st.integers(0, 255),
            st.integers(0, 255),
        ).map(lambda rgb: f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"),
    )


def palette_entry_st() -> st.SearchStrategy[PaletteEntry]:
    """Generate a valid PaletteEntry with known color names."""
    return st.builds(
        PaletteEntry,
        color=st.sampled_from(_COLOR_NAMES),
        material=st.sampled_from(_MATERIALS),
        hex_color=hex_color_st(),
    )


def color_mode_st() -> st.SearchStrategy:
    """Generate a valid color_mode string or None."""
    return st.one_of(
        st.none(),
        st.sampled_from(_VALID_COLOR_MODES),
    )


def lut_metadata_st() -> st.SearchStrategy[LUTMetadata]:
    """Generate a valid LUTMetadata instance with random fields.

    Ensures unique color names in palette (since to_dict uses color as dict key).
    """
    return st.builds(
        LUTMetadata,
        palette=st.lists(
            palette_entry_st(),
            min_size=0,
            max_size=8,
        ).map(_deduplicate_palette),
        color_mode=color_mode_st(),
        max_color_layers=st.integers(min_value=1, max_value=10),
        layer_height_mm=st.sampled_from([0.04, 0.08, 0.12, 0.16, 0.20]),
        line_width_mm=st.sampled_from([0.30, 0.42, 0.50, 0.60]),
        base_layers=st.integers(min_value=1, max_value=30),
        base_channel_idx=st.integers(min_value=0, max_value=7),
        layer_order=st.sampled_from(["Top2Bottom", "Bottom2Top"]),
    )


def _deduplicate_palette(entries: list[PaletteEntry]) -> list[PaletteEntry]:
    """Keep only the first entry per color name (to_dict uses color as key)."""
    seen: set[str] = set()
    result: list[PaletteEntry] = []
    for e in entries:
        if e.color not in seen:
            seen.add(e.color)
            result.append(e)
    return result


# ---------------------------------------------------------------------------
# Feature: color-system-propagation-fix, Property 1: LUTMetadata round-trip 一致性
# **Validates: Requirements 6.1, 6.2, 6.3, 1.2, 1.3**
# ---------------------------------------------------------------------------

@given(metadata=lut_metadata_st())
@settings(max_examples=100)
def test_lut_metadata_round_trip(metadata: LUTMetadata) -> None:
    """Property 1: For any valid LUTMetadata instance (with any valid color_mode
    string or None), from_dict(to_dict(metadata)) should produce an equivalent
    metadata object with all fields preserved.

    **Validates: Requirements 6.1, 6.2, 6.3, 1.2, 1.3**
    """
    serialized = metadata.to_dict()
    restored = LUTMetadata.from_dict(serialized)

    # color_mode round-trip
    assert restored.color_mode == metadata.color_mode, (
        f"color_mode mismatch: {restored.color_mode!r} != {metadata.color_mode!r}"
    )

    # Scalar print parameters round-trip
    assert restored.max_color_layers == metadata.max_color_layers
    assert restored.layer_height_mm == metadata.layer_height_mm
    assert restored.line_width_mm == metadata.line_width_mm
    assert restored.base_layers == metadata.base_layers
    assert restored.base_channel_idx == metadata.base_channel_idx
    assert restored.layer_order == metadata.layer_order

    # Palette round-trip: same length and entries match
    assert len(restored.palette) == len(metadata.palette), (
        f"palette length mismatch: {len(restored.palette)} != {len(metadata.palette)}"
    )
    for orig, rest in zip(metadata.palette, restored.palette):
        assert rest.color == orig.color, (
            f"palette color mismatch: {rest.color!r} != {orig.color!r}"
        )
        assert rest.material == orig.material, (
            f"palette material mismatch: {rest.material!r} != {orig.material!r}"
        )
        assert rest.hex_color == orig.hex_color, (
            f"palette hex_color mismatch: {rest.hex_color!r} != {orig.hex_color!r}"
        )


# ---------------------------------------------------------------------------
# Feature: color-system-propagation-fix, Property 2: Keyed JSON save/load round-trip 保留 color_mode
# **Validates: Requirements 1.4, 1.5**
# ---------------------------------------------------------------------------

import json
import tempfile
import os
import numpy as np

from utils.lut_manager import LUTManager


def _non_none_color_mode_metadata_st() -> st.SearchStrategy[LUTMetadata]:
    """Generate a valid LUTMetadata with a non-None color_mode and at least 1 palette entry.

    Ensures palette has unique color names and at least one entry (required for
    recipe name resolution in save_keyed_json).
    """
    return st.builds(
        LUTMetadata,
        palette=st.lists(
            palette_entry_st(),
            min_size=1,
            max_size=8,
        ).map(_deduplicate_palette),
        color_mode=st.sampled_from(_VALID_COLOR_MODES),
        max_color_layers=st.integers(min_value=1, max_value=10),
        layer_height_mm=st.sampled_from([0.04, 0.08, 0.12, 0.16, 0.20]),
        line_width_mm=st.sampled_from([0.30, 0.42, 0.50, 0.60]),
        base_layers=st.integers(min_value=1, max_value=30),
        base_channel_idx=st.integers(min_value=0, max_value=7),
        layer_order=st.sampled_from(["Top2Bottom", "Bottom2Top"]),
    )


@given(
    metadata=_non_none_color_mode_metadata_st(),
    n_entries=st.integers(min_value=4, max_value=10),
)
@settings(max_examples=100)
def test_keyed_json_round_trip_preserves_color_mode(
    metadata: LUTMetadata,
    n_entries: int,
) -> None:
    """Property 2: For any valid LUTMetadata (with color_mode), RGB array, and
    stacks array, saving via save_keyed_json() then loading via
    load_lut_with_metadata() should preserve the color_mode in the returned
    metadata.

    **Validates: Requirements 1.4, 1.5**
    """
    # Build small but realistic RGB and stacks arrays
    rng = np.random.RandomState(42)
    rgb = rng.randint(0, 256, size=(n_entries, 3), dtype=np.uint8)

    n_palette = len(metadata.palette)
    # stacks: each entry is a recipe of max_color_layers indices into palette
    stacks = rng.randint(0, n_palette, size=(n_entries, metadata.max_color_layers), dtype=np.int32)

    with tempfile.TemporaryDirectory() as tmp_dir:
        json_path = os.path.join(tmp_dir, "test_lut.json")

        # Save
        LUTManager.save_keyed_json(json_path, rgb, stacks, metadata)

        # Load
        loaded_rgb, loaded_stacks, loaded_metadata = LUTManager.load_lut_with_metadata(json_path)

        # Core property: color_mode is preserved
        assert loaded_metadata.color_mode == metadata.color_mode, (
            f"color_mode mismatch after round-trip: "
            f"{loaded_metadata.color_mode!r} != {metadata.color_mode!r}"
        )


# ---------------------------------------------------------------------------
# Feature: color-system-propagation-fix, Property 3: 存储的 color_mode 优先级
# **Validates: Requirements 2.1, 2.2**
# ---------------------------------------------------------------------------


@given(
    color_mode=st.sampled_from(_VALID_COLOR_MODES),
    n_entries=st.integers(min_value=0, max_value=3000),
)
@settings(max_examples=100)
def test_stored_color_mode_takes_priority(
    color_mode: str,
    n_entries: int,
) -> None:
    """Property 3: For any valid color_mode string and any entries count,
    when a JSON LUT file contains a stored `color_mode` field,
    `_infer_color_mode_from_json()` should return that stored value
    regardless of entries count.

    **Validates: Requirements 2.1, 2.2**
    """
    # Build a minimal keyed JSON with stored color_mode and arbitrary entries
    lut_data = {
        "color_mode": color_mode,
        "entries": [{"rgb": [128, 128, 128], "stack": [0]}] * n_entries,
        "palette": {"White": {"material": "PLA Basic"}},
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(lut_data, f)
        tmp_path = f.name

    try:
        result = LUTManager._infer_color_mode_from_json(tmp_path)
        assert result == color_mode, (
            f"Expected stored color_mode {color_mode!r} but got {result!r} "
            f"(n_entries={n_entries})"
        )
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Feature: color-system-propagation-fix, Property 4: Palette 名称区分颜色模式变体
# **Validates: Requirements 2.3, 2.4, 2.5, 2.6, 7.2, 7.3, 7.4, 7.5, 7.6**
# ---------------------------------------------------------------------------

# Palette templates for each variant
_RYBW_4COLOR_PALETTE = {"White": {"material": "PLA Basic"}, "Red": {"material": "PLA Basic"},
                        "Yellow": {"material": "PLA Basic"}, "Blue": {"material": "PLA Basic"}}
_CMYW_4COLOR_PALETTE = {"White": {"material": "PLA Basic"}, "Cyan": {"material": "PLA Basic"},
                        "Magenta": {"material": "PLA Basic"}, "Yellow": {"material": "PLA Basic"}}
_RYBW_6COLOR_PALETTE = {"White": {"material": "PLA Basic"}, "Red": {"material": "PLA Basic"},
                        "Yellow": {"material": "PLA Basic"}, "Blue": {"material": "PLA Basic"},
                        "Green": {"material": "PLA Basic"}, "Black": {"material": "PLA Basic"}}
_CMYW_6COLOR_PALETTE = {"White": {"material": "PLA Basic"}, "Cyan": {"material": "PLA Basic"},
                        "Magenta": {"material": "PLA Basic"}, "Green": {"material": "PLA Basic"},
                        "Yellow": {"material": "PLA Basic"}, "Black": {"material": "PLA Basic"}}

# Map (variant, entry_count) → (palette, expected_mode)
_VARIANT_CONFIGS = {
    ("RYBW", 1024): (_RYBW_4COLOR_PALETTE, "4-Color (RYBW)"),
    ("CMYW", 1024): (_CMYW_4COLOR_PALETTE, "4-Color (CMYW)"),
    ("RYBW", 1296): (_RYBW_6COLOR_PALETTE, "6-Color (RYBW 1296)"),
    ("CMYW", 1296): (_CMYW_6COLOR_PALETTE, "6-Color (Smart 1296)"),
}


@given(
    variant=st.sampled_from(["RYBW", "CMYW"]),
    entry_count=st.sampled_from([1024, 1296]),
)
@settings(max_examples=100)
def test_palette_names_distinguish_color_mode_variants(
    variant: str,
    entry_count: int,
) -> None:
    """Property 4: For any JSON LUT file without a `color_mode` field, when
    entries count is 1024 or 1296, `_infer_color_mode_from_json()` should
    correctly distinguish RYBW and CMYW variants based on palette color names.

    - 1024 + RYBW palette → "4-Color (RYBW)"
    - 1024 + CMYW palette → "4-Color (CMYW)"
    - 1296 + RYBW palette → "6-Color (RYBW 1296)"
    - 1296 + CMYW palette → "6-Color (Smart 1296)"

    **Validates: Requirements 2.3, 2.4, 2.5, 2.6, 7.2, 7.3, 7.4, 7.5, 7.6**
    """
    palette, expected_mode = _VARIANT_CONFIGS[(variant, entry_count)]

    # Build a JSON LUT without color_mode, with the given palette and entry count
    dummy_entry = {"rgb": [128, 128, 128], "recipe": ["White"]}
    lut_data = {
        "palette": palette,
        "entries": [dummy_entry] * entry_count,
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(lut_data, f)
        tmp_path = f.name

    try:
        result = LUTManager._infer_color_mode_from_json(tmp_path)
        assert result == expected_mode, (
            f"variant={variant}, entry_count={entry_count}: "
            f"expected {expected_mode!r} but got {result!r}"
        )
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Feature: color-system-propagation-fix, Property 5: infer_default_metadata 传入 color_mode 优先
# **Validates: Requirements 3.2, 3.6**
# ---------------------------------------------------------------------------

from config import ColorSystem


@given(color_mode=st.sampled_from(_VALID_COLOR_MODES))
@settings(max_examples=100)
def test_infer_default_metadata_color_mode_priority(color_mode: str) -> None:
    """Property 5: For any valid color_mode string, when infer_default_metadata()
    is called with a color_mode parameter, the returned LUTMetadata's color_mode
    field should equal the passed-in value, and the palette should match the
    corresponding ColorSystem configuration.

    **Validates: Requirements 3.2, 3.6**
    """
    metadata = LUTManager.infer_default_metadata(
        display_name="test_lut",
        file_path="/tmp/test_lut.json",
        color_count=0,
        color_mode=color_mode,
    )

    # color_mode must equal the passed-in value
    assert metadata.color_mode == color_mode, (
        f"color_mode mismatch: expected {color_mode!r}, got {metadata.color_mode!r}"
    )

    # palette must match the ColorSystem configuration for this mode
    color_conf = ColorSystem.get(color_mode)
    expected_slots = color_conf.get("slots", [])

    actual_colors = [entry.color for entry in metadata.palette]
    assert actual_colors == expected_slots, (
        f"palette mismatch for {color_mode!r}: "
        f"expected {expected_slots}, got {actual_colors}"
    )

    # All palette entries should have default material "PLA Basic"
    for entry in metadata.palette:
        assert entry.material == "PLA Basic", (
            f"Expected material 'PLA Basic' for {entry.color}, got {entry.material!r}"
        )


# ---------------------------------------------------------------------------
# Feature: color-system-propagation-fix, Property 6: detect_lut_color_mode 使用存储的 color_mode
# **Validates: Requirements 4.1, 4.3, 5.1, 5.2**
# ---------------------------------------------------------------------------

from core.converter import detect_lut_color_mode


@given(
    metadata=_non_none_color_mode_metadata_st(),
    n_entries=st.integers(min_value=4, max_value=20),
)
@settings(max_examples=100)
def test_detect_lut_color_mode_uses_stored_color_mode(
    metadata: LUTMetadata,
    n_entries: int,
) -> None:
    """Property 6: For any JSON LUT file with a stored color_mode,
    detect_lut_color_mode() should return that stored value.

    Creates a temp JSON LUT via save_keyed_json() with a known color_mode,
    then calls detect_lut_color_mode() and verifies it returns the stored value.

    **Validates: Requirements 4.1, 4.3, 5.1, 5.2**
    """
    rng = np.random.RandomState(42)
    rgb = rng.randint(0, 256, size=(n_entries, 3), dtype=np.uint8)

    n_palette = len(metadata.palette)
    assume(n_palette >= 1)
    stacks = rng.randint(0, n_palette, size=(n_entries, metadata.max_color_layers), dtype=np.int32)

    with tempfile.TemporaryDirectory() as tmp_dir:
        json_path = os.path.join(tmp_dir, "test_lut.json")

        # Save with known color_mode
        LUTManager.save_keyed_json(json_path, rgb, stacks, metadata)

        # detect_lut_color_mode should return the stored color_mode
        result = detect_lut_color_mode(json_path)
        assert result == metadata.color_mode, (
            f"detect_lut_color_mode returned {result!r}, "
            f"expected stored color_mode {metadata.color_mode!r}"
        )
