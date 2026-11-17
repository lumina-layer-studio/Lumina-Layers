"""Profile SVG fast-union parity and vector GLB exporter hotspots."""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import os
import pstats
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_LUT_PATH = ROOT / "tests/fixtures/lut_regression" / "彩多屋" / "4色" / "RYBW" / "lumina_lut.json"
DEFAULT_SVGS: list[Path] = []


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_zip_member(path: Path, member: str) -> str | None:
    digest = hashlib.sha256()
    with ZipFile(path) as archive:
        if member not in archive.namelist():
            return None
        with archive.open(member) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _round_float(value: object, digits: int = 6) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return round(number, digits)


def _round_array(values: object, digits: int = 6) -> list:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return []
    return np.round(arr, digits).tolist()


def _summarize_glb(path: str | None) -> dict[str, object] | None:
    if not path:
        return None
    glb_path = Path(path)
    if not glb_path.exists():
        return {"path": str(glb_path), "exists": False}

    import trimesh

    started = time.perf_counter()
    scene = trimesh.load(str(glb_path), force="scene")
    load_s = time.perf_counter() - started
    geometry_rows = []
    total_vertices = 0
    total_faces = 0
    for name, geometry in sorted(scene.geometry.items(), key=lambda item: str(item[0])):
        vertices = getattr(geometry, "vertices", [])
        faces = getattr(geometry, "faces", [])
        vertex_count = int(len(vertices))
        face_count = int(len(faces))
        total_vertices += vertex_count
        total_faces += face_count
        bounds = getattr(geometry, "bounds", None)
        geometry_rows.append(
            {
                "name": str(name),
                "vertices": vertex_count,
                "faces": face_count,
                "bounds": _round_array(bounds),
                "volume": _round_float(getattr(geometry, "volume", None)),
                "area": _round_float(getattr(geometry, "area", None)),
            }
        )
    return {
        "path": str(glb_path),
        "exists": True,
        "bytes": glb_path.stat().st_size,
        "sha256": _sha256_file(glb_path),
        "load_s": round(load_s, 6),
        "geometry_count": len(geometry_rows),
        "total_vertices": total_vertices,
        "total_faces": total_faces,
        "geometry": geometry_rows,
    }


def _summarize_3mf(path: str | None) -> dict[str, object] | None:
    if not path:
        return None
    threemf_path = Path(path)
    if not threemf_path.exists():
        return {"path": str(threemf_path), "exists": False}

    object_member = "3D/Objects/object_1.model"
    objects: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    current_min: list[float] | None = None
    current_max: list[float] | None = None
    started = time.perf_counter()
    with ZipFile(threemf_path) as archive:
        with archive.open(object_member) as handle:
            for event, elem in ET.iterparse(handle, events=("start", "end")):
                tag = _local_name(elem.tag)
                if event == "start" and tag == "object":
                    current = {
                        "id": elem.attrib.get("id"),
                        "name": elem.attrib.get("name"),
                        "pid": elem.attrib.get("pid"),
                        "pindex": elem.attrib.get("pindex"),
                        "vertices": 0,
                        "triangles": 0,
                    }
                    current_min = [float("inf"), float("inf"), float("inf")]
                    current_max = [float("-inf"), float("-inf"), float("-inf")]
                elif event == "end" and current is not None and tag == "vertex":
                    try:
                        coords = [
                            float(elem.attrib.get("x", 0.0)),
                            float(elem.attrib.get("y", 0.0)),
                            float(elem.attrib.get("z", 0.0)),
                        ]
                    except (TypeError, ValueError):
                        coords = [0.0, 0.0, 0.0]
                    current["vertices"] = int(current["vertices"]) + 1
                    assert current_min is not None and current_max is not None
                    for idx, value in enumerate(coords):
                        current_min[idx] = min(current_min[idx], value)
                        current_max[idx] = max(current_max[idx], value)
                elif event == "end" and current is not None and tag == "triangle":
                    current["triangles"] = int(current["triangles"]) + 1
                elif event == "end" and current is not None and tag == "object":
                    assert current_min is not None and current_max is not None
                    if int(current["vertices"]) > 0:
                        current["bounds"] = [
                            [round(value, 6) for value in current_min],
                            [round(value, 6) for value in current_max],
                        ]
                    else:
                        current["bounds"] = []
                    objects.append(current)
                    current = None
                    current_min = None
                    current_max = None
                if event == "end":
                    elem.clear()
    parse_s = time.perf_counter() - started
    return {
        "path": str(threemf_path),
        "exists": True,
        "bytes": threemf_path.stat().st_size,
        "object_model_sha256": _sha256_zip_member(threemf_path, object_member),
        "parse_s": round(parse_s, 6),
        "object_count": len(objects),
        "total_vertices": int(sum(int(obj["vertices"]) for obj in objects)),
        "total_triangles": int(sum(int(obj["triangles"]) for obj in objects)),
        "objects": objects,
    }


