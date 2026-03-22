"""
Lumina Studio - Mesh Generation Strategies (Refactored v2.2)
Mesh generation strategy module - Refactored version

ARCHITECTURE:
- High-Fidelity Mode: RLE-based solid extrusion with morphological dilation
- Pixel Art Mode: Legacy voxel mesher (blocky aesthetic with gaps)

PERFORMANCE: Optimized for 100k+ faces with instant generation.

CHANGELOG v2.2:
- Vectorized _greedy_rect_merge using NumPy operations
- np.diff + np.where replaces pixel-by-pixel horizontal scanning
- np.all on slices replaces inner for-loop for vertical expansion
- ~10-50x faster for large images (1000x1000+)

CHANGELOG v2.1:
- Added morphological dilation to HighFidelityMesher to fix thin wall issues
- Ensures all features are printable (>0.4mm nozzle width)
- Eliminates micro-gaps between adjacent color regions
"""

from abc import ABC, abstractmethod
import numpy as np
import cv2
import trimesh
from config import ModelingMode

try:
    import numba

    HAS_NUMBA = True
except ImportError:
    numba = None
    HAS_NUMBA = False


if HAS_NUMBA:

    @numba.njit(cache=True)
    def _greedy_rect_numba(mask):
        h, w = mask.shape
        processed = np.zeros((h, w), dtype=np.uint8)
        rects = np.empty((h * w, 4), dtype=np.int32)
        count = 0

        for y in range(h):
            x = 0
            while x < w:
                if mask[y, x] and processed[y, x] == 0:
                    x_start = x
                    x_end = x + 1
                    while x_end < w and mask[y, x_end] and processed[y, x_end] == 0:
                        x_end += 1

                    y_end = y + 1
                    while y_end < h:
                        valid = 1
                        for xx in range(x_start, x_end):
                            if (not mask[y_end, xx]) or processed[y_end, xx] != 0:
                                valid = 0
                                break
                        if valid == 0:
                            break
                        y_end += 1

                    for yy in range(y, y_end):
                        for xx in range(x_start, x_end):
                            processed[yy, xx] = 1

                    rects[count, 0] = x_start
                    rects[count, 1] = y
                    rects[count, 2] = x_end
                    rects[count, 3] = y_end
                    count += 1
                    x = x_end
                else:
                    x += 1

        return rects[:count]

else:

    def _greedy_rect_numba(mask):
        return None


