"""Five-Color Query — Pydantic 数据模型。
五色组合查询的请求与响应模型定义。
"""

from typing import Optional

from pydantic import BaseModel, Field


class BaseColorEntry(BaseModel):
    """单个基础颜色条目。"""

    index: int = Field(..., description="颜色索引 (0-based)")
    rgb: tuple[int, int, int] = Field(..., description="RGB 值")
    name: str = Field(..., description="颜色名称")
    hex: str = Field(..., description="Hex 颜色代码")


class BaseColorsResponse(BaseModel):
    """基础颜色列表响应。"""

    lut_name: str = Field(..., description="LUT 显示名称")
    color_count: int = Field(..., description="基础颜色数量")
    colors: list[BaseColorEntry] = Field(..., description="基础颜色列表")


class FiveColorQueryRequest(BaseModel):
    """五色组合查询请求。"""

    lut_name: str = Field(..., description="LUT 显示名称")
    selected_indices: list[int] = Field(
        ..., min_length=5, max_length=5, description="5 个颜色索引"
    )


class FiveColorQueryResponse(BaseModel):
    """五色组合查询响应。"""

    found: bool = Field(..., description="是否找到匹配")
    selected_indices: list[int] = Field(..., description="用户选择的索引")
    result_rgb: Optional[tuple[int, int, int]] = Field(None, description="结果 RGB")
    result_hex: Optional[str] = Field(None, description="结果 Hex")
    row_index: int = Field(..., description="Stack LUT 行索引")
    message: str = Field(..., description="状态消息")
    source: str = Field("", description="来源标识")
