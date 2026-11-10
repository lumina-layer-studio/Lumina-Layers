"""Transactional installation lifecycle for Creative Workshop modules."""

from __future__ import annotations

import errno
import os
import shutil
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from .errors import WorkshopInstallError, WorkshopPackageError
from .install_store import InstalledModuleState, InstallStateStore
from .models import (
    MODULE_ID_PATTERN,
    InspectedWorkshopPackage,
    semver_sort_key,
    validate_semver,
)
from .package_validator import (
    extract_inspected_package,
    inspect_workshop_package,
)


InstallSource = Literal["registry", "github", "local", "seed"]
AfterExtract = Callable[[InspectedWorkshopPackage, Path], None]
DirectoryReplace = Callable[[Path, Path], None]
VersionInUse = Callable[[str, str], bool]
_MODULE_LOCKS_GUARD = threading.Lock()
_MODULE_LOCKS: dict[tuple[str, str], threading.RLock] = {}


def _noop_after_extract(
    _inspected: InspectedWorkshopPackage,
    _staging_path: Path,
) -> None:
    return None


def _version_never_in_use(_module_id: str, _version: str) -> bool:
    return False


def _canonical_versions(values: set[str]) -> tuple[str, ...]:
    return tuple(sorted(values, key=semver_sort_key))


def _replace_state(
    state: InstalledModuleState,
    **updates: object,
) -> InstalledModuleState:
    value = state.model_dump(mode="python")
    value.update(updates)
    return InstalledModuleState.model_validate(value)


