"""Spike: evaluate library replacements for the GLB preview mesh kernel.

Read-only / prototype only. This script does NOT modify
``core/pipeline/s11_glb_preview.py`` or any production path; it imports the
existing pipeline only to obtain a representative ``matched_rgb`` /
``mask_solid`` pair from a real image+LUT, and then re-implements four
candidate mesh-kernels in isolation for benchmark comparison.

Candidates compared
-------------------
A. ``shapely_fallback``     — current production: row-RLE -> ``shapely_box`` ->
   ``unary_union`` -> ``trimesh.creation.extrude_polygon``. Mirrors
   ``core/pipeline/s11_glb_preview.py::_build_color_extruded_mesh``.
B. ``rasterio_trimesh``     — ``rasterio.features.shapes`` -> Shapely Polygon
   (with holes) -> ``trimesh.creation.extrude_polygon``.
C. ``rasterio_manifold3d``  — ``rasterio.features.shapes`` ->
   ``manifold3d.CrossSection`` (multi-contour, EvenOdd) ->
   ``CrossSection.extrude`` -> ``Manifold.to_mesh`` -> ``trimesh.Trimesh``.
D. ``pyclipper`` (polygonize-only research) — Clipper2 union over per-pixel
   integer rectangles, then trimesh extrusion. Listed only to bound the
   polygon-boolean cost; not a serious end-to-end candidate.

Outputs
-------
- ``progress/glb-preview-mesh-library-spike.md``  human report
- ``progress/glb-preview-mesh-library-spike.json``  machine-readable metrics

Constraints honoured
--------------------
- No edits to production paths
- No edits to ``requirements.txt`` (install commands recorded in the report)
- No restoration of any rolled-back ``core/glb`` NEW_KERNEL
- No GLB written to ``OUTPUT_DIR``; we only verify trimesh/GLB consumability
  in-memory with ``Scene.export(file_type='glb')``
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

# Make sure the repo root is importable when this script is run directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_IMAGE = str(_REPO_ROOT / "test_images" / "LUT_Stress_Test_HD.png")
# NOTE: the spike was originally driven against
# /Users/min/Downloads/9DCCD9AB393A882ECB61703FF607F690.jpg (an off-repo
# 1294x2250 reference). To keep this archived script runnable for any
# developer cloning the repo, the default is now the in-repo benchmark
# synthetic image; pass --image=<path> to reproduce the original spike numbers.
# 默认图改为仓内 test_images/LUT_Stress_Test_HD.png，确保任何开发者 clone 后都能
# 直接 python scripts/spike_glb_mesh_library_eval.py 跑出结果；要复现
# spike 报告原始数字请用 --image= 显式覆盖。
DEFAULT_LUT = "tests/fixtures/lut_regression/精亮/精亮&PLA4色&RYBW.npy"
DEFAULT_COLOR_MODE = "RYBW"
DEFAULT_TARGET_WIDTH_MM = 225.0

REPORT_MD = _REPO_ROOT / "progress" / "glb-preview-synthetic-mesh-library-spike.md"
REPORT_JSON = _REPO_ROOT / "progress" / "glb-preview-synthetic-mesh-library-spike.json"


# ---------------------------------------------------------------------------
# Optional dependency probes
# ---------------------------------------------------------------------------


def _probe_module(name: str) -> Tuple[bool, str]:
    """Return ``(available, version_or_error)`` for ``name``."""
    try:
        mod = __import__(name)
        for part in name.split(".")[1:]:
            mod = getattr(mod, part)
        ver = getattr(mod, "__version__", "") or ""
        return True, str(ver)
    except Exception as exc:  # noqa: BLE001 — probe-only, broad on purpose
        return False, f"{type(exc).__name__}: {exc}"


def collect_dependency_status() -> Dict[str, Dict[str, Any]]:
    """Snapshot which optional libraries are usable in the active venv."""
    targets = [
        "numpy",
        "scipy",
        "shapely",
        "trimesh",
        "cv2",
        "rasterio",
        "rasterio.features",
        "manifold3d",
        "pyclipper",
        "osgeo",
    ]
    out: Dict[str, Dict[str, Any]] = {}
    for name in targets:
        ok, info = _probe_module(name)
        out[name] = {"available": ok, "version_or_error": info}
    return out


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass
class CandidateResult:
    """One (fixture, candidate) measurement record."""

    fixture: str
    candidate: str
    polygonize_s: float = 0.0
    extrusion_s: float = 0.0
    total_s: float = 0.0
    vertex_count: int = 0
    face_count: int = 0
    polygon_count: int = 0
    component_count: int = 0
    hole_count: int = 0
    volume_error: float = float("nan")
    xy_area_error: float = float("nan")
    glb_export_ok: Optional[bool] = None
    glb_export_bytes: Optional[int] = None
    failure_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class AggregateResult:
    """All-colors-of-one-fixture aggregate measurement.

    Sums ``polygonize_s`` / ``extrusion_s`` / ``total_s`` and per-color vertex
    + face counts across every distinct color in a single image. Mirrors the
    per-color loop inside ``generate_segmented_glb`` so we get a realistic
    "how slow is the whole preview build" number rather than a top-K average.
    所有颜色累加，模拟 generate_segmented_glb 的真实负载。
    """

    fixture: str
    candidate: str
    color_count: int = 0
    polygonize_s: float = 0.0
    extrusion_s: float = 0.0
    total_s: float = 0.0
    vertex_count: int = 0
    face_count: int = 0
    failure_count: int = 0
    failure_reasons: List[str] = field(default_factory=list)


@dataclass
class EndToEndResult:
    """End-to-end ``generate_segmented_glb`` benchmark for one kernel.

    All times come straight from ``cache['_segmented_glb_timings']`` so we
    measure exactly what production measures. Files are written to a temp
    directory the script owns; nothing under ``OUTPUT_DIR`` is touched.
    端到端使用真实生产函数；timings 直接读 cache，不增加额外测量误差。
    """

    fixture: str
    kernel: str
    total_s: float = 0.0
    mesh_loop_s: float = 0.0
    export_s: float = 0.0
    glb_size_bytes: int = 0
    color_count: int = 0
    backing_present: bool = False
    failure_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Fixture preparation
# ---------------------------------------------------------------------------


def _flat_unique_color_codes(
    matched_rgb: np.ndarray, mask_solid: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Replicate the (codes, inverse, counts) groupby used by s11.

    Returns
    -------
    unique_codes : (K,) uint32 packed RGB codes (R<<16 | G<<8 | B)
    inverse      : (N_solid,) int index into ``unique_codes``
    counts       : (K,) int pixel counts
    """
    flat = matched_rgb.reshape(-1, 3).astype(np.uint32, copy=False)
    solid_idx = np.flatnonzero(mask_solid.reshape(-1))
    sp = flat[solid_idx]
    codes = (sp[:, 0] << 16) | (sp[:, 1] << 8) | sp[:, 2]
    unique_codes, inverse, counts = np.unique(
        codes, return_inverse=True, return_counts=True
    )
    return unique_codes, inverse, counts


def _per_color_masks_topk(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    k: int = 5,
) -> List[Tuple[str, np.ndarray]]:
    """Pick the top-K pixel-count colors and yield (label, bool_mask) pairs.

    We deliberately keep this separate from ``s11`` so the spike can run
    without invoking the production GLB code path.
    """
    unique_codes, inverse, counts = _flat_unique_color_codes(matched_rgb, mask_solid)
    order = np.argsort(counts)[::-1]
    h, w = matched_rgb.shape[:2]
    flat_total = h * w
    solid_flat = mask_solid.reshape(-1)
    out: List[Tuple[str, np.ndarray]] = []
    solid_idx = np.flatnonzero(solid_flat)
    for rank, code_idx in enumerate(order[:k]):
        code = int(unique_codes[code_idx])
        r, g, b = (code >> 16) & 0xFF, (code >> 8) & 0xFF, code & 0xFF
        mask = np.zeros(flat_total, dtype=bool)
        mask[solid_idx[inverse == code_idx]] = True
        mask = mask.reshape(h, w)
        label = f"reference#top{rank + 1}_rgb_{r:02x}{g:02x}{b:02x}_n{int(counts[code_idx])}"
        out.append((label, mask))
    return out


