"""Self-driven log quality checks for Lumina Studio workflows.

Runs a small API workflow, audits the captured structured log file, and
emits human-readable plus machine-readable log reports.

Ad-hoc workflow steps (not in the default canonical workflow):
  - replace_bw / replace_8color / replace_5color_ext: per-mode replace regression.
  - batch_merge_3mf: batch merge 3MF regression. Triggers a minimal N=2 batch
    request that exercises batch_merge_3mf_init + batch_merge_3mf_done (and
    batch_merge_plate_overflow_warning when layout exceeds plate bounds).
    Invoke via: --workflow batch_merge_3mf
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from collections import Counter
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_logs import audit_files, event_from_line, parse_json_object

Mode = Literal["fast", "full"]

DEFAULT_WORKFLOW = [
    "startup",
    "lut_list",
    "lut_colors",
    "preview",
    "generate",
    "replace",
    "extract_single_stage",
    "extract",
    "merge_8color",
    "merge_5color_ext",
]
WORKFLOW_ORDER = [
    "startup",
    "lut_list",
    "lut_colors",
    "preview",
    "generate",
    "vector",
    "replace",
    "replace_bw",
    "replace_8color",
    "replace_5color_ext",
    "replace_color",
    "reset_replacements",
    "source_color_pick",
    "color_highlight",
    "region_detect",
    "region_requantize",
    "replace_colors_batch",
    "region_replace_batch",
    "predict_recipe",
    "apply_recipe_override",
    "region_recipe",
    "merge_colors",
    "generate_large_format",
    "batch",
    "batch_merge_3mf",
    "puzzle_layout_preview",
    "generate_puzzle",
    "auto_detect_colors",
    "cleanup_session_files",
    "extract_single_stage",
    "fit_stage_a",
    "extract_gradient_card_stage_a",
    "save_gradient_card_material",
    "delete_gradient_card_material",
    "update_gradient_card_material",
    "export_gradient_card_materials",
    "import_gradient_card_materials",
    "material_solver_cache_status",
    "material_solver_cache_build",
    "material_solver_cache_delete",
    "material_solver_cache_suggest_colors",
    "calibration_generate",
    "calibration_generate_single_stage_kit",
    "five_color_query",
    "five_color_generate_swatch",
    "five_color_base_colors",
    "vectorize_image",
    "lut_merge",
    "lut_compare",
    "lut_details",
    "lut_upload",
    "lut_session_info",
    "system_image_preview",
    "system_save_settings",
    "slicer_launch",
    "feedback_submit",
    "extract",
    "merge_8color",
    "merge_5color_ext",
    "manual_fix",
    "preview_wb",
    "rotate",
    "confirm_palette",
]
WORKFLOW_STEPS = set(WORKFLOW_ORDER)
DEFAULT_PORT = 18000
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_SERVER_START_TIMEOUT_SECONDS = 30.0
DEFAULT_LUT_STEM = "Aliz&PLA&4色RYBW&20260211"
DEFAULT_LUT_NAME = f"Aliz - PLA - 4色 - {DEFAULT_LUT_STEM}"
DEFAULT_COLOR_MODE = "4-Color (RYBW)"
BW_COLOR_MODE = "BW (Black & White)"
BW_LUT_STEM = "Bambulab&PLA&BW&白-黑"
BW_LUT_NAME = f"Custom - {BW_LUT_STEM}"
EIGHT_COLOR_MODE = "8-Color Max"
EIGHT_COLOR_LUT_STEM = "Aliz&8色PLA"
EIGHT_COLOR_LUT_NAME = f"Aliz - PLA - {EIGHT_COLOR_LUT_STEM}"
FIVE_COLOR_EXT_MODE = "5-Color Extended"
FIVE_COLOR_EXT_LUT_STEM = "Aliz&PETG&5color&红-黄-蓝-白-黑-20260304"
FIVE_COLOR_EXT_LUT_NAME = f"Aliz - PETG - 5色 - {FIVE_COLOR_EXT_LUT_STEM}"
DEFAULT_MODELING_MODE = "high-fidelity"
VECTOR_MODELING_MODE = "vector"
FIXTURE_IMAGE = REPO_ROOT / "tests" / "fixtures" / "frozen_assets" / "images" / "logo.png"
VECTOR_FIXTURE_IMAGE = REPO_ROOT / "tests" / "fixtures" / "svg_alignment" / "ring_with_hole.svg"
REPLACE_COLOR_CANDIDATES = ("#ff0000", "#ffff00", "#ffffff", "#0000ff")
REPLACE_FAMILY_STEPS = frozenset(
    {"replace", "replace_bw", "replace_8color", "replace_5color_ext"}
)
ALTERNATE_REPLACE_CONFIG = {
    "replace_bw": (BW_COLOR_MODE, BW_LUT_NAME),
    "replace_8color": (EIGHT_COLOR_MODE, EIGHT_COLOR_LUT_NAME),
    "replace_5color_ext": (FIVE_COLOR_EXT_MODE, FIVE_COLOR_EXT_LUT_NAME),
}
MOCK_COLOR_CONFIGS = {
    DEFAULT_COLOR_MODE: (
        ["White", "Red", "Yellow", "Blue"],
        [(255, 255, 255), (255, 0, 0), (255, 255, 0), (0, 128, 255)],
    ),
    BW_COLOR_MODE: (["White", "Black"], [(255, 255, 255), (0, 0, 0)]),
    EIGHT_COLOR_MODE: (
        ["White", "Red", "Yellow", "Blue", "Magenta", "Cyan", "Green", "Black"],
        [
            (255, 255, 255),
            (255, 0, 0),
            (255, 255, 0),
            (0, 128, 255),
            (255, 0, 255),
            (0, 255, 255),
            (0, 255, 0),
            (0, 0, 0),
        ],
    ),
    FIVE_COLOR_EXT_MODE: (
        ["White", "Red", "Yellow", "Blue", "Black"],
        [(255, 255, 255), (255, 0, 0), (255, 255, 0), (0, 128, 255), (0, 0, 0)],
    ),
}

_CATCH_ALL_PATTERN = re.compile(r"^(.*_log|status_.*|request_.*)$")
_ALLOWED_LOG_EVENTS = {"client_log", "log_file_configured"}
_ANSI_PATTERN = re.compile(r"(?:\x1b|\\u001b)\[")
_BRACKET_TAG_PATTERN = re.compile(r"^\s*\[[A-Z][A-Z0-9_]*\]")
_WARNING_ERROR_ACTIONABLE_FIELDS = frozenset(
    {
        "dependency",
        "error_code",
        "error_message",
        "error_type",
        "exception",
        "fallback_action",
        "path",
        "status_code",
    }
)


class QualityCheckError(RuntimeError):
    """Raised when the check cannot run to completion.

    当脚本自身无法完成检查时抛出，例如服务启动失败、fixture 缺失或请求失败。
    """


@dataclass(frozen=True)
class CheckResult:
    """One log or workflow check result.
    单个日志或工作流检查结果。
    """

    name: str
    passed: bool
    actual: int | float
    operator: str
    threshold: int | float
    severity: str = "error"

    @classmethod
    def evaluate(
        cls,
        *,
        name: str,
        actual: int | float,
        operator: str,
        threshold: int | float,
        severity: str = "error",
    ) -> "CheckResult":
        """Evaluate a numeric threshold.

        Args:
            name: Check name. 检查名称。
            actual: Observed value. 实测值。
            operator: ``<=`` or ``==``. 运算符。
            threshold: Expected threshold. 期望阈值。
            severity: Failure severity label. 失败级别。

        Returns:
            CheckResult: Evaluated result. 已评估结果。
        """

        if operator == "<=":
            passed = actual <= threshold
        elif operator == ">=":
            passed = actual >= threshold
        elif operator == "==":
            passed = actual == threshold
        else:
            raise ValueError(f"Unsupported check operator: {operator}")
        return cls(
            name=name,
            passed=passed,
            actual=actual,
            operator=operator,
            threshold=threshold,
            severity=severity,
        )


@dataclass(frozen=True)
class QualityReport:
    """Complete log quality report.
    完整日志质量报表。
    """

    mode: Mode
    workflow: list[str]
    timestamp: str
    log_path: str
    total_lines: int
    structured_lines: int
    unstructured_lines: int
    duplicate_event_count: int
    request_completed_count: int
    event_counts: dict[str, int]
    top_events: list[dict[str, Any]]
    total_bytes: int
    info_lines: int
    warning_lines: int
    error_lines: int
    warning_error_missing_actionable_fields: int
    catch_all_event_count: int
    ansi_field_count: int
    bracket_tag_message_count: int
    log_file_configured_count: int
    max_info_per_endpoint: int
    info_lines_by_endpoint: dict[str, int]
    checks: list[CheckResult]
    workflow_checks: list[CheckResult]
    overall_passed: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        Returns:
            dict[str, Any]: Report dictionary. 报表字典。
        """

        return asdict(self)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Optional argument vector. 可选参数列表。

    Returns:
        argparse.Namespace: Parsed arguments. 解析后的参数。
    """

    parser = argparse.ArgumentParser(
        description="Run Lumina Studio log quality checks.",
    )
    parser.add_argument("--mode", choices=("fast", "full"), required=True)
    parser.add_argument(
        "--workflow",
        default=",".join(DEFAULT_WORKFLOW),
        help="Comma-separated workflow steps.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON report to this path.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port used by full mode.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP request timeout for full mode.",
    )
    return parser.parse_args(argv)


def _build_fast_mode_app():
    """Build the in-process app used by the fast log gate.
    构建快速日志质量门使用的进程内应用。
    """
    from api.app import create_app
    from api.routers import (
        calibration_router,
        extractor_router,
        five_color_router,
        single_stage_router,
    )

    app = create_app()
    app.include_router(extractor_router)
    app.include_router(single_stage_router)
    app.include_router(calibration_router)
    app.include_router(five_color_router)
    return app


def run_fast_mode(temp_log_path: Path, workflow: list[str]) -> dict[str, Any]:
    """Run the workflow through FastAPI TestClient with mocked workers.

    Args:
        temp_log_path: Structured log path. 结构化日志路径。
        workflow: Workflow steps. 业务流步骤。

    Returns:
        dict[str, Any]: Raw audit result. 原始审计结果。
    """

    _prepare_log_environment(temp_log_path)
    if "feedback_submit" in workflow:
        _disable_feedback_upload_env(os.environ)

    import io
    import numpy as np
    from contextlib import ExitStack, redirect_stdout
    from fastapi.testclient import TestClient
    from PIL import Image
    from unittest.mock import AsyncMock, MagicMock, patch

    console_capture = io.StringIO()
    with redirect_stdout(console_capture):
        import api.app as api_app_module
        from api.dependencies import get_file_registry, get_session_store, get_worker_pool
        from api.file_registry import FileRegistry
        from api.session_store import SessionStore
        from api.worker_pool import WorkerPoolManager

        app = _build_fast_mode_app()
        created_paths: list[Path] = []
        test_store = SessionStore(ttl=1800)
        test_registry = FileRegistry()
        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.max_workers = 1
        mock_pool.is_alive = True

        def build_mock_submission_result(
            worker_fn: Callable[..., Any],
            *args: Any,
            **submission_options: Any,
        ) -> dict[str, Any]:
            """Mirror pool metadata kwargs without forwarding them to workers."""

            unexpected = set(submission_options)
            if unexpected:
                names = ", ".join(sorted(unexpected))
                raise QualityCheckError(
                    f"Unexpected fast-mode worker submission options: {names}"
                )
            return _build_mock_worker_result(
                worker_fn,
                created_paths,
                np,
                Image,
                *args,
            )

        mock_pool.submit = AsyncMock(
            side_effect=build_mock_submission_result
        )
        mock_pool.submit_timed = AsyncMock(
            side_effect=lambda worker_fn, *args, **kwargs: (
                build_mock_submission_result(worker_fn, *args, **kwargs),
                {
                    "queue_wait_s": 0.0,
                    "worker_execution_s": 0.001,
                    "result_delivery_s": 0.0,
                    "pool_roundtrip_s": 0.001,
                },
            )
        )

        original_lifespan_pool = api_app_module.worker_pool
        app.dependency_overrides[get_session_store] = lambda: test_store
        app.dependency_overrides[get_file_registry] = lambda: test_registry
        app.dependency_overrides[get_worker_pool] = lambda: mock_pool
        api_app_module.worker_pool = mock_pool

        try:
            extract_lut_path = _make_temp_path(".json", created_paths)
            _synthesize_lut_keyed_json(
                extract_lut_path,
                rgb=np.array(
                    [
                        [255, 255, 255],
                        [255, 0, 0],
                        [255, 255, 0],
                        [0, 128, 255],
                    ],
                    dtype=np.uint8,
                ),
                stacks=np.zeros((4, 0), dtype=np.int32),
                color_mode=DEFAULT_COLOR_MODE,
            )
            extract_image = np.zeros((8, 8, 3), dtype=np.uint8)
            patch_contexts = [
                patch("api.routers.converter.preview.generate_segmented_glb", return_value=None),
                patch(
                    "api.routers.converter.preview.recompute_gradient_groups_into_session",
                    return_value=None,
                ),
                patch(
                    "api.routers.converter.replace.schedule_glb_build",
                    return_value="mock-glb-token",
                ),
                patch(
                    "api.routers.converter.replace.load_multiple_materials",
                    return_value=[],
                ),
                patch(
                    "api.routers.converter.replace.load_material_solver_cache_with_fallback",
                    return_value=(object(), 64),
                ),
                patch(
                    "api.routers.converter.replace.requantize_gradient_regions",
                    side_effect=_mock_requantize_gradient_regions,
                ),
                patch(
                    "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
                ),
                patch(
                    "api.routers.converter.replace.recompute_gradient_groups_into_session",
                    return_value=[],
                ),
                patch(
                    "api.routers.extractor.run_extraction",
                    return_value=(
                        extract_image,
                        extract_image,
                        str(extract_lut_path),
                        "OK",
                    ),
                ),
                patch(
                    "api.routers.single_stage.extract_single_stage_dataset",
                    side_effect=lambda *args, **kwargs: _mock_extract_single_stage_dataset(
                        created_paths,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.single_stage.fit_stage_a_from_stage_json",
                    side_effect=lambda *args, **kwargs: _mock_fit_stage_a_from_stage_json(
                        created_paths,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.single_stage.extract_stage_a_material_from_gradient_cards",
                    side_effect=lambda *args, **kwargs: _mock_extract_gradient_card_stage_a(
                        created_paths,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.single_stage.save_stage_a_material_archive",
                    side_effect=lambda *args, **kwargs: _mock_save_gradient_card_material(
                        created_paths,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.single_stage.delete_saved_stage_a_material_archive",
                    side_effect=_mock_delete_gradient_card_material,
                ),
                patch(
                    "api.routers.single_stage.update_saved_stage_a_material_archive_metadata",
                    side_effect=lambda *args, **kwargs: _mock_update_gradient_card_material(
                        created_paths,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.single_stage.export_saved_stage_a_material_archives",
                    side_effect=lambda *args, **kwargs: _mock_export_gradient_card_materials(
                        created_paths,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.single_stage.import_saved_stage_a_material_archives",
                    side_effect=lambda *args, **kwargs: _mock_import_gradient_card_materials(
                        created_paths,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.single_stage.load_material_solver_cache",
                    side_effect=_mock_load_material_solver_cache,
                ),
                patch(
                    "api.routers.single_stage.build_material_solver_cache",
                    side_effect=_mock_build_material_solver_cache,
                ),
                patch(
                    "api.routers.single_stage.save_material_solver_cache",
                    side_effect=lambda *args, **kwargs: _mock_save_material_solver_cache(
                        created_paths,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.single_stage.delete_cached_entry",
                    side_effect=_mock_delete_cached_entry,
                ),
                patch(
                    "api.routers.single_stage.suggest_colors_for_target",
                    side_effect=_mock_suggest_colors_for_target,
                ),
                patch(
                    "api.routers.single_stage.load_multiple_materials",
                    side_effect=_mock_load_multiple_materials,
                ),
                patch(
                    "api.routers.single_stage._palette_cache_identity",
                    side_effect=_mock_palette_cache_identity,
                ),
                patch(
                    "api.routers.single_stage.cache_file_path",
                    side_effect=lambda *args, **kwargs: _mock_cache_file_path(
                        created_paths,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.converter.puzzle.assemble_puzzle_3mf",
                    side_effect=_mock_assemble_puzzle_3mf,
                ),
                # Fast workers emit sentinel bytes; metadata reads belong to
                # the real package integration checks, not this logging gate.
                patch(
                    "api.routers.converter.puzzle._batch_extract_slots_from_3mf",
                    return_value=[{
                        "slot_id": 0, "slot_name": "White",
                        "preview_color": "#ffffff", "material_id": "PLA",
                    }],
                ),
                patch(
                    "api.routers.converter.puzzle.read_wipe_tower_placement_warnings",
                    return_value=[],
                ),
                patch(
                    "api.routers.calibration.generate_calibration_board",
                    side_effect=lambda *args, **kwargs: _mock_calibration_board(
                        created_paths,
                        Image,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.calibration.generate_single_stage_kit",
                    side_effect=lambda *args, **kwargs: _mock_single_stage_kit(
                        created_paths,
                        Image,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.five_color._load_engine",
                    side_effect=_mock_load_five_color_engine,
                ),
                patch(
                    "core.recipe_swatch.generate_recipe_swatch",
                    side_effect=lambda *args, **kwargs: _mock_generate_recipe_swatch(
                        created_paths,
                        Image,
                        *args,
                        **kwargs,
                    ),
                ),
                patch(
                    "api.routers.converter.generate.MergedBambu3MFWriter",
                    side_effect=lambda: _MockMergedBambu3MFWriter(created_paths),
                ),
            ]
            with ExitStack() as stack:
                for patch_context in patch_contexts:
                    stack.enter_context(patch_context)
                with TestClient(app, base_url="http://localhost:8000") as client:
                    _execute_workflow(client, workflow)
            _flush_lumina_handlers()
        finally:
            app.dependency_overrides.clear()
            api_app_module.worker_pool = original_lifespan_pool
            test_store.clear_all()
            _remove_paths(created_paths)
            _flush_lumina_handlers()

    return audit_files([temp_log_path], label="fast")


def run_full_mode(
    temp_log_path: Path,
    workflow: list[str],
    *,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Spawn a real uvicorn server and run the workflow through HTTP.

    Args:
        temp_log_path: Structured log path. 结构化日志路径。
        workflow: Workflow steps. 业务流步骤。
        port: Non-default uvicorn port. uvicorn 非默认端口。
        timeout: HTTP timeout seconds. HTTP 超时秒数。

    Returns:
        dict[str, Any]: Raw audit result. 原始审计结果。
    """

    env = os.environ.copy()
    env["LUMINA_LOG_PATH"] = str(temp_log_path)
    env["LUMINA_LOG_LEVEL"] = "INFO"
    env["LUMINA_LOG_FORMAT"] = "json"
    env.pop("LUMINA_LOG_INIT_BY_PARENT", None)
    if "feedback_submit" in workflow:
        _disable_feedback_upload_env(env)
    support_paths = (
        _ensure_single_stage_colorchecker_assets()
        if any(step in workflow for step in ("extract_single_stage", "fit_stage_a"))
        else []
    )

    creationflags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if os.name == "nt"
        else 0
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_server(base_url, DEFAULT_SERVER_START_TIMEOUT_SECONDS, proc)
        _execute_http_workflow(base_url, workflow, timeout)
    finally:
        _terminate_server_process(proc)
        time.sleep(1.0)
        _remove_single_stage_colorchecker_assets(support_paths)

    if not temp_log_path.exists():
        raise QualityCheckError(f"Log file was not created: {temp_log_path}")
    return audit_files([temp_log_path], label="full")


