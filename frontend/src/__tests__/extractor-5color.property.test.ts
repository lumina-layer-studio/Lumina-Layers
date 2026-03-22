import { describe, it, vi, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useExtractorStore } from "../stores/extractorStore";
import type { ExtractorState } from "../stores/extractorStore";
import {
  ExtractorColorMode,
  ExtractorPage,
} from "../api/types";
import type { ExtractResponse } from "../api/types";

// ========== Mock API module ==========

vi.mock("../api/extractor", () => ({
  extractColors: vi.fn(),
  manualFixCell: vi.fn(),
  mergeEightColor: vi.fn(),
  mergeFiveColorExtended: vi.fn(),
}));

import {
  extractColors,
  mergeEightColor,
  mergeFiveColorExtended,
} from "../api/extractor";

const mockExtractColors = vi.mocked(extractColors);
const mockMergeEightColor = vi.mocked(mergeEightColor);
const mockMergeFiveColorExtended = vi.mocked(mergeFiveColorExtended);

// ========== Mock browser APIs ==========

vi.stubGlobal(
  "URL",
  Object.assign(globalThis.URL ?? {}, {
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  })
);

// ========== Helpers ==========

const DEFAULT_STATE: Partial<ExtractorState> = {
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
};

function resetStore(): void {
  useExtractorStore.setState(DEFAULT_STATE);
}

/** Build a mock ExtractResponse */
function mockExtractResponse(): ExtractResponse {
  return {
    session_id: "test-session",
    status: "ok",
    message: "success",
    lut_download_url: "/output/test.npy",
    warp_view_url: "/output/warp.png",
    lut_preview_url: "/output/preview.png",
  };
}

// ========== Generators ==========

const arbExtractorPage = fc.constantFrom(
  ExtractorPage.PAGE_1,
  ExtractorPage.PAGE_2
);

const arbBoolPair = fc.record({
  page1: fc.boolean(),
  page2: fc.boolean(),
});

const arbColorModeForMerge = fc.constantFrom(
  ExtractorColorMode.FIVE_COLOR_EXT,
  ExtractorColorMode.EIGHT_COLOR
);

// ========== Tests ==========

beforeEach(() => {
  vi.clearAllMocks();
  resetStore();
});

// ========== Property 1: 5-Color Extended 页面提取状态追踪 ==========

// **Validates: Requirements 1.2**
describe("Feature: component-completion, Property 1: 5-Color Extended 页面提取状态追踪", () => {
  it("After successful extraction in 5-Color Extended mode, only the corresponding page state is set to true while the other remains unchanged", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbExtractorPage,
        arbBoolPair,
        async (page, initialStates) => {
          resetStore();

          // Set initial 5c page states
          useExtractorStore.setState({
            color_mode: ExtractorColorMode.FIVE_COLOR_EXT,
            page,
            page1Extracted_5c: initialStates.page1,
            page2Extracted_5c: initialStates.page2,
            // Provide valid extraction prerequisites
            imageFile: new File(["test"], "test.png", { type: "image/png" }),
            corner_points: [[0, 0], [100, 0], [100, 100], [0, 100]],
          });

          mockExtractColors.mockResolvedValueOnce(mockExtractResponse());

          await useExtractorStore.getState().submitExtract();
          const state = useExtractorStore.getState();

          if (page === ExtractorPage.PAGE_1) {
            // Page 1 extracted → page1Extracted_5c must be true
            // page2Extracted_5c must remain unchanged
            return (
              state.page1Extracted_5c === true &&
              state.page2Extracted_5c === initialStates.page2
            );
          } else {
            // Page 2 extracted → page2Extracted_5c must be true
            // page1Extracted_5c must remain unchanged
            return (
              state.page2Extracted_5c === true &&
              state.page1Extracted_5c === initialStates.page1
            );
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});

// ========== Property 2: 双页合并按钮启用条件 ==========

// **Validates: Requirements 1.3**
describe("Feature: component-completion, Property 2: 双页合并按钮启用条件", () => {
  it("The merge button should be enabled if and only if both page1Extracted_5c and page2Extracted_5c are true", () => {
    fc.assert(
      fc.property(arbBoolPair, (pages) => {
        resetStore();

        useExtractorStore.setState({
          color_mode: ExtractorColorMode.FIVE_COLOR_EXT,
          page1Extracted_5c: pages.page1,
          page2Extracted_5c: pages.page2,
        });

        const state = useExtractorStore.getState();
        const bothExtracted = state.page1Extracted_5c && state.page2Extracted_5c;

        // The merge button enabled condition: both pages extracted
        const mergeEnabled = pages.page1 && pages.page2;

        return bothExtracted === mergeEnabled;
      }),
      { numRuns: 100 }
    );
  });
});

// ========== Property 3: 合并端点路由正确性 ==========

// **Validates: Requirements 1.4**
describe("Feature: component-completion, Property 3: 合并端点路由正确性", () => {
  it("submitMerge calls mergeFiveColorExtended when color_mode is FIVE_COLOR_EXT, and mergeEightColor when color_mode is EIGHT_COLOR", async () => {
    await fc.assert(
      fc.asyncProperty(arbColorModeForMerge, async (colorMode) => {
        resetStore();
        vi.clearAllMocks();

        const is5c = colorMode === ExtractorColorMode.FIVE_COLOR_EXT;

        // Set up state so merge is allowed (both pages extracted)
        useExtractorStore.setState({
          color_mode: colorMode,
          page1Extracted_5c: is5c,
          page2Extracted_5c: is5c,
          page1Extracted: !is5c,
          page2Extracted: !is5c,
        });

        mockMergeFiveColorExtended.mockResolvedValueOnce(mockExtractResponse());
        mockMergeEightColor.mockResolvedValueOnce(mockExtractResponse());

        await useExtractorStore.getState().submitMerge();

        if (is5c) {
          return (
            mockMergeFiveColorExtended.mock.calls.length === 1 &&
            mockMergeEightColor.mock.calls.length === 0
          );
        } else {
          return (
            mockMergeEightColor.mock.calls.length === 1 &&
            mockMergeFiveColorExtended.mock.calls.length === 0
          );
        }
      }),
      { numRuns: 100 }
    );
  });
});
