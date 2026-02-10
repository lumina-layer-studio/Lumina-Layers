#!/usr/bin/env python
"""
Baseline Capture Script for High-Fidelity Color Mapping

This script captures baseline performance metrics for the legacy RGB Euclidean
color matching strategy. It runs the existing processing pipeline on fixed sample
images and records timing, output hashes, and perceptual error statistics.

The captured baseline will be used for A/B comparison with the new DeltaE2000 strategy.

Usage:
    python capture_baseline.py [--lut-path LUT_PATH] [--color-mode MODE]

Output:
    .sisyphus/evidence/task-3-baseline-summary.json

Author: Sisyphus-Junior
Date: 2026-02-10
"""

import sys
import os
import time
import hashlib
import json
from datetime import datetime
from typing import Dict, List, Any, Tuple
import numpy as np
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import project modules (avoid circular imports)
from config import ModelingMode, ColorSystem, MatchStrategy, PrinterConfig

# Import internal modules directly
from core.image_processing_factory import ProcessorFactory, LUTManager, ImageLoader
from core.image_processing_factory.color_modes import FourColorStrategy


# ========== Configuration ==========

SAMPLE_DIR = project_root / ".sisyphus" / "fixtures" / "samples"
EVIDENCE_DIR = project_root / ".sisyphus" / "evidence"

# Default LUT path (can be overridden via command line)
DEFAULT_LUT_PATH = None  # Will search for first .npy file if None

# Default color mode
DEFAULT_COLOR_MODE = "CMYW"

# Processing parameters (mimicking default behavior)
TARGET_WIDTH_MM = 50.0
QUANTIZE_COLORS = 64
AUTO_BG = False
BG_TOL = 30
BLUR_KERNEL = 0
SMOOTH_SIGMA = 10.0

# Sample files
SAMPLE_FILES = [
    "sample1_portrait.png",
    "sample2_high_saturation.png",
    "sample3_low_contrast.png",
]


# ========== Utility Functions ==========


def find_lut_file() -> str:
    """
    Find the first .npy LUT file in the project directory.

    Returns:
        Path to LUT file

    Raises:
        FileNotFoundError: If no LUT file found
    """
    # Search in common locations
    search_paths = [
        project_root / "outputs",
        project_root,
    ]

    for search_path in search_paths:
        if search_path.exists():
            npy_files = list(search_path.glob("*.npy"))
            if npy_files:
                lut_path = str(npy_files[0])
                print(f"[LUT] Found LUT file: {lut_path}")
                return lut_path

    raise FileNotFoundError(
        "No LUT file found. Please provide a LUT file using --lut-path argument."
    )


def calculate_hash(array: np.ndarray) -> str:
    """
    Calculate SHA256 hash of a numpy array.

    Args:
        array: Input numpy array

    Returns:
        SHA256 hash as hex string
    """
    return hashlib.sha256(array.tobytes()).hexdigest()


def count_unique_colors(rgb_array: np.ndarray, mask: np.ndarray) -> int:
    """
    Count unique RGB colors in solid pixels.

    Args:
        rgb_array: RGB array (H, W, 3)
        mask: Boolean mask for solid pixels

    Returns:
        Number of unique colors
    """
    solid_pixels = rgb_array[mask]
    if len(solid_pixels) == 0:
        return 0

    # Reshape to (N, 3) and find unique rows
    unique_colors = np.unique(solid_pixels, axis=0)
    return len(unique_colors)


def calculate_perceptual_error(
    original_rgb: np.ndarray, matched_rgb: np.ndarray, mask_solid: np.ndarray
) -> Dict[str, float]:
    """
    Calculate perceptual error statistics between original and matched colors.

    This measures how well the LUT matching preserves the original colors.

    Args:
        original_rgb: Original RGB array (H, W, 3)
        matched_rgb: Matched RGB array from LUT (H, W, 3)
        mask_solid: Boolean mask for solid pixels

    Returns:
        Dictionary with error statistics:
        - mean_error: Mean RGB Euclidean distance
        - max_error: Maximum RGB Euclidean distance
        - std_error: Standard deviation of RGB Euclidean distance
    """
    # Extract solid pixels
    orig_pixels = original_rgb[mask_solid].astype(np.float32)
    match_pixels = matched_rgb[mask_solid].astype(np.float32)

    if len(orig_pixels) == 0:
        return {"mean_error": 0.0, "max_error": 0.0, "std_error": 0.0}

    # Calculate RGB Euclidean distance for each pixel
    diff = orig_pixels - match_pixels
    distances = np.sqrt(np.sum(diff**2, axis=1))

    return {
        "mean_error": float(np.mean(distances)),
        "max_error": float(np.max(distances)),
        "std_error": float(np.std(distances)),
    }


