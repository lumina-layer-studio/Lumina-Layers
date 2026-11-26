"""Local material paths, JSON reading, library cache, and usage sidecars."""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from config import MATERIALS_DIR, TEMP_DIR

_INVALID_WINDOWS_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
INTERNAL_MATERIAL_ROOT_NAMES = frozenset({"_sync", "_solver_cache"})

_MATERIAL_LIBRARY_CACHE_TTL_S = 5 * 60

_MATERIAL_LIBRARY_CACHE_LOCK = threading.RLock()

_MATERIAL_LIBRARY_CACHE: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_material_dirname(material_name: str) -> str:
    cleaned = _INVALID_WINDOWS_FILENAME.sub("_", str(material_name)).strip().strip(". ")
    return cleaned or "material"


def _unique_material_dir(
    base_dir: Path,
    material_name: str,
    *,
    brand: str | None = None,
) -> Path:
    """Compute an unused material directory path, optionally under a brand subdir.
    计算未被占用的耗材目录路径，可选放入品牌子目录。
    """
    stem = _sanitize_material_dirname(material_name)
    parent = base_dir
    if brand is not None:
        brand_stem = _sanitize_material_dirname(brand)
        parent = base_dir / brand_stem
    candidate = parent / stem
    if not candidate.exists():
        return candidate
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    return parent / f"{stem}_{suffix}"


def _json_clone(payload: Any) -> Any:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _material_library_cache_key(target_root: Path) -> str:
    try:
        return str(target_root.resolve())
    except OSError:
        return str(target_root.absolute())


def _material_library_path_state(path: Path) -> tuple[int, ...] | None:
    """Track replacement, edits, and symlink changes without reading file data.

    The first field is the target mtime, also used for the library's recency order.
    """
    try:
        state, link_state = path.stat(), path.lstat()
    except OSError:
        return None
    return (
        state.st_mtime_ns, state.st_ctime_ns, state.st_size,
        state.st_dev, state.st_ino, state.st_mode,
        link_state.st_mtime_ns, link_state.st_ctime_ns, link_state.st_ino,
    )


def _material_library_directory_children(directory: Path) -> frozenset[str] | None:
    listing = next(directory.walk(), None)
    return frozenset(listing[1]) if listing is not None else None


@dataclass
class _MaterialLibrarySnapshot:
    path_states: dict[Path, tuple[int, ...] | None] = field(default_factory=dict)
    directory_children: dict[Path, frozenset[str] | None] = field(default_factory=dict)

    def is_current(self) -> bool:
        if any(_material_library_path_state(path) != state for path, state in self.path_states.items()):
            return False
        # Rapid directory changes can leave the parent's stat signature unchanged.
        return all(
            _material_library_directory_children(directory) == children
            for directory, children in self.directory_children.items()
        )


def _cached_material_library_items(target_root: Path) -> list[dict[str, Any]] | None:
    cache_key = _material_library_cache_key(target_root)
    now = time.monotonic()
    with _MATERIAL_LIBRARY_CACHE_LOCK:
        cached = _MATERIAL_LIBRARY_CACHE.get(cache_key)
        if not cached:
            return None
        cached_at = float(cached.get("cached_at") or 0.0)
        if now - cached_at > _MATERIAL_LIBRARY_CACHE_TTL_S:
            _MATERIAL_LIBRARY_CACHE.pop(cache_key, None)
            return None
        payload, snapshot = cached.get("payload"), cached.get("snapshot")
    if not isinstance(payload, list) or not isinstance(snapshot, _MaterialLibrarySnapshot):
        return None
    if not snapshot.is_current():
        with _MATERIAL_LIBRARY_CACHE_LOCK:
            if _MATERIAL_LIBRARY_CACHE.get(cache_key) is cached:
                _MATERIAL_LIBRARY_CACHE.pop(cache_key, None)
        return None
    return _json_clone(payload)


def _store_material_library_cache(
    target_root: Path,
    payload: list[dict[str, Any]],
    *,
    snapshot: _MaterialLibrarySnapshot,
) -> None:
    # Never pair already-built summaries with a newer, unvalidated file state.
    if not snapshot.is_current():
        return
    cache_key = _material_library_cache_key(target_root)
    with _MATERIAL_LIBRARY_CACHE_LOCK:
        _MATERIAL_LIBRARY_CACHE[cache_key] = {
            "cached_at": time.monotonic(),
            "payload": _json_clone(payload),
            "snapshot": snapshot,
        }