class BaseMesher(ABC):
    """Mesh generator abstract base class"""

    _VERTEX_TEMPLATE = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=np.float64
    )
    _FACE_TEMPLATE = np.array(
        [
            [0, 2, 1],
            [0, 3, 2],
            [4, 5, 6],
            [4, 6, 7],
            [0, 1, 5],
            [0, 5, 4],
            [1, 2, 6],
            [1, 6, 5],
            [2, 3, 7],
            [2, 7, 6],
            [3, 0, 4],
            [3, 4, 7],
        ],
        dtype=np.int64,
    )

    @abstractmethod
    def generate_mesh(self, voxel_matrix, mat_id, height_px):
        """
        Generate 3D mesh for specified material

        Args:
            voxel_matrix: (Z, H, W) voxel matrix
            mat_id: Material ID (0-7 for regular materials, -2 for backing layer)
            height_px: Image height (pixels)

        Returns:
            trimesh.Trimesh or None
        """
        pass

    def generate_backing_mesh(self, voxel_matrix, height_px):
        """
        Generate backing mesh (convenience method)

        Args:
            voxel_matrix: (Z, H, W) voxel matrix
            height_px: Image height (pixels)

        Returns:
            trimesh.Trimesh or None
        """
        return self.generate_mesh(voxel_matrix, mat_id=-2, height_px=height_px)

    @staticmethod
    def _greedy_rect_merge(mask):
        """Greedy rectangle merging on a 2D boolean mask.
        贪婪矩形合并（2D 布尔掩码）。

        Args:
            mask (np.ndarray): (H, W) bool array. (布尔掩码)

        Returns:
            np.ndarray: (R, 4) float64 array of rectangles [x0, y0, x1, y1].
                (矩形数组，像素坐标)
        """
        if HAS_NUMBA:
            rects = _greedy_rect_numba(mask)
            return rects.astype(np.float64)

        h, w = mask.shape
        processed = np.zeros_like(mask, dtype=bool)
        rectangles = []
        for y in range(h):
            row_valid = mask[y] & ~processed[y]
            if not np.any(row_valid):
                continue
            padded = np.concatenate([[False], row_valid, [False]])
            diff = np.diff(padded.astype(np.int8))
            starts = np.where(diff == 1)[0]
            ends = np.where(diff == -1)[0]
            for x_start, x_end in zip(starts, ends):
                if processed[y, x_start]:
                    continue
                y_end = y + 1
                while y_end < h:
                    segment_mask = mask[y_end, x_start:x_end]
                    segment_proc = processed[y_end, x_start:x_end]
                    if not (np.all(segment_mask) and not np.any(segment_proc)):
                        break
                    y_end += 1
                processed[y:y_end, x_start:x_end] = True
                rectangles.append((float(x_start), float(y), float(x_end), float(y_end)))
        if not rectangles:
            return np.empty((0, 4), dtype=np.float64)
        return np.array(rectangles, dtype=np.float64)

    def _build_mesh_from_layer_rects(self, layer_rectangles, height_px):
        """Build trimesh from list of (z_bottom, z_top, rects_array) tuples.
        从层矩形列表构建 trimesh。

        Args:
            layer_rectangles: list of (z_bottom, z_top, np.ndarray(R,4)).
            height_px (int): Image height for Y-axis inversion.

        Returns:
            trimesh.Trimesh or None
        """
        total_rects = sum(r.shape[0] for _, _, r in layer_rectangles)
        if total_rects == 0:
            return None

        raw_verts = np.empty((total_rects * 8, 3), dtype=np.float64)
        raw_faces = np.empty((total_rects * 12, 3), dtype=np.int64)
        rect_idx = 0

        for z_bottom, z_top, rect_arr in layer_rectangles:
            n = rect_arr.shape[0]
            if n == 0:
                continue
            x0, y0, x1, y1 = rect_arr[:, 0], rect_arr[:, 1], rect_arr[:, 2], rect_arr[:, 3]
            wy0 = height_px - y1
            wy1 = height_px - y0

            base = np.empty((n, 8, 3), dtype=np.float64)
            base[:, 0, 0] = x0
            base[:, 0, 1] = wy0
            base[:, 0, 2] = z_bottom
            base[:, 1, 0] = x1
            base[:, 1, 1] = wy0
            base[:, 1, 2] = z_bottom
            base[:, 2, 0] = x1
            base[:, 2, 1] = wy1
            base[:, 2, 2] = z_bottom
            base[:, 3, 0] = x0
            base[:, 3, 1] = wy1
            base[:, 3, 2] = z_bottom
            base[:, 4, 0] = x0
            base[:, 4, 1] = wy0
            base[:, 4, 2] = z_top
            base[:, 5, 0] = x1
            base[:, 5, 1] = wy0
            base[:, 5, 2] = z_top
            base[:, 6, 0] = x1
            base[:, 6, 1] = wy1
            base[:, 6, 2] = z_top
            base[:, 7, 0] = x0
            base[:, 7, 1] = wy1
            base[:, 7, 2] = z_top

            v_start = rect_idx * 8
            raw_verts[v_start : v_start + n * 8] = base.reshape(-1, 3)

            offsets = (np.arange(n, dtype=np.int64) * 8 + v_start).reshape(-1, 1, 1)
            faces = self._FACE_TEMPLATE.reshape(1, 12, 3) + offsets
            f_start = rect_idx * 12
            raw_faces[f_start : f_start + n * 12] = faces.reshape(-1, 3)
            rect_idx += n

        # Fast vertex dedup via integer coordinate encoding
        ix = np.round(raw_verts[:, 0]).astype(np.int64)
        iy = np.round(raw_verts[:, 1]).astype(np.int64)
        iz = np.round(raw_verts[:, 2]).astype(np.int64)
        codes = ix * 10_000_000 + iy * 10_000 + iz
        _, first_idx, inverse = np.unique(codes, return_index=True, return_inverse=True)

        unique_verts = raw_verts[first_idx]
        deduped_faces = inverse[raw_faces]

        mesh = trimesh.Trimesh(vertices=unique_verts, faces=deduped_faces, process=False)
        mesh.update_faces(mesh.unique_faces())
        return mesh


