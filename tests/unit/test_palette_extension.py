import pytest

from ui.palette_extension import generate_palette_html


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
