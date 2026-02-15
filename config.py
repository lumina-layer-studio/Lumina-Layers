"""Lumina Studio configuration: paths, printer/smart config, and legacy i18n data."""

import os
from enum import Enum

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


class PrinterConfig:
    """Physical printer parameters (layer height, nozzle, backing)."""

    LAYER_HEIGHT: float = 0.08
    NOZZLE_WIDTH: float = 0.42
    COLOR_LAYERS: int = 5
    BACKING_MM: float = 1.6
    SHRINK_OFFSET: float = 0.02


class SmartConfig:
    """Configuration for the Smart 1296 (36x36) System."""

    GRID_DIM: int = 36
    TOTAL_BLOCKS: int = 1296

    DEFAULT_BLOCK_SIZE: float = 5.0  # mm (Face Down mode)
    DEFAULT_GAP: float = 0.8  # mm

    FILAMENTS = {
        0: {"name": "White", "hex": "#FFFFFF", "rgb": [255, 255, 255], "td": 5.0},
        1: {"name": "Cyan", "hex": "#0086D6", "rgb": [0, 134, 214], "td": 3.5},
        2: {"name": "Magenta", "hex": "#EC008C", "rgb": [236, 0, 140], "td": 3.0},
        3: {"name": "Green", "hex": "#00AE42", "rgb": [0, 174, 66], "td": 2.0},
        4: {"name": "Yellow", "hex": "#F4EE2A", "rgb": [244, 238, 42], "td": 6.0},
        5: {"name": "Black", "hex": "#000000", "rgb": [0, 0, 0], "td": 0.6},
    }


class ModelingMode(str, Enum):
    """建模模式枚举"""

    HIGH_FIDELITY = "high-fidelity"  # 高保真模式
    PIXEL = "pixel"  # 像素模式
    VECTOR = "vector"

    def get_display_name(self) -> str:
        """获取模式的显示名称"""
        display_names = {
            ModelingMode.HIGH_FIDELITY: "High-Fidelity",
            ModelingMode.PIXEL: "Pixel Art",
            ModelingMode.VECTOR: "Vector",
        }
        return display_names.get(self, self.value)


class StructureMode(str, Enum):
    """结构模式枚举"""

    DOUBLE_SIDED = "double-sided"
    SINGLE_SIDED = "single-sided"

    def get_display_name(self) -> str:
        display_names = {
            StructureMode.DOUBLE_SIDED: "Double-sided",
            StructureMode.SINGLE_SIDED: "Single-sided",
        }
        return display_names.get(self, self.value)


class ColorMode(str, Enum):
    """色彩模式枚举"""

    BW = "BW"
    CMYW = "CMYW"
    RYBW = "RYBW"
    SIX_COLOR = "6-Color"
    EIGHT_COLOR_MAX = "8-Color Max"

    def get_display_name(self) -> str:
        display_names = {
            ColorMode.BW: "BW",
            ColorMode.CMYW: "CMYW",
            ColorMode.RYBW: "RYBW",
            ColorMode.SIX_COLOR: "6-Color",
            ColorMode.EIGHT_COLOR_MAX: "8-Color Max",
        }
        return display_names.get(self, self.value)


class MatchStrategy(str, Enum):
    """LUT 匹配策略枚举

    仅在 High-Fidelity 模式下有效,控制颜色匹配算法选择。
    """

    RGB_EUCLIDEAN = "rgb_euclidean"  # RGB 欧几里得距离匹配
    DELTAE2000 = "deltae2000"  # CIEDE2000 感知距离匹配

    def get_display_name(self) -> str:
        """获取策略的显示名称"""
        display_names = {
            MatchStrategy.RGB_EUCLIDEAN: "RGB Euclidean",
            MatchStrategy.DELTAE2000: "CIEDE2000",
        }
        return display_names.get(self, self.value)


