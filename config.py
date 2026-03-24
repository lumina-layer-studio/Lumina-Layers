"""Lumina Studio configuration: paths, printer/smart config, and legacy i18n data."""

import os
import sys
import platform
from enum import Enum

# Handle PyInstaller bundled resources
if getattr(sys, 'frozen', False):
    # Running as compiled executable - use current working directory
    _BASE_DIR = os.getcwd()
else:
    # Running as script
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR = os.path.join(_BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_asset_path(relative_path: str) -> str:
    """Resolve asset file path for both script and PyInstaller frozen modes.
    解析资源文件路径，兼容脚本运行和 PyInstaller 打包模式。

    Args:
        relative_path (str): Relative path under assets/, e.g. 'smart_8color_stacks.npy'.
                             (assets/ 下的相对路径)

    Returns:
        str: Absolute path to the asset file. (资源文件的绝对路径)

    Raises:
        FileNotFoundError: If the asset file cannot be found. (找不到资源文件时抛出)
    """
    candidates = []
    asset_rel = os.path.join("assets", relative_path)

    if getattr(sys, 'frozen', False):
        # PyInstaller bundled: check _MEIPASS first, then CWD
        candidates.append(os.path.join(sys._MEIPASS, asset_rel))
        candidates.append(os.path.join(os.getcwd(), asset_rel))
    else:
        # Script mode: check project root, then parent dir
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), asset_rel))
        candidates.append(os.path.join(os.getcwd(), asset_rel))
        candidates.append(os.path.join("..", asset_rel))

    for path in candidates:
        if os.path.exists(path):
            return path

    raise FileNotFoundError(
        f"Asset not found: {relative_path}\n"
        f"Searched: {candidates}"
    )


class PrinterConfig:
    """Physical printer parameters (layer height, nozzle, backing)."""
    LAYER_HEIGHT: float = 0.08
    NOZZLE_WIDTH: float = 0.42
    COLOR_LAYERS: int = 5
    BACKING_MM: float = 1.6
    SHRINK_OFFSET: float = 0.02


class WorkerPoolConfig:
    """Worker pool configuration with env var overrides.
    工作进程池配置，支持环境变量覆盖。

    Attributes:
        MAX_WORKERS (int): Max number of worker processes. (最大工作进程数)
        TASK_TIMEOUT (float): Task timeout in seconds. (任务超时秒数)
    """
    MAX_WORKERS: int = min(os.cpu_count() or 2, 4)
    TASK_TIMEOUT: float = 0  # No timeout

    @classmethod
    def from_env(cls) -> "WorkerPoolConfig":
        """Create config with environment variable overrides.
        创建配置，支持环境变量覆盖。

        Reads:
            LUMINA_MAX_WORKERS: Override MAX_WORKERS. (覆盖最大工作进程数)
            LUMINA_TASK_TIMEOUT: Override TASK_TIMEOUT. (覆盖任务超时秒数)

        Returns:
            WorkerPoolConfig: Config instance with env overrides applied.
                              (应用环境变量覆盖后的配置实例)
        """
        cfg = cls()
        if v := os.environ.get("LUMINA_MAX_WORKERS"):
            cfg.MAX_WORKERS = int(v)
        if v := os.environ.get("LUMINA_TASK_TIMEOUT"):
            cfg.TASK_TIMEOUT = float(v)
        return cfg


class SmartConfig:
    """Configuration for the Smart 1296 (36x36) System."""
    GRID_DIM: int = 36
    TOTAL_BLOCKS: int = 1296
    
    DEFAULT_BLOCK_SIZE: float = 5.0  # mm (Face Down mode)
    DEFAULT_GAP: float = 0.8  # mm

    FILAMENTS = {
        0: {"name": "White",   "hex": "#FFFFFF", "rgb": [255, 255, 255], "td": 5.0},
        1: {"name": "Cyan",    "hex": "#0086D6", "rgb": [0, 134, 214],   "td": 3.5},
        2: {"name": "Magenta", "hex": "#EC008C", "rgb": [236, 0, 140],   "td": 3.0},
        3: {"name": "Green",   "hex": "#00AE42", "rgb": [0, 174, 66],    "td": 2.0},
        4: {"name": "Yellow",  "hex": "#F4EE2A", "rgb": [244, 238, 42],  "td": 6.0},
        5: {"name": "Black",   "hex": "#000000", "rgb": [0, 0, 0],       "td": 0.6},
    }


