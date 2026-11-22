"""
Lumina Studio - Geometry Utilities
Geometry utilities module - Pure functional geometry calculation tools
"""

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
