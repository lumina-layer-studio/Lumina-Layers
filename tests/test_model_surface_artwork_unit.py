from __future__ import annotations

from PIL import Image
import pytest
from shapely.ops import unary_union

from core import native_svg_adapter
from core.model_surface.artwork import SurfacePlacement, render_surface_artwork
from core.model_surface.types import EdgeMode, ModelSurfaceError, PlaneFrame, SurfaceFootprint
from core.vector_engine import VectorProcessor


@pytest.mark.parametrize("offset,alpha", [(100.0, 255), (0.0, 9)])
def test_raster_artwork_without_printable_overlap_is_rejected(tmp_path, offset, alpha):
    source = tmp_path / "art.png"
    Image.new("RGBA", (20, 20), (100, 50, 10, alpha)).save(source)

    with pytest.raises(ModelSurfaceError, match="model_surface_artwork_no_overlap"):
        render_surface_artwork(
            source_path=source,
            footprint=_square_footprint(),
            placement=SurfacePlacement(offset_x_mm=offset),
            output_dir=tmp_path,
        )

    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("native_available", [True, False])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_surface_svg_preserves_authored_strokes_and_filters_only_generated_gap_lines(
    tmp_path, monkeypatch: pytest.MonkeyPatch, native_available: bool, encoding: str,
):
    if not native_available:
        def unavailable():
            raise ImportError("native SVG unavailable")

        monkeypatch.setattr(native_svg_adapter, "_load_native_module", unavailable)
    source = tmp_path / "authored-strokes.svg"
    source.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <rect width="20" height="20" fill="#0080ff"/>
          <g transform="translate(0 2)" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round">
            <path d="M2 4H18"/>
            <circle cx="10" cy="10" r="3"/>
          </g>
          <path class="qq3d-gap-filler" fill="none" stroke="#ff0000"
                stroke-width="2" vector-effect="non-scaling-stroke" d="M2 18H18"/>
        </svg>""",
        encoding=encoding,
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=2,
        output_dir=tmp_path,
    )

    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale, _bounds = processor._parse_svg(str(result.output_path), 20.0)
    clipped = processor._clip_occlusion(shapes)
    by_color = {
        color: unary_union([item["geometry"] for item in clipped if item["color"] == color])
        for color in {item["color"] for item in clipped}
    }
    assert set(by_color) == {(0, 128, 255), (255, 255, 255)}
    white = by_color[(255, 255, 255)]
    assert white.area * scale**2 == pytest.approx(32.0 + 13.0 * 3.14159265, abs=0.5)
    assert by_color[(0, 128, 255)].intersection(white).area * scale**2 < 0.01


@pytest.mark.parametrize("native_available", [True, False])
def test_surface_svg_clips_authored_stroke_after_group_transform(
    tmp_path, monkeypatch: pytest.MonkeyPatch, native_available: bool,
):
    if not native_available:
        def unavailable():
            raise ImportError("native SVG unavailable")

        monkeypatch.setattr(native_svg_adapter, "_load_native_module", unavailable)
    source = tmp_path / "clipped-stroke.svg"
    source.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <defs><clipPath id="clip"><rect x="2" y="2" width="16" height="16"/></clipPath></defs>
          <rect width="20" height="20" fill="#0080ff"/>
          <g transform="translate(0 2)" clip-path="url(#clip)"
             fill="none" stroke="#ffffff" stroke-width="2"><path d="M0 4H20"/></g>
        </svg>""", encoding="utf-8",
    )
    result = render_surface_artwork(
        source_path=source, footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE), output_dir=tmp_path,
    )
    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale, _bounds = processor._parse_svg(str(result.output_path), 20.0)
    white = unary_union([item["poly"] for item in shapes if item["color"] == (255, 255, 255)])
    assert white.area * scale**2 == pytest.approx(32.0, abs=0.1)
    assert tuple(value * scale for value in white.bounds) == pytest.approx((2, 5, 18, 7), abs=0.02)


