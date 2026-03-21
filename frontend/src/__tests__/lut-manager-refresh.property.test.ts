import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fc from "fast-check";

// Mock API modules BEFORE importing stores
const mockMergeLuts = vi.fn();
const mockFetchLutList = vi.fn();
const mockFetchLutInfo = vi.fn();

vi.mock("../api/lut", () => ({
  fetchLutInfo: (...args: unknown[]) => mockFetchLutInfo(...args),
  mergeLuts: (...args: unknown[]) => mockMergeLuts(...args),
}));

vi.mock("../api/converter", () => ({
  fetchLutList: (...args: unknown[]) => mockFetchLutList(...args),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
}));

import { useLutManagerStore } from "../stores/lutManagerStore";
import { useConverterStore } from "../stores/converterStore";

// ========== Tests ==========

describe("Property 5: 合并后全局 LUT 列表刷新", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset both stores to default state
    useLutManagerStore.setState({
      lutList: [],
      lutListLoading: false,
      primaryName: "",
      primaryInfo: null,
      primaryLoading: false,
      secondaryNames: [],
      secondaryInfos: new Map(),
      filteredSecondaryOptions: [],
      dedupThreshold: 3.0,
      merging: false,
      mergeResult: null,
      error: null,
    });
    useConverterStore.setState({
      lutList: [],
      lutListLoading: false,
    });
  });

  // **Validates: Requirements 7.1, 7.2**
  it("converterStore.lutList contains the new merged LUT filename after successful merge", async () => {
    await fc.assert(
      fc.asyncProperty(
        // Generate a random merged filename
        fc.string({ minLength: 1, maxLength: 30 }).map((s) => `Merged_${s}.npz`),
        // Generate random merge stats
        fc.record({
          total_before: fc.integer({ min: 10, max: 5000 }),
          exact_dupes: fc.integer({ min: 0, max: 100 }),
          similar_removed: fc.integer({ min: 0, max: 100 }),
        }),
        // Generate random existing LUT names
        fc.array(fc.string({ minLength: 1, maxLength: 20 }), {
          minLength: 0,
          maxLength: 5,
        }),
        async (mergedFilename, statsInput, existingLuts) => {
          const totalAfter =
            statsInput.total_before -
            statsInput.exact_dupes -
            statsInput.similar_removed;
          const safeTotalAfter = Math.max(totalAfter, 0);

          // Mock mergeLuts to return success with the generated filename
          mockMergeLuts.mockResolvedValueOnce({
            status: "success",
            message: "Merge complete",
            filename: mergedFilename,
            stats: {
              total_before: statsInput.total_before,
              total_after: safeTotalAfter,
              exact_dupes: statsInput.exact_dupes,
              similar_removed: statsInput.similar_removed,
            },
          });

          // Build the LUT list that includes the new merged file
          const allLutNames = [...existingLuts, mergedFilename];
          const lutListResponse = {
            luts: allLutNames.map((name) => ({
              name,
              color_mode: "Merged",
              path: `/fake/${name}`,
            })),
          };

          // fetchLutList is called twice: once by converterStore, once by lutManagerStore
          mockFetchLutList.mockResolvedValue(lutListResponse);

          // Set up store with valid primary and secondary
          useLutManagerStore.setState({
            primaryName: "TestPrimary_8Color",
            secondaryNames: ["TestSecondary_4Color"],
            dedupThreshold: 3.0,
          });

          // Execute merge
          await useLutManagerStore.getState().executeMerge();

          // Wait for the async fetchLutList calls triggered inside executeMerge
          await vi.waitFor(() => {
            expect(mockFetchLutList).toHaveBeenCalled();
          });

          // Verify converterStore's lutList contains the new merged filename
          const converterLutList = useConverterStore.getState().lutList;
          expect(converterLutList).toContain(mergedFilename);

          // Clean up for next iteration
          vi.clearAllMocks();
          useLutManagerStore.setState({
            primaryName: "",
            secondaryNames: [],
            merging: false,
            mergeResult: null,
            error: null,
          });
          useConverterStore.setState({
            lutList: [],
            lutListLoading: false,
          });
        }
      ),
      { numRuns: 100 }
    );
  });
});
