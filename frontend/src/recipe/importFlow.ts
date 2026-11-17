/**
 * Recipe import orchestration: coordinates parsing, restore, and store updates.
 * 配方导入编排：协调解析、恢复和 store 更新。
 */

import { DEFAULT_STATE, isValidImageType, RAW_EXTENSIONS_CONVERTER, useConverterStore } from "../stores/converter";
import { saveGeneratedFile, type SaveOutcome } from "../utils/saveGeneratedFile";
import { useSettingsStore, withExternalSpoolSelection, type NozzleSize } from "../stores/settingsStore";
import { captureProjectSettings, resolveProjectDeviceSettings } from "../stores/converter/project";
import { useWidgetStore } from "../stores/widgetStore";
import { externalSpoolPaletteKey } from "../stores/converter/nativeMaterialSelection";
import { useWorkshopStore } from "../workshop/store";
import { getPrinters, uploadImagePreview, validateHeightmapImage } from "../api/system";
import { HEIGHTMAP_IMAGE_TYPES } from "../constants/heightmap";
import type { PrinterInfo } from "../api/types";
import {
  parseRecipeFile,
  RECIPE_ASSET_CORRUPT_ERROR,
  RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED,
  restoreConverterRecipe,
} from "./importRecipe";
import { hasLuminaRecipe } from "./pngMetadata";
import type { LuminaRecipe } from "./types";
import type { RestoreResult } from "./importRecipe";

const SPATIAL_EDIT_DEGRADED_FIELD =
  "converter.color_ops.spatial_region_edits";
const IMAGE_DECODE_TIMEOUT_MS = 30_000;

export const MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR =
  "Model surface recipes are not supported";

export const RECIPE_IMPORT_PREDICTIVE_LUT_UNAVAILABLE_ERROR =
  "Inferred LUT is currently unavailable";

/**
 * Warn for legacy spatial edits without a portable checkpoint.
 *
 * 旧项目缺少可携带局部编辑快照时，通过既有本地化机制明确提示。
 *
 * @param recipe - Full recipe built for a share PNG or JSON sidecar.
 * @param spatialEditCount - Number of connected-region edits in the session.
 * @returns The same recipe object after compatibility metadata is updated.
 */
export function annotateSpatialEditCompatibility(
  recipe: LuminaRecipe,
  spatialEditCount: number,
): LuminaRecipe {
  if (recipe.asset.editor || !Number.isFinite(spatialEditCount) || spatialEditCount <= 0) {
    return recipe;
  }

  const degradedFields = recipe.compat.degraded_fields ?? [];
  if (!degradedFields.includes(SPATIAL_EDIT_DEGRADED_FIELD)) {
    recipe.compat.degraded_fields = [
      ...degradedFields,
      SPATIAL_EDIT_DEGRADED_FIELD,
    ];
  }
  if (
    !recipe.warnings.includes(
      RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED,
    )
  ) {
    recipe.warnings = [
      ...recipe.warnings,
      RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED,
    ];
  }
  return recipe;
}

// ========== Share card detection ==========

/**
 * Check if a dropped/selected file is a Lumina share card or sidecar.
 * 检查拖放/选择的文件是否为 Lumina 分享卡或 sidecar。
 *
 * @returns true if the file contains a Lumina recipe.
 */
export async function isShareCardFile(file: File): Promise<boolean> {
  const name = file.name.toLowerCase();

  // .lumina.json sidecar
  if (name.endsWith(".lumina.json")) return true;

  // A native save dialog may replace the compound extension with .json.
  if (name.endsWith(".json")) {
    if (file.size > 128 * 1024 * 1024) return false;
    try {
      await parseRecipeFile(file);
      return true;
    } catch {
      return false;
    }
  }

  // PNG with Lumina metadata
  if (name.endsWith(".png")) {
    try {
      return await hasLuminaRecipe(file);
    } catch {
      return false;
    }
  }

  return false;
}

function assertRecipeSourceAvailable(recipe: LuminaRecipe): void {
  if (recipe.recipe.converter?.source?.source_version === "native") {
    throw new Error(RECIPE_IMPORT_PREDICTIVE_LUT_UNAVAILABLE_ERROR);
  }
}

// ========== Import orchestration ==========

export interface ImportPreview {
  recipe: LuminaRecipe;
  restoreResult: RestoreResult;
  /** Blob URL for the cover image preview (must be revoked after use). */
  coverUrl: string | null;
  /** Printer registry snapshot used to reconcile older share cards. */
  printerOptions?: PrinterInfo[];
}

/**
 * Parse a share card file and prepare a preview for the confirmation dialog.
 * 解析分享卡文件，为确认对话框准备预览。
 *
 * This does NOT apply changes to the store — call `applyImport` after user confirms.
 */
