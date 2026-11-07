"""Shared packaging contract for the Fat Cat C++ metadata runtime.

Native wheel builders and CI use this contract to verify dependency identity,
entry points, and metadata data files.
"""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path
from typing import Any


FATCAT_DISTRIBUTION = "fatcat-metadata"
FATCAT_MODULE = "fatcat_metadata"
FATCAT_ADAPTER_MODULE = "fatcat_metadata_neroued"
FATCAT_VERSION = "0.1.5"
FATCAT_REPOSITORY = "https://github.com/MOVIBALE/fatcat-metadata"
FATCAT_SOURCE_COMMIT = "6491c6b570bea86395ded65e4054afca878066c1"
FATCAT_LEGACY_DISTRIBUTION = "lumina-3mf-metadata-cpp"
FATCAT_WRITER_DISTRIBUTION = "neroued-3mf"
FATCAT_WRITER_VERSION = "0.4.2"
FATCAT_WRITER_REPOSITORY = "https://github.com/Neroued/neroued_3mf.git"
FATCAT_WRITER_SOURCE_COMMIT = "656f87c55caf742cef2e958a7fc5199cdba2c6f0"
FATCAT_REQUIRED_ENTRY_POINTS = (
    "metadata_target",
    "metadata_resource_specs",
    "native_project_source_catalog",
    "native_project_source",
    "list_native_fields",
    "compose_project_settings",
    "resolve_project_materials",
    "compose_model_metadata",
    "patch_wipe_tower",
    "read_source_metadata",
    "read_project_layout",
    "read_placement_warnings",
    "read_model_object_metadata",
    "extract_source_material_slots",
    "serialize_layer_config_ranges",
    "template_import_parts",
    "resolve_template_build_plate",
    "detect_template_source",
    "import_template_metadata",
    "validate_template_hardware",
)
FATCAT_REQUIRED_DATA_FILES = (
    Path("translations/canonical.json"),
    Path("translations/targets/bambu-studio-02.09.01.70.json"),
    Path("translations/targets/orca-slicer-2.4.2.json"),
    Path("translations/targets/qidi-studio-02.07.02.73.json"),
    Path("translations/targets/elegoo-slicer-1.5.3.5.json"),
    Path("translations/targets/anycubic-slicer-next-2.0.0.6.json"),
    Path("translations/targets/flash-studio-1.7.19.json"),
    Path("translations/targets/snapmaker-orca-2.4.1.json"),
    Path("translations/targets/prusa-slicer-3.0.0-alpha13.json"),
    Path("native_project_sources/source-index.json"),
    Path("native_project_sources/prusa-3/catalog.json"),
    Path("native_project_sources/prusa-3/schema.json"),
)


def validate_fatcat_packaging_contract(
    fatcat_module: Any,
    writer_module: Any,
) -> Path:
    """Validate native package identity and return its bundled data root.

    校验 Fat Cat 与 Production writer 的版本、公开入口和随包数据，并返回数据根目录。

    Args:
        fatcat_module: Imported ``fatcat_metadata`` module. 已导入的元数据模块。
        writer_module: Imported ``neroued_3mf`` module.

    Returns:
        The resolved ``fatcat_metadata_data`` directory.

    Raises:
        RuntimeError: If a required module, version, or entry point is absent.
        FileNotFoundError: If required Fat Cat data is absent.
    """

    if writer_module is None:
        raise RuntimeError("neroued writer module is unavailable")

    try:
        fatcat_version = metadata.version(FATCAT_DISTRIBUTION)
        writer_version = metadata.version(FATCAT_WRITER_DISTRIBUTION)
    except metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "required native 3MF distributions are not installed"
        ) from exc

    if fatcat_version != FATCAT_VERSION:
        raise RuntimeError(
            f"unexpected Fat Cat C++ distribution version: {fatcat_version}"
        )
    if writer_version != FATCAT_WRITER_VERSION:
        raise RuntimeError(
            "native 3MF export requires the pinned Production writer "
            f"{FATCAT_WRITER_VERSION}, got {writer_version}"
        )

    missing_entry_points = [
        name
        for name in FATCAT_REQUIRED_ENTRY_POINTS
        if not callable(getattr(fatcat_module, name, None))
    ]
    if missing_entry_points:
        raise RuntimeError(
            f"Fat Cat C++ binding is missing entry points: {missing_entry_points}"
        )

    module_file = getattr(fatcat_module, "__file__", None)
    if not module_file:
        raise RuntimeError("Fat Cat C++ binding has no module file")
    data_root = Path(module_file).resolve().parent / "fatcat_metadata_data"
    if not data_root.is_dir():
        raise FileNotFoundError(f"Fat Cat packaged data is missing: {data_root}")

    missing_data = [
        relative_path
        for relative_path in FATCAT_REQUIRED_DATA_FILES
        if not (data_root / relative_path).is_file()
    ]
    if missing_data:
        rendered = ", ".join(path.as_posix() for path in missing_data)
        raise FileNotFoundError(
            f"Fat Cat packaged data files are missing under {data_root}: {rendered}"
        )
    return data_root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--get", required=True, choices=(
        "FATCAT_DISTRIBUTION", "FATCAT_MODULE", "FATCAT_VERSION",
        "FATCAT_REPOSITORY", "FATCAT_SOURCE_COMMIT",
        "FATCAT_WRITER_DISTRIBUTION", "FATCAT_WRITER_VERSION",
        "FATCAT_WRITER_REPOSITORY", "FATCAT_WRITER_SOURCE_COMMIT",
    ))
    print(globals()[parser.parse_args().get])
