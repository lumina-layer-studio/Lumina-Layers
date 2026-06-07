import re

from ui.layout_new import CUSTOM_TAB_HEAD_JS, HEADER_CSS, create_app


def test_header_css_shows_converter_by_default_and_hides_other_tabs():
    assert re.search(
        r"#tab-content-calibration,\s*#tab-content-extractor,\s*#tab-content-merge,\s*#tab-content-5color,\s*#tab-content-settings\s*\{\s*display:\s*none;",
        HEADER_CSS,
        re.S,
    )
    assert re.search(
        r"#tab-content-converter\s*\{\s*display:\s*block;",
        HEADER_CSS,
        re.S,
    )


def test_custom_tab_js_explicitly_switches_active_content_display():
    assert 'content.style.display = isActive ? "block" : "none";' in CUSTOM_TAB_HEAD_JS
    assert 'window.luminaSwitchTab("converter");' in CUSTOM_TAB_HEAD_JS
    assert 'window.requestAnimationFrame(function() {' in CUSTOM_TAB_HEAD_JS


def test_create_app_registers_all_custom_tab_ids():
    app = create_app()
    config = app.get_config_file()

    expected_ids = {
        "tab-btn-converter",
        "tab-btn-calibration",
        "tab-btn-extractor",
        "tab-btn-merge",
        "tab-btn-5color",
        "tab-btn-settings",
        "tab-content-converter",
        "tab-content-calibration",
        "tab-content-extractor",
        "tab-content-merge",
        "tab-content-5color",
        "tab-content-settings",
    }

    found_ids = {
        comp.get("props", {}).get("elem_id")
        for comp in config.get("components", [])
        if comp.get("props", {}).get("elem_id") in expected_ids
    }

    assert found_ids == expected_ids


def test_create_app_marks_converter_tab_selected_by_default():
    app = create_app()
    config = app.get_config_file()

    converter_button = next(
        comp
        for comp in config.get("components", [])
        if comp.get("props", {}).get("elem_id") == "tab-btn-converter"
    )

    assert "selected" in converter_button["props"]["elem_classes"]


def test_create_app_injects_dropdown_scroll_fix_script():
    app = create_app()
    config = app.get_config_file()

    html_values = [
        comp.get("props", {}).get("value", "")
        for comp in config.get("components", [])
        if comp.get("type") == "html"
    ]

    assert any("window.__luminaDropdownScrollFix" in value for value in html_values)


def test_legacy_saved_converter_color_mode_is_normalized(monkeypatch):
    monkeypatch.setattr(
        "ui.layout_new._load_user_settings",
        lambda: {"last_color_mode": "4-Color"},
    )

    app = create_app()
    config = app.get_config_file()

    color_mode_dropdown = next(
        comp
        for comp in config.get("components", [])
        if comp.get("type") == "dropdown"
        and comp.get("props", {}).get("label") == "色彩模式"
    )

    assert color_mode_dropdown["props"]["value"] == "RYBW"