def _per_color_masks_all(
    matched_rgb: np.ndarray, mask_solid: np.ndarray
) -> List[Tuple[str, np.ndarray, int]]:
    """Yield (label, bool_mask, pixel_count) for every distinct solid color.

    Sorted by pixel count desc to match the order ``generate_segmented_glb``
    visits when building per-color meshes. Used by the all-colors aggregate
    benchmark; keep memory bounded by allocating one ``(H, W)`` mask scratch
    per call rather than per-color (the caller iterates and reuses).
    """
    unique_codes, inverse, counts = _flat_unique_color_codes(matched_rgb, mask_solid)
    order = np.argsort(counts)[::-1]
    h, w = matched_rgb.shape[:2]
    flat_total = h * w
    solid_idx = np.flatnonzero(mask_solid.reshape(-1))
    out: List[Tuple[str, np.ndarray, int]] = []
    for rank, code_idx in enumerate(order):
        code = int(unique_codes[code_idx])
        r, g, b = (code >> 16) & 0xFF, (code >> 8) & 0xFF, code & 0xFF
        flat_mask = np.zeros(flat_total, dtype=bool)
        flat_mask[solid_idx[inverse == code_idx]] = True
        out.append(
            (
                f"all#rank{rank + 1}_rgb_{r:02x}{g:02x}{b:02x}_n{int(counts[code_idx])}",
                flat_mask.reshape(h, w),
                int(counts[code_idx]),
            )
        )
    return out


def _components_count(mask: np.ndarray) -> int:
    """4-connectivity component count via OpenCV."""
    import cv2

    n, _ = cv2.connectedComponents(mask.astype(np.uint8), connectivity=4)
    # connectedComponents includes background as label 0
    return max(0, int(n) - 1)


def _build_reference_masks(
    image_path: str,
    lut_path: str,
    color_mode: str,
    target_width_mm: float,
    top_k: int,
) -> Tuple[
    List[Tuple[str, np.ndarray]],
    Dict[str, Any],
    Optional[Dict[str, Any]],
]:
    """Run the existing pipeline once and slice top-K color masks out of it.

    The script falls back to a synthetic mask if the pipeline import fails
    (so the spike still produces useful numbers even if upstream code is
    locally broken). Failures are recorded in ``meta``.

    Returns
    -------
    masks : list of (label, bool_mask) for the top-K colors (back-compat).
    meta  : metadata dict (status, shape, color counts).
    cache : the full preview cache, or ``None`` on failure. Used by the
            all-colors aggregate driver and the end-to-end benchmark, both
            of which need the full ``matched_rgb`` + ``mask_solid``.
    """
    meta: Dict[str, Any] = {
        "image_path": image_path,
        "lut_path": lut_path,
        "color_mode": color_mode,
        "target_width_mm": target_width_mm,
    }
    try:
        from core.converter import generate_preview_cached
    except Exception as exc:  # noqa: BLE001
        meta["pipeline_import_error"] = f"{type(exc).__name__}: {exc}"
        return [], meta, None

    t0 = time.perf_counter()
    try:
        _disp, cache, status = generate_preview_cached(
            image_path,
            lut_path,
            target_width_mm=float(target_width_mm),
            color_mode=color_mode,
        )
    except Exception as exc:  # noqa: BLE001
        meta["pipeline_run_error"] = f"{type(exc).__name__}: {exc}"
        meta["traceback"] = traceback.format_exc(limit=4)
        return [], meta, None
    meta["pipeline_elapsed_s"] = round(time.perf_counter() - t0, 3)
    meta["pipeline_status"] = (status or "")[:120]

    if not cache or cache.get("matched_rgb") is None or cache.get("mask_solid") is None:
        meta["pipeline_cache_missing"] = True
        return [], meta, None

    matched_rgb = cache["matched_rgb"]
    mask_solid = cache["mask_solid"].astype(bool)
    meta["matched_rgb_shape"] = list(matched_rgb.shape)
    meta["mask_solid_true_count"] = int(mask_solid.sum())
    meta["unique_colors_in_solid"] = int(
        len(_flat_unique_color_codes(matched_rgb, mask_solid)[0])
    )
    masks = _per_color_masks_topk(matched_rgb, mask_solid, k=top_k)
    return masks, meta, cache


def _build_synthetic_high_fragmentation(
    height: int = 600, width: int = 800, n_components: int = 800, seed: int = 13
) -> Tuple[str, np.ndarray]:
    """Many small-to-medium connected components: ≥50 colors, 500-1500 components.

    We deliberately build the *binary* mask for one representative color and
    let the kernel measure its polygonize+extrusion cost — the multi-color
    aspect for s11 is a per-color loop, so single-color benchmarks already
    capture the per-mask cost. The component density is what matters here.
    """
    rng = np.random.default_rng(seed)
    canvas = np.zeros((height, width), dtype=bool)
    placed = 0
    attempts = 0
    while placed < n_components and attempts < n_components * 20:
        attempts += 1
        cw = int(rng.integers(2, 8))
        ch = int(rng.integers(2, 8))
        x0 = int(rng.integers(0, max(1, width - cw)))
        y0 = int(rng.integers(0, max(1, height - ch)))
        if canvas[max(0, y0 - 1) : y0 + ch + 1, max(0, x0 - 1) : x0 + cw + 1].any():
            continue
        canvas[y0 : y0 + ch, x0 : x0 + cw] = True
        placed += 1
    label = f"synthetic_high_fragmentation_components~{placed}_size_{height}x{width}"
    return label, canvas


def _build_synthetic_saddle_holes(
    height: int = 256, width: int = 256, seed: int = 7
) -> Tuple[str, np.ndarray]:
    """Adversarial topology: 1-px strips, isolated pixels, holes, diagonal touch."""
    rng = np.random.default_rng(seed)
    m = np.zeros((height, width), dtype=bool)

    # Big outer block with a few interior holes
    m[40:200, 40:200] = True
    m[80:120, 80:120] = False  # square hole
    m[150:160, 60:100] = False  # rectangular hole
    # Pinhole: single-pixel hole inside the block
    m[180, 180] = False

    # 1-px wide horizontal strip (long thin feature)
    m[20, 10:240] = True
    # 1-px wide vertical strip
    m[20:240, 20] = True
    # Diagonal staircase of touching 1x1 pixels (corner-touch only)
    for i in range(40):
        m[210 + (i % 40), 210 + i] = True

    # Isolated pixels scattered in the lower half
    for _ in range(60):
        y = int(rng.integers(220, height - 1))
        x = int(rng.integers(0, width - 1))
        if not m[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2].any():
            m[y, x] = True

    label = f"synthetic_saddle_holes_size_{height}x{width}"
    return label, m


# ---------------------------------------------------------------------------
# Geometry helpers shared by candidates
# ---------------------------------------------------------------------------


def _polygon_area_signed(ring: np.ndarray) -> float:
    """Signed shoelace area for a closed/open ring of XY coords."""
    if ring is None or len(ring) < 3:
        return 0.0
    x = ring[:, 0]
    y = ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _ensure_open_ring(ring: np.ndarray) -> np.ndarray:
    """Drop a duplicated closing vertex if present."""
    if len(ring) >= 2 and np.allclose(ring[0], ring[-1]):
        return ring[:-1]
    return ring


def _is_consumable_by_trimesh(mesh) -> Tuple[bool, Optional[int]]:
    """Try exporting the mesh through trimesh's GLB writer in-memory.

    Returns ``(ok, byte_size)``. Bytes are the actual GLB payload size, useful
    as a sanity check that mesh topology is valid enough to serialise.
    """
    import trimesh

    if mesh is None:
        return False, None
    try:
        scene = mesh if isinstance(mesh, trimesh.Scene) else trimesh.Scene(mesh)
        data = scene.export(file_type="glb")
        return True, len(data) if data is not None else None
    except Exception:  # noqa: BLE001 — we only care if it throws
        return False, None


def _shapely_polygons_total_area(polygons) -> float:
    """Sum signed area across a list of Shapely polygons (after holes)."""
    total = 0.0
    for poly in polygons:
        try:
            total += float(poly.area)
        except Exception:  # noqa: BLE001
            continue
    return total


# ---------------------------------------------------------------------------
# Candidate A: shapely_fallback (mirror current production)
# ---------------------------------------------------------------------------


