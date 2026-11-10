import { describe, it, expect, beforeEach, vi } from "vitest";
import * as fc from "fast-check";

// Intercept the converter API so applyBatchColorRemap (now routed through
// /replace-colors-batch instead of looping /replace-color) resolves
// without hitting the network. Without this mock, the batch call's
// catch branch would roll back colorRemapMap and break the property
// assertions below.
// Mock converter API 让 applyBatchColorRemap 内部的 replaceColorsBatch
// resolve，否则 catch 分支会回滚 colorRemapMap 导致属性测试失败。
vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>(
      "../api/converter",
    );
  return {
    ...actual,
    replaceColorsBatch: vi.fn().mockResolvedValue({
      status: "ok",
      message: "ok",
      preview_url: "/api/files/fake-preview.png",
      replacement_count: 1,
    }),
  };
});

import { useConverterStore } from "../stores/converter";
import type { SelectionMode } from "../stores/converter";
import type { PaletteEntry } from "../api/types";

// ========== Generators ==========

/** Generate a valid 6-character lowercase hex string (no '#' prefix) */
const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

/** Generate a non-empty palette of unique PaletteEntry items */
const paletteArb = fc
  .uniqueArray(hexColor, { minLength: 1, maxLength: 20 })
  .map((hexes) =>
    hexes.map(
      (h, i): PaletteEntry => ({
        quantized_hex: h,
        matched_hex: h,
        pixel_count: (i + 1) * 100,
        percentage: 100 / hexes.length,
      }),
    ),
  );

/** Generate a non-empty Set<string> of unique hex colors */
const selectedColorsArb = fc
  .uniqueArray(hexColor, { minLength: 1, maxLength: 15 })
  .map((arr) => new Set(arr));

// ========== Helpers ==========

function resetStore(): void {
  useConverterStore.setState({
    selectionMode: "current",
    selectedColors: new Set<string>(),
    selectedColor: null,
    regionData: null,
    palette: [],
    colorRemapMap: {},
    remapHistory: [],
    remapRedoHistory: [],
    replacePreviewLoading: false,
    error: null,
    sessionId: null,
  });
}

// ========== Tests ==========

describe("Feature: color-selection-modes — Property-Based Tests", () => {
  beforeEach(() => {
    resetStore();
  });

  // **Validates: Requirements 1.3**
  describe("Property 1: 全选模式清空多选集合（用户从调色板逐个选择）", () => {
    it("for any palette, switching to select-all clears selectedColors (user picks one color for global replace)", () => {
      fc.assert(
        fc.property(paletteArb, (palette) => {
          resetStore();
          useConverterStore.setState({
            palette,
            selectedColors: new Set(["aabbcc", "ddeeff"]),
          });

          useConverterStore.getState().setSelectionMode("select-all");

          const state = useConverterStore.getState();

          expect(state.selectionMode).toBe("select-all");
          // select-all 模式下 selectedColors 应为空（全局单色替换通过 selectedColor 选择）
          expect(state.selectedColors.size).toBe(0);
        }),
        { numRuns: 100 },
      );
    });
  });

  // **Validates: Requirements 1.4, 1.5, 1.6**
  describe("Property 2: 任意模式切换清空多选集合", () => {
    it("for any non-empty selectedColors, switching to any mode clears selectedColors", () => {
      fc.assert(
        fc.property(
          selectedColorsArb,
          fc.constantFrom<SelectionMode>(
            "current",
            "select-all",
            "multi-select",
            "region",
          ),
          (colors, targetMode) => {
            resetStore();
            // Set up a non-empty selectedColors state
            useConverterStore.setState({
              selectionMode: "multi-select",
              selectedColors: new Set(colors),
            });

            useConverterStore.getState().setSelectionMode(targetMode);

            const state = useConverterStore.getState();
            expect(state.selectionMode).toBe(targetMode);
            expect(state.selectedColors.size).toBe(0);
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  // **Validates: Requirements 5.1**
  describe("Property 3: 多选模式下颜色切换的自逆性", () => {
    it("toggling the same color twice in multi-select mode restores selectedColors to initial state", () => {
      fc.assert(
        fc.property(selectedColorsArb, hexColor, (initialColors, toggleHex) => {
          resetStore();
          useConverterStore.setState({
            selectionMode: "multi-select",
            selectedColors: new Set(initialColors),
          });

          const before = new Set(useConverterStore.getState().selectedColors);

          // Toggle twice
          useConverterStore.getState().toggleColorInSelection(toggleHex);
          useConverterStore.getState().toggleColorInSelection(toggleHex);

          const after = useConverterStore.getState().selectedColors;
          expect(after).toEqual(before);
        }),
        { numRuns: 100 },
      );
    });
  });

  // **Validates: Requirements 3.2, 5.3, 7.1**
  describe("Property 4: 批量替换映射所有选中颜色", () => {
    it("after applyBatchColorRemap, colorRemapMap contains a mapping from each selectedColor to targetHex", async () => {
      // Mock submitSingleReplace to avoid actual network requests
      const originalSubmitSingleReplace =
        useConverterStore.getState().submitSingleReplace;
      useConverterStore.setState({
        submitSingleReplace: vi.fn().mockResolvedValue(undefined),
      } as never);

      await fc.assert(
        fc.asyncProperty(
          selectedColorsArb,
          hexColor,
          async (colors, targetHex) => {
            resetStore();
            // Re-apply mock after reset
            useConverterStore.setState({
              submitSingleReplace: vi.fn().mockResolvedValue(undefined),
              selectionMode: "multi-select",
              selectedColors: new Set(colors),
              sessionId: "test-session",
            } as never);

            await useConverterStore.getState().applyBatchColorRemap(targetHex);

            const { colorRemapMap } = useConverterStore.getState();
            for (const hex of colors) {
              expect(colorRemapMap[hex]).toBe(targetHex);
            }
          },
        ),
        { numRuns: 100 },
      );

      // Restore original
      useConverterStore.setState({
        submitSingleReplace: originalSubmitSingleReplace,
      } as never);
    });
  });

  // **Validates: Requirements 3.3, 5.4**
  describe("Property 5: 批量替换产生单条撤销历史", () => {
    it("after one applyBatchColorRemap call, remapHistory length increases by exactly 1", async () => {
      await fc.assert(
        fc.asyncProperty(
          selectedColorsArb,
          hexColor,
          fc.array(fc.record({ key: hexColor, value: hexColor }), {
            minLength: 0,
            maxLength: 5,
          }),
          async (colors, targetHex, priorRemaps) => {
            resetStore();

            // Build prior remapHistory and colorRemapMap
            const priorMap: Record<string, string> = {};
            const priorHistory: Record<string, string>[] = [];
            for (const { key, value } of priorRemaps) {
              priorHistory.push({ ...priorMap });
              priorMap[key] = value;
            }

            useConverterStore.setState({
              submitSingleReplace: vi.fn().mockResolvedValue(undefined),
              selectionMode: "multi-select",
              selectedColors: new Set(colors),
              colorRemapMap: priorMap,
              remapHistory: priorHistory,
              sessionId: "test-session",
            } as never);

            const historyLenBefore =
              useConverterStore.getState().remapHistory.length;

            await useConverterStore.getState().applyBatchColorRemap(targetHex);

            const historyLenAfter =
              useConverterStore.getState().remapHistory.length;
            expect(historyLenAfter).toBe(historyLenBefore + 1);
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
