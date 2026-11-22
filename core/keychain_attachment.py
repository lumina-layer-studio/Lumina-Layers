"""Place keychain loops in artwork millimetres and validate the printable joint."""

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.affinity import scale, translate
from shapely.geometry import GeometryCollection, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
import trimesh

from core.errors import KeychainPlacementError
from core.geometry_utils import KEYCHAIN_JOINT_INSET_MM, keychain_loop_footprint
from core.vector_structure import resolve_structure_plan

_AREA_EPSILON_MM2 = 1e-6
_CLEARANCE_EPSILON_MM = 1e-5


@dataclass(frozen=True)
class LoopProfile:
    width: float
    length: float
    hole: float
    angle: float

    def footprint(self) -> Polygon:
        return keychain_loop_footprint(self.width, self.length, self.hole, 0, 0, self.angle)


def vector_keychain_body(analysis: object) -> BaseGeometry:
    structure = resolve_structure_plan(analysis)
    return scale(structure.body, structure.mm_per_unit, -structure.mm_per_unit, origin=(0, 0))


def _preset_target(bounds: tuple[float, float, float, float], preset: str) -> Point:
    x0, y0, x1, y1 = bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    corner_inset = min(2 * KEYCHAIN_JOINT_INSET_MM, (x1 - x0) / 2)
    return Point({
        "top-left": (x0 + corner_inset, y1),
        "top-right": (x1 - corner_inset, y1),
        "left-center": (x0, cy),
        "right-center": (x1, cy),
        "bottom-center": (cx, y0),
    }.get(preset, (cx, y1)))


def _local_bounds(point: Point, radius: float) -> tuple[float, float, float, float]:
    return point.x - radius, point.y - radius, point.x + radius, point.y + radius


def _contact_region(body: BaseGeometry, shape: Polygon) -> BaseGeometry:
    """Return the translations for which the convex profile touches the body.

    Sweep the reflected profile along every exterior and interior edge and
    include the body at one kernel vertex. This is body ⊕ (-profile), so it
    preserves concave bays and holes without sampling possible anchor points.
    """
    if body.is_empty or shape.is_empty:
        return GeometryCollection()
    kernel = -np.asarray(shape.exterior.coords[:-1])
    pieces = [translate(body, *kernel[0])]
    polygons = shapely.get_parts(shapely.get_parts(body))
    for polygon in polygons:
        if not isinstance(polygon, Polygon):
            continue
        for ring in (polygon.exterior, *polygon.interiors):
            coords = np.asarray(ring.coords)
            for start in range(0, len(coords) - 1, 2048):
                ends = coords[start + 1:start + 2049]
                starts = coords[start:start + len(ends)]
                corners = np.concatenate((
                    starts[:, None, :] + kernel, ends[:, None, :] + kernel,
                ), axis=1)
                pieces.append(shapely.union_all(shapely.convex_hull(shapely.multipoints(corners))))
    return shapely.union_all(pieces)


def _seat_loop(body: BaseGeometry, profile: LoopProfile, target: Point) -> tuple[float, float]:
    loop = profile.footprint()
    outer = Polygon(loop.exterior)
    bore = Polygon(loop.interiors[0])
    occupied_bore = _contact_region(body, bore).buffer(_CLEARANCE_EPSILON_MM)
    # Contact of these eroded outlines means the overlap contains a 0.4 mm
    # disk. It gives a 0.4 mm lap on straight walls and a solid patch even at
    # a corner, where a fixed translation could leave only a point of contact.
    radius = KEYCHAIN_JOINT_INSET_MM / 2
    joint = _contact_region(body.buffer(-radius), outer.buffer(-radius))
    viable = joint.difference(occupied_bore)
    if viable.is_empty:
        # A narrow feature may not accommodate the whole joint disk. Keep
        # the bore clear and inset wherever its actual geometry allows.
        contact = _contact_region(body, outer)
        viable = contact.buffer(-_CLEARANCE_EPSILON_MM).difference(occupied_bore)
        if viable.is_empty:
            # The draft remains editable when there is no hole-safe seat.
            viable = contact if joint.is_empty else joint
    if viable.is_empty:
        raise KeychainPlacementError.detached()
    anchor, _ = nearest_points(viable, target)
    return anchor.x, anchor.y


def solve_vector_loop(
    body: BaseGeometry, profile: LoopProfile, preset: str,
) -> tuple[float, float]:
    if body.is_empty:
        raise KeychainPlacementError.detached()
    target = _preset_target(body.bounds, preset)
    # The nearest body point gives a finite search window even for separated
    # islands with a preset in the middle of the transparent space.
    reach = max(profile.width, profile.length)
    radius = target.distance(body) + 3 * reach
    local = body.intersection(box(*_local_bounds(target, radius)))
    return _seat_loop(local, profile, target)


