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
import logging
import os
import pickle
import types
import zipfile
from types import SimpleNamespace
from typing import get_args, get_origin
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from api.workers.converter_workers import (
    worker_batch_convert_item,
    worker_generate_large_format_svg_native,
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

    def test_worker_generate_large_format_svg_native_is_importable(self) -> None:
        """worker_generate_large_format_svg_native should be importable from the module."""
        assert worker_generate_large_format_svg_native is not None

    def test_worker_generate_preview_is_function(self) -> None:
        """worker_generate_preview must be a plain function, not a method."""
        assert isinstance(worker_generate_preview, types.FunctionType)

    def test_worker_generate_model_is_function(self) -> None:
        """worker_generate_model must be a plain function, not a method."""
        assert isinstance(worker_generate_model, types.FunctionType)

    def test_worker_generate_large_format_svg_native_is_function(self) -> None:
        """worker_generate_large_format_svg_native must be a plain function."""
        assert isinstance(worker_generate_large_format_svg_native, types.FunctionType)


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

    def test_worker_generate_large_format_svg_native_is_picklable(self) -> None:
        """pickle.dumps/loads round-trip should return the same function."""
        restored = pickle.loads(pickle.dumps(worker_generate_large_format_svg_native))
        assert restored is worker_generate_large_format_svg_native


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

    @staticmethod
    def _annotation_is_serializable(annotation: object) -> bool:
        if annotation in SERIALIZABLE_TYPES or annotation is type(None):
            return True
        origin = get_origin(annotation)
        if origin is None and isinstance(annotation, types.UnionType):
            return all(
                TestParameterAnnotations._annotation_is_serializable(option)
                for option in get_args(annotation)
            )
        if origin is not None:
            return all(
                TestParameterAnnotations._annotation_is_serializable(option)
                for option in get_args(annotation)
            )
        return False

    def test_preview_params_are_serializable(self) -> None:
        """All worker_generate_preview params must be basic serializable types."""
        annotations = self._get_param_annotations(worker_generate_preview)
        assert len(annotations) > 0, "Function should have type annotations"
        for name, ann in annotations.items():
            assert self._annotation_is_serializable(ann), (
                f"Parameter '{name}' has non-serializable type {ann}"
            )

    def test_model_params_are_serializable(self) -> None:
        """All worker_generate_model params must be basic serializable types."""
        annotations = self._get_param_annotations(worker_generate_model)
        assert len(annotations) > 0, "Function should have type annotations"
        for name, ann in annotations.items():
            assert self._annotation_is_serializable(ann), (
                f"Parameter '{name}' has non-serializable type {ann}"
            )

    def test_large_format_svg_native_params_are_serializable(self) -> None:
        """All worker_generate_large_format_svg_native params must be serializable."""
        annotations = self._get_param_annotations(worker_generate_large_format_svg_native)
        assert len(annotations) > 0, "Function should have type annotations"
        for name, ann in annotations.items():
            assert self._annotation_is_serializable(ann), (
                f"Parameter '{name}' has non-serializable type {ann}"
            )

    def test_preview_param_names(self) -> None:
        """Verify expected parameter names for worker_generate_preview."""
        sig = inspect.signature(worker_generate_preview)
        expected = {
            "image_path", "lut_path", "target_width_mm",
            "color_mode", "modeling_mode", "quantize_colors",
            "color_layers", "layer_height_mm", "enable_cleanup",
            "enable_outline", "outline_width",
            "svg_pixels_per_mm", "is_dark",
            "model_enable", "model_only", "model_threshold", "model_margin",
            "hue_weight", "chroma_gate", "use_lut_constrained",
            "material_source", "selected_materials",
            "material_layer_count", "material_layer_height_mm",
            "material_grid_resolution", "material_backing_material_index",
            "material_dynamic_layer_count_enabled",
            "material_min_layer_count", "material_max_layer_count",
            "material_delta_e00_tolerance", "auto_dynamic_range",
            "high_precision_3d_preview", "replacement_regions",
            "svg_hole_compensation_enabled", "svg_hole_max_area_mm2",
            "svg_hole_max_width_mm",
            "materials_dir",
        }
        assert set(sig.parameters.keys()) == expected

    def test_preview_compensation_parameters_are_optional_scalars(self) -> None:
        """Existing preview calls remain valid with compensation disabled."""
        parameters = inspect.signature(worker_generate_preview).parameters
        assert parameters["svg_hole_compensation_enabled"].default is False
        assert parameters["svg_hole_max_area_mm2"].default == 0.5
        assert parameters["svg_hole_max_width_mm"].default == 0.1

    def test_model_param_names(self) -> None:
        """Verify expected parameter names for worker_generate_model."""
        sig = inspect.signature(worker_generate_model)
        expected = {"image_path", "lut_path", "params"}
        assert set(sig.parameters.keys()) == expected

    def test_large_format_svg_native_param_names(self) -> None:
        """Verify expected parameter names for worker_generate_large_format_svg_native."""
        sig = inspect.signature(worker_generate_large_format_svg_native)
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

    def test_large_format_svg_native_returns_dict(self) -> None:
        """worker_generate_large_format_svg_native return annotation should be dict."""
        hints = inspect.signature(worker_generate_large_format_svg_native).return_annotation
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

    def test_large_format_svg_native_has_no_self_param(self) -> None:
        """Top-level functions should not have 'self' or 'cls' parameter."""
        sig = inspect.signature(worker_generate_large_format_svg_native)
        assert "self" not in sig.parameters
        assert "cls" not in sig.parameters

    def test_preview_qualname_is_module_level(self) -> None:
        """__qualname__ should equal __name__ for top-level functions."""
        assert "." not in worker_generate_preview.__qualname__

    def test_model_qualname_is_module_level(self) -> None:
        """__qualname__ should equal __name__ for top-level functions."""
        assert "." not in worker_generate_model.__qualname__

    def test_large_format_svg_native_qualname_is_module_level(self) -> None:
        """__qualname__ should equal __name__ for top-level functions."""
        assert "." not in worker_generate_large_format_svg_native.__qualname__


def test_worker_generate_model_forwards_fridge_magnet_params_intact() -> None:
    """worker_generate_model should pass fridge-magnet params through untouched."""

    expected_fridge_magnets = [
        {
            "id": "magnet-round",
            "shape": "round",
            "preset_key": "round-18",
            "diameter_mm": 18.0,
            "width_mm": None,
            "height_mm": None,
            "thickness_mm": 2.0,
            "center_x_mm": 20.0,
            "center_y_mm": 25.0,
        },
        {
            "id": "magnet-rect",
            "shape": "rect",
            "preset_key": "rect-20x10",
            "diameter_mm": None,
            "width_mm": 20.0,
            "height_mm": 10.0,
            "thickness_mm": 2.5,
            "center_x_mm": 40.0,
            "center_y_mm": 15.0,
        },
    ]
    params = {
        "target_width_mm": 80.0,
        "spacer_thick": 1.5,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color (RYBW)",
        "add_loop": True,
        "loop_width": 5.0,
        "loop_length": 10.0,
        "loop_hole": 3.0,
        "loop_pos": (50.0, 50.0),
        "enable_fridge_magnet": True,
        "fridge_magnets": expected_fridge_magnets,
        "modeling_mode": "high-fidelity",
        "original_matched_rgb_path": "original-rgb.npy",
        "original_material_matrix_path": "original-material.npy",
        "edit_projection": {
            "mode": "delta",
            "source_shape": [40, 80],
        },
    }

    def _generate_with_transform_metadata(**kwargs):
        metadata = kwargs.get("export_transform_metadata")
        if isinstance(metadata, dict):
            metadata.update({"x_mirrored": True, "mirror_span_mm": 80.0})
        return "out.3mf", "out.glb", None, "OK", None

    with patch(
        "core.converter.generate_final_model",
        side_effect=_generate_with_transform_metadata,
    ) as generate_final_model_mock:
        result = worker_generate_model("image.png", "lut.npy", params)

    assert result == {
        "threemf_path": "out.3mf",
        "glb_path": "out.glb",
        "status_msg": "OK",
        "x_mirrored": True,
        "mirror_span_mm": 80.0,
    }
    generate_final_model_mock.assert_called_once()
    call_kwargs = generate_final_model_mock.call_args.kwargs
    assert call_kwargs["image_path"] == "image.png"
    assert call_kwargs["lut_path"] == "lut.npy"
    assert {
        key: value
        for key, value in call_kwargs.items()
        if key not in {"image_path", "lut_path", "export_transform_metadata"}
    } == params
    assert call_kwargs["export_transform_metadata"] == {
        "x_mirrored": True,
        "mirror_span_mm": 80.0,
    }


def test_worker_batch_convert_item_forwards_relief_params_intact() -> None:
    """worker_batch_convert_item should pass batch relief params through.

    When ``convert_image_to_3d`` reports a synthetic 3MF path that does not
    exist on disk, the worker now takes the legacy failure-style early
    return so the parent process records this item as ``failed``. We
    assert relief kwargs propagated and the new 5-key result contract is
    intact (with sentinel values for the 4 file-path / bbox fields).
    """

    color_height_map = {"#ff0000": 1.7, "#ffffff": 1.3}

    with patch(
        "core.converter.convert_image_to_3d",
        return_value=("out.3mf", None, None, "OK", None),
    ) as convert_image_to_3d_mock:
        result = worker_batch_convert_item(
            image_path="image.png",
            lut_path="lut.npy",
            target_width_mm=80.0,
            spacer_thick=1.2,
            structure_mode="Single-sided",
            color_mode="4-Color (RYBW)",
            modeling_mode_value="high-fidelity",
            color_layers=5,
            layer_height_mm=0.08,
            quantize_colors=64,
            enable_cleanup=True,
            artifact_prefix="batch-test-",
            hue_weight=0.5,
            chroma_gate=12.0,
            enable_relief=True,
            height_mode="color",
            color_height_map=color_height_map,
            heightmap_max_height=4.2,
            material_source="material_archive",
            selected_materials=["brand/red", "brand/white"],
            material_backing_material_index=1,
            separate_backing=True,
            high_precision_3d_preview=True,
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
        )

    assert result == {
        "threemf_path": None,
        "preview_glb_path": None,
        "metadata_sidecar_path": None,
        "xy_bbox_mm": (0.0, 0.0),
        "status_msg": "OK",
    }
    convert_image_to_3d_mock.assert_called_once()
    call_kwargs = convert_image_to_3d_mock.call_args.kwargs
    assert call_kwargs["enable_relief"] is True
    assert call_kwargs["height_mode"] == "color"
    assert call_kwargs["color_height_map"] == color_height_map
    assert call_kwargs["heightmap_max_height"] == 4.2
    assert call_kwargs["material_source"] == "material_archive"
    assert call_kwargs["selected_materials"] == ["brand/red", "brand/white"]
    assert call_kwargs["material_backing_material_index"] == 1
    assert call_kwargs["separate_backing"] is True
    assert call_kwargs["high_precision_3d_preview"] is True
    assert call_kwargs["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"


def test_worker_generate_preview_accepts_numpy_preview_image(tmp_path) -> None:
    preview_img = np.zeros((4, 6, 4), dtype=np.uint8)
    preview_img[..., 0] = 255
    cache_payload = {"preview_rgba": preview_img.copy(), "color_conf": {}}

    with (
        patch(
            "core.converter.generate_preview_cached",
            return_value=(preview_img, cache_payload, "OK"),
        ) as generate_preview_cached_mock,
        patch("config.TEMP_DIR", str(tmp_path)),
    ):
        result = worker_generate_preview(
            image_path="image.png",
            lut_path="lut.npy",
            target_width_mm=60.0,
            color_mode="4-Color (RYBW)",
            modeling_mode="high-fidelity",
            color_layers=10,
            layer_height_mm=0.08,
            quantize_colors=16,
            enable_cleanup=True,
            enable_outline=True,
            outline_width=2.5,
            replacement_regions=[
                {
                    "quantized_hex": "#111111",
                    "matched_hex": "#111111",
                    "replacement_hex": "#222222",
                },
            ],
        )

    assert result["status_msg"] == "OK"
    call_kwargs = generate_preview_cached_mock.call_args.kwargs
    assert call_kwargs["enable_outline"] is True
    assert call_kwargs["outline_width"] == 2.5
    assert call_kwargs["replacement_regions"] == [
        {
            "quantized_hex": "#111111",
            "matched_hex": "#111111",
            "replacement_hex": "#222222",
        },
    ]
    assert result["preview_png_path"] is not None
    assert result["raw_preview_png_path"] is not None
    assert result["cache_data_path"] is not None
    assert result["cache_artifact_ref"] is not None
    assert os.path.exists(result["preview_png_path"])
    assert os.path.exists(result["raw_preview_png_path"])
    assert os.path.exists(result["cache_data_path"])

    try:
        with open(result["cache_data_path"], "rb") as handle:
            restored_cache = pickle.load(handle)
        assert "preview_rgba" not in restored_cache
        np.testing.assert_array_equal(
            np.load(result["cache_artifact_ref"]["fields"]["preview_rgba"]["path"]),
            preview_img,
        )
        np.testing.assert_array_equal(
            np.asarray(Image.open(result["raw_preview_png_path"])),
            preview_img,
        )
    finally:
        cleanup_paths = {
            result.get("preview_png_path"),
            result.get("raw_preview_png_path"),
            result.get("cache_data_path"),
            *(
                field_ref["path"]
                for field_ref in result["cache_artifact_ref"].get("fields", {}).values()
            ),
        }
        for path in cleanup_paths:
            if path and os.path.exists(path):
                os.unlink(path)


def test_worker_generate_preview_writes_cache_arrays_as_artifact(tmp_path) -> None:
    preview_img = np.zeros((4, 6, 4), dtype=np.uint8)
    preview_img[..., 0] = 255
    matched_rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    cache_payload = {
        "preview_rgba": preview_img.copy(),
        "matched_rgb": matched_rgb,
        "target_w": 6,
        "target_h": 4,
        "color_conf": {},
    }

    with (
        patch(
            "core.converter.generate_preview_cached",
            return_value=(preview_img, cache_payload, "OK"),
        ),
        patch("config.TEMP_DIR", str(tmp_path)),
    ):
        result = worker_generate_preview(
            image_path="image.png",
            lut_path="lut.npy",
            target_width_mm=60.0,
            color_mode="4-Color (RYBW)",
            modeling_mode="high-fidelity",
            color_layers=10,
            layer_height_mm=0.08,
            quantize_colors=16,
            enable_cleanup=True,
        )

    artifact_ref = result["cache_artifact_ref"]
    assert result["raw_preview_png_path"] is not None
    assert artifact_ref["metadata"]["target_w"] == 6
    assert artifact_ref["metadata"]["target_h"] == 4
    assert set(artifact_ref["fields"]) == {"preview_rgba", "matched_rgb"}
    try:
        with open(result["cache_data_path"], "rb") as handle:
            metadata_pickle = pickle.load(handle)
        assert "preview_rgba" not in metadata_pickle
        assert "matched_rgb" not in metadata_pickle
        np.testing.assert_array_equal(
            np.load(artifact_ref["fields"]["preview_rgba"]["path"]),
            preview_img,
        )
        np.testing.assert_array_equal(
            np.load(artifact_ref["fields"]["matched_rgb"]["path"]),
            matched_rgb,
        )
        np.testing.assert_array_equal(
            np.asarray(Image.open(result["raw_preview_png_path"])),
            preview_img,
        )
    finally:
        cleanup_paths = {
            result.get("preview_png_path"),
            result.get("raw_preview_png_path"),
            result.get("cache_data_path"),
            *(
                field_ref["path"]
                for field_ref in artifact_ref.get("fields", {}).values()
            ),
        }
        for path in cleanup_paths:
            if path and os.path.exists(path):
                os.unlink(path)


def test_worker_generate_preview_precomputes_response_payloads(tmp_path) -> None:
    preview_img = np.zeros((4, 6, 4), dtype=np.uint8)
    preview_img[..., 3] = 255
    matched_rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    matched_rgb[:2, :, :] = [255, 0, 0]
    matched_rgb[2:, :, :] = [0, 255, 0]
    quantized_image = matched_rgb.copy()
    quantized_image[:2, :, :] = [250, 0, 0]
    mask_solid = np.ones((4, 6), dtype=bool)
    cache_payload = {
        "preview_rgba": preview_img.copy(),
        "matched_rgb": matched_rgb,
        "quantized_image": quantized_image,
        "mask_solid": mask_solid,
        "target_w": 6,
        "target_h": 4,
        "color_palette": [
            {
                "hex": "#ff0000",
                "color": (255, 0, 0),
                "count": 12,
                "percentage": 50.0,
            },
            {
                "hex": "#00ff00",
                "color": (0, 255, 0),
                "count": 12,
                "percentage": 50.0,
            },
        ],
        "color_conf": {},
    }

    with (
        patch(
            "core.converter.generate_preview_cached",
            return_value=(preview_img, cache_payload, "OK"),
        ),
        patch("config.TEMP_DIR", str(tmp_path)),
    ):
        result = worker_generate_preview(
            image_path="image.png",
            lut_path="lut.npy",
            target_width_mm=60.0,
            color_mode="4-Color (RYBW)",
            modeling_mode="high-fidelity",
            color_layers=10,
            layer_height_mm=0.08,
            quantize_colors=16,
            enable_cleanup=True,
        )

    assert result["response_palette"] == [
        {
            "quantized_hex": "#fa0000",
            "matched_hex": "#ff0000",
            "pixel_count": 12,
            "percentage": 50.0,
        },
        {
            "quantized_hex": "#00ff00",
            "matched_hex": "#00ff00",
            "pixel_count": 12,
            "percentage": 50.0,
        },
    ]
    assert isinstance(result["gradient_groups"], list)
    assert result["gradient_region_id_map_path"] is not None
    region_id_map = np.load(result["gradient_region_id_map_path"])
    assert region_id_map.shape == (4, 6)
    assert region_id_map.dtype == np.uint32

    cleanup_paths = {
        result.get("preview_png_path"),
        result.get("raw_preview_png_path"),
        result.get("cache_data_path"),
        result.get("gradient_region_id_map_path"),
        *(
            field_ref["path"]
            for field_ref in result["cache_artifact_ref"].get("fields", {}).values()
        ),
    }
    for path in cleanup_paths:
        if path and os.path.exists(path):
            os.unlink(path)


def test_worker_generate_preview_cleans_temp_artifacts_when_serialization_fails(
    tmp_path,
) -> None:
    preview_img = np.zeros((4, 6, 4), dtype=np.uint8)
    preview_img[..., 3] = 255
    matched_rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    quantized_image = matched_rgb.copy()
    mask_solid = np.ones((4, 6), dtype=bool)
    cache_payload = {
        "preview_rgba": preview_img.copy(),
        "matched_rgb": matched_rgb,
        "quantized_image": quantized_image,
        "mask_solid": mask_solid,
        "target_w": 6,
        "target_h": 4,
        "color_palette": [
            {
                "hex": "#000000",
                "color": (0, 0, 0),
                "count": 24,
                "percentage": 100.0,
            }
        ],
        "color_conf": {},
        "vector_parse_clip_cache_blob": b"parse-clip-artifact",
    }

    with (
        patch(
            "core.converter.generate_preview_cached",
            return_value=(preview_img, cache_payload, "OK"),
        ),
        patch("config.TEMP_DIR", str(tmp_path)),
        patch("pickle.dump", side_effect=RuntimeError("pickle failed")),
    ):
        with pytest.raises(RuntimeError, match="pickle failed"):
            worker_generate_preview(
                image_path="image.png",
                lut_path="lut.npy",
                target_width_mm=60.0,
                color_mode="4-Color (RYBW)",
                modeling_mode="high-fidelity",
                color_layers=10,
                layer_height_mm=0.08,
                quantize_colors=16,
                enable_cleanup=True,
            )

    leftovers = [path.name for path in tmp_path.iterdir()]
    assert leftovers == []


def test_worker_generate_preview_splits_vector_parse_clip_cache_blob(tmp_path) -> None:
    preview_img = np.zeros((4, 6, 4), dtype=np.uint8)
    cache_payload = {
        "preview_rgba": preview_img.copy(),
        "color_conf": {},
        "vector_parse_clip_cache_blob": b"parse-clip-artifact",
        "vector_parse_clip_cache_provenance": "a" * 64,
    }

    with (
        patch(
            "core.converter.generate_preview_cached",
            return_value=(preview_img, cache_payload, "OK"),
        ),
        patch("config.TEMP_DIR", str(tmp_path)),
    ):
        result = worker_generate_preview(
            image_path="image.svg",
            lut_path="lut.npy",
            target_width_mm=60.0,
            color_mode="4-Color (RYBW)",
            modeling_mode="vector",
            color_layers=10,
            layer_height_mm=0.08,
            quantize_colors=16,
            enable_cleanup=True,
        )

    assert result["cache_data_path"] is not None
    assert result["vector_parse_clip_cache_path"] is not None
    try:
        with open(result["cache_data_path"], "rb") as handle:
            restored_cache = pickle.load(handle)
        assert "vector_parse_clip_cache_blob" not in restored_cache
        assert restored_cache["vector_parse_clip_cache_provenance"] == "a" * 64
        with open(result["vector_parse_clip_cache_path"], "rb") as handle:
            assert handle.read() == b"parse-clip-artifact"
    finally:
        for key in (
            "preview_png_path",
            "cache_data_path",
            "vector_parse_clip_cache_path",
        ):
            path = result.get(key)
            if path and os.path.exists(path):
                os.unlink(path)


def test_worker_generate_preview_no_image_warning_has_actionable_fields(caplog) -> None:
    status_msg = "synthetic no preview image"
    target_logger = logging.getLogger("lumina.api.workers.converter_workers")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger="lumina.api.workers.converter_workers")

    try:
        with patch(
            "core.converter.generate_preview_cached",
            return_value=(None, None, status_msg),
        ):
            with pytest.raises(RuntimeError, match=status_msg):
                worker_generate_preview(
                    image_path="image.png",
                    lut_path="lut.npy",
                    target_width_mm=60.0,
                    color_mode="4-Color (RYBW)",
                    modeling_mode="high-fidelity",
                    color_layers=10,
                    layer_height_mm=0.08,
                    quantize_colors=16,
                    enable_cleanup=True,
                    enable_outline=True,
                    outline_width=2.5,
                )
    finally:
        target_logger.removeHandler(caplog.handler)

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "worker_preview_no_image"
    ]
    assert len(records) == 1

    record = records[0]
    assert record.error_type == "PreviewImageMissing"
    assert record.error_message == status_msg

    from scripts.log_quality_check import _has_actionable_warning_error_field

    assert _has_actionable_warning_error_field(record.__dict__) is True


