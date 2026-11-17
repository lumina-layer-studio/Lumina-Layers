"""Deterministic SVG-to-3D regression repro harness.

Runs the native vector processor outside FastAPI and writes diagnostic
artefacts for edge precision and white-seam analysis.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import trimesh
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.vector_engine import VectorProcessor  # noqa: E402

LOGGER = logging.getLogger("svg_converter_repro")


@dataclass(frozen=True)
class _ModeConfig:
    mode_key: str
    color_mode: str
    lut_path: Path


_MODES: dict[str, _ModeConfig] = {
    "4color_rybw": _ModeConfig(
        mode_key="4color_rybw",
        color_mode="4-Color (RYBW)",
        lut_path=Path("tests/fixtures/lut_regression") / "Bambulab&PLA&RYBW&红-黄-蓝-白.npy",
    ),
    "6color_rybw": _ModeConfig(
        mode_key="6color_rybw",
        color_mode="6-Color",
        lut_path=Path("tests/fixtures/frozen_assets/luts/6c")
        / "Aliz&PLA&RYBW&红-蓝-黄-绿-白-黑&20260211.npy",
    ),
    "5color_ext": _ModeConfig(
        mode_key="5color_ext",
        color_mode="5-Color Extended",
        lut_path=Path("tests/fixtures/lut_regression") / "Bambulab&PLA&RYBW&红-黄-蓝-白.npy",
    ),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic SVG vector-engine repro artefact generation."
    )
    parser.add_argument("--svg", type=Path, default=Path("test_images") / "1.svg")
    parser.add_argument("--out-root", type=Path, default=Path("output") / "repro" / "phase0")
    parser.add_argument("--target-width-mm", type=float, default=100.0)
    parser.add_argument("--thickness-mm", type=float, default=2.4)
    parser.add_argument(
        "--modes",
        default=",".join(_MODES),
        help="Comma-separated subset of 4color_rybw,6color_rybw,5color_ext.",
    )
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _selected_modes(raw_modes: str) -> list[_ModeConfig]:
    mode_keys = [item.strip() for item in raw_modes.split(",") if item.strip()]
    unknown = [item for item in mode_keys if item not in _MODES]
    if unknown:
        valid = ", ".join(_MODES)
        raise ValueError(f"Unknown mode key(s): {', '.join(unknown)}. Valid keys: {valid}.")
    return [_MODES[item] for item in mode_keys]


def _round_float(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (np.floating,)):
        return round(float(value), 6)
    return value


def _rounded_list(values: Iterable[Any]) -> list[Any]:
    return [_round_float(value) for value in values]


def _rgb_to_hex(rgb: Iterable[int]) -> str:
    r, g, b = (int(channel) & 255 for channel in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _iter_polygons(geometry: Any) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return []


def _vertex_count(geometry: Any) -> int:
    total = 0
    for polygon in _iter_polygons(geometry):
        total += len(polygon.exterior.coords)
        total += sum(len(ring.coords) for ring in polygon.interiors)
    return total


def _shape_pairs(analysis: Any) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    pairs = []
    for index, (clipped, matched) in enumerate(zip(analysis.clipped_shapes, analysis.matched_shapes)):
        draw_order = int(clipped.get("draw_order", index))
        pairs.append((index, clipped, matched, draw_order))
    pairs.sort(key=lambda item: (item[3], item[0]))
    return [(index, clipped, matched) for index, clipped, matched, _ in pairs]


def _stable_stage_timings(stage_timings: dict[str, Any]) -> dict[str, float]:
    return {key: 0.0 for key in sorted(stage_timings)}


def _build_shape_stats(
    mode_config: _ModeConfig,
    analysis: Any,
    processor: VectorProcessor,
) -> dict[str, Any]:
    scale_factor = float(analysis.scale_factor)
    clipped_shapes = []

    for output_index, (source_index, clipped, matched) in enumerate(_shape_pairs(analysis)):
        geometry = matched.get("geometry") or clipped.get("geometry")
        bounds = geometry.bounds if geometry is not None and not geometry.is_empty else (0.0, 0.0, 0.0, 0.0)
        color = matched.get("color") or clipped.get("color") or (0, 0, 0)
        matched_rgb = matched.get("matched_rgb") or color
        area_mm2 = float(geometry.area) * scale_factor * scale_factor if geometry is not None else 0.0

        clipped_shapes.append(
            {
                "idx": output_index,
                "draw_order": int(clipped.get("draw_order", source_index)),
                "geom_type": str(getattr(geometry, "geom_type", "")),
                "area_mm2": round(area_mm2, 6),
                "n_vertices": _vertex_count(geometry),
                "fill_hex": _rgb_to_hex(color),
                "matched_rgb": [int(channel) for channel in matched_rgb],
                "recipe": [int(channel) for channel in matched.get("recipe", [])],
                "bounds_mm": _rounded_list(
                    [
                        float(bounds[0]) * scale_factor,
                        float(bounds[1]) * scale_factor,
                        float(bounds[2]) * scale_factor,
                        float(bounds[3]) * scale_factor,
                    ]
                ),
            }
        )

    return {
        "mode_key": mode_config.mode_key,
        "color_mode": mode_config.color_mode,
        "lut_path": mode_config.lut_path.as_posix(),
        "scale_factor": round(scale_factor, 6),
        "bbox": _rounded_list(analysis.bbox),
        "num_channels": int(analysis.num_channels),
        "num_layers": int(analysis.num_layers),
        "slot_names": [str(slot) for slot in analysis.slot_names],
        "parse_warnings": list(getattr(processor, "parse_warnings", []) or []),
        "stage_timings": _stable_stage_timings(dict(analysis.stage_timings)),
        "clipped_shapes": clipped_shapes,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _save_preview(path: Path, preview: Any) -> None:
    if isinstance(preview, Image.Image):
        image = preview
    else:
        array = np.asarray(preview)
        image = Image.fromarray(array.astype(np.uint8), mode="RGBA")
    image.save(path)


def _canvas_size(analysis: Any, pixels_per_mm: float) -> tuple[int, int]:
    width_mm = float(analysis.bbox[2]) * float(analysis.scale_factor)
    height_mm = float(analysis.bbox[3]) * float(analysis.scale_factor)
    width_px = max(1, int(round(width_mm * pixels_per_mm)))
    height_px = max(1, int(round(height_mm * pixels_per_mm)))
    return width_px, height_px


def _transform_coords(coords: Iterable[tuple[float, float]], scale: float) -> list[tuple[int, int]]:
    return [(int(round(float(x) * scale)), int(round(float(y) * scale))) for x, y in coords]


def _draw_masked_polygon(
    base: Image.Image,
    polygon: Any,
    fill_rgba: tuple[int, int, int, int],
    coord_scale: float,
) -> None:
    mask = Image.new("L", base.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    exterior = _transform_coords(polygon.exterior.coords, coord_scale)
    if len(exterior) >= 3:
        mask_draw.polygon(exterior, fill=255)
    for interior in polygon.interiors:
        hole = _transform_coords(interior.coords, coord_scale)
        if len(hole) >= 3:
            mask_draw.polygon(hole, fill=0)

    color_layer = Image.new("RGBA", base.size, fill_rgba)
    base.alpha_composite(Image.composite(color_layer, Image.new("RGBA", base.size, (0, 0, 0, 0)), mask))


def _draw_geometry_fill(
    base: Image.Image,
    geometry: Any,
    fill_rgba: tuple[int, int, int, int],
    coord_scale: float,
) -> None:
    for polygon in _iter_polygons(geometry):
        _draw_masked_polygon(base, polygon, fill_rgba, coord_scale)


def _contrast_color(rgb: tuple[int, int, int]) -> tuple[int, int, int, int]:
    luminance = (0.299 * rgb[0]) + (0.587 * rgb[1]) + (0.114 * rgb[2])
    return (0, 0, 0, 255) if luminance > 160 else (255, 255, 255, 255)


def _draw_geometry_boundary(
    draw: ImageDraw.ImageDraw,
    geometry: Any,
    line_rgba: tuple[int, int, int, int],
    coord_scale: float,
) -> None:
    for polygon in _iter_polygons(geometry):
        exterior = _transform_coords(polygon.exterior.coords, coord_scale)
        if len(exterior) >= 2:
            draw.line(exterior, fill=line_rgba, width=1, joint="curve")
        for interior in polygon.interiors:
            hole = _transform_coords(interior.coords, coord_scale)
            if len(hole) >= 2:
                draw.line(hole, fill=line_rgba, width=1, joint="curve")


def _save_overlay(path: Path, analysis: Any, pixels_per_mm: float = 20.0) -> None:
    width_px, height_px = _canvas_size(analysis, pixels_per_mm)
    coord_scale = float(analysis.scale_factor) * pixels_per_mm
    image = Image.new("RGBA", (width_px, height_px), (255, 255, 255, 255))

    if analysis.silhouette is not None and not analysis.silhouette.is_empty:
        _draw_geometry_fill(image, analysis.silhouette, (216, 216, 216, 255), coord_scale)

    for _, clipped, matched in _shape_pairs(analysis):
        geometry = matched.get("geometry") or clipped.get("geometry")
        rgb_raw = matched.get("matched_rgb") or matched.get("color") or clipped.get("color") or (0, 0, 0)
        rgb = tuple(int(channel) & 255 for channel in rgb_raw[:3])
        _draw_geometry_fill(image, geometry, (*rgb, int(round(255 * 0.85))), coord_scale)

    draw = ImageDraw.Draw(image)
    for _, clipped, matched in _shape_pairs(analysis):
        geometry = matched.get("geometry") or clipped.get("geometry")
        rgb_raw = matched.get("matched_rgb") or matched.get("color") or clipped.get("color") or (0, 0, 0)
        rgb = tuple(int(channel) & 255 for channel in rgb_raw[:3])
        _draw_geometry_boundary(draw, geometry, _contrast_color(rgb), coord_scale)

    image.convert("RGB").save(path)


def _as_scene(mesh_result: Any) -> Any:
    if isinstance(mesh_result, trimesh.Scene):
        return mesh_result
    scene = trimesh.Scene()
    if isinstance(mesh_result, trimesh.Trimesh):
        scene.add_geometry(mesh_result, geom_name=mesh_result.metadata.get("name", "mesh"))
        return scene
    if isinstance(mesh_result, (list, tuple)):
        for index, mesh in enumerate(mesh_result):
            if isinstance(mesh, trimesh.Trimesh):
                scene.add_geometry(mesh, geom_name=mesh.metadata.get("name", f"mesh_{index}"))
        return scene
    raise TypeError(f"Unsupported mesh result type: {type(mesh_result).__name__}")


def _export_mesh(mesh_result: Any, model_path: Path) -> None:
    scene = _as_scene(mesh_result)
    scene.export(os.fspath(model_path))


def _write_model_error(path: Path, exc: BaseException) -> None:
    path.write_text(
        "".join(traceback.format_exception_only(type(exc), exc)).strip() + "\n",
        encoding="utf-8",
    )


def _format_warning(warnings: list[str], mesh_error: str | None, mode_error: str | None) -> str:
    parts = []
    parts.extend(warnings)
    if mesh_error:
        parts.append(f"3MF export: {mesh_error}")
    if mode_error:
        parts.append(mode_error)
    return "<br>".join(parts) if parts else ""


def _write_summary(out_root: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# SVG Converter Repro Summary",
        "",
        "| mode_key | num_shapes | total_area_mm2 | preview path | overlay path | 3MF path | warnings |",
        "| --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {mode_key} | {num_shapes} | {total_area_mm2:.6f} | {preview_path} | "
            "{overlay_path} | {model_path} | {warnings} |".format(**row)
        )
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_mode(
    mode_config: _ModeConfig,
    svg_path: Path,
    out_root: Path,
    target_width_mm: float,
    thickness_mm: float,
) -> tuple[dict[str, Any], bool]:
    mode_dir = out_root / mode_config.mode_key
    mode_dir.mkdir(parents=True, exist_ok=True)
    lut_abs = _resolve_repo_path(mode_config.lut_path)
    if not lut_abs.exists():
        raise FileNotFoundError(
            f"LUT file for mode '{mode_config.mode_key}' was not found: {lut_abs}. "
            "Verify the checkout includes the fixed test LUT fixture."
        )

    LOGGER.info("%s: analyze start", mode_config.mode_key)
    processor = VectorProcessor(os.fspath(lut_abs), mode_config.color_mode)
    analysis = processor.analyze_svg(
        os.fspath(svg_path),
        target_width_mm=target_width_mm,
    )

    stats = _build_shape_stats(mode_config, analysis, processor)
    stats_path = mode_dir / "shape_stats.json"
    _write_json(stats_path, stats)
    LOGGER.info("%s: shape_stats written", mode_config.mode_key)

    preview_path = mode_dir / "preview.png"
    preview = VectorProcessor.render_preview(analysis, pixels_per_mm=20.0)
    _save_preview(preview_path, preview)
    LOGGER.info("%s: preview written", mode_config.mode_key)

    model_path = mode_dir / "model.3mf"
    model_error_path = mode_dir / "model.error.txt"
    mesh_error = None
    try:
        LOGGER.info("%s: mesh build start", mode_config.mode_key)
        mesh_result = processor.build_mesh(analysis, thickness_mm=thickness_mm)
        _export_mesh(mesh_result, model_path)
        if model_error_path.exists():
            model_error_path.unlink()
        LOGGER.info("%s: model.3mf written", mode_config.mode_key)
    except Exception as exc:
        mesh_error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        _write_model_error(model_error_path, exc)
        if model_path.exists():
            model_path.unlink()
        LOGGER.exception("%s: model.3mf export failed", mode_config.mode_key)

    overlay_path = mode_dir / "shapes_overlay.png"
    _save_overlay(overlay_path, analysis, pixels_per_mm=20.0)
    LOGGER.info("%s: shapes_overlay written", mode_config.mode_key)

    total_area = sum(shape["area_mm2"] for shape in stats["clipped_shapes"])
    summary_row = {
        "mode_key": mode_config.mode_key,
        "num_shapes": len(stats["clipped_shapes"]),
        "total_area_mm2": total_area,
        "preview_path": preview_path.as_posix(),
        "overlay_path": overlay_path.as_posix(),
        "model_path": model_path.as_posix() if model_path.exists() else model_error_path.as_posix(),
        "warnings": _format_warning(stats["parse_warnings"], mesh_error, None),
    }
    return summary_row, mesh_error is None


def main() -> int:
    """Run the SVG converter repro CLI.
    运行 SVG 转 3D 复现命令行工具。
    """
    from api.structured_logging import configure_structured_logging

    configure_structured_logging()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = _parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)

    svg_path = _resolve_repo_path(args.svg)
    out_root = _resolve_repo_path(args.out_root)
    if not svg_path.exists():
        raise FileNotFoundError(f"SVG input was not found: {svg_path}")

    rows: list[dict[str, Any]] = []
    full_success = True
    for mode_config in _selected_modes(args.modes):
        try:
            row, mode_success = _run_mode(
                mode_config=mode_config,
                svg_path=svg_path,
                out_root=out_root,
                target_width_mm=args.target_width_mm,
                thickness_mm=args.thickness_mm,
            )
            rows.append(row)
            full_success = full_success and mode_success
        except Exception as exc:
            full_success = False
            LOGGER.exception("%s: mode failed", mode_config.mode_key)
            mode_dir = out_root / mode_config.mode_key
            mode_dir.mkdir(parents=True, exist_ok=True)
            error_path = mode_dir / "mode.error.txt"
            _write_model_error(error_path, exc)
            rows.append(
                {
                    "mode_key": mode_config.mode_key,
                    "num_shapes": 0,
                    "total_area_mm2": 0.0,
                    "preview_path": "",
                    "overlay_path": "",
                    "model_path": error_path.as_posix(),
                    "warnings": _format_warning([], None, str(exc)),
                }
            )

    _write_summary(out_root, rows)
    LOGGER.info("summary written: %s", out_root / "summary.md")
    return 0 if full_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
