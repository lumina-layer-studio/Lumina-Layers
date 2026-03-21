"""Calibration domain Pydantic schemas and enums.
Calibration 领域的 Pydantic 数据模型与枚举定义。

This module defines the request model for calibration board generation,
including backing color options and block sizing parameters.
本模块定义校准板生成 API 的请求模型，
包括底板颜色选项和色块尺寸参数。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from api.schemas.extractor import CalibrationColorMode


# ========== Enums ==========


class BackingColor(str, Enum):
    """Backing plate color for calibration board generation.
    校准板底板颜色。

    Attributes:
        WHITE: White backing plate.
            白色底板。
        CYAN: Cyan backing plate.
            青色底板。
        MAGENTA: Magenta backing plate.
            品红色底板。
        YELLOW: Yellow backing plate.
            黄色底板。
        RED: Red backing plate.
            红色底板。
        BLUE: Blue backing plate.
            蓝色底板。
    """

    WHITE = "White"
    CYAN = "Cyan"
    MAGENTA = "Magenta"
    YELLOW = "Yellow"
    RED = "Red"
    BLUE = "Blue"


# ========== Models ==========


class CalibrationGenerateRequest(BaseModel):
    """Request model for generating a calibration board.
    生成校准板的请求模型。

    Used by ``POST /api/calibration/generate`` to create a printable
    calibration board with specified color mode, block size, and spacing.
    用于 ``POST /api/calibration/generate``，按指定颜色模式、色块尺寸和间距
    生成可打印的校准板。

    Attributes:
        color_mode: Calibration color system mode.
            校准颜色模式。
        block_size: Block size in millimeters (3-10).
            色块尺寸 (mm)。
        gap: Gap between blocks in millimeters (0.4-2.0).
            色块间距 (mm)。
        backing: Backing plate color.
            底板颜色。
    """

    color_mode: CalibrationColorMode = Field(
        CalibrationColorMode.FOUR_COLOR, description="校准颜色模式"
    )
    block_size: int = Field(5, ge=3, le=10, description="色块尺寸 (mm)")
    gap: float = Field(0.82, ge=0.4, le=2.0, description="色块间距 (mm)")
    backing: BackingColor = Field(
        BackingColor.WHITE, description="底板颜色"
    )
