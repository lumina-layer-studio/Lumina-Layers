"""Profile one SVG/vector GLB preview kernel with lightweight 3MF stubs.

The regular vector branch also exports a full 3MF and cover thumbnail before
the GLB preview. This helper keeps the branch's SVG business rules, but stubs
those unrelated export costs so V1/V2 GLB preview timings are easier to read.
"""

from __future__ import annotations

import argparse
import gzip
import json
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


def _stub_heavy_non_glb_work() -> None:
    from core.pipeline import vector_branch
    import utils.bambu_3mf_writer as bambu_writer

    def fake_export_scene_with_bambu_metadata(*args: Any, **kwargs: Any) -> str:
        output_path = kwargs.get("output_path")
        if output_path is None and len(args) >= 2:
            output_path = args[1]
        if output_path is None:
            raise RuntimeError("output_path is required")
        path = Path(str(output_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Lumina profile stub 3MF\n")
        return str(path)

    def fake_rasterize_svg(*_args: Any, **_kwargs: Any) -> np.ndarray:
        rgba = np.zeros((8, 8, 4), dtype=np.uint8)
        rgba[..., 3] = 255
        return rgba

    bambu_writer.export_scene_with_bambu_metadata = fake_export_scene_with_bambu_metadata
    vector_branch.rasterize_svg = fake_rasterize_svg


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


def _run_once(svg_path: Path, kernel: str, lut_path: Path) -> dict[str, object]:
    from config import ModelingMode
    from core.pipeline import coordinator
    import core.vector_engine as vector_engine

    _stub_heavy_non_glb_work()
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()
    os.environ["LUMINA_VECTOR_GLB_KERNEL"] = kernel
    os.environ["LUMINA_VECTOR_SKIP_2D_PREVIEW"] = "1"

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
    elapsed_s = time.perf_counter() - started
    timings = dict(result.get("vector_timing") or {})
    result_tuple = result.get("result_tuple") or ()
    glb_path = result_tuple[1] if len(result_tuple) > 1 else None
    return {
        "svg": str(svg_path),
        "kernel": kernel,
        "elapsed_s": round(elapsed_s, 6),
        "timings": timings,
        "error": result.get("error"),
        "glb": _summarize_glb(glb_path),
    }


def main() -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("svg", type=Path)
    parser.add_argument("--kernel", choices=("v1", "v2"), required=True)
    parser.add_argument("--lut", type=Path, default=DEFAULT_LUT_PATH)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    if not args.svg.exists():
        raise FileNotFoundError(f"SVG not found: {args.svg}")
    if not args.lut.exists():
        raise FileNotFoundError(f"LUT not found: {args.lut}")

    row = _run_once(args.svg, args.kernel, args.lut)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(row, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0 if row.get("error") is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