class VoxelMesher(BaseMesher):
    """
    Pixel art mode mesh generator
    Uses greedy rectangle merging + Z-layer compression for optimized blocky mesh.
    """

    def generate_mesh(self, voxel_matrix, mat_id, height_px):
        """Generate pixel mode mesh with greedy rect merging and Z-compression.
        生成像素模式网格（贪婪矩形合并 + Z 层压缩）。

        Args:
            voxel_matrix (np.ndarray): (Z, H, W) int voxel matrix.
            mat_id (int): Material ID (0-7 or -2 for backing).
            height_px (int): Image height in pixels.

        Returns:
            trimesh.Trimesh or None
        """
        layer_groups = self._merge_layers_no_dilation(voxel_matrix, mat_id)
        if not layer_groups:
            return None

        mesh_type = "Backing" if mat_id == -2 else f"Mat ID {mat_id}"
        print(f"[VOXEL_MESHER] {mesh_type}: Merged {voxel_matrix.shape[0]} Z-layers -> {len(layer_groups)} groups")

        layer_rects = []
        for start_z, end_z, mask in layer_groups:
            rects = self._greedy_rect_merge(mask)
            if rects.shape[0] > 0:
                layer_rects.append((float(start_z), float(end_z + 1), rects))

        mesh = self._build_mesh_from_layer_rects(layer_rects, height_px)
        if mesh is not None:
            total_rects = sum(r.shape[0] for _, _, r in layer_rects)
            print(
                f"[VOXEL_MESHER] {mesh_type}: {total_rects} rects -> "
                f"{len(mesh.vertices):,} verts, {len(mesh.faces):,} faces"
            )
        return mesh

    @staticmethod
    def _merge_layers_no_dilation(voxel_matrix, mat_id):
        """Group consecutive Z-layers with identical masks (no dilation).
        将连续相同掩码的 Z 层合并为组（不做膨胀）。"""
        layer_groups = []
        prev_mask = None
        start_z = 0
        for z in range(voxel_matrix.shape[0]):
            curr_mask = voxel_matrix[z] == mat_id
            if not np.any(curr_mask):
                if prev_mask is not None:
                    layer_groups.append((start_z, z - 1, prev_mask))
                    prev_mask = None
                continue
            if prev_mask is None:
                start_z = z
                prev_mask = curr_mask
            elif np.array_equal(curr_mask, prev_mask):
                pass
            else:
                layer_groups.append((start_z, z - 1, prev_mask))
                start_z = z
                prev_mask = curr_mask
        if prev_mask is not None:
            layer_groups.append((start_z, voxel_matrix.shape[0] - 1, prev_mask))
        return layer_groups


