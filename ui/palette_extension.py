"""
Lumina Studio - Color Palette Extension
Non-invasive color palette functionality extension for the converter tab.

This module provides enhanced color palette display without modifying core files.
Text and percentage are displayed BELOW the color swatches for better readability.
Click handlers are defined globally in crop_extension.py to survive Gradio re-renders.
"""

from typing import List

from core.i18n import I18n


def build_hue_filter_bar_html(lang: str = "zh") -> str:
    """Build the hue filter button bar HTML (shared by swatch, card, and palette grids)."""
    hue_labels = [
        ('all',     I18n.get('lut_grid_hue_all', lang),     '#666'),
        ('red',     I18n.get('lut_grid_hue_red', lang),     '#e53935'),
        ('orange',  I18n.get('lut_grid_hue_orange', lang),  '#fb8c00'),
        ('yellow',  I18n.get('lut_grid_hue_yellow', lang),  '#fdd835'),
        ('green',   I18n.get('lut_grid_hue_green', lang),   '#43a047'),
        ('cyan',    I18n.get('lut_grid_hue_cyan', lang),    '#00acc1'),
        ('blue',    I18n.get('lut_grid_hue_blue', lang),    '#1e88e5'),
        ('purple',  I18n.get('lut_grid_hue_purple', lang),  '#8e24aa'),
        ('neutral', I18n.get('lut_grid_hue_neutral', lang), '#9e9e9e'),
        ('fav',     I18n.get('lut_grid_hue_fav', lang),     '#ffc107'),
    ]
    parts = ['<div id="lut-hue-filter-bar" style="display:flex; flex-wrap:wrap; gap:3px; margin-bottom:8px;">']
    for hue_key, hue_label, hue_color in hue_labels:
        active_style = "background:#333; color:#fff; border-color:#333;" if hue_key == 'all' else ""
        if hue_key == 'all':
            dot = ''
        elif hue_key == 'neutral':
            # Neutral dot: box-sizing keeps total size at 6px despite border
            dot = f'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:{hue_color};border:1px solid #666;box-sizing:border-box;margin-right:2px;vertical-align:middle;"></span>'
        elif hue_key == 'fav':
            # Star scaled down to match dot size
            dot = '<span style="font-size:8px;margin-right:1px;vertical-align:middle;">⭐</span>'
        else:
            dot = f'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:{hue_color};margin-right:2px;vertical-align:middle;"></span>'
        # Use a unified JS dispatcher that works for both swatch and card modes
        parts.append(
            f'<button class="lut-hue-btn" data-hue="{hue_key}" '
            f'onclick="window.lutHueDispatch && window.lutHueDispatch(\'{hue_key}\', this)" '
            f'style="padding:2px 8px; border:1px solid #ccc; border-radius:10px; background:#f5f5f5; '
            f'cursor:pointer; font-size:10px; height:22px; line-height:16px; {active_style}">{dot}{hue_label}</button>'
        )
    parts.append('</div>')
    return ''.join(parts)


def build_search_bar_html(lang: str = "zh") -> str:
    """Build the search input bar HTML (shared by swatch and card grids)."""
    search_placeholder = I18n.get('lut_grid_search_hex_placeholder', lang)
    search_clear = I18n.get('lut_grid_search_clear', lang)
    return f'''<div style="margin-bottom:8px; display:flex; align-items:center; gap:8px;">
        <span style="font-size:12px; color:#666;">🔍</span>
        <input type="text" id="lut-color-search" placeholder="{search_placeholder}"
               style="flex:1; padding:6px 10px; border:1px solid #ddd; border-radius:6px; font-size:11px; outline:none;"
               oninput="window.lutSearchDispatch && window.lutSearchDispatch(this.value)"
               onfocus="this.style.borderColor='#2196F3'"
               onblur="this.style.borderColor='#ddd'" />
        <button onclick="document.getElementById('lut-color-search').value=''; window.lutSearchDispatch && window.lutSearchDispatch('');"
                style="padding:4px 10px; border:1px solid #ddd; border-radius:6px; background:#f5f5f5; cursor:pointer; font-size:10px;">{search_clear}</button>
    </div>'''


def generate_palette_html(palette: List[dict], replacements: dict = None, selected_color: str = None, lang: str = "zh") -> str:
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
    count_text = I18n.get('palette_count', lang).format(count=len(palette))
    hint_text = I18n.get('palette_hint', lang)
    html_parts = [
        f'<p style="color:#666; margin:4px 8px;">{count_text}</p>',
        f'<p style="color:#888; margin:2px 8px; font-size:11px;">💡 {hint_text}</p>',
        '<div id="palette-grid-container" style="display:flex; flex-wrap:wrap; gap:8px; padding:8px; max-height:400px; overflow-y:auto;">'
    ]
    
    for entry in palette:
        hex_color = entry['hex']
        percentage = entry['percentage']
        
        # Check if this color has a replacement
        replacement_hex = replacements.get(hex_color)
        
        # Build color swatch HTML - text BELOW the swatch
        border_style = "3px solid #ff6b6b" if replacement_hex else "1px solid #ccc"
        
        # Check if this is the selected color
        is_selected = selected_color and hex_color.lower() == selected_color.lower()
        outline_style = "outline: 3px solid #2196F3; outline-offset: 2px;" if is_selected else ""
        
        # Container with flex-direction:column to put text BELOW swatch
        # No onclick - handled by event delegation
        tooltip = I18n.get('palette_tooltip', lang).format(hex=hex_color, pct=percentage)
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
            replacement_title = I18n.get('palette_replaced_with', lang).format(hex=replacement_hex)
            html_parts.append(f'''
            <div style="width:20px; height:60px; display:flex; align-items:center; font-size:16px; color:#666;">→</div>
            <div style="width:40px; height:40px; background:{replacement_hex}; border:2px solid #4CAF50; border-radius:8px;" title="{replacement_title}"></div>
            ''')
    
    html_parts.append('</div>')
    # Note: JavaScript handlers are now global in crop_extension.py
    
    return ''.join(html_parts)


