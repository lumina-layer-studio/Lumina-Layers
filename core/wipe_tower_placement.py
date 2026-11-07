"""Geometry-only wipe-tower placement for generated slicer projects.

生成切片工程时使用的纯几何擦料塔摆放逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Callable, Iterable, Sequence


Point2D = tuple[float, float]
Polygon2D = tuple[Point2D, ...]

_EPSILON = 1e-7
_EDGE_CLEARANCE_MM = 2.0
_PREFERRED_EDGE_CLEARANCE_MM = 4.0
_MIN_LONG_STRIP_MM = 200.0
_PREFERRED_VERTICAL_TOWER_WIDTH_MM = 30.0
WIPE_TOWER_MANUAL_WARNING_CODE = "wipe_tower_manual_adjustment_required"


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle in millimetres. / 以毫米表示的轴对齐矩形。"""

    left: float
    bottom: float
    right: float
    top: float

    def __post_init__(self) -> None:
        if self.right < self.left or self.top < self.bottom:
            raise ValueError("rectangle bounds must be ordered")

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.top - self.bottom

    @property
    def center(self) -> Point2D:
        return ((self.left + self.right) / 2.0, (self.bottom + self.top) / 2.0)

    def translated(self, dx: float, dy: float) -> "Rect":
        return Rect(self.left + dx, self.bottom + dy, self.right + dx, self.top + dy)

    def expanded(self, margin: float) -> "Rect":
        margin = max(0.0, float(margin))
        return Rect(
            self.left - margin,
            self.bottom - margin,
            self.right + margin,
            self.top + margin,
        )

    def intersection_area(self, other: "Rect") -> float:
        width = max(0.0, min(self.right, other.right) - max(self.left, other.left))
        height = max(0.0, min(self.top, other.top) - max(self.bottom, other.bottom))
        return width * height

    def contains_point(self, point: Point2D) -> bool:
        x, y = point
        return (
            self.left - _EPSILON <= x <= self.right + _EPSILON
            and self.bottom - _EPSILON <= y <= self.top + _EPSILON
        )

    def sample_points(self) -> tuple[Point2D, ...]:
        center_x, center_y = self.center
        return (
            (self.left, self.bottom),
            (self.right, self.bottom),
            (self.right, self.top),
            (self.left, self.top),
            (center_x, self.bottom),
            (self.right, center_y),
            (center_x, self.top),
            (self.left, center_y),
            (center_x, center_y),
        )


@dataclass(frozen=True)
class WipeTowerPlacementRequest:
    """Inputs required to solve one model-and-tower layout.

    求解单个模型与擦料塔布局所需的输入。
    """

    printable_area: Polygon2D
    bed_exclusions: tuple[Polygon2D, ...]
    extruder_printable_areas: tuple[Polygon2D, ...]
    model_bounds: Rect
    model_height: float
    model_brim: float
    material_count: int
    layer_height: float
    nozzle_diameter: float
    purge_volume: float
    tower_x: float
    tower_y: float
    tower_width: float
    tower_rotation: float
    tower_brim: float
    tower_infill_spacing_ratio: float = 1.0
    extruder_count: int = 1
    filament_change_volume: float = 0.0
    model_tower_clearance: float = 8.0
    edge_clearance: float = _EDGE_CLEARANCE_MM
    preferred_edge_clearance: float = _PREFERRED_EDGE_CLEARANCE_MM
    preferred_top_edge_clearance: float = 0.0
    prefer_vertical_strip: bool = False
    model_translation_locked: bool = False
    minimum_tower_footprint_width: float = 0.0
    minimum_tower_depth: float = 0.0
    tower_rib_width: float = 0.0
    tower_extra_rib_length: float = 0.0
    tower_square_rib_body: bool = False
    tower_preview_x_guard_enabled: bool = False
    tower_preview_x_guard_margin: float = 0.0
    cyclic_toolchanges: bool = False
    tower_wall_types: tuple[str, ...] = ()
    reserve_model_brim_at_bed_edge: bool = True
    nozzle_change_volume: float = 0.0
    separate_material_bands: bool = False


@dataclass(frozen=True)
class WipeTowerPlacementResult:
    """Solved build transform, tower settings, and safety state.

    已求解的模型变换、擦料塔参数与安全状态。
    """

    model_translation: Point2D
    model_bounds: Rect
    model_outer_bounds: Rect
    tower_x: float
    tower_y: float
    tower_width: float
    tower_depth: float
    tower_rotation: float
    tower_bounds: Rect
    tower_outer_bounds: Rect
    adapted: bool
    requires_manual_adjustment: bool
    warning_code: str | None
    reason: str
    tower_wall_type: str | None = None
    bed_bounds: Rect | None = None
    model_brim_requires_review: bool = False

    @property
    def placement_available(self) -> bool:
        """Whether body placement is usable, possibly pending native brim review.

        实体布局是否可用；底边仍可保持待原生切片确认。
        """
        return not self.requires_manual_adjustment or self.model_brim_requires_review


