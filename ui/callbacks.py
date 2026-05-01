"""
Lumina Studio - UI Callbacks
UI event handling callback functions
"""

import os
import numpy as np
import gradio as gr

from config import ColorSystem, LUT_FILE_PATH
from core.i18n import I18n
from core.extractor import generate_simulated_reference
from utils import LUTManager


def _hex_to_rgb_tuple(hex_color: str):
    h = (hex_color or '').strip().lower()
    if not h.startswith('#'):
        h = f"#{h}"
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))


def _build_full_color_region_mask(cache, selected_color: str):
    q_img = (cache or {}).get('quantized_image')
    m_img = (cache or {}).get('matched_rgb')
    solid = (cache or {}).get('mask_solid')
    if q_img is None or m_img is None or solid is None or not selected_color:
        return None

    rgb = _hex_to_rgb_tuple(selected_color)
    q_match = np.all(q_img == np.array(rgb, dtype=np.uint8), axis=2)
    m_match = np.all(m_img == np.array(rgb, dtype=np.uint8), axis=2)
    return solid & (q_match | m_match)


# ═══════════════════════════════════════════════════════════════
# LUT Management Callbacks
# ═══════════════════════════════════════════════════════════════

_MODE_DOTS = {
    "8-Color":          ["#C12E1F","#FFFF00","#0064F0","#FF00FF","#00FFFF","#F0F0F0","#00AE42","#111111"],
    "6-Color-CMYWGK":   ["#00AE42","#111111","#00FFFF","#FF00FF","#FFFF00","#F0F0F0"],
    "6-Color-RYBWGK":   ["#00AE42","#111111","#DC143C","#FFE600","#0064F0","#F0F0F0"],
    "6-Color":          ["#00AE42","#111111","#DC143C","#FFE600","#0064F0","#F0F0F0"],
    "5-Color Extended": ["#DC143C","#FFE600","#0064F0","#F0F0F0","#111111"],
    "BW":               ["#F0F0F0","#111111"],
    "4-Color-CMYW":     ["#00FFFF","#FF00FF","#FFFF00","#F0F0F0"],
    "4-Color":          ["#DC143C","#FFE600","#0064F0","#F0F0F0"],
}

def _resolve_mode_key(mode: str) -> str:
    if mode == "Merged":         return "Merged"
    if mode.startswith("8-Color"): return "8-Color"
    if "CMYWGK" in mode:         return "6-Color-CMYWGK"
    if "RYBWGK" in mode:         return "6-Color-RYBWGK"
    if mode.startswith("6-Color"): return "6-Color"
    if "5-Color Extended" in mode: return "5-Color Extended"
    if mode.startswith("BW"):    return "BW"
    if "CMYW" in mode:           return "4-Color-CMYW"
    return "4-Color"

def _color_mode_html(mode: str) -> str:
    """Return an HTML snippet with colored dots + label for the given color mode."""
    key = _resolve_mode_key(mode)
    dot_style = ("display:inline-block;width:10px;height:10px;border-radius:50%;"
                 "margin:0 1px;vertical-align:middle;"
                 "box-shadow:inset 0 0 0 1px rgba(128,128,128,0.4)")
    if key == "Merged":
        dots_html = (
            f'<span style="{dot_style};background:conic-gradient('
            '#E53935,#FDD835,#43A047,#1E88E5,#9C27B0,#E91E63,#E53935)"></span>'
        )
        label = "Merged"
    else:
        colors = _MODE_DOTS.get(key, _MODE_DOTS["4-Color"])
        dots_html = "".join(
            f'<span style="{dot_style};background:{c}"></span>' for c in colors
        )
        label = mode.split("(")[0].strip() if "Color" in mode else key
    return f'{dots_html} <span style="font-size:0.8em;color:#aaa">{label}</span>'


def on_lut_select(display_name):
    """
    When user selects LUT from dropdown
    
    Returns:
        tuple: (lut_path, status_message)
    """
    if not display_name:
        return None, ""
    
    lut_path = LUTManager.get_lut_path(display_name)
    
    if lut_path:
        color_mode = LUTManager.infer_color_mode(display_name, lut_path)
        badge = _color_mode_html(color_mode)
        status = f"[OK] Selected: {display_name}<br>{badge}"
        return lut_path, status
    else:
        return None, f"[ERROR] File not found: {display_name}"


def on_lut_upload_save(uploaded_file):
    """
    Save uploaded LUT file (auto-save, no custom name needed)
    
    Returns:
        tuple: (new_dropdown, status_message)
    """
    success, message, new_choices = LUTManager.save_uploaded_lut(uploaded_file, custom_name=None)
    
    return gr.Dropdown(choices=new_choices), message


# ═══════════════════════════════════════════════════════════════
# Extractor Callbacks
# ═══════════════════════════════════════════════════════════════

def _get_corner_labels(mode, page_choice=None):
    if mode is not None and "5-Color Extended" in mode and page_choice is not None and "2" in str(page_choice):
        return ["蓝色 (左上)", "红色 (右上)", "黑色 (右下)", "黄色 (左下)"], None
    conf = ColorSystem.get(mode)
    return conf['corner_labels'], conf.get('corner_labels_en', conf['corner_labels'])


