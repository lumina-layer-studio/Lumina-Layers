import { create } from "zustand";
import type { VectorizeParams, VectorizeResponse } from "../api/types";
import { vectorizeImage } from "../api/vectorizer";

export interface VectorizerState {
  imageFile: File | null;
  imagePreviewUrl: string | null;
  params: VectorizeParams;
  isProcessing: boolean;
  error: string | null;
  result: VectorizeResponse | null;
  abortController: AbortController | null;
}

export interface VectorizerActions {
  setImageFile: (file: File | null) => void;
  setParam: <K extends keyof VectorizeParams>(key: K, value: VectorizeParams[K]) => void;
  submit: () => Promise<void>;
  cancel: () => void;
  reset: () => void;
}

const DEFAULT_PARAMS: VectorizeParams = {
  num_colors: 0,
  smoothness: 0.5,
  detail_level: -1,
  svg_enable_stroke: true,
  svg_stroke_width: 0.5,
  thin_line_max_radius: 2.5,
  enable_coverage_fix: true,
  min_coverage_ratio: 0.998,
  smoothing_spatial: 15,
  smoothing_color: 25,
  max_working_pixels: 3000000,
  slic_region_size: 20,
  edge_sensitivity: 0.8,
  refine_passes: 6,
  enable_antialias_detect: false,
  aa_tolerance: 10,
  curve_fit_error: 0.8,
  contour_simplify: 0.45,
  merge_segment_tolerance: 0.05,
  min_region_area: 50,
  max_merge_color_dist: 200,
  min_contour_area: 10,
  min_hole_area: 4,
};

const DEFAULT_STATE: Omit<VectorizerState, "params"> = {
  imageFile: null,
  imagePreviewUrl: null,
  isProcessing: false,
  error: null,
  result: null,
  abortController: null,
};

export const useVectorizerStore = create<VectorizerState & VectorizerActions>(
  (set, get) => ({
    ...DEFAULT_STATE,
    params: { ...DEFAULT_PARAMS },

    setImageFile: (file: File | null) => {
      const prev = get().imagePreviewUrl;
      if (prev) URL.revokeObjectURL(prev);

      if (file) {
        const url = URL.createObjectURL(file);
        set({ imageFile: file, imagePreviewUrl: url, result: null, error: null });
      } else {
        set({ imageFile: null, imagePreviewUrl: null, result: null, error: null });
      }
    },

    setParam: (key, value) => {
      set((state) => ({
        params: { ...state.params, [key]: value },
      }));
    },

    submit: async () => {
      const { imageFile, params } = get();
      if (!imageFile) return;

      const controller = new AbortController();
      set({ isProcessing: true, error: null, result: null, abortController: controller });

      try {
        const result = await vectorizeImage(imageFile, params, controller.signal);
        set({ result, isProcessing: false, abortController: null });
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "CanceledError") {
          set({ isProcessing: false, abortController: null });
          return;
        }
        const message = err instanceof Error ? err.message : String(err);
        set({ error: message, isProcessing: false, abortController: null });
      }
    },

    cancel: () => {
      const { abortController } = get();
      if (abortController) {
        abortController.abort();
        set({ isProcessing: false, abortController: null });
      }
    },

    reset: () => {
      const { imagePreviewUrl, abortController } = get();
      if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
      if (abortController) abortController.abort();
      set({ ...DEFAULT_STATE, params: { ...DEFAULT_PARAMS } });
    },
  }),
);
