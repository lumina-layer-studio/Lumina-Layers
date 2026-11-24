"""
Lumina Studio - Mesh Generation Strategies (Refactored v2.2)
Mesh generation strategy module - Refactored version

ARCHITECTURE:
- High-Fidelity Mode: exact labeled surfaces with optional material dilation
- Pixel Art Mode: exact labeled surfaces without material dilation

TOPOLOGY: Same-material cells share one exposed surface; edge/point-only
contacts retain independent closed index domains. Puzzle boundaries are
sampled onto that same printable pixel lattice before meshing; there is no
secondary polygon-extrusion path.
"""

import logging
from abc import ABC, abstractmethod

import cv2
import numpy as np
from shapely import contains_xy
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union

from config import ModelingMode
from core.layered_meshing import (
    build_labeled_surface_mesh,
    group_identical_material_layers,
)

log = logging.getLogger(__name__)


def _normalize_polygonal_geometry(geometry):
    """Normalize polygonal geometry and drop non-polygon parts.
    规范化多边形几何并丢弃非多边形部分。
    """
    if geometry is None or getattr(geometry, "is_empty", True):
        return None

    candidate = geometry.buffer(0) if not geometry.is_valid else geometry
    if candidate.is_empty:
        return None
    if isinstance(candidate, Polygon):
        return candidate
    if isinstance(candidate, MultiPolygon):
        return candidate
    if isinstance(candidate, GeometryCollection):
        parts = [
            part
            for part in candidate.geoms
            if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty
        ]
        if not parts:
            return None
        return _normalize_polygonal_geometry(unary_union(parts))
    return None


def rasterize_boundary_geometry(
    geometry,
    *,
    height_px: int,
    width_px: int,
) -> np.ndarray:
    """Sample a puzzle boundary onto the printable cell lattice.

    将拼图边界按像素单元中心采样到统一可打印网格。

    The converter already runs puzzle pieces at a fixed pixels-per-millimetre
    resolution finer than the supported nozzle widths. Keeping the boundary
    on this lattice lets all raster modes use one by-construction mesher and
    removes the former polygon extrusion/topology-repair branch entirely.

    Args:
        geometry: Polygonal boundary in y-down pixel coordinates.
            （y 向下像素坐标中的多边形边界）
        height_px: Output mask height.（输出掩码高度）
        width_px: Output mask width.（输出掩码宽度）

    Returns:
        Boolean ``(height_px, width_px)`` cell mask.（布尔单元掩码）
    """

    height_px = int(height_px)
    width_px = int(width_px)
    if height_px <= 0 or width_px <= 0:
        raise ValueError("Boundary raster dimensions must be positive")
    normalized = _normalize_polygonal_geometry(geometry)
    if normalized is None:
        return np.zeros((height_px, width_px), dtype=bool)
    x_centers = np.arange(width_px, dtype=np.float64) + 0.5
    y_centers = np.arange(height_px, dtype=np.float64) + 0.5
    return np.asarray(
        contains_xy(normalized, x_centers[None, :], y_centers[:, None]),
        dtype=bool,
    )


def _mask_volume_from_layer_groups(layer_groups, shape):
    """Expand merged masks into an exact boolean Z/Y/X volume.
    将合并后的掩码组还原为精确的 Z/Y/X 布尔体。
    """

    mask_volume = np.zeros(shape, dtype=bool)
    for start_z, end_z, mask in layer_groups:
        mask_volume[start_z : end_z + 1] = mask
    return mask_volume


def _dilate_mask_preserving_enclosed_voids(mask, kernel):
    """Dilate into exterior background while keeping enclosed voids open."""
    if not np.any(mask):
        return mask

    mask_uint8 = mask.astype(np.uint8)
    dilated_mask = cv2.dilate(mask_uint8, kernel, iterations=1).astype(bool)

    background = (~mask).astype(np.uint8)
    if not np.any(background):
        return dilated_mask

    _, labels = cv2.connectedComponents(background, connectivity=8)
    border_labels = np.unique(
        np.concatenate((labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]))
    )
    exterior_background = np.isin(labels, border_labels)
    enclosed_voids = background.astype(bool) & ~exterior_background
    if not np.any(enclosed_voids):
        return dilated_mask

    return dilated_mask & ~enclosed_voids


