"""
Lumina Studio - Color Merger

Intelligent color merger for simplifying color palettes.
Identifies low-usage colors and merges them with perceptually similar
high-usage colors using CIELAB color space.
"""

from typing import Dict, List, Optional, Set, Tuple, Callable
import numpy as np


class ColorMerger:
    """
    Intelligent color merger for simplifying color palettes.
    
    This class identifies low-usage colors and merges them with
    perceptually similar high-usage colors using CIELAB color space.
    
    The merger uses Delta-E (CIE76) distance metric to find perceptually
    similar colors, ensuring that merged colors look natural to the human eye.
    """
    
    # Default configuration values
    DEFAULT_THRESHOLD_PERCENT = 0.5  # Default usage threshold (0.5%)
    DEFAULT_MAX_DISTANCE = 20.0      # Default max Delta-E distance
    
    def __init__(self, rgb_to_lab_func: Callable):
        """
        Initialize the color merger.
        
        Args:
            rgb_to_lab_func: Function to convert RGB to LAB color space.
                            Should accept np.ndarray of shape (N, 3) with dtype uint8
                            and return np.ndarray of shape (N, 3) with LAB values.
                            Example: LuminaImageProcessor._rgb_to_lab
        """
        self.rgb_to_lab = rgb_to_lab_func
    
    def identify_low_usage_colors(self, palette: List[dict], 
                                  threshold_percent: float) -> List[str]:
        """
        Identify colors with usage below threshold.
        
        Args:
            palette: Color palette from extract_color_palette()
                    Each entry should have 'hex' and 'percentage' keys
            threshold_percent: Minimum usage percentage (0.1 to 5.0)
        
        Returns:
            List of hex color codes for low usage colors
        
        Example:
            >>> palette = [
            ...     {'hex': '#ff0000', 'percentage': 10.5},
            ...     {'hex': '#00ff00', 'percentage': 0.3},
            ...     {'hex': '#0000ff', 'percentage': 89.2}
            ... ]
            >>> merger = ColorMerger(some_rgb_to_lab_func)
            >>> low_usage = merger.identify_low_usage_colors(palette, 0.5)
            >>> print(low_usage)
            ['#00ff00']
        """
        low_usage_colors = []
        
        for entry in palette:
            hex_color = entry['hex']
            percentage = entry['percentage']
            
            if percentage < threshold_percent:
                low_usage_colors.append(hex_color)
        
        return low_usage_colors
    
    def calculate_color_distance(self, color1_rgb: Tuple[int, int, int],
                                color2_rgb: Tuple[int, int, int]) -> float:
        """
        Calculate perceptual distance between two colors using Delta-E (CIE76).
        
        The Delta-E distance is calculated in CIELAB color space using the formula:
        Delta-E = sqrt((L2-L1)² + (a2-a1)² + (b2-b1)²)
        
        Args:
            color1_rgb: RGB tuple (0-255)
            color2_rgb: RGB tuple (0-255)
        
        Returns:
            Delta-E distance (CIE76 formula)
        
        Example:
            >>> merger = ColorMerger(some_rgb_to_lab_func)
            >>> distance = merger.calculate_color_distance((255, 0, 0), (250, 0, 0))
            >>> print(f"Distance: {distance:.2f}")
            Distance: 2.34
        """
        # Convert RGB tuples to numpy arrays
        rgb1 = np.array([color1_rgb], dtype=np.uint8)
        rgb2 = np.array([color2_rgb], dtype=np.uint8)
        
        # Convert to LAB color space
        lab1 = self.rgb_to_lab(rgb1)[0]  # Shape: (3,)
        lab2 = self.rgb_to_lab(rgb2)[0]  # Shape: (3,)
        
        # Calculate Euclidean distance in LAB space (Delta-E CIE76)
        delta_e = np.sqrt(np.sum((lab2 - lab1) ** 2))
        
        return float(delta_e)
    
    def find_merge_target(self, source_color: str, palette: List[dict],
                         max_distance: float, 
                         excluded_colors: Set[str]) -> Optional[str]:
        """
        Find the best merge target for a low usage color.
        
        The best target is the color with:
        1. Smallest Delta-E distance to the source color
        2. Not in the excluded_colors set (other low usage colors)
        3. Distance within max_distance threshold
        4. If multiple colors have the same distance, select the one with highest usage
        
        Args:
            source_color: Hex color code to merge
            palette: Color palette with usage information
            max_distance: Maximum Delta-E distance for merging
            excluded_colors: Set of colors to exclude (other low usage colors)
        
        Returns:
            Hex color code of merge target, or None if no suitable target found
        
        Example:
            >>> palette = [
            ...     {'hex': '#ff0000', 'color': (255, 0, 0), 'percentage': 10.5},
            ...     {'hex': '#fe0000', 'color': (254, 0, 0), 'percentage': 0.3},
            ...     {'hex': '#0000ff', 'color': (0, 0, 255), 'percentage': 89.2}
            ... ]
            >>> merger = ColorMerger(some_rgb_to_lab_func)
            >>> target = merger.find_merge_target('#fe0000', palette, 20.0, {'#fe0000'})
            >>> print(target)
            '#ff0000'
        """
        # Find source color entry
        source_entry = None
        for entry in palette:
            if entry['hex'] == source_color:
                source_entry = entry
                break
        
        if source_entry is None:
            return None
        
        source_rgb = source_entry['color']
        
        # Find all candidate targets (not excluded, not source itself)
        candidates = []
        for entry in palette:
            hex_color = entry['hex']
            
            # Skip excluded colors and source color itself
            if hex_color in excluded_colors or hex_color == source_color:
                continue
            
            target_rgb = entry['color']
            distance = self.calculate_color_distance(source_rgb, target_rgb)
            
            # Only consider colors within max_distance
            if distance <= max_distance:
                candidates.append({
                    'hex': hex_color,
                    'distance': distance,
                    'percentage': entry['percentage']
                })
        
        if not candidates:
            return None
        
        # Sort by distance (ascending), then by percentage (descending)
        # This ensures we pick the closest color, and if there are ties,
        # we pick the one with highest usage
        candidates.sort(key=lambda x: (x['distance'], -x['percentage']))
        
        return candidates[0]['hex']
    
    def build_merge_map(self, palette: List[dict], 
                       threshold_percent: float,
                       max_distance: float) -> Dict[str, str]:
        """
        Build a complete merge map for all low usage colors.
        
        This method:
        1. Identifies all low usage colors
        2. For each low usage color, finds the best merge target
        3. Returns a mapping from source colors to target colors
        
        Edge cases handled:
        - Empty palette: returns empty dict
        - Single color: returns empty dict
        - All colors below threshold: returns empty dict (to prevent color loss)
        - No suitable targets: colors without targets are not included in map
        
        Args:
            palette: Color palette from extract_color_palette()
            threshold_percent: Minimum usage percentage
            max_distance: Maximum Delta-E distance
        
        Returns:
            Dict mapping source hex colors to target hex colors
        
        Example:
            >>> palette = [
            ...     {'hex': '#ff0000', 'color': (255, 0, 0), 'percentage': 50.0},
            ...     {'hex': '#fe0000', 'color': (254, 0, 0), 'percentage': 0.3},
            ...     {'hex': '#0000ff', 'color': (0, 0, 255), 'percentage': 49.7}
            ... ]
            >>> merger = ColorMerger(some_rgb_to_lab_func)
            >>> merge_map = merger.build_merge_map(palette, 0.5, 20.0)
            >>> print(merge_map)
            {'#fe0000': '#ff0000'}
        """
        # Validate inputs
        threshold_percent = max(0.1, min(5.0, threshold_percent))
        max_distance = max(5.0, min(50.0, max_distance))
        
        # Handle edge cases
        if not palette:
            return {}
        
        if len(palette) == 1:
            return {}
        
        # Identify low usage colors
        low_usage_colors = self.identify_low_usage_colors(palette, threshold_percent)
        
        # If all colors are low usage, don't merge (prevent color loss)
        if len(low_usage_colors) >= len(palette):
            print("[COLOR_MERGER] Warning: All colors below threshold, merging disabled")
            return {}
        
        # If no low usage colors, nothing to merge
        if not low_usage_colors:
            return {}
        
        # Build merge map
        merge_map = {}
        excluded_colors = set(low_usage_colors)
        
        for source_hex in low_usage_colors:
            target_hex = self.find_merge_target(
                source_hex, palette, max_distance, excluded_colors
            )
            
            if target_hex is not None:
                merge_map[source_hex] = target_hex
            else:
                print(f"[COLOR_MERGER] No suitable target for {source_hex}, keeping original")
        
        return merge_map
    
    def apply_color_merging(self, matched_rgb: np.ndarray,
                           merge_map: Dict[str, str]) -> np.ndarray:
        """
        Apply color merging to an image array.
        
        This method replaces all pixels of source colors with their
        corresponding target colors according to the merge_map.
        
        Args:
            matched_rgb: Image array (H, W, 3) with RGB values (dtype uint8)
            merge_map: Dict mapping source hex to target hex colors
        
        Returns:
            Modified image array with merged colors (original is not modified)
        
        Example:
            >>> image = np.array([[[255, 0, 0], [254, 0, 0]]], dtype=np.uint8)
            >>> merge_map = {'#fe0000': '#ff0000'}
            >>> merger = ColorMerger(some_rgb_to_lab_func)
            >>> merged = merger.apply_color_merging(image, merge_map)
            >>> print(merged)
            [[[255   0   0]
              [255   0   0]]]
        """
        if not merge_map:
            return matched_rgb.copy()
        
        result = matched_rgb.copy()
        
        for source_hex, target_hex in merge_map.items():
            # Convert hex to RGB
            source_rgb = self._hex_to_rgb(source_hex)
            target_rgb = self._hex_to_rgb(target_hex)
            
            # Find all pixels matching source color
            mask = np.all(matched_rgb == source_rgb, axis=-1)
            
            # Replace with target color
            result[mask] = target_rgb
        
        return result
    
    def calculate_quality_metric(self, original_palette: List[dict],
                                 merged_palette: List[dict],
                                 merge_map: Dict[str, str]) -> float:
        """
        Calculate quality metric showing perceptual difference before and after merging.
        
        The quality metric is a value between 0 and 100:
        - 100: No colors were merged (perfect quality)
        - 0: Maximum perceptual difference
        
        The metric is calculated based on:
        1. Number of colors merged (fewer merges = higher quality)
        2. Average Delta-E distance of merged colors (smaller distances = higher quality)
        3. Usage percentage of merged colors (merging low-usage colors has less impact)
        
        Args:
            original_palette: Original color palette before merging
            merged_palette: Color palette after merging
            merge_map: Dict mapping source hex to target hex colors
        
        Returns:
            Quality metric (0-100), where 100 is perfect quality
        
        Example:
            >>> original = [
            ...     {'hex': '#ff0000', 'color': (255, 0, 0), 'percentage': 50.0},
            ...     {'hex': '#fe0000', 'color': (254, 0, 0), 'percentage': 0.3},
            ...     {'hex': '#0000ff', 'color': (0, 0, 255), 'percentage': 49.7}
            ... ]
            >>> merged = [
            ...     {'hex': '#ff0000', 'color': (255, 0, 0), 'percentage': 50.3},
            ...     {'hex': '#0000ff', 'color': (0, 0, 255), 'percentage': 49.7}
            ... ]
            >>> merge_map = {'#fe0000': '#ff0000'}
            >>> merger = ColorMerger(some_rgb_to_lab_func)
            >>> quality = merger.calculate_quality_metric(original, merged, merge_map)
            >>> print(f"Quality: {quality:.1f}")
            Quality: 98.5
        """
        # If no merging occurred, quality is perfect
        if not merge_map:
            return 100.0
        
        # Build palette lookup
        palette_dict = {entry['hex']: entry for entry in original_palette}
        
        # Calculate weighted average Delta-E distance
        total_weight = 0.0
        weighted_distance = 0.0
        
        for source_hex, target_hex in merge_map.items():
            source_entry = palette_dict[source_hex]
            target_entry = palette_dict[target_hex]
            
            # Calculate distance
            distance = self.calculate_color_distance(
                source_entry['color'],
                target_entry['color']
            )
            
            # Weight by usage percentage (low usage colors have less impact)
            weight = source_entry['percentage']
            weighted_distance += distance * weight
            total_weight += weight
        
        if total_weight == 0:
            return 100.0
        
        avg_distance = weighted_distance / total_weight
        
        # Convert distance to quality score
        # Typical Delta-E values:
        # 0-1: Not perceptible
        # 1-2: Perceptible through close observation
        # 2-10: Perceptible at a glance
        # 10-50: Colors are more different than similar
        # 50+: Colors are completely different
        
        # Map distance to quality score (0-100)
        # Use exponential decay: quality = 100 * exp(-distance / scale)
        # where scale is chosen so that distance=20 gives quality~50
        scale = 20.0 / np.log(2)  # ~28.85
        
        # Clamp to avoid overflow and ensure 0-100 range
        avg_distance = min(avg_distance, 200.0)  # Cap at 200 Delta-E
        quality = 100.0 * np.exp(-avg_distance / scale)
        quality = max(0.0, min(100.0, quality))  # Clamp to [0, 100]
        
        return float(quality)
    
    @staticmethod
    def _hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
        """Convert hex string to RGB tuple."""
        hex_str = hex_str.lstrip('#')
        return (
            int(hex_str[0:2], 16),
            int(hex_str[2:4], 16),
            int(hex_str[4:6], 16)
        )
