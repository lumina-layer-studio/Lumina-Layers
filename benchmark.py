"""
Lumina Studio — headless benchmark script.

Runs both SVG mode (Lanz1.svg) and High-Fidelity mode (Lanz2.jpg) without
starting the Gradio UI, measures wall-clock time for each stage, and prints
[BENCH] summary lines that can be grepped from log files for easy comparison
across optimisation iterations.

Usage:
    cd g:\\Lumina\\Lumina-Layers
    python benchmark.py [--svg-only | --hifi-only] [--no-preview]

Each run creates a timestamped log in  logs/bench_YYYYMMDD_HHMMSS.log
"""

import os
import sys
import time
import glob
import argparse
from datetime import datetime

# ── Bootstrap: ensure project root is on sys.path ────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Redirect stdout/stderr to both console and log file ──────────────────────
import re as _re
import threading as _threading
import multiprocessing as _mp

_ANSI_RE = _re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

class _Tee:
    def __init__(self, log_path, console_stream=None, lock=None):
        self._console = console_stream or sys.stdout
        self._file = open(log_path, 'a', encoding='utf-8', buffering=1)
        self.encoding = getattr(self._console, 'encoding', 'utf-8')
        self._at_line_start = True
        self._lock = lock or _threading.Lock()

    def write(self, msg):
        try:
            self._console.write(msg)
        except (UnicodeEncodeError, UnicodeDecodeError):
            # Windows console may be GBK; replace unencodable chars
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
        self._console.flush()
        try:
            self._file.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._console, name)


class _TeeStderr:
    def __init__(self, log_file, lock):
        self._console = sys.stderr
        self._file = log_file
        self._lock = lock
        self._at_line_start = True
        self.encoding = getattr(sys.stderr, 'encoding', 'utf-8')

    def write(self, msg):
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
        self._console.flush()
        try:
            self._file.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._console, name)


if _mp.current_process().name == 'MainProcess':
    _log_dir = os.path.join(_ROOT, 'logs')
    os.makedirs(_log_dir, exist_ok=True)
    _ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _log_path = os.path.join(_log_dir, f'bench_{_ts}.log')
    _lock = _threading.Lock()
    _tee = _Tee(_log_path, console_stream=sys.stdout, lock=_lock)
    _tee_err = _TeeStderr(_tee._file, _lock)
    sys.stdout = _tee
    sys.stderr = _tee_err
    print(f"[BENCH] Log: {_log_path}")

# ── Now safe to import heavy project modules ──────────────────────────────────
from config import ModelingMode

# ── Constants ─────────────────────────────────────────────────────────────────
def _pick_first_existing(candidates):
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        "No benchmark input file found. Tried:\n- " + "\n- ".join(candidates)
    )


def _pick_latest_lut():
    lut_dir = os.path.join(_ROOT, "lut-preset", "Aliz", "PETG", "5色")
    matches = glob.glob(os.path.join(lut_dir, "*.npy"))
    if not matches:
        raise FileNotFoundError(f"No LUT .npy file found in: {lut_dir}")
    return max(matches, key=os.path.getmtime)


LUT_PATH = _pick_latest_lut()
SVG_PATH = _pick_first_existing([
    os.path.join(_ROOT, "test_images", "benchmark.svg"),
    os.path.join(_ROOT, "Lanz1.svg"),
])
HIFI_PATH = _pick_first_existing([
    os.path.join(_ROOT, "test_images", "benchmark.jpg"),
    os.path.join(_ROOT, "Lanz2.jpg"),
])
COLOR_MODE = "5-Color Extended"
LONG_EDGE  = 240.0          # mm — long-edge constraint
SPACER_MM  = 1.2
QUANTIZE   = 48


def _calc_target_width(image_path: str, long_edge_mm: float) -> float:
    """Return target_width_mm so that the longest side == long_edge_mm."""
    from PIL import Image as _PILImage
    import xml.etree.ElementTree as _ET

    if image_path.lower().endswith('.svg'):
        # Parse SVG viewBox / width / height
        try:
            tree = _ET.parse(image_path)
            root = tree.getroot()
            ns = root.tag.split('}')[0].lstrip('{') if '}' in root.tag else ''
            vb = root.get('viewBox', '')
            if vb:
                parts = vb.replace(',', ' ').split()
                w_svg, h_svg = float(parts[2]), float(parts[3])
            else:
                w_str = root.get('width', '100').replace('px', '').strip()
                h_str = root.get('height', '100').replace('px', '').strip()
                w_svg, h_svg = float(w_str), float(h_str)
        except Exception:
            return long_edge_mm  # fallback

        if w_svg >= h_svg:
            return long_edge_mm
        else:
            return long_edge_mm * w_svg / h_svg
    else:
        with _PILImage.open(image_path) as im:
            w_px, h_px = im.size
        if w_px >= h_px:
            return long_edge_mm
        else:
            return long_edge_mm * w_px / h_px


def _bench_header(label: str):
    print(f"\n{'='*60}")
    print(f"[BENCH] >>> {label}")
    print(f"{'='*60}")


def _bench_result(label: str, timings: dict, total: float):
    """Print a single-line [BENCH] summary that is easy to grep/compare."""
    parts = "  ".join(f"{k}={v:.2f}s" for k, v in timings.items())
    print(f"[BENCH] RESULT  {label}  |  {parts}  |  TOTAL={total:.2f}s")


