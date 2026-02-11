import pytest

pytest.importorskip("gradio")

import gradio as gr

from ui.layout_new import create_app


@pytest.mark.integration
def test_create_app_returns_blocks():
    app = create_app()
    assert isinstance(app, gr.Blocks)
