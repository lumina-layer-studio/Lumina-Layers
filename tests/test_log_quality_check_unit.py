"""Unit tests for the log quality check helper functions."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import scripts.log_quality_check as log_quality_check
from scripts.audit_logs import audit_files, event_from_line, parse_json_object
from scripts.log_quality_check import (
    CheckResult,
    WORKFLOW_ORDER,
    WORKFLOW_STEPS,
    _parse_workflow,
    _scan_log_metrics,
    _select_replace_click,
    _workflow_required_event_checks,
)


def _write_json_lines(path: Path, payloads: list[dict[str, object]]) -> None:
    lines = [json.dumps(payload, ensure_ascii=False) for payload in payloads]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def test_fast_puzzle_worker_includes_export_transform_metadata() -> None:
    created_paths: list[Path] = []
    try:
        result = log_quality_check._build_mock_generate_result(
            created_paths, worker_name="_submit_puzzle_worker",
        )
        assert result["x_mirrored"] is False
        assert result["mirror_span_mm"] == 60.0
        assert Path(result["threemf_path"]).is_file()
    finally:
        for path in created_paths:
            path.unlink(missing_ok=True)


def _build_report_for_log(path: Path) -> log_quality_check.QualityReport:
    audit_result = audit_files([path], label="unit")
    return log_quality_check.build_quality_report(
        mode="fast",
        workflow=[],
        log_path=path,
        audit_result=audit_result,
    )


def test_quality_report_accepts_useful_info_without_a_line_budget(tmp_path: Path) -> None:
    log_path = tmp_path / "many-info.log"
    _write_json_lines(log_path, [
        {"level": "INFO", "event": "log_file_configured", "message": "configured"},
        *[
            {"level": "INFO", "event": "worker_tile_done", "request_id": "same-request",
             "tile_index": index, "message": "tile complete"}
            for index in range(40)
        ],
    ])

    report = _build_report_for_log(log_path)

    assert report.info_lines == 41
    assert report.overall_passed is True


def test_scan_empty_file_returns_zero_metrics(tmp_path: Path) -> None:
    log_path = tmp_path / "empty.log"
    log_path.write_text("", encoding="utf-8")

    metrics = _scan_log_metrics(log_path)

    assert metrics["info_lines"] == 0
    assert metrics["warning_lines"] == 0
    assert metrics["error_lines"] == 0
    assert metrics["catch_all_event_count"] == 0
    assert metrics["ansi_field_count"] == 0
    assert metrics["bracket_tag_message_count"] == 0
    assert metrics["log_file_configured_count"] == 0
    assert metrics["warning_error_missing_actionable_fields"] == 0


def test_scan_counts_catch_all_request_log_event(tmp_path: Path) -> None:
    log_path = tmp_path / "catch-all.log"
    _write_json_lines(
        log_path,
        [{"level": "INFO", "event": "request_log", "message": "legacy bucket"}],
    )

    metrics = _scan_log_metrics(log_path)

    assert metrics["info_lines"] == 1
    assert metrics["catch_all_event_count"] == 1


def test_scan_counts_bracket_tag_message_prefix(tmp_path: Path) -> None:
    log_path = tmp_path / "bracket.log"
    _write_json_lines(
        log_path,
        [
            {
                "level": "INFO",
                "event": "isolated_pixels_cleaned",
                "message": "[ISOLATED_CLEANUP] removed pixels",
            }
        ],
    )

    metrics = _scan_log_metrics(log_path)

    assert metrics["bracket_tag_message_count"] == 1


def test_scan_counts_json_escaped_ansi_sequences(tmp_path: Path) -> None:
    log_path = tmp_path / "ansi.log"
    _write_json_lines(
        log_path,
        [
            {
                "level": "INFO",
                "event": "uvicorn",
                "message": "\u001b[36mGET /api/health\u001b[0m",
            }
        ],
    )

    metrics = _scan_log_metrics(log_path)

    assert metrics["ansi_field_count"] == 1


def test_scan_allows_client_log_event(tmp_path: Path) -> None:
    log_path = tmp_path / "client.log"
    _write_json_lines(
        log_path,
        [{"level": "INFO", "event": "client_log", "message": "frontend timing"}],
    )

    metrics = _scan_log_metrics(log_path)

    assert metrics["catch_all_event_count"] == 0


def test_quality_report_fails_warning_without_actionable_fields(tmp_path: Path) -> None:
    log_path = tmp_path / "warning-missing-fields.log"
    _write_json_lines(
        log_path,
        [
            {"level": "INFO", "event": "log_file_configured", "message": "configured"},
            {
                "level": "WARNING",
                "event": "converter_generate_failed",
                "message": "generation failed",
            },
        ],
    )

    report = _build_report_for_log(log_path)

    assert report.warning_lines == 1
    assert report.warning_error_missing_actionable_fields == 1
    assert report.overall_passed is False
    failed_checks = {check.name for check in report.checks if not check.passed}
    assert "no_warning_error_missing_actionable_fields" in failed_checks


def test_quality_report_rejects_only_request_or_session_ids_on_warning(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "warning-only-correlation-fields.log"
    _write_json_lines(
        log_path,
        [
            {"level": "INFO", "event": "log_file_configured", "message": "configured"},
            {
                "level": "WARNING",
                "event": "converter_generate_failed",
                "message": "generation failed",
                "request_id": "req-1",
                "session_id": "session-1",
            },
        ],
    )

    report = _build_report_for_log(log_path)

    assert report.warning_error_missing_actionable_fields == 1
    assert report.overall_passed is False


def test_quality_report_rejects_empty_actionable_fields(tmp_path: Path) -> None:
    log_path = tmp_path / "warning-empty-actionable-fields.log"
    _write_json_lines(
        log_path,
        [
            {"level": "INFO", "event": "log_file_configured", "message": "configured"},
            {
                "level": "WARNING",
                "event": "converter_generate_failed",
                "message": "generation failed",
                "error_type": "  ",
                "error_message": "",
                "path": [],
                "status_code": 0,
            },
        ],
    )

    report = _build_report_for_log(log_path)

    assert report.warning_error_missing_actionable_fields == 1
    assert report.overall_passed is False


def test_quality_report_allows_warning_and_error_with_diagnostic_fields(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "warning-error-diagnostic-fields.log"
    _write_json_lines(
        log_path,
        [
            {"level": "INFO", "event": "log_file_configured", "message": "configured"},
            {
                "level": "WARNING",
                "event": "preview_resource_missing",
                "message": "resource missing",
                "path": "/tmp/missing.glb",
            },
            {
                "level": "ERROR",
                "event": "converter_generate_failed",
                "message": "generation failed",
                "error_type": "RuntimeError",
                "error_message": "mesh export failed",
            },
        ],
    )

    report = _build_report_for_log(log_path)

    assert report.warning_lines == 1
    assert report.error_lines == 1
    assert report.warning_error_missing_actionable_fields == 0
    assert report.overall_passed is True


def test_vector_workflow_step_is_first_class() -> None:
    """The SVG-native vector workflow must be accepted by the quality gate."""

    workflow = _parse_workflow("startup,lut_list,lut_colors,preview,generate,vector")

    assert workflow == ["startup", "lut_list", "lut_colors", "preview", "generate", "vector"]
    assert "vector" in WORKFLOW_ORDER
    assert "vector" in WORKFLOW_STEPS


def test_replace_workflow_step_is_first_class() -> None:
    """The replace workflow must be accepted by the quality gate."""

    workflow = _parse_workflow("startup,lut_list,lut_colors,preview,generate,replace")

    assert workflow == [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
    ]
    assert "replace" in WORKFLOW_ORDER
    assert "replace" in WORKFLOW_STEPS


def _assert_replace_family_step_is_first_class(step: str) -> None:
    workflow = _parse_workflow(
        f"startup,lut_list,lut_colors,preview,generate,{step}"
    )

    assert workflow == ["startup", "lut_list", "lut_colors", "preview", "generate", step]
    assert step in WORKFLOW_ORDER
    assert step in WORKFLOW_STEPS


def test_replace_bw_workflow_step_is_first_class() -> None:
    _assert_replace_family_step_is_first_class("replace_bw")


def test_replace_8color_workflow_step_is_first_class() -> None:
    _assert_replace_family_step_is_first_class("replace_8color")


def test_replace_5color_ext_workflow_step_is_first_class() -> None:
    _assert_replace_family_step_is_first_class("replace_5color_ext")


def test_replace_color_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow(
        "startup,lut_list,lut_colors,preview,generate,replace_color"
    )

    assert workflow == [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace_color",
    ]
    assert "replace_color" not in log_quality_check.DEFAULT_WORKFLOW
    assert "replace_color" in WORKFLOW_ORDER
    assert "replace_color" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("replace_color")
        == WORKFLOW_ORDER.index("replace_5color_ext") + 1
    )


def test_extract_workflow_step_is_first_class() -> None:
    """The extractor workflow must be accepted by the quality gate."""

    workflow = _parse_workflow(
        "startup,lut_list,lut_colors,preview,generate,replace,extract"
    )

    assert workflow == [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract",
    ]
    assert "extract" in WORKFLOW_ORDER
    assert "extract" in WORKFLOW_STEPS


def test_extract_single_stage_workflow_step_is_first_class() -> None:
    """The single-stage extractor workflow must be part of the canonical gate."""

    workflow = _parse_workflow(
        "startup,lut_list,lut_colors,preview,generate,replace,extract_single_stage,extract"
    )

    assert workflow == [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract_single_stage",
        "extract",
    ]
    assert "extract_single_stage" in log_quality_check.DEFAULT_WORKFLOW
    assert "extract_single_stage" in WORKFLOW_ORDER
    assert "extract_single_stage" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("extract_single_stage")
        == WORKFLOW_ORDER.index("cleanup_session_files") + 1
    )


def test_fast_mode_app_mounts_local_development_routes() -> None:
    """Fast log gate must exercise the full local development route baseline."""

    app = log_quality_check._build_fast_mode_app()

    assert str(app.url_path_for("extractor_extract_single_stage")) == (
        "/api/extractor/extract-single-stage"
    )
    assert str(app.url_path_for("extractor_extract")) == "/api/extractor/extract"
    assert str(app.url_path_for("calibration_generate_single_stage_kit")) == (
        "/api/calibration/generate-single-stage-kit"
    )


@pytest.mark.parametrize("external_output", [False, True], ids=["repository", "external"])
def test_fast_mode_preview_supports_timed_worker_submission(
    tmp_path: Path, external_output: bool,
) -> None:
    """The fast gate must mirror the preview endpoint's timed pool contract."""

    output_path = tmp_path / "log-quality.json" if external_output else (
        log_quality_check.REPO_ROOT
        / ".scratch"
        / f"log-quality-timed-{uuid.uuid4().hex}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/log_quality_check.py",
                "--mode",
                "fast",
                "--workflow",
                "lut_list,lut_colors,preview",
                "--output",
                str(output_path),
            ],
            cwd=log_quality_check.REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert completed.returncode == 0, completed.stdout + completed.stderr
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["overall_passed"] is True
        assert "RESULT: PASS" in completed.stdout
    finally:
        output_path.unlink(missing_ok=True)
        output_path.with_suffix(".log").unlink(missing_ok=True)




