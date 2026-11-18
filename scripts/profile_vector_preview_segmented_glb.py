"""Profile SVG frontend preview-cache GLB generation with V1/V2 kernels.

This measures the path used by the in-app 3D preview after SVG preview:
``_run_vector_preview_branch`` builds the preview cache, then
``generate_segmented_glb`` exports the color-segmented GLB without changing
runtime material data.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_LUT_PATH = ROOT / "tests/fixtures/lut_regression" / "彩多屋" / "4色" / "RYBW" / "lumina_lut.json"


class _StructuredEventCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.events: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        event = getattr(record, "event", None)
        if not event:
            return
        self.events.append(
            {
                "event": event,
                "error_type": getattr(record, "error_type", None),
                "error_message": getattr(record, "error_message", None),
                "fallback_kernel": getattr(record, "fallback_kernel", None),
            }
        )


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
        }
    return value


def _copy_cache_for_glb(cache: dict[str, object]) -> dict[str, object]:
    copied: dict[str, object] = {}
    for key, value in cache.items():
        if isinstance(value, np.ndarray):
            copied[key] = value.copy()
        elif key in {"color_conf", "lut_metadata", "preview_colors", "slot_names"}:
            copied[key] = copy.deepcopy(value)
        elif key in {
            "matched_rgb",
            "mask_solid",
            "backing_mask",
            "target_w",
            "target_h",
            "target_width_mm",
            "pixel_scale",
            "backing_color_id",
            "glb_max_meshes",
        }:
            copied[key] = copy.deepcopy(value)
    return copied


def _summarize_glb(path_value: object) -> dict[str, object] | None:
    if not path_value:
        return None
    path = Path(str(path_value))
    if not path.exists():
        return {"path": str(path), "exists": False}
    raw = path.read_bytes()
    return {
        "path": str(path),
        "exists": True,
        "bytes": len(raw),
        "gzip_bytes": len(gzip.compress(raw, compresslevel=6)),
    }


def _build_preview_cache(svg_path: Path, lut_path: Path, target_width_mm: float) -> dict[str, object]:
    from core.pipeline.vector_branch import _run_vector_preview_branch

    ctx: dict[str, object] = {
        "image_path": str(svg_path),
        "actual_lut_path": str(lut_path),
        "color_mode": "4-Color",
        "target_width_mm": float(target_width_mm),
        "quantize_colors": 64,
        "backing_color_id": 0,
        "is_dark": True,
        "lut_metadata": None,
    }
    started = time.perf_counter()
    result = _run_vector_preview_branch(ctx)
    elapsed_s = time.perf_counter() - started
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    cache = result.get("cache")
    if not isinstance(cache, dict):
        raise RuntimeError("vector preview branch did not return cache")
    return {
        "cache": cache,
        "elapsed_s": elapsed_s,
        "vector_preview_timing": result.get("vector_preview_timing"),
    }


def _run_glb(cache: dict[str, object], kernel: str, output_path: Path) -> dict[str, object]:
    from core.pipeline.s11_glb_preview import generate_segmented_glb

    if kernel == "v1":
        os.environ["LUMINA_GLB_KERNEL"] = "v1"
    elif kernel == "v2":
        os.environ["LUMINA_GLB_KERNEL"] = "v2"
    else:
        raise ValueError(f"unknown kernel: {kernel}")

    capture = _StructuredEventCapture()
    target_logger = logging.getLogger("lumina.core.pipeline.s11_glb_preview")
    target_logger.addHandler(capture)
    local_cache = _copy_cache_for_glb(cache)
    started = time.perf_counter()
    try:
        glb_path = generate_segmented_glb(local_cache, output_path=str(output_path))
    finally:
        target_logger.removeHandler(capture)
    elapsed_s = time.perf_counter() - started
    return {
        "kernel": kernel,
        "elapsed_s": round(elapsed_s, 6),
        "glb": _summarize_glb(glb_path),
        "timings": _json_safe(local_cache.get("_segmented_glb_timings") or {}),
        "warnings": capture.events,
        "color_contour_count": len(local_cache.get("color_contours") or {}),
    }


def main() -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("svg", type=Path)
    parser.add_argument("--lut", type=Path, default=DEFAULT_LUT_PATH)
    parser.add_argument("--target-width-mm", type=float, default=80.0)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    if not args.svg.exists():
        raise FileNotFoundError(f"SVG not found: {args.svg}")
    if not args.lut.exists():
        raise FileNotFoundError(f"LUT not found: {args.lut}")

    preview = _build_preview_cache(args.svg, args.lut, args.target_width_mm)
    cache = preview["cache"]
    out_base = args.json_out.with_suffix("")
    rows = [
        _run_glb(cache, "v1", out_base.with_name(out_base.name + "_v1.glb")),
        _run_glb(cache, "v2", out_base.with_name(out_base.name + "_v2.glb")),
    ]

    payload = {
        "svg": str(args.svg),
        "target_width_mm": float(args.target_width_mm),
        "preview_cache_elapsed_s": round(float(preview["elapsed_s"]), 6),
        "preview_cache_summary": {
            "target_w": int(cache.get("target_w", 0) or 0),
            "target_h": int(cache.get("target_h", 0) or 0),
            "mask_solid_pixels": int(np.count_nonzero(cache.get("mask_solid"))),
            "unique_colors": int(
                np.unique(
                    np.asarray(cache.get("matched_rgb"), dtype=np.uint8).reshape(-1, 3),
                    axis=0,
                ).shape[0]
            )
            if cache.get("matched_rgb") is not None
            else 0,
        },
        "rows": rows,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
