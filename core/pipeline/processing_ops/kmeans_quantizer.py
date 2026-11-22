"""
K-Means 颜色量化模块（K-Means Color Quantizer）

从 image_processing.py 的 _process_high_fidelity_mode Step 4 搬入。
包含预缩放优化、K-Means++ 初始化和 LUT 约束量化。

K-Means color quantization with pre-scaling optimization.
Extracted from _process_high_fidelity_mode Step 4.
"""

from api.structured_logging import get_logger
import time
import numpy as np
import cv2
from scipy.spatial import KDTree

from core.pipeline.processing_ops.color_histogram import RGB_LOOKUP_BLOCK_PIXELS, pack_rgb24

_log = get_logger(__name__)


# At most four exact input snapshots; no digest or caller identity is needed.
_kmeans_cache: list[tuple[tuple, tuple[np.ndarray, ...], np.ndarray]] = []
_KMEANS_CACHE_MAX = 4


def _cached_quantization(parameters: tuple, arrays: tuple[np.ndarray, ...]) -> np.ndarray | None:
    for stored_parameters, snapshots, result in _kmeans_cache:
        if stored_parameters == parameters and all(
            current.dtype == saved.dtype and np.array_equal(current, saved)
            for current, saved in zip(arrays, snapshots, strict=True)
        ):
            return result.copy()
    return None


def _store_quantization(parameters: tuple, arrays: tuple[np.ndarray, ...], result: np.ndarray) -> None:
    if len(_kmeans_cache) >= _KMEANS_CACHE_MAX:
        del _kmeans_cache[0]
    _kmeans_cache.append((parameters, tuple(array.copy() for array in arrays), result.copy()))


def _resolve_cluster_count(requested_colors: int, sample_count: int) -> int:
    """Clamp the cluster count to the available sample count.

    OpenCV ``cv2.kmeans`` requires ``K <= N`` where ``N`` is the number of
    samples. Tiny SVG puzzle pieces can easily rasterize to fewer pixels than
    the requested quantization count, so we degrade gracefully instead of
    raising inside OpenCV.
    """
    if sample_count <= 0:
        return 0
    return max(1, min(requested_colors, sample_count))


def _maybe_return_low_unique_input(
    rgb: np.ndarray,
    effective_n_colors: int,
) -> np.ndarray | None:
    """Return an exact copy when the input already satisfies the palette cap."""

    if effective_n_colors <= 0:
        return None
    rgb_u8 = np.ascontiguousarray(rgb, dtype=np.uint8)
    flat = rgb_u8.reshape(-1, 3)
    keys = np.empty(0, dtype=np.uint32)
    for start in range(0, len(flat), RGB_LOOKUP_BLOCK_PIXELS):
        block = flat[start : start + RGB_LOOKUP_BLOCK_PIXELS]
        block_keys = np.unique(pack_rgb24(block))
        if block_keys.size > effective_n_colors:
            return None
        keys = np.union1d(keys, block_keys)
        if keys.size > effective_n_colors:
            return None
    _log.debug(
        "K-Means skipped because unique RGB count is within budget",
        extra={
            "event": "kmeans_low_unique_fast_path",
            "unique_colors": int(keys.size),
            "effective_n_colors": int(effective_n_colors),
        },
    )
    return rgb_u8.copy()


KMEANS_PIXEL_THRESHOLD = 500_000


def _stratified_sample_indices(
    population_size: int,
    sample_size: int,
    seed: int,
) -> np.ndarray:
    """Return one reproducible random index from each contiguous stratum."""

    boundaries = np.linspace(
        0,
        population_size,
        num=sample_size + 1,
        dtype=np.int64,
    )
    widths = np.diff(boundaries)
    rng = np.random.default_rng(seed)
    offsets = rng.integers(0, widths, dtype=np.int64)
    boundaries[:-1] += offsets
    return boundaries[:-1]


