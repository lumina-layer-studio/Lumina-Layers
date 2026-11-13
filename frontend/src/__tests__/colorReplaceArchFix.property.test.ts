import { describe, it, expect, beforeEach, vi } from "vitest";
import * as fc from "fast-check";

vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>(
      "../api/converter",
    );
  return {
    ...actual,
    fetchLutList: vi.fn(),
    convertPreview: vi.fn(),
    convertGenerate: vi.fn(),
    fetchBedSizes: vi.fn(),
    uploadHeightmap: vi.fn(),
    fetchLutColors: vi.fn(),
    cropImage: vi.fn(),
    convertBatch: vi.fn(),
    replaceColor: vi.fn(),
    replaceColorsBatch: vi.fn().mockResolvedValue({
      status: "ok",
      message: "ok",
      preview_url: "/api/files/mock-preview",
      replacement_count: 1,
    }),
    colorHighlight: vi.fn().mockResolvedValue({
      preview_url: "/api/files/mock-highlight",
    }),
    detectRegion: vi.fn(),
    regionReplace: vi.fn(),
    regionReplaceBatch: vi.fn().mockResolvedValue({
      preview_url: "/api/files/mock-preview",
      preview_glb_url: null,
      message: "ok",
    }),
    resetReplacements: vi.fn(),
    getEditorCommitStatus: vi.fn().mockResolvedValue({
      status: "failed",
      operation_id: "test-operation",
      editor_content_revision: 0,
      visible_content_revision: 0,
    }),
  };
});

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

import { useConverterStore } from "../stores/converter";
import type { SelectionMode, RegionData } from "../stores/converter";
import { colorRemapToReplacementRegions } from "../utils/colorUtils";
import type { PaletteEntry } from "../api/types";
import { replaceColorsBatch, resetReplacements } from "../api/converter";