class BaseMesher(ABC):
    """Mesh generator abstract base class"""

    @abstractmethod
    def generate_mesh(self, voxel_matrix, mat_id, height_px, *, z_edges: np.ndarray | None = None):
        """
        Generate 3D mesh for specified material

        Args:
            voxel_matrix: (Z, H, W) voxel matrix
            mat_id: Material ID (0-7 for regular materials, -2 for backing layer)
            height_px: Image height (pixels)
            z_edges: Optional Z+1 integer layer boundaries for this volume.
                Omit for dense volumes; never reused by a later mesh call.

        Returns:
            trimesh.Trimesh or None
        """
        pass

    def generate_backing_mesh(self, voxel_matrix, height_px, *, z_edges: np.ndarray | None = None):
        """
        Generate backing mesh (convenience method)

        Args:
            voxel_matrix: (Z, H, W) voxel matrix
            height_px: Image height (pixels)
            z_edges: Optional Z+1 integer layer boundaries for this volume.

        Returns:
            trimesh.Trimesh or None
        """
        kwargs = {"z_edges": z_edges} if z_edges is not None else {}
        return self.generate_mesh(voxel_matrix, mat_id=-2, height_px=height_px, **kwargs)

class VoxelMesher(BaseMesher):
    """
    Pixel art mode mesh generator
    Builds one exact exposed surface from the material label volume.
    """

    def generate_mesh(self, voxel_matrix, mat_id, height_px, *, z_edges: np.ndarray | None = None):
        """Generate a pixel-mode exact labeled surface.
        生成像素模式的精确标签表面。

        Args:
            voxel_matrix (np.ndarray): (Z, H, W) int voxel matrix.
            mat_id (int): Material ID (0-7 or -2 for backing).
            height_px (int): Image height in pixels.
            z_edges: Optional Z+1 integer layer boundaries for this volume.

        Returns:
            trimesh.Trimesh or None
        """
        mesh_type = "Backing" if mat_id == -2 else f"Mat ID {mat_id}"
        mesh = build_labeled_surface_mesh(
            np.asarray(voxel_matrix),
            material_id=mat_id,
            height_px=height_px,
            **({"z_edges": z_edges} if z_edges is not None else {}),
        )
        if mesh is not None:
            patch_count = int(
                mesh.metadata["layered_mesh_stats"]["merged_patch_count"]
            )
            log.info(
                "%s: built exact surface from %s patches",
                mesh_type,
                patch_count,
                extra={
                    "event": "voxel_mesher_mesh_built",
                    "mesh_type": mesh_type,
                    "patch_count": patch_count,
                    "vertex_count": len(mesh.vertices),
                    "face_count": len(mesh.faces),
                },
            )
        return mesh

