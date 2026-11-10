"""Lumina Studio API — Router re-exports.
Lumina Studio API — 路由模块的统一导出。

This package re-exports all domain routers so that consumers
can import directly from ``api.routers`` instead of reaching into
individual domain modules.
本包统一导出所有领域 Router，使用方可直接从 ``api.routers``
导入，无需深入各领域子模块。
"""

from api.routers.calibration import router as calibration_router
from api.routers.converter import router as converter_router
from api.routers.extractor import router as extractor_router
from api.routers.feedback import router as feedback_router
from api.routers.five_color import router as five_color_router
from api.routers.health import router as health_router
from api.routers.lut import router as lut_router
from api.routers.lut_registry import router as lut_registry_router
from api.routers.material_registry import router as material_registry_router
from api.routers.material_sync import router as material_sync_router
from api.routers.session import router as session_router
from api.routers.slicer import router as slicer_router
from api.routers.single_stage import router as single_stage_router
from api.routers.system import router as system_router
from api.routers.vectorizer import router as vectorizer_router
from api.routers.workshop import router as workshop_router
from api.routers.workshop_backend import router as workshop_backend_router

__all__ = [
    "converter_router",
    "extractor_router",
    "feedback_router",
    "calibration_router",
    "five_color_router",
    "health_router",
    "lut_router",
    "lut_registry_router",
    "material_registry_router",
    "material_sync_router",
    "session_router",
    "slicer_router",
    "single_stage_router",
    "system_router",
    "vectorizer_router",
    "workshop_router",
    "workshop_backend_router",
]
