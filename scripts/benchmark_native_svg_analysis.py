#!/usr/bin/env python3
"""Benchmark the complete Lumina native-SVG ``VectorAnalysis`` entry point."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import re
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Set native math runtimes before NumPy/Shapely enter the process. This is one
# caller thread, matching the reference benchmark contract.
for _thread_variable in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[_thread_variable] = "1"

import shapely  # noqa: E402

from core import native_svg_adapter  # noqa: E402
from core.native_svg_adapter import NativeSvgFallback  # noqa: E402
from core.vector_engine import (  # noqa: E402
    VectorProcessor,
    _VECTOR_PARSE_CLIP_CACHE,
)
SUPPORTED_SCALE_FIXTURE = (
    REPO_ROOT
    / "native"
    / "lumina-svg-core"
    / "benchmarks"
    / "supported_scale_fixture.svg"
)
SUPPORTED_SCALE_PROVENANCE = (
    REPO_ROOT
    / "native"
    / "lumina-svg-core"
    / "benchmarks"
    / "supported_scale_fixture_provenance.json"
)
ALPHA_COMPOSITING_FIXTURE = (
    REPO_ROOT
    / "native"
    / "lumina-svg-core"
    / "benchmarks"
    / "alpha_compositing_fixture.svg"
)
LARGE_REGRESSION_MINIMUM_BYTES = 50 * 1024 * 1024


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _style_map(style: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        name, value = declaration.split(":", 1)
        declarations[name.strip().lower()] = value.strip().lower()
    return declarations


def _fixture_structure(path: Path) -> dict[str, Any]:
    root: ET.Element | None = None
    path_count = 0
    stroke_count = 0
    stroke_only_count = 0
    transform_count = 0
    clip_count = 0
    for _event, element in ET.iterparse(path, events=("start",)):
        if root is None:
            root = element
        tag = _local_name(element.tag)
        if tag == "path":
            path_count += 1
        if tag == "clipPath":
            clip_count += 1
        if "transform" in element.attrib:
            transform_count += 1
        style = _style_map(element.attrib.get("style", ""))
        stroke = element.attrib.get("stroke", style.get("stroke", "none"))
        fill = element.attrib.get("fill", style.get("fill", "black"))
        if stroke.strip().lower() != "none":
            stroke_count += 1
            if fill.strip().lower() == "none":
                stroke_only_count += 1

    if root is None:
        raise ValueError("empty_svg")
    view_box = root.attrib.get("viewBox", "").replace(",", " ").split()
    if len(view_box) == 4:
        canvas = [float(view_box[2]), float(view_box[3])]
    else:
        number = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)")

        def dimension(name: str) -> float:
            match = number.match(root.attrib.get(name, ""))
            return float(match.group()) if match else 0.0

        canvas = [dimension("width"), dimension("height")]
    return {
        "canvas_user_units": canvas,
        "path_count": path_count,
        "stroke_count": stroke_count,
        "stroke_only_count": stroke_only_count,
        "transform_count": transform_count,
        "clip_count": clip_count,
    }


def _command_output(args: list[str]) -> str:
    try:
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def _processor_name() -> str:
    if sys.platform == "darwin":
        return _command_output(["sysctl", "-n", "machdep.cpu.brand_string"])
    return platform.processor() or platform.machine()


def _memory_bytes() -> int:
    if sys.platform == "darwin":
        value = _command_output(["sysctl", "-n", "hw.memsize"])
        if value.isdigit():
            return int(value)
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except (ImportError, OSError):
        return 0


def _peak_rss_bytes() -> int:
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except (ImportError, ValueError):
        try:
            import psutil

            return int(psutil.Process().memory_info().rss)
        except (ImportError, OSError):
            return 0


def _system_swap_used_bytes() -> tuple[int, str]:
    if sys.platform == "darwin":
        output = _command_output(["sysctl", "-n", "vm.swapusage"])
        match = re.search(r"used\s*=\s*([0-9.]+)([KMG])", output)
        if match:
            multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3}
            return int(float(match.group(1)) * multiplier[match.group(2)]), (
                "system_vm.swapusage"
            )
    if sys.platform.startswith("linux"):
        values: dict[str, int] = {}
        try:
            for line in Path("/proc/meminfo").read_text("utf-8").splitlines():
                if line.startswith(("SwapTotal:", "SwapFree:")):
                    key, value, _unit = line.split()
                    values[key.rstrip(":")] = int(value) * 1024
            if {"SwapTotal", "SwapFree"} <= values.keys():
                return values["SwapTotal"] - values["SwapFree"], (
                    "system_proc_meminfo"
                )
        except (OSError, ValueError):
            pass
    try:
        import psutil

        return int(psutil.swap_memory().used), "system_psutil"
    except (ImportError, OSError, RuntimeError):
        return 0, "unavailable"


def _host_manifest() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "processor": _processor_name(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "memory_bytes": _memory_bytes(),
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _rounded(value: float) -> float:
    return round(float(value), 9)


def _geometry_wkb(geometry: Any) -> bytes:
    return bytes(
        shapely.to_wkb(
            geometry,
            byte_order=1,
            include_srid=False,
            output_dimension=2,
        )
    )


def _update_geometry(hasher: Any, geometry: Any) -> None:
    payload = _geometry_wkb(geometry)
    hasher.update(struct.pack("<Q", len(payload)))
    hasher.update(payload)


def _update_json(hasher: Any, value: Any) -> None:
    hasher.update(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _contributor_fingerprint_payload(contributor: Any) -> dict[str, Any]:
    if isinstance(contributor, dict):
        value = contributor.get
    else:
        value = lambda name, default=None: getattr(  # noqa: E731
            contributor, name, default
        )
    paint_id = value("native_paint_id")
    return {
        "native_draw_order": int(value("native_draw_order", -1)),
        "native_source_index": int(value("native_source_index", -1)),
        "source_kind": str(value("source_kind", "")),
        "weight": float(value("weight", 0.0)),
        "native_paint_id": (
            None if paint_id is None else [int(part) for part in paint_id]
        ),
    }


def _paint_fingerprint_payload(item: dict[str, Any]) -> dict[str, Any]:
    paint_id = item.get("native_paint_id")
    return {
        "color": [int(value) for value in item["color"]],
        "rgba": [int(value) for value in item.get("rgba", ())],
        "rgba_f64": [float(value) for value in item.get("rgba_f64", ())],
        "source_kind": str(item.get("source_kind", "")),
        "native_paint_id": (
            None if paint_id is None else [int(part) for part in paint_id]
        ),
        "native_paint_contributors": [
            _contributor_fingerprint_payload(contributor)
            for contributor in item.get("native_paint_contributors", ())
        ],
    }


def _analysis_fingerprint(analysis: Any) -> str:
    hasher = hashlib.sha256()
    _update_json(
        hasher,
        {
            "bbox": [float(value) for value in analysis.bbox],
            "scale_factor": float(analysis.scale_factor),
            "num_channels": int(analysis.num_channels),
            "num_layers": int(analysis.num_layers),
            "slot_names": list(analysis.slot_names),
        },
    )
    for item in analysis.shape_data:
        _update_json(hasher, _paint_fingerprint_payload(item))
        _update_geometry(hasher, item["poly"])
    for item in analysis.clipped_shapes:
        paint_payload = _paint_fingerprint_payload(item)
        paint_payload.update(
            {
                "draw_order": int(item.get("draw_order", -1)),
                "native_draw_order": int(
                    item.get("native_draw_order", -1)
                ),
                "native_source_index": int(
                    item.get("native_source_index", -1)
                ),
            }
        )
        _update_json(
            hasher,
            paint_payload,
        )
        _update_geometry(hasher, item["geometry"])
    for item in analysis.matched_shapes:
        _update_json(
            hasher,
            {
                "color": list(item.get("color") or ()),
                "match_color": list(item.get("match_color") or ()),
                "matched_rgb": list(item.get("matched_rgb") or ()),
                "recipe": [int(value) for value in item.get("recipe") or ()],
            },
        )
    _update_geometry(hasher, analysis.silhouette)
    return hasher.hexdigest()


def _polygon_components(geometry: Any) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [
        component
        for component in geometry.geoms
        if component.geom_type == "Polygon" and not component.is_empty
    ]


def _output_summary(analysis: Any, fingerprint: str) -> dict[str, Any]:
    visible_geometries = [
        item["geometry"] for item in analysis.clipped_shapes
    ]
    silhouette_components = _polygon_components(analysis.silhouette)
    return {
        "geometry_backend": analysis.stage_timings.get("geometry_backend"),
        "native_version": analysis.stage_timings.get("native_version"),
        "native_schema_version": analysis.stage_timings.get(
            "native_schema_version"
        ),
        "native_cache_hit": bool(
            analysis.stage_timings.get("native_cache_hit")
        ),
        "raw_shape_count": len(analysis.shape_data),
        "visible_shape_count": len(analysis.clipped_shapes),
        "matched_shape_count": len(analysis.matched_shapes),
        "partial_alpha_raw_shape_count": sum(
            0.0 < float(item["rgba_f64"][3]) < 1.0
            for item in analysis.shape_data
        ),
        "partial_alpha_visible_shape_count": sum(
            0.0 < float(item["rgba_f64"][3]) < 1.0
            for item in analysis.clipped_shapes
        ),
        "composite_visible_shape_count": sum(
            item.get("source_kind") == "composite"
            for item in analysis.clipped_shapes
        ),
        "visible_contributor_count": sum(
            len(item.get("native_paint_contributors", ()))
            for item in analysis.clipped_shapes
        ),
        "silhouette_component_count": len(silhouette_components),
        "silhouette_hole_count": sum(
            len(component.interiors) for component in silhouette_components
        ),
        "coordinate_count": sum(
            int(shapely.get_num_coordinates(geometry))
            for geometry in visible_geometries
        ),
        "source_color_count": len(
            {tuple(item["color"]) for item in analysis.clipped_shapes}
        ),
        "matched_recipe_count": len(
            {
                tuple(int(value) for value in item.get("recipe") or ())
                for item in analysis.matched_shapes
            }
        ),
        "fingerprint": fingerprint,
        "fingerprint_contract": (
            "geometry-exact-rgba-paint-provenance-v2"
        ),
    }


def _clear_entry_caches(processor: VectorProcessor) -> None:
    if getattr(processor, "_parse_clip_cache_path", None) is not None:
        raise RuntimeError("artifact_cache_must_be_disabled")
    _VECTOR_PARSE_CLIP_CACHE.clear()
    gc.collect()


def _median_stage(stage_runs: list[dict[str, Any]], key: str) -> float:
    return statistics.median(
        max(0.0, float(stage.get(key, 0.0))) for stage in stage_runs
    )


def _measure_complete_entry(
    processor: VectorProcessor,
    svg_path: Path,
    *,
    target_width_mm: float,
    tolerance_mm: float,
    warm_runs: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if warm_runs < 3:
        raise ValueError("warm_runs_must_be_at_least_three")
    processor.sampling_precision = tolerance_mm
    if hasattr(processor, "_parse_clip_cache_path"):
        delattr(processor, "_parse_clip_cache_path")

    _clear_entry_caches(processor)
    warmup = processor.analyze_svg(str(svg_path), target_width_mm)
    if warmup.stage_timings.get("geometry_backend") != "native":
        reason = warmup.stage_timings.get("native_fallback_reason", "unknown")
        raise RuntimeError(f"fixture_did_not_use_native_backend:{reason}")
    fingerprints = {_analysis_fingerprint(warmup)}
    del warmup

    wall_runs: list[float] = []
    stage_runs: list[dict[str, Any]] = []
    output: dict[str, Any] | None = None
    for _run_index in range(warm_runs):
        _clear_entry_caches(processor)
        started = time.perf_counter()
        analysis = processor.analyze_svg(str(svg_path), target_width_mm)
        wall_seconds = time.perf_counter() - started
        if analysis.stage_timings.get("geometry_backend") != "native":
            reason = analysis.stage_timings.get(
                "native_fallback_reason", "unknown"
            )
            raise RuntimeError(f"fixture_did_not_use_native_backend:{reason}")
        if analysis.stage_timings.get("native_cache_hit"):
            raise RuntimeError("benchmark_measured_a_cache_hit")
        fingerprint = _analysis_fingerprint(analysis)
        fingerprints.add(fingerprint)
        wall_runs.append(wall_seconds)
        stage_runs.append(dict(analysis.stage_timings))
        output = _output_summary(analysis, fingerprint)
        del analysis

    if len(fingerprints) != 1 or output is None:
        raise RuntimeError("non_deterministic_vector_analysis")

    native_call_runs = [
        max(0.0, float(stage.get("native_svg_s", 0.0)))
        for stage in stage_runs
    ]
    native_adapter_runs = [
        max(0.0, float(stage.get("native_adapter_s", 0.0)))
        for stage in stage_runs
    ]
    color_match_runs = [
        max(0.0, float(stage.get("color_match_s", 0.0)))
        for stage in stage_runs
    ]
    # VectorProcessor measures ``native_svg_s`` around the complete adapter
    # call, so it already includes the separately reported Shapely conversion.
    # Do not add ``native_adapter_s`` a second time.
    native_geometry_runs = native_call_runs
    orchestration_runs = [
        max(0.0, wall - geometry - color_match)
        for wall, geometry, color_match in zip(
            wall_runs,
            native_geometry_runs,
            color_match_runs,
            strict=True,
        )
    ]
    median_seconds = statistics.median(wall_runs)
    p95_seconds = _percentile(wall_runs, 0.95)
    output["stable_across_runs"] = True
    return (
        {
            "warmup_runs": 1,
            "warm_runs_seconds": [_rounded(value) for value in wall_runs],
            "median_seconds": _rounded(median_seconds),
            "p95_seconds": _rounded(p95_seconds),
            "p95_method": "linear_interpolation_r7",
            "range_seconds": _rounded(max(wall_runs) - min(wall_runs)),
            "native_recorder_seconds": _rounded(
                _median_stage(stage_runs, "native_recorder_s")
            ),
            "native_kernel_seconds": _rounded(
                _median_stage(stage_runs, "native_kernel_s")
            ),
            "native_bounds_seconds": _rounded(
                _median_stage(stage_runs, "native_bounds_s")
            ),
            "native_replay_seconds": _rounded(
                _median_stage(stage_runs, "native_replay_s")
            ),
            "native_topology_seconds": _rounded(
                _median_stage(stage_runs, "native_topology_s")
            ),
            "native_normalize_raw_seconds": _rounded(
                _median_stage(stage_runs, "native_normalize_raw_s")
            ),
            "native_composite_seconds": _rounded(
                _median_stage(stage_runs, "native_composite_s")
            ),
            "native_normalize_visible_seconds": _rounded(
                _median_stage(stage_runs, "native_normalize_visible_s")
            ),
            "native_export_seconds": _rounded(
                _median_stage(stage_runs, "native_export_s")
            ),
            "native_binding_conversion_seconds": _rounded(
                _median_stage(stage_runs, "native_binding_conversion_s")
            ),
            "native_adapter_conversion_seconds": _rounded(
                _median_stage(stage_runs, "native_adapter_s")
            ),
            "native_geometry_total_seconds": _rounded(
                statistics.median(native_geometry_runs)
            ),
            "color_match_seconds": _rounded(
                statistics.median(color_match_runs)
            ),
            "orchestration_seconds": _rounded(
                statistics.median(orchestration_runs)
            ),
            "cache_policy": {
                "memory_cache_cleared_before_each_run": True,
                "artifact_cache_disabled": True,
            },
            "median_threshold_seconds": 1.0,
            "p95_threshold_seconds": 1.25,
            "median_threshold_passed": median_seconds <= 1.0,
            "p95_threshold_passed": p95_seconds <= 1.25,
        },
        output,
    )


def _measure_complete_entry_isolated(
    svg_path: Path,
    lut_path: Path,
    *,
    target_width_mm: float,
    tolerance_mm: float,
    warm_runs: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Measure one complete public-entry case in a fresh interpreter.

    在全新的解释器进程中测量一次完整公共入口案例。
    """

    with tempfile.TemporaryDirectory(
        prefix="lumina-native-svg-benchmark-"
    ) as temporary_dir:
        result_path = Path(temporary_dir) / "measurement.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--_measurement-child",
            "--svg",
            str(Path(svg_path).resolve()),
            "--lut",
            str(Path(lut_path).resolve()),
            "--target-width-mm",
            str(target_width_mm),
            "--tolerance-mm",
            str(tolerance_mm),
            "--warm-runs",
            str(warm_runs),
            "--output",
            str(result_path),
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=7200,
            cwd=REPO_ROOT,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(
                "isolated_native_svg_benchmark_failed:"
                + (detail or f"exit_{completed.returncode}")
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            measurement = payload["measurement"]
            output = payload["output"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "isolated_native_svg_benchmark_invalid_result"
            ) from exc
        if not isinstance(measurement, dict) or not isinstance(output, dict):
            raise RuntimeError("isolated_native_svg_benchmark_invalid_result")
        return measurement, output


def _measurement_child_main(argv: list[str]) -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--_measurement-child", action="store_true")
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--lut", type=Path, required=True)
    parser.add_argument("--target-width-mm", type=float, required=True)
    parser.add_argument("--tolerance-mm", type=float, required=True)
    parser.add_argument("--warm-runs", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    processor = VectorProcessor(str(args.lut.resolve()), "4-Color (RYBW)")
    swap_before, swap_source = _system_swap_used_bytes()
    measurement, output = _measure_complete_entry(
        processor,
        args.svg.resolve(),
        target_width_mm=args.target_width_mm,
        tolerance_mm=args.tolerance_mm,
        warm_runs=args.warm_runs,
    )
    swap_after, swap_after_source = _system_swap_used_bytes()
    if swap_source != swap_after_source:
        swap_source = f"{swap_source}->{swap_after_source}"
    measurement.update(
        {
            "process_isolation": "fresh_subprocess",
            "process_pid": os.getpid(),
            "peak_rss_bytes": _peak_rss_bytes(),
            "swap_delta_bytes": max(0, swap_after - swap_before),
            "swap_measurement": swap_source,
        }
    )
    args.output.write_text(
        json.dumps(
            {"measurement": measurement, "output": output},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 0


def _record_real_r4c1(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "classification": "real_r4c1",
            "status": "unavailable",
            "reason_code": None,
            "native_by_default_ready": False,
            "source": "not_provided",
        }

    record: dict[str, Any] = {
        "classification": "real_r4c1",
        "native_by_default_ready": False,
        "source": "local_private_fixture",
    }

    started = time.perf_counter()
    outcome = native_svg_adapter.analyze_native_svg(
        str(path), 111.0, 0.02, expand_stroke_to_fill=True
    )
    elapsed = time.perf_counter() - started
    supported = not isinstance(outcome, NativeSvgFallback)
    record.update(
        {
            "byte_size": path.stat().st_size,
            "status": "supported" if supported else "unsupported",
            "reason_code": None if supported else outcome.reason_code,
            "native_by_default_ready": supported,
            "capability_check_seconds": _rounded(elapsed),
            "structure": _fixture_structure(path),
        }
    )
    return record


def _record_source_proxy_capability(path: Path | None) -> dict[str, Any]:
    """Run the source proxy directly and record its current native outcome."""

    if path is None:
        return {
            "classification": "real_proxy",
            "status": "unavailable",
            "source": "not_provided",
            "reason_code": None,
            "native_by_default_ready": False,
        }

    started = time.perf_counter()
    outcome = native_svg_adapter.analyze_native_svg(
        str(path), 111.0, 0.02
    )
    elapsed = time.perf_counter() - started
    supported = not isinstance(outcome, NativeSvgFallback)
    return {
        "classification": "real_proxy",
        "path": _relative_repo_path(path),
        "byte_size": path.stat().st_size,
        "status": "supported" if supported else "unsupported",
        "reason_code": None if supported else outcome.reason_code,
        "native_by_default_ready": supported,
        "capability_check_seconds": _rounded(elapsed),
        "structure": _fixture_structure(path),
    }


def _parse_search_root(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected LABEL=PATH")
    label, raw_path = value.split("=", 1)
    if not label or not raw_path:
        raise argparse.ArgumentTypeError("expected LABEL=PATH")
    return label, Path(raw_path).expanduser().resolve()


def _find_large_svg_files(
    search_roots: list[tuple[str, Path]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for label, root in search_roots:
        if not root.exists():
            continue
        try:
            candidates = root.rglob("*.svg")
            for candidate in candidates:
                try:
                    byte_size = candidate.stat().st_size
                except OSError:
                    continue
                if byte_size < LARGE_REGRESSION_MINIMUM_BYTES:
                    continue
                matches.append(
                    {
                        "root": label,
                        "relative_path": candidate.relative_to(root).as_posix(),
                        "byte_size": byte_size,
                    }
                )
        except OSError:
            continue
    return sorted(
        matches,
        key=lambda item: (item["root"], item["relative_path"]),
    )


def _large_regression_record(
    search_roots: list[tuple[str, Path]],
    explicit_path: Path | None,
    lut_path: Path,
    *,
    target_width_mm: float,
    tolerance_mm: float,
    warm_runs: int,
) -> dict[str, Any]:
    matches = _find_large_svg_files(search_roots)
    if explicit_path is None and matches:
        raise RuntimeError(
            "large_regression_found; rerun with --large-svg PATH:"
            + json.dumps(matches, sort_keys=True)
        )
    base_record = {
        "classification": "large_regression",
        "minimum_byte_size": LARGE_REGRESSION_MINIMUM_BYTES,
        "searched_roots": [label for label, _path in search_roots],
        "matching_files": matches,
        "memory_policy": "observation_only",
    }
    if explicit_path is None:
        return {
            **base_record,
            "status": "unavailable",
            "matching_files": [],
            "note": (
                "No SVG at or above 50 MiB was found; the smaller derived "
                "supported-scale fixture, source proxy, and real R4C1 "
                "fixture were not substituted."
            ),
        }

    large_path = explicit_path.resolve()
    byte_size = large_path.stat().st_size
    if byte_size < LARGE_REGRESSION_MINIMUM_BYTES:
        raise ValueError(f"large_regression_is_too_small:{byte_size}")
    measurement, output = _measure_complete_entry_isolated(
        large_path,
        lut_path,
        target_width_mm=target_width_mm,
        tolerance_mm=tolerance_mm,
        warm_runs=warm_runs,
    )
    peak_rss_bytes = int(measurement["peak_rss_bytes"])
    swap_delta_bytes = int(measurement["swap_delta_bytes"])
    return {
        **base_record,
        "status": "measured",
        "path": _relative_repo_path(large_path),
        "byte_size": byte_size,
        "structure": _fixture_structure(large_path),
        "measurement": measurement,
        "output": output,
        "peak_rss_bytes": peak_rss_bytes,
        "swap_delta_bytes": swap_delta_bytes,
        "swap_measurement": measurement["swap_measurement"],
        "note": (
            "Measured separately from the public proxy and real R4C1 fixture."
        ),
    }


def _relative_repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _benchmark_manifest(args: argparse.Namespace) -> dict[str, Any]:
    svg_path = args.svg.resolve()
    lut_path = args.lut.resolve()
    measurement, output = _measure_complete_entry_isolated(
        svg_path,
        lut_path,
        target_width_mm=args.target_width_mm,
        tolerance_mm=args.tolerance_mm,
        warm_runs=args.warm_runs,
    )
    alpha_measurement, alpha_output = _measure_complete_entry_isolated(
        ALPHA_COMPOSITING_FIXTURE,
        lut_path,
        target_width_mm=args.target_width_mm,
        tolerance_mm=args.tolerance_mm,
        warm_runs=args.warm_runs,
    )
    if svg_path == SUPPORTED_SCALE_FIXTURE.resolve():
        provenance = json.loads(
            SUPPORTED_SCALE_PROVENANCE.read_text(encoding="utf-8")
        )
        fixture_classification = str(provenance["classification"])
    else:
        provenance = None
        fixture_classification = "explicit_supported_fixture"
    return {
        "schema_version": 5,
        "entrypoint": "core.vector_engine.VectorProcessor.analyze_svg",
        "fixture": {
            "path": _relative_repo_path(svg_path),
            "classification": fixture_classification,
            "byte_size": svg_path.stat().st_size,
            "provenance": provenance,
            **_fixture_structure(svg_path),
        },
        "lut": {
            "path": _relative_repo_path(lut_path),
            "byte_size": lut_path.stat().st_size,
            "color_mode": "4-Color (RYBW)",
        },
        "host": _host_manifest(),
        "parameters": {
            "target_width_mm": args.target_width_mm,
            "tolerance_mm": args.tolerance_mm,
            "build_type": "Release",
            "openmp_enabled": False,
            "caller_threads": 1,
        },
        "measurement": measurement,
        "output": output,
        "alpha_compositing": {
            "fixture": {
                "path": _relative_repo_path(ALPHA_COMPOSITING_FIXTURE),
                "classification": "alpha_compositing",
                "byte_size": ALPHA_COMPOSITING_FIXTURE.stat().st_size,
                **_fixture_structure(ALPHA_COMPOSITING_FIXTURE),
            },
            "measurement": alpha_measurement,
            "output": alpha_output,
        },
        "source_proxy": _record_source_proxy_capability(
            args.source_proxy.resolve() if args.source_proxy is not None else None
        ),
        "real_r4c1": _record_real_r4c1(args.real_r4c1),
        "large_regression": _large_regression_record(
            args.large_search_root,
            args.large_svg,
            lut_path,
            target_width_mm=args.target_width_mm,
            tolerance_mm=args.tolerance_mm,
            warm_runs=args.warm_runs,
        ),
    }


def _threshold_failures(manifest: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    measurement = manifest["measurement"]
    for name in ("median_threshold_passed", "p95_threshold_passed"):
        if measurement.get(name) is not True:
            failures.append(f"measurement.{name}")

    return failures


def main() -> None:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--svg",
        type=Path,
        default=SUPPORTED_SCALE_FIXTURE,
    )
    parser.add_argument(
        "--source-proxy",
        type=Path,
        help="Optional real SVG supplied by the caller; no third-party artwork is bundled.",
    )
    parser.add_argument(
        "--lut",
        type=Path,
        default=(
            REPO_ROOT
            / "tests/fixtures/lut_regression/Bambulab&PLA&RYBW&红-黄-蓝-白.npy"
        ),
    )
    parser.add_argument("--target-width-mm", type=float, default=111.0)
    parser.add_argument("--tolerance-mm", type=float, default=0.02)
    parser.add_argument("--warm-runs", type=int, default=3)
    parser.add_argument("--real-r4c1", type=Path)
    parser.add_argument(
        "--large-svg",
        type=Path,
        help="Explicit >=50 MiB regression SVG to measure when available.",
    )
    parser.add_argument(
        "--large-search-root",
        action="append",
        type=_parse_search_root,
        required=True,
        metavar="LABEL=PATH",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            REPO_ROOT / "progress" / "native-svg-synthetic-benchmark.json"
        ),
    )
    args = parser.parse_args()
    manifest = _benchmark_manifest(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    failures = _threshold_failures(manifest)
    if failures:
        raise SystemExit(
            "Native SVG benchmark thresholds failed: "
            + ", ".join(failures)
        )


if __name__ == "__main__":
    if "--_measurement-child" in sys.argv[1:]:
        raise SystemExit(_measurement_child_main(sys.argv[1:]))
    main()