class SmartConfigRYBW:
    """Configuration for the Smart 1296 RYBW (36x36) System.
    RYBW 6 色系统配置：White, Red, Yellow, Blue, Green, Black。
    """
    GRID_DIM: int = 36
    TOTAL_BLOCKS: int = 1296

    DEFAULT_BLOCK_SIZE: float = 5.0  # mm (Face Down mode)
    DEFAULT_GAP: float = 0.8  # mm

    FILAMENTS = {
        0: {"name": "White",  "hex": "#FFFFFF", "rgb": [255, 255, 255], "td": 5.0},
        1: {"name": "Red",    "hex": "#DC143C", "rgb": [220, 20, 60],   "td": 3.0},
        2: {"name": "Yellow", "hex": "#FFE600", "rgb": [255, 230, 0],   "td": 6.0},
        3: {"name": "Blue",   "hex": "#0064F0", "rgb": [0, 100, 240],   "td": 3.5},
        4: {"name": "Green",  "hex": "#00AE42", "rgb": [0, 174, 66],    "td": 2.0},
        5: {"name": "Black",  "hex": "#000000", "rgb": [0, 0, 0],       "td": 0.6},
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
            ModelingMode.VECTOR: "Vector"
        }
        return display_names.get(self, self.value)


class ColorSystem:
    """Color model definitions for CMYW, RYBW, and 6-Color systems."""

    CMYW = {
        'name': 'CMYW',
        'slots': ["White", "Cyan", "Magenta", "Yellow"],
        'preview': {
            0: [255, 255, 255, 255],
            1: [0, 134, 214, 255],
            2: [236, 0, 140, 255],
            3: [244, 238, 42, 255]
        },
        'map': {"White": 0, "Cyan": 1, "Magenta": 2, "Yellow": 3},
        'corner_labels': ["白色 (左上)", "青色 (右上)", "品红 (右下)", "黄色 (左下)"],
        'corner_labels_en': ["White (TL)", "Cyan (TR)", "Magenta (BR)", "Yellow (BL)"]
    }

    RYBW = {
        'name': 'RYBW',
        'slots': ["White", "Red", "Yellow", "Blue"],
        'preview': {
            0: [255, 255, 255, 255],
            1: [220, 20, 60, 255],
            2: [255, 230, 0, 255],
            3: [0, 100, 240, 255]
        },
        'map': {"White": 0, "Red": 1, "Yellow": 2, "Blue": 3},
        'corner_labels': ["左上", "右上", "右下", "左下"],
        'corner_labels_en': ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"]
    }

    SIX_COLOR = {
        'name': '6-Color',
        'base': 6,
        'layer_count': 5,
        'slots': ["White", "Cyan", "Magenta", "Green", "Yellow", "Black"],
        'preview': {
            0: [255, 255, 255, 255],  # White
            1: [0, 134, 214, 255],    # Cyan
            2: [236, 0, 140, 255],    # Magenta
            3: [0, 174, 66, 255],     # Green
            4: [244, 238, 42, 255],   # Yellow
            5: [0, 0, 0, 255]         # Black (纯黑 #000000)
        },
        'map': {"White": 0, "Cyan": 1, "Magenta": 2, "Green": 3, "Yellow": 4, "Black": 5},
        'corner_labels': ["白色 (左上)", "青色 (右上)", "品红 (右下)", "黄色 (左下)"],
        'corner_labels_en': ["White (TL)", "Cyan (TR)", "Magenta (BR)", "Yellow (BL)"]
    }

    SIX_COLOR_RYBW = {
        'name': '6-Color (RYBW)',
        'base': 6,
        'layer_count': 5,
        'slots': ["White", "Red", "Yellow", "Blue", "Green", "Black"],
        'preview': {
            0: [255, 255, 255, 255],  # White
            1: [220, 20, 60, 255],    # Red
            2: [255, 230, 0, 255],    # Yellow
            3: [0, 100, 240, 255],    # Blue
            4: [0, 174, 66, 255],     # Green
            5: [0, 0, 0, 255]         # Black
        },
        'map': {"White": 0, "Red": 1, "Yellow": 2, "Blue": 3, "Green": 4, "Black": 5},
        'corner_labels': ["白色 (左上)", "红色 (右上)", "蓝色 (右下)", "黄色 (左下)"],
        'corner_labels_en': ["White (TL)", "Red (TR)", "Blue (BR)", "Yellow (BL)"]
    }

    EIGHT_COLOR = {
        'name': '8-Color Max',
        'slots': ['Slot 1 (White)', 'Slot 2 (Cyan)', 'Slot 3 (Magenta)', 'Slot 4 (Yellow)', 'Slot 5 (Black)', 'Slot 6 (Red)', 'Slot 7 (Deep Blue)', 'Slot 8 (Green)'],
        'preview': {
            0: [255, 255, 255, 255], 1: [0, 134, 214, 255], 2: [236, 0, 140, 255], 3: [244, 238, 42, 255],
            4: [0, 0, 0, 255], 5: [193, 46, 31, 255], 6: [10, 41, 137, 255], 7: [0, 174, 66, 255]
        },
        'map': {'White': 0, 'Cyan': 1, 'Magenta': 2, 'Yellow': 3, 'Black': 4, 'Red': 5, 'Deep Blue': 6, 'Green': 7},
        'corner_labels': ['TL', 'TR', 'BR', 'BL']
    }

    BW = {
        'name': 'BW',
        'base': 2,
        'layer_count': 5,
        'slots': ["White", "Black"],
        'preview': {
            0: [255, 255, 255, 255],  # White
            1: [0, 0, 0, 255]         # Black (纯黑 #000000)
        },
        'map': {"White": 0, "Black": 1},
        'corner_labels': ["白色 (左上)", "黑色 (右上)", "黑色 (右下)", "黑色 (左下)"],
        'corner_labels_en': ["White (TL)", "Black (TR)", "Black (BR)", "Black (BL)"]
    }

    FIVE_COLOR_EXTENDED = {
        'name': '5-Color Extended',
        'base': 5,
        'layer_count': 6,
        'slots': ["White", "Red", "Yellow", "Blue", "Black"],
        'preview': {
            0: [255, 255, 255, 255],  # White
            1: [220, 20, 60, 255],    # Red
            2: [255, 230, 0, 255],    # Yellow
            3: [0, 100, 240, 255],    # Blue
            4: [20, 20, 20, 255]      # Black
        },
        'map': {"White": 0, "Red": 1, "Yellow": 2, "Blue": 3, "Black": 4},
        'corner_labels': ["白色 (左上)", "红色 (右上)", "蓝色 (右下)", "黄色 (左下)", "黑色 (外层)"],
        'corner_labels_en': ["White (TL)", "Red (TR)", "Blue (BR)", "Yellow (BL)", "Black (Outer)"]
    }

    @staticmethod
    def get(mode: str):
        """
        Get color system configuration (Unified 4-Color Backend)
        
        Args:
            mode: Color mode string (4-Color/6-Color/8-Color/BW)
        
        Returns:
            Color system configuration dict
        
        Note:
            4-Color mode defaults to RYBW palette.
            CMYW and RYBW share the same processing pipeline.
        """
        if mode is None:
            return ColorSystem.RYBW  # Default fallback
        
        # 4-Color CMYW variant
        if mode in ("4-Color (CMYW)", "CMYW"):
            return ColorSystem.CMYW
        
        # 4-Color RYBW variant (also handles legacy "4-Color" string)
        if mode in ("4-Color (RYBW)", "4-Color", "RYBW") or "4-Color" in mode:
            return ColorSystem.RYBW
        
        # Check specific patterns
        if "8-Color" in mode:
            return ColorSystem.EIGHT_COLOR
        if mode in ("6-Color (RYBWGK 1296)",):
            return ColorSystem.SIX_COLOR_RYBW
        if "6-Color" in mode:
            return ColorSystem.SIX_COLOR
        
        # Merged LUT: use 8-Color config (superset of all material IDs 0-7)
        if mode == "Merged":
            return ColorSystem.EIGHT_COLOR
        
        # Legacy support for old mode strings
        if "RYBW" in mode:
            return ColorSystem.RYBW
        if "CMYW" in mode:
            return ColorSystem.CMYW
        
        # Check BW last to avoid matching RYBW
        if mode == "BW" or mode == "BW (Black & White)":
            return ColorSystem.BW
        
        # 5-Color Extended mode
        if "5-Color Extended" in mode or "5-Color (Extended)" in mode:
            return ColorSystem.FIVE_COLOR_EXTENDED
        
        return ColorSystem.RYBW  # Default fallback

