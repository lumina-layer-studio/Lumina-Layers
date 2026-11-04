"""Converter domain Pydantic schemas and enums.
Converter 领域的 Pydantic 数据模型与枚举定义。

This module defines all request models for the image-to-3D conversion API,
including preview, generate, batch, color replacement, and color merging.
本模块定义图像转 3D 转换 API 的所有请求模型，
包括预览、生成、批量、颜色替换和颜色合并。
"""

from __future__ import annotations

from enum import Enum
from math import ceil
from typing import Dict, List, Literal, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.dynamic_material_settings import normalize_dynamic_material_settings
from api.schemas.dynamic_material import DynamicMaterialResultResponse
from api.schemas.lut import LutSourceSelection
from config import (
    PrinterConfig,
    SVG_PIXELS_PER_MM_DEFAULT,
    SVG_PIXELS_PER_MM_MAX,
    SVG_PIXELS_PER_MM_MIN,
    normalize_svg_pixels_per_mm,
)

MAX_BACKING_THICKNESS_MM = PrinterConfig.MAX_BACKING_THICKNESS_MM
FRIDGE_MAGNET_SHELL_THICKNESS_MM = 0.4
MAX_FRIDGE_MAGNET_THICKNESS_MM = (
    MAX_BACKING_THICKNESS_MM - FRIDGE_MAGNET_SHELL_THICKNESS_MM
)
MAX_FRIDGE_MAGNETS = 20
MAX_RELIEF_EXTRA_HEIGHT_MM = 15.0
MAX_RELIEF_TOTAL_HEIGHT_MM = MAX_BACKING_THICKNESS_MM + MAX_RELIEF_EXTRA_HEIGHT_MM
# Minimum accepted by API handoff workflows; ordinary converter UI keeps its
# existing 10 mm control limit. API 交接流程允许的最小宽度；普通转换器界面
# 仍保留现有的 10 mm 控件下限。
MIN_TARGET_WIDTH_MM = 0.5
SVG_PIXELS_PER_MM_DESCRIPTION = (
    "高保真 SVG 采样密度（px/mm）；仅高保真模式处理 SVG 时生效，"
    "直接矢量模式不使用此参数"
)


def _validate_dynamic_material_model(model: BaseModel) -> BaseModel:
    """Normalize dynamic-layer fields shared by preview and generate models."""
    enabled, minimum, maximum, tolerance = normalize_dynamic_material_settings(
        material_source="material_archive",
        enabled=getattr(model, "material_dynamic_layer_count_enabled"),
        min_layer_count=getattr(model, "material_min_layer_count"),
        max_layer_count=getattr(model, "material_max_layer_count"),
        delta_e00_tolerance=getattr(model, "material_delta_e00_tolerance"),
        hue_weight=getattr(model, "hue_weight"),
    )
    # Preserve ``model_fields_set`` so generate can distinguish an omitted field
    # (inherit preview state) from an explicit value (must match preview state).
    object.__setattr__(model, "material_dynamic_layer_count_enabled", enabled)
    object.__setattr__(model, "material_min_layer_count", minimum)
    object.__setattr__(model, "material_max_layer_count", maximum)
    object.__setattr__(model, "material_delta_e00_tolerance", tolerance)
    return model

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
    SIX_COLOR = "6-Color (CMYWGK 1296)"
    SIX_COLOR_RYBW = "6-Color (RYBWGK 1296)"
    EIGHT_COLOR = "8-Color Max"
    MERGED = "Merged"


def _normalize_color_mode_alias(value: object) -> object:
    if isinstance(value, str) and value.strip() == "8-Color":
        return ColorMode.EIGHT_COLOR.value
    return value


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
    COLOR_CARD = "color-card"


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


class FridgeMagnetShape(str, Enum):
    """Supported fridge-magnet cavity presets.
    冰箱贴磁铁槽支持的形状预设。

    Attributes:
        ROUND: Circular magnet cavity. (圆形磁铁槽)
        RECT: Rectangular magnet cavity. (矩形磁铁槽)
    """

    ROUND = "round"
    RECT = "rect"


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


