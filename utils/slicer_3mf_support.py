"""Shared device and layout facts for single, batch and puzzle 3MF exports.

单件、批量与拼图 3MF 导出共用的设备和布局事实。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Mapping

from api.structured_logging import get_logger
from core.wipe_tower_placement import (
    Rect, WIPE_TOWER_MANUAL_WARNING_CODE,
    WipeTowerPlacementRequest, WipeTowerPlacementResult,
)

if TYPE_CHECKING:
    from core.machine_registry import BuildPlateProfile, DeviceProfile

# Preserve the established logger for the existing placement event contract.
log = get_logger("utils.bambu_3mf_writer")

DEFAULT_EXPORT_SETTINGS = {
    "layer_height": "0.08",
    "initial_layer_height": "0.08",
    "wall_loops": "1",
    "top_shell_layers": "0",
    "bottom_shell_layers": "1",
    "bottom_surface_pattern": "monotonicline",
    "elefant_foot_compensation": "0",
    "sparse_infill_density": "100%",
    "sparse_infill_pattern": "zig-zag",
    "travel_speed": "150",
    "enable_support": "0",
    "brim_width": "5",
    "brim_type": "auto_brim",
}


_CREATOR_5_PRINTER_IDS = frozenset(
    {"flashforge-creator-5", "flashforge-creator-5-pro"}
)
_CREATOR_5_TOWER_MIN_FOOTPRINT_WIDTH_MM = 58.5
_CREATOR_5_TOWER_MIN_DEPTH_MM = 61.0
_CREATOR_5_MODEL_TOWER_CLEARANCE_MM = 7.5
_ANYCUBIC_TOWER_MIN_FOOTPRINT_WIDTH_MM = 50.0
_ANYCUBIC_TOWER_MIN_DEPTH_MM = 57.5
_ELEGOO_CC2_PREFERRED_TOP_EDGE_CLEARANCE_MM = 32.0


def _resolve_machine_registry_root() -> str:
    """Return the shared absolute machine-registry resource root.

    返回共享的机器注册表绝对资源根目录。
    """

    from core.machine_registry import resolve_machine_registry_root

    return str(resolve_machine_registry_root())


def _validate_registry_device_profile(
    *,
    device_profile_id: str,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    registry_path: str,
) -> DeviceProfile:
    """Load and validate a generated registry device profile.

    加载并校验生成的机器注册表设备配置，避免选择的切片器/喷嘴与实际
    3MF 模板混用。
    """
    from core.machine_registry import (
        MachineRegistrySelectionError,
        load_machine_registry,
        validate_device_profile_selection,
    )

    registry = load_machine_registry(registry_path)
    try:
        profile, _ = validate_device_profile_selection(
            registry,
            device_profile_id=device_profile_id,
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=nozzle_size,
        )
    except MachineRegistrySelectionError as exc:
        raise ValueError(str(exc)) from exc
    return profile


def _load_registry_device_profile_if_available(
    *,
    device_profile_id: str,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
) -> DeviceProfile | None:
    """Return a validated registry device profile when registry data exists.

    存在机器注册表时返回已校验的设备配置；未显式配置环境变量且默认
    ``machine_registry`` 不存在时返回 ``None``，保持旧模板回退兼容。
    """
    registry_root = _resolve_machine_registry_root()
    registry_path = os.path.join(registry_root, "registry.json")
    if not os.path.exists(registry_path):
        if os.environ.get("LUMINA_MACHINE_REGISTRY_DIR"):
            raise ValueError(f"Machine registry not found: {registry_path}")
        return None
    return _validate_registry_device_profile(
        device_profile_id=device_profile_id,
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        registry_path=registry_path,
    )


def resolve_export_device(
    *,
    printer_id: str,
    slicer: str,
    nozzle_size: object,
    device_profile_id: str | None,
    build_plate_id: str | None,
) -> tuple[str, DeviceProfile | None, BuildPlateProfile | None]:
    """Resolve the nozzle and validate selected registry hardware.

    解析喷嘴尺寸，并校验所选注册表硬件。

    Args:
        printer_id: Product printer identity. 产品打印机身份。
        slicer: Selected slicer identity. 所选切片软件身份。
        nozzle_size: Requested nozzle size. 请求的喷嘴尺寸。
        device_profile_id: Optional registry device. 可选注册表设备。
        build_plate_id: Optional native plate. 可选原生打印板。

    Returns:
        Nozzle, device and plate selected for this export.
        本次导出的喷嘴、设备和打印板。
    """
    from config import (
        format_native_nozzle_size,
        get_printer_profile,
        normalize_nozzle_size,
    )

    legacy_nozzle_size = normalize_nozzle_size(nozzle_size) or "0.4"
    native_nozzle_size = format_native_nozzle_size(nozzle_size) or legacy_nozzle_size
    configured_nozzle_sizes = get_printer_profile(printer_id).supported_nozzle_sizes
    resolved_nozzle_size = (
        native_nozzle_size
        if device_profile_id or native_nozzle_size in configured_nozzle_sizes
        else legacy_nozzle_size
    )
    device_profile = (
        _load_registry_device_profile_if_available(
            device_profile_id=device_profile_id,
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=resolved_nozzle_size,
        )
        if device_profile_id
        else None
    )
    build_plate = None
    if build_plate_id:
        if device_profile is None or not device_profile_id:
            raise ValueError("Build plate selection requires a machine registry device profile")
        from core.machine_registry import load_machine_registry

        registry_path = os.path.join(
            _resolve_machine_registry_root(),
            "registry.json",
        )
        try:
            build_plate = load_machine_registry(
                registry_path
            ).resolve_build_plate(device_profile_id, build_plate_id)
        except KeyError as exc:
            raise ValueError(str(exc).strip("'")) from exc
    return resolved_nozzle_size, device_profile, build_plate


def build_wipe_tower_placement_request(
    layout: Mapping[str, Any],
    *,
    model_bounds: Rect,
    model_height: float,
    material_count: int,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    process_layout: Mapping[str, Any] | None = None,
) -> WipeTowerPlacementRequest | None:
    """Build placement input from decoded layout and geometry facts.

    从已解析布局及几何事实构造摆放请求。

    Args:
        layout: FatCat decoded hardware and tower facts. FatCat 解析的硬件和塔事实。
        model_bounds: Model footprint. 模型平面边界。
        model_height: Model height in mm. 模型高度，毫米。
        material_count: Number of selected materials. 所选材料数量。
        printer_id: Product printer identity. 产品打印机身份。
        slicer: Selected slicer identity. 所选切片软件身份。
        nozzle_size: Selected nozzle size. 所选喷嘴尺寸。
        process_layout: Optional effective process facts. 可选实际工艺事实。

    Returns:
        Placement request, or None without a usable printable area.
        摆放请求；没有可用打印区域时返回 None。
    """

    process = layout if process_layout is None else process_layout
    printable_area = tuple(tuple(point) for point in layout["printable_area"])
    if len(printable_area) < 3:
        return None

    uses_creator_5_tower_interface = (
        slicer == "FlashStudio"
        and printer_id in _CREATOR_5_PRINTER_IDS
    )
    uses_anycubic_tower_interface = slicer == "AnycubicSlicerNext"
    uses_native_tower_envelope = (
        uses_creator_5_tower_interface or uses_anycubic_tower_interface
    )
    uses_rib_wall = layout["uses_rib_wall"]
    tower_brim = (
        min(8.0, max(0.0, model_height) / 100.0 * 8.0)
        if layout["tower_brim_auto"] else layout["tower_brim_width"]
    )
    layer_height = process["layer_height"]
    first_layer = process.get("initial_layer_height")
    if slicer == "BambuStudio" and first_layer and first_layer > 0:
        # The tower footprint must also hold the purge on its first layer.
        layer_height = min(layer_height, first_layer)
    return WipeTowerPlacementRequest(
        printable_area=printable_area,
        bed_exclusions=tuple(
            tuple(tuple(point) for point in polygon)
            for polygon in layout["bed_exclusions"]
        ),
        extruder_printable_areas=tuple(
            tuple(tuple(point) for point in polygon)
            for polygon in layout["extruder_printable_areas"]
        ),
        model_bounds=model_bounds,
        model_height=max(0.0, float(model_height)),
        model_brim=process["model_brim"],
        material_count=max(1, int(material_count)),
        layer_height=layer_height,
        nozzle_diameter=max(0.1, float(nozzle_size)),
        purge_volume=layout["purge_volume"],
        tower_x=layout["tower_x"],
        tower_y=layout["tower_y"],
        tower_width=layout["tower_width"],
        tower_rotation=layout["tower_rotation"],
        tower_brim=0.0 if uses_native_tower_envelope else tower_brim,
        tower_infill_spacing_ratio=layout["tower_infill_spacing_ratio"],
        cyclic_toolchanges=bool(layout.get("tower_cyclic_toolchanges", False)),
        tower_wall_types=tuple(layout.get("tower_wall_types", ())),
        tower_rib_width=(
            layout["tower_rib_width"]
            if uses_rib_wall and not uses_native_tower_envelope else 0.0
        ),
        tower_extra_rib_length=layout["tower_extra_rib_length"],
        tower_square_rib_body=(
            uses_rib_wall and (
                layout.get("tower_square_rib_body")
                if layout.get("tower_square_rib_body") is not None
                else printer_id.startswith("bambu-")
                and slicer in {"BambuStudio", "OrcaSlicer"}
            )
        ),
        tower_preview_x_guard_enabled=bool(
            layout.get("tower_preview_x_guard_enabled", False)
        ),
        tower_preview_x_guard_margin=max(
            0.0, float(layout.get("tower_preview_x_guard_margin") or 0.0)
        ),
        extruder_count=layout["extruder_count"],
        nozzle_change_volume=layout.get("nozzle_change_volume", 0.0),
        separate_material_bands=slicer == "BambuStudio",
        filament_change_volume=layout["filament_change_volume"],
        model_tower_clearance=(
            _CREATOR_5_MODEL_TOWER_CLEARANCE_MM
            if uses_creator_5_tower_interface else 8.0
        ),
        edge_clearance=0.0 if uses_native_tower_envelope else 2.0,
        preferred_edge_clearance=4.0,
        preferred_top_edge_clearance=(
            _ELEGOO_CC2_PREFERRED_TOP_EDGE_CLEARANCE_MM
            if printer_id == "elegoo-cc2" else 0.0
        ),
        prefer_vertical_strip=printer_id == "bambu-a1-mini",
        minimum_tower_footprint_width=(
            _CREATOR_5_TOWER_MIN_FOOTPRINT_WIDTH_MM
            if uses_creator_5_tower_interface
            else _ANYCUBIC_TOWER_MIN_FOOTPRINT_WIDTH_MM
            if uses_anycubic_tower_interface else 0.0
        ),
        minimum_tower_depth=(
            _CREATOR_5_TOWER_MIN_DEPTH_MM
            if uses_creator_5_tower_interface
            else _ANYCUBIC_TOWER_MIN_DEPTH_MM
            if uses_anycubic_tower_interface else 0.0
        ),
    )


def build_wipe_tower_patch_settings(
    placement: WipeTowerPlacementResult | None,
) -> dict[str, Any]:
    """Translate a usable body placement into FatCat's native tower request.

    将可用实体布局转换为 FatCat 原生塔请求；底边待确认时仍报告警告，无解时保留设置。

    Args:
        placement: Shared solver result. 共享布局求解结果。

    Returns:
        Native tower changes, or no changes without a usable body layout.
        原生塔变更；实体布局无解时不修改塔设置。
    """

    if placement is None or not placement.placement_available:
        return {}
    settings: dict[str, Any] = {
        "enabled": True,
        "width_mm": placement.tower_width,
        "rotation_deg": placement.tower_rotation,
        "positions": [{
            "plate_index": 0, "x_mm": placement.tower_x, "y_mm": placement.tower_y,
        }],
    }
    if placement.tower_wall_type is not None:
        settings["wall_type"] = placement.tower_wall_type
    return settings


def build_wipe_tower_placement_metadata_payload(
    placement: WipeTowerPlacementResult | None,
    *,
    enabled: bool,
    output_path: str,
    printer_id: str,
    slicer: str,
) -> dict[str, Any]:
    """Describe Lumina's computed placement for Fat Cat to serialize.

    返回 Lumina 已计算的摆放结果，由 Fat Cat 负责最终 JSON 部件序列化。

    Args:
        placement: Computed placement, if available. 可用时提供计算后的摆放结果。
        enabled: User's placement choice. 用户的摆放选项。
        output_path: Destination for existing diagnostics. 现有诊断使用的输出路径。
        printer_id: Product printer identity. 产品打印机身份。
        slicer: Selected slicer identity. 所选切片软件身份。

    Returns:
        Placement facts passed to FatCat. 传给 FatCat 的摆放事实。
    """

    if not enabled:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "enabled": False,
            "available": False,
            "adapted": False,
            "requires_manual_adjustment": False,
            "warning_code": None,
            "reason": "disabled_by_user",
        }
    elif placement is None:
        log.warning(
            "Printable area unavailable for wipe-tower validation",
            extra={
                "event": "wipe_tower_manual_adjustment_required",
                "error_type": "PrintableAreaUnavailable",
                "error_message": (
                    "Generated without scaling the model or disabling the wipe tower; "
                    "manual slicer validation is required."
                ),
                "path": output_path,
                "printer_id": printer_id,
                "slicer": slicer,
            },
        )
        payload = {
            "schema_version": 1,
            "enabled": True,
            "available": False,
            "adapted": False,
            "requires_manual_adjustment": True,
            "warning_code": WIPE_TOWER_MANUAL_WARNING_CODE,
            "reason": "printable_area_unavailable",
        }
    elif not placement.placement_available:
        # Report the conservative search result without presenting an unsafe
        # candidate's translation or tower changes as an applied placement.
        payload = {
            "schema_version": 1, "enabled": True, "available": True,
            "adapted": False, "placement_applied": False,
            "requires_manual_adjustment": True,
            "warning_code": WIPE_TOWER_MANUAL_WARNING_CODE,
            "reason": placement.reason,
            "model_size_mm": [placement.model_bounds.width, placement.model_bounds.height],
            "reserved_envelope_mm": [placement.model_outer_bounds.width, placement.model_outer_bounds.height],
            "envelope_policy": "axis_aligned_bounds_with_full_brim_allowance",
            "printable_bounds_mm": (
                [placement.bed_bounds.width, placement.bed_bounds.height]
                if placement.bed_bounds else None
            ),
        }
    else:
        payload = {
            "schema_version": 1,
            "enabled": True,
            "available": True,
            "adapted": placement.adapted,
            "placement_applied": True,
            "model_brim_requires_review": placement.model_brim_requires_review,
            "requires_manual_adjustment": placement.requires_manual_adjustment,
            "warning_code": placement.warning_code,
            "reason": placement.reason,
            "model_translation_mm": list(placement.model_translation),
            "model_bounds_mm": [
                placement.model_bounds.left,
                placement.model_bounds.bottom,
                placement.model_bounds.right,
                placement.model_bounds.top,
            ],
            "model_outer_bounds_mm": [
                placement.model_outer_bounds.left,
                placement.model_outer_bounds.bottom,
                placement.model_outer_bounds.right,
                placement.model_outer_bounds.top,
            ],
            "tower": {
                "x_mm": placement.tower_x,
                "y_mm": placement.tower_y,
                "width_mm": placement.tower_width,
                "estimated_depth_mm": placement.tower_depth,
                "rotation_deg": placement.tower_rotation,
                "outer_bounds_mm": [
                    placement.tower_outer_bounds.left,
                    placement.tower_outer_bounds.bottom,
                    placement.tower_outer_bounds.right,
                    placement.tower_outer_bounds.top,
                ],
            },
        }
    return payload
