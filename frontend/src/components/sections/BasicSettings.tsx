import { useRef, useEffect, useMemo, useState, useCallback } from "react";
import { ScissorsIcon } from "@heroicons/react/24/outline";
import { useShallow } from "zustand/react/shallow";
import {
  useConverterStore,
  ACCEPT_IMAGE_FORMATS,
  MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
  inferDefaultMaterialBackingDirName,
  isValidImageType,
  hasOnlySvgInputs,
} from "../../stores/converter";
import {
  ColorMode,
  ModelingMode,
  StructureMode,
} from "../../api/types";
import { apiErrorToVisibleMessage } from "../../api/client";
import type { SavedMaterialLibraryItem } from "../../api/types";
import { listGradientCardMaterials } from "../../api/extractor";
import { reconcileDirectoryNames } from "../../utils/materialDirectoryMigration";
import UnifiedUploader from "../ui/UnifiedUploader";
import Button from "../ui/Button";
import ConversionPresets from "./ConversionPresets";
import Checkbox from "../ui/Checkbox";
import Dropdown from "../ui/Dropdown";
import Slider from "../ui/Slider";
import RadioGroup from "../ui/RadioGroup";
import { CropModal } from "../ui/CropModal";
import type { CropData } from "../ui/CropModal";
import ImportConfirmDialog from "../ui/ImportConfirmDialog";
import MaterialPickerDialog from "../ui/MaterialPickerDialog";
import MaterialSolverCacheDialog from "../MaterialSolverCacheDialog";
import LegacyLutSelector from "./LegacyLutSelector";
import { TUTORIAL_STEPS } from "../../data/tutorialSteps";
import { useTutorialStore } from "../../stores/tutorialStore";
import { useI18n } from "../../i18n/context";
import {
  prepareImport,
  applyImport,
  revokeImportCoverUrl,
  RECIPE_IMPORT_PREDICTIVE_LUT_UNAVAILABLE_ERROR,
} from "../../recipe/importFlow";
import type { ImportPreview } from "../../recipe/importFlow";
import {
  RECIPE_ASSET_CORRUPT_ERROR,
  RECIPE_IMPORT_NOT_SHARE_CARD_ERROR,
  type RecipeFileSource,
} from "../../recipe/importRecipe";
import {
  StatusBanner,
  settingsGroupClass,
  settingsGroupHeadingClass,
  dependentGroupClass,
  workstationFieldLabelClass,
  workstationInputClass,
  cx,
} from "../ui/panelPrimitives";
import { isSvgImageFile } from "../../utils/imageRotation";
import { WIKI_DOCS } from "../../utils/wikiDocs";
import { isPredictiveLutSource } from "../../utils/lutVisibility";
import {
  resolveLargeFormatTileGrid,
  resolveLargeFormatTotalHeightMm,
} from "../../utils/largeFormatTileLayout";
import {
  buildLutCatalogIndex,
  getBucketDisplayColorMode,
  listBucketsForManufacturer,
  normalizeLutPath,
  type ColorModeBucket,
} from "../../stores/converter/legacyLutSelection";
import WorkshopSourceBanner from "../../workshop/WorkshopSourceBanner";
import { useSettingsStore } from "../../stores/settingsStore";
import { getPrinterBedDimensions } from "../../stores/converter/dimensions";
import {
  buildWorkshopColorLibrary,
  clearWorkshopMaterialCatalog,
  getWorkshopColorLibrarySelectionKey,
  updateWorkshopMaterialCatalog,
} from "../../workshop/colorLibrary";

const COLOR_MODE_DOTS: Record<string, string[]> = {
  [ColorMode.BW]: ["var(--palette-black)", "var(--palette-white)"],
  [ColorMode.FOUR_COLOR_RYBW]: ["var(--palette-crimson)", "var(--palette-yellow)", "var(--palette-blue)", "var(--palette-white)"],
  [ColorMode.FOUR_COLOR_CMYW]: ["var(--palette-cyan)", "var(--palette-magenta)", "var(--palette-yellow-soft)", "var(--palette-white)"],
  [ColorMode.FIVE_COLOR_EXT]: ["var(--palette-white)", "var(--palette-crimson)", "var(--palette-yellow)", "var(--palette-blue)", "var(--palette-charcoal)"],
  [ColorMode.SIX_COLOR]: ["var(--palette-white)", "var(--palette-cyan)", "var(--palette-magenta)", "var(--palette-green)", "var(--palette-yellow-soft)", "var(--palette-black)"],
  [ColorMode.SIX_COLOR_RYBW]: ["var(--palette-white)", "var(--palette-crimson)", "var(--palette-yellow)", "var(--palette-blue)", "var(--palette-green)", "var(--palette-black)"],
  [ColorMode.EIGHT_COLOR]: [
    "var(--palette-white)", "var(--palette-cyan)", "var(--palette-magenta)", "var(--palette-yellow-soft)",
    "var(--palette-black)", "var(--palette-brick)", "var(--palette-indigo)", "var(--palette-green)",
  ],
};

const DOT_CLS = "inline-block size-2 rounded-full shrink-0 ring-1 ring-black/10 dark:ring-white/20";
// Material swatches: slightly larger, with a visible edge so white/black read clearly.
const MATERIAL_DOT_CLS = "inline-block size-2.5 rounded-full shrink-0 bg-slate-200 ring-1 ring-black/15 dark:bg-slate-700 dark:ring-white/25";
const THICKNESS_LAYER_STEP_MM = 0.08;
const THICKNESS_SLIDER_MIN_MM = 0.24;
const THICKNESS_SLIDER_MAX_MM = 10;
const BACKING_INFILL_DENSITY_MIN_PERCENT = 5;
const BACKING_INFILL_DENSITY_MAX_PERCENT = 100;
const BACKING_INFILL_DENSITY_STEP_PERCENT = 5;
const LARGE_FORMAT_TILE_SLIDER_MAX_MM = 500;
const GENERIC_HTTP_STATUS_ERROR_RE =
  /(?:Request failed with status code|HTTP(?:\s+error)?|status(?:\s+code)?)\s*\d{3}\b/i;
const STARTUP_LUT_RETRY_DELAY_MS = 5_000;
const STARTUP_LUT_ATTEMPT_LIMIT = 2;

function dimensionSliderStep(value: number): number {
  const normalized = value
    .toFixed(3)
    .replace(/0+$/, "")
    .replace(/\.$/, "");
  const decimals = normalized.split(".")[1]?.length ?? 0;
  return decimals === 0 ? 1 : 10 ** -decimals;
}


const LARGE_FORMAT_PREVIEW_FALLBACK_PREFIX =
  "Native vector large-format is unavailable for this SVG; large-format generation will fall back to raster tiling.";
const LARGE_FORMAT_GENERATE_FALLBACK_WARNING =
  "Raster fallback was used for this large-format SVG request.";
const LARGE_FORMAT_NATIVE_FAILURE_WARNING =
  "Native vector generation failed; raster fallback was used for this large-format SVG request.";
const WIPE_TOWER_MANUAL_WARNING_CODE = "wipe_tower_manual_adjustment_required";

function localizeLargeFormatWarning(
  warning: string,
  t: (key: string) => string,
): string {
  if (warning.startsWith(LARGE_FORMAT_PREVIEW_FALLBACK_PREFIX)) {
    const unsupportedFeatures = warning.match(/Unsupported features:\s*(.+?)\.?$/i)?.[1];
    if (unsupportedFeatures) {
      return t("large_format_warning_unsupported_features").replace(
        "{features}",
        unsupportedFeatures,
      );
    }
    return t("large_format_warning_native_unavailable");
  }
  if (warning === LARGE_FORMAT_GENERATE_FALLBACK_WARNING) {
    return t("large_format_warning_raster_fallback");
  }
  if (warning === LARGE_FORMAT_NATIVE_FAILURE_WARNING) {
    return t("large_format_warning_native_failure");
  }
  if (warning === WIPE_TOWER_MANUAL_WARNING_CODE) {
    return t("wipe_tower_manual_adjustment_warning");
  }
  return warning;
}

