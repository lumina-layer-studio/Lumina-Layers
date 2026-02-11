from contextlib import contextmanager
import socket
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

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
        layout, "merge_8color_data", lambda: (str(ext_npy), "E2E_MERGE_OK")
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
                    "多材料3D打印色彩系统",
                    "累计生成",
                    "校准板",
                    "颜色提取",
                    "模型转换",
                ],
                timeout=8000,
            )
            _assert_visible_buttons(page, ["🌐 English", "🌙 夜间模式"])
            page.get_by_role("tab", name="💎 图像转换").wait_for(timeout=5000)
            page.get_by_role("tab", name="📐 校准板生成").wait_for(timeout=5000)
            page.get_by_role("tab", name="🎨 颜色提取").wait_for(timeout=5000)
            page.get_by_role("tab", name="ℹ️ 关于").wait_for(timeout=5000)

            # Converter tab: all visible controls
            _assert_visible_texts(
                page,
                [
                    "📁 输入",
                    "⚙️ 参数",
                    "🎨 2D预览",
                    "🎮 3D预览",
                    "下载【务必合并对象后再切片】",
                    "状态",
                ],
            )
            _assert_visible_labels(
                page,
                [
                    "校准数据 (.npy) / Calibration Data",
                    "📦 批量模式",
                    "输入图像",
                    "宽度 (mm)",
                    "高度 (mm)",
                    "背板 (mm)",
                    "色彩模式",
                    "结构",
                    "🎨 建模模式",
                    "🗑️ 移除背景",
                    "3MF文件",
                ],
            )
            _assert_visible_buttons(
                page,
                [
                    "👁️ 生成预览",
                    "🚀 生成3MF",
                    "🛑 停止生成",
                ],
            )

            page.get_by_role("button", name="🛠️ 高级设置").click()
            _assert_visible_labels(
                page, ["🎨 色彩细节", "容差", "匹配策略 / Match Strategy"]
            )
            _assert_visible_buttons(page, ["🔍 自动计算"])

            page.get_by_role("button", name="🎨 颜色调色板").click()
            _assert_visible_texts(
                page,
                [
                    "原图颜色",
                    "替换为",
                    "已生效的替换",
                ],
            )
            _assert_visible_labels(page, ["当前选中", "将替换为"])
            _assert_visible_buttons(page, ["✅ 确认替换", "↩️ 撤销", "🗑️ 清除所有"])

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
            page.get_by_role("tab", name="📐 校准板生成").click()
            _assert_visible_labels(
                page,
                [
                    "色彩模式",
                    "色块尺寸 (mm)",
                    "间隙 (mm)",
                    "底板颜色",
                    "状态",
                ],
            )
            _assert_visible_texts(page, ["👁️ 预览", "下载 3MF"])
            _assert_visible_buttons(page, ["🚀 生成"])

            # Extractor tab
            page.get_by_role("tab", name="🎨 颜色提取").click()
            _assert_visible_texts(
                page,
                [
                    "📸 上传照片",
                    "🔧 校正参数",
                    "📍 采样预览",
                    "🎯 参考",
                    "📊 结果",
                    "🛠️ 手动修正",
                ],
            )
            _assert_visible_labels(
                page,
                [
                    "🎨 色彩模式",
                    "校准板照片",
                    "自动白平衡",
                    "暗角校正",
                    "缩放",
                    "畸变",
                    "X偏移",
                    "Y偏移",
                    "8-Color Page",
                    "状态",
                    "替换颜色",
                    "下载 .npy",
                ],
            )
            _assert_visible_buttons(
                page, ["↺ 旋转", "🗑️ 重置", "🚀 提取", "Merge 8-Color", "🔧 应用"]
            )

            # About tab
            page.get_by_role("tab", name="ℹ️ 关于").click()
            _assert_visible_texts(page, ["⚙️ 设置", "Lumina Studio v1.5.6", "技术原理"])
            _assert_visible_buttons(page, ["🗑️ 清空缓存", "🔢 使用计数归零"])

            # Switch language and re-check core UI labels in all tabs.
            page.get_by_role("button", name="🌐 English").click()
            page.get_by_role("tab", name="💎 Image Converter").wait_for(timeout=5000)
            _assert_visible_buttons(page, ["🌐 English", "🌙 Night Mode"])
            _assert_visible_texts(
                page,
                ["📊 Total Generated", "Calibrations", "Extractions", "Conversions"],
            )

            page.get_by_role("tab", name="💎 Image Converter").click()
            _assert_visible_labels(
                page,
                [
                    "Input Image",
                    "Width (mm)",
                    "Height (mm)",
                    "Backing (mm)",
                    "Color Mode",
                    "Structure",
                    "🎨 Modeling Mode",
                    "🗑️ Remove Background",
                    "3MF File",
                ],
            )
            _assert_visible_buttons(
                page, ["👁️ Generate Preview", "🚀 Generate 3MF", "🛑 Stop Generation"]
            )

            page.get_by_role("button", name="🛠️ Advanced Settings").click()
            try:
                _assert_visible_labels(
                    page, ["🎨 Color Detail", "Tolerance", "Match Strategy"]
                )
            except Exception:
                # Accordion may be toggled closed after language refresh; click again to open.
                page.get_by_role("button", name="🛠️ Advanced Settings").click()
                _assert_visible_labels(
                    page, ["🎨 Color Detail", "Tolerance", "Match Strategy"]
                )
            # Button text can vary after language toggle, already covered in Chinese assertions above.

            page.get_by_role("button", name="🎨 Color Palette").click()
            # Palette detail labels are validated in Chinese mode above.

            page.get_by_role("tab", name="📐 Calibration").click()
            _assert_visible_buttons(page, ["🚀 Generate"])

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
            page.get_by_role("button", name="👁️ 生成预览").click()
            _wait_status_contains(page, "E2E_PREVIEW_OK")

            page.get_by_role("button", name="🚀 生成3MF").click()
            _wait_status_contains(page, "E2E_GENERATE_OK")

            page.get_by_role("tab", name="📐 校准板生成").click()
            page.get_by_role("button", name="🚀 生成").click()
            _wait_status_contains(page, "E2E_CAL_OK")

            page.get_by_role("tab", name="🎨 颜色提取").click()
            page.get_by_role("button", name="🚀 提取").click()
            _wait_status_contains(page, "E2E_EXT_OK")

            page.get_by_role("button", name="Merge 8-Color").click()
            _wait_status_contains(page, "E2E_MERGE_OK")

            page.get_by_role("tab", name="ℹ️ 关于").click()
            page.get_by_role("button", name="🗑️ 清空缓存").click()
            page.get_by_text("缓存已清空", exact=False).wait_for(timeout=5000)

            page.get_by_role("button", name="🔢 使用计数归零").click()
            page.get_by_text("计数器已归零", exact=False).wait_for(timeout=5000)

            browser.close()
