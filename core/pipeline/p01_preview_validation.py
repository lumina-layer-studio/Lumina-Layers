"""
P01 — Preview input validation and parameter normalization.
P01 — 预览输入验证与参数规范化。

从 generate_preview_cached 函数开头搬入的逻辑，包括：
- 输入参数校验（image_path, lut_path）
- LUT 路径解析（支持字符串路径和 Gradio File 对象）
- modeling_mode 规范化（None -> HIGH_FIDELITY）
- quantize_colors 范围 clamp（8-256）
- Merged LUT palette 提取和 preview_colors 构建
"""

from config import ModelingMode, ColorSystem


def run(ctx: dict) -> dict:
    """Validate preview inputs and normalize parameters.
    验证预览输入参数并规范化。

    PipelineContext 输入键 / Input keys:
        - image_path (str): 输入图像路径
        - lut_path (str | object): LUT 文件路径或 Gradio File 对象
        - modeling_mode (ModelingMode | str | None): 建模模式
        - quantize_colors (int): K-Means 量化颜色数
        - color_mode (str): 颜色模式字符串

    PipelineContext 输出键 / Output keys:
        - actual_lut_path (str): 解析后的实际 LUT 文件路径
        - modeling_mode (ModelingMode): 规范化后的建模模式
        - quantize_colors (int): clamp 到 [8, 256] 范围后的量化颜色数
        - preview_colors (dict): 材料ID到RGBA颜色的映射
        - slot_names (list): 材料槽位名称列表

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- 读取必需输入 ----
    image_path = ctx['image_path']
    lut_path = ctx['lut_path']
    modeling_mode = ctx.get('modeling_mode')
    quantize_colors = ctx.get('quantize_colors', 64)
    color_mode = ctx.get('color_mode', '4-Color')

    # ---- 输入校验 ----
    if image_path is None:
        ctx['error'] = "[ERROR] Please upload an image"
        return ctx
    if lut_path is None:
        ctx['error'] = "[WARNING] Please select or upload calibration file"
        return ctx

    # ---- LUT 路径解析 ----
    if isinstance(lut_path, str):
        actual_lut_path = lut_path
    elif hasattr(lut_path, 'name'):
        actual_lut_path = lut_path.name
    else:
        ctx['error'] = "[ERROR] Invalid LUT file format"
        return ctx

    # ---- modeling_mode 规范化 ----
    if modeling_mode is None or modeling_mode == "none":
        modeling_mode = ModelingMode.HIGH_FIDELITY
        print("[CONVERTER] Warning: modeling_mode was None, using default HIGH_FIDELITY")
    else:
        modeling_mode = ModelingMode(modeling_mode)

    # ---- quantize_colors clamp ----
    quantize_colors = max(8, min(256, quantize_colors))

    # ---- 颜色系统配置 ----
    color_conf = ColorSystem.get(color_mode)
    
    # For Merged LUTs, extract slot_names and preview_colors from LUT palette
    # Use material names as keys (not indices) for direct lookup
    preview_colors = None
    slot_names = None
    
    if color_mode == "Merged" and actual_lut_path.endswith('.json'):
        try:
            import json
            with open(actual_lut_path, 'r', encoding='utf-8') as f:
                lut_data = json.load(f)
            if 'palette' in lut_data:
                # Sort palette keys alphabetically to match recipe material IDs
                slot_names = sorted(lut_data['palette'].keys())
                print(f"[P01] Merged LUT: Using palette order: {slot_names}")
                
                # Build preview_colors dict with material names as keys
                preview_colors = {}
                for name in slot_names:
                    hex_color = lut_data['palette'][name].get('hex_color', '#FFFFFF')
                    # Convert hex to RGBA
                    r = int(hex_color[1:3], 16)
                    g = int(hex_color[3:5], 16)
                    b = int(hex_color[5:7], 16)
                    preview_colors[name] = [r, g, b, 255]
                    print(f"[P01] Material '{name}' -> RGB{[r,g,b]} ({hex_color})")
            else:
                print(f"[P01] Warning: Merged LUT has no palette, using default color_conf")
        except Exception as e:
            print(f"[P01] Warning: Failed to extract palette from Merged LUT: {e}")
    
    # ---- 写入输出 ----
    ctx['actual_lut_path'] = actual_lut_path
    ctx['modeling_mode'] = modeling_mode
    ctx['quantize_colors'] = quantize_colors
    ctx['preview_colors'] = preview_colors
    ctx['slot_names'] = slot_names
    
    return ctx
