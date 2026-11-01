from __future__ import annotations

import base64
import binascii
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

try:  # pragma: no cover - depends on optional runtime dependency
    from pillow_heif import register_heif_opener
except ImportError:  # pragma: no cover - optional dependency
    pass
else:  # pragma: no cover - registration side effect
    register_heif_opener()

try:
    import rawpy
except ImportError:  # pragma: no cover - depends on the local runtime
    rawpy = None

RAW_DECODE_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    RuntimeError,
)
if rawpy is not None and hasattr(rawpy, "LibRawError"):
    RAW_DECODE_ERRORS = RAW_DECODE_ERRORS + (rawpy.LibRawError,)

RAW_EXTENSIONS = {
    ".3fr",
    ".arw",
    ".cr2",
    ".cr3",
    ".dng",
    ".erf",
    ".kdc",
    ".mdc",
    ".mos",
    ".mrw",
    ".nef",
    ".nrw",
    ".orf",
    ".pef",
    ".raf",
    ".raw",
    ".rw2",
    ".rwl",
    ".sr2",
    ".srf",
    ".srw",
    ".x3f",
}
STANDARD_IMAGE_EXTENSIONS = {
    ".bmp",
    ".heic",
    ".heif",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
RAW_SHARPEN_SIGMA = 1.1
RAW_SHARPEN_AMOUNT = 0.32


def parse_data_url(data_url: str) -> tuple[str, bytes]:
    if "," not in data_url:
        raise ValueError("Invalid image payload.")
    header, encoded = data_url.split(",", 1)
    mime_type = "application/octet-stream"
    if header.startswith("data:"):
        mime_type = header[5:].split(";", 1)[0] or mime_type
    try:
        raw = base64.b64decode(encoded)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid image payload.") from exc
    return mime_type.lower(), raw


def decode_standard_image_bytes(raw: bytes) -> np.ndarray | None:
    if not raw:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as image:
            rgb = _pil_image_to_rgb_array(image)
    except (UnidentifiedImageError, OSError, ValueError):
        arr = np.frombuffer(raw, dtype=np.uint8)
        if arr.size == 0:
            return None
        try:
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except cv2.error:
            return None
    if rgb.size == 0:
        return None
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def apply_unsharp_mask(image: np.ndarray, sigma: float, amount: float) -> np.ndarray:
    blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=sigma, sigmaY=sigma)
    sharpened = cv2.addWeighted(image, 1.0 + amount, blurred, -amount, 0)
    if image.dtype == np.uint16:
        return np.clip(sharpened, 0, 65535).astype(np.uint16)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def looks_like_raw_input(mime_type: str, file_name: str) -> bool:
    mime_type = (mime_type or "").lower()
    suffix = Path(file_name).suffix.lower()
    if suffix in STANDARD_IMAGE_EXTENSIONS:
        return False
    if not suffix and mime_type == "application/octet-stream":
        return False
    return (
        suffix in RAW_EXTENSIONS
        or mime_type == "application/octet-stream"
        or mime_type.startswith("image/x-")
        or mime_type.endswith("/dng")
        or "raw" in mime_type
    )


def is_supported_archive_image(file_name: str) -> bool:
    suffix = Path(file_name).suffix.lower()
    return suffix in RAW_EXTENSIONS or suffix in STANDARD_IMAGE_EXTENSIONS


def decode_raw_image_bytes(raw: bytes, *, file_name: str = "") -> np.ndarray:
    if rawpy is None:
        raise ValueError(
            "当前环境未安装 rawpy，暂时无法解码 RAW 图片。请先执行 pip install -r requirements.txt。"
        )
    try:
        with rawpy.imread(io.BytesIO(raw)) as raw_image:
            return _postprocess_raw_image(raw_image)
    except RAW_DECODE_ERRORS as exc:
        raise ValueError(f"RAW 图片解码失败：{exc}") from exc


def decode_standard_image_file(path: str | Path) -> np.ndarray | None:
    if not str(path):
        return None
    try:
        with Image.open(path) as image:
            rgb = _pil_image_to_rgb_array(image)
    except (UnidentifiedImageError, OSError, ValueError):
        try:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        except cv2.error:
            return None
        if image is None or image.size == 0:
            return None
        return image
    if rgb.size == 0:
        return None
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _pil_image_to_rgb_array(image: Image.Image) -> np.ndarray:
    """Copy a PIL image to RGB ndarray while closing intermediate images."""
    transposed = ImageOps.exif_transpose(image)
    try:
        converted = transposed.convert("RGB")
        try:
            return np.array(converted, dtype=np.uint8, copy=True)
        finally:
            if converted is not transposed:
                converted.close()
    finally:
        if transposed is not image:
            transposed.close()


