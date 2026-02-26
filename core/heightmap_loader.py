"""
Lumina Studio - 高度图加载与处理模块 (Heightmap Loader)

负责高度图的加载、验证、灰度转换、缩放和高度映射。
灰度映射约定：纯黑(0) = 最大高度，纯白(255) = 最小高度（底板厚度）。
"""

import numpy as np
import cv2


class HeightmapLoader:
    """高度图加载与处理器"""

    # 缩略图最大尺寸
    THUMBNAIL_MAX_SIZE = 200

    @staticmethod
    def _to_grayscale(image: np.ndarray) -> np.ndarray:
        """
        将图像转换为单通道灰度图。

        Args:
            image: np.ndarray，可能为灰度 (H,W)、RGB (H,W,3) 或 RGBA (H,W,4)

        Returns:
            np.ndarray: (H, W) uint8 灰度数组
        """
        # 已经是灰度图
        if image.ndim == 2:
            return image.astype(np.uint8)

        channels = image.shape[2]

        if channels == 4:
            # RGBA → BGR → 灰度
            bgr = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        elif channels == 3:
            # cv2.imread 读取的是 BGR 格式，直接转灰度
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            # 未知通道数，取第一个通道
            gray = image[:, :, 0]

        return gray.astype(np.uint8)

    @staticmethod
    def _resize_to_target(grayscale: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
        """
        使用双线性插值缩放灰度图至目标尺寸。

        Args:
            grayscale: (H, W) uint8 灰度数组
            target_w: 目标宽度（像素）
            target_h: 目标高度（像素）

        Returns:
            np.ndarray: (target_h, target_w) uint8 数组
        """
        orig_h, orig_w = grayscale.shape[:2]
        resized = cv2.resize(grayscale, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        print(f"[HEIGHTMAP] 缩放高度图: ({orig_w}x{orig_h}) → ({target_w}x{target_h})")
        return resized.astype(np.uint8)

    @staticmethod
    def _map_grayscale_to_height(
        grayscale: np.ndarray,
        max_relief_height: float,
        base_thickness: float
    ) -> np.ndarray:
        """
        灰度值到高度的线性映射（NumPy 向量化计算）。

        公式: height_mm = max_relief_height - (grayscale / 255.0) * (max_relief_height - base_thickness)
        纯黑(0) → max_relief_height（最高）
        纯白(255) → base_thickness（最低）

        Args:
            grayscale: (H, W) uint8 灰度数组
            max_relief_height: 最大浮雕高度（mm）
            base_thickness: 底板厚度（mm）

        Returns:
            np.ndarray: (H, W) float32，单位 mm
        """
        height_mm = max_relief_height - (grayscale.astype(np.float32) / 255.0) * (max_relief_height - base_thickness)
        return height_mm.astype(np.float32)

    @staticmethod
    def _check_aspect_ratio(
        heightmap_w: int, heightmap_h: int,
        target_w: int, target_h: int
    ) -> str | None:
        """
        检查高度图与目标图的宽高比偏差。

        偏差公式: |w1/h1 - w2/h2| / (w2/h2)
        偏差超过 20% 返回警告字符串，否则返回 None。

        Args:
            heightmap_w: 高度图宽度
            heightmap_h: 高度图高度
            target_w: 目标宽度
            target_h: 目标高度

        Returns:
            str | None: 警告信息或 None
        """
        if heightmap_h == 0 or target_h == 0:
            return "⚠️ 高度图或目标图高度为 0，无法计算宽高比"

        hm_ratio = heightmap_w / heightmap_h
        target_ratio = target_w / target_h
        deviation = abs(hm_ratio - target_ratio) / target_ratio

        if deviation > 0.2:
            return (
                f"⚠️ 高度图宽高比与原图偏差 {deviation:.0%}，可能不匹配 "
                f"(高度图: {heightmap_w}x{heightmap_h}, 目标: {target_w}x{target_h})"
            )
        return None

    @staticmethod
    def _check_contrast(grayscale: np.ndarray) -> str | None:
        """
        检查灰度图对比度（标准差）。

        标准差小于 1.0 表示灰度变化极小，浮雕效果可能不明显。

        Args:
            grayscale: (H, W) uint8 灰度数组

        Returns:
            str | None: 警告信息或 None
        """
        std_val = float(np.std(grayscale))
        if std_val < 1.0:
            return f"⚠️ 高度图灰度变化极小（标准差={std_val:.2f}），浮雕效果可能不明显"
        return None

    @staticmethod
    def load_and_validate(heightmap_path: str) -> dict:
        """
        加载并验证高度图文件。

        Args:
            heightmap_path: 高度图文件路径

        Returns:
            dict: {
                'success': bool,
                'grayscale': np.ndarray (H, W) uint8 或 None,
                'original_size': (w, h) 或 None,
                'thumbnail': np.ndarray 或 None,  # 用于 UI 预览
                'warnings': list[str],
                'error': str 或 None
            }
        """
        warnings_list = []

        # 读取图像文件（兼容中文路径）
        try:
            img_data = np.fromfile(heightmap_path, dtype=np.uint8)
            image = cv2.imdecode(img_data, cv2.IMREAD_UNCHANGED)
        except Exception as e:
            return {
                'success': False,
                'grayscale': None,
                'original_size': None,
                'thumbnail': None,
                'warnings': [],
                'error': f"❌ 无法读取高度图文件: {heightmap_path} ({e})"
            }
        if image is None:
            return {
                'success': False,
                'grayscale': None,
                'original_size': None,
                'thumbnail': None,
                'warnings': [],
                'error': f"❌ 无法读取高度图文件: {heightmap_path}"
            }

        orig_h, orig_w = image.shape[:2]
        print(f"[HEIGHTMAP] 加载高度图: {heightmap_path} ({orig_w}x{orig_h})")

        # 转换为灰度
        grayscale = HeightmapLoader._to_grayscale(image)

        # 生成缩略预览图（最大 200x200）
        max_dim = max(orig_h, orig_w)
        if max_dim > HeightmapLoader.THUMBNAIL_MAX_SIZE:
            scale = HeightmapLoader.THUMBNAIL_MAX_SIZE / max_dim
            thumb_w = int(orig_w * scale)
            thumb_h = int(orig_h * scale)
            thumbnail = cv2.resize(grayscale, (thumb_w, thumb_h), interpolation=cv2.INTER_LINEAR)
        else:
            thumbnail = grayscale.copy()

        return {
            'success': True,
            'grayscale': grayscale,
            'original_size': (orig_w, orig_h),
            'thumbnail': thumbnail,
            'warnings': warnings_list,
            'error': None
        }

    @staticmethod
    def load_and_process(
        heightmap_path: str,
        target_w: int,
        target_h: int,
        max_relief_height: float,
        base_thickness: float
    ) -> dict:
        """
        加载高度图并生成 Height_Matrix。
        完整处理流程：加载 → 验证 → 灰度转换 → 宽高比检查 → 缩放 → 对比度检查 → 高度映射。

        Args:
            heightmap_path: 高度图文件路径
            target_w: 目标宽度（像素）
            target_h: 目标高度（像素）
            max_relief_height: 最大浮雕高度（mm）
            base_thickness: 底板厚度（mm）

        Returns:
            dict: {
                'success': bool,
                'height_matrix': np.ndarray (H, W) float32 单位 mm 或 None,
                'stats': {'min_mm': float, 'max_mm': float, 'avg_mm': float} 或 None,
                'warnings': list[str],
                'error': str 或 None
            }
        """
        warnings_list = []

        # Step 1: 加载并验证
        validate_result = HeightmapLoader.load_and_validate(heightmap_path)
        if not validate_result['success']:
            return {
                'success': False,
                'height_matrix': None,
                'stats': None,
                'warnings': validate_result['warnings'],
                'error': validate_result['error']
            }

        grayscale = validate_result['grayscale']
        orig_w, orig_h = validate_result['original_size']
        warnings_list.extend(validate_result['warnings'])

        # Step 2: 宽高比检查
        ar_warning = HeightmapLoader._check_aspect_ratio(orig_w, orig_h, target_w, target_h)
        if ar_warning:
            warnings_list.append(ar_warning)

        # Step 3: 缩放至目标尺寸
        grayscale = HeightmapLoader._resize_to_target(grayscale, target_w, target_h)

        # Step 4: 对比度检查
        contrast_warning = HeightmapLoader._check_contrast(grayscale)
        if contrast_warning:
            warnings_list.append(contrast_warning)

        # Step 5: 灰度值映射为高度矩阵
        height_matrix = HeightmapLoader._map_grayscale_to_height(
            grayscale, max_relief_height, base_thickness
        )

        # Step 6: 计算统计信息
        stats = {
            'min_mm': float(np.min(height_matrix)),
            'max_mm': float(np.max(height_matrix)),
            'avg_mm': float(np.mean(height_matrix))
        }

        print(f"[HEIGHTMAP] 高度映射完成: "
              f"min={stats['min_mm']:.2f}mm, max={stats['max_mm']:.2f}mm, avg={stats['avg_mm']:.2f}mm")

        return {
            'success': True,
            'height_matrix': height_matrix,
            'stats': stats,
            'warnings': warnings_list,
            'error': None
        }
