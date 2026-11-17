"""Domain errors for editable Lumina project packages.

可编辑 Lumina 工程包的领域错误。
"""

from __future__ import annotations


class ProjectError(Exception):
    """Base class for project package failures."""

    code = "project_error"


class ProjectValidationError(ProjectError):
    """Raised when an in-memory project snapshot is invalid."""

    code = "project_validation_error"


class ProjectFormatError(ProjectError):
    """Raised when a package is not a supported lumina-project."""

    code = "project_format_error"


class ProjectSecurityError(ProjectError):
    """Raised when untrusted package input violates safety limits."""

    code = "project_security_error"


class ProjectResourceLimitError(ProjectSecurityError):
    """Raised when a package exceeds a bounded resource budget."""

    code = "project_resource_limit"
