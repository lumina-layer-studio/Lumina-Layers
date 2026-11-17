from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image

from tools.machine_adapter.build_plates import (
    LUMINA_NEUTRAL_BUILD_PLATE_FILENAMES,
    LUMINA_NEUTRAL_BUILD_PLATE_SOURCE_VERSION,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _registry_root() -> Path:
    return _repo_root() / "machine_registry"


def _load_registry() -> dict[str, Any]:
    path = _registry_root() / "registry.json"
    assert path.exists(), "machine_registry/registry.json must be bundled"
    return json.loads(path.read_text(encoding="utf-8"))


def _slicers_by_id(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    slicers: dict[str, list[dict[str, Any]]] = {}
    for slicer in data["slicers"]:
        slicers.setdefault(str(slicer["slicer_id"]), []).append(slicer)
    return slicers


def _device_ids(data: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for slicer in data["slicers"]:
        for machine in slicer["machines"]:
            for nozzle in machine["nozzles"]:
                ids.add(str(nozzle["device_profile_id"]))
    return ids


def test_bundled_machine_registry_assets_exist() -> None:
    root = _registry_root()
    data = _load_registry()
    assert not [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() == ".stl"
    ], (
        "Third-party bed models must never be bundled in the Lumina registry"
    )
    device_ids: set[str] = set()

    for slicer in data["slicers"]:
        build_plate_ids: set[str] = set()
        for plate in slicer.get("build_plates", []):
            plate_id = str(plate["id"])
            assert plate_id not in build_plate_ids
            build_plate_ids.add(plate_id)
            image_path = root / str(plate["image"])
            assert image_path.exists(), str(plate["image"])
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            assert plate["revision"] == f"sha256:{digest}"
            assert plate["source_path"] == (
                f"LuminaStudio:generated/build_plates/{image_path.name}"
            )
            assert plate["source_version"] == (
                LUMINA_NEUTRAL_BUILD_PLATE_SOURCE_VERSION
            )
        for machine in slicer["machines"]:
            supported_plate_ids = {
                str(value) for value in machine.get("supported_build_plate_ids", [])
            }
            assert supported_plate_ids <= build_plate_ids
            default_plate_id = str(machine.get("default_build_plate_id") or "")
            if default_plate_id:
                assert default_plate_id in supported_plate_ids
            thumbnail = str(machine.get("thumbnail") or "")
            assert thumbnail, f"{machine['display_name']} is missing a thumbnail"
            assert (root / thumbnail).exists(), thumbnail
            bed_model = str(machine.get("bed_model") or "")
            assert bed_model.casefold().endswith(".stl"), (
                f"{machine['display_name']} is missing its slicer-native bed model"
            )
            assert Path(bed_model).name == bed_model
            assert "/" not in bed_model and "\\" not in bed_model
            assert not (root / bed_model).exists(), (
                "Third-party bed models must be read from the user's installed slicer"
            )
            for nozzle in machine["nozzles"]:
                device_profile_id = str(nozzle["device_profile_id"])
                assert device_profile_id not in device_ids
                device_ids.add(device_profile_id)


def test_bundled_build_plate_art_uses_one_app_owned_neutral_asset_set() -> None:
    root = _registry_root()
    data = _load_registry()
    referenced_images = {
        str(plate["image"])
        for slicer in data["slicers"]
        for plate in slicer.get("build_plates", [])
    }

    assert referenced_images == {
        f"build_plates/{filename}"
        for filename in LUMINA_NEUTRAL_BUILD_PLATE_FILENAMES
    }
    assert not list((root / "slicers").glob("*/*/build_plates/*"))
    for relative_path in referenced_images:
        with Image.open(root / relative_path).convert("RGBA") as image:
            assert image.size == (320, 220)
            assert image.getpixel((0, 0))[3] == 0
            assert image.getbbox() is not None


def test_bundled_registry_has_native_build_plates_for_primary_slicers() -> None:
    slicers = _slicers_by_id(_load_registry())

    for slicer_id in ("BambuStudio", "OrcaSlicer", "SnapmakerOrca", "ElegooSlicer"):
        entries = slicers[slicer_id]
        assert any(entry.get("build_plates") for entry in entries), slicer_id
        for entry in entries:
            if not entry.get("build_plates"):
                continue
            assert all(
                machine.get("default_build_plate_id")
                for machine in entry["machines"]
            )


def test_bundled_h2d_excludes_officially_unsupported_cool_plate() -> None:
    bambu = _slicers_by_id(_load_registry())["BambuStudio"][0]
    h2d = next(
        machine for machine in bambu["machines"] if machine["display_name"] == "Bambu Lab H2D"
    )

    assert "cool-plate" not in h2d["supported_build_plate_ids"]


def test_bundled_kobra_s1_excludes_zero_temperature_engineering_plate() -> None:
    anycubic = _slicers_by_id(_load_registry())["AnycubicSlicerNext"][0]
    kobra_s1 = next(
        machine
        for machine in anycubic["machines"]
        if machine["display_name"] == "Anycubic Kobra S1"
    )

    assert "engineering-plate" not in kobra_s1["supported_build_plate_ids"]


def test_bundled_snapmaker_u1_uses_nozzle_plate_intersection() -> None:
    snapmaker = _slicers_by_id(_load_registry())["SnapmakerOrca"][0]
    u1 = next(
        machine for machine in snapmaker["machines"] if machine["display_name"] == "Snapmaker U1"
    )

    assert u1["supported_build_plate_ids"] == ["textured-pei-plate"]
    assert u1["default_build_plate_id"] == "textured-pei-plate"


def test_bambu_machine_thumbnails_use_antialiased_transparent_artwork() -> None:
    root = _registry_root()
    data = _load_registry()

    for slicer in data["slicers"]:
        for machine in slicer["machines"]:
            if machine["brand"] != "Bambu Lab":
                continue

            thumbnail = root / str(machine["thumbnail"])
            with Image.open(thumbnail).convert("RGBA") as image:
                width, height = image.size
                alpha = image.getchannel("A")
                corner_alpha = {
                    image.getpixel((0, 0))[3],
                    image.getpixel((width - 1, 0))[3],
                    image.getpixel((0, height - 1))[3],
                    image.getpixel((width - 1, height - 1))[3],
                }
                partial_alpha_pixels = sum(alpha.histogram()[1:255])

            # Official H3C artwork is 180px; preserve it without artificial upscaling.
            assert min(width, height) >= 180, str(machine["thumbnail"])
            assert corner_alpha == {0}, str(machine["thumbnail"])
            assert partial_alpha_pixels >= 256, str(machine["thumbnail"])


def test_bundled_machine_registry_keeps_upgraded_ac_and_elegoo_versions() -> None:
    slicers = _slicers_by_id(_load_registry())

    anycubic = slicers["AnycubicSlicerNext"][0]
    assert anycubic["source_version"] == "1.3.2605.22"

    elegoo = slicers["ElegooSlicer"][0]
    assert elegoo["source_version"] == "01.05.01.06"

    flash_studio = slicers["FlashStudio"][0]
    assert flash_studio["source_version"] == "02.01.01.00"
    assert {
        machine["display_name"]: [nozzle["nozzle_size"] for nozzle in machine["nozzles"]]
        for machine in flash_studio["machines"]
    } == {
        "Flashforge AD5X": ["0.25", "0.4"],
        "Flashforge Creator 5": ["0.25", "0.4"],
        "Flashforge Creator 5 Pro": ["0.25", "0.4"],
        "Flashforge Guider 3 Ultra": ["0.4"],
        "Flashforge Guider4": ["0.25", "0.4"],
        "Flashforge Guider4 Pro": ["0.25", "0.4"],
    }

    qidi_studio = slicers["QIDIStudio"][0]
    assert qidi_studio["source_version"] == "02.07.02.60"
    assert {
        machine["display_name"]: [nozzle["nozzle_size"] for nozzle in machine["nozzles"]]
        for machine in qidi_studio["machines"]
    } == {
        "Q2": ["0.2", "0.4"],
        "Q2C": ["0.2", "0.4"],
        "X-Max 4": ["0.2", "0.4"],
        "X-Plus 5": ["0.4"],
    }


def test_bundled_machine_registry_contains_acceptance_profiles() -> None:
    ids = _device_ids(_load_registry())

    assert {
        "AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.4",
        "ElegooSlicer:elegoo:elegoo-centauri-carbon-2:0.4",
        "BambuStudio:bbl:bambu-lab-h2d:0.2",
        "BambuStudio:bbl:bambu-lab-h2d:0.4",
        "BambuStudio:bbl:bambu-lab-x2d:0.4",
        "BambuStudio:bbl:bambu-lab-a2l:0.4",
        "SnapmakerOrca:snapmaker:snapmaker-u1:0.4",
        "FlashStudio:flashforge:flashforge-ad5x:0.25",
        "FlashStudio:flashforge:flashforge-ad5x:0.4",
        "FlashStudio:flashforge:flashforge-creator-5:0.4",
        "FlashStudio:flashforge:flashforge-creator-5-pro:0.25",
        "FlashStudio:flashforge:flashforge-guider-3-ultra:0.4",
        "FlashStudio:flashforge:flashforge-guider4:0.4",
        "FlashStudio:flashforge:flashforge-guider4-pro:0.25",
        "QIDIStudio:qidi:q2:0.2",
        "QIDIStudio:qidi:q2:0.4",
        "QIDIStudio:qidi:q2c:0.4",
        "QIDIStudio:qidi:x-max-4:0.2",
        "QIDIStudio:qidi:x-max-4:0.4",
        "QIDIStudio:qidi:x-plus-5:0.4",
    } <= ids
