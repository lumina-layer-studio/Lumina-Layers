"""
Lumina Studio - UI Callbacks
UI event handling callback functions
"""

import os
import numpy as np
import gradio as gr

from config import ColorMode, ColorSystem, LUT_FILE_PATH
from core.i18n import I18n
from utils.i18n_help import resolve_i18n_text
from core.extractor import generate_simulated_reference
from utils import LUTManager


# ═══════════════════════════════════════════════════════════════
# LUT Management Callbacks
# ═══════════════════════════════════════════════════════════════


def on_lut_select(display_name, lang: str = "zh"):
    """
    When user selects LUT from dropdown

    Returns:
        tuple: (lut_path, status_message)
    """
    if not display_name:
        return None, ""

    lut_path = LUTManager.get_lut_path(display_name)

    if lut_path:
        return lut_path, I18n.get("conv_lut_selected", lang).format(name=display_name)
    else:
        return None, I18n.get("conv_lut_file_not_found", lang).format(name=display_name)


def on_lut_upload_save(uploaded_file):
    """
    Save uploaded LUT file (auto-save, no custom name needed)

    Returns:
        tuple: (new_dropdown, status_message)
    """
    success, message, new_choices = LUTManager.save_uploaded_lut(
        uploaded_file, custom_name=None
    )

    return gr.Dropdown(choices=new_choices), message


# ═══════════════════════════════════════════════════════════════
# Extractor Callbacks
# ═══════════════════════════════════════════════════════════════


def get_first_hint(mode, lang: str = "zh"):
    """Get first corner point hint based on mode"""
    mode_enum = ColorMode(mode)
    conf = ColorSystem.get(mode_enum)
    label_zh = conf["corner_labels"][0]
    label_en = conf.get("corner_labels_en", conf["corner_labels"])[0]
    return I18n.get("ext_hint_click_corner", lang).format(
        label_zh=label_zh, label_en=label_en
    )


def get_next_hint(mode, pts_count, lang: str = "zh"):
    """Get next corner point hint based on mode"""
    mode_enum = ColorMode(mode)
    conf = ColorSystem.get(mode_enum)
    if pts_count >= 4:
        return I18n.get("ext_hint_positioning_complete", lang)
    label_zh = conf["corner_labels"][pts_count]
    label_en = conf.get("corner_labels_en", conf["corner_labels"])[pts_count]
    return I18n.get("ext_hint_click_corner", lang).format(
        label_zh=label_zh, label_en=label_en
    )


def on_extractor_upload(i, mode, lang: str = "zh"):
    """Handle image upload"""
    hint = get_first_hint(mode, lang)
    return i, i, [], None, hint


def on_extractor_mode_change(img, mode, lang: str = "zh"):
    """Handle color mode change"""
    hint = get_first_hint(mode, lang)
    return [], hint, img


def on_extractor_rotate(i, mode, lang: str = "zh"):
    """Rotate image"""
    from core.extractor import rotate_image

    if i is None:
        return None, None, [], get_first_hint(mode, lang)
    r = rotate_image(i, "Rotate Left 90°")
    return r, r, [], get_first_hint(mode, lang)


def on_extractor_click(img, pts, mode, evt: gr.SelectData, lang: str = "zh"):
    """Set corner point by clicking image"""
    from core.extractor import draw_corner_points

    if len(pts) >= 4:
        return img, pts, I18n.get("ext_hint_positioning_done", lang)
    n = pts + [[evt.index[0], evt.index[1]]]
    vis = draw_corner_points(img, n, mode)
    hint = get_next_hint(mode, len(n), lang)
    return vis, n, hint


def on_extractor_clear(img, mode, lang: str = "zh"):
    """Clear corner points"""
    hint = get_first_hint(mode, lang)
    return img, [], hint


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
    return None, I18n.get("palette_click_to_select", lang)


