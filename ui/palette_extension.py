"""
Lumina Studio - Color Palette Extension
Non-invasive color palette functionality extension for the converter tab.

This module provides enhanced color palette display without modifying core files.
Text and percentage are displayed BELOW the color swatches for better readability.
Click handlers are defined globally in crop_extension.py to survive Gradio re-renders.
"""

from typing import Any, Optional

import cv2
import numpy as np

from core.i18n import I18n
from core.color_replacement import parse_selection_token


RECOMMENDED_REPLACEMENT_COUNT = 20


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
) -> str:
    """
    Generate HTML display for color palette with clickable swatches.
    Text and percentage are displayed BELOW the color swatches.
    Clicking a color will highlight that color's regions in the preview.
    Uses event delegation for click handling.

    Args:
        palette: List of palette entries from extract_color_palette
        replacements: Optional dict of current color replacements
        selected_color: Currently selected color hex (for highlighting)

    Returns:
        HTML string for displaying the palette with click-to-select functionality
    """
    if not palette:
        return f"<p style='color:#888;'>{I18n.get('palette_empty', lang)}</p>"

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

    html_parts = [
        f'<p style="color:#666; margin:4px 8px;">{count_text}</p>',
        f'<p style="color:#888; margin:2px 8px; font-size:11px;">💡 {hint_text}</p>',
        '<div id="palette-grid-container" style="display:grid; grid-template-columns:minmax(260px, 1fr) minmax(260px, 1fr); gap:12px; align-items:start;">',
        '<div style="border:1px solid #ddd; border-radius:8px; padding:8px; background:#fafafa;">',
        f'<div style="font-size:12px; font-weight:600; color:#444; margin-bottom:8px;">{applied_title} ({len(applied_items)})</div>',
        f'<div style="font-size:11px; color:#666; margin-bottom:8px; line-height:1.4;">{applied_legend}</div>',
    ]

    if applied_items:
        html_parts.append('<div style="display:flex; flex-direction:column; gap:8px;">')
        html_parts.append(f"""
        <div style="display:grid; grid-template-columns:1fr 16px 1fr 16px 1fr; gap:6px; padding:0 8px; margin-bottom:2px;">
            <div style="font-size:10px; color:#666; text-align:center;">{quant_label}</div>
            <div></div>
            <div style="font-size:10px; color:#666; text-align:center;">{original_label}</div>
            <div></div>
            <div style="font-size:10px; color:#666; text-align:center;">{replaced_label}</div>
        </div>
        """)
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
                selected_color
                and str(source_key).lower() == str(selected_color).lower()
            )
            row_border = "2px solid #2196F3" if row_selected else "1px solid #eee"
            row_shadow = (
                "box-shadow:0 0 0 1px rgba(33,150,243,0.2);" if row_selected else ""
            )
            html_parts.append(f'''
            <div class="palette-applied-item" data-color="{source_key}" style="display:grid; grid-template-columns:1fr 16px 1fr 16px 1fr; align-items:start; gap:6px; border:{row_border}; border-radius:8px; padding:8px; background:#fff; cursor:pointer; {row_shadow}">
                <div style="display:flex; flex-direction:column; align-items:center; gap:4px;">
                    <div class="palette-applied-color-block" title="{quant_hex}" style="width:28px; height:28px; border:1px solid #ccc; border-radius:6px; background:{quant_hex};"></div>
                    <div style="font-size:9px; color:#666; word-break:break-all; text-align:center;">{quant_hex}</div>
                </div>
                <div style="font-size:12px; color:#888; text-align:center; padding-top:22px;">→</div>
                <div style="display:flex; flex-direction:column; align-items:center; gap:4px;">
                    <div class="palette-applied-color-block" title="{original_hex}" style="width:28px; height:28px; border:1px solid #999; border-radius:6px; background:{original_hex};"></div>
                    <div style="font-size:9px; color:#666; word-break:break-all; text-align:center;">{original_hex}</div>
                </div>
                <div style="font-size:12px; color:#888; text-align:center; padding-top:22px;">→</div>
                <div style="display:flex; flex-direction:column; align-items:center; gap:4px;">
                    <div class="palette-applied-color-block" title="{replacement_hex}" style="width:28px; height:28px; border:1px solid #4CAF50; border-radius:6px; background:{replacement_hex};"></div>
                    <div style="font-size:9px; color:#666; word-break:break-all; text-align:center;">{replacement_hex}</div>
                </div>
            </div>
            ''')
    else:
        html_parts.append(
            f'<p style="font-size:12px; color:#888; margin:0;">{none_applied_text}</p>'
        )

    if applied_items:
        html_parts.append("</div>")

    html_parts.append("</div>")
    html_parts.append(
        '<div style="border:1px solid #ddd; border-radius:8px; padding:8px; background:#fff;">'
    )
    html_parts.append(
        f'<div style="font-size:12px; font-weight:600; color:#444; margin-bottom:8px;">{original_title}</div>'
    )
    html_parts.append(f"""
    <div style="display:grid; grid-template-columns:1fr 16px 1fr auto; gap:6px; padding:0 8px; margin-bottom:2px;">
        <div style="font-size:10px; color:#666; text-align:center;">{quant_label}</div>
        <div></div>
        <div style="font-size:10px; color:#666; text-align:center;">{original_label}</div>
        <div style="font-size:10px; color:#666; text-align:right;">%</div>
    </div>
    """)
    html_parts.append(
        '<div style="display:flex; flex-direction:column; gap:8px; max-height:360px; overflow-y:auto;">'
    )

    for entry in normalized_original:
        quant_hex = entry["quant_hex"]
        matched_hex = entry["matched_hex"]
        token = entry["token"]
        percentage = entry["percentage"]
        replacement_hex = replacements.get(token)
        quant_border_style = (
            "2px solid #ff6b6b" if replacement_hex else "1px solid #ccc"
        )
        is_selected = selected_color and token.lower() == str(selected_color).lower()
        row_border = "2px solid #2196F3" if is_selected else "1px solid #eee"
        row_shadow = "box-shadow:0 0 0 1px rgba(33,150,243,0.2);" if is_selected else ""
        tooltip = I18n.get("palette_tooltip", lang).format(
            hex=f"{quant_hex} → {matched_hex}", pct=percentage
        )
        html_parts.append(f'''
        <div class="palette-original-item" data-color="{token}" title="{tooltip}" style="display:grid; grid-template-columns:1fr 16px 1fr auto; align-items:start; gap:6px; border:{row_border}; border-radius:8px; padding:8px; background:#fff; cursor:pointer; {row_shadow}">
            <div style="display:flex; flex-direction:column; align-items:center; gap:4px;">
                <div class="palette-original-color-block" style="width:28px; height:28px; background:{quant_hex}; border:{quant_border_style}; border-radius:6px;"></div>
                <div style="font-size:9px; color:#666; word-break:break-all; text-align:center;">{quant_hex}</div>
            </div>
            <div style="font-size:12px; color:#888; text-align:center; padding-top:8px;">→</div>
            <div style="display:flex; flex-direction:column; align-items:center; gap:4px;">
                <div class="palette-original-color-block" style="width:28px; height:28px; background:{matched_hex}; border:1px solid #999; border-radius:6px;"></div>
                <div style="font-size:9px; color:#666; word-break:break-all; text-align:center;">{matched_hex}</div>
            </div>
            <div style="font-size:10px; color:#444; text-align:right; padding-top:8px; font-weight:600;">
                {percentage}%
            </div>
        </div>
        ''')

    html_parts.append("</div></div></div>")
    return "".join(html_parts)


