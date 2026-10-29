"""Predictive LUT runtime helpers.
预测式 LUT 运行时辅助函数。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import json
from typing import Optional

import cv2
import numpy as np
import msgpack

from config import LUTMetadata, get_supported_modes, is_predictive_lut
from core.native_reference import (
    build_channel_key,
    build_recipe_runtime_payload,
    detect_opencv_lab_encoding,
    ensure_reference_repo_importable,
    opencv_lab_to_rgb_uint8,
    rgb_to_opencv_lab_float_space,
)
from core.recipe_order import build_mode_key, convert_recipe_between_orders


@dataclass(frozen=True)
class PredictiveModeRuntime:
    """Runtime-ready predictive candidate package for one mode.
    单个模式的预测式运行时候选包。
    """

    mode_key: str
    layer_height_mm: float
    color_layers: int
    layer_order: str
    candidate_recipes: np.ndarray
    pred_lab: np.ndarray
    threshold: float
    margin: float
    substrate_idx: Optional[int] = None


def _rgb_to_opencv_lab(rgb_array: np.ndarray) -> np.ndarray:
    """Convert RGB uint8 colors to OpenCV Lab working space.
    将 RGB uint8 颜色转换为 OpenCV Lab 工作空间。
    """
    rgb_3d = np.asarray(rgb_array, dtype=np.uint8).reshape(1, -1, 3)
    bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).reshape(-1, 3).astype(np.float32)


def _rgb_to_runtime_opencv_lab(rgb_array: np.ndarray, runtime_lab: np.ndarray) -> np.ndarray:
    """Convert RGB uint8 colors into the OpenCV Lab encoding used by one runtime payload.
    将 RGB uint8 颜色转换为指定运行时载荷所使用的 OpenCV Lab 编码。
    """
    if detect_opencv_lab_encoding(runtime_lab) == "float":
        return rgb_to_opencv_lab_float_space(rgb_array)
    return _rgb_to_opencv_lab(rgb_array)


def _parse_mode_block(
    mode_key: str,
    payload: dict,
    threshold: float,
    margin: float,
) -> PredictiveModeRuntime | None:
    recipes_raw = payload.get("candidate_recipes")
    pred_lab_raw = payload.get("pred_lab")
    if not isinstance(recipes_raw, list) or not isinstance(pred_lab_raw, list):
        return None

    candidate_recipes = np.asarray(recipes_raw, dtype=np.int32)
    pred_lab = np.asarray(pred_lab_raw, dtype=np.float32)
    if candidate_recipes.ndim != 2 or pred_lab.ndim != 2 or pred_lab.shape != (candidate_recipes.shape[0], 3):
        return None

    layer_height_mm = float(payload.get("layer_height_mm", 0.0))
    color_layers = int(payload.get("color_layers", candidate_recipes.shape[1]))
    layer_order = str(payload.get("layer_order", "Top2Bottom"))
    substrate_idx = payload.get("substrate_idx")

    return PredictiveModeRuntime(
        mode_key=mode_key,
        layer_height_mm=layer_height_mm,
        color_layers=color_layers,
        layer_order=layer_order,
        candidate_recipes=candidate_recipes,
        pred_lab=pred_lab,
        threshold=float(payload.get("threshold", threshold)),
        margin=float(payload.get("margin", margin)),
        substrate_idx=(int(substrate_idx) if substrate_idx is not None else None),
    )


def load_predictive_modes(metadata: LUTMetadata | None) -> dict[str, PredictiveModeRuntime]:
    """Load predictive runtime modes from LUT V2 metadata extensions.
    从 LUT V2 元数据扩展块中加载预测式运行时模式。
    """
    if metadata is None or not is_predictive_lut(metadata):
        return {}

    runtime_package = metadata.extensions.get("runtime_package")
    if not isinstance(runtime_package, dict):
        return {}

    defaults = runtime_package.get("defaults", {}) if isinstance(runtime_package.get("defaults"), dict) else {}
    threshold = float(defaults.get("threshold", 5.0))
    margin = float(defaults.get("margin", 0.7))
    modes_raw = runtime_package.get("modes", {})
    if not isinstance(modes_raw, dict):
        return {}

    modes: dict[str, PredictiveModeRuntime] = {}
    for mode_key, payload in modes_raw.items():
        if not isinstance(payload, dict):
            continue
        parsed = _parse_mode_block(str(mode_key), payload, threshold, margin)
        if parsed is not None:
            modes[parsed.mode_key] = parsed
    return modes


@lru_cache(maxsize=16)
def _load_native_package_modes(package_path: str) -> dict[str, PredictiveModeRuntime]:
    payload = msgpack.unpackb(Path(package_path).read_bytes(), raw=False)
    if not isinstance(payload, dict):
        return {}
    defaults = payload.get("defaults", {}) if isinstance(payload.get("defaults"), dict) else {}
    threshold = float(defaults.get("threshold", 5.0))
    margin = float(defaults.get("margin", 0.7))
    modes_raw = payload.get("modes", [])
    modes: dict[str, PredictiveModeRuntime] = {}
    if not isinstance(modes_raw, list):
        return modes
    for item in modes_raw:
        if not isinstance(item, dict):
            continue
        color_layers = int(item.get("color_layers", 0))
        layer_height_mm = float(item.get("layer_height_mm", 0.0))
        mode_key = build_mode_key(layer_height_mm, color_layers)
        num_candidates = int(item.get("num_candidates", 0))
        if num_candidates <= 0 or color_layers <= 0:
            continue
        recipes = np.frombuffer(item.get("candidate_recipes", b""), dtype=np.uint8).reshape(num_candidates, color_layers).astype(np.int32)
        pred_lab = np.frombuffer(item.get("pred_lab", b""), dtype="<f4").reshape(num_candidates, 3).astype(np.float32)
        modes[mode_key] = PredictiveModeRuntime(
            mode_key=mode_key,
            layer_height_mm=layer_height_mm,
            color_layers=color_layers,
            layer_order=str(item.get("layer_order", "Top2Bottom")),
            candidate_recipes=recipes,
            pred_lab=pred_lab,
            threshold=float(item.get("threshold", threshold)),
            margin=float(item.get("margin", margin)),
            substrate_idx=(int(item["substrate_idx"]) if item.get("substrate_idx") is not None else None),
        )
    return modes


@lru_cache(maxsize=16)
def _load_native_recipe_modes(recipe_path: str) -> dict[str, PredictiveModeRuntime]:
    payload = json.loads(Path(recipe_path).read_text(encoding="utf-8"))
    runtime_package = build_recipe_runtime_payload(payload)
    temp_meta = LUTMetadata(extensions={"runtime_package": runtime_package}, capabilities=["predictive_match"])
    return load_predictive_modes(temp_meta)


@lru_cache(maxsize=32)
def _build_stage_runtime_mode(
    stage_model_path: str,
    db_paths_key: tuple[str, ...],
    layer_height_mm: float,
    color_layers: int,
    layer_order: str,
    base_channel_idx: int,
    candidate_count: int = 65536,
) -> PredictiveModeRuntime | None:
    ensure_reference_repo_importable()
    from modeling.core.forward_model import (  # type: ignore
        load_stage_forward_model,
        predict_linear_batch as predict_with_stage_model,
        resolve_substrate_idx,
    )
    from modeling.core.color_space import linear_rgb_to_opencv_lab_batch  # type: ignore
    from modeling.pipeline.step5_build_model_package import (  # type: ignore
        collect_seed_recipes,
        sample_candidate_recipes,
    )

    stage_model = load_stage_forward_model(Path(stage_model_path))
    channel_keys = [build_channel_key(name, "PLA Basic") for name in stage_model.channel_names]
    stage_key_to_idx = {key: idx for idx, key in enumerate(channel_keys)}
    db_paths = [Path(path) for path in db_paths_key]
    substrate_idx = resolve_substrate_idx(stage_model, db_paths, base_channel_idx)
    seed_recipes = collect_seed_recipes(
        db_paths,
        stage_key_to_idx,
        float(layer_height_mm),
        int(color_layers),
        str(layer_order),
        int(base_channel_idx),
    )
    recipes = sample_candidate_recipes(
        seed_recipes,
        stage_model.E.shape[0],
        int(color_layers),
        int(candidate_count),
        42 + int(color_layers),
    )
    linear_rgb = predict_with_stage_model(
        recipes,
        stage_model,
        float(layer_height_mm),
        float(stage_model.micro_layer_height_mm),
        int(base_channel_idx),
        str(layer_order),
        int(substrate_idx),
    )
    pred_lab = linear_rgb_to_opencv_lab_batch(linear_rgb).astype(np.float32)
    return PredictiveModeRuntime(
        mode_key=build_mode_key(layer_height_mm, color_layers),
        layer_height_mm=float(layer_height_mm),
        color_layers=int(color_layers),
        layer_order=str(layer_order),
        candidate_recipes=recipes.astype(np.int32),
        pred_lab=pred_lab,
        threshold=5.0,
        margin=0.7,
        substrate_idx=int(substrate_idx),
    )


def select_predictive_mode(
    modes: dict[str, PredictiveModeRuntime],
    layer_height_mm: float,
    color_layers: int,
    layer_order: str,
) -> PredictiveModeRuntime | None:
    """Select best predictive runtime mode for the current print settings.
    为当前打印设置选择最合适的预测运行时模式。
    """
    if not modes:
        return None

    mode_key = build_mode_key(layer_height_mm, color_layers)
    selected = modes.get(mode_key)
    if selected is None:
        for candidate in modes.values():
            if (
                abs(float(candidate.layer_height_mm) - float(layer_height_mm)) <= 1e-3
                and int(candidate.color_layers) == int(color_layers)
            ):
                selected = candidate
                break
    if selected is None:
        return None
    if selected.layer_order == layer_order:
        return selected

    converted = np.asarray(
        [
            convert_recipe_between_orders(recipe, selected.layer_order, layer_order)
            for recipe in selected.candidate_recipes
        ],
        dtype=np.int32,
    )
    return PredictiveModeRuntime(
        mode_key=selected.mode_key,
        layer_height_mm=selected.layer_height_mm,
        color_layers=selected.color_layers,
        layer_order=layer_order,
        candidate_recipes=converted,
        pred_lab=selected.pred_lab,
        threshold=selected.threshold,
        margin=selected.margin,
        substrate_idx=selected.substrate_idx,
    )


def resolve_predictive_runtime(
    metadata: LUTMetadata | None,
    layer_height_mm: float,
    color_layers: int,
    layer_order: str,
) -> PredictiveModeRuntime | None:
    """Resolve predictive runtime for Lumina LUT V2 or native reference sources."""
    if metadata is None:
        return None

    modes = load_predictive_modes(metadata)
    if not modes:
        package_path = metadata.extensions.get("native_model_package_path")
        if isinstance(package_path, str) and package_path:
            modes = _load_native_package_modes(package_path)

    if not modes:
        recipe_path = metadata.extensions.get("native_recipe_path")
        if isinstance(recipe_path, str) and recipe_path:
            modes = _load_native_recipe_modes(recipe_path)

    selected = select_predictive_mode(modes, layer_height_mm, color_layers, layer_order)
    if selected is not None:
        return selected

    stage_model_path = metadata.extensions.get("native_stage_model_path")
    db_paths = metadata.extensions.get("native_db_paths") or []
    if isinstance(stage_model_path, str) and stage_model_path and isinstance(db_paths, list) and db_paths:
        try:
            return _build_stage_runtime_mode(
                stage_model_path,
                tuple(str(path) for path in db_paths),
                float(layer_height_mm),
                int(color_layers),
                str(layer_order),
                int(metadata.base_channel_idx),
            )
        except Exception:
            return None

    return None


def list_predictive_supported_modes(metadata: LUTMetadata | None) -> list[dict]:
    """Return predictive supported modes from metadata or native source context."""
    if metadata is None:
        return []

    explicit = get_supported_modes(metadata)
    if explicit:
        return explicit

    embedded_modes = load_predictive_modes(metadata)
    if embedded_modes:
        return [
            {
                "mode_key": mode.mode_key,
                "color_layers": mode.color_layers,
                "layer_height_mm": mode.layer_height_mm,
                "layer_order": mode.layer_order,
            }
            for mode in embedded_modes.values()
        ]

    package_path = metadata.extensions.get("native_model_package_path")
    if isinstance(package_path, str) and package_path:
        return [
            {
                "mode_key": mode.mode_key,
                "color_layers": mode.color_layers,
                "layer_height_mm": mode.layer_height_mm,
                "layer_order": mode.layer_order,
            }
            for mode in _load_native_package_modes(package_path).values()
        ]

    recipe_path = metadata.extensions.get("native_recipe_path")
    if isinstance(recipe_path, str) and recipe_path:
        return [
            {
                "mode_key": mode.mode_key,
                "color_layers": mode.color_layers,
                "layer_height_mm": mode.layer_height_mm,
                "layer_order": mode.layer_order,
            }
            for mode in _load_native_recipe_modes(recipe_path).values()
        ]

    return []


def predict_recipe_color(
    metadata: LUTMetadata,
    recipe: list[int],
    layer_height_mm: float,
    color_layers: int,
    layer_order: str,
) -> dict[str, object]:
    """Predict a custom recipe color using native stage model or selected runtime."""
    runtime = resolve_predictive_runtime(metadata, layer_height_mm, color_layers, layer_order)
    if runtime is not None:
        recipe_arr = np.asarray(recipe, dtype=np.int32).reshape(1, -1)
        converted = recipe_arr
        if runtime.layer_order != layer_order:
            converted = np.asarray(
                [convert_recipe_between_orders(recipe_arr[0], layer_order, runtime.layer_order)],
                dtype=np.int32,
            )
        match_runtime = PredictiveModeRuntime(
            mode_key=runtime.mode_key,
            layer_height_mm=runtime.layer_height_mm,
            color_layers=runtime.color_layers,
            layer_order=runtime.layer_order,
            candidate_recipes=converted,
            pred_lab=runtime.pred_lab[:1] if runtime.pred_lab.shape[0] else np.zeros((1, 3), dtype=np.float32),
            threshold=runtime.threshold,
            margin=runtime.margin,
            substrate_idx=runtime.substrate_idx,
        )
        # If a stage model exists, prefer exact forward prediction below.

    stage_model_path = metadata.extensions.get("native_stage_model_path")
    db_paths = metadata.extensions.get("native_db_paths") or []
    if isinstance(stage_model_path, str) and stage_model_path:
        try:
            ensure_reference_repo_importable()
            from modeling.core.forward_model import (  # type: ignore
                load_stage_forward_model,
                predict_linear_batch as predict_with_stage_model,
                resolve_substrate_idx,
            )
            from modeling.core.color_space import linear_rgb_to_opencv_lab_batch  # type: ignore

            stage_model = load_stage_forward_model(Path(stage_model_path))
            substrate_idx = resolve_substrate_idx(stage_model, [Path(path) for path in db_paths], int(metadata.base_channel_idx))
            linear_rgb = predict_with_stage_model(
                np.asarray(recipe, dtype=np.int32).reshape(1, -1),
                stage_model,
                float(layer_height_mm),
                float(stage_model.micro_layer_height_mm),
                int(metadata.base_channel_idx),
                str(layer_order),
                int(substrate_idx),
            )
            pred_lab = linear_rgb_to_opencv_lab_batch(linear_rgb).astype(np.float32)
            pred_rgb = opencv_lab_to_rgb_uint8(pred_lab)
            return {
                "rgb": pred_rgb[0].astype(int).tolist(),
                "lab": pred_lab[0].astype(float).tolist(),
                "source": "stage_model",
                "runtime_mode_key": build_mode_key(layer_height_mm, color_layers),
            }
        except Exception:
            pass

    runtime = resolve_predictive_runtime(metadata, layer_height_mm, color_layers, layer_order)
    if runtime is None:
        raise ValueError("No predictive runtime available for this source")
    converted = np.asarray(recipe, dtype=np.int32).reshape(1, -1)
    if runtime.layer_order != layer_order:
        converted = np.asarray(
            [convert_recipe_between_orders(converted[0], layer_order, runtime.layer_order)],
            dtype=np.int32,
        )
    # runtime-package-only sources can only predict exact candidates
    diff = runtime.candidate_recipes - converted[0]
    same_mask = np.all(diff == 0, axis=1)
    if not np.any(same_mask):
        raise ValueError("Recipe is not present in the runtime package; exact prediction unavailable for package-only source")
    idx = int(np.argmax(same_mask))
    pred_lab = runtime.pred_lab[idx : idx + 1]
    pred_rgb = opencv_lab_to_rgb_uint8(pred_lab)
    return {
        "rgb": pred_rgb[0].astype(int).tolist(),
        "lab": pred_lab[0].astype(float).tolist(),
        "source": "runtime_package",
        "runtime_mode_key": runtime.mode_key,
    }


def match_unique_colors_with_runtime(
    unique_colors: np.ndarray,
    runtime: PredictiveModeRuntime,
) -> dict[str, object]:
    """Match unique colors to predictive runtime candidates.
    将唯一颜色匹配到预测式运行时候选集。
    """
    unique_lab = _rgb_to_runtime_opencv_lab(unique_colors, runtime.pred_lab)
    pred_lab = runtime.pred_lab.astype(np.float32, copy=False)
    # Photo palettes can contain tens of thousands of colors. Bound both axes
    # instead of allocating targets × all recipes × Lab (41 GiB in one report).
    # Keep float32 arithmetic and first-candidate tie order identical to the
    # full search; no quantization or approximate nearest-neighbor matching.
    candidate_count = pred_lab.shape[0]
    if candidate_count == 0:
        raise ValueError("Predictive runtime has no candidate recipes")
    candidate_chunk = min(candidate_count, 8192)
    # Each pair needs three float32 differences and one squared distance.
    target_chunk = max(1, (32 * 1024 * 1024) // (candidate_chunk * 16))
    nearest = np.zeros(len(unique_lab), dtype=np.intp)
    best_dist2 = np.full(len(unique_lab), np.inf, dtype=np.float32)
    for start in range(0, len(unique_lab), target_chunk):
        stop = min(start + target_chunk, len(unique_lab))
        block_best = best_dist2[start:stop]
        block_nearest = nearest[start:stop]
        rows = np.arange(stop - start)
        for offset in range(0, candidate_count, candidate_chunk):
            diff = unique_lab[start:stop, None, :] - pred_lab[None, offset:offset + candidate_chunk, :]
            np.square(diff, out=diff)
            dist2 = np.sum(diff, axis=2)
            local_nearest = np.argmin(dist2, axis=1)
            local_dist2 = dist2[rows, local_nearest]
            improved = local_dist2 < block_best
            block_best[improved] = local_dist2[improved]
            block_nearest[improved] = offset + local_nearest[improved]
            del diff, dist2
    distances = np.sqrt(best_dist2)
    matched_lab = pred_lab[nearest]
    matched_rgb = opencv_lab_to_rgb_uint8(matched_lab)
    recipes = runtime.candidate_recipes[nearest].astype(np.int32, copy=False)

    return {
        "match_mode": "predictive",
        "runtime_mode_key": runtime.mode_key,
        "matched_rgb": matched_rgb,
        "recipes": recipes,
        "distances": distances,
        "threshold": float(runtime.threshold),
        "margin": float(runtime.margin),
        "within_threshold": distances <= float(runtime.threshold),
    }
