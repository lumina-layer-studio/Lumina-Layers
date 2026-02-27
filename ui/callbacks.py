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


# ═══════════════════════════════════════════════════════════════
# LUT Management Callbacks
# ═══════════════════════════════════════════════════════════════

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
        return lut_path, f"✅ Selected: {display_name}"
    else:
        return None, f"❌ File not found: {display_name}"


def on_lut_upload_save(uploaded_file):
    """
    Save uploaded LUT file (.npy or .zip bundle) with auto-extraction.

    Supports:
    - .npy: Single LUT file (legacy behavior)
    - .zip: Bundle containing .npy + optional _stacks.npy + optional _meta.json

    Args:
        uploaded_file: Gradio 上传的文件对象

    Returns:
        tuple: (new_dropdown, status_message)
    """
    import zipfile as _zipfile
    import tempfile

    if uploaded_file is None:
        return gr.Dropdown(choices=LUTManager.get_lut_choices()), "❌ No file selected"

    file_path = uploaded_file.name if hasattr(uploaded_file, 'name') else str(uploaded_file)

    # ZIP 文件：自动解包
    if file_path.lower().endswith('.zip'):
        try:
            with _zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()
                # 找到主 LUT .npy 文件（不含 _stacks）
                lut_files = [n for n in names if n.endswith('.npy') and '_stacks' not in n]
                if not lut_files:
                    return gr.Dropdown(choices=LUTManager.get_lut_choices()), "❌ ZIP 中未找到 .npy LUT 文件"

                lut_name = lut_files[0]
                base_stem = lut_name.rsplit('.', 1)[0]  # e.g. "AAAAAAAA_KS"

                # 解压到临时目录
                tmp_dir = tempfile.mkdtemp()
                zf.extractall(tmp_dir)

                # 构建文件路径
                import os
                lut_tmp = os.path.join(tmp_dir, lut_name)

                stacks_name = base_stem + "_stacks.npy"
                stacks_tmp = os.path.join(tmp_dir, stacks_name) if stacks_name in names else None

                meta_name = base_stem + "_meta.json"
                meta_tmp = os.path.join(tmp_dir, meta_name) if meta_name in names else None

                # 创建临时文件对象模拟 Gradio 上传
                class _TmpFile:
                    def __init__(self, path):
                        self.name = path

                stacks_file = _TmpFile(stacks_tmp) if stacks_tmp and os.path.exists(stacks_tmp) else None
                meta_file = _TmpFile(meta_tmp) if meta_tmp and os.path.exists(meta_tmp) else None

                success, message, new_choices, saved_name = LUTManager.save_uploaded_lut(
                    _TmpFile(lut_tmp), stacks_file=stacks_file, meta_file=meta_file, custom_name=None
                )

                # 清理临时目录
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

                return gr.Dropdown(choices=new_choices, value=saved_name), message

        except _zipfile.BadZipFile:
            return gr.Dropdown(choices=LUTManager.get_lut_choices()), "❌ 无效的 ZIP 文件"
        except Exception as e:
            return gr.Dropdown(choices=LUTManager.get_lut_choices()), f"❌ ZIP 解包失败: {e}"

    # 普通 .npy 文件：直接保存
    success, message, new_choices, saved_name = LUTManager.save_uploaded_lut(
        uploaded_file, custom_name=None
    )
    return gr.Dropdown(choices=new_choices, value=saved_name), message



def on_stacks_only_upload(stacks_file):
    """
    当用户仅上传 stacks 文件（未上传 LUT）时返回提示信息
    
    Args:
        stacks_file: Gradio 上传的 stacks 文件对象
    
    Returns:
        str: 提示用户先上传 LUT 文件的状态消息
    """
    return "⚠️ 请先上传 LUT 文件，再上传 Stacks 文件"


# ═══════════════════════════════════════════════════════════════
# Extractor Callbacks
# ═══════════════════════════════════════════════════════════════

def get_first_hint(mode):
    """Get first corner point hint based on mode"""
    if mode == "K/S Parameter":
        return "#### 👉 步骤 1/2: 点击 A4纸/背景板 **左上角 / Top-Left**"
    
    conf = ColorSystem.get(mode)
    label_zh = conf['corner_labels'][0]
    label_en = conf.get('corner_labels_en', conf['corner_labels'])[0]
    return f"#### 👉 点击 Click: **{label_zh} / {label_en}**"


