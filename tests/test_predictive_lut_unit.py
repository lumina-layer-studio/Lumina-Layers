"""Unit tests for LUT V2 predictive runtime support."""

from __future__ import annotations

import json
import os
import tempfile
import tracemalloc
from unittest.mock import patch

import msgpack
import numpy as np
import cv2
import pytest
from scipy.spatial import KDTree

from config import LUTMetadata, PaletteEntry
from core.lut_merger import LUTMerger
from core.predictive_lut import (
    PredictiveModeRuntime,
    _rgb_to_opencv_lab,
    match_unique_colors_with_runtime,
    opencv_lab_to_rgb_uint8,
)
from core.pipeline.processing_ops.lut_color_matcher import match_colors_to_lut
from core.pipeline.processing_ops.lut_loader import load_lut
from core.converter import generate_preview_cached
from utils.lut_manager import LUTManager


def _rgb_to_opencv_lab_float_space(rgb_array: np.ndarray) -> np.ndarray:
    """Build float-space OpenCV Lab values like the native/reference runtime."""
    rgb = np.asarray(rgb_array, dtype=np.uint8).reshape(1, -1, 3)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR).astype(np.float32) / 255.0
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).reshape(-1, 3).astype(np.float32)


def _build_predictive_metadata() -> LUTMetadata:
    return LUTMetadata(
        palette=[
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="Black", material="PLA Basic"),
        ],
        color_mode="8-Color Max",
        schema_version="2.0",
        capabilities=["legacy_lookup", "predictive_match", "dynamic_layer_height"],
        extensions={
            "stage_model": {"model_id": "predictive-model-1"},
            "runtime_package": {
                "defaults": {"threshold": 4.5, "margin": 0.8},
                "modes": {
                    "0.08x5": {
                        "layer_height_mm": 0.08,
                        "color_layers": 5,
                        "layer_order": "Top2Bottom",
                        "candidate_recipes": [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]],
                        "pred_lab": _rgb_to_opencv_lab(
                            np.array([[255, 255, 255], [0, 0, 0]], dtype=np.uint8)
                        ).tolist(),
                        "threshold": 4.5,
                        "margin": 0.8,
                    }
                },
            },
            "custom_block": {"keep": True},
        },
    )


def test_save_keyed_json_preserves_v2_extensions_by_default() -> None:
    """save_keyed_json should keep V2 extension blocks unless legacy_save is requested."""
    rgb = np.array([[255, 255, 255]], dtype=np.uint8)
    stacks = np.array([[0, 0, 0, 0, 0]], dtype=np.int32)
    metadata = _build_predictive_metadata()

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "predictive_lut.json")
        LUTManager.save_keyed_json(path, rgb, stacks, metadata)

        with open(path, "r", encoding="utf-8") as fh:
            saved = json.load(fh)

        assert saved["schema_version"] == "2.0"
        assert "predictive_match" in saved["capabilities"]
        assert "runtime_package" in saved
        assert saved["custom_block"] == {"keep": True}

        _rgb, loaded_stacks, loaded_metadata = LUTManager.load_lut_with_metadata(path)
        np.testing.assert_array_equal(loaded_stacks, stacks)
        assert loaded_metadata.supports_predictive_match() is True
        assert loaded_metadata.extensions["custom_block"] == {"keep": True}


def test_load_lut_returns_predictive_runtime_for_v2_json() -> None:
    """load_lut should expose predictive runtime payload when runtime_package exists."""
    rgb = np.array([[255, 255, 255], [0, 0, 0]], dtype=np.uint8)
    stacks = np.array([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32)
    metadata = _build_predictive_metadata()

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "predictive_runtime.json")
        LUTManager.save_keyed_json(path, rgb, stacks, metadata)

        loaded = load_lut(path, "8-Color Max")

        assert loaded["predictive_runtime"] is not None
        assert loaded["predictive_runtime"].mode_key == "0.08x5"
        assert loaded["predictive_threshold"] == 4.5
        assert "0.08x5" in loaded["predictive_modes"]