def _invalidate_material_library_cache(target_root: Path | None = None) -> None:
    with _MATERIAL_LIBRARY_CACHE_LOCK:
        if target_root is None:
            _MATERIAL_LIBRARY_CACHE.clear()
            return
        _MATERIAL_LIBRARY_CACHE.pop(_material_library_cache_key(target_root), None)


def _normalize_relative_directory_name(directory_name: str) -> str:
    """Normalize a user-provided material directory_name to a POSIX relative path.
    将用户提供的耗材 directory_name 归一化为 POSIX 相对路径。

    Accepts forward-slash or backslash separators for cross-platform tolerance,
    rejects empty / absolute / traversal inputs, and returns the canonical
    forward-slash form. Does not touch the filesystem.
    """
    raw = str(directory_name).strip().replace("\\", "/")
    if not raw or raw in {".", ".."}:
        raise ValueError("directory_name must reference a saved material directory")
    if raw.startswith("/"):
        raise ValueError("directory_name must be a relative path")
    parts = [segment for segment in raw.split("/") if segment]
    if not parts:
        raise ValueError("directory_name must reference a saved material directory")
    for segment in parts:
        if segment in {".", ".."}:
            raise ValueError("directory_name must not contain '.' or '..' segments")
    requested = Path(*parts)
    if requested.anchor:
        raise ValueError("directory_name must be a relative path")
    return "/".join(parts)


def resolve_saved_material_dir(base_dir: Path, directory_name: str) -> Path:
    """Safely resolve a saved-material directory under ``base_dir``.
    在 ``base_dir`` 之下安全解析已保存的耗材目录。

    Supports multi-segment relative directory names (e.g. ``"瑞贝思/瑞贝思 PLA 白"``)
    while preventing path traversal: the resolved path must remain inside
    ``base_dir``. Returns the existing directory as a ``Path``.
    """
    normalized = _normalize_relative_directory_name(directory_name)
    candidate = (base_dir / normalized)
    try:
        resolved = candidate.resolve()
        root_resolved = base_dir.resolve()
    except OSError as exc:
        raise FileNotFoundError(f"Saved material directory not found: {normalized}") from exc
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("directory_name escapes the materials directory") from exc
    if not resolved.is_dir():
        raise FileNotFoundError(f"Saved material directory not found: {normalized}")
    return resolved


def _resolve_material_dir(base_dir: Path, directory_name: str) -> Path:
    """Backward-compatible alias kept for internal call sites."""
    return resolve_saved_material_dir(base_dir, directory_name)


def _relative_directory_name(base_dir: Path, material_dir: Path) -> str:
    """Return POSIX-style relative directory name for a saved material."""
    try:
        rel = material_dir.resolve().relative_to(base_dir.resolve())
    except ValueError:
        rel = Path(material_dir.name)
    return rel.as_posix()


