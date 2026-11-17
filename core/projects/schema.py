"""Versioned domain model for the editable lumina-project format.

可编辑 lumina-project 格式的版本化领域模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import math
import re
from typing import Any
from uuid import uuid4

from .errors import ProjectValidationError

PROJECT_FORMAT = "lumina-project"
PROJECT_CONTAINER_VERSION = 1
PROJECT_SCHEMA_VERSION = 1
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FORBIDDEN_RUNTIME_KEYS = frozenset(
    {
        "sessionId",
        "session_id",
        "fileId",
        "file_id",
        "previewUrl",
        "preview_url",
        "modelUrl",
        "model_url",
        "downloadUrl",
        "download_url",
        "localPath",
        "local_path",
        "machineIp",
        "machine_ip",
        "accessToken",
        "access_token",
        "command",
        "commands",
        "commandLine",
        "executable",
        "download",
        "downloadUrl",
        "externalUrl",
        "script",
    }
)
_MAX_JSON_DEPTH = 32
_SVG_UNSAFE = re.compile(
    rb"<\s*script\b|\bon[a-z0-9_-]+\s*=|(?:href|src|action)\s*=\s*['\"](?:https?:|file:|javascript:|//)|@import\s+url\(",
    re.IGNORECASE,
)


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp.

    返回 ISO-8601 UTC 时间戳。
    """

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def new_identity() -> str:
    """Return a stable project/document identity.

    返回稳定的工程/文档身份。
    """

    return str(uuid4())


