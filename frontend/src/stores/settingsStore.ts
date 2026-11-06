import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  deleteCustom3mfTemplate,
  importCustom3mfTemplate,
  saveSettings,
  type Custom3mfTemplate,
} from "../api/system";
import type { UserSettings } from "../api/types";
import { normalizeConversionPreferences, type ConversionPreferences } from "./conversionPreferences";
import {
  invalidateGeneratedArtifacts,
  invalidatePreviewArtifacts,
  invalidateSingleItemDownload,
} from "./generatedArtifactInvalidation";
import { synchronizePrinterBedLabel } from "./printerBedLabelSync";

// ========== State Interface ==========

/**
 * User-facing grid-resolution tiers for the material-solver exhaustive
 * cache. The numeric value equals the Lab bucket count per axis and must
 * stay in sync with ``ALLOWED_GRID_RESOLUTIONS`` on the backend.
 *
 * The ladder doubles per step. The build path is sparse, so peak build
 * memory tracks the number of physically reachable recipes (~materials^
 * layers) rather than the cube of the tier — even Ultra+ stays light.
 * Higher tiers mainly reduce bucket-collision loss (more distinct
 * recipes survive into the cache); per-lookup cost scales mildly.
 *
 * 穷举数量的用户档位；数值等于 Lab 网格每轴桶数，必须与后端
 * ``ALLOWED_GRID_RESOLUTIONS`` 保持一致。每档边长翻倍，但构建采用稀疏
 * 存储，峰值内存只随实际可达配方数（~材料^层数）增长，与档位无关——
 * 极致+ 档也很轻。更高档主要减少桶碰撞损失（更多配方被保留进缓存）；
 * 单次查找时间随档位略增。
 */
export type SolverCacheGridResolution =
  | 64
  | 128
  | 256
  | 512
  | 1024
  | 2048;

export const SOLVER_CACHE_GRID_RESOLUTIONS: readonly SolverCacheGridResolution[] =
  [64, 128, 256, 512, 1024, 2048] as const;

export const SVG_PIXELS_PER_MM_DEFAULT = 10.0;
export const SVG_PIXELS_PER_MM_MIN = 2.0;
export const SVG_PIXELS_PER_MM_MAX = 50.0;
export const SVG_PIXELS_PER_MM_STEP = 0.1;
export const MATERIAL_DELTA_E00_TOLERANCE_DEFAULT = 0.5;
export const MATERIAL_DELTA_E00_TOLERANCE_MIN = 0.0;
export const MATERIAL_DELTA_E00_TOLERANCE_MAX = 5.0;
export const MATERIAL_DELTA_E00_TOLERANCE_STEP = 0.1;

export type NozzleSize = "0.2" | "0.25" | "0.4";

const NOZZLE_SIZES: readonly NozzleSize[] = ["0.2", "0.25", "0.4"];

function isNozzleSize(value: unknown): value is NozzleSize {
  return typeof value === "string" && NOZZLE_SIZES.includes(value as NozzleSize);
}

/** Horizontal alignment of the primary and secondary navigation rows. */
export type HeaderNavAlignment = "center" | "left";

export const HEADER_NAV_ALIGNMENTS: readonly HeaderNavAlignment[] = [
  "center",
  "left",
];

export function isHeaderNavAlignment(
  value: unknown,
): value is HeaderNavAlignment {
  return (
    typeof value === "string" &&
    HEADER_NAV_ALIGNMENTS.includes(value as HeaderNavAlignment)
  );
}

