from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry
import trimesh

from config import PrinterConfig
from core.converter import build_image_model_context
from core.layered_coordinate_domain import (
    LayeredCoordinateDomain,
    certify_layered_pattern_scene,
    read_layered_coordinate_domain,
)
from core.vector_layer_geometry import (
    resolve_vector_writer_grid_mm,
)
from core.model_surface.assembly import (
    MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY,
    MODEL_SURFACE_DISPLAY_Z_BOUNDS_KEY,
    MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY,
    MODEL_SURFACE_PROJECT_SLOT_NAMES_KEY,
    OverlaySceneResult,
    PreparedSurfacePattern,
    apply_model_transform_to_overlay_scene,
    build_embedded_overlay_scene,
    orient_overlay_scene_for_print,
)
from core.model_surface.loader import load_model_surface_mesh
from core.model_surface.slot_meshing import (
    build_printable_footprint_from_voxels,
    build_slot_surface_scene_from_voxels,
)
from core.model_surface.types import (
    MODEL_SURFACE_ARTWORK_NO_OVERLAP,
    MODEL_SURFACE_FATAL_ERRORS,
    ModelSurfaceError,
    SurfaceFootprint,
)
from core.model_surface.validation import prepare_surface_base_for_export
from core.pipeline.preview_color_utils import resolve_material_preview


# Shapely materializes one Polygon object per upward cap triangle before its
# union. Independent RSS probes reached 26.811x the retained scene arrays, so
# keep a conservative, stage-specific margin instead of reusing the writer's
# much smaller workspace factor.


def build_surface_overlay_scene(
    *,
    model_path: str,
    artwork_image_path: str,
    lut_path: str,
    converter_params: dict,
    footprint: SurfaceFootprint,
    pocket_depth_mm: float,
    model_transform: dict | None = None,
) -> OverlaySceneResult:
    """Build a model-surface overlay scene by reusing the image converter.

    复用图片转换器构建模型覆面装配场景。
    """

    loaded = load_model_surface_mesh(model_path)
    surface_converter_params = dict(converter_params)
    surface_converter_params["structure_mode"] = "Single-sided"
    ctx = build_image_model_context(
        stop_after_step="S08",
        image_path=artwork_image_path,
        lut_path=lut_path,
        **surface_converter_params,
    )
    if ctx.get("error"):
        raise ModelSurfaceError(str(ctx["error"]))
    face_orientation = str(ctx.get("bambu_face_orientation", "down") or "down")
    base_color = (245, 245, 245)
    project_materials: dict[str, tuple[int, int, int]] = {}
    project_slot_names: tuple[str, ...] = ()
    if ctx.get("material_source") == "material_archive":
        project_slot_names = tuple(ctx["slot_names"])
        backing_index = ctx.get("material_backing_material_index")
        if backing_index is None:
            backing_index = ctx.get("material_base_channel_idx", 0)
        styles = [resolve_material_preview(
            material_id=index,
            slot_names=ctx["slot_names"],
            preview_colors=ctx.get("preview_colors"),
            color_conf=ctx.get("color_conf"),
        ) for index in range(len(ctx["slot_names"]))]
        base_style = styles[int(backing_index)]
        if not base_style.is_resolved:
            raise ModelSurfaceError("Converter did not resolve the surface backing material.")
        loaded.mesh.metadata["bambu_material_name"] = base_style.material_name
        base_color = base_style.rgba[:3]
        project_materials = {
            style.material_name: style.rgba[:3]
            for style in styles if style.is_resolved
        }
    pattern_scene = _build_pattern_scene(
        ctx,
        _take_vector_scene_ownership=True,
    )
    material_types = dict(ctx.get("material_types") or {})
    material_types["surface_base"] = "PLA Basic"
    # This context is private to the model-surface request. Pattern building
    # has either transferred the native mesh arrays or materialized the voxel
    # pattern, so retaining converter analysis/cache state only inflates peak
    # RSS during the boolean and writer stages.
    ctx.clear()
    if len(pattern_scene.geometry) == 0:
        raise ModelSurfaceError("Converter did not produce an overlay pattern scene.")
    overlay = build_embedded_overlay_scene(
        base_mesh=loaded.mesh,
        pattern_scene=pattern_scene,
        footprint=footprint,
        pocket_depth_mm=pocket_depth_mm,
        base_slot_name="surface_base",
        base_color=base_color,
        _take_pattern_ownership=True,
    )
    overlay.scene.metadata["material_types"] = material_types
    if project_slot_names:
        overlay.scene.metadata[MODEL_SURFACE_PROJECT_SLOT_NAMES_KEY] = project_slot_names
        overlay.preview_colors.update(project_materials)
    transformed_overlay = apply_model_transform_to_overlay_scene(
        overlay,
        model_transform,
        _copy_scene=False,
    )
    print_overlay = orient_overlay_scene_for_print(
        transformed_overlay,
        face_orientation,
        _copy_scene=False,
    )
    print_overlay.scene.geometry["surface_base"] = prepare_surface_base_for_export(
        print_overlay.scene.geometry["surface_base"],
    )
    return print_overlay


