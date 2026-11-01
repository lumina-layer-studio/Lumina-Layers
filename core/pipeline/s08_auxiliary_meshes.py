"""
S08 — Auxiliary mesh generation (backing, cloisonne wire, free color, loop, coating, outline).
S08 — 附加网格生成（底板、掐丝、自由颜色、挂件环、涂层、描边）。

从 converter.py 搬入的附加网格逻辑：
- 独立底板网格（separate_backing）
- 掐丝珐琅线网格（cloisonne wire）
- 自由颜色网格（free color）
- 挂件环网格（keychain loop）
- 涂层网格（coating）
- 描边网格（outline）
- _generate_outline_mesh / _parse_outline_slot 辅助函数
"""

from api.structured_logging import get_logger
import os
import time

import cv2
import numpy as np
import trimesh
from shapely.affinity import translate

from config import PrinterConfig
from core.geometry_utils import create_keychain_loop
from core.layered_meshing import build_labeled_surface_mesh
from core.mesh_export_parts import (
    copy_mesh_export_part_ranges,
    set_concatenated_mesh_export_part_ranges,
)
from core.pipeline.preview_color_utils import (
    build_material_preview_warning_extra,
    resolve_material_preview,
)

S08_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    OSError,
    RuntimeError,
    cv2.error,
)

_log = get_logger(__name__)

# ========== Helper Functions ==========


def _parse_outline_slot(slot_str: str, num_materials: int) -> int:
    """Parse outline color slot string to material index.
    解析描边颜色槽位字符串为材料索引。

    Args:
        slot_str (str): e.g. "Slot 1", "Slot 2", etc.
        num_materials (int): Total number of materials.

    Returns:
        int: Material index (0-based), clamped to valid range.
    """
    try:
        idx = int(slot_str.replace("Slot ", "")) - 1
        return max(0, min(idx, num_materials - 1))
    except (ValueError, AttributeError):
        return 0


def _dilate_mask_with_outline_padding(
    mask_solid: np.ndarray,
    outline_width_px: int,
) -> tuple[np.ndarray, int]:
    """Dilate a mask without clipping expansion at image boundaries.
    对掩码加边后膨胀，避免图像边界裁掉外扩区域。
    """
    pad = outline_width_px + 1
    mask_uint8 = mask_solid.astype(np.uint8) * 255
    padded_mask = cv2.copyMakeBorder(
        mask_uint8,
        pad,
        pad,
        pad,
        pad,
        cv2.BORDER_CONSTANT,
        value=0,
    )
    kernel = np.ones((3, 3), np.uint8)
    dilated_mask = cv2.dilate(
        padded_mask,
        kernel,
        iterations=outline_width_px,
    )
    return dilated_mask > 0, pad