def test_worker_generate_preview_no_image_warning_uses_default_message_for_blank_status(
    caplog,
) -> None:
    target_logger = logging.getLogger("lumina.api.workers.converter_workers")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger="lumina.api.workers.converter_workers")

    try:
        with patch(
            "core.converter.generate_preview_cached",
            return_value=(None, None, "   "),
        ):
            with pytest.raises(RuntimeError):
                worker_generate_preview(
                    image_path="image.png",
                    lut_path="lut.npy",
                    target_width_mm=60.0,
                    color_mode="4-Color (RYBW)",
                    modeling_mode="high-fidelity",
                    color_layers=10,
                    layer_height_mm=0.08,
                    quantize_colors=16,
                    enable_cleanup=True,
                    enable_outline=True,
                    outline_width=2.5,
                )
    finally:
        target_logger.removeHandler(caplog.handler)

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "worker_preview_no_image"
    ]
    assert len(records) == 1

    record = records[0]
    assert record.error_type == "PreviewImageMissing"
    assert record.error_message == "Preview generation returned no image."


def test_worker_generate_large_format_svg_native_uses_sanitized_tile_prefix_in_zip_entries(tmp_path) -> None:
    """Native SVG worker should emit safe ZIP entry names using tile_name_prefix."""

    class _FakeVectorProcessor:
        def __init__(self, lut_path: str, color_mode: str) -> None:
            self.lut_path = lut_path
            self.color_mode = color_mode

        def analyze_svg(self, **_kwargs):
            return SimpleNamespace(num_layers=5, slot_names=["Slot1"], preview_colors={0: [255, 0, 0, 255]})

        def build_mesh(self, **_kwargs):
            fake_geom = SimpleNamespace(vertices=[(0, 0, 0)], faces=[(0, 0, 0)])
            return SimpleNamespace(geometry={"Slot1": fake_geom})

    fake_tile = SimpleNamespace(
        label="R1C1",
        analysis=SimpleNamespace(
            preview_colors={0: [255, 0, 0, 255]},
            slot_names=["Slot1"],
        ),
    )

    captured_export_kwargs: list[dict[str, object]] = []

    def _fake_export_scene_with_bambu_metadata(*, output_path: str, **kwargs) -> None:
        captured_export_kwargs.append(dict(kwargs))
        with open(output_path, "wb") as handle:
            handle.write(b"3mf")

    params = {
        "tile_name_prefix": r"bad:name*",
        "total_width_mm": 120.0,
        "total_height_mm": 80.0,
        "tile_width_mm": 60.0,
        "tile_height_mm": 80.0,
        "spacer_thick": 1.2,
        "backing_infill_density_percent": 25,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
        "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
    }

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=[fake_tile]),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=None),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export_scene_with_bambu_metadata),
    ):
        result = worker_generate_large_format_svg_native("image.svg", "lut.npy", params)

    try:
        with zipfile.ZipFile(result["zip_path"], "r") as archive:
            assert archive.namelist() == ["bad_name_R1C1.3mf"]
        assert captured_export_kwargs
        assert (
            captured_export_kwargs[0]["device_profile_id"]
            == "BambuStudio:bbl:bambu-lab-h2d:0.4"
        )
        assert captured_export_kwargs[0]["backing_infill_density_percent"] == 25
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


