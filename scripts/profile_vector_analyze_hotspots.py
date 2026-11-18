#!/usr/bin/env python3
"""Profile SVG vector analyze-stage hotspots across one or more SVG files."""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import pstats
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.vector_engine import VectorProcessor  # noqa: E402


PROFILE_NEEDLES = (
    "analyze_svg",
    "_parse_svg",
    "_clip_occlusion",
    "_combine_evenodd_polygons",
    "_combine_nonzero_subpaths",
    "_parse_gradient_defs",
    "_sample_path_coords",
    "_flatten_segments",
    "_flatten_cubic",
    "_flatten_quadratic",
    "_normalize_contours",
    "_postprocess_clipped_shapes",
    "_split_disconnected_shapes",
    "STRtree",
    "query",
    "unary_union",
    "union_all",
    "symmetric_difference_all",
    "polygonize",
    "difference",
    "buffer",
    "make_valid",
)


def discover_svg_files(path: Path) -> list[Path]:
    """Return SVG files under ``path`` in deterministic path order."""

    candidate = Path(path)
    if candidate.is_file():
        return [candidate] if candidate.suffix.lower() == ".svg" else []
    if not candidate.exists():
        return []
    files = [
        item
        for item in candidate.rglob("*")
        if item.is_file() and item.suffix.lower() == ".svg"
    ]
    return sorted(files, key=str)


