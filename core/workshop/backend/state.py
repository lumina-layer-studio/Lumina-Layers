"""Persistent backend runtime state, separate from install-state.json.

Keeping authorization, preparation, and reference data in a separate
document leaves the v1 install state readable by older hosts after a
downgrade.

后端授权、准备结果与引用数据独立于 install-state.json 存放，降级后旧宿主仍可
读取 v1 安装状态。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..errors import WorkshopBackendError
from ..install_store import _atomic_write


MAX_STATE_BYTES = 8 * 1024 * 1024
ReviewLevel = Literal["official", "reviewed", "unreviewed"]
PreparationStatus = Literal["unprepared", "preparing", "prepared", "failed"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BackendAuthorization(_StateModel):
    """User consent bound to exact package bytes and declaration."""

    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    declaration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_level: ReviewLevel
    acknowledged_unreviewed: bool
    inherited_from: str | None = None
    granted_at: str


class InstallFootprint(_StateModel):
    """Measured physical bytes added versus satisfied by shared content."""

    environment_new_bytes: int = 0
    environment_shared_bytes: int = 0
    model_new_bytes: int = 0
    model_shared_bytes: int = 0
    reused_environment: bool = False


class BackendVersionRecord(_StateModel):
    module_id: str
    version: str
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    declaration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preparation: PreparationStatus = "unprepared"
    failure_code: str | None = None
    environment_key: str | None = None
    variant_environments: dict[str, str] = Field(default_factory=dict)
    variant_failures: dict[str, str] = Field(default_factory=dict)
    model_sha256s: tuple[str, ...] = ()
    authorization: BackendAuthorization | None = None
    footprint: InstallFootprint | None = None
    prepared_at: str | None = None
    recorded_at: str


class ModuleBackendSettings(_StateModel):
    module_id: str
    acceleration: str | None = None


class RetainedModel(_StateModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_name: str
    module_id: str
    size_bytes: int = Field(ge=0)
    retained_at: str


class PendingReclaim(_StateModel):
    path: str
    reason: str
    since: str


class BackendStateDocument(_StateModel):
    schema_version: Literal[1] = 1
    versions: tuple[BackendVersionRecord, ...] = ()
    settings: tuple[ModuleBackendSettings, ...] = ()
    retained_models: tuple[RetainedModel, ...] = ()
    pending: tuple[PendingReclaim, ...] = ()


class BackendStateStore:
    """Serialize read-modify-write access to the backend state document.

    串行化后端状态文档的读取、修改与写入。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def read(self) -> BackendStateDocument:
        with self._lock:
            if not self.path.exists():
                return BackendStateDocument()
            try:
                if self.path.stat().st_size > MAX_STATE_BYTES:
                    raise WorkshopBackendError(
                        "backend-state-invalid",
                        "Backend runtime state exceeds its size limit.",
                    )
                return BackendStateDocument.model_validate(
                    json.loads(self.path.read_text(encoding="utf-8"))
                )
            except WorkshopBackendError:
                raise
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
                raise WorkshopBackendError(
                    "backend-state-invalid",
                    "Backend runtime state is unreadable.",
                ) from exc

    def mutate(
        self,
        callback: Callable[[BackendStateDocument], BackendStateDocument],
    ) -> BackendStateDocument:
        with self._lock:
            replacement = callback(self.read())
            payload = (
                json.dumps(
                    replacement.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            if len(payload) > MAX_STATE_BYTES:
                raise WorkshopBackendError(
                    "backend-state-invalid",
                    "Backend runtime state exceeds its size limit.",
                )
            _atomic_write(self.path, payload)
            return replacement

    def get_version(
        self,
        module_id: str,
        version: str,
    ) -> BackendVersionRecord | None:
        return next(
            (
                record
                for record in self.read().versions
                if record.module_id == module_id and record.version == version
            ),
            None,
        )

    def upsert_version(self, record: BackendVersionRecord) -> BackendVersionRecord:
        def apply(document: BackendStateDocument) -> BackendStateDocument:
            others = tuple(
                item
                for item in document.versions
                if not (item.module_id == record.module_id and item.version == record.version)
            )
            return document.model_copy(
                update={
                    "versions": tuple(
                        sorted(
                            (*others, record),
                            key=lambda item: (item.module_id, item.version),
                        )
                    )
                }
            )

        self.mutate(apply)
        return record

    def update_version(
        self,
        module_id: str,
        version: str,
        **changes: object,
    ) -> BackendVersionRecord:
        with self._lock:
            current = self.get_version(module_id, version)
            if current is None:
                raise WorkshopBackendError(
                    "backend-not-declared",
                    "This module version has no backend record.",
                )
            replacement = BackendVersionRecord.model_validate(
                {**current.model_dump(mode="python"), **changes}
            )
            return self.upsert_version(replacement)

    def remove_versions(
        self,
        predicate: Callable[[BackendVersionRecord], bool],
    ) -> tuple[BackendVersionRecord, ...]:
        removed: list[BackendVersionRecord] = []

        def apply(document: BackendStateDocument) -> BackendStateDocument:
            kept = []
            for item in document.versions:
                (removed if predicate(item) else kept).append(item)
            return document.model_copy(update={"versions": tuple(kept)})

        self.mutate(apply)
        return tuple(removed)

    def settings_for(self, module_id: str) -> ModuleBackendSettings:
        return next(
            (item for item in self.read().settings if item.module_id == module_id),
            ModuleBackendSettings(module_id=module_id),
        )

    def set_settings(self, settings: ModuleBackendSettings | None, module_id: str) -> None:
        def apply(document: BackendStateDocument) -> BackendStateDocument:
            others = tuple(item for item in document.settings if item.module_id != module_id)
            values = others if settings is None else (*others, settings)
            return document.model_copy(
                update={"settings": tuple(sorted(values, key=lambda item: item.module_id))}
            )

        self.mutate(apply)

    def change_retained_models(
        self,
        change: Callable[[tuple[RetainedModel, ...]], tuple[RetainedModel, ...]],
    ) -> tuple[RetainedModel, ...]:
        """Apply one change to the user's kept models as a single update.

        Concurrent uninstalls and deletions each edit this list; reading and
        writing it under the state lock keeps every user choice.
        """

        updated = self.mutate(
            lambda document: document.model_copy(
                update={"retained_models": change(document.retained_models)}
            )
        )
        return updated.retained_models

    def set_pending(self, pending: tuple[PendingReclaim, ...]) -> None:
        self.mutate(lambda document: document.model_copy(update={"pending": pending}))