def _validate_json_value(value: Any, *, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ProjectValidationError("project payload exceeds JSON nesting limit")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProjectValidationError("project payload contains a non-finite number")
        return
    if isinstance(value, list | tuple):
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProjectValidationError("project payload keys must be strings")
            if key in _FORBIDDEN_RUNTIME_KEYS:
                raise ProjectValidationError(
                    f"runtime-only field is not project data: {key}"
                )
            _validate_json_value(item, depth=depth + 1)
        return
    raise ProjectValidationError(
        f"project payload contains unsupported value type: {type(value).__name__}"
    )


def _validate_identity(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ProjectValidationError(f"{field_name} is not a valid project identity")


@dataclass(frozen=True)
class AssetBlob:
    """A content-addressed project asset.

    工程中的内容寻址资源。
    """

    asset_id: str
    data: bytes
    media_type: str
    filename: str | None = None
    role: str = "asset"

    def __post_init__(self) -> None:
        _validate_identity(self.asset_id, "asset_id")
        if not isinstance(self.data, bytes):
            raise ProjectValidationError("asset data must be bytes")
        if not self.media_type or "/" not in self.media_type:
            raise ProjectValidationError("asset media_type is invalid")
        if self.role not in {"asset", "resource"}:
            raise ProjectValidationError("asset role must be asset or resource")
        if self.filename is not None and (
            not self.filename or "/" in self.filename or "\\" in self.filename
        ):
            raise ProjectValidationError("asset filename must be a plain filename")
        if (
            self.media_type.lower() == "image/svg+xml"
            or (self.filename is not None and self.filename.lower().endswith(".svg"))
        ) and _SVG_UNSAFE.search(self.data):
            raise ProjectValidationError(
                "SVG assets must not contain scripts or external references"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class WorkflowDocument:
    """One versioned editable workflow document.

    一个版本化、可继续编辑的工作流文档。
    """

    document_id: str
    kind: str
    schema_version: int
    payload: dict[str, Any]
    input_revision_ids: tuple[str, ...] = ()
    resource_refs: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identity(self.document_id, "document_id")
        if not self.kind or not isinstance(self.kind, str):
            raise ProjectValidationError("document kind is required")
        if not isinstance(self.schema_version, int) or self.schema_version < 1:
            raise ProjectValidationError("document schema_version must be positive")
        if not isinstance(self.payload, dict):
            raise ProjectValidationError("document payload must be an object")
        _validate_json_value(self.payload)
        for revision_id in self.input_revision_ids:
            _validate_identity(revision_id, "input_revision_id")
        for asset_id in self.resource_refs:
            _validate_identity(asset_id, "resource_ref")
        for capability in self.required_capabilities:
            if not isinstance(capability, str) or not capability:
                raise ProjectValidationError("required capabilities must be non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "documentId": self.document_id,
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "payload": self.payload,
            "inputRevisionIds": list(self.input_revision_ids),
            "resourceRefs": list(self.resource_refs),
            "requiredCapabilities": list(self.required_capabilities),
        }


@dataclass
class ProjectSnapshot:
    """An immutable-at-save project revision in memory.

    内存中的工程修订；成功写盘后按 revisionId 视为不可变。
    """

    project_id: str
    revision_id: str
    name: str
    workflow_kinds: tuple[str, ...]
    entry_document_id: str
    documents: tuple[WorkflowDocument, ...]
    assets: dict[str, AssetBlob] = field(default_factory=dict)
    thumbnail: AssetBlob | None = None
    created_at: str = field(default_factory=utc_now)
    modified_at: str = field(default_factory=utc_now)
    source_project_id: str | None = None
    source_revision_id: str | None = None
    required_capabilities: tuple[str, ...] = ()
    degraded_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def new(
        cls,
        *,
        name: str,
        workflow_kinds: tuple[str, ...] | list[str],
        documents: tuple[WorkflowDocument, ...] | list[WorkflowDocument],
        assets: tuple[AssetBlob, ...] | list[AssetBlob] = (),
        thumbnail: AssetBlob | None = None,
        source_project_id: str | None = None,
        source_revision_id: str | None = None,
        required_capabilities: tuple[str, ...] = (),
        degraded_fields: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> "ProjectSnapshot":
        asset_list = tuple(assets)
        if len({asset.asset_id for asset in asset_list}) != len(asset_list):
            raise ProjectValidationError("asset identities must be unique")
        project_id = new_identity()
        return cls(
            project_id=project_id,
            revision_id=new_identity(),
            name=name,
            workflow_kinds=tuple(workflow_kinds),
            entry_document_id=documents[0].document_id if documents else "",
            documents=tuple(documents),
            assets={asset.asset_id: asset for asset in asset_list},
            thumbnail=thumbnail,
            source_project_id=source_project_id,
            source_revision_id=source_revision_id,
            required_capabilities=tuple(required_capabilities),
            degraded_fields=tuple(degraded_fields),
            warnings=tuple(warnings),
        )

    def validate(self) -> None:
        _validate_identity(self.project_id, "project_id")
        _validate_identity(self.revision_id, "revision_id")
        if not self.name or len(self.name) > 500:
            raise ProjectValidationError("project name is required and bounded")
        if not self.workflow_kinds or any(
            not isinstance(kind, str) or not kind for kind in self.workflow_kinds
        ):
            raise ProjectValidationError("workflow_kinds must be non-empty strings")
        if not self.documents:
            raise ProjectValidationError("project must contain at least one document")
        if len({document.document_id for document in self.documents}) != len(
            self.documents
        ):
            raise ProjectValidationError("document identities must be unique")
        if self.entry_document_id not in {
            document.document_id for document in self.documents
        }:
            raise ProjectValidationError("entry_document_id is not present")
        if len(self.assets) != len(set(self.assets)):
            raise ProjectValidationError("asset identities must be unique")
        for asset_id, asset in self.assets.items():
            if asset_id != asset.asset_id:
                raise ProjectValidationError("asset map key does not match asset_id")
        for document in self.documents:
            # Documents are intentionally mutable while an editor is building
            # a revision. Re-run the boundary checks here instead of trusting
            # only the constructor-time validation.
            document.__post_init__()
            missing = set(document.resource_refs) - self.assets.keys()
            if missing:
                raise ProjectValidationError(
                    f"document references missing assets: {sorted(missing)}"
                )
        if self.thumbnail is not None and self.thumbnail.role != "resource":
            raise ProjectValidationError("thumbnail must use the resource role")
        if self.source_project_id is not None:
            _validate_identity(self.source_project_id, "source_project_id")
        if self.source_revision_id is not None:
            _validate_identity(self.source_revision_id, "source_revision_id")
        for capability in self.required_capabilities:
            if not isinstance(capability, str) or not capability:
                raise ProjectValidationError("required capabilities must be non-empty strings")
        for field_name, values in (
            ("degraded_fields", self.degraded_fields),
            ("warnings", self.warnings),
        ):
            if any(not isinstance(value, str) or not value for value in values):
                raise ProjectValidationError(f"{field_name} must contain non-empty strings")

    def resource_descriptors(self) -> list[dict[str, Any]]:
        descriptors: list[dict[str, Any]] = []
        for asset in self.assets.values():
            prefix = "resources" if asset.role == "resource" else "assets"
            descriptors.append(
                {
                    "assetId": asset.asset_id,
                    "sha256": asset.sha256,
                    "path": f"{prefix}/{asset.sha256}",
                    "byteSize": len(asset.data),
                    "mediaType": asset.media_type,
                    **({"filename": asset.filename} if asset.filename else {}),
                    "role": asset.role,
                }
            )
        return descriptors

    def manifest_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "format": PROJECT_FORMAT,
            "containerVersion": PROJECT_CONTAINER_VERSION,
            "schemaVersion": PROJECT_SCHEMA_VERSION,
            "projectId": self.project_id,
            "revisionId": self.revision_id,
            "name": self.name,
            "workflowKinds": list(self.workflow_kinds),
            "createdAt": self.created_at,
            "modifiedAt": self.modified_at,
            "entryDocumentId": self.entry_document_id,
            "documents": [
                {
                    "documentId": document.document_id,
                    "kind": document.kind,
                    "schemaVersion": document.schema_version,
                    "path": f"documents/{document.document_id}.json",
                }
                for document in self.documents
            ],
            "resources": self.resource_descriptors(),
            "thumbnail": (
                {
                    "path": "preview/thumbnail.png",
                    "sha256": self.thumbnail.sha256,
                    "byteSize": len(self.thumbnail.data),
                    "mediaType": self.thumbnail.media_type,
                }
                if self.thumbnail is not None
                else None
            ),
            "requiredCapabilities": list(self.required_capabilities),
            "degradedFields": list(self.degraded_fields),
            "warnings": list(self.warnings),
        }

    def project_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "projectId": self.project_id,
            "revisionId": self.revision_id,
            "name": self.name,
            "workflowKinds": list(self.workflow_kinds),
            "entryDocumentId": self.entry_document_id,
            "sourceProjectId": self.source_project_id,
            "sourceRevisionId": self.source_revision_id,
            "documentIds": [document.document_id for document in self.documents],
            "resourceRefs": list(self.assets),
        }
