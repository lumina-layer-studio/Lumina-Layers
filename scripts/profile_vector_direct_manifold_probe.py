"""Probe direct Shapely-polygon -> manifold3d extrusion for vector GLB V2.

This script is diagnostic only. It builds the same V2 color descriptors used
by the SVG GLB exporter, then compares the current rasterize/polygonize V2
mesh path with a candidate direct-polygon manifold path.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import trimesh
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_LUT_PATH = ROOT / "tests/fixtures/lut_regression" / "彩多屋" / "4色" / "RYBW" / "lumina_lut.json"


def _iter_polygons(geometry: BaseGeometry) -> Iterable[Polygon]:
    try:
        geom = make_valid(geometry) if not geometry.is_valid else geometry
    except (AttributeError, ValueError, TypeError):
        return
    if geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
        return
    if isinstance(geom, MultiPolygon):
        for polygon in geom.geoms:
            if not polygon.is_empty:
                yield polygon
        return
    if isinstance(geom, GeometryCollection):
        for child in geom.geoms:
            yield from _iter_polygons(child)


def _ring_coords(ring: object) -> np.ndarray | None:
    coords = np.asarray(ring.coords, dtype=np.float64)
    if len(coords) >= 2 and np.allclose(coords[0], coords[-1]):
        coords = coords[:-1]
    if len(coords) < 3:
        return None
    return coords[:, :2]


def _polygon_contours(polygon: Polygon) -> list[np.ndarray]:
    exterior = _ring_coords(polygon.exterior)
    if exterior is None:
        return []
    contours = [exterior]
    for interior in polygon.interiors:
        hole = _ring_coords(interior)
        if hole is not None:
            contours.append(hole)
    return contours


def _direct_manifold_mesh(extrusion: Any) -> trimesh.Trimesh:
    import manifold3d as m3d

    z_height = float(extrusion.z_max) - float(extrusion.z_min)
    if z_height <= 0.0:
        raise RuntimeError("non-positive extrusion height")

    manifolds = []
    for footprint in extrusion.footprints:
        for polygon in _iter_polygons(footprint):
            contours = _polygon_contours(polygon)
            if not contours:
                continue
            section = m3d.CrossSection(contours, m3d.FillRule.EvenOdd)
            manifold = section.extrude(z_height)
            if not manifold.is_empty():
                manifolds.append(manifold)
    if not manifolds:
        raise RuntimeError("direct manifold path produced no manifolds")

    combined = m3d.Manifold.compose(manifolds)
    mesh_data = combined.to_mesh()
    vertices = np.asarray(mesh_data.vert_properties, dtype=np.float64)
    faces = np.asarray(mesh_data.tri_verts, dtype=np.int64)
    if vertices.size == 0 or faces.size == 0:
        raise RuntimeError("direct manifold path produced an empty mesh")
    if vertices.shape[1] > 3:
        vertices = vertices[:, :3]
    vertices = vertices.copy()
    vertices[:, 2] += float(extrusion.z_min)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def _mesh_summary(mesh: trimesh.Trimesh) -> dict[str, Any]:
    bounds = np.asarray(mesh.bounds, dtype=float)
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "bounds": bounds.tolist(),
        "volume": abs(float(mesh.volume)),
    }


def _compare_meshes(current: trimesh.Trimesh, direct: trimesh.Trimesh) -> dict[str, Any]:
    current_summary = _mesh_summary(current)
    direct_summary = _mesh_summary(direct)
    current_bounds = np.asarray(current_summary["bounds"], dtype=float)
    direct_bounds = np.asarray(direct_summary["bounds"], dtype=float)
    current_volume = float(current_summary["volume"])
    direct_volume = float(direct_summary["volume"])
    return {
        "current": current_summary,
        "direct": direct_summary,
        "bounds_max_abs_diff": float(np.max(np.abs(current_bounds - direct_bounds))),
        "volume_abs_diff": abs(current_volume - direct_volume),
        "volume_rel_diff": (
            abs(current_volume - direct_volume) / current_volume
            if current_volume > 0.0
            else 0.0
        ),
    }


def _build_color_extrusions(svg_path: Path, lut_path: Path, target_width_mm: float) -> list[Any]:
    from config import ModelingMode
    from core.pipeline.vector_branch import _build_vector_processor
    from core.pipeline import vector_glb_preview

    ctx = {
        "image_path": str(svg_path),
        "actual_lut_path": str(lut_path),
        "color_mode": "4-Color",
        "modeling_mode": ModelingMode.VECTOR,
        "target_width_mm": target_width_mm,
        "spacer_thick": 1.6,
        "structure_mode": "Single-sided",
    }
    processor = _build_vector_processor(ctx, fallback_color_mode="4-Color")
    analysis = processor.analyze_svg(
        svg_path=str(svg_path),
        target_width_mm=target_width_mm,
        color_replacements=None,
    )
    parts = vector_glb_preview.build_vector_preview_parts_from_analysis(
        analysis=analysis,
        preview_colors=dict(analysis.preview_colors),
        slot_list=list(analysis.slot_names),
        structure_mode="Single-sided",
        color_mode="4-Color",
        thickness_mm=1.6,
        separate_backing=False,
        include_backing=False,
        include_outline=False,
        outline_width_mm=2.0,
    )
    extrusions = []
    for part in parts:
        if part.role != "color":
            continue
        extrusions.extend(vector_glb_preview._batch_part_extrusions_for_v2(part))
    return extrusions


def main() -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("svg", type=Path)
    parser.add_argument("--lut", type=Path, default=DEFAULT_LUT_PATH)
    parser.add_argument("--target-width-mm", type=float, default=80.0)
    parser.add_argument("--pixels-per-mm", type=float, default=10.0)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    if not args.svg.exists():
        raise FileNotFoundError(f"SVG not found: {args.svg}")
    if not args.lut.exists():
        raise FileNotFoundError(f"LUT not found: {args.lut}")

    from core.pipeline import vector_glb_preview

    build_started = time.perf_counter()
    extrusions = _build_color_extrusions(args.svg, args.lut, args.target_width_mm)
    build_elapsed = time.perf_counter() - build_started

    rows: list[dict[str, Any]] = []
    current_total = 0.0
    direct_total = 0.0
    for index, extrusion in enumerate(extrusions):
        current_started = time.perf_counter()
        current = vector_glb_preview._mesh_from_extrusion_v2(
            extrusion,
            rgba=(255, 0, 0, 255),
            pixels_per_mm=args.pixels_per_mm,
        )
        current_elapsed = time.perf_counter() - current_started
        direct_started = time.perf_counter()
        direct = _direct_manifold_mesh(extrusion)
        direct_elapsed = time.perf_counter() - direct_started
        current_total += current_elapsed
        direct_total += direct_elapsed
        row = _compare_meshes(current, direct)
        row.update(
            {
                "index": index,
                "z_min": float(extrusion.z_min),
                "z_max": float(extrusion.z_max),
                "footprint_count": len(extrusion.footprints),
                "current_elapsed_s": current_elapsed,
                "direct_elapsed_s": direct_elapsed,
            }
        )
        rows.append(row)

    summary = {
        "svg": str(args.svg),
        "target_width_mm": args.target_width_mm,
        "pixels_per_mm": args.pixels_per_mm,
        "descriptor_build_s": build_elapsed,
        "extrusion_count": len(rows),
        "current_total_s": current_total,
        "direct_total_s": direct_total,
        "speedup": current_total / direct_total if direct_total > 0.0 else None,
        "max_bounds_abs_diff": max((row["bounds_max_abs_diff"] for row in rows), default=0.0),
        "max_volume_rel_diff": max((row["volume_rel_diff"] for row in rows), default=0.0),
        "max_volume_abs_diff": max((row["volume_abs_diff"] for row in rows), default=0.0),
        "rows": rows,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
