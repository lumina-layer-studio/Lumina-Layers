import pytest

from core.i18n import I18n
from ui.callbacks import on_clear_selected_original_color


@pytest.mark.unit
def test_on_clear_selected_original_color_resets_state_and_message():
    selected_display, selected_state, status = on_clear_selected_original_color("zh")

    assert selected_display is None
    assert selected_state is None
    assert status == I18n.get("palette_not_selected", "zh")