def generate_lut_color_grid_html(
    colors: list[dict[str, Any]],
    selected_color: Optional[str] = None,
    used_colors: Optional[set[str]] = None,
    reference_color: Optional[str] = None,
    lang: str = "zh",
) -> str:
    """
    Generate HTML for displaying LUT available colors as a clickable visual grid.
    Text is displayed BELOW the color swatches.
    Includes a search box to filter colors by hex code.
    Uses event delegation for click handling.

    Args:
        colors: List of color dicts with 'color' (R,G,B) and 'hex' keys
        selected_color: Currently selected replacement color hex
        used_colors: Set of hex colors currently used in the image (for grouping)

    Returns:
        HTML string showing available colors as a clickable grid with search
    """
    if not colors:
        return f"<p style='color:#888;'>{I18n.get('lut_grid_load_hint', lang)}</p>"

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

    # Note: Click handlers are now global in crop_extension.py
    # Only keep the search filter function which uses oninput attribute

    count_text = I18n.get("lut_grid_count", lang).format(count=len(colors))
    search_placeholder = I18n.get("lut_grid_search_placeholder", lang)
    search_clear = I18n.get("lut_grid_search_clear", lang)
    html_parts = [
        f'<p style="color:#666; font-size:12px; margin-bottom:8px;">{count_text}: <span id="lut-color-visible-count">{len(colors)}</span></p>',
        # Search box with inline filter function
        f'''
        <div style="margin-bottom:12px; display:flex; align-items:center; gap:8px;">
            <span style="font-size:12px; color:#666;">🔍</span>
            <input type="text" id="lut-color-search" placeholder="{search_placeholder}" 
                   style="flex:1; padding:8px 12px; border:1px solid #ddd; border-radius:6px; font-size:12px; outline:none; transition: border-color 0.2s;"
                   oninput="window.filterLutColors && window.filterLutColors(this.value)"
                   onfocus="this.style.borderColor='#2196F3'"
                   onblur="this.style.borderColor='#ddd'" />
            <button onclick="document.getElementById('lut-color-search').value=''; window.filterLutColors && window.filterLutColors('');" 
                    style="padding:6px 12px; border:1px solid #ddd; border-radius:6px; background:#f5f5f5; cursor:pointer; font-size:11px; transition: background 0.2s;"
                    onmouseover="this.style.background='#e0e0e0'"
                    onmouseout="this.style.background='#f5f5f5'">{search_clear}</button>
        </div>
        ''',
        '<div id="lut-color-grid-container" style="max-height:400px; overflow-y:auto; padding:4px;">',
    ]

    def render_color_grid(color_list, section_title=None, section_color="#666"):
        """Helper to render a section of colors with text BELOW swatches. No onclick - uses event delegation."""
        parts = []
        if section_title:
            parts.append(
                f'<p style="color:{section_color}; font-size:11px; margin:8px 0 4px 0; font-weight:bold;">{section_title}</p>'
            )
        parts.append(
            '<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px;">'
        )

        for entry in color_list:
            hex_color = entry["hex"]

            # Check if selected
            is_selected = selected_color and hex_color.lower() == selected_color.lower()
            outline_style = (
                "outline: 3px solid #2196F3; outline-offset: 2px;"
                if is_selected
                else ""
            )

            # Container with text BELOW swatch - no onclick, handled by event delegation
            tooltip = I18n.get("lut_grid_tooltip", lang).format(hex=hex_color)
            parts.append(f'''
            <div class="lut-color-swatch-container" style="display:flex; flex-direction:column; align-items:center; gap:4px;">
                <div class="lut-color-swatch" style="width:50px; height:50px; background:{hex_color}; border:1px solid #ccc; border-radius:8px; cursor:pointer; transition: all 0.2s ease; {outline_style}" data-color="{hex_color}" title="{tooltip}"></div>
                <div style="text-align:center; font-size:9px; color:#666;">{hex_color}</div>
            </div>
            ''')

        parts.append("</div>")
        return parts

    recommended_colors = _get_recommended_colors(
        colors,
        reference_color=reference_color,
        limit=RECOMMENDED_REPLACEMENT_COUNT,
    )
    if recommended_colors:
        section_title = I18n.get("lut_grid_recommended", lang).format(
            count=len(recommended_colors)
        )
        section_hint = I18n.get("lut_grid_recommended_hint", lang)
        html_parts.append(
            f'<p style="color:#0D6EFD; font-size:11px; margin:8px 0 4px 0; font-weight:bold;">{section_title}</p>'
        )
        html_parts.append(
            f'<p style="color:#5b6b7a; font-size:10px; margin:0 0 6px 0;">{section_hint}</p>'
        )
        html_parts.extend(render_color_grid(recommended_colors))

    # Render used colors section (if any)
    if used_in_image:
        section_title = I18n.get("lut_grid_used", lang).format(count=len(used_in_image))
        html_parts.extend(render_color_grid(used_in_image, section_title, "#4CAF50"))

    # Render unused colors section
    if not_used:
        section_title = None
        if used_in_image:
            section_title = I18n.get("lut_grid_other", lang).format(count=len(not_used))
        html_parts.extend(render_color_grid(not_used, section_title, "#888"))

    html_parts.append("</div>")
    # Note: JavaScript handlers are now global in crop_extension.py

    return "".join(html_parts)