# ========== Global Constants ==========

# Extractor constants
PHYSICAL_GRID_SIZE = 34
DATA_GRID_SIZE = 32
DST_SIZE = 1000
CELL_SIZE = DST_SIZE / PHYSICAL_GRID_SIZE
LUT_FILE_PATH = os.path.join(OUTPUT_DIR, "lumina_lut.json")

# Converter constants
PREVIEW_SCALE = 2
PREVIEW_MARGIN = 30


class BedManager:
    """Print bed size manager for preview rendering.
    
    Provides standard bed sizes and dynamic canvas scaling
    so that models on a 400mm bed are visually comparable to
    those on a 180mm bed.
    """

    # (label, width_mm, height_mm)
    BEDS = [
        ("180×180 mm", 180, 180),
        ("220×220 mm", 220, 220),
        ("256×256 mm", 256, 256),
        ("300×300 mm", 300, 300),
        ("400×400 mm", 400, 400),
    ]

    DEFAULT_BED = "256×256 mm"

    # Target canvas pixels (long edge) – keeps UI responsive
    _TARGET_CANVAS_PX = 1200

    @classmethod
    def get_choices(cls):
        """Return list of (label, label) tuples for Gradio Radio/Dropdown."""
        return [(b[0], b[0]) for b in cls.BEDS]

    @classmethod
    def get_bed_size(cls, label: str):
        """Return (width_mm, height_mm) for a given label or printer display name.
        根据标签或打印机显示名称返回热床尺寸。
        
        Args:
            label (str): Bed size label or printer display name. (热床尺寸标签或打印机显示名称)
        
        Returns:
            tuple[int, int]: (width_mm, height_mm). (宽度和高度，毫米)
        """
        # Try standard bed sizes first
        for name, w, h in cls.BEDS:
            if name == label:
                return (w, h)
        
        # Try printer profiles by display name
        for profile in PRINTER_PROFILES.values():
            if profile.display_name == label:
                return (profile.bed_width, profile.bed_depth)
        
        return (256, 256)  # fallback

    @classmethod
    def get_all_bed_options(cls):
        """Return all bed size options including printer models and custom sizes.
        返回所有热床尺寸选项，包括打印机型号和自定义尺寸。
        
        Returns:
            list[tuple]: List of (label, width_mm, height_mm, printer_id).
                         printer_id is None for custom sizes. 
                         (标签、宽度、高度、打印机ID的元组列表，自定义尺寸的 printer_id 为 None)
        """
        options = []
        
        # Add printer models first
        for profile in PRINTER_PROFILES.values():
            options.append((
                profile.display_name,
                profile.bed_width,
                profile.bed_depth,
                profile.id
            ))
        
        # Add custom sizes
        for label, w, h in cls.BEDS:
            options.append((label, w, h, None))
        
        return options

    @classmethod
    def compute_scale(cls, bed_w_mm, bed_h_mm):
        """Pixels-per-mm so the bed fits in _TARGET_CANVAS_PX."""
        long_edge = max(bed_w_mm, bed_h_mm)
        return cls._TARGET_CANVAS_PX / long_edge