def run_svg_benchmark(run_preview: bool = True):
    from core.converter import generate_preview_cached, generate_final_model

    target_w = _calc_target_width(SVG_PATH, LONG_EDGE)
    print(f"[BENCH] SVG target_width_mm={target_w:.1f} (long edge={LONG_EDGE}mm)")

    timings = {}

    if run_preview:
        _bench_header("SVG Preview")
        t0 = time.perf_counter()
        prev_img, cache_data, status = generate_preview_cached(
            image_path=SVG_PATH,
            lut_path=LUT_PATH,
            target_width_mm=target_w,
            auto_bg=False,
            bg_tol=20,
            color_mode=COLOR_MODE,
            modeling_mode=ModelingMode.VECTOR,
            quantize_colors=QUANTIZE,
            backing_color_id=0,
            enable_cleanup=True,
            is_dark=False,
        )
        timings['preview'] = time.perf_counter() - t0
        print(f"[BENCH] SVG preview done: {status}")

    _bench_header("SVG Convert")
    t0 = time.perf_counter()
    result = generate_final_model(
        image_path=SVG_PATH,
        lut_path=LUT_PATH,
        target_width_mm=target_w,
        spacer_thick=SPACER_MM,
        structure_mode="Single-sided",
        auto_bg=False,
        bg_tol=20,
        color_mode=COLOR_MODE,
        add_loop=False,
        loop_width=8.0,
        loop_length=12.0,
        loop_hole=4.0,
        loop_pos=50.0,
        modeling_mode=ModelingMode.VECTOR,
        quantize_colors=QUANTIZE,
        backing_color_name="White",
    )
    timings['convert'] = time.perf_counter() - t0
    print(f"[BENCH] SVG convert done: {result}")

    total = sum(timings.values())
    _bench_result("SVG", timings, total)
    return timings, total


def run_hifi_benchmark(run_preview: bool = True):
    from core.converter import generate_preview_cached, generate_final_model

    target_w = _calc_target_width(HIFI_PATH, LONG_EDGE)
    print(f"[BENCH] HiFi target_width_mm={target_w:.1f} (long edge={LONG_EDGE}mm)")

    timings = {}

    if run_preview:
        _bench_header("HiFi Preview")
        t0 = time.perf_counter()
        prev_img, cache_data, status = generate_preview_cached(
            image_path=HIFI_PATH,
            lut_path=LUT_PATH,
            target_width_mm=target_w,
            auto_bg=False,
            bg_tol=20,
            color_mode=COLOR_MODE,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            quantize_colors=QUANTIZE,
            backing_color_id=0,
            enable_cleanup=True,
            is_dark=False,
        )
        timings['preview'] = time.perf_counter() - t0
        print(f"[BENCH] HiFi preview done: {status}")

    _bench_header("HiFi Convert")
    t0 = time.perf_counter()
    
    # Enable internal conversion timing (zero-overhead when not instrumenting)
    import os
    os.environ['LUMINA_BENCH_TIMING'] = '1'
    
    result = generate_final_model(
        image_path=HIFI_PATH,
        lut_path=LUT_PATH,
        target_width_mm=target_w,
        spacer_thick=SPACER_MM,
        structure_mode="Single-sided",
        auto_bg=False,
        bg_tol=20,
        color_mode=COLOR_MODE,
        add_loop=False,
        loop_width=8.0,
        loop_length=12.0,
        loop_hole=4.0,
        loop_pos=50.0,
        modeling_mode=ModelingMode.HIGH_FIDELITY,
        quantize_colors=QUANTIZE,
        backing_color_name="White",
    )
    timings['convert'] = time.perf_counter() - t0
    print(f"[BENCH] HiFi convert done: {result}")

    total = sum(timings.values())
    _bench_result("HiFi", timings, total)
    return timings, total


def main():
    parser = argparse.ArgumentParser(description="Lumina headless benchmark")
    parser.add_argument('--svg-only',    action='store_true', help='Only run SVG benchmark')
    parser.add_argument('--hifi-only',   action='store_true', help='Only run HiFi benchmark')
    parser.add_argument('--no-preview',  action='store_true', help='Skip preview step')
    parser.add_argument('--runs', type=int, default=1, help='Number of times to repeat each test')
    args = parser.parse_args()

    run_preview = not args.no_preview
    run_svg  = not args.hifi_only
    run_hifi = not args.svg_only

    all_results = {}
    for i in range(args.runs):
        if args.runs > 1:
            print(f"\n[BENCH] ====== RUN {i+1}/{args.runs} ======")
        if run_svg:
            t, total = run_svg_benchmark(run_preview=run_preview)
            all_results.setdefault('svg', []).append(total)
        if run_hifi:
            t, total = run_hifi_benchmark(run_preview=run_preview)
            all_results.setdefault('hifi', []).append(total)

    # Final summary
    print(f"\n[BENCH] ====== SUMMARY ======")
    for mode, totals in all_results.items():
        avg = sum(totals) / len(totals)
        mn  = min(totals)
        mx  = max(totals)
        if len(totals) == 1:
            print(f"[BENCH] {mode.upper():<6} total={totals[0]:.2f}s")
        else:
            print(f"[BENCH] {mode.upper():<6} avg={avg:.2f}s  min={mn:.2f}s  max={mx:.2f}s")


if __name__ == '__main__':
    main()
