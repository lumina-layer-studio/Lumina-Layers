from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

import cv2
import numpy as np

from .calibration_core import EXPOSURE_ANCHOR_TARGET_SRGB
from .image_io import decode_uploaded_bytes, encode_png_bytes, png_bytes_to_data_url
from .image_io import looks_like_raw_input, write_png_file
from .pipeline import (
    DEFAULT_PREVIEW_HEIGHT,
    DEFAULT_PREVIEW_WIDTH,
    calibrate_image_bgr,
    generate_patch_points,
)
from .reference import resolve_reference
from .strict_pipeline import calibrate_strict_raw

PointInput = Mapping[str, float] | Sequence[float]
ImageInput = str | bytes | bytearray | Path | np.ndarray


@dataclass(frozen=True)
class CalibrationResult:
    calibrated_image: np.ndarray
    preview_image: np.ndarray
    preview_overlay_image: np.ndarray
    calibrated_png: bytes | None
    preview_png: bytes
    preview_overlay_png: bytes
    report: dict[str, Any]
    ccm: np.ndarray
    corners: list[dict[str, float]]
    patch_points: list[dict[str, float]]
    source_type: str

    @property
    def calibrated_image_data_url(self) -> str:
        if self.calibrated_png is None:
            raise ValueError("Calibrated PNG bytes were not generated.")
        return png_bytes_to_data_url(self.calibrated_png)

    @property
    def preview_image_data_url(self) -> str:
        return png_bytes_to_data_url(self.preview_png)

    @property
    def preview_overlay_image_data_url(self) -> str:
        return png_bytes_to_data_url(self.preview_overlay_png)

    def save(self, output_dir: str | Path, prefix: str = "colorchecker") -> dict[str, Path]:
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        paths = {
            "calibrated": target / f"{prefix}_calibrated.png",
            "preview": target / f"{prefix}_preview.png",
            "preview_overlay": target / f"{prefix}_preview_overlay.png",
        }
        if self.calibrated_png is None:
            write_png_file(paths["calibrated"], self.calibrated_image)
        else:
            paths["calibrated"].write_bytes(self.calibrated_png)
        paths["preview"].write_bytes(self.preview_png)
        paths["preview_overlay"].write_bytes(self.preview_overlay_png)
        return paths


def calibrate(
    image: ImageInput,
    corners: Sequence[PointInput],
    patch_points: Sequence[PointInput] | None = None,
    *,
    file_name: str = "",
    mime_type: str = "application/octet-stream",
    input_color: Literal["bgr", "rgb"] = "bgr",
    preview_width: int = DEFAULT_PREVIEW_WIDTH,
    preview_height: int = DEFAULT_PREVIEW_HEIGHT,
    sample_radius: int = 12,
    method: Literal["mean", "median"] = "mean",
    calibration_mode: Literal["matrix_3x3", "matrix_3x4", "root_polynomial", "auto"] = "matrix_3x3",
    gray_affine_mode: Literal["auto", "enabled", "fallback"] = "auto",
    sampling_filter: object | None = None,
    blur_radius: float = 0.0,
    brand: str | None = None,
    reference_id: str | None = None,
    reference_patches: Sequence[Mapping[str, object]] | None = None,
    reference_source: Mapping[str, object] | None = None,
    patch_layout: Literal["4x6", "3x8"] = "4x6",
    auto_arrange: bool = True,
    exposure_anchor_target_srgb: int = EXPOSURE_ANCHOR_TARGET_SRGB,
    encode_calibrated_png: bool = True,
) -> CalibrationResult:
    if method not in {"mean", "median"}:
        raise ValueError("method must be 'mean' or 'median'.")
    if input_color not in {"bgr", "rgb"}:
        raise ValueError("input_color must be 'bgr' or 'rgb'.")

    raw_payload = _raw_input_payload(image, file_name=file_name, mime_type=mime_type)
    brand_data = resolve_reference(
        reference_id=reference_id or brand,
        reference_patches=reference_patches,
        reference_source=reference_source,
        exposure_anchor_target_srgb=exposure_anchor_target_srgb,
    )
    reference_patches = brand_data["patches"]
    reference_color_map = brand_data["color_map"]
    reference_source = _brand_reference_source(brand_data)
    normalized_corners = _normalize_points(corners, expected_count=4, name="corners")
    if patch_points is None:
        if not auto_arrange:
            raise ValueError("patch_points is required when auto_arrange is False.")
        normalized_patch_points = generate_patch_points(
            int(preview_width),
            int(preview_height),
            patch_layout=patch_layout,
            patch_count=len(reference_patches),
        )
    else:
        normalized_patch_points = _normalize_points(
            patch_points,
            expected_count=len(reference_patches),
            name="patch_points",
        )

    if raw_payload is not None:
        raw_bytes, raw_file_name = raw_payload
        calibration = calibrate_strict_raw(
            raw_bytes,
            file_name=raw_file_name,
            corners=normalized_corners,
            patch_points=normalized_patch_points,
            reference_patches=reference_patches,
            reference_source=reference_source,
            preview_width=int(preview_width),
            preview_height=int(preview_height),
            sample_radius=int(sample_radius),
            sampling_filter=sampling_filter,
            calibration_mode=calibration_mode,
            gray_affine_mode=gray_affine_mode,
            blur_radius=float(blur_radius),
            target_white_point="D50",
        )
        calibrated_png = (
            encode_png_bytes(calibration.calibrated_image)
            if encode_calibrated_png
            else None
        )
        preview_png = encode_png_bytes(calibration.preview_image)
        overlay_png = encode_png_bytes(calibration.preview_overlay_image)
        calibration.report.setdefault("reference_source", reference_source)
        return CalibrationResult(
            calibrated_image=calibration.calibrated_image,
            preview_image=calibration.preview_image,
            preview_overlay_image=calibration.preview_overlay_image,
            calibrated_png=calibrated_png,
            preview_png=preview_png,
            preview_overlay_png=overlay_png,
            report=calibration.report,
            ccm=_model_coefficients_array(calibration.model),
            corners=normalized_corners,
            patch_points=normalized_patch_points,
            source_type="raw",
        )

    image_bgr, source_type = _load_image(image, file_name=file_name, mime_type=mime_type, input_color=input_color)
    calibration = calibrate_image_bgr(
        image_bgr,
        normalized_corners,
        normalized_patch_points,
        reference_patches,
        reference_color_map,
        preview_width=int(preview_width),
        preview_height=int(preview_height),
        sample_radius=int(sample_radius),
        method=method,
        calibration_mode=calibration_mode,
        gray_affine_mode=gray_affine_mode,
        sampling_filter=sampling_filter,
        blur_radius=float(blur_radius),
    )
    calibrated_png = (
        encode_png_bytes(calibration.calibrated_image)
        if encode_calibrated_png
        else None
    )
    preview_png = encode_png_bytes(calibration.preview_image)
    overlay_png = encode_png_bytes(calibration.preview_overlay_image)
    calibration.report.setdefault("reference_source", reference_source)
    return CalibrationResult(
        calibrated_image=calibration.calibrated_image,
        preview_image=calibration.preview_image,
        preview_overlay_image=calibration.preview_overlay_image,
        calibrated_png=calibrated_png,
        preview_png=preview_png,
        preview_overlay_png=overlay_png,
        report=calibration.report,
        ccm=calibration.ccm,
        corners=normalized_corners,
        patch_points=normalized_patch_points,
        source_type=source_type,
    )


