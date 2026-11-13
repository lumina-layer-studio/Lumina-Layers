"""
P03 — Core image processing (quantization + LUT matching).
P03 — 核心图像处理（量化 + LUT 匹配）。

从 generate_preview_cached 函数搬入的逻辑，包括：
- 创建 LuminaImageProcessor 实例
- 调用 process_image 进行图像处理
- 提取处理结果（matched_rgb, material_matrix, mask_solid 等）
- Material-archive 模式：跳过 LUT 匹配，使用 beam-search 耗材求解器
"""


from copy import deepcopy

from api.structured_logging import get_logger
import time

import numpy as np

from config import (
    SVG_PIXELS_PER_MM_DEFAULT,
    ModelingMode,
    normalize_svg_pixels_per_mm,
)
from core.material_layer_fallback_policy import should_run_cross_n_fallback
from core.pipeline.processing_ops.color_histogram import count_visible_rgb

_log = get_logger(__name__)


def _snap_svg_to_fill_palette(
    *,
    rgb_arr: np.ndarray,
    mask_transparent: np.ndarray,
    quantize_budget: int,
    coverage_threshold: float = 0.99,
) -> np.ndarray:
    """Collapse a rasterized SVG into its true fill palette via KDTree snap.
    将栅格化后的 SVG 还原到真实填充色板，避免抗锯齿过渡带产生杂色配方。

    The SVG → resvg → numpy pipeline produces anti-aliased edges where
    neighbouring fill colors linearly blend. Critically, when the SVG has
    an opaque background, the AA blending happens entirely in RGB while
    alpha stays at 255 — so an alpha-based heuristic cannot distinguish
    fills from edge blends. Instead we exploit the fact that **real fills
    cover large contiguous regions while AA pixels are spread thin** (each
    unique blend RGB appears only at pixel-thick transitions).

    Algorithm:

    1. Build a histogram over visible (non-transparent) pixels: ``(unique
       RGB, count)``.
    2. Sort by count descending and take the smallest prefix whose
       cumulative count covers ``coverage_threshold`` of visible pixels.
       For SVGs with N pure fills, this prefix is exactly the N fills (AA
       contributes <1% in aggregate). For gradient SVGs, the prefix grows
       gracefully with the gradient's pixel count distribution.
    3. Cap by ``quantize_budget`` so the user's quantize cap still binds.
    4. KDTree-snap every visible pixel to its nearest selected fill.
       Transparent pixels are reassigned to ``fill_palette[0]`` so they
       don't pollute ``unique_colors`` (they'll be set to -1 in the
       material matrix later anyway).

    Args:
        rgb_arr: ``(H, W, 3)`` uint8 RGB after rasterization (no alpha).
        mask_transparent: ``(H, W)`` bool — pixels already classified as
            transparent (``alpha < 10`` plus auto-bg results).
        quantize_budget: Upper bound on resulting unique colors. The user's
            ``quantize_colors`` setting from the request.
        coverage_threshold: Cumulative pixel fraction that the fill palette
            must explain. Defaults to 0.99 — empirically this captures all
            real fills of a typical multi-color SVG while excluding the
            sub-1% noise floor of anti-aliased edge blends.

    Returns:
        ``(H, W, 3)`` uint8 image with at most ``min(len(fill_palette),
        quantize_budget)`` distinct RGB values.
    """
    from scipy.spatial import KDTree

    visible_mask = ~mask_transparent
    if not np.any(visible_mask):
        return rgb_arr.copy()

    visible_pixels = rgb_arr[visible_mask].reshape(-1, 3)
    unique_rgb, counts = np.unique(visible_pixels, axis=0, return_counts=True)

    # Sort by frequency descending. Real fills are dense; AA pixels are rare.
    order = np.argsort(-counts)
    unique_rgb = unique_rgb[order]
    counts = counts[order]

    total_visible = int(visible_pixels.shape[0])
    cumulative = np.cumsum(counts)
    coverage_cap = int(np.searchsorted(cumulative, total_visible * coverage_threshold)) + 1
    fill_count = max(1, min(coverage_cap, int(quantize_budget), int(unique_rgb.shape[0])))
    fill_palette = unique_rgb[:fill_count]

    _log.debug(
        "SVG fill palette: %d/%d unique RGB selected (coverage=%.3f, budget=%d)",
        fill_count,
        unique_rgb.shape[0],
        coverage_threshold,
        quantize_budget,
    )

    quantized_image = np.empty_like(rgb_arr)
    tree = KDTree(fill_palette.astype(np.float32))
    _, idx = tree.query(visible_pixels.astype(np.float32))
    quantized_image[visible_mask] = fill_palette[idx]
    # Transparent pixels: assign palette[0] so they share an existing
    # ``unique_colors`` entry (they'll be masked out via material_matrix=-1).
    if np.any(mask_transparent):
        quantized_image[mask_transparent] = fill_palette[0]
    return quantized_image


