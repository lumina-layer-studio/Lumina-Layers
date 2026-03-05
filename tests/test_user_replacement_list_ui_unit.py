import os
import sys

# Add project root to path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import numpy as np

from config import ModelingMode
from core.converter import _normalize_color_replacements_input
from core.i18n import I18n
from ui.callbacks import on_apply_color_replacement, on_delete_selected_user_replacement
from ui.palette_extension import generate_palette_html


def test_palette_list_i18n_keys_exist():
    keys = [
        'conv_palette_user_replacements_title',
        'conv_palette_auto_pairs_title',
        'conv_palette_delete_selected_btn',
        'conv_palette_delete_selected_empty',
        'conv_palette_user_empty',
        'conv_palette_auto_empty',
    ]
    for k in keys:
        assert I18n.get(k, 'zh')
        assert I18n.get(k, 'en')


def test_generate_palette_html_uses_list_cards_and_selected_classes():
    html = generate_palette_html(
        palette=[],
        replacements={'#111111': '#aaaaaa'},
        replacement_regions=[{'source': '#222222', 'matched': '#333333', 'replacement': '#bbbbbb'}],
        auto_pairs=[{'quantized_hex': '#010203', 'matched_hex': '#040506'}],
        selected_user_row_id='user::#222222|#333333|#bbbbbb|0',
        selected_auto_row_id='auto::#010203|#040506|0',
        lang='zh',
    )
    assert '<table' not in html
    assert "class='palette-list-item is-selected'" in html
    assert "data-row-type='user'" in html
    assert "data-row-type='auto'" in html
    assert "id='conv-palette-delete-selected'" in html


def test_delete_selected_user_replacement_removes_target_row(monkeypatch):
    cache = {'dummy': True}
    replacement_regions = [{'source': '#222222', 'matched': '#333333', 'replacement': '#bbbbbb', 'mask': None}]
    history = []

    def fake_update_preview_with_replacements(cache, new_regions, *args, **kwargs):
        return 'preview', {'dummy': True}, '<html/>'

    monkeypatch.setattr('ui.callbacks.update_preview_with_replacements', fake_update_preview_with_replacements,
                        raising=False)

    _, _, _, new_regions, new_history, status, selected_user = on_delete_selected_user_replacement(
        cache, replacement_regions, history,
        'user::#222222|#333333|#bbbbbb|0',
        None, False, 4, 8, 2.5, 0, 'zh'
    )


def test_apply_replacement_global_scope_writes_region_not_map(monkeypatch):
    cache = {
        'selection_scope': 'global',
        'selected_region_mask': None,
        'quantized_image': np.array([
            [[1, 2, 3], [9, 9, 9]],
            [[1, 2, 3], [4, 5, 6]],
        ], dtype=np.uint8),
        'matched_rgb': np.array([
            [[7, 8, 9], [9, 9, 9]],
            [[7, 8, 9], [4, 5, 6]],
        ], dtype=np.uint8),
        'mask_solid': np.array([
            [True, True],
            [True, True],
        ], dtype=bool),
        'selected_quantized_hex': '#010203',
        'selected_matched_hex': '#070809',
    }

    def fake_update_preview_with_replacements(cache, new_regions, *args, **kwargs):
        return 'preview', cache, '<html/>'

    monkeypatch.setattr('core.converter.update_preview_with_replacements', fake_update_preview_with_replacements,
                        raising=False)

    _, _, _, new_regions, _, _ = on_apply_color_replacement(
        cache,
        '#010203',
        '#aabbcc',
        [],
        [],
        None,
        False,
        4,
        8,
        2.5,
        0,
        'zh',
    )

    assert len(new_regions) == 1
    assert new_regions[0]['source'] == '#010203'
    assert new_regions[0]['replacement'] == '#aabbcc'
    assert new_regions[0]['mask'].dtype == bool
    assert int(new_regions[0]['mask'].sum()) == 2


def test_normalize_color_replacements_accepts_region_list_without_crash():
    region_list = [
        {'source': '#112233', 'replacement': '#aabbcc'},
        {'source': '#445566', 'replacement': '#ddeeff'},
    ]

    normalized = _normalize_color_replacements_input(region_list)

    assert normalized == {
        '#112233': '#aabbcc',
        '#445566': '#ddeeff',
    }


def test_normalize_color_replacements_prefers_matched_when_present_in_region_item():
    region_list = [
        {'source': '#010203', 'matched': '#070809', 'replacement': '#aabbcc'},
    ]

    normalized = _normalize_color_replacements_input(region_list)

    assert normalized == {
        '#070809': '#aabbcc',
    }


