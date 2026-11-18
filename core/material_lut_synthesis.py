"""Material LUT synthesis — material loading, pipeline helpers, and re-exports.
耗材 LUT 合成 — 耗材加载、管线辅助函数及算法再导出。

This module provides:
- Disk I/O for loading saved material archives (``load_material_params``,
  ``load_multiple_materials``)
- Pipeline integration helpers (``build_material_slot_names``,
  ``build_material_preview_colors``)

The pure color-solving algorithm lives in ``core.material_color_solver``.
All solver symbols are re-exported here for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path, PureWindowsPath
from typing import Any

import numpy as np

from config import MATERIALS_DIR

# Re-export solver symbols so existing imports keep working
from core.material_color_solver import (  # noqa: F401
    ALLOWED_LAYER_HEIGHTS_MM,
    DEFAULT_BEAM_WIDTH,
    DEFAULT_LAYER_COUNT,
    DEFAULT_LAYER_HEIGHT_MM,
    MAX_LAYER_COUNT,
    MIN_LAYER_COUNT,
    MaterialParams,
    beer_lambert_layer as _beer_lambert_layer,
    ensure_not_worse_than_smaller_N,
    forward_model,
    linear_to_srgb_uint8 as _linear_to_srgb_uint8,
    map_pixels_to_materials,
    srgb_to_linear as _srgb_to_linear,
    solve_image_colors,
    solve_image_colors_optimal,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Material loading
# ---------------------------------------------------------------------------


def _material_solver_value_error(material_label: str, reason: str) -> ValueError:
    label = str(material_label or "selected material").strip() or "selected material"
    return ValueError(
        f"Material '{label}' cannot be used by the material solver: {reason}. "
        "Re-fit Stage A or import a complete Lumina material export."
    )


_STAGE_A_PARAMS_FILE_REASON = (
    "stage_a_params_file must reference an existing file inside the material directory"
)


def _stage_a_params_file_error(material_label: str) -> ValueError:
    return _material_solver_value_error(material_label, _STAGE_A_PARAMS_FILE_REASON)


def _resolve_stage_a_params_path(
    material_dir: Path,
    archive: dict[str, Any],
    *,
    material_label: str,
) -> Path:
    raw_value = archive.get("stage_a_params_file")
    if raw_value is None:
        raw_filename = "stage_A_parameters.json"
    elif isinstance(raw_value, str):
        raw_filename = raw_value.strip()
    else:
        raise _stage_a_params_file_error(material_label)

    normalized = raw_filename.replace("\\", "/")
    windows_path = PureWindowsPath(raw_filename)
    if (
        not normalized
        or normalized.startswith("/")
        or windows_path.drive
        or windows_path.is_absolute()
        or Path(raw_filename).is_absolute()
    ):
        raise _stage_a_params_file_error(material_label)

    path_parts = tuple(part for part in normalized.split("/") if part)
    if not path_parts or any(part in {".", ".."} for part in path_parts):
        raise _stage_a_params_file_error(material_label)

    try:
        material_root = material_dir.resolve(strict=True)
        resolved_path = material_dir.joinpath(*path_parts).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _stage_a_params_file_error(material_label) from exc

    try:
        resolved_path.relative_to(material_root)
    except ValueError as exc:
        raise _stage_a_params_file_error(material_label) from exc

    if not resolved_path.is_file():
        raise _stage_a_params_file_error(material_label)
    return resolved_path


def _solver_vector(
    raw_value: Any,
    *,
    material_label: str,
    field_path: str,
    bounded_unit: bool = False,
    positive: bool = False,
) -> np.ndarray:
    if not isinstance(raw_value, (list, tuple)):
        raise _material_solver_value_error(
            material_label,
            f"{field_path} must contain exactly 3 finite numbers",
        )
    try:
        vector = np.asarray(raw_value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise _material_solver_value_error(
            material_label,
            f"{field_path} must contain exactly 3 finite numbers",
        ) from exc
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise _material_solver_value_error(
            material_label,
            f"{field_path} must contain exactly 3 finite numbers",
        )
    if bounded_unit and not np.all((0.0 <= vector) & (vector <= 1.0)):
        raise _material_solver_value_error(
            material_label,
            f"{field_path} must contain numbers in [0, 1]",
        )
    if positive and not np.all(vector > 0.0):
        raise _material_solver_value_error(
            material_label,
            f"{field_path} must contain positive numbers",
        )
    return vector


def validate_stage_a_solver_parameters(
    stage_a: Any,
    *,
    material_label: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate and extract the Stage A vectors required by the material solver.
    校验并提取材料求解器所需的 Stage A 向量。

    Args:
        stage_a: Parsed Stage A JSON payload. (已解析的 Stage A JSON 数据)
        material_label: Logical material label for user-facing errors.
            (用于错误提示的逻辑耗材标识)

    Returns:
        ``E``, ``k``, and white-substrate ``C0`` vectors. (E、k 和白底 C0 向量)
    """
    if not isinstance(stage_a, dict):
        raise _material_solver_value_error(
            material_label,
            "Stage A parameters must be a JSON object",
        )
    parameters = stage_a.get("parameters")
    if not isinstance(parameters, dict):
        raise _material_solver_value_error(
            material_label,
            "parameters must be a JSON object",
        )
    channels = parameters.get("channels")
    if not isinstance(channels, list) or not channels:
        raise _material_solver_value_error(
            material_label,
            "parameters.channels[0] must be an object with E and k vectors",
        )
    channel0 = channels[0]
    if not isinstance(channel0, dict):
        raise _material_solver_value_error(
            material_label,
            "parameters.channels[0] must be an object with E and k vectors",
        )

    E = _solver_vector(
        channel0.get("E"),
        material_label=material_label,
        field_path="parameters.channels[0].E",
        bounded_unit=True,
    )
    k = _solver_vector(
        channel0.get("k"),
        material_label=material_label,
        field_path="parameters.channels[0].k",
        positive=True,
    )

    c0_raw: Any = None
    substrates = parameters.get("substrates")
    if isinstance(substrates, list):
        for substrate in substrates:
            if (
                isinstance(substrate, dict)
                and substrate.get("substrate_id") == "white"
            ):
                c0_raw = substrate.get("C0")
                break
    if c0_raw is None:
        fitted_substrates = stage_a.get("fitted_substrates")
        if isinstance(fitted_substrates, dict):
            white_fitted = fitted_substrates.get("white")
            if isinstance(white_fitted, dict):
                c0_raw = white_fitted.get("C0")
    if c0_raw is None:
        raise _material_solver_value_error(
            material_label,
            "Stage A parameters must include white substrate C0 as "
            "parameters.substrates[substrate_id='white'].C0 or "
            "fitted_substrates.white.C0",
        )
    C0_white = _solver_vector(
        c0_raw,
        material_label=material_label,
        field_path="white substrate C0",
        bounded_unit=True,
    )
    return E, k, C0_white


