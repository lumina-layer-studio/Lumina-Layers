"""Core-layer domain exceptions.

Core modules should raise these exceptions instead of API-specific errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass
class CoreError(Exception):
    """Base exception for core-layer failures."""

    detail: str
    error_type: str = "core_error"

    def __str__(self) -> str:
        return self.detail


class CoreValidationError(CoreError):
    """Raised when caller input/parameters are invalid for core logic."""

    def __init__(self, detail: str):
        super().__init__(detail=detail, error_type="core_validation_error")


class TemplateSlotCapacityError(CoreValidationError):
    """The imported template cannot hold every material used by the model."""

    def __init__(self, required_slots: int, available_slots: int):
        self.required_slots = required_slots
        self.available_slots = available_slots
        super().__init__(
            f"This model needs {required_slots} material slots, but the selected "
            f"3MF template has {available_slots}. Choose a template with at least "
            f"{required_slots} slots or use fewer materials."
        )
        self.error_type = "template_slot_capacity"


class NativeMaterialSelectionError(CoreValidationError):
    """Report a native preset or plate choice the user must resolve.

    报告需要用户明确选择的原生耗材预设或打印板问题。
    """

    def __init__(self, material_selection: Mapping[str, Any]):
        self.material_selection = dict(material_selection)
        issues = self.material_selection.get("issues") or []
        message = str(issues[0]["message"]) if issues else "Resolve native material selections."
        super().__init__(message)
        self.error_type = "native_material_selection_required"


class ExternalSpoolSelectionError(CoreValidationError):
    """The requested material cannot be assigned to the X2D external spool."""


class WipeTowerLayoutError(CoreValidationError):
    """Report a model-and-tower layout that cannot be safely exported.

    报告无法安全导出的模型与擦料塔布局；调用方应调整打印板或摆放选项。
    """

    def __init__(self, detail: str):
        super().__init__(detail)
        self.error_type = "wipe_tower_layout_unavailable"


class CoreDependencyError(CoreError):
    """Raised when optional dependencies or external resources are unavailable."""

    def __init__(self, detail: str):
        super().__init__(detail=detail, error_type="core_dependency_error")


class CoreProcessingError(CoreError):
    """Raised for unexpected processing failures in core logic."""

    def __init__(self, detail: str):
        super().__init__(detail=detail, error_type="core_processing_error")


class NativeSvgInvalidError(CoreValidationError):
    """Report deterministic invalid input from the native SVG boundary.

    报告原生 SVG 边界识别出的确定性无效输入。
    """

    def __init__(self, detail: str, *, reason_code: str):
        self.reason_code = str(reason_code)
        super().__init__(detail)


class NativeSvgInternalError(CoreProcessingError):
    """Report a native SVG ABI or processing failure without legacy retry.

    报告原生 SVG ABI 或处理故障；此类错误不得静默走旧链路重试。
    """

    def __init__(self, detail: str, *, reason_code: str):
        self.reason_code = str(reason_code)
        super().__init__(detail)


class CachedPreviewAnalysisError(CoreError):
    """Raised when explicitly required preview analysis cannot be consumed.

    当用户的空间编辑要求复用预览分析，而缓存三件套无法安全读取或投影时抛出。
    """

    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            error_type="cached_preview_analysis_error",
        )