def process_sample(image_path: str, lut_path: str, color_mode: str) -> Dict[str, Any]:
    """
    Process a single sample image and capture metrics.

    Args:
        image_path: Path to sample image
        lut_path: Path to LUT file
        color_mode: Color mode (CMYW/RYBW)

    Returns:
        Dictionary containing processing results and metrics
    """
    print(f"\n[PROCESSING] {os.path.basename(image_path)}")
    print("-" * 60)

    # Load original image for comparison
    from PIL import Image

    original_img = Image.open(image_path).convert("RGBA")
    original_arr = np.array(original_img)
    original_rgb = original_arr[:, :, :3]

    # Initialize color strategy
    print(f"[PROCESSING] Initializing with {color_mode} mode...")
    color_strategy = FourColorStrategy(color_mode)

    # Load LUT
    lut_manager = LUTManager.from_strategy(color_strategy, lut_path)

    # Get processing strategy
    processing_strategy = ProcessorFactory.create_processing_strategy(
        ModelingMode.HIGH_FIDELITY
    )

    # Calculate target resolution
    target_w, _, pixel_to_mm_scale = processing_strategy.get_resolution(TARGET_WIDTH_MM)
    target_h = int(target_w * original_img.height / original_img.width)

    print(f"[PROCESSING] Target resolution: {target_w} x {target_h}")

    # Load and resize image
    img = original_img.resize((target_w, target_h), Image.Resampling.NEAREST)
    img_arr = np.array(img)
    rgb_arr = img_arr[:, :, :3]
    alpha_arr = img_arr[:, :, 3]

    # Store resized original for comparison
    original_rgb = rgb_arr.copy()

    # Identify transparent pixels
    mask_transparent_initial = alpha_arr < 10

    # Measure processing time
    print(f"[PROCESSING] Processing with RGB Euclidean strategy...")
    start_time = time.perf_counter()

    try:
        # Process image using default RGB Euclidean strategy
        matched_rgb, material_matrix, bg_reference, debug_data = (
            processing_strategy.process(
                rgb_arr=rgb_arr,
                target_h=target_h,
                target_w=target_w,
                lut_rgb=lut_manager.lut_rgb,
                ref_stacks=lut_manager.ref_stacks,
                kdtree=lut_manager.kdtree,
                quantize_colors=QUANTIZE_COLORS,
                blur_kernel=BLUR_KERNEL,
                smooth_sigma=SMOOTH_SIGMA,
                match_strategy=MatchStrategy.RGB_EUCLIDEAN,
            )
        )
    except Exception as e:
        print(f"[ERROR] Processing failed: {e}")
        import traceback

        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
        }

    end_time = time.perf_counter()
    duration_ms = (end_time - start_time) * 1000

    # Apply transparency mask
    mask_transparent = mask_transparent_initial.copy()
    material_matrix[mask_transparent] = -1
    mask_solid = ~mask_transparent

    print(f"[PROCESSING] Output dimensions: {target_w} x {target_h}")
    print(f"[PROCESSING] Solid pixels: {np.sum(mask_solid)}")

    print(f"[PROCESSING] Output dimensions: {target_w} x {target_h}")
    print(f"[PROCESSING] Solid pixels: {np.sum(mask_solid)}")

    # Calculate metrics
    matched_hash = calculate_hash(matched_rgb)
    unique_color_count = count_unique_colors(matched_rgb, mask_solid)
    perceptual_error = calculate_perceptual_error(original_rgb, matched_rgb, mask_solid)

    print(f"[METRICS] Duration: {duration_ms:.2f} ms")
    print(f"[METRICS] Matched RGB hash: {matched_hash[:16]}...")
    print(f"[METRICS] Unique colors: {unique_color_count}")
    print(f"[METRICS] Mean perceptual error: {perceptual_error['mean_error']:.2f}")

    return {
        "success": True,
        "duration_ms": round(duration_ms, 2),
        "matched_rgb_hash": f"sha256:{matched_hash}",
        "unique_color_count": unique_color_count,
        "perceptual_error": perceptual_error,
        "dimensions": {"width": target_w, "height": target_h},
        "solid_pixel_count": int(np.sum(mask_solid)),
    }