class VirtualMaterial(BaseModel):
    """User-declared extra material attached to a recipe override.

    recipe override 附带的用户声明虚拟耗材（LUT 原生没有时使用）。

    Indices in a recipe that are ``>= len(lut_palette)`` refer to positions in
    the ``virtual_materials`` list: entry ``k`` corresponds to recipe value
    ``len(lut_palette) + k``. The downstream pipeline extends the working
    palette with these entries so preview and 3MF output honour the colour
    the user actually picked even when the bundle has no matching channel.

    配方里 ``>= len(lut_palette)`` 的索引指向 ``virtual_materials`` 列表的位置：
    第 ``k`` 条对应索引值 ``len(lut_palette) + k``。下游管线把这些条目追加到
    工作调色板，保证即使 LUT 没有对应通道，预览和 3MF 也按用户选择的原色输出。
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="耗材显示名，例如 'Black' 或 'User-Red'。",
    )
    hex: str = Field(
        ...,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="耗材外观 hex (#RRGGBB)。",
    )


class FridgeMagnetItem(BaseModel):
    """A single fridge-magnet cavity descriptor.
    单个冰箱贴磁铁槽描述。

    Attributes:
        id: Stable frontend/client item identifier. (前端或调用方的稳定 ID)
        shape: Magnet shape preset family. (磁铁形状预设)
        preset_key: Preset key chosen by the client. (客户端选择的预设键)
        diameter_mm: Circular diameter in millimeters for round magnets.
            (圆形磁铁直径，单位毫米)
        width_mm: Width in millimeters for rectangular magnets.
            (矩形磁铁宽度，单位毫米)
        height_mm: Height in millimeters for rectangular magnets.
            (矩形磁铁高度，单位毫米)
        thickness_mm: Magnet thickness in millimeters. (磁铁厚度，单位毫米)
        center_x_mm: Cavity center X coordinate in millimeters.
            (磁铁槽中心 X 坐标，单位毫米)
        center_y_mm: Cavity center Y coordinate in millimeters.
            (磁铁槽中心 Y 坐标，单位毫米)
    """

    model_config = ConfigDict(allow_inf_nan=False)

    id: str = Field(..., description="磁铁槽项 ID")
    shape: FridgeMagnetShape = Field(..., description="磁铁形状: round | rect")
    preset_key: str = Field(..., description="磁铁预设键")
    diameter_mm: float | None = Field(None, gt=0, description="圆形磁铁直径 (mm)")
    width_mm: float | None = Field(None, gt=0, description="矩形磁铁宽度 (mm)")
    height_mm: float | None = Field(None, gt=0, description="矩形磁铁高度 (mm)")
    thickness_mm: float = Field(
        ...,
        gt=0,
        le=MAX_FRIDGE_MAGNET_THICKNESS_MM,
        description="磁铁厚度 (mm)",
    )
    center_x_mm: float = Field(..., description="磁铁槽中心 X (mm)")
    center_y_mm: float = Field(..., description="磁铁槽中心 Y (mm)")

    @model_validator(mode="after")
    def validate_shape_dimensions(self) -> "FridgeMagnetItem":
        """Validate shape-specific dimension requirements.
        校验形状特定的尺寸必填项。
        """

        if self.shape == FridgeMagnetShape.ROUND:
            if self.diameter_mm is None:
                raise ValueError("Round fridge magnets require diameter_mm.")
            if self.width_mm is not None or self.height_mm is not None:
                raise ValueError("Round fridge magnets reject width_mm and height_mm.")
        if self.shape == FridgeMagnetShape.RECT:
            if self.width_mm is None or self.height_mm is None:
                raise ValueError("Rect fridge magnets require width_mm and height_mm.")
            if self.diameter_mm is not None:
                raise ValueError("Rect fridge magnets reject diameter_mm.")
        return self


class SvgHoleCompensationOptions(BaseModel):
    """Optional source-SVG 2D hole filling in physical units.
    可选的 SVG 二维补洞参数，按成品物理尺寸计算。
    """

    svg_hole_compensation_enabled: bool = Field(False, description="SVG 小洞补偿")
    svg_hole_max_area_mm2: float = Field(
        0.5, ge=0.0, allow_inf_nan=False, description="补孔面积上限 (mm²)，0 关闭面积筛选",
    )
    svg_hole_max_width_mm: float = Field(
        0.1, ge=0.0, allow_inf_nan=False, description="细缝宽度上限 (mm)，0 关闭细缝筛选",
    )


class ConvertPreviewRequest(LutSourceSelection, SvgHoleCompensationOptions):
    """Request model for generating a 2D color preview.
    生成 2D 颜色预览的请求模型。

    Used by ``POST /api/convert/preview`` to produce a quick preview image
    showing how the input image will be color-matched against the LUT.
    用于 ``POST /api/convert/preview``，生成快速预览图，
    展示输入图像与 LUT 的颜色匹配效果。

    Attributes:
        source_kind: Legacy LUT or native bundle source selector.
            源类型选择器。
        lut_name: Name of the LUT to use (for legacy_single).
            LUT 名称（legacy_single 使用）。
        material_type: Native material type (for native_bundle).
            原生材料类型。
        vendor: Native vendor (for native_bundle).
            原生厂商。
        db_names: Native DB selection list (for native_bundle).
            原生 DB 选择列表。
        target_width_mm: Target output width in millimeters.
            目标宽度 (mm)。
        color_mode: Color system mode.
            颜色模式。
        modeling_mode: 3D modeling strategy.
            建模模式。
        quantize_colors: Number of K-Means quantization colors.
            K-Means 色彩细节（仅高保真模式生效）。
        enable_cleanup: Whether to clean up isolated pixels.
            是否启用孤立像素清理。
        enable_outline: Whether to request outline metadata in vector preview.
            是否在矢量预览中请求描边元数据。
        outline_width: Outline stroke width in millimeters.
            描边宽度 (mm)。

    Note:
        Legacy clients that still send ``auto_bg``/``bg_tol`` are accepted
        thanks to ``extra='ignore'``; the fields are silently dropped.
    """

    model_config = ConfigDict(extra="ignore")

    target_width_mm: float = Field(
        60.0,
        ge=MIN_TARGET_WIDTH_MM,
        le=9999,
        description="目标宽度 (mm)",
    )
    color_mode: ColorMode = Field(ColorMode.FOUR_COLOR_RYBW, description="颜色模式")
    modeling_mode: ModelingMode = Field(ModelingMode.HIGH_FIDELITY, description="建模模式")
    color_layers: Optional[int] = Field(None, ge=1, le=20, description="叠色层数")
    layer_height_mm: Optional[float] = Field(None, gt=0.0, le=1.0, description="叠色层高 (mm)")
    model_enable: bool = Field(False, description="启用模型辅助匹配")
    model_only: bool = Field(False, description="仅使用模型匹配，跳过 DB 匹配")
    model_threshold: float | None = Field(None, description="模型回退阈值；空值或负数表示使用运行时默认值")
    model_margin: float | None = Field(None, description="模型回退边距；空值或负数表示使用运行时默认值")
    quantize_colors: int = Field(48, ge=8, le=8192, description="K-Means 色彩细节（仅高保真模式生效）")
    enable_cleanup: bool = Field(True, description="孤立像素清理")
    enable_outline: bool = Field(False, description="启用描边")
    outline_width: float = Field(2.0, ge=0.5, le=10.0, description="描边宽度 (mm)")
    svg_pixels_per_mm: float = Field(
        SVG_PIXELS_PER_MM_DEFAULT,
        ge=SVG_PIXELS_PER_MM_MIN,
        le=SVG_PIXELS_PER_MM_MAX,
        description=SVG_PIXELS_PER_MM_DESCRIPTION,
    )
    hue_weight: float = Field(0.0, ge=0.0, le=1.0, description="色相保护权重 (0=纯色差, 0.5=推荐, 1.0=最强)")
    chroma_gate: float = Field(15.0, ge=0.0, le=50.0, description="暗色彩度门槛 (0=禁用, 15=默认)")
    material_backing_material_index: int | None = Field(
        None,
        ge=0,
        description="耗材档案模式底板耗材索引（基于 selected_materials 的 0-based 索引）",
    )
    material_dynamic_layer_count_enabled: bool = Field(
        False,
        description="启用耗材模式动态有效叠层数",
    )
    material_min_layer_count: int = Field(5, ge=5, le=10, description="最小有效叠层数")
    material_max_layer_count: int = Field(10, ge=5, le=10, description="最大有效叠层数")
    material_delta_e00_tolerance: float = Field(
        0.5,
        ge=0.0,
        le=5.0,
        description="短配方允许的 CIEDE2000 色差损失",
    )
    use_lut_constrained: bool = Field(False, description="启用高精度LUT约束颜色匹配（实验性）")
    auto_dynamic_range: bool = Field(False, description="启用自动动态范围压缩（实验性）")
    high_precision_3d_preview: bool = Field(False, description="启用3D高精度颜色预览")
    surface_model_file_id: str | None = Field(None, description="Uploaded model file id for surface overlay")
    surface_selection_json: str | None = Field(None, description="JSON surface selection payload")
    surface_footprint_json: str | None = Field(None, description="JSON surface footprint payload")
    surface_placement_json: str | None = Field(None, description="JSON surface placement payload")
    surface_model_transform_json: str | None = Field(None, description="JSON surface model transform payload")

    @field_validator("color_mode", mode="before")
    @classmethod
    def normalize_color_mode_alias(cls, value: object) -> object:
        return _normalize_color_mode_alias(value)

    @field_validator("svg_pixels_per_mm")
    @classmethod
    def validate_svg_pixels_per_mm(cls, value: float) -> float:
        return normalize_svg_pixels_per_mm(value)

    @model_validator(mode="after")
    def validate_dynamic_material_settings(self) -> "ConvertPreviewRequest":
        """Validate dynamic material range and hue compatibility.
        校验动态耗材层数范围与色相兼容性。
        """
        return _validate_dynamic_material_model(self)  # type: ignore[return-value]


class RecipeOverrideItem(BaseModel):
    """Region-level recipe override for predictive/custom recipe workflows."""

    region_id: str = Field(..., description="区域 ID")
    recipe: list[int] = Field(..., min_length=1, max_length=20, description="配方层序列")
    layer_order: str = Field("Top2Bottom", description="配方层顺序")
    color_layers: int | None = Field(None, ge=1, le=20, description="实际配方层数")
    actual_recipe_top_to_bottom: list[int] | None = Field(
        None,
        min_length=1,
        max_length=20,
        description="动态模式实际 Top-to-Bottom 配方",
    )
    print_recipe_top_to_bottom: list[int] | None = Field(
        None,
        min_length=1,
        max_length=20,
        description="动态模式补齐后的 Top-to-Bottom 打印配方",
    )
    actual_layer_count: int | None = Field(None, ge=1, le=20)
    padding_layer_count: int | None = Field(None, ge=0, le=20)
    virtual_materials: list[VirtualMaterial] | None = Field(
        default=None,
        description=(
            "可选：配方里 >= LUT.N 的索引对应的虚拟耗材。See ``VirtualMaterial``. "
            "Mirrors the converter-side override item so the generate pipeline "
            "can reconstruct the extended palette."
        ),
    )


class CoatingMaterialReference(BaseModel):
    """Legacy request field; coating now follows the source material types."""

    model_config = ConfigDict(extra="forbid")
    source: Literal["palette", "material_archive"]
    key: str = Field(min_length=1)


class ConvertGenerateRequest(LutSourceSelection, SvgHoleCompensationOptions):
    project_revision_file_id: str | None = Field(None, max_length=128, description="Explicit frozen project revision to embed in the final output")
    """Request model for generating a final 3MF model.
    生成最终 3MF 模型的请求模型。

    Used by ``POST /api/convert/generate`` to produce a printable 3MF file
    with full parameter control including relief, outline, cloisonne, coating,
    keychain loop, and color replacement options.
    用于 ``POST /api/convert/generate``，生成可打印的 3MF 文件，
    支持浮雕、描边、掐丝珐琅、涂层、挂件环和颜色替换等完整参数控制。

    Attributes:
        source_kind: Legacy LUT or native bundle source selector.
            源类型选择器。
        lut_name: Name of the LUT to use (for legacy_single).
            LUT 名称（legacy_single 使用）。
        material_type: Native material type (for native_bundle).
            原生材料类型。
        vendor: Native vendor (for native_bundle).
            原生厂商。
        db_names: Native DB selection list (for native_bundle).
            原生 DB 选择列表。
        target_width_mm: Target output width in millimeters.
            目标宽度 (mm)。
        spacer_thick: Backing plate thickness in millimeters.
            底板厚度 (mm)。
        backing_infill_density_percent: Sparse-infill density used only below
            the protected viewing-surface zone.（仅用于观赏面保护区以下深层底板的
            稀疏填充百分比。）
        structure_mode: Print structure mode.
            打印结构模式。
        color_mode: Color system mode.
            颜色模式。
        modeling_mode: 3D modeling strategy.
            建模模式。
        quantize_colors: Number of K-Means quantization colors.
            K-Means 色彩细节（仅高保真模式生效）。
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
        enable_fridge_magnet: Whether to enable fridge magnet cavity processing.
            是否启用冰箱贴磁铁槽。
        fridge_magnets: Fridge magnet cavity descriptors.
            冰箱贴磁铁槽参数列表。
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
        heightmap_max_height: Maximum total relief model height in millimeters.
            最大浮雕模型总高度 (mm)。
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

    model_config = ConfigDict(extra="ignore")

    target_width_mm: float = Field(
        60.0,
        ge=MIN_TARGET_WIDTH_MM,
        le=9999,
        description="目标宽度 (mm)",
    )
    spacer_thick: float = Field(1.2, ge=0.2, le=MAX_BACKING_THICKNESS_MM, description="底板厚度 (mm)")
    backing_infill_density_percent: int = Field(
        PrinterConfig.BACKING_INFILL_DENSITY_DEFAULT_PERCENT,
        ge=PrinterConfig.BACKING_INFILL_DENSITY_MIN_PERCENT,
        le=PrinterConfig.BACKING_INFILL_DENSITY_MAX_PERCENT,
        description="深层底板填充率 (%)",
    )
    structure_mode: StructureMode = Field(StructureMode.DOUBLE_SIDED, description="打印结构模式")
    color_mode: ColorMode = Field(ColorMode.FOUR_COLOR_RYBW, description="颜色模式")
    modeling_mode: ModelingMode = Field(ModelingMode.HIGH_FIDELITY, description="建模模式")
    color_layers: Optional[int] = Field(None, ge=1, le=20, description="叠色层数")
    layer_height_mm: Optional[float] = Field(None, gt=0.0, le=1.0, description="叠色层高 (mm)")
    model_enable: bool = Field(False, description="启用模型辅助匹配")
    model_only: bool = Field(False, description="仅使用模型匹配，跳过 DB 匹配")
    model_threshold: float | None = Field(None, description="模型回退阈值；空值或负数表示使用运行时默认值")
    model_margin: float | None = Field(None, description="模型回退边距；空值或负数表示使用运行时默认值")
    quantize_colors: int = Field(48, ge=8, le=8192, description="K-Means 色彩细节（仅高保真模式生效）")
    enable_cleanup: bool = Field(True, description="孤立像素清理")
    svg_pixels_per_mm: float = Field(
        SVG_PIXELS_PER_MM_DEFAULT,
        ge=SVG_PIXELS_PER_MM_MIN,
        le=SVG_PIXELS_PER_MM_MAX,
        description=SVG_PIXELS_PER_MM_DESCRIPTION,
    )
    hue_weight: float = Field(0.0, ge=0.0, le=1.0, description="色相保护权重 (0=纯色差, 0.5=推荐, 1.0=最强)")
    chroma_gate: float = Field(15.0, ge=0.0, le=50.0, description="暗色彩度门槛 (0=禁用, 15=默认)")
    material_backing_material_index: int | None = Field(
        None,
        ge=0,
        description="耗材档案模式底板耗材索引（基于 selected_materials 的 0-based 索引）",
    )
    material_dynamic_layer_count_enabled: bool = Field(
        False,
        description="启用耗材模式动态有效叠层数",
    )
    material_min_layer_count: int = Field(5, ge=5, le=10, description="最小有效叠层数")
    material_max_layer_count: int = Field(10, ge=5, le=10, description="最大有效叠层数")
    material_delta_e00_tolerance: float = Field(
        0.5,
        ge=0.0,
        le=5.0,
        description="短配方允许的 CIEDE2000 色差损失",
    )
    use_lut_constrained: bool = Field(False, description="启用高精度LUT约束颜色匹配（实验性）")
    auto_dynamic_range: bool = Field(False, description="启用自动动态范围压缩（实验性）")
    high_precision_3d_preview: bool = Field(False, description="启用3D高精度颜色预览")
    recipe_overrides: list[RecipeOverrideItem] | None = Field(None, description="区域级自定义配方覆盖")
    separate_backing: bool = Field(False, description="底板作为独立对象")
    backing_output: Literal["same_project", "separate_project"] = "same_project"
    add_loop: bool = Field(False, description="启用挂件环")
    loop_width: float = Field(4.0, ge=2, le=10, description="环宽度 (mm)")
    loop_length: float = Field(8.0, ge=4, le=15, description="环长度 (mm)")
    loop_hole: float = Field(2.5, ge=1, le=5, description="环孔直径 (mm)")
    loop_pos: Optional[Tuple[float, float]] = Field(None, description="环位置 (x, y)")
    enable_fridge_magnet: bool = Field(False, description="启用冰箱贴磁铁槽")
    fridge_magnets: List[FridgeMagnetItem] = Field(
        default_factory=list,
        max_length=MAX_FRIDGE_MAGNETS,
        description="冰箱贴磁铁槽列表",
    )
    loop_angle: float = Field(0.0, ge=-180, le=180, description="环旋转角度 (度)")
    loop_offset_x: float = Field(0.0, ge=-200, le=200, description="环 X 偏移 (mm)")
    loop_offset_y: float = Field(0.0, ge=-200, le=200, description="环 Y 偏移 (mm)")
    loop_position_preset: Optional[str] = Field(
        "top-center",
        description="环位置预设: top-center, top-left, top-right, left-center, right-center, bottom-center",
    )
    enable_relief: bool = Field(False, description="启用 2.5D 浮雕模式")
    height_mode: Optional[str] = Field(
        "color",
        description="浮雕高度模式: 'color' (按颜色) 或 'heightmap' (按高度图)",
    )
    color_height_map: Optional[Dict[str, float]] = Field(None, description="颜色高度映射 {hex: mm}")
    heightmap_max_height: float = Field(
        5.0,
        ge=0.08,
        le=MAX_RELIEF_TOTAL_HEIGHT_MM,
        description="最大浮雕模型总高度 (mm)",
    )
    enable_outline: bool = Field(False, description="启用描边")
    outline_width: float = Field(2.0, ge=0.5, le=10.0, description="描边宽度 (mm)")
    enable_cloisonne: bool = Field(False, description="启用掐丝珐琅")
    wire_width_mm: float = Field(0.4, ge=0.2, le=1.2, description="金属丝宽度 (mm)")
    wire_height_mm: float = Field(0.4, ge=0.04, le=1.0, description="金属丝高度 (mm)")
    enable_coating: bool = Field(False, description="启用涂层")
    coating_height_mm: float = Field(0.08, ge=0.04, le=0.12, description="涂层高度 (mm)")
    coating_material: CoatingMaterialReference | None = Field(
        default=None, deprecated=True,
        description="Legacy selection, ignored; coating follows source types and mixed types default to PLA.",
    )
    replacement_regions: Optional[List[ColorReplacementItem]] = Field(None, description="颜色替换列表")
    recipe_overrides: Optional[List[RecipeOverrideItem]] = Field(None, description="区域级配方覆盖列表")
    free_color_set: Optional[Set[str]] = Field(None, description="自由色集合 (hex)")
    printer_id: str = Field("bambu-h2d", description="Printer profile ID")
    slicer: str = Field("BambuStudio", description="Slicer software name")
    custom_3mf_template_id: str | None = None
    native_filament_profiles: dict[str, str] = Field(
        default_factory=dict,
        description="Exact native filament preset selections keyed by exported material name",
    )
    nozzle_size: str = Field("0.4", description="Printer nozzle size")
    device_profile_id: Optional[str] = Field(
        None,
        description="Generated machine registry device profile ID",
    )
    build_plate_id: Optional[str] = Field(
        None,
        description="Validated slicer-native build plate ID",
    )
    enable_base_layer_height_modifier: bool = Field(
        True,
        description="Bambu 切片器：底板层高修改器开关（底板用 nozzle×0.5 粗层高打印）",
    )
    enable_wipe_tower_auto_placement: bool = Field(
        True,
        description="自动调整擦料塔位置和尺寸以避开模型",
    )
    use_cached_matched_rgb: bool = Field(
        False,
        description="使用 Session 缓存的 matched_rgb 而非从原始图像重新处理",
    )
    editor_content_revision: int | None = Field(
        None,
        ge=0,
        description="前端提交的已确认可见内容版本",
    )
    selection_revision: int | None = Field(
        None,
        ge=0,
        description="前端提交的已确认共享选区版本",
    )

    @field_validator("color_mode", mode="before")
    @classmethod
    def normalize_color_mode_alias(cls, value: object) -> object:
        return _normalize_color_mode_alias(value)

    @field_validator("svg_pixels_per_mm")
    @classmethod
    def validate_svg_pixels_per_mm(cls, value: float) -> float:
        return normalize_svg_pixels_per_mm(value)

    @model_validator(mode="after")
    def validate_sparse_backing_contract(self) -> "ConvertGenerateRequest":
        """Reject geometry whose variable surface cannot use one safe Z range.
        拒绝无法用统一 Z 区间保护观赏面的可变高度几何。
        """
        if self.backing_output == "separate_project" and (
            not self.separate_backing or self.structure_mode != StructureMode.SINGLE_SIDED
            or self.enable_relief or self.color_mode == ColorMode.FIVE_COLOR_EXT
        ):
            raise ValueError("Independent backing projects require a single-sided model with separated backing and no relief or 5-color extended structure")
        if self.enable_relief and self.backing_infill_density_percent < 100:
            raise ValueError(
                "Sparse backing infill is not supported with relief mode; "
                "use 100% backing infill."
            )
        if self.enable_fridge_magnet and self.fridge_magnets:
            deepest_cavity_mm = max(
                magnet.thickness_mm for magnet in self.fridge_magnets
            )
            required_backing_mm = round(
                ceil(
                    (
                        deepest_cavity_mm
                        + FRIDGE_MAGNET_SHELL_THICKNESS_MM
                    )
                    / PrinterConfig.LAYER_HEIGHT
                    - 1e-9
                )
                * PrinterConfig.LAYER_HEIGHT,
                10,
            )
            self.spacer_thick = max(self.spacer_thick, required_backing_mm)
        return self

    @model_validator(mode="after")
    def validate_dynamic_material_settings(self) -> "ConvertGenerateRequest":
        """Validate dynamic material range and hue compatibility.
        校验动态耗材层数范围与色相兼容性。
        """
        return _validate_dynamic_material_model(self)  # type: ignore[return-value]


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

    target_height_mm: float | None = Field(
        None,
        gt=0,
        allow_inf_nan=False,
        description="总输出高度 (mm)",
    )
    tile_width_mm: float = Field(
        250.0,
        gt=0,
        allow_inf_nan=False,
        description="切片宽度 (mm)",
    )
    tile_height_mm: float = Field(
        250.0,
        gt=0,
        allow_inf_nan=False,
        description="切片高度 (mm)",
    )
    params: "LargeFormatConvertGenerateRequest" = Field(..., description="生成参数")