function snapThicknessToLayerGrid(value: number): number {
  const clamped = Math.min(
    THICKNESS_SLIDER_MAX_MM,
    Math.max(THICKNESS_SLIDER_MIN_MM, value),
  );
  const scaledLayerCount = clamped / THICKNESS_LAYER_STEP_MM;
  const lowerLayerCount = Math.floor(scaledLayerCount);
  // Match Python round() in the generation pipeline: exact half layers tie to even.
  // 与生成管线的 Python round() 保持一致：正好半层时取最近的偶数层。
  const isHalfLayer = scaledLayerCount - lowerLayerCount === 0.5;
  const layerCount = isHalfLayer
    ? lowerLayerCount + (lowerLayerCount % 2)
    : Math.round(scaledLayerCount);
  return Number((layerCount * THICKNESS_LAYER_STEP_MM).toFixed(2));
}

function hasApiErrorResponse(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "response" in error);
}

function shouldUseApiErrorLanguage(error: unknown): boolean {
  if (hasApiErrorResponse(error)) {
    return true;
  }
  const message = error instanceof Error ? error.message.trim() : "";
  return GENERIC_HTTP_STATUS_ERROR_RE.test(message);
}

function resolveRecipeImportError(
  error: unknown,
  t: (key: string) => string,
): string {
  if (shouldUseApiErrorLanguage(error)) {
    return apiErrorToVisibleMessage(error, t("recipe_import_error_unreadable"));
  }
  const message = error instanceof Error ? error.message.trim() : "";
  if (message === RECIPE_IMPORT_NOT_SHARE_CARD_ERROR) {
    return t("recipe_import_not_share_card");
  }
  if (message === RECIPE_ASSET_CORRUPT_ERROR) {
    return t("recipe_import_asset_corrupt");
  }
  if (message === RECIPE_IMPORT_PREDICTIVE_LUT_UNAVAILABLE_ERROR) {
    return t("recipe_import_predictive_lut_unavailable");
  }
  return t("recipe_import_error_unreadable");
}
const LEGACY_BUCKET_I18N_KEY: Partial<Record<ColorModeBucket, string>> = {
  [ColorMode.BW]: "basic_lut_color_mode_bw",
  [ColorMode.FOUR_COLOR_CMYW]: "basic_lut_color_mode_4color_cmyw",
  [ColorMode.FOUR_COLOR_RYBW]: "basic_lut_color_mode_4color_rybw",
  [ColorMode.FIVE_COLOR_EXT]: "basic_lut_color_mode_5color_ext",
  "5-Color Extended (1444)": "basic_lut_color_mode_5color_ext_1444",
  [ColorMode.SIX_COLOR]: "basic_lut_color_mode_6color_cmywgk",
  [ColorMode.SIX_COLOR_RYBW]: "basic_lut_color_mode_6color_rybwgk",
  [ColorMode.EIGHT_COLOR]: "basic_lut_color_mode_8color_max",
  [ColorMode.MERGED]: "basic_lut_color_mode_merged",
  "4-Color": "basic_lut_color_mode_4color",
  "6-Color": "basic_lut_color_mode_6color",
  "8-Color": "basic_lut_color_mode_8color",
};

function legacyBucketLabel(bucket: ColorModeBucket, t: (key: string) => string): string {
  const key = LEGACY_BUCKET_I18N_KEY[bucket];
  return key ? t(key) : bucket;
}

/** A borderless tinted group; radio groups provide their own heading. */
function Block({
  label,
  children,
  className,
  tutorial,
}: {
  label?: string;
  children: React.ReactNode;
  className?: string;
  tutorial?: string;
}) {
  return (
    <div data-tutorial={tutorial} className={cx(settingsGroupClass, !label && "settings-choice-group", className)}>
      {label && <p className={settingsGroupHeadingClass}>{label}</p>}
      {children}
    </div>
  );
}

function clampRgbChannel(value: number | undefined): number {
  return Math.max(0, Math.min(255, Math.round(value ?? 0)));
}

/** CSS color for a material's estimated sRGB. 耗材估计颜色的 CSS 值。 */
function materialSwatchColor(rgb: readonly number[] | undefined): string | null {
  if (!rgb || rgb.length < 3) return null;
  return `rgb(${clampRgbChannel(rgb[0])} ${clampRgbChannel(rgb[1])} ${clampRgbChannel(rgb[2])})`;
}

function ColorModeDots({ mode }: { mode: string }) {
  if (mode === ColorMode.MERGED) {
    return (
      <span
        className={`${DOT_CLS} animate-spin [animation-duration:3s]`}
        style={{
          background:
            "conic-gradient(var(--palette-crimson), var(--palette-yellow-soft), var(--palette-green), var(--palette-cyan), var(--palette-magenta), var(--palette-crimson))",
        }}
      />
    );
  }

  const dots = COLOR_MODE_DOTS[mode];
  if (!dots) return null;

  return (
    <span className="inline-flex items-center gap-0.5">
      {dots.map((color, i) => (
        <span
          key={i}
          className={DOT_CLS}
          style={{ backgroundColor: color }}
        />
      ))}
    </span>
  );
}

