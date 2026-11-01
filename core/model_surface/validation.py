from __future__ import annotations

import numpy as np
import trimesh

from core.model_surface.types import MODEL_SURFACE_FATAL_ERRORS, ModelSurfaceError

MODEL_SURFACE_MESH_NOT_WATERTIGHT = "model_surface_mesh_not_watertight"
MODEL_SURFACE_MESH_NOT_VOLUME = "model_surface_mesh_not_volume"
MODEL_SURFACE_EMPTY_GEOMETRY = "model_surface_empty_geometry"
MODEL_SURFACE_INVALID_FILE = "model_surface_invalid_file"
MODEL_SURFACE_THICKNESS_UNKNOWN = "model_surface_thickness_unknown"
MODEL_SURFACE_INSUFFICIENT_THICKNESS = "model_surface_insufficient_thickness"
MODEL_SURFACE_BOOLEAN_FAILED = "model_surface_boolean_failed"


def _retriangulate_collinear_faces(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Split the neighbor of a flat triangle at its existing middle vertex.

    Manifold can retain collinear faces at Boolean seams. Swapping their long
    edge preserves the surface, vertex positions and oriented outer boundary;
    deleting those faces independently would leave a hole or a T-junction.
    """
    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.faces).copy()
    pending = set(np.flatnonzero(mesh.area_faces == 0.0).tolist())
    while pending:
        progressed = False
        for index in sorted(pending):
            triangle = faces[index]
            points = vertices[triangle]
            edge_lengths = np.sum(
                (points - np.roll(points, -1, axis=0)) ** 2, axis=1,
            )
            edge = int(np.argmax(edge_lengths))
            first, second, middle = np.roll(triangle, -edge)
            neighbors = np.flatnonzero(
                np.any(faces == first, axis=1) & np.any(faces == second, axis=1)
            )
            if len(neighbors) != 2:
                raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED)
            neighbor = int(neighbors[0] if neighbors[1] == index else neighbors[1])
            if neighbor in pending:
                continue
            opposite = faces[neighbor][~np.isin(faces[neighbor], [first, second])]
            if len(opposite) != 1:
                raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED)
            tip = int(opposite[0])
            # An existing middle-to-tip edge would create a non-manifold seam.
            if np.any(
                np.any(faces == middle, axis=1) & np.any(faces == tip, axis=1)
            ):
                continue
            replacement = np.asarray([(second, middle, tip), (middle, first, tip)])
            triangles = vertices[replacement]
            normals = np.cross(
                triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0],
            )
            old = vertices[faces[neighbor]]
            old_normal = np.cross(old[1] - old[0], old[2] - old[0])
            if np.any(normals @ old_normal <= 0.0):
                continue
            faces[index], faces[neighbor] = replacement
            pending.remove(index)
            progressed = True
        if not progressed:
            raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED)
    return trimesh.Trimesh(vertices, faces, process=False)


def prepare_surface_base_for_export(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Finalize the Boolean base after every model/print transform.

    Quantize once to the writer's coordinates, then let Manifold contract
    collapsed edges while preserving the closed solid. Use Mesh64 for that
    topology operation, then retriangulate any remaining collinear seams.
    No independent triangle filtering or wider geometric tolerance is used.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float32).astype(np.float64)
    if not np.all(np.isfinite(vertices)):
        raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED)
    result = trimesh.Trimesh(vertices, mesh.faces, process=False)
    if np.any(result.area_faces == 0.0):
        try:
            import manifold3d as m3d

            solid = m3d.Manifold(m3d.Mesh64(
                vertices,
                np.asarray(mesh.faces, dtype=np.uint64),
            ))
            if solid.status() != m3d.Error.NoError or solid.is_empty():
                raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED)
            data = solid.to_mesh64()
            result = trimesh.Trimesh(
                np.asarray(data.vert_properties)[:, :3],
                np.asarray(data.tri_verts),
                process=False,
            )
        except ModelSurfaceError:
            raise
        except MODEL_SURFACE_FATAL_ERRORS:
            raise
        except Exception as exc:
            raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED) from exc

        if np.any(result.area_faces == 0.0):
            result = _retriangulate_collinear_faces(result)

    if (
        not np.array_equal(
            result.vertices, result.vertices.astype(np.float32).astype(np.float64),
        )
        or np.any(result.area_faces == 0.0)
    ):
        raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED)
    validate_model_surface_mesh_for_boolean(result)
    result.metadata.update(mesh.metadata)
    # The base has one material/color; its face count may change on contraction.
    result.visual.face_colors = mesh.visual.main_color
    return result


def validate_model_surface_mesh_for_boolean(mesh: trimesh.Trimesh) -> None:
    """Validate that a model-surface mesh is safe for solid booleans.

    验证模型覆面网格能否安全参与实体布尔运算。

    Args:
        mesh: Triangle mesh to validate.
            待验证的三角网格。

    Raises:
        ModelSurfaceError: If the mesh is open, empty, inconsistently wound,
            or does not represent a volume.
            当网格开放、为空、绕序不一致或不构成实体时抛出。
    """

    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ModelSurfaceError(MODEL_SURFACE_MESH_NOT_VOLUME)
    if not mesh.is_watertight:
        raise ModelSurfaceError(MODEL_SURFACE_MESH_NOT_WATERTIGHT)
    if not mesh.is_winding_consistent or not mesh.is_volume:
        raise ModelSurfaceError(MODEL_SURFACE_MESH_NOT_VOLUME)


def prepare_model_surface_mesh_for_boolean(
    mesh: trimesh.Trimesh,
    *,
    _take_ownership: bool = False,
) -> trimesh.Trimesh:
    """Return a validated single-volume mesh for model-surface booleans.

    返回经验证、可用于模型覆面布尔运算的单实体网格。

    Args:
        mesh: Source triangle mesh. Independent positive volumes are unioned;
            reversed inner shells are preserved as cavity geometry.
            源三角网格；独立正体积会合并，反向内壳则保留为空腔几何。
        _take_ownership: Internal opt-in allowing an already validated single
            body to be returned without a full array copy. 内部所有权转移开关；
            已验证的单实体可直接复用，避免完整数组复制。

    Returns:
        A copied or unioned volume mesh with source metadata preserved.
        保留源元数据的复制实体或合并实体。

    Raises:
        ModelSurfaceError: If validation or the safe union fails.
            当几何验证或安全合并失败时抛出。
    """

    validate_model_surface_mesh_for_boolean(mesh)
    if _take_ownership:
        try:
            if int(mesh.body_count) <= 1:
                return mesh
        except MODEL_SURFACE_FATAL_ERRORS:
            raise
        except (AttributeError, TypeError, ValueError):
            pass
    parts = list(mesh.split(only_watertight=True))
    if len(parts) <= 1:
        return mesh if _take_ownership else mesh.copy()
    if not all(part.is_volume for part in parts):
        return mesh if _take_ownership else mesh.copy()

    try:
        result = trimesh.boolean.union(parts, engine="manifold")
    except MODEL_SURFACE_FATAL_ERRORS:
        raise
    except Exception as exc:
        raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED) from exc
    if not isinstance(result, trimesh.Trimesh) or not result.is_volume:
        raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED)

    result.metadata.update(mesh.metadata or {})
    return result
