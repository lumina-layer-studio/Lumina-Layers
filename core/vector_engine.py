"""
Lumina Studio - Native Vector Engine

Handles direct SVG to 3D mesh conversion using vector math (Shapely/Clipper)
instead of rasterization. This preserves smooth curves and sharp edges.

Architecture:
    SVG → Parse Paths → Match Colors → Boolean Ops → Extrude → Silhouette Backing → 3MF

Key Features:
    - Direct path processing (no rasterization)
    - Boolean operations via Shapely (equivalent to Clipper)
    - Smooth curve preservation
    - Automatic color matching to LUT
    - Mesh merging by material
    - Coordinate system correction (Y-axis flip)
    - Accurate silhouette backing (union of all shapes)
    - Double-sided structure support
"""

import numpy as np
import trimesh
from svgelements import SVG, Path, Shape
from shapely.geometry import Polygon, MultiPolygon
from shapely import affinity  # <--- 【新增】用于几何变换
from shapely.ops import unary_union
import os

from config import PrinterConfig, ColorSystem

# Reuse image processor for color matching infrastructure
from core.image_processing import LuminaImageProcessor


class VectorProcessor:
    """
    Native vector processing engine for SVG files.
    
    This class provides direct SVG-to-3D conversion without rasterization,
    preserving vector precision and smooth curves.
    
    Attributes:
        color_mode (str): Color system mode (CMYW/RYBW/6-Color)
        img_processor (LuminaImageProcessor): For LUT color matching
        sampling_precision (float): Curve approximation precision in mm
    
    Example:
        >>> processor = VectorProcessor("my_lut.npy", "CMYW")
        >>> scene = processor.svg_to_mesh("logo.svg", 50.0, 1.6, "Double-sided")
        >>> scene.export("output.3mf")
    """
    
    def __init__(self, lut_path: str, color_mode: str):
        """
        Initialize vector processor with LUT and color mode.
        
        Args:
            lut_path: Path to .npy LUT file
            color_mode: Color system ("CMYW", "RYBW", or "6-Color")
            
        Raises:
            FileNotFoundError: If LUT file doesn't exist
            ValueError: If color mode is invalid
        """
        self.color_mode = color_mode
        print(f"[VECTOR] Initializing Native Vector Engine ({color_mode})...")
        
        # Reuse ImageProcessor for LUT loading and KD-Tree
        # We only use its color matching infrastructure, not image processing
        self.img_processor = LuminaImageProcessor(lut_path, color_mode)
        
        # Default curve approximation precision
        self.sampling_precision = 0.05  # mm (high quality)
        
        print(f"[VECTOR] ✅ Initialized with {len(self.img_processor.ref_stacks)} LUT colors")

    def svg_to_mesh(self, svg_path: str, target_width_mm: float, 
                    thickness_mm: float, structure_mode: str = "Single-sided",
                    color_replacements: dict = None) -> trimesh.Scene:
        """
        Convert SVG file to 3D mesh scene.
        
        This is the main entry point for vector processing. It orchestrates
        the entire pipeline from SVG parsing to 3D mesh generation.
        
        Args:
            svg_path: Path to SVG file
            target_width_mm: Target width in millimeters
            thickness_mm: Backing layer thickness in mm
            structure_mode: "Single-sided" or "Double-sided" (双面/单面)
            
        Returns:
            trimesh.Scene: Complete 3D scene with all meshes
            
        Raises:
            ValueError: If SVG parsing fails or no valid shapes found
            
        Example:
            >>> processor = VectorProcessor("lut.npy", "CMYW")
            >>> scene = processor.svg_to_mesh("logo.svg", 50.0, 1.6, "Double-sided")
            >>> scene.export("output.3mf")
        """
        print(f"[VECTOR] Processing: {svg_path}")
        print(f"[VECTOR] Structure mode: {structure_mode}")
        
        # Step 1: Parse SVG and extract shapes
        shape_data, scale_factor, bbox = self._parse_svg(svg_path, target_width_mm)
        
        if not shape_data:
            raise ValueError("No valid filled shapes found in SVG.")
        
        print(f"[VECTOR] Found {len(shape_data)} valid shapes. Scale: {scale_factor:.4f}")
        
        # Step 2: Group shapes by SVG color (NOT by LUT material yet)
        # This allows us to handle overlapping shapes correctly
        replacement_manager = None
        if color_replacements:
            try:
                from core.color_replacement import ColorReplacementManager
                replacement_manager = ColorReplacementManager.from_dict(color_replacements)
            except Exception as e:
                print(f"[VECTOR] Warning: Failed to load color replacements: {e}")

        # Group by original SVG color first
        color_groups = {}  # {svg_color: [polygons]}
        color_order = []  # Track the order colors first appear in SVG
        
        for item in shape_data:
            color_key = item['color']
            if color_key not in color_groups:
                color_groups[color_key] = []
                color_order.append(color_key)  # Preserve SVG order
            color_groups[color_key].append(item['poly'])
        
        print(f"[VECTOR] Found {len(color_groups)} unique SVG colors")
        
        # Perform Boolean operations between different colors
        # Key insight: In SVG, later elements are drawn ON TOP
        # So later colors should NOT be subtracted - they stay complete
        # Earlier colors should have holes cut by later colors
        # BUT: Small features (< 100 sq units) are preserved without subtraction
        
        print(f"[VECTOR] Processing {len(color_order)} colors in SVG order:")
        for c in color_order:
            hex_color = f'#{c[0]:02x}{c[1]:02x}{c[2]:02x}'
            num_shapes = len(color_groups[c])
            print(f"  {hex_color}: {num_shapes} shapes")
        
        final_geometries = {}  # {svg_color: final_geometry}
        
        # First pass: merge all polygons of each color and calculate areas
        merged_colors = {}
        for current_color in color_order:
            merged = self._perform_boolean_union(color_groups[current_color])
            if merged is not None and not merged.is_empty:
                merged_colors[current_color] = merged
        
        # Second pass: perform Boolean operations, but protect small features
        for i, current_color in enumerate(color_order):
            if current_color not in merged_colors:
                continue
                
            merged = merged_colors[current_color]
            area = merged.area
            hex_color = f'#{current_color[0]:02x}{current_color[1]:02x}{current_color[2]:02x}'
            
            # Small features are protected from Boolean subtraction
            is_small_feature = area < 100
            
            if is_small_feature:
                print(f"  {hex_color}: area={area:.2f} sq units ⭐ SMALL FEATURE - PROTECTED")
                final_geometries[current_color] = merged
                continue
            
            # For larger features, subtract from earlier colors
            for j in range(i):
                earlier_color = color_order[j]
                if earlier_color not in final_geometries:
                    continue
                earlier_geom = final_geometries[earlier_color]
                
                if earlier_geom is not None and not earlier_geom.is_empty:
                    try:
                        # Remove the part of earlier color that overlaps with current color
                        final_geometries[earlier_color] = earlier_geom.difference(merged)
                    except Exception as e:
                        print(f"[VECTOR] Warning: Boolean difference failed: {e}")
            
            # Current color stays complete
            print(f"  {hex_color}: area={area:.2f} sq units")
            final_geometries[current_color] = merged
        
        print(f"[VECTOR] After Boolean operations: {len(final_geometries)} color regions")
        
        # Now map each color to LUT and distribute to layers
        # We need to track the order of colors for proper Z-layering
        layer_map = {}  # {z_layer: {mat_id: [(geometry, svg_color_index)]}}
        
        print(f"[VECTOR] Mapping colors to LUT materials:")
        for color_index, (svg_color, geometry) in enumerate(final_geometries.items()):
            # Query LUT for this color
            query = np.array([svg_color], dtype=np.float32)
            _, index = self.img_processor.kdtree.query(query)
            
            # Get matched LUT color
            matched_rgb = tuple(int(c) for c in self.img_processor.lut_rgb[index[0]])
            
            # Get material stack
            stack = self.img_processor.ref_stacks[index[0]]
            
            hex_color = f'#{svg_color[0]:02x}{svg_color[1]:02x}{svg_color[2]:02x}'
            print(f"  {hex_color} → LUT {matched_rgb} → Materials {stack[:5]}")
            
            # Apply replacement if provided
            if replacement_manager is not None:
                replacement = replacement_manager.get_replacement(matched_rgb)
                if replacement is not None:
                    _, rep_index = self.img_processor.kdtree.query(np.array([replacement]))
                    index = rep_index
                    stack = self.img_processor.ref_stacks[index[0]]
                    print(f"    → Replaced with {replacement} → Materials {stack[:5]}")
            
            # Distribute to layers with color order tracking
            num_layers_to_use = min(5, len(stack))
            for z in range(num_layers_to_use):
                mat_id = stack[z]
                
                if z not in layer_map:
                    layer_map[z] = {}
                if mat_id not in layer_map[z]:
                    layer_map[z][mat_id] = []
                
                # Store geometry with its original color index for Z-ordering
                layer_map[z][mat_id].append((geometry, color_index))
        
        # ==================== [关键修复] 强制同步颜色配置 ====================
        # Check actual LUT size
        is_six_color = len(self.img_processor.lut_rgb) == 1296  # 6^4 = 1296
        num_layers = 5
        
        if is_six_color:
            print("[VECTOR] 🧠 Auto-detected 6-Color LUT (1296). Forcing 6-Color mode.")
            # 强制切换到 6 色配置，覆盖 UI 选择
            color_conf = ColorSystem.SIX_COLOR
            self.color_mode = "6-Color"  # 更新内部状态
        else:
            # 否则使用 UI 传入的模式
            color_conf = ColorSystem.get(self.color_mode)
        
        # 获取正确的材质名称和预览颜色
        slot_names = color_conf['slots']
        preview_colors = color_conf['preview']
        print(f"[VECTOR] Using config: {len(slot_names)} slots")
        # ===================================================================
        
        # Step 4: Collect all polygons for silhouette backing
        all_polygons = []
        for z in range(num_layers):
            if z not in layer_map:
                continue
            for mat_id, geom_list in layer_map[z].items():
                # Extract just the geometries (ignore color indices)
                all_polygons.extend([g for g, _ in geom_list])
        
        # Step 5: Create silhouette backing
        print(f"[VECTOR] Creating silhouette backing from {len(all_polygons)} polygons...")
        silhouette = self._perform_boolean_union(all_polygons)
        
        # Step 6: Generate meshes for color layers
        # Handle multiple SVG colors mapping to same material by using micro Z-offsets
        layer_h = PrinterConfig.LAYER_HEIGHT
        meshes_by_slot = {}
        
        # Micro offset for overlapping colors on same material (0.001mm per color)
        MICRO_OFFSET = 0.001
        
        for z in range(num_layers):
            if z not in layer_map:
                continue
            
            for mat_id, geom_list in layer_map[z].items():
                if not geom_list:
                    continue
                
                # 安全检查：防止脏数据导致的越界
                if mat_id >= len(slot_names):
                    print(f"[VECTOR] ⚠️ Skipping invalid mat_id {mat_id} (max {len(slot_names)-1})")
                    continue
                
                # Sort by color index to maintain SVG order
                geom_list.sort(key=lambda x: x[1])
                
                # Process each geometry separately with micro Z-offset
                # This prevents small features from being lost in union operations
                slot_name = slot_names[mat_id]
                
                for offset_idx, (geometry, color_idx) in enumerate(geom_list):
                    if geometry is None or geometry.is_empty:
                        continue
                    
                    # Calculate Z position with micro offset
                    # Later colors (higher color_idx) get slightly higher Z
                    current_z = z * layer_h + (offset_idx * MICRO_OFFSET)
                    
                    new_meshes = self._extrude_geometry(
                        geometry, 
                        height=layer_h, 
                        z_offset=current_z, 
                        scale=scale_factor
                    )
                    
                    if len(new_meshes) == 0:
                        geom_area = geometry.area
                        print(f"[VECTOR] ⚠️ No meshes generated for mat_id={mat_id}, z={z}, area={geom_area:.2f}")
                    
                    if slot_name not in meshes_by_slot:
                        meshes_by_slot[slot_name] = {'meshes': [], 'mat_id': mat_id}
                    meshes_by_slot[slot_name]['meshes'].extend(new_meshes)
        
        # Step 7: Generate backing layer
        backing_layers = max(1, int(round(thickness_mm / layer_h)))
        backing_z_start = num_layers * layer_h
        
        if thickness_mm > 0:
            print(f"[VECTOR] Generating backing: {backing_layers} layers ({thickness_mm}mm)")
            backing_meshes = []
            for i in range(backing_layers):
                backing_z = backing_z_start + (i * layer_h)
                backing_mesh_list = self._extrude_geometry(
                    silhouette,
                    height=layer_h,
                    z_offset=backing_z,
                    scale=scale_factor
                )
                backing_meshes.extend(backing_mesh_list)
            
            # 背板始终使用 Slot 0 (White)
            if backing_meshes:
                # 确保 "Board" 对象使用正确的白色材质 ID
                backing_id = 0
                backing_name = "Board"  # 或者使用 slot_names[0] 比如 "White"
                if backing_name not in meshes_by_slot:
                    meshes_by_slot[backing_name] = {'meshes': [], 'mat_id': backing_id}
                meshes_by_slot[backing_name]['meshes'].extend(backing_meshes)
        
        # Step 8: Handle double-sided structure
        is_double_sided = ("双面" in structure_mode or "Double" in structure_mode)
        
        if is_double_sided:
            print("[VECTOR] Adding top color layers (double-sided mode)...")
            top_z_start = backing_z_start + (backing_layers * layer_h)
            
            for z in range(num_layers):
                if z not in layer_map:
                    continue
                
                # Z轴倒序：Face Up (Top layer is Detail)
                inverted_z = (num_layers - 1) - z
                current_z = top_z_start + (inverted_z * layer_h)
                
                for mat_id, geom_list in layer_map[z].items():
                    if not geom_list:
                        continue
                    if mat_id >= len(slot_names):  # 安全检查
                        continue
                    
                    slot_name = slot_names[mat_id]
                    
                    # Sort by color index
                    geom_list.sort(key=lambda x: x[1])
                    
                    # Process each geometry separately with micro Z-offset
                    for offset_idx, (geometry, color_idx) in enumerate(geom_list):
                        if geometry is None or geometry.is_empty:
                            continue
                        
                        # Calculate Z position with micro offset
                        current_z_with_offset = current_z + (offset_idx * MICRO_OFFSET)
                        
                        new_meshes = self._extrude_geometry(
                            geometry,
                            height=layer_h,
                            z_offset=current_z_with_offset,
                            scale=scale_factor
                        )
                        
                        if slot_name in meshes_by_slot:
                            meshes_by_slot[slot_name]['meshes'].extend(new_meshes)
        
        # Step 9: Merge and Assemble
        scene = trimesh.Scene()
        svg_height_mm = bbox[3] * scale_factor
        
        # [FIX] Sort by Material ID to ensure consistent order in Slicer
        # This fixes the "random color order" issue
        sorted_items = sorted(meshes_by_slot.items(), key=lambda x: x[1]['mat_id'])
        
        for name, data in sorted_items:
            mesh_list = data['meshes']
            mat_id = data['mat_id']
            
            if not mesh_list:
                continue
            
            print(f"[VECTOR] Merging {len(mesh_list)} parts for {name}...")
            if len(mesh_list) > 1:
                combined_mesh = trimesh.util.concatenate(mesh_list)
            else:
                combined_mesh = mesh_list[0]
            
            self._fix_coordinates(combined_mesh, svg_height_mm)
            
            # 应用正确的预览颜色
            # 使用 .get 防止越界，默认白色
            color_val = preview_colors.get(mat_id, [255, 255, 255, 255])
            combined_mesh.visual.face_colors = color_val
            
            # Set metadata names (Critical for Slicer recognition)
            combined_mesh.metadata['name'] = name
            
            # Use name as node name
            scene.add_geometry(combined_mesh, geom_name=name)
        
        print(f"[VECTOR] ✅ Scene complete: {len(scene.geometry)} objects")
        return scene
    
    def _parse_svg(self, svg_path: str, target_width_mm: float):
        """
        Parse SVG and normalize coordinates using Shapely Affinity.
        
        [Method]: Global Geometry Normalization
        """
        try:
            svg = SVG.parse(svg_path)
        except Exception as e:
            raise ValueError(f"Failed to parse SVG: {e}")
        
        raw_shapes = []
        
        print(f"[VECTOR] Parsing SVG geometry...")
        
        # --- 阶段 1: 提取所有原始几何体 (不关心坐标) ---
        for element in svg.elements():
            if not isinstance(element, (Path, Shape)):
                continue
            
            if element.fill is None or element.fill.value is None:
                continue
            
            rgb = (element.fill.red, element.fill.green, element.fill.blue)
            
            # 统一转为 Path
            if isinstance(element, Shape) and not isinstance(element, Path):
                try:
                    element = Path(element)
                except Exception:
                    continue
            
            try:
                # 采样点生成多边形
                # 这里我们先用一个相对安全的采样步长，后续不需重采，直接变换几何体
                path_len = element.length()
                if path_len == 0:
                    continue
                
                # 初始采样 (保证基本形状)
                step = 1.0  # 初始像素步长
                num_points = max(10, min(int(path_len / step), 2000))
                
                t_vals = np.linspace(0, 1, num_points)
                pts = [element.point(t) for t in t_vals]
                
                if len(pts) < 3:
                    continue
                
                poly = Polygon([(p.x, p.y) for p in pts])
                
                if not poly.is_valid:
                    poly = poly.buffer(0)
                
                if poly.is_valid and not poly.is_empty:
                    raw_shapes.append({'poly': poly, 'color': rgb})
                    
            except Exception as e:
                continue
        
        if not raw_shapes:
            raise ValueError("No valid shapes found in SVG")
        
        # --- 阶段 2: 计算全局物理边界 (Global BBox) ---
        # 将所有形状视为一个整体，计算它的真实边界
        all_polys = [item['poly'] for item in raw_shapes]
        
        # 使用 unary_union 可能较慢，我们直接用 bounds 列表计算
        # 这样速度极快且不容易出错
        min_xs, min_ys, max_xs, max_ys = [], [], [], []
        for p in all_polys:
            minx, miny, maxx, maxy = p.bounds
            min_xs.append(minx)
            min_ys.append(miny)
            max_xs.append(maxx)
            max_ys.append(maxy)
        
        global_min_x = min(min_xs)
        global_min_y = min(min_ys)
        global_max_x = max(max_xs)
        global_max_y = max(max_ys)
        
        real_w = global_max_x - global_min_x
        real_h = global_max_y - global_min_y
        
        print(f"[VECTOR] Global Geometry Bounds: x={global_min_x:.1f}, y={global_min_y:.1f}, w={real_w:.1f}, h={real_h:.1f}")
        
        if real_w == 0:
            raise ValueError("Invalid geometry width (0)")
        
        # --- 阶段 3: 计算缩放与归位 ---
        scale_factor = target_width_mm / real_w
        
        final_shapes = []
        
        # --- 阶段 4: 整体平移 (Shapely Affinity) ---
        # 直接操作几何对象，不操作点，这更稳健
        for item in raw_shapes:
            original_poly = item['poly']
            
            # 平移：所有形状减去 global_min_x/y，使其左上角归零
            shifted_poly = affinity.translate(original_poly, xoff=-global_min_x, yoff=-global_min_y)
            
            final_shapes.append({'poly': shifted_poly, 'color': item['color']})
        
        return final_shapes, scale_factor, (global_min_x, global_min_y, real_w, real_h)
    
    def _group_by_layers(self, shape_data, replacement_manager=None):
        """
        Group shapes by Z-layer and material ID.
        
        Each shape's color is matched to a 5-layer material stack.
        The shape is then distributed to the appropriate layers.
        
        Args:
            shape_data: List of {'poly': Polygon, 'color': (r,g,b)}
            
        Returns:
            dict: {z_layer: {mat_id: [polygons]}}
                Example: {0: {0: [poly1, poly2], 1: [poly3]}, 1: {...}}
        """
        layers = {}
        
        for item in shape_data:
            r, g, b = item['color']
            
            # Query KD-Tree for nearest LUT color
            query = np.array([[r, g, b]])
            _, index = self.img_processor.kdtree.query(query)

            # Get matched LUT color (for replacement lookup)
            matched_rgb = tuple(int(c) for c in self.img_processor.lut_rgb[index][0])

            # Apply replacement if provided (replacement keys are LUT colors)
            if replacement_manager is not None:
                replacement = replacement_manager.get_replacement(matched_rgb)
                if replacement is not None:
                    _, rep_index = self.img_processor.kdtree.query(np.array([replacement]))
                    index = rep_index

            # Get 5-layer material stack
            stack = self.img_processor.ref_stacks[index][0]
            
            # Distribute polygon to layers
            for z, mat_id in enumerate(stack):
                if z >= 5:  # Only use first 5 layers
                    break
                
                # Initialize nested dicts
                if z not in layers:
                    layers[z] = {}
                if mat_id not in layers[z]:
                    layers[z][mat_id] = []
                
                # Add polygon to this layer/material
                layers[z][mat_id].append(item['poly'])
        
        return layers
    
    def _perform_boolean_union(self, polygons):
        """
        Merge overlapping polygons using boolean union.
        
        This is equivalent to Clipper's union operation but uses
        Shapely's Python-native implementation.
        
        Args:
            polygons: List of Shapely Polygon objects
            
        Returns:
            Geometry: Merged result (Polygon or MultiPolygon)
        """
        if not polygons:
            return None
        
        return unary_union(polygons)
    
    def _extrude_geometry(self, geometry, height, z_offset, scale):
        """
        Extrude 2D geometry to 3D meshes.
        
        Handles both single Polygon and MultiPolygon geometries.
        
        Args:
            geometry: Shapely Polygon or MultiPolygon
            height: Extrusion height in mm
            z_offset: Z position of bottom face
            scale: Scale factor (SVG units to mm)
            
        Returns:
            list: List of trimesh.Trimesh objects
        """
        meshes = []
        
        if geometry is None or geometry.is_empty:
            return meshes
        
        # Handle both Polygon and MultiPolygon
        polys = geometry.geoms if hasattr(geometry, 'geoms') else [geometry]
        
        for poly in polys:
            if poly.is_empty:
                continue
            
            try:
                # Extrude polygon to 3D
                m = trimesh.creation.extrude_polygon(poly, height=height)
                
                # Apply scale (SVG units → mm)
                m.apply_scale([scale, scale, 1])
                
                # Apply Z translation
                m.apply_translation([0, 0, z_offset])
                
                meshes.append(m)
                
            except Exception as e:
                print(f"[VECTOR] Warning: Failed to extrude polygon: {e}")
                continue
        
        return meshes
    
    def _fix_coordinates(self, mesh, svg_height_mm):
        """
        Fix SVG coordinate system (Y-down) to 3D printer (Y-up).
        
        SVG uses Y-down coordinate system, but 3D printers use Y-up.
        This method flips the Y-axis and translates back to positive quadrant.
        
        Args:
            mesh: trimesh.Trimesh object (modified in-place)
            svg_height_mm: SVG height in millimeters
        """
        # Flip Y-axis
        transform = np.eye(4)
        transform[1, 1] = -1
        mesh.apply_transform(transform)
        
        # Translate back to positive quadrant
        # (Flipping around 0 makes everything negative)
        mesh.apply_translation([0, svg_height_mm, 0])
