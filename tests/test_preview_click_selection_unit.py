"""Unit tests for preview-click selection safety and HTML rendering."""

import sys
import os
from unittest.mock import MagicMock

# Add project root to path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Stub gradio for environments where full UI dependencies are unavailable.
for _mod_name in ("gradio", "gradio.themes"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

from core.converter import _resolve_click_selection_hexes, on_preview_click_select_color
from ui.palette_extension import build_selected_dual_color_html


class _EvtNoneIndex:
    index = None


def test_invalid_click_returns_none_hex():
    """Invalid click events should not return dict-like hex values."""
    cache = {"bed_label": "256x256 mm"}
    _img, _text, hex_val, msg = on_preview_click_select_color(cache, _EvtNoneIndex())
    assert hex_val is None
    assert "无效点击" in msg


def test_resolve_click_selection_hexes_rejects_non_string_default():
    """dict default_hex (e.g. gr.update payload) should be normalized away."""
    display_hex, state_hex = _resolve_click_selection_hexes({}, {"value": "bad"})
    assert display_hex is None
    assert state_hex is None


def test_resolve_click_selection_hexes_prefers_cached_strings():
    cache = {"selected_quantized_hex": "#112233", "selected_matched_hex": "#445566"}
    display_hex, state_hex = _resolve_click_selection_hexes(cache, {"value": "bad"})
    assert display_hex == "#445566"
    assert state_hex == "#112233"


def test_selected_dual_color_html_accepts_non_string_inputs():
    """HTML renderer should gracefully fallback to #000000 for bad input types."""
    html = build_selected_dual_color_html({"x": 1}, None, lang="zh")
    assert "#000000" in html