def test_worker_generate_large_format_svg_native_applies_coating_to_tile() -> None:
    """A native SVG tile must inherit the requested transparent coating."""

    build_calls: list[dict[str, object]] = []

    class _FakeVectorProcessor:
        def __init__(self, lut_path: str, color_mode: str) -> None:
            self.lut_path = lut_path
            self.color_mode = color_mode

        def analyze_svg(self, **_kwargs):
            return SimpleNamespace(num_layers=5, slot_names=["Slot1"], preview_colors={0: [255, 0, 0, 255]})

        def build_mesh(self, **kwargs):
            build_calls.append(
                {
                    **kwargs,
                    "enable_coating": getattr(self, "enable_coating", False),
                    "coating_height_mm": getattr(self, "coating_height_mm", 0.08),
                }
            )
            fake_geom = SimpleNamespace(vertices=[(0, 0, 0)], faces=[(0, 0, 0)])
            return SimpleNamespace(geometry={"Slot1": fake_geom})

    fake_tile = SimpleNamespace(
        label="R1C1",
        analysis=SimpleNamespace(
            preview_colors={0: [255, 0, 0, 255]},
            slot_names=["Slot1"],
        ),
    )
    params = {
        "tile_name_prefix": "coating",
        "total_width_mm": 20.0,
        "total_height_mm": 20.0,
        "tile_width_mm": 20.0,
        "tile_height_mm": 20.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
        "enable_coating": True,
        "coating_height_mm": 0.12,
    }

    result = None
    with (
        patch(
            "core.pipeline.s03_color_replacement._normalize_color_replacements_input",
            return_value={},
        ),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch(
            "core.vector_large_format.slice_vector_analysis_into_tiles",
            return_value=[fake_tile],
        ),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=None),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=lambda *, output_path, **_kwargs: open(output_path, "wb").close(),
        ),
    ):
        result = worker_generate_large_format_svg_native(
            "image.svg",
            "lut.npy",
            params,
        )

    try:
        assert len(build_calls) == 1
        assert build_calls[0]["enable_coating"] is True
        assert build_calls[0]["coating_height_mm"] == pytest.approx(0.12)
    finally:
        if result is not None and os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


