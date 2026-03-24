/**
 * Property 2: Block_Size and Gap sliders follow mode-specific enable rules.
 *
 * Tag: Feature: calibration-swatch-config, Property 2: Block_Size and Gap sliders follow mode rules
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

describe("Feature: calibration-swatch-config, Property 2: Block_Size and Gap sliders follow mode rules", () => {
  it("Block_Size and Gap sliders are always enabled regardless of color mode", () => {
    fc.assert(
      fc.property(arbCalibrationColorMode, (mode) => {
        useCalibrationStore.setState({ color_mode: mode });

        const { unmount } = render(<CalibrationPanel />);

        const sliders = screen.getAllByRole("slider");

        expect(sliders.length).toBeGreaterThanOrEqual(2);

        expect(sliders[0]).not.toBeDisabled();
        expect(sliders[1]).not.toBeDisabled();

        unmount();
      }),
      { numRuns: 100 }
    );
  }, 15000);
});