def test_mock_preview_worker_contract_binds_current_worker_signature() -> None:
    """Fast-gate preview caches must carry the real worker semantics."""

    from api.workers.converter_workers import worker_generate_preview

    worker_args = (
        "source.svg",
        "lut.json",
        60.0,
        log_quality_check.DEFAULT_COLOR_MODE,
        log_quality_check.VECTOR_MODELING_MODE,
        None,
        None,
        48,
        True,
        False,
        2.0,
        True,
        False,
        False,
        None,
        None,
        0.0,
        15.0,
        False,
        "lut",
        None,
        None,
        None,
        None,
        False,
        False,
        10.0,
        None,
    )

    contract = log_quality_check._mock_preview_worker_contract(
        worker_generate_preview,
        worker_args,
    )

    assert contract["is_vector"] is True
    assert contract["color_mode"] == log_quality_check.DEFAULT_COLOR_MODE
    assert contract["metadata"] == {
        "target_width_mm": 60.0,
        "color_mode": log_quality_check.DEFAULT_COLOR_MODE,
        "modeling_mode": log_quality_check.VECTOR_MODELING_MODE,
        "color_layers": None,
        "layer_height_mm": None,
        "quantize_colors": 48,
        "enable_cleanup": True,
        "hue_weight": 0.0,
        "chroma_gate": 15.0,
        "use_lut_constrained": False,
        "auto_dynamic_range": False,
        "model_enable": False,
        "model_only": False,
        "model_threshold": None,
        "model_margin": None,
        "svg_pixels_per_mm": 10.0,
        "material_source": "lut",
    }