class LargeFormatConvertGenerateRequest(ConvertGenerateRequest):
    """Large-format generate params where target width may be derived.
    大画幅生成参数：目标宽度可由目标高度和原图比例推导。
    """

    target_width_mm: float | None = Field(
        None,
        ge=MIN_TARGET_WIDTH_MM,
        allow_inf_nan=False,
        description="目标宽度 (mm)",
    )

    @model_validator(mode="after")
    def validate_backing_output(self) -> "LargeFormatConvertGenerateRequest":
        if self.backing_output != "same_project":
            raise ValueError("Independent backing projects are available for single-model generation; large-format already has a tile output workflow")
        return self


LargeFormatGenerateRequest.model_rebuild()


class PuzzleStyle(str, Enum):
    """Puzzle layout style.
    拼图布局风格。

    Attributes:
        REGULAR: Regular row-column puzzle. (规则行列拼图)
        IRREGULAR: Perturbed row-column puzzle. (扰动网格拼图)
    """

    REGULAR = "regular"
    IRREGULAR = "irregular"


class PuzzleSizingMode(str, Enum):
    """Puzzle sizing control mode.
    拼图尺寸控制模式。

    Attributes:
        PIECE_SIZE: Resolve rows/cols from average piece size.
            (根据平均块尺寸推导行列)
        GRID: Use explicit row and column counts. (直接使用行列数)
        PIECE_COUNT: Resolve the closest row-column grid from target count.
            (根据目标片数推导最接近的行列网格)
    """

    PIECE_SIZE = "piece_size"
    GRID = "grid"
    PIECE_COUNT = "piece_count"


