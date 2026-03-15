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
  detectRegion as apiDetectRegion,
  regionReplace as apiRegionReplace,
  resetReplacements as apiResetReplacements,
} from "../api/converter";
import type { LutColorEntry, LutInfo } from "../api/types";
import {
  computeAutoHeightMap,
  colorRemapToReplacementRegions,
} from "../utils/colorUtils";
import { useSettingsStore } from "./settingsStore";

// ========== Selection Mode Types ==========

export type SelectionMode = 'select-all' | 'current' | 'multi-select' | 'region';

export interface RegionData {
  regionId: string;
  colorHex: string;
  pixelCount: number;
  previewUrl: string;
  contours?: number[][][] | null;
}

// ========== Pending Replacement Types ==========

export interface PendingReplacement {
  sourceHex: string;      // 原色 hex（不带 #）
  targetHex: string;      // 目标色 hex（不带 #）
  mode: SelectionMode;    // 触发时的选择模式
  sourceColors?: string[]; // multi-select 模式下的多个源色
}

// ========== Helpers ==========

export function clampValue(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

const VALID_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/svg+xml",
  "image/webp",
  "image/heic",
  "image/heif",
]);

export const ACCEPT_IMAGE_FORMATS = Array.from(VALID_IMAGE_TYPES).join(",");

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
  hue_enable: boolean;
  chroma_gate: number;
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
  preview_width_mm: number | null; // 预览时的原始宽度
  preview_height_mm: number | null; // 预览时的原始高度
  preview_spacer_thick: number | null; // 预览时的原始厚度
  previewPixelWidth: number | null;  // 预览图像像素宽度（用于 3D→像素坐标转换）
  previewPixelHeight: number | null; // 预览图像像素高度（用于 3D→像素坐标转换）

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

  // 分层预览
  layerImages: { layer_index: number; name: string; url: string }[];
  layerImagesLoading: boolean;
  layerImagesOpen: boolean;

  // 颜色选择模式
  selectionMode: SelectionMode;
  selectedColors: Set<string>;
  regionData: RegionData | null;

  // 待确认颜色替换
  pendingReplacement: PendingReplacement | null;

  // 区域替换计数（current 模式不走 colorRemapMap，需要独立计数以启用清除按钮）
  regionReplacementCount: number;
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
  setHueEnable: (enabled: boolean) => void;
  setChromaGate: (gate: number) => void;
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

  // 颜色选择模式
  setSelectionMode: (mode: SelectionMode) => void;
  toggleColorInSelection: (hex: string) => void;
  applyBatchColorRemap: (newHex: string) => Promise<void>;
  detectRegion: (x: number, y: number) => Promise<void>;
  applyRegionReplace: (newHex: string) => Promise<void>;

  // 待确认颜色替换
  setPendingReplacement: (pending: PendingReplacement | null) => void;
  confirmReplacement: () => Promise<void>;

  // 颜色替换（纯前端）
  applyColorRemap: (origHex: string, newHex: string) => void;
  undoColorRemap: () => void;
  clearAllRemaps: () => void;

  // 浮雕高度
  updateColorHeight: (hex: string, heightMm: number) => void;
  applyAutoHeight: (mode: "darker-higher" | "lighter-higher") => void;
  setAutoHeightMode: (mode: AutoHeightMode) => void;

  // 高度图
  setHeightmapFile: (file: File | null) => void;
  uploadHeightmap: () => Promise<void>;

  // GLB 预览
  setPreviewGlbUrl: (url: string | null) => void;

  // 模型边界
  setModelBounds: (bounds: ConverterState["modelBounds"]) => void;

  // API 操作
  fetchLutList: () => Promise<void>;
  fetchLutColors: (lutName: string) => Promise<void>;
  submitPreview: () => Promise<void>;
  submitGenerate: () => Promise<string | null>;

  // 裁剪
  setEnableCrop: (enabled: boolean) => void;
  setCropModalOpen: (open: boolean) => void;
  submitCrop: (
    x: number,
    y: number,
    width: number,
    height: number,
  ) => Promise<void>;

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

  // 自由色
  toggleFreeColor: (hex: string) => void;
  clearFreeColors: () => void;

  // UI 状态
  setError: (error: string | null) => void;
  clearError: () => void;

  // 分层预览
  fetchLayerImages: () => Promise<void>;
  setLayerImagesOpen: (open: boolean) => void;
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
  hue_enable: false,
  chroma_gate: 15,
  separate_backing: false,
  add_loop: false,
  loop_width: 4.0,
  loop_length: 8.0,
  loop_hole: 2.5,
  enable_relief: false,
  color_height_map: {},
  heightmap_max_height: 3.0,
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
  autoHeightMode: "darker-higher" as AutoHeightMode,
  heightmapFile: null,
  heightmapThumbnailUrl: null,
  previewGlbUrl: null,
  preview_width_mm: null,
  preview_height_mm: null,
  preview_spacer_thick: null,
  previewPixelWidth: null,
  previewPixelHeight: null,
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
  lutColorsLutName: "",
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
  layerImages: [],
  layerImagesLoading: false,
  layerImagesOpen: false,
  selectionMode: 'current' as SelectionMode,
  selectedColors: new Set<string>(),
  regionData: null,
  pendingReplacement: null,
  regionReplacementCount: 0,
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
      try {
        localStorage.setItem("lumina_lastLut", name);
      } catch {
        /* noop */
      }
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
              400,
            ),
            threemfDiskPath: null,
            downloadUrl: null,
          };
        }
        return {
          target_width_mm: clamped,
          threemfDiskPath: null,
          downloadUrl: null,
        };
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
              400,
            ),
          };
        }
        return { target_height_mm: clamped };
      }),

    setSpacerThick: (thick: number) =>
      set({
        spacer_thick: clampValue(thick, 0.2, 3.5),
        threemfDiskPath: null,
        downloadUrl: null,
      }),

    setStructureMode: (mode: StructureMode) =>
      set({ structure_mode: mode, threemfDiskPath: null, downloadUrl: null }),
    setColorMode: (mode: ColorMode) =>
      set({ color_mode: mode, threemfDiskPath: null, downloadUrl: null }),
    setModelingMode: (mode: ModelingMode) =>
      set({ modeling_mode: mode, threemfDiskPath: null, downloadUrl: null }),

    // --- 高级设置 ---
    setAutoBg: (enabled: boolean) =>
      set({ auto_bg: enabled, threemfDiskPath: null, downloadUrl: null }),
    setBgTol: (tol: number) =>
      set({
        bg_tol: clampValue(tol, 0, 150),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setQuantizeColors: (colors: number) =>
      set({
        quantize_colors: clampValue(colors, 8, 256),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setEnableCleanup: (enabled: boolean) =>
      set({
        enable_cleanup: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setHueEnable: (enabled: boolean) =>
      set({
        hue_enable: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setChromaGate: (gate: number) =>
      set({
        chroma_gate: clampValue(gate, 0, 50),
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setSeparateBacking: (enabled: boolean) =>
      set({ separate_backing: enabled }),

    // --- 挂件环 ---
    setAddLoop: (enabled: boolean) =>
      set({ add_loop: enabled, threemfDiskPath: null, downloadUrl: null }),
    setLoopWidth: (width: number) =>
      set({ loop_width: clampValue(width, 2, 10) }),
    setLoopLength: (length: number) =>
      set({ loop_length: clampValue(length, 4, 15) }),
    setLoopHole: (hole: number) => set({ loop_hole: clampValue(hole, 1, 5) }),

    // --- 浮雕（互斥） ---
    setEnableRelief: (enabled: boolean) => {
      set((state) => {
        const updates: Partial<ConverterState> = {
          enable_relief: enabled,
          enable_cloisonne: enabled ? false : state.enable_cloisonne,
          // Relief only supports single-sided structure
          structure_mode: enabled
            ? StructureModeEnum.SINGLE_SIDED
            : state.structure_mode,
          threemfDiskPath: null,
          downloadUrl: null,
        };
        // Requirement 6.5: When switching enable_relief from false to true,
        // auto-initialize color_height_map ONLY if it is currently empty.
        // Use computeAutoHeightMap to assign different heights based on
        // luminance, so the relief effect is visible immediately.
        if (
          enabled &&
          !state.enable_relief &&
          state.palette.length > 0 &&
          Object.keys(state.color_height_map).length === 0
        ) {
          const mode = state.autoHeightMode === "use-heightmap"
            ? "darker-higher"
            : (state.autoHeightMode as "darker-higher" | "lighter-higher");
          updates.color_height_map = computeAutoHeightMap(
            state.palette,
            mode,
            state.heightmap_max_height,
          );
        }
        return updates;
      });
    },
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
    setEnableOutline: (enabled: boolean) =>
      set({
        enable_outline: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
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
    setEnableCoating: (enabled: boolean) =>
      set({
        enable_coating: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }),
    setCoatingHeightMm: (height: number) =>
      set({ coating_height_mm: clampValue(height, 0.04, 0.12) }),

    // --- 热床尺寸 ---
    setBedLabel: (label: string) => {
      set({ bed_label: label });
    },

    // --- 调色板与选择 ---
    setSelectedColor: (hex: string | null) => set({ selectedColor: hex }),
    setPalette: (entries: PaletteEntry[]) => set({ palette: entries }),

    // --- 颜色选择模式 ---
    // current: 单区域替换（3D 预览点击 → region-detect → 只替换该连通区域）
    // select-all: 全局单色替换（选一个颜色 → 全图该颜色都替换）
    // multi-select: 多选批量替换（选多个颜色 → 批量替换）
    // region: 保留的局部区域模式
    setSelectionMode: (mode: SelectionMode) => {
      switch (mode) {
        case 'current':
          // 当前模式 = 单区域替换，清空多选，清空 selectedColor，准备 region-detect
          set({
            selectionMode: mode,
            selectedColors: new Set<string>(),
            selectedColor: null,
            regionData: null,
          });
          break;
        case 'select-all':
          // 全选模式 = 全局单色替换，清空多选，保留 selectedColor 用于全局替换
          set({ selectionMode: mode, selectedColors: new Set<string>() });
          break;
        case 'multi-select':
          // 多选模式 = 可复选多个颜色，清空多选集合等待用户逐个选择
          set({ selectionMode: mode, selectedColors: new Set<string>() });
          break;
        case 'region':
          set({
            selectionMode: mode,
            selectedColors: new Set<string>(),
            selectedColor: null,
            regionData: null,
          });
          break;
      }
    },

    // --- 多选模式颜色切换 ---
    toggleColorInSelection: (hex: string) => {
      set((state) => {
        const next = new Set(state.selectedColors);
        if (next.has(hex)) {
          next.delete(hex);
        } else {
          next.add(hex);
        }
        return { selectedColors: next };
      });
    },

    // --- 批量颜色替换 ---
    applyBatchColorRemap: async (newHex: string) => {
      const state = _get();
      const colors = Array.from(state.selectedColors);
      if (colors.length === 0) return;

      // 1. 快照当前 colorRemapMap，作为单条记录推入 remapHistory
      const snapshot = { ...state.colorRemapMap };
      const newHistory = [...state.remapHistory, snapshot];

      // 2. 批量更新 colorRemapMap
      const newMap = { ...state.colorRemapMap };
      for (const hex of colors) {
        newMap[hex] = newHex;
      }
      set({
        colorRemapMap: newMap,
        remapHistory: newHistory,
        replacePreviewLoading: true,
        threemfDiskPath: null,
        downloadUrl: null,
      });

      // 3. 依次调用后端替换
      try {
        for (const hex of colors) {
          await _get().submitSingleReplace(hex, newHex);
        }
        set({ replacePreviewLoading: false });
      } catch {
        // 回滚整个批量操作
        set({
          colorRemapMap: snapshot,
          remapHistory: state.remapHistory,
          replacePreviewLoading: false,
          error: "批量颜色替换失败",
        });
      }
    },

    // --- 连通区域检测 ---
    detectRegion: async (x: number, y: number) => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return;
      }
      try {
        const response = await apiDetectRegion(state.sessionId, x, y);
        set({
          regionData: {
            regionId: response.region_id,
            colorHex: response.color_hex,
            pixelCount: response.pixel_count,
            previewUrl: response.preview_url,
            contours: response.contours ?? null,
          },
          selectedColor: response.color_hex.replace(/^#/, ''),
          previewImageUrl: `http://localhost:8000${response.preview_url}`,
        });
      } catch (err) {
        set({
          error: err instanceof Error ? err.message : "连通区域检测失败",
        });
      }
    },

    // --- 连通区域替换 ---
    applyRegionReplace: async (newHex: string) => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return;
      }
      if (!state.regionData) {
        set({ error: "请先选择一个连通区域" });
        return;
      }
      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiRegionReplace(state.sessionId, `#${newHex}`);
        const updates: Partial<ConverterState> = {
          previewImageUrl: `http://localhost:8000${response.preview_url}`,
          regionData: null,
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
        };

        // 更新 3D 预览 GLB URL（仅当后端返回非空 URL 时）
        if (response.preview_glb_url) {
          updates.previewGlbUrl = `http://localhost:8000${response.preview_glb_url}`;
        }
        // preview_glb_url 为 null 时不清除现有 previewGlbUrl

        // 更新颜色轮廓数据（仅当后端返回非空数据时）
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }

        // 不递增 regionReplacementCount（已在 confirmReplacement 中处理）
        set(updates);
      } catch (err) {
        set({
          replacePreviewLoading: false,
          error: err instanceof Error ? err.message : "区域颜色替换失败",
        });
      }
    },

    // --- 待确认颜色替换 ---
    setPendingReplacement: (pending: PendingReplacement | null) => {
      set({ pendingReplacement: pending });
    },

    confirmReplacement: async () => {
      const state = _get();
      const pending = state.pendingReplacement;
      if (!pending) return;

      // 清除 pending 状态
      set({ pendingReplacement: null });

      switch (pending.mode) {
        case 'select-all':
          // 乐观更新 colorRemapMap → 3D 预览即时响应
          _get().applyColorRemap(pending.sourceHex, pending.targetHex);
          break;
        case 'multi-select': {
          // 使用 pending 中保存的 sourceColors，而非 state.selectedColors
          const colors = pending.sourceColors ?? [];
          if (colors.length === 0) break;
          const curState = _get();
          const snapshot = { ...curState.colorRemapMap };
          const newHistory = [...curState.remapHistory, snapshot];
          const newMap = { ...curState.colorRemapMap };
          for (const hex of colors) {
            newMap[hex] = pending.targetHex;
          }
          set({
            colorRemapMap: newMap,
            remapHistory: newHistory,
            replacePreviewLoading: true,
            threemfDiskPath: null,
            downloadUrl: null,
          });
          try {
            for (const hex of colors) {
              await _get().submitSingleReplace(hex, pending.targetHex);
            }
            set({ replacePreviewLoading: false });
          } catch {
            set({
              colorRemapMap: snapshot,
              remapHistory: curState.remapHistory,
              replacePreviewLoading: false,
              error: "批量颜色替换失败",
            });
          }
          break;
        }
        case 'current':
        case 'region': {
          // 不更新 colorRemapMap（避免 3D 预览全局变色）
          // 仅递增 regionReplacementCount 并调用后端区域替换
          const curState = _get();
          set({
            regionReplacementCount: curState.regionReplacementCount + 1,
          });
          // 调用后端 region-replace → 2D 预览精确区域替换
          if (curState.regionData) {
            await _get().applyRegionReplace(pending.targetHex);
          }
          break;
        }
      }
    },

    // --- 颜色替换（纯前端） ---
    applyColorRemap: (origHex: string, newHex: string) => {
      const state = _get();
      // 推入当前快照到 history
      const snapshot = { ...state.colorRemapMap };
      const newHistory = [...state.remapHistory, snapshot];
      // 更新 map
      const newMap = { ...state.colorRemapMap, [origHex]: newHex };
      set({
        colorRemapMap: newMap,
        remapHistory: newHistory,
        threemfDiskPath: null,
        downloadUrl: null,
      });
      // 立即触发后端替换预览
      _get().submitSingleReplace(origHex, newHex);
    },

    undoColorRemap: () => {
      const state = _get();
      if (state.remapHistory.length === 0) return;
      const newHistory = [...state.remapHistory];
      const previousMap = newHistory.pop()!;
      set({
        colorRemapMap: previousMap,
        remapHistory: newHistory,
        threemfDiskPath: null,
        downloadUrl: null,
      });
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
      const state = _get();
      set({
        colorRemapMap: {},
        remapHistory: [],
        threemfDiskPath: null,
        downloadUrl: null,
        regionData: null,
        regionReplacementCount: 0,
      });
      // 调用后端清空 replacement_regions 并从原始 matched_rgb 重新生成预览和 GLB
      // 不能依赖 originalPreviewUrl，因为 region-replace 会修改后端缓存的 matched_rgb
      if (state.sessionId) {
        apiResetReplacements(state.sessionId)
          .then((res) => {
            const url = `http://localhost:8000${res.preview_url}`;
            const updates: Partial<ConverterState> = {
              previewImageUrl: url,
              originalPreviewUrl: url,
            };
            // 后端 reset-replacements 现在也会重新生成 GLB
            if (res.preview_glb_url) {
              updates.previewGlbUrl = `http://localhost:8000${res.preview_glb_url}`;
            }
            set(updates);
          })
          .catch(() => {
            // 后端清空失败时回退到 originalPreviewUrl
            const fallback = _get().originalPreviewUrl;
            if (fallback) {
              set({ previewImageUrl: fallback });
            }
          });
      } else {
        // 无 session 时直接回退到 originalPreviewUrl
        const originalUrl = state.originalPreviewUrl;
        if (originalUrl) {
          set({ previewImageUrl: originalUrl });
        }
      }
    },

    // --- 浮雕高度 ---
    updateColorHeight: (hex: string, heightMm: number) => {
      set((state) => ({
        color_height_map: { ...state.color_height_map, [hex]: heightMm },
      }));
    },

    applyAutoHeight: (mode: "darker-higher" | "lighter-higher") => {
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
    setModelBounds: (bounds: ConverterState["modelBounds"]) =>
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
            try {
              localStorage.removeItem("lumina_lastLut");
            } catch {
              /* noop */
            }
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
        set({ lutColors: [], lutColorsLutName: "" });
        return;
      }
      // 缓存命中检查：LUT 名称未变且已有数据时跳过请求
      if (lutName === _get().lutColorsLutName && _get().lutColors.length > 0) {
        return;
      }
      set({ lutColorsLoading: true });
      try {
        const response = await apiFetchLutColors(lutName);
        set({
          lutColors: response.colors,
          lutColorsLoading: false,
          lutColorsLutName: lutName,
        });
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
        const response = await apiConvertPreview(
          state.imageFile,
          {
            lut_name: state.lut_name,
            target_width_mm: state.target_width_mm,
            auto_bg: state.auto_bg,
            bg_tol: state.bg_tol,
            color_mode: state.color_mode,
            modeling_mode: state.modeling_mode,
            quantize_colors: state.quantize_colors,
            enable_cleanup: state.enable_cleanup,
            hue_weight: state.hue_enable ? 0.5 : 0.0,
            chroma_gate: state.hue_enable ? state.chroma_gate : 0,
            is_dark: useSettingsStore.getState().theme === "dark",
          },
          signal,
        );
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
          previewPixelWidth: response.dimensions?.width ?? null,
          previewPixelHeight: response.dimensions?.height ?? null,
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
      if (
        state.enable_relief &&
        Object.keys(state.color_height_map).length === 0
      ) {
        // Requirement 10.3: 高度图模式时给出更具体的提示
        if (state.autoHeightMode === "use-heightmap") {
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
          mergedReplacements = [...(mergedReplacements ?? []), ...remapRegions];
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
          hue_weight: state.hue_enable ? 0.5 : 0.0,
          chroma_gate: state.hue_enable ? state.chroma_gate : 0,
          spacer_thick: state.spacer_thick,
          structure_mode: state.structure_mode,
          separate_backing: state.separate_backing,
          add_loop: state.add_loop,
          loop_width: state.loop_width,
          loop_length: state.loop_length,
          loop_hole: state.loop_hole,
          enable_relief: state.enable_relief,
          height_mode: state.enable_relief
            ? state.autoHeightMode === "use-heightmap"
              ? "heightmap"
              : "color"
            : undefined,
          color_height_map: state.enable_relief
            ? state.color_height_map
            : undefined,
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
              ? Array.from(state.free_color_set).map(h => `#${h}`)
              : undefined,
          use_cached_matched_rgb: state.regionReplacementCount > 0,
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
        const response = await apiCropImage(
          state.imageFile,
          x,
          y,
          width,
          height,
        );
        const croppedFullUrl = `http://localhost:8000${response.cropped_url}`;

        // Fetch cropped image as Blob to create a new File
        const blob = await fetch(croppedFullUrl).then((r) => r.blob());
        const croppedFile = new File([blob], state.imageFile.name, {
          type: "image/png",
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
          hue_weight: state.hue_enable ? 0.5 : 0.0,
          chroma_gate: state.hue_enable ? state.chroma_gate : 0,
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
            error: err instanceof Error ? err.message : "颜色替换失败",
          });
        } else {
          set({
            replacePreviewLoading: false,
            error: err instanceof Error ? err.message : "颜色替换失败",
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

    // --- 自由色 ---
    toggleFreeColor: (hex: string) => {
      set((state) => {
        const next = new Set(state.free_color_set);
        if (next.has(hex)) {
          next.delete(hex);
        } else {
          next.add(hex);
        }
        return { free_color_set: next, threemfDiskPath: null, downloadUrl: null };
      });
    },

    clearFreeColors: () => {
      set({ free_color_set: new Set(), threemfDiskPath: null, downloadUrl: null });
    },

    // --- UI 状态 ---
    setError: (error: string | null) => set({ error }),
    clearError: () => set({ error: null }),

    // --- 分层预览 ---
    fetchLayerImages: async () => {
      const { sessionId } = _get();
      if (!sessionId) return;
      set({ layerImagesLoading: true });
      try {
        const { fetchLayerImages: apiFetch } = await import("../api/converter");
        const res = await apiFetch(sessionId);
        set({ layerImages: res.layers, layerImagesLoading: false, layerImagesOpen: true });
      } catch (e) {
        console.error("fetchLayerImages failed:", e);
        set({ layerImagesLoading: false });
      }
    },
    setLayerImagesOpen: (open: boolean) => set({ layerImagesOpen: open }),
  }),
);