def _build_pattern_scene(
    ctx: dict,
    *,
    _take_vector_scene_ownership: bool = False,
) -> PreparedSurfacePattern:
    if ctx.get("is_svg_vector"):
        return _build_vector_pattern_scene(
            ctx,
            _take_scene_ownership=_take_vector_scene_ownership,
        )

    full_matrix = ctx.get("full_matrix")
    slot_names = ctx.get("slot_names")
    preview_colors = ctx.get("preview_colors")
    target_h = ctx.get("target_h")
    pixel_scale = ctx.get("pixel_scale")
    if (
        full_matrix is not None
        and slot_names is not None
        and preview_colors is not None
        and target_h is not None
        and pixel_scale is not None
    ):
        pattern_matrix, layer_heights_mm = _resolve_surface_display_stack(
            ctx,
            np.asarray(full_matrix),
        )
        pattern_scene = build_slot_surface_scene_from_voxels(
            full_matrix=pattern_matrix,
            slot_names=slot_names,
            preview_colors=preview_colors,
            target_h=int(target_h),
            pixel_scale=float(pixel_scale),
            layer_heights_mm=layer_heights_mm,
        )
        domain = LayeredCoordinateDomain.from_canvas_and_layers(
            width_mm=float(pattern_matrix.shape[2]) * float(pixel_scale),
            height_mm=float(target_h) * float(pixel_scale),
            xy_grid_mm=float(pixel_scale),
            layer_heights_mm=layer_heights_mm,
        )
        _certify_surface_pattern_scene(pattern_scene, domain)
        printable_footprint = build_printable_footprint_from_voxels(
            full_matrix=pattern_matrix,
            material_count=len(slot_names),
            target_h=int(target_h),
            pixel_scale=float(pixel_scale),
        )
        return PreparedSurfacePattern(
            scene=pattern_scene,
            printable_footprint=printable_footprint,
        )
    raise ModelSurfaceError("Converter did not produce a display voxel stack.")


