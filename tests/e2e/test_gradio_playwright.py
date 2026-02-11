from contextlib import contextmanager
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


@pytest.mark.e2e
def test_playwright_e2e_text_submit():
    playwright_sync = pytest.importorskip("playwright.sync_api")

    def echo(text: str) -> str:
        return f"PW:{text}"

    demo = gr.Interface(fn=echo, inputs="text", outputs="text", api_name="echo")

    with launch_server(demo) as base_url:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(base_url, wait_until="domcontentloaded")

            page.wait_for_selector("textarea", timeout=5000)
            textareas = page.locator("textarea")
            input_box = textareas.nth(0)
            output_box = textareas.nth(1)

            input_box.fill("hello")
            page.get_by_role("button", name="Submit").first.click()
            page.wait_for_function(
                "() => { const els = document.querySelectorAll('textarea'); return els.length > 1 && els[1].value.includes('PW:hello'); }",
                timeout=8000,
            )

            result = output_box.input_value()
            browser.close()
            assert "PW:hello" in result
