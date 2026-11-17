"""Selection, diagnostics, and aggregation of material verification runs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from core.filament_display import preview_step_indices
from . import material_calibration, material_files
from .kit import SINGLE_STAGE_SPEC, SingleStageSpec


def _extract_stage_a_vectors(
    params_payload: dict[str, Any],
) -> tuple[list[float], list[float], list[float], list[float]]:
    parameters = params_payload.get("parameters") or {}
    channels = parameters.get("channels") or []
    substrates = parameters.get("substrates") or []
    if not channels or not isinstance(channels[0], dict):
        raise ValueError("Stage A parameter payload is missing channel parameters")
    channel = channels[0]
    white_substrate = next(
        (
            substrate
            for substrate in substrates
            if isinstance(substrate, dict) and substrate.get("substrate_id") == "white"
        ),
        None,
    )
    black_substrate = next(
        (
            substrate
            for substrate in substrates
            if isinstance(substrate, dict) and substrate.get("substrate_id") == "black"
        ),
        None,
    )
    if not isinstance(white_substrate, dict) or not isinstance(black_substrate, dict):
        raise ValueError("Stage A parameter payload is missing white/black substrate parameters")

    try:
        e_values = [float(value) for value in list(channel.get("E") or [])]
        k_values = [float(value) for value in list(channel.get("k") or [])]
        white_c0_values = [float(value) for value in list(white_substrate.get("C0") or [])]
        black_c0_values = [float(value) for value in list(black_substrate.get("C0") or [])]
    except (TypeError, ValueError) as exc:
        raise ValueError("Stage A parameter payload contains non-numeric channel vectors") from exc

    vector_lengths = {len(e_values), len(k_values), len(white_c0_values), len(black_c0_values)}
    if vector_lengths != {3}:
        raise ValueError("Stage A parameter payload must contain 3-channel E/k/C0 vectors")
    return e_values, k_values, white_c0_values, black_c0_values


def _update_stage_a_payload_material_name(
    stage_a_payload: dict[str, Any],
    material_name: str,
) -> dict[str, Any]:
    updated_payload = material_files._json_clone(stage_a_payload)
    parameters = updated_payload.get("parameters")
    if isinstance(parameters, dict):
        channels = parameters.get("channels")
        if isinstance(channels, list) and channels and isinstance(channels[0], dict):
            channels[0]["color_name"] = material_name
    meta = updated_payload.get("meta")
    if isinstance(meta, dict) and "material_name" in meta:
        meta["material_name"] = material_name
    return updated_payload


def _build_verification_run(
    *,
    params_payload: dict[str, Any],
    fit_summary: dict[str, Any],
    material_summary: dict[str, Any],
    source_summary: dict[str, Any],
    captured_at: str | None = None,
) -> dict[str, Any]:
    e_values, k_values, white_c0_values, black_c0_values = _extract_stage_a_vectors(params_payload)
    samples = _normalize_fit_samples_payload(material_summary.get("fit_samples"))
    run: dict[str, Any] = {
        "captured_at": captured_at or material_files._now_iso(),
        "params": {
            "E": [round(float(value), 6) for value in e_values],
            "k": [round(float(value), 6) for value in k_values],
            "white_C0": [round(float(value), 6) for value in white_c0_values],
            "black_C0": [round(float(value), 6) for value in black_c0_values],
        },
        "fit_summary": material_files._json_clone(fit_summary),
        "material_summary": material_files._json_clone(material_summary),
        "source": material_files._json_clone(source_summary),
    }
    if samples is not None:
        run["samples"] = samples
    return run


def _normalize_fit_samples_payload(value: Any) -> dict[str, Any] | None:
    """Validate and normalize a stored ``fit_samples`` block.
    校验并规范化已存储的 ``fit_samples`` 数据块。

    Returns ``None`` when the block is missing or malformed (so the caller
    falls back to parameter-mean aggregation). Returned dict carries
    plain lists ready to be JSON-serialized; numerical conversion happens
    here so downstream code can rely on shape and dtype.
    缺失或格式异常时返回 ``None``，调用方将回退到参数均值聚合；返回的
    字典统一为 JSON 安全的 list 形态，避免下游再做形状检查。
    """
    if not isinstance(value, dict):
        return None
    thickness_raw = value.get("thickness_mm")
    white_raw = value.get("white_linear")
    black_raw = value.get("black_linear")
    if not isinstance(thickness_raw, list) or not isinstance(white_raw, list) or not isinstance(black_raw, list):
        return None
    try:
        thickness_mm = [float(v) for v in thickness_raw]
    except (TypeError, ValueError):
        return None
    if not thickness_mm:
        return None

    def _normalize_matrix(rows: list[Any], expected_rows: int) -> list[list[float]] | None:
        if len(rows) != expected_rows:
            return None
        normalized: list[list[float]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 3:
                return None
            try:
                normalized.append([float(v) for v in row])
            except (TypeError, ValueError):
                return None
        return normalized

    white_linear = _normalize_matrix(white_raw, len(thickness_mm))
    black_linear = _normalize_matrix(black_raw, len(thickness_mm))
    if white_linear is None or black_linear is None:
        return None
    return {
        "schema_version": str(value.get("schema_version") or "1.0"),
        "thickness_mm": thickness_mm,
        "white_linear": white_linear,
        "black_linear": black_linear,
    }


def _printed_board_thickness(archive: dict[str, Any]) -> float | None:
    source = archive.get("source")
    manifest = source.get("kit_manifest") if isinstance(source, dict) else None
    spec = manifest.get("spec") if isinstance(manifest, dict) else None
    if not isinstance(spec, dict):
        return None
    height, base, steps = (spec.get(key) for key in ("layer_height_mm", "base_mm", "max_step_layers"))
    short_edge = SINGLE_STAGE_SPEC.board_height_mm
    if not (
        type(height) in (int, float) and 0 < height <= short_edge
        and type(base) in (int, float) and 0 <= base <= short_edge
        and type(steps) is int and steps > 0
    ):
        return None
    kit = SingleStageSpec(layer_height_mm=height, base_mm=base, max_step_layers=steps)
    try:
        depth = (kit.base_layers + kit.max_step_layers) * kit.layer_height_mm
    except OverflowError:
        return None
    return round(depth, 4) if 0 < depth <= short_edge else None


def measured_gradient_preview(archive: dict[str, Any]) -> dict[str, Any]:
    """Project one saved calibration capture's paired observations into a thumbnail."""
    summary = archive.get("material_summary")
    runs = archive.get("verification_runs")
    candidates = [summary.get("fit_samples")] if isinstance(summary, dict) else []
    if isinstance(runs, list):
        candidates.extend(run.get("samples") for run in reversed(runs) if isinstance(run, dict))
    for candidate in candidates:
        samples = _normalize_fit_samples_payload(candidate)
        if samples is None:
            continue
        thickness = np.asarray(samples["thickness_mm"])
        observations = np.asarray([samples["black_linear"], samples["white_linear"]])
        if (
            not np.isfinite(thickness).all() or (thickness < 0).any()
            or not np.isfinite(observations).all() or (observations < 0).any() or (observations > 1).any()
        ):
            continue
        _, ordered = np.unique(thickness, return_index=True)
        if len(ordered) < 2:
            continue
        indices = ordered[preview_step_indices(len(ordered))]
        colors = material_calibration._linear_to_srgb_uint8(observations[:, indices])
        swatches = {"source": "measured", "black": colors[0].tolist(), "white": colors[1].tolist()}
        depth = _printed_board_thickness(archive)
        if depth is not None:
            swatches["board_thickness_mm"] = depth
        return {"preview_swatches": swatches}
    return {}


