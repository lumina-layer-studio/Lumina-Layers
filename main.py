"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                          LUMINA STUDIO v1.5.7                                 ║
║                    Multi-Material 3D Print Color System                       ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Author: [MIN]                                                                ║
║  License: CC BY-NC-SA 4.0                                                     ║
╚═══════════════════════════════════════════════════════════════════════════════╝

Main Entry Point
"""

import os
from pathlib import Path

# Colormath compatibility with numpy 1.20+ (run before other imports).
import numpy as np


def patch_asscalar(a):
    """Replace deprecated numpy.asscalar for colormath."""
    return a.item()


setattr(np, "asscalar", patch_asscalar)

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_GRADIO_TEMP = os.path.join(_PROJECT_ROOT, "output", ".gradio_cache")
os.makedirs(_GRADIO_TEMP, exist_ok=True)
os.environ["GRADIO_TEMP_DIR"] = _GRADIO_TEMP
import sys
import time
import threading
import webbrowser
import socket
import gradio as gr  # type:ignore
from gradio.themes import Soft
from ui.layout_new import create_app

HAS_DISPLAY = os.environ.get("DISPLAY") or os.name == "nt"
LuminaTray = None
if HAS_DISPLAY:
    try:
        from core.tray import LuminaTray
    except ImportError:
        HAS_DISPLAY = False


def find_available_port(start_port=7860, max_attempts=1000):
    """Return first free port in [start_port, start_port + max_attempts)."""
    import socket

    for i in range(max_attempts):
        port = start_port + i
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"No available port found after {max_attempts} attempts")


def start_browser(port):
    """Launch the default web browser after a short delay."""
    time.sleep(2)
    webbrowser.open(f"http://127.0.0.1:{port}")


if __name__ == "__main__":
    tray = None
    PORT = 7860
    try:
        PORT = find_available_port(7860)
        if LuminaTray is not None:
            tray = LuminaTray(port=PORT)
    except Exception as e:
        print(f"⚠️ Warning: Failed to initialize tray: {e}")

    threading.Thread(target=start_browser, args=(PORT,), daemon=True).start()
    print(f"✨ Lumina Studio is running on http://127.0.0.1:{PORT}")
    app = create_app()

    try:
        # Import crop extension for head HTML injection
        from ui.crop_extension import get_crop_head_html

        gr.set_static_paths(paths=[Path(_PROJECT_ROOT) / "ui" / "static"])

        app.launch(
            inbrowser=False,
            server_name="0.0.0.0",
            server_port=PORT,
            show_error=True,
            prevent_thread_lock=True,
            favicon_path="icon.ico" if os.path.exists("icon.ico") else None,
            css_paths=[
                str(Path(_PROJECT_ROOT) / "ui" / "static" / "css" / "app_layout.css"),
                str(Path(_PROJECT_ROOT)/ "ui"/ "static"/ "css"/ "lut_interaction.css"),
            ],
            theme=Soft(),
            head=get_crop_head_html(),
        )
    except Exception as e:
        raise
    except BaseException as e:
        raise

    if tray:
        try:
            print("🚀 Starting System Tray...")
            tray.run()
        except Exception as e:
            print(f"⚠️ Warning: System tray crashed: {e}")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    else:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    print("Stopping...")
    os._exit(0)
