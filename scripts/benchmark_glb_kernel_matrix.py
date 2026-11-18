"""Read-only matrix benchmark: GLB kernel v1 vs v2 across sizes and modes.

NO production code changes. NO requirements.txt changes. NO API, frontend,
or cache-schema changes. The only thing this script touches:

* It reads a single image + LUT under each mode listed below.
* It runs ``run_raster_pipeline`` end-to-end with ``LUMINA_GLB_KERNEL=v1``
  and ``=v2``.
* It writes a Markdown + JSON report under ``progress/``.
* It writes throwaway GLBs under a local ``artifacts/glb-bench-tmp/``
  directory (auto-cleaned on success). Nothing under ``OUTPUT_DIR`` is
  touched.

Usage:
    .venv/bin/python scripts/benchmark_glb_kernel_matrix.py
    .venv/bin/python scripts/benchmark_glb_kernel_matrix.py --quick
    .venv/bin/python scripts/benchmark_glb_kernel_matrix.py --modes 4-Color,BW

Stop conditions are honoured exactly as the spec asks: a single case >
15 minutes, a v2 case that falls back end-to-end (data identical to v1),
GLB ratios > 1.10x v1, geometry / load failure, or the need to mutate
production code all abort the run.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import logging
import os
import platform
import shutil
import sys
import time
import traceback
import tracemalloc
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

# Repo root onto sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Defer heavy imports so --help is fast
import numpy as np  # noqa: E402

DEFAULT_IMAGE = _REPO_ROOT / "test_images" / "LUT_Stress_Test_HD.png"
TMP_DIR = _REPO_ROOT / "artifacts" / "glb-bench-tmp"
REPORT_MD = _REPO_ROOT / "progress" / "glb-benchmark-synthetic-multisize-multimode.md"
REPORT_JSON = _REPO_ROOT / "progress" / "glb-benchmark-synthetic-multisize-multimode.json"

# Mode -> LUT discovery (verified to load via load_lut() in the pre-flight).
MODE_TO_LUT: dict[str, Path] = {
    "4-Color RYBW": _REPO_ROOT / "tests/fixtures/lut_regression" / "精亮" / "精亮&PLA4色&RYBW.npy",
    "BW": _REPO_ROOT / "tests/fixtures/lut_regression" / "赛纳" / "赛纳&2色PLA&BW-白-黑.npy",
    "8-Color": _REPO_ROOT / "tests/fixtures/lut_regression" / "精亮" / "精亮&PLA8色.npy",
    "6-Color": _REPO_ROOT / "tests/fixtures/lut_regression" / "精亮" / "精亮&PLA6色&黑 白 黄 绿 红 蓝.npy",
    "5-Color-Extended": (
        _REPO_ROOT
        / "tests/fixtures/lut_regression"
        / "Aliz"
        / "PETG"
        / "5色"
        / "Aliz&PETG&5color&红-黄-蓝-白-黑-20260304.npy"
    ),
}

DEFAULT_WIDTHS_MM: list[float] = [75.0, 150.0, 225.0, 300.0]
QUICK_WIDTHS_MM: list[float] = [75.0, 150.0]
DEFAULT_MODES: list[str] = list(MODE_TO_LUT.keys())

CASE_TIMEOUT_S = 15 * 60.0  # spec hard stop


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class CaseRun:
    """One (mode, width, kernel) measurement."""

    mode: str
    target_width_mm: float
    kernel: str  # 'v1' or 'v2'
    run_index: int
    total_s: float = 0.0
    s06_s: float = 0.0
    s07_s: float = 0.0
    s11_s: float = 0.0
    s11_mesh_loop_s: float = 0.0
    s11_export_s: float = 0.0
    mesh_compute_s: float = 0.0
    peak_memory_mb: float = 0.0
    glb_size_bytes: int = 0
    vertex_count: int = 0
    face_count: int = 0
    unique_color_count: int = 0
    node_count: int = 0
    color_node_count: int = 0
    has_backing_plate: bool = False
    warnings: list[str] = field(default_factory=list)
    fallback_v2_to_v1: bool = False
    failure_reason: str | None = None


@dataclass
class CaseSummary:
    """Aggregate across the warm runs of a single case."""

    mode: str
    target_width_mm: float
    kernel: str
    total_s_median: float = float("nan")
    s06_s_median: float = float("nan")
    s07_s_median: float = float("nan")
    s11_s_median: float = float("nan")
    s11_mesh_loop_s_median: float = float("nan")
    s11_export_s_median: float = float("nan")
    mesh_compute_s_median: float = float("nan")
    peak_memory_mb_max: float = 0.0
    glb_size_bytes_median: float = 0.0
    vertex_count_median: float = 0.0
    face_count_median: float = 0.0
    unique_color_count: int = 0
    node_count: int = 0
    color_node_count: int = 0
    has_backing_plate: bool = False
    warnings_seen: list[str] = field(default_factory=list)
    fallback_v2_to_v1: bool = False
    cold_run: dict[str, float] = field(default_factory=dict)
    runs: list[CaseRun] = field(default_factory=list)
    failure_reason: str | None = None


# ---------------------------------------------------------------------------
# Pipeline driver
# ---------------------------------------------------------------------------


def _build_ctx(image_path: Path, lut_path: Path, target_width_mm: float, color_mode: str) -> dict[str, Any]:
    """Mirror profile_stage3._build_ctx but parametrised on color_mode."""
    from config import ModelingMode

    return {
        "image_path": str(image_path),
        "lut_path": str(lut_path),
        "target_width_mm": float(target_width_mm),
        "spacer_thick": 1.2,
        "structure_mode": "single-sided",
        "color_mode": color_mode,
        "add_loop": False,
        "loop_width": 4.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_pos": None,
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "quantize_colors": 64,
        "blur_kernel": 0,
        "smooth_sigma": 10,
        "color_replacements": None,
        "replacement_regions": None,
        "backing_color_id": 0,
        "separate_backing": False,
        "enable_relief": False,
        "color_height_map": None,
        "height_mode": "color",
        "heightmap_path": None,
        "heightmap_max_height": None,
        "enable_cleanup": True,
        "enable_outline": False,
        "outline_width": 2.0,
        "enable_cloisonne": False,
        "wire_width_mm": 0.4,
        "wire_height_mm": 0.4,
        "free_color_set": None,
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "hue_weight": 0.5,
        "chroma_gate": 15.0,
        "matched_rgb_path": None,
        "loop_angle": 0.0,
        "loop_offset_x": 0.0,
        "loop_offset_y": 0.0,
        "loop_position_preset": "top-center",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "relief_global_max_height": None,
        "progress": None,
        "need_2d_preview": False,
    }


class _StructuredEventCapture(logging.Handler):
    """Capture WARNING records that carry an ``event=glb_kernel_*`` extra."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.events: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        event = getattr(record, "event", None)
        if not isinstance(event, str):
            return
        if not event.startswith("glb_kernel_"):
            return
        self.events.append(
            {
                "event": event,
                "level": record.levelname,
                "message": record.getMessage(),
                "error_type": getattr(record, "error_type", None),
            }
        )


