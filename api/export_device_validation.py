from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from api.errors import to_http_exception
from core.errors import TemplateMaterialMappingError
from core.machine_registry import (
    MachineRegistrySelectionError,
    load_machine_registry,
    resolve_machine_registry_root,
    validate_device_profile_selection,
)


def _machine_registry_path() -> Path:
    return resolve_machine_registry_root() / "registry.json"


def validate_export_device_selection(
    *,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    device_profile_id: str | None,
    build_plate_id: str | None,
    custom_3mf_template_id: str | None = None,
    supports_custom_template: bool = False,
) -> None:
    """Validate explicit machine-registry selections at the API boundary.

    在 API 边界校验显式传入的机器注册表设备与打印板组合。旧客户端未传
    两个注册表字段时保持兼容；只要显式传入设备，就严格校验其完整身份。

    Args:
        printer_id: Requested printer ID. 请求的打印机 ID。
        slicer: Requested slicer ID. 请求的切片软件 ID。
        nozzle_size: Requested nozzle size. 请求的喷嘴尺寸。
        device_profile_id: Optional registry device ID. 可选注册表设备 ID。
        build_plate_id: Optional native build plate ID. 可选原生打印板 ID。
        custom_3mf_template_id: Saved template ID. 已保存的模板 ID。
        supports_custom_template: Whether this export supports templates.
            当前导出是否支持自定义模板。

    Raises:
        HTTPException: 422 for invalid combinations or 503 when the registry
            cannot be loaded. 组合非法时返回 422，注册表不可用时返回 503。
            Custom templates return 400 when unsupported or mismatched, and
            404 when missing. 自定义模板不支持或不匹配返回 400，缺失返回 404。
    """
    if custom_3mf_template_id:
        if not supports_custom_template:
            raise HTTPException(
                status_code=400,
                detail="Custom 3MF templates are not supported for this export.",
            )
        from utils.bambu_3mf_writer import load_export_project_settings

        try:
            load_export_project_settings(
                printer_id,
                slicer,
                nozzle_size,
                device_profile_id,
                custom_3mf_template_id=custom_3mf_template_id,
            )
        except TemplateMaterialMappingError as exc:
            raise to_http_exception(exc, "Custom 3MF template") from exc
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Custom 3MF template was not found. Select or import a template again.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    selected_device_id = str(device_profile_id or "").strip()
    selected_plate_id = str(build_plate_id or "").strip()
    if not selected_device_id:
        if selected_plate_id:
            raise HTTPException(
                status_code=422,
                detail="build_plate_id requires device_profile_id.",
            )
        return

    try:
        registry = load_machine_registry(_machine_registry_path())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Machine registry is unavailable.",
        ) from exc

    try:
        validate_device_profile_selection(
            registry,
            device_profile_id=selected_device_id,
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=nozzle_size,
            build_plate_id=selected_plate_id,
        )
    except MachineRegistrySelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
