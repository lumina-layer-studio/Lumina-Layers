"""Reuse the last rendered browser mesh, keeping each session's output independent."""

from __future__ import annotations

import hashlib
import os
import pickle
import shutil
import tempfile
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import BinaryIO


def mesh_input_digest(*inputs: object) -> bytes:
    """Hash shape, dtype and contents, streaming contiguous NumPy buffers directly."""
    digest = hashlib.sha256()

    def update(buffer: pickle.PickleBuffer) -> None:
        raw = buffer.raw()
        digest.update(b"B" + raw.nbytes.to_bytes(8, "big"))
        digest.update(raw)

    for value in inputs:
        metadata = pickle.dumps(value, protocol=5, buffer_callback=update)
        digest.update(b"M" + len(metadata).to_bytes(8, "big"))
        digest.update(metadata)
    return digest.digest()


class RecentPreviewMesh:
    """One disk-backed slot. Equal concurrent builds share the owner's result."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._building: set[bytes] = set()
        self._key: bytes | None = None
        self._file: BinaryIO | None = None
        self._contours: bytes = b""

    def clear(self) -> None:
        with self._condition:
            self._key = None
            self._contours = b""
            if self._file is not None:
                with suppress(OSError):
                    self._file.close()
                self._file = None

    def render(
        self, key: bytes, cache: dict, output_path: str,
        build: Callable[[], str | None],
    ) -> str | None:
        with self._condition:
            self._condition.wait_for(lambda: key not in self._building)
            if self._key == key and self._file is not None:
                try:
                    self._file.seek(0)
                    with open(output_path, "wb") as output:
                        shutil.copyfileobj(self._file, output, 1024 * 1024)
                    cache["color_contours"] = pickle.loads(self._contours)
                    cache["_glb_reused"] = True
                    return output_path
                except OSError:
                    self.clear()
                    with suppress(OSError):
                        os.remove(output_path)
            self._building.add(key)
        try:
            path = build()
            if path:
                self._remember(key, path, cache)
            return path
        finally:
            with self._condition:
                self._building.remove(key)
                self._condition.notify_all()

    def _remember(self, key: bytes, path: str, cache: dict) -> None:
        with self._condition:
            try:
                with open(path, "rb") as source:
                    contours = pickle.dumps(cache.get("color_contours"), protocol=5)
                    self._key = None
                    if self._file is None:
                        self._file = tempfile.TemporaryFile()
                    self._file.seek(0)
                    shutil.copyfileobj(source, self._file, 1024 * 1024)
                    self._file.truncate()
                self._contours = contours
                self._key = key
            except OSError:
                # The freshly rendered session file remains usable on its own.
                self.clear()
