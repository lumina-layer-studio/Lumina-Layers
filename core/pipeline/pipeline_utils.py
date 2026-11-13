"""
core.pipeline.pipeline_utils — 管道共享工具函数
Pipeline shared utility functions.

从 converter.py 原封不动搬入的工具函数集合，包括：
- 颜色工具函数（RGB/Hex 转换、亮度计算、调色板提取、自动高度图生成）
- LUT 工具函数（颜色提取、下拉菜单生成、颜色模式检测）
- 检测工具函数（图像类型检测）
- 缓存辅助函数（量化图像缓存回填）
- LUT HTML 网格生成函数
"""

from api.structured_logging import get_logger
import os
import math
import numpy as np
from typing import Any, List, Dict, Tuple, Optional

from config import PrinterConfig, ColorSystem, ModelingMode

log = get_logger(__name__)

# ========== 颜色工具函数 (Color Utility Functions) ==========


def _rgb_to_hex(rgb):
    """将 RGB 三元组转换为 #RRGGBB。
    Convert RGB tuple to #RRGGBB hex string.

    Args:
        rgb: (R, G, B) 三元组，每个值 0-255

    Returns:
        str: '#rrggbb' 格式的十六进制颜色字符串
    """
    r, g, b = [int(x) for x in rgb]
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_to_rgb_tuple(hex_color):
    """将 #RRGGBB 转换为 (R, G, B)。
    Convert #RRGGBB hex string to (R, G, B) tuple.

    Args:
        hex_color (str): '#rrggbb' 格式的十六进制颜色字符串

    Returns:
        tuple: (R, G, B) 三元组，每个值 0-255

    Raises:
        ValueError: 如果输入不是有效的 hex 颜色字符串
    """
    if not isinstance(hex_color, str):
        raise ValueError("hex_color must be a string")

    h = hex_color.strip().lower()
    if h.startswith("#"):
        h = h[1:]
    if len(h) != 6:
        raise ValueError(f"invalid hex color: {hex_color}")

    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def calculate_luminance(hex_color):
    """
    Calculate relative luminance of a color using standard formula.
    使用标准公式计算颜色的相对亮度。

    Formula: Y = 0.299*R + 0.587*G + 0.114*B

    Args:
        hex_color: Color in hex format (e.g., '#ff0000')

    Returns:
        float: Luminance value (0-255)
    """
    # Remove '#' if present
    hex_color = hex_color.lstrip("#")

    # Convert hex to RGB
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # Calculate luminance using standard formula
    luminance = 0.299 * r + 0.587 * g + 0.114 * b

    return luminance


def extract_color_palette(preview_cache: dict) -> List[dict]:
    """
    Extract unique colors from preview cache.
    从预览缓存中提取唯一颜色调色板。

    Args:
        preview_cache: Cache data from generate_preview_cached containing:
            - matched_rgb: (H, W, 3) uint8 array of matched colors
            - mask_solid: (H, W) bool array indicating solid pixels

    Returns:
        List of dicts sorted by pixel count (descending), each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string
        - 'count': pixel count
        - 'percentage': percentage of total solid pixels (0.0-100.0)
    """
    if preview_cache is None:
        return []

    matched_rgb = preview_cache.get("matched_rgb")
    mask_solid = preview_cache.get("mask_solid")

    if matched_rgb is None or mask_solid is None:
        return []

    from core.pipeline.processing_ops.color_histogram import count_visible_rgb

    unique_colors, counts = count_visible_rgb(
        np.asarray(matched_rgb[..., :3], dtype=np.uint8), mask_solid
    )
    total_solid = int(counts.sum())
    if total_solid == 0:
        return []

    # Build palette entries
    palette = []
    order = np.argsort(-counts, kind="stable")
    for idx in order:
        count = int(counts[idx])
        r, g, b = (int(channel) for channel in unique_colors[idx])
        palette.append(
            {
                "color": (r, g, b),
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "count": count,
                "percentage": round(count / total_solid * 100, 2),
            }
        )

    return palette