export default function BasicSettings() {
  const { t } = useI18n();

  const structureModeOptions = Object.values(StructureMode).map((v) => ({
    label: t(`structure_mode.${v}`),
    value: v,
  }));

  const modelingModeOptions = Object.values(ModelingMode).map((v) => ({
    label: t(`modeling_mode.${v}`),
    value: v,
  }));
  // 状态字段使用 useShallow 分组提取，避免无关字段变化触发重渲染
  const {
    imageFile,
    imagePreviewUrl,
    source_version,
    lut_name,
    lut_names,
    lutListFull,
    lutListLoading,
    legacyCatalogGroups,
    legacyCatalogLoading,
    selectedLegacyManufacturer,
    nativeBrandGroups,
    selectedNativeBrandKey,
    selectedNativeDbNames,
    color_mode,
    color_layers,
    layer_height_mm,
    selectedLutInfo,
    lutColors,
    lutColorsLutName,
    workshopSource,
    target_width_mm,
    target_height_mm,
    spacer_thick,
    backing_infill_density_percent,
    structure_mode,
    modeling_mode,
    enable_relief,
    enableCrop,
    cropModalOpen,
    isCropping,
    batchMode,
    batchFiles,
    isLoading,
    largeFormatEnabled,
    enable_fridge_magnet,
    puzzleEnabled,
    tileWidthMm,
    tileHeightMm,
    largeFormatTileOverlayVisible,
    previewPixelWidth,
    previewPixelHeight,
    previewImageUrl,
    previewWarnings,
    generatedLargeFormatWarnings,
    largeFormatFailedTiles,
    selectedMaterialDirNames,
    materialLayerCount,
    materialDynamicLayerCountEnabled,
    materialMinLayerCount,
    materialMaxLayerCount,
    materialLayerHeightMm,
    materialBackingMaterialDirName,
    modelSurfaceEnabled,
    setColorLayers,
    setLayerHeightMm,
    setSourceVersion,
    setSelectedMaterialDirNames,
    setMaterialLayerCount,
    setMaterialDynamicLayerCountEnabled,
    setMaterialMinLayerCount,
    setMaterialMaxLayerCount,
    setMaterialLayerHeightMm,
    setMaterialBackingMaterialDirName,
    setLegacyManufacturer,
    setLegacyLutNames,
    fetchLutList,
    fetchLegacyCatalog,
  } = useConverterStore(useShallow((s) => ({
    imageFile: s.imageFile,
    imagePreviewUrl: s.imagePreviewUrl,
    source_version: s.source_version,
    lut_name: s.lut_name,
    lut_names: s.lut_names,
    lutListFull: s.lutListFull,
    lutListLoading: s.lutListLoading,
    legacyCatalogGroups: s.legacyCatalogGroups,
    legacyCatalogLoading: s.legacyCatalogLoading,
    selectedLegacyManufacturer: s.selectedLegacyManufacturer,
    nativeBrandGroups: s.nativeBrandGroups,
    selectedNativeBrandKey: s.selectedNativeBrandKey,
    selectedNativeDbNames: s.selectedNativeDbNames,
    color_mode: s.color_mode,
    color_layers: s.color_layers,
    layer_height_mm: s.layer_height_mm,
    selectedLutInfo: s.selectedLutInfo,
    lutColors: s.lutColors,
    lutColorsLutName: s.lutColorsLutName,
    workshopSource: s.workshopSource,
    target_width_mm: s.target_width_mm,
    target_height_mm: s.target_height_mm,
    spacer_thick: s.spacer_thick,
    backing_infill_density_percent: s.backing_infill_density_percent,
    structure_mode: s.structure_mode,
    modeling_mode: s.modeling_mode,
    enable_relief: s.enable_relief,
    enableCrop: s.enableCrop,
    cropModalOpen: s.cropModalOpen,
    isCropping: s.isCropping,
    batchMode: s.batchMode,
    batchFiles: s.batchFiles,
    isLoading: s.isLoading,
    largeFormatEnabled: s.largeFormatEnabled,
    enable_fridge_magnet: s.enable_fridge_magnet,
    puzzleEnabled: s.puzzleEnabled,
    tileWidthMm: s.tileWidthMm,
    tileHeightMm: s.tileHeightMm,
    largeFormatTileOverlayVisible: s.largeFormatTileOverlayVisible,
    previewPixelWidth: s.previewPixelWidth,
    previewPixelHeight: s.previewPixelHeight,
    previewImageUrl: s.previewImageUrl,
    previewWarnings: s.previewWarnings,
    generatedLargeFormatWarnings: s.largeFormatWarnings,
    largeFormatFailedTiles: s.largeFormatFailedTiles,
    selectedMaterialDirNames: s.selectedMaterialDirNames,
    materialLayerCount: s.materialLayerCount,
    materialDynamicLayerCountEnabled: s.materialDynamicLayerCountEnabled,
    materialMinLayerCount: s.materialMinLayerCount,
    materialMaxLayerCount: s.materialMaxLayerCount,
    materialLayerHeightMm: s.materialLayerHeightMm,
    materialBackingMaterialDirName: s.materialBackingMaterialDirName,
    modelSurfaceEnabled: s.modelSurfaceEnabled,
    setColorLayers: s.setColorLayers,
    setLayerHeightMm: s.setLayerHeightMm,
    setSourceVersion: s.setSourceVersion,
    setSelectedMaterialDirNames: s.setSelectedMaterialDirNames,
    setMaterialLayerCount: s.setMaterialLayerCount,
    setMaterialDynamicLayerCountEnabled: s.setMaterialDynamicLayerCountEnabled,
    setMaterialMinLayerCount: s.setMaterialMinLayerCount,
    setMaterialMaxLayerCount: s.setMaterialMaxLayerCount,
    setMaterialLayerHeightMm: s.setMaterialLayerHeightMm,
    setMaterialBackingMaterialDirName: s.setMaterialBackingMaterialDirName,
    setLegacyManufacturer: s.setLegacyManufacturer,
    setLegacyLutNames: s.setLegacyLutNames,
    fetchLutList: s.fetchLutList,
    fetchLegacyCatalog: s.fetchLegacyCatalog,
  })));

  const [uploaderExpanded, setUploaderExpanded] = useState(true);
  const startupRetryMountedRef = useRef(false);
  const legacyCatalogRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const legacyCatalogStartupAttemptRef = useRef(0);
  const legacyCatalogLoadPendingRef = useRef(false);
  const lutListRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lutListStartupAttemptRef = useRef(0);
  const lutListLoadPendingRef = useRef(false);

  // --- Share card import state ---
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [importSource, setImportSource] = useState<RecipeFileSource>("png");
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [importLoading, setImportLoading] = useState(false);

  const handleShareCardDetected = useCallback(async (file: File) => {
    try {
      setImportLoading(true);
      const preview = await prepareImport(file);
      setImportPreview(preview);
      setImportSource(file.name.toLowerCase().endsWith(".json") ? "json" : "png");
      setImportDialogOpen(true);
    } catch (err) {
      const visibleError = resolveRecipeImportError(err, t);
      useConverterStore.getState().setError(
        t("recipe_import_error").replace("{error}", visibleError),
      );
    } finally {
      setImportLoading(false);
    }
  }, [t]);

  const applyPreparedImport = useCallback((
    destination: "converter" | "workshop",
  ) => {
    if (!importPreview) return;
    applyImport(
      importPreview.restoreResult,
      importPreview.printerOptions ?? [],
      { destination },
    );
    revokeImportCoverUrl(importPreview.coverUrl);
    setImportDialogOpen(false);
    setImportPreview(null);
  }, [importPreview]);

  const handleImportConfirm = useCallback(() => {
    applyPreparedImport("converter");
  }, [applyPreparedImport]);

  const handleImportContinueEditing = useCallback(() => {
    applyPreparedImport("workshop");
  }, [applyPreparedImport]);

  const handleImportCancel = useCallback(() => {
    revokeImportCoverUrl(importPreview?.coverUrl ?? null);
    setImportDialogOpen(false);
    setImportPreview(null);
  }, [importPreview]);

  useEffect(() => {
    if (previewImageUrl) setUploaderExpanded(false);
  }, [previewImageUrl]);

  useEffect(() => {
    if (!imageFile) setUploaderExpanded(true);
  }, [imageFile]);

  // Action 函数单独提取（函数引用稳定，不需要 shallow）
  const handleFilesSelect = useConverterStore((s) => s.handleFilesSelect);
  const setImageFile = useConverterStore((s) => s.setImageFile);
  const setLutName = useConverterStore((s) => s.setLutName);
  useEffect(() => {
    if (source_version === "native" || (
      source_version === "legacy" && isPredictiveLutSource(selectedLutInfo?.source_kind)
    )) {
      // Preserve the image, but require a new source instead of reusing an inactive LUT.
      setLutName("");
    }
  }, [source_version, selectedLutInfo?.source_kind, setLutName]);
  const setTargetWidthMm = useConverterStore((s) => s.setTargetWidthMm);
  const setTargetHeightMm = useConverterStore((s) => s.setTargetHeightMm);
  const setSpacerThick = useConverterStore((s) => s.setSpacerThick);
  const setBackingInfillDensityPercent = useConverterStore(
    (s) => s.setBackingInfillDensityPercent,
  );
  const setStructureMode = useConverterStore((s) => s.setStructureMode);
  const setModelingMode = useConverterStore((s) => s.setModelingMode);
  const setEnableCrop = useConverterStore((s) => s.setEnableCrop);
  const setCropModalOpen = useConverterStore((s) => s.setCropModalOpen);
  const submitCrop = useConverterStore((s) => s.submitCrop);
  const uploadLut = useConverterStore((s) => s.uploadLut);
  const fetchLutCatalog = useConverterStore((s) => s.fetchLutCatalog);
  const removeBatchFile = useConverterStore((s) => s.removeBatchFile);
  const setLargeFormatEnabled = useConverterStore((s) => s.setLargeFormatEnabled);
  const setTileWidthMm = useConverterStore((s) => s.setTileWidthMm);
  const setTileHeightMm = useConverterStore((s) => s.setTileHeightMm);
  const setLargeFormatTileOverlayVisible = useConverterStore(
    (s) => s.setLargeFormatTileOverlayVisible,
  );
  const rotateImageForExport = useConverterStore((s) => s.rotateImageForExport);
  const isVectorModelingAvailable = useConverterStore(hasOnlySvgInputs);
  const disabledModelingModes = isVectorModelingAvailable ? [] : [ModelingMode.VECTOR];

  const handleFileReplace = useCallback(
    (file: File) => {
      if (!isValidImageType(file.type, file.name)) return;
      setImageFile(file);
    },
    [setImageFile],
  );

  const sourceVersionOptions = [
    { label: t("basic_source_version_material"), value: "material" },
    { label: t("basic_source_version_legacy"), value: "legacy" },
  ];

  const clearLegacyCatalogRetry = useCallback(() => {
    if (legacyCatalogRetryTimerRef.current === null) return;
    clearTimeout(legacyCatalogRetryTimerRef.current);
    legacyCatalogRetryTimerRef.current = null;
  }, []);

  const clearLutListRetry = useCallback(() => {
    if (lutListRetryTimerRef.current === null) return;
    clearTimeout(lutListRetryTimerRef.current);
    lutListRetryTimerRef.current = null;
  }, []);

  useEffect(() => {
    startupRetryMountedRef.current = true;
    return () => {
      startupRetryMountedRef.current = false;
      clearLegacyCatalogRetry();
      clearLutListRetry();
    };
  }, [clearLegacyCatalogRetry, clearLutListRetry]);

  const startLegacyCatalogLoad = useCallback(() => {
    if (legacyCatalogLoadPendingRef.current) return;
    legacyCatalogLoadPendingRef.current = true;
    legacyCatalogStartupAttemptRef.current += 1;

    void fetchLegacyCatalog({ suppressClientLog: true })
      .catch(() => undefined)
      .then(() => {
        legacyCatalogLoadPendingRef.current = false;
        if (!startupRetryMountedRef.current) return;

        const state = useConverterStore.getState();
        if (state.source_version !== "legacy" || state.legacyCatalogGroups.length > 0) {
          legacyCatalogStartupAttemptRef.current = 0;
          return;
        }
        if (
          !state.legacyCatalogLoading &&
          legacyCatalogRetryTimerRef.current === null &&
          legacyCatalogStartupAttemptRef.current < STARTUP_LUT_ATTEMPT_LIMIT
        ) {
          legacyCatalogRetryTimerRef.current = setTimeout(() => {
            legacyCatalogRetryTimerRef.current = null;
            startLegacyCatalogLoad();
          }, STARTUP_LUT_RETRY_DELAY_MS);
        }
      });
  }, [fetchLegacyCatalog]);

  const startLutListLoad = useCallback(() => {
    if (lutListLoadPendingRef.current) return;
    lutListLoadPendingRef.current = true;
    lutListStartupAttemptRef.current += 1;

    void fetchLutList({ suppressClientLog: true })
      .catch(() => undefined)
      .then(() => {
        lutListLoadPendingRef.current = false;
        if (!startupRetryMountedRef.current) return;

        const state = useConverterStore.getState();
        if (state.source_version !== "legacy" || state.lutListFull.length > 0) {
          lutListStartupAttemptRef.current = 0;
          return;
        }
        if (
          !state.lutListLoading &&
          lutListRetryTimerRef.current === null &&
          lutListStartupAttemptRef.current < STARTUP_LUT_ATTEMPT_LIMIT
        ) {
          lutListRetryTimerRef.current = setTimeout(() => {
            lutListRetryTimerRef.current = null;
            startLutListLoad();
          }, STARTUP_LUT_RETRY_DELAY_MS);
        }
      });
  }, [fetchLutList]);

  useEffect(() => {
    if (source_version !== "legacy" || legacyCatalogGroups.length > 0) {
      clearLegacyCatalogRetry();
      legacyCatalogStartupAttemptRef.current = 0;
      return;
    }
    if (legacyCatalogStartupAttemptRef.current >= STARTUP_LUT_ATTEMPT_LIMIT) {
      return;
    }
    if (
      legacyCatalogLoading ||
      legacyCatalogRetryTimerRef.current !== null ||
      legacyCatalogLoadPendingRef.current
    ) {
      return;
    }

    startLegacyCatalogLoad();
  }, [
    source_version,
    legacyCatalogGroups.length,
    legacyCatalogLoading,
    clearLegacyCatalogRetry,
    startLegacyCatalogLoad,
  ]);

  useEffect(() => {
    if (source_version !== "legacy" || lutListFull.length > 0) {
      clearLutListRetry();
      lutListStartupAttemptRef.current = 0;
      return;
    }
    if (lutListStartupAttemptRef.current >= STARTUP_LUT_ATTEMPT_LIMIT) {
      return;
    }
    if (
      lutListLoading ||
      lutListRetryTimerRef.current !== null ||
      lutListLoadPendingRef.current
    ) {
      return;
    }

    startLutListLoad();
  }, [
    source_version,
    lutListFull.length,
    lutListLoading,
    clearLutListRetry,
    startLutListLoad,
  ]);

  const lutIndex = useMemo(
    () => buildLutCatalogIndex(legacyCatalogGroups),
    [legacyCatalogGroups],
  );
  const manufacturerOptions = useMemo(
    () =>
      Object.keys(lutIndex.byManufacturer)
        .sort((a, b) => a.localeCompare(b))
        .map((name) => ({
          label: name === "Unlabeled" ? t("basic_lut_unlabeled_brand") : name,
          value: name,
        })),
    [lutIndex, t],
  );
  const lutNameByPath = useMemo(() => {
    const map = new Map<string, string>();
    for (const entry of lutListFull) {
      map.set(normalizeLutPath(entry.path), entry.name);
    }
    return map;
  }, [lutListFull]);
  const groupedLutOptions = useMemo(() => {
    if (!selectedLegacyManufacturer) {
      return [];
    }
    const buckets = listBucketsForManufacturer(lutIndex, selectedLegacyManufacturer);
    const bucketModes = new Map(
      buckets.map((bucket) => [
        bucket,
        getBucketDisplayColorMode(lutIndex, selectedLegacyManufacturer, bucket),
      ]),
    );
    const visibleGroups = buckets
      .map((bucket) => {
        const displayMode = bucketModes.get(bucket) ?? bucket;
        const baseLabel = legacyBucketLabel(displayMode, t);
        return {
          displayMode,
          baseLabel,
          options:
            lutIndex.byManufacturerAndBucket[selectedLegacyManufacturer]?.[
              bucket
            ]?.map((item) => {
              const legacyName = lutNameByPath.get(normalizeLutPath(item.path));
              if (!legacyName) {
                return null;
              }
              return {
                label: item.name,
                value: legacyName,
              };
            }).filter((option) => option !== null) ?? [],
        };
      })
      .filter((group) => group.options.length > 0);
    const modeCounts = new Map<string, number>();
    for (const group of visibleGroups) {
      modeCounts.set(group.displayMode, (modeCounts.get(group.displayMode) ?? 0) + 1);
    }
    const modePositions = new Map<string, number>();
    return visibleGroups.map((group) => {
      const position = (modePositions.get(group.displayMode) ?? 0) + 1;
      modePositions.set(group.displayMode, position);
      return {
        label:
          (modeCounts.get(group.displayMode) ?? 0) > 1
            ? `${group.baseLabel} #${position}`
            : group.baseLabel,
        options: group.options,
      };
    });
  }, [lutIndex, selectedLegacyManufacturer, t, lutNameByPath]);
  const allLegacyLutOptions = useMemo(
    () => legacyCatalogGroups.flatMap((group) => group.items.flatMap((item) => {
      const value = lutNameByPath.get(normalizeLutPath(item.path));
      return value ? [{ label: item.name, value, brand: group.manufacturer, materialType: item.material_type }] : [];
    })),
    [legacyCatalogGroups, lutNameByPath],
  );
  const selectedLegacyBrandInfo = useMemo(() => {
    if (!selectedLegacyManufacturer) {
      return null;
    }
    const group = legacyCatalogGroups.find(
      (candidate) => candidate.manufacturer === selectedLegacyManufacturer,
    );
    const materialTypes = Array.from(
      new Set(
        (group?.items ?? [])
          .map((item) => item.material_type.trim())
          .filter(Boolean),
      ),
    ).sort((a, b) => a.localeCompare(b));
    return {
      displayName:
        selectedLegacyManufacturer === "Unlabeled"
          ? t("basic_lut_unlabeled_brand")
          : selectedLegacyManufacturer,
      materialTypes,
      vendor:
        selectedLegacyManufacturer === "Unlabeled"
          ? t("basic_lut_unlabeled_brand")
          : selectedLegacyManufacturer,
    };
  }, [legacyCatalogGroups, selectedLegacyManufacturer, t]);

  // --- Material library for material-archive mode ---
  const [materialLibrary, setMaterialLibrary] = useState<SavedMaterialLibraryItem[]>([]);
  const [materialLibraryLoading, setMaterialLibraryLoading] = useState(false);
  const [materialLibraryLoaded, setMaterialLibraryLoaded] = useState(false);
  const [materialLibraryLoadError, setMaterialLibraryLoadError] = useState(false);
  const [materialLibraryLoadAttempt, setMaterialLibraryLoadAttempt] = useState(0);
  const retryMaterialLibraryLoad = useCallback(() => {
    setMaterialLibraryLoadAttempt((attempt) => attempt + 1);
  }, []);
  useEffect(() => {
    if (source_version !== "material") {
      clearWorkshopMaterialCatalog();
      setMaterialLibraryLoaded(false);
      setMaterialLibraryLoadError(false);
      return;
    }
    let cancelled = false;
    setMaterialLibraryLoading(true);
    setMaterialLibraryLoaded(false);
    setMaterialLibraryLoadError(false);
    listGradientCardMaterials()
      .then((res) => {
        if (cancelled) return;
        const materials = res.materials ?? [];
        updateWorkshopMaterialCatalog(materials);
        setMaterialLibrary(materials);
        setMaterialLibraryLoaded(true);
      })
      .catch(() => {
        if (!cancelled) {
          clearWorkshopMaterialCatalog();
          setMaterialLibrary([]);
          setMaterialLibraryLoaded(false);
          setMaterialLibraryLoadError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setMaterialLibraryLoading(false);
      });
    return () => { cancelled = true; };
  }, [materialLibraryLoadAttempt, source_version]);

  useEffect(() => {
    if (source_version !== "material" || !materialLibraryLoaded) return;
    const { names: reconciled, changed } = reconcileDirectoryNames(
      selectedMaterialDirNames,
      materialLibrary,
    );
    if (changed) {
      setSelectedMaterialDirNames(reconciled);
    }
    if (materialBackingMaterialDirName) {
      const backing = reconcileDirectoryNames(
        [materialBackingMaterialDirName],
        materialLibrary,
      );
      if (backing.changed) {
        setMaterialBackingMaterialDirName(backing.names[0] ?? null);
      }
    }
  }, [
    materialBackingMaterialDirName,
    materialLibrary,
    materialLibraryLoaded,
    selectedMaterialDirNames,
    setMaterialBackingMaterialDirName,
    setSelectedMaterialDirNames,
    source_version,
  ]);

  const [materialPickerOpen, setMaterialPickerOpen] = useState(false);
  const handleMaterialPickerConfirm = useCallback(
    (next: string[]) => {
      setSelectedMaterialDirNames(next);
      setMaterialPickerOpen(false);
    },
    [setSelectedMaterialDirNames],
  );

  // Compact summary for the trigger button: shows the first few material names
  // plus a "+N more" suffix when truncated.
  // The beginner tour walks through the picker dialog: open it while a step
  // asks for it, and close it again only if the tour opened it.
  // 新手引导会讲解耗材选择框：步骤需要时打开，离开时只关闭由引导打开的选择框。
  const tutorialWantsMaterialPicker = useTutorialStore(
    (state) =>
      state.phase === "touring" &&
      Boolean(TUTORIAL_STEPS[state.stepIndex]?.prepare?.materialPicker),
  );
  const materialPickerOpenedByTutorialRef = useRef(false);
  useEffect(() => {
    if (tutorialWantsMaterialPicker && source_version === "material") {
      if (!materialPickerOpen) {
        materialPickerOpenedByTutorialRef.current = true;
        setMaterialPickerOpen(true);
      }
    } else if (materialPickerOpenedByTutorialRef.current) {
      materialPickerOpenedByTutorialRef.current = false;
      setMaterialPickerOpen(false);
    }
  }, [tutorialWantsMaterialPicker, source_version, materialPickerOpen]);

  const materialSummary = useMemo(() => {
    if (selectedMaterialDirNames.length === 0) {
      return null;
    }
    // Show every selected material with its color: stacks usually use 4–8.
    // 显示全部已选耗材及其颜色：叠色通常使用 4–8 种耗材。
    const lookup = new Map(materialLibrary.map((mat) => [mat.directory_name, mat]));
    return selectedMaterialDirNames.map((dirName) => {
      const material = lookup.get(dirName);
      return {
        dirName,
        name: material?.material_name ?? dirName,
        color: material ? materialSwatchColor(material.estimated_rgb) : null,
      };
    });
  }, [selectedMaterialDirNames, materialLibrary]);
  const materialNameLookup = useMemo(
    () => new Map(materialLibrary.map((mat) => [mat.directory_name, mat.material_name])),
    [materialLibrary],
  );
  const materialBackingOptions = useMemo(
    () =>
      selectedMaterialDirNames.map((dirName, index) => ({
        label: `${index + 1}. ${materialNameLookup.get(dirName) ?? dirName}`,
        value: dirName,
      })),
    [selectedMaterialDirNames, materialNameLookup],
  );
  const resolvedMaterialBackingDirName =
    materialBackingMaterialDirName &&
    selectedMaterialDirNames.includes(materialBackingMaterialDirName)
      ? materialBackingMaterialDirName
      : (inferDefaultMaterialBackingDirName(selectedMaterialDirNames) ?? "");
  const workshopColorLibrary =
    workshopSource === null
      ? null
      : buildWorkshopColorLibrary({
          source_version,
          lut_name,
          lut_names,
          lutListFull,
          legacyCatalogGroups,
          selectedLutInfo,
          lutColors,
          lutColorsLutName,
          nativeBrandGroups,
          selectedNativeBrandKey,
          selectedNativeDbNames,
          color_layers,
          layer_height_mm,
          selectedMaterialDirNames,
          materialLayerCount,
          materialLayerHeightMm,
        });
  const workshopColorLibrarySelectionKey =
    getWorkshopColorLibrarySelectionKey({
      source_version,
      lut_name,
      lut_names,
      selectedNativeBrandKey,
      selectedNativeDbNames,
      selectedMaterialDirNames,
    });

  const materialLayerHeightOptions = [
    { label: "0.04 mm", value: "0.04" },
    { label: "0.08 mm", value: "0.08" },
    { label: "0.10 mm", value: "0.1" },
  ];
  const lutFileRef = useRef<HTMLInputElement>(null);

  // 5-Color Extended and model-surface workflows only support one viewing side.
  const isFiveColorExt = color_mode === ColorMode.FIVE_COLOR_EXT;
  const supportsDynamicLayers = !!selectedLutInfo?.supports_dynamic_layer_count;
  const supportedModes = useMemo(
    () => selectedLutInfo?.supported_modes ?? [],
    [selectedLutInfo?.supported_modes],
  );
  const supportedLayerHeightOptions = useMemo(() => {
    const heights = Array.from(
      new Set(
        supportedModes
          .map((mode) => mode.layer_height_mm)
          .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
      ),
    ).sort((left, right) => left - right);
    const fallback = layer_height_mm ?? selectedLutInfo?.layer_height_mm ?? 0.08;
    if (heights.length === 0) {
      return [{ label: `${fallback.toFixed(2)} mm`, value: String(fallback) }];
    }
    return heights.map((value) => ({
      label: `${value.toFixed(2)} mm`,
      value: String(value),
    }));
  }, [layer_height_mm, selectedLutInfo?.layer_height_mm, supportedModes]);
  useEffect(() => {
    if (
      (isFiveColorExt || modelSurfaceEnabled) &&
      structure_mode === StructureMode.DOUBLE_SIDED
    ) {
      setStructureMode(StructureMode.SINGLE_SIDED);
    }
  }, [isFiveColorExt, modelSurfaceEnabled, structure_mode, setStructureMode]);

  const handleLutUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadLut(file);
    // Reset so same file can be re-uploaded
    if (lutFileRef.current) lutFileRef.current.value = "";
  };

  const [isRefreshingLut, setIsRefreshingLut] = useState(false);
  const handleRefreshLut = useCallback(async () => {
    if (isRefreshingLut) return;
    setIsRefreshingLut(true);
    try {
      await Promise.all([fetchLutCatalog(), fetchLegacyCatalog()]);
    } finally {
      setIsRefreshingLut(false);
    }
  }, [fetchLegacyCatalog, fetchLutCatalog, isRefreshingLut]);

  const handleCropConfirm = (data: CropData) => {
    if (isSvgImageFile(imageFile)) {
      if (data.rotation) void rotateImageForExport(data.rotation);
      else setCropModalOpen(false);
      return;
    }
    void submitCrop(data.x, data.y, data.width, data.height, data.rotation);
  };

  const printerModel = useSettingsStore((s) => s.printerModel);
  const dimensionLimits = useConverterStore(useShallow((state) =>
    getPrinterBedDimensions(state, printerModel),
  ));
  // Large-format text entry can exceed one bed; the sliders follow its size.
  const dimInputMax = largeFormatEnabled ? Number.POSITIVE_INFINITY : undefined;

  // Large-format tiles cut flat artwork, so they cannot represent a model
  // surface; the conflict banner replaces the grid summary in that case.
  const largeFormatModelSurfaceConflict = largeFormatEnabled && modelSurfaceEnabled;
  const tileGrid = useMemo(() => {
    if (!largeFormatEnabled || modelSurfaceEnabled) return null;
    // Match the height the backend derives for large-format generation.
    const grid = resolveLargeFormatTileGrid(
      target_width_mm,
      resolveLargeFormatTotalHeightMm(
        target_width_mm,
        target_height_mm,
        previewPixelWidth,
        previewPixelHeight,
      ),
      tileWidthMm,
      tileHeightMm,
    );
    if (!grid) return null;
    const lastW = Math.round(grid.lastColumnWidthMm);
    const lastH = Math.round(grid.lastRowHeightMm);
    return { cols: grid.cols, rows: grid.rows, total: grid.total, lastW, lastH };
  }, [
    largeFormatEnabled,
    modelSurfaceEnabled,
    target_width_mm,
    target_height_mm,
    previewPixelWidth,
    previewPixelHeight,
    tileWidthMm,
    tileHeightMm,
  ]);

  const mergedLargeFormatWarnings = useMemo(
    () =>
      Array.from(
        new Set(
          [
            ...(previewWarnings ?? []), ...(generatedLargeFormatWarnings ?? []),
            ...(largeFormatFailedTiles.length ? [t("large_format_partial_result").replace(
              "{tiles}", largeFormatFailedTiles.join(", "),
            )] : []),
          ].map(
            (warning) => localizeLargeFormatWarning(warning, t),
          ),
        ),
      ),
    [previewWarnings, generatedLargeFormatWarnings, largeFormatFailedTiles, t],
  );

  // A control that silently disappears reads as a missing feature. Keep both
  // visible and say why they are inactive instead.
  // 控件直接消失会被当成功能丢了；保持可见并说明不可用的原因。
  const backingInfillDisabledReason = modelSurfaceEnabled
    ? t("basic_backing_infill_disabled_model_surface")
    : enable_relief
      ? t("basic_backing_infill_disabled_relief")
      : null;
  const structureModeDisabledReason = modelSurfaceEnabled
    ? t("basic_structure_mode_disabled_model_surface")
    : enable_relief
      ? t("basic_structure_mode_disabled_relief")
      : enable_fridge_magnet
        ? t("basic_structure_mode_disabled_fridge_magnet")
        : null;

  return (
    <div className="flex flex-col gap-4">
      <Block label={t("basic_group_input")} tutorial="image-upload">
        <div hidden={!uploaderExpanded}>
          <UnifiedUploader
            singlePreview={imagePreviewUrl ?? undefined}
            batchFiles={batchFiles}
            isBatchMode={batchMode}
            onFilesSelect={handleFilesSelect}
            onFileReplace={handleFileReplace}
            onBatchFileRemove={removeBatchFile}
            accept={ACCEPT_IMAGE_FORMATS}
            onShareCardDetected={(file) => void handleShareCardDetected(file)}
          />
        </div>
        {!uploaderExpanded && (
          <button
            type="button"
            onClick={() => setUploaderExpanded(true)}
            className="flex items-center gap-2 rounded-2xl border border-slate-200/80 bg-slate-100/70 px-3 py-2 text-left transition-colors hover:bg-slate-100/90 dark:border-slate-700/60 dark:bg-slate-900/50 dark:hover:bg-slate-900/80"
          >
            {imagePreviewUrl && (
              <img
                src={imagePreviewUrl}
                alt=""
                className="h-8 w-8 shrink-0 rounded-lg object-cover"
              />
            )}
            <span className="min-w-0 flex-1 truncate text-[clamp(0.65rem,0.85vw,0.75rem)] text-slate-600 dark:text-slate-300">
              {imageFile?.name ?? t("upload_unified_hint")}
            </span>
            <span className="shrink-0 text-[10px] text-slate-400 dark:text-slate-500">
              {t("upload_tap_to_change")}
            </span>
          </button>
        )}

        {workshopSource ? (
          <WorkshopSourceBanner
            source={workshopSource}
            colorLibrary={workshopColorLibrary}
            colorLibrarySelectionKey={
              workshopColorLibrarySelectionKey
            }
          />
        ) : null}

        {batchFiles.length === 0 && (
          <div className="flex flex-col gap-3">
            {imageFile !== null && (
              <Button
                label={t("basic_crop_image")}
                leadingIcon={<ScissorsIcon className="size-4" />}
                variant="secondary"
                size="sm"
                onClick={() => setCropModalOpen(true)}
                disabled={!imagePreviewUrl || isLoading || isCropping}
              />
            )}
            <Checkbox
              label={t("basic_crop_after_upload")}
              tooltip={t("basic_crop_after_upload_hint")}
              wikiPath={WIKI_DOCS.imageInputAndCrop}
              checked={enableCrop}
              onChange={setEnableCrop}
            />

          </div>
        )}

        <CropModal
          open={cropModalOpen}
          imageSrc={imagePreviewUrl ?? ""}
          allowCrop={!isSvgImageFile(imageFile)}
          onConfirm={handleCropConfirm}
          onUseOriginal={() => setCropModalOpen(false)}
          onClose={() => setCropModalOpen(false)}
          isLoading={isCropping || isLoading}
        />
      </Block>

      <ConversionPresets />

      <Block label={t("basic_group_color_source")} tutorial="color-source" className="gap-5">
        <RadioGroup
          label={t("basic_source_version_label")}
          tooltip={t("basic_source_version_hint")}
          wikiPath={WIKI_DOCS.sourceType}
          value={source_version}
          options={sourceVersionOptions}
          onChange={(value) => setSourceVersion(value as "legacy" | "material")}
        />

        {source_version === "material" ? (
          <div className="flex min-w-0 flex-col gap-5">
            <div data-tutorial="material-picker" className="flex min-w-0 flex-col gap-2">
              <label htmlFor="basic-material-picker" className={workstationFieldLabelClass}>{t("basic_material_select_label")}</label>

              <button
                type="button"
                onClick={() => setMaterialPickerOpen(true)}
                id="basic-material-picker"
                data-testid="material-picker-trigger"
                className={`${workstationInputClass} flex h-auto min-h-10 flex-col items-stretch gap-2 py-2.5 text-left`}
              >
                <span className="flex items-center justify-between gap-3">
                  {materialSummary === null ? (
                    <span className="text-slate-400 dark:text-slate-500">
                      {t("basic_material_picker_open")}
                    </span>
                  ) : (
                    <span
                      className="inline-flex flex-wrap items-center gap-1"
                      data-testid="material-picker-summary-dots"
                      aria-hidden="true"
                    >
                      {materialSummary.map((item) => (
                        <span
                          key={item.dirName}
                          className={`${MATERIAL_DOT_CLS} size-3`}
                          style={item.color ? { backgroundColor: item.color } : undefined}
                        />
                      ))}
                    </span>
                  )}
                  <span className="shrink-0 text-xs text-slate-400 dark:text-slate-500">
                    {t("basic_material_selected_count")}: {selectedMaterialDirNames.length}
                  </span>
                </span>
                {materialSummary !== null && (
                  <span
                    className="grid grid-cols-2 gap-x-3 gap-y-1.5"
                    data-testid="material-picker-summary-list"
                  >
                    {materialSummary.map((item) => (
                      <span
                        key={item.dirName}
                        className="flex min-w-0 items-start gap-1.5 text-xs font-medium leading-4 text-slate-700 dark:text-slate-200"
                        title={item.name}
                      >
                        <span
                          aria-hidden="true"
                          className={`${MATERIAL_DOT_CLS} mt-[3px]`}
                          style={item.color ? { backgroundColor: item.color } : undefined}
                        />
                        {/* Wrap long names instead of cutting them off. 长名称换行而不是截断。 */}
                        <span className="min-w-0 break-words">{item.name}</span>
                      </span>
                    ))}
                  </span>
                )}
              </button>

              <MaterialPickerDialog
                open={materialPickerOpen}
                materials={materialLibrary}
                loading={materialLibraryLoading}
                loadError={materialLibraryLoadError}
                initialSelected={selectedMaterialDirNames}
                onConfirm={handleMaterialPickerConfirm}
                onCancel={() => setMaterialPickerOpen(false)}
                onRetry={retryMaterialLibraryLoad}
              />
            </div>
            <div className="flex min-w-0 flex-col gap-3">
              <div data-tutorial="material-layer-height" className="min-w-0">
                <Dropdown
                  label={t("basic_material_layer_height_label")}
                  tooltip={t("basic_material_layer_height_hint")}
                  wikiPath={WIKI_DOCS.materialArchiveSource}
                  value={String(materialLayerHeightMm)}
                  options={materialLayerHeightOptions}
                  onChange={(v) => setMaterialLayerHeightMm(Number(v))}
                />
              </div>

              <div data-tutorial="material-layer-count" className="flex min-w-0 flex-col gap-3">
                <Checkbox
                  label={t("basic_material_dynamic_layer_count_label")}
                  tooltip={t("basic_material_dynamic_layer_count_hint")}
                  wikiPath={WIKI_DOCS.materialArchiveSource}
                  checked={materialDynamicLayerCountEnabled}
                  onChange={setMaterialDynamicLayerCountEnabled}
                />

                {materialDynamicLayerCountEnabled ? (
                  <>
                    <Slider
                      label={t("basic_material_min_layer_count_label")}
                      tooltip={t("basic_material_min_layer_count_hint")}
                      wikiPath={WIKI_DOCS.materialArchiveSource}
                      value={materialMinLayerCount}
                      min={MATERIAL_DYNAMIC_LAYER_COUNT_MIN}
                      max={MATERIAL_DYNAMIC_LAYER_COUNT_MAX}
                      step={1}
                      onChange={(v) => setMaterialMinLayerCount(Math.round(v))}
                    />
                    <Slider
                      label={t("basic_material_max_layer_count_label")}
                      tooltip={t("basic_material_max_layer_count_hint")}
                      wikiPath={WIKI_DOCS.materialArchiveSource}
                      value={materialMaxLayerCount}
                      min={MATERIAL_DYNAMIC_LAYER_COUNT_MIN}
                      max={MATERIAL_DYNAMIC_LAYER_COUNT_MAX}
                      step={1}
                      onChange={(v) => setMaterialMaxLayerCount(Math.round(v))}
                    />
                  </>
                ) : (
                  <Slider
                    label={t("basic_material_layer_count_label")}
                    tooltip={t("basic_material_layer_count_hint")}
                    wikiPath={WIKI_DOCS.materialArchiveSource}
                    value={materialLayerCount}
                    min={5}
                    max={10}
                    step={1}
                    onChange={(v) => setMaterialLayerCount(Math.round(v))}
                  />
                )}
              </div>
            </div>
            <div className="flex min-w-0 flex-col gap-3">
              <div data-tutorial="material-backing" className="min-w-0">
                <Dropdown
                  label={t("basic_material_backing_label")}
                  tooltip={t("basic_material_backing_hint")}
                  wikiPath={WIKI_DOCS.materialArchiveSource}
                  value={resolvedMaterialBackingDirName}
                  options={materialBackingOptions}
                  onChange={(v) => setMaterialBackingMaterialDirName(v || null)}
                  disabled={selectedMaterialDirNames.length === 0}
                  placeholder={t("basic_material_backing_placeholder")}
                />
              </div>

              {!materialDynamicLayerCountEnabled && (
                <MaterialSolverCacheDialog
                  materialDirectoryNames={selectedMaterialDirNames}
                  layerCount={materialLayerCount}
                  layerHeightMm={materialLayerHeightMm}
                />
              )}
            </div>
          </div>
        ) : source_version === "legacy" && !isPredictiveLutSource(selectedLutInfo?.source_kind) ? (
          <div className="flex min-w-0 flex-col gap-5">
            <LegacyLutSelector
              manufacturer={selectedLegacyManufacturer}
              lutName={lut_name}
              selectedLutNames={lut_names.length > 0 ? lut_names : (lut_name ? [lut_name] : [])}
              manufacturerOptions={manufacturerOptions}
              groupedLutOptions={groupedLutOptions}
              allLutOptions={allLegacyLutOptions}
              brandInfo={selectedLegacyBrandInfo}
              colorModeSummary={lut_name ? (
                <span className="inline-flex items-center gap-1.5">
                  <ColorModeDots mode={color_mode} />
                  <span>{color_mode}</span>
                </span>
              ) : undefined}
              onManufacturerChange={setLegacyManufacturer}
              onLutChange={setLutName}
              onLutSelectionChange={setLegacyLutNames}
              onRefresh={() => void handleRefreshLut()}
              onUploadClick={() => lutFileRef.current?.click()}
              loading={legacyCatalogLoading}
              lutLoading={lutListLoading}
              refreshing={isRefreshingLut}
              labels={{
                manufacturer: t("basic_lut_manufacturer_label"),
                manufacturerPlaceholder: t("basic_lut_manufacturer_placeholder"),
                lutPlaceholder: t("basic_lut_lut_placeholder"),
                refreshTooltip: t("basic_lut_refresh_tooltip"),
                upload: `+ ${t("basic_lut_upload")}`,
                loadingHint: t("basic_brand_loading"),
                noBrandHint: t("basic_lut_no_brand_hint"),
                selectedCount: t("basic_lut_selected_count"),
                brandInfo: t("basic_native_brand_summary_label"),
                materialType: t("basic_native_material_label"),
                vendor: t("basic_native_vendor_label"),
                dialogTitle: t("basic_lut_picker_title"),
                dialogSearchPlaceholder: t("basic_lut_picker_search_placeholder"),
                dialogAllGroups: t("basic_lut_picker_all_groups"),
                dialogNoMatch: t("basic_lut_picker_no_match"),
                dialogDeselectAll: t("basic_lut_picker_deselect_all"),
                dialogConfirm: t("basic_lut_picker_confirm"),
                dialogCancel: t("basic_lut_picker_cancel"),
                openPicker: t("basic_lut_picker_open"),
                change: t("basic_lut_picker_change"),
                selectionSummary: t("basic_lut_picker_selection_summary"),
                moreSelected: t("basic_lut_picker_more_selected"),
              }}
            />
            <input
              ref={lutFileRef}
              type="file"
              accept=".npy,.json,.npz,.msgpack"
              className="hidden"
              onChange={(e) => void handleLutUpload(e)}
            />

            {lut_name && selectedLutInfo && supportsDynamicLayers && (
              <div className="flex min-w-0 flex-col gap-3">
                <Slider
                  label={t("basic_color_layers_label")}
                  tooltip={t("basic_color_layers_hint")}
                  wikiPath={WIKI_DOCS.legacyLutSource}
                  value={color_layers ?? selectedLutInfo.max_color_layers ?? 5}
                  min={1}
                  max={10}
                  step={1}
                  onChange={(value) => setColorLayers(Math.round(value))}
                />
                <Dropdown
                  label={t("basic_layer_height_label")}
                  tooltip={t("basic_layer_height_hint")}
                  wikiPath={WIKI_DOCS.legacyLutSource}
                  value={String(layer_height_mm ?? selectedLutInfo.layer_height_mm ?? 0.08)}
                  options={supportedLayerHeightOptions}
                  onChange={(value) => setLayerHeightMm(Number(value))}
                />
                {supportedModes.length > 0 && (
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {t("basic_supported_modes_label")}:{" "}
                    {supportedModes
                      .map((mode) => `${mode.color_layers}L @ ${mode.layer_height_mm.toFixed(2)}mm`)
                      .join(", ")}
                  </p>
                )}
              </div>
            )}
          </div>
        ) : null}

        <QuantizeColorsControl />
      </Block>

      <Block label={t("basic_block_size_and_base_plate")} className="gap-y-4">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-3">
            <div data-tutorial="output-size" className="flex flex-col gap-3">
              <Slider
                className="gap-y-1"
                label={t("basic_width")}
                tooltip={t("basic_width_hint")}
                wikiPath={WIKI_DOCS.outputDimensions}
                value={target_width_mm}
                min={10}
                max={dimensionLimits.width}
                inputMax={dimInputMax}
                step={dimensionSliderStep(target_width_mm)}
                displayDecimals={1}
                unit="mm"
                onChange={setTargetWidthMm}
              />

              <Slider
                className="gap-y-1"
                label={t("basic_height")}
                tooltip={t("basic_height_hint")}
                wikiPath={WIKI_DOCS.outputDimensions}
                value={target_height_mm}
                min={10}
                max={dimensionLimits.height}
                inputMax={dimInputMax}
                step={dimensionSliderStep(target_height_mm)}
                displayDecimals={1}
                unit="mm"
                onChange={setTargetHeightMm}
              />
            </div>

            <Slider
              className="gap-y-1"
              label={t("basic_thickness")}
              tooltip={t("basic_thickness_hint")}
              wikiPath={WIKI_DOCS.backingThickness}
              value={spacer_thick}
              min={THICKNESS_SLIDER_MIN_MM}
              max={THICKNESS_SLIDER_MAX_MM}
              step={THICKNESS_LAYER_STEP_MM}
              unit="mm"
              onChange={setSpacerThick}
              normalizeTextValue={snapThicknessToLayerGrid}
            />

            <Slider
              className="gap-y-1"
              label={t("basic_backing_infill_density")}
              tooltip={t("basic_backing_infill_density_hint")}
              wikiPath={WIKI_DOCS.backingThickness}
              value={backing_infill_density_percent}
              min={BACKING_INFILL_DENSITY_MIN_PERCENT}
              max={BACKING_INFILL_DENSITY_MAX_PERCENT}
              step={BACKING_INFILL_DENSITY_STEP_PERCENT}
              unit="%"
              onChange={setBackingInfillDensityPercent}
              disabled={modelSurfaceEnabled || enable_relief}
            />
            {backingInfillDisabledReason && (
              <p className="-mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {backingInfillDisabledReason}
              </p>
            )}
          </div>

          <div className="[&>div]:py-1">
            <Checkbox
              label={t("basic_large_format")}
              checked={largeFormatEnabled}
              onChange={setLargeFormatEnabled}
              disabled={puzzleEnabled || enable_fridge_magnet || (modelSurfaceEnabled && !largeFormatEnabled)}
              tooltip={t("basic_large_format_hint")}
              wikiPath={WIKI_DOCS.largeFormat}
            />
          </div>
        </div>

        {puzzleEnabled && !largeFormatEnabled && (
          <p className="-mt-2 px-1 text-xs text-slate-500 dark:text-slate-400">
            {t("puzzle_large_format_disabled_hint")}
          </p>
        )}

        {modelSurfaceEnabled && !largeFormatEnabled && !puzzleEnabled && (
          <p className="-mt-2 px-1 text-xs text-slate-500 dark:text-slate-400">
            {t("model_surface_large_format_disabled_hint")}
          </p>
        )}

        {largeFormatModelSurfaceConflict && (
          <StatusBanner tone="warning">
            <p data-testid="large-format-model-surface-conflict">
              {t("large_format_model_surface_conflict")}
            </p>
          </StatusBanner>
        )}

        {mergedLargeFormatWarnings.length > 0 ? (
          <StatusBanner tone="warning">
            <div className="flex flex-col gap-1">
              {mergedLargeFormatWarnings.map((warning) => (
                <p key={warning}>{warning}</p>
              ))}
            </div>
          </StatusBanner>
        ) : null}

        {largeFormatEnabled && (
          <div className={dependentGroupClass}>
            <Slider
              label={t("basic_tile_width")}
              tooltip={t("basic_tile_width_hint")}
              wikiPath={WIKI_DOCS.largeFormat}
              value={tileWidthMm}
              min={50}
              max={LARGE_FORMAT_TILE_SLIDER_MAX_MM}
              inputMax={Number.POSITIVE_INFINITY}
              step={10}
              unit="mm"
              onChange={setTileWidthMm}
            />
            <Slider
              label={t("basic_tile_height")}
              tooltip={t("basic_tile_height_hint")}
              wikiPath={WIKI_DOCS.largeFormat}
              value={tileHeightMm}
              min={50}
              max={LARGE_FORMAT_TILE_SLIDER_MAX_MM}
              inputMax={Number.POSITIVE_INFINITY}
              step={10}
              unit="mm"
              onChange={setTileHeightMm}
            />
            {tileGrid && (
              <p className="px-1 text-xs text-slate-500 dark:text-slate-400">
                {tileGrid.cols}×{tileGrid.rows} = {tileGrid.total}
                {tileGrid.total > 1 && (tileGrid.lastW !== tileWidthMm || tileGrid.lastH !== tileHeightMm)
                  ? ` (${tileGrid.lastW}×${tileGrid.lastH}mm)`
                  : ""}
              </p>
            )}
            <Checkbox
              label={t("basic_large_format_show_tiles")}
              checked={largeFormatTileOverlayVisible}
              onChange={setLargeFormatTileOverlayVisible}
              tooltip={t("basic_large_format_show_tiles_hint")}
            />
          </div>
        )}
      </Block>

      <Block>
        <RadioGroup
          label={t("basic_structure_mode")}
          tooltip={t("basic_structure_mode_hint")}
          wikiPath={WIKI_DOCS.structureMode}
          value={structure_mode}
          options={structureModeOptions}
          columns={2}
          onChange={(v) => setStructureMode(v as StructureMode)}
          disabled={structureModeDisabledReason !== null}
          disabledValues={isFiveColorExt ? [StructureMode.DOUBLE_SIDED] : []}
        />
        {structureModeDisabledReason && (
          <p className="-mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {structureModeDisabledReason}
          </p>
        )}
        {isFiveColorExt && (
          <p className="-mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {t("basic_structure_mode_five_color_hint")}
          </p>
        )}
      </Block>

      <Block>
        <RadioGroup
          label={t("basic_modeling_mode")}
          tooltip={t("basic_modeling_mode_hint")}
          wikiPath={WIKI_DOCS.modelingMode}
          value={modeling_mode}
          options={modelingModeOptions}
          columns={2}
          onChange={(v) => setModelingMode(v as ModelingMode)}
          disabledValues={disabledModelingModes}
        />
      </Block>

      <ImportConfirmDialog
        open={importDialogOpen}
        preview={importPreview}
        source={importSource}
        onConfirm={handleImportConfirm}
        onContinueEditing={handleImportContinueEditing}
        onCancel={handleImportCancel}
        isLoading={importLoading}
      />
    </div>
  );
}

