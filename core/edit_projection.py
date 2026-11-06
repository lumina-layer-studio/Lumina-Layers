"""Normalized-grid projection for replaying preview-time spatial edits.

The preview grid is an editing coordinate system, not generated geometry.
This module maps its pixel centres onto a fresh analysis grid so only explicit
user deltas are replayed after dimensions change.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.recipe_order import pad_material_matrix_layers


MAX_EDIT_PROJECTION_PIXELS = 64_000_000


def _validate_grid_shape(shape: tuple[int, int], *, label: str) -> tuple[int, int]:
    """Return one positive two-dimensional integer grid shape."""

    if len(shape) != 2:
        raise ValueError(f"{label} grid must contain exactly two dimensions")
    try:
        height, width = (int(shape[0]), int(shape[1]))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} grid dimensions must be integers") from exc
    if height <= 0 or width <= 0:
        raise ValueError(f"{label} grid dimensions must be positive")
    return height, width


@dataclass(frozen=True, slots=True)
class EditProjectionGrid:
    """Map preview edit pixels onto a fresh current-size analysis grid.

    映射预览编辑像素到当前尺寸的新分析网格。采样使用像素中心最近邻，
    因此布尔选区、离散材料编号和 RGB 都不会被插值成无效的中间值。
    """

    source_shape: tuple[int, int]
    target_shape: tuple[int, int]
    max_target_pixels: int = MAX_EDIT_PROJECTION_PIXELS

    def __post_init__(self) -> None:
        source_shape = _validate_grid_shape(self.source_shape, label="source")
        target_shape = _validate_grid_shape(self.target_shape, label="target")
        max_pixels = int(self.max_target_pixels)
        if max_pixels <= 0:
            raise ValueError("maximum projected pixel count must be positive")
        if target_shape[0] * target_shape[1] > max_pixels:
            raise ValueError("target edit projection grid exceeds the safety limit")
        object.__setattr__(self, "source_shape", source_shape)
        object.__setattr__(self, "target_shape", target_shape)
        object.__setattr__(self, "max_target_pixels", max_pixels)

    @staticmethod
    def _axis_indices(source_size: int, target_size: int) -> np.ndarray:
        indices = (
            (np.arange(target_size, dtype=np.float64) + 0.5)
            * source_size
            / target_size
        ).astype(np.intp)
        return np.minimum(indices, source_size - 1)

    def project(self, values: np.ndarray) -> np.ndarray:
        """Project the first two axes while preserving all value axes.

        投影前两个空间轴，并原样保留 RGB、材料层等尾部值轴。
        """

        source = np.asarray(values)
        if source.ndim < 2 or source.shape[:2] != self.source_shape:
            raise ValueError(
                "projection input does not match the declared source grid"
            )
        if self.source_shape == self.target_shape:
            return source
        source_h, source_w = self.source_shape
        target_h, target_w = self.target_shape
        y_indices = self._axis_indices(source_h, target_h)
        x_indices = self._axis_indices(source_w, target_w)
        return source[y_indices[:, None], x_indices[None, :], ...]

    def project_mask(
        self,
        source_mask: np.ndarray,
        *,
        target_solid: np.ndarray | None = None,
    ) -> np.ndarray:
        """Project one boolean mask and optionally clip it to target solids.

        投影布尔选区，并可选地裁剪到目标实体范围。
        """

        projected = np.asarray(self.project(source_mask), dtype=bool)
        if target_solid is None:
            return projected
        solid = np.asarray(target_solid, dtype=bool)
        if solid.shape != self.target_shape:
            raise ValueError("target solid mask does not match the target grid")
        return projected & solid

    def sample_target_mask(
        self,
        values: np.ndarray,
        target_mask: np.ndarray,
    ) -> np.ndarray:
        """Sample values only for selected target pixels.

        This avoids allocating a full projected RGB/material tensor when an
        edit touches only a small part of a large capped preview grid.
        只采样目标选区需要的值，避免为小范围编辑分配完整 RGB/材料张量。
        """

        source = np.asarray(values)
        if source.ndim < 2 or source.shape[:2] != self.source_shape:
            raise ValueError(
                "projection input does not match the declared source grid"
            )
        selected = np.asarray(target_mask, dtype=bool)
        if selected.shape != self.target_shape:
            raise ValueError("target mask does not match the target grid")
        target_y, target_x = np.nonzero(selected)
        source_y = self._axis_indices(
            self.source_shape[0],
            self.target_shape[0],
        )
        source_x = self._axis_indices(
            self.source_shape[1],
            self.target_shape[1],
        )
        return source[source_y[target_y], source_x[target_x], ...]

    def source_change_mask(
        self,
        edited: np.ndarray,
        pristine: np.ndarray,
        *,
        source_solid: np.ndarray | None = None,
    ) -> np.ndarray:
        """Return source pixels whose discrete value differs from pristine.

        返回相对原始状态发生离散值变化的源网格像素。
        """

        edited_arr = np.asarray(edited)
        pristine_arr = np.asarray(pristine)
        if edited_arr.shape != pristine_arr.shape:
            raise ValueError("edited and pristine artifacts must use one shape")
        if edited_arr.ndim < 2 or edited_arr.shape[:2] != self.source_shape:
            raise ValueError("edit artifacts do not match the source grid")
        differences = edited_arr != pristine_arr
        if differences.ndim > 2:
            differences = np.any(
                differences,
                axis=tuple(range(2, differences.ndim)),
            )
        changed = np.asarray(differences, dtype=bool)
        if source_solid is not None:
            solid = np.asarray(source_solid, dtype=bool)
            if solid.shape != self.source_shape:
                raise ValueError("source solid mask does not match the source grid")
            changed &= solid
        return changed

    def project_change_mask(
        self,
        edited: np.ndarray,
        pristine: np.ndarray,
        *,
        source_solid: np.ndarray | None = None,
        target_solid: np.ndarray | None = None,
    ) -> np.ndarray:
        """Project only explicit source deltas onto target solid pixels.

        仅把明确的源编辑差异投影到目标实体像素。
        """

        return self.project_mask(
            self.source_change_mask(
                edited,
                pristine,
                source_solid=source_solid,
            ),
            target_solid=target_solid,
        )

    def replay(
        self, edited: np.ndarray, pristine: np.ndarray, fresh: np.ndarray,
        *, source_solid: np.ndarray, target_solid: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Copy explicit deltas only; fresh analysis owns all other pixels."""
        if fresh.shape[:2] != self.target_shape or fresh.shape[2:] != edited.shape[2:]:
            raise ValueError("fresh analysis does not match the projected edit values")
        changed = self.project_change_mask(
            edited, pristine, source_solid=source_solid, target_solid=target_solid,
        )
        result = fresh.copy()
        result[changed] = self.sample_target_mask(edited, changed)
        return result, changed

    def replay_materials(
        self, edited: np.ndarray, pristine: np.ndarray, fresh: np.ndarray,
        *, source_solid: np.ndarray, target_solid: np.ndarray,
        base_channel_idx: int, layer_order: str, target_layers: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Align backing layers before comparing edits, then use the output depth.

        Project restoration retains all saved layers. Generation supplies its
        requested depth; changing that depth never changes the source checkpoint.
        """
        layers = max(edited.shape[2], pristine.shape[2], fresh.shape[2], target_layers)
        aligned = [pad_material_matrix_layers(matrix, layers, base_channel_idx, layer_order, solid)
                   for matrix, solid in ((edited, source_solid), (pristine, source_solid), (fresh, target_solid))]
        result, changed = self.replay(*aligned, source_solid=source_solid, target_solid=target_solid)
        view_layers = slice(-target_layers, None) if layer_order == "Bottom2Top" else slice(None, target_layers)
        return result[..., view_layers], changed
