import pytest
import inspect

from config import ColorMode, MatchStrategy, StructureMode
from ui.tabs import converter_tab
from ui.tabs.converter_tab import process_batch_generation


@pytest.mark.unit
def test_process_batch_generation_returns_friendly_error_when_modeling_mode_missing():
    out_3mf, out_glb, preview, status = process_batch_generation(
        batch_files=[],
        is_batch=False,
        single_image="dummy.png",
        lut_path="dummy.npy",
        target_width_mm=60,
        spacer_thick=1.2,
        structure_mode=StructureMode.DOUBLE_SIDED.value,
        auto_bg=False,
        bg_tol=40,
        color_mode=ColorMode.RYBW,
        add_loop=False,
        loop_width=4,
        loop_length=8,
        loop_hole=2.5,
        loop_pos=None,
        modeling_mode=None,
        quantize_colors=64,
        color_replacements={},
        match_strategy=MatchStrategy.RGB_EUCLIDEAN,
        lang="zh",
    )

    assert out_3mf is None
    assert out_glb is None
    assert isinstance(preview, dict)
    assert "建模模式" in str(status)


@pytest.mark.unit
def test_preview_click_sync_ui_uses_hex_for_colorpicker_binding():
    source = inspect.getsource(converter_tab.create_converter_tab_content)
    assert "return _preview_update(img), display_hex, hex_val, resolved_msg" in source


@pytest.mark.unit
def test_palette_has_clear_selected_button_binding():
    source = inspect.getsource(converter_tab.create_converter_tab_content)
    assert 'I18n.get("conv_palette_unselect_btn", lang)' in source
    assert "conv_clear_selected.click(" in source
    assert "on_clear_selected_and_highlight_with_fit" in source


@pytest.mark.unit
def test_palette_has_color_select_and_single_remove_bindings():
    source = inspect.getsource(converter_tab.create_converter_tab_content)
    assert "conv_color_trigger_btn.click(" in source
    assert "on_original_color_click" in source
    assert 'I18n.get("conv_palette_undo_selected_btn", lang)' in source
    assert "conv_undo_selected_replacement.click(" in source
    assert "on_remove_single_replacement_with_fit" in source