def _generate_outline_mesh(
    mask_solid: np.ndarray,
    pixel_scale: float,
    outline_width_mm: float,
    outline_thickness_mm: float,
    target_h: int,
) -> trimesh.Trimesh | None:
    """Generate a ring-shaped outline mesh around the outer contour of the model.
    生成模型外轮廓的环形描边网格。

    Algorithm:
    1. Find outer contour of mask_solid using cv2.findContours
    2. Dilate the mask outward by outline_width_mm
    3. Create ring = dilated - original
    4. Extrude the ring to outline_thickness_mm height

    Args:
        mask_solid (np.ndarray): (H, W) boolean mask of solid pixels.
        pixel_scale (float): mm per pixel.
        outline_width_mm (float): Width of the outline in mm.
        outline_thickness_mm (float): Thickness (height) of the outline in mm.
        target_h (int): Image height in pixels.

    Returns:
        trimesh.Trimesh or None: Generated outline mesh, or None if empty.
    """
    # Convert outline width from mm to pixels
    outline_width_px = max(1, int(round(outline_width_mm / pixel_scale)))

    # Convert thickness from mm to layers
    outline_layers = max(1, int(round(outline_thickness_mm / PrinterConfig.LAYER_HEIGHT)))

    _log.debug(
        f"Width: {outline_width_mm}mm = {outline_width_px}px, "
        f"Thickness: {outline_thickness_mm}mm = {outline_layers} layers"
    )

    # Pad before dilation so edge-touching geometry can expand outward.
    dilated_mask, pad = _dilate_mask_with_outline_padding(
        mask_solid,
        outline_width_px,
    )

    # Also pad the original mask for subtraction
    mask_uint8 = mask_solid.astype(np.uint8) * 255
    padded_original = cv2.copyMakeBorder(mask_uint8, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)

    # Ring = dilated minus original (in padded space)
    ring_mask = dilated_mask & ~(padded_original > 0)

    # Use padded dimensions for mesh generation.
    h, w = ring_mask.shape

    if not np.any(ring_mask):
        _log.debug(f"Ring mask is empty, skipping")
        return None

    ring_pixel_count = np.sum(ring_mask)
    _log.debug(f"Ring mask: {ring_pixel_count} pixels")

    layer_volume = np.broadcast_to(
        ring_mask,
        (outline_layers, h, w),
    )
    mesh = build_labeled_surface_mesh(
        layer_volume,
        material_id=True,
        height_px=h,
    )
    if mesh is None:
        return None

    # The canonical builder emits padded pixel-lattice coordinates with a
    # Y-up origin. Scale once into physical millimetres, then remove the same
    # padding offset on both axes to retain the historical model alignment.
    transform = np.eye(4)
    transform[0, 0] = float(pixel_scale)
    transform[1, 1] = float(pixel_scale)
    transform[2, 2] = float(PrinterConfig.LAYER_HEIGHT)
    transform[0, 3] = -float(pad) * float(pixel_scale)
    transform[1, 3] = -float(pad) * float(pixel_scale)
    mesh.apply_transform(transform)

    _log.debug(f"Generated outline mesh: {len(mesh.vertices):,} verts, {len(mesh.faces):,} faces")
    return mesh


def _generate_boundary_fill_mesh(
    mesher,
    boundary_geometry,
    target_h: int,
    target_w: int,
    num_layers: int,
    pad_pixels: int = 0,
) -> trimesh.Trimesh | None:
    """Generate an exact fill mesh from polygonal boundary geometry.
    从 polygon 边界几何生成精确填充网格。
    """
    if boundary_geometry is None or num_layers <= 0:
        return None

    pad_pixels = max(0, int(pad_pixels))
    padded_h = target_h + pad_pixels * 2
    padded_w = target_w + pad_pixels * 2
    shifted_geometry = (
        translate(boundary_geometry, xoff=float(pad_pixels), yoff=float(pad_pixels))
        if pad_pixels > 0
        else boundary_geometry
    )

    fill_matrix = np.zeros((num_layers, padded_h, padded_w), dtype=int)
    mesh = mesher.generate_mesh(
        fill_matrix,
        0,
        padded_h,
        boundary_geometry=shifted_geometry,
        disable_material_dilation=True,
    )
    if mesh is not None and pad_pixels > 0:
        mesh.apply_translation([-float(pad_pixels), -float(pad_pixels), 0.0])
    return mesh


def _coerce_preview_rgba(color) -> list[int]:
    if isinstance(color, (list, tuple, np.ndarray)) and len(color) >= 3:
        try:
            alpha = int(color[3]) if len(color) >= 4 else 255
            return [int(color[0]), int(color[1]), int(color[2]), alpha]
        except (TypeError, ValueError):
            pass
    return [255, 255, 255, 255]


def _resolve_material_archive_base_aux_style(ctx: dict, preview_colors: dict) -> tuple[list[int], str | None]:
    if str(ctx.get("material_source") or "lut") != "material_archive":
        return _coerce_preview_rgba(preview_colors.get(0) or preview_colors.get("0")), None

    try:
        base_idx = int(ctx.get("material_base_channel_idx", 0))
    except (TypeError, ValueError):
        base_idx = 0

    color = preview_colors.get(base_idx)
    if color is None:
        color = preview_colors.get(str(base_idx))
    slot_names = ctx.get("slot_names") or []
    material_name = str(slot_names[base_idx]) if 0 <= base_idx < len(slot_names) else None
    return _coerce_preview_rgba(color), material_name