def test_match_colors_to_lut_prefers_predictive_runtime() -> None:
    """Predictive runtime should short-circuit legacy KD-tree matching when available."""
    unique_colors = np.array([[255, 255, 255], [0, 0, 0]], dtype=np.uint8)
    runtime = PredictiveModeRuntime(
        mode_key="0.08x5",
        layer_height_mm=0.08,
        color_layers=5,
        layer_order="Top2Bottom",
        candidate_recipes=np.array([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32),
        pred_lab=_rgb_to_opencv_lab(unique_colors),
        threshold=4.5,
        margin=0.8,
    )
    legacy_rgb = np.array([[12, 34, 56], [78, 90, 123]], dtype=np.uint8)
    legacy_lab = _rgb_to_opencv_lab(legacy_rgb)
    kdtree = KDTree(legacy_lab)

    result = match_colors_to_lut(
        unique_colors,
        legacy_rgb,
        legacy_lab,
        kdtree,
        predictive_runtime=runtime,
    )

    assert isinstance(result, dict)
    assert result["match_mode"] == "predictive"
    np.testing.assert_array_equal(
        np.asarray(result["recipes"], dtype=np.int32),
        np.array([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32),
    )


def test_match_colors_to_lut_native_model_only_bypasses_db_matching() -> None:
    """Native model-only matching should ignore DB lookup and use runtime candidates only."""
    unique_colors = np.array([[0, 255, 0]], dtype=np.uint8)
    runtime = PredictiveModeRuntime(
        mode_key="0.08x5",
        layer_height_mm=0.08,
        color_layers=5,
        layer_order="Top2Bottom",
        candidate_recipes=np.array([[7, 7, 7, 7, 7]], dtype=np.int32),
        pred_lab=_rgb_to_opencv_lab(unique_colors),
        threshold=4.5,
        margin=0.8,
    )
    legacy_rgb = np.array([[255, 0, 0], [0, 0, 255]], dtype=np.uint8)
    legacy_lab = _rgb_to_opencv_lab(legacy_rgb)
    kdtree = KDTree(legacy_lab)

    result = match_colors_to_lut(
        unique_colors,
        legacy_rgb,
        legacy_lab,
        kdtree,
        predictive_runtime=runtime,
        source_kind="predictive_package",
        native_reference_source=True,
        model_enable=False,
        model_only=True,
    )

    assert isinstance(result, dict)
    assert result["match_mode"] == "predictive"
    np.testing.assert_allclose(np.asarray(result["matched_rgb"], dtype=np.uint8), unique_colors, atol=8)
    np.testing.assert_array_equal(
        np.asarray(result["recipes"], dtype=np.int32),
        np.array([[7, 7, 7, 7, 7]], dtype=np.int32),
    )


def test_match_colors_to_lut_native_model_enable_gates_db_fallback_by_threshold_and_margin() -> None:
    """Native model-assisted matching should keep close DB hits and only override far DB hits."""
    unique_colors = np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)
    lut_rgb = np.array([[255, 0, 0], [0, 0, 255]], dtype=np.uint8)
    lut_lab = _rgb_to_opencv_lab(lut_rgb)
    kdtree = KDTree(lut_lab)
    runtime = PredictiveModeRuntime(
        mode_key="0.08x5",
        layer_height_mm=0.08,
        color_layers=5,
        layer_order="Top2Bottom",
        candidate_recipes=np.array([[9, 9, 9, 9, 9], [4, 4, 4, 4, 4]], dtype=np.int32),
        pred_lab=_rgb_to_opencv_lab(np.array([[0, 255, 0], [255, 0, 0]], dtype=np.uint8)),
        threshold=10.0,
        margin=1.0,
    )

    result = match_colors_to_lut(
        unique_colors,
        lut_rgb,
        lut_lab,
        kdtree,
        predictive_runtime=runtime,
        source_kind="predictive_package",
        native_reference_source=True,
        model_enable=True,
        model_only=False,
        ref_stacks=np.array([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32),
    )

    assert isinstance(result, dict)
    assert result["match_mode"] == "predictive"
    np.testing.assert_allclose(
        np.asarray(result["matched_rgb"], dtype=np.uint8),
        np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8),
        atol=8,
    )
    np.testing.assert_array_equal(
        np.asarray(result["recipes"], dtype=np.int32),
        np.array([[0, 0, 0, 0, 0], [9, 9, 9, 9, 9]], dtype=np.int32),
    )
    assert result["db_overrides"] == [False, True]
    assert result["threshold"] == 10.0
    assert result["margin"] == 1.0


def test_match_colors_to_lut_legacy_lookup_stays_legacy_without_predictive_runtime() -> None:
    """Pure legacy lookups should still return LUT indices when no runtime is available."""
    unique_colors = np.array([[254, 0, 0], [0, 0, 254]], dtype=np.uint8)
    lut_rgb = np.array([[255, 0, 0], [0, 0, 255]], dtype=np.uint8)
    lut_lab = _rgb_to_opencv_lab(lut_rgb)
    kdtree = KDTree(lut_lab)

    result = match_colors_to_lut(unique_colors, lut_rgb, lut_lab, kdtree)

    assert isinstance(result, np.ndarray)
    np.testing.assert_array_equal(result, np.array([0, 1], dtype=np.int64))


def test_opencv_lab_to_rgb_uint8_roundtrips_float_space_lab() -> None:
    """Float-space OpenCV Lab should convert back to the original RGB colors."""
    rgb = np.array(
        [[255, 255, 255], [0, 100, 240], [220, 20, 60], [0, 174, 66]],
        dtype=np.uint8,
    )

    converted = opencv_lab_to_rgb_uint8(_rgb_to_opencv_lab_float_space(rgb))

    np.testing.assert_allclose(converted, rgb, atol=2)


def test_match_unique_colors_with_runtime_accepts_float_space_pred_lab() -> None:
    """Runtime matching should compare against float-space native/reference OpenCV Lab."""
    unique_colors = np.array(
        [[255, 255, 255], [255, 128, 0]],
        dtype=np.uint8,
    )
    runtime = PredictiveModeRuntime(
        mode_key="0.08x2",
        layer_height_mm=0.08,
        color_layers=2,
        layer_order="Top2Bottom",
        candidate_recipes=np.array([[0, 0], [1, 1]], dtype=np.int32),
        pred_lab=_rgb_to_opencv_lab_float_space(unique_colors),
        threshold=4.5,
        margin=0.8,
    )

    result = match_unique_colors_with_runtime(unique_colors, runtime)

    np.testing.assert_array_equal(result["recipes"], runtime.candidate_recipes)
    np.testing.assert_allclose(result["matched_rgb"], unique_colors, atol=2)
    np.testing.assert_allclose(result["distances"], np.zeros(2, dtype=np.float32), atol=1e-4)


def test_predictive_matching_bounds_memory_and_keeps_first_equal_recipe() -> None:
    """Photo palettes must not allocate the full targets × recipes RGB tensor."""
    colors = np.random.default_rng(12).integers(0, 256, (1536, 3), dtype=np.uint8)
    endpoints = _rgb_to_opencv_lab(np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8))
    runtime = PredictiveModeRuntime(
        mode_key="0.08x2", layer_height_mm=0.08, color_layers=2,
        layer_order="Top2Bottom",
        candidate_recipes=np.tile([[0, 0], [1, 1]], (2048, 1)).astype(np.int32),
        pred_lab=np.tile(endpoints, (2048, 1)), threshold=80.0, margin=0.8,
    )
    # Every recipe predicts either black or white. The two-color reference
    # verifies exact distances, threshold boundaries, and duplicate tie order.
    reference = match_unique_colors_with_runtime(
        colors,
        PredictiveModeRuntime(
            mode_key="0.08x2", layer_height_mm=0.08, color_layers=2,
            layer_order="Top2Bottom", candidate_recipes=np.array([[0, 0], [1, 1]]),
            pred_lab=endpoints, threshold=80.0, margin=0.8,
        ),
    )
    # Make later equal-color recipes observably different from the first pair.
    runtime.candidate_recipes[2:] = [1, 0]
    tracemalloc.start()
    try:
        result = match_unique_colors_with_runtime(colors, runtime)
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    for key in ("recipes", "matched_rgb", "distances", "within_threshold"):
        np.testing.assert_array_equal(result[key], reference[key])
    assert peak_bytes < 64 * 1024 * 1024


