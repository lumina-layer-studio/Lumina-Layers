import { create } from "zustand";
import type { ExtractorColorMode, ExtractorPage } from "../api/types";
import {
  ExtractorColorMode as ExtractorColorModeEnum,
  ExtractorPage as ExtractorPageEnum,
} from "../api/types";
import {
  confirmPalette,
  extractColors,
  manualFixCell,
  mergeEightColor,
  mergeFiveColorExtended,
} from "../api/extractor";
import type { ExtractorPaletteEntry } from "../api/types";
import { clampValue } from "./converterStore";

// ========== State Interface ==========

export interface ExtractorState {
  // 图片
  imageFile: File | null;
  imagePreviewUrl: string | null;
  imageNaturalWidth: number | null;
  imageNaturalHeight: number | null;

  // 颜色模式与页码
  color_mode: ExtractorColorMode;
  page: ExtractorPage;

  // 角点
  corner_points: Array<[number, number]>;

  // 提取参数
  offset_x: number;
  offset_y: number;
  zoom: number;
  distortion: number;
  vignette_correction: boolean;

  // API 状态
  isLoading: boolean;
  error: string | null;
  session_id: string | null;

  // 提取结果
  lut_download_url: string | null;
  warp_view_url: string | null;
  lut_preview_url: string | null;

  // 手动修正
  manualFixLoading: boolean;
  manualFixError: string | null;

  // 8色双页状态
  page1Extracted: boolean;
  page2Extracted: boolean;
  mergeLoading: boolean;
  mergeError: string | null;

  // 5色扩展双页状态
  page1Extracted_5c: boolean;
  page2Extracted_5c: boolean;

  // 调色板确认
  manufacturer: string;
  type: string;
  defaultPalette: ExtractorPaletteEntry[];
  paletteConfirmed: boolean;
  paletteConfirmLoading: boolean;
  paletteConfirmError: string | null;
}

// ========== Actions Interface ==========

export interface ExtractorActions {
  setImageFile: (file: File | null) => void;
  setColorMode: (mode: ExtractorColorMode) => void;
  setPage: (page: ExtractorPage) => void;
  addCornerPoint: (point: [number, number]) => void;
  clearCornerPoints: () => void;
  setOffsetX: (value: number) => void;
  setOffsetY: (value: number) => void;
  setZoom: (value: number) => void;
  setDistortion: (value: number) => void;
  setVignetteCorrection: (value: boolean) => void;
  setManufacturer: (value: string) => void;
  setType: (value: string) => void;
  submitExtract: () => Promise<void>;
  submitManualFix: (row: number, col: number, color: string) => Promise<void>;
  submitMerge: () => Promise<void>;
  setError: (error: string | null) => void;
  clearError: () => void;
  updatePaletteEntry: (index: number, entry: Partial<ExtractorPaletteEntry>) => void;
  submitConfirmPalette: () => Promise<void>;
}

// ========== Default State ==========

const DEFAULT_STATE: ExtractorState = {
  imageFile: null,
  imagePreviewUrl: null,
  imageNaturalWidth: null,
  imageNaturalHeight: null,
  color_mode: ExtractorColorModeEnum.FOUR_COLOR_RYBW,
  page: ExtractorPageEnum.PAGE_1,
  corner_points: [],
  offset_x: 0,
  offset_y: 0,
  zoom: 1.0,
  distortion: 0.0,
  vignette_correction: false,
  isLoading: false,
  error: null,
  session_id: null,
  lut_download_url: null,
  warp_view_url: null,
  lut_preview_url: null,
  manualFixLoading: false,
  manualFixError: null,
  page1Extracted: false,
  page2Extracted: false,
  mergeLoading: false,
  mergeError: null,
  page1Extracted_5c: false,
  page2Extracted_5c: false,
  manufacturer: "",
  type: "",
  defaultPalette: [],
  paletteConfirmed: false,
  paletteConfirmLoading: false,
  paletteConfirmError: null,
};

