"""Extractor domain Pydantic schemas and enums.
Extractor 领域的 Pydantic 数据模型与枚举定义。

This module defines all request models for the color extraction API,
including calibration board scanning and manual LUT cell correction.
本模块定义颜色提取 API 的所有请求模型，
包括校准板扫描和手动 LUT 单元格校正。
"""

from __future__ import annotations

from enum import Enum
from typing import List, Tuple

from pydantic import BaseModel, Field

from api.schemas.lut import PaletteEntrySchema

# ========== Enums ==========


class CalibrationColorMode(str, Enum):
    """Color mode for calibration and extraction.
    校准与提取的颜色模式。

    Attributes:
        BW: Black & White grayscale mode (32 levels).
            黑白灰度模式 (32 级)。
        FOUR_COLOR_CMYW: 4-Color CMYW mode (1024 colors).
            4 色 CMYW 模式 (1024 色)。
        FOUR_COLOR_RYBW: 4-Color RYBW mode (1024 colors).
            4 色 RYBW 模式 (1024 色)。
        FIVE_COLOR_EXT: 5-Color Extended mode (1444 colors).
            5 色扩展模式 (1444 色)。
        SIX_COLOR: 6-Color extended smart mode (1296 colors).
            6 色扩展智能模式 (1296 色)。
        EIGHT_COLOR: 8-Color professional mode (2738 colors).
            8 色专业模式 (2738 色)。
    """

    BW = "BW (Black & White)"
    FOUR_COLOR_CMYW = "4-Color (CMYW)"
    FOUR_COLOR_RYBW = "4-Color (RYBW)"
    FIVE_COLOR_EXT = "5-Color Extended (1444)"
    SIX_COLOR = "6-Color (Smart 1296)"
    SIX_COLOR_RYBW = "6-Color (RYBW 1296)"
    EIGHT_COLOR = "8-Color Max"


class ExtractorPage(str, Enum):
    """Page selector for 8-Color two-page calibration workflow.
    8 色双页校准流程的页码选择器。

    Attributes:
        PAGE_1: First calibration page.
            第一页。
        PAGE_2: Second calibration page.
            第二页。
    """

    PAGE_1 = "Page 1"
    PAGE_2 = "Page 2"


# ========== Models ==========


class ExtractorExtractRequest(BaseModel):
    """Request model for extracting colors from a photographed calibration board.
    从拍摄的校准板照片中提取颜色的请求模型。

    Used by ``POST /api/extractor/extract`` to perform perspective correction
    and color sampling on a calibration board image.
    用于 ``POST /api/extractor/extract``，对校准板照片执行透视校正和颜色采样。

    Attributes:
        color_mode: Calibration color system mode.
            校准颜色模式。
        corner_points: Four corner coordinates for perspective correction [(x, y), ...].
            4 个角点坐标 [(x, y), ...]。
        offset_x: Horizontal sampling offset in pixels.
            水平采样偏移 (px)。
        offset_y: Vertical sampling offset in pixels.
            垂直采样偏移 (px)。
        zoom: Perspective correction zoom factor.
            透视校正缩放。
        distortion: Lens distortion correction factor.
            畸变校正。
        vignette_correction: Whether to apply vignette correction.
            暗角校正。
        page: Page number for 8-Color two-page workflow.
            8-Color 页码。
    """

    color_mode: CalibrationColorMode = Field(CalibrationColorMode.FOUR_COLOR_RYBW, description="校准颜色模式")
    corner_points: List[Tuple[int, int]] = Field(
        ..., min_length=4, max_length=4, description="4 个角点坐标 [(x,y), ...]"
    )
    offset_x: int = Field(0, ge=-30, le=30, description="水平采样偏移 (px)")
    offset_y: int = Field(0, ge=-30, le=30, description="垂直采样偏移 (px)")
    zoom: float = Field(1.0, ge=0.8, le=1.2, description="透视校正缩放")
    distortion: float = Field(0.0, ge=-0.2, le=0.2, description="畸变校正")
    vignette_correction: bool = Field(False, description="暗角校正")
    page: ExtractorPage = Field(ExtractorPage.PAGE_1, description="8-Color 页码")


class ExtractorManualFixRequest(BaseModel):
    """Request model for manually overriding a single LUT cell color.
    手动覆盖单个 LUT 单元格颜色的请求模型。

    Used by ``POST /api/extractor/manual-fix`` to correct an incorrectly
    extracted color value in the LUT.
    用于 ``POST /api/extractor/manual-fix``，校正 LUT 中提取错误的颜色值。

    Attributes:
        lut_path: File path to the LUT being edited.
            LUT 文件路径。
        cell_coord: Cell coordinates as (row, col) in the LUT grid.
            单元格坐标 (row, col)。
        override_color: Replacement color value in hex format.
            覆盖颜色 (hex)。
    """

    lut_path: str = Field("", description="LUT 文件路径 (可选，优先使用 session_id 查找)")
    session_id: str = Field("", description="Session ID (用于查找 LUT 路径)")
    cell_coord: Tuple[int, int] = Field(..., description="单元格坐标 (row, col)")
    override_color: str = Field(..., description="覆盖颜色 (hex)")


class ConfirmPaletteRequest(BaseModel):
    """Request model for confirming user palette after extraction.
    调色板确认请求模型。

    Used by ``POST /api/extractor/confirm-palette`` to submit the
    user-confirmed palette data to the session.
    用于 ``POST /api/extractor/confirm-palette``，提交用户确认的调色板数据。

    Attributes:
        session_id: Extraction session ID. (提取会话 ID)
        palette: User-confirmed palette entries. (用户确认的调色板数组)
    """

    session_id: str = Field(..., description="提取会话 ID")
    palette: list[PaletteEntrySchema] = Field(..., min_length=1, description="用户确认的调色板数组")
