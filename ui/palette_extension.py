"""
Lumina Studio - Color Palette Extension
Non-invasive color palette functionality extension for the converter tab.

This module provides enhanced color palette display without modifying core files.
Text and percentage are displayed BELOW the color swatches for better readability.
Click handlers are defined globally in crop_extension.py to survive Gradio re-renders.
"""

from typing import Any, Optional
from pathlib import Path

import cv2
import numpy as np

from core.i18n import I18n
from core.color_replacement import parse_selection_token


RECOMMENDED_REPLACEMENT_COUNT = 20

_TEMPLATE_ROOT = Path(__file__).resolve().parent / "template"


def _load_template_text(filename: str) -> str:
    return (_TEMPLATE_ROOT / filename).read_text(encoding="utf-8")


PALETTE_HTML_TEMPLATE = _load_template_text("palette_panel.html")
PALETTE_CSS_TEMPLATE = _load_template_text("palette_panel.css")
PALETTE_JS_ON_LOAD = _load_template_text("palette_panel.js")

LUT_GRID_HTML_TEMPLATE = _load_template_text("lut_grid_panel.html")
LUT_GRID_CSS_TEMPLATE = _load_template_text("lut_grid_panel.css")
LUT_GRID_JS_ON_LOAD = _load_template_text("lut_grid_panel.js")


def _hex_to_rgb_array(hex_color: str) -> Optional[np.ndarray]:
    value = str(hex_color).strip()
    if len(value) != 7 or not value.startswith("#"):
        return None
    try:
        return np.array(
            [
                int(value[1:3], 16),
                int(value[3:5], 16),
                int(value[5:7], 16),
            ],
            dtype=np.float32,
        )
    except ValueError:
        return None


