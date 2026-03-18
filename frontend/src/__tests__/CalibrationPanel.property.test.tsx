/**
 * Property 2: All color modes enable Block_Size and Gap sliders
 *
 * Tag: Feature: calibration-swatch-config, Property 2: All color modes enable Block_Size and Gap sliders
 *
 * **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 5.1**
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import * as fc from "fast-check";
import CalibrationPanel from "../components/CalibrationPanel";
import { useCalibrationStore } from "../stores/calibrationStore";
import { CalibrationColorMode, BackingColor } from "../api/types";

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
}));

beforeEach(() => {
  useCalibrationStore.setState({
    color_mode: CalibrationColorMode.FOUR_COLOR_CMYW,
    block_size: 5,
    gap: 0.82,
    backing: BackingColor.WHITE,
    isLoading: false,
    error: null,
    downloadUrl: null,
    previewImageUrl: null,
    modelUrl: null,
    statusMessage: null,
  });
});

afterEach(() => {
  cleanup();
});

// Generator: enumerate all CalibrationColorMode values
const arbCalibrationColorMode = fc.constantFrom(
  ...Object.values(CalibrationColorMode)
);

describe("Feature: calibration-swatch-config, Property 2: All color modes enable Block_Size and Gap sliders", () => {
  it("Block_Size and Gap sliders are NOT disabled for any CalibrationColorMode", () => {
    fc.assert(
      fc.property(arbCalibrationColorMode, (mode) => {
        // Set the color mode in the store
        useCalibrationStore.setState({ color_mode: mode });

        // Render the CalibrationPanel
        const { unmount } = render(<CalibrationPanel />);

        // Query all sliders (input[type="range"])
        const sliders = screen.getAllByRole("slider");

        // There should be at least 2 sliders: Block_Size and Gap
        expect(sliders.length).toBeGreaterThanOrEqual(2);

        // Block_Size slider (first) should NOT be disabled
        const blockSizeSlider = sliders[0];
        expect(blockSizeSlider).not.toBeDisabled();

        // Gap slider (second) should NOT be disabled
        const gapSlider = sliders[1];
        expect(gapSlider).not.toBeDisabled();

        // Cleanup after each iteration
        unmount();
      }),
      { numRuns: 100 }
    );
  });
});