def get_first_hint(mode, page_choice=None):
    labels_zh, labels_en = _get_corner_labels(mode, page_choice)
    label_zh = labels_zh[0]
    label_en = label_zh if labels_en is None else labels_en[0]
    return f"#### 👉 点击 Click: **{label_zh} / {label_en}**"


def get_next_hint(mode, pts_count, page_choice=None):
    labels_zh, labels_en = _get_corner_labels(mode, page_choice)
    if pts_count >= 4:
        return "#### [OK] Positioning complete! Ready to extract!"
    label_zh = labels_zh[pts_count]
    label_en = label_zh if labels_en is None else labels_en[pts_count]
    return f"#### 👉 点击 Click: **{label_zh} / {label_en}**"


def on_extractor_upload(i, mode, page_choice=None):
    """Handle image upload"""
    hint = get_first_hint(mode, page_choice)
    return i, i, [], None, hint


def on_extractor_mode_change(img, mode, page_choice=None):
    """Handle color mode change"""
    hint = get_first_hint(mode, page_choice)
    # Show page selector and merge button for dual-page modes
    is_dual_page = "8-Color" in mode or "5-Color Extended" in mode
    return [], hint, img, gr.update(visible=is_dual_page), gr.update(visible=is_dual_page)


def on_extractor_rotate(i, mode, page_choice=None):
    """Rotate image"""
    from core.extractor import rotate_image
    if i is None:
        return None, None, [], get_first_hint(mode, page_choice)
    r = rotate_image(i, "Rotate Left 90°")
    return r, r, [], get_first_hint(mode, page_choice)


def on_extractor_click(img, pts, mode, page_choice, evt: gr.SelectData):
    """Set corner point by clicking image"""
    from core.extractor import draw_corner_points
    if len(pts) >= 4:
        return img, pts, "#### [OK] 定位完成 Complete!"
    n = pts + [[evt.index[0], evt.index[1]]]
    vis = draw_corner_points(img, n, mode, page_choice)
    hint = get_next_hint(mode, len(n), page_choice)
    return vis, n, hint


def on_extractor_clear(img, mode, page_choice=None):
    """Clear corner points"""
    hint = get_first_hint(mode, page_choice)
    return img, [], hint


def on_extractor_page_change(img, mode, page_choice):
    hint = get_first_hint(mode, page_choice)
    return [], hint, img


# ═══════════════════════════════════════════════════════════════
# Color Replacement Callbacks
# ═══════════════════════════════════════════════════════════════

def on_palette_color_select(palette_html, evt: gr.SelectData, lang: str = "zh"):
    """
    Handle palette color selection from HTML display.
    
    Note: This is a placeholder - Gradio HTML components don't support
    click events directly. The actual selection is done via JavaScript
    or by clicking on the palette display area.
    
    Args:
        palette_html: Current palette HTML
        evt: Selection event data
    
    Returns:
        tuple: (selected_color_hex, display_text)
    """
    # In practice, color selection would be handled differently
    # since Gradio HTML doesn't support click events
    return None, I18n.get('palette_click_to_select', lang)


def on_apply_color_replacement(cache, selected_color, replacement_color,
                               replacement_regions, replacement_history,
                               loop_pos, add_loop,
                               loop_width, loop_length, loop_hole, loop_angle,
                               lang: str = "zh"):
    """
    Apply a color replacement to the preview.

    Returns:
        tuple: (preview_image, updated_cache, palette_html,
                updated_replacement_regions, updated_history, status)
    """
    from core.converter import update_preview_with_replacements

    if cache is None:
        return None, None, "", replacement_regions, replacement_history, I18n.get('palette_need_preview', lang)

    if not selected_color:
        return gr.update(), cache, gr.update(), replacement_regions, replacement_history, I18n.get('palette_need_original', lang)

    if not replacement_color:
        return gr.update(), cache, gr.update(), replacement_regions, replacement_history, I18n.get('palette_need_replacement', lang)

    # Save current regions-only state to history
    new_history = replacement_history.copy() if replacement_history else []
    new_history.append((replacement_regions.copy() if replacement_regions else []))

    new_regions = replacement_regions.copy() if replacement_regions else []

    region_mask = cache.get('selected_region_mask')
    if region_mask is None:
        region_mask = _build_full_color_region_mask(cache, selected_color)

    if region_mask is not None and np.any(region_mask):
        new_regions.append({
            'source': selected_color,
            'matched': cache.get('selected_matched_hex') or selected_color,
            'quantized': cache.get('selected_quantized_hex') or selected_color,
            'replacement': replacement_color,
            'mask': region_mask.copy()
        })

    display, updated_cache, palette_html = update_preview_with_replacements(
        cache, new_regions, loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle,
        lang=lang
    )

    status_msg = I18n.get('palette_replaced', lang).format(src=selected_color, dst=replacement_color)
    return display, updated_cache, palette_html, new_regions, new_history, status_msg



def on_clear_color_replacements(cache, replacement_regions, replacement_history,
                                loop_pos, add_loop,
                                loop_width, loop_length, loop_hole, loop_angle,
                                lang: str = "zh"):
    """
    Clear all color replacements and restore original preview.

    Returns:
        tuple: (preview_image, updated_cache, palette_html,
                empty_replacement_regions, updated_history, status)
    """
    from core.converter import update_preview_with_replacements

    if cache is None:
        return None, None, "", [], [], I18n.get('palette_need_preview', lang)

    # Save current regions-only state to history before clearing
    new_history = replacement_history.copy() if replacement_history else []
    if replacement_regions:
        new_history.append(replacement_regions.copy())

    display, updated_cache, palette_html = update_preview_with_replacements(
        cache, [], loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle,
        lang=lang
    )

    return display, updated_cache, palette_html, [], new_history, I18n.get('palette_cleared', lang)



