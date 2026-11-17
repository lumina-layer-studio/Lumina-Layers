"""LUT Manager domain Pydantic schemas.
LUT 管理领域的 Pydantic 数据模型。

This module defines request and response models for the LUT merge API,
including merge parameters, merge statistics, and LUT info queries.
本模块定义 LUT 合并 API 的请求和响应模型，
包括合并参数、合并统计信息和 LUT 信息查询。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ========== Models ==========


class PaletteEntrySchema(BaseModel):
    """Palette entry schema for API responses.
    调色板条目 Schema。

    Attributes:
        color: Color name, e.g. "Red", "Cyan". (颜色名称)
        material: Material name. (材料名称)
        hex_color: Optional hex color value, e.g. "#FF0000". (十六进制颜色值)
        color_name: Optional manufacturer-provided display name. (厂商颜色名称)
    """

    color: str = Field(..., description="颜色名称，如 Red、Cyan")
    material: str = Field("PLA Basic", description="材料名称")
    hex_color: str | None = Field(None, description="十六进制颜色值，如 #FF0000")
    color_name: str | None = Field(None, description="厂商提供的颜色名称")


class LutCatalogItem(BaseModel):
    """Single catalog item for legacy LUT sources.
    经典 LUT 源的单条目录项。
    """

    name: str = Field(..., description="LUT 显示名称")
    color_mode: str = Field(..., description="颜色模式")
    path: str = Field(..., description="公开引用（非本机文件系统路径）")


class LutCatalogGroup(BaseModel):
    """Grouped legacy LUT catalog entries.
    分组后的经典 LUT 目录。
    """

    group_name: str = Field(..., description="分组名称")
    items: list[LutCatalogItem] = Field(default_factory=list, description="分组条目")


class NativeDbOption(BaseModel):
    """One native ColorDB option exposed in the source catalog.
    原生 ColorDB 目录中的单个可选项。
    """

    name: str = Field(..., description="DB 文件名")
    path: str = Field(..., description="公开引用（非本机文件系统路径）")
    color_mode: str = Field(..., description="颜色模式")


class NativeBrandCatalogGroup(BaseModel):
    """Native source catalog entry grouped by vendor/material.
    按厂商/材料分组的原生源目录项。
    """

    brand_key: str = Field(..., description="品牌键")
    material_type: str = Field(..., description="材料类型")
    vendor: str = Field(..., description="厂商")
    display_name: str = Field(..., description="显示名称")
    db_options: list[NativeDbOption] = Field(default_factory=list, description="可选 DB 列表")
    default_db_names: list[str] = Field(default_factory=list, description="默认 DB 名称列表")
    package_name: str | None = Field(None, description="同范围模型包文件名")
    model_name: str | None = Field(None, description="同范围前向模型文件名")
    supported_modes: list[dict[str, Any]] = Field(default_factory=list, description="支持的模式列表")


class LutSourceCatalogResponse(BaseModel):
    """Source catalog response containing legacy and native selections.
    同时包含传统源和原生品牌分组的目录响应。
    """

    legacy_groups: list[LutCatalogGroup] = Field(default_factory=list, description="经典 LUT 分组")
    legacy_aliases: dict[str, str] = Field(default_factory=dict)
    native_brand_groups: list[NativeBrandCatalogGroup] = Field(default_factory=list, description="原生品牌分组")


class LocalLutVersion(BaseModel):
    current: bool
    installed_at: str | None = None


class LutDetailsCatalogItem(BaseModel):
    """Indexed item for the LUT details catalog.
    LUT 详情目录中的索引条目。
    """

    name: str = Field(..., description="LUT 详情显示名称")
    display: dict[str, Any] | None = None
    path: str = Field(..., description="公开引用（非本机文件系统路径）")
    color_mode: str = Field(..., description="颜色模式")
    source_kind: str = Field("legacy_lookup", description="来源类型")
    compatibility_key: str = Field("", description="legacy_multi 兼容分组键")
    manufacturer: str = Field(..., description="解析后的厂商")
    material_type: str = Field("", description="解析后的材质")
    manufacturer_source: str = Field(..., description="厂商解析来源")
    material_source: str = Field(..., description="材质解析来源")
    search_tokens: list[str] = Field(default_factory=list, description="预计算搜索 token")
    revision: str = Field("", description="目录读取代次，更新时重新加载详情")
    local_version: LocalLutVersion | None = None


class LutDetailsCatalogGroup(BaseModel):
    """Manufacturer-grouped LUT details catalog bucket.
    按厂商分组的 LUT 详情目录桶。
    """

    manufacturer: str = Field(..., description="标准化后的厂商名")
    items: list[LutDetailsCatalogItem] = Field(default_factory=list, description="该厂商下的 LUT 条目")


class LutDetailsCatalogResponse(BaseModel):
    """Grouped LUT details catalog response.
    分组后的 LUT 详情目录响应。
    """

    groups: list[LutDetailsCatalogGroup] = Field(default_factory=list, description="按厂商分组后的目录")


class LutAxisRange(BaseModel):
    """Axis min/max pair for coverage stats.
    覆盖统计的坐标轴范围。
    """

    min: float = Field(..., description="最小值")
    max: float = Field(..., description="最大值")


class LutCoverageStatsResponse(BaseModel):
    """Coverage statistics for LUT detail visualizations.
    LUT 详情可视化的覆盖统计。
    """

    entry_count: int = Field(..., ge=0, description="LUT 条目数量")
    plotted_point_count: int = Field(..., ge=0, description="绘制点数量")
    l_range: LutAxisRange = Field(..., description="Lab L 范围")
    a_range: LutAxisRange = Field(..., description="Lab a 范围")
    b_range: LutAxisRange = Field(..., description="Lab b 范围")
    r_range: LutAxisRange = Field(..., description="RGB R 范围")
    g_range: LutAxisRange = Field(..., description="RGB G 范围")
    b_rgb_range: LutAxisRange = Field(..., description="RGB B 范围")


class LutPlotPoint(BaseModel):
    """Plot point for LUT details charts.
    LUT 详情图表中的散点。
    """

    x: float = Field(..., description="X 坐标")
    y: float = Field(..., description="Y 坐标")
    hex_color: str = Field(..., description="点的十六进制颜色")
    rgb: list[int] = Field(..., min_length=3, max_length=3, description="点的 RGB 值")
    label: str = Field(..., description="点标签")


class LutPlotPoint3D(BaseModel):
    """3D plot point for LUT details charts.
    LUT 详情 3D 图表中的散点。
    """

    l: float = Field(..., description="L* 坐标")
    a: float = Field(..., description="a* 坐标")
    b: float = Field(..., description="b* 坐标")
    hex_color: str = Field(..., description="点的十六进制颜色")
    rgb: list[int] = Field(..., min_length=3, max_length=3, description="点的 RGB 值")
    label: str = Field(..., description="点标签")


class LutHullPoint(BaseModel):
    """Hull polygon point for Lab coverage region.
    Lab 覆盖区域凸包点。
    """

    x: float = Field(..., description="X 坐标")
    y: float = Field(..., description="Y 坐标")


class LutDetailsResponse(BaseModel):
    """Detailed LUT metadata and visualization payload.
    LUT 详细元数据与可视化载荷。
    """

    name: str = Field(..., description="LUT 名称")
    path: str = Field(..., description="公开引用（非本机文件系统路径）")
    manufacturer: str = Field(..., description="解析后的厂商")
    manufacturer_source: str = Field(..., description="厂商解析来源")
    material_type: str = Field("", description="解析后的材质")
    material_source: str = Field(..., description="材质解析来源")
    color_mode: str = Field(..., description="颜色模式")
    color_count: int = Field(..., ge=0, description="颜色数量")
    source_kind: str = Field("legacy_lookup", description="来源类型")
    schema_version: str = Field("1.0", description="Schema 版本")
    capabilities: list[str] = Field(default_factory=list, description="能力列表")
    supported_modes: list[dict[str, Any]] = Field(default_factory=list, description="支持的模式列表")
    raw_metadata: dict[str, Any] = Field(default_factory=dict, description="安全裁剪后的原始元数据")
    palette: list[PaletteEntrySchema] = Field(default_factory=list, description="调色板")
    coverage_stats: LutCoverageStatsResponse = Field(..., description="覆盖统计")
    lab_points: list[LutPlotPoint] = Field(default_factory=list, description="Lab 散点图点集")
    lab_points_3d: list[LutPlotPoint3D] = Field(default_factory=list, description="Lab 3D 散点图点集")
    lab_hull: list[LutHullPoint] = Field(default_factory=list, description="Lab 凸包点集")
    rgb_points: list[LutPlotPoint] = Field(default_factory=list, description="RGB 投影视图点集")
    max_color_layers: int = Field(5, description="最大颜色层数")
    layer_height_mm: float = Field(0.08, description="层高 (mm)")
    line_width_mm: float = Field(0.42, description="线宽 (mm)")
    base_layers: int = Field(10, description="底板层数")
    base_channel_idx: int = Field(0, description="底板通道索引")
    layer_order: str = Field("Top2Bottom", description="打印顺序")


class LutSourceSelection(BaseModel):
    """Shared LUT source selection contract.
    LUT 源选择共享契约。
    """

    source_kind: Literal["legacy_single", "legacy_multi", "native_bundle"] = Field(
        "legacy_single",
        description="源类型：legacy_single | legacy_multi | native_bundle",
    )
    lut_name: str | None = Field(None, description="经典 LUT 名称")
    lut_names: list[str] = Field(default_factory=list, description="经典 LUT 名称列表")
    material_type: str | None = Field(None, description="原生材料类型")
    vendor: str | None = Field(None, description="原生厂商")
    db_names: list[str] = Field(default_factory=list, description="原生 DB 文件名列表")

    @field_validator("lut_names", mode="before")
    @classmethod
    def normalize_lut_names(cls, value: object) -> list[str]:
        """Normalize legacy LUT name lists from JSON and form-compatible shapes.
        规范化 JSON/form 兼容形态的经典 LUT 名称列表。
        """

        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "lut_names must be a list of strings, JSON array string, or comma-separated string"
                    ) from exc
                if not isinstance(parsed, list):
                    raise ValueError(
                        "lut_names must be a list of strings, JSON array string, or comma-separated string"
                    )
                value = parsed
            else:
                return [item.strip() for item in stripped.split(",") if item.strip()]

        if isinstance(value, (list, tuple)):
            normalized: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    raise ValueError("lut_names entries must be strings")
                stripped_item = item.strip()
                if stripped_item:
                    normalized.append(stripped_item)
            return normalized

        raise ValueError(
            "lut_names must be a list of strings, JSON array string, or comma-separated string"
        )

    @model_validator(mode="after")
    def validate_source_selection(self) -> "LutSourceSelection":
        """Validate the source selection contract.
        校验源选择契约。
        """

        if self.source_kind == "legacy_single":
            if not self.lut_name:
                raise ValueError("legacy_single requires lut_name")
            return self

        if self.source_kind == "legacy_multi":
            normalized: list[str] = []
            for name in ([self.lut_name] if self.lut_name else []) + list(self.lut_names or []):
                clean_name = str(name).strip()
                if clean_name and clean_name not in normalized:
                    normalized.append(clean_name)
            if not normalized:
                raise ValueError("legacy_multi requires lut_names or lut_name")
            self.lut_names = normalized
            self.lut_name = normalized[0]
            return self

        if self.source_kind == "native_bundle":
            if not self.material_type or not self.vendor:
                raise ValueError("native_bundle requires material_type and vendor")
            if not self.db_names:
                raise ValueError("native_bundle requires at least one db_names entry")
            return self

        raise ValueError(f"Unsupported source_kind: {self.source_kind}")


class MergeStats(BaseModel):
    """Statistics from a LUT merge operation.
    LUT 合并操作的统计信息。

    Attributes:
        total_before: Total color count across all input LUTs before merging.
            合并前所有输入 LUT 的总颜色数。
        total_after: Color count in the merged result after deduplication.
            去重后合并结果的颜色数。
        exact_dupes: Number of exact duplicate colors removed.
            精确去重移除的颜色数。
        similar_removed: Number of perceptually similar colors removed by Delta-E threshold.
            通过 Delta-E 阈值移除的相近颜色数。
    """

    total_before: int = Field(..., description="合并前总颜色数")
    total_after: int = Field(..., description="合并后颜色数")
    exact_dupes: int = Field(..., description="精确去重数")
    similar_removed: int = Field(..., description="相近色去除数")


class MergeRequest(BaseModel):
    """Request model for merging multiple LUTs.
    合并多个 LUT 的请求模型。

    Used by ``POST /api/lut/merge`` to execute a LUT merge operation
    with a primary LUT, one or more secondary LUTs, and a deduplication
    threshold.
    用于 ``POST /api/lut/merge``，执行 LUT 合并操作，
    包含主 LUT、一个或多个辅助 LUT 和去重阈值。

    Attributes:
        primary_name: Display name of the primary LUT.
            主 LUT 显示名称。
        secondary_names: Display names of secondary LUTs to merge.
            辅助 LUT 显示名称列表。
        dedup_threshold: Delta-E threshold for removing perceptually similar colors.
            Delta-E 去重阈值（0 = 仅精确去重，值越大去除越多相近色）。
    """

    primary_name: str = Field(..., description="主 LUT 显示名称")
    secondary_names: list[str] = Field(..., description="辅助 LUT 显示名称列表")
    dedup_threshold: float = Field(
        3.0, ge=0.0, le=20.0, description="Delta-E 去重阈值"
    )


class MergeResponse(BaseModel):
    """Response model for a completed LUT merge operation.
    LUT 合并操作完成后的响应模型。

    Returned by ``POST /api/lut/merge`` on success, containing the
    output filename and detailed merge statistics.
    由 ``POST /api/lut/merge`` 成功时返回，包含输出文件名和详细合并统计。

    Attributes:
        status: Operation result status (e.g. ``"success"``).
            操作状态。
        message: Human-readable result message.
            结果描述信息。
        filename: Display name of the newly created merged LUT file.
            新创建的合并 LUT 文件显示名称。
        stats: Detailed merge statistics.
            合并统计信息。
    """

    status: str = Field(..., description="操作状态")
    message: str = Field(..., description="结果描述信息")
    filename: str = Field(..., description="合并 LUT 文件显示名称")
    stats: MergeStats = Field(..., description="合并统计信息")
    palette: list[PaletteEntrySchema] = Field(default_factory=list, description="合并后调色板")
    warnings: list[str] = Field(default_factory=list, description="打印参数兼容性警告列表")


class CompareDiffItem(BaseModel):
    """Single same-recipe comparison item.
    单条同配方对比结果。

    Attributes:
        recipe: Canonical recipe tokens for this shared stack. (标准化后的配方标记)
        rgb_a: RGB from LUT A. (LUT A 的 RGB)
        rgb_b: RGB from LUT B. (LUT B 的 RGB)
        hex_a: Hex color for LUT A. (LUT A 的十六进制颜色)
        hex_b: Hex color for LUT B. (LUT B 的十六进制颜色)
        delta_e00: Perceptual color difference under CIEDE2000. (CIEDE2000 感知色差)
    """

    recipe: list[str] = Field(..., description="共享配方的标准化标记列表")
    rgb_a: list[int] = Field(..., min_length=3, max_length=3, description="LUT A 的 RGB")
    rgb_b: list[int] = Field(..., min_length=3, max_length=3, description="LUT B 的 RGB")
    hex_a: str = Field(..., description="LUT A 的十六进制颜色")
    hex_b: str = Field(..., description="LUT B 的十六进制颜色")
    delta_e00: float = Field(..., ge=0.0, description="该共享配方的 CIEDE2000 色差")


class CompareStats(BaseModel):
    """Statistics from same-recipe LUT comparison.
    同配方 LUT 对比统计信息。

    Attributes:
        matched_recipe_count: Shared recipe count between two LUTs. (共享配方数量)
        recipe_coverage_a: Shared recipe coverage over LUT A. (LUT A 共享配方覆盖率)
        recipe_coverage_b: Shared recipe coverage over LUT B. (LUT B 共享配方覆盖率)
        mean_delta_e00: Mean Delta-E over shared recipes. (共享配方平均 Delta-E)
        median_delta_e00: Median Delta-E over shared recipes. (共享配方中位数 Delta-E)
        p95_delta_e00: 95th percentile Delta-E. (95 分位 Delta-E)
        max_delta_e00: Maximum Delta-E. (最大 Delta-E)
        identical_rgb_count: Shared recipes whose RGB values are exactly identical.
            (RGB 完全一致的共享配方数量)
        recipes_only_in_a: Recipes only present in LUT A. (仅存在于 LUT A 的配方数量)
        recipes_only_in_b: Recipes only present in LUT B. (仅存在于 LUT B 的配方数量)
    """

    matched_recipe_count: int = Field(..., ge=0, description="共享配方数量")
    recipe_coverage_a: float = Field(..., ge=0.0, le=1.0, description="LUT A 共享配方覆盖率")
    recipe_coverage_b: float = Field(..., ge=0.0, le=1.0, description="LUT B 共享配方覆盖率")
    mean_delta_e00: float = Field(..., ge=0.0, description="共享配方平均 Delta-E00")
    median_delta_e00: float = Field(..., ge=0.0, description="共享配方中位数 Delta-E00")
    p95_delta_e00: float = Field(..., ge=0.0, description="共享配方 95 分位 Delta-E00")
    max_delta_e00: float = Field(..., ge=0.0, description="共享配方最大 Delta-E00")
    identical_rgb_count: int = Field(..., ge=0, description="RGB 完全一致的共享配方数量")
    recipes_only_in_a: int = Field(..., ge=0, description="仅存在于 LUT A 的配方数量")
    recipes_only_in_b: int = Field(..., ge=0, description="仅存在于 LUT B 的配方数量")


class CompareRequest(BaseModel):
    """Request model for comparing two LUTs by shared recipe.
    按共享配方比较两个 LUT 的请求模型。

    Attributes:
        lut_a_name: Display name of the baseline LUT. (基准 LUT 显示名称)
        lut_b_name: Display name of the comparison LUT. (对比 LUT 显示名称)
        top_n: Max number of worst-difference items to return. (返回的最大差异条目数)
    """

    lut_a_name: str = Field(..., description="基准 LUT 显示名称")
    lut_b_name: str = Field(..., description="对比 LUT 显示名称")
    top_n: int = Field(10, ge=1, le=20, description="返回的最大差异条目数")


class CompareResponse(BaseModel):
    """Response model for same-recipe LUT comparison.
    同配方 LUT 对比结果响应模型。

    Attributes:
        status: Operation status. (操作状态)
        message: Human-readable summary. (结果摘要)
        lut_a_name: Baseline LUT display name. (基准 LUT 显示名称)
        lut_b_name: Comparison LUT display name. (对比 LUT 显示名称)
        lut_a_mode: Detected mode for LUT A. (LUT A 检测模式)
        lut_b_mode: Detected mode for LUT B. (LUT B 检测模式)
        stats: Aggregated comparison metrics. (聚合对比指标)
        warnings: Compatibility or interpretation warnings. (兼容性或解释警告)
        worst_diffs: Top worst same-recipe differences. (最大差异条目列表)
    """

    status: str = Field(..., description="操作状态")
    message: str = Field(..., description="结果摘要")
    lut_a_name: str = Field(..., description="基准 LUT 显示名称")
    lut_b_name: str = Field(..., description="对比 LUT 显示名称")
    lut_a_mode: str = Field(..., description="LUT A 检测模式")
    lut_b_mode: str = Field(..., description="LUT B 检测模式")
    stats: CompareStats = Field(..., description="同配方对比统计")
    warnings: list[str] = Field(default_factory=list, description="兼容性或解释警告")
    worst_diffs: list[CompareDiffItem] = Field(default_factory=list, description="差异最大的共享配方条目")


class LutInfoResponseV2(BaseModel):
    """Extended LUT info response with LUT V2 capability fields."""

    name: str = Field(..., description="LUT 显示名称")
    color_mode: str = Field(..., description="颜色模式")
    color_count: int = Field(..., ge=0, description="颜色数量")
    palette: list[PaletteEntrySchema] = Field(default_factory=list, description="调色板数组")
    max_color_layers: int = Field(5, description="最大颜色层数")
    layer_height_mm: float = Field(0.08, description="层高 (mm)")
    line_width_mm: float = Field(0.42, description="线宽 (mm)")
    base_layers: int = Field(10, description="底板层数")
    base_channel_idx: int = Field(0, description="底板通道索引")
    layer_order: str = Field("Top2Bottom", description="打印顺序")
    schema_version: str = Field("1.0", description="LUT schema 版本")
    capabilities: list[str] = Field(default_factory=list, description="LUT 能力列表")
    supports_predictive_match: bool = Field(False, description="是否支持预测式匹配")
    supports_dynamic_layer_height: bool = Field(False, description="是否支持动态层高")
    supports_dynamic_layer_count: bool = Field(False, description="是否支持动态叠色层数")
    supports_custom_recipe: bool = Field(False, description="是否支持自定义配方")
    source_kind: str = Field("legacy_lookup", description="颜色源类型")
    supported_modes: list[dict] = Field(default_factory=list, description="可用模式列表")

class LutInfoResponse(BaseModel):
    """Response model for LUT information queries.
    LUT 信息查询的响应模型。

    Returned by ``GET /api/lut/{lut_name}/info`` with the detected
    color mode and color count for the specified LUT.
    由 ``GET /api/lut/{lut_name}/info`` 返回，包含指定 LUT 的
    检测到的颜色模式和颜色数量。

    Attributes:
        name: Display name of the LUT.
            LUT 显示名称。
        color_mode: Detected color mode (e.g. ``"8-Color Max"``, ``"BW"``).
            检测到的颜色模式。
        color_count: Number of colors in the LUT.
            LUT 中的颜色数量。
    """

    name: str = Field(..., description="LUT 显示名称")
    color_mode: str = Field(..., description="颜色模式")
    color_count: int = Field(..., ge=0, description="颜色数量")
    palette: list[PaletteEntrySchema] = Field(default_factory=list, description="调色板数组")
    max_color_layers: int = Field(5, description="最大颜色层数")
    layer_height_mm: float = Field(0.08, description="层高 (mm)")
    line_width_mm: float = Field(0.42, description="线宽 (mm)")
    base_layers: int = Field(10, description="底板层数")
    base_channel_idx: int = Field(0, description="底板通道索引")
    layer_order: str = Field("Top2Bottom", description="打印顺序")


class RecipeColorPredictRequest(BaseModel):
    """Predictive source custom recipe color request."""

    recipe: list[int] = Field(..., min_length=1, max_length=20, description="通道索引配方")
    color_layers: int = Field(..., ge=1, le=20, description="叠色层数")
    layer_height_mm: float = Field(..., gt=0.0, le=1.0, description="层高 (mm)")
    layer_order: str = Field("Top2Bottom", description="配方层序")


class RecipeColorPredictResponse(BaseModel):
    """Predicted color response for a custom recipe."""

    status: str = Field(..., description="状态")
    rgb: list[int] = Field(..., min_length=3, max_length=3, description="预测 RGB")
    lab: list[float] = Field(..., min_length=3, max_length=3, description="预测 Lab")
    runtime_mode_key: str = Field(..., description="命中的运行时模式")
    source: str = Field(..., description="预测来源")


class RecipeSearchRequest(BaseModel):
    """Search candidate recipes by a layer pattern."""

    pattern: str = Field(..., description="层序搜索模式")
    color_layers: int = Field(..., ge=1, le=20, description="叠色层数")
    layer_height_mm: float = Field(..., gt=0.0, le=1.0, description="层高 (mm)")
    layer_order: str = Field("Top2Bottom", description="层序约定")
    limit: int = Field(32, ge=1, le=128, description="返回候选数量上限")


class RecipeSearchItem(BaseModel):
    recipe: list[int] = Field(..., description="匹配到的配方")
    rgb: list[int] = Field(..., description="预测 RGB")
    lab: list[float] = Field(..., description="预测 Lab")


class RecipeSearchResponse(BaseModel):
    status: str = Field(..., description="状态")
    runtime_mode_key: str = Field(..., description="命中的运行时模式")
    items: list[RecipeSearchItem] = Field(default_factory=list, description="匹配到的候选配方")
    schema_version: str = Field("1.0", description="LUT schema 版本")
    capabilities: list[str] = Field(default_factory=list, description="LUT 能力列表")
    source_kind: str = Field("legacy_lookup", description="source 类型")
    supported_modes: list[dict] = Field(default_factory=list, description="支持的叠色层数/层高模式")
    supports_predictive_match: bool = Field(False, description="是否支持预测式匹配")
    supports_dynamic_layer_height: bool = Field(False, description="是否支持动态层高")
    supports_dynamic_layer_count: bool = Field(False, description="是否支持动态叠色层数")
    supports_custom_recipe: bool = Field(False, description="是否支持自定义配方")
