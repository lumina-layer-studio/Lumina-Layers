"""
Lumina Studio - LUT Preset Manager
LUT preset management module
"""

import copy
from collections import Counter
from dataclasses import dataclass
import os
import re
import json
import shutil
import glob
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import msgpack
import numpy as np

from api.structured_logging import get_logger
from config import LUTMetadata, PaletteEntry, ColorSystem, PrinterConfig, TEMP_DIR
from core.native_reference import (
    SOURCE_KIND_COLORD_DB,
    SOURCE_KIND_PACKAGE,
    SOURCE_KIND_STAGE_MODEL,
    _parse_model_package_payload,
    build_channel_key,
    build_model_package_runtime_payload,
    build_recipe_runtime_payload,
    derive_color_mode_from_palette_entries,
    derive_color_mode_from_palette_size,
    discover_native_reference_context,
    get_reference_db_root,
    get_reference_forward_model_root,
    get_reference_model_pack_root,
    looks_like_reference_colordb,
    looks_like_reference_recipe_set,
    looks_like_reference_stage_model,
    normalize_channel_key,
    parse_model_package_file,
    select_native_db_paths_for_mode,
    split_channel_key,
    standard_lab_to_rgb_uint8,
)
from core.recipe_order import convert_recipe_between_orders, expand_recipe_by_layer_height, pad_recipe_to_layer_count

_log = get_logger(__name__)
_LUT_PRESET_CACHE_TTL_SECONDS = 30.0
_lut_preset_cache_lock = threading.Lock()
_lut_preset_cache_at: float | None = None
_lut_preset_cache_value: dict[str, str] | None = None
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1
_RECONSTRUCTABLE_LUT_COUNTS = frozenset({32, 1024, 1296, 2468, 2738})


def _looks_like_missing_keyed_stacks(stacks: object, color_count: int) -> bool:
    if color_count not in _RECONSTRUCTABLE_LUT_COUNTS:
        return False
    if not isinstance(stacks, np.ndarray):
        return False
    if stacks.ndim != 2 or stacks.shape[0] != color_count or stacks.shape[1] <= 0:
        return False
    return bool(np.all(stacks < 0))


def _resolve_native_base_channel_idx(
    channel_keys: list[str] | tuple[str, ...],
    preferred_key: str | None = None,
) -> int:
    """Resolve native base channel index from an explicit key or white fallback."""
    normalized_keys = [normalize_channel_key(str(key)) for key in channel_keys if str(key)]
    if preferred_key:
        normalized_preferred = normalize_channel_key(preferred_key)
        if normalized_preferred in normalized_keys:
            return normalized_keys.index(normalized_preferred)
    for fallback in ("white|plabasic", "white|pla basic"):
        if fallback in normalized_keys:
            return normalized_keys.index(fallback)
    return 0


def _resolve_model_package_base_channel_idx(
    payload: dict[str, Any],
    channel_keys: list[str] | tuple[str, ...],
    default_mode: dict[str, Any] | None,
) -> int:
    """Resolve native package/stage base channel index from model package metadata."""
    preferred_key: str | None = None
    modes_raw = payload.get("modes", [])
    if isinstance(modes_raw, list):
        if default_mode is not None:
            for item in modes_raw:
                if not isinstance(item, dict):
                    continue
                try:
                    if (
                        int(item.get("color_layers", 0)) == int(default_mode.get("color_layers", 0))
                        and abs(float(item.get("layer_height_mm", 0.0)) - float(default_mode.get("layer_height_mm", 0.0))) <= 1e-3
                        and str(item.get("layer_order", "Top2Bottom")) == str(default_mode.get("layer_order", "Top2Bottom"))
                    ):
                        preferred_key = item.get("base_channel_key")
                        break
                except (TypeError, ValueError):
                    continue
        if preferred_key is None:
            for item in modes_raw:
                if isinstance(item, dict) and item.get("base_channel_key"):
                    preferred_key = str(item.get("base_channel_key"))
                    break
    return _resolve_native_base_channel_idx(channel_keys, preferred_key)


def _supported_modes_from_runtime_package(runtime_package: dict[str, Any]) -> list[dict[str, Any]]:
    """Build normalized supported-mode metadata from a validated runtime package.
    从已验证的 runtime package 构建规范化的 supported_modes 元数据。
    """
    modes_raw = runtime_package.get("modes", {})
    if not isinstance(modes_raw, dict):
        return []

    supported_modes: list[dict[str, Any]] = []
    for mode_key, item in modes_raw.items():
        if not isinstance(item, dict):
            continue
        try:
            supported_modes.append(
                {
                    "mode_key": str(
                        mode_key
                        or f"{float(item.get('layer_height_mm', 0.08)):.2f}x{int(item.get('color_layers', 0))}"
                    ),
                    "color_layers": int(item.get("color_layers", 0)),
                    "layer_height_mm": float(item.get("layer_height_mm", 0.08)),
                    "layer_order": str(item.get("layer_order", "Top2Bottom")),
                }
            )
        except (TypeError, ValueError):
            continue
    return supported_modes