class ColorSystem:
    """Color model definitions for BW, CMYW, RYBW, 6-Color and 8-Color systems."""

    BW = {
        "name": "BW",
        "slots": ["White", "Black"],
        "preview": {
            0: [255, 255, 255, 255],
            1: [0, 0, 0, 255],
        },
        "map": {"White": 0, "Black": 1},
        "corner_labels": ["白色 (左上)", "黑色 (右上)", "黑色 (右下)", "黑色 (左下)"],
        "corner_labels_en": ["White (TL)", "Black (TR)", "Black (BR)", "Black (BL)"],
    }

    CMYW = {
        "name": "CMYW",
        "slots": ["White", "Cyan", "Magenta", "Yellow"],
        "preview": {
            0: [255, 255, 255, 255],
            1: [0, 134, 214, 255],
            2: [236, 0, 140, 255],
            3: [244, 238, 42, 255],
        },
        "map": {"White": 0, "Cyan": 1, "Magenta": 2, "Yellow": 3},
        "corner_labels": ["白色 (左上)", "青色 (右上)", "品红 (右下)", "黄色 (左下)"],
        "corner_labels_en": ["White (TL)", "Cyan (TR)", "Magenta (BR)", "Yellow (BL)"],
    }

    RYBW = {
        "name": "RYBW",
        "slots": ["White", "Red", "Yellow", "Blue"],
        "preview": {
            0: [255, 255, 255, 255],
            1: [220, 20, 60, 255],
            2: [255, 230, 0, 255],
            3: [0, 100, 240, 255],
        },
        "map": {"White": 0, "Red": 1, "Yellow": 2, "Blue": 3},
        "corner_labels": ["白色 (左上)", "红色 (右上)", "蓝色 (右下)", "黄色 (左下)"],
        "corner_labels_en": ["White (TL)", "Red (TR)", "Blue (BR)", "Yellow (BL)"],
    }

    SIX_COLOR = {
        "name": "6-Color",
        "base": 6,
        "layer_count": 5,
        "slots": ["White", "Cyan", "Magenta", "Green", "Yellow", "Black"],
        "preview": {
            0: [255, 255, 255, 255],  # White
            1: [0, 134, 214, 255],  # Cyan
            2: [236, 0, 140, 255],  # Magenta
            3: [0, 174, 66, 255],  # Green
            4: [244, 238, 42, 255],  # Yellow
            5: [20, 20, 20, 255],  # Black
        },
        "map": {
            "White": 0,
            "Cyan": 1,
            "Magenta": 2,
            "Green": 3,
            "Yellow": 4,
            "Black": 5,
        },
        "corner_labels": ["白色 (左上)", "青色 (右上)", "品红 (右下)", "黄色 (左下)"],
        "corner_labels_en": ["White (TL)", "Cyan (TR)", "Magenta (BR)", "Yellow (BL)"],
    }

    EIGHT_COLOR = {
        "name": "8-Color Max",
        "slots": [
            "Slot 1 (White)",
            "Slot 2 (Cyan)",
            "Slot 3 (Magenta)",
            "Slot 4 (Yellow)",
            "Slot 5 (Black)",
            "Slot 6 (Red)",
            "Slot 7 (Deep Blue)",
            "Slot 8 (Green)",
        ],
        "preview": {
            0: [255, 255, 255, 255],
            1: [0, 134, 214, 255],
            2: [236, 0, 140, 255],
            3: [244, 238, 42, 255],
            4: [20, 20, 20, 255],
            5: [193, 46, 31, 255],
            6: [10, 41, 137, 255],
            7: [0, 174, 66, 255],
        },
        "map": {
            "White": 0,
            "Cyan": 1,
            "Magenta": 2,
            "Yellow": 3,
            "Black": 4,
            "Red": 5,
            "Deep Blue": 6,
            "Green": 7,
        },
        "corner_labels": ["TL", "TR", "BR", "BL"],
    }

    @staticmethod
    def get(mode: "ColorMode"):
        if mode == ColorMode.EIGHT_COLOR_MAX:
            return ColorSystem.EIGHT_COLOR
        if mode == ColorMode.SIX_COLOR:
            return ColorSystem.SIX_COLOR
        if mode == ColorMode.BW:
            return ColorSystem.BW
        return ColorSystem.CMYW if mode == ColorMode.CMYW else ColorSystem.RYBW


# ========== Global Constants ==========

# Extractor constants
PHYSICAL_GRID_SIZE = 34
DATA_GRID_SIZE = 32
DST_SIZE = 1000
CELL_SIZE = DST_SIZE / PHYSICAL_GRID_SIZE
LUT_FILE_PATH = os.path.join(OUTPUT_DIR, "lumina_lut.npy")

# Converter constants
PREVIEW_SCALE = 2
PREVIEW_MARGIN = 30


# ========== Vector Engine Configuration ==========


class VectorConfig:
    """Configuration for native vector engine."""

    # Curve approximation precision
    DEFAULT_SAMPLING_MM: float = 0.05  # High quality (default)
    MIN_SAMPLING_MM: float = 0.01  # Ultra-high quality
    MAX_SAMPLING_MM: float = 0.20  # Low quality (faster)

    # Performance limits
    MAX_POLYGONS: int = 10000  # Prevent memory issues
    MAX_VERTICES_PER_POLY: int = 5000  # Prevent degenerate geometry

    # Boolean operation tolerance
    BUFFER_TOLERANCE: float = 0.0  # Shapely buffer precision

    # Coordinate system
    FLIP_Y_AXIS: bool = False  # SVG Y-down → 3D Y-up (disabled by default)

    # Parallel processing
    ENABLE_PARALLEL: bool = False  # Parallel layer processing (experimental)
    MAX_WORKERS: int = 5  # Thread pool size