def test_worker_generate_large_format_svg_native_preserves_relief_semantics_per_tile(
    tmp_path,
) -> None:
    """Each native SVG tile receives relief settings and its global heightmap crop."""

    build_calls: list[dict[str, object]] = []
    sampled_heightmap_means: list[float] = []
    sampled_heightmap_sizes: list[tuple[int, int]] = []
    tile_heightmap_paths: list[str] = []

    class _FakeVectorProcessor:
        def __init__(self, lut_path: str, color_mode: str) -> None:
            self.lut_path = lut_path
            self.color_mode = color_mode

        def analyze_svg(self, **_kwargs):
            return SimpleNamespace(num_layers=5, slot_names=["Slot1"], preview_colors={0: [255, 0, 0, 255]})

        def build_mesh(self, **kwargs):
            build_calls.append(dict(kwargs))
            tile_heightmap_paths.append(kwargs["heightmap_path"])
            with Image.open(kwargs["heightmap_path"]) as heightmap:
                sampled_heightmap_means.append(float(np.asarray(heightmap).mean()))
                sampled_heightmap_sizes.append(heightmap.size)
            fake_geom = SimpleNamespace(vertices=[(0, 0, 0)], faces=[(0, 0, 0)])
            return SimpleNamespace(geometry={"Slot1": fake_geom})

    heightmap_path = tmp_path / "heightmap.png"
    heightmap = np.zeros((7, 9), dtype=np.uint8)
    heightmap[:4, 5:] = 64
    heightmap[4:, :5] = 128
    heightmap[4:, 5:] = 255
    Image.fromarray(heightmap).save(heightmap_path)

    def _tile(
        label: str,
        x0_mm: float,
        y0_mm: float,
        x1_mm: float,
        y1_mm: float,
    ):
        return SimpleNamespace(
            label=label,
            spec=SimpleNamespace(
                x0_mm=x0_mm,
                y0_mm=y0_mm,
                x1_mm=x1_mm,
                y1_mm=y1_mm,
            ),
            analysis=SimpleNamespace(
                preview_colors={0: [255, 0, 0, 255]},
                slot_names=["Slot1"],
            ),
        )

    params = {
        "tile_name_prefix": "relief",
        "total_width_mm": 70.0,
        "total_height_mm": 50.0,
        "tile_width_mm": 40.0,
        "tile_height_mm": 30.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
        "enable_relief": True,
        "height_mode": "heightmap",
        "color_height_map": {"#ff0000": 2.4},
        "heightmap_path": str(heightmap_path),
        "heightmap_max_height": 3.2,
    }

    result = None
    with (
        patch(
            "core.pipeline.s03_color_replacement._normalize_color_replacements_input",
            return_value={},
        ),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch(
            "core.vector_large_format.slice_vector_analysis_into_tiles",
            return_value=[
                _tile("R1C1", 0.0, 0.0, 40.0, 30.0),
                _tile("R1C2", 40.0, 0.0, 70.0, 30.0),
                _tile("R2C1", 0.0, 30.0, 40.0, 50.0),
                _tile("R2C2", 40.0, 30.0, 70.0, 50.0),
            ],
        ),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=None),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=lambda *, output_path, **_kwargs: open(output_path, "wb").close(),
        ),
    ):
        result = worker_generate_large_format_svg_native(
            "image.svg",
            "lut.npy",
            params,
        )

    try:
        assert len(build_calls) == 4
        for call in build_calls:
            assert call["enable_relief"] is True
            assert call["height_mode"] == "heightmap"
            assert call["color_height_map"] == {"#ff0000": 2.4}
            assert call["heightmap_max_height"] == pytest.approx(3.2)
        assert sampled_heightmap_means == pytest.approx(
            [0.0, 64.0, 128.0, 255.0]
        )
        assert sampled_heightmap_sizes == [(5, 4), (4, 4), (5, 3), (4, 3)]
        assert len(set(tile_heightmap_paths)) == 4
        assert all(not os.path.exists(path) for path in tile_heightmap_paths)
    finally:
        if result is not None and os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


