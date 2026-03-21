import { create } from "zustand";
import type { BaseColorEntry, FiveColorQueryResponse } from "../api/types";
import { fetchBaseColors, queryFiveColor } from "../api/fiveColor";

// ========== State Interface ==========

export interface FiveColorState {
  lutName: string;
  baseColors: BaseColorEntry[];
  selectedIndices: number[];
  queryResult: FiveColorQueryResponse | null;
  isLoading: boolean;
  error: string | null;
}

// ========== Actions Interface ==========

export interface FiveColorActions {
  loadBaseColors: (lutName: string) => Promise<void>;
  addSelection: (index: number) => void;
  removeLastSelection: () => void;
  clearSelection: () => void;
  reverseSelection: () => void;
  submitQuery: () => Promise<void>;
  clearError: () => void;
}

// ========== Default State ==========

const DEFAULT_STATE: FiveColorState = {
  lutName: "",
  baseColors: [],
  selectedIndices: [],
  queryResult: null,
  isLoading: false,
  error: null,
};

// ========== Store ==========

export const useFiveColorStore = create<FiveColorState & FiveColorActions>(
  (set, get) => ({
    ...DEFAULT_STATE,

    loadBaseColors: async (lutName: string) => {
      set({
        lutName,
        selectedIndices: [],
        queryResult: null,
        isLoading: true,
        error: null,
      });
      try {
        const response = await fetchBaseColors(lutName);
        set({ baseColors: response.colors, isLoading: false });
      } catch (err) {
        set({
          error: err instanceof Error ? err.message : "加载基础颜色失败",
          isLoading: false,
        });
      }
    },

    addSelection: (index: number) => {
      const { selectedIndices } = get();
      if (selectedIndices.length < 5) {
        set({ selectedIndices: [...selectedIndices, index] });
      }
    },

    removeLastSelection: () => {
      const { selectedIndices } = get();
      set({
        selectedIndices: selectedIndices.slice(0, -1),
        queryResult: null,
      });
    },

    clearSelection: () => {
      set({ selectedIndices: [], queryResult: null });
    },

    reverseSelection: () => {
      const { selectedIndices } = get();
      if (selectedIndices.length === 5) {
        set({
          selectedIndices: [...selectedIndices].reverse(),
          queryResult: null,
        });
      }
    },

    submitQuery: async () => {
      const { selectedIndices, lutName } = get();
      if (selectedIndices.length !== 5) return;
      set({ isLoading: true, error: null });
      try {
        const response = await queryFiveColor({
          lut_name: lutName,
          selected_indices: selectedIndices,
        });
        set({ queryResult: response, isLoading: false });
      } catch (err) {
        set({
          error: err instanceof Error ? err.message : "查询失败",
          isLoading: false,
        });
      }
    },

    clearError: () => {
      set({ error: null });
    },
  }),
);