def _raster_footprint(mask: np.ndarray, col: int, row: int) -> BaseGeometry:
    """Polygonize full occupied cells, including internal voids."""
    # Merge equal rows before forming rectangles to avoid emitting a run
    # polygon per row inside large, solid areas.
    changes = np.flatnonzero(np.any(mask[1:] != mask[:-1], axis=1)) + 1
    row_edges = np.r_[0, changes, len(mask)]
    stripes = mask[row_edges[:-1]]
    # Signed differences of padded rows mark the two sides of each occupied run.
    padded = np.pad(stripes, ((0, 0), (1, 1))).astype(np.int8)
    start_row, start_col = np.nonzero(np.diff(padded, axis=1) == 1)
    _, end_col = np.nonzero(np.diff(padded, axis=1) == -1)
    return shapely.union_all(shapely.box(
        col + start_col, -row - row_edges[start_row + 1],
        col + end_col, -row - row_edges[start_row],
    ))


def solve_raster_loop(
    mask: np.ndarray, pixel_scale_x: float, pixel_scale_y: float,
    profile: LoopProfile, preset: str,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return the artwork anchor and body centre using the exact raster grid."""
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if not len(rows):
        raise KeychainPlacementError.detached()
    height, width = mask.shape
    bounds = (
        cols[0] * pixel_scale_x, (height - rows[-1] - 1) * pixel_scale_y,
        (cols[-1] + 1) * pixel_scale_x, (height - rows[0]) * pixel_scale_y,
    )
    target = _preset_target(bounds, preset)
    reach = max(profile.width, profile.length)
    radius = 3 * reach
    while True:
        left, bottom, right, top = _local_bounds(target, radius)
        c0 = max(0, int(np.floor(left / pixel_scale_x)))
        c1 = min(width, int(np.ceil(right / pixel_scale_x)))
        r0 = max(0, height - int(np.ceil(top / pixel_scale_y)))
        r1 = min(height, height - int(np.floor(bottom / pixel_scale_y)))
        local = mask[r0:r1, c0:c1]
        if local.any():
            geometry = _raster_footprint(local, c0, r0)
            body = translate(
                scale(geometry, pixel_scale_x, pixel_scale_y, origin=(0, 0)),
                yoff=height * pixel_scale_y,
            )
            if radius >= target.distance(body) + 2 * reach:
                break
        if (r0, c0, r1, c1) == (0, 0, height, width):
            break
        radius *= 2
    center = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
    return _seat_loop(body, profile, target), center


def _project_mesh(
    mesh: trimesh.Trimesh, transform: np.ndarray,
    window: Polygon | None = None,
) -> BaseGeometry:
    """Project printable triangle caps in bounded batches."""
    bounds = window.bounds if window is not None else None
    parts = []
    for start in range(0, len(mesh.faces), 65536):
        indices = mesh.faces[start:start + 65536]
        triangles = mesh.vertices[indices] @ transform[:3, :3].T + transform[:3, 3]
        xy = triangles[:, :, :2]
        if bounds is not None:
            overlaps_window = (
                (xy.max(axis=1) > bounds[:2]) & (xy.min(axis=1) < bounds[2:])
            ).all(axis=1)
            xy = xy[overlaps_window]
        projected = shapely.polygons(xy)
        projected = projected[shapely.area(projected) > 0]
        if len(projected):
            if window is not None:
                projected = shapely.intersection(projected, window)
            parts.append(shapely.union_all(projected))
    return shapely.union_all(parts)


def validate_keychain_export(scene: trimesh.Scene, *, separate_backing: bool = False) -> None:
    """Require a solid overlap and a through opening in the final print scene."""
    if "Keychain_Loop" not in scene.graph.nodes_geometry:
        raise KeychainPlacementError.detached()
    ring_transform, ring_name = scene.graph["Keychain_Loop"]
    ring_mesh = scene.geometry[ring_name]
    ring = _project_mesh(ring_mesh, ring_transform)
    if not isinstance(ring, Polygon) or not ring.interiors:
        raise KeychainPlacementError.blocked()
    bore = Polygon(ring.interiors[0])
    window = box(*ring.bounds)
    ring_z = trimesh.transform_points(trimesh.bounds.corners(ring_mesh.bounds), ring_transform)[:, 2]
    z_min, z_max = ring_z.min(), ring_z.max()
    joined = False
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph[node]
        if name == ring_name:
            continue
        mesh = scene.geometry[name]
        if not isinstance(mesh, trimesh.Trimesh) or mesh.is_empty:
            continue
        if separate_backing and mesh.metadata.get("lumina_print_role") == "backing":
            continue
        bounds = trimesh.transform_points(trimesh.bounds.corners(mesh.bounds), transform)
        if not window.intersects(box(*bounds[:, :2].min(axis=0), *bounds[:, :2].max(axis=0))):
            continue
        body = _project_mesh(mesh, transform, window)
        if min(z_max, bounds[:, 2].max()) > max(z_min, bounds[:, 2].min()):
            joined = joined or ring.intersection(body).area > _AREA_EPSILON_MM2
        bore = bore.difference(body)
    if not joined:
        raise KeychainPlacementError.detached()
    if bore.area <= _AREA_EPSILON_MM2:
        raise KeychainPlacementError.blocked()