def on_apply_color_replacement(
    cache,
    selected_color,
    replacement_color,
    replacement_map,
    replacement_history,
    loop_pos,
    add_loop,
    loop_width,
    loop_length,
    loop_hole,
    loop_angle,
    lang: str = "zh",
):
    """
    Apply a color replacement to the preview.

    Args:
        cache: Preview cache from generate_preview_cached
        selected_color: Currently selected original color (hex string)
        replacement_color: New color to replace with (hex string from ColorPicker)
        replacement_map: Current replacement map dict
        replacement_history: History stack for undo
        loop_pos: Loop position tuple
        add_loop: Whether loop is enabled
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle

    Returns:
        tuple: (preview_image, updated_cache, palette_html, updated_replacement_map,
                updated_history, status)
    """
    from ui.converter_ui import update_preview_with_replacements, generate_palette_html

    if cache is None:
        return (
            None,
            None,
            "",
            replacement_map,
            replacement_history,
            I18n.get("palette_need_preview", lang),
        )

    if not selected_color:
        return (
            gr.update(),
            cache,
            gr.update(),
            replacement_map,
            replacement_history,
            I18n.get("palette_need_original", lang),
        )

    if not replacement_color:
        return (
            gr.update(),
            cache,
            gr.update(),
            replacement_map,
            replacement_history,
            I18n.get("palette_need_replacement", lang),
        )

    # Save current state to history before applying new replacement
    new_history = replacement_history.copy() if replacement_history else []
    new_history.append(replacement_map.copy() if replacement_map else {})

    # Update replacement map
    new_map = replacement_map.copy() if replacement_map else {}
    new_map[selected_color] = replacement_color

    # Apply replacements and update preview
    display, updated_cache, palette_html = update_preview_with_replacements(
        cache,
        new_map,
        loop_pos,
        add_loop,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        lang=lang,
    )

    status_msg = I18n.get("palette_replaced", lang).format(
        src=selected_color, dst=replacement_color
    )
    return display, updated_cache, palette_html, new_map, new_history, status_msg


def on_clear_color_replacements(
    cache,
    replacement_map,
    replacement_history,
    loop_pos,
    add_loop,
    loop_width,
    loop_length,
    loop_hole,
    loop_angle,
    lang: str = "zh",
):
    """
    Clear all color replacements and restore original preview.

    Args:
        cache: Preview cache
        replacement_map: Current replacement map dict
        replacement_history: History stack for undo
        loop_pos: Loop position tuple
        add_loop: Whether loop is enabled
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle

    Returns:
        tuple: (preview_image, updated_cache, palette_html, empty_replacement_map,
                updated_history, status)
    """
    from ui.converter_ui import update_preview_with_replacements, generate_palette_html

    if cache is None:
        return None, None, "", {}, [], I18n.get("palette_need_preview", lang)

    # Save current state to history before clearing
    new_history = replacement_history.copy() if replacement_history else []
    if replacement_map:
        new_history.append(replacement_map.copy())

    # Clear replacements by passing empty dict
    display, updated_cache, palette_html = update_preview_with_replacements(
        cache,
        {},
        loop_pos,
        add_loop,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        lang=lang,
    )

    return (
        display,
        updated_cache,
        palette_html,
        {},
        new_history,
        I18n.get("palette_cleared", lang),
    )


def on_preview_generated_update_palette(cache, lang: str = "zh"):
    """
    Update palette display after preview is generated.

    Args:
        cache: Preview cache from generate_preview_cached

    Returns:
        tuple: (palette_html, selected_color_state)
    """
    from ui.converter_ui import generate_palette_html

    if cache is None:
        placeholder = I18n.get("conv_palette_replacements_placeholder", lang)
        return (
            f"<p style='color:#888;'>{placeholder}</p>",
            None,  # selected_color state
        )

    palette = cache.get("color_palette", [])
    palette_html = generate_palette_html(
        palette,
        {},
        "",
        original_palette=cache.get("original_color_palette", palette),
        lang=lang,
    )

    return (
        palette_html,
        None,  # Reset selected color
    )


def on_clear_selected_original_color(lang: str = "zh"):
    return None, None, I18n.get("palette_not_selected", lang)


def on_color_swatch_click(selected_hex, lang: str = "zh"):
    """
    Handle color selection from clicking palette swatch.

    Args:
        selected_hex: The hex color value from hidden textbox (set by JavaScript)

    Returns:
        tuple: (selected_color_state, display_text)
    """
    if not selected_hex or selected_hex.strip() == "":
        return None, I18n.get("palette_not_selected", lang)

    # Clean up the hex value
    hex_color = selected_hex.strip()

    return hex_color, I18n.get("palette_selected_format", lang).format(hex=hex_color)