class WorkshopInstaller:
    """Install and switch immutable module versions using atomic renames.

    通过原子重命名安装并切换不可变的模块版本。
    """

    def __init__(
        self,
        *,
        data_dir: str | Path,
        after_extract: AfterExtract | None = None,
        directory_replace: DirectoryReplace = os.replace,
        version_in_use: VersionInUse | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.modules_dir = self.data_dir / "modules"
        self.staging_dir = self.data_dir / "staging"
        self.projects_dir = self.data_dir / "projects"
        self.state_path = self.data_dir / "install-state.json"
        for directory in (
            self.data_dir,
            self.modules_dir,
            self.staging_dir,
            self.projects_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._store = InstallStateStore(self.state_path)
        self._after_extract = after_extract or _noop_after_extract
        self._directory_replace = directory_replace
        # Backend tasks may still need a version that rollback retention
        # would prune; such versions stay installed until they are released.
        self._version_in_use = version_in_use or _version_never_in_use

    def _busy_versions(
        self,
        module_id: str,
        candidates: set[str],
    ) -> set[str]:
        return {
            version
            for version in candidates
            if self.version_path(module_id, version).is_dir()
            and self._version_in_use(module_id, version)
        }

    def _validate_module_id(self, module_id: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(module_id) is None:
            raise WorkshopInstallError("invalid Workshop module ID")
        return module_id

    def _validate_version(self, version: str) -> str:
        try:
            return validate_semver(version)
        except ValueError as exc:
            raise WorkshopInstallError(
                "invalid Workshop module version"
            ) from exc

    def _lock_for(self, module_id: str) -> threading.RLock:
        key = (os.fspath(self.data_dir), module_id)
        with _MODULE_LOCKS_GUARD:
            return _MODULE_LOCKS.setdefault(
                key,
                threading.RLock(),
            )

    def module_path(self, module_id: str) -> Path:
        """Return the private module-code directory for one safe ID.

        返回一个安全模块 ID 对应的私有代码目录。
        """

        return self.modules_dir / self._validate_module_id(module_id)

    def version_path(self, module_id: str, version: str) -> Path:
        """Return one immutable installed-version directory.

        返回一个不可变的已安装版本目录。
        """

        return self.module_path(module_id) / self._validate_version(version)

    def project_data_path(self, module_id: str) -> Path:
        """Return the host-owned project namespace path for one module.

        返回一个模块对应的宿主项目命名空间路径。
        """

        return self.projects_dir / self._validate_module_id(module_id)

    def list(self) -> tuple[InstalledModuleState, ...]:
        return self._store.list()

    def get(self, module_id: str) -> InstalledModuleState | None:
        return self._store.get(self._validate_module_id(module_id))

    def _identity_is_compatible(
        self,
        existing: InstalledModuleState,
        *,
        source_repository: str,
        official: bool,
    ) -> None:
        if existing.official != official:
            raise WorkshopInstallError(
                "module official identity cannot change"
            )
        if existing.source_repository != source_repository:
            raise WorkshopInstallError(
                "module source repository cannot change"
            )

    def _candidate_state(
        self,
        *,
        existing: InstalledModuleState | None,
        inspected: InspectedWorkshopPackage,
        source: InstallSource,
        source_repository: str,
        official: bool,
        restore_official: bool,
    ) -> tuple[InstalledModuleState, set[str]]:
        version = inspected.manifest.version
        if existing is None:
            return (
                InstalledModuleState(
                    module_id=inspected.manifest.id,
                    source=source,
                    source_repository=source_repository,
                    official=official,
                    enabled=True,
                    active_version=None,
                    previous_version=None,
                    candidate_version=version,
                    versions=(version,),
                    official_uninstalled=False,
                    consecutive_start_failures=0,
                ),
                set(),
            )

        self._identity_is_compatible(
            existing,
            source_repository=source_repository,
            official=official,
        )
        if (
            existing.official_uninstalled
            and source == "seed"
            and not restore_official
        ):
            raise WorkshopInstallError(
                "official module was uninstalled by the user"
            )

        protected = {
            value
            for value in (
                existing.active_version,
                existing.previous_version,
                version,
            )
            if value is not None
        }
        removed_versions = set(existing.versions) - protected
        busy = self._busy_versions(existing.module_id, removed_versions)
        protected |= busy
        removed_versions -= busy
        state = _replace_state(
            existing,
            source=source,
            source_repository=source_repository,
            enabled=True
            if existing.official_uninstalled
            else existing.enabled,
            candidate_version=version,
            versions=_canonical_versions(protected),
            official_uninstalled=False,
        )
        return state, removed_versions

    def install_candidate(
        self,
        archive_path: str | Path,
        *,
        source: InstallSource,
        source_repository: str,
        official: bool,
        restore_official: bool = False,
    ) -> InstalledModuleState:
        """Inspect and atomically stage one non-active candidate version.

        检查并原子暂存一个尚未激活的候选版本。
        """

        if source not in {"registry", "github", "local", "seed"}:
            raise WorkshopInstallError("unsupported module install source")
        if official and source not in {"registry", "seed"}:
            raise WorkshopInstallError(
                "only Registry or seed installs may be official"
            )
        if restore_official and (source != "seed" or not official):
            raise WorkshopInstallError(
                "official restore requires an official seed package"
            )
        if "\x00" in source_repository or len(source_repository) > 2048:
            raise WorkshopInstallError("invalid source repository")

        inspected = inspect_workshop_package(archive_path)
        module_id = inspected.manifest.id
        version = inspected.manifest.version
        with self._lock_for(module_id):
            existing = self._store.get(module_id)
            if restore_official and (
                existing is None
                or not existing.official
                or not existing.official_uninstalled
            ):
                raise WorkshopInstallError(
                    "official module is not awaiting seed restore"
                )
            if (
                existing is not None
                and existing.official_uninstalled
                and source == "seed"
                and not restore_official
            ):
                raise WorkshopInstallError(
                    "official module was uninstalled by the user"
                )
            target = self.version_path(module_id, version)
            if target.exists():
                if (
                    existing is not None
                    and existing.candidate_version == version
                ):
                    return existing
                raise WorkshopInstallError(
                    "module version is already installed"
                )

            transaction_root = (
                self.staging_dir
                / f"{module_id}-{version}-{uuid.uuid4().hex}"
            )
            staging_payload = transaction_root / "payload"
            transaction_root.mkdir(parents=False, exist_ok=False)
            moved = False
            state_committed = False
            removed_versions: set[str] = set()
            try:
                extract_inspected_package(inspected, staging_payload)
                self._after_extract(inspected, staging_payload)
                target.parent.mkdir(parents=True, exist_ok=True)
                if (
                    staging_payload.stat().st_dev
                    != target.parent.stat().st_dev
                ):
                    raise WorkshopInstallError(
                        "candidate and module store must share the same filesystem"
                    )
                try:
                    self._directory_replace(staging_payload, target)
                except OSError as exc:
                    if exc.errno == errno.EXDEV:
                        raise WorkshopInstallError(
                            "candidate and module store must share the same filesystem"
                        ) from exc
                    raise
                moved = True

                candidate_state, removed_versions = self._candidate_state(
                    existing=existing,
                    inspected=inspected,
                    source=source,
                    source_repository=source_repository,
                    official=official,
                    restore_official=restore_official,
                )
                self._store.upsert(candidate_state)
                state_committed = True
            except (WorkshopInstallError, WorkshopPackageError):
                raise
            except Exception as exc:
                raise WorkshopInstallError(
                    "candidate installation failed"
                ) from exc
            finally:
                if moved and not state_committed:
                    self._remove_tree(target)
                self._remove_tree(transaction_root)

            for removed_version in removed_versions:
                self._remove_tree(
                    self.version_path(module_id, removed_version)
                )
            return candidate_state

    def _require_state(self, module_id: str) -> InstalledModuleState:
        state = self._store.get(module_id)
        if state is None:
            raise WorkshopInstallError("Workshop module is not installed")
        return state

    def activate(
        self,
        module_id: str,
        version: str,
    ) -> InstalledModuleState:
        """Activate an installed version after its sandbox health check.

        在沙箱健康检查通过后激活一个已安装版本。
        """

        module_id = self._validate_module_id(module_id)
        version = self._validate_version(version)
        with self._lock_for(module_id):
            state = self._require_state(module_id)
            if (
                version not in state.versions
                or not self.version_path(module_id, version).is_dir()
            ):
                raise WorkshopInstallError(
                    "Workshop module version is not installed"
                )
            previous = (
                state.active_version
                if state.active_version != version
                else state.previous_version
            )
            retained = {
                value
                for value in (version, previous)
                if value is not None
            }
            retained |= self._busy_versions(
                module_id,
                set(state.versions) - retained,
            )
            replacement = _replace_state(
                state,
                enabled=True,
                active_version=version,
                previous_version=previous,
                candidate_version=None,
                versions=_canonical_versions(retained),
                official_uninstalled=False,
                consecutive_start_failures=0,
            )
            self._store.upsert(replacement)
            self._prune_versions(module_id, retained)
            return replacement

    def rollback(self, module_id: str) -> InstalledModuleState:
        """Swap the active version with the single rollback version.

        交换当前激活版本与唯一回滚版本。
        """

        module_id = self._validate_module_id(module_id)
        with self._lock_for(module_id):
            state = self._require_state(module_id)
            previous = state.previous_version
            if (
                previous is None
                or not self.version_path(module_id, previous).is_dir()
            ):
                raise WorkshopInstallError(
                    "Workshop module has no rollback version"
                )
            retained = {
                value
                for value in (previous, state.active_version)
                if value is not None
            }
            retained |= self._busy_versions(
                module_id,
                set(state.versions) - retained,
            )
            replacement = _replace_state(
                state,
                enabled=True,
                active_version=previous,
                previous_version=state.active_version,
                candidate_version=None,
                versions=_canonical_versions(retained),
                consecutive_start_failures=0,
            )
            self._store.upsert(replacement)
            self._prune_versions(module_id, retained)
            return replacement

    def discard_candidate(
        self,
        module_id: str,
    ) -> InstalledModuleState:
        """Remove an unactivated candidate while preserving active code.

        删除未激活候选版本，同时保留当前代码。
        """

        module_id = self._validate_module_id(module_id)
        with self._lock_for(module_id):
            state = self._require_state(module_id)
            candidate = state.candidate_version
            if candidate is None:
                return state
            retained = {
                value
                for value in (
                    state.active_version,
                    state.previous_version,
                )
                if value is not None
            }
            retained |= self._busy_versions(
                module_id,
                set(state.versions) - retained,
            )
            replacement = _replace_state(
                state,
                candidate_version=None,
                versions=_canonical_versions(retained),
            )
            self._store.upsert(replacement)
            if candidate not in retained:
                self._remove_tree(
                    self.version_path(module_id, candidate)
                )
            return replacement

    def prune_retired_versions(
        self,
        module_id: str,
    ) -> InstalledModuleState | None:
        """Remove kept-for-task versions once no backend task needs them.

        删除因后端任务仍在使用而暂留、现已无人使用的版本。
        """

        module_id = self._validate_module_id(module_id)
        with self._lock_for(module_id):
            state = self._store.get(module_id)
            if state is None:
                return None
            keep = {
                value
                for value in (
                    state.active_version,
                    state.previous_version,
                    state.candidate_version,
                )
                if value is not None
            }
            extra = set(state.versions) - keep
            busy = self._busy_versions(module_id, extra)
            removable = extra - busy
            if not removable:
                return state
            replacement = _replace_state(
                state,
                versions=_canonical_versions(keep | busy),
            )
            self._store.upsert(replacement)
            for version in removable:
                self._remove_tree(self.version_path(module_id, version))
            return replacement

    def set_enabled(
        self,
        module_id: str,
        enabled: bool,
    ) -> InstalledModuleState:
        """Enable or disable a module without deleting its code.

        启用或禁用模块，但不删除模块代码。
        """

        module_id = self._validate_module_id(module_id)
        with self._lock_for(module_id):
            state = self._require_state(module_id)
            if enabled and (
                state.official_uninstalled or state.active_version is None
            ):
                raise WorkshopInstallError(
                    "module has no active version to enable"
                )
            replacement = _replace_state(state, enabled=bool(enabled))
            self._store.upsert(replacement)
            return replacement

    def uninstall(
        self,
        module_id: str,
        *,
        delete_projects: bool = False,
    ) -> InstalledModuleState | None:
        """Uninstall code, preserving projects unless explicitly requested.

        卸载模块代码；除非明确请求，否则保留项目数据。
        """

        module_id = self._validate_module_id(module_id)
        with self._lock_for(module_id):
            state = self._require_state(module_id)
            module_root = self.module_path(module_id)
            transaction_root = (
                self.staging_dir
                / f"uninstall-{module_id}-{uuid.uuid4().hex}"
            )
            moved = False
            if module_root.exists():
                try:
                    self._directory_replace(module_root, transaction_root)
                    moved = True
                except OSError as exc:
                    raise WorkshopInstallError(
                        "module code could not be staged for uninstall"
                    ) from exc
            try:
                if state.official:
                    replacement: InstalledModuleState | None = _replace_state(
                        state,
                        enabled=False,
                        active_version=None,
                        previous_version=None,
                        candidate_version=None,
                        versions=(),
                        official_uninstalled=True,
                        consecutive_start_failures=0,
                    )
                    self._store.upsert(replacement)
                else:
                    replacement = None
                    self._store.remove(module_id)
            except Exception:
                if moved and transaction_root.exists():
                    try:
                        self._directory_replace(
                            transaction_root,
                            module_root,
                        )
                    except OSError:
                        pass
                raise

            self._remove_tree(transaction_root)
            if delete_projects:
                self._remove_tree(self.project_data_path(module_id))
            return replacement

    def record_start_success(
        self,
        module_id: str,
    ) -> InstalledModuleState:
        """Clear the consecutive sandbox-start failure counter.

        清零连续沙箱启动失败计数。
        """

        module_id = self._validate_module_id(module_id)
        with self._lock_for(module_id):
            state = self._require_state(module_id)
            replacement = _replace_state(
                state,
                consecutive_start_failures=0,
            )
            self._store.upsert(replacement)
            return replacement

    def record_start_failure(
        self,
        module_id: str,
    ) -> InstalledModuleState:
        """Record one start failure and roll back after three strikes.

        记录一次启动失败，并在连续三次失败后自动回滚。
        """

        module_id = self._validate_module_id(module_id)
        with self._lock_for(module_id):
            state = self._require_state(module_id)
            failures = min(3, state.consecutive_start_failures + 1)
            if failures >= 3 and state.previous_version is not None:
                previous = state.previous_version
                replacement = _replace_state(
                    state,
                    active_version=previous,
                    previous_version=state.active_version,
                    candidate_version=None,
                    consecutive_start_failures=0,
                )
            else:
                replacement = _replace_state(
                    state,
                    consecutive_start_failures=failures,
                )
            self._store.upsert(replacement)
            return replacement

    def _prune_versions(
        self,
        module_id: str,
        retained: set[str],
    ) -> None:
        module_root = self.module_path(module_id)
        if not module_root.is_dir():
            return
        for child in module_root.iterdir():
            if child.name not in retained:
                self._remove_tree(child)

    @staticmethod
    def _remove_tree(path: Path) -> None:
        try:
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except FileNotFoundError:
            pass
