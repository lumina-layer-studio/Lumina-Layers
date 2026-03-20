"""
Lumina Studio - Color Replacement Manager

Manages color replacement mappings for preview and final model generation.
Supports CRUD operations on color mappings and batch application to images.
"""

from typing import Dict, Tuple, Optional, List
import numpy as np


class ColorReplacementManager:
    """
    Manages color replacement mappings for preview and final model generation.
    
    Color replacements allow users to swap specific colors in the preview
    with different colors before generating the final 3D model.
    """

    def __init__(self):
        """Initialize an empty color replacement manager."""
        self._replacements: Dict[Tuple[int, int, int], Tuple[int, int, int]] = {}

    def add_replacement(self, original: Tuple[int, int, int],
                       replacement: Tuple[int, int, int]) -> None:
        """
        Add or update a color replacement mapping.
        
        Args:
            original: Original RGB color tuple (R, G, B) with values 0-255
            replacement: Replacement RGB color tuple (R, G, B) with values 0-255
            
        Note:
            If original == replacement, the mapping is ignored (not added).
        """
        # Validate inputs
        original = self._validate_color(original)
        replacement = self._validate_color(replacement)
        
        # Don't add if colors are the same
        if original == replacement:
            return
        
        self._replacements[original] = replacement

    def remove_replacement(self, original: Tuple[int, int, int]) -> bool:
        """
        Remove a color replacement mapping.
        
        Args:
            original: Original RGB color tuple to remove
            
        Returns:
            True if the mapping was found and removed, False otherwise
        """
        original = self._validate_color(original)
        if original in self._replacements:
            del self._replacements[original]
            return True
        return False

    def get_replacement(self, original: Tuple[int, int, int]) -> Optional[Tuple[int, int, int]]:
        """
        Get the replacement color for an original color.
        
        Args:
            original: Original RGB color tuple
            
        Returns:
            Replacement RGB color tuple, or None if not mapped
        """
        original = self._validate_color(original)
        return self._replacements.get(original)

    def apply_to_image(self, rgb_array: np.ndarray) -> np.ndarray:
        """
        Apply all color replacements to an RGB image array.
        
        Args:
            rgb_array: NumPy array of shape (H, W, 3) with dtype uint8
            
        Returns:
            New NumPy array with replacements applied (original is not modified)
        """
        if len(self._replacements) == 0:
            return rgb_array.copy()
        
        result = rgb_array.copy()
        
        for original, replacement in self._replacements.items():
            # Create mask for pixels matching original color
            mask = np.all(rgb_array == original, axis=-1)
            result[mask] = replacement
        
        return result

    def clear(self) -> None:
        """Clear all color replacements."""
        self._replacements.clear()

    def __len__(self) -> int:
        """Return the number of color replacements."""
        return len(self._replacements)

    def __contains__(self, original: Tuple[int, int, int]) -> bool:
        """Check if a color has a replacement mapping."""
        original = self._validate_color(original)
        return original in self._replacements

    def get_all_replacements(self) -> Dict[Tuple[int, int, int], Tuple[int, int, int]]:
        """
        Get all color replacement mappings.
        
        Returns:
            Dictionary mapping original colors to replacement colors
        """
        return self._replacements.copy()

    def to_dict(self) -> Dict:
        """
        Export replacements as a JSON-serializable dictionary.
        
        Returns:
            Dictionary with string keys (hex colors) for JSON serialization
        """
        return {
            self._color_to_hex(orig): self._color_to_hex(repl)
            for orig, repl in self._replacements.items()
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ColorReplacementManager':
        """
        Create a ColorReplacementManager from a serialized dictionary.
        
        Args:
            data: Dictionary with hex color string keys and values
            
        Returns:
            New ColorReplacementManager instance with loaded mappings
        """
        manager = cls()
        for orig_hex, repl_hex in data.items():
            original = cls._hex_to_color(orig_hex)
            replacement = cls._hex_to_color(repl_hex)
            manager.add_replacement(original, replacement)
        return manager

    @staticmethod
    def _validate_color(color: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """
        Validate and normalize a color tuple.
        
        Args:
            color: RGB color tuple
            
        Returns:
            Normalized color tuple with values clamped to 0-255
            
        Raises:
            ValueError: If color is not a valid RGB tuple
        """
        if not isinstance(color, (tuple, list)) or len(color) != 3:
            raise ValueError(f"Color must be a tuple of 3 integers, got {color}")
        
        return tuple(max(0, min(255, int(c))) for c in color)

    @staticmethod
    def _color_to_hex(color: Tuple[int, int, int]) -> str:
        """Convert RGB tuple to hex string."""
        return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"

    @staticmethod
    def _hex_to_color(hex_str: str) -> Tuple[int, int, int]:
        """Convert hex string or rgb() string to RGB tuple.
        
        Supports formats:
        - '#RRGGBB' or 'RRGGBB'
        - 'rgb(r, g, b)' or 'rgba(r, g, b, a)'
        """
        hex_str = hex_str.strip()
        
        # Handle rgb() or rgba() format from Gradio ColorPicker
        if hex_str.startswith('rgb'):
            import re
            # Extract numbers from rgb(r, g, b) or rgba(r, g, b, a)
            match = re.search(r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', hex_str)
            if match:
                return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            raise ValueError(f"Invalid rgb format: {hex_str}")
        
        # Handle hex format
        hex_str = hex_str.lstrip('#')
        if len(hex_str) != 6:
            raise ValueError(f"Invalid hex color: {hex_str}")
        return (
            int(hex_str[0:2], 16),
            int(hex_str[2:4], 16),
            int(hex_str[4:6], 16)
        )
