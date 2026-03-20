"""Lumina Studio API — Five-Color Query Router.
Lumina Studio API — 五色组合查询路由。

Provides endpoints for querying base colors from a LUT and
performing five-color combination lookups.
提供从 LUT 获取基础颜色和执行五色组合查询的端点。
"""

from fastapi import APIRouter, HTTPException, Query

from api.schemas.five_color import (
    BaseColorEntry,
    BaseColorsResponse,
    FiveColorQueryRequest,
    FiveColorQueryResponse,
)
from core.five_color_combination import (
    ColorCountDetector,
    ColorQueryEngine,
    StackFileManager,
    StackLUTLoader,
    rgb_to_hex,
)
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/five-color", tags=["Five-Color"])


def _load_engine(lut_name: str) -> tuple[ColorQueryEngine, str]:
    """Load a LUT and create a ColorQueryEngine.
    加载 LUT 并创建 ColorQueryEngine。

    Args:
        lut_name: LUT 显示名称。

    Returns:
        (engine, lut_display_name)

    Raises:
        HTTPException 404: LUT 不存在。
        HTTPException 400: LUT 格式无法识别。
        HTTPException 500: 加载失败。
    """
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    try:
        if path.endswith(".npz"):
            success, msg, stack_data, rgb_data = StackLUTLoader.load_npz_file(path)
            if not success:
                raise HTTPException(status_code=500, detail=f"Failed to load LUT: {msg}")
            engine = ColorQueryEngine(stack_lut=stack_data, lut_rgb=rgb_data)
        else:
            # .npy file
            success, msg, rgb_data = StackLUTLoader.load_lut_rgb(path)
            if not success:
                raise HTTPException(status_code=500, detail=f"Failed to load LUT: {msg}")

            color_count, combination_count = ColorCountDetector.detect_color_count(rgb_data)
            if color_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unrecognized LUT format: {combination_count} combinations",
                )

            stack_path = StackFileManager.find_stack_file(color_count)
            stack_data = None
            if stack_path is not None:
                ok, _, loaded_stack = StackLUTLoader.load_stack_lut(stack_path)
                if ok:
                    stack_data = loaded_stack

            engine = ColorQueryEngine(
                stack_lut=stack_data, lut_rgb=rgb_data, color_count=color_count
            )

        return engine, lut_name

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load LUT: {exc}"
        ) from exc


@router.get("/base-colors")
def get_base_colors(lut_name: str = Query(..., description="LUT 显示名称")) -> BaseColorsResponse:
    """Return the base colors of a LUT.
    返回指定 LUT 的基础颜色列表。
    """
    engine, display_name = _load_engine(lut_name)
    base_colors = engine.get_base_colors()
    color_names = engine.get_color_names()

    colors: list[BaseColorEntry] = [
        BaseColorEntry(
            index=i,
            rgb=rgb,
            name=color_names[i] if i < len(color_names) else "",
            hex=rgb_to_hex(rgb),
        )
        for i, rgb in enumerate(base_colors)
    ]

    return BaseColorsResponse(
        lut_name=display_name,
        color_count=len(colors),
        colors=colors,
    )


@router.post("/query")
def query_five_color(request: FiveColorQueryRequest) -> FiveColorQueryResponse:
    """Query a five-color combination result.
    查询五色组合结果。
    """
    engine, _ = _load_engine(request.lut_name)

    # Validate index range
    for idx in request.selected_indices:
        if idx < 0 or idx >= engine.color_count:
            raise HTTPException(
                status_code=400,
                detail=f"Index {idx} out of range [0, {engine.color_count})",
            )

    result = engine.query(request.selected_indices)

    return FiveColorQueryResponse(
        found=result.found,
        selected_indices=result.selected_indices,
        result_rgb=result.result_rgb,
        result_hex=rgb_to_hex(result.result_rgb) if result.result_rgb else None,
        row_index=result.row_index,
        message=result.message,
    )
