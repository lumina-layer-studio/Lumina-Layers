"""
S11 — GLB 3D preview export.
S11 — GLB 3D 预览导出。

从 converter.py 搬入的 GLB 预览函数：
- _create_preview_mesh: 简化预览网格生成
- _merge_low_frequency_colors: 低频颜色合并
- _build_color_voxel_mesh: 按颜色体素网格构建
- generate_segmented_glb: 分色 GLB 预览
- generate_realtime_glb: 实时 GLB 预览
- generate_empty_bed_glb: 空热床 GLB
"""

import os
from typing import Optional

import cv2
import numpy as np
import trimesh

from config import PrinterConfig, OUTPUT_DIR, BedManager
from core.naming import generate_preview_filename


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

        print(f"[PREVIEW] Downsampling by {scale_factor}x ({total_pixels:,} -> ~{TARGET_PIXELS:,} pixels)")

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

    solid_ys, solid_xs = np.where(mask_solid)
    n_solid = len(solid_ys)
    if n_solid == 0:
        return None

    wx0 = solid_xs.astype(np.float64)
    wx1 = wx0 + 1.0
    wy0 = (height - 1 - solid_ys).astype(np.float64)
    wy1 = wy0 + 1.0

    pixel_rgb = matched_rgb[solid_ys, solid_xs]
    pixel_rgba = np.column_stack([pixel_rgb, np.full(n_solid, 255, dtype=np.uint8)])

    _FACE_TPL = np.array(
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

    def _boxes_batch(bx0, bx1, by0, by1, bz0, bz1, rgba, v_offset):
        """Build N boxes as pre-allocated arrays with global vertex offset."""
        m = len(bx0)
        v = np.empty((m, 8, 3), dtype=np.float64)
        v[:, 0, 0] = bx0
        v[:, 0, 1] = by0
        v[:, 0, 2] = bz0
        v[:, 1, 0] = bx1
        v[:, 1, 1] = by0
        v[:, 1, 2] = bz0
        v[:, 2, 0] = bx1
        v[:, 2, 1] = by1
        v[:, 2, 2] = bz0
        v[:, 3, 0] = bx0
        v[:, 3, 1] = by1
        v[:, 3, 2] = bz0
        v[:, 4, 0] = bx0
        v[:, 4, 1] = by0
        v[:, 4, 2] = bz1
        v[:, 5, 0] = bx1
        v[:, 5, 1] = by0
        v[:, 5, 2] = bz1
        v[:, 6, 0] = bx1
        v[:, 6, 1] = by1
        v[:, 6, 2] = bz1
        v[:, 7, 0] = bx0
        v[:, 7, 1] = by1
        v[:, 7, 2] = bz1
        offsets = (np.arange(m, dtype=np.int64) * 8 + v_offset).reshape(-1, 1, 1)
        f = _FACE_TPL.reshape(1, 12, 3) + offsets
        fc = np.broadcast_to(rgba[:, np.newaxis, :], (m, 12, 4)).copy().reshape(-1, 4)
        return v.reshape(-1, 3), f.reshape(-1, 3), fc

    all_v, all_f, all_c = [], [], []
    v_offset = 0

    if backing_z_range is not None and preview_colors is not None:
        backing_start, backing_end = backing_z_range
        actual_bid = 0 if backing_color_id == -2 else backing_color_id
        pc = preview_colors[actual_bid]
        backing_rgba = np.broadcast_to(
            np.array([int(pc[0]), int(pc[1]), int(pc[2]), 255], dtype=np.uint8),
            (n_solid, 4),
        )
        bz0 = np.full(n_solid, float(backing_start))
        bz1 = np.full(n_solid, float(backing_end + 1))
        bv, bf, bc = _boxes_batch(wx0, wx1, wy0, wy1, bz0, bz1, backing_rgba, v_offset)
        all_v.append(bv)
        all_f.append(bf)
        all_c.append(bc)
        v_offset += n_solid * 8

        if backing_start > 0:
            z0 = np.zeros(n_solid)
            z1 = np.full(n_solid, float(backing_start))
            bv, bf, bc = _boxes_batch(wx0, wx1, wy0, wy1, z0, z1, pixel_rgba, v_offset)
            all_v.append(bv)
            all_f.append(bf)
            all_c.append(bc)
            v_offset += n_solid * 8

        if backing_end + 1 < total_layers:
            z0 = np.full(n_solid, float(backing_end + 1))
            z1 = np.full(n_solid, float(total_layers))
            bv, bf, bc = _boxes_batch(wx0, wx1, wy0, wy1, z0, z1, pixel_rgba, v_offset)
            all_v.append(bv)
            all_f.append(bf)
            all_c.append(bc)
            v_offset += n_solid * 8
    else:
        z0 = np.zeros(n_solid)
        z1 = np.full(n_solid, float(total_layers))
        bv, bf, bc = _boxes_batch(wx0, wx1, wy0, wy1, z0, z1, pixel_rgba, v_offset)
        all_v.append(bv)
        all_f.append(bf)
        all_c.append(bc)

    vertices = np.concatenate(all_v)
    faces = np.concatenate(all_f)
    face_colors = np.concatenate(all_c)

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.visual.face_colors = face_colors

    print(f"[PREVIEW] Generated: {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces")

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


def _build_color_voxel_mesh(
    mask: np.ndarray,
    height: int,
    width: int,
    total_layers: int,
    shrink: float,
    rgba: np.ndarray,
) -> Optional[trimesh.Trimesh]:
    """Build a voxelized Trimesh for pixels indicated by *mask*.
    为 mask 指示的像素构建体素化 Trimesh。

    Args:
        mask (np.ndarray): (H, W) bool array of pixels belonging to this color.
        height (int): Image height after downsampling.
        width (int): Image width after downsampling.
        total_layers (int): Number of Z layers for the voxel height.
        shrink (float): Inset amount for voxel gaps.
        rgba (np.ndarray): (4,) uint8 RGBA color for face coloring.

    Returns:
        trimesh.Trimesh or None: Generated mesh, or None if mask has no True pixels.
    """
    ys, xs = np.where(mask)
    n_pixels = len(ys)
    if n_pixels == 0:
        return None

    # Pre-allocate arrays for all cubes (8 verts, 12 faces each)
    all_verts = np.empty((n_pixels * 8, 3), dtype=np.float64)
    all_faces = np.empty((n_pixels * 12, 3), dtype=np.int64)
    all_colors = np.empty((n_pixels * 12, 4), dtype=np.uint8)

    cube_faces_template = np.array(
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

    x0 = xs.astype(np.float64) + shrink
    x1 = xs.astype(np.float64) + 1.0 - shrink
    world_y = (height - 1 - ys).astype(np.float64)
    y0 = world_y + shrink
    y1 = world_y + 1.0 - shrink
    z0 = np.zeros(n_pixels, dtype=np.float64)
    z1 = np.full(n_pixels, float(total_layers), dtype=np.float64)

    # Vectorized vertex construction: 8 corners per pixel
    for i, (vx0, vx1, vy0, vy1, vz0, vz1) in enumerate(zip(x0, x1, y0, y1, z0, z1)):
        base = i * 8
        all_verts[base : base + 8] = [
            [vx0, vy0, vz0],
            [vx1, vy0, vz0],
            [vx1, vy1, vz0],
            [vx0, vy1, vz0],
            [vx0, vy0, vz1],
            [vx1, vy0, vz1],
            [vx1, vy1, vz1],
            [vx0, vy1, vz1],
        ]
        face_base = i * 12
        all_faces[face_base : face_base + 12] = cube_faces_template + base
        all_colors[face_base : face_base + 12] = rgba

    mesh = trimesh.Trimesh(vertices=all_verts, faces=all_faces, process=False)
    mesh.visual.face_colors = all_colors
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
    except Exception as e:
        print(f"[EMPTY_BED] Failed: {e}")
        return None


def generate_segmented_glb(cache: dict, max_meshes: int = 64) -> Optional[str]:
    """Generate a color-segmented GLB preview with one named Mesh per color.
    生成按颜色分段的 GLB 预览，每种颜色一个独立 Mesh。

    Args:
        cache (dict): Preview cache dict containing at least:
            - matched_rgb: (H, W, 3) uint8 array
            - mask_solid: (H, W) bool array
            - target_w, target_h: pixel dimensions
            - target_width_mm: physical width in mm
        max_meshes (int): Maximum Mesh count before merging (default 64).

    Returns:
        str: Path to the exported GLB file, or None on failure.
    """
    if cache is None:
        return None

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    target_w = cache.get("target_w")
    target_width_mm = cache.get("target_width_mm")

    if matched_rgb is None or mask_solid is None:
        return None

    try:
        # 1. Downsample large images
        height, width = matched_rgb.shape[:2]
        total_pixels = width * height
        SIMPLIFY_THRESHOLD = 500_000
        TARGET_PIXELS = 300_000

        if total_pixels > SIMPLIFY_THRESHOLD:
            scale_factor = int(np.sqrt(total_pixels / TARGET_PIXELS))
            scale_factor = max(2, min(scale_factor, 16))
            print(f"[SEGMENTED_GLB] Downsampling by {scale_factor}x")

            new_h = height // scale_factor
            new_w = width // scale_factor
            matched_rgb = cv2.resize(matched_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
            mask_solid = cv2.resize(
                mask_solid.astype(np.uint8),
                (new_w, new_h),
                interpolation=cv2.INTER_NEAREST,
            ).astype(bool)
            height, width = new_h, new_w
            shrink = 0.0
        else:
            shrink = 0.0

        # 2. Extract unique colors and pixel counts (solid pixels only)
        solid_pixels = matched_rgb[mask_solid]  # (N, 3)
        if len(solid_pixels) == 0:
            print("[SEGMENTED_GLB] No solid pixels, returning None")
            return None

        unique_colors, inverse, pixel_counts = np.unique(
            solid_pixels,
            axis=0,
            return_inverse=True,
            return_counts=True,
        )
        n_unique = len(unique_colors)
        print(f"[SEGMENTED_GLB] Found {n_unique} unique colors")

        # 3. Merge low-frequency colors if exceeding max_meshes
        if n_unique > max_meshes:
            print(f"[SEGMENTED_GLB] Merging {n_unique} colors down to {max_meshes}")
            merged_colors = _merge_low_frequency_colors(unique_colors, pixel_counts, max_meshes)
            new_solid = merged_colors[inverse]
            matched_rgb_work = matched_rgb.copy()
            matched_rgb_work[mask_solid] = new_solid
            solid_pixels = matched_rgb_work[mask_solid]
            unique_colors, _, pixel_counts = np.unique(
                solid_pixels,
                axis=0,
                return_inverse=True,
                return_counts=True,
            )
            matched_rgb = matched_rgb_work
            print(f"[SEGMENTED_GLB] After merge: {len(unique_colors)} colors")

        # 4. Build per-color Meshes
        total_layers = 25
        scene = trimesh.Scene()

        pixel_scale = target_width_mm / width if width > 0 else 0.42
        scale_transform = np.eye(4)
        scale_transform[0, 0] = pixel_scale
        scale_transform[1, 1] = pixel_scale
        scale_transform[2, 2] = PrinterConfig.LAYER_HEIGHT

        for color_rgb in unique_colors:
            r, g, b = int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2])
            hex_name = f"{r:02x}{g:02x}{b:02x}"
            rgba = np.array([r, g, b, 255], dtype=np.uint8)

            color_match = np.all(matched_rgb == color_rgb, axis=2) & mask_solid

            mesh = _build_color_voxel_mesh(
                color_match,
                height,
                width,
                total_layers,
                shrink,
                rgba,
            )
            if mesh is None:
                continue

            mesh.apply_transform(scale_transform)

            min_z = mesh.vertices[:, 2].min()
            if min_z != 0.0:
                mesh.vertices[:, 2] -= min_z

            scene.add_geometry(mesh, node_name=f"color_{hex_name}")

        if len(scene.geometry) == 0:
            print("[SEGMENTED_GLB] No meshes generated")
            return None

        # 4.5 Build backing plate mesh
        backing_mesh = _build_color_voxel_mesh(
            mask_solid,
            height,
            width,
            total_layers=1,
            shrink=shrink,
            rgba=np.array([245, 245, 245, 255], dtype=np.uint8),
        )
        if backing_mesh is not None:
            backing_mesh.apply_transform(scale_transform)
            min_z = backing_mesh.vertices[:, 2].min()
            if min_z != 0.0:
                backing_mesh.vertices[:, 2] -= min_z
            scene.add_geometry(backing_mesh, node_name="backing_plate")
            print(f"[SEGMENTED_GLB] Backing plate added ({backing_mesh.vertices.shape[0]} vertices)")

        # 5. Extract 2D contours for each color
        contours_data: dict[str, list[list[list[float]]]] = {}
        for color_rgb in unique_colors:
            r, g, b = int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2])
            hex_name = f"{r:02x}{g:02x}{b:02x}"

            color_match = np.all(matched_rgb == color_rgb, axis=2) & mask_solid
            mask_u8 = color_match.astype(np.uint8) * 255

            cv_contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cv_contours:
                continue

            color_contour_list: list[list[list[float]]] = []
            for cnt in cv_contours:
                if len(cnt) < 3:
                    continue
                pts = cnt.squeeze(1).astype(float)
                world_pts: list[list[float]] = []
                for px, py in pts:
                    x_mm = float(px * pixel_scale)
                    y_mm = float((height - py) * pixel_scale)
                    world_pts.append([x_mm, y_mm])
                color_contour_list.append(world_pts)

            if color_contour_list:
                contours_data[hex_name] = color_contour_list

        cache["color_contours"] = contours_data
        print(f"[SEGMENTED_GLB] Extracted contours for {len(contours_data)} colors")

        # 6. Export GLB
        glb_path = os.path.join(OUTPUT_DIR, "segmented_preview.glb")
        scene.export(glb_path)
        print(f"[SEGMENTED_GLB] Exported {len(scene.geometry)} meshes -> {glb_path}")
        return glb_path

    except Exception as e:
        print(f"[SEGMENTED_GLB] Failed: {e}")
        import traceback

        traceback.print_exc()
        return None