def test_fit_stage_a_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("fit_stage_a")

    assert workflow == ["fit_stage_a"]
    assert "fit_stage_a" not in log_quality_check.DEFAULT_WORKFLOW
    assert "fit_stage_a" in WORKFLOW_ORDER
    assert "fit_stage_a" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("fit_stage_a")
        == WORKFLOW_ORDER.index("extract_single_stage") + 1
    )


def test_extract_gradient_card_stage_a_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("extract_gradient_card_stage_a")

    assert workflow == ["extract_gradient_card_stage_a"]
    assert "extract_gradient_card_stage_a" not in log_quality_check.DEFAULT_WORKFLOW
    assert "extract_gradient_card_stage_a" in WORKFLOW_ORDER
    assert "extract_gradient_card_stage_a" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("extract_gradient_card_stage_a")
        == WORKFLOW_ORDER.index("fit_stage_a") + 1
    )


def test_save_gradient_card_material_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("save_gradient_card_material")

    assert workflow == ["save_gradient_card_material"]
    assert "save_gradient_card_material" not in log_quality_check.DEFAULT_WORKFLOW
    assert "save_gradient_card_material" in WORKFLOW_ORDER
    assert "save_gradient_card_material" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("save_gradient_card_material")
        == WORKFLOW_ORDER.index("extract_gradient_card_stage_a") + 1
    )


def test_delete_gradient_card_material_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("delete_gradient_card_material")

    assert workflow == ["delete_gradient_card_material"]
    assert "delete_gradient_card_material" not in log_quality_check.DEFAULT_WORKFLOW
    assert "delete_gradient_card_material" in WORKFLOW_ORDER
    assert "delete_gradient_card_material" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("delete_gradient_card_material")
        == WORKFLOW_ORDER.index("save_gradient_card_material") + 1
    )


def test_update_gradient_card_material_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("update_gradient_card_material")

    assert workflow == ["update_gradient_card_material"]
    assert "update_gradient_card_material" not in log_quality_check.DEFAULT_WORKFLOW
    assert "update_gradient_card_material" in WORKFLOW_ORDER
    assert "update_gradient_card_material" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("update_gradient_card_material")
        == WORKFLOW_ORDER.index("delete_gradient_card_material") + 1
    )


def test_export_gradient_card_materials_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("export_gradient_card_materials")

    assert workflow == ["export_gradient_card_materials"]
    assert "export_gradient_card_materials" not in log_quality_check.DEFAULT_WORKFLOW
    assert "export_gradient_card_materials" in WORKFLOW_ORDER
    assert "export_gradient_card_materials" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("export_gradient_card_materials")
        == WORKFLOW_ORDER.index("update_gradient_card_material") + 1
    )


def test_import_gradient_card_materials_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("import_gradient_card_materials")

    assert workflow == ["import_gradient_card_materials"]
    assert "import_gradient_card_materials" not in log_quality_check.DEFAULT_WORKFLOW
    assert "import_gradient_card_materials" in WORKFLOW_ORDER
    assert "import_gradient_card_materials" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("import_gradient_card_materials")
        == WORKFLOW_ORDER.index("export_gradient_card_materials") + 1
    )


def test_material_solver_cache_status_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("material_solver_cache_status")

    assert workflow == ["material_solver_cache_status"]
    assert "material_solver_cache_status" not in log_quality_check.DEFAULT_WORKFLOW
    assert "material_solver_cache_status" in WORKFLOW_ORDER
    assert "material_solver_cache_status" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("material_solver_cache_status")
        == WORKFLOW_ORDER.index("import_gradient_card_materials") + 1
    )


def test_material_solver_cache_build_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("material_solver_cache_build")

    assert workflow == ["material_solver_cache_build"]
    assert "material_solver_cache_build" not in log_quality_check.DEFAULT_WORKFLOW
    assert "material_solver_cache_build" in WORKFLOW_ORDER
    assert "material_solver_cache_build" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("material_solver_cache_build")
        == WORKFLOW_ORDER.index("material_solver_cache_status") + 1
    )


def test_material_solver_cache_delete_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("material_solver_cache_delete")

    assert workflow == ["material_solver_cache_delete"]
    assert "material_solver_cache_delete" not in log_quality_check.DEFAULT_WORKFLOW
    assert "material_solver_cache_delete" in WORKFLOW_ORDER
    assert "material_solver_cache_delete" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("material_solver_cache_delete")
        == WORKFLOW_ORDER.index("material_solver_cache_build") + 1
    )


def test_material_solver_cache_suggest_colors_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("material_solver_cache_suggest_colors")

    assert workflow == ["material_solver_cache_suggest_colors"]
    assert (
        "material_solver_cache_suggest_colors"
        not in log_quality_check.DEFAULT_WORKFLOW
    )
    assert "material_solver_cache_suggest_colors" in WORKFLOW_ORDER
    assert "material_solver_cache_suggest_colors" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("material_solver_cache_suggest_colors")
        == WORKFLOW_ORDER.index("material_solver_cache_delete") + 1
    )


def test_calibration_generate_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("calibration_generate")

    assert workflow == ["calibration_generate"]
    assert "calibration_generate" not in log_quality_check.DEFAULT_WORKFLOW
    assert "calibration_generate" in WORKFLOW_ORDER
    assert "calibration_generate" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("calibration_generate")
        == WORKFLOW_ORDER.index("material_solver_cache_suggest_colors") + 1
    )