def _load_existing_verification_runs(
    material_dir: Path,
    archive_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    stored_runs = archive_payload.get("verification_runs")
    if isinstance(stored_runs, list) and stored_runs:
        return [material_files._json_clone(run) for run in stored_runs if isinstance(run, dict)]

    stage_a_filename = str(archive_payload.get("stage_a_params_file") or "stage_A_parameters.json")
    stage_a_path = material_dir / stage_a_filename
    if not stage_a_path.exists():
        return []
    try:
        params_payload = json.loads(stage_a_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    try:
        seeded_run = _build_verification_run(
            params_payload=params_payload,
            fit_summary=archive_payload.get("fit_summary") or {},
            material_summary=archive_payload.get("material_summary") or {},
            source_summary=archive_payload.get("source") or {},
            captured_at=str(
                archive_payload.get("updated_at")
                or archive_payload.get("created_at")
                or material_files._now_iso()
            ),
        )
    except ValueError:
        return []
    return [seeded_run]


def _average_numeric_vectors(vectors: list[list[float]], fallback: list[float]) -> list[float]:
    expected_length = len(fallback)
    normalized: list[list[float]] = []
    for vector in vectors:
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError):
            continue
        if len(values) != expected_length:
            continue
        normalized.append(values)
    if not normalized:
        return [float(value) for value in fallback]
    return np.mean(np.asarray(normalized, dtype=np.float64), axis=0).tolist()


def _collect_combined_run_samples(
    verification_runs: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Concatenate ``samples`` from every run when *all* runs have them.
    若所有 run 都带样本则将其拼接。

    Returns ``None`` when any run is missing samples or has shape errors,
    forcing the caller to fall back to parameter-mean aggregation. We require
    completeness instead of mixing samples-vs-mean to keep the aggregation
    semantics single-method-per-archive (so ``aggregation_method`` is a
    truthful single value rather than a per-run patchwork).
    任何 run 缺样本或形状不一致时返回 ``None``，强制调用方使用参数均值；
    保持每次聚合采用单一方法，便于追踪 ``aggregation_method``。
    """
    if not verification_runs:
        return None
    thickness_chunks: list[np.ndarray] = []
    white_chunks: list[np.ndarray] = []
    black_chunks: list[np.ndarray] = []
    for run in verification_runs:
        samples = _normalize_fit_samples_payload(run.get("samples"))
        if samples is None:
            return None
        thickness = np.asarray(samples["thickness_mm"], dtype=np.float64)
        white = np.asarray(samples["white_linear"], dtype=np.float64)
        black = np.asarray(samples["black_linear"], dtype=np.float64)
        if thickness.ndim != 1 or thickness.size == 0:
            return None
        if white.shape != (thickness.size, 3) or black.shape != (thickness.size, 3):
            return None
        thickness_chunks.append(thickness)
        white_chunks.append(white)
        black_chunks.append(black)
    return (
        np.concatenate(thickness_chunks, axis=0),
        np.concatenate(white_chunks, axis=0),
        np.concatenate(black_chunks, axis=0),
    )


def _refit_combined_samples(
    thickness_mm: np.ndarray,
    white_linear: np.ndarray,
    black_linear: np.ndarray,
) -> tuple[
    list[float], list[float], list[float], list[float], list[float], dict[str, float]
]:
    """Run a fresh per-channel ``_fit_component`` on combined samples.
    在合并样本上重新执行逐通道 ``_fit_component`` 拟合。

    Statistical rationale: averaging Beer-Lambert ``(E, k)`` is invalid
    because the model is non-linear in ``k``. Concatenating samples and
    refitting is the correct generalization of "more data = tighter fit"
    and is the only way the verification count actually improves accuracy.
    Beer-Lambert 在 ``k`` 上是非线性的，对参数取均值无统计意义；合并样
    本重拟合才是"多次校准 = 更精确"的正确实现。

    Returns:
        ``(E, k, C0_white, C0_black, channel_rmse, overall_validation)``.
    """
    e_values: list[float] = []
    k_values: list[float] = []
    c0_white_values: list[float] = []
    c0_black_values: list[float] = []
    channel_rmse: list[float] = []
    for channel_idx in range(3):
        e_val, k_val, c0_white, c0_black, rmse = material_calibration._fit_component(
            thickness_mm,
            white_linear[:, channel_idx],
            black_linear[:, channel_idx],
        )
        e_values.append(e_val)
        k_values.append(k_val)
        c0_white_values.append(c0_white)
        c0_black_values.append(c0_black)
        channel_rmse.append(rmse)

    e_arr = np.asarray(e_values, dtype=np.float64)
    k_arr = np.asarray(k_values, dtype=np.float64)
    c0w_arr = np.asarray(c0_white_values, dtype=np.float64)
    c0b_arr = np.asarray(c0_black_values, dtype=np.float64)
    decay = np.exp(-np.outer(thickness_mm, k_arr))
    pred_white = e_arr + (c0w_arr - e_arr) * decay
    pred_black = e_arr + (c0b_arr - e_arr) * decay
    observed_linear = np.vstack([white_linear, black_linear])
    predicted_linear = np.vstack([pred_white, pred_black])
    observed_srgb = material_calibration._linear_to_srgb_uint8(observed_linear)
    predicted_srgb = material_calibration._linear_to_srgb_uint8(predicted_linear)
    delta_e = np.linalg.norm(
        material_calibration._rgb_to_lab_float(observed_srgb) - material_calibration._rgb_to_lab_float(predicted_srgb), axis=1
    )
    overall_validation: dict[str, float] = {
        "mean_delta_e": float(np.mean(delta_e)) if delta_e.size else 0.0,
        "max_delta_e": float(np.max(delta_e)) if delta_e.size else 0.0,
        "rmse_linear": float(np.sqrt(np.mean(np.square(predicted_linear - observed_linear))))
        if observed_linear.size
        else 0.0,
    }
    return e_values, k_values, c0_white_values, c0_black_values, channel_rmse, overall_validation


def _coerce_image_source(value: Any) -> str | None:
    """Normalize a stored ``image_source`` value to a known tag or ``None``.
    将持久化的 ``image_source`` 标签归一化为已知值或 ``None``。

    Returns ``None`` for missing / non-string / unknown values so legacy
    archives written before the tag existed are treated as "unknown" and
    do not block re-verification merges. Known tags are normalized to
    lowercase to make matching case-insensitive.
    历史档案缺失该字段或为非法值时返回 ``None``，不阻塞合并；已知值统一
    转小写以做大小写无关匹配。
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if candidate not in material_calibration._VALID_IMAGE_SOURCES:
        return None
    return candidate


def _collect_run_image_sources(
    verification_runs: list[dict[str, Any]],
) -> set[str]:
    """Return the set of known ``image_source`` tags across the given runs.
    提取已知 ``image_source`` 标签集合。

    Runs whose source lacks the tag (legacy archives) contribute nothing
    so the merge consistency check only fires when at least one run
    carries an explicit, recognised tag.
    """
    seen: set[str] = set()
    for run in verification_runs:
        source = run.get("source")
        if not isinstance(source, dict):
            continue
        tag = _coerce_image_source(source.get("image_source"))
        if tag is not None:
            seen.add(tag)
    return seen


def _collect_run_warnings(verification_runs: list[dict[str, Any]]) -> list[str]:
    """Union of all run-level fit warnings, deduplicated and sorted.
    汇总所有 run 的拟合警告并去重排序。
    """
    warning_values: list[str] = []
    for run in verification_runs:
        run_fit_summary = run.get("fit_summary") or {}
        if not isinstance(run_fit_summary, dict):
            continue
        run_warnings = run_fit_summary.get("warnings")
        if isinstance(run_warnings, list):
            warning_values.extend(str(value) for value in run_warnings if str(value).strip())
    return sorted(dict.fromkeys(warning_values))


# --- Multi-run selection: bias filter + cross-validation -----------------
#
# Why this exists: when more than one verification_run lives in an archive,
# blindly concatenating every run's samples lets a single biased capture
# (e.g. white-balanced input pushing C0_white to ~1.0) drag the joint LM
# fit toward physically wrong (E, k). The fit RMSE may even look BETTER
# under bias because the model bends to fit the biased data perfectly,
# which is exactly the trap "low ΔE != accurate" warned about during the
# 品红 calibration debugging session.
#
# The mitigation has two layers:
#
#   1. ``_score_run_bias`` flags KNOWN bias indicators on each run
#      (C0_white avg > 0.95, image_source=restored, flat substrate,
#      unreliable orientation). Scoring is independent of the run's own
#      fit metrics so a "self-consistently biased" run cannot hide.
#
#   2. ``_cross_val_score_runs`` (only when N>=3) measures how well each
#      run's ``(E, k)`` predicts the OTHER runs' samples. A biased run
#      fits itself but generalises poorly, so its cross-val mean ΔE is
#      high. This catches "unknown unknown" biases that 1) misses.
#
# ``_select_runs_for_refit`` composes the two: hard-filter by bias first,
# then optionally rank survivors by cross-val. The fresh run (last in the
# list) is ALWAYS kept regardless of its bias score because the user just
# captured it on purpose; we let the operator inspect the diagnostics
# instead of silently discarding their freshest input.
#
# 多 run 选择：偏置硬过滤 + 跨 run 交叉验证。低 ΔE 不等于准确，配合时既筛
# 掉已知偏置 run，又通过 N>=3 时的 cross-val 抓"未知偏置"。新 run（列表
# 末尾）始终保留，便于审计。
_BIAS_FLAG_C0_WHITE_HIGH = "c0_white_avg_gt_0_95"

_BIAS_FLAG_C0_WHITE_LOW = "c0_white_avg_lt_0_60"

_BIAS_FLAG_IMAGE_SOURCE_RESTORED = "image_source_restored"

_BIAS_FLAG_WHITE_SUBSTRATE_FLAT = "white_substrate_flat"

_BIAS_FLAG_BLACK_SUBSTRATE_FLAT = "black_substrate_flat"

_BIAS_FLAG_ORIENTATION_UNRELIABLE = "orientation_unreliable"

_BIAS_FLAG_MEAN_DE_HIGH = "mean_de_gt_3"

_BIAS_FLAG_C0_SESSION_OUTLIER = "c0_session_outlier"


# Single-run thresholds. Pinned at the module level so tests, frontend
# i18n and any future docs reference one canonical number.
# 单 run 阈值集中在模块级，避免散落在判定逻辑中难以维护。
_C0_WHITE_AVG_HIGH_THRESHOLD = 0.95

_C0_WHITE_AVG_LOW_THRESHOLD = 0.60

_MEAN_DELTA_E_HIGH_THRESHOLD = 3.0


# Cross-run pairwise threshold: two captures whose white_C0 averages
# differ by more than this multiplicative factor cannot share a single
# joint Beer-Lambert fit (the cost surface has no consistent (E, k) for
# both lighting environments). Ratio is computed as max/min so it is
# direction-agnostic.
# 跨 run 白底亮度比阈值；超过即视为光照环境不一致，无法共拟合。
_C0_WHITE_PAIRWISE_RATIO_THRESHOLD = 1.5


# Cross-material session reference thresholds. A run trips the session
# outlier flag when *any* of its three white_C0 channels is more than
# ``_C0_SESSION_OUTLIER_ABS_THRESHOLD`` (linear-RGB units, absolute) OR
# ``_C0_SESSION_OUTLIER_REL_THRESHOLD`` (proportional, vs the session
# median) away from the session median. Either guard is a hit so we
# catch both bright-room shifts (small relative, big absolute on dark
# channels) and dark-room shifts (small absolute, large relative).
# Default window is 24 h: the same operator-session timeframe.
# 跨材料 session 中位数比对阈值；任一通道超过绝对阈值或相对阈值即触发，
# 兼顾亮室漂移（绝对差大）与暗室漂移（相对差大）。默认 24 小时窗口。
_C0_SESSION_OUTLIER_ABS_THRESHOLD = 0.05

_C0_SESSION_OUTLIER_REL_THRESHOLD = 0.05

_C0_SESSION_WINDOW_HOURS = 24.0


# Structural-bias flags: each indicates the *physics* of the capture
# is compromised (white-balanced input, underexposed input, restored
# image, flat substrate, or fit metrics already untrustworthy), so
# dropping a strictly-worse-than-fresh run is justified.
# 结构性偏置标签：捕获本身的物理意义被破坏，可作为硬过滤依据。
_STRUCTURAL_BIAS_FLAGS = frozenset(
    {
        _BIAS_FLAG_C0_WHITE_HIGH,
        _BIAS_FLAG_C0_WHITE_LOW,
        _BIAS_FLAG_IMAGE_SOURCE_RESTORED,
        _BIAS_FLAG_WHITE_SUBSTRATE_FLAT,
        _BIAS_FLAG_BLACK_SUBSTRATE_FLAT,
        _BIAS_FLAG_MEAN_DE_HIGH,
        _BIAS_FLAG_C0_SESSION_OUTLIER,
    }
)


# Advisory flags: surfaced in the UI for awareness but not used for the
# strict-worse comparison. Orientation reliability depends on the
# ``delta_e_gap`` margin between top orientation candidates, which is
# stochastic in noisy captures — flagging a run for orientation alone
# would give false positives on otherwise-fine inputs.
# 提示性标签：仅在 UI 中展示，不参与硬过滤；朝向可靠性会随噪声波动，
# 单凭它丢 run 容易误伤。
_ADVISORY_BIAS_FLAGS = frozenset(
    {
        _BIAS_FLAG_ORIENTATION_UNRELIABLE,
    }
)


def _safe_mean(values: list[float] | None) -> float | None:
    if not values:
        return None
    try:
        arr = np.asarray([float(v) for v in values], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if arr.size == 0:
        return None
    return float(np.mean(arr))


def _score_run_bias(run: dict[str, Any]) -> dict[str, Any]:
    """Compute bias indicators for a single verification run.
    为单个 verification run 计算偏置指标。

    Each detected indicator pushes the run toward exclusion from the joint
    refit. Indicators are intentionally *physical* / structural, never
    derived from the run's own fit ΔE: a self-consistently biased capture
    produces low ΔE precisely because the model bends to fit its biased
    data, so ΔE-based scores would silently approve those runs.
    每个指标都是物理 / 结构性的，**不**用 run 自身的 ΔE，因为"自我一致地
    偏置"的捕获 ΔE 反而会很低、骗过基于 ΔE 的打分器。

    Args:
        run: A single ``verification_runs[*]`` dict as persisted on disk.
            (磁盘上单条 verification_runs 字典)

    Returns:
        ``{"bias_flag_count": int, "bias_flags": list[str], "white_c0_avg":
        float | None, "image_source": str | None}``. ``bias_flags`` uses
        the stable ``_BIAS_FLAG_*`` codes so frontend i18n can map them
        to localised labels without parsing free text.
    """
    flags: list[str] = []
    params = run.get("params") if isinstance(run.get("params"), dict) else {}
    white_c0 = params.get("white_C0") if isinstance(params, dict) else None
    white_c0_avg = _safe_mean(white_c0 if isinstance(white_c0, list) else None)
    if white_c0_avg is not None and white_c0_avg > _C0_WHITE_AVG_HIGH_THRESHOLD:
        flags.append(_BIAS_FLAG_C0_WHITE_HIGH)
    # Mirror image of the high-white check: severely underexposed
    # captures land white_C0 below the typical PLA white substrate
    # band (0.85-0.92). Below 0.60 the dynamic range squeezes so much
    # that LM has to inflate ``k`` to bend exp through near-step data,
    # producing physically meaningless parameters.
    # 白底过暗（<0.60）会压扁动态范围导致拟合失真。
    if white_c0_avg is not None and white_c0_avg < _C0_WHITE_AVG_LOW_THRESHOLD:
        flags.append(_BIAS_FLAG_C0_WHITE_LOW)

    source = run.get("source") if isinstance(run.get("source"), dict) else {}
    image_source = source.get("image_source") if isinstance(source, dict) else None
    image_source_str = str(image_source) if isinstance(image_source, str) else None
    if image_source_str == "restored":
        flags.append(_BIAS_FLAG_IMAGE_SOURCE_RESTORED)

    fit_summary = run.get("fit_summary") if isinstance(run.get("fit_summary"), dict) else {}
    ranking = (
        fit_summary.get("orientation_ranking")
        if isinstance(fit_summary, dict)
        else None
    )

    if isinstance(ranking, dict):
        white_info = ranking.get("white_orientation_info")
        if isinstance(white_info, dict) and white_info.get("flat") is True:
            flags.append(_BIAS_FLAG_WHITE_SUBSTRATE_FLAT)
        black_info = ranking.get("black_orientation_info")
        if isinstance(black_info, dict) and black_info.get("flat") is True:
            flags.append(_BIAS_FLAG_BLACK_SUBSTRATE_FLAT)
        if ranking.get("orientation_reliable") is False:
            flags.append(_BIAS_FLAG_ORIENTATION_UNRELIABLE)

    # The run's own goodness-of-fit guards "garbage in, garbage out":
    # if a single capture's mean ΔE is already above 3.0 (the
    # printer-profile "borderline acceptable" line), feeding its
    # samples into a joint refit can only drag the merged (E, k)
    # toward this run's distorted fit.
    # 单 run mean_dE>3 表示拟合已不可信，禁止其参与联合重拟。
    overall_validation = (
        fit_summary.get("overall_validation")
        if isinstance(fit_summary, dict)
        else None
    )
    if isinstance(overall_validation, dict):
        mean_de = overall_validation.get("mean_delta_e")
        if (
            isinstance(mean_de, (int, float))
            and not isinstance(mean_de, bool)
            and float(mean_de) > _MEAN_DELTA_E_HIGH_THRESHOLD
        ):
            flags.append(_BIAS_FLAG_MEAN_DE_HIGH)

    structural_flags = [flag for flag in flags if flag in _STRUCTURAL_BIAS_FLAGS]
    return {
        "bias_flag_count": len(flags),
        "bias_flags": flags,
        # ``structural_flag_count`` drives the strict-worse comparison
        # in :func:`_select_runs_for_refit`; advisory flags such as
        # ``orientation_unreliable`` show up in ``bias_flags`` for UI
        # awareness but do NOT make a run "structurally biased".
        # 仅结构性标签参与硬过滤；提示性标签只在 UI 中展示。
        "structural_flag_count": len(structural_flags),
        "structural_flags": structural_flags,
        "white_c0_avg": white_c0_avg,
        "image_source": image_source_str,
    }


def _predict_substrate_linear(
    e_values: np.ndarray,
    k_values: np.ndarray,
    c0_values: np.ndarray,
    thickness_mm: np.ndarray,
) -> np.ndarray:
    """Forward Beer-Lambert: predict linear-RGB observations.
    Beer-Lambert 前向：根据 (E, k, C0) 预测线性 RGB 观测值。

    Vectorised over samples and channels: ``pred[s, c] = E[c] + (C0[c] -
    E[c]) * exp(-k[c] * t[s])``.
    """
    decay = np.exp(-k_values[None, :] * thickness_mm[:, None])
    return e_values[None, :] + (c0_values[None, :] - e_values[None, :]) * decay


def _cross_val_score_runs(
    verification_runs: list[dict[str, Any]],
    candidate_indices: list[int],
) -> dict[int, float]:
    """Score each candidate run by how well it predicts OTHER candidates.
    用每个候选 run 拟合的 (E, k) 预测其他候选 run 的样本，得分越低越好。

    Algorithm: for each candidate ``R`` in ``candidate_indices``, fit
    ``(E, k, C0_white, C0_black)`` per channel using only ``R``'s
    samples, then predict the union of all OTHER candidates' samples
    using ``R``'s parameters and report the linear-space RMSE.

    A biased run fits itself perfectly (low intra-run RMSE) but produces
    parameters that fail to explain other captures, yielding a HIGH
    cross-val RMSE. An unbiased run yields a low one. This generalises
    "low ΔE != accurate" detection beyond the hand-coded bias flags.

    Args:
        verification_runs: Full archive list (only the entries at
            ``candidate_indices`` are touched). (完整 verification_runs)
        candidate_indices: Indices to score. Need at least 2; with 1 the
            score is undefined and this function returns an empty dict.
            (候选索引列表，<2 时返回空 dict)

    Returns:
        Mapping from candidate index to cross-val RMSE in linear RGB
        space. Lower = more accurate / less biased.
        (候选索引 -> 线性 RGB 空间 cross-val RMSE 映射)
    """
    if len(candidate_indices) < 2:
        return {}

    samples_per_index: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for idx in candidate_indices:
        run = verification_runs[idx]
        normalized = _normalize_fit_samples_payload(run.get("samples"))
        if normalized is None:
            continue
        thickness = np.asarray(normalized["thickness_mm"], dtype=np.float64)
        white = np.asarray(normalized["white_linear"], dtype=np.float64)
        black = np.asarray(normalized["black_linear"], dtype=np.float64)
        if thickness.ndim != 1 or thickness.size == 0:
            continue
        if white.shape != (thickness.size, 3) or black.shape != (thickness.size, 3):
            continue
        samples_per_index[idx] = (thickness, white, black)

    if len(samples_per_index) < 2:
        return {}

    scores: dict[int, float] = {}
    for fit_idx, (fit_t, fit_white, fit_black) in samples_per_index.items():
        e_values: list[float] = []
        k_values: list[float] = []
        c0_white_values: list[float] = []
        c0_black_values: list[float] = []
        for channel in range(3):
            e_val, k_val, c0_white, c0_black, _rmse = material_calibration._fit_component(
                fit_t,
                fit_white[:, channel],
                fit_black[:, channel],
            )
            e_values.append(e_val)
            k_values.append(k_val)
            c0_white_values.append(c0_white)
            c0_black_values.append(c0_black)
        e_arr = np.asarray(e_values, dtype=np.float64)
        k_arr = np.asarray(k_values, dtype=np.float64)
        c0w_arr = np.asarray(c0_white_values, dtype=np.float64)
        c0b_arr = np.asarray(c0_black_values, dtype=np.float64)

        residual_chunks: list[np.ndarray] = []
        for other_idx, (other_t, other_white, other_black) in samples_per_index.items():
            if other_idx == fit_idx:
                continue
            pred_white = _predict_substrate_linear(e_arr, k_arr, c0w_arr, other_t)
            pred_black = _predict_substrate_linear(e_arr, k_arr, c0b_arr, other_t)
            residual_chunks.append((pred_white - other_white).reshape(-1))
            residual_chunks.append((pred_black - other_black).reshape(-1))
        if not residual_chunks:
            continue
        residual = np.concatenate(residual_chunks, axis=0)
        scores[fit_idx] = float(np.sqrt(np.mean(np.square(residual))))

    return scores


# ---------------------------------------------------------------------------
# Cross-material session reference for white_C0 consistency
# 跨材料 session 级白底参考
# ---------------------------------------------------------------------------


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp into a timezone-aware :class:`datetime`.
    将 ISO-8601 时间戳解析为带时区的 datetime。

    Returns ``None`` for any input that cannot be parsed (non-string,
    malformed, etc.) so the caller can simply skip rows whose
    ``captured_at`` is missing rather than abort the whole walk.
    解析失败返回 None，调用方按 row 级跳过即可。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # ``datetime.fromisoformat`` only learned to accept the ``Z`` suffix
    # in 3.11; normalise to ``+00:00`` for older interpreters.
    # ``fromisoformat`` 在 3.11 之前不接受 ``Z`` 后缀；统一改写。
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _collect_session_white_c0_samples(
    materials_root: Path,
    *,
    image_source: str | None,
    captured_at: datetime | None,
    window_hours: float = _C0_SESSION_WINDOW_HOURS,
    exclude_directory: Path | None = None,
) -> list[dict[str, Any]]:
    """Collect ``white_C0`` readings from other materials in the same session.
    从同一 session 的其他材料里收集 ``white_C0`` 读数。

    A "session" is the set of captures sharing the same ``image_source``
    and falling within ``window_hours`` of ``captured_at``. The current
    material being saved (``exclude_directory``) is intentionally
    skipped so its own white reading does not anchor the median against
    which it will be compared.
    "session" 定义为同 ``image_source`` 且 ``captured_at`` 在窗口内的样本集合；
    保存中的材料目录会被显式排除，避免自我参照。

    Args:
        materials_root: Root directory containing saved material archives. (耗材根目录)
        image_source: Required match for each candidate run. ``None``
            matches runs that have no recorded image_source. (匹配 image_source)
        captured_at: Anchor timestamp; ``None`` disables the time-window
            filter (used for tests / batch revalidation). (锚定时间)
        window_hours: Half-window size in hours. (窗口半径，小时)
        exclude_directory: Material directory to skip during the walk. (排除目录)

    Returns:
        List of ``{"directory", "captured_at", "white_C0"}`` rows;
        empty when no qualifying samples were found. (匹配样本列表)
    """
    if not materials_root.exists():
        return []
    samples: list[dict[str, Any]] = []
    exclude_resolved = (
        exclude_directory.resolve() if exclude_directory is not None else None
    )
    delta_max = timedelta(hours=float(window_hours))
    for archive_path in materials_root.rglob("material.json"):
        try:
            if not archive_path.is_file():
                continue
            material_dir = archive_path.parent.resolve()
            if exclude_resolved is not None and material_dir == exclude_resolved:
                continue
            payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # Corrupt / unreadable archives are silently skipped: the
            # session check is opportunistic, not a load-time validator.
            # 损坏档案静默跳过；该层是机会性检查，不承担加载校验职责。
            continue
        runs = payload.get("verification_runs")
        if not isinstance(runs, list):
            continue
        archive_aggregation = (
            payload.get("aggregation")
            if isinstance(payload.get("aggregation"), dict)
            else {}
        )
        archive_image_source = (
            archive_aggregation.get("image_source")
            if isinstance(archive_aggregation, dict)
            else None
        )
        archive_image_source_str = (
            str(archive_image_source)
            if isinstance(archive_image_source, str)
            else None
        )
        for run in runs:
            if not isinstance(run, dict):
                continue
            run_source = (
                run.get("source") if isinstance(run.get("source"), dict) else {}
            )
            run_image_source_value = (
                run_source.get("image_source") if isinstance(run_source, dict) else None
            )
            run_image_source = (
                str(run_image_source_value)
                if isinstance(run_image_source_value, str)
                else archive_image_source_str
            )
            if image_source != run_image_source:
                continue
            run_captured = _parse_iso_datetime(run.get("captured_at"))
            if captured_at is not None:
                if run_captured is None:
                    continue
                if abs(run_captured - captured_at) > delta_max:
                    continue
            params = (
                run.get("params") if isinstance(run.get("params"), dict) else {}
            )
            white_c0_raw = params.get("white_C0") if isinstance(params, dict) else None
            if not isinstance(white_c0_raw, list) or len(white_c0_raw) != 3:
                continue
            try:
                values = [float(v) for v in white_c0_raw]
            except (TypeError, ValueError):
                continue
            samples.append(
                {
                    "directory": str(material_dir),
                    "captured_at": run.get("captured_at"),
                    "white_C0": values,
                }
            )
    return samples


def _compute_session_white_c0_reference(
    materials_root: Path | None,
    *,
    image_source: str | None,
    captured_at_iso: str | None,
    window_hours: float = _C0_SESSION_WINDOW_HOURS,
    exclude_directory: Path | None = None,
) -> dict[str, Any] | None:
    """Compute the per-channel median ``white_C0`` across the session.
    计算同一 session 内的 ``white_C0`` 逐通道中位数。

    Returns ``None`` when no qualifying samples exist (greenfield
    materials root, mismatched image source, archives outside the time
    window). The ``_select_runs_for_refit`` layer treats ``None`` as
    "skip the session check" so first-time calibrations don't trip on
    an empty reference.
    无可用样本时返回 None；selection 层视为"跳过本层"，避免在首次校准时
    把唯一的 fresh run 排除。
    """
    if materials_root is None:
        return None
    captured_at = _parse_iso_datetime(captured_at_iso)
    samples = _collect_session_white_c0_samples(
        materials_root,
        image_source=image_source,
        captured_at=captured_at,
        window_hours=window_hours,
        exclude_directory=exclude_directory,
    )
    if not samples:
        return None
    arr = np.asarray([s["white_C0"] for s in samples], dtype=np.float64)
    median = np.median(arr, axis=0)
    return {
        "median": [float(v) for v in median.tolist()],
        "sample_count": int(arr.shape[0]),
        "image_source": image_source,
        "window_hours": float(window_hours),
        "abs_threshold": _C0_SESSION_OUTLIER_ABS_THRESHOLD,
        "rel_threshold": _C0_SESSION_OUTLIER_REL_THRESHOLD,
        "captured_at_anchor": captured_at_iso,
    }


def _check_run_against_session_c0(
    run: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any] | None:
    """Test a single run's ``white_C0`` against the session reference.
    将单个 run 的 ``white_C0`` 与 session 中位数对比。

    Returns ``None`` when the run is within tolerance, or a diagnostic
    dict (``run_white_c0``, ``session_median``, ``max_abs_diff``,
    ``max_rel_diff``, thresholds, ``sample_count``) when it trips the
    outlier rule. The diagnostic is wired straight into the
    ``selection.excluded_runs`` audit list so the UI can render a
    concrete "your run vs session" comparison.
    通过返回 None；越界返回诊断字典直接拼到 ``excluded_runs`` 供前端展示。
    """
    params = run.get("params") if isinstance(run.get("params"), dict) else {}
    white_c0_raw = params.get("white_C0") if isinstance(params, dict) else None
    if not isinstance(white_c0_raw, list) or len(white_c0_raw) != 3:
        return None
    try:
        values = np.asarray([float(v) for v in white_c0_raw], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    median_list = reference.get("median")
    if not isinstance(median_list, list) or len(median_list) != 3:
        return None
    try:
        median = np.asarray([float(v) for v in median_list], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    abs_diff = np.abs(values - median)
    safe_denom = np.maximum(np.abs(median), 1e-6)
    rel_diff = abs_diff / safe_denom
    max_abs = float(abs_diff.max())
    max_rel = float(rel_diff.max())
    abs_threshold = float(
        reference.get("abs_threshold", _C0_SESSION_OUTLIER_ABS_THRESHOLD)
    )
    rel_threshold = float(
        reference.get("rel_threshold", _C0_SESSION_OUTLIER_REL_THRESHOLD)
    )
    if max_abs <= abs_threshold and max_rel <= rel_threshold:
        return None
    return {
        "run_white_c0": values.tolist(),
        "session_median": median.tolist(),
        "max_abs_diff": max_abs,
        "max_rel_diff": max_rel,
        "abs_threshold": abs_threshold,
        "rel_threshold": rel_threshold,
        "sample_count": int(reference.get("sample_count") or 0),
    }


def _select_runs_for_refit(
    verification_runs: list[dict[str, Any]],
    *,
    cross_val_threshold: int = 3,
    session_white_c0_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pick which runs participate in the joint refit.
    选择哪些 run 参与联合重拟合。

    Selection policy (two-layer):

    1. **Bias filter**: a historical run is dropped when it carries
       *strictly more* bias flags than the fresh run. Equal-or-fewer
       flags are kept so the joint refit can still benefit from extra
       samples when both the fresh capture and the historical share
       the same level of bias (e.g. both ``image_source=restored``).
       There is no "graceful degradation" that keeps a strictly-worse
       historical: if every historical is worse than the fresh run we
       fall back to a single-run refit on the fresh capture alone,
       because adding biased samples to the LM cost would corrupt
       ``(E, k)`` more than helping precision.
    2. **Cross-val ranking**: when ``cross_val_threshold`` or more
       historical runs survive the bias filter, score them by how well
       each predicts the others (lower RMSE = more accurate); keep the
       top ``ceil(N/2)`` (at least one). With N<threshold the cross-val
       tie-breaker is skipped — too few candidates to detect bias by
       mutual disagreement.

    The fresh run (assumed to be the LAST entry in ``verification_runs``)
    is always kept so the user's most recent capture cannot be silently
    discarded — surfacing it lets the operator see why their workflow
    is flagged instead of pretending the capture never happened.

    Args:
        verification_runs: Full chronological list as persisted on disk.
            (完整按时间排序的 verification_runs)
        cross_val_threshold: Minimum surviving historical count required
            to enable cross-val ranking. Defaults to 3 because cross-val
            on 2 runs only checks "do they agree", not "which is right".
            (启用 cross-val 的最小存活历史数量；2 个时只能查"是否一致")

    Returns:
        Dict with keys:
          - ``selected_indices``: sorted list of indices to refit on
          - ``excluded_runs``: list of dicts ``{index, reason, score?,
            bias_flags}`` for audit / UI display
          - ``selection_strategy``: stable string code identifying which
            policy ran (``bias_filter_v1`` vs ``bias_filter_v1+cross_val``)
          - ``run_scores``: per-run diagnostic dict (always present, lets
            UI show every run's bias flags + cross-val score even when no
            run was excluded)
          - ``fresh_index``: the index of the run that was force-kept
    """
    if not verification_runs:
        return {
            "selected_indices": [],
            "excluded_runs": [],
            "selection_strategy": "bias_filter_v1",
            "run_scores": [],
            "fresh_index": None,
        }

    fresh_index = len(verification_runs) - 1
    historical_indices = list(range(fresh_index))

    run_scores: list[dict[str, Any]] = []
    for idx, run in enumerate(verification_runs):
        bias = _score_run_bias(run)
        run_scores.append(
            {
                "index": idx,
                "is_fresh": idx == fresh_index,
                "bias_flag_count": bias["bias_flag_count"],
                "bias_flags": bias["bias_flags"],
                "structural_flag_count": bias["structural_flag_count"],
                "structural_flags": bias["structural_flags"],
                "white_c0_avg": bias["white_c0_avg"],
                "image_source": bias["image_source"],
                "cross_val_rmse": None,
            }
        )

    excluded: list[dict[str, Any]] = []

    # --- Layer 1: bias filter on historical runs ---
    # Drop historicals strictly worse (more *structural* flags) than the
    # fresh run. We use ``structural_flag_count``, not the broader
    # ``bias_flag_count``, because advisory flags like
    # ``orientation_unreliable`` are signal-to-noise driven and would
    # cause spurious drops on equally-good captures whose noise
    # happens to land just below the orientation_ranker threshold.
    # 仅按"结构性"偏置标签做硬过滤；提示性标签会在 UI 中展示但不参与丢
    # 弃决策，避免噪声驱动的朝向标志误伤同等水平的历史 run。
    fresh_struct_flags = run_scores[fresh_index]["structural_flag_count"]
    clean_historical = [
        i
        for i in historical_indices
        if run_scores[i]["structural_flag_count"] <= fresh_struct_flags
    ]
    for i in historical_indices:
        if i in clean_historical:
            continue
        excluded.append(
            {
                "index": i,
                "reason": "bias_filter",
                "bias_flags": list(run_scores[i]["bias_flags"]),
                "structural_flags": list(run_scores[i]["structural_flags"]),
            }
        )

    selection_strategy = "bias_filter_v1"

    # --- Layer 1.5: pairwise white_C0 mismatch vs fresh ---
    # Two runs whose white_C0 averages differ by more than
    # ``_C0_WHITE_PAIRWISE_RATIO_THRESHOLD`` cannot share a single
    # joint refit: the cost surface has no consistent (E, k) for both
    # lighting environments. The fresh run is the canonical reference
    # (the operator just captured it on purpose), so the historical
    # is the one excluded. We compute ratio = max/min so the rule is
    # symmetric whether the fresh is brighter or darker.
    # 跨 run 的成对白底比较：与新 run 偏离超过 1.5× 即视为光照不一致，
    # 剔除历史 run。
    fresh_white_c0 = run_scores[fresh_index]["white_c0_avg"]
    if (
        isinstance(fresh_white_c0, (int, float))
        and not isinstance(fresh_white_c0, bool)
        and fresh_white_c0 > 0.0
    ):
        survived_pairwise: list[int] = []
        for i in clean_historical:
            run_white_c0 = run_scores[i]["white_c0_avg"]
            if (
                not isinstance(run_white_c0, (int, float))
                or isinstance(run_white_c0, bool)
                or run_white_c0 <= 0.0
            ):
                # Cannot compare without a numeric reference; let
                # Layer 1's single-run filter speak for this run.
                survived_pairwise.append(i)
                continue
            ratio = max(run_white_c0, fresh_white_c0) / min(
                run_white_c0, fresh_white_c0
            )
            if ratio > _C0_WHITE_PAIRWISE_RATIO_THRESHOLD:
                excluded.append(
                    {
                        "index": i,
                        "reason": "c0_white_pairwise_mismatch",
                        "bias_flags": list(run_scores[i]["bias_flags"]),
                        "structural_flags": list(
                            run_scores[i]["structural_flags"]
                        ),
                        "fresh_white_c0_avg": float(fresh_white_c0),
                        "run_white_c0_avg": float(run_white_c0),
                        "ratio": float(ratio),
                    }
                )
            else:
                survived_pairwise.append(i)
        clean_historical = survived_pairwise

    # --- Layer 2: cross-val on surviving historicals (+ fresh) when N>=threshold ---
    if len(clean_historical) >= cross_val_threshold:
        cross_val_candidates = clean_historical + [fresh_index]
        cv_scores = _cross_val_score_runs(verification_runs, cross_val_candidates)
        for i in cross_val_candidates:
            if i in cv_scores:
                run_scores[i]["cross_val_rmse"] = cv_scores[i]
        if cv_scores:
            selection_strategy = "bias_filter_v1+cross_val"
            historical_with_score = [
                i for i in clean_historical if i in cv_scores
            ]
            if historical_with_score:
                historical_with_score.sort(key=lambda i: cv_scores[i])
                keep_count = max(1, (len(historical_with_score) + 1) // 2)
                kept_after_cv = set(historical_with_score[:keep_count])
                kept_after_cv.update(
                    i for i in clean_historical if i not in cv_scores
                )
                for i in clean_historical:
                    if i not in kept_after_cv:
                        excluded.append(
                            {
                                "index": i,
                                "reason": "cross_val",
                                "bias_flags": list(run_scores[i]["bias_flags"]),
                                "cross_val_rmse": cv_scores.get(i),
                            }
                        )
                clean_historical = sorted(kept_after_cv)

    selected_indices = sorted(set(clean_historical) | {fresh_index})

    # --- Layer 1.7: cross-material session-level white_C0 consistency ---
    # When a session reference is available, every selected run
    # (including ``fresh_index``) is compared against the session's
    # median white_C0. A run whose white_C0 deviates beyond either
    # threshold is excluded — even if it is fresh — because a wrong
    # white substrate sample cannot be salvaged by force-keeping: the
    # resulting (E, k) would absorb the lighting offset and bias every
    # downstream multi-material colour prediction. The earlier layers
    # are intentionally fresh-canonical (the operator's most recent
    # capture is trusted *relative to history*), but here the median of
    # other materials in the same session provides an objective
    # reference, so the fresh-keep contract is correctly weakened.
    # 跨材料 session-level 白底比对放在最后：用同 session 其他材料的
    # 中位数为客观参考，任意 selected run（含 fresh）越界即排除。该层有
    # 意识地不享受 fresh 强留，因为白底参照是物理客观，不存在"最近就一定
    # 对"的语义。
    if session_white_c0_reference is not None:
        survivors_after_session: list[int] = []
        any_session_outlier = False
        for i in selected_indices:
            outlier_diag = _check_run_against_session_c0(
                verification_runs[i],
                session_white_c0_reference,
            )
            if outlier_diag is None:
                survivors_after_session.append(i)
                continue
            # Fold the new structural flag into ``run_scores`` so the
            # UI's per-run badge list stays the single source of truth
            # for "what's wrong with this run". (将新标签合并进 run_scores)
            score = run_scores[i]
            if _BIAS_FLAG_C0_SESSION_OUTLIER not in score["bias_flags"]:
                score["bias_flags"].append(_BIAS_FLAG_C0_SESSION_OUTLIER)
                score["bias_flag_count"] = len(score["bias_flags"])
            if _BIAS_FLAG_C0_SESSION_OUTLIER not in score["structural_flags"]:
                score["structural_flags"].append(_BIAS_FLAG_C0_SESSION_OUTLIER)
                score["structural_flag_count"] = len(score["structural_flags"])
            excluded.append(
                {
                    "index": i,
                    "reason": "c0_session_outlier",
                    "bias_flags": list(score["bias_flags"]),
                    "structural_flags": list(score["structural_flags"]),
                    **outlier_diag,
                }
            )
            any_session_outlier = True
        selected_indices = survivors_after_session
        if any_session_outlier and "session_c0" not in selection_strategy:
            selection_strategy = f"{selection_strategy}+session_c0"

    return {
        "selected_indices": selected_indices,
        "excluded_runs": excluded,
        "selection_strategy": selection_strategy,
        "run_scores": run_scores,
        "fresh_index": fresh_index,
    }


def _aggregate_stage_a_runs(
    *,
    material_name: str,
    params_payload: dict[str, Any],
    fit_summary: dict[str, Any],
    material_summary: dict[str, Any],
    verification_runs: list[dict[str, Any]],
    session_white_c0_reference: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fallback_e_values, fallback_k_values, fallback_white_c0_values, fallback_black_c0_values = _extract_stage_a_vectors(params_payload)

    aggregated_warnings = _collect_run_warnings(verification_runs)

    # Decide which runs participate in the joint refit. Biased runs are
    # excluded so a single white-balanced capture cannot drag the LM fit
    # toward a model that "looks great" against its own biased samples
    # but predicts colour poorly in production. Selection metadata is
    # persisted later so the UI can explain *why* a run was dropped.
    # The optional session reference enables the cross-material white_C0
    # consistency check (Layer 1.7); ``None`` keeps legacy behaviour.
    # 选择哪些 run 参与联合重拟合，把已知偏置的 run 隔离掉；选择详情会写
    # 入 archive，便于前端解释为何某个 run 被排除。可选的 session 参考用于
    # 跨材料白底一致性检查（Layer 1.7），传 None 保持旧行为。
    selection = _select_runs_for_refit(
        verification_runs,
        session_white_c0_reference=session_white_c0_reference,
    )
    selected_runs = [verification_runs[i] for i in selection["selected_indices"]]

    combined = _collect_combined_run_samples(selected_runs)
    if combined is not None:
        # Preferred path: re-fit Beer-Lambert on the combined sample set.
        # Statistically valid; lets verification_count actually improve (E, k).
        # 合并样本重拟合：统计有效，验证次数能真正提升精度。
        thickness_mm, white_linear, black_linear = combined
        (
            agg_e_values,
            agg_k_values,
            agg_white_c0_values,
            agg_black_c0_values,
            channel_rmse,
            overall_validation_refit,
        ) = _refit_combined_samples(thickness_mm, white_linear, black_linear)
        aggregation_method = "refit_combined_samples"
        overall_validation: dict[str, Any] = dict(overall_validation_refit)
        overall_validation["channel_rmse"] = channel_rmse
        per_run_mean_de: list[float] = []
        for run in selected_runs:
            ov = (run.get("fit_summary") or {}).get("overall_validation") or {}
            try:
                per_run_mean_de.append(float(ov["mean_delta_e"]))
            except (KeyError, TypeError, ValueError):
                continue
        if per_run_mean_de:
            overall_validation["best_run_mean_delta_e"] = float(np.min(np.asarray(per_run_mean_de, dtype=np.float64)))
    else:
        # Fallback path: per-run parameter arithmetic mean. Used when any
        # historical run lacks ``samples`` (older archives) or when stored
        # samples failed schema validation. Aggregation is statistically
        # weaker but never worse than a single run, and preserves backwards
        # compatibility for archives saved before the samples field existed.
        # 历史档案缺 samples 或 schema 校验失败时回退到参数均值，保持向后兼容。
        # Mean fallback also operates only on selected_runs so the bias
        # filter applies regardless of which path the aggregator takes.
        # 参数均值兜底同样只对 selected_runs 平均，确保偏置过滤在两个路径上一致生效。
        agg_e_values = _average_numeric_vectors(
            [list((run.get("params") or {}).get("E") or []) for run in selected_runs],
            fallback_e_values,
        )
        agg_k_values = _average_numeric_vectors(
            [list((run.get("params") or {}).get("k") or []) for run in selected_runs],
            fallback_k_values,
        )
        agg_white_c0_values = _average_numeric_vectors(
            [list((run.get("params") or {}).get("white_C0") or []) for run in selected_runs],
            fallback_white_c0_values,
        )
        agg_black_c0_values = _average_numeric_vectors(
            [list((run.get("params") or {}).get("black_C0") or []) for run in selected_runs],
            fallback_black_c0_values,
        )
        aggregation_method = "mean"

        mean_delta_e_values: list[float] = []
        max_delta_e_values: list[float] = []
        rmse_linear_values: list[float] = []
        channel_rmse_values: list[list[float]] = []
        for run in selected_runs:
            run_fit_summary = run.get("fit_summary") or {}
            if not isinstance(run_fit_summary, dict):
                continue
            ov = run_fit_summary.get("overall_validation") or {}
            if not isinstance(ov, dict):
                ov = {}
            try:
                if "mean_delta_e" in ov:
                    mean_delta_e_values.append(float(ov["mean_delta_e"]))
                if "max_delta_e" in ov:
                    max_delta_e_values.append(float(ov["max_delta_e"]))
                if "rmse_linear" in ov:
                    rmse_linear_values.append(float(ov["rmse_linear"]))
            except (TypeError, ValueError):
                pass
            channel_rmse_per_run = ov.get("channel_rmse")
            if isinstance(channel_rmse_per_run, list):
                try:
                    channel_rmse_values.append([float(value) for value in channel_rmse_per_run])
                except (TypeError, ValueError):
                    pass

        overall_validation = material_files._json_clone(fit_summary.get("overall_validation") or {})
        if mean_delta_e_values:
            overall_validation["mean_delta_e"] = float(np.mean(np.asarray(mean_delta_e_values, dtype=np.float64)))
            overall_validation["best_run_mean_delta_e"] = float(np.min(np.asarray(mean_delta_e_values, dtype=np.float64)))
        if max_delta_e_values:
            overall_validation["max_delta_e"] = float(np.max(np.asarray(max_delta_e_values, dtype=np.float64)))
        if rmse_linear_values:
            overall_validation["rmse_linear"] = float(np.mean(np.asarray(rmse_linear_values, dtype=np.float64)))
        if channel_rmse_values:
            overall_validation["channel_rmse"] = [
                float(value)
                for value in np.mean(np.asarray(channel_rmse_values, dtype=np.float64), axis=0).tolist()
            ]

    overall_validation["verification_count"] = len(verification_runs)
    overall_validation["aggregation_method"] = aggregation_method
    overall_validation["selected_run_count"] = len(selected_runs)
    overall_validation["selection_strategy"] = selection["selection_strategy"]

    aggregated_fit_summary = material_files._json_clone(fit_summary)
    aggregated_fit_summary["colors"] = [material_name]
    aggregated_fit_summary["warnings"] = aggregated_warnings
    aggregated_fit_summary["overall_validation"] = overall_validation

    aggregated_material_summary = material_files._json_clone(material_summary)
    aggregated_material_summary["white_zero_rgb"] = material_calibration._linear_to_srgb_uint8(
        np.asarray([agg_white_c0_values], dtype=np.float64)
    )[0].tolist()
    aggregated_material_summary["black_zero_rgb"] = material_calibration._linear_to_srgb_uint8(
        np.asarray([agg_black_c0_values], dtype=np.float64)
    )[0].tolist()
    aggregated_material_summary["estimated_rgb"] = material_calibration._linear_to_srgb_uint8(
        np.asarray([agg_e_values], dtype=np.float64)
    )[0].tolist()
    aggregated_material_summary["estimated_k"] = [round(float(value), 6) for value in agg_k_values]
    aggregated_material_summary["verification_count"] = len(verification_runs)
    aggregated_material_summary["aggregation_method"] = aggregation_method
    aggregated_material_summary["selected_run_count"] = len(selected_runs)
    # Drop the per-run ``fit_samples`` from the aggregated material_summary.
    # The samples are preserved per-run inside ``verification_runs[*].samples``
    # so we don't need to keep a copy on the top-level summary, and removing
    # it keeps the archive footprint stable across multi-run aggregations.
    # 聚合后的 material_summary 不再保留 fit_samples（它们已存在每个 run 内），
    # 减少多次验证后档案体积膨胀。
    aggregated_material_summary.pop("fit_samples", None)

    aggregated_params_payload = material_files._json_clone(params_payload)
    meta = aggregated_params_payload.setdefault("meta", {})
    meta["generated_at"] = material_files._now_iso()
    meta["warnings"] = aggregated_warnings
    meta["verification_count"] = len(verification_runs)
    meta["aggregation_method"] = aggregation_method
    meta["selection"] = material_files._json_clone(selection)
    parameters = aggregated_params_payload.setdefault("parameters", {})
    channels = parameters.get("channels") or []
    if channels and isinstance(channels[0], dict):
        channels[0]["color_name"] = material_name
        channels[0]["E"] = [round(float(value), 6) for value in agg_e_values]
        channels[0]["k"] = [round(float(value), 6) for value in agg_k_values]
    substrates = parameters.get("substrates") or []
    for substrate in substrates:
        if not isinstance(substrate, dict):
            continue
        if substrate.get("substrate_id") == "white":
            substrate["C0"] = [round(float(value), 6) for value in agg_white_c0_values]
        elif substrate.get("substrate_id") == "black":
            substrate["C0"] = [round(float(value), 6) for value in agg_black_c0_values]
    fitted_substrates = aggregated_params_payload.setdefault("fitted_substrates", {})
    fitted_substrates["white"] = {"C0": [round(float(value), 6) for value in agg_white_c0_values]}
    fitted_substrates["black"] = {"C0": [round(float(value), 6) for value in agg_black_c0_values]}
    validation = aggregated_params_payload.setdefault("validation", {})
    validation["overall"] = overall_validation
    return aggregated_params_payload, aggregated_fit_summary, aggregated_material_summary


def _safe_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    try:
        return [float(entry) for entry in value]
    except (TypeError, ValueError):
        return []


def _summarize_verification_runs(
    verification_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    history_items: list[dict[str, Any]] = []
    for index, run in enumerate(verification_runs, start=1):
        run_fit_summary = run.get("fit_summary") or {}
        run_material_summary = run.get("material_summary") or {}
        run_source = run.get("source") or {}
        run_params = run.get("params") or {}
        if not isinstance(run_fit_summary, dict):
            run_fit_summary = {}
        if not isinstance(run_material_summary, dict):
            run_material_summary = {}
        if not isinstance(run_source, dict):
            run_source = {}
        if not isinstance(run_params, dict):
            run_params = {}
        overall_validation = run_fit_summary.get("overall_validation") or {}
        if not isinstance(overall_validation, dict):
            overall_validation = {}

        mean_delta_e: float | None = None
        rmse_linear: float | None = None
        try:
            if "mean_delta_e" in overall_validation:
                mean_delta_e = float(overall_validation["mean_delta_e"])
            if "rmse_linear" in overall_validation:
                rmse_linear = float(overall_validation["rmse_linear"])
        except (TypeError, ValueError):
            mean_delta_e = None if mean_delta_e is None else mean_delta_e
            rmse_linear = None if rmse_linear is None else rmse_linear

        history_items.append(
            {
                "verification_index": index,
                "captured_at": run.get("captured_at"),
                "mean_delta_e": mean_delta_e,
                "rmse_linear": rmse_linear,
                "estimated_rgb": material_files._safe_rgb_triplet(run_material_summary.get("estimated_rgb")),
                "estimated_k": _safe_float_list(run_material_summary.get("estimated_k") or run_params.get("k")),
                "e_values": _safe_float_list(run_params.get("E")),
                "k_values": _safe_float_list(run_params.get("k")),
                "white_c0_values": _safe_float_list(run_params.get("white_C0")),
                "black_c0_values": _safe_float_list(run_params.get("black_C0")),
                "white_detected_orientation": run_source.get("white_detected_orientation"),
                "black_detected_orientation": run_source.get("black_detected_orientation"),
            }
        )
    return history_items