def _raw_input_payload(
    image: ImageInput,
    *,
    file_name: str,
    mime_type: str,
) -> tuple[bytes, str] | None:
    if isinstance(image, np.ndarray):
        return None
    if isinstance(image, (bytes, bytearray)):
        detected_file_name = file_name
        detected_mime_type = mime_type
        if detected_mime_type == "application/octet-stream" and detected_file_name:
            detected_mime_type = mimetypes.guess_type(detected_file_name)[0] or detected_mime_type
        if looks_like_raw_input(detected_mime_type, detected_file_name):
            return bytes(image), detected_file_name
        return None

    path = Path(image)
    detected_file_name = file_name or path.name
    detected_mime_type = mime_type
    if detected_mime_type == "application/octet-stream":
        detected_mime_type = mimetypes.guess_type(detected_file_name)[0] or detected_mime_type
    if not looks_like_raw_input(detected_mime_type, detected_file_name):
        return None
    return path.read_bytes(), detected_file_name


def _brand_reference_source(brand_data: dict[str, Any]) -> dict[str, object]:
    source = brand_data.get("reference_source")
    if isinstance(source, dict):
        return source
    return {
        "source_type": "built_in",
        "source_name": brand_data.get("name"),
        "serial_number": None,
        "patch_count": len(brand_data.get("patches") or []),
        "lab_white_point": "D50",
    }


def _model_coefficients_array(model: Mapping[str, object]) -> np.ndarray:
    coefficients = model.get("coefficients")
    if coefficients is None:
        return np.empty((0, 3), dtype=np.float32)
    return np.asarray(coefficients, dtype=np.float32)


def _load_image(
    image: ImageInput,
    *,
    file_name: str,
    mime_type: str,
    input_color: Literal["bgr", "rgb"],
) -> tuple[np.ndarray, str]:
    if isinstance(image, np.ndarray):
        image_array = image.copy()
        if image_array.ndim != 3 or image_array.shape[2] < 3:
            raise ValueError("image ndarray must have shape HxWx3 or HxWx4.")
        if image_array.shape[2] == 4:
            image_array = cv2.cvtColor(image_array, cv2.COLOR_RGBA2RGB if input_color == "rgb" else cv2.COLOR_BGRA2BGR)
        if input_color == "rgb":
            image_array = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
        return image_array, "ndarray"

    if isinstance(image, (bytes, bytearray)):
        detected_mime_type = mime_type
        if detected_mime_type == "application/octet-stream" and file_name:
            detected_mime_type = mimetypes.guess_type(file_name)[0] or detected_mime_type
        return decode_uploaded_bytes(bytes(image), file_name=file_name, mime_type=detected_mime_type)

    path = Path(image)
    raw = path.read_bytes()
    detected_file_name = file_name or path.name
    detected_mime_type = mime_type
    if detected_mime_type == "application/octet-stream":
        detected_mime_type = mimetypes.guess_type(detected_file_name)[0] or detected_mime_type
    return decode_uploaded_bytes(raw, file_name=detected_file_name, mime_type=detected_mime_type)


def _normalize_points(
    points: Sequence[PointInput],
    *,
    expected_count: int,
    name: str,
) -> list[dict[str, float]]:
    normalized: list[dict[str, float]] = []
    for point in points:
        if isinstance(point, Mapping):
            if "x" not in point or "y" not in point:
                raise ValueError(f"{name} item must contain x and y.")
            normalized.append({"x": float(point["x"]), "y": float(point["y"])})
        else:
            if len(point) < 2:
                raise ValueError(f"{name} item must contain at least 2 values.")
            normalized.append({"x": float(point[0]), "y": float(point[1])})
    if len(normalized) != expected_count:
        raise ValueError(f"{name} must contain exactly {expected_count} points.")
    return normalized
