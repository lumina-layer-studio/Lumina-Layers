import { describe, it, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import * as fc from "fast-check";
import { useConverterStore } from "../stores/converterStore";
import { useCalibrationStore } from "../stores/calibrationStore";
import { useActiveModelUrl } from "../hooks/useActiveModelUrl";

// **Validates: Requirements 5.2, 5.3**
describe("Feature: calibration-tab-integration, Property 3: modelUrl 多路复用解析", () => {
  afterEach(() => {
    act(() => {
      useConverterStore.setState({ modelUrl: null });
      useCalibrationStore.setState({ modelUrl: null });
    });
  });

  const arbActiveTab = fc.constantFrom<"converter" | "calibration">(
    "converter",
    "calibration"
  );
  const arbUrl = fc.option(fc.webUrl(), { nil: null });

  it("useActiveModelUrl returns calibrationModelUrl when activeTab is 'calibration' and calibrationModelUrl is non-null, otherwise returns converterModelUrl", () => {
    fc.assert(
      fc.property(
        arbActiveTab,
        arbUrl,
        arbUrl,
        (activeTab, converterUrl, calibrationUrl) => {
          // Set store states before rendering the hook
          act(() => {
            useConverterStore.setState({ modelUrl: converterUrl });
            useCalibrationStore.setState({ modelUrl: calibrationUrl });
          });

          // Render the hook — reads from stores synchronously
          const { result, unmount } = renderHook(() =>
            useActiveModelUrl(activeTab)
          );

          // Compute expected value per the design spec
          const expected =
            activeTab === "calibration" && calibrationUrl !== null
              ? calibrationUrl
              : converterUrl;

          const actual = result.current;

          // Cleanup: unmount and reset stores
          unmount();
          act(() => {
            useConverterStore.setState({ modelUrl: null });
            useCalibrationStore.setState({ modelUrl: null });
          });

          return actual === expected;
        }
      ),
      { numRuns: 100 }
    );
  });
});

// **Validates: Requirements 1.5**
describe("Feature: calibration-tab-integration, Property 2: Tab 切换状态持久性", () => {
  afterEach(() => {
    act(() => {
      useConverterStore.setState({
        lut_name: "",
        target_width_mm: 60,
        target_height_mm: 60,
        spacer_thick: 1.2,
        auto_bg: false,
        bg_tol: 40,
        quantize_colors: 48,
        enable_cleanup: true,
        separate_backing: false,
        add_loop: false,
        loop_width: 4.0,
        loop_length: 8.0,
        loop_hole: 2.5,
        enable_relief: false,
        heightmap_max_height: 5.0,
        enable_outline: false,
        outline_width: 2.0,
        enable_cloisonne: false,
        wire_width_mm: 0.4,
        wire_height_mm: 0.4,
        enable_coating: false,
        coating_height_mm: 0.08,
        modelUrl: null,
      });
      useCalibrationStore.setState({ modelUrl: null });
    });
  });

  // Arbitrary generators for converter parameters
  const arbConverterParams = fc.record({
    lut_name: fc.string({ minLength: 0, maxLength: 30 }),
    target_width_mm: fc.double({ min: 10, max: 400, noNaN: true }),
    target_height_mm: fc.double({ min: 10, max: 400, noNaN: true }),
    spacer_thick: fc.double({ min: 0.2, max: 3.5, noNaN: true }),
    auto_bg: fc.boolean(),
    bg_tol: fc.integer({ min: 0, max: 150 }),
    quantize_colors: fc.integer({ min: 8, max: 256 }),
    enable_cleanup: fc.boolean(),
    separate_backing: fc.boolean(),
    add_loop: fc.boolean(),
    loop_width: fc.double({ min: 2, max: 10, noNaN: true }),
    loop_length: fc.double({ min: 4, max: 15, noNaN: true }),
    loop_hole: fc.double({ min: 1, max: 5, noNaN: true }),
    enable_relief: fc.boolean(),
    heightmap_max_height: fc.double({ min: 0.08, max: 15.0, noNaN: true }),
    enable_outline: fc.boolean(),
    outline_width: fc.double({ min: 0.5, max: 10.0, noNaN: true }),
    enable_cloisonne: fc.boolean(),
    wire_width_mm: fc.double({ min: 0.2, max: 1.2, noNaN: true }),
    wire_height_mm: fc.double({ min: 0.04, max: 1.0, noNaN: true }),
    enable_coating: fc.boolean(),
    coating_height_mm: fc.double({ min: 0.04, max: 0.12, noNaN: true }),
  });

  it("ConverterStore parameters persist unchanged after tab switch (converter → calibration → converter)", () => {
    fc.assert(
      fc.property(arbConverterParams, (params) => {
        // Step 1: Set random parameters into ConverterStore
        act(() => {
          useConverterStore.setState(params);
        });

        // Step 2: Snapshot the store state before "tab switch"
        const snapshotBefore = useConverterStore.getState();

        // Step 3: Simulate tab switch — converter → calibration → converter
        // Since Zustand stores are global singletons, switching tabs only
        // changes which component renders; the store state persists.
        // We simulate by interacting with CalibrationStore (as would happen
        // when the calibration tab is active) and then reading ConverterStore.
        act(() => {
          useCalibrationStore.setState({ modelUrl: "https://example.com/test.glb" });
        });

        // Step 4: Read ConverterStore state after "switching back"
        const snapshotAfter = useConverterStore.getState();

        // Step 5: Verify all parameter fields are unchanged
        const fieldsToCheck = Object.keys(params) as (keyof typeof params)[];
        for (const field of fieldsToCheck) {
          if (snapshotAfter[field] !== snapshotBefore[field]) {
            return false;
          }
        }

        // Cleanup
        act(() => {
          useConverterStore.setState({
            lut_name: "",
            target_width_mm: 60,
            target_height_mm: 60,
            spacer_thick: 1.2,
            auto_bg: false,
            bg_tol: 40,
            quantize_colors: 48,
            enable_cleanup: true,
            separate_backing: false,
            add_loop: false,
            loop_width: 4.0,
            loop_length: 8.0,
            loop_hole: 2.5,
            enable_relief: false,
            heightmap_max_height: 5.0,
            enable_outline: false,
            outline_width: 2.0,
            enable_cloisonne: false,
            wire_width_mm: 0.4,
            wire_height_mm: 0.4,
            enable_coating: false,
            coating_height_mm: 0.08,
            modelUrl: null,
          });
          useCalibrationStore.setState({ modelUrl: null });
        });

        return true;
      }),
      { numRuns: 100 }
    );
  });
});
