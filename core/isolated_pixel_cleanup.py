"""孤立像素清理模块（Isolated Pixel Cleanup）。
Isolated pixel cleanup for the material matrix.

检测与 8 邻域全部不同的严格孤立像素（盐锡噪点），将其材料堆叠与
RGB 替换为 8 邻域众数邻居的对应值。新版本不再依赖 LUT 标准化步骤：
邻居像素本身就是由上游求解器（经典 LUT 匹配 / 预测匹配 / 材料档案
求解器）写入的合法值，直接复制即可。这让函数同时适用于 LUT 模式、
预测匹配模式和材料档案模式。

Replace strict 1-pixel isolates (pixels whose material stack differs from all
8 neighbours) with the corresponding values from the 8-neighbour mode's
neighbour pixel. The LUT-canonicalisation detour has been removed: neighbour
pixels carry legal stacks/RGB by construction (they were written by the
upstream solver), so direct copy is both simpler and pipeline-agnostic.
"""

import numpy as np
from collections import Counter
from typing import Any

from api.structured_logging import get_logger

_log = get_logger(__name__)


def _encode_stacks(material_matrix, base):
    """将 (H, W, N) 的材料矩阵编码为 (H, W) 整数矩阵。"""
    if material_matrix.ndim != 3:
        raise ValueError(f"material_matrix must be 3D, got shape={material_matrix.shape}")
    n = material_matrix.shape[2]
    if n == 0 or base ** n <= np.iinfo(np.int64).max:
        weights = np.array([base ** i for i in range(n - 1, -1, -1)], dtype=np.int64)
        return np.sum(material_matrix.astype(np.int64) * weights, axis=2)
    # Deep stacks (e.g. 8 materials x 30 layers) overflow a base-M int64 key.
    # Codes are only compared for equality, so per-image row IDs are exact.
    # 深叠层时 base-M 编码会溢出 int64；编码只做相等比较，改用逐行唯一 ID 等价替代。
    h, w = material_matrix.shape[:2]
    _, inverse = np.unique(
        material_matrix.reshape(h * w, n), axis=0, return_inverse=True
    )
    return inverse.reshape(h, w).astype(np.int64)


def _detect_isolated(encoded):
    """检测孤立像素（与所有 8 邻域均不同），返回布尔掩码。"""
    H, W = encoded.shape
    if H <= 1 and W <= 1:
        return np.zeros((H, W), dtype=bool)
    nc = np.zeros((H, W), dtype=np.int32)
    dc = np.zeros((H, W), dtype=np.int32)
    for dy, dx in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
        cy0, cy1 = max(0, -dy), H - max(0, dy)
        cx0, cx1 = max(0, -dx), W - max(0, dx)
        c = encoded[cy0:cy1, cx0:cx1]
        n = encoded[cy0+dy:cy1+dy, cx0+dx:cx1+dx]
        nc[cy0:cy1, cx0:cx1] += 1
        dc[cy0:cy1, cx0:cx1] += (c != n).astype(np.int32)
    return (dc == nc) & (nc > 0)


def _find_neighbor_mode_with_source(encoded, isolated_mask):
    """对每个孤立像素返回（众数编码，贡献该编码的邻居坐标）。
    For each isolated pixel, return (mode_encoding, (ni, nj)) where (ni, nj)
    is the location of one neighbour carrying that mode encoding. The caller
    uses (ni, nj) to copy both the material stack and the RGB directly,
    sidestepping the previous LUT-canonicalisation step.
    """
    H, W = encoded.shape
    dirs = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    results: dict[tuple[int, int], tuple[int, tuple[int, int]]] = {}
    for i, j in np.argwhere(isolated_mask):
        i_i, j_i = int(i), int(j)
        neighbour_entries: list[tuple[int, int, int]] = []
        for dy, dx in dirs:
            ni, nj = i_i + dy, j_i + dx
            if 0 <= ni < H and 0 <= nj < W:
                neighbour_entries.append((ni, nj, int(encoded[ni, nj])))
        if not neighbour_entries:
            continue
        counts = Counter(entry[2] for entry in neighbour_entries)
        mode_enc = counts.most_common(1)[0][0]
        for ni, nj, enc in neighbour_entries:
            if enc == mode_enc:
                results[(i_i, j_i)] = (mode_enc, (ni, nj))
                break
    return results


