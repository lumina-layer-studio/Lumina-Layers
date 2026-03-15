import { describe, it, expect, beforeEach, vi } from "vitest";
import * as fc from "fast-check";

// ========== Mock API module (needed for Property 3: confirmReplacement → applyColorRemap → submitSingleReplace) ==========

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
}));

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

import { useConverterStore } from "../stores/converterStore";
import type { PendingReplacement, SelectionMode } from "../stores/converterStore";

// ========== Generators ==========

/** Generate a valid 6-character lowercase hex color string (no # prefix) */
const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

/** Generate a valid SelectionMode */
const selectionMode: fc.Arbitrary<SelectionMode> = fc.constantFrom(
  "select-all" as const,
  "multi-select" as const,
  "current" as const,
  "region" as const,
);

/** Generate a non-empty array of unique hex colors for multi-select sourceColors */
const hexColorArray = fc
  .uniqueArray(hexColor, { minLength: 1, maxLength: 8 });

// ========== Tests ==========

describe("Feature: free-color-and-replace-fix — Property-Based Tests", () => {
  /**
   * **Validates: Requirements 1.1, 1.3**
   *
   * Property 1: Hex 前缀 round-trip
   * For any valid hex color string h (without #), applying '#' + h then
   * .replace(/^#/, '') should produce the same value as h; and '#' + h
   * should start with '#' and have length 7.
   */
  describe("Property 1: Hex 前缀 round-trip", () => {
    it("adding # prefix then removing it yields the original hex string", () => {
      fc.assert(
        fc.property(hexColor, (h) => {
          const withPrefix = "#" + h;
          const stripped = withPrefix.replace(/^#/, "");
          return stripped === h;
        }),
        { numRuns: 100 }
      );
    });

    it("'#' + h starts with '#' and has length 7", () => {
      fc.assert(
        fc.property(hexColor, (h) => {
          const withPrefix = "#" + h;
          return withPrefix.startsWith("#") && withPrefix.length === 7;
        }),
        { numRuns: 100 }
      );
    });
  });

  /**
   * **Validates: Requirements 2.1, 4.1, 4.2, 4.3**
   *
   * Property 2: 点击设置 pending 而非立即替换
   * For any selection mode and any valid source/target colors, calling
   * setPendingReplacement should NOT modify colorRemapMap, and should
   * set pendingReplacement with the correct sourceHex, targetHex, and mode.
   */
  describe("Property 2: 点击设置 pending 而非立即替换", () => {
    beforeEach(() => {
      // Reset store to default state before each test
      useConverterStore.setState({
        colorRemapMap: {},
        remapHistory: [],
        pendingReplacement: null,
        selectedColors: new Set<string>(),
      });
    });

    it("setPendingReplacement does not modify colorRemapMap and sets correct pending state", () => {
      fc.assert(
        fc.property(
          selectionMode,
          hexColor,
          hexColor,
          hexColorArray,
          (mode, sourceHex, targetHex, sourceColors) => {
            const store = useConverterStore;

            // Reset state
            store.setState({
              colorRemapMap: {},
              remapHistory: [],
              pendingReplacement: null,
            });

            // Capture colorRemapMap before
            const mapBefore = { ...store.getState().colorRemapMap };

            // Build pending replacement based on mode
            const pending: PendingReplacement = {
              sourceHex,
              targetHex,
              mode,
              ...(mode === "multi-select" ? { sourceColors } : {}),
            };

            // Act: set pending replacement
            store.getState().setPendingReplacement(pending);

            const state = store.getState();

            // Assert: colorRemapMap unchanged
            expect(state.colorRemapMap).toEqual(mapBefore);

            // Assert: pendingReplacement set correctly
            expect(state.pendingReplacement).not.toBeNull();
            expect(state.pendingReplacement!.sourceHex).toBe(sourceHex);
            expect(state.pendingReplacement!.targetHex).toBe(targetHex);
            expect(state.pendingReplacement!.mode).toBe(mode);

            if (mode === "multi-select") {
              expect(state.pendingReplacement!.sourceColors).toEqual(sourceColors);
            }
          },
        ),
        { numRuns: 100 },
      );
    });

    it("setPendingReplacement does not modify a pre-existing colorRemapMap", () => {
      fc.assert(
        fc.property(
          selectionMode,
          hexColor,
          hexColor,
          hexColor,
          hexColor,
          (mode, sourceHex, targetHex, existingKey, existingValue) => {
            const store = useConverterStore;

            // Set up a pre-existing colorRemapMap
            const existingMap = { [existingKey]: existingValue };
            store.setState({
              colorRemapMap: existingMap,
              remapHistory: [],
              pendingReplacement: null,
            });

            // Capture colorRemapMap before
            const mapBefore = { ...store.getState().colorRemapMap };

            // Act: set pending replacement
            store.getState().setPendingReplacement({
              sourceHex,
              targetHex,
              mode,
            });

            const state = store.getState();

            // Assert: colorRemapMap unchanged (still has the pre-existing entry)
            expect(state.colorRemapMap).toEqual(mapBefore);
            expect(state.colorRemapMap[existingKey]).toBe(existingValue);

            // Assert: pendingReplacement set correctly
            expect(state.pendingReplacement).not.toBeNull();
            expect(state.pendingReplacement!.sourceHex).toBe(sourceHex);
            expect(state.pendingReplacement!.targetHex).toBe(targetHex);
            expect(state.pendingReplacement!.mode).toBe(mode);
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  /**
   * **Validates: Requirements 2.3, 3.1**
   *
   * Property 3: 确认替换更新 colorRemapMap 并清除 pending
   * For any non-null pendingReplacement in select-all mode, calling
   * confirmReplacement() should set pendingReplacement to null and
   * colorRemapMap should contain the sourceHex → targetHex mapping.
   */
  describe("Property 3: 确认替换更新 colorRemapMap 并清除 pending", () => {
    beforeEach(() => {
      useConverterStore.setState({
        colorRemapMap: {},
        remapHistory: [],
        pendingReplacement: null,
        selectedColors: new Set<string>(),
        sessionId: null,
      });
    });

    it("confirmReplacement clears pendingReplacement and updates colorRemapMap (select-all)", async () => {
      await fc.assert(
        fc.asyncProperty(
          hexColor,
          hexColor,
          async (sourceHex, targetHex) => {
            const store = useConverterStore;

            // Reset state
            store.setState({
              colorRemapMap: {},
              remapHistory: [],
              pendingReplacement: {
                sourceHex,
                targetHex,
                mode: "select-all",
              },
              sessionId: null,
            });

            // Act: confirm replacement
            await store.getState().confirmReplacement();

            const state = store.getState();

            // Assert: pendingReplacement cleared
            expect(state.pendingReplacement).toBeNull();

            // Assert: colorRemapMap contains sourceHex → targetHex
            expect(state.colorRemapMap[sourceHex]).toBe(targetHex);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("confirmReplacement preserves existing colorRemapMap entries and adds new mapping", async () => {
      await fc.assert(
        fc.asyncProperty(
          hexColor,
          hexColor,
          hexColor,
          hexColor,
          async (sourceHex, targetHex, existingKey, existingValue) => {
            // Ensure source and existing key differ to avoid overwrite
            fc.pre(sourceHex !== existingKey);

            const store = useConverterStore;

            // Set up pre-existing map + pending
            store.setState({
              colorRemapMap: { [existingKey]: existingValue },
              remapHistory: [],
              pendingReplacement: {
                sourceHex,
                targetHex,
                mode: "select-all",
              },
              sessionId: null,
            });

            // Act
            await store.getState().confirmReplacement();

            const state = store.getState();

            // Assert: pending cleared
            expect(state.pendingReplacement).toBeNull();

            // Assert: new mapping added
            expect(state.colorRemapMap[sourceHex]).toBe(targetHex);

            // Assert: existing mapping preserved
            expect(state.colorRemapMap[existingKey]).toBe(existingValue);
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  /**
   * **Validates: Requirements 2.4**
   *
   * Property 4: 取消清除 pending 而不执行替换
   * For any non-null pendingReplacement state, calling
   * setPendingReplacement(null) should set pendingReplacement to null,
   * and colorRemapMap should remain exactly the same as before the cancel.
   */
  describe("Property 4: 取消清除 pending 而不执行替换", () => {
    beforeEach(() => {
      useConverterStore.setState({
        colorRemapMap: {},
        remapHistory: [],
        pendingReplacement: null,
        selectedColors: new Set<string>(),
      });
    });

    it("setPendingReplacement(null) clears pending without modifying empty colorRemapMap", () => {
      fc.assert(
        fc.property(
          selectionMode,
          hexColor,
          hexColor,
          (mode, sourceHex, targetHex) => {
            const store = useConverterStore;

            // Set up a pending replacement
            store.setState({
              colorRemapMap: {},
              remapHistory: [],
              pendingReplacement: { sourceHex, targetHex, mode },
            });

            // Capture colorRemapMap before cancel
            const mapBefore = { ...store.getState().colorRemapMap };

            // Act: cancel by setting pending to null
            store.getState().setPendingReplacement(null);

            const state = store.getState();

            // Assert: pendingReplacement cleared
            expect(state.pendingReplacement).toBeNull();

            // Assert: colorRemapMap unchanged
            expect(state.colorRemapMap).toEqual(mapBefore);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("setPendingReplacement(null) clears pending without modifying pre-existing colorRemapMap", () => {
      fc.assert(
        fc.property(
          selectionMode,
          hexColor,
          hexColor,
          hexColor,
          hexColor,
          (mode, sourceHex, targetHex, existingKey, existingValue) => {
            const store = useConverterStore;

            // Set up pre-existing colorRemapMap + pending replacement
            const existingMap = { [existingKey]: existingValue };
            store.setState({
              colorRemapMap: { ...existingMap },
              remapHistory: [],
              pendingReplacement: { sourceHex, targetHex, mode },
            });

            // Capture colorRemapMap before cancel
            const mapBefore = { ...store.getState().colorRemapMap };

            // Act: cancel by setting pending to null
            store.getState().setPendingReplacement(null);

            const state = store.getState();

            // Assert: pendingReplacement cleared
            expect(state.pendingReplacement).toBeNull();

            // Assert: colorRemapMap unchanged — pre-existing entries preserved
            expect(state.colorRemapMap).toEqual(mapBefore);
            expect(state.colorRemapMap[existingKey]).toBe(existingValue);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("setPendingReplacement(null) clears pending with multi-select sourceColors without modifying colorRemapMap", () => {
      fc.assert(
        fc.property(
          hexColor,
          hexColor,
          hexColorArray,
          hexColor,
          hexColor,
          (sourceHex, targetHex, sourceColors, existingKey, existingValue) => {
            const store = useConverterStore;

            // Set up pre-existing colorRemapMap + multi-select pending
            store.setState({
              colorRemapMap: { [existingKey]: existingValue },
              remapHistory: [],
              pendingReplacement: {
                sourceHex,
                targetHex,
                mode: "multi-select",
                sourceColors,
              },
            });

            // Capture colorRemapMap before cancel
            const mapBefore = { ...store.getState().colorRemapMap };

            // Act: cancel
            store.getState().setPendingReplacement(null);

            const state = store.getState();

            // Assert: pendingReplacement cleared
            expect(state.pendingReplacement).toBeNull();

            // Assert: colorRemapMap unchanged
            expect(state.colorRemapMap).toEqual(mapBefore);
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