def test_calibration_generate_single_stage_kit_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("calibration_generate_single_stage_kit")

    assert workflow == ["calibration_generate_single_stage_kit"]
    assert (
        "calibration_generate_single_stage_kit"
        not in log_quality_check.DEFAULT_WORKFLOW
    )
    assert "calibration_generate_single_stage_kit" in WORKFLOW_ORDER
    assert "calibration_generate_single_stage_kit" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("calibration_generate_single_stage_kit")
        == WORKFLOW_ORDER.index("calibration_generate") + 1
    )


def test_five_color_query_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("five_color_query")

    assert workflow == ["five_color_query"]
    assert "five_color_query" not in log_quality_check.DEFAULT_WORKFLOW
    assert "five_color_query" in WORKFLOW_ORDER
    assert "five_color_query" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("five_color_query")
        == WORKFLOW_ORDER.index("calibration_generate_single_stage_kit") + 1
    )


def test_five_color_generate_swatch_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("five_color_generate_swatch")

    assert workflow == ["five_color_generate_swatch"]
    assert "five_color_generate_swatch" not in log_quality_check.DEFAULT_WORKFLOW
    assert "five_color_generate_swatch" in WORKFLOW_ORDER
    assert "five_color_generate_swatch" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("five_color_generate_swatch")
        == WORKFLOW_ORDER.index("five_color_query") + 1
    )


def test_five_color_base_colors_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("five_color_base_colors")

    assert workflow == ["five_color_base_colors"]
    assert "five_color_base_colors" not in log_quality_check.DEFAULT_WORKFLOW
    assert "five_color_base_colors" in WORKFLOW_ORDER
    assert "five_color_base_colors" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("five_color_base_colors")
        == WORKFLOW_ORDER.index("five_color_generate_swatch") + 1
    )


def test_vectorize_image_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("vectorize_image")

    assert workflow == ["vectorize_image"]
    assert "vectorize_image" not in log_quality_check.DEFAULT_WORKFLOW
    assert "vectorize_image" in WORKFLOW_ORDER
    assert "vectorize_image" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("vectorize_image")
        == WORKFLOW_ORDER.index("five_color_base_colors") + 1
    )


def test_lut_merge_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("lut_merge")

    assert workflow == ["lut_merge"]
    assert "lut_merge" not in log_quality_check.DEFAULT_WORKFLOW
    assert "lut_merge" in WORKFLOW_ORDER
    assert "lut_merge" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("lut_merge") == WORKFLOW_ORDER.index("vectorize_image") + 1


def test_lut_compare_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("lut_compare")

    assert workflow == ["lut_compare"]
    assert "lut_compare" not in log_quality_check.DEFAULT_WORKFLOW
    assert "lut_compare" in WORKFLOW_ORDER
    assert "lut_compare" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("lut_compare") == WORKFLOW_ORDER.index("lut_merge") + 1


def test_lut_details_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("lut_details")

    assert workflow == ["lut_details"]
    assert "lut_details" not in log_quality_check.DEFAULT_WORKFLOW
    assert "lut_details" in WORKFLOW_ORDER
    assert "lut_details" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("lut_details") == WORKFLOW_ORDER.index("lut_compare") + 1


def test_lut_upload_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("lut_upload")

    assert workflow == ["lut_upload"]
    assert "lut_upload" not in log_quality_check.DEFAULT_WORKFLOW
    assert "lut_upload" in WORKFLOW_ORDER
    assert "lut_upload" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("lut_upload") == WORKFLOW_ORDER.index("lut_details") + 1


def test_lut_session_info_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("lut_session_info")

    assert workflow == ["lut_session_info"]
    assert "lut_session_info" not in log_quality_check.DEFAULT_WORKFLOW
    assert "lut_session_info" in WORKFLOW_ORDER
    assert "lut_session_info" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("lut_session_info") == WORKFLOW_ORDER.index("lut_upload") + 1


def test_system_image_preview_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("system_image_preview")

    assert workflow == ["system_image_preview"]
    assert "system_image_preview" not in log_quality_check.DEFAULT_WORKFLOW
    assert "system_image_preview" in WORKFLOW_ORDER
    assert "system_image_preview" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("system_image_preview")
        == WORKFLOW_ORDER.index("lut_session_info") + 1
    )


def test_system_image_preview_workflow_requires_canary_event() -> None:
    workflow = ["system_image_preview"]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"system_image_preview_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_system_image_preview_done"].passed is True
    assert missing_by_name["workflow_event_system_image_preview_done"].passed is False


def test_system_save_settings_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("system_save_settings")

    assert workflow == ["system_save_settings"]
    assert "system_save_settings" not in log_quality_check.DEFAULT_WORKFLOW
    assert "system_save_settings" in WORKFLOW_ORDER
    assert "system_save_settings" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("system_save_settings")
        == WORKFLOW_ORDER.index("system_image_preview") + 1
    )


def test_system_save_settings_workflow_requires_canary_event() -> None:
    workflow = ["system_save_settings"]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"system_save_settings_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_system_save_settings_done"].passed is True
    assert missing_by_name["workflow_event_system_save_settings_done"].passed is False


def test_slicer_launch_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("slicer_launch")

    assert workflow == ["slicer_launch"]
    assert "slicer_launch" not in log_quality_check.DEFAULT_WORKFLOW
    assert "slicer_launch" in WORKFLOW_ORDER
    assert "slicer_launch" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("slicer_launch")
        == WORKFLOW_ORDER.index("system_save_settings") + 1
    )


def test_slicer_launch_workflow_requires_canary_event() -> None:
    workflow = ["slicer_launch"]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"slicer_launch_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_slicer_launch_done"].passed is True
    assert missing_by_name["workflow_event_slicer_launch_done"].passed is False


def test_feedback_submit_workflow_step_is_first_class() -> None:
    workflow = _parse_workflow("feedback_submit")

    assert workflow == ["feedback_submit"]
    assert "feedback_submit" not in log_quality_check.DEFAULT_WORKFLOW
    assert "feedback_submit" in WORKFLOW_ORDER
    assert "feedback_submit" in WORKFLOW_STEPS
    assert (
        WORKFLOW_ORDER.index("feedback_submit")
        == WORKFLOW_ORDER.index("slicer_launch") + 1
    )


