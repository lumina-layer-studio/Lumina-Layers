"""Slicer domain API router.
Slicer 领域 API 路由模块 — 切片软件检测与启动端点。
"""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.slicer import (
    SlicerDetectResponse,
    SlicerInfo,
    SlicerLaunchRequest,
    SlicerLaunchResponse,
)
from core.slicer import detect_installed_slicers, launch_slicer

router = APIRouter(prefix="/api/slicer", tags=["Slicer"])


@router.get("/detect")
def detect_slicers() -> SlicerDetectResponse:
    """扫描系统已安装的切片软件。"""
    slicers = detect_installed_slicers()
    return SlicerDetectResponse(
        slicers=[
            SlicerInfo(
                id=s.id,
                display_name=s.display_name,
                exe_path=s.exe_path,
            )
            for s in slicers
        ]
    )


@router.post("/launch")
def launch_slicer_endpoint(request: SlicerLaunchRequest) -> SlicerLaunchResponse:
    """启动切片软件打开指定文件。"""
    # 1) Validate file exists
    if not os.path.isfile(request.file_path):
        return JSONResponse(
            status_code=400,
            content=SlicerLaunchResponse(
                status="error",
                message=f"文件不存在: {request.file_path}",
            ).model_dump(),
        )

    # 2) Get fresh slicer list
    slicers = detect_installed_slicers()

    # 3) Attempt launch
    try:
        success, message = launch_slicer(request.slicer_id, request.file_path, slicers)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content=SlicerLaunchResponse(
                status="error",
                message=f"启动失败: {exc}",
            ).model_dump(),
        )

    if not success:
        # Distinguish 404 (slicer not found) from 500 (launch failure)
        if "not found" in message.lower():
            return JSONResponse(
                status_code=404,
                content=SlicerLaunchResponse(
                    status="error",
                    message=f"未找到切片软件: {request.slicer_id}",
                ).model_dump(),
            )
        return JSONResponse(
            status_code=500,
            content=SlicerLaunchResponse(
                status="error",
                message=f"启动失败: {message}",
            ).model_dump(),
        )

    return SlicerLaunchResponse(status="success", message=message)
