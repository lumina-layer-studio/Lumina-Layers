import { create } from "zustand";
import type {
  ColorMode,
  ModelingMode,
  StructureMode,
  ColorReplacementItem,
  BedSizeItem,
  PaletteEntry,
  AutoHeightMode,
  BatchResponse,
} from "../api/types";
import {
  ColorMode as ColorModeEnum,
  ModelingMode as ModelingModeEnum,
  StructureMode as StructureModeEnum,
} from "../api/types";
import {
  fetchLutList as apiFetchLutList,
  convertPreview as apiConvertPreview,
  convertGenerate as apiConvertGenerate,
  fetchBedSizes as apiFetchBedSizes,
  uploadHeightmap as apiUploadHeightmap,
  fetchLutColors as apiFetchLutColors,
  cropImage as apiCropImage,
  convertBatch as apiConvertBatch,
  replaceColor as apiReplaceColor,
} from "../api/converter";
import type { LutColorEntry, LutInfo } from "../api/types";
import {
  computeAutoHeightMap,
  colorRemapToReplacementRegions,
} from "../utils/colorUtils";
import { useSettingsStore } from "./settingsStore";

// ========== Helpers ==========

export function clampValue(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

const VALID_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/svg+xml",
]);

export function isValidImageType(mimeType: string): boolean {
  return VALID_IMAGE_TYPES.has(mimeType);
}

// ========== State Interface ==========

export interface ConverterState {
  // 图片
  imageFile: File | null;
  imagePreviewUrl: string | null;
  aspectRatio: number | null;

  // 会话（预览后由后端返回）
  sessionId: string | null;

  // 基础参数
  lut_name: string;
  target_width_mm: number;
  target_height_mm: number;
  spacer_thick: number;
  structure_mode: StructureMode;
  color_mode: ColorMode;
  modeling_mode: ModelingMode;

  // 高级设置
  auto_bg: boolean;
  bg_tol: number;
  quantize_colors: number;
  enable_cleanup: boolean;
  separate_backing: boolean;

  // 挂件环
  add_loop: boolean;
  loop_width: number;
  loop_length: number;
  loop_hole: number;

  // 浮雕
  enable_relief: boolean;
  color_height_map: Record<string, number>;
  heightmap_max_height: number;

  // 描边
  enable_outline: boolean;
  outline_width: number;

  // 掐丝珐琅
  enable_cloisonne: boolean;
  wire_width_mm: number;
  wire_height_mm: number;

  // 涂层
  enable_coating: boolean;
  coating_height_mm: number;

  // 颜色替换
  replacement_regions: ColorReplacementItem[];
  free_color_set: Set<string>;

  // 调色板与选择
  selectedColor: string | null;
  palette: PaletteEntry[];

  // 颜色替换映射（纯前端）
  colorRemapMap: Record<string, string>;
  remapHistory: Record<string, string>[];

  // 颜色轮廓数据（后端 OpenCV 提取，用于 3D 高亮）
  colorContours: Record<string, number[][][]>;
  // 浮雕联动
  autoHeightMode: AutoHeightMode;
  heightmapFile: File | null;
  heightmapThumbnailUrl: string | null;

  // 3D 预览
  previewGlbUrl: string | null;

  // 预览时的原始尺寸（用于实时缩放比例计算）
  preview_width_mm: number | null;   // 预览时的原始宽度
  preview_height_mm: number | null;  // 预览时的原始高度
  preview_spacer_thick: number | null; // 预览时的原始厚度

  // 模型边界（供 KeychainRing3D 定位）
  modelBounds: {
    minX: number;
    maxX: number;
    minY: number;
    maxY: number;
    maxZ: number;
  } | null;

  // 裁剪
  enableCrop: boolean;
  cropModalOpen: boolean;
  isCropping: boolean;

  // UI 状态
  isLoading: boolean;
  error: string | null;
  previewImageUrl: string | null;
  modelUrl: string | null;

  // LUT 列表
  lutList: string[];
  lutListLoading: boolean;
  lutListFull: LutInfo[];

  // LUT 全部颜色
  lutColors: LutColorEntry[];
  lutColorsLoading: boolean;
  lutColorsLutName: string;

  // 热床尺寸
  bed_label: string;
  bedSizes: BedSizeItem[];
  bedSizesLoading: boolean;

