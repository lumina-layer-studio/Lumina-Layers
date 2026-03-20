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
from api.routers.five_color import router as five_color_router
from api.routers.health import router as health_router
from api.routers.lut import router as lut_router
from api.routers.slicer import router as slicer_router
from api.routers.system import router as system_router

__all__ = [
    "converter_router",
    "extractor_router",
    "calibration_router",
    "five_color_router",
    "health_router",
    "lut_router",
    "slicer_router",
    "system_router",
]
