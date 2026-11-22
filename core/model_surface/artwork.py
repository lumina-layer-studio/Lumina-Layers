from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
import tempfile
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid

from config import MIN_PRINTABLE_ALPHA, TEMP_DIR
from core.model_surface.types import (
    MODEL_SURFACE_ARTWORK_NO_OVERLAP,
    EdgeMode,
    ModelSurfaceError,
    SurfaceFootprint,
)
from core.vector_engine import parse_svg_geometry


_SVG_NAMESPACE = "http://www.w3.org/2000/svg"


@dataclass(frozen=True)
class SurfacePlacement:
    """Artwork placement parameters in selected-surface coordinates.

    选中表面坐标系中的画面摆放参数。
    """

    mode: EdgeMode = EdgeMode.EDGE_TO_EDGE
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    scale: float = 1.0
    rotation_deg: float = 0.0
    inset_mm: float = 0.0


@dataclass(frozen=True)
class RenderedSurfaceArtwork:
    """Rendered masked artwork for model-surface preview/generation.

    用于模型覆面预览和生成的已渲染遮罩画面。
    """

    output_path: Path
    width_px: int
    height_px: int
    target_width_mm: float
    target_height_mm: float


def render_surface_artwork(
    *,
    source_path: str | Path,
    footprint: SurfaceFootprint,
    placement: SurfacePlacement,
    pixels_per_mm: int = 6,
    output_dir: str | Path = TEMP_DIR,
) -> RenderedSurfaceArtwork:
    """Render placed artwork into the selected surface bounds and mask holes.

    将画面按摆放参数渲染到选中表面范围内，并遮掉孔洞区域。

    Args:
        source_path: Source bitmap or SVG path.
            源位图或 SVG 路径。
        footprint: Selected surface footprint.
            选中表面的二维轮廓。
        placement: Scale, offset, rotation, and inset parameters.
            缩放、位移、旋转和内缩参数。
        pixels_per_mm: Output raster density.
            输出栅格密度。
        output_dir: Directory for the temporary rendered artwork.
            临时渲染画面的输出目录。

    Returns:
        Rendered artwork path and physical/pixel dimensions. SVG input stays
        vector-native; bitmap input produces PNG.
        渲染画面路径及物理/像素尺寸。SVG 输入保持原生矢量，
        位图输入输出 PNG。
    """

    if pixels_per_mm <= 0:
        raise ModelSurfaceError("pixels_per_mm must be positive.")
    if placement.scale <= 0.0:
        raise ModelSurfaceError("Surface artwork scale must be positive.")

    target_width_mm = float(footprint.bounds_width_mm)
    target_height_mm = float(footprint.bounds_height_mm)
    if target_width_mm <= 0.0 or target_height_mm <= 0.0:
        raise ModelSurfaceError("Surface footprint bounds are invalid.")

    width_px = max(1, round(target_width_mm * pixels_per_mm))
    height_px = max(1, round(target_height_mm * pixels_per_mm))
    source_file = Path(source_path)
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    if source_file.suffix.lower() == ".svg":
        output_path = _render_vector_surface_artwork(
            source_path=source_file,
            footprint=footprint,
            placement=placement,
            output_dir=output_root,
        )
        return RenderedSurfaceArtwork(
            output_path=output_path,
            width_px=width_px,
            height_px=height_px,
            target_width_mm=target_width_mm,
            target_height_mm=target_height_mm,
        )

    source = _load_source_rgba(source_file)
    canvas = _place_source_on_canvas(
        source=source,
        width_px=width_px,
        height_px=height_px,
        pixels_per_mm=float(pixels_per_mm),
        placement=placement,
    )

    mask = _footprint_mask(footprint, width_px, height_px)
    alpha = Image.composite(canvas.getchannel("A"), Image.new("L", canvas.size, 0), mask)
    if alpha.getextrema()[1] < MIN_PRINTABLE_ALPHA:
        raise ModelSurfaceError(MODEL_SURFACE_ARTWORK_NO_OVERLAP)
    canvas.putalpha(alpha)

    fd, output_path = tempfile.mkstemp(suffix=".png", dir=str(output_root))
    os.close(fd)
    canvas.save(output_path)
    return RenderedSurfaceArtwork(
        output_path=Path(output_path),
        width_px=width_px,
        height_px=height_px,
        target_width_mm=target_width_mm,
        target_height_mm=target_height_mm,
    )


def _load_source_rgba(source_path: Path) -> Image.Image:
    return Image.open(source_path).convert("RGBA")