def _prune_empty_parents(start_dir: Path, stop_dir: Path) -> None:
    """Remove empty ancestor directories up to (but excluding) ``stop_dir``.
    向上清理空的祖先目录，遇到 ``stop_dir`` 即停止（不含）。

    Best-effort: any OSError (non-empty, permission, etc.) halts pruning.
    """
    try:
        stop = stop_dir.resolve()
        current = start_dir.resolve()
    except OSError:
        return
    while current != stop and stop in current.parents:
        try:
            if any(current.iterdir()):
                return
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _load_json_object(path: Path, error_message: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(error_message) from exc
    if not isinstance(payload, dict):
        raise ValueError(error_message)
    return payload


def _resolve_stage_a_params_path(material_dir: Path, archive_payload: dict[str, Any]) -> Path:
    raw_value = str(archive_payload.get("stage_a_params_file") or "stage_A_parameters.json")
    normalized = raw_value.strip().replace("\\", "/")
    if not normalized:
        raise ValueError("stage_a_params_file must reference a file inside the material directory")
    path_parts = [segment for segment in normalized.split("/") if segment]
    if not path_parts or any(segment in {".", ".."} for segment in path_parts):
        raise ValueError("stage_a_params_file must reference a file inside the material directory")
    candidate = material_dir / Path(*path_parts)
    try:
        resolved = candidate.resolve()
        material_root = material_dir.resolve()
    except OSError as exc:
        raise ValueError("stage_a_params_file must reference a file inside the material directory") from exc
    try:
        resolved.relative_to(material_root)
    except ValueError as exc:
        raise ValueError("stage_a_params_file must reference a file inside the material directory") from exc
    return resolved


def _saved_material_brand_from_archive_payload(
    archive_payload: dict[str, Any],
    relative_directory_name: str,
) -> str | None:
    if "brand" in archive_payload:
        raw_brand = archive_payload.get("brand")
        if isinstance(raw_brand, str):
            cleaned_brand = raw_brand.strip()
            return cleaned_brand or None
        return None
    if "/" in relative_directory_name:
        return relative_directory_name.split("/", 1)[0]
    return None


_MATERIAL_PICKER_METADATA_KEYS = (
    "material_type",
    "material_product_id",
    "material_profile_id",
    "contributor_name",
)


def _clean_optional_archive_text(value: Any) -> str | None:
    """Return a trimmed archive metadata string or ``None``.
    返回去除首尾空白的档案元数据字符串，无有效内容时返回 ``None``。
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _resolve_picker_material_type(
    archive_payload: dict[str, Any],
    *,
    material_name: str,
    relative_directory_name: str,
) -> tuple[str | None, str | None]:
    """Resolve a material type for picker filtering without mutating archives.
    为选择器筛选解析材料类型，但不修改旧档案。

    Explicit archive metadata is authoritative. Legacy fallback recognizes
    only complete ASCII ``PLA`` or ``PETG`` tokens, even when adjacent to
    Chinese characters. The fallback is display-only and must never be used
    to group physical material products.
    显式档案字段优先；旧档案仅识别完整的 ASCII ``PLA`` 或 ``PETG`` 标记。
    兼容结果只用于展示，不得用于实体耗材归组。
    """
    explicit = _clean_optional_archive_text(
        archive_payload.get("material_type")
    )
    if explicit:
        return explicit.upper(), "archive"

    haystack = f"{material_name} {relative_directory_name}"
    for candidate in ("PETG", "PLA"):
        if re.search(
            rf"(?<![A-Za-z0-9]){candidate}(?![A-Za-z0-9])",
            haystack,
            flags=re.IGNORECASE,
        ):
            return candidate, "legacy_name"
    return None, None


def _picker_metadata_from_archive(
    archive_payload: dict[str, Any],
    *,
    material_name: str,
    relative_directory_name: str,
) -> dict[str, str | None]:
    material_type, material_type_source = _resolve_picker_material_type(
        archive_payload,
        material_name=material_name,
        relative_directory_name=relative_directory_name,
    )
    return {
        "material_type": material_type,
        "material_type_source": material_type_source,
        "material_product_id": _clean_optional_archive_text(
            archive_payload.get("material_product_id")
        ),
        "material_profile_id": _clean_optional_archive_text(
            archive_payload.get("material_profile_id")
        ),
        "contributor_name": _clean_optional_archive_text(
            archive_payload.get("contributor_name")
        ),
    }


def _normalize_material_directory_names(directory_names: list[str]) -> list[str]:
    normalized_names: list[str] = []
    seen: set[str] = set()
    for raw_name in directory_names:
        if not isinstance(raw_name, str):
            raise ValueError("directory_names must contain only strings")
        normalized = _normalize_relative_directory_name(raw_name)
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_names.append(normalized)
    if not normalized_names:
        raise ValueError("directory_names must contain at least one saved material directory")
    return normalized_names


def invalidate_material_library_cache(materials_dir: str | None = None) -> None:
    """Clear cached saved-material library summaries.
    清理已保存耗材库摘要缓存。
    """
    if materials_dir is None:
        _invalidate_material_library_cache()
        return
    _invalidate_material_library_cache(Path(materials_dir or MATERIALS_DIR))


def _is_internal_material_directory(directory_name: str) -> bool:
    return any(
        part.casefold() in INTERNAL_MATERIAL_ROOT_NAMES
        for part in directory_name.replace("\\", "/").split("/")
    )


def _discover_saved_material_dirs(
    material_root: Path, *, include_internal: bool = False,
    snapshot: _MaterialLibrarySnapshot | None = None,
) -> list[Path]:
    """Find archives, excluding internal stores by default and nested runs always."""
    archives: list[Path] = []
    if snapshot is not None:
        snapshot.directory_children[material_root] = None
    for directory, subdirs, _ in material_root.walk():
        archive = directory / "material.json"
        if snapshot is not None:
            snapshot.path_states[directory] = _material_library_path_state(directory)
            snapshot.path_states[archive] = _material_library_path_state(archive)
        if archive.is_file():
            archives.append(directory)
            subdirs.clear()
            if snapshot is not None:
                snapshot.directory_children.pop(directory, None)
            continue
        if snapshot is not None:
            snapshot.directory_children[directory] = frozenset(subdirs)
        if not include_internal:
            subdirs[:] = [name for name in subdirs if not _is_internal_material_directory(name)]
        if snapshot is not None:
            # walk() skips unreadable children; keep their permission state so a
            # repaired subtree can invalidate an otherwise empty cached list.
            for name in subdirs:
                child = directory / name
                snapshot.path_states[child] = _material_library_path_state(child)
                snapshot.directory_children[child] = None
    return archives


def _import_target_material_dir(target_root: Path, directory_name: str) -> Path:
    normalized = _normalize_relative_directory_name(directory_name)
    requested_path = target_root / normalized
    if not requested_path.exists():
        return requested_path
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candidate = requested_path.parent / f"{requested_path.name}_{suffix}"
    collision_index = 2
    while candidate.exists():
        candidate = requested_path.parent / f"{requested_path.name}_{suffix}_{collision_index}"
        collision_index += 1
    return candidate


def _safe_rgb_triplet(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    try:
        return [int(entry) for entry in value[:3]]
    except (TypeError, ValueError):
        return []


# ---------------------------------------------------------------------------
# Material usage tracking (per-material usage_stats.json sidecar)
# 耗材使用次数追踪（每个耗材目录下的 usage_stats.json 边车文件）
# ---------------------------------------------------------------------------

_MATERIAL_USAGE_FILENAME = "usage_stats.json"

_MATERIAL_USAGE_SCHEMA_VERSION = "1.0"

_MATERIAL_USAGE_HISTORY_LIMIT = 50


"""Maximum number of recent usage events kept in ``usage_stats.json``.
Older events are trimmed; aggregated counters in ``total`` / ``by_color_mode``
are never reset.
``usage_stats.json`` 中保留的最近使用事件数量上限；超出后旧事件会被裁剪，
但 ``total`` / ``by_color_mode`` 这些累计计数不会被重置。
"""


def _normalize_color_mode_for_usage(color_mode: Any) -> str:
    """Coerce a color_mode value to a clean string for usage bucketing.
    将 color_mode 值规范为用于使用次数分桶的干净字符串。

    Accepts enum members (with ``.value``), strings, and other primitives.
    Returns ``"unknown"`` for empty / non-stringifiable values.
    支持枚举（取 ``.value``）、字符串及其他基础类型；无效或空值返回 ``"unknown"``。
    """
    if color_mode is None:
        return "unknown"
    raw = getattr(color_mode, "value", color_mode)
    text = str(raw).strip()
    return text or "unknown"


def _empty_usage_payload() -> dict[str, Any]:
    """Build a fresh, zeroed usage_stats payload.
    构造一份初始化为零的 usage_stats 数据。
    """
    return {
        "schema_version": _MATERIAL_USAGE_SCHEMA_VERSION,
        "total": 0,
        "by_color_mode": {},
        "last_used_at": None,
        "last_used_color_mode": None,
        "history": [],
    }


def _load_usage_payload(material_dir: Path) -> dict[str, Any]:
    """Load and normalize ``usage_stats.json`` from a material directory.
    从耗材目录读取并规范化 ``usage_stats.json``。

    Tolerates missing / corrupt files by falling back to an empty payload —
    usage stats are diagnostics, never primary archive data, so a corrupted
    sidecar must not block the rest of the workflow.
    缺失或损坏的文件会回退为空 payload；usage 仅用于诊断展示，不应阻塞主流程。
    """
    usage_path = material_dir / _MATERIAL_USAGE_FILENAME
    if not usage_path.is_file():
        return _empty_usage_payload()
    try:
        raw = json.loads(usage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _empty_usage_payload()
    if not isinstance(raw, dict):
        return _empty_usage_payload()

    normalized = _empty_usage_payload()
    try:
        normalized["total"] = max(0, int(raw.get("total") or 0))
    except (TypeError, ValueError):
        normalized["total"] = 0

    by_mode_raw = raw.get("by_color_mode")
    if isinstance(by_mode_raw, dict):
        cleaned: dict[str, int] = {}
        for key, value in by_mode_raw.items():
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            cleaned[str(key)] = count
        normalized["by_color_mode"] = cleaned

    last_at = raw.get("last_used_at")
    if isinstance(last_at, str) and last_at.strip():
        normalized["last_used_at"] = last_at
    last_mode = raw.get("last_used_color_mode")
    if isinstance(last_mode, str) and last_mode.strip():
        normalized["last_used_color_mode"] = last_mode

    history_raw = raw.get("history")
    if isinstance(history_raw, list):
        cleaned_history: list[dict[str, Any]] = []
        for entry in history_raw[-_MATERIAL_USAGE_HISTORY_LIMIT:]:
            if not isinstance(entry, dict):
                continue
            mode = entry.get("color_mode")
            used_at = entry.get("used_at")
            if not isinstance(mode, str) or not isinstance(used_at, str):
                continue
            cleaned_history.append({"color_mode": mode, "used_at": used_at})
        normalized["history"] = cleaned_history
    return normalized


def get_material_usage(material_dir: Path | str) -> dict[str, Any]:
    """Public read accessor for a material's usage statistics.
    对外暴露的耗材使用统计读取函数。

    Args:
        material_dir: Path to the saved-material directory containing
            ``material.json``. (耗材档案目录)

    Returns:
        Normalized usage payload (always a dict; counters default to 0).
        规范化后的 usage payload，计数缺省为 0。
    """
    return _load_usage_payload(Path(material_dir))


def record_material_usage(
    directory_names: Sequence[str],
    color_mode: Any,
    *,
    materials_dir: str | None = None,
    used_at: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Record one usage event for each given material directory.
    为每个给定的耗材目录追加一次使用记录。

    Increments ``total`` and ``by_color_mode[color_mode]`` for each material,
    appends a history entry, and writes the sidecar back atomically (best
    effort: a per-material I/O failure is logged into the result dict but
    does not raise — usage tracking is auxiliary).

    Args:
        directory_names: Material directory_name values used in the build.
            (本次生成中使用的耗材目录名)
        color_mode: Color mode the build was generated under (enum or string).
            (本次生成使用的颜色模式)
        materials_dir: Optional override for the materials root directory.
            (可选的 materials 根目录覆盖)
        used_at: Optional ISO-8601 timestamp; defaults to now (UTC).
            (可选的 ISO-8601 时间戳；默认 UTC 当前时间)

    Returns:
        Mapping ``{directory_name: updated_usage_payload | {"error": "..."}}``
        for diagnostic purposes. 仅用于诊断。
    """
    if not directory_names:
        return {}
    target_root = Path(materials_dir or MATERIALS_DIR)
    timestamp = used_at if isinstance(used_at, str) and used_at.strip() else _now_iso()
    color_mode_label = _normalize_color_mode_for_usage(color_mode)

    seen: set[str] = set()
    results: dict[str, dict[str, Any]] = {}
    for raw_name in directory_names:
        if not isinstance(raw_name, str):
            continue
        try:
            normalized_name = _normalize_relative_directory_name(raw_name)
        except ValueError:
            results[str(raw_name)] = {"error": "invalid_directory_name"}
            continue
        if normalized_name in seen:
            continue
        seen.add(normalized_name)
        try:
            material_dir = resolve_saved_material_dir(target_root, normalized_name)
        except (ValueError, FileNotFoundError):
            results[normalized_name] = {"error": "material_not_found"}
            continue
        if not (material_dir / "material.json").is_file():
            results[normalized_name] = {"error": "material_archive_missing"}
            continue

        payload = _load_usage_payload(material_dir)
        payload["total"] = int(payload.get("total") or 0) + 1
        by_mode = payload.setdefault("by_color_mode", {})
        by_mode[color_mode_label] = int(by_mode.get(color_mode_label, 0) or 0) + 1
        payload["last_used_at"] = timestamp
        payload["last_used_color_mode"] = color_mode_label
        history = payload.setdefault("history", [])
        history.append({"color_mode": color_mode_label, "used_at": timestamp})
        if len(history) > _MATERIAL_USAGE_HISTORY_LIMIT:
            del history[: len(history) - _MATERIAL_USAGE_HISTORY_LIMIT]
        payload["schema_version"] = _MATERIAL_USAGE_SCHEMA_VERSION

        usage_path = material_dir / _MATERIAL_USAGE_FILENAME
        try:
            usage_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            results[normalized_name] = payload
        except OSError as exc:
            # Auxiliary tracking must never break a successful generation.
            # 辅助统计写入失败时不应影响生成主流程。
            results[normalized_name] = {"error": f"write_failed: {exc}"}
    if any("error" not in payload for payload in results.values()):
        _invalidate_material_library_cache(target_root)
    return results