def on_remove_single_color_replacement(
    cache,
    original_color,
    replacement_map,
    replacement_history,
    loop_pos,
    add_loop,
    loop_width,
    loop_length,
    loop_hole,
    loop_angle,
    lang: str = "zh",
):
    from ui.converter_ui import update_preview_with_replacements

    if cache is None:
        return (
            None,
            None,
            "",
            replacement_map,
            replacement_history,
            None,
            I18n.get("palette_need_preview", lang),
        )

    if not original_color:
        return (
            gr.update(),
            cache,
            gr.update(),
            replacement_map,
            replacement_history,
            None,
            I18n.get("palette_remove_missing", lang),
        )

    new_map = replacement_map.copy() if replacement_map else {}
    if original_color not in new_map:
        return (
            gr.update(),
            cache,
            gr.update(),
            replacement_map,
            replacement_history,
            original_color,
            I18n.get("palette_remove_missing", lang),
        )

    removed_target = new_map.pop(original_color)
    new_history = replacement_history.copy() if replacement_history else []
    new_history.append(replacement_map.copy() if replacement_map else {})

    display, updated_cache, palette_html = update_preview_with_replacements(
        cache,
        new_map,
        loop_pos,
        add_loop,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        lang=lang,
    )

    return (
        display,
        updated_cache,
        palette_html,
        new_map,
        new_history,
        original_color,
        I18n.get("palette_removed_one", lang).format(
            src=original_color, dst=removed_target
        ),
    )


def on_color_dropdown_select(selected_value):
    """
    Handle color selection from dropdown.

    Args:
        selected_value: The hex color value selected from dropdown

    Returns:
        tuple: (selected_color_state, display_text)
    """
    if not selected_value:
        return None, I18n.get("palette_not_selected", "zh")

    return selected_value, I18n.get("palette_selected_format", "zh").format(
        hex=selected_value
    )


def on_lut_change_update_colors(lut_path, cache=None, lang: str = "zh"):
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
    from ui.converter_ui import generate_lut_color_dropdown_html

    if not lut_path:
        return f"<p style='color:#888;'>{I18n.get('lut_select_first', lang)}</p>"

    # Extract used colors from cache if available
    used_colors = set()
    if cache and "color_palette" in cache:
        for entry in cache["color_palette"]:
            used_colors.add(entry["hex"])

    html_preview = generate_lut_color_dropdown_html(lut_path, used_colors=used_colors)

    return html_preview


def on_preview_update_lut_colors(cache, lut_path, lang: str = "zh"):
    """
    Update LUT color display after preview is generated.

    Groups colors into "used in image" and "other available" sections.

    Args:
        cache: Preview cache containing color_palette
        lut_path: Path to the selected LUT file

    Returns:
        str: HTML preview of LUT colors with grouping
    """
    from ui.converter_ui import generate_lut_color_dropdown_html

    if not lut_path:
        return f"<p style='color:#888;'>{I18n.get('lut_select_first', lang)}</p>"

    # Extract used colors from cache
    used_colors = set()
    if cache and "color_palette" in cache:
        for entry in cache["color_palette"]:
            used_colors.add(entry["hex"])

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
        return None, I18n.get("palette_replacement_not_selected", "zh")

    # Clean up the hex value
    hex_color = selected_hex.strip()

    return hex_color, I18n.get("palette_replacement_selected", "zh").format(
        hex=hex_color
    )


def on_replacement_color_select(selected_value):
    """
    Handle replacement color selection from LUT color dropdown.

    Args:
        selected_value: The hex color value selected from dropdown

    Returns:
        str: Display text showing selected color
    """
    if not selected_value:
        return I18n.get("palette_replacement_not_selected", "zh")

    return I18n.get("palette_replacement_selected", "zh").format(hex=selected_value)


# ═══════════════════════════════════════════════════════════════
# Color Highlight Callbacks
# ═══════════════════════════════════════════════════════════════