def test_worker_generate_large_format_svg_native_cleans_heightmap_when_save_fails(
    tmp_path,
) -> None:
    """A failed tile-heightmap save must not leak its mkstemp file."""

    class _FakeVectorProcessor:
        def __init__(self, lut_path: str, color_mode: str) -> None:
            self.color_mode = color_mode

        def analyze_svg(self, **_kwargs):
            return SimpleNamespace(num_layers=5, slot_names=["Slot1"], preview_colors={0: [255, 0, 0, 255]})

    heightmap_path = tmp_path / "heightmap.png"
    Image.fromarray(np.zeros((4, 4), dtype=np.uint8)).save(heightmap_path)
    tile = SimpleNamespace(
        label="R1C1",
        spec=SimpleNamespace(x0_mm=0.0, y0_mm=0.0, x1_mm=40.0, y1_mm=40.0),
        analysis=SimpleNamespace(preview_colors={}, slot_names=[]),
    )
    params = {
        "total_width_mm": 40.0,
        "total_height_mm": 40.0,
        "tile_width_mm": 40.0,
        "tile_height_mm": 40.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "enable_relief": True,
        "height_mode": "heightmap",
        "heightmap_path": str(heightmap_path),
        "heightmap_max_height": 3.2,
    }
    created_heightmap_paths: list[str] = []
    original_mkstemp = __import__("tempfile").mkstemp

    def _capture_mkstemp(*args, **kwargs):
        fd, path = original_mkstemp(*args, **kwargs)
        if kwargs.get("suffix") == ".png":
            created_heightmap_paths.append(path)
        return fd, path

    try:
        with (
            patch(
                "core.pipeline.s03_color_replacement._normalize_color_replacements_input",
                return_value={},
            ),
            patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
            patch(
                "core.vector_large_format.slice_vector_analysis_into_tiles",
                return_value=[tile],
            ),
            patch("tempfile.mkstemp", side_effect=_capture_mkstemp),
            patch.object(Image.Image, "save", side_effect=OSError("disk full")),
        ):
            with pytest.raises(OSError, match="disk full"):
                worker_generate_large_format_svg_native(
                    "image.svg",
                    "lut.npy",
                    params,
                )

        assert created_heightmap_paths
        assert all(not os.path.exists(path) for path in created_heightmap_paths)
    finally:
        for path in created_heightmap_paths:
            if os.path.exists(path):
                os.unlink(path)