def test_predictive_matching_searches_later_recipe_blocks_without_changing_ties() -> None:
    colors = np.array([[255, 0, 0], [0, 0, 0], [255, 255, 255]], dtype=np.uint8)
    lab = _rgb_to_opencv_lab(colors)
    predictions = np.repeat(lab[0:1], 16385, axis=0)
    predictions[8192] = lab[1]
    predictions[-1] = lab[2]
    recipes = np.tile([1, 0], (len(predictions), 1)).astype(np.int32)
    recipes[0] = [0, 0]
    recipes[8192] = [0, 1]
    recipes[-1] = [1, 1]
    runtime = PredictiveModeRuntime(
        mode_key="0.08x2", layer_height_mm=0.08, color_layers=2,
        layer_order="Top2Bottom", candidate_recipes=recipes,
        pred_lab=predictions, threshold=0.0, margin=0.8,
    )
    result = match_unique_colors_with_runtime(colors, runtime)
    np.testing.assert_array_equal(result["recipes"], [[0, 0], [0, 1], [1, 1]])
    np.testing.assert_array_equal(result["distances"], [0, 0, 0])
    assert np.all(result["within_threshold"])


def test_predict_recipe_color_rejects_non_exact_recipe_for_runtime_package_only_source() -> None:
    """Package-only runtime prediction should fail for recipes not present in candidate_recipes."""
    metadata = LUTMetadata(
        palette=[
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="Black", material="PLA Basic"),
        ],
        extensions={
            "runtime_package": {
                "defaults": {"threshold": 5.0, "margin": 0.7},
                "modes": {
                    "0.08x5": {
                        "layer_height_mm": 0.08,
                        "color_layers": 5,
                        "layer_order": "Top2Bottom",
                        "candidate_recipes": [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]],
                        "pred_lab": _rgb_to_opencv_lab(
                            np.array([[255, 255, 255], [0, 0, 0]], dtype=np.uint8)
                        ).tolist(),
                    }
                },
            }
        },
    )

    from core.predictive_lut import predict_recipe_color

    try:
        predict_recipe_color(
            metadata,
            recipe=[0, 1, 0, 1, 0],
            layer_height_mm=0.08,
            color_layers=5,
            layer_order="Top2Bottom",
        )
    except ValueError as exc:
        assert "not present in the runtime package" in str(exc)
    else:
        raise AssertionError("predict_recipe_color should reject non-exact package-only recipes")


def test_predict_recipe_color_falls_back_to_runtime_when_stage_model_dependencies_are_unavailable() -> None:
    """Bundled native assets should still support exact runtime prediction without the reference Python package."""
    metadata = LUTMetadata(
        palette=[
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="Black", material="PLA Basic"),
        ],
        extensions={
            "native_stage_model_path": "missing-stage-model.json",
            "native_db_paths": ["DB-A.json"],
            "runtime_package": {
                "defaults": {"threshold": 5.0, "margin": 0.7},
                "modes": {
                    "0.08x5": {
                        "layer_height_mm": 0.08,
                        "color_layers": 5,
                        "layer_order": "Top2Bottom",
                        "candidate_recipes": [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]],
                        "pred_lab": _rgb_to_opencv_lab(
                            np.array([[255, 255, 255], [0, 0, 0]], dtype=np.uint8)
                        ).tolist(),
                    }
                },
            },
        },
    )

    from core.predictive_lut import predict_recipe_color

    with patch("core.predictive_lut.ensure_reference_repo_importable"):
        payload = predict_recipe_color(
            metadata,
            recipe=[0, 0, 0, 0, 0],
            layer_height_mm=0.08,
            color_layers=5,
            layer_order="Top2Bottom",
        )

    assert payload["source"] == "runtime_package"
    assert payload["rgb"] == [255, 255, 255]


