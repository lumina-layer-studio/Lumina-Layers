"""
Pipeline coordinator — orchestrates raster (S01-S12) and preview (P01-P06) pipelines.
管道协调器 — 编排光栅管道（S01-S12）和预览管道（P01-P06）。

Provides:
    - run_raster_pipeline(ctx) -> ctx: 光栅转换管道
    - run_preview_pipeline(ctx) -> ctx: 预览管道
    - _run_vector_branch(ctx) -> ctx: SVG 矢量分支（从 ``vector_branch.py`` 重导出）

The SVG-native vector branch lives in :mod:`core.pipeline.vector_branch`;
this module re-exports its symbols below so existing callers and tests that
patch ``core.pipeline.coordinator._run_vector_branch`` etc. continue to work
unchanged.
"""

import time

import cv2

from api.structured_logging import get_logger
from api.worker_diagnostics import report_worker_stage
from core.errors import CachedPreviewAnalysisError
from core.svg_hole_compensation import validate_svg_compensation_scope
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

log = get_logger(__name__)
COORDINATOR_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    OSError,
    RuntimeError,
    ModuleNotFoundError,
    cv2.error,
)


# ---------------------------------------------------------------------------
# Raster pipeline step definitions
# ---------------------------------------------------------------------------

# Each entry: (module, step_label, progress_before, progress_after, optional)
_RASTER_STEPS = [
    # S01 is called separately (before vector branch check)
    (s02_image_processing, "S02", 0.05, 0.20, False),
    (s03_color_replacement, "S03", 0.20, 0.25, False),
    (s04_debug_preview, "S04", 0.25, 0.28, True),
    (s05_preview_generation, "S05", 0.28, 0.35, False),
    (s06_voxel_building, "S06", 0.35, 0.45, False),
    (s07_mesh_generation, "S07", 0.45, 0.60, False),
    (s08_auxiliary_meshes, "S08", 0.60, 0.68, False),
    (s09_export_3mf, "S09", 0.68, 0.75, False),
    (s10_color_recipe, "S10", 0.75, 0.80, True),
    (s11_glb_preview, "S11", 0.80, 0.90, False),
    (s12_result_assembly, "S12", 0.90, 1.00, False),
]

_PREVIEW_STEPS = [
    # P01 is called separately (for early error check)
    (p02_lut_metadata, "P02", 0.10, 0.20, False),
    (p03_core_processing, "P03", 0.20, 0.55, False),
    (p04_cache_building, "P04", 0.55, 0.70, False),
    (p05_palette_extraction, "P05", 0.70, 0.80, False),
    (p06_bed_rendering, "P06", 0.80, 1.00, False),
]


def _report_progress(ctx: dict, value: float, desc: str = "") -> None:
    """Call progress callback if present in ctx.
    如果 ctx 中存在 progress 回调则调用。

    Args:
        ctx: 管道上下文
        value: 进度值 (0.0 - 1.0)
        desc: 进度描述文本
    """
    progress = ctx.get("progress")
    if progress is not None:
        progress(value, desc=desc)


