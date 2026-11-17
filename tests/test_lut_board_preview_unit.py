from __future__ import annotations

import base64
from io import BytesIO

import numpy as np
from PIL import Image
import pytest

from core.lut_board_preview import lut_board_preview, published_lut_board


def _pixels(page: dict) -> np.ndarray:
    with Image.open(BytesIO(base64.b64decode(page["png"]))) as image:
        return np.asarray(image.convert("RGBA"))


@pytest.mark.parametrize(("mode", "counts", "family", "padding"), [
    ("5-Color Extended", [1024, 1444], "five", [4, 1]),
    ("8-Color Max", [1369, 1369], "eight", [1, 1]),
])
def test_two_boards_preserve_every_rgb_row_and_the_canonical_page_boundary(mode, counts, family, padding):
    rgb = np.arange(3 * sum(counts), dtype=np.int64).reshape(-1, 3).astype(np.uint8)
    preview = lut_board_preview(rgb, mode, {})["lut_board_preview"]
    assert preview["set_size"] == 2 and preview["family"] == family
    assert [page["padding"] for page in preview["pages"]] == padding
    assert published_lut_board(preview)["lut_board_preview"] == preview
    offset = 0
    for page_number, (page, count) in enumerate(zip(preview["pages"], counts, strict=True), 1):
        assert (page["number"], page["count"]) == (page_number, count)
        pixels = _pixels(page)
        assert pixels.shape == (page["rows"], page["cols"], 4)
        assert (pixels[:, :, 3] == 255).all()
        np.testing.assert_array_equal(pixels[:, :, :3].reshape(-1, 3), rgb[offset:offset + count])
        offset += count


def test_full_eight_color_and_standalone_page_keep_last_board_position_and_unused_cells():
    rgb = np.zeros((32768, 3), dtype=np.uint8)
    rgb[-1] = [4, 26, 255]
    preview = lut_board_preview(rgb, "8-Color Max", {})["lut_board_preview"]
    assert (preview["family"], preview["set_size"], len(preview["pages"])) == ("full", 24, 24)
    last = preview["pages"][-1]
    assert (last["number"], last["count"], last["rows"], last["cols"]) == (24, 1281, 37, 37)
    pixels = _pixels(last).reshape(-1, 4)
    assert pixels[1280].tolist() == [4, 26, 255, 255]
    assert np.count_nonzero(pixels[1281:, 3]) == 0
    standalone = lut_board_preview(rgb[-1281:], "8-Color Max", {"page_index": 24, "total_pages": 24})["lut_board_preview"]
    assert standalone["pages"] == [last] and standalone["set_size"] == 24
    five = lut_board_preview(rgb[:1444], "5-color", {})["lut_board_preview"]
    assert five["set_size"] == 2 and [p["number"] for p in five["pages"]] == [2]
    partial = lut_board_preview(rgb[:47], "8-color", {})["lut_board_preview"]
    assert partial["family"] == "index" and partial["set_size"] == 1
    assert not lut_board_preview(rgb[:100], "8-Color Max", {"page_index": 1, "total_pages": 2})


def test_custom_lookup_and_untrusted_remote_board_fields_have_bounded_preview():
    rgb = np.zeros((5000, 3), dtype=np.uint8)
    preview = lut_board_preview(rgb, "Merged", {})["lut_board_preview"]
    page = preview["pages"][0]
    assert preview["family"] == "index"
    assert _pixels(page).shape == (48, 48, 4)
    assert not published_lut_board({**preview, "pages": [{**page, "png": "https://invalid.test/full-lut"}]})
    assert not published_lut_board({**preview, "pages": [{**page, "rows": 12}]})
    assert not lut_board_preview(np.zeros((8, 4)), "BW", {})


def test_bw_scans_preserve_32_printed_positions_and_leave_the_last_four_blank():
    rgb = np.zeros((6, 6, 3), dtype=np.uint8)
    rgb.reshape(-1, 3)[:32] = np.arange(32)[:, None]
    board = lut_board_preview(rgb, "2-color", {})["lut_board_preview"]
    page = board["pages"][0]
    assert (board["family"], page["padding"], page["count"]) == ("board", 1, 32)
    pixels = _pixels(page).reshape(-1, 4)
    np.testing.assert_array_equal(pixels[:32, :3], rgb.reshape(-1, 3)[:32])
    assert not pixels[32:, 3].any()
    rgb[-1, -1] = [4, 5, 6]
    custom = lut_board_preview(rgb, "2-color", {})["lut_board_preview"]
    assert custom["family"] == "index" and custom["pages"][0]["count"] == 36


def test_print_gap_follows_recorded_geometry_and_defaults_to_the_calibration_form():
    rgb = np.zeros((1024, 3), dtype=np.uint8)
    default_board = lut_board_preview(rgb, "RYBW", {})["lut_board_preview"]
    assert default_board["block_fraction"] == pytest.approx(11 / 13)
    custom = lut_board_preview(rgb, "RYBW", {"block_size_mm": 4.2, "gap_mm": 0.42})["lut_board_preview"]
    assert custom["block_fraction"] == pytest.approx(10 / 11)
    assert published_lut_board(custom)["lut_board_preview"] == custom