export async function prepareImport(file: File): Promise<ImportPreview> {
  const { recipe, source } = await parseRecipeFile(file);
  assertRecipeSourceAvailable(recipe);

  const converterState = useConverterStore.getState();
  const lutListFull = converterState.lutListFull;

  const restoreResult = restoreConverterRecipe(recipe, lutListFull);
  await validateRestoredImage(restoreResult.assetFile);
  if (restoreResult.heightmapFile) {
    await validateRestoredHeightmap(restoreResult.heightmapFile);
  }

  // Build cover preview URL
  let coverUrl: string | null = null;
  if (source === "png") {
    // For PNG share cards, the file itself is the cover image
    coverUrl = URL.createObjectURL(file);
  }

  let printerOptions: PrinterInfo[] = [];
  try {
    printerOptions = await getPrinters();
  } catch {
    printerOptions = [];
  }

  return { recipe, restoreResult, coverUrl, printerOptions };
}

async function validateRestoredHeightmap(file: File): Promise<void> {
  if (!HEIGHTMAP_IMAGE_TYPES.some((mime) => mime === file.type)) {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  }
  const controller = new AbortController();
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    const result = await Promise.race([
      validateHeightmapImage(file, controller.signal),
      new Promise<never>((_, reject) => {
        timeout = setTimeout(() => {
          controller.abort();
          reject(new Error(RECIPE_ASSET_CORRUPT_ERROR));
        }, IMAGE_DECODE_TIMEOUT_MS);
      }),
    ]);
    if (
      !Number.isFinite(result.width) ||
      !Number.isFinite(result.height) ||
      result.width <= 0 || result.height <= 0
    ) {
      throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
    }
  } catch {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}

async function validateRestoredImage(file: File): Promise<void> {
  if (!isValidImageType(file.type, file.name)) {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  }
  const extension = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
  if (RAW_EXTENSIONS_CONVERTER.has(extension) || file.type === "image/heic" || file.type === "image/heif") {
    // These formats already use the backend's optional image decoders.
    await uploadImagePreview(file);
    return;
  }
  const url = URL.createObjectURL(file);
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let image: HTMLImageElement | undefined;
  try {
    image = new Image();
    image.src = url;
    await Promise.race([
      image.decode(),
      new Promise<never>((_, reject) => {
        timeout = setTimeout(() => reject(new Error(RECIPE_ASSET_CORRUPT_ERROR)), IMAGE_DECODE_TIMEOUT_MS);
      }),
    ]);
    if (image.naturalWidth <= 0 || image.naturalHeight <= 0) {
      throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
    }
  } catch {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
    if (image) image.src = "";
    URL.revokeObjectURL(url);
  }
}

/**
 * Revoke a cover URL created during import preview.
 * 释放导入预览时创建的封面 URL。
 */
export function revokeImportCoverUrl(coverUrl: string | null): void {
  if (coverUrl) {
    URL.revokeObjectURL(coverUrl);
  }
}

export interface ApplyImportOptions {
  destination?: "converter" | "workshop";
}

/**
 * Apply a prepared import to the converter store.
 * 将准备好的导入应用到 converter store。
 *
 * This restores all parameters and sets the image file, triggering the
 * normal preview pipeline.
 */
export function applyImport(
  restoreResult: RestoreResult,
  printerOptions: PrinterInfo[] = [],
  options: ApplyImportOptions = {},
): void {
  assertRecipeSourceAvailable(restoreResult.recipe);
  if (restoreResult.state.source_version === "native") {
    throw new Error(RECIPE_IMPORT_PREDICTIVE_LUT_UNAVAILABLE_ERROR);
  }
  const store = useConverterStore.getState();
  const conv = restoreResult.recipe.recipe.converter;

  // Recipes establish their own output settings, just like .lum documents.
  // Resolve everything before committing so old project resources and new
  // parameters can never be observed as one mixed source.
  const defaults = captureProjectSettings(useSettingsStore.getState());
  const projectSettings = conv ? resolveProjectDeviceSettings(defaults, {
    printerModel: conv.device.printer_id || defaults.printerModel,
    slicerSoftware: conv.device.slicer || defaults.slicerSoftware,
    nozzleSize: (conv.device.nozzle_size ?? defaults.nozzleSize) as NozzleSize,
    deviceProfileId: conv.device.device_profile_id ?? "",
    buildPlateId: conv.device.build_plate_id ?? "",
    custom3mfTemplateId: conv.device.custom_3mf_template_id ?? null,
    externalSpoolSelections: withExternalSpoolSelection(
      externalSpoolPaletteKey({ ...DEFAULT_STATE, ...restoreResult.state }), conv.device.external_spool_material,
    ),
    svgPixelsPerMm: conv.base.svg_pixels_per_mm ?? defaults.svgPixelsPerMm,
    materialDeltaE00Tolerance: conv.source?.material_delta_e00_tolerance ?? defaults.materialDeltaE00Tolerance,
    enableBaseLayerHeightModifier: conv.device.enable_base_layer_height_modifier ?? defaults.enableBaseLayerHeightModifier,
    enableWipeTowerAutoPlacement: conv.device.enable_wipe_tower_auto_placement ?? defaults.enableWipeTowerAutoPlacement,
  }, printerOptions) : defaults;
  store.importRecipeState(
    { ...restoreResult.state, projectSettings },
    restoreResult.assetFile,
    restoreResult.heightmapFile,
  );

  // 3. The converter is always restored first. A validated workshop source
  // may then reopen its editor without losing the printable image state.
  // 始终先恢复转换器；随后可用已验证的工坊来源重开编辑器，同时保留可打印图像。
  const workshopSource = restoreResult.state.workshopSource ?? null;
  if (
    options.destination === "workshop" &&
    workshopSource
  ) {
    useWorkshopStore.getState().openRecipe(workshopSource);
    useWidgetStore.getState().setActiveTab("workshop");
    return;
  }
  useWidgetStore.getState().setActiveTab("converter");
}

