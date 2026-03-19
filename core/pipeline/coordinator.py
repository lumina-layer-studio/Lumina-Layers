"""
Pipeline coordinator — orchestrates raster (S01-S12) and preview (P01-P06) pipelines.
管道协调器 — 编排光栅管道（S01-S12）和预览管道（P01-P06）。

Provides:
    - run_raster_pipeline(ctx) -> ctx: 光栅转换管道
    - run_preview_pipeline(ctx) -> ctx: 预览管道
    - _run_vector_branch(ctx) -> ctx: SVG 矢量分支（内部使用）
"""

import os
import time

import cv2
import numpy as np

from core.pipeline import (
    s01_input_validation,
    s02_image_processing,
    s03_color_replacement,
    s04_debug_preview,
    s05_preview_generation,
    s06_voxel_building,
    s07_mesh_generation,
    s08_auxiliary_meshes,
    s09_export_3mf,
    s10_color_recipe,
    s11_glb_preview,
    s12_result_assembly,
    p01_preview_validation,
    p02_lut_metadata,
    p03_core_processing,
    p04_cache_building,
    p05_palette_extraction,
    p06_bed_rendering,
)
from core.pipeline.s03_color_replacement import _normalize_color_replacements_input

# Try to import SVG rendering libraries (for vector branch 2D preview)
try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM
    HAS_SVG_LIB = True
except ImportError:
    HAS_SVG_LIB = False


# ---------------------------------------------------------------------------
# Raster pipeline step definitions
# ---------------------------------------------------------------------------

# Each entry: (module, step_label, progress_before, progress_after, optional)
_RASTER_STEPS = [
    # S01 is called separately (before vector branch check)
    (s02_image_processing, "S02", 0.05, 0.20, False),
    (s03_color_replacement, "S03", 0.20, 0.25, False),
    (s04_debug_preview,     "S04", 0.25, 0.28, True),
    (s05_preview_generation,"S05", 0.28, 0.35, False),
    (s06_voxel_building,    "S06", 0.35, 0.45, False),
    (s07_mesh_generation,   "S07", 0.45, 0.60, False),
    (s08_auxiliary_meshes,  "S08", 0.60, 0.68, False),
    (s09_export_3mf,        "S09", 0.68, 0.75, False),
    (s10_color_recipe,      "S10", 0.75, 0.80, True),
    (s11_glb_preview,       "S11", 0.80, 0.90, False),
    (s12_result_assembly,   "S12", 0.90, 1.00, False),
]

_PREVIEW_STEPS = [
    # P01 is called separately (for early error check)
    (p02_lut_metadata,    "P02", 0.10, 0.20, False),
    (p03_core_processing, "P03", 0.20, 0.55, False),
    (p04_cache_building,  "P04", 0.55, 0.70, False),
    (p05_palette_extraction, "P05", 0.70, 0.80, False),
    (p06_bed_rendering,   "P06", 0.80, 1.00, False),
]


def _report_progress(ctx: dict, value: float, desc: str = "") -> None:
    """Call progress callback if present in ctx.
    如果 ctx 中存在 progress 回调则调用。

    Args:
        ctx: 管道上下文
        value: 进度值 (0.0 - 1.0)
        desc: 进度描述文本
    """
    progress = ctx.get('progress')
    if progress is not None:
        progress(value, desc=desc)


# ===================================================================
# Raster pipeline
# ===================================================================

def run_raster_pipeline(ctx: dict) -> dict:
    """Execute raster conversion pipeline S01-S12 in order.
    按顺序执行光栅转换管道 S01-S12。

    S01 执行后检查 ``is_svg_vector`` 标志，若为 True 则走矢量分支
    ``_run_vector_branch``，不再执行 S02-S12。

    S04（调试预览）和 S10（颜色配方）标记为 optional，失败仅打印
    警告，不终止管道。其余步骤抛出异常时捕获并写入 ``ctx['error']``，
    提前终止管道。

    Args:
        ctx: 已初始化的 PipelineContext 字典

    Returns:
        更新后的 PipelineContext 字典
    """
    # ---- S01: Input validation ----
    _report_progress(ctx, 0.0, "输入验证中... | Validating inputs...")
    try:
        ctx = s01_input_validation.run(ctx)
    except Exception as exc:
        ctx['error'] = f"[S01] {exc}"
        return ctx

    if ctx.get('error'):
        return ctx

    # ---- Vector branch check ----
    if ctx.get('is_svg_vector'):
        return _run_vector_branch(ctx)

    # ---- S02-S12: Raster steps ----
    for module, label, prog_before, prog_after, optional in _RASTER_STEPS:
        _report_progress(ctx, prog_before, f"{label} 执行中...")
        try:
            ctx = module.run(ctx)
        except Exception as exc:
            if optional:
                print(f"[COORDINATOR] Warning: optional step {label} failed: {exc}")
            else:
                ctx['error'] = f"[{label}] {exc}"
                print(f"[COORDINATOR] Pipeline aborted at {label}: {exc}")
                return ctx
        if ctx.get('error'):
            return ctx
        _report_progress(ctx, prog_after)

    return ctx


