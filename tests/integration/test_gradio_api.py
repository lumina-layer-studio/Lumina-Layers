from contextlib import contextmanager
import socket

import pytest

pytest.importorskip("gradio")
import gradio as gr


gradio_client = pytest.importorskip("gradio_client")
Client = gradio_client.Client


@contextmanager
def launch_client(demo: gr.Blocks):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])

    _, local_url, _ = demo.launch(
        prevent_thread_lock=True,
        server_name="127.0.0.1",
        server_port=port,
        show_error=True,
    )
    client = Client(local_url)
    try:
        yield client
    finally:
        client.close()
        demo.close()


@pytest.mark.integration
def test_gradio_client_predict_roundtrip():
    def echo(text: str) -> str:
        return f"echo:{text}"

    demo = gr.Interface(fn=echo, inputs="text", outputs="text", api_name="echo")

    with launch_client(demo) as client:
        info = client.view_api(return_format="dict")
        assert "/echo" in info["named_endpoints"]
        result = client.predict("hello", api_name="/echo")
        assert result == "echo:hello"