/**
 * Export the current converter state as a share card PNG (download trigger).
 * 将当前 converter 状态导出为分享卡 PNG（触发下载）。
 */
export async function exportShareCard(): Promise<SaveOutcome> {
  const { state: converterState, editorFile } = await useConverterStore.getState().prepareRecipeExport();
  assertRecipeExportSupported(converterState.modelSurfaceEnabled);

  const { exportConverterRecipe, buildFullRecipe, buildRecipeAssets, buildCoverImage } =
    await import("./exportRecipe");
  const { embedRecipeInPng } = await import("./pngMetadata");

  const settingsState = useSettingsStore.getState();

  // Validate prerequisites
  if (!converterState.imageFile) {
    throw new Error("No image file loaded");
  }
  if (!converterState.previewImageUrl) {
    throw new Error("No preview available — please generate a preview first");
  }

  // Use the existing LUT record reference.
  const lutInfo = converterState.lutListFull.find(
    (l) => l.name === converterState.lut_name,
  );

  // 1. Build converter recipe
  const converterRecipe = exportConverterRecipe(
    converterState,
    settingsState,
    lutInfo?.path,
  );

  // 2. Build assets
  const assets = await buildRecipeAssets(
    converterState.imageFile,
    converterState.heightmapFile,
    editorFile,
  );

  // 3. Build cover image from preview
  const { blob: coverBlob, cover } = await buildCoverImage(
    converterState.previewImageUrl,
  );

  // 4. Build full recipe
  const fullRecipe = annotateSpatialEditCompatibility(
    await buildFullRecipe(
      converterRecipe,
      cover,
      assets,
      converterState.workshopSource,
    ),
    converterState.regionReplacementCount,
  );

  // 5. Embed into PNG
  const shareCardBlob = await embedRecipeInPng(coverBlob, fullRecipe);

  // 6. Trigger download
  const filename = converterState.imageFile.name.replace(/\.[^.]+$/, "") + "-share.png";
  return saveGeneratedFile(shareCardBlob, filename, 'share-card');
}

/**
 * Export the current converter state as a .lumina.json sidecar file.
 * 将当前 converter 状态导出为 .lumina.json sidecar 文件。
 */
export async function exportSidecar(): Promise<SaveOutcome> {
  const { state: converterState, editorFile } = await useConverterStore.getState().prepareRecipeExport();
  assertRecipeExportSupported(converterState.modelSurfaceEnabled);

  const { exportConverterRecipe, buildFullRecipe, buildRecipeAssets, buildCoverImage } =
    await import("./exportRecipe");

  const settingsState = useSettingsStore.getState();

  if (!converterState.imageFile) {
    throw new Error("No image file loaded");
  }
  if (!converterState.previewImageUrl) {
    throw new Error("No preview available — please generate a preview first");
  }

  const lutInfo = converterState.lutListFull.find(
    (l) => l.name === converterState.lut_name,
  );

  const converterRecipe = exportConverterRecipe(
    converterState,
    settingsState,
    lutInfo?.path,
  );

  const assets = await buildRecipeAssets(
    converterState.imageFile,
    converterState.heightmapFile,
    editorFile,
  );

  const { cover } = await buildCoverImage(converterState.previewImageUrl);
  const fullRecipe = annotateSpatialEditCompatibility(
    await buildFullRecipe(
      converterRecipe,
      cover,
      assets,
      converterState.workshopSource,
    ),
    converterState.regionReplacementCount,
  );

  const json = JSON.stringify(fullRecipe, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const filename = converterState.imageFile.name.replace(/\.[^.]+$/, "") + ".lumina.json";
  return saveGeneratedFile(blob, filename, 'project');
}

// ========== Helpers ==========

function assertRecipeExportSupported(modelSurfaceEnabled: boolean): void {
  if (modelSurfaceEnabled) {
    throw new Error(MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR);
  }
}