const hexColor = fc.stringMatching(/^[0-9a-f]{6}$/).filter((s) => s.length === 6);
const selectionMode: fc.Arbitrary<SelectionMode> = fc.constantFrom(
  "select-all",
  "current",
  "multi-select",
  "region",
);
const hexColorArray = fc.uniqueArray(hexColor, { minLength: 1, maxLength: 8 });
const mockReplaceColorsBatch = vi.mocked(replaceColorsBatch);
const mockResetReplacements = vi.mocked(resetReplacements);

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function flushPromises(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

function resetStore() {
  useConverterStore.setState({
    colorRemapMap: {},
    remapHistory: [],
    remapRedoHistory: [],
    replacement_regions: [],
    palette: [],
    pendingReplacement: null,
    selectedColors: new Set<string>(),
    selectedRegions: [],
    sessionId: null,
    regionData: null,
    recipe_overrides: [],
    regionReplacementCount: 0,
    replacePreviewLoading: false,
    originalPreviewUrl: null,
    previewBaseImageUrl: null,
    previewImageUrl: null,
    previewGlbUrl: null,
    error: null,
  });
}

function toRegions(colors: string[]): RegionData[] {
  return colors.map((c, i) => ({
    regionId: `r-${i}`,
    colorHex: `#${c}`,
    pixelCount: 10,
    previewUrl: "/mock",
    clickX: i,
    clickY: i,
  }));
}

describe("color replace architecture", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  it("confirmReplacement follows mode-specific behavior", async () => {
    const { regionReplace, regionReplaceBatch } = await import("../api/converter");
    (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue({
      preview_url: "/api/files/mock-preview",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });
    (regionReplaceBatch as ReturnType<typeof vi.fn>).mockResolvedValue({
      preview_url: "/api/files/mock-preview",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    await fc.assert(
      fc.asyncProperty(
        selectionMode,
        hexColor,
        hexColor,
        hexColorArray,
        async (mode, sourceHex, targetHex, sourceColors) => {
          resetStore();

          if (mode === "current" || mode === "region") {
            useConverterStore.setState({
              sessionId: "test-session",
              regionData: {
                regionId: "r1",
                colorHex: `#${sourceHex}`,
                pixelCount: 10,
                previewUrl: "/mock",
                clickX: 1,
                clickY: 1,
              },
            });
          }
          if (mode === "multi-select") {
            useConverterStore.setState({ sessionId: "test-session" });
          }

          const sourceRegions = mode === "multi-select" ? toRegions(sourceColors) : undefined;
          useConverterStore.setState({
            pendingReplacement: {
              sourceHex,
              targetHex,
              mode,
              ...(mode === "multi-select" ? { sourceColors, sourceRegions } : {}),
            },
          });

          const before = useConverterStore.getState();
          await useConverterStore.getState().confirmReplacement();
          const state = useConverterStore.getState();

          expect(state.pendingReplacement).toBeNull();

          if (mode === "select-all") {
            expect(state.colorRemapMap[sourceHex]).toBe(targetHex);
            expect(state.remapHistory.length).toBeGreaterThanOrEqual(1);
          } else {
            expect(state.colorRemapMap).toEqual(before.colorRemapMap);
          }

          if (mode === "current" || mode === "region") {
            expect(state.regionReplacementCount).toBe(before.regionReplacementCount + 1);
          }
          if (mode === "multi-select") {
            expect(state.regionReplacementCount).toBe(before.regionReplacementCount + sourceColors.length);
          }
        },
      ),
      { numRuns: 50 },
    );
  });

  it("keeps a connected single-region edit out of global replacement mappings", async () => {
    const { regionReplace } = await import("../api/converter");
    (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue({
      preview_url: "/api/files/region-preview",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });
    const globalSentinel = [
      {
        quantized_hex: "#102030",
        matched_hex: "#405060",
        replacement_hex: "#708090",
      },
    ];
    const beforeJson = JSON.stringify(globalSentinel);
    resetStore();
    useConverterStore.setState({
      sessionId: "test-session",
      replacement_regions: globalSentinel,
      regionReplacementCount: 4,
      regionData: {
        regionId: "connected-region",
        colorHex: "#aabbcc",
        pixelCount: 20,
        previewUrl: "/api/files/highlight",
        clickX: 8,
        clickY: 9,
      },
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 20,
          percentage: 1,
        },
      ],
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ddeeff",
        mode: "current",
      },
    });

    await useConverterStore.getState().confirmReplacement();

    const state = useConverterStore.getState();
    expect(regionReplace).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(state.replacement_regions)).toBe(beforeJson);
    expect(state.regionReplacementCount).toBe(5);
  });

  it("does not count a connected-region edit when the API rejects", async () => {
    const { regionReplace } = await import("../api/converter");
    (regionReplace as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("region replace failed"),
    );
    const globalSentinel = [
      {
        quantized_hex: "#102030",
        matched_hex: "#405060",
        replacement_hex: "#708090",
      },
    ];
    resetStore();
    useConverterStore.setState({
      sessionId: "test-session",
      replacement_regions: globalSentinel,
      regionReplacementCount: 6,
      regionData: {
        regionId: "connected-region",
        colorHex: "#aabbcc",
        pixelCount: 20,
        previewUrl: "/api/files/highlight",
        clickX: 8,
        clickY: 9,
      },
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ddeeff",
        mode: "current",
      },
    });

    await useConverterStore.getState().confirmReplacement();

    const state = useConverterStore.getState();
    expect(regionReplace).toHaveBeenCalledTimes(1);
    expect(state.regionReplacementCount).toBe(6);
    expect(state.replacement_regions).toEqual(globalSentinel);
    expect(state.replacePreviewLoading).toBe(false);
    expect(state.error).toBeTruthy();
  });

  it("ignores a connected-region success response after the session changes", async () => {
    const { regionReplace } = await import("../api/converter");
    const response = deferred<Awaited<ReturnType<typeof regionReplace>>>();
    (regionReplace as ReturnType<typeof vi.fn>).mockReturnValueOnce(
      response.promise,
    );
    resetStore();
    useConverterStore.setState({
      sessionId: "session-a",
      regionReplacementCount: 4,
      regionData: toRegions(["aabbcc"])[0],
      previewImageUrl: "/api/files/session-a.png",
      previewBaseImageUrl: "/api/files/session-a.png",
    });

    const request = useConverterStore
      .getState()
      .applyRegionReplace("ddeeff");
    expect(regionReplace).toHaveBeenCalledWith(
      "session-a",
      "#ddeeff",
      undefined,
      undefined,
      expect.any(String),
    );

    const sessionBRegion = toRegions(["112233"])[0];
    useConverterStore.setState({
      sessionId: "session-b",
      regionReplacementCount: 0,
      regionData: sessionBRegion,
      previewImageUrl: "/api/files/session-b.png",
      previewBaseImageUrl: "/api/files/session-b.png",
      replacePreviewLoading: false,
      error: null,
    });
    response.resolve({
      preview_url: "/api/files/stale-session-a.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });
    await request;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBe("session-b");
    expect(state.regionReplacementCount).toBe(0);
    expect(state.regionData).toEqual(sessionBRegion);
    expect(state.previewImageUrl).toBe("/api/files/session-b.png");
    expect(state.previewBaseImageUrl).toBe("/api/files/session-b.png");
  });

  it("ignores a connected-region failure after the session changes", async () => {
    const { regionReplace } = await import("../api/converter");
    const response = deferred<Awaited<ReturnType<typeof regionReplace>>>();
    (regionReplace as ReturnType<typeof vi.fn>).mockReturnValueOnce(
      response.promise,
    );
    resetStore();
    useConverterStore.setState({
      sessionId: "session-a",
      regionData: toRegions(["aabbcc"])[0],
    });

    const request = useConverterStore
      .getState()
      .applyRegionReplace("ddeeff");
    useConverterStore.setState({
      sessionId: "session-b",
      replacePreviewLoading: true,
      error: "session-b-error",
    });
    response.reject(new Error("stale session-a failure"));
    await request;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBe("session-b");
    expect(state.replacePreviewLoading).toBe(true);
    expect(state.error).toBe("session-b-error");
  });

  it.each(["current", "region"] as const)(
    "does not count or request a %s edit without selected region data",
    async (mode) => {
      const { regionReplace } = await import("../api/converter");
      const globalSentinel = [
        {
          quantized_hex: "#102030",
          matched_hex: "#405060",
          replacement_hex: "#708090",
        },
      ];
      resetStore();
      useConverterStore.setState({
        sessionId: "test-session",
        replacement_regions: globalSentinel,
        regionReplacementCount: 6,
        regionData: null,
        pendingReplacement: {
          sourceHex: "aabbcc",
          targetHex: "ddeeff",
          mode,
        },
      });

      await useConverterStore.getState().confirmReplacement();

      const state = useConverterStore.getState();
      expect(regionReplace).not.toHaveBeenCalled();
      expect(state.regionReplacementCount).toBe(6);
      expect(state.replacement_regions).toEqual(globalSentinel);
      expect(state.replacePreviewLoading).toBe(false);
      expect(state.error).toBeNull();
    },
  );

  it("keeps a successful multi-region batch out of global replacement mappings", async () => {
    const { regionReplaceBatch } = await import("../api/converter");
    (regionReplaceBatch as ReturnType<typeof vi.fn>).mockResolvedValue({
      preview_url: "/api/files/batch-preview",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });
    const globalSentinel = [
      {
        quantized_hex: "#102030",
        matched_hex: "#405060",
        replacement_hex: "#708090",
      },
    ];
    const sourceRegions = toRegions(["aabbcc", "112233"]);
    const beforeJson = JSON.stringify(globalSentinel);
    resetStore();
    useConverterStore.setState({
      sessionId: "test-session",
      replacement_regions: globalSentinel,
      regionReplacementCount: 3,
      palette: sourceRegions.map((region) => ({
        quantized_hex: region.colorHex,
        matched_hex: region.colorHex,
        pixel_count: region.pixelCount,
        percentage: 1,
      })),
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ddeeff",
        mode: "multi-select",
        sourceRegions,
      },
    });

    await useConverterStore.getState().confirmReplacement();

    const state = useConverterStore.getState();
    expect(regionReplaceBatch).toHaveBeenCalledTimes(1);
    expect(state.error).toBeNull();
    expect(state.previewImageUrl).toBe("/api/files/batch-preview");
    expect(JSON.stringify(state.replacement_regions)).toBe(beforeJson);
    expect(state.regionReplacementCount).toBe(5);
  });

  it("does not count a multi-region batch when the API rejects", async () => {
    const { regionReplaceBatch } = await import("../api/converter");
    (regionReplaceBatch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("batch replace failed"),
    );
    const globalSentinel = [
      {
        quantized_hex: "#102030",
        matched_hex: "#405060",
        replacement_hex: "#708090",
      },
    ];
    resetStore();
    useConverterStore.setState({
      sessionId: "test-session",
      replacement_regions: globalSentinel,
      regionReplacementCount: 3,
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ddeeff",
        mode: "multi-select",
        sourceRegions: toRegions(["aabbcc", "112233"]),
      },
    });

    await useConverterStore.getState().confirmReplacement();

    const state = useConverterStore.getState();
    expect(regionReplaceBatch).toHaveBeenCalledTimes(1);
    expect(state.regionReplacementCount).toBe(3);
    expect(state.replacement_regions).toEqual(globalSentinel);
    expect(state.replacePreviewLoading).toBe(false);
    expect(state.error).toBeTruthy();
  });

  it("ignores a multi-region success response after the session changes", async () => {
    const { regionReplaceBatch } = await import("../api/converter");
    const response = deferred<Awaited<ReturnType<typeof regionReplaceBatch>>>();
    (regionReplaceBatch as ReturnType<typeof vi.fn>).mockReturnValueOnce(
      response.promise,
    );
    const sourceRegions = toRegions([
      "aabbcc",
      "112233",
      "223344",
      "334455",
      "445566",
      "556677",
    ]);
    resetStore();
    useConverterStore.setState({
      sessionId: "session-a",
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ddeeff",
        mode: "multi-select",
        sourceRegions,
      },
    });

    const request = useConverterStore.getState().confirmReplacement();
    expect(regionReplaceBatch).toHaveBeenCalledTimes(1);

    const sessionBRegion = toRegions(["778899"])[0];
    useConverterStore.setState({
      sessionId: "session-b",
      regionReplacementCount: 0,
      regionData: sessionBRegion,
      selectedRegions: [sessionBRegion],
      selectedColor: "778899",
      previewImageUrl: "/api/files/session-b.png",
      previewBaseImageUrl: "/api/files/session-b.png",
      replacePreviewLoading: false,
      error: null,
    });
    response.resolve({
      preview_url: "/api/files/stale-session-a.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });
    await request;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBe("session-b");
    expect(state.regionReplacementCount).toBe(0);
    expect(state.regionData).toEqual(sessionBRegion);
    expect(state.selectedRegions).toEqual([sessionBRegion]);
    expect(state.selectedColor).toBe("778899");
    expect(state.previewImageUrl).toBe("/api/files/session-b.png");
    expect(state.previewBaseImageUrl).toBe("/api/files/session-b.png");
  });

  it("ignores a multi-region failure after the session changes", async () => {
    const { regionReplaceBatch } = await import("../api/converter");
    const response = deferred<Awaited<ReturnType<typeof regionReplaceBatch>>>();
    (regionReplaceBatch as ReturnType<typeof vi.fn>).mockReturnValueOnce(
      response.promise,
    );
    resetStore();
    useConverterStore.setState({
      sessionId: "session-a",
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ddeeff",
        mode: "multi-select",
        sourceRegions: toRegions(["aabbcc", "112233"]),
      },
    });

    const request = useConverterStore.getState().confirmReplacement();
    useConverterStore.setState({
      sessionId: "session-b",
      replacePreviewLoading: true,
      error: "session-b-error",
    });
    response.reject(new Error("stale session-a failure"));
    await request;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBe("session-b");
    expect(state.replacePreviewLoading).toBe(true);
    expect(state.error).toBe("session-b-error");
  });

  it("does not count or request a multi-region batch without valid coordinates", async () => {
    const { regionReplaceBatch } = await import("../api/converter");
    const globalSentinel = [
      {
        quantized_hex: "#102030",
        matched_hex: "#405060",
        replacement_hex: "#708090",
      },
    ];
    resetStore();
    useConverterStore.setState({
      sessionId: "test-session",
      replacement_regions: globalSentinel,
      regionReplacementCount: 3,
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ddeeff",
        mode: "multi-select",
        sourceRegions: [
          {
            regionId: "missing-coordinates",
            colorHex: "#aabbcc",
            pixelCount: 10,
            previewUrl: "/mock",
          },
        ],
      },
    });

    await useConverterStore.getState().confirmReplacement();

    const state = useConverterStore.getState();
    expect(regionReplaceBatch).not.toHaveBeenCalled();
    expect(state.regionReplacementCount).toBe(3);
    expect(state.replacement_regions).toEqual(globalSentinel);
    expect(state.replacePreviewLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("select-all writes map and snapshot", async () => {
    await fc.assert(
      fc.asyncProperty(hexColor, hexColor, async (sourceHex, targetHex) => {
        resetStore();
        useConverterStore.setState({
          pendingReplacement: { sourceHex, targetHex, mode: "select-all" },
        });
        await useConverterStore.getState().confirmReplacement();

        const state = useConverterStore.getState();
        expect(state.colorRemapMap[sourceHex]).toBe(targetHex);
        expect(state.remapHistory.length).toBe(1);
        expect(state.remapHistory[0]).toEqual({});
      }),
      { numRuns: 50 },
    );
  });

  it("clearAllRemaps resets remap-related state", () => {
    fc.assert(
      fc.property(
        fc.dictionary(hexColor, hexColor, { minKeys: 1, maxKeys: 5 }),
        fc.nat({ max: 10 }),
        (remapMap, regionCount) => {
          useConverterStore.setState({
            colorRemapMap: remapMap,
            remapHistory: [{ ...remapMap }],
            regionReplacementCount: regionCount,
            sessionId: null,
          });

          useConverterStore.getState().clearAllRemaps();
          const state = useConverterStore.getState();
          expect(state.colorRemapMap).toEqual({});
          expect(state.remapRedoHistory).toEqual([]);
          expect(state.regionReplacementCount).toBe(0);
          expect(state.regionData).toBeNull();
        },
      ),
      { numRuns: 50 },
    );
  });

  it("clearAllRemaps accepts reset result and ignores stale replace preview", async () => {
    resetStore();
    const staleReplace = deferred<{
      status: string;
      message: string;
      preview_url: string;
      preview_3d_url?: string | null;
      replacement_count: number;
    }>();
    mockReplaceColorsBatch.mockReturnValueOnce(staleReplace.promise);
    mockResetReplacements.mockResolvedValueOnce({
      status: "ok",
      message: "All replacements cleared",
      preview_url: "/api/files/reset-preview",
      preview_glb_url: null,
    });

    useConverterStore.setState({
      sessionId: "test-session",
      colorRemapMap: { ff0000: "00ff00" },
      remapHistory: [{ ff0000: "0000ff" }],
      replacement_regions: [
        {
          quantized_hex: "#ff0000",
          matched_hex: "#ff0000",
          replacement_hex: "#00ff00",
        },
      ],
      recipe_overrides: [
        {
          region_id: "r-1",
          recipe: [0, 1],
          layer_order: "Top2Bottom",
        },
      ],
      regionReplacementCount: 2,
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/replaced-preview",
      previewImageUrl: "/api/files/replaced-preview",
      previewGlbUrl: "/api/files/replaced.glb",
    });

    const pendingReplace = useConverterStore.getState().submitReplacePreview();
    const clearRequest = useConverterStore.getState().clearAllRemaps();
    await flushPromises();

    // Same-session content edits share one barrier. The reset must wait for
    // the earlier replacement request instead of overtaking it.
    expect(mockResetReplacements).not.toHaveBeenCalled();
    staleReplace.resolve({
      status: "ok",
      message: "stale",
      preview_url: "/api/files/stale-replaced-preview",
      preview_3d_url: "/api/files/stale-replaced.glb",
      replacement_count: 1,
    });
    await pendingReplace;
    await clearRequest;

    let state = useConverterStore.getState();
    expect(mockResetReplacements).toHaveBeenCalledWith(
      "test-session",
      expect.any(String),
    );
    expect(state.colorRemapMap).toEqual({});
    expect(state.replacement_regions).toEqual([]);
    expect(state.recipe_overrides).toEqual([]);
    expect(state.regionReplacementCount).toBe(0);
    expect(state.previewImageUrl).toBe("/api/files/reset-preview");
    expect(state.previewBaseImageUrl).toBe("/api/files/reset-preview");
    expect(state.previewGlbUrl).toBeNull();

    state = useConverterStore.getState();
    expect(state.previewImageUrl).toBe("/api/files/reset-preview");
    expect(state.previewBaseImageUrl).toBe("/api/files/reset-preview");
    expect(state.previewGlbUrl).toBeNull();
    expect(state.colorRemapMap).toEqual({});
  });

  it("undoColorRemap restores previous snapshot", () => {
    fc.assert(
      fc.property(fc.array(fc.tuple(hexColor, hexColor), { minLength: 1, maxLength: 5 }), (ops) => {
        resetStore();
        useConverterStore.setState({ sessionId: null });

        const snapshots: Record<string, string>[] = [];
        for (const [orig, next] of ops) {
          snapshots.push({ ...useConverterStore.getState().colorRemapMap });
          useConverterStore.getState().applyColorRemap(orig, next);
        }

        const expected = snapshots[snapshots.length - 1];
        useConverterStore.getState().undoColorRemap();
        const state = useConverterStore.getState();
        expect(state.colorRemapMap).toEqual(expected);
        expect(state.remapHistory.length).toBe(ops.length - 1);
      }),
      { numRuns: 50 },
    );
  });

  it("colorRemapToReplacementRegions converts mapping to backend payload", () => {
    fc.assert(
      fc.property(fc.array(fc.tuple(hexColor, hexColor), { minLength: 1, maxLength: 5 }), (pairs) => {
        const remapMap: Record<string, string> = {};
        const palette: PaletteEntry[] = [];
        const seen = new Set<string>();

        for (const [src, tgt] of pairs) {
          if (seen.has(src)) continue;
          seen.add(src);
          remapMap[src] = tgt;
          palette.push({
            quantized_hex: src,
            matched_hex: src,
            pixel_count: 100,
            percentage: 10,
          });
        }

        const result = colorRemapToReplacementRegions(remapMap, palette);
        expect(result.length).toBe(Object.keys(remapMap).length);
        for (const item of result) {
          expect(item.quantized_hex.startsWith("#")).toBe(true);
          expect(item.matched_hex.startsWith("#")).toBe(true);
          expect(item.replacement_hex.startsWith("#")).toBe(true);
        }
      }),
      { numRuns: 50 },
    );
  });

  it("colorRemapToReplacementRegions falls back to the source hex when palette entry is missing", () => {
    fc.assert(
      fc.property(hexColor, hexColor, (sourceHex, targetHex) => {
        const result = colorRemapToReplacementRegions(
          { [sourceHex]: targetHex },
          [],
        );

        expect(result).toEqual([
          {
            quantized_hex: `#${sourceHex}`,
            matched_hex: `#${sourceHex}`,
            replacement_hex: `#${targetHex}`,
          },
        ]);
      }),
      { numRuns: 50 },
    );
  });
});