# ========== Vector Engine Configuration ==========

class VectorConfig:
    """Configuration for native vector engine."""
    
    # Curve approximation precision
    DEFAULT_SAMPLING_MM: float = 0.05  # High quality (default)
    MIN_SAMPLING_MM: float = 0.01      # Ultra-high quality
    MAX_SAMPLING_MM: float = 0.20      # Low quality (faster)
    
    # Performance limits
    MAX_POLYGONS: int = 10000          # Prevent memory issues
    MAX_VERTICES_PER_POLY: int = 5000  # Prevent degenerate geometry
    
    # Boolean operation tolerance
    BUFFER_TOLERANCE: float = 0.0      # Shapely buffer precision
    
    # Coordinate system
    FLIP_Y_AXIS: bool = False          # SVG Y-down → 3D Y-up (disabled by default)
    
    # Parallel processing
    ENABLE_PARALLEL: bool = False      # Parallel layer processing (experimental)
    MAX_WORKERS: int = 5               # Thread pool size


# ========== Runtime Platform Policy ==========

def _env_flag(name: str) -> bool:
    """Return True for common truthy env var values."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def is_wsl_runtime() -> bool:
    """Detect whether current runtime is WSL."""
    if "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ:
        return True
    try:
        return "microsoft" in platform.release().lower()
    except Exception:
        return False


def get_tray_runtime_policy():
    """Return (enabled, reason) for system tray initialization."""
    if _env_flag("DISABLE_TRAY"):
        return False, "Disabled by DISABLE_TRAY environment variable"

    if is_wsl_runtime():
        return False, "Disabled on WSL environment"

    # Linux desktop tray support is inconsistent across distros/DEs.
    # Keep it opt-in to avoid startup noise.
    if sys.platform.startswith("linux"):
        if _env_flag("ENABLE_TRAY"):
            return True, "Enabled on Linux via ENABLE_TRAY=1"
        return False, "Disabled on Linux by default (set ENABLE_TRAY=1 to force)"

    if os.name == "nt" or sys.platform == "darwin":
        return True, "Enabled on desktop platform"

    return False, f"Disabled on unsupported platform: {sys.platform}"


# ========== Printer Profile Registry ==========

from dataclasses import dataclass, field
from typing import Optional

LEGACY_SLICER_ID_ALIASES: dict[str, str] = {
    "bambu": "BambuStudio",
    "bambu_studio": "BambuStudio",
    "bambu studio": "BambuStudio",
    "bambustudio": "BambuStudio",
    "orca": "OrcaSlicer",
    "orca_slicer": "OrcaSlicer",
    "orcaslicer": "OrcaSlicer",
    "snapmaker": "SnapmakerOrca",
    "snapmaker_orca": "SnapmakerOrca",
    "snapmaker orca": "SnapmakerOrca",
    "snapmakerorca": "SnapmakerOrca",
    "elegoo": "ElegooSlicer",
    "elegoo_slicer": "ElegooSlicer",
    "elegoo slicer": "ElegooSlicer",
    "elegooslicer": "ElegooSlicer",
}


def normalize_slicer_software_id(slicer: str) -> str:
    """Normalize legacy slicer IDs to canonical settings IDs.
    将旧版切片器 ID 规范化为当前设置使用的标准 ID。

    Args:
        slicer (str): Raw slicer identifier or display-like value. (原始切片器标识)

    Returns:
        str: Canonical slicer ID when known, otherwise the trimmed input. (标准切片器 ID)
    """
    trimmed = slicer.strip()
    if not trimmed:
        return DEFAULT_SLICER_ID
    return LEGACY_SLICER_ID_ALIASES.get(trimmed.lower(), trimmed)


def normalize_printer_profile_id(printer_id: str) -> str:
    """Normalize legacy printer IDs to canonical registry IDs.
    将旧版打印机 ID 规范化为当前注册表使用的标准 ID。

    Args:
        printer_id (str): Raw printer identifier. (原始打印机标识)

    Returns:
        str: Canonical printer ID when known, otherwise normalized text. (标准打印机 ID)
    """
    trimmed = printer_id.strip()
    if not trimmed:
        return DEFAULT_PRINTER_ID
    return trimmed.lower().replace("_", "-")


@dataclass
class PrinterProfile:
    """Printer hardware profile for 3MF export template selection.
    打印机硬件配置，用于 3MF 导出模板选择。

    Attributes:
        id (str): Unique printer identifier, e.g. "bambu-h2d". (唯一打印机标识)
        display_name (str): Human-readable name, e.g. "Bambu Lab H2D". (显示名称)
        brand (str): Manufacturer brand, e.g. "Bambu Lab". (品牌)
        bed_width (int): Print bed width in mm. (打印床宽度，毫米)
        bed_depth (int): Print bed depth in mm. (打印床深度，毫米)
        bed_height (int): Max print height in mm. (最大打印高度，毫米)
        nozzle_count (int): Number of nozzles, 1=single, 2=dual. (喷头数量)
        is_dual_head (bool): Whether the printer has dual print heads. (是否双头)
        template_file (str): Default (BambuStudio) config template filename. (默认模板文件名)
        slicer_templates (dict[str, str]): Slicer-specific template filenames. (切片器专属模板)
        thumbnail (str): Thumbnail image filename, reserved for future use. (缩略图文件名，预留)
    """
    id: str
    display_name: str
    brand: str
    bed_width: int
    bed_depth: int
    bed_height: int
    nozzle_count: int
    is_dual_head: bool
    template_file: str
    slicer_templates: dict = field(default_factory=dict)
    thumbnail: str = ""

    def get_template_file(self, slicer: str = "BambuStudio") -> str:
        """Return template filename for the given slicer.
        返回指定切片器的模板文件名。

        Args:
            slicer (str): Slicer identifier, e.g. "BambuStudio" or "OrcaSlicer". (切片器标识)

        Returns:
            str: Template filename. Falls back to default template_file. (模板文件名，回退到默认)
        """
        normalized_slicer = normalize_slicer_software_id(slicer)
        return self.slicer_templates.get(normalized_slicer, self.template_file)


# Supported slicer software list
SUPPORTED_SLICERS: list[dict[str, str]] = [
    {"id": "BambuStudio", "display_name": "BambuStudio"},
    {"id": "OrcaSlicer", "display_name": "OrcaSlicer"},
    {"id": "SnapmakerOrca", "display_name": "Snapmaker Orca"},
    {"id": "ElegooSlicer", "display_name": "ElegooSlicer"},
]

DEFAULT_SLICER_ID: str = "BambuStudio"


PRINTER_PROFILES: dict[str, PrinterProfile] = {
    "bambu-a1-mini": PrinterProfile(
        id="bambu-a1-mini", display_name="Bambu Lab A1 mini", brand="Bambu Lab",
        bed_width=180, bed_depth=180, bed_height=180,
        nozzle_count=1, is_dual_head=False,
        template_file="bambu_a1_mini.json",
        slicer_templates={"OrcaSlicer": "orca_a1_mini.json"},
    ),
    "bambu-a1": PrinterProfile(
        id="bambu-a1", display_name="Bambu Lab A1", brand="Bambu Lab",
        bed_width=256, bed_depth=256, bed_height=256,
        nozzle_count=1, is_dual_head=False,
        template_file="bambu_a1.json",
        slicer_templates={"OrcaSlicer": "orca_a1.json"},
    ),
    "bambu-p1p": PrinterProfile(
        id="bambu-p1p", display_name="Bambu Lab P1P", brand="Bambu Lab",
        bed_width=256, bed_depth=256, bed_height=256,
        nozzle_count=1, is_dual_head=False,
        template_file="bambu_p1p.json",
        slicer_templates={"OrcaSlicer": "orca_p1p.json"},
    ),
    "bambu-p1s": PrinterProfile(
        id="bambu-p1s", display_name="Bambu Lab P1S", brand="Bambu Lab",
        bed_width=256, bed_depth=256, bed_height=250,
        nozzle_count=1, is_dual_head=False,
        template_file="bambu_p1s.json",
        slicer_templates={"OrcaSlicer": "orca_p1s.json"},
    ),
    "bambu-x1c": PrinterProfile(
        id="bambu-x1c", display_name="Bambu Lab X1 Carbon", brand="Bambu Lab",
        bed_width=256, bed_depth=256, bed_height=256,
        nozzle_count=1, is_dual_head=False,
        template_file="bambu_x1c.json",
        slicer_templates={"OrcaSlicer": "orca_x1c.json"},
    ),
    "bambu-x1e": PrinterProfile(
        id="bambu-x1e", display_name="Bambu Lab X1E", brand="Bambu Lab",
        bed_width=256, bed_depth=256, bed_height=256,
        nozzle_count=1, is_dual_head=False,
        template_file="bambu_x1e.json",
        slicer_templates={"OrcaSlicer": "orca_x1e.json"},
    ),
    "bambu-h2d": PrinterProfile(
        id="bambu-h2d", display_name="Bambu Lab H2D", brand="Bambu Lab",
        bed_width=350, bed_depth=320, bed_height=325,
        nozzle_count=2, is_dual_head=True,
        template_file="bambu_h2d.json",
        slicer_templates={"OrcaSlicer": "orca_h2d.json"},
    ),
    "bambu-h2d-pro": PrinterProfile(
        id="bambu-h2d-pro", display_name="Bambu Lab H2D Pro", brand="Bambu Lab",
        bed_width=350, bed_depth=320, bed_height=325,
        nozzle_count=2, is_dual_head=True,
        template_file="bambu_h2d_pro.json",
        slicer_templates={"OrcaSlicer": "orca_h2d_pro.json"},
    ),
    "bambu-h2s": PrinterProfile(
        id="bambu-h2s", display_name="Bambu Lab H2S", brand="Bambu Lab",
        bed_width=350, bed_depth=320, bed_height=325,
        nozzle_count=2, is_dual_head=True,
        template_file="bambu_h2s.json",
        slicer_templates={"OrcaSlicer": "orca_h2s.json"},
    ),
    "bambu-p2s": PrinterProfile(
        id="bambu-p2s", display_name="Bambu Lab P2S", brand="Bambu Lab",
        bed_width=256, bed_depth=256, bed_height=250,
        nozzle_count=1, is_dual_head=False,
        template_file="bambu_p2s.json",
        slicer_templates={"OrcaSlicer": "orca_p2s.json"},
    ),
    "bambu-h2c": PrinterProfile(
        id="bambu-h2c", display_name="Bambu Lab H2C", brand="Bambu Lab",
        bed_width=350, bed_depth=320, bed_height=325,
        nozzle_count=2, is_dual_head=True,
        template_file="bambu_h2c.json",
        slicer_templates={"OrcaSlicer": "orca_h2c.json"},
    ),
    "snapmaker-u1": PrinterProfile(
        id="snapmaker-u1", display_name="Snapmaker U1", brand="Snapmaker",
        bed_width=270, bed_depth=270, bed_height=270,
        nozzle_count=4, is_dual_head=False,
        template_file="snapmaker_u1.json",
        slicer_templates={"SnapmakerOrca": "snapmaker_u1.json"},
    ),
    "elegoo-cc2": PrinterProfile(
        id="elegoo-cc2", display_name="Elegoo Centauri Carbon 2", brand="Elegoo",
        bed_width=256, bed_depth=256, bed_height=256,
        nozzle_count=1, is_dual_head=False,
        template_file="elegoo_cc2.json",
        slicer_templates={"ElegooSlicer": "elegoo_cc2.json"},
    ),
}

DEFAULT_PRINTER_ID: str = "bambu-h2d"


def get_printer_profile(printer_id: str) -> PrinterProfile:
    """Get printer profile by ID, falling back to default (H2D) for unknown IDs.
    根据 ID 获取打印机配置，未知 ID 回退到默认机型 H2D。

    Args:
        printer_id (str): Printer identifier, e.g. "bambu-h2d". (打印机标识)

    Returns:
        PrinterProfile: Matching profile or default H2D profile. (匹配的配置或默认 H2D 配置)
    """
    normalized_printer_id = normalize_printer_profile_id(printer_id)
    return PRINTER_PROFILES.get(
        normalized_printer_id,
        PRINTER_PROFILES[DEFAULT_PRINTER_ID],
    )


def list_printer_profiles() -> list[PrinterProfile]:
    """Return all supported printer profiles as a list.
    返回所有支持的打印机配置列表。

    Returns:
        list[PrinterProfile]: All registered printer profiles. (所有已注册的打印机配置)
    """
    return list(PRINTER_PROFILES.values())


# ========== LUT Palette & Metadata ==========


@dataclass
class PaletteEntry:
    """Palette entry: describes a single base color channel.
    调色板条目：描述一个基础色通道。

    Attributes:
        color (str): Color name, e.g. "Red", "Cyan". (颜色名称)
        material (str): Material name. (材料名称)
        hex_color (Optional[str]): Hex color value, e.g. "#FF0000". (十六进制颜色值)
        color_name (Optional[str]): Manufacturer-provided display name. (厂商提供的颜色名称)
    """
    color: str
    material: str = "PLA Basic"
    hex_color: Optional[str] = None
    color_name: Optional[str] = None


@dataclass
class LUTMetadata:
    """LUT metadata: palette + print parameters.
    LUT 元数据：调色板 + 打印参数。

    Attributes:
        palette (list[PaletteEntry]): Palette entries. (调色板条目列表)
        manufacturer (str): LUT / color DB manufacturer. (厂商名称)
        type (str): LUT / color DB type. (类型)
        color_mode (Optional[str]): Color mode identifier, e.g. "4-Color (RYBW)". (颜色模式标识)
        max_color_layers (int): Max color layers in recipe. (最大颜色层数)
        layer_height_mm (float): Layer height in mm. (层高，毫米)
        line_width_mm (float): Line width in mm. (线宽，毫米)
        base_layers (int): Number of base layers. (底板层数)
        base_channel_idx (int): Base channel index. (底板通道索引)
        layer_order (str): Print order, "Top2Bottom" or "Bottom2Top". (打印顺序)
    """
    palette: list[PaletteEntry] = field(default_factory=list)
    manufacturer: str = ""
    type: str = ""
    color_mode: Optional[str] = None
    max_color_layers: int = 5
    layer_height_mm: float = 0.08
    line_width_mm: float = 0.42
    base_layers: int = 10
    base_channel_idx: int = 0
    layer_order: str = "Top2Bottom"

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary.
        序列化为可 JSON 化的字典。palette 以颜色名为 key 的对象格式输出。

        Returns:
            dict: JSON-compatible dictionary. (可 JSON 化的字典)
        """
        palette_obj: dict = {}
        for e in self.palette:
            entry: dict = {"material": e.material}
            if e.hex_color is not None:
                entry["hex_color"] = e.hex_color
            if e.color_name is not None:
                entry["color_name"] = e.color_name
            palette_obj[e.color] = entry

        d = {
            "palette": palette_obj,
            "manufacturer": self.manufacturer,
            "type": self.type,
            "max_color_layers": self.max_color_layers,
            "layer_height_mm": self.layer_height_mm,
            "line_width_mm": self.line_width_mm,
            "base_layers": self.base_layers,
            "base_channel_idx": self.base_channel_idx,
            "layer_order": self.layer_order,
        }
        if self.color_mode is not None:
            d["color_mode"] = self.color_mode
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "LUTMetadata":
        """Deserialize from a dictionary. Missing fields use defaults.
        从字典反序列化。支持新对象格式和旧数组格式的 palette。

        Args:
            data (dict): Source dictionary. (源字典)

        Returns:
            LUTMetadata: Deserialized metadata instance. (反序列化的元数据实例)
        """
        palette_raw = data.get("palette", {})
        palette: list[PaletteEntry] = []

        if isinstance(palette_raw, dict):
            # 新格式: {"White": {"material": "PLA Basic", "hex_color": "#FFF"}, ...}
            for color_name, props in palette_raw.items():
                if isinstance(props, dict):
                    palette.append(PaletteEntry(
                        color=str(color_name),
                        material=str(props.get("material", "PLA Basic")),
                        hex_color=props.get("hex_color"),
                        color_name=props.get("color_name"),
                    ))
        elif isinstance(palette_raw, list):
            # 旧格式兼容: [{"color": "White", "material": "PLA Basic"}, ...]
            for item in palette_raw:
                if isinstance(item, dict) and "color" in item and "material" in item:
                    palette.append(PaletteEntry(
                        color=str(item["color"]),
                        material=str(item["material"]),
                        hex_color=item.get("hex_color"),
                        color_name=item.get("color_name"),
                    ))

        return cls(
            palette=palette,
            manufacturer=str(data.get("manufacturer", "") or ""),
            type=str(data.get("type", "") or ""),
            color_mode=data.get("color_mode"),
            max_color_layers=int(data.get("max_color_layers", 5)),
            layer_height_mm=float(data.get("layer_height_mm", 0.08)),
            line_width_mm=float(data.get("line_width_mm", 0.42)),
            base_layers=int(data.get("base_layers", 10)),
            base_channel_idx=int(data.get("base_channel_idx", 0)),
            layer_order=str(data.get("layer_order", "Top2Bottom")),
        )

    @staticmethod
    def validate_color_name(name: str) -> bool:
        """Validate that a color name is non-empty after stripping whitespace.
        校验颜色名称非空（strip 后不为空字符串）。

        Args:
            name (str): Color name to validate. (待校验的颜色名称)

        Returns:
            bool: True if valid, False otherwise. (合法返回 True，否则 False)
        """
        return isinstance(name, str) and len(name.strip()) > 0
