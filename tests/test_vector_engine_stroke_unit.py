"""Regression tests for vector stroke handling alignment.

These tests cover the P0/P1 behavior lock from
``docs/svg_alignment/subagent_c_rootcause.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.vector_engine as vector_engine
from core.vector_engine import VectorProcessor


REPO_ROOT = Path(__file__).resolve().parents[1]
LUT_PATH = REPO_ROOT / "tests/fixtures/lut_regression" / "Bambulab&PLA&RYBW&红-黄-蓝-白.npy"
COLOR_MODE = "4-Color (RYBW)"
TARGET_WIDTH_MM = 100.0


@pytest.fixture()
def processor() -> VectorProcessor:
    return VectorProcessor(str(LUT_PATH), COLOR_MODE)


def _artifact_json(*parts: str) -> dict:
    path = REPO_ROOT.joinpath(*parts)
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_svg(name: str) -> str:
    return str(REPO_ROOT / "tests" / "fixtures" / "svg_alignment" / name)


def _pixel_tolerance_mm(meta: dict) -> float:
    width_px = int(meta["width_px"])
    x0, x1 = (float(value) for value in meta["xlim"])
    return abs(x1 - x0) / max(width_px, 1)


def _geometry_bounds_by_name(scene, name: str) -> list[list[float]]:
    mesh = scene.geometry[name]
    return [[float(v) for v in row] for row in mesh.bounds.tolist()]


def _assert_bounds_close(actual: list[list[float]], expected: list[list[float]], tolerance_mm: float) -> None:
    for actual_row, expected_row in zip(actual, expected):
        for actual_value, expected_value in zip(actual_row[:2], expected_row[:2]):
            assert abs(actual_value - expected_value) <= tolerance_mm


def test_stroke_only_default_raises_no_valid_shapes(processor: VectorProcessor) -> None:
    with pytest.raises(ValueError, match="No valid shapes found in SVG"):
        processor.analyze_svg(_fixture_svg("stroke_only.svg"), target_width_mm=TARGET_WIDTH_MM)


def test_stroke_only_expansion_uses_native_geometry(
    processor: VectorProcessor,
) -> None:
    processor.expand_stroke_to_fill = True
    analysis = processor.analyze_svg(
        _fixture_svg("stroke_only.svg"),
        target_width_mm=TARGET_WIDTH_MM,
    )

    assert analysis.shape_data
    assert analysis.stage_timings["geometry_backend"] == "native"
    assert {
        item["source_kind"] for item in analysis.shape_data
    } == {"stroke_only"}
    assert {
        tuple(item["rgba"]) for item in analysis.shape_data
    } == {(0, 0, 0, 255)}


def test_fill_eq_stroke_default_matches_b2_no_stroke_bounds(processor: VectorProcessor) -> None:
    expected_manifest = _artifact_json(
        "artifacts", "svg_diagnosis", "synth_fill_eq_stroke", "scene_manifest_no_stroke.json"
    )
    expected_meta = _artifact_json(
        "artifacts", "svg_diagnosis", "synth_fill_eq_stroke", "render_top_no_stroke_meta.json"
    )

    analysis = processor.analyze_svg(_fixture_svg("fill_eq_stroke.svg"), target_width_mm=TARGET_WIDTH_MM)
    scene = processor.build_mesh(analysis=analysis, thickness_mm=2.4, structure_mode="Single-sided")

    actual_bounds = _geometry_bounds_by_name(scene, "Yellow")
    expected_bounds = next(
        item["bounds_mm"] for item in expected_manifest["geometries"] if item["name"] == "Yellow"
    )
    _assert_bounds_close(actual_bounds, expected_bounds, _pixel_tolerance_mm(expected_meta))


def test_default_stroke_disabled_does_not_resolve_stroke_color(
    processor: VectorProcessor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_on_stroke_color(_color_obj):
        raise AssertionError("default stroke-disabled parse should not resolve stroke color")

    monkeypatch.setattr(vector_engine, "_color_object_to_hex", fail_on_stroke_color)

    analysis = processor.analyze_svg(_fixture_svg("fill_eq_stroke.svg"), target_width_mm=TARGET_WIDTH_MM)

    assert analysis.shape_data


def test_fill_eq_stroke_legacy_mode_matches_b2_baseline_bounds(processor: VectorProcessor) -> None:
    processor.expand_stroke_to_fill = True
    expected_manifest = _artifact_json(
        "artifacts", "svg_diagnosis", "synth_fill_eq_stroke", "scene_manifest.json"
    )
    expected_meta = _artifact_json(
        "artifacts", "svg_diagnosis", "synth_fill_eq_stroke", "render_top_meta.json"
    )

    analysis = processor.analyze_svg(_fixture_svg("fill_eq_stroke.svg"), target_width_mm=TARGET_WIDTH_MM)
    scene = processor.build_mesh(analysis=analysis, thickness_mm=2.4, structure_mode="Single-sided")

    actual_bounds = _geometry_bounds_by_name(scene, "Yellow")
    expected_bounds = next(
        item["bounds_mm"] for item in expected_manifest["geometries"] if item["name"] == "Yellow"
    )
    _assert_bounds_close(actual_bounds, expected_bounds, _pixel_tolerance_mm(expected_meta))


def test_ring_with_hole_default_keeps_single_shape_and_hole(processor: VectorProcessor) -> None:
    analysis = processor.analyze_svg(_fixture_svg("ring_with_hole.svg"), target_width_mm=TARGET_WIDTH_MM)

    assert len(analysis.shape_data) == 1
    assert analysis.silhouette is not None
    polygons = [analysis.silhouette] if analysis.silhouette.geom_type == "Polygon" else list(analysis.silhouette.geoms)
    assert any(len(poly.interiors) >= 1 for poly in polygons)


def test_real_svg_default_uses_native_fill_only_geometry(
    processor: VectorProcessor,
) -> None:
    analysis = processor.analyze_svg(
        str(REPO_ROOT / "test_images" / "1.svg"),
        target_width_mm=TARGET_WIDTH_MM,
    )

    assert analysis.stage_timings["geometry_backend"] == "native"
    assert all(
        item.get("source_kind") != "stroke_only"
        for item in analysis.shape_data
    )


def test_local_svg_without_stroke_keeps_shape_count(processor: VectorProcessor) -> None:
    expected = _artifact_json("artifacts", "svg_diagnosis", "local", "source_stats.json")

    analysis = processor.analyze_svg(str(REPO_ROOT / "test_images" / "1.svg"), target_width_mm=TARGET_WIDTH_MM)

    assert len(analysis.shape_data) == int(expected["shape_data_count"]) == 88
