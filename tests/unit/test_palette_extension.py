import pytest

from ui.palette_extension import (
    RECOMMENDED_REPLACEMENT_COUNT,
    generate_lut_color_grid_html,
    generate_palette_html,
)


@pytest.mark.unit
def test_generate_palette_html_splits_applied_and_original_sections():
    html = generate_palette_html(
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

    assert "已生效的替换" in html
    assert "原始颜色" in html
    assert "说明：量化" in html
    assert "量化" in html
    assert "原始" in html
    assert "替换" in html
    assert "#111111" in html
    assert "#121212" in html
    assert "#eeeeee" in html
    assert "palette-applied-item" in html
    assert "palette-original-item" in html
    assert "palette-remove-replacement-btn" not in html


@pytest.mark.unit
def test_generate_lut_color_grid_html_includes_recommended_section_and_limit():
    colors: list[dict[str, object]] = []
    for i in range(RECOMMENDED_REPLACEMENT_COUNT + 5):
        colors.append({"hex": f"#{i:02x}{i:02x}{i:02x}", "color": (i, i, i)})

    html = generate_lut_color_grid_html(
        colors=colors,
        selected_color="#ffffff",
        used_colors={"#000000"},
        reference_color="#101010",
        lang="zh",
    )

    assert "推荐相近颜色" in html
    assert "RGB/HSV/Lab" in html
    assert html.count('class="lut-color-swatch"') >= RECOMMENDED_REPLACEMENT_COUNT


@pytest.mark.unit
def test_generate_lut_color_grid_html_recommended_is_independent_of_selected_color():
    colors = [
        {"hex": "#101010", "color": (16, 16, 16)},
        {"hex": "#121212", "color": (18, 18, 18)},
        {"hex": "#f0f0f0", "color": (240, 240, 240)},
    ]

    html = generate_lut_color_grid_html(
        colors=colors,
        selected_color="#f0f0f0",
        used_colors=set(),
        reference_color="#101010",
        lang="zh",
    )

    assert "推荐相近颜色" in html
    assert "#121212" in html