export interface SettingsState {
  conversionPreferences: ConversionPreferences;
  language: "zh" | "en";
  theme: "light" | "dark";
  lastLutName: string;
  lastColorMode: string;
  lastModelingMode: string;
  lastBedLabel: string;
  cropEnabled: boolean;
  lastSlicerId: string;
  enableBlur: boolean;
  enableFancyLoading: boolean;
  enableWittyLoading: boolean;
  enableCompletionNotifications: boolean;
  /**
   * Prefer analytic native-SVG browser geometry. This affects only the
   * lightweight 3D preview; exact 3MF generation never consumes it.
   */
  enableSmoothVectorPreview: boolean;
  preserveUploadFilenameFor3mf: boolean;
  paletteMode: "swatch" | "card";
  printerModel: string;
  slicerSoftware: string;
  deviceProfileId: string;
  buildPlateId: string;
  custom3mfTemplateId: string | null;
  buildPlateSelections: Record<string, string>;
  customSlicerPath: string;
  customSlicerId: string;
  nozzleSize: NozzleSize;
  enableBaseLayerHeightModifier: boolean;
  enableWipeTowerAutoPlacement: boolean;
  /**
   * When ``false`` (default) the exhaustive-cache dialog hides its
   * density selector and builds always use the low-tier default on the
   * backend. Flipping to ``true`` reveals the dropdown, but does *not*
   * change the current value of ``solverCacheGridResolution``.
   */
  enableSolverCacheGridSelection: boolean;
  /**
   * Currently-selected grid resolution. Only consumed by the build flow
   * when ``enableSolverCacheGridSelection`` is true; otherwise callers
   * must fall through to the backend default (64).
   */
  solverCacheGridResolution: SolverCacheGridResolution;
  /**
   * High-fidelity SVG raster density in pixels per millimeter. This only
   * affects SVG files processed through High-Fidelity mode; native Vector
   * mode bypasses rasterization and ignores this value.
   */
  svgPixelsPerMm: number;
  /**
   * Maximum accepted Delta-E00 loss when choosing a shorter dynamic material
   * recipe. 动态材料配方选择更短层数时允许的最大 Delta-E00 损失。
   */
  materialDeltaE00Tolerance: number;
  /**
   * Advanced: when true, successful previews automatically collapse every
   * gradient-banding group to its representative colour (the material with
   * the highest pixel count). Off by default so first-time users see the
   * raw banded preview and opt into the fix from the color workstation.
   * 高级设置：开启后，每次预览成功会自动把每个渐变海带纹分组统一替换为组
   * 内代表色（像素最多的那一个），一键去掉海带纹；默认关闭。
   */
  autoReplaceGradientBanding: boolean;
  /**
   * Desktop only: folder the save dialog for generated files opens in.
   * Empty means the operating-system default location.
   * 仅桌面版：生成文件保存对话框默认打开的文件夹；空字符串表示系统默认位置。
   */
  generatedFileDirectory: string;
  /**
   * Centered keeps both navigation rows on the window axis; left places the
   * primary tabs after the brand and aligns the sub tabs with them.
   * 居中时两行导航都以窗口中线对齐；居左时主导航紧跟标题，子导航与主导航左对齐。
   */
  headerNavAlignment: HeaderNavAlignment;
}

// ========== Actions Interface ==========

export interface SettingsActions {
  setConversionPreferences: (preferences: ConversionPreferences) => void;
  setLanguage: (lang: "zh" | "en") => void;
  setTheme: (theme: "light" | "dark") => void;
  setLastLutName: (name: string) => void;
  setLastColorMode: (mode: string) => void;
  setLastModelingMode: (mode: string) => void;
  setLastBedLabel: (label: string) => void;
  setCropEnabled: (enabled: boolean) => void;
  setLastSlicerId: (id: string) => void;
  setEnableBlur: (enabled: boolean) => void;
  setEnableFancyLoading: (enabled: boolean) => void;
  setEnableWittyLoading: (enabled: boolean) => void;
  setEnableCompletionNotifications: (enabled: boolean) => void;
  setEnableSmoothVectorPreview: (enabled: boolean) => void;
  setPreserveUploadFilenameFor3mf: (enabled: boolean) => void;
  setPaletteMode: (mode: "swatch" | "card") => void;
  setPrinterModel: (id: string) => void;
  setSlicerSoftware: (id: string) => void;
  setDeviceProfileId: (id: string) => void;
  setCustom3mfTemplateId: (id: string | null) => void;
  importCustom3mfTemplate: (file: File, name: string) => Promise<Custom3mfTemplate>;
  deleteCustom3mfTemplate: (id: string) => Promise<void>;
  setBuildPlateForMachine: (machineProfileId: string, plateId: string) => void;
  setCustomSlicerPath: (path: string) => void;
  setCustomSlicerId: (id: string) => void;
  setNozzleSize: (size: NozzleSize) => void;
  setEnableBaseLayerHeightModifier: (enabled: boolean) => void;
  setEnableWipeTowerAutoPlacement: (enabled: boolean) => void;
  setEnableSolverCacheGridSelection: (enabled: boolean) => void;
  setSolverCacheGridResolution: (value: SolverCacheGridResolution) => void;
  setSvgPixelsPerMm: (value: number) => void;
  resetSvgPixelsPerMm: () => void;
  setMaterialDeltaE00Tolerance: (value: number) => void;
  setAutoReplaceGradientBanding: (enabled: boolean) => void;
  setGeneratedFileDirectory: (directory: string) => void;
  setHeaderNavAlignment: (alignment: HeaderNavAlignment) => void;
  hydrateDeviceSettingsFromBackend: (settings: Partial<UserSettings>) => void;
  syncToBackend: () => Promise<void>;
}

