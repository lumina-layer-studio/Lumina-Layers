"""Top-level worker functions for converter CPU tasks.
Converter CPU 任务的顶层工作函数。

These functions run in separate processes via ProcessPoolExecutor.
All arguments must be picklable (file paths, scalars, dicts of scalars).
这些函数通过 ProcessPoolExecutor 在独立进程中运行。
所有参数必须可序列化（文件路径、标量、标量字典）。

Design rules:
- Top-level functions only (no methods) — must be picklable.
- Accept only file paths (str) and scalar parameters (int, float, bool, str, dict).
- NEVER accept numpy arrays, PIL Images, or complex objects.
- Large results (images, cache data) are written to temp files; paths are returned.
- All imports of core modules are lazy (inside function body).
"""

import logging

from config import SVG_PIXELS_PER_MM_DEFAULT

_HIGH_FIDELITY_PIXELS_PER_MM = 10.0

# Tile cover thumbnail rasterization caps. The cover thumbnail only needs
# enough resolution to identify the tile visually; we cap the longest edge
# to 512 px so downstream PIL letterbox stays cheap, and ensure at least
# 256 px so visual identification still holds (R5.1).
# 切片封面缩略图栅格化上下界：长边落在 [256, 512] 像素之间，既能保证
# 视觉可识别，又不让下游的 letterbox 缩放变贵。
_TILE_COVER_MAX_LONGEST_PX = 512
_TILE_COVER_MIN_LONGEST_PX = 256
# Process-local cache for the full SVG canvas array. One ``rasterize_svg``
# call typically costs hundreds of milliseconds; with this cache, a 4×4
# grid pays for one subprocess spawn instead of 16. The key is
# ``(svg_abs_path, target_width_mm, pixels_per_mm, mtime)``; values are
# the raw RGBA numpy arrays returned by the subprocess.
# 父进程级整图栅格化结果缓存：避免每个 tile 都开子进程。
_TILE_COVER_CANVAS_CACHE: dict = {}
_TILE_COVER_CANVAS_CACHE_MAX = 4


class LargeFormatCachedAnalysisError(RuntimeError):
    """A native SVG cached analysis artifact is unreadable or incompatible.

    原生 SVG 大画幅缓存分析文件无法读取、解析或与当前网格不兼容。
    """


def _cleanup_worker_temp_paths(*paths: str | None) -> None:
    """Best-effort cleanup for worker-created temp files on local failure."""

    import os as _os

    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            if _os.path.exists(path):
                _os.unlink(path)
        except OSError:
            pass


def _rasterize_canvas_subprocess_entry(
    svg_path: str,
    target_width_mm: float,
    pixels_per_mm: float,
    output_npy_path: str,
) -> None:
    """Rasterize the full SVG canvas inside a spawned subprocess.

    在 spawn 出来的子进程中将整张 SVG 栅格化为完整画布并写入 ``.npy``。

    Top-level so it is picklable for ``multiprocessing.Process``. The
    subprocess writes the result array to ``output_npy_path`` and exits 0
    on success; on rasterize error it lets the exception propagate so the
    parent observes a non-zero ``exitcode`` and raises ``RuntimeError``.

    Args:
        svg_path: SVG 文件绝对路径。
        target_width_mm: 整张目标宽度（毫米）。
        pixels_per_mm: 栅格化像素密度。
        output_npy_path: 子进程将 RGBA 数组保存到该路径，由父进程读取后
            清理。
    """

    import numpy as _np

    from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg

    arr = rasterize_svg(
        svg_path=svg_path,
        target_width_mm=float(target_width_mm),
        pixels_per_mm=float(pixels_per_mm),
        crop_to_content=False,
        _min_quality_px=1,
        _max_longest_px=_TILE_COVER_MAX_LONGEST_PX,
        _cache_result=False,
    )
    _np.save(output_npy_path, arr)