def get_next_hint(mode, pts_count):
    """Get next corner point hint based on mode"""
    if mode == "K/S Parameter":
        # K/S mode needs 8 points total (4 for A4, 4 for chip)
        if pts_count < 4:
            labels = ["左上角 / Top-Left", "右上角 / Top-Right", "右下角 / Bottom-Right", "左下角 / Bottom-Left"]
            return f"#### 👉 步骤 1/2 (A4纸/背景板): 点击 **{labels[pts_count]}**"
        elif pts_count == 4:
            return "#### ✅ A4纸/背景板定位完成！图像已自动校正\n#### 👉 步骤 2/2: 在校正后的图像上点击阶梯卡 **左上角 / Top-Left**\n⚠️ 确保上方是厚端(5层)，下方是薄端(1层)"
        elif pts_count < 8:
            labels = ["左上角 / Top-Left", "右上角 / Top-Right", "右下角 / Bottom-Right", "左下角 / Bottom-Left"]
            chip_idx = pts_count - 4
            return f"#### 👉 步骤 2/2 (阶梯卡): 点击 **{labels[chip_idx]}**"
        else:
            return "#### ✅ 定位完成！可以开始提取 K/S 参数！"
    
    # Standard modes
    conf = ColorSystem.get(mode)
    if pts_count >= 4:
        return "#### ✅ Positioning complete! Ready to extract!"
    label_zh = conf['corner_labels'][pts_count]
    label_en = conf.get('corner_labels_en', conf['corner_labels'])[pts_count]
    return f"#### 👉 点击 Click: **{label_zh} / {label_en}**"


def on_extractor_upload(i, mode):
    """Handle image upload"""
    hint = get_first_hint(mode)
    print(f"[K/S DEBUG] on_extractor_upload: type={type(i).__name__}, {'shape='+str(i.shape)+' dtype='+str(i.dtype) if hasattr(i, 'shape') else 'value='+str(i)[:80]}")
    if hasattr(i, 'shape') and len(i.shape) == 3:
        print(f"[K/S DEBUG] upload pixel[0,0]: {i[0,0]}")
    # Return: state_img, original_img, pts, curr_coord, hint
    return i, i, [], None, hint


def on_extractor_mode_change(img, mode):
    """Handle color mode change"""
    hint = get_first_hint(mode)
    return [], hint, img


def on_extractor_rotate(i, mode):
    """Rotate image"""
    from core.extractor import rotate_image
    if i is None:
        return None, None, [], get_first_hint(mode)
    r = rotate_image(i, "Rotate Left 90°")
    return r, r, [], get_first_hint(mode)


