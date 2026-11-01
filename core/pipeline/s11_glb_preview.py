"""
S11 — GLB 3D preview export.
S11 — GLB 3D 预览导出。

从 converter.py 搬入的 GLB 预览函数：
- _create_preview_mesh: 简化预览网格生成
- _merge_low_frequency_colors: 低频颜色合并
- _build_color_extruded_mesh: 按颜色轮廓挤出网格（替换原逐像素体素盒）
- generate_segmented_glb: 分色 GLB 预览
- generate_realtime_glb: 实时 GLB 预览
- generate_empty_bed_glb: 空热床 GLB
"""

from api.structured_logging import get_logger
from functools import lru_cache
import os
import time
from typing import Optional

import cv2
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

from config import PrinterConfig, OUTPUT_DIR, BedManager
from core.naming import generate_preview_filename

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Mesh-kernel feature flag
# ---------------------------------------------------------------------------
#
# ``LUMINA_GLB_KERNEL`` selects the per-color extrusion backend used by the
# S11 segmented-GLB preview. Default is the faster rasterio + manifold3d
# backend, which is the measured preview-performance baseline. Missing native
# deps or runtime v2 failures fall back to the long-standing Shapely v1 path
# (RLE -> shapely_box -> unary_union -> trimesh.creation.extrude_polygon).
# Operators can still force ``v1`` to pin the proven path.
# 该开关用于选择 GLB 分色预览的 mesh kernel。默认走已经作为性能基准的
# rasterio + manifold3d v2；缺依赖或运行失败时回退旧 Shapely v1。需要锁定
# 旧路径时可显式设置 ``v1``。
#
# Allowed values (case-insensitive, leading/trailing whitespace stripped):
#     - ``""`` / unset                         -> attempt v2, fallback to v1 (default)
#     - ``v1`` / ``shapely``                   -> ``shapely_v1``
#     - ``v2`` / ``rasterio_manifold3d``       -> attempt v2, fallback to v1
#     - ``auto``                               -> attempt v2 if importable,
#                                                 silently fallback otherwise
#
# Setting this env var is the *only* supported way to toggle the kernel; we
# keep no Python-level mutable global so process-pool workers inherit the
# choice via env automatically (see api/routers/converter/async_glb.py).
_KERNEL_ENV_VAR = "LUMINA_GLB_KERNEL"
_GLTF_UINT16_COMPONENT_TYPE = 5123
_GLTF_UINT32_COMPONENT_TYPE = 5125
PREVIEW_CANVAS_BOUNDS_NODE_NAME = "preview_canvas_bounds"


def _resolve_glb_pixel_scale(target_width_mm: object, pixel_width: float) -> float:
    """Return mm-per-pixel for GLB previews with a nozzle-width fallback."""

    if pixel_width > 0:
        try:
            width_mm = float(target_width_mm)
        except (TypeError, ValueError):
            width_mm = 0.0
        if np.isfinite(width_mm) and width_mm > 0:
            return width_mm / float(pixel_width)
    return float(PrinterConfig.NOZZLE_WIDTH)


_GLB_SIMPLIFY_THRESHOLD_PIXELS = 500_000
_GLB_TARGET_PIXELS = 300_000


def _resolve_glb_downsample_factor(total_pixels: int) -> int:
    """Return the integer GLB preview downsample factor (1 means none)."""

    if total_pixels <= _GLB_SIMPLIFY_THRESHOLD_PIXELS:
        return 1
    scale_factor = int(np.sqrt(total_pixels / _GLB_TARGET_PIXELS))
    return max(2, min(scale_factor, 16))


def _extract_mask_contours(
    color_match: np.ndarray,
    height: int,
    pixel_scale: float,
) -> list[list[list[float]]]:
    """Return external contours of one colour mask in canvas millimetres.

    Points use a bottom-left canvas origin so they match the
    ``preview_canvas_bounds`` anchor consumed by the frontend.
    """

    mask_u8 = color_match.astype(np.uint8) * 255
    cv_contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour_list: list[list[list[float]]] = []
    for cnt in cv_contours:
        if len(cnt) < 3:
            continue
        pts = cnt.squeeze(1).astype(float)
        contour_list.append(
            [[float(px * pixel_scale), float((height - py) * pixel_scale)] for px, py in pts]
        )
    return contour_list


def extract_color_contours(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    target_width_mm: object,
) -> dict[str, list[list[list[float]]]]:
    """Extract per-colour 2D contours for renderers that skip segmented GLBs.

    Uses the same downsampling, pixel scale, and canvas origin as
    :func:`generate_segmented_glb`, so highlight overlays and keychain loop
    placement stay aligned with the preview canvas anchor.

    为不经过分段 GLB 的预览渲染器提取逐颜色二维轮廓。下采样、像素尺度与
    画布原点均与 :func:`generate_segmented_glb` 一致，保证高亮叠加和挂环
    定位与预览画布锚点对齐。

    Args:
        matched_rgb (np.ndarray): Matched colour raster ``(H, W, 3)``.
            匹配后的颜色栅格。
        mask_solid (np.ndarray): Solid-pixel mask ``(H, W)``. 实体像素掩码。
        target_width_mm (object): Physical canvas width in millimetres.
            画布物理宽度（毫米）。

    Returns:
        dict[str, list[list[list[float]]]]: Hex colour -> contour polygons;
        empty when inputs are missing or mismatched.
        十六进制颜色到轮廓多边形的映射；输入缺失或不匹配时为空。
    """

    if matched_rgb is None or mask_solid is None:
        return {}
    rgb = np.asarray(matched_rgb)
    solid = np.asarray(mask_solid, dtype=bool)
    if rgb.ndim != 3 or rgb.shape[2] < 3 or solid.shape != rgb.shape[:2]:
        return {}
    height, width = solid.shape
    factor = _resolve_glb_downsample_factor(width * height)
    if factor > 1:
        new_w, new_h = width // factor, height // factor
        rgb = cv2.resize(np.ascontiguousarray(rgb[:, :, :3]), (new_w, new_h), interpolation=cv2.INTER_NEAREST)
        solid = cv2.resize(solid.astype(np.uint8), (new_w, new_h), interpolation=cv2.INTER_NEAREST).astype(bool)
        height, width = new_h, new_w
    pixel_scale = _resolve_glb_pixel_scale(target_width_mm, width)

    flat_rgb = rgb.reshape(-1, rgb.shape[-1])[:, :3].astype(np.uint32, copy=False)
    codes = (flat_rgb[:, 0] << 16) | (flat_rgb[:, 1] << 8) | flat_rgb[:, 2]
    codes = codes.reshape(height, width)
    contours_data: dict[str, list[list[list[float]]]] = {}
    for code in np.unique(codes[solid]):
        contour_list = _extract_mask_contours(solid & (codes == code), height, pixel_scale)
        if contour_list:
            contours_data[_rgb_code_to_hex(int(code))] = contour_list
    return contours_data


def _resolve_kernel_choice() -> str:
    """Return the requested kernel id: 'shapely_v1', 'rasterio_manifold3d', or 'auto'.

    Reads the env var fresh on every call so tests can monkeypatch
    ``os.environ`` without restarting the process. The result is intentionally
    *requested* (not yet "available") — actual import-time fallback to
    ``shapely_v1`` is decided by ``_v2_available()`` and the dispatcher in
    ``_build_color_extruded_mesh``.
    返回调用方请求的 kernel 名称；真正的可用性检查由 dispatcher 完成。
    """
    raw = (os.environ.get(_KERNEL_ENV_VAR) or "").strip().lower()
    if raw == "auto":
        return "auto"
    if raw in {"v1", "shapely", "shapely_v1"}:
        return "shapely_v1"
    if raw in {"", "v2", "rasterio_manifold3d", "rasterio+manifold3d"}:
        return "rasterio_manifold3d"
    _log.warning(
        "Unknown LUMINA_GLB_KERNEL value, falling back to shapely_v1",
        extra={
            "event": "glb_kernel_unknown_value",
            "value": raw,
            "error_type": "ValueError",
            "fallback_kernel": "shapely_v1",
        },
    )
    return "shapely_v1"


# Cache of "did v2 import succeed" — a single failed import per process is
# enough; we don't keep retrying on every call. ``None`` means not yet
# probed; ``True`` / ``False`` is the cached outcome.
_V2_IMPORT_OK: Optional[bool] = None
_V2_IMPORT_ERROR: Optional[str] = None
# Process-level latch for the dispatcher's "v2 requested but unavailable"
# WARNING. Without this, ``_build_color_extruded_mesh`` would emit a copy of
# ``glb_kernel_v2_requested_unavailable`` for every per-color call inside
# ``generate_segmented_glb`` (typically 40-60 colours + 1 backing plate per
# preview), which floods the log with identical payloads on Windows arm64
# and other v2-wheel-less environments. ``_v2_available()``'s
# ``glb_kernel_v2_unavailable`` is already process-level via
# ``_V2_IMPORT_OK`` caching; this latch gives the dispatcher's downstream
# WARNING the same one-shot semantics.
# 进程级锁，避免 dispatcher 在每色循环中重复发出同一条 WARNING；
# ``_V2_IMPORT_OK`` 已经把 ``glb_kernel_v2_unavailable`` 控制为进程内只发
# 一次，本锁让 ``glb_kernel_v2_requested_unavailable`` 也只发一次。
_V2_REQUESTED_UNAVAILABLE_LOGGED: bool = False


@lru_cache(maxsize=1)
def _get_v2_mesh_kernel_modules():
    """Return cached optional modules used by the v2 mesh builder."""
    from rasterio.features import shapes as rio_shapes
    import manifold3d as m3d

    return rio_shapes, m3d


