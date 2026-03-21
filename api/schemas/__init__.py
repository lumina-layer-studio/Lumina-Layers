"""Lumina Studio API — Pydantic schemas and enums re-exports.
Lumina Studio API — Pydantic 数据模型与枚举的统一导出。

This package re-exports all domain schemas and enums so that consumers
can import directly from ``api.schemas`` instead of reaching into
individual domain modules.
本包统一导出所有领域 Schema 和枚举，使用方可直接从 ``api.schemas``
导入，无需深入各领域子模块。
"""

from api.schemas.five_color import (
    BaseColorEntry,
    BaseColorsResponse,
    FiveColorQueryRequest,
    FiveColorQueryResponse,
)
from api.schemas.calibration import BackingColor, CalibrationGenerateRequest
from api.schemas.converter import (
    AutoHeightMode,
    ColorMergePreviewRequest,
    ColorMode,
    ColorReplaceRequest,
    ColorReplacementItem,
    ConvertBatchRequest,
    ConvertGenerateRequest,
    ConvertPreviewRequest,
    ModelingMode,
    StructureMode,
)
from api.schemas.extractor import (
    CalibrationColorMode,
    ExtractorExtractRequest,
    ExtractorManualFixRequest,
    ExtractorPage,
)
from api.schemas.lut import (
    LutInfoResponse,
    MergeRequest,
    MergeResponse,
    MergeStats,
)
from api.schemas.system import (
    CacheCleanupDetails,
    ClearCacheResponse,
    ClearCacheResult,
)
from api.schemas.slicer import (
    SlicerDetectResponse,
    SlicerInfo,
    SlicerLaunchRequest,
    SlicerLaunchResponse,
)
from api.schemas.responses import (
    BatchItemResult,
    BatchResponse,
    CalibrationResponse,
    ColorReplaceResponse,
    ExtractResponse,
    GenerateResponse,
    HealthResponse,
    LUTListResponse,
    ManualFixResponse,
    MergePreviewResponse,
    PreviewResponse,
)

__all__ = [
    # --- Converter enums ---
    "ColorMode",
    "ModelingMode",
    "StructureMode",
    "AutoHeightMode",
    # --- Converter models ---
    "ColorReplacementItem",
    "ConvertPreviewRequest",
    "ConvertGenerateRequest",
    "ConvertBatchRequest",
    "ColorReplaceRequest",
    "ColorMergePreviewRequest",
    # --- Extractor enums ---
    "CalibrationColorMode",
    "ExtractorPage",
    # --- Extractor models ---
    "ExtractorExtractRequest",
    "ExtractorManualFixRequest",
    # --- Calibration enums ---
    "BackingColor",
    # --- Calibration models ---
    "CalibrationGenerateRequest",
    # --- LUT Manager models ---
    "MergeRequest",
    "MergeResponse",
    "MergeStats",
    "LutInfoResponse",
    # --- Slicer models ---
    "SlicerInfo",
    "SlicerDetectResponse",
    "SlicerLaunchRequest",
    "SlicerLaunchResponse",
    # --- System models ---
    "CacheCleanupDetails",
    "ClearCacheResponse",
    "ClearCacheResult",
    # --- Five-Color models ---
    "BaseColorEntry",
    "BaseColorsResponse",
    "FiveColorQueryRequest",
    "FiveColorQueryResponse",
    # --- Response models ---
    "CalibrationResponse",
    "PreviewResponse",
    "ColorReplaceResponse",
    "MergePreviewResponse",
    "GenerateResponse",
    "BatchItemResult",
    "BatchResponse",
    "LUTListResponse",
    "HealthResponse",
    "ExtractResponse",
    "ManualFixResponse",
]