class HighFidelityMesher(BaseMesher):
    """
    High-fidelity mode mesh generator
    Uses Greedy Rectangle Merging algorithm to generate optimized, watertight 3D mesh

    ALGORITHM:
    1. Apply morphological dilation to thicken thin features
    2. Vertical layer compression (merge identical Z-layers)
    3. Greedy rectangle merging (find maximal rectangles in 2D mask)
    4. Generate ONE box per rectangle (instead of per-pixel-row)

    OPTIMIZATION:
    - Old method: 1 box per horizontal run → ~100k faces for 200x200 image
    - New method: 1 box per maximal rectangle → ~5k-10k faces (80-95% reduction)

    GEOMETRY:
    - Dilation: Expands features by ~0.1-0.15mm to ensure printability
    - Perfect edge-to-edge contact (watertight)
    - Vertices match pixel coordinates exactly
    """

    def generate_mesh(self, voxel_matrix, mat_id, height_px):
        """Generate high-fidelity mode mesh with greedy rect merging and dilation.
        生成高保真模式网格（贪婪矩形合并 + 形态学膨胀）。

        Args:
            voxel_matrix (np.ndarray): (Z, H, W) int voxel matrix.
            mat_id (int): Material ID (0-7 or -2 for backing).
            height_px (int): Image height in pixels.

        Returns:
            trimesh.Trimesh or None
        """
        layer_groups = self._merge_layers_with_dilation(voxel_matrix, mat_id)
        if not layer_groups:
            return None

        mesh_type = "Backing" if mat_id == -2 else f"Mat ID {mat_id}"
        print(f"[HIGH_FIDELITY] {mesh_type}: Merged {voxel_matrix.shape[0]} layers -> {len(layer_groups)} groups")

        layer_rects = []
        for start_z, end_z, mask in layer_groups:
            rects = self._greedy_rect_merge(mask)
            if rects.shape[0] > 0:
                layer_rects.append((float(start_z), float(end_z + 1), rects))

        mesh = self._build_mesh_from_layer_rects(layer_rects, height_px)
        if mesh is not None:
            total_rects = sum(r.shape[0] for _, _, r in layer_rects)
            print(
                f"[HIGH_FIDELITY] {mesh_type}: {total_rects} rects -> "
                f"{len(mesh.vertices):,} verts, {len(mesh.faces):,} faces"
            )
        return mesh

    def _merge_layers_with_dilation(self, voxel_matrix, mat_id):
        """
        Merge identical vertical layers and apply morphological dilation

        Groups consecutive Z-layers with identical masks to reduce geometry.
        Applies morphological dilation to ensure thin features are printable.

        Returns:
            list of tuples: [(start_z, end_z, dilated_mask), ...]
        """
        kernel = np.ones((3, 3), np.uint8)

        layer_groups = []
        prev_mask = None
        start_z = 0

        for z in range(voxel_matrix.shape[0]):
            curr_mask = voxel_matrix[z] == mat_id

            if not np.any(curr_mask):
                if prev_mask is not None and np.any(prev_mask):
                    layer_groups.append((start_z, z - 1, prev_mask))
                    prev_mask = None
                continue

            dilated_mask = cv2.dilate(curr_mask.astype(np.uint8), kernel, iterations=1).astype(bool)

            if prev_mask is None:
                start_z = z
                prev_mask = dilated_mask.copy()
            elif np.array_equal(dilated_mask, prev_mask):
                pass
            else:
                layer_groups.append((start_z, z - 1, prev_mask))
                start_z = z
                prev_mask = dilated_mask.copy()

        if prev_mask is not None and np.any(prev_mask):
            layer_groups.append((start_z, voxel_matrix.shape[0] - 1, prev_mask))

        return layer_groups


# ========== Factory Method ==========


def get_mesher(mode_name: ModelingMode):
    """
    Return corresponding Mesher instance based on mode name

    Args:
        mode_name: ModelingMode enum value
            - ModelingMode.HIGH_FIDELITY → HighFidelityMesher
            - ModelingMode.PIXEL → VoxelMesher
            - ModelingMode.VECTOR → HighFidelityMesher (vector uses same algorithm)

    Returns:
        BaseMesher instance
    """
    # High-Fidelity mode (replaces Vector and Woodblock)
    if mode_name == ModelingMode.HIGH_FIDELITY:
        print("[MESHER_FACTORY] Selected: HighFidelityMesher (RLE-based with Dilation)")
        return HighFidelityMesher()

    # Vector mode uses same algorithm as High-Fidelity
    if mode_name == ModelingMode.VECTOR:
        print("[MESHER_FACTORY] Selected: HighFidelityMesher (Vector mode)")
        return HighFidelityMesher()

    # Pixel Art mode (legacy voxel)
    if mode_name == ModelingMode.PIXEL:
        print("[MESHER_FACTORY] Selected: VoxelMesher (Blocky)")
        return VoxelMesher()

    # Default fallback to High-Fidelity
    print(f"[MESHER_FACTORY] Unknown mode '{mode_name}', defaulting to HighFidelityMesher")
    return HighFidelityMesher()
