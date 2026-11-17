from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import re
import struct
from typing import Any
import zlib


LUMINA_NEUTRAL_BUILD_PLATE_SOURCE_VERSION = "lumina-neutral-v1"
LUMINA_NEUTRAL_BUILD_PLATE_FILENAMES = (
    "bed_cool.png",
    "bed_engineering.png",
    "bed_high_templ.png",
    "bed_pei.png",
    "bed_pei_cool.png",
    "bed_cool_supertack.png",
)

_NEUTRAL_IMAGE_BY_PLATE_ID = {
    "cool-plate": "bed_cool.png",
    "smooth-cool-plate": "bed_cool.png",
    "engineering-plate": "bed_engineering.png",
    "smooth-pei-plate": "bed_high_templ.png",
    "smooth-high-temp-plate": "bed_high_templ.png",
    "textured-pei-plate": "bed_pei.png",
    "textured-cool-plate": "bed_pei_cool.png",
    "supertack-plate": "bed_cool_supertack.png",
}

_NEUTRAL_PLATE_STYLES = {
    "bed_cool.png": ((61, 75, 92, 255), (119, 193, 226, 255), "grid"),
    "bed_engineering.png": ((56, 61, 68, 255), (220, 167, 92, 255), "grid"),
    "bed_high_templ.png": ((77, 82, 89, 255), (205, 211, 218, 255), "smooth"),
    "bed_pei.png": ((154, 119, 61, 255), (234, 198, 125, 255), "texture"),
    "bed_pei_cool.png": ((64, 81, 103, 255), (139, 180, 210, 255), "texture"),
    "bed_cool_supertack.png": ((70, 72, 88, 255), (139, 211, 161, 255), "diagonal"),
}


@dataclass(frozen=True)
class NativeBuildPlateSpec:
    """Picker labels and the upstream value used to resolve machine support.

    选择器标签及解析机型支持范围时使用的上游打印板名称。
    """

    id: str
    display_name: str
    project_value: str
    display_name_zh: str = ""


_BAMBU_PLATES = (
    NativeBuildPlateSpec(
        "cool-plate",
        "Cool Plate",
        "Cool Plate",
        display_name_zh="低温打印板",
    ),
    NativeBuildPlateSpec(
        "engineering-plate",
        "Engineering Plate",
        "Engineering Plate",
        display_name_zh="工程材料打印板",
    ),
    NativeBuildPlateSpec(
        "smooth-pei-plate",
        "Smooth PEI Plate / High Temp Plate",
        "High Temp Plate",
        display_name_zh="光面PEI打印板 / 高温打印板",
    ),
    NativeBuildPlateSpec(
        "textured-pei-plate",
        "Textured PEI Plate",
        "Textured PEI Plate",
        display_name_zh="纹理PEI打印板",
    ),
    NativeBuildPlateSpec(
        "supertack-plate",
        "Bambu Cool Plate SuperTack",
        "Supertack Plate",
        display_name_zh="增稳低温打印板",
    ),
)

_ORCA_PLATES = (
    NativeBuildPlateSpec(
        "smooth-cool-plate",
        "Smooth Cool Plate",
        "Cool Plate",
        display_name_zh="光滑的低温打印床",
    ),
    NativeBuildPlateSpec(
        "engineering-plate",
        "Engineering Plate",
        "Engineering Plate",
        display_name_zh="工程材料热床",
    ),
    NativeBuildPlateSpec(
        "smooth-high-temp-plate",
        "Smooth High Temp Plate",
        "High Temp Plate",
        display_name_zh="光滑高温打印热床",
    ),
    NativeBuildPlateSpec(
        "textured-pei-plate",
        "Textured PEI Plate",
        "Textured PEI Plate",
        display_name_zh="纹理PEI热床",
    ),
    NativeBuildPlateSpec(
        "textured-cool-plate",
        "Textured Cool Plate",
        "Textured Cool Plate",
        display_name_zh="纹理的低温打印床",
    ),
    NativeBuildPlateSpec(
        "supertack-plate",
        "Cool Plate (SuperTack)",
        "Supertack Plate",
        display_name_zh="低温打印板（超强粘附）",
    ),
)