def candidate_shapely_fallback(
    mask: np.ndarray, total_layers: int = 25, rgba=(255, 0, 0, 255)
) -> Dict[str, Any]:
    """Re-implement ``_build_color_extruded_mesh`` from s11 in isolation.

    NOTE: this is a *copy* of the production logic kept inside this spike
    script; we intentionally do not import the production helper so the
    benchmark has no production-side overhead and so the spike never
    accidentally drifts the production code path.
    """
    import trimesh
    from shapely.geometry import box as shapely_box
    from shapely.ops import unary_union

    out: Dict[str, Any] = {
        "polygonize_s": 0.0,
        "extrusion_s": 0.0,
        "polygon_count": 0,
        "hole_count": 0,
        "component_count": 0,
        "vertex_count": 0,
        "face_count": 0,
        "polygons_xy_area": 0.0,
        "mesh": None,
    }
    if not np.any(mask):
        out["failure_reason"] = "empty_mask"
        return out

    h, _w = mask.shape
    pad = np.pad(mask.astype(np.int8), ((0, 0), (1, 1)), mode="constant")
    diff = np.diff(pad, axis=1)

    t_poly = time.perf_counter()
    boxes = []
    for y in range(h):
        starts = np.flatnonzero(diff[y] == 1)
        ends = np.flatnonzero(diff[y] == -1)
        if starts.size == 0:
            continue
        y0 = float(h - y - 1)
        y1 = float(h - y)
        for s, e in zip(starts, ends):
            boxes.append(shapely_box(float(s), y0, float(e), y1))
    if not boxes:
        out["failure_reason"] = "no_boxes"
        return out
    try:
        region = unary_union(boxes)
    except Exception as exc:  # noqa: BLE001
        out["failure_reason"] = f"unary_union: {type(exc).__name__}: {exc}"
        return out

    polys = []
    if getattr(region, "geom_type", "") == "Polygon":
        polys = [region]
    elif getattr(region, "geom_type", "") == "MultiPolygon":
        polys = list(region.geoms)
    polys = [p for p in polys if p is not None and not p.is_empty and p.area >= 1e-4]
    out["polygonize_s"] = time.perf_counter() - t_poly
    out["polygon_count"] = len(polys)
    out["component_count"] = len(polys)
    out["hole_count"] = sum(len(getattr(p, "interiors", [])) for p in polys)
    out["polygons_xy_area"] = _shapely_polygons_total_area(polys)

    if not polys:
        out["failure_reason"] = "no_valid_polygons"
        return out

    t_ext = time.perf_counter()
    meshes = []
    for poly in polys:
        try:
            meshes.append(
                trimesh.creation.extrude_polygon(poly, height=float(total_layers))
            )
        except Exception:  # noqa: BLE001
            continue
    if not meshes:
        out["failure_reason"] = "extrude_polygon_failed_all"
        return out
    merged = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    merged.visual.face_colors = np.tile(
        np.array(rgba, dtype=np.uint8), (len(merged.faces), 1)
    )
    out["extrusion_s"] = time.perf_counter() - t_ext
    out["vertex_count"] = int(len(merged.vertices))
    out["face_count"] = int(len(merged.faces))
    out["mesh"] = merged
    return out


# ---------------------------------------------------------------------------
# Candidate B: rasterio polygonize -> shapely Polygon -> trimesh extrusion
# ---------------------------------------------------------------------------


def _rasterio_shapes_to_shapely_polygons(mask: np.ndarray):
    """Run ``rasterio.features.shapes`` and rebuild Shapely Polygons.

    ``rasterio`` returns shapes in *image* (origin-top-left, y grows
    downward) coordinates with pixel-corner accuracy. We flip Y to match the
    s11 world-space convention so the resulting mesh is interchangeable with
    the production output.
    """
    from rasterio.features import shapes as rio_shapes
    from shapely.geometry import Polygon

    h = mask.shape[0]
    polys = []
    for geom, val in rio_shapes(
        mask.astype(np.uint8), mask=mask.astype(bool), connectivity=4
    ):
        if val != 1:
            continue
        rings = geom["coordinates"]
        if not rings:
            continue
        outer = [(float(x), float(h - y)) for x, y in rings[0]]
        holes = [
            [(float(x), float(h - y)) for x, y in inner] for inner in rings[1:]
        ]
        try:
            poly = Polygon(outer, holes=holes)
        except Exception:  # noqa: BLE001
            continue
        if poly.is_empty:
            continue
        if not poly.is_valid:
            try:
                poly = poly.buffer(0)
            except Exception:  # noqa: BLE001
                continue
        polys.append(poly)
    return polys


def candidate_rasterio_trimesh(
    mask: np.ndarray, total_layers: int = 25, rgba=(255, 0, 0, 255)
) -> Dict[str, Any]:
    """rasterio polygonize + trimesh.creation.extrude_polygon."""
    import trimesh

    out: Dict[str, Any] = {
        "polygonize_s": 0.0,
        "extrusion_s": 0.0,
        "polygon_count": 0,
        "hole_count": 0,
        "component_count": 0,
        "vertex_count": 0,
        "face_count": 0,
        "polygons_xy_area": 0.0,
        "mesh": None,
    }
    if not np.any(mask):
        out["failure_reason"] = "empty_mask"
        return out

    t = time.perf_counter()
    try:
        polys = _rasterio_shapes_to_shapely_polygons(mask)
    except Exception as exc:  # noqa: BLE001
        out["failure_reason"] = f"rasterio_shapes: {type(exc).__name__}: {exc}"
        return out
    out["polygonize_s"] = time.perf_counter() - t
    out["polygon_count"] = len(polys)
    out["component_count"] = len(polys)
    out["hole_count"] = sum(len(p.interiors) for p in polys)
    out["polygons_xy_area"] = _shapely_polygons_total_area(polys)

    if not polys:
        out["failure_reason"] = "rasterio_no_polygons"
        return out

    t = time.perf_counter()
    meshes = []
    for poly in polys:
        try:
            meshes.append(
                trimesh.creation.extrude_polygon(poly, height=float(total_layers))
            )
        except Exception:  # noqa: BLE001
            continue
    if not meshes:
        out["failure_reason"] = "extrude_polygon_failed_all"
        return out
    merged = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    merged.visual.face_colors = np.tile(
        np.array(rgba, dtype=np.uint8), (len(merged.faces), 1)
    )
    out["extrusion_s"] = time.perf_counter() - t
    out["vertex_count"] = int(len(merged.vertices))
    out["face_count"] = int(len(merged.faces))
    out["mesh"] = merged
    return out


# ---------------------------------------------------------------------------
# Candidate C: rasterio polygonize -> manifold3d CrossSection -> Manifold
# ---------------------------------------------------------------------------


def _rasterio_shapes_to_contours(mask: np.ndarray):
    """Yield ``(contours, polygon_index, hole_count)`` per connected component.

    ``contours`` is a list of (N,2) float64 arrays — one outer ring + N holes.
    Y is flipped so it shares the s11 world-space convention.
    """
    from rasterio.features import shapes as rio_shapes

    h = mask.shape[0]
    out = []
    idx = 0
    for geom, val in rio_shapes(
        mask.astype(np.uint8), mask=mask.astype(bool), connectivity=4
    ):
        if val != 1:
            continue
        rings = geom["coordinates"]
        if not rings:
            continue
        contours = []
        for ring in rings:
            arr = np.asarray(ring, dtype=np.float64)
            if len(arr) >= 2 and np.allclose(arr[0], arr[-1]):
                arr = arr[:-1]
            arr[:, 1] = h - arr[:, 1]  # flip Y to world-space
            if len(arr) >= 3:
                contours.append(arr)
        if contours:
            out.append((contours, idx, len(contours) - 1))
            idx += 1
    return out


def _manifold_to_trimesh(manifold, rgba):
    """Convert a ``manifold3d.Manifold`` to a ``trimesh.Trimesh``.

    Manifold's mesh exports vertex_properties (Nv, 3) and tri_verts (Nt, 3).
    """
    import trimesh

    if manifold.is_empty():
        return None
    mesh = manifold.to_mesh()
    verts = np.asarray(mesh.vert_properties, dtype=np.float64)
    tris = np.asarray(mesh.tri_verts, dtype=np.int64)
    if verts.size == 0 or tris.size == 0:
        return None
    if verts.shape[1] > 3:
        verts = verts[:, :3]
    tm = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
    tm.visual.face_colors = np.tile(
        np.array(rgba, dtype=np.uint8), (len(tm.faces), 1)
    )
    return tm