def test_surface_svg_uses_visible_native_paint_for_translucent_stroke(tmp_path):
    source = tmp_path / "translucent-stroke.svg"
    source.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <rect width="20" height="20" fill="#0080ff"/>
          <path d="M2 6H18" fill="none" stroke="#ffffff" stroke-width="2" stroke-opacity="0.5"/>
        </svg>""", encoding="utf-8",
    )
    result = render_surface_artwork(
        source_path=source, footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE), output_dir=tmp_path,
    )
    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, _scale, _bounds = processor._parse_svg(str(result.output_path), 20.0)

    assert {item["color"] for item in shapes} == {(0, 128, 255), (128, 192, 255)}


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_surface_svg_preserves_clipped_curve_across_encodings(
    tmp_path, monkeypatch: pytest.MonkeyPatch, encoding: str,
):
    real_analyze = native_svg_adapter.analyze_native_svg
    native_outcomes = []

    def record_native(*args, **kwargs):
        outcome = real_analyze(*args, **kwargs)
        native_outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(native_svg_adapter, "analyze_native_svg", record_native)
    source = tmp_path / "clipped-circle.svg"
    source.write_text(
        f'''<?xml version="1.0" encoding="{encoding}"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <defs><clipPath id="clip"><rect x="2" y="2" width="16" height="16"/></clipPath></defs>
          <rect width="20" height="20" fill="#0080ff"/>
          <g transform="translate(0 2)" clip-path="url(#clip)" fill="none" stroke="#ffffff" stroke-width="2">
            <circle cx="10" cy="10" r="3"/>
          </g>
        </svg>''', encoding=encoding,
    )
    result = render_surface_artwork(
        source_path=source, footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE), output_dir=tmp_path,
    )
    assert len(native_outcomes) == 1
    if encoding == "utf-8":
        assert isinstance(native_outcomes[0], native_svg_adapter.NativeSvgGeometry)
    else:
        assert native_outcomes[0] == native_svg_adapter.NativeSvgFallback(
            reason_code="unsupported_xml_encoding", native_version="0.3.4",
        )
    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale, _bounds = processor._parse_svg(str(result.output_path), 20.0)
    white_area = sum(item["poly"].area for item in shapes if item["color"] == (255, 255, 255)) * scale**2
    assert white_area == pytest.approx(12.0 * 3.14159265, abs=0.5)


def test_render_surface_artwork_masks_to_surface_bounds(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 40), (255, 0, 0)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    assert result.width_px == 80
    assert result.height_px == 40
    assert result.target_width_mm == 20.0
    assert result.output_path.exists()
    rendered = Image.open(result.output_path).convert("RGBA")
    assert rendered.getpixel((40, 20)) == (255, 0, 0, 255)


def test_render_surface_artwork_edge_to_edge_preserves_source_aspect_ratio(tmp_path):
    source = tmp_path / "wide-source.png"
    image = Image.new("RGB", (80, 40), (0, 192, 0))
    for x in range(16):
        for y in range(40):
            image.putpixel((x, y), (255, 0, 0))
            image.putpixel((79 - x, y), (0, 0, 255))
    image.save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    rendered = Image.open(result.output_path).convert("RGBA")
    assert rendered.getpixel((4, 40)) == (0, 192, 0, 255)
    assert rendered.getpixel((75, 40)) == (0, 192, 0, 255)


def test_render_surface_artwork_uses_surface_space_counter_clockwise_rotation(tmp_path):
    source = tmp_path / "asymmetric-rotation.png"
    image = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
    for x in range(60, 80):
        for y in range(0, 10):
            image.putpixel((x, y), (255, 0, 0, 255))
    for x in range(0, 20):
        for y in range(30, 40):
            image.putpixel((x, y), (0, 0, 255, 255))
    image.save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(
            mode=EdgeMode.EDGE_TO_EDGE,
            rotation_deg=90.0,
        ),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    rendered = Image.open(result.output_path).convert("RGBA")
    red_top_left = sum(
        1
        for pixel in rendered.crop((0, 0, 40, 40)).getdata()
        if pixel[0] > 200 and pixel[1] < 40 and pixel[3] > 0
    )
    blue_bottom_right = sum(
        1
        for pixel in rendered.crop((40, 40, 80, 80)).getdata()
        if pixel[2] > 200 and pixel[0] < 40 and pixel[3] > 0
    )
    assert red_top_left > 0
    assert blue_bottom_right > 0


def test_render_surface_artwork_inset_contains_portrait_bitmap_with_four_side_clearance(
    tmp_path,
):
    source = tmp_path / "portrait.png"
    Image.new("RGB", (40, 80), (255, 0, 0)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.INSET, inset_mm=2.0),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    rendered = Image.open(result.output_path).convert("RGBA")
    assert rendered.getchannel("A").getbbox() == (24, 8, 56, 72)


def test_render_surface_artwork_inset_contains_rotated_portrait_bitmap(
    tmp_path,
):
    source = tmp_path / "rotated-portrait.png"
    Image.new("RGB", (40, 80), (255, 0, 0)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(
            mode=EdgeMode.INSET,
            inset_mm=2.0,
            rotation_deg=17.0,
        ),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    alpha_bounds = Image.open(result.output_path).convert("RGBA").getchannel("A").getbbox()
    assert alpha_bounds is not None
    assert alpha_bounds[0] >= 8
    assert alpha_bounds[1] >= 8
    assert alpha_bounds[2] <= 72
    assert alpha_bounds[3] <= 72


def test_render_surface_artwork_edge_to_edge_rotated_bitmap_covers_corners(
    tmp_path,
):
    source = tmp_path / "rotated-cover.png"
    Image.new("RGB", (40, 40), (255, 0, 0)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(
            mode=EdgeMode.EDGE_TO_EDGE,
            rotation_deg=17.0,
        ),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    rendered = Image.open(result.output_path).convert("RGBA")
    for point in ((0, 0), (79, 0), (0, 79), (79, 79)):
        assert rendered.getpixel(point)[3] > 0


def test_render_surface_artwork_keeps_footprint_hole_transparent(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (40, 40), (0, 128, 255)).save(source)

    result = render_surface_artwork(
        source_path=source,
        footprint=_footprint_with_hole(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=2,
        output_dir=tmp_path,
    )

    rendered = Image.open(result.output_path).convert("RGBA")
    assert rendered.getpixel((20, 20))[3] == 0
    assert rendered.getpixel((4, 4)) == (0, 128, 255, 255)


def test_render_surface_artwork_preserves_svg_and_clips_holes_as_vector_geometry(
    tmp_path,
):
    source = tmp_path / "source.svg"
    source.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg"
             width="40" height="20" viewBox="0 0 40 20">
          <path d="M0 0H40V20H0Z" fill="#0080ff"/>
        </svg>
        """,
        encoding="utf-8",
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_footprint_with_hole(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=2,
        output_dir=tmp_path,
    )

    assert result.output_path.suffix == ".svg"
    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor.expand_stroke_to_fill = False
    shapes, scale_factor, _bounds = processor._parse_svg(
        str(result.output_path),
        target_width_mm=20.0,
    )
    total_area_mm2 = sum(shape["poly"].area for shape in shapes) * scale_factor**2
    assert total_area_mm2 == pytest.approx(384.0, abs=0.1)


