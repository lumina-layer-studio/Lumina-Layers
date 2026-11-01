"""
S06 — Voxel matrix building (5 modes).
S06 — 体素矩阵构建（5 种模式）。

从 converter.py 搬入的体素构建函数：
- _normalize_color_height_map: hex 键归一化
- _build_voxel_matrix: 标准体素矩阵（双面/单面）
- _build_voxel_matrix_6layer: 6 层体素矩阵（5-Color Extended）
- _build_voxel_matrix_faceup: 面朝上体素矩阵（5-Color Extended）
- _build_relief_voxel_matrix: 2.5D 浮雕体素矩阵
- _build_cloisonne_voxel_matrix: 掐丝珐琅体素矩阵
"""

from api.structured_logging import get_logger
import time
import numpy as np

from config import PrinterConfig, get_source_kind

_log = get_logger(__name__)


def _update_bambu_base_layer_ctx_from_voxels(
    ctx: dict,
    *,
    color_mode: str,
    structure_mode: str,
    num_layers: int,
    thickness_mm: float,
    face_orientation_override: str | None = None,
) -> None:
    """Populate Bambu base-layer modifier values from voxel-stage inputs.
    根据体素阶段输入填充 Bambu 底板粗层高相关上下文值。

    Args:
        ctx (dict): Pipeline context updated in place.
            （就地更新的流水线上下文字典）
        color_mode (str): Effective color mode for the current build.
            （当前构建使用的颜色模式）
        structure_mode (str): Effective structure mode after stage-level normalization.
            （阶段归一化后的结构模式）
        num_layers (int): Optical color-layer count before backing is added.
            （添加底板前的彩色光学层层数）
        thickness_mm (float): Requested or quantized backing thickness in millimetres.
            （请求值或量化后的底板厚度，单位毫米）
    """
    layer_h = PrinterConfig.LAYER_HEIGHT
    backing_layer_count = max(1, int(round(float(thickness_mm) / layer_h)))
    base_height_mm = backing_layer_count * layer_h
    coating_layers = 0
    if bool(ctx.get("enable_coating", False)):
        try:
            coating_height_mm = float(ctx.get("coating_height_mm", layer_h))
        except (TypeError, ValueError):
            coating_height_mm = layer_h
        if np.isfinite(coating_height_mm) and coating_height_mm > 0:
            coating_layers = max(1, int(round(coating_height_mm / layer_h)))
    color_height_mm = (max(0, int(num_layers)) + coating_layers) * layer_h

    structure_mode_text = str(structure_mode or "")
    color_mode_text = str(color_mode or "")
    is_double = "双面" in structure_mode_text or "Double" in structure_mode_text
    is_5color = "5-Color Extended" in color_mode_text

    if face_orientation_override in {"up", "down", "double"}:
        face_orientation = face_orientation_override
    elif is_double:
        face_orientation = "double"
    elif is_5color:
        face_orientation = "up"
    else:
        face_orientation = "down"

    ctx["bambu_base_height_mm"] = float(base_height_mm)
    ctx["bambu_color_height_mm"] = float(color_height_mm)
    ctx["bambu_face_orientation"] = face_orientation
    ctx["enable_base_layer_height_modifier"] = bool(
        ctx.get("enable_base_layer_height_modifier", True)
    ) and not bool(ctx.get("enable_relief", False))


def _normalize_color_height_map(color_height_map: dict[str, float]) -> dict[str, float]:
    """Normalize hex keys to '#rrggbb' format.
    将 hex 键归一化为 '#rrggbb' 格式。

    Args:
        color_height_map (dict[str, float]): Mapping of hex color keys to height values.
            Keys may or may not have '#' prefix. (颜色到高度的映射，键可能带或不带 '#' 前缀)

    Returns:
        dict[str, float]: New dict with all keys normalized to '#rrggbb' format.
            (所有键归一化为 '#rrggbb' 格式的新字典)
    """
    normalized = {}
    for key, value in color_height_map.items():
        if not key.startswith("#"):
            normalized[f"#{key}"] = value
        else:
            normalized[key] = value
    return normalized


def _mask_solid_bounds_mm(mask_solid: np.ndarray, pixel_scale: float) -> tuple[float, float, float, float] | None:
    """Return solid silhouette bounds in model-space millimeters."""
    if pixel_scale <= 0:
        return None

    solid_rows = np.any(mask_solid, axis=1)
    solid_cols = np.any(mask_solid, axis=0)
    if not np.any(solid_rows) or not np.any(solid_cols):
        return None

    row_indices = np.where(solid_rows)[0]
    col_indices = np.where(solid_cols)[0]
    min_row = int(row_indices[0])
    max_row = int(row_indices[-1])
    min_col = int(col_indices[0])
    max_col = int(col_indices[-1])
    target_h = mask_solid.shape[0]

    min_x_mm = min_col * pixel_scale
    max_x_mm = (max_col + 1) * pixel_scale
    min_y_mm = (target_h - (max_row + 1)) * pixel_scale
    max_y_mm = (target_h - min_row) * pixel_scale
    return (min_x_mm, min_y_mm, max_x_mm, max_y_mm)