def on_preview_generated_update_palette(cache, lang: str = "zh"):
    """
    Update palette display after preview is generated.

    Args:
        cache: Preview cache from generate_preview_cached

    Returns:
        tuple: (palette_html, selected_color_state)
    """
    from ui.palette_extension import generate_palette_html

    if cache is None:
        placeholder = I18n.get('conv_palette_replacements_placeholder', lang)
        return (
            f"<p style='color:#888;'>{placeholder}</p>",
            None  # selected_color state
        )

    palette = cache.get('color_palette', [])

    auto_pairs = []
    q_img = cache.get('quantized_image')
    m_img = cache.get('matched_rgb')
    mask = cache.get('mask_solid')
    if q_img is not None and m_img is not None and mask is not None:
        h, w = m_img.shape[:2]
        for y in range(h):
            for x in range(w):
                if not mask[y, x]:
                    continue
                qh = f"#{int(q_img[y,x,0]):02x}{int(q_img[y,x,1]):02x}{int(q_img[y,x,2]):02x}"
                mh = f"#{int(m_img[y,x,0]):02x}{int(m_img[y,x,1]):02x}{int(m_img[y,x,2]):02x}"
                auto_pairs.append({"quantized_hex": qh, "matched_hex": mh})

    palette_html = generate_palette_html(
        palette,
        {},
        None,
        lang=lang,
        replacement_regions=[],
        auto_pairs=auto_pairs,
    )

    return (
        palette_html,
        None  # Reset selected color
    )


def on_color_swatch_click(selected_hex):
    """
    Handle color selection from clicking palette swatch.
    
    Args:
        selected_hex: The hex color value from hidden textbox (set by JavaScript)
    
    Returns:
        tuple: (selected_color_state, display_text)
    """
    if not selected_hex or selected_hex.strip() == "":
        return None, "未选择"
    
    # Clean up the hex value
    hex_color = selected_hex.strip()
    
    return hex_color, f"[OK] {hex_color}"


def on_color_dropdown_select(selected_value):
    """
    Handle color selection from dropdown.
    
    Args:
        selected_value: The hex color value selected from dropdown
    
    Returns:
        tuple: (selected_color_state, display_text)
    """
    if not selected_value:
        return None, "未选择"
    
    return selected_value, f"[OK] {selected_value}"


def on_lut_change_update_colors(lut_path, cache=None):
    """
    Update available replacement colors when LUT selection changes.
    
    This callback extracts all available colors from the selected LUT
    and updates the LUT color grid HTML display, grouping by used/unused.
    
    Args:
        lut_path: Path to the selected LUT file
        cache: Optional preview cache containing color_palette
    
    Returns:
        str: HTML preview of LUT colors
    """
    from core.converter import generate_lut_color_dropdown_html
    
    if not lut_path:
        return "<p style='color:#888;'>请先选择 LUT | Select LUT first</p>"
    
    # Extract used colors from cache if available
    used_colors = set()
    if cache and 'color_palette' in cache:
        for entry in cache['color_palette']:
            used_colors.add(entry['hex'])
    
    html_preview = generate_lut_color_dropdown_html(lut_path, used_colors=used_colors)
    
    return html_preview


def on_preview_update_lut_colors(cache, lut_path):
    """
    Update LUT color display after preview is generated.
    
    Groups colors into "used in image" and "other available" sections.
    
    Args:
        cache: Preview cache containing color_palette
        lut_path: Path to the selected LUT file
    
    Returns:
        str: HTML preview of LUT colors with grouping
    """
    from core.converter import generate_lut_color_dropdown_html
    
    if not lut_path:
        return "<p style='color:#888;'>请先选择 LUT | Select LUT first</p>"
    
    # Extract used colors from cache
    used_colors = set()
    if cache and 'color_palette' in cache:
        for entry in cache['color_palette']:
            used_colors.add(entry['hex'])
    
    html_preview = generate_lut_color_dropdown_html(lut_path, used_colors=used_colors)
    
    return html_preview


def on_lut_color_swatch_click(selected_hex):
    """
    Handle LUT color selection from clicking color swatch.
    
    Args:
        selected_hex: The hex color value from hidden textbox (set by JavaScript)
    
    Returns:
        tuple: (selected_color_state, display_text)
    """
    if not selected_hex or selected_hex.strip() == "":
        return None, "未选择替换颜色"
    
    # Clean up the hex value
    hex_color = selected_hex.strip()
    
    return hex_color, f"替换为: {hex_color}"


def on_replacement_color_select(selected_value):
    """
    Handle replacement color selection from LUT color dropdown.
    
    Args:
        selected_value: The hex color value selected from dropdown
    
    Returns:
        str: Display text showing selected color
    """
    if not selected_value:
        return "未选择替换颜色"
    
    return f"替换为: {selected_value}"


