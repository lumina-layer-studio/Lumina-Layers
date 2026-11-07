"""Lumina Studio API system schemas."""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool


class DeviceProfileInfo(BaseModel):
    """Slicer-scoped machine registry device profile metadata."""

    device_profile_id: str
    machine_profile_id: str
    slicer_id: str
    nozzle_size: str
    source_profile_name: str
    revision: str
    supported: bool = True
    build_plates: list["BuildPlateInfo"] = Field(default_factory=list)
    default_build_plate_id: str = ""


class BuildPlateInfo(BaseModel):
    """Slicer-native build plate available for one machine."""

    id: str
    display_name: str
    display_name_zh: str = ""
    image_url: str


class PrinterInfo(BaseModel):
    """Printer metadata exposed to frontend."""

    id: str
    display_name: str
    brand: str
    bed_width: int
    bed_depth: int
    bed_height: int
    supported_nozzle_sizes: list[str] = Field(default_factory=lambda: ["0.2", "0.4"])
    supported_slicers: list[str] = Field(default_factory=list)
    thumbnail: str = ""
    device_profiles: list[DeviceProfileInfo] = Field(default_factory=list)


class PrinterListResponse(BaseModel):
    """Response for GET /api/system/printers."""

    status: str
    printers: list[PrinterInfo]


class CacheCleanupDetails(BaseModel):
    """Detailed cache cleanup statistics."""

    registry_cleaned: int
    sessions_cleaned: int
    output_files_cleaned: int


class ClearCacheResponse(BaseModel):
    """Response body for cache cleanup."""

    status: str
    message: str
    deleted_files: int
    freed_bytes: int
    details: CacheCleanupDetails


@dataclass
class ClearCacheResult:
    """Internal aggregate result for perform_cache_cleanup."""

    registry_cleaned: int
    sessions_cleaned: int
    output_files_cleaned: int
    total_freed_bytes: int


class UserSettings(BaseModel):
    """User settings persisted in user_settings.json."""

    language: Literal["zh", "en"] = "zh"
    theme: Literal["light", "dark"] = "light"
    last_lut: str = ""
    last_modeling_mode: str = "high-fidelity"
    last_color_mode: str = "4-Color (RYBW)"
    last_slicer: str = ""
    last_bed_label: str = "256×256 mm"
    palette_mode: str = "swatch"
    enable_crop_modal: StrictBool = True
    enable_blur: StrictBool = True
    enable_fancy_loading: StrictBool = True
    enable_witty_loading: StrictBool = True
    enable_completion_notifications: StrictBool = False
    enable_smooth_vector_preview: StrictBool = True
    preserve_upload_filename_for_3mf: StrictBool = False
    printer_model: str = "bambu-h2d"
    slicer_software: str = "BambuStudio"
    custom_3mf_template_id: str | None = None
    device_profile_id: str = "BambuStudio:bbl:bambu-lab-h2d:0.4"
    build_plate_id: str = ""
    external_spool_selections: dict[str, str] = Field(default_factory=dict)
    build_plate_selections: dict[str, str] = Field(default_factory=dict)
    custom_slicer_path: str = ""
    custom_slicer_id: str = ""
    nozzle_size: str = "0.4"
    enable_base_layer_height_modifier: StrictBool = True
    enable_wipe_tower_auto_placement: StrictBool = True
    enable_solver_cache_grid_selection: StrictBool = False
    solver_cache_grid_resolution: Literal[64, 128, 256, 512, 1024, 2048] = 64
    svg_pixels_per_mm: float = Field(default=10.0, ge=2.0, le=50.0)
    material_delta_e00_tolerance: float = Field(default=0.5, ge=0.0, le=5.0)
    auto_replace_gradient_banding: StrictBool = False
    generated_file_directory: str = Field(default="", max_length=1024)
    header_nav_alignment: Literal["center", "left"] = "center"
    conversion_preferences: dict[str, Any] | None = None


class UserSettingsResponse(BaseModel):
    """Response for GET /api/system/settings."""

    status: str
    settings: UserSettings


class SaveSettingsResponse(BaseModel):
    """Response for POST /api/system/settings."""

    status: str
    message: str


class StatsResponse(BaseModel):
    """Response for GET /api/system/stats."""

    calibrations: int = 0
    extractions: int = 0
    conversions: int = 0


class SlicerInfo(BaseModel):
    """Slicer software metadata."""

    id: str
    display_name: str


class SlicerListResponse(BaseModel):
    """Response for GET /api/system/slicers."""

    status: str
    slicers: list[SlicerInfo]
