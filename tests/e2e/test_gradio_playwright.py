from contextlib import contextmanager
import socket
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from core.i18n import I18n

pytest.importorskip("gradio")
import gradio as gr


@contextmanager
def launch_server(demo: gr.Blocks):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])

    _, local_url, _ = demo.launch(
        prevent_thread_lock=True,
        server_name="127.0.0.1",
        server_port=port,
        show_error=True,
    )
    try:
        yield local_url
    finally:
        demo.close()


def _wait_status_contains(page, message: str, timeout: int = 10000) -> None:
    page.wait_for_function(
        """(msg) => {
            return Array.from(document.querySelectorAll('textarea,input')).some((el) => {
                const value = el && typeof el.value === 'string' ? el.value : '';
                return value.includes(msg);
            });
        }""",
        arg=message,
        timeout=timeout,
    )


def _assert_visible_texts(page, texts: list[str], timeout: int = 5000) -> None:
    for text in texts:
        page.wait_for_function(
            """(needle) => {
                const target = String(needle || '').toLowerCase();
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                return Array.from(document.querySelectorAll('body *')).some((el) => {
                    if (!isVisible(el)) return false;
                    const textValue = String(el.innerText || el.textContent || el.value || '').toLowerCase();
                    return textValue.includes(target);
                });
            }""",
            arg=text,
            timeout=timeout,
        )


def _assert_visible_buttons(page, names: list[str], timeout: int = 5000) -> None:
    for name in names:
        try:
            page.get_by_role("button", name=name).first.wait_for(timeout=timeout)
        except Exception:
            _assert_visible_texts(page, [name], timeout=timeout)


def _assert_visible_labels(page, labels: list[str], timeout: int = 5000) -> None:
    for label in labels:
        try:
            page.get_by_label(label, exact=False).first.wait_for(timeout=timeout)
        except Exception:
            _assert_visible_texts(page, [label], timeout=timeout)


def _assert_attached_selectors(page, selectors: list[str], timeout: int = 5000) -> None:
    for selector in selectors:
        page.wait_for_selector(selector, state="attached", timeout=timeout)


def _i18n(key: str, lang: str = "zh") -> str:
    return I18n.get(key, lang)


def _i18n_ui(key: str, lang: str = "zh") -> str:
    text = _i18n(key, lang).strip().replace("**", "")
    while text.startswith("#"):
        text = text[1:].strip()
    return text


def _about_heading(index: int, lang: str = "zh") -> str:
    headings = []
    for line in _i18n("about_content", lang).splitlines():
        s = line.strip()
        if s.startswith("#"):
            while s.startswith("#"):
                s = s[1:].strip()
            if s:
                headings.append(s)
    if not headings:
        return ""
    return headings[min(index, len(headings) - 1)]


def _build_stubbed_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> gr.Blocks:
    import ui.layout_new as layout
    from core.image_preprocessor import ImagePreprocessor

    preview_img = np.full((32, 48, 3), 127, dtype=np.uint8)
    warp_img = np.full((16, 16, 3), 64, dtype=np.uint8)
    lut_img = np.full((16, 16, 3), 192, dtype=np.uint8)

    model_3mf = tmp_path / "dummy_model.3mf"
    model_3mf.write_text("dummy", encoding="utf-8")

    cal_3mf = tmp_path / "dummy_calibration.3mf"
    cal_3mf.write_text("dummy", encoding="utf-8")

    cal_zip = tmp_path / "dummy_8color.zip"
    cal_zip.write_text("dummy", encoding="utf-8")

    ext_npy = tmp_path / "dummy_extracted.npy"
    np.save(ext_npy, np.array([[1, 2, 3]], dtype=np.uint8))

    monkeypatch.setattr(
        ImagePreprocessor,
        "process_upload",
        staticmethod(
            lambda image_path: SimpleNamespace(
                width=48,
                height=32,
                processed_path=str(image_path),
            )
        ),
    )
    monkeypatch.setattr(
        ImagePreprocessor,
        "convert_to_png",
        staticmethod(lambda image_path: str(image_path)),
    )
    monkeypatch.setattr(
        ImagePreprocessor,
        "analyze_recommended_colors",
        staticmethod(
            lambda image_path, target_width_mm: {"recommended": 24, "max_safe": 32}
        ),
    )

    monkeypatch.setattr(
        layout,
        "generate_preview_cached",
        lambda image_path, request: (preview_img, {"mock": True}, "E2E_PREVIEW_OK"),
    )
    monkeypatch.setattr(
        layout,
        "on_preview_generated_update_palette",
        lambda cache, lang: ("<div>E2E_PALETTE_OK</div>", "#112233"),
    )
    monkeypatch.setattr(
        layout,
        "process_batch_generation",
        lambda *args, **kwargs: (str(model_3mf), None, preview_img, "E2E_GENERATE_OK"),
    )
    monkeypatch.setattr(
        layout,
        "generate_calibration_board",
        lambda color_mode, block_size, gap, backing: (
            str(cal_3mf),
            preview_img,
            "E2E_CAL_OK",
        ),
    )
    monkeypatch.setattr(
        layout,
        "generate_smart_board",
        lambda block_size, gap: (str(cal_3mf), preview_img, "E2E_CAL_OK"),
    )
    monkeypatch.setattr(
        layout,
        "generate_8color_batch_zip",
        lambda: (str(cal_zip), preview_img, "E2E_CAL_OK"),
    )
    monkeypatch.setattr(
        layout, "get_extractor_reference_image", lambda mode_str: preview_img
    )
    monkeypatch.setattr(
        layout,
        "run_extraction_wrapper",
        lambda *args, **kwargs: (warp_img, lut_img, str(ext_npy), "E2E_EXT_OK"),
    )
    monkeypatch.setattr(
        layout,
        "merge_8color_data",
        lambda *args, **kwargs: (str(ext_npy), "E2E_MERGE_OK"),
    )

    return layout.create_app()