// ========== Store ==========

export const useExtractorStore = create<ExtractorState & ExtractorActions>(
  (set, get) => ({
    ...DEFAULT_STATE,

    setImageFile: (file: File | null) => {
      // Revoke previous object URL to avoid memory leaks
      const prev = get().imagePreviewUrl;
      if (prev) {
        URL.revokeObjectURL(prev);
      }

      if (!file) {
        set({
          imageFile: null,
          imagePreviewUrl: null,
          imageNaturalWidth: null,
          imageNaturalHeight: null,
          corner_points: [],
          session_id: null,
          lut_download_url: null,
          warp_view_url: null,
          lut_preview_url: null,
          defaultPalette: [],
          paletteConfirmed: false,
          paletteConfirmError: null,
        });
        return;
      }

      const previewUrl = URL.createObjectURL(file);

      // Load image to get natural dimensions
      const img = new Image();
      img.onload = () => {
        set({
          imageNaturalWidth: img.naturalWidth,
          imageNaturalHeight: img.naturalHeight,
        });
      };
      img.src = previewUrl;

      set({
        imageFile: file,
        imagePreviewUrl: previewUrl,
        imageNaturalWidth: null,
        imageNaturalHeight: null,
        // Clear previous corner points and extraction results
        corner_points: [],
        session_id: null,
        lut_download_url: null,
        warp_view_url: null,
        lut_preview_url: null,
        defaultPalette: [],
        paletteConfirmed: false,
        paletteConfirmError: null,
      });
    },

    setColorMode: (mode: ExtractorColorMode) => set({
      color_mode: mode,
      // Reset 8-color and 5-color page tracking when switching modes
      page1Extracted: false,
      page2Extracted: false,
      page1Extracted_5c: false,
      page2Extracted_5c: false,
      mergeError: null,
      defaultPalette: [],
      paletteConfirmed: false,
      paletteConfirmError: null,
    }),

    setPage: (page: ExtractorPage) => set({ page }),

    addCornerPoint: (point: [number, number]) => {
      const { corner_points } = get();
      if (corner_points.length >= 4) return;
      set({ corner_points: [...corner_points, point] });
    },

    clearCornerPoints: () => set({ corner_points: [] }),

    setOffsetX: (value: number) =>
      set({ offset_x: clampValue(value, -30, 30) }),

    setOffsetY: (value: number) =>
      set({ offset_y: clampValue(value, -30, 30) }),

    setZoom: (value: number) =>
      set({ zoom: clampValue(value, 0.8, 1.2) }),

    setDistortion: (value: number) =>
      set({ distortion: clampValue(value, -0.2, 0.2) }),

    setVignetteCorrection: (value: boolean) =>
      set({ vignette_correction: value }),

    setManufacturer: (value: string) => set({ manufacturer: value }),

    setType: (value: string) => set({ type: value }),

    submitExtract: async () => {
      const state = get();
      if (!state.imageFile || state.corner_points.length < 4) return;

      set({ isLoading: true, error: null });
      try {
        const response = await extractColors(state.imageFile, {
          corner_points: state.corner_points,
          color_mode: state.color_mode,
          page: state.page,
          offset_x: state.offset_x,
          offset_y: state.offset_y,
          zoom: state.zoom,
          distortion: state.distortion,
          vignette_correction: state.vignette_correction,
        });
        const BASE = "http://localhost:8000";

        // Track 8-color page extraction status
        const pageUpdate: Partial<ExtractorState> = {};
        if (state.color_mode === ExtractorColorModeEnum.EIGHT_COLOR) {
          if (state.page === ExtractorPageEnum.PAGE_1) {
            pageUpdate.page1Extracted = true;
          } else {
            pageUpdate.page2Extracted = true;
          }
        }
        // Track 5-Color Extended page extraction status
        if (state.color_mode === ExtractorColorModeEnum.FIVE_COLOR_EXT) {
          if (state.page === ExtractorPageEnum.PAGE_1) {
            pageUpdate.page1Extracted_5c = true;
          } else {
            pageUpdate.page2Extracted_5c = true;
          }
        }

        set({
          session_id: response.session_id,
          lut_download_url: response.lut_download_url
            ? `${BASE}${response.lut_download_url}`
            : null,
          warp_view_url: response.warp_view_url
            ? `${BASE}${response.warp_view_url}`
            : null,
          lut_preview_url: response.lut_preview_url
            ? `${BASE}${response.lut_preview_url}`
            : null,
          isLoading: false,
          defaultPalette: response.default_palette ?? [],
          paletteConfirmed: false,
          paletteConfirmError: null,
          ...pageUpdate,
        });
      } catch (err) {
        set({
          error:
            err instanceof Error ? err.message : "颜色提取失败，请重试",
          isLoading: false,
        });
      }
    },

    submitManualFix: async (row: number, col: number, color: string) => {
      const state = get();
      if (!state.session_id) return;

      set({ manualFixLoading: true, manualFixError: null });
      try {
        const response = await manualFixCell(
          state.session_id,
          [row, col],
          color
        );
        set({
          lut_preview_url: response.lut_preview_url
            ? `http://localhost:8000${response.lut_preview_url}`
            : null,
          manualFixLoading: false,
        });
      } catch (err) {
        set({
          manualFixError:
            err instanceof Error ? err.message : "手动修正失败，请重试",
          manualFixLoading: false,
        });
      }
    },

    submitMerge: async () => {
      const state = get();
      // Determine which page states to check based on color_mode
      const is5c = state.color_mode === ExtractorColorModeEnum.FIVE_COLOR_EXT;
      const bothExtracted = is5c
        ? state.page1Extracted_5c && state.page2Extracted_5c
        : state.page1Extracted && state.page2Extracted;

      if (!bothExtracted) return;

      set({ mergeLoading: true, mergeError: null });
      try {
        const response = is5c
          ? await mergeFiveColorExtended()
          : await mergeEightColor();
        const BASE = "http://localhost:8000";
        set({
          session_id: response.session_id,
          lut_download_url: response.lut_download_url
            ? `${BASE}${response.lut_download_url}`
            : null,
          warp_view_url: response.warp_view_url
            ? `${BASE}${response.warp_view_url}`
            : null,
          lut_preview_url: response.lut_preview_url
            ? `${BASE}${response.lut_preview_url}`
            : null,
          defaultPalette: response.default_palette ?? [],
          paletteConfirmed: false,
          paletteConfirmError: null,
          mergeLoading: false,
        });
      } catch (err) {
        set({
          mergeError:
            err instanceof Error ? err.message : "合并失败，请重试",
          mergeLoading: false,
        });
      }
    },

    setError: (error: string | null) => set({ error }),
    clearError: () => set({ error: null }),

    updatePaletteEntry: (index: number, entry: Partial<ExtractorPaletteEntry>) => {
      const palette = [...get().defaultPalette];
      if (index >= 0 && index < palette.length) {
        palette[index] = { ...palette[index], ...entry };
        set({ defaultPalette: palette });
      }
    },

    submitConfirmPalette: async () => {
      const state = get();
      if (!state.session_id || state.defaultPalette.length === 0) return;

      set({ paletteConfirmLoading: true, paletteConfirmError: null });
      try {
        await confirmPalette({
          session_id: state.session_id,
          manufacturer: state.manufacturer.trim(),
          type: state.type.trim(),
          palette: state.defaultPalette.map((entry) => ({
            ...entry,
            color_name: entry.color_name?.trim() || null,
          })),
        });
        set({ paletteConfirmed: true, paletteConfirmLoading: false });
      } catch (err) {
        set({
          paletteConfirmError:
            err instanceof Error ? err.message : "调色板确认失败，请重试",
          paletteConfirmLoading: false,
        });
      }
    },
  })
);