@dataclass(frozen=True)
class _ScoredPlacement:
    """One safe placement plus deterministic selection ranks."""

    result: WipeTowerPlacementResult
    clearance_rank: int
    orientation_index: int
    width_rank: int
    movement: float
    side_rank: int
    offset_rank: int

    @property
    def within_orientation_score(self) -> tuple[float, ...]:
        return (
            float(self.width_rank),
            float(self.clearance_rank),
            self.movement,
            float(self.side_rank),
            float(self.offset_rank),
        )

    def overall_score(self, *, prefer_vertical: bool) -> tuple[float, ...]:
        vertical_preference_penalty = (
            0.0
            if not prefer_vertical or self.orientation_index == 1
            else 1.0
        )
        footprint_area = (
            self.result.tower_bounds.width * self.result.tower_bounds.height
        )
        return (
            vertical_preference_penalty,
            self.movement,
            footprint_area,
            float(self.width_rank),
            float(self.clearance_rank),
            float(self.orientation_index),
            float(self.side_rank),
            float(self.offset_rank),
        )


def _minimum_depth_for_height(model_height: float) -> float:
    points = ((5.0, 5.0), (100.0, 20.0), (250.0, 40.0), (350.0, 60.0))
    height = max(0.0, float(model_height))
    if height <= points[0][0]:
        return points[0][1]
    for (height_a, depth_a), (height_b, depth_b) in zip(points, points[1:]):
        if height <= height_b:
            ratio = (height - height_a) / (height_b - height_a)
            return depth_a + ratio * (depth_b - depth_a)
    return points[-1][1]


def estimate_wipe_tower_depth(
    *,
    width: float,
    model_height: float,
    material_count: int,
    layer_height: float,
    nozzle_diameter: float,
    purge_volume: float,
    tower_infill_spacing_ratio: float = 1.0,
    extruder_count: int = 1,
    filament_change_volume: float = 0.0,
    cyclic_toolchanges: bool = False,
) -> float:
    """Estimate peak tower depth from native transition-volume facts.

    按原生换料体积和循环换料规则估算擦料塔深度，用于预留占地；
    不改变冲刷量，也不会关闭擦料塔。
    """

    width = max(2.0, float(width))
    layer_height = max(0.01, float(layer_height))
    tower_line_width = max(0.1, float(nozzle_diameter)) * 1.25
    material_count = max(1, int(material_count))
    extruder_count = max(1, int(extruder_count))
    transition_count = (
        material_count if extruder_count == 2 or cyclic_toolchanges else material_count - 1
    )
    if cyclic_toolchanges and material_count == 1:
        transition_count = 0
    purge_volume = max(0.0, float(purge_volume))
    spacing_ratio = max(0.01, float(tower_infill_spacing_ratio))
    usable_line_length = max(tower_line_width, width - 2.0 * tower_line_width)
    transition_count = max(0, transition_count)
    purge_line_length = purge_volume / (layer_height * tower_line_width)
    lines_per_transition = (
        math.ceil(purge_line_length / usable_line_length)
        if purge_line_length > _EPSILON
        else 0
    )
    line_count = lines_per_transition * transition_count
    if extruder_count == 2:
        change_volume = max(0.0, float(filament_change_volume)) * (
            material_count // 2
        )
        change_line_length = change_volume / (layer_height * tower_line_width)
        if change_line_length > _EPSILON:
            line_count += math.ceil(change_line_length / usable_line_length)

    # Native Bambu/Orca-style towers reserve two structural paths around each
    # material-transition block.  The generated path depth is therefore
    # discretely larger than the continuous volume/area preview estimate,
    # especially for a narrow (vertical) strip.
    structural_lines = 2 * transition_count if line_count else 0
    purge_depth = (line_count + structural_lines) * tower_line_width * spacing_ratio
    if line_count:
        purge_depth += tower_line_width
    return max(_minimum_depth_for_height(model_height), purge_depth)


def _estimate_request_tower_depth(
    request: WipeTowerPlacementRequest,
    width: float,
) -> float:
    return max(
        max(0.0, float(request.minimum_tower_depth)),
        estimate_wipe_tower_depth(
            width=width,
            model_height=request.model_height,
            material_count=request.material_count,
            layer_height=request.layer_height,
            nozzle_diameter=request.nozzle_diameter,
            # A same-head nozzle exchange can ram the old filament and prime
            # the new one during the same visit.
            purge_volume=request.purge_volume + request.nozzle_change_volume,
            tower_infill_spacing_ratio=request.tower_infill_spacing_ratio,
            extruder_count=request.extruder_count,
            filament_change_volume=request.filament_change_volume,
            # Rib towers reserve a separate band for each material family.
            # The bands can reach their peak on different layers: a per-layer
            # count of N-1 switches need not cover their combined depth.
            cyclic_toolchanges=request.cyclic_toolchanges or (
                request.tower_square_rib_body and request.separate_material_bands
            ),
        ),
    )