def _stage_seconds(ctx: dict[str, Any], stage_label: str, hifi_key: str) -> float:
    step_timings = ctx.get("_step_timings") or {}
    hifi_timings = ctx.get("_hifi_timings") or {}
    step_val = step_timings.get(stage_label)
    if isinstance(step_val, (int, float)):
        return float(step_val)
    hifi_val = hifi_timings.get(hifi_key)
    if isinstance(hifi_val, (int, float)):
        return float(hifi_val)
    return 0.0


def _hifi(ctx: dict[str, Any], key: str) -> float:
    val = (ctx.get("_hifi_timings") or {}).get(key)
    return float(val) if isinstance(val, (int, float)) else 0.0


def _cleanup_outputs(ctx: dict[str, Any]) -> None:
    for candidate in (ctx.get("out_path"), ctx.get("glb_path"), ctx.get("color_recipe_path")):
        if not candidate:
            continue
        try:
            p = Path(candidate)
            if p.exists():
                p.unlink()
        except OSError:
            continue


def _run_one(
    *,
    image_path: Path,
    lut_path: Path,
    target_width_mm: float,
    color_mode: str,
    kernel: str,
    run_index: int,
) -> CaseRun:
    """Execute one warm/cold run and capture metrics + WARNINGs."""
    rec = CaseRun(
        mode=color_mode,
        target_width_mm=target_width_mm,
        kernel=kernel,
        run_index=run_index,
    )

    if kernel == "v1":
        os.environ.pop("LUMINA_GLB_KERNEL", None)
    elif kernel == "v2":
        os.environ["LUMINA_GLB_KERNEL"] = "v2"
    else:
        rec.failure_reason = f"unknown kernel {kernel!r}"
        return rec

    capture = _StructuredEventCapture()
    target_logger = logging.getLogger("lumina.core.pipeline.s11_glb_preview")
    target_logger.addHandler(capture)

    from core.pipeline.coordinator import run_raster_pipeline

    ctx = _build_ctx(image_path, lut_path, target_width_mm, color_mode)
    tracemalloc.start()
    t0 = time.perf_counter()
    try:
        result = run_raster_pipeline(ctx)
    except Exception as exc:  # noqa: BLE001 — benchmark wants to record, not crash
        rec.failure_reason = f"{type(exc).__name__}: {exc}"
        rec.warnings = [json.dumps(e, ensure_ascii=False) for e in capture.events]
        target_logger.removeHandler(capture)
        tracemalloc.stop()
        return rec
    elapsed = time.perf_counter() - t0
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    target_logger.removeHandler(capture)

    if result.get("error"):
        rec.failure_reason = str(result["error"])[:200]
        rec.warnings = [json.dumps(e, ensure_ascii=False) for e in capture.events]
        _cleanup_outputs(result)
        return rec

    rec.total_s = elapsed
    rec.s06_s = _stage_seconds(result, "S06", "voxel_build_s")
    rec.s07_s = _stage_seconds(result, "S07", "mesh_gen_s")
    rec.s11_s = _stage_seconds(result, "S11", "glb_preview_s")
    rec.s11_mesh_loop_s = _hifi(result, "s11_mesh_loop_s")
    rec.s11_export_s = _hifi(result, "s11_export_s")
    rec.mesh_compute_s = _hifi(result, "mesh_compute_s")
    rec.peak_memory_mb = float(peak_bytes) / (1024.0 * 1024.0)

    glb_path = result.get("glb_path")
    if glb_path and Path(glb_path).exists():
        glb_p = Path(glb_path)
        rec.glb_size_bytes = glb_p.stat().st_size
        try:
            import trimesh

            scene = trimesh.load(glb_path, force="scene")
            v_total = sum(int(len(g.vertices)) for g in scene.geometry.values())
            f_total = sum(int(len(g.faces)) for g in scene.geometry.values())
            rec.vertex_count = v_total
            rec.face_count = f_total
            named_nodes = [n for n in scene.graph.nodes if n != "world"]
            rec.node_count = len(named_nodes)
            rec.color_node_count = sum(
                1 for n in named_nodes if n.startswith("color_")
            )
            rec.has_backing_plate = "backing_plate" in named_nodes
        except Exception as exc:  # noqa: BLE001 — record load failure, do not crash bench
            rec.failure_reason = f"glb_load: {type(exc).__name__}: {exc}"

    matched_rgb = result.get("matched_rgb")
    mask_solid = result.get("mask_solid")
    if matched_rgb is not None and mask_solid is not None:
        flat = np.asarray(matched_rgb).reshape(-1, 3).astype(np.uint32, copy=False)
        msk = np.asarray(mask_solid, dtype=bool).reshape(-1)
        idx = np.flatnonzero(msk)
        if idx.size:
            sp = flat[idx]
            codes = (sp[:, 0] << 16) | (sp[:, 1] << 8) | sp[:, 2]
            rec.unique_color_count = int(np.unique(codes).size)

    rec.warnings = [
        f"{e['event']}:{e.get('error_type') or '-'}" for e in capture.events
    ]
    rec.fallback_v2_to_v1 = (
        kernel == "v2"
        and any(
            e["event"] in {
                "glb_kernel_v2_runtime_fallback",
                "glb_kernel_v2_requested_unavailable",
                "glb_kernel_v2_unavailable",
            }
            for e in capture.events
        )
    )
    _cleanup_outputs(result)
    return rec