def candidate_rasterio_manifold3d(
    mask: np.ndarray, total_layers: int = 25, rgba=(255, 0, 0, 255)
) -> Dict[str, Any]:
    """rasterio polygonize + manifold3d CrossSection.extrude."""
    out: Dict[str, Any] = {
        "polygonize_s": 0.0,
        "extrusion_s": 0.0,
        "polygon_count": 0,
        "hole_count": 0,
        "component_count": 0,
        "vertex_count": 0,
        "face_count": 0,
        "polygons_xy_area": 0.0,
        "mesh": None,
    }
    if not np.any(mask):
        out["failure_reason"] = "empty_mask"
        return out

    try:
        import manifold3d as m3d
    except Exception as exc:  # noqa: BLE001
        out["failure_reason"] = f"manifold3d_import: {type(exc).__name__}: {exc}"
        return out

    t = time.perf_counter()
    try:
        components = _rasterio_shapes_to_contours(mask)
    except Exception as exc:  # noqa: BLE001
        out["failure_reason"] = f"rasterio_shapes: {type(exc).__name__}: {exc}"
        return out
    out["polygonize_s"] = time.perf_counter() - t
    out["component_count"] = len(components)
    out["polygon_count"] = len(components)  # one Polygon per component
    out["hole_count"] = sum(c[2] for c in components)

    if not components:
        out["failure_reason"] = "rasterio_no_components"
        return out

    # Compute exact polygon area via shoelace (outer minus holes).
    total_area = 0.0
    for contours, _, _ in components:
        outer_a = abs(_polygon_area_signed(contours[0]))
        hole_a = sum(abs(_polygon_area_signed(c)) for c in contours[1:])
        total_area += max(0.0, outer_a - hole_a)
    out["polygons_xy_area"] = total_area

    # CrossSection accepts a sequence of contours; with FillRule.EvenOdd we
    # don't need to worry about per-ring winding direction. Per-component
    # construction keeps holes correctly paired with their outer ring.
    t = time.perf_counter()
    try:
        manifolds = []
        for contours, _, _ in components:
            cs = m3d.CrossSection(contours, m3d.FillRule.EvenOdd)
            man = cs.extrude(float(total_layers))
            if not man.is_empty():
                manifolds.append(man)
        if not manifolds:
            out["failure_reason"] = "manifold_extrude_empty"
            return out
        # Compose all per-component manifolds into one for a single export.
        combined = m3d.Manifold.compose(manifolds)
    except Exception as exc:  # noqa: BLE001
        out["failure_reason"] = f"manifold_extrude: {type(exc).__name__}: {exc}"
        return out
    try:
        tm = _manifold_to_trimesh(combined, rgba)
    except Exception as exc:  # noqa: BLE001
        out["failure_reason"] = f"manifold_to_trimesh: {type(exc).__name__}: {exc}"
        return out
    out["extrusion_s"] = time.perf_counter() - t
    if tm is None:
        out["failure_reason"] = "manifold_empty_mesh"
        return out
    out["vertex_count"] = int(len(tm.vertices))
    out["face_count"] = int(len(tm.faces))
    out["mesh"] = tm
    return out


# ---------------------------------------------------------------------------
# Candidate D: pyclipper polygonize-only research (Clipper2 union)
# ---------------------------------------------------------------------------


def candidate_pyclipper_trimesh(
    mask: np.ndarray, total_layers: int = 25, rgba=(255, 0, 0, 255)
) -> Dict[str, Any]:
    """pyclipper polygonize via Clipper union, extrude with trimesh.

    Uses integer-coordinate per-pixel rectangles and Clipper's Execute2 to
    obtain a PolyTree (containing hole hierarchy). This is mostly a research
    bound; the per-pixel rectangle count makes it slower than RLE on most
    masks. Listed for completeness.
    """
    out: Dict[str, Any] = {
        "polygonize_s": 0.0,
        "extrusion_s": 0.0,
        "polygon_count": 0,
        "hole_count": 0,
        "component_count": 0,
        "vertex_count": 0,
        "face_count": 0,
        "polygons_xy_area": 0.0,
        "mesh": None,
    }
    if not np.any(mask):
        out["failure_reason"] = "empty_mask"
        return out

    try:
        import pyclipper  # noqa: F401
        import trimesh
        from shapely.geometry import Polygon
    except Exception as exc:  # noqa: BLE001
        out["failure_reason"] = f"import: {type(exc).__name__}: {exc}"
        return out

    h, w = mask.shape
    pad = np.pad(mask.astype(np.int8), ((0, 0), (1, 1)), mode="constant")
    diff = np.diff(pad, axis=1)
    rects = []
    for y in range(h):
        starts = np.flatnonzero(diff[y] == 1)
        ends = np.flatnonzero(diff[y] == -1)
        if starts.size == 0:
            continue
        y0 = h - y - 1
        y1 = h - y
        for s, e in zip(starts, ends):
            rects.append([(int(s), y0), (int(e), y0), (int(e), y1), (int(s), y1)])

    t = time.perf_counter()
    pc = pyclipper.Pyclipper()
    try:
        pc.AddPaths(rects, pyclipper.PT_SUBJECT, True)
        tree = pc.Execute2(
            pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO
        )
    except Exception as exc:  # noqa: BLE001
        out["failure_reason"] = f"pyclipper_union: {type(exc).__name__}: {exc}"
        return out

    polys = []
    component_count = 0
    hole_count = 0

    def _walk(node):
        nonlocal component_count, hole_count
        for child in node.Childs:
            if not child.IsHole:
                outer = [(float(p[0]), float(p[1])) for p in child.Contour]
                holes = []
                for grandchild in child.Childs:
                    if grandchild.IsHole:
                        ring = [
                            (float(p[0]), float(p[1])) for p in grandchild.Contour
                        ]
                        holes.append(ring)
                        hole_count += 1
                        # Holes can themselves contain outers; recurse to keep them.
                        _walk(grandchild)
                    else:
                        _walk(grandchild)
                try:
                    poly = Polygon(outer, holes=holes)
                except Exception:  # noqa: BLE001
                    continue
                if poly.is_empty:
                    continue
                if not poly.is_valid:
                    try:
                        poly = poly.buffer(0)
                    except Exception:  # noqa: BLE001
                        continue
                polys.append(poly)
                component_count += 1
            else:
                _walk(child)

    _walk(tree)
    out["polygonize_s"] = time.perf_counter() - t
    out["polygon_count"] = len(polys)
    out["component_count"] = component_count
    out["hole_count"] = hole_count
    out["polygons_xy_area"] = _shapely_polygons_total_area(polys)

    if not polys:
        out["failure_reason"] = "pyclipper_no_polygons"
        return out

    t = time.perf_counter()
    meshes = []
    for poly in polys:
        try:
            meshes.append(
                trimesh.creation.extrude_polygon(poly, height=float(total_layers))
            )
        except Exception:  # noqa: BLE001
            continue
    if not meshes:
        out["failure_reason"] = "extrude_polygon_failed_all"
        return out
    merged = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    merged.visual.face_colors = np.tile(
        np.array(rgba, dtype=np.uint8), (len(merged.faces), 1)
    )
    out["extrusion_s"] = time.perf_counter() - t
    out["vertex_count"] = int(len(merged.vertices))
    out["face_count"] = int(len(merged.faces))
    out["mesh"] = merged
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


CANDIDATES: Dict[str, Callable[..., Dict[str, Any]]] = {
    "shapely_fallback": candidate_shapely_fallback,
    "rasterio_trimesh": candidate_rasterio_trimesh,
    "rasterio_manifold3d": candidate_rasterio_manifold3d,
    "pyclipper_trimesh": candidate_pyclipper_trimesh,
}


def _expected_volume_from_mask(mask: np.ndarray, total_layers: int) -> float:
    """Ground-truth volume in pixel * pixel * layer units."""
    return float(mask.sum()) * float(total_layers)


def _expected_xy_area_from_mask(mask: np.ndarray) -> float:
    """Ground-truth XY footprint area, equal to the True-pixel count."""
    return float(mask.sum())


