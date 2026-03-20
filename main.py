#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                          LUMINA STUDIO v1.6.3                                 ║
║                    Multi-Material 3D Print Color System                       ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Copyright (C) 2025 Lumina Studio Contributors                                ║
║  License: GNU GPL v3.0                                                        ║
╚═══════════════════════════════════════════════════════════════════════════════╝

Main Entry Point
"""

import os
import sys
import signal
import numpy as np
import re
import multiprocessing as mp
from datetime import datetime


def patch_asscalar(a):
    """Replace deprecated numpy.asscalar for colormath."""
    return a.item()

setattr(np, "asscalar", patch_asscalar)

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


class _Tee:
    def __init__(self, log_path, console_stream=None, lock=None):
        self._console = console_stream if console_stream is not None else sys.__stdout__
        self._file = open(log_path, 'a', encoding='utf-8', buffering=1)
        self._at_line_start = True
        self._lock = lock
        self.encoding = getattr(self._console, 'encoding', 'utf-8')

    def write(self, msg):
        if self._console is not None:
            try:
                self._console.write(msg)
            except (UnicodeEncodeError, UnicodeDecodeError):
                enc = getattr(self._console, 'encoding', 'utf-8') or 'utf-8'
                self._console.write(msg.encode(enc, errors='replace').decode(enc))
        if not msg:
            return
        clean = _ANSI_RE.sub('', msg)
        if not clean:
            return
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        with self._lock:
            for part in clean.splitlines(keepends=True):
                if self._at_line_start:
                    self._file.write(f'[{ts}] ')
                self._file.write(part)
                self._at_line_start = part.endswith('\n')

    def flush(self):
        if self._console is not None:
            self._console.flush()
        try:
            self._file.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        if self._console is not None:
            return getattr(self._console, name)
        raise AttributeError(name)


class _TeeStderr:
    def __init__(self, log_file, lock):
        self._console = sys.__stderr__
        self._file = log_file
        self._lock = lock
        self._at_line_start = True
        self.encoding = getattr(self._console, 'encoding', 'utf-8')

    def write(self, msg):
        if self._console is not None:
            try:
                self._console.write(msg)
            except (UnicodeEncodeError, UnicodeDecodeError):
                enc = getattr(self._console, 'encoding', 'utf-8') or 'utf-8'
                self._console.write(msg.encode(enc, errors='replace').decode(enc))
        if not msg:
            return
        clean = _ANSI_RE.sub('', msg)
        if not clean:
            return
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        with self._lock:
            for part in clean.splitlines(keepends=True):
                if self._at_line_start:
                    self._file.write(f'[{ts}] [ERR] ')
                self._file.write(part)
                self._at_line_start = part.endswith('\n')

    def flush(self):
        if self._console is not None:
            self._console.flush()
        try:
            self._file.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        if self._console is not None:
            return getattr(self._console, name)
        raise AttributeError(name)


def init_runtime_log():
    if mp.current_process().name != 'MainProcess':
        return None
    root = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join(log_dir, f'lumina_{ts}.log')
    import threading
    lock = threading.Lock()
    tee = _Tee(log_path, console_stream=sys.stdout, lock=lock)
    tee_err = _TeeStderr(tee._file, lock)
    sys.stdout = tee
    sys.stderr = tee_err
    print(f"[LOG] {log_path}")
    return log_path

# Handle PyInstaller bundled resources
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    _PROJECT_ROOT = sys._MEIPASS
    # Also set the working directory to where the exe is located
    os.chdir(os.path.dirname(sys.executable))
else:
    # Running as script
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

_GRADIO_TEMP = os.path.join(os.getcwd(), "output", ".gradio_cache")
os.makedirs(_GRADIO_TEMP, exist_ok=True)
os.environ["GRADIO_TEMP_DIR"] = _GRADIO_TEMP

import time
import threading
import webbrowser
import socket
import gradio as gr     # type:ignore
from config import get_tray_runtime_policy
from ui.layout_new import create_app
from ui.styles import CUSTOM_CSS

ENABLE_TRAY, TRAY_POLICY_REASON = get_tray_runtime_policy()
LuminaTray = None
if ENABLE_TRAY:
    try:
        from core.tray import LuminaTray
    except Exception as e:
        print(f"⚠️ Warning: Tray module unavailable, disabling tray: {e}")
        ENABLE_TRAY = False
        TRAY_POLICY_REASON = f"Tray module unavailable: {e}"
        
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

def _graceful_shutdown(signum, frame):
    """Handle SIGTERM/SIGINT for clean container shutdown.
    处理 SIGTERM/SIGINT 信号，实现容器优雅退出。

    Args:
        signum (int): Signal number received. (接收到的信号编号)
        frame (frame): Current stack frame. (当前栈帧)
    """
    sig_name = signal.Signals(signum).name
    print(f"Received {sig_name}, shutting down...")
    os._exit(0)


if __name__ == "__main__":
    try:
        # Register signal handlers for graceful shutdown (SIGTERM from docker stop)
        signal.signal(signal.SIGTERM, _graceful_shutdown)
        signal.signal(signal.SIGINT, _graceful_shutdown)

        init_runtime_log()
        tray = None
        PORT = find_available_port(7860)

        if ENABLE_TRAY and LuminaTray is not None:
            try:
                tray = LuminaTray(port=PORT)
            except Exception as e:
                print(f"⚠️ Warning: Failed to initialize tray: {e}")
        else:
            print(f"[TRAY] {TRAY_POLICY_REASON}")

        threading.Thread(target=start_browser, args=(PORT,), daemon=True).start()
        print(f"✨ Lumina Studio is running on http://127.0.0.1:{PORT}")
        app = create_app()

        try:
            from ui.layout_new import HEADER_CSS, DEBOUNCE_JS, FIVECOLOR_CLICK_JS
            # Import crop extension for head JS injection
            from ui.crop_extension import get_crop_head_js
            
            # Find icon path (handle both dev and frozen modes)
            icon_path = None
            if os.path.exists("icon.ico"):
                icon_path = "icon.ico"
            elif getattr(sys, 'frozen', False):
                # In frozen mode, check in _MEIPASS
                icon_in_bundle = os.path.join(sys._MEIPASS, "icon.ico")
                if os.path.exists(icon_in_bundle):
                    icon_path = icon_in_bundle
            
            app.launch(
                inbrowser=False,
                server_name="0.0.0.0",
                server_port=PORT,
                show_error=True,
                prevent_thread_lock=True,
                favicon_path=icon_path,
                css=CUSTOM_CSS + HEADER_CSS,
                theme=gr.themes.Soft(),
                head=get_crop_head_js() + DEBOUNCE_JS + FIVECOLOR_CLICK_JS
            )
        except Exception as e:
            print(f"❌ Failed to launch Gradio app: {e}")
            import traceback
            traceback.print_exc()
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
        
    except Exception as e:
        print(f"❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")
        os._exit(1)
