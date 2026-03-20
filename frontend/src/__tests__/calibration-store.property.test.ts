import { describe, it } from "vitest";
import * as fc from "fast-check";
import { clampValue } from "../stores/converterStore";

// **Validates: Requirements 6.3**
describe("Feature: calibration-tab-integration, Property 4: clampValue 通用正确性", () => {
  it("clampValue always returns a value within [min, max] for any (value, min, max) where min ≤ max", () => {
    fc.assert(
      fc.property(
        fc
          .tuple(
            fc.double({ noNaN: true, noDefaultInfinity: true }),
            fc.double({ noNaN: true, noDefaultInfinity: true })
          )
          .map(([a, b]) => (a <= b ? ([a, b] as const) : ([b, a] as const))),
        fc.double({ noNaN: true, noDefaultInfinity: true }),
        ([min, max], value) => {
          const result = clampValue(value, min, max);
          return result >= min && result <= max;
        }
      ),
      { numRuns: 100 }
    );
  });
});

import { useCalibrationStore } from "../stores/calibrationStore";

// **Validates: Requirements 6.1, 6.2**
describe("Feature: calibration-tab-integration, Property 5: Store setter 钳制正确性", () => {
  it("setBlockSize always clamps block_size to [3, 10] for any numeric input", () => {
    fc.assert(
      fc.property(
        fc.double({ min: -1000, max: 1000, noNaN: true, noDefaultInfinity: true }),
        (value) => {
          const store = useCalibrationStore.getState();
          store.setBlockSize(value);
          const { block_size } = useCalibrationStore.getState();
          // Reset to default to avoid state leaking
          useCalibrationStore.setState({ block_size: 5 });
          return block_size >= 3 && block_size <= 10;
        }
      ),
      { numRuns: 100 }
    );
  });

  it("setGap always clamps gap to [0.4, 2.0] for any numeric input", () => {
    fc.assert(
      fc.property(
        fc.double({ min: -1000, max: 1000, noNaN: true, noDefaultInfinity: true }),
        (value) => {
          const store = useCalibrationStore.getState();
          store.setGap(value);
          const { gap } = useCalibrationStore.getState();
          // Reset to default to avoid state leaking
          useCalibrationStore.setState({ gap: 0.82 });
          return gap >= 0.4 && gap <= 2.0;
        }
      ),
      { numRuns: 100 }
    );
  });
});

import { useConverterStore } from "../stores/converterStore";
import {
  CalibrationColorMode,
  BackingColor,
} from "../api/types";

// ========== Helpers ==========

/** Extract only data fields from CalibrationStore (no action functions). */
function snapshotCalibrationState() {
  const s = useCalibrationStore.getState();
  return {
    color_mode: s.color_mode,
    block_size: s.block_size,
    gap: s.gap,
    backing: s.backing,
    isLoading: s.isLoading,
    error: s.error,
    downloadUrl: s.downloadUrl,
    previewImageUrl: s.previewImageUrl,
    modelUrl: s.modelUrl,
    statusMessage: s.statusMessage,
  };
}

/** Extract only serializable data fields from ConverterStore (no action functions, no File/Set). */
function snapshotConverterState() {
  const s = useConverterStore.getState();
  return {
    imagePreviewUrl: s.imagePreviewUrl,
    aspectRatio: s.aspectRatio,
    sessionId: s.sessionId,
    lut_name: s.lut_name,
    target_width_mm: s.target_width_mm,
    target_height_mm: s.target_height_mm,
    spacer_thick: s.spacer_thick,
    structure_mode: s.structure_mode,
    color_mode: s.color_mode,
    modeling_mode: s.modeling_mode,
    auto_bg: s.auto_bg,
    bg_tol: s.bg_tol,
    quantize_colors: s.quantize_colors,
    enable_cleanup: s.enable_cleanup,
    separate_backing: s.separate_backing,
    add_loop: s.add_loop,
    loop_width: s.loop_width,
    loop_length: s.loop_length,
    loop_hole: s.loop_hole,
    enable_relief: s.enable_relief,
    heightmap_max_height: s.heightmap_max_height,
    enable_outline: s.enable_outline,
    outline_width: s.outline_width,
    enable_cloisonne: s.enable_cloisonne,
    wire_width_mm: s.wire_width_mm,
    wire_height_mm: s.wire_height_mm,
    enable_coating: s.enable_coating,
    coating_height_mm: s.coating_height_mm,
    isLoading: s.isLoading,
    error: s.error,
    previewImageUrl: s.previewImageUrl,
    modelUrl: s.modelUrl,
  };
}

// ========== Generators ==========

const arbCalibrationColorMode = fc.constantFrom(
  CalibrationColorMode.BW,
  CalibrationColorMode.FOUR_COLOR,
  CalibrationColorMode.SIX_COLOR,
  CalibrationColorMode.EIGHT_COLOR
);

const arbBackingColor = fc.constantFrom(
  BackingColor.WHITE,
  BackingColor.CYAN,
  BackingColor.MAGENTA,
  BackingColor.YELLOW,
  BackingColor.RED,
  BackingColor.BLUE
);

const arbCalibrationMutation = fc.record({
  color_mode: arbCalibrationColorMode,
  block_size: fc.double({ min: -100, max: 200, noNaN: true, noDefaultInfinity: true }),
  gap: fc.double({ min: -10, max: 10, noNaN: true, noDefaultInfinity: true }),
  backing: arbBackingColor,
});

