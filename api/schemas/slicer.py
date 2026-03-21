"""Slicer domain Pydantic schemas.
Slicer 领域的 Pydantic 数据模型定义。

This module defines request and response models for the slicer detection
and launch API, including slicer info, detection response, launch request,
and launch response.
本模块定义切片软件检测与启动 API 的请求和响应模型，
包括切片软件信息、检测响应、启动请求和启动响应。
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator


class SlicerInfo(BaseModel):
    """Information about a detected slicer application.
    已检测到的切片软件信息。

    Attributes:
        id: Slicer identifier, e.g. "bambu_studio".
            切片软件标识符。
        display_name: Human-readable display name, e.g. "Bambu Studio".
            显示名称。
        exe_path: Absolute path to the slicer executable.
            可执行文件路径。
    """

    id: str = Field(..., min_length=1, description="切片软件标识符")
    display_name: str = Field(..., description="显示名称")
    exe_path: str = Field(..., description="可执行文件路径")


class SlicerDetectResponse(BaseModel):
    """Response model for slicer detection endpoint.
    切片软件检测端点的响应模型。

    Attributes:
        slicers: List of all detected slicer applications.
            已检测到的切片软件列表。
    """

    slicers: List[SlicerInfo] = Field(default_factory=list, description="已检测切片软件列表")


class SlicerLaunchRequest(BaseModel):
    """Request model for launching a slicer with a file.
    启动切片软件打开文件的请求模型。

    Attributes:
        slicer_id: Identifier of the slicer to launch.
            要启动的切片软件 ID。
        file_path: Path to the 3MF file to open.
            要打开的 3MF 文件路径。
    """

    slicer_id: str = Field(..., description="要启动的切片软件 ID")
    file_path: str = Field(..., min_length=1, description="要打开的 3MF 文件路径")


class SlicerLaunchResponse(BaseModel):
    """Response model for slicer launch endpoint.
    切片软件启动端点的响应模型。

    Attributes:
        status: Result status, either "success" or "error".
            结果状态，"success" 或 "error"。
        message: Descriptive message about the launch result.
            描述信息。
    """

    status: str = Field(..., description="结果状态 (success / error)")
    message: str = Field(..., description="描述信息")