_SNAPMAKER_PLATES = _ORCA_PLATES

_ELEGOO_TRANSLATIONS = {
    "smooth-cool-plate": "光滑的低温打印床",
    "engineering-plate": "工程耗材热床",
    "smooth-high-temp-plate": "光滑高温打印热床",
    "textured-pei-plate": "纹理PEI热床",
    "textured-cool-plate": "纹理的低温打印床",
    "supertack-plate": "低温打印板（超强粘附）",
}
_ELEGOO_PLATES = tuple(
    replace(
        spec,
        display_name_zh=_ELEGOO_TRANSLATIONS[spec.id],
    )
    for spec in _ORCA_PLATES
)

_ANYCUBIC_DISPLAY_NAMES = {
    "smooth-cool-plate": "Cool Plate",
    "engineering-plate": "Engineering Plate",
    "smooth-high-temp-plate": "High Temp Plate",
    "textured-pei-plate": "Textured PEI Plate",
    "textured-cool-plate": "Textured Cool Plate",
    "supertack-plate": "Cool Plate (SuperTack)",
}
_ANYCUBIC_TRANSLATIONS = {
    "smooth-cool-plate": "低温打印板",
    "engineering-plate": "工程材料打印板",
    # Anycubic omits this msgid; retain the established translated vocabulary.
    "smooth-high-temp-plate": "光滑高温打印热床",
    "textured-pei-plate": "纹理 PEI 打印板",
    "textured-cool-plate": "增稳低温打印板",
    "supertack-plate": "低温打印板（SuperTack）",
}
_ANYCUBIC_PLATES = tuple(
    replace(
        spec,
        display_name=_ANYCUBIC_DISPLAY_NAMES[spec.id],
        display_name_zh=_ANYCUBIC_TRANSLATIONS[spec.id],
    )
    for spec in _ORCA_PLATES
)

_FLASH_STUDIO_PLATES = _ORCA_PLATES

_PLATES_BY_SLICER = {
    "BambuStudio": _BAMBU_PLATES,
    "OrcaSlicer": _ORCA_PLATES,
    "ElegooSlicer": _ELEGOO_PLATES,
    "SnapmakerOrca": _SNAPMAKER_PLATES,
    "AnycubicSlicerNext": _ANYCUBIC_PLATES,
    "FlashStudio": _FLASH_STUDIO_PLATES,
}

_ALIASES = {
    "coolplate": "Cool Plate",
    "smoothcoolplate": "Cool Plate",
    "engineeringplate": "Engineering Plate",
    "hightempplate": "High Temp Plate",
    "smoothhightempplate": "High Temp Plate",
    "smoothpeiplatehightempplate": "High Temp Plate",
    "texturedpeiplate": "Textured PEI Plate",
    "texturedcoolplate": "Textured Cool Plate",
    "supertackplate": "Supertack Plate",
    "bambucoolplatesupertack": "Supertack Plate",
    "coolplatesupertack": "Supertack Plate",
}

_VALIDATED_NATIVE_SLICE_EXCLUSIONS: dict[
    tuple[str, str, str], frozenset[str]
] = {
    # Anycubic Slicer Next 1.4.1.1 with this pinned profile snapshot emits
    # M140 S0 for Engineering Plate on Kobra S1. Scope the acceptance result
    # to the stable machine profile ID so other models and versions are not
    # filtered by inference.
    (
        "AnycubicSlicerNext",
        "1.3.2605.22",
        "AnycubicSlicerNext:anycubic:anycubic-kobra-s1",
    ): frozenset({"engineering-plate"}),
}


def native_build_plate_specs(slicer_id: str) -> tuple[NativeBuildPlateSpec, ...]:
    """Return the native plate catalog for a supported slicer family.

    返回受支持切片软件家族的原生打印板目录。
    """

    return _PLATES_BY_SLICER.get(slicer_id, ())