def _profile_summary(profile: cProfile.Profile, limit: int = 80) -> dict[str, object]:
    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumtime")
    stats.print_stats(limit)
    selected_needles = (
        "_run_length_extrude",
        "_union_run_group_geometries",
        "build_vector_layered_volume",
        "_extrude_indexed_run_group",
        "build_labeled_surface_mesh",
        "_normalize_contours",
        "polygonize",
        "buffer",
        "set_precision",
        "unary_union",
        "union_all",
        "disjoint_subset_union_all",
        "export_vector_glb_preview",
        "export_vector_glb_preview_v2",
        "build_vector_preview_parts_from_analysis",
        "_batch_part_extrusions_for_v2",
        "_mesh_from_extrusion_v2",
        "_build_color_extruded_mesh_v2",
        "rasterize",
        "_write_glb_scene",
        "concatenate",
    )
    selected = []
    for (filename, line, func), stat in stats.stats.items():
        ccalls, ncalls, tottime, cumtime, _callers = stat
        label = f"{Path(filename).name}:{line}:{func}"
        if any(needle in func or needle in label for needle in selected_needles):
            selected.append(
                {
                    "function": label,
                    "primitive_calls": ccalls,
                    "calls": ncalls,
                    "tottime_s": round(tottime, 6),
                    "cumtime_s": round(cumtime, 6),
                }
            )
    selected.sort(key=lambda item: float(item["cumtime_s"]), reverse=True)
    return {
        "top_cumtime": stream.getvalue(),
        "selected": selected[:80],
    }


def _base_ctx(svg_path: Path, lut_path: Path) -> dict[str, object]:
    from config import ModelingMode

    return {
        "image_path": str(svg_path),
        "actual_lut_path": str(lut_path),
        "color_mode": "4-Color",
        "modeling_mode": ModelingMode.VECTOR,
        "target_width_mm": 80.0,
        "spacer_thick": 1.6,
        "structure_mode": "Single-sided",
        "need_2d_preview": False,
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
    }


def _clear_vector_cache() -> None:
    import core.vector_engine as vector_engine

    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()