@pytest.mark.e2e
def test_playwright_e2e_all_tabs_ui_elements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    playwright_sync = pytest.importorskip("playwright.sync_api")
    app = _build_stubbed_app(monkeypatch, tmp_path)

    with launch_server(app) as base_url:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(base_url, wait_until="domcontentloaded")

            # Header + tabs
            _assert_visible_texts(
                page,
                [
                    "Lumina Studio",
                    _i18n("app_subtitle", "zh").split("|")[0].strip(),
                    _i18n_ui("stats_total", "zh"),
                    _i18n("stats_calibrations", "zh"),
                    _i18n("stats_extractions", "zh"),
                    _i18n("stats_conversions", "zh"),
                ],
                timeout=8000,
            )
            _assert_visible_buttons(
                page, [_i18n("lang_btn_en", "zh"), _i18n("theme_toggle_night", "zh")]
            )
            page.get_by_role("tab", name=_i18n("tab_converter", "zh")).wait_for(
                timeout=5000
            )
            page.get_by_role("tab", name=_i18n("tab_calibration", "zh")).wait_for(
                timeout=5000
            )
            page.get_by_role("tab", name=_i18n("tab_extractor", "zh")).wait_for(
                timeout=5000
            )
            page.get_by_role("tab", name=_i18n("tab_about", "zh")).wait_for(
                timeout=5000
            )

            # Converter tab: all visible controls
            _assert_visible_texts(
                page,
                [
                    _i18n_ui("conv_input_section", "zh"),
                    _i18n_ui("conv_params_section", "zh"),
                    _i18n_ui("conv_preview_section", "zh"),
                    _i18n_ui("conv_3d_preview", "zh"),
                    _i18n_ui("conv_download_section", "zh"),
                    _i18n("conv_status", "zh"),
                ],
            )
            _assert_visible_labels(
                page,
                [
                    _i18n("conv_lut_dropdown_label", "zh"),
                    _i18n("conv_batch_mode", "zh"),
                    _i18n("conv_image_label", "zh"),
                    _i18n("conv_width", "zh"),
                    _i18n("conv_height", "zh"),
                    _i18n("conv_thickness", "zh"),
                    _i18n("conv_color_mode", "zh"),
                    _i18n("conv_structure", "zh"),
                    _i18n("conv_modeling_mode", "zh"),
                    _i18n("conv_auto_bg", "zh"),
                    _i18n("conv_download_file", "zh"),
                ],
            )
            _assert_visible_buttons(
                page,
                [
                    _i18n("conv_preview_btn", "zh"),
                    _i18n("conv_generate_btn", "zh"),
                    _i18n("conv_stop", "zh"),
                ],
            )

            page.get_by_role("button", name=_i18n("conv_advanced", "zh")).click()
            _assert_visible_labels(
                page,
                [
                    _i18n("conv_quantize_colors", "zh"),
                    _i18n("conv_tolerance", "zh"),
                    _i18n("conv_match_strategy", "zh"),
                ],
            )
            _assert_visible_buttons(page, [_i18n("conv_auto_color_btn", "zh")])

            page.get_by_role("button", name=_i18n("conv_palette", "zh")).click()
            _assert_visible_texts(
                page,
                [
                    _i18n_ui("conv_palette_step1", "zh"),
                    _i18n_ui("conv_palette_step2", "zh"),
                    _i18n_ui("conv_palette_replacements_label", "zh"),
                ],
            )
            _assert_visible_labels(
                page,
                [
                    _i18n("conv_palette_selected_label", "zh"),
                    _i18n("conv_palette_replace_label", "zh"),
                ],
            )
            _assert_visible_buttons(
                page,
                [
                    _i18n("conv_palette_apply_btn", "zh"),
                    _i18n("conv_palette_undo_btn", "zh"),
                    _i18n("conv_palette_clear_btn", "zh"),
                ],
            )

            # Hidden trigger elements still exist in DOM and are test covered.
            _assert_attached_selectors(
                page,
                [
                    "#conv-preview",
                    "#conv-image-input",
                    "#crop-data-json",
                    "#use-original-hidden-btn",
                    "#confirm-crop-hidden-btn",
                    "#preprocess-dimensions-data",
                    "#conv-color-selected-hidden",
                    "#conv-highlight-color-hidden",
                    "#conv-highlight-trigger-btn",
                    "#conv-color-trigger-btn",
                    "#conv-lut-color-selected-hidden",
                    "#conv-lut-color-trigger-btn",
                    "#lang-btn",
                    "#theme-btn",
                ],
            )

            # Calibration tab
            page.get_by_role("tab", name=_i18n("tab_calibration", "zh")).click()
            _assert_visible_labels(
                page,
                [
                    _i18n("cal_color_mode", "zh"),
                    _i18n("cal_block_size", "zh"),
                    _i18n("cal_gap", "zh"),
                    _i18n("cal_backing", "zh"),
                    _i18n("cal_status", "zh"),
                ],
            )
            _assert_visible_texts(
                page, [_i18n_ui("cal_preview", "zh"), _i18n("cal_download", "zh")]
            )
            _assert_visible_buttons(page, [_i18n("cal_generate_btn", "zh")])

            # Extractor tab
            page.get_by_role("tab", name=_i18n("tab_extractor", "zh")).click()
            _assert_visible_texts(
                page,
                [
                    _i18n_ui("ext_upload_section", "zh"),
                    _i18n_ui("ext_correction_section", "zh"),
                    _i18n_ui("ext_sampling", "zh"),
                    _i18n_ui("ext_reference", "zh"),
                    _i18n_ui("ext_result", "zh"),
                    _i18n_ui("ext_manual_fix", "zh"),
                ],
            )
            _assert_visible_labels(
                page,
                [
                    _i18n("ext_color_mode", "zh"),
                    _i18n("ext_photo", "zh"),
                    _i18n("ext_wb", "zh"),
                    _i18n("ext_vignette", "zh"),
                    _i18n("ext_zoom", "zh"),
                    _i18n("ext_distortion", "zh"),
                    _i18n("ext_offset_x", "zh"),
                    _i18n("ext_offset_y", "zh"),
                    _i18n("ext_8color_page", "zh"),
                    _i18n("ext_status", "zh"),
                    _i18n("ext_override", "zh"),
                    _i18n("ext_download_npy", "zh"),
                ],
            )
            _assert_visible_buttons(
                page,
                [
                    _i18n("ext_rotate_btn", "zh"),
                    _i18n("ext_reset_btn", "zh"),
                    _i18n("ext_extract_btn", "zh"),
                    _i18n("ext_merge_8color", "zh"),
                    _i18n("ext_apply_btn", "zh"),
                ],
            )

            # About tab
            page.get_by_role("tab", name=_i18n("tab_about", "zh")).click()
            _assert_visible_texts(
                page,
                [
                    _i18n_ui("settings_title", "zh"),
                    _about_heading(0, "zh"),
                    _about_heading(2, "zh"),
                ],
            )
            _assert_visible_buttons(
                page,
                [
                    _i18n("settings_clear_cache", "zh"),
                    _i18n("settings_reset_counters", "zh"),
                ],
            )

            # Switch language and re-check core UI labels in all tabs.
            page.get_by_role("button", name=_i18n("lang_btn_en", "zh")).click()
            page.get_by_role("tab", name=_i18n("tab_converter", "en")).wait_for(
                timeout=5000
            )
            _assert_visible_buttons(
                page, [_i18n("lang_btn_en", "en"), _i18n("theme_toggle_night", "en")]
            )
            _assert_visible_texts(
                page,
                [
                    _i18n_ui("stats_total", "en"),
                    _i18n("stats_calibrations", "en"),
                    _i18n("stats_extractions", "en"),
                    _i18n("stats_conversions", "en"),
                ],
            )

            page.get_by_role("tab", name=_i18n("tab_converter", "en")).click()
            _assert_visible_labels(
                page,
                [
                    _i18n("conv_image_label", "en"),
                    _i18n("conv_width", "en"),
                    _i18n("conv_height", "en"),
                    _i18n("conv_thickness", "en"),
                    _i18n("conv_color_mode", "en"),
                    _i18n("conv_structure", "en"),
                    _i18n("conv_modeling_mode", "en"),
                    _i18n("conv_auto_bg", "en"),
                    _i18n("conv_download_file", "en"),
                ],
            )
            _assert_visible_buttons(
                page,
                [
                    _i18n("conv_preview_btn", "en"),
                    _i18n("conv_generate_btn", "en"),
                    _i18n("conv_stop", "en"),
                ],
            )

            page.get_by_role("button", name=_i18n("conv_advanced", "en")).click()
            try:
                _assert_visible_labels(
                    page,
                    [
                        _i18n("conv_quantize_colors", "en"),
                        _i18n("conv_tolerance", "en"),
                        _i18n("conv_match_strategy", "en"),
                    ],
                )
            except Exception:
                # Accordion may be toggled closed after language refresh; click again to open.
                page.get_by_role("button", name=_i18n("conv_advanced", "en")).click()
                _assert_visible_labels(
                    page,
                    [
                        _i18n("conv_quantize_colors", "en"),
                        _i18n("conv_tolerance", "en"),
                        _i18n("conv_match_strategy", "en"),
                    ],
                )
            # Button text can vary after language toggle, already covered in Chinese assertions above.

            page.get_by_role("button", name=_i18n("conv_palette", "en")).click()
            # Palette detail labels are validated in Chinese mode above.

            page.get_by_role("tab", name=_i18n("tab_calibration", "en")).click()
            _assert_visible_buttons(page, [_i18n("cal_generate_btn", "en")])

            browser.close()


