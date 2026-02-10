"""
Edge Case Testing Script for High-Fidelity DeltaE2000 Strategy

This script tests boundary conditions and error handling for the match strategy:
1. Solid color images (single unique color)
2. Few unique colors (1-2 colors)
3. Invalid strategy names
4. Empty/transparent images
5. dtype stability (uint8 vs float32)
"""

import sys
import os
import time
import json
import traceback
from typing import Dict, Any, List, Tuple
import numpy as np
from scipy.spatial import KDTree

# Add project root to path
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, project_root)

from config import MatchStrategy, PrinterConfig
from core.image_processing_factory.processing_modes import HighFidelityStrategy
from core.color_matchers import match_colors_deltae2000


class EdgeCaseTester:
    """Test runner for edge case scenarios."""

    def __init__(self, output_dir: str = ".sisyphus/evidence"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.results = []

        # Create a minimal LUT for testing
        self.lut_rgb = self._create_test_lut()
        self.ref_stacks = self._create_test_ref_stacks()
        self.kdtree = KDTree(self.lut_rgb.astype(float))

    def _create_test_lut(self) -> np.ndarray:
        """Create a minimal test LUT with representative colors."""
        # Basic CMYW palette + some intermediate colors
        lut = np.array(
            [
                [255, 255, 255],  # White
                [0, 134, 214],  # Cyan
                [236, 0, 140],  # Magenta
                [244, 238, 42],  # Yellow
                [128, 0, 0],  # Dark red
                [0, 128, 0],  # Dark green
                [0, 0, 128],  # Dark blue
                [128, 128, 128],  # Gray
            ],
            dtype=np.uint8,
        )
        return lut

    def _create_test_ref_stacks(self) -> np.ndarray:
        """Create test ref_stacks matching LUT size."""
        n_colors = len(self.lut_rgb)
        # Simple layer stacks (all white for simplicity)
        stacks = np.zeros((n_colors, PrinterConfig.COLOR_LAYERS), dtype=np.int32)
        for i in range(n_colors):
            stacks[i] = [0, 1, 2, 3, 0]  # Sample layer composition
        return stacks

    def run_test(self, test_name: str, test_func: callable) -> Dict[str, Any]:
        """Run a single test and capture results."""
        print(f"\n{'=' * 60}")
        print(f"Running: {test_name}")
        print(f"{'=' * 60}")

        result = {
            "test_name": test_name,
            "success": False,
            "error": None,
            "duration_ms": 0,
            "details": {},
        }

        start_time = time.time()

        try:
            details = test_func()
            result["success"] = True
            result["details"] = details
            print(f"[PASS] {test_name}")
        except Exception as e:
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()
            print(f"[FAIL] {test_name}")
            print(f"   Error: {e}")

        result["duration_ms"] = (time.time() - start_time) * 1000
        self.results.append(result)

        return result

    def test_solid_color_rgb_euclidean(self) -> Dict[str, Any]:
        """Test solid color image with RGB Euclidean strategy."""
        # Create a pure red image
        h, w = 100, 100
        rgb_arr = np.zeros((h, w, 3), dtype=np.uint8)
        rgb_arr[:, :, 0] = 255  # Pure red

        strategy = HighFidelityStrategy()
        matched_rgb, material_matrix, quantized_image, debug_data = strategy.process(
            rgb_arr=rgb_arr,
            target_h=h,
            target_w=w,
            lut_rgb=self.lut_rgb,
            ref_stacks=self.ref_stacks,
            kdtree=self.kdtree,
            quantize_colors=8,
            blur_kernel=0,
            smooth_sigma=0,
            match_strategy=MatchStrategy.RGB_EUCLIDEAN,
        )

        # Verify output
        unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)

        return {
            "input_shape": rgb_arr.shape,
            "output_shape": matched_rgb.shape,
            "unique_colors_count": len(unique_colors),
            "input_color": "pure red (255, 0, 0)",
            "output_sample": matched_rgb[0, 0].tolist(),
        }

    def test_solid_color_deltae2000(self) -> Dict[str, Any]:
        """Test solid color image with DeltaE2000 strategy."""
        # Create a pure red image
        h, w = 100, 100
        rgb_arr = np.zeros((h, w, 3), dtype=np.uint8)
        rgb_arr[:, :, 0] = 255  # Pure red

        strategy = HighFidelityStrategy()
        matched_rgb, material_matrix, quantized_image, debug_data = strategy.process(
            rgb_arr=rgb_arr,
            target_h=h,
            target_w=w,
            lut_rgb=self.lut_rgb,
            ref_stacks=self.ref_stacks,
            kdtree=self.kdtree,
            quantize_colors=8,
            blur_kernel=0,
            smooth_sigma=0,
            match_strategy=MatchStrategy.DELTAE2000,
        )

        # Verify output
        unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)

        return {
            "input_shape": rgb_arr.shape,
            "output_shape": matched_rgb.shape,
            "unique_colors_count": len(unique_colors),
            "input_color": "pure red (255, 0, 0)",
            "output_sample": matched_rgb[0, 0].tolist(),
        }

    def test_two_unique_colors(self) -> Dict[str, Any]:
        """Test image with only 2 unique colors."""
        h, w = 100, 100
        rgb_arr = np.zeros((h, w, 3), dtype=np.uint8)
        # Half red, half blue
        rgb_arr[:, : w // 2, 0] = 255  # Red half
        rgb_arr[:, w // 2 :, 2] = 255  # Blue half

        # Test both strategies
        results = {}

        for strategy_name in [MatchStrategy.RGB_EUCLIDEAN, MatchStrategy.DELTAE2000]:
            strategy = HighFidelityStrategy()
            matched_rgb, material_matrix, quantized_image, debug_data = (
                strategy.process(
                    rgb_arr=rgb_arr,
                    target_h=h,
                    target_w=w,
                    lut_rgb=self.lut_rgb,
                    ref_stacks=self.ref_stacks,
                    kdtree=self.kdtree,
                    quantize_colors=4,
                    blur_kernel=0,
                    smooth_sigma=0,
                    match_strategy=strategy_name,
                )
            )

            unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)
            results[strategy_name.value] = {
                "unique_colors_count": len(unique_colors),
                "output_sample_red_half": matched_rgb[0, 0].tolist(),
                "output_sample_blue_half": matched_rgb[0, -1].tolist(),
            }

        return results

    def test_invalid_strategy_name(self) -> Dict[str, Any]:
        """Test error handling for invalid strategy name."""
        h, w = 50, 50
        rgb_arr = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)

        strategy = HighFidelityStrategy()
        error_caught = None
        error_message = None

        try:
            _ = strategy.process(
                rgb_arr=rgb_arr,
                target_h=h,
                target_w=w,
                lut_rgb=self.lut_rgb,
                ref_stacks=self.ref_stacks,
                kdtree=self.kdtree,
                quantize_colors=8,
                blur_kernel=0,
                smooth_sigma=0,
                match_strategy="invalid_strategy_name",  # Invalid!
            )
        except ValueError as e:
            error_caught = "ValueError"
            error_message = str(e)
        except Exception as e:
            error_caught = type(e).__name__
            error_message = str(e)

        if error_caught is None:
            raise AssertionError(
                "Expected ValueError for invalid strategy, but no error was raised"
            )

        # Verify error message contains allowed values
        has_allowed_values = any(
            s in error_message for s in ["RGB_EUCLIDEAN", "DELTAE2000", "MatchStrategy"]
        )

        return {
            "error_type": error_caught,
            "error_message": error_message,
            "contains_allowed_values": has_allowed_values,
        }

    def test_transparent_image(self) -> Dict[str, Any]:
        """Test handling of image with transparent regions."""
        h, w = 100, 100
        # Create RGB with some "transparent" regions (black background)
        rgb_arr = np.zeros((h, w, 3), dtype=np.uint8)
        # Add some colored region
        rgb_arr[25:75, 25:75] = [255, 128, 0]  # Orange square in center

        strategy = HighFidelityStrategy()
        matched_rgb, material_matrix, quantized_image, debug_data = strategy.process(
            rgb_arr=rgb_arr,
            target_h=h,
            target_w=w,
            lut_rgb=self.lut_rgb,
            ref_stacks=self.ref_stacks,
            kdtree=self.kdtree,
            quantize_colors=8,
            blur_kernel=0,
            smooth_sigma=0,
            match_strategy=MatchStrategy.RGB_EUCLIDEAN,
        )

        unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)

        return {
            "input_shape": rgb_arr.shape,
            "output_shape": matched_rgb.shape,
            "unique_colors_count": len(unique_colors),
            "center_pixel": matched_rgb[50, 50].tolist(),
            "corner_pixel": matched_rgb[0, 0].tolist(),
        }

    def test_minimal_size_1x1(self) -> Dict[str, Any]:
        """Test minimal image size (1x1 pixels)."""
        h, w = 1, 1
        rgb_arr = np.array([[[128, 128, 128]]], dtype=np.uint8)  # Single gray pixel

        # Test RGB Euclidean
        strategy = HighFidelityStrategy()
        matched_rgb, material_matrix, quantized_image, debug_data = strategy.process(
            rgb_arr=rgb_arr,
            target_h=h,
            target_w=w,
            lut_rgb=self.lut_rgb,
            ref_stacks=self.ref_stacks,
            kdtree=self.kdtree,
            quantize_colors=2,
            blur_kernel=0,
            smooth_sigma=0,
            match_strategy=MatchStrategy.RGB_EUCLIDEAN,
        )

        return {
            "input_shape": rgb_arr.shape,
            "output_shape": matched_rgb.shape,
            "input_color": [128, 128, 128],
            "matched_color": matched_rgb[0, 0].tolist(),
        }

    def test_dtype_uint8(self) -> Dict[str, Any]:
        """Test uint8 dtype input."""
        h, w = 50, 50
        rgb_arr = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)

        strategy = HighFidelityStrategy()
        matched_rgb, material_matrix, quantized_image, debug_data = strategy.process(
            rgb_arr=rgb_arr,
            target_h=h,
            target_w=w,
            lut_rgb=self.lut_rgb,
            ref_stacks=self.ref_stacks,
            kdtree=self.kdtree,
            quantize_colors=8,
            blur_kernel=0,
            smooth_sigma=0,
            match_strategy=MatchStrategy.RGB_EUCLIDEAN,
        )

        return {
            "input_dtype": str(rgb_arr.dtype),
            "output_dtype": str(matched_rgb.dtype),
            "output_shape": matched_rgb.shape,
        }

    def test_dtype_float32(self) -> Dict[str, Any]:
        """Test float32 dtype input."""
        h, w = 50, 50
        # Create float32 image in [0, 1] range
        rgb_arr = np.random.rand(h, w, 3).astype(np.float32)

        # Convert to uint8 as expected by process()
        rgb_arr_uint8 = (rgb_arr * 255).astype(np.uint8)

        strategy = HighFidelityStrategy()
        matched_rgb, material_matrix, quantized_image, debug_data = strategy.process(
            rgb_arr=rgb_arr_uint8,  # Process expects uint8
            target_h=h,
            target_w=w,
            lut_rgb=self.lut_rgb,
            ref_stacks=self.ref_stacks,
            kdtree=self.kdtree,
            quantize_colors=8,
            blur_kernel=0,
            smooth_sigma=0,
            match_strategy=MatchStrategy.RGB_EUCLIDEAN,
        )

        return {
            "original_dtype": str(rgb_arr.dtype),
            "converted_dtype": str(rgb_arr_uint8.dtype),
            "output_dtype": str(matched_rgb.dtype),
            "output_shape": matched_rgb.shape,
        }

    def test_matcher_empty_unique_colors(self) -> Dict[str, Any]:
        """Test deltae2000 matcher with empty unique colors."""
        unique_colors = np.array([], dtype=np.uint8).reshape(0, 3)

        indices = match_colors_deltae2000(unique_colors, self.lut_rgb)

        return {
            "input_shape": unique_colors.shape,
            "output_shape": indices.shape,
            "output_length": len(indices),
        }

    def test_matcher_single_color(self) -> Dict[str, Any]:
        """Test deltae2000 matcher with single color."""
        unique_colors = np.array([[255, 0, 0]], dtype=np.uint8)  # Pure red

        indices = match_colors_deltae2000(unique_colors, self.lut_rgb)

        return {
            "input_color": [255, 0, 0],
            "matched_index": int(indices[0]),
            "matched_color": self.lut_rgb[indices[0]].tolist(),
        }

    def test_matcher_tie_breaking(self) -> Dict[str, Any]:
        """Test tie-breaking stability in deltae2000 matcher."""
        # Create color that might have multiple close matches
        unique_colors = np.array([[128, 128, 128]], dtype=np.uint8)  # Gray

        # Run multiple times to check stability
        results = []
        for i in range(5):
            indices = match_colors_deltae2000(unique_colors, self.lut_rgb)
            results.append(int(indices[0]))

        # All results should be identical
        is_stable = len(set(results)) == 1

        return {
            "input_color": [128, 128, 128],
            "matched_indices": results,
            "is_stable": is_stable,
            "final_index": results[0] if is_stable else None,
        }

    def run_all_tests(self) -> List[Dict[str, Any]]:
        """Run all edge case tests."""
        print(f"\n{'#' * 60}")
        print("# Edge Case Testing for High-Fidelity DeltaE2000 Strategy")
        print(f"{'#' * 60}")

        # Define all tests
        tests = [
            ("Solid Color - RGB Euclidean", self.test_solid_color_rgb_euclidean),
            ("Solid Color - DeltaE2000", self.test_solid_color_deltae2000),
            ("Two Unique Colors", self.test_two_unique_colors),
            ("Invalid Strategy Name", self.test_invalid_strategy_name),
            ("Transparent Image", self.test_transparent_image),
            ("Minimal Size 1x1", self.test_minimal_size_1x1),
            ("dtype uint8", self.test_dtype_uint8),
            ("dtype float32", self.test_dtype_float32),
            ("Matcher - Empty Unique Colors", self.test_matcher_empty_unique_colors),
            ("Matcher - Single Color", self.test_matcher_single_color),
            ("Matcher - Tie Breaking", self.test_matcher_tie_breaking),
        ]

        # Run each test
        for test_name, test_func in tests:
            self.run_test(test_name, test_func)

        return self.results

    def generate_report(self) -> Dict[str, Any]:
        """Generate summary report."""
        passed = sum(1 for r in self.results if r["success"])
        failed = sum(1 for r in self.results if not r["success"])

        report = {
            "summary": {
                "total_tests": len(self.results),
                "passed": passed,
                "failed": failed,
                "success_rate": f"{passed / len(self.results) * 100:.1f}%"
                if self.results
                else "N/A",
            },
            "tests": self.results,
            "recommendations": self._generate_recommendations(),
        }

        return report

    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on test results."""
        recommendations = []

        for result in self.results:
            if not result["success"]:
                recommendations.append(
                    f"Fix {result['test_name']}: {result.get('error', 'Unknown error')}"
                )

        if not recommendations:
            recommendations.append("All edge cases handled correctly. No fixes needed.")

        return recommendations

    def save_report(self, filename: str = "task-5-edge-cases-report.json"):
        """Save report to JSON file."""
        report = self.generate_report()
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n{'=' * 60}")
        print(f"Report saved to: {filepath}")
        print(f"{'=' * 60}")

        return filepath


def main():
    """Main entry point."""
    tester = EdgeCaseTester()
    tester.run_all_tests()

    # Print summary
    print(f"\n{'=' * 60}")
    print("TEST SUMMARY")
    print(f"{'=' * 60}")
    for result in tester.results:
        status = "[PASS]" if result["success"] else "[FAIL]"
        duration = f"{result['duration_ms']:.1f}ms"
        print(f"{status} | {result['test_name']:<40} | {duration}")

    # Save report
    tester.save_report()

    # Exit with error code if any tests failed
    failed_count = sum(1 for r in tester.results if not r["success"])
    if failed_count > 0:
        print(f"\n[ERROR] {failed_count} test(s) failed. See report for details.")
        sys.exit(1)
    else:
        print(f"\n[SUCCESS] All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
