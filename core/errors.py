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


class CoatingLayerHeightError(CoreValidationError):
    """The selected nozzle cannot divide the requested film into printable layers."""


class KeychainPlacementError(CoreValidationError):
    """The final ring cannot be printed as an attached part with an open bore."""

    @classmethod
    def detached(cls) -> KeychainPlacementError:
        return cls(
            "挂件环与主体没有实体接合。请调整挂件环的位置、角度或偏移。 / "
            "The keychain loop has no solid joint to the model. Adjust its position, angle or offsets."
        )

    @classmethod
    def blocked(cls) -> KeychainPlacementError:
        return cls(
            "挂孔已被主体完全堵住。请调整挂件环的位置、角度或偏移。 / "
            "The model completely blocks the keychain hole. Adjust the loop position, angle or offsets."
        )


class MaterialArchiveUnavailableError(CoreValidationError):
    """A selected conversion material is missing or has unusable calibration data."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.error_type = "material_archive_unavailable"


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


class TemplateMaterialMappingError(CoreValidationError):
    """An imported template has unresolved material-to-nozzle assignments."""

    def __init__(self, field: str, material_count: int, value_count: int, mapping_mode: str) -> None:
        self.field = field
        self.material_count = material_count
        self.value_count = value_count
        self.mapping_mode = mapping_mode
        super().__init__(
            f"The selected 3MF template has incomplete nozzle assignments "
            f"({value_count} entries for {material_count} materials) in {mapping_mode} mode. Open it in "
            "Bambu Studio, assign every material to a nozzle, then save and import "
            "the project again. Alternatively, select automatic material grouping "
            "in Bambu Studio before saving and importing the template."
        )
        self.error_type = "template_material_mapping"

    def __reduce__(self) -> tuple[type[TemplateMaterialMappingError], tuple[str, int, int, str]]:
        return type(self), (self.field, self.material_count, self.value_count, self.mapping_mode)


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