def _v2_available(log_warning: bool = True) -> bool:
    """Return True if the v2 stack (``rasterio.features`` + ``manifold3d``) imports.

    Probed once per process and cached. By default, failures are logged at
    WARNING with the import error so operators can see why an environment
    falls back. Pass ``log_warning=False`` to suppress that WARNING — used by
    the ``auto`` dispatch path where a missing v2 wheel is an expected
    "best-effort" outcome, not an operator-visible problem.
    被调用一次后缓存结果；默认在 import 失败时发 WARNING；``log_warning=False``
    用于 ``auto`` 路径，让缺 wheel 时的回退保持静默。
    """
    global _V2_IMPORT_OK, _V2_IMPORT_ERROR
    if _V2_IMPORT_OK is not None:
        return _V2_IMPORT_OK
    try:
        import rasterio.features  # noqa: F401
        import manifold3d  # noqa: F401
    except Exception as exc:  # noqa: BLE001 — import probe, broad on purpose
        _V2_IMPORT_OK = False
        _V2_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        if log_warning:
            _log.warning(
                "GLB kernel v2 unavailable, will fall back to shapely_v1",
                extra={
                    "event": "glb_kernel_v2_unavailable",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
        return False
    _V2_IMPORT_OK = True
    return True

def _iter_valid_polygons(geometry_obj, min_area: float = 1e-4):
    """Yield valid Polygon geometries from Polygon/MultiPolygon-like objects."""
    if geometry_obj is None:
        return

    geom_type = getattr(geometry_obj, "geom_type", "")
    if geom_type == "Polygon":
        polygons = [geometry_obj]
    elif geom_type == "MultiPolygon":
        polygons = list(getattr(geometry_obj, "geoms", []))
    else:
        return

    for poly in polygons:
        if poly is None:
            continue
        if not getattr(poly, "is_valid", False):
            try:
                poly = poly.buffer(0)
            except (ValueError, TypeError, RuntimeError):
                continue
        if getattr(poly, "is_empty", True):
            continue
        area = float(getattr(poly, "area", 0.0) or 0.0)
        if area < min_area:
            continue
        if getattr(poly, "geom_type", "") == "Polygon":
            yield poly
        elif getattr(poly, "geom_type", "") == "MultiPolygon":
            for sub in getattr(poly, "geoms", []):
                if sub is None or getattr(sub, "is_empty", True):
                    continue
                sub_area = float(getattr(sub, "area", 0.0) or 0.0)
                if sub_area >= min_area:
                    yield sub


def _create_preview_mesh(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    total_layers: int,
    backing_color_id: int = 0,
    backing_z_range: tuple = None,
    preview_colors: list = None,
) -> Optional[trimesh.Trimesh]:
    """Create simplified 3D preview mesh for browser display.
    为浏览器显示创建简化的 3D 预览网格。

    Args:
        matched_rgb (np.ndarray): RGB color array of shape (H, W, 3).
        mask_solid (np.ndarray): Boolean mask of solid pixels of shape (H, W).
        total_layers (int): Total number of Z layers.
        backing_color_id (int): Backing material ID (0-7), default is 0 (White).
        backing_z_range (tuple): Tuple of (start_z, end_z) for backing layer, or None.
        preview_colors (list): List of preview colors for materials.

    Returns:
        trimesh.Trimesh: Simplified preview mesh, downsampled for large models.
    """
    height, width = matched_rgb.shape[:2]
    total_pixels = width * height

    SIMPLIFY_THRESHOLD = 500_000
    TARGET_PIXELS = 300_000

    if total_pixels > SIMPLIFY_THRESHOLD:
        scale_factor = int(np.sqrt(total_pixels / TARGET_PIXELS))
        scale_factor = max(2, min(scale_factor, 16))

        _log.debug(f"Downsampling by {scale_factor}x ({total_pixels:,} -> ~{TARGET_PIXELS:,} pixels)")

        new_height = height // scale_factor
        new_width = width // scale_factor

        matched_rgb = cv2.resize(matched_rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)
        mask_solid = cv2.resize(
            mask_solid.astype(np.uint8), (new_width, new_height), interpolation=cv2.INTER_NEAREST
        ).astype(bool)

        height, width = new_height, new_width
        shrink = 0.0
    else:
        shrink = 0.0

    # --- numpy vectorized mesh build ---
    _CUBE_FACES = np.array(
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
    )  # (12, 3)

    def _boxes_np(px, py, z0_scalar, z1_scalar, colors_rgba):
        """Build voxel boxes for N pixels, all at same z range."""
        n = len(px)
        if n == 0:
            return np.empty((0, 3)), np.empty((0, 3), dtype=np.int64), np.empty((0, 4), dtype=np.uint8)
        x0 = px + shrink
        x1 = px + 1 - shrink
        y0 = py + shrink
        y1 = py + 1 - shrink
        z0 = np.full(n, z0_scalar, dtype=np.float64)
        z1 = np.full(n, z1_scalar, dtype=np.float64)
        # verts: (n,8,3)
        verts = np.stack(
            [
                np.column_stack([x0, y0, z0]),
                np.column_stack([x1, y0, z0]),
                np.column_stack([x1, y1, z0]),
                np.column_stack([x0, y1, z0]),
                np.column_stack([x0, y0, z1]),
                np.column_stack([x1, y0, z1]),
                np.column_stack([x1, y1, z1]),
                np.column_stack([x0, y1, z1]),
            ],
            axis=1,
        )  # (n,8,3)
        all_verts = verts.reshape(-1, 3)
        offsets = (np.arange(n, dtype=np.int64) * 8)[:, None, None]
        all_faces = (_CUBE_FACES[None] + offsets).reshape(-1, 3)
        if colors_rgba.ndim == 1:
            all_colors = np.tile(colors_rgba, (n * 12, 1))
        else:
            all_colors = np.repeat(colors_rgba, 12, axis=0)
        return all_verts, all_faces, all_colors

    ys_all, xs_all = np.where(mask_solid)
    world_ys = (height - 1 - ys_all).astype(np.float64)
    xs_f = xs_all.astype(np.float64)

    all_v_list, all_f_list, all_c_list = [], [], []
    face_offset = 0

    if backing_z_range is not None and preview_colors is not None:
        backing_start, backing_end = backing_z_range
        backing_color_rgba = np.array(preview_colors[backing_color_id], dtype=np.uint8)[:4]
        pixel_colors = np.column_stack(
            [matched_rgb[ys_all, xs_all].astype(np.uint8), np.full(len(ys_all), 255, dtype=np.uint8)]
        )  # (N,4)

        # backing box
        v, f, c = _boxes_np(xs_f, world_ys, float(backing_start), float(backing_end + 1), backing_color_rgba)
        if len(v):
            all_v_list.append(v)
            all_f_list.append(f + face_offset)
            all_c_list.append(c)
            face_offset += len(v)

        # bottom box (z 0 -> backing_start)
        if backing_start > 0:
            v, f, c = _boxes_np(xs_f, world_ys, 0.0, float(backing_start), pixel_colors)
            if len(v):
                all_v_list.append(v)
                all_f_list.append(f + face_offset)
                all_c_list.append(c)
                face_offset += len(v)

        # top box (backing_end+1 -> total_layers)
        if backing_end + 1 < total_layers:
            v, f, c = _boxes_np(xs_f, world_ys, float(backing_end + 1), float(total_layers), pixel_colors)
            if len(v):
                all_v_list.append(v)
                all_f_list.append(f + face_offset)
                all_c_list.append(c)
                face_offset += len(v)
    else:
        pixel_colors = np.column_stack(
            [matched_rgb[ys_all, xs_all].astype(np.uint8), np.full(len(ys_all), 255, dtype=np.uint8)]
        )
        v, f, c = _boxes_np(xs_f, world_ys, 0.0, float(total_layers), pixel_colors)
        if len(v):
            all_v_list.append(v)
            all_f_list.append(f)
            all_c_list.append(c)

    if not all_v_list:
        return None

    vertices_np = np.concatenate(all_v_list, axis=0)
    faces_np = np.concatenate(all_f_list, axis=0)
    face_colors_np = np.concatenate(all_c_list, axis=0)

    mesh = trimesh.Trimesh(vertices=vertices_np, faces=faces_np, process=False)
    mesh.visual.face_colors = face_colors_np
    _log.debug(f"Generated: {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces")
    return mesh


def _merge_low_frequency_colors(
    unique_colors: np.ndarray,
    pixel_counts: np.ndarray,
    max_meshes: int,
) -> np.ndarray:
    """Merge low-frequency colors into their nearest high-frequency neighbors.
    将低频颜色合并到最近的高频邻居。

    Args:
        unique_colors (np.ndarray): (N, 3) uint8 array of unique RGB colors.
        pixel_counts (np.ndarray): (N,) int array of pixel counts per color.
        max_meshes (int): Maximum number of colors to keep.

    Returns:
        np.ndarray: (N, 3) uint8 array where tail colors are replaced by nearest kept color.
    """
    n = len(unique_colors)
    if n <= max_meshes:
        return unique_colors.copy()

    order = np.argsort(-pixel_counts)
    keep_indices = order[:max_meshes]
    tail_indices = order[max_meshes:]

    kept_colors = unique_colors[keep_indices].astype(np.float64)
    merged = unique_colors.copy()

    tail_rgb = unique_colors[tail_indices].astype(np.float64)
    # Vectorized nearest-neighbor via broadcasting: (T, 1, 3) - (1, K, 3)
    diff = tail_rgb[:, None, :] - kept_colors[None, :, :]
    dist_sq = np.sum(diff**2, axis=2)
    nearest = np.argmin(dist_sq, axis=1)

    merged[tail_indices] = unique_colors[keep_indices[nearest]]
    return merged


def _build_color_extruded_mesh_shapely_v1(
    mask: np.ndarray,
    height: int,
    total_layers: int,
    rgba: np.ndarray,
) -> Optional[trimesh.Trimesh]:
    """Build an extruded Trimesh for pixels indicated by *mask* (Shapely v1).
    为 mask 指示的像素构建挤出式 Trimesh（Shapely 旧实现）。

    Replaces the per-pixel voxel-box representation. For a connected pixel
    region of N pixels the old approach emitted 8·N vertices / 12·N triangles
    regardless of shape complexity; this approach computes the region's true
    pixel-corner polygonal boundary (including any interior holes) and
    extrudes it along Z. For the preview the two are mathematically
    equivalent (identical footprint, identical height) but the extrusion
    typically uses 20–100× fewer vertices and faces.
    将逐像素体素盒替换为挤出方案：对 N 像素的连通区域，直接求出它在像素
    栅格上的外轮廓多边形（含内部孔洞），沿 Z 方向挤出一次。预览视角下两者
    完全等效（相同占地与高度），但挤出通常使用 20–100 倍更少的顶点和面。

    Implementation note / 实现说明:
        We build the mask's pixel-corner polygon by run-length-encoding each
        row into unit-tall rectangles and unioning them with Shapely's
        ``unary_union``. RLE keeps the object count to O(N_runs) which for
        typical color-layer masks is 10–100× smaller than N_pixels, so the
        union stays fast even for ~300k-pixel previews. We deliberately do
        NOT use ``cv2.findContours`` here: it traces pixel CENTERS, which
        collapse 1-pixel-thin strips into degenerate zero-area lines.
        通过逐行 RLE + Shapely ``unary_union`` 构造像素角点级精度的多边形。
        RLE 把对象数量控制在 O(N_runs)，通常比 N_pixels 少 10–100 倍，
        因此即便 ~30 万像素的预览也能快速求并。这里刻意不使用
        ``cv2.findContours``，因为它沿像素中心追踪，会把 1 像素窄条退化
        成零面积直线。

    Args:
        mask (np.ndarray): (H, W) bool array of pixels belonging to this color.
        height (int): Image height used for Y-axis flip so image-up maps to world-up.
        total_layers (int): Number of Z layers for the extrusion height.
        rgba (np.ndarray): (4,) uint8 RGBA color for face coloring.

    Returns:
        trimesh.Trimesh or None: Generated mesh, or None if mask has no True pixels.
    """
    from shapely.geometry import box as shapely_box
    from shapely.ops import unary_union

    if not np.any(mask):
        return None

    mask_arr = np.asarray(mask, dtype=bool)
    if mask_arr.ndim != 2:
        return None

    h, _w = mask_arr.shape
    # Vectorised row-wise RLE: pad each row with a False sentinel on both sides
    # so that np.diff marks every run's start (+1) and end (-1) symmetrically.
    # 逐行向量化 RLE：两端补 False 哨兵，np.diff 即可对称标记每段起止。
    padded = np.pad(mask_arr.astype(np.int8), ((0, 0), (1, 1)), mode="constant")
    diff = np.diff(padded, axis=1)
    starts_per_row = [np.flatnonzero(diff[y] == 1) for y in range(h)]
    ends_per_row = [np.flatnonzero(diff[y] == -1) for y in range(h)]

    boxes: list = []
    for y in range(h):
        starts = starts_per_row[y]
        ends = ends_per_row[y]
        if starts.size == 0:
            continue
        world_y0 = float(height - y - 1)
        world_y1 = float(height - y)
        for s, e in zip(starts, ends):
            boxes.append(shapely_box(float(s), world_y0, float(e), world_y1))

    if not boxes:
        return None

    try:
        region = unary_union(boxes)
    except (ValueError, TypeError, RuntimeError) as exc:
        _log.warning(f"unary_union failed: {exc}")
        return None

    if region.is_empty:
        return None

    valid_polygons = list(_iter_valid_polygons(region, min_area=1e-4))
    if not valid_polygons:
        return None

    extrude_h = float(total_layers)
    meshes: list[trimesh.Trimesh] = []
    extrude_fail = 0
    for poly in valid_polygons:
        try:
            m = trimesh.creation.extrude_polygon(poly, height=extrude_h)
            meshes.append(m)
        except (ValueError, TypeError, RuntimeError, AttributeError):
            extrude_fail += 1
            continue

    if not meshes:
        _log.warning(
            f"Color mesh extrusion failed for all components: "
            f"components={len(valid_polygons)}, extrude_fail={extrude_fail}"
        )
        return None

    result = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    result.visual.face_colors = np.tile(rgba, (len(result.faces), 1))
    return result


def _build_color_extruded_mesh_v2(
    mask: np.ndarray,
    height: int,
    total_layers: int,
    rgba: np.ndarray,
    *,
    assign_face_colors: bool = True,
    component_compose_chunk_size: int | None = None,
) -> Optional[trimesh.Trimesh]:
    """Build an extruded Trimesh using rasterio polygonize + manifold3d extrude.
    使用 rasterio polygonize + manifold3d 挤出构建 Trimesh（v2 路径）。

    Geometric semantics are identical to ``_build_color_extruded_mesh_shapely_v1``:
    pixel-corner polygons (NOT pixel-center, unlike ``cv2.findContours``),
    interior holes preserved, 1-px strips and isolated pixels kept. The
    measured speedup vs v1 on representative reference-image masks is in
    ``progress/glb-preview-mesh-library-spike.md``. The dispatcher now uses
    this v2 path by default and falls back to v1 on import/runtime failure;
    set ``LUMINA_GLB_KERNEL=v1`` only when the older path must be pinned.

    On any failure (import error, geometry error, manifold construction
    error) this helper returns ``None``; the dispatcher in
    ``_build_color_extruded_mesh`` then transparently falls back to v1.
    几何语义与 v1 完全一致；任何失败都返回 None，由调度器回退到 v1。

    Precondition:
        ``mask`` MUST be a strict 0/1 boolean grid (``dtype=bool``). With
        this precondition, ``rasterio.features.shapes(connectivity=4)``
        cannot produce sub-pixel degenerate rings — the smallest possible
        output is a 1×1-pixel square at pixel-corner coordinates — so this
        helper does NOT need the ``min_area=1e-4`` filter that
        ``_build_color_extruded_mesh_shapely_v1`` runs via
        ``_iter_valid_polygons``. If a future caller relaxes this and
        passes a non-bool raster (uint8 grayscale, nodata-valued float,
        etc.), manifold3d may receive a degenerate ring and raise a
        ``RuntimeError`` at ``CrossSection.extrude``; that path is already
        guarded by the per-component atomicity contract (the whole color
        aborts to None, dispatcher falls back to v1), so behaviour stays
        safe — only correctness of the v2 fast path would silently
        degrade.
        前提：``mask`` 必须是严格 0/1 bool 数组。该前提下 rasterio 的
        connectivity=4 polygonize 不会输出退化环，因此本函数不需要
        v1 的 ``min_area`` 过滤。若未来允许非 bool 输入，由 per-component
        atomicity 兜底（整色 abort + dispatcher fallback v1），不会爆炸，
        但 v2 快路径的覆盖率会下降。

    Args:
        mask (np.ndarray): (H, W) bool array of pixels belonging to this color.
        height (int): Image height used for Y-axis flip so image-up maps to world-up.
        total_layers (int): Number of Z layers for the extrusion height.
        rgba (np.ndarray): (4,) uint8 RGBA color for face coloring.
        assign_face_colors (bool): Whether to allocate per-face preview colors.
        component_compose_chunk_size (int | None): Optional number of
            connected components to compose before each native extrusion.

    Returns:
        trimesh.Trimesh or None: Generated mesh, or None on empty mask / failure.
    """
    if not np.any(mask):
        return None

    mask_arr = np.asarray(mask, dtype=bool)
    if mask_arr.ndim != 2:
        return None

    try:
        rio_shapes, m3d = _get_v2_mesh_kernel_modules()
    except Exception as exc:  # noqa: BLE001 — import-level fallback signal
        _log.warning(
            "v2 kernel import failed",
            extra={
                "event": "glb_kernel_v2_import_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None

    h = mask_arr.shape[0]
    # rasterio.features.shapes returns each connected component's outer ring
    # plus its interior hole rings, already grouped per component. We don't
    # need an O(N²) hole-pairing loop because the grouping comes for free.
    # rasterio 已按 component 聚合外环 + 孔洞环，无需手写 O(N²) 配对。
    components: list[list[np.ndarray]] = []
    try:
        for geom, val in rio_shapes(
            mask_arr.astype(np.uint8), mask=mask_arr, connectivity=4
        ):
            if val != 1:
                continue
            rings = geom.get("coordinates") or []
            if not rings:
                continue
            contours: list[np.ndarray] = []
            for ring in rings:
                arr = np.asarray(ring, dtype=np.float64)
                if len(arr) >= 2 and np.allclose(arr[0], arr[-1]):
                    arr = arr[:-1]
                if len(arr) < 3:
                    continue
                # Flip Y so world-up == image-up, matching v1's convention.
                arr[:, 1] = float(h) - arr[:, 1]
                contours.append(arr)
            if contours:
                components.append(contours)
    except Exception as exc:  # noqa: BLE001 — rasterio runtime failure
        _log.warning(
            "rasterio.features.shapes failed",
            extra={
                "event": "glb_kernel_v2_polygonize_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None

    if not components:
        return None

    extrude_h = float(total_layers)
    mesh_data = None
    try:
        chunk_size = int(component_compose_chunk_size or 0)
        if len(components) == 1:
            combined_cs = m3d.CrossSection(components[0], m3d.FillRule.EvenOdd)
            combined = combined_cs.extrude(extrude_h)
        elif chunk_size > 1 and chunk_size < len(components):
            manifolds = []
            for start in range(0, len(components), chunk_size):
                group = components[start : start + chunk_size]
                if len(group) == 1:
                    cs = m3d.CrossSection(group[0], m3d.FillRule.EvenOdd)
                else:
                    cs = m3d.CrossSection.compose(
                        [
                            m3d.CrossSection(contours, m3d.FillRule.EvenOdd)
                            for contours in group
                        ]
                    )
                man = cs.extrude(extrude_h)
                if man.is_empty():
                    raise RuntimeError("CrossSection chunk extrude returned empty")
                manifolds.append(man)
            combined = m3d.Manifold.compose(manifolds)
        else:
            combined_cs = m3d.CrossSection.compose(
                [
                    m3d.CrossSection(contours, m3d.FillRule.EvenOdd)
                    for contours in components
                ]
            )
            combined = combined_cs.extrude(extrude_h)
        if not combined.is_empty():
            mesh_data = combined.to_mesh()
    except Exception:
        mesh_data = None

    if mesh_data is None:
        manifolds = []
        for component_idx, contours in enumerate(components):
            try:
                cs = m3d.CrossSection(contours, m3d.FillRule.EvenOdd)
                man = cs.extrude(extrude_h)
            except Exception as exc:  # noqa: BLE001 — per-component boundary guard
                # Atomicity contract: a single bad component is enough to
                # abort the whole color. Returning None here lets the
                # dispatcher transparently fall back to shapely_v1 for the
                # entire mask, which guarantees volume / XY-coverage parity
                # with v1 (no partial-color geometry leaks). v1 is fully
                # capable of handling the same input — manifold3d C-extension
                # failures are the exception, not the rule, so the cost of
                # rebuilding the whole color in v1 is acceptable.
                # 任一 component 失败即丢弃整色：不允许 partial 输出，
                # 保证 v2 与 v1 在 volume / XY 覆盖上严格一致；dispatcher
                # 看到 None 后会用 v1 重建该色。
                _log.warning(
                    "v2 kernel per-component extrude failed, aborting color",
                    extra={
                        "event": "glb_kernel_v2_no_manifolds",
                        "components": len(components),
                        "failed_component_index": int(component_idx),
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:200],
                        "fallback_kernel": "shapely_v1",
                    },
                )
                return None
            if man.is_empty():
                # An empty manifold from a non-empty contour list is a
                # geometry pathology (e.g. degenerate self-intersection that
                # manifold3d collapses to nothing). Treat it the same as an
                # exception: abort the color, let v1 rebuild.
                # manifold 退化成空在拓扑上等价于失败，按同一策略丢色 fallback。
                _log.warning(
                    "v2 kernel produced empty manifold for non-empty component",
                    extra={
                        "event": "glb_kernel_v2_no_manifolds",
                        "components": len(components),
                        "failed_component_index": int(component_idx),
                        "error_type": "EmptyManifold",
                        "error_message": "CrossSection.extrude returned an empty Manifold",
                        "fallback_kernel": "shapely_v1",
                    },
                )
                return None
            manifolds.append(man)

        if not manifolds:
            # Only reachable if ``components`` was already empty above; defensive.
            return None

        try:
            combined = m3d.Manifold.compose(manifolds)
            mesh_data = combined.to_mesh()
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "v2 kernel manifold compose/to_mesh failed",
                extra={
                    "event": "glb_kernel_v2_compose_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            return None

    verts = np.asarray(mesh_data.vert_properties, dtype=np.float64)
    tris = np.asarray(mesh_data.tri_verts, dtype=np.int64)
    if verts.size == 0 or tris.size == 0:
        return None
    if verts.shape[1] > 3:
        verts = verts[:, :3]

    result = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
    result = _sort_mesh_vertices_spatially_for_gzip(result)
    if assign_face_colors:
        result.visual.face_colors = np.tile(rgba, (len(result.faces), 1))
    return result


def _sort_mesh_vertices_spatially_for_gzip(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(vertices) == 0 or len(faces) == 0:
        return mesh

    order = np.lexsort((vertices[:, 2], vertices[:, 1], vertices[:, 0]))
    if np.array_equal(order, np.arange(len(vertices))):
        return mesh

    inverse = np.empty(len(order), dtype=np.int64)
    inverse[order] = np.arange(len(order), dtype=np.int64)
    return trimesh.Trimesh(
        vertices=vertices[order].copy(),
        faces=inverse[faces].copy(),
        process=False,
    )


def _ordered_key_at(mapping: dict, index: object) -> object | None:
    try:
        return list(mapping.keys())[int(index)]
    except (IndexError, TypeError, ValueError):
        return None


def _sort_triangle_index_buffers_for_gzip(buffer_items: dict, tree: dict) -> None:
    accessors = tree.get("accessors")
    if not isinstance(accessors, dict):
        return

    sorted_views: set[tuple[object, int, int, str]] = set()
    for mesh in tree.get("meshes", []) or []:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives", []) or []:
            if not isinstance(primitive, dict):
                continue
            if int(primitive.get("mode", 4) or 4) != 4:
                continue
            accessor_index = primitive.get("indices")
            if accessor_index is None:
                continue
            accessor_key = _ordered_key_at(accessors, accessor_index)
            if accessor_key is None:
                continue
            accessor = accessors.get(accessor_key)
            if not isinstance(accessor, dict) or accessor.get("type") != "SCALAR":
                continue
            component_type = accessor.get("componentType")
            if component_type == _GLTF_UINT16_COMPONENT_TYPE:
                dtype = "<u2"
            elif component_type == _GLTF_UINT32_COMPONENT_TYPE:
                dtype = "<u4"
            else:
                continue
            try:
                count = int(accessor.get("count", 0) or 0)
                buffer_view = int(accessor["bufferView"])
                byte_offset = int(accessor.get("byteOffset", 0) or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if count <= 0 or count % 3 != 0:
                continue
            buffer_key = _ordered_key_at(buffer_items, buffer_view)
            if buffer_key is None:
                continue
            raw = buffer_items.get(buffer_key)
            if not isinstance(raw, (bytes, bytearray)):
                continue
            view_key = (buffer_key, byte_offset, count, dtype)
            if view_key in sorted_views:
                continue
            itemsize = np.dtype(dtype).itemsize
            byte_length = count * itemsize
            if byte_offset < 0 or byte_offset + byte_length > len(raw):
                continue
            try:
                indices = np.frombuffer(
                    raw[byte_offset : byte_offset + byte_length],
                    dtype=dtype,
                ).reshape((-1, 3))
            except ValueError:
                continue
            if len(indices) <= 1:
                continue
            order = np.lexsort((indices[:, 1], indices[:, 0]))
            sorted_indices = indices[order].reshape(-1).astype(dtype, copy=False)
            updated = bytearray(raw)
            updated[byte_offset : byte_offset + byte_length] = sorted_indices.tobytes()
            buffer_items[buffer_key] = bytes(updated)
            sorted_views.add(view_key)


def _build_color_extruded_mesh(
    mask: np.ndarray,
    height: int,
    total_layers: int,
    rgba: np.ndarray,
    *,
    assign_face_colors: bool = True,
) -> Optional[trimesh.Trimesh]:
    """Dispatch to the active mesh kernel; transparently fall back to v1.
    根据 ``LUMINA_GLB_KERNEL`` 选择 kernel；失败自动回退到 v1。

    Public API: callers in ``generate_segmented_glb`` and
    ``_build_backing_plate_mesh`` keep using this name. Behaviour:
        - ``LUMINA_GLB_KERNEL`` unset / ``v2``                -> v2, fallback to v1
                                                                 with warning (default)
        - ``LUMINA_GLB_KERNEL=v1`` / ``shapely``              -> v1
        - ``LUMINA_GLB_KERNEL=v2``                            -> v2, fallback to v1
        - ``LUMINA_GLB_KERNEL=auto``                          -> v2 if importable,
                                                                 else v1, no warning
    """
    requested = _resolve_kernel_choice()
    use_v2 = False
    if requested == "rasterio_manifold3d":
        # Explicit v2 request: surface a WARNING when v2 is unavailable so
        # operators see why the env value got ignored. Latch it to once-per-
        # process so a single multi-colour preview does not produce one
        # copy of this WARNING per colour (was reviewer feedback on
        # PR #210; see _V2_REQUESTED_UNAVAILABLE_LOGGED).
        # 显式请求 v2 时，缺 wheel 必须发 WARNING，让运维看到 env 值被忽略
        # 的原因；用进程级锁压制风暴，单次预览不会重复刷屏。
        global _V2_REQUESTED_UNAVAILABLE_LOGGED
        use_v2 = _v2_available(log_warning=True)
        if not use_v2 and not _V2_REQUESTED_UNAVAILABLE_LOGGED:
            _log.warning(
                "LUMINA_GLB_KERNEL=v2 requested but unavailable, using shapely_v1",
                extra={
                    "event": "glb_kernel_v2_requested_unavailable",
                    "import_error": _V2_IMPORT_ERROR,
                    "error_type": "ImportError",
                    "fallback_kernel": "shapely_v1",
                },
            )
            _V2_REQUESTED_UNAVAILABLE_LOGGED = True
    elif requested == "auto":
        # Auto: best-effort v2, silent fallback on import failure.
        # auto 模式：能用就用 v2，缺 wheel 时静默降级，不打扰运维。
        use_v2 = _v2_available(log_warning=False)

    if use_v2:
        mesh = _build_color_extruded_mesh_v2(
            mask=mask,
            height=height,
            total_layers=total_layers,
            rgba=rgba,
            assign_face_colors=assign_face_colors,
        )
        if mesh is not None:
            return mesh
        # v2 explicitly returned None on a non-empty mask: fall back so we
        # never lose a per-color mesh on a transient v2 failure.
        # v2 在非空 mask 上返回 None 视为运行时失败，回退到 v1，避免预览丢色。
        if np.any(mask):
            _log.warning(
                "GLB kernel v2 returned None on non-empty mask, falling back to shapely_v1",
                extra={
                    "event": "glb_kernel_v2_runtime_fallback",
                    # Actionable fields so on-call can correlate with mask
                    # size when grepping; v2 helper itself has already
                    # logged the precise failure cause (one of
                    # glb_kernel_v2_polygonize_failed / _no_manifolds /
                    # _compose_failed / _import_failed) on the same call.
                    # 配合 v2 helper 已发的具体失败 event 一起读，能定位到
                    # 是哪一步触发了回退。
                    "mask_pixels": int(np.count_nonzero(mask)),
                    "mask_shape": list(mask.shape),
                    "fallback_kernel": "shapely_v1",
                },
            )
            return _build_color_extruded_mesh_shapely_v1(
                mask=mask,
                height=height,
                total_layers=total_layers,
                rgba=rgba,
            )
        return None

    return _build_color_extruded_mesh_shapely_v1(
        mask=mask, height=height, total_layers=total_layers, rgba=rgba
    )


def _assign_mesh_material_rgba(
    mesh: trimesh.Trimesh,
    rgba: np.ndarray,
    *,
    material_name: str,
) -> None:
    mesh.visual = trimesh.visual.TextureVisuals(
        material=PBRMaterial(
            name=material_name,
            baseColorFactor=[int(value) for value in rgba],
        )
    )


def _remove_mesh_horizontal_caps(
    mesh: trimesh.Trimesh,
    *,
    remove_bottom: bool,
) -> trimesh.Trimesh | None:
    """Drop the hidden bottom cap while retaining relief-visible surfaces."""

    if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
        return None
    face_z = np.asarray(mesh.vertices)[np.asarray(mesh.faces), 2]
    min_z = float(np.min(face_z))
    keep = np.ones(len(mesh.faces), dtype=bool)
    if remove_bottom:
        keep &= ~np.all(np.isclose(face_z, min_z, atol=1e-9), axis=1)
    if not np.any(keep):
        return None
    mesh.update_faces(keep)
    mesh.remove_unreferenced_vertices()
    return mesh


def _concatenate_layered_mesh_parts(
    parts: list[trimesh.Trimesh],
    *,
    metadata: dict,
) -> trimesh.Trimesh | None:
    """Concatenate independently coloured parts without merging vertex ranges."""

    if not parts:
        return None
    combined = trimesh.util.concatenate(parts)
    combined.metadata.update(metadata)
    return combined


def _rgb_code_to_hex(code: int) -> str:
    return f"{(code >> 16) & 0xFF:02x}{(code >> 8) & 0xFF:02x}{code & 0xFF:02x}"


def _rgb_codes(rgb: np.ndarray) -> np.ndarray:
    values = np.asarray(rgb, dtype=np.uint32)
    return (values[..., 0] << 16) | (values[..., 1] << 8) | values[..., 2]


def _resolve_height_identity_rgb(
    cache: dict,
    matched_rgb: np.ndarray,
) -> np.ndarray:
    """Return the stable per-pixel relief identity, falling back safely."""

    candidate = cache.get("height_identity_rgb")
    if candidate is None:
        candidate = cache.get("original_matched_rgb")
    try:
        identity = np.asarray(candidate, dtype=np.uint8)
    except (TypeError, ValueError):
        identity = np.asarray(matched_rgb, dtype=np.uint8)
    if identity.shape != matched_rgb.shape:
        error_message = (
            "height_identity_rgb shape does not match matched_rgb; "
            "falling back to current display colours"
        )
        _log.warning(
            "Height identity shape mismatch; using current matched RGB",
            extra={
                "event": "segmented_glb_height_identity_shape_mismatch",
                "error_type": "ValueError",
                "error_message": error_message,
                "height_identity_shape": list(identity.shape),
                "matched_rgb_shape": list(matched_rgb.shape),
            },
        )
        identity = np.asarray(matched_rgb, dtype=np.uint8)
    return identity


def _coerce_preview_rgba(raw: object) -> np.ndarray | None:
    """Return an RGBA uint8 row from preview colour metadata."""

    try:
        arr = np.asarray(raw, dtype=np.uint8).reshape(-1)
    except (TypeError, ValueError):
        return None
    if arr.shape[0] < 3:
        return None
    if arr.shape[0] >= 4:
        return arr[:4].copy()
    return np.array([int(arr[0]), int(arr[1]), int(arr[2]), 255], dtype=np.uint8)


def _preview_rgba_for_material(cache: dict, material_id: int) -> np.ndarray:
    preview_colors = cache.get("preview_colors")
    slot_names = cache.get("slot_names")
    candidates: list[object] = []
    if isinstance(preview_colors, dict):
        candidates.append(preview_colors.get(material_id))
        candidates.append(preview_colors.get(str(material_id)))
        if isinstance(slot_names, (list, tuple)) and material_id < len(slot_names):
            candidates.append(preview_colors.get(slot_names[material_id]))

    color_conf = cache.get("color_conf") or {}
    if isinstance(color_conf, dict):
        conf_preview = color_conf.get("preview")
        conf_slots = color_conf.get("slots")
        if isinstance(conf_preview, dict):
            candidates.append(conf_preview.get(material_id))
            candidates.append(conf_preview.get(str(material_id)))
            if isinstance(conf_slots, (list, tuple)) and material_id < len(conf_slots):
                candidates.append(conf_preview.get(conf_slots[material_id]))

    for candidate in candidates:
        rgba = _coerce_preview_rgba(candidate)
        if rgba is not None:
            return rgba
    return np.array([128, 128, 128, 255], dtype=np.uint8)


def _material_matrix_for_segmented_glb(
    cache: dict,
    mask_solid: np.ndarray,
) -> np.ndarray | None:
    """Return material_matrix only for material-archive GLB previews."""

    if str(cache.get("material_source") or "lut") != "material_archive":
        return None
    material_matrix = cache.get("material_matrix")
    if material_matrix is None:
        return None
    try:
        arr = np.asarray(material_matrix)
    except (TypeError, ValueError):
        return None
    if arr.ndim != 3 or arr.shape[:2] != mask_solid.shape or arr.shape[2] <= 0:
        _log.warning(
            "Material-archive preview cache has invalid material_matrix shape",
            extra={
                "event": "segmented_glb_material_matrix_invalid",
                "material_matrix_shape": list(getattr(arr, "shape", ())),
                "mask_solid_shape": list(mask_solid.shape),
                "error_type": "ValueError",
            },
        )
        return None
    return arr


def _resize_material_matrix_nearest(
    material_matrix: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    layers = [
        cv2.resize(
            material_matrix[:, :, layer_idx],
            (width, height),
            interpolation=cv2.INTER_NEAREST,
        )
        for layer_idx in range(int(material_matrix.shape[2]))
    ]
    return np.stack(layers, axis=2).astype(material_matrix.dtype, copy=False)


def _resolve_material_layer_height_mm(cache: dict) -> float:
    try:
        value = float(cache.get("layer_height_mm"))
    except (TypeError, ValueError):
        value = 0.0
    if np.isfinite(value) and value > 0:
        return value
    return float(PrinterConfig.LAYER_HEIGHT)


def _add_material_matrix_color_meshes(
    *,
    scene: trimesh.Scene,
    cache: dict,
    material_matrix: np.ndarray,
    mask_solid: np.ndarray,
    height: int,
    pixel_scale: float,
) -> int:
    """Add one vertex-coloured physical mesh per native optical layer.

    Display colours are preserved as compact vertex ranges in GLTF extras
    while geometry count remains ``O(layer_count)`` instead of
    ``O(material_count * layer_count)``. Layer 0 is represented exclusively
    by the solver-coloured appearance shell. Omitting a second layer-0 shell
    prevents coplanar side walls and z-fighting in the normal viewer.
    """

    layer_count = int(material_matrix.shape[2])
    layer_height_mm = _resolve_material_layer_height_mm(cache)
    scale_transform = np.eye(4)
    scale_transform[0, 0] = pixel_scale
    scale_transform[1, 1] = pixel_scale
    scale_transform[2, 2] = layer_height_mm

    added = 0
    for layer_idx in range(1, layer_count):
        layer = material_matrix[:, :, layer_idx]
        valid_ids = np.unique(layer[np.logical_and(mask_solid, layer >= 0)])
        z_offset_mm = float(layer_count - layer_idx - 1) * layer_height_mm
        parts: list[trimesh.Trimesh] = []
        material_segments: list[dict[str, int | str]] = []
        vertex_cursor = 0
        for raw_material_id in valid_ids:
            material_id = int(raw_material_id)
            color_match = np.logical_and(mask_solid, layer == material_id)
            if not np.any(color_match):
                continue
            rgba = _preview_rgba_for_material(cache, material_id)
            mesh = _build_color_extruded_mesh(
                color_match,
                height,
                1,
                rgba,
                assign_face_colors=False,
            )
            if mesh is None:
                continue
            mesh.apply_transform(scale_transform)
            min_z = float(mesh.vertices[:, 2].min())
            if min_z != 0.0:
                mesh.vertices[:, 2] -= min_z
            if z_offset_mm != 0.0:
                mesh.vertices[:, 2] += z_offset_mm
            material_segments.append(
                {
                    "display_hex": (
                        f"{int(rgba[0]):02x}{int(rgba[1]):02x}"
                        f"{int(rgba[2]):02x}"
                    ),
                    "vertex_start": vertex_cursor,
                    "vertex_count": int(len(mesh.vertices)),
                }
            )
            vertex_cursor += int(len(mesh.vertices))
            parts.append(mesh)

        combined = _concatenate_layered_mesh_parts(
            parts,
            metadata={
                "material_segments": material_segments,
            },
        )
        if combined is None:
            continue
        _assign_mesh_material_rgba(
            combined,
            np.array([255, 255, 255, 255], dtype=np.uint8),
            material_name=f"layered_physical_{layer_idx:03d}_palette",
        )
        node_name = f"color_layered_physical_l{layer_idx:03d}"
        scene.add_geometry(
            combined,
            node_name=node_name,
            geom_name=node_name,
        )
        added += 1

    return added


def _build_backing_plate_mesh(
    mask_solid: np.ndarray,
    height: int,
    pixel_scale: float,
    rgba: np.ndarray,
) -> Optional[trimesh.Trimesh]:
    """用 RLE/Shapely 像素轮廓拉伸构建底板，替代逐像素体素方案。
    顶点数从 ~3M 降至 <5k，节省约 2.5s。
    """
    mesh = _build_color_extruded_mesh(
        mask=mask_solid,
        height=height,
        total_layers=1,
        rgba=rgba,
    )
    if mesh is None:
        _log.warning("Backing plate skipped: mask extrusion returned no mesh")
        return None

    scale_transform = np.eye(4)
    scale_transform[0, 0] = pixel_scale
    scale_transform[1, 1] = pixel_scale
    scale_transform[2, 2] = PrinterConfig.LAYER_HEIGHT
    mesh.apply_transform(scale_transform)
    return mesh


def _build_preview_canvas_bounds_mesh(
    width: float,
    height: float,
    pixel_scale: float,
) -> Optional[trimesh.Trimesh]:
    """Build an invisible full-canvas bounds anchor for frontend overlay placement.
    构建不可见的完整画布 bounds 锚点，用于前端叠线对齐。
    """
    if width <= 0 or height <= 0 or pixel_scale <= 0:
        return None

    canvas_w = float(width * pixel_scale)
    canvas_h = float(height * pixel_scale)
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [canvas_w, 0.0, 0.0],
            [canvas_w, canvas_h, 0.0],
            [0.0, canvas_h, 0.0],
        ],
        dtype=np.float64,
    )
    faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.visual.face_colors = np.tile(
        np.array([0, 0, 0, 0], dtype=np.uint8),
        (len(mesh.faces), 1),
    )
    return mesh


def generate_empty_bed_glb(
    bed_w: int = None,
    bed_h: int = None,
    is_dark: bool = False,
) -> Optional[str]:
    """Generate a GLB file containing only the print bed (no model).
    生成仅包含打印热床的 GLB 文件（无模型）。

    Args:
        bed_w (int): Bed width in mm. Defaults to BedManager default.
        bed_h (int): Bed height in mm. Defaults to BedManager default.
        is_dark (bool): Use dark PEI theme.

    Returns:
        str: Path to GLB file, or None on failure.
    """
    try:
        # Lazy import: _create_bed_mesh lives in converter.py until P06 is wired
        from core.converter import _create_bed_mesh

        if bed_w is None or bed_h is None:
            bed_w, bed_h = BedManager.get_bed_size(BedManager.DEFAULT_BED)
        bed_mesh = _create_bed_mesh(bed_w, bed_h, is_dark=is_dark)
        if bed_mesh is None:
            return None
        glb_scene = trimesh.Scene()
        glb_scene.add_geometry(bed_mesh, node_name="bed")
        glb_path = os.path.join(OUTPUT_DIR, f"empty_bed_{bed_w}x{bed_h}.glb")
        glb_scene.export(glb_path)
        return glb_path
    except (OSError, ImportError, ValueError, TypeError, RuntimeError) as e:
        _log.warning(f"Failed: {e}")
        return None


def generate_segmented_glb(
    cache: dict,
    output_path: str,
    max_meshes: int = 128,
    *,
    outline_mesh: trimesh.Trimesh | None = None,
    total_layers: int = 25,
) -> Optional[str]:
    """Generate a color-segmented GLB with a bounded scene-node contract.
    生成按颜色分段、且场景节点总数受控的 GLB 预览。

    LUT previews retain named colour meshes for legacy viewer compatibility.
    Material-archive previews batch the optical appearance into one mesh and
    emit at most one physical mesh for each lower layer; display colour,
    relief-height identity, and physical-layer display colours remain separate.
    LUT 预览继续保留历史命名色块；耗材档案预览把外观合批为一个 mesh，
    其余物理层每层至多一个 mesh，同时保留显示色、高度身份与物理层预览色。

    Args:
        outline_mesh: Optional batch outline in preview coordinates. Single-image
            quick previews leave this absent and use their interactive overlay.
        total_layers: Display height in printer layers; batch callers use the
            generated model height so the embedded outline aligns vertically.
        cache (dict): Preview cache dict containing at least:
            - matched_rgb: (H, W, 3) uint8 array
            - mask_solid: (H, W) bool array
            - backing_mask: (H, W) optional bool array for a backing footprint
              that differs from the visible colour pixels. SVG/vector preview
              caches use this to keep the GLB backing aligned with the native
              vector ``Board`` mesh.
            - target_w, target_h: pixel dimensions
            - target_width_mm: physical width in mm; missing/null legacy
              values fall back to ``PrinterConfig.NOZZLE_WIDTH`` per pixel.
            - glb_max_meshes (optional): per-session override that bumps
              the retained-colour merge cap above the function default. Set by edit
              endpoints (e.g. ``/region-requantize``) that intentionally
              add many low-frequency colours which would otherwise be
              wiped out by the default 128-mesh merge.
              可选：调用方写入的保留颜色数上限覆盖。例如二次量化会引入
              大量低频新色，若按默认 128 合并它们会被丢回原色，导致 GLB
              和 2D 预览不一致。
        output_path (str): Required absolute path the exported GLB is written to.
            Callers MUST pass a session-scoped, collision-free path (typically
            built via ``core.naming.generate_segmented_glb_filename`` joined to
            ``OUTPUT_DIR``). Sharing one process-global path across concurrent
            sessions overwrites peer GLBs on disk and surfaces as a 3D preview
            cross-session contamination bug; see
            ``progress/glb-internals-audit-2026-04-30.md``.
            必填。调用方必须传入会话隔离、不会冲突的路径（通常由
            ``core.naming.generate_segmented_glb_filename`` 拼 接
            ``OUTPUT_DIR`` 得到）。共用同一进程级路径会跨会话覆写彼此的 GLB，
            表现为“3D 预览串联”；详见
            ``progress/glb-internals-audit-2026-04-30.md``。
        max_meshes (int): Default retained-colour limit before low-frequency
            colours are merged when no cache override is present (default 128).

    Returns:
        str: Path to the exported GLB file (== ``output_path`` on success),
            or ``None`` on failure.

    Side effects (cache mutations):
        On success the function writes two keys back into ``cache`` for
        downstream consumers:
            - ``cache['color_contours']``: ``dict[str, list[list[list[float]]]]``
                Per-colour world-space pixel contours extracted via
                ``cv2.findContours``; consumed by API responses to draw
                SVG overlays aligned with the GLB.
            - ``cache['_segmented_glb_timings']``: ``dict[str, float]``
                Per-stage wall-clock timings (downsample/unique/merge/...)
                useful for performance profiling.
        Each ``cache`` is per-session, so these writes never cross sessions,
        but callers should not assume the input dict is read-only.
        会话级缓存反馈：成功调用后函数向 ``cache`` 写入 ``color_contours``
        （每色轮廓）与 ``_segmented_glb_timings``（各阶段耗时）两个键；
        ``cache`` 本身属于单个会话，因此该写入不会跨会话，但调用方
        不能把入参当作只读。
    """
    if cache is None:
        return None

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    backing_mask = cache.get("backing_mask")
    target_w = cache.get("target_w")
    target_width_mm = cache.get("target_width_mm")

    if matched_rgb is None or mask_solid is None:
        return None
    height_identity_rgb = _resolve_height_identity_rgb(cache, matched_rgb)
    material_matrix = _material_matrix_for_segmented_glb(cache, mask_solid)
    if backing_mask is not None:
        try:
            backing_mask = np.asarray(backing_mask, dtype=bool)
        except (TypeError, ValueError):
            backing_mask = None
    if backing_mask is not None and backing_mask.shape != mask_solid.shape:
        _log.warning(
            "Backing mask shape mismatch; falling back to mask_solid",
            extra={
                "event": "segmented_glb_backing_mask_mismatch",
                "backing_mask_shape": list(backing_mask.shape),
                "mask_solid_shape": list(mask_solid.shape),
            },
        )
        backing_mask = None

    # Honour per-session override before the merge step. Anything below
    # the function default is ignored — we never want to merge MORE than
    # the caller-provided default (which is sized to a known-good upper
    # bound for three.js perf). Anything above bumps the cap so newly
    # added colours from edit endpoints survive into the segmented GLB.
    # 仅在 cache 覆盖值大于默认时生效；小于默认时退回默认，避免下调上限
    # 反而让正常预览的颜色被多砍。
    cache_override = cache.get("glb_max_meshes")
    if isinstance(cache_override, (int, np.integer)) and int(cache_override) > max_meshes:
        max_meshes = int(cache_override)

    height = None
    width = None
    scene = None
    requested_kernel = None
    logged_max_meshes = int(max_meshes) if isinstance(max_meshes, (int, np.integer)) else None

    try:
        _glb_t0 = time.perf_counter()

        # 1. Downsample large images
        _t = time.perf_counter()
        height, width = matched_rgb.shape[:2]
        total_pixels = width * height
        scale_factor = _resolve_glb_downsample_factor(total_pixels)

        if scale_factor > 1:
            _log.debug(f"Downsampling by {scale_factor}x")

            new_h = height // scale_factor
            new_w = width // scale_factor
            matched_rgb = cv2.resize(matched_rgb, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
            height_identity_rgb = cv2.resize(
                height_identity_rgb,
                (new_w, new_h),
                interpolation=cv2.INTER_NEAREST,
            )
            mask_solid = cv2.resize(
                mask_solid.astype(np.uint8),
                (new_w, new_h),
                interpolation=cv2.INTER_NEAREST,
            ).astype(bool)
            if backing_mask is not None:
                backing_mask = cv2.resize(
                    backing_mask.astype(np.uint8),
                    (new_w, new_h),
                    interpolation=cv2.INTER_NEAREST,
                ).astype(bool)
            if material_matrix is not None:
                material_matrix = _resize_material_matrix_nearest(
                    material_matrix,
                    new_w,
                    new_h,
                )
            height, width = new_h, new_w
            shrink = 0.0
        else:
            shrink = 0.0
        _t_downsample = time.perf_counter() - _t

        # 2. Extract unique colors and pixel counts (solid pixels only)
        _t = time.perf_counter()
        flat_mask = mask_solid.reshape(-1)
        solid_idx = np.flatnonzero(flat_mask)
        flat_rgb = matched_rgb.reshape(-1, 3).astype(np.uint32, copy=False)
        solid_pixels = flat_rgb[solid_idx]  # (N, 3)
        if len(solid_pixels) == 0:
            _log.warning("No solid pixels, returning None")
            return None

        solid_codes = (solid_pixels[:, 0] << 16) | (solid_pixels[:, 1] << 8) | solid_pixels[:, 2]
        unique_codes, inverse, pixel_counts = np.unique(
            solid_codes,
            return_inverse=True,
            return_counts=True,
        )
        n_unique = len(unique_codes)
        _log.debug(
            "unique-colour scan",
            extra={
                "event": "segmented_glb_unique_scan",
                "n_unique": int(n_unique),
                "max_meshes": int(max_meshes),
                "cache_override": int(cache_override) if isinstance(cache_override, (int, np.integer)) else None,
                "will_merge": bool(n_unique > max_meshes),
            },
        )
        _t_unique = time.perf_counter() - _t

        # 3. Merge low-frequency colors if exceeding max_meshes
        _t = time.perf_counter()
        if n_unique > max_meshes:
            _log.debug(
                "merging low-frequency colours",
                extra={
                    "event": "segmented_glb_merge_low_freq",
                    "n_unique_before": int(n_unique),
                    "max_meshes": int(max_meshes),
                    "n_to_merge": int(n_unique - max_meshes),
                },
            )
            unique_colors = np.column_stack(
                [
                    (unique_codes >> 16) & 0xFF,
                    (unique_codes >> 8) & 0xFF,
                    unique_codes & 0xFF,
                ]
            ).astype(np.uint8)
            merged_colors = _merge_low_frequency_colors(unique_colors, pixel_counts, max_meshes)
            merged_codes = (
                (merged_colors[:, 0].astype(np.uint32) << 16)
                | (merged_colors[:, 1].astype(np.uint32) << 8)
                | merged_colors[:, 2].astype(np.uint32)
            )
            code_map = merged_codes[inverse]
            updated_flat = matched_rgb.reshape(-1, 3).copy()
            updated_flat[solid_idx, 0] = (code_map >> 16) & 0xFF
            updated_flat[solid_idx, 1] = (code_map >> 8) & 0xFF
            updated_flat[solid_idx, 2] = code_map & 0xFF
            matched_rgb = updated_flat.reshape(matched_rgb.shape).astype(np.uint8, copy=False)

            unique_codes, inverse, pixel_counts = np.unique(
                code_map,
                return_inverse=True,
                return_counts=True,
            )
            _log.debug(f"After merge: {len(unique_codes)} colors")
        color_indices: dict[int, np.ndarray] = {}
        for code_idx in range(len(unique_codes)):
            color_indices[code_idx] = solid_idx[inverse == code_idx]
        _t_merge = time.perf_counter() - _t

        # 4. Build colour geometry + extract 2D contours (single pass).
        # Material archives concatenate the colour parts into one appearance
        # node after this loop, so unique colours do not multiply draw calls.
        _t = time.perf_counter()
        scene = trimesh.Scene()
        contours_data: dict[str, list[list[list[float]]]] = {}
        use_material_matrix_meshes = material_matrix is not None

        pixel_scale = _resolve_glb_pixel_scale(target_width_mm, width)
        scale_transform = np.eye(4)
        scale_transform[0, 0] = pixel_scale
        scale_transform[1, 1] = pixel_scale
        scale_transform[2, 2] = PrinterConfig.LAYER_HEIGHT

        flat_total = width * height
        color_match_flat = np.zeros(flat_total, dtype=bool)
        appearance_match_flat = np.zeros(flat_total, dtype=bool)
        material_scale_transform = None
        material_layer_count = 0
        material_layer_height_mm = 0.0
        appearance_parts: list[trimesh.Trimesh] = []
        height_segments: list[dict[str, int | str]] = []
        appearance_vertex_cursor = 0
        height_identity_codes_flat = _rgb_codes(height_identity_rgb).reshape(-1)
        if material_matrix is not None:
            material_layer_count = int(material_matrix.shape[2])
            material_layer_height_mm = _resolve_material_layer_height_mm(cache)
            material_scale_transform = np.eye(4)
            material_scale_transform[0, 0] = pixel_scale
            material_scale_transform[1, 1] = pixel_scale
            material_scale_transform[2, 2] = material_layer_height_mm
        _t_mask_build = 0.0
        requested_kernel = _resolve_kernel_choice()
        use_material_color = requested_kernel in {"rasterio_manifold3d", "auto"}
        for code_idx, code in enumerate(unique_codes):
            r = int((code >> 16) & 0xFF)
            g = int((code >> 8) & 0xFF)
            b = int(code & 0xFF)
            hex_name = f"{r:02x}{g:02x}{b:02x}"
            rgba = np.array([r, g, b, 255], dtype=np.uint8)

            idxs = color_indices.get(code_idx)
            if idxs is None or len(idxs) == 0:
                continue
            _mask_t0 = time.perf_counter()
            color_match_flat[idxs] = True
            color_match = color_match_flat.reshape(height, width)
            _t_mask_build += time.perf_counter() - _mask_t0

            if use_material_matrix_meshes:
                # Build appearance shells by stable relief identity, not by
                # physical material. This sole layer-0 shell carries exact 2D
                # display colours plus immutable per-vertex height ranges.
                # Keeping only viewer-consumed vertex ranges avoids a second
                # coplanar shell and geometry multiplication by colour ×
                # material.
                top_z_offset_mm = (
                    float(material_layer_count - 1) * material_layer_height_mm
                )
                identity_codes_for_color = height_identity_codes_flat[idxs]
                for raw_height_code in np.unique(identity_codes_for_color):
                    height_code = int(raw_height_code)
                    height_idxs = idxs[
                        identity_codes_for_color == raw_height_code
                    ]
                    appearance_match_flat[height_idxs] = True
                    appearance_mesh = _build_color_extruded_mesh(
                        appearance_match_flat.reshape(height, width),
                        height,
                        1,
                        rgba,
                        assign_face_colors=False,
                    )
                    appearance_match_flat[height_idxs] = False
                    if appearance_mesh is None:
                        continue
                    appearance_mesh = _remove_mesh_horizontal_caps(
                        appearance_mesh,
                        remove_bottom=True,
                    )
                    if appearance_mesh is None:
                        continue
                    appearance_mesh.apply_transform(material_scale_transform)
                    appearance_min_z = float(
                        appearance_mesh.vertices[:, 2].min()
                    )
                    if appearance_min_z != 0.0:
                        appearance_mesh.vertices[:, 2] -= appearance_min_z
                    if top_z_offset_mm != 0.0:
                        appearance_mesh.vertices[:, 2] += top_z_offset_mm
                    height_segments.append(
                        {
                            "height_key": _rgb_code_to_hex(height_code),
                            "display_hex": hex_name,
                            "vertex_start": appearance_vertex_cursor,
                            "vertex_count": int(len(appearance_mesh.vertices)),
                        }
                    )
                    appearance_vertex_cursor += int(len(appearance_mesh.vertices))
                    appearance_parts.append(appearance_mesh)
            else:
                mesh = _build_color_extruded_mesh(
                    color_match,
                    height,
                    total_layers,
                    rgba,
                    assign_face_colors=not use_material_color,
                )
                if mesh is not None:
                    if use_material_color:
                        _assign_mesh_material_rgba(
                            mesh,
                            rgba,
                            material_name=f"color_{hex_name}_material",
                        )
                    mesh.apply_transform(scale_transform)
                    min_z = mesh.vertices[:, 2].min()
                    if min_z != 0.0:
                        mesh.vertices[:, 2] -= min_z
                    scene.add_geometry(mesh, node_name=f"color_{hex_name}")

            # Reuse same color_match for contour extraction
            color_contour_list = _extract_mask_contours(color_match, height, pixel_scale)
            if color_contour_list:
                contours_data[hex_name] = color_contour_list
            color_match_flat[idxs] = False

        if material_matrix is not None:
            appearance_mesh = _concatenate_layered_mesh_parts(
                appearance_parts,
                metadata={
                    "height_segments": height_segments,
                },
            )
            if appearance_mesh is not None:
                _assign_mesh_material_rgba(
                    appearance_mesh,
                    np.array([255, 255, 255, 255], dtype=np.uint8),
                    material_name="layered_appearance_palette",
                )
                appearance_node_name = "color_layered_appearance_l000"
                scene.add_geometry(
                    appearance_mesh,
                    node_name=appearance_node_name,
                    geom_name=appearance_node_name,
                )
            _add_material_matrix_color_meshes(
                scene=scene,
                cache=cache,
                material_matrix=material_matrix,
                mask_solid=mask_solid,
                height=height,
                pixel_scale=pixel_scale,
            )

        _t_mesh_loop = time.perf_counter() - _t

        if len(scene.geometry) == 0:
            _log.warning("No meshes generated")
            return None

        # 4.5 Build backing plate mesh (contour extrusion)
        _t = time.perf_counter()
        backing_source_mask = backing_mask if backing_mask is not None else mask_solid
        backing_mesh = _build_backing_plate_mesh(
            mask_solid=backing_source_mask,
            height=height,
            pixel_scale=pixel_scale,
            rgba=np.array([245, 245, 245, 255], dtype=np.uint8),
        )
        if backing_mesh is not None:
            scene.add_geometry(backing_mesh, node_name="backing_plate")
            _log.debug(f"Backing plate added ({backing_mesh.vertices.shape[0]} vertices)")
        _t_backing = time.perf_counter() - _t

        if outline_mesh is not None:
            scene.add_geometry(outline_mesh, node_name="Outline", geom_name="Outline")

        _t = time.perf_counter()
        canvas_bounds_mesh = _build_preview_canvas_bounds_mesh(
            width=width,
            height=height,
            pixel_scale=pixel_scale,
        )
        if canvas_bounds_mesh is not None:
            scene.add_geometry(
                canvas_bounds_mesh,
                node_name=PREVIEW_CANVAS_BOUNDS_NODE_NAME,
            )
        _t_canvas_bounds = time.perf_counter() - _t

        cache["color_contours"] = contours_data
        _log.debug(f"Extracted contours for {len(contours_data)} colors")

        # 6. Export GLB
        _t = time.perf_counter()
        glb_path = output_path
        export_kwargs = {}
        if _resolve_kernel_choice() in {"rasterio_manifold3d", "auto"}:
            export_kwargs["buffer_postprocessor"] = _sort_triangle_index_buffers_for_gzip
        scene.export(glb_path, file_type="glb", **export_kwargs)
        _t_export = time.perf_counter() - _t

        _t_glb_total = time.perf_counter() - _glb_t0
        cache["_segmented_glb_timings"] = {
            "downsample_s": _t_downsample,
            "unique_s": _t_unique,
            "merge_s": _t_merge,
            "mask_build_s": _t_mask_build,
            "mesh_loop_s": _t_mesh_loop,
            "backing_s": _t_backing,
            "canvas_bounds_s": _t_canvas_bounds,
            "export_s": _t_export,
            "total_s": _t_glb_total,
        }
        _log.debug(f"Exported {len(scene.geometry)} meshes -> {glb_path}")
        _log.debug(
            f"Timing: downsample={_t_downsample:.2f}s, "
            f"unique={_t_unique:.2f}s, merge={_t_merge:.2f}s, mask_build={_t_mask_build:.2f}s, "
            f"mesh_loop={_t_mesh_loop:.2f}s, backing={_t_backing:.2f}s, "
            f"canvas_bounds={_t_canvas_bounds:.2f}s, "
            f"export={_t_export:.2f}s, total={_t_glb_total:.2f}s"
        )
        return glb_path

    except (OSError, ValueError, TypeError, RuntimeError) as e:
        _log.exception(
            "Segmented GLB export failed",
            extra={
                "event": "segmented_glb_export_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
                "output_path": str(output_path),
                "width": int(width) if width is not None else None,
                "height": int(height) if height is not None else None,
                "geometry_count": int(len(scene.geometry)) if scene is not None else 0,
                "max_meshes": logged_max_meshes,
                "kernel": requested_kernel,
            },
        )
        return None


def generate_realtime_glb(cache: dict, output_path: str) -> Optional[str]:
    """Generate a lightweight GLB preview from cached preview data.
    从缓存的预览数据生成轻量级 GLB 预览。

    Called during preview stage so the 3D thumbnail updates immediately
    without waiting for the full 3MF export.

    Args:
        cache (dict): Preview cache dict from generate_preview_cached.
        output_path (str): Required absolute path the exported GLB is written to.
            Same session-isolation rules as :func:`generate_segmented_glb`—
            callers MUST pass a unique per-session path to avoid cross-session
            overwrites on disk.
            必填。与 :func:`generate_segmented_glb` 同样的会话隔离要求，
            调用方必须传入会话隔离、不会冲突的路径。

    Returns:
        str: Path to GLB file (== ``output_path`` on success), or ``None`` on failure.
    """
    if cache is None:
        return None

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    target_w = cache.get("target_w")
    target_h = cache.get("target_h")
    target_width_mm = cache.get("target_width_mm")
    color_conf = cache.get("color_conf")

    if matched_rgb is None or mask_solid is None:
        return None

    try:
        total_layers = 25
        preview_colors = color_conf.get("preview") if color_conf else None

        preview_mesh = _create_preview_mesh(
            matched_rgb,
            mask_solid,
            total_layers,
            backing_color_id=cache.get("backing_color_id", 0),
            preview_colors=preview_colors,
        )

        if preview_mesh is None:
            _log.warning("Preview mesh is None (model too large?)")
            return None

        # Scale from pixel/voxel coords to mm
        mesh_width = preview_mesh.bounds[1][0] - preview_mesh.bounds[0][0]
        pixel_scale = _resolve_glb_pixel_scale(target_width_mm, mesh_width)
        transform = np.eye(4)
        transform[0, 0] = pixel_scale
        transform[1, 1] = pixel_scale
        transform[2, 2] = PrinterConfig.LAYER_HEIGHT
        preview_mesh.apply_transform(transform)

        glb_path = output_path
        preview_mesh.export(glb_path)
        _log.debug(f"Exported: {glb_path}")
        return glb_path

    except (OSError, ValueError, TypeError, RuntimeError) as e:
        _log.warning(f"Failed: {e}")
        return None


def run(ctx: dict) -> dict:
    """Generate GLB 3D preview for the converted model.
    为转换后的模型生成 GLB 3D 预览。

    PipelineContext 输入键 / Input keys:
        - matched_rgb (np.ndarray): (H, W, 3) 匹配后的 RGB
        - mask_solid (np.ndarray): (H, W) bool 实体掩码
        - total_layers (int): 总层数
        - backing_color_id (int): 底板材料 ID
        - backing_metadata (dict): 底板元数据
        - preview_colors (dict): 材料预览颜色
        - pixel_scale (float): mm/px 缩放因子
        - loop_info (dict | None): 挂件环信息
        - loop_added (bool): 挂件环是否已添加
        - image_path (str): 原始图像路径
        - modeling_mode (ModelingMode): 建模模式
        - target_h (int): 图像高度（像素）
        - transform (np.ndarray): 4x4 变换矩阵
        - preview_glb_path (str | None): 可复用的已生成预览 GLB 路径

    PipelineContext 输出键 / Output keys:
        - glb_path (str | None): GLB 预览文件路径
    """
    _t0 = time.perf_counter()

    reusable_glb_path = ctx.get("preview_glb_path")
    if (
        isinstance(reusable_glb_path, str)
        and os.path.exists(reusable_glb_path)
    ):
        _prog = ctx.get("progress")
        if _prog is not None:
            _prog(0.90, "复用 3D 预览中... | Reusing 3D preview...")
        ctx["glb_path"] = reusable_glb_path
        _elapsed = time.perf_counter() - _t0
        _hifi_timings = ctx.setdefault("_hifi_timings", {})
        _hifi_timings["glb_preview_s"] = _elapsed
        _log.debug(f"glb_preview reused: {_elapsed:.3f}s")
        return ctx

    matched_rgb = ctx["matched_rgb"]
    mask_solid = ctx["mask_solid"]
    pixel_scale = ctx["pixel_scale"]
    image_path = ctx["image_path"]

    _prog = ctx.get("progress")
    if _prog is not None:
        _prog(0.90, "生成 3D 预览中... | Generating 3D preview...")

    height, width = matched_rgb.shape[:2]
    target_width_mm = pixel_scale * width
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(OUTPUT_DIR, generate_preview_filename(base_name))

    cache = {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "target_w": width,
        "target_h": height,
        "target_width_mm": target_width_mm,
    }
    if bool(ctx.get("high_precision_3d_preview", False)):
        try:
            glb_mesh_budget = int(ctx.get("quantize_colors") or 0)
        except (TypeError, ValueError):
            glb_mesh_budget = 0
        if glb_mesh_budget > 128:
            cache["glb_max_meshes"] = glb_mesh_budget
    batch_preview_options = (
        {"outline_mesh": ctx.get("preview_outline_mesh"), "total_layers": ctx["total_layers"]}
        if ctx.get("batch_preview", False) else {}
    )
    glb_path = generate_segmented_glb(cache, output_path=out_path, **batch_preview_options)

    ctx["glb_path"] = glb_path

    _elapsed = time.perf_counter() - _t0
    _log.debug(f"glb_preview done: {_elapsed:.3f}s")
    _hifi_timings = ctx.setdefault("_hifi_timings", {})
    _hifi_timings["glb_preview_s"] = _elapsed
    seg_timing = cache.get("_segmented_glb_timings")
    if isinstance(seg_timing, dict):
        _hifi_timings["s11_unique_s"] = float(seg_timing.get("unique_s", 0.0))
        _hifi_timings["s11_merge_s"] = float(seg_timing.get("merge_s", 0.0))
        _hifi_timings["s11_mask_build_s"] = float(seg_timing.get("mask_build_s", 0.0))
        _hifi_timings["s11_mesh_loop_s"] = float(seg_timing.get("mesh_loop_s", 0.0))
        _hifi_timings["s11_backing_s"] = float(seg_timing.get("backing_s", 0.0))
        _hifi_timings["s11_export_s"] = float(seg_timing.get("export_s", 0.0))
    return ctx
