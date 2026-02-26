"""
孤立像素清理模块（Isolated Pixel Cleanup）

在 LUT 颜色匹配之后、voxel matrix 构建之前，对 material_matrix 执行孤立像素检测与替换。
孤立像素是指其 5 层材料堆叠编码与所有 8 邻域像素均不同的像素点，
这些像素在打印时会产生不必要的换色操作。

核心思路：将每个像素的 5 层材料 ID 编码为单个整数（堆叠编码），
通过 NumPy 向量化操作快速检测孤立像素，然后用邻域众数替换，
同时同步更新 matched_rgb 以保持数据一致性。
"""

import numpy as np
from collections import Counter


def _encode_stacks(material_matrix: np.ndarray, base: int) -> np.ndarray:
    """
    将 (H, W, 5) 的材料矩阵编码为 (H, W) 的整数矩阵。

    编码公式: layer0 * B^4 + layer1 * B^3 + layer2 * B^2 + layer3 * B + layer4
    其中 B = base（材料 ID 的最大值 + 1）

    Args:
        material_matrix: (H, W, 5) 材料堆叠矩阵
        base: 编码基数，通常为 max(material_id) + 1

    Returns:
        (H, W) 整数矩阵，dtype 为 int64
    """
    weights = np.array([base ** i for i in range(4, -1, -1)], dtype=np.int64)
    encoded = np.sum(material_matrix.astype(np.int64) * weights, axis=2)
    return encoded


def _detect_isolated(encoded: np.ndarray) -> np.ndarray:
    """
    检测孤立像素，返回 (H, W) 布尔掩码。

    孤立像素 = 堆叠编码与所有 8 邻域均不同。
    边界像素仅使用实际存在的邻居（3 个或 5 个）进行判定。
    使用切片比较（非 np.roll），正确处理边界。

    Args:
        encoded: (H, W) 整数编码矩阵

    Returns:
        (H, W) 布尔掩码，True 表示孤立像素
    """
    H, W = encoded.shape

    # 特殊情况：1x1 图像没有邻居，不判定为孤立
    if H <= 1 and W <= 1:
        return np.zeros((H, W), dtype=bool)

    # neighbor_count[i,j] = 像素 (i,j) 的实际邻居数量
    # diff_count[i,j] = 像素 (i,j) 与邻居不同的次数
    neighbor_count = np.zeros((H, W), dtype=np.int32)
    diff_count = np.zeros((H, W), dtype=np.int32)

    # 8 个方向的偏移: (dy, dx)
    directions = [(-1, -1), (-1, 0), (-1, 1),
                  (0, -1),           (0, 1),
                  (1, -1),  (1, 0),  (1, 1)]

    for dy, dx in directions:
        # 计算中心像素和邻居像素的切片范围
        # 中心区域
        c_y_start = max(0, -dy)
        c_y_end = H - max(0, dy)
        c_x_start = max(0, -dx)
        c_x_end = W - max(0, dx)

        # 邻居区域（偏移后）
        n_y_start = c_y_start + dy
        n_y_end = c_y_end + dy
        n_x_start = c_x_start + dx
        n_x_end = c_x_end + dx

        center = encoded[c_y_start:c_y_end, c_x_start:c_x_end]
        neighbor = encoded[n_y_start:n_y_end, n_x_start:n_x_end]

        # 该方向上有邻居的像素，邻居计数 +1
        neighbor_count[c_y_start:c_y_end, c_x_start:c_x_end] += 1
        # 与邻居不同的像素，差异计数 +1
        diff_count[c_y_start:c_y_end, c_x_start:c_x_end] += (center != neighbor).astype(np.int32)

    # 孤立 = 与所有实际邻居都不同（且至少有一个邻居）
    isolated = (diff_count == neighbor_count) & (neighbor_count > 0)
    return isolated