def build_quality_report(
    *,
    mode: Mode,
    workflow: list[str],
    log_path: Path,
    audit_result: Mapping[str, Any],
) -> QualityReport:
    """Combine captured logs with format, diagnostic, and workflow checks.

    Args:
        mode: Execution mode. 执行模式。
        workflow: Workflow steps. 业务流步骤。
        log_path: Captured log path. 捕获日志路径。
        audit_result: Raw ``audit_files`` result. 原始审计结果。

    Returns:
        QualityReport: Scored report. 评分报表。
    """

    metrics = _scan_log_metrics(log_path)
    info_by_endpoint = _count_info_lines_by_request_id(log_path)
    max_endpoint_info = max(info_by_endpoint.values(), default=0)
    event_counts = {
        str(key): int(value)
        for key, value in dict(audit_result.get("event_counts", {})).items()
    }
    checks = [
        CheckResult.evaluate(
            name="no_request_completed_catchall",
            actual=int(audit_result.get("request_completed_count", 0)),
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="no_unstructured_lines",
            actual=int(audit_result.get("unstructured_lines", 0)),
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="no_catch_all_events",
            actual=metrics["catch_all_event_count"],
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="no_ansi_escape",
            actual=metrics["ansi_field_count"],
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="no_bracket_tag_message",
            actual=metrics["bracket_tag_message_count"],
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="no_warning_error_missing_actionable_fields",
            actual=metrics["warning_error_missing_actionable_fields"],
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="log_file_configured_once",
            actual=metrics["log_file_configured_count"],
            operator="==",
            threshold=1,
        ),
    ]
    workflow_checks = _workflow_required_event_checks(
        mode=mode,
        workflow=workflow,
        event_counts=event_counts,
    )
    report = QualityReport(
        mode=mode,
        workflow=workflow,
        timestamp=datetime.now(timezone.utc).isoformat(),
        log_path=str(log_path),
        total_lines=int(audit_result.get("total_lines", 0)),
        structured_lines=int(audit_result.get("structured_lines", 0)),
        unstructured_lines=int(audit_result.get("unstructured_lines", 0)),
        duplicate_event_count=int(audit_result.get("duplicate_event_count", 0)),
        request_completed_count=int(audit_result.get("request_completed_count", 0)),
        event_counts=event_counts,
        top_events=list(audit_result.get("top_events", [])),
        total_bytes=int(audit_result.get("total_bytes", 0)),
        info_lines=metrics["info_lines"],
        warning_lines=metrics["warning_lines"],
        error_lines=metrics["error_lines"],
        warning_error_missing_actionable_fields=metrics[
            "warning_error_missing_actionable_fields"
        ],
        catch_all_event_count=metrics["catch_all_event_count"],
        ansi_field_count=metrics["ansi_field_count"],
        bracket_tag_message_count=metrics["bracket_tag_message_count"],
        log_file_configured_count=metrics["log_file_configured_count"],
        max_info_per_endpoint=max_endpoint_info,
        info_lines_by_endpoint=info_by_endpoint,
        checks=checks,
        workflow_checks=workflow_checks,
        overall_passed=all(check.passed for check in checks)
        and all(check.passed for check in workflow_checks),

    )
    return report


def _workflow_required_event_checks(
    *,
    mode: Mode,
    workflow: Sequence[str],
    event_counts: Mapping[str, int],
) -> list[CheckResult]:
    required_events: list[str] = []
    if any(step in workflow for step in REPLACE_FAMILY_STEPS):
        required_events.extend(_replace_required_events_for_mode(mode))
    if "extract_single_stage" in workflow:
        required_events.append("extractor_extract_single_stage_done")
    if "fit_stage_a" in workflow:
        required_events.append("extractor_fit_stage_a_done")
    if "extract_gradient_card_stage_a" in workflow:
        required_events.append("extractor_extract_gradient_card_stage_a_done")
    if "save_gradient_card_material" in workflow:
        required_events.append("extractor_save_gradient_card_material_done")
    if "delete_gradient_card_material" in workflow:
        required_events.append("extractor_delete_gradient_card_material_done")
    if "update_gradient_card_material" in workflow:
        required_events.append("extractor_update_gradient_card_material_done")
    if "export_gradient_card_materials" in workflow:
        required_events.append("extractor_export_gradient_card_materials_done")
    if "import_gradient_card_materials" in workflow:
        required_events.append("extractor_import_gradient_card_materials_done")
    if "material_solver_cache_status" in workflow:
        required_events.append("material_solver_cache_status_done")
    if "material_solver_cache_build" in workflow:
        required_events.append("material_solver_cache_build_done")
    if "material_solver_cache_delete" in workflow:
        required_events.append("material_solver_cache_delete_done")
    if "material_solver_cache_suggest_colors" in workflow:
        required_events.append("material_solver_cache_suggest_colors_done")
    if "calibration_generate" in workflow:
        required_events.append("calibration_generate_done")
    if "calibration_generate_single_stage_kit" in workflow:
        required_events.append("calibration_generate_single_stage_kit_done")
    if "five_color_query" in workflow:
        required_events.append("five_color_query_done")
    if "five_color_generate_swatch" in workflow:
        required_events.append("five_color_generate_swatch_done")
    if "five_color_base_colors" in workflow:
        required_events.append("five_color_base_colors_done")
    if "vectorize_image" in workflow:
        required_events.append("vectorize_image_done")
    if "lut_merge" in workflow:
        required_events.append("lut_merge_done")
    if "lut_compare" in workflow:
        required_events.append("lut_compare_done")
    if "lut_details" in workflow:
        required_events.append("lut_details_done")
    if "lut_upload" in workflow:
        required_events.append("lut_upload_done")
    if "lut_session_info" in workflow:
        required_events.append("lut_session_info_done")
    if "system_image_preview" in workflow:
        required_events.append("system_image_preview_done")
    if "system_save_settings" in workflow:
        required_events.append("system_save_settings_done")
    if "feedback_submit" in workflow:
        required_events.append("feedback_bug_report_submitted")
    if "slicer_launch" in workflow:
        required_events.append("slicer_launch_done")
    if "extract" in workflow:
        required_events.append("extractor_extract_done")
    if "merge_8color" in workflow:
        required_events.append("extractor_merge_8color_done")
    if "merge_5color_ext" in workflow:
        required_events.append("extractor_merge_5color_extended_done")
    if "manual_fix" in workflow:
        required_events.append("extractor_manual_fix_done")
    if "preview_wb" in workflow:
        required_events.append("extractor_preview_wb_done")
    if "rotate" in workflow:
        required_events.append("extractor_rotate_done")
    if "confirm_palette" in workflow:
        required_events.append("extractor_confirm_palette_done")
    if "replace_color" in workflow:
        required_events.append("converter_replace_color_done")
    if "reset_replacements" in workflow:
        required_events.append("converter_reset_replacements_done")
    if "source_color_pick" in workflow:
        required_events.append("converter_source_color_pick_done")
    if "color_highlight" in workflow:
        required_events.append("converter_color_highlight_done")
    if "region_detect" in workflow:
        required_events.append("converter_region_detect_done")
    if "region_requantize" in workflow:
        required_events.append("converter_region_requantize_done")
    if "replace_colors_batch" in workflow:
        required_events.append("converter_replace_colors_batch_done")
    if "region_replace_batch" in workflow:
        required_events.append("converter_region_replace_batch_done")
    if "predict_recipe" in workflow:
        required_events.append("converter_predict_recipe_done")
    if "apply_recipe_override" in workflow:
        required_events.append("converter_apply_recipe_override_done")
    if "region_recipe" in workflow:
        required_events.append("converter_region_recipe_done")
    if "merge_colors" in workflow:
        required_events.append("converter_merge_colors_done")
    if "generate_large_format" in workflow:
        required_events.append("converter_generate_large_format_done")
    if "batch" in workflow:
        required_events.append("converter_batch_done")
    if "batch_merge_3mf" in workflow:
        required_events.append("batch_merge_3mf_init")
        required_events.append("batch_merge_3mf_done")
    if "puzzle_layout_preview" in workflow:
        required_events.append("converter_puzzle_layout_preview_done")
    if "generate_puzzle" in workflow:
        required_events.append("converter_puzzle_generate_done")
    if "auto_detect_colors" in workflow:
        required_events.append("converter_auto_detect_colors_done")
    if "cleanup_session_files" in workflow:
        required_events.append("converter_cleanup_session_files_done")

    required_events = list(dict.fromkeys(required_events))
    checks = [
        CheckResult.evaluate(
            name=f"workflow_event_{event}",
            actual=int(event_counts.get(event, 0)),
            operator=">=",
            threshold=1,
        )
        for event in required_events
    ]
    if "feedback_submit" in workflow:
        checks.append(
            CheckResult.evaluate(
                name="workflow_event_feedback_bug_report_submitted_exact",
                actual=int(event_counts.get("feedback_bug_report_submitted", 0)),
                operator="==",
                threshold=1,
            )
        )
    return checks


def _replace_required_events_for_mode(mode: Mode) -> tuple[str, ...]:
    """Return replace-family canaries for the selected execution mode."""

    events = ["converter_region_replace_timing"]
    if mode == "full":
        events.append("vector_matched_rgb_overrides_applied")
    return tuple(events)