def _stop_after_step_if_requested(
    ctx: dict,
    label: str,
    pipeline_t0: float,
    step_timings: dict,
) -> bool:
    if ctx.get("stop_after_step") != label:
        return False
    total_s = time.perf_counter() - pipeline_t0
    ctx["_pipeline_stopped_after"] = label
    ctx["_pipeline_total_s"] = total_s
    ctx["_step_timings"] = dict(step_timings)
    log.debug(
        "Pipeline stopped after %s in %.2fs",
        label,
        total_s,
        extra={
            "event": "pipeline_stopped_after_step",
            "step": label,
            "duration_ms": round(total_s * 1000, 3),
        },
    )
    return True


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
    pipeline_t0 = time.perf_counter()
    step_timings = {}

    export_only = bool(ctx.get("export_only_3mf_path"))
    # ---- S01: Input validation ----
    if export_only:
        report_worker_stage("S01")
    _report_progress(ctx, 0.0, "输入验证中... | Validating inputs...")
    t0 = time.perf_counter()
    try:
        validate_svg_compensation_scope(
            enabled=ctx.get("svg_hole_compensation_enabled", False),
            image_path=ctx.get("image_path", ""),
            modeling_mode=ctx.get("modeling_mode"),
        )
        ctx = s01_input_validation.run(ctx)
    except COORDINATOR_HANDLED_ERRORS as exc:
        ctx["error"] = f"[S01] {exc}"
        return ctx
    step_timings["S01"] = time.perf_counter() - t0

    if ctx.get("error"):
        if export_only:
            ctx["error"] = f"[S01] {ctx['error']}"
        return ctx
    if _stop_after_step_if_requested(ctx, "S01", pipeline_t0, step_timings):
        return ctx

    # ---- Vector branch check ----
    if ctx.get("is_svg_vector"):
        return _run_vector_branch(ctx)

    # ---- S02-S12: Raster steps ----
    for module, label, prog_before, prog_after, optional in _RASTER_STEPS:
        # S05 also computes the keychain loop consumed by S08.
        if export_only and (label == "S04" or (label == "S05" and not ctx.get("add_loop"))):
            continue
        if export_only:
            report_worker_stage(label)
        _report_progress(ctx, prog_before, f"{label} 执行中...")
        t0 = time.perf_counter()
        try:
            ctx = module.run(ctx)
        except CachedPreviewAnalysisError:
            raise
        except COORDINATOR_HANDLED_ERRORS as exc:
            if optional:
                log.warning(
                    "Optional step %s failed: %s",
                    label,
                    exc,
                    extra={
                        "event": "pipeline_optional_step_failed",
                        "step": label,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
            else:
                ctx["error"] = f"[{label}] {exc}"
                log.error(
                    "Pipeline aborted at %s: %s",
                    label,
                    exc,
                    extra={
                        "event": "pipeline_aborted",
                        "step": label,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                return ctx
        step_timings[label] = time.perf_counter() - t0
        if ctx.get("error"):
            if export_only:
                ctx["error"] = f"[{label}] {ctx['error']}"
            return ctx
        if _stop_after_step_if_requested(ctx, label, pipeline_t0, step_timings):
            return ctx
        _report_progress(ctx, prog_after)
        if export_only and label == "S09":
            ctx["result_tuple"] = (ctx["out_path"], None, None, "[OK] 3MF exported", None)
            _report_progress(ctx, 1.0)
            break

    total_s = time.perf_counter() - pipeline_t0
    log.debug(
        "Raster pipeline completed in %.2fs",
        total_s,
        extra={
            "event": "pipeline_completed",
            "duration_ms": round(total_s * 1000, 3),
            "step_timings_ms": {
                label: round(elapsed * 1000, 3)
                for label, elapsed in step_timings.items()
            },
            "count": len(step_timings),
        },
    )
    ctx["_pipeline_total_s"] = total_s
    ctx["_step_timings"] = step_timings

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
    pipeline_t0 = time.perf_counter()
    step_timings = {}

    # ---- P01: Preview validation ----
    _report_progress(ctx, 0.0, "预览验证中... | Validating preview inputs...")
    t0 = time.perf_counter()
    try:
        validate_svg_compensation_scope(
            enabled=ctx.get("svg_hole_compensation_enabled", False),
            image_path=ctx.get("image_path", ""),
            modeling_mode=ctx.get("modeling_mode"),
        )
        ctx = p01_preview_validation.run(ctx)
    except COORDINATOR_HANDLED_ERRORS as exc:
        ctx["error"] = f"[P01] {exc}"
        return ctx
    step_timings["P01"] = time.perf_counter() - t0

    if ctx.get("error"):
        return ctx

    modeling_mode = ctx.get("modeling_mode")
    modeling_mode_value = getattr(modeling_mode, "value", modeling_mode)
    image_path = str(ctx.get("image_path", "") or "")
    # NOTE: ``material_source == "material_archive"`` is now allowed to
    # take the SVG-native vector branch as well — the branch resolves
    # the right colour matcher (LUT KDTree or material-archive solver)
    # internally based on ``material_source`` so both modes share one
    # parse → clip → preview pipeline.
    # 耗材档案 + 矢量模式现在也走原生矢量分支，分支内部按 material
    # source 路由不同的颜色匹配器，预览/几何完全共线。
    is_svg_vector = (
        modeling_mode_value == "vector"
        and image_path.lower().endswith(".svg")
    )
    if is_svg_vector:
        _report_progress(ctx, 0.10, "SVG 矢量预览分析中... | Building vector preview...")
        t0 = time.perf_counter()
        ctx = _run_vector_preview_branch(ctx)
        step_timings["P_VECTOR"] = time.perf_counter() - t0
        if ctx.get("error"):
            return ctx
        total_s = time.perf_counter() - pipeline_t0
        log.debug(
            "P01 + VectorPreview completed in %.2fs",
            total_s,
            extra={
                "event": "preview_pipeline_completed",
                "duration_ms": round(total_s * 1000, 3),
                "mode": "vector",
                "step_timings_ms": {
                    label: round(elapsed * 1000, 3)
                    for label, elapsed in step_timings.items()
                },
                "count": len(step_timings),
            },
        )
        ctx["_preview_total_s"] = total_s
        ctx["_preview_step_timings"] = step_timings
        return ctx

    # ---- P02-P06 ----
    for module, label, prog_before, prog_after, optional in _PREVIEW_STEPS:
        _report_progress(ctx, prog_before, f"{label} 执行中...")
        t0 = time.perf_counter()
        try:
            ctx = module.run(ctx)
        except COORDINATOR_HANDLED_ERRORS as exc:
            if optional:
                log.warning(
                    "Optional step %s failed: %s",
                    label,
                    exc,
                    extra={
                        "event": "preview_optional_step_failed",
                        "step": label,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
            else:
                ctx["error"] = f"[{label}] {exc}"
                log.error(
                    "Preview pipeline aborted at %s: %s",
                    label,
                    exc,
                    extra={
                        "event": "preview_pipeline_aborted",
                        "step": label,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                return ctx
        step_timings[label] = time.perf_counter() - t0
        if ctx.get("error"):
            return ctx
        _report_progress(ctx, prog_after)

    total_s = time.perf_counter() - pipeline_t0
    log.debug(
        "P01-P06 completed in %.2fs",
        total_s,
        extra={
            "event": "preview_pipeline_completed",
            "duration_ms": round(total_s * 1000, 3),
            "mode": "raster",
            "step_timings_ms": {
                label: round(elapsed * 1000, 3)
                for label, elapsed in step_timings.items()
            },
            "count": len(step_timings),
        },
    )
    ctx["_preview_total_s"] = total_s
    ctx["_preview_step_timings"] = step_timings

    return ctx


# ===================================================================
# Vector branch re-exports
# 矢量分支重导出 — 实现位于 core/pipeline/vector_branch.py（Phase 0 Sub-PR D）
# ===================================================================
#
# These bindings are deliberately placed AFTER ``COORDINATOR_HANDLED_ERRORS``
# and ``_report_progress`` so that vector_branch.py can pull both names from
# this module during the cycle-safe import without ImportError.
from core.pipeline.vector_branch import (  # noqa: E402
    _update_bambu_base_layer_ctx_for_vector,
    _run_vector_branch,
    _run_vector_preview_branch,
    _log_vector_timings,
)

__all__ = [
    "run_raster_pipeline",
    "run_preview_pipeline",
    "COORDINATOR_HANDLED_ERRORS",
    "_run_vector_branch",
    "_run_vector_preview_branch",
    "_update_bambu_base_layer_ctx_for_vector",
    "_log_vector_timings",
]
