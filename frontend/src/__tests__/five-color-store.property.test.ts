import { describe, it, vi, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useFiveColorStore } from "../stores/fiveColorStore";
import type { FiveColorState } from "../stores/fiveColorStore";

// Mock the API module
vi.mock("../api/fiveColor", () => ({
  fetchBaseColors: vi.fn(),
  queryFiveColor: vi.fn(),
}));

import { fetchBaseColors, queryFiveColor } from "../api/fiveColor";

const mockFetchBaseColors = vi.mocked(fetchBaseColors);
const mockQueryFiveColor = vi.mocked(queryFiveColor);

// ========== Helpers ==========

const DEFAULT_STATE: Partial<FiveColorState> = {
  lutName: "",
  baseColors: [],
  selectedIndices: [],
  queryResult: null,
  isLoading: false,
  error: null,
};

function resetStore() {
  useFiveColorStore.setState(DEFAULT_STATE);
}

// ========== Generators ==========

const arbColorIndex = fc.integer({ min: 0, max: 7 });

const arbSelectedIndices = (min: number, max: number) =>
  fc.array(arbColorIndex, { minLength: min, maxLength: max });

const arbLutName = fc.stringMatching(/^[A-Za-z0-9_-]{1,20}$/);

// ========== Property 4: 选择追加与上限为 5 ==========

// **Validates: Requirements 3.1, 3.2**
describe("Feature: five-color-query, Property 4: 选择追加与上限为 5", () => {
  it("addSelection appends when length < 5, ignores when length == 5", () => {
    fc.assert(
      fc.property(arbSelectedIndices(0, 5), arbColorIndex, (indices, newIndex) => {
        resetStore();
        useFiveColorStore.setState({ selectedIndices: [...indices] });

        const originalLength = indices.length;
        useFiveColorStore.getState().addSelection(newIndex);
        const result = useFiveColorStore.getState().selectedIndices;

        if (originalLength < 5) {
          return (
            result.length === originalLength + 1 &&
            result[result.length - 1] === newIndex
          );
        } else {
          // length == 5, array unchanged
          return (
            result.length === 5 &&
            JSON.stringify(result) === JSON.stringify(indices)
          );
        }
      }),
      { numRuns: 100 }
    );
  });
});

// ========== Property 5: 撤销移除最后一个元素 ==========

// **Validates: Requirements 3.3**
describe("Feature: five-color-query, Property 5: 撤销移除最后一个元素", () => {
  it("removeLastSelection removes the last element from a non-empty array", () => {
    fc.assert(
      fc.property(arbSelectedIndices(1, 5), (indices) => {
        resetStore();
        useFiveColorStore.setState({ selectedIndices: [...indices] });

        useFiveColorStore.getState().removeLastSelection();
        const result = useFiveColorStore.getState().selectedIndices;

        const expected = indices.slice(0, -1);
        return JSON.stringify(result) === JSON.stringify(expected);
      }),
      { numRuns: 100 }
    );
  });
});

// ========== Property 6: 清除重置为空 ==========

// **Validates: Requirements 3.4**
describe("Feature: five-color-query, Property 6: 清除重置为空", () => {
  it("clearSelection resets selectedIndices to [] and queryResult to null", () => {
    fc.assert(
      fc.property(arbSelectedIndices(0, 5), (indices) => {
        resetStore();
        useFiveColorStore.setState({
          selectedIndices: [...indices],
          queryResult: {
            found: true,
            selected_indices: [0, 1, 2, 3, 4],
            result_rgb: [128, 64, 32],
            result_hex: "#804020",
            row_index: 42,
            message: "found",
          },
        });

        useFiveColorStore.getState().clearSelection();
        const state = useFiveColorStore.getState();

        return (
          state.selectedIndices.length === 0 &&
          state.queryResult === null
        );
      }),
      { numRuns: 100 }
    );
  });
});

// ========== Property 7: 反序是自逆操作 (round-trip) ==========

// **Validates: Requirements 3.5**
describe("Feature: five-color-query, Property 7: 反序是自逆操作 (round-trip)", () => {
  it("reverseSelection twice restores the original array for length-5 arrays", () => {
    fc.assert(
      fc.property(arbSelectedIndices(5, 5), (indices) => {
        resetStore();
        useFiveColorStore.setState({ selectedIndices: [...indices] });

        useFiveColorStore.getState().reverseSelection();
        useFiveColorStore.getState().reverseSelection();
        const result = useFiveColorStore.getState().selectedIndices;

        return JSON.stringify(result) === JSON.stringify(indices);
      }),
      { numRuns: 100 }
    );
  });
});

// ========== Property 8: 切换 LUT 重置选择和结果 ==========

// **Validates: Requirements 5.3**
describe("Feature: five-color-query, Property 8: 切换 LUT 重置选择和结果", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  it("loadBaseColors resets selectedIndices to [] and queryResult to null", async () => {
    await fc.assert(
      fc.asyncProperty(arbLutName, async (lutName) => {
        // Pre-populate store with some state
        useFiveColorStore.setState({
          selectedIndices: [0, 1, 2, 3, 4],
          queryResult: {
            found: true,
            selected_indices: [0, 1, 2, 3, 4],
            result_rgb: [100, 200, 50],
            result_hex: "#64C832",
            row_index: 10,
            message: "found",
          },
        });

        // Mock API to resolve successfully
        mockFetchBaseColors.mockResolvedValueOnce({
          lut_name: lutName,
          color_count: 4,
          colors: [
            { index: 0, rgb: [255, 0, 0], name: "Red", hex: "#FF0000" },
            { index: 1, rgb: [0, 255, 0], name: "Green", hex: "#00FF00" },
            { index: 2, rgb: [0, 0, 255], name: "Blue", hex: "#0000FF" },
            { index: 3, rgb: [255, 255, 255], name: "White", hex: "#FFFFFF" },
          ],
        });

        await useFiveColorStore.getState().loadBaseColors(lutName);
        const state = useFiveColorStore.getState();

        return (
          state.selectedIndices.length === 0 &&
          state.queryResult === null
        );
      }),
      { numRuns: 100 }
    );
  });
});

// ========== Property 10: Store 捕获 API 错误 ==========

// **Validates: Requirements 4.4, 5.4**
describe("Feature: five-color-query, Property 10: Store 捕获 API 错误", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  it("loadBaseColors failure sets non-empty error and isLoading=false", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbLutName,
        fc.string({ minLength: 1, maxLength: 50 }),
        async (lutName, errorMsg) => {
          mockFetchBaseColors.mockRejectedValueOnce(new Error(errorMsg));

          await useFiveColorStore.getState().loadBaseColors(lutName);
          const state = useFiveColorStore.getState();

          return (
            state.error !== null &&
            state.error.length > 0 &&
            state.isLoading === false
          );
        }
      ),
      { numRuns: 100 }
    );
  });

  it("submitQuery failure sets non-empty error and isLoading=false", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string({ minLength: 1, maxLength: 50 }),
        async (errorMsg) => {
          // Set up valid state for query submission
          useFiveColorStore.setState({
            lutName: "test-lut",
            selectedIndices: [0, 1, 2, 3, 4],
          });

          mockQueryFiveColor.mockRejectedValueOnce(new Error(errorMsg));

          await useFiveColorStore.getState().submitQuery();
          const state = useFiveColorStore.getState();

          // Reset for next iteration
          resetStore();

          return (
            state.error !== null &&
            state.error.length > 0 &&
            state.isLoading === false
          );
        }
      ),
      { numRuns: 100 }
    );
  });
});
