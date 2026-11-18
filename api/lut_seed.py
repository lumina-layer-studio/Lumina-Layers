"""Browse a local LUT collection and install explicitly selected revisions."""

from __future__ import annotations

import json
import os
import zipfile
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

import msgpack
import numpy as np

from api.services import lut_registry_sync as sync
from core.filament_display import filament_display, filament_preview
from core.lut_board_preview import lut_board_preview
from core.resource_seed import (
    initialize_seed,
    read_seed_state,
    seed_catalog_signature,
    seed_lock,
    verify_seed_release,
)
from core.single_stage.material_files import _resolve_picker_material_type
from utils.lut_manager import LUTManager

_MANIFEST = "lumina_lut_seed.json"
_MAX_SEED_BYTES = 256 * 1024 * 1024
_SEED_SOURCE = "https://github.com/lumina-layer-studio/Lumina-materials"


def _seed_path() -> Path:
    configured = os.environ.get("LUMINA_LUTS_SEED_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent.parent / "resources/luts/lumina-luts-seed.zip"


def lut_seed_status() -> dict[str, Any]:
    return {**read_seed_state(LUTManager.cloud_lut_sync_dir()), "available": _seed_path().is_file()}


def _has_user_luts() -> bool:
    roots = [LUTManager.cloud_lut_dir(), LUTManager.custom_lut_dir(), Path(LUTManager.LUT_PRESET_DIR)]
    return any(
        path.suffix.lower() in sync.ALLOWED_LUT_EXTENSIONS
        for root in roots if root.exists()
        for path in root.rglob("*") if path.is_file() and "_sync" not in path.relative_to(root).parts
    )


def _verified_release(path: Path) -> str | None:
    if path.stat().st_size > _MAX_SEED_BYTES:
        raise ValueError("LUT starter resource exceeds the size limit")
    return verify_seed_release(path, "luts")


def _collection_manifest(archive: zipfile.ZipFile, release_version: str | None) -> dict[str, Any]:
    infos = archive.infolist()
    names: set[str] = set()
    total = 0
    for info in infos:
        if sync._is_special_zip_entry(info) or not sync._is_safe_zip_path(info.filename):
            raise ValueError("LUT starter resource contains an unsafe path")
        normalized = info.filename.rstrip("/").casefold()
        if normalized in names:
            raise ValueError("LUT starter resource contains duplicate paths")
        names.add(normalized)
        total += info.file_size
    if total > _MAX_SEED_BYTES:
        raise ValueError("LUT starter resource exceeds the expanded size limit")
    if archive.getinfo(_MANIFEST).file_size > sync.MAX_LUT_MANIFEST_BYTES:
        raise ValueError("LUT starter manifest exceeds the size limit")
    manifest = json.loads(archive.read(_MANIFEST))
    if (
        not isinstance(manifest, dict)
        or manifest.get("kind") != "lumina_lut_seed"
        or manifest.get("schema_version") != "1.0"
    ):
        raise ValueError("Unsupported LUT starter resource format")
    if release_version and manifest.get("dataset_version") != release_version:
        raise ValueError("LUT starter resource dataset version does not match its release")
    entries = manifest.get("packages")
    if not isinstance(entries, list) or not entries or len(entries) > 1000:
        raise ValueError("LUT starter resource needs a bounded package list")
    identities: set[str] = set()
    payloads: set[str] = set()
    destinations: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("channel") not in {"official", "community"}:
            raise ValueError("LUT starter resources must use public channels")
        identity = (entry.get("lut_id"), entry.get("revision_id"))
        if not all(isinstance(value, str) and value and value.strip() == value for value in identity):
            raise ValueError("LUT starter resource identity must be a string")
        key = sync._record_key(entry)
        local_path = sync._canonical_cloud_local_path(entry.get("local_path"))
        if not local_path or key in identities or local_path.casefold() in destinations:
            raise ValueError("LUT starter resource has duplicate or unsafe identities")
        identities.add(key)
        destinations.add(local_path.casefold())
        package_path = entry.get("path")
        if (
            not isinstance(package_path, str)
            or not sync._is_safe_zip_path(package_path)
            or package_path in payloads
        ):
            raise ValueError("LUT starter resource package path is invalid")
        payloads.add(package_path)
        expected_bytes = sync._required_package_bytes(entry)
        if archive.getinfo(package_path).file_size != expected_bytes:
            raise ValueError("LUT starter resource package byte count mismatch")
        sync._required_package_sha256(entry)
        sync._required_content_hash(entry.get("content_hash"), "seed")
    actual_files = {info.filename for info in infos if not info.is_dir()}
    if actual_files - {"DATA-LICENSE.md"} != {_MANIFEST, *payloads}:
        raise ValueError("LUT starter resource contains unlisted payloads")
    return manifest


def _package_metadata(entry: dict[str, Any], package: bytes) -> dict[str, Any]:
    sync._validate_expected_sha256(package, sync._required_package_sha256(entry), "LUT starter package")
    with zipfile.ZipFile(BytesIO(package)) as bundle:
        if bundle.getinfo(sync.MANIFEST_NAME).file_size > sync.MAX_LUT_MANIFEST_BYTES:
            raise ValueError("LUT package manifest exceeds the size limit")
        metadata = json.loads(bundle.read(sync.MANIFEST_NAME))
        if not isinstance(metadata, dict):
            raise ValueError("LUT package manifest must be a JSON object")
        for field in ("lut_id", "revision_id", "content_hash", "channel", "local_path"):
            if metadata.get(field) != entry.get(field):
                raise ValueError(f"LUT starter package {field} does not match its manifest")
        display = {
            **filament_display(metadata),
            **filament_display(metadata.get("display")),
            **filament_display(entry),
            **filament_display(entry.get("display")),
        }
        if "palette_rgb" not in display or "lut_board_preview" not in display:
            display = {**_bundled_lut_preview(bundle, metadata), **display}
        file_hash = sync._required_lut_file_sha256(sync._manifest_lut_file(metadata))
    return {**metadata, **entry, "display": display, "lut_file_sha256": file_hash}


def _entry_board_colors(raw: object) -> np.ndarray:
    entries = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or not entries:
        return np.empty((0, 3), dtype=np.uint8)
    if any(not isinstance(entry, dict) for entry in entries):
        return np.empty((0, 3), dtype=np.uint8)
    colors = [entry.get("rgb") for entry in entries]
    # A keyed file can store Lab alone. Convert those entries without opening
    # companion model files or shifting the positions of subsequent RGB rows.
    if any(color is None for color in colors):
        from core.native_reference import standard_lab_to_rgb_uint8

        missing = [i for i, color in enumerate(colors) if color is None]
        try:
            labs = np.asarray([entries[i].get("lab") for i in missing], dtype=np.float32)
        except (TypeError, ValueError, OverflowError):
            return np.empty((0, 3), dtype=np.uint8)
        if labs.shape != (len(missing), 3) or not np.isfinite(labs).all():
            return np.empty((0, 3), dtype=np.uint8)
        for index, color in zip(missing, standard_lab_to_rgb_uint8(labs).tolist(), strict=True):
            colors[index] = color
    try:
        array = np.asarray(colors)
    except ValueError:
        return np.empty((0, 3), dtype=np.uint8)
    return array if array.shape == (len(entries), 3) else np.empty((0, 3), dtype=np.uint8)


def _bundled_lut_preview(bundle: zipfile.ZipFile, manifest: dict[str, Any]) -> dict[str, Any]:
    file = sync._manifest_lut_file(manifest)
    name = sync._file_entry_path(file)
    suffix = Path(name).suffix.lower()
    info = bundle.getinfo(name)
    if suffix not in sync.ALLOWED_LUT_EXTENSIONS or info.file_size > sync.MAX_LUT_MANIFEST_BYTES:
        return {}
    if info.file_size != sync._required_lut_file_bytes(file):
        raise ValueError("LUT starter payload byte count mismatch")
    data = bundle.read(info)
    sync._validate_expected_sha256(data, sync._required_lut_file_sha256(file), "LUT starter payload")
    raw: Any = {}
    if suffix in {".json", ".msgpack"}:
        raw = json.loads(data) if suffix == ".json" else msgpack.unpackb(data, raw=False)
        colors = _entry_board_colors(raw)
    elif suffix == ".npy":
        colors = np.load(BytesIO(data), allow_pickle=False)
    else:  # NPZ previews only need the color plane and optional embedded metadata.
        colors = np.empty((0, 3), dtype=np.uint8)
        with zipfile.ZipFile(BytesIO(data)) as contents:
            names = contents.namelist()
            if "rgb.npy" in names and contents.getinfo("rgb.npy").file_size <= sync.MAX_LUT_MANIFEST_BYTES:
                colors = np.load(BytesIO(contents.read("rgb.npy")), allow_pickle=False)
            if "metadata_json.npy" in names and contents.getinfo("metadata_json.npy").file_size <= sync.MAX_LUT_MANIFEST_BYTES:
                value = np.load(BytesIO(contents.read("metadata_json.npy")), allow_pickle=False)
                if not value.shape and value.dtype.kind in {"U", "S"}:
                    raw = json.loads(value.item())
    metadata = raw if isinstance(raw, dict) else {}
    compatibility = manifest.get("compatibility") if isinstance(manifest.get("compatibility"), dict) else {}
    mode = metadata.get("color_mode") or compatibility.get("color_mode")
    return {**filament_preview(metadata), **lut_board_preview(colors, mode, metadata)}


@lru_cache(maxsize=2)
def _lut_seed_entries(path: Path, _signature: tuple[Any, ...]) -> tuple[str | None, list[dict[str, Any]]]:
    release_version = _verified_release(path)
    with zipfile.ZipFile(path) as archive:
        manifest = _collection_manifest(archive, release_version)
        entries = [
            _package_metadata(entry, archive.read(entry["path"])) for entry in manifest["packages"]
        ]
    return sync._clean_display_text(manifest.get("dataset_version")), entries


def lut_seed_catalog() -> dict[str, Any]:
    path = _seed_path()
    if not path.is_file():
        return {"items": [], "dataset_version": None}
    version, entries = _lut_seed_entries(path, seed_catalog_signature(path, "luts"))
    index = sync.read_installed_index()
    items = []
    for entry in entries:
        display = entry["display"]
        compatibility = entry.get("compatibility") if isinstance(entry.get("compatibility"), dict) else {}
        name = sync._catalog_item_display_name(entry) or entry["lut_id"]
        material_type, _ = _resolve_picker_material_type(
            display, material_name=name, relative_directory_name=entry["local_path"],
        )
        items.append({
            "resource_id": entry["lut_id"],
            "revision_id": entry["revision_id"],
            "name": name,
            "brand": sync._clean_display_text(display.get("manufacturer") or display.get("brand")),
            "material_type": material_type,
            "color_mode": sync._clean_display_text(compatibility.get("color_mode")),
            "installed": sync._catalog_item_local_presence(entry, index)["local_exists"],
            "channel": entry["channel"],
            "display": display,
        })
    return {"items": items, "dataset_version": version}


def add_matching_seed_previews(catalog: dict[str, Any]) -> dict[str, Any]:
    """Older online catalogs can reuse artwork from identical bytes in the offline bundle."""
    items = catalog.get("items") or []
    path = _seed_path()
    if not path.is_file() or not any(
        item.get("content_hash") and not (item.get("display") or {}).get("lut_board_available")
        and "lut_board_preview" not in (item.get("display") or {}) for item in items
    ):
        return catalog
    try:
        _, entries = _lut_seed_entries(path, seed_catalog_signature(path, "luts"))
    except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile, msgpack.UnpackException, sync.LutRegistryPackageError):
        # An optional offline bundle cannot prevent browsing a working online catalog.
        return catalog
    previews = {}
    for entry in entries:
        display = entry["display"]
        if "lut_board_preview" in display:
            preview = {key: display[key] for key in ("lut_board_preview", "palette_rgb") if key in display}
            for digest in (entry["content_hash"], entry["lut_file_sha256"]):
                previews[sync._hex_digest(digest)] = preview
    rows = []
    for item in items:
        match = previews.get(sync._hex_digest(item.get("content_hash")))
        rows.append({**item, "display": {**match, **(item.get("display") or {})}}
                    if match and not (item.get("display") or {}).get("lut_board_available") else item)
    return {**catalog, "items": rows}


