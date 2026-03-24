import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useExtractorStore } from "../stores/extractorStore";
import { ExtractorColorMode, ExtractorPage } from "../api/types";
import type { ExtractResponse } from "../api/types";

// ========== Mock API module ==========

vi.mock("../api/extractor", () => ({
  confirmPalette: vi.fn(),
  extractColors: vi.fn(),
  manualFixCell: vi.fn(),
}));

import { confirmPalette, extractColors } from "../api/extractor";

const mockedExtractColors = vi.mocked(extractColors);
const mockedConfirmPalette = vi.mocked(confirmPalette);

// ========== Mock browser APIs ==========

vi.stubGlobal(
  "URL",
  Object.assign(globalThis.URL ?? {}, {
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  })
);

// ========== Helpers ==========

function resetExtractorStore(): void {
  useExtractorStore.setState({
    imageFile: null,
    imagePreviewUrl: null,
    imageNaturalWidth: null,
    imageNaturalHeight: null,
    color_mode: ExtractorColorMode.FOUR_COLOR_RYBW,
    page: ExtractorPage.PAGE_1,
    corner_points: [],
    offset_x: 0,
    offset_y: 0,
    zoom: 1.0,
    distortion: 0.0,
    vignette_correction: false,
    isLoading: false,
    error: null,
    session_id: null,
    lut_download_url: null,
    warp_view_url: null,
    lut_preview_url: null,
    manualFixLoading: false,
    manualFixError: null,
    page1Extracted: false,
    page2Extracted: false,
    mergeLoading: false,
    mergeError: null,
    page1Extracted_5c: false,
    page2Extracted_5c: false,
    manufacturer: "",
    type: "",
    defaultPalette: [],
    paletteConfirmed: false,
    paletteConfirmLoading: false,
    paletteConfirmError: null,
  });
}

// ========== Generators ==========

const arbCornerPoint = fc.tuple(
  fc.integer({ min: 0, max: 10000 }),
  fc.integer({ min: 0, max: 10000 })
) as fc.Arbitrary<[number, number]>;

const arbFourCorners = fc.array(arbCornerPoint, {
  minLength: 4,
  maxLength: 4,
});

const arbExtractorColorMode = fc.constantFrom(
  ExtractorColorMode.BW,
  ExtractorColorMode.FOUR_COLOR_RYBW,
  ExtractorColorMode.SIX_COLOR,
  ExtractorColorMode.EIGHT_COLOR
);

/** Generate a valid store state for submitExtract (imageFile non-null, 4 corner points). */
const arbValidExtractState = fc.record({
  color_mode: arbExtractorColorMode,
  corner_points: arbFourCorners,
  offset_x: fc.integer({ min: -30, max: 30 }),
  offset_y: fc.integer({ min: -30, max: 30 }),
  zoom: fc.double({ min: 0.8, max: 1.2, noNaN: true, noDefaultInfinity: true }),
  distortion: fc.double({ min: -0.2, max: 0.2, noNaN: true, noDefaultInfinity: true }),
  vignette_correction: fc.boolean(),
});

/** Generate a valid ExtractResponse. */
const arbExtractResponse = fc.record({
  session_id: fc.string({ minLength: 1, maxLength: 40 }),
  status: fc.constant("success"),
  message: fc.string({ minLength: 0, maxLength: 50 }),
  lut_download_url: fc.string({ minLength: 1, maxLength: 80 }),
  warp_view_url: fc.string({ minLength: 1, maxLength: 80 }),
  lut_preview_url: fc.string({ minLength: 1, maxLength: 80 }),
  default_palette: fc.constant([]),
});

const arbPaletteEntry = fc.record({
  color: fc.string({ minLength: 1, maxLength: 16 }),
  material: fc.string({ minLength: 1, maxLength: 16 }),
  hex_color: fc.option(fc.constantFrom("#FFFFFF", "#000000", "#FF0000"), { nil: null }),
  color_name: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
});

// ========== Tests ==========

beforeEach(() => {
  resetExtractorStore();
  vi.clearAllMocks();
});