def on_extractor_click(img, original_img, pts, mode, evt: gr.SelectData):
    """Set corner point by clicking image
    
    Returns:
        tuple: (state_img, original_img, work_img, pts, hint)
            - state_img: The base image for next click (updated when switching to corrected A4)
            - original_img: Always keeps the original uploaded image (for K/S extraction)
            - work_img: The display image with markers
            - pts: Updated points list
            - hint: Hint text for next step
    """
    from core.extractor import draw_corner_points
    
    # Debug: log input types and shapes
    print(f"[K/S DEBUG] on_extractor_click called")
    print(f"[K/S DEBUG] img type={type(img).__name__}, {'shape='+str(img.shape)+' dtype='+str(img.dtype) if hasattr(img, 'shape') else 'value='+str(img)[:80]}")
    print(f"[K/S DEBUG] original_img type={type(original_img).__name__}, {'shape='+str(original_img.shape)+' dtype='+str(original_img.dtype) if hasattr(original_img, 'shape') else 'value='+str(original_img)[:80]}")
    print(f"[K/S DEBUG] mode={mode}, pts count={len(pts)}")
    
    # K/S mode needs 8 points, standard modes need 4
    max_points = 8 if mode == "K/S Parameter" else 4
    
    if len(pts) >= max_points:
        return img, original_img, img, pts, get_next_hint(mode, len(pts))
    
    n = pts + [[evt.index[0], evt.index[1]]]
    print(f"[K/S DEBUG] New point: [{evt.index[0]}, {evt.index[1]}], total points: {len(n)}")
    
    # For K/S mode, handle two-step process
    if mode == "K/S Parameter":
        if len(n) <= 4:
            # Step 1: Selecting A4 corners on original image
            vis = draw_ks_corner_points(img, n, mode='a4')
            hint = get_next_hint(mode, len(n))
            
            # If we just completed A4 selection (4 points), show corrected A4 image
            if len(n) == 4:
                try:
                    import cv2
                    import numpy as np
                    from core.ks_engine.calibration_ks import apply_perspective_transform, auto_white_balance_by_paper
                    
                    # Gradio Image (type="numpy") provides RGB, OpenCV needs BGR
                    if isinstance(original_img, str):
                        img_raw = cv2.imread(original_img)
                        print(f"[K/S DEBUG] Loaded original from path: {original_img}")
                    else:
                        img_raw = cv2.cvtColor(original_img, cv2.COLOR_RGB2BGR)
                        print(f"[K/S DEBUG] Converted original RGB->BGR, shape={img_raw.shape}")
                    
                    print(f"[K/S DEBUG] img_raw pixel[0,0] BGR: {img_raw[0,0]}")
                    
                    # Apply perspective transform to A4
                    a4_pts = np.float32(n)
                    print(f"[K/S DEBUG] A4 corners: {a4_pts.tolist()}")
                    img_a4 = apply_perspective_transform(img_raw, a4_pts, 1414, 1000)
                    print(f"[K/S DEBUG] img_a4 shape={img_a4.shape}, pixel[0,0] BGR: {img_a4[0,0]}")
                    
                    # Apply white balance
                    img_calibrated = auto_white_balance_by_paper(img_a4, enable_wb=True)
                    print(f"[K/S DEBUG] img_calibrated shape={img_calibrated.shape}, pixel[0,0] BGR: {img_calibrated[0,0]}")
                    
                    # Save corrected A4 image for chip selection (BGR format for file)
                    import os
                    temp_dir = "output/ks_engine/debug"
                    os.makedirs(temp_dir, exist_ok=True)
                    a4_corrected_path = os.path.join(temp_dir, "a4_corrected_for_selection.jpg")
                    cv2.imwrite(a4_corrected_path, img_calibrated)
                    
                    # Convert BGR -> RGB for Gradio display
                    img_calibrated_rgb = cv2.cvtColor(img_calibrated, cv2.COLOR_BGR2RGB)
                    
                    print(f"[K/S DEBUG] A4 corrected saved to: {a4_corrected_path}")
                    print(f"[K/S DEBUG] Returning RGB numpy array for state_img and work_img")
                    print(f"[K/S DEBUG] img_calibrated_rgb pixel[0,0] RGB: {img_calibrated_rgb[0,0]}")
                    
                    # Return RGB numpy array for Gradio, keep original_img unchanged
                    return img_calibrated_rgb, original_img, img_calibrated_rgb, n, hint
                except Exception as e:
                    print(f"Error generating A4 corrected image: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Return: state unchanged, original unchanged, work with markers
            print(f"[K/S DEBUG] Returning vis type={type(vis).__name__}")
            return img, original_img, vis, n, hint
        else:
            # Step 2: Selecting chip corners on corrected A4 image
            print(f"[K/S DEBUG] Step 2: chip selection, img type={type(img).__name__}")
            vis = draw_ks_corner_points(img, n[4:], mode='chip')
            hint = get_next_hint(mode, len(n))
            return img, original_img, vis, n, hint
    else:
        # Standard modes
        vis = draw_corner_points(img, n, mode)
        hint = get_next_hint(mode, len(n))
        return img, original_img, vis, n, hint


def draw_ks_corner_points(img_path, pts, mode='a4'):
    """Draw corner points for K/S mode
    
    Args:
        img_path: Image path or array
        pts: List of points to draw
        mode: 'a4' for A4 paper points (green), 'chip' for chip points (red)
    """
    import cv2
    import numpy as np
    
    print(f"[K/S DEBUG] draw_ks_corner_points: input type={type(img_path).__name__}, mode={mode}")
    if isinstance(img_path, str):
        img = cv2.imread(img_path)
        if img is not None:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)  # Convert to RGB for Gradio
    else:
        img = img_path.copy()  # Already RGB from Gradio
    if img is None:
        print(f"[K/S DEBUG] draw_ks_corner_points: img is None!")
        return img_path
    
    print(f"[K/S DEBUG] draw_ks_corner_points: img shape={img.shape}, dtype={img.dtype}, pixel[0,0]={img[0,0]}")
    
    if mode == 'a4':
        # Drawing A4 points (green, large markers) - RGB colors for Gradio
        color = (0, 255, 0)
        marker_size = 30
        circle_size = 15
        font_scale = 1.2
    else:  # mode == 'chip'
        # Drawing chip points (red, smaller markers) - RGB colors for Gradio
        color = (255, 0, 0)
        marker_size = 20
        circle_size = 10
        font_scale = 0.8
    
    for i, (x, y) in enumerate(pts):
        # Draw cross marker
        cv2.drawMarker(img, (x, y), color, cv2.MARKER_CROSS, marker_size, 3)
        # Draw circle
        cv2.circle(img, (x, y), circle_size, color, 3)
        # Draw label
        label = str(i + 1)
        cv2.putText(
            img, label,
            (x + 20, y - 10),
            cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 3
        )
    
    # Draw polylines if we have 4 points
    if len(pts) == 4:
        pts_array = np.array(pts, dtype=np.int32)
        cv2.polylines(img, [pts_array], True, color, 3)
    
    return img


def on_extractor_clear(img, mode):
    """Clear corner points"""
    hint = get_first_hint(mode)
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
    return None, I18n.get('palette_click_to_select', lang)