# ═══════════════════════════════════════════════════════════════
# Color Highlight Callbacks
# ═══════════════════════════════════════════════════════════════

def on_highlight_color_change(highlight_hex, cache, loop_pos, add_loop,
                              loop_width, loop_length, loop_hole, loop_angle):
    """
    Handle color highlight request from palette click.
    
    When user clicks a color in the palette, this callback generates
    a preview with that color highlighted (other colors dimmed).
    
    Args:
        highlight_hex: Hex color to highlight (from hidden textbox)
        cache: Preview cache from generate_preview_cached
        loop_pos: Loop position tuple
        add_loop: Whether loop is enabled
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle
    
    Returns:
        tuple: (preview_image, status_message)
    """
    from core.converter import generate_highlight_preview
    
    if not highlight_hex or highlight_hex.strip() == "":
        # No highlight - return normal preview
        from core.converter import clear_highlight_preview
        return clear_highlight_preview(
            cache, loop_pos, add_loop,
            loop_width, loop_length, loop_hole, loop_angle
        )
    
    return generate_highlight_preview(
        cache, highlight_hex.strip(),
        loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle
    )


def on_clear_highlight(cache, loop_pos, add_loop,
                       loop_width, loop_length, loop_hole, loop_angle):
    """
    Clear color highlight and restore normal preview.
    
    Args:
        cache: Preview cache from generate_preview_cached
        loop_pos: Loop position tuple
        add_loop: Whether loop is enabled
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle
    
    Returns:
        tuple: (preview_image, status_message, cleared_highlight_state)
    """
    from core.converter import clear_highlight_preview
    
    print(f"[ON_CLEAR_HIGHLIGHT] Called with cache={cache is not None}, loop_pos={loop_pos}, add_loop={add_loop}")
    
    display, status = clear_highlight_preview(
        cache, loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle
    )
    
    print(f"[ON_CLEAR_HIGHLIGHT] Returning display={display is not None}, status={status}")
    
    return display, status, ""  # Clear the highlight state


# ═══════════════════════════════════════════════════════════════
# Undo Color Replacement Callback
# ═══════════════════════════════════════════════════════════════

def on_delete_selected_user_replacement(
    cache, replacement_regions, replacement_history,
    selected_user_row_id,
    loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
    lang: str = 'zh'
):
    """按选中用户行删除并刷新预览（regions-only）。"""
    updater = globals().get('update_preview_with_replacements')
    if updater is None:
        from core.converter import update_preview_with_replacements as updater

    if cache is None:
        return None, None, "", replacement_regions, replacement_history, I18n.get('palette_need_preview', lang), selected_user_row_id

    if not selected_user_row_id:
        return gr.update(), cache, gr.update(), replacement_regions, replacement_history, I18n.get('conv_palette_delete_selected_empty', lang), selected_user_row_id

    old_regions = replacement_regions.copy() if replacement_regions else []

    new_history = replacement_history.copy() if replacement_history else []
    new_history.append(old_regions.copy())

    raw_user_rows = []
    for item in old_regions:
        raw_user_rows.append({
            'quantized': (item.get('quantized') or item.get('source') or '').lower(),
            'matched': (item.get('matched') or item.get('source') or '').lower(),
            'replacement': (item.get('replacement') or '').lower(),
            'origin': 'region',
            'index': len(raw_user_rows),
        })

    filtered_rows = [r for r in raw_user_rows if r['quantized'] and r['replacement']]
    indexed_rows = []
    for idx, r in enumerate(filtered_rows):
        rr = dict(r)
        rr['row_id'] = f"user::{rr['quantized']}|{rr['matched']}|{rr['replacement']}|{idx}"
        indexed_rows.append(rr)
    user_rows = list(reversed(indexed_rows))

    target = next((r for r in user_rows if r['row_id'] == selected_user_row_id), None)
    if target is None:
        return gr.update(), cache, gr.update(), old_regions, new_history, I18n.get('conv_palette_delete_selected_empty', lang), None

    new_regions = old_regions.copy()

    rev_idx = user_rows.index(target)
    raw_index = (len(raw_user_rows) - 1) - rev_idx
    if 0 <= raw_index < len(raw_user_rows):
        del new_regions[raw_index]
    else:
        q, m, rep = target['quantized'], target['matched'], target['replacement']
        for i, item in enumerate(new_regions):
            iq = (item.get('quantized') or item.get('source') or '').lower()
            im = (item.get('matched') or item.get('source') or '').lower()
            ir = (item.get('replacement') or '').lower()
            if iq == q and im == m and ir == rep:
                del new_regions[i]
                break

    display, updated_cache, palette_html = updater(
        cache, new_regions,
        loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
        lang=lang
    )

    return display, updated_cache, palette_html, new_regions, new_history, I18n.get('palette_cleared', lang), None


def on_undo_color_replacement(cache, replacement_regions, replacement_history,
                               loop_pos, add_loop, loop_width, loop_length,
                               loop_hole, loop_angle, lang: str = "zh"):
    """
    Undo the last color replacement operation (regions-only).
    """
    from core.converter import update_preview_with_replacements

    if cache is None:
        return None, None, "", replacement_regions, replacement_history, I18n.get('palette_need_preview', lang)

    if not replacement_history:
        return None, cache, "", replacement_regions, replacement_history, I18n.get('palette_undo_empty', lang)

    new_history = replacement_history.copy()
    previous_regions = new_history.pop()

    display, updated_cache, palette_html = update_preview_with_replacements(
        cache, previous_regions, loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle,
        lang=lang
    )

    return display, updated_cache, palette_html, previous_regions, new_history, I18n.get('palette_undone', lang)