def write_report(report: QualityReport, output_path: Path) -> None:
    """Write the report JSON to disk.

    Args:
        report: Report to serialize. 待序列化报表。
        output_path: Destination JSON path. 目标 JSON 路径。
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the log quality check command.

    Args:
        argv: Optional CLI argument vector. 可选 CLI 参数列表。

    Returns:
        int: Process exit code. 进程退出码。
    """

    try:
        args = parse_args(argv)
        mode: Mode = args.mode
        workflow = _parse_workflow(args.workflow)
        output_path = _default_output_path(mode) if args.output is None else args.output
        output_path = (REPO_ROOT / output_path).resolve() if not output_path.is_absolute() else output_path
        log_path = output_path.with_suffix(".log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists():
            log_path.unlink()

        if mode == "fast":
            audit_result = run_fast_mode(log_path, workflow)
        else:
            audit_result = run_full_mode(
                log_path,
                workflow,
                port=args.port,
                timeout=args.timeout,
            )

        report = build_quality_report(
            mode=mode,
            workflow=workflow,
            log_path=log_path,
            audit_result=audit_result,
        )
        write_report(report, output_path)
        sys.stdout.write(_format_stdout_summary(report, output_path))
        return 0 if report.overall_passed else 1
    except QualityCheckError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    except Exception as exc:
        sys.stderr.write(f"ERROR: {type(exc).__name__}: {exc}\n")
        return 2


def _prepare_log_environment(log_path: Path) -> None:
    os.environ["LUMINA_LOG_PATH"] = str(log_path)
    os.environ["LUMINA_LOG_LEVEL"] = "INFO"
    os.environ["LUMINA_LOG_FORMAT"] = "json"
    os.environ.pop("LUMINA_LOG_INIT_BY_PARENT", None)


def _disable_feedback_upload_env(env: MutableMapping[str, str]) -> None:
    """Keep quality-gate bug reports local; never upload them to the real server."""
    env["LUMINA_FEEDBACK_SERVER_URL"] = "off"


def _build_mock_worker_result(
    worker_fn: Callable[..., Any],
    created_paths: list[Path],
    np_module: Any,
    image_cls: Any,
    *worker_args: Any,
) -> dict[str, Any]:
    name = getattr(worker_fn, "__name__", "")
    if name == "worker_generate_preview":
        preview_contract = _mock_preview_worker_contract(worker_fn, worker_args)
        if preview_contract["is_vector"]:
            return _build_mock_vector_preview_result(
                created_paths,
                np_module,
                image_cls,
                preview_contract["color_mode"],
                preview_contract["metadata"],
            )
        return _build_mock_preview_result(
            created_paths,
            np_module,
            image_cls,
            preview_contract["color_mode"],
            preview_contract["metadata"],
        )
    if name in {
        "worker_generate_model",
        "worker_batch_convert_item",
        "_submit_puzzle_worker",
    }:
        return _build_mock_generate_result(created_paths, worker_name=name)
    if name == "worker_vectorize":
        svg_path = _make_temp_path(".svg", created_paths)
        svg_path.write_text("<svg/>", encoding="utf-8")
        return {
            "svg_path": str(svg_path),
            "num_shapes": 5,
            "num_colors": 3,
            "width": 64,
            "height": 64,
            "palette": [[255, 0, 0], [0, 255, 0], [0, 0, 255]],
        }
    raise QualityCheckError(f"Unexpected worker submitted in fast mode: {name}")


def _mock_preview_worker_contract(
    worker_fn: Callable[..., Any],
    worker_args: Sequence[Any],
) -> dict[str, Any]:
    """Bind fast-gate inputs to the current preview-worker signature.

    通过真实 worker 签名绑定 mock 参数，避免新增位置参数后静默错位。
    """

    import inspect

    try:
        bound = inspect.signature(worker_fn).bind(*worker_args)
    except TypeError as exc:
        raise QualityCheckError(
            "Fast-mode preview mock no longer matches worker_generate_preview"
        ) from exc
    bound.apply_defaults()
    arguments = bound.arguments

    def _enum_text(name: str, default: str) -> str:
        value = arguments.get(name, default)
        enum_value = getattr(value, "value", value)
        return str(enum_value) if enum_value is not None else default

    color_mode = _enum_text("color_mode", DEFAULT_COLOR_MODE)
    modeling_mode = _enum_text("modeling_mode", DEFAULT_MODELING_MODE)
    metadata = {
        "target_width_mm": float(arguments["target_width_mm"]),
        "color_mode": color_mode,
        "modeling_mode": modeling_mode,
        "color_layers": arguments.get("color_layers"),
        "layer_height_mm": arguments.get("layer_height_mm"),
        "quantize_colors": int(arguments["quantize_colors"]),
        "enable_cleanup": bool(arguments["enable_cleanup"]),
        "hue_weight": float(arguments["hue_weight"]),
        "chroma_gate": float(arguments["chroma_gate"]),
        "use_lut_constrained": bool(arguments["use_lut_constrained"]),
        "auto_dynamic_range": bool(arguments["auto_dynamic_range"]),
        "model_enable": bool(arguments["model_enable"]),
        "model_only": bool(arguments["model_only"]),
        "model_threshold": arguments.get("model_threshold"),
        "model_margin": arguments.get("model_margin"),
        "svg_pixels_per_mm": float(arguments["svg_pixels_per_mm"]),
        "material_source": str(arguments["material_source"]),
    }
    image_path = str(arguments.get("image_path", ""))
    return {
        "color_mode": color_mode,
        "is_vector": (
            image_path.lower().endswith(".svg")
            and modeling_mode == VECTOR_MODELING_MODE
        ),
        "metadata": metadata,
    }


def _build_mock_preview_result(
    created_paths: list[Path],
    np_module: Any,
    image_cls: Any,
    color_mode: str,
    preview_analysis_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    import pickle

    preview = np_module.zeros((8, 8, 3), dtype=np_module.uint8)
    preview[:4, :, :] = [255, 0, 0]
    preview[4:, :, :] = [255, 255, 255]
    mask_solid = np_module.ones((8, 8), dtype=bool)
    slots, preview_colors = _mock_color_config_for_mode(color_mode)
    material_matrix = _mock_material_matrix(np_module, 8, 8, len(slots))

    png_path = _make_temp_path(".png", created_paths)
    image_cls.fromarray(preview).save(png_path)

    cache = {
        "target_w": 8,
        "target_h": 8,
        "target_width_mm": 60.0,
        "color_palette": [
            {"hex": "#ff0000", "color": (255, 0, 0), "count": 32, "percentage": 50.0},
            {"hex": "#ffffff", "color": (255, 255, 255), "count": 32, "percentage": 50.0},
        ],
        "matched_rgb": preview.copy(),
        "mask_solid": mask_solid,
        "quantized_image": preview.copy(),
        "material_matrix": material_matrix,
        "color_conf": {
            "slots": slots,
            "preview": preview_colors,
        },
        "preview_colors": preview_colors,
        "slot_names": slots,
    }
    cache.update(preview_analysis_metadata)
    cache_path = _make_temp_path(".pkl", created_paths)
    with cache_path.open("wb") as handle:
        pickle.dump(cache, handle)

    return {
        "status_msg": "Preview OK",
        "preview_png_path": str(png_path),
        "cache_data_path": str(cache_path),
    }


def _build_mock_vector_preview_result(
    created_paths: list[Path],
    np_module: Any,
    image_cls: Any,
    color_mode: str,
    preview_analysis_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    import pickle

    preview = np_module.zeros((10, 10, 3), dtype=np_module.uint8)
    slots, preview_colors = _mock_color_config_for_mode(color_mode)
    primary_rgba = preview_colors[min(len(preview_colors) - 1, 3)]
    preview[:, :, :] = primary_rgba[:3]
    mask_solid = np_module.ones((10, 10), dtype=bool)
    material_matrix = _mock_material_matrix(np_module, 10, 10, len(slots))
    preview_rgba = np_module.zeros((10, 10, 4), dtype=np_module.uint8)
    preview_rgba[:, :, :3] = preview
    preview_rgba[:, :, 3] = 255

    png_path = _make_temp_path(".png", created_paths)
    image_cls.fromarray(preview).save(png_path)

    cache = {
        "target_w": 10,
        "target_h": 10,
        "target_width_mm": 60.0,
        "color_palette": [
            {"hex": "#0080ff", "color": (0, 128, 255), "count": 100, "percentage": 100.0},
        ],
        "matched_rgb": preview.copy(),
        "mask_solid": mask_solid,
        "quantized_image": preview.copy(),
        "material_matrix": material_matrix,
        "preview_rgba": preview_rgba,
        "color_conf": {
            "slots": slots,
            "preview": preview_colors,
        },
        "preview_colors": preview_colors,
        "slot_names": slots,
        "color_contours": {},
        "lut_match_info": {"match_mode": "mock-vector"},
    }
    cache.update(preview_analysis_metadata)
    cache_path = _make_temp_path(".pkl", created_paths)
    with cache_path.open("wb") as handle:
        pickle.dump(cache, handle)

    return {
        "status_msg": "Vector Preview OK",
        "preview_png_path": str(png_path),
        "cache_data_path": str(cache_path),
    }


def _mock_color_config_for_mode(color_mode: str) -> tuple[list[str], dict[int, list[int]]]:
    default_config = MOCK_COLOR_CONFIGS[DEFAULT_COLOR_MODE]
    slots, rgb_values = MOCK_COLOR_CONFIGS.get(color_mode, default_config)
    return list(slots), {index: [*rgb, 255] for index, rgb in enumerate(rgb_values)}


def _mock_material_matrix(
    np_module: Any,
    height: int,
    width: int,
    slot_count: int,
) -> Any:
    y_indices, x_indices, layer_indices = np_module.indices((height, width, 5))
    return ((y_indices + x_indices + layer_indices) % slot_count).astype(
        np_module.int16
    )


def _build_mock_generate_result(created_paths: list[Path], *, worker_name: str = "") -> dict[str, Any]:
    threemf_path = _make_temp_path(".3mf", created_paths)
    threemf_path.write_bytes(b"mock 3mf")
    glb_path = _make_temp_path(".glb", created_paths)
    glb_path.write_bytes(b"mock glb")
    result: dict[str, Any] = {
        "threemf_path": str(threemf_path),
        "glb_path": str(glb_path),
        "status_msg": "Model OK",
    }
    if worker_name == "_submit_puzzle_worker":
        result.update(x_mirrored=False, mirror_span_mm=60.0)
    if worker_name == "worker_batch_convert_item":
        # Batch merge flow needs additional fields from the worker result.
        preview_glb_path = _make_temp_path(".glb", created_paths)
        preview_glb_path.write_bytes(b"mock preview glb")
        sidecar_path = _make_temp_path(".json", created_paths)
        sidecar_data = {
            "schema_version": 1,
            "source_filename": "mock_batch_item.png",
            "xy_bbox_mm": {"width_mm": 60.0, "depth_mm": 40.0},
            "slots": [
                {
                    "slot_id": 0,
                    "slot_name": "White",
                    "preview_color": "#ffffff",
                    "material_id": "GFL00",
                },
                {
                    "slot_id": 1,
                    "slot_name": "Red",
                    "preview_color": "#ff0000",
                    "material_id": "GFL01",
                },
            ],
        }
        sidecar_path.write_text(
            json.dumps(sidecar_data, ensure_ascii=False),
            encoding="utf-8",
        )
        result["preview_glb_path"] = str(preview_glb_path)
        result["metadata_sidecar_path"] = str(sidecar_path)
        result["xy_bbox_mm"] = (60.0, 40.0)
    return result


def _mock_assemble_puzzle_3mf(*, output_path: str, **_kwargs: Any) -> str:
    """Fast-mode stub for ``core.puzzle_3mf.assemble_puzzle_3mf``.

    Writes a placeholder byte payload to ``output_path`` so the puzzle endpoint
    success path can complete. The endpoint emits its canary log and registers
    the file via FileRegistry; downstream consumers (log analysis, INFO
    counters) only inspect the response payload, never the file content.
    """
    from pathlib import Path as _Path

    _Path(output_path).write_bytes(b"mock puzzle 3mf")
    return output_path


class _MockMergedBambu3MFWriter:
    """Fast-mode stub for MergedBambu3MFWriter.

    Writes a placeholder file so the batch merge path can complete without
    needing real 3MF parsing / OPC packaging.
    """

    def __init__(self, created_paths: list[Path]) -> None:
        self._created_paths = created_paths

    def write(self, items: Any, output_path: Any, **_kwargs: Any) -> None:
        output = Path(output_path) if not isinstance(output_path, Path) else output_path
        output.write_bytes(b"mock merged 3mf")


def _mock_requantize_gradient_regions(
    *,
    matched_rgb: Any,
    original_source_rgb: Any,
    region_id_map: Any,
    **_kwargs: Any,
) -> tuple[Any, int]:
    import numpy as np

    if original_source_rgb is None:
        raise ValueError("original_source_rgb is required")
    updated = np.asarray(matched_rgb, dtype=np.uint8).copy()
    region_ids = np.asarray(region_id_map)
    mask = region_ids == np.uint32(1001)
    if not np.any(mask):
        mask = region_ids > 0
    if not np.any(mask):
        mask = np.ones(updated.shape[:2], dtype=bool)
    updated[mask] = [1, 2, 3]
    return updated, int(mask.sum())


def _mock_extract_single_stage_dataset(
    created_paths: list[Path],
    *_args: Any,
    **_kwargs: Any,
) -> Any:
    from core.single_stage import SingleStageExtractResult

    stage_json_path = _make_temp_path(".json", created_paths)
    stage_json_path.write_text(
        json.dumps({"datasets": [], "meta": {"warnings": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return SingleStageExtractResult(
        stage_json_path=str(stage_json_path),
        dataset_summary={
            "substrate_count": 1,
            "color_count": 1,
            "dataset_count": 1,
            "image_count": 1,
            "substrates": ["white"],
            "coverage": [{"substrate_id": "white", "colors": ["White"]}],
            "datasets": [],
        },
        warnings=[],
        extracted_root=str(stage_json_path.parent),
    )


def _mock_fit_stage_a_from_stage_json(
    created_paths: list[Path],
    *_args: Any,
    **_kwargs: Any,
) -> Any:
    from core.single_stage import StageAFitResult

    params_path = _make_temp_path(".json", created_paths)
    params_path.write_text(
        json.dumps({"version": "stage_a/v1"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return StageAFitResult(
        params_path=str(params_path),
        fit_summary={
            "substrate_count": 1,
            "channel_count": 6,
            "substrates": ["white"],
            "colors": ["White"],
            "overall_validation": {"mean_delta_e": 0.001},
            "warnings": [],
        },
    )


def _mock_extract_gradient_card_stage_a(
    created_paths: list[Path],
    *_args: Any,
    **_kwargs: Any,
) -> Any:
    import numpy as np
    from core.single_stage import GradientCardStageAResult

    params_path = _make_temp_path(".json", created_paths)
    params_payload = {"version": "stage_a/v1"}
    params_path.write_text(
        json.dumps(params_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return GradientCardStageAResult(
        params_path=str(params_path),
        params_payload=params_payload,
        fit_summary={
            "substrate_count": 2,
            "channel_count": 6,
            "substrates": ["white", "black"],
            "colors": ["stub"],
            "overall_validation": {"mean_delta_e": 0.001},
            "warnings": [],
            "orientation_ranking": {
                "orientation_reliable": True,
                "delta_e_gap": 1.0,
                "top_candidates": [],
            },
        },
        material_summary={
            "sample_count": 1,
            "per_substrate_sample_count": 1,
            "grid_rows": 1,
            "grid_cols": 1,
            "layer_height_mm": 0.04,
            "warp_width_px": 8,
            "warp_height_px": 8,
            "thickness_layers": [0],
            "sample_boxes": [],
            "white_zero_rgb": [255, 255, 255],
            "black_zero_rgb": [0, 0, 0],
            "estimated_rgb": [128, 130, 132],
            "estimated_k": [0.1, 0.1, 0.1],
        },
        source_summary={
            "white_image_size": [16, 16],
            "black_image_size": [16, 16],
        },
        warnings=[],
        white_warp_rgb=np.zeros((8, 8, 3), dtype=np.uint8),
        black_warp_rgb=np.zeros((8, 8, 3), dtype=np.uint8),
    )


def _mock_save_gradient_card_material(
    created_paths: list[Path],
    *_args: Any,
    **_kwargs: Any,
) -> Any:
    from core.single_stage import MaterialArchiveSaveResult

    archive_path = _make_temp_path(".json", created_paths)
    params_path = _make_temp_path(".json", created_paths)
    archive_path.write_text(
        json.dumps({"material_name": "Stub PLA"}, ensure_ascii=False),
        encoding="utf-8",
    )
    params_path.write_text(
        json.dumps({"version": "stage_a/v1"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return MaterialArchiveSaveResult(
        archive_path=str(archive_path),
        stage_a_params_path=str(params_path),
        material_summary={
            "material_name": "Stub PLA",
            "directory_name": "stub_material_v1",
            "brand": "Lumina",
            "archive_path": str(archive_path),
            "stage_a_params_path": str(params_path),
            "verification_count": 1,
        },
    )


def _mock_delete_gradient_card_material(*_args: Any, **kwargs: Any) -> Any:
    from core.single_stage import MaterialArchiveDeleteResult

    directory_name = str(kwargs.get("directory_name") or "stub_material_v1")
    return MaterialArchiveDeleteResult(
        directory_name=directory_name,
        material_name="Stub PLA",
        deleted_path=str(REPO_ROOT / "materials" / directory_name),
    )


def _mock_update_gradient_card_material(
    created_paths: list[Path],
    *_args: Any,
    **kwargs: Any,
) -> Any:
    from core.single_stage import MaterialArchiveUpdateResult

    archive_path = _make_temp_path(".json", created_paths)
    params_path = _make_temp_path(".json", created_paths)
    material_name = str(kwargs.get("material_name") or "Stub PLA")
    directory_name = str(kwargs.get("directory_name") or "stub_material_v1")
    archive_path.write_text(
        json.dumps({"material_name": material_name}, ensure_ascii=False),
        encoding="utf-8",
    )
    params_path.write_text(
        json.dumps({"version": "stage_a/v1"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return MaterialArchiveUpdateResult(
        archive_path=str(archive_path),
        stage_a_params_path=str(params_path),
        material_summary={
            "material_name": material_name,
            "directory_name": directory_name,
            "brand": kwargs.get("brand"),
            "archive_path": str(archive_path),
            "stage_a_params_path": str(params_path),
            "estimated_rgb": kwargs.get("estimated_rgb") or [128, 130, 132],
            "verification_count": 1,
        },
    )


def _mock_export_gradient_card_materials(
    created_paths: list[Path],
    *_args: Any,
    **kwargs: Any,
) -> Any:
    from core.single_stage.material_library import MaterialArchiveExportResult

    archive_path = _make_temp_path(".zip", created_paths)
    archive_path.write_bytes(b"stub material export")
    directory_names = kwargs.get("directory_names") or ["stub_material_v1"]
    return MaterialArchiveExportResult(
        archive_path=str(archive_path),
        download_filename="stub_materials.zip",
        exported_directory_names=[str(name) for name in directory_names],
    )


def _mock_import_gradient_card_materials(
    created_paths: list[Path],
    *_args: Any,
    **_kwargs: Any,
) -> Any:
    from core.single_stage.material_library import MaterialArchiveImportResult

    archive_path = _make_temp_path(".json", created_paths)
    params_path = _make_temp_path(".json", created_paths)
    archive_path.write_text(
        json.dumps({"material_name": "Imported Stub PLA"}, ensure_ascii=False),
        encoding="utf-8",
    )
    params_path.write_text(
        json.dumps({"version": "stage_a/v1"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return MaterialArchiveImportResult(
        imported_materials=[
            {
                "material_name": "Imported Stub PLA",
                "directory_name": "imported_stub_material_v1",
                "brand": "Lumina",
                "archive_path": str(archive_path),
                "stage_a_params_path": str(params_path),
                "verification_count": 1,
            }
        ]
    )


def _mock_solver_cache_metadata() -> dict[str, Any]:
    return {
        "cache_id": "stub_hash",
        "canonical_materials": [
            {"directory_name": "stub_material_v1"},
            {"directory_name": "stub_material_v2"},
        ],
        "layer_count": 8,
        "layer_height_mm": 0.04,
        "substrate": "white",
        "grid_resolution": 64,
        "total_combinations": 256,
        "valid_cell_count": 200,
        "total_cell_count": 256,
        "mean_delta_e": 1.5,
        "max_delta_e": 4.0,
        "build_time_seconds": 1.0,
        "built_at": "2024-01-01T00:00:00",
    }


class _MockMaterialSolverCache:
    metadata = _mock_solver_cache_metadata()
    valid_cell_count = 200

    def lookup_top_k(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return _mock_color_suggestions()


def _mock_load_material_solver_cache(*_args: Any, **_kwargs: Any) -> Any:
    return _MockMaterialSolverCache()


def _mock_build_material_solver_cache(*_args: Any, **_kwargs: Any) -> Any:
    return _MockMaterialSolverCache()


def _mock_save_material_solver_cache(
    created_paths: list[Path],
    *_args: Any,
    **_kwargs: Any,
) -> Path:
    cache_path = _make_temp_path(".npz", created_paths)
    cache_path.write_bytes(b"x" * 64)
    return cache_path


def _mock_delete_cached_entry(*_args: Any, **_kwargs: Any) -> bool:
    return True


class _MockColorSuggestion:
    pass


def _mock_color_suggestions() -> list[Any]:
    import numpy as np

    suggestion = _MockColorSuggestion()
    suggestion.matched_rgb = np.array([255, 0, 0], dtype=np.uint8)
    suggestion.delta_e = 1.5
    suggestion.recipe = np.array([1, 0, 1], dtype=np.int32)
    return [suggestion]


def _mock_suggest_colors_for_target(*_args: Any, **_kwargs: Any) -> list[Any]:
    return _mock_color_suggestions()


def _mock_load_multiple_materials(directory_names: Sequence[str]) -> list[Any]:
    return [
        {"directory_name": str(directory_name)}
        for directory_name in directory_names
    ]


def _mock_palette_cache_identity(_materials: Sequence[Any]) -> str:
    return "stub_hash"


def _mock_cache_file_path(
    created_paths: list[Path],
    *_args: Any,
    **_kwargs: Any,
) -> Path:
    cache_path = _make_temp_path(".npz", created_paths)
    cache_path.write_bytes(b"stub cache")
    return cache_path


def _mock_calibration_board(
    created_paths: list[Path],
    image_cls: Any,
    *_args: Any,
    **_kwargs: Any,
) -> tuple[str, Any, str]:
    output_path = _make_temp_path(".3mf", created_paths)
    output_path.write_bytes(b"calibration board")
    return str(output_path), image_cls.new("RGB", (4, 4), (0, 0, 0)), "ok"


def _mock_single_stage_kit(
    created_paths: list[Path],
    image_cls: Any,
    *_args: Any,
    **_kwargs: Any,
) -> SimpleNamespace:
    zip_path = _make_temp_path(".zip", created_paths)
    manifest_path = _make_temp_path(".json", created_paths)
    zip_path.write_bytes(b"single-stage kit")
    manifest_path.write_text("{}", encoding="utf-8")
    return SimpleNamespace(
        zip_path=str(zip_path),
        manifest_path=str(manifest_path),
        preview_image=image_cls.new("RGB", (4, 4), (0, 0, 0)),
        jobs=[
            {
                "color": "White",
                "color_name": "White",
                "material": "PLA Basic",
                "substrate_id": "white",
                "substrate_display_name": "White",
                "filename": "white.3mf",
            }
        ],
        message="ok",
    )


class _MockStackLut:
    def __len__(self) -> int:
        return 1

    def tolist(self) -> list[list[int]]:
        return [[0, 1, 2, 3, 4]]


class _MockFiveColorEngine:
    color_count = 5
    stack_lut = _MockStackLut()

    def query(self, selected_indices: Sequence[int]) -> SimpleNamespace:
        return SimpleNamespace(
            found=True,
            selected_indices=list(selected_indices),
            result_rgb=(1, 2, 3),
            row_index=0,
            message="ok",
            source="mock",
        )

    def get_base_colors(self) -> list[tuple[int, int, int]]:
        return [
            (255, 255, 255),
            (255, 0, 0),
            (255, 255, 0),
            (0, 128, 255),
            (0, 0, 0),
        ]

    def get_color_names(self) -> list[str]:
        return ["White", "Red", "Yellow", "Blue", "Black"]

    def accepted_selection_lengths(self) -> tuple[int, ...]:
        return (5,)


def _mock_load_five_color_engine(lut_name: str) -> tuple[_MockFiveColorEngine, str]:
    return _MockFiveColorEngine(), lut_name


def _mock_generate_recipe_swatch(
    created_paths: list[Path],
    image_cls: Any,
    *_args: Any,
    **_kwargs: Any,
) -> tuple[str, Any, str]:
    output_path = _make_temp_path(".3mf", created_paths)
    output_path.write_bytes(b"swatch")
    return str(output_path), image_cls.new("RGB", (4, 4), (0, 0, 0)), "ok"


def _make_temp_path(suffix: str, created_paths: list[Path]) -> Path:
    fd, raw_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    path = Path(raw_path)
    created_paths.append(path)
    return path


def _synthesize_lut_keyed_json(
    path: Path | str,
    *,
    color_mode: str,
    rgb: Any,
    stacks: Any,
) -> None:
    from utils.lut_manager import LUTManager

    path_obj = Path(str(path))
    metadata = LUTManager.infer_default_metadata(
        path_obj.stem,
        str(path_obj),
        len(rgb),
        color_mode=color_mode,
    )
    LUTManager.save_keyed_json(str(path_obj), rgb, stacks, metadata)


def _synthesize_keyed_json_lut_bytes() -> bytes:
    """Produce a tiny well-formed Keyed-JSON LUT for upload tests."""

    payload = {
        "schema_version": "keyed-v1",
        "color_mode": DEFAULT_COLOR_MODE,
        "palette": {
            "White": {
                "material": "PLA",
                "hex_color": "#FFFFFF",
                "color_name": "White",
            },
            "Red": {
                "material": "PLA",
                "hex_color": "#FF0000",
                "color_name": "Red",
            },
            "Yellow": {
                "material": "PLA",
                "hex_color": "#FFFF00",
                "color_name": "Yellow",
            },
            "Blue": {
                "material": "PLA",
                "hex_color": "#0000FF",
                "color_name": "Blue",
            },
        },
        "entries": [
            {
                "rgb": [255, 255, 255],
                "hex": "#FFFFFF",
                "lab": [100.0, 0.0, 0.0],
                "recipe": ["White", "White", "White"],
            },
            {
                "rgb": [255, 0, 0],
                "hex": "#FF0000",
                "lab": [53.2408, 80.0925, 67.2032],
                "recipe": ["Red", "Red", "Red"],
            },
        ],
    }
    return json.dumps(payload).encode("utf-8")


def _synthesize_rgb_png_bytes(width: int, height: int) -> bytes:
    from io import BytesIO

    import numpy as np
    from PIL import Image

    image = np.full((height, width, 3), [128, 130, 132], dtype=np.uint8)
    buffer = BytesIO()
    Image.fromarray(image, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _synthesize_single_stage_dataset_zip_bytes() -> bytes:
    def _label_payload(color_name: str) -> dict[str, Any]:
        return {
            "version": "5.0.1",
            "flags": {},
            "imagePath": "sample.png",
            "imageHeight": 64,
            "imageWidth": 64,
            "shapes": [
                {
                    "label": "ColorChecker",
                    "points": [[4, 4], [28, 4], [28, 28], [4, 28]],
                    "group_id": None,
                    "shape_type": "polygon",
                    "flags": {},
                },
                {
                    "label": color_name,
                    "points": [[32, 32], [60, 32], [60, 60], [32, 60]],
                    "group_id": None,
                    "shape_type": "polygon",
                    "flags": {},
                },
            ],
        }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for substrate_id, color_name in (("white", "White"), ("black", "Black")):
            archive.writestr(
                f"{substrate_id}/{color_name}/sample.png",
                _synthesize_rgb_png_bytes(64, 64),
            )
            archive.writestr(
                f"{substrate_id}/{color_name}/sample.json",
                json.dumps(_label_payload(color_name), ensure_ascii=False),
            )
    return buffer.getvalue()


def _synthesize_gradient_card_kit_zip_bytes() -> bytes:
    manifest = {
        "schema_version": "1.0",
        "workflow": "single-stage-kit",
        "material_default": "Stub PLA",
        "substrate_id": "white",
        "substrate_display_name": "White",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    return buffer.getvalue()


def _write_single_stage_colorchecker_assets(
    asset_dir: Path,
    created_paths: list[Path],
) -> None:
    ref_json_path = asset_dir / "ColorCheckerjson.json"
    desc_path = asset_dir / "desc.txt"
    _mkdir_for_cleanup(asset_dir, created_paths)
    ref_payload = {
        "version": "5.0.1",
        "flags": {},
        "imageHeight": 32,
        "imageWidth": 32,
        "shapes": [
            {
                "label": "ColorChecker",
                "points": [[0, 0], [32, 0], [32, 32], [0, 32]],
                "group_id": None,
                "shape_type": "polygon",
                "flags": {},
            },
            {
                "label": "Patch1",
                "points": [[4, 4], [10, 4], [10, 10], [4, 10]],
                "group_id": None,
                "shape_type": "polygon",
                "flags": {},
            },
            {
                "label": "Patch2",
                "points": [[12, 4], [18, 4], [18, 10], [12, 10]],
                "group_id": None,
                "shape_type": "polygon",
                "flags": {},
            },
            {
                "label": "Patch3",
                "points": [[20, 4], [26, 4], [26, 10], [20, 10]],
                "group_id": None,
                "shape_type": "polygon",
                "flags": {},
            },
        ],
    }
    desc_text = "\n\n".join(
        [
            "1. Patch1:\nsRGB: [128, 130, 132]",
            "2. Patch2:\nsRGB: [128, 130, 132]",
            "3. Patch3:\nsRGB: [128, 130, 132]",
        ]
    )
    if not ref_json_path.exists():
        ref_json_path.write_text(
            json.dumps(ref_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        created_paths.append(ref_json_path)
    if not desc_path.exists():
        desc_path.write_text(desc_text + "\n", encoding="utf-8")
        created_paths.append(desc_path)


def _mkdir_for_cleanup(path: Path, created_paths: list[Path]) -> None:
    if path.exists():
        return
    path.mkdir(parents=True, exist_ok=True)
    created_paths.append(path)


def _safe_to_replace_reference_stub(reference_root: Path) -> bool:
    if not reference_root.exists():
        return True
    allowed_files = {
        ".lumina_log_quality_stub",
        "modeling/__init__.py",
        "modeling/pipeline/__init__.py",
        "modeling/pipeline/step1_extract_stages.py",
        "modeling/pipeline/step2_fit_stage_a.py",
        "modeling/data/ColorChecker/ColorCheckerjson.json",
        "modeling/data/ColorChecker/desc.txt",
    }
    for path in reference_root.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        try:
            relative = path.relative_to(reference_root).as_posix()
        except ValueError:
            return False
        if relative not in allowed_files:
            return False
    return True


def _ensure_single_stage_reference_stub(created_paths: list[Path]) -> None:
    reference_root = REPO_ROOT / "reference" / "ChromaPrint3D"
    required_files = (
        reference_root / "modeling" / "pipeline" / "step1_extract_stages.py",
        reference_root / "modeling" / "pipeline" / "step2_fit_stage_a.py",
    )
    if reference_root.exists() and not _safe_to_replace_reference_stub(reference_root):
        return
    if reference_root.exists():
        shutil.rmtree(reference_root)
        try:
            reference_root.parent.rmdir()
        except OSError:
            pass
    if all(path.exists() for path in required_files):
        return

    modeling_dir = reference_root / "modeling"
    pipeline_dir = modeling_dir / "pipeline"
    colorchecker_dir = modeling_dir / "data" / "ColorChecker"
    reference_parent = reference_root.parent
    _mkdir_for_cleanup(reference_parent, created_paths)
    _mkdir_for_cleanup(reference_root, created_paths)
    _mkdir_for_cleanup(modeling_dir, created_paths)
    _mkdir_for_cleanup(pipeline_dir, created_paths)
    _mkdir_for_cleanup(colorchecker_dir.parent, created_paths)
    _mkdir_for_cleanup(colorchecker_dir, created_paths)

    for package_init in (
        modeling_dir / "__init__.py",
        pipeline_dir / "__init__.py",
    ):
        package_init.write_text("", encoding="utf-8")
        created_paths.append(package_init)

    (pipeline_dir / "step1_extract_stages.py").write_text(
        """
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ref-json", required=True)
    parser.add_argument("--ref-desc")
    args = parser.parse_args()
    input_root = Path(args.input_root)
    datasets = []
    for substrate_dir in sorted(path for path in input_root.iterdir() if path.is_dir()):
        for color_dir in sorted(path for path in substrate_dir.iterdir() if path.is_dir()):
            image_count = sum(
                1
                for item in color_dir.iterdir()
                if item.is_file() and item.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
            )
            datasets.append(
                {
                    "substrate_id": substrate_dir.name,
                    "color_name": color_dir.name,
                    "image_count": image_count,
                    "calibration": {"source": "log_quality_stub"},
                }
            )
    Path(args.output).write_text(
        json.dumps({"datasets": datasets, "meta": {"warnings": []}}, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
""".lstrip(),
        encoding="utf-8",
    )
    created_paths.append(pipeline_dir / "step1_extract_stages.py")

    (pipeline_dir / "step2_fit_stage_a.py").write_text(
        """
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = {
        "fitted_substrates": {"white": {}},
        "parameters": {"channels": [{"color_name": "White"}]},
        "validation": {"overall": {"mean_delta_e": 0.001}},
        "meta": {"warnings": []},
    }
    Path(args.output).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
""".lstrip(),
        encoding="utf-8",
    )
    created_paths.append(pipeline_dir / "step2_fit_stage_a.py")

    _write_single_stage_colorchecker_assets(colorchecker_dir, created_paths)
    (reference_root / ".lumina_log_quality_stub").write_text(
        "Created by scripts/log_quality_check.py for self-contained full-mode checks.\n",
        encoding="utf-8",
    )
    created_paths.append(reference_root / ".lumina_log_quality_stub")


def _ensure_single_stage_colorchecker_assets() -> list[Path]:
    created_paths: list[Path] = []
    _ensure_single_stage_reference_stub(created_paths)
    _write_single_stage_colorchecker_assets(
        REPO_ROOT / "assets" / "ColorChecker",
        created_paths,
    )
    return created_paths


def _remove_single_stage_colorchecker_assets(paths: Sequence[Path]) -> None:
    for path in reversed(paths):
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                if path.name == "ChromaPrint3D" and _safe_to_replace_reference_stub(path):
                    shutil.rmtree(path)
                else:
                    path.rmdir()
        except OSError:
            pass


def _create_saved_gradient_card_material_fixture() -> str:
    from config import MATERIALS_DIR

    directory_name = f"pr113_stub_{uuid.uuid4().hex}"
    material_dir = Path(MATERIALS_DIR) / directory_name
    material_dir.mkdir(parents=True, exist_ok=False)
    stage_a_params_path = material_dir / "stage_A_parameters.json"
    stage_a_params_path.write_text(
        json.dumps({"meta": {"material_name": "Stub PLA"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    archive_payload = {
        "schema_version": "1.1",
        "kind": "lumina_stage_a_material",
        "material_name": "Stub PLA",
        "brand": "Lumina",
        "created_at": "2026-04-28T00:00:00+00:00",
        "updated_at": "2026-04-28T00:00:00+00:00",
        "stage_a_params_file": stage_a_params_path.name,
        "fit_summary": {"overall_validation": {"mean_delta_e": 0.001}},
        "material_summary": {"estimated_rgb": [128, 130, 132]},
        "source": {},
        "verification_count": 1,
        "verification_runs": [],
    }
    (material_dir / "material.json").write_text(
        json.dumps(archive_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return directory_name


def _remove_saved_gradient_card_material_fixture(directory_name: str | None) -> None:
    if not directory_name:
        return
    from config import MATERIALS_DIR

    material_dir = Path(MATERIALS_DIR) / directory_name
    try:
        resolved = material_dir.resolve()
        root = Path(MATERIALS_DIR).resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return
    try:
        shutil.rmtree(resolved)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _execute_http_workflow(base_url: str, workflow: list[str], timeout: float) -> None:
    import httpx

    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        _execute_workflow(client, workflow)


def _execute_workflow(client: Any, workflow: list[str]) -> None:
    lut_name = DEFAULT_LUT_NAME
    session_id: str | None = None
    for step in WORKFLOW_ORDER:
        if step not in workflow or step == "startup":
            continue
        if step == "lut_list":
            response = client.get("/api/lut/list")
            _raise_for_status(response.status_code, response.text, step)
            lut_name = _select_lut_name(response.json(), fallback=lut_name)
        elif step == "lut_colors":
            response = client.get(_lut_colors_path(lut_name))
            _raise_for_status(response.status_code, response.text, step)
        elif step == "preview":
            session_id = _post_preview(client, lut_name)
        elif step == "generate":
            if session_id is None:
                raise QualityCheckError("Workflow step 'generate' requires 'preview'")
            _post_generate(client, session_id, lut_name)
        elif step == "vector":
            _execute_vector_workflow(client, lut_name)
        elif step == "replace":
            _execute_replace_workflow(client, lut_name=lut_name)
        elif step in ALTERNATE_REPLACE_CONFIG:
            _execute_alternate_replace_workflow(client, step)
        elif step == "replace_color":
            _execute_replace_color_workflow(client)
        elif step == "reset_replacements":
            _execute_reset_replacements_workflow(client)
        elif step == "source_color_pick":
            _execute_source_color_pick_workflow(client)
        elif step == "color_highlight":
            _execute_color_highlight_workflow(client)
        elif step == "region_detect":
            _execute_region_detect_workflow(client)
        elif step == "region_requantize":
            _execute_region_requantize_workflow(client)
        elif step == "replace_colors_batch":
            _execute_replace_colors_batch_workflow(client)
        elif step == "region_replace_batch":
            _execute_region_replace_batch_workflow(client)
        elif step == "predict_recipe":
            _execute_predict_recipe_workflow(client)
        elif step == "apply_recipe_override":
            _execute_apply_recipe_override_workflow(client)
        elif step == "region_recipe":
            _execute_region_recipe_workflow(client)
        elif step == "merge_colors":
            _execute_merge_colors_workflow(client)
        elif step == "generate_large_format":
            _execute_generate_large_format_workflow(client)
        elif step == "batch":
            _execute_batch_workflow(client)
        elif step == "batch_merge_3mf":
            _execute_batch_merge_3mf_workflow(client)
        elif step == "puzzle_layout_preview":
            _execute_puzzle_layout_preview_workflow(client)
        elif step == "generate_puzzle":
            _execute_generate_puzzle_workflow(client)
        elif step == "auto_detect_colors":
            _execute_auto_detect_colors_workflow(client)
        elif step == "cleanup_session_files":
            _execute_cleanup_session_files_workflow(client)
        elif step == "extract_single_stage":
            _execute_extract_single_stage_workflow(client)
        elif step == "fit_stage_a":
            _execute_fit_stage_a_workflow(client)
        elif step == "extract_gradient_card_stage_a":
            _execute_extract_gradient_card_stage_a_workflow(client)
        elif step == "save_gradient_card_material":
            _execute_save_gradient_card_material_workflow(client)
        elif step == "delete_gradient_card_material":
            _execute_delete_gradient_card_material_workflow(client)
        elif step == "update_gradient_card_material":
            _execute_update_gradient_card_material_workflow(client)
        elif step == "export_gradient_card_materials":
            _execute_export_gradient_card_materials_workflow(client)
        elif step == "import_gradient_card_materials":
            _execute_import_gradient_card_materials_workflow(client)
        elif step == "material_solver_cache_status":
            _execute_material_solver_cache_status_workflow(client)
        elif step == "material_solver_cache_build":
            _execute_material_solver_cache_build_workflow(client)
        elif step == "material_solver_cache_delete":
            _execute_material_solver_cache_delete_workflow(client)
        elif step == "material_solver_cache_suggest_colors":
            _execute_material_solver_cache_suggest_colors_workflow(client)
        elif step == "calibration_generate":
            _execute_calibration_generate_workflow(client)
        elif step == "calibration_generate_single_stage_kit":
            _execute_calibration_generate_single_stage_kit_workflow(client)
        elif step == "five_color_query":
            _execute_five_color_query_workflow(client)
        elif step == "five_color_generate_swatch":
            _execute_five_color_generate_swatch_workflow(client)
        elif step == "five_color_base_colors":
            _execute_five_color_base_colors_workflow(client)
        elif step == "vectorize_image":
            _execute_vectorize_image_workflow(client)
        elif step == "lut_merge":
            _execute_lut_merge_workflow(client)
        elif step == "lut_compare":
            _execute_lut_compare_workflow(client)
        elif step == "lut_details":
            _execute_lut_details_workflow(client)
        elif step == "lut_upload":
            _execute_lut_upload_workflow(client)
        elif step == "lut_session_info":
            _execute_lut_session_info_workflow(client)
        elif step == "system_image_preview":
            _execute_system_image_preview_workflow(client)
        elif step == "system_save_settings":
            _execute_system_save_settings_workflow(client)
        elif step == "feedback_submit":
            _execute_feedback_submit_workflow(client)
        elif step == "slicer_launch":
            _execute_slicer_launch_workflow(client)
        elif step == "extract":
            _execute_extract_workflow(client)
        elif step == "merge_8color":
            _execute_merge_8color_workflow(client)
        elif step == "merge_5color_ext":
            _execute_merge_5color_ext_workflow(client)
        elif step == "manual_fix":
            _execute_manual_fix_workflow(client)
        elif step == "preview_wb":
            _execute_preview_wb_workflow(client)
        elif step == "rotate":
            _execute_rotate_workflow(client)
        elif step == "confirm_palette":
            _execute_confirm_palette_workflow(client)


def _execute_vector_workflow(client: Any, lut_name: str) -> None:
    session_id = _post_vector_preview(client, lut_name)
    _post_vector_generate(client, session_id, lut_name)


def _execute_replace_bw_workflow(client: Any) -> None:
    _execute_alternate_replace_workflow(client, "replace_bw")


def _execute_replace_8color_workflow(client: Any) -> None:
    _execute_alternate_replace_workflow(client, "replace_8color")


def _execute_replace_5color_ext_workflow(client: Any) -> None:
    _execute_alternate_replace_workflow(client, "replace_5color_ext")


def _execute_alternate_replace_workflow(client: Any, step: str) -> None:
    color_mode, lut_name = ALTERNATE_REPLACE_CONFIG[step]
    _execute_replace_workflow(
        client,
        mode=step,
        color_mode=color_mode,
        lut_name=lut_name,
    )


def _execute_replace_workflow(
    client: Any,
    *,
    mode: str = "replace",
    color_mode: str = DEFAULT_COLOR_MODE,
    lut_name: str = DEFAULT_LUT_NAME,
) -> None:
    """Exercise vector preview, click region replace, then cached vector generate."""

    # Use the same click-detect path as the frontend so the endpoint owns
    # selected_region_mask population before /region-replace mutates cache.
    preview_payload = _post_vector_preview_payload(
        client,
        lut_name,
        color_mode=color_mode,
        label=f"{mode} vector preview",
    )
    session_id = _extract_session_id(preview_payload, "Vector preview")
    click_x, click_y = _select_replace_click(preview_payload)
    detected_region = _post_region_detect(client, session_id, click_x, click_y)
    replacement_color = _choose_replacement_color(detected_region)
    _post_region_replace(client, session_id, replacement_color)
    _wait_for_async_glb(client, session_id)
    _post_vector_generate(
        client,
        session_id,
        lut_name,
        color_mode=color_mode,
        label=f"{mode} vector generate",
        use_cached_matched_rgb=True,
    )


def _execute_replace_color_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="replace_color setup",
    )
    session_id = _extract_session_id(preview_payload, "replace_color preview")
    selected_color = _first_palette_hex(preview_payload, fallback="#0080ff")
    replacement_color = "#ffffff" if selected_color.lower() != "#ffffff" else "#0000ff"
    payload = _post_replace_color(
        client,
        session_id,
        selected_color,
        replacement_color,
        label="replace_color",
    )
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Replace color response was not an object")
    if payload.get("status") != "ok":
        raise QualityCheckError("Replace color response status was not ok")
    if not payload.get("preview_url"):
        raise QualityCheckError("Replace color response did not include preview_url")
    if int(payload.get("replacement_count", 0)) < 1:
        raise QualityCheckError("Replace color response did not record a replacement")


def _execute_reset_replacements_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="reset_replacements setup",
    )
    session_id = _extract_session_id(preview_payload, "reset_replacements preview")
    selected_color = _first_palette_hex(preview_payload, fallback="#0080ff")
    replacement_color = "#ffffff" if selected_color.lower() != "#ffffff" else "#0000ff"
    _post_replace_color(
        client,
        session_id,
        selected_color,
        replacement_color,
        label="reset_replacements seed replace-color",
    )
    response = client.post(
        "/api/convert/reset-replacements",
        json={"session_id": session_id},
    )
    _raise_for_status(response.status_code, response.text, "reset_replacements")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Reset replacements response was not an object")
    if payload.get("status") != "ok":
        raise QualityCheckError("Reset replacements response status was not ok")
    if not payload.get("preview_url"):
        raise QualityCheckError("Reset replacements response did not include preview_url")


def _execute_source_color_pick_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="source_color_pick setup",
    )
    session_id = _extract_session_id(preview_payload, "source_color_pick preview")
    pick_x, pick_y = _select_replace_click(preview_payload)
    response = client.post(
        "/api/convert/source-color-pick",
        json={"session_id": session_id, "x": pick_x, "y": pick_y},
    )
    _raise_for_status(response.status_code, response.text, "source_color_pick")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Source color pick response was not an object")
    picked_color = payload.get("source_matched_hex")
    if not isinstance(picked_color, str) or not re.fullmatch(
        r"#[0-9a-fA-F]{6}",
        picked_color,
    ):
        raise QualityCheckError("Source color pick response did not include a hex color")


def _execute_color_highlight_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="color_highlight setup",
    )
    session_id = _extract_session_id(preview_payload, "color_highlight preview")
    highlighted_color = _first_palette_hex(preview_payload, fallback="#0080ff")
    response = client.post(
        "/api/convert/color-highlight",
        json={"session_id": session_id, "color_hexes": [highlighted_color]},
    )
    _raise_for_status(response.status_code, response.text, "color_highlight")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Color highlight response was not an object")
    if not payload.get("preview_url"):
        raise QualityCheckError("Color highlight response did not include preview_url")


def _execute_region_detect_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="region_detect setup",
    )
    session_id = _extract_session_id(preview_payload, "region_detect preview")
    click_x, click_y = _select_replace_click(preview_payload)
    payload = _post_region_detect(client, session_id, click_x, click_y)
    if not payload.get("region_id"):
        raise QualityCheckError("Region detect response did not include region_id")
    if not payload.get("color_hex"):
        raise QualityCheckError("Region detect response did not include color_hex")
    if not payload.get("preview_url"):
        raise QualityCheckError("Region detect response did not include preview_url")


def _execute_region_requantize_workflow(client: Any) -> None:
    selected_materials = _region_requantize_materials_for_client(client)
    created_cache_paths = (
        []
        if _client_uses_dependency_overrides(client)
        else _ensure_region_requantize_solver_cache(selected_materials)
    )
    try:
        preview_payload = _post_material_archive_preview_payload(
            client,
            selected_materials,
            label="region_requantize setup",
        )
        session_id = _extract_session_id(preview_payload, "region_requantize preview")
        _seed_region_requantize_test_session_if_available(client, session_id)
        response = client.post(
            "/api/convert/region-requantize",
            json={
                "session_id": session_id,
                "targets": [
                    {"gradient_group_index": 1, "gradient_region_index": 1}
                ],
                "local_quantize_colors": 12,
            },
        )
        _raise_for_status(response.status_code, response.text, "region_requantize")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError("Region requantize response was not an object")
        if not payload.get("preview_url"):
            raise QualityCheckError("Region requantize response did not include preview_url")
    finally:
        _remove_paths(created_cache_paths)


def _execute_replace_colors_batch_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="replace_colors_batch setup",
    )
    session_id = _extract_session_id(
        preview_payload,
        "replace_colors_batch preview",
    )
    response = client.post(
        "/api/convert/replace-colors-batch",
        json={
            "session_id": session_id,
            "replacements": [
                {
                    "selected_color": "#ffffff",
                    "replacement_color": "#0000ff",
                },
                {
                    "selected_color": "#ffff00",
                    "replacement_color": "#ff0000",
                },
            ],
        },
    )
    _raise_for_status(response.status_code, response.text, "replace_colors_batch")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Replace colors batch response was not an object")
    if payload.get("status") != "ok":
        raise QualityCheckError("Replace colors batch response status was not ok")
    if not payload.get("preview_url"):
        raise QualityCheckError(
            "Replace colors batch response did not include preview_url"
        )
    if int(payload.get("replacement_count", 0)) < 2:
        raise QualityCheckError(
            "Replace colors batch response did not record two replacements"
        )


def _execute_region_replace_batch_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="region_replace_batch setup",
    )
    session_id = _extract_session_id(
        preview_payload,
        "region_replace_batch preview",
    )
    click_x, click_y = _select_replace_click(preview_payload)
    _post_region_detect(client, session_id, click_x, click_y)
    response = client.post(
        "/api/convert/region-replace-batch",
        json={
            "session_id": session_id,
            "items": [
                {
                    "replacement_color": "#0000ff",
                    "click_x": click_x,
                    "click_y": click_y,
                }
            ],
        },
    )
    _raise_for_status(response.status_code, response.text, "region_replace_batch")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Region replace batch response was not an object")
    if not payload.get("preview_url"):
        raise QualityCheckError(
            "Region replace batch response did not include preview_url"
        )
    message = str(payload.get("message") or "")
    if "Batch replaced" not in message:
        raise QualityCheckError(
            "Region replace batch response did not report batch replacement"
        )


def _execute_predict_recipe_workflow(client: Any) -> None:
    selected_materials = _region_requantize_materials_for_client(client)
    created_cache_paths = (
        []
        if _client_uses_dependency_overrides(client)
        else _ensure_region_requantize_solver_cache(selected_materials)
    )
    try:
        preview_payload = _post_material_archive_preview_payload(
            client,
            selected_materials,
            label="predict_recipe setup",
        )
        session_id = _extract_session_id(preview_payload, "predict_recipe preview")
        response = client.post(
            "/api/convert/predict-recipe",
            json={
                "session_id": session_id,
                "recipe": [0, 0, 0, 0, 0],
                "layer_height_mm": 0.08,
                "color_layers": 5,
                "layer_order": "Top2Bottom",
            },
        )
        _raise_for_status(response.status_code, response.text, "predict_recipe")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError("Predict recipe response was not an object")
        if payload.get("status") != "ok":
            raise QualityCheckError("Predict recipe response status was not ok")
        rgb = payload.get("rgb")
        if not isinstance(rgb, list) or len(rgb) != 3:
            raise QualityCheckError("Predict recipe response did not include RGB triple")
        lab = payload.get("lab")
        if not isinstance(lab, list) or len(lab) != 3:
            raise QualityCheckError("Predict recipe response did not include LAB triple")
        if not payload.get("source"):
            raise QualityCheckError("Predict recipe response source was empty")
    finally:
        _remove_paths(created_cache_paths)


def _execute_apply_recipe_override_workflow(client: Any) -> None:
    selected_materials = _region_requantize_materials_for_client(client)
    created_cache_paths = (
        []
        if _client_uses_dependency_overrides(client)
        else _ensure_region_requantize_solver_cache(selected_materials)
    )
    try:
        preview_payload = _post_material_archive_preview_payload(
            client,
            selected_materials,
            label="apply_recipe_override setup",
        )
        session_id = _extract_session_id(
            preview_payload,
            "apply_recipe_override preview",
        )
        click_x, click_y = _select_replace_click(preview_payload)
        detected_region = _post_region_detect(client, session_id, click_x, click_y)
        region_id = detected_region.get("region_id")
        if not isinstance(region_id, str) or not region_id:
            raise QualityCheckError(
                "Region detect response did not include region_id"
            )
        response = client.post(
            "/api/convert/apply-recipe-override",
            json={
                "session_id": session_id,
                "region_ids": [region_id],
                "recipe": [0, 0, 0, 0, 0],
                "layer_height_mm": 0.08,
                "color_layers": 5,
                "layer_order": "Top2Bottom",
            },
        )
        _raise_for_status(response.status_code, response.text, "apply_recipe_override")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError(
                "Apply recipe override response was not an object"
            )
        if payload.get("status") != "ok":
            raise QualityCheckError(
                "Apply recipe override response status was not ok"
            )
        if not payload.get("preview_url"):
            raise QualityCheckError(
                "Apply recipe override response did not include preview_url"
            )
        if int(payload.get("override_count", 0)) < 1:
            raise QualityCheckError(
                "Apply recipe override response did not record an override"
            )
    finally:
        _remove_paths(created_cache_paths)


def _execute_region_recipe_workflow(client: Any) -> None:
    selected_materials = _region_requantize_materials_for_client(client)
    created_cache_paths = (
        []
        if _client_uses_dependency_overrides(client)
        else _ensure_region_requantize_solver_cache(selected_materials)
    )
    try:
        preview_payload = _post_material_archive_preview_payload(
            client,
            selected_materials,
            label="region_recipe setup",
        )
        session_id = _extract_session_id(preview_payload, "region_recipe preview")
        click_x, click_y = _select_replace_click(preview_payload)
        detected_region = _post_region_detect(client, session_id, click_x, click_y)
        region_id = detected_region.get("region_id")
        if not isinstance(region_id, str) or not region_id:
            raise QualityCheckError(
                "Region detect response did not include region_id"
            )
        response = client.post(
            "/api/convert/region-recipe",
            json={
                "session_id": session_id,
                "region_ids": [region_id],
                "layer_order": "Top2Bottom",
            },
        )
        _raise_for_status(response.status_code, response.text, "region_recipe")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError("Region recipe response was not an object")
        if payload.get("status") != "ok":
            raise QualityCheckError("Region recipe response status was not ok")
        recipes = payload.get("recipes")
        if not isinstance(recipes, list) or not recipes:
            raise QualityCheckError("Region recipe response did not include recipes")
        first_recipe = recipes[0]
        if not isinstance(first_recipe, Mapping):
            raise QualityCheckError("Region recipe entry was not an object")
        if first_recipe.get("region_id") != region_id:
            raise QualityCheckError("Region recipe response used an unexpected region")
        recipe = first_recipe.get("recipe")
        if not isinstance(recipe, list) or not recipe:
            raise QualityCheckError("Region recipe response recipe was empty")
        if first_recipe.get("layer_order") != "Top2Bottom":
            raise QualityCheckError("Region recipe response layer_order was unexpected")
    finally:
        _remove_paths(created_cache_paths)


def _execute_merge_colors_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="merge_colors setup",
    )
    session_id = _extract_session_id(preview_payload, "merge_colors preview")
    response = client.post(
        "/api/convert/merge-colors",
        json={
            "session_id": session_id,
            "merge_enable": True,
            "merge_threshold": 5.0,
            "merge_max_distance": 20,
        },
    )
    _raise_for_status(response.status_code, response.text, "merge_colors")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Merge colors response was not an object")
    if payload.get("status") != "ok":
        raise QualityCheckError("Merge colors response status was not ok")
    if not payload.get("preview_url"):
        raise QualityCheckError("Merge colors response did not include preview_url")
    if not isinstance(payload.get("colors_before"), int):
        raise QualityCheckError("Merge colors response colors_before was not an int")
    if not isinstance(payload.get("colors_after"), int):
        raise QualityCheckError("Merge colors response colors_after was not an int")
    quality_metric = payload.get("quality_metric")
    if not isinstance(quality_metric, (float, int)) or not 0 <= quality_metric <= 100:
        raise QualityCheckError("Merge colors response quality_metric was invalid")


def _execute_generate_large_format_workflow(client: Any) -> None:
    session_id = _post_preview(client, DEFAULT_LUT_NAME)
    response = client.post(
        "/api/convert/generate-large-format",
        json={
            "session_id": session_id,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 60.0,
                "tile_height_mm": 60.0,
                "params": {
                    "lut_name": DEFAULT_LUT_NAME,
                    "target_width_mm": 60.0,
                    "color_mode": DEFAULT_COLOR_MODE,
                    "modeling_mode": DEFAULT_MODELING_MODE,
                    "enable_fridge_magnet": False,
                    "add_loop": False,
                },
            },
        },
    )
    _raise_for_status(response.status_code, response.text, "generate_large_format")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Large-format response was not an object")
    if payload.get("status") != "ok":
        raise QualityCheckError("Large-format response status was not ok")
    if not payload.get("download_url"):
        raise QualityCheckError("Large-format response did not include download_url")
    if int(payload.get("tile_count", 0)) < 1:
        raise QualityCheckError("Large-format response did not generate any tiles")


def _execute_batch_workflow(client: Any) -> None:
    image_bytes = _synthesize_rgb_png_bytes(32, 32)
    response = client.post(
        "/api/convert/batch",
        files=[("images", ("batch.png", image_bytes, "image/png"))],
        data={
            "lut_name": DEFAULT_LUT_NAME,
            "color_mode": DEFAULT_COLOR_MODE,
            "modeling_mode": DEFAULT_MODELING_MODE,
            "target_width_mm": "60.0",
            "quantize_colors": "48",
            "enable_cleanup": "true",
        },
    )
    _raise_for_status(response.status_code, response.text, "batch")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Batch response was not an object")
    if not payload.get("download_url"):
        raise QualityCheckError("Batch response did not include download_url")
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise QualityCheckError("Batch response did not include item results")
    success_count = sum(
        1
        for item in results
        if isinstance(item, Mapping) and item.get("status") == "success"
    )
    if success_count < 1:
        raise QualityCheckError("Batch response did not include a successful item")


def _execute_batch_merge_3mf_workflow(client: Any) -> None:
    """Run a minimal N=2 batch request to trigger batch_merge_3mf_init + done.

    Uses two small synthetic images so the batch merge path is exercised.
    The merged 3MF and merged preview GLB are produced; we verify the response
    contains both download_url and preview_3d_url.
    """

    # Ensure LUT presets are discovered (needed when running as standalone ad-hoc step).
    response = client.get("/api/lut/list")
    _raise_for_status(response.status_code, response.text, "batch_merge_3mf lut_list")
    lut_name = _select_lut_name(response.json(), fallback=DEFAULT_LUT_NAME)

    image_bytes_a = _synthesize_rgb_png_bytes(32, 32)
    image_bytes_b = _synthesize_rgb_png_bytes(24, 24)
    response = client.post(
        "/api/convert/batch",
        files=[
            ("images", ("merge_a.png", image_bytes_a, "image/png")),
            ("images", ("merge_b.png", image_bytes_b, "image/png")),
        ],
        data={
            "lut_name": lut_name,
            "color_mode": DEFAULT_COLOR_MODE,
            "modeling_mode": DEFAULT_MODELING_MODE,
            "target_width_mm": "60.0",
            "quantize_colors": "48",
            "enable_cleanup": "true",
        },
    )
    _raise_for_status(response.status_code, response.text, "batch_merge_3mf")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Batch merge 3MF response was not an object")
    if not payload.get("download_url"):
        raise QualityCheckError(
            "Batch merge 3MF response did not include download_url"
        )
    if not payload.get("preview_3d_url"):
        raise QualityCheckError(
            "Batch merge 3MF response did not include preview_3d_url"
        )
    results = payload.get("results")
    if not isinstance(results, list) or len(results) < 2:
        raise QualityCheckError(
            "Batch merge 3MF response did not include at least 2 item results"
        )
    success_count = sum(
        1
        for item in results
        if isinstance(item, Mapping) and item.get("status") == "success"
    )
    if success_count < 2:
        raise QualityCheckError(
            "Batch merge 3MF response did not include at least 2 successful items"
        )


def _execute_puzzle_layout_preview_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="puzzle_layout_preview setup",
    )
    session_id = _extract_session_id(preview_payload, "Puzzle layout preview setup")
    response = client.post(
        "/api/convert/puzzle-layout-preview",
        json={
            "session_id": session_id,
            "params": {
                "target_height_mm": 60.0,
                "puzzle_style": "regular",
                "sizing_mode": "grid",
                "rows": 2,
                "cols": 2,
                "target_piece_count": 4,
                "labels_enabled": False,
            },
        },
    )
    _raise_for_status(response.status_code, response.text, "puzzle_layout_preview")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Puzzle layout preview response was not an object")
    if not payload.get("overlay_url"):
        raise QualityCheckError("Puzzle layout preview response did not include overlay_url")
    if int(payload.get("piece_count", 0)) < 1:
        raise QualityCheckError("Puzzle layout preview response did not include pieces")


def _execute_generate_puzzle_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="generate_puzzle setup",
    )
    session_id = _extract_session_id(preview_payload, "Generate puzzle setup")
    response = client.post(
        "/api/convert/generate-puzzle",
        json={
            "session_id": session_id,
            "params": {
                "target_height_mm": 60.0,
                "puzzle_style": "regular",
                "sizing_mode": "grid",
                "rows": 2,
                "cols": 2,
                "target_piece_count": 4,
                "labels_enabled": False,
                "engrave_back_labels": False,
                "params": {
                    "lut_name": DEFAULT_LUT_NAME,
                    "target_width_mm": 60.0,
                    "color_mode": DEFAULT_COLOR_MODE,
                    "modeling_mode": DEFAULT_MODELING_MODE,
                    "enable_fridge_magnet": False,
                    "fridge_magnets": [],
                    "add_loop": False,
                },
            },
        },
    )
    _raise_for_status(response.status_code, response.text, "generate_puzzle")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Generate puzzle response was not an object")
    if not payload.get("download_url"):
        raise QualityCheckError("Generate puzzle response did not include download_url")
    if int(payload.get("piece_count", 0)) < 1:
        raise QualityCheckError("Generate puzzle response did not include pieces")


def _execute_auto_detect_colors_workflow(client: Any) -> None:
    image_bytes = _synthesize_rgb_png_bytes(32, 32)
    response = client.post(
        "/api/convert/auto-detect-colors",
        files={"image": ("auto-detect.png", image_bytes, "image/png")},
        data={"target_width_mm": "60.0"},
    )
    _raise_for_status(response.status_code, response.text, "auto_detect_colors")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Auto-detect colors response was not an object")
    if int(payload.get("recommended", 0)) < 1:
        raise QualityCheckError("Auto-detect colors response recommendation was invalid")
    if int(payload.get("unique_colors", 0)) < 1:
        raise QualityCheckError("Auto-detect colors response did not report colors")


def _execute_cleanup_session_files_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="cleanup_session_files setup",
    )
    session_id = _extract_session_id(preview_payload, "Cleanup session files setup")
    response = client.post(
        "/api/convert/cleanup-session-files",
        json={"session_id": session_id, "keep_file_ids": []},
    )
    _raise_for_status(response.status_code, response.text, "cleanup_session_files")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Cleanup session files response was not an object")
    if payload.get("status") != "success":
        raise QualityCheckError("Cleanup session files response status was not success")
    if int(payload.get("cleaned", -1)) < 0:
        raise QualityCheckError("Cleanup session files response cleaned count was invalid")


def _execute_extract_workflow(client: Any) -> None:
    payload = _post_extract_for_session(client)
    if not payload.get("lut_download_url"):
        raise QualityCheckError("Extract response did not include lut_download_url")


def _execute_extract_single_stage_workflow(client: Any) -> None:
    payload = _post_extract_single_stage_for_session(client)
    if not payload.get("stage_json_url"):
        raise QualityCheckError(
            "Single-stage extract response did not include stage_json_url"
        )


def _execute_fit_stage_a_workflow(client: Any) -> None:
    extract_payload = _post_extract_single_stage_for_session(client)
    session_id = str(extract_payload["session_id"])
    response = client.post(
        "/api/extractor/fit-stage-a",
        data={"session_id": session_id},
    )
    _raise_for_status(response.status_code, response.text, "fit_stage_a")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Stage A fit response was not an object")
    if not payload.get("stage_a_params_url"):
        raise QualityCheckError("Stage A fit response did not include params URL")


def _execute_extract_gradient_card_stage_a_workflow(client: Any) -> None:
    payload = _post_extract_gradient_card_stage_a_for_session(client)
    if not payload.get("stage_a_params_url"):
        raise QualityCheckError(
            "Gradient card Stage A response did not include params URL"
        )
    if not payload.get("white_warp_preview_url"):
        raise QualityCheckError(
            "Gradient card Stage A response did not include white preview URL"
        )
    if not payload.get("black_warp_preview_url"):
        raise QualityCheckError(
            "Gradient card Stage A response did not include black preview URL"
        )


def _execute_save_gradient_card_material_workflow(client: Any) -> None:
    extract_payload = _post_extract_gradient_card_stage_a_for_session(client)
    session_id = str(extract_payload["session_id"])
    saved_directory_name: str | None = None
    try:
        response = client.post(
            "/api/extractor/save-gradient-card-material",
            data={
                "session_id": session_id,
                "material_name": "Stub PLA",
                "save_mode": "merge",
                "brand": "Lumina",
            },
        )
        _raise_for_status(
            response.status_code,
            response.text,
            "save_gradient_card_material",
        )
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError(
                "Gradient card material save response was not an object"
            )
        if not payload.get("material_file_url"):
            raise QualityCheckError(
                "Gradient card material save response did not include material URL"
            )
        material_summary = payload.get("material_summary")
        if isinstance(material_summary, Mapping):
            raw_directory_name = material_summary.get("directory_name")
            if isinstance(raw_directory_name, str):
                saved_directory_name = raw_directory_name
    finally:
        _remove_saved_gradient_card_material_fixture(saved_directory_name)


def _execute_delete_gradient_card_material_workflow(client: Any) -> None:
    directory_name = _create_saved_gradient_card_material_fixture()
    try:
        response = client.delete(
            f"/api/extractor/gradient-card-materials/{directory_name}",
        )
        _raise_for_status(
            response.status_code,
            response.text,
            "delete_gradient_card_material",
        )
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError(
                "Gradient card material delete response was not an object"
            )
        if payload.get("directory_name") != directory_name:
            raise QualityCheckError(
                "Gradient card material delete response used an unexpected directory"
            )
    finally:
        _remove_saved_gradient_card_material_fixture(directory_name)


def _execute_update_gradient_card_material_workflow(client: Any) -> None:
    directory_name = _create_saved_gradient_card_material_fixture()
    try:
        response = client.patch(
            f"/api/extractor/gradient-card-materials/{directory_name}",
            json={
                "material_name": "Renamed Stub PLA",
                "brand": "Lumina",
                "estimated_rgb": [255, 0, 0],
            },
        )
        _raise_for_status(
            response.status_code,
            response.text,
            "update_gradient_card_material",
        )
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError(
                "Gradient card material update response was not an object"
            )
        material = payload.get("material")
        if not isinstance(material, Mapping):
            raise QualityCheckError(
                "Gradient card material update response did not include material"
            )
        if material.get("directory_name") != directory_name:
            raise QualityCheckError(
                "Gradient card material update response used an unexpected directory"
            )
    finally:
        _remove_saved_gradient_card_material_fixture(directory_name)


def _execute_export_gradient_card_materials_workflow(client: Any) -> None:
    response = client.post(
        "/api/extractor/gradient-card-materials/export",
        json={"directory_names": ["stub_material_v1", "stub_material_v2"]},
    )
    _raise_for_status(
        response.status_code,
        response.text,
        "export_gradient_card_materials",
    )
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError(
            "Gradient card material export response was not an object"
        )
    if not payload.get("download_url"):
        raise QualityCheckError(
            "Gradient card material export response did not include download URL"
        )
    if int(payload.get("exported_count", 0)) < 1:
        raise QualityCheckError(
            "Gradient card material export response did not report exports"
        )


def _execute_import_gradient_card_materials_workflow(client: Any) -> None:
    response = client.post(
        "/api/extractor/gradient-card-materials/import",
        files={"archives": ("materials.zip", b"stub zip", "application/zip")},
    )
    _raise_for_status(
        response.status_code,
        response.text,
        "import_gradient_card_materials",
    )
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError(
            "Gradient card material import response was not an object"
        )
    if int(payload.get("imported_count", 0)) < 1:
        raise QualityCheckError(
            "Gradient card material import response did not report imports"
        )


def _material_solver_cache_form_data() -> dict[str, str]:
    return {
        "material_directory_names": json.dumps(
            ["stub_material_v1", "stub_material_v2"]
        ),
        "layer_count": "8",
        "layer_height_mm": "0.04",
        "substrate": "white",
        "grid_resolution": "64",
    }


def _execute_material_solver_cache_status_workflow(client: Any) -> None:
    response = client.post(
        "/api/extractor/material-solver-cache/status",
        data=_material_solver_cache_form_data(),
    )
    _raise_for_status(
        response.status_code,
        response.text,
        "material_solver_cache_status",
    )
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Material solver cache status response was not an object")
    if payload.get("cached") is not True:
        raise QualityCheckError("Material solver cache status response was not cached")


def _execute_material_solver_cache_build_workflow(client: Any) -> None:
    response = client.post(
        "/api/extractor/material-solver-cache/build",
        data=_material_solver_cache_form_data(),
    )
    _raise_for_status(
        response.status_code,
        response.text,
        "material_solver_cache_build",
    )
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Material solver cache build response was not an object")
    entry = payload.get("entry")
    if not isinstance(entry, Mapping):
        raise QualityCheckError("Material solver cache build response missed entry")
    if int(entry.get("valid_cell_count", 0)) < 1:
        raise QualityCheckError(
            "Material solver cache build response did not report valid cells"
        )


def _execute_material_solver_cache_delete_workflow(client: Any) -> None:
    response = client.post(
        "/api/extractor/material-solver-cache/delete",
        data=_material_solver_cache_form_data(),
    )
    _raise_for_status(
        response.status_code,
        response.text,
        "material_solver_cache_delete",
    )
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Material solver cache delete response was not an object")
    if payload.get("deleted") is not True:
        raise QualityCheckError("Material solver cache delete response was not deleted")


def _execute_material_solver_cache_suggest_colors_workflow(client: Any) -> None:
    data = _material_solver_cache_form_data()
    data.update(
        {
            "target_hex": "#ff0000",
            "top_k": "3",
            "min_spacing": "1.0",
            "max_combinations": "100000",
        }
    )
    response = client.post(
        "/api/extractor/material-solver-cache/suggest-colors",
        data=data,
    )
    _raise_for_status(
        response.status_code,
        response.text,
        "material_solver_cache_suggest_colors",
    )
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError(
            "Material solver cache suggest-colors response was not an object"
        )
    if payload.get("source") != "cache":
        raise QualityCheckError(
            "Material solver cache suggest-colors response did not use cache"
        )
    suggestions = payload.get("suggestions")
    if not isinstance(suggestions, list) or not suggestions:
        raise QualityCheckError(
            "Material solver cache suggest-colors response missed suggestions"
        )


def _execute_calibration_generate_workflow(client: Any) -> None:
    response = client.post(
        "/api/calibration/generate",
        json={
            "color_mode": DEFAULT_COLOR_MODE,
            "block_size": 5,
            "gap": 0.84,
            "backing": "White",
        },
    )
    _raise_for_status(response.status_code, response.text, "calibration_generate")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Calibration generate response was not an object")
    if payload.get("status") != "ok":
        raise QualityCheckError("Calibration generate response status was not ok")
    if not payload.get("download_url"):
        raise QualityCheckError("Calibration generate response missed download URL")
    if not payload.get("preview_url"):
        raise QualityCheckError("Calibration generate response missed preview URL")


def _execute_calibration_generate_single_stage_kit_workflow(client: Any) -> None:
    response = client.post(
        "/api/calibration/generate-single-stage-kit",
        json={
            "palette": [
                {
                    "color": "White",
                    "material": "PLA Basic",
                    "hex_color": "#FFFFFF",
                    "color_name": "White",
                }
            ],
            "substrate_id": "white",
            "substrate_display_name": "White",
            "material_default": "PLA Basic",
            "layer_height_mm": 0.04,
        },
    )
    _raise_for_status(
        response.status_code,
        response.text,
        "calibration_generate_single_stage_kit",
    )
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Single-stage kit response was not an object")
    if payload.get("status") != "ok":
        raise QualityCheckError("Single-stage kit response status was not ok")
    if not payload.get("kit_download_url"):
        raise QualityCheckError("Single-stage kit response missed kit URL")
    if not payload.get("manifest_url"):
        raise QualityCheckError("Single-stage kit response missed manifest URL")
    if not payload.get("preview_url"):
        raise QualityCheckError("Single-stage kit response missed preview URL")
    if int(len(payload.get("jobs") or [])) < 1:
        raise QualityCheckError("Single-stage kit response missed jobs")


def _execute_five_color_query_workflow(client: Any) -> None:
    response = client.post(
        "/api/five-color/query",
        json={
            "lut_name": FIVE_COLOR_EXT_LUT_NAME,
            "selected_indices": [0, 1, 2, 3, 4],
        },
    )
    _raise_for_status(response.status_code, response.text, "five_color_query")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Five-color query response was not an object")
    if payload.get("found") is not True:
        raise QualityCheckError("Five-color query response was not found")
    result_hex = payload.get("result_hex")
    if not isinstance(result_hex, str) or not re.fullmatch(
        r"#[0-9a-fA-F]{6}",
        result_hex,
    ):
        raise QualityCheckError("Five-color query response missed result hex")


def _execute_five_color_generate_swatch_workflow(client: Any) -> None:
    response = client.post(
        "/api/five-color/generate-swatch",
        json={
            "lut_name": FIVE_COLOR_EXT_LUT_NAME,
            "recipes": [
                {
                    "selected_indices": [0, 1, 2, 3, 4],
                    "result_hex": "#010203",
                    "base_color_names": [],
                    "base_color_hexes": [],
                }
            ],
            "block_size_mm": 12.5,
            "gap_mm": 1.5,
            "cols": 2,
        },
    )
    _raise_for_status(
        response.status_code,
        response.text,
        "five_color_generate_swatch",
    )
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Five-color swatch response was not an object")
    if payload.get("status") != "ok":
        raise QualityCheckError("Five-color swatch response status was not ok")
    if not payload.get("download_url"):
        raise QualityCheckError("Five-color swatch response missed download URL")
    if not payload.get("preview_url"):
        raise QualityCheckError("Five-color swatch response missed preview URL")
    if int(payload.get("recipe_count", 0)) < 1:
        raise QualityCheckError("Five-color swatch response missed recipe count")


def _execute_five_color_base_colors_workflow(client: Any) -> None:
    response = client.get(
        "/api/five-color/base-colors",
        params={"lut_name": FIVE_COLOR_EXT_LUT_NAME},
    )
    _raise_for_status(response.status_code, response.text, "five_color_base_colors")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Five-color base-colors response was not an object")
    if int(payload.get("color_count", 0)) < 1:
        raise QualityCheckError("Five-color base-colors response missed colors")
    combinations = payload.get("combinations")
    if not isinstance(combinations, list) or not combinations:
        raise QualityCheckError("Five-color base-colors response missed combinations")


def _execute_vectorize_image_workflow(client: Any) -> None:
    response = client.post(
        "/api/vectorize",
        files={
            "image": (
                "vectorize.png",
                _synthesize_rgb_png_bytes(4, 4),
                "image/png",
            )
        },
        data={"params": "{}"},
    )
    _raise_for_status(response.status_code, response.text, "vectorize_image")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Vectorize image response was not an object")
    if not payload.get("svg_url"):
        raise QualityCheckError("Vectorize image response missed SVG URL")
    if int(payload.get("num_shapes", 0)) < 1:
        raise QualityCheckError("Vectorize image response missed shapes")
    if int(payload.get("num_colors", 0)) < 1:
        raise QualityCheckError("Vectorize image response missed colors")
    palette = payload.get("palette")
    if not isinstance(palette, list) or len(palette) < 1:
        raise QualityCheckError("Vectorize image response missed palette")


def _execute_lut_merge_workflow(client: Any) -> None:
    response = client.post(
        "/api/lut/merge",
        json={
            "primary_name": EIGHT_COLOR_LUT_NAME,
            "secondary_names": [DEFAULT_LUT_NAME],
            "dedup_threshold": 0.0,
        },
    )
    _raise_for_status(response.status_code, response.text, "lut_merge")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("LUT merge response was not an object")
    if payload.get("status") != "success":
        raise QualityCheckError("LUT merge response status was not success")
    if not payload.get("filename"):
        raise QualityCheckError("LUT merge response missed filename")

    try:
        from utils.lut_manager import LUTManager

        merged_path = LUTManager.get_lut_path(str(payload["filename"]))
        if isinstance(merged_path, str):
            _remove_paths([Path(merged_path)])
    except Exception:
        pass


def _execute_lut_compare_workflow(client: Any) -> None:
    response = client.post(
        "/api/lut/compare",
        json={
            "lut_a_name": DEFAULT_LUT_NAME,
            "lut_b_name": EIGHT_COLOR_LUT_NAME,
            "top_n": 5,
        },
    )
    _raise_for_status(response.status_code, response.text, "lut_compare")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("LUT compare response was not an object")
    if payload.get("status") != "success":
        raise QualityCheckError("LUT compare response status was not success")
    if not isinstance(payload.get("stats"), Mapping):
        raise QualityCheckError("LUT compare response missed stats")


def _resolve_lut_details_catalog_name(client: Any) -> str:
    """Resolve a LUT catalog name accepted by the details service.

    The details service catalog uses 'manufacturer - material_type - color_count - stem'
    keys, distinct from LUTManager's 'manufacturer - stem' display names. Discover
    a usable name by matching DEFAULT_LUT_STEM suffix; fall back to the first item.
    """

    response = client.get("/api/lut/details/catalog")
    _raise_for_status(response.status_code, response.text, "lut_details")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("LUT details catalog response was not an object")
    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise QualityCheckError("LUT details catalog response missed groups")
    fallback: str | None = None
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        items = group.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            if fallback is None:
                fallback = name
            if name.endswith(DEFAULT_LUT_STEM):
                return name
    if fallback is None:
        raise QualityCheckError("LUT details catalog response had no items")
    return fallback


def _execute_lut_details_workflow(client: Any) -> None:
    catalog_name = _resolve_lut_details_catalog_name(client)
    response = client.get(f"/api/lut/{quote(catalog_name, safe='')}/details")
    _raise_for_status(response.status_code, response.text, "lut_details")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("LUT details response was not an object")
    if int(payload.get("color_count", 0)) < 1:
        raise QualityCheckError("LUT details response missed colors")
    if not isinstance(payload.get("coverage_stats"), Mapping):
        raise QualityCheckError("LUT details response missed coverage stats")


def _execute_lut_upload_workflow(client: Any) -> None:
    payload_bytes = _synthesize_keyed_json_lut_bytes()
    response = client.post(
        "/api/lut/upload",
        files={"file": ("synthetic_lut.json", payload_bytes, "application/json")},
    )
    _raise_for_status(response.status_code, response.text, "lut_upload")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("LUT upload response was not an object")
    if payload.get("status") != "ok":
        raise QualityCheckError("LUT upload response status was not ok")
    if not payload.get("name"):
        raise QualityCheckError("LUT upload response missed name")

    try:
        from utils.lut_manager import LUTManager

        uploaded_path = LUTManager.get_lut_path(str(payload["name"]))
        if isinstance(uploaded_path, str):
            _remove_paths([Path(uploaded_path)])
    except Exception:
        pass


def _execute_lut_session_info_workflow(client: Any) -> None:
    preview_payload = _post_vector_preview_payload(
        client,
        DEFAULT_LUT_NAME,
        color_mode=DEFAULT_COLOR_MODE,
        label="lut_session_info setup",
    )
    session_id = _extract_session_id(preview_payload, "lut_session_info preview")
    response = client.get(f"/api/lut/session/{session_id}/info")
    _raise_for_status(response.status_code, response.text, "lut_session_info")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Session LUT info response was not an object")
    if int(payload.get("color_count", 0)) < 1:
        raise QualityCheckError("Session LUT info response missed colors")
    if not isinstance(payload.get("palette"), list):
        raise QualityCheckError("Session LUT info response missed palette")


def _execute_system_image_preview_workflow(client: Any) -> None:
    image_bytes = _synthesize_rgb_png_bytes(64, 64)
    response = client.post(
        "/api/system/image-preview",
        files={"file": ("preview_input.png", image_bytes, "image/png")},
    )
    _raise_for_status(response.status_code, response.text, "system_image_preview")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Image preview response was not an object")
    if not isinstance(payload.get("preview_url"), str):
        raise QualityCheckError("Image preview response missed preview_url")
    if int(payload.get("width", 0)) <= 0 or int(payload.get("height", 0)) <= 0:
        raise QualityCheckError("Image preview response had invalid dimensions")


def _execute_system_save_settings_workflow(client: Any) -> None:
    get_response = client.get("/api/system/settings")
    _raise_for_status(
        get_response.status_code,
        get_response.text,
        "system_save_settings",
    )
    get_payload = get_response.json()
    if not isinstance(get_payload, Mapping) or not isinstance(
        get_payload.get("settings"),
        Mapping,
    ):
        raise QualityCheckError("Settings GET response was not an object")
    settings_payload = dict(get_payload["settings"])

    settings_path = Path("user_settings.json")
    backup = settings_path.read_text(encoding="utf-8") if settings_path.exists() else None
    try:
        post_response = client.post("/api/system/settings", json=settings_payload)
        _raise_for_status(
            post_response.status_code,
            post_response.text,
            "system_save_settings",
        )
        post_payload = post_response.json()
        if not isinstance(post_payload, Mapping) or post_payload.get("status") != "success":
            raise QualityCheckError("Settings POST did not return success")
    finally:
        if backup is not None:
            settings_path.write_text(backup, encoding="utf-8")
        elif settings_path.exists():
            try:
                settings_path.unlink()
            except OSError:
                pass


def _execute_feedback_submit_workflow(client: Any) -> None:
    payload = {
        "description": "log_quality_check synthetic report",
        "user_email": None,
        "context": {
            "url": "http://localhost:5174/",
            "user_agent": "log-quality-check",
            "screen_width": 1920,
            "screen_height": 1080,
            "device_pixel_ratio": 1.0,
            "app_version": "test",
            "language": "en",
            "theme": "light",
            "active_tab": "converter",
            "active_session_ids": {"converter": None, "single_stage": None},
            "color_mode": None,
            "lut_name": None,
            "recent_client_logs": [],
        },
        "screenshot_data_url": None,
    }
    response = client.post("/api/feedback/bug-report", json=payload)
    _raise_for_status(response.status_code, response.text, "feedback_submit")
    response_payload = response.json()
    if not isinstance(response_payload, Mapping):
        raise QualityCheckError("feedback_submit response was not an object")
    if not response_payload.get("ticket_id"):
        raise QualityCheckError("feedback_submit response missed ticket_id")
    if response_payload.get("emailed") is not False:
        raise QualityCheckError("feedback_submit response expected emailed=false")


def _execute_slicer_launch_workflow(client: Any) -> None:
    from unittest.mock import patch

    from config import TEMP_DIR
    from core.slicer import DetectedSlicer

    with tempfile.NamedTemporaryFile(
        suffix=".3mf",
        dir=TEMP_DIR,
        delete=False,
    ) as src_handle:
        src_handle.write(b"placeholder-3mf")
        src_path = src_handle.name
    try:
        fake_slicer = DetectedSlicer(
            id="bambu-studio",
            display_name="Bambu Studio",
            exe_path="C:/fake/BambuStudio.exe",
        )
        with patch(
            "api.routers.slicer.detect_installed_slicers",
            return_value=[fake_slicer],
        ), patch(
            "api.routers.slicer.launch_slicer",
            return_value=(True, "launched"),
        ):
            response = client.post(
                "/api/slicer/launch",
                json={"slicer_id": "bambu-studio", "file_path": src_path},
            )
            _raise_for_status(response.status_code, response.text, "slicer_launch")
            payload = response.json()
            if not isinstance(payload, Mapping) or payload.get("status") != "success":
                raise QualityCheckError("Slicer launch response was not success")
    finally:
        try:
            os.unlink(src_path)
        except OSError:
            pass


def _post_extract_gradient_card_stage_a_for_session(client: Any) -> Mapping[str, Any]:
    response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        files={
            "white_image": ("white.png", _synthesize_rgb_png_bytes(16, 16), "image/png"),
            "black_image": ("black.png", _synthesize_rgb_png_bytes(16, 16), "image/png"),
            "dataset_zip": (
                "kit.zip",
                _synthesize_gradient_card_kit_zip_bytes(),
                "application/zip",
            ),
        },
        data={
            "white_corner_points": "[[0,0],[15,0],[15,15],[0,15]]",
            "black_corner_points": "[[0,0],[15,0],[15,15],[0,15]]",
            "manual_white_orientation": "rotate_90_cw",
            "manual_black_orientation": "auto",
        },
    )
    _raise_for_status(
        response.status_code,
        response.text,
        "extract_gradient_card_stage_a",
    )
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Gradient card Stage A response was not an object")
    if not payload.get("session_id"):
        raise QualityCheckError(
            "Gradient card Stage A response did not include session_id"
        )
    return payload


def _post_extract_single_stage_for_session(client: Any) -> Mapping[str, Any]:
    response = client.post(
        "/api/extractor/extract-single-stage",
        files={
            "dataset_zip": (
                "single_stage_dataset.zip",
                _synthesize_single_stage_dataset_zip_bytes(),
                "application/zip",
            )
        },
    )
    _raise_for_status(response.status_code, response.text, "extract_single_stage")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Single-stage extract response was not an object")
    if not payload.get("session_id"):
        raise QualityCheckError(
            "Single-stage extract response did not include session_id"
        )
    return payload


def _post_extract_for_session(client: Any) -> Mapping[str, Any]:
    from io import BytesIO

    import numpy as np
    from PIL import Image

    image = np.zeros((100, 100, 3), dtype=np.uint8)
    image[:50, :50] = [255, 255, 255]
    image[:50, 50:] = [255, 0, 0]
    image[50:, :50] = [255, 255, 0]
    image[50:, 50:] = [0, 0, 255]
    buffer = BytesIO()
    Image.fromarray(image, mode="RGB").save(buffer, format="PNG")
    buffer.seek(0)

    response = client.post(
        "/api/extractor/extract",
        files={"image": ("extract.png", buffer, "image/png")},
        data={
            "corner_points": "[[5,5],[95,5],[95,95],[5,95]]",
            "color_mode": DEFAULT_COLOR_MODE,
            "page": "0",
            "eight_color_full_export": "false",
            "offset_x": "0",
            "offset_y": "0",
            "zoom": "1.0",
            "distortion": "0",
            "vignette_correction": "false",
            "auto_wb": "false",
        },
    )
    _raise_for_status(response.status_code, response.text, "extract")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Extract response was not an object")
    if not payload.get("session_id"):
        raise QualityCheckError("Extract response did not include session_id")
    return payload


def _execute_merge_8color_workflow(client: Any) -> None:
    from api.routers.extractor import _get_8color_temp_path, _get_assets_dir

    import numpy as np

    assets_dir = _get_assets_dir()
    Path(assets_dir).mkdir(parents=True, exist_ok=True)
    page_paths = [
        Path(_get_8color_temp_path(assets_dir, page_number, False))
        for page_number in (1, 2)
    ]
    previous_contents = {path: path.read_bytes() for path in page_paths if path.exists()}
    stacks = np.array(
        [[0, 1, 2, 3, 4, 5, 6, 7], [7, 6, 5, 4, 3, 2, 1, 0]],
        dtype=np.int32,
    )

    try:
        for page_index, page_path in enumerate(page_paths):
            rgb = np.array(
                [
                    [255, 255, 255],
                    [255, 0, 0] if page_index == 0 else [0, 128, 255],
                ],
                dtype=np.uint8,
            )
            _synthesize_lut_keyed_json(
                page_path,
                rgb=rgb,
                stacks=stacks,
                color_mode=EIGHT_COLOR_MODE,
            )

        response = client.post(
            "/api/extractor/merge-8color",
            json={"eight_color_full_export": False},
        )
        _raise_for_status(response.status_code, response.text, "merge_8color")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError("8-Color merge response was not an object")
        if payload.get("status") != "ok":
            raise QualityCheckError("8-Color merge response status was not ok")
        if not payload.get("session_id"):
            raise QualityCheckError("8-Color merge response did not include session_id")
    finally:
        for page_path in page_paths:
            if page_path in previous_contents:
                page_path.write_bytes(previous_contents[page_path])
            else:
                _remove_paths([page_path])


def _execute_merge_5color_ext_workflow(client: Any) -> None:
    import numpy as np

    if getattr(sys, "frozen", False):
        assets_dir = Path(os.path.join(os.getcwd(), "assets"))
    else:
        assets_dir = Path("assets")
    assets_dir.mkdir(parents=True, exist_ok=True)
    page_paths = [
        assets_dir / "temp_5c_ext_page_1.json",
        assets_dir / "temp_5c_ext_page_2.json",
    ]
    previous_contents = {path: path.read_bytes() for path in page_paths if path.exists()}
    stacks = np.array(
        [[0, 1, 2, 3, 4], [4, 3, 2, 1, 0]],
        dtype=np.int32,
    )

    try:
        for page_index, page_path in enumerate(page_paths):
            rgb = np.array(
                [
                    [255, 255, 255],
                    [255, 0, 0] if page_index == 0 else [0, 0, 0],
                ],
                dtype=np.uint8,
            )
            _synthesize_lut_keyed_json(
                page_path,
                rgb=rgb,
                stacks=stacks,
                color_mode=FIVE_COLOR_EXT_MODE,
            )

        response = client.post("/api/extractor/merge-5color-extended", json={})
        _raise_for_status(response.status_code, response.text, "merge_5color_ext")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError("5-Color Extended merge response was not an object")
        if payload.get("status") != "ok":
            raise QualityCheckError("5-Color Extended merge response status was not ok")
        if not payload.get("session_id"):
            raise QualityCheckError(
                "5-Color Extended merge response did not include session_id"
            )
    finally:
        for page_path in page_paths:
            if page_path in previous_contents:
                page_path.write_bytes(previous_contents[page_path])
            else:
                _remove_paths([page_path])


def _execute_manual_fix_workflow(client: Any) -> None:
    import numpy as np

    temp_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    temp_file.close()
    lut_path = Path(temp_file.name)
    rgb = np.array(
        [
            [255, 255, 255],
            [255, 255, 0],
            [0, 128, 255],
            [0, 0, 0],
        ],
        dtype=np.uint8,
    )
    stacks = np.zeros((4, 0), dtype=np.int32)

    try:
        _synthesize_lut_keyed_json(
            lut_path,
            rgb=rgb,
            stacks=stacks,
            color_mode=DEFAULT_COLOR_MODE,
        )
        response = client.post(
            "/api/extractor/manual-fix",
            json={
                "lut_path": str(lut_path),
                "cell_coord": [0, 0],
                "override_color": "#ff0000",
            },
        )
        _raise_for_status(response.status_code, response.text, "manual_fix")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError("Manual fix response was not an object")
        if payload.get("status") != "ok":
            raise QualityCheckError("Manual fix response status was not ok")
        if not payload.get("lut_preview_url"):
            raise QualityCheckError("Manual fix response did not include lut_preview_url")
    finally:
        _remove_paths([lut_path])


def _execute_preview_wb_workflow(client: Any) -> None:
    image_bytes = _synthesize_rgb_png_bytes(32, 32)
    response = client.post(
        "/api/extractor/preview-wb",
        files={"image": ("preview-wb.png", image_bytes, "image/png")},
    )
    _raise_for_status(response.status_code, response.text, "preview_wb")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("White-balance preview response was not an object")
    if not payload.get("preview_url"):
        raise QualityCheckError("White-balance preview response did not include preview_url")
    if int(payload.get("width", 0)) < 1 or int(payload.get("height", 0)) < 1:
        raise QualityCheckError("White-balance preview response dimensions were invalid")


def _execute_rotate_workflow(client: Any) -> None:
    image_bytes = _synthesize_rgb_png_bytes(32, 16)
    response = client.post(
        "/api/extractor/rotate?direction=ccw",
        files={"image": ("rotate.png", image_bytes, "image/png")},
    )
    _raise_for_status(response.status_code, response.text, "rotate")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Rotate response was not an object")
    if not payload.get("preview_url"):
        raise QualityCheckError("Rotate response did not include preview_url")
    if int(payload.get("width", 0)) != 16 or int(payload.get("height", 0)) != 32:
        raise QualityCheckError("Rotate response dimensions did not match 16x32")


def _execute_confirm_palette_workflow(client: Any) -> None:
    extract_payload = _post_extract_for_session(client)
    session_id = _extract_session_id(extract_payload, "Extract")
    response = client.post(
        "/api/extractor/confirm-palette",
        json={
            "session_id": session_id,
            "manufacturer": "TestMfg",
            "type": "PLA",
            "palette": [
                {
                    "color": "Red",
                    "material": "PLA Basic",
                    "hex_color": "#ff0000",
                    "color_name": "Red",
                },
                {
                    "color": "White",
                    "material": "PLA Basic",
                    "hex_color": "#ffffff",
                    "color_name": "White",
                },
            ],
        },
    )
    _raise_for_status(response.status_code, response.text, "confirm_palette")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Palette confirmation response was not an object")
    if payload.get("status") not in ("ok", "warning"):
        raise QualityCheckError("Palette confirmation response status was not ok or warning")


def _post_preview(client: Any, lut_name: str) -> str:
    _require_fixture(FIXTURE_IMAGE)
    with FIXTURE_IMAGE.open("rb") as handle:
        response = client.post(
            "/api/convert/preview",
            files={"image": ("logo.png", handle, "image/png")},
            data=_preview_form_data(lut_name),
        )
    _raise_for_status(response.status_code, response.text, "preview")
    return _extract_session_id(response.json(), "Preview")


def _post_vector_preview(
    client: Any,
    lut_name: str,
    *,
    color_mode: str = DEFAULT_COLOR_MODE,
) -> str:
    return _extract_session_id(
        _post_vector_preview_payload(client, lut_name, color_mode=color_mode),
        "Vector preview",
    )


def _post_vector_preview_payload(
    client: Any,
    lut_name: str,
    *,
    color_mode: str = DEFAULT_COLOR_MODE,
    label: str = "vector preview",
) -> Mapping[str, Any]:
    _require_fixture(VECTOR_FIXTURE_IMAGE)
    with VECTOR_FIXTURE_IMAGE.open("rb") as handle:
        response = client.post(
            "/api/convert/preview",
            files={"image": (VECTOR_FIXTURE_IMAGE.name, handle, "image/svg+xml")},
            data=_preview_form_data(
                lut_name,
                color_mode=color_mode,
                modeling_mode=VECTOR_MODELING_MODE,
            ),
        )
    _raise_for_status(response.status_code, response.text, label)
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Vector preview response was not an object")
    return payload


def _post_material_archive_preview_payload(
    client: Any,
    selected_materials: Sequence[str],
    *,
    label: str,
) -> Mapping[str, Any]:
    import io

    import numpy as np
    from PIL import Image

    image = np.zeros((32, 32, 3), dtype=np.uint8)
    image[:, :16, :] = [255, 255, 255]
    image[:, 16:, :] = [255, 0, 0]
    buffer = io.BytesIO()
    Image.fromarray(image, mode="RGB").save(buffer, format="PNG")
    image_bytes = buffer.getvalue()
    response = client.post(
        "/api/convert/preview",
        files={"image": ("region-requantize.png", image_bytes, "image/png")},
        data={
            **_preview_form_data(DEFAULT_LUT_NAME),
            "material_source": "material_archive",
            "selected_materials": json.dumps(list(selected_materials)),
            "material_layer_count": "5",
            "material_layer_height_mm": "0.08",
            "material_grid_resolution": "8",
        },
    )
    _raise_for_status(response.status_code, response.text, label)
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Material archive preview response was not an object")
    return payload


def _extract_session_id(payload: Mapping[str, Any], label: str) -> str:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise QualityCheckError(f"{label} response did not include session_id")
    return session_id


def _select_replace_click(preview_payload: Mapping[str, Any]) -> tuple[int, int]:
    dimensions = preview_payload.get("dimensions")
    width = (
        int(dimensions.get("width", 10))
        if isinstance(dimensions, Mapping)
        else 10
    )
    height = (
        int(dimensions.get("height", 10))
        if isinstance(dimensions, Mapping)
        else 10
    )
    if width <= 0 or height <= 0:
        raise QualityCheckError("Vector preview did not include positive dimensions")

    # For ring_with_hole.svg the one-quarter-width point can land just
    # outside the rasterized fill after scaling; one-third width at
    # mid-height lands in the filled band in the real 600x600 preview.
    return max(0, width // 3), max(0, height // 2)


def _post_region_detect(
    client: Any,
    session_id: str,
    x: int,
    y: int,
) -> Mapping[str, Any]:
    response = client.post(
        "/api/convert/region-detect",
        json={"session_id": session_id, "x": x, "y": y},
    )
    _raise_for_status(response.status_code, response.text, "region detect")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Region detect response was not an object")
    if int(payload.get("pixel_count", 0)) <= 0:
        raise QualityCheckError("Region detect returned no pixels")
    return payload


def _choose_replacement_color(region_payload: Mapping[str, Any]) -> str:
    current_color = str(region_payload.get("color_hex") or "").lower()
    for candidate in REPLACE_COLOR_CANDIDATES:
        if candidate.lower() != current_color:
            return candidate
    raise QualityCheckError("No replacement color differed from detected region color")


def _first_palette_hex(payload: Mapping[str, Any], *, fallback: str) -> str:
    palette = payload.get("palette")
    if isinstance(palette, list):
        for item in palette:
            if not isinstance(item, Mapping):
                continue
            value = item.get("hex")
            if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                return value
    return fallback


def _client_uses_dependency_overrides(client: Any) -> bool:
    app = getattr(client, "app", None)
    overrides = getattr(app, "dependency_overrides", None)
    return isinstance(overrides, dict) and bool(overrides)


def _region_requantize_materials_for_client(client: Any) -> list[str]:
    if _client_uses_dependency_overrides(client):
        return ["fake/A", "fake/B"]
    return _discover_material_archive_workflow_materials(limit=2)


def _discover_material_archive_workflow_materials(*, limit: int) -> list[str]:
    materials_root = REPO_ROOT / "materials"
    candidates = sorted(materials_root.glob("*/*/material.json"))
    material_names = [
        path.parent.relative_to(materials_root).as_posix()
        for path in candidates
    ]
    if len(material_names) < limit:
        raise QualityCheckError(
            f"Need at least {limit} material archives for region_requantize"
        )
    return material_names[:limit]


def _ensure_region_requantize_solver_cache(
    selected_materials: Sequence[str],
) -> list[Path]:
    try:
        from core.material_cache import (
            build_material_solver_cache,
            cache_file_path,
            save_material_solver_cache,
        )
        from core.material_lut_synthesis import load_multiple_materials
    except ImportError as exc:
        raise QualityCheckError(f"Failed to import material cache helpers: {exc}") from exc

    materials = load_multiple_materials(list(selected_materials))
    npz_path = cache_file_path(
        materials,
        5,
        0.08,
        "white",
        grid_resolution=8,
    )
    meta_path = npz_path.with_name(npz_path.stem + ".meta.json")
    if npz_path.exists() and meta_path.exists():
        return []

    cache = build_material_solver_cache(
        materials,
        5,
        0.08,
        "white",
        grid_resolution=8,
    )
    saved_path = save_material_solver_cache(cache)
    saved_meta_path = saved_path.with_name(saved_path.stem + ".meta.json")
    return [saved_path, saved_meta_path]


def _seed_region_requantize_test_session_if_available(
    client: Any,
    session_id: str,
) -> None:
    app = getattr(client, "app", None)
    overrides = getattr(app, "dependency_overrides", None)
    if not isinstance(overrides, dict):
        return
    try:
        from api.dependencies import get_session_store
    except ImportError:
        return
    store_factory = overrides.get(get_session_store)
    if store_factory is None:
        return
    store = store_factory()
    session_data = store.get(session_id)
    if not isinstance(session_data, dict):
        return
    cache = session_data.get("preview_cache")
    if not isinstance(cache, dict) or "matched_rgb" not in cache:
        return

    import numpy as np

    matched_rgb = np.asarray(cache["matched_rgb"])
    height, width = matched_rgb.shape[:2]
    region_id_map = np.zeros((height, width), dtype=np.uint32)
    y0, y1 = height // 4, max(height // 4 + 1, 3 * height // 4)
    x0, x1 = width // 4, max(width // 4 + 1, 3 * width // 4)
    region_id_map[y0:y1, x0:x1] = np.uint32(1001)
    store.put(session_id, "gradient_region_id_map", region_id_map)
    store.put(session_id, "material_source", "material_archive")
    store.put(session_id, "selected_materials", ["fake/A", "fake/B"])
    store.put(session_id, "material_layer_count", 5)
    store.put(session_id, "material_layer_height_mm", 0.08)
    store.put(session_id, "material_grid_resolution", 8)
    store.put(session_id, "lut_name", "__material_archive__")


def _post_replace_color(
    client: Any,
    session_id: str,
    selected_color: str,
    replacement_color: str,
    *,
    label: str,
) -> Mapping[str, Any]:
    response = client.post(
        "/api/convert/replace-color",
        json={
            "session_id": session_id,
            "selected_color": selected_color,
            "replacement_color": replacement_color,
        },
    )
    _raise_for_status(response.status_code, response.text, label)
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Replace color response was not an object")
    return payload


def _post_region_replace(
    client: Any,
    session_id: str,
    replacement_color: str,
) -> None:
    response = client.post(
        "/api/convert/region-replace",
        json={"session_id": session_id, "replacement_color": replacement_color},
    )
    _raise_for_status(response.status_code, response.text, "region replace")


def _wait_for_async_glb(client: Any, session_id: str) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        response = client.get(f"/api/convert/glb-status/{session_id}")
        _raise_for_status(response.status_code, response.text, "glb status")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise QualityCheckError("GLB status response was not an object")
        if payload.get("status") in {"idle", "ready", "error"}:
            return
        time.sleep(0.1)
    raise QualityCheckError("Timed out waiting for async GLB build to settle")


def _post_generate(client: Any, session_id: str, lut_name: str) -> None:
    response = client.post(
        "/api/convert/generate",
        json=_generate_payload(session_id, lut_name),
    )
    _raise_for_status(response.status_code, response.text, "generate")


def _post_vector_generate(
    client: Any,
    session_id: str,
    lut_name: str,
    *,
    color_mode: str = DEFAULT_COLOR_MODE,
    label: str = "vector generate",
    use_cached_matched_rgb: bool = False,
) -> None:
    response = client.post(
        "/api/convert/generate",
        json=_generate_payload(
            session_id,
            lut_name,
            color_mode=color_mode,
            modeling_mode=VECTOR_MODELING_MODE,
            use_cached_matched_rgb=use_cached_matched_rgb,
        ),
    )
    _raise_for_status(response.status_code, response.text, label)


def _preview_form_data(
    lut_name: str,
    *,
    color_mode: str = DEFAULT_COLOR_MODE,
    modeling_mode: str = DEFAULT_MODELING_MODE,
) -> dict[str, str]:
    return {
        "source_kind": "legacy_single",
        "lut_name": lut_name,
        "color_mode": color_mode,
        "modeling_mode": modeling_mode,
        "target_width_mm": "60.0",
        "auto_bg": "false",
        "bg_tol": "40",
        "quantize_colors": "48",
        "enable_cleanup": "true",
    }


def _generate_payload(
    session_id: str,
    lut_name: str,
    *,
    color_mode: str = DEFAULT_COLOR_MODE,
    modeling_mode: str = DEFAULT_MODELING_MODE,
    use_cached_matched_rgb: bool = False,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "params": {
            "source_kind": "legacy_single",
            "lut_name": lut_name,
            "color_mode": color_mode,
            "modeling_mode": modeling_mode,
            "target_width_mm": 60.0,
            "auto_bg": False,
            "bg_tol": 40,
            "quantize_colors": 48,
            "enable_cleanup": True,
            "use_cached_matched_rgb": use_cached_matched_rgb,
        },
    }


def _require_fixture(path: Path) -> None:
    if not path.is_file():
        raise QualityCheckError(f"Fixture image missing: {path}")


def _raise_for_status(status_code: int, text: str, label: str) -> None:
    if status_code >= 400:
        snippet = text[:800].replace("\n", "\\n")
        raise QualityCheckError(f"{label} request failed: HTTP {status_code}: {snippet}")


def _select_lut_name(payload: Mapping[str, Any], *, fallback: str) -> str:
    entries = payload.get("luts")
    if not isinstance(entries, list):
        return fallback
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if isinstance(name, str) and DEFAULT_LUT_STEM in name:
            return name
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        color_mode = item.get("color_mode")
        if isinstance(name, str) and color_mode == DEFAULT_COLOR_MODE:
            return name
    return fallback


def _lut_colors_path(lut_name: str) -> str:
    return f"/api/lut/{quote(lut_name, safe='')}/colors"


def _wait_for_server(
    base_url: str,
    timeout: float,
    proc: subprocess.Popen[Any],
) -> None:
    import httpx

    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise QualityCheckError(
                f"Server process exited before becoming ready, code={proc.returncode}"
            )
        try:
            response = httpx.get(f"{base_url}/api/health", timeout=2.0)
            if response.status_code < 500:
                return
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    raise QualityCheckError(
        f"Server at {base_url} did not start within {timeout}s"
        + (f" (last error: {last_error})" if last_error else "")
    )


def _terminate_server_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return

    if os.name == "nt":
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
            proc.wait(timeout=10)
            return
        except (OSError, subprocess.TimeoutExpired):
            _kill_windows_process_tree(proc.pid)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            proc.kill()

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _kill_windows_process_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _scan_log_metrics(log_path: Path) -> dict[str, int]:
    info_lines = 0
    warning_lines = 0
    error_lines = 0
    catch_all = 0
    ansi = 0
    bracket = 0
    log_file_configured = 0
    warning_error_missing_actionable_fields = 0

    if not log_path.exists():
        raise QualityCheckError(f"Log file missing: {log_path}")

    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if _ANSI_PATTERN.search(line):
                ansi += 1

            event, _structured = event_from_line(line)
            payload = parse_json_object(line)
            if payload is None:
                continue

            level = str(payload.get("level", "")).upper()
            payload_event = payload.get("event")
            if isinstance(payload_event, str) and payload_event:
                event = payload_event
            message = payload.get("message", "")

            if level == "INFO":
                info_lines += 1
            elif level == "WARNING":
                warning_lines += 1
                if not _has_actionable_warning_error_field(payload):
                    warning_error_missing_actionable_fields += 1
            elif level == "ERROR":
                error_lines += 1
                if not _has_actionable_warning_error_field(payload):
                    warning_error_missing_actionable_fields += 1

            if event == "log_file_configured":
                log_file_configured += 1

            if _CATCH_ALL_PATTERN.match(event) and event not in _ALLOWED_LOG_EVENTS:
                catch_all += 1

            if isinstance(message, str) and _BRACKET_TAG_PATTERN.match(message):
                bracket += 1

    return {
        "info_lines": info_lines,
        "warning_lines": warning_lines,
        "error_lines": error_lines,
        "warning_error_missing_actionable_fields": (
            warning_error_missing_actionable_fields
        ),
        "catch_all_event_count": catch_all,
        "ansi_field_count": ansi,
        "bracket_tag_message_count": bracket,
        "log_file_configured_count": log_file_configured,
    }


def _has_actionable_warning_error_field(payload: Mapping[str, Any]) -> bool:
    for field in _WARNING_ERROR_ACTIONABLE_FIELDS:
        if _is_nonempty_actionable_value(payload.get(field)):
            return True
    return False


def _is_nonempty_actionable_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _count_info_lines_by_request_id(log_path: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            payload = parse_json_object(line)
            if payload is None:
                continue
            if str(payload.get("level", "")).upper() != "INFO":
                continue
            request_id = payload.get("request_id")
            if isinstance(request_id, str) and request_id:
                counts[request_id] += 1
    return dict(sorted(counts.items()))




def _parse_workflow(raw_workflow: str) -> list[str]:
    workflow = [item.strip() for item in raw_workflow.split(",") if item.strip()]
    if not workflow:
        raise QualityCheckError("Workflow must include at least one step")
    unknown = sorted(set(workflow) - WORKFLOW_STEPS)
    if unknown:
        raise QualityCheckError(f"Unknown workflow step(s): {', '.join(unknown)}")
    if "generate" in workflow and "preview" not in workflow:
        raise QualityCheckError("Workflow step 'generate' requires 'preview'")
    selected_replace_steps = [
        step for step in workflow if step in REPLACE_FAMILY_STEPS
    ]
    if len(selected_replace_steps) > 1:
        conflict = ", ".join(selected_replace_steps)
        raise QualityCheckError(
            f"Workflow replace family steps should not be combined: {conflict}. "
            "Pick exactly one replace family step."
        )
    if "vector" in workflow and selected_replace_steps:
        conflict = ", ".join(["vector", *selected_replace_steps])
        raise QualityCheckError(
            f"Workflow steps should not be combined: {conflict}; "
            "replace family steps already exercise the vector region-replace path. "
            "Pick exactly one replace family step or run 'vector' separately."
        )
    return workflow


def _default_output_path(mode: Mode) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "progress" / f"log_audit_{mode}_{timestamp}.json"


def _format_stdout_summary(report: QualityReport, output_path: Path) -> str:
    log_path = Path(report.log_path)
    display_log_path = (
        log_path.relative_to(REPO_ROOT)
        if log_path.is_relative_to(REPO_ROOT) else log_path
    )
    display_output_path = (
        output_path.relative_to(REPO_ROOT)
        if output_path.is_relative_to(REPO_ROOT) else output_path
    )
    lines = [
        (
            "=== Lumina Log Quality Check "
            f"(mode={report.mode}, workflow={','.join(report.workflow)}) ==="
        ),
        (
            f"Log: {display_log_path} "
            f"({_format_bytes(report.total_bytes)}, {report.total_lines} lines)"
        ),
        f"JSON: {display_output_path}",
        "",
        "LEVEL DISTRIBUTION",
        f"  INFO    : {report.info_lines}",
        f"  WARNING : {report.warning_lines}",
        f"  ERROR   : {report.error_lines}",
        (
            "  WARNING/ERROR missing actionable fields: "
            f"{report.warning_error_missing_actionable_fields}"
        ),
        "",
        "TOP EVENTS",
    ]
    if report.top_events:
        for entry in report.top_events:
            event = str(entry.get("event", "?"))
            count = int(entry.get("count", 0))
            lines.append(f"  {event:<32}: {count}")
    else:
        lines.append("  none")

    lines.extend(
        [
            "",
            "LOG CHECKS",
        ]
    )
    for check in report.checks:
        label = "PASS" if check.passed else "FAIL"
        lines.append(
            f"  [{label}] {check.name:<34} "
            f"{check.actual} {check.operator} {check.threshold}"
        )

    if report.workflow_checks:
        lines.extend(["", "WORKFLOW CHECKS"])
        for check in report.workflow_checks:
            label = "PASS" if check.passed else "FAIL"
            lines.append(
                f"  [{label}] {check.name:<34} "
                f"{check.actual} {check.operator} {check.threshold}"
            )

    lines.append("")
    lines.append(f"RESULT: {'PASS' if report.overall_passed else 'FAIL'}")

    return "\n".join(lines) + "\n"




def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    return f"{size / 1024:.1f} KB"


def _flush_lumina_handlers() -> None:
    for logger_name in ("lumina", ""):
        for handler in logging.getLogger(logger_name).handlers:
            try:
                handler.flush()
            except Exception:
                continue


def _remove_paths(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