def test_merge_luts_preserves_compatible_predictive_payload() -> None:
    """Merging with one predictive source should preserve its runtime payload when palette stays compatible."""
    rgb_a = np.array([[255, 255, 255]], dtype=np.uint8)
    rgb_b = np.array([[0, 0, 0]], dtype=np.uint8)
    stacks_a = np.array([[0, 0, 0, 0, 0]], dtype=np.int32)
    stacks_b = np.array([[1, 1, 1, 1, 1]], dtype=np.int32)

    predictive_meta = _build_predictive_metadata()
    legacy_meta = LUTMetadata(
        palette=list(predictive_meta.palette),
        color_mode="8-Color Max",
    )

    _merged_rgb, _merged_stacks, stats = LUTMerger.merge_luts(
        [(rgb_a, stacks_a, "8-Color"), (rgb_b, stacks_b, "8-Color")],
        dedup_threshold=0,
        metadata_list=[predictive_meta, legacy_meta],
    )

    merged_metadata = stats["merged_metadata"]
    assert merged_metadata is not None
    assert merged_metadata.supports_predictive_match() is True
    assert merged_metadata.extensions["stage_model"]["model_id"] == "predictive-model-1"


def test_merge_luts_drops_incompatible_predictive_payloads() -> None:
    """Conflicting predictive payloads should be dropped with a warning."""
    rgb_a = np.array([[255, 255, 255]], dtype=np.uint8)
    rgb_b = np.array([[0, 0, 0]], dtype=np.uint8)
    stacks_a = np.array([[0, 0, 0, 0, 0]], dtype=np.int32)
    stacks_b = np.array([[1, 1, 1, 1, 1]], dtype=np.int32)

    meta_a = _build_predictive_metadata()
    meta_b = _build_predictive_metadata()
    meta_b.extensions["stage_model"] = {"model_id": "predictive-model-2"}

    _merged_rgb, _merged_stacks, stats = LUTMerger.merge_luts(
        [(rgb_a, stacks_a, "8-Color"), (rgb_b, stacks_b, "8-Color")],
        dedup_threshold=0,
        metadata_list=[meta_a, meta_b],
    )

    merged_metadata = stats["merged_metadata"]
    assert merged_metadata is not None
    assert merged_metadata.extensions == {}
    assert any("predictive metadata dropped" in warning for warning in stats["warnings"])