class PuzzleConnectorStyle(str, Enum):
    """Puzzle connector style preset.
    拼图连接器风格预设。

    Attributes:
        CLASSIC: Classic rounded connector. (经典圆润连接器)
        EASY_CUT: Shallower and easier-to-print connector.
            (更浅、更容易打印的简化连接器)
    """

    CLASSIC = "classic"
    EASY_CUT = "easy_cut"


class PuzzleLayoutPreviewRequest(BaseModel):
    """Request model for puzzle layout overlay preview.
    拼图布局叠线预览请求模型。

    Attributes:
        target_height_mm: Intended total output height in millimeters.
            (期望总输出高度，单位毫米)
        puzzle_style: Puzzle style selector. (拼图风格选择)
        sizing_mode: Active sizing mode. (当前尺寸模式)
        piece_width_mm: Requested average piece width. (请求的平均块宽度)
        piece_height_mm: Requested average piece height. (请求的平均块高度)
        rows: Requested row count in grid mode. (grid 模式下的目标行数)
        cols: Requested column count in grid mode. (grid 模式下的目标列数)
        target_piece_count: Requested target piece count. (目标片数)
        seed: Deterministic random seed. (确定性的随机种子)
        connector_style: Connector preset. (连接器预设)
        labels_enabled: Whether labels should be shown on the overlay.
            (是否在叠线图中显示编号)
        engrave_back_labels: Reserved flag for future underside label engraving.
            (为未来背面刻号预留的标志位，当前版本未实现)
        irregularity_strength: Perturbation strength for irregular layouts.
            (不规则布局扰动强度)
        min_neck_width_mm: Minimum printable neck width.
            (最小可打印脖颈宽度)
    """

    target_height_mm: float = Field(..., gt=0, description="拼图总高度 (mm)")
    puzzle_style: PuzzleStyle = Field(PuzzleStyle.REGULAR, description="拼图风格")
    sizing_mode: PuzzleSizingMode = Field(PuzzleSizingMode.PIECE_SIZE, description="尺寸模式")
    piece_width_mm: float = Field(20.0, gt=0, description="平均块宽度 (mm)")
    piece_height_mm: float = Field(20.0, gt=0, description="平均块高度 (mm)")
    rows: int = Field(3, ge=1, description="行数")
    cols: int = Field(3, ge=1, description="列数")
    target_piece_count: int = Field(12, ge=1, description="目标片数")
    seed: int = Field(0, ge=0, le=999999, description="随机种子")
    connector_style: PuzzleConnectorStyle = Field(PuzzleConnectorStyle.CLASSIC, description="连接器风格")
    labels_enabled: bool = Field(False, description="显示编号")
    engrave_back_labels: bool = Field(False, description="背面刻号（预留，当前未实现）")
    irregularity_strength: float = Field(0.35, ge=0.0, le=1.0, description="不规则强度")
    min_neck_width_mm: float = Field(1.2, gt=0, le=10.0, description="最小脖颈宽度 (mm)")


class PuzzleGenerateRequest(PuzzleLayoutPreviewRequest):
    """Request model for puzzle piece generation.
    拼图分块生成请求模型。

    Attributes:
        params: Shared generate parameters for each piece.
            (每个拼图块共享的生成参数)
    """

    params: ConvertGenerateRequest = Field(..., description="每块共享的生成参数")

    @model_validator(mode="after")
    def validate_backing_output(self) -> "PuzzleGenerateRequest":
        if self.params.backing_output != "same_project":
            raise ValueError("Independent backing projects are available for single-model generation; use the existing puzzle plate output for pieces")
        return self

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
    operation_id: str | None = Field(None, max_length=128, description="编辑操作 ID")


class ColorReplacePair(BaseModel):
    """A single ``(selected_color, replacement_color)`` swap entry.
    单个 (原色, 目标色) 替换项。
    """

    selected_color: str = Field(..., description="选中的原图颜色 (hex)")
    replacement_color: str = Field(..., description="替换目标色 (hex)")