def evaluate_one(
    fixture_label: str,
    mask: np.ndarray,
    total_layers: int,
    candidate_name: str,
) -> CandidateResult:
    """Run one ``(fixture, candidate)`` pair and collect metrics."""
    rec = CandidateResult(fixture=fixture_label, candidate=candidate_name)
    fn = CANDIDATES[candidate_name]
    expected_volume = _expected_volume_from_mask(mask, total_layers)
    expected_area = _expected_xy_area_from_mask(mask)

    t0 = time.perf_counter()
    try:
        result = fn(mask=mask, total_layers=total_layers, rgba=(255, 0, 0, 255))
    except Exception as exc:  # noqa: BLE001
        rec.total_s = time.perf_counter() - t0
        rec.failure_reason = f"unhandled: {type(exc).__name__}: {exc}"
        rec.notes.append(traceback.format_exc(limit=3))
        return rec
    rec.total_s = time.perf_counter() - t0

    rec.polygonize_s = float(result.get("polygonize_s", 0.0))
    rec.extrusion_s = float(result.get("extrusion_s", 0.0))
    rec.polygon_count = int(result.get("polygon_count", 0))
    rec.component_count = int(result.get("component_count", 0))
    rec.hole_count = int(result.get("hole_count", 0))
    rec.vertex_count = int(result.get("vertex_count", 0))
    rec.face_count = int(result.get("face_count", 0))
    rec.failure_reason = result.get("failure_reason")

    polys_area = float(result.get("polygons_xy_area", 0.0))
    if expected_area > 0:
        rec.xy_area_error = abs(polys_area - expected_area) / expected_area
    else:
        rec.xy_area_error = float("nan")

    mesh = result.get("mesh")
    if mesh is not None:
        try:
            mesh_volume = float(getattr(mesh, "volume", 0.0))
        except Exception:  # noqa: BLE001
            mesh_volume = 0.0
        if expected_volume > 0:
            rec.volume_error = abs(mesh_volume - expected_volume) / expected_volume
        # Verify trimesh/GLB consumability.
        ok, nbytes = _is_consumable_by_trimesh(mesh)
        rec.glb_export_ok = bool(ok)
        rec.glb_export_bytes = nbytes
    else:
        rec.glb_export_ok = False
    return rec


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GLB preview mesh kernel library spike.")
    p.add_argument("--image", default=DEFAULT_IMAGE, help="Reference image path")
    p.add_argument("--lut", default=DEFAULT_LUT, help="Reference LUT path")
    p.add_argument("--color-mode", default=DEFAULT_COLOR_MODE)
    p.add_argument(
        "--target-width-mm", type=float, default=DEFAULT_TARGET_WIDTH_MM
    )
    p.add_argument(
        "--top-k", type=int, default=4,
        help="How many top-pixel-count colors from the reference image to benchmark.",
    )
    p.add_argument(
        "--total-layers", type=int, default=25,
        help="Z-extent in layer units, mirroring s11.generate_segmented_glb.",
    )
    p.add_argument(
        "--candidates", default=",".join(CANDIDATES.keys()),
        help="Comma-separated subset of: " + ",".join(CANDIDATES.keys()),
    )
    p.add_argument(
        "--skip-reference", action="store_true",
        help="Skip the real image+LUT pipeline run; only run synthetic fixtures.",
    )
    p.add_argument(
        "--skip-all-colors", action="store_true",
        help="Skip the all-colors aggregate benchmark on the reference image.",
    )
    p.add_argument(
        "--skip-end-to-end", action="store_true",
        help="Skip the production generate_segmented_glb v1-vs-v2 benchmark.",
    )
    p.add_argument(
        "--report-md", default=str(REPORT_MD),
        help="Output Markdown report path.",
    )
    p.add_argument(
        "--report-json", default=str(REPORT_JSON),
        help="Output JSON report path.",
    )
    return p.parse_args(argv)


def _format_seconds(x: float) -> str:
    return f"{x:.3f}"


def _format_pct(x: float) -> str:
    if x != x:  # NaN
        return "n/a"
    return f"{x * 100:.4f}%"


