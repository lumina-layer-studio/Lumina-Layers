"""Single-stage calibration request schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from api.schemas.lut import PaletteEntrySchema
from config import DEFAULT_PRINTER_ID, DEFAULT_SLICER_ID


class SingleStageKitGenerateRequest(BaseModel):
    """Request model for generating a single-stage kit."""

    palette: list[PaletteEntrySchema] = Field(
        ...,
        min_length=1,
        description="Palette entries to generate one single-stage job per color.",
    )
    substrate_id: str = Field("white", description="Stable substrate identifier")
    substrate_display_name: str = Field(
        "White",
        description="User-facing substrate display name",
    )
    material_default: str = Field(
        "PLA Basic",
        description="Default material label used when palette entries omit material",
    )
    layer_height_mm: float = Field(
        0.04,
        ge=0.04,
        le=0.3,
        description="Layer height in millimeters for generated single-stage jobs",
    )
    printer_id: str = Field(DEFAULT_PRINTER_ID, description="Printer profile ID.")
    slicer: str = Field(DEFAULT_SLICER_ID, description="Slicer software ID.")
    custom_3mf_template_id: str | None = None
    nozzle_size: str = Field("0.4", description="Nozzle size.")
    device_profile_id: str | None = Field(None, description="Machine registry device profile ID.")
    build_plate_id: str | None = Field(None, description="Native slicer build plate ID.")


class StageAFitRequest(BaseModel):
    """Request model for fitting Stage A from a stored extraction session."""

    session_id: str | None = Field(
        None,
        description="Extraction session id carrying a stage JSON output",
    )

    @model_validator(mode="after")
    def validate_any_source(self) -> "StageAFitRequest":
        if self.session_id is not None and not str(self.session_id).strip():
            raise ValueError("session_id cannot be blank")
        return self


class GradientCardMaterialUpdateRequest(BaseModel):
    """Request model for updating saved material metadata."""

    material_name: str = Field(
        ...,
        description="Updated user-facing material name.",
    )
    brand: str | None = Field(
        None,
        description="Updated optional brand label.",
    )
    estimated_rgb: list[int] | None = Field(
        None,
        description=(
            "Optional user-overridden display sRGB [R, G, B] triplet in [0, 255]. "
            "Leave null or omit to keep the previously stored display color."
        ),
    )

    @field_validator("material_name")
    @classmethod
    def validate_material_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("material_name is required")
        return cleaned

    @field_validator("brand")
    @classmethod
    def normalize_brand(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("estimated_rgb")
    @classmethod
    def validate_estimated_rgb(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if len(value) != 3:
            raise ValueError("estimated_rgb must contain exactly 3 channels")
        normalized: list[int] = []
        for channel in value:
            try:
                channel_int = int(channel)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "estimated_rgb channels must be integers in [0, 255]"
                ) from exc
            if not 0 <= channel_int <= 255:
                raise ValueError(
                    "estimated_rgb channels must be integers in [0, 255]"
                )
            normalized.append(channel_int)
        return normalized


class MaterialRecipePreviewRequest(BaseModel):
    """Forward-simulate the predicted color of a stacked-material recipe.
    正向模拟选定耗材按顺序叠层的预测颜色。

    Each entry in ``directory_names`` is one print layer (bottom -> top relative
    to the substrate). The endpoint loads the corresponding Stage A parameters
    and runs a Beer-Lambert forward pass; no LUT is consulted. The recipe
    length is intentionally unconstrained beyond a sane upper bound so users
    can preview any layer count, not just the 5-layer presets the inverse
    solver requires.

    每个 ``directory_names`` 元素代表一层打印（从基底向外）。后端会加载对应
    Stage A 参数，使用 Beer-Lambert 正向模型求解叠层颜色；不依赖任何 LUT。
    层数上限设得宽松，以便用户预览任意层数。
    """

    directory_names: list[str] = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Saved material directory names, in stacking order from substrate "
            "(index 0) to outermost visible layer (index -1)."
        ),
    )
    layer_height_mm: float = Field(
        0.08,
        gt=0.0,
        le=1.0,
        description="Per-layer thickness in millimeters used by the forward model.",
    )
    substrate: str = Field(
        "white",
        description="Substrate identifier; only 'white' is supported in v1.",
    )

    @field_validator("directory_names")
    @classmethod
    def validate_directory_names(cls, value: list[str]) -> list[str]:
        cleaned = [name.strip() for name in value if isinstance(name, str) and name.strip()]
        if len(cleaned) != len(value) or not cleaned:
            raise ValueError("directory_names must contain non-empty strings")
        return cleaned

    @field_validator("substrate")
    @classmethod
    def validate_substrate(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in ("white", "black"):
            raise ValueError("substrate must be 'white' or 'black'")
        return cleaned


class MaterialRecipeSwatchItemRequest(BaseModel):
    """Single material-archive recipe for swatch generation.
    单个耗材档案配方，用于色块 3MF 生成。
    """

    directory_names: list[str] = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Material directory names in stacking order (substrate → top).",
    )
    result_hex: str = Field(..., description="Predicted blended hex color.")
    layer_height_mm: float = Field(0.08, gt=0.0, le=1.0, description="Layer height (mm).")
    substrate: str = Field("white", description="Substrate identifier.")


class MaterialRecipeSwatchRequest(BaseModel):
    """Batch request for generating a 3MF swatch file from material-archive recipes.
    耗材档案配方批量色块 3MF 生成请求。
    """

    recipes: list[MaterialRecipeSwatchItemRequest] = Field(
        ..., min_length=1, max_length=100, description="Recipe list."
    )
    block_size_mm: float = Field(15.0, ge=5.0, le=50.0, description="Block size (mm).")
    gap_mm: float = Field(2.0, ge=0.5, le=10.0, description="Grid gap (mm).")
    cols: int = Field(0, ge=0, le=20, description="Columns per row; 0 = auto.")
    structure_mode: str = Field("Single-sided", description="Single-sided / Double-sided.")
    printer_id: str = Field("bambu-h2d", description="Printer profile ID.")
    slicer: str = Field("BambuStudio", description="Slicer software ID.")
    custom_3mf_template_id: str | None = None
    nozzle_size: str = Field("0.4", description="Nozzle size.")
    device_profile_id: str | None = Field(None, description="Machine registry device profile ID.")
    build_plate_id: str | None = Field(None, description="Native slicer build plate ID.")


class MaterialRecipeSwatchResponse(BaseModel):
    """Response for material-archive swatch generation.
    耗材档案色块 3MF 生成响应。
    """

    status: str = Field(..., description="Status.")
    message: str = Field(..., description="Status message.")
    download_url: str = Field(..., description="3MF download URL.")
    preview_url: str | None = Field(None, description="Legend preview URL.")
    recipe_count: int = Field(..., description="Number of generated recipes.")


class MaterialLibraryBulkExportRequest(BaseModel):
    """Request model for exporting multiple saved material archives."""

    directory_names: list[str] = Field(
        ...,
        min_length=1,
        description="Saved material directory names to export as one ZIP archive.",
    )

    @field_validator("directory_names")
    @classmethod
    def validate_directory_names(cls, value: list[str]) -> list[str]:
        cleaned = [name.strip() for name in value if isinstance(name, str) and name.strip()]
        if len(cleaned) != len(value) or not cleaned:
            raise ValueError("directory_names must contain non-empty strings")
        return cleaned


class MaterialSyncRollbackRequest(BaseModel):
    """Request model for rolling a synced material back to an earlier revision."""

    material_id: str = Field(..., description="Stable material identity.")
    revision_id: str = Field(..., description="Revision to make current again.")

    @field_validator("material_id", "revision_id")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned


class MaterialRegistryInstallRequest(BaseModel):
    """Request model for installing one selected Registry package."""

    package_url: str = Field(..., description="Registry package URL from catalog.")
    package_sha256: str = Field(..., description="Expected ZIP SHA-256.")
    material_id: str = Field(..., description="Stable material identity.")
    revision_id: str = Field(..., description="Selected material revision.")
    account_id: str | None = Field(default=None, max_length=200)

    @field_validator("package_url", "package_sha256", "material_id", "revision_id")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned


class MaterialRegistryApproveRequest(BaseModel):
    """Request model for approving one Registry package into official channel."""

    official_password: str = Field(..., description="Server-side official approval password.")

    @field_validator("official_password")
    @classmethod
    def validate_official_password(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("official_password cannot be blank")
        return cleaned


class MaterialRegistryLocalUploadRequest(BaseModel):
    """Request model for uploading one local saved material into the Registry.
    将一个本地已保存耗材上传到 Registry 待审核队列的请求模型。
    """

    directory_name: str = Field(
        ...,
        description="Saved material directory name to export and upload.",
    )

    @field_validator("directory_name")
    @classmethod
    def validate_directory_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("directory_name cannot be blank")
        return cleaned