// ========== Default State ==========

export const DEFAULT_SETTINGS: SettingsState = {
  conversionPreferences: { last: null, presets: [] },
  language: "zh",
  theme: "light",
  lastLutName: "",
  lastColorMode: "4-Color (RYBW)",
  lastModelingMode: "high-fidelity",
  lastBedLabel: "256×256 mm",
  cropEnabled: true,
  lastSlicerId: "",
  enableBlur: true,
  enableFancyLoading: true,
  enableWittyLoading: true,
  enableCompletionNotifications: false,
  enableSmoothVectorPreview: true,
  preserveUploadFilenameFor3mf: false,
  paletteMode: "swatch",
  printerModel: "bambu-h2d",
  slicerSoftware: "BambuStudio",
  deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
  buildPlateId: "",
  custom3mfTemplateId: null,
  buildPlateSelections: {},
  customSlicerPath: "",
  customSlicerId: "",
  nozzleSize: "0.4",
  enableBaseLayerHeightModifier: true,
  enableWipeTowerAutoPlacement: true,
  // Opt-in feature: the density dropdown is hidden by default so the
  // exhaustive-cache dialog stays focused for first-time users. When the
  // toggle is off, builds silently use the low (64) default on the backend.
  enableSolverCacheGridSelection: false,
  solverCacheGridResolution: 64,
  svgPixelsPerMm: SVG_PIXELS_PER_MM_DEFAULT,
  materialDeltaE00Tolerance: MATERIAL_DELTA_E00_TOLERANCE_DEFAULT,
  autoReplaceGradientBanding: false,
  generatedFileDirectory: "",
  headerNavAlignment: "center",
};

type PersistedSettingsSnapshot = Partial<SettingsState>;

const RETIRED_CLIENT_ONLY_SETTING_KEYS = [
  "mlsBaseUrl",
  "mlsBackendUrl",
] as const;

function stripRetiredClientOnlySettings(
  snapshot: Record<string, unknown>,
): PersistedSettingsSnapshot {
  const migrated: Record<string, unknown> = { ...snapshot };
  for (const key of RETIRED_CLIENT_ONLY_SETTING_KEYS) {
    delete migrated[key];
  }
  return migrated as PersistedSettingsSnapshot;
}

function patchLegacyPersistedDeviceProfile(
  snapshot: PersistedSettingsSnapshot,
): PersistedSettingsSnapshot {
  if (Object.prototype.hasOwnProperty.call(snapshot, "deviceProfileId")) {
    return snapshot;
  }
  if (
    Object.prototype.hasOwnProperty.call(snapshot, "printerModel") ||
    Object.prototype.hasOwnProperty.call(snapshot, "slicerSoftware") ||
    Object.prototype.hasOwnProperty.call(snapshot, "nozzleSize")
  ) {
    return { ...snapshot, deviceProfileId: "" };
  }
  return snapshot;
}

function migratePersistedSettings(
  persistedState: unknown,
): PersistedSettingsSnapshot {
  if (!persistedState || typeof persistedState !== "object") {
    return {};
  }
  return patchLegacyPersistedDeviceProfile(
    stripRetiredClientOnlySettings(persistedState as Record<string, unknown>),
  );
}

function readPersistedSettingsSnapshot(): PersistedSettingsSnapshot | null {
  try {
    const raw = localStorage.getItem("lumina-settings");
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as { state?: Record<string, unknown> };
    if (
      !parsed ||
      typeof parsed !== "object" ||
      !parsed.state ||
      typeof parsed.state !== "object"
    ) {
      return null;
    }
    return stripRetiredClientOnlySettings(parsed.state);
  } catch {
    return null;
  }
}

const INITIAL_PERSISTED_SETTINGS_SNAPSHOT = readPersistedSettingsSnapshot();

function hasOwnSetting(
  snapshot: PersistedSettingsSnapshot | null,
  key: keyof SettingsState,
): boolean {
  return !!snapshot && Object.prototype.hasOwnProperty.call(snapshot, key);
}

function normalizeSvgPixelsPerMm(value: number): number {
  if (!Number.isFinite(value)) {
    return SVG_PIXELS_PER_MM_DEFAULT;
  }
  const clamped = Math.min(
    SVG_PIXELS_PER_MM_MAX,
    Math.max(SVG_PIXELS_PER_MM_MIN, value),
  );
  return Number(clamped.toFixed(1));
}