def _select_preferred_supported_mode(supported_modes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer the canonical 5-layer mode, otherwise fall back to the first usable mode.
    优先选择标准 5 层模式，否则回退到第一个可用模式。
    """
    if not supported_modes:
        return None
    return next(
        (mode for mode in supported_modes if int(mode.get("color_layers", 0)) == 5),
        supported_modes[0],
    )


@dataclass(frozen=True)
class _NativeDbIndexItem:
    name: str
    path: str
    color_mode: str


@dataclass(frozen=True)
class _NativeBrandIndexItem:
    brand_key: str
    material_type: str
    vendor: str
    display_name: str
    db_options: tuple[_NativeDbIndexItem, ...]
    default_db_names: tuple[str, ...]
    package_name: str | None
    model_name: str | None
    supported_modes: tuple[dict[str, Any], ...]
    package_path: str | None
    model_path: str | None


class LUTManager:
    """LUT preset manager"""
    
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    LUT_PRESET_DIR = os.path.join(_BASE_DIR, "lut-preset")

    @classmethod
    def _resolve_mutable_lut_dir(
        cls,
        env_name: str,
        fallback_name: str,
    ) -> Path:
        """Resolve one mutable LUT directory outside immutable runtimes."""

        override = os.environ.get(env_name, "").strip()
        if not override:
            return Path(cls.LUT_PRESET_DIR) / fallback_name
        resolved = Path(override).expanduser()
        if not resolved.is_absolute():
            raise ValueError(f"{env_name} must be an absolute directory path")
        return resolved

    @classmethod
    def custom_lut_dir(cls) -> Path:
        """Return the writable custom-LUT directory.

        返回可写的用户自定义 LUT 目录。

        Returns:
            Configured directory or legacy fallback. 配置目录或旧版默认目录。

        Raises:
            ValueError: If the override is relative. 覆盖路径为相对路径时抛出。
        """

        return cls._resolve_mutable_lut_dir("LUMINA_CUSTOM_LUT_DIR", "Custom")

    @classmethod
    def cloud_lut_dir(cls) -> Path:
        """Return the writable cloud-LUT directory.

        返回可写的云端 LUT 目录。

        Returns:
            Configured directory or legacy fallback. 配置目录或旧版默认目录。

        Raises:
            ValueError: If the override is relative. 覆盖路径为相对路径时抛出。
        """

        return cls._resolve_mutable_lut_dir("LUMINA_CLOUD_LUT_DIR", "Cloud")

    @classmethod
    def cloud_lut_sync_dir(cls) -> Path:
        """Return the writable cloud-LUT synchronization metadata directory.

        返回可写的云端 LUT 同步元数据目录。

        Returns:
            Synchronization metadata directory. 同步元数据目录。

        Raises:
            ValueError: If the cloud override is relative. 云端覆盖路径为相对路径时抛出。
        """

        if os.environ.get("LUMINA_CLOUD_LUT_DIR", "").strip():
            return cls.cloud_lut_dir().parent / "_sync" / "luts"
        return Path(cls.LUT_PRESET_DIR) / "_sync" / "luts"

    @classmethod
    def logical_lut_path(cls, file_path: str | Path) -> str | None:
        """Map a physical LUT path to its stable catalog-relative identity.

        将 LUT 实际路径映射为稳定的目录逻辑标识。

        Args:
            file_path: Physical LUT path. LUT 实际路径。

        Returns:
            Logical identity, or None outside known roots. 逻辑标识，未知根目录返回 None。

        Raises:
            ValueError: If a configured root is relative. 配置根目录为相对路径时抛出。
        """

        try:
            resolved = Path(file_path).resolve()
        except OSError:
            return None
        roots = (
            ("Custom", cls.custom_lut_dir()),
            ("Cloud", cls.cloud_lut_dir()),
            ("", Path(cls.LUT_PRESET_DIR)),
        )
        for prefix, root in roots:
            try:
                relative = resolved.relative_to(root.resolve())
            except (OSError, ValueError):
                continue
            if not relative.parts:
                return prefix or None
            logical = relative.as_posix()
            return f"{prefix}/{logical}" if prefix else logical
        return None

    _native_source_index_cache: tuple[_NativeBrandIndexItem, ...] | None = None
    _native_source_index_cache_at: float | None = None
    _native_source_index_lock = threading.Lock()
    _source_catalog_cache: dict[str, list[dict]] | None = None
    _source_catalog_cache_checked_at: float | None = None
    _source_catalog_cache_lock = threading.Lock()
    NATIVE_SOURCE_INDEX_TTL_SECONDS = 30.0
    SOURCE_CATALOG_SIGNATURE_TTL_SECONDS = 5.0
    _LEGACY_MULTI_STANDARD_SLOT_ORDER: tuple[str, ...] = (
        "White",
        "Cyan",
        "Magenta",
        "Yellow",
        "Black",
        "Red",
        "Deep Blue",
        "Green",
    )
    _LEGACY_MULTI_COLOR_ALIASES: dict[str, str] = {
        "white": "White",
        "cyan": "Cyan",
        "magenta": "Magenta",
        "yellow": "Yellow",
        "black": "Black",
        "red": "Red",
        "blue": "Deep Blue",
        "deepblue": "Deep Blue",
        "green": "Green",
    }

    @classmethod
    def _scan_roots(cls) -> list[tuple[str, str]]:
        roots: list[tuple[str, str]] = []
        if os.path.exists(cls.LUT_PRESET_DIR):
            roots.append(("Preset", cls.LUT_PRESET_DIR))
        reference_db_root = get_reference_db_root()
        reference_model_pack_root = get_reference_model_pack_root()
        reference_forward_model_root = get_reference_forward_model_root()
        if reference_db_root.exists():
            roots.append(("ReferenceDB", str(reference_db_root)))
        if reference_model_pack_root.exists():
            roots.append(("ReferencePack", str(reference_model_pack_root)))
        if reference_forward_model_root.exists():
            roots.append(("ReferenceModel", str(reference_forward_model_root)))
        return roots

    @classmethod
    def _scan_legacy_roots(cls) -> list[tuple[str, str]]:
        """Return roots that should remain visible to legacy LUT consumers."""

        roots: list[tuple[str, str]] = []
        if os.path.exists(cls.LUT_PRESET_DIR):
            roots.append(("Preset", cls.LUT_PRESET_DIR))
        preset_root = Path(cls.LUT_PRESET_DIR).resolve()
        for label, mutable_root in (
            ("Custom", cls.custom_lut_dir()),
            ("Cloud", cls.cloud_lut_dir()),
        ):
            try:
                resolved = mutable_root.resolve()
                resolved.relative_to(preset_root)
                is_inside_preset = True
            except (OSError, ValueError):
                is_inside_preset = False
            if not is_inside_preset and mutable_root.exists():
                roots.append((label, str(mutable_root)))
        return roots

    @staticmethod
    def _display_name_for_root(root_label: str, root_dir: str, file_path: str) -> str:
        rel_path = os.path.relpath(file_path, root_dir)
        parts = Path(rel_path).parts
        stem = Path(rel_path).stem
        if root_label == "Preset":
            if len(parts) > 1:
                return " - ".join([*parts[:-1], stem])
            return stem
        if root_label in {"Custom", "Cloud"}:
            return " - ".join([root_label, *parts[:-1], stem])
        if root_label == "ReferenceDB":
            if len(parts) >= 3:
                return f"ReferenceDB - {parts[0]} - {parts[1]} - {stem}"
            return f"ReferenceDB - {stem}"
        if root_label == "ReferencePack":
            return f"ReferencePack - {stem}"
        if root_label == "ReferenceModel":
            return f"ReferenceModel - {stem}"
        return stem

    @staticmethod
    def _is_preset_sync_file(root_label: str, root_dir: str, file_path: str) -> bool:
        if root_label != "Preset":
            return False
        rel_parts = Path(os.path.relpath(file_path, root_dir)).parts
        return bool(rel_parts and rel_parts[0] == "_sync")
    
    @classmethod
    def get_all_lut_files(cls) -> dict[str, str]:
        """Scan and return all available LUT files.
        扫描并返回所有可用的 LUT 文件。

        Returns:
            dict[str, str]: 映射 {显示名称: 文件路径}。
        """
        global _lut_preset_cache_at, _lut_preset_cache_value
        now = time.monotonic()
        with _lut_preset_cache_lock:
            if (
                _lut_preset_cache_value is not None
                and _lut_preset_cache_at is not None
                and now - _lut_preset_cache_at <= _LUT_PRESET_CACHE_TTL_SECONDS
            ):
                _log.debug(
                    "LUT presets cache hit",
                    extra={
                        "event": "lut_presets_cache_hit",
                        "preset_count": len(_lut_preset_cache_value),
                        "cache_age_ms": round((now - _lut_preset_cache_at) * 1000, 3),
                    },
                )
                return dict(_lut_preset_cache_value)

        lut_files: dict[str, str] = {}

        # Priority: .msgpack > .json > .npz > .npy (higher priority overwrites lower)
        _EXT_PRIORITY = {".npy": 0, ".npz": 1, ".json": 2, ".msgpack": 3}
        # Track priority of each display_name to avoid lower-priority overwrite
        _name_priority: dict[str, int] = {}

        for root_label, root_dir in cls._scan_legacy_roots():
            patterns = [
                os.path.join(root_dir, "**", "*.npy"),
                os.path.join(root_dir, "**", "*.json"),
                os.path.join(root_dir, "**", "*.npz"),
                os.path.join(root_dir, "**", "*.msgpack"),
            ]
            all_files: list[str] = []
            for pattern in patterns:
                all_files.extend(glob.glob(pattern, recursive=True))

            for file_path in all_files:
                if cls._is_preset_sync_file(root_label, root_dir, file_path):
                    continue
                display_name = cls._display_name_for_root(root_label, root_dir, file_path)
                ext = Path(file_path).suffix.lower()
                priority = _EXT_PRIORITY.get(ext, -1)
                if display_name not in lut_files or priority > _name_priority.get(display_name, -1):
                    lut_files[display_name] = file_path
                    _name_priority[display_name] = priority
        
        # Sort by name
        lut_files = dict(sorted(lut_files.items()))
        
        _log.info(
            "Discovered LUT presets",
            extra={
                "event": "lut_presets_discovered",
                "preset_count": len(lut_files),
                "root_count": len(cls._scan_legacy_roots()),
            },
        )
        with _lut_preset_cache_lock:
            _lut_preset_cache_at = time.monotonic()
            _lut_preset_cache_value = dict(lut_files)
        return dict(lut_files)

    @classmethod
    def invalidate_preset_cache(cls) -> None:
        """Drop the cached LUT preset scan so the next call rescans from disk.
        立即丢弃 LUT 预设扫描缓存，让下次调用重新扫盘。

        Use this whenever ``LUT_PRESET_DIR`` changes during a process lifetime
        (e.g. tests that point the manager at a temporary directory) or when
        on-disk files mutate inside the 30 s TTL window. Without this, callers
        observe stale results from the previous scan because
        :meth:`get_all_lut_files` caches at module level for performance.

        在进程生命周期内 ``LUT_PRESET_DIR`` 变更（如测试切到临时目录），
        或磁盘文件在 30 秒 TTL 内发生变化时调用，避免读到陈旧扫描结果。
        """

        global _lut_preset_cache_at, _lut_preset_cache_value
        with _lut_preset_cache_lock:
            _lut_preset_cache_at = None
            _lut_preset_cache_value = None
        cls.invalidate_source_catalog_cache()

    @classmethod
    def get_lut_choices(cls):
        """
        Get LUT choice list (for Dropdown).
        获取 LUT 选择列表（用于下拉菜单）。

        Returns:
            list: Display name list / 显示名称列表
        """
        lut_files = cls.get_all_lut_files()
        return list(lut_files.keys())

    # JSON LUT 颜色数量 → 模式映射（与 lut_merger._SIZE_TO_MODE 对齐）
    # 1024 和 1296 已移除：多个变体共享相同数量（CMYW/RYBW 均为 1024，
    # 6-Color CMYW/RYBW 均为 1296），通过 _detect_variant_from_palette 处理
    _JSON_SIZE_TO_MODE: dict[int, str] = {
        32: "BW (Black & White)",
        2468: "5-Color Extended",
        2738: "8-Color Max",
    }

    @staticmethod
    def _detect_variant_from_palette(data: dict, base_mode: str) -> str:
        """Detect RYBW/CMYW variant from palette color names.
        从 palette 颜色名称推断 RYBW/CMYW 变体。

        For ambiguous entry counts (1024 for 4-Color, 1296 for 6-Color),
        inspect palette keys/color fields to distinguish RYBW from CMYW.
        对于有歧义的 entries 数量（4-Color 的 1024、6-Color 的 1296），
        通过检查 palette 的键名或 color 字段区分 RYBW 和 CMYW 变体。

        Args:
            data (dict): Parsed JSON data containing a "palette" field.
                         (包含 "palette" 字段的已解析 JSON 数据)
            base_mode (str): Base color mode without variant, e.g. "4-Color" or "6-Color".
                             (不含变体的基础颜色模式，如 "4-Color" 或 "6-Color")

        Returns:
            str: Full color mode string with variant, e.g. "4-Color (RYBW)".
                 (含变体的完整颜色模式字符串)
        """
        palette_raw = data.get("palette", {})
        color_names: set[str] = set()
        if isinstance(palette_raw, dict):
            color_names = {k.lower() for k in palette_raw.keys()}
        elif isinstance(palette_raw, list):
            color_names = {
                item.get("color", "").lower()
                for item in palette_raw
                if isinstance(item, dict)
            }

        rybw_indicators = {"red", "blue"}
        cmyw_indicators = {"cyan", "magenta"}

        if base_mode == "4-Color":
            if rybw_indicators & color_names:
                return "4-Color (RYBW)"
            if cmyw_indicators & color_names:
                return "4-Color (CMYW)"
            return "4-Color (CMYW)"  # default fallback

        if base_mode == "6-Color":
            if rybw_indicators & color_names:
                return "6-Color (RYBWGK 1296)"
            return "6-Color (CMYWGK 1296)"  # default fallback

        return f"{base_mode}"

    @staticmethod
    def _canonicalize_legacy_color_mode(
        color_mode: str | None,
        data: dict[str, Any] | None = None,
    ) -> str | None:
        """Canonicalize legacy base color modes using palette data when available.
        当可用时，结合 palette 数据将旧版基础颜色模式规范化为 canonical 变体。
        """
        if not isinstance(color_mode, str):
            return color_mode

        normalized = color_mode.strip()
        normalized_key = re.sub(r"[^a-z0-9]+", "", normalized.lower())
        if normalized_key == "cmyw":
            return "4-Color (CMYW)"
        if normalized_key == "rybw":
            return "4-Color (RYBW)"
        if normalized_key == "bw":
            return "BW (Black & White)"
        if normalized_key == "merged":
            return "Merged"
        if normalized_key == "rybwgk":
            return "6-Color (RYBWGK 1296)"
        if normalized_key == "cmywgk":
            return "6-Color (CMYWGK 1296)"
        if normalized_key == "4color":
            if isinstance(data, dict):
                return LUTManager._detect_variant_from_palette(data, "4-Color")
            return "4-Color (RYBW)"
        if "4color" in normalized_key:
            if "cmyw" in normalized_key:
                return "4-Color (CMYW)"
            if "rybw" in normalized_key:
                return "4-Color (RYBW)"
        if normalized_key == "6color":
            if isinstance(data, dict):
                return LUTManager._detect_variant_from_palette(data, "6-Color")
            return "6-Color (CMYWGK 1296)"
        if "6color" in normalized_key:
            if "rybw" in normalized_key:
                return "6-Color (RYBWGK 1296)"
            if "cmyw" in normalized_key:
                return "6-Color (CMYWGK 1296)"
        if normalized_key == "8color":
            return "8-Color Max"
        if "5color" in normalized_key and "extended" in normalized_key:
            return "5-Color Extended"
        return normalized

    @staticmethod
    def infer_color_mode(display_name: str, file_path: str) -> str:
        """Infer color mode from LUT display name or file path.
        根据 LUT 显示名称或文件路径推断颜色模式。

        - .npz → 直接返回 "Merged"
        - .msgpack → 按 channel_keys / package metadata 判断
        - .json → 轻量读取 JSON，按原生 source 类型或 entries 数量判断
        - .npy → 按文件名关键词匹配

        Args:
            display_name: LUT 显示名称。
            file_path: LUT 文件路径。

        Returns:
            str: 推断出的颜色模式字符串，与前端 ColorMode 枚举对应。
        """
        ext = os.path.splitext(file_path)[1].lower()

        # .npz 文件通常是合并 LUT
        if ext == ".npz":
            return "Merged"

        if ext == ".msgpack":
            try:
                ctx = parse_model_package_file(file_path)
                return derive_color_mode_from_palette_entries(ctx.channel_keys, "Merged")
            except Exception:
                return "Merged"

        # .json (Keyed JSON) — 自描述格式，从内容判断模式
        if ext == ".json":
            return LUTManager._infer_color_mode_from_json(file_path)

        # .npy — 无元数据，按文件名关键词匹配
        return LUTManager._infer_color_mode_by_name(display_name, file_path)

    @staticmethod
    def _infer_color_mode_from_json(file_path: str) -> str:
        """Infer color mode from JSON file content (lightweight read, no numpy).
        从 JSON 文件内容推断颜色模式（轻量读取，不做 numpy 运算）。

        Priority: stored color_mode > palette-based variant detection > size mapping.
        优先级：存储的 color_mode > 基于 palette 的变体检测 > 数量映射。

        支持两种 JSON 格式：
        - flat-list: 顶层为数组，len(data) 即 entries 数量
        - keyed: 顶层为对象，len(data["entries"]) 即 entries 数量
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            _log.warning(
                "Failed to read JSON for LUT mode detection",
                extra={
                    "event": "lut_mode_detection_json_read_failed",
                    "path": file_path,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            return "4-Color (CMYW)"

        # 计算 entries 数量
        if isinstance(data, list):
            count = len(data)
        elif isinstance(data, dict):
            # 优先使用存储的 color_mode
            stored_mode = data.get("color_mode")
            if stored_mode and isinstance(stored_mode, str):
                return LUTManager._canonicalize_legacy_color_mode(stored_mode, data)
            if looks_like_reference_stage_model(data):
                channels = data.get("parameters", {}).get("channels", [])
                return derive_color_mode_from_palette_entries(channels, "Merged")
            if looks_like_reference_recipe_set(data):
                palette = data.get("palette", [])
                return derive_color_mode_from_palette_entries(palette, "Merged")
            if looks_like_reference_colordb(data):
                palette = data.get("palette", [])
                return derive_color_mode_from_palette_entries(palette, "Merged")
            entries = data.get("entries", [])
            count = len(entries)
        else:
            count = 0

        # 对于有歧义的数量，通过 palette 名称区分变体
        if count == 1024 and isinstance(data, dict):
            return LUTManager._detect_variant_from_palette(data, "4-Color")
        if count == 1296 and isinstance(data, dict):
            return LUTManager._detect_variant_from_palette(data, "6-Color")

        # 无歧义的数量直接映射
        mode = LUTManager._JSON_SIZE_TO_MODE.get(count)
        if mode:
            return mode

        # BW 容差：30-36
        if 30 <= count <= 36:
            return "BW (Black & White)"

        # 非标准尺寸 → Merged
        if count > 0:
            return "Merged"

        # 空文件回退
        return "4-Color (CMYW)"

    @staticmethod
    def _infer_color_mode_by_name(display_name: str, file_path: str) -> str:
        """按文件名关键词匹配颜色模式（用于 .npy 等无元数据格式）。"""
        combined = (display_name + " " + file_path).upper()

        if "8色" in combined or "8-COLOR" in combined or "8COLOR" in combined:
            return "8-Color Max"
        if "6色" in combined or "6-COLOR" in combined or "6COLOR" in combined:
            if "RYBW" in combined or "红黄蓝" in combined:
                return "6-Color (RYBWGK 1296)"
            return "6-Color (CMYWGK 1296)"
        # 5-Color Extended 必须在 4-Color 之前检测
        if "5色" in combined or "5-COLOR" in combined or "5COLOR" in combined:
            return "5-Color Extended"
        # CMYW/RYBW 必须在 BW 之前检测，避免 "RYBW" 中的 "BW" 误匹配
        if "CMYW" in combined or "青品黄" in combined:
            return "4-Color (CMYW)"
        if "RYBW" in combined or "红黄蓝" in combined:
            return "4-Color (RYBW)"
        if "4色" in combined or "4-COLOR" in combined or "4COLOR" in combined:
            return "4-Color (CMYW)"
        # BW 单独检测
        if "黑白" in combined or "B&W" in combined:
            return "BW (Black & White)"
        if re.search(r"(?<![A-Z])BW(?![A-Z])", combined):
            return "BW (Black & White)"

        # 默认回退
        return "4-Color (CMYW)"
    
    @classmethod
    def get_lut_path(cls, display_name: str) -> str | None:
        """Get LUT file path by display name.
        根据显示名称获取 LUT 文件路径。

        Args:
            display_name: LUT 显示名称。

        Returns:
            str | None: 文件路径，未找到时返回 None。
        """
        lut_files = cls.get_all_lut_files()
        return lut_files.get(display_name)

    @classmethod
    def _iter_scanned_lut_files(cls):
        """Yield every discovered LUT-like file with its source root metadata."""

        for root_label, root_dir in cls._scan_roots():
            patterns = [
                os.path.join(root_dir, "**", "*.npy"),
                os.path.join(root_dir, "**", "*.json"),
                os.path.join(root_dir, "**", "*.npz"),
                os.path.join(root_dir, "**", "*.msgpack"),
            ]
            seen: set[str] = set()
            for pattern in patterns:
                for file_path in glob.glob(pattern, recursive=True):
                    resolved = str(Path(file_path).resolve())
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    yield root_label, root_dir, resolved

    @classmethod
    def invalidate_native_source_index_cache(cls) -> None:
        """Clear the cached native source index."""

        with cls._native_source_index_lock:
            cls._native_source_index_cache = None
            cls._native_source_index_cache_at = None
        cls.invalidate_source_catalog_cache()

    @classmethod
    def invalidate_source_catalog_cache(cls) -> None:
        """Clear cached source catalog groups.
        清空源目录分组缓存。
        """

        with cls._source_catalog_cache_lock:
            cls._source_catalog_cache = None
            cls._source_catalog_cache_checked_at = None

    @classmethod
    def _build_native_source_index(cls) -> tuple[_NativeBrandIndexItem, ...]:
        groups: dict[tuple[str, str], dict[str, Any]] = {}

        for root_label, _root_dir, file_path in cls._iter_scanned_lut_files():
            if root_label == "Preset":
                continue

            ext = Path(file_path).suffix.lower()
            data = None
            native_ctx = None
            try:
                if ext == ".json":
                    with open(file_path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    native_ctx = discover_native_reference_context(file_path, data)
                elif ext == ".msgpack":
                    native_ctx = discover_native_reference_context(file_path)
                else:
                    continue
            except Exception as exc:
                _log.warning(
                    "Native source discovery failed",
                    extra={
                        "event": "lut_native_source_discovery_failed",
                        "path": file_path,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                continue

            if native_ctx is None or not native_ctx.vendor or not native_ctx.material_type:
                continue

            brand_key = f"{native_ctx.vendor.lower().replace(' ', '')}_{native_ctx.material_type.lower()}"
            group_key = (native_ctx.vendor, native_ctx.material_type)
            group = groups.setdefault(
                group_key,
                {
                    "brand_key": brand_key,
                    "material_type": native_ctx.material_type,
                    "vendor": native_ctx.vendor,
                    "display_name": f"{native_ctx.vendor} {native_ctx.material_type}",
                    "db_options": {},
                    "default_db_names": set(),
                    "package_name": None,
                    "model_name": None,
                    "supported_modes": [],
                    "_supported_mode_keys": set(),
                    "package_path": native_ctx.package_path,
                    "model_path": native_ctx.stage_model_path,
                },
            )

            if native_ctx.package_path and group["package_path"] is None:
                group["package_path"] = native_ctx.package_path
            if native_ctx.stage_model_path and group["model_path"] is None:
                group["model_path"] = native_ctx.stage_model_path

            if native_ctx.source_kind == SOURCE_KIND_COLORD_DB:
                group["db_options"][Path(file_path).name] = _NativeDbIndexItem(
                    name=Path(file_path).name,
                    path=file_path,
                    color_mode=cls.infer_color_mode(Path(file_path).name, file_path),
                )
            elif native_ctx.source_kind == SOURCE_KIND_PACKAGE:
                group["package_name"] = Path(file_path).name
            elif native_ctx.source_kind == SOURCE_KIND_STAGE_MODEL:
                group["model_name"] = Path(file_path).name

            for db_path in native_ctx.db_paths:
                group["default_db_names"].add(Path(db_path).name)
            for mode in native_ctx.supported_modes:
                mode_key = (
                    str(mode.get("mode_key"))
                    if isinstance(mode, dict) and mode.get("mode_key")
                    else f"{float(mode.get('layer_height_mm', 0.0)):.2f}x{int(mode.get('color_layers', 0))}"
                )
                if mode_key in group["_supported_mode_keys"]:
                    continue
                group["_supported_mode_keys"].add(mode_key)
                group["supported_modes"].append(dict(mode))

        index: list[_NativeBrandIndexItem] = []
        for group_key in sorted(groups, key=lambda item: (item[0].lower(), item[1].lower())):
            group = groups[group_key]
            db_options = tuple(
                sorted(group["db_options"].values(), key=lambda item: item.name)
            )
            default_db_names = tuple(sorted(group["default_db_names"])) or tuple(item.name for item in db_options)
            index.append(
                _NativeBrandIndexItem(
                    brand_key=group["brand_key"],
                    material_type=group["material_type"],
                    vendor=group["vendor"],
                    display_name=group["display_name"],
                    db_options=db_options,
                    default_db_names=default_db_names,
                    package_name=group["package_name"],
                    model_name=group["model_name"],
                    supported_modes=tuple(group["supported_modes"]),
                    package_path=group["package_path"],
                    model_path=group["model_path"],
                )
            )
        return tuple(index)

    @classmethod
    def _get_native_source_index(cls) -> tuple[_NativeBrandIndexItem, ...]:
        cached = cls._native_source_index_cache
        cached_at = cls._native_source_index_cache_at
        now = time.monotonic()
        if (
            cached is not None
            and cached_at is not None
            and (now - cached_at) < float(cls.NATIVE_SOURCE_INDEX_TTL_SECONDS)
        ):
            return cached

        with cls._native_source_index_lock:
            now = time.monotonic()
            if (
                cls._native_source_index_cache is not None
                and cls._native_source_index_cache_at is not None
                and (now - cls._native_source_index_cache_at) < float(cls.NATIVE_SOURCE_INDEX_TTL_SECONDS)
            ):
                return cls._native_source_index_cache
            cls._native_source_index_cache = cls._build_native_source_index()
            cls._native_source_index_cache_at = now
            return cls._native_source_index_cache

    @classmethod
    def _build_legacy_catalog_groups(cls) -> list[dict]:
        groups: dict[str, list[dict]] = {}
        for root_label, root_dir in cls._scan_legacy_roots():
            patterns = [
                os.path.join(root_dir, "**", "*.npy"),
                os.path.join(root_dir, "**", "*.json"),
                os.path.join(root_dir, "**", "*.npz"),
                os.path.join(root_dir, "**", "*.msgpack"),
            ]
            all_files: list[str] = []
            for pattern in patterns:
                all_files.extend(glob.glob(pattern, recursive=True))

            for file_path in all_files:
                if cls._is_preset_sync_file(root_label, root_dir, file_path):
                    continue
                display_name = cls._display_name_for_root(root_label, root_dir, file_path)
                groups.setdefault(root_label, []).append(
                    {
                        "name": display_name,
                        "color_mode": cls.infer_color_mode(display_name, file_path),
                        "path": file_path,
                    }
                )

        legacy_groups: list[dict] = []
        for group_name in sorted(groups):
            items = sorted(groups[group_name], key=lambda item: item["name"])
            legacy_groups.append({"group_name": group_name, "items": items})
        return legacy_groups

    @classmethod
    def _build_native_brand_catalog_groups_from_index(
        cls,
        native_index: tuple[_NativeBrandIndexItem, ...],
    ) -> list[dict]:
        native_groups: list[dict] = []
        for item in native_index:
            native_groups.append(
                {
                    "brand_key": item.brand_key,
                    "material_type": item.material_type,
                    "vendor": item.vendor,
                    "display_name": item.display_name,
                    "db_options": [
                        {
                            "name": option.name,
                            "path": option.path,
                            "color_mode": option.color_mode,
                        }
                        for option in item.db_options
                    ],
                    "default_db_names": list(item.default_db_names),
                    "package_name": item.package_name,
                    "model_name": item.model_name,
                    "supported_modes": [dict(mode) for mode in item.supported_modes],
                }
            )
        return native_groups

    @classmethod
    def _build_native_brand_catalog_groups(cls) -> list[dict]:
        return cls._build_native_brand_catalog_groups_from_index(cls._get_native_source_index())

    @classmethod
    def _bundle_selection_temp_path(
        cls,
        bundle_path: str,
        selected_db_paths: list[str],
    ) -> str:
        """Create a temp copy of a native bundle with an explicit DB subset."""

        source_path = Path(bundle_path)
        suffix = source_path.suffix.lower()
        resolved_selected_db_paths = [str(Path(path).resolve()) for path in selected_db_paths if str(path)]

        if suffix == ".msgpack":
            payload = msgpack.unpackb(source_path.read_bytes(), raw=False)
            if not isinstance(payload, dict):
                raise ValueError("Invalid model package payload")
            payload["selected_db_paths"] = resolved_selected_db_paths
            payload["selected_db_names"] = [Path(path).name for path in resolved_selected_db_paths]
            fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
            os.close(fd)
            try:
                Path(temp_path).write_bytes(msgpack.packb(payload, use_bin_type=True))
                return temp_path
            except Exception:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        if suffix == ".json":
            data = json.loads(source_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Invalid stage model payload")
            data["selected_db_paths"] = resolved_selected_db_paths
            data["selected_db_names"] = [Path(path).name for path in resolved_selected_db_paths]
            fd, temp_path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
            os.close(fd)
            try:
                Path(temp_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                return temp_path
            except Exception:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        raise ValueError(f"Unsupported native bundle format: {bundle_path}")

    @staticmethod
    def _normalize_legacy_multi_names(
        lut_name: str | None,
        lut_names: list[str] | None,
    ) -> list[str]:
        normalized: list[str] = []
        for name in ([lut_name] if lut_name else []) + list(lut_names or []):
            clean_name = str(name).strip()
            if clean_name and clean_name not in normalized:
                normalized.append(clean_name)
        if not normalized:
            raise ValueError("legacy_multi requires lut_names or lut_name")
        return normalized

    @classmethod
    def _legacy_multi_compatibility_signature(cls, metadata: LUTMetadata) -> dict[str, Any]:
        """Return the runtime compatibility shape for legacy_multi LUTs.

        返回经典多选 LUT 的运行时兼容形状。

        The signature intentionally excludes color_mode and palette contents:
        multi-select combines 2/4/6/8-color legacy LUTs into a wider runtime
        palette, so those fields are expected to differ across selected LUTs.
        """

        return {
            "max_color_layers": int(metadata.max_color_layers),
            "layer_height_mm": round(float(metadata.layer_height_mm), 6),
            "line_width_mm": round(float(metadata.line_width_mm), 6),
            "base_layers": int(metadata.base_layers),
            "base_channel_idx": int(metadata.base_channel_idx),
            "layer_order": str(metadata.layer_order),
        }

    @classmethod
    def legacy_multi_compatibility_key(cls, metadata: LUTMetadata) -> str:
        """Return a stable key for legacy_multi-compatible LUT metadata.
        返回用于 legacy_multi 兼容分组的稳定键。
        """

        signature = cls._legacy_multi_compatibility_signature(metadata)
        payload = json.dumps(
            signature,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return payload

    @staticmethod
    def _legacy_standard_stacks_for_count(color_count: int) -> np.ndarray | None:
        if 30 <= color_count <= 36:
            rows = []
            for index in range(color_count):
                temp = index % 32
                digits = []
                for _ in range(5):
                    digits.append(temp % 2)
                    temp //= 2
                rows.append(convert_recipe_between_orders(digits, "Bottom2Top", "Top2Bottom"))
            return np.asarray(rows, dtype=np.int32)

        if color_count == 1024:
            rows = []
            for index in range(color_count):
                temp = index
                digits = []
                for _ in range(5):
                    digits.append(temp % 4)
                    temp //= 4
                rows.append(convert_recipe_between_orders(digits, "Bottom2Top", "Top2Bottom"))
            return np.asarray(rows, dtype=np.int32)

        if color_count == 1296:
            from core.calibration import get_top_1296_colors

            rows = [
                convert_recipe_between_orders(row, "Bottom2Top", "Top2Bottom")
                for row in get_top_1296_colors()
            ]
            return np.asarray(rows[:color_count], dtype=np.int32)

        if color_count == 2468:
            from core.calibration import select_extended_1444_colors

            base_5layer = [
                tuple(
                    convert_recipe_between_orders(
                        [index // 4**pos % 4 for pos in range(5)],
                        "Bottom2Top",
                        "Top2Bottom",
                    )
                )
                for index in range(1024)
            ]
            rows: list[tuple[int, ...]] = [(-1,) + row for row in base_5layer]
            rows.extend(tuple(row) for row in select_extended_1444_colors(base_5layer))
            return np.asarray(rows[:color_count], dtype=np.int32)

        if color_count == 2738:
            from config import get_asset_path

            stacks_path = get_asset_path("smart_8color_stacks.npy")
            rows = [
                convert_recipe_between_orders(row, "Bottom2Top", "Top2Bottom")
                for row in np.load(stacks_path).tolist()
            ]
            return np.asarray(rows[:color_count], dtype=np.int32)

        return None

    @classmethod
    def _ensure_legacy_runtime_stacks(
        cls,
        rgb: np.ndarray,
        stacks: np.ndarray | None,
        lut_name: str,
    ) -> np.ndarray:
        measured_colors = rgb.reshape(-1, 3)
        if (
            isinstance(stacks, np.ndarray)
            and stacks.ndim == 2
            and stacks.shape[0] == measured_colors.shape[0]
            and stacks.shape[1] > 0
        ):
            runtime_stacks = stacks.astype(np.int32, copy=False)
            if not np.all(runtime_stacks < 0):
                return runtime_stacks

        reconstructed = cls._legacy_standard_stacks_for_count(int(measured_colors.shape[0]))
        if reconstructed is not None and reconstructed.shape[0] == measured_colors.shape[0]:
            return reconstructed

        raise ValueError(f"Legacy LUT missing recipe stacks: {lut_name}")

    @classmethod
    def _canonicalize_legacy_multi_color_name(cls, color: object) -> str:
        text = str(color or "").strip()
        parenthetical = re.findall(r"\(([^()]*)\)", text)
        if parenthetical:
            text = parenthetical[-1].strip()
        else:
            text = re.sub(r"^\s*slot\s*\d+\s*[:：\-_\s]*", "", text, flags=re.IGNORECASE).strip()

        normalized = re.sub(r"[^a-z]+", "", text.lower())
        return cls._LEGACY_MULTI_COLOR_ALIASES.get(normalized, text)

    @classmethod
    def _legacy_multi_slot_label(cls, color: str) -> str:
        slot_index = cls._LEGACY_MULTI_STANDARD_SLOT_ORDER.index(color) + 1
        return f"Slot {slot_index} ({color})"

    @classmethod
    def _legacy_palette_entry_key(cls, entry: PaletteEntry) -> str:
        color = cls._canonicalize_legacy_multi_color_name(entry.color)
        return normalize_channel_key(build_channel_key(color, entry.material))

    @classmethod
    def _canonicalize_legacy_multi_palette_entry(cls, entry: PaletteEntry) -> PaletteEntry:
        cloned = copy.deepcopy(entry)
        color = cls._canonicalize_legacy_multi_color_name(cloned.color)
        if color in cls._LEGACY_MULTI_STANDARD_SLOT_ORDER:
            cloned.color = cls._legacy_multi_slot_label(color)
            cloned.color_name = color
        return cloned

    @classmethod
    def _ordered_legacy_multi_palette(
        cls,
        entries_by_key: dict[str, PaletteEntry],
    ) -> list[PaletteEntry]:
        standard_order = {
            color: index
            for index, color in enumerate(cls._LEGACY_MULTI_STANDARD_SLOT_ORDER)
        }

        def sort_key(item: tuple[str, PaletteEntry]) -> tuple[int, int, str]:
            key, entry = item
            color = cls._canonicalize_legacy_multi_color_name(entry.color)
            if color in standard_order:
                return (0, standard_order[color], normalize_channel_key(str(entry.material)))
            return (1, len(standard_order), key)

        palette = [entry for _key, entry in sorted(entries_by_key.items(), key=sort_key)]
        # Metadata serializes the palette by display name. Equal color labels
        # from different materials must not overwrite each other on disk.
        counts = Counter(entry.color for entry in palette)
        used_names = set(counts)
        for entry in palette:
            if counts[entry.color] == 1:
                continue
            color = cls._canonicalize_legacy_multi_color_name(entry.color)
            label = f"{entry.material} ({color})"
            unique_label = label
            suffix = 2
            while unique_label in used_names:
                unique_label = f"{label} [{suffix}]"
                suffix += 1
            entry.color = unique_label
            used_names.add(unique_label)
        return palette

    @staticmethod
    def _legacy_print_settings_signature(metadata: LUTMetadata) -> dict[str, Any]:
        return {
            "max_color_layers": int(metadata.max_color_layers),
            "layer_height_mm": round(float(metadata.layer_height_mm), 6),
            "line_width_mm": round(float(metadata.line_width_mm), 6),
            "base_layers": int(metadata.base_layers),
            "base_channel_idx": int(metadata.base_channel_idx),
            "layer_order": str(metadata.layer_order),
        }

    @classmethod
    def _remap_legacy_stacks_to_palette(
        cls,
        stacks: np.ndarray,
        source_palette: list[PaletteEntry],
        global_palette_index: dict[str, int],
        lut_name: str,
    ) -> np.ndarray:
        remapped = np.full(stacks.shape, -1, dtype=np.int32)
        local_to_global: dict[int, int] = {}
        for local_idx, entry in enumerate(source_palette):
            key = cls._legacy_palette_entry_key(entry)
            if key in global_palette_index:
                local_to_global[local_idx] = global_palette_index[key]

        used_indices = {
            int(value)
            for value in np.unique(stacks)
            if int(value) >= 0
        }
        missing_indices = sorted(
            index for index in used_indices if index not in local_to_global
        )
        if missing_indices:
            raise ValueError(
                f"Legacy LUT palette cannot map recipe channels for {lut_name}: "
                + ", ".join(str(index) for index in missing_indices)
            )

        for local_idx, global_idx in local_to_global.items():
            remapped[stacks == local_idx] = global_idx
        return remapped

    @classmethod
    def _legacy_multi_runtime_path(
        cls,
        selected_names: list[str],
        selected_paths: list[str],
    ) -> str:
        rgb_parts: list[np.ndarray] = []
        stack_parts: list[np.ndarray] = []
        source_references: list[dict[str, str]] = []
        seen_recipes: set[tuple[int, ...]] = set()
        baseline_print_signature: dict[str, Any] | None = None
        baseline_metadata: LUTMetadata | None = None
        global_palette_entries: dict[str, PaletteEntry] = {}
        loaded_sources: list[tuple[str, str, np.ndarray, np.ndarray, LUTMetadata]] = []
        stack_width: int | None = None

        for lut_name, lut_path in zip(selected_names, selected_paths):
            rgb, stacks, metadata = cls.load_lut_with_metadata(lut_path)
            measured_colors = rgb.reshape(-1, 3)
            if measured_colors.size == 0:
                raise ValueError(f"Legacy LUT has no lookup entries: {lut_name}")

            print_signature = cls._legacy_print_settings_signature(metadata)
            if baseline_print_signature is None:
                baseline_print_signature = print_signature
                baseline_metadata = copy.deepcopy(metadata)
            elif print_signature != baseline_print_signature:
                raise ValueError(f"Incompatible legacy LUT print settings: {lut_name}")

            runtime_stacks = cls._ensure_legacy_runtime_stacks(measured_colors, stacks, lut_name)
            if stack_width is None:
                stack_width = int(runtime_stacks.shape[1])
            elif int(runtime_stacks.shape[1]) != stack_width:
                raise ValueError(f"Incompatible legacy LUT recipe layer count: {lut_name}")

            for entry in metadata.palette:
                key = cls._legacy_palette_entry_key(entry)
                if key and key not in global_palette_entries:
                    global_palette_entries[key] = cls._canonicalize_legacy_multi_palette_entry(entry)
            loaded_sources.append((lut_name, lut_path, measured_colors, runtime_stacks, metadata))

        if baseline_metadata is None or not loaded_sources or stack_width is None:
            raise ValueError("legacy_multi requires at least one usable LUT")

        global_palette = cls._ordered_legacy_multi_palette(global_palette_entries)
        global_palette_index = {
            cls._legacy_palette_entry_key(entry): index
            for index, entry in enumerate(global_palette)
        }

        for lut_name, lut_path, measured_colors, runtime_stacks, _metadata in loaded_sources:
            remapped_stacks = cls._remap_legacy_stacks_to_palette(
                runtime_stacks,
                _metadata.palette,
                global_palette_index,
                lut_name,
            )
            kept_rgb: list[np.ndarray] = []
            kept_stacks: list[np.ndarray] = []
            for row_rgb, row_stack in zip(measured_colors, remapped_stacks):
                recipe_key = tuple(int(value) for value in row_stack)
                if recipe_key in seen_recipes:
                    continue
                seen_recipes.add(recipe_key)
                kept_rgb.append(row_rgb)
                kept_stacks.append(row_stack)
            if kept_rgb:
                rgb_parts.append(np.asarray(kept_rgb, dtype=np.uint8).reshape(-1, 3))
                stack_parts.append(np.asarray(kept_stacks, dtype=np.int32))
            source_references.append(
                {
                    "name": lut_name,
                    "path": str(Path(lut_path).resolve()),
                }
            )

        if not rgb_parts:
            raise ValueError("legacy_multi requires at least one usable LUT")

        runtime_rgb = np.concatenate(rgb_parts, axis=0)
        runtime_stacks = np.concatenate(stack_parts, axis=0)
        metadata = baseline_metadata
        base_index = int(metadata.base_channel_idx)
        if not 0 <= base_index < len(metadata.palette):
            raise ValueError(f"Legacy LUT base channel is outside its palette: {selected_names[0]}")
        base_key = cls._legacy_palette_entry_key(metadata.palette[base_index])
        metadata.base_channel_idx = global_palette_index[base_key]
        metadata.palette = global_palette
        metadata.color_mode = "Merged"
        metadata.max_color_layers = int(stack_width)
        metadata.schema_version = metadata.schema_version or "1.0"
        metadata.capabilities = sorted(
            (set(metadata.capabilities) | {"legacy_lookup"})
            - {"predictive_match", "predictive_model"}
        )
        for key in (
            "runtime_package",
            "stage_model",
            "native_model_package_path",
            "native_stage_model_path",
        ):
            metadata.extensions.pop(key, None)
        metadata.extensions["source_kind"] = "legacy_multi"
        metadata.extensions["selected_lut_names"] = list(selected_names)
        metadata.extensions.pop("source_fingerprints", None)
        metadata.extensions["source_references"] = source_references

        fd, temp_path = tempfile.mkstemp(suffix=".npz", dir=TEMP_DIR)
        os.close(fd)
        try:
            cls.save_npz_with_metadata(temp_path, runtime_rgb, runtime_stacks, metadata)
            return temp_path
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    @classmethod
    def get_source_catalog(cls) -> dict[str, list[dict]]:
        """Return legacy and native source catalog groupings.
        返回传统源与原生源的分组目录。
        """

        now = time.monotonic()
        with cls._source_catalog_cache_lock:
            if (
                cls._source_catalog_cache is not None
                and cls._source_catalog_cache_checked_at is not None
                and now - cls._source_catalog_cache_checked_at <= float(cls.SOURCE_CATALOG_SIGNATURE_TTL_SECONDS)
            ):
                return copy.deepcopy(cls._source_catalog_cache)

        native_index = cls._get_native_source_index()
        catalog = {
            "legacy_groups": cls._build_legacy_catalog_groups(),
            "native_brand_groups": cls._build_native_brand_catalog_groups_from_index(native_index),
        }
        with cls._source_catalog_cache_lock:
            cls._source_catalog_cache = copy.deepcopy(catalog)
            cls._source_catalog_cache_checked_at = now
        return catalog

    @classmethod
    def resolve_source_selection(
        cls,
        *,
        source_kind: str,
        lut_name: str | None = None,
        lut_names: list[str] | None = None,
        material_type: str | None = None,
        vendor: str | None = None,
        db_names: list[str] | None = None,
    ) -> tuple[str, str]:
        """Resolve a source selection to a concrete LUT loading path and display name."""

        normalized_kind = str(source_kind or "legacy_single")
        if normalized_kind == "legacy_single":
            if not lut_name:
                raise ValueError("legacy_single requires lut_name")
            lut_path = cls.get_lut_path(lut_name)
            if lut_path is None:
                raise ValueError(f"LUT not found: {lut_name}")
            return lut_path, lut_name

        if normalized_kind == "legacy_multi":
            selected_names = cls._normalize_legacy_multi_names(lut_name, lut_names)
            selected_paths: list[str] = []
            for selected_name in selected_names:
                lut_path = cls.get_lut_path(selected_name)
                if lut_path is None:
                    raise ValueError(f"LUT not found: {selected_name}")
                selected_paths.append(lut_path)
            runtime_path = cls._legacy_multi_runtime_path(selected_names, selected_paths)
            return runtime_path, selected_names[0]

        if normalized_kind != "native_bundle":
            raise ValueError(f"Unsupported source_kind: {source_kind}")

        if not material_type or not vendor:
            raise ValueError("native_bundle requires material_type and vendor")

        native_groups = cls._get_native_source_index()
        selected = next(
            (
                group
                for group in native_groups
                if group.vendor == vendor and group.material_type == material_type
            ),
            None,
        )
        if selected is None:
            raise ValueError(f"Native brand not found: {vendor}/{material_type}")

        allowed_db_names = {item.name for item in selected.db_options}
        requested_db_names = list(dict.fromkeys(db_names or [])) or list(selected.default_db_names)
        invalid_db_names = [name for name in requested_db_names if name not in allowed_db_names]
        if invalid_db_names:
            raise ValueError(
                "Selected db_names do not belong to the requested native brand: "
                + ", ".join(invalid_db_names)
            )

        selected_db_paths = [
            option.path
            for option in selected.db_options
            if option.name in requested_db_names
        ]
        bundle_path = selected.package_path or selected.model_path
        if bundle_path and os.path.exists(bundle_path):
            temp_bundle_path = cls._bundle_selection_temp_path(bundle_path, selected_db_paths)
            display_name = selected.display_name
            return temp_bundle_path, display_name

        if requested_db_names:
            for option in selected.db_options:
                if option.name == requested_db_names[0]:
                    return option.path, option.name

        raise ValueError(f"No loadable source found for native brand: {vendor}/{material_type}")

    
    @classmethod
    def save_uploaded_lut(cls, uploaded_file, custom_name=None):
        """
        Save user-uploaded LUT file to preset folder
        
        Args:
            uploaded_file: Object with the source file path in its .name attribute
            custom_name: Custom filename (optional)
        
        Returns:
            tuple: (success_flag, message, new_choice_list)
        """
        if uploaded_file is None:
            return False, "[ERROR] No file selected", cls.get_lut_choices()
        
        try:
            # Ensure preset folder exists
            custom_dir = str(cls.custom_lut_dir())
            os.makedirs(custom_dir, exist_ok=True)
            
            # Get original filename and extension
            original_path = Path(uploaded_file.name)
            original_name = original_path.stem
            file_extension = original_path.suffix  # .npy
            
            # Validate file extension
            if file_extension not in ('.npy', '.json', '.npz', '.msgpack'):
                return False, f"[ERROR] Invalid file type: {file_extension}. Only .npy, .json, .npz and .msgpack are supported.", cls.get_lut_choices()
            
            # Use custom name or original name
            if custom_name and custom_name.strip():
                final_name = custom_name.strip()
            else:
                final_name = original_name
            
            # Ensure filename is safe
            final_name = "".join(c for c in final_name if c.isalnum() or c in (' ', '-', '_', '中', '文'))
            final_name = final_name.strip()
            
            if not final_name:
                final_name = "custom_lut"
            
            # Auto-convert .npy to Keyed JSON
            if file_extension == '.npy':
                dest_extension = '.json'
            else:
                dest_extension = file_extension
            
            # Build target path with correct extension
            dest_path = os.path.join(custom_dir, f"{final_name}{dest_extension}")
            
            # If file exists, add numeric suffix
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(custom_dir, f"{final_name}_{counter}{dest_extension}")
                counter += 1
            
            if file_extension == '.npy':
                # Convert .npy to Keyed JSON
                try:
                    rgb = np.load(uploaded_file.name)
                    if rgb.ndim == 3:
                        rgb = rgb.reshape(-1, 3)
                    elif rgb.ndim == 1:
                        rgb = rgb.reshape(-1, 3)
                    metadata = cls.infer_default_metadata(final_name, uploaded_file.name, len(rgb))
                    stacks = np.zeros((len(rgb), 0), dtype=np.int32)
                    cls.save_keyed_json(dest_path, rgb, stacks, metadata)
                except Exception as e:
                    return False, f"[ERROR] Failed to convert .npy to JSON: {e}", cls.get_lut_choices()
            else:
                # Copy file directly for .json, .npz and .msgpack
                shutil.copy2(uploaded_file.name, dest_path)
            
            # Build display name
            display_name = f"Custom - {Path(dest_path).stem}"
            
            _log.info(
                "Saved uploaded LUT",
                extra={
                    "event": "lut_saved",
                    "path": dest_path,
                    "display_name": display_name,
                },
            )
            
            return True, f"[OK] LUT saved: {display_name}\nPlease select from dropdown to use", cls.get_lut_choices()
            
        except Exception as e:
            _log.warning(
                "Error saving LUT",
                extra={
                    "event": "lut_save_failed",
                    "path": dest_path if "dest_path" in locals() else str(getattr(uploaded_file, "name", "") or ""),
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            return False, f"[ERROR] Save failed: {e}", cls.get_lut_choices()
    
    @classmethod
    def delete_lut(cls, display_name):
        """
        Delete specified LUT preset
        
        Args:
            display_name: Display name
        
        Returns:
            tuple: (success_flag, message, new_choice_list)
        """
        file_path = cls.get_lut_path(display_name)
        
        if not file_path:
            return False, "[ERROR] File not found", cls.get_lut_choices()
        
        # Only allow deleting files inside the configured Custom root.
        try:
            Path(file_path).resolve().relative_to(cls.custom_lut_dir().resolve())
        except (OSError, ValueError):
            return False, "[ERROR] Can only delete custom LUTs", cls.get_lut_choices()
        
        try:
            os.remove(file_path)
            _log.info(
                "Deleted LUT",
                extra={
                    "event": "lut_deleted",
                    "path": file_path,
                    "display_name": display_name,
                },
            )
            return True, f"[OK] Deleted: {display_name}", cls.get_lut_choices()
        except Exception as e:
            _log.warning(
                "Error deleting LUT",
                extra={
                    "event": "lut_delete_failed",
                    "path": file_path,
                    "display_name": display_name,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            return False, f"[ERROR] Delete failed: {e}", cls.get_lut_choices()

    # ------------------------------------------------------------------
    # Metadata-aware loading / saving (Task 4)
    # ------------------------------------------------------------------

    @classmethod
    def infer_default_metadata(cls, display_name: str, file_path: str,
                               color_count: int,
                               color_mode: str | None = None) -> LUTMetadata:
        """Infer default LUTMetadata from filename and color count.
        根据文件名和颜色数量推断默认元数据。

        Args:
            display_name (str): LUT display name. (LUT 显示名称)
            file_path (str): LUT file path. (LUT 文件路径)
            color_count (int): Number of colors in the LUT. (LUT 中的颜色数量)
            color_mode (str | None): Optional color mode override; when provided,
                takes priority over inference. (可选颜色模式覆盖；传入时优先使用)

        Returns:
            LUTMetadata: Inferred default metadata. (推断的默认元数据)
        """
        mode = (
            cls._canonicalize_legacy_color_mode(color_mode)
            if color_mode
            else cls.infer_color_mode(display_name, file_path)
        )
        color_conf = ColorSystem.get(mode)
        slots = color_conf.get("slots", [])
        combined_name = f"{display_name} {file_path}".casefold()
        if (
            color_count == 1296
            and mode == "6-Color (RYBWGK 1296)"
            and ("biqu" in combined_name or "必趣" in combined_name)
        ):
            slots = ["White", "Blue", "Red", "Green", "Yellow", "Black"]

        palette = [
            PaletteEntry(color=name, material="PLA Basic")
            for name in slots
        ]

        return LUTMetadata(
            palette=palette,
            color_mode=mode,
            max_color_layers=PrinterConfig.COLOR_LAYERS,
            layer_height_mm=PrinterConfig.LAYER_HEIGHT,
            line_width_mm=PrinterConfig.NOZZLE_WIDTH,
            base_layers=10,
            base_channel_idx=0,
            layer_order="Top2Bottom",
        )

    @classmethod
    def load_lut_with_metadata(cls, file_path: str) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        """Load LUT file and return (rgb, stacks_or_None, metadata).
        统一加载 LUT 文件，返回 (rgb, stacks_or_None, metadata)。

        Supports .npy, .json, .npz, and native reference .msgpack formats.
        支持 .npy、.json、.npz 以及原生参考 .msgpack 格式。

        Args:
            file_path (str): Path to the LUT file. (LUT 文件路径)

        Returns:
            tuple: (rgb ndarray, stacks ndarray or None, LUTMetadata).
        """
        ext = os.path.splitext(file_path)[1].lower()
        display_name = Path(file_path).stem

        # ---- .npy format ----
        if ext == ".npy":
            try:
                rgb = np.load(file_path)
            except Exception as e:
                _log.warning(
                    "Failed to load NPY LUT file",
                    extra={
                        "event": "lut_npy_load_failed",
                        "path": file_path,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
                rgb = np.zeros((0, 3), dtype=np.uint8)
            color_count = int(rgb.reshape(-1, 3).shape[0]) if rgb.size else 0
            metadata = cls.infer_default_metadata(display_name, file_path, color_count)
            return rgb, None, metadata

        # ---- .json (Keyed JSON) format ----
        if ext == ".json":
            return cls._load_keyed_json(file_path, display_name)

        # ---- .npz format ----
        if ext == ".npz":
            return cls._load_npz(file_path, display_name)

        # ---- native model package (.msgpack) ----
        if ext == ".msgpack":
            try:
                payload = msgpack.unpackb(Path(file_path).read_bytes(), raw=False)
            except Exception as e:
                _log.warning(
                    "Failed to parse msgpack LUT file",
                    extra={
                        "event": "lut_msgpack_parse_failed",
                        "path": file_path,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
                rgb = np.zeros((0, 3), dtype=np.uint8)
                metadata = cls.infer_default_metadata(display_name, file_path, 0)
                return rgb, None, metadata
            if cls._is_model_package_payload(payload):
                return cls._load_model_package(file_path, display_name)
            return cls._load_keyed_payload(payload, display_name, file_path)

        # Unsupported format – return empty defaults
        _log.warning(
            "Unsupported LUT format",
            extra={
                "event": "lut_unsupported_format",
                "path": file_path,
                "extension": ext,
            },
        )
        rgb = np.zeros((0, 3), dtype=np.uint8)
        metadata = cls.infer_default_metadata(display_name, file_path, 0)
        return rgb, None, metadata

    # ---- private helpers ----

    @classmethod
    def _load_keyed_json(cls, file_path: str, display_name: str) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        """Load a Keyed JSON LUT file.
        加载 Keyed JSON 格式的 LUT 文件。支持新对象格式和旧数组格式的 palette/recipe。
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            _log.warning(
                "Failed to parse JSON LUT file",
                extra={
                    "event": "lut_json_parse_failed",
                    "path": file_path,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            rgb = np.zeros((0, 3), dtype=np.uint8)
            metadata = cls.infer_default_metadata(display_name, file_path, 0)
            return rgb, None, metadata
        return cls._load_keyed_payload(data, display_name, file_path)

    @classmethod
    def _load_keyed_payload(
        cls,
        data: Any,
        display_name: str,
        file_path: str,
        *,
        skip_malformed_recipes: bool = False,
    ) -> tuple[np.ndarray, np.ndarray | None, 'LUTMetadata']:
        """Load a keyed LUT payload from JSON or msgpack content.

        从 JSON 或 msgpack 内容加载 keyed LUT 载荷。

        Args:
            data: Parsed JSON/msgpack object (dict).
                (解析后的 JSON/msgpack 对象。)
            display_name: Human-readable LUT name. (人类可读 LUT 名称。)
            file_path: Source file path for diagnostic logging.
                (用于诊断日志的源文件路径。)
            skip_malformed_recipes: When True (strict mode), rows whose recipe
                is malformed (non-list/tuple payload, OR contains a member that
                is neither a string nor int-castable) are dropped entirely
                instead of being kept with an all-(-1) sentinel stack. The
                lenient default (False) preserves the contract relied on by
                ``api/routers/five_color.py``: the row stays so
                ``/api/five-color/match-color`` can return the row index with
                ``reason="recipe_unavailable"``. Strict mode is used by
                ``core/lut_details/parser.py`` where ``parsed.rgb`` /
                ``parsed.lab`` must only reflect rows with usable recipes.
                (True 严格模式下 recipe 不合法的行会被整行丢弃; 默认 False 宽松
                模式保留行+sentinel, 供 five-color match-color API 返回
                recipe_unavailable。)

        Returns:
            (rgb, stacks, metadata): rgb is (N, 3) uint8; stacks is (N, L)
            int32 or None when no recipe rows exist; metadata is the populated
            ``LUTMetadata`` instance.
        """

        native_ctx = discover_native_reference_context(file_path, data)
        if native_ctx is not None:
            if looks_like_reference_colordb(data):
                return cls._load_native_colordb_json(file_path, display_name, data, native_ctx)
            if looks_like_reference_stage_model(data):
                return cls._load_native_stage_model_json(file_path, display_name, data, native_ctx)
            if looks_like_reference_recipe_set(data):
                return cls._load_native_recipe_json(file_path, display_name, data, native_ctx)

        # ── 兼容顶层为数组的旧格式 ──────────────────────────────────
        # 格式: [{recipe: [...], rgb: [r,g,b], hex: "#...", source: "..."}, ...]
        if isinstance(data, list):
            return cls._load_keyed_json_flat_list(data, display_name, file_path)

        metadata = LUTMetadata.from_dict(data)
        metadata.color_mode = cls._canonicalize_legacy_color_mode(metadata.color_mode, data)

        # If palette is empty, infer defaults
        if not metadata.palette:
            _log.warning(
                "No valid LUT palette; inferring defaults",
                extra={
                    "event": "lut_palette_missing",
                    "path": file_path,
                    "display_name": display_name,
                },
            )
            default_meta = cls.infer_default_metadata(display_name, file_path, 0)
            metadata.palette = default_meta.palette

        # Build name→index mapping for recipe resolution
        name_to_idx: dict[str, int] = {
            e.color: i for i, e in enumerate(metadata.palette)
        }

        # Parse entries → rgb + stacks
        entries = data.get("entries", [])
        rgb_list: list[list[int]] = []
        stacks_list: list[list[int]] = []
        stack_recipe_widths: list[int] = []

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # Prefer stored RGB for exact roundtrip; fall back to Lab→RGB
            rgb_val = entry.get("rgb")
            hex_val = entry.get("hex")
            lab = entry.get("lab")
            row_rgb: list[int] | None = None
            if rgb_val and len(rgb_val) == 3:
                try:
                    r = max(0, min(255, int(rgb_val[0])))
                    g = max(0, min(255, int(rgb_val[1])))
                    b = max(0, min(255, int(rgb_val[2])))
                except (TypeError, ValueError) as e:
                    _log.debug(
                        "RGB row conversion failed",
                        extra={
                            "event": "lut_rgb_row_conversion_failed",
                            "path": file_path,
                            "rgb_value": rgb_val,
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                        },
                    )
                    continue
                row_rgb = [r, g, b]
                
                # Optional: Validate hex consistency with RGB
                if hex_val:
                    expected_hex = f"#{r:02X}{g:02X}{b:02X}"
                    if hex_val.upper() != expected_hex:
                        _log.debug(
                            "LUT hex value does not match RGB",
                            extra={
                                "event": "lut_hex_mismatch",
                                "path": file_path,
                                "rgb_value": rgb_val,
                                "expected_hex": expected_hex,
                                "stored_hex": hex_val,
                            },
                        )
                        
            elif lab and len(lab) == 3:
                try:
                    from colormath.color_objects import LabColor, sRGBColor
                    from colormath.color_conversions import convert_color
                    lab_values = np.asarray([float(lab[0]), float(lab[1]), float(lab[2])], dtype=np.float32)
                    if not np.isfinite(lab_values).all():
                        raise ValueError("non-finite lab")
                    lab_color = LabColor(float(lab_values[0]), float(lab_values[1]), float(lab_values[2]))
                    srgb = convert_color(lab_color, sRGBColor)
                    r = max(0, min(255, int(round(srgb.clamped_rgb_r * 255))))
                    g = max(0, min(255, int(round(srgb.clamped_rgb_g * 255))))
                    b = max(0, min(255, int(round(srgb.clamped_rgb_b * 255))))
                    row_rgb = [r, g, b]
                except Exception as e:
                    _log.debug(
                        "Lab to RGB conversion failed",
                        extra={
                            "event": "lut_lab_rgb_conversion_failed",
                            "path": file_path,
                            "lab_value": lab,
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                        },
                    )
                    continue
            else:
                continue

            # Recipe: resolve color names to indices, support both formats.
            # In strict mode (skip_malformed_recipes=True), drop rows with
            # non-list payloads or non-castable members entirely so downstream
            # parsers (core/lut_details/parser.py) only see usable rows.
            recipe_raw = entry.get("recipe", [])
            if not isinstance(recipe_raw, (list, tuple)):
                source_recipe_width = 0
                if skip_malformed_recipes:
                    _log.debug(
                        "Skipping row with non-list recipe payload (strict)",
                        extra={
                            "event": "lut_recipe_payload_invalid",
                            "path": file_path,
                            "recipe_value": recipe_raw,
                        },
                    )
                    continue
                _log.debug(
                    "Invalid LUT recipe payload marked unavailable",
                    extra={
                        "event": "lut_recipe_payload_invalid",
                        "path": file_path,
                        "recipe_value": recipe_raw,
                    },
                )
                recipe_indices = [-1, -1, -1, -1, -1]
            else:
                source_recipe_width = len(recipe_raw)
                if skip_malformed_recipes:
                    has_invalid_member = False
                    for member in recipe_raw:
                        if isinstance(member, str):
                            continue
                        try:
                            int(member)
                        except (TypeError, ValueError):
                            has_invalid_member = True
                            break
                    if has_invalid_member:
                        _log.debug(
                            "Skipping row with non-castable recipe member (strict)",
                            extra={
                                "event": "lut_recipe_member_invalid",
                                "path": file_path,
                                "recipe_value": recipe_raw,
                            },
                        )
                        continue
                recipe_indices = [
                    cls._resolve_recipe_member(value, name_to_idx, file_path)
                    for value in recipe_raw
                ]
            recipe_indices = cls._normalize_resolved_layer_recipe(
                recipe_indices,
                max_color_layers=getattr(metadata, "max_color_layers", 5),
            )
            rgb_list.append(row_rgb)
            stacks_list.append(recipe_indices)
            stack_recipe_widths.append(source_recipe_width)

        if rgb_list:
            rgb = np.array(rgb_list, dtype=np.uint8)
        else:
            rgb = np.zeros((0, 3), dtype=np.uint8)

        if stacks_list:
            max_len = max((len(row) for row in stacks_list), default=0)
            normalized_stacks = [
                row + ([-1] * (max_len - len(row)))
                for row in stacks_list
            ]
            stacks = np.array(normalized_stacks, dtype=np.int32)
        else:
            stacks = None
        if _looks_like_missing_keyed_stacks(stacks, rgb.reshape(-1, 3).shape[0]):
            stacks = None
        if stacks is not None and len(stack_recipe_widths) == len(stacks_list):
            metadata.extensions["stack_recipe_widths"] = stack_recipe_widths

        return rgb, stacks, metadata

    @staticmethod
    def _parse_integer_recipe_value(value: Any) -> int | None:
        if isinstance(value, (bool, np.bool_)):
            return None
        if isinstance(value, str):
            stripped_value = value.strip()
            if not re.fullmatch(r"[+-]?\d+", stripped_value):
                return None
            try:
                numeric_value = int(stripped_value)
            except ValueError:
                return None
            if _INT32_MIN <= numeric_value <= _INT32_MAX:
                return numeric_value
            return None
        if isinstance(value, (int, np.integer)):
            numeric_value = int(value)
            if _INT32_MIN <= numeric_value <= _INT32_MAX:
                return numeric_value
        return None

    @staticmethod
    def _is_numeric_recipe_literal(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        try:
            float(value)
        except ValueError:
            return False
        return True

    @classmethod
    def _resolve_recipe_member(
        cls,
        value: Any,
        name_to_idx: dict[str, int],
        file_path: str,
    ) -> int:
        numeric_index = cls._parse_integer_recipe_value(value)
        if numeric_index is not None:
            return numeric_index

        if isinstance(value, str):
            if cls._is_numeric_recipe_literal(value):
                _log.debug(
                    "Invalid numeric LUT recipe string",
                    extra={
                        "event": "lut_recipe_numeric_string_invalid",
                        "path": file_path,
                        "recipe_member": value,
                    },
                )
                return -1
            if value == "Air":
                return -1
            if value in name_to_idx:
                return name_to_idx[value]
            _log.debug(
                "Unknown LUT recipe color name",
                extra={
                    "event": "lut_recipe_color_unknown",
                    "path": file_path,
                    "color_name": value,
                },
            )
            return -1

        _log.debug(
            "Invalid LUT recipe member skipped",
            extra={
                "event": "lut_recipe_member_invalid",
                "path": file_path,
                "recipe_member": value,
                "error_type": type(value).__name__,
                "error_message": "member is not an integer recipe index or color name",
            },
        )
        return -1

    @staticmethod
    def _normalize_resolved_five_layer_recipe(recipe_indices: list[int]) -> list[int]:
        return LUTManager._normalize_resolved_recipe_width(recipe_indices, 5)

    @staticmethod
    def _normalize_resolved_recipe_width(recipe_indices: list[int], expected_width: int) -> list[int]:
        try:
            width = int(expected_width)
        except (TypeError, ValueError):
            width = 5
        if width <= 0:
            width = 5
        if len(recipe_indices) == width:
            return recipe_indices
        return [-1] * width

    @staticmethod
    def _normalize_resolved_layer_recipe(
        recipe_indices: list[int],
        *,
        max_color_layers: int = PrinterConfig.COLOR_LAYERS,
    ) -> list[int]:
        try:
            layer_count = int(max_color_layers)
        except (TypeError, ValueError):
            layer_count = PrinterConfig.COLOR_LAYERS
        supported_widths = (5, 6) if layer_count >= 6 else (5,)
        if len(recipe_indices) in supported_widths:
            return recipe_indices
        return LUTManager._normalize_resolved_recipe_width(recipe_indices, layer_count)

    @staticmethod
    def _infer_native_colordb_recipe_layer_count(
        data: dict[str, Any],
        entries: list[dict[str, Any]],
    ) -> int:
        try:
            layer_count = int(data.get("max_color_layers", 0))
        except (TypeError, ValueError):
            layer_count = 0
        if layer_count > 0:
            return layer_count
        for entry in entries:
            recipe_raw = entry.get("recipe", [])
            if isinstance(recipe_raw, (list, tuple)) and recipe_raw:
                return len(recipe_raw)
        return 5

    @staticmethod
    def _normalize_native_colordb_recipe_width(
        recipe_indices: list[int],
        target_layer_count: int,
    ) -> list[int]:
        if len(recipe_indices) >= target_layer_count:
            return recipe_indices
        return recipe_indices + ([-1] * (target_layer_count - len(recipe_indices)))

    @staticmethod
    def _infer_color_count_from_resolved_recipes(
        stacks_list: list[list[int]],
    ) -> int | None:
        max_index = -1
        for recipe in stacks_list:
            if len(recipe) not in (5, 6) or any(index < 0 for index in recipe):
                continue
            if any(index >= 8 for index in recipe):
                continue
            max_index = max(max_index, max(recipe))
        inferred_count = max_index + 1
        if 1 <= inferred_count <= 8:
            return inferred_count
        return None

    @classmethod
    def load_native_bundle_exact_lookup(
        cls,
        metadata: LUTMetadata,
        *,
        color_layers: int,
        layer_height_mm: float,
        layer_order: str | None = None,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Load exact lookup RGB/stacks from native ColorDB bundle members.

        Exact same-mode DBs are preferred. When none exist, selected DB entries
        remain searchable and their recipes are converted to the requested
        layer-count / layer-height / layer-order target semantics.
        """
        db_paths = metadata.extensions.get("native_db_paths")
        if not isinstance(db_paths, list) or not db_paths:
            return None

        channel_keys = metadata.extensions.get("native_channel_keys")
        selected_db_paths = select_native_db_paths_for_mode(
            db_paths,
            color_layers=int(color_layers),
            layer_height_mm=float(layer_height_mm),
            expected_channel_keys=(channel_keys if isinstance(channel_keys, list) else None),
            layer_order=layer_order,
        )
        explicit_subset = bool(metadata.extensions.get("native_db_subset_explicit"))
        if selected_db_paths and explicit_subset:
            exact_paths = list(selected_db_paths)
            remaining_paths = [path for path in db_paths if path not in set(exact_paths)]
            candidate_db_paths = exact_paths + remaining_paths
        elif selected_db_paths:
            candidate_db_paths = list(selected_db_paths)
        else:
            candidate_db_paths = list(db_paths)
        if not candidate_db_paths:
            return None

        rgb_parts: list[np.ndarray] = []
        stack_parts: list[np.ndarray] = []
        channel_keys = metadata.extensions.get("native_channel_keys")
        canonical_channel_keys = (
            [
                normalize_channel_key(str(key))
                for key in channel_keys
                if str(key)
            ]
            if isinstance(channel_keys, list)
            else []
        )
        canonical_lookup = {
            key: idx for idx, key in enumerate(canonical_channel_keys)
        }
        target_layers = int(color_layers)
        target_height = float(layer_height_mm)
        target_order = str(layer_order or getattr(metadata, "layer_order", "Top2Bottom"))
        target_base_channel = int(getattr(metadata, "base_channel_idx", 0))

        for db_path in candidate_db_paths:
            rgb, stacks, _db_metadata = cls._load_keyed_json(db_path, Path(db_path).stem)
            if (
                rgb is None
                or stacks is None
                or not isinstance(stacks, np.ndarray)
                or rgb.size == 0
                or stacks.ndim != 2
                or stacks.shape[0] != rgb.reshape(-1, 3).shape[0]
            ):
                continue
            if canonical_lookup and _db_metadata.palette:
                remapped = np.full(stacks.shape, -1, dtype=np.int32)
                db_index_to_bundle_index: dict[int, int] = {}
                for db_idx, entry in enumerate(_db_metadata.palette):
                    bundle_idx = canonical_lookup.get(
                        normalize_channel_key(build_channel_key(entry.color, entry.material))
                    )
                    if bundle_idx is not None:
                        db_index_to_bundle_index[db_idx] = bundle_idx
                for db_idx, bundle_idx in db_index_to_bundle_index.items():
                    remapped[stacks == db_idx] = bundle_idx
                stacks = remapped
            source_height = float(getattr(_db_metadata, "layer_height_mm", target_height))
            source_order = str(getattr(_db_metadata, "layer_order", target_order))
            converted_rows: list[list[int]] = []
            for recipe in stacks:
                recipe_list = [int(v) for v in recipe]
                try:
                    converted = expand_recipe_by_layer_height(
                        recipe_list,
                        source_height,
                        target_height,
                        source_order=source_order,
                        target_order=target_order,
                    )
                except ValueError:
                    converted = convert_recipe_between_orders(recipe_list, source_order, target_order)
                converted = pad_recipe_to_layer_count(
                    converted,
                    target_layers,
                    target_base_channel,
                    layer_order=target_order,
                )
                converted_rows.append(converted[:target_layers])
            if not converted_rows:
                continue
            rgb_parts.append(rgb.reshape(-1, 3))
            stack_parts.append(np.asarray(converted_rows, dtype=np.int32))

        if not rgb_parts:
            return None
        if len(rgb_parts) == 1:
            return rgb_parts[0], stack_parts[0]
        return np.concatenate(rgb_parts, axis=0), np.concatenate(stack_parts, axis=0)

    @classmethod
    def _apply_native_context_to_metadata(
        cls,
        metadata: LUTMetadata,
        native_ctx,
        *,
        custom_recipe_supported: bool = False,
    ) -> LUTMetadata:
        metadata.extensions["source_kind"] = native_ctx.source_kind
        metadata.extensions["supported_modes"] = list(native_ctx.supported_modes)
        metadata.extensions["custom_recipe_supported"] = bool(custom_recipe_supported)
        if native_ctx.package_path:
            metadata.extensions["native_model_package_path"] = native_ctx.package_path
        if native_ctx.stage_model_path:
            metadata.extensions["native_stage_model_path"] = native_ctx.stage_model_path
            metadata.capabilities = sorted(set(metadata.capabilities) | {"predictive_model"})
        if native_ctx.recipe_path:
            metadata.extensions["native_recipe_path"] = native_ctx.recipe_path
        if native_ctx.db_paths:
            metadata.extensions["native_db_paths"] = list(native_ctx.db_paths)
        if native_ctx.channel_keys:
            metadata.extensions["native_channel_keys"] = list(native_ctx.channel_keys)
        if native_ctx.vendor:
            metadata.extensions["native_vendor"] = native_ctx.vendor
        if native_ctx.material_type:
            metadata.extensions["native_material_type"] = native_ctx.material_type
        if native_ctx.source_kind == SOURCE_KIND_PACKAGE:
            metadata.capabilities = sorted(set(metadata.capabilities) | {"predictive_match", "dynamic_layer_count"})
        elif native_ctx.source_kind == SOURCE_KIND_STAGE_MODEL:
            metadata.capabilities = sorted(set(metadata.capabilities) | {"predictive_model", "dynamic_layer_count"})
        elif native_ctx.source_kind == SOURCE_KIND_COLORD_DB:
            metadata.capabilities = sorted(set(metadata.capabilities) | {"legacy_lookup"})
        if custom_recipe_supported:
            metadata.capabilities = sorted(set(metadata.capabilities) | {"custom_recipe"})
        return metadata

    @classmethod
    def _load_native_colordb_json(
        cls,
        file_path: str,
        display_name: str,
        data: dict,
        native_ctx,
    ) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        palette_raw = data.get("palette", [])
        palette = [
            PaletteEntry(
                color=str(item.get("color", "")),
                material=str(item.get("material", native_ctx.material_type) or ""),
            )
            for item in palette_raw
            if isinstance(item, dict) and str(item.get("color", ""))
        ]
        entries_raw = data.get("entries", [])
        entries = [
            entry
            for entry in entries_raw
            if isinstance(entry, dict)
        ] if isinstance(entries_raw, list) else []
        native_layer_count = cls._infer_native_colordb_recipe_layer_count(data, entries)
        raw_stack_rows: list[list[int]] = []
        for entry in entries:
            recipe_raw = entry.get("recipe", [])
            if not isinstance(recipe_raw, (list, tuple)):
                recipe_indices = [-1] * native_layer_count
            else:
                recipe_indices = [
                    cls._resolve_recipe_member(value, {}, file_path)
                    for value in recipe_raw
                ]
                if len(recipe_indices) != native_layer_count:
                    recipe_indices = [-1] * native_layer_count
            raw_stack_rows.append(recipe_indices)
        stack_width = max(
            [native_layer_count] + [len(row) for row in raw_stack_rows],
            default=native_layer_count,
        )
        stack_rows = [
            cls._normalize_native_colordb_recipe_width(row, stack_width)
            for row in raw_stack_rows
        ]
        stacks = (
            np.asarray(stack_rows, dtype=np.int32)
            if stack_rows
            else np.zeros((0, native_layer_count), dtype=np.int32)
        )
        labs = np.asarray(
            [entry.get("lab", [0.0, 0.0, 0.0]) for entry in entries],
            dtype=np.float32,
        )
        rgb = standard_lab_to_rgb_uint8(labs)
        try:
            metadata_layer_count = int(data.get("max_color_layers", 0))
        except (TypeError, ValueError):
            metadata_layer_count = 0
        metadata = LUTMetadata(
            palette=palette,
            manufacturer=str(data.get("manufacturer", "") or ""),
            type=str(data.get("type", "") or ""),
            color_mode=derive_color_mode_from_palette_entries(palette, display_name),
            max_color_layers=max(
                metadata_layer_count,
                stacks.shape[1] if stacks.ndim == 2 else 0,
            ),
            layer_height_mm=float(data.get("layer_height_mm", 0.08)),
            line_width_mm=float(data.get("line_width_mm", 0.42)),
            base_layers=int(data.get("base_layers", 0)),
            base_channel_idx=int(data.get("base_channel_idx", 0)),
            layer_order=str(data.get("layer_order", "Top2Bottom")),
        )
        metadata = cls._apply_native_context_to_metadata(
            metadata,
            native_ctx,
            custom_recipe_supported=bool(native_ctx.package_path or native_ctx.stage_model_path),
        )
        return rgb, stacks, metadata

    @classmethod
    def _load_native_stage_model_json(
        cls,
        file_path: str,
        display_name: str,
        data: dict,
        native_ctx,
    ) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        palette: list[PaletteEntry] = [
            PaletteEntry(color=split_channel_key(key)[0], material=split_channel_key(key)[1])
            for key in native_ctx.channel_keys
        ]
        channels = data.get("parameters", {}).get("channels", [])
        rgb_list: list[list[int]] = []
        for item in channels:
            if not isinstance(item, dict):
                continue
            e_rgb = np.asarray(item.get("E", [0.5, 0.5, 0.5]), dtype=np.float32)
            rgb_list.append([int(np.clip(round(float(v) * 255.0), 0, 255)) for v in e_rgb])

        rgb = np.asarray(rgb_list, dtype=np.uint8) if rgb_list else np.zeros((0, 3), dtype=np.uint8)
        stacks = None
        default_mode = next(
            (mode for mode in native_ctx.supported_modes if int(mode.get("color_layers", 0)) == 5),
            native_ctx.supported_modes[0] if native_ctx.supported_modes else None,
        )
        if native_ctx.db_paths:
            try:
                selected_db_paths = ()
                if default_mode is not None:
                    selected_db_paths = select_native_db_paths_for_mode(
                        native_ctx.db_paths,
                        color_layers=int(default_mode.get("color_layers", 5)),
                        layer_height_mm=float(default_mode.get("layer_height_mm", 0.08)),
                        expected_channel_keys=native_ctx.channel_keys,
                        layer_order=str(default_mode.get("layer_order", "Top2Bottom")),
                    )
                    resolved_base_channel_idx = (
                        _resolve_model_package_base_channel_idx(
                            msgpack.unpackb(Path(native_ctx.package_path).read_bytes(), raw=False),
                            list(native_ctx.channel_keys),
                            default_mode,
                        )
                        if native_ctx.package_path
                        else _resolve_native_base_channel_idx(list(native_ctx.channel_keys))
                    )
                    selected_lookup = cls.load_native_bundle_exact_lookup(
                        LUTMetadata(
                            layer_order=str(default_mode.get("layer_order", "Top2Bottom")),
                            base_channel_idx=resolved_base_channel_idx,
                            extensions={
                                "native_db_paths": list(native_ctx.db_paths),
                                "native_channel_keys": list(native_ctx.channel_keys),
                                "native_db_subset_explicit": bool(data.get("selected_db_paths")),
                            }
                        ),
                        color_layers=int(default_mode.get("color_layers", 5)),
                        layer_height_mm=float(default_mode.get("layer_height_mm", 0.08)),
                        layer_order=str(default_mode.get("layer_order", "Top2Bottom")),
                    )
                    if selected_lookup is not None:
                        rgb, stacks = selected_lookup
                sample_db_path = selected_db_paths[0] if selected_db_paths else native_ctx.db_paths[0]
                _db_rgb, _db_stacks, db_meta = cls._load_keyed_json(sample_db_path, Path(sample_db_path).stem)
                if stacks is None:
                    rgb = _db_rgb
                    stacks = _db_stacks
                if not palette:
                    palette = db_meta.palette or palette
            except Exception:
                pass

        metadata = LUTMetadata(
            palette=palette,
            color_mode=derive_color_mode_from_palette_entries(palette, display_name),
            max_color_layers=(stacks.shape[1] if isinstance(stacks, np.ndarray) and stacks.ndim == 2 and stacks.size else 5),
            layer_height_mm=(native_ctx.supported_modes[0]["layer_height_mm"] if native_ctx.supported_modes else 0.08),
            line_width_mm=0.42,
            base_layers=0,
            base_channel_idx=(
                _resolve_model_package_base_channel_idx(
                    msgpack.unpackb(Path(native_ctx.package_path).read_bytes(), raw=False),
                    list(native_ctx.channel_keys),
                    default_mode,
                )
                if native_ctx.package_path
                else _resolve_native_base_channel_idx(list(native_ctx.channel_keys))
            ),
            layer_order=(native_ctx.supported_modes[0].get("layer_order", "Top2Bottom") if native_ctx.supported_modes else "Top2Bottom"),
        )
        if native_ctx.package_path:
            metadata.extensions["runtime_package"] = build_model_package_runtime_payload(native_ctx.package_path)
            metadata.capabilities = sorted(set(metadata.capabilities) | {"predictive_match"})
        metadata.extensions["native_db_subset_explicit"] = bool(data.get("selected_db_paths"))
        metadata = cls._apply_native_context_to_metadata(metadata, native_ctx, custom_recipe_supported=True)
        return rgb, stacks, metadata

    @classmethod
    def _load_native_recipe_json(
        cls,
        file_path: str,
        display_name: str,
        data: dict,
        native_ctx,
    ) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        runtime_payload = build_recipe_runtime_payload(data)
        modes = runtime_payload.get("modes", {})
        first_mode = next(iter(modes.values())) if isinstance(modes, dict) and modes else None
        stacks = np.asarray(first_mode.get("candidate_recipes", []), dtype=np.int32) if first_mode else np.zeros((0, 0), dtype=np.int32)
        pred_lab = np.asarray(first_mode.get("pred_lab", []), dtype=np.float32) if first_mode else np.zeros((0, 3), dtype=np.float32)
        rgb = standard_lab_to_rgb_uint8(pred_lab)
        palette_raw = data.get("palette", [])
        palette = [
            PaletteEntry(
                color=str(item.get("color", "")),
                material=str(item.get("material", native_ctx.material_type) or ""),
            )
            for item in palette_raw
            if isinstance(item, dict) and str(item.get("color", ""))
        ]
        metadata = LUTMetadata(
            palette=palette,
            color_mode=derive_color_mode_from_palette_entries(palette, display_name),
            max_color_layers=int(first_mode.get("color_layers", stacks.shape[1] if stacks.ndim == 2 else 0)) if first_mode else 5,
            layer_height_mm=float(first_mode.get("layer_height_mm", 0.08)) if first_mode else 0.08,
            line_width_mm=0.42,
            base_layers=int(data.get("base_layers", 0)),
            base_channel_idx=int(data.get("base_channel_idx", 0)),
            layer_order=str(first_mode.get("layer_order", "Top2Bottom")) if first_mode else "Top2Bottom",
            schema_version="1.0",
            capabilities=["predictive_match", "dynamic_layer_count", "custom_recipe"],
            extensions={"runtime_package": runtime_payload},
        )
        metadata = cls._apply_native_context_to_metadata(metadata, native_ctx, custom_recipe_supported=True)
        return rgb, stacks, metadata

    @classmethod
    def _load_model_package_from_payload(
        cls,
        file_path: str,
        display_name: str,
        payload: Any,
    ) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        native_ctx = _parse_model_package_payload(payload, file_path)
        runtime_package = build_model_package_runtime_payload(file_path, payload=payload)
        runtime_supported_modes = _supported_modes_from_runtime_package(runtime_package)
        effective_mode = _select_preferred_supported_mode(runtime_supported_modes)
        palette = [
            PaletteEntry(color=split_channel_key(key)[0], material=split_channel_key(key)[1])
            for key in native_ctx.channel_keys
        ]
        rgb = np.zeros((0, 3), dtype=np.uint8)
        stacks = None
        metadata = LUTMetadata(
            palette=palette,
            color_mode=derive_color_mode_from_palette_entries(palette, display_name),
            max_color_layers=(
                int(effective_mode["color_layers"])
                if effective_mode is not None
                else 5
            ),
            layer_height_mm=(float(effective_mode["layer_height_mm"]) if effective_mode is not None else 0.08),
            line_width_mm=0.42,
            base_layers=0,
            base_channel_idx=_resolve_model_package_base_channel_idx(payload, list(native_ctx.channel_keys), effective_mode),
            layer_order=(str(effective_mode.get("layer_order", "Top2Bottom")) if effective_mode is not None else "Top2Bottom"),
            schema_version="2.0",
            capabilities=["predictive_match", "dynamic_layer_count", "custom_recipe"],
        )
        metadata.extensions["runtime_package"] = runtime_package
        metadata.extensions["native_db_subset_explicit"] = bool(
            isinstance(payload, dict) and payload.get("selected_db_paths")
        )
        metadata = cls._apply_native_context_to_metadata(metadata, native_ctx, custom_recipe_supported=True)
        if runtime_supported_modes:
            metadata.extensions["supported_modes"] = runtime_supported_modes
        return rgb, stacks, metadata

    @classmethod
    def _load_model_package(cls, file_path: str, display_name: str) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        payload = msgpack.unpackb(Path(file_path).read_bytes(), raw=False)
        return cls._load_model_package_from_payload(file_path, display_name, payload)

    @classmethod
    def _is_model_package_payload(cls, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        modes = payload.get("modes")
        if not isinstance(modes, list) or not modes:
            return False
        return any(
            isinstance(mode, dict)
            and mode.get("num_candidates")
            and ("candidate_recipes" in mode or "pred_lab" in mode)
            for mode in modes
        )

    @classmethod
    def _load_keyed_json_flat_list(
        cls,
        data: list,
        display_name: str,
        file_path: str,
    ) -> tuple[np.ndarray, np.ndarray | None, 'LUTMetadata']:
        """Load a flat-list JSON LUT: [{recipe, rgb, hex, source}, ...].
        加载顶层为数组的旧格式 JSON LUT 文件。
        """
        # Legacy flat-list JSON has no metadata/max_color_layers field, so it
        # remains a five-layer-only format. Use keyed JSON for six-layer recipes.
        legacy_recipe_width = PrinterConfig.COLOR_LAYERS
        numeric_recipe_rows: list[list[int]] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            recipe_raw = entry.get("recipe", [])
            if not isinstance(recipe_raw, (list, tuple)) or len(recipe_raw) != legacy_recipe_width:
                continue
            parsed_row = [cls._parse_integer_recipe_value(value) for value in recipe_raw]
            if any(value is None for value in parsed_row):
                continue
            recipe_indices = [int(value) for value in parsed_row]
            if any(index < 0 or index >= 8 for index in recipe_indices):
                continue
            numeric_recipe_rows.append(recipe_indices)
        prefer_numeric_recipes = bool(
            cls._infer_color_count_from_resolved_recipes(numeric_recipe_rows)
        )

        # 1. 收集所有出现的颜色名，构建 palette
        color_names_ordered: list[str] = []
        color_name_set: set[str] = set()
        if not prefer_numeric_recipes:
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                recipe_raw = entry.get("recipe", [])
                if not isinstance(recipe_raw, (list, tuple)):
                    continue
                for v in recipe_raw:
                    if (
                        isinstance(v, str)
                        and v != "Air"
                        and not cls._is_numeric_recipe_literal(v)
                        and v not in color_name_set
                    ):
                        color_names_ordered.append(v)
                        color_name_set.add(v)

        palette = [
            PaletteEntry(color=name, material="PLA Basic", hex_color=None)
            for name in color_names_ordered
        ]
        name_to_idx: dict[str, int] = {name: i for i, name in enumerate(color_names_ordered)}

        # 2. 解析 rgb + stacks
        rgb_list: list[list[int]] = []
        stacks_list: list[list[int]] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            rgb_val = entry.get("rgb")
            if rgb_val and len(rgb_val) == 3:
                rgb_list.append([max(0, min(255, int(v))) for v in rgb_val])
            else:
                rgb_list.append([0, 0, 0])

            recipe_raw = entry.get("recipe", [])
            if not isinstance(recipe_raw, (list, tuple)):
                _log.debug(
                    "Invalid LUT recipe payload marked unavailable",
                    extra={
                        "event": "lut_recipe_payload_invalid",
                        "path": file_path,
                        "recipe_value": recipe_raw,
                    },
                )
                recipe_indices = [-1] * legacy_recipe_width
            else:
                recipe_indices = [
                    cls._resolve_recipe_member(value, name_to_idx, file_path)
                    for value in recipe_raw
                ]
            recipe_indices = cls._normalize_resolved_layer_recipe(
                recipe_indices,
                max_color_layers=legacy_recipe_width,
            )
            stacks_list.append(recipe_indices)

        rgb = np.array(rgb_list, dtype=np.uint8) if rgb_list else np.zeros((0, 3), dtype=np.uint8)
        stacks = np.array(stacks_list, dtype=np.int32) if stacks_list else None
        if _looks_like_missing_keyed_stacks(stacks, rgb.reshape(-1, 3).shape[0]):
            stacks = None

        metadata = LUTMetadata(
            palette=palette,
            max_color_layers=max(PrinterConfig.COLOR_LAYERS, max((len(row) for row in stacks_list), default=0)),
            layer_height_mm=PrinterConfig.LAYER_HEIGHT,
            line_width_mm=PrinterConfig.NOZZLE_WIDTH,
            base_layers=10,
            base_channel_idx=0,
            layer_order="Top2Bottom",
        )
        if not metadata.palette:
            inferred_count = cls._infer_color_count_from_resolved_recipes(stacks_list)
            if inferred_count is not None:
                metadata.extensions["inferred_color_count"] = inferred_count
        _log.info(
            "Loaded flat-list JSON LUT",
            extra={
                "event": "lut_flat_list_json_loaded",
                "path": file_path,
                "entry_count": len(rgb_list),
                "palette_color_count": len(palette),
                "has_stacks": stacks is not None,
            },
        )
        if stacks is not None:
            _log.debug(
                "Generated LUT stacks array",
                extra={
                    "event": "lut_stacks_array_generated",
                    "path": file_path,
                    "shape": tuple(int(value) for value in stacks.shape),
                    "dtype": str(stacks.dtype),
                },
            )
        else:
            _log.warning(
                "LUT stacks array missing",
                extra={
                    "event": "lut_stacks_missing",
                    "path": file_path,
                    "entry_count": len(rgb_list),
                },
            )
        return rgb, stacks, metadata

    @classmethod
    def _load_npz(cls, file_path: str, display_name: str) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        """Load a .npz LUT file with optional metadata_json.
        加载 .npz 格式的 LUT 文件，解析可选的 metadata_json 键。
        """
        try:
            npz = np.load(file_path, allow_pickle=False)
        except Exception as e:
            _log.warning(
                "Failed to load NPZ LUT file",
                extra={
                    "event": "lut_npz_load_failed",
                    "path": file_path,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            rgb = np.zeros((0, 3), dtype=np.uint8)
            metadata = cls.infer_default_metadata(display_name, file_path, 0)
            return rgb, None, metadata

        rgb = npz.get("rgb", np.zeros((0, 3), dtype=np.uint8))
        stacks = None
        if "stacks" in npz:
            try:
                stacks = npz["stacks"]
            except ValueError as exc:
                if "Object arrays cannot be loaded" not in str(exc):
                    raise
                stacks = np.full((len(rgb), 5), -1, dtype=int)

        # Parse metadata_json if present
        metadata_json_str = None
        if "metadata_json" in npz:
            try:
                metadata_json_str = str(npz["metadata_json"])
            except Exception:
                pass

        if metadata_json_str:
            try:
                meta_dict = json.loads(metadata_json_str)
                metadata = LUTMetadata.from_dict(meta_dict)
                metadata.color_mode = cls._canonicalize_legacy_color_mode(metadata.color_mode, meta_dict)
            except Exception as e:
                _log.warning(
                    "Failed to parse LUT metadata_json",
                    extra={
                        "event": "lut_metadata_json_parse_failed",
                        "path": file_path,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
                metadata = cls.infer_default_metadata(display_name, file_path, len(rgb))
        else:
            metadata = cls.infer_default_metadata(display_name, file_path, len(rgb))

        return rgb, stacks, metadata

    @classmethod
    def save_keyed_json(cls, path: str, rgb: np.ndarray, stacks: np.ndarray,
                        metadata: LUTMetadata, lab: np.ndarray | None = None,
                        sources: list[str] | None = None,
                        preserve_extensions: bool = True,
                        legacy_save: bool = False) -> None:
        """Save LUT data as Keyed JSON format.
        将 LUT 数据保存为 Keyed JSON 格式。

        Args:
            path (str): Output file path. (输出文件路径)
            rgb (np.ndarray): RGB array (N, 3) uint8. (RGB 数组)
            stacks (np.ndarray): Stacks array (N, L) int32. (堆叠配方数组)
            metadata (LUTMetadata): LUT metadata. (LUT 元数据)
            lab (np.ndarray | None): Optional Lab array (N, 3). If None, convert from RGB.
                                     (可选 Lab 数组，为 None 时从 RGB 转换)
            sources (list[str] | None): Optional per-entry source labels (e.g. origin LUT name).
                                        (可选的每条记录来源标识)
            preserve_extensions (bool): Preserve LUT V2 extension blocks by default.
                                        (默认保留 LUT V2 扩展块)
            legacy_save (bool): Force V1-only output without V2 extension blocks.
                                (强制输出不带 V2 扩展块的 V1 结构)
        """
        meta_dict = metadata.to_dict()
        if stacks is not None:
            stack_array = np.asarray(stacks)
            if stack_array.ndim == 2 and stack_array.shape[1] > 0:
                meta_dict["max_color_layers"] = int(stack_array.shape[1])
        if legacy_save or not preserve_extensions:
            for key in list(metadata.extensions.keys()):
                meta_dict.pop(key, None)
            if metadata.schema_version is not None:
                meta_dict.pop("schema_version", None)
            if metadata.capabilities:
                meta_dict.pop("capabilities", None)

        # Build name from filename
        meta_dict["name"] = Path(path).stem

        # Build palette name list for recipe index → name mapping
        palette_names = [e.color for e in metadata.palette]

        # Build entries
        entries = []
        n = len(rgb)

        # Batch RGB → Lab conversion using OpenCV (much faster than per-entry colormath)
        if lab is None:
            import cv2
            rgb_arr = np.array(rgb[:n], dtype=np.uint8).reshape(1, n, 3)
            lab_arr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2Lab).reshape(n, 3).astype(float)
            # OpenCV Lab range: L [0,255], a [0,255], b [0,255] → standard L [0,100], a [-128,127], b [-128,127]
            lab_arr[:, 0] = lab_arr[:, 0] * 100.0 / 255.0
            lab_arr[:, 1] = lab_arr[:, 1] - 128.0
            lab_arr[:, 2] = lab_arr[:, 2] - 128.0
        else:
            lab_arr = np.array(lab[:n], dtype=float)

        for i in range(n):
            entry: dict = {}
            # Store original RGB for exact roundtrip
            r, g, b = int(rgb[i][0]), int(rgb[i][1]), int(rgb[i][2])
            entry["rgb"] = [r, g, b]
            
            # Hex color representation (RGB → #RRGGBB)
            entry["hex"] = f"#{r:02X}{g:02X}{b:02X}"
            
            # Lab values (pre-computed batch)
            entry["lab"] = [
                round(float(lab_arr[i][0]), 6),
                round(float(lab_arr[i][1]), 6),
                round(float(lab_arr[i][2]), 6),
            ]

            # Recipe: use palette color names instead of numeric indices
            if stacks is not None and i < len(stacks):
                recipe_names = []
                for v in stacks[i]:
                    idx = int(v)
                    if idx == -1:
                        recipe_names.append("Air")
                    elif 0 <= idx < len(palette_names):
                        recipe_names.append(palette_names[idx])
                    else:
                        recipe_names.append(f"Unknown({idx})")
                entry["recipe"] = recipe_names
            else:
                entry["recipe"] = []

            # Source label (origin LUT name for merged entries)
            if sources and i < len(sources):
                entry["source"] = sources[i]

            entries.append(entry)

        meta_dict["entries"] = entries

        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta_dict, f, ensure_ascii=False, indent=4)

    @classmethod
    def save_npz_with_metadata(cls, path: str, rgb: np.ndarray, stacks: np.ndarray,
                               metadata: LUTMetadata) -> None:
        """Save LUT data as .npz with metadata_json key.
        将 LUT 数据保存为 .npz 格式，含 metadata_json 键。

        Args:
            path (str): Output file path. (输出文件路径)
            rgb (np.ndarray): RGB array (N, 3) uint8. (RGB 数组)
            stacks (np.ndarray): Stacks array (N, L) int32. (堆叠配方数组)
            metadata (LUTMetadata): LUT metadata. (LUT 元数据)
        """
        metadata_json_str = json.dumps(metadata.to_dict(), ensure_ascii=False)
        np.savez(
            path,
            rgb=rgb,
            stacks=stacks,
            metadata_json=np.array(metadata_json_str),
        )