def load_material_params(
    directory_name: str,
    *,
    materials_dir: str | None = None,
) -> MaterialParams:
    """Load a saved material archive and extract Beer-Lambert parameters.
    加载保存的耗材档案并提取 Beer-Lambert 参数。

    Args:
        directory_name: Name of the material directory under ``materials/``.
            (materials/ 下的耗材目录名)
        materials_dir: Override materials root path. (可选的材料根目录覆盖)

    Returns:
        MaterialParams with E, k, C0_white vectors loaded.
    """
    from core.single_stage import material_files

    root = Path(materials_dir or MATERIALS_DIR)
    try:
        material_dir = material_files.resolve_saved_material_dir(root, directory_name)
    except FileNotFoundError:
        raise FileNotFoundError(f"Material directory not found: {directory_name}")

    if not materials_dir:
        relative_path = material_dir.relative_to(root.resolve())
        supplied_root = directory_name.strip().replace("\\", "/").split("/", 1)[0]
        if (
            supplied_root.casefold() in material_files.INTERNAL_MATERIAL_ROOT_NAMES
            or (relative_path.parts and relative_path.parts[0].casefold() in material_files.INTERNAL_MATERIAL_ROOT_NAMES)
        ):
            raise ValueError(
                f"Material '{directory_name}' belongs to an internal library directory. "
                "Choose a material from your library."
            )

    archive_path = material_dir / "material.json"
    if not archive_path.exists():
        raise FileNotFoundError(f"material.json not found in {directory_name}")

    archive = material_files._load_json_object(
        archive_path,
        f"Material '{directory_name}' has an unreadable material.json. Import a complete material archive.",
    )
    material_name = str(archive.get("material_name") or directory_name)

    # Load stage_A_parameters.json for E and k
    stage_a_path = _resolve_stage_a_params_path(
        material_dir,
        archive,
        material_label=directory_name,
    )
    try:
        stage_a = json.loads(stage_a_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _stage_a_params_file_error(directory_name) from exc
    E, k, C0_white = validate_stage_a_solver_parameters(
        stage_a,
        material_label=directory_name,
    )

    # Estimated sRGB for preview
    material_summary = archive.get("material_summary") or {}
    estimated_rgb_raw = material_summary.get("estimated_rgb")
    if isinstance(estimated_rgb_raw, list) and len(estimated_rgb_raw) >= 3:
        estimated_rgb = np.asarray(estimated_rgb_raw[:3], dtype=np.uint8)
    else:
        estimated_rgb = _linear_to_srgb_uint8(E.reshape(1, 3))[0]

    return MaterialParams(
        name=material_name,
        directory_name=directory_name,
        E=E,
        k=k,
        C0_white=C0_white,
        estimated_rgb=estimated_rgb,
        material_type=(
            archive["material_type"].strip() or None
            if isinstance(archive.get("material_type"), str)
            else None
        ),
    )


def load_multiple_materials(
    directory_names: list[str],
    *,
    materials_dir: str | None = None,
) -> list[MaterialParams]:
    """Load multiple material archives by directory name.
    批量加载耗材档案。

    Args:
        directory_names: List of material directory names. (耗材目录名列表)
        materials_dir: Override materials root path. (可选的材料根目录覆盖)

    Returns:
        List of MaterialParams in the same order. (按顺序的耗材参数列表)
    """
    if not directory_names:
        raise ValueError("At least one material must be selected")
    materials = []
    for dir_name in directory_names:
        materials.append(load_material_params(dir_name, materials_dir=materials_dir))
    return materials


# ---------------------------------------------------------------------------
# Preview-color / slot-name helpers for pipeline integration
# ---------------------------------------------------------------------------


def build_material_slot_names(materials: list[MaterialParams]) -> list[str]:
    """Build slot_names list from material params — used as mesh/object names in 3MF.
    从耗材参数构建槽位名列表 — 作为 3MF 中的网格/对象名。

    Args:
        materials: List of selected materials. (已选耗材列表)

    Returns:
        List of material names. (耗材名列表)
    """
    return [m.name for m in materials]


def build_material_preview_colors(
    materials: list[MaterialParams],
) -> dict[int, list[int]]:
    """Build preview_colors mapping from material params.
    从耗材参数构建预览颜色映射。

    Args:
        materials: List of selected materials. (已选耗材列表)

    Returns:
        Dict mapping material_id (int) to [R, G, B, A] list. (材料ID到RGBA映射)
    """
    preview: dict[int, list[int]] = {}
    for idx, mat in enumerate(materials):
        rgb = mat.estimated_rgb.tolist()
        preview[idx] = [int(rgb[0]), int(rgb[1]), int(rgb[2]), 255]
    return preview


def _looks_like_white_material_label(label: object) -> bool:
    text = str(label or "").strip().lower()
    if not text:
        return False
    if "白" in text:
        return True
    tokens = (
        text.replace("\\", "/")
        .replace("/", " ")
        .replace("-", " ")
        .replace("_", " ")
        .split()
    )
    return "white" in tokens or "w" in tokens


def _preview_color_rgb(preview_colors: object, idx: int) -> np.ndarray | None:
    if not isinstance(preview_colors, dict):
        return None
    raw = preview_colors.get(idx)
    if raw is None:
        raw = preview_colors.get(str(idx))
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        rgb = np.asarray([int(raw[0]), int(raw[1]), int(raw[2])], dtype=np.int32)
    except (TypeError, ValueError):
        return None
    if not bool(np.all((0 <= rgb) & (rgb <= 255))):
        return None
    return rgb


def infer_material_archive_base_channel_idx(
    selected_materials: list,
    slot_names: list,
    preview_colors: object,
) -> int:
    """Infer the white/base channel index for a material-archive palette.
    推断耗材档案 palette 中的白色/底色通道索引。

    Args:
        selected_materials: Material directory names in user-selected order.
            (用户选择顺序下的耗材目录名)
        slot_names: Display slot names aligned with ``selected_materials``.
            (与耗材顺序对齐的显示槽位名)
        preview_colors: Optional preview color map keyed by material index.
            (按材料索引存储的预览颜色映射)

    Returns:
        Best-effort base channel index, falling back to ``0`` when no white
        candidate is identifiable. (推断出的底色通道索引；无法识别时回退 0)
    """
    for idx, dir_name in enumerate(selected_materials):
        raw_slot = slot_names[idx] if idx < len(slot_names) else None
        if (
            _looks_like_white_material_label(raw_slot)
            or _looks_like_white_material_label(dir_name)
        ):
            return idx
    target = np.asarray((245, 245, 245), dtype=np.int32)
    best_idx = 0
    best_dist: int | None = None
    for idx in range(len(selected_materials)):
        rgb = _preview_color_rgb(preview_colors, idx)
        if rgb is None:
            continue
        dist = int(np.sum((rgb - target) ** 2))
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_idx = idx
    return best_idx if best_dist is not None and best_dist <= 6400 else 0