def apply_validated_build_plate_exclusions(
    *,
    slicer_id: str,
    source_version: str,
    machine_profile_id: str,
    supported_plate_ids: list[str],
) -> list[str]:
    """Apply exact native-slice exclusions for one pinned machine snapshot.

    应用绑定到切片软件版本与稳定机器 ID 的真实切片排除项。
    """

    excluded = _VALIDATED_NATIVE_SLICE_EXCLUSIONS.get(
        (slicer_id, source_version, machine_profile_id),
        frozenset(),
    )
    return [plate_id for plate_id in supported_plate_ids if plate_id not in excluded]


def intersect_machine_build_plate_scopes(
    resolutions: list[tuple[list[str], str]],
) -> tuple[list[str], str]:
    """Intersect per-nozzle plate scopes while preserving catalog order.

    对同一机器的逐喷嘴打印板能力求交集，并保持目录顺序和有效默认值。
    """

    if not resolutions:
        return [], ""
    supported = list(resolutions[0][0])
    for nozzle_supported, _ in resolutions[1:]:
        allowed = set(nozzle_supported)
        supported = [plate_id for plate_id in supported if plate_id in allowed]
    if not supported:
        return [], ""
    default = next(
        (
            nozzle_default
            for _, nozzle_default in resolutions
            if nozzle_default in supported
        ),
        supported[0],
    )
    return supported, default


def _canonical_plate_value(value: Any, *, slicer_id: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.isdigit():
        values = [spec.project_value for spec in native_build_plate_specs(slicer_id)]
        index = int(raw) - 1
        return values[index] if 0 <= index < len(values) else ""
    key = re.sub(r"[^a-z0-9]+", "", raw.casefold())
    return _ALIASES.get(key, raw)


def resolve_machine_build_plates(
    *,
    slicer_id: str,
    settings: dict[str, Any],
    available_plate_ids: set[str],
    source_version: str = "",
    machine_profile_id: str = "",
) -> tuple[list[str], str]:
    """Resolve one machine's supported plates and native default.

    根据机器原生配置解析受支持打印板和默认打印板。
    """

    native_multi_bed_flag = settings.get("support_multi_bed_types")
    multi_bed_disabled = str(native_multi_bed_flag).strip().casefold() in {
        "0",
        "false",
        "off",
    }
    if (
        slicer_id in {"ElegooSlicer", "AnycubicSlicerNext"}
        and multi_bed_disabled
    ):
        return [], ""

    specs = [
        spec
        for spec in native_build_plate_specs(slicer_id)
        if spec.id in available_plate_ids
    ]
    unsupported_raw = settings.get("not_support_bed_type")
    if isinstance(unsupported_raw, list):
        unsupported_values = unsupported_raw
    else:
        unsupported_values = re.split(r"[;,]", str(unsupported_raw or ""))
    unsupported = {
        _canonical_plate_value(value, slicer_id=slicer_id)
        for value in unsupported_values
        if str(value).strip()
    }
    supported = [spec for spec in specs if spec.project_value not in unsupported]
    supported_ids = apply_validated_build_plate_exclusions(
        slicer_id=slicer_id,
        source_version=source_version,
        machine_profile_id=machine_profile_id,
        supported_plate_ids=[spec.id for spec in supported],
    )
    supported = [spec for spec in supported if spec.id in supported_ids]
    if not supported:
        return [], ""

    configured_default = _canonical_plate_value(
        settings.get("default_bed_type") or settings.get("curr_bed_type"),
        slicer_id=slicer_id,
    )
    if slicer_id == "FlashStudio" and multi_bed_disabled:
        # Flash's fixed-bed GUI uses High Temp Plate (enum 3) if the
        # machine defines no default. It does not offer the other plates.
        fixed_value = configured_default or _canonical_plate_value("3", slicer_id=slicer_id)
        fixed = next((spec for spec in supported if spec.project_value == fixed_value), None)
        return ([fixed.id], fixed.id) if fixed else ([], "")
    default = next(
        (spec for spec in supported if spec.project_value == configured_default),
        None,
    )
    if default is None:
        default = next(
            (spec for spec in supported if spec.project_value == "Textured PEI Plate"),
            supported[0],
        )
    if slicer_id == "SnapmakerOrca" and multi_bed_disabled:
        return [default.id], default.id
    return [spec.id for spec in supported], default.id


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", checksum)
    )


