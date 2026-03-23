"""
Full pipeline benchmark: runs convert_image_to_3d end-to-end.
完整流水线基准测试：端到端运行 convert_image_to_3d。

Usage:
    python tests/bench_full_pipeline.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(_PROJECT_ROOT, "IMG_0892.JPG")
LUT = os.path.join(_PROJECT_ROOT, "lut-preset", "Custom", "lumina_lut.json")

# TCT.jpg is 3071x4096 (WxH), ratio 1:1.334
# target_width_mm=225 -> height ≈ 225*1.334 ≈ 300mm -> 2250x3002 px at 10px/mm
TARGET_WIDTH_MM = 225.0


def run_benchmark():
    from config import ModelingMode
    from core.converter import convert_image_to_3d

    print("=" * 70)
    print(f"FULL PIPELINE BENCHMARK")
    print(f"  Image:  {IMAGE}")
    print(f"  LUT:    {LUT}")
    print(f"  Width:  {TARGET_WIDTH_MM}mm (height ~300mm)")
    print(f"  Mode:   High-Fidelity")
    print("=" * 70)

    t_total = time.perf_counter()

    threemf_path, glb_path, preview_img, status_msg, recipe = convert_image_to_3d(
        image_path=IMAGE,
        lut_path=LUT,
        target_width_mm=TARGET_WIDTH_MM,
        spacer_thick=1.2,
        structure_mode="单面",
        auto_bg=True,
        bg_tol=30,
        color_mode="4-Color",
        add_loop=False,
        loop_width=4.0,
        loop_length=8.0,
        loop_hole=2.5,
        loop_pos=None,
        modeling_mode=ModelingMode.HIGH_FIDELITY,
        quantize_colors=64,
        enable_cleanup=True,
        hue_weight=0.5,
        chroma_gate=15.0,
    )

    elapsed = time.perf_counter() - t_total

    print("\n" + "=" * 70)
    print(f"RESULT")
    print(f"  Status:    {status_msg}")
    print(f"  3MF:       {threemf_path}")
    print(f"  GLB:       {glb_path}")
    if threemf_path and os.path.exists(threemf_path):
        size_mb = os.path.getsize(threemf_path) / (1024 * 1024)
        print(f"  3MF size:  {size_mb:.1f} MB")
    print(f"")
    print(f"  TOTAL TIME: {elapsed:.2f}s")
    print("=" * 70)

    # Cleanup temp files
    for p in [threemf_path, glb_path]:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    return elapsed


if __name__ == "__main__":
    run_benchmark()
