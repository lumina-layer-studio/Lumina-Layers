"""Browse a local material bundle and import explicitly selected revisions."""

from __future__ import annotations

import json
import hashlib
import io
import os
import tempfile
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import MATERIALS_DIR, TEMP_DIR
from core.filament_display import filament_display
from core.resource_seed import (
    initialize_seed,
    read_seed_state,
    seed_catalog_signature,
    seed_lock,
    verify_seed_release,
)
from core.single_stage import import_saved_stage_a_material_archives
from core.single_stage import material_files, material_package, material_runs, material_sync

_DEFAULT_SEED_FILENAME = "lumina-materials-seed.zip"
_COLLECTION_MANIFEST = "lumina_material_seed.json"


def _nested_package(archive: zipfile.ZipFile, entry: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """Read one unchanged distribution ZIP, preserving its identity and filenames."""
    relative = material_package._safe_manifest_relative_path(entry.get("path")).as_posix()
    expected_bytes = entry.get("package_bytes")
    if type(expected_bytes) is not int or expected_bytes <= 0 or archive.getinfo(relative).file_size != expected_bytes:
        raise ValueError("Offline material package byte count mismatch")
    payload = archive.read(relative)
    if hashlib.sha256(payload).hexdigest() != str(entry.get("package_sha256", "")).removeprefix("sha256:"):
        raise ValueError("Offline material package checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        material_package._validate_material_zip_resource_limits(bundle, archive_path=relative)
        manifest = json.loads(bundle.read(material_package._MATERIAL_BUNDLE_MANIFEST_FILENAME))
        if (not isinstance(manifest, dict) or manifest.get("kind") != "lumina_material_bundle"
                or manifest.get("schema_version") != material_package._MATERIAL_PACKAGE_SCHEMA_VERSION
                or not isinstance(manifest.get("packages"), list) or len(manifest["packages"]) != 1):
            raise ValueError("Offline material entry needs one distribution revision")
        package = manifest["packages"][0]
        if not isinstance(package, dict) or any(package.get(key) != entry.get(key) for key in (
                "material_id", "revision_id", "content_hash", "channel", "local_directory")):
            raise ValueError("Offline material entry does not match its distribution package")
    return payload, package


def _materials_root_has_user_content(root: Path) -> bool:
    if not root.exists():
        return False
    for child in root.iterdir():
        if child.name.casefold() in material_files.INTERNAL_MATERIAL_ROOT_NAMES:
            continue
        return True
    return False


def _local_seed_path() -> Path:
    configured = os.environ.get("LUMINA_MATERIALS_SEED_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent.parent / "resources/materials" / _DEFAULT_SEED_FILENAME


def _download_seed(seed_url: str) -> Path:
    temp_root = Path(TEMP_DIR)
    temp_root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="lumina_materials_seed_",
        suffix=".zip",
        dir=temp_root,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    timeout_s = float(os.environ.get("LUMINA_MATERIALS_SEED_TIMEOUT_S", "60"))
    try:
        with urllib.request.urlopen(seed_url, timeout=timeout_s) as response:
            with temp_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
    return temp_path


def _resolve_seed_path() -> tuple[Path, str, bool] | None:
    seed_path = _local_seed_path()
    if os.environ.get("LUMINA_MATERIALS_SEED_PATH", "").strip():
        if not seed_path.is_file():
            raise FileNotFoundError(f"Material seed not found: {seed_path}")
        return seed_path, str(seed_path), False

    raw_url = os.environ.get("LUMINA_MATERIALS_SEED_URL", "").strip()
    if raw_url:
        if not raw_url.startswith(("http://", "https://")):
            raise ValueError("Material seed URL must be http:// or https://")
        seed_path = _download_seed(raw_url)
        return seed_path, raw_url, True

    if seed_path.is_file():
        return seed_path, str(seed_path), False
    return None


def install_material_seed_if_needed(
    *,
    materials_dir: str | None = None,
) -> dict[str, Any] | None:
    """Install the configured material seed when the writable library is empty.
    当可写耗材库为空时安装配置的耗材 seed。

    Args:
        materials_dir: Optional writable material library root.
            可选的可写耗材库根目录。

    Returns:
        dict[str, Any] | None: Install summary, or ``None`` when no seed is
            configured or the runtime library already has user content.
            安装摘要；未配置 seed 或运行时已有用户内容时返回 ``None``。
    """
    target_root = Path(materials_dir or MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)
    return initialize_seed(
        state_dir=target_root / "_sync",
        has_content=lambda: _materials_root_has_user_content(target_root),
        install=lambda: _install_material_seed(target_root),
    )


def restore_material_seed(*, materials_dir: str | None = None) -> dict[str, Any]:
    """Explicitly merge bundled revisions without replacing personal archives."""
    target_root = Path(materials_dir or MATERIALS_DIR)
    result = initialize_seed(
        state_dir=target_root / "_sync",
        has_content=lambda: _materials_root_has_user_content(target_root),
        install=lambda: _install_material_seed(target_root), restore=True,
    )
    if result is None:
        raise FileNotFoundError("No material starter resource is available")
    return result


def material_seed_status(*, materials_dir: str | None = None) -> dict[str, Any]:
    """Inspect local seed availability without downloading or installing it."""
    return {
        **read_seed_state(Path(materials_dir or MATERIALS_DIR) / "_sync"),
        "available": _local_seed_path().is_file(),
    }


def _material_catalog_row(archive: zipfile.ZipFile, package: dict[str, Any]) -> dict[str, Any]:
    directory = material_package._safe_manifest_relative_path(package.get("local_directory")).as_posix()
    payload = json.loads(archive.read(f"materials/{directory}/material.json"))
    if not isinstance(payload, dict):
        raise ValueError("Material archive must be a JSON object")
    display = material_package._display_payload_from_material_archive(payload, directory)
    display.update(filament_display(package))
    if isinstance(package.get("display"), dict):
        display.update(package["display"])
    display.update(material_runs.measured_gradient_preview(payload))
    name = material_files._clean_optional_archive_text(display.get("material_name")) or Path(directory).name
    material_type, _ = material_files._resolve_picker_material_type(
        display, material_name=name, relative_directory_name=directory,
    )
    rgb = material_files._safe_rgb_triplet(display.get("estimated_rgb"))
    return {
        "resource_id": package["material_id"],
        "revision_id": package["revision_id"],
        "name": name,
        "brand": material_files._clean_optional_archive_text(display.get("brand")),
        "material_type": material_type,
        "color_mode": None,
        "rgb": rgb if len(rgb) == 3 and all(0 <= value <= 255 for value in rgb) else None,
        "channel": package["channel"],
        "display": filament_display(display),
    }


@lru_cache(maxsize=2)
def _material_seed_entries(
    path: Path, _signature: tuple[Any, ...],
) -> tuple[str | None, list[tuple[dict[str, Any], dict[str, Any]]]]:
    if path.stat().st_size > material_package.material_package_max_archive_bytes():
        raise ValueError("Material collection exceeds the size limit")
    version = verify_seed_release(path, "materials")
    entries = []
    identities: set[tuple[str, str]] = set()
    with zipfile.ZipFile(path) as archive:
        nested = _COLLECTION_MANIFEST in archive.namelist()
        material_package._validate_material_zip_resource_limits(
            archive, archive_path=str(path), max_entries=2002 if nested else None,
        )
        names = [info.filename.rstrip("/").casefold() for info in archive.infolist()]
        if len(names) != len(set(names)):
            raise ValueError("Material collection contains duplicate paths")
        try:
            manifest = json.loads(archive.read(_COLLECTION_MANIFEST if nested else material_package._MATERIAL_BUNDLE_MANIFEST_FILENAME))
        except KeyError as exc:
            raise ValueError("Material collection has no selectable revisions") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("kind") != ("lumina_material_seed" if nested else "lumina_material_bundle")
            or manifest.get("schema_version") != ("1.0" if nested else material_package._MATERIAL_PACKAGE_SCHEMA_VERSION)
        ):
            raise ValueError("Unsupported offline material collection format")
        packages = manifest.get("packages")
        if not isinstance(packages, list) or not packages or len(packages) > 2000:
            raise ValueError("Material collection has no selectable revisions")
        if nested and version and manifest.get("dataset_version") != version:
            raise ValueError("Material collection dataset version does not match its release")
        payload_paths = set()
        for package in packages:
            if not isinstance(package, dict) or package.get("channel") not in {"official", "community"}:
                raise ValueError("Material collection must contain public packages")
            identity = (package.get("material_id"), package.get("revision_id"))
            if not all(isinstance(value, str) and value and value.strip() == value for value in identity):
                raise ValueError("Material collection has an invalid revision identity")
            if identity in identities:
                raise ValueError("Material collection has a missing or duplicate revision identity")
            identities.add(identity)
            if nested:
                payload, original = _nested_package(archive, package)
                if package["path"].casefold() in payload_paths:
                    raise ValueError("Material collection contains duplicate package paths")
                payload_paths.add(package["path"].casefold())
                with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
                    row = _material_catalog_row(bundle, {**original, "display": package.get("display", original.get("display", {}))})
                entries.append((package, row))
            else:
                entries.append((package, _material_catalog_row(archive, package)))
        if nested:
            allowed = {_COLLECTION_MANIFEST, "DATA-LICENSE.md", *(package["path"] for package in packages)}
            if any(not info.is_dir() and info.filename not in allowed for info in archive.infolist()):
                raise ValueError("Material collection contains unlisted payloads")
    return version or material_files._clean_optional_archive_text(manifest.get("dataset_version")), entries


def material_seed_catalog(*, materials_dir: str | None = None) -> dict[str, Any]:
    path = _local_seed_path()
    if not path.is_file():
        return {"items": [], "dataset_version": None}
    version, entries = _material_seed_entries(path, seed_catalog_signature(path, "materials"))
    target_root = Path(materials_dir or MATERIALS_DIR)
    index = material_sync._load_material_sync_index(target_root)
    items = []
    for package, row in entries:
        installed_path = material_sync._installed_material_bundle_revision_path(
            target_root=target_root, package=package, include_revision_history=True, index=index,
        )
        items.append({**row, "installed": installed_path is not None})
    return {"items": items, "dataset_version": version}


def install_material_seed_revision(
    resource_id: str, revision_id: str, *, materials_dir: str | None = None,
) -> dict[str, int]:
    path = _local_seed_path()
    if not path.is_file():
        raise FileNotFoundError("The offline material collection is unavailable")
    _, entries = _material_seed_entries(path, seed_catalog_signature(path, "materials"))
    selected = next((
        (package, row) for package, row in entries
        if row["resource_id"] == resource_id and row["revision_id"] == revision_id
    ), None)
    if selected is None:
        raise FileNotFoundError("This revision is absent from the offline material collection")
    target_root = Path(materials_dir or MATERIALS_DIR)
    with seed_lock(target_root / "_sync"), material_sync._MaterialSyncRefreshFileLock(target_root):
        verify_seed_release(path, "materials")
        try:
            result = _import_seed_entry(path, selected[0], selected[1], target_root)
        except FileNotFoundError as exc:
            raise ValueError("The selected material revision is missing a required file") from exc
    return {"installed_count": len(result.imported_materials)}


def _import_seed_entry(path: Path, package: dict[str, Any], row: dict[str, Any], target_root: Path) -> Any:
    with tempfile.TemporaryDirectory(prefix="lumina-material-selection-") as temporary:
        selected_path = path
        if "path" in package:
            with zipfile.ZipFile(path) as archive:
                payload, _ = _nested_package(archive, package)
            selected_path = Path(temporary) / "selected.zip"
            selected_path.write_bytes(payload)
        return import_saved_stage_a_material_archives(
            archive_path=str(selected_path), materials_dir=str(target_root),
            selected_material_id=row["resource_id"], selected_revision_id=row["revision_id"],
            selected_display=row["display"],
        )


def _install_material_seed(target_root: Path) -> dict[str, Any] | None:
    resolved_seed = _resolve_seed_path()
    if resolved_seed is None:
        return None
    seed_path, seed_source, delete_after_import = resolved_seed
    try:
        dataset_version = verify_seed_release(seed_path, "materials")
        with material_sync._MaterialSyncRefreshFileLock(target_root):
            with zipfile.ZipFile(seed_path) as archive:
                nested = _COLLECTION_MANIFEST in archive.namelist()
            if nested:
                _, entries = _material_seed_entries(seed_path, seed_catalog_signature(seed_path, "materials"))
                imported = []
                for package, row in entries:
                    imported.extend(_import_seed_entry(seed_path, package, row, target_root).imported_materials)
                return {"seed_source": seed_source, "dataset_version": dataset_version,
                        "installed_count": len(imported), "installed_materials": imported}
            result = import_saved_stage_a_material_archives(
                archive_path=str(seed_path),
                materials_dir=str(target_root),
            )
        return {
            "seed_source": seed_source,
            "dataset_version": dataset_version,
            "installed_count": len(result.imported_materials),
            "installed_materials": result.imported_materials,
        }
    finally:
        if delete_after_import:
            try:
                seed_path.unlink()
            except OSError:
                pass
