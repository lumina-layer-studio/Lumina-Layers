import io
import os
import tempfile
from typing import Optional

import numpy as np
from fastapi import UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image


async def upload_to_ndarray(file: UploadFile) -> np.ndarray:
    """将 UploadFile 图像转换为 RGB NumPy ndarray。

    Args:
        file: FastAPI UploadFile 对象

    Returns:
        np.ndarray: shape (H, W, 3), dtype uint8, RGB 格式

    Raises:
        ValueError: 文件格式无效或无法解码
    """
    contents = await file.read()
    try:
        img = Image.open(io.BytesIO(contents))
        if img.mode != "RGB":
            img = img.convert("RGB")
        return np.array(img, dtype=np.uint8)
    except Exception as e:
        raise ValueError(f"无法解码图像文件: {e}")


async def upload_to_tempfile(
    file: UploadFile, suffix: Optional[str] = None
) -> str:
    """将 UploadFile 保存为临时文件，返回路径。

    Args:
        file: FastAPI UploadFile 对象
        suffix: 文件后缀（如 ".png"、".svg"）

    Returns:
        str: 临时文件绝对路径
    """
    if suffix is None:
        suffix = os.path.splitext(file.filename or "")[1] or ".tmp"
    contents = await file.read()
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        os.write(fd, contents)
    finally:
        os.close(fd)
    return path


def pil_to_png_bytes(img: Image.Image) -> bytes:
    """将 PIL Image 编码为 PNG 字节流。"""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ndarray_to_png_bytes(arr: np.ndarray) -> bytes:
    """将 NumPy ndarray 编码为 PNG 字节流。"""
    img = Image.fromarray(arr)
    return pil_to_png_bytes(img)


def pil_to_streaming_response(img: Image.Image, fmt: str = "PNG") -> StreamingResponse:
    """将 PIL Image 编码为 StreamingResponse。"""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    media_type = "image/png" if fmt.upper() == "PNG" else f"image/{fmt.lower()}"
    return StreamingResponse(buf, media_type=media_type)


def file_to_response(path: str, filename: Optional[str] = None) -> FileResponse:
    """将文件路径包装为 FileResponse。"""
    if filename is None:
        filename = os.path.basename(path)
    media_type = _guess_media_type(path)
    return FileResponse(path=path, filename=filename, media_type=media_type)


def _guess_media_type(path: str) -> str:
    """根据文件扩展名推断 MIME 类型。"""
    ext = os.path.splitext(path)[1].lower()
    return {
        ".3mf": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
        ".glb": "model/gltf-binary",
        ".zip": "application/zip",
        ".npy": "application/octet-stream",
        ".npz": "application/octet-stream",
        ".png": "image/png",
        ".jpg": "image/jpeg",
    }.get(ext, "application/octet-stream")
