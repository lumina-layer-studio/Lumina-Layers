from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

MODEL_SURFACE_FATAL_ERRORS = (MemoryError,)
MODEL_SURFACE_ARTWORK_NO_OVERLAP = "model_surface_artwork_no_overlap"


class ModelSurfaceError(ValueError):
    """Domain error for model-surface workflow.

    模型覆面流程的领域错误。
    """


class EdgeMode(str, Enum):
    """Artwork edge handling mode for selected model surfaces.

    选中模型表面的画面边缘处理模式。
    """

    EDGE_TO_EDGE = "edge_to_edge"
    INSET = "inset"


@dataclass(frozen=True)
class MeshSummary:
    """Public mesh quality summary in millimeters.

    面向接口和界面的毫米单位模型质量摘要。
    """

    vertex_count: int
    face_count: int
    bounds_min_mm: tuple[float, float, float]
    bounds_max_mm: tuple[float, float, float]
    extents_mm: tuple[float, float, float]
    is_watertight: bool
    is_winding_consistent: bool
    body_count: int
    unit_warning: str | None

    def to_public_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation.

        返回适合 JSON 序列化的公开数据。
        """

        return asdict(self)


@dataclass(frozen=True)
class LoadedSurfaceMesh:
    """Loaded mesh plus immutable summary for model-surface operations.

    用于模型覆面操作的已加载网格和不可变摘要。
    """

    path: Path
    mesh: Any
    summary: MeshSummary


@dataclass(frozen=True)
class PlaneFrame:
    """Local 2D frame anchored on a selected 3D plane.

    锚定在选中三维平面上的局部二维坐标系。
    """

    origin: tuple[float, float, float]
    normal: tuple[float, float, float]
    u_axis: tuple[float, float, float]
    v_axis: tuple[float, float, float]


@dataclass(frozen=True)
class SurfaceSelection:
    """Connected planar face selection from a triangle mesh.

    从三角网格中选出的连通平面区域。
    """

    face_indices: tuple[int, ...]
    normal: tuple[float, float, float]
    plane_origin: tuple[float, float, float]
    area_mm2: float
    face_count: int


@dataclass(frozen=True)
class SurfaceCandidate:
    """Printable planar candidate surfaced for interactive selection.

    可在交互界面中选择的可打印平面候选区域。
    """

    id: str
    face_index: int
    face_indices: tuple[int, ...]
    normal: tuple[float, float, float]
    plane_origin: tuple[float, float, float]
    area_mm2: float
    face_count: int
    footprint: Any


@dataclass(frozen=True)
class SurfaceFootprint:
    """Projected 2D footprint of a selected model surface.

    选中模型表面投影后的二维轮廓。
    """

    frame: PlaneFrame
    outer: tuple[tuple[float, float], ...]
    holes: tuple[tuple[tuple[float, float], ...], ...]
    bounds_min: tuple[float, float]
    bounds_max: tuple[float, float]
    bounds_width_mm: float
    bounds_height_mm: float
    area_mm2: float
    hole_count: int
    # Mesh provenance anchors thickness rays to the selected surface, even
    # when its fitted plane crosses a shallow cavity.
    face_indices: tuple[int, ...] = ()