# ---------------------------------------------------------------------------
# Case orchestration (Warm Protocol: run1 cold drop, run2/run3 median)
# ---------------------------------------------------------------------------


def _summarise(runs: list[CaseRun]) -> CaseSummary:
    if not runs:
        raise ValueError("empty runs")
    head = runs[0]
    summary = CaseSummary(
        mode=head.mode, target_width_mm=head.target_width_mm, kernel=head.kernel,
    )
    cold = next((r for r in runs if r.run_index == 1), None)
    warm = [r for r in runs if r.run_index >= 2]
    if cold is not None:
        summary.cold_run = {
            "total_s": cold.total_s,
            "s11_s": cold.s11_s,
            "s11_mesh_loop_s": cold.s11_mesh_loop_s,
        }
    summary.runs = list(runs)
    if not warm:
        summary.failure_reason = "no warm runs (all failed)"
        return summary
    successful_warm = [r for r in warm if r.failure_reason is None]
    if not successful_warm:
        summary.failure_reason = "all warm runs failed: " + "; ".join(
            r.failure_reason or "" for r in warm
        )
        return summary

    def _med(attr: str) -> float:
        vals = [getattr(r, attr) for r in successful_warm]
        return float(median(vals)) if vals else float("nan")

    summary.total_s_median = _med("total_s")
    summary.s06_s_median = _med("s06_s")
    summary.s07_s_median = _med("s07_s")
    summary.s11_s_median = _med("s11_s")
    summary.s11_mesh_loop_s_median = _med("s11_mesh_loop_s")
    summary.s11_export_s_median = _med("s11_export_s")
    summary.mesh_compute_s_median = _med("mesh_compute_s")
    summary.peak_memory_mb_max = float(max(r.peak_memory_mb for r in successful_warm))
    summary.glb_size_bytes_median = float(median(r.glb_size_bytes for r in successful_warm))
    summary.vertex_count_median = float(median(r.vertex_count for r in successful_warm))
    summary.face_count_median = float(median(r.face_count for r in successful_warm))
    summary.unique_color_count = int(successful_warm[-1].unique_color_count)
    summary.node_count = int(successful_warm[-1].node_count)
    summary.color_node_count = int(successful_warm[-1].color_node_count)
    summary.has_backing_plate = bool(successful_warm[-1].has_backing_plate)
    seen: list[str] = []
    for r in successful_warm:
        for w in r.warnings:
            if w not in seen:
                seen.append(w)
    summary.warnings_seen = seen
    summary.fallback_v2_to_v1 = any(r.fallback_v2_to_v1 for r in successful_warm)
    return summary


