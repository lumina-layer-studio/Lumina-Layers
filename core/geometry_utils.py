"""
Lumina Studio - Geometry Utilities
Geometry utilities module - Pure functional geometry calculation tools
"""

from collections.abc import Callable

import numpy as np
from shapely.geometry import Polygon
import trimesh
from trimesh.creation import extrude_polygon

from api.structured_logging import get_logger

log = get_logger(__name__)

KEYCHAIN_JOINT_INSET_MM = 0.4
KEYCHAIN_ARC_SEGMENTS = 32


def _keychain_loop_profile(
    width_mm: float,
    length_mm: float,
    hole_dia_mm: float,
) -> tuple[float, float, float]:
    """Return (circle_radius, rect_height, hole_radius) for a loop."""
    circle_radius = width_mm / 2
    rect_height = max(0.2, length_mm - circle_radius)
    hole_radius = min(hole_dia_mm / 2, circle_radius * 0.8, rect_height * 0.8)
    return circle_radius, rect_height, hole_radius


def keychain_loop_hole_clearance(
    width_mm: float,
    length_mm: float,
    hole_dia_mm: float,
) -> float:
    """Return the distance from an unrotated loop's bottom edge to its hole.
    返回未旋转挂环底边到挂孔最低点的距离。

    A loop may sink into the model body by at most this depth before the
    hole starts to overlap the body.
    挂环最多可向模型本体内嵌入该深度，超过后挂孔会与本体重叠。

    Args:
        width_mm (float): Loop width in millimeters. (环宽度，毫米)
        length_mm (float): Loop length in millimeters. (环长度，毫米)
        hole_dia_mm (float): Hole diameter in millimeters. (孔径，毫米)

    Returns:
        float: Bottom-to-hole clearance in millimeters. (底边到孔的距离，毫米)
    """
    _circle_radius, rect_height, hole_radius = _keychain_loop_profile(
        width_mm, length_mm, hole_dia_mm
    )
    return max(0.0, rect_height - hole_radius)


def resolve_keychain_contact_anchor_y(
    lowest_top_y: float,
    highest_top_y: float,
    hole_clearance_mm: float,
    joint_inset_mm: float = 0.0,
) -> float:
    """Return the loop bottom Y that keeps a full-width, hole-safe connection.
    返回既保证整段接触、又不让挂孔压入本体的挂环底边 Y。

    Seat the foot below the lowest edge in the band, limited by the clearance
    to the unrotated hole. This preserves the joint along straight and sloped edges.

    Args:
        lowest_top_y (float): Lowest top-contour Y inside the band. (接触带内轮廓最低点 Y)
        highest_top_y (float): Highest top-contour Y inside the band. (接触带内轮廓最高点 Y)
        hole_clearance_mm (float): Result of ``keychain_loop_hole_clearance``.
            (``keychain_loop_hole_clearance`` 的结果)
        joint_inset_mm (float): Overlap to leave on a straight edge.

    Returns:
        float: Loop bottom Y before any outward user offset. (未叠加向外偏移的挂环底边 Y)
    """
    return max(lowest_top_y - joint_inset_mm, highest_top_y - max(0.0, hole_clearance_mm))


def resolve_keychain_attachment(
    bounds_xy: tuple[float, float, float, float],
    preset: str,
    offset_x: float,
    offset_y: float,
    contact_width_mm: float,
    hole_clearance_mm: float,
    contact_range: Callable[[int, int, float, float], tuple[float, float] | None],
) -> tuple[float, float]:
    """Resolve the angle-independent loop pivot in artwork XY (Y up).

    Query the body along the preset's edge, using the same (tangent, outward)
    frame for all sides. Seat the pivot a small distance into the body so a
    flat edge has a printable lap joint even at zero rotation.
    """
    min_x, min_y, max_x, max_y = bounds_xy
    along_x = preset not in ("left-center", "right-center")
    outward_sign = -1 if preset in ("left-center", "bottom-center") else 1
    tangent_min, tangent_max = (min_x, max_x) if along_x else (min_y, max_y)
    normal_min, normal_max = (min_y, max_y) if along_x else (min_x, max_x)
    tangent_offset, normal_offset = (offset_x, offset_y) if along_x else (offset_y, offset_x)

    max_inset = KEYCHAIN_JOINT_INSET_MM if contact_width_mm > 0 else 0.0
    inset = min(max_inset, (normal_max - normal_min) / 2)
    corner_inset = min(2 * max_inset, (tangent_max - tangent_min) / 2)
    tangent = (tangent_min + tangent_max) / 2
    if preset == "top-left":
        tangent = tangent_min + corner_inset
    elif preset == "top-right":
        tangent = tangent_max - corner_inset
    tangent += tangent_offset

    outward_edge = normal_max if outward_sign > 0 else -normal_min
    local_range = contact_range(0 if along_x else 1, outward_sign, tangent, contact_width_mm)
    if local_range is None:
        outward = outward_edge - inset
    else:
        outward = resolve_keychain_contact_anchor_y(*local_range, hole_clearance_mm, inset)
        if preset == "top-center":
            normal_offset = max(0.0, normal_offset)

    normal = outward_sign * outward + normal_offset
    return (tangent, normal) if along_x else (normal, tangent)


