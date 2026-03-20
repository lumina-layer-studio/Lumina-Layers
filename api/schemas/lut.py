"""LUT Manager domain Pydantic schemas.
LUT 管理领域的 Pydantic 数据模型。

This module defines request and response models for the LUT merge API,
including merge parameters, merge statistics, and LUT info queries.
本模块定义 LUT 合并 API 的请求和响应模型，
包括合并参数、合并统计信息和 LUT 信息查询。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ========== Models ==========


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