def _run_vector_branch(
    *,
    svg_path: Path,
    lut_path: Path,
    kernel: str,
    union_mode: str,
    profile: bool = False,
    profile_export_dispatch: bool = False,
) -> dict[str, object]:
    from core.pipeline import coordinator, vector_glb_preview
    import core.vector_engine as vector_engine

    original_fast_union = vector_engine.disjoint_subset_union_all
    original_export_dispatch = vector_glb_preview.export_vector_glb_preview
    original_export_v1 = vector_glb_preview.export_vector_glb_preview_v1
    original_export_v2 = vector_glb_preview.export_vector_glb_preview_v2

    export_profile: cProfile.Profile | None = None
    export_call_state = {
        "dispatch_called": 0,
        "v1_called": 0,
        "v2_called": 0,
    }

    def wrapped_export_dispatch(*args, **kwargs):
        export_call_state["dispatch_called"] += 1
        assert export_profile is not None
        export_profile.enable()
        try:
            return original_export_dispatch(*args, **kwargs)
        finally:
            export_profile.disable()

    def wrapped_export_v1(*args, **kwargs):
        export_call_state["v1_called"] += 1
        return original_export_v1(*args, **kwargs)

    def wrapped_export_v2(*args, **kwargs):
        export_call_state["v2_called"] += 1
        return original_export_v2(*args, **kwargs)

    try:
        if union_mode == "fallback":
            vector_engine.disjoint_subset_union_all = None
        elif union_mode != "fast":
            raise ValueError(f"Unknown union mode: {union_mode}")

        if profile_export_dispatch:
            export_profile = cProfile.Profile()
            vector_glb_preview.export_vector_glb_preview = wrapped_export_dispatch
            vector_glb_preview.export_vector_glb_preview_v1 = wrapped_export_v1
            vector_glb_preview.export_vector_glb_preview_v2 = wrapped_export_v2

        os.environ["LUMINA_VECTOR_GLB_KERNEL"] = kernel
        os.environ["LUMINA_VECTOR_SKIP_2D_PREVIEW"] = "1"
        _clear_vector_cache()
        ctx = _base_ctx(svg_path, lut_path)
        run_profile = cProfile.Profile() if profile else None
        started = time.perf_counter()
        if run_profile is not None:
            run_profile.enable()
        try:
            result = coordinator._run_vector_branch(ctx)
        finally:
            if run_profile is not None:
                run_profile.disable()
        elapsed_s = time.perf_counter() - started

        result_tuple = result.get("result_tuple") or ()
        threemf_path = result_tuple[0] if len(result_tuple) > 0 else None
        glb_path = result_tuple[1] if len(result_tuple) > 1 else None
        row: dict[str, object] = {
            "svg": str(svg_path),
            "kernel": kernel,
            "union_mode": union_mode,
            "elapsed_s": round(elapsed_s, 6),
            "error": result.get("error"),
            "timings": result.get("vector_timing") or {},
            "threemf_path": threemf_path,
            "glb_path": glb_path,
            "glb_summary": _summarize_glb(glb_path),
            "threemf_summary": _summarize_3mf(threemf_path),
        }
        if run_profile is not None:
            row["profile"] = _profile_summary(run_profile)
        if export_profile is not None:
            row["export_profile"] = _profile_summary(export_profile)
            row["export_call_state"] = export_call_state
        return row
    finally:
        vector_engine.disjoint_subset_union_all = original_fast_union
        vector_glb_preview.export_vector_glb_preview = original_export_dispatch
        vector_glb_preview.export_vector_glb_preview_v1 = original_export_v1
        vector_glb_preview.export_vector_glb_preview_v2 = original_export_v2


def _max_abs_bounds_diff(left: list | None, right: list | None) -> float | None:
    if not left or not right:
        return None
    left_arr = np.asarray(left, dtype=float)
    right_arr = np.asarray(right, dtype=float)
    if left_arr.shape != right_arr.shape:
        return None
    return round(float(np.max(np.abs(left_arr - right_arr))), 9)


def _compare_named_rows(
    left_rows: list[dict[str, object]],
    right_rows: list[dict[str, object]],
    *,
    name_key: str,
    face_key: str,
) -> dict[str, object]:
    left_map = {str(row.get(name_key)): row for row in left_rows}
    right_map = {str(row.get(name_key)): row for row in right_rows}
    names_match = sorted(left_map) == sorted(right_map)
    row_diffs = []
    for name in sorted(set(left_map) & set(right_map)):
        left = left_map[name]
        right = right_map[name]
        row_diffs.append(
            {
                "name": name,
                "vertices_delta": int(right.get("vertices", 0)) - int(left.get("vertices", 0)),
                f"{face_key}_delta": int(right.get(face_key, 0)) - int(left.get(face_key, 0)),
                "bounds_max_abs_diff": _max_abs_bounds_diff(
                    left.get("bounds"), right.get("bounds")
                ),
                "volume_delta": (
                    _round_float(float(right.get("volume", 0.0)) - float(left.get("volume", 0.0)))
                    if "volume" in left and "volume" in right
                    else None
                ),
                "area_delta": (
                    _round_float(float(right.get("area", 0.0)) - float(left.get("area", 0.0)))
                    if "area" in left and "area" in right
                    else None
                ),
            }
        )
    return {
        "names_match": names_match,
        "left_only": sorted(set(left_map) - set(right_map)),
        "right_only": sorted(set(right_map) - set(left_map)),
        "row_diffs": row_diffs,
    }


