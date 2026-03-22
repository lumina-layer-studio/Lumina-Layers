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

import numpy as np

from config import PrinterConfig


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


def _build_voxel_matrix(material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0):
    """Build complete voxel matrix with backing layer marked using special material_id.
    构建带底板标记的完整体素矩阵。

    Args:
        material_matrix (np.ndarray): (H, W, N) material matrix (N optical layers)
            (材料矩阵，N 个光学层)
        mask_solid (np.ndarray): (H, W) solid pixel mask (实体像素掩码)
        spacer_thick (float): backing thickness (mm) (底板厚度)
        structure_mode (str): "双面" or "单面" (Double-sided or Single-sided)
        backing_color_id (int): backing material ID (0-7), default is 0 (White)

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
    mask_transparent = ~mask_solid

    bottom_voxels = np.transpose(material_matrix, (2, 0, 1))

    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))

    if "双面" in structure_mode or "Double" in structure_mode:
        top_voxels = np.transpose(material_matrix[..., ::-1], (2, 0, 1))
        total_layers = optical_layers + spacer_layers + optical_layers
        full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)

        full_matrix[0:optical_layers] = bottom_voxels

        # Use backing_color_id parameter to mark backing layer
        spacer = np.full((target_h, target_w), -1, dtype=int)
        spacer[~mask_transparent] = backing_color_id
        for z in range(optical_layers, optical_layers + spacer_layers):
            full_matrix[z] = spacer

        full_matrix[optical_layers + spacer_layers :] = top_voxels

        backing_z_range = (optical_layers, optical_layers + spacer_layers - 1)
    else:
        total_layers = optical_layers + spacer_layers
        full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)

        full_matrix[0:optical_layers] = bottom_voxels

        # Use backing_color_id parameter to mark backing layer
        spacer = np.full((target_h, target_w), -1, dtype=int)
        spacer[~mask_transparent] = backing_color_id
        for z in range(optical_layers, total_layers):
            full_matrix[z] = spacer

        backing_z_range = (optical_layers, total_layers - 1)

    backing_metadata = {"backing_color_id": backing_color_id, "backing_z_range": backing_z_range}

    return full_matrix, backing_metadata


def _build_voxel_matrix_6layer(material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0):
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
        material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=backing_color_id
    )


def _build_voxel_matrix_faceup(material_matrix, mask_solid, spacer_thick, backing_color_id=0):
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

    Returns:
        tuple: (full_matrix, backing_metadata)
    """
    target_h, target_w, optical_layers = material_matrix.shape
    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))
    total_layers = spacer_layers + optical_layers
    full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)

    # Backing: solid block at the bottom
    spacer = np.where(mask_solid, backing_color_id, -1).astype(int)
    full_matrix[:spacer_layers] = spacer[np.newaxis, :, :]

    # Optical: reversed order so index 0 (viewing surface) -> highest Z
    for i in range(optical_layers):
        layer = material_matrix[:, :, optical_layers - 1 - i]
        z = spacer_layers + i
        full_matrix[z] = np.where(mask_solid, layer, -1)

    backing_z_range = (0, spacer_layers - 1)
    return full_matrix, {
        "backing_color_id": backing_color_id,
        "backing_z_range": backing_z_range,
    }


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
):
    """Build 2.5D relief voxel matrix with per-color or per-pixel variable heights.
    构建 2.5D 浮雕体素矩阵，支持按颜色或按像素的可变高度。

    Supports two modes:
    1. Color height map mode (default): heights assigned by color
    2. Heightmap mode: heights from external grayscale heightmap (per-pixel)

    Physical Model:
    - Each color region has its own target height (Target_Z)
    - Bottom layers (base): Z=0 to Z=(Target_Z - 0.4mm) - filled with backing_color_id
    - Top layers (optical): Z=(Target_Z - 0.4mm) to Z=Target_Z - filled with material layers

    Args:
        matched_rgb (np.ndarray): (H, W, 3) RGB color array after K-Means matching
        material_matrix (np.ndarray): (H, W, 5) material matrix for optical layers
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

    # Constants
    OPTICAL_LAYERS = 5
    OPTICAL_THICKNESS_MM = OPTICAL_LAYERS * PrinterConfig.LAYER_HEIGHT  # 0.4mm

    print(f"[RELIEF] Building 2.5D relief voxel matrix...")
    print(f"[RELIEF] Optical layer thickness: {OPTICAL_THICKNESS_MM}mm ({OPTICAL_LAYERS} layers)")

    # Step 1: Build per-pixel height matrix
    if height_matrix is not None:
        print(f"[RELIEF] Using heightmap mode (per-pixel height)")
        pixel_heights = height_matrix.copy()
        pixel_heights[mask_solid & (pixel_heights < OPTICAL_THICKNESS_MM)] = OPTICAL_THICKNESS_MM
    else:
        # Color height map mode: vectorized RGB-code lookup
        pixel_heights = np.full((target_h, target_w), default_height, dtype=np.float32)
        if color_height_map:
            rgb_codes = (
                matched_rgb[..., 0].astype(np.int32) * 65536
                + matched_rgb[..., 1].astype(np.int32) * 256
                + matched_rgb[..., 2].astype(np.int32)
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

    print(f"[RELIEF] Max height: {max_height_mm:.2f}mm ({max_z_layers} layers)")
    if np.any(mask_solid):
        print(f"[RELIEF] Height range: {np.min(pixel_heights[mask_solid]):.2f}mm - {max_height_mm:.2f}mm")

    # Step 3: Initialize voxel matrix
    full_matrix = np.full((max_z_layers, target_h, target_w), -1, dtype=int)

    # Step 4: Fill voxel matrix (vectorized for both modes)
    target_z_layers = np.clip(
        np.ceil(np.maximum(0.08, pixel_heights) / PrinterConfig.LAYER_HEIGHT).astype(int),
        OPTICAL_LAYERS,
        max_z_layers,
    )
    optical_start_z = target_z_layers - OPTICAL_LAYERS

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
        "is_relief": True,
        "max_height_mm": max_height_mm,
    }

    print(f"[RELIEF] Relief voxel matrix built: {full_matrix.shape}")
    print(f"[RELIEF] Backing range: Z={backing_z_range[0]} to Z={backing_z_range[1]}")
    print(f"[RELIEF] Mode: Single-sided (viewing surface on top)")

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
    backing_metadata = {
        "backing_color_id": backing_color_id,
        "backing_z_range": backing_z_range,
        "is_cloisonne": True,
        "wire_layers": wire_layers,
    }

    print(
        f"[CLOISONNE] Voxel matrix: {full_matrix.shape} "
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
        - full_matrix (np.ndarray): (Z, H, W) int 体素矩阵
        - backing_metadata (dict): 底板元数据
        - total_layers (int): 总层数
        - heightmap_stats (dict | None): 高度图统计信息
    """
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
    pixel_scale = ctx["pixel_scale"]
    relief_global_max_height = ctx.get("relief_global_max_height")

    heightmap_stats = None

    try:
        # ========== 5-Color Extended: force single-sided face-up ==========
        if "5-Color Extended" in color_mode:
            print(f"[S06] 5-Color Extended: forcing single-sided face-up")
            structure_mode = "单面"
            if enable_relief:
                print(f"[S06] 5-Color Extended: 2.5D relief mode disabled (incompatible)")
                enable_relief = False
            full_matrix, backing_metadata = _build_voxel_matrix_faceup(
                material_matrix, mask_solid, spacer_thick, backing_color_id
            )

        # ========== Cloisonne Mode ==========
        elif enable_cloisonne:
            print(f"[S06] Cloisonne Mode ENABLED")
            wire_width_mm = ctx.get("wire_width_mm", 0.4)
            wire_height_mm = ctx.get("wire_height_mm", 0.4)
            print(f"[S06] Wire: width={wire_width_mm}mm, height={wire_height_mm}mm")

            # Force single-sided (face-up)
            structure_mode = "单面"

            # Extract wireframe mask from matched colours
            processor = ctx["processor"]
            target_w = ctx["target_w"]
            mask_wireframe = processor._extract_wireframe_mask(matched_rgb, target_w, pixel_scale, wire_width_mm)

            full_matrix, backing_metadata = _build_cloisonne_voxel_matrix(
                material_matrix, mask_solid, mask_wireframe, spacer_thick, wire_height_mm, backing_color_id
            )

        # ========== 2.5D Relief Mode ==========
        else:
            heightmap_height_matrix = None

            if enable_relief and height_mode == "heightmap" and heightmap_path is not None:
                print(f"[S06] Heightmap Relief Mode: loading heightmap...")
                print(f"[S06] Heightmap path: {heightmap_path}")
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
                            print(f"[S06] {w}")
                        print(f"[S06] Heightmap loaded: {heightmap_height_matrix.shape}")
                    else:
                        print(f"[S06] WARNING: Heightmap processing failed: {hm_result['error']}, falling back to flat")
                except Exception as e:
                    print(f"[S06] WARNING: Heightmap processing error: {e}, falling back to flat")
            elif enable_relief and height_mode == "heightmap" and heightmap_path is None:
                print("[S06] WARNING: heightmap mode selected but no heightmap provided, falling back to flat")

            if heightmap_height_matrix is not None:
                # Heightmap mode
                print(f"[S06] 2.5D Heightmap Relief Mode ENABLED")
                full_matrix, backing_metadata = _build_relief_voxel_matrix(
                    matched_rgb=matched_rgb,
                    material_matrix=material_matrix,
                    mask_solid=mask_solid,
                    color_height_map=color_height_map if color_height_map else {},
                    default_height=spacer_thick,
                    structure_mode=structure_mode,
                    backing_color_id=backing_color_id,
                    pixel_scale=pixel_scale,
                    height_matrix=heightmap_height_matrix,
                    global_max_height=relief_global_max_height,
                )
            elif enable_relief and height_mode == "color" and color_height_map:
                print(f"[S06] 2.5D Relief Mode ENABLED")
                print(f"[S06] Color height map: {color_height_map}")

                full_matrix, backing_metadata = _build_relief_voxel_matrix(
                    matched_rgb=matched_rgb,
                    material_matrix=material_matrix,
                    mask_solid=mask_solid,
                    color_height_map=color_height_map,
                    default_height=spacer_thick,
                    structure_mode=structure_mode,
                    backing_color_id=backing_color_id,
                    pixel_scale=pixel_scale,
                    global_max_height=relief_global_max_height,
                )
            else:
                # Original flat voxel matrix
                full_matrix, backing_metadata = _build_voxel_matrix(
                    material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id
                )

        total_layers = full_matrix.shape[0]
        print(f"[S06] Voxel matrix: {full_matrix.shape} (ZxHxW)")
        print(
            f"[S06] Backing layer: z={backing_metadata['backing_z_range']}, "
            f"color_id={backing_metadata['backing_color_id']}"
        )

    except Exception as e:
        print(f"[S06] Error marking backing layer: {e}")
        print(f"[S06] Falling back to original behavior (backing_color_id=0)")

        # Fallback to original behavior
        try:
            full_matrix, backing_metadata = _build_voxel_matrix(
                material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0
            )
            total_layers = full_matrix.shape[0]
            print(f"[S06] Fallback successful: {full_matrix.shape} (ZxHxW)")
        except Exception as fallback_error:
            ctx["error"] = f"[ERROR] Voxel matrix generation failed: {fallback_error}"
            return ctx

    ctx["full_matrix"] = full_matrix
    ctx["backing_metadata"] = backing_metadata
    ctx["total_layers"] = total_layers
    ctx["heightmap_stats"] = heightmap_stats
    # Update structure_mode in case it was forced
    ctx["structure_mode"] = structure_mode

    return ctx