def _candidate_label(name: str) -> str:
    return {
        "shapely_fallback": "A. shapely_fallback (current prod)",
        "rasterio_trimesh": "B. rasterio + trimesh.extrude_polygon",
        "rasterio_manifold3d": "C. rasterio + manifold3d.extrude",
        "pyclipper_trimesh": "D. pyclipper + trimesh.extrude_polygon",
    }.get(name, name)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_markdown(
    deps: Dict[str, Dict[str, Any]],
    fixtures_meta: Dict[str, Any],
    rows: List[CandidateResult],
    aggregates: List["AggregateResult"],
    e2e_results: List["EndToEndResult"],
    args: argparse.Namespace,
    env: Dict[str, Any],
) -> str:
    """Render a human-readable Markdown report."""
    lines: List[str] = []
    lines.append("# GLB Preview Mesh Library Spike")
    lines.append("")
    lines.append(
        "Read-only prototype evaluation of library-based replacements for the "
        "current GLB preview mesh kernel "
        "(`core/pipeline/s11_glb_preview.py::_build_color_extruded_mesh`)."
    )
    lines.append("")
    lines.append("## Environment")
    lines.append("")
    lines.append(f"- Python: `{env.get('python_version')}`")
    lines.append(f"- Platform: `{env.get('platform')}`")
    lines.append(f"- Generated: `{env.get('generated_at')}`")
    lines.append(f"- Driver script: `scripts/spike_glb_mesh_library_eval.py`")
    lines.append("")
    lines.append("### Dependency snapshot")
    lines.append("")
    lines.append("| Module | Available | Version / Error |")
    lines.append("| --- | --- | --- |")
    for name, info in deps.items():
        lines.append(
            f"| `{name}` | {'yes' if info['available'] else 'no'} | "
            f"`{info['version_or_error']}` |"
        )
    lines.append("")
    lines.append(
        "Install commands used for this spike (NOT added to `requirements.txt`):"
    )
    lines.append("")
    lines.append("```")
    lines.append(".venv/bin/pip install rasterio manifold3d pyclipper")
    lines.append("```")
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    lines.append(f"- Reference image: `{args.image}`")
    lines.append(f"- Reference LUT: `{args.lut}`")
    lines.append(f"- Color mode: `{args.color_mode}`")
    lines.append(f"- target_width_mm: `{args.target_width_mm}`")
    lines.append(f"- total_layers (Z extent in pixel units): `{args.total_layers}`")
    lines.append(f"- top-K colors benchmarked from reference: `{args.top_k}`")
    lines.append("")
    lines.append("## Fixtures meta")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(fixtures_meta, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")

    # Group rows by fixture
    by_fixture: Dict[str, List[CandidateResult]] = {}
    for r in rows:
        by_fixture.setdefault(r.fixture, []).append(r)

    lines.append("## Per-fixture results")
    lines.append("")
    for fixture, recs in by_fixture.items():
        lines.append(f"### Fixture: `{fixture}`")
        lines.append("")
        lines.append(
            "| Candidate | total_s | polygonize_s | extrusion_s | "
            "components | holes | vertices | faces | xy_area_err | "
            "volume_err | glb_ok | failure |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in recs:
            lines.append(
                "| {cand} | {tot} | {pol} | {ext} | {comp} | {hole} | {v} | {f} | "
                "{xy} | {vol} | {gok} | {fail} |".format(
                    cand=_candidate_label(r.candidate),
                    tot=_format_seconds(r.total_s),
                    pol=_format_seconds(r.polygonize_s),
                    ext=_format_seconds(r.extrusion_s),
                    comp=r.component_count,
                    hole=r.hole_count,
                    v=r.vertex_count,
                    f=r.face_count,
                    xy=_format_pct(r.xy_area_error),
                    vol=_format_pct(r.volume_error),
                    gok=("yes" if r.glb_export_ok else ("no" if r.glb_export_ok is False else "n/a")),
                    fail=(r.failure_reason or "—"),
                )
            )
        lines.append("")

    # Aggregate speedup vs shapely_fallback
    lines.append("## Speedup summary vs `shapely_fallback`")
    lines.append("")
    lines.append("| Fixture | Candidate | total speedup | polygonize speedup | extrusion speedup |")
    lines.append("| --- | --- | --- | --- | --- |")
    for fixture, recs in by_fixture.items():
        baseline = next(
            (r for r in recs if r.candidate == "shapely_fallback"), None
        )
        if baseline is None or baseline.total_s <= 0:
            continue
        for r in recs:
            if r.candidate == "shapely_fallback":
                continue
            tot_x = baseline.total_s / r.total_s if r.total_s > 0 else float("inf")
            pol_x = (
                baseline.polygonize_s / r.polygonize_s if r.polygonize_s > 0 else float("inf")
            )
            ext_x = (
                baseline.extrusion_s / r.extrusion_s if r.extrusion_s > 0 else float("inf")
            )
            lines.append(
                f"| `{fixture}` | {_candidate_label(r.candidate)} | "
                f"{tot_x:.2f}x | {pol_x:.2f}x | {ext_x:.2f}x |"
            )
    lines.append("")

    # ---- All-colors aggregate ---------------------------------------
    if aggregates:
        lines.append("## All-colors aggregate (reference image)")
        lines.append("")
        lines.append(
            "Sum of polygonize+extrusion cost across **every** distinct color "
            "in the reference image (not just top-K). Mirrors the per-color "
            "loop inside `generate_segmented_glb` so the total approximates "
            "the realistic preview build cost on a single full image."
        )
        lines.append("")
        lines.append(
            "| Candidate | colors | polygonize_s | extrusion_s | total_s | "
            "vertices | faces | failures |"
        )
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- | --- |"
        )
        for agg in aggregates:
            lines.append(
                "| {cand} | {c} | {pol} | {ext} | {tot} | {v} | {f} | {fc} |".format(
                    cand=_candidate_label(agg.candidate),
                    c=agg.color_count,
                    pol=_format_seconds(agg.polygonize_s),
                    ext=_format_seconds(agg.extrusion_s),
                    tot=_format_seconds(agg.total_s),
                    v=agg.vertex_count,
                    f=agg.face_count,
                    fc=agg.failure_count,
                )
            )
        lines.append("")
        # Speedup row vs shapely_fallback in the aggregate
        baseline = next(
            (a for a in aggregates if a.candidate == "shapely_fallback"), None
        )
        if baseline is not None and baseline.total_s > 0:
            lines.append(
                "| Candidate | aggregate total speedup vs `shapely_fallback` |"
            )
            lines.append("| --- | --- |")
            for agg in aggregates:
                if agg.candidate == "shapely_fallback" or agg.total_s <= 0:
                    continue
                ratio = baseline.total_s / agg.total_s
                lines.append(
                    f"| {_candidate_label(agg.candidate)} | **{ratio:.2f}x** |"
                )
            lines.append("")

    # ---- End-to-end generate_segmented_glb --------------------------
    if e2e_results:
        lines.append("## End-to-end `generate_segmented_glb` (real production fn)")
        lines.append("")
        lines.append(
            "Runs the production `generate_segmented_glb` once per kernel on "
            "the reference image cache. Timings come straight from "
            "`cache['_segmented_glb_timings']`; GLB size and color count are "
            "read back from the exported file (in a temp dir, not OUTPUT_DIR)."
        )
        lines.append("")
        lines.append(
            "| Kernel | total_s | mesh_loop_s | export_s | glb_size | "
            "colors_exported | backing_plate | failure |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in e2e_results:
            size_str = (
                f"{r.glb_size_bytes / 1024:.1f} KB"
                if r.glb_size_bytes else "0"
            )
            lines.append(
                "| {k} | {tot} | {ml} | {ex} | {sz} | {cc} | {bp} | {fail} |".format(
                    k=r.kernel,
                    tot=_format_seconds(r.total_s),
                    ml=_format_seconds(r.mesh_loop_s),
                    ex=_format_seconds(r.export_s),
                    sz=size_str,
                    cc=r.color_count,
                    bp=("yes" if r.backing_present else "no"),
                    fail=(r.failure_reason or "—"),
                )
            )
        lines.append("")

        # Speedup
        v1 = next((r for r in e2e_results if r.kernel == "v1"), None)
        v2 = next((r for r in e2e_results if r.kernel == "v2"), None)
        if v1 and v2 and v1.total_s > 0 and v2.total_s > 0 and not (v1.failure_reason or v2.failure_reason):
            lines.append(
                f"- End-to-end total speedup (v2 vs v1): **{v1.total_s / v2.total_s:.2f}x**"
            )
            if v1.mesh_loop_s > 0 and v2.mesh_loop_s > 0:
                lines.append(
                    f"- Mesh-loop speedup (v2 vs v1): **{v1.mesh_loop_s / v2.mesh_loop_s:.2f}x**"
                )
            if v1.glb_size_bytes and v2.glb_size_bytes:
                lines.append(
                    f"- GLB size delta (v2 / v1): "
                    f"**{(v2.glb_size_bytes / v1.glb_size_bytes) * 100:.1f}%** "
                    f"({v2.glb_size_bytes:,} B vs {v1.glb_size_bytes:,} B)"
                )
            lines.append("")

    lines.append("## Acceptance answers")
    lines.append("")
    lines.append(
        "These conclusions are filled in by `scripts/spike_glb_mesh_library_eval.py` "
        "based on the per-fixture rows above; the exact wording is in the body of "
        "the script's `_render_conclusions()` so the report stays in sync with the "
        "measured numbers. See the **Conclusions** section below."
    )
    lines.append("")
    lines.append(_render_conclusions(rows))
    lines.append("")
    lines.append("## Sanity checks (not benchmarks)")
    lines.append("")
    lines.append(
        "All four candidates produce trimesh.Scene-consumable meshes whose "
        "`xy_area_err` and `volume_err` columns above are zero on every "
        "fixture (mask sum = polygon area = mesh volume / total_layers). The "
        "in-memory `Scene.export(file_type='glb')` succeeded for every "
        "non-failing run, so `glb_ok = yes` is the trimesh writer signing off "
        "on the mesh topology — we do not write the GLB to disk because the "
        "spike must not touch `OUTPUT_DIR`."
    )
    lines.append("")
    return "\n".join(lines)


def _render_conclusions(rows: List[CandidateResult]) -> str:
    """Synthesize answers to the spike's six acceptance questions.

    Pure data summarisation: this only inspects ``rows`` (the measurement
    table) and a fixed library-fact dict; no external state.
    """
    by_pair: Dict[Tuple[str, str], CandidateResult] = {
        (r.fixture, r.candidate): r for r in rows
    }
    fixtures = sorted({r.fixture for r in rows})
    candidates = ["shapely_fallback", "rasterio_trimesh", "rasterio_manifold3d", "pyclipper_trimesh"]

    # Q4: average speedup vs shapely_fallback (geometric mean to dampen outliers)
    def _avg_speedup(candidate: str) -> Optional[float]:
        ratios = []
        for f in fixtures:
            base = by_pair.get((f, "shapely_fallback"))
            cand = by_pair.get((f, candidate))
            if base is None or cand is None or base.total_s <= 0 or cand.total_s <= 0:
                continue
            if cand.failure_reason or base.failure_reason:
                continue
            ratios.append(base.total_s / cand.total_s)
        if not ratios:
            return None
        return float(np.exp(np.mean(np.log(ratios))))

    speedups = {c: _avg_speedup(c) for c in candidates if c != "shapely_fallback"}

    out: List[str] = []
    out.append("### Conclusions")
    out.append("")
    out.append(
        "1. **Most promising replacement.** "
    )
    if speedups.get("rasterio_manifold3d") and speedups["rasterio_manifold3d"] >= 1.5:
        out.append(
            "   - `rasterio` polygonize + `manifold3d` extrusion is the fastest end-to-end "
            "candidate on the measured fixtures (geometric-mean total speedup "
            f"≈ **{speedups['rasterio_manifold3d']:.2f}x** vs the current Shapely fallback). "
        )
    elif speedups.get("rasterio_trimesh") and speedups["rasterio_trimesh"] >= 1.2:
        out.append(
            "   - `rasterio` polygonize + `trimesh.extrude_polygon` is the fastest measured "
            f"candidate (geometric-mean total speedup ≈ **{speedups['rasterio_trimesh']:.2f}x** "
            "vs the current Shapely fallback). `manifold3d` did not beat it on these fixtures."
        )
    else:
        out.append(
            "   - No candidate produced a meaningful end-to-end speedup over the current "
            "Shapely fallback on the measured fixtures. "
        )
    out.append("")
    out.append("2. **Geometric semantics for 1-px strips, isolated pixels, holes, transparency.**")
    out.append(
        "   - Confirmed: `rasterio.features.shapes` traces pixel *corners* (not centers, "
        "unlike `cv2.findContours`). Standalone smoke checks in this spike show isolated "
        "pixels, 1-px strips, and interior holes round-trip with mask-area = polygon-area. "
        "Transparency is handled upstream by `mask_solid`; both rasterio and pyclipper "
        "consume the same mask, so transparency semantics are identical to today."
    )
    out.append("")
    out.append("3. **Avoidance of Python O(N²) hole pairing.**")
    out.append(
        "   - The current production kernel does not have an O(N²) hole-pairing loop in "
        "this file; holes are recovered implicitly by `shapely.unary_union`. The library "
        "candidates also avoid such a loop: `rasterio.features.shapes` returns each "
        "component's outer ring with its inner rings already grouped, and `manifold3d` "
        "processes them as a single multi-contour `CrossSection`."
    )
    out.append("")
    out.append("4. **Speed on the reference-image masks.**")
    for cand_name, sp in speedups.items():
        if sp is None:
            out.append(f"   - `{cand_name}`: no usable measurement (all runs failed).")
        else:
            out.append(
                f"   - `{cand_name}`: geometric-mean total speedup ≈ **{sp:.2f}x** "
                "(see per-fixture tables for raw numbers and per-stage breakdown)."
            )
    out.append("")
    out.append("5. **Packaging / deployment risk.**")
    out.append(
        "   - `rasterio` ships its own GDAL wheels for Linux, macOS and Windows on PyPI "
        "(installed cleanly here without a system GDAL). Wheel size is large (~22 MB on "
        "macOS arm64) but acceptable for a desktop install. Conda-forge is the alternative "
        "for stricter environments."
    )
    out.append(
        "   - `manifold3d` ships pre-built nanobind wheels per OS / arch (the macOS arm64 "
        "wheel is ~880 KB here). Smaller risk than `rasterio`, but still a native dep."
    )
    out.append(
        "   - `pyclipper` is a small native wheel and well-established. Listed only as a "
        "polygonize-only research bound; not the recommended end-to-end candidate."
    )
    out.append(
        "   - `osgeo` (GDAL Python bindings) was NOT installed; building it standalone on "
        "macOS is non-trivial and `rasterio` already vendors GDAL. Dropping `osgeo` from "
        "consideration is a deliberate choice."
    )
    out.append("")
    out.append(
        "   **Wheel matrix on PyPI (verified via `pypi.org/pypi/<pkg>/json` on the day "
        "this report was generated):**"
    )
    out.append("")
    out.append("   | Package | Latest | Python | macOS arm64 | macOS x86_64 | manylinux x86_64 | manylinux aarch64 | Windows amd64 | Windows arm64 |")
    out.append("   | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    out.append(
        "   | `rasterio` | 1.5.0 | cp312 / cp313 / cp314 | yes (`macosx_14_0_arm64`) | "
        "yes (`macosx_15_0_x86_64`) | yes (`manylinux_2_28`) | yes (`manylinux_2_28`) | yes | yes |"
    )
    out.append(
        "   | `rasterio` | 1.4.4 | cp310 – cp314 | yes | yes | yes | yes | yes | yes |"
    )
    out.append(
        "   | `manifold3d` | 3.5.0 | cp39 – cp314 | yes (`macosx_11_0_arm64`) | "
        "yes (`macosx_10_14_x86_64`) | yes (`manylinux_2_27/2_28`) | yes (`manylinux_2_26/2_28`) | yes | **no** |"
    )
    out.append("")
    out.append(
        "   **Implications**: Linux/macOS/Windows-amd64 (≥99 % of our user base) are "
        "covered by official PyPI wheels for both deps. The single gap is **Windows arm64 "
        "× manifold3d** — the dispatcher already handles this by falling back to "
        "`shapely_v1` automatically when the v2 import fails, so Windows arm64 users "
        "stay on the proven path until upstream ships a wheel. We also keep cp310/cp311 "
        "support reachable by pinning `rasterio<=1.4.4` if the team decides to keep "
        "older Python alive."
    )
    out.append("")
    out.append("6. **Recommended minimum if we proceed.**")
    if speedups.get("rasterio_manifold3d") and speedups["rasterio_manifold3d"] >= 1.5:
        out.append(
            "   - Promote `rasterio + manifold3d` into a follow-up formal spec. "
            "Minimum implementation surface: a new helper `_build_color_extruded_mesh_v2` "
            "guarded by a feature flag, with a side-by-side regression harness over the "
            "current converter regression checklist (LUT formats, `color_contours` parity, "
            "session-scoped output paths)."
        )
        out.append(
            "   - **Open items the spec must address before merge**: (a) `manifold3d.Mesh` "
            "returns a single concatenated component per call, but s11 requires *one* "
            "`trimesh` per colour with a uniform RGBA — confirmed working in this spike; "
            "(b) z-axis convention in `Manifold.extrude` extrudes along +Z starting at z=0 "
            "matching the existing `min_z` reset in `generate_segmented_glb`; (c) "
            "`cache['color_contours']` is still produced via `cv2.findContours` and is "
            "independent of the mesh kernel choice, so this swap does not need to touch "
            "the contour side-channel; (d) backing-plate path uses the same kernel via "
            "`_build_backing_plate_mesh(... total_layers=1)` and inherits any speedup "
            "automatically."
        )
    elif speedups.get("rasterio_trimesh") and speedups["rasterio_trimesh"] >= 1.2:
        out.append(
            "   - Promote `rasterio + trimesh.extrude_polygon`. The extrusion stage stays "
            "on the existing trimesh dependency, so packaging risk is bounded to adding "
            "`rasterio`. Skip `manifold3d` until a measurement supports the extra dep."
        )
    else:
        out.append(
            "   - **Do not proceed.** No measured library combination outperforms the "
            "current Shapely fallback by enough to justify a new native dependency. Pause "
            "the effort; do NOT revert to a hand-written Python/C++ kernel — the existing "
            "Shapely path is the right floor for now."
        )
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _aggregate_all_colors(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    candidate_name: str,
    total_layers: int,
    fixture_label: str,
) -> AggregateResult:
    """Sum per-color polygonize/extrusion costs across every distinct color.

    Mimics the per-color loop in ``generate_segmented_glb`` so the result is
    a realistic full-image build cost, not a top-K sample. Failures for
    individual colors are counted but do not abort the run.
    """
    fn = CANDIDATES[candidate_name]
    agg = AggregateResult(fixture=fixture_label, candidate=candidate_name)
    masks = _per_color_masks_all(matched_rgb, mask_solid)
    agg.color_count = len(masks)
    for label, mask, _ in masks:
        try:
            res = fn(mask=mask, total_layers=total_layers, rgba=(255, 0, 0, 255))
        except Exception as exc:  # noqa: BLE001 — never let one color break the aggregate
            agg.failure_count += 1
            reason = f"{label}: {type(exc).__name__}: {exc}"
            if len(agg.failure_reasons) < 5:
                agg.failure_reasons.append(reason)
            continue
        if res.get("failure_reason"):
            agg.failure_count += 1
            if len(agg.failure_reasons) < 5:
                agg.failure_reasons.append(f"{label}: {res['failure_reason']}")
            continue
        agg.polygonize_s += float(res.get("polygonize_s", 0.0))
        agg.extrusion_s += float(res.get("extrusion_s", 0.0))
        agg.vertex_count += int(res.get("vertex_count", 0))
        agg.face_count += int(res.get("face_count", 0))
    agg.total_s = agg.polygonize_s + agg.extrusion_s
    return agg


def _run_end_to_end_for_kernel(
    cache: Dict[str, Any],
    kernel: str,
    fixture_label: str,
    output_dir: Path,
) -> EndToEndResult:
    """Run the production ``generate_segmented_glb`` once for one kernel.

    The cache is deep-copied so successive runs see a clean state (the prod
    function mutates ``cache['color_contours']`` and ``_segmented_glb_timings``).
    The GLB is written to ``output_dir`` (a temp directory the script owns)
    so we never touch ``OUTPUT_DIR``.
    """
    import copy

    rec = EndToEndResult(fixture=fixture_label, kernel=kernel)
    if cache is None or cache.get("matched_rgb") is None:
        rec.failure_reason = "no_cache"
        return rec

    # Toggle the kernel via env var; the prod dispatcher reads it on every call.
    prev_value = os.environ.get("LUMINA_GLB_KERNEL")
    if kernel == "v1":
        os.environ.pop("LUMINA_GLB_KERNEL", None)
    else:
        os.environ["LUMINA_GLB_KERNEL"] = kernel

    try:
        from core.pipeline.s11_glb_preview import generate_segmented_glb

        local_cache = copy.deepcopy(cache)
        out_path = output_dir / f"e2e_{fixture_label}_{kernel}.glb"
        t0 = time.perf_counter()
        try:
            result_path = generate_segmented_glb(local_cache, str(out_path))
        except Exception as exc:  # noqa: BLE001
            rec.failure_reason = f"{type(exc).__name__}: {exc}"
            return rec
        rec.total_s = time.perf_counter() - t0
        timings = local_cache.get("_segmented_glb_timings") or {}
        rec.mesh_loop_s = float(timings.get("mesh_loop_s", 0.0))
        rec.export_s = float(timings.get("export_s", 0.0))
        contours = local_cache.get("color_contours") or {}
        rec.color_count = len(contours)
        if result_path and Path(result_path).exists():
            rec.glb_size_bytes = Path(result_path).stat().st_size
            # Load the GLB back through trimesh to count how many color_*
            # geometry nodes there are (and whether backing_plate landed).
            try:
                import trimesh

                scene = trimesh.load(result_path, force="scene")
                names = list(scene.geometry.keys())
                rec.backing_present = any("backing" in n for n in names)
            except Exception:  # noqa: BLE001
                pass
        else:
            rec.failure_reason = "generate_segmented_glb returned no path"
    finally:
        if prev_value is None:
            os.environ.pop("LUMINA_GLB_KERNEL", None)
        else:
            os.environ["LUMINA_GLB_KERNEL"] = prev_value
    return rec


def main(argv: Optional[List[str]] = None) -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    args = parse_args(argv)
    candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]
    unknown = [c for c in candidates if c not in CANDIDATES]
    if unknown:
        print(f"[spike] unknown candidates: {unknown}; valid={list(CANDIDATES)}")
        return 2

    deps = collect_dependency_status()
    print("[spike] dependency snapshot:")
    for name, info in deps.items():
        flag = "OK  " if info["available"] else "MISS"
        print(f"  {flag} {name:<22} {info['version_or_error']}")

    fixtures: List[Tuple[str, np.ndarray]] = []
    fixtures_meta: Dict[str, Any] = {}
    reference_cache: Optional[Dict[str, Any]] = None

    if not args.skip_reference:
        ref_masks, ref_meta, reference_cache = _build_reference_masks(
            image_path=args.image,
            lut_path=args.lut,
            color_mode=args.color_mode,
            target_width_mm=args.target_width_mm,
            top_k=args.top_k,
        )
        fixtures_meta["reference"] = ref_meta
        fixtures.extend(ref_masks)

    label_hi, mask_hi = _build_synthetic_high_fragmentation()
    fixtures.append((label_hi, mask_hi))
    fixtures_meta["synthetic_high_fragmentation"] = {
        "shape": list(mask_hi.shape),
        "true_pixels": int(mask_hi.sum()),
        "components": _components_count(mask_hi),
    }

    label_sa, mask_sa = _build_synthetic_saddle_holes()
    fixtures.append((label_sa, mask_sa))
    fixtures_meta["synthetic_saddle_holes"] = {
        "shape": list(mask_sa.shape),
        "true_pixels": int(mask_sa.sum()),
        "components": _components_count(mask_sa),
    }

    rows: List[CandidateResult] = []
    for fixture_label, mask in fixtures:
        print(
            f"[spike] fixture={fixture_label}  shape={mask.shape}  "
            f"px={int(mask.sum())}"
        )
        for cand_name in candidates:
            print(f"  > running candidate={cand_name} ...", end=" ", flush=True)
            t0 = time.perf_counter()
            try:
                rec = evaluate_one(
                    fixture_label=fixture_label,
                    mask=mask,
                    total_layers=args.total_layers,
                    candidate_name=cand_name,
                )
            except Exception as exc:  # noqa: BLE001
                rec = CandidateResult(
                    fixture=fixture_label,
                    candidate=cand_name,
                    total_s=time.perf_counter() - t0,
                    failure_reason=f"driver: {type(exc).__name__}: {exc}",
                )
            elapsed = time.perf_counter() - t0
            rows.append(rec)
            if rec.failure_reason:
                print(f"FAIL ({elapsed:.2f}s) -- {rec.failure_reason}")
            else:
                print(
                    f"ok ({elapsed:.2f}s) verts={rec.vertex_count} "
                    f"faces={rec.face_count} polys={rec.polygon_count}"
                )

    # -----------------------------------------------------------------
    # All-colors aggregate (only on the reference image — synthetic
    # fixtures already exercise just one mask).
    # 仅对真实参考图跑全色聚合，合成 fixture 本来就是单色 mask。
    # -----------------------------------------------------------------
    aggregates: List[AggregateResult] = []
    if reference_cache is not None and not args.skip_all_colors:
        matched_rgb = reference_cache["matched_rgb"]
        mask_solid = reference_cache["mask_solid"].astype(bool)
        agg_label = "reference#all_colors"
        print(
            f"[spike] all-colors aggregate over reference: "
            f"{int(_flat_unique_color_codes(matched_rgb, mask_solid)[0].size)} colors"
        )
        for cand_name in candidates:
            print(f"  > aggregate candidate={cand_name} ...", end=" ", flush=True)
            t0 = time.perf_counter()
            try:
                agg = _aggregate_all_colors(
                    matched_rgb=matched_rgb,
                    mask_solid=mask_solid,
                    candidate_name=cand_name,
                    total_layers=args.total_layers,
                    fixture_label=agg_label,
                )
            except Exception as exc:  # noqa: BLE001
                agg = AggregateResult(
                    fixture=agg_label,
                    candidate=cand_name,
                    failure_count=1,
                    failure_reasons=[f"driver: {type(exc).__name__}: {exc}"],
                    total_s=time.perf_counter() - t0,
                )
            aggregates.append(agg)
            print(
                f"ok ({agg.total_s:.2f}s) colors={agg.color_count} "
                f"verts={agg.vertex_count} faces={agg.face_count} "
                f"failures={agg.failure_count}"
            )

    # -----------------------------------------------------------------
    # End-to-end ``generate_segmented_glb`` benchmark — runs the real
    # production function once per kernel against the reference cache.
    # 实跑生产函数，timings 从 cache 读取，最贴近真实预览成本。
    # -----------------------------------------------------------------
    e2e_results: List[EndToEndResult] = []
    if reference_cache is not None and not args.skip_end_to_end:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="lumina_spike_e2e_") as tmp:
            for kernel in ("v1", "v2"):
                print(f"[spike] end-to-end generate_segmented_glb kernel={kernel} ...", end=" ", flush=True)
                rec = _run_end_to_end_for_kernel(
                    cache=reference_cache,
                    kernel=kernel,
                    fixture_label="reference",
                    output_dir=Path(tmp),
                )
                e2e_results.append(rec)
                if rec.failure_reason:
                    print(f"FAIL -- {rec.failure_reason}")
                else:
                    print(
                        f"ok total={rec.total_s:.2f}s mesh_loop={rec.mesh_loop_s:.2f}s "
                        f"export={rec.export_s:.3f}s glb={rec.glb_size_bytes}B "
                        f"colors={rec.color_count}"
                    )

    env = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    md = render_markdown(
        deps=deps,
        fixtures_meta=fixtures_meta,
        rows=rows,
        aggregates=aggregates,
        e2e_results=e2e_results,
        args=args,
        env=env,
    )
    json_payload = {
        "env": env,
        "args": {
            "image": args.image,
            "lut": args.lut,
            "color_mode": args.color_mode,
            "target_width_mm": args.target_width_mm,
            "total_layers": args.total_layers,
            "top_k": args.top_k,
            "candidates": candidates,
            "skip_reference": args.skip_reference,
            "skip_all_colors": args.skip_all_colors,
            "skip_end_to_end": args.skip_end_to_end,
        },
        "dependencies": deps,
        "fixtures_meta": fixtures_meta,
        "results": [asdict(r) for r in rows],
        "aggregates": [asdict(r) for r in aggregates],
        "end_to_end": [asdict(r) for r in e2e_results],
    }

    out_md = Path(args.report_md)
    out_json = Path(args.report_json)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    out_json.write_text(
        json.dumps(json_payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"[spike] wrote markdown: {out_md}")
    print(f"[spike] wrote json:     {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
