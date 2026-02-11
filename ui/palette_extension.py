"""
Lumina Studio - Color Palette Extension
Non-invasive color palette functionality extension for the converter tab.

This module provides enhanced color palette display without modifying core files.
Text and percentage are displayed BELOW the color swatches for better readability.
Click handlers are defined globally in crop_extension.py to survive Gradio re-renders.
"""

from typing import List

from core.i18n import I18n


def generate_palette_html(
    palette: List[dict],
    replacements: dict = None,
    selected_color: str = None,
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

    # Note: JavaScript click handlers are now in crop_extension.py (global head JS)
    # The script tags here are kept for reference but won't execute via innerHTML

    # Show total color count with highlight hint
    count_text = I18n.get("palette_count", lang).format(count=len(palette))
    hint_text = I18n.get("palette_hint", lang)
    html_parts = [
        f'<p style="color:#666; margin:4px 8px;">{count_text}</p>',
        f'<p style="color:#888; margin:2px 8px; font-size:11px;">💡 {hint_text}</p>',
        '<div id="palette-grid-container" style="display:flex; flex-wrap:wrap; gap:8px; padding:8px; max-height:400px; overflow-y:auto;">',
    ]

    for entry in palette:
        hex_color = entry["hex"]
        percentage = entry["percentage"]

        # Check if this color has a replacement
        replacement_hex = replacements.get(hex_color)

        # Build color swatch HTML - text BELOW the swatch
        border_style = "3px solid #ff6b6b" if replacement_hex else "1px solid #ccc"

        # Check if this is the selected color
        is_selected = selected_color and hex_color.lower() == selected_color.lower()
        outline_style = (
            "outline: 3px solid #2196F3; outline-offset: 2px;" if is_selected else ""
        )

        # Container with flex-direction:column to put text BELOW swatch
        # No onclick - handled by event delegation
        tooltip = I18n.get("palette_tooltip", lang).format(
            hex=hex_color, pct=percentage
        )
        html_parts.append(f'''
        <div class="palette-swatch-container" style="display:flex; flex-direction:column; align-items:center; gap:4px;">
            <div class="palette-swatch" style="width:50px; height:50px; background:{hex_color}; border:{border_style}; border-radius:8px; cursor:pointer; transition: all 0.2s ease; {outline_style}" data-color="{hex_color}" title="{tooltip}"></div>
            <div style="text-align:center; font-size:10px; color:#333;">
                <div style="font-weight:bold;">{percentage}%</div>
                <div style="font-size:8px; color:#666;">{hex_color}</div>
            </div>
        </div>
        ''')

        # Show replacement indicator if exists
        if replacement_hex:
            replacement_title = I18n.get("palette_replaced_with", lang).format(
                hex=replacement_hex
            )
            html_parts.append(f'''
            <div style="width:20px; height:60px; display:flex; align-items:center; font-size:16px; color:#666;">→</div>
            <div style="width:40px; height:40px; background:{replacement_hex}; border:2px solid #4CAF50; border-radius:8px;" title="{replacement_title}"></div>
            ''')

    html_parts.append("</div>")
    # Note: JavaScript handlers are now global in crop_extension.py

    return "".join(html_parts)


def generate_lut_color_grid_html(
    colors: List[dict],
    selected_color: str = None,
    used_colors: set = None,
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