def test_load_lut_with_metadata_supports_native_model_package() -> None:
    """Native msgpack model packages should load as predictive-package sources."""
    payload = {
        "schema_version": 2,
        "name": "TestPackage",
        "scope": {"vendor": "BambuLab", "material_type": "PLA"},
        "channel_keys": ["White|PLA Basic", "Black|PLA Basic"],
        "defaults": {"threshold": 5.0, "margin": 0.7},
        "modes": [
            {
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
                "num_candidates": 2,
                "candidate_recipes": np.asarray([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.uint8).tobytes(),
                "pred_lab": np.asarray([[255, 128, 128], [0, 128, 128]], dtype="<f4").tobytes(),
            }
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "native.msgpack")
        with open(path, "wb") as fh:
            fh.write(msgpack.packb(payload, use_bin_type=True))

        rgb, stacks, metadata = LUTManager.load_lut_with_metadata(path)

        assert metadata.get_source_kind() == "predictive_package"
        assert metadata.supports_predictive_match() is True
        assert metadata.supports_dynamic_layer_count() is True
        assert any(mode["mode_key"] == "0.08x5" for mode in metadata.get_supported_modes())
        assert metadata.base_channel_idx == 0
        assert rgb.shape == (0, 3)
        assert stacks is None


def test_load_lut_with_metadata_filters_model_package_metadata_to_usable_runtime_modes() -> None:
    """Metadata should only expose model-package modes that survive runtime payload parsing."""
    payload = {
        "schema_version": 2,
        "name": "TestPackage",
        "scope": {"vendor": "BambuLab", "material_type": "PLA"},
        "channel_keys": ["White|PLA Basic"],
        "defaults": {"threshold": 5.0, "margin": 0.7},
        "modes": [
            {
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
                "num_candidates": "oops",
                "candidate_recipes": b"",
                "pred_lab": b"",
            },
            {
                "color_layers": 8,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
                "num_candidates": 1,
                "candidate_recipes": np.asarray([[0, 0, 0, 0, 0, 0, 0, 0]], dtype=np.uint8).tobytes(),
                "pred_lab": np.asarray([[50.0, 0.0, 0.0]], dtype="<f4").tobytes(),
            },
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "native.msgpack")
        with open(path, "wb") as fh:
            fh.write(msgpack.packb(payload, use_bin_type=True))

        rgb, stacks, metadata = LUTManager.load_lut_with_metadata(path)

        assert rgb.shape == (0, 3)
        assert stacks is None
        assert metadata.max_color_layers == 8
        assert metadata.layer_height_mm == pytest.approx(0.08)
        assert metadata.get_supported_modes() == [
            {
                "mode_key": "0.08x8",
                "color_layers": 8,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
            }
        ]


def test_load_lut_rejects_unavailable_dynamic_mode_for_direct_model_package() -> None:
    """Direct model-package loads should fail early when the requested layer mode is unavailable."""
    payload = {
        "schema_version": 2,
        "name": "TestPackage",
        "scope": {"vendor": "UnknownVendor", "material_type": "UnknownMaterial"},
        "channel_keys": ["White|PLA Basic", "Black|PLA Basic"],
        "defaults": {"threshold": 5.0, "margin": 0.7},
        "modes": [
            {
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
                "num_candidates": 2,
                "candidate_recipes": np.asarray([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.uint8).tobytes(),
                "pred_lab": np.asarray([[255, 128, 128], [0, 128, 128]], dtype="<f4").tobytes(),
            }
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "native.msgpack")
        with open(path, "wb") as fh:
            fh.write(msgpack.packb(payload, use_bin_type=True))

        with pytest.raises(ValueError, match="empty or corrupted"):
            load_lut(path, "8-Color Max", color_layers=10, layer_height_mm=0.08, model_enable=True)


def test_native_model_package_discovers_compatible_vendor_bundle_db_paths() -> None:
    """Native model packages should carry only compatible vendor/material ColorDB bundle paths."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )

    _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)

    native_db_paths = metadata.extensions.get("native_db_paths")

    assert metadata.get_source_kind() == "predictive_package"
    assert metadata.extensions.get("native_stage_model_path", "").endswith("bambulab_pla_stage_B.json")
    assert set(native_db_paths or []) >= {
        os.path.abspath(
            os.path.join(
                "reference",
                "ChromaPrint3D",
                "data",
                "dbs",
                "PLA",
                "BambuLab",
                "CMYW_008_5L.json",
            )
        ),
        os.path.abspath(
            os.path.join(
                "reference",
                "ChromaPrint3D",
                "data",
                "dbs",
                "PLA",
                "BambuLab",
                "RYBW_008_5L.json",
            )
        ),
        os.path.abspath(
            os.path.join(
                "reference",
                "ChromaPrint3D",
                "data",
                "dbs",
                "PLA",
                "BambuLab",
                "RYBWCMKG_004_10L_001.json",
            )
        ),
        os.path.abspath(
            os.path.join(
                "reference",
                "ChromaPrint3D",
                "data",
                "dbs",
                "PLA",
                "BambuLab",
                "RYBWCMKG_008_5L_001.json",
            )
        ),
    }


def test_load_lut_native_model_package_uses_requested_bundle_mode_for_exact_lookup() -> None:
    """Native model packages should use the matching ColorDB bundle for exact lookup at load time."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )

    loaded = load_lut(path, "8-Color Max", color_layers=5, layer_height_mm=0.08)

    assert loaded["source_kind"] == "predictive_package"
    assert loaded["lut_rgb"].shape == (3072, 3)
    assert loaded["ref_stacks"].shape == (3072, 5)
    assert int(np.max(loaded["ref_stacks"])) <= 7
    assert any(mode["mode_key"] == "0.08x10" for mode in loaded["supported_modes"])


def test_load_lut_native_model_package_10l_mode_does_not_leak_first_mode_synthetic_stacks() -> None:
    """Native package exact lookup at 10L should not inherit arbitrary 2-layer stacks from the package payload."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )

    loaded = load_lut(path, "8-Color Max", color_layers=10, layer_height_mm=0.08, model_enable=True)

    assert loaded["source_kind"] == "predictive_package"
    assert loaded["layer_count"] == 10
    assert loaded["ref_stacks"].ndim == 2
    assert loaded["ref_stacks"].shape[1] == 10
    assert loaded["lut_rgb"].shape[0] == loaded["ref_stacks"].shape[0]
    assert loaded["predictive_runtime"] is not None


def test_load_lut_native_model_package_10l_mode_uses_db_first_baseline_from_selected_dbs() -> None:
    """Native packages at 10L should keep a DB-first candidate space when selected DBs exist, even without same-mode DBs."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )

    loaded = load_lut(path, "8-Color Max", color_layers=10, layer_height_mm=0.08, model_enable=False)

    assert loaded["source_kind"] == "predictive_package"
    assert loaded["lut_rgb"].shape[0] > 0
    assert loaded["ref_stacks"].shape[0] == loaded["lut_rgb"].shape[0]
    assert loaded["ref_stacks"].shape[1] == 10


def test_bambulab_native_model_package_resolves_white_base_channel_not_green() -> None:
    """bambulab_pla.msgpack should resolve the package base channel to white, not palette index 0."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )

    _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)

    assert metadata.get_source_kind() == "predictive_package"
    assert metadata.palette[metadata.base_channel_idx].color.lower() == "white"
    assert metadata.base_channel_idx != 0


def test_native_colordb_preserves_native_ten_layer_recipes_from_bundled_assets() -> None:
    """Native CP3D ColorDB rows should keep their source recipe width."""
    path = os.path.join(
        "assets",
        "native_sources",
        "ChromaPrint3D",
        "data",
        "dbs",
        "PLA",
        "BambuLab",
        "RYBWCMKG_004_10L_001.json",
    )
    if not os.path.exists(path):
        pytest.skip(f"requires bundled native ColorDB: {path}")

    expected_recipe = [1, 1, 6, 0, 1, 4, 7, 5, 1, 4]
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    matching_rows = [
        idx
        for idx, entry in enumerate(data["entries"])
        if entry.get("recipe") == expected_recipe
    ]
    assert matching_rows
    row_index = matching_rows[0]

    _rgb, stacks, metadata = LUTManager.load_lut_with_metadata(path)

    assert stacks is not None
    assert stacks.shape[1] == 10
    assert metadata.max_color_layers == 10
    np.testing.assert_array_equal(
        stacks[row_index],
        np.asarray(expected_recipe, dtype=np.int32),
    )


def test_native_package_db_first_black_match_keeps_black_recipe_from_bundled_assets() -> None:
    """DB-first native matching should not replace black DB recipes with all-Air stacks."""
    path = os.path.join(
        "assets",
        "native_sources",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )
    if not os.path.exists(path):
        pytest.skip(f"requires bundled native model package: {path}")

    loaded = load_lut(
        path,
        "8-Color Max",
        color_layers=6,
        layer_height_mm=0.08,
        model_enable=True,
        model_only=False,
    )
    match = match_colors_to_lut(
        np.array([[0, 0, 0]], dtype=np.uint8),
        loaded["lut_rgb"],
        loaded["lut_lab"],
        loaded["kdtree"],
        predictive_runtime=loaded["predictive_runtime"],
        source_kind=loaded["source_kind"],
        native_reference_source=loaded["native_reference_source"],
        model_enable=True,
        model_only=False,
        ref_stacks=loaded["ref_stacks"],
    )
    recipe = (
        np.asarray(match["recipes"], dtype=np.int32)[0]
        if isinstance(match, dict)
        else loaded["ref_stacks"][int(np.asarray(match, dtype=np.int32)[0])]
    )

    assert 1 in {int(value) for value in recipe}
    assert not np.all(recipe < 0)


def test_native_model_package_converted_higher_layer_padding_uses_resolved_white_base_channel() -> None:
    """Converted higher-layer native DB stacks should pad with the resolved white base channel index."""
    bundle_path, _display_name = LUTManager.resolve_source_selection(
        source_kind="native_bundle",
        material_type="PLA",
        vendor="BambuLab",
        db_names=["RYBW_008_5L.json"],
    )

    _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(bundle_path)
    loaded = load_lut(bundle_path, "8-Color Max", color_layers=10, layer_height_mm=0.08, model_enable=False)

    assert metadata.palette[metadata.base_channel_idx].color.lower() == "white"
    padding_slice = loaded["ref_stacks"][:, 5:]
    assert padding_slice.shape[1] == 5
    assert np.all(padding_slice == metadata.base_channel_idx)


def test_load_lut_native_bundle_subset_constrains_db_first_candidate_space_after_recipe_conversion() -> None:
    """Selected DB subsets should still bound the DB-first search space after mode conversion."""
    bundle_path, _display_name = LUTManager.resolve_source_selection(
        source_kind="native_bundle",
        material_type="PLA",
        vendor="BambuLab",
        db_names=["RYBW_008_5L.json"],
    )

    loaded = load_lut(bundle_path, "8-Color Max", color_layers=10, layer_height_mm=0.08, model_enable=False)

    assert loaded["source_kind"] == "predictive_package"
    assert loaded["lut_rgb"].shape[0] == 1024
    assert loaded["ref_stacks"].shape == (1024, 10)
    used_channels = {int(value) for value in np.unique(loaded["ref_stacks"]) if int(value) >= 0}
    assert len(used_channels) <= 5


def test_load_native_bundle_exact_lookup_keeps_non_exact_selected_dbs_when_exact_mode_db_exists(monkeypatch) -> None:
    """Exact-mode DBs should be preferred but must not exclude other selected DBs from the DB-first candidate space."""
    metadata = LUTMetadata(
        layer_order="Top2Bottom",
        base_channel_idx=0,
        extensions={
            "native_db_paths": ["exact.json", "converted.json"],
            "native_channel_keys": ["White|PLA Basic"],
            "native_db_subset_explicit": True,
        },
    )

    def _fake_select(*_args, **_kwargs):
        return ("exact.json",)

    def _fake_load_keyed_json(path: str, _display: str):
        rgb = np.array([[1, 2, 3]], dtype=np.uint8) if path == "exact.json" else np.array([[4, 5, 6]], dtype=np.uint8)
        stacks = np.array([[0, 0, 0, 0, 0]], dtype=np.int32)
        db_meta = LUTMetadata(
            palette=[PaletteEntry(color="White", material="PLA Basic")],
            layer_height_mm=0.08,
            layer_order="Top2Bottom",
        )
        return rgb, stacks, db_meta

    monkeypatch.setattr("utils.lut_manager.select_native_db_paths_for_mode", _fake_select)
    monkeypatch.setattr(LUTManager, "_load_keyed_json", staticmethod(_fake_load_keyed_json))

    rgb, stacks = LUTManager.load_native_bundle_exact_lookup(
        metadata,
        color_layers=10,
        layer_height_mm=0.08,
        layer_order="Top2Bottom",
    )

    assert rgb.shape == (2, 3)
    assert stacks.shape == (2, 10)


def test_load_lut_native_stage_model_uses_requested_bundle_mode_for_exact_lookup() -> None:
    """Native stage-model sources should select the matching bundle ColorDB for the requested mode."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "models",
        "forward",
        "bambulab_pla_stage_B.json",
    )

    loaded = load_lut(path, "8-Color Max", color_layers=10, layer_height_mm=0.04)

    assert loaded["source_kind"] == "predictive_stage_model"
    assert loaded["lut_rgb"].shape == (1024, 3)
    assert loaded["ref_stacks"].shape == (1024, 10)
    assert int(np.max(loaded["ref_stacks"])) <= 7
    assert any(mode["mode_key"] == "0.08x10" for mode in loaded["supported_modes"])


def test_native_model_gate_compares_db_distance_in_runtime_lab_space() -> None:
    """Native model gate should report DB distances in the runtime Lab encoding, not legacy uint8 Lab."""
    unique_colors = np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)
    lut_rgb = np.array([[255, 0, 0], [0, 0, 255]], dtype=np.uint8)
    lut_lab = _rgb_to_opencv_lab(lut_rgb)
    kdtree = KDTree(lut_lab)
    runtime = PredictiveModeRuntime(
        mode_key="0.08x5",
        layer_height_mm=0.08,
        color_layers=5,
        layer_order="Top2Bottom",
        candidate_recipes=np.array([[9, 9, 9, 9, 9], [4, 4, 4, 4, 4]], dtype=np.int32),
        pred_lab=_rgb_to_opencv_lab_float_space(np.array([[0, 255, 0], [255, 0, 0]], dtype=np.uint8)),
        threshold=10.0,
        margin=1.0,
    )

    result = match_colors_to_lut(
        unique_colors,
        lut_rgb,
        lut_lab,
        kdtree,
        predictive_runtime=runtime,
        source_kind="predictive_package",
        native_reference_source=True,
        model_enable=True,
        model_only=False,
        ref_stacks=np.array([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32),
    )

    expected_unique_lab = _rgb_to_opencv_lab_float_space(unique_colors)
    expected_db_lab = _rgb_to_opencv_lab_float_space(lut_rgb)
    expected_db_tree = KDTree(expected_db_lab)
    expected_db_distances, _expected_indices = expected_db_tree.query(expected_unique_lab)

    np.testing.assert_allclose(
        np.asarray(result["db_distances"], dtype=np.float32),
        np.asarray(expected_db_distances, dtype=np.float32),
        atol=1e-4,
    )


def test_native_predictive_runtime_without_db_baseline_falls_back_to_runtime_only_without_crashing() -> None:
    """Native predictive sources with no DB baseline should behave as explicit runtime-only matches."""
    unique_colors = np.array([[255, 255, 255], [0, 0, 0]], dtype=np.uint8)
    runtime = PredictiveModeRuntime(
        mode_key="0.08x5",
        layer_height_mm=0.08,
        color_layers=5,
        layer_order="Top2Bottom",
        candidate_recipes=np.array([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32),
        pred_lab=_rgb_to_opencv_lab_float_space(unique_colors),
        threshold=4.5,
        margin=0.8,
    )

    result = match_colors_to_lut(
        unique_colors,
        np.zeros((0, 3), dtype=np.uint8),
        np.zeros((0, 3), dtype=np.float32),
        None,
        predictive_runtime=runtime,
        source_kind="predictive_package",
        native_reference_source=True,
        model_enable=False,
        model_only=False,
        ref_stacks=np.zeros((0, 5), dtype=np.int32),
    )

    assert isinstance(result, dict)
    assert result["match_mode"] == "predictive"
    assert result["db_baseline_available"] is False
    np.testing.assert_array_equal(np.asarray(result["recipes"], dtype=np.int32), runtime.candidate_recipes)


def test_load_lut_native_model_package_uses_runtime_defaults_when_model_threshold_margin_unset() -> None:
    """Unset or negative overrides should keep the runtime package default threshold and margin."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )

    loaded = load_lut(
        path,
        "8-Color Max",
        color_layers=5,
        layer_height_mm=0.08,
        model_enable=True,
        model_threshold=-1.0,
        model_margin=None,
    )

    assert loaded["predictive_runtime"] is not None
    assert loaded["predictive_threshold"] == 5.0
    assert loaded["predictive_margin"] == 0.7


def test_reference_colordb_does_not_bind_incompatible_global_predictive_assets() -> None:
    """A 4-color ReferenceDB source should not auto-bind an incompatible 8-color package/stage model."""
    path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "dbs",
        "PLA",
        "BambuLab",
        "RYBW_008_5L.json",
    )
    rgb, stacks, metadata = LUTManager.load_lut_with_metadata(path)

    assert rgb.shape[0] == stacks.shape[0] == 1024
    assert stacks.shape[1] == 5
    assert int(np.max(stacks)) <= 3
    assert metadata.get_source_kind() == "colordb_backed"
    assert metadata.extensions.get("native_model_package_path") is None
    assert metadata.extensions.get("native_stage_model_path") is None
    assert len(metadata.get_supported_modes()) == 1
    mode = metadata.get_supported_modes()[0]
    assert mode["color_layers"] == 5
    assert abs(mode["layer_height_mm"] - 0.08) < 1e-3
    assert mode["layer_order"] == "Top2Bottom"


def test_reference_colordb_preview_uses_palette_colors_and_in_range_layer_indices() -> None:
    """ReferenceDB preview cache should keep layer indices within palette range and expose non-white preview colors."""
    lut_path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "dbs",
        "PLA",
        "BambuLab",
        "RYBW_008_5L.json",
    )
    image = np.zeros((20, 20, 4), dtype=np.uint8)
    image[:10, :10, :3] = [255, 255, 255]
    image[:10, 10:, :3] = [255, 230, 0]
    image[10:, :10, :3] = [220, 20, 60]
    image[10:, 10:, :3] = [0, 100, 240]
    image[:, :, 3] = 255

    with tempfile.TemporaryDirectory() as tmpdir:
        image_path = os.path.join(tmpdir, "reference_preview.png")
        from PIL import Image

        Image.fromarray(image).save(image_path)
        _preview, cache, status = generate_preview_cached(
            image_path=image_path,
            lut_path=lut_path,
            target_width_mm=20,
            color_mode="4-Color (RYBW)",
            modeling_mode="high-fidelity",
            color_layers=5,
            layer_height_mm=0.08,
            quantize_colors=8,
            enable_cleanup=False,
            is_dark=True,
            hue_weight=0.0,
            chroma_gate=15.0,
        )

    assert "Preview" in status
    material_matrix = cache["material_matrix"]
    slot_names = cache["slot_names"]
    preview_colors = cache["preview_colors"]

    assert slot_names == ["White", "Yellow", "Red", "Blue"]
    assert sorted(preview_colors.keys()) == [0, 1, 2, 3]
    assert len({tuple(value[:3]) for value in preview_colors.values()}) == 4
    assert not all(tuple(value[:3]) == (255, 255, 255) for value in preview_colors.values())
    assert int(np.max(material_matrix)) < len(slot_names)


def test_native_model_package_preview_preserves_palette_order_colors() -> None:
    """Direct native msgpack sources should preserve package palette order when deriving preview colors."""
    lut_path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )
    image = np.zeros((16, 16, 4), dtype=np.uint8)
    image[:8, :8, :3] = [0, 174, 66]
    image[:8, 8:, :3] = [0, 0, 0]
    image[8:, :8, :3] = [0, 100, 240]
    image[8:, 8:, :3] = [255, 255, 255]
    image[:, :, 3] = 255

    with tempfile.TemporaryDirectory() as tmpdir:
        image_path = os.path.join(tmpdir, "native_package_preview.png")
        from PIL import Image

        Image.fromarray(image).save(image_path)
        _preview, cache, status = generate_preview_cached(
            image_path=image_path,
            lut_path=lut_path,
            target_width_mm=16,
            color_mode="8-Color Max",
            modeling_mode="high-fidelity",
            color_layers=5,
            layer_height_mm=0.08,
            quantize_colors=8,
            enable_cleanup=False,
            is_dark=True,
            hue_weight=0.0,
            chroma_gate=15.0,
        )

    assert "Preview" in status
    slot_names = cache["slot_names"]
    preview_colors = cache["preview_colors"]

    assert slot_names[:4] == ["bambugreen", "black", "blue", "cyan"]
    assert preview_colors[0][:3] == [0, 174, 66]
    assert preview_colors[1][:3] == [0, 0, 0]
    assert preview_colors[2][:3] == [10, 41, 137]
    assert preview_colors[6][:3] == [255, 255, 255]


def test_native_model_package_preview_uses_bundle_exact_lookup_instead_of_monochrome_blue() -> None:
    """ReferencePack previews should use vendor-bundle ColorDB lookup, not the tiny synthetic package LUT."""
    lut_path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "model_packs",
        "bambulab_pla.msgpack",
    )
    image = np.zeros((24, 24, 4), dtype=np.uint8)
    image[:12, :12, :3] = [255, 255, 255]
    image[:12, 12:, :3] = [255, 230, 0]
    image[12:, :12, :3] = [220, 20, 60]
    image[12:, 12:, :3] = [0, 100, 240]
    image[:, :, 3] = 255

    with tempfile.TemporaryDirectory() as tmpdir:
        image_path = os.path.join(tmpdir, "native_bundle_preview.png")
        from PIL import Image

        Image.fromarray(image).save(image_path)
        _preview, cache, status = generate_preview_cached(
            image_path=image_path,
            lut_path=lut_path,
            target_width_mm=16,
            color_mode="8-Color Max",
            modeling_mode="high-fidelity",
            color_layers=5,
            layer_height_mm=0.08,
            quantize_colors=8,
            enable_cleanup=False,
            is_dark=True,
            hue_weight=0.0,
            chroma_gate=15.0,
        )

    assert "Preview" in status
    matched = cache["matched_rgb"]
    h, w = matched.shape[:2]
    top_left = matched[: h // 2, : w // 2].mean(axis=(0, 1))
    top_right = matched[: h // 2, w // 2 :].mean(axis=(0, 1))
    bottom_left = matched[h // 2 :, : w // 2].mean(axis=(0, 1))
    bottom_right = matched[h // 2 :, w // 2 :].mean(axis=(0, 1))

    assert top_left.min() > 150  # near white
    assert top_right[0] > top_right[2] and top_right[1] > top_right[2]  # yellow-ish
    assert bottom_left[0] > bottom_left[1] and bottom_left[0] > bottom_left[2]  # red-ish
    assert bottom_right[2] > bottom_right[0] and bottom_right[2] > bottom_right[1]  # blue-ish
