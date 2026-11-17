#!/usr/bin/env python3
"""Generate native-SVG artifacts and validate them in real slicer CLIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEPENDENCY_UNAVAILABLE_EXIT = 20
_GCODE_COMMAND_RE = re.compile(
    r"^(?:N\d+\s+)?([GMT])(\d+)(?:\s|$)", re.IGNORECASE
)
_GCODE_WORD_RE = re.compile(
    r"([A-Z])([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)",
    re.IGNORECASE,
)
_GCODE_FEATURE_RE = re.compile(r"^FEATURE:\s*(.+)$", re.IGNORECASE)
_AUXILIARY_FEATURE_TOKENS = (
    "brim",
    "custom",
    "prime tower",
    "purge tower",
    "skirt",
    "support",
    "wipe tower",
)
_POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(^|[\s\"'=(])(/[^\s\"'<>]+)", re.MULTILINE
)
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(^|[\s\"'=(])([A-Za-z]:\\[^\s\"'<>]+)", re.MULTILINE
)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _inspect_3mf(path: Path) -> dict[str, Any]:
    """Return format-level object, triangle, and material evidence."""

    with zipfile.ZipFile(path) as package:
        names = set(package.namelist())
        if "3D/3dmodel.model" not in names:
            raise ValueError("three_mf_missing_model")
        model_names = sorted(
            name
            for name in names
            if name.startswith("3D/") and name.lower().endswith(".model")
        )
        model_roots = [
            ET.fromstring(package.read(name)) for name in model_names
        ]
        model_root = model_roots[model_names.index("3D/3dmodel.model")]
        settings_root = None
        if "Metadata/model_settings.config" in names:
            settings_root = ET.fromstring(
                package.read("Metadata/model_settings.config")
            )

    object_count = sum(
        len(root.findall(".//{*}object")) for root in model_roots
    )
    build_item_count = len(model_root.findall(".//{*}build/{*}item"))
    triangle_count = sum(
        len(root.findall(".//{*}triangle")) for root in model_roots
    )
    base_material_count = sum(
        len(root.findall(".//{*}basematerials/{*}base"))
        for root in model_roots
    )
    extruder_values: set[str] = set()
    part_names: set[str] = set()
    if settings_root is not None:
        for metadata in settings_root.findall(".//metadata"):
            key = metadata.attrib.get("key", "")
            value = metadata.attrib.get("value", "")
            if key == "extruder" and value:
                extruder_values.add(value)
            elif key == "name" and value:
                part_names.add(value)
    material_count = len(extruder_values) or base_material_count
    try:
        expected_tool_ids = sorted(
            {int(value) - 1 for value in extruder_values}
        )
    except ValueError as exc:
        raise ValueError("three_mf_invalid_extruder_metadata") from exc
    if any(tool_id < 0 for tool_id in expected_tool_ids):
        raise ValueError("three_mf_invalid_extruder_metadata")
    return {
        "path": path.name,
        "byte_size": path.stat().st_size,
        "sha256": _sha256_file(path),
        "object_count": object_count,
        "build_item_count": build_item_count,
        "triangle_count": triangle_count,
        "material_count": material_count,
        "expected_tool_ids": expected_tool_ids,
        "part_names": sorted(part_names),
    }


def _is_model_feature(feature: str | None) -> bool:
    if feature is None:
        return False
    normalized = " ".join(feature.lower().split())
    return not any(
        token in normalized for token in _AUXILIARY_FEATURE_TOKENS
    )


def _extrusion_distance_mm(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    command_code: int,
    words: dict[str, float],
) -> float:
    """Distance to an XY line or a slicer's relative-I/J circular arc."""
    if command_code in {2, 3}:
        if "R" in words or not ("I" in words or "J" in words):
            raise ValueError("coverage_requires_relative_ij_arcs")
        center = start[0] + words.get("I", 0), start[1] + words.get("J", 0)
        radius = math.dist(start, center)
        first = math.atan2(start[1] - center[1], start[0] - center[0])
        last = math.atan2(end[1] - center[1], end[0] - center[0])
        query = math.atan2(point[1] - center[1], point[0] - center[0])
        direction = 1 if command_code == 3 else -1
        sweep = (direction * (last - first)) % math.tau
        offset = (direction * (query - first)) % math.tau
        if start == end or offset <= sweep:
            return abs(math.dist(point, center) - radius)
        return min(math.dist(point, start), math.dist(point, end))
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    fraction = (
        ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
        if length_squared else 0.0
    )
    fraction = min(1.0, max(0.0, fraction))
    return math.hypot(
        point[0] - start[0] - fraction * dx,
        point[1] - start[1] - fraction * dy,
    )