def test_render_surface_artwork_filters_generated_gap_filler_paths(
    tmp_path,
):
    source = tmp_path / "gap-filler.svg"
    source.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <path d="M2 2H8V8H2Z" fill="#ff0000"/>
          <path class="qq3d-gap-filler"
                d="M2 10H18"
                fill="none"
                stroke="#0000ff"
                stroke-width="2"
                stroke-linejoin="round"
                stroke-linecap="round"
                vector-effect="non-scaling-stroke"/>
        </svg>
        """,
        encoding="utf-8",
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.EDGE_TO_EDGE),
        pixels_per_mm=2,
        output_dir=tmp_path,
    )

    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale_factor, _bounds = processor._parse_svg(
        str(result.output_path),
        target_width_mm=20.0,
    )

    assert [shape["color"] for shape in shapes] == [(255, 0, 0)]
    red_area_mm2 = sum(shape["poly"].area for shape in shapes) * scale_factor**2
    assert red_area_mm2 == pytest.approx(36.0, abs=0.1)


def test_render_surface_artwork_inset_contains_portrait_svg_with_four_side_clearance(
    tmp_path,
):
    source = tmp_path / "portrait.svg"
    source.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20">
          <path d="M0 0H10V20H0Z" fill="#ff0000"/>
        </svg>
        """,
        encoding="utf-8",
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(mode=EdgeMode.INSET, inset_mm=2.0),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale_factor, _bounds = processor._parse_svg(
        str(result.output_path),
        target_width_mm=20.0,
    )
    visible_bounds = unary_union([shape["poly"] for shape in shapes]).bounds
    assert tuple(value * scale_factor for value in visible_bounds) == pytest.approx(
        (6.0, 2.0, 14.0, 18.0),
        abs=0.01,
    )