def on_highlight_color_change(
    highlight_hex,
    cache,
    loop_pos,
    add_loop,
    loop_width,
    loop_length,
    loop_hole,
    loop_angle,
):
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
    from ui.converter_ui import generate_highlight_preview

    if not highlight_hex or highlight_hex.strip() == "":
        # No highlight - return normal preview
        from ui.converter_ui import clear_highlight_preview

        return clear_highlight_preview(
            cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle
        )

    return generate_highlight_preview(
        cache,
        highlight_hex.strip(),
        loop_pos,
        add_loop,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
    )


def on_clear_highlight(
    cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle
):
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
    from ui.converter_ui import clear_highlight_preview

    print(
        f"[ON_CLEAR_HIGHLIGHT] Called with cache={cache is not None}, loop_pos={loop_pos}, add_loop={add_loop}"
    )

    display, status = clear_highlight_preview(
        cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle
    )

    print(
        f"[ON_CLEAR_HIGHLIGHT] Returning display={display is not None}, status={status}"
    )

    return display, status, ""  # Clear the highlight state


# ═══════════════════════════════════════════════════════════════
# Undo Color Replacement Callback
# ═══════════════════════════════════════════════════════════════


def on_undo_color_replacement(
    cache,
    replacement_map,
    replacement_history,
    loop_pos,
    add_loop,
    loop_width,
    loop_length,
    loop_hole,
    loop_angle,
    lang: str = "zh",
):
    """
    Undo the last color replacement operation.

    Args:
        cache: Preview cache from generate_preview_cached
        replacement_map: Current replacement map dict
        replacement_history: History stack of previous states
        loop_pos: Loop position tuple
        add_loop: Whether loop is enabled
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle

    Returns:
        tuple: (preview_image, updated_cache, palette_html, updated_replacement_map,
                updated_history, status)
    """
    from ui.converter_ui import update_preview_with_replacements, generate_palette_html

    if cache is None:
        return (
            None,
            None,
            "",
            replacement_map,
            replacement_history,
            I18n.get("palette_need_preview", lang),
        )

    if not replacement_history:
        return (
            None,
            cache,
            "",
            replacement_map,
            replacement_history,
            I18n.get("palette_undo_empty", lang),
        )

    # Pop the last state from history
    new_history = replacement_history.copy()
    previous_map = new_history.pop()

    # Apply the previous replacement map
    display, updated_cache, palette_html = update_preview_with_replacements(
        cache,
        previous_map,
        loop_pos,
        add_loop,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        lang=lang,
    )

    return (
        display,
        updated_cache,
        palette_html,
        previous_map,
        new_history,
        I18n.get("palette_undone", lang),
    )


def run_extraction_wrapper(
    img,
    points,
    offset_x,
    offset_y,
    zoom,
    barrel,
    wb,
    bright,
    color_mode,
    page_choice,
    lang: str = "zh",
):
    """Wrapper for extraction: supports 8-Color page saving."""
    from core.extractor import run_extraction

    run_mode = ColorMode(color_mode)

    vis, prev, lut_path, status = run_extraction(
        img, points, offset_x, offset_y, zoom, barrel, wb, bright, run_mode
    )

    if run_mode == ColorMode.EIGHT_COLOR_MAX and lut_path:
        os.makedirs("assets", exist_ok=True)
        page_idx = 1 if "1" in str(page_choice) else 2
        temp_path = os.path.join("assets", f"temp_8c_page_{page_idx}.npy")
        try:
            lut = np.load(lut_path)
            np.save(temp_path, lut)
            lut_path = temp_path
        except Exception:
            pass

    return vis, prev, lut_path, resolve_i18n_text(status, lang)


def merge_8color_data(lang: str = "zh"):
    """Concatenate two 8-color pages and save to LUT_FILE_PATH."""
    path1 = os.path.join("assets", "temp_8c_page_1.npy")
    path2 = os.path.join("assets", "temp_8c_page_2.npy")

    if not os.path.exists(path1) or not os.path.exists(path2):
        return None, I18n.get("ext_merge_missing_pages", lang)

    try:
        lut1 = np.load(path1)
        lut2 = np.load(path2)
        merged = np.concatenate([lut1, lut2], axis=0)
        np.save(LUT_FILE_PATH, merged)
        return LUT_FILE_PATH, I18n.get("ext_merge_success", lang)
    except Exception as e:
        return None, I18n.get("ext_merge_failed", lang).format(error=e)
