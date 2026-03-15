import { describe, it, expect, beforeEach, vi } from "vitest";
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
import type { SelectionMode } from "../stores/converterStore";
import { colorRemapToReplacementRegions } from "../utils/colorUtils";
import type { PaletteEntry } from "../api/types";

// ========== Generators ==========

const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

const selectionMode: fc.Arbitrary<SelectionMode> = fc.constantFrom(
  "select-all" as const,
  "current" as const,
  "multi-select" as const,
  "region" as const,
);

const hexColorArray = fc.uniqueArray(hexColor, { minLength: 1, maxLength: 8 });

// ========== Helper: reset store ==========

function resetStore() {
  useConverterStore.setState({
    colorRemapMap: {},
    remapHistory: [],
    pendingReplacement: null,
    selectedColors: new Set<string>(),
    sessionId: null,
    regionData: null,
    regionReplacementCount: 0,
    replacePreviewLoading: false,
    originalPreviewUrl: null,
    previewImageUrl: null,
    error: null,
  });
}

// ========== Tests ==========

describe("Feature: color-replace-architecture-fix — Property-Based Tests", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  /**
   * **Validates: Requirements 2.1, 2.2, 2.3**
   *
   * Task 5.1 — P2: confirmReplacement 在所有四种模式下都正确更新 colorRemapMap
   * For any mode, after confirmReplacement, colorRemapMap contains the expected mapping.
   */
  describe("5.1 confirmReplacement in all four modes correctly updates colorRemapMap (P2)", () => {
    it("confirmReplacement updates colorRemapMap for any mode", async () => {
      const { regionReplace } = await import("../api/converter");
      (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue({
        preview_url: "/api/files/mock-preview",
        preview_glb_url: null,
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

            // For current/region modes, set regionData so applyRegionReplace can proceed
            if (mode === "current" || mode === "region") {
              useConverterStore.setState({
                sessionId: "test-session",
                regionData: {
                  regionId: "r1",
                  colorHex: sourceHex,
                  pixelCount: 10,
                  previewUrl: "/mock",
                },
              });
            }

            // Set pending replacement
            useConverterStore.setState({
              pendingReplacement: {
                sourceHex,
                targetHex,
                mode,
                ...(mode === "multi-select" ? { sourceColors } : {}),
              },
            });

            await useConverterStore.getState().confirmReplacement();

            const state = useConverterStore.getState();

            // pendingReplacement should be cleared
            expect(state.pendingReplacement).toBeNull();

            // colorRemapMap should contain the mapping(s)
            if (mode === "multi-select") {
              for (const c of sourceColors) {
                expect(state.colorRemapMap[c]).toBe(targetHex);
              }
            } else {
              expect(state.colorRemapMap[sourceHex]).toBe(targetHex);
            }

            // remapHistory should have grown by 1
            expect(state.remapHistory.length).toBeGreaterThanOrEqual(1);
          },
        ),
        { numRuns: 50 },
      );
    });
  });

  /**
   * **Validates: Requirements 2.2**
   *
   * Task 5.3 — select-all mode confirmReplacement → colorRemapMap contains correct mapping
   */
  describe("5.3 select-all mode confirmReplacement → colorRemapMap contains correct mapping", () => {
    it("select-all: colorRemapMap[sourceHex] === targetHex and snapshot saved", async () => {
      await fc.assert(
        fc.asyncProperty(hexColor, hexColor, async (sourceHex, targetHex) => {
          resetStore();

          useConverterStore.setState({
            pendingReplacement: {
              sourceHex,
              targetHex,
              mode: "select-all",
            },
          });

          await useConverterStore.getState().confirmReplacement();

          const state = useConverterStore.getState();
          expect(state.pendingReplacement).toBeNull();
          expect(state.colorRemapMap[sourceHex]).toBe(targetHex);
          // History should contain the snapshot before this operation (empty map)
          expect(state.remapHistory.length).toBe(1);
          expect(state.remapHistory[0]).toEqual({});
        }),
        { numRuns: 50 },
      );
    });
  });

  /**
   * **Validates: Requirements 2.2**
   *
   * Task 5.4 — multi-select mode confirmReplacement → all selected colors map to targetHex
   */
  describe("5.4 multi-select mode confirmReplacement → all selected colors map to targetHex", () => {
    it("multi-select: every sourceColor maps to targetHex", async () => {
      await fc.assert(
        fc.asyncProperty(
          hexColorArray,
          hexColor,
          async (sourceColors, targetHex) => {
            resetStore();

            useConverterStore.setState({
              pendingReplacement: {
                sourceHex: sourceColors[0],
                targetHex,
                mode: "multi-select",
                sourceColors,
              },
            });

            await useConverterStore.getState().confirmReplacement();

            const state = useConverterStore.getState();
            expect(state.pendingReplacement).toBeNull();

            for (const c of sourceColors) {
              expect(state.colorRemapMap[c]).toBe(targetHex);
            }

            // History should contain one snapshot (the empty map before)
            expect(state.remapHistory.length).toBe(1);
            expect(state.remapHistory[0]).toEqual({});
          },
        ),
        { numRuns: 50 },
      );
    });
  });

  /**
   * **Validates: Requirements 2.1, 2.2**
   *
   * Task 5.5 — current/region mode confirmReplacement → colorRemapMap contains
   * sourceHex→targetHex and regionReplacementCount increments
   */
  describe("5.5 current/region mode confirmReplacement → colorRemapMap + regionReplacementCount", () => {
    it("current/region: colorRemapMap updated and regionReplacementCount incremented", async () => {
      const { regionReplace } = await import("../api/converter");
      (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue({
        preview_url: "/api/files/mock-preview",
        preview_glb_url: null,
        message: "ok",
      });

      const currentOrRegion: fc.Arbitrary<SelectionMode> = fc.constantFrom(
        "current" as const,
        "region" as const,
      );

      await fc.assert(
        fc.asyncProperty(
          currentOrRegion,
          hexColor,
          hexColor,
          async (mode, sourceHex, targetHex) => {
            resetStore();

            const initialCount = 0;
            useConverterStore.setState({
              sessionId: "test-session",
              regionData: {
                regionId: "r1",
                colorHex: sourceHex,
                pixelCount: 10,
                previewUrl: "/mock",
              },
              regionReplacementCount: initialCount,
            });

            useConverterStore.setState({
              pendingReplacement: {
                sourceHex,
                targetHex,
                mode,
              },
            });

            await useConverterStore.getState().confirmReplacement();

            const state = useConverterStore.getState();

            // colorRemapMap should contain the mapping
            expect(state.colorRemapMap[sourceHex]).toBe(targetHex);

            // regionReplacementCount should have incremented
            expect(state.regionReplacementCount).toBe(initialCount + 1);

            // History should contain one snapshot
            expect(state.remapHistory.length).toBe(1);
            expect(state.remapHistory[0]).toEqual({});
          },
        ),
        { numRuns: 50 },
      );
    });
  });

  /**
   * **Validates: Requirements 4.1, 4.2**
   *
   * Task 5.2 — P3: clearAllRemaps 完全重置 colorRemapMap 和 regionReplacementCount
   * After any number of operations, clearAllRemaps should reset colorRemapMap to {},
   * remapHistory to [], and regionReplacementCount to 0.
   */
  describe("5.2 clearAllRemaps fully resets colorRemapMap and regionReplacementCount (P3)", () => {
    it("clearAllRemaps resets all remap state regardless of prior operations", () => {
      fc.assert(
        fc.property(
          fc.dictionary(hexColor, hexColor, { minKeys: 1, maxKeys: 5 }),
          fc.nat({ max: 10 }),
          (remapMap, regionCount) => {
            // Set up arbitrary dirty state
            const history = [{ ...remapMap }];
            useConverterStore.setState({
              colorRemapMap: remapMap,
              remapHistory: history,
              regionReplacementCount: regionCount,
              sessionId: null, // no session → skip backend call
            });

            useConverterStore.getState().clearAllRemaps();

            const state = useConverterStore.getState();
            expect(state.colorRemapMap).toEqual({});
            expect(state.remapHistory).toEqual([]);
            expect(state.regionReplacementCount).toBe(0);
            expect(state.regionData).toBeNull();
          },
        ),
        { numRuns: 50 },
      );
    });
  });

  /**
   * **Validates: Requirements 4.1**
   *
   * Task 5.6 — undoColorRemap correctly reverts colorRemapMap to previous snapshot
   * After N applyColorRemap calls, one undoColorRemap should restore the map to the N-1 snapshot.
   */
  describe("5.6 undoColorRemap correctly reverts colorRemapMap to previous snapshot", () => {
    it("undo restores colorRemapMap to the previous history snapshot", () => {
      fc.assert(
        fc.property(
          fc.array(
            fc.tuple(hexColor, hexColor),
            { minLength: 1, maxLength: 5 },
          ),
          (operations) => {
            resetStore();
            useConverterStore.setState({ sessionId: null });

            // Apply N operations via applyColorRemap (which pushes snapshots)
            const snapshots: Record<string, string>[] = [];
            for (const [origHex, newHex] of operations) {
              snapshots.push({ ...useConverterStore.getState().colorRemapMap });
              useConverterStore.getState().applyColorRemap(origHex, newHex);
            }

            // The last snapshot before the final operation
            const expectedMap = snapshots[snapshots.length - 1];

            // Undo once
            useConverterStore.getState().undoColorRemap();

            const state = useConverterStore.getState();
            expect(state.colorRemapMap).toEqual(expectedMap);
            expect(state.remapHistory.length).toBe(operations.length - 1);
          },
        ),
        { numRuns: 50 },
      );
    });

    it("undo on empty history is a no-op", () => {
      resetStore();
      const mapBefore = { ...useConverterStore.getState().colorRemapMap };
      useConverterStore.getState().undoColorRemap();
      expect(useConverterStore.getState().colorRemapMap).toEqual(mapBefore);
    });
  });

  /**
   * **Validates: Requirements 3.1**
   *
   * Task 5.7 — colorRemapToReplacementRegions correctly converts colorRemapMap to backend format
   * Pure function test: output length, # prefix, and replacement_hex correctness.
   */
  describe("5.7 colorRemapToReplacementRegions correctly converts colorRemapMap to backend format", () => {
    it("output length equals number of remapMap entries with matching palette entries", () => {
      fc.assert(
        fc.property(
          fc.array(
            fc.tuple(hexColor, hexColor),
            { minLength: 1, maxLength: 5 },
          ),
          (pairs) => {
            // Build unique remapMap and matching palette
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
          },
        ),
        { numRuns: 50 },
      );
    });

    it("all output hex values have # prefix", () => {
      fc.assert(
        fc.property(
          hexColor,
          hexColor,
          hexColor,
          (sourceHex, targetHex, quantizedHex) => {
            const remapMap = { [sourceHex]: targetHex };
            const palette: PaletteEntry[] = [
              {
                quantized_hex: quantizedHex,
                matched_hex: sourceHex,
                pixel_count: 100,
                percentage: 10,
              },
            ];

            const result = colorRemapToReplacementRegions(remapMap, palette);
            expect(result.length).toBe(1);

            const item = result[0];
            expect(item.quantized_hex.startsWith("#")).toBe(true);
            expect(item.matched_hex.startsWith("#")).toBe(true);
            expect(item.replacement_hex.startsWith("#")).toBe(true);
          },
        ),
        { numRuns: 50 },
      );
    });

    it("replacement_hex matches the target from remapMap", () => {
      fc.assert(
        fc.property(
          hexColor,
          hexColor,
          hexColor,
          (sourceHex, targetHex, quantizedHex) => {
            const remapMap = { [sourceHex]: targetHex };
            const palette: PaletteEntry[] = [
              {
                quantized_hex: quantizedHex,
                matched_hex: sourceHex,
                pixel_count: 100,
                percentage: 10,
              },
            ];

            const result = colorRemapToReplacementRegions(remapMap, palette);
            expect(result.length).toBe(1);
            expect(result[0].replacement_hex).toBe(`#${targetHex}`);
          },
        ),
        { numRuns: 50 },
      );
    });

    it("entries without matching palette are excluded from output", () => {
      fc.assert(
        fc.property(
          hexColor,
          hexColor,
          hexColor,
          (sourceHex, targetHex, unrelatedHex) => {
            fc.pre(sourceHex !== unrelatedHex);

            const remapMap = { [sourceHex]: targetHex };
            // Palette does NOT contain sourceHex
            const palette: PaletteEntry[] = [
              {
                quantized_hex: unrelatedHex,
                matched_hex: unrelatedHex,
                pixel_count: 100,
                percentage: 10,
              },
            ];

            const result = colorRemapToReplacementRegions(remapMap, palette);
            expect(result.length).toBe(0);
          },
        ),
        { numRuns: 50 },
      );
    });
  });
});