def _compare_pair(fast_row: dict[str, object], fallback_row: dict[str, object]) -> dict[str, object]:
    fast_glb = fast_row.get("glb_summary") or {}
    fallback_glb = fallback_row.get("glb_summary") or {}
    fast_3mf = fast_row.get("threemf_summary") or {}
    fallback_3mf = fallback_row.get("threemf_summary") or {}
    glb_geometry = _compare_named_rows(
        fast_glb.get("geometry", []),
        fallback_glb.get("geometry", []),
        name_key="name",
        face_key="faces",
    )
    threemf_geometry = _compare_named_rows(
        fast_3mf.get("objects", []),
        fallback_3mf.get("objects", []),
        name_key="name",
        face_key="triangles",
    )
    glb_clean = (
        fast_glb.get("geometry_count") == fallback_glb.get("geometry_count")
        and fast_glb.get("total_vertices") == fallback_glb.get("total_vertices")
        and fast_glb.get("total_faces") == fallback_glb.get("total_faces")
        and glb_geometry["names_match"]
        and all(
            diff["vertices_delta"] == 0
            and diff["faces_delta"] == 0
            and (diff["bounds_max_abs_diff"] is None or diff["bounds_max_abs_diff"] <= 1e-6)
            for diff in glb_geometry["row_diffs"]
        )
    )
    threemf_clean = (
        fast_3mf.get("object_count") == fallback_3mf.get("object_count")
        and fast_3mf.get("total_vertices") == fallback_3mf.get("total_vertices")
        and fast_3mf.get("total_triangles") == fallback_3mf.get("total_triangles")
        and threemf_geometry["names_match"]
        and all(
            diff["vertices_delta"] == 0
            and diff["triangles_delta"] == 0
            and (diff["bounds_max_abs_diff"] is None or diff["bounds_max_abs_diff"] <= 1e-6)
            for diff in threemf_geometry["row_diffs"]
        )
    )
    return {
        "svg": fast_row["svg"],
        "glb_file_sha_match": fast_glb.get("sha256") == fallback_glb.get("sha256"),
        "threemf_object_model_sha_match": fast_3mf.get("object_model_sha256")
        == fallback_3mf.get("object_model_sha256"),
        "glb_clean": glb_clean,
        "threemf_clean": threemf_clean,
        "glb": {
            "fast_vertices": fast_glb.get("total_vertices"),
            "fallback_vertices": fallback_glb.get("total_vertices"),
            "fast_faces": fast_glb.get("total_faces"),
            "fallback_faces": fallback_glb.get("total_faces"),
            "geometry": glb_geometry,
        },
        "threemf": {
            "fast_vertices": fast_3mf.get("total_vertices"),
            "fallback_vertices": fallback_3mf.get("total_vertices"),
            "fast_triangles": fast_3mf.get("total_triangles"),
            "fallback_triangles": fallback_3mf.get("total_triangles"),
            "geometry": threemf_geometry,
        },
    }


def main() -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("svg", nargs="*", type=Path, help="SVG fixtures to profile.")
    parser.add_argument("--lut", type=Path, default=DEFAULT_LUT_PATH)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "logs" / "svg_fast_union_parity_profile.json",
    )
    args = parser.parse_args()

    if not args.lut.exists():
        raise FileNotFoundError(f"LUT not found: {args.lut}")
    svg_paths = args.svg or DEFAULT_SVGS
    if not svg_paths:
        parser.error("at least one SVG path is required")
    for svg_path in svg_paths:
        if not svg_path.exists():
            raise FileNotFoundError(f"SVG not found: {svg_path}")

    rows = []
    comparisons = []
    for svg_path in svg_paths:
        print(f"[parity] {svg_path.name} fast")
        fast_row = _run_vector_branch(
            svg_path=svg_path,
            lut_path=args.lut,
            kernel="v1",
            union_mode="fast",
        )
        rows.append(fast_row)
        print(f"[parity] {svg_path.name} fallback")
        fallback_row = _run_vector_branch(
            svg_path=svg_path,
            lut_path=args.lut,
            kernel="v1",
            union_mode="fallback",
        )
        rows.append(fallback_row)
        comparisons.append(_compare_pair(fast_row, fallback_row))

    v1_profiles = []
    for svg_path in svg_paths:
        print(f"[profile:v1] {svg_path.name}")
        v1_profiles.append(
            _run_vector_branch(
                svg_path=svg_path,
                lut_path=args.lut,
                kernel="v1",
                union_mode="fast",
                profile=True,
            )
        )

    v2_export_profiles = []
    for svg_path in svg_paths:
        print(f"[profile:v2-export] {svg_path.name}")
        v2_export_profiles.append(
            _run_vector_branch(
                svg_path=svg_path,
                lut_path=args.lut,
                kernel="v2",
                union_mode="fast",
                profile_export_dispatch=True,
            )
        )

    payload = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "svg_paths": [str(path) for path in svg_paths],
        "parity_rows": rows,
        "parity_comparisons": comparisons,
        "v1_profiles": v1_profiles,
        "v2_export_profiles": v2_export_profiles,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