# ===================================================================
# Preview pipeline
# ===================================================================

def run_preview_pipeline(ctx: dict) -> dict:
    """Execute preview pipeline P01-P06 in order.
    按顺序执行预览管道 P01-P06。

    任意步骤抛出异常时捕获并写入 ``ctx['error']``，提前终止管道。

    Args:
        ctx: 已初始化的 PipelineContext 字典

    Returns:
        更新后的 PipelineContext 字典
    """
    # ---- P01: Preview validation ----
    _report_progress(ctx, 0.0, "预览验证中... | Validating preview inputs...")
    try:
        ctx = p01_preview_validation.run(ctx)
    except Exception as exc:
        ctx['error'] = f"[P01] {exc}"
        return ctx

    if ctx.get('error'):
        return ctx

    # ---- P02-P06 ----
    for module, label, prog_before, prog_after, optional in _PREVIEW_STEPS:
        _report_progress(ctx, prog_before, f"{label} 执行中...")
        try:
            ctx = module.run(ctx)
        except Exception as exc:
            if optional:
                print(f"[COORDINATOR] Warning: optional step {label} failed: {exc}")
            else:
                ctx['error'] = f"[{label}] {exc}"
                print(f"[COORDINATOR] Preview pipeline aborted at {label}: {exc}")
                return ctx
        if ctx.get('error'):
            return ctx
        _report_progress(ctx, prog_after)

    return ctx



# ===================================================================
# Vector branch (SVG native processing)
# ===================================================================

