"""Profile SVG/vector GLB V1 vs V2 preview export on fixture SVG files."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_LUT_PATH = "tests/fixtures/lut_regression/彩多屋/4色/RYBW/lumina_lut.json"


def _run_once(svg_path: Path, kernel: str, *, lut_path: Path) -> dict[str, object]:
    from config import ModelingMode
    from core.pipeline import coordinator

    os.environ["LUMINA_VECTOR_GLB_KERNEL"] = kernel
    ctx = {
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
    started = time.perf_counter()
    result = coordinator._run_vector_branch(ctx)
    elapsed = time.perf_counter() - started
    timings = result.get("vector_timing") or {}
    result_tuple = result.get("result_tuple") or ()
    glb_path = result_tuple[1] if len(result_tuple) > 1 else None
    return {
        "svg": str(svg_path),
        "kernel": kernel,
        "elapsed_s": elapsed,
        "export_glb_s": timings.get("export_glb_s"),
        "mesh_total_s": timings.get("mesh_total_s"),
        "vector_branch_total_s": timings.get("vector_branch_total_s"),
        "error": result.get("error"),
        "glb_path": glb_path,
    }


def main() -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("svg", nargs="+", help="SVG fixture paths")
    parser.add_argument("--lut", default=DEFAULT_LUT_PATH)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--json-out", default="logs/vector_glb_v2_profile.json")
    args = parser.parse_args()

    lut_path = Path(args.lut)
    if not lut_path.exists():
        raise FileNotFoundError(f"LUT file not found: {lut_path}")

    rows: list[dict[str, object]] = []
    for svg in args.svg:
        path = Path(svg)
        for kernel in ("v1", "v2"):
            for _ in range(args.runs):
                rows.append(_run_once(path, kernel, lut_path=lut_path))

    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for kernel in ("v1", "v2"):
        values = [
            float(row["elapsed_s"])
            for row in rows
            if row["kernel"] == kernel and row.get("error") is None
        ]
        if values:
            print(f"{kernel}: median elapsed_s={statistics.median(values):.3f}")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
