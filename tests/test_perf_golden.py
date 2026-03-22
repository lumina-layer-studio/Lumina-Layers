"""
Golden-baseline regression test for performance optimization.
性能优化黄金基准回归测试。

Usage:
    # Generate baseline (run ONCE before any optimization):
    python tests/test_perf_golden.py --generate

    # Verify current code matches baseline:
    python tests/test_perf_golden.py --verify

    # Run as pytest:
    pytest tests/test_perf_golden.py -v
"""

import argparse
import json
import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ModelingMode
from core.image_processing import LuminaImageProcessor
from core.color_replacement import ColorReplacementManager

# ── Fixed test parameters (must never change) ──────────────────────────────

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HIFI_IMAGE = os.path.join(_PROJECT_ROOT, "TCT.jpg")
PIXEL_IMAGE = os.path.join(_PROJECT_ROOT, "Giant_Pumpkin.png")
LUT_PATH = os.path.join(_PROJECT_ROOT, "lut-npy预设", "Custom", "lumina_lut.json")

BASELINE_PATH = os.path.join(_PROJECT_ROOT, "tests", "golden_baseline.npz")
TIMINGS_PATH = os.path.join(_PROJECT_ROOT, "tests", "golden_timings.json")

TARGET_WIDTH_MM = 80.0
QUANTIZE_COLORS = 64
HUE_WEIGHT = 0.5
CHROMA_GATE = 15.0
AUTO_BG = True
BG_TOL = 30

# Color replacement pairs for testing apply_to_image
_REPLACEMENT_PAIRS = [
    ((220, 20, 60), (0, 128, 0)),
    ((255, 230, 0), (128, 0, 128)),
]


def _check_assets():
    """Verify all test assets exist before running.
    验证所有测试素材是否存在。"""
    missing = []
    for label, path in [("HIFI_IMAGE", HIFI_IMAGE), ("PIXEL_IMAGE", PIXEL_IMAGE), ("LUT_PATH", LUT_PATH)]:
        if not os.path.isfile(path):
            missing.append(f"  {label}: {path}")
    if missing:
        msg = "Missing test assets:\n" + "\n".join(missing)
        raise FileNotFoundError(msg)


def _run_pipeline(mode: ModelingMode, image_path: str):
    """Run the image processing pipeline and return key arrays + timing.
    运行图像处理流水线，返回关键数组和耗时。"""
    processor = LuminaImageProcessor(LUT_PATH, "4-Color", hue_weight=HUE_WEIGHT, chroma_gate=CHROMA_GATE)

    t0 = time.perf_counter()
    result = processor.process_image(
        image_path=image_path,
        target_width_mm=TARGET_WIDTH_MM,
        modeling_mode=mode,
        quantize_colors=QUANTIZE_COLORS,
        auto_bg=AUTO_BG,
        bg_tol=BG_TOL,
    )
    elapsed = time.perf_counter() - t0

    return {
        "matched_rgb": result["matched_rgb"],
        "material_matrix": result["material_matrix"],
        "mask_solid": result["mask_solid"],
    }, elapsed


def _run_color_replacement(rgb_array: np.ndarray):
    """Run color replacement and return result + timing.
    运行颜色替换，返回结果和耗时。"""
    mgr = ColorReplacementManager()
    for orig, repl in _REPLACEMENT_PAIRS:
        mgr.add_replacement(orig, repl)

    t0 = time.perf_counter()
    replaced = mgr.apply_to_image(rgb_array)
    elapsed = time.perf_counter() - t0
    return replaced, elapsed


