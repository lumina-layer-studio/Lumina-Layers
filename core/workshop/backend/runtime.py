"""Host-managed module backend runtime: one coordinator per data directory.

Modules declare a backend; the host prepares hash-locked environments and
models after the user authorizes them, starts processes on demand, owns
tasks and their files, and reclaims every resource by ownership.
Installed, enabled, and running are separate states: installing or
enabling never starts a process.

模块声明后端，宿主在用户授权后准备按哈希锁定的环境与模型，按需启动进程，
拥有任务及其文件，并按归属回收资源。安装、启用与运行是相互独立的状态。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from datetime import datetime, timezone
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from api.structured_logging import get_logger

from ..constants import (
    MAX_BACKEND_TASK_FILE_BYTES,
    MAX_BACKEND_TASK_INPUTS,
    MAX_BACKEND_TASK_PARAMS_BYTES,
)
from ..errors import WorkshopBackendError, WorkshopInstallError
from ..install_store import InstalledModuleState
from ..installer import WorkshopInstaller
from ..models import (
    MODULE_ID_PATTERN,
    InspectedWorkshopPackage,
    WorkshopManifestV2,
    parse_workshop_manifest_json,
)
from .environments import EnvironmentManager, environment_key, environment_python
from .locks import BackendLock, WheelSourcePolicy, current_platform_key, parse_backend_lock
from .model_files import ModelFetcher, ModelManager
from .preview import (
    MANAGED_PYTHON_DISK_ESTIMATE_BYTES,
    MANAGED_PYTHON_DOWNLOAD_ESTIMATE_BYTES,
    estimate_dependencies,
    model_estimates,
)
from .process import BackendLaunch, BackendProcess, kill_recorded_process
from .protocol import BOOTSTRAP_SOURCE
from .review import LEVEL_RANK, ReviewContextSource, determine_review_level, registry_version_state
from .state import (
    BackendAuthorization,
    BackendStateStore,
    BackendVersionRecord,
    InstallFootprint,
    ModuleBackendSettings,
    PendingReclaim,
    RetainedModel,
    ReviewLevel,
    utc_now,
)
from .store import ContentStore, RemovalOutcome, releasable_bytes, remove_tree
from .supervisor import ModuleBackendSupervisor, RunTarget
from .tasks import (
    FILE_NAME_PATTERN,
    SAFE_FILE_NAME_PATTERN,
    TaskError,
    TaskFile,
    TaskRecord,
    TaskStore,
    stored_input_path,
)
from .tooling import (
    CancelToken,
    ExternalInterpreterProvider,
    InterpreterProvider,
    ManagedInterpreterProvider,
    UvTool,
)


log = get_logger(__name__)

DEFAULT_IDLE_TIMEOUT_SECONDS = 300.0
_PREPARE_OPERATION = "prepare"
# A version is recorded by the installer hook just before its install-state
# commit; GC leaves such fresh records alone for this long.
_FRESH_RECORD_SECONDS = 600


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS
    cancel_grace_seconds: float = 5.0
    start_timeout_seconds: float = 120.0
    task_retention: timedelta = timedelta(days=14)


@dataclass(frozen=True, slots=True)
class TaskInputFile:
    """One uploaded input already written to a temporary file."""

    name: str
    file_name: str
    mime_type: str
    path: Path


@dataclass(slots=True)
class UninstallReport:
    """Four user-visible outcome categories of an uninstall."""

    cleared: list[dict[str, Any]] = field(default_factory=list)
    shared: list[dict[str, Any]] = field(default_factory=list)
    retained: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "cleared": self.cleared,
            "shared": self.shared,
            "retained": self.retained,
            "failed": self.failed,
        }


@dataclass(slots=True)
class GarbageReport:
    environment_bytes: int = 0
    environments: list[str] = field(default_factory=list)
    object_bytes: int = 0
    interpreter_bytes: int = 0
    interpreters: list[str] = field(default_factory=list)
    other_bytes: int = 0
    pending: list[str] = field(default_factory=list)

    @property
    def freed_bytes(self) -> int:
        return self.environment_bytes + self.object_bytes + self.interpreter_bytes + self.other_bytes


def declaration_digest(manifest: WorkshopManifestV2) -> str:
    payload = json.dumps(
        manifest.backend.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _capability_names(manifest: WorkshopManifestV2) -> set[str]:
    return {item.name for item in manifest.backend.capabilities}


class WorkshopBackendRuntime:
    """Coordinate module backends for one Workshop data directory.

    协调一个创意工坊数据目录下的全部模块后端。
    """

    def __init__(
        self,
        *,
        data_dir: Path,
        installer_factory: Callable[[], WorkshopInstaller],
        uv_executable: Path | None,
        model_fetcher: ModelFetcher,
        review_context: ReviewContextSource,
        wheel_sources: WheelSourcePolicy = WheelSourcePolicy(),
        external_python: Path | None = None,
        python_mirror: str | None = None,
        settings: RuntimeSettings = RuntimeSettings(),
        platform_key: str | None = None,
        process_factory: Callable[..., BackendProcess] = BackendProcess,
    ) -> None:
        self.root = Path(data_dir) / "runtime"
        self.root.mkdir(parents=True, exist_ok=True)
        self._installer_factory = installer_factory
        self._review_context = review_context
        self._settings = settings
        self._platform_key = platform_key if platform_key is not None else current_platform_key()
        self._process_factory = process_factory
        self._uv = (
            UvTool(
                uv_executable,
                cache_dir=self.root / "uv-cache",
                python_install_dir=self.root / "python",
            )
            if uv_executable is not None
            else None
        )
        self._interpreters: InterpreterProvider | None
        if external_python is not None:
            self._interpreters = ExternalInterpreterProvider(external_python)
        elif self._uv is not None:
            self._interpreters = ManagedInterpreterProvider(self._uv, mirror=python_mirror)
        else:
            self._interpreters = None
        self.store = ContentStore(self.root / "store")
        self.environments = EnvironmentManager(
            self.root / "envs",
            uv=self._uv,
            store=self.store,
            sources=wheel_sources,
        )
        self.models = ModelManager(self.root / "models", store=self.store, fetcher=model_fetcher)
        self.tasks = TaskStore(self.root / "tasks", retention=settings.task_retention)
        self.state = BackendStateStore(self.root / "state.json")
        self._scratch_root = self.root / "scratch"
        self._processes_root = self.root / "processes"
        self._scratch_root.mkdir(parents=True, exist_ok=True)
        self._processes_root.mkdir(parents=True, exist_ok=True)
        self._bootstrap = self.root / "bootstrap.py"
        self._write_bootstrap()
        self._lock = threading.RLock()
        self._supervisors: dict[str, ModuleBackendSupervisor] = {}
        self._preparations: dict[str, tuple[CancelToken, threading.Thread, str, str]] = {}
        self._leased_environments: dict[str, int] = {}
        # Collection snapshots references and preparations commit results
        # under this lock, so a commit never falls between the two.
        self._gc_lock = threading.Lock()
        # Destructive maintenance (staging, download cache, temporary files,
        # interpreters) runs only while no preparation works, and new
        # preparations wait for a running pass to finish.
        self._work_condition = threading.Condition()
        self._active_preparations = 0
        self._maintenance = False
        # Uninstalls record kept models and remove module code one at a time:
        # a failed one withdraws what it recorded, and no other uninstall may
        # rely on that entry in between (modules can share one model file).
        self._uninstall_commit_lock = threading.Lock()
        self._closed = False

    # ----- small helpers ------------------------------------------------

    def _write_bootstrap(self) -> None:
        current = self._bootstrap.read_text(encoding="utf-8") if self._bootstrap.is_file() else None
        if current != BOOTSTRAP_SOURCE:
            self._bootstrap.write_text(BOOTSTRAP_SOURCE, encoding="utf-8")

    @property
    def tool_available(self) -> bool:
        return self._uv is not None and self._interpreters is not None

    def _installer(self) -> WorkshopInstaller:
        return self._installer_factory()

    @staticmethod
    def _require_module_id(module_id: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(module_id) is None:
            raise WorkshopBackendError("module-invalid", "Module ID is invalid.")
        return module_id

    def _installed_state(self, module_id: str) -> InstalledModuleState:
        try:
            state = self._installer().get(self._require_module_id(module_id))
        except WorkshopInstallError as exc:
            raise WorkshopBackendError("module-invalid", "Module ID is invalid.") from exc
        if state is None or state.official_uninstalled:
            raise WorkshopBackendError("module-not-installed", "The Workshop module is not installed.")
        return state

    def _manifest(self, module_id: str, version: str) -> tuple[WorkshopManifestV2, Path]:
        installer = self._installer()
        try:
            root = installer.version_path(module_id, version)
        except WorkshopInstallError as exc:
            raise WorkshopBackendError("module-invalid", "Module identity is invalid.") from exc
        try:
            manifest = parse_workshop_manifest_json((root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkshopBackendError(
                "module-version-unavailable",
                "The installed module version is unavailable.",
            ) from exc
        if not isinstance(manifest, WorkshopManifestV2):
            raise WorkshopBackendError("backend-not-declared", "This module version has no backend.")
        return manifest, root

    def _lock_for(self, root: Path, relative: str) -> BackendLock:
        try:
            return parse_backend_lock((root / relative).read_bytes())
        except OSError as exc:
            raise WorkshopBackendError("backend-lock-unavailable", "The backend lock file is unavailable.") from exc

    def _record(self, module_id: str, version: str) -> BackendVersionRecord:
        record = self.state.get_version(module_id, version)
        if record is None:
            raise WorkshopBackendError(
                "backend-identity-unknown",
                "Reinstall this module version so its package identity can be recorded.",
            )
        return record

    def _supervisor(self, module_id: str) -> ModuleBackendSupervisor:
        with self._lock:
            supervisor = self._supervisors.get(module_id)
            if supervisor is None:
                supervisor = ModuleBackendSupervisor(
                    module_id,
                    tasks=self.tasks,
                    resolve_target=self._resolve_target,
                    process_record_path=self._processes_root / f"{module_id}.json",
                    cancel_grace_seconds=self._settings.cancel_grace_seconds,
                    start_timeout_seconds=self._settings.start_timeout_seconds,
                    on_task_finished=self._task_finished,
                    # Bound to this module: another module may use the same
                    # version number and variant name.
                    on_variant_failed=lambda version, variant, owner=module_id: self._variant_failed(
                        owner, version, variant
                    ),
                    on_process_released=lambda version, owner=module_id: self._release_if_retired(owner, version),
                    process_factory=self._process_factory,
                )
                self._supervisors[module_id] = supervisor
            return supervisor

    # ----- install integration -------------------------------------------

    def record_package(self, inspected: InspectedWorkshopPackage, _staging: Path) -> None:
        """Installer hook: bind a v2 version to its exact package identity."""

        manifest = inspected.manifest
        if not isinstance(manifest, WorkshopManifestV2):
            return
        self.state.upsert_version(
            BackendVersionRecord(
                module_id=manifest.id,
                version=manifest.version,
                package_sha256=inspected.archive_sha256,
                manifest_sha256=inspected.manifest_sha256,
                declaration_sha256=declaration_digest(manifest),
                recorded_at=utc_now(),
            )
        )

    def version_in_use(self, module_id: str, version: str) -> bool:
        """Installer hook: whether pruning ``version`` would break work."""

        with self._lock:
            supervisor = self._supervisors.get(module_id)
            if supervisor is not None and version in supervisor.active_versions():
                return True
            if any(
                prepared_module == module_id and prepared_version == version
                for _token, thread, prepared_module, prepared_version in self._preparations.values()
                if thread.is_alive()
            ):
                return True
        return any(
            record.module_id == module_id and record.module_version == version
            for record in self.tasks.unfinished()
        )

    def require_activatable(self, module_id: str, version: str) -> None:
        """Refuse activation of a backend version that is not prepared."""

        try:
            self._manifest(module_id, version)
        except WorkshopBackendError as exc:
            if exc.code == "backend-not-declared":
                return
            raise
        record = self._record(module_id, version)
        if record.preparation != "prepared":
            raise WorkshopBackendError(
                "backend-not-prepared",
                "Prepare this module's backend before activating it.",
            )

    # ----- review and authorization ------------------------------------

    def _review_level(
        self,
        state: InstalledModuleState,
        record: BackendVersionRecord,
    ) -> tuple[ReviewLevel, bool]:
        context = self._review_context()
        level = determine_review_level(
            source=state.source,
            official=state.official,
            module_id=record.module_id,
            version=record.version,
            package_sha256=record.package_sha256,
            context=context,
            recorded_level=record.authorization.review_level if record.authorization else None,
        )
        registry_state, _sha, _official = registry_version_state(context, record.module_id, record.version)
        blocked = state.source == "registry" and registry_state == "blocked"
        return level, blocked

    def _inheritable_authorization(
        self,
        record: BackendVersionRecord,
        manifest: WorkshopManifestV2,
        level: ReviewLevel,
    ) -> BackendAuthorization | None:
        if LEVEL_RANK[level] < LEVEL_RANK["reviewed"]:
            return None
        capabilities = _capability_names(manifest)
        for other in self.state.read().versions:
            if other.module_id != record.module_id or other.version == record.version:
                continue
            authorization = other.authorization
            if authorization is None or LEVEL_RANK[authorization.review_level] < LEVEL_RANK["reviewed"]:
                continue
            try:
                other_manifest, _root = self._manifest(other.module_id, other.version)
            except WorkshopBackendError:
                continue
            if capabilities <= _capability_names(other_manifest):
                return BackendAuthorization(
                    package_sha256=record.package_sha256,
                    declaration_sha256=record.declaration_sha256,
                    review_level=level,
                    acknowledged_unreviewed=False,
                    inherited_from=other.version,
                    granted_at=utc_now(),
                )
        return None

    def _authorization_status(
        self,
        record: BackendVersionRecord,
        manifest: WorkshopManifestV2,
        level: ReviewLevel,
    ) -> tuple[str, BackendAuthorization | None]:
        authorization = record.authorization
        if (
            authorization is not None
            and authorization.package_sha256 == record.package_sha256
            and authorization.declaration_sha256 == record.declaration_sha256
            and LEVEL_RANK[level] >= LEVEL_RANK[authorization.review_level]
            and (level != "unreviewed" or authorization.acknowledged_unreviewed)
        ):
            return ("inherited" if authorization.inherited_from else "granted"), authorization
        inherited = self._inheritable_authorization(record, manifest, level)
        if inherited is not None:
            return "inherited", inherited
        return "required", None

    def _require_authorized(
        self,
        state: InstalledModuleState,
        record: BackendVersionRecord,
        manifest: WorkshopManifestV2,
    ) -> ReviewLevel:
        level, blocked = self._review_level(state, record)
        if blocked:
            raise WorkshopBackendError("module-version-blocked", "This module version is blocked by the Registry.")
        status, authorization = self._authorization_status(record, manifest, level)
        if status == "required" or authorization is None:
            raise WorkshopBackendError(
                "backend-authorization-required",
                "Confirm this module's backend permissions before it can run.",
            )
        if authorization is not record.authorization:
            self.state.update_version(record.module_id, record.version, authorization=authorization)
        return level

    def authorize(self, module_id: str, version: str, *, acknowledge_unreviewed: bool) -> dict[str, Any]:
        state = self._installed_state(module_id)
        if version not in state.versions:
            raise WorkshopBackendError("module-version-unavailable", "The module version is not installed.")
        manifest, _root = self._manifest(module_id, version)
        record = self._record(module_id, version)
        level, blocked = self._review_level(state, record)
        if blocked:
            raise WorkshopBackendError("module-version-blocked", "This module version is blocked by the Registry.")
        if level == "unreviewed" and not acknowledge_unreviewed:
            raise WorkshopBackendError(
                "unreviewed-confirmation-required",
                "This module's code is unreviewed; confirm the risk to continue.",
            )
        authorization = BackendAuthorization(
            package_sha256=record.package_sha256,
            declaration_sha256=record.declaration_sha256,
            review_level=level,
            acknowledged_unreviewed=level == "unreviewed",
            granted_at=utc_now(),
        )
        self.state.update_version(module_id, version, authorization=authorization)
        log.info(
            "Workshop backend authorized",
            extra={
                "event": "workshop_backend_authorize_done",
                "module_id": module_id,
                "version": version,
                "review_level": level,
            },
        )
        return self.describe(module_id, version)

    # ----- description / preview -----------------------------------------

    def describe(self, module_id: str, version: str) -> dict[str, Any]:
        state = self._installed_state(module_id)
        if version not in state.versions:
            raise WorkshopBackendError("module-version-unavailable", "The module version is not installed.")
        manifest, root = self._manifest(module_id, version)
        record = self._record(module_id, version)
        level, blocked = self._review_level(state, record)
        authorization_status, _authorization = self._authorization_status(record, manifest, level)
        declaration = manifest.backend
        platform_supported = self._platform_key is not None and self._platform_key in declaration.platforms
        dependency: dict[str, Any] | None = None
        variants: list[dict[str, Any]] = []
        package_users = self.environments.package_users()
        if platform_supported and self._platform_key is not None:
            lock = self._lock_for(root, declaration.lock)
            key = environment_key(lock, platform_key=self._platform_key, python_version=declaration.python)
            dependency = estimate_dependencies(
                lock,
                environment_key=key,
                environment_exists=self.environments.get(key) is not None,
                package_users=package_users,
                platform_key=self._platform_key,
                python_version=declaration.python,
            ).as_json()
            for variant in declaration.variants:
                available = self._platform_key in variant.platforms
                estimate = None
                if available:
                    variant_lock = self._lock_for(root, variant.lock)
                    variant_key = environment_key(
                        variant_lock,
                        platform_key=self._platform_key,
                        python_version=declaration.python,
                    )
                    estimate = estimate_dependencies(
                        variant_lock,
                        environment_key=variant_key,
                        environment_exists=self.environments.get(variant_key) is not None,
                        package_users=package_users,
                        platform_key=self._platform_key,
                        python_version=declaration.python,
                    ).as_json()
                variants.append(
                    {
                        "id": variant.id,
                        "name": variant.name.model_dump(by_alias=True),
                        "description": variant.description.model_dump(by_alias=True),
                        "available": available,
                        "prepared": variant.id in record.variant_environments,
                        "failure_code": record.variant_failures.get(variant.id),
                        "dependencies": estimate,
                    }
                )
        interpreter_needed = False
        if self._interpreters is not None and isinstance(self._interpreters, ManagedInterpreterProvider):
            interpreter_needed = not any(
                item.python_version == declaration.python for item in self._interpreters.installed()
            )
        present_models = {model.sha256 for model in declaration.models if self.store.has(model.sha256)}
        preparing = self._active_preparation(module_id, version)
        with self._lock:
            supervisor = self._supervisors.get(module_id)
        return {
            "module_id": module_id,
            "version": version,
            "platform": self._platform_key,
            "platform_supported": platform_supported,
            "tool_available": self.tool_available,
            "review_level": level,
            "blocked": blocked,
            "authorization": authorization_status,
            "requires_unreviewed_confirmation": level == "unreviewed" and authorization_status == "required",
            "preparation": record.preparation,
            "failure_code": record.failure_code,
            "preparation_task_id": preparing,
            "python": declaration.python,
            "interpreter_download_bytes": MANAGED_PYTHON_DOWNLOAD_ESTIMATE_BYTES if interpreter_needed else 0,
            "interpreter_disk_bytes": MANAGED_PYTHON_DISK_ESTIMATE_BYTES if interpreter_needed else 0,
            "capabilities": [
                {"name": item.name, "reason": item.reason} for item in declaration.capabilities
            ],
            "models": model_estimates(declaration.models, present_models),
            "dependencies": dependency,
            "variants": variants,
            "acceleration": self.state.settings_for(module_id).acceleration,
            "footprint": record.footprint.model_dump(mode="json") if record.footprint else None,
            "runtime": supervisor.snapshot() if supervisor is not None else {"state": "stopped", "pid": None, "version": None, "variant": None, "current_task_id": None, "queued": 0, "last_failure": None},
        }

    # ----- preparation ----------------------------------------------------

    def _active_preparation(self, module_id: str, version: str) -> str | None:
        with self._lock:
            for task_id, (_token, thread, prepared_module, prepared_version) in self._preparations.items():
                if thread.is_alive() and prepared_module == module_id and prepared_version == version:
                    return task_id
        return None

    def _lease(self, keys: Sequence[str], delta: int) -> None:
        with self._lock:
            for key in keys:
                count = self._leased_environments.get(key, 0) + delta
                if count <= 0:
                    self._leased_environments.pop(key, None)
                else:
                    self._leased_environments[key] = count

    def _is_leased(self, key: str) -> bool:
        with self._lock:
            return key in self._leased_environments

    def _enter_preparation_work(self, token: CancelToken) -> None:
        """Wait for a running maintenance pass, then count as working."""

        with self._work_condition:
            while self._maintenance:
                self._work_condition.wait(timeout=0.2)
                token.raise_if_cancelled()
            self._active_preparations += 1

    def _leave_preparation_work(self) -> None:
        with self._work_condition:
            self._active_preparations -= 1
            self._work_condition.notify_all()

    def _begin_maintenance(self) -> bool:
        """Claim the destructive cleanup phase unless a preparation works."""

        with self._work_condition:
            if self._active_preparations or self._maintenance:
                return False
            self._maintenance = True
            return True

    def _end_maintenance(self) -> None:
        with self._work_condition:
            self._maintenance = False
            self._work_condition.notify_all()

    def start_preparation(self, module_id: str, version: str) -> TaskRecord:
        state = self._installed_state(module_id)
        if version not in state.versions:
            raise WorkshopBackendError("module-version-unavailable", "The module version is not installed.")
        manifest, _root = self._manifest(module_id, version)
        record = self._record(module_id, version)
        self._require_authorized(state, record, manifest)
        if not self.tool_available:
            raise WorkshopBackendError(
                "backend-tool-unavailable",
                "The backend dependency tool is not installed with this Lumina build.",
            )
        if self._platform_key is None or self._platform_key not in manifest.backend.platforms:
            raise WorkshopBackendError("platform-unsupported", "This module backend does not support this platform.")
        existing = self._active_preparation(module_id, version)
        if existing is not None:
            return self.tasks.require(module_id, existing)
        task, _created = self.tasks.create(
            module_id=module_id,
            module_version=version,
            kind="prepare",
            operation=_PREPARE_OPERATION,
        )
        token = CancelToken()
        thread = threading.Thread(
            target=self._run_preparation,
            args=(task, token),
            name=f"workshop-prepare-{module_id}",
            daemon=True,
        )
        with self._lock:
            self._preparations[task.task_id] = (token, thread, module_id, version)
        if record.preparation != "prepared":
            # A prepared CPU backend stays usable while a variant is added.
            self.state.update_version(module_id, version, preparation="preparing", failure_code=None)
        thread.start()
        return task

    def _progress(self, task: TaskRecord, completed: float, phase: str) -> None:
        from .tasks import TaskProgress

        self.tasks.update(
            task.module_id,
            task.task_id,
            progress=TaskProgress(completed=completed, total=4, phase=phase),
        )

    def _prepare_environment(
        self,
        task: TaskRecord,
        root: Path,
        lock_relative: str,
        manifest: WorkshopManifestV2,
        token: CancelToken,
        leased: list[str],
    ) -> tuple[str, int, int, bool]:
        assert self._interpreters is not None and self._platform_key is not None
        lock = self._lock_for(root, lock_relative)
        key = environment_key(lock, platform_key=self._platform_key, python_version=manifest.backend.python)
        # The lease keeps GC from removing an environment mid-transaction.
        self._lease([key], 1)
        leased.append(key)
        self._progress(task, 0, "interpreter")
        interpreter = self._interpreters.ensure(manifest.backend.python, token)
        self._progress(task, 1, "environment")
        record, created = self.environments.ensure(
            lock,
            platform_key=self._platform_key,
            interpreter=interpreter,
            cancel=token,
        )
        return key, record.new_bytes if created else 0, record.shared_bytes if created else record.new_bytes + record.shared_bytes, not created

    def _self_check(
        self,
        module_id: str,
        version: str,
        root: Path,
        manifest: WorkshopManifestV2,
        env_key: str,
        variant: str | None,
        token: CancelToken,
    ) -> None:
        """Start the backend once and require its ready handshake."""

        launch = self._launch(module_id, version, root, manifest, env_key, variant)
        ready = threading.Event()
        exited = threading.Event()

        def on_message(message: dict[str, Any]) -> None:
            if message.get("type") == "ready" and message.get("protocol") == 1:
                ready.set()

        process = self._process_factory(
            launch,
            on_message=on_message,
            on_exit=lambda _code, _failure: exited.set(),
            log_fields={"module_id": module_id, "version": version, "variant": variant or "cpu", "phase": "self-check"},
        )
        process.start()
        try:
            waited = 0.0
            while waited < self._settings.start_timeout_seconds:
                if ready.wait(0.2) or exited.is_set():
                    break
                token.raise_if_cancelled()
                waited += 0.2
            if not ready.is_set():
                log.warning(
                    "Workshop backend self-check failed",
                    extra={
                        "event": "workshop_backend_selfcheck_failed",
                        "module_id": module_id,
                        "version": version,
                        "variant": variant or "cpu",
                        "error_message": process.output_tail()[-1500:] or "no ready handshake",
                    },
                )
                raise WorkshopBackendError(
                    "backend-self-check-failed",
                    "The module backend did not start correctly during preparation.",
                )
        finally:
            process.shutdown(wait_seconds=5, grace_seconds=1.0)

    def _run_preparation(self, task: TaskRecord, token: CancelToken) -> None:
        module_id, version = task.module_id, task.module_version
        leased: list[str] = []
        pinned: list[str] = []
        working = False
        self.tasks.update(module_id, task.task_id, status="running")
        current = self.state.get_version(module_id, version)
        was_prepared = current is not None and current.preparation == "prepared"
        outcome: tuple[str, TaskError | None] = ("failed", None)
        try:
            self._enter_preparation_work(token)
            working = True
            manifest, root = self._manifest(module_id, version)
            # Other modules may finish, uninstall, and collect garbage while
            # this runs; pins keep these models until the commit below makes
            # the version record reference them.
            pinned = [model.sha256 for model in manifest.backend.models]
            self.store.pin(pinned)
            env_key, env_new, env_shared, reused = self._prepare_environment(
                task, root, manifest.backend.lock, manifest, token, leased
            )
            self._progress(task, 2, "models")
            _paths, model_new, model_shared = self.models.ensure_models(
                module_id,
                version,
                manifest.backend.models,
                cancel=token,
                progress=lambda _model_id, _received, _total: None,
            )
            self._progress(task, 3, "self-check")
            self._self_check(module_id, version, root, manifest, env_key, None, token)
            variant_environments: dict[str, str] = {}
            variant_failures: dict[str, str] = {}
            acceleration = self.state.settings_for(module_id).acceleration
            variant = next((item for item in manifest.backend.variants if item.id == acceleration), None)
            if variant is not None and self._platform_key in variant.platforms:
                try:
                    variant_key, _new, _shared, _reused = self._prepare_environment(
                        task, root, variant.lock, manifest, token, leased
                    )
                    self._self_check(module_id, version, root, manifest, variant_key, variant.id, token)
                    variant_environments[variant.id] = variant_key
                except WorkshopBackendError as exc:
                    if exc.code == "cancelled":
                        raise
                    variant_failures[variant.id] = exc.code
            with self._gc_lock:
                # Collection sees either this transaction's leases and pins
                # or the committed record that replaces them, never neither.
                token.raise_if_cancelled()
                self.state.update_version(
                    module_id,
                    version,
                    preparation="prepared",
                    failure_code=None,
                    environment_key=env_key,
                    variant_environments=variant_environments,
                    variant_failures=variant_failures,
                    model_sha256s=tuple(model.sha256 for model in manifest.backend.models),
                    footprint=InstallFootprint(
                        environment_new_bytes=env_new,
                        environment_shared_bytes=env_shared,
                        model_new_bytes=model_new,
                        model_shared_bytes=model_shared,
                        reused_environment=reused,
                    ),
                    prepared_at=utc_now(),
                )
            outcome = ("succeeded", None)
            log.info(
                "Workshop backend prepared",
                extra={
                    "event": "workshop_backend_prepare_done",
                    "module_id": module_id,
                    "version": version,
                    "environment_reused": reused,
                    "environment_new_bytes": env_new,
                    "model_new_bytes": model_new,
                },
            )
        except Exception as exc:  # noqa: BLE001 - preparation transaction boundary
            code = exc.code if isinstance(exc, WorkshopBackendError) else "backend-prepare-failed"
            message = str(exc) if isinstance(exc, WorkshopBackendError) else "Backend preparation failed."
            log.warning(
                "Workshop backend preparation failed",
                extra={
                    "event": "workshop_backend_prepare_failed",
                    "module_id": module_id,
                    "version": version,
                    "error_type": type(exc).__name__,
                    "error_code": code,
                    "error_message": getattr(exc, "tool_output", "") or message,
                },
            )
            try:
                if was_prepared:
                    self.state.update_version(module_id, version, failure_code=code)
                else:
                    self.state.update_version(module_id, version, preparation="failed", failure_code=code)
            except WorkshopBackendError:
                pass
            outcome = (
                "cancelled" if code == "cancelled" else "failed",
                TaskError(code=code, message=message[:500]),
            )
        finally:
            self._lease(leased, -1)
            self.store.unpin(pinned)
            if working:
                self._leave_preparation_work()
            with self._lock:
                self._preparations.pop(task.task_id, None)
            # Roll back anything this transaction added but nothing uses,
            # before the task reports a terminal state. On failure or cancel
            # nothing references the new files any more, so they go now (or
            # with the next pass if another preparation is still working).
            self.collect_garbage()
            status, error = outcome
            self.tasks.finish(module_id, task.task_id, status, error=error)  # type: ignore[arg-type]

    # ----- tasks ------------------------------------------------------------

    def _launch(
        self,
        module_id: str,
        version: str,
        root: Path,
        manifest: WorkshopManifestV2,
        env_key: str,
        variant: str | None,
    ) -> BackendLaunch:
        env_root = self.environments.path(env_key)
        if self.environments.get(env_key) is None:
            raise WorkshopBackendError("environment-missing", "The prepared backend environment is missing.")
        scratch = self._scratch_root / module_id
        return BackendLaunch(
            python=environment_python(env_root),
            bootstrap=self._bootstrap,
            backend_dir=root / "backend",
            entry=root / manifest.backend.entry,
            scratch_dir=scratch,
            work_dir=scratch / "work",
            extra_environment={
                "LUMINA_WORKSHOP_MODULE_ID": module_id,
                "LUMINA_WORKSHOP_MODULE_VERSION": version,
                "LUMINA_WORKSHOP_BACKEND_VARIANT": variant or "cpu",
                "LUMINA_WORKSHOP_MODELS_DIR": str(self.models.view_dir(module_id, version)),
            },
        )

    def _require_runnable(
        self,
        module_id: str,
        version: str,
    ) -> tuple[WorkshopManifestV2, Path, BackendVersionRecord]:
        """Checks a task passes when submitted and again before it runs.

        A queued task may wait behind a long one; disabling, a withdrawn
        review, or a Registry block in the meantime keeps it from running.
        """

        state = self._installed_state(module_id)
        if not state.enabled:
            raise WorkshopBackendError("module-disabled", "The Workshop module is disabled.")
        if version not in state.versions:
            raise WorkshopBackendError("module-version-unavailable", "The module version is not installed.")
        manifest, root = self._manifest(module_id, version)
        record = self._record(module_id, version)
        self._require_authorized(state, record, manifest)
        if record.preparation != "prepared" or record.environment_key is None:
            raise WorkshopBackendError("backend-not-prepared", "Prepare this module's backend first.")
        return manifest, root, record

    def _resolve_target(self, task: TaskRecord) -> RunTarget:
        module_id, version = task.module_id, task.module_version
        manifest, root, record = self._require_runnable(module_id, version)
        assert record.environment_key is not None
        models = {
            model.id: str(self.models.view_dir(module_id, version) / model.file_name)
            for model in manifest.backend.models
        }
        idle = float(manifest.backend.idle_timeout_seconds or self._settings.idle_timeout_seconds)
        cpu = RunTarget(
            version=version,
            variant=None,
            launch=self._launch(module_id, version, root, manifest, record.environment_key, None),
            models=models,
            idle_timeout_seconds=idle,
        )
        acceleration = self.state.settings_for(module_id).acceleration
        variant_key = record.variant_environments.get(acceleration or "")
        if acceleration and variant_key and acceleration not in record.variant_failures:
            return RunTarget(
                version=version,
                variant=acceleration,
                launch=self._launch(module_id, version, root, manifest, variant_key, acceleration),
                models=models,
                idle_timeout_seconds=idle,
                fallback=cpu,
            )
        return cpu

    def _variant_failed(self, module_id: str, version: str, variant: str) -> None:
        """Mark one module version's variant as failed to start (CPU fallback)."""

        record = self.state.get_version(module_id, version)
        if record is None or variant not in record.variant_environments:
            return
        failures = {**record.variant_failures, variant: "variant-start-failed"}
        self.state.update_version(module_id, version, variant_failures=failures)
        log.warning(
            "Workshop backend acceleration fell back to CPU",
            extra={
                "event": "workshop_backend_variant_fallback",
                "module_id": module_id,
                "version": version,
                "variant": variant,
            },
        )

    def submit(
        self,
        module_id: str,
        version: str,
        *,
        operation: str,
        params: dict[str, Any],
        inputs: Sequence[TaskInputFile],
        idempotency_key: str | None,
    ) -> TaskRecord:
        self._require_runnable(module_id, version)
        encoded = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_BACKEND_TASK_PARAMS_BYTES:
            raise WorkshopBackendError("task-params-too-large", "Backend task parameters exceed 64 KiB.")
        if len(inputs) > MAX_BACKEND_TASK_INPUTS:
            raise WorkshopBackendError("task-inputs-too-many", "Too many backend task inputs.")
        names: set[str] = set()
        for item in inputs:
            if (
                FILE_NAME_PATTERN.fullmatch(item.name) is None
                or item.name in names
                or SAFE_FILE_NAME_PATTERN.fullmatch(item.file_name) is None
                or item.file_name.endswith((".", " "))
                or not 0 < len(item.mime_type) <= 127
            ):
                raise WorkshopBackendError("task-input-invalid", "A backend task input is invalid.")
            if item.path.stat().st_size > MAX_BACKEND_TASK_FILE_BYTES:
                raise WorkshopBackendError("task-input-too-large", "A backend task input exceeds 64 MiB.")
            names.add(item.name)

        def prepare_files(_record: TaskRecord, inputs_dir: Path) -> tuple[TaskFile, ...]:
            files: list[TaskFile] = []
            for index, item in enumerate(inputs):
                destination = stored_input_path(inputs_dir, index, item.file_name)
                destination.parent.mkdir()
                shutil.copyfile(item.path, destination)
                data = destination.read_bytes()
                files.append(
                    TaskFile(
                        name=item.name,
                        file_name=item.file_name,
                        mime_type=item.mime_type,
                        size_bytes=len(data),
                        sha256=hashlib.sha256(data).hexdigest(),
                    )
                )
            return tuple(files)

        task, created = self.tasks.create(
            module_id=module_id,
            module_version=version,
            kind="operation",
            operation=operation,
            params=params,
            idempotency_key=idempotency_key,
            prepare_files=prepare_files,
        )
        if created:
            self._supervisor(module_id).enqueue(task.task_id)
            log.info(
                "Workshop backend task submitted",
                extra={
                    "event": "workshop_backend_task_submitted",
                    "module_id": module_id,
                    "version": version,
                    "task_id": task.task_id,
                    "operation": operation,
                },
            )
        return task

    def get_task(self, module_id: str, task_id: str) -> TaskRecord:
        return self.tasks.require(self._require_module_id(module_id), task_id)

    def list_tasks(self, module_id: str) -> tuple[TaskRecord, ...]:
        return self.tasks.list(self._require_module_id(module_id))

    def cancel_task(self, module_id: str, task_id: str) -> TaskRecord:
        record = self.tasks.require(self._require_module_id(module_id), task_id)
        if record.terminal:
            return record
        if record.kind == "prepare":
            with self._lock:
                entry = self._preparations.get(task_id)
            if entry is not None:
                entry[0].cancel()
            else:
                self.tasks.finish(module_id, task_id, "cancelled", error=TaskError(code="cancelled", message="The task was cancelled."))
            return self.tasks.require(module_id, task_id)
        self.tasks.update(module_id, task_id, cancel_requested=True)
        result = self._supervisor(module_id).cancel(task_id)
        return result or self.tasks.require(module_id, task_id)

    def delete_task(self, module_id: str, task_id: str) -> RemovalOutcome:
        return self.tasks.delete(self._require_module_id(module_id), task_id)

    def output_file(self, module_id: str, task_id: str, name: str) -> tuple[Path, TaskFile]:
        record = self.tasks.require(self._require_module_id(module_id), task_id)
        if record.status != "succeeded":
            raise WorkshopBackendError("task-output-unavailable", "The backend task has no finished outputs.")
        entry = next((item for item in record.outputs if item.name == name), None)
        if entry is None:
            raise WorkshopBackendError("task-output-not-found", "The backend task output does not exist.")
        directory = self.tasks.outputs_dir(record).resolve()
        path = (directory / entry.file_name).resolve()
        if path.parent != directory or not path.is_file() or path.is_symlink():
            raise WorkshopBackendError("task-output-not-found", "The backend task output does not exist.")
        return path, entry

    def touch_presence(self, module_id: str) -> None:
        self._supervisor(self._require_module_id(module_id)).touch_presence()

    def _task_finished(self, record: TaskRecord) -> None:
        log.info(
            "Workshop backend task finished",
            extra={
                "event": "workshop_backend_task_done" if record.status == "succeeded" else "workshop_backend_task_ended",
                "module_id": record.module_id,
                "version": record.module_version,
                "task_id": record.task_id,
                "task_status": record.status,
                "error_code": record.error.code if record.error else None,
            },
        )
        self._release_if_retired(record.module_id, record.module_version, finished_task=record.task_id)

    def _release_if_retired(self, module_id: str, version: str, *, finished_task: str | None = None) -> None:
        """Finish retiring ``version`` in the background if no slot keeps it.

        Runs when a task of the version ends and when a process of the version
        is released: either may be the moment its last user goes away. Callers
        may hold the supervisor's lock, so this takes no runtime lock.
        """

        try:
            state = self._installer().get(module_id)
        except WorkshopInstallError:
            return
        if state is not None and version not in {
            state.active_version,
            state.previous_version,
            state.candidate_version,
        }:
            threading.Thread(target=self._release_retired, args=(module_id, finished_task), daemon=True).start()

    def _release_retired(self, module_id: str, finished_task: str | None = None) -> None:
        try:
            installer = self._installer()
            state = installer.get(module_id)
            if state is None:
                return
            keep = {
                value
                for value in (state.active_version, state.previous_version, state.candidate_version)
                if value is not None
            }
            with self._lock:
                supervisor = self._supervisors.get(module_id)
            if supervisor is not None:
                supervisor.release_idle_version(keep, finished_task)
            installer.prune_retired_versions(module_id)
        except (WorkshopInstallError, OSError):
            return
        self.collect_garbage()

    # ----- stop / enable / acceleration ----------------------------------

    def stop_module(self, module_id: str, *, code: str, message: str, grace_seconds: float | None = None) -> None:
        """Cancel this module's tasks and preparations; end its processes."""

        with self._lock:
            supervisor = self._supervisors.get(module_id)
            preparations = [
                (token, thread)
                for token, thread, prepared_module, _version in self._preparations.values()
                if prepared_module == module_id
            ]
        for token, _thread in preparations:
            token.cancel()
        if supervisor is not None:
            supervisor.stop(code=code, message=message, grace_seconds=grace_seconds)
        for record in self.tasks.list(module_id):
            if not record.terminal and record.kind == "operation":
                self.tasks.finish(module_id, record.task_id, "cancelled", error=TaskError(code=code, message=message))
        for _token, thread in preparations:
            thread.join(timeout=60)
        log.info(
            "Workshop backend stopped",
            extra={"event": "workshop_backend_stop_done", "module_id": module_id, "stop_reason": code},
        )

    def stop_backend_process(self, module_id: str) -> None:
        """User action from the manager: end the running backend now."""

        with self._lock:
            supervisor = self._supervisors.get(self._require_module_id(module_id))
        if supervisor is not None:
            supervisor.stop_idle_process()

    def module_disabled(self, module_id: str) -> None:
        self.stop_module(module_id, code="module-disabled", message="The module was disabled.")

    def set_acceleration(self, module_id: str, variant_id: str | None) -> dict[str, Any]:
        state = self._installed_state(module_id)
        version = state.active_version or state.candidate_version
        if version is None:
            raise WorkshopBackendError("module-version-unavailable", "The module has no usable version.")
        manifest, _root = self._manifest(module_id, version)
        if variant_id is not None and not any(item.id == variant_id for item in manifest.backend.variants):
            raise WorkshopBackendError("variant-unknown", "This module does not declare that acceleration option.")
        previous = self.state.settings_for(module_id).acceleration
        self.state.set_settings(ModuleBackendSettings(module_id=module_id, acceleration=variant_id), module_id)
        if previous != variant_id:
            with self._lock:
                supervisor = self._supervisors.get(module_id)
            if supervisor is not None and supervisor.process_alive():
                supervisor.stop_idle_process()
        if variant_id is None:
            # Turning acceleration off releases every variant environment.
            for record in self.state.read().versions:
                if record.module_id == module_id and (record.variant_environments or record.variant_failures):
                    self.state.update_version(module_id, record.version, variant_environments={}, variant_failures={})
            self.collect_garbage()
        else:
            record = self._record(module_id, version)
            if record.preparation == "prepared" and variant_id not in record.variant_environments:
                # Prepares only what is missing; the CPU backend stays usable.
                self.start_preparation(module_id, version)
        return self.describe(module_id, version)

    # ----- uninstall and reclamation -------------------------------------

    def uninstall_module(
        self,
        module_id: str,
        *,
        delete_projects: bool,
        delete_task_data: bool,
        retain_models: bool,
    ) -> tuple[InstalledModuleState | None, UninstallReport]:
        """Stop, remove code, release references, reclaim, and report.

        依次停止任务与进程、移除模块代码、释放引用、回收无人使用的内容并生成报告。
        """

        self._require_module_id(module_id)
        report = UninstallReport()
        self.stop_module(module_id, code="module-uninstalled", message="The module was uninstalled.")
        installer = self._installer()
        code_bytes = releasable_bytes(installer.module_path(module_id))
        project_bytes = releasable_bytes(installer.project_data_path(module_id)) if delete_projects else 0
        document = self.state.read()
        own_records = [record for record in document.versions if record.module_id == module_id]
        own_envs = {
            key
            for record in own_records
            for key in (record.environment_key, *record.variant_environments.values())
            if key
        }
        own_shared_inodes: dict[tuple[int, int], int] = {}
        for key in own_envs:
            own_shared_inodes.update(self._linked_inodes(key))
        own_models: dict[str, tuple[str, int]] = {}
        for record in own_records:
            try:
                manifest, _root = self._manifest(module_id, record.version)
            except WorkshopBackendError:
                continue
            for model in manifest.backend.models:
                own_models[model.sha256] = (model.file_name, model.size_bytes)
        # Retention becomes a reference before this module's versions stop
        # counting, so no collection in between can see the model unused.
        with self._uninstall_commit_lock:
            added, kept_models = self._retain_models(module_id, own_models) if retain_models else (set(), [])
            try:
                state = installer.uninstall(module_id, delete_projects=delete_projects)
            except Exception:
                if added:
                    self.state.change_retained_models(
                        lambda current: tuple(item for item in current if item.sha256 not in added)
                    )
                raise
        report.cleared.append({"kind": "module-code", "bytes": code_bytes})
        if delete_projects:
            report.cleared.append({"kind": "projects", "bytes": project_bytes})
        else:
            report.retained.append({"kind": "projects"})
        self.state.remove_versions(lambda record: record.module_id == module_id)
        self.state.set_settings(None, module_id)
        view_result = self.models.remove_view(module_id)
        if view_result.freed_bytes:
            # Copied views on volumes without hard links.
            report.cleared.append({"kind": "model-files", "bytes": view_result.freed_bytes})
        scratch = self._scratch_root / module_id
        cache_result = remove_tree(scratch)
        report.cleared.append({"kind": "module-cache", "bytes": cache_result.freed_bytes})
        # Views and scratch files still in use are retried by every
        # collection pass (the one below included); task data is user data
        # and is retried only when the user deletes it again.
        task_leftovers: list[str] = []
        if delete_task_data:
            task_result = self.tasks.delete_module(module_id)
            report.cleared.append({"kind": "task-data", "bytes": task_result.freed_bytes})
            task_leftovers = task_result.pending
        else:
            usage = self.tasks.module_usage().get(module_id)
            if usage is not None:
                report.retained.append({"kind": "task-data", "count": usage[0], "bytes": usage[1]})
        for item in kept_models:
            report.retained.append({"kind": "model", "label": item["file_name"], "bytes": item["bytes"]})
        remaining_users = self._model_users()
        garbage = self.collect_garbage()
        environment_users = self._environment_users()
        surviving_own = {key for key in own_envs if key in environment_users}
        overlap: set[tuple[int, int]] = set()
        sharing_modules: set[str] = set()
        for environment in self.environments.list():
            if environment.key in surviving_own:
                continue
            common = set(self._linked_inodes(environment.key)) & set(own_shared_inodes)
            if common:
                overlap |= common
                sharing_modules |= environment_users.get(environment.key, set())
        if overlap and sharing_modules:
            report.shared.append(
                {
                    "kind": "shared-files",
                    "bytes": sum(own_shared_inodes[item] for item in overlap),
                    "users": sorted(sharing_modules),
                }
            )
        for key in sorted(own_envs):
            users = sorted(environment_users.get(key, set()))
            if users:
                record = self.environments.get(key)
                report.shared.append(
                    {
                        "kind": "environment",
                        "label": key[:12],
                        "bytes": (record.new_bytes + record.shared_bytes) if record else 0,
                        "users": users,
                    }
                )
        if garbage.environment_bytes:
            report.cleared.append(
                {"kind": "environments", "count": len(garbage.environments), "bytes": garbage.environment_bytes}
            )
        if garbage.object_bytes:
            report.cleared.append({"kind": "shared-files", "bytes": garbage.object_bytes})
        if garbage.interpreter_bytes or garbage.interpreters:
            report.cleared.append(
                {"kind": "interpreters", "count": len(garbage.interpreters), "bytes": garbage.interpreter_bytes}
            )
        for sha256, (file_name, size) in own_models.items():
            users = sorted(remaining_users.get(sha256, set()) - {module_id})
            if users:
                report.shared.append({"kind": "model", "label": file_name, "bytes": size, "users": users})
        for path in garbage.pending:
            report.failed.append({"kind": "file", "label": Path(path).name, "reason": "in-use", "will_retry": True})
        for path in task_leftovers:
            report.failed.append({"kind": "file", "label": Path(path).name, "reason": "in-use", "will_retry": False})
        log.info(
            "Workshop module backend resources released",
            extra={
                "event": "workshop_backend_uninstall_done",
                "module_id": module_id,
                "freed_bytes": garbage.freed_bytes,
                "pending_count": len(report.failed),
                "delete_task_data": delete_task_data,
                "retain_models": retain_models,
            },
        )
        return state, report

    def _retain_models(
        self,
        module_id: str,
        models: dict[str, tuple[str, int]],
    ) -> tuple[set[str], list[dict[str, Any]]]:
        """Record the user's choice to keep these models after uninstall.

        The store object itself is the kept copy on every volume, so keeping
        a model never duplicates it. Returns the digests this call added (to
        withdraw if the uninstall fails) and every requested model now kept,
        including ones an earlier uninstall already kept.
        """

        # Runs while the module's versions still count as references, so a
        # concurrent collection keeps these models either way. The list edit
        # itself is one state update, so concurrent uninstalls keep all choices.
        added: set[str] = set()

        def keep(current: tuple[RetainedModel, ...]) -> tuple[RetainedModel, ...]:
            known = {item.sha256 for item in current}
            new: list[RetainedModel] = []
            for sha256, (file_name, size) in models.items():
                if sha256 in known or not self.store.has(sha256):
                    continue
                new.append(
                    RetainedModel(
                        sha256=sha256,
                        file_name=file_name,
                        module_id=module_id,
                        size_bytes=size,
                        retained_at=utc_now(),
                    )
                )
                added.add(sha256)
            return (*current, *new)

        kept = {item.sha256 for item in self.state.change_retained_models(keep)}
        return added, [
            {"file_name": file_name, "bytes": size}
            for sha256, (file_name, size) in models.items()
            if sha256 in kept
        ]

    def _linked_inodes(self, key: str) -> dict[tuple[int, int], int]:
        """Return hard-linked files of one environment by inode and size."""

        found: dict[tuple[int, int], int] = {}
        root = self.environments.path(key)
        if not root.is_dir():
            return found
        for directory, _dirs, files in os.walk(root):
            for name in files:
                try:
                    info = (Path(directory) / name).lstat()
                except OSError:
                    continue
                if info.st_nlink > 1:
                    found[(info.st_dev, info.st_ino)] = info.st_size
        return found

    def _installed_versions(self) -> dict[str, set[str]]:
        installed: dict[str, set[str]] = {}
        for state in self._installer().list():
            installed[state.module_id] = set(state.versions)
        return installed

    def _live_records(self) -> list[BackendVersionRecord]:
        installed = self._installed_versions()
        unfinished = {(record.module_id, record.module_version) for record in self.tasks.unfinished()}
        live: list[BackendVersionRecord] = []
        for record in self.state.read().versions:
            if record.version in installed.get(record.module_id, set()) or (
                record.module_id,
                record.version,
            ) in unfinished:
                live.append(record)
        return live

    def _environment_users(self) -> dict[str, set[str]]:
        users: dict[str, set[str]] = {}
        for record in self._live_records():
            if record.preparation not in {"prepared", "preparing"}:
                continue
            for key in (record.environment_key, *record.variant_environments.values()):
                if key:
                    users.setdefault(key, set()).add(record.module_id)
        return users

    def _model_users(self) -> dict[str, set[str]]:
        users: dict[str, set[str]] = {}
        for record in self._live_records():
            for sha256 in record.model_sha256s:
                users.setdefault(sha256, set()).add(record.module_id)
        return users

    def collect_garbage(self) -> GarbageReport:
        """Remove unreferenced environments, objects, and interpreters.

        Order matters: environments and model views drop their links first,
        the download cache is cleaned, then objects whose link count shows no
        remaining user are deleted, and finally unused managed interpreters.
        """

        report = GarbageReport()
        with self._gc_lock:
            with self._lock:
                leased = set(self._leased_environments)
            live = self._live_records()
            referenced_envs = set(leased)
            live_versions: set[tuple[str, str]] = set()
            # Models are referenced logically as well as by links: a view on
            # a volume without hard links is a copy, so link counts alone
            # would drop a model an installed version or the user still keeps.
            referenced_models: set[str] = {item.sha256 for item in self.state.read().retained_models}
            for record in live:
                live_versions.add((record.module_id, record.version))
                referenced_models.update(record.model_sha256s)
                if record.preparation in {"prepared", "preparing"}:
                    referenced_envs.update(
                        key for key in (record.environment_key, *record.variant_environments.values()) if key
                    )
            # Records of versions no longer installed and not needed by tasks.
            now = datetime.now(timezone.utc)

            def retired(record: BackendVersionRecord) -> bool:
                if (record.module_id, record.version) in live_versions:
                    return False
                try:
                    age = (now - datetime.fromisoformat(record.recorded_at)).total_seconds()
                except ValueError:
                    age = _FRESH_RECORD_SECONDS
                return age >= _FRESH_RECORD_SECONDS or record.preparation != "unprepared"

            self.state.remove_versions(retired)
            for environment in self.environments.list():
                if environment.key in referenced_envs:
                    continue
                outcome = self.environments.remove(
                    environment.key,
                    still_needed=lambda key=environment.key: self._is_leased(key),
                )
                if outcome is None:
                    continue
                report.environment_bytes += outcome.freed_bytes
                report.environments.append(environment.key)
                report.pending.extend(outcome.pending)
            # Leftovers of removals whose files were in use; retried here from
            # what is on disk now, before objects, so freed links count too.
            orphans = self.environments.remove_orphans(skip=self._is_leased)
            report.environment_bytes += orphans.freed_bytes
            report.pending.extend(orphans.pending)
            for module_id, version in self.models.views():
                if (module_id, version) not in live_versions:
                    try:
                        outcome = self.models.remove_view(module_id, version)
                    except (WorkshopBackendError, ValueError):
                        continue
                    report.other_bytes += outcome.freed_bytes
                    report.pending.extend(outcome.pending)
            maintenance = self._begin_maintenance()
            try:
                if maintenance:
                    self._clean_transient_files(report)
                objects = self.store.collect_garbage(keep=referenced_models)
                report.object_bytes += objects.freed_bytes
                report.pending.extend(objects.pending)
                if maintenance:
                    self._release_unused_interpreters(report)
            finally:
                if maintenance:
                    self._end_maintenance()
            installed_modules = set(self._installed_versions())
            for scratch in self._scratch_root.iterdir():
                if scratch.is_dir() and scratch.name not in installed_modules:
                    outcome = remove_tree(scratch)
                    report.other_bytes += outcome.freed_bytes
                    report.pending.extend(outcome.pending)
            self._record_pending(report.pending)
        if report.freed_bytes or report.pending:
            log.info(
                "Workshop backend storage reclaimed",
                extra={
                    "event": "workshop_backend_gc_done",
                    "freed_bytes": report.freed_bytes,
                    "environment_count": len(report.environments),
                    "pending_count": len(report.pending),
                },
            )
        return report

    def _clean_transient_files(self, report: GarbageReport) -> None:
        """Staging, download cache, and temporary downloads (no preparation runs)."""

        staging = self.environments.remove_staging_leftovers()
        temporary = self.store.clear_temporary()
        report.other_bytes += staging.freed_bytes + temporary.freed_bytes
        report.pending.extend([*staging.pending, *temporary.pending])
        if self._uv is not None:
            try:
                self._uv.clean_cache()
            except WorkshopBackendError as exc:
                log.warning(
                    "Workshop backend download cache cleanup failed",
                    extra={
                        "event": "workshop_backend_cache_clean_failed",
                        "error_code": exc.code,
                        "error_message": getattr(exc, "tool_output", "") or str(exc),
                    },
                )

    def _release_unused_interpreters(self, report: GarbageReport) -> None:
        """Managed interpreters no environment uses (no preparation runs)."""

        if self._interpreters is None:
            return
        needed = {environment.interpreter_key for environment in self.environments.list()}
        for interpreter in self._interpreters.installed():
            if interpreter.key in needed or not interpreter.managed:
                continue
            try:
                report.interpreter_bytes += self._interpreters.release(interpreter)
                report.interpreters.append(interpreter.key)
            except WorkshopBackendError as exc:
                report.pending.append(str(interpreter.executable))
                log.warning(
                    "Workshop backend interpreter cleanup failed",
                    extra={
                        "event": "workshop_backend_interpreter_clean_failed",
                        "error_code": exc.code,
                        "error_message": str(exc),
                    },
                )
        if (
            self._uv is not None
            and isinstance(self._interpreters, ManagedInterpreterProvider)
            and not needed
            and not self._interpreters.installed()
            and self._uv.python_install_dir.exists()
        ):
            # Only uv metadata or leftovers of a removal remain; retried on
            # every pass until the directory is gone.
            report.pending.extend(remove_tree(self._uv.python_install_dir).pending)

    def _record_pending(self, paths: list[str]) -> None:
        """Remember what this pass could not delete, for the storage overview.

        Nothing is ever deleted from this list later. Each pass derives
        garbage from current references and leases again, so a name that is
        in use again (same content, environment key, version, or interpreter)
        cannot be removed by an earlier deletion attempt.
        """

        earlier = {item.path: item for item in self.state.read().pending}
        current = tuple(
            earlier.get(path) or PendingReclaim(path=path, reason="in-use", since=utc_now())
            for path in dict.fromkeys(paths)
            if self._owned_path(Path(path))
        )
        self.state.set_pending(current)

    def _owned_path(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root.resolve())
            return True
        except (OSError, ValueError):
            return False

    def delete_retained_model(self, sha256: str) -> int:
        def drop(current: tuple[RetainedModel, ...]) -> tuple[RetainedModel, ...]:
            if not any(item.sha256 == sha256 for item in current):
                raise WorkshopBackendError("model-not-retained", "This model is not kept by the user.")
            return tuple(item for item in current if item.sha256 != sha256)

        self.state.change_retained_models(drop)
        # Freed only when no installed version still uses the same file.
        return self.collect_garbage().object_bytes

    def delete_module_task_data(self, module_id: str) -> int:
        self._require_module_id(module_id)
        if any(not record.terminal for record in self.tasks.list(module_id)):
            raise WorkshopBackendError("task-active", "Cancel running tasks before deleting task data.")
        return self.tasks.delete_module(module_id).freed_bytes

    def storage_overview(self) -> dict[str, Any]:
        environment_users = self._environment_users()
        model_users = self._model_users()
        retained = self.state.read().retained_models
        environments = []
        for environment in self.environments.list():
            environments.append(
                {
                    "key": environment.key,
                    "python": environment.python_version,
                    "packages": len(environment.packages),
                    "exclusive_bytes": releasable_bytes(self.environments.path(environment.key)),
                    "logical_bytes": environment.new_bytes + environment.shared_bytes,
                    "users": sorted(environment_users.get(environment.key, set())),
                }
            )
        objects, object_bytes = self.store.usage()
        copy_files, copy_bytes = self.models.copy_usage()
        interpreters = []
        if self._interpreters is not None:
            for interpreter in self._interpreters.installed():
                interpreters.append(
                    {
                        "key": interpreter.key,
                        "python": interpreter.python_version,
                        "managed": interpreter.managed,
                    }
                )
        tasks = [
            {"module_id": module_id, "task_count": count, "bytes": size}
            for module_id, (count, size) in sorted(self.tasks.module_usage().items())
        ]
        return {
            "environments": environments,
            "interpreters": interpreters,
            "shared_store": {"objects": objects, "bytes": object_bytes},
            # Views that are full copies because the volume lacks hard links.
            "model_copies": {"files": copy_files, "bytes": copy_bytes},
            "models": [
                {"sha256": sha256, "users": sorted(users), "bytes": self.store.object_size(sha256) or 0}
                for sha256, users in sorted(model_users.items())
            ],
            "retained_models": [item.model_dump(mode="json") for item in retained],
            "task_data": tasks,
            "pending": [item.model_dump(mode="json") for item in self.state.read().pending],
            "tool_available": self.tool_available,
        }

    # ----- lifecycle ------------------------------------------------------

    def startup(self) -> None:
        """Reconcile after a previous run, including abrupt host exits.

        结束上次遗留的后端进程，把未完成任务标记为已中断，并重试待回收项。
        """

        # Tasks of the previous run end as interrupted first, so a leftover
        # process terminated below can never be reported as a crash.
        interrupted = self.tasks.mark_unfinished_interrupted(
            code="host-restarted",
            message="Lumina stopped before this task finished.",
        )
        for record_path in self._processes_root.glob("*.json"):
            try:
                identity = json.loads(record_path.read_text(encoding="utf-8"))
                if kill_recorded_process(int(identity["pid"]), float(identity["createTime"])):
                    log.warning(
                        "Leftover Workshop backend process terminated",
                        extra={
                            "event": "workshop_backend_leftover_killed",
                            "module_id": identity.get("moduleId"),
                            "pid": identity.get("pid"),
                        },
                    )
            except (OSError, ValueError, KeyError, TypeError):
                pass
            try:
                record_path.unlink(missing_ok=True)
            except OSError:
                pass
        for record in self.state.read().versions:
            if record.preparation == "preparing":
                self.state.update_version(
                    record.module_id,
                    record.version,
                    preparation="failed",
                    failure_code="interrupted",
                )
        self.tasks.purge_expired()
        report = self.collect_garbage()
        log.info(
            "Workshop backend runtime reconciled",
            extra={
                "event": "workshop_backend_startup_done",
                "interrupted_tasks": interrupted,
                "freed_bytes": report.freed_bytes,
                "tool_available": self.tool_available,
            },
        )

    def purge_expired_task_data(self) -> None:
        self.tasks.purge_expired()

    def shutdown(self) -> None:
        """Stop every backend and preparation when the host exits."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            supervisors = list(self._supervisors.values())
            preparations = list(self._preparations.values())
        for token, _thread, _module, _version in preparations:
            token.cancel()
        for supervisor in supervisors:
            supervisor.stop(code="host-exit", message="Lumina exited before this task finished.", grace_seconds=1.0)
        for _token, thread, _module, _version in preparations:
            thread.join(timeout=10)
        for record in self.tasks.unfinished():
            self.tasks.finish(
                record.module_id,
                record.task_id,
                "interrupted",
                error=TaskError(code="host-exit", message="Lumina exited before this task finished."),
            )
        log.info("Workshop backend runtime stopped", extra={"event": "workshop_backend_shutdown_done"})