class ColorReplaceBatchRequest(BaseModel):
    """Request model for batch-replacing multiple colors in one round-trip.
    一次请求批量替换多个颜色（用 1 次 PNG+GLB 渲染代替 N 次，N× 提速）。

    Used by ``POST /api/convert/replace-colors-batch``. The server applies
    every pair to the cached ``matched_rgb`` in a single pass, runs the
    material-matrix sync once against the combined diff, and regenerates the
    styled preview PNG + segmented GLB exactly once at the end. Avoids the
    N-round pattern where each per-colour request triggered a fresh GLB
    build (``generate_segmented_glb`` is the dominant cost).

    用于 ``POST /api/convert/replace-colors-batch``：一次调用里把多条 pair
    累加地应用到 ``matched_rgb``，物料矩阵 sync、PNG、GLB 分别只跑 1 次。
    解决前端 for 循环 N 次 /replace-color 的瓶颈——GLB 生成是主要成本。

    Attributes:
        session_id: Active session identifier. (Session ID)
        replacements: Ordered list of (selected_color, replacement_color)
            pairs. Later pairs see earlier pairs' effects, matching the
            semantics of calling /replace-color N times in sequence.
            有序替换对列表；后面的 pair 能看见前面 pair 的效果，语义上
            等价于顺序调用 N 次 /replace-color。
    """

    session_id: str = Field(..., description="Session ID")
    replacements: list[ColorReplacePair] = Field(
        default_factory=list,
        description="批量替换对列表（可为空，空列表表示重放为无全局颜色替换）",
    )
    operation_id: str | None = Field(None, max_length=128, description="编辑操作 ID")


class FreeColorMutationRequest(BaseModel):
    """Set or clear free-colour flags as one undoable content action."""

    session_id: str = Field(..., description="Session ID")
    action: Literal["toggle", "clear", "replace"]
    color_hexes: list[str] = Field(default_factory=list)
    operation_id: str | None = Field(None, max_length=128, description="编辑操作 ID")


class FreeColorMutationResponse(BaseModel):
    status: str = "ok"
    free_color_set: list[str] = Field(default_factory=list)
    can_undo: bool = False
    can_redo: bool = False
    operation_id: str | None = None
    editor_content_revision: int | None = Field(None, ge=0)


class EditorCommitResult(BaseModel):
    """Bounded business-state projection for a committed editor operation.

    编辑操作提交回执中的有限业务状态投影。

    This is intentionally smaller than a preview cache or history checkpoint;
    it lets a client converge after a lost HTTP response without transporting
    image arrays, masks, or a second copy of the editor state.
    """

    preview_url: str | None = None
    preview_glb_url: str | None = None
    replacement_regions: list[ColorReplacementItem] | None = None
    recipe_overrides: list[RecipeOverrideItem] | None = None
    recipe_override_count: int | None = Field(None, ge=0)
    region_replacement_count: int | None = Field(None, ge=0)
    color_layers: int | None = Field(None, ge=1)
    layer_height_mm: float | None = Field(None, gt=0.0)
    gradient_groups: list[GradientGroupItem] | None = None
    free_color_set: list[str] | None = None
    can_undo: bool | None = None
    can_redo: bool | None = None
    material_dynamic_recipes: list[dict] | None = None
    material_layer_benefit_curve: list[dict] | None = None
    material_layer_benefit_scope: str | None = None
    material_layer_benefit_pixel_count: int | None = Field(None, ge=0)


class EditorCommitStatusResponse(BaseModel):
    """Confirmation for one editor operation after a lost response."""

    status: Literal["pending", "committed", "failed", "unknown"]
    operation_id: str
    operation: str | None = None
    editor_content_revision: int = Field(0, ge=0)
    visible_content_revision: int = Field(0, ge=0)
    selection_revision: int | None = Field(None, ge=0)
    result: EditorCommitResult | None = None


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
    operation_id: str | None = Field(None, max_length=128, description="编辑操作 ID")


class RecipePredictRequest(BaseModel):
    """Request for predicting a custom recipe color.
    预测自定义配方颜色的请求。
    """

    session_id: str = Field(..., description="Session ID")
    recipe: List[int] = Field(..., min_length=1, description="配方通道索引序列")
    layer_order: str = Field("Top2Bottom", description="配方层序")
    color_layers: int = Field(..., ge=1, le=20, description="叠色层数")
    layer_height_mm: float = Field(..., gt=0.0, le=1.0, description="叠色层高 (mm)")
    virtual_materials: list[VirtualMaterial] | None = Field(
        default=None,
        description=(
            "可选：配方里 >= LUT.N 的索引对应的虚拟耗材列表。Optional list of "
            "user-declared extra materials. Recipe values at or beyond the LUT "
            "palette length index into this list."
        ),
    )


class SimilarRecipesRequest(BaseModel):
    """Request for printable recipes whose colour is close to a target.
    请求与目标颜色相近的可打印配方。

    Attributes:
        session_id: Active converter session. (当前转换会话)
        target_color: Colour to match as ``#rrggbb``. (要匹配的颜色)
        limit: Maximum number of suggestions. (最多返回条数)
        include_predictive: Also rank forward-model candidates when the LUT
            ships a predictive runtime. (LUT 带预测模型时同时排序预测候选)
    """

    session_id: str = Field(..., description="Session ID")
    target_color: str = Field(
        ...,
        pattern=r"^#?[0-9a-fA-F]{6}$",
        description="目标颜色 / target colour (#rrggbb)",
    )
    limit: int = Field(12, ge=1, le=48, description="最多返回条数 / max suggestions")
    include_predictive: bool = Field(
        True,
        description="是否包含预测配方 / include forward-model candidates",
    )


class RecipeOverrideApplyRequest(RecipePredictRequest):
    """Request for applying a custom recipe to selected regions.
    将自定义配方应用到选区的请求。
    """

    region_ids: List[str] = Field(default_factory=list, description="要应用的区域 ID 列表")
    operation_id: str | None = Field(None, max_length=128, description="编辑操作 ID")


class RegionRecipeRequest(BaseModel):
    """Request model for reading the current per-layer recipe of selected regions.
    读取选中区域当前每层堆叠配方的请求模型。

    Used by the Custom Recipe dialog to pre-populate the per-layer dropdowns
    with the region's *actual* matched recipe instead of the all-White
    default. Without this the dialog silently overwrites the user's current
    recipe on "Apply" if they just wanted to tweak one or two layers —
    exactly the "全白默认" bug the user reported.

    Attributes:
        session_id: Active session identifier. (Session ID)
        region_ids: Regions to sample. Must be non-empty; mirrors the apply
            endpoint's region contract so both dialogs share the same session
            keys (``selected_region_masks`` + fallback single-region).
            区域 ID 列表，至少一个；与 apply 端点共用 session 里的区域键。
        layer_order: Output layer order ("Top2Bottom" / "Bottom2Top").
            Defaults to ``Top2Bottom`` since the pipeline stores
            ``material_matrix`` with layer 0 = viewing surface.
            输出层序，默认 Top2Bottom（material_matrix 的存储约定）。
    """

    session_id: str = Field(..., description="Session ID")
    region_ids: List[str] = Field(
        default_factory=list, description="要读取 recipe 的区域 ID 列表"
    )
    layer_order: str = Field(
        "Top2Bottom", description="返回 recipe 的层序，默认 Top2Bottom"
    )


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
    merge_threshold: float = Field(0.5, ge=0.1, le=5.0, description="CIELAB 色差阈值")
    merge_max_distance: int = Field(20, ge=5, le=50, description="最大合并距离 (px)")


