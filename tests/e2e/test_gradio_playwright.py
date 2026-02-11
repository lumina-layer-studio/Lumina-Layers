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

            page.get_by_text("Lumina Studio", exact=False).first.wait_for(timeout=8000)
            page.get_by_role("tab", name="💎 图像转换").wait_for(timeout=5000)
            page.get_by_role("button", name="👁️ 生成预览").wait_for(timeout=5000)
            page.get_by_role("button", name="🚀 生成3MF").wait_for(timeout=5000)
            page.get_by_role("button", name="🛑 停止生成").wait_for(timeout=5000)

            page.get_by_role("tab", name="📐 校准板生成").click()
            page.get_by_role("button", name="🚀 生成").wait_for(timeout=5000)
            page.get_by_text("色块尺寸 (mm)", exact=False).wait_for(timeout=5000)

            page.get_by_role("tab", name="🎨 颜色提取").click()
            page.get_by_role("button", name="🚀 提取").wait_for(timeout=5000)
            page.get_by_role("button", name="Merge 8-Color").wait_for(timeout=5000)

            page.get_by_role("tab", name="ℹ️ 关于").click()
            page.get_by_role("button", name="🗑️ 清空缓存").wait_for(timeout=5000)
            page.get_by_role("button", name="🔢 使用计数归零").wait_for(timeout=5000)

            page.get_by_role("button", name="🌐 English").click()
            page.get_by_role("tab", name="💎 Image Converter").wait_for(timeout=5000)

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


            browser.close()
