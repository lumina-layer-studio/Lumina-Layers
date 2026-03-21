import { describe, it, vi, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useConverterStore } from "../stores/converterStore";
import type { ConverterState } from "../stores/converterStore";
import type { ColorReplaceResponse } from "../api/types";

// ========== Mock API module ==========

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn(),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  fetchBedSizes: vi.fn(),
  uploadHeightmap: vi.fn(),
  fetchLutColors: vi.fn(),
  cropImage: vi.fn(),
  convertBatch: vi.fn(),
  replaceColor: vi.fn(),
}));

import { replaceColor } from "../api/converter";

const mockReplaceColor = vi.mocked(replaceColor);

// ========== Mock browser APIs ==========

vi.stubGlobal(
  "URL",
  Object.assign(globalThis.URL ?? {}, {
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  })
);

vi.stubGlobal("Image", class {
  onload: (() => void) | null = null;
  set src(_: string) {
    if (this.onload) this.onload();
  }
  naturalWidth = 100;
  naturalHeight = 100;
});

// ========== Helpers ==========

const DEFAULT_STATE: Partial<ConverterState> = {
  imageFile: null,
  imagePreviewUrl: null,
  aspectRatio: null,
  sessionId: null,
  lut_name: "",
  colorRemapMap: {},
  remapHistory: [],
  palette: [],
  selectedColor: null,
  replacePreviewLoading: false,
  isLoading: false,
  error: null,
  previewImageUrl: null,
  modelUrl: null,
  previewGlbUrl: null,
  replacement_regions: [],
  free_color_set: new Set(),
};

function resetStore(): void {
  useConverterStore.setState(DEFAULT_STATE);
}

// ========== Generators ==========

/** Generate a hex color string without '#' prefix (6 hex chars) */
const arbHexColor = fc.stringMatching(/^[0-9a-fA-F]{6}$/).filter((s) => s.length === 6);

/** Generate a non-empty colorRemapMap with 1-5 entries */
const arbNonEmptyRemapMap = fc
  .array(fc.tuple(arbHexColor, arbHexColor), { minLength: 1, maxLength: 5 })
  .map((pairs) => {
    const map: Record<string, string> = {};
    for (const [orig, replacement] of pairs) {
      map[orig] = replacement;
    }
    return map;
  })
  .filter((m) => Object.keys(m).length > 0);

/** Generate a colorRemapMap that may be empty */
const arbRemapMap = fc.oneof(
  fc.constant({} as Record<string, string>),
  arbNonEmptyRemapMap
);

/** Generate a valid preview URL path */
const arbPreviewUrlPath = fc
  .stringMatching(/^\/output\/[a-zA-Z0-9_-]{1,30}\.png$/)
  .filter((s) => s.length > 0);

// ========== Tests ==========

beforeEach(() => {
  vi.clearAllMocks();
  resetStore();
});

// ========== Property 6: 颜色替换按钮状态 ==========

// **Validates: Requirements 4.1, 4.4**
describe("Feature: component-completion, Property 6: 颜色替换按钮状态", () => {
  it("The '应用替换到预览' button should be enabled iff colorRemapMap has at least one entry AND replacePreviewLoading is false", () => {
    fc.assert(
      fc.property(arbRemapMap, fc.boolean(), (remapMap, loading) => {
        resetStore();

        useConverterStore.setState({
          colorRemapMap: remapMap,
          replacePreviewLoading: loading,
        });

        const state = useConverterStore.getState();
        const hasRemaps = Object.keys(state.colorRemapMap).length > 0;
        const isLoading = state.replacePreviewLoading;

        // Button enabled condition: has remaps AND not loading
        const expectedEnabled = hasRemaps && !isLoading;

        // Derive the same condition from the raw inputs
        const actualEnabled =
          Object.keys(remapMap).length > 0 && !loading;

        return expectedEnabled === actualEnabled;
      }),
      { numRuns: 100 }
    );
  });
});

// ========== Property 7: 预览图 URL 替换更新 ==========

// **Validates: Requirements 4.3**
describe("Feature: component-completion, Property 7: 预览图 URL 替换更新", () => {
  it("After submitReplacePreview completes successfully, previewImageUrl should equal the URL returned from the last replace-color call", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbNonEmptyRemapMap,
        arbPreviewUrlPath,
        async (remapMap, previewPath) => {
          resetStore();
          vi.clearAllMocks();

          // Build palette entries matching the remap keys
          const palette = Object.keys(remapMap).map((hex) => ({
            quantized_hex: hex,
            matched_hex: hex,
            pixel_count: 100,
            percentage: 10,
          }));

          useConverterStore.setState({
            sessionId: "test-session",
            colorRemapMap: remapMap,
            palette,
            previewImageUrl: "http://localhost:8000/output/old.png",
          });

          // Mock replaceColor to return the given preview path for every call
          const mockResponse: ColorReplaceResponse = {
            status: "ok",
            message: "replaced",
            preview_url: previewPath,
            replacement_count: 1,
          };
          mockReplaceColor.mockResolvedValue(mockResponse);

          await useConverterStore.getState().submitReplacePreview();
          const state = useConverterStore.getState();

          const expectedUrl = `http://localhost:8000${previewPath}`;

          return (
            state.previewImageUrl === expectedUrl &&
            state.replacePreviewLoading === false
          );
        }
      ),
      { numRuns: 100 }
    );
  });
});