class ColorHighlightRequest(BaseModel):
    """Request model for highlighting all pixels of given colors in the preview.
    高亮预览图中指定颜色所有像素的请求模型。

    Used by ``POST /api/convert/color-highlight`` to generate a preview
    image with semi-transparent cyan overlay on all pixels matching any
    of the given color hex values. Two optional clipping modes are
    supported, checked in priority order:

    1. ``gradient_group_index + gradient_region_index`` — clip the highlight
       to the *exact* pixel mask of one spatial sub-region inside a gradient
       group. This uses the cached per-pixel region-id map computed during
       preview generation; it is the correct choice when the UI wants to
       focus on one specific sub-region without leaking into other
       same-colour pixels elsewhere.
       最精确模式：按单个渐变子区域的精确像素 mask 裁剪，依赖预览生成时
       缓存的 region_id_map，完全不会污染组外或同色其他区域。
    2. ``region_bbox`` — clip the highlight to a rectangular region. This is
       a cheap legacy fallback for clients that don't yet pass region
       identifiers; its accuracy is limited to the region's bounding box.
       回退模式：按矩形 bbox 裁剪，精度受限于区域外接矩形。

    If neither clipping field is provided, the highlight covers every
    matching pixel on the whole canvas.
    若两个裁剪字段都未提供，则在整张预览上高亮所有匹配像素。

    Attributes:
        session_id: Active session identifier. (Session ID)
        color_hexes: List of hex color strings to highlight (with or without '#' prefix).
            要高亮的颜色 hex 列表（可带或不带 '#' 前缀）。
        gradient_group_index: Optional 1-based group index from the gradient-groups
            analysis. Must be combined with ``gradient_region_index``.
            渐变分组编号（1-based），与 ``gradient_region_index`` 成对使用。
        gradient_region_index: Optional 1-based sub-region index inside the
            identified gradient group.
            渐变分组内子区域编号（1-based）。
        region_bbox: Optional ``[x0, y0, x1, y1]`` (inclusive-exclusive in
            pixel coordinates) fallback rectangle. Ignored when both
            ``gradient_group_index`` and ``gradient_region_index`` are set.
            可选 ``[x0, y0, x1, y1]`` 边界框（像素坐标，x1/y1 开区间）。
            当渐变分组/子区域字段都存在时忽略此字段。
    """

    session_id: str = Field(..., description="Session ID")
    color_hexes: List[str] = Field(..., min_length=1, description="要高亮的颜色 hex 列表")
    gradient_group_index: Optional[int] = Field(
        None,
        ge=1,
        description="可选：渐变分组编号（1-based），与 gradient_region_index 成对使用",
    )
    gradient_region_index: Optional[int] = Field(
        None,
        ge=1,
        description="可选：渐变分组内子区域编号（1-based）",
    )
    region_bbox: Optional[List[int]] = Field(
        None,
        min_length=4,
        max_length=4,
        description="可选 [x0, y0, x1, y1] 边界框（像素坐标），只在该矩形内扫描；当 gradient_group_index/gradient_region_index 给出时被忽略",
    )


class ColorHighlightResponse(BaseModel):
    """Response model for color-based pixel highlighting.
    基于颜色的像素高亮的响应模型。

    Attributes:
        preview_url: URL of the highlighted preview image. (高亮预览图 URL)
    """

    preview_url: str = Field(..., description="高亮预览图 URL")


class SourceColorPickRequest(BaseModel):
    """Request model for resolving a preview pixel's current matched color.
    解析预览像素当前匹配色的请求模型。

    Used by ``POST /api/convert/source-color-pick`` when the Same-color
    selection tool maps a clicked preview coordinate to the colour the user
    currently sees after replacements or recipe overrides.
    用于 ``POST /api/convert/source-color-pick``：同颜色全选点图时，按
    当前预览状态回查点击像素颜色，会跟随替换和自定义配方后的结果。

    Attributes:
        session_id: Active session identifier. (Session ID)
        x: Preview pixel X coordinate (0-indexed). (预览像素 X 坐标)
        y: Preview pixel Y coordinate (0-indexed). (预览像素 Y 坐标)
    """

    session_id: str = Field(..., description="Session ID")
    x: int = Field(..., ge=0, description="预览像素 X 坐标")
    y: int = Field(..., ge=0, description="预览像素 Y 坐标")


class SourceColorPickResponse(BaseModel):
    """Response model for a preview pixel's current matched and quantized colors.
    预览像素对应当前匹配色和量化色的响应模型。

    Attributes:
        source_matched_hex: Current matched colour as ``#rrggbb``.
            当前匹配色，格式为 ``#rrggbb``。字段名为兼容旧前端保留。
        quantized_hex: Quantized source colour at the same pixel as ``#rrggbb``.
            同一像素的量化原色，格式为 ``#rrggbb``。
    """

    source_matched_hex: str = Field(..., description="当前匹配色 (#rrggbb)")
    quantized_hex: str = Field(..., description="量化原色 (#rrggbb)")


class SelectionPoint(BaseModel):
    """One image-space point in a staged selection brush stroke."""

    x: float = Field(..., ge=0, description="预览像素 X 坐标")
    y: float = Field(..., ge=0, description="预览像素 Y 坐标")


class SelectionMutationRequest(BaseModel):
    """Mutate the shared editor selection without changing preview content."""

    session_id: str = Field(..., description="Session ID")
    operation: Literal[
        "point-toggle",
        "point-remove",
        "same-color-toggle",
        "same-color-remove",
        "colors-set",
        "gradient-region-set",
        "color-range-toggle",
        "brush-add",
        "clear",
    ]
    base_selection_revision: int = Field(..., ge=0, description="客户端选区版本")
    content_revision: int = Field(..., ge=0, description="可见区域缓存内容版本")
    x: int | None = Field(None, ge=0)
    y: int | None = Field(None, ge=0)
    color_hex: str | None = None
    color_hexes: list[str] | None = Field(None, max_length=10000)
    gradient_group_index: int | None = Field(None, ge=1)
    gradient_region_index: int | None = Field(None, ge=1)
    color_tolerance: float | None = Field(
        None,
        ge=0,
        le=100,
        description="颜色范围选择的 CIEDE2000 容差 / CIEDE2000 tolerance for colour-range selection",
    )
    brush_radius: float | None = Field(None, gt=0, le=4096)
    brush_points: list[SelectionPoint] = Field(default_factory=list, max_length=10000)
    brush_strokes: list[list[SelectionPoint]] | None = Field(None, max_length=10000)


class SelectionComponentItem(BaseModel):
    label: int
    region_id: str
    color_hex: str
    pixel_count: int
    bbox: list[int]
    anchor: list[int]


class SelectionDocumentResponse(BaseModel):
    """Authoritative shared selection summary and union boundary."""

    selection_revision: int
    content_revision: int
    selected_pixel_count: int
    selected_component_count: int
    selected_color_hexes: list[str] = Field(default_factory=list)
    region_ids: list[str] = Field(default_factory=list)
    components: list[SelectionComponentItem] = Field(default_factory=list)
    contours: list[list[list[float]]] = Field(default_factory=list)
    can_undo: bool = False
    can_redo: bool = False
    brush_hit_component_count: int | None = None
    editor_content_revision: int | None = Field(None, ge=0)


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
    include_preview: bool = Field(
        False,
        description="是否生成高亮预览 PNG；默认 false，仅显式请求时生成",
    )


class RegionDetectResponse(BaseModel):
    """Response model for connected region detection.
    连通区域检测的响应模型。

    Returns the detected region metadata including a unique identifier,
    the region color, pixel count, optional contours, and optionally a
    highlighted preview image URL when ``include_preview`` is true.
    返回检测到的区域元数据，包括唯一标识、区域颜色、像素数量、可选轮廓；
    仅在 ``include_preview`` 为 true 时返回高亮预览图 URL。

    Attributes:
        region_id: Unique identifier for the detected region. (区域唯一标识)
        color_hex: Hex color of the region. (区域颜色 hex)
        pixel_count: Number of pixels in the region. (区域像素数量)
        preview_url: URL of the highlighted preview image when explicitly
            requested, otherwise null. (显式请求时的高亮预览图 URL；默认 null)
    """

    region_id: str = Field(..., description="区域唯一标识")
    color_hex: str = Field(..., description="区域颜色 hex")
    pixel_count: int = Field(..., description="区域像素数量")
    preview_url: str | None = Field(None, description="高亮预览图 URL；默认不生成，可为 null")
    contours: list[list[list[float]]] | None = Field(None, description="区域轮廓坐标（世界坐标 mm），用于 3D 高亮")
    bbox: tuple[int, int, int, int] | None = Field(
        None,
        description="区域像素 bbox: (x, y, width, height)，仅用于诊断和旧客户端兼容，不作为可视选区形状",
    )