def test_feedback_submit_workflow_requires_canary_event() -> None:
    workflow = ["feedback_submit"]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"feedback_bug_report_submitted": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_feedback_bug_report_submitted"].passed is True
    assert missing_by_name["workflow_event_feedback_bug_report_submitted"].passed is False


def test_merge_8color_workflow_step_is_first_class() -> None:
    """The 8-color merge workflow must be accepted by the quality gate."""

    workflow = _parse_workflow(
        "startup,lut_list,lut_colors,preview,generate,replace,extract,merge_8color"
    )

    assert workflow == [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract",
        "merge_8color",
    ]
    assert "merge_8color" in WORKFLOW_ORDER
    assert "merge_8color" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("merge_8color") == WORKFLOW_ORDER.index("extract") + 1


def test_merge_5color_ext_workflow_step_is_first_class() -> None:
    """The 5-color extended merge workflow must be accepted by the quality gate."""

    workflow = _parse_workflow(
        "startup,lut_list,lut_colors,preview,generate,replace,extract,merge_8color,merge_5color_ext"
    )

    assert workflow == [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract",
        "merge_8color",
        "merge_5color_ext",
    ]
    assert "merge_5color_ext" in log_quality_check.DEFAULT_WORKFLOW
    assert "merge_5color_ext" in WORKFLOW_ORDER
    assert "merge_5color_ext" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("merge_5color_ext") == WORKFLOW_ORDER.index("merge_8color") + 1


def test_manual_fix_workflow_step_is_first_class() -> None:
    """The extractor manual-fix workflow must be accepted by the quality gate."""

    workflow = _parse_workflow("manual_fix")

    assert workflow == ["manual_fix"]
    assert "manual_fix" not in log_quality_check.DEFAULT_WORKFLOW
    assert "manual_fix" in WORKFLOW_ORDER
    assert "manual_fix" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("manual_fix") == WORKFLOW_ORDER.index("merge_5color_ext") + 1


def test_preview_wb_workflow_step_is_first_class() -> None:
    """The white-balance preview workflow must be accepted by the quality gate."""

    workflow = _parse_workflow("preview_wb")

    assert workflow == ["preview_wb"]
    assert "preview_wb" not in log_quality_check.DEFAULT_WORKFLOW
    assert "preview_wb" in WORKFLOW_ORDER
    assert "preview_wb" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("preview_wb") == WORKFLOW_ORDER.index("manual_fix") + 1


def test_rotate_workflow_step_is_first_class() -> None:
    """The extractor rotate workflow must be accepted by the quality gate."""

    workflow = _parse_workflow("rotate")

    assert workflow == ["rotate"]
    assert "rotate" not in log_quality_check.DEFAULT_WORKFLOW
    assert "rotate" in WORKFLOW_ORDER
    assert "rotate" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("rotate") == WORKFLOW_ORDER.index("preview_wb") + 1


def test_confirm_palette_workflow_step_is_first_class() -> None:
    """The palette confirmation workflow must be accepted by the quality gate."""

    workflow = _parse_workflow("confirm_palette")

    assert workflow == ["confirm_palette"]
    assert "confirm_palette" not in log_quality_check.DEFAULT_WORKFLOW
    assert "confirm_palette" in WORKFLOW_ORDER
    assert "confirm_palette" in WORKFLOW_STEPS
    assert WORKFLOW_ORDER.index("confirm_palette") == WORKFLOW_ORDER.index("rotate") + 1


def test_parse_workflow_rejects_vector_and_replace_together() -> None:
    try:
        _parse_workflow("startup,lut_list,lut_colors,preview,generate,vector,replace")
    except Exception as exc:
        assert "should not be combined" in str(exc)
    else:
        raise AssertionError("Expected vector + replace workflow to be rejected")


def test_parse_workflow_rejects_replace_family_combinations() -> None:
    workflow_prefix = "startup,lut_list,lut_colors,preview,generate"
    conflicts = [
        ("replace", "replace_bw"),
        ("replace", "replace_8color"),
        ("replace", "replace_5color_ext"),
        ("replace_bw", "replace_8color"),
        ("replace_bw", "replace_5color_ext"),
        ("replace_8color", "replace_5color_ext"),
    ]

    for first, second in conflicts:
        with pytest.raises(Exception) as exc_info:
            _parse_workflow(f"{workflow_prefix},{first},{second}")

        message = str(exc_info.value)
        assert first in message
        assert second in message
        assert "replace family" in message
        assert "Pick exactly one" in message

    with pytest.raises(Exception) as exc_info:
        _parse_workflow(f"{workflow_prefix},vector,replace_bw")

    message = str(exc_info.value)
    assert "vector" in message
    assert "replace_bw" in message
    assert "replace family" in message
    assert "run 'vector' separately" in message or "Pick exactly one" in message