def _resolve_loop_material_style(
    ctx: dict,
    loop_info: dict,
) -> tuple[list[int], str]:
    """Resolve the loop style while preserving S05 material identity.
    解析挂环样式，同时保留 S05 已确定的材料身份。

    Args:
        ctx: Pipeline context containing authoritative palette metadata.
            包含权威调色板元数据的管线上下文。
        loop_info: Loop metadata produced by S05 or a legacy direct caller.
            由 S05 或旧式直接调用方生成的挂环元数据。

    Returns:
        tuple[list[int], str]: Resolved RGBA and authoritative material name.
            解析后的 RGBA 与权威材料名。

    Raises:
        ValueError: If material identity or preview color cannot be resolved.
            材料身份或预览颜色无法解析时抛出。
    """

    material_id = loop_info.get("color_id")
    slot_names = ctx.get("slot_names")
    color_conf = ctx.get("color_conf") or {}

    carried_rgba = loop_info.get("color_rgba")
    carried_name = loop_info.get("material_name")
    if carried_rgba is not None and carried_name is not None:
        carried_resolution = resolve_material_preview(
            material_id=material_id,
            slot_names=slot_names,
            preview_colors={material_id: carried_rgba},
            color_conf={},
        )
        if (
            carried_resolution.is_resolved
            and carried_resolution.material_name == str(carried_name)
        ):
            return list(carried_resolution.rgba), carried_resolution.material_name

    preview_colors = ctx.get("preview_colors")
    resolution = resolve_material_preview(
        material_id=material_id,
        slot_names=slot_names,
        preview_colors=preview_colors,
        color_conf=color_conf,
    )
    if not resolution.is_resolved:
        _log.warning(
            "Loop material preview metadata is unresolved",
            extra=build_material_preview_warning_extra(
                resolution,
                slot_names=slot_names,
                preview_colors=preview_colors,
                color_conf=color_conf,
                material_source=ctx.get("material_source", "lut"),
            ),
        )
        raise ValueError(
            "Loop material identity or preview color is unavailable"
        )

    loop_info["material_name"] = resolution.material_name
    loop_info["color_rgba"] = list(resolution.rgba)
    loop_info["color_source"] = resolution.source
    return list(resolution.rgba), resolution.material_name


