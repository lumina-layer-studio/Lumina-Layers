import { create } from "zustand";
import type { CalibrationColorMode, BackingColor } from "../api/types";
import {
  CalibrationColorMode as CalibrationColorModeEnum,
  BackingColor as BackingColorEnum,
} from "../api/types";
import { calibrationGenerate } from "../api/calibration";
import { clampValue } from "./converterStore";

// ========== State Interface ==========

export interface CalibrationState {
  color_mode: CalibrationColorMode;
  block_size: number;
  gap: number;
  backing: BackingColor;
  isLoading: boolean;
  error: string | null;
  downloadUrl: string | null;
  previewImageUrl: string | null;
  modelUrl: string | null;
  statusMessage: string | null;
}

// ========== Actions Interface ==========

export interface CalibrationActions {
  setColorMode: (mode: CalibrationColorMode) => void;
  setBlockSize: (size: number) => void;
  setGap: (gap: number) => void;
  setBacking: (color: BackingColor) => void;
  submitGenerate: () => Promise<void>;
  setError: (error: string | null) => void;
  clearError: () => void;
}

// ========== Default State ==========

const DEFAULT_STATE: CalibrationState = {
  color_mode: CalibrationColorModeEnum.FOUR_COLOR,
  block_size: 5,
  gap: 0.82,
  backing: BackingColorEnum.WHITE,
  isLoading: false,
  error: null,
  downloadUrl: null,
  previewImageUrl: null,
  modelUrl: null,
  statusMessage: null,
};

// ========== Store ==========

export const useCalibrationStore = create<CalibrationState & CalibrationActions>(
  (set, get) => ({
    ...DEFAULT_STATE,

    setColorMode: (mode: CalibrationColorMode) => set({ color_mode: mode }),

    setBlockSize: (size: number) =>
      set({ block_size: clampValue(size, 3, 10) }),

    setGap: (gap: number) =>
      set({ gap: clampValue(gap, 0.4, 2.0) }),

    setBacking: (color: BackingColor) => set({ backing: color }),

    submitGenerate: async () => {
      const state = get();
      set({ isLoading: true, error: null });
      try {
        const response = await calibrationGenerate({
          color_mode: state.color_mode,
          block_size: state.block_size,
          gap: state.gap,
          backing: state.backing,
        });
        const downloadUrl = `http://localhost:8000${response.download_url}`;
        const previewImageUrl = response.preview_url
          ? `http://localhost:8000${response.preview_url}`
          : null;
        // 校准板后端不生成 GLB 预览文件，不设置 modelUrl
        // 8 色模式返回 ZIP 包（两个 3MF），其他模式返回单个 3MF，均非 Three.js 可解析格式
        set({
          downloadUrl,
          previewImageUrl,
          modelUrl: null,
          statusMessage: response.message,
          isLoading: false,
        });
      } catch (err) {
        set({
          error:
            err instanceof Error ? err.message : "校准板生成失败，请重试",
          isLoading: false,
        });
      }
    },

    setError: (error: string | null) => set({ error }),
    clearError: () => set({ error: null }),
  })
);