def run_extraction_wrapper(img, points, offset_x, offset_y, zoom, barrel, wb, bright, color_mode, page_choice):
    """Wrapper for extraction: supports 8-Color and 5-Color Extended page saving."""
    from core.extractor import run_extraction
    
    run_mode = color_mode
    
    vis, prev, lut_path, status = run_extraction(
        img, points, offset_x, offset_y, zoom, barrel, wb, bright, run_mode, page_choice
    )
    
    # Handle 8-Color dual-page saving
    if "8-Color" in color_mode and lut_path:
        import sys
        # Handle both dev and frozen modes
        if getattr(sys, 'frozen', False):
            assets_dir = os.path.join(os.getcwd(), "assets")
        else:
            assets_dir = "assets"
        
        os.makedirs(assets_dir, exist_ok=True)
        page_idx = 1 if "1" in str(page_choice) else 2
        temp_path = os.path.join(assets_dir, f"temp_8c_page_{page_idx}.npy")
        try:
            lut = np.load(lut_path)
            np.save(temp_path, lut)
            # Return the assets path, not the original LUT_FILE_PATH
            # This ensures manual corrections are saved to the correct location
            print(f"[8-COLOR] Saved page {page_idx} to: {temp_path}")
            lut_path = temp_path
        except Exception as e:
            print(f"[8-COLOR] Error saving page {page_idx}: {e}")
    
    # Handle 5-Color Extended dual-page saving
    if "5-Color Extended" in color_mode and lut_path:
        import sys
        # Handle both dev and frozen modes
        if getattr(sys, 'frozen', False):
            assets_dir = os.path.join(os.getcwd(), "assets")
        else:
            assets_dir = "assets"
        
        os.makedirs(assets_dir, exist_ok=True)
        page_idx = 1 if "1" in str(page_choice) else 2
        temp_path = os.path.join(assets_dir, f"temp_5c_ext_page_{page_idx}.npy")
        try:
            lut = np.load(lut_path)
            np.save(temp_path, lut)
            print(f"[5C-EXT] Saved page {page_idx} to: {temp_path}")
            lut_path = temp_path
        except Exception as e:
            print(f"[5C-EXT] Error saving page {page_idx}: {e}")
    
    return vis, prev, lut_path, status


def merge_8color_data():
    """Concatenate two 8-color pages and save to LUT_FILE_PATH."""
    import sys
    # Handle both dev and frozen modes
    if getattr(sys, 'frozen', False):
        assets_dir = os.path.join(os.getcwd(), "assets")
    else:
        assets_dir = "assets"
    
    path1 = os.path.join(assets_dir, "temp_8c_page_1.npy")
    path2 = os.path.join(assets_dir, "temp_8c_page_2.npy")
    
    print(f"[MERGE_8COLOR] Looking for page 1: {path1}")
    print(f"[MERGE_8COLOR] Looking for page 2: {path2}")
    print(f"[MERGE_8COLOR] Page 1 exists: {os.path.exists(path1)}")
    print(f"[MERGE_8COLOR] Page 2 exists: {os.path.exists(path2)}")
    
    if not os.path.exists(path1) or not os.path.exists(path2):
        return None, "[ERROR] Missing temp pages. Please extract Page 1 and Page 2 first."
    
    try:
        lut1 = np.load(path1)
        lut2 = np.load(path2)
        print(f"[MERGE_8COLOR] Page 1 shape: {lut1.shape}")
        print(f"[MERGE_8COLOR] Page 2 shape: {lut2.shape}")
        
        merged = np.concatenate([lut1, lut2], axis=0)
        print(f"[MERGE_8COLOR] Merged shape: {merged.shape}")
        
        np.save(LUT_FILE_PATH, merged)
        print(f"[MERGE_8COLOR] Saved merged LUT to: {LUT_FILE_PATH}")
        
        return LUT_FILE_PATH, "[OK] 8-Color LUT merged and saved!"
    except Exception as e:
        print(f"[MERGE_8COLOR] Error: {e}")
        import traceback
        traceback.print_exc()
        return None, f"[ERROR] Merge failed: {e}"


