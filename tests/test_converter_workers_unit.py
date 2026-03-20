"""Unit tests for converter worker function signatures and picklability.
Converter Worker 函数签名与可序列化性单元测试。

These tests verify that worker functions conform to the ProcessPoolExecutor
contract: they must be top-level picklable functions that accept only
serializable parameters (str, int, float, bool, dict) and return dict.

We do NOT call the actual worker functions (they depend on heavy core modules).
Instead we inspect function metadata and verify picklability.

**Validates: Requirements 2.4, 2.5**
"""

import inspect
import pickle
import types

import pytest

from api.workers.converter_workers import (
    worker_generate_model,
    worker_generate_preview,
)

# Types that are safe to pass across process boundaries via pickle
SERIALIZABLE_TYPES = (str, int, float, bool, dict)


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------

class TestWorkerImportability:
    """Verify worker functions are importable top-level functions."""

    def test_worker_generate_preview_is_importable(self) -> None:
        """worker_generate_preview should be importable from the module."""
        assert worker_generate_preview is not None

    def test_worker_generate_model_is_importable(self) -> None:
        """worker_generate_model should be importable from the module."""
        assert worker_generate_model is not None

    def test_worker_generate_preview_is_function(self) -> None:
        """worker_generate_preview must be a plain function, not a method."""
        assert isinstance(worker_generate_preview, types.FunctionType)

    def test_worker_generate_model_is_function(self) -> None:
        """worker_generate_model must be a plain function, not a method."""
        assert isinstance(worker_generate_model, types.FunctionType)


# ---------------------------------------------------------------------------
# Picklability (required for ProcessPoolExecutor)
# ---------------------------------------------------------------------------

class TestWorkerPicklability:
    """Worker functions must survive pickle round-trip for ProcessPoolExecutor."""

    def test_worker_generate_preview_is_picklable(self) -> None:
        """pickle.dumps/loads round-trip should return the same function."""
        restored = pickle.loads(pickle.dumps(worker_generate_preview))
        assert restored is worker_generate_preview

    def test_worker_generate_model_is_picklable(self) -> None:
        """pickle.dumps/loads round-trip should return the same function."""
        restored = pickle.loads(pickle.dumps(worker_generate_model))
        assert restored is worker_generate_model


# ---------------------------------------------------------------------------
# Parameter type annotations — all must be serializable scalars
# ---------------------------------------------------------------------------

class TestParameterAnnotations:
    """Verify all parameter annotations are serializable types."""

    @staticmethod
    def _get_param_annotations(fn) -> dict[str, type]:
        """Extract parameter name → annotation mapping (excluding 'return')."""
        sig = inspect.signature(fn)
        return {
            name: param.annotation
            for name, param in sig.parameters.items()
            if param.annotation is not inspect.Parameter.empty
        }

    def test_preview_params_are_serializable(self) -> None:
        """All worker_generate_preview params must be basic serializable types."""
        annotations = self._get_param_annotations(worker_generate_preview)
        assert len(annotations) > 0, "Function should have type annotations"
        for name, ann in annotations.items():
            assert ann in SERIALIZABLE_TYPES, (
                f"Parameter '{name}' has non-serializable type {ann}"
            )

    def test_model_params_are_serializable(self) -> None:
        """All worker_generate_model params must be basic serializable types."""
        annotations = self._get_param_annotations(worker_generate_model)
        assert len(annotations) > 0, "Function should have type annotations"
        for name, ann in annotations.items():
            assert ann in SERIALIZABLE_TYPES, (
                f"Parameter '{name}' has non-serializable type {ann}"
            )

    def test_preview_has_expected_param_count(self) -> None:
        """worker_generate_preview should have 9 parameters."""
        sig = inspect.signature(worker_generate_preview)
        assert len(sig.parameters) == 9

    def test_model_has_expected_param_count(self) -> None:
        """worker_generate_model should have 3 parameters."""
        sig = inspect.signature(worker_generate_model)
        assert len(sig.parameters) == 3

    def test_preview_param_names(self) -> None:
        """Verify expected parameter names for worker_generate_preview."""
        sig = inspect.signature(worker_generate_preview)
        expected = {
            "image_path", "lut_path", "target_width_mm", "auto_bg",
            "bg_tol", "color_mode", "modeling_mode", "quantize_colors",
            "enable_cleanup",
        }
        assert set(sig.parameters.keys()) == expected

    def test_model_param_names(self) -> None:
        """Verify expected parameter names for worker_generate_model."""
        sig = inspect.signature(worker_generate_model)
        expected = {"image_path", "lut_path", "params"}
        assert set(sig.parameters.keys()) == expected


# ---------------------------------------------------------------------------
# Return type annotation — must be dict
# ---------------------------------------------------------------------------

class TestReturnAnnotations:
    """Verify return type annotations are dict."""

    def test_preview_returns_dict(self) -> None:
        """worker_generate_preview return annotation should be dict."""
        hints = inspect.signature(worker_generate_preview).return_annotation
        assert hints is dict

    def test_model_returns_dict(self) -> None:
        """worker_generate_model return annotation should be dict."""
        hints = inspect.signature(worker_generate_model).return_annotation
        assert hints is dict


# ---------------------------------------------------------------------------
# Top-level function check (not bound to a class)
# ---------------------------------------------------------------------------

class TestTopLevelFunctions:
    """Worker functions must be module-level, not class methods."""

    def test_preview_has_no_self_param(self) -> None:
        """Top-level functions should not have 'self' or 'cls' parameter."""
        sig = inspect.signature(worker_generate_preview)
        assert "self" not in sig.parameters
        assert "cls" not in sig.parameters

    def test_model_has_no_self_param(self) -> None:
        """Top-level functions should not have 'self' or 'cls' parameter."""
        sig = inspect.signature(worker_generate_model)
        assert "self" not in sig.parameters
        assert "cls" not in sig.parameters

    def test_preview_qualname_is_module_level(self) -> None:
        """__qualname__ should equal __name__ for top-level functions."""
        assert "." not in worker_generate_preview.__qualname__

    def test_model_qualname_is_module_level(self) -> None:
        """__qualname__ should equal __name__ for top-level functions."""
        assert "." not in worker_generate_model.__qualname__