def generate_baseline():
    """Generate golden baseline files (run before any optimization).
    生成黄金基准文件（在任何优化之前运行）。"""
    _check_assets()
    arrays = {}
    timings = {}

    print("=" * 60)
    print("GENERATING GOLDEN BASELINE")
    print("=" * 60)

    # High-Fidelity mode
    print(f"\n[1/3] High-Fidelity mode: {HIFI_IMAGE}")
    hifi_data, hifi_time = _run_pipeline(ModelingMode.HIGH_FIDELITY, HIFI_IMAGE)
    arrays["hifi_matched_rgb"] = hifi_data["matched_rgb"]
    arrays["hifi_material_matrix"] = hifi_data["material_matrix"]
    arrays["hifi_mask_solid"] = hifi_data["mask_solid"]
    timings["hifi_pipeline_s"] = round(hifi_time, 4)
    print(f"  -> matched_rgb: {hifi_data['matched_rgb'].shape}, time: {hifi_time:.3f}s")

    # Pixel mode
    print(f"\n[2/3] Pixel mode: {PIXEL_IMAGE}")
    pixel_data, pixel_time = _run_pipeline(ModelingMode.PIXEL, PIXEL_IMAGE)
    arrays["pixel_matched_rgb"] = pixel_data["matched_rgb"]
    arrays["pixel_material_matrix"] = pixel_data["material_matrix"]
    arrays["pixel_mask_solid"] = pixel_data["mask_solid"]
    timings["pixel_pipeline_s"] = round(pixel_time, 4)
    print(f"  -> matched_rgb: {pixel_data['matched_rgb'].shape}, time: {pixel_time:.3f}s")

    # Color replacement
    print(f"\n[3/3] Color replacement test")
    replaced, repl_time = _run_color_replacement(hifi_data["matched_rgb"])
    arrays["hifi_replaced_rgb"] = replaced
    timings["color_replacement_s"] = round(repl_time, 6)
    print(f"  -> replaced_rgb: {replaced.shape}, time: {repl_time:.6f}s")

    # Save
    np.savez_compressed(BASELINE_PATH, **arrays)
    with open(TIMINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(timings, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Baseline saved to:  {BASELINE_PATH}")
    print(f"Timings saved to:   {TIMINGS_PATH}")
    print(f"{'=' * 60}")
    print(f"\nHigh-Fidelity: {hifi_time:.3f}s")
    print(f"Pixel:         {pixel_time:.3f}s")
    print(f"Replacement:   {repl_time:.6f}s")


def verify_baseline():
    """Verify current code produces bit-identical output to baseline.
    验证当前代码与基准的输出完全一致。"""
    _check_assets()

    if not os.path.isfile(BASELINE_PATH):
        print("ERROR: Baseline file not found. Run --generate first.")
        sys.exit(1)

    baseline = np.load(BASELINE_PATH)
    old_timings = {}
    if os.path.isfile(TIMINGS_PATH):
        with open(TIMINGS_PATH, "r", encoding="utf-8") as f:
            old_timings = json.load(f)

    print("=" * 60)
    print("VERIFYING AGAINST GOLDEN BASELINE")
    print("=" * 60)

    all_pass = True
    new_timings = {}

    # High-Fidelity mode
    print(f"\n[1/3] High-Fidelity mode: {HIFI_IMAGE}")
    hifi_data, hifi_time = _run_pipeline(ModelingMode.HIGH_FIDELITY, HIFI_IMAGE)
    new_timings["hifi_pipeline_s"] = hifi_time

    for key in ["hifi_matched_rgb", "hifi_material_matrix", "hifi_mask_solid"]:
        ok = np.array_equal(hifi_data[key.replace("hifi_", "")], baseline[key])
        status = "PASS" if ok else "FAIL"
        print(f"  {key}: {status}")
        if not ok:
            all_pass = False
            diff_count = np.sum(hifi_data[key.replace("hifi_", "")] != baseline[key])
            total = baseline[key].size
            print(f"    -> {diff_count}/{total} elements differ ({diff_count/total*100:.4f}%)")

    # Pixel mode
    print(f"\n[2/3] Pixel mode: {PIXEL_IMAGE}")
    pixel_data, pixel_time = _run_pipeline(ModelingMode.PIXEL, PIXEL_IMAGE)
    new_timings["pixel_pipeline_s"] = pixel_time

    for key in ["pixel_matched_rgb", "pixel_material_matrix", "pixel_mask_solid"]:
        ok = np.array_equal(pixel_data[key.replace("pixel_", "")], baseline[key])
        status = "PASS" if ok else "FAIL"
        print(f"  {key}: {status}")
        if not ok:
            all_pass = False
            diff_count = np.sum(pixel_data[key.replace("pixel_", "")] != baseline[key])
            total = baseline[key].size
            print(f"    -> {diff_count}/{total} elements differ ({diff_count/total*100:.4f}%)")

    # Color replacement
    print(f"\n[3/3] Color replacement test")
    replaced, repl_time = _run_color_replacement(hifi_data["matched_rgb"])
    new_timings["color_replacement_s"] = repl_time

    ok = np.array_equal(replaced, baseline["hifi_replaced_rgb"])
    status = "PASS" if ok else "FAIL"
    print(f"  hifi_replaced_rgb: {status}")
    if not ok:
        all_pass = False
        diff_count = np.sum(replaced != baseline["hifi_replaced_rgb"])
        total = baseline["hifi_replaced_rgb"].size
        print(f"    -> {diff_count}/{total} elements differ ({diff_count/total*100:.4f}%)")

    # Timing comparison
    print(f"\n{'=' * 60}")
    print("TIMING COMPARISON (old -> new, speedup)")
    print(f"{'=' * 60}")
    for key, new_val in new_timings.items():
        old_val = old_timings.get(key, 0)
        if old_val > 0:
            speedup = old_val / new_val if new_val > 0 else float("inf")
            print(f"  {key}: {old_val:.4f}s -> {new_val:.4f}s  ({speedup:.2f}x)")
        else:
            print(f"  {key}: N/A -> {new_val:.4f}s")

    # Final verdict
    print(f"\n{'=' * 60}")
    if all_pass:
        print("RESULT: ALL CHECKS PASSED (bit-identical)")
    else:
        print("RESULT: MISMATCH DETECTED — output differs from baseline!")
    print(f"{'=' * 60}")

    return all_pass


# ── pytest integration ──────────────────────────────────────────────────────

def _load_baseline():
    if not os.path.isfile(BASELINE_PATH):
        pytest.skip("Golden baseline not generated yet. Run: python tests/test_perf_golden.py --generate")
    return np.load(BASELINE_PATH)


class TestGoldenHighFidelity:
    """Golden baseline tests for High-Fidelity mode."""

    @pytest.fixture(scope="class")
    def hifi_result(self):
        _check_assets()
        data, _ = _run_pipeline(ModelingMode.HIGH_FIDELITY, HIFI_IMAGE)
        return data

    @pytest.fixture(scope="class")
    def baseline(self):
        return _load_baseline()

    def test_matched_rgb(self, hifi_result, baseline):
        np.testing.assert_array_equal(
            hifi_result["matched_rgb"], baseline["hifi_matched_rgb"],
            err_msg="High-Fidelity matched_rgb differs from golden baseline"
        )

    def test_material_matrix(self, hifi_result, baseline):
        np.testing.assert_array_equal(
            hifi_result["material_matrix"], baseline["hifi_material_matrix"],
            err_msg="High-Fidelity material_matrix differs from golden baseline"
        )

    def test_mask_solid(self, hifi_result, baseline):
        np.testing.assert_array_equal(
            hifi_result["mask_solid"], baseline["hifi_mask_solid"],
            err_msg="High-Fidelity mask_solid differs from golden baseline"
        )


class TestGoldenPixel:
    """Golden baseline tests for Pixel mode."""

    @pytest.fixture(scope="class")
    def pixel_result(self):
        _check_assets()
        data, _ = _run_pipeline(ModelingMode.PIXEL, PIXEL_IMAGE)
        return data

    @pytest.fixture(scope="class")
    def baseline(self):
        return _load_baseline()

    def test_matched_rgb(self, pixel_result, baseline):
        np.testing.assert_array_equal(
            pixel_result["matched_rgb"], baseline["pixel_matched_rgb"],
            err_msg="Pixel matched_rgb differs from golden baseline"
        )

    def test_material_matrix(self, pixel_result, baseline):
        np.testing.assert_array_equal(
            pixel_result["material_matrix"], baseline["pixel_material_matrix"],
            err_msg="Pixel material_matrix differs from golden baseline"
        )

    def test_mask_solid(self, pixel_result, baseline):
        np.testing.assert_array_equal(
            pixel_result["mask_solid"], baseline["pixel_mask_solid"],
            err_msg="Pixel mask_solid differs from golden baseline"
        )


class TestGoldenColorReplacement:
    """Golden baseline tests for color replacement."""

    @pytest.fixture(scope="class")
    def replacement_result(self):
        _check_assets()
        hifi_data, _ = _run_pipeline(ModelingMode.HIGH_FIDELITY, HIFI_IMAGE)
        replaced, _ = _run_color_replacement(hifi_data["matched_rgb"])
        return replaced

    @pytest.fixture(scope="class")
    def baseline(self):
        return _load_baseline()

    def test_replaced_rgb(self, replacement_result, baseline):
        np.testing.assert_array_equal(
            replacement_result, baseline["hifi_replaced_rgb"],
            err_msg="Color replacement result differs from golden baseline"
        )


# ── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Golden baseline regression test")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true", help="Generate baseline (run ONCE before optimization)")
    group.add_argument("--verify", action="store_true", help="Verify current code against baseline")
    args = parser.parse_args()

    if args.generate:
        generate_baseline()
    elif args.verify:
        ok = verify_baseline()
        sys.exit(0 if ok else 1)