def test_main_returns_script_error_for_replace_family_combination(capsys) -> None:
    exit_code = log_quality_check.main(
        ["--mode", "fast", "--workflow", "startup,lut_list,lut_colors,preview,generate,replace,replace_bw"]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "replace family" in captured.err
    assert "Pick exactly one" in captured.err


def test_replace_family_member_dispatches_correct_color_mode(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_execute_replace_workflow(client, **kwargs):
        captured.append({"client": client, **kwargs})

    monkeypatch.setattr(
        log_quality_check, "_execute_replace_workflow", fake_execute_replace_workflow
    )

    client = object()
    wrappers = {
        "replace_bw": log_quality_check._execute_replace_bw_workflow,
        "replace_8color": log_quality_check._execute_replace_8color_workflow,
        "replace_5color_ext": log_quality_check._execute_replace_5color_ext_workflow,
    }
    for step, execute_workflow in wrappers.items():
        color_mode, lut_name = log_quality_check.ALTERNATE_REPLACE_CONFIG[step]
        captured.clear()

        execute_workflow(client)

        assert captured == [
            {
                "client": client,
                "mode": step,
                "color_mode": color_mode,
                "lut_name": lut_name,
            }
        ]


def test_default_workflow_lut_names_exist_in_catalog() -> None:
    from utils.lut_manager import LUTManager

    lut_names = [
        log_quality_check.DEFAULT_LUT_NAME,
        log_quality_check.BW_LUT_NAME,
        log_quality_check.EIGHT_COLOR_LUT_NAME,
        log_quality_check.FIVE_COLOR_EXT_LUT_NAME,
    ]

    with log_quality_check.isolated_workflow_resources():
        missing = [name for name in lut_names if LUTManager.get_lut_path(name) is None]

    assert missing == []


def test_full_replace_workflow_requires_canary_events() -> None:
    checks = _workflow_required_event_checks(
        mode="full",
        workflow=["startup", "lut_list", "lut_colors", "preview", "generate", "replace"],
        event_counts={"converter_region_replace_timing": 1},
    )

    by_name = {check.name: check for check in checks}

    assert by_name["workflow_event_converter_region_replace_timing"].passed is True
    assert (
        by_name["workflow_event_vector_matched_rgb_overrides_applied"].passed
        is False
    )


def test_fast_replace_workflow_does_not_require_worker_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["startup", "lut_list", "lut_colors", "preview", "generate", "replace"],
        event_counts={"converter_region_replace_timing": 1},
    )

    assert {check.name for check in checks} == {
        "workflow_event_converter_region_replace_timing"
    }
    assert all(check.passed for check in checks)


def test_replace_bw_fast_and_full_canary_requirements_differ() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace_bw",
    ]

    fast_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_region_replace_timing": 1},
    )
    full_checks = _workflow_required_event_checks(
        mode="full",
        workflow=workflow,
        event_counts={"converter_region_replace_timing": 1},
    )

    fast_by_name = {check.name: check for check in fast_checks}
    full_by_name = {check.name: check for check in full_checks}

    assert set(fast_by_name) == {"workflow_event_converter_region_replace_timing"}
    assert fast_by_name["workflow_event_converter_region_replace_timing"].passed is True
    assert full_by_name["workflow_event_converter_region_replace_timing"].passed is True
    assert (
        full_by_name["workflow_event_vector_matched_rgb_overrides_applied"].passed
        is False
    )


def test_replace_color_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace_color",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_replace_color_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_replace_color_done"].passed is True
    assert missing_by_name["workflow_event_converter_replace_color_done"].passed is False


def test_reset_replacements_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "reset_replacements",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_reset_replacements_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_reset_replacements_done"].passed is True
    assert (
        missing_by_name["workflow_event_converter_reset_replacements_done"].passed
        is False
    )


def test_source_color_pick_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "source_color_pick",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_source_color_pick_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_source_color_pick_done"].passed is True
    assert (
        missing_by_name["workflow_event_converter_source_color_pick_done"].passed
        is False
    )


def test_color_highlight_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "color_highlight",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_color_highlight_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_color_highlight_done"].passed is True
    assert missing_by_name["workflow_event_converter_color_highlight_done"].passed is False


def test_region_detect_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "region_detect",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_region_detect_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_region_detect_done"].passed is True
    assert missing_by_name["workflow_event_converter_region_detect_done"].passed is False


def test_region_requantize_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "region_requantize",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_region_requantize_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_region_requantize_done"].passed is True
    assert (
        missing_by_name["workflow_event_converter_region_requantize_done"].passed
        is False
    )


def test_replace_colors_batch_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace_colors_batch",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_replace_colors_batch_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_converter_replace_colors_batch_done"].passed
        is True
    )
    assert (
        missing_by_name["workflow_event_converter_replace_colors_batch_done"].passed
        is False
    )


def test_region_replace_batch_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "region_replace_batch",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_region_replace_batch_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_converter_region_replace_batch_done"].passed
        is True
    )
    assert (
        missing_by_name["workflow_event_converter_region_replace_batch_done"].passed
        is False
    )


def test_predict_recipe_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "predict_recipe",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_predict_recipe_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_predict_recipe_done"].passed is True
    assert missing_by_name["workflow_event_converter_predict_recipe_done"].passed is False


def test_apply_recipe_override_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "apply_recipe_override",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_apply_recipe_override_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_converter_apply_recipe_override_done"].passed
        is True
    )
    assert (
        missing_by_name[
            "workflow_event_converter_apply_recipe_override_done"
        ].passed
        is False
    )


def test_region_recipe_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "region_recipe",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_region_recipe_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_region_recipe_done"].passed is True
    assert missing_by_name["workflow_event_converter_region_recipe_done"].passed is False


def test_merge_colors_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "merge_colors",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_merge_colors_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_merge_colors_done"].passed is True
    assert missing_by_name["workflow_event_converter_merge_colors_done"].passed is False


def test_generate_large_format_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["generate_large_format"],
        event_counts={"converter_generate_large_format_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["generate_large_format"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_generate_large_format_done"].passed is True
    assert (
        missing_by_name["workflow_event_converter_generate_large_format_done"].passed
        is False
    )


def test_batch_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["batch"],
        event_counts={"converter_batch_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["batch"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_batch_done"].passed is True
    assert missing_by_name["workflow_event_converter_batch_done"].passed is False


def test_puzzle_layout_preview_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["puzzle_layout_preview"],
        event_counts={"converter_puzzle_layout_preview_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["puzzle_layout_preview"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_puzzle_layout_preview_done"].passed is True
    assert (
        missing_by_name["workflow_event_converter_puzzle_layout_preview_done"].passed
        is False
    )


def test_generate_puzzle_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["generate_puzzle"],
        event_counts={"converter_puzzle_generate_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["generate_puzzle"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_puzzle_generate_done"].passed is True
    assert missing_by_name["workflow_event_converter_puzzle_generate_done"].passed is False


def test_auto_detect_colors_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["auto_detect_colors"],
        event_counts={"converter_auto_detect_colors_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["auto_detect_colors"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_auto_detect_colors_done"].passed is True
    assert (
        missing_by_name["workflow_event_converter_auto_detect_colors_done"].passed
        is False
    )


def test_cleanup_session_files_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["cleanup_session_files"],
        event_counts={"converter_cleanup_session_files_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["cleanup_session_files"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_converter_cleanup_session_files_done"].passed is True
    assert (
        missing_by_name["workflow_event_converter_cleanup_session_files_done"].passed
        is False
    )