def test_worker_generate_large_format_svg_native_raises_when_all_tiles_are_empty() -> None:
    """Native SVG worker should surface the empty-slice failure clearly."""

    class _FakeVectorProcessor:
        def __init__(self, lut_path: str, color_mode: str) -> None:
            self.lut_path = lut_path
            self.color_mode = color_mode

        def analyze_svg(self, **_kwargs):
            return SimpleNamespace(num_layers=5, slot_names=["Slot1"], preview_colors={0: [255, 0, 0, 255]})

    params = {
        "tile_name_prefix": "poster-art",
        "total_width_mm": 120.0,
        "total_height_mm": 80.0,
        "tile_width_mm": 60.0,
        "tile_height_mm": 80.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
    }

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=[]),
    ):
        with pytest.raises(ValueError, match="All SVG large-format tiles were empty after slicing"):
            worker_generate_large_format_svg_native("image.svg", "lut.npy", params)


def test_worker_generate_large_format_svg_native_cleans_current_tile_file_on_export_exception() -> None:
    """Native SVG worker should delete the current tile file if export fails before append."""

    class _FakeVectorProcessor:
        def __init__(self, lut_path: str, color_mode: str) -> None:
            self.lut_path = lut_path
            self.color_mode = color_mode

        def analyze_svg(self, **_kwargs):
            return SimpleNamespace(num_layers=5, slot_names=["Slot1"], preview_colors={0: [255, 0, 0, 255]})

        def build_mesh(self, **_kwargs):
            fake_geom = SimpleNamespace(vertices=[(0, 0, 0)], faces=[(0, 0, 0)])
            return SimpleNamespace(geometry={"Slot1": fake_geom})

    fake_tiles = [
        SimpleNamespace(
            label="R1C1",
            analysis=SimpleNamespace(preview_colors={0: [255, 0, 0, 255]}, slot_names=["Slot1"]),
        ),
    ]
    created_paths: list[str] = []

    def _fake_export_scene_with_bambu_metadata(*, output_path: str, **_kwargs) -> None:
        with open(output_path, "wb") as handle:
            handle.write(b"3mf")
        created_paths.append(output_path)
        raise RuntimeError("tile export failed")

    params = {
        "tile_name_prefix": "poster-art",
        "total_width_mm": 120.0,
        "total_height_mm": 80.0,
        "tile_width_mm": 60.0,
        "tile_height_mm": 80.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
    }

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=fake_tiles),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=None),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export_scene_with_bambu_metadata),
    ):
        with pytest.raises(RuntimeError, match="tile export failed"):
            worker_generate_large_format_svg_native("image.svg", "lut.npy", params)

    assert created_paths
    assert all(not os.path.exists(path) for path in created_paths)