def _nearest_center_sq(
    points_lab: np.ndarray,
    centers_lab: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return squared nearest-center distances and labels using KDTree.

    Returns:
        tuple[np.ndarray, np.ndarray]: ``(dist_sq, labels)`` with one entry
        per point. Uses KDTree to avoid dense ``points * centers`` matrices.
    """

    center_tree = KDTree(centers_lab)
    distances, labels = center_tree.query(points_lab)
    return np.square(distances), labels.astype(np.intp, copy=False)


def _map_rgb_to_lut_nearest(
    rgb: np.ndarray,
    lut_rgb: np.ndarray,
    lut_tree: KDTree,
) -> np.ndarray:
    """Map every RGB pixel to its nearest LUT RGB row in Lab space."""

    h, w = rgb.shape[:2]
    full_pixels_lab = _rgb_to_lab_quantize(rgb.reshape(-1, 3).astype(np.float32))
    _, nearest_lut_indices = lut_tree.query(full_pixels_lab)
    return lut_rgb[nearest_lut_indices].reshape(h, w, 3)


def _lut_constrained_quantize(
    rgb: np.ndarray,
    n_colors: int,
    seed: int,
    *,
    lut_lab: np.ndarray,
    lut_rgb: np.ndarray,
) -> np.ndarray:
    h, w = rgb.shape[:2]
    total_pixels = h * w
    if total_pixels == 0:
        return rgb.copy()

    lut_count = len(lut_lab)
    effective_k = min(n_colors, lut_count)
    if effective_k < n_colors:
        _log.info(
            "LUT-Constrained K-Means: K clamped from %s to %s (LUT has %s entries)",
            n_colors, effective_k, lut_count,
            extra={
                "event": "lut_constrained_kmeans_k_clamped",
                "requested_k": int(n_colors),
                "effective_k": int(effective_k),
                "lut_count": int(lut_count),
            },
        )

    if effective_k <= 0:
        return rgb.copy()

    _cache_key = ("lut", effective_k, seed)
    _cache_arrays = (rgb, lut_lab, lut_rgb)
    cached_result = _cached_quantization(_cache_key, _cache_arrays)
    if cached_result is not None:
        return cached_result

    # ``lut_lab`` is the authoritative LUT geometry. Rebuild the default tree
    # only on cache misses so externally supplied construction options or tree
    # topology cannot change exact-query tie-breaking or cache semantics.
    canonical_lut_tree = KDTree(lut_lab)

    if effective_k == lut_count:
        _log.info(
            "LUT-Constrained K-Means: direct LUT nearest-neighbor mapping "
            "because effective_k covers all %s LUT entries",
            lut_count,
            extra={
                "event": "lut_constrained_kmeans_direct_map",
                "effective_k": int(effective_k),
                "lut_count": int(lut_count),
            },
        )
        quantized_image = _map_rgb_to_lut_nearest(
            rgb,
            lut_rgb,
            canonical_lut_tree,
        )
        _store_quantization(_cache_key, _cache_arrays, quantized_image)
        return quantized_image

    rng = np.random.RandomState(seed)

    if total_pixels > KMEANS_PIXEL_THRESHOLD:
        scale_factor = np.sqrt(total_pixels / KMEANS_PIXEL_THRESHOLD)
        small_h = int(h / scale_factor)
        small_w = int(w / scale_factor)
        _log.debug(
            "LUT-Constrained pre-scaling: %sx%s -> %sx%s",
            w, h, small_w, small_h,
        )
        rgb_small = cv2.resize(rgb, (small_w, small_h), interpolation=cv2.INTER_AREA)
        work_rgb = rgb_small
        full_rgb = rgb
    else:
        work_rgb = rgb
        full_rgb = rgb

    work_pixels_rgb = work_rgb.reshape(-1, 3).astype(np.float32)
    work_pixels_lab = _rgb_to_lab_quantize(work_pixels_rgb)

    _, nearest_lut_indices = canonical_lut_tree.query(work_pixels_lab)
    lut_pixel_counts = np.bincount(nearest_lut_indices, minlength=lut_count).astype(np.float64)
    lut_pixel_counts[lut_pixel_counts == 0] = 1e-9

    best_centers_lab = None
    best_sse = np.inf

    for _attempt in range(3):
        centers_idx = np.empty(effective_k, dtype=np.intp)
        probs = lut_pixel_counts / lut_pixel_counts.sum()
        centers_idx[0] = rng.choice(lut_count, p=probs)

        cur_centers_lab = lut_lab[centers_idx[:1]].copy()
        for c in range(1, effective_k):
            dist_sq, _ = _nearest_center_sq(lut_lab, cur_centers_lab)
            weighted_dist_sq = dist_sq * lut_pixel_counts
            total_weight = weighted_dist_sq.sum()
            if total_weight <= 0:
                centers_idx[c] = rng.choice(lut_count)
            else:
                centers_idx[c] = rng.choice(lut_count, p=weighted_dist_sq / total_weight)
            cur_centers_lab = lut_lab[centers_idx[:c + 1]].copy()

        cur_centers_lab = lut_lab[centers_idx].copy()

        for _iter in range(20):
            _, labels = _nearest_center_sq(work_pixels_lab, cur_centers_lab)

            new_centers_lab = cur_centers_lab.copy()
            any_changed = False
            for ci in range(effective_k):
                mask = labels == ci
                if mask.sum() == 0:
                    new_idx = rng.choice(lut_count)
                    new_centers_lab[ci] = lut_lab[new_idx]
                    any_changed = True
                else:
                    mean_lab = work_pixels_lab[mask].mean(axis=0)
                    _, nearest_idx = canonical_lut_tree.query(mean_lab)
                    new_centers_lab[ci] = lut_lab[nearest_idx]

            if not any_changed and np.allclose(cur_centers_lab, new_centers_lab):
                cur_centers_lab = new_centers_lab
                break
            cur_centers_lab = new_centers_lab

        dist_sq, _ = _nearest_center_sq(work_pixels_lab, cur_centers_lab)
        sse = dist_sq.sum()
        if sse < best_sse:
            best_sse = sse
            best_centers_lab = cur_centers_lab.copy()

    if best_centers_lab is None:
        return rgb.copy()

    # Map best Lab centers to LUT RGB
    _, best_center_indices = canonical_lut_tree.query(best_centers_lab)
    centers_rgb = lut_rgb[best_center_indices]

    if total_pixels > KMEANS_PIXEL_THRESHOLD:
        full_pixels_lab = _rgb_to_lab_quantize(full_rgb.reshape(-1, 3).astype(np.float32))
        _, labels = _nearest_center_sq(full_pixels_lab, best_centers_lab)
    else:
        _, labels = _nearest_center_sq(work_pixels_lab, best_centers_lab)

    quantized_image = centers_rgb[labels].reshape(h, w, 3)

    _store_quantization(_cache_key, _cache_arrays, quantized_image)
    return quantized_image


def _rgb_to_lab_quantize(rgb_flat: np.ndarray) -> np.ndarray:
    """Convert (N, 3) float32 RGB to float64 Lab for distance computation.
    将 (N, 3) float32 RGB 转为 float64 Lab，用于距离计算。
    """
    rgb_u8 = np.clip(rgb_flat, 0, 255).astype(np.uint8).reshape(1, -1, 3)
    bgr = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
    return lab.reshape(-1, 3)


def quantize_colors(
    rgb: np.ndarray,
    n_colors: int,
    seed: int = 42,
    *,
    mask: np.ndarray | None = None,
    skip_post_blur: bool = False,
    lut_lab: np.ndarray | None = None,
    lut_rgb: np.ndarray | None = None,
    lut_tree: KDTree | None = None,
    use_lut_constrained: bool = False,
    lut_fingerprint: str | None = None,
) -> np.ndarray:
    """K-Means 颜色量化（含预缩放优化和 K-Means++ 初始化）。
    K-Means color quantization with pre-scaling optimization and K-Means++ init.

    Args:
        rgb: (H, W, 3) uint8 RGB 图像数组
        n_colors: 量化目标颜色数
        seed: 随机种子，默认 42
        mask: Optional ``(H, W)`` boolean quantization mask for unconstrained
            K-Means. Pixels outside the mask do not train K-Means or consume
            a cluster, and retain
            their input RGB in the output. (可选量化掩码；掩码外像素不参与
            K-Means、不占颜色簇，并在输出中保留原 RGB。)
        skip_post_blur: **Deprecated no-op**. Historical opt-out for a
            post-quantization ``cv2.medianBlur`` step that violated the
            ``unique RGB count <= n_colors`` contract by per-channel median
            synthesis. The blur has been removed entirely so the contract
            is always honoured; pre-quantization denoising is handled by
            the upstream bilateral filter and isolated-pixel cleanup by
            :func:`core.isolated_pixel_cleanup.cleanup_isolated_pixels`.
            This kwarg remains accepted for caller compatibility; it does
            not control any processing step.
            (**已废弃的空操作**。原来用于关闭破坏调色板契约的
            后量化 ``cv2.medianBlur``，该步骤已整块删除，契约总能满足。
            空间降噪由上游 bilateral 和下游孤立像素清理共同完成。)
        lut_lab: (N, 3) float64 LUT Lab 颜色表，用于 LUT 约束量化。
        lut_rgb: (N, 3) uint8 LUT RGB 颜色表，用于映射 LUT 索引到 RGB。
        lut_tree: 基于 ``lut_lab`` 构建的 KDTree。保留该参数用于兼容现有
            调用方和确认 LUT 已加载；量化在缓存未命中时会从权威
            ``lut_lab`` 重建默认 KDTree，以固定最近邻等距选择语义。
            (KDTree built from ``lut_lab``. Retained for caller compatibility
            and loaded-LUT validation; cache misses rebuild a default KDTree
            from authoritative ``lut_lab`` for deterministic tie-breaking.)
        use_lut_constrained: 若为 True 且 LUT 数据有效，使用 LUT-Constrained K-Means。
        lut_fingerprint: Retired caller metadata, accepted for compatibility.
            已退役的调用方元数据；兼容接收，缓存直接比较实际输入。

    Returns:
        (H, W, 3) uint8 quantized RGB. Without ``mask``, the whole-image
        unique RGB count is at most ``n_colors``; with ``mask``, that contract
        applies to selected pixels while unselected RGB is preserved.
        （量化后的 RGB；传入 ``mask`` 时颜色数上限仅约束掩码内像素，掩码外
        RGB 原样保留。）
    """
    h, w = rgb.shape[:2]
    mask_arr: np.ndarray | None = None
    selected_rgb: np.ndarray | None = None
    if mask is not None:
        mask_arr = np.asarray(mask, dtype=bool)
        if mask_arr.shape != (h, w):
            raise ValueError(
                f"mask shape {mask_arr.shape} does not match RGB shape {(h, w)}"
            )
        if bool(mask_arr.all()):
            # All-selected input is semantically identical to no mask. Keep
            # the historical INTER_AREA algorithm and full-image cache identity.
            mask_arr = None
            total_pixels = h * w
        else:
            selected_rgb = np.ascontiguousarray(rgb[mask_arr], dtype=np.uint8)
            total_pixels = int(selected_rgb.shape[0])
    else:
        total_pixels = h * w
    if total_pixels == 0:
        return rgb.copy()

    # ``skip_post_blur`` is a deprecated no-op (the post-blur has been
    # removed). It is still accepted so legacy call sites keep working.
    del skip_post_blur, lut_fingerprint  # Accepted legacy keywords have no effect.

    lut_constrained_active = (
        use_lut_constrained
        and lut_lab is not None
        and lut_lab.size > 0
        and lut_tree is not None
    )
    if mask_arr is not None and lut_constrained_active:
        raise ValueError("mask is not supported with LUT-constrained K-Means")
    if lut_constrained_active:
        return _lut_constrained_quantize(
            rgb, n_colors, seed,
            lut_lab=lut_lab, lut_rgb=lut_rgb,
        )

    effective_n_colors = _resolve_cluster_count(n_colors, total_pixels)
    if effective_n_colors != n_colors:
        _log.debug(
            "Clamping K-Means colors from %s to %s for %s pixels",
            n_colors,
            effective_n_colors,
            total_pixels,
        )
    unique_check_rgb = (
        rgb
        if selected_rgb is None
        else selected_rgb.reshape(1, total_pixels, 3)
    )
    low_unique_result = _maybe_return_low_unique_input(
        unique_check_rgb,
        effective_n_colors,
    )
    if low_unique_result is not None:
        return low_unique_result if selected_rgb is None else rgb.copy()

    _cache_key = ("rgb", effective_n_colors, seed, rgb.shape, mask_arr is not None)
    _cache_arrays = (rgb,) if selected_rgb is None else (selected_rgb, mask_arr)
    cached_result = _cached_quantization(_cache_key, _cache_arrays)
    if cached_result is not None:
        if mask_arr is not None:
            cached_result[~mask_arr] = rgb[~mask_arr]
        return cached_result

    t0 = time.time()
    if total_pixels > KMEANS_PIXEL_THRESHOLD:
        if selected_rgb is None:
            # 计算缩放比例，目标 50 万像素
            scale_factor = np.sqrt(total_pixels / KMEANS_PIXEL_THRESHOLD)
            small_h = int(h / scale_factor)
            small_w = int(w / scale_factor)

            _log.debug(
                f"🚀 Pre-scaling optimization: {w}×{h} → {small_w}×{small_h} ({total_pixels:,} → {small_w*small_h:,} pixels)"
            )

            # 缩小图片
            rgb_small = cv2.resize(rgb, (small_w, small_h), interpolation=cv2.INTER_AREA)
            pixels_small = rgb_small.reshape(-1, 3).astype(np.float32)
        else:
            # A spatial resize would blend air into selected pixels. Jittered
            # stratified sampling covers the full selected sequence without
            # phase-locking onto periodic pixel patterns. Its temporary index
            # arrays are bounded by KMEANS_PIXEL_THRESHOLD, not image size.
            sample_indices = _stratified_sample_indices(
                total_pixels,
                KMEANS_PIXEL_THRESHOLD,
                seed,
            )
            pixels_small = selected_rgb[sample_indices].astype(np.float32)

        # 在降采样像素上做 K-Means（使用 K-Means++ 初始化）
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
        flags = cv2.KMEANS_PP_CENTERS  # K-Means++ 初始化

        t_kmeans = time.time()
        _log.debug(f"K-Means++ on downscaled image ({effective_n_colors} colors)...")
        cv2.setRNGSeed(seed)  # 固定随机种子，确保 K-Means 结果可复现
        _, _, centers = cv2.kmeans(pixels_small, effective_n_colors, None, criteria, 5, flags)
        _log.debug(f"⏱️ K-Means: {time.time() - t_kmeans:.2f}s")

        # 用得到的 centers 直接映射原图（不再迭代，只做最近邻查找）
        t_map = time.time()
        _log.debug(f"Mapping centers to full image...")
        centers = centers.astype(np.float32)
        pixels_full = (
            rgb.reshape(-1, 3).astype(np.float32)
            if selected_rgb is None
            else selected_rgb.astype(np.float32)
        )

        # 批量计算每个像素到所有 centers 的距离，找最近的
        # 使用 KDTree 加速
        centers_tree = KDTree(centers)
        _, labels = centers_tree.query(pixels_full)
        _log.debug(f"⏱️ KDTree query: {time.time() - t_map:.2f}s")

        centers = centers.astype(np.uint8)
        quantized_pixels = centers[labels]
        if mask_arr is None:
            quantized_image = quantized_pixels.reshape(h, w, 3)
        else:
            quantized_image = rgb.copy()
            quantized_image[mask_arr] = quantized_pixels

        _log.debug(f"✅ Pre-scaling optimization complete!")
    else:
        # 小图直接做 K-Means
        _log.debug(f"K-Means++ quantization to {effective_n_colors} colors...")
        pixels = (
            rgb.reshape(-1, 3).astype(np.float32)
            if selected_rgb is None
            else selected_rgb.astype(np.float32)
        )
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
        flags = cv2.KMEANS_PP_CENTERS

        cv2.setRNGSeed(seed)  # 固定随机种子，确保 K-Means 结果可复现
        _, labels, centers = cv2.kmeans(pixels, effective_n_colors, None, criteria, 10, flags)

        centers = centers.astype(np.uint8)
        quantized_pixels = centers[labels.flatten()]
        if mask_arr is None:
            quantized_image = quantized_pixels.reshape(h, w, 3)
        else:
            quantized_image = rgb.copy()
            quantized_image[mask_arr] = quantized_pixels
    _log.debug(f"⏱️ Total quantization: {time.time() - t0:.2f}s")

    # Post-quantization ``cv2.medianBlur`` has been removed. It used to run
    # a per-channel median on the quantized RGB image, which synthesised new
    # RGB triples at neighbourhood boundaries and broke the
    # ``unique RGB count <= n_colors`` contract (inflating the palette by up
    # to 10-100x on noisy real-world images). Spatial denoising is handled
    # by the upstream ``apply_bilateral_filter`` + the dedicated
    # ``core.isolated_pixel_cleanup.cleanup_isolated_pixels`` stage that
    # operates on the material matrix without breaking the palette.
    # (后量化 medianBlur 已整块删除，它逐通道取中值会凭空造调色板外的
    # 新 RGB，破坏 ``unique <= n_colors`` 契约。降噪改由上游 bilateral 和
    # 下游 isolated_pixel_cleanup 共同完成，后者在材料矩阵上工作不破坏调色板。)
    _log.debug(f"Quantization complete!")
    # 写入缓存（LRU 简化：超限时清空最旧条目）
    _store_quantization(_cache_key, _cache_arrays, quantized_image)
    return quantized_image
