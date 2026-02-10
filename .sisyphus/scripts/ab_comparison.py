#!/usr/bin/env python
"""
A/B Comparison Script for High-Fidelity Color Matching Strategies

This script performs comprehensive A/B testing between RGB_EUCLIDEAN and DELTAE2000
strategies, measuring:
1. Performance (duration comparison)
2. Stability (hash consistency across repeated runs)
3. Quality (perceptual error metrics)

Usage:
    python ab_comparison.py [--lut-path LUT_PATH] [--color-mode MODE] [--runs N]

Output:
    .sisyphus/evidence/task-6-ab-raw-data.json

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
from dataclasses import dataclass, asdict

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import project modules
from config import ModelingMode, ColorSystem, MatchStrategy, PrinterConfig
from core.image_processing_factory import ProcessorFactory, LUTManager
from core.image_processing_factory.color_modes import FourColorStrategy


# ========== Configuration ==========

SAMPLE_DIR = project_root / ".sisyphus" / "fixtures" / "samples"
EVIDENCE_DIR = project_root / ".sisyphus" / "evidence"

DEFAULT_LUT_PATH = None  # Will search for first .npy file if None
DEFAULT_COLOR_MODE = "CMYW"
DEFAULT_RUNS = 3  # Number of repeated runs per strategy

# Processing parameters (same as baseline)
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


# ========== Data Structures ==========


@dataclass
class RunResult:
    """Single run result."""

    run_id: int
    success: bool
    duration_ms: float
    matched_rgb_hash: str
    unique_color_count: int
    perceptual_error: Dict[str, float]
    dimensions: Dict[str, int]
    solid_pixel_count: int
    error_message: str = ""


@dataclass
class StrategyResult:
    """Results for all runs of a single strategy on a single sample."""

    strategy: str
    sample_name: str
    runs: List[RunResult]

    def get_successful_runs(self) -> List[RunResult]:
        """Get all successful runs."""
        return [r for r in self.runs if r.success]

    def is_stable(self) -> bool:
        """Check if all successful runs have identical hashes."""
        successful = self.get_successful_runs()
        if len(successful) < 2:
            return True  # Not enough runs to compare
        first_hash = successful[0].matched_rgb_hash
        return all(r.matched_rgb_hash == first_hash for r in successful)

    def get_mean_duration(self) -> float:
        """Get mean duration across successful runs."""
        successful = self.get_successful_runs()
        if not successful:
            return 0.0
        return float(np.mean([r.duration_ms for r in successful]))

    def get_std_duration(self) -> float:
        """Get std duration across successful runs."""
        successful = self.get_successful_runs()
        if len(successful) < 2:
            return 0.0
        return float(np.std([r.duration_ms for r in successful]))


# ========== Utility Functions ==========


def find_lut_file() -> str:
    """Find the first .npy LUT file in the project directory."""
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
    """Calculate SHA256 hash of a numpy array."""
    return hashlib.sha256(array.tobytes()).hexdigest()


def count_unique_colors(rgb_array: np.ndarray, mask: np.ndarray) -> int:
    """Count unique RGB colors in solid pixels."""
    solid_pixels = rgb_array[mask]
    if len(solid_pixels) == 0:
        return 0
    unique_colors = np.unique(solid_pixels, axis=0)
    return len(unique_colors)


def calculate_perceptual_error(
    original_rgb: np.ndarray, matched_rgb: np.ndarray, mask_solid: np.ndarray
) -> Dict[str, float]:
    """Calculate perceptual error statistics."""
    orig_pixels = original_rgb[mask_solid].astype(np.float32)
    match_pixels = matched_rgb[mask_solid].astype(np.float32)

    if len(orig_pixels) == 0:
        return {"mean_error": 0.0, "max_error": 0.0, "std_error": 0.0}

    # Calculate RGB Euclidean distance
    diff = orig_pixels - match_pixels
    distances = np.sqrt(np.sum(diff**2, axis=1))

    return {
        "mean_error": float(np.mean(distances)),
        "max_error": float(np.max(distances)),
        "std_error": float(np.std(distances)),
    }


def process_single_run(
    image_path: str,
    lut_path: str,
    color_mode: str,
    strategy: MatchStrategy,
    run_id: int,
) -> RunResult:
    """
    Process a single sample image with a specific strategy.

    Args:
        image_path: Path to sample image
        lut_path: Path to LUT file
        color_mode: Color mode (CMYW/RYBW)
        strategy: MatchStrategy to use
        run_id: Run identifier

    Returns:
        RunResult with metrics
    """
    from PIL import Image

    sample_name = os.path.basename(image_path)

    try:
        # Load original image
        original_img = Image.open(image_path).convert("RGBA")
        original_arr = np.array(original_img)
        original_rgb = original_arr[:, :, :3]

        # Initialize color strategy
        color_strategy = FourColorStrategy(color_mode)

        # Load LUT
        lut_manager = LUTManager.from_strategy(color_strategy, lut_path)

        # Get processing strategy
        processing_strategy = ProcessorFactory.create_processing_strategy(
            ModelingMode.HIGH_FIDELITY
        )

        # Calculate target resolution
        target_w, _, _ = processing_strategy.get_resolution(TARGET_WIDTH_MM)
        target_h = int(target_w * original_img.height / original_img.width)

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
        start_time = time.perf_counter()

        # Process image with specified strategy
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
                match_strategy=strategy,
            )
        )

        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000

        # Apply transparency mask
        mask_transparent = mask_transparent_initial.copy()
        material_matrix[mask_transparent] = -1
        mask_solid = ~mask_transparent

        # Calculate metrics
        matched_hash = calculate_hash(matched_rgb)
        unique_color_count = count_unique_colors(matched_rgb, mask_solid)
        perceptual_error = calculate_perceptual_error(
            original_rgb, matched_rgb, mask_solid
        )

        return RunResult(
            run_id=run_id,
            success=True,
            duration_ms=round(duration_ms, 2),
            matched_rgb_hash=f"sha256:{matched_hash}",
            unique_color_count=unique_color_count,
            perceptual_error=perceptual_error,
            dimensions={"width": target_w, "height": target_h},
            solid_pixel_count=int(np.sum(mask_solid)),
        )

    except Exception as e:
        print(f"[ERROR] Run {run_id} failed for {sample_name}: {e}")
        import traceback

        traceback.print_exc()
        return RunResult(
            run_id=run_id,
            success=False,
            duration_ms=0.0,
            matched_rgb_hash="",
            unique_color_count=0,
            perceptual_error={"mean_error": 0.0, "max_error": 0.0, "std_error": 0.0},
            dimensions={"width": 0, "height": 0},
            solid_pixel_count=0,
            error_message=str(e),
        )


def run_ab_comparison(
    sample_path: str,
    lut_path: str,
    color_mode: str,
    num_runs: int,
) -> Tuple[StrategyResult, StrategyResult]:
    """
    Run A/B comparison for a single sample.

    Args:
        sample_path: Path to sample image
        lut_path: Path to LUT file
        color_mode: Color mode (CMYW/RYBW)
        num_runs: Number of runs per strategy

    Returns:
        Tuple of (RGB_EUCLIDEAN results, DELTAE2000 results)
    """
    sample_name = os.path.basename(sample_path)
    print(f"\n{'=' * 70}")
    print(f"SAMPLE: {sample_name}")
    print("=" * 70)

    # Run RGB_EUCLIDEAN
    print(f"\n[STRATEGY] Running RGB_EUCLIDEAN ({num_runs} runs)...")
    rgb_runs = []
    for i in range(num_runs):
        print(f"  Run {i + 1}/{num_runs}...", end=" ")
        result = process_single_run(
            sample_path,
            lut_path,
            color_mode,
            MatchStrategy.RGB_EUCLIDEAN,
            i + 1,
        )
        rgb_runs.append(result)
        if result.success:
            print(f"[OK] {result.duration_ms:.2f}ms")
        else:
            print(f"[FAILED]")

    rgb_result = StrategyResult(
        strategy="RGB_EUCLIDEAN",
        sample_name=sample_name,
        runs=rgb_runs,
    )

    # Run DELTAE2000
    print(f"\n[STRATEGY] Running DELTAE2000 ({num_runs} runs)...")
    delta_runs = []
    for i in range(num_runs):
        print(f"  Run {i + 1}/{num_runs}...", end=" ")
        result = process_single_run(
            sample_path,
            lut_path,
            color_mode,
            MatchStrategy.DELTAE2000,
            i + 1,
        )
        delta_runs.append(result)
        if result.success:
            print(f"[OK] {result.duration_ms:.2f}ms")
        else:
            print(f"[FAILED]")

    delta_result = StrategyResult(
        strategy="DELTAE2000",
        sample_name=sample_name,
        runs=delta_runs,
    )

    # Print comparison summary
    print(f"\n[SUMMARY] Comparison for {sample_name}:")
    print(f"  RGB_EUCLIDEAN:")
    print(f"    Mean duration: {rgb_result.get_mean_duration():.2f}ms")
    print(f"    Stable: {rgb_result.is_stable()}")
    print(f"  DELTAE2000:")
    print(f"    Mean duration: {delta_result.get_mean_duration():.2f}ms")
    print(f"    Stable: {delta_result.is_stable()}")
    if rgb_result.get_mean_duration() > 0:
        ratio = delta_result.get_mean_duration() / rgb_result.get_mean_duration()
        print(f"  Duration ratio (ΔE2000 / RGB): {ratio:.2f}x")

    return rgb_result, delta_result


def main():
    """Main execution function."""
    print("=" * 70)
    print("A/B COMPARISON: RGB_EUCLIDEAN vs DELTAE2000")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Project root: {project_root}")
    print()

    # Parse command line arguments
    lut_path = DEFAULT_LUT_PATH
    color_mode = DEFAULT_COLOR_MODE
    num_runs = DEFAULT_RUNS

    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--lut-path" and i + 1 < len(sys.argv):
            lut_path = sys.argv[i + 2]
        elif arg == "--color-mode" and i + 1 < len(sys.argv):
            color_mode = sys.argv[i + 2]
        elif arg == "--runs" and i + 1 < len(sys.argv):
            num_runs = int(sys.argv[i + 2])
        elif arg == "--help":
            print("Usage: python ab_comparison.py [options]")
            print("Options:")
            print("  --lut-path PATH    Path to LUT .npy file")
            print("  --color-mode MODE  Color mode (CMYW/RYBW)")
            print("  --runs N           Number of runs per strategy (default: 3)")
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
    print(f"[CONFIG] Runs per strategy: {num_runs}")
    print(f"[CONFIG] Quantize colors: {QUANTIZE_COLORS}")
    print(f"[CONFIG] Target width: {TARGET_WIDTH_MM} mm")

    # Verify sample files exist
    sample_paths = []
    for sample_file in SAMPLE_FILES:
        sample_path = SAMPLE_DIR / sample_file
        if not sample_path.exists():
            print(f"[ERROR] Sample file not found: {sample_path}")
            return 1
        sample_paths.append(str(sample_path))

    print(f"[CONFIG] Sample files: {len(sample_paths)}")
    for i, path in enumerate(sample_paths, 1):
        print(f"  {i}. {os.path.basename(path)}")

    # Run A/B comparison for all samples
    all_results = []
    for sample_path in sample_paths:
        rgb_result, delta_result = run_ab_comparison(
            sample_path, lut_path, color_mode, num_runs
        )
        all_results.append(
            {
                "sample": os.path.basename(sample_path),
                "rgb_euclidean": asdict(rgb_result),
                "deltae2000": asdict(delta_result),
            }
        )

    # Compile summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "lut_path": lut_path,
        "color_mode": color_mode,
        "num_runs": num_runs,
        "parameters": {
            "target_width_mm": TARGET_WIDTH_MM,
            "quantize_colors": QUANTIZE_COLORS,
            "auto_bg": AUTO_BG,
            "bg_tol": BG_TOL,
            "blur_kernel": BLUR_KERNEL,
            "smooth_sigma": SMOOTH_SIGMA,
        },
        "results": all_results,
    }

    # Save evidence file
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    evidence_path = EVIDENCE_DIR / "task-6-ab-raw-data.json"

    with open(evidence_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print("A/B COMPARISON COMPLETE")
    print("=" * 70)
    print(f"Evidence saved to: {evidence_path}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
