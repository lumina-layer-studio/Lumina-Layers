"""LUT details aggregation service.
LUT 详情聚合服务。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from config import get_capabilities, get_schema_version, get_supported_modes
from core.lut_details.aliases import AliasResolver
from core.lut_details.catalog import (
    LutCatalogIndexer,
    LutDetailsCatalog,
    ResolvedLutIdentity,
)
from core.lut_details.parser import LutParser, ParsedLut


@dataclass(frozen=True)
class AxisRange:
    """Axis min/max pair for coverage stats.
    覆盖统计的坐标轴最小/最大值。
    """

    min: float
    max: float


@dataclass(frozen=True)
class LutCoverageStats:
    """Coverage statistics for one LUT.
    单个 LUT 的覆盖统计。
    """

    entry_count: int
    plotted_point_count: int
    l_range: AxisRange
    a_range: AxisRange
    b_range: AxisRange
    r_range: AxisRange
    g_range: AxisRange
    b_rgb_range: AxisRange


@dataclass(frozen=True)
class LutPlotPoint:
    """Plot point for Lab or RGB charts.
    Lab 或 RGB 图的散点。
    """

    x: float
    y: float
    hex_color: str
    rgb: tuple[int, int, int]
    label: str


@dataclass(frozen=True)
class LutPlotPoint3D:
    """3D plot point for Lab charts.
    Lab 图的 3D 散点。
    """

    l: float
    a: float
    b: float
    hex_color: str
    rgb: tuple[int, int, int]
    label: str


@dataclass(frozen=True)
class LutDetails:
    """Aggregated details payload for one LUT.
    单个 LUT 的聚合详情载荷。
    """

    name: str
    path: str
    manufacturer: str
    manufacturer_source: str
    material_type: str
    material_source: str
    color_mode: str
    color_count: int
    source_kind: str
    schema_version: str
    capabilities: tuple[str, ...]
    supported_modes: tuple[dict[str, Any], ...]
    raw_metadata: dict[str, Any]
    palette: tuple[dict[str, Any], ...]
    coverage_stats: LutCoverageStats
    lab_points: tuple[LutPlotPoint, ...]
    lab_points_3d: tuple[LutPlotPoint3D, ...]
    lab_hull: tuple[tuple[float, float], ...]
    rgb_points: tuple[LutPlotPoint, ...]
    max_color_layers: int
    layer_height_mm: float
    line_width_mm: float
    base_layers: int
    base_channel_idx: int
    layer_order: str


class LutDetailService:
    """Build LUT details catalog and details payloads.
    构建 LUT 详情目录和详情载荷。

    Args:
        preset_dir: Root preset directory. (预设根目录)
        alias_resolver: Alias resolver. (别名解析器)
        parser: LUT parser. (LUT 解析器)
        indexer: Catalog indexer. (目录索引器)
    """

    def __init__(
        self,
        *,
        preset_dir: Path,
        alias_resolver: AliasResolver,
        parser: LutParser,
        indexer: LutCatalogIndexer,
    ) -> None:
        self._preset_dir = Path(preset_dir)
        self._alias_resolver = alias_resolver
        self._parser = parser
        self._indexer = indexer

    def get_catalog(self) -> LutDetailsCatalog:
        """Return the grouped LUT details catalog.
        返回分组后的 LUT 详情目录。
        """

        return self._indexer.build_catalog()

    def get_lut_details(self, lut_name: str) -> LutDetails:
        """Return detailed metadata and visualization data for one LUT.
        返回单个 LUT 的详细元数据和可视化数据。

        Args:
            lut_name: Details catalog display name. (详情目录显示名称)

        Returns:
            LutDetails: Aggregated details. (聚合详情)

        Raises:
            KeyError: If the LUT cannot be found. (未找到 LUT 时抛出)
        """

        path = self._indexer.find_path_by_name(lut_name)
        if path is None:
            raise KeyError(lut_name)
        return self.get_lut_details_from_path(lut_name, path)

    def get_lut_details_from_path(self, lut_name: str, path: Path) -> LutDetails:
        """Build details for a validated project-local source using the same parser."""
        parsed = self._parser.parse(name=lut_name, path=path)
        identity = self._indexer.resolve_identity(path, parsed)
        return self._build_details(parsed, identity)

    def _build_details(self, parsed: ParsedLut, identity: ResolvedLutIdentity) -> LutDetails:
        rgb = parsed.rgb
        lab = parsed.lab
        palette = tuple(
            {
                "color": entry.color,
                "material": entry.material,
                "hex_color": entry.hex_color,
                "color_name": entry.color_name,
            }
            for entry in parsed.metadata.palette
        )
        coverage_stats = self._build_coverage_stats(rgb, lab)
        lab_points = tuple(
            LutPlotPoint(
                x=round(float(point[1]), 6),
                y=round(float(point[2]), 6),
                hex_color=self._rgb_to_hex(color),
                rgb=(int(color[0]), int(color[1]), int(color[2])),
                label=f"{index + 1}",
            )
            for index, (point, color) in enumerate(zip(lab, rgb, strict=False))
        )
        lab_points_3d = tuple(
            LutPlotPoint3D(
                l=round(float(point[0]), 6),
                a=round(float(point[1]), 6),
                b=round(float(point[2]), 6),
                hex_color=self._rgb_to_hex(color),
                rgb=(int(color[0]), int(color[1]), int(color[2])),
                label=f"{index + 1}",
            )
            for index, (point, color) in enumerate(zip(lab, rgb, strict=False))
        )
        rgb_points = tuple(
            LutPlotPoint(
                x=round(float(projected[0]), 6),
                y=round(float(projected[1]), 6),
                hex_color=self._rgb_to_hex(color),
                rgb=(int(color[0]), int(color[1]), int(color[2])),
                label=f"{index + 1}",
            )
            for index, (color, projected) in enumerate(zip(rgb, self._project_rgb_points(rgb), strict=False))
        )
        return LutDetails(
            name=parsed.name,
            path=str(parsed.path),
            manufacturer=identity.manufacturer,
            manufacturer_source=identity.manufacturer_source,
            material_type=identity.material_type,
            material_source=identity.material_source,
            color_mode=parsed.color_mode,
            color_count=parsed.color_count,
            source_kind=parsed.source_kind,
            schema_version=get_schema_version(parsed.metadata),
            capabilities=tuple(get_capabilities(parsed.metadata)),
            supported_modes=tuple(get_supported_modes(parsed.metadata)),
            raw_metadata=parsed.raw_metadata,
            palette=palette,
            coverage_stats=coverage_stats,
            lab_points=lab_points,
            lab_points_3d=lab_points_3d,
            lab_hull=self._compute_lab_hull(lab),
            rgb_points=rgb_points,
            max_color_layers=parsed.metadata.max_color_layers,
            layer_height_mm=parsed.metadata.layer_height_mm,
            line_width_mm=parsed.metadata.line_width_mm,
            base_layers=parsed.metadata.base_layers,
            base_channel_idx=parsed.metadata.base_channel_idx,
            layer_order=parsed.metadata.layer_order,
        )

    def _build_coverage_stats(self, rgb: np.ndarray, lab: np.ndarray) -> LutCoverageStats:
        rgb_values = rgb.astype(np.float32) if rgb.size else np.zeros((0, 3), dtype=np.float32)
        lab_values = lab.astype(np.float32) if lab.size else np.zeros((0, 3), dtype=np.float32)
        return LutCoverageStats(
            entry_count=int(max(rgb.shape[0], lab.shape[0])),
            plotted_point_count=int(min(rgb.shape[0], lab.shape[0]) if rgb.size and lab.size else max(rgb.shape[0], lab.shape[0])),
            l_range=self._axis_range(lab_values[:, 0] if lab_values.size else np.asarray([], dtype=np.float32)),
            a_range=self._axis_range(lab_values[:, 1] if lab_values.size else np.asarray([], dtype=np.float32)),
            b_range=self._axis_range(lab_values[:, 2] if lab_values.size else np.asarray([], dtype=np.float32)),
            r_range=self._axis_range(rgb_values[:, 0] if rgb_values.size else np.asarray([], dtype=np.float32)),
            g_range=self._axis_range(rgb_values[:, 1] if rgb_values.size else np.asarray([], dtype=np.float32)),
            b_rgb_range=self._axis_range(rgb_values[:, 2] if rgb_values.size else np.asarray([], dtype=np.float32)),
        )

    @staticmethod
    def _axis_range(values: np.ndarray) -> AxisRange:
        if values.size == 0:
            return AxisRange(min=0.0, max=0.0)
        return AxisRange(min=round(float(np.min(values)), 6), max=round(float(np.max(values)), 6))

    @staticmethod
    def _project_rgb_points(rgb: np.ndarray) -> np.ndarray:
        if rgb.size == 0:
            return np.zeros((0, 2), dtype=np.float32)
        rgb_norm = rgb.astype(np.float32) / 255.0
        x = (rgb_norm[:, 0] - rgb_norm[:, 2]) * 0.8660254
        y = rgb_norm[:, 1] - (rgb_norm[:, 0] + rgb_norm[:, 2]) * 0.5
        return np.stack([x, y], axis=1)

    @staticmethod
    def _compute_lab_hull(lab: np.ndarray) -> tuple[tuple[float, float], ...]:
        if lab.size == 0:
            return ()
        points = np.unique(np.round(lab[:, 1:3].astype(np.float64), 6), axis=0)
        if points.shape[0] < 3:
            return ()
        sorted_points = sorted((float(point[0]), float(point[1])) for point in points.tolist())

        def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        lower: list[tuple[float, float]] = []
        for point in sorted_points:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
                lower.pop()
            lower.append(point)

        upper: list[tuple[float, float]] = []
        for point in reversed(sorted_points):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
                upper.pop()
            upper.append(point)

        hull = lower[:-1] + upper[:-1]
        return tuple((round(point[0], 6), round(point[1], 6)) for point in hull)

    @staticmethod
    def _rgb_to_hex(color: np.ndarray) -> str:
        return "#{:02X}{:02X}{:02X}".format(int(color[0]), int(color[1]), int(color[2]))


@lru_cache(maxsize=4)
def get_lut_details_service(
    *,
    preset_dir: Path | None = None,
    alias_config_path: Path | None = None,
) -> LutDetailService:
    """Return a cached LUT details service instance.
    返回缓存的 LUT 详情服务实例。
    """

    from utils.lut_manager import LUTManager

    resolved_preset_dir = Path(preset_dir or LUTManager.LUT_PRESET_DIR).resolve()
    resolved_alias_path = Path(alias_config_path or (Path(__file__).resolve().parents[2] / "assets" / "lut_details_aliases.json")).resolve()
    alias_resolver = AliasResolver.from_file(resolved_alias_path)
    parser = LutParser()
    additional_roots: tuple[tuple[str, Path], ...] = ()
    if preset_dir is None:
        additional_roots = (
            ("Custom", LUTManager.custom_lut_dir()),
            ("Cloud", LUTManager.cloud_lut_dir()),
        )
    indexer = LutCatalogIndexer(
        preset_dir=resolved_preset_dir,
        alias_resolver=alias_resolver,
        parser=parser,
        additional_roots=additional_roots,
    )
    return LutDetailService(
        preset_dir=resolved_preset_dir,
        alias_resolver=alias_resolver,
        parser=parser,
        indexer=indexer,
    )