const arbConverterMutation = fc.record({
  lut_name: fc.string({ minLength: 0, maxLength: 20 }),
  target_width_mm: fc.double({ min: -100, max: 500, noNaN: true, noDefaultInfinity: true }),
  target_height_mm: fc.double({ min: -100, max: 500, noNaN: true, noDefaultInfinity: true }),
  spacer_thick: fc.double({ min: -10, max: 10, noNaN: true, noDefaultInfinity: true }),
  auto_bg: fc.boolean(),
  bg_tol: fc.double({ min: -50, max: 200, noNaN: true, noDefaultInfinity: true }),
  quantize_colors: fc.integer({ min: 1, max: 300 }),
  enable_cleanup: fc.boolean(),
  separate_backing: fc.boolean(),
  add_loop: fc.boolean(),
  enable_outline: fc.boolean(),
  outline_width: fc.double({ min: 0, max: 15, noNaN: true, noDefaultInfinity: true }),
  enable_coating: fc.boolean(),
  coating_height_mm: fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
});

// **Validates: Requirements 4.1, 4.2, 4.3**
describe("Feature: calibration-tab-integration, Property 1: 双向状态隔离", () => {
  it("CalibrationStore changes do not affect ConverterStore state", () => {
    fc.assert(
      fc.property(arbCalibrationMutation, (mutation) => {
        // Snapshot ConverterStore before mutation
        const before = snapshotConverterState();

        // Apply random mutations to CalibrationStore
        const calStore = useCalibrationStore.getState();
        calStore.setColorMode(mutation.color_mode);
        calStore.setBlockSize(mutation.block_size);
        calStore.setGap(mutation.gap);
        calStore.setBacking(mutation.backing);

        // Snapshot ConverterStore after mutation
        const after = snapshotConverterState();

        // Reset CalibrationStore to defaults
        useCalibrationStore.setState({
          color_mode: CalibrationColorMode.FOUR_COLOR,
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

        // Verify ConverterStore is unchanged
        return JSON.stringify(before) === JSON.stringify(after);
      }),
      { numRuns: 100 }
    );
  });

  it("ConverterStore changes do not affect CalibrationStore state", () => {
    fc.assert(
      fc.property(arbConverterMutation, (mutation) => {
        // Snapshot CalibrationStore before mutation
        const before = snapshotCalibrationState();

        // Apply random mutations to ConverterStore via setter methods
        const convStore = useConverterStore.getState();
        convStore.setLutName(mutation.lut_name);
        convStore.setTargetWidthMm(mutation.target_width_mm);
        convStore.setTargetHeightMm(mutation.target_height_mm);
        convStore.setSpacerThick(mutation.spacer_thick);
        convStore.setAutoBg(mutation.auto_bg);
        convStore.setBgTol(mutation.bg_tol);
        convStore.setQuantizeColors(mutation.quantize_colors);
        convStore.setEnableCleanup(mutation.enable_cleanup);
        convStore.setSeparateBacking(mutation.separate_backing);
        convStore.setAddLoop(mutation.add_loop);
        convStore.setEnableOutline(mutation.enable_outline);
        convStore.setOutlineWidth(mutation.outline_width);
        convStore.setEnableCoating(mutation.enable_coating);
        convStore.setCoatingHeightMm(mutation.coating_height_mm);

        // Snapshot CalibrationStore after mutation
        const after = snapshotCalibrationState();

        // Reset ConverterStore to defaults
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
          enable_outline: false,
          outline_width: 2.0,
          enable_coating: false,
          coating_height_mm: 0.08,
        });

        // Verify CalibrationStore is unchanged
        return JSON.stringify(before) === JSON.stringify(after);
      }),
      { numRuns: 100 }
    );
  });
});

import { vi, beforeEach, afterEach } from "vitest";
import { calibrationGenerate } from "../api/calibration";

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
}));

const mockCalibrationGenerate = vi.mocked(calibrationGenerate);

// **Validates: Requirements 3.1**
describe("Feature: calibration-tab-integration, Property 6: API 请求载荷与 Store 状态一致性", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset store to defaults before each test
    useCalibrationStore.setState({
      color_mode: CalibrationColorMode.FOUR_COLOR,
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
    vi.restoreAllMocks();
  });

  const arbValidCalibrationState = fc.record({
    color_mode: arbCalibrationColorMode,
    block_size: fc.double({ min: 3, max: 10, noNaN: true, noDefaultInfinity: true }),
    gap: fc.double({ min: 0.4, max: 2.0, noNaN: true, noDefaultInfinity: true }),
    backing: arbBackingColor,
  });

  it("submitGenerate sends API request body matching current store state", async () => {
    await fc.assert(
      fc.asyncProperty(arbValidCalibrationState, async (state) => {
        // Set random valid state in the store
        const store = useCalibrationStore.getState();
        store.setColorMode(state.color_mode);
        store.setBlockSize(state.block_size);
        store.setGap(state.gap);
        store.setBacking(state.backing);

        // Mock API to return success
        mockCalibrationGenerate.mockResolvedValueOnce({
          status: "ok",
          message: "success",
          download_url: "/test.3mf",
          preview_url: null,
        });

        // Call submitGenerate
        await useCalibrationStore.getState().submitGenerate();

        // Verify the API was called with the correct payload
        const currentState = useCalibrationStore.getState();
        const callArgs = mockCalibrationGenerate.mock.calls[
          mockCalibrationGenerate.mock.calls.length - 1
        ][0];

        return (
          callArgs.color_mode === currentState.color_mode &&
          callArgs.block_size === currentState.block_size &&
          callArgs.gap === currentState.gap &&
          callArgs.backing === currentState.backing
        );
      }),
      { numRuns: 100 }
    );
  });
});