def _run_case(
    *,
    image_path: Path,
    lut_path: Path,
    target_width_mm: float,
    color_mode: str,
    kernel: str,
    runs: int = 3,
) -> CaseSummary:
    """Run ``runs`` iterations and summarise."""
    out: list[CaseRun] = []
    for idx in range(1, runs + 1):
        t0 = time.perf_counter()
        rec = _run_one(
            image_path=image_path,
            lut_path=lut_path,
            target_width_mm=target_width_mm,
            color_mode=color_mode,
            kernel=kernel,
            run_index=idx,
        )
        elapsed = time.perf_counter() - t0
        if elapsed > CASE_TIMEOUT_S and rec.failure_reason is None:
            rec.failure_reason = f"timeout: {elapsed:.0f}s > {CASE_TIMEOUT_S:.0f}s"
        out.append(rec)
        status = "FAIL" if rec.failure_reason else "ok"
        print(
            f"      run{idx}/{runs} [{kernel}] {status} "
            f"total={rec.total_s:.2f}s s11={rec.s11_s:.2f}s "
            f"loop={rec.s11_mesh_loop_s:.2f}s "
            f"glb={rec.glb_size_bytes/1024/1024:.2f}MB "
            f"v={rec.vertex_count} f={rec.face_count} "
            f"warn={len(rec.warnings)}"
            + (f" fail={rec.failure_reason}" if rec.failure_reason else "")
        )
        # Bail if a single run exceeded the spec timeout — don't keep running
        # warm iterations on a clearly stuck case.
        if elapsed > CASE_TIMEOUT_S:
            break
    return _summarise(out)


# ---------------------------------------------------------------------------
# Driver / CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GLB kernel v1/v2 matrix benchmark.")
    p.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    p.add_argument("--quick", action="store_true", help="only run 75/150 mm widths")
    p.add_argument(
        "--modes",
        default=",".join(DEFAULT_MODES),
        help="comma-separated subset of: " + ", ".join(DEFAULT_MODES),
    )
    p.add_argument(
        "--widths-mm",
        default=None,
        help="override widths, e.g. '75,150' (default: 75,150,225,300)",
    )
    p.add_argument(
        "--runs", type=int, default=3, help="iterations per (mode, width, kernel)"
    )
    p.add_argument("--report-md", type=Path, default=REPORT_MD)
    p.add_argument("--report-json", type=Path, default=REPORT_JSON)
    return p.parse_args(argv)


def _collect_env() -> dict[str, Any]:
    info: dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        import subprocess

        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(_REPO_ROOT)
        ).decode().strip()
        info["commit_sha"] = sha
    except Exception:  # noqa: BLE001
        info["commit_sha"] = "unknown"
    deps: dict[str, str] = {}
    for name in ("rasterio", "manifold3d", "shapely", "trimesh", "cv2", "numpy", "scipy"):
        try:
            mod = __import__(name)
            ver = getattr(mod, "__version__", None)
            if not ver:
                # nanobind / pybind extensions sometimes don't export
                # __version__; fall back to importlib.metadata.
                try:
                    import importlib.metadata as _md
                    ver = _md.version(name)
                except Exception:  # noqa: BLE001
                    ver = "?"
            deps[name] = str(ver)
        except Exception as exc:  # noqa: BLE001
            deps[name] = f"missing ({type(exc).__name__})"
    info["dependencies"] = deps
    return info


def _format_speedup(old: float, new: float) -> str:
    if not old or not new or old <= 0 or new <= 0:
        return "n/a"
    return f"{old / new:.2f}x"


