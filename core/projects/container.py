"""Secure ZIP container I/O for `.lum` project revisions.

`.lum` 工程修订的安全 ZIP 容器读写。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import tempfile
import unicodedata
import zipfile
from typing import Any

from .errors import (
    ProjectFormatError,
    ProjectResourceLimitError,
    ProjectSecurityError,
    ProjectValidationError,
)
from .schema import (
    AssetBlob,
    PROJECT_CONTAINER_VERSION,
    PROJECT_FORMAT,
    PROJECT_SCHEMA_VERSION,
    ProjectSnapshot,
    WorkflowDocument,
)

_CANONICAL_JSON_KWARGS = {
    "ensure_ascii": False,
    "sort_keys": True,
    "separators": (",", ":"),
    "allow_nan": False,
}


@dataclass(frozen=True)
class ProjectLimits:
    """Bounded package-reading limits.

    工程包读取资源上限。
    """

    max_archive_bytes: int = 512 * 1024 * 1024
    max_entries: int = 4096
    max_member_bytes: int = 256 * 1024 * 1024
    max_total_uncompressed_bytes: int = 1024 * 1024 * 1024
    max_json_bytes: int = 32 * 1024 * 1024
    max_thumbnail_pixels: int = 16 * 1024 * 1024


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, **_CANONICAL_JSON_KWARGS).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProjectFormatError("project JSON is not canonicalizable") from exc


def _normalized_member_name(name: str) -> str:
    if not name or "\\" in name or "\x00" in name:
        raise ProjectSecurityError("project ZIP member name is invalid")
    if name.startswith("/") or PurePosixPath(name).is_absolute():
        raise ProjectSecurityError("project ZIP member path must be relative")
    if len(name) >= 2 and name[1] == ":":
        raise ProjectSecurityError("project ZIP member path must not have a drive")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ProjectSecurityError("project ZIP member path is not normalized")
    normalized = posixpath.normpath(name)
    if normalized != name:
        raise ProjectSecurityError("project ZIP member path is not normalized")
    return unicodedata.normalize("NFC", name).casefold()


def _validate_zip_members(
    archive: zipfile.ZipFile,
    package_size: int,
    limits: ProjectLimits,
) -> dict[str, str]:
    if package_size > limits.max_archive_bytes:
        raise ProjectResourceLimitError("project ZIP exceeds compressed size limit")
    infos = archive.infolist()
    if len(infos) > limits.max_entries:
        raise ProjectResourceLimitError("project ZIP has too many entries")
    seen: dict[str, str] = {}
    total_size = 0
    for info in infos:
        normalized = _normalized_member_name(info.filename)
        if normalized in seen:
            raise ProjectSecurityError(
                f"project ZIP has duplicate normalized member: {info.filename}"
            )
        seen[normalized] = info.filename
        if info.is_dir() or info.filename.endswith("/"):
            raise ProjectSecurityError("project ZIP directories are not supported")
        if info.create_system == 3 and ((info.external_attr >> 16) & 0o170000) == 0o120000:
            raise ProjectSecurityError("project ZIP symlinks are not supported")
        if info.file_size > limits.max_member_bytes:
            raise ProjectResourceLimitError(
                f"project ZIP member exceeds size limit: {info.filename}"
            )
        total_size += info.file_size
        if total_size > limits.max_total_uncompressed_bytes:
            raise ProjectResourceLimitError(
                "project ZIP exceeds total uncompressed size limit"
            )
    return seen


def _read_json(
    archive: zipfile.ZipFile,
    member: str,
    limits: ProjectLimits,
) -> dict[str, Any]:
    try:
        data = archive.read(member)
    except KeyError as exc:
        raise ProjectFormatError(f"project ZIP is missing {member}") from exc
    if len(data) > limits.max_json_bytes:
        raise ProjectResourceLimitError(f"project JSON exceeds size limit: {member}")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectFormatError(f"project JSON is invalid: {member}") from exc
    if not isinstance(value, dict):
        raise ProjectFormatError(f"project JSON must be an object: {member}")
    return value


def _read_member(
    archive: zipfile.ZipFile,
    path: str,
    limits: ProjectLimits,
) -> bytes:
    try:
        info = archive.getinfo(path)
    except KeyError as exc:
        raise ProjectFormatError(f"project ZIP is missing {path}") from exc
    if info.file_size > limits.max_member_bytes:
        raise ProjectResourceLimitError(f"project member exceeds size limit: {path}")
    data = archive.read(path)
    if len(data) > limits.max_member_bytes:
        raise ProjectResourceLimitError(f"project member exceeds size limit: {path}")
    return data


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ProjectFormatError(f"{field_name} must be a list of non-empty strings")
    return value


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ProjectFormatError(f"{field_name} must be a SHA-256 hex digest")
    normalized = value.lower()
    if any(character not in "0123456789abcdef" for character in normalized):
        raise ProjectFormatError(f"{field_name} must be a SHA-256 hex digest")
    return normalized


def _resource_path(role: str, sha256: str) -> str:
    if role not in {"asset", "resource"}:
        raise ProjectFormatError("resource role is invalid")
    return f"{'resources' if role == 'resource' else 'assets'}/{sha256}"


def _validate_thumbnail_png(data: bytes, max_pixels: int) -> None:
    signature = b"\x89PNG\r\n\x1a\n"
    if len(data) < 24 or data[:8] != signature or data[12:16] != b"IHDR":
        raise ProjectFormatError("project thumbnail is not a valid PNG")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        raise ProjectFormatError("project thumbnail dimensions are invalid")
    if width * height > max_pixels:
        raise ProjectResourceLimitError(
            "project thumbnail exceeds decoded pixel limit"
        )


def build_project_bytes(snapshot: ProjectSnapshot) -> bytes:
    snapshot.validate()
    if snapshot.thumbnail is not None:
        _validate_thumbnail_png(
            snapshot.thumbnail.data,
            ProjectLimits().max_thumbnail_pixels,
        )
    manifest = snapshot.manifest_dict()
    project = snapshot.project_dict()
    stream = io.BytesIO()
    with zipfile.ZipFile(
        stream,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=True,
    ) as archive:
        archive.writestr("manifest.json", canonical_json_bytes(manifest))
        archive.writestr("project.json", canonical_json_bytes(project))
        for document in snapshot.documents:
            archive.writestr(
                f"documents/{document.document_id}.json",
                canonical_json_bytes(document.to_dict()),
            )
        written_paths: set[str] = set()
        for asset in snapshot.assets.values():
            prefix = "resources" if asset.role == "resource" else "assets"
            path = f"{prefix}/{asset.sha256}"
            if path in written_paths:
                continue
            archive.writestr(path, asset.data)
            written_paths.add(path)
        if snapshot.thumbnail is not None:
            archive.writestr("preview/thumbnail.png", snapshot.thumbnail.data)
    return stream.getvalue()


def _read_from_bytes(data: bytes, limits: ProjectLimits) -> ProjectSnapshot:
    if len(data) > limits.max_archive_bytes:
        raise ProjectResourceLimitError("project ZIP exceeds compressed size limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ProjectFormatError("project ZIP is invalid") from exc
    with archive:
        _validate_zip_members(archive, len(data), limits)
        manifest = _read_json(archive, "manifest.json", limits)
        project = _read_json(archive, "project.json", limits)
        if (
            manifest.get("format") != PROJECT_FORMAT
            or manifest.get("containerVersion") != PROJECT_CONTAINER_VERSION
            or manifest.get("schemaVersion") != PROJECT_SCHEMA_VERSION
        ):
            raise ProjectFormatError("unsupported lumina-project manifest")
        if project.get("projectId") != manifest.get("projectId") or project.get(
            "revisionId"
        ) != manifest.get("revisionId"):
            raise ProjectFormatError("manifest and project identities disagree")

        raw_document_descriptors = manifest.get("documents")
        if not isinstance(raw_document_descriptors, list) or not raw_document_descriptors:
            raise ProjectFormatError("manifest documents are missing")
        documents: list[WorkflowDocument] = []
        document_ids: set[str] = set()
        for descriptor in raw_document_descriptors:
            if not isinstance(descriptor, dict):
                raise ProjectFormatError("document descriptor must be an object")
            document_id = descriptor.get("documentId")
            kind = descriptor.get("kind")
            schema_version = descriptor.get("schemaVersion")
            path = descriptor.get("path")
            if (
                not isinstance(document_id, str)
                or not isinstance(kind, str)
                or not isinstance(schema_version, int)
                or isinstance(schema_version, bool)
                or schema_version < 1
                or not isinstance(path, str)
            ):
                raise ProjectFormatError("document descriptor is incomplete")
            if document_id in document_ids:
                raise ProjectFormatError("duplicate document descriptor")
            document_ids.add(document_id)
            expected_path = f"documents/{document_id}.json"
            if path != expected_path:
                raise ProjectSecurityError("document path is not canonical")
            raw_document = _read_json(archive, path, limits)
            input_revision_ids = raw_document.get("inputRevisionIds", [])
            resource_refs = raw_document.get("resourceRefs", [])
            required_capabilities = raw_document.get("requiredCapabilities", [])
            if not isinstance(input_revision_ids, list):
                raise ProjectFormatError("document inputRevisionIds must be a list")
            if not isinstance(resource_refs, list):
                raise ProjectFormatError("document resourceRefs must be a list")
            if not isinstance(required_capabilities, list):
                raise ProjectFormatError(
                    "document requiredCapabilities must be a list"
                )
            if (
                raw_document.get("documentId") != document_id
                or raw_document.get("kind") != kind
                or raw_document.get("schemaVersion") != schema_version
            ):
                raise ProjectFormatError(
                    f"document descriptor does not match payload: {document_id}"
                )
            try:
                documents.append(
                    WorkflowDocument(
                        document_id=raw_document["documentId"],
                        kind=raw_document["kind"],
                        schema_version=raw_document["schemaVersion"],
                        payload=raw_document["payload"],
                        input_revision_ids=tuple(input_revision_ids),
                        resource_refs=tuple(resource_refs),
                        required_capabilities=tuple(required_capabilities),
                    )
                )
            except (KeyError, TypeError, ValueError, ProjectValidationError) as exc:
                raise ProjectFormatError(f"invalid document: {document_id}") from exc

        raw_resource_descriptors = manifest.get("resources")
        if not isinstance(raw_resource_descriptors, list):
            raise ProjectFormatError("manifest resources are missing")
        assets: dict[str, AssetBlob] = {}
        resource_ids: set[str] = set()
        for descriptor in raw_resource_descriptors:
            if not isinstance(descriptor, dict):
                raise ProjectFormatError("resource descriptor must be an object")
            try:
                asset_id = descriptor["assetId"]
                path = descriptor["path"]
                expected_hash = descriptor["sha256"]
                media_type = descriptor["mediaType"]
                role = descriptor["role"]
                byte_size = descriptor["byteSize"]
            except (KeyError, TypeError) as exc:
                raise ProjectFormatError("resource descriptor is incomplete") from exc
            if not isinstance(asset_id, str) or not asset_id or asset_id in resource_ids:
                raise ProjectFormatError("resource identity is invalid or duplicated")
            resource_ids.add(asset_id)
            if not isinstance(role, str):
                raise ProjectFormatError("resource role is invalid")
            normalized_hash = _sha256(expected_hash, f"resource {asset_id} sha256")
            expected_path = _resource_path(role, normalized_hash)
            if path != expected_path:
                raise ProjectSecurityError(f"resource path is not canonical: {asset_id}")
            if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0:
                raise ProjectFormatError(f"resource byteSize is invalid: {asset_id}")
            if not isinstance(media_type, str) or not media_type:
                raise ProjectFormatError(f"resource mediaType is invalid: {asset_id}")
            filename = descriptor.get("filename")
            if filename is not None and (
                not isinstance(filename, str) or not filename or "/" in filename or "\\" in filename
            ):
                raise ProjectFormatError(f"resource filename is invalid: {asset_id}")
            data = _read_member(archive, path, limits)
            if hashlib.sha256(data).hexdigest() != normalized_hash:
                raise ProjectFormatError(f"resource checksum mismatch: {asset_id}")
            if byte_size != len(data):
                raise ProjectFormatError(f"resource byte size mismatch: {asset_id}")
            try:
                assets[asset_id] = AssetBlob(
                    asset_id=asset_id,
                    data=data,
                    media_type=media_type,
                    filename=filename,
                    role=role,
                )
            except ProjectValidationError as exc:
                raise ProjectFormatError(f"invalid resource: {asset_id}") from exc

        thumbnail = None
        thumbnail_descriptor = manifest.get("thumbnail")
        if thumbnail_descriptor is not None:
            if not isinstance(thumbnail_descriptor, dict):
                raise ProjectFormatError("thumbnail descriptor must be an object")
            thumbnail_path = thumbnail_descriptor.get("path")
            thumbnail_hash = _sha256(
                thumbnail_descriptor.get("sha256"),
                "thumbnail sha256",
            )
            if thumbnail_path != "preview/thumbnail.png":
                raise ProjectSecurityError("thumbnail path is not canonical")
            thumbnail_size = thumbnail_descriptor.get("byteSize")
            thumbnail_media_type = thumbnail_descriptor.get("mediaType")
            if (
                not isinstance(thumbnail_size, int)
                or isinstance(thumbnail_size, bool)
                or thumbnail_size < 0
                or not isinstance(thumbnail_media_type, str)
                or not thumbnail_media_type
            ):
                raise ProjectFormatError("thumbnail descriptor is invalid")
            thumbnail_data = _read_member(
                archive,
                thumbnail_path,
                limits,
            )
            if hashlib.sha256(thumbnail_data).hexdigest() != thumbnail_hash:
                raise ProjectFormatError("thumbnail checksum mismatch")
            if len(thumbnail_data) != thumbnail_size:
                raise ProjectFormatError("thumbnail byte size mismatch")
            if thumbnail_media_type.lower() != "image/png":
                raise ProjectFormatError("project thumbnail must use image/png")
            _validate_thumbnail_png(
                thumbnail_data,
                limits.max_thumbnail_pixels,
            )
            thumbnail = AssetBlob(
                asset_id="thumbnail",
                data=thumbnail_data,
                media_type=thumbnail_media_type,
                role="resource",
            )

        try:
            workflow_kinds = _string_list(
                manifest.get("workflowKinds"),
                "manifest workflowKinds",
            )
            required_capabilities = _string_list(
                manifest.get("requiredCapabilities", []),
                "manifest requiredCapabilities",
            )
            degraded_fields = _string_list(
                manifest.get("degradedFields", []),
                "manifest degradedFields",
            )
            warnings = _string_list(
                manifest.get("warnings", []),
                "manifest warnings",
            )
            manifest_document_ids = [
                descriptor["documentId"] for descriptor in raw_document_descriptors
            ]
            if project.get("documentIds") != manifest_document_ids:
                raise ProjectFormatError("project document index is inconsistent")
            if project.get("resourceRefs") != list(assets):
                raise ProjectFormatError("project resource index is inconsistent")
            snapshot = ProjectSnapshot(
                project_id=manifest["projectId"],
                revision_id=manifest["revisionId"],
                name=manifest["name"],
                workflow_kinds=tuple(workflow_kinds),
                entry_document_id=manifest["entryDocumentId"],
                documents=tuple(documents),
                assets=assets,
                thumbnail=thumbnail,
                created_at=manifest["createdAt"],
                modified_at=manifest["modifiedAt"],
                source_project_id=project.get("sourceProjectId"),
                source_revision_id=project.get("sourceRevisionId"),
                required_capabilities=tuple(required_capabilities),
                degraded_fields=tuple(degraded_fields),
                warnings=tuple(warnings),
            )
            snapshot.validate()
            return snapshot
        except (KeyError, TypeError, ValueError, ProjectValidationError) as exc:
            raise ProjectFormatError("project metadata is invalid") from exc


def read_project(
    source: Path | str | bytes | bytearray,
    *,
    limits: ProjectLimits | None = None,
) -> ProjectSnapshot:
    """Read and validate a project from bytes or a local file.

    从字节或本地文件读取并校验工程。
    """

    active_limits = limits or ProjectLimits()
    if isinstance(source, (str, Path)):
        path = Path(source)
        try:
            package_size = path.stat().st_size
            if package_size > active_limits.max_archive_bytes:
                raise ProjectResourceLimitError(
                    "project ZIP exceeds compressed size limit"
                )
            data = path.read_bytes()
        except OSError as exc:
            raise ProjectFormatError("project file cannot be read") from exc
    else:
        data = bytes(source)
    return _read_from_bytes(data, active_limits)


def write_project(path: Path | str, snapshot: ProjectSnapshot) -> None:
    """Write a validated project with same-directory atomic replacement.

    在同目录通过临时文件和原子替换写入已校验工程。
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    package = build_project_bytes(snapshot)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(package)
            handle.flush()
            os.fsync(handle.fileno())
        read_project(Path(temporary_name))
        os.replace(temporary_name, target)
        try:
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