def _load_dynamic_preview_analysis(
    ctx: dict,
    *,
    max_layer_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """Load the complete dynamic preview analysis for a puzzle worker.
    为拼图 worker 加载完整的动态预览分析资产。

    This is deliberately narrower than the LUT preview reuse path. Dynamic
    material matrices are authoritative solver output: recreating them from
    ``matched_rgb`` would silently discard accepted recipe overrides or
    virtual-material choices. Only callers that explicitly request reuse and
    provide all four persisted arrays may take this path.
    该分支比 LUT 预览复用更严格。动态耗材矩阵是权威求解结果；仅用
    ``matched_rgb`` 重算会静默丢失已确认的配方覆盖或虚拟耗材选择。只有明确
    请求复用且提供全部四个持久化数组的调用方才能进入该路径。

    Args:
        ctx: Pipeline context containing the four ``.npy`` asset paths.
            (包含四个 ``.npy`` 资产路径的流水线上下文)
        max_layer_count: Required physical matrix depth for dynamic mode.
            (动态模式要求的物理矩阵层深)

    Returns:
        tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
            ``matched_rgb``, ``mask_solid``, ``quantized_image``, and the
            authoritative ``material_matrix``; ``None`` when reuse was not
            requested. (依次为 ``matched_rgb``、``mask_solid``、
            ``quantized_image`` 与权威 ``material_matrix``；未请求复用时
            返回 ``None``)

    Raises:
        ValueError: If an asset is absent or its shape/dtype is inconsistent.
            (资产缺失或其形状/数据类型不一致时抛出)
        OSError: If a persisted asset cannot be read. (无法读取持久化资产时抛出)
    """

    if not (
        bool(ctx.get("reuse_preview_analysis"))
        and bool(ctx.get("material_dynamic_layer_count_enabled"))
    ):
        return None

    paths = {
        "matched_rgb": ctx.get("matched_rgb_path"),
        "mask_solid": ctx.get("mask_solid_path"),
        "quantized_image": ctx.get("quantized_image_path"),
        "material_matrix": ctx.get("material_matrix_path"),
    }
    missing = [name for name, path in paths.items() if not isinstance(path, str) or not path]
    if missing:
        raise ValueError(
            "dynamic preview-analysis reuse requires "
            + ", ".join(sorted(missing))
        )

    matched_rgb = np.load(paths["matched_rgb"], allow_pickle=False)
    mask_solid = np.load(paths["mask_solid"], allow_pickle=False)
    quantized_image = np.load(paths["quantized_image"], allow_pickle=False)
    material_matrix = np.load(paths["material_matrix"], allow_pickle=False)

    if (
        matched_rgb.dtype != np.uint8
        or matched_rgb.ndim != 3
        or matched_rgb.shape[2] != 3
    ):
        raise ValueError("dynamic preview matched_rgb must be HxWx3 uint8")
    image_shape = matched_rgb.shape[:2]
    if mask_solid.dtype != np.bool_ or mask_solid.shape != image_shape:
        raise ValueError("dynamic preview mask_solid must be HxW bool")
    if quantized_image.dtype != np.uint8 or quantized_image.shape != matched_rgb.shape:
        raise ValueError("dynamic preview quantized_image must match matched_rgb")
    if (
        material_matrix.dtype != np.int32
        or material_matrix.ndim != 3
        or material_matrix.shape[:2] != image_shape
        or material_matrix.shape[2] != int(max_layer_count)
    ):
        raise ValueError(
            "dynamic preview material_matrix must be HxWxmax_layer_count int32"
        )
    return matched_rgb, mask_solid, quantized_image, material_matrix


def _run_material_archive_branch(ctx: dict) -> dict:
    """Material-archive processing: quantize image, solve recipes via runtime.
    耗材档案模式处理：量化图像，通过求解运行时生成配方。

    Solver selection:
      1. Dynamic mode delegates all sorted targets to the exact CIEDE2000
         dynamic solver and consumes fixed-width padded recipes.
      2. Fixed mode tries a persisted
         :class:`core.material_cache.MaterialSolverCache`.
      3. When no persisted fixed cache exists, build a bounded runtime and
         resolve recipes through the shared ``lookup`` contract.
    The choice is recorded in ``ctx["material_solver_info"]`` so the UI can
    show whether the cache was used.
    """
    from PIL import Image

    from core.material_cache import DEFAULT_GRID_RESOLUTION
    from core.material_lut_provider import load_solver_cache, load_solver_runtime
    from core.material_lut_synthesis import (
        ensure_not_worse_than_smaller_N,
        map_pixels_to_materials,
    )
    from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter
    from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors as kmeans_quantize
    from core.pipeline.processing_ops.median_filter import apply_median_filter

    _t0 = time.perf_counter()

    image_path = ctx["image_path"]
    target_width_mm = ctx["target_width_mm"]
    modeling_mode = ctx["modeling_mode"]
    quantize_colors_n = ctx["quantize_colors"]
    materials = ctx["_material_params"]
    fixed_layer_count = int(ctx.get("color_layers") or 5)
    dynamic_layer_count_enabled = bool(
        ctx.get("material_dynamic_layer_count_enabled", False)
    )
    # Keep disabled-mode compatibility exact: stale or malformed dynamic-only
    # values are ignored unless the feature is enabled. The solver config owns
    # validation and normalization when dynamic mode is active.
    dynamic_min_layer_count = ctx.get("material_min_layer_count", 5)
    dynamic_max_layer_count = ctx.get("material_max_layer_count", 10)
    dynamic_delta_e00_tolerance = ctx.get("material_delta_e00_tolerance", 0.5)
    layer_count = fixed_layer_count
    layer_height_mm = float(ctx.get("layer_height_mm") or 0.08)
    substrate = str(ctx.get("material_substrate") or "white")
    requested_grid = int(ctx.get("grid_resolution") or DEFAULT_GRID_RESOLUTION)

    reused_analysis = None
    if dynamic_layer_count_enabled and bool(ctx.get("reuse_preview_analysis")):
        try:
            reused_analysis = _load_dynamic_preview_analysis(
                ctx,
                max_layer_count=int(dynamic_max_layer_count),
            )
        except (OSError, ValueError, TypeError) as exc:
            ctx["error"] = (
                "[P03] 动态拼图预览分析资产无效，请重新预览。"
                " / Dynamic puzzle preview-analysis assets are invalid. Re-run preview."
            )
            _log.warning(
                "Dynamic preview-analysis reuse rejected",
                extra={
                    "event": "p03_dynamic_preview_reuse_rejected",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            return ctx
    if reused_analysis is not None:
        matched_rgb, mask_solid, quantized_image, material_matrix = reused_analysis
        target_h, target_w = mask_solid.shape
        layer_count = int(material_matrix.shape[2])
        pixel_scale = float(target_width_mm) / float(max(1, target_w))
        ctx["matched_rgb"] = matched_rgb
        ctx["material_matrix"] = material_matrix
        ctx["mask_solid"] = mask_solid
        ctx["target_w"] = target_w
        ctx["target_h"] = target_h
        ctx["pixel_scale"] = pixel_scale
        ctx["debug_data"] = None
        ctx["quantized_image"] = quantized_image
        ctx["lut_match_info"] = None
        ctx["color_layers"] = layer_count
        ctx["material_dynamic_layer_info"] = {
            "enabled": True,
            "min_layer_count": int(dynamic_min_layer_count),
            "max_layer_count": layer_count,
            "benefit_curve_scope": "all_printable_pixels",
            "benefit_curve_pixel_count": int(np.count_nonzero(mask_solid)),
            "preview_matrix_reuse": True,
        }
        ctx["material_solver_info"] = {
            "path": "preview_matrix_reuse",
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "unique_color_count": int(
                count_visible_rgb(quantized_image, mask_solid)[0].shape[0]
            )
            if np.any(mask_solid)
            else 0,
        }
        ctx["mode_info"] = {
            "mode": ctx.get("modeling_mode"),
            "lut_match_mode": "material_archive",
        }
        ctx["preview_matrix_reuse"] = True
        elapsed = time.perf_counter() - _t0
        ctx.setdefault("_preview_timings", {})["p03_s"] = elapsed
        _log.debug(
            "material_archive preview matrix reused: %.3fs",
            elapsed,
            extra={
                "event": "p03_dynamic_preview_matrix_reused",
                "target_width": target_w,
                "target_height": target_h,
                "layer_count": layer_count,
            },
        )
        return ctx

    # ---- Load and resize ----
    PIXELS_PER_MM = SVG_PIXELS_PER_MM_DEFAULT
    is_svg = image_path.lower().endswith(".svg")
    if is_svg:
        from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg

        modeling_mode_value = getattr(modeling_mode, "value", modeling_mode)
        if modeling_mode_value == ModelingMode.HIGH_FIDELITY.value:
            PIXELS_PER_MM = normalize_svg_pixels_per_mm(
                ctx.get("svg_pixels_per_mm", SVG_PIXELS_PER_MM_DEFAULT)
            )
        try:
            img = Image.fromarray(rasterize_svg(image_path, target_width_mm, pixels_per_mm=PIXELS_PER_MM))
        except ImportError:
            ctx["error"] = (
                "[P03] SVG 光栅化需要 resvg-py，请执行 pip install resvg-py。"
                " / SVG rasterization requires resvg-py. "
                "Please run: pip install resvg-py"
            )
            return ctx
        target_w, target_h = img.size[0], img.size[1]
        # The rasterizer alpha-crops canvas margins; map the cropped width to
        # the requested width like the preview GLB and preview-reuse paths.
        # 光栅化会裁掉画布边距；与预览 GLB 及预览复用路径一致，按裁后宽度映射到目标宽度。
        pixel_scale = float(target_width_mm) / float(max(1, target_w))
    else:
        img = Image.open(image_path).convert("RGBA")
        target_w = max(1, int(target_width_mm * PIXELS_PER_MM))
        target_h = max(1, int(target_w * img.height / img.width))
        pixel_scale = 1.0 / PIXELS_PER_MM
    img = img.resize((target_w, target_h), Image.Resampling.NEAREST)

    img_arr = np.array(img)
    del img
    rgb_arr = img_arr[:, :, :3]
    alpha_arr = img_arr[:, :, 3]
    mask_transparent = alpha_arr < 10
    mask_solid = ~mask_transparent
    modeling_mode_value = getattr(modeling_mode, "value", modeling_mode)
    is_pixel_raster = (
        not is_svg and modeling_mode_value == ModelingMode.PIXEL.value
    )

    if is_pixel_raster:
        # Flatten partial alpha against the source/display white canvas before
        # any RGB analysis. Converter solver substrate is a separate physical
        # model input; changing it must not change the source target colour.
        # The original alpha mask remains authoritative for air pixels.
        alpha_u16 = alpha_arr[..., None].astype(np.uint16)
        rgb_u16 = rgb_arr.astype(np.uint16)
        rgb_arr = (
            (
                rgb_u16 * alpha_u16
                + 255 * (255 - alpha_u16)
                + 127
            )
            // 255
        ).astype(np.uint8)
        del alpha_u16, rgb_u16

    # ---- Load persisted solver cache early for auto dynamic range L* targets ----
    # 自动动态范围只需要已有 legacy cache 的 ``lab_centers``；不要在量化前构建
    # candidate runtime，否则透明图/空色集也会提前分配大候选数组。
    # Auto dynamic range only benefits from a persisted legacy cache's
    # ``lab_centers``. Do not build a candidate runtime before quantization:
    # transparent/empty inputs should not allocate candidate arrays at all.
    cache = None
    actual_grid = None
    if not dynamic_layer_count_enabled:
        try:
            cache, actual_grid = load_solver_cache(
                materials=materials,
                layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
                grid_resolution=requested_grid,
            )
        except (MemoryError, RuntimeError, ValueError) as exc:
            _log.error(
                "Material solver cache load failed: %s",
                exc,
                extra={
                    "event": "material_solver_cache_load_failed",
                    "material_count": len(materials),
                    "layer_count": layer_count,
                    "layer_height_mm": layer_height_mm,
                    "substrate": substrate,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            ctx["error"] = (
                "[P03] 耗材求解缓存加载失败。"
                " / Material solver cache load failed."
            )
            return ctx

    # ---- Auto dynamic range (optional) ----
    if ctx.get("auto_dynamic_range"):
        from core.pipeline.processing_ops.dynamic_range_compressor import (
            apply_auto_dynamic_range,
            compute_target_l_range,
        )
        target_lab = None
        if cache is not None and getattr(cache, "lab_centers", None) is not None:
            target_lab = np.asarray(cache.lab_centers, dtype=np.float64)
        target_range = compute_target_l_range(target_lab) if target_lab is not None else None
        if target_range is not None:
            dynamic_range_input = (
                rgb_arr[mask_solid].reshape(1, -1, 3)
                if is_pixel_raster
                else rgb_arr
            )
            rgb_arr_compressed, dr_info = apply_auto_dynamic_range(
                dynamic_range_input, target_range[0], target_range[1]
            )
            if dr_info.get("applied"):
                _log.info(
                    "Auto dynamic range applied (material archive)",
                    extra={
                        "event": "auto_dynamic_range_applied",
                        "src_l_range": list(dr_info.get("src_l_range") or ()),
                        "tgt_l_range": list(dr_info.get("tgt_l_range") or ()),
                        "branch": "material_archive",
                    },
                )
                if is_pixel_raster:
                    rgb_arr = rgb_arr.copy()
                    rgb_arr[mask_solid] = rgb_arr_compressed.reshape(-1, 3)
                else:
                    rgb_arr = rgb_arr_compressed
            else:
                _log.debug(
                    "Auto dynamic range skipped (material archive)",
                    extra={
                        "event": "auto_dynamic_range_skipped",
                        "reason": dr_info.get("reason"),
                        "branch": "material_archive",
                    },
                )
        else:
            _log.debug(
                "Auto dynamic range skipped: no lab_centers in cache",
                extra={
                    "event": "auto_dynamic_range_skipped",
                    "reason": "no_target_range",
                    "branch": "material_archive",
                },
            )

    # ---- Quantize ----
    # Two paths:
    #
    # 1. **SVG fill-palette snapping** (``is_svg`` branch). resvg outputs
    #    anti-aliased edges where neighbouring fill colors blend into
    #    intermediate RGB triples. Feeding those edge blends into K-Means
    #    with a large budget (``quantize_colors_n=256``) makes the algorithm
    #    spend clusters on transition bands; each transition cluster then
    #    resolves to its own material recipe, producing the "noise pixels
    #    not following the SVG strokes" symptom. Instead we derive the fill
    #    palette directly from the RGB histogram of visible pixels:
    #    real fills cover dense regions while AA edge blends are spread
    #    thin, so the smallest top-K colors covering 99% of visible pixels
    #    are exactly the SVG's true fills. We then KDTree-snap every
    #    visible pixel to its nearest fill. This keeps ``unique_colors``
    #    bounded by the SVG's actual fill count, no matter how large the
    #    user's ``quantize_colors`` is. (NB: with an opaque background the
    #    AA blending happens entirely in RGB while alpha stays at 255, so
    #    an alpha-based heuristic cannot distinguish fills from edges —
    #    the histogram-frequency signal is the robust one.)
    #    (SVG 走线杂色根因：resvg 抗锯齿边缘是相邻填充色的混合 RGB，K-Means
    #    给 256 预算时会专门给过渡带开簇，过渡带每个 cluster 又被独立查表
    #    成不相关配方，这就是「不沿走线的杂色」。改为：对可见像素做 RGB 直方图，
    #    取累计覆盖 99% 像素的高频色作为填充色板（AA 像素分布稀疏总和 <1% 自然
    #    被剔除），其余可见像素 KDTree 吸附到最近填充色。注意当 SVG 有不透明
    #    背景时，AA 混合完全发生在 RGB 上而 alpha 仍为 255，因此只有频次信号
    #    可靠，alpha 阈值无效。)
    #
    # 2. **Raster path** (PNG/JPG/HEIC). High-fidelity raster previews still
    #    apply edge-preserving smoothing before K-Means. Pixel-mode raster art
    #    preserves the nearest-resized source palette when it fits the user's
    #    colour budget; if it exceeds the budget, K-Means runs on those raw
    #    pixels directly instead of synthesizing boundary colours first.
    #    (高保真栅格仍先做边缘保持平滑再 K-Means；像素模式保留最近邻缩放后的
    #    原始色板，超出预算时也直接量化原始像素，避免先平滑出边界脏色。)
    if is_svg:
        quantized_image = _snap_svg_to_fill_palette(
            rgb_arr=rgb_arr,
            mask_transparent=mask_transparent,
            quantize_budget=quantize_colors_n,
        )
    elif modeling_mode_value == ModelingMode.PIXEL.value:
        unique_visible, _visible_counts = count_visible_rgb(rgb_arr, mask_solid)
        if unique_visible.shape[0] <= quantize_colors_n:
            quantized_image = rgb_arr.copy()
        else:
            # Pixel mode must not blur hard-edged source art. Transparent air
            # is excluded from fitting so it cannot consume a color cluster.
            quantized_image = kmeans_quantize(
                rgb_arr,
                quantize_colors_n,
                mask=mask_solid,
            )
    else:
        rgb_processed = apply_bilateral_filter(rgb_arr, 10)
        rgb_processed = apply_median_filter(rgb_processed, 0)
        quantized_image = kmeans_quantize(rgb_processed, quantize_colors_n)
        del rgb_processed
    # Source/compositing buffers are no longer needed once quantization is
    # complete. Release them before allocating the per-pixel layer tensor.
    del rgb_arr, img_arr, alpha_arr
    unique_colors, pixel_counts = count_visible_rgb(quantized_image, mask_solid)
    _log.debug(
        "%d visible unique colors after quantization (svg=%s)",
        len(unique_colors),
        is_svg,
    )

    # ---- Resolve recipes: cache lookup or per-image B&B fallback ----
    # ``cache`` / ``actual_grid`` were pre-loaded above for auto dynamic range;
    # reuse them here to avoid a second disk read.
    # 上面已为自动动态范围预先加载 ``cache`` / ``actual_grid``，此处直接复用，避免重复读盘。
    solver_t0 = time.perf_counter()
    solver_path: str
    solver_meta: dict = {}
    dynamic_layer_info: dict | None = None
    if dynamic_layer_count_enabled:
        from core import material_dynamic_solver as dynamic_solver
        from core.pipeline.material_dynamic_layers import (
            _record_dynamic_material_error,
            _solve_dynamic_material_targets,
        )

        backing_material_index = ctx.get("material_backing_material_index")
        if backing_material_index is None:
            backing_material_index = ctx.get("material_base_channel_idx")
        try:
            (
                matched_rgb_unique,
                recipes_unique,
                delta_e,
                dynamic_layer_info,
                solver_meta,
            ) = _solve_dynamic_material_targets(
                unique_colors=unique_colors,
                pixel_counts=pixel_counts,
                materials=materials,
                backing_material_index=backing_material_index,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
                min_layer_count=dynamic_min_layer_count,
                max_layer_count=dynamic_max_layer_count,
                delta_e00_tolerance=dynamic_delta_e00_tolerance,
            )
        except (
            dynamic_solver.DynamicMaterialCandidateError,
            dynamic_solver.DynamicMaterialSolverError,
            TypeError,
            ValueError,
        ) as exc:
            return _record_dynamic_material_error(ctx, exc)
        layer_count = int(dynamic_layer_info["max_layer_count"])
        solver_path = "dynamic_exact"
    elif cache is None and unique_colors.shape[0] > 0:
        try:
            cache, actual_grid = load_solver_runtime(
                materials=materials,
                layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
                grid_resolution=requested_grid,
            )
        except (MemoryError, RuntimeError, ValueError) as exc:
            _log.error(
                "Material solver runtime build failed: %s",
                exc,
                extra={
                    "event": "material_solver_runtime_failed",
                    "material_count": len(materials),
                    "layer_count": layer_count,
                    "layer_height_mm": layer_height_mm,
                    "substrate": substrate,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            ctx["error"] = (
                "[P03] 耗材求解运行时构建失败，请减少耗材/层数或先构建持久缓存。"
                " / Material solver runtime build failed. Reduce materials/layers "
                "or build a persisted cache first."
            )
            return ctx
    if (
        not dynamic_layer_count_enabled
        and cache is not None
        and unique_colors.shape[0] > 0
    ):
        cache_mode = str(getattr(cache, "mode", "bucketed"))
        cache_metadata = getattr(cache, "metadata", {}) or {}
        cache_layer_count = int(getattr(cache, "layer_count", layer_count))
        cache_grid_resolution = int(getattr(cache, "grid_resolution", requested_grid))
        cache_valid_cell_count = int(getattr(cache, "valid_cell_count", 0))
        matched_rgb_unique, recipes_unique, delta_e = cache.lookup(
            unique_colors, materials
        )
        solver_path = "cache"
        solver_meta = {
            "palette_hash": getattr(cache, "palette_hash", ""),
            "requested_grid_resolution": requested_grid,
            "grid_resolution": cache_grid_resolution,
            "grid_fallback_used": actual_grid != requested_grid,
            "valid_cell_count": cache_valid_cell_count,
            "built_at": cache_metadata.get("built_at"),
            "cache_mean_delta_e": float(cache_metadata.get("mean_delta_e", 0.0)),
            "cache_max_delta_e": float(cache_metadata.get("max_delta_e", 0.0)),
            "cache_mode": cache_mode,
        }
        _log.info(
            "Material solver: using %s cache (M=%d, N=%d, recipes=%d)",
            cache_mode.upper(),
            len(materials),
            cache_layer_count,
            cache_valid_cell_count,
            extra={
                "event": "material_solver_cache_used",
                "cache_mode": cache_mode,
                "material_count": len(materials),
                "layer_count": cache_layer_count,
                "valid_cell_count": cache_valid_cell_count,
                "unique_color_count": int(unique_colors.shape[0]),
            },
        )
    elif not dynamic_layer_count_enabled and unique_colors.shape[0] == 0:
        matched_rgb_unique = np.zeros((0, 3), dtype=np.uint8)
        recipes_unique = np.zeros((0, layer_count), dtype=np.int32)
        delta_e = np.zeros((0,), dtype=np.float64)
        solver_path = "cache"
        solver_meta = {
            "palette_hash": getattr(cache, "palette_hash", "") if cache else "",
            "requested_grid_resolution": requested_grid,
            "grid_resolution": (
                getattr(cache, "grid_resolution", requested_grid)
                if cache
                else requested_grid
            ),
            "grid_fallback_used": False,
            "valid_cell_count": (
                int(getattr(cache, "valid_cell_count", 0)) if cache else 0
            ),
            "built_at": None,
            "cache_mean_delta_e": 0.0,
            "cache_max_delta_e": 0.0,
            "cache_mode": (
                str(getattr(cache, "mode", "candidate_hybrid")) if cache else "none"
            ),
        }
    elif not dynamic_layer_count_enabled:
        ctx["error"] = (
            "[P03] 未能加载或构建耗材求解运行时。"
            " / No material solver runtime could be loaded or built."
        )
        return ctx
    solver_elapsed = time.perf_counter() - solver_t0
    _log.debug(
        "Solver path=%s colors=%d mean_ΔE=%.2f max_ΔE=%.2f elapsed=%.2fs",
        solver_path,
        int(unique_colors.shape[0]),
        float(np.mean(delta_e)) if delta_e.size else 0.0,
        float(np.max(delta_e)) if delta_e.size else 0.0,
        solver_elapsed,
    )

    # ---- Enforce "N-layer recipe not worse than smaller-N + white padding" ----
    # Run the cross-N fallback for small runtimes that fully cover the M**N
    # recipe space. Approximate candidate runtimes and bucketed caches still
    # skip this expensive pass, preserving the large-palette OOM guard.
    # 仅当 runtime 已完整覆盖 M**N 且组合数很小时才做跨 N 保底；近似候选
    # runtime 和分桶缓存仍跳过，避免回到大调色板 OOM 路径。
    _run_cross_n = False
    if not dynamic_layer_count_enabled:
        _run_cross_n = should_run_cross_n_fallback(
            solver_path=solver_path,
            runtime=cache,
            unique_color_count=int(unique_colors.shape[0]),
            material_count=len(materials),
            layer_count=layer_count,
        )
    if _run_cross_n:
        fallback_t0 = time.perf_counter()
        matched_rgb_unique, recipes_unique, delta_e, fallback_stats = (
            ensure_not_worse_than_smaller_N(
                unique_colors,
                materials,
                matched_rgb_unique,
                recipes_unique,
                delta_e,
                target_layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
            )
        )
        fallback_elapsed = time.perf_counter() - fallback_t0
        solver_meta["not_worse_fallback"] = {
            **fallback_stats,
            "elapsed_seconds": float(fallback_elapsed),
        }
        if fallback_stats["applied"] and fallback_stats["improved_pixels"] > 0:
            _log.debug(
                "Not-worse fallback replaced %d/%d unique colours "
                "(mean ΔE %.2f→%.2f, max ΔE %.2f→%.2f, elapsed=%.2fs)",
                fallback_stats["improved_pixels"],
                int(unique_colors.shape[0]),
                fallback_stats["mean_delta_e_before"],
                fallback_stats["mean_delta_e_after"],
                fallback_stats["max_delta_e_before"],
                fallback_stats["max_delta_e_after"],
                fallback_elapsed,
            )
        elif not fallback_stats["applied"]:
            _log.debug(
                "Not-worse fallback skipped (no white material "
                "detected in palette or N=%d already at the lower bound).",
                layer_count,
            )

    # ---- Convert layer order: solver "Bottom2Top" -> pipeline "Top2Bottom" ----
    # 层序转换：求解器/缓存输出的 ``recipes_unique[:, 0]`` 是底层（贴基底、
    # 即靠背板侧），``recipes_unique[:, -1]`` 是顶层（观赏面）。而 S06
    # ``_build_voxel_matrix`` / ``_build_voxel_matrix_faceup`` 约定
    # ``material_matrix[..., 0]`` 是观赏面，``material_matrix[..., -1]`` 贴背板。
    # 直接把求解结果喂进 ``map_pixels_to_materials`` 会让整叠层上下颠倒，
    # 产出的 3MF 配色与用户所见的预测色不一致，所以在此一次性反转列序。
    # Solver/cache output uses ``Bottom2Top`` (index 0 = substrate-adjacent)
    # while the voxel builders in S06 assume ``Top2Bottom`` (index 0 =
    # viewing surface). Reverse the recipe columns once here so downstream
    # ``material_matrix`` matches the pipeline convention.
    if not dynamic_layer_count_enabled and recipes_unique.shape[1] > 1:
        recipes_unique = np.ascontiguousarray(recipes_unique[:, ::-1])

    # ---- Map pixels ----
    if unique_colors.shape[0] == 0:
        matched_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        material_matrix = np.full(
            (target_h, target_w, layer_count),
            -1,
            dtype=np.int32,
        )
    else:
        quantized_for_mapping = quantized_image
        if np.any(mask_transparent):
            quantized_for_mapping = quantized_image.copy()
            quantized_for_mapping[mask_transparent] = unique_colors[0]
        matched_rgb, material_matrix = map_pixels_to_materials(
            quantized_for_mapping, unique_colors, matched_rgb_unique, recipes_unique,
            target_h, target_w,
        )

    # ---- Isolated pixel cleanup (honours the user's ``enable_cleanup`` flag) ----
    # Cleanup belongs to the pristine analysis. Re-preview replacements must be
    # applied afterwards so reset/undo returns to exactly the same cleaned grid
    # as a preview that carried no replacements.
    # 清理属于 pristine 分析；重预览携带的替色必须在其后应用，确保 reset/undo
    # 精确回到未替色预览的同一份已清理网格。
    if ctx.get("enable_cleanup", True):
        if dynamic_layer_count_enabled:
            from core.isolated_pixel_cleanup import (
                cleanup_isolated_pixels_with_target_map,
            )
            from core.pipeline.material_dynamic_layers import (
                recompute_dynamic_material_benefit_curve,
            )

            matched_rgb, material_matrix, quantized_image = (
                cleanup_isolated_pixels_with_target_map(
                    material_matrix,
                    matched_rgb,
                    quantized_image,
                )
            )
            if isinstance(dynamic_layer_info, dict):
                colors = dynamic_layer_info.get("colors")
                dynamic_layer_info["benefit_curve"] = (
                    recompute_dynamic_material_benefit_curve(
                        colors if isinstance(colors, list) else [],
                        quantized_image,
                        mask_solid,
                    )
                )
        else:
            from core.isolated_pixel_cleanup import cleanup_isolated_pixels

            matched_rgb, material_matrix = cleanup_isolated_pixels(
                material_matrix,
                matched_rgb,
            )

    # Transparent pixels are air in both current and pristine recipes.
    material_matrix[mask_transparent] = -1

    # Capture stable reset/relief identity before any display replacement.
    # These are immutable semantic aliases, not independent working buffers:
    # the replacement helper allocates current copies only when a mapping
    # actually touches pixels. Keeping the pristine arrays aliased avoids
    # tripling large preview caches in the overwhelmingly common no-remap flow.
    # 这里保存的是不可变语义别名，而不是三份工作副本；只有替色真正命中时，
    # helper 才会分配 current 副本，避免普通预览无谓放大内存和落盘缓存。
    original_matched_rgb = np.asarray(matched_rgb, dtype=np.uint8)
    original_material_matrix = np.asarray(material_matrix)
    original_quantized_image = np.asarray(quantized_image, dtype=np.uint8)
    height_identity_rgb = original_matched_rgb
    original_dynamic_layer_info = (
        deepcopy(dynamic_layer_info)
        if isinstance(dynamic_layer_info, dict)
        else None
    )
    original_material_solver_info = {
        "path": solver_path,
        "layer_count": layer_count,
        "layer_height_mm": layer_height_mm,
        "substrate": substrate,
        "elapsed_seconds": solver_elapsed,
        "unique_color_count": int(unique_colors.shape[0]),
        "mean_delta_e": float(np.mean(delta_e)) if delta_e.size else 0.0,
        "max_delta_e": float(np.max(delta_e)) if delta_e.size else 0.0,
        **deepcopy(solver_meta),
    }

    # Re-preview requests can carry global replacements already chosen by the
    # user. Apply them only to the current display/recipe arrays.
    from core.pipeline.s03_color_replacement import (
        _apply_dynamic_material_archive_color_replacements,
        _apply_material_archive_color_replacements,
        _resolve_replayed_color_replacement_jobs,
    )

    effective_color_replacements = _resolve_replayed_color_replacement_jobs(
        ctx.get("replacement_regions"),
        matched_rgb,
        quantized_image,
        mask_solid,
    )
    applied_replacements = 0
    if effective_color_replacements:
        if dynamic_layer_count_enabled:
            try:
                (
                    matched_rgb,
                    material_matrix,
                    applied_replacements,
                    dynamic_layer_info,
                    replacement_solver_meta,
                    quantized_image,
                ) = _apply_dynamic_material_archive_color_replacements(
                    matched_rgb,
                    material_matrix,
                    mask_solid,
                    quantized_image,
                    effective_color_replacements,
                    materials,
                    backing_material_index=int(backing_material_index),
                    min_layer_count=int(dynamic_min_layer_count),
                    max_layer_count=int(dynamic_max_layer_count),
                    delta_e00_tolerance=float(dynamic_delta_e00_tolerance),
                    layer_height_mm=layer_height_mm,
                    substrate=substrate,
                    dynamic_layer_info=dynamic_layer_info,
                    material_solver_info=original_material_solver_info,
                )
                solver_meta.update(replacement_solver_meta)
            except (
                dynamic_solver.DynamicMaterialCandidateError,
                dynamic_solver.DynamicMaterialSolverError,
                TypeError,
                ValueError,
            ) as exc:
                return _record_dynamic_material_error(ctx, exc)
        else:
            matched_rgb, material_matrix, applied_replacements = (
                _apply_material_archive_color_replacements(
                    matched_rgb,
                    material_matrix,
                    mask_solid,
                    effective_color_replacements,
                    materials,
                    layer_count,
                    layer_height_mm,
                    substrate,
                    grid_resolution=actual_grid or requested_grid,
                )
            )
        _log.debug(
            "Applied %d material-archive preview color replacements",
            applied_replacements,
            extra={
                "event": "material_archive_preview_replacements_applied",
                "replacement_count": len(effective_color_replacements),
                "applied_replacement_count": applied_replacements,
            },
        )

    # ---- Write output ----
    ctx["matched_rgb"] = matched_rgb
    ctx["material_matrix"] = material_matrix
    ctx["original_matched_rgb"] = original_matched_rgb
    ctx["height_identity_rgb"] = height_identity_rgb
    ctx["original_material_matrix"] = original_material_matrix
    ctx["mask_solid"] = mask_solid
    ctx["target_w"] = target_w
    ctx["target_h"] = target_h
    ctx["pixel_scale"] = pixel_scale
    ctx["debug_data"] = None
    ctx["quantized_image"] = quantized_image
    ctx["original_quantized_image"] = original_quantized_image
    ctx["lut_match_info"] = None
    if dynamic_layer_count_enabled:
        if isinstance(dynamic_layer_info, dict):
            # Preview-time replacements and isolated-pixel cleanup can change
            # target ownership after the solver constructs its initial curve.
            # This path is still wholly automatic, so record the final
            # coverage explicitly rather than leaving a stale denominator.
            if applied_replacements > 0:
                from core.pipeline.material_dynamic_layers import (
                    recompute_dynamic_material_benefit_curve,
                )

                colors = dynamic_layer_info.get("colors")
                dynamic_layer_info["benefit_curve"] = (
                    recompute_dynamic_material_benefit_curve(
                        colors if isinstance(colors, list) else [],
                        quantized_image,
                        mask_solid,
                    )
                )
            dynamic_layer_info["benefit_curve_scope"] = "all_printable_pixels"
            dynamic_layer_info["benefit_curve_pixel_count"] = int(
                np.count_nonzero(mask_solid)
            )
        ctx["color_layers"] = layer_count
        ctx["material_dynamic_layer_info"] = dynamic_layer_info
        if original_dynamic_layer_info is not None:
            ctx["original_material_dynamic_layer_info"] = (
                original_dynamic_layer_info
            )
    ctx["material_solver_info"] = {
        "path": solver_path,
        "layer_count": layer_count,
        "layer_height_mm": layer_height_mm,
        "substrate": substrate,
        "elapsed_seconds": solver_elapsed,
        "unique_color_count": int(unique_colors.shape[0]),
        "mean_delta_e": float(np.mean(delta_e)) if delta_e.size else 0.0,
        "max_delta_e": float(np.max(delta_e)) if delta_e.size else 0.0,
        **solver_meta,
    }
    if dynamic_layer_count_enabled:
        ctx["original_material_solver_info"] = original_material_solver_info
    # mode_info is consumed by S04 (debug preview) and S12 (result assembly).
    # Material-archive mode does not run a LUT-based color matcher, so we
    # populate a placeholder match mode so the contract stays consistent.
    ctx["mode_info"] = {
        "mode": ctx.get("modeling_mode"),
        "lut_match_mode": "material_archive",
    }
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault("_preview_timings", {})["p03_s"] = _elapsed
    _log.debug("material_archive core_processing done: %.3fs", _elapsed)
    return ctx


def run(ctx: dict) -> dict:
    """Execute core image processing: quantization and LUT color matching.
    执行核心图像处理：量化与 LUT 颜色匹配。

    PipelineContext 输入键 / Input keys:
        - actual_lut_path (str): 解析后的实际 LUT 文件路径
        - color_mode (str): 颜色模式字符串
        - hue_weight (float): 色相权重
        - chroma_gate (float): 色度门限
        - image_path (str): 输入图像路径
        - target_width_mm (float): 目标宽度（毫米）
        - modeling_mode (ModelingMode): 建模模式
        - quantize_colors (int): 量化颜色数
        - enable_cleanup (bool): 是否启用孤立像素清理

    PipelineContext 输出键 / Output keys:
        - matched_rgb (np.ndarray): LUT 匹配后的 RGB 图像 (H, W, 3)
        - material_matrix (np.ndarray): 材料矩阵 (H, W, N)
        - mask_solid (np.ndarray): 实体掩码 (H, W) bool
        - target_w (int): 目标宽度（像素）
        - target_h (int): 目标高度（像素）
        - debug_data (dict | None): 调试数据
        - quantized_image (np.ndarray | None): 量化后的图像

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- Material-archive branch ----
    if ctx.get("material_source") == "material_archive":
        return _run_material_archive_branch(ctx)

    from core.image_processing import LuminaImageProcessor
    _t0 = time.perf_counter()

    # ---- 读取必需输入 ----
    actual_lut_path = ctx['actual_lut_path']
    color_mode = ctx['color_mode']
    hue_weight = ctx.get('hue_weight', 0.0)
    chroma_gate = ctx.get('chroma_gate', 15.0)
    image_path = ctx['image_path']
    target_width_mm = ctx['target_width_mm']
    modeling_mode = ctx['modeling_mode']
    quantize_colors = ctx['quantize_colors']
    enable_cleanup = ctx.get('enable_cleanup', True)
    color_layers = ctx.get('color_layers')
    layer_height_mm = ctx.get('layer_height_mm')
    model_enable = ctx.get('model_enable', False)
    model_only = ctx.get('model_only', False)
    model_threshold = ctx.get('model_threshold')
    model_margin = ctx.get('model_margin')
    use_lut_constrained = ctx.get('use_lut_constrained', False)
    auto_dynamic_range = ctx.get('auto_dynamic_range', False)
    svg_pixels_per_mm = ctx.get('svg_pixels_per_mm', SVG_PIXELS_PER_MM_DEFAULT)

    # ---- 核心处理 ----
    processor = LuminaImageProcessor(
        actual_lut_path,
        color_mode,
        hue_weight=hue_weight,
        chroma_gate=chroma_gate,
        color_layers=color_layers,
        layer_height_mm=layer_height_mm,
        model_enable=model_enable,
        model_only=model_only,
        model_threshold=model_threshold,
        model_margin=model_margin,
        use_lut_constrained=use_lut_constrained,
        auto_dynamic_range=auto_dynamic_range,
        svg_pixels_per_mm=svg_pixels_per_mm,
    )
    processor.enable_cleanup = enable_cleanup

    result = processor.process_image(
        image_path=image_path,
        target_width_mm=target_width_mm,
        modeling_mode=modeling_mode,
        quantize_colors=quantize_colors,
        blur_kernel=0,
        smooth_sigma=10
    )

    # ---- 提取结果 ----
    matched_rgb = result['matched_rgb']
    material_matrix = result['material_matrix']
    mask_solid = result['mask_solid']
    target_w, target_h = result['dimensions']
    quantized_image = result.get('quantized_image')

    # Preserve pristine arrays for reset/undo and relief-height identity, then
    # replay only portable whole-image mappings into the current preview.
    # 先保存重置/撤销与浮雕高度身份所需的原始数组，再把可移植的全图改色
    # 应用到当前预览。局部选区仍只属于原会话，不在这里重建。
    has_portable_replacements = bool(
        ctx.get("replacement_regions") and quantized_image is not None
    )
    original_matched_rgb = (
        np.array(matched_rgb, dtype=np.uint8, copy=True)
        if has_portable_replacements
        else np.asarray(matched_rgb, dtype=np.uint8)
    )
    original_material_matrix = (
        np.array(material_matrix, copy=True)
        if has_portable_replacements
        else np.asarray(material_matrix)
    )
    if has_portable_replacements:
        from core.pipeline.s03_color_replacement import (
            _resolve_replayed_color_replacement_jobs,
        )
        replacements = _resolve_replayed_color_replacement_jobs(
            ctx.get("replacement_regions"),
            matched_rgb,
            quantized_image,
            mask_solid,
        )
        if replacements:
            from core.pipeline.pipeline_utils import _hex_to_rgb_tuple

            matched_rgb = matched_rgb.copy()
            for target_hex, source_mask in replacements:
                target_rgb = _hex_to_rgb_tuple(target_hex)
                matched_rgb[source_mask] = target_rgb
                target_lab = processor._rgb_to_lab(
                    np.array([target_rgb], dtype=np.uint8)
                )
                _, lut_index = processor.kdtree.query(target_lab)
                material_matrix[source_mask] = processor.ref_stacks[lut_index[0]]

    # ---- 写入输出 ----
    ctx['matched_rgb'] = matched_rgb
    ctx['material_matrix'] = material_matrix
    ctx['original_matched_rgb'] = original_matched_rgb
    ctx['height_identity_rgb'] = original_matched_rgb
    ctx['original_material_matrix'] = original_material_matrix
    ctx['mask_solid'] = mask_solid
    ctx['target_w'] = target_w
    ctx['target_h'] = target_h
    ctx['debug_data'] = result.get('debug_data') if isinstance(result, dict) else None
    ctx['quantized_image'] = quantized_image
    if quantized_image is not None:
        ctx['original_quantized_image'] = np.asarray(
            quantized_image,
            dtype=np.uint8,
        )
    ctx['lut_match_info'] = getattr(processor, 'last_match_info', None)
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault('_preview_timings', {})['p03_s'] = _elapsed
    _log.debug("core_processing done: %.3fs", _elapsed)
    return ctx