class RegionReplaceRequest(BaseModel):
    """Request model for replacing color in a selected connected region.
    替换选中连通区域颜色的请求模型。

    Used by ``POST /api/converter/region-replace`` to replace the colour
    inside a spatially confined mask with a target colour. Supports two
    mask-source modes:

    - **Click-detected region** (legacy). The endpoint reads the mask stored
      by :func:`region_detect` under ``selected_region_mask``. The caller
      must have hit :func:`region_detect` first.
    - **Gradient region** (new). When ``gradient_group_index`` /
      ``gradient_region_index`` are provided, the mask is derived on the
      fly from the cached per-pixel ``gradient_region_id_map``. This lets
      the Gradient Groups panel apply a target colour only inside a single
      banded sub-region, without polluting other regions that happen to
      share the same quantised hex.

    用于 ``POST /api/converter/region-replace``：把一个空间受限 mask 内的
    像素替换为目标色。支持两种 mask 来源：

    - **点击检测的区域**（legacy）：从 session_data["selected_region_mask"]
      读取（需要先调 region-detect）。
    - **渐变区域**（新）：传入 ``gradient_group_index`` /
      ``gradient_region_index`` 时，从缓存的 per-pixel region_id_map
      现场生成 mask。用于"仅在这一个渐变区域内换色"的场景，避免污染
      共用同一量化 hex 的其它区域。

    Exactly one source must be usable: if both gradient indices are given
    together, they take precedence over the click-detected mask.
    两种来源不互斥；传了 gradient 索引时优先用 gradient region mask。

    Attributes:
        session_id: Active session identifier. (Session ID)
        replacement_color: Target replacement color in hex format. (替换目标色 hex)
        gradient_group_index: 1-based gradient group index from the panel.
            When provided alone, the mask covers the entire group ("去海带纹"
            whole-group flatten). When paired with ``gradient_region_index``,
            the mask narrows to a single sub-region.
            渐变分组编号（1 起）。单独传 = 整组 mask；配合
            ``gradient_region_index`` = 单区域 mask。
        gradient_region_index: Optional 1-based region index inside the
            gradient group. Only meaningful when ``gradient_group_index``
            is also provided.
            渐变分组内的区域编号（1 起），仅在同时提供分组编号时生效。
    """

    session_id: str = Field(..., description="Session ID")
    replacement_color: str = Field(..., description="替换目标色 hex")
    gradient_group_index: Optional[int] = Field(
        None,
        description=(
            "1-based gradient group index; pair with gradient_region_index "
            "to restrict replacement to a gradient sub-region."
        ),
    )
    gradient_region_index: Optional[int] = Field(
        None,
        description=(
            "1-based region index inside the gradient group; pair with "
            "gradient_group_index."
        ),
    )
    selection_revision: int | None = Field(
        None,
        ge=0,
        description="统一编辑选区版本；提供时优先使用共享 selection mask",
    )
    operation_id: str | None = Field(None, max_length=128, description="编辑操作 ID")


class RegionReplaceBatchItem(BaseModel):
    """One region-replacement entry inside a batch request.
    批量区域替换中的单条记录。

    Each item defines its own mask source: click coordinates (flood-fill
    on the current visible preview colour) OR gradient group/region indices (mask
    rebuilt from the cached region_id_map) — exactly the same sources as
    the non-batch :class:`RegionReplaceRequest`. Items are applied in
    order so the final preview reflects the cumulative result.
    每条 item 自己定义 mask 来源：点击坐标（按当前可见预览色泛洪填充）或渐变 group/region
    索引（从缓存的 region_id_map 重建 mask），与 :class:`RegionReplaceRequest`
    一致。items 按顺序累积作用到 matched_rgb，最终预览是综合结果。

    Attributes:
        replacement_color: Target replacement color (hex).
        click_x, click_y: Click coordinates for flood-fill mask (legacy
            click-detected path).
        gradient_group_index, gradient_region_index: Gradient mask
            coordinates, see :class:`RegionReplaceRequest`.
    """

    replacement_color: str = Field(..., description="替换目标色 hex")
    click_x: Optional[int] = Field(None, description="Legacy click-detect 的 X 像素坐标")
    click_y: Optional[int] = Field(None, description="Legacy click-detect 的 Y 像素坐标")
    gradient_group_index: Optional[int] = Field(
        None, description="渐变分组编号（1 起），整组或配合 region 使用"
    )
    gradient_region_index: Optional[int] = Field(
        None, description="渐变分组内的区域编号（1 起）"
    )


class RegionReplaceBatchRequest(BaseModel):
    """Request model for batch region-replacement in a single round-trip.
    一次请求里批量执行多个区域替换（PNG + GLB 只渲染 1 次）。

    Used by ``POST /api/convert/region-replace-batch``. Each item in
    ``items`` defines its own mask + replacement target and they are
    applied in order; the server runs the material-matrix sync once, then
    renders the styled PNG and segmented GLB exactly once. Designed for:

    - Multi-select click-detected regions (前端 multi-select 模式).
    - Multi-region gradient flatten batches.

    用于 ``POST /api/convert/region-replace-batch``：每条 item 独立定义
    mask 与目标色，按顺序累积应用；物料矩阵 sync、PNG、GLB 各只跑 1 次。
    覆盖前端"多区域点击"与"批量渐变去海带纹"两种场景。

    Attributes:
        session_id: Active session identifier. (Session ID)
        items: Ordered list of region-replacement entries.
            有序的区域替换条目列表。
    """

    session_id: str = Field(..., description="Session ID")
    items: list[RegionReplaceBatchItem] = Field(
        ..., min_length=1, description="批量区域替换条目列表"
    )
    operation_id: str | None = Field(None, max_length=128, description="编辑操作 ID")


class RegionRequantizeTarget(BaseModel):
    """One gradient-region selector inside a re-quantise request.
    二次量化请求中的单个渐变 region 选择器。

    Attributes:
        gradient_group_index: 1-based gradient group index (matches the
            :class:`GradientGroupsAnalysis` payload returned by
            ``/gradient-groups``).
            渐变分组编号（1 起），对应 ``/gradient-groups`` 返回的 group_index。
        gradient_region_index: 1-based region index inside the group.
            组内区域编号（1 起）。
    """

    gradient_group_index: int = Field(..., ge=1, description="渐变分组编号（1 起）")
    gradient_region_index: int = Field(..., ge=1, description="组内区域编号（1 起）")


class RegionRequantizeRequest(BaseModel):
    """Request model for per-region secondary re-quantisation.
    区域级二次量化请求模型。

    Used by ``POST /api/convert/region-requantize``. For each selected
    gradient region, the server (1) extracts the ORIGINAL source pixels
    inside the region's mask, (2) runs a local K-Means with a dedicated
    ``local_quantize_colors`` palette, and (3) re-matches the locally
    quantised colours through the same material solver the preview used,
    writing the result back into the region.

    This endpoint is scoped to **regions only** (single or multi-select);
    whole-group re-quantisation is intentionally unsupported — use the
    existing ``/region-replace`` whole-group flatten for that. The algorithm
    preserves low-frequency gradients within a region while collapsing
    high-frequency kelp banding.

    用于 ``POST /api/convert/region-requantize``：对每个选中的 region，
    取原图像素 → 用 ``local_quantize_colors`` 做局部 K-Means → 重新走
    管线的材料求解器 → 写回 matched_rgb。仅支持 region 粒度（单选 / 多选），
    不支持整组；整组去海带纹仍走 ``/region-replace``。

    Attributes:
        session_id: Active session identifier. (Session ID)
        targets: Non-empty list of gradient regions to re-quantise.
            至少一个目标 region。
        local_quantize_colors: Per-region k-means cluster count; validated
            against ``[MIN_LOCAL_QUANTIZE_COLORS, MAX_LOCAL_QUANTIZE_COLORS]``
            = ``[12, 256]`` in :mod:`core.gradient_region_requantize`.
            每个 region 独立的 k-means 聚类数，范围 12-256。
    """

    session_id: str = Field(..., description="Session ID")
    targets: list[RegionRequantizeTarget] = Field(
        ..., min_length=1, description="待二次量化的 region 列表（至少 1 个）"
    )
    local_quantize_colors: int = Field(
        ...,
        ge=12,
        le=256,
        description=(
            "每个 region 独立 k-means 聚类数（12-256）。越大保留的色阶越多，"
            "越小越接近 flatten。"
        ),
    )
    operation_id: str | None = Field(None, max_length=128, description="编辑操作 ID")


class ReplacementHistoryRequest(BaseModel):
    """Request model for replacement undo/redo.
    替换历史撤销/重做请求。
    """

    session_id: str = Field(..., description="Session ID")
    action: Literal["undo", "redo"] = Field(..., description="历史操作：undo 或 redo")
    operation_id: str | None = Field(None, max_length=128, description="编辑操作 ID")