def _tower_margin(
    request: WipeTowerPlacementRequest,
    width: float,
    edge_clearance: float,
) -> float:
    """Reserve brim and the native diagonal rib envelope around the body."""
    margin = max(0.0, request.tower_brim) + max(0.0, edge_clearance)
    if request.tower_rib_width <= 0.0:
        return margin
    # Bambu/Orca WipeTower::plan_tower / generate_rib_polygon: two diagonal
    # rectangles extend beyond the body by half their width and extra length.
    # Native rib length may also reach the height-dependent minimum diagonal.
    # Its unknown sliced body diagonal is >= width; this bounds that extension
    # without assuming our conservative purge-depth estimate is the real depth.
    half_rib_width = min(request.tower_rib_width, width / 2.0) / 2.0
    minimum_diagonal = (
        _minimum_depth_for_height(request.model_height) * math.sqrt(2.0)
    )
    extension = max(0.0, minimum_diagonal - width)
    extension = max(0.0, extension + request.tower_extra_rib_length) / 2.0
    return margin + half_rib_width + extension


def _tower_footprint_dimensions(
    request: WipeTowerPlacementRequest,
    width: float,
    depth: float,
) -> tuple[float, float]:
    """Return the physical envelope reserved around native tower paths."""

    if request.tower_square_rib_body:
        # Bambu-style WipeTower::plan_tower_new (also used by Orca for Bambu
        # printers) squares the purge area, ignoring the requested strip shape.
        # Our depth already includes infill spacing; do not apply it twice.
        line_width = max(0.1, request.nozzle_diameter) * 1.25
        width = math.ceil(math.sqrt(width * depth) / line_width) * line_width
        # The area estimate bounds the native squared body in both axes.
        # Its width can exceed the slicer's actual width; recalculating depth
        # at that larger width can then underestimate the real Y extent.
        # Keep the square envelope as well as the recalculated path depth.
        depth = max(width, _estimate_request_tower_depth(request, width))
    return (
        max(float(width), max(0.0, float(request.minimum_tower_footprint_width))),
        max(float(depth), max(0.0, float(request.minimum_tower_depth))),
    )


def _polygon_has_area(polygon: Sequence[Point2D]) -> bool:
    """Return whether a polygon encloses a non-zero two-dimensional area."""

    if len(polygon) < 3:
        return False
    area_twice = sum(
        point[0] * polygon[(index + 1) % len(polygon)][1]
        - polygon[(index + 1) % len(polygon)][0] * point[1]
        for index, point in enumerate(polygon)
    )
    return abs(area_twice) > _EPSILON


def _polygon_bounds(polygon: Sequence[Point2D]) -> Rect | None:
    if not _polygon_has_area(polygon):
        return None
    xs = [float(point[0]) for point in polygon]
    ys = [float(point[1]) for point in polygon]
    return Rect(min(xs), min(ys), max(xs), max(ys))


def _point_on_segment(point: Point2D, start: Point2D, end: Point2D) -> bool:
    px, py = point
    ax, ay = start
    bx, by = end
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > _EPSILON:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    if dot < -_EPSILON:
        return False
    length_sq = (bx - ax) ** 2 + (by - ay) ** 2
    return dot <= length_sq + _EPSILON


def _point_in_polygon(point: Point2D, polygon: Sequence[Point2D]) -> bool:
    if len(polygon) < 3:
        return False
    inside = False
    x, y = point
    previous = polygon[-1]
    for current in polygon:
        if _point_on_segment(point, previous, current):
            return True
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def _orientation(a: Point2D, b: Point2D, c: Point2D) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(a: Point2D, b: Point2D, c: Point2D, d: Point2D) -> bool:
    values = (_orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b))
    if values[0] * values[1] < -_EPSILON and values[2] * values[3] < -_EPSILON:
        return True
    return any(
        abs(value) <= _EPSILON and _point_on_segment(point, start, end)
        for value, point, start, end in (
            (values[0], c, a, b),
            (values[1], d, a, b),
            (values[2], a, c, d),
            (values[3], b, c, d),
        )
    )


def _rect_edges(rect: Rect) -> tuple[tuple[Point2D, Point2D], ...]:
    points = (
        (rect.left, rect.bottom),
        (rect.right, rect.bottom),
        (rect.right, rect.top),
        (rect.left, rect.top),
    )
    return tuple((points[index], points[(index + 1) % 4]) for index in range(4))


def _polygon_edges(polygon: Sequence[Point2D]) -> Iterable[tuple[Point2D, Point2D]]:
    for index, point in enumerate(polygon):
        yield point, polygon[(index + 1) % len(polygon)]


def _rect_inside_polygon(rect: Rect, polygon: Sequence[Point2D]) -> bool:
    if not _polygon_has_area(polygon) or not all(
        _point_in_polygon(point, polygon) for point in rect.sample_points()
    ):
        return False
    # A concave printable polygon can contain all four corners while an edge
    # crosses a notch. Midpoints above catch common notches; this intersection
    # guard covers the remaining cases without rejecting shared boundaries.
    for rect_start, rect_end in _rect_edges(rect):
        for poly_start, poly_end in _polygon_edges(polygon):
            if not _segments_cross(rect_start, rect_end, poly_start, poly_end):
                continue
            if (
                _point_on_segment(rect_start, poly_start, poly_end)
                or _point_on_segment(rect_end, poly_start, poly_end)
            ):
                continue
            return False
    return True


def _rect_intersects_polygon(rect: Rect, polygon: Sequence[Point2D]) -> bool:
    if not _polygon_has_area(polygon):
        return False
    if any(rect.contains_point(point) for point in polygon):
        return True
    if any(_point_in_polygon(point, polygon) for point in rect.sample_points()[:4]):
        return True
    return any(
        _segments_cross(rect_start, rect_end, poly_start, poly_end)
        for rect_start, rect_end in _rect_edges(rect)
        for poly_start, poly_end in _polygon_edges(polygon)
    )