def _inside_rounded_rect(
    x: int,
    y: int,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    radius: int,
) -> bool:
    if (
        left + radius <= x <= right - radius
        or top + radius <= y <= bottom - radius
    ):
        return left <= x <= right and top <= y <= bottom
    center_x = left + radius if x < left + radius else right - radius
    center_y = top + radius if y < top + radius else bottom - radius
    return (x - center_x) ** 2 + (y - center_y) ** 2 <= radius**2


def _neutral_build_plate_png(filename: str) -> bytes:
    """Render one deterministic app-owned neutral build-plate PNG.

    生成一张确定性的 Lumina 自有中性打印板 PNG。
    """

    fill, accent, pattern = _NEUTRAL_PLATE_STYLES[filename]
    width, height = 320, 220
    pixels = bytearray(width * height * 4)

    def set_pixel(x: int, y: int, color: tuple[int, int, int, int]) -> None:
        offset = (y * width + x) * 4
        pixels[offset : offset + 4] = bytes(color)

    for y in range(height):
        for x in range(width):
            in_shadow = _inside_rounded_rect(
                x,
                y,
                left=17,
                top=31,
                right=307,
                bottom=207,
                radius=17,
            )
            if in_shadow:
                set_pixel(x, y, (12, 18, 25, 54))

            in_plate = _inside_rounded_rect(
                x,
                y,
                left=13,
                top=26,
                right=303,
                bottom=203,
                radius=16,
            )
            in_handle = 137 <= x <= 179 and 18 <= y <= 34
            if not in_plate and not in_handle:
                continue

            border = not _inside_rounded_rect(
                x,
                y,
                left=18,
                top=31,
                right=298,
                bottom=198,
                radius=12,
            )
            color = accent if border else fill
            if not border:
                local_x = x - 18
                local_y = y - 31
                highlighted = False
                if pattern == "grid":
                    highlighted = local_x % 24 == 0 or local_y % 24 == 0
                elif pattern == "texture":
                    highlighted = (local_x * 17 + local_y * 31) % 113 < 3
                elif pattern == "diagonal":
                    highlighted = (local_x + local_y) % 28 < 2
                elif pattern == "smooth":
                    highlighted = local_y in {1, 2}
                if highlighted:
                    color = (
                        (fill[0] * 3 + accent[0]) // 4,
                        (fill[1] * 3 + accent[1]) // 4,
                        (fill[2] * 3 + accent[2]) // 4,
                        255,
                    )
            set_pixel(x, y, color)

    scanlines = b"".join(
        b"\x00" + bytes(pixels[y * width * 4 : (y + 1) * width * 4])
        for y in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + _png_chunk(b"IEND", b"")
    )


def _write_neutral_build_plate_assets(output_root: Path) -> dict[str, bytes]:
    asset_root = output_root / "build_plates"
    asset_root.mkdir(parents=True, exist_ok=True)
    assets: dict[str, bytes] = {}
    for filename in LUMINA_NEUTRAL_BUILD_PLATE_FILENAMES:
        payload = _neutral_build_plate_png(filename)
        (asset_root / filename).write_bytes(payload)
        assets[filename] = payload
    return assets


def copy_native_build_plate_assets(
    *,
    slicer_id: str,
    output_root: Path,
) -> list[dict[str, str]]:
    """Generate app-owned neutral plate artwork and emit registry records.

    生成 Lumina 自有中性打印板图片及带来源校验值的注册表记录。
    """

    assets = _write_neutral_build_plate_assets(output_root)
    payload: list[dict[str, str]] = []
    for spec in native_build_plate_specs(slicer_id):
        filename = _NEUTRAL_IMAGE_BY_PLATE_ID[spec.id]
        relative = Path("build_plates") / filename
        digest = hashlib.sha256(assets[filename]).hexdigest()
        payload.append(
            {
                "id": spec.id,
                "display_name": spec.display_name,
                "display_name_zh": spec.display_name_zh,
                "image": relative.as_posix(),
                "source_path": (
                    f"LuminaStudio:generated/build_plates/{filename}"
                ),
                "source_version": LUMINA_NEUTRAL_BUILD_PLATE_SOURCE_VERSION,
                "revision": f"sha256:{digest}",
            }
        )
    return payload