def run(ctx: dict) -> dict:
    """Generate auxiliary meshes: backing, wire, free color, loop, coating, outline.
    生成附加网格：底板、掐丝、自由颜色、挂件环、涂层、描边。

    PipelineContext 输入键 / Input keys:
        - scene (trimesh.Scene): 当前 3D 场景
        - valid_slot_names (list[str]): 已有的有效槽位名称
        - full_matrix (np.ndarray): (Z, H, W) signed material label planes.
        - voxel_z_edges (np.ndarray | None): Z+1 logical boundaries belonging
          only to full_matrix, not independent coating or outline volumes.
        - mask_solid (np.ndarray): (H, W) bool 实体掩码
        - matched_rgb (np.ndarray): (H, W, 3) 匹配后的 RGB
        - target_h (int): 图像高度（像素）
        - target_w (int): 图像宽度（像素）
        - pixel_scale (float): mm/px 缩放因子
        - total_layers (int): 总层数
        - preview_colors (dict): 材料预览颜色
        - transform (np.ndarray): 4x4 变换矩阵
        - mesher: 网格生成器实例
        - separate_backing (bool): 是否分离底板
        - enable_cloisonne (bool): 启用掐丝珐琅
        - backing_metadata (dict): 底板元数据
        - enable_coating (bool): 启用涂层
        - coating_height_mm (float): 涂层高度
        - enable_outline (bool): 启用描边
        - outline_width (float): 描边宽度
        - structure_mode (str): 单面或双面结构模式
        - free_color_set (set | None): 自由颜色集合
        - add_loop (bool): 添加挂件环
        - loop_info (dict | None): 挂件环信息

    PipelineContext 输出键 / Output keys:
        - scene (trimesh.Scene): 更新后的 3D 场景
        - valid_slot_names (list[str]): 更新后的有效槽位名称
        - loop_added (bool): 挂件环是否成功添加
        - outline_added (bool): 描边是否成功添加
    """
    _t0 = time.perf_counter()

    scene = ctx["scene"]
    valid_slot_names = ctx["valid_slot_names"]
    full_matrix = ctx["full_matrix"]
    volume_kwargs = (
        {"z_edges": ctx["voxel_z_edges"]} if ctx.get("voxel_z_edges") is not None else {}
    )
    mask_solid = ctx["mask_solid"]
    matched_rgb = ctx["matched_rgb"]
    target_h = ctx["target_h"]
    target_w = ctx.get("target_w", mask_solid.shape[1])
    pixel_scale = ctx["pixel_scale"]
    total_layers = ctx["total_layers"]
    preview_colors = ctx["preview_colors"]
    transform = ctx["transform"]
    mesher = ctx["mesher"]
    separate_backing = ctx.get("separate_backing", False)
    separate_backing_color_id = ctx.get(
        "separate_backing_color_id",
        ctx.get("backing_color_id", 0),
    )
    enable_cloisonne = ctx.get("enable_cloisonne", False)
    backing_metadata = ctx["backing_metadata"]
    enable_coating = ctx.get("enable_coating", False)
    coating_height_mm = ctx.get("coating_height_mm", 0.08)
    enable_outline = ctx.get("enable_outline", False)
    outline_width = ctx.get("outline_width", 2.0)
    structure_mode_text = str(ctx.get("structure_mode", "") or "")
    is_double_sided = "双面" in structure_mode_text or "Double" in structure_mode_text
    free_color_set = ctx.get("free_color_set")
    add_loop = ctx.get("add_loop", False)
    loop_info = ctx.get("loop_info")
    boundary_geometry = ctx.get("boundary_geometry")
    boundary_coating_geometry = boundary_geometry
    boundary_outline_geometry = None
    boundary_pad_pixels = 0
    if boundary_geometry is not None and enable_outline:
        boundary_outline_width_px = max(
            1,
            int(round(outline_width / max(pixel_scale, 1e-9))),
        )
        boundary_coating_geometry = boundary_geometry.buffer(
            float(boundary_outline_width_px)
        )
        boundary_outline_geometry = boundary_coating_geometry.difference(
            boundary_geometry
        )
        boundary_pad_pixels = boundary_outline_width_px + 1

    loop_added = False
    outline_added = False
    base_aux_color, base_aux_material_name = _resolve_material_archive_base_aux_style(ctx, preview_colors)
    has_explicit_backing_color = (
        "separate_backing_color_id" in ctx
        and ctx.get("separate_backing_color_id") != ctx.get("material_base_channel_idx")
    )
    if separate_backing and (
        str(ctx.get("material_source") or "lut") != "material_archive" or has_explicit_backing_color
    ):
        try:
            separate_backing_color_idx = int(separate_backing_color_id)
        except (TypeError, ValueError):
            separate_backing_color_idx = 0
        separate_backing_color = preview_colors.get(separate_backing_color_idx)
        if separate_backing_color is None:
            separate_backing_color = preview_colors.get(str(separate_backing_color_idx))
        if separate_backing_color is not None:
            base_aux_color = _coerce_preview_rgba(separate_backing_color)
        slot_names = ctx.get("slot_names") or []
        if 0 <= separate_backing_color_idx < len(slot_names):
            base_aux_material_name = str(slot_names[separate_backing_color_idx])

    # ========== Separate Backing Mesh ==========
    if separate_backing:
        _s08_t_backing = time.perf_counter()
        _log.debug(f"Attempting to generate separate backing mesh (mat_id=-2)...")
        try:
            backing_mesh = mesher.generate_mesh(full_matrix, mat_id=-2, height_px=target_h, **volume_kwargs)

            _log.debug(f"Backing mesh result: {backing_mesh}")
            if backing_mesh is not None:
                _log.debug(f"Backing mesh vertices: {len(backing_mesh.vertices)}")

            if backing_mesh is None or len(backing_mesh.vertices) == 0:
                _log.warning("Backing mesh is empty, skipping separate backing object")
                _log.debug(f"Continuing with other material meshes...")
            else:
                backing_mesh.apply_transform(transform)

                backing_name = "Backing"
                backing_mesh.visual.face_colors = base_aux_color
                backing_mesh.metadata["name"] = backing_name
                backing_mesh.metadata["lumina_print_role"] = "backing"
                if base_aux_material_name:
                    backing_mesh.metadata["bambu_material_name"] = base_aux_material_name
                preview_colors[backing_name] = base_aux_color
                scene.add_geometry(backing_mesh, node_name=backing_name, geom_name=backing_name)
                valid_slot_names.append(backing_name)
                _log.debug(
                    "Added backing mesh as separate object",
                    extra={
                        "event": "s08_separate_backing_mesh_added",
                        "separate_backing_color_id": separate_backing_color_id,
                    },
                )
                _log.debug(f"Scene now has {len(scene.geometry)} geometries")
        except S08_HANDLED_ERRORS as e:
            _log.exception(f"Error generating backing mesh: {e}")
            _log.debug(f"Continuing with other material meshes...")
    else:
        _log.debug(f"Backing merged with first layer (original behavior)")
    if separate_backing:
        _log.debug(f"backing: {time.perf_counter() - _s08_t_backing:.3f}s")

    # ========== Cloisonné Wire Mesh ==========
    if enable_cloisonne and backing_metadata.get("is_cloisonne"):
        _s08_t_wire = time.perf_counter()
        _log.debug(f"Generating cloisonné wire mesh (mat_id=-3)...")
        try:
            wire_mesh = mesher.generate_mesh(full_matrix, mat_id=-3, height_px=target_h, **volume_kwargs)
            if wire_mesh is not None and len(wire_mesh.vertices) > 0:
                wire_mesh.apply_transform(transform)
                wire_mesh.visual.face_colors = [218, 165, 32, 255]  # Gold colour
                wire_name = "Wire"
                wire_mesh.metadata["name"] = wire_name
                scene.add_geometry(wire_mesh, node_name=wire_name, geom_name=wire_name)
                valid_slot_names.append(wire_name)
                _log.debug(f"Added wire mesh as standalone object ({len(wire_mesh.vertices)} verts)")
            else:
                _log.warning("Wire mesh is empty, skipping")
        except S08_HANDLED_ERRORS as e:
            _log.exception(f"Error generating wire mesh: {e}")
        _log.debug(f"wire: {time.perf_counter() - _s08_t_wire:.3f}s")

    # ========== Free Color Mesh Extraction ==========
    if free_color_set:
        _s08_t_free = time.perf_counter()
        _free_set = {c.lower() for c in free_color_set if c}
        if _free_set:
            _log.debug(f"Free Color mode: {len(_free_set)} colors marked")
            for hex_c in sorted(_free_set):
                try:
                    # Parse hex to RGB
                    r_fc = int(hex_c[1:3], 16)
                    g_fc = int(hex_c[3:5], 16)
                    b_fc = int(hex_c[5:7], 16)
                    # Build mask for this color in matched_rgb
                    color_mask = (
                        (matched_rgb[:, :, 0] == r_fc)
                        & (matched_rgb[:, :, 1] == g_fc)
                        & (matched_rgb[:, :, 2] == b_fc)
                        & mask_solid
                    )
                    if not np.any(color_mask):
                        _log.debug(f"{hex_c}: no pixels found, skipping")
                        continue
                    # Build a sub-voxel matrix: keep only this color's voxels
                    fc_matrix = np.where(
                        np.broadcast_to(color_mask[np.newaxis, :, :], full_matrix.shape), full_matrix, -1
                    )
                    # Replace all non-air values with a single ID (0) for meshing
                    fc_matrix = np.where(fc_matrix >= 0, 0, -1)
                    fc_mesh = mesher.generate_mesh(fc_matrix, 0, target_h, **volume_kwargs)
                    if fc_mesh and len(fc_mesh.vertices) > 0:
                        fc_mesh.apply_transform(transform)
                        fc_mesh.visual.face_colors = [r_fc, g_fc, b_fc, 255]
                        fc_name = f"Free_{hex_c[1:]}"
                        fc_mesh.metadata["name"] = fc_name
                        scene.add_geometry(fc_mesh, node_name=fc_name, geom_name=fc_name)
                        valid_slot_names.append(fc_name)
                        _log.debug(f"{hex_c} -> standalone object '{fc_name}' ({np.sum(color_mask)} px)")
                    else:
                        _log.debug(f"{hex_c}: mesh empty, skipping")
                except S08_HANDLED_ERRORS as e:
                    _log.exception(f"Error extracting free color {hex_c}: {e}")
        _log.debug(f"free_color: {time.perf_counter() - _s08_t_free:.3f}s")

    # ========== Keychain Loop ==========
    if add_loop and loop_info is not None:
        _s08_t_loop = time.perf_counter()
        loop_color_rgba, loop_material_name = _resolve_loop_material_style(
            ctx,
            loop_info,
        )
        loop_preview_color_added = False
        try:
            loop_thickness = total_layers * PrinterConfig.LAYER_HEIGHT
            loop_mesh = create_keychain_loop(
                width_mm=loop_info["width_mm"],
                length_mm=loop_info["length_mm"],
                hole_dia_mm=loop_info["hole_dia_mm"],
                thickness_mm=loop_thickness,
                attach_x_mm=loop_info["attach_x_mm"],
                attach_y_mm=loop_info["attach_y_mm"],
                angle_deg=loop_info.get("angle_deg", 0.0),
            )

            if loop_mesh is None or len(loop_mesh.vertices) == 0:
                raise RuntimeError("Keychain loop geometry is empty")

            loop_mesh.visual.face_colors = loop_color_rgba
            loop_mesh.metadata["name"] = "Keychain_Loop"
            loop_mesh.metadata["bambu_material_name"] = loop_material_name
            if "Keychain_Loop" not in preview_colors:
                preview_colors["Keychain_Loop"] = list(loop_color_rgba)
                loop_preview_color_added = True
            scene.add_geometry(
                loop_mesh,
                node_name="Keychain_Loop",
                geom_name="Keychain_Loop",
            )
            valid_slot_names.append("Keychain_Loop")
            loop_added = True
            _log.debug("Loop added successfully")
        except S08_HANDLED_ERRORS as exc:
            if loop_preview_color_added:
                preview_colors.pop("Keychain_Loop", None)
            _log.warning(
                "Loop creation failed; continuing without loop",
                extra={
                    "event": "s08_keychain_loop_creation_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "material_id": int(loop_info.get("color_id", -1)),
                },
            )
        _log.debug(f"loop: {time.perf_counter() - _s08_t_loop:.3f}s")

    # ========== Coating Mesh ==========
    if enable_coating:
        _s08_t_coating = time.perf_counter()
        try:
            coating_layers = max(1, int(round(coating_height_mm / PrinterConfig.LAYER_HEIGHT)))
            _log.debug(f"Generating coating: height={coating_height_mm}mm ({coating_layers} layers), bottom side")
            coating_pad_px = 0
            if boundary_geometry is not None:
                coating_mesh = _generate_boundary_fill_mesh(
                    mesher=mesher,
                    boundary_geometry=boundary_coating_geometry,
                    target_h=target_h,
                    target_w=target_w,
                    num_layers=coating_layers,
                    pad_pixels=boundary_pad_pixels,
                )
            else:
                # Determine coating coverage area
                coating_mask = mask_solid.copy()

                # If outline is enabled, extend coating to cover outline area as well
                if enable_outline:
                    _log.debug(f"Extending coating to cover outline area (width={outline_width}mm)")
                    outline_width_px = max(1, int(round(outline_width / pixel_scale)))
                    coating_mask, coating_pad_px = _dilate_mask_with_outline_padding(
                        mask_solid,
                        outline_width_px,
                    )

                # Build a small voxel matrix for the coating
                coating_matrix = np.full(
                    (coating_layers, *coating_mask.shape),
                    -1,
                    dtype=int,
                )
                coating_slice = np.where(coating_mask, 0, -1).astype(int)
                coating_matrix[:] = coating_slice[np.newaxis, :, :]

                coating_mesh = mesher.generate_mesh(
                    coating_matrix,
                    0,
                    coating_mask.shape[0],
                )
            if coating_mesh and len(coating_mesh.vertices) > 0:
                # Transform XY same as model, Z same layer height
                coat_transform = np.eye(4)
                coat_transform[0, 0] = pixel_scale
                coat_transform[1, 1] = pixel_scale
                coat_transform[2, 2] = PrinterConfig.LAYER_HEIGHT
                coat_transform[0, 3] = -coating_pad_px * pixel_scale
                coat_transform[1, 3] = -coating_pad_px * pixel_scale
                # Shift down so coating sits below the model (Z < 0)
                coat_transform[2, 3] = -coating_layers * PrinterConfig.LAYER_HEIGHT
                coating_mesh.apply_transform(coat_transform)
                if is_double_sided:
                    top_coating_mesh = coating_mesh.copy()
                    copy_mesh_export_part_ranges(
                        coating_mesh,
                        top_coating_mesh,
                    )
                    top_coating_mesh.apply_translation(
                        [
                            0.0,
                            0.0,
                            (total_layers + coating_layers) * PrinterConfig.LAYER_HEIGHT,
                        ]
                    )
                    coating_sources = [coating_mesh, top_coating_mesh]
                    coating_mesh = trimesh.util.concatenate(coating_sources)
                    set_concatenated_mesh_export_part_ranges(
                        coating_mesh,
                        coating_sources,
                    )
                coating_material = ctx["resolved_coating_material"]
                coating_mesh.visual.face_colors = [*coating_material.rgb, 255]
                coating_name = "Coating"
                coating_mesh.metadata["name"] = coating_name
                coating_mesh.metadata["bambu_material_name"] = coating_material.name
                scene.add_geometry(coating_mesh, node_name=coating_name, geom_name=coating_name)
                valid_slot_names.append(coating_name)
                _log.debug(f"Coating added as standalone '{coating_name}' ({coating_layers} layers)")
            else:
                _log.warning("Coating mesh empty, skipping")
        except S08_HANDLED_ERRORS as e:
            _log.exception(f"Coating generation failed: {e}")
        _log.debug(f"coating: {time.perf_counter() - _s08_t_coating:.3f}s")

    # ========== Outline Mesh ==========
    if enable_outline:
        _s08_t_outline = time.perf_counter()
        try:
            outline_thickness_mm = total_layers * PrinterConfig.LAYER_HEIGHT
            outline_z_offset = 0.0
            # Coating owns the negative-Z interval; the outline starts at its
            # upper surface, so different materials never occupy that volume.

            _log.debug(
                f"Generating outline: width={outline_width}mm, "
                f"thickness={outline_thickness_mm}mm (z_offset={outline_z_offset}mm)"
            )
            if boundary_geometry is not None:
                outline_layers = max(1, int(round(outline_thickness_mm / PrinterConfig.LAYER_HEIGHT)))
                outline_mesh = _generate_boundary_fill_mesh(
                    mesher=mesher,
                    boundary_geometry=boundary_outline_geometry,
                    target_h=target_h,
                    target_w=target_w,
                    num_layers=outline_layers,
                    pad_pixels=boundary_pad_pixels,
                )
            else:
                outline_mesh = _generate_outline_mesh(
                    mask_solid=mask_solid,
                    pixel_scale=pixel_scale,
                    outline_width_mm=outline_width,
                    outline_thickness_mm=outline_thickness_mm,
                    target_h=target_h,
                )

            if outline_mesh is not None:
                if boundary_geometry is not None:
                    outline_transform = np.eye(4)
                    outline_transform[0, 0] = pixel_scale
                    outline_transform[1, 1] = pixel_scale
                    outline_transform[2, 2] = PrinterConfig.LAYER_HEIGHT
                    outline_mesh.apply_transform(outline_transform)
                # Shift outline down if coating is enabled
                if outline_z_offset != 0.0:
                    outline_mesh.vertices[:, 2] += outline_z_offset
                outline_name = "Outline"
                outline_mesh.visual.face_colors = base_aux_color
                outline_mesh.metadata["name"] = outline_name
                if base_aux_material_name:
                    outline_mesh.metadata["bambu_material_name"] = base_aux_material_name
                preview_colors[outline_name] = base_aux_color
                scene.add_geometry(outline_mesh, node_name=outline_name, geom_name=outline_name)
                if ctx.get("batch_preview", False):
                    # Capture image-space geometry before S09 mirrors and
                    # centres the print scene. Quick previews keep using the
                    # interactive frontend outline instead.
                    ctx["preview_outline_mesh"] = outline_mesh.copy()
                valid_slot_names.append(outline_name)
                _log.debug(f"Outline added as standalone '{outline_name}' object")
                outline_added = True
            else:
                _log.warning("Outline mesh is empty, skipping")
        except S08_HANDLED_ERRORS as e:
            _log.exception(f"Outline generation failed: {e}")
        _log.debug(f"outline: {time.perf_counter() - _s08_t_outline:.3f}s")

    ctx["scene"] = scene
    ctx["valid_slot_names"] = valid_slot_names
    ctx["loop_added"] = loop_added
    ctx["outline_added"] = outline_added

    _elapsed = time.perf_counter() - _t0
    _log.debug(f"aux_meshes done: {_elapsed:.3f}s")
    ctx.setdefault("_hifi_timings", {})["aux_meshes_s"] = _elapsed

    return ctx
