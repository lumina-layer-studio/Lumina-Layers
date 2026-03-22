"""
S01 — Input validation, LUT path resolution, and color system configuration.
S01 — 输入验证、LUT 路径解析与颜色系统配置。

从 convert_image_to_3d 函数开头搬入的逻辑，包括：
- 输入参数校验（image_path, lut_path）
- LUT 路径解析（支持字符串路径和 Gradio File 对象）
- 颜色系统配置（ColorSystem.get）
- SVG 矢量模式检测（is_svg_vector 标志）
- backing_color_id 校验
- separate_backing 处理
"""

from config import ColorSystem, ModelingMode


def run(ctx: dict) -> dict:
    """Validate inputs, resolve LUT path, configure color system, detect SVG vector mode.
    验证输入参数，解析 LUT 路径，配置颜色系统，检测 SVG 矢量模式。

    PipelineContext 输入键 / Input keys:
        - image_path (str): 输入图像路径
        - lut_path (str | object): LUT 文件路径或 Gradio File 对象
        - color_mode (str): 颜色模式字符串
        - modeling_mode (ModelingMode): 建模模式枚举
        - backing_color_id (int): 底板材料 ID
        - separate_backing (bool): 是否分离底板

    PipelineContext 输出键 / Output keys:
        - actual_lut_path (str): 解析后的实际 LUT 文件路径
        - color_conf (dict): 颜色系统配置
        - slot_names (list): 材料槽名称列表
        - preview_colors (dict): 预览颜色映射
        - is_svg_vector (bool): 是否为 SVG 矢量模式
        - backing_color_id (int): 校验/更新后的底板材料 ID
        - separate_backing (bool): 校验后的底板分离标志

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- 读取必需输入 ----
    image_path = ctx["image_path"]
    lut_path = ctx["lut_path"]
    color_mode = ctx["color_mode"]
    modeling_mode = ctx["modeling_mode"]

    # ---- 输入校验 ----
    if image_path is None:
        ctx["error"] = "[ERROR] Please upload an image"
        return ctx
    if lut_path is None:
        ctx["error"] = "[WARNING] Please select or upload a .npy calibration file!"
        return ctx

    # ---- LUT 路径解析 ----
    if isinstance(lut_path, str):
        actual_lut_path = lut_path
    elif hasattr(lut_path, "name"):
        actual_lut_path = lut_path.name
    else:
        ctx["error"] = "[ERROR] Invalid LUT file format"
        return ctx

    ctx["actual_lut_path"] = actual_lut_path

    # ---- separate_backing 处理 ----
    separate_backing = ctx.get("separate_backing", False)
    try:
        separate_backing = bool(separate_backing) if separate_backing is not None else False
    except Exception as e:
        print(f"[S01] Error reading separate_backing checkbox state: {e}, using default (False)")
        separate_backing = False

    backing_color_id = ctx.get("backing_color_id", 0)
    if separate_backing:
        backing_color_id = -2
        print(f"[S01] Backing separation enabled: backing will be a separate object (white)")
    else:
        print(
            f"[S01] Backing separation disabled: backing merged with first layer (backing_color_id={backing_color_id})"
        )

    ctx["separate_backing"] = separate_backing
    ctx["backing_color_id"] = backing_color_id

    # ---- SVG 矢量模式检测 ----
    is_svg_vector = (
        modeling_mode == ModelingMode.VECTOR and isinstance(image_path, str) and image_path.lower().endswith(".svg")
    )
    ctx["is_svg_vector"] = is_svg_vector

    # 矢量模式但非 SVG 文件 → 提前报错
    if modeling_mode == ModelingMode.VECTOR and not is_svg_vector:
        if isinstance(image_path, str) and not image_path.lower().endswith(".svg"):
            ctx["error"] = (
                "⚠️ Vector Native mode requires SVG files!\n\n"
                "Your file is not an SVG. Please either:\n"
                "• Upload an SVG file, or\n"
                "• Switch to 'High-Fidelity' or 'Pixel Art' mode"
            )
            return ctx

    print(f"[S01] Starting conversion...")
    print(f"[S01] Mode: {modeling_mode.get_display_name()}, Quantize: {ctx.get('quantize_colors', 32)}")
    print(f"[S01] Filters: blur_kernel={ctx.get('blur_kernel', 0)}, smooth_sigma={ctx.get('smooth_sigma', 10)}")
    print(f"[S01] LUT: {actual_lut_path}")

    # ---- 颜色系统配置 ----
    color_conf = ColorSystem.get(color_mode)

    # For Merged LUTs, extract slot_names and preview_colors from LUT palette
    # Use material names as keys (not indices) for direct lookup
    if color_mode == "Merged" and actual_lut_path.endswith(".json"):
        try:
            import json

            with open(actual_lut_path, "r", encoding="utf-8") as f:
                lut_data = json.load(f)
            if "palette" in lut_data:
                # Sort palette keys alphabetically to match recipe material IDs
                slot_names = sorted(lut_data["palette"].keys())
                print(f"[S01] Merged LUT: Using palette order: {slot_names}")

                # Build preview_colors dict with material names as keys
                preview_colors = {}
                for name in slot_names:
                    hex_color = lut_data["palette"][name].get("hex_color", "#FFFFFF")
                    # Convert hex to RGBA
                    r = int(hex_color[1:3], 16)
                    g = int(hex_color[3:5], 16)
                    b = int(hex_color[5:7], 16)
                    preview_colors[name] = [r, g, b, 255]
                    print(f"[S01] Material '{name}' -> RGB{[r,g,b]} ({hex_color})")
            else:
                slot_names = color_conf["slots"]
                preview_colors = color_conf["preview"]
        except Exception as e:
            print(f"[S01] Warning: Failed to extract palette from Merged LUT: {e}")
            slot_names = color_conf["slots"]
            preview_colors = color_conf["preview"]
    else:
        slot_names = color_conf["slots"]
        preview_colors = color_conf["preview"]

    ctx["color_conf"] = color_conf
    ctx["slot_names"] = slot_names
    ctx["preview_colors"] = preview_colors

    print(f"[S01] Final slot_names: {slot_names}")
    print(f"[S01] Final preview_colors keys: {list(preview_colors.keys())}")

    # ---- backing_color_id 范围校验 ----
    num_materials = len(slot_names)
    if backing_color_id != -2 and (backing_color_id < 0 or backing_color_id >= num_materials):
        print(f"[S01] Warning: Invalid backing_color_id={backing_color_id}, using default (0)")
        ctx["backing_color_id"] = 0

    return ctx