def keychain_loop_footprint(
    width_mm: float,
    length_mm: float,
    hole_dia_mm: float,
    attach_x_mm: float,
    attach_y_mm: float,
    angle_deg: float = 0.0,
) -> Polygon:
    """Build the loop in artwork XY, rotated about the midpoint of its foot."""
    radius, rect_height, hole_radius = _keychain_loop_profile(width_mm, length_mm, hole_dia_mm)
    arc = np.linspace(0.0, np.pi, KEYCHAIN_ARC_SEGMENTS + 1)
    outer = np.vstack((
        [(-radius, 0.0), (radius, 0.0)],
        np.column_stack((radius * np.cos(arc), rect_height + radius * np.sin(arc))),
    ))
    angles = np.linspace(0.0, 2 * np.pi, KEYCHAIN_ARC_SEGMENTS, endpoint=False)
    hole = np.column_stack((hole_radius * np.cos(angles), rect_height + hole_radius * np.sin(angles)))
    radians = np.deg2rad(angle_deg)
    cosine, sine = np.cos(radians), np.sin(radians)
    rotation = np.array([[cosine, sine], [-sine, cosine]])
    offset = np.array([attach_x_mm, attach_y_mm])
    return Polygon(outer @ rotation + offset, [hole @ rotation + offset])


def create_keychain_loop(
    width_mm: float,
    length_mm: float,
    hole_dia_mm: float,
    thickness_mm: float,
    attach_x_mm: float,
    attach_y_mm: float,
    angle_deg: float = 0.0,
) -> trimesh.Trimesh:
    """Create keychain loop mesh with optional Z-axis rotation.
    创建钥匙扣挂孔网格，支持绕 Z 轴旋转。

    Generates a rectangle + semicircle loop geometry with a circular hole.
    The foot midpoint is the local origin, matching the live 3D preview.
    Rotation is applied there before placing the loop at the attachment point.

    Args:
        width_mm (float): Loop width in millimeters. (环宽度，毫米)
        length_mm (float): Loop length in millimeters. (环长度，毫米)
        hole_dia_mm (float): Hole diameter in millimeters. (孔径，毫米)
        thickness_mm (float): Loop thickness in millimeters. (环厚度，毫米)
        attach_x_mm (float): Attachment point X coordinate in millimeters. (吸附点 X 坐标，毫米)
        attach_y_mm (float): Attachment point Y coordinate in millimeters. (吸附点 Y 坐标，毫米)
        angle_deg (float): Rotation angle around Z-axis in degrees, default 0. (绕 Z 轴旋转角度，度，默认 0)

    Returns:
        trimesh.Trimesh: Loop mesh object. (挂孔网格对象)
    """
    log.debug(
        "Creating keychain loop mesh",
        extra={
            "event": "keychain_loop_mesh_started",
            "width_mm": width_mm,
            "length_mm": length_mm,
            "hole_dia_mm": hole_dia_mm,
            "thickness_mm": thickness_mm,
            "attach_x_mm": attach_x_mm,
            "attach_y_mm": attach_y_mm,
            "angle_deg": angle_deg,
        },
    )
    polygon = keychain_loop_footprint(
        width_mm, length_mm, hole_dia_mm, attach_x_mm, attach_y_mm, angle_deg,
    )
    mesh = extrude_polygon(polygon, thickness_mm, engine="earcut")
    
    log.debug(
        "Keychain loop mesh created",
        extra={
            "event": "keychain_loop_mesh_created",
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.faces),
        },
    )
    
    return mesh
