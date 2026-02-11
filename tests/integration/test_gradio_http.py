from contextlib import contextmanager
import socket

import pytest

pytest.importorskip("gradio")
import gradio as gr

requests = pytest.importorskip("requests")


@contextmanager
def launch_server(demo: gr.Blocks):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])

    app, local_url, _ = demo.launch(
        prevent_thread_lock=True,
        server_name="127.0.0.1",
        server_port=port,
        show_error=True,
    )
    try:
        yield app, local_url
    finally:
        demo.close()


@pytest.mark.integration
def test_http_call_endpoint_roundtrip():
    def echo(text: str) -> str:
        return text.upper()

    demo = gr.Interface(fn=echo, inputs="text", outputs="text", api_name="echo")

    with launch_server(demo) as (_, base_url):
        # Gradio 6 serves HTTP call endpoints under /gradio_api/call/*
        post_resp = requests.post(
            f"{base_url}gradio_api/call/echo",
            json={"data": ["lumina"]},
            timeout=10,
        )
        assert post_resp.status_code == 200
        payload = post_resp.json()
        assert "event_id" in payload

        get_resp = requests.get(
            f"{base_url}gradio_api/call/echo/{payload['event_id']}",
            timeout=15,
        )
        assert get_resp.status_code == 200
        assert "event:" in get_resp.text