def _get_recommended_colors(
    colors: list[dict[str, Any]],
    reference_color: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Rank LUT colors by a combined color-similarity score."""
    ref_rgb = _hex_to_rgb_array(reference_color or "")
    if ref_rgb is None or limit <= 0:
        return []

    candidates = []
    for entry in colors:
        hex_color = str(entry.get("hex", ""))
        rgb = _hex_to_rgb_array(hex_color)
        if rgb is None:
            continue
        if hex_color.lower() == str(reference_color).lower():
            continue
        candidates.append((entry, rgb))

    if not candidates:
        return []

    ref_rgb_u8 = ref_rgb.astype(np.uint8).reshape(1, 1, 3)
    ref_hsv = cv2.cvtColor(ref_rgb_u8, cv2.COLOR_RGB2HSV).astype(np.float32)[0, 0]
    ref_lab = cv2.cvtColor(ref_rgb_u8, cv2.COLOR_RGB2LAB).astype(np.float32)[0, 0]

    scored = []
    for entry, cand_rgb in candidates:
        cand_rgb_u8 = cand_rgb.astype(np.uint8).reshape(1, 1, 3)
        cand_hsv = cv2.cvtColor(cand_rgb_u8, cv2.COLOR_RGB2HSV).astype(np.float32)[0, 0]
        cand_lab = cv2.cvtColor(cand_rgb_u8, cv2.COLOR_RGB2LAB).astype(np.float32)[0, 0]

        rgb_l2 = float(np.linalg.norm(cand_rgb - ref_rgb) / np.sqrt(3 * 255 * 255))
        rgb_l1 = float(np.sum(np.abs(cand_rgb - ref_rgb)) / (3 * 255))
        hue_delta = abs(float(cand_hsv[0] - ref_hsv[0]))
        hue_dist = min(hue_delta, 180 - hue_delta) / 90.0
        sat_dist = abs(float(cand_hsv[1] - ref_hsv[1])) / 255.0
        val_dist = abs(float(cand_hsv[2] - ref_hsv[2])) / 255.0
        hsv_dist = (hue_dist + sat_dist + val_dist) / 3.0
        lab_l2 = float(
            np.linalg.norm(cand_lab - ref_lab)
            / np.sqrt(100 * 100 + 255 * 255 + 255 * 255)
        )

        composite_score = (
            0.35 * lab_l2 + 0.30 * rgb_l2 + 0.20 * hsv_dist + 0.15 * rgb_l1
        )
        scored.append((composite_score, entry))

    scored.sort(key=lambda item: item[0])
    return [entry for _, entry in scored[:limit]]


def generate_palette_html(
    palette: list[dict[str, Any]],
    replacements: Optional[dict[str, str]] = None,
    selected_color: Optional[str] = None,
    original_palette: Optional[list[dict[str, Any]]] = None,
    lang: str = "zh",
) -> dict[str, Any]:
    if not palette:
        return {
            "empty": True,
            "empty_text": I18n.get("palette_empty", lang),
        }

    replacements = replacements or {}
    original_palette = original_palette or palette

    normalized_original = []
    for entry in original_palette:
        quant_hex = entry.get("quant_hex", entry.get("hex"))
        matched_hex = entry.get("matched_hex", quant_hex)
        token = entry.get("token", quant_hex)
        normalized_original.append(
            {
                "quant_hex": quant_hex,
                "matched_hex": matched_hex,
                "token": token,
                "percentage": entry.get("percentage", 0),
                "count": entry.get("count", 0),
            }
        )

    original_by_token = {item["token"]: item for item in normalized_original}

    count_text = I18n.get("palette_count", lang).format(count=len(normalized_original))
    hint_text = I18n.get("palette_hint", lang)
    applied_title = I18n.get("palette_applied_section", lang)
    original_title = I18n.get("palette_original_section", lang)
    none_applied_text = I18n.get("palette_none_applied", lang)
    applied_legend = I18n.get("palette_applied_legend", lang)
    quant_label = I18n.get("palette_quant_label", lang)
    original_label = I18n.get("palette_original_label", lang)
    replaced_label = I18n.get("palette_replacement_label", lang)
    applied_items = list(replacements.items())

    applied_view: list[dict[str, Any]] = []
    for source_key, replacement_hex in applied_items:
        token_data = parse_selection_token(str(source_key))
        original_hex = str(source_key)
        quant_hex = original_hex
        if token_data is not None:
            quant_hex = str(token_data.get("q", ""))
            original_hex = str(token_data.get("m", quant_hex))
        if source_key in original_by_token:
            quant_hex = original_by_token[source_key]["quant_hex"]
            original_hex = original_by_token[source_key]["matched_hex"]
        row_selected = (
            selected_color and str(source_key).lower() == str(selected_color).lower()
        )
        applied_view.append(
            {
                "source_key": str(source_key),
                "quant_hex": str(quant_hex),
                "original_hex": str(original_hex),
                "replacement_hex": str(replacement_hex),
                "row_class": "palette-row-selected" if row_selected else "",
            }
        )

    original_view: list[dict[str, Any]] = []
    for entry in normalized_original:
        quant_hex = str(entry["quant_hex"])
        matched_hex = str(entry["matched_hex"])
        token = str(entry["token"])
        percentage = entry["percentage"]
        replacement_hex = replacements.get(token)
        is_selected = selected_color and token.lower() == str(selected_color).lower()
        tooltip = I18n.get("palette_tooltip", lang).format(
            hex=f"{quant_hex} → {matched_hex}", pct=percentage
        )
        original_view.append(
            {
                "token": token,
                "quant_hex": quant_hex,
                "matched_hex": matched_hex,
                "tooltip": tooltip,
                "percentage_text": f"{percentage}%",
                "quant_block_class": "palette-quant-replaced"
                if replacement_hex
                else "",
                "row_class": "palette-row-selected" if is_selected else "",
            }
        )

    return {
        "empty": False,
        "count_text": count_text,
        "hint_text": hint_text,
        "applied_title": applied_title,
        "applied_count": len(applied_view),
        "applied_legend": applied_legend,
        "none_applied_text": none_applied_text,
        "quant_label": quant_label,
        "original_label": original_label,
        "replaced_label": replaced_label,
        "original_title": original_title,
        "applied_items": applied_view,
        "original_items": original_view,
    }


def generate_lut_color_grid_html(
    colors: list[dict[str, Any]],
    selected_color: Optional[str] = None,
    used_colors: Optional[set[str]] = None,
    reference_color: Optional[str] = None,
    lang: str = "zh",
) -> dict[str, Any]:
    if not colors:
        return {
            "empty": True,
            "load_hint": I18n.get("lut_grid_load_hint", lang),
        }

    used_colors = used_colors or set()
    used_colors_lower = {c.lower() for c in used_colors}

    # Separate colors into used and unused
    used_in_image = []
    not_used = []

    for entry in colors:
        hex_color = entry["hex"]
        if hex_color.lower() in used_colors_lower:
            used_in_image.append(entry)
        else:
            not_used.append(entry)

    count_text = I18n.get("lut_grid_count", lang).format(count=len(colors))
    search_placeholder = I18n.get("lut_grid_search_placeholder", lang)
    search_clear = I18n.get("lut_grid_search_clear", lang)

    def to_swatch_items(color_list: list[dict[str, Any]]) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for entry in color_list:
            hex_color = str(entry["hex"])
            is_selected = selected_color and hex_color.lower() == selected_color.lower()
            items.append(
                {
                    "hex": hex_color,
                    "tooltip": I18n.get("lut_grid_tooltip", lang).format(hex=hex_color),
                    "selected_class": "lut-color-swatch-selected"
                    if is_selected
                    else "",
                }
            )
        return items

    recommended_colors = _get_recommended_colors(
        colors,
        reference_color=reference_color,
        limit=RECOMMENDED_REPLACEMENT_COUNT,
    )
    recommended_section: Optional[dict[str, Any]] = None
    if recommended_colors:
        recommended_section = {
            "title": I18n.get("lut_grid_recommended", lang).format(
                count=len(recommended_colors)
            ),
            "hint": I18n.get("lut_grid_recommended_hint", lang),
            "items": to_swatch_items(recommended_colors),
        }

    used_section: Optional[dict[str, Any]] = None
    if used_in_image:
        used_section = {
            "title": I18n.get("lut_grid_used", lang).format(count=len(used_in_image)),
            "items": to_swatch_items(used_in_image),
        }

    other_section: Optional[dict[str, Any]] = None
    if not_used:
        title = ""
        if used_in_image:
            title = I18n.get("lut_grid_other", lang).format(count=len(not_used))
        other_section = {
            "title": title,
            "items": to_swatch_items(not_used),
        }

    return {
        "empty": False,
        "count_text": count_text,
        "visible_count": len(colors),
        "search_placeholder": search_placeholder,
        "search_clear": search_clear,
        "recommended_section": recommended_section,
        "used_section": used_section,
        "other_section": other_section,
    }
