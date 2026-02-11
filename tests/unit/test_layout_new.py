import json
import ast
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from ui import layout_new


def _parse_layout_new_ast() -> ast.Module:
    source = (Path(__file__).resolve().parents[2] / "ui" / "layout_new.py").read_text(
        encoding="utf-8"
    )
    return ast.parse(source)


def _find_create_app_func(module_ast: ast.Module) -> ast.FunctionDef:
    for node in module_ast.body:
        if isinstance(node, ast.FunctionDef) and node.name == "create_app":
            return node
    raise AssertionError("create_app not found in ui/layout_new.py")


def _extract_tab_label_calls(create_app_func: ast.FunctionDef) -> list[ast.AST]:
    labels: list[ast.AST] = []
    for node in ast.walk(create_app_func):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            ctx = item.context_expr
            if not (
                isinstance(ctx, ast.Call)
                and isinstance(ctx.func, ast.Attribute)
                and isinstance(ctx.func.value, ast.Name)
                and ctx.func.value.id == "gr"
                and ctx.func.attr == "TabItem"
            ):
                continue
            for kw in ctx.keywords:
                if kw.arg == "label":
                    labels.append(kw.value)
    return labels


def _is_i18n_get_call(expr: ast.AST, text_key: str) -> bool:
    if not (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and isinstance(expr.func.value, ast.Name)
        and expr.func.value.id == "I18n"
        and expr.func.attr == "get"
        and len(expr.args) >= 2
    ):
        return False
    return (
        isinstance(expr.args[0], ast.Constant)
        and expr.args[0].value == text_key
        and isinstance(expr.args[1], ast.Constant)
        and expr.args[1].value == "zh"
    )


@pytest.fixture
def temp_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = tmp_path / "user_settings.json"
    monkeypatch.setattr(layout_new, "CONFIG_FILE", str(config_path))
    return config_path


@pytest.fixture
def sample_png_path(tmp_path: Path) -> Path:
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (120, 80), color=(10, 20, 30)).save(image_path)
    return image_path


@pytest.fixture
def mock_i18n_get(monkeypatch: pytest.MonkeyPatch):
    def _fake_get(key: str, lang: str) -> str:
        return f"{key}:{lang}"

    monkeypatch.setattr(layout_new.I18n, "get", staticmethod(_fake_get))
    return _fake_get


@pytest.mark.unit
def test_helper_load_last_lut_setting_returns_config_value(temp_config_path: Path):
    """读取已有配置时，应返回 last_lut 值。"""
    temp_config_path.write_text('{"last_lut": "demo_lut"}', encoding="utf-8")

    result = layout_new.load_last_lut_setting()

    assert result == "demo_lut"


@pytest.mark.unit
def test_helper_load_last_lut_setting_returns_none_when_file_missing(
    temp_config_path: Path,
):
    """配置文件不存在时，应返回 None。"""
    result = layout_new.load_last_lut_setting()
    assert result is None


@pytest.mark.unit
def test_helper_load_last_lut_setting_returns_none_for_invalid_json(
    temp_config_path: Path,
):
    """配置文件损坏时，应降级返回 None。"""
    temp_config_path.write_text("{invalid-json", encoding="utf-8")

    result = layout_new.load_last_lut_setting()

    assert result is None


@pytest.mark.unit
def test_helper_save_last_lut_setting_writes_new_config(temp_config_path: Path):
    """保存 LUT 时，应创建配置并写入 last_lut。"""
    layout_new.save_last_lut_setting("new_lut")

    data = json.loads(temp_config_path.read_text(encoding="utf-8"))
    assert data["last_lut"] == "new_lut"


