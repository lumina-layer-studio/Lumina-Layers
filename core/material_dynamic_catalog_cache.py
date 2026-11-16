"""Persistent cache for exact dynamic material candidate catalogs.

动态耗材精确候选目录的持久缓存。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
import zipfile
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from api.structured_logging import get_logger
from core.material_cache import (
    _find_cache_record, _legacy_material_enumeration_key, describe_material,
    default_cache_directory,
)
from core.material_candidate_cache import HYBRID_CANDIDATE_ALGORITHM_VERSION
from core.material_color_solver import MaterialParams, rgb_to_lab
from core.material_dynamic_solver import (
    DynamicCandidateCatalog,
    DynamicMaterialCandidateError,
)


DYNAMIC_CATALOG_SCHEMA_VERSION = 2
DYNAMIC_CATALOG_ALGORITHM_VERSION = "dynamic-ciede2000-v2"
_DYNAMIC_CACHE_SUBDIRECTORY = "dynamic-catalogs"
_CACHE_LOCK_TIMEOUT_SECONDS = 30.0
_PAYLOAD_FIELDS = {
    "score_srgb",
    "score_lab",
    "print_recipes_canonical",
    "minimum_actual_layer_counts",
    "max_layer_reachable",
    "source_indices",
    "metadata_json",
}
_log = get_logger(__name__)
_thread_locks_guard = threading.Lock()
_thread_locks: dict[str, threading.RLock] = {}


class DynamicCatalogCacheCorruptionError(ValueError):
    """Report one malformed dynamic catalog cache entry.

    报告单个损坏的动态候选目录缓存条目。
    """


@dataclass(frozen=True)
class DynamicCatalogCacheKey:
    """Describe every input that defines one candidate universe.

    描述决定单个候选宇宙的全部输入。

    Attributes:
        algorithm_version: Dynamic catalog algorithm version. 动态目录算法版本。
        candidate_source_version: Bounded candidate source algorithm version.
            有界候选来源算法版本。
        palette_descriptor: Serialized effective material descriptors.
            序列化的有效耗材描述。
        backing_material_descriptor: Selected backing identity and parameters.
            所选基板耗材的身份与参数。
        material_count: Number of materials in the palette. 调色板耗材数。
        layer_height_mm: Physical layer height. 物理层高。
        substrate: White or black optical substrate. 光学基底。
        min_layer_count: Minimum effective layer count. 最小有效层数。
        max_layer_count: Maximum/printed layer count. 最大及打印层数。
        candidate_budget: Explicit bounded candidate budget used at every
            layer count. 每个层数统一使用的显式候选预算。
    """

    algorithm_version: str
    candidate_source_version: str
    palette_descriptor: str
    backing_material_descriptor: str
    material_count: int
    layer_height_mm: float
    substrate: str
    min_layer_count: int
    max_layer_count: int
    candidate_budget: int

    def as_metadata(self) -> dict[str, object]:
        """Return a stable JSON-compatible key mapping.

        返回稳定且可 JSON 序列化的键映射。
        """

        return asdict(self)


@dataclass(frozen=True)
class CachedDynamicCandidateCatalog:
    """Loaded catalog and its pre-deduplication row count.

    已加载目录及其去重前候选行数。

    Attributes:
        catalog: Immutable catalog rebound to current user material order.
            已重绑到当前用户耗材顺序的不可变目录。
        candidate_count_before_dedup: Candidate rows before exact-RGB dedup.
            精确 RGB 去重前候选行数。
    """

    catalog: DynamicCandidateCatalog
    candidate_count_before_dedup: int


@dataclass(frozen=True)
class DynamicCatalogCacheResult(CachedDynamicCandidateCatalog):
    """Return a cache hit or a freshly built dynamic catalog.

    返回缓存命中或新构建的动态候选目录。

    Attributes:
        cache_hit: Whether the catalog came from a validated cache entry.
            是否命中已验证缓存条目。
        rebuilt_corrupt: Whether one corrupt entry was quarantined before build.
            构建前是否隔离了一个损坏条目。
    """

    cache_hit: bool
    rebuilt_corrupt: bool


DynamicCatalogBuilder = Callable[[], tuple[DynamicCandidateCatalog, int]]


def _validate_materials(materials: list[MaterialParams]) -> None:
    if not isinstance(materials, list) or not materials:
        raise ValueError("materials must be a non-empty list")
    if not all(isinstance(material, MaterialParams) for material in materials):
        raise TypeError("materials must contain MaterialParams values")


def _serialized_material(material: MaterialParams) -> str:
    return json.dumps(describe_material(material), sort_keys=True, separators=(",", ":"))


def _serialized_palette(materials: list[MaterialParams]) -> str:
    descriptors = [describe_material(materials[index])
                   for index in dynamic_material_canonical_order(materials)]
    return json.dumps(descriptors, sort_keys=True, separators=(",", ":"))


def _legacy_dynamic_enumeration_key(material: MaterialParams) -> str:
    """Preserve the historical dynamic recipe order, never cache identity.

    Equal optical results retain the same physical material choice. Cache
    records instead compare the complete saved descriptors directly.
    """
    payload = {
        "directory_name": str(material.directory_name).strip().casefold(),
        "name": str(material.name).strip().casefold(),
        "optical_fingerprint": _legacy_material_enumeration_key(material),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def dynamic_material_canonical_order(
    materials: list[MaterialParams],
) -> tuple[int, ...]:
    """Return identity-safe canonical indices for dynamic catalog building.

    返回用于动态目录构建的身份安全规范索引。

    Args:
        materials: Non-empty material palette in current user order. 当前用户
            顺序的非空耗材列表。

    Returns:
        tuple[int, ...]: Original palette indices sorted by stable material
            identity and optical properties. 按稳定耗材身份和光学参数排序后的
            原始列表索引。

    Raises:
        TypeError: If an entry is not a ``MaterialParams`` instance. 列表项
            不是 ``MaterialParams`` 实例。
        ValueError: If ``materials`` is not a non-empty list or contains
            duplicate material identities. ``materials`` 不是非空列表，或包含
            重复耗材身份。
    """

    _validate_materials(materials)
    identities = [
        _serialized_material(material) for material in materials
    ]
    if len(identities) != len(set(identities)):
        raise ValueError(
            "dynamic material catalog does not support duplicate material identities"
        )
    enumeration_keys = [_legacy_dynamic_enumeration_key(material) for material in materials]
    return tuple(sorted(range(len(materials)), key=lambda index: enumeration_keys[index]))


def build_dynamic_catalog_cache_key(
    materials: list[MaterialParams],
    *,
    backing_material_index: int,
    layer_height_mm: float,
    substrate: str,
    min_layer_count: int,
    max_layer_count: int,
    candidate_budget: int,
    algorithm_version: str = DYNAMIC_CATALOG_ALGORITHM_VERSION,
) -> DynamicCatalogCacheKey:
    """Build the order-independent identity of one dynamic catalog.

    构建一个动态候选目录的顺序无关标识。

    Args:
        materials: Material palette in current user order. 当前用户顺序耗材。
        backing_material_index: Backing index in current user order. 当前用户
            顺序中的基板索引。
        layer_height_mm: Physical layer height. 物理层高。
        substrate: Optical substrate, ``white`` or ``black``. 光学基底。
        min_layer_count: Minimum effective layer count. 最小有效层数。
        max_layer_count: Maximum effective/printed layer count. 最大有效层数。
        candidate_budget: One pinned candidate budget used for every layer.
            所有层数统一使用的固定候选预算。
        algorithm_version: Cache algorithm version override. 缓存算法版本覆盖。

    Returns:
        DynamicCatalogCacheKey: Validated cache identity. 已验证缓存标识。

    Raises:
        TypeError: If integer inputs use incompatible types. 整数输入类型不兼容。
        ValueError: If an input is outside its supported range. 输入超出范围。
    """

    _validate_materials(materials)
    for name, value in (
        ("backing_material_index", backing_material_index),
        ("min_layer_count", min_layer_count),
        ("max_layer_count", max_layer_count),
        ("candidate_budget", candidate_budget),
    ):
        if isinstance(value, (bool, np.bool_)) or not isinstance(
            value, (int, np.integer)
        ):
            raise TypeError(f"{name} must be an integer")
    backing_index = int(backing_material_index)
    minimum = int(min_layer_count)
    maximum = int(max_layer_count)
    budget = int(candidate_budget)
    if not 0 <= backing_index < len(materials):
        raise ValueError("backing_material_index is outside the material palette")
    if not 5 <= minimum <= maximum <= 30:
        raise ValueError("dynamic layer range must satisfy 5 <= min <= max <= 30")
    if budget <= 0:
        raise ValueError("candidate_budget must be positive")
    if isinstance(layer_height_mm, (bool, np.bool_)) or not isinstance(
        layer_height_mm, (int, float, np.integer, np.floating)
    ):
        raise TypeError("layer_height_mm must be a real number")
    height = float(layer_height_mm)
    if not math.isfinite(height) or height <= 0.0:
        raise ValueError("layer_height_mm must be finite and positive")
    normalized_substrate = str(substrate).lower()
    if normalized_substrate not in {"white", "black"}:
        raise ValueError("substrate must be 'white' or 'black'")
    normalized_version = str(algorithm_version).strip()
    if not normalized_version:
        raise ValueError("algorithm_version must not be empty")

    return DynamicCatalogCacheKey(
        algorithm_version=normalized_version,
        candidate_source_version=HYBRID_CANDIDATE_ALGORITHM_VERSION,
        palette_descriptor=_serialized_palette(materials),
        backing_material_descriptor=_serialized_material(
            materials[backing_index]
        ),
        material_count=len(materials),
        layer_height_mm=height,
        substrate=normalized_substrate,
        min_layer_count=minimum,
        max_layer_count=maximum,
        candidate_budget=budget,
    )


def dynamic_catalog_cache_file_path(
    key: DynamicCatalogCacheKey,
    *,
    cache_root: str | Path | None = None,
) -> Path:
    """Resolve the one-file NPZ path for a dynamic catalog key.

    解析动态目录键对应的单文件 NPZ 路径。

    Args:
        key: Validated dynamic catalog identity. 已验证动态目录标识。
        cache_root: Optional cache-root override. 可选缓存根目录。

    Returns:
        Path: Canonical one-file NPZ path. 规范的单 NPZ 文件路径。
    """

    if not isinstance(key, DynamicCatalogCacheKey):
        raise TypeError("key must be a DynamicCatalogCacheKey")
    directory = default_cache_directory(cache_root) / _DYNAMIC_CACHE_SUBDIRECTORY
    expected = {"schema_version": DYNAMIC_CATALOG_SCHEMA_VERSION, "key": key.as_metadata()}
    existing = _find_cache_record(directory, expected)
    return existing or directory / f"catalog-{uuid.uuid4().hex}.npz"


def _canonical_index_maps(
    materials: list[MaterialParams],
) -> tuple[np.ndarray, np.ndarray]:
    canonical_to_user = np.asarray(
        dynamic_material_canonical_order(materials), dtype=np.int32
    )
    if canonical_to_user.shape != (len(materials),):
        raise ValueError("canonical material order has an invalid shape")
    user_to_canonical = np.empty(len(materials), dtype=np.int32)
    user_to_canonical[canonical_to_user] = np.arange(len(materials), dtype=np.int32)
    return canonical_to_user, user_to_canonical


def _canonical_backing_index(
    materials: list[MaterialParams],
    key: DynamicCatalogCacheKey,
    user_to_canonical: np.ndarray,
) -> int:
    matches = [
        index
        for index, material in enumerate(materials)
        if _serialized_material(material) == key.backing_material_descriptor
    ]
    if not matches:
        raise ValueError("backing material descriptor is absent from the palette")
    return int(user_to_canonical[matches[0]])


def _metadata_bytes(metadata: dict[str, object]) -> np.ndarray:
    encoded = json.dumps(
        metadata,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return np.frombuffer(encoded, dtype=np.uint8)


def _thread_lock_for(path: Path) -> threading.RLock:
    lock_key = str(path.resolve()).casefold()
    with _thread_locks_guard:
        lock = _thread_locks.get(lock_key)
        if lock is None:
            lock = threading.RLock()
            _thread_locks[lock_key] = lock
        return lock


class _DynamicCatalogKeyLock:
    """Serialize one cache key across threads and operating-system processes."""

    def __init__(self, path: Path, *, layer_count: int) -> None:
        self._lock_path = path.with_name(path.name + ".lock")
        self._layer_count = int(layer_count)
        self._thread_lock = _thread_lock_for(self._lock_path)
        self._thread_acquired = False
        self._handle = None

    def __enter__(self) -> "_DynamicCatalogKeyLock":
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._thread_acquired = self._thread_lock.acquire(
                timeout=_CACHE_LOCK_TIMEOUT_SECONDS
            )
            if not self._thread_acquired:
                raise TimeoutError("thread lock timed out")
            self._handle = self._lock_path.open("a+b")
            self._handle.seek(0, os.SEEK_END)
            if self._handle.tell() == 0:
                self._handle.write(b"\0")
                self._handle.flush()
            deadline = time.monotonic() + _CACHE_LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    self._acquire_process_lock()
                    return self
                except (BlockingIOError, PermissionError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("process lock timed out")
                    time.sleep(0.05)
        except Exception as exc:
            self._release_resources()
            raise DynamicMaterialCandidateError(
                "dynamic catalog cache lock could not be acquired",
                layer_count=self._layer_count,
                phase="dynamic_catalog_cache_lock",
            ) from exc

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is not None:
            try:
                self._release_process_lock()
            finally:
                self._release_resources()
        else:
            self._release_resources()

    def _acquire_process_lock(self) -> None:
        if self._handle is None:
            raise RuntimeError("cache lock file is not open")
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release_process_lock(self) -> None:
        if self._handle is None:
            return
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)

    def _release_resources(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        if self._thread_acquired:
            self._thread_lock.release()
            self._thread_acquired = False


def _prepare_catalog_payload(
    catalog: DynamicCandidateCatalog,
    *,
    materials: list[MaterialParams],
    key: DynamicCatalogCacheKey,
    candidate_count_before_dedup: int,
) -> dict[str, np.ndarray]:
    _validate_materials(materials)
    if not isinstance(catalog, DynamicCandidateCatalog):
        raise TypeError("catalog must be a DynamicCandidateCatalog")
    if key.palette_descriptor != _serialized_palette(materials):
        raise ValueError("cache key does not match the material palette")
    before_count = int(candidate_count_before_dedup)
    after_count = int(catalog.score_srgb.shape[0])
    if before_count < after_count:
        raise ValueError("candidate_count_before_dedup cannot be smaller than catalog")
    if catalog.print_recipes.shape[1] != key.max_layer_count:
        raise ValueError("catalog recipe width does not match the cache key")
    if np.any(catalog.print_recipes < 0) or np.any(
        catalog.print_recipes >= len(materials)
    ):
        raise ValueError("catalog recipes contain invalid user material indices")

    canonical_to_user, user_to_canonical = _canonical_index_maps(materials)
    canonical_recipes = user_to_canonical[catalog.print_recipes]
    canonical_backing = _canonical_backing_index(materials, key, user_to_canonical)
    canonical_identities = [
        _serialized_material(materials[int(user_index)])
        for user_index in canonical_to_user
    ]
    metadata: dict[str, object] = {
        "schema_version": DYNAMIC_CATALOG_SCHEMA_VERSION,
        "key": key.as_metadata(),
        "recipe_index_space": "canonical",
        "canonical_material_descriptors": canonical_identities,
        "canonical_backing_material_index": canonical_backing,
        "canonical_backing_material_descriptor": canonical_identities[
            canonical_backing
        ],
        "candidate_count_before_dedup": before_count,
        "candidate_count_after_dedup": after_count,
    }
    payload = {
        "score_srgb": np.asarray(catalog.score_srgb, dtype=np.uint8),
        "score_lab": np.asarray(catalog.score_lab, dtype=np.float64),
        "print_recipes_canonical": np.asarray(canonical_recipes, dtype=np.int32),
        "minimum_actual_layer_counts": np.asarray(
            catalog.minimum_actual_layer_counts, dtype=np.int16
        ),
        "max_layer_reachable": np.asarray(
            catalog.max_layer_reachable, dtype=np.bool_
        ),
        "source_indices": np.asarray(catalog.source_indices, dtype=np.int64),
        "metadata_json": _metadata_bytes(metadata),
    }
    _validated_loaded_catalog(
        payload={
            field: payload[field]
            for field in _PAYLOAD_FIELDS
            if field != "metadata_json"
        },
        metadata=metadata,
        materials=materials,
        key=key,
    )
    return payload


def _resolve_catalog_record(
    key: DynamicCatalogCacheKey, cache_root: str | Path | None, *, register: bool,
) -> Path:
    directory = default_cache_directory(cache_root) / _DYNAMIC_CACHE_SUBDIRECTORY
    with _DynamicCatalogKeyLock(directory / "catalog", layer_count=key.max_layer_count):
        path = dynamic_catalog_cache_file_path(key, cache_root=cache_root)
        meta_path = path.with_suffix(".meta.json")
        if register and not meta_path.exists():
            temporary = meta_path.with_name(meta_path.name + f".tmp-{uuid.uuid4().hex}")
            try:
                temporary.write_text(json.dumps({
                    "schema_version": DYNAMIC_CATALOG_SCHEMA_VERSION,
                    "key": key.as_metadata(), "cache_id": path.stem,
                }, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary, meta_path)
            except OSError as exc:
                raise DynamicMaterialCandidateError(
                    "dynamic catalog record could not be registered",
                    layer_count=key.max_layer_count,
                    phase="dynamic_catalog_cache_register",
                ) from exc
            finally:
                temporary.unlink(missing_ok=True)
    return path


def _write_catalog_payload_unlocked(
    path: Path,
    payload: dict[str, np.ndarray],
) -> None:
    temporary = path.with_name(
        f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    )
    try:
        with temporary.open("wb") as handle:
            np.savez_compressed(handle, **payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def save_dynamic_candidate_catalog(
    catalog: DynamicCandidateCatalog,
    *,
    materials: list[MaterialParams],
    key: DynamicCatalogCacheKey,
    candidate_count_before_dedup: int,
    cache_root: str | Path | None = None,
) -> Path:
    """Atomically persist one catalog using canonical material indices.

    使用规范耗材索引原子保存一个动态候选目录。

    Args:
        catalog: User-order immutable dynamic catalog. 用户顺序不可变目录。
        materials: Materials matching the catalog's current recipe indices.
            与目录当前配方索引匹配的耗材。
        key: Validated order-independent cache identity. 已验证缓存标识。
        candidate_count_before_dedup: Source row count before exact-RGB dedup.
            精确 RGB 去重前的源行数。
        cache_root: Optional cache-root override. 可选缓存根目录。

    Returns:
        Path: Atomically replaced NPZ path. 原子替换后的 NPZ 路径。
    """

    payload = _prepare_catalog_payload(
        catalog,
        materials=materials,
        key=key,
        candidate_count_before_dedup=candidate_count_before_dedup,
    )
    path = _resolve_catalog_record(key, cache_root, register=True)
    with _DynamicCatalogKeyLock(path, layer_count=key.max_layer_count):
        _write_catalog_payload_unlocked(path, payload)
    return path


def _corruption(message: str, *, cause: Exception | None = None) -> None:
    error = DynamicCatalogCacheCorruptionError(message)
    if cause is not None:
        error.__cause__ = cause
    raise error


def _validated_loaded_catalog(
    *,
    payload: dict[str, np.ndarray],
    metadata: dict[str, object],
    materials: list[MaterialParams],
    key: DynamicCatalogCacheKey,
) -> CachedDynamicCandidateCatalog:
    if metadata.get("schema_version") != DYNAMIC_CATALOG_SCHEMA_VERSION:
        _corruption("dynamic catalog schema version mismatch")
    if metadata.get("key") != key.as_metadata():
        _corruption("dynamic catalog key mismatch")
    if metadata.get("recipe_index_space") != "canonical":
        _corruption("dynamic catalog recipes are not canonical indices")
    canonical_to_user, _user_to_canonical = _canonical_index_maps(materials)
    canonical_identities = [
        _serialized_material(materials[int(user_index)])
        for user_index in canonical_to_user
    ]
    if metadata.get("canonical_material_descriptors") != canonical_identities:
        _corruption("dynamic catalog canonical material identities are invalid")

    expected_dtypes = {
        "score_srgb": np.dtype(np.uint8),
        "score_lab": np.dtype(np.float64),
        "print_recipes_canonical": np.dtype(np.int32),
        "minimum_actual_layer_counts": np.dtype(np.int16),
        "max_layer_reachable": np.dtype(np.bool_),
        "source_indices": np.dtype(np.int64),
    }
    for field, dtype in expected_dtypes.items():
        if field not in payload or payload[field].dtype != dtype:
            _corruption(f"dynamic catalog field {field} has an invalid dtype")

    score_srgb = payload["score_srgb"]
    score_lab = payload["score_lab"]
    canonical_recipes = payload["print_recipes_canonical"]
    minimum_counts = payload["minimum_actual_layer_counts"]
    max_reachable = payload["max_layer_reachable"]
    source_indices = payload["source_indices"]
    row_count = int(score_srgb.shape[0]) if score_srgb.ndim == 2 else -1
    if row_count <= 0 or score_srgb.shape != (row_count, 3):
        _corruption("dynamic catalog score_srgb shape is invalid")
    if score_lab.shape != (row_count, 3):
        _corruption("dynamic catalog score_lab shape is invalid")
    if canonical_recipes.shape != (row_count, key.max_layer_count):
        _corruption("dynamic catalog recipe shape is invalid")
    if any(
        value.shape != (row_count,)
        for value in (minimum_counts, max_reachable, source_indices)
    ):
        _corruption("dynamic catalog vector field shape is invalid")
    if not np.all(np.isfinite(score_lab)):
        _corruption("dynamic catalog score_lab contains non-finite values")
    if np.unique(score_srgb, axis=0).shape[0] != row_count:
        _corruption("dynamic catalog score_srgb rows are not unique")
    expected_lab = np.asarray(rgb_to_lab(score_srgb), dtype=np.float64)
    if not np.array_equal(score_lab, expected_lab):
        _corruption("dynamic catalog score_lab violates the scoring contract")
    if np.any(canonical_recipes < 0) or np.any(
        canonical_recipes >= len(materials)
    ):
        _corruption("dynamic catalog recipe contains invalid canonical indices")
    if np.any(minimum_counts < key.min_layer_count) or np.any(
        minimum_counts > key.max_layer_count
    ):
        _corruption("dynamic catalog actual layer counts are outside the key range")
    try:
        before_count = int(metadata["candidate_count_before_dedup"])
        after_count = int(metadata["candidate_count_after_dedup"])
        canonical_backing = int(metadata["canonical_backing_material_index"])
    except (KeyError, TypeError, ValueError) as exc:
        _corruption("dynamic catalog count metadata is invalid", cause=exc)
    if before_count < row_count or after_count != row_count:
        _corruption("dynamic catalog candidate counts are inconsistent")
    if (
        np.any(source_indices < 0)
        or np.any(source_indices >= before_count)
        or np.unique(source_indices).shape[0] != row_count
    ):
        _corruption("dynamic catalog source indices are invalid")
    if not 0 <= canonical_backing < len(materials):
        _corruption("dynamic catalog canonical backing index is invalid")
    if (
        metadata.get("canonical_backing_material_descriptor")
        != key.backing_material_descriptor
        or canonical_identities[canonical_backing]
        != key.backing_material_descriptor
    ):
        _corruption("dynamic catalog canonical backing identity is invalid")
    if not np.any(max_reachable):
        _corruption("dynamic catalog has no fixed-maximum reachable candidate")
    if np.any((minimum_counts == key.max_layer_count) & (~max_reachable)):
        _corruption("dynamic catalog maximum-layer candidates are not reachable")
    for row_index, actual_count in enumerate(minimum_counts):
        padding_count = key.max_layer_count - int(actual_count)
        if padding_count and np.any(
            canonical_recipes[row_index, :padding_count] != canonical_backing
        ):
            _corruption("dynamic catalog backing padding is inconsistent")

    user_recipes = canonical_to_user[canonical_recipes]
    catalog = DynamicCandidateCatalog(
        score_srgb=score_srgb,
        score_lab=score_lab,
        print_recipes=user_recipes,
        minimum_actual_layer_counts=minimum_counts,
        max_layer_reachable=max_reachable,
        source_indices=source_indices,
    )
    return CachedDynamicCandidateCatalog(
        catalog=catalog,
        candidate_count_before_dedup=before_count,
    )


def _load_dynamic_candidate_catalog_unlocked(
    *,
    materials: list[MaterialParams],
    key: DynamicCatalogCacheKey,
    path: Path,
) -> CachedDynamicCandidateCatalog | None:
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as loaded:
            if set(loaded.files) != _PAYLOAD_FIELDS:
                _corruption("dynamic catalog payload fields are invalid")
            payload = {
                field: np.array(loaded[field], copy=True)
                for field in _PAYLOAD_FIELDS
                if field != "metadata_json"
            }
            metadata_raw = np.array(loaded["metadata_json"], copy=True)
    except DynamicCatalogCacheCorruptionError:
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        EOFError,
        zipfile.BadZipFile,
        zlib.error,
    ) as exc:
        _corruption("dynamic catalog NPZ cannot be loaded", cause=exc)
    if metadata_raw.dtype != np.uint8 or metadata_raw.ndim != 1:
        _corruption("dynamic catalog metadata_json encoding is invalid")
    try:
        metadata = json.loads(metadata_raw.tobytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        _corruption("dynamic catalog metadata_json is invalid", cause=exc)
    if not isinstance(metadata, dict):
        _corruption("dynamic catalog metadata must be an object")
    return _validated_loaded_catalog(
        payload=payload,
        metadata=metadata,
        materials=materials,
        key=key,
    )


def load_dynamic_candidate_catalog(
    *,
    materials: list[MaterialParams],
    key: DynamicCatalogCacheKey,
    cache_root: str | Path | None = None,
) -> CachedDynamicCandidateCatalog | None:
    """Load and validate one catalog, returning ``None`` only for a miss.

    加载并验证一个目录；仅在文件不存在时返回 ``None``。

    Args:
        materials: Current user-order material palette. 当前用户顺序耗材。
        key: Order-independent catalog identity. 顺序无关目录标识。
        cache_root: Optional cache-root override. 可选缓存根目录。

    Returns:
        CachedDynamicCandidateCatalog | None: Validated/rebound catalog, or
        ``None`` for a true miss. 已验证并重绑的目录；真正未命中时为 ``None``。

    Raises:
        DynamicCatalogCacheCorruptionError: Existing entry is malformed or
            belongs to another key. 已存在条目损坏或键不匹配。
    """

    _validate_materials(materials)
    if key.palette_descriptor != _serialized_palette(materials):
        raise ValueError("cache key does not match the material palette")
    path = _resolve_catalog_record(key, cache_root, register=False)
    if not path.exists():
        return None
    with _DynamicCatalogKeyLock(path, layer_count=key.max_layer_count):
        return _load_dynamic_candidate_catalog_unlocked(
            materials=materials,
            key=key,
            path=path,
        )


def load_or_build_dynamic_candidate_catalog(
    *,
    materials: list[MaterialParams],
    key: DynamicCatalogCacheKey,
    builder: DynamicCatalogBuilder,
    cache_root: str | Path | None = None,
) -> DynamicCatalogCacheResult:
    """Load a catalog or atomically rebuild exactly one missing/corrupt entry.

    加载目录，或原子重建唯一缺失/损坏的条目。

    Args:
        materials: Current user-order material palette. 当前用户顺序耗材。
        key: Order-independent catalog identity. 顺序无关目录标识。
        builder: Zero-argument builder returning a user-order catalog and its
            pre-deduplication row count. 返回用户顺序目录和去重前行数的构建器。
        cache_root: Optional cache-root override. 可选缓存根目录。

    Returns:
        DynamicCatalogCacheResult: Loaded or freshly built catalog plus cache
        diagnostics. 已加载或新构建的目录及缓存诊断。

    Raises:
        DynamicMaterialCandidateError: Cache removal, build, or atomic write
            fails. 缓存移除、构建或原子写入失败。
    """

    _validate_materials(materials)
    if key.palette_descriptor != _serialized_palette(materials):
        raise ValueError("cache key does not match the material palette")
    path = _resolve_catalog_record(key, cache_root, register=True)
    key_id = path.stem
    with _DynamicCatalogKeyLock(path, layer_count=key.max_layer_count):
        rebuilt_corrupt = False
        try:
            loaded = _load_dynamic_candidate_catalog_unlocked(
                materials=materials,
                key=key,
                path=path,
            )
        except DynamicCatalogCacheCorruptionError as exc:
            rebuilt_corrupt = True
            quarantine = path.with_name(
                f"{path.name}.corrupt-{os.getpid()}-{uuid.uuid4().hex}"
            )
            try:
                os.replace(path, quarantine)
            except FileNotFoundError:
                quarantine = None
            except OSError as quarantine_exc:
                raise DynamicMaterialCandidateError(
                    "corrupt dynamic catalog could not be quarantined",
                    layer_count=key.max_layer_count,
                    phase="dynamic_catalog_cache_load",
                ) from quarantine_exc
            _log.warning(
                "Corrupt dynamic material catalog quarantined for rebuild",
                extra={
                    "event": "dynamic_material_catalog_cache_corrupt_rebuild",
                    "error_type": type(exc.__cause__ or exc).__name__,
                    "error_message": str(exc),
                    "cache_key": key_id,
                    "quarantine_name": quarantine.name if quarantine else None,
                    "layer_count": key.max_layer_count,
                },
            )
            loaded = None
        if loaded is not None:
            _log.debug(
                "Dynamic material catalog cache hit",
                extra={
                    "event": "dynamic_material_catalog_cache_hit",
                    "cache_key": key_id,
                    "candidate_count": int(loaded.catalog.score_srgb.shape[0]),
                    "layer_count": key.max_layer_count,
                },
            )
            return DynamicCatalogCacheResult(
                catalog=loaded.catalog,
                candidate_count_before_dedup=loaded.candidate_count_before_dedup,
                cache_hit=True,
                rebuilt_corrupt=False,
            )

        _log.debug(
            "Dynamic material catalog cache miss",
            extra={
                "event": "dynamic_material_catalog_cache_miss",
                "cache_key": key_id,
                "rebuilt_corrupt": rebuilt_corrupt,
                "layer_count": key.max_layer_count,
            },
        )
        _log.debug(
            "Dynamic material catalog build started",
            extra={
                "event": "dynamic_material_catalog_cache_build_init",
                "cache_key": key_id,
                "candidate_budget": key.candidate_budget,
                "min_layer_count": key.min_layer_count,
                "max_layer_count": key.max_layer_count,
            },
        )
        try:
            catalog, before_count = builder()
            payload = _prepare_catalog_payload(
                catalog,
                materials=materials,
                key=key,
                candidate_count_before_dedup=before_count,
            )
            _write_catalog_payload_unlocked(path, payload)
        except Exception as exc:
            diagnostic_error = exc.__cause__ or exc
            failure_phase = (
                exc.phase
                if isinstance(exc, DynamicMaterialCandidateError)
                else "dynamic_catalog_cache_build"
            )
            _log.warning(
                "Dynamic material catalog build failed",
                extra={
                    "event": "dynamic_material_catalog_cache_build_failed",
                    "error_type": type(diagnostic_error).__name__,
                    "error_message": str(diagnostic_error),
                    "cache_key": key_id,
                    "layer_count": key.max_layer_count,
                    "phase": failure_phase,
                    "rebuilt_corrupt": rebuilt_corrupt,
                },
            )
            if isinstance(exc, DynamicMaterialCandidateError):
                raise
            raise DynamicMaterialCandidateError(
                "dynamic candidate catalog build or write failed",
                layer_count=key.max_layer_count,
                phase="dynamic_catalog_cache_build",
            ) from exc
        _log.debug(
            "Dynamic material catalog build completed",
            extra={
                "event": "dynamic_material_catalog_cache_build_done",
                "cache_key": key_id,
                "candidate_count_before_dedup": int(before_count),
                "candidate_count_after_dedup": int(catalog.score_srgb.shape[0]),
                "layer_count": key.max_layer_count,
            },
        )
        return DynamicCatalogCacheResult(
            catalog=catalog,
            candidate_count_before_dedup=int(before_count),
            cache_hit=False,
            rebuilt_corrupt=rebuilt_corrupt,
        )