def decode_raw_image_file(path: str | Path, *, file_name: str = "") -> np.ndarray:
    if rawpy is None:
        raise ValueError(
            "当前环境未安装 rawpy，暂时无法解码 RAW 图片。请先执行 pip install -r requirements.txt。"
        )
    try:
        with rawpy.imread(str(path)) as raw_image:
            return _postprocess_raw_image(raw_image)
    except RAW_DECODE_ERRORS as exc:
        raise ValueError(f"RAW 图片解码失败：{exc}") from exc


def _postprocess_raw_image(raw_image: object) -> np.ndarray:
    postprocess_kwargs: dict[str, object] = {
        "use_camera_wb": True,
        "use_auto_wb": False,
        "no_auto_bright": True,
        "output_bps": 8,
    }
    color_space = getattr(getattr(rawpy, "ColorSpace", None), "sRGB", None)
    if color_space is not None:
        postprocess_kwargs["output_color"] = color_space
    demosaic_algorithm = getattr(getattr(rawpy, "DemosaicAlgorithm", None), "AHD", None)
    if demosaic_algorithm is not None:
        postprocess_kwargs["demosaic_algorithm"] = demosaic_algorithm
    rgb = raw_image.postprocess(**postprocess_kwargs)
    if rgb is None or rgb.size == 0:
        raise ValueError("RAW 图片解码失败。")
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return apply_unsharp_mask(bgr, sigma=RAW_SHARPEN_SIGMA, amount=RAW_SHARPEN_AMOUNT)


def decode_uploaded_bytes(
    raw: bytes,
    file_name: str = "",
    mime_type: str = "application/octet-stream",
) -> tuple[np.ndarray, str]:
    mime_type = (mime_type or "application/octet-stream").lower()
    raw_hint = looks_like_raw_input(mime_type, file_name)
    if raw_hint:
        return decode_raw_image_bytes(raw, file_name=file_name), "raw"
    image = decode_standard_image_bytes(raw)
    if image is not None:
        return image, "standard"
    if rawpy is not None:
        try:
            return decode_raw_image_bytes(raw, file_name=file_name), "raw"
        except ValueError:
            pass
    raise ValueError(
        "当前文件无法解码。支持常规图片，以及 DNG、NEF、CR2、CR3、ARW、RAF、ORF、RW2、PEF、SRW、RAW 等格式。"
    )


def decode_uploaded_file(
    path: str | Path,
    file_name: str = "",
    mime_type: str = "application/octet-stream",
) -> tuple[np.ndarray, str]:
    mime_type = (mime_type or "application/octet-stream").lower()
    detected_name = file_name or str(path)
    raw_hint = looks_like_raw_input(mime_type, detected_name)
    if raw_hint:
        return decode_raw_image_file(path, file_name=detected_name), "raw"
    image = decode_standard_image_file(path)
    if image is not None:
        return image, "standard"
    if rawpy is not None:
        try:
            return decode_raw_image_file(path, file_name=detected_name), "raw"
        except ValueError:
            pass
    raise ValueError(
        "当前文件无法解码。支持常规图片，以及 DNG、NEF、CR2、CR3、ARW、RAF、ORF、RW2、PEF、SRW、RAW 等格式。"
    )


def decode_uploaded_image(data_url: str, file_name: str = "") -> tuple[np.ndarray, str]:
    mime_type, raw = parse_data_url(data_url)
    return decode_uploaded_bytes(raw, file_name=file_name, mime_type=mime_type)


def decode_data_url(data_url: str) -> np.ndarray:
    _, raw = parse_data_url(data_url)
    image = decode_standard_image_bytes(raw)
    if image is None:
        raise ValueError("Failed to decode image payload.")
    return image


def image_to_uint8_display(image: np.ndarray) -> np.ndarray:
    """Return a uint8 BGR view suitable for browser display."""
    if image.dtype == np.uint16:
        return (image.astype(np.uint32) >> 8).astype(np.uint8)
    if image.dtype != np.uint8:
        return np.clip(image, 0, 255).astype(np.uint8)
    return image


def encode_png_bytes(image: np.ndarray) -> bytes:
    display = image_to_uint8_display(image)
    ok, buffer = cv2.imencode(".png", display)
    if not ok:
        raise ValueError("Failed to encode image.")
    return buffer.tobytes()


def write_png_file(path: str | Path, image: np.ndarray) -> None:
    """Encode without a filename so Windows paths use Python's Unicode I/O.

    Keep the caller's bit depth/channel order and write the encoder buffer
    directly, avoiding an additional full-size PNG bytes copy.
    """
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Failed to encode PNG image.")
    with Path(path).open("wb") as output:
        output.write(memoryview(buffer))


def encode_jpeg_bytes(image: np.ndarray, quality: int = 95) -> bytes:
    display = image_to_uint8_display(image)
    ok, buffer = cv2.imencode(".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("Failed to encode JPEG.")
    return buffer.tobytes()


def png_bytes_to_data_url(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def encode_png_data_url(image: np.ndarray) -> str:
    return png_bytes_to_data_url(encode_png_bytes(image))