@pytest.mark.unit
def test_helper_save_last_lut_setting_preserves_existing_keys(temp_config_path: Path):
    """保存 LUT 时，应保留配置中的其他键。"""
    temp_config_path.write_text(
        json.dumps({"theme": "dark", "last_lut": "old"}), encoding="utf-8"
    )

    layout_new.save_last_lut_setting("updated_lut")

    data = json.loads(temp_config_path.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    assert data["last_lut"] == "updated_lut"


@pytest.mark.unit
def test_helper_save_last_lut_setting_write_error_is_swallowed(
    temp_config_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """写入失败时，函数应吞掉异常而不是抛出。"""
    original_open = open

    def _raise_on_write(path, mode="r", *args, **kwargs):
        if Path(path) == temp_config_path and "w" in mode:
            raise PermissionError("write denied")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _raise_on_write)

    layout_new.save_last_lut_setting("cannot_write")


@pytest.mark.unit
def test_helper_get_image_size_reads_file_path(sample_png_path: Path):
    """传入图片路径时，应返回 (width, height)。"""
    assert layout_new._get_image_size(str(sample_png_path)) == (120, 80)


@pytest.mark.unit
def test_helper_get_image_size_reads_numpy_array_shape():
    """传入 numpy 图像数组时，应返回 (W, H)。"""
    arr = np.zeros((33, 55, 3), dtype=np.uint8)
    assert layout_new._get_image_size(arr) == (55, 33)


@pytest.mark.unit
def test_helper_get_image_size_returns_none_for_missing_file(tmp_path: Path):
    """文件路径不存在时，应返回 None。"""
    missing = tmp_path / "missing.png"
    assert layout_new._get_image_size(str(missing)) is None


@pytest.mark.unit
def test_helper_get_extractor_reference_image_uses_cached_file(temp_cwd: Path):
    """缓存参考图存在时，应直接读取缓存文件。"""
    assets = temp_cwd / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    cache_path = assets / "ref_cmyw_standard.png"
    Image.new("RGB", (16, 16), color=(1, 2, 3)).save(cache_path)

    img = layout_new.get_extractor_reference_image("CMYW")

    assert isinstance(img, Image.Image)
    assert img.size == (16, 16)


@pytest.mark.unit
def test_helper_get_extractor_reference_image_generates_and_saves_cmyw(
    temp_cwd: Path, monkeypatch: pytest.MonkeyPatch
):
    """无缓存时，应调用生成逻辑并落盘缓存。"""
    import core.calibration as calibration

    def _fake_generate_calibration_board(mode, block_size, gap, backing):
        img = Image.new("RGB", (20, 12), color=(200, 0, 0))
        return None, img, None

    monkeypatch.setattr(
        calibration,
        "generate_calibration_board",
        _fake_generate_calibration_board,
    )

    img = layout_new.get_extractor_reference_image("CMYW")
    cache_file = temp_cwd / "assets" / "ref_cmyw_standard.png"

    assert isinstance(img, Image.Image)
    assert img.size == (20, 12)
    assert cache_file.exists()


@pytest.mark.unit
def test_helper_get_extractor_reference_image_returns_none_on_generate_error(
    temp_cwd: Path, monkeypatch: pytest.MonkeyPatch
):
    """生成流程异常时，应返回 None。"""
    import core.calibration as calibration

    def _raise_generate(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(calibration, "generate_calibration_board", _raise_generate)

    result = layout_new.get_extractor_reference_image("CMYW")

    assert result is None


@pytest.mark.unit
def test_layout_new_app_structure_has_tabs_in_expected_order():
    module_ast = _parse_layout_new_ast()
    create_app_func = _find_create_app_func(module_ast)

    labels = _extract_tab_label_calls(create_app_func)
    assert len(labels) == 4

    expected_keys = [
        "tab_converter",
        "tab_calibration",
        "tab_extractor",
        "tab_about",
    ]
    for expected_key, actual_label in zip(expected_keys, labels):
        assert _is_i18n_get_call(actual_label, expected_key)


@pytest.mark.unit
def test_layout_new_app_structure_has_language_and_settings_handlers():
    module_ast = _parse_layout_new_ast()
    create_app_func = _find_create_app_func(module_ast)
    inner_fn_names = {
        node.name
        for node in ast.walk(create_app_func)
        if isinstance(node, ast.FunctionDef) and node is not create_app_func
    }

    assert "change_language" in inner_fn_names
    assert "on_clear_cache" in inner_fn_names
    assert "on_reset_counters" in inner_fn_names


@pytest.mark.unit
def test_layout_new_app_structure_wires_core_click_events():
    module_ast = _parse_layout_new_ast()
    create_app_func = _find_create_app_func(module_ast)

    click_calls = [
        node
        for node in ast.walk(create_app_func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "click"
    ]

    has_change_language_wiring = any(
        call.args
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "change_language"
        for call in click_calls
    )

    click_keyword_fns = [
        kw.value.id
        for call in click_calls
        for kw in call.keywords
        if kw.arg == "fn" and isinstance(kw.value, ast.Name)
    ]

    assert has_change_language_wiring
    assert "on_clear_cache" in click_keyword_fns
    assert "on_reset_counters" in click_keyword_fns