def test_render_surface_artwork_inset_contains_rotated_svg_bounding_box(
    tmp_path,
):
    source = tmp_path / "rotated-square.svg"
    source.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <path d="M0 0H20V20H0Z" fill="#ff0000"/>
        </svg>
        """,
        encoding="utf-8",
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(
            mode=EdgeMode.INSET,
            inset_mm=2.0,
            rotation_deg=17.0,
        ),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale_factor, _bounds = processor._parse_svg(
        str(result.output_path),
        target_width_mm=20.0,
    )
    visible_bounds = unary_union([shape["poly"] for shape in shapes]).bounds
    assert tuple(value * scale_factor for value in visible_bounds) == pytest.approx(
        (2.0, 2.0, 18.0, 18.0),
        abs=0.01,
    )


def test_render_surface_artwork_edge_to_edge_covers_rotated_surface_corners(
    tmp_path,
):
    source = tmp_path / "rotated-cover-square.svg"
    source.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <path d="M0 0H20V20H0Z" fill="#ff0000"/>
        </svg>
        """,
        encoding="utf-8",
    )

    result = render_surface_artwork(
        source_path=source,
        footprint=_square_footprint(),
        placement=SurfacePlacement(
            mode=EdgeMode.EDGE_TO_EDGE,
            rotation_deg=17.0,
        ),
        pixels_per_mm=4,
        output_dir=tmp_path,
    )

    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    processor._parse_expand_stroke_to_fill = False
    shapes, scale_factor, _bounds = processor._parse_svg(
        str(result.output_path),
        target_width_mm=20.0,
    )
    visible_area_mm2 = unary_union(
        [shape["poly"] for shape in shapes]
    ).area * scale_factor**2
    assert visible_area_mm2 == pytest.approx(400.0, abs=0.01)


def _footprint() -> SurfaceFootprint:
    return SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 0.0),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0), (-10.0, -5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )


def _footprint_with_hole() -> SurfaceFootprint:
    footprint = _footprint()
    return SurfaceFootprint(
        frame=footprint.frame,
        outer=((-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0), (-10.0, -10.0)),
        holes=(((-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0), (-2.0, -2.0)),),
        bounds_min=(-10.0, -10.0),
        bounds_max=(10.0, 10.0),
        bounds_width_mm=20.0,
        bounds_height_mm=20.0,
        area_mm2=384.0,
        hole_count=1,
    )


def _square_footprint() -> SurfaceFootprint:
    footprint = _footprint()
    return SurfaceFootprint(
        frame=footprint.frame,
        outer=((-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0), (-10.0, -10.0)),
        holes=(),
        bounds_min=(-10.0, -10.0),
        bounds_max=(10.0, 10.0),
        bounds_width_mm=20.0,
        bounds_height_mm=20.0,
        area_mm2=400.0,
        hole_count=0,
    )