def generate_auto_height_map(color_list, mode, base_thickness, max_relief_height):
    """
    Generate automatic height mapping based on color luminance using Min-Max normalization.
    基于颜色亮度使用 Min-Max 归一化生成自动高度映射。

    This function calculates the luminance of each color and assigns heights
    using normalization, ensuring all heights fall within [base_thickness, max_relief_height].
    This prevents height explosion when dealing with many colors.

    Algorithm:
    1. Calculate luminance Y = 0.299*R + 0.587*G + 0.114*B for each color
    2. Find Y_min and Y_max across all colors
    3. Calculate available height range: Delta_Z = max_relief_height - base_thickness
    4. For each color, calculate normalized ratio:
       - If "浅色凸起": Ratio = (Y - Y_min) / (Y_max - Y_min)
       - If "深色凸起": Ratio = 1.0 - (Y - Y_min) / (Y_max - Y_min)
    5. Final height = base_thickness + Ratio * Delta_Z
    6. Round to 0.1mm precision

    Args:
        color_list: List of hex color strings (e.g., ['#ff0000', '#00ff00'])
        mode: Sorting mode - "深色凸起" (darker higher) or "浅色凸起" (lighter higher)
        base_thickness: Base thickness in mm (minimum height)
        max_relief_height: Maximum relief height in mm (maximum height)

    Returns:
        dict: Color-to-height mapping {hex_color: height_mm}

    Example:
        >>> colors = ['#ff0000', '#00ff00', '#0000ff']
        >>> generate_auto_height_map(colors, "深色凸起", 1.2, 5.0)
        {'#00ff00': 1.2, '#ff0000': 3.1, '#0000ff': 5.0}
    """
    if not color_list:
        return {}

    # Step 1: Calculate luminance for each color
    color_luminance = []
    for color in color_list:
        luminance = calculate_luminance(color)
        color_luminance.append((color, luminance))

    # Step 2: Find min and max luminance
    luminances = [lum for _, lum in color_luminance]
    y_min = min(luminances)
    y_max = max(luminances)

    # Handle edge case: all colors have same luminance
    if y_max == y_min:
        # All colors get the same height (average of base and max)
        avg_height = (base_thickness + max_relief_height) / 2.0
        color_height_map = {color: round(avg_height, 1) for color, _ in color_luminance}
        log.info(
            "Auto height map used average height",
            extra={
                "event": "auto_height_map_average_used",
                "color_count": len(color_list),
                "average_height_mm": round(avg_height, 3),
            },
        )
        return color_height_map

    # Step 3: Calculate available height range
    delta_z = max_relief_height - base_thickness

    # Step 4 & 5: Calculate normalized heights
    color_height_map = {}
    for color, luminance in color_luminance:
        # Normalize luminance to [0, 1]
        normalized = (luminance - y_min) / (y_max - y_min)

        # Apply mode: darker higher or lighter higher
        if "深色凸起" in mode or "Darker Higher" in mode:
            # Darker colors (lower luminance) should be higher
            # Invert the ratio: 0 -> 1, 1 -> 0
            ratio = 1.0 - normalized
        else:
            # Lighter colors (higher luminance) should be higher
            # Keep the ratio as is: 0 -> 0, 1 -> 1
            ratio = normalized

        # Calculate final height (minimum 0.08mm = 1 layer height)
        height = max(0.08, base_thickness + ratio * delta_z)

        # Round to 0.1mm precision
        color_height_map[color] = round(height, 1)

    log.info(
        "Auto height map generated",
        extra={
            "event": "auto_height_map_generated",
            "color_count": len(color_list),
            "mode": mode,
            "luminance_min": round(float(y_min), 3),
            "luminance_max": round(float(y_max), 3),
            "height_min_mm": round(float(min(color_height_map.values())), 3),
            "height_max_mm": round(float(max(color_height_map.values())), 3),
            "height_span_mm": round(float(max(color_height_map.values()) - min(color_height_map.values())), 3),
        },
    )

    return color_height_map


# ========== LUT 工具函数 (LUT Utility Functions) ==========

# Try to import LUTManager for metadata loading
try:
    from utils.lut_manager import LUTManager