def main():
    """Main execution function."""
    print("=" * 70)
    print("BASELINE CAPTURE: High-Fidelity RGB Euclidean Strategy")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Project root: {project_root}")
    print()

    # Parse command line arguments
    lut_path = DEFAULT_LUT_PATH
    color_mode = DEFAULT_COLOR_MODE

    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--lut-path" and i + 1 < len(sys.argv):
            lut_path = sys.argv[i + 2]
        elif arg == "--color-mode" and i + 1 < len(sys.argv):
            color_mode = sys.argv[i + 2]
        elif arg == "--help":
            print("Usage: python capture_baseline.py [options]")
            print("Options:")
            print("  --lut-path PATH    Path to LUT .npy file")
            print("  --color-mode MODE  Color mode (CMYW/RYBW)")
            print("  --help             Show this help message")
            return

    # Find LUT file if not provided
    if lut_path is None:
        print("[INIT] Searching for LUT file...")
        try:
            lut_path = find_lut_file()
        except FileNotFoundError as e:
            print(f"[ERROR] {e}")
            return 1

    if not os.path.exists(lut_path):
        print(f"[ERROR] LUT file not found: {lut_path}")
        return 1

    print(f"[CONFIG] LUT path: {lut_path}")
    print(f"[CONFIG] Color mode: {color_mode}")
    print(f"[CONFIG] Quantize colors: {QUANTIZE_COLORS}")
    print(f"[CONFIG] Target width: {TARGET_WIDTH_MM} mm")

    # Verify sample files exist
    sample_paths = []
    for sample_file in SAMPLE_FILES:
        sample_path = SAMPLE_DIR / sample_file
        if not sample_path.exists():
            print(f"[ERROR] Sample file not found: {sample_path}")
            print(f"[ERROR] Please run generate_samples.py first.")
            return 1
        sample_paths.append(str(sample_path))

    print(f"[CONFIG] Sample files: {len(sample_paths)}")
    for i, path in enumerate(sample_paths, 1):
        print(f"  {i}. {os.path.basename(path)}")

    # Process all samples
    results = []
    for i, sample_path in enumerate(sample_paths, 1):
        print(f"\n{'=' * 70}")
        print(f"SAMPLE {i}/{len(sample_paths)}")
        print("=" * 70)

        result = process_sample(sample_path, lut_path, color_mode)
        result["name"] = os.path.basename(sample_path)
        result["index"] = i
        results.append(result)

    # Compile summary
    successful_results = [r for r in results if r.get("success", False)]

    if not successful_results:
        print("\n[ERROR] All samples failed to process")
        return 1

    summary = {
        "timestamp": datetime.now().isoformat(),
        "strategy": "RGB_EUCLIDEAN",
        "lut_path": lut_path,
        "color_mode": color_mode,
        "parameters": {
            "target_width_mm": TARGET_WIDTH_MM,
            "quantize_colors": QUANTIZE_COLORS,
            "auto_bg": AUTO_BG,
            "bg_tol": BG_TOL,
            "blur_kernel": BLUR_KERNEL,
            "smooth_sigma": SMOOTH_SIGMA,
        },
        "samples": successful_results,
        "statistics": {
            "total_samples": len(successful_results),
            "total_duration_ms": round(
                sum(r["duration_ms"] for r in successful_results), 2
            ),
            "mean_duration_ms": round(
                np.mean([r["duration_ms"] for r in successful_results]), 2
            ),
            "mean_unique_colors": round(
                np.mean([r["unique_color_count"] for r in successful_results]), 2
            ),
            "mean_perceptual_error": round(
                np.mean(
                    [r["perceptual_error"]["mean_error"] for r in successful_results]
                ),
                2,
            ),
        },
    }

    # Save evidence file
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    evidence_path = EVIDENCE_DIR / "task-3-baseline-summary.json"

    with open(evidence_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print("BASELINE CAPTURE COMPLETE")
    print("=" * 70)
    print(f"Evidence saved to: {evidence_path}")
    print()
    print("SUMMARY:")
    print(f"  Total samples: {summary['statistics']['total_samples']}")
    print(f"  Total duration: {summary['statistics']['total_duration_ms']:.2f} ms")
    print(f"  Mean duration: {summary['statistics']['mean_duration_ms']:.2f} ms")
    print(f"  Mean unique colors: {summary['statistics']['mean_unique_colors']:.1f}")
    print(
        f"  Mean perceptual error: {summary['statistics']['mean_perceptual_error']:.2f}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