  // 批量模式
  batchMode: boolean;
  batchFiles: File[];
  batchLoading: boolean;
  batchResult: BatchResponse | null;

  // 颜色替换预览
  replacePreviewLoading: boolean;
  originalPreviewUrl: string | null;

  // 切片集成：3MF 路径
  threemfDiskPath: string | null;
  downloadUrl: string | null;
}

// ========== Actions Interface ==========

export interface ConverterActions {
  // 图片
  setImageFile: (file: File | null) => void;

  // 参数 setter
  setLutName: (name: string) => void;
  setTargetWidthMm: (width: number) => void;
  setTargetHeightMm: (height: number) => void;
  setSpacerThick: (thick: number) => void;
  setStructureMode: (mode: StructureMode) => void;
  setColorMode: (mode: ColorMode) => void;
  setModelingMode: (mode: ModelingMode) => void;
  setAutoBg: (enabled: boolean) => void;
  setBgTol: (tol: number) => void;
  setQuantizeColors: (colors: number) => void;
  setEnableCleanup: (enabled: boolean) => void;
  setSeparateBacking: (enabled: boolean) => void;
  setAddLoop: (enabled: boolean) => void;
  setLoopWidth: (width: number) => void;
  setLoopLength: (length: number) => void;
  setLoopHole: (hole: number) => void;
  setEnableRelief: (enabled: boolean) => void;
  setColorHeightMap: (map: Record<string, number>) => void;
  setHeightmapMaxHeight: (height: number) => void;
  setEnableOutline: (enabled: boolean) => void;
  setOutlineWidth: (width: number) => void;
  setEnableCloisonne: (enabled: boolean) => void;
  setWireWidthMm: (width: number) => void;
  setWireHeightMm: (height: number) => void;
  setEnableCoating: (enabled: boolean) => void;
  setCoatingHeightMm: (height: number) => void;

  // 热床尺寸
  setBedLabel: (label: string) => void;
  fetchBedSizes: () => Promise<void>;

  // 调色板与选择
  setSelectedColor: (hex: string | null) => void;
  setPalette: (entries: PaletteEntry[]) => void;

  // 颜色替换（纯前端）
  applyColorRemap: (origHex: string, newHex: string) => void;
  undoColorRemap: () => void;
  clearAllRemaps: () => void;

  // 浮雕高度
  updateColorHeight: (hex: string, heightMm: number) => void;
  applyAutoHeight: (mode: 'darker-higher' | 'lighter-higher') => void;
  setAutoHeightMode: (mode: AutoHeightMode) => void;

  // 高度图
  setHeightmapFile: (file: File | null) => void;
  uploadHeightmap: () => Promise<void>;

  // GLB 预览
  setPreviewGlbUrl: (url: string | null) => void;

  // 模型边界
  setModelBounds: (bounds: ConverterState['modelBounds']) => void;

  // API 操作
  fetchLutList: () => Promise<void>;
  fetchLutColors: (lutName: string) => Promise<void>;
  submitPreview: () => Promise<void>;
  submitGenerate: () => Promise<string | null>;

  // 裁剪
  setEnableCrop: (enabled: boolean) => void;
  setCropModalOpen: (open: boolean) => void;
  submitCrop: (x: number, y: number, width: number, height: number) => Promise<void>;

  // 批量模式
  setBatchMode: (enabled: boolean) => void;
  addBatchFiles: (files: File[]) => void;
  removeBatchFile: (index: number) => void;
  clearBatchFiles: () => void;
  submitBatch: () => Promise<void>;

  // 颜色替换预览
  submitReplacePreview: () => Promise<void>;
  submitSingleReplace: (origHex: string, newHex: string) => Promise<void>;

  // 完整流水线（preview → generate）
  submitFullPipeline: () => Promise<string | null>;

  // UI 状态
  setError: (error: string | null) => void;
  clearError: () => void;
}


// ========== localStorage Helpers ==========

function loadEnableCrop(): boolean {
  try {
    const stored = localStorage.getItem("lumina_enableCrop");
    if (stored === null) return true;
    return stored === "true";
  } catch {
    return true;
  }
}

function loadLutName(): string {
  try {
    return localStorage.getItem("lumina_lastLut") ?? "";
  } catch {
    return "";
  }
}

// ========== Default State ==========