class HighFidelityMesher(BaseMesher):
    """
    High-fidelity mode mesh generator
    Builds an optimized closed surface after optional material dilation.

    ALGORITHM:
    1. Apply morphological dilation to thicken thin features
    2. Reconstruct the effective labeled volume
    3. Emit only exposed faces and merge coplanar cells
    4. Preserve independent index domains for edge/point-only contacts

    OPTIMIZATION:
    - Removes internal faces between same-material cells
    - Triangulates split rectangular boundaries without extra center vertices

    GEOMETRY:
    - Dilation: Expands features by ~0.1-0.15mm to ensure printability
    - Exact edge-to-edge topology on an integer lattice
    - Vertices match pixel coordinates exactly
    """

    def __init__(
        self,
        disable_material_dilation: bool = False,
        boundary_geometry=None,
        *,
        boundary_shape: tuple[int, int] | None = None,
    ):
        """Create a configurable high-fidelity mesher.
        创建可配置的高保真 mesher。

        Args:
            disable_material_dilation: If True, skip per-material dilation.
                (若为 True，则跳过每材质膨胀)
            boundary_geometry: Optional polygonal boundary in pixel space.
                (可选的像素空间 polygon 边界)
            boundary_shape: Shared grid height and width for material meshes.
        """
        self.disable_material_dilation = bool(disable_material_dilation)
        self.boundary_geometry = _normalize_polygonal_geometry(boundary_geometry)
        self._boundary_mask: np.ndarray | None = None
        if self.boundary_geometry is not None and boundary_shape is not None:
            # GEOS can lazily initialize shared geometry during contains_xy.
            # Sample it before starting the parallel material mesh workers.
            height_px, width_px = boundary_shape
            self._boundary_mask = rasterize_boundary_geometry(
                self.boundary_geometry, height_px=height_px, width_px=width_px,
            )
            self._boundary_mask.setflags(write=False)

    def generate_mesh(
        self,
        voxel_matrix,
        mat_id,
        height_px,
        boundary_geometry=None,
        disable_material_dilation=None,
        *,
        z_edges: np.ndarray | None = None,
    ):
        """Generate a high-fidelity exact surface with optional dilation.
        生成可选膨胀的高保真精确表面。

        Args:
            voxel_matrix (np.ndarray): (Z, H, W) int voxel matrix.
            mat_id (int): Material ID (0-7 or -2 for backing).
            height_px (int): Image height in pixels.
            z_edges: Optional Z+1 integer layer boundaries for this volume.

        Returns:
            trimesh.Trimesh or None
        """
        boundary_mask = self._boundary_mask if boundary_geometry is None else None
        boundary_geometry = (
            self.boundary_geometry
            if boundary_geometry is None
            else _normalize_polygonal_geometry(boundary_geometry)
        )
        use_no_dilation = (
            self.disable_material_dilation
            if disable_material_dilation is None
            else bool(disable_material_dilation)
        )
        boundary_enabled = boundary_geometry is not None

        if use_no_dilation and not boundary_enabled:
            layer_groups = None
        elif use_no_dilation:
            layer_groups = group_identical_material_layers(voxel_matrix, mat_id)
        else:
            layer_groups = self._merge_layers_with_dilation(voxel_matrix, mat_id)
        if layer_groups is not None and not layer_groups:
            return None

        mesh_type = "Backing" if mat_id == -2 else f"Mat ID {mat_id}"
        if layer_groups is not None:
            log.info(
                "%s: merged %s layers into %s groups%s%s",
                mesh_type,
                voxel_matrix.shape[0],
                len(layer_groups),
                " [no-dilation]" if use_no_dilation else "",
                " [boundary-aware]" if boundary_enabled else "",
                extra={
                    "event": "mesh_layers_merged",
                    "mesh_type": mesh_type,
                    "layer_count": int(voxel_matrix.shape[0]),
                    "group_count": len(layer_groups),
                    "no_dilation": use_no_dilation,
                    "boundary_enabled": boundary_enabled,
                },
            )

        if use_no_dilation and not boundary_enabled:
            effective_volume = np.asarray(voxel_matrix)
            effective_material_id = mat_id
        else:
            effective_volume = _mask_volume_from_layer_groups(
                layer_groups,
                np.asarray(voxel_matrix).shape,
            )
            effective_material_id = True

        if boundary_enabled:
            height, width = np.shape(voxel_matrix)[1:]
            if boundary_mask is None or boundary_mask.shape != (height, width):
                boundary_mask = rasterize_boundary_geometry(
                    boundary_geometry, height_px=height, width_px=width,
                )
            effective_volume = np.asarray(effective_volume, dtype=bool)
            effective_volume &= boundary_mask[None, :, :]

        grid_mesh = build_labeled_surface_mesh(
            effective_volume,
            material_id=effective_material_id,
            height_px=height_px,
            **({"z_edges": z_edges} if z_edges is not None else {}),
        )
        mesh = grid_mesh
        if mesh is not None:
            lattice_stats = (
                grid_mesh.metadata.get("layered_mesh_stats", {})
                if grid_mesh is not None
                else {}
            )
            if not isinstance(lattice_stats, dict):
                lattice_stats = {}
            lattice_patch_count = int(
                lattice_stats.get("merged_patch_count", 0)
            )
            patch_count = lattice_patch_count
            mesh.metadata["raster_surface_stats"] = {
                "patch_count": patch_count,
                "lattice_patch_count": lattice_patch_count,
                "boundary_rasterized": boundary_enabled,
                "boundary_enabled": boundary_enabled,
                "material_dilation_applied": not use_no_dilation,
            }
            log.info(
                "%s: built high-fidelity surface from %s patches",
                mesh_type,
                patch_count,
                extra={
                    "event": "high_fidelity_mesh_built",
                    "mesh_type": mesh_type,
                    "patch_count": patch_count,
                    "vertex_count": len(mesh.vertices),
                    "face_count": len(mesh.faces),
                },
            )
        return mesh

    def _merge_layers_with_dilation(self, voxel_matrix, mat_id):
        """
        Merge identical vertical layers and apply morphological dilation

        Groups consecutive Z-layers with identical masks to reduce geometry.
        Applies morphological dilation to ensure thin features are printable.

        Returns:
            list of tuples: [(start_z, end_z, dilated_mask), ...]
        """
        kernel = np.ones((3, 3), np.uint8)

        layer_groups = []
        prev_mask = None
        start_z = 0

        for z in range(voxel_matrix.shape[0]):
            curr_mask = voxel_matrix[z] == mat_id

            if not np.any(curr_mask):
                if prev_mask is not None and np.any(prev_mask):
                    layer_groups.append((start_z, z - 1, prev_mask))
                    prev_mask = None
                continue

            dilated_mask = _dilate_mask_preserving_enclosed_voids(curr_mask, kernel)

            if prev_mask is None:
                start_z = z
                prev_mask = dilated_mask.copy()
            elif np.array_equal(dilated_mask, prev_mask):
                pass
            else:
                layer_groups.append((start_z, z - 1, prev_mask))
                start_z = z
                prev_mask = dilated_mask.copy()

        if prev_mask is not None and np.any(prev_mask):
            layer_groups.append((start_z, voxel_matrix.shape[0] - 1, prev_mask))

        return layer_groups