def test_full_extract_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract",
    ]
    checks = _workflow_required_event_checks(
        mode="full",
        workflow=workflow,
        event_counts={
            "converter_region_replace_timing": 1,
            "vector_matched_rgb_overrides_applied": 1,
            "extractor_extract_done": 1,
        },
    )
    missing_checks = _workflow_required_event_checks(
        mode="full",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_extract_done"].passed is True
    assert missing_by_name["workflow_event_extractor_extract_done"].passed is False


def test_fast_extract_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={
            "converter_region_replace_timing": 1,
            "extractor_extract_done": 1,
        },
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_extract_done"].passed is True
    assert missing_by_name["workflow_event_extractor_extract_done"].passed is False


def test_extract_single_stage_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract_single_stage",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={
            "converter_region_replace_timing": 1,
            "extractor_extract_single_stage_done": 1,
        },
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_extractor_extract_single_stage_done"].passed
        is True
    )
    assert (
        missing_by_name["workflow_event_extractor_extract_single_stage_done"].passed
        is False
    )


def test_single_stage_full_mode_assets_create_reference_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(log_quality_check, "REPO_ROOT", tmp_path)

    created_paths = log_quality_check._ensure_single_stage_colorchecker_assets()

    reference_root = tmp_path / "reference" / "ChromaPrint3D"
    try:
        assert (
            reference_root
            / "modeling"
            / "pipeline"
            / "step1_extract_stages.py"
        ).is_file()
        assert (
            reference_root
            / "modeling"
            / "pipeline"
            / "step2_fit_stage_a.py"
        ).is_file()
        assert (
            reference_root
            / "modeling"
            / "data"
            / "ColorChecker"
            / "ColorCheckerjson.json"
        ).is_file()
        pycache_dir = reference_root / "modeling" / "pipeline" / "__pycache__"
        pycache_dir.mkdir(parents=True)
        (pycache_dir / "step1_extract_stages.cpython-312.pyc").write_bytes(b"cache")
    finally:
        log_quality_check._remove_single_stage_colorchecker_assets(created_paths)

    assert not reference_root.exists()


def test_single_stage_full_mode_assets_recreate_incomplete_reference_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(log_quality_check, "REPO_ROOT", tmp_path)
    reference_root = tmp_path / "reference" / "ChromaPrint3D"
    residue = reference_root / "modeling" / "pipeline" / "__pycache__"
    residue.mkdir(parents=True)
    (residue / "step1_extract_stages.cpython-312.pyc").write_bytes(b"cache")

    created_paths = log_quality_check._ensure_single_stage_colorchecker_assets()

    try:
        assert (
            reference_root
            / "modeling"
            / "pipeline"
            / "step1_extract_stages.py"
        ).is_file()
        assert (reference_root / ".lumina_log_quality_stub").is_file()
    finally:
        log_quality_check._remove_single_stage_colorchecker_assets(created_paths)

    assert not reference_root.exists()


def test_fit_stage_a_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["fit_stage_a"],
        event_counts={"extractor_fit_stage_a_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["fit_stage_a"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_fit_stage_a_done"].passed is True
    assert missing_by_name["workflow_event_extractor_fit_stage_a_done"].passed is False


def test_extract_gradient_card_stage_a_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["extract_gradient_card_stage_a"],
        event_counts={"extractor_extract_gradient_card_stage_a_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["extract_gradient_card_stage_a"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name[
            "workflow_event_extractor_extract_gradient_card_stage_a_done"
        ].passed
        is True
    )
    assert (
        missing_by_name[
            "workflow_event_extractor_extract_gradient_card_stage_a_done"
        ].passed
        is False
    )


def test_save_gradient_card_material_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["save_gradient_card_material"],
        event_counts={"extractor_save_gradient_card_material_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["save_gradient_card_material"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_extractor_save_gradient_card_material_done"].passed
        is True
    )
    assert (
        missing_by_name[
            "workflow_event_extractor_save_gradient_card_material_done"
        ].passed
        is False
    )


def test_delete_gradient_card_material_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["delete_gradient_card_material"],
        event_counts={"extractor_delete_gradient_card_material_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["delete_gradient_card_material"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_extractor_delete_gradient_card_material_done"].passed
        is True
    )
    assert (
        missing_by_name[
            "workflow_event_extractor_delete_gradient_card_material_done"
        ].passed
        is False
    )


def test_update_gradient_card_material_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["update_gradient_card_material"],
        event_counts={"extractor_update_gradient_card_material_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["update_gradient_card_material"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_extractor_update_gradient_card_material_done"].passed
        is True
    )
    assert (
        missing_by_name[
            "workflow_event_extractor_update_gradient_card_material_done"
        ].passed
        is False
    )


def test_merge_8color_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract",
        "merge_8color",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={
            "converter_region_replace_timing": 1,
            "extractor_extract_done": 1,
            "extractor_merge_8color_done": 1,
        },
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_merge_8color_done"].passed is True
    assert (
        missing_by_name["workflow_event_extractor_merge_8color_done"].passed
        is False
    )


def test_merge_5color_ext_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract",
        "merge_8color",
        "merge_5color_ext",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={
            "converter_region_replace_timing": 1,
            "extractor_extract_done": 1,
            "extractor_merge_8color_done": 1,
            "extractor_merge_5color_extended_done": 1,
        },
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_merge_5color_extended_done"].passed is True
    assert (
        missing_by_name["workflow_event_extractor_merge_5color_extended_done"].passed
        is False
    )


def test_manual_fix_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["manual_fix"],
        event_counts={"extractor_manual_fix_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["manual_fix"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_manual_fix_done"].passed is True
    assert missing_by_name["workflow_event_extractor_manual_fix_done"].passed is False


def test_preview_wb_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["preview_wb"],
        event_counts={"extractor_preview_wb_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["preview_wb"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_preview_wb_done"].passed is True
    assert missing_by_name["workflow_event_extractor_preview_wb_done"].passed is False


def test_rotate_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["rotate"],
        event_counts={"extractor_rotate_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["rotate"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_rotate_done"].passed is True
    assert missing_by_name["workflow_event_extractor_rotate_done"].passed is False


