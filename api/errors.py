"""Domain error types and HTTP mapping helpers."""

from __future__ import annotations

from fastapi import HTTPException
from core.errors import (
    CoreDependencyError,
    CoreError,
    CoreProcessingError,
    CoreValidationError,
    NativeMaterialSelectionError,
    TemplateSlotCapacityError,
)
from core.material_dynamic_solver import (
    DynamicMaterialCandidateError,
    DynamicMaterialSolverError,
)
from core.workshop.errors import WorkshopBackendError

# Creative Workshop module backends: stable ``{code, message}`` details.
# Unlisted codes are request problems the user can correct (422).
WORKSHOP_BACKEND_STATUS_BY_CODE: dict[str, int] = {
    "task-not-found": 404,
    "task-output-not-found": 404,
    "module-not-installed": 404,
    "module-version-unavailable": 404,
    "backend-not-declared": 404,
    "model-not-retained": 404,
    "backend-authorization-required": 409,
    "unreviewed-confirmation-required": 409,
    "module-disabled": 409,
    "module-version-blocked": 409,
    "backend-not-prepared": 409,
    "backend-identity-unknown": 409,
    "task-active": 409,
    "task-output-unavailable": 409,
    "backend-stopping": 409,
    "platform-unsupported": 409,
    "task-input-too-large": 413,
    "backend-tool-unavailable": 503,
    "backend-state-invalid": 503,
}


def to_http_exception(exc: Exception, context: str) -> HTTPException:
    """Map domain/unknown exceptions to stable HTTPException.

    将领域异常和未知异常映射为稳定的 HTTPException。

    Args:
        exc: Exception raised by the domain, core, or boundary layer. 领域层、
            核心层或边界层抛出的异常。
        context: Safe operation label used in the fallback error message.
            用于兜底错误消息的安全操作标签。

    Returns:
        HTTPException: Existing HTTP exception or a stable mapped response.
            原有 HTTP 异常，或映射后的稳定 HTTP 响应异常。
    """
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, TemplateSlotCapacityError):
        return HTTPException(
            status_code=422,
            detail={
                "code": exc.error_type,
                "message": exc.detail,
                "required_slots": exc.required_slots,
                "available_slots": exc.available_slots,
            },
        )
    if isinstance(exc, NativeMaterialSelectionError):
        from core.export_material_selection import present_material_selection

        selection = exc.material_selection
        if not selection.get("device_profile_id"):
            selection = present_material_selection(selection)
        return HTTPException(
            status_code=422,
            detail={
                "error": exc.error_type,
                "message": exc.detail,
                "material_selection": selection,
            },
        )
    if isinstance(exc, DynamicMaterialCandidateError):
        no_candidate = exc.phase in {"exact_search", "fixed_max_baseline"}
        return HTTPException(
            status_code=409 if no_candidate else 503,
            detail={
                "code": (
                    "dynamic_material_no_candidate"
                    if no_candidate
                    else "dynamic_material_solver_unavailable"
                ),
                "message": (
                    "No exact dynamic material candidate is available for this target."
                    if no_candidate
                    else "The exact dynamic material solver is temporarily unavailable."
                ),
                "target_srgb": (
                    list(exc.target_srgb) if exc.target_srgb is not None else None
                ),
                "layer_count": exc.layer_count,
                "stage": exc.phase,
            },
        )
    if isinstance(exc, DynamicMaterialSolverError):
        return HTTPException(
            status_code=503,
            detail={
                "code": "dynamic_material_solver_unavailable",
                "message": (
                    "The exact dynamic material solver is temporarily unavailable."
                ),
                "target_srgb": None,
                "layer_count": None,
                "stage": "exact_search_engine",
            },
        )
    if isinstance(exc, WorkshopBackendError):
        return HTTPException(
            status_code=WORKSHOP_BACKEND_STATUS_BY_CODE.get(exc.code, 422),
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, CoreValidationError):
        return HTTPException(status_code=422, detail=exc.detail)
    if isinstance(exc, CoreDependencyError):
        return HTTPException(status_code=502, detail=exc.detail)
    if isinstance(exc, (CoreProcessingError, CoreError)):
        return HTTPException(status_code=500, detail=exc.detail)
    return HTTPException(
        status_code=500,
        detail=f"{context} failed. Check the server log for details.",
    )
