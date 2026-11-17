"""Shared dimensions for bounded screen previews."""

from __future__ import annotations

import config


def preview_dimensions(
    width: int, height: int, *, max_edge: int | None = None,
) -> tuple[int, int]:
    """Fit an image to the display budget while preserving its aspect ratio."""
    limit = int(config.IMAGE_PREVIEW_MAX_EDGE if max_edge is None else max_edge)
    if limit <= 0 or max(width, height) <= limit:
        return int(width), int(height)
    scale = limit / float(max(width, height))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))