def test_confirm_palette_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["confirm_palette"],
        event_counts={"extractor_confirm_palette_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["confirm_palette"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_confirm_palette_done"].passed is True
    assert missing_by_name["workflow_event_extractor_confirm_palette_done"].passed is False


def test_export_gradient_card_materials_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["export_gradient_card_materials"],
        event_counts={"extractor_export_gradient_card_materials_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["export_gradient_card_materials"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_extractor_export_gradient_card_materials_done"].passed
        is True
    )
    assert (
        missing_by_name[
            "workflow_event_extractor_export_gradient_card_materials_done"
        ].passed
        is False
    )


def test_import_gradient_card_materials_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["import_gradient_card_materials"],
        event_counts={"extractor_import_gradient_card_materials_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["import_gradient_card_materials"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_extractor_import_gradient_card_materials_done"].passed
        is True
    )
    assert (
        missing_by_name[
            "workflow_event_extractor_import_gradient_card_materials_done"
        ].passed
        is False
    )


def test_material_solver_cache_status_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["material_solver_cache_status"],
        event_counts={"material_solver_cache_status_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["material_solver_cache_status"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_material_solver_cache_status_done"].passed is True
    assert missing_by_name["workflow_event_material_solver_cache_status_done"].passed is False


def test_material_solver_cache_build_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["material_solver_cache_build"],
        event_counts={"material_solver_cache_build_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["material_solver_cache_build"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_material_solver_cache_build_done"].passed is True
    assert missing_by_name["workflow_event_material_solver_cache_build_done"].passed is False


def test_material_solver_cache_delete_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["material_solver_cache_delete"],
        event_counts={"material_solver_cache_delete_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["material_solver_cache_delete"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_material_solver_cache_delete_done"].passed is True
    assert missing_by_name["workflow_event_material_solver_cache_delete_done"].passed is False


def test_material_solver_cache_suggest_colors_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["material_solver_cache_suggest_colors"],
        event_counts={"material_solver_cache_suggest_colors_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["material_solver_cache_suggest_colors"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_material_solver_cache_suggest_colors_done"].passed
        is True
    )
    assert (
        missing_by_name[
            "workflow_event_material_solver_cache_suggest_colors_done"
        ].passed
        is False
    )


def test_calibration_generate_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["calibration_generate"],
        event_counts={"calibration_generate_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["calibration_generate"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_calibration_generate_done"].passed is True
    assert missing_by_name["workflow_event_calibration_generate_done"].passed is False


def test_calibration_generate_single_stage_kit_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["calibration_generate_single_stage_kit"],
        event_counts={"calibration_generate_single_stage_kit_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["calibration_generate_single_stage_kit"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert (
        by_name["workflow_event_calibration_generate_single_stage_kit_done"].passed
        is True
    )
    assert (
        missing_by_name[
            "workflow_event_calibration_generate_single_stage_kit_done"
        ].passed
        is False
    )


def test_five_color_query_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["five_color_query"],
        event_counts={"five_color_query_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["five_color_query"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_five_color_query_done"].passed is True
    assert missing_by_name["workflow_event_five_color_query_done"].passed is False


def test_five_color_generate_swatch_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["five_color_generate_swatch"],
        event_counts={"five_color_generate_swatch_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["five_color_generate_swatch"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_five_color_generate_swatch_done"].passed is True
    assert (
        missing_by_name["workflow_event_five_color_generate_swatch_done"].passed
        is False
    )


def test_five_color_base_colors_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["five_color_base_colors"],
        event_counts={"five_color_base_colors_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["five_color_base_colors"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_five_color_base_colors_done"].passed is True
    assert missing_by_name["workflow_event_five_color_base_colors_done"].passed is False


def test_vectorize_image_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["vectorize_image"],
        event_counts={"vectorize_image_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["vectorize_image"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_vectorize_image_done"].passed is True
    assert missing_by_name["workflow_event_vectorize_image_done"].passed is False


def test_lut_merge_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["lut_merge"],
        event_counts={"lut_merge_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["lut_merge"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_lut_merge_done"].passed is True
    assert missing_by_name["workflow_event_lut_merge_done"].passed is False


def test_lut_compare_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["lut_compare"],
        event_counts={"lut_compare_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["lut_compare"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_lut_compare_done"].passed is True
    assert missing_by_name["workflow_event_lut_compare_done"].passed is False


def test_lut_details_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["lut_details"],
        event_counts={"lut_details_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["lut_details"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_lut_details_done"].passed is True
    assert missing_by_name["workflow_event_lut_details_done"].passed is False


def test_lut_upload_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["lut_upload"],
        event_counts={"lut_upload_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["lut_upload"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_lut_upload_done"].passed is True
    assert missing_by_name["workflow_event_lut_upload_done"].passed is False


def test_lut_session_info_workflow_requires_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["lut_session_info"],
        event_counts={"lut_session_info_done": 1},
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["lut_session_info"],
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_lut_session_info_done"].passed is True
    assert missing_by_name["workflow_event_lut_session_info_done"].passed is False


def test_replace_click_targets_filled_band_for_ring_fixture() -> None:
    payload = {"dimensions": {"width": 600, "height": 600}}

    assert _select_replace_click(payload) == (200, 300)


def test_check_result_evaluate_marks_passing_threshold() -> None:
    result = CheckResult.evaluate(
        name="observed_line_count",
        actual=18,
        operator="<=",
        threshold=30,
    )

    assert result.passed is True
    assert result.actual == 18
    assert result.threshold == 30


def test_check_result_evaluate_marks_failing_threshold() -> None:
    result = CheckResult.evaluate(
        name="no_unstructured_lines",
        actual=1,
        operator="==",
        threshold=0,
    )

    assert result.passed is False


def test_parse_json_object_accepts_prefixed_json() -> None:
    payload = parse_json_object('INFO {"event":"worker_pool_started","level":"INFO"}')

    assert payload == {"event": "worker_pool_started", "level": "INFO"}


def test_event_from_line_reports_unstructured_lines() -> None:
    event, structured = event_from_line("not-json")

    assert event == "unstructured"
    assert structured is False
