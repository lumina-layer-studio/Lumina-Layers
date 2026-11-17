"""Stage-3 profiling runner for S06/S07/S11 performance baselining.

Outputs:
  - artifacts/perf_baseline.json
  - docs/perf_baseline.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median, pstdev
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import ModelingMode
from core.pipeline.coordinator import run_raster_pipeline

ARTIFACTS_DIR = ROOT / "artifacts"
BASELINE_JSON = ARTIFACTS_DIR / "perf_baseline.json"
LATEST_JSON = ARTIFACTS_DIR / "perf_latest.json"
BASELINE_MD = ROOT / "docs" / "perf_baseline.md"

DEFAULT_LUT = ROOT / "tests/fixtures/lut_regression" / "Custom" / "lumina_lut.json"
DEFAULT_IMAGE = ROOT / "TCT.jpg"

WARN_THRESHOLD_PCT = 15
FAIL_THRESHOLD_PCT = 30


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    image_path: Path
    target_width_mm: float


def _require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"Required file not found: {path}")
    return path


def _build_ctx(image_path: Path, lut_path: Path, target_width_mm: float) -> dict[str, Any]:
    return {
        "image_path": str(image_path),
        "lut_path": str(lut_path),
        "target_width_mm": target_width_mm,
        "spacer_thick": 1.2,
        "structure_mode": "single-sided",
        "color_mode": "4-Color",
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


def _timing_value(ctx: dict[str, Any], key: str) -> float:
    hifi_timings = ctx.get("_hifi_timings") or {}
    value = hifi_timings.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _cleanup_outputs(ctx: dict[str, Any]) -> None:
    candidates = [
        ctx.get("out_path"),
        ctx.get("glb_path"),
        ctx.get("color_recipe_path"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = Path(candidate)
            if path.exists():
                path.unlink()
        except OSError:
            continue


def _run_once(spec: DatasetSpec, lut_path: Path) -> dict[str, Any]:
    ctx = _build_ctx(spec.image_path, lut_path, spec.target_width_mm)
    tracemalloc.start()
    t0 = time.perf_counter()
    result = run_raster_pipeline(ctx)
    elapsed_s = time.perf_counter() - t0
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    if result.get("error"):
        raise RuntimeError(f"{spec.name} failed: {result['error']}")

    out_path = result.get("out_path")
    glb_path = result.get("glb_path")
    recipe_path = result.get("color_recipe_path")

    output_bytes = 0
    for p in [out_path, glb_path, recipe_path]:
        if p and Path(p).exists():
            output_bytes += Path(p).stat().st_size

    input_bytes = spec.image_path.stat().st_size + lut_path.stat().st_size

    metrics = {
        "total_s": elapsed_s,
        "s06_s": _stage_seconds(result, "S06", "voxel_build_s"),
        "s07_s": _stage_seconds(result, "S07", "mesh_gen_s"),
        "s11_s": _stage_seconds(result, "S11", "glb_preview_s"),
        "mesh_compute_s": _timing_value(result, "mesh_compute_s"),
        "mesh_apply_transform_s": _timing_value(result, "mesh_apply_transform_s"),
        "s11_unique_s": _timing_value(result, "s11_unique_s"),
        "s11_merge_s": _timing_value(result, "s11_merge_s"),
        "s11_mask_build_s": _timing_value(result, "s11_mask_build_s"),
        "s11_mesh_loop_s": _timing_value(result, "s11_mesh_loop_s"),
        "s11_backing_s": _timing_value(result, "s11_backing_s"),
        "s11_export_s": _timing_value(result, "s11_export_s"),
        "peak_memory_mb": peak_bytes / (1024 * 1024),
        "estimated_io_read_bytes": input_bytes,
        "estimated_io_write_bytes": output_bytes,
        "estimated_io_total_bytes": input_bytes + output_bytes,
    }

    _cleanup_outputs(result)
    return metrics


def _dataset_specs() -> list[DatasetSpec]:
    image = _require_file(DEFAULT_IMAGE)
    return [
        DatasetSpec(name="small", image_path=image, target_width_mm=60.0),
        DatasetSpec(name="medium", image_path=image, target_width_mm=120.0),
        DatasetSpec(name="large", image_path=image, target_width_mm=225.0),
    ]


def _summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    keys = [
        "total_s",
        "s06_s",
        "s07_s",
        "s11_s",
        "mesh_compute_s",
        "mesh_apply_transform_s",
        "s11_unique_s",
        "s11_merge_s",
        "s11_mask_build_s",
        "s11_mesh_loop_s",
        "s11_backing_s",
        "s11_export_s",
        "peak_memory_mb",
        "estimated_io_read_bytes",
        "estimated_io_write_bytes",
        "estimated_io_total_bytes",
    ]
    summary: dict[str, Any] = {}
    for key in keys:
        vals = [float(r[key]) for r in runs]
        summary[key] = {
            "median": median(vals),
            "min": min(vals),
            "max": max(vals),
            "stdev": pstdev(vals) if len(vals) > 1 else 0.0,
        }
    return summary


def _build_dataset_metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summarize_runs(runs)
    cold_start = runs[0] if runs else {}
    warm_runs = runs[1:] if len(runs) > 1 else runs
    warm_summary = _summarize_runs(warm_runs) if warm_runs else _summarize_runs(runs)

    for key in summary.keys():
        summary[key]["warm_median"] = warm_summary[key]["median"]

    return {
        "cold_start": cold_start,
        "warm_runs": warm_runs,
        "warm_summary": warm_summary,
        "summary": summary,
    }


def _write_markdown(payload: dict[str, Any], out_path: Path) -> None:
    generated_at = payload["generated_at"]
    machine = payload["machine"]
    datasets = payload["datasets"]

    stage_rank: list[tuple[str, float]] = []
    for stage in ["s06_s", "s07_s", "s11_s"]:
        medians = [float(ds["summary"][stage]["warm_median"]) for ds in datasets]
        stage_rank.append((stage, median(medians)))
    stage_rank.sort(key=lambda it: it[1], reverse=True)

    lines: list[str] = []
    lines.append("# Stage 3 Performance Baseline")
    lines.append("")
    lines.append(f"- Generated at: `{generated_at}`")
    lines.append(f"- Host: `{machine['hostname']}` | Platform: `{machine['platform']}`")
    lines.append(f"- Python: `{machine['python']}`")
    lines.append("- Profiling scope: `S06/S07/S11` and end-to-end `total_s`")
    lines.append(f"- Thresholds: `warn=+{WARN_THRESHOLD_PCT}%`, `fail=+{FAIL_THRESHOLD_PCT}%` (vs median baseline)")
    lines.append("")
    lines.append("## Baseline Table (median)")
    lines.append("")
    lines.append("| Dataset | total_s | S06_s | S07_s | S11_s | peak_memory_mb | io_total_mb |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for ds in datasets:
        summary = ds["summary"]
        io_mb = float(summary["estimated_io_total_bytes"]["median"]) / (1024 * 1024)
        lines.append(
            f"| {ds['name']} | {summary['total_s']['median']:.3f} | "
            f"{summary['s06_s']['median']:.3f} | {summary['s07_s']['median']:.3f} | "
            f"{summary['s11_s']['median']:.3f} | {summary['peak_memory_mb']['median']:.2f} | {io_mb:.2f} |"
        )
    lines.append("")
    lines.append("## Warm Baseline Table (run2/run3 median)")
    lines.append("")
    lines.append("| Dataset | total_s | S06_s | S07_s | S11_s | peak_memory_mb |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for ds in datasets:
        summary = ds["summary"]
        lines.append(
            f"| {ds['name']} | {summary['total_s']['warm_median']:.3f} | "
            f"{summary['s06_s']['warm_median']:.3f} | {summary['s07_s']['warm_median']:.3f} | "
            f"{summary['s11_s']['warm_median']:.3f} | {summary['peak_memory_mb']['warm_median']:.2f} |"
        )
    lines.append("")
    lines.append("## Bottleneck Ranking (cross-dataset median)")
    lines.append("")
    for idx, (stage, val) in enumerate(stage_rank, start=1):
        lines.append(f"{idx}. `{stage}`: {val:.3f}s")
    lines.append("")
    lines.append("## Warm Hotspots (Top 3 per dataset)")
    lines.append("")
    component_keys = [
        "mesh_compute_s",
        "mesh_apply_transform_s",
        "s11_unique_s",
        "s11_merge_s",
        "s11_mask_build_s",
        "s11_mesh_loop_s",
        "s11_backing_s",
        "s11_export_s",
    ]
    for ds in datasets:
        summary = ds["summary"]
        pairs: list[tuple[str, float]] = []
        for key in component_keys:
            value = float(summary.get(key, {}).get("warm_median", 0.0))
            if value > 0:
                pairs.append((key, value))
        pairs.sort(key=lambda item: item[1], reverse=True)
        lines.append(f"- {ds['name']}: " + ", ".join(f"`{k}`={v:.3f}s" for k, v in pairs[:3]))
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- `estimated_io_*` uses input/output file sizes as practical local proxy.")
    lines.append("- This baseline is local-machine authoritative for now (P2 stage-3 v3).")
    lines.append("- Cold-start (run1) is recorded separately; default regression checks use warm median.")
    lines.append("- This round is diagnosis-first; hotspot ranking is expected to guide the next focused optimization.")
    lines.append("- Re-run with `python scripts/profile_stage3.py` after substantial pipeline changes.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile Stage-3 pipeline performance.")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=BASELINE_JSON,
        help="Output JSON path (default: artifacts/perf_baseline.json).",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=BASELINE_MD,
        help="Output markdown path (default: docs/perf_baseline.md).",
    )
    parser.add_argument(
        "--skip-markdown",
        action="store_true",
        help="Do not write markdown report.",
    )
    parser.add_argument(
        "--also-write-latest",
        action="store_true",
        help="Also write artifacts/perf_latest.json for regression checks.",
    )
    # Custom-image trio: --image / --lut / --width-mm. Backward-compatible —
    # when all three are absent the script uses the existing TCT.jpg dataset.
    # Mixing one or two but not all three is rejected (exit 2) so the user
    # cannot accidentally measure with a default LUT against a custom image.
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="Custom image path. Must be combined with --lut and --width-mm.",
    )
    parser.add_argument(
        "--lut",
        type=Path,
        default=None,
        help="Custom LUT path (.npy / .json / .npz). Must be combined with --image and --width-mm.",
    )
    parser.add_argument(
        "--width-mm",
        type=float,
        default=None,
        dest="width_mm",
        help="Custom target width in mm. Must be combined with --image and --lut.",
    )
    args = parser.parse_args()
    custom_args = (args.image, args.lut, args.width_mm)
    custom_set = sum(arg is not None for arg in custom_args)
    if custom_set not in (0, 3):
        parser.error(
            "--image, --lut, and --width-mm must all be provided together "
            f"(or all omitted); got image={args.image} lut={args.lut} width-mm={args.width_mm}"
        )
    return args


def main() -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    args = _parse_args()
    if args.image is not None:
        # Custom dataset path — used by the GLB v2 spec to measure
        # Reference_Image baselines without disturbing the default
        # TCT.jpg regression coverage.
        lut_path = _require_file(args.lut)
        specs = [
            DatasetSpec(
                name="custom",
                image_path=_require_file(args.image),
                target_width_mm=float(args.width_mm),
            )
        ]
    else:
        lut_path = _require_file(DEFAULT_LUT)
        specs = _dataset_specs()

    payload: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": {
            "hostname": os.environ.get("COMPUTERNAME", "unknown"),
            "platform": os.name,
            "python": sys.version.split()[0],
        },
        "thresholds": {
            "warn_regression_pct": WARN_THRESHOLD_PCT,
            "fail_regression_pct": FAIL_THRESHOLD_PCT,
        },
        "runs_per_dataset": 3,
        "datasets": [],
    }

    for spec in specs:
        print(f"\n[profile] dataset={spec.name}, width_mm={spec.target_width_mm}")
        runs: list[dict[str, Any]] = []
        for idx in range(1, 4):
            print(f"[profile]   run {idx}/3 ...")
            run_metrics = _run_once(spec, lut_path)
            runs.append(run_metrics)
            print(
                f"[profile]   total={run_metrics['total_s']:.3f}s "
                f"s06={run_metrics['s06_s']:.3f}s "
                f"s07={run_metrics['s07_s']:.3f}s "
                f"s11={run_metrics['s11_s']:.3f}s "
                f"peak_mem={run_metrics['peak_memory_mb']:.2f}MB"
            )
        metrics = _build_dataset_metrics(runs)
        payload["datasets"].append(
            {
                "name": spec.name,
                "image_path": str(spec.image_path),
                "target_width_mm": spec.target_width_mm,
                "runs": runs,
                "cold_start": metrics["cold_start"],
                "warm_runs": metrics["warm_runs"],
                "warm_summary": metrics["warm_summary"],
                "summary": metrics["summary"],
            }
        )

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if not args.skip_markdown:
        _write_markdown(payload, args.output_md)
    if args.also_write_latest:
        LATEST_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n[profile] output json: {args.output_json}")
    if not args.skip_markdown:
        print(f"[profile] output markdown: {args.output_md}")
    if args.also_write_latest:
        print(f"[profile] latest json: {LATEST_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
