"""Async segmented-GLB build scheduling for the converter router.

Background / 背景:
    ``generate_segmented_glb`` dominates every replace-flow endpoint: on a
    2984×2000 image with ~64 unique colours it takes ~35 s — roughly 77 %
    of the total /region-replace latency. Running it inside the HTTP request
    blocks the UI for tens of seconds even when the 2D preview (PNG) is
    already known. This module lets a replace endpoint return the freshly
    rendered 2D PNG immediately while the GLB is rebuilt in a background
    thread; the frontend polls :func:`get_glb_status` to pick up the new
    GLB URL once it's ready.

Threading model / 线程模型:
    A module-level :class:`ThreadPoolExecutor` (``max_workers=2``) runs the
    per-session GLB builds without competing with FastAPI's request event
    loop. ``generate_segmented_glb`` spends most of its time inside Shapely,
    trimesh and NumPy C extensions that release the GIL, so a thread pool
    is a good fit here — and it avoids the pickle cost we'd pay to ship
    several-hundred-MB NumPy arrays through the ProcessPool boundary.

Job-token guard / 任务令牌保护:
    Each scheduling call writes a fresh ``job_token`` into the session's
    ``preview_cache`` and atomically claims its cache revision. When a newer
    edit arrives while an older GLB build is still running, the old worker
    discards its result if either the token or the captured cache revision
    changed. Late schedulers also claim the latest stored revision instead of
    restoring their caller's stale snapshot.
"""

from __future__ import annotations

import atexit
import math
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, TypedDict

from api.file_registry import FileRegistry
from api.preview_mesh_cache import RecentPreviewMesh, mesh_input_digest
from api.preview_cache_artifacts import (
    PREVIEW_CACHE_REVISION_KEY,
    hydrate_preview_cache_for_worker,
    is_preview_cache_artifact_ref,
    merge_preview_cache_metadata,
)
from api.session_store import SessionStore
from api.structured_logging import get_logger
from config import OUTPUT_DIR, PrinterConfig
from core.converter import generate_segmented_glb
from core.errors import CoreError
from core.naming import generate_segmented_glb_filename
from core.pipeline.s11_glb_preview import extract_color_contours, _resolve_kernel_choice
from core.pipeline.vector_glb_preview import (
    build_vector_quick_preview_parts,
    coerce_preview_rgba,
    export_vector_quick_preview_glb,
    load_vector_quick_preview_source,
)

from .common import NON_FATAL_GLB_ERRORS

log = get_logger(__name__)
_RECENT_MESH = RecentPreviewMesh()
atexit.register(_RECENT_MESH.clear)
_GLB_BUILD_ERRORS = NON_FATAL_GLB_ERRORS + (CoreError,)
_GLB_CACHE_UNAVAILABLE_MESSAGE = (
    "3D preview cache is unavailable. Re-run preview before updating the 3D preview."
)
_GLB_BUILD_FAILED_MESSAGE = (
    "3D preview could not be updated. Re-run preview and try again."
)
_GLB_SCHEDULE_CAS_ATTEMPTS = 8


class _GlbPreviewCacheUnavailableError(RuntimeError):
    """Public-safe GLB failure raised when preview-cache artifacts are stale."""


def _cache_state(cache: dict) -> dict:
    if is_preview_cache_artifact_ref(cache):
        metadata = cache.get("metadata")
        return metadata if isinstance(metadata, dict) else {}
    return cache


def _cache_value(cache: dict, key: str) -> object:
    return _cache_state(cache).get(key)


def _cache_publication_guard(cache: dict) -> tuple[tuple[str, ...], object]:
    revision = _cache_value(cache, PREVIEW_CACHE_REVISION_KEY)
    if isinstance(revision, str) and revision:
        path = (
            ("metadata", PREVIEW_CACHE_REVISION_KEY)
            if is_preview_cache_artifact_ref(cache)
            else (PREVIEW_CACHE_REVISION_KEY,)
        )
        return path, revision
    token_path = (
        ("metadata", "glb_job_token")
        if is_preview_cache_artifact_ref(cache)
        else ("glb_job_token",)
    )
    return token_path, _cache_value(cache, "glb_job_token")


