"""Merged LUTs must retain every material channel after serialization."""

from pathlib import Path

import numpy as np
import pytest

from config import LUTMetadata, ModelingMode, PaletteEntry
from core.pipeline import s01_input_validation, s05_preview_generation
from utils.lut_manager import LUTManager


@pytest.mark.parametrize("second_material", ["PLA", "PETG (matte)"])
def test_multi_lut_roundtrip_preserves_same_color_different_materials(
    tmp_path: Path, second_material: str,
) -> None:
    paths = []
    materials = ["PLA Basic", second_material]
    colors = [("Red", "#e02030"), ("White", "#fff8f0")]
    for index, material in enumerate(materials):
        path = tmp_path / f"source-{index}.npz"
        LUTManager.save_npz_with_metadata(
            str(path),
            np.array([[120 + index, 30, 20]], dtype=np.uint8),
            np.array([[0, 1, 0, 1, 0]], dtype=np.int32),
            LUTMetadata(
                palette=[PaletteEntry(name, material, color) for name, color in colors],
                base_channel_idx=1,
            ),
        )
        paths.append(str(path))

    runtime = Path(LUTManager._legacy_multi_runtime_path(["first", "second"], paths))
    try:
        rgb, stacks, metadata = LUTManager.load_lut_with_metadata(str(runtime))
        assert len(metadata.palette) == 4
        assert len({entry.color for entry in metadata.palette}) == 4
        np.testing.assert_array_equal(rgb, [[120, 30, 20], [121, 30, 20]])
        for row, material in zip(stacks, materials):
            assert [metadata.palette[i].material for i in row] == [material] * 5
            assert [metadata.palette[i].hex_color for i in row] == [
                "#e02030", "#fff8f0", "#e02030", "#fff8f0", "#e02030",
            ]
        backing = metadata.palette[metadata.base_channel_idx]
        assert (backing.material, backing.hex_color) == ("PLA Basic", "#fff8f0")

        # The real generation stages must resolve the selected loop channel,
        # including indices above the palette size before the fix.
        ctx = s01_input_validation.run({
            "image_path": str(tmp_path / "image.png"),
            "lut_path": str(runtime),
            "color_mode": "4-Color (RYBW)",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
        })
        ctx.update(
            matched_rgb=np.full((10, 10, 3), 120, dtype=np.uint8),
            mask_solid=np.ones((10, 10), dtype=bool),
            material_matrix=np.tile(stacks[0], (10, 10, 1)),
            target_w=10, target_h=10, pixel_scale=1.0, add_loop=True,
        )
        ctx = s05_preview_generation.run(ctx)
        selected = metadata.palette[ctx["loop_info"]["color_id"]]
        assert selected.material == "PLA Basic"
        assert ctx["loop_info"]["material_name"] == selected.color

        # A merged LUT remains a valid input; labels must not create new channels.
        remixed = Path(LUTManager._legacy_multi_runtime_path(["merged"], [str(runtime)]))
        try:
            _, remixed_stacks, remixed_metadata = LUTManager.load_lut_with_metadata(str(remixed))
            assert remixed_metadata.palette == metadata.palette
            assert remixed_metadata.base_channel_idx == metadata.base_channel_idx
            np.testing.assert_array_equal(remixed_stacks, stacks)
        finally:
            remixed.unlink()
    finally:
        runtime.unlink()