def _convert_centered_fridge_coords_to_raw_mm(
    mask_solid: np.ndarray,
    pixel_scale: float,
    center_x_mm: float,
    center_y_mm: float,
) -> tuple[float, float]:
    """Convert centered preview-space magnet coordinates to raw model-space mm."""
    bounds = _mask_solid_bounds_mm(mask_solid, pixel_scale)
    if bounds is None:
        target_h, target_w = mask_solid.shape
        center_raw_x = (target_w / 2.0) * pixel_scale
        center_raw_y = (target_h / 2.0) * pixel_scale
    else:
        min_x_mm, min_y_mm, max_x_mm, max_y_mm = bounds
        center_raw_x = (min_x_mm + max_x_mm) / 2.0
        center_raw_y = (min_y_mm + max_y_mm) / 2.0

    return (center_raw_x + float(center_x_mm), center_raw_y + float(center_y_mm))


def _build_fridge_magnet_footprint_mask(mask_solid: np.ndarray, pixel_scale: float, magnet: dict) -> np.ndarray:
    """Build a 2D raster mask for a fridge-magnet cavity footprint."""
    target_h, target_w = mask_solid.shape
    footprint_mask = np.zeros((target_h, target_w), dtype=bool)
    if pixel_scale <= 0:
        return footprint_mask

    center_raw_x, center_raw_y = _convert_centered_fridge_coords_to_raw_mm(
        mask_solid,
        pixel_scale,
        float(magnet.get("center_x_mm", 0.0) or 0.0),
        float(magnet.get("center_y_mm", 0.0) or 0.0),
    )

    xs_mm = (np.arange(target_w, dtype=np.float64) + 0.5) * pixel_scale
    ys_mm = (target_h - np.arange(target_h, dtype=np.float64) - 0.5) * pixel_scale
    grid_x_mm, grid_y_mm = np.meshgrid(xs_mm, ys_mm)

    shape = str(magnet.get("shape", "") or "").lower()
    if shape == "round":
        diameter_mm = float(magnet.get("diameter_mm") or 0.0)
        if diameter_mm <= 0:
            return footprint_mask
        radius_mm = diameter_mm / 2.0
        footprint_mask = (grid_x_mm - center_raw_x) ** 2 + (grid_y_mm - center_raw_y) ** 2 <= radius_mm**2 + 1e-12
    elif shape == "rect":
        width_mm = float(magnet.get("width_mm") or 0.0)
        height_mm = float(magnet.get("height_mm") or 0.0)
        if width_mm <= 0 or height_mm <= 0:
            return footprint_mask
        half_width_mm = width_mm / 2.0
        half_height_mm = height_mm / 2.0
        footprint_mask = (
            (np.abs(grid_x_mm - center_raw_x) <= half_width_mm + 1e-9)
            & (np.abs(grid_y_mm - center_raw_y) <= half_height_mm + 1e-9)
        )

    return footprint_mask & mask_solid


def _resolve_fridge_cavity_z_range(
    backing_z_range: tuple[int, int],
    shell_layers: int,
    cavity_layers: int,
) -> tuple[int, int] | None:
    """Resolve the blind cavity Z range inside the backing block."""
    backing_z_start, backing_z_end = backing_z_range
    if cavity_layers <= 0 or shell_layers <= 0:
        return None

    backing_layer_count = backing_z_end - backing_z_start + 1
    if backing_layer_count <= 0 or shell_layers + cavity_layers > backing_layer_count:
        return None

    if backing_z_start == 0:
        cavity_z_start = backing_z_start + shell_layers
        cavity_z_end = cavity_z_start + cavity_layers - 1
    else:
        cavity_z_end = backing_z_end - shell_layers
        cavity_z_start = cavity_z_end - cavity_layers + 1

    if cavity_z_start < backing_z_start or cavity_z_end > backing_z_end:
        return None
    return (cavity_z_start, cavity_z_end)


def _resolve_min_fridge_spacer_thick(fridge_magnets: list[dict] | None) -> float:
    """Return the minimum backing thickness required after layer quantization."""
    if not fridge_magnets:
        return 0.0

    shell_layers = max(1, int(round(0.4 / PrinterConfig.LAYER_HEIGHT)))
    required_layers = shell_layers
    for magnet in fridge_magnets:
        thickness_mm = float(magnet.get("thickness_mm") or 0.0)
        if thickness_mm <= 0:
            continue
        cavity_layers = max(1, int(round(thickness_mm / PrinterConfig.LAYER_HEIGHT)))
        required_layers = max(required_layers, shell_layers + cavity_layers)

    return required_layers * PrinterConfig.LAYER_HEIGHT