def test_process_batch_generation_single_accepts_replacement_regions_list(monkeypatch):
    captured = {}

    def fake_generate_final_model(*args, **kwargs):
        captured['args'] = args
        captured['kwargs'] = kwargs
        return 'out.3mf', 'preview.glb', None, 'ok', None

    monkeypatch.setattr('ui.layout_new.generate_final_model', fake_generate_final_model)

    from ui.layout_new import process_batch_generation

    replacement_regions = [
        {'source': '#112233', 'replacement': '#aabbcc'},
        {'source': '#445566', 'replacement': '#ddeeff'},
    ]

    out_path, glb_path, preview_img, status, color_recipe_path = process_batch_generation(
        batch_files=None,
        is_batch=False,
        single_image='demo.png',
        lut_path='demo.npy',
        target_width_mm=20,
        spacer_thick=1.0,
        structure_mode='单面',
        auto_bg=True,
        bg_tol=12,
        color_mode='4-Color',
        add_loop=False,
        loop_width=4,
        loop_length=8,
        loop_hole=2.5,
        loop_pos=None,
        modeling_mode=ModelingMode.HIGH_FIDELITY.value,
        quantize_colors=16,
        replacement_regions=replacement_regions,
        separate_backing=False,
        enable_relief=False,
        color_height_map=None,
        heightmap_path=None,
        heightmap_max_height=None,
        enable_cleanup=True,
        enable_outline=False,
        outline_width=2.0,
        enable_cloisonne=False,
        wire_width_mm=0.4,
        wire_height_mm=0.4,
        free_color_set=None,
        enable_coating=False,
        coating_height_mm=0.08,
    )

    assert out_path == 'out.3mf'
    assert glb_path == 'preview.glb'
    assert status == 'ok'
    assert captured['kwargs']['image_path'] == 'demo.png'
    assert captured['kwargs']['replacement_regions'] == replacement_regions


def test_process_batch_generation_full_pipeline_replacement_regions_affect_preview_and_model():
    from ui.layout_new import process_batch_generation

    image_path = 'test_images/sample_logo.png'
    lut_path = 'lut-npy预设/bambulab/bambulab_pla_basic_rybw.npy'

    assert os.path.exists(image_path)
    assert os.path.exists(lut_path)

    common_kwargs = dict(
        batch_files=None,
        is_batch=False,
        single_image=image_path,
        lut_path=lut_path,
        target_width_mm=50.0,
        spacer_thick=2.0,
        structure_mode='Double-sided',
        auto_bg=False,
        bg_tol=10,
        color_mode='4-Color',
        add_loop=False,
        loop_width=4,
        loop_length=8,
        loop_hole=2.5,
        loop_pos=None,
        modeling_mode=ModelingMode.HIGH_FIDELITY.value,
        quantize_colors=64,
        separate_backing=False,
        enable_relief=False,
        color_height_map=None,
        heightmap_path=None,
        heightmap_max_height=None,
        enable_cleanup=True,
        enable_outline=False,
        outline_width=2.0,
        enable_cloisonne=False,
        wire_width_mm=0.4,
        wire_height_mm=0.4,
        free_color_set=None,
        enable_coating=False,
        coating_height_mm=0.08,
    )

    base_out, base_glb, base_preview, base_status, _ = process_batch_generation(
        replacement_regions=None,
        **common_kwargs,
    )

    def preview_value(preview_output):
        if isinstance(preview_output, dict) and preview_output.get('__type__') == 'update':
            return preview_output.get('value')
        return preview_output

    base_preview_value = preview_value(base_preview)
    assert base_preview_value is not None

    solid_mask = base_preview_value[:, :, 3] > 0

    replaced_out, replaced_glb, replaced_preview, replaced_status, _ = process_batch_generation(
        replacement_regions=[{'matched': '#d60040', 'replacement': '#00ff00', 'mask': solid_mask}],
        **common_kwargs,
    )

    replaced_preview_value = preview_value(replaced_preview)

    assert base_out and os.path.exists(base_out)
    assert replaced_out and os.path.exists(replaced_out)
    assert base_glb and os.path.exists(base_glb)
    assert replaced_glb and os.path.exists(replaced_glb)
    assert replaced_preview_value is not None
    assert isinstance(base_status, str) and base_status
    assert isinstance(replaced_status, str) and replaced_status

    assert np.any(base_preview_value != replaced_preview_value)


def test_update_preview_with_replacement_regions_applies_hex_without_nameerror(monkeypatch):
    from core.converter import update_preview_with_replacements

    cache = {
        'matched_rgb': np.array([[[1, 2, 3]]], dtype=np.uint8),
        'original_matched_rgb': np.array([[[1, 2, 3]]], dtype=np.uint8),
        'mask_solid': np.array([[True]], dtype=bool),
        'color_conf': {'slots': ['C']},
        'preview_rgba': np.zeros((1, 1, 4), dtype=np.uint8),
    }

    monkeypatch.setattr('core.converter.render_preview', lambda *args, **kwargs: 'display', raising=False)
    monkeypatch.setattr('core.converter.extract_color_palette', lambda *_args, **_kwargs: [], raising=False)
    monkeypatch.setattr('ui.palette_extension.generate_palette_html', lambda *args, **kwargs: '<html/>', raising=False)

    replacement_regions = [
        {'mask': np.array([[True]], dtype=bool), 'replacement': '#aabbcc'},
    ]

    display, updated_cache, _ = update_preview_with_replacements(
        cache,
        replacement_regions,
        None,
        False,
        4,
        8,
        2.5,
        0,
        'zh',
    )

    assert display == 'display'
    assert tuple(updated_cache['matched_rgb'][0, 0]) == (170, 187, 204)


