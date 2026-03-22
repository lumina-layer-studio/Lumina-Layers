"""
Lumina Studio - Color Recipe Logger

Records color mapping information for debugging and reference.
Generates a text file documenting:
- Original colors from the image
- Matched LUT colors
- Material stacking recipes
- LUT file information
"""

import os
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional


class ColorRecipeLogger:
    """
    Logs color mapping and stacking recipes to a text file.
    """
    
    def __init__(self, lut_path: str, lut_rgb: np.ndarray, ref_stacks: np.ndarray, color_mode: str, metadata=None):
        """
        Initialize the logger.
        
        Args:
            lut_path: Path to the LUT file
            lut_rgb: LUT RGB array (N, 3)
            ref_stacks: Reference stacks array (N, 5)
            color_mode: Color mode string (e.g., "8-Color")
            metadata: Optional LUTMetadata with palette info (可选的 LUT 元数据)
        """
        self.lut_path = lut_path
        self.lut_filename = os.path.basename(lut_path)
        self.lut_rgb = lut_rgb
        self.ref_stacks = ref_stacks
        self.color_mode = color_mode
        self.metadata = metadata
        
        # Extract color names from LUT filename if possible
        self.color_names = self._extract_color_names_from_filename()
        
        # If metadata has palette, prefer palette color names
        if metadata and hasattr(metadata, 'palette') and metadata.palette:
            self.color_names = [e.color for e in metadata.palette]
        
        # Color mappings to record
        self.mappings: List[Dict] = []
    
    def _extract_color_names_from_filename(self) -> Optional[List[str]]:
        """
        Infer color names from actual RGB values in LUT, not from filename.
        
        This is more reliable because LUT filenames may not match the actual
        data order (e.g., filename says "大红-品红-青-..." but actual data
        is ordered as "白-青-品红-...").
        
        Returns:
            List of color names based on RGB analysis
        """
        if self.lut_rgb is None or len(self.lut_rgb) < 8:
            return None
        
        # Analyze first 8 colors (base colors) by RGB values
        color_names = []
        
        for i in range(min(8, len(self.lut_rgb))):
            rgb = self.lut_rgb[i]
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
            
            # Infer color name from RGB values
            # Use perceptual thresholds to identify colors
            if r > 240 and g > 240 and b > 240:
                name = "白色/White"
            elif r < 15 and g < 15 and b < 15:
                name = "黑色/Black"
            elif r > 200 and g < 100 and b < 100:
                name = "红色/Red"
            elif r < 120 and g > 150 and b < 120:
                name = "绿色/Green"
            elif r < 50 and g > 100 and b > 180:
                # 青色: 低红, 中高绿, 高蓝 (例如 RGB(0, 132, 212))
                name = "青色/Cyan"
            elif r < 50 and g < 100 and b > 120:
                # 深蓝: 低红, 低绿, 中高蓝 (例如 RGB(0, 53, 142))
                name = "蓝色/Blue"
            elif r > 180 and g < 100 and b > 150:
                name = "品红/Magenta"
            elif r > 200 and g > 200 and b < 100:
                name = "黄色/Yellow"
            elif r > 150 and g > 100 and b < 100:
                name = "橙色/Orange"
            else:
                # Fallback: describe by dominant channel
                max_channel = max(r, g, b)
                if max_channel == r:
                    name = f"红调/Reddish"
                elif max_channel == g:
                    name = f"绿调/Greenish"
                else:
                    name = f"蓝调/Blueish"
            
            color_names.append(name)
        
        return color_names
    
    def _get_color_name(self, material_id: int) -> str:
        """
        Get color name for a material ID.
        
        Args:
            material_id: Material ID (0-7 for 8-color)
        
        Returns:
            Color name string
        """
        if self.color_names and 0 <= material_id < len(self.color_names):
            return self.color_names[material_id]
        
        # Fallback to generic names
        generic_names = {
            0: 'Color_0',
            1: 'Color_1',
            2: 'Color_2',
            3: 'Color_3',
            4: 'Color_4',
            5: 'Color_5',
            6: 'Color_6',
            7: 'Color_7'
        }
        return generic_names.get(material_id, f'Color_{material_id}')
    
    def add_mapping(self, original_rgb: Tuple[int, int, int], 
                   matched_rgb: Tuple[int, int, int],
                   lut_index: int,
                   pixel_count: int = 0):
        """
        Add a color mapping record.
        
        Args:
            original_rgb: Original color from image (R, G, B)
            matched_rgb: Matched LUT color (R, G, B)
            lut_index: Index in LUT array
            pixel_count: Number of pixels with this color
        """
        # Get stacking recipe
        # Note: self.ref_stacks already stores stacks in bottom-to-top order
        # (after the reversed() conversion in _load_lut)
        stack = self.ref_stacks[lut_index]
        
        # Convert stack to color names (stack is already bottom-to-top)
        stack_names_bottom_to_top = [self._get_color_name(int(mat_id)) for mat_id in stack]
        stack_names_top_to_bottom = list(reversed(stack_names_bottom_to_top))
        
        mapping = {
            'original_rgb': original_rgb,
            'original_hex': f'#{original_rgb[0]:02x}{original_rgb[1]:02x}{original_rgb[2]:02x}',
            'matched_rgb': matched_rgb,
            'matched_hex': f'#{matched_rgb[0]:02x}{matched_rgb[1]:02x}{matched_rgb[2]:02x}',
            'lut_index': lut_index,
            'stack_indices': [int(x) for x in stack],
            'stack_names_bottom_to_top': stack_names_bottom_to_top,
            'stack_names_top_to_bottom': stack_names_top_to_bottom,
            'pixel_count': pixel_count
        }
        
        self.mappings.append(mapping)
    
    def generate_report(self, output_path: str, model_filename: str):
        """
        Generate and save the color recipe report.
        
        Args:
            output_path: Path to save the report file
            model_filename: Name of the generated 3MF file
        """
        lines = []
        
        # Header
        lines.append("=" * 80)
        lines.append("Lumina Layers - 颜色配方记录 / Color Recipe Report")
        lines.append("=" * 80)
        lines.append("")
        
        # Metadata
        lines.append(f"生成时间 / Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"LUT 文件 / LUT File: {self.lut_filename}")
        lines.append(f"颜色模式 / Color Mode: {self.color_mode}")
        lines.append(f"模型文件 / Model File: {model_filename}")
        lines.append(f"总颜色数 / Total Colors: {len(self.mappings)}")
        lines.append("")
        
        # Material Slot Order (not LUT order)
        lines.append("-" * 80)
        lines.append("材料槽位顺序 / Material Slot Order")
        lines.append("-" * 80)
        
        # Show material slots with their representative colors
        # Find a pure stack for each material to get its RGB
        material_rgb_map = {}
        for lut_idx in range(len(self.ref_stacks)):
            stack = self.ref_stacks[lut_idx]
            # Check if this is a pure color (all layers same material)
            if len(set(stack)) == 1:
                material_id = stack[0]
                if material_id >= 0 and material_id not in material_rgb_map:
                    material_rgb_map[material_id] = self.lut_rgb[lut_idx]
        
        # Display material slots
        for i in range(min(8, len(self.color_names) if self.color_names else 8)):
            color_name = self._get_color_name(i)
            if i in material_rgb_map:
                rgb = material_rgb_map[i]
                hex_color = f'#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}'
                lines.append(f"  槽位 {i}: {color_name:15s} RGB({int(rgb[0]):3d}, {int(rgb[1]):3d}, {int(rgb[2]):3d}) = {hex_color}")
            else:
                lines.append(f"  槽位 {i}: {color_name:15s} (未找到纯色样本)")
        lines.append("")
        
        # Color Mappings
        lines.append("-" * 80)
        lines.append("颜色映射 / Color Mappings")
        lines.append("-" * 80)
        lines.append("")
        
        # Sort by pixel count (most common colors first)
        sorted_mappings = sorted(self.mappings, key=lambda x: x['pixel_count'], reverse=True)
        
        for idx, mapping in enumerate(sorted_mappings, 1):
            lines.append(f"[{idx}] 原始颜色 / Original Color: {mapping['original_hex']}")
            lines.append(f"    RGB: ({mapping['original_rgb'][0]}, {mapping['original_rgb'][1]}, {mapping['original_rgb'][2]})")
            
            if mapping['pixel_count'] > 0:
                lines.append(f"    像素数 / Pixel Count: {mapping['pixel_count']:,}")
            
            lines.append(f"")
            lines.append(f"    匹配颜色 / Matched Color: {mapping['matched_hex']}")
            lines.append(f"    RGB: ({mapping['matched_rgb'][0]}, {mapping['matched_rgb'][1]}, {mapping['matched_rgb'][2]})")
            lines.append(f"    LUT 索引 / LUT Index: {mapping['lut_index']}")
            lines.append(f"")
            
            # Stacking recipe (bottom to top)
            lines.append(f"    堆叠配方 (底→顶) / Stack Recipe (Bottom→Top):")
            stack_str = " -> ".join(mapping['stack_names_bottom_to_top'])
            lines.append(f"      {stack_str}")
            lines.append(f"      索引 / Indices: {mapping['stack_indices']}")
            lines.append(f"")
            
            # Stacking recipe (top to bottom)
            lines.append(f"    堆叠配方 (顶→底) / Stack Recipe (Top→Bottom):")
            stack_str = " -> ".join(mapping['stack_names_top_to_bottom'])
            lines.append(f"      {stack_str}")
            lines.append(f"      索引 / Indices: {list(reversed(mapping['stack_indices']))}")
            lines.append("")
            lines.append("-" * 80)
            lines.append("")
        
        # Footer
        lines.append("")
        lines.append("=" * 80)
        lines.append("说明 / Notes:")
        lines.append("  - 堆叠配方显示了 5 层材料的排列顺序")
        lines.append("  - Stack recipe shows the arrangement of 5 material layers")
        lines.append("  - 底→顶：从打印床到观赏面 / Bottom→Top: From build plate to viewing surface")
        lines.append("  - 顶→底：从观赏面到打印床 / Top→Bottom: From viewing surface to build plate")
        lines.append("=" * 80)
        
        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"[COLOR_RECIPE] ✅ Color recipe saved: {output_path}")
    
    @staticmethod
    def create_from_processor(processor, output_dir: str, model_filename: str,
                             matched_rgb: np.ndarray, material_matrix: np.ndarray,
                             mask_solid: np.ndarray, metadata=None):
        """
        Create a color recipe logger from image processor results.
        
        Args:
            processor: LuminaImageProcessor instance
            output_dir: Output directory for the report
            model_filename: Name of the 3MF file
            matched_rgb: Matched RGB array (H, W, 3)
            material_matrix: Material matrix (H, W, 5)
            mask_solid: Solid mask (H, W)
            metadata: Optional LUTMetadata with palette info (可选的 LUT 元数据)
        
        Returns:
            Path to the generated report file
        """
        logger = ColorRecipeLogger(
            lut_path=processor.lut_path if hasattr(processor, 'lut_path') else 'unknown.npy',
            lut_rgb=processor.lut_rgb,
            ref_stacks=processor.ref_stacks,
            color_mode=processor.color_mode,
            metadata=metadata,
        )
        
        # Extract unique colors and their pixel counts
        solid_rgb = matched_rgb[mask_solid]
        solid_materials = material_matrix[mask_solid]
        
        # Find unique color-stack combinations
        unique_colors = {}
        for i in range(len(solid_rgb)):
            rgb_tuple = tuple(solid_rgb[i])
            stack_tuple = tuple(solid_materials[i])
            
            key = (rgb_tuple, stack_tuple)
            if key not in unique_colors:
                unique_colors[key] = 0
            unique_colors[key] += 1
        
        # Add mappings
        for (rgb_tuple, stack_tuple), count in unique_colors.items():
            # Find LUT index by matching RGB
            lut_index = -1
            for idx, lut_color in enumerate(processor.lut_rgb):
                if tuple(lut_color) == rgb_tuple:
                    lut_index = idx
                    break
            
            if lut_index == -1:
                # Fallback: find closest match
                distances = np.sum(np.abs(processor.lut_rgb.astype(int) - np.array(rgb_tuple).astype(int)), axis=1)
                lut_index = np.argmin(distances)
            
            logger.add_mapping(
                original_rgb=rgb_tuple,  # In this case, we don't have the original, so use matched
                matched_rgb=rgb_tuple,
                lut_index=lut_index,
                pixel_count=count
            )
        
        # Generate report
        base_name = os.path.splitext(model_filename)[0]
        report_filename = f"{base_name}_color_recipe.txt"
        report_path = os.path.join(output_dir, report_filename)
        
        logger.generate_report(report_path, model_filename)
        
        return report_path