// **Feature: extractor-calibration-tab, Property 7: API 请求载荷与 Store 状态一致性**
// **Validates: Requirements 6.3**
describe("Feature: extractor-calibration-tab, Property 7: API 请求载荷与 Store 状态一致性", () => {
  it("For any valid ExtractorStore state, submitExtract sends API params matching the store state", async () => {
    await fc.assert(
      fc.asyncProperty(arbValidExtractState, async (stateInput) => {
        resetExtractorStore();
        vi.clearAllMocks();

        // Set up a mock File as imageFile
        const file = new File(["test-data"], "calibration.png", {
          type: "image/png",
        });

        // Set store state
        useExtractorStore.setState({
          imageFile: file,
          corner_points: stateInput.corner_points,
          color_mode: stateInput.color_mode,
          offset_x: stateInput.offset_x,
          offset_y: stateInput.offset_y,
          zoom: stateInput.zoom,
          distortion: stateInput.distortion,
          vignette_correction: stateInput.vignette_correction,
        });

        // Mock extractColors to resolve with a dummy response
        mockedExtractColors.mockResolvedValueOnce({
          session_id: "dummy",
          status: "success",
          message: "ok",
          lut_download_url: "/dummy.npy",
          warp_view_url: "/dummy_warp.png",
          lut_preview_url: "/dummy_preview.png",
          default_palette: [],
        });

        // Call submitExtract
        await useExtractorStore.getState().submitExtract();

        // Verify extractColors was called exactly once
        expect(mockedExtractColors).toHaveBeenCalledTimes(1);

        // Verify the parameters match the store state
        const [calledImage, calledParams] = mockedExtractColors.mock.calls[0];

        expect(calledImage).toBe(file);
        expect(calledParams.corner_points).toEqual(stateInput.corner_points);
        expect(calledParams.color_mode).toBe(stateInput.color_mode);
        expect(calledParams.offset_x).toBe(stateInput.offset_x);
        expect(calledParams.offset_y).toBe(stateInput.offset_y);
        expect(calledParams.zoom).toBe(stateInput.zoom);
        expect(calledParams.distortion).toBe(stateInput.distortion);
        expect(calledParams.vignette_correction).toBe(stateInput.vignette_correction);
      }),
      { numRuns: 100 }
    );
  });
});

describe("Feature: extractor-calibration-tab, Property 11: confirm-palette 请求载荷与 Store 状态一致性", () => {
  it("For any valid metadata and palette, submitConfirmPalette sends confirmPalette payload matching the store state", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string({ maxLength: 20 }),
        fc.string({ maxLength: 20 }),
        fc.array(arbPaletteEntry, { minLength: 1, maxLength: 4 }),
        async (manufacturer, type, palette) => {
          resetExtractorStore();
          vi.clearAllMocks();

          useExtractorStore.setState({
            session_id: "session-1",
            manufacturer,
            type,
            defaultPalette: palette,
          });

          mockedConfirmPalette.mockResolvedValueOnce({
            status: "ok",
            message: "confirmed",
          });

          await useExtractorStore.getState().submitConfirmPalette();

          expect(mockedConfirmPalette).toHaveBeenCalledTimes(1);
          expect(mockedConfirmPalette).toHaveBeenCalledWith({
            session_id: "session-1",
            manufacturer: manufacturer.trim(),
            type: type.trim(),
            palette: palette.map((entry) => ({
              ...entry,
              color_name: entry.color_name?.trim() || null,
            })),
          });

          const state = useExtractorStore.getState();
          expect(state.paletteConfirmed).toBe(true);
          expect(state.paletteConfirmLoading).toBe(false);
          expect(state.paletteConfirmError).toBeNull();
        }
      ),
      { numRuns: 50 }
    );
  });
});

// **Feature: extractor-calibration-tab, Property 8: API 响应字段正确存储**
// **Validates: Requirements 6.5**
describe("Feature: extractor-calibration-tab, Property 8: API 响应字段正确存储", () => {
  it("For any valid ExtractResponse, submitExtract stores session_id, lut_download_url, warp_view_url, lut_preview_url correctly", async () => {
    await fc.assert(
      fc.asyncProperty(arbExtractResponse, async (response: ExtractResponse) => {
        resetExtractorStore();
        vi.clearAllMocks();

        // Set up valid preconditions for submitExtract
        const file = new File(["test-data"], "calibration.png", {
          type: "image/png",
        });
        useExtractorStore.setState({
          imageFile: file,
          corner_points: [
            [0, 0],
            [100, 0],
            [100, 100],
            [0, 100],
          ],
        });

        // Mock extractColors to return the random response
        mockedExtractColors.mockResolvedValueOnce(response);

        // Call submitExtract
        await useExtractorStore.getState().submitExtract();

        // Verify store fields match the response (with base URL prefix)
        const BASE = "http://localhost:8000";
        const state = useExtractorStore.getState();
        expect(state.session_id).toBe(response.session_id);
        expect(state.lut_download_url).toBe(
          response.lut_download_url ? `${BASE}${response.lut_download_url}` : null
        );
        expect(state.warp_view_url).toBe(
          response.warp_view_url ? `${BASE}${response.warp_view_url}` : null
        );
        expect(state.lut_preview_url).toBe(
          response.lut_preview_url ? `${BASE}${response.lut_preview_url}` : null
        );
        expect(state.isLoading).toBe(false);
        expect(state.error).toBeNull();
      }),
      { numRuns: 100 }
    );
  });
});