def cleanup_isolated_pixels(
    material_matrix,
    matched_rgb,
    lut_rgb=None,  # Deprecated no-op; kept for backward compatibility.
    ref_stacks=None,  # Deprecated no-op; kept for backward compatibility.
):
    """孤立像素清理：与所有 8 邻域均不同的像素，直接复制邻居众数所在的
    材料堆叠与 RGB，因此则不会凭空造调色板外的新值。
    Replace strict 1-pixel isolates by copying the material stack and RGB
    from the neighbour that contributed the 8-neighbour mode encoding. The
    operation is palette-preserving by construction (we only ever reuse
    values already present in the image) and therefore works uniformly in
    LUT, predictive and material-archive pipelines.

    Args:
        material_matrix: ``(H, W, N)`` integer material stack tensor.
        matched_rgb: ``(H, W, 3)`` uint8 RGB image matched upstream.
        lut_rgb: **Deprecated no-op**. Historical LUT canonicalisation
            source; the function now copies directly from neighbour pixels,
            which is valid because neighbour stacks/RGB are already the
            canonical upstream output.
        ref_stacks: **Deprecated no-op**. Historical LUT canonicalisation
            source; retained so legacy positional callers keep working.

    Returns:
        ``(cleaned_rgb, cleaned_material_matrix)`` tuple with the same
        shapes/dtypes as the inputs.
    """
    del lut_rgb, ref_stacks  # silence unused-arg; kwargs kept for API parity
    cleaned_rgb, cleaned_mat, _cleaned_target = _cleanup_isolated_pixels(
        material_matrix,
        matched_rgb,
    )
    return cleaned_rgb, cleaned_mat


def cleanup_isolated_pixels_with_target_map(
    material_matrix: np.ndarray,
    matched_rgb: np.ndarray,
    target_rgb_map: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Clean isolated output pixels and preserve their final target ownership.

    清理孤立输出像素，并同步复制来源邻居的目标色归属，使动态层数收益曲线
    可以按最终打印矩阵重新加权。

    Args:
        material_matrix: ``(H, W, N)`` material stack tensor.
            ``(H, W, N)`` 材料堆叠张量。
        matched_rgb: ``(H, W, 3)`` simulated output colors.
            ``(H, W, 3)`` 模拟输出颜色。
        target_rgb_map: ``(H, W, 3)`` target-color ownership map.
            ``(H, W, 3)`` 目标色归属图。

    Returns:
        Cleaned output colors, material stacks, and target-color map.
        清理后的输出颜色、材料堆叠和目标色归属图。
    """
    target_map = np.asarray(target_rgb_map)
    if target_map.shape != np.asarray(matched_rgb).shape:
        raise ValueError(
            "target_rgb_map must have the same shape as matched_rgb"
        )
    cleaned_rgb, cleaned_mat, cleaned_target = _cleanup_isolated_pixels(
        material_matrix,
        matched_rgb,
        target_map,
    )
    if cleaned_target is None:  # pragma: no cover - guarded by target_map input
        raise RuntimeError("cleaned target map is unavailable")
    return cleaned_rgb, cleaned_mat, cleaned_target


def _cleanup_isolated_pixels(
    material_matrix: np.ndarray,
    matched_rgb: np.ndarray,
    target_rgb_map: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Shared cleanup implementation with optional target ownership copying."""
    import time

    cleaned_mat = material_matrix.copy()
    cleaned_rgb = matched_rgb.copy()
    cleaned_target = target_rgb_map.copy() if target_rgb_map is not None else None
    H, W = material_matrix.shape[:2]
    total_pixels = H * W

    base = int(material_matrix.max()) + 1 if material_matrix.size > 0 else 1
    encoded = _encode_stacks(material_matrix, base)

    t0 = time.time()
    iso = _detect_isolated(encoded)
    iso_count = int(np.sum(iso))
    replaced = 0
    if iso_count > 0:
        mode_sources = _find_neighbor_mode_with_source(encoded, iso)
        for (i, j), (mode_enc, (ni, nj)) in mode_sources.items():
            cleaned_mat[i, j] = material_matrix[ni, nj]
            cleaned_rgb[i, j] = matched_rgb[ni, nj]
            if cleaned_target is not None and target_rgb_map is not None:
                cleaned_target[i, j] = target_rgb_map[ni, nj]
            encoded[i, j] = mode_enc
            replaced += 1
    ratio = (replaced / total_pixels * 100) if total_pixels > 0 else 0.0
    extra: dict[str, Any] = {
        "event": "isolated_pixels_cleaned",
        "isolated_count": iso_count,
        "merge_ratio_percent": round(ratio, 3),
        "duration_ms": round((time.time() - t0) * 1000, 3),
    }
    if replaced != iso_count:
        extra["merged_count"] = replaced
    _log.info("Isolated pixels cleaned", extra=extra)

    return cleaned_rgb, cleaned_mat, cleaned_target