function QuantizeColorsControl() {
  const { t } = useI18n();
  const quantize_colors = useConverterStore((s) => s.quantize_colors);
  const quantize_colors_unlocked = useConverterStore((s) => s.quantize_colors_unlocked);
  const imageFile = useConverterStore((s) => s.imageFile);
  const autoDetectLoading = useConverterStore((s) => s.autoDetectColorsLoading);
  const setQuantizeColors = useConverterStore((s) => s.setQuantizeColors);
  const autoDetectColors = useConverterStore((s) => s.autoDetectColors);
  const upperBound = quantize_colors_unlocked ? 8192 : 256;
  // Step must divide (upperBound - min=8) so the slider can reach the
  // declared ceiling. (8192 - 8) is divisible by 8 but not by 32, hence
  // step=8 even in unlocked mode to keep 8192 reachable; otherwise the
  // slider would max out at 8168.
  // 步长必须能整除 (upperBound - min=8)，否则滑条到不了声明的上限。
  // (8192 - 8) 能被 8 整除但不能被 32 整除，所以解锁后仍用 step=8，
  // 不然滑条只能停在 8168。
  const step = 8;

  return (
    <div className="flex flex-col gap-2">
      <Slider
        label={t("adv_quantize_colors")}
        tooltip={t("adv_quantize_colors_hint")}
        wikiPath={WIKI_DOCS.quantizeColors}
        value={quantize_colors}
        min={8}
        max={upperBound}
        step={step}
        onChange={setQuantizeColors}
      />
      <Button
        label={autoDetectLoading ? t("conv_auto_color_calculating") : t("conv_auto_color_btn")}
        variant="secondary"
        size="sm"
        onClick={autoDetectColors}
        disabled={!imageFile || autoDetectLoading}
        loading={autoDetectLoading}
        className="self-end"
      />
    </div>
  );
}
