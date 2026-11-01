"""Material bundle manifests, content hashes, and ZIP validation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Any

from . import material_files

DEFAULT_MATERIAL_PACKAGE_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024

DEFAULT_MATERIAL_PACKAGE_MAX_ZIP_ENTRIES = 512

DEFAULT_MATERIAL_PACKAGE_MAX_ZIP_ENTRY_BYTES = 50 * 1024 * 1024

DEFAULT_MATERIAL_PACKAGE_MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024

DEFAULT_MATERIAL_PACKAGE_MAX_COMPRESSION_RATIO = 100

_MATERIAL_EXPORT_MANIFEST_FILENAME = "lumina_material_export.json"

_MATERIAL_BUNDLE_MANIFEST_FILENAME = "lumina_material_bundle.json"

_MATERIAL_PACKAGE_SCHEMA_VERSION = "2.0"

_MATERIAL_LOCAL_ONLY_FILENAMES = frozenset({"usage_stats.json"})

_MATERIAL_LOCAL_ONLY_DIRNAMES = frozenset({"_solver_cache"})


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def material_package_max_archive_bytes() -> int:
    """Return the compressed material-package byte limit.
    返回耗材包压缩归档的字节上限。
    """
    return _positive_int_env(
        "LUMINA_MATERIAL_PACKAGE_MAX_ARCHIVE_BYTES",
        DEFAULT_MATERIAL_PACKAGE_MAX_ARCHIVE_BYTES,
    )


def _material_package_zip_limits() -> dict[str, int]:
    return {
        "max_entries": _positive_int_env(
            "LUMINA_MATERIAL_PACKAGE_MAX_ZIP_ENTRIES",
            DEFAULT_MATERIAL_PACKAGE_MAX_ZIP_ENTRIES,
        ),
        "max_entry_bytes": _positive_int_env(
            "LUMINA_MATERIAL_PACKAGE_MAX_ZIP_ENTRY_BYTES",
            DEFAULT_MATERIAL_PACKAGE_MAX_ZIP_ENTRY_BYTES,
        ),
        "max_uncompressed_bytes": _positive_int_env(
            "LUMINA_MATERIAL_PACKAGE_MAX_UNCOMPRESSED_BYTES",
            DEFAULT_MATERIAL_PACKAGE_MAX_UNCOMPRESSED_BYTES,
        ),
        "max_compression_ratio": _positive_int_env(
            "LUMINA_MATERIAL_PACKAGE_MAX_COMPRESSION_RATIO",
            DEFAULT_MATERIAL_PACKAGE_MAX_COMPRESSION_RATIO,
        ),
    }


def _validate_material_zip_resource_limits(
    archive: zipfile.ZipFile,
    *,
    archive_path: str,
) -> None:
    limits = _material_package_zip_limits()
    infos = archive.infolist()
    if len(infos) > limits["max_entries"]:
        raise ValueError(
            "Material package ZIP has too many entries: "
            f"{len(infos)} > {limits['max_entries']}"
        )
    total_uncompressed_bytes = 0
    for member in infos:
        if member.is_dir():
            continue
        if member.file_size > limits["max_entry_bytes"]:
            raise ValueError(
                "Material package ZIP entry exceeds maximum size: "
                f"{member.filename}"
            )
        total_uncompressed_bytes += member.file_size
        if total_uncompressed_bytes > limits["max_uncompressed_bytes"]:
            raise ValueError(
                "Material package ZIP uncompressed size exceeds maximum: "
                f"{archive_path}"
            )
        compressed_size = max(int(member.compress_size or 0), 1)
        if member.file_size / compressed_size > limits["max_compression_ratio"]:
            raise ValueError(
                "Material package ZIP compression ratio is too high: "
                f"{member.filename}"
            )


def _is_local_only_material_file(relative_path: Path) -> bool:
    if relative_path.name in _MATERIAL_LOCAL_ONLY_FILENAMES:
        return True
    return any(part in _MATERIAL_LOCAL_ONLY_DIRNAMES for part in relative_path.parts)


def _material_bundle_file_role(relative_path: Path, stage_a_relative_path: Path) -> str:
    if relative_path.as_posix() == "material.json":
        return "material_archive"
    if relative_path.as_posix() == stage_a_relative_path.as_posix():
        return "stage_a_parameters"
    return "sidecar"


def _material_content_hash_from_file_records(
    file_records: list[dict[str, Any]],
) -> str:
    required_records = [
        record
        for record in file_records
        if str(record.get("role") or "") in {"material_archive", "stage_a_parameters"}
    ]
    logical_lines = []
    for record in sorted(required_records, key=lambda item: str(item.get("role") or "")):
        role = str(record.get("role") or "")
        logical_path = (
            "material.json"
            if role == "material_archive"
            else Path(str(record.get("path") or "")).name
        )
        logical_lines.append(f"{logical_path}:{record['sha256']}")
    return f"sha256:{_sha256_bytes(chr(10).join(logical_lines).encode('utf-8'))}"


def _material_package_identity(
    *,
    relative_directory_name: str,
    material_name: str,
    content_hash: str,
    existing_material_id: Any = None,
) -> tuple[str, str]:
    existing_id = str(existing_material_id or "").strip()
    if existing_id:
        material_id = existing_id
    else:
        material_seed = f"{relative_directory_name}\n{material_name}"
        material_id = f"mat_{_sha256_bytes(material_seed.encode('utf-8'))[:26]}"
    revision_id = f"rev_{content_hash.removeprefix('sha256:')[:26]}"
    return material_id, revision_id


def _display_payload_from_material_archive(
    archive_payload: dict[str, Any],
    relative_directory_name: str,
) -> dict[str, str]:
    path_parts = Path(relative_directory_name).parts
    fallback_brand = path_parts[0] if len(path_parts) > 1 else ""
    fallback_name = path_parts[-1] if path_parts else relative_directory_name
    display: dict[str, Any] = {
        "brand": str(archive_payload.get("brand") or fallback_brand),
        "material_name": str(archive_payload.get("material_name") or fallback_name),
    }
    for source_key, target_key in (
        ("material_type", "material_type"),
        ("color_name", "color_name"),
    ):
        value = archive_payload.get(source_key)
        if isinstance(value, str) and value.strip():
            display[target_key] = value.strip()
    material_summary = archive_payload.get("material_summary")
    if isinstance(material_summary, dict):
        estimated_rgb = material_files._safe_rgb_triplet(material_summary.get("estimated_rgb"))
        if len(estimated_rgb) == 3 and all(0 <= channel <= 255 for channel in estimated_rgb):
            display["estimated_rgb"] = estimated_rgb
    return display


def _build_material_bundle_package_manifest(
    *,
    target_root: Path,
    material_dir: Path,
) -> tuple[dict[str, Any], list[tuple[Path, str]]]:
    relative_directory_name = material_files._relative_directory_name(target_root, material_dir)
    material_archive_path = material_dir / "material.json"
    archive_payload = material_files._load_json_object(
        material_archive_path,
        "Saved material archive is not valid UTF-8 JSON",
    )
    stage_a_params_path = material_files._resolve_stage_a_params_path(material_dir, archive_payload)
    stage_a_relative_path = stage_a_params_path.relative_to(material_dir)
    file_records: list[dict[str, Any]] = []
    files_to_write: list[tuple[Path, str]] = []
    package_files = sorted(path for path in material_dir.rglob("*") if path.is_file())
    for file_path in package_files:
        material_relative_path = file_path.relative_to(material_dir)
        if _is_local_only_material_file(material_relative_path):
            continue
        zip_path = (
            Path("materials")
            .joinpath(relative_directory_name)
            .joinpath(material_relative_path)
            .as_posix()
        )
        role = _material_bundle_file_role(material_relative_path, stage_a_relative_path)
        file_records.append(
            {
                "path": zip_path,
                "role": role,
                "sha256": _sha256_file(file_path),
                "bytes": int(file_path.stat().st_size),
                "required": role in {"material_archive", "stage_a_parameters"},
            }
        )
        files_to_write.append((file_path, zip_path))

    roles = {str(record.get("role") or "") for record in file_records}
    if "material_archive" not in roles or "stage_a_parameters" not in roles:
        raise FileNotFoundError(
            f"Saved material archive is missing required files: {relative_directory_name}"
        )
    content_hash = _material_content_hash_from_file_records(file_records)
    display = _display_payload_from_material_archive(
        archive_payload,
        relative_directory_name,
    )
    material_id, revision_id = _material_package_identity(
        relative_directory_name=relative_directory_name,
        material_name=display["material_name"],
        content_hash=content_hash,
        existing_material_id=archive_payload.get("material_id"),
    )
    return (
        {
            "material_id": material_id,
            "revision_id": revision_id,
            "content_hash": content_hash,
            "channel": "manual",
            "visibility": "private",
            "local_directory": relative_directory_name,
            "display": display,
            "files": file_records,
            "compatibility": {
                "min_app_version": "0.0.0",
                "material_schema_version": str(
                    archive_payload.get("schema_version")
                    or archive_payload.get("material_schema_version")
                    or "1"
                ),
            },
        },
        files_to_write,
    )


def _safe_extract_material_zip(zip_path: str, dest_dir: Path) -> Path:
    archive_size = Path(zip_path).stat().st_size
    max_archive_bytes = material_package_max_archive_bytes()
    if archive_size > max_archive_bytes:
        raise ValueError(
            "Material package ZIP exceeds maximum size: "
            f"{archive_size} > {max_archive_bytes}"
        )
    resolved_dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            _validate_material_zip_resource_limits(
                archive,
                archive_path=zip_path,
            )
            for member in archive.infolist():
                raw_member_name = member.filename.strip()
                normalized_member_name = raw_member_name.replace("\\", "/")
                windows_member_name = PureWindowsPath(raw_member_name)
                member_name = Path(normalized_member_name)
                if (
                    windows_member_name.is_absolute()
                    or windows_member_name.drive
                    or windows_member_name.anchor
                    or normalized_member_name.startswith("/")
                    or member_name.is_absolute()
                    or ".." in member_name.parts
                ):
                    raise ValueError(f"Unsafe zip entry: {member.filename}")
                member_path = (resolved_dest_dir / member_name).resolve()
                try:
                    member_path.relative_to(resolved_dest_dir)
                except ValueError as exc:
                    raise ValueError(f"Unsafe zip entry: {member.filename}") from exc
            archive.extractall(resolved_dest_dir)
    except zipfile.BadZipFile as exc:
        raise ValueError("Malformed ZIP archive") from exc

    # Manifest paths are relative to the package root. Do not unwrap its
    # materials directory: a material's own parent may also be named materials.
    if any(
        (resolved_dest_dir / filename).is_file()
        for filename in (
            _MATERIAL_BUNDLE_MANIFEST_FILENAME,
            _MATERIAL_EXPORT_MANIFEST_FILENAME,
        )
    ):
        return resolved_dest_dir

    children = [p for p in resolved_dest_dir.iterdir() if p.is_dir()]
    if len(children) == 1 and not any(p.is_dir() for p in resolved_dest_dir.iterdir() if p != children[0]):
        return children[0]
    return resolved_dest_dir


def _load_material_export_manifest(extracted_root: Path) -> dict[str, Any] | None:
    manifest_path = extracted_root / _MATERIAL_EXPORT_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    manifest = material_files._load_json_object(
        manifest_path,
        "Material export manifest is not valid UTF-8 JSON",
    )
    if str(manifest.get("kind") or "") != "lumina_material_export":
        raise ValueError("Material export manifest is invalid")
    return manifest


def _load_material_bundle_manifest(extracted_root: Path) -> dict[str, Any] | None:
    manifest_path = extracted_root / _MATERIAL_BUNDLE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    manifest = material_files._load_json_object(
        manifest_path,
        "Material bundle manifest is not valid UTF-8 JSON",
    )
    if str(manifest.get("kind") or "") != "lumina_material_bundle":
        raise ValueError("Material bundle manifest is invalid")
    if str(manifest.get("schema_version") or "") != _MATERIAL_PACKAGE_SCHEMA_VERSION:
        raise ValueError("Material bundle manifest schema_version is unsupported")
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Material bundle manifest is missing packages")
    return manifest


def _safe_manifest_relative_path(raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Material bundle file path must be a non-empty string")
    normalized = raw_path.strip().replace("\\", "/")
    windows_relative = PureWindowsPath(raw_path.strip())
    if (
        windows_relative.is_absolute()
        or windows_relative.drive
        or windows_relative.anchor
        or normalized.startswith("/")
    ):
        raise ValueError(f"Unsafe material bundle file path: {raw_path}")
    parts = [segment for segment in normalized.split("/") if segment]
    if not parts or any(segment in {".", ".."} for segment in parts):
        raise ValueError(f"Unsafe material bundle file path: {raw_path}")
    relative = Path(*parts)
    if (
        relative.is_absolute()
        or relative.drive
        or relative.anchor
        or ".." in relative.parts
    ):
        raise ValueError(f"Unsafe material bundle file path: {raw_path}")
    return relative


def _verify_material_bundle_package(
    *,
    extracted_root: Path,
    package: dict[str, Any],
) -> None:
    material_id = str(package.get("material_id") or "")
    revision_id = str(package.get("revision_id") or "")
    if not material_id or not revision_id:
        raise ValueError("Material bundle package is missing material_id or revision_id")
    files = package.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"Material bundle package {material_id} is missing files")

    normalized_local_directory = material_files._normalize_relative_directory_name(
        str(package.get("local_directory") or "")
    )
    material_dir_relative = Path("materials").joinpath(
        *normalized_local_directory.split("/")
    )
    expected_material_archive_path = material_dir_relative / "material.json"

    required_roles = {"material_archive", "stage_a_parameters"}
    parsed_records: list[tuple[dict[str, Any], Path, str]] = []
    required_role_paths: dict[str, Path] = {}
    for record in files:
        if not isinstance(record, dict):
            raise ValueError(f"Material bundle package {material_id} has invalid file record")
        relative_path = _safe_manifest_relative_path(record.get("path"))
        role = str(record.get("role") or "")
        if role in required_roles:
            if role in required_role_paths:
                raise ValueError(
                    f"Material bundle package {material_id} has duplicate required role: {role}"
                )
            required_role_paths[role] = relative_path
        parsed_records.append((record, relative_path, role))

    if required_roles - set(required_role_paths):
        raise ValueError(f"Material bundle package {material_id} is missing required roles")

    material_archive_role_path = required_role_paths["material_archive"]
    if material_archive_role_path.as_posix() != expected_material_archive_path.as_posix():
        raise ValueError(
            "Material bundle package "
            f"{material_id} material_archive role must point to "
            f"{expected_material_archive_path.as_posix()}"
        )

    material_archive_file_path = extracted_root / expected_material_archive_path
    if not material_archive_file_path.is_file():
        raise FileNotFoundError(
            "Material bundle file is missing: "
            f"{expected_material_archive_path.as_posix()}"
        )
    archive_payload = material_files._load_json_object(
        material_archive_file_path,
        "Material bundle material archive is not valid UTF-8 JSON",
    )
    expected_stage_a_path = material_dir_relative / (
        material_files._resolve_stage_a_params_path(
            material_archive_file_path.parent,
            archive_payload,
        ).relative_to(material_archive_file_path.parent.resolve())
    )
    stage_a_role_path = required_role_paths["stage_a_parameters"]
    if stage_a_role_path.as_posix() != expected_stage_a_path.as_posix():
        raise ValueError(
            "Material bundle package "
            f"{material_id} stage_a_parameters role must point to "
            f"{expected_stage_a_path.as_posix()}"
        )

    normalized_records: list[dict[str, Any]] = []
    for record, relative_path, role in parsed_records:
        file_path = extracted_root / relative_path
        if not file_path.is_file():
            raise FileNotFoundError(f"Material bundle file is missing: {relative_path.as_posix()}")
        expected_size = record.get("bytes")
        if expected_size is not None and int(expected_size) != int(file_path.stat().st_size):
            raise ValueError(f"Material bundle file size mismatch: {relative_path.as_posix()}")
        expected_hash = str(record.get("sha256") or "")
        actual_hash = _sha256_file(file_path)
        if expected_hash != actual_hash:
            raise ValueError(f"Material bundle file hash mismatch: {relative_path.as_posix()}")
        normalized_records.append(
            {
                "path": relative_path.as_posix(),
                "role": role,
                "sha256": actual_hash,
                "bytes": int(file_path.stat().st_size),
                "required": bool(record.get("required")),
            }
        )

    expected_content_hash = str(package.get("content_hash") or "")
    actual_content_hash = _material_content_hash_from_file_records(normalized_records)
    if expected_content_hash != actual_content_hash:
        raise ValueError(f"Material bundle content hash mismatch: {material_id}")


def validate_material_bundle_archive(*, archive_path: str) -> dict[str, Any]:
    """Validate a v2 material bundle ZIP without importing its contents.
    校验 v2 耗材 bundle ZIP，但不导入其中内容。

    Args:
        archive_path: ZIP archive path to validate. (要校验的 ZIP 路径)

    Returns:
        dict[str, Any]: Parsed bundle manifest. (解析后的 bundle manifest)
    """
    extract_root = Path(
        tempfile.mkdtemp(prefix="material_bundle_validate_", dir=material_files.TEMP_DIR)
    )
    try:
        extracted_root = _safe_extract_material_zip(archive_path, extract_root)
        manifest_root = extracted_root
        if not (manifest_root / _MATERIAL_BUNDLE_MANIFEST_FILENAME).is_file():
            if (extract_root / _MATERIAL_BUNDLE_MANIFEST_FILENAME).is_file():
                manifest_root = extract_root
        bundle_manifest = _load_material_bundle_manifest(manifest_root)
        if bundle_manifest is None:
            raise ValueError("Material bundle manifest is invalid")
        raw_packages = bundle_manifest["packages"]
        for raw_package in raw_packages:
            if not isinstance(raw_package, dict):
                raise ValueError("Material bundle manifest contains invalid package")
            _verify_material_bundle_package(
                extracted_root=manifest_root,
                package=raw_package,
            )
        return json.loads(json.dumps(bundle_manifest, ensure_ascii=False))
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


def _local_material_content_hash(
    material_dir: Path,
    archive_payload: dict[str, Any],
) -> str | None:
    archive_path = material_dir / "material.json"
    try:
        stage_a_path = material_files._resolve_stage_a_params_path(material_dir, archive_payload)
    except ValueError:
        return None
    if not archive_path.is_file() or not stage_a_path.is_file():
        return None
    file_records = [
        {
            "path": archive_path.name,
            "role": "material_archive",
            "sha256": _sha256_file(archive_path),
        },
        {
            "path": stage_a_path.name,
            "role": "stage_a_parameters",
            "sha256": _sha256_file(stage_a_path),
        },
    ]
    return _material_content_hash_from_file_records(file_records)


def _copy_material_bundle_package_files(
    *,
    manifest_root: Path,
    staged_material_dir: Path,
    destination_dir: Path,
    package: dict[str, Any],
) -> None:
    # Compare aliases in one canonical namespace without relaxing containment.
    manifest_root = manifest_root.resolve()
    staged_material_dir = staged_material_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=False)
    raw_files = package.get("files")
    if not isinstance(raw_files, list):
        raise ValueError("Material bundle package files must be a list")
    for raw_record in raw_files:
        if not isinstance(raw_record, dict):
            raise ValueError("Material bundle package contains invalid file record")
        source_path = manifest_root / _safe_manifest_relative_path(raw_record.get("path"))
        try:
            material_relative_path = source_path.relative_to(staged_material_dir)
            # Preserve the manifest path check and reject symlink escapes too.
            source_path.resolve().relative_to(staged_material_dir)
        except ValueError as exc:
            raise ValueError(
                f"Material bundle file is outside material directory: {raw_record.get('path')}"
            ) from exc
        if _is_local_only_material_file(material_relative_path):
            continue
        target_path = destination_dir / material_relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