def on_apply_color_replacement(cache, selected_color, replacement_color,
                               replacement_map, replacement_history, loop_pos, add_loop,
                               loop_width, loop_length, loop_hole, loop_angle,
                               lang: str = "zh"):
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
    from core.converter import update_preview_with_replacements
    from ui.palette_extension import generate_palette_html
    
    if cache is None:
        return None, None, "", replacement_map, replacement_history, I18n.get('palette_need_preview', lang)
    
    if not selected_color:
        return gr.update(), cache, gr.update(), replacement_map, replacement_history, I18n.get('palette_need_original', lang)

    if not replacement_color:
        return gr.update(), cache, gr.update(), replacement_map, replacement_history, I18n.get('palette_need_replacement', lang)
    
    # Save current state to history before applying new replacement
    new_history = replacement_history.copy() if replacement_history else []
    new_history.append(replacement_map.copy() if replacement_map else {})
    
    # Update replacement map
    new_map = replacement_map.copy() if replacement_map else {}
    new_map[selected_color] = replacement_color
    
    # Apply replacements and update preview
    display, updated_cache, palette_html = update_preview_with_replacements(
        cache, new_map, loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle,
        lang=lang
    )
    
    status_msg = I18n.get('palette_replaced', lang).format(src=selected_color, dst=replacement_color)
    return display, updated_cache, palette_html, new_map, new_history, status_msg


def on_clear_color_replacements(cache, replacement_map, replacement_history,
                                loop_pos, add_loop,
                                loop_width, loop_length, loop_hole, loop_angle,
                                lang: str = "zh"):
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
    from core.converter import update_preview_with_replacements
    from ui.palette_extension import generate_palette_html
    
    if cache is None:
        return None, None, "", {}, [], I18n.get('palette_need_preview', lang)
    
    # Save current state to history before clearing
    new_history = replacement_history.copy() if replacement_history else []
    if replacement_map:
        new_history.append(replacement_map.copy())
    
    # Clear replacements by passing empty dict
    display, updated_cache, palette_html = update_preview_with_replacements(
        cache, {}, loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle,
        lang=lang
    )
    
    return display, updated_cache, palette_html, {}, new_history, I18n.get('palette_cleared', lang)


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
    palette_html = generate_palette_html(palette, {}, None, lang=lang)
    
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
    
    return hex_color, f"✅ {hex_color}"


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
    
    return selected_value, f"✅ {selected_value}"


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

def on_undo_color_replacement(cache, replacement_map, replacement_history,
                               loop_pos, add_loop, loop_width, loop_length,
                               loop_hole, loop_angle, lang: str = "zh"):
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
    from core.converter import update_preview_with_replacements
    from ui.palette_extension import generate_palette_html
    
    if cache is None:
        return None, None, "", replacement_map, replacement_history, I18n.get('palette_need_preview', lang)
    
    if not replacement_history:
        return None, cache, "", replacement_map, replacement_history, I18n.get('palette_undo_empty', lang)
    
    # Pop the last state from history
    new_history = replacement_history.copy()
    previous_map = new_history.pop()
    
    # Apply the previous replacement map
    display, updated_cache, palette_html = update_preview_with_replacements(
        cache, previous_map, loop_pos, add_loop,
        loop_width, loop_length, loop_hole, loop_angle,
        lang=lang
    )
    
    return display, updated_cache, palette_html, previous_map, new_history, I18n.get('palette_undone', lang)

def run_extraction_wrapper(img, points, offset_x, offset_y, zoom, barrel, wb, bright, color_mode, page_choice):
    """Wrapper for extraction: supports 8-Color page saving."""
    from core.extractor import run_extraction
    
    run_mode = color_mode
    
    vis, prev, lut_path, status = run_extraction(
        img, points, offset_x, offset_y, zoom, barrel, wb, bright, run_mode
    )
    
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
        return None, "❌ Missing temp pages. Please extract Page 1 and Page 2 first."
    
    try:
        lut1 = np.load(path1)
        lut2 = np.load(path2)
        print(f"[MERGE_8COLOR] Page 1 shape: {lut1.shape}")
        print(f"[MERGE_8COLOR] Page 2 shape: {lut2.shape}")
        
        merged = np.concatenate([lut1, lut2], axis=0)
        print(f"[MERGE_8COLOR] Merged shape: {merged.shape}")
        
        np.save(LUT_FILE_PATH, merged)
        print(f"[MERGE_8COLOR] Saved merged LUT to: {LUT_FILE_PATH}")
        
        return LUT_FILE_PATH, "✅ 8-Color LUT merged and saved!"
    except Exception as e:
        print(f"[MERGE_8COLOR] Error: {e}")
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
        return f"**{I18n.get('merge_mode_label', lang)}**: ❌ File not found"

    try:
        mode, count = LUTMerger.detect_color_mode(lut_path)
        return f"**{I18n.get('merge_mode_label', lang)}**: {mode} ({count} colors)"
    except Exception as e:
        return f"**{I18n.get('merge_mode_label', lang)}**: ❌ {e}"


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