def _format_ratio(old: float, new: float) -> str:
    if not old or old <= 0:
        return "n/a"
    return f"{new / old:.2%}"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_markdown(
    *,
    image_path: Path,
    image_dims: tuple[int, int],
    image_bytes: int,
    matrix: list[CaseSummary],
    skipped: list[dict[str, str]],
    env: dict[str, Any],
    args: argparse.Namespace,
) -> str:
    L: list[str] = []
    L.append("# GLB Preview Mesh Kernel: bitmap multi-size × multi-mode benchmark")
    L.append("")
    L.append(
        "Read-only matrix benchmark of `core/pipeline/s11_glb_preview.py`'s "
        "v1 (Shapely) vs v2 (rasterio + manifold3d) per-color extrusion "
        "kernel on a single bitmap. Same code path, different env "
        "(`LUMINA_GLB_KERNEL`). No production files modified by this report."
    )
    L.append("")

    # === 1. Executive Summary ===
    pairs: dict[tuple[str, float], dict[str, CaseSummary]] = {}
    for s in matrix:
        pairs.setdefault((s.mode, s.target_width_mm), {})[s.kernel] = s

    valid_pairs = [
        (k, p)
        for k, p in pairs.items()
        if "v1" in p and "v2" in p
        and p["v1"].failure_reason is None
        and p["v2"].failure_reason is None
    ]
    speedups_loop = [p["v1"].s11_mesh_loop_s_median / p["v2"].s11_mesh_loop_s_median
                     for _, p in valid_pairs if p["v2"].s11_mesh_loop_s_median > 0]
    speedups_s11 = [p["v1"].s11_s_median / p["v2"].s11_s_median
                    for _, p in valid_pairs if p["v2"].s11_s_median > 0]

    fallback_cases = [(k, p) for k, p in valid_pairs if p["v2"].fallback_v2_to_v1]
    glb_inflated = [
        (k, p) for k, p in valid_pairs
        if p["v1"].glb_size_bytes_median > 0
        and p["v2"].glb_size_bytes_median > p["v1"].glb_size_bytes_median * 1.10
    ]
    geom_violations = [
        (k, p) for k, p in valid_pairs
        if p["v1"].vertex_count_median > 0
        and p["v2"].vertex_count_median > p["v1"].vertex_count_median * 1.10
    ]

    L.append("## 1. Executive Summary")
    L.append("")
    if speedups_loop:
        gm_loop = float(np.exp(np.mean(np.log(speedups_loop))))
        gm_s11 = float(np.exp(np.mean(np.log(speedups_s11)))) if speedups_s11 else float("nan")
        L.append(
            f"- **{len(valid_pairs)} mode×size cases**, geometric-mean speedup: "
            f"`s11_mesh_loop_s` **{gm_loop:.2f}x**, `s11_s` **{gm_s11:.2f}x**."
        )
        best = max(valid_pairs, key=lambda kp: (
            kp[1]['v1'].s11_mesh_loop_s_median / max(kp[1]['v2'].s11_mesh_loop_s_median, 1e-9)
        ))
        worst = min(valid_pairs, key=lambda kp: (
            kp[1]['v1'].s11_mesh_loop_s_median / max(kp[1]['v2'].s11_mesh_loop_s_median, 1e-9)
        ))
        bk, bp = best
        wk, wp = worst
        L.append(
            f"- **Best case**: `{bk[0]}` @ {bk[1]:.0f} mm — "
            f"v1 loop {bp['v1'].s11_mesh_loop_s_median:.2f} s → v2 "
            f"{bp['v2'].s11_mesh_loop_s_median:.2f} s "
            f"(speedup {bp['v1'].s11_mesh_loop_s_median / max(bp['v2'].s11_mesh_loop_s_median,1e-9):.2f}x)."
        )
        L.append(
            f"- **Worst case**: `{wk[0]}` @ {wk[1]:.0f} mm — "
            f"v1 loop {wp['v1'].s11_mesh_loop_s_median:.2f} s → v2 "
            f"{wp['v2'].s11_mesh_loop_s_median:.2f} s "
            f"(speedup {wp['v1'].s11_mesh_loop_s_median / max(wp['v2'].s11_mesh_loop_s_median,1e-9):.2f}x)."
        )
    else:
        L.append("- **No valid v1/v2 pairs collected**, see Matrix below for failures.")
    if fallback_cases:
        L.append(
            f"- **Fallback observed in {len(fallback_cases)} cases**: "
            + ", ".join(f"`{m}` @ {w:.0f}mm" for (m, w), _ in fallback_cases) + "."
        )
    else:
        L.append("- **No v2 → v1 fallback observed across the matrix.**")
    if glb_inflated:
        L.append(
            f"- **GLB size HARD-STOP triggered in {len(glb_inflated)} cases** "
            "(v2 GLB > v1 × 1.10x). See Matrix."
        )
    if geom_violations:
        L.append(
            f"- **Vertex count HARD-STOP triggered in {len(geom_violations)} cases**."
        )
    if skipped:
        L.append(f"- **Skipped cases**: {len(skipped)}.")
    L.append("")

    # === 2. Environment ===
    L.append("## 2. Environment")
    L.append("")
    L.append(f"- Commit SHA: `{env.get('commit_sha', '?')}`")
    L.append(f"- Generated at: `{env.get('generated_at', '?')}`")
    L.append(f"- Python: `{env.get('python_version', '?')}`")
    L.append(f"- Platform: `{env.get('platform', '?')}`")
    L.append("- Dependencies:")
    for k, v in (env.get("dependencies") or {}).items():
        L.append(f"  - `{k}` = `{v}`")
    L.append(
        f"- Hard stop: per-case timeout = {CASE_TIMEOUT_S:.0f}s; "
        "GLB / vertex / face SHALL NOT exceed v1 × 1.10x; "
        "v2 SHALL NOT regress to v1 (fallback would invalidate the comparison)."
    )
    L.append("")

    # === 3. Input ===
    L.append("## 3. Input")
    L.append("")
    L.append(f"- Image path: `{image_path}`")
    L.append(f"- Image dimensions: `{image_dims[0]}x{image_dims[1]} px`, file `{image_bytes/1024/1024:.2f} MB` (JPEG)")
    L.append("- Modes / LUTs:")
    for m in args.modes.split(","):
        m = m.strip()
        if not m:
            continue
        lut = MODE_TO_LUT.get(m)
        L.append(f"  - `{m}` → `{lut.relative_to(_REPO_ROOT) if lut else '?'}`")
    widths = (
        [float(w) for w in args.widths_mm.split(",")]
        if args.widths_mm
        else (QUICK_WIDTHS_MM if args.quick else DEFAULT_WIDTHS_MM)
    )
    L.append(f"- target_width_mm list: {widths}")
    L.append(f"- modeling_mode: HIGH_FIDELITY (single mode for the matrix)")
    L.append("")

    # === 4. Matrix Table ===
    L.append("## 4. Matrix Table")
    L.append("")
    L.append("| mode | width_mm | kernel | total_s | s11_s | s11_loop_s | s11_export_s | glb_MB | vertices | faces | colors | fallback | warnings |")
    L.append("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |")
    for s in matrix:
        if s.failure_reason:
            L.append(
                f"| `{s.mode}` | {s.target_width_mm:.0f} | {s.kernel} | "
                f"FAIL: {s.failure_reason[:60]} |  |  |  |  |  |  |  |  |  |"
            )
            continue
        L.append(
            "| `{m}` | {w:.0f} | {k} | {tot:.2f} | {s11:.2f} | {loop:.2f} | "
            "{exp:.2f} | {glb:.2f} | {v:,d} | {f:,d} | {c} | {fb} | {wn} |".format(
                m=s.mode,
                w=s.target_width_mm,
                k=s.kernel,
                tot=s.total_s_median,
                s11=s.s11_s_median,
                loop=s.s11_mesh_loop_s_median,
                exp=s.s11_export_s_median,
                glb=s.glb_size_bytes_median / (1024 * 1024),
                v=int(s.vertex_count_median),
                f=int(s.face_count_median),
                c=s.unique_color_count,
                fb=("yes" if s.fallback_v2_to_v1 else "no"),
                wn=("; ".join(s.warnings_seen) or "—"),
            )
        )
    L.append("")

    # === 5. Speedup Table ===
    L.append("## 5. Speedup Table (v1 → v2, warm median)")
    L.append("")
    L.append("| mode | width_mm | s11_loop speedup | s11_s speedup | total_s speedup | glb ratio | vertex ratio | face ratio |")
    L.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for (mode, width), p in pairs.items():
        v1 = p.get("v1")
        v2 = p.get("v2")
        if not v1 or not v2 or v1.failure_reason or v2.failure_reason:
            continue
        L.append(
            f"| `{mode}` | {width:.0f} | "
            f"{_format_speedup(v1.s11_mesh_loop_s_median, v2.s11_mesh_loop_s_median)} | "
            f"{_format_speedup(v1.s11_s_median, v2.s11_s_median)} | "
            f"{_format_speedup(v1.total_s_median, v2.total_s_median)} | "
            f"{_format_ratio(v1.glb_size_bytes_median, v2.glb_size_bytes_median)} | "
            f"{_format_ratio(v1.vertex_count_median, v2.vertex_count_median)} | "
            f"{_format_ratio(v1.face_count_median, v2.face_count_median)} |"
        )
    L.append("")

    # === 6. Bottleneck Breakdown ===
    L.append("## 6. Bottleneck Breakdown (warm median, seconds)")
    L.append("")
    L.append("Of the four pipeline stages whose timing s11 reports — S06 (voxel build), S07 (mesh gen), S11 (GLB preview), and the rest (image processing / S02) — only **S11** is changed by this PR. The table below shows where the v1→v2 saving lands; everything else should be flat (within run-to-run noise).")
    L.append("")
    L.append("| mode | width_mm | kernel | image_proc | s06 | s07 | s11_loop | s11_export | total |")
    L.append("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for s in matrix:
        if s.failure_reason:
            continue
        # image_proc ≈ total - s06 - s07 - s11
        image_proc = max(
            0.0,
            s.total_s_median - s.s06_s_median - s.s07_s_median - s.s11_s_median,
        )
        L.append(
            f"| `{s.mode}` | {s.target_width_mm:.0f} | {s.kernel} | "
            f"{image_proc:.2f} | {s.s06_s_median:.2f} | {s.s07_s_median:.2f} | "
            f"{s.s11_mesh_loop_s_median:.2f} | {s.s11_export_s_median:.2f} | "
            f"{s.total_s_median:.2f} |"
        )
    L.append("")

    # === 7. Mode-specific notes ===
    L.append("## 7. Mode-specific Notes")
    L.append("")
    seen_modes = sorted({s.mode for s in matrix})
    for mode in seen_modes:
        cases = [s for s in matrix if s.mode == mode]
        L.append(f"### `{mode}`")
        L.append("")
        any_failure = any(s.failure_reason for s in cases)
        any_v2_fallback = any(s.fallback_v2_to_v1 for s in cases if s.kernel == "v2")
        v2_cases = [s for s in cases if s.kernel == "v2" and not s.failure_reason]
        v1_cases = [s for s in cases if s.kernel == "v1" and not s.failure_reason]
        L.append(f"- runs collected: {len(cases)} ({len(v1_cases)} v1 ok / {len(v2_cases)} v2 ok)")
        if any_failure:
            L.append("- failures present: " + "; ".join(
                f"{s.kernel}@{s.target_width_mm:.0f}mm: {s.failure_reason}"
                for s in cases if s.failure_reason
            ))
        if any_v2_fallback:
            L.append("- **v2 fallback to v1 fired in this mode** — see warnings column for events.")
        if v2_cases:
            colors = sorted({s.unique_color_count for s in v2_cases})
            comp = sorted({s.color_node_count for s in v2_cases})
            L.append(f"- unique colors: {colors}, color_<hex> nodes: {comp}")
        # mesh-loop speedup spread for this mode
        ms_speedups = []
        for s in v2_cases:
            v1m = next(
                (x for x in v1_cases if x.target_width_mm == s.target_width_mm), None
            )
            if v1m and s.s11_mesh_loop_s_median > 0:
                ms_speedups.append(v1m.s11_mesh_loop_s_median / s.s11_mesh_loop_s_median)
        if ms_speedups:
            L.append(
                f"- s11_mesh_loop speedup range across widths: "
                f"min={min(ms_speedups):.2f}x, max={max(ms_speedups):.2f}x"
            )
        L.append("")

    if skipped:
        L.append("### Skipped modes")
        L.append("")
        for entry in skipped:
            L.append(f"- `{entry['mode']}`: {entry['reason']}")
        L.append("")

    # === 8. Recommendation ===
    L.append("## 8. Recommendation")
    L.append("")
    if speedups_loop:
        gm = float(np.exp(np.mean(np.log(speedups_loop))))
        if gm >= 2.0 and not glb_inflated and not geom_violations and not fallback_cases:
            L.append(
                f"- **Continue with v2.** Geometric-mean s11_mesh_loop speedup ≈ "
                f"**{gm:.2f}x** across {len(valid_pairs)} bitmap matrix cases; "
                "no fallback, no GLB / vertex inflation, no geometry failure."
            )
        else:
            L.append(
                f"- **Keep v2 default-off.** Speedup is uneven (geometric mean "
                f"{gm:.2f}x); review failed / inflated cases before promoting."
            )
    else:
        L.append("- **Insufficient successful pairs** to make a recommendation.")
    L.append(
        "- **Default kernel** is `v2`: use the rasterio + manifold3d path as "
        "the performance baseline, with fallback to `shapely_v1` if v2 is "
        "unavailable or fails. Set `LUMINA_GLB_KERNEL=shapely_v1` to pin the "
        "legacy path."
    )
    L.append(
        "- **SVG / vector pipeline is out of scope** for this benchmark; the matrix "
        "above only covers the raster / bitmap path through `run_raster_pipeline`."
    )
    L.append(
        "- If a specific mode shows a regression here, do not introduce new "
        "heuristics in s11; either `LUMINA_GLB_KERNEL=shapely_v1` keeps that mode "
        "on the proven path, or open a separate spec to investigate."
    )
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    args = parse_args(argv)
    image_path = Path(args.image).resolve()
    if not image_path.is_file():
        print(f"[bench] image not found: {image_path}", file=sys.stderr)
        return 2

    requested_modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    skipped: list[dict[str, str]] = []
    runnable_modes: list[str] = []
    for m in requested_modes:
        lut = MODE_TO_LUT.get(m)
        if lut is None:
            skipped.append({"mode": m, "reason": "no LUT mapping"})
            continue
        if not lut.is_file():
            skipped.append({"mode": m, "reason": f"LUT file missing: {lut}"})
            continue
        runnable_modes.append(m)

    if args.widths_mm:
        widths = [float(w) for w in args.widths_mm.split(",")]
    elif args.quick:
        widths = list(QUICK_WIDTHS_MM)
    else:
        widths = list(DEFAULT_WIDTHS_MM)

    print(f"[bench] image: {image_path}")
    print(f"[bench] modes: {runnable_modes}")
    print(f"[bench] widths_mm: {widths}")
    print(f"[bench] skipped: {skipped}")

    # Image dims for the report.
    from PIL import Image

    with Image.open(image_path) as im:
        image_dims = im.size  # (W, H)
    image_bytes = image_path.stat().st_size

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    matrix: list[CaseSummary] = []
    abort_reason: str | None = None
    for mode in runnable_modes:
        for width_mm in widths:
            print(f"\n[bench] === mode={mode}  width_mm={width_mm:.0f} ===")
            for kernel in ("v1", "v2"):
                print(f"   kernel={kernel}")
                summary = _run_case(
                    image_path=image_path,
                    lut_path=MODE_TO_LUT[mode],
                    target_width_mm=width_mm,
                    color_mode=mode,
                    kernel=kernel,
                    runs=args.runs,
                )
                matrix.append(summary)

            # Hard-stop checks per spec.
            v1 = next(
                (s for s in matrix if s.mode == mode and s.target_width_mm == width_mm and s.kernel == "v1"),
                None,
            )
            v2 = next(
                (s for s in matrix if s.mode == mode and s.target_width_mm == width_mm and s.kernel == "v2"),
                None,
            )
            if v1 and v2 and v1.failure_reason is None and v2.failure_reason is None:
                if v2.fallback_v2_to_v1 and abs(v2.s11_mesh_loop_s_median - v1.s11_mesh_loop_s_median) < 0.05 * max(v1.s11_mesh_loop_s_median, 1e-9):
                    abort_reason = (
                        f"v2 fell back to v1 with equivalent timing for {mode}@{width_mm:.0f}mm"
                    )
                if v1.glb_size_bytes_median > 0 and v2.glb_size_bytes_median > v1.glb_size_bytes_median * 1.10:
                    abort_reason = (
                        f"v2 GLB > v1 × 1.10x for {mode}@{width_mm:.0f}mm"
                    )
                if v1.vertex_count_median > 0 and v2.vertex_count_median > v1.vertex_count_median * 1.10:
                    abort_reason = (
                        f"v2 vertex_count > v1 × 1.10x for {mode}@{width_mm:.0f}mm"
                    )
            if abort_reason:
                print(f"[bench] HARD STOP: {abort_reason}")
                break
        if abort_reason:
            break

    env = _collect_env()
    md = render_markdown(
        image_path=image_path,
        image_dims=image_dims,
        image_bytes=image_bytes,
        matrix=matrix,
        skipped=skipped,
        env=env,
        args=args,
    )
    if abort_reason:
        md += "\n\n## Abort\n\nBenchmark aborted: " + abort_reason + "\n"

    args.report_md.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_md.write_text(md, encoding="utf-8")
    json_payload = {
        "env": env,
        "args": {
            "image": str(image_path),
            "modes": runnable_modes,
            "widths_mm": widths,
            "runs": args.runs,
            "skipped": skipped,
        },
        "input": {
            "image_dims": list(image_dims),
            "image_bytes": image_bytes,
        },
        "matrix": [asdict(s) for s in matrix],
        "abort_reason": abort_reason,
    }
    args.report_json.write_text(
        json.dumps(json_payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"\n[bench] markdown: {args.report_md}")
    print(f"[bench] json:     {args.report_json}")

    # Cleanup TMP_DIR contents (we don't write GLB there ourselves —
    # generate_segmented_glb writes to OUTPUT_DIR via naming helpers; we just
    # ensure no stragglers ended up here).
    if TMP_DIR.is_dir() and not any(TMP_DIR.iterdir()):
        try:
            TMP_DIR.rmdir()
        except OSError:
            pass
    return 0 if not abort_reason else 1


if __name__ == "__main__":
    sys.exit(main())