function normalizeMaterialDeltaE00Tolerance(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return MATERIAL_DELTA_E00_TOLERANCE_DEFAULT;
  }
  const clamped = Math.min(
    MATERIAL_DELTA_E00_TOLERANCE_MAX,
    Math.max(MATERIAL_DELTA_E00_TOLERANCE_MIN, value),
  );
  return Number(clamped.toFixed(1));
}

export function deriveBackendDeviceSettingsPatch(
  current: SettingsState,
  settings: Partial<UserSettings>,
  persistedSnapshot: PersistedSettingsSnapshot | null,
): Partial<SettingsState> {
  const patch: Partial<SettingsState> = {};
  if (!hasOwnSetting(persistedSnapshot, "conversionPreferences") &&
      !current.conversionPreferences.last && current.conversionPreferences.presets.length === 0 &&
      settings.conversion_preferences) {
    patch.conversionPreferences = normalizeConversionPreferences(settings.conversion_preferences);
  }

  const setScalarIfFresh = <Key extends keyof SettingsState>(
    key: Key,
    value: SettingsState[Key] | undefined,
  ): void => {
    if (
      value !== undefined &&
      current[key] === DEFAULT_SETTINGS[key] &&
      !hasOwnSetting(persistedSnapshot, key)
    ) {
      (patch as Record<keyof SettingsState, unknown>)[key] = value;
    }
  };

  setScalarIfFresh(
    "language",
    settings.language === "zh" || settings.language === "en"
      ? settings.language
      : undefined,
  );
  setScalarIfFresh(
    "custom3mfTemplateId",
    typeof settings.custom_3mf_template_id === "string"
      ? settings.custom_3mf_template_id || null
      : settings.custom_3mf_template_id === null ? null : undefined,
  );
  setScalarIfFresh(
    "theme",
    settings.theme === "light" || settings.theme === "dark"
      ? settings.theme
      : undefined,
  );
  setScalarIfFresh(
    "lastLutName",
    typeof settings.last_lut === "string" ? settings.last_lut : undefined,
  );
  setScalarIfFresh(
    "lastModelingMode",
    typeof settings.last_modeling_mode === "string"
      ? settings.last_modeling_mode
      : undefined,
  );
  setScalarIfFresh(
    "lastColorMode",
    typeof settings.last_color_mode === "string"
      ? settings.last_color_mode
      : undefined,
  );
  setScalarIfFresh(
    "lastSlicerId",
    typeof settings.last_slicer === "string" ? settings.last_slicer : undefined,
  );
  setScalarIfFresh(
    "lastBedLabel",
    typeof settings.last_bed_label === "string"
      ? settings.last_bed_label
      : undefined,
  );
  setScalarIfFresh(
    "paletteMode",
    settings.palette_mode === "swatch" || settings.palette_mode === "card"
      ? settings.palette_mode
      : undefined,
  );
  setScalarIfFresh(
    "cropEnabled",
    typeof settings.enable_crop_modal === "boolean"
      ? settings.enable_crop_modal
      : undefined,
  );
  setScalarIfFresh(
    "enableBlur",
    typeof settings.enable_blur === "boolean"
      ? settings.enable_blur
      : undefined,
  );
  setScalarIfFresh(
    "enableFancyLoading",
    typeof settings.enable_fancy_loading === "boolean"
      ? settings.enable_fancy_loading
      : undefined,
  );
  setScalarIfFresh(
    "enableWittyLoading",
    typeof settings.enable_witty_loading === "boolean"
      ? settings.enable_witty_loading
      : undefined,
  );
  setScalarIfFresh(
    "enableCompletionNotifications",
    typeof settings.enable_completion_notifications === "boolean"
      ? settings.enable_completion_notifications
      : undefined,
  );
  setScalarIfFresh(
    "enableSmoothVectorPreview",
    typeof settings.enable_smooth_vector_preview === "boolean"
      ? settings.enable_smooth_vector_preview
      : undefined,
  );
  setScalarIfFresh(
    "preserveUploadFilenameFor3mf",
    typeof settings.preserve_upload_filename_for_3mf === "boolean"
      ? settings.preserve_upload_filename_for_3mf
      : undefined,
  );

  if (
    typeof settings.printer_model === "string" &&
    settings.printer_model.trim() &&
    current.printerModel === DEFAULT_SETTINGS.printerModel &&
    !hasOwnSetting(persistedSnapshot, "printerModel")
  ) {
    patch.printerModel = settings.printer_model.trim();
  }

  if (
    typeof settings.slicer_software === "string" &&
    settings.slicer_software.trim() &&
    current.slicerSoftware === DEFAULT_SETTINGS.slicerSoftware &&
    !hasOwnSetting(persistedSnapshot, "slicerSoftware")
  ) {
    patch.slicerSoftware = settings.slicer_software.trim();
  }

  if (
    typeof settings.device_profile_id === "string" &&
    settings.device_profile_id.trim() &&
    current.deviceProfileId === DEFAULT_SETTINGS.deviceProfileId &&
    !hasOwnSetting(persistedSnapshot, "deviceProfileId")
  ) {
    patch.deviceProfileId = settings.device_profile_id.trim();
  }

  if (
    typeof settings.build_plate_id === "string" &&
    current.buildPlateId === DEFAULT_SETTINGS.buildPlateId &&
    !hasOwnSetting(persistedSnapshot, "buildPlateId")
  ) {
    patch.buildPlateId = settings.build_plate_id.trim();
  }

  if (
    settings.build_plate_selections &&
    typeof settings.build_plate_selections === "object" &&
    Object.keys(current.buildPlateSelections).length === 0 &&
    !hasOwnSetting(persistedSnapshot, "buildPlateSelections")
  ) {
    patch.buildPlateSelections = { ...settings.build_plate_selections };
  }

  if (
    typeof settings.custom_slicer_path === "string" &&
    settings.custom_slicer_path.trim() &&
    current.customSlicerPath === DEFAULT_SETTINGS.customSlicerPath &&
    !hasOwnSetting(persistedSnapshot, "customSlicerPath")
  ) {
    patch.customSlicerPath = settings.custom_slicer_path.trim();
  }

  if (
    typeof settings.custom_slicer_id === "string" &&
    settings.custom_slicer_id.trim() &&
    current.customSlicerId === DEFAULT_SETTINGS.customSlicerId &&
    !hasOwnSetting(persistedSnapshot, "customSlicerId")
  ) {
    patch.customSlicerId = settings.custom_slicer_id.trim();
  }

  if (
    isNozzleSize(settings.nozzle_size) &&
    current.nozzleSize === DEFAULT_SETTINGS.nozzleSize &&
    !hasOwnSetting(persistedSnapshot, "nozzleSize")
  ) {
    patch.nozzleSize = settings.nozzle_size;
  }

  if (
    typeof settings.enable_base_layer_height_modifier === "boolean" &&
    current.enableBaseLayerHeightModifier ===
      DEFAULT_SETTINGS.enableBaseLayerHeightModifier &&
    !hasOwnSetting(persistedSnapshot, "enableBaseLayerHeightModifier")
  ) {
    patch.enableBaseLayerHeightModifier =
      settings.enable_base_layer_height_modifier;
  }

  setScalarIfFresh(
    "enableWipeTowerAutoPlacement",
    typeof settings.enable_wipe_tower_auto_placement === "boolean"
      ? settings.enable_wipe_tower_auto_placement
      : undefined,
  );
  setScalarIfFresh(
    "enableSolverCacheGridSelection",
    typeof settings.enable_solver_cache_grid_selection === "boolean"
      ? settings.enable_solver_cache_grid_selection
      : undefined,
  );
  setScalarIfFresh(
    "solverCacheGridResolution",
    SOLVER_CACHE_GRID_RESOLUTIONS.includes(
      settings.solver_cache_grid_resolution as SolverCacheGridResolution,
    )
      ? (settings.solver_cache_grid_resolution as SolverCacheGridResolution)
      : undefined,
  );
  setScalarIfFresh(
    "svgPixelsPerMm",
    typeof settings.svg_pixels_per_mm === "number"
      ? normalizeSvgPixelsPerMm(settings.svg_pixels_per_mm)
      : undefined,
  );
  setScalarIfFresh(
    "materialDeltaE00Tolerance",
    typeof settings.material_delta_e00_tolerance === "number"
      ? normalizeMaterialDeltaE00Tolerance(
          settings.material_delta_e00_tolerance,
        )
      : undefined,
  );
  setScalarIfFresh(
    "autoReplaceGradientBanding",
    typeof settings.auto_replace_gradient_banding === "boolean"
      ? settings.auto_replace_gradient_banding
      : undefined,
  );
  setScalarIfFresh(
    "generatedFileDirectory",
    typeof settings.generated_file_directory === "string"
      ? settings.generated_file_directory.trim()
      : undefined,
  );
  setScalarIfFresh(
    "headerNavAlignment",
    isHeaderNavAlignment(settings.header_nav_alignment)
      ? settings.header_nav_alignment
      : undefined,
  );

  return patch;
}

