"""Pytest global configuration for test stability and smoke tagging."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

SMOKE_TEST_FILES = {
    "test_api_app_unit.py",
    "test_api_errors_unit.py",
    "test_converter_puzzle_unit.py",
    "test_converter_structure_contract_unit.py",
    "test_structured_logging_unit.py",
    "test_heightmap_upload_unit.py",
    "test_converter_preview_unit.py",
    "test_puzzle_3mf_unit.py",
}

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = REPO_ROOT / "reference" / "ChromaPrint3D"
SVG_DIAGNOSIS_ROOT = REPO_ROOT / "artifacts" / "svg_diagnosis"

REFERENCE_ASSET_TESTS = {
    "test_native_reference_compatibility_unit.py": {
        "test_colordb_discovery_skips_incompatible_global_predictive_assets",
        "test_direct_reference_colordb_stays_single_db_even_when_global_predictive_assets_exist",
        "test_native_colordb_infers_cmyw_variant_from_palette_contents",
        "test_native_colordb_infers_rybwgk_variant_from_palette_contents",
        "test_native_model_package_bundle_includes_subset_mode_colordbs",
        "test_native_model_package_metadata_load_does_not_expose_arbitrary_first_mode_exact_stacks",
        "test_native_stage_model_metadata_uses_white_base_channel_from_compatible_package",
        "test_native_stage_model_non_exact_mode_lookup_keeps_converted_padding_and_white_base",
        "test_native_model_package_float_space_lab_preview_conversion_uses_reference_semantics",
    },
    "test_predictive_lut_unit.py": {
        "test_native_model_package_discovers_compatible_vendor_bundle_db_paths",
        "test_load_lut_native_model_package_uses_requested_bundle_mode_for_exact_lookup",
        "test_load_lut_native_model_package_10l_mode_does_not_leak_first_mode_synthetic_stacks",
        "test_load_lut_native_model_package_10l_mode_uses_db_first_baseline_from_selected_dbs",
        "test_bambulab_native_model_package_resolves_white_base_channel_not_green",
        "test_load_lut_native_stage_model_uses_requested_bundle_mode_for_exact_lookup",
        "test_load_lut_native_model_package_uses_runtime_defaults_when_model_threshold_margin_unset",
        "test_reference_colordb_does_not_bind_incompatible_global_predictive_assets",
        "test_reference_colordb_preview_uses_palette_colors_and_in_range_layer_indices",
        "test_native_model_package_preview_preserves_palette_order_colors",
        "test_native_model_package_preview_uses_bundle_exact_lookup_instead_of_monochrome_blue",
    },
    "test_reference_layer_images_unit.py": {
        "test_reference_colordb_layer_images_are_available",
    },
}

SVG_DIAGNOSIS_ASSET_TESTS = {
    "test_fill_eq_stroke_default_matches_b2_no_stroke_bounds",
    "test_fill_eq_stroke_legacy_mode_matches_b2_baseline_bounds",
    "test_local_svg_without_stroke_keeps_shape_count",
}


@pytest.fixture(autouse=True)
def _finish_preview_jobs_before_capture_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep actual preview tasks within the test that owns their resources."""
    async_glb = sys.modules.get("api.routers.converter.async_glb")
    if async_glb is None:
        yield
        return
    mesh_cache = async_glb.RecentPreviewMesh()
    monkeypatch.setattr(async_glb, "_RECENT_MESH", mesh_cache)
    try:
        with ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="test-glb-build",
        ) as executor:
            monkeypatch.setattr(async_glb, "_GLB_EXECUTOR", executor)
            yield
    finally:
        mesh_cache.clear()


def pytest_configure(config: pytest.Config) -> None:
    """Register deterministic Hypothesis defaults for CI and local runs."""
    settings.register_profile(
        "lumina",
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    settings.load_profile("lumina")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark selected fast, high-signal tests as smoke for PR gate runs."""
    smoke_marker = pytest.mark.smoke
    for item in items:
        filename = Path(str(item.fspath)).name
        if filename in SMOKE_TEST_FILES:
            item.add_marker(smoke_marker)
        if filename in REFERENCE_ASSET_TESTS and item.name in REFERENCE_ASSET_TESTS[filename]:
            if not REFERENCE_ROOT.exists():
                item.add_marker(pytest.mark.skip(reason=f"requires external test asset: {REFERENCE_ROOT}"))
        if filename == "test_vector_engine_stroke_unit.py" and item.name in SVG_DIAGNOSIS_ASSET_TESTS:
            if not SVG_DIAGNOSIS_ROOT.exists():
                item.add_marker(pytest.mark.skip(reason=f"requires external test asset: {SVG_DIAGNOSIS_ROOT}"))