def _run_vector_branch(ctx: dict) -> dict:
    """Execute SVG native vector processing branch.
    执行 SVG 原生矢量处理分支。

    当 S01 检测到 ``is_svg_vector=True`` 时由 ``run_raster_pipeline``
    调用。使用 ``core.vector_engine.VectorProcessor`` 完成 SVG → 3D
    转换，包括 3MF 导出、GLB 预览和 2D 预览生成。

    Args:
        ctx: 经过 S01 验证后的 PipelineContext 字典

    Returns:
        更新后的 PipelineContext 字典（包含 result_tuple）
    """
    from config import ColorSystem, OUTPUT_DIR
    from core.naming import generate_model_filename, generate_preview_filename
    from utils.bambu_3mf_writer import export_scene_with_bambu_metadata
    from utils import Stats

    image_path = ctx['image_path']
    actual_lut_path = ctx['actual_lut_path']
    color_mode = ctx['color_mode']
    modeling_mode = ctx['modeling_mode']
    target_width_mm = ctx['target_width_mm']
    spacer_thick = ctx['spacer_thick']
    structure_mode = ctx['structure_mode']
    color_replacements = ctx.get('color_replacements')
    replacement_regions = ctx.get('replacement_regions')

    print("[COORDINATOR] Using Native Vector Engine (Shapely/Clipper)...")
    vector_timing = {}
    vector_total_t0 = time.perf_counter()

    # ---- Normalize color replacements ----
    vector_replacements = _normalize_color_replacements_input(replacement_regions)
    if not vector_replacements:
        vector_replacements = _normalize_color_replacements_input(color_replacements)

    try:
        from core.vector_engine import VectorProcessor

        vec_processor = VectorProcessor(actual_lut_path, color_mode)

        # 1. SVG → 3D mesh
        _report_progress(ctx, 0.05, "SVG 解析与几何处理中... | Parsing & extruding SVG...")
        mesh_t0 = time.perf_counter()
        scene = vec_processor.svg_to_mesh(
            svg_path=image_path,
            target_width_mm=target_width_mm,
            thickness_mm=spacer_thick,
            structure_mode=structure_mode,
            color_replacements=vector_replacements,
        )
        vector_timing["mesh_total_s"] = time.perf_counter() - mesh_t0
        if isinstance(getattr(vec_processor, "last_stage_timings", None), dict):
            vector_timing.update(vec_processor.last_stage_timings)

        if len(scene.geometry) == 0:
            ctx['error'] = "[ERROR] Vector mesh generation failed: no valid geometry generated"
            return ctx

        # 2. Export 3MF
        _report_progress(ctx, 0.72, "导出 3MF 中... | Exporting 3MF...")
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        out_path = os.path.join(OUTPUT_DIR, generate_model_filename(base_name, modeling_mode, color_mode))

        is_six_color = len(vec_processor.img_processor.lut_rgb) == 1296
        if is_six_color:
            vec_color_conf = ColorSystem.SIX_COLOR
            vec_color_mode = "6-Color"
        else:
            vec_color_conf = ColorSystem.get(color_mode)
            vec_color_mode = color_mode

        vec_slot_names = []
        for geom_name, geom in scene.geometry.items():
            vertices = getattr(geom, "vertices", None)
            faces = getattr(geom, "faces", None)
            v_count = len(vertices) if vertices is not None else 0
            f_count = len(faces) if faces is not None else 0
            if v_count == 0 or f_count == 0:
                print(f"[COORDINATOR] Skipping empty vector geometry '{geom_name}' (v={v_count}, f={f_count})")
                continue
            vec_slot_names.append(geom_name)

        if not vec_slot_names:
            ctx['error'] = "[ERROR] Vector export aborted: all generated geometries are empty"
            return ctx

        vec_preview_colors = vec_color_conf['preview']

        vec_print_settings = {
            'layer_height': '0.08',
            'initial_layer_height': '0.08',
            'wall_loops': '1',
            'top_shell_layers': '0',
            'bottom_shell_layers': '0',
            'sparse_infill_density': '100%',
            'sparse_infill_pattern': 'zig-zag',
            'nozzle_temperature': ['220'] * 8,
            'bed_temperature': ['60'] * 8,
            'filament_type': ['PLA'] * 8,
            'print_speed': '100',
            'travel_speed': '150',
            'enable_support': '0',
            'brim_width': '5',
            'brim_type': 'auto_brim',
        }

        export_t0 = time.perf_counter()
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=out_path,
            slot_names=vec_slot_names,
            preview_colors=vec_preview_colors,
            settings=vec_print_settings,
            color_mode=vec_color_mode,
            printer_id=ctx.get('printer_id', 'bambu-h2d'),
            slicer=ctx.get('slicer', 'BambuStudio'),
        )
        print(f"[COORDINATOR] Vector 3MF exported with Bambu metadata: {out_path}")
        vector_timing["export_3mf_s"] = time.perf_counter() - export_t0

        # 3. GLB preview
        _report_progress(ctx, 0.82, "生成 3D 预览中... | Generating 3D preview...")
        glb_path = None
        glb_t0 = time.perf_counter()
        try:
            glb_path = os.path.join(OUTPUT_DIR, generate_preview_filename(base_name))
            scene.export(glb_path)
            print(f"[COORDINATOR] Preview GLB exported: {glb_path}")
        except Exception as e:
            print(f"[COORDINATOR] Warning: Preview generation skipped: {e}")
        vector_timing["export_glb_s"] = time.perf_counter() - glb_t0

        # 4. 2D preview from SVG
        _report_progress(ctx, 0.90, "生成 2D 预览中... | Generating 2D preview...")
        preview_img = None
        preview_t0 = time.perf_counter()
        skip_heavy_preview = os.getenv("LUMINA_VECTOR_SKIP_2D_PREVIEW", "0") == "1"
        if skip_heavy_preview:
            print("[COORDINATOR] Skipping SVG 2D preview due to LUMINA_VECTOR_SKIP_2D_PREVIEW=1")
        elif HAS_SVG_LIB:
            preview_img = _generate_vector_2d_preview(
                vec_processor, image_path, target_width_mm, vector_replacements
            )
        else:
            print("[COORDINATOR] svglib not installed, skipping 2D preview")
        vector_timing["preview_2d_s"] = time.perf_counter() - preview_t0

        # 5. Stats & timing
        Stats.increment("conversions")
        vector_timing["vector_branch_total_s"] = time.perf_counter() - vector_total_t0
        _log_vector_timings(vector_timing)

        msg = "Vector conversion complete! Objects merged by material."
        ctx['result_tuple'] = (out_path, glb_path, preview_img, msg, None)
        return ctx

    except Exception as e:
        error_msg = (
            f"Vector processing failed: {e}\n\n"
            "Suggestions:\n"
            "- Ensure SVG has filled paths (not just strokes)\n"
            "- Try opening in Inkscape and re-saving as 'Plain SVG'\n"
            "- Convert text to paths (Path -> Object to Path)\n"
            "- Or switch to 'High-Fidelity' mode for rasterization"
        )
        print(f"[COORDINATOR] {error_msg}")
        ctx['error'] = error_msg
        return ctx