export interface ResolvedBuildPlateSelection {
  plateId: string;
  fellBack: boolean;
}

export function resolveBuildPlateSelection(
  machineProfileId: string,
  availablePlateIds: readonly string[],
  defaultPlateId: string,
  selections: Readonly<Record<string, string>>,
): ResolvedBuildPlateSelection {
  const remembered = selections[machineProfileId] ?? "";
  if (remembered && availablePlateIds.includes(remembered)) {
    return { plateId: remembered, fellBack: false };
  }
  const plateId = availablePlateIds.includes(defaultPlateId)
    ? defaultPlateId
    : (availablePlateIds[0] ?? "");
  return { plateId, fellBack: Boolean(remembered && plateId) };
}

// ========== Store ==========

function clearMaterialSuggestionsForGridChange(): void {
  void import("./converter").then(({ useConverterStore }) => {
    const state = useConverterStore.getState();
    if (!state.projectSettings) state.clearMaterialSuggestions();
  });
}

export const useSettingsStore = create<SettingsState & SettingsActions>()(
  persist(
    (set, get) => ({
      ...DEFAULT_SETTINGS,

      setConversionPreferences: (preferences) => set({ conversionPreferences: normalizeConversionPreferences(preferences) }),

      setLanguage: (lang: "zh" | "en") => set({ language: lang }),

      setTheme: (theme: "light" | "dark") => set({ theme }),

      setLastLutName: (name: string) => set({ lastLutName: name }),

      setLastColorMode: (mode: string) => set({ lastColorMode: mode }),

      setLastModelingMode: (mode: string) => set({ lastModelingMode: mode }),

      setLastBedLabel: (label: string) => set({ lastBedLabel: label }),

      setCropEnabled: (enabled: boolean) => set({ cropEnabled: enabled }),

      setLastSlicerId: (id: string) => set({ lastSlicerId: id }),

      setEnableBlur: (enabled: boolean) => set({ enableBlur: enabled }),

      setEnableFancyLoading: (enabled: boolean) =>
        set({ enableFancyLoading: enabled }),

      setEnableWittyLoading: (enabled: boolean) =>
        set({ enableWittyLoading: enabled }),

      setEnableCompletionNotifications: (enabled: boolean) =>
        set({ enableCompletionNotifications: enabled }),

      setEnableSmoothVectorPreview: (enabled: boolean) =>
        set({ enableSmoothVectorPreview: enabled }),

      setPreserveUploadFilenameFor3mf: (enabled: boolean) => {
        if (get().preserveUploadFilenameFor3mf === enabled) {
          return;
        }
        set({ preserveUploadFilenameFor3mf: enabled });
        invalidateSingleItemDownload();
      },

      setPaletteMode: (mode: "swatch" | "card") => set({ paletteMode: mode }),

      setPrinterModel: (id: string) => {
        set((state) => ({
          printerModel: id,
          deviceProfileId:
            state.printerModel === id ? state.deviceProfileId : "",
        }));
        invalidateGeneratedArtifacts({ source: "defaults" });
        synchronizePrinterBedLabel(id);
      },

      setSlicerSoftware: (id: string) => {
        set((state) => ({
          slicerSoftware: id,
          deviceProfileId:
            state.slicerSoftware === id ? state.deviceProfileId : "",
        }));
        invalidateGeneratedArtifacts({ source: "defaults" });
      },

      setDeviceProfileId: (id: string) => {
        set({ deviceProfileId: id });
        invalidateGeneratedArtifacts({ source: "defaults" });
      },

      setCustom3mfTemplateId: (id: string | null) => {
        if (get().custom3mfTemplateId === id) return;
        set({ custom3mfTemplateId: id });
        invalidateGeneratedArtifacts({ preservePreviews: true, source: "defaults" });
        void get().syncToBackend();
      },

      /** Import and select unless the user changed selection while awaiting the API.
       * 导入模板；等待期间用户更改过的模板或切片软件选择优先保留。
       */
      importCustom3mfTemplate: async (file, name) => {
        const { slicerSoftware } = get();
        let selectionUnchanged = true;
        const unsubscribe = useSettingsStore.subscribe((current, previous) => {
          if (
            current.custom3mfTemplateId !== previous.custom3mfTemplateId ||
            current.slicerSoftware !== previous.slicerSoftware
          ) {
            selectionUnchanged = false;
          }
        });
        try {
          const template = await importCustom3mfTemplate(file, name, slicerSoftware);
          if (selectionUnchanged) get().setCustom3mfTemplateId(template.id);
          return template;
        } finally {
          unsubscribe();
        }
      },

      /** Clear a deleted selection independently of the settings panel lifecycle.
       * 删除成功后清理仍指向该模板的全局选择，不依赖设置面板是否挂载。
       */
      deleteCustom3mfTemplate: async (id) => {
        await deleteCustom3mfTemplate(id);
        const current = get();
        if (current.custom3mfTemplateId === id) current.setCustom3mfTemplateId(null);
      },

      setBuildPlateForMachine: (machineProfileId: string, plateId: string) => {
        const current = get();
        if (
          current.buildPlateId === plateId &&
          (!plateId || current.buildPlateSelections[machineProfileId] === plateId)
        ) {
          return;
        }
        set((state) => {
          if (!plateId) {
            return { buildPlateId: "" };
          }
          return {
            buildPlateId: plateId,
            buildPlateSelections: {
              ...state.buildPlateSelections,
              [machineProfileId]: plateId,
            },
          };
        });
        invalidateGeneratedArtifacts({ preservePreviews: true, source: "defaults" });
      },

      setCustomSlicerPath: (path: string) => set({ customSlicerPath: path }),

      setCustomSlicerId: (id: string) => set({ customSlicerId: id }),

      setNozzleSize: (size: NozzleSize) => {
        set((state) => ({
          nozzleSize: size,
          deviceProfileId:
            state.nozzleSize === size ? state.deviceProfileId : "",
        }));
        invalidateGeneratedArtifacts({ source: "defaults" });
      },

      setEnableBaseLayerHeightModifier: (enabled: boolean) => {
        set({ enableBaseLayerHeightModifier: enabled });
        invalidateGeneratedArtifacts({ source: "defaults" });
      },

      setEnableWipeTowerAutoPlacement: (enabled: boolean) => {
        if (get().enableWipeTowerAutoPlacement === enabled) {
          return;
        }
        set({ enableWipeTowerAutoPlacement: enabled });
        invalidateGeneratedArtifacts({ source: "defaults" });
      },

      setEnableSolverCacheGridSelection: (enabled: boolean) => {
        if (get().enableSolverCacheGridSelection === enabled) {
          return;
        }
        set({ enableSolverCacheGridSelection: enabled });
        clearMaterialSuggestionsForGridChange();
      },

      setSolverCacheGridResolution: (value: SolverCacheGridResolution) => {
        if (!SOLVER_CACHE_GRID_RESOLUTIONS.includes(value)) {
          // Defensive guard: callers should only pass whitelisted values,
          // but a stale persisted snapshot or an external caller could
          // still slip through; treat unknown inputs as a no-op rather
          // than corrupting the store.
          return;
        }
        const current = get();
        if (current.solverCacheGridResolution === value) {
          return;
        }
        set({ solverCacheGridResolution: value });
        if (current.enableSolverCacheGridSelection) {
          clearMaterialSuggestionsForGridChange();
        }
      },

      setSvgPixelsPerMm: (value: number) => {
        set({ svgPixelsPerMm: normalizeSvgPixelsPerMm(value) });
        invalidateGeneratedArtifacts({ source: "defaults" });
      },

      resetSvgPixelsPerMm: () => {
        set({ svgPixelsPerMm: SVG_PIXELS_PER_MM_DEFAULT });
        invalidateGeneratedArtifacts({ source: "defaults" });
      },

      setMaterialDeltaE00Tolerance: (value: number) => {
        set({
          materialDeltaE00Tolerance:
            normalizeMaterialDeltaE00Tolerance(value),
        });
        invalidatePreviewArtifacts();
      },

      setAutoReplaceGradientBanding: (enabled: boolean) =>
        set({ autoReplaceGradientBanding: enabled }),

      setGeneratedFileDirectory: (directory: string) =>
        set({ generatedFileDirectory: directory.trim() }),

      setHeaderNavAlignment: (alignment: HeaderNavAlignment) => {
        if (!isHeaderNavAlignment(alignment)) {
          return;
        }
        set({ headerNavAlignment: alignment });
      },

      hydrateDeviceSettingsFromBackend: (settings: Partial<UserSettings>) => {
        const current = get();
        const patch = deriveBackendDeviceSettingsPatch(
          current,
          settings,
          INITIAL_PERSISTED_SETTINGS_SNAPSHOT,
        );
        const actions = get();
        const directPatch = { ...patch };
        if (patch.printerModel) {
          actions.setPrinterModel(patch.printerModel);
          delete directPatch.printerModel;
        }
        if (patch.slicerSoftware) {
          actions.setSlicerSoftware(patch.slicerSoftware);
          delete directPatch.slicerSoftware;
        }
        if (typeof patch.customSlicerPath === "string") {
          actions.setCustomSlicerPath(patch.customSlicerPath);
          delete directPatch.customSlicerPath;
        }
        if (typeof patch.customSlicerId === "string") {
          actions.setCustomSlicerId(patch.customSlicerId);
          delete directPatch.customSlicerId;
        }
        if (patch.nozzleSize) {
          actions.setNozzleSize(patch.nozzleSize);
          delete directPatch.nozzleSize;
        }
        if (typeof patch.enableBaseLayerHeightModifier === "boolean") {
          actions.setEnableBaseLayerHeightModifier(
            patch.enableBaseLayerHeightModifier,
          );
          delete directPatch.enableBaseLayerHeightModifier;
        }
        if (typeof patch.enableWipeTowerAutoPlacement === "boolean") {
          actions.setEnableWipeTowerAutoPlacement(
            patch.enableWipeTowerAutoPlacement,
          );
          delete directPatch.enableWipeTowerAutoPlacement;
        }
        if (typeof patch.deviceProfileId === "string") {
          actions.setDeviceProfileId(patch.deviceProfileId);
          delete directPatch.deviceProfileId;
        }
        if (Object.keys(directPatch).length > 0) {
          set(directPatch);
        }
      },

      syncToBackend: async () => {
        const state = get();
        try {
          await saveSettings({
            conversion_preferences: state.conversionPreferences,
            language: state.language,
            theme: state.theme,
            last_lut: state.lastLutName,
            last_modeling_mode: state.lastModelingMode,
            last_color_mode: state.lastColorMode,
            last_slicer: state.lastSlicerId,
            last_bed_label: state.lastBedLabel,
            palette_mode: state.paletteMode,
            enable_crop_modal: state.cropEnabled,
            enable_blur: state.enableBlur,
            enable_fancy_loading: state.enableFancyLoading,
            enable_witty_loading: state.enableWittyLoading,
            enable_completion_notifications:
              state.enableCompletionNotifications,
            enable_smooth_vector_preview: state.enableSmoothVectorPreview,
            preserve_upload_filename_for_3mf:
              state.preserveUploadFilenameFor3mf,
            printer_model: state.printerModel,
            slicer_software: state.slicerSoftware,
            device_profile_id: state.deviceProfileId,
            build_plate_id: state.buildPlateId,
            custom_3mf_template_id: state.custom3mfTemplateId,
            build_plate_selections: state.buildPlateSelections,
            custom_slicer_path: state.customSlicerPath,
            custom_slicer_id: state.customSlicerId,
            nozzle_size: state.nozzleSize,
            enable_base_layer_height_modifier:
              state.enableBaseLayerHeightModifier,
            enable_wipe_tower_auto_placement:
              state.enableWipeTowerAutoPlacement,
            enable_solver_cache_grid_selection:
              state.enableSolverCacheGridSelection,
            solver_cache_grid_resolution: state.solverCacheGridResolution,
            svg_pixels_per_mm: state.svgPixelsPerMm,
            material_delta_e00_tolerance:
              state.materialDeltaE00Tolerance,
            auto_replace_gradient_banding:
              state.autoReplaceGradientBanding,
            generated_file_directory: state.generatedFileDirectory,
            header_nav_alignment: state.headerNavAlignment,
          });
        } catch {
          // best-effort sync — settings are already persisted in localStorage
        }
      },
    }),
    {
      name: "lumina-settings",
      version: 1,
      migrate: migratePersistedSettings,
      merge: (persistedState, currentState) => {
        const persistedSettings = patchLegacyPersistedDeviceProfile(
          stripRetiredClientOnlySettings(
            persistedState && typeof persistedState === "object"
              ? (persistedState as Record<string, unknown>)
              : {},
          ),
        );
        return {
          ...currentState,
          ...persistedSettings,
          conversionPreferences: normalizeConversionPreferences(persistedSettings.conversionPreferences),
          materialDeltaE00Tolerance: normalizeMaterialDeltaE00Tolerance(
            persistedSettings.materialDeltaE00Tolerance ??
              currentState.materialDeltaE00Tolerance,
          ),
          enableWipeTowerAutoPlacement:
            typeof persistedSettings.enableWipeTowerAutoPlacement === "boolean"
              ? persistedSettings.enableWipeTowerAutoPlacement
              : currentState.enableWipeTowerAutoPlacement,
          headerNavAlignment: isHeaderNavAlignment(
            persistedSettings.headerNavAlignment,
          )
            ? persistedSettings.headerNavAlignment
            : currentState.headerNavAlignment,
        };
      },
    },
  ),
);
