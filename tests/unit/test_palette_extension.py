import pytest

from ui.palette_extension import (
    RECOMMENDED_REPLACEMENT_COUNT,
    generate_lut_color_grid_html,
    generate_palette_html,
)


@pytest.mark.unit
def test_generate_palette_html_splits_applied_and_original_sections():
    payload = generate_palette_html(
        palette=[
            {"hex": "#111111", "percentage": 60.0, "token": "#111111"},
            {"hex": "#222222", "percentage": 40.0, "token": "#222222"},
        ],
        replacements={"#111111": "#eeeeee"},
        selected_color="#222222",
        original_palette=[
            {
                "quant_hex": "#111111",
                "matched_hex": "#121212",
                "percentage": 60.0,
                "token": "#111111",
            },
            {
                "quant_hex": "#222222",
                "matched_hex": "#232323",
                "percentage": 40.0,
                "token": "#222222",
            },
        ],
        lang="zh",
    )

    assert payload["empty"] is False
    assert payload["applied_title"] == "已生效的替换"
    assert payload["original_title"] == "原始颜色"
    assert payload["applied_legend"].startswith("说明")
    assert payload["quant_label"] == "量化"
    assert payload["original_label"] == "原始"
    assert payload["replaced_label"] == "替换"
    assert payload["applied_items"][0]["quant_hex"] == "#111111"
    assert payload["applied_items"][0]["original_hex"] == "#121212"
    assert payload["applied_items"][0]["replacement_hex"] == "#eeeeee"
    assert payload["original_items"][1]["token"] == "#222222"
    assert payload["original_items"][1]["row_class"] == "palette-row-selected"


@pytest.mark.unit
def test_generate_lut_color_grid_html_includes_recommended_section_and_limit():
    colors: list[dict[str, object]] = []
    for i in range(RECOMMENDED_REPLACEMENT_COUNT + 5):
        colors.append({"hex": f"#{i:02x}{i:02x}{i:02x}", "color": (i, i, i)})

    payload = generate_lut_color_grid_html(
        colors=colors,
        selected_color="#ffffff",
        used_colors={"#000000"},
        reference_color="#101010",
        lang="zh",
    )

    assert payload["empty"] is False
    assert payload["recommended_section"]["title"].startswith("推荐相近颜色")
    assert "RGB/HSV/Lab" in payload["recommended_section"]["hint"]
    assert len(payload["recommended_section"]["items"]) <= RECOMMENDED_REPLACEMENT_COUNT


@pytest.mark.unit
def test_generate_lut_color_grid_html_recommended_is_independent_of_selected_color():
    colors = [
        {"hex": "#101010", "color": (16, 16, 16)},
        {"hex": "#121212", "color": (18, 18, 18)},
        {"hex": "#f0f0f0", "color": (240, 240, 240)},
    ]

    payload = generate_lut_color_grid_html(
        colors=colors,
        selected_color="#f0f0f0",
        used_colors=set(),
        reference_color="#101010",
        lang="zh",
    )

    assert payload["recommended_section"] is not None
    recommended_hex = {item["hex"] for item in payload["recommended_section"]["items"]}
    assert "#121212" in recommended_hex
