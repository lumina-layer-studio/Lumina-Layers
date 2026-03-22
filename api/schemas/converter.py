"""Converter domain Pydantic schemas and enums.
Converter 领域的 Pydantic 数据模型与枚举定义。

This module defines all request models for the image-to-3D conversion API,
including preview, generate, batch, color replacement, and color merging.
本模块定义图像转 3D 转换 API 的所有请求模型，
包括预览、生成、批量、颜色替换和颜色合并。
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field


# ========== Enums ==========


class ColorMode(str, Enum):
    """Color system mode for the converter.
    转换器的颜色系统模式。

    Attributes:
        BW: Black & White grayscale mode (32 levels).
            黑白灰度模式 (32 级)。
        FOUR_COLOR_CMYW: 4-Color CMYW mode (1024 colors).
            4 色 CMYW 模式 (1024 色)。
        FOUR_COLOR_RYBW: 4-Color RYBW mode (1024 colors).
            4 色 RYBW 模式 (1024 色)。
        SIX_COLOR: 6-Color extended smart mode (1296 colors).
            6 色扩展智能模式 (1296 色)。
        EIGHT_COLOR: 8-Color professional mode (2738 colors).
            8 色专业模式 (2738 色)。
        MERGED: Merged multi-mode LUT.
            合并多模式 LUT。
    """

    BW = "BW (Black & White)"
    FOUR_COLOR_CMYW = "4-Color (CMYW)"
    FOUR_COLOR_RYBW = "4-Color (RYBW)"
    FIVE_COLOR_EXT = "5-Color Extended"
    SIX_COLOR = "6-Color (Smart 1296)"
    SIX_COLOR_RYBW = "6-Color (RYBW 1296)"
    EIGHT_COLOR = "8-Color Max"
    MERGED = "Merged"


class ModelingMode(str, Enum):
    """3D modeling strategy mode.
    3D 建模策略模式。

    Attributes:
        HIGH_FIDELITY: RLE-based smooth meshing for high detail.
            基于 RLE 的平滑网格，高细节。
        PIXEL: Voxel-based blocky meshing for pixel art style.
            基于体素的块状网格，像素艺术风格。
        VECTOR: Native SVG-to-3D conversion.
            原生 SVG 转 3D 转换。
    """

    HIGH_FIDELITY = "high-fidelity"
    PIXEL = "pixel"
    VECTOR = "vector"


class StructureMode(str, Enum):
    """Print structure mode (single-sided or double-sided).
    打印结构模式（单面或双面）。

    Attributes:
        DOUBLE_SIDED: Double-sided structure with backing plate.
            双面结构，含底板。
        SINGLE_SIDED: Single-sided structure without backing plate.
            单面结构，无底板。
    """

    DOUBLE_SIDED = "Double-sided"
    SINGLE_SIDED = "Single-sided"


class AutoHeightMode(str, Enum):
    """Automatic height assignment mode for 2.5D relief.
    2.5D 浮雕的自动高度分配模式。

    Attributes:
        DARKER_HIGHER: Darker colors get higher relief.
            深色凸起。
        LIGHTER_HIGHER: Lighter colors get higher relief.
            浅色凸起。
        USE_HEIGHTMAP: Use external heightmap image for relief.
            根据高度图。
    """

    DARKER_HIGHER = "深色凸起"
    LIGHTER_HIGHER = "浅色凸起"
    USE_HEIGHTMAP = "根据高度图"


# ========== Models ==========


class ColorReplacementItem(BaseModel):
    """A single color replacement record.
    单条颜色替换记录。

    Maps a quantized source color through its LUT match to a user-chosen
    replacement color.
    将量化后的原色通过 LUT 匹配映射到用户选择的替换色。

    Attributes:
        quantized_hex: Quantized source color in #rrggbb format.
            量化后的原色 (#rrggbb)。
        matched_hex: LUT-matched color in #rrggbb format.
            LUT 匹配色 (#rrggbb)。
        replacement_hex: User-chosen replacement color in #rrggbb format.
            替换目标色 (#rrggbb)。
    """

    quantized_hex: str = Field(..., description="量化后的原色 (#rrggbb)")
    matched_hex: str = Field(..., description="LUT 匹配色 (#rrggbb)")
    replacement_hex: str = Field(..., description="替换目标色 (#rrggbb)")


class ConvertPreviewRequest(BaseModel):
    """Request model for generating a 2D color preview.
    生成 2D 颜色预览的请求模型。

    Used by ``POST /api/convert/preview`` to produce a quick preview image
    showing how the input image will be color-matched against the LUT.
    用于 ``POST /api/convert/preview``，生成快速预览图，
    展示输入图像与 LUT 的颜色匹配效果。

    Attributes:
        lut_name: Name of the LUT to use (from LUT list).
            LUT 名称（从 LUT 列表获取）。
        target_width_mm: Target output width in millimeters.
            目标宽度 (mm)。
        auto_bg: Whether to automatically remove background.
            是否自动去背景。
        bg_tol: Background removal tolerance.
            背景容差。
        color_mode: Color system mode.
            颜色模式。
        modeling_mode: 3D modeling strategy.
            建模模式。
        quantize_colors: Number of K-Means quantization colors.
            K-Means 色彩细节。
        enable_cleanup: Whether to clean up isolated pixels.
            是否启用孤立像素清理。
    """

    lut_name: str = Field(..., description="LUT 名称")
    target_width_mm: float = Field(
        60.0, ge=10, le=9999, description="目标宽度 (mm)"
    )
    auto_bg: bool = Field(False, description="自动去背景")
    bg_tol: int = Field(40, ge=0, le=150, description="背景容差")
    color_mode: ColorMode = Field(
        ColorMode.FOUR_COLOR_RYBW, description="颜色模式"
    )
    modeling_mode: ModelingMode = Field(
        ModelingMode.HIGH_FIDELITY, description="建模模式"
    )
    quantize_colors: int = Field(48, ge=8, le=256, description="K-Means 色彩细节")
    enable_cleanup: bool = Field(True, description="孤立像素清理")
    hue_weight: float = Field(0.0, ge=0.0, le=1.0, description="色相保护权重 (0=纯色差, 0.5=推荐, 1.0=最强)")
    chroma_gate: float = Field(15.0, ge=0.0, le=50.0, description="暗色彩度门槛 (0=禁用, 15=默认)")


class ConvertGenerateRequest(BaseModel):
    """Request model for generating a final 3MF model.
    生成最终 3MF 模型的请求模型。

    Used by ``POST /api/convert/generate`` to produce a printable 3MF file
    with full parameter control including relief, outline, cloisonne, coating,
    keychain loop, and color replacement options.
    用于 ``POST /api/convert/generate``，生成可打印的 3MF 文件，
    支持浮雕、描边、掐丝珐琅、涂层、挂件环和颜色替换等完整参数控制。

    Attributes:
        lut_name: Name of the LUT to use.
            LUT 名称。
        target_width_mm: Target output width in millimeters.
            目标宽度 (mm)。
        spacer_thick: Backing plate thickness in millimeters.
            底板厚度 (mm)。
        structure_mode: Print structure mode.
            打印结构模式。
        auto_bg: Whether to automatically remove background.
            是否自动去背景。
        bg_tol: Background removal tolerance.
            背景容差。
        color_mode: Color system mode.
            颜色模式。
        modeling_mode: 3D modeling strategy.
            建模模式。
        quantize_colors: Number of K-Means quantization colors.
            K-Means 色彩细节。
        enable_cleanup: Whether to clean up isolated pixels.
            是否启用孤立像素清理。
        separate_backing: Whether to export backing plate as separate object.
            底板是否作为独立对象。
        add_loop: Whether to add a keychain loop.
            是否启用挂件环。
        loop_width: Keychain loop width in millimeters.
            环宽度 (mm)。
        loop_length: Keychain loop length in millimeters.
            环长度 (mm)。
        loop_hole: Keychain loop hole diameter in millimeters.
            环孔直径 (mm)。
        loop_pos: Keychain loop position as (x, y) coordinates.
            环位置 (x, y)。
        loop_angle: Keychain loop rotation angle in degrees (-180 to 180).
            环旋转角度 (度)。
        loop_offset_x: Keychain loop X offset in millimeters (-20 to 20).
            环 X 偏移 (mm)。
        loop_offset_y: Keychain loop Y offset in millimeters (-20 to 20).
            环 Y 偏移 (mm)。
        loop_position_preset: Keychain loop position preset name.
            环位置预设名称。
        enable_relief: Whether to enable 2.5D relief mode.
            是否启用 2.5D 浮雕模式。
        color_height_map: Color-to-height mapping for relief mode.
            颜色高度映射 {hex: mm}。
        heightmap_max_height: Maximum relief height in millimeters.
            最大浮雕高度 (mm)。
        enable_outline: Whether to enable outline stroke.
            是否启用描边。
        outline_width: Outline stroke width in millimeters.
            描边宽度 (mm)。
        enable_cloisonne: Whether to enable cloisonne wire frame.
            是否启用掐丝珐琅。
        wire_width_mm: Cloisonne wire width in millimeters.
            金属丝宽度 (mm)。
        wire_height_mm: Cloisonne wire height in millimeters.
            金属丝高度 (mm)。
        enable_coating: Whether to enable transparent coating.
            是否启用涂层。
        coating_height_mm: Coating height in millimeters.
            涂层高度 (mm)。
        replacement_regions: List of color replacement records.
            颜色替换列表。
        free_color_set: Set of hex colors marked as free colors.
            自由色集合 (hex)。
    """

    lut_name: str = Field(..., description="LUT 名称")
    target_width_mm: float = Field(
        60.0, ge=10, le=9999, description="目标宽度 (mm)"
    )
    spacer_thick: float = Field(
        1.2, ge=0.2, le=3.5, description="底板厚度 (mm)"
    )
    structure_mode: StructureMode = Field(
        StructureMode.DOUBLE_SIDED, description="打印结构模式"
    )
    auto_bg: bool = Field(False, description="自动去背景")
    bg_tol: int = Field(40, ge=0, le=150, description="背景容差")
    color_mode: ColorMode = Field(
        ColorMode.FOUR_COLOR_RYBW, description="颜色模式"
    )
    modeling_mode: ModelingMode = Field(
        ModelingMode.HIGH_FIDELITY, description="建模模式"
    )
    quantize_colors: int = Field(48, ge=8, le=256, description="K-Means 色彩细节")
    enable_cleanup: bool = Field(True, description="孤立像素清理")
    hue_weight: float = Field(0.0, ge=0.0, le=1.0, description="色相保护权重 (0=纯色差, 0.5=推荐, 1.0=最强)")
    chroma_gate: float = Field(15.0, ge=0.0, le=50.0, description="暗色彩度门槛 (0=禁用, 15=默认)")
    separate_backing: bool = Field(False, description="底板作为独立对象")
    add_loop: bool = Field(False, description="启用挂件环")
    loop_width: float = Field(
        4.0, ge=2, le=10, description="环宽度 (mm)"
    )
    loop_length: float = Field(
        8.0, ge=4, le=15, description="环长度 (mm)"
    )
    loop_hole: float = Field(
        2.5, ge=1, le=5, description="环孔直径 (mm)"
    )
    loop_pos: Optional[Tuple[float, float]] = Field(
        None, description="环位置 (x, y)"
    )
    loop_angle: float = Field(
        0.0, ge=-180, le=180, description="环旋转角度 (度)"
    )
    loop_offset_x: float = Field(
        0.0, ge=-200, le=200, description="环 X 偏移 (mm)"
    )
    loop_offset_y: float = Field(
        0.0, ge=-200, le=200, description="环 Y 偏移 (mm)"
    )
    loop_position_preset: Optional[str] = Field(
        "top-center",
        description="环位置预设: top-center, top-left, top-right, left-center, right-center, bottom-center",
    )
    enable_relief: bool = Field(False, description="启用 2.5D 浮雕模式")
    height_mode: Optional[str] = Field(
        "color",
        description="浮雕高度模式: 'color' (按颜色) 或 'heightmap' (按高度图)",
    )
    color_height_map: Optional[Dict[str, float]] = Field(
        None, description="颜色高度映射 {hex: mm}"
    )
    heightmap_max_height: float = Field(
        5.0, ge=0.08, le=15.0, description="最大浮雕高度 (mm)"
    )
    enable_outline: bool = Field(False, description="启用描边")
    outline_width: float = Field(
        2.0, ge=0.5, le=10.0, description="描边宽度 (mm)"
    )
    enable_cloisonne: bool = Field(False, description="启用掐丝珐琅")
    wire_width_mm: float = Field(
        0.4, ge=0.2, le=1.2, description="金属丝宽度 (mm)"
    )
    wire_height_mm: float = Field(
        0.4, ge=0.04, le=1.0, description="金属丝高度 (mm)"
    )
    enable_coating: bool = Field(False, description="启用涂层")
    coating_height_mm: float = Field(
        0.08, ge=0.04, le=0.12, description="涂层高度 (mm)"
    )
    replacement_regions: Optional[List[ColorReplacementItem]] = Field(
        None, description="颜色替换列表"
    )
    free_color_set: Optional[Set[str]] = Field(
        None, description="自由色集合 (hex)"
    )
    printer_id: str = Field(
        "bambu-h2d", description="????? ID"
    )
    slicer: str = Field(
        "BambuStudio", description="??????"
    )
    use_cached_matched_rgb: bool = Field(
        False,
        description="使用 Session 缓存的 matched_rgb 而非从原始图像重新处理",
    )


class LargeFormatGenerateRequest(BaseModel):
    """Request model for large-format tiled 3MF generation.
    大画幅切片 3MF 生成的请求模型。

    Splits the image into a grid of tiles, generates a 3MF for each tile,
    and packages all results into a ZIP archive.
    将图片切割为网格切片，每片生成一个 3MF，最终打包为 ZIP。

    Attributes:
        target_height_mm: Total output height in millimeters.
            总输出高度 (mm)。
        tile_width_mm: Width of each tile in millimeters.
            切片宽度 (mm)。
        tile_height_mm: Height of each tile in millimeters.
            切片高度 (mm)。
        params: Shared generation parameters for all tiles.
            所有切片共享的生成参数。
    """

    target_height_mm: float = Field(..., gt=0, description="总输出高度 (mm)")
    tile_width_mm: float = Field(250.0, gt=0, description="切片宽度 (mm)")
    tile_height_mm: float = Field(250.0, gt=0, description="切片高度 (mm)")
    params: ConvertGenerateRequest = Field(..., description="生成参数")


class ConvertBatchRequest(BaseModel):
    """Request model for batch image conversion.
    批量图像转换的请求模型。

    Used by ``POST /api/convert/batch`` to process multiple images with
    shared conversion parameters.
    用于 ``POST /api/convert/batch``，使用共享参数批量处理多张图像。

    Attributes:
        params: Shared conversion parameters applied to all images.
            应用于所有图像的共享转换参数。
    """

    params: ConvertGenerateRequest = Field(..., description="共享参数")


class ColorReplaceRequest(BaseModel):
    """Request model for replacing a single color in the preview.
    替换预览中单个颜色的请求模型。

    Used by ``POST /api/convert/replace-color`` to swap one color in the
    current session's color-matched result.
    用于 ``POST /api/convert/replace-color``，在当前 session 的
    颜色匹配结果中替换一个颜色。

    Attributes:
        session_id: Active session identifier.
            Session ID。
        selected_color: Original image color to replace (hex).
            选中的原图颜色 (hex)。
        replacement_color: Target replacement color (hex).
            替换目标色 (hex)。
    """

    session_id: str = Field(..., description="Session ID")
    selected_color: str = Field(..., description="选中的原图颜色 (hex)")
    replacement_color: str = Field(..., description="替换目标色 (hex)")


class ResetReplacementsRequest(BaseModel):
    """Request model for resetting all color replacements in a session.
    重置 session 中所有颜色替换的请求模型。

    Used by ``POST /api/convert/reset-replacements`` to clear all
    replacement_regions and replacement_history, restoring the preview
    to its original state.
    用于 ``POST /api/convert/reset-replacements``，清空所有
    replacement_regions 和 replacement_history，将预览恢复到原始状态。

    Attributes:
        session_id: Active session identifier. (Session ID)
    """

    session_id: str = Field(..., description="Session ID")


class ColorMergePreviewRequest(BaseModel):
    """Request model for previewing color merge results.
    预览颜色合并结果的请求模型。

    Used by ``POST /api/convert/merge-colors`` to preview the effect of
    merging similar colors based on CIELAB distance thresholds.
    用于 ``POST /api/convert/merge-colors``，预览基于 CIELAB 色差阈值
    合并相似颜色的效果。

    Attributes:
        session_id: Active session identifier.
            Session ID。
        merge_enable: Whether color merging is enabled.
            是否启用颜色合并。
        merge_threshold: CIELAB color difference threshold for merging.
            CIELAB 色差阈值。
        merge_max_distance: Maximum pixel distance for merge candidates.
            最大合并距离 (px)。
    """

    session_id: str = Field(..., description="Session ID")
    merge_enable: bool = Field(True, description="启用颜色合并")
    merge_threshold: float = Field(
        0.5, ge=0.1, le=5.0, description="CIELAB 色差阈值"
    )
    merge_max_distance: int = Field(
        20, ge=5, le=50, description="最大合并距离 (px)"
    )


class RegionDetectRequest(BaseModel):
    """Request model for detecting a connected region at a click position.
    检测点击位置连通区域的请求模型。

    Used by ``POST /api/converter/region-detect`` to identify the connected
    region of same-colored pixels at the given (x, y) coordinate.
    用于 ``POST /api/converter/region-detect``，识别给定 (x, y) 坐标处
    同色像素的连通区域。

    Attributes:
        session_id: Active session identifier. (Session ID)
        x: Click pixel X coordinate (0-indexed). (点击像素 X 坐标)
        y: Click pixel Y coordinate (0-indexed). (点击像素 Y 坐标)
    """

    session_id: str = Field(..., description="Session ID")
    x: int = Field(..., ge=0, description="点击像素 X 坐标")
    y: int = Field(..., ge=0, description="点击像素 Y 坐标")


class RegionDetectResponse(BaseModel):
    """Response model for connected region detection.
    连通区域检测的响应模型。

    Returns the detected region metadata including a unique identifier,
    the region color, pixel count, and a highlighted preview image URL.
    返回检测到的区域元数据，包括唯一标识、区域颜色、像素数量和高亮预览图 URL。

    Attributes:
        region_id: Unique identifier for the detected region. (区域唯一标识)
        color_hex: Hex color of the region. (区域颜色 hex)
        pixel_count: Number of pixels in the region. (区域像素数量)
        preview_url: URL of the highlighted preview image. (高亮预览图 URL)
    """

    region_id: str = Field(..., description="区域唯一标识")
    color_hex: str = Field(..., description="区域颜色 hex")
    pixel_count: int = Field(..., description="区域像素数量")
    preview_url: str = Field(..., description="高亮预览图 URL")
    contours: list[list[list[float]]] | None = Field(
        None, description="区域轮廓坐标（世界坐标 mm），用于 3D 高亮"
    )


class RegionReplaceRequest(BaseModel):
    """Request model for replacing color in a selected connected region.
    替换选中连通区域颜色的请求模型。

    Used by ``POST /api/converter/region-replace`` to replace the color
    of a previously detected connected region with a new target color.
    用于 ``POST /api/converter/region-replace``，将先前检测到的
    连通区域颜色替换为新的目标颜色。

    Attributes:
        session_id: Active session identifier. (Session ID)
        replacement_color: Target replacement color in hex format. (替换目标色 hex)
    """

    session_id: str = Field(..., description="Session ID")
    replacement_color: str = Field(..., description="替换目标色 hex")


class RegionReplaceResponse(BaseModel):
    """Response model for region color replacement.
    区域颜色替换的响应模型。

    Returns the preview image URL after replacement, an optional GLB URL
    for refreshing the 3D preview, and an operation message.
    返回替换后的预览图 URL、可选的 GLB URL（用于刷新 3D 预览）和操作结果消息。

    Attributes:
        preview_url: URL of the post-replacement preview image. (替换后预览图 URL)
        preview_glb_url: URL of the regenerated segmented GLB. (重新生成的分段 GLB URL)
        message: Operation result message. (操作结果消息)
    """

    preview_url: str = Field(..., description="替换后预览图 URL")
    preview_glb_url: Optional[str] = Field(None, description="重新生成的分段 GLB URL")
    color_contours: Optional[dict] = Field(None, description="更新后的颜色轮廓数据")
    message: str = Field("Region replaced", description="操作结果消息")


class BedSizeItem(BaseModel):
    """A single printer bed size option.
    单个打印热床尺寸选项。

    Attributes:
        label: Display label for the bed size, e.g. "256×256 mm" or "Bambu Lab H2D".
            热床尺寸显示标签（可以是尺寸或机型名）。
        width_mm: Bed width in millimeters.
            热床宽度 (mm)。
        height_mm: Bed height in millimeters.
            热床高度 (mm)。
        is_default: Whether this is the default bed size.
            是否为默认热床尺寸。
        printer_id: Optional printer profile ID if this is from a printer model.
            可选的打印机配置 ID（如果来自机型）。
    """

    label: str = Field(..., description="热床尺寸标签")
    width_mm: int = Field(..., description="热床宽度 (mm)")
    height_mm: int = Field(..., description="热床高度 (mm)")
    is_default: bool = Field(False, description="是否为默认热床尺寸")
    printer_id: str | None = Field(None, description="打印机配置 ID（如果来自机型）")


class BedSizeListResponse(BaseModel):
    """Response model for the bed size list endpoint.
    热床尺寸列表响应模型。

    Attributes:
        beds: List of all available bed size options.
            所有可用的热床尺寸选项列表。
    """

    beds: List[BedSizeItem] = Field(..., description="热床尺寸列表")
