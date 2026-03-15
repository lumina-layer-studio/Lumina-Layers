import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fc from "fast-check";

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
  detectRegion: vi.fn(),
  regionReplace: vi.fn(),
  resetReplacements: vi.fn(),
}));

// ========== Mock browser APIs ==========

vi.stubGlobal(
  "URL",
  Object.assign(globalThis.URL ?? {}, {
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  }),
);

vi.stubGlobal(
  "Image",
  class {
    onload: (() => void) | null = null;
    set src(_: string) {
      if (this.onload) this.onload();
    }
    naturalWidth = 100;
    naturalHeight = 100;
  },
);

import { useConverterStore } from "../stores/converterStore";
import type { RegionReplaceResponse } from "../api/types";

// ========== Generators ==========

/** Generate a valid URL path segment like /api/files/abc123 */
const glbUrlPath = fc
  .stringMatching(/^[a-z0-9]{6,12}$/)
  .map((id) => `/api/files/${id}`);

/** Generate null or a valid GLB URL path */
const optionalGlbUrl: fc.Arbitrary<string | null> = fc.oneof(
  fc.constant(null),
  glbUrlPath,
);

/** Generate a hex color string (6 chars, lowercase) */
const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

/** Generate a single contour polygon (list of [x, y] points) */
const contourPolygon = fc.array(
  fc.tuple(
    fc.float({ min: 0, max: 100, noNaN: true }),
    fc.float({ min: 0, max: 100, noNaN: true }),
  ).map(([x, y]) => [x, y]),
  { minLength: 3, maxLength: 8 },
);

/** Generate color_contours: Record<string, number[][][]> */
const colorContoursData: fc.Arbitrary<Record<string, number[][][]>> = fc
  .dictionary(
    hexColor.map((h) => `#${h}`),
    fc.array(contourPolygon, { minLength: 1, maxLength: 3 }),
    { minKeys: 1, maxKeys: 4 },
  );

/** Generate null or valid color_contours */
const optionalColorContours: fc.Arbitrary<Record<string, number[][][]> | null> =
  fc.oneof(fc.constant(null), colorContoursData);

/** Generate a complete RegionReplaceResponse with random field combinations */
const regionReplaceResponse: fc.Arbitrary<RegionReplaceResponse> = fc.record({
  preview_url: fc.constant("/api/files/preview-mock"),
  preview_glb_url: optionalGlbUrl,
  color_contours: optionalColorContours,
  message: fc.constant("Region color replaced successfully"),
});

/** Generate an existing previewGlbUrl (always non-null, to test preservation) */
const existingGlbUrl = glbUrlPath.map((p) => `http://localhost:8000${p}`);

/** Generate existing colorContours state */
const existingContours: fc.Arbitrary<Record<string, number[][][]>> = fc
  .dictionary(
    hexColor.map((h) => `#${h}`),
    fc.array(contourPolygon, { minLength: 1, maxLength: 2 }),
    { minKeys: 1, maxKeys: 3 },
  );

// ========== Helper: reset store ==========

function resetStore(overrides?: Partial<ReturnType<typeof useConverterStore.getState>>) {
  useConverterStore.setState({
    sessionId: "test-session",
    regionData: {
      regionId: "r1",
      colorHex: "#ff0000",
      pixelCount: 100,
      previewUrl: "/mock",
    },
    replacePreviewLoading: false,
    error: null,
    previewImageUrl: null,
    previewGlbUrl: null,
    colorContours: {},
    threemfDiskPath: null,
    downloadUrl: null,
    ...overrides,
  });
}

// ========== Tests ==========

