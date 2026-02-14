"""
Color Mode Strategies

Each strategy handles LUT loading for a specific color mode:
- FourColorStrategy: CMYW/RYBW (1024 colors)
- SixColorStrategy: 6-Color Smart 1296 (1296 colors)
- EightColorStrategy: 8-Color Max (2738 colors)
"""

from abc import ABC, abstractmethod
from typing import Tuple
import numpy as np
from scipy.spatial import KDTree

from config import ColorMode


class ColorModeStrategy(ABC):
    """
    Abstract base class for color mode strategies.

    Each strategy is responsible for:
    1. Loading and validating LUT data
    2. Building stacking sequences
    3. Filtering outliers if needed
    4. Building KD-Tree for color matching
    """

    @abstractmethod
    def load_lut(self, lut_path: str) -> Tuple[np.ndarray, np.ndarray, KDTree]:
        """
        Load LUT file and return processed data.

        Args:
            lut_path: Path to .npy LUT file

        Returns:
            Tuple of (lut_rgb, ref_stacks, kdtree):
            - lut_rgb: (N, 3) RGB color array
            - ref_stacks: (N, 5) stacking sequence array
            - kdtree: KD-Tree for color matching
        """
        pass

    @abstractmethod
    def get_mode_name(self) -> str:
        """Return the display name of this color mode."""
        pass


class FourColorStrategy(ColorModeStrategy):
    """
    Strategy for 4-color standard modes (CMYW/RYBW).

    Features:
    - 1024 colors (4^5 combinations)
    - Blue outlier filtering
    - Standard 5-layer stacking
    """

    def __init__(self, color_mode: ColorMode):
        self.color_mode = color_mode

    def load_lut(self, lut_path: str) -> Tuple[np.ndarray, np.ndarray, KDTree]:
        """Load 4-color LUT with blue filtering."""
        try:
            lut_grid = np.load(lut_path)
            measured_colors = lut_grid.reshape(-1, 3)
            total_colors = measured_colors.shape[0]
        except Exception as e:
            raise ValueError(f"❌ LUT file corrupted: {e}")

        print(f"[FourColorStrategy] Loading 4-Color LUT ({total_colors} points)...")

        valid_rgb = []
        valid_stacks = []

        # Blue outlier filtering
        base_blue = np.array([30, 100, 200])
        dropped = 0

        for i in range(1024):
            if i >= total_colors:
                break

            # Rebuild 4-base stacking (0..1023)
            digits = []
            temp = i
            for _ in range(5):
                digits.append(temp % 4)
                temp //= 4
            stack = digits[::-1]

            real_rgb = measured_colors[i]

            # Filter outliers: close to blue but doesn't contain blue
            dist = np.linalg.norm(real_rgb - base_blue)
            if dist < 60 and 3 not in stack:  # 3 is Blue in RYBW/CMYW
                dropped += 1
                continue

            valid_rgb.append(real_rgb)
            valid_stacks.append(stack)

        lut_rgb = np.array(valid_rgb)
        ref_stacks = np.array(valid_stacks)
        kdtree = KDTree(lut_rgb)

        print(f"[OK] LUT loaded: {len(lut_rgb)} colors (filtered {dropped} outliers)")

        return lut_rgb, ref_stacks, kdtree

    def get_mode_name(self) -> str:
        return "4-Color Standard"


class SixColorStrategy(ColorModeStrategy):
    """
    Strategy for 6-Color Smart 1296 mode.

    Features:
    - 1296 colors (36x36 grid)
    - Intelligent stacking order
    - No outlier filtering (colors too complex)
    """

    def __init__(self, color_mode: ColorMode):
        self.color_mode = color_mode

    def load_lut(self, lut_path: str) -> Tuple[np.ndarray, np.ndarray, KDTree]:
        """Load 6-color LUT with smart stacking order."""
        try:
            lut_grid = np.load(lut_path)
            measured_colors = lut_grid.reshape(-1, 3)
            total_colors = measured_colors.shape[0]
        except Exception as e:
            raise ValueError(f"❌ LUT file corrupted: {e}")

        print(f"[SixColorStrategy] Loading 6-Color LUT ({total_colors} points)...")

        from core.calibration import get_top_1296_colors

        # Retrieve 1296 intelligent stacking order
        smart_stacks = get_top_1296_colors()

        # Reverse stacking order for Face-Down printing
        # Original: [Bottom, ..., Top] -> Convert to [Top, ..., Bottom]
        smart_stacks = [tuple(reversed(s)) for s in smart_stacks]
        print(
            "[SixColorStrategy] Stacks reversed for Face-Down printing compatibility."
        )

        if len(smart_stacks) != total_colors:
            print(
                f"⚠️ Warning: Stacks count ({len(smart_stacks)}) != LUT count ({total_colors})"
            )
            min_len = min(len(smart_stacks), total_colors)
            smart_stacks = smart_stacks[:min_len]
            measured_colors = measured_colors[:min_len]

        lut_rgb = measured_colors
        ref_stacks = np.array(smart_stacks)
        kdtree = KDTree(lut_rgb)

        print(f"✅ LUT loaded: {len(lut_rgb)} colors (6-Color mode)")

        return lut_rgb, ref_stacks, kdtree

    def get_mode_name(self) -> str:
        return "6-Color Smart 1296"


class EightColorStrategy(ColorModeStrategy):
    """
    Strategy for 8-Color Max mode.

    Features:
    - 2738 colors
    - Pre-generated smart stacks
    - Extended color support
    """

    def __init__(self, color_mode: ColorMode):
        self.color_mode = color_mode

    def load_lut(self, lut_path: str) -> Tuple[np.ndarray, np.ndarray, KDTree]:
        """Load 8-color LUT with pre-generated stacks."""
        try:
            lut_grid = np.load(lut_path)
            measured_colors = lut_grid.reshape(-1, 3)
            total_colors = measured_colors.shape[0]
        except Exception as e:
            raise ValueError(f"❌ LUT file corrupted: {e}")

        print(f"[EightColorStrategy] Loading 8-Color LUT ({total_colors} points)...")

        # Load pre-generated 8-color stacks
        smart_stacks = np.load("assets/smart_8color_stacks.npy").tolist()

        # Reverse stacking order for Face-Down printing
        smart_stacks = [tuple(reversed(s)) for s in smart_stacks]
        print(
            "[EightColorStrategy] Stacks reversed for Face-Down printing compatibility."
        )

        if len(smart_stacks) != total_colors:
            print(
                f"⚠️ Warning: Stacks count ({len(smart_stacks)}) != LUT count ({total_colors})"
            )
            min_len = min(len(smart_stacks), total_colors)
            smart_stacks = smart_stacks[:min_len]
            measured_colors = measured_colors[:min_len]

        lut_rgb = measured_colors
        ref_stacks = np.array(smart_stacks)
        kdtree = KDTree(lut_rgb)

        print(f"✅ LUT loaded: {len(lut_rgb)} colors (8-Color mode)")

        return lut_rgb, ref_stacks, kdtree

    def get_mode_name(self) -> str:
        return "8-Color Max"
