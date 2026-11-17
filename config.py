"""Lumina Studio configuration: paths, printer/smart config, and legacy i18n data."""

from __future__ import annotations

import logging
import os
import platform
import sys
from decimal import Decimal, InvalidOperation
from enum import Enum

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR = os.path.join(_BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TEMP_DIR = os.path.join(OUTPUT_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Bounded image previews used by workflows that must not return full-size
# source images to the browser.
IMAGE_PREVIEW_MAX_EDGE = 1600
IMAGE_PREVIEW_JPEG_QUALITY = 85

# ColorChecker calibration artifacts.
COLORCHECKER_PREVIEW_MAX_EDGE = IMAGE_PREVIEW_MAX_EDGE
COLORCHECKER_PREVIEW_JPEG_QUALITY = IMAGE_PREVIEW_JPEG_QUALITY
COLORCHECKER_TEMP_TTL_SECONDS = 600

MODELS_DIR = os.path.join(OUTPUT_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)


def _desktop_user_data_dir() -> str:
    """Return a platform user-data directory for mutable desktop files.
    返回桌面端可写用户数据目录。
    """
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"),
            "AppData",
            "Roaming",
        )
        return os.path.join(root, "Lumina Studio")
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"),
            "Library",
            "Application Support",
            "Lumina Studio",
        )
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    root = xdg_data_home or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(root, "lumina-studio")


