"""
Lumina Studio - Color Replacement Manager

Manages color replacement mappings for preview and final model generation.
Supports CRUD operations on color mappings and batch application to images.
"""

from typing import Dict, Tuple, Optional, Any
import numpy as np
import cv2


def _parse_rgb_hex(hex_str: str) -> Tuple[int, int, int]:
    s = hex_str.strip().lower()
    if s.startswith("rgb"):
        import re

        m = re.search(r"rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", s)
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        raise ValueError(f"Invalid rgb format: {hex_str}")
    if not s.startswith("#"):
        s = "#" + s
    if len(s) != 7:
        raise ValueError(f"Invalid hex color: {hex_str}")
    return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))


def make_group_selection_token(quant_hex: str, matched_hex: str) -> str:
    return f"group|q={quant_hex.lower()}|m={matched_hex.lower()}"


def make_region_selection_token(
    quant_hex: str, matched_hex: str, seed_x: int, seed_y: int
) -> str:
    return f"region|q={quant_hex.lower()}|m={matched_hex.lower()}|x={int(seed_x)}|y={int(seed_y)}"


def parse_selection_token(token: str) -> Optional[Dict[str, Any]]:
    s = str(token).strip()
    if not s:
        return None
    if not s.startswith(("group|", "region|")):
        return None

    parts = s.split("|")
    mode = parts[0]
    parsed: Dict[str, Any] = {"mode": mode}
    for part in parts[1:]:
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        parsed[k] = v

    if "q" not in parsed:
        return None

    try:
        parsed["q_rgb"] = _parse_rgb_hex(str(parsed["q"]))
    except Exception:
        return None

    if "m" in parsed:
        try:
            parsed["m_rgb"] = _parse_rgb_hex(str(parsed["m"]))
        except Exception:
            parsed["m_rgb"] = None

    if mode == "region":
        try:
            parsed["x"] = int(str(parsed.get("x", -1)))
            parsed["y"] = int(str(parsed.get("y", -1)))
        except Exception:
            return None
    return parsed


def build_selection_mask(
    quantized_image: np.ndarray,
    mask_solid: np.ndarray,
    selection_token: str,
) -> np.ndarray:
    parsed = parse_selection_token(selection_token)
    if parsed is None:
        return np.zeros(mask_solid.shape, dtype=bool)

    q_rgb = np.array(parsed["q_rgb"], dtype=np.uint8)
    color_mask = np.all(quantized_image == q_rgb, axis=2) & mask_solid

    if parsed["mode"] == "group":
        return color_mask

    x = int(parsed.get("x", -1))
    y = int(parsed.get("y", -1))
    h, w = mask_solid.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return np.zeros(mask_solid.shape, dtype=bool)
    if not color_mask[y, x]:
        return np.zeros(mask_solid.shape, dtype=bool)

    cc_result = cv2.connectedComponents(color_mask.astype(np.uint8), connectivity=4)
    labels_count = int(cc_result[0])
    labels = cc_result[1]
    if labels_count <= 1:
        return color_mask
    label = labels[y, x]
    if label == 0:
        return np.zeros(mask_solid.shape, dtype=bool)
    return labels == label


def apply_replacements_with_selection(
    base_matched_rgb: np.ndarray,
    quantized_image: Optional[np.ndarray],
    mask_solid: np.ndarray,
    replacements: Optional[dict],
) -> np.ndarray:
    if not replacements:
        return base_matched_rgb.copy()

    result = base_matched_rgb.copy()
    for source, target in replacements.items():
        if target is None or str(target).strip() == "":
            continue
        try:
            target_rgb = np.array(_parse_rgb_hex(str(target)), dtype=np.uint8)
        except Exception:
            continue

        parsed = parse_selection_token(str(source))
        if parsed is not None and quantized_image is not None:
            selection_mask = build_selection_mask(
                quantized_image, mask_solid, str(source)
            )
            if np.any(selection_mask):
                result[selection_mask] = target_rgb
            continue

        try:
            source_rgb = np.array(_parse_rgb_hex(str(source)), dtype=np.uint8)
        except Exception:
            continue
        global_mask = np.all(base_matched_rgb == source_rgb, axis=2) & mask_solid
        if np.any(global_mask):
            result[global_mask] = target_rgb
    return result


def apply_replacements_to_material_matrix(
    base_material_matrix: np.ndarray,
    base_matched_rgb: np.ndarray,
    quantized_image: Optional[np.ndarray],
    mask_solid: np.ndarray,
    replacements: Optional[dict],
    lut_rgb: np.ndarray,
    ref_stacks: np.ndarray,
) -> np.ndarray:
    if not replacements:
        return base_material_matrix.copy()

    result = base_material_matrix.copy()
    lut_rgb_i32 = lut_rgb.astype(np.int32)

    for source, target in replacements.items():
        if target is None or str(target).strip() == "":
            continue
        try:
            target_tuple = _parse_rgb_hex(str(target))
        except Exception:
            continue

        parsed = parse_selection_token(str(source))
        if parsed is not None and quantized_image is not None:
            selection_mask = build_selection_mask(
                quantized_image, mask_solid, str(source)
            )
        else:
            try:
                source_tuple = _parse_rgb_hex(str(source))
            except Exception:
                continue
            source_rgb = np.array(source_tuple, dtype=np.uint8)
            selection_mask = np.all(base_matched_rgb == source_rgb, axis=2) & mask_solid

        if not np.any(selection_mask):
            continue

        target_rgb_i32 = np.array(target_tuple, dtype=np.int32)
        diff = lut_rgb_i32 - target_rgb_i32
        dist2 = np.sum(diff * diff, axis=1)
        lut_idx = int(np.argmin(dist2))
        target_stack = ref_stacks[lut_idx]
        result[selection_mask] = target_stack

    return result


class ColorReplacementManager:
    """
    Manages color replacement mappings for preview and final model generation.

    Color replacements allow users to swap specific colors in the preview
    with different colors before generating the final 3D model.
    """

    def __init__(self):
        """Initialize an empty color replacement manager."""
        self._replacements: Dict[Tuple[int, int, int], Tuple[int, int, int]] = {}

    def add_replacement(
        self, original: Tuple[int, int, int], replacement: Tuple[int, int, int]
    ) -> None:
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

    def get_replacement(
        self, original: Tuple[int, int, int]
    ) -> Optional[Tuple[int, int, int]]:
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
    def from_dict(cls, data: Dict) -> "ColorReplacementManager":
        """
        Create a ColorReplacementManager from a serialized dictionary.

        Args:
            data: Dictionary with hex color string keys and values

        Returns:
            New ColorReplacementManager instance with loaded mappings
        """
        manager = cls()
        for orig_hex, repl_hex in data.items():
            if parse_selection_token(str(orig_hex)) is not None:
                continue
            try:
                original = cls._hex_to_color(orig_hex)
                replacement = cls._hex_to_color(repl_hex)
                manager.add_replacement(original, replacement)
            except Exception:
                continue
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
        if hex_str.startswith("rgb"):
            import re

            # Extract numbers from rgb(r, g, b) or rgba(r, g, b, a)
            match = re.search(r"rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", hex_str)
            if match:
                return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            raise ValueError(f"Invalid rgb format: {hex_str}")

        # Handle hex format
        hex_str = hex_str.lstrip("#")
        if len(hex_str) != 6:
            raise ValueError(f"Invalid hex color: {hex_str}")
        return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))