def merge_5color_extended_data():
    """Concatenate two 5-Color Extended pages and save to LUT_FILE_PATH."""
    import sys
    # Handle both dev and frozen modes
    if getattr(sys, 'frozen', False):
        assets_dir = os.path.join(os.getcwd(), "assets")
    else:
        assets_dir = "assets"
    
    path1 = os.path.join(assets_dir, "temp_5c_ext_page_1.npy")
    path2 = os.path.join(assets_dir, "temp_5c_ext_page_2.npy")
    
    print(f"[MERGE_5C_EXT] Looking for page 1: {path1}")
    print(f"[MERGE_5C_EXT] Looking for page 2: {path2}")
    print(f"[MERGE_5C_EXT] Page 1 exists: {os.path.exists(path1)}")
    print(f"[MERGE_5C_EXT] Page 2 exists: {os.path.exists(path2)}")
    
    if not os.path.exists(path1) or not os.path.exists(path2):
        return None, "❌ Missing temp pages. Please extract Page 1 and Page 2 first."
    
    try:
        lut1 = np.load(path1)
        lut2 = np.load(path2)
        print(f"[MERGE_5C_EXT] Page 1 shape: {lut1.shape}")
        print(f"[MERGE_5C_EXT] Page 2 shape: {lut2.shape}")

        lut1_rgb = lut1.reshape(-1, 3)
        lut2_rgb = lut2.reshape(-1, 3)
        merged = np.vstack([lut1_rgb, lut2_rgb]).astype(np.uint8, copy=False)
        print(f"[MERGE_5C_EXT] Merged shape: {merged.shape}")

        np.save(LUT_FILE_PATH, merged)
        print(f"[MERGE_5C_EXT] Saved merged LUT to: {LUT_FILE_PATH}")
        
        return LUT_FILE_PATH, "✅ 5-Color Extended LUT merged and saved! (2468 colors)"
    except Exception as e:
        print(f"[MERGE_5C_EXT] Error: {e}")
        import traceback
        traceback.print_exc()
        return None, f"❌ Merge failed: {e}"


# ═══════════════════════════════════════════════════════════════
# LUT Merge Callbacks
# ═══════════════════════════════════════════════════════════════

def on_merge_lut_select(display_name, lang="zh"):
    """
    When user selects a LUT in the merge tab, detect its color mode.

    Returns:
        str: Markdown showing detected mode
    """
    from core.lut_merger import LUTMerger

    if not display_name:
        label = I18n.get('merge_mode_label', lang)
        unknown = I18n.get('merge_mode_unknown', lang)
        return f"**{label}**: {unknown}"

    lut_path = LUTManager.get_lut_path(display_name)
    if not lut_path:
        return f"**{I18n.get('merge_mode_label', lang)}**: [ERROR] File not found"

    try:
        mode, count = LUTMerger.detect_color_mode(lut_path)
        return f"**{I18n.get('merge_mode_label', lang)}**: {mode} ({count} colors)"
    except Exception as e:
        return f"**{I18n.get('merge_mode_label', lang)}**: [ERROR] {e}"


def on_merge_primary_select(display_name, lang="zh"):
    """
    When user selects the primary LUT, detect its mode and filter secondary choices.

    Primary must be 6-Color or 8-Color.
    - 8-Color primary → secondary can be BW, 4-Color, 6-Color
    - 6-Color primary → secondary can be BW, 4-Color

    Returns:
        tuple: (mode_markdown, updated_secondary_dropdown)
    """
    from core.lut_merger import LUTMerger

    if not display_name:
        return (
            I18n.get('merge_primary_hint', lang),
            gr.Dropdown(choices=[], value=[]),
        )

    lut_path = LUTManager.get_lut_path(display_name)
    if not lut_path:
        return (
            f"**{I18n.get('merge_mode_label', lang)}**: ❌ File not found",
            gr.Dropdown(choices=[], value=[]),
        )

    try:
        mode, count = LUTMerger.detect_color_mode(lut_path)
    except Exception as e:
        return (
            f"**{I18n.get('merge_mode_label', lang)}**: ❌ {e}",
            gr.Dropdown(choices=[], value=[]),
        )

    # Primary must be 6-Color or 8-Color
    if mode not in ("6-Color", "8-Color"):
        return (
            I18n.get('merge_primary_not_high', lang),
            gr.Dropdown(choices=[], value=[]),
        )

    mode_md = f"**{I18n.get('merge_mode_label', lang)}**: {mode} ({count} colors)"

    # Determine allowed secondary modes
    # Exclude "Merged" to prevent stale/corrupt merged LUTs from being re-merged
    if mode == "8-Color":
        allowed_modes = {"BW", "4-Color", "6-Color"}
    else:  # 6-Color
        allowed_modes = {"BW", "4-Color"}

    # Filter LUT choices: exclude the primary itself, only include allowed modes
    all_choices = LUTManager.get_lut_choices()
    filtered = []
    for choice_name in all_choices:
        if choice_name == display_name:
            continue
        path = LUTManager.get_lut_path(choice_name)
        if not path:
            continue
        try:
            m, _ = LUTMerger.detect_color_mode(path)
            if m in allowed_modes:
                filtered.append(choice_name)
        except Exception:
            continue

    return (
        mode_md,
        gr.Dropdown(choices=filtered, value=[]),
    )


def on_merge_secondary_change(selected_names, lang="zh"):
    """
    When user changes secondary LUT selection, show detected modes.

    Args:
        selected_names: List of selected LUT display names (multi-select)

    Returns:
        str: Markdown showing detected modes for each selected LUT
    """
    from core.lut_merger import LUTMerger

    if not selected_names:
        return I18n.get('merge_secondary_none', lang)

    lines = [f"**{I18n.get('merge_secondary_modes', lang)}**:"]
    for name in selected_names:
        path = LUTManager.get_lut_path(name)
        if not path:
            lines.append(f"- {name}: ❌")
            continue
        try:
            mode, count = LUTMerger.detect_color_mode(path)
            lines.append(f"- {name}: **{mode}** ({count} colors)")
        except Exception as e:
            lines.append(f"- {name}: ❌ {e}")

    return "\n".join(lines)