const DEFAULT_STATE: ConverterState = {
  imageFile: null,
  imagePreviewUrl: null,
  aspectRatio: null,
  sessionId: null,
  lut_name: loadLutName(),
  target_width_mm: 60,
  target_height_mm: 60,
  spacer_thick: 1.2,
  structure_mode: StructureModeEnum.DOUBLE_SIDED,
  color_mode: ColorModeEnum.FOUR_COLOR,
  modeling_mode: ModelingModeEnum.HIGH_FIDELITY,
  auto_bg: false,
  bg_tol: 40,
  quantize_colors: 48,
  enable_cleanup: true,
  separate_backing: false,
  add_loop: false,
  loop_width: 4.0,
  loop_length: 8.0,
  loop_hole: 2.5,
  enable_relief: false,
  color_height_map: {},
  heightmap_max_height: 5.0,
  enable_outline: false,
  outline_width: 2.0,
  enable_cloisonne: false,
  wire_width_mm: 0.4,
  wire_height_mm: 0.4,
  enable_coating: false,
  coating_height_mm: 0.08,
  replacement_regions: [],
  free_color_set: new Set(),
  selectedColor: null,
  palette: [],
  colorRemapMap: {},
  remapHistory: [],
  colorContours: {},
  autoHeightMode: 'darker-higher' as AutoHeightMode,
  heightmapFile: null,
  heightmapThumbnailUrl: null,
  previewGlbUrl: null,
  preview_width_mm: null,
  preview_height_mm: null,
  preview_spacer_thick: null,
  modelBounds: null,
  enableCrop: loadEnableCrop(),
  cropModalOpen: false,
  isCropping: false,
  isLoading: false,
  error: null,
  previewImageUrl: null,
  modelUrl: null,
  lutList: [],
  lutListLoading: false,
  lutListFull: [],
  lutColors: [],
  lutColorsLoading: false,
  lutColorsLutName: '',
  bed_label: "256×256 mm",
  bedSizes: [],
  bedSizesLoading: false,
  batchMode: false,
  batchFiles: [],
  batchLoading: false,
  batchResult: null,
  replacePreviewLoading: false,
  originalPreviewUrl: null,
  threemfDiskPath: null,
  downloadUrl: null,
};

// ========== Preview AbortController ==========

let _previewAbortController: AbortController | null = null;

// ========== Store ==========