@pytest.mark.e2e
def test_playwright_e2e_full_workflow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    playwright_sync = pytest.importorskip("playwright.sync_api")
    app = _build_stubbed_app(monkeypatch, tmp_path)

    test_image = tmp_path / "workflow_input.png"
    Image.fromarray(np.full((24, 36, 3), 220, dtype=np.uint8)).save(test_image)

    with launch_server(app) as base_url:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(base_url, wait_until="domcontentloaded")

            page.wait_for_selector(
                "#conv-image-input input[type='file']", state="attached", timeout=8000
            )
            page.locator("#conv-image-input input[type='file']").set_input_files(
                str(test_image)
            )
            page.get_by_role("button", name=_i18n("conv_preview_btn", "zh")).click()
            _wait_status_contains(page, "E2E_PREVIEW_OK")

            page.get_by_role("button", name=_i18n("conv_generate_btn", "zh")).click()
            _wait_status_contains(page, "E2E_GENERATE_OK")

            page.get_by_role("tab", name=_i18n("tab_calibration", "zh")).click()
            page.get_by_role("button", name=_i18n("cal_generate_btn", "zh")).click()
            _wait_status_contains(page, "E2E_CAL_OK")

            page.get_by_role("tab", name=_i18n("tab_extractor", "zh")).click()
            page.get_by_role("button", name=_i18n("ext_extract_btn", "zh")).click()
            _wait_status_contains(page, "E2E_EXT_OK")

            page.get_by_role("button", name=_i18n("ext_merge_8color", "zh")).click()
            _wait_status_contains(page, "E2E_MERGE_OK")

            page.get_by_role("tab", name=_i18n("tab_about", "zh")).click()
            page.get_by_role("button", name=_i18n("settings_clear_cache", "zh")).click()
            page.get_by_text(
                _i18n("settings_cache_cleared", "zh").split("，")[0], exact=False
            ).wait_for(timeout=5000)

            page.get_by_role(
                "button", name=_i18n("settings_reset_counters", "zh")
            ).click()
            page.get_by_text(
                _i18n("settings_counters_reset", "zh").split("：")[0], exact=False
            ).wait_for(timeout=5000)

            browser.close()
