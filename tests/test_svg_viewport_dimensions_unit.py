"""SVG fallback geometry and canvas must share the same coordinate domain."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from shapely.ops import unary_union

from core.native_svg_adapter import NativeSvgFallback, NativeSvgGeometry, analyze_native_svg
from core.vector_engine import VectorProcessor, parse_svg_geometry


def _write_svg(tmp_path: Path, attributes: str, content: str) -> Path:
    source = tmp_path / "viewport.svg"
    source.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" {attributes}>{content}</svg>',
        encoding="utf-8",
    )
    return source


def _legacy_bounds_mm(source: Path) -> tuple[float, float, float, float]:
    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    shapes, scale, _bbox = processor._parse_svg(str(source), 60.0)
    return tuple(value * scale for value in unary_union([item["poly"] for item in shapes]).bounds)


@pytest.mark.parametrize(
    ("width", "height"),
    [("300mm", "150mm"), ("30cm", "15cm"), ("2in", "1in"), ("400px", "200px")],
)
def test_legacy_viewport_units_preserve_requested_print_size(
    tmp_path: Path, width: str, height: str,
) -> None:
    source = _write_svg(
        tmp_path, f'width="{width}" height="{height}" viewBox="0 0 29994 14997"',
        '<rect width="29994" height="14997" fill="#f00"/>',
    )

    assert _legacy_bounds_mm(source) == pytest.approx((0, 0, 60, 30), abs=0.001)


@pytest.mark.parametrize("origin", ['x="0" y="0"', 'x="20" y="30"'])
def test_legacy_nonzero_viewbox_origin_is_not_applied_twice(tmp_path: Path, origin: str) -> None:
    source = _write_svg(
        tmp_path, f'{origin} width="200" height="100" viewBox="-100 200 1000 500"',
        '<rect x="-100" y="200" width="1000" height="500" fill="#f00"/>',
    )

    assert _legacy_bounds_mm(source) == pytest.approx((0, 0, 60, 30), abs=0.001)


@pytest.mark.parametrize(
    ("aspect", "expected"),
    [("xMidYMid meet", (15, 0, 45, 30)), ("none", (0, 0, 60, 30))],
)
def test_legacy_viewport_preserves_letterboxing_and_stretching(
    tmp_path: Path, aspect: str, expected: tuple[float, float, float, float],
) -> None:
    source = _write_svg(
        tmp_path, f'width="200" height="100" viewBox="10 20 100 100" preserveAspectRatio="{aspect}"',
        '<rect x="10" y="20" width="100" height="100" fill="#f00"/>',
    )

    assert _legacy_bounds_mm(source) == pytest.approx(expected, abs=0.001)


def test_legacy_root_transform_moves_canvas_with_geometry(tmp_path: Path) -> None:
    source = _write_svg(
        tmp_path,
        'width="200" height="100" viewBox="10 20 100 50" transform="translate(20 30) rotate(90)"',
        '<rect x="10" y="20" width="100" height="50" fill="#f00"/>',
    )

    assert _legacy_bounds_mm(source) == pytest.approx((0, 0, 60, 120), abs=0.001)


def test_legacy_nested_rotation_keeps_physical_viewport_size(tmp_path: Path) -> None:
    source = _write_svg(
        tmp_path, 'width="80mm" height="160mm" viewBox="0 0 40 80"',
        '<g transform="translate(40 0) rotate(90)">'
        '<svg width="80" height="40" viewBox="0 0 80 40" preserveAspectRatio="none">'
        '<rect width="80" height="40" fill="#f00"/></svg></g>',
    )

    assert _legacy_bounds_mm(source) == pytest.approx((0, 0, 60, 120), abs=0.001)


@pytest.mark.parametrize("container", ["svg", "symbol"])
def test_legacy_root_transform_keeps_nested_viewport_clip_in_output_space(
    tmp_path: Path, container: str,
) -> None:
    rectangle = '<rect width="100" height="50" fill="#f00"/>'
    content = (
        f'<svg x="10" y="20" width="100" height="50" viewBox="0 0 100 50">{rectangle}</svg>'
        if container == "svg"
        else f'<defs><symbol id="tile" viewBox="0 0 100 50">{rectangle}</symbol></defs>'
        '<use href="#tile" x="10" y="20" width="100" height="50"/>'
    )
    source = _write_svg(
        tmp_path,
        'width="200" height="100" viewBox="10 20 100 50" transform="translate(20 30) rotate(90)"',
        content,
    )

    assert _legacy_bounds_mm(source) == pytest.approx((0, 0, 60, 120), abs=0.001)


@pytest.mark.parametrize(
    ("overflow", "expected_height"),
    [
        ('overflow="hidden"', 30),
        ('overflow="visible" style="overflow: hidden"', 30),
        ('overflow="visible"', 60),
        ('overflow="hidden" style="overflow: visible"', 60),
    ],
)
def test_legacy_root_slice_respects_explicit_overflow(
    tmp_path: Path, overflow: str, expected_height: float,
) -> None:
    source = _write_svg(
        tmp_path,
        f'width="200" height="100" viewBox="10 20 100 100" preserveAspectRatio="xMidYMid slice" {overflow}',
        '<rect x="10" y="20" width="100" height="100" fill="#f00"/>',
    )

    assert _legacy_bounds_mm(source) == pytest.approx((0, 0, 60, expected_height), abs=0.001)


def test_legacy_visible_root_does_not_clip_nested_overflow(tmp_path: Path) -> None:
    source = _write_svg(
        tmp_path, 'width="200" height="100" viewBox="0 0 200 100" overflow="visible"',
        '<svg width="200" height="100" overflow="visible">'
        '<rect x="-100" width="400" height="100" fill="#f00"/></svg>',
    )

    assert _legacy_bounds_mm(source) == pytest.approx((0, 0, 60, 15), abs=0.001)


@pytest.mark.parametrize("masked", [False, True])
def test_public_svg_geometry_preserves_size_across_native_and_mask_fallback(
    tmp_path: Path, masked: bool,
) -> None:
    pytest.importorskip("lumina_svg_core")
    mask = (
        '<defs><mask id="opaque"><rect width="29994" height="29994" fill="#fff"/></mask></defs>'
        if masked else ""
    )
    mask_attribute = ' mask="url(#opaque)"' if masked else ""
    source = _write_svg(
        tmp_path, 'width="300mm" height="300mm" viewBox="0 0 29994 29994"',
        f'{mask}<rect width="29994" height="29994" fill="#f00"{mask_attribute}/>',
    )
    outcome = analyze_native_svg(str(source), 60.0, 0.05, expand_stroke_to_fill=True)
    if masked:
        assert isinstance(outcome, NativeSvgFallback)
        assert outcome.reason_code == "unsupported_mask"
    else:
        assert isinstance(outcome, NativeSvgGeometry)

    shapes, scale, _bbox = parse_svg_geometry(source, target_width_mm=60.0)
    bounds = np.asarray(unary_union([item["poly"] for item in shapes]).bounds) * scale

    np.testing.assert_allclose(bounds, [0, 0, 60, 60], atol=0.001)