def _build_uniform_backing_z_maps(
    mask_solid: np.ndarray,
    backing_z_start: int,
    backing_z_end: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build per-pixel backing Z bounds for uniform-thickness backing."""
    backing_z_min_map = np.full(mask_solid.shape, -1, dtype=int)
    backing_z_max_map = np.full(mask_solid.shape, -1, dtype=int)
    if backing_z_end < backing_z_start:
        return backing_z_min_map, backing_z_max_map

    backing_z_min_map[mask_solid] = backing_z_start
    backing_z_max_map[mask_solid] = backing_z_end
    return backing_z_min_map, backing_z_max_map


def _carve_fridge_magnet_cavities(
    full_matrix: np.ndarray,
    mask_solid: np.ndarray,
    pixel_scale: float,
    backing_metadata: dict,
    fridge_magnets: list[dict] | None,
) -> np.ndarray:
    """Carve blind fridge-magnet cavities into backing voxels only."""
    if not fridge_magnets:
        return full_matrix

    shell_layers = max(1, int(round(0.4 / PrinterConfig.LAYER_HEIGHT)))
    backing_z_min_map = backing_metadata.get("backing_z_min_map")
    backing_z_max_map = backing_metadata.get("backing_z_max_map")
    if backing_z_min_map is None or backing_z_max_map is None:
        backing_z_min_map, backing_z_max_map = _build_uniform_backing_z_maps(
            mask_solid,
            int(backing_metadata["backing_z_range"][0]),
            int(backing_metadata["backing_z_range"][1]),
        )

    for magnet in fridge_magnets:
        thickness_mm = float(magnet.get("thickness_mm") or 0.0)
        cavity_layers = max(1, int(round(thickness_mm / PrinterConfig.LAYER_HEIGHT)))
        cavity_z_range = _resolve_fridge_cavity_z_range(
            backing_metadata["backing_z_range"],
            shell_layers,
            cavity_layers,
        )
        if cavity_z_range is None:
            continue

        footprint_mask = _build_fridge_magnet_footprint_mask(mask_solid, pixel_scale, magnet)
        if not np.any(footprint_mask):
            continue

        cavity_z_start, cavity_z_end = cavity_z_range
        backing_slice = full_matrix[cavity_z_start : cavity_z_end + 1]
        z_indices = np.arange(cavity_z_start, cavity_z_end + 1, dtype=int)[:, np.newaxis, np.newaxis]
        carve_mask = (
            footprint_mask[np.newaxis, :, :]
            & (backing_z_min_map[np.newaxis, :, :] >= 0)
            & (z_indices >= backing_z_min_map[np.newaxis, :, :])
            & (z_indices <= backing_z_max_map[np.newaxis, :, :])
        )
        full_matrix[cavity_z_start : cavity_z_end + 1] = np.where(
            carve_mask,
            -1,
            backing_slice,
        )

    return full_matrix


def _resolve_generation_backing_color_id(
    backing_color_id: int,
    lut_metadata,
) -> int:
    """Resolve the backing fill id for actual generation.
    解析实际生成时使用的底板填充编号。
    """
    # Negative labels reserve a separate mesh; its material is assigned at export.
    if backing_color_id < 0 or lut_metadata is None:
        return int(backing_color_id)

    if get_source_kind(lut_metadata) == "legacy_lookup":
        return int(backing_color_id)

    base_channel_idx = int(getattr(lut_metadata, "base_channel_idx", backing_color_id))
    if base_channel_idx >= 0:
        return base_channel_idx

    _log.warning(
        "Invalid metadata base_channel_idx=%s for generation, falling back to backing_color_id=%s",
        base_channel_idx,
        backing_color_id,
    )
    return int(backing_color_id)


def _normalize_backing_mask(backing_mask, mask_solid: np.ndarray) -> np.ndarray | None:
    """Return a validated backing footprint mask, or None when unavailable."""
    if backing_mask is None:
        return None
    backing_arr = np.asarray(backing_mask, dtype=bool)
    if backing_arr.shape != mask_solid.shape:
        raise ValueError(
            f"backing_mask shape {backing_arr.shape} does not match mask_solid shape {mask_solid.shape}"
        )
    return backing_arr


def _resolve_flat_backing_mask(ctx: dict, mask_solid: np.ndarray) -> np.ndarray:
    """Resolve the 2D backing footprint for flat raster voxel builds."""
    explicit_backing_mask = _normalize_backing_mask(ctx.get("backing_mask"), mask_solid)
    if explicit_backing_mask is not None:
        return explicit_backing_mask

    return mask_solid


def _build_voxel_matrix(
    material_matrix,
    mask_solid,
    spacer_thick,
    structure_mode,
    backing_color_id=0,
    backing_mask=None,
    *,
    compact_backing: bool = False,
):
    """Build complete voxel matrix with backing layer marked using special material_id.
    构建带底板标记的完整体素矩阵。

    Args:
        material_matrix (np.ndarray): (H, W, N) material matrix (N optical layers)
            (材料矩阵，N 个光学层)
        mask_solid (np.ndarray): (H, W) solid pixel mask (实体像素掩码)
        spacer_thick (float): backing thickness (mm) (底板厚度)
        structure_mode (str): "双面" or "单面" (Double-sided or Single-sided)
        backing_color_id (int): backing material ID (0-7), default is 0 (White)
        backing_mask (np.ndarray | None): Optional 2D backing footprint mask.
        compact_backing (bool): Store a uniform backing as one label plane.
            Metadata then supplies voxel_z_edges in original layer coordinates;
            backing_z_range and the per-pixel maps retain logical layer indices.

    Returns:
        tuple: (full_matrix, backing_metadata)
            - full_matrix: (Z, H, W) voxel matrix
            - backing_metadata: dict with keys:
                - 'backing_color_id': int
                - 'backing_z_range': tuple (start_z, end_z)
    """
    if material_matrix.ndim != 3:
        raise ValueError(f"material_matrix must be 3D (H, W, N), got shape={material_matrix.shape}")
    target_h, target_w, optical_layers = material_matrix.shape
    backing_mask_arr = _normalize_backing_mask(backing_mask, mask_solid)
    if backing_mask_arr is None:
        backing_mask_arr = mask_solid

    bottom_voxels = np.transpose(material_matrix, (2, 0, 1))

    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))
    stored_spacer_layers = 1 if compact_backing else spacer_layers
    label_dtype = (
        np.result_type(material_matrix.dtype, np.min_scalar_type(backing_color_id), np.int8)
        if compact_backing and material_matrix.dtype.kind == "i" else np.dtype(int)
    )

    if "双面" in structure_mode or "Double" in structure_mode:
        top_voxels = np.transpose(material_matrix[..., ::-1], (2, 0, 1))
        total_layers = optical_layers + spacer_layers + optical_layers
        stored_layers = optical_layers * 2 + stored_spacer_layers
        full_matrix = np.full((stored_layers, target_h, target_w), -1, dtype=label_dtype)

        full_matrix[0:optical_layers] = bottom_voxels

        # Use backing_color_id parameter to mark backing layer
        spacer = np.full((target_h, target_w), -1, dtype=int)
        spacer[backing_mask_arr] = backing_color_id
        for z in range(optical_layers, optical_layers + stored_spacer_layers):
            full_matrix[z] = spacer

        full_matrix[optical_layers + stored_spacer_layers :] = top_voxels

        backing_z_range = (optical_layers, optical_layers + spacer_layers - 1)
    else:
        total_layers = optical_layers + spacer_layers
        stored_layers = optical_layers + stored_spacer_layers
        full_matrix = np.full((stored_layers, target_h, target_w), -1, dtype=label_dtype)

        full_matrix[0:optical_layers] = bottom_voxels

        # Use backing_color_id parameter to mark backing layer
        spacer = np.full((target_h, target_w), -1, dtype=int)
        spacer[backing_mask_arr] = backing_color_id
        for z in range(optical_layers, stored_layers):
            full_matrix[z] = spacer

        backing_z_range = (optical_layers, total_layers - 1)

    backing_z_min_map, backing_z_max_map = _build_uniform_backing_z_maps(
        backing_mask_arr,
        backing_z_range[0],
        backing_z_range[1],
    )
    backing_metadata = {
        "backing_color_id": backing_color_id,
        "backing_z_range": backing_z_range,
        "backing_z_min_map": backing_z_min_map,
        "backing_z_max_map": backing_z_max_map,
    }
    if compact_backing:
        widths = [1] * optical_layers + [spacer_layers]
        if "双面" in structure_mode or "Double" in structure_mode:
            widths.extend([1] * optical_layers)
        backing_metadata["voxel_z_edges"] = np.concatenate(([0], np.cumsum(widths, dtype=np.int64)))

    return full_matrix, backing_metadata


def _build_voxel_matrix_6layer(
    material_matrix,
    mask_solid,
    spacer_thick,
    structure_mode,
    backing_color_id=0,
    backing_mask=None,
):
    """Build complete voxel matrix for 6-layer structures (5-Color Extended mode).
    构建 6 层体素矩阵（5-Color Extended 模式）。

    Args:
        material_matrix (np.ndarray): (H, W, 6) material matrix for 6 layers
        mask_solid (np.ndarray): (H, W) solid pixel mask
        spacer_thick (float): backing thickness (mm)
        structure_mode (str): "双面" or "单面"
        backing_color_id (int): backing material ID (0-7), default is 0

    Returns:
        tuple: (full_matrix, backing_metadata)
    """
    return _build_voxel_matrix(
        material_matrix,
        mask_solid,
        spacer_thick,
        structure_mode,
        backing_color_id=backing_color_id,
        backing_mask=backing_mask,
    )


def _build_voxel_matrix_faceup(
    material_matrix, mask_solid, spacer_thick, backing_color_id=0, *, compact_backing: bool = False,
):
    """Face-up voxel matrix for 5-Color Extended mode.
    面朝上体素矩阵（5-Color Extended 模式）。

    Orientation: backing at the bottom (print-bed side), viewing surface at the
    top.  The model is printed right-side-up -- no post-print flipping required.
    方向：底板在底部（打印床侧），观赏面在顶部。模型正面朝上打印，无需翻转。

    material_matrix convention (top-to-bottom):
        index 0 = viewing surface (outermost)
        index N-1 = near backing (innermost)

    For base 1024 stacks, index 0 = -1 (air padding) so their viewing surface
    sits 1 Z below the extended stacks, keeping each Z <= 4 materials.

    Layer structure (bottom -> top, Z ascending):
        Z = 0 .. spacer-1  : Solid backing (backing_color_id)
        Z = spacer .. +5   : Optical layers (reversed: index N-1 -> lowest Z,
                             index 0 -> highest Z)
        -1 values stay as air in the voxel matrix.

    Args:
        material_matrix (np.ndarray): (H, W, N) 材料矩阵
        mask_solid (np.ndarray): (H, W) bool 实体掩码
        spacer_thick (float): 底板厚度 (mm)
        backing_color_id (int): 底板材料 ID
        compact_backing (bool): Store the backing as one representative plane
            and report its original layer boundaries in voxel_z_edges.

    Returns:
        tuple: (full_matrix, backing_metadata)
    """
    target_h, target_w, optical_layers = material_matrix.shape
    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))
    stored_spacer_layers = 1 if compact_backing else spacer_layers
    label_dtype = (
        np.result_type(material_matrix.dtype, np.min_scalar_type(backing_color_id), np.int8)
        if compact_backing and material_matrix.dtype.kind == "i" else np.dtype(int)
    )
    full_matrix = np.full((stored_spacer_layers + optical_layers, target_h, target_w), -1, dtype=label_dtype)

    # Backing: solid block at the bottom
    spacer = np.where(mask_solid, backing_color_id, -1).astype(int)
    full_matrix[:stored_spacer_layers] = spacer[np.newaxis, :, :]

    # Optical: reversed order so index 0 (viewing surface) -> highest Z
    for i in range(optical_layers):
        layer = material_matrix[:, :, optical_layers - 1 - i]
        z = stored_spacer_layers + i
        full_matrix[z] = np.where(mask_solid, layer, -1)

    backing_z_range = (0, spacer_layers - 1)
    backing_z_min_map, backing_z_max_map = _build_uniform_backing_z_maps(
        mask_solid,
        backing_z_range[0],
        backing_z_range[1],
    )
    backing_metadata = {
        "backing_color_id": backing_color_id,
        "backing_z_range": backing_z_range,
        "backing_z_min_map": backing_z_min_map,
        "backing_z_max_map": backing_z_max_map,
    }
    if compact_backing:
        backing_metadata["voxel_z_edges"] = np.concatenate(
            ([0], np.cumsum([spacer_layers] + [1] * optical_layers, dtype=np.int64)),
        )
    return full_matrix, backing_metadata


def _build_relief_voxel_matrix(
    matched_rgb,
    material_matrix,
    mask_solid,
    color_height_map,
    default_height,
    structure_mode,
    backing_color_id,
    pixel_scale,
    height_matrix=None,
    global_max_height=None,
    height_identity_rgb=None,
):
    """Build 2.5D relief voxel matrix with per-color or per-pixel variable heights.
    构建 2.5D 浮雕体素矩阵，支持按颜色或按像素的可变高度。

    Supports two modes:
    1. Color height map mode (default): heights assigned by color
    2. Heightmap mode: heights from external grayscale heightmap (per-pixel)

    Physical Model:
    - Each color region has its own target height (Target_Z)
    - Optical thickness is material_matrix.shape[2] * layer height
    - Bottom layers (base): Z=0 to Z=(Target_Z - optical thickness) - filled with backing_color_id
    - Top layers (optical): Z=(Target_Z - optical thickness) to Z=Target_Z - filled with material layers

    Args:
        matched_rgb (np.ndarray): (H, W, 3) display RGB after replacements.
        height_identity_rgb (np.ndarray | None): Stable (H, W, 3) source RGB
            used only for color-height lookup. Replacements must never mutate
            this identity plane. When omitted, ``matched_rgb`` preserves the
            legacy behaviour.
        material_matrix (np.ndarray): (H, W, N) material matrix for optical layers
        mask_solid (np.ndarray): (H, W) boolean mask of solid pixels
        color_height_map (dict): dict mapping hex colors to heights in mm
        default_height (float): default height in mm for colors not in map
        structure_mode (str): "Double-sided" or "Single-sided"
        backing_color_id (int): backing material ID (0-7)
        pixel_scale (float): mm per pixel
        height_matrix (np.ndarray | None): optional (H, W) float32 per-pixel height matrix
        global_max_height (float | None): if provided, forces max Z height across all tiles
            for consistent relief height in large-format mode (大画幅全局最大高度)

    Returns:
        tuple: (full_matrix, backing_metadata)
    """
    color_height_map = _normalize_color_height_map(color_height_map)

    target_h, target_w = material_matrix.shape[:2]
    height_lookup_rgb = (
        np.asarray(height_identity_rgb, dtype=np.uint8)
        if height_identity_rgb is not None
        else np.asarray(matched_rgb, dtype=np.uint8)
    )
    if height_lookup_rgb.shape != (target_h, target_w, 3):
        raise ValueError(
            "height_identity_rgb shape must match the material matrix grid"
        )

    # Material archives can use more than the legacy 5 optical layers. Relief
    # must preserve the full recipe depth instead of truncating to 5.
    OPTICAL_LAYERS = int(material_matrix.shape[2])
    if OPTICAL_LAYERS <= 0:
        raise ValueError("material_matrix must contain at least one optical layer")
    OPTICAL_THICKNESS_MM = OPTICAL_LAYERS * PrinterConfig.LAYER_HEIGHT

    _log.debug(f"Building 2.5D relief voxel matrix...")
    _log.debug(f"Optical layer thickness: {OPTICAL_THICKNESS_MM}mm ({OPTICAL_LAYERS} layers)")

    # Step 1: Build per-pixel height matrix
    if height_matrix is not None:
        _log.debug(f"Using heightmap mode (per-pixel height)")
        pixel_heights = height_matrix.copy()
        pixel_heights[mask_solid & (pixel_heights < OPTICAL_THICKNESS_MM)] = OPTICAL_THICKNESS_MM
    else:
        # Color height map mode: vectorized RGB-code lookup
        pixel_heights = np.full((target_h, target_w), default_height, dtype=np.float32)
        if color_height_map:
            rgb_codes = (
                height_lookup_rgb[..., 0].astype(np.int32) * 65536
                + height_lookup_rgb[..., 1].astype(np.int32) * 256
                + height_lookup_rgb[..., 2].astype(np.int32)
            )
            for hex_color, height in color_height_map.items():
                hex_clean = hex_color.lstrip("#")
                r, g, b = int(hex_clean[0:2], 16), int(hex_clean[2:4], 16), int(hex_clean[4:6], 16)
                code = r * 65536 + g * 256 + b
                pixel_heights[mask_solid & (rgb_codes == code)] = height

    # Step 2: Calculate max height to determine total Z layers
    if global_max_height is not None:
        max_height_mm = global_max_height
    else:
        max_height_mm = np.max(pixel_heights[mask_solid]) if np.any(mask_solid) else default_height
    max_z_layers = max(OPTICAL_LAYERS + 1, int(np.ceil(max_height_mm / PrinterConfig.LAYER_HEIGHT)))

    _log.debug(f"Max height: {max_height_mm:.2f}mm ({max_z_layers} layers)")
    if np.any(mask_solid):
        _log.debug(f"Height range: {np.min(pixel_heights[mask_solid]):.2f}mm - {max_height_mm:.2f}mm")

    # Step 3: Initialize voxel matrix
    full_matrix = np.full((max_z_layers, target_h, target_w), -1, dtype=int)

    # Step 4: Fill voxel matrix (vectorized for both modes)
    target_z_layers = np.clip(
        np.ceil(np.maximum(0.08, pixel_heights) / PrinterConfig.LAYER_HEIGHT).astype(int),
        OPTICAL_LAYERS,
        max_z_layers,
    )
    optical_start_z = target_z_layers - OPTICAL_LAYERS
    backing_z_min_map = np.full((target_h, target_w), -1, dtype=int)
    backing_z_max_map = np.full((target_h, target_w), -1, dtype=int)
    backing_z_min_map[mask_solid] = 0
    backing_z_max_map[mask_solid] = optical_start_z[mask_solid] - 1

    # Fill backing layers
    for z in range(max_z_layers):
        backing_mask = mask_solid & (z < optical_start_z)
        full_matrix[z][backing_mask] = backing_color_id

    # Fill optical layers (vectorized advanced indexing)
    solid_ys, solid_xs = np.where(mask_solid)
    for layer_idx in range(OPTICAL_LAYERS):
        z_pos = optical_start_z[solid_ys, solid_xs] + layer_idx
        valid = z_pos < max_z_layers
        ys_v, xs_v, zs_v = solid_ys[valid], solid_xs[valid], z_pos[valid]
        mat_ids = material_matrix[ys_v, xs_v, OPTICAL_LAYERS - 1 - layer_idx]
        full_matrix[zs_v, ys_v, xs_v] = mat_ids

    # Step 5: Relief mode is always single-sided
    backing_z_range = (0, max_z_layers - OPTICAL_LAYERS - 1)

    backing_metadata = {
        "backing_color_id": backing_color_id,
        "backing_z_range": backing_z_range,
        "backing_z_min_map": backing_z_min_map,
        "backing_z_max_map": backing_z_max_map,
        "is_relief": True,
        "max_height_mm": max_height_mm,
    }

    _log.debug(f"Relief voxel matrix built: {full_matrix.shape}")
    _log.debug(f"Backing range: Z={backing_z_range[0]} to Z={backing_z_range[1]}")
    _log.debug(f"Mode: Single-sided (viewing surface on top)")

    return full_matrix, backing_metadata


def _build_cloisonne_voxel_matrix(
    material_matrix, mask_solid, mask_wireframe, spacer_thick, wire_height_mm, backing_color_id=0
):
    """Build voxel matrix for cloisonne mode.
    构建掐丝珐琅模式的体素矩阵。

    Layer structure (bottom -> top, Z ascending):
        Z = 0 ... spacer_layers-1   : Base / backing  (backing_color_id)
        Z = spacer_layers ... +4    : Colour layers   (material_matrix, flipped for face-up)
        Z = spacer_layers+5 ... +N  : Wire layers     (-3 marker, separate object)

    Cloisonne is always single-sided (face-up).
    Wire uses special marker -3 and is generated as a standalone mesh object.

    Args:
        material_matrix (np.ndarray): (H, W, 5) int per-pixel material IDs for 5 optical layers.
        mask_solid (np.ndarray): (H, W) bool True for non-transparent pixels.
        mask_wireframe (np.ndarray): (H, W) bool True for wire pixels.
        spacer_thick (float): backing thickness in mm.
        wire_height_mm (float): extra wire protrusion above colour surface in mm.
        backing_color_id (int): material slot ID for the backing (default 0 = white).

    Returns:
        tuple: (full_matrix, backing_metadata)
            full_matrix: (Z, H, W) int voxel matrix (-1 = air, -3 = wire).
            backing_metadata: dict with 'backing_color_id', 'backing_z_range', 'is_cloisonne'.
    """
    target_h, target_w = material_matrix.shape[:2]
    OPTICAL = PrinterConfig.COLOR_LAYERS  # 5

    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))
    wire_layers = max(1, int(round(wire_height_mm / PrinterConfig.LAYER_HEIGHT)))

    total_z = spacer_layers + OPTICAL + wire_layers
    full_matrix = np.full((total_z, target_h, target_w), -1, dtype=int)

    # --- Base / backing ---
    spacer_slice = np.where(mask_solid, backing_color_id, -1).astype(int)
    full_matrix[:spacer_layers] = spacer_slice[np.newaxis, :, :]

    # --- Colour layers (face-up: reverse material order) ---
    colour_start = spacer_layers
    for i in range(OPTICAL):
        layer = material_matrix[:, :, OPTICAL - 1 - i]
        z = colour_start + i
        full_matrix[z] = np.where(mask_solid, layer, -1)

    # --- Wire layers (only where mask_wireframe AND mask_solid) ---
    wire_mask_2d = mask_wireframe & mask_solid
    wire_slice = np.where(wire_mask_2d, -3, -1).astype(int)
    wire_start = colour_start + OPTICAL
    full_matrix[wire_start:] = wire_slice[np.newaxis, :, :]

    backing_z_range = (0, spacer_layers - 1)
    backing_z_min_map, backing_z_max_map = _build_uniform_backing_z_maps(
        mask_solid,
        backing_z_range[0],
        backing_z_range[1],
    )
    backing_metadata = {
        "backing_color_id": backing_color_id,
        "backing_z_range": backing_z_range,
        "backing_z_min_map": backing_z_min_map,
        "backing_z_max_map": backing_z_max_map,
        "is_cloisonne": True,
        "wire_layers": wire_layers,
    }

    _log.debug(
        f"Voxel matrix: {full_matrix.shape} "
        f"(base={spacer_layers}, colour={OPTICAL}, wire={wire_layers})"
    )
    return full_matrix, backing_metadata


def run(ctx: dict) -> dict:
    """Build voxel matrix based on mode (standard/5-color/cloisonne/relief).
    根据模式构建体素矩阵（标准/5色/掐丝珐琅/浮雕）。

    PipelineContext 输入键 / Input keys:
        - material_matrix (np.ndarray): (H, W, N) int 材料矩阵
        - mask_solid (np.ndarray): (H, W) bool 实体掩码
        - spacer_thick (float): 底板厚度 (mm)
        - structure_mode (str): "双面" or "单面"
        - backing_color_id (int): 底板材料 ID
        - color_mode (str): 颜色模式
        - enable_cloisonne (bool): 启用掐丝珐琅
        - wire_width_mm (float): 掐丝宽度 (mm)
        - wire_height_mm (float): 掐丝高度 (mm)
        - enable_relief (bool): 启用浮雕
        - color_height_map (dict | None): 颜色高度映射
        - height_mode (str): 高度模式 ("color" | "heightmap")
        - heightmap_path (str | None): 高度图路径
        - heightmap_max_height (float | None): 高度图最大高度
        - matched_rgb (np.ndarray): (H, W, 3) 匹配后的 RGB
        - processor (LuminaImageProcessor): 处理器实例
        - pixel_scale (float): mm/px 缩放因子

    PipelineContext 输出键 / Output keys:
        - full_matrix (np.ndarray): (Z, H, W) signed material label planes.
          Z counts stored representative planes when voxel_z_edges is present.
        - voxel_z_edges (np.ndarray | None): Z+1 original layer boundaries,
          or None for a dense volume; pass these with this volume to the mesher.
        - backing_metadata (dict): 底板元数据
        - total_layers (int): 总层数
        - heightmap_stats (dict | None): 高度图统计信息
    """
    _t0 = time.perf_counter()

    material_matrix = ctx["material_matrix"]
    mask_solid = ctx["mask_solid"]
    spacer_thick = ctx["spacer_thick"]
    structure_mode = ctx.get("structure_mode", "单面")
    backing_color_id = ctx.get("backing_color_id", 0)
    color_mode = ctx.get("color_mode", "4-Color")
    enable_cloisonne = ctx.get("enable_cloisonne", False)
    enable_relief = ctx.get("enable_relief", False)
    color_height_map = ctx.get("color_height_map")
    height_mode = ctx.get("height_mode", "color")
    heightmap_path = ctx.get("heightmap_path")
    heightmap_max_height = ctx.get("heightmap_max_height")
    matched_rgb = ctx["matched_rgb"]
    height_identity_rgb = ctx.get("height_identity_rgb")
    pixel_scale = ctx["pixel_scale"]
    relief_global_max_height = ctx.get("relief_global_max_height")
    enable_fridge_magnet = ctx.get("enable_fridge_magnet", False)
    fridge_magnets = ctx.get("fridge_magnets") or []
    lut_metadata = ctx.get("lut_metadata")
    effective_backing_color_id = _resolve_generation_backing_color_id(backing_color_id, lut_metadata)
    if enable_fridge_magnet and fridge_magnets:
        min_fridge_spacer_thick = _resolve_min_fridge_spacer_thick(fridge_magnets)
        if spacer_thick + 1e-9 < min_fridge_spacer_thick:
            _log.debug(
                "Raising spacer_thick from %.3fmm to %.3fmm so fridge cavity fits after layer quantization",
                spacer_thick,
                min_fridge_spacer_thick,
            )
            spacer_thick = min_fridge_spacer_thick

    heightmap_stats = None

    try:
        # ========== 5-Color Extended: force single-sided face-up ==========
        if "5-Color Extended" in color_mode:
            _log.debug(f"5-Color Extended: forcing single-sided face-up")
            structure_mode = "单面"
            if enable_relief:
                _log.debug(f"5-Color Extended: 2.5D relief mode disabled (incompatible)")
                enable_relief = False
            full_matrix, backing_metadata = _build_voxel_matrix_faceup(
                material_matrix, mask_solid, spacer_thick, effective_backing_color_id,
                compact_backing=not enable_fridge_magnet,
            )

        # ========== Cloisonne Mode ==========
        elif enable_cloisonne:
            _log.debug(f"Cloisonne Mode ENABLED")
            wire_width_mm = ctx.get("wire_width_mm", 0.4)
            wire_height_mm = ctx.get("wire_height_mm", 0.4)
            _log.debug(f"Wire: width={wire_width_mm}mm, height={wire_height_mm}mm")

            # Force single-sided (face-up)
            structure_mode = "单面"

            # Extract wireframe mask from matched colours
            processor = ctx.get("processor")
            if processor is not None and hasattr(processor, "_extract_wireframe_mask"):
                target_w = ctx.get("target_w", matched_rgb.shape[1])
                mask_wireframe = processor._extract_wireframe_mask(
                    matched_rgb,
                    target_w,
                    pixel_scale,
                    wire_width_mm,
                )
            else:
                from core.pipeline.processing_ops.wireframe_extractor import extract_wireframe_mask

                mask_wireframe = extract_wireframe_mask(matched_rgb, pixel_scale, wire_width_mm)

            full_matrix, backing_metadata = _build_cloisonne_voxel_matrix(
                material_matrix,
                mask_solid,
                mask_wireframe,
                spacer_thick,
                wire_height_mm,
                effective_backing_color_id,
            )

        # ========== 2.5D Relief Mode ==========
        else:
            heightmap_height_matrix = None

            if enable_relief and height_mode == "heightmap" and heightmap_path is not None:
                _log.debug(f"Heightmap Relief Mode: loading heightmap...")
                _log.debug(f"Heightmap path: {heightmap_path}")
                try:
                    from core.heightmap_loader import HeightmapLoader

                    target_w = ctx["target_w"]
                    target_h = ctx["target_h"]
                    hm_max = heightmap_max_height if heightmap_max_height is not None else 5.0
                    hm_result = HeightmapLoader.load_and_process(
                        heightmap_path=heightmap_path,
                        target_w=target_w,
                        target_h=target_h,
                        max_relief_height=hm_max,
                        base_thickness=spacer_thick,
                    )
                    if hm_result["success"]:
                        heightmap_height_matrix = hm_result["height_matrix"]
                        heightmap_stats = hm_result["stats"]
                        for w in hm_result.get("warnings", []):
                            _log.warning(f"{w}")
                        _log.debug(f"Heightmap loaded: {heightmap_height_matrix.shape}")
                    else:
                        raise RuntimeError(f"Heightmap processing failed: {hm_result['error']}")
                except (ImportError, OSError, ValueError, TypeError, KeyError) as e:
                    raise RuntimeError(f"Heightmap processing error: {e}") from e
            elif enable_relief and height_mode == "heightmap" and heightmap_path is None:
                raise RuntimeError("Heightmap mode selected but no heightmap provided")

            if heightmap_height_matrix is not None:
                # Heightmap mode
                _log.debug(f"2.5D Heightmap Relief Mode ENABLED")
                full_matrix, backing_metadata = _build_relief_voxel_matrix(
                    matched_rgb=matched_rgb,
                    material_matrix=material_matrix,
                    mask_solid=mask_solid,
                    color_height_map=color_height_map if color_height_map else {},
                    default_height=spacer_thick,
                    structure_mode=structure_mode,
                    backing_color_id=effective_backing_color_id,
                    pixel_scale=pixel_scale,
                    height_matrix=heightmap_height_matrix,
                    global_max_height=relief_global_max_height,
                    height_identity_rgb=height_identity_rgb,
                )
            elif enable_relief and height_mode == "color" and color_height_map:
                _log.debug(f"2.5D Relief Mode ENABLED")
                _log.debug(f"Color height map: {color_height_map}")

                full_matrix, backing_metadata = _build_relief_voxel_matrix(
                    matched_rgb=matched_rgb,
                    material_matrix=material_matrix,
                    mask_solid=mask_solid,
                    color_height_map=color_height_map,
                    default_height=spacer_thick,
                    structure_mode=structure_mode,
                    backing_color_id=effective_backing_color_id,
                    pixel_scale=pixel_scale,
                    global_max_height=relief_global_max_height,
                    height_identity_rgb=height_identity_rgb,
                )
            else:
                # Original flat voxel matrix
                flat_backing_mask = _resolve_flat_backing_mask(ctx, mask_solid)
                full_matrix, backing_metadata = _build_voxel_matrix(
                    material_matrix,
                    mask_solid,
                    spacer_thick,
                    structure_mode,
                    effective_backing_color_id,
                    backing_mask=flat_backing_mask,
                    compact_backing=not enable_fridge_magnet,
                )

        if enable_fridge_magnet:
            full_matrix = _carve_fridge_magnet_cavities(
                full_matrix,
                mask_solid,
                pixel_scale,
                backing_metadata,
                fridge_magnets,
            )

        z_edges = backing_metadata.get("voxel_z_edges")
        total_layers = int(z_edges[-1]) if z_edges is not None else full_matrix.shape[0]
        _log.debug(f"Voxel matrix: {full_matrix.shape} (ZxHxW)")
        _log.debug(
            f"Backing layer: z={backing_metadata['backing_z_range']}, "
            f"color_id={backing_metadata['backing_color_id']}"
        )

    except (ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
        # A flat retry would discard the requested relief, wire or cavities.
        # 平面重试会丢掉请求中的浮雕、掐丝或磁铁孔槽，不能作为成功结果。
        _log.error(
            "Voxel matrix generation failed: %s",
            e,
            extra={
                "event": "voxel_build_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        ctx["error"] = f"[ERROR] Voxel matrix generation failed: {e}"
        return ctx

    ctx["full_matrix"] = full_matrix
    ctx["voxel_z_edges"] = z_edges
    ctx["backing_metadata"] = backing_metadata
    ctx["total_layers"] = total_layers
    ctx["heightmap_stats"] = heightmap_stats
    # Update structure_mode in case it was forced
    ctx["structure_mode"] = structure_mode
    ctx["spacer_thick"] = spacer_thick
    face_orientation_override = (
        "up"
        if backing_metadata.get("is_relief") or backing_metadata.get("is_cloisonne")
        else None
    )
    _update_bambu_base_layer_ctx_from_voxels(
        ctx,
        color_mode=color_mode,
        structure_mode=structure_mode,
        num_layers=material_matrix.shape[2],
        thickness_mm=spacer_thick,
        face_orientation_override=face_orientation_override,
    )

    _elapsed = time.perf_counter() - _t0
    _log.debug(f"voxel_build done: {_elapsed:.3f}s")
    ctx.setdefault("_hifi_timings", {})["voxel_build_s"] = _elapsed
    return ctx