def get_workshop_data_dir() -> str:
    """Return the mutable Workshop package root.
    返回创意工坊模块的可写数据目录。
    """

    override = os.environ.get("LUMINA_WORKSHOP_DATA_DIR", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(_desktop_user_data_dir(), "workshop")


def _resolve_materials_dir() -> str:
    """Resolve the writable material library root.
    解析可写耗材库根目录。

    ``LUMINA_MATERIALS_DIR`` overrides the repository's material directory.
    ``LUMINA_MATERIALS_DIR`` 可指定仓库目录之外的耗材存储位置。
    """
    override = os.environ.get("LUMINA_MATERIALS_DIR", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(_BASE_DIR, "materials")


MATERIALS_DIR = _resolve_materials_dir()
os.makedirs(MATERIALS_DIR, exist_ok=True)


def get_asset_path(relative_path: str) -> str:
    """Resolve a source asset file path.
    解析源码资源文件路径。

    Args:
        relative_path (str): Relative path under assets/, e.g. 'smart_8color_stacks.npy'.
                             (assets/ 下的相对路径)

    Returns:
        str: Absolute path to the asset file. (资源文件的绝对路径)

    Raises:
        FileNotFoundError: If the asset file cannot be found. (找不到资源文件时抛出)
    """
    asset_rel = os.path.join("assets", relative_path)
    candidates = [
        os.path.join(_BASE_DIR, asset_rel),
        os.path.join(os.getcwd(), asset_rel),
        os.path.join("..", asset_rel),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    raise FileNotFoundError(f"Asset not found: {relative_path}\n" f"Searched: {candidates}")


class PrinterConfig:
    """Physical printer parameters (layer height, nozzle, backing)."""

    LAYER_HEIGHT: float = 0.08
    NOZZLE_WIDTH: float = 0.42
    COLOR_LAYERS: int = 5
    BACKING_MM: float = 1.2
    MAX_BACKING_THICKNESS_MM: float = 10.0
    BACKING_INFILL_DENSITY_MIN_PERCENT: int = 5
    BACKING_INFILL_DENSITY_DEFAULT_PERCENT: int = 100
    BACKING_INFILL_DENSITY_MAX_PERCENT: int = 100
    VIEWING_SURFACE_SOLID_DEPTH_MM: float = 3.0
    SHRINK_OFFSET: float = 0.02


SVG_PIXELS_PER_MM_DEFAULT: float = 10.0
SVG_PIXELS_PER_MM_MIN: float = 2.0
SVG_PIXELS_PER_MM_MAX: float = 50.0


def normalize_svg_pixels_per_mm(value: float | int | str | None) -> float:
    """Validate and normalize high-fidelity SVG raster density.
    校验并规范化高保真 SVG 光栅化采样密度。

    Args:
        value: Pixels per millimeter. ``None`` falls back to the default.
            每毫米像素数；``None`` 使用默认值。

    Returns:
        float: A value in ``[2.0, 50.0]`` with one decimal place.
            范围在 ``[2.0, 50.0]`` 内、精确到 0.1 的数值。

    Raises:
        ValueError: If the value is non-finite, out of range, or not aligned
            to a 0.1 step. (非有限数、越界或不是 0.1 步进时抛出。)
    """
    raw_value = SVG_PIXELS_PER_MM_DEFAULT if value is None else value
    try:
        decimal_value = Decimal(str(raw_value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("svg_pixels_per_mm must be a finite number") from exc
    if not decimal_value.is_finite():
        raise ValueError("svg_pixels_per_mm must be a finite number")

    minimum = Decimal(str(SVG_PIXELS_PER_MM_MIN))
    maximum = Decimal(str(SVG_PIXELS_PER_MM_MAX))
    if decimal_value < minimum or decimal_value > maximum:
        raise ValueError(
            "svg_pixels_per_mm must be between "
            f"{SVG_PIXELS_PER_MM_MIN:g} and {SVG_PIXELS_PER_MM_MAX:g}"
        )

    quantized = decimal_value.quantize(Decimal("0.1"))
    if decimal_value != quantized:
        raise ValueError("svg_pixels_per_mm must use 0.1 increments")
    return float(quantized)


class WorkerPoolConfig:
    """Worker pool configuration with env var overrides.
    工作进程池配置，支持环境变量覆盖。

    Attributes:
        MAX_WORKERS (int): Max number of worker processes. (最大工作进程数)
    """

    MAX_WORKERS: int = min(os.cpu_count() or 2, 4)

    @staticmethod
    def _log_invalid_env(
        *,
        event: str,
        env_var: str,
        raw_value: str,
        fallback: int | float,
        message: str,
    ) -> None:
        logging.getLogger("lumina.config").warning(
            message,
            extra={
                "event": event,
                "env_var": env_var,
                "raw_value": raw_value,
                "fallback": fallback,
                "error_type": "ValueError",
                "error_message": message,
            },
        )

    @classmethod
    def _read_positive_int_env(
        cls,
        env_var: str,
        fallback: int,
        *,
        event: str,
    ) -> int:
        raw_value = os.environ.get(env_var)
        if raw_value is None:
            return fallback
        value_text = raw_value.strip()
        if not value_text:
            return fallback
        try:
            value = int(value_text)
            if value <= 0:
                raise ValueError(f"{env_var} must be a positive integer")
        except ValueError:
            cls._log_invalid_env(
                event=event,
                env_var=env_var,
                raw_value=raw_value,
                fallback=fallback,
                message=f"{env_var} must be a positive integer; got {raw_value!r}",
            )
            return fallback
        return value

    @classmethod
    def from_env(cls) -> "WorkerPoolConfig":
        """Create config with environment variable overrides.
        创建配置，支持环境变量覆盖。

        Reads:
            LUMINA_MAX_WORKERS: Override MAX_WORKERS. (覆盖最大工作进程数)

        Returns:
            WorkerPoolConfig: Config instance with env overrides applied.
                              (应用环境变量覆盖后的配置实例)
        """
        cfg = cls()
        cfg.MAX_WORKERS = cls._read_positive_int_env(
            "LUMINA_MAX_WORKERS",
            cls.MAX_WORKERS,
            event="worker_pool_max_workers_invalid",
        )
        return cfg


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


class SmartConfigRYBW:
    """Configuration for the Smart 1296 RYBW (36x36) System.
    RYBW 6 色系统配置：White, Red, Yellow, Blue, Green, Black。
    """

    GRID_DIM: int = 36
    TOTAL_BLOCKS: int = 1296

    DEFAULT_BLOCK_SIZE: float = 5.0  # mm (Face Down mode)
    DEFAULT_GAP: float = 0.8  # mm

    FILAMENTS = {
        0: {"name": "White", "hex": "#FFFFFF", "rgb": [255, 255, 255], "td": 5.0},
        1: {"name": "Red", "hex": "#DC143C", "rgb": [220, 20, 60], "td": 3.0},
        2: {"name": "Yellow", "hex": "#FFE600", "rgb": [255, 230, 0], "td": 6.0},
        3: {"name": "Blue", "hex": "#0064F0", "rgb": [0, 100, 240], "td": 3.5},
        4: {"name": "Green", "hex": "#00AE42", "rgb": [0, 174, 66], "td": 2.0},
        5: {"name": "Black", "hex": "#000000", "rgb": [0, 0, 0], "td": 0.6},
    }


class ModelingMode(str, Enum):
    """建模模式枚举"""

    HIGH_FIDELITY = "high-fidelity"  # 高保真模式
    PIXEL = "pixel"  # 像素模式
    VECTOR = "vector"
    COLOR_CARD = "color-card"  # 验证色卡模式

    def get_display_name(self) -> str:
        """获取模式的显示名称"""
        display_names = {
            ModelingMode.HIGH_FIDELITY: "High-Fidelity",
            ModelingMode.PIXEL: "Pixel Art",
            ModelingMode.VECTOR: "Vector",
            ModelingMode.COLOR_CARD: "Color Card",
        }
        return display_names.get(self, self.value)


class ColorSystem:
    """Color model definitions for CMYW, RYBW, and 6-Color systems."""

    CMYW = {
        "name": "CMYW",
        "slots": ["White", "Cyan", "Magenta", "Yellow"],
        "preview": {0: [255, 255, 255, 255], 1: [0, 134, 214, 255], 2: [236, 0, 140, 255], 3: [244, 238, 42, 255]},
        "map": {"White": 0, "Cyan": 1, "Magenta": 2, "Yellow": 3},
        "corner_labels": ["白色 (左上)", "青色 (右上)", "品红 (右下)", "黄色 (左下)"],
        "corner_labels_en": ["White (TL)", "Cyan (TR)", "Magenta (BR)", "Yellow (BL)"],
    }

    RYBW = {
        "name": "RYBW",
        "slots": ["White", "Red", "Yellow", "Blue"],
        "preview": {0: [255, 255, 255, 255], 1: [220, 20, 60, 255], 2: [255, 230, 0, 255], 3: [0, 100, 240, 255]},
        "map": {"White": 0, "Red": 1, "Yellow": 2, "Blue": 3},
        "corner_labels": ["左上", "右上", "右下", "左下"],
        "corner_labels_en": ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"],
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
            5: [0, 0, 0, 255],  # Black (纯黑 #000000)
        },
        "map": {"White": 0, "Cyan": 1, "Magenta": 2, "Green": 3, "Yellow": 4, "Black": 5},
        "corner_labels": ["白色 (左上)", "青色 (右上)", "品红 (右下)", "黄色 (左下)"],
        "corner_labels_en": ["White (TL)", "Cyan (TR)", "Magenta (BR)", "Yellow (BL)"],
    }

    SIX_COLOR_RYBW = {
        "name": "6-Color (RYBW)",
        "base": 6,
        "layer_count": 5,
        "slots": ["White", "Red", "Yellow", "Blue", "Green", "Black"],
        "preview": {
            0: [255, 255, 255, 255],  # White
            1: [220, 20, 60, 255],  # Red
            2: [255, 230, 0, 255],  # Yellow
            3: [0, 100, 240, 255],  # Blue
            4: [0, 174, 66, 255],  # Green
            5: [0, 0, 0, 255],  # Black
        },
        "map": {"White": 0, "Red": 1, "Yellow": 2, "Blue": 3, "Green": 4, "Black": 5},
        "corner_labels": ["白色 (左上)", "红色 (右上)", "蓝色 (右下)", "黄色 (左下)"],
        "corner_labels_en": ["White (TL)", "Red (TR)", "Blue (BR)", "Yellow (BL)"],
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
            4: [0, 0, 0, 255],
            5: [193, 46, 31, 255],
            6: [10, 41, 137, 255],
            7: [0, 174, 66, 255],
        },
        "map": {"White": 0, "Cyan": 1, "Magenta": 2, "Yellow": 3, "Black": 4, "Red": 5, "Deep Blue": 6, "Green": 7},
        "corner_labels": ["TL", "TR", "BR", "BL"],
    }

    BW = {
        "name": "BW",
        "base": 2,
        "layer_count": 5,
        "slots": ["White", "Black"],
        "preview": {0: [255, 255, 255, 255], 1: [0, 0, 0, 255]},  # White  # Black (纯黑 #000000)
        "map": {"White": 0, "Black": 1},
        "corner_labels": ["白色 (左上)", "黑色 (右上)", "黑色 (右下)", "黑色 (左下)"],
        "corner_labels_en": ["White (TL)", "Black (TR)", "Black (BR)", "Black (BL)"],
    }

    FIVE_COLOR_EXTENDED = {
        "name": "5-Color Extended",
        "base": 5,
        "layer_count": 6,
        "slots": ["White", "Red", "Yellow", "Blue", "Black"],
        "preview": {
            0: [255, 255, 255, 255],  # White
            1: [220, 20, 60, 255],  # Red
            2: [255, 230, 0, 255],  # Yellow
            3: [0, 100, 240, 255],  # Blue
            4: [20, 20, 20, 255],  # Black
        },
        "map": {"White": 0, "Red": 1, "Yellow": 2, "Blue": 3, "Black": 4},
        "corner_labels": ["白色 (左上)", "红色 (右上)", "蓝色 (右下)", "黄色 (左下)", "黑色 (外层)"],
        "corner_labels_en": ["White (TL)", "Red (TR)", "Blue (BR)", "Yellow (BL)", "Black (Outer)"],
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

        mode_text = str(mode).strip()
        mode_upper = mode_text.upper()

        if "8-COLOR" in mode_upper or "8COLOR" in mode_upper:
            return ColorSystem.EIGHT_COLOR
        if "6-COLOR" in mode_upper or "6COLOR" in mode_upper or "RYBWGK" in mode_upper or "CMYWGK" in mode_upper:
            if "RYBW" in mode_upper:
                return ColorSystem.SIX_COLOR_RYBW
            return ColorSystem.SIX_COLOR
        if "4-COLOR" in mode_upper or "4COLOR" in mode_upper:
            if "CMYW" in mode_upper:
                return ColorSystem.CMYW
            return ColorSystem.RYBW
        if ("5-COLOR" in mode_upper or "5COLOR" in mode_upper) and "EXTENDED" in mode_upper:
            return ColorSystem.FIVE_COLOR_EXTENDED

        if mode_upper == "MERGED":
            return ColorSystem.EIGHT_COLOR

        if "RYBW" in mode_upper:
            return ColorSystem.RYBW
        if "CMYW" in mode_upper:
            return ColorSystem.CMYW
        if mode_upper == "BW" or mode_upper == "BW (BLACK & WHITE)":
            return ColorSystem.BW

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
        """Return list of (label, label) tuples for bed-size selectors."""
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
            options.append((profile.display_name, profile.bed_width, profile.bed_depth, profile.id))

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
    MIN_SAMPLING_MM: float = 0.01  # Ultra-high quality
    MAX_SAMPLING_MM: float = 0.20  # Low quality (faster)

    MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MAX_AREA_RATIO: float = 0.01
    MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MIN_ANCHOR_AREA_RATIO: float = 0.03
    MATERIAL_VECTOR_SMALL_SHAPE_SNAP_DELTA_E: float = 20.0
    VECTOR_NEAR_FILL_QUERY_DELTA_E: float = 2.0

    # Boolean operation tolerance
    BUFFER_TOLERANCE: float = 0.0  # Shapely buffer precision

    # Coordinate system
    FLIP_Y_AXIS: bool = False  # SVG Y-down → 3D Y-up (disabled by default)

    # Parallel processing
    ENABLE_PARALLEL: bool = False  # Parallel layer processing (experimental)
    MAX_WORKERS: int = 5  # Thread pool size


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
from typing import Any, Optional

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
    "anycubic": "AnycubicSlicerNext",
    "anycubic_slicer": "AnycubicSlicerNext",
    "anycubic_slicer_next": "AnycubicSlicerNext",
    "anycubic slicer": "AnycubicSlicerNext",
    "anycubic slicer next": "AnycubicSlicerNext",
    "anycubicslicer": "AnycubicSlicerNext",
    "anycubicslicernext": "AnycubicSlicerNext",
    "flashforge": "FlashStudio",
    "flash_studio": "FlashStudio",
    "flash studio": "FlashStudio",
    "flash studio desktop": "FlashStudio",
    "flashstudio": "FlashStudio",
    "qidi": "QIDIStudio",
    "qidi_studio": "QIDIStudio",
    "qidi studio": "QIDIStudio",
    "qidistudio": "QIDIStudio",
    "prusa": "PrusaSlicer",
    "prusa_slicer": "PrusaSlicer",
    "prusa slicer": "PrusaSlicer",
    "prusaslicer": "PrusaSlicer",
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


def normalize_nozzle_size(nozzle_size: Any) -> Optional[str]:
    """Normalize nozzle size input to a canonical one-decimal string.
    将喷嘴尺寸输入规范化为固定一位小数的标准字符串。

    Args:
        nozzle_size (Any): Raw nozzle size, e.g. 0.2, "0.2", or "0.2mm". (原始喷嘴尺寸)

    Returns:
        Optional[str]: Canonical size like "0.2", or None when absent/invalid.
                       (如 "0.2" 的标准尺寸，缺失或无效时返回 None)
    """
    if nozzle_size is None:
        return None

    if isinstance(nozzle_size, str):
        candidate = nozzle_size.strip().lower().replace("mm", "")
        if not candidate:
            return None
    else:
        candidate = str(nozzle_size)

    try:
        return f"{float(candidate):.1f}"
    except (TypeError, ValueError):
        return None


def format_native_nozzle_size(nozzle_size: Any) -> Optional[str]:
    """Format a slicer-native nozzle size without rounding it to Lumina slots.
    格式化切片软件原生喷嘴尺寸，不归并到 Lumina 的 0.2/0.4 档位。

    Args:
        nozzle_size (Any): Raw nozzle size, e.g. "0.25mm" or "0.40".
                           (原始喷嘴尺寸)

    Returns:
        Optional[str]: Stable decimal text like "0.25" or "0.4", or None
                       when absent/invalid. (稳定小数字符串，缺失或无效时返回 None)
    """
    if nozzle_size is None:
        return None

    if isinstance(nozzle_size, str):
        candidate = nozzle_size.strip().lower().replace("mm", "")
        if not candidate:
            return None
    else:
        candidate = str(nozzle_size)

    try:
        value = Decimal(candidate)
    except (InvalidOperation, ValueError):
        return None

    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if not text:
        return None
    return f"{text}.0" if "." not in text else text


@dataclass
class PrinterProfile:
    """Lumina printer hardware facts used by geometry and device selection.
    Lumina 几何和设备选择使用的打印机硬件事实。

    Attributes:
        id (str): Unique printer identifier, e.g. "bambu-h2d". (唯一打印机标识)
        display_name (str): Human-readable name, e.g. "Bambu Lab H2D". (显示名称)
        brand (str): Manufacturer brand, e.g. "Bambu Lab". (品牌)
        bed_width (int): Print bed width in mm. (打印床宽度，毫米)
        bed_depth (int): Print bed depth in mm. (打印床深度，毫米)
        bed_height (int): Max print height in mm. (最大打印高度，毫米)
        nozzle_count (int): Number of nozzles, 1=single, 2=dual. (喷头数量)
        is_dual_head (bool): Whether the printer has dual print heads. (是否双头)
        thumbnail (str): Thumbnail image filename, reserved for future use. (缩略图文件名，预留)
        supported_nozzle_sizes (tuple[str, ...]): Supported hardware nozzle sizes.
            (支持的硬件喷嘴尺寸)
    """

    id: str
    display_name: str
    brand: str
    bed_width: int
    bed_depth: int
    bed_height: int
    nozzle_count: int
    is_dual_head: bool
    thumbnail: str = ""
    supported_nozzle_sizes: tuple[str, ...] = ("0.2", "0.4")


# Supported slicer software list
SUPPORTED_SLICERS: list[dict[str, str]] = [
    {"id": "BambuStudio", "display_name": "BambuStudio"},
    {"id": "OrcaSlicer", "display_name": "OrcaSlicer"},
    {"id": "SnapmakerOrca", "display_name": "Snapmaker Orca"},
    {"id": "ElegooSlicer", "display_name": "ElegooSlicer"},
    {"id": "AnycubicSlicerNext", "display_name": "Anycubic Slicer Next"},
    {"id": "FlashStudio", "display_name": "Flash Studio Desktop"},
    {"id": "QIDIStudio", "display_name": "QIDI Studio"},
    {"id": "PrusaSlicer", "display_name": "PrusaSlicer 3.0.0-alpha13"},
]

DEFAULT_SLICER_ID: str = "BambuStudio"


PRINTER_PROFILES: dict[str, PrinterProfile] = {
    "bambu-a1-mini": PrinterProfile(
        id="bambu-a1-mini",
        display_name="Bambu Lab A1 mini",
        brand="Bambu Lab",
        bed_width=180,
        bed_depth=180,
        bed_height=180,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "bambu-a1": PrinterProfile(
        id="bambu-a1",
        display_name="Bambu Lab A1",
        brand="Bambu Lab",
        bed_width=256,
        bed_depth=256,
        bed_height=256,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "bambu-p1p": PrinterProfile(
        id="bambu-p1p",
        display_name="Bambu Lab P1P",
        brand="Bambu Lab",
        bed_width=256,
        bed_depth=256,
        bed_height=256,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "bambu-p1s": PrinterProfile(
        id="bambu-p1s",
        display_name="Bambu Lab P1S",
        brand="Bambu Lab",
        bed_width=256,
        bed_depth=256,
        bed_height=250,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "bambu-x1c": PrinterProfile(
        id="bambu-x1c",
        display_name="Bambu Lab X1 Carbon",
        brand="Bambu Lab",
        bed_width=256,
        bed_depth=256,
        bed_height=256,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "bambu-x1e": PrinterProfile(
        id="bambu-x1e",
        display_name="Bambu Lab X1E",
        brand="Bambu Lab",
        bed_width=256,
        bed_depth=256,
        bed_height=256,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "bambu-lab-x2d": PrinterProfile(
        id="bambu-lab-x2d",
        display_name="Bambu Lab X2D",
        brand="Bambu Lab",
        bed_width=256,
        bed_depth=256,
        bed_height=261,
        nozzle_count=2,
        is_dual_head=True,
    ),
    "bambu-lab-a2l": PrinterProfile(
        id="bambu-lab-a2l",
        display_name="Bambu Lab A2L",
        brand="Bambu Lab",
        bed_width=330,
        bed_depth=320,
        bed_height=325,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "bambu-h2d": PrinterProfile(
        id="bambu-h2d",
        display_name="Bambu Lab H2D",
        brand="Bambu Lab",
        bed_width=350,
        bed_depth=320,
        bed_height=325,
        nozzle_count=2,
        is_dual_head=True,
    ),
    "bambu-h2d-pro": PrinterProfile(
        id="bambu-h2d-pro",
        display_name="Bambu Lab H2D Pro",
        brand="Bambu Lab",
        bed_width=350,
        bed_depth=320,
        bed_height=325,
        nozzle_count=2,
        is_dual_head=True,
    ),
    "bambu-h2s": PrinterProfile(
        id="bambu-h2s",
        display_name="Bambu Lab H2S",
        brand="Bambu Lab",
        bed_width=340,
        bed_depth=320,
        bed_height=340,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "bambu-p2s": PrinterProfile(
        id="bambu-p2s",
        display_name="Bambu Lab P2S",
        brand="Bambu Lab",
        bed_width=256,
        bed_depth=256,
        bed_height=250,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "bambu-h2c": PrinterProfile(
        id="bambu-h2c",
        display_name="Bambu Lab H2C",
        brand="Bambu Lab",
        bed_width=330,
        bed_depth=320,
        bed_height=325,
        nozzle_count=2,
        is_dual_head=True,
    ),
    "bambu-h3c": PrinterProfile(
        id="bambu-h3c",
        display_name="Bambu Lab H3C",
        brand="Bambu Lab",
        bed_width=330,
        bed_depth=320,
        bed_height=325,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "snapmaker-u1": PrinterProfile(
        id="snapmaker-u1",
        display_name="Snapmaker U1",
        brand="Snapmaker",
        bed_width=270,
        bed_depth=270,
        bed_height=270,
        nozzle_count=4,
        is_dual_head=False,
    ),
    "elegoo-cc2": PrinterProfile(
        id="elegoo-cc2",
        display_name="Elegoo Centauri Carbon 2",
        brand="Elegoo",
        bed_width=256,
        bed_depth=256,
        bed_height=256,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "anycubic-kobra-3-max": PrinterProfile(
        id="anycubic-kobra-3-max",
        display_name="Anycubic Kobra 3 Max",
        brand="Anycubic",
        bed_width=426,
        bed_depth=420,
        bed_height=501,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "anycubic-kobra-3-v2": PrinterProfile(
        id="anycubic-kobra-3-v2",
        display_name="Anycubic Kobra 3 V2",
        brand="Anycubic",
        bed_width=255,
        bed_depth=255,
        bed_height=260,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "anycubic-kobra-s1": PrinterProfile(
        id="anycubic-kobra-s1",
        display_name="Anycubic Kobra S1",
        brand="Anycubic",
        bed_width=250,
        bed_depth=250,
        bed_height=250,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "anycubic-kobra-s1-max": PrinterProfile(
        id="anycubic-kobra-s1-max",
        display_name="Anycubic Kobra S1 Max",
        brand="Anycubic",
        bed_width=350,
        bed_depth=350,
        bed_height=350,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "anycubic-kobra-x": PrinterProfile(
        id="anycubic-kobra-x",
        display_name="Anycubic Kobra X",
        brand="Anycubic",
        bed_width=260,
        bed_depth=260,
        bed_height=260,
        nozzle_count=1,
        is_dual_head=False,
    ),
    "flashforge-ad5x": PrinterProfile(
        id="flashforge-ad5x",
        display_name="Flashforge AD5X",
        brand="Flashforge",
        bed_width=220,
        bed_depth=220,
        bed_height=220,
        nozzle_count=1,
        is_dual_head=False,
        supported_nozzle_sizes=("0.25", "0.4"),
    ),
    "flashforge-creator-5": PrinterProfile(
        id="flashforge-creator-5",
        display_name="Flashforge Creator 5",
        brand="Flashforge",
        bed_width=256,
        bed_depth=256,
        bed_height=256,
        nozzle_count=4,
        is_dual_head=False,
        supported_nozzle_sizes=("0.25", "0.4"),
    ),
    "flashforge-creator-5-pro": PrinterProfile(
        id="flashforge-creator-5-pro",
        display_name="Flashforge Creator 5 Pro",
        brand="Flashforge",
        bed_width=256,
        bed_depth=256,
        bed_height=256,
        nozzle_count=4,
        is_dual_head=False,
        supported_nozzle_sizes=("0.25", "0.4"),
    ),
    "flashforge-guider-3-ultra": PrinterProfile(
        id="flashforge-guider-3-ultra",
        display_name="Flashforge Guider 3 Ultra",
        brand="Flashforge",
        bed_width=300,
        bed_depth=330,
        bed_height=600,
        nozzle_count=2,
        is_dual_head=True,
        supported_nozzle_sizes=("0.4",),
    ),
    "flashforge-guider4": PrinterProfile(
        id="flashforge-guider4",
        display_name="Flashforge Guider4",
        brand="Flashforge",
        bed_width=300,
        bed_depth=300,
        bed_height=300,
        nozzle_count=1,
        is_dual_head=False,
        supported_nozzle_sizes=("0.25", "0.4"),
    ),
    "flashforge-guider4-pro": PrinterProfile(
        id="flashforge-guider4-pro",
        display_name="Flashforge Guider4 Pro",
        brand="Flashforge",
        bed_width=300,
        bed_depth=300,
        bed_height=300,
        nozzle_count=1,
        is_dual_head=False,
        supported_nozzle_sizes=("0.25", "0.4"),
    ),
    "qidi-q2": PrinterProfile(
        id="qidi-q2",
        display_name="Q2",
        brand="QIDI",
        bed_width=270,
        bed_depth=270,
        bed_height=256,
        nozzle_count=1,
        is_dual_head=False,
        supported_nozzle_sizes=("0.2", "0.4"),
    ),
    "qidi-q2c": PrinterProfile(
        id="qidi-q2c",
        display_name="Q2C",
        brand="QIDI",
        bed_width=270,
        bed_depth=270,
        bed_height=256,
        nozzle_count=1,
        is_dual_head=False,
        supported_nozzle_sizes=("0.2", "0.4"),
    ),
    "qidi-x-max-4": PrinterProfile(
        id="qidi-x-max-4",
        display_name="X-Max 4",
        brand="QIDI",
        bed_width=390,
        bed_depth=390,
        bed_height=340,
        nozzle_count=1,
        is_dual_head=False,
        supported_nozzle_sizes=("0.2", "0.4"),
    ),
    "qidi-x-plus-5": PrinterProfile(
        id="qidi-x-plus-5",
        display_name="X-Plus 5",
        brand="QIDI",
        bed_width=320,
        bed_depth=320,
        bed_height=300,
        nozzle_count=1,
        is_dual_head=False,
        supported_nozzle_sizes=("0.4",),
    ),
}

DEFAULT_PRINTER_ID: str = "bambu-h2d"


def get_printer_profile(printer_id: str) -> PrinterProfile:
    """Resolve a product or FatCat Prusa profile; unknown IDs retain H2D fallback.
    解析本体或 FatCat Prusa 机型；未知 ID 保留 H2D 回退。

    Args:
        printer_id (str): Printer identifier, e.g. "bambu-h2d". (打印机标识)

    Returns:
        PrinterProfile: Matching profile or default H2D profile. (匹配的配置或默认 H2D 配置)
    """
    normalized_printer_id = normalize_printer_profile_id(printer_id)
    profile = PRINTER_PROFILES.get(normalized_printer_id)
    if profile is not None:
        return profile
    if "prusa" in normalized_printer_id:
        from core.machine_registry import _registry_printer_slug
        from utils.fatcat_metadata import native_project_source_catalog

        sources = native_project_source_catalog("PrusaSlicer")["sources"]
        matches = [
            row for row in sources
            if normalized_printer_id in {
                _registry_printer_slug(row["display_name"]),
                str(row["machine_uid"]).replace(":", "-"),
            }
        ]
        if matches:
            source = matches[0]
            hardware = source["hardware_settings"]
            bed = hardware["bed"]
            return PrinterProfile(
                id=normalized_printer_id, display_name=source["display_name"], brand="Prusa",
                bed_width=int(bed["width"]), bed_depth=int(bed["height"]),
                bed_height=int(bed["max_print_height"]),
                nozzle_count=int(hardware["tool_count"]),
                is_dual_head=int(hardware["tool_count"]) > 1,
                supported_nozzle_sizes=tuple(dict.fromkeys(
                    str(row["nozzle_uid"]).removeprefix("nozzle:").removesuffix("mm")
                    for row in matches
                )),
            )
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
    schema_version: Optional[str] = None
    capabilities: list[str] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)

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

        d = dict(self.extensions)
        d.update({
            "palette": palette_obj,
            "manufacturer": self.manufacturer,
            "type": self.type,
            "max_color_layers": self.max_color_layers,
            "layer_height_mm": self.layer_height_mm,
            "line_width_mm": self.line_width_mm,
            "base_layers": self.base_layers,
            "base_channel_idx": self.base_channel_idx,
            "layer_order": self.layer_order,
        })
        if self.color_mode is not None:
            d["color_mode"] = self.color_mode
        if self.schema_version is not None:
            d["schema_version"] = self.schema_version
        if self.capabilities:
            d["capabilities"] = list(self.capabilities)
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
                    palette.append(
                        PaletteEntry(
                            color=str(color_name),
                            material=str(props.get("material", "PLA Basic")),
                            hex_color=props.get("hex_color"),
                            color_name=props.get("color_name"),
                        )
                    )
        elif isinstance(palette_raw, list):
            # 旧格式兼容: [{"color": "White", "material": "PLA Basic"}, ...]
            for item in palette_raw:
                if isinstance(item, dict) and "color" in item and "material" in item:
                    palette.append(
                        PaletteEntry(
                            color=str(item["color"]),
                            material=str(item["material"]),
                            hex_color=item.get("hex_color"),
                            color_name=item.get("color_name"),
                        )
                    )

        known_keys = {
            "palette",
            "manufacturer",
            "type",
            "color_mode",
            "max_color_layers",
            "layer_height_mm",
            "line_width_mm",
            "base_layers",
            "base_channel_idx",
            "layer_order",
            "schema_version",
            "capabilities",
            "name",
            "entries",
        }
        extensions = {
            key: value
            for key, value in data.items()
            if key not in known_keys
        }

        capabilities_raw = data.get("capabilities", [])
        capabilities = []
        if isinstance(capabilities_raw, list):
            capabilities = [str(item) for item in capabilities_raw if str(item)]

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
            schema_version=(str(data["schema_version"]) if data.get("schema_version") is not None else None),
            capabilities=capabilities,
            extensions=extensions,
        )

    def get_schema_version(self) -> str:
        """Return schema version for the current LUT metadata.
        返回当前 LUT 元数据的 schema 版本。
        """
        return self.schema_version or "1.0"

    def get_capabilities(self) -> list[str]:
        """Return normalized capability list.
        返回规范化后的能力列表。
        """
        return get_capabilities(self)

    def supports_predictive_match(self) -> bool:
        """Whether this LUT carries predictive runtime data.
        当前 LUT 是否携带预测式运行时数据。
        """
        return is_predictive_lut(self)

    def supports_dynamic_layer_height(self) -> bool:
        """Whether this LUT explicitly declares dynamic layer height support.
        当前 LUT 是否显式声明支持动态层高。
        """
        return "dynamic_layer_height" in set(self.capabilities) or "dynamic_layer_height" in self.get_capabilities()

    def supports_dynamic_layer_count(self) -> bool:
        """Whether this LUT/source explicitly supports variable color-layer counts.
        当前 LUT/source 是否显式支持可变颜色层数。
        """
        if "dynamic_layer_count" in self.get_capabilities():
            return True
        supported_modes = self.extensions.get("supported_modes")
        if isinstance(supported_modes, list):
            unique_counts = {
                int(item.get("color_layers", 0))
                for item in supported_modes
                if isinstance(item, dict) and int(item.get("color_layers", 0)) > 0
            }
            return len(unique_counts) > 1
        return False

    def supports_custom_recipe(self) -> bool:
        """Whether this LUT/source can drive custom recipe editing/prediction.
        当前 LUT/source 是否支持自定义配方编辑/预测。
        """
        if "custom_recipe" in self.get_capabilities():
            return True
        return bool(self.extensions.get("custom_recipe_supported"))

    def get_source_kind(self) -> str:
        """Return normalized source kind for the selected color source."""
        source_kind = self.extensions.get("source_kind")
        if isinstance(source_kind, str) and source_kind:
            return source_kind
        if self.extensions.get("runtime_package") is not None:
            return "predictive_package"
        return "legacy_lookup"

    def get_supported_modes(self) -> list[dict[str, Any]]:
        """Return normalized supported mode list for this LUT/source."""
        supported_modes = self.extensions.get("supported_modes")
        if isinstance(supported_modes, list):
            return [dict(item) for item in supported_modes if isinstance(item, dict)]
        return []

    def supports_dynamic_layer_count(self) -> bool:
        """Whether this source supports changing color layer counts.
        当前 source 是否支持动态叠色层数。
        """
        return "dynamic_layer_count" in set(self.capabilities) or "dynamic_layer_count" in self.get_capabilities()

    def supports_custom_recipe(self) -> bool:
        """Whether this source supports custom recipe editing/prediction.
        当前 source 是否支持自定义配方编辑/预测。
        """
        return "custom_recipe" in set(self.capabilities) or "custom_recipe" in self.get_capabilities()

    def get_source_kind(self) -> str:
        """Return normalized source kind.
        返回规范化后的 source 类型。
        """
        return get_source_kind(self)

    def get_supported_modes(self) -> list[dict[str, Any]]:
        """Return supported dynamic color-layer modes for the source.
        返回当前 source 支持的叠色层数/层高模式列表。
        """
        return get_supported_modes(self)

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


def get_schema_version(data_or_meta: LUTMetadata | dict | None) -> str:
    """Return LUT schema version from metadata or raw dict.
    从元数据或原始字典中获取 LUT schema 版本。
    """
    if isinstance(data_or_meta, LUTMetadata):
        return data_or_meta.get_schema_version()
    if isinstance(data_or_meta, dict):
        value = data_or_meta.get("schema_version")
        return str(value) if value is not None else "1.0"
    return "1.0"


def get_capabilities(data_or_meta: LUTMetadata | dict | None) -> list[str]:
    """Return normalized LUT capability list.
    返回规范化后的 LUT 能力列表。
    """
    capabilities: set[str] = set()
    payload: dict[str, Any] = {}

    if isinstance(data_or_meta, LUTMetadata):
        capabilities.update(str(item) for item in data_or_meta.capabilities if str(item))
        payload = dict(data_or_meta.extensions)
    elif isinstance(data_or_meta, dict):
        raw_caps = data_or_meta.get("capabilities", [])
        if isinstance(raw_caps, list):
            capabilities.update(str(item) for item in raw_caps if str(item))
        payload = dict(data_or_meta)

    if payload.get("runtime_package") is not None:
        capabilities.add("predictive_match")
    if payload.get("stage_model") is not None:
        capabilities.add("predictive_model")
    if payload.get("source_kind") in ("predictive_package", "predictive_stage_model"):
        capabilities.add("predictive_match")
    if payload.get("supported_modes"):
        capabilities.add("dynamic_layer_count")
    if payload.get("custom_recipe_supported"):
        capabilities.add("custom_recipe")
    if payload.get("source_kind") in ("predictive_package", "predictive_stage_model", "colordb_backed"):
        capabilities.add("native_reference")
    if "dynamic_layer_height" in payload.get("capabilities", []):
        capabilities.add("dynamic_layer_height")

    capabilities.add("legacy_lookup")
    return sorted(capabilities)


def is_predictive_lut(data_or_meta: LUTMetadata | dict | None) -> bool:
    """Return True when predictive runtime data is present.
    当存在预测式运行时数据时返回 True。
    """
    capabilities = set(get_capabilities(data_or_meta))
    if "predictive_match" in capabilities:
        return True
    if isinstance(data_or_meta, LUTMetadata):
        return data_or_meta.extensions.get("runtime_package") is not None
    if isinstance(data_or_meta, dict):
        return data_or_meta.get("runtime_package") is not None
    return False


def get_source_kind(data_or_meta: LUTMetadata | dict | None) -> str:
    """Return normalized source kind for metadata or raw payload."""
    if isinstance(data_or_meta, LUTMetadata):
        source_kind = data_or_meta.extensions.get("source_kind")
        if isinstance(source_kind, str) and source_kind:
            return source_kind
        if data_or_meta.extensions.get("runtime_package") is not None:
            return "predictive_package"
        if data_or_meta.extensions.get("stage_model") is not None:
            return "predictive_stage_model"
        return "legacy_lookup"
    if isinstance(data_or_meta, dict):
        source_kind = data_or_meta.get("source_kind")
        if isinstance(source_kind, str) and source_kind:
            return source_kind
        if data_or_meta.get("runtime_package") is not None:
            return "predictive_package"
        if data_or_meta.get("stage_model") is not None:
            return "predictive_stage_model"
        return "legacy_lookup"
    return "legacy_lookup"


def get_supported_modes(data_or_meta: LUTMetadata | dict | None) -> list[dict[str, Any]]:
    """Return normalized supported mode list.
    返回规范化的支持模式列表。
    """
    payload: dict[str, Any] = {}
    if isinstance(data_or_meta, LUTMetadata):
        payload = dict(data_or_meta.extensions)
    elif isinstance(data_or_meta, dict):
        payload = dict(data_or_meta)

    raw_modes = payload.get("supported_modes", [])
    if not isinstance(raw_modes, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw_modes:
        if not isinstance(item, dict):
            continue
        try:
            normalized.append(
                {
                    "mode_key": str(item.get("mode_key") or f"{float(item.get('layer_height_mm', 0.08)):.2f}x{int(item.get('color_layers', 0))}"),
                    "color_layers": int(item.get("color_layers", 0)),
                    "layer_height_mm": float(item.get("layer_height_mm", 0.08)),
                    "layer_order": str(item.get("layer_order", "Top2Bottom")),
                }
            )
        except (TypeError, ValueError):
            continue
    return normalized