# ========== Factory Method ==========


def get_mesher(
    mode_name: ModelingMode,
    disable_material_dilation: bool = False,
    boundary_geometry=None,
    *,
    boundary_shape: tuple[int, int] | None = None,
):
    """
    Return corresponding Mesher instance based on mode name

    Args:
        mode_name: ModelingMode enum value
            - ModelingMode.HIGH_FIDELITY → HighFidelityMesher
            - ModelingMode.PIXEL → VoxelMesher
            - ModelingMode.VECTOR → HighFidelityMesher (vector uses same algorithm)

    Returns:
        BaseMesher instance
    """
    # High-Fidelity mode (replaces Vector and Woodblock)
    if mode_name == ModelingMode.HIGH_FIDELITY:
        log.info(
            "Selected HighFidelityMesher",
            extra={
                "event": "mesher_selected",
                "mode": str(mode_name),
                "mesher": "HighFidelityMesher",
            },
        )
        return HighFidelityMesher(
            disable_material_dilation=disable_material_dilation,
            boundary_geometry=boundary_geometry,
            boundary_shape=boundary_shape,
        )

    # Vector mode uses same algorithm as High-Fidelity
    if mode_name == ModelingMode.VECTOR:
        log.info(
            "Selected HighFidelityMesher for vector mode",
            extra={
                "event": "mesher_selected",
                "mode": str(mode_name),
                "mesher": "HighFidelityMesher",
            },
        )
        return HighFidelityMesher(
            disable_material_dilation=disable_material_dilation,
            boundary_geometry=boundary_geometry,
            boundary_shape=boundary_shape,
        )

    # Pixel Art mode (legacy voxel)
    if mode_name == ModelingMode.PIXEL:
        log.info(
            "Selected VoxelMesher",
            extra={"event": "mesher_selected", "mode": str(mode_name), "mesher": "VoxelMesher"},
        )
        return VoxelMesher()

    # Default fallback to High-Fidelity
    log.info(
        "Unknown mode; defaulting to HighFidelityMesher",
        extra={
            "event": "mesher_defaulted",
            "mode": str(mode_name),
            "mesher": "HighFidelityMesher",
        },
    )
    return HighFidelityMesher(
        disable_material_dilation=disable_material_dilation,
        boundary_geometry=boundary_geometry,
        boundary_shape=boundary_shape,
    )