class ReplacementHistoryResponse(BaseModel):
    """Response model for replacement undo/redo.
    替换历史撤销/重做响应。
    """

    status: str = Field("ok", description="操作状态")
    action: Literal["undo", "redo"] = Field(..., description="执行的历史操作")
    label: str | None = Field(None, description="被恢复的 checkpoint 标签")
    entry_kind: Literal["content", "selection"] = Field(
        "content", description="恢复的是内容操作还是选区操作"
    )
    selection: SelectionDocumentResponse | None = Field(
        None, description="恢复选区操作后的当前选区摘要"
    )
    message: str = Field("Replacement history restored", description="操作结果消息")
    preview_url: str = Field(..., description="恢复后的预览图 URL")
    preview_glb_url: str | None = Field(None, description="异步 GLB URL；通常为 null")
    can_undo: bool = Field(False, description="是否还可撤销")
    can_redo: bool = Field(False, description="是否还可重做")
    replacement_regions: list[dict] = Field(default_factory=list, description="当前颜色替换记录")
    recipe_overrides: list[dict] = Field(default_factory=list, description="当前区域配方覆盖")
    recipe_override_count: int = Field(0, description="区域配方覆盖数量")
    region_replacement_count: int = Field(0, description="区域级像素修改次数")
    color_layers: int | None = Field(None, description="当前颜色层数")
    layer_height_mm: float | None = Field(None, description="当前层高")
    gradient_groups: Optional[List["GradientGroupItem"]] = Field(None, description="当前渐变分组")
    free_color_set: list[str] = Field(default_factory=list, description="恢复后的自由色集合")
    operation_id: str | None = None
    editor_content_revision: int | None = Field(None, ge=0)


class RegionReplaceResponse(DynamicMaterialResultResponse):
    """Response model for region color replacement.
    区域颜色替换的响应模型。

    Returns the preview image URL after replacement, an optional GLB URL
    for refreshing the 3D preview, and an operation message.
    返回替换后的预览图 URL、可选的 GLB URL（用于刷新 3D 预览）和操作结果消息。

    Attributes:
        preview_url: URL of the post-replacement preview image. (替换后预览图 URL)
        preview_glb_url: URL of the regenerated segmented GLB. (重新生成的分段 GLB URL)
        message: Operation result message. (操作结果消息)
        gradient_groups: Refreshed gradient-banding analysis payload, when
            the endpoint re-ran :func:`analyze_gradient_groups`. Only
            populated by endpoints that mutate ``matched_rgb`` enough to
            shift the gradient segmentation (e.g. ``/region-requantize``);
            endpoints that only rewrite a fixed colour leave this ``None``
            so existing clients continue to use the cached groups.
            当端点重新分析了渐变分组时返回的新分组负载；像素改动剧烈的
            端点（如 ``/region-requantize``）会填充此字段，其它仅换固定
            hex 的端点留空，保持老客户端兼容。
    """

    preview_url: str = Field(..., description="替换后预览图 URL")
    preview_glb_url: Optional[str] = Field(None, description="重新生成的分段 GLB URL")
    color_contours: Optional[dict] = Field(None, description="更新后的颜色轮廓数据")
    message: str = Field("Region replaced", description="操作结果消息")
    can_undo: bool = Field(False, description="是否可撤销颜色调整")
    can_redo: bool = Field(False, description="是否可重做颜色调整")
    gradient_groups: Optional[List["GradientGroupItem"]] = Field(
        None,
        description=(
            "更新后的渐变分组（仅在端点重跑了 gradient-group 分析时提供）"
        ),
    )
    selection: Optional[SelectionDocumentResponse] = Field(
        None,
        description="共享选区换色后的权威选区状态（仅 selection mask 路径返回）",
    )


class CleanupSessionFilesRequest(BaseModel):
    """Request model for cleaning up intermediate files after download.
    下载后清理中间文件的请求模型。

    Attributes:
        session_id: Active session identifier. (Session ID)
        keep_file_ids: File IDs to preserve (e.g. the downloaded 3MF).
            要保留的文件 ID 列表（如已下载的 3MF）。
    """

    session_id: str = Field(..., description="Session ID")
    keep_file_ids: List[str] = Field(default_factory=list, description="保留的文件 ID")


class CleanupSessionFilesResponse(BaseModel):
    """Response model for session file cleanup.
    Session 文件清理的响应模型。

    Attributes:
        status: Operation status. (操作状态)
        cleaned: Number of files deleted. (删除的文件数)
    """

    status: str = Field("success")
    cleaned: int = Field(0, description="删除的文件数")


class VectorPreviewRendererRequest(BaseModel):
    """Select the lightweight browser renderer for an active Vector session.

    为当前 Vector session 选择浏览器轻量预览 renderer。
    """

    session_id: str = Field(..., min_length=1, description="Session ID")
    enable_smooth_vector_preview: bool = Field(
        True,
        description="Use analytic SVG polygons for the browser GLB preview.",
    )


class VectorPreviewRendererResponse(BaseModel):
    """Pending state returned after scheduling a renderer-only rebuild.

    仅重建 renderer 后返回的 pending 状态。
    """

    session_id: str
    status: Literal["pending"] = "pending"
    job_token: str
    glb_url: None = None
    renderer: Literal["vector_analytic", "segmented"]


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


# ========== Gradient group (banding) analysis ==========


class GradientMaterialColour(BaseModel):
    """A material colour that contributes to a gradient group or region.
    构成渐变组或区域的单个耗材色。
    """

    hex: str = Field(..., description="耗材色 hex，形如 #RRGGBB")
    rgb: List[int] = Field(..., min_length=3, max_length=3, description="RGB 值 (0-255)")
    pixel_count: int = Field(..., ge=0, description="该耗材色在本作用域的像素数")


class GradientRegionItem(BaseModel):
    """A connected spatial region inside a gradient group.
    渐变大分组内一个空间连通区域。
    """

    region_index: int = Field(..., ge=1, description="1 起始的区域编号（按像素数降序）")
    pixel_count: int = Field(..., ge=0, description="区域像素数")
    bbox: List[int] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="边界框 [x0, y0, x1, y1]（像素坐标，x1/y1 开区间）",
    )
    centroid: List[float] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="质心 [cx, cy]，像素坐标",
    )
    material_breakdown: List[GradientMaterialColour] = Field(
        ..., description="区域内耗材色按像素数降序列表"
    )


class GradientGroupItem(BaseModel):
    """A gradient cluster of material colours caused by quantisation banding.
    由量化海带纹造成的一个耗材色渐变聚类。
    """

    group_index: int = Field(..., ge=1, description="1 起始的分组编号（按像素数降序）")
    total_pixel_count: int = Field(..., ge=0, description="分组总像素数")
    material_colour_count: int = Field(..., ge=2, description="分组内耗材色数（>= 2）")
    material_colours: List[GradientMaterialColour] = Field(
        ..., description="分组内耗材色按像素数降序列表"
    )
    representative_hex: str = Field(
        ..., description="分组代表色（默认为像素数最多的那一个）"
    )
    representative_rgb: List[int] = Field(
        ..., min_length=3, max_length=3, description="代表色 RGB"
    )
    boundary_pair_count: int = Field(
        ..., ge=0, description="分组内部认定为海带纹的相邻对数量"
    )
    regions: List[GradientRegionItem] = Field(
        ..., description="分组内空间连通区域列表（按像素数降序）"
    )


class GradientGroupsResponse(BaseModel):
    """Response model for the gradient-groups GET endpoint.
    渐变分组查询端点的响应模型。
    """

    session_id: str = Field(..., description="Session ID")
    status: str = Field("ok", description="'ok' / 'pending' / 'unavailable'")
    groups: List[GradientGroupItem] = Field(
        default_factory=list, description="渐变组列表（按像素数降序）"
    )


# Resolve the forward reference ``RegionReplaceResponse.gradient_groups: Optional[List['GradientGroupItem']]``
# now that :class:`GradientGroupItem` is defined above. Without an explicit
# rebuild Pydantic v2 raises at first validation instead of at import time,
# which makes stacktraces harder to diagnose.
# 在 GradientGroupItem 定义完成后强制 rebuild 以解析 forward 引用，
# 避免 Pydantic v2 首次校验时才报错、掩盖真实 import 顺序问题。
RegionReplaceResponse.model_rebuild()
EditorCommitResult.model_rebuild()