export const useConverterStore = create<ConverterState & ConverterActions>(
  (set, _get) => ({
    ...DEFAULT_STATE,

    // --- 图片 ---
    setImageFile: (file: File | null) => {
      // Revoke previous object URL to avoid memory leaks
      const prev = _get().imagePreviewUrl;
      if (prev) {
        URL.revokeObjectURL(prev);
      }

      if (!file) {
        set({ imageFile: null, imagePreviewUrl: null, aspectRatio: null });
        return;
      }

      const previewUrl = URL.createObjectURL(file);

      // Calculate aspect ratio from image dimensions
      const img = new Image();
      img.onload = () => {
        const ratio = img.naturalWidth / img.naturalHeight;
        set({ aspectRatio: ratio });
      };
      img.src = previewUrl;

      const shouldOpenCrop = _get().enableCrop;
      set({
        imageFile: file,
        imagePreviewUrl: previewUrl,
        cropModalOpen: shouldOpenCrop,
      });
    },

    // --- 基础参数 ---
    setLutName: (name: string) => {
      const state = _get();
      const lutInfo = state.lutListFull.find((l) => l.name === name);
      const updates: Partial<ConverterState> = { lut_name: name };
      if (lutInfo && lutInfo.color_mode) {
        updates.color_mode = lutInfo.color_mode as ColorMode;
      }
      set(updates);
      try { localStorage.setItem("lumina_lastLut", name); } catch { /* noop */ }
      // 仅当 LUT 名称实际变化时获取颜色
      if (name && name !== state.lutColorsLutName) {
        _get().fetchLutColors(name);
      }
    },

    setTargetWidthMm: (width: number) =>
      set((state) => {
        const clamped = clampValue(width, 10, 400);
        if (state.aspectRatio) {
          return {
            target_width_mm: clamped,
            target_height_mm: clampValue(
              Math.round(clamped / state.aspectRatio),
              10,
              400
            ),
            threemfDiskPath: null,
            downloadUrl: null,
          };
        }
        return { target_width_mm: clamped, threemfDiskPath: null, downloadUrl: null };
      }),

    setTargetHeightMm: (height: number) =>
      set((state) => {
        const clamped = clampValue(height, 10, 400);
        if (state.aspectRatio) {
          return {
            target_height_mm: clamped,
            target_width_mm: clampValue(
              Math.round(clamped * state.aspectRatio),
              10,
              400
            ),
          };
        }
        return { target_height_mm: clamped };
      }),

    setSpacerThick: (thick: number) =>
      set({ spacer_thick: clampValue(thick, 0.2, 3.5), threemfDiskPath: null, downloadUrl: null }),

    setStructureMode: (mode: StructureMode) => set({ structure_mode: mode, threemfDiskPath: null, downloadUrl: null }),
    setColorMode: (mode: ColorMode) => set({ color_mode: mode, threemfDiskPath: null, downloadUrl: null }),
    setModelingMode: (mode: ModelingMode) => set({ modeling_mode: mode, threemfDiskPath: null, downloadUrl: null }),

    // --- 高级设置 ---
    setAutoBg: (enabled: boolean) => set({ auto_bg: enabled, threemfDiskPath: null, downloadUrl: null }),
    setBgTol: (tol: number) => set({ bg_tol: clampValue(tol, 0, 150), threemfDiskPath: null, downloadUrl: null }),
    setQuantizeColors: (colors: number) =>
      set({ quantize_colors: clampValue(colors, 8, 256), threemfDiskPath: null, downloadUrl: null }),
    setEnableCleanup: (enabled: boolean) => set({ enable_cleanup: enabled, threemfDiskPath: null, downloadUrl: null }),
    setSeparateBacking: (enabled: boolean) =>
      set({ separate_backing: enabled }),

    // --- 挂件环 ---
    setAddLoop: (enabled: boolean) => set({ add_loop: enabled, threemfDiskPath: null, downloadUrl: null }),
    setLoopWidth: (width: number) =>
      set({ loop_width: clampValue(width, 2, 10) }),
    setLoopLength: (length: number) =>
      set({ loop_length: clampValue(length, 4, 15) }),
    setLoopHole: (hole: number) =>
      set({ loop_hole: clampValue(hole, 1, 5) }),

    // --- 浮雕（互斥） ---
    setEnableRelief: (enabled: boolean) =>
      set((state) => {
        const updates: Partial<ConverterState> = {
          enable_relief: enabled,
          enable_cloisonne: enabled ? false : state.enable_cloisonne,
          // Relief only supports single-sided structure
          structure_mode: enabled ? StructureModeEnum.SINGLE_SIDED : state.structure_mode,
          threemfDiskPath: null,
          downloadUrl: null,
        };
        // Requirement 6.5: When switching enable_relief from false to true,
        // auto-initialize color_height_map ONLY if it is currently empty
        if (
          enabled &&
          !state.enable_relief &&
          state.palette.length > 0 &&
          Object.keys(state.color_height_map).length === 0
        ) {
          const defaultHeight = state.heightmap_max_height * 0.5;
          const initMap: Record<string, number> = {};
          for (const entry of state.palette) {
            initMap[entry.matched_hex] = defaultHeight;
          }
          updates.color_height_map = initMap;
        }
        return updates;
      }),
    setColorHeightMap: (map: Record<string, number>) =>
      set({ color_height_map: map }),
    setHeightmapMaxHeight: (height: number) => {
      const state = _get();
      const newMax = clampValue(height, 0.08, 15.0);
      const oldMax = state.heightmap_max_height;
      // Proportionally rescale all existing color heights
      if (oldMax > 0 && Object.keys(state.color_height_map).length > 0) {
        const ratio = newMax / oldMax;
        const scaled: Record<string, number> = {};
        for (const [hex, h] of Object.entries(state.color_height_map)) {
          scaled[hex] = clampValue(h * ratio, 0.08, newMax);
        }
        set({ heightmap_max_height: newMax, color_height_map: scaled });
      } else {
        set({ heightmap_max_height: newMax });
      }
    },

    // --- 描边 ---
    setEnableOutline: (enabled: boolean) => set({ enable_outline: enabled, threemfDiskPath: null, downloadUrl: null }),
    setOutlineWidth: (width: number) =>
      set({ outline_width: clampValue(width, 0.5, 10.0) }),

    // --- 掐丝珐琅（互斥） ---
    setEnableCloisonne: (enabled: boolean) =>
      set((state) => ({
        enable_cloisonne: enabled,
        enable_relief: enabled ? false : state.enable_relief,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setWireWidthMm: (width: number) =>
      set({ wire_width_mm: clampValue(width, 0.2, 1.2) }),
    setWireHeightMm: (height: number) =>
      set({ wire_height_mm: clampValue(height, 0.04, 1.0) }),

    // --- 涂层 ---
    setEnableCoating: (enabled: boolean) => set({ enable_coating: enabled, threemfDiskPath: null, downloadUrl: null }),
    setCoatingHeightMm: (height: number) =>
      set({ coating_height_mm: clampValue(height, 0.04, 0.12) }),

    // --- 热床尺寸 ---
    setBedLabel: (label: string) => {
      set({ bed_label: label });
    },

    // --- 调色板与选择 ---
    setSelectedColor: (hex: string | null) => set({ selectedColor: hex }),
    setPalette: (entries: PaletteEntry[]) => set({ palette: entries }),

    // --- 颜色替换（纯前端） ---
    applyColorRemap: (origHex: string, newHex: string) => {
      const state = _get();
      // 推入当前快照到 history
      const snapshot = { ...state.colorRemapMap };
      const newHistory = [...state.remapHistory, snapshot];
      // 更新 map
      const newMap = { ...state.colorRemapMap, [origHex]: newHex };
      set({ colorRemapMap: newMap, remapHistory: newHistory, threemfDiskPath: null, downloadUrl: null });
      // 立即触发后端替换预览
      _get().submitSingleReplace(origHex, newHex);
    },

    undoColorRemap: () => {
      const state = _get();
      if (state.remapHistory.length === 0) return;
      const newHistory = [...state.remapHistory];
      const previousMap = newHistory.pop()!;
      set({ colorRemapMap: previousMap, remapHistory: newHistory, threemfDiskPath: null, downloadUrl: null });
      // 根据撤销后的 map 状态恢复预览
      if (Object.keys(previousMap).length === 0) {
        // map 为空，恢复原始预览
        const originalUrl = _get().originalPreviewUrl;
        if (originalUrl) {
          set({ previewImageUrl: originalUrl });
        }
      } else {
        // map 仍有映射，重新调用后端生成预览
        _get().submitReplacePreview();
      }
    },

    clearAllRemaps: () => {
      const originalUrl = _get().originalPreviewUrl;
      set({
        colorRemapMap: {},
        remapHistory: [],
        threemfDiskPath: null,
        downloadUrl: null,
        ...(originalUrl ? { previewImageUrl: originalUrl } : {}),
      });
    },

    // --- 浮雕高度 ---
    updateColorHeight: (hex: string, heightMm: number) => {
      const state = _get();
      set({
        color_height_map: { ...state.color_height_map, [hex]: heightMm },
      });
    },

    applyAutoHeight: (mode: 'darker-higher' | 'lighter-higher') => {
      const state = _get();
      const heightMap = computeAutoHeightMap(
        state.palette,
        mode,
        state.heightmap_max_height,
      );
      set({ color_height_map: heightMap });
    },

    setAutoHeightMode: (mode: AutoHeightMode) => set({ autoHeightMode: mode }),

    // --- 高度图 ---
    setHeightmapFile: (file: File | null) => set({ heightmapFile: file }),

    uploadHeightmap: async () => {
      const state = _get();
      if (!state.heightmapFile || !state.sessionId) {
        set({ error: "请先上传高度图文件并完成预览" });
        return;
      }
      set({ isLoading: true, error: null });
      try {
        const response = await apiUploadHeightmap(
          state.heightmapFile,
          state.sessionId,
        );
        const thumbnailUrl = `http://localhost:8000${response.thumbnail_url}`;
        set({
          isLoading: false,
          heightmapThumbnailUrl: thumbnailUrl,
          color_height_map: response.color_height_map,
        });
      } catch (err) {
        set({
          isLoading: false,
          error: err instanceof Error ? err.message : "高度图上传失败",
        });
      }
    },

    // --- GLB 预览 ---
    setPreviewGlbUrl: (url: string | null) => set({ previewGlbUrl: url }),

    // --- 模型边界 ---
    setModelBounds: (bounds: ConverterState['modelBounds']) =>
      set({ modelBounds: bounds }),

    fetchBedSizes: async () => {
      set({ bedSizesLoading: true });
      try {
        const response = await apiFetchBedSizes();
        set({ bedSizes: response.beds, bedSizesLoading: false });
      } catch (err) {
        set({
          bedSizesLoading: false,
          error: err instanceof Error ? err.message : "热床尺寸列表加载失败",
        });
      }
    },

    // --- API 操作 ---
    fetchLutList: async () => {
      set({ lutListLoading: true });
      try {
        const response = await apiFetchLutList();
        const luts = response.luts;
        const updates: Partial<ConverterState> = {
          lutList: luts.map((l) => l.name),
          lutListFull: luts,
          lutListLoading: false,
        };

        // If a remembered LUT exists, apply its color_mode
        const remembered = _get().lut_name;
        if (remembered) {
          const info = luts.find((l) => l.name === remembered);
          if (info && info.color_mode) {
            updates.color_mode = info.color_mode as ColorMode;
          } else if (!info) {
            // Remembered LUT no longer exists — clear it
            updates.lut_name = "";
            try { localStorage.removeItem("lumina_lastLut"); } catch { /* noop */ }
          }
        }

        set(updates);
      } catch (err) {
        set({
          lutListLoading: false,
          error: err instanceof Error ? err.message : "LUT 列表加载失败",
        });
      }
    },

    fetchLutColors: async (lutName: string) => {
      if (!lutName) {
        set({ lutColors: [], lutColorsLutName: '' });
        return;
      }
      // 缓存命中检查：LUT 名称未变且已有数据时跳过请求
      if (lutName === _get().lutColorsLutName && _get().lutColors.length > 0) {
        return;
      }
      set({ lutColorsLoading: true });
      try {
        const response = await apiFetchLutColors(lutName);
        set({ lutColors: response.colors, lutColorsLoading: false, lutColorsLutName: lutName });
      } catch (err) {
        set({
          lutColorsLoading: false,
          error: err instanceof Error ? err.message : "LUT 颜色加载失败",
        });
      }
    },

    submitPreview: async () => {
      const state = _get();
      if (!state.imageFile) {
        set({ error: "请先上传图片" });
        return;
      }
      if (!state.lut_name) {
        set({ error: "请先选择 LUT" });
        return;
      }

      // Cancel any in-flight preview request
      if (_previewAbortController) {
        _previewAbortController.abort();
      }
      _previewAbortController = new AbortController();
      const { signal } = _previewAbortController;

      set({ isLoading: true, error: null });
      try {
        const response = await apiConvertPreview(state.imageFile, {
          lut_name: state.lut_name,
          target_width_mm: state.target_width_mm,
          auto_bg: state.auto_bg,
          bg_tol: state.bg_tol,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          quantize_colors: state.quantize_colors,
          enable_cleanup: state.enable_cleanup,
          is_dark: useSettingsStore.getState().theme === 'dark',
        }, signal);
        // 后端返回 JSON，preview_url 是相对路径如 /api/files/xxx
        const previewUrl = `http://localhost:8000${response.preview_url}`;
        const glbUrl = response.preview_glb_url
          ? `http://localhost:8000${response.preview_glb_url}`
          : null;
        // Normalize palette hex values: strip leading '#' for frontend consistency
        const normalizedPalette = (response.palette ?? []).map((e) => ({
          ...e,
          quantized_hex: e.quantized_hex.replace(/^#/, ""),
          matched_hex: e.matched_hex.replace(/^#/, ""),
        }));
        set({
          isLoading: false,
          sessionId: response.session_id,
          previewImageUrl: previewUrl,
          originalPreviewUrl: previewUrl,
          palette: normalizedPalette,
          colorContours: response.contours ?? {},
          previewGlbUrl: glbUrl,
          preview_width_mm: state.target_width_mm,
          preview_height_mm: state.target_height_mm,
          preview_spacer_thick: state.spacer_thick,
        });
      } catch (err) {
        // Ignore aborted requests (user started a new preview)
        if (err instanceof Error && err.name === "CanceledError") {
          return;
        }
        set({
          isLoading: false,
          error: err instanceof Error ? err.message : "预览失败",
        });
      }
    },

    submitGenerate: async () => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return null;
      }
      // Requirement 10.4: enable_relief 为 true 且 color_height_map 为空时阻止生成
      if (state.enable_relief && Object.keys(state.color_height_map).length === 0) {
        // Requirement 10.3: 高度图模式时给出更具体的提示
        if (state.autoHeightMode === 'use-heightmap') {
          set({ error: "请先上传高度图并获取高度映射后再生成" });
        } else {
          set({ error: "请先设置颜色高度映射后再生成" });
        }
        return null;
      }

      set({ isLoading: true, error: null });
      try {
        // 合并 colorRemapMap 转换的 replacement_regions 与已有的 replacement_regions
        let mergedReplacements: ColorReplacementItem[] | undefined =
          state.replacement_regions.length > 0
            ? [...state.replacement_regions]
            : undefined;

        if (Object.keys(state.colorRemapMap).length > 0) {
          const remapRegions = colorRemapToReplacementRegions(
            state.colorRemapMap,
            state.palette,
          );
          mergedReplacements = [
            ...(mergedReplacements ?? []),
            ...remapRegions,
          ];
        }

        const response = await apiConvertGenerate(state.sessionId, {
          lut_name: state.lut_name,
          target_width_mm: state.target_width_mm,
          auto_bg: state.auto_bg,
          bg_tol: state.bg_tol,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          quantize_colors: state.quantize_colors,
          enable_cleanup: state.enable_cleanup,
          spacer_thick: state.spacer_thick,
          structure_mode: state.structure_mode,
          separate_backing: state.separate_backing,
          add_loop: state.add_loop,
          loop_width: state.loop_width,
          loop_length: state.loop_length,
          loop_hole: state.loop_hole,
          enable_relief: state.enable_relief,
          height_mode: state.enable_relief
            ? (state.autoHeightMode === 'use-heightmap' ? 'heightmap' : 'color')
            : undefined,
          color_height_map: state.enable_relief ? state.color_height_map : undefined,
          heightmap_max_height: state.heightmap_max_height,
          enable_outline: state.enable_outline,
          outline_width: state.outline_width,
          enable_cloisonne: state.enable_cloisonne,
          wire_width_mm: state.wire_width_mm,
          wire_height_mm: state.wire_height_mm,
          enable_coating: state.enable_coating,
          coating_height_mm: state.coating_height_mm,
          replacement_regions:
            mergedReplacements && mergedReplacements.length > 0
              ? mergedReplacements
              : undefined,
          free_color_set:
            state.free_color_set.size > 0
              ? Array.from(state.free_color_set)
              : undefined,
        });
        // 后端返回 download_url 和可选的 preview_3d_url
        // preview_3d_url 指向 GLB 文件（Three.js 可加载）
        // download_url 指向 3MF 文件（ZIP 格式，Three.js 无法加载）
        const modelUrl = response.preview_3d_url
          ? `http://localhost:8000${response.preview_3d_url}`
          : null;
        set({
          isLoading: false,
          modelUrl,
          threemfDiskPath: response.threemf_disk_path ?? null,
          downloadUrl: response.download_url
            ? `http://localhost:8000${response.download_url}`
            : null,
        });
        return modelUrl;
      } catch (err) {
        set({
          isLoading: false,
          error: err instanceof Error ? err.message : "生成失败",
        });
        return null;
      }
    },

    // --- 裁剪 ---
    setEnableCrop: (enabled: boolean) => {
      set({ enableCrop: enabled });
      try {
        localStorage.setItem("lumina_enableCrop", String(enabled));
      } catch {
        // localStorage unavailable, ignore
      }
    },

    setCropModalOpen: (open: boolean) => set({ cropModalOpen: open }),

    submitCrop: async (x: number, y: number, width: number, height: number) => {
      const state = _get();
      if (!state.imageFile) {
        set({ error: "No image file to crop" });
        return;
      }
      set({ isCropping: true, error: null });
      try {
        const response = await apiCropImage(state.imageFile, x, y, width, height);
        const croppedFullUrl = `http://localhost:8000${response.cropped_url}`;

        // Fetch cropped image as Blob to create a new File
        const blob = await fetch(croppedFullUrl).then((r) => r.blob());
        const croppedFile = new File([blob], state.imageFile.name, {
          type: blob.type || state.imageFile.type,
        });

        // Revoke previous preview URL
        const prev = _get().imagePreviewUrl;
        if (prev) {
          URL.revokeObjectURL(prev);
        }

        const newPreviewUrl = URL.createObjectURL(croppedFile);

        // Update aspect ratio from cropped dimensions
        const ratio = response.width / response.height;

        set({
          imageFile: croppedFile,
          imagePreviewUrl: newPreviewUrl,
          aspectRatio: ratio,
          cropModalOpen: false,
          isCropping: false,
        });
      } catch (err) {
        set({
          isCropping: false,
          error: err instanceof Error ? err.message : "Crop failed",
        });
      }
    },

    // --- 批量模式 ---
    setBatchMode: (enabled: boolean) => {
      if (enabled) {
        set({ batchMode: true });
      } else {
        set({ batchMode: false, batchFiles: [], batchResult: null });
      }
    },

    addBatchFiles: (files: File[]) => {
      const valid = files.filter((f) => isValidImageType(f.type));
      if (valid.length === 0) return;
      set((state) => ({ batchFiles: [...state.batchFiles, ...valid] }));
    },

    removeBatchFile: (index: number) => {
      set((state) => ({
        batchFiles: state.batchFiles.filter((_, i) => i !== index),
      }));
    },

    clearBatchFiles: () => set({ batchFiles: [] }),

    submitBatch: async () => {
      const state = _get();
      set({ batchLoading: true, batchResult: null, error: null });
      try {
        const params = {
          lut_name: state.lut_name,
          target_width_mm: state.target_width_mm,
          spacer_thick: state.spacer_thick,
          structure_mode: state.structure_mode,
          auto_bg: state.auto_bg,
          bg_tol: state.bg_tol,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          quantize_colors: state.quantize_colors,
          enable_cleanup: state.enable_cleanup,
        };
        const result = await apiConvertBatch(state.batchFiles, params);
        set({ batchResult: result, batchLoading: false });
      } catch (err) {
        set({
          batchLoading: false,
          error: err instanceof Error ? err.message : "批量处理失败",
        });
      }
    },

    // --- 颜色替换：单次即时替换 ---
    submitSingleReplace: async (origHex: string, newHex: string) => {
      const state = _get();
      if (!state.sessionId) return;
      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiReplaceColor(
          state.sessionId,
          `#${origHex}`,
          `#${newHex}`,
        );
        set({
          replacePreviewLoading: false,
          previewImageUrl: `http://localhost:8000${response.preview_url}`,
        });
      } catch (err) {
        // 回滚 colorRemapMap 到操作前状态
        const currentHistory = _get().remapHistory;
        if (currentHistory.length > 0) {
          const previousMap = currentHistory[currentHistory.length - 1];
          set({
            colorRemapMap: previousMap,
            remapHistory: currentHistory.slice(0, -1),
            replacePreviewLoading: false,
            error: err instanceof Error ? err.message : '颜色替换失败',
          });
        } else {
          set({
            replacePreviewLoading: false,
            error: err instanceof Error ? err.message : '颜色替换失败',
          });
        }
      }
    },

    // --- 颜色替换预览 ---
    submitReplacePreview: async () => {
      const state = _get();
      const entries = Object.entries(state.colorRemapMap);
      if (entries.length === 0 || !state.sessionId) return;

      set({ replacePreviewLoading: true, error: null });
      try {
        let lastPreviewUrl = state.previewImageUrl;
        for (const [origHex, newHex] of entries) {
          // 查找 palette 中对应的 matched_hex 作为 selected_color
          const paletteEntry = state.palette.find(
            (p) => p.matched_hex === origHex,
          );
          const selectedColor = `#${paletteEntry ? paletteEntry.matched_hex : origHex}`;
          const replacementColor = `#${newHex}`;

          const response = await apiReplaceColor(
            state.sessionId,
            selectedColor,
            replacementColor,
          );
          lastPreviewUrl = `http://localhost:8000${response.preview_url}`;
        }
        set({
          replacePreviewLoading: false,
          previewImageUrl: lastPreviewUrl,
        });
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "颜色替换预览失败",
        });
      }
    },

    // --- 完整流水线（preview → generate） ---
    submitFullPipeline: async () => {
      const state = _get();

      // 步骤 1：如果没有 sessionId，先执行预览
      if (!state.sessionId) {
        await _get().submitPreview();
        // 检查预览是否成功
        const afterPreview = _get();
        if (!afterPreview.sessionId) {
          return null; // 预览失败，错误已由 submitPreview 设置
        }
      }

      // 步骤 2：执行生成
      return await _get().submitGenerate();
    },

    // --- UI 状态 ---
    setError: (error: string | null) => set({ error }),
    clearError: () => set({ error: null }),
  })
);