from ui.callbacks import on_undo_color_replacement


def test_undo_uses_regions_only_history(monkeypatch):
    cache = {
        'matched_rgb': np.zeros((1, 1, 3), dtype=np.uint8),
        'mask_solid': np.array([[True]]),
        'color_conf': {'slots': ['C']},
        'preview_rgba': np.zeros((1, 1, 4), dtype=np.uint8),
    }
    history = [[{'source': '#010203', 'replacement': '#aabbcc', 'mask': np.array([[True]])}]]

    monkeypatch.setattr(
        'core.converter.update_preview_with_replacements',
        lambda *a, **k: ('d', cache, '<html/>'),
        raising=False,
    )

    _, _, _, regions, new_history, _ = on_undo_color_replacement(
        cache, [], history, None, False, 4, 8, 2.5, 0, 'zh'
    )
    assert len(regions) == 1
    assert new_history == []


from core.converter import update_preview_with_replacements


def test_update_preview_applies_regions_in_order_without_map(monkeypatch):
    cache = {
        'matched_rgb': np.array([[[1, 2, 3], [1, 2, 3]]], dtype=np.uint8),
        'original_matched_rgb': np.array([[[1, 2, 3], [1, 2, 3]]], dtype=np.uint8),
        'mask_solid': np.array([[True, True]], dtype=bool),
        'color_conf': {'slots': ['C']},
        'preview_rgba': np.zeros((1, 2, 4), dtype=np.uint8),
    }

    monkeypatch.setattr('core.converter.render_preview', lambda *a, **k: 'display', raising=False)
    monkeypatch.setattr('core.converter.extract_color_palette', lambda *_a, **_k: [], raising=False)
    monkeypatch.setattr('ui.palette_extension.generate_palette_html', lambda *a, **k: '<html/>', raising=False)

    r1 = {'mask': np.array([[True, False]], dtype=bool), 'replacement': '#112233'}
    r2 = {'mask': np.array([[True, True]], dtype=bool), 'replacement': '#aabbcc'}

    _, updated, _ = update_preview_with_replacements(cache, [r1, r2], None, False, 4, 8, 2.5, 0, 'zh')
    assert tuple(updated['matched_rgb'][0, 0]) == (170, 187, 204)
    assert tuple(updated['matched_rgb'][0, 1]) == (170, 187, 204)


def test_create_converter_tab_content_initializes_without_replacement_map_nameerror():
    import gradio as gr
    from ui.layout_new import create_converter_tab_content

    with gr.Blocks():
        lang_state = gr.State(value='zh')
        theme_state = gr.State(value=False)
        components = create_converter_tab_content('zh', lang_state, theme_state)

    assert isinstance(components, dict)


from core.converter import _apply_regions_to_raster_outputs


def test_regions_override_updates_material_matrix_in_order():
    matched_rgb = np.array([[[1, 2, 3], [4, 5, 6]]], dtype=np.uint8)
    material_matrix = np.array([[[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]]], dtype=np.int16)
    mask_solid = np.array([[True, True]], dtype=bool)

    ref_stacks = np.array([
        [0, 0, 0, 0, 0],
        [1, 1, 1, 1, 1],
        [2, 2, 2, 2, 2],
        [3, 3, 3, 3, 3],
    ], dtype=np.int16)

    def rgb_to_lut_index(rgb_tuple):
        if rgb_tuple == (17, 34, 51):
            return 2
        if rgb_tuple == (170, 187, 204):
            return 3
        raise AssertionError(f"unexpected rgb: {rgb_tuple}")

    regions = [
        {'mask': np.array([[True, False]], dtype=bool), 'replacement': '#112233'},
        {'mask': np.array([[True, True]], dtype=bool), 'replacement': '#aabbcc'},
    ]

    out_rgb, out_mat = _apply_regions_to_raster_outputs(
        matched_rgb,
        material_matrix,
        mask_solid,
        regions,
        rgb_to_lut_index,
        ref_stacks,
    )

    assert tuple(out_rgb[0, 0]) == (170, 187, 204)
    assert tuple(out_rgb[0, 1]) == (170, 187, 204)
    assert tuple(out_mat[0, 0]) == (3, 3, 3, 3, 3)
    assert tuple(out_mat[0, 1]) == (3, 3, 3, 3, 3)