def _render_vector_surface_artwork(
    *,
    source_path: Path,
    footprint: SurfaceFootprint,
    placement: SurfacePlacement,
    output_dir: Path,
) -> Path:
    shapes, _scale_factor, bounds = parse_svg_geometry(
        source_path,
        target_width_mm=float(footprint.bounds_width_mm),
    )
    source_width = float(bounds[2])
    source_height = float(bounds[3])
    if source_width <= 0.0 or source_height <= 0.0:
        raise ModelSurfaceError("Surface artwork SVG has invalid bounds.")

    inset_mm = (
        max(0.0, float(placement.inset_mm))
        if placement.mode == EdgeMode.INSET
        else 0.0
    )
    available_width = max(1e-9, float(footprint.bounds_width_mm) - inset_mm * 2.0)
    available_height = max(1e-9, float(footprint.bounds_height_mm) - inset_mm * 2.0)
    artwork_scale = _artwork_scale(
        source_width=source_width,
        source_height=source_height,
        available_width=available_width,
        available_height=available_height,
        placement=placement,
    )

    footprint_geometry = _footprint_geometry(footprint)
    transformed_shapes: list[tuple[BaseGeometry, tuple[int, int, int]]] = []
    for item in shapes:
        geometry = item.get("poly")
        if geometry is None or geometry.is_empty:
            continue
        geometry = affinity.translate(
            geometry,
            xoff=-source_width / 2.0,
            yoff=-source_height / 2.0,
        )
        geometry = affinity.scale(
            geometry,
            xfact=artwork_scale,
            yfact=artwork_scale,
            origin=(0.0, 0.0),
        )
        if placement.rotation_deg:
            # SVG coordinates are Y-down, while Shapely rotation is Y-up.
            geometry = affinity.rotate(
                geometry,
                -float(placement.rotation_deg),
                origin=(0.0, 0.0),
            )
        geometry = affinity.translate(
            geometry,
            xoff=float(footprint.bounds_width_mm) / 2.0 + float(placement.offset_x_mm),
            yoff=float(footprint.bounds_height_mm) / 2.0 - float(placement.offset_y_mm),
        )
        clipped = _extract_polygonal_geometry(
            make_valid(geometry.intersection(footprint_geometry))
        )
        if clipped is None or clipped.is_empty:
            continue
        color = tuple(max(0, min(255, int(channel))) for channel in item["color"][:3])
        transformed_shapes.append((clipped, color))

    if not transformed_shapes:
        raise ModelSurfaceError(MODEL_SURFACE_ARTWORK_NO_OVERLAP)

    fd, output_path = tempfile.mkstemp(suffix=".svg", dir=str(output_dir))
    os.close(fd)
    _write_flattened_svg(
        output_path=Path(output_path),
        width_mm=float(footprint.bounds_width_mm),
        height_mm=float(footprint.bounds_height_mm),
        shapes=transformed_shapes,
    )
    return Path(output_path)


def _footprint_geometry(
    footprint: SurfaceFootprint,
) -> Polygon | MultiPolygon:
    min_x, _min_y = footprint.bounds_min
    _max_x, max_y = footprint.bounds_max

    def to_svg_ring(ring):
        return [
            (float(x_coord) - float(min_x), float(max_y) - float(y_coord))
            for x_coord, y_coord in ring
        ]

    geometry = Polygon(
        to_svg_ring(footprint.outer),
        [to_svg_ring(hole) for hole in footprint.holes],
    )
    geometry = _extract_polygonal_geometry(make_valid(geometry))
    if geometry is None or geometry.is_empty:
        raise ModelSurfaceError("Surface footprint geometry is invalid.")
    return geometry


def _extract_polygonal_geometry(
    geometry: BaseGeometry | None,
) -> Polygon | MultiPolygon | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    polygons = [
        part
        for part in getattr(geometry, "geoms", ())
        if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty
    ]
    if not polygons:
        return None
    flattened = []
    for part in polygons:
        if isinstance(part, Polygon):
            flattened.append(part)
        else:
            flattened.extend(poly for poly in part.geoms if not poly.is_empty)
    if not flattened:
        return None
    return flattened[0] if len(flattened) == 1 else MultiPolygon(flattened)


def _write_flattened_svg(
    *,
    output_path: Path,
    width_mm: float,
    height_mm: float,
    shapes: list[tuple[BaseGeometry, tuple[int, int, int]]],
) -> None:
    ET.register_namespace("", _SVG_NAMESPACE)
    root = ET.Element(
        f"{{{_SVG_NAMESPACE}}}svg",
        {
            "width": f"{_format_svg_number(width_mm)}mm",
            "height": f"{_format_svg_number(height_mm)}mm",
            "viewBox": (
                f"0 0 {_format_svg_number(width_mm)} "
                f"{_format_svg_number(height_mm)}"
            ),
        },
    )
    for geometry, color in shapes:
        path_data = _geometry_to_svg_path_data(geometry)
        if not path_data:
            continue
        ET.SubElement(
            root,
            f"{{{_SVG_NAMESPACE}}}path",
            {
                "d": path_data,
                "fill": f"rgb({color[0]},{color[1]},{color[2]})",
                "fill-rule": "evenodd",
            },
        )
    ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)