def _find_neighbor_mode(encoded: np.ndarray, isolated_mask: np.ndarray) -> np.ndarray:
    """
    对每个孤立像素，找到其 8 邻域中出现次数最多的堆叠编码。

    统计 8 邻域中各堆叠编码出现次数，选择最多的作为替换值。
    多个并列众数时确定性选择其中之一（Counter.most_common 的第一个）。

    Args:
        encoded: (H, W) 整数编码矩阵
        isolated_mask: (H, W) 布尔掩码，True 表示孤立像素

    Returns:
        (H, W) 数组，孤立像素位置存储邻域众数编码，非孤立像素位置值为原编码
    """
    H, W = encoded.shape
    mode_map = encoded.copy()

    directions = [(-1, -1), (-1, 0), (-1, 1),
                  (0, -1),           (0, 1),
                  (1, -1),  (1, 0),  (1, 1)]

    # 获取孤立像素的坐标
    isolated_coords = np.argwhere(isolated_mask)

    for i, j in isolated_coords:
        neighbors = []
        for dy, dx in directions:
            ni, nj = i + dy, j + dx
            if 0 <= ni < H and 0 <= nj < W:
                neighbors.append(encoded[ni, nj])

        if neighbors:
            counter = Counter(neighbors)
            # most_common(1) 返回出现次数最多的，确定性选择
            mode_map[i, j] = counter.most_common(1)[0][0]

    return mode_map


def cleanup_isolated_pixels(
    material_matrix: np.ndarray,
    matched_rgb: np.ndarray,
    lut_rgb: np.ndarray,
    ref_stacks: np.ndarray,
) -> tuple:
    """
    检测并替换孤立像素。

    流程：编码堆叠 → 检测孤立 → 邻域众数替换 → LUT 反查同步 RGB
    单轮清理，不修改输入数组。

    Args:
        material_matrix: (H, W, 5) 材料堆叠矩阵
        matched_rgb: (H, W, 3) 匹配的 RGB 颜色
        lut_rgb: (N, 3) LUT 颜色表
        ref_stacks: (N, 5) LUT 材料堆叠表

    Returns:
        (cleaned_matched_rgb, cleaned_material_matrix) - 清理后的副本
    """
    # 创建副本，不修改输入
    cleaned_mat = material_matrix.copy()
    cleaned_rgb = matched_rgb.copy()

    H, W = material_matrix.shape[:2]
    total_pixels = H * W

    # 步骤 1：编码堆叠
    base = int(material_matrix.max()) + 1 if material_matrix.size > 0 else 1
    encoded = _encode_stacks(material_matrix, base)

    # 步骤 2：检测孤立像素
    isolated_mask = _detect_isolated(encoded)
    isolated_count = int(np.sum(isolated_mask))

    if isolated_count == 0:
        print(f"[ISOLATED_CLEANUP] 未检测到孤立像素，跳过清理")
        return cleaned_rgb, cleaned_mat

    # 步骤 3：找到邻域众数
    mode_map = _find_neighbor_mode(encoded, isolated_mask)

    # 步骤 4：构建 LUT 编码 → 索引 的映射，用于反查
    lut_encoded = _encode_stacks(ref_stacks.reshape(1, -1, 5), base).flatten()
    # 编码 → LUT 索引的字典
    encode_to_lut_idx = {}
    for idx in range(len(lut_encoded)):
        enc_val = int(lut_encoded[idx])
        if enc_val not in encode_to_lut_idx:
            encode_to_lut_idx[enc_val] = idx

    # 步骤 5：替换孤立像素
    replaced_count = 0
    isolated_coords = np.argwhere(isolated_mask)

    for i, j in isolated_coords:
        new_enc = int(mode_map[i, j])
        if new_enc in encode_to_lut_idx:
            lut_idx = encode_to_lut_idx[new_enc]
            cleaned_mat[i, j] = ref_stacks[lut_idx]
            cleaned_rgb[i, j] = lut_rgb[lut_idx]
            replaced_count += 1

    # 输出统计信息
    percentage = (replaced_count / total_pixels * 100) if total_pixels > 0 else 0
    print(
        f"[ISOLATED_CLEANUP] ✅ 清理完成: "
        f"检测到 {isolated_count} 个孤立像素, "
        f"成功合并 {replaced_count} 个, "
        f"占总像素 {percentage:.2f}% "
        f"(总像素={total_pixels})"
    )

    return cleaned_rgb, cleaned_mat