def on_merge_execute(primary_name, secondary_names, dedup_threshold, lang="zh"):
    """
    Execute LUT merge: primary + multiple secondary LUTs.

    Returns:
        tuple: (status_markdown, updated_primary_dropdown, updated_secondary_dropdown)
    """
    from core.lut_merger import LUTMerger
    import time

    # Validate primary
    if not primary_name:
        return I18n.get('merge_error_no_lut', lang), gr.update(), gr.update()

    # Validate secondary
    if not secondary_names or len(secondary_names) == 0:
        return I18n.get('merge_error_no_secondary', lang), gr.update(), gr.update()

    primary_path = LUTManager.get_lut_path(primary_name)
    if not primary_path:
        return I18n.get('merge_error_no_lut', lang), gr.update(), gr.update()

    try:
        # Detect primary mode
        primary_mode, _ = LUTMerger.detect_color_mode(primary_path)

        # Load primary
        primary_rgb, primary_stacks = LUTMerger.load_lut_with_stacks(primary_path, primary_mode)
        entries = [(primary_rgb, primary_stacks, primary_mode)]
        all_modes = [primary_mode]

        # Load each secondary (skip Merged LUTs to prevent stale data contamination)
        for sec_name in secondary_names:
            sec_path = LUTManager.get_lut_path(sec_name)
            if not sec_path:
                continue
            sec_mode, _ = LUTMerger.detect_color_mode(sec_path)
            if sec_mode == "Merged":
                print(f"[MERGE] Skipping Merged LUT as secondary: {sec_name}")
                continue
            sec_rgb, sec_stacks = LUTMerger.load_lut_with_stacks(sec_path, sec_mode)
            entries.append((sec_rgb, sec_stacks, sec_mode))
            all_modes.append(sec_mode)

        if len(entries) < 2:
            return I18n.get('merge_error_no_lut', lang), gr.update(), gr.update()

        # Validate compatibility
        valid, err_msg = LUTMerger.validate_compatibility(all_modes)
        if not valid:
            return I18n.get('merge_error_incompatible', lang).format(msg=err_msg), gr.update(), gr.update()

        # Merge
        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(entries, dedup_threshold=dedup_threshold)

        # Save to Custom folder
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        mode_str = "+".join(all_modes)
        output_name = f"Merged_{mode_str}_{timestamp}.npz"
        custom_dir = os.path.join(LUTManager.LUT_PRESET_DIR, "Custom")
        os.makedirs(custom_dir, exist_ok=True)
        output_path = os.path.join(custom_dir, output_name)

        saved_path = LUTMerger.save_merged_lut(merged_rgb, merged_stacks, output_path)

        # Build success message
        status = I18n.get('merge_status_success', lang).format(
            before=stats['total_before'],
            after=stats['total_after'],
            exact=stats['exact_dupes'],
            similar=stats['similar_removed'],
            path=os.path.basename(saved_path),
        )

        # Refresh dropdown choices
        new_choices = LUTManager.get_lut_choices()
        return status, gr.Dropdown(choices=new_choices), gr.Dropdown(choices=[], value=[])

    except Exception as e:
        print(f"[MERGE] Error: {e}")
        import traceback
        traceback.print_exc()
        return I18n.get('merge_error_failed', lang).format(msg=str(e)), gr.update(), gr.update()


# ═══════════════════════════════════════════════════════════════
# Color Merging Callbacks
# ═══════════════════════════════════════════════════════════════