describe("Feature: region-3d-preview-sync, Property 2: 前端 Store 根据响应字段条件更新 3D 预览状态", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  /**
   * **Validates: Requirements 2.1, 2.2, 3.2**
   *
   * Property 2: For any applyRegionReplace response:
   * - When preview_glb_url is non-null, previewGlbUrl should be updated to the full URL
   * - When preview_glb_url is null, previewGlbUrl should remain unchanged
   * - When color_contours is non-null, colorContours should be updated
   * - When color_contours is null, colorContours should remain unchanged
   */
  describe("Property-Based: applyRegionReplace conditionally updates previewGlbUrl and colorContours", () => {
    it("previewGlbUrl and colorContours update only when response fields are non-null", async () => {
      const { regionReplace } = await import("../api/converter");

      await fc.assert(
        fc.asyncProperty(
          regionReplaceResponse,
          existingGlbUrl,
          existingContours,
          async (response, prevGlbUrl, prevContours) => {
            // Setup: store has existing previewGlbUrl and colorContours
            resetStore({
              previewGlbUrl: prevGlbUrl,
              colorContours: prevContours,
            });

            // Mock API to return the generated response
            (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

            // Act
            await useConverterStore.getState().applyRegionReplace("ff0000");

            const state = useConverterStore.getState();

            // Assert: previewGlbUrl
            if (response.preview_glb_url) {
              // Req 2.1: non-null → updated to full URL
              expect(state.previewGlbUrl).toBe(
                `http://localhost:8000${response.preview_glb_url}`,
              );
            } else {
              // Req 2.2: null → preserved previous value
              expect(state.previewGlbUrl).toBe(prevGlbUrl);
            }

            // Assert: colorContours
            if (response.color_contours) {
              // Req 3.2: non-null → updated
              expect(state.colorContours).toEqual(response.color_contours);
            } else {
              // null → preserved previous value
              expect(state.colorContours).toEqual(prevContours);
            }
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  /**
   * **Validates: Requirements 2.1**
   *
   * When preview_glb_url is a non-empty string, previewGlbUrl is always
   * set to http://localhost:8000 + preview_glb_url.
   */
  describe("Property-Based: non-null preview_glb_url always produces full URL", () => {
    it("previewGlbUrl equals http://localhost:8000 + response.preview_glb_url", async () => {
      const { regionReplace } = await import("../api/converter");

      await fc.assert(
        fc.asyncProperty(glbUrlPath, async (glbPath) => {
          resetStore({ previewGlbUrl: null });

          const response: RegionReplaceResponse = {
            preview_url: "/api/files/preview-mock",
            preview_glb_url: glbPath,
            color_contours: null,
            message: "ok",
          };
          (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

          await useConverterStore.getState().applyRegionReplace("aabbcc");

          expect(useConverterStore.getState().previewGlbUrl).toBe(
            `http://localhost:8000${glbPath}`,
          );
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * **Validates: Requirements 2.2**
   *
   * Unit Test: When preview_glb_url is null, existing previewGlbUrl is preserved.
   */
  describe("Unit: preview_glb_url 为 null 时保持现有 previewGlbUrl", () => {
    it("should preserve existing previewGlbUrl when response has null preview_glb_url", async () => {
      const { regionReplace } = await import("../api/converter");

      const existingUrl = "http://localhost:8000/api/files/existing-glb-123";
      resetStore({ previewGlbUrl: existingUrl });

      const response: RegionReplaceResponse = {
        preview_url: "/api/files/preview-after-replace",
        preview_glb_url: null,
        color_contours: null,
        message: "Region color replaced successfully",
      };
      (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

      await useConverterStore.getState().applyRegionReplace("00ff00");

      const state = useConverterStore.getState();
      // previewGlbUrl must remain unchanged
      expect(state.previewGlbUrl).toBe(existingUrl);
      // 2D preview should still be updated
      expect(state.previewImageUrl).toBe(
        "http://localhost:8000/api/files/preview-after-replace",
      );
    });

    it("should preserve existing colorContours when response has null color_contours", async () => {
      const { regionReplace } = await import("../api/converter");

      const existingContours = {
        "#ff0000": [[[0, 0], [10, 0], [10, 10]]],
        "#00ff00": [[[5, 5], [15, 5], [15, 15]]],
      };
      resetStore({ colorContours: existingContours });

      const response: RegionReplaceResponse = {
        preview_url: "/api/files/preview-after-replace",
        preview_glb_url: null,
        color_contours: null,
        message: "ok",
      };
      (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

      await useConverterStore.getState().applyRegionReplace("0000ff");

      expect(useConverterStore.getState().colorContours).toEqual(existingContours);
    });
  });
});
