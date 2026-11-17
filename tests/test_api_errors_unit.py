"""Unit tests for domain error -> HTTP exception mapping."""

from __future__ import annotations

from api.errors import to_http_exception
from core.errors import (
    CoreDependencyError,
    CoreProcessingError,
    CoreValidationError,
)


def test_unknown_exception_maps_to_500_without_leaking_exception_detail() -> None:
    exc = to_http_exception(
        RuntimeError("boom at /Users/min/private/input.png"),
        "vectorize",
    )
    assert exc.status_code == 500
    assert exc.detail == "vectorize failed. Check the server log for details."
    assert "boom" not in exc.detail
    assert "/Users/min" not in exc.detail


def test_core_validation_error_maps_to_422() -> None:
    exc = to_http_exception(CoreValidationError("invalid"), "converter")
    assert exc.status_code == 422
    assert exc.detail == "invalid"


def test_core_dependency_error_maps_to_502() -> None:
    exc = to_http_exception(CoreDependencyError("missing optional dependency"), "converter")
    assert exc.status_code == 502
    assert exc.detail == "missing optional dependency"


def test_core_processing_error_maps_to_500() -> None:
    exc = to_http_exception(CoreProcessingError("processing failed"), "converter")
    assert exc.status_code == 500
    assert exc.detail == "processing failed"


def test_workshop_backend_error_keeps_code_and_message_contract() -> None:
    from core.workshop.errors import WorkshopBackendError

    conflict = to_http_exception(
        WorkshopBackendError("backend-authorization-required", "Confirm this backend first."),
        "Creative Workshop backend request",
    )
    assert conflict.status_code == 409
    assert conflict.detail == {
        "code": "backend-authorization-required",
        "message": "Confirm this backend first.",
    }
    statuses = {
        code: to_http_exception(WorkshopBackendError(code, "x"), "backend").status_code
        for code in ("task-not-found", "task-input-too-large", "backend-tool-unavailable", "task-input-invalid")
    }
    # Unlisted codes are request problems the user can correct.
    assert statuses == {
        "task-not-found": 404,
        "task-input-too-large": 413,
        "backend-tool-unavailable": 503,
        "task-input-invalid": 422,
    }
