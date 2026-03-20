"""Lumina Studio API — LUT Management Router.
Lumina Studio API — LUT 管理路由。

Provides endpoints for LUT preset listing, information queries, and merge operations.
提供 LUT 预设列表、信息查询和合并操作端点。
"""

import os
import time

from fastapi import APIRouter, HTTPException

from api.schemas.lut import (
    LutInfoResponse,
    MergeRequest,
    MergeResponse,
    MergeStats,
)
from api.schemas.responses import LUTListResponse, LutInfo, LutColorsResponse, LutColorEntry
from core.lut_merger import LUTMerger
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/lut", tags=["LUT"])

_VALID_PRIMARY_MODES = {"6-Color", "8-Color", "8-Color Max"}


@router.get("/list")
def list_luts() -> LUTListResponse:
    """Return all available LUT presets as a list of LutInfo objects.
    返回所有可用 LUT 预设，以 LutInfo 对象列表形式返回。
    """
    lut_dict: dict[str, str] = LUTManager.get_all_lut_files()
    lut_list: list[LutInfo] = [
        LutInfo(
            name=display_name,
            color_mode=LUTManager.infer_color_mode(display_name, file_path),
            path=file_path,
        )
        for display_name, file_path in lut_dict.items()
    ]
    return LUTListResponse(luts=lut_list)


@router.post("/merge")
def merge_luts_endpoint(request: MergeRequest) -> MergeResponse:
    """Execute LUT merge: primary + multiple secondary LUTs.
    执行 LUT 合并：主 LUT + 多个辅助 LUT。

    Replicates the flow of ``ui/callbacks.py::on_merge_execute``:
    resolve paths → detect modes → validate compatibility →
    load data → skip Merged secondaries → merge → save to Custom dir.
    复刻 ``ui/callbacks.py::on_merge_execute`` 的完整流程：
    解析路径 → 检测模式 → 验证兼容性 → 加载数据 → 跳过 Merged Secondary → 合并 → 保存到 Custom 目录。
    """
    # 1. Validate secondary list not empty / 验证 Secondary 列表非空
    if not request.secondary_names:
        raise HTTPException(
            status_code=400,
            detail="At least one secondary LUT is required",
        )

    # 2. Resolve primary path / 解析主 LUT 路径
    primary_path: str | None = LUTManager.get_lut_path(request.primary_name)
    if primary_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"LUT not found: {request.primary_name}",
        )

    try:
        # 3. Detect primary mode / 检测主 LUT 模式
        primary_mode, _ = LUTMerger.detect_color_mode(primary_path)
        if primary_mode not in _VALID_PRIMARY_MODES:
            raise HTTPException(
                status_code=400,
                detail="Primary LUT must be 6-Color or 8-Color",
            )

        # 4. Load primary data / 加载主 LUT 数据
        primary_rgb, primary_stacks = LUTMerger.load_lut_with_stacks(
            primary_path, primary_mode
        )
        entries = [(primary_rgb, primary_stacks, primary_mode)]
        all_modes: list[str] = [primary_mode]

        # 5. Load each secondary, skip Merged / 加载辅助 LUT，跳过 Merged
        for sec_name in request.secondary_names:
            sec_path: str | None = LUTManager.get_lut_path(sec_name)
            if sec_path is None:
                continue
            sec_mode, _ = LUTMerger.detect_color_mode(sec_path)
            if sec_mode == "Merged":
                continue
            sec_rgb, sec_stacks = LUTMerger.load_lut_with_stacks(
                sec_path, sec_mode
            )
            entries.append((sec_rgb, sec_stacks, sec_mode))
            all_modes.append(sec_mode)

        # 6. Need at least 2 entries / 至少需要 2 个有效条目
        if len(entries) < 2:
            raise HTTPException(
                status_code=400,
                detail="At least one secondary LUT is required",
            )

        # 7. Validate compatibility / 验证兼容性
        valid, err_msg = LUTMerger.validate_compatibility(all_modes)
        if not valid:
            raise HTTPException(status_code=400, detail=err_msg)

        # 8. Merge / 执行合并
        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(
            entries, dedup_threshold=request.dedup_threshold
        )

        # 9. Save to Custom dir / 保存到 Custom 目录
        timestamp: str = time.strftime("%Y%m%d_%H%M%S")
        mode_str: str = "+".join(all_modes)
        output_name: str = f"Merged_{mode_str}_{timestamp}.npz"
        custom_dir: str = os.path.join(LUTManager.LUT_PRESET_DIR, "Custom")
        os.makedirs(custom_dir, exist_ok=True)
        output_path: str = os.path.join(custom_dir, output_name)

        LUTMerger.save_merged_lut(merged_rgb, merged_stacks, output_path)

        # 10. Return response / 返回响应
        return MergeResponse(
            status="success",
            message=f"Merged {stats['total_before']} colors → {stats['total_after']} colors",
            filename=output_name,
            stats=MergeStats(
                total_before=stats["total_before"],
                total_after=stats["total_after"],
                exact_dupes=stats["exact_dupes"],
                similar_removed=stats["similar_removed"],
            ),
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Merge failed: {exc}",
        ) from exc


@router.get("/{lut_name}/colors")
def get_lut_colors(lut_name: str) -> LutColorsResponse:
    """Return all unique colors available in a LUT file.
    返回 LUT 文件中所有可用的唯一颜色。
    """
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    from core.converter import extract_lut_available_colors

    raw_colors: list[dict] = extract_lut_available_colors(path)
    entries: list[LutColorEntry] = [
        LutColorEntry(hex=c["hex"], rgb=c["color"]) for c in raw_colors
    ]
    return LutColorsResponse(lut_name=lut_name, total=len(entries), colors=entries)


@router.get("/{lut_name}/info")
def get_lut_info(lut_name: str) -> LutInfoResponse:
    """Return color mode and color count for a specific LUT.
    返回指定 LUT 的颜色模式和颜色数量。
    """
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    color_mode, color_count = LUTMerger.detect_color_mode(path)
    return LutInfoResponse(name=lut_name, color_mode=color_mode, color_count=color_count)