def _with_cache_metadata(cache: dict, metadata: dict[str, object]) -> dict:
    if is_preview_cache_artifact_ref(cache):
        return merge_preview_cache_metadata(cache, metadata)
    updated = dict(cache)
    updated.update(metadata)
    updated[PREVIEW_CACHE_REVISION_KEY] = uuid.uuid4().hex
    return updated


def _hydrate_cache_for_glb_worker(cache: dict) -> dict:
    if not is_preview_cache_artifact_ref(cache):
        return cache
    try:
        return hydrate_preview_cache_for_worker(cache)
    except (OSError, ValueError, TypeError, KeyError, EOFError) as exc:
        raise _GlbPreviewCacheUnavailableError(
            _GLB_CACHE_UNAVAILABLE_MESSAGE
        ) from exc


def _glb_status_error_text(exc: Exception) -> str:
    if isinstance(exc, _GlbPreviewCacheUnavailableError):
        return str(exc)
    return _GLB_BUILD_FAILED_MESSAGE


def _cleanup_unregistered_glb(
    path: str | None,
    *,
    session_id: str,
    job_token: str,
    reason: str,
) -> None:
    """Best-effort cleanup for GLB files not adopted by FileRegistry."""

    if not path:
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as exc:
        log.warning(
            "Failed to clean unregistered GLB output",
            extra={
                "event": "converter_glb_unregistered_cleanup_failed",
                "session_id": session_id,
                "job_token": job_token,
                "path": path,
                "reason": reason,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )


def _session_owns_temp_path(
    store: SessionStore,
    session_id: str,
    path: object,
) -> bool:
    if not isinstance(path, str) or not path:
        return False
    try:
        candidate = os.path.realpath(path)
        owned_paths = {
            os.path.realpath(owned_path)
            for owned_path in store.get_temp_file_paths(session_id)
        }
    except (OSError, TypeError):
        return False
    return candidate in owned_paths and os.path.isfile(candidate)


def _vector_backing_rgba(cache: dict) -> tuple[int, int, int, int]:
    preview_colors = cache.get("preview_colors")
    if not isinstance(preview_colors, dict):
        preview_colors = {}
    try:
        backing_index = int(cache.get("backing_color_id", 0) or 0)
    except (TypeError, ValueError):
        backing_index = 0
    slot_names = cache.get("slot_names")
    slot_name = None
    if isinstance(slot_names, (list, tuple)) and 0 <= backing_index < len(slot_names):
        slot_name = slot_names[backing_index]
    for key in ("Board", backing_index, str(backing_index), slot_name):
        if key is None:
            continue
        rgba = coerce_preview_rgba(preview_colors.get(key))
        if rgba is not None:
            return rgba

    color_conf = cache.get("color_conf")
    color_preview = (
        color_conf.get("preview")
        if isinstance(color_conf, dict)
        else None
    )
    if isinstance(color_preview, dict):
        for key in (backing_index, str(backing_index), slot_name):
            rgba = coerce_preview_rgba(color_preview.get(key))
            if rgba is not None:
                return rgba
    return (255, 255, 255, 255)


def _try_build_analytic_vector_glb(
    *,
    session_id: str,
    store: SessionStore,
    cache: dict,
    output_path: str,
) -> str | None:
    artifact_path = cache.get("vector_parse_clip_cache_path")
    provenance = cache.get("vector_parse_clip_cache_provenance")
    if not _session_owns_temp_path(store, session_id, artifact_path):
        return None
    if not isinstance(provenance, str):
        return None
    source = load_vector_quick_preview_source(
        artifact_path,
        expected_provenance=provenance,
    )
    if source is None:
        return None
    # Both file ownership and provenance were checked above. Compare geometry
    # instead of upload paths so a new session can reuse an identical mesh.
    render_inputs = dict(
        matched_rgb=cache.get("matched_rgb"),
        height_identity_rgb=cache.get("height_identity_rgb"),
        mask_solid=cache.get("mask_solid"),
        backing_rgba=_vector_backing_rgba(cache),
        backing_thickness_mm=cache.get("spacer_thick", 1.6),
    )
    key = mesh_input_digest(
        "vector_analytic",
        tuple(item["geometry"] for item in source.clipped_shapes),
        source.silhouette, source.image_vectorizer_bounds, source.bbox, source.scale_factor,
        getattr(source.svg_coordinate_domain, "source_units_per_unit", 1.0),
        render_inputs, cache.get("target_width_mm"),
        PrinterConfig.NOZZLE_WIDTH, PrinterConfig.LAYER_HEIGHT,
    )

    def build() -> str | None:
        parts = build_vector_quick_preview_parts(source=source, **render_inputs)
        if not parts:
            return None
        path = export_vector_quick_preview_glb(parts, output_path=output_path)
        if path:
            cache["color_contours"] = extract_color_contours(
                render_inputs["matched_rgb"], render_inputs["mask_solid"],
                cache.get("target_width_mm"),
            )
        return path

    return _RECENT_MESH.render(key, cache, output_path, build)


def _build_preview_glb(
    *,
    session_id: str,
    store: SessionStore,
    cache: dict,
    output_path: str,
) -> tuple[str | None, str]:
    """Build the selected browser GLB, with safe analytic fallback."""

    cache.pop("_segmented_glb_timings", None)
    cache["_glb_reused"] = False
    modeling_mode = cache.get("modeling_mode")
    modeling_mode_value = getattr(modeling_mode, "value", modeling_mode)
    use_analytic = (
        modeling_mode_value == "vector"
        and bool(cache.get("enable_smooth_vector_preview", True))
    )
    if use_analytic:
        try:
            analytic_path = _try_build_analytic_vector_glb(
                session_id=session_id,
                store=store,
                cache=cache,
                output_path=output_path,
            )
        except _GLB_BUILD_ERRORS as exc:
            log.debug(
                "Analytic Vector GLB unavailable; using segmented fallback",
                extra={
                    "event": "converter_vector_glb_analytic_fallback",
                    "session_id": session_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            analytic_path = None
        if analytic_path:
            return analytic_path, "vector_analytic"

    height_identity = cache.get("height_identity_rgb")
    if height_identity is None:
        height_identity = cache.get("original_matched_rgb")
    material_inputs = None
    if cache.get("material_source") == "material_archive":
        color_conf = cache.get("color_conf")
        if not isinstance(color_conf, dict):
            color_conf = {}
        material_inputs = (
            cache.get("material_matrix"), cache.get("layer_height_mm"),
            cache.get("preview_colors"), cache.get("slot_names"),
            color_conf.get("slots"), color_conf.get("preview"),
        )
    key = mesh_input_digest(
        "segmented", cache.get("matched_rgb"), height_identity, cache.get("mask_solid"),
        cache.get("backing_mask"), cache.get("target_width_mm"), cache.get("glb_max_meshes"),
        material_inputs, PrinterConfig.NOZZLE_WIDTH, PrinterConfig.LAYER_HEIGHT,
        _resolve_kernel_choice(),
    )
    path = _RECENT_MESH.render(
        key, cache, output_path, lambda: generate_segmented_glb(cache, output_path=output_path),
    )
    return path, "segmented"


# Module-level executor shared by every session. ``max_workers=2`` keeps the
# pool small so a single browser tab hammering replace endpoints can't
# starve genuinely concurrent sessions; values larger than the number of
# physical cores offer no extra parallelism because ``generate_segmented_glb``
# is CPU-bound inside Shapely/trimesh.
# 模块级线程池，两并发足以满足单浏览器多次触发的流水线需求；再大也无意义，
# generate_segmented_glb 是 CPU 密集，线程数 > 核数只会抢占。
_GLB_EXECUTOR: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="glb-build"
)


class GlbStatus(TypedDict, total=False):
    """Lightweight snapshot of the async GLB build state for a session."""

    status: str  # "pending" | "ready" | "error" | "idle"
    glb_url: Optional[str]
    job_token: Optional[str]
    error: Optional[str]  # Public-safe error detail for client polling.


def schedule_glb_build(
    session_id: str,
    store: SessionStore,
    registry: FileRegistry,
    cache: dict,
    *,
    metadata_updates: dict[str, object] | None = None,
) -> str:
    """Start a background segmented-GLB rebuild for *session_id*.

    Atomically claims the latest stored cache with a fresh ``glb_job_token``
    (and clears any prior ``glb_url`` / ``glb_error``), so a late scheduler
    can never restore an older edit snapshot. Submits the claimed revision to
    :data:`_GLB_EXECUTOR` and returns its job token for observability.
    为指定 session 触发后台 GLB 重建：原子领取 store 中最新的
    cache revision，写入新 ``glb_job_token`` 并清空旧结果，再提交给
    线程池。晚到的调度请求不会把旧缓存快照写回 session。

    Args:
        session_id (str): SessionStore 中的 session id。
        store (SessionStore): 会话存储，用于 worker 重新读取最新 cache。
        registry (FileRegistry): 文件注册表，用于把生成的 GLB 路径映射为
            ``/api/files/<id>`` URL。
        cache (dict): 调用方刚提交的 preview_cache 快照；若它已过期，
            调度器会改为原子领取 store 中的最新版本。
        metadata_updates: Optional small metadata that must be applied to
            whichever cache revision wins the claim. 需要应用到最终领取
            版本上的可选小型元数据。

    Returns:
        str: 已原子写入最新 session cache 的 job_token。
    """

    candidate_cache = cache
    claimed_metadata = dict(metadata_updates or {})
    job_token: str | None = None
    publication_revision_path: tuple[str, ...] | None = None
    expected_publication_revision: object = None
    for _attempt in range(_GLB_SCHEDULE_CAS_ATTEMPTS):
        revision_path, expected_revision = _cache_publication_guard(
            candidate_cache
        )
        candidate_token = uuid.uuid4().hex
        pending_cache = _with_cache_metadata(
            candidate_cache,
            {
                **claimed_metadata,
                "glb_job_token": candidate_token,
                # Clear any previous outcome so the status endpoint reports
                # "pending" until this new job completes.
                # 清空旧结果让状态查询立即返回 pending。
                "glb_url": None,
                "glb_error": None,
                "glb_started_at": time.time(),
            },
        )
        claimed = store.compare_and_set(
            session_id,
            "preview_cache",
            pending_cache,
            revision_path=revision_path,
            expected_revision=expected_revision,
        )
        if claimed:
            job_token = candidate_token
            publication_revision_path, expected_publication_revision = (
                _cache_publication_guard(pending_cache)
            )
            break
        session_data = store.get(session_id)
        latest_cache = session_data.get("preview_cache") if session_data else None
        if not isinstance(latest_cache, dict):
            raise _GlbPreviewCacheUnavailableError(
                _GLB_CACHE_UNAVAILABLE_MESSAGE
            )
        candidate_cache = latest_cache
    if job_token is None:
        raise RuntimeError(
            "Preview cache changed repeatedly while scheduling the 3D preview."
        )

    scheduled_perf_counter = time.perf_counter()
    submit_succeeded = True
    try:
        _GLB_EXECUTOR.submit(
            _run_glb_build_job,
            session_id,
            job_token,
            store,
            registry,
            scheduled_perf_counter,
        )
    except Exception as exc:
        submit_succeeded = False
        # The 2D content transaction is already committed at this point. A
        # scheduler/executor failure is therefore a derived-preview failure,
        # not a reason to make the edit look uncommitted or ask the frontend
        # to roll its mapping back. Publish an error through the same token /
        # revision CAS so a newer edit cannot be overwritten.
        # 这里 2D 内容事务已经提交；调度器/线程池失败只影响派生预览，不能
        # 伪装成编辑未提交，也不能让前端回滚映射。沿用 token/revision CAS
        # 发布错误，避免覆盖更新的编辑。
        log.warning(
            "GLB build could not be scheduled",
            extra={
                "event": "converter_glb_schedule_failed",
                "session_id": session_id,
                "job_token": job_token,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        latest_session = store.get(session_id)
        latest_cache = (
            latest_session.get("preview_cache")
            if latest_session is not None
            else None
        )
        if (
            isinstance(latest_cache, dict)
            and _cache_value(latest_cache, "glb_job_token") == job_token
            and _cache_publication_guard(latest_cache)
            == (publication_revision_path, expected_publication_revision)
        ):
            failed_cache = _with_cache_metadata(
                latest_cache,
                {
                    "glb_url": None,
                    "glb_error": _glb_status_error_text(exc),
                    "glb_completed_at": time.time(),
                },
            )
            store.compare_and_set(
                session_id,
                "preview_cache",
                failed_cache,
                revision_path=publication_revision_path,
                expected_revision=expected_publication_revision,
            )
    if submit_succeeded:
        log.debug(
            "GLB build scheduled",
            extra={
                "event": "converter_glb_scheduled",
                "session_id": session_id,
                "job_token": job_token,
            },
        )
    return job_token


def _run_glb_build_job(
    session_id: str,
    job_token: str,
    store: SessionStore,
    registry: FileRegistry,
    scheduled_perf_counter: float | None = None,
) -> None:
    """Worker body: regenerate the segmented GLB and write it back to cache.

    Re-reads the claimed ``preview_cache`` on entry and captures both its
    token and immutable cache revision before hydration/build. Any edit,
    reschedule, close, or restore changes that revision, so stale results are
    discarded before registration or by the final atomic publication.
    Worker 主体：入口同时捕获 job token 与不可复用的 cache revision。
    编辑、重调度、关闭或历史恢复任一发生后，旧结果都无法注册或写回。
    """

    t_start = time.perf_counter()
    queue_wait_ms = (
        max(0.0, (t_start - scheduled_perf_counter) * 1000.0)
        if scheduled_perf_counter is not None
        else 0.0
    )
    glb_path: str | None = None
    registered_glb_id: str | None = None
    registered_glb_adopted = False
    publication_revision_path: tuple[str, ...] | None = None
    expected_publication_revision: object = None
    try:
        session_data = store.get(session_id)
        if session_data is None:
            log.debug(
                "GLB build aborted: session vanished",
                extra={
                    "event": "converter_glb_aborted_no_session",
                    "session_id": session_id,
                    "job_token": job_token,
                },
            )
            return
        latest_cache = session_data.get("preview_cache")
        if latest_cache is None:
            log.debug(
                "GLB build aborted: preview cache cleared",
                extra={
                    "event": "converter_glb_aborted_no_cache",
                    "session_id": session_id,
                    "job_token": job_token,
                },
            )
            return
        if _cache_value(latest_cache, "glb_job_token") != job_token:
            log.debug(
                "GLB build aborted: superseded by newer job",
                extra={
                    "event": "converter_glb_aborted_superseded",
                    "session_id": session_id,
                    "job_token": job_token,
                    "current_job_token": _cache_value(latest_cache, "glb_job_token"),
                },
            )
            return
        (
            publication_revision_path,
            expected_publication_revision,
        ) = _cache_publication_guard(latest_cache)

        target_path = os.path.join(
            OUTPUT_DIR,
            generate_segmented_glb_filename(session_id),
        )
        build_cache = _hydrate_cache_for_glb_worker(latest_cache)
        glb_path, selected_renderer = _build_preview_glb(
            session_id=session_id,
            store=store,
            cache=build_cache,
            output_path=target_path,
        )

        # Re-check the token post-build: another replace might have landed
        # while the heavy Shapely/trimesh work was running. Honour the
        # newer job by leaving its cleared ``glb_url = None`` untouched.
        # 任务完成后再次确认 token，若期间被新任务覆盖则放弃写回，以免把
        # 陈旧 GLB 错误地当成"最新"推送给前端。
        session_data = store.get(session_id)
        latest_cache = session_data.get("preview_cache") if session_data else None
        if latest_cache is None:
            return
        if (
            _cache_value(latest_cache, "glb_job_token") != job_token
            or _cache_publication_guard(latest_cache)
            != (publication_revision_path, expected_publication_revision)
        ):
            log.debug(
                "GLB build result discarded: superseded after completion",
                extra={
                    "event": "converter_glb_discarded_after_build",
                    "session_id": session_id,
                    "job_token": job_token,
                    "current_job_token": _cache_value(latest_cache, "glb_job_token"),
                },
            )
            return

        cache_updates: dict[str, object] = {}
        if glb_path and os.path.exists(glb_path):
            registered_glb_id = registry.register_path(session_id, glb_path)
            registered_session = store.get(session_id)
            registered_cache = (
                registered_session.get("preview_cache")
                if registered_session is not None
                else None
            )
            current_token = (
                _cache_value(registered_cache, "glb_job_token")
                if isinstance(registered_cache, dict)
                else None
            )
            if (
                registered_cache is None
                or current_token != job_token
                or _cache_publication_guard(registered_cache)
                != (publication_revision_path, expected_publication_revision)
            ):
                log.debug(
                    "GLB registration discarded after ownership changed",
                    extra={
                        "event": "converter_glb_discarded_after_registration",
                        "session_id": session_id,
                        "job_token": job_token,
                        "current_job_token": current_token,
                        "reason": (
                            "session_missing"
                            if registered_cache is None
                            else "superseded"
                        ),
                    },
                )
                return
            latest_cache = registered_cache
            cache_updates["glb_url"] = f"/api/files/{registered_glb_id}"
            cache_updates["glb_error"] = None
            cache_updates["glb_renderer"] = selected_renderer
            # color_contours is populated as a side effect of
            # generate_segmented_glb; re-expose it here so follow-up calls
            # can pick up contour highlights without another round-trip.
            # generate_segmented_glb 会在 cache["color_contours"] 写入轮廓；
            # 这里无需额外动作即可被后续流程读取。
            if "color_contours" in build_cache:
                cache_updates["color_contours"] = build_cache["color_contours"]
        else:
            cache_updates["glb_url"] = None
            cache_updates["glb_error"] = _GLB_BUILD_FAILED_MESSAGE
            log.warning(
                "GLB build produced no output path",
                extra={
                    "event": "converter_glb_no_output",
                    "session_id": session_id,
                    "job_token": job_token,
                    "error_type": "missing_output",
                    "error_message": "generate_segmented_glb returned no path",
                },
            )

        cache_updates["glb_completed_at"] = time.time()
        completed_cache = _with_cache_metadata(latest_cache, cache_updates)
        if publication_revision_path is None:
            return
        published = store.compare_and_set(
            session_id,
            "preview_cache",
            completed_cache,
            revision_path=publication_revision_path,
            expected_revision=expected_publication_revision,
        )
        if not published:
            log.debug(
                "GLB result discarded during atomic publication",
                extra={
                    "event": "converter_glb_discarded_during_publish",
                    "session_id": session_id,
                    "job_token": job_token,
                    "reason": "session_or_revision_changed",
                },
            )
            return
        registered_glb_adopted = True
        completed_at = time.perf_counter()
        execution_ms = max(0.0, (completed_at - t_start) * 1000.0)
        segmented_glb_timings = {}
        raw_segmented_timings = build_cache.get("_segmented_glb_timings")
        if isinstance(raw_segmented_timings, dict):
            for timing_name in (
                "downsample_s",
                "unique_s",
                "merge_s",
                "mask_build_s",
                "mesh_loop_s",
                "backing_s",
                "canvas_bounds_s",
                "export_s",
                "total_s",
            ):
                try:
                    timing_value = float(raw_segmented_timings.get(timing_name))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(timing_value) and timing_value >= 0.0:
                    segmented_glb_timings[timing_name] = round(timing_value, 6)
        log.info(
            "GLB build completed",
            extra={
                "event": "converter_glb_completed",
                "session_id": session_id,
                "job_token": job_token,
                "duration_ms": round(execution_ms, 1),
                "queue_wait_ms": round(queue_wait_ms, 3),
                "execution_ms": round(execution_ms, 3),
                "segmented_glb_timings": segmented_glb_timings,
                "renderer": selected_renderer,
                "mesh_reused": build_cache.get("_glb_reused", False),
                "glb_url_set": cache_updates.get("glb_url") is not None,
            },
        )
    except _GLB_BUILD_ERRORS as exc:
        # Record the error so the status endpoint can surface it and the
        # frontend can stop polling. Do NOT re-raise — this is a detached
        # worker thread; propagation would only log at the ThreadPoolExecutor.
        # 记录到 cache 让前端 polling 得到 error 态并停止轮询；不重抛以免
        # 线程池打印无法关联的 Traceback。
        log.warning(
            "GLB build failed",
            extra={
                "event": "converter_glb_build_failed",
                "session_id": session_id,
                "job_token": job_token,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        session_data = store.get(session_id)
        latest_cache = session_data.get("preview_cache") if session_data else None
        if latest_cache is None:
            return
        if (
            publication_revision_path is None
            or _cache_value(latest_cache, "glb_job_token") != job_token
            or _cache_publication_guard(latest_cache)
            != (publication_revision_path, expected_publication_revision)
        ):
            return
        failed_cache = _with_cache_metadata(
            latest_cache,
            {
                "glb_url": None,
                "glb_error": _glb_status_error_text(exc),
                "glb_completed_at": time.time(),
            },
        )
        store.compare_and_set(
            session_id,
            "preview_cache",
            failed_cache,
            revision_path=publication_revision_path,
            expected_revision=expected_publication_revision,
        )
    finally:
        if registered_glb_id is not None and not registered_glb_adopted:
            registry.cleanup_file(registered_glb_id)
        elif glb_path is not None and not registered_glb_adopted:
            _cleanup_unregistered_glb(
                glb_path,
                session_id=session_id,
                job_token=job_token,
                reason="preview_not_published",
            )


def get_glb_status(cache: dict) -> GlbStatus:
    """Translate a session's cache into the public GLB build status.

    Precedence / 状态优先级:
        - ``ready``   : ``cache['glb_url']`` is a non-empty string.
        - ``error``   : ``cache['glb_error']`` is set (and URL is not set).
        - ``pending`` : a ``glb_job_token`` exists but no URL/error yet.
        - ``idle``    : no job has ever been scheduled for this cache.
    """

    state = _cache_state(cache)
    token = state.get("glb_job_token")
    url = state.get("glb_url")
    err = state.get("glb_error")
    if isinstance(url, str) and url:
        return {"status": "ready", "glb_url": url, "job_token": token, "error": None}
    if isinstance(err, str) and err:
        return {"status": "error", "glb_url": None, "job_token": token, "error": err}
    if isinstance(token, str) and token:
        return {"status": "pending", "glb_url": None, "job_token": token, "error": None}
    return {"status": "idle", "glb_url": None, "job_token": None, "error": None}