def _verified_packages(path: Path) -> tuple[dict[str, Any], list[tuple[dict[str, Any], bytes]]]:
    """Validate the entire collection before an explicit whole-library restore."""
    release_version = _verified_release(path)
    verified = []
    with zipfile.ZipFile(path) as archive:
        manifest = _collection_manifest(archive, release_version)
        for entry in manifest["packages"]:
            package = archive.read(entry["path"])
            metadata = _package_metadata(entry, package)
            sync._read_lut_from_package(
                package, sync._required_content_hash(entry.get("content_hash"), "seed"),
                local_path=entry["local_path"],
            )
            verified.append((metadata, package))
    return manifest, verified


def install_lut_seed_revision(resource_id: str, revision_id: str) -> dict[str, int]:
    path = _seed_path()
    if not path.is_file():
        raise FileNotFoundError("The offline LUT collection is unavailable")
    release_version = _verified_release(path)
    with zipfile.ZipFile(path) as archive:
        manifest = _collection_manifest(archive, release_version)
        entry = next((
            item for item in manifest["packages"]
            if item["lut_id"] == resource_id and item["revision_id"] == revision_id
        ), None)
        if entry is None:
            raise FileNotFoundError("This revision is absent from the offline LUT collection")
        package = archive.read(entry["path"])
        metadata = _package_metadata(entry, package)
    with seed_lock(LUTManager.cloud_lut_sync_dir()):
        previous = sync.read_installed_index()["luts"].get(sync._record_key(entry))
        record = sync.install_lut_archive_bytes(metadata, package, source_url=_SEED_SOURCE)
    return {"installed_count": int(previous != record)}


def _install() -> dict[str, Any] | None:
    path = _seed_path()
    if not path.is_file():
        if os.environ.get("LUMINA_LUTS_SEED_PATH", "").strip():
            raise FileNotFoundError("Configured LUT starter resource was not found")
        return None
    manifest, packages = _verified_packages(path)
    count = 0
    records = []
    for entry, package in packages:
        previous = sync.read_installed_index().get("luts", {}).get(sync._record_key(entry), {})
        record = sync.install_lut_archive_bytes(
            entry, package,
            source_url=_SEED_SOURCE,
        )
        count += int(record != previous)
        records.append(record)
    return {"seed_source": str(path), "dataset_version": manifest.get("dataset_version"),
            "installed_count": count, "installed_luts": records}


def install_lut_seed_if_needed() -> dict[str, Any] | None:
    return initialize_seed(state_dir=LUTManager.cloud_lut_sync_dir(), has_content=_has_user_luts, install=_install)


def restore_lut_seed() -> dict[str, Any]:
    result = initialize_seed(state_dir=LUTManager.cloud_lut_sync_dir(), has_content=_has_user_luts, install=_install, restore=True)
    if result is None:
        raise FileNotFoundError("No LUT starter resource is available")
    return result
