import pytest

from core.i18n import I18n
from ui.callbacks import (
    on_clear_selected_original_color,
    on_remove_single_color_replacement,
)


@pytest.mark.unit
def test_on_clear_selected_original_color_resets_state_and_message():
    selected_display, selected_state, status = on_clear_selected_original_color("zh")

    assert selected_display is None
    assert selected_state is None
    assert status == I18n.get("palette_not_selected", "zh")


@pytest.mark.unit
def test_on_remove_single_color_replacement_updates_map_and_selects_removed_color(
    monkeypatch: pytest.MonkeyPatch,
):
    def _fake_update(*args, **kwargs):
        return "preview", {"cache": 1}, "<html>ok</html>"

    monkeypatch.setattr(
        "ui.converter_ui.update_preview_with_replacements", _fake_update
    )

    display, updated_cache, palette_html, new_map, new_history, selected, status = (
        on_remove_single_color_replacement(
            cache={"x": 1},
            original_color="#112233",
            replacement_map={"#112233": "#445566", "#abcdef": "#010203"},
            replacement_history=[],
            loop_pos=None,
            add_loop=False,
            loop_width=4,
            loop_length=8,
            loop_hole=2.5,
            loop_angle=0,
            lang="zh",
        )
    )

    assert display == "preview"
    assert updated_cache == {"cache": 1}
    assert palette_html == "<html>ok</html>"
    assert new_map == {"#abcdef": "#010203"}
    assert len(new_history) == 1
    assert selected == "#112233"
    assert "#112233" in status
