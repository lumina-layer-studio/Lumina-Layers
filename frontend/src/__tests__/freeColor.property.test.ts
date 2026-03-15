import { describe, it, expect, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useConverterStore } from "../stores/converterStore";

// ========== Generators ==========

/** Generate a valid 6-character lowercase hex string (no '#' prefix) */
const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

/** Generate a non-empty Set<string> of unique hex colors */
const hexSetArb = fc
  .uniqueArray(hexColor, { minLength: 0, maxLength: 20 })
  .map((arr) => new Set(arr));

// ========== Helpers ==========

function resetStore(): void {
  useConverterStore.setState({
    free_color_set: new Set<string>(),
    threemfDiskPath: null,
    downloadUrl: null,
  });
}

// ========== Tests ==========

describe("Feature: free-color-mode — Property-Based Tests", () => {
  beforeEach(() => {
    resetStore();
  });

  // **Validates: Requirements 1.1, 1.2**
  describe("Property 1: Toggle 自反性（Round-Trip）", () => {
    it("toggling the same hex twice restores free_color_set to its initial state", () => {
      fc.assert(
        fc.property(hexSetArb, hexColor, (initialSet, hex) => {
          resetStore();
          useConverterStore.setState({ free_color_set: new Set(initialSet) });

          const before = new Set(useConverterStore.getState().free_color_set);

          // Toggle twice
          useConverterStore.getState().toggleFreeColor(hex);
          useConverterStore.getState().toggleFreeColor(hex);

          const after = useConverterStore.getState().free_color_set;
          expect(after).toEqual(before);
        }),
        { numRuns: 100 },
      );
    });
  });

  // **Validates: Requirements 1.3**
  describe("Property 2: Clear 清空性", () => {
    it("clearFreeColors empties any non-empty free_color_set", () => {
      const nonEmptyHexSet = fc
        .uniqueArray(hexColor, { minLength: 1, maxLength: 20 })
        .map((arr) => new Set(arr));

      fc.assert(
        fc.property(nonEmptyHexSet, (initialSet) => {
          resetStore();
          useConverterStore.setState({ free_color_set: new Set(initialSet) });

          useConverterStore.getState().clearFreeColors();

          expect(useConverterStore.getState().free_color_set.size).toBe(0);
        }),
        { numRuns: 100 },
      );
    });
  });

  // **Validates: Requirements 1.4**
  describe("Property 3: 缓存失效", () => {
    it("toggleFreeColor invalidates threemfDiskPath and downloadUrl", () => {
      fc.assert(
        fc.property(hexColor, (hex) => {
          resetStore();
          useConverterStore.setState({
            threemfDiskPath: "/some/path.3mf",
            downloadUrl: "http://example.com/download",
          });

          useConverterStore.getState().toggleFreeColor(hex);

          const state = useConverterStore.getState();
          expect(state.threemfDiskPath).toBeNull();
          expect(state.downloadUrl).toBeNull();
        }),
        { numRuns: 100 },
      );
    });

    it("clearFreeColors invalidates threemfDiskPath and downloadUrl", () => {
      fc.assert(
        fc.property(hexSetArb, (initialSet) => {
          resetStore();
          useConverterStore.setState({
            free_color_set: new Set(initialSet),
            threemfDiskPath: "/some/path.3mf",
            downloadUrl: "http://example.com/download",
          });

          useConverterStore.getState().clearFreeColors();

          const state = useConverterStore.getState();
          expect(state.threemfDiskPath).toBeNull();
          expect(state.downloadUrl).toBeNull();
        }),
        { numRuns: 100 },
      );
    });
  });

  // **Validates: Requirements 7.1**
  describe("Property 4: Set-Array 序列化一致性", () => {
    it("Set → Array → Set preserves all elements", () => {
      fc.assert(
        fc.property(hexSetArb, (originalSet) => {
          const array = Array.from(originalSet);
          const roundTripped = new Set(array);
          expect(roundTripped).toEqual(originalSet);
        }),
        { numRuns: 100 },
      );
    });
  });
});