def _generate_vector_2d_preview(vec_processor, image_path: str,
                                target_width_mm: float,
                                vector_replacements: dict) -> 'np.ndarray | None':
    """Generate 2D preview image from SVG for vector branch.
    为矢量分支从 SVG 生成 2D 预览图像。

    Args:
        vec_processor: VectorProcessor 实例
        image_path: SVG 文件路径
        target_width_mm: 目标宽度（毫米）
        vector_replacements: 颜色替换映射

    Returns:
        np.ndarray | None: RGBA 预览图像，失败返回 None
    """
    try:
        preview_rgba = vec_processor.img_processor._load_svg(
            image_path, target_width_mm, pixels_per_mm=10.0
        )

        # Apply color replacements to preview
        if vector_replacements:
            from core.color_replacement import ColorReplacementManager
            manager = ColorReplacementManager.from_dict(vector_replacements)
            replacements = manager.get_all_replacements()

            if replacements:
                print(f"[COORDINATOR] Applying {len(replacements)} color replacements to SVG preview...")
                rgb_data = preview_rgba[:, :, :3]
                alpha_data = preview_rgba[:, :, 3]
                mask_solid = alpha_data > 10

                for orig_color, repl_color in replacements.items():
                    orig_arr = np.array(orig_color, dtype=np.uint8)
                    repl_arr = np.array(repl_color, dtype=np.uint8)
                    diff = np.abs(rgb_data.astype(int) - orig_arr.astype(int))
                    distance = np.sum(diff, axis=2)
                    threshold = 50
                    match_mask = (distance < threshold) & mask_solid
                    if np.any(match_mask):
                        rgb_data[match_mask] = repl_arr
                        matched_count = np.sum(match_mask)
                        print(f"[COORDINATOR]   {orig_color} -> {repl_color}: {matched_count} pixels")

                preview_rgba[:, :, :3] = rgb_data
                print("[COORDINATOR] Color replacements applied to SVG preview")

        # Downscale overly large previews
        max_preview_px = 1600
        h, w = preview_rgba.shape[:2]
        if w > max_preview_px:
            scale = max_preview_px / w
            new_w = max_preview_px
            new_h = max(1, int(h * scale))
            preview_rgba = cv2.resize(preview_rgba, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Fix black background: set transparent pixels to white RGB
        alpha_channel = preview_rgba[:, :, 3]
        transparent_mask = alpha_channel == 0
        if np.any(transparent_mask):
            preview_rgba[transparent_mask, :3] = 255

        print("[COORDINATOR] Generated 2D vector preview")
        return preview_rgba

    except Exception as e:
        print(f"[COORDINATOR] Failed to render SVG preview: {e}")
        return None


def _log_vector_timings(timings: dict) -> None:
    """Log vector branch timing breakdown.
    输出矢量分支计时明细。

    Args:
        timings: 计时字典
    """
    if not timings:
        return
    print(
        "[COORDINATOR] Vector timings (s): "
        f"parse={timings.get('parse_s', 0.0):.3f}, "
        f"clip={timings.get('occlusion_s', 0.0):.3f}, "
        f"match={timings.get('color_match_s', 0.0):.3f}, "
        f"extrude_bottom={timings.get('extrude_bottom_s', 0.0):.3f}, "
        f"backing={timings.get('backing_s', 0.0):.3f}, "
        f"extrude_top={timings.get('extrude_top_s', 0.0):.3f}, "
        f"assemble={timings.get('assemble_s', 0.0):.3f}, "
        f"mesh_total={timings.get('mesh_total_s', 0.0):.3f}, "
        f"export_3mf={timings.get('export_3mf_s', 0.0):.3f}, "
        f"export_glb={timings.get('export_glb_s', 0.0):.3f}, "
        f"preview_2d={timings.get('preview_2d_s', 0.0):.3f}, "
        f"total={timings.get('vector_branch_total_s', 0.0):.3f}"
    )