def generate_realtime_glb(cache: dict) -> Optional[str]:
    """Generate a lightweight GLB preview from cached preview data.
    从缓存的预览数据生成轻量级 GLB 预览。

    Called during preview stage so the 3D thumbnail updates immediately
    without waiting for the full 3MF export.

    Args:
        cache (dict): Preview cache dict from generate_preview_cached.

    Returns:
        str: Path to GLB file, or None on failure.
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
            print("[REALTIME_GLB] Preview mesh is None (model too large?)")
            return None

        # Scale from pixel/voxel coords to mm
        mesh_width = preview_mesh.bounds[1][0] - preview_mesh.bounds[0][0]
        pixel_scale = target_width_mm / mesh_width if mesh_width > 0 else 0.42
        transform = np.eye(4)
        transform[0, 0] = pixel_scale
        transform[1, 1] = pixel_scale
        transform[2, 2] = PrinterConfig.LAYER_HEIGHT
        preview_mesh.apply_transform(transform)

        glb_path = os.path.join(OUTPUT_DIR, "realtime_preview.glb")
        preview_mesh.export(glb_path)
        print(f"[REALTIME_GLB] Exported: {glb_path}")
        return glb_path

    except Exception as e:
        print(f"[REALTIME_GLB] Failed: {e}")
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
        - enable_outline (bool): 启用描边
        - outline_width (float): 描边宽度
        - outline_added (bool): 描边是否已添加
        - target_h (int): 图像高度（像素）
        - transform (np.ndarray): 4x4 变换矩阵

    PipelineContext 输出键 / Output keys:
        - glb_path (str | None): GLB 预览文件路径
    """
    matched_rgb = ctx["matched_rgb"]
    mask_solid = ctx["mask_solid"]
    total_layers = ctx["total_layers"]
    backing_color_id = ctx.get("backing_color_id", 0)
    backing_metadata = ctx["backing_metadata"]
    preview_colors = ctx["preview_colors"]
    pixel_scale = ctx["pixel_scale"]
    loop_info = ctx.get("loop_info")
    loop_added = ctx.get("loop_added", False)
    image_path = ctx["image_path"]
    enable_outline = ctx.get("enable_outline", False)
    outline_width = ctx.get("outline_width", 2.0)
    outline_added = ctx.get("outline_added", False)
    target_h = ctx["target_h"]
    transform = ctx["transform"]

    _prog = ctx.get("progress")
    if _prog is not None:
        _prog(0.90, "生成 3D 预览中... | Generating 3D preview...")

    preview_mesh = _create_preview_mesh(
        matched_rgb,
        mask_solid,
        total_layers,
        backing_color_id=backing_color_id,
        backing_z_range=backing_metadata["backing_z_range"],
        preview_colors=preview_colors,
    )

    if preview_mesh:
        preview_mesh.apply_transform(transform)

        if loop_added and loop_info:
            try:
                from core.geometry_utils import create_keychain_loop

                preview_loop = create_keychain_loop(
                    width_mm=loop_info["width_mm"],
                    length_mm=loop_info["length_mm"],
                    hole_dia_mm=loop_info["hole_dia_mm"],
                    thickness_mm=total_layers * PrinterConfig.LAYER_HEIGHT,
                    attach_x_mm=loop_info["attach_x_mm"],
                    attach_y_mm=loop_info["attach_y_mm"],
                    angle_deg=loop_info.get("angle_deg", 0.0),
                )
                if preview_loop:
                    loop_color = preview_colors[loop_info["color_id"]]
                    preview_loop.visual.face_colors = [loop_color] * len(preview_loop.faces)
                    preview_mesh = trimesh.util.concatenate([preview_mesh, preview_loop])
            except Exception as e:
                print(f"[S11] Preview loop failed: {e}")

        # Add outline to preview
        if outline_added:
            try:
                from core.pipeline.s08_auxiliary_meshes import _generate_outline_mesh

                outline_thickness_mm = total_layers * PrinterConfig.LAYER_HEIGHT
                preview_outline = _generate_outline_mesh(
                    mask_solid=mask_solid,
                    pixel_scale=pixel_scale,
                    outline_width_mm=outline_width,
                    outline_thickness_mm=outline_thickness_mm,
                    target_h=target_h,
                )
                if preview_outline:
                    outline_color = preview_colors[0]  # White
                    preview_outline.visual.face_colors = [outline_color] * len(preview_outline.faces)
                    preview_mesh = trimesh.util.concatenate([preview_mesh, preview_outline])
            except Exception as e:
                print(f"[S11] Preview outline failed: {e}")

    glb_path = None
    if preview_mesh:
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        glb_path = os.path.join(OUTPUT_DIR, generate_preview_filename(base_name))
        preview_mesh.export(glb_path)

    ctx["glb_path"] = glb_path

    return ctx