def generate_lut_color_grid_html(colors: List[dict], selected_color: str = None, used_colors: set = None, lang: str = "zh") -> str:
    """
    Generate HTML for displaying LUT available colors as a clickable visual grid.
    Text is displayed BELOW the color swatches.
    Includes hex/RGB search, hue filter buttons, and scroll-to-highlight.
    Uses event delegation for click handling.
    
    Args:
        colors: List of color dicts with 'color' (R,G,B) and 'hex' keys
        selected_color: Currently selected replacement color hex
        used_colors: Set of hex colors currently used in the image (for grouping)
    
    Returns:
        HTML string showing available colors as a clickable grid with search & filters
    """
    if not colors:
        return f"<p style='color:#888;'>{I18n.get('lut_grid_load_hint', lang)}</p>"
    
    used_colors = used_colors or set()
    used_colors_lower = {c.lower() for c in used_colors}
    
    # Separate colors into used and unused
    used_in_image = []
    not_used = []
    
    for entry in colors:
        hex_color = entry['hex']
        if hex_color.lower() in used_colors_lower:
            used_in_image.append(entry)
        else:
            not_used.append(entry)
    
    count_text = I18n.get('lut_grid_count', lang).format(count=len(colors))

    html_parts = [
        f'<p style="color:#666; font-size:12px; margin-bottom:8px;">{count_text}: <span id="lut-color-visible-count">{len(colors)}</span></p>',
        build_search_bar_html(lang),
        build_hue_filter_bar_html(lang),
    ]

    html_parts.append('<div id="lut-color-grid-container" style="max-height:400px; overflow-y:auto; padding:4px;">')
    
    def _classify_hue(r, g, b):
        """Classify RGB color into hue category."""
        import colorsys
        rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
        h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
        h360 = h * 360
        # Neutral: low saturation or very dark/light
        if s < 0.15 or v < 0.10:
            return 'neutral'
        # Hue ranges
        if h360 < 15 or h360 >= 345:
            return 'red'
        elif h360 < 40:
            return 'orange'
        elif h360 < 70:
            return 'yellow'
        elif h360 < 160:
            return 'green'
        elif h360 < 195:
            return 'cyan'
        elif h360 < 260:
            return 'blue'
        elif h360 < 345:
            return 'purple'
        return 'neutral'

    def render_color_grid(color_list, section_title=None, section_color="#666"):
        """Helper to render a section of colors with data-hue attribute."""
        parts = []
        if section_title:
            parts.append(f'<p style="color:{section_color}; font-size:11px; margin:8px 0 4px 0; font-weight:bold;">{section_title}</p>')
        parts.append('<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px;">')
        
        for entry in color_list:
            hex_color = entry['hex']
            r, g, b = entry['color']
            hue_cat = _classify_hue(r, g, b)
            
            is_selected = selected_color and hex_color.lower() == selected_color.lower()
            outline_style = "outline: 3px solid #2196F3; outline-offset: 2px;" if is_selected else ""
            
            tooltip = I18n.get('lut_grid_tooltip', lang).format(hex=hex_color)
            parts.append(f'''
            <div class="lut-color-swatch-container" data-hue="{hue_cat}" style="display:flex; flex-direction:column; align-items:center; gap:4px;">
                <div class="lut-color-swatch" style="width:50px; height:50px; background:{hex_color}; border:1px solid #ccc; border-radius:8px; cursor:pointer; transition: all 0.2s ease; {outline_style}" data-color="{hex_color}" title="{tooltip}"></div>
                <div style="text-align:center; font-size:9px; color:#666;">{hex_color}</div>
            </div>
            ''')
        
        parts.append('</div>')
        return parts
    
    # Render used colors section (if any)
    if used_in_image:
        section_title = I18n.get('lut_grid_used', lang).format(count=len(used_in_image))
        html_parts.extend(render_color_grid(used_in_image, section_title, "#4CAF50"))
    
    # Render unused colors section
    if not_used:
        section_title = None
        if used_in_image:
            section_title = I18n.get('lut_grid_other', lang).format(count=len(not_used))
        html_parts.extend(render_color_grid(not_used, section_title, "#888"))
    
    html_parts.append('</div>')
    
    return ''.join(html_parts)