def _run_rasterize_canvas_in_subprocess(
    svg_path: str,
    target_width_mm: float,
    pixels_per_mm: float,
    *,
    _entry=_rasterize_canvas_subprocess_entry,
):
    """Run the rasterize entry in a spawned subprocess until it exits.

    在 spawn 子进程里跑整图栅格化，等待它正常完成或报告真实进程错误。

    Algorithm:
        1. Spawn a fresh interpreter via ``multiprocessing.get_context("spawn")``
           so neither resvg state nor the parent's address space leak.
        2. ``proc.join()`` waits for normal completion without an application
           compute deadline.
        3. Non-zero ``exitcode`` after a normal join is treated as a
           rasterize crash; raise ``RuntimeError`` so the worker logs it
           and falls back to the silent placeholder.

    Args:
        svg_path / target_width_mm / pixels_per_mm: forwarded to the
            subprocess.
        _entry: testability hook. Defaults to
            ``_rasterize_canvas_subprocess_entry`` and **must** be a
            top-level pickle-able function with the same 4-arg signature
            ``(svg_path, target_width_mm, pixels_per_mm, output_npy_path)``;
            tests inject a hang/crash helper from a separate module so the
            kill machinery can be exercised without monkey-patching the
            spawn child's import-time module dict.
            （仅用于测试覆盖硬终止路径；生产路径走默认值）

    Returns:
        ``numpy.ndarray``: the RGBA canvas saved by the subprocess.

    Raises:
        RuntimeError: subprocess exited non-zero (rasterize crashed) or
            the parent could not spawn (daemonic restriction); caller
            falls back to placeholder cover.
    """

    import multiprocessing
    import os as _os
    import tempfile

    import numpy as _np

    from config import TEMP_DIR

    fd, npy_path = tempfile.mkstemp(suffix=".npy", dir=TEMP_DIR)
    _os.close(fd)

    proc = None
    try:
        ctx = multiprocessing.get_context("spawn")
        try:
            proc = ctx.Process(
                target=_entry,
                args=(
                    svg_path,
                    float(target_width_mm),
                    float(pixels_per_mm),
                    npy_path,
                ),
                daemon=True,
            )
            proc.start()
        except (AssertionError, RuntimeError) as exc:
            # ``daemonic processes are not allowed to have children`` and
            # similar fork-restriction errors. Surface as RuntimeError so
            # the caller logs ``placeholder_written`` and the printable
            # tile is still exported.
            # 一些环境（如 daemonic 父进程）禁止再 spawn；统一抛 RuntimeError，
            # 让上层走静默占位回退路径。
            raise RuntimeError(
                f"unable to spawn rasterize subprocess: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        proc.join()

        if proc.exitcode != 0:
            raise RuntimeError(
                f"rasterize_svg subprocess exited with code {proc.exitcode}"
            )

        return _np.load(npy_path)
    finally:
        # The subprocess Process object owns OS resources only while
        # ``.close()`` has not been called; on Python 3.7+ explicit close
        # avoids resource warnings under pytest.
        if proc is not None:
            try:
                proc.close()
            except (ValueError, AttributeError):
                pass
        if _os.path.exists(npy_path):
            try:
                _os.unlink(npy_path)
            except OSError:
                pass


def _get_or_rasterize_full_canvas(
    svg_path: str,
    target_width_mm: float,
    pixels_per_mm: float,
):
    """Return the full SVG canvas, using a parent-process cache where possible.

    优先命中 ``_TILE_COVER_CANVAS_CACHE``；未命中时通过子进程栅格化并填充。

    The cache key is ``(svg_abs_path, target_width_mm, pixels_per_mm,
    mtime)`` so a one-time rasterization is reused across every tile in
    one worker invocation. mtime guards against rare in-place SVG edits.

    Raises propagated ``RuntimeError`` from the subprocess runner;
    degenerate canvases (``None`` / ``size == 0``)
    return ``None`` so the caller treats them as the silent-placeholder
    path.
    """

    import os as _os

    cache_key = None
    try:
        svg_abs = _os.path.abspath(svg_path)
        svg_mtime = _os.path.getmtime(svg_abs)
        cache_key = (
            svg_abs,
            round(float(target_width_mm), 4),
            round(float(pixels_per_mm), 2),
            svg_mtime,
        )
        cached = _TILE_COVER_CANVAS_CACHE.get(cache_key)
        if cached is not None:
            return cached
    except (OSError, ValueError, TypeError):
        cache_key = None

    arr = _run_rasterize_canvas_in_subprocess(
        svg_path=svg_path,
        target_width_mm=target_width_mm,
        pixels_per_mm=pixels_per_mm,
    )

    if arr is None or getattr(arr, "size", 0) == 0:
        return arr

    # Every tile only reads and slices this canvas. Sharing one immutable
    # array avoids a full-canvas copy on every cache hit and another copy on
    # cache insertion.
    try:
        arr.setflags(write=False)
    except (AttributeError, ValueError):
        pass
    if cache_key is not None:
        _TILE_COVER_CANVAS_CACHE[cache_key] = arr
        while len(_TILE_COVER_CANVAS_CACHE) > _TILE_COVER_CANVAS_CACHE_MAX:
            _TILE_COVER_CANVAS_CACHE.pop(next(iter(_TILE_COVER_CANVAS_CACHE)))

    return arr


def _rasterize_tile_for_cover(
    tile,
    svg_path: str,
    total_width_mm: float,
    total_height_mm: float,
) -> "object | None":
    """Rasterize one large-format tile region for its 3MF cover thumbnail.

    将一个大画幅 tile 的区域栅格化为封面缩略图位图（PIL Image）。

    Strategy: rasterize the full SVG canvas once via a spawned
    subprocess (``_run_rasterize_canvas_in_subprocess``) with
    ``crop_to_content=False`` so ``(0, 0)`` strictly maps to the SVG
    viewBox origin. The result lives in ``_TILE_COVER_CANVAS_CACHE``;
    every other tile in the same worker invocation reuses it without
    spawning another subprocess. We then proportionally crop the tile's
    ``(x_mm, y_mm)`` region from the canvas, convert to RGBA PIL Image,
    and clamp the longest edge into ``[256, 512] px``.

    策略：用独立子进程把整张 SVG（``crop_to_content=False``，保留
    画布坐标稳定性）栅格化一次，结果缓存到 ``_TILE_COVER_CANVAS_CACHE``；
    同一 worker 调用里其他 tile 直接命中缓存，不再 spawn。然后按 tile 的
    mm 范围在像素空间按比例裁切，转成 RGBA 后把长边夹到 ``[256, 512] px``。

    Args:
        tile: ``SlicedVectorTile`` 实例（暴露 ``.spec`` 的 mm 范围字段）。
        svg_path: 完整 SVG 文件路径。
        total_width_mm: 大画幅总宽（毫米）。
        total_height_mm: 大画幅总高（毫米）。

    Returns:
        PIL Image（RGBA 模式）或 ``None``（当 tile 没有合法 ``.spec`` /
        范围越界 / 栅格化空像素时）。``None`` 由调用方按"封面静默占位"
        处理，不发 WARNING（与 ``cover_source=None`` 同义）。

    Raises:
        RuntimeError: 子进程崩溃或无法 spawn。
    """

    from PIL import Image

    spec = getattr(tile, "spec", None)
    if spec is None:
        return None

    if total_width_mm <= 0.0 or total_height_mm <= 0.0:
        return None

    longest_mm = max(total_width_mm, total_height_mm)
    # Keep the whole SVG thumbnail-sized. A density floor would make canvas
    # memory grow with physical millimetres (a 9999 mm square previously
    # allocated roughly 5000x5000 RGBA pixels).
    pixels_per_mm = _TILE_COVER_MAX_LONGEST_PX / longest_mm
    shortest_mm = min(total_width_mm, total_height_mm)
    if shortest_mm * pixels_per_mm < 1.0:
        # resvg cannot represent a sub-pixel short edge without rounding it
        # up and exploding the long edge. The cover is optional, so use the
        # existing placeholder instead of risking an unbounded allocation.
        return None

    arr = _get_or_rasterize_full_canvas(
        svg_path=svg_path,
        target_width_mm=float(total_width_mm),
        pixels_per_mm=pixels_per_mm,
    )
    if arr is None:
        return None
    if getattr(arr, "size", 0) == 0:
        return None
    if arr.ndim < 2:
        return None

    full_h = int(arr.shape[0])
    full_w = int(arr.shape[1])
    if full_w <= 0 or full_h <= 0:
        return None

    # Proportionally crop the tile region in pixel coordinates. The
    # whole-SVG raster is taken with ``crop_to_content=False`` so the
    # canvas matches the full SVG viewBox: ``(x_mm, y_mm) /
    # (total_w_mm, total_h_mm)`` maps directly onto ``(full_w, full_h)``
    # without the bounding-box shift that the alpha-crop would introduce
    # for sparse SVGs whose content does not start at ``(0, 0)``.
    # 整图未做 alpha 裁切，因此按 (x_mm, y_mm) / (total_w_mm, total_h_mm)
    # 与 (full_w, full_h) 的比例直接换算到像素坐标即可，不会被内容偏移
    # 误导（这正是 task 6 review 中发现的 tile 坐标错位 bug）。
    x0_mm = float(spec.x0_mm)
    y0_mm = float(spec.y0_mm)
    x1_mm = float(spec.x1_mm)
    y1_mm = float(spec.y1_mm)

    px_x0 = max(0, min(full_w, int(round(x0_mm / total_width_mm * full_w))))
    px_y0 = max(0, min(full_h, int(round(y0_mm / total_height_mm * full_h))))
    px_x1 = max(0, min(full_w, int(round(x1_mm / total_width_mm * full_w))))
    px_y1 = max(0, min(full_h, int(round(y1_mm / total_height_mm * full_h))))
    if px_x1 <= px_x0 or px_y1 <= px_y0:
        return None

    crop = arr[px_y0:px_y1, px_x0:px_x1]
    if crop.size == 0:
        return None

    # Force RGBA so PIL preserves the alpha channel (R5.1 requires keeping
    # the alpha channel before downstream letterboxing).
    if crop.ndim == 2:
        img = Image.fromarray(crop, mode="L").convert("RGBA")
    elif crop.shape[2] == 4:
        img = Image.fromarray(crop, mode="RGBA")
    elif crop.shape[2] == 3:
        img = Image.fromarray(crop, mode="RGB").convert("RGBA")
    else:
        return None

    cw, ch = img.size
    longest_px = max(cw, ch)
    if longest_px <= 0:
        return None

    # Bring longest edge into [_TILE_COVER_MIN_LONGEST_PX,
    # _TILE_COVER_MAX_LONGEST_PX]. Either downscale (cheap, common path)
    # or upscale tiny tiles for visual identifiability.
    if longest_px > _TILE_COVER_MAX_LONGEST_PX:
        scale = _TILE_COVER_MAX_LONGEST_PX / float(longest_px)
    elif longest_px < _TILE_COVER_MIN_LONGEST_PX:
        scale = _TILE_COVER_MIN_LONGEST_PX / float(longest_px)
    else:
        scale = 1.0

    if scale != 1.0:
        new_w = max(1, int(round(cw * scale)))
        new_h = max(1, int(round(ch * scale)))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    return img


def _normalize_puzzle_piece_target_width(image_path: str, params: dict) -> dict:
    """Stabilize puzzle-piece width against float truncation artifacts.
    规整拼图块宽度，避免浮点截断导致的单像素偏差。
    """

    piece_boundary_geometry_path = params.get("piece_boundary_geometry_path")
    target_width_mm = params.get("target_width_mm")
    modeling_mode = params.get("modeling_mode")

    modeling_mode_value = modeling_mode.value if hasattr(modeling_mode, "value") else modeling_mode
    if (
        not piece_boundary_geometry_path
        or target_width_mm is None
        or modeling_mode_value != "high-fidelity"
    ):
        return params

    try:
        from PIL import Image

        with Image.open(image_path) as image:
            source_width_px = int(image.width)
    except (OSError, ValueError):
        return params

    target_width_mm_value = float(target_width_mm)
    truncated_width_px = max(1, int(target_width_mm_value * _HIGH_FIDELITY_PIXELS_PER_MM))
    rounded_width_px = max(1, int(round(target_width_mm_value * _HIGH_FIDELITY_PIXELS_PER_MM)))
    if truncated_width_px == rounded_width_px or source_width_px != rounded_width_px:
        return params

    normalized_params = dict(params)
    normalized_params["target_width_mm"] = (source_width_px + 1e-6) / _HIGH_FIDELITY_PIXELS_PER_MM
    return normalized_params


def worker_generate_preview(
    image_path: str,
    lut_path: str,
    target_width_mm: float,
    color_mode: str,
    modeling_mode: str,
    color_layers: int | None,
    layer_height_mm: float | None,
    quantize_colors: int,
    enable_cleanup: bool,
    enable_outline: bool = False,
    outline_width: float = 2.0,
    is_dark: bool = True,
    model_enable: bool = False,
    model_only: bool = False,
    model_threshold: float | None = None,
    model_margin: float | None = None,
    hue_weight: float = 0.0,
    chroma_gate: float = 15.0,
    use_lut_constrained: bool = False,
    material_source: str = "lut",
    selected_materials: list[str] | None = None,
    material_layer_count: int | None = None,
    material_layer_height_mm: float | None = None,
    material_grid_resolution: int | None = None,
    auto_dynamic_range: bool = False,
    high_precision_3d_preview: bool = False,
    svg_pixels_per_mm: float = SVG_PIXELS_PER_MM_DEFAULT,
    replacement_regions: list[dict[str, str]] | None = None,
    material_backing_material_index: int | None = None,
    material_dynamic_layer_count_enabled: bool = False,
    material_min_layer_count: int = 5,
    material_max_layer_count: int = 10,
    material_delta_e00_tolerance: float = 0.5,
    svg_hole_compensation_enabled: bool = False,
    svg_hole_max_area_mm2: float = 0.5,
    svg_hole_max_width_mm: float = 0.1,
    materials_dir: str | None = None,
) -> dict:
    """Execute preview generation in a worker process.
    在工作进程中执行预览生成。

    Calls ``core.converter.generate_preview_cached`` with the supplied
    scalar parameters, serialises the resulting preview image and cache
    data to temporary files, and returns a dict of file paths.

    Args:
        image_path (str): Path to the input image file. (输入图像文件路径)
        lut_path (str): Path to the LUT calibration file (.npy/.npz). (LUT 校准文件路径)
        target_width_mm (float): Target physical width in mm. (目标物理宽度，毫米)
        color_mode (str): Color system mode, e.g. "CMYW". (色彩系统模式)
        modeling_mode (str): Modeling mode string value, e.g. "high-fidelity". (建模模式字符串)
        quantize_colors (int): Number of K-Means quantization colors. (仅高保真模式生效)
        enable_cleanup (bool): Enable isolated-pixel cleanup. (启用孤立像素清理)
        enable_outline (bool): Enable vector outline metadata during preview.
            (预览时启用矢量描边元数据)
        outline_width (float): Outline width in millimeters. (描边宽度，毫米)
        svg_pixels_per_mm (float): High-fidelity SVG raster density in px/mm.
            (高保真 SVG 光栅化采样密度，单位 px/mm)
        is_dark (bool): Dark theme flag for 2D preview bed colors. (深色主题标志)
        material_backing_material_index: Selected backing material index.
            (用户选择的基板耗材索引)
        material_dynamic_layer_count_enabled: Enable exact dynamic effective
            layers. (启用精确动态有效层数)
        material_min_layer_count: Minimum dynamic effective layers. (动态最小
            有效层数)
        material_max_layer_count: Maximum dynamic effective and physical
            layers. (动态最大有效层数及物理模型层数)
        material_delta_e00_tolerance: Allowed CIEDE2000 loss for shorter
            recipes. (短配方允许的 CIEDE2000 损失)

    Returns:
        dict: Result dictionary with keys: (结果字典，包含以下键)
            - preview_png_path (str | None): Path to saved preview PNG.
            - cache_data_path (str | None): Path to pickled cache data.
            - status_msg (str): Status message from the converter.
    """
    # Lazy imports — executed inside the worker process
    import os
    import pickle
    import tempfile
    import time as _time

    import numpy as np
    from PIL import Image

    from core.preview_sizing import preview_dimensions
    from config import ModelingMode
    from api.structured_logging import get_logger
    from core.converter import generate_preview_cached

    log = get_logger(__name__)

    # Convert string modeling_mode to enum
    mode_enum = ModelingMode(modeling_mode)
    _t_worker_start = _time.perf_counter()

    log.debug(
        "Worker preview started",
        extra={
            "event": "worker_preview_started",
            "hue_weight": hue_weight,
            "chroma_gate": chroma_gate,
            "lut_path": lut_path,
            "image_name": os.path.basename(image_path),
            "target_width_mm": target_width_mm,
            "color_mode": color_mode,
            "modeling_mode": modeling_mode,
            "color_layers": color_layers,
            "layer_height_mm": layer_height_mm,
            "quantize_colors": quantize_colors,
            "enable_cleanup": enable_cleanup,
            "enable_outline": enable_outline,
            "outline_width": outline_width,
            "svg_pixels_per_mm": svg_pixels_per_mm,
            "material_source": material_source,
            "selected_material_count": len(selected_materials or []),
            "material_grid_resolution": material_grid_resolution,
            "replacement_count": len(replacement_regions or []),
            "model_enable": model_enable,
            "model_only": model_only,
            "high_precision_3d_preview": high_precision_3d_preview,
        },
    )
    try:
        preview_img, cache_data, status_msg = generate_preview_cached(
            image_path=image_path,
            lut_path=lut_path,
            target_width_mm=target_width_mm,
            color_mode=color_mode,
            modeling_mode=mode_enum,
            color_layers=color_layers,
            layer_height_mm=layer_height_mm,
            model_enable=model_enable,
            model_only=model_only,
            model_threshold=model_threshold,
            model_margin=model_margin,
            quantize_colors=quantize_colors,
            enable_cleanup=enable_cleanup,
            enable_outline=enable_outline,
            outline_width=outline_width,
            svg_pixels_per_mm=svg_pixels_per_mm,
            svg_hole_compensation_enabled=svg_hole_compensation_enabled,
            svg_hole_max_area_mm2=svg_hole_max_area_mm2,
            svg_hole_max_width_mm=svg_hole_max_width_mm,
            is_dark=is_dark,
            hue_weight=hue_weight,
            chroma_gate=chroma_gate,
            use_lut_constrained=use_lut_constrained,
            auto_dynamic_range=auto_dynamic_range,
            high_precision_3d_preview=high_precision_3d_preview,
            material_source=material_source,
            materials_dir=materials_dir,
            selected_materials=selected_materials,
            material_layer_count=material_layer_count,
            material_layer_height_mm=material_layer_height_mm,
            material_grid_resolution=material_grid_resolution,
            material_backing_material_index=material_backing_material_index,
            material_dynamic_layer_count_enabled=(
                material_dynamic_layer_count_enabled
            ),
            material_min_layer_count=material_min_layer_count,
            material_max_layer_count=material_max_layer_count,
            material_delta_e00_tolerance=material_delta_e00_tolerance,
            replacement_regions=replacement_regions,
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        RuntimeError,
    ) as e:
        log.exception(
            "Worker preview failed",
            extra={
                "event": "worker_preview_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise

    # ---- Color-card mode: replace the 2D preview image only ----
    # 色卡模式：worker 只替换 2D 预览图。完整的 cache 替换（matched_rgb、
    # mask_solid、material_matrix 等）在主进程的 preview 端点中执行，
    # 避免 subprocess pickle 序列化导致替换丢失。
    if mode_enum == ModelingMode.COLOR_CARD and cache_data is not None:
        color_palette = cache_data.get("color_palette") or []
        hex_list = [entry["hex"] for entry in color_palette if "hex" in entry]
        if hex_list:
            from core.color_card import render_color_card_image
            preview_img = render_color_card_image(hex_list)

    preview_array_shape = list(preview_img.shape) if isinstance(preview_img, np.ndarray) else None
    if isinstance(preview_img, np.ndarray):
        if preview_img.ndim >= 2:
            preview_image_size = [int(preview_img.shape[1]), int(preview_img.shape[0])]
        else:
            preview_image_size = [int(preview_img.shape[0])]
    else:
        preview_image_size = list(preview_img.size) if hasattr(preview_img, "size") else None

    log.debug(
        "Worker preview core conversion complete",
        extra={
            "event": "worker_preview_core_done",
            "duration_ms": round((_time.perf_counter() - _t_worker_start) * 1000, 3),
            "status_msg": status_msg,
            "cache_data_ready": cache_data is not None,
            "preview_array_shape": preview_array_shape,
            "preview_image_size": preview_image_size,
        },
    )

    result: dict = {
        "status_msg": status_msg,
        "preview_png_path": None,
        "raw_preview_png_path": None,
        "cache_data_path": None,
        "cache_artifact_ref": None,
        "vector_parse_clip_cache_path": None,
        "response_palette": None,
        "gradient_groups": None,
        "gradient_region_id_map_path": None,
    }

    if preview_img is None:
        status_error_message = str(status_msg).strip() if status_msg else ""
        error_message = (
            status_error_message or "Preview generation returned no image."
        )
        log.warning(
            "Worker preview returned no image",
            extra={
                "event": "worker_preview_no_image",
                "error_type": "PreviewImageMissing",
                "error_message": error_message,
                "status_msg": status_msg,
            },
        )
        # Surface the domain error to the API layer so the 500 response
        # includes the actual pipeline error instead of an opaque fallback.
        raise RuntimeError(status_msg or "Preview generation failed")

    _t_serial_start = _time.perf_counter()

    # Write preview image to a temp PNG file
    from config import TEMP_DIR

    created_temp_paths: list[str] = []
    _t_png = 0.0
    _t_pkl = 0.0
    try:
        _t = _time.perf_counter()
        if preview_img is not None:
            fd, png_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
            os.close(fd)
            created_temp_paths.append(png_path)
            if isinstance(preview_img, np.ndarray):
                height, width = preview_img.shape[:2]
                display_size = preview_dimensions(width, height)
                if display_size != (width, height):
                    import cv2

                    preview_img = cv2.resize(
                        preview_img, display_size, interpolation=cv2.INTER_NEAREST,
                    )
                Image.fromarray(preview_img).save(png_path)
            else:
                display_size = preview_dimensions(*preview_img.size)
                if display_size != preview_img.size:
                    preview_img = preview_img.resize(display_size, Image.Resampling.NEAREST)
                preview_img.save(png_path)
            result["preview_png_path"] = png_path
        _t_png = _time.perf_counter() - _t

        # Pickle cache data to a temp file
        _t = _time.perf_counter()
        if cache_data is not None:
            vector_parse_clip_cache_blob = None
            if isinstance(cache_data, dict):
                vector_parse_clip_cache_blob = cache_data.pop(
                    "vector_parse_clip_cache_blob",
                    None,
                )
            if isinstance(vector_parse_clip_cache_blob, (bytes, bytearray)):
                fd, vector_cache_path = tempfile.mkstemp(
                    prefix="vector_parse_clip_cache_",
                    suffix=".pkl",
                    dir=TEMP_DIR,
                )
                os.close(fd)
                created_temp_paths.append(vector_cache_path)
                with open(vector_cache_path, "wb") as f:
                    f.write(vector_parse_clip_cache_blob)
                result["vector_parse_clip_cache_path"] = vector_cache_path

            cache_pickle_payload = cache_data
            if mode_enum != ModelingMode.COLOR_CARD and isinstance(cache_data, dict):
                from api.gradient_group_payload import compute_gradient_group_payload
                raw_preview_rgba = cache_data.get("preview_rgba")
                if isinstance(raw_preview_rgba, np.ndarray):
                    fd, raw_png_path = tempfile.mkstemp(
                        prefix="preview_raw_",
                        suffix=".png",
                        dir=TEMP_DIR,
                    )
                    os.close(fd)
                    created_temp_paths.append(raw_png_path)
                    Image.fromarray(raw_preview_rgba).save(raw_png_path)
                    result["raw_preview_png_path"] = raw_png_path

                try:
                    from api.preview_response_payload import (
                        build_preview_response_palette,
                    )

                    result["response_palette"] = build_preview_response_palette(cache_data)
                except (ValueError, TypeError, KeyError) as exc:
                    log.warning(
                        "Worker preview response palette precompute failed",
                        extra={
                            "event": "worker_preview_response_palette_failed",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        },
                    )

                try:
                    computed_gradient_payload = compute_gradient_group_payload(cache_data)
                except (ValueError, RuntimeError) as exc:
                    log.warning(
                        "Worker gradient-group precompute failed",
                        extra={
                            "event": "worker_gradient_groups_failed",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        },
                    )
                    computed_gradient_payload = None
                if computed_gradient_payload is not None:
                    gradient_groups, region_id_map = computed_gradient_payload
                    fd, region_map_path = tempfile.mkstemp(
                        prefix="gradient_region_id_map_",
                        suffix=".npy",
                        dir=TEMP_DIR,
                    )
                    os.close(fd)
                    created_temp_paths.append(region_map_path)
                    np.save(region_map_path, region_id_map)
                    result["gradient_groups"] = gradient_groups
                    result["gradient_region_id_map_path"] = region_map_path

                from api.preview_cache_artifacts import (
                    externalize_preview_cache_to_artifacts,
                )

                cache_artifact_ref, _artifact_paths = (
                    externalize_preview_cache_to_artifacts(
                        cache_data,
                        root_dir=TEMP_DIR,
                    )
                )
                created_temp_paths.extend(_artifact_paths)
                result["cache_artifact_ref"] = cache_artifact_ref
                cache_pickle_payload = dict(cache_artifact_ref["metadata"])

            fd, cache_path = tempfile.mkstemp(suffix=".pkl", dir=TEMP_DIR)
            os.close(fd)
            created_temp_paths.append(cache_path)
            with open(cache_path, "wb") as f:
                pickle.dump(cache_pickle_payload, f)
            result["cache_data_path"] = cache_path
        _t_pkl = _time.perf_counter() - _t
    except (OSError, RuntimeError, ValueError, TypeError, pickle.PickleError):
        _cleanup_worker_temp_paths(*created_temp_paths)
        raise

    cache_artifact_file_bytes = None
    if result["cache_artifact_ref"]:
        cache_artifact_paths = {
            field_ref["path"]
            for field_ref in result["cache_artifact_ref"].get("fields", {}).values()
        }
        cache_artifact_file_bytes = sum(
            os.path.getsize(path)
            for path in cache_artifact_paths
            if os.path.exists(path)
        )

    log.debug(
        "Worker preview serialization complete",
        extra={
            "event": "worker_preview_serialization_done",
            "png_save_ms": round(_t_png * 1000, 3),
            "pickle_dump_ms": round(_t_pkl * 1000, 3),
            "duration_ms": round((_time.perf_counter() - _t_serial_start) * 1000, 3),
            "worker_total_ms": round((_time.perf_counter() - _t_worker_start) * 1000, 3),
            "preview_png_bytes": os.path.getsize(result["preview_png_path"]) if result["preview_png_path"] else None,
            "raw_preview_png_bytes": (
                os.path.getsize(result["raw_preview_png_path"])
                if result["raw_preview_png_path"]
                else None
            ),
            "cache_data_bytes": os.path.getsize(result["cache_data_path"]) if result["cache_data_path"] else None,
            "cache_artifact_file_bytes": cache_artifact_file_bytes,
            "vector_parse_clip_cache_bytes": (
                os.path.getsize(result["vector_parse_clip_cache_path"])
                if result["vector_parse_clip_cache_path"]
                else None
            ),
            "response_palette_count": (
                len(result["response_palette"])
                if result["response_palette"] is not None
                else None
            ),
            "gradient_group_count": (
                len(result["gradient_groups"])
                if result["gradient_groups"] is not None
                else None
            ),
            "gradient_region_id_map_bytes": (
                os.path.getsize(result["gradient_region_id_map_path"])
                if result["gradient_region_id_map_path"]
                else None
            ),
        },
    )

    return result


def _batch_extract_slots_from_3mf(
    threemf_path: str,
    target: "MetadataTarget | SourceMaterialTarget | None" = None,
) -> list[dict]:
    """Read canonical source slots through Fat Cat.

    通过 Fat Cat 读取规范化的源耗材槽位。
    """
    from utils.fatcat_metadata import read_source_metadata

    return read_source_metadata(threemf_path, target=target)["slots"]


def worker_batch_convert_item(
    image_path: str,
    lut_path: str,
    target_width_mm: float,
    spacer_thick: float,
    structure_mode: str,
    color_mode: str,
    modeling_mode_value: str,
    color_layers: int | None,
    layer_height_mm: float | None,
    quantize_colors: int,
    enable_cleanup: bool,
    artifact_prefix: str,
    hue_weight: float = 0.0,
    chroma_gate: float = 15.0,
    enable_relief: bool = False,
    height_mode: str = "color",
    color_height_map: dict[str, float] | None = None,
    heightmap_max_height: float | None = None,
    svg_pixels_per_mm: float = SVG_PIXELS_PER_MM_DEFAULT,
    printer_id: str = "bambu-h2d",
    slicer: str = "BambuStudio",
    nozzle_size: str = "0.4",
    enable_base_layer_height_modifier: bool = True,
    model_enable: bool = False,
    model_only: bool = False,
    model_threshold: float | None = None,
    model_margin: float | None = None,
    material_source: str = "lut",
    selected_materials: list[str] | None = None,
    material_layer_count: int | None = None,
    material_layer_height_mm: float | None = None,
    material_grid_resolution: int | None = None,
    material_backing_material_index: int | None = None,
    use_lut_constrained: bool = False,
    auto_dynamic_range: bool = False,
    high_precision_3d_preview: bool = False,
    device_profile_id: str | None = None,
    build_plate_id: str | None = None,
    backing_infill_density_percent: int = 100,
    material_dynamic_layer_count_enabled: bool = False,
    material_min_layer_count: int = 5,
    material_max_layer_count: int = 10,
    material_delta_e00_tolerance: float = 0.5,
    separate_backing: bool = False,
    enable_wipe_tower_auto_placement: bool = True,
    svg_hole_compensation_enabled: bool = False,
    svg_hole_max_area_mm2: float = 0.5,
    svg_hole_max_width_mm: float = 0.1,
    enable_coating: bool = False,
    coating_height_mm: float = 0.08,
    native_filament_profiles: dict[str, str] | None = None,
    coating_material: dict[str, str] | None = None,
    enable_outline: bool = False,
    outline_width: float = 2.0,
    external_spool_material: str | None = None,
    materials_dir: str | None = None,
) -> dict:
    """Execute a single batch conversion item in a worker process.
    在工作进程中执行单个批量转换项。

    Calls ``core.converter.convert_image_to_3d`` with the supplied
    scalar parameters, then renames the produced 3MF / preview GLB into
    ``TEMP_DIR/<artifact_prefix><stem>.{3mf,glb}`` and writes a
    structured sidecar JSON next to them so the parent process can build
    a merged 3MF and register the original per-image preview GLBs for
    multi-model rendering without re-parsing artifacts inside another
    process.

    调用 ``core.converter.convert_image_to_3d`` 后，将产出的 per-image 3MF
    与预览 GLB 重命名到 ``TEMP_DIR/<artifact_prefix><stem>.{3mf,glb}``，
    并在同目录写出结构化 sidecar JSON，供父进程合并 3MF、注册每个
    单件预览 GLB 时使用，免得跨进程解析 per-image 产物。

    Args:
        enable_coating: Enable transparent coating for this batch item.
            (为此批量项启用透明镀层)
        coating_height_mm: Transparent coating thickness in millimeters.
            (透明镀层厚度，毫米)
        image_path: Path to the input image file. (输入图像文件路径)
        lut_path: Path to the LUT calibration file. (LUT 校准文件路径)
        target_width_mm: Target physical width in mm. (目标物理宽度，毫米)
        spacer_thick: Backing plate thickness in mm. (底板厚度，毫米)
        backing_infill_density_percent: Sparse-infill percentage used for deep
            backing below the protected viewing-surface zone.
            (观赏面保护区以下深层底板的稀疏填充百分比)
        structure_mode: Print structure mode, e.g. "Double-sided". (打印结构模式)
        color_mode: Color system mode, e.g. "4-Color". (色彩系统模式)
        modeling_mode_value: Modeling mode string, e.g. "high-fidelity". (建模模式字符串)
        color_layers: Optional explicit color layer count. (可选的颜色层数)
        layer_height_mm: Optional explicit layer height in mm. (可选的层厚)
        quantize_colors: Number of K-Means quantization colors. (仅高保真模式生效)
        enable_cleanup: Enable isolated-pixel cleanup. (启用孤立像素清理)
        artifact_prefix: Filename prefix for per-image intermediate
            artifacts (3MF / GLB / sidecar JSON). The parent process
            generates ``f"batch-{batch_run_id}-"`` once per batch request
            and forwards it as a scalar so cleanup can scan all artifacts
            for one request via this single prefix. The worker MUST NOT
            generate its own UUIDs — keeping pickleable + minimal
            boundary.
            (per-image 中间产物文件名前缀；父进程每次批量请求生成一次，
            按标量传入；worker 不要自己生成 UUID)
        svg_pixels_per_mm: High-fidelity SVG raster density in px/mm.
            (高保真 SVG 光栅化采样密度，单位 px/mm)
        printer_id / slicer / nozzle_size: Device preset fields forwarded
            to the canonical single-item 3MF writer. (透传到单件 3MF
            writer 的设备预设字段)
        device_profile_id: Generated machine registry device profile ID
            forwarded to the canonical single-item 3MF writer.
            (透传到单件 3MF writer 的机器注册表设备配置 ID)
        enable_base_layer_height_modifier: Whether to keep the Bambu-family
            coarse base-layer setting from user settings. (是否沿用设置页
            的底板粗层高开关)
        enable_wipe_tower_auto_placement: Whether 3MF export may adapt the
            model and wipe-tower layout. (3MF 导出时是否允许自动调整模型与
            擦料塔布局。)
        material_dynamic_layer_count_enabled: Enable exact dynamic effective
            layers. (启用精确动态有效层数)
        material_min_layer_count: Minimum dynamic effective layers. (动态最小
            有效层数)
        material_max_layer_count: Maximum dynamic effective and physical
            layers. (动态最大有效层数及物理模型层数)
        material_delta_e00_tolerance: Allowed CIEDE2000 loss for shorter
            recipes. (短配方允许的 CIEDE2000 损失)
        separate_backing: Whether the backing plate remains a separate mesh.
            (是否将底板保留为独立网格)

    Returns:
        dict: Result dictionary with the following keys:
            - ``threemf_path`` (str | None): Final per-image 3MF path
              under ``TEMP_DIR``, prefixed by ``artifact_prefix``.
            - ``preview_glb_path`` (str | None): Final per-image preview
              GLB path under ``TEMP_DIR``, prefixed by ``artifact_prefix``.
            - ``metadata_sidecar_path`` (str | None): JSON sidecar path
              under ``TEMP_DIR``, prefixed by ``artifact_prefix``.
              Contains the source filename, XY footprint and material slots
              consumed by the parent process during merged export.
            - ``xy_bbox_mm`` (tuple[float, float]): ``(width_mm, depth_mm)``
              footprint, scalar copy of ``sidecar.xy_bbox_mm``.
            - ``status_msg`` (str): Conversion status or artifact inspection error.
            (5 个 key；前 3 个为落盘文件路径或 ``None``，``xy_bbox_mm``
            为 ``(width_mm, depth_mm)`` 标量，``status_msg`` 沿用旧含义)
    """
    # Lazy imports — executed inside the worker process
    import json
    import os
    import shutil

    from config import ModelingMode, TEMP_DIR
    from core.converter import convert_image_to_3d

    core_modeling_mode = ModelingMode(modeling_mode_value)

    threemf_path, glb_path, _preview_img, status_msg, _recipe = convert_image_to_3d(
        image_path=image_path,
        lut_path=lut_path,
        target_width_mm=target_width_mm,
        spacer_thick=spacer_thick,
        backing_infill_density_percent=backing_infill_density_percent,
        structure_mode=structure_mode,
        color_mode=color_mode,
        color_layers=color_layers,
        layer_height_mm=layer_height_mm,
        model_enable=model_enable,
        model_only=model_only,
        model_threshold=model_threshold,
        model_margin=model_margin,
        add_loop=False,
        loop_width=4.0,
        loop_length=8.0,
        loop_hole=2.5,
        loop_pos=None,
        modeling_mode=core_modeling_mode,
        quantize_colors=quantize_colors,
        enable_cleanup=enable_cleanup,
        svg_pixels_per_mm=svg_pixels_per_mm,
        svg_hole_compensation_enabled=svg_hole_compensation_enabled,
        svg_hole_max_area_mm2=svg_hole_max_area_mm2,
        svg_hole_max_width_mm=svg_hole_max_width_mm,
        hue_weight=hue_weight,
        chroma_gate=chroma_gate,
        enable_relief=enable_relief,
        height_mode=height_mode,
        color_height_map=color_height_map,
        heightmap_max_height=heightmap_max_height,
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        build_plate_id=build_plate_id,
        enable_base_layer_height_modifier=enable_base_layer_height_modifier,
        enable_wipe_tower_auto_placement=enable_wipe_tower_auto_placement,
        material_source=material_source,
        materials_dir=materials_dir,
        native_filament_profiles=native_filament_profiles,
        selected_materials=selected_materials,
        material_layer_count=material_layer_count,
        material_layer_height_mm=material_layer_height_mm,
        material_grid_resolution=material_grid_resolution,
        material_backing_material_index=material_backing_material_index,
        separate_backing=separate_backing,
        use_lut_constrained=use_lut_constrained,
        auto_dynamic_range=auto_dynamic_range,
        high_precision_3d_preview=high_precision_3d_preview,
        material_dynamic_layer_count_enabled=material_dynamic_layer_count_enabled,
        material_min_layer_count=material_min_layer_count,
        material_max_layer_count=material_max_layer_count,
        material_delta_e00_tolerance=material_delta_e00_tolerance,
        enable_coating=enable_coating,
        coating_height_mm=coating_height_mm,
        coating_material=coating_material,
        enable_outline=enable_outline,
        outline_width=outline_width,
        batch_preview=True,
    )

    # Conversion failure surfaces as no 3MF; keep the legacy contract
    # (``threemf_path=None``) so the parent's existing failure branch
    # (records BatchItemResult(status="failed")) keeps working.
    # 转换失败时沿用旧契约：``threemf_path=None``，父进程仍把这一项当
    # failed 处理；本 worker 不再尝试落盘 sidecar / 重命名 GLB。
    if not threemf_path or not os.path.exists(threemf_path):
        return {
            "threemf_path": None,
            "preview_glb_path": None,
            "metadata_sidecar_path": None,
            "xy_bbox_mm": (0.0, 0.0),
            "status_msg": status_msg,
        }

    # Use the same exported components as the merger. Re-measuring the input
    # can disagree with cropped SVG scale or omit auxiliary geometry.
    from api.structured_logging import get_logger
    from utils.fatcat_metadata import select_metadata_target
    from utils.merged_bambu_3mf_writer import read_merge_source_info

    try:
        slot_target = select_metadata_target(
            slicer=slicer,
            printer_id=printer_id,
            nozzle_size=nozzle_size,
            device_profile_id=device_profile_id,
            build_plate_id=build_plate_id,
        )
        (width_mm, depth_mm), slots = read_merge_source_info(
            threemf_path, metadata_target=slot_target,
            use_base_material_names=external_spool_material is not None,
        )
    except Exception as exc:
        # Artifact inspection is a worker boundary: an unknown footprint
        # cannot be laid out safely. Release only this conversion's outputs.
        log = get_logger(__name__)
        log.warning(
            "Cannot inspect the exported batch model footprint",
            extra={
                "event": "worker_batch_footprint_failed",
                "image_name": os.path.basename(image_path),
                "path": threemf_path,
                "artifact_prefix": artifact_prefix,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        for path in (threemf_path, glb_path):
            if not path:
                continue
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                log.warning(
                    "Cannot remove a failed batch item's artifact",
                    extra={
                        "event": "worker_batch_artifact_cleanup_failed",
                        "path": path,
                        "artifact_prefix": artifact_prefix,
                        "error_type": type(cleanup_error).__name__,
                        "error_message": str(cleanup_error),
                    },
                )
        return {
            "threemf_path": None,
            "preview_glb_path": None,
            "metadata_sidecar_path": None,
            "xy_bbox_mm": (0.0, 0.0),
            "status_msg": "Cannot read the exported batch model footprint. Retry conversion.",
        }

    source_filename = os.path.basename(image_path) or "input.png"
    base_stem, _ = os.path.splitext(source_filename)
    if not base_stem:
        base_stem = "item"

    # Disambiguate via the produced 3MF basename (which already encodes
    # the timestamp) so sibling worker calls within the same batch do
    # not clobber each other's intermediates.
    # 用产出 3MF 的文件名（已带时间戳）做后缀，避免同批多 worker 撞名。
    threemf_stem, _ = os.path.splitext(os.path.basename(threemf_path))

    target_3mf_name = f"{artifact_prefix}{threemf_stem}.3mf"
    target_glb_name = f"{artifact_prefix}{threemf_stem}.glb"
    target_sidecar_name = f"{artifact_prefix}{threemf_stem}.json"

    target_3mf_path = os.path.join(TEMP_DIR, target_3mf_name)
    target_glb_path = os.path.join(TEMP_DIR, target_glb_name)
    target_sidecar_path = os.path.join(TEMP_DIR, target_sidecar_name)

    os.makedirs(TEMP_DIR, exist_ok=True)

    # Move the per-image 3MF into TEMP_DIR with the prefixed name. Use
    # ``shutil.move`` so cross-device moves (e.g. when MODELS_DIR and
    # TEMP_DIR live on different volumes) still work; ``os.replace`` is
    # not always available across filesystems.
    # 用 shutil.move 兼容跨卷场景；os.replace 在不同卷上可能失败。
    if os.path.exists(target_3mf_path):
        os.unlink(target_3mf_path)
    shutil.move(threemf_path, target_3mf_path)

    # Preview GLB is optional in some pipeline configurations (rare).
    # When absent we still build a sidecar with the 3MF + xy_bbox so the
    # parent process can produce the merged 3MF; it then skips this item
    # in the batch preview list. The acceptance for this task only mandates the
    # presence of the GLB when the underlying pipeline emits one, which
    # is the default high-fidelity / vector behaviour today.
    # GLB 只有在底层 pipeline 实际产出时才落盘；缺失时父进程的
    # preview_items 列表会跳过本项。当前默认 pipeline 总是产出 GLB。
    final_glb_path: str | None = None
    if glb_path and os.path.exists(glb_path):
        if os.path.exists(target_glb_path):
            os.unlink(target_glb_path)
        shutil.move(glb_path, target_glb_path)
        final_glb_path = target_glb_path

    # Geometry and slots were read together from this exported 3MF.
    sidecar_payload = {
        "schema_version": 1,
        "source_filename": source_filename,
        "xy_bbox_mm": {"width_mm": width_mm, "depth_mm": depth_mm},
        "slots": slots,
    }

    with open(target_sidecar_path, "w", encoding="utf-8") as fh:
        json.dump(sidecar_payload, fh, ensure_ascii=False, indent=2)

    return {
        "threemf_path": target_3mf_path,
        "preview_glb_path": final_glb_path,
        "metadata_sidecar_path": target_sidecar_path,
        "xy_bbox_mm": (width_mm, depth_mm),
        "status_msg": status_msg,
    }


def worker_generate_model(
    image_path: str,
    lut_path: str,
    params: dict,
) -> dict:
    """Execute 3MF model generation in a worker process.
    在工作进程中执行 3MF 模型生成。

    Calls ``core.converter.generate_final_model`` with the supplied
    parameters and returns a dict containing the output file paths.

    Args:
        image_path (str): Path to the input image file. (输入图像文件路径)
        lut_path (str): Path to the LUT calibration file (.npy/.npz). (LUT 校准文件路径)
        params (dict): Dict of scalar parameters forwarded to
            ``generate_final_model`` via **kwargs. Keys must match the
            function signature (e.g. target_width_mm, spacer_thick,
            color_mode, modeling_mode, fridge-magnet metadata, etc.).
            (标量参数字典，通过 **kwargs 转发给 generate_final_model，
            包括冰箱贴磁铁槽元数据等字段)

    Returns:
        dict: Result dictionary with keys: (结果字典，包含以下键)
            - threemf_path (str | None): Path to the generated .3mf file.
            - glb_path (str | None): Path to the generated .glb preview file.
            - status_msg (str): Status message from the converter.
            - x_mirrored (bool, optional): Effective S09 X-mirror decision.
            - mirror_span_mm (float, optional): Exact S09 X-mirror span.
    """
    # Lazy imports — executed inside the worker process
    import os
    import time as _time

    from api.structured_logging import get_logger
    from core.converter import generate_final_model
    from core.errors import CachedPreviewAnalysisError

    log = get_logger(__name__)
    normalized_params = _normalize_puzzle_piece_target_width(image_path, params)
    _t_worker_start = _time.perf_counter()
    log.debug(
        "Worker model generation started",
        extra={
            "event": "worker_model_started",
            "image_name": os.path.basename(image_path),
            "lut_path": lut_path,
            "target_width_mm": normalized_params.get("target_width_mm"),
            "color_mode": normalized_params.get("color_mode"),
            "modeling_mode": normalized_params.get("modeling_mode"),
            "quantize_colors": normalized_params.get("quantize_colors"),
            "enable_cleanup": normalized_params.get("enable_cleanup"),
            "replacement_count": len(normalized_params.get("replacement_regions") or []),
            "recipe_override_count": len(normalized_params.get("recipe_overrides") or []),
            "free_color_count": len(normalized_params.get("free_color_set") or []),
            "fridge_magnet_count": len(normalized_params.get("fridge_magnets") or []),
            "enable_relief": normalized_params.get("enable_relief"),
            "enable_outline": normalized_params.get("enable_outline"),
            "enable_cloisonne": normalized_params.get("enable_cloisonne"),
        },
    )
    # Spec svg-vector-outline-support / Task 3.2: confirm vector + outline
    # request payload is faithfully forwarded to ctx. DEBUG-only — does not
    # consume the per-request INFO budget. Emitted only when the user
    # actually asked for outline on a vector input, so the line stays cheap
    # in the common case and observable when the bug-condition recurs.
    # 规范 svg-vector-outline-support / Task 3.2：vector + outline 请求被
    # 忠实写入 ctx 的可观测点；DEBUG 级，不占 INFO 预算，且只在用户真正
    # 在 vector 模式下勾选 outline 时打印，避免无关请求噪音。
    _modeling_mode_raw = normalized_params.get("modeling_mode")
    _modeling_mode_value = (
        _modeling_mode_raw.value
        if hasattr(_modeling_mode_raw, "value")
        else _modeling_mode_raw
    )
    if (
        _modeling_mode_value == "vector"
        and bool(normalized_params.get("enable_outline"))
    ):
        _outline_width_raw = normalized_params.get("outline_width")
        try:
            _outline_width_value: float | None = float(_outline_width_raw)
        except (TypeError, ValueError):
            _outline_width_value = None
        log.debug(
            "Vector outline normalized",
            extra={
                "event": "vector_outline_normalized",
                "modeling_mode": "vector",
                "enable_outline": True,
                "outline_width": _outline_width_value,
            },
        )
    export_transform_metadata: dict[str, object] = {}
    try:
        result_tuple = generate_final_model(
            image_path=image_path,
            lut_path=lut_path,
            export_transform_metadata=export_transform_metadata,
            **normalized_params,
        )
    except (
        CachedPreviewAnalysisError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        RuntimeError,
    ) as e:
        log.exception(
            "Worker model generation failed",
            extra={
                "event": "worker_model_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise

    # generate_final_model returns:
    # (3mf_path, glb_path, preview_image, status_message, recipe)
    threemf_path, glb_path, _preview, status_msg, _recipe = result_tuple

    log.debug(
        "Worker model generation complete",
        extra={
            "event": "worker_model_done",
            "duration_ms": round((_time.perf_counter() - _t_worker_start) * 1000, 3),
            "status_msg": status_msg,
            "threemf_path": threemf_path,
            "threemf_bytes": os.path.getsize(threemf_path) if threemf_path and os.path.exists(threemf_path) else None,
            "glb_path": glb_path,
            "glb_bytes": os.path.getsize(glb_path) if glb_path and os.path.exists(glb_path) else None,
        },
    )

    result = {
        "threemf_path": threemf_path,
        "glb_path": glb_path,
        "status_msg": status_msg,
    }
    x_mirrored = export_transform_metadata.get("x_mirrored")
    mirror_span_mm = export_transform_metadata.get("mirror_span_mm")
    if isinstance(x_mirrored, bool) and isinstance(mirror_span_mm, (int, float)):
        result.update(
            {
                "x_mirrored": x_mirrored,
                "mirror_span_mm": float(mirror_span_mm),
            }
        )
    return result


def worker_generate_model_surface_overlay(
    image_path: str,
    lut_path: str,
    params: dict,
) -> dict:
    """Generate a 3MF by embedding image-converter layers into a model surface.

    使用图片转换器色层嵌入模型选中表面并生成 3MF。

    Args:
        image_path: Already rendered surface artwork path (PNG or SVG).
            已渲染好的贴面画面路径（PNG 或 SVG）。
        lut_path: LUT calibration path forwarded to the converter.
            透传给转换器的 LUT 校准文件路径。
        params: Picklable scalar dict containing model path, footprint payload,
            pocket depth, and converter params.
            可序列化参数，包含模型路径、表面轮廓、开槽深度与转换参数。

    Returns:
        Worker result dict compatible with ``convert_generate``.
        与 ``convert_generate`` 兼容的 worker 结果字典。
    """

    import os
    import tempfile
    import time as _time

    from api.structured_logging import get_logger
    from config import TEMP_DIR
    from core.model_surface.assembly import (
        MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY,
    )
    from core.model_surface.pipeline import build_surface_overlay_scene
    from core.model_surface.serialization import surface_footprint_from_payload
    from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

    log = get_logger(__name__)
    normalized_params = _normalize_puzzle_piece_target_width(image_path, params)
    converter_params = dict(normalized_params.get("converter_params") or {})
    if not converter_params:
        converter_params = {
            key: value
            for key, value in normalized_params.items()
            if not str(key).startswith("surface_") and key != "converter_params"
        }
    # Keep the worker entry point safe when called outside the HTTP router.
    # A model surface has one display side; a second colour stack would be
    # embedded behind the uploaded body and reappear in upper slicer layers.
    converter_params["structure_mode"] = "Single-sided"
    converter_params["enable_relief"] = False
    converter_params["enable_cloisonne"] = False
    converter_params["enable_coating"] = False
    if int(converter_params.get("backing_infill_density_percent", 100)) < 100:
        raise ValueError(
            "Sparse backing infill is not supported for model surface generation."
        )

    footprint_payload = normalized_params.get("surface_footprint")
    if not isinstance(footprint_payload, dict):
        raise ValueError("surface_footprint must be a JSON object")

    footprint = surface_footprint_from_payload(footprint_payload)
    pocket_depth_mm = float(normalized_params.get("surface_pocket_depth_mm", 0.4))
    model_path = str(normalized_params["surface_model_path"])
    model_transform = normalized_params.get("surface_model_transform")
    if model_transform is not None and not isinstance(model_transform, dict):
        raise ValueError("surface_model_transform must be a JSON object")
    _t_worker_start = _time.perf_counter()
    out_path: str | None = None
    export_ready = False
    log.debug(
        "Worker model-surface generation started",
        extra={
            "event": "worker_model_surface_started",
            "image_name": os.path.basename(image_path),
            "model_name": os.path.basename(model_path),
            "target_width_mm": converter_params.get("target_width_mm"),
            "color_mode": converter_params.get("color_mode"),
            "pocket_depth_mm": pocket_depth_mm,
        },
    )
    try:
        overlay = build_surface_overlay_scene(
            model_path=model_path,
            artwork_image_path=image_path,
            lut_path=lut_path,
            converter_params=converter_params,
            footprint=footprint,
            pocket_depth_mm=pocket_depth_mm,
            model_transform=model_transform,
        )
        display_layer_height_mm = _resolve_model_surface_display_layer_height_mm(
            converter_params,
            actual_layer_heights_mm=overlay.scene.metadata.get(
                MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY
            ),
        )
        fd, out_path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR)
        os.close(fd)
        cover_source = _resolve_model_surface_cover_source(
            image_path,
            target_width_mm=float(
                converter_params.get("target_width_mm", 60.0)
            ),
            log=log,
        )
        export_scene_with_bambu_metadata(
            scene=overlay.scene,
            output_path=out_path,
            slot_names=overlay.slot_names,
            preview_colors=overlay.preview_colors,
            project_slot_names=overlay.project_slot_names,
            material_types=overlay.scene.metadata.get("material_types"),
            external_spool_material=normalized_params.get("external_spool_material"),
            native_filament_profiles=normalized_params.get("native_filament_profiles"),
            preserve_template_filament_slots=(
                False if converter_params.get("material_source") == "material_archive" else None
            ),
            settings={"layer_height": f"{display_layer_height_mm:g}"},
            color_mode=str(converter_params.get("color_mode", "4-Color")),
            printer_id=str(normalized_params.get("printer_id", "bambu-h2d")),
            custom_3mf_template_id=normalized_params.get("custom_3mf_template_id"),
            slicer=str(normalized_params.get("slicer", "BambuStudio")),
            nozzle_size=str(normalized_params.get("nozzle_size", "0.4")),
            cover_source=cover_source,
            device_profile_id=normalized_params.get("device_profile_id") or None,
            build_plate_id=normalized_params.get("build_plate_id") or None,
            enable_base_layer_height_modifier=False,
            enable_wipe_tower_auto_placement=bool(
                converter_params.get("enable_wipe_tower_auto_placement", True)
            ),
        )
        export_ready = True
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        if out_path and not export_ready:
            _cleanup_worker_temp_paths(out_path)
        log.exception(
            "Worker model-surface generation failed",
            extra={
                "event": "worker_model_surface_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise

    log.debug(
        "Worker model-surface generation complete",
        extra={
            "event": "worker_model_surface_done",
            "duration_ms": round((_time.perf_counter() - _t_worker_start) * 1000, 3),
            "threemf_path": out_path,
            "threemf_bytes": os.path.getsize(out_path) if out_path and os.path.exists(out_path) else None,
            "slot_count": len(overlay.slot_names),
        },
    )
    return {
        "threemf_path": out_path,
        "glb_path": None,
        "status_msg": "Surface overlay model generated",
    }


def _resolve_model_surface_cover_source(
    image_path: str,
    *,
    target_width_mm: float,
    log: logging.Logger,
) -> str | bytes | None:
    """Return a writer-compatible cover source for model-surface exports."""

    from pathlib import Path

    if Path(image_path).suffix.lower() != ".svg":
        return image_path

    from io import BytesIO

    import numpy as np
    from PIL import Image

    from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg

    try:
        cover_rgba = rasterize_svg(
            image_path,
            float(target_width_mm),
            pixels_per_mm=2.0,
            crop_to_content=False,
            _min_quality_px=1,
            _max_longest_px=512,
            _cache_result=False,
        )
        cover_image = Image.fromarray(
            np.asarray(cover_rgba, dtype=np.uint8),
            mode="RGBA",
        )
        cover_buffer = BytesIO()
        cover_image.save(cover_buffer, format="PNG", optimize=False)
        return cover_buffer.getvalue()
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        log.warning(
            "Model-surface SVG cover render failed; using placeholder",
            extra={
                "event": "model_surface_cover_render_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": image_path,
            },
        )
        return None


def _resolve_model_surface_display_layer_height_mm(
    converter_params: dict,
    *,
    actual_layer_heights_mm: object = None,
) -> float:
    """Resolve the uniform slicer layer height for a surface display stack.

    解析模型覆面展示层栈当前使用的统一切片层高。
    """

    import math

    from config import PrinterConfig

    raw_schedule = actual_layer_heights_mm
    if raw_schedule is None:
        raw_schedule = converter_params.get("display_layer_heights_mm")
    if raw_schedule is not None:
        try:
            schedule = tuple(float(value) for value in raw_schedule)
        except (TypeError, ValueError) as exc:
            raise ValueError("Model-surface display layer heights are invalid.") from exc
        if not schedule or any(
            not math.isfinite(value) or value <= 0.0 for value in schedule
        ):
            raise ValueError(
                "Model-surface display layer heights must be positive and finite."
            )
        if any(abs(value - schedule[0]) > 1e-9 for value in schedule[1:]):
            raise ValueError(
                "Model-surface non-uniform display layer heights require "
                "slicer range metadata support."
            )
        return schedule[0]

    material_source = str(converter_params.get("material_source") or "lut")
    raw_height = converter_params.get("layer_height_mm")
    if material_source == "material_archive":
        archive_height = converter_params.get("material_layer_height_mm")
        if archive_height is not None:
            raw_height = archive_height
    if raw_height is None:
        raw_height = PrinterConfig.LAYER_HEIGHT
    try:
        height_mm = float(raw_height)
    except (TypeError, ValueError) as exc:
        raise ValueError("Model-surface display layer height must be a number.") from exc
    if not math.isfinite(height_mm) or height_mm <= 0.0:
        raise ValueError("Model-surface display layer height must be positive and finite.")
    return height_mm


def worker_generate_large_format_svg_native(
    image_path: str,
    lut_path: str,
    params: dict,
) -> dict:
    """Generate a large-format ZIP from one globally analyzed SVG in a worker.

    大画幅 SVG 矢量模式：在 worker 进程里一次完成全图分析、按 grid 切片、
    每个 tile 导出 3MF（含封面缩略图），最后打包成 ZIP。

    Returned counters:
        ``tile_count``: tiles written into the ZIP. Includes tiles whose
            cover thumbnail rasterization raised — those still export a 3MF
            with the silent placeholder cover.
        ``tile_skipped_empty``: tiles dropped because their geometry was
            empty (slicer-stage drop or post-build empty scene). Silent —
            no WARNING.
        ``tile_failed_cover``: quality indicator on ``tile_count`` — number
            of written tiles whose cover defaulted to the placeholder due
            to a rasterize exception. **Subset of ``tile_count``,
            not a separate bucket.** Each increment is paired with one
            ``bambu_3mf_cover_thumbnail_failed`` WARNING.

    Invariant: ``tile_count + tile_skipped_empty == grid_cols * grid_rows``.
    """
    import math
    import os
    import tempfile
    import zipfile

    import numpy as np
    from PIL import Image

    from api.structured_logging import get_logger
    from config import TEMP_DIR
    from core.pipeline._input_validation_common import (
        _apply_material_archive_branch,
    )
    from core.pipeline.preview_color_utils import build_lut_material_types
    from core.pipeline.vector_branch import (
        _build_vector_processor,
        _generate_vector_outline_mesh,
        _resolve_vector_outline_base_aux_style,
        _resolve_vector_layer_height_mm,
        _update_bambu_base_layer_ctx_for_vector,
    )
    from core.vector_structure import resolve_structure_plan
    from core.vector_engine import (
        _concatenate_meshes_fast,
        apply_matched_rgb_overrides_to_analysis,
        apply_recipe_overrides_to_analysis,
    )
    from core.vector_large_format import (
        format_large_format_tile_label,
        resolve_large_format_grid_shape,
        slice_vector_analysis_into_tiles,
    )
    from utils.bambu_3mf_writer import (
        export_scene_with_bambu_metadata,
        read_wipe_tower_placement_warnings,
    )

    log = get_logger(__name__)

    tile_name_prefix = params.get("tile_name_prefix")
    total_width_mm = float(params["total_width_mm"])
    total_height_mm = float(params["total_height_mm"])
    tile_width_mm = float(params["tile_width_mm"])
    tile_height_mm = float(params["tile_height_mm"])
    replacement_regions = params.get("replacement_regions")
    # Preserve ColorReplacementItem records through the native SVG analysis so
    # dynamic material matching can project effective target colours before its
    # final geometry-weighted solve.
    vector_replacements = replacement_regions

    grid_cols, grid_rows = resolve_large_format_grid_shape(
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
        tile_width_mm=tile_width_mm,
        tile_height_mm=tile_height_mm,
    )
    expected_total_tiles = grid_cols * grid_rows

    material_source = str(params.get("material_source") or "lut")
    worker_ctx = dict(params)
    worker_ctx["actual_lut_path"] = lut_path
    if material_source == "material_archive":
        validation_outcome = _apply_material_archive_branch(
            worker_ctx,
            log=log,
            event_prefix="large_format_svg",
        )
        if validation_outcome == "error":
            raise ValueError(
                str(
                    worker_ctx.get("error")
                    or "Material archive validation failed for native SVG tiling"
                )
            )

    vector_processor = _build_vector_processor(
        worker_ctx,
        fallback_color_mode=str(params["color_mode"]),
    )
    layer_height_mm = _resolve_vector_layer_height_mm(worker_ctx)
    vector_processor.layer_height_mm = layer_height_mm
    vector_processor.enable_coating = bool(worker_ctx.get("enable_coating", False))
    vector_processor.coating_height_mm = float(
        worker_ctx.get("coating_height_mm", 0.08)
    )
    vector_processor.auto_dynamic_range = bool(params.get("auto_dynamic_range", False))
    analysis = vector_processor.analyze_svg(
        svg_path=image_path,
        target_width_mm=total_width_mm,
        color_replacements=vector_replacements,
    )
    if material_source != "material_archive":
        from utils.lut_manager import LUTManager

        _, _, lut_metadata = LUTManager.load_lut_with_metadata(lut_path)
        worker_ctx["material_types"] = build_lut_material_types(
            lut_metadata, analysis.slot_names,
        )
    from core.export_materials import configure_coating_material

    worker_ctx["slot_names"] = list(analysis.slot_names)
    worker_ctx["preview_colors"] = dict(analysis.preview_colors)
    vector_processor.coating_material = configure_coating_material(worker_ctx)
    matched_rgb_path = params.get("matched_rgb_path")
    mask_solid_path = params.get("mask_solid_path")
    material_matrix_path = params.get("material_matrix_path")
    if matched_rgb_path or mask_solid_path:
        loaded_arrays: list[np.ndarray] = []
        try:
            if not matched_rgb_path or not mask_solid_path or not material_matrix_path:
                raise ValueError(
                    "Native SVG cached overrides require matched_rgb, mask_solid, "
                    "and material_matrix inputs."
                )
            for cache_path in (
                matched_rgb_path,
                mask_solid_path,
                material_matrix_path,
            ):
                loaded = np.load(
                    str(cache_path),
                    mmap_mode="r",
                    allow_pickle=False,
                )
                if not isinstance(loaded, np.ndarray):
                    close_loaded = getattr(loaded, "close", None)
                    if callable(close_loaded):
                        close_loaded()
                    raise ValueError("Native SVG cached override is not a NumPy array")
                loaded_arrays.append(loaded)

            matched_rgb, mask_solid, material_matrix = loaded_arrays
            if matched_rgb.ndim != 3:
                raise ValueError("Native SVG matched_rgb cache must be 3-dimensional")
            analysis_width_mm = float(analysis.bbox[2]) * float(
                analysis.scale_factor
            )
            if analysis_width_mm <= 0:
                raise ValueError("Native SVG analysis width must be positive")
            cache_pixels_per_mm = float(matched_rgb.shape[1]) / analysis_width_mm
            apply_matched_rgb_overrides_to_analysis(
                analysis,
                matched_rgb=matched_rgb,
                mask_solid=mask_solid,
                material_matrix=material_matrix,
                img_processor=vector_processor.img_processor,
                pixels_per_mm=cache_pixels_per_mm,
                max_width_px=int(matched_rgb.shape[1]),
                strict=True,
                prefer_cached_material_state=bool(
                    worker_ctx.get("material_dynamic_layer_count_enabled", False)
                    and material_source == "material_archive"
                ),
            )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            EOFError,
            zipfile.BadZipFile,
        ) as exc:
            raise LargeFormatCachedAnalysisError(str(exc)) from exc
        finally:
            for loaded in loaded_arrays:
                mmap_obj = getattr(loaded, "_mmap", None)
                if mmap_obj is not None and not getattr(mmap_obj, "closed", False):
                    mmap_obj.close()

    recipe_overrides = params.get("recipe_overrides") or []
    recipe_override_masks_path = params.get("recipe_override_masks_path")
    if recipe_overrides and recipe_override_masks_path:
        import pickle

        try:
            with open(str(recipe_override_masks_path), "rb") as mask_file:
                region_masks = pickle.load(mask_file)
            if not isinstance(region_masks, dict) or not region_masks:
                raise ValueError("Native SVG recipe override masks are missing")

            override_region_ids = {
                str(item.get("region_id") or "").strip()
                for item in recipe_overrides
                if isinstance(item, dict)
            }
            override_region_ids.discard("")
            missing_region_ids = sorted(
                region_id
                for region_id in override_region_ids
                if region_id not in region_masks
            )
            if missing_region_ids:
                raise ValueError(
                    "Native SVG recipe override masks are incomplete"
                )

            normalized_masks = {
                str(region_id): np.asarray(mask, dtype=bool)
                for region_id, mask in region_masks.items()
            }
            mask_shapes = {
                tuple(mask.shape)
                for mask in normalized_masks.values()
                if mask.ndim == 2
            }
            if (
                len(mask_shapes) != 1
                or any(mask.ndim != 2 for mask in normalized_masks.values())
            ):
                raise ValueError(
                    "Native SVG recipe override masks must share one 2D grid"
                )

            mask_height_px, mask_width_px = next(iter(mask_shapes))
            if mask_width_px <= 0 or mask_height_px <= 0:
                raise ValueError(
                    "Native SVG recipe override mask dimensions must be positive"
                )
            analysis_width_mm = float(analysis.bbox[2]) * float(
                analysis.scale_factor
            )
            analysis_height_mm = float(analysis.bbox[3]) * float(
                analysis.scale_factor
            )
            if analysis_width_mm <= 0 or analysis_height_mm <= 0:
                raise ValueError("Native SVG analysis dimensions must be positive")
            recipe_pixels_per_mm = float(mask_width_px) / analysis_width_mm
            expected_mask_height = max(
                1,
                int(round(analysis_height_mm * recipe_pixels_per_mm)),
            )
            if expected_mask_height != mask_height_px:
                raise ValueError(
                    "Native SVG recipe override mask aspect ratio does not "
                    "match the vector analysis"
                )

            apply_recipe_overrides_to_analysis(
                analysis,
                recipe_overrides=recipe_overrides,
                region_masks=normalized_masks,
                target_layers=worker_ctx.get("color_layers"),
                base_channel_idx=int(
                    worker_ctx.get("material_base_channel_idx")
                    if worker_ctx.get("material_base_channel_idx") is not None
                    else worker_ctx.get("base_channel_idx", 0)
                ),
                pixels_per_mm=recipe_pixels_per_mm,
                max_width_px=int(mask_width_px),
                img_processor=vector_processor.img_processor,
            )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            EOFError,
            pickle.PickleError,
        ) as exc:
            raise LargeFormatCachedAnalysisError(str(exc)) from exc

    try:
        analysis_num_layers = int(analysis.num_layers)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(
            "Native SVG analysis must provide a valid num_layers value"
        ) from exc
    if analysis_num_layers < 0:
        raise ValueError(
            "Native SVG analysis num_layers must not be negative"
        )
    _update_bambu_base_layer_ctx_for_vector(
        worker_ctx,
        color_mode=vector_processor.color_mode,
        structure_mode=str(params["structure_mode"]),
        num_layers=analysis_num_layers,
        thickness_mm=float(params["spacer_thick"]),
        layer_height_mm=layer_height_mm,
    )

    vector_processor.enable_outline = bool(params.get("enable_outline", False))
    vector_processor.outline_width_mm = float(params.get("outline_width", 2.0))
    vector_processor.enable_coating = bool(params.get("enable_coating", False))
    vector_processor.coating_height_mm = float(params.get("coating_height_mm", 0.08))
    analysis.structure_plan = resolve_structure_plan(
        analysis, vector_processor.outline_width_mm if vector_processor.enable_outline else 0.0,
    )
    tile_analyses = slice_vector_analysis_into_tiles(
        analysis=analysis,
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
        tile_width_mm=tile_width_mm,
        tile_height_mm=tile_height_mm,
        materialize=False,
    )

    # Tiles dropped at slicing time (entirely empty geometry within the
    # tile bounds) count as "skipped empty", not "failed cover".
    # 切片阶段已经被丢弃的空 tile 计入 tile_skipped_empty，与封面失败区分。
    tile_skipped_empty = 0
    sliced_tile_count = 0
    tile_failed_cover = 0

    # Resolve the backing material slot once; tiles share the palette.
    # 底板材质槽在整批 tile 中共用，解析一次即可。
    raw_backing_color_id = params.get("backing_color_id", 0)
    if material_source == "material_archive":
        raw_backing_color_id = params.get("material_backing_material_index")
        if raw_backing_color_id is None:
            raw_backing_color_id = worker_ctx.get("material_base_channel_idx", 0)
    try:
        requested_backing_color_id = int(raw_backing_color_id or 0)
    except (TypeError, ValueError):
        requested_backing_color_id = 0

    layer_height_setting = f"{layer_height_mm:g}"

    successful_paths: list[tuple[str, str]] = []
    tile_warnings: list[str] = []
    tile_cleanup_paths: set[str] = set()
    zip_path: str | None = None
    zip_ready = False
    full_heightmap = None
    if bool(params.get("enable_relief", False)) and str(
        params.get("height_mode") or "color"
    ).lower() == "heightmap":
        heightmap_path = params.get("heightmap_path")
        if not heightmap_path:
            raise ValueError(
                "Native SVG large-format heightmap relief requires heightmap_path"
            )
        with Image.open(str(heightmap_path)) as heightmap_image:
            full_heightmap = heightmap_image.convert("L").copy()
    try:
        for tile in tile_analyses:
            sliced_tile_count += 1
            tile_processor = vector_processor
            tile_heightmap_path = None
            heightmap_tile = None
            scene = None
            board_geom = None
            target_geom = None
            merged = None
            geom = None
            tile_cover = None
            if full_heightmap is not None:
                hm_width, hm_height = full_heightmap.size
                px_x0 = int(round(tile.spec.x0_mm / total_width_mm * hm_width))
                px_y0 = int(round(tile.spec.y0_mm / total_height_mm * hm_height))
                px_x1 = int(round(tile.spec.x1_mm / total_width_mm * hm_width))
                px_y1 = int(round(tile.spec.y1_mm / total_height_mm * hm_height))
                px_x0 = min(max(px_x0, 0), max(hm_width - 1, 0))
                px_y0 = min(max(px_y0, 0), max(hm_height - 1, 0))
                px_x1 = min(max(px_x1, px_x0 + 1), hm_width)
                px_y1 = min(max(px_y1, px_y0 + 1), hm_height)
                heightmap_tile = full_heightmap.crop((px_x0, px_y0, px_x1, px_y1))
                fd_heightmap, tile_heightmap_path = tempfile.mkstemp(
                    suffix=".png",
                    dir=TEMP_DIR,
                )
                os.close(fd_heightmap)
                tile_cleanup_paths.add(tile_heightmap_path)
                heightmap_tile.save(tile_heightmap_path)
            separate_backing = bool(params.get("separate_backing", False))
            tile_processor._merge_backing_into_material = not separate_backing
            scene = tile_processor.build_mesh(
                analysis=tile.analysis,
                thickness_mm=float(params["spacer_thick"]),
                structure_mode=params["structure_mode"],
                backing_color_id=requested_backing_color_id,
                enable_relief=bool(params.get("enable_relief", False)),
                height_mode=str(params.get("height_mode") or "color"),
                color_height_map=params.get("color_height_map"),
                heightmap_path=tile_heightmap_path,
                heightmap_max_height=params.get("heightmap_max_height"),
            )
            if len(scene.geometry) == 0:
                # Empty downstream geometry: same semantics as a slicing-time
                # empty tile — the tile is silently dropped.
                # 下游构建后几何为空：与切片阶段的空 tile 同义，静默跳过。
                tile_skipped_empty += 1
                scene = None
                heightmap_tile = None
                tile = None
                continue

            preview_colors = dict(tile.analysis.preview_colors)
            if coating_material := worker_ctx.get("resolved_coating_material"):
                preview_colors[coating_material.name] = [*coating_material.rgb, 255]
            slot_names = list(tile.analysis.slot_names)
            if vector_processor.enable_outline:
                outline_color, outline_material = _resolve_vector_outline_base_aux_style(
                    worker_ctx, preview_colors, slot_names,
                )
                outline = _generate_vector_outline_mesh(
                    tile.analysis, vector_processor.outline_width_mm,
                    outline_color, outline_material, worker_ctx,
                    export_color_mode=vector_processor.color_mode,
                )
                if outline is not None:
                    scene.add_geometry(outline, geom_name="Outline", node_name="Outline")
                    preview_colors["Outline"] = outline_color
            for material_id, rgba in list(preview_colors.items()):
                if isinstance(material_id, int) and material_id < len(slot_names):
                    preview_colors[slot_names[material_id]] = rgba

            # Clamp the backing slot index for this tile in case the palette
            # differs (defensive; normally tiles share the same slot list).
            # 为当前 tile 钳制底板槽位索引；一般情况下所有 tile 调色板一致。
            tile_backing_slot_index = 0
            if slot_names and 0 <= requested_backing_color_id < len(slot_names):
                tile_backing_slot_index = requested_backing_color_id
            target_slot = slot_names[tile_backing_slot_index] if slot_names else None

            board_geom = scene.geometry.get("Board")
            if board_geom is not None and not separate_backing:
                target_geom = scene.geometry.get(target_slot) if target_slot else None
                if target_geom is not None:
                    merged = _concatenate_meshes_fast(
                        [target_geom, board_geom],
                    )
                    merged.visual.face_colors = target_geom.visual.face_colors
                    merged.metadata["name"] = target_slot
                    merged.metadata["bambu_material_name"] = target_slot
                    scene.geometry[target_slot] = merged
                    del scene.geometry["Board"]
                    # The scene owns the merged mesh now. Release both source
                    # arrays before the native writer allocates its own copy.
                    del target_geom, board_geom, merged
                elif target_slot:
                    backing_color = preview_colors.get(
                        target_slot,
                        preview_colors.get(
                            tile_backing_slot_index,
                            [255, 255, 255, 255],
                        ),
                    )
                    board_geom.visual.face_colors = backing_color
                    board_geom.metadata["name"] = target_slot
                    board_geom.metadata["bambu_material_name"] = target_slot
                    scene.geometry[target_slot] = board_geom
                    del scene.geometry["Board"]
            elif board_geom is not None and separate_backing:
                preview_colors["Board"] = preview_colors.get(
                    tile_backing_slot_index,
                    preview_colors.get(0, [255, 255, 255, 255]),
                )
                if target_slot:
                    board_geom.metadata["bambu_material_name"] = target_slot

            slot_export_names: list[str] = []
            for geom_name, geom in scene.geometry.items():
                vertices = getattr(geom, "vertices", None)
                faces = getattr(geom, "faces", None)
                if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
                    continue
                slot_export_names.append(geom_name)
            if not slot_export_names:
                tile_skipped_empty += 1
                scene = None
                board_geom = None
                target_geom = None
                merged = None
                geom = None
                heightmap_tile = None
                tile = None
                continue

            fd, tile_3mf_path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR)
            os.close(fd)
            tile_cleanup_paths.add(tile_3mf_path)

            # Rasterize the tile region for its 3MF cover thumbnail.
            # ``_rasterize_tile_for_cover`` runs the heavy ``rasterize_svg``
            # call in a hard-killable spawn subprocess (see
            # ``_run_rasterize_canvas_in_subprocess``) with a 10s timeout
            # and a parent-process canvas cache, so:
            #
            # - First tile pays the spawn + rasterize cost; remaining
            #   tiles in the same worker invocation hit
            #   ``_TILE_COVER_CANVAS_CACHE`` and skip the subprocess
            #   entirely.
            #
            # On RuntimeError (subprocess crashed or could not be spawned)
            # we bump ``tile_failed_cover``, log a single
            # structured WARNING, and fall through with
            # ``tile_cover = None`` so the writer emits the silent
            # placeholder cover and the printable tile still reaches the
            # ZIP. ``tile_failed_cover`` is a quality indicator on the
            # written tile, not a "skipped" bucket.
            #
            # 用 spawn 子进程跑栅格化并复用父进程整图缓存；后续 tile
            # 命中缓存不再 spawn；真实崩溃时 tile 仍然进 ZIP，封面回落
            # 到静默占位，``tile_failed_cover`` 只是质量指标。
            tile_cover = None
            try:
                tile_cover = _rasterize_tile_for_cover(
                    tile,
                    image_path,
                    total_width_mm,
                    total_height_mm,
                )
            except MemoryError:
                raise
            except Exception as exc:  # noqa: BLE001 — bound rasterize errors per R5.4
                tile_cover = None
                tile_failed_cover += 1
                log.warning(
                    "Bambu 3MF cover thumbnail tile rasterization "
                    "failed; exporting tile with placeholder cover",
                    extra={
                        "event": "bambu_3mf_cover_thumbnail_failed",
                        "path": str(tile_3mf_path),
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:2048],
                        "fallback_action": "placeholder_written",
                    },
                )

            export_scene_with_bambu_metadata(
                scene=scene,
                output_path=tile_3mf_path,
                slot_names=slot_export_names,
                preview_colors=preview_colors,
                settings={
                    "layer_height": layer_height_setting,
                    "initial_layer_height": layer_height_setting,
                },
                color_mode=tile_processor.color_mode,
                printer_id=params.get("printer_id", "bambu-h2d"),
                slicer=params.get("slicer", "BambuStudio"),
                nozzle_size=params.get("nozzle_size", "0.4"),
                project_slot_names=slot_names,
                material_types=worker_ctx.get("material_types"),
                external_spool_material=params.get("external_spool_material"),
                native_filament_profiles=params.get("native_filament_profiles"),
                enable_base_layer_height_modifier=bool(
                    worker_ctx.get("enable_base_layer_height_modifier", True)
                ),
                enable_wipe_tower_auto_placement=bool(
                    worker_ctx.get("enable_wipe_tower_auto_placement", True)
                ),
                enable_relief=bool(worker_ctx.get("enable_relief", False)),
                base_height_mm=float(
                    worker_ctx.get("bambu_base_height_mm", 0.0)
                ),
                color_height_mm=float(
                    worker_ctx.get("bambu_color_height_mm", 0.0)
                ),
                face_orientation=str(
                    worker_ctx.get("bambu_face_orientation", "down")
                ),
                backing_infill_density_percent=int(
                    params.get("backing_infill_density_percent", 100)
                ),
                cover_source=tile_cover,
                device_profile_id=params.get("device_profile_id") or None,
                custom_3mf_template_id=params.get("custom_3mf_template_id") or None,
                build_plate_id=params.get("build_plate_id") or None,
                preserve_template_filament_slots=(
                    False if material_source == "material_archive" else None
                ),
            )
            for warning_code in read_wipe_tower_placement_warnings(tile_3mf_path):
                if warning_code not in tile_warnings:
                    tile_warnings.append(warning_code)
            successful_paths.append(
                (
                    format_large_format_tile_label(source_basename=tile_name_prefix, tile_label=tile.label),
                    tile_3mf_path,
                )
            )
            # Do not retain a completed tile while the next build allocates
            # its full scene. The written 3MF path is the only cross-iteration
            # state needed from this point onward.
            tile_cover = None
            scene = None
            board_geom = None
            target_geom = None
            merged = None
            geom = None
            heightmap_tile = None
            tile = None

        tile_skipped_empty += max(
            0,
            expected_total_tiles - sliced_tile_count,
        )
        if not successful_paths:
            raise ValueError("All SVG large-format tiles were empty after slicing.")

        fd, zip_path = tempfile.mkstemp(suffix=".zip", dir=TEMP_DIR)
        os.close(fd)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for label, path_3mf in successful_paths:
                zf.write(path_3mf, f"{label}.3mf")
        zip_ready = True

        tile_count = len(successful_paths)
        # R5.6 invariant (updated semantics): every grid cell maps to
        # exactly one of {written-to-zip, sliced-empty}. ``tile_count``
        # now includes tiles whose cover defaulted to the silent
        # placeholder (cover-failed); ``tile_failed_cover`` is a quality
        # indicator on the *written* subset, not a separate bucket.
        # R5.6 不变量（新语义）：每个网格 cell 要么写进 ZIP，要么是切片
        # 阶段就被丢弃的空 tile。``tile_count`` 包含封面失败回落到占位
        # 的 tile；``tile_failed_cover`` 只是其中"封面用了占位"的质量
        # 指标，不再是独立桶。
        assert tile_count + tile_skipped_empty == expected_total_tiles, (
            f"tile counts mismatch: {tile_count} + {tile_skipped_empty} != "
            f"{expected_total_tiles} (tile_failed_cover={tile_failed_cover})"
        )

        return {
            "zip_path": zip_path,
            "tile_count": tile_count,
            "tile_skipped_empty": tile_skipped_empty,
            "tile_failed_cover": tile_failed_cover,
            "grid_cols": grid_cols,
            "grid_rows": grid_rows,
            "warnings": tile_warnings,
        }
    finally:
        for path_3mf in tile_cleanup_paths:
            if os.path.exists(path_3mf):
                os.unlink(path_3mf)
        if zip_path is not None and not zip_ready and os.path.exists(zip_path):
            os.unlink(zip_path)
