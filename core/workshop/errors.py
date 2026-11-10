"""Typed Creative Workshop domain errors."""

from __future__ import annotations


class WorkshopError(Exception):
    """Base error for Workshop domain operations.

    创意工坊领域操作的基础错误。
    """


class WorkshopPackageError(WorkshopError):
    """Raised when a Workshop package fails closed validation.

    创意工坊安装包未通过安全校验时抛出。
    """


class WorkshopRegistryError(WorkshopError):
    """Raised when a Registry index or signature is not trustworthy.

    创意工坊 Registry 索引或签名不可信时抛出。
    """


class WorkshopReleaseError(WorkshopError):
    """Raised when a remote module release fails its trust boundary.

    远程模块 Release 未通过信任边界校验时抛出。
    """


class WorkshopInstallError(WorkshopError):
    """Raised when an install-state transaction cannot converge safely.

    创意工坊安装状态事务无法安全收敛时抛出。
    """


class WorkshopBackendError(WorkshopError):
    """Raised by the module backend runtime with a stable error code.

    模块后端运行时抛出的错误，附带稳定的错误码。

    Args:
        code: Stable kebab-case code shown to modules and the manager UI.
            提供给模块与管理界面的稳定短横线错误码。
        message: Actionable description without secrets or private paths.
            不含密钥或私有路径的可操作说明。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
