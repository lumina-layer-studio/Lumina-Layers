import pytest

from ui.palette_extension import generate_palette_html


@pytest.mark.unit
def test_generate_palette_html_splits_applied_and_original_sections():
    html = generate_palette_html(
        palette=[
            {"hex": "#111111", "percentage": 60.0},
            {"hex": "#222222", "percentage": 40.0},
        ],
        replacements={"#111111": "#eeeeee"},
        selected_color="#222222",
        original_palette=[
            {"hex": "#111111", "percentage": 60.0},
            {"hex": "#222222", "percentage": 40.0},
        ],
        lang="zh",
    )

    assert "已生效的替换" in html
    assert "原始颜色" in html
    assert "palette-remove-replacement-btn" in html