def on_merge_preview(cache, merge_enable, merge_threshold, merge_max_distance,
                    loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
                    lang: str = "zh"):
    """
    Generate preview with color merging applied.
    
    Args:
        cache: Preview cache from generate_preview_cached
        merge_enable: Whether merging is enabled
        merge_threshold: Usage threshold percentage (0.1-5.0)
        merge_max_distance: Maximum Delta-E distance (5-50)
        loop_pos: Loop position tuple
        add_loop: Whether loop is enabled
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle
        lang: Language code
    
    Returns:
        tuple: (preview_image, updated_cache, palette_html, merge_map, merge_stats, status)
    """
    from core.converter import update_preview_with_replacements, extract_color_palette
    from core.color_merger import ColorMerger
    from core.image_processing import LuminaImageProcessor
    from ui.palette_extension import generate_palette_html
    
    if cache is None:
        return None, None, "", {}, {}, I18n.get('palette_need_preview', lang)
    
    # If merging is disabled, return empty merge map
    if not merge_enable:
        return gr.update(), cache, gr.update(), {}, {}, I18n.get('merge_status_empty', lang)
    
    # Extract color palette from cache
    palette = cache.get('color_palette', [])
    
    if not palette:
        return gr.update(), cache, gr.update(), {}, {}, I18n.get('merge_error_empty_palette', lang)
    
    # Handle edge cases
    if len(palette) == 1:
        return gr.update(), cache, gr.update(), {}, {}, I18n.get('merge_error_single_color', lang)
    
    # Build merge map using ColorMerger
    merger = ColorMerger(LuminaImageProcessor._rgb_to_lab)
    merge_map = merger.build_merge_map(palette, merge_threshold, merge_max_distance)
    
    # Check if all colors are below threshold
    if not merge_map and len(palette) > 1:
        low_usage_colors = merger.identify_low_usage_colors(palette, merge_threshold)
        if len(low_usage_colors) >= len(palette):
            return gr.update(), cache, gr.update(), {}, {}, I18n.get('merge_error_all_below_threshold', lang)
    
    # If no colors to merge, return info message
    if not merge_map:
        return gr.update(), cache, gr.update(), {}, {}, I18n.get('merge_info_low_usage', lang).format(
            count=0, threshold=merge_threshold
        )
    
    # Apply merge map to preview (without modifying cache yet)
    # Create a temporary cache with merged colors (deep copy matched_rgb to avoid modifying original)
    temp_cache = cache.copy()
    matched_rgb = temp_cache.get('matched_rgb')
    
    if matched_rgb is not None:
        # Deep copy to avoid modifying original cache
        matched_rgb_copy = matched_rgb.copy()
        merged_rgb = merger.apply_color_merging(matched_rgb_copy, merge_map)
        temp_cache['matched_rgb'] = merged_rgb
        
        # Re-extract palette from merged image
        merged_palette = extract_color_palette(temp_cache)
        temp_cache['color_palette'] = merged_palette
    else:
        merged_palette = palette
    
    # Calculate quality metric
    quality = merger.calculate_quality_metric(palette, merged_palette, merge_map)
    
    # Build merge stats
    merge_stats = {
        'total_colors_before': len(palette),
        'total_colors_after': len(merged_palette),
        'colors_merged': len(merge_map),
        'merge_map': merge_map,
        'quality_metric': quality
    }
    
    # Generate updated preview
    display, updated_cache, palette_html = update_preview_with_replacements(
        temp_cache, {}, loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle,
        merge_map=None,  # Don't pass merge_map here since temp_cache already has merged colors
        lang=lang
    )
    
    # Status message
    status_msg = I18n.get('merge_status_preview', lang).format(
        merged=len(merge_map),
        quality=quality
    )
    
    return display, updated_cache, palette_html, merge_map, merge_stats, status_msg


def on_merge_apply(cache, merge_map, merge_stats, loop_pos, add_loop,
                  loop_width, loop_length, loop_hole, loop_angle,
                  lang: str = "zh"):
    """
    Apply color merging to the cached image data.
    
    Args:
        cache: Preview cache from generate_preview_cached
        merge_map: Dict mapping source hex to target hex colors
        merge_stats: Merge statistics dict
        loop_pos: Loop position tuple
        add_loop: Whether loop is enabled
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle
        lang: Language code
    
    Returns:
        tuple: (preview_image, updated_cache, palette_html, status)
    """
    from core.converter import update_preview_with_replacements, extract_color_palette
    from core.color_merger import ColorMerger
    from core.image_processing import LuminaImageProcessor
    
    if cache is None:
        return None, None, "", I18n.get('palette_need_preview', lang)
    
    if not merge_map:
        return gr.update(), cache, gr.update(), I18n.get('merge_status_empty', lang)
    
    # Save original matched_rgb for potential revert
    if 'original_matched_rgb' not in cache:
        cache['original_matched_rgb'] = cache.get('matched_rgb').copy()
    
    # Apply merging
    merger = ColorMerger(LuminaImageProcessor._rgb_to_lab)
    matched_rgb = cache.get('matched_rgb')
    
    if matched_rgb is not None:
        merged_rgb = merger.apply_color_merging(matched_rgb, merge_map)
        cache['matched_rgb'] = merged_rgb
        
        # Re-extract palette
        merged_palette = extract_color_palette(cache)
        cache['color_palette'] = merged_palette
    
    # Store merge info in cache
    cache['merge_map'] = merge_map
    cache['merge_stats'] = merge_stats
    
    # Generate updated preview
    display, updated_cache, palette_html = update_preview_with_replacements(
        cache, {}, loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle,
        lang=lang
    )
    
    # Status message
    status_msg = I18n.get('merge_status_applied', lang).format(
        merged=len(merge_map)
    )
    
    return display, updated_cache, palette_html, status_msg


def on_merge_revert(cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
                   lang: str = "zh"):
    """
    Revert color merging and restore original colors.
    
    Args:
        cache: Preview cache from generate_preview_cached
        loop_pos: Loop position tuple
        add_loop: Whether loop is enabled
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle
        lang: Language code
    
    Returns:
        tuple: (preview_image, updated_cache, palette_html, empty_merge_map, empty_stats, status)
    """
    from core.converter import update_preview_with_replacements, extract_color_palette
    
    if cache is None:
        return None, None, "", {}, {}, I18n.get('palette_need_preview', lang)
    
    # Restore original matched_rgb if it exists
    if 'original_matched_rgb' in cache:
        cache['matched_rgb'] = cache['original_matched_rgb'].copy()
        del cache['original_matched_rgb']
        
        # Re-extract palette
        original_palette = extract_color_palette(cache)
        cache['color_palette'] = original_palette
    
    # Clear merge info
    if 'merge_map' in cache:
        del cache['merge_map']
    if 'merge_stats' in cache:
        del cache['merge_stats']
    
    # Generate updated preview
    display, updated_cache, palette_html = update_preview_with_replacements(
        cache, {}, loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle,
        lang=lang
    )
    
    # Status message
    status_msg = I18n.get('merge_status_reverted', lang)
    
    return display, updated_cache, palette_html, {}, {}, status_msg
