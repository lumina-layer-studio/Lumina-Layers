"""Portable pixel ownership for whole-color edits across material changes."""

from __future__ import annotations

import base64
import zlib
from binascii import Error as Base64Error

import numpy as np

from core.edit_projection import EditProjectionGrid


def capture_color_scope(rgb: np.ndarray, color: tuple[int, int, int], solid: np.ndarray | None) -> dict[str, object]:
    """Capture ownership in bounded chunks, retaining only compressed packed bits."""
    pixels = np.asarray(rgb).reshape(-1, 3)
    solids = np.asarray(solid).reshape(-1) if solid is not None else None
    compressor = zlib.compressobj()
    parts: list[bytes] = []
    # A multiple of eight preserves the bit layout between chunks.
    for start in range(0, len(pixels), 65536):
        block = pixels[start:start + 65536]
        mask = np.all(block == color, axis=-1)
        if solids is not None:
            mask &= solids[start:start + 65536]
        parts.append(compressor.compress(np.packbits(mask).tobytes()))
    parts.append(compressor.flush())
    return {"shape": list(rgb.shape[:2]), "bits": base64.b64encode(b"".join(parts)).decode("ascii")}


def decode_color_scope(scope: dict[str, object], solid: np.ndarray) -> np.ndarray:
    """Restore saved ownership on the current grid using normal edit projection."""
    shape = scope.get("shape")
    if not isinstance(shape, list) or len(shape) != 2 or any(type(n) is not int or n <= 0 for n in shape):
        raise ValueError("Color edit scope has invalid dimensions")
    count = shape[0] * shape[1]
    try:
        packed = base64.b64decode(scope["bits"], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed, (count + 7) // 8 + 1)
        if len(raw) != (count + 7) // 8 or not decoder.eof or decoder.unused_data:
            raise ValueError("Color edit scope size does not match its dimensions")
        mask = np.unpackbits(np.frombuffer(raw, dtype=np.uint8), count=count).reshape(shape).astype(bool)
    except (KeyError, TypeError, zlib.error, Base64Error) as exc:
        raise ValueError("Color edit scope is damaged") from exc
    if tuple(shape) == solid.shape:
        mask &= solid
        return mask
    return EditProjectionGrid(tuple(shape), solid.shape, max_target_pixels=solid.size).project_mask(mask, target_solid=solid)
