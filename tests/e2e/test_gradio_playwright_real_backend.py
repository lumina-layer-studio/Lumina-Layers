from contextlib import contextmanager
from pathlib import Path
import socket

import pytest

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


def _wait_status_contains(page, message: str, timeout: int = 120000) -> None:
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


def _pick_real_image(repo_root: Path) -> Path | None:
    candidates = [
        repo_root / "example" / "any002.png",
        repo_root / "lut-npy预设" / "bambulab" / "bambulab_pla_basic_cmyw_sample.png",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _pick_real_lut(repo_root: Path) -> Path | None:
    candidates = [
        repo_root / "lut-npy预设" / "bambulab" / "bambulab_pla_basic_cmyw.npy",
        repo_root / "lut-npy预设" / "bambulab" / "bambulab_pla_basic_cmyw_new.npy",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


@pytest.mark.e2e
@pytest.mark.slow
def test_playwright_real_backend_converter_workflow_no_mock():
    playwright_sync = pytest.importorskip("playwright.sync_api")

    repo_root = Path(__file__).resolve().parents[2]
    image_path = _pick_real_image(repo_root)
    lut_path = _pick_real_lut(repo_root)

    if image_path is None:
        pytest.skip("No real image asset found (expected example/any002.png)")
    if lut_path is None:
        pytest.skip("No real LUT asset found under lut-npy预设/bambulab")

    from ui.layout_new import create_app

    app = create_app()

    with launch_server(app) as base_url:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(base_url, wait_until="domcontentloaded")

            page.locator(".tall-upload input[type='file']").first.set_input_files(
                str(lut_path)
            )
            page.locator("#conv-image-input input[type='file']").first.set_input_files(
                str(image_path)
            )

            page.get_by_role("button", name="👁️ 生成预览").click()
            _wait_status_contains(page, "✅ Preview", timeout=180000)

            page.get_by_role("button", name="🚀 生成3MF").click()
            _wait_status_contains(page, "✅ Conversion complete", timeout=300000)

            browser.close()