except ImportError:
    LUTManager = None


def extract_lut_available_colors(lut_path: str) -> List[dict]:
    """
    Extract all available colors from a LUT file.
    从 LUT 文件中提取所有可用颜色。

    This function loads a LUT file (.npy/.npz/.json) and extracts all unique
    colors that the printer can produce. These colors can be used as
    replacement options in the color replacement feature.

    Uses LUTManager.load_lut_with_metadata() as the unified loading entry
    point to support all LUT formats consistently.

    Args:
        lut_path: Path to the LUT file (.npy/.npz/.json)

    Returns:
        List of dicts, each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string

        Returns empty list if LUT cannot be loaded.
    """
    if not lut_path:
        return []

    try:
        # 统一通过 LUTManager 加载，支持 .npy/.npz/.json 三种格式
        if LUTManager is not None:
            rgb, _stacks, _metadata = LUTManager.load_lut_with_metadata(lut_path)
            measured_colors = rgb.reshape(-1, 3)
        elif lut_path.endswith(".npz"):
            data = np.load(lut_path, allow_pickle=False)
            measured_colors = data["rgb"]
        else:
            lut_grid = np.load(lut_path)
            measured_colors = lut_grid.reshape(-1, 3)
        log.debug(
            "Loading LUT colors",
            extra={
                "event": "lut_colors_loading",
                "lut_path": lut_path,
                "color_count": int(len(measured_colors)),
            },
        )

        # Get unique colors
        unique_colors = np.unique(measured_colors, axis=0)

        # Build color list
        colors = []
        for color in unique_colors:
            r, g, b = int(color[0]), int(color[1]), int(color[2])
            colors.append({"color": (r, g, b), "hex": f"#{r:02x}{g:02x}{b:02x}"})

        # Sort by brightness (dark to light) for better UX
        colors.sort(key=lambda x: sum(x["color"]))

        measured_count = int(len(measured_colors))
        unique_count = int(len(unique_colors))
        extra: dict[str, Any] = {
            "event": "lut_colors_loaded",
            "lut_path": lut_path,
            "color_count": measured_count,
        }
        if unique_count != measured_count:
            extra["unique_count"] = unique_count
        log.info("LUT colors loaded", extra=extra)
        return colors

    except (OSError, ValueError, TypeError, KeyError) as e:
        log.warning(
            "Failed to extract LUT colors",
            extra={
                "event": "lut_colors_extraction_failed",
                "lut_path": lut_path,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        return []


def get_lut_color_choices(lut_path: str) -> List[tuple]:
    """
    Get LUT colors formatted for dropdown selection.
    获取格式化为下拉菜单的 LUT 颜色列表。

    Args:
        lut_path: Path to the LUT .npy file

    Returns:
        List of (display_label, hex_value) tuples for Dropdown choices.
        Display label includes a colored square emoji approximation.
    """
    colors = extract_lut_available_colors(lut_path)

    if not colors:
        return []

    choices = []
    for entry in colors:
        hex_color = entry["hex"]
        r, g, b = entry["color"]
        # Create a display label with RGB values
        label = f"■ {hex_color} (R:{r} G:{g} B:{b})"
        choices.append((label, hex_color))

    return choices


def _resolve_color_mode_from_size(
    total_colors: int,
    layer_count: int | None,
    max_mat: int | None,
    *,
    require_layer_count: bool = False,
) -> str | None:
    """将 (size, layers, max_material) 三元组解析为展示字符串。
    Resolve a (size, layers, max_material) triple into the canonical display
    string used by ``detect_lut_color_mode``. Returns ``None`` if the size
    falls outside every registered window.

    Structured LUTs must supply recipe layers for layer-specific modes;
    raw NPY arrays may infer the mode from their size alone.
    """
    from core.color_modes import ColorMode

    mode = ColorMode.from_lut_size_and_layers(int(total_colors), layer_count, max_mat)
    if mode is None or (
        require_layer_count
        and mode.requires_layer_count is not None
        and layer_count is None
    ):
        return None
    return mode.canonical_display_name


def detect_lut_color_mode(lut_path):
    """
    自动检测LUT文件的颜色模式。
    Auto-detect the color mode of a LUT file.

    Args:
        lut_path: LUT文件路径

    Returns:
        str: 颜色模式 ("BW (Black & White)", "Merged", "6-Color (CMYWGK 1296)", "8-Color Max", etc.)
             Returns None if detection fails.
    """
    if not lut_path or not os.path.exists(lut_path):
        return None

    try:
        if lut_path.endswith(".npz"):
            data = np.load(lut_path)
            if "rgb" in data:
                rgb = data["rgb"]
                total_colors = int(rgb.reshape(-1, 3).shape[0])
                stacks = data["stacks"] if "stacks" in data else None
                layer_count = int(stacks.shape[1]) if isinstance(stacks, np.ndarray) and stacks.ndim == 2 else None
                max_mat = int(np.max(stacks)) if isinstance(stacks, np.ndarray) and stacks.size > 0 else None
                resolved = _resolve_color_mode_from_size(
                    total_colors, layer_count, max_mat, require_layer_count=True,
                )
                if resolved is not None:
                    log.info(
                        "Detected LUT color mode",
                        extra={
                            "event": "lut_color_mode_detected",
                            "source": "npz",
                            "color_count": int(total_colors),
                            "color_mode": resolved,
                        },
                    )
                    return resolved
            log.info(
                "Detected merged LUT color mode",
                extra={"event": "lut_color_mode_detected", "source": "npz", "color_mode": "Merged"},
            )
            return "Merged"

        # .json (Keyed JSON) format
        if lut_path.endswith(".json"):
            from utils.lut_manager import LUTManager

            rgb, stacks, _meta = LUTManager.load_lut_with_metadata(lut_path)
            # 优先使用存储的 color_mode
            if _meta and _meta.color_mode:
                log.info(
                    "Using LUT color mode metadata",
                    extra={"event": "lut_color_mode_metadata_used", "source": "json", "color_mode": _meta.color_mode},
                )
                return _meta.color_mode
            # 回退到基于数量的推断
            total_colors = len(rgb) if rgb is not None else 0
            layer_count = int(stacks.shape[1]) if isinstance(stacks, np.ndarray) and stacks.ndim == 2 else None
            max_mat = int(np.max(stacks)) if isinstance(stacks, np.ndarray) and stacks.size > 0 else None
            log.debug(
                "JSON LUT mode inputs resolved",
                extra={
                    "event": "json_lut_mode_inputs_resolved",
                    "color_count": int(total_colors),
                    "layer_count": layer_count,
                    "max_material": max_mat,
                },
            )
            resolved = _resolve_color_mode_from_size(
                total_colors, layer_count, max_mat, require_layer_count=True,
            )
            if resolved is not None:
                log.info(
                    "Detected LUT color mode",
                    extra={
                        "event": "lut_color_mode_detected",
                        "source": "json",
                        "color_count": int(total_colors),
                        "color_mode": resolved,
                    },
                )
                return resolved
            log.info(
                "Detected merged LUT color mode",
                extra={"event": "lut_color_mode_detected", "source": "json", "color_count": int(total_colors), "color_mode": "Merged"},
            )
            return "Merged"

        # Standard .npy format
        lut_data = np.load(lut_path)

        # 确保是2D数组
        if lut_data.ndim == 1:
            # 如果是1D数组，假设是 (N*3,) 格式，重塑为 (N, 3)
            if len(lut_data) % 3 == 0:
                lut_data = lut_data.reshape(-1, 3)
            else:
                log.info(
                    "Invalid LUT shape for mode detection",
                    extra={"event": "lut_color_mode_detection_invalid_shape", "lut_path": lut_path},
                )
                return None

        # 计算颜色数量
        if lut_data.ndim == 2:
            total_colors = lut_data.shape[0]
        else:
            total_colors = lut_data.shape[0] * lut_data.shape[1]

        log.debug(
            "LUT mode inputs resolved",
            extra={"event": "lut_mode_inputs_resolved", "lut_shape": list(lut_data.shape), "color_count": int(total_colors)},
        )

        # 尝试从 ColorMode 表中解析。.npy 格式没有随带 stacks 信息，于是
        # ``layers`` / ``max_material`` 传 None，让 5-Color Extended 以重叠卷靠 size 属于
        # 2400-2599 区间。多个随备序重定位在该 ColorMode 上。
        # Try ColorMode taxonomy first (single canonical implementation).
        # NB: .npy LUTs do not carry stacks metadata, so layers + max_material
        # are unknown; the 5-Color Extended window is reachable via size alone
        # because its registered size_range (2400-2600) does not overlap the
        # 8-color window (2600-2801).
        resolved = _resolve_color_mode_from_size(total_colors, None, None)
        if resolved is not None:
            log.info(
                "Detected LUT color mode",
                extra={
                    "event": "lut_color_mode_detected",
                    "source": "npy",
                    "color_count": int(total_colors),
                    "color_mode": resolved,
                },
            )
            return resolved

        # 非标准尺寸：识别为合并色卡。Non-canonical size -> Merged.
        log.info(
            "Detected merged LUT color mode",
            extra={
                "event": "lut_color_mode_detected",
                "source": "npy",
                "color_count": int(total_colors),
                "color_mode": "Merged",
            },
        )
        return "Merged"

    except (OSError, ValueError, TypeError, KeyError, ImportError) as e:
        log.exception(
            "Failed to detect LUT color mode",
            extra={
                "event": "lut_color_mode_detection_failed",
                "lut_path": lut_path,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        return None


# ========== 检测工具函数 (Detection Utility Functions) ==========


def detect_image_type(image_path: str | None) -> str | None:
    """Detect image type and return recommended modeling mode.
    自动检测图像类型并返回推荐的建模模式。

    Args:
        image_path (str | None): Image file path. (图像文件路径)

    Returns:
        str | None: Modeling mode string if change recommended, None otherwise.
            (推荐的建模模式字符串，无需变更时返回 None)
    """
    if not image_path:
        return None

    try:
        ext = os.path.splitext(image_path)[1].lower()

        if ext == ".svg":
            log.info(
                "Detected SVG image type",
                extra={"event": "image_type_detected", "image_path": image_path, "extension": ext, "recommended_mode": str(ModelingMode.VECTOR)},
            )
            return ModelingMode.VECTOR
        else:
            log.info(
                "Detected raster image type",
                extra={"event": "image_type_detected", "image_path": image_path, "extension": ext, "recommended_mode": None},
            )
            return None

    except (OSError, ValueError, TypeError) as e:
        log.warning(
            "Failed to detect image type",
            extra={
                "event": "image_type_detection_failed",
                "image_path": image_path,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        return None


# ========== 缓存辅助函数 (Cache Helper Functions) ==========


def _ensure_quantized_image_in_cache(cache):
    """保证预览缓存中存在 quantized_image，缺失时自动回填。
    Ensure quantized_image exists in preview cache, auto-backfill if missing.

    Args:
        cache (dict): 预览缓存字典，包含 matched_rgb 和可选的 debug_data

    Returns:
        dict: 更新后的缓存字典，保证包含 quantized_image 键
    """
    if cache.get("quantized_image") is not None:
        return cache

    dbg = cache.get("debug_data") or {}
    q = dbg.get("quantized_image")
    if q is None:
        q = cache["matched_rgb"].copy()

    cache["quantized_image"] = q
    return cache


# Click selection and color recommendations.

def _recommend_lut_colors_by_rgb(base_rgb, lut_colors, top_k=10):
    """Recommend LUT colors by RGB Euclidean distance, return top_k items.
    按 RGB 欧氏距离推荐 LUT 颜色，返回前 top_k 项。

    Args:
        base_rgb: (R, G, B) 基准颜色
        lut_colors: LUT 颜色列表（dict 或 tuple 格式）
        top_k (int): 返回前 k 项

    Returns:
        list[dict]: 推荐颜色列表，每项包含 'color' 和 'hex'
    """
    if not lut_colors:
        return []

    normalized = []
    for c in lut_colors:
        if isinstance(c, dict):
            color = c.get("color")
            hex_color = c.get("hex")
            if color is None and isinstance(hex_color, str) and len(hex_color.strip().lstrip("#")) == 6:
                h = hex_color.strip().lstrip("#")
                color = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            if color is not None and isinstance(hex_color, str):
                normalized.append({"color": tuple(int(v) for v in color), "hex": hex_color.lower()})
            continue

        if isinstance(c, (tuple, list)) and len(c) >= 2 and isinstance(c[1], str):
            h = c[1].strip().lstrip("#")
            if len(h) != 6:
                continue
            normalized.append({"color": (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)), "hex": f"#{h.lower()}"})

    if not normalized:
        return []

    arr = np.array([c["color"] for c in normalized], dtype=np.float64)
    b = np.array(base_rgb, dtype=np.float64)
    dist = np.sqrt(np.sum((arr - b) ** 2, axis=1))
    idx = np.argsort(dist)[:top_k]
    return [normalized[i] for i in idx]


def _build_selection_meta(q_rgb, m_rgb, scope="region"):
    """Build click selection metadata (quantized color + matched color).
    构建点击选区元数据（量化色 + 原配准色）。

    Args:
        q_rgb: 量化色 RGB 三元组
        m_rgb: 原配准色 RGB 三元组
        scope (str): 选择范围 ("region" 或 "global")

    Returns:
        dict: 包含 selected_quantized_hex、selected_matched_hex、selection_scope
    """
    return {
        "selected_quantized_hex": _rgb_to_hex(q_rgb),
        "selected_matched_hex": _rgb_to_hex(m_rgb),
        "selection_scope": scope,
    }


def _resolve_highlight_mask(color_match, mask_solid, region_mask=None, scope="global"):
    """Determine highlight mask based on selection scope: region first, otherwise global same-color.
    根据选择范围决定高亮掩码：区域优先，否则全图同色。

    Args:
        color_match (np.ndarray): (H, W) bool 颜色匹配掩码
        mask_solid (np.ndarray): (H, W) bool 实体掩码
        region_mask (np.ndarray | None): (H, W) bool 区域掩码
        scope (str): "region" 或 "global"

    Returns:
        np.ndarray: (H, W) bool 高亮掩码
    """
    if scope == "region" and region_mask is not None:
        return region_mask & mask_solid
    return color_match & mask_solid


def _build_dual_recommendations(q_rgb, m_rgb, lut_colors, top_k=10):
    """Build dual-basis recommendations: by quantized color and by matched color.
    构建双基准推荐：按量化色与按原配准色。

    Args:
        q_rgb: 量化色 RGB 三元组
        m_rgb: 原配准色 RGB 三元组
        lut_colors: LUT 颜色列表
        top_k (int): 每组返回前 k 项

    Returns:
        dict: 包含 'by_quantized' 和 'by_matched' 两组推荐列表
    """
    return {
        "by_quantized": _recommend_lut_colors_by_rgb(q_rgb, lut_colors, top_k=top_k),
        "by_matched": _recommend_lut_colors_by_rgb(m_rgb, lut_colors, top_k=top_k),
    }


def _resolve_click_selection_hexes(cache, default_hex):
    """Resolve display color and internal state color after click.
    解析点击后的显示色与内部状态色。

    显示色优先使用原配准色，内部状态色保持量化色，
    以兼容"显示原图色、替换按量化色作用连通域"的设计。

    Args:
        cache (dict | None): 预览缓存
        default_hex: 默认 hex 颜色值

    Returns:
        tuple: (display_hex, internal_hex)
    """
    cached_q_hex = (cache or {}).get("selected_quantized_hex")
    cached_m_hex = (cache or {}).get("selected_matched_hex")

    # Non-string values (e.g. None) must not propagate into hex state.
    fallback_hex = default_hex if isinstance(default_hex, str) else None
    q_hex = cached_q_hex if isinstance(cached_q_hex, str) else fallback_hex
    m_hex = cached_m_hex if isinstance(cached_m_hex, str) else q_hex
    return m_hex, q_hex