def _write_synthetic_compound_fixture(
    output_path: Path,
    *,
    grid_size: int = 189,
    total_cells: int = 35_587,
    path_groups: int = 49,
    viewbox_size: float = 160.0,
) -> dict[str, int | float | str]:
    """Write the deterministic fragmented-shape tail-latency fixture."""

    if grid_size <= 0 or total_cells <= 0 or path_groups <= 0:
        raise ValueError("fixture dimensions must be positive")
    if total_cells > grid_size * grid_size:
        raise ValueError("total_cells exceeds the synthetic grid capacity")
    if path_groups > total_cells:
        raise ValueError("path_groups cannot exceed total_cells")
    if viewbox_size <= 0.0:
        raise ValueError("viewbox_size must be positive")

    cell_size = viewbox_size / grid_size
    side = cell_size * 0.82
    colors = ("#ff0000", "#ffff00", "#0000ff", "#ffffff")
    chunks = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {viewbox_size:g} {viewbox_size:g}">'
    ]
    for group_index in range(path_groups):
        commands = []
        for flat_index in range(group_index, total_cells, path_groups):
            row, column = divmod(flat_index, grid_size)
            x_value = column * cell_size
            y_value = row * cell_size
            commands.append(
                f"M{x_value:.8f},{y_value:.8f}"
                f"h{side:.8f}v{side:.8f}h-{side:.8f}z"
            )
        chunks.append(
            f'<path d="{"".join(commands)}" '
            f'fill="{colors[group_index % len(colors)]}" '
            'fill-rule="nonzero"/>'
        )
    chunks.append("</svg>")
    payload = "".join(chunks).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return {
        "grid_size": grid_size,
        "total_cells": total_cells,
        "path_groups": path_groups,
        "viewbox_size": viewbox_size,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _profile_rows_from_raw_stats(
    raw_stats: dict[tuple[str, int, str], tuple[int, int, float, float, dict]],
    *,
    limit: int,
    selected_needles: tuple[str, ...] = PROFILE_NEEDLES,
) -> dict[str, list[dict[str, Any]]]:
    """Convert raw ``pstats`` entries into ranked top and selected rows."""

    rows = []
    selected = []
    for (filename, line, func), stat in raw_stats.items():
        primitive_calls, calls, tottime, cumtime, _callers = stat
        label = f"{Path(filename).name}:{line}:{func}"
        row = {
            "function": label,
            "calls": int(calls),
            "primitive_calls": int(primitive_calls),
            "tottime_s": round(float(tottime), 6),
            "cumtime_s": round(float(cumtime), 6),
        }
        rows.append(row)
        if any(needle in func or needle in label for needle in selected_needles):
            selected.append(row)

    rows.sort(key=lambda item: float(item["cumtime_s"]), reverse=True)
    selected.sort(key=lambda item: float(item["cumtime_s"]), reverse=True)
    return {"top": rows[:limit], "selected": selected[:limit]}


def _profile_summary(profile: cProfile.Profile, *, limit: int) -> dict[str, Any]:
    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumtime")
    stats.print_stats(limit)
    rows = _profile_rows_from_raw_stats(stats.stats, limit=limit)
    rows["top_cumtime_text"] = stream.getvalue()
    return rows


def _stage_value(sample: dict[str, Any], key: str) -> float:
    return float((sample.get("stage_timings") or {}).get(key, 0.0))


def _build_report(*, input_path: Path, samples: list[dict[str, Any]]) -> dict[str, Any]:
    ok_samples = [sample for sample in samples if sample.get("status") == "ok"]
    error_samples = [sample for sample in samples if sample.get("status") != "ok"]
    analysis_total = sum(float(sample.get("analysis_seconds", 0.0)) for sample in ok_samples)
    parse_total = sum(_stage_value(sample, "parse_s") for sample in ok_samples)
    occlusion_total = sum(_stage_value(sample, "occlusion_s") for sample in ok_samples)
    color_match_total = sum(_stage_value(sample, "color_match_s") for sample in ok_samples)
    stage_total = parse_total + occlusion_total + color_match_total
    slowest = {
        "analysis": sorted(
            ok_samples,
            key=lambda item: float(item.get("analysis_seconds", 0.0)),
            reverse=True,
        )[:5],
        "parse": sorted(ok_samples, key=lambda item: _stage_value(item, "parse_s"), reverse=True)[:5],
        "occlusion": sorted(
            ok_samples,
            key=lambda item: _stage_value(item, "occlusion_s"),
            reverse=True,
        )[:5],
    }
    return {
        "input": {"path": str(Path(input_path).resolve())},
        "summary": {
            "sample_count": len(samples),
            "ok_count": len(ok_samples),
            "error_count": len(error_samples),
            "analysis_total_seconds": round(analysis_total, 6),
            "stage_totals_seconds": {
                "parse": round(parse_total, 6),
                "occlusion": round(occlusion_total, 6),
                "color_match": round(color_match_total, 6),
                "unaccounted": round(max(0.0, analysis_total - stage_total), 6),
            },
        },
        "slowest": slowest,
        "samples": samples,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    stages = summary["stage_totals_seconds"]
    lines = [
        "# Vector Analyze Hotspots",
        "",
        f"- Samples: {summary['sample_count']}",
        f"- OK / ERROR: {summary['ok_count']} / {summary['error_count']}",
        f"- Analyze total: {summary['analysis_total_seconds']:.3f}s",
        f"- Stage totals: parse={stages['parse']:.3f}s, "
        f"occlusion={stages['occlusion']:.3f}s, "
        f"color_match={stages['color_match']:.3f}s, "
        f"unaccounted={stages['unaccounted']:.3f}s",
        "",
        "## Slowest Analyze",
        "",
    ]
    lines.extend(
        f"- `{sample['svg_name']}`: analyze={sample['analysis_seconds']:.3f}s, "
        f"parse={_stage_value(sample, 'parse_s'):.3f}s, "
        f"occlusion={_stage_value(sample, 'occlusion_s'):.3f}s, "
        f"shapes={sample.get('shape_count', 0)}"
        for sample in report["slowest"]["analysis"]
    )
    lines.extend(["", "## Slowest Occlusion", ""])
    lines.extend(
        f"- `{sample['svg_name']}`: occlusion={_stage_value(sample, 'occlusion_s'):.3f}s, "
        f"analyze={sample['analysis_seconds']:.3f}s, shapes={sample.get('shape_count', 0)}"
        for sample in report["slowest"]["occlusion"]
    )
    lines.extend(["", "## Selected Profile Hotspots", ""])
    for sample in report["slowest"]["analysis"]:
        selected = (sample.get("profile") or {}).get("selected", [])[:8]
        if not selected:
            continue
        lines.append(f"### {sample['svg_name']}")
        for row in selected:
            lines.append(
                f"- `{row['function']}`: cum={float(row['cumtime_s']):.3f}s, "
                f"self={float(row['tottime_s']):.3f}s, calls={row['calls']}"
            )
        lines.append("")
    error_samples = [sample for sample in report["samples"] if sample.get("status") != "ok"]
    if error_samples:
        lines.extend(["## Errors", ""])
        lines.extend(
            f"- `{sample.get('svg_name', 'unknown')}`: "
            f"{sample.get('error_type', 'Error')}: {sample.get('error_message', '')}"
            for sample in error_samples
        )
    return "\n".join(lines).rstrip() + "\n"


def _profile_svg(svg_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    processor = VectorProcessor(str(args.lut), args.color_mode)
    profile = cProfile.Profile()
    started = time.perf_counter()
    profile.enable()
    analysis = processor.analyze_svg(str(svg_path), target_width_mm=args.target_width_mm)
    profile.disable()
    elapsed = time.perf_counter() - started
    profile_summary = _profile_summary(profile, limit=args.profile_limit)
    return {
        "status": "ok",
        "svg_name": svg_path.name,
        "svg_path": str(svg_path.resolve()),
        "analysis_seconds": elapsed,
        "shape_count": len(getattr(analysis, "matched_shapes", []) or []),
        "stage_timings": dict(getattr(analysis, "stage_timings", {}) or {}),
        "profile": profile_summary,
    }


def _write_outputs(report: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "vector_analyze_hotspots.json"
    md_path = out_dir / "vector_analyze_hotspots.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def run(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if args.generate_compound_tail_fixture:
        metadata = _write_synthetic_compound_fixture(
            input_path,
            grid_size=args.fixture_grid_size,
            total_cells=args.fixture_total_cells,
            path_groups=args.fixture_path_groups,
            viewbox_size=args.fixture_viewbox_size,
        )
        print(json.dumps({"generated_fixture": metadata}, sort_keys=True))
    svg_files = discover_svg_files(input_path)
    if args.max_samples > 0:
        svg_files = svg_files[: args.max_samples]
    if not svg_files:
        print(f"No SVG files found under {input_path}", file=sys.stderr)
        return 2

    samples: list[dict[str, Any]] = []
    for index, svg_path in enumerate(svg_files, start=1):
        print(f"[{index}/{len(svg_files)}] {svg_path}")
        try:
            sample = _profile_svg(svg_path, args)
        except Exception as exc:
            sample = {
                "status": "error",
                "svg_name": svg_path.name,
                "svg_path": str(svg_path.resolve()),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        samples.append(sample)
    report = _build_report(input_path=input_path, samples=samples)
    outputs = _write_outputs(report, Path(args.out_dir))
    print(outputs["markdown"])
    return 0 if not any(sample.get("status") != "ok" for sample in samples) else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--lut", type=Path, default=REPO_ROOT / "tests/fixtures/lut_regression" / "Custom" / "lumina_lut.json")
    parser.add_argument("--color-mode", default="4-Color (RYBW)")
    parser.add_argument("--target-width-mm", type=float, default=80.0)
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--profile-limit", type=int, default=60)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / ".scratch" / "vector_analyze_hotspots")
    parser.add_argument("--generate-compound-tail-fixture", action="store_true")
    parser.add_argument("--fixture-grid-size", type=int, default=189)
    parser.add_argument("--fixture-total-cells", type=int, default=35_587)
    parser.add_argument("--fixture-path-groups", type=int, default=49)
    parser.add_argument("--fixture-viewbox-size", type=float, default=160.0)
    return parser.parse_args(argv)


if __name__ == "__main__":
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    raise SystemExit(run(parse_args(sys.argv[1:])))
