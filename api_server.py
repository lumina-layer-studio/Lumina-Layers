"""Lumina Studio API server and native geometry diagnostic entry point.

Lumina Studio API 服务与原生几何诊断入口。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _resolve_server_bind(env: Mapping[str, str]) -> tuple[str, int]:
    """Resolve and validate the API bind address.

    解析并校验 API 监听地址。

    Args:
        env: Environment mapping used by the server process.
            服务进程使用的环境变量映射。

    Returns:
        A validated ``(host, port)`` tuple. 经过校验的地址和端口。

    Raises:
        ValueError: If the host or port is unsafe or malformed.
            地址或端口不安全、格式错误时抛出。
    """

    host = env.get("LUMINA_API_HOST", "0.0.0.0")
    if host not in {"0.0.0.0", "127.0.0.1"}:
        raise ValueError("LUMINA_API_HOST must be a supported local bind")
    raw_port = env.get("LUMINA_API_PORT", "8000")
    if not re.fullmatch(r"[0-9]+", raw_port):
        raise ValueError("LUMINA_API_PORT must be an integer")
    port = int(raw_port)
    if port < 1024 or port > 65535:
        raise ValueError("LUMINA_API_PORT must be between 1024 and 65535")
    return host, port


def _run_server(env: Mapping[str, str]) -> None:
    """Load local environment settings and start the API.

    加载本地环境配置后启动 API。
    """

    import uvicorn

    # Import before resolving the bind so .env.local values take effect.
    from api.app import app

    bind_host, bind_port = _resolve_server_bind(env)
    uvicorn.run(app, host=bind_host, port=bind_port)


class NativeSvgSelfTestError(RuntimeError):
    """Stable failure raised when the required native path cannot run.

    必选原生 SVG 路径无法执行时使用的稳定失败类型。
    """

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class MaterialSamplingSelfTestError(RuntimeError):
    """Stable failure when packaged material sampling cannot run correctly.

    打包后的耗材采样无法正确执行时使用的稳定失败类型。
    """

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _geometry_wkb(geometry: Any) -> bytes:
    import shapely

    return bytes(
        shapely.to_wkb(
            geometry,
            byte_order=1,
            include_srid=False,
        )
    )


def _update_record_fingerprint(
    digest: Any,
    *,
    family: bytes,
    records: Sequence[dict[str, Any]],
    geometry_key: str,
) -> None:
    digest.update(family)
    digest.update(struct.pack("<Q", len(records)))
    for record in records:
        color = tuple(int(value) for value in record.get("color", ()))
        digest.update(struct.pack("<Q", len(color)))
        digest.update(bytes(color))
        digest.update(
            str(record.get("source_kind", "")).encode("utf-8")
        )
        digest.update(
            struct.pack("<q", int(record.get("draw_order", -1)))
        )
        digest.update(_geometry_wkb(record[geometry_key]))


def _native_svg_self_test_payload(svg_path: str) -> dict[str, Any]:
    from core.native_svg_adapter import (
        NativeSvgFallback,
        analyze_native_svg,
        native_build_identity,
    )
    import shapely

    result = analyze_native_svg(
        svg_path,
        target_width_mm=20.0,
        tolerance_mm=0.02,
        expand_stroke_to_fill=False,
    )
    if isinstance(result, NativeSvgFallback):
        raise NativeSvgSelfTestError(result.reason_code)
    if result.geometry_backend != "native":
        raise NativeSvgSelfTestError("non_native_backend")
    if not result.shape_data:
        raise NativeSvgSelfTestError("empty_raw_geometry")
    if not result.clipped_shapes:
        raise NativeSvgSelfTestError("empty_visible_geometry")
    if result.silhouette is None or result.silhouette.is_empty:
        raise NativeSvgSelfTestError("empty_silhouette")
    if result.svg_coordinate_domain is not None:
        import lumina_svg_core
        from core.svg_coordinate_domain import project_print_regions

        if not callable(getattr(lumina_svg_core, "canonicalize_grid_regions", None)):
            raise NativeSvgSelfTestError("native_grid_canonicalization_unavailable")
        if not callable(getattr(lumina_svg_core, "project_regions_to_grid", None)):
            raise NativeSvgSelfTestError("native_coordinate_projection_unavailable")
        probe = lumina_svg_core.canonicalize_grid_regions([[
            [(0, 0), (1, 0), (0, 1000), (0, 0)],
        ]])
        probe_area = sum(
            shapely.Polygon(shell, holes).area
            for shell, holes in probe[0]
        )
        if probe_area != 500.0:
            raise NativeSvgSelfTestError(
                "native_grid_canonicalization_lost_positive_area"
            )
        projected = project_print_regions(
            [item["geometry"] for item in result.clipped_shapes],
            mm_per_unit=result.scale_factor, grid_mm=0.0001,
        )
        if not all(geometry.is_valid for geometry in projected):
            raise NativeSvgSelfTestError("invalid_print_domain_geometry")

    silhouette_components = (
        len(result.silhouette.geoms)
        if result.silhouette.geom_type == "MultiPolygon"
        else 1
    )
    digest = hashlib.sha256()
    digest.update(b"lumina-native-svg-self-test-v1\0")
    digest.update(struct.pack("<d", float(result.scale_factor)))
    digest.update(struct.pack("<4d", *result.bbox))
    _update_record_fingerprint(
        digest,
        family=b"raw\0",
        records=result.shape_data,
        geometry_key="poly",
    )
    _update_record_fingerprint(
        digest,
        family=b"visible\0",
        records=result.clipped_shapes,
        geometry_key="geometry",
    )
    digest.update(b"silhouette\0")
    digest.update(_geometry_wkb(result.silhouette))

    return {
        "status": "ok",
        "geometry_backend": "native",
        "native_version": result.native_version,
        "native_schema_version": int(result.native_schema_version),
        "native_build_sha256": native_build_identity(),
        "native_extension_path": getattr(
            sys.modules.get("lumina_svg_core._lumina_svg_core"), "__file__", None
        ),
        "coordinate_contract_version": (
            result.svg_coordinate_domain.version
            if result.svg_coordinate_domain is not None else None
        ),
        "shapely_version": str(shapely.__version__),
        "geos_version": str(shapely.geos_version_string),
        "raw_geometry_count": len(result.shape_data),
        "visible_geometry_count": len(result.clipped_shapes),
        "silhouette_component_count": silhouette_components,
        "fingerprint_sha256": digest.hexdigest(),
    }


def _svg_hole_compensation_self_test_payload() -> dict[str, Any]:
    """Exercise native SVG compensation without a server or user material.
    无需启动服务或读取用户素材，验证原生 SVG 补偿功能。
    """
    from math import isclose

    from shapely.geometry import Polygon

    from core.svg_hole_compensation import compensate_svg_regions

    left = Polygon([
        (0, 0), (5, 0), (5, 4.8), (4.8, 4.8),
        (4.8, 5.2), (5, 5.2), (5, 10), (0, 10),
    ])
    right = Polygon([
        (5, 0), (10, 0), (10, 10), (5, 10),
        (5, 5.2), (5.2, 5.2), (5.2, 4.8), (5, 4.8),
    ])
    silhouette = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)],
        [[(4.8, 4.8), (4.8, 5.2), (5.2, 5.2), (5.2, 4.8)]],
    )
    regions = [
        {"geometry": left, "color": (255, 0, 0)},
        {"geometry": right, "color": (0, 0, 255)},
    ]
    result = compensate_svg_regions(
        regions, silhouette=silhouette, scale_factor=1.0,
        max_hole_area_mm2=0.5, max_hole_width_mm=0.0,
    )
    if (
        result.filled_holes != 1
        or len(result.regions) != 3
        or not result.silhouette.is_valid
        or not isclose(result.added_area_mm2, 0.16, abs_tol=1e-9)
        or not isclose(result.silhouette.area, 100.0, abs_tol=1e-9)
        or not all(a is b for a, b in zip(regions, result.regions))
    ):
        raise NativeSvgSelfTestError("compensation_contract_failed")
    return {
        "status": "ok", "input_regions": len(regions),
        "output_regions": len(result.regions), "filled_holes": result.filled_holes,
        "added_area_mm2": result.added_area_mm2,
    }


def _material_sampling_self_test_payload() -> dict[str, Any]:
    """Check installed SciPy data and real high-layer recipes without a server.
    无需启动服务，检查已安装的 SciPy 数据与真实高层配方生成。
    """
    from importlib import resources

    import numpy as np

    from core.material_candidate_sampling import (
        _sobol_points, _validate_sample_points, generate_candidate_recipes,
    )

    resource_present = resources.files("scipy.stats").joinpath(
        "_sobol_direction_numbers.npz"
    ).is_file()
    if not resource_present:
        raise MaterialSamplingSelfTestError("sobol_resource_missing")

    dimensions = 10
    sample_count = 1024
    points = _sobol_points(sample_count, dimensions, 7)
    try:
        points = _validate_sample_points(points, sample_count, dimensions)
    except ValueError as exc:
        raise MaterialSamplingSelfTestError("sobol_samples_invalid") from exc
    sobol_unique_points = int(np.unique(points, axis=0).shape[0])
    if sobol_unique_points != sample_count:
        raise MaterialSamplingSelfTestError("sobol_samples_invalid")

    candidate_budget = 4096
    recipes = generate_candidate_recipes(
        material_count=4, layer_count=dimensions,
        candidate_budget=candidate_budget, seed=7,
    ).recipes
    if (
        recipes.shape != (candidate_budget, dimensions)
        or recipes.dtype.kind not in "iu"
        or np.any(recipes < 0)
        or np.any(recipes >= 4)
        or np.unique(recipes, axis=0).shape[0] != candidate_budget
    ):
        raise MaterialSamplingSelfTestError("candidate_samples_invalid")
    return {
        "status": "ok", "resource_present": resource_present,
        "dimensions": dimensions, "sample_count": sample_count,
        "sobol_unique_points": sobol_unique_points,
        "candidate_budget": candidate_budget,
        "candidate_count": int(recipes.shape[0]),
    }


def _print_json(payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run a packaged-runtime diagnostic or start the API server.

    执行打包运行时自检，或启动 API 服务。

    Args:
        argv: Optional command-line arguments without the executable name.
            可选命令行参数，不含可执行文件名。

    Returns:
        Process exit code. 进程退出码。
    """

    parser = argparse.ArgumentParser(description="Run Lumina Studio backend.")
    parser.add_argument(
        "--check-dependencies", action="store_true",
        help="Check source runtime dependencies without starting the server.",
    )
    parser.add_argument(
        "--native-svg-self-test",
        metavar="SVG_PATH",
        help="Analyze one SVG through the required native Lumina adapter.",
    )
    parser.add_argument(
        "--svg-hole-compensation-self-test", action="store_true",
        help="Exercise native SVG hole compensation without starting a server.",
    )
    parser.add_argument(
        "--material-sampling-self-test", action="store_true",
        help="Check SciPy data and material sampling without starting a server.",
    )
    args = parser.parse_args(argv)
    if (
        args.native_svg_self_test or args.svg_hole_compensation_self_test
        or args.material_sampling_self_test
    ):
        from api.structured_logging import configure_structured_logging

        configure_structured_logging()
        try:
            if args.material_sampling_self_test:
                payload = _material_sampling_self_test_payload()
            elif args.svg_hole_compensation_self_test:
                payload = _svg_hole_compensation_self_test_payload()
            else:
                payload = _native_svg_self_test_payload(args.native_svg_self_test)
        except (NativeSvgSelfTestError, MaterialSamplingSelfTestError) as exc:
            _print_json(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "reason_code": exc.reason_code,
                }
            )
            return 1
        except Exception as exc:  # Boundary guard for diagnostic commands.
            _print_json(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "reason_code": (
                        "material_sampling_self_test_failed"
                        if args.material_sampling_self_test
                        else str(getattr(
                            exc, "reason_code", "native_self_test_failed",
                        ))
                    ),
                }
            )
            return 1
        _print_json(payload)
        return 0

    if not getattr(sys, "frozen", False):
        from scripts.source_dependencies import report_backend_dependencies

        if not report_backend_dependencies():
            return 1
    if args.check_dependencies:
        print(f"Backend dependencies OK. Python: {sys.executable}")
        return 0
    _run_server(os.environ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