def _build_vector_pattern_scene(
    ctx: dict,
    *,
    _take_scene_ownership: bool = False,
) -> PreparedSurfacePattern:
    """Extract native vector color layers for model-surface assembly."""

    if _take_scene_ownership:
        source_scene = ctx.pop("scene", None)
        analysis = ctx.pop("vector_analysis", None)
    else:
        source_scene = ctx.get("scene")
        analysis = ctx.get("vector_analysis")
    if not isinstance(source_scene, trimesh.Scene) or analysis is None:
        raise ModelSurfaceError(
            "Converter did not produce a native vector pattern scene."
        )

    pattern_scene = trimesh.Scene()
    for raw_name in getattr(analysis, "slot_names", ()) or ():
        name = str(raw_name)
        mesh = source_scene.geometry.get(name)
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            continue
        pattern_scene.add_geometry(
            mesh if _take_scene_ownership else mesh.copy(),
            node_name=name,
            geom_name=name,
        )
    if len(pattern_scene.geometry) == 0:
        raise ModelSurfaceError(
            "Converter did not produce native vector color layers."
        )

    try:
        bbox = tuple(float(value) for value in analysis.bbox)
        scale_factor = float(analysis.scale_factor)
        layer_count = int(analysis.num_layers)
        layer_height_mm = float(
            ctx.get("layer_height_mm") or PrinterConfig.LAYER_HEIGHT
        )
    except (TypeError, ValueError) as exc:
        raise ModelSurfaceError(
            "Converter produced invalid native vector pattern metadata."
        ) from exc
    if (
        len(bbox) < 4
        or not np.all(np.isfinite(bbox[:4]))
        or not np.isfinite(scale_factor)
        or scale_factor <= 0.0
        or layer_count <= 0
        or not np.isfinite(layer_height_mm)
        or layer_height_mm <= 0.0
    ):
        raise ModelSurfaceError(
            "Converter produced invalid native vector pattern metadata."
        )

    coordinate_domain = getattr(analysis, "coordinate_domain", None)
    if coordinate_domain is not None and not isinstance(
        coordinate_domain,
        LayeredCoordinateDomain,
    ):
        raise ModelSurfaceError(
            "Converter produced invalid native vector coordinate metadata."
        )
    if coordinate_domain is None:
        try:
            coordinate_domain = read_layered_coordinate_domain(source_scene)
        except ValueError as exc:
            raise ModelSurfaceError(
                "Converter produced invalid native vector coordinate metadata."
            ) from exc
    if coordinate_domain is None:
        logical_width_mm = bbox[2] * scale_factor
        logical_height_mm = bbox[3] * scale_factor
        if logical_width_mm <= 0.0 or logical_height_mm <= 0.0:
            raise ModelSurfaceError(
                "Converter produced an invalid native vector canvas."
            )
        vector_grid_mm = resolve_vector_writer_grid_mm(
            max(abs(logical_width_mm), abs(logical_height_mm)),
        )
        coordinate_domain = LayeredCoordinateDomain.from_canvas_and_layers(
            width_mm=logical_width_mm,
            height_mm=logical_height_mm,
            xy_grid_mm=vector_grid_mm,
            layer_heights_mm=(layer_height_mm,) * layer_count,
        )
    if len(coordinate_domain.layer_heights_mm) != layer_count:
        raise ModelSurfaceError(
            "Converter vector layer schedule does not match its coordinate domain."
        )

    logical_bounds = coordinate_domain.writer_canvas_bounds_mm

    pattern_bounds = np.asarray(pattern_scene.bounds, dtype=np.float64)
    face_orientation = str(
        ctx.get("bambu_face_orientation", "down") or "down"
    ).lower()
    if face_orientation == "down":
        # The native vector engine has already prepared its single-sided
        # scene for direct face-down export. Normalize it back to a face-up
        # local pattern before embedding; the assembled model receives the
        # final rigid face-down rotation as one unit. Vector export now keeps
        # its X/Y placement out of mesh vertices, so both axes live in the
        # negative local quadrant here. Restore the historical model-surface
        # canvas without changing the standalone 3MF writer-domain contract.
        normalize_for_embedding = np.asarray(
            [
                [-1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, logical_bounds[3]],
                [0.0, 0.0, -1.0, pattern_bounds[0, 2] + pattern_bounds[1, 2]],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        for geometry in pattern_scene.geometry.values():
            if isinstance(geometry, trimesh.Trimesh):
                geometry.apply_transform(normalize_for_embedding)
        pattern_bounds = np.asarray(pattern_scene.bounds, dtype=np.float64)
    elif face_orientation == "up":
        # Up-facing vector scenes still use the translation-free SVG Y flip.
        # Bring that local negative Y canvas back to the model-surface frame.
        normalize_for_embedding = np.eye(4, dtype=np.float64)
        normalize_for_embedding[1, 3] = logical_bounds[3]
        normalize_for_embedding[2, 3] = -float(pattern_bounds[0, 2])
        for geometry in pattern_scene.geometry.values():
            if isinstance(geometry, trimesh.Trimesh):
                geometry.apply_transform(normalize_for_embedding)
        pattern_bounds = np.asarray(pattern_scene.bounds, dtype=np.float64)
    else:
        raise ModelSurfaceError(
            "Model-surface overlay requires a single display face."
        )

    _certify_surface_pattern_scene(pattern_scene, coordinate_domain)
    printable_footprint = _build_scene_printable_footprint(pattern_scene)
    return PreparedSurfacePattern(
        scene=pattern_scene,
        printable_footprint=printable_footprint,
    )


def _certify_surface_pattern_scene(
    pattern_scene: trimesh.Scene,
    domain: LayeredCoordinateDomain,
) -> None:
    """Publish compatibility metadata and certify one canonical pattern."""

    if not pattern_scene.geometry:
        raise ModelSurfaceError(MODEL_SURFACE_ARTWORK_NO_OVERLAP)
    pattern_scene.metadata[MODEL_SURFACE_DISPLAY_Z_BOUNDS_KEY] = (
        domain.writer_z_bounds_mm
    )
    pattern_scene.metadata[MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY] = (
        domain.layer_heights_mm
    )
    pattern_scene.metadata[MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY] = (
        domain.writer_canvas_bounds_mm
    )
    try:
        certify_layered_pattern_scene(pattern_scene, domain)
    except ValueError as exc:
        raise ModelSurfaceError(str(exc)) from exc


def _build_scene_printable_footprint(
    pattern_scene: trimesh.Scene,
) -> BaseGeometry:
    """Project the final printable vector meshes into an exact XY footprint."""

    slot_footprints = []
    try:
        for mesh in pattern_scene.geometry.values():
            if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
                continue
            triangles = np.asarray(mesh.triangles, dtype=np.float64)
            upward_caps = np.asarray(mesh.face_normals)[:, 2] > 1.0 - 1e-7
            cap_triangles = triangles[upward_caps]
            if len(cap_triangles) == 0:
                continue
            edge_a = cap_triangles[:, 1, :2] - cap_triangles[:, 0, :2]
            edge_b = cap_triangles[:, 2, :2] - cap_triangles[:, 0, :2]
            twice_area = (
                edge_a[:, 0] * edge_b[:, 1]
                - edge_a[:, 1] * edge_b[:, 0]
            )
            cap_triangles = cap_triangles[np.abs(twice_area) > 1e-12]
            if len(cap_triangles) == 0:
                continue
            triangle_polygons = shapely.polygons(cap_triangles[:, :, :2])
            slot_footprint = shapely.union_all(triangle_polygons)
            if not slot_footprint.is_empty:
                slot_footprints.append(slot_footprint)
        footprint = shapely.union_all(slot_footprints)
    except MODEL_SURFACE_FATAL_ERRORS:
        raise
    except Exception as exc:
        raise ModelSurfaceError(
            "Converter produced an invalid native vector footprint."
        ) from exc
    if (
        not slot_footprints
        or footprint.is_empty
        or not np.isfinite(float(footprint.area))
        or footprint.area <= 0.0
    ):
        raise ModelSurfaceError(
            "Converter did not produce a printable native vector footprint."
        )
    return footprint


def _resolve_surface_display_stack(
    ctx: dict,
    full_matrix: np.ndarray,
) -> tuple[np.ndarray, tuple[float, ...]]:
    """Return display voxels with embedded Z order and standard print orientation.

    返回按嵌入方向排列并保持标准打印朝向的纯展示体素。
    """

    if full_matrix.ndim != 3:
        raise ModelSurfaceError("Converter produced an invalid voxel matrix.")

    material_matrix = ctx.get("material_matrix")
    if isinstance(material_matrix, np.ndarray) and material_matrix.ndim == 3:
        display_layer_count = int(material_matrix.shape[2])
    else:
        try:
            display_layer_count = int(ctx.get("color_layers"))
        except (TypeError, ValueError) as exc:
            raise ModelSurfaceError("Converter did not report display layer count.") from exc
    if display_layer_count <= 0 or display_layer_count > full_matrix.shape[0]:
        raise ModelSurfaceError("Converter produced an invalid display layer count.")

    canonical_heights_raw = ctx.get("display_layer_heights_mm")
    if canonical_heights_raw is None:
        uniform_height_raw = ctx.get("layer_height_mm")
        if uniform_height_raw is None:
            uniform_height_raw = PrinterConfig.LAYER_HEIGHT
        try:
            uniform_height_mm = float(uniform_height_raw)
        except (TypeError, ValueError) as exc:
            raise ModelSurfaceError("Converter produced an invalid display layer height.") from exc
        canonical_heights = np.full(
            display_layer_count,
            uniform_height_mm,
            dtype=np.float64,
        )
    else:
        try:
            canonical_heights = np.asarray(
                canonical_heights_raw,
                dtype=np.float64,
            )
        except (TypeError, ValueError) as exc:
            raise ModelSurfaceError("Converter produced invalid display layer heights.") from exc

    if canonical_heights.shape != (display_layer_count,):
        raise ModelSurfaceError("Converter display layer heights do not match its layer count.")
    if not np.all(np.isfinite(canonical_heights)) or np.any(canonical_heights <= 0.0):
        raise ModelSurfaceError("Converter display layer heights must be positive and finite.")

    face_orientation = str(ctx.get("bambu_face_orientation", "down") or "down").lower()
    if ctx.get("voxel_z_edges") is not None:
        from core.layered_z import validate_layer_z_edges

        edges = validate_layer_z_edges(ctx["voxel_z_edges"], full_matrix.shape[0])
        widths = np.diff(edges)
        display_widths = (
            widths[:display_layer_count] if face_orientation == "down" else widths[-display_layer_count:]
        )
        if np.any(display_widths != 1):
            raise ModelSurfaceError("Converter display layers must retain their individual Z intervals.")
    if face_orientation == "down":
        # Reverse only the display stack so its viewing layer faces outward
        # while the pattern is embedded. The final rigid rotation of the
        # assembled model supplies the print-time X mirror.
        display_matrix = np.flip(full_matrix[:display_layer_count], axis=0)
    elif face_orientation == "up":
        display_matrix = full_matrix[-display_layer_count:]
    else:
        raise ModelSurfaceError("Model-surface overlay requires a single display face.")

    return (
        np.ascontiguousarray(display_matrix),
        tuple(float(value) for value in canonical_heights[::-1]),
    )