def _effective_bed_bounds(request: WipeTowerPlacementRequest) -> Rect | None:
    bounds = _polygon_bounds(request.printable_area)
    if bounds is None:
        return None
    left, bottom, right, top = bounds.left, bounds.bottom, bounds.right, bounds.top
    for polygon in request.extruder_printable_areas:
        extruder_bounds = _polygon_bounds(polygon)
        if extruder_bounds is None:
            continue
        left = max(left, extruder_bounds.left)
        bottom = max(bottom, extruder_bounds.bottom)
        right = min(right, extruder_bounds.right)
        top = min(top, extruder_bounds.top)
    if right <= left or top <= bottom:
        return None
    return Rect(left, bottom, right, top)


def _rect_allowed(rect: Rect, request: WipeTowerPlacementRequest) -> bool:
    if not _rect_inside_polygon(rect, request.printable_area):
        return False
    for polygon in request.extruder_printable_areas:
        if len(polygon) >= 3 and not _rect_inside_polygon(rect, polygon):
            return False
    return not any(
        _rect_intersects_polygon(rect, polygon)
        for polygon in request.bed_exclusions
        if len(polygon) >= 3
    )


def _rotated_tower_bounds(
    x: float,
    y: float,
    width: float,
    depth: float,
    angle_degrees: float,
) -> Rect:
    angle = math.radians(angle_degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    points: list[Point2D] = []
    for local_x, local_y in (
        (0.0, 0.0),
        (width, 0.0),
        (width, depth),
        (0.0, depth),
    ):
        points.append(
            (
                x + local_x * cosine - local_y * sine,
                y + local_x * sine + local_y * cosine,
            )
        )
    return Rect(
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _anchor_for_bounds(
    bounds: Rect,
    width: float,
    depth: float,
    angle_degrees: float,
) -> Point2D:
    local_bounds = _rotated_tower_bounds(
        0.0,
        0.0,
        width,
        depth,
        angle_degrees,
    )
    return bounds.left - local_bounds.left, bounds.bottom - local_bounds.bottom


def _dedupe(values: Iterable[float]) -> list[float]:
    result: list[float] = []
    for value in values:
        if not any(abs(value - current) <= 1e-5 for current in result):
            result.append(float(value))
    return result


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if maximum < minimum:
        return minimum
    return min(maximum, max(minimum, value))


def _model_position_candidates(
    request: WipeTowerPlacementRequest,
    bed: Rect,
    model_margin: float,
    tower_outer: Rect,
) -> list[tuple[float, float]]:
    model = request.model_bounds
    min_x = bed.left + model_margin - model.left
    max_x = bed.right - model_margin - model.right
    min_y = bed.bottom + model_margin - model.bottom
    max_y = bed.top - model_margin - model.top
    centered_x = bed.center[0] - (model.left + model.right) / 2.0
    centered_y = bed.center[1] - (model.bottom + model.top) / 2.0

    x_values = [centered_x, min_x, max_x]
    y_values = [centered_y, min_y, max_y]
    x_values.extend(
        (
            tower_outer.left - model_margin - model.right,
            tower_outer.right + model_margin - model.left,
        )
    )
    y_values.extend(
        (
            tower_outer.bottom - model_margin - model.top,
            tower_outer.top + model_margin - model.bottom,
        )
    )
    for polygon in request.bed_exclusions:
        exclusion = _polygon_bounds(polygon)
        if exclusion is None:
            continue
        x_values.extend(
            (
                exclusion.left - model_margin - model.right,
                exclusion.right + model_margin - model.left,
            )
        )
        y_values.extend(
            (
                exclusion.bottom - model_margin - model.top,
                exclusion.top + model_margin - model.bottom,
            )
        )

    if max_x >= min_x:
        x_values.extend(min_x + (max_x - min_x) * fraction / 8.0 for fraction in range(1, 8))
    if max_y >= min_y:
        y_values.extend(min_y + (max_y - min_y) * fraction / 8.0 for fraction in range(1, 8))

    clamped_x = _dedupe(_clamp(value, min_x, max_x) for value in x_values)
    clamped_y = _dedupe(_clamp(value, min_y, max_y) for value in y_values)
    candidates = [(x, y) for x in clamped_x for y in clamped_y]
    candidates.sort(key=lambda item: (item[0] - centered_x) ** 2 + (item[1] - centered_y) ** 2)
    return candidates


def _tower_bounds_at_side(
    *,
    bed: Rect,
    footprint_width: float,
    footprint_height: float,
    margin: float,
    perpendicular_margin: float,
    side: str,
    along_offset: float,
) -> Rect:
    if side in {"top", "bottom"}:
        left = bed.center[0] - footprint_width / 2.0 + along_offset
        left = _clamp(left, bed.left + margin, bed.right - margin - footprint_width)
        bottom = (
            bed.top - perpendicular_margin - footprint_height
            if side == "top"
            else bed.bottom + perpendicular_margin
        )
    else:
        bottom = bed.center[1] - footprint_height / 2.0 + along_offset
        bottom = _clamp(bottom, bed.bottom + margin, bed.top - margin - footprint_height)
        left = (
            bed.right - perpendicular_margin - footprint_width
            if side == "right"
            else bed.left + perpendicular_margin
        )
    return Rect(left, bottom, left + footprint_width, bottom + footprint_height)


def _tower_along_offsets(
    request: WipeTowerPlacementRequest,
    bed: Rect,
    footprint_width: float,
    footprint_height: float,
    margin: float,
    side: str,
) -> list[float]:
    offsets = [0.0]
    for polygon in request.bed_exclusions:
        exclusion = _polygon_bounds(polygon)
        if exclusion is None:
            continue
        if side in {"top", "bottom"}:
            centered_left = bed.center[0] - footprint_width / 2.0
            offsets.extend(
                (
                    exclusion.left - margin - footprint_width - centered_left,
                    exclusion.right + margin - centered_left,
                )
            )
        else:
            centered_bottom = bed.center[1] - footprint_height / 2.0
            offsets.extend(
                (
                    exclusion.bottom - margin - footprint_height - centered_bottom,
                    exclusion.top + margin - centered_bottom,
                )
            )
    return _dedupe(offsets)


def _vertical_strip_dimensions(
    request: WipeTowerPlacementRequest,
    bed: Rect,
    tower_margin: float,
) -> list[tuple[float, float]]:
    """Return narrow-width candidates whose purge depth forms a vertical strip."""

    max_width = bed.width - 2.0 * tower_margin
    max_depth = bed.height - 2.0 * tower_margin
    if max_width < 2.0 or max_depth < 2.0:
        return []

    samples: list[tuple[float, float]] = []
    half_millimetre_steps = int(math.floor(max_width * 2.0))
    for step in range(4, half_millimetre_steps + 1):
        width = step / 2.0
        depth = _estimate_request_tower_depth(request, width)
        if depth <= max_depth + _EPSILON and depth > width + _EPSILON:
            samples.append((width, depth))

    if not samples:
        return []

    # A zero-degree 30 mm tower is the native slicer idiom for a vertical
    # prime strip. Search outwards in 0.5 mm increments so the first safe
    # result stays as close to that familiar value as the model allows.
    return sorted(
        samples,
        key=lambda item: (
            abs(item[0] - _PREFERRED_VERTICAL_TOWER_WIDTH_MM),
            item[0] > _PREFERRED_VERTICAL_TOWER_WIDTH_MM,
            item[0],
        ),
    )


def _width_can_still_win(
    best_rank: tuple[int, int] | None,
    *,
    width_rank: int,
    clearance_rank: int,
) -> bool:
    """Return whether a tower width can still beat the best safe layout so far.

    ``_ScoredPlacement.within_orientation_score`` compares width rank first and
    clearance rank second, and only the best layout per orientation is ever
    selected. A width whose ``(width_rank, clearance_rank)`` is already worse
    than a proven safe layout in the same orientation can therefore be skipped
    without changing the result.
    """

    return best_rank is None or (width_rank, clearance_rank) <= best_rank


def _build_result(
    request: WipeTowerPlacementRequest,
    *,
    translation: Point2D,
    tower_x: float,
    tower_y: float,
    tower_width: float,
    tower_depth: float,
    tower_rotation: float,
    adapted: bool,
    requires_manual_adjustment: bool,
    reason: str,
) -> WipeTowerPlacementResult:
    model_bounds = request.model_bounds.translated(*translation)
    edge_clearance = max(0.0, float(request.edge_clearance))
    model_outer = model_bounds.expanded(
        max(0.0, request.model_brim) + edge_clearance
    )
    footprint_width, footprint_depth = _tower_footprint_dimensions(
        request,
        tower_width,
        tower_depth,
    )
    tower_bounds = _rotated_tower_bounds(
        tower_x,
        tower_y,
        footprint_width,
        footprint_depth,
        tower_rotation,
    )
    tower_outer = tower_bounds.expanded(
        _tower_margin(request, footprint_width, edge_clearance)
    )
    return WipeTowerPlacementResult(
        model_translation=translation,
        model_bounds=model_bounds,
        model_outer_bounds=model_outer,
        tower_x=tower_x,
        tower_y=tower_y,
        tower_width=tower_width,
        tower_depth=tower_depth,
        tower_rotation=tower_rotation,
        tower_bounds=tower_bounds,
        tower_outer_bounds=tower_outer,
        adapted=adapted,
        requires_manual_adjustment=requires_manual_adjustment,
        warning_code=(
            WIPE_TOWER_MANUAL_WARNING_CODE
            if requires_manual_adjustment
            else None
        ),
        reason=reason,
        bed_bounds=_effective_bed_bounds(request),
    )


class _RectAllowanceCache:
    """Memoize ``_rect_allowed`` for the fixed request of one solve.

    The candidate search revisits the same model and tower rectangles many
    times, and the polygon containment test is the solver's hot path.
    """

    def __init__(self, request: WipeTowerPlacementRequest) -> None:
        self._request = request
        self._results: dict[Rect, bool] = {}

    def __call__(self, rect: Rect) -> bool:
        allowed = self._results.get(rect)
        if allowed is None:
            allowed = _rect_allowed(rect, self._request)
            self._results[rect] = allowed
        return allowed


def _layout_is_safe(
    result: WipeTowerPlacementResult,
    request: WipeTowerPlacementRequest,
    rect_allowed: Callable[[Rect], bool] | None = None,
) -> bool:
    if rect_allowed is None:
        rect_allowed = _RectAllowanceCache(request)
    edge_clearance = max(0.0, float(request.edge_clearance))
    bed = _effective_bed_bounds(request)
    preview_guard_enabled = bool(request.tower_preview_x_guard_enabled)
    preview_guard_margin = max(0.0, float(request.tower_preview_x_guard_margin))
    collision_expansion = max(
        0.0,
        float(request.model_tower_clearance) - 2.0 * edge_clearance,
    )
    model_bed_bounds = (
        result.model_outer_bounds if request.reserve_model_brim_at_bed_edge
        else result.model_bounds.expanded(edge_clearance)
    )
    # Run the cheap overlap test before the polygon containment tests; all
    # three checks are pure, so the order does not change the answer.
    return (
        (
            not preview_guard_enabled
            or bed is not None
            and result.tower_x >= preview_guard_margin - _EPSILON
            and result.tower_x + result.tower_width + preview_guard_margin
            <= bed.right + _EPSILON
        )
        and result.model_outer_bounds.intersection_area(
            result.tower_outer_bounds.expanded(
                collision_expansion
            )
        )
        <= _EPSILON
        and rect_allowed(model_bed_bounds)
        and rect_allowed(result.tower_outer_bounds)
    )


def _solve_tower_body_placement(
    request: WipeTowerPlacementRequest,
) -> WipeTowerPlacementResult:
    """Find an automatic horizontal/vertical tower layout for the current model.

    开启自动摆放时始终根据当前模型重新求解，而不是因为模板碰巧未碰撞就
    原样返回。求解只平移模型，绝不缩放模型或关闭擦料塔；无安全解时返回
    可导出的尽力布局及明确的手动调整标记。
    """

    bed = _effective_bed_bounds(request)
    edge_clearance = max(0.0, float(request.edge_clearance))
    original_depth = _estimate_request_tower_depth(
        request,
        request.tower_width,
    )

    if bed is not None and not request.model_translation_locked:
        centered_translation = (
            bed.center[0] - (request.model_bounds.left + request.model_bounds.right) / 2.0,
            bed.center[1] - (request.model_bounds.bottom + request.model_bounds.top) / 2.0,
        )
    else:
        centered_translation = (0.0, 0.0)

    original = _build_result(
        request,
        translation=centered_translation,
        tower_x=request.tower_x,
        tower_y=request.tower_y,
        tower_width=max(2.0, request.tower_width),
        tower_depth=original_depth,
        tower_rotation=request.tower_rotation,
        adapted=False,
        requires_manual_adjustment=False,
        reason="template_layout_safe",
    )
    rect_allowed = _RectAllowanceCache(request)
    original_is_safe = bed is not None and _layout_is_safe(original, request, rect_allowed)

    if (
        request.model_translation_locked
        and bed is not None
        and not rect_allowed(
            original.model_outer_bounds if request.reserve_model_brim_at_bed_edge
            else original.model_bounds.expanded(edge_clearance)
        )
    ):
        return _build_result(
            request,
            translation=(0.0, 0.0),
            tower_x=original.tower_x,
            tower_y=original.tower_y,
            tower_width=original.tower_width,
            tower_depth=original.tower_depth,
            tower_rotation=original.tower_rotation,
            adapted=True,
            requires_manual_adjustment=True,
            reason="no_safe_layout_without_scaling_or_disabling_tower",
        )

    # Snapmaker Orca 2.3.6 clamps the tower's X coordinate in its preview to
    # the bed edges using configured width, brim, and a 1 mm pad. Match that
    # single-axis adjustment before generic placement so opening a generated
    # project does not silently rewrite its tower position.
    preview_guard_enabled = bool(request.tower_preview_x_guard_enabled)
    preview_guard_margin = max(0.0, float(request.tower_preview_x_guard_margin))
    if bed is not None and preview_guard_enabled:
        maximum_preview_guarded_x = (
            bed.right - original.tower_width - preview_guard_margin
        )
        adjusted_preview_guarded_x = min(
            max(original.tower_x, preview_guard_margin),
            maximum_preview_guarded_x,
        )
        if abs(adjusted_preview_guarded_x - original.tower_x) > _EPSILON:
            guarded_original = _build_result(
                request,
                translation=centered_translation,
                tower_x=adjusted_preview_guarded_x,
                tower_y=original.tower_y,
                tower_width=original.tower_width,
                tower_depth=original.tower_depth,
                tower_rotation=original.tower_rotation,
                adapted=True,
                requires_manual_adjustment=False,
                reason="adapted_native_preview_x_guard",
            )
            if _layout_is_safe(guarded_original, request, rect_allowed):
                return guarded_original

    safe_candidates: list[_ScoredPlacement] = []
    fallback_candidates: list[WipeTowerPlacementResult] = []
    best_rank_by_orientation: dict[int, tuple[int, int]] = {}
    if bed is not None:
        preferred_edge_clearance = max(
            edge_clearance,
            float(request.preferred_edge_clearance),
        )
        clearance_candidates = _dedupe(
            (preferred_edge_clearance, edge_clearance)
        )
        for clearance_index, candidate_edge_clearance in enumerate(
            clearance_candidates
        ):
            model_margin = (
                (max(0.0, request.model_brim) if request.reserve_model_brim_at_bed_edge else 0.0)
                + candidate_edge_clearance
            )
            base_tower_margin = (
                max(0.0, request.tower_brim) + candidate_edge_clearance
            )
            max_horizontal_width = bed.width - 2.0 * _tower_margin(
                request, max(2.0, bed.width - 2.0 * base_tower_margin),
                candidate_edge_clearance,
            )
            horizontal_dimensions: list[tuple[float, float]] = []
            if max_horizontal_width >= 2.0:
                preferred_width = min(
                    max_horizontal_width,
                    max(
                        _MIN_LONG_STRIP_MM,
                        min(
                            max_horizontal_width,
                            max(2.0, request.tower_width),
                        ),
                    ),
                )
                for width in _dedupe((preferred_width, max_horizontal_width)):
                    horizontal_dimensions.append(
                        (
                            width,
                            _estimate_request_tower_depth(request, width),
                        )
                    )

            orientation_sides = (("top", "bottom"), ("right", "left"))
            for orientation_index, sides in enumerate(orientation_sides):
                dimensions = (
                    horizontal_dimensions
                    if orientation_index == 0
                    else _vertical_strip_dimensions(request, bed, base_tower_margin)
                )
                for width_index, (width, depth) in enumerate(dimensions):
                    if not _width_can_still_win(
                        best_rank_by_orientation.get(orientation_index),
                        width_rank=width_index,
                        clearance_rank=clearance_index,
                    ):
                        # Later widths only rank lower, so none of them can win.
                        break
                    footprint_width, footprint_height = _tower_footprint_dimensions(
                        request,
                        width,
                        depth,
                    )
                    tower_margin = _tower_margin(
                        request, footprint_width, candidate_edge_clearance,
                    )
                    if (
                        footprint_width + 2.0 * tower_margin > bed.width + _EPSILON
                        or footprint_height + 2.0 * tower_margin > bed.height + _EPSILON
                    ):
                        continue
                    for side_index, side in enumerate(sides):
                        perpendicular_margin = tower_margin
                        if clearance_index == 0 and side == "top":
                            perpendicular_margin = max(
                                perpendicular_margin,
                                _tower_margin(
                                    request, footprint_width,
                                    float(request.preferred_top_edge_clearance),
                                ),
                            )
                        if side in {"top", "bottom"}:
                            if (
                                footprint_height
                                + perpendicular_margin
                                + tower_margin
                                > bed.height + _EPSILON
                            ):
                                continue
                        elif (
                            footprint_width
                            + perpendicular_margin
                            + tower_margin
                            > bed.width + _EPSILON
                        ):
                            continue
                        offsets = _tower_along_offsets(
                            request,
                            bed=bed,
                            footprint_width=footprint_width,
                            footprint_height=footprint_height,
                            margin=tower_margin,
                            side=side,
                        )
                        for offset_index, offset in enumerate(offsets):
                            footprint = _tower_bounds_at_side(
                                bed=bed,
                                footprint_width=footprint_width,
                                footprint_height=footprint_height,
                                margin=tower_margin,
                                perpendicular_margin=perpendicular_margin,
                                side=side,
                                along_offset=offset,
                            )
                            tower_x, tower_y = _anchor_for_bounds(
                                footprint,
                                width,
                                depth,
                                0.0,
                            )
                            position_reason = f"adapted_{side}"
                            if preview_guard_enabled:
                                maximum_preview_guarded_x = (
                                    bed.right - width - preview_guard_margin
                                )
                                if maximum_preview_guarded_x < preview_guard_margin:
                                    continue
                                guarded_x = _clamp(
                                    tower_x,
                                    preview_guard_margin,
                                    maximum_preview_guarded_x,
                                )
                                if abs(guarded_x - tower_x) > _EPSILON:
                                    tower_x = guarded_x
                                    position_reason = (
                                        "adapted_native_preview_x_guard"
                                    )
                            placeholder = _build_result(
                                request,
                                translation=centered_translation,
                                tower_x=tower_x,
                                tower_y=tower_y,
                                tower_width=width,
                                tower_depth=depth,
                                tower_rotation=0.0,
                                adapted=True,
                                requires_manual_adjustment=False,
                                reason=position_reason,
                            )
                            fallback_candidates.append(placeholder)
                            if not rect_allowed(placeholder.tower_outer_bounds):
                                continue
                            collision_tower_outer = (
                                placeholder.tower_outer_bounds.expanded(
                                    max(
                                        0.0,
                                        float(request.model_tower_clearance)
                                        - 2.0 * edge_clearance,
                                    )
                                )
                            )
                            translations = (
                                [(0.0, 0.0)]
                                if request.model_translation_locked
                                else _model_position_candidates(
                                    request,
                                    bed,
                                    model_margin,
                                    collision_tower_outer,
                                )
                            )
                            for translation in translations:
                                candidate = _build_result(
                                    request,
                                    translation=translation,
                                    tower_x=tower_x,
                                    tower_y=tower_y,
                                    tower_width=width,
                                    tower_depth=depth,
                                    tower_rotation=0.0,
                                    adapted=True,
                                    requires_manual_adjustment=False,
                                    reason=position_reason,
                                )
                                if not _layout_is_safe(candidate, request, rect_allowed):
                                    continue
                                movement = math.hypot(
                                    translation[0] - centered_translation[0],
                                    translation[1] - centered_translation[1],
                                )
                                safe_candidates.append(
                                    _ScoredPlacement(
                                        result=candidate,
                                        clearance_rank=clearance_index,
                                        orientation_index=orientation_index,
                                        width_rank=width_index,
                                        movement=movement,
                                        side_rank=side_index,
                                        offset_rank=offset_index,
                                    )
                                )
                                rank = (width_index, clearance_index)
                                best_rank_by_orientation[orientation_index] = min(
                                    best_rank_by_orientation.get(orientation_index, rank),
                                    rank,
                                )
                                break

    if safe_candidates:
        # Preserve the proven width search within each orientation: use the
        # candidate nearest the slicer's stable 30 mm vertical idiom (or the
        # preferred long horizontal width) before considering farther widths.
        # Then choose between the best horizontal and vertical layouts using
        # model movement and physical footprint. This makes normal, already-safe
        # projects visibly auto-plan without regressing tight-bed width choices.
        best_by_orientation: dict[int, _ScoredPlacement] = {}
        for candidate in safe_candidates:
            current = best_by_orientation.get(candidate.orientation_index)
            if (
                current is None
                or candidate.within_orientation_score
                < current.within_orientation_score
            ):
                best_by_orientation[candidate.orientation_index] = candidate

        selected = min(
            best_by_orientation.values(),
            key=lambda candidate: candidate.overall_score(
                prefer_vertical=request.prefer_vertical_strip
            ),
        )
        return selected.result

    # Irregular vendor beds may admit a safe native template placement while
    # none of the generic edge anchors fit. Preserve that verified-safe layout
    # instead of turning a successful project into a false manual warning.
    if original_is_safe:
        return original

    fallback = fallback_candidates[0] if fallback_candidates else original
    return _build_result(
        request,
        translation=fallback.model_translation,
        tower_x=fallback.tower_x,
        tower_y=fallback.tower_y,
        tower_width=fallback.tower_width,
        tower_depth=fallback.tower_depth,
        tower_rotation=fallback.tower_rotation,
        adapted=True,
        requires_manual_adjustment=True,
        reason="no_safe_layout_without_scaling_or_disabling_tower",
    )


def _solve_supported_tower_shapes(
    request: WipeTowerPlacementRequest,
) -> WipeTowerPlacementResult:
    current = _solve_tower_body_placement(request)
    if (
        not current.requires_manual_adjustment
        or not request.tower_square_rib_body
        or "rectangle" not in request.tower_wall_types
    ):
        return current

    rectangular = _solve_tower_body_placement(replace(
        request, tower_square_rib_body=False, tower_rib_width=0.0,
    ))
    if rectangular.requires_manual_adjustment:
        return current
    return replace(
        rectangular, tower_wall_type="rectangle",
        reason=f"{rectangular.reason}_rectangle",
    )


def solve_wipe_tower_placement(
    request: WipeTowerPlacementRequest,
) -> WipeTowerPlacementResult:
    """Search supported tower shapes without confusing brim estimates with geometry.

    优先预留完整底边。仅底边估算挡住床边时，保留模型/塔的真实边界和
    两者之间的完整底边间距，继续求解侧边布局并提示原生切片确认底边。
    不缩放模型、不减少冲刷量，也不更改底边设置。
    """
    current = _solve_supported_tower_shapes(request)
    if not current.requires_manual_adjustment:
        return current
    if request.model_brim > 0 and request.reserve_model_brim_at_bed_edge:
        # Auto brim is determined by native slicing, not by a full rectangular
        # offset of the model. Keep that offset for model/tower separation, but
        # do not discard a body-safe layout solely for a possible brim at the
        # bed edge. Explicit brims also retain a warning until native review.
        body_layout = _solve_supported_tower_shapes(replace(
            request, reserve_model_brim_at_bed_edge=False,
        ))
        if not body_layout.requires_manual_adjustment:
            return replace(
                body_layout, model_brim_requires_review=True,
                requires_manual_adjustment=True,
                warning_code=WIPE_TOWER_MANUAL_WARNING_CODE,
                reason="model_brim_requires_native_slice",
            )
    bed = current.bed_bounds
    if bed is not None and (
        current.model_outer_bounds.width > bed.width + _EPSILON
        or current.model_outer_bounds.height > bed.height + _EPSILON
    ):
        return replace(current, reason="model_envelope_exceeds_printable_bounds")
    return current


__all__ = [
    "Rect",
    "WIPE_TOWER_MANUAL_WARNING_CODE",
    "WipeTowerPlacementRequest",
    "WipeTowerPlacementResult",
    "estimate_wipe_tower_depth",
    "solve_wipe_tower_placement",
]