def _toolpath_metrics(
    payload: bytes, *, coverage_probes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fingerprint motion and count model-region planar extrusion only."""

    normalized_commands: list[str] = []
    motion_count = 0
    extrusion_count = 0
    tool_change_count = 0
    active_tool = 0
    absolute_extrusion = True
    absolute_positioning = True
    extrusion_position = 0.0
    planar_positions: dict[str, float | None] = {"X": None, "Y": None}
    active_feature: str | None = None
    positive_extrusion_by_tool: dict[int, int] = {}
    z_position: float | None = None
    coverage = []
    for probe in coverage_probes or []:
        if not all(math.isfinite(float(probe[key])) for key in (
            "x_mm", "y_mm", "z_mm", "max_distance_mm",
        )) or float(probe["max_distance_mm"]) <= 0:
            raise ValueError("invalid_toolpath_coverage_probe")
        coverage.append({**probe, "nearest_mm": None, "covered": False})
    for raw_line in payload.decode("utf-8", errors="replace").splitlines():
        command_text, _separator, comment = raw_line.partition(";")
        feature_match = _GCODE_FEATURE_RE.match(comment.strip())
        if feature_match is not None:
            active_feature = feature_match.group(1).strip()
        command = command_text.strip()
        if not command:
            continue
        command = " ".join(command.upper().split())
        match = _GCODE_COMMAND_RE.match(command)
        if match is None:
            continue
        command_letter = match.group(1).upper()
        command_code = int(match.group(2))
        is_motion = command_letter == "G" and command_code in {0, 1, 2, 3}
        is_position_reset = command_letter == "G" and command_code == 92
        is_positioning_mode = (
            command_letter == "G" and command_code in {90, 91}
        )
        is_extrusion_mode = command_letter == "M" and command_code in {82, 83}
        is_tool_change = command_letter == "T"
        if not (
            is_motion
            or is_position_reset
            or is_positioning_mode
            or is_extrusion_mode
            or is_tool_change
        ):
            continue
        normalized_commands.append(command)
        words = {
            letter.upper(): float(value)
            for letter, value in _GCODE_WORD_RE.findall(command)
        }
        if is_tool_change:
            tool_change_count += 1
            active_tool = command_code
            continue
        if is_extrusion_mode:
            absolute_extrusion = command_code == 82
            continue
        if is_positioning_mode:
            absolute_positioning = command_code == 90
            continue
        if is_position_reset:
            if "E" in words:
                extrusion_position = words["E"]
            for axis in ("X", "Y"):
                if axis in words:
                    planar_positions[axis] = words[axis]
            if "Z" in words:
                z_position = words["Z"]
            continue

        motion_count += 1
        start = planar_positions["X"], planar_positions["Y"]
        previous_z = z_position
        if "Z" in words:
            z_position = (
                words["Z"] if absolute_positioning
                else (z_position or 0.0) + words["Z"]
            )
        has_planar_motion = command_code in {2, 3} and any(
            words.get(key, 0) != 0 for key in ("I", "J", "R")
        )
        for axis in ("X", "Y"):
            if axis not in words:
                continue
            coordinate = words[axis]
            previous_coordinate = planar_positions[axis]
            if absolute_positioning:
                if (
                    previous_coordinate is None
                    or coordinate != previous_coordinate
                ):
                    has_planar_motion = True
                planar_positions[axis] = coordinate
            else:
                if coordinate != 0.0:
                    has_planar_motion = True
                planar_positions[axis] = (
                    (previous_coordinate or 0.0) + coordinate
                )
        if "E" not in words:
            continue
        extrusion_value = words["E"]
        if absolute_extrusion:
            extrusion_delta = extrusion_value - extrusion_position
            extrusion_position = extrusion_value
        else:
            extrusion_delta = extrusion_value
            extrusion_position += extrusion_value
        if (
            extrusion_delta > 0.0
            and has_planar_motion
            and _is_model_feature(active_feature)
        ):
            extrusion_count += 1
            positive_extrusion_by_tool[active_tool] = (
                positive_extrusion_by_tool.get(active_tool, 0) + 1
            )
            end = planar_positions["X"], planar_positions["Y"]
            if None not in (*start, *end) and z_position is not None and (
                previous_z is not None and abs(previous_z - z_position) <= 1e-6
            ):
                for probe in coverage:
                    if abs(z_position - float(probe["z_mm"])) > 1e-4:
                        continue
                    if "tool_id" in probe and int(probe["tool_id"]) != active_tool:
                        continue
                    distance = _extrusion_distance_mm(
                        (float(probe["x_mm"]), float(probe["y_mm"])),
                        start, end, command_code, words,
                    )
                    if probe["nearest_mm"] is None or distance < probe["nearest_mm"]:
                        probe["nearest_mm"] = distance
                    probe["covered"] = probe["nearest_mm"] <= float(probe["max_distance_mm"])
    normalized = "\n".join(normalized_commands).encode("utf-8")
    result = {
        "fingerprint": hashlib.sha256(normalized).hexdigest(),
        "normalized_byte_size": len(normalized),
        "motion_command_count": motion_count,
        "extrusion_move_count": extrusion_count,
        "positive_extrusion_by_tool": {
            str(tool_id): positive_extrusion_by_tool[tool_id]
            for tool_id in sorted(positive_extrusion_by_tool)
        },
        "positive_extrusion_tool_ids": sorted(positive_extrusion_by_tool),
        "tool_change_count": tool_change_count,
    }
    if coverage:
        result["coverage"] = coverage
    return result


def _toolpath_payloads(output_dir: Path) -> tuple[bytes, list[str]]:
    payloads: list[tuple[str, bytes]] = []
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        relative_path = path.relative_to(output_dir).as_posix()
        lower_name = path.name.lower()
        if lower_name.endswith((".gcode", ".gco", ".gcode.txt")):
            payloads.append((relative_path, path.read_bytes()))
            continue
        if not zipfile.is_zipfile(path):
            continue
        with zipfile.ZipFile(path) as package:
            for member in sorted(package.namelist()):
                if member.lower().endswith((".gcode", ".gco", ".gcode.txt")):
                    payloads.append(
                        (f"{relative_path}!{member}", package.read(member))
                    )
    combined = b"\n".join(payload for _name, payload in payloads)
    return combined, [name for name, _payload in payloads]


def _standard_executable_candidates(slicer_name: str) -> list[Path]:
    if slicer_name == "BambuStudio":
        names = (
            "bambu-studio.exe",
            "BambuStudio.exe",
        )
        mac_path = Path(
            "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"
        )
        linux_paths = (
            Path("/usr/bin/bambu-studio"),
            Path("/usr/local/bin/bambu-studio"),
        )
        windows_dirs = ("Bambu Studio", "BambuStudio")
    else:
        names = (
            "orca-slicer.exe",
            "OrcaSlicer.exe",
        )
        mac_path = Path(
            "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"
        )
        linux_paths = (
            Path("/usr/bin/orca-slicer"),
            Path("/usr/local/bin/orca-slicer"),
        )
        windows_dirs = ("OrcaSlicer", "Orca Slicer")

    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.append(mac_path)
    elif os.name == "nt":
        roots = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        for root in roots:
            if not root:
                continue
            for directory in windows_dirs:
                for name in names:
                    candidates.append(Path(root) / directory / name)
    else:
        candidates.extend(linux_paths)
        command_name = "bambu-studio" if slicer_name == "BambuStudio" else "orca-slicer"
        located = shutil.which(command_name)
        if located:
            candidates.insert(0, Path(located))
    return candidates


def _resolve_executable(
    slicer_name: str,
    explicit_path: Path | None,
    *,
    auto_detect: bool,
) -> Path | None:
    if explicit_path is not None:
        resolved = explicit_path.expanduser().resolve()
        return resolved if resolved.is_file() else None
    if not auto_detect:
        return None
    return next(
        (
            candidate
            for candidate in _standard_executable_candidates(slicer_name)
            if candidate.is_file()
        ),
        None,
    )


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def _run_command(
    command: list[str],
    *,
    timeout_seconds: float,
    cwd: Path | None = None,
) -> tuple[int, str, str, float]:
    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "cwd": cwd,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    started = time.perf_counter()
    process = subprocess.Popen(command, **popen_kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        raise TimeoutError(
            f"command_timed_out_after_{timeout_seconds:g}_seconds"
        ) from exc
    return (
        int(process.returncode),
        stdout,
        stderr,
        time.perf_counter() - started,
    )


def _slicer_version(executable: Path, cwd: Path) -> str:
    try:
        _return_code, stdout, stderr, _duration = _run_command(
            [str(executable), "--help"],
            timeout_seconds=30.0,
            cwd=cwd,
        )
    except (OSError, TimeoutError):
        return "unknown"
    for line in (stdout + "\n" + stderr).splitlines():
        stripped = line.strip()
        if re.match(r"^(?:BambuStudio|OrcaSlicer)-", stripped):
            return stripped.removesuffix(":")
    return "unknown"


def _validation_command(
    executable: Path,
    project_path: Path,
    output_dir: Path,
) -> list[str]:
    return [
        str(executable),
        "--debug",
        "1",
        "--allow-newer-file",
        "--slice",
        "0",
        "--outputdir",
        str(output_dir),
        str(project_path),
    ]


def _portable_command_hint(
    slicer_name: str,
    project_path: Path,
) -> list[str]:
    return [
        f"<{slicer_name}-executable>",
        "--debug",
        "1",
        "--allow-newer-file",
        "--slice",
        "0",
        "--outputdir",
        "<isolated-run-directory>",
        project_path.name,
    ]


def _portable_diagnostic_tail(value: str) -> str:
    """Redact machine-local absolute paths from committed evidence."""

    sanitized = _WINDOWS_ABSOLUTE_PATH_RE.sub(
        lambda match: match.group(1) + "<absolute-path>", value
    )
    return _POSIX_ABSOLUTE_PATH_RE.sub(
        lambda match: match.group(1) + "<absolute-path>", sanitized
    )


def _validate_slicer(
    slicer_name: str,
    executable: Path | None,
    project_path: Path,
    output_root: Path,
    *,
    timeout_seconds: float,
    validation_runs: int = 2,
    coverage_probes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if validation_runs < 2:
        raise ValueError("validation_runs_must_be_at_least_two")
    inspection = _inspect_3mf(project_path)
    output_base = output_root / slicer_name
    command_hint = _portable_command_hint(slicer_name, project_path)
    if executable is None:
        return {
            "status": "reality_dependency_unavailable",
            "reason": "slicer_executable_not_found",
            "executable": None,
            "expected_command": command_hint,
            "input": inspection,
        }

    output_base.mkdir(parents=True, exist_ok=True)
    run_results: list[dict[str, Any]] = []
    for run_index in range(validation_runs):
        output_dir = Path(
            tempfile.mkdtemp(
                prefix=f"run-{run_index + 1}-",
                dir=output_base,
            )
        )
        command = _validation_command(executable, project_path, output_dir)
        try:
            return_code, stdout, stderr, duration = _run_command(
                command,
                timeout_seconds=timeout_seconds,
                cwd=output_dir,
            )
        except (OSError, TimeoutError) as exc:
            run_results.append(
                {
                    "status": "failed",
                    "reason": type(exc).__name__,
                    "error": _portable_diagnostic_tail(str(exc)),
                    "command": command_hint,
                    "output_directory": f"run-{run_index + 1}",
                }
            )
            break

        payload, payload_paths = _toolpath_payloads(output_dir)
        toolpath = _toolpath_metrics(payload, coverage_probes=coverage_probes)
        missing_expected_tool_ids = sorted(
            set(inspection["expected_tool_ids"])
            - set(toolpath["positive_extrusion_tool_ids"])
        )
        if return_code != 0:
            run_status = "failed"
            run_reason = "slicer_exit_nonzero"
        elif not payload_paths:
            run_status = "failed"
            run_reason = "toolpath_not_emitted"
        elif toolpath["extrusion_move_count"] <= 0:
            run_status = "failed"
            run_reason = "toolpath_has_no_extrusion"
        elif missing_expected_tool_ids:
            run_status = "failed"
            run_reason = "toolpath_missing_material_extrusion"
        elif any(not probe["covered"] for probe in toolpath.get("coverage", [])):
            run_status = "failed"
            run_reason = "toolpath_missing_region_extrusion"
        else:
            run_status = "passed"
            run_reason = ""
        run_results.append(
            {
                "status": run_status,
                "reason": run_reason,
                "command": command_hint,
                "output_directory": f"run-{run_index + 1}",
                "exit_code": return_code,
                "duration_seconds": round(duration, 6),
                "stdout_tail": _portable_diagnostic_tail(stdout[-4000:]),
                "stderr_tail": _portable_diagnostic_tail(stderr[-4000:]),
                "toolpath_files": payload_paths,
                "toolpath": toolpath,
                "missing_expected_tool_ids": missing_expected_tool_ids,
            }
        )
        if run_status != "passed":
            break

    fingerprints = {
        run["toolpath"]["fingerprint"]
        for run in run_results
        if run.get("status") == "passed"
    }
    stable_across_runs = (
        len(run_results) == validation_runs
        and all(run.get("status") == "passed" for run in run_results)
        and len(fingerprints) == 1
    )
    if not all(run.get("status") == "passed" for run in run_results):
        status = "failed"
        reason = next(
            run.get("reason", "slicer_validation_failed")
            for run in run_results
            if run.get("status") != "passed"
        )
    elif not stable_across_runs:
        status = "failed"
        reason = "non_deterministic_toolpath"
    else:
        status = "passed"
        reason = ""
    representative = run_results[0]
    version_cwd = output_dir
    return {
        "status": status,
        "reason": reason,
        "executable": executable.name,
        "version": _slicer_version(executable, version_cwd),
        "command": representative.get("command"),
        "exit_code": representative.get("exit_code"),
        "duration_seconds": round(
            sum(float(run.get("duration_seconds", 0.0)) for run in run_results),
            6,
        ),
        "stdout_tail": representative.get("stdout_tail", ""),
        "stderr_tail": representative.get("stderr_tail", ""),
        "input": inspection,
        "toolpath_files": representative.get("toolpath_files", []),
        "toolpath": representative.get("toolpath", _toolpath_metrics(b"")),
        "stable_across_runs": stable_across_runs,
        "runs": run_results,
    }


def _preview_colors_with_names(analysis: Any) -> dict[Any, Any]:
    colors = dict(analysis.preview_colors)
    for index, name in enumerate(analysis.slot_names):
        colors[name] = colors[index]
    colors["Board"] = colors[0]
    return colors


def _generate_artifacts(output_dir: Path) -> dict[str, Any]:
    """Generate representative GLB and slicer-specific 3MF artifacts."""

    import trimesh

    from core.pipeline.vector_glb_preview import (
        build_vector_preview_parts_from_analysis,
        export_vector_glb_preview_v2,
    )
    from core.vector_engine import VectorProcessor, _VECTOR_PARSE_CLIP_CACHE
    from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

    output_dir.mkdir(parents=True, exist_ok=True)
    fixture = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "native_svg"
        / "clip_inherited_fill.svg"
    )
    lut_path = (
        REPO_ROOT
        / "tests/fixtures/lut_regression/Bambulab&PLA&RYBW&红-黄-蓝-白.npy"
    )
    processor = VectorProcessor(str(lut_path), "4-Color (RYBW)")
    _VECTOR_PARSE_CLIP_CACHE.clear()
    analysis = processor.analyze_svg(str(fixture), 40.0)
    if analysis.stage_timings.get("geometry_backend") != "native":
        raise RuntimeError(
            "native_artifact_generation_fell_back:"
            + str(analysis.stage_timings.get("native_fallback_reason"))
        )
    scene = processor.build_mesh(
        analysis,
        thickness_mm=0.8,
        structure_mode="Single-sided",
    )
    preview_colors = _preview_colors_with_names(analysis)

    parts = build_vector_preview_parts_from_analysis(
        analysis=analysis,
        preview_colors=preview_colors,
        slot_list=list(analysis.slot_names),
        structure_mode="Single-sided",
        color_mode=processor.color_mode,
        thickness_mm=0.8,
        separate_backing=True,
        include_backing=True,
        include_outline=False,
        outline_width_mm=0.0,
    )
    glb_path = output_dir / "native-svg-reality.glb"
    export_vector_glb_preview_v2(
        parts,
        output_path=str(glb_path),
        pixels_per_mm=1.0,
    )
    loaded_glb = trimesh.load(glb_path, force="scene")
    if not loaded_glb.geometry:
        raise RuntimeError("generated_glb_is_empty")

    project_paths: dict[str, Path] = {}
    used_names = list(scene.geometry)
    for slicer_name in ("BambuStudio", "OrcaSlicer"):
        project_path = output_dir / f"native-svg-{slicer_name}.3mf"
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=str(project_path),
            slot_names=used_names,
            preview_colors=preview_colors,
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer=slicer_name,
            nozzle_size="0.4",
            project_slot_names=analysis.slot_names,
        )
        project_paths[slicer_name] = project_path

    manifest = {
        "schema_version": 1,
        "status": "generated",
        "geometry_backend": analysis.stage_timings.get("geometry_backend"),
        "native_version": analysis.stage_timings.get("native_version"),
        "fixture": {
            "path": fixture.relative_to(REPO_ROOT).as_posix(),
            "sha256": _sha256_file(fixture),
        },
        "analysis": {
            "raw_shape_count": len(analysis.shape_data),
            "visible_shape_count": len(analysis.clipped_shapes),
            "matched_shape_count": len(analysis.matched_shapes),
            "bbox": [float(value) for value in analysis.bbox],
            "scale_factor": float(analysis.scale_factor),
        },
        "glb": {
            "path": glb_path.name,
            "byte_size": glb_path.stat().st_size,
            "sha256": _sha256_file(glb_path),
            "geometry_count": len(loaded_glb.geometry),
        },
        "projects": {
            name: _inspect_3mf(path) for name, path in project_paths.items()
        },
    }
    manifest_path = output_dir / "artifact-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "glb_path": glb_path,
        "BambuStudio": project_paths["BambuStudio"],
        "OrcaSlicer": project_paths["OrcaSlicer"],
    }


def _host_manifest() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-artifacts", action="store_true")
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=REPO_ROOT / "output" / "native-svg-reality",
    )
    parser.add_argument("--bambu-executable", type=Path)
    parser.add_argument("--orca-executable", type=Path)
    parser.add_argument("--bambu-3mf", type=Path)
    parser.add_argument("--orca-3mf", type=Path)
    parser.add_argument("--no-auto-detect", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--validation-runs", type=int, default=2)
    parser.add_argument(
        "--coverage-probes", type=Path,
        help="JSON mapping slicer names to x_mm/y_mm/z_mm/max_distance_mm probes; optional tool_id.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPO_ROOT / "progress" / "native-svg-slicer-reality.json",
    )
    args = parser.parse_args()
    probes = (
        json.loads(args.coverage_probes.read_text(encoding="utf-8"))
        if args.coverage_probes else {}
    )

    generated = None
    if args.generate_artifacts or args.generate_only:
        generated = _generate_artifacts(args.artifact_dir.resolve())
    if args.generate_only:
        report = {
            "schema_version": 1,
            "status": "generated",
            "host": _host_manifest(),
            "artifacts": generated["manifest"],
        }
        _write_report(args.report, report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    bambu_project = (
        args.bambu_3mf.resolve()
        if args.bambu_3mf is not None
        else generated["BambuStudio"] if generated else None
    )
    orca_project = (
        args.orca_3mf.resolve()
        if args.orca_3mf is not None
        else generated["OrcaSlicer"] if generated else None
    )
    if bambu_project is None or orca_project is None:
        parser.error(
            "provide both --bambu-3mf/--orca-3mf or use --generate-artifacts"
        )

    auto_detect = not args.no_auto_detect
    executable_paths = {
        "BambuStudio": _resolve_executable(
            "BambuStudio", args.bambu_executable, auto_detect=auto_detect
        ),
        "OrcaSlicer": _resolve_executable(
            "OrcaSlicer", args.orca_executable, auto_detect=auto_detect
        ),
    }
    output_root = args.artifact_dir.resolve() / "toolpaths"
    slicer_results = {
        "BambuStudio": _validate_slicer(
            "BambuStudio",
            executable_paths["BambuStudio"],
            bambu_project,
            output_root,
            timeout_seconds=args.timeout_seconds,
            validation_runs=args.validation_runs,
            coverage_probes=probes.get("BambuStudio"),
        ),
        "OrcaSlicer": _validate_slicer(
            "OrcaSlicer",
            executable_paths["OrcaSlicer"],
            orca_project,
            output_root,
            timeout_seconds=args.timeout_seconds,
            validation_runs=args.validation_runs,
            coverage_probes=probes.get("OrcaSlicer"),
        ),
    }
    statuses = {result["status"] for result in slicer_results.values()}
    if statuses == {"passed"}:
        status = "passed"
        exit_code = 0
    elif "failed" in statuses:
        status = "failed"
        exit_code = 1
    else:
        status = "reality_dependency_unavailable"
        exit_code = DEPENDENCY_UNAVAILABLE_EXIT
    report = {
        "schema_version": 1,
        "status": status,
        "host": _host_manifest(),
        "artifacts": generated["manifest"] if generated else None,
        "slicers": slicer_results,
    }
    _write_report(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