def _geometry_to_svg_path_data(geometry: BaseGeometry) -> str:
    polygons = (
        [geometry]
        if isinstance(geometry, Polygon)
        else list(getattr(geometry, "geoms", ()))
    )
    commands: list[str] = []
    for polygon in polygons:
        if not isinstance(polygon, Polygon) or polygon.is_empty:
            continue
        for ring in (polygon.exterior, *polygon.interiors):
            coordinates = list(ring.coords)
            if len(coordinates) < 4:
                continue
            points = coordinates[:-1]
            first_x, first_y = points[0]
            commands.append(
                f"M{_format_svg_number(first_x)} {_format_svg_number(first_y)}"
            )
            commands.extend(
                f"L{_format_svg_number(x_coord)} {_format_svg_number(y_coord)}"
                for x_coord, y_coord in points[1:]
            )
            commands.append("Z")
    return "".join(commands)


def _format_svg_number(value: float) -> str:
    formatted = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if formatted in {"", "-0"} else formatted


def _place_source_on_canvas(
    *,
    source: Image.Image,
    width_px: int,
    height_px: int,
    pixels_per_mm: float,
    placement: SurfacePlacement,
) -> Image.Image:
    canvas = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    inset_px = (
        max(0, round(placement.inset_mm * pixels_per_mm))
        if placement.mode == EdgeMode.INSET
        else 0
    )
    available_width = max(1, width_px - inset_px * 2)
    available_height = max(1, height_px - inset_px * 2)
    target_size = _placed_artwork_size(
        source_width=source.width,
        source_height=source.height,
        available_width=available_width,
        available_height=available_height,
        placement=placement,
    )

    artwork = source.resize(target_size, Image.Resampling.LANCZOS)
    if placement.rotation_deg:
        artwork = artwork.rotate(
            placement.rotation_deg,
            resample=Image.Resampling.BICUBIC,
            expand=True,
        )

    x_px = round((width_px - artwork.width) / 2.0 + placement.offset_x_mm * pixels_per_mm)
    y_px = round((height_px - artwork.height) / 2.0 - placement.offset_y_mm * pixels_per_mm)
    _alpha_composite_clipped(canvas, artwork, x_px, y_px)
    return canvas


def _placed_artwork_size(
    *,
    source_width: int,
    source_height: int,
    available_width: int,
    available_height: int,
    placement: SurfacePlacement,
) -> tuple[int, int]:
    artwork_scale = _artwork_scale(
        source_width=float(source_width),
        source_height=float(source_height),
        available_width=float(available_width),
        available_height=float(available_height),
        placement=placement,
    )
    round_size = math.floor if placement.mode == EdgeMode.INSET else math.ceil
    return (
        max(1, round_size(float(source_width) * artwork_scale)),
        max(1, round_size(float(source_height) * artwork_scale)),
    )


def _artwork_scale(
    *,
    source_width: float,
    source_height: float,
    available_width: float,
    available_height: float,
    placement: SurfacePlacement,
) -> float:
    if source_width <= 0.0 or source_height <= 0.0:
        raise ModelSurfaceError("Surface artwork source has invalid size.")
    rotation_deg = (
        float(placement.rotation_deg)
        if math.isfinite(float(placement.rotation_deg))
        else 0.0
    )
    rotation_radians = math.radians(rotation_deg)
    cosine = abs(math.cos(rotation_radians))
    sine = abs(math.sin(rotation_radians))
    if placement.mode == EdgeMode.INSET:
        rotated_source_width = source_width * cosine + source_height * sine
        rotated_source_height = source_width * sine + source_height * cosine
        fit_ratio = min(
            available_width / rotated_source_width,
            available_height / rotated_source_height,
        )
    else:
        required_local_width = available_width * cosine + available_height * sine
        required_local_height = available_width * sine + available_height * cosine
        fit_ratio = max(
            required_local_width / source_width,
            required_local_height / source_height,
        )
    return fit_ratio * float(placement.scale)


def _alpha_composite_clipped(
    canvas: Image.Image,
    overlay: Image.Image,
    x_px: int,
    y_px: int,
) -> None:
    src_left = max(0, -x_px)
    src_top = max(0, -y_px)
    dst_left = max(0, x_px)
    dst_top = max(0, y_px)
    width = min(overlay.width - src_left, canvas.width - dst_left)
    height = min(overlay.height - src_top, canvas.height - dst_top)
    if width <= 0 or height <= 0:
        return
    cropped = overlay.crop((src_left, src_top, src_left + width, src_top + height))
    canvas.alpha_composite(cropped, (dst_left, dst_top))


def _footprint_mask(footprint: SurfaceFootprint, width_px: int, height_px: int) -> Image.Image:
    min_x, min_y = footprint.bounds_min
    max_x, max_y = footprint.bounds_max
    scale_x = width_px / max(max_x - min_x, 1e-9)
    scale_y = height_px / max(max_y - min_y, 1e-9)

    def to_px(point: tuple[float, float]) -> tuple[int, int]:
        x_coord, y_coord = point
        return (
            round((x_coord - min_x) * scale_x),
            round((max_y - y_coord) * scale_y),
        )

    mask = Image.new("L", (width_px, height_px), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([to_px(point) for point in footprint.outer], fill=255)
    for hole in footprint.holes:
        draw.polygon([to_px(point) for point in hole], fill=0)
    return mask
