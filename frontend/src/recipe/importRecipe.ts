/**
 * Recipe import adapter: parses recipe files and maps back to converter store state.
 * 配方导入适配器：解析配方文件并映射回 converter store 状态。
 */

import type {
  AssetEntry,
  ConverterRecipeSource,
  LutReference,
  LuminaRecipe,
} from "./types";
import { DEFAULT_CONVERTER_RECIPE_PUZZLE, EDITOR_PROJECT_MAX_BYTES, WORKSHOP_RECIPE_ENVELOPE_MAX_BYTES } from "./types";
import {
  DEFAULT_MODEL_SURFACE_MODEL_ROTATION,
  DEFAULT_MODEL_SURFACE_PLACEMENT,
  MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
  type ConverterState,
} from "../stores/converter/store";
import type {
  ColorReplacementItem,
  FridgeMagnetItem,
  LutInfo,
  RecipeHistoryItem,
} from "../api/types";
import { extractRecipeFromPng } from "./pngMetadata";
import { migrateRecipe } from "./migration";
import { base64ToFile } from "./utils";
import {
  normalizeFridgeMagnetItems,
  resolveFridgeMagnetSpacerThick,
} from "../constants/fridgeMagnets";
import { restoreImportedDynamicMaterialMetadata } from "./dynamicMaterialMetadata";
import type { WorkshopRecipeSource } from "../workshop/types";
import {
  svgHoleCompensationOptions,
  validSvgHoleCompensationOptions,
} from "../constants/svgHoleCompensation";
import { tRuntime } from "../i18n/runtime";

// ========== Hex normalization ==========

/** Strip '#' prefix from a hex color string. */
function stripHash(hex: string): string {
  return hex.startsWith("#") ? hex.slice(1) : hex;
}

function cloneVirtualMaterials(
  materials: Array<{ name: string; hex: string }> | undefined,
): Array<{ name: string; hex: string }> | undefined {
  if (!materials || materials.length === 0) {
    return undefined;
  }
  return materials.map((material) => ({
    name: material.name,
    hex: material.hex,
  }));
}

function normalizeBackingInfillDensityPercent(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 100;
  }
  return Math.min(100, Math.max(5, Math.round(value)));
}

function normalizeImportedDynamicLayerCount(
  value: unknown,
  fallback: number,
): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(
    MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
    Math.max(MATERIAL_DYNAMIC_LAYER_COUNT_MIN, Math.round(value)),
  );
}

function resolveImportedDynamicLayerBounds(
  source: ConverterRecipeSource | undefined,
): { minimum: number; maximum: number } {
  const minimum = normalizeImportedDynamicLayerCount(
    source?.material_min_layer_count,
    MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
  );
  const maximum = normalizeImportedDynamicLayerCount(
    source?.material_max_layer_count,
    MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  );
  return {
    minimum: Math.min(minimum, maximum),
    maximum: Math.max(minimum, maximum),
  };
}

// ========== Source detection ==========

export type RecipeFileSource = "png" | "json";

export const RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_PUZZLE =
  "recipe_import_warning_fridge_conflict_puzzle";
export const RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LARGE_FORMAT =
  "recipe_import_warning_fridge_conflict_large_format";
export const RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LOOP =
  "recipe_import_warning_fridge_conflict_loop";
export const RECIPE_IMPORT_WARNING_LUT_DEGRADED =
  "recipe_import_lut_degraded";
export const RECIPE_IMPORT_WARNING_LUT_MISSING =
  "recipe_import_lut_missing";
export const RECIPE_IMPORT_WARNING_SECONDARY_LUT_MISSING =
  "recipe_import_warning_secondary_lut_missing";
export const RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LARGE_FORMAT =
  "recipe_import_warning_puzzle_conflict_large_format";
export const RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LOOP =
  "recipe_import_warning_puzzle_conflict_loop";
export const RECIPE_IMPORT_WARNING_BACK_LABELS_UNAVAILABLE =
  "recipe_import_warning_back_labels_unavailable";
export const RECIPE_IMPORT_WARNING_SPATIAL_EDITS_NOT_SERIALIZED =
  "recipe_import_warning_spatial_edits_not_serialized";
export const RECIPE_IMPORT_WARNING_REGION_RECIPES_NOT_RESTORED =
  "recipe_import_warning_region_recipes_not_restored";
export const RECIPE_IMPORT_WARNING_WORKSHOP_DEGRADED =
  "recipe_import_workshop_degraded";

export const RECIPE_IMPORT_NOT_SHARE_CARD_ERROR =
  "PNG file does not contain Lumina recipe metadata";
export const RECIPE_ASSET_CORRUPT_ERROR =
  "Asset data is corrupted — unable to restore original file";
const WORKSHOP_MODULE_ID_PATTERN =
  /^[a-z0-9]+(?:[.-][a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)*$/;
const WORKSHOP_SEMVER_PATTERN =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

function isRecord(
  value: unknown,
): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function hasWorkshopRecipeEnvelopeShape(
  value: unknown,
): value is WorkshopRecipeSource {
  if (!isRecord(value)) {
    return false;
  }
  return (
    value.manifestSchemaVersion === 1 &&
    typeof value.moduleId === "string" &&
    WORKSHOP_MODULE_ID_PATTERN.test(value.moduleId) &&
    typeof value.moduleVersion === "string" &&
    WORKSHOP_SEMVER_PATTERN.test(value.moduleVersion) &&
    isNonEmptyString(value.projectSchemaVersion) &&
    isNonEmptyString(value.renderSchemaVersion) &&
    isRecord(value.payload)
  );
}

/**
 * Validate a share-card envelope without loading or trusting module code.
 * The installed sandboxed module owns payload validation and migration.
 *
 * 不加载、不信任模块代码地校验分享卡信封；payload 的完整校验和迁移由
 * 已安装的沙箱模块负责。
 */
export function validateWorkshopRecipeEnvelope(
  value: unknown,
): WorkshopRecipeSource | null {
  if (!hasWorkshopRecipeEnvelopeShape(value)) {
    return null;
  }
  try {
    const serialized = JSON.stringify(value);
    if (
      new TextEncoder().encode(serialized).byteLength >
      WORKSHOP_RECIPE_ENVELOPE_MAX_BYTES
    ) {
      return null;
    }
    const cloned = JSON.parse(serialized) as unknown;
    return hasWorkshopRecipeEnvelopeShape(cloned)
      ? cloned
      : null;
  } catch {
    return null;
  }
}

/**
 * Detect a candidate PNG or JSON recipe container; parsing validates its content.
 * 检测候选 PNG 或 JSON 项目容器；内容是否有效由解析步骤校验。
 */
export function detectRecipeFileType(file: File): RecipeFileSource | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".json")) return "json";
  if (name.endsWith(".png") && file.type === "image/png") return "png";
  // Also accept PNG files without explicit type (some OS don't set MIME)
  if (name.endsWith(".png")) return "png";
  return null;
}

// ========== Parse entry ==========

export interface ParsedRecipe {
  recipe: LuminaRecipe;
  source: RecipeFileSource;
}

/**
 * Parse a recipe from a file (PNG or JSON).
 * 从文件（PNG 或 JSON）中解析配方。
 *
 * @throws Error if the file cannot be parsed or contains invalid recipe data.
 */
export async function parseRecipeFile(file: File): Promise<ParsedRecipe> {
  const fileType = detectRecipeFileType(file);

  if (fileType === "json") {
    const text = await file.text();
    let raw: unknown;
    try {
      raw = JSON.parse(text);
    } catch {
      throw new Error("Invalid .lumina.json: failed to parse JSON");
    }
    const recipe = migrateRecipe(raw);
    validateRecipeAssets(recipe);
    return { recipe, source: "json" };
  }

  if (fileType === "png") {
    const recipe = await extractRecipeFromPng(file);
    if (!recipe) {
      throw new Error(RECIPE_IMPORT_NOT_SHARE_CARD_ERROR);
    }
    const migrated = migrateRecipe(recipe);
    validateRecipeAssets(migrated);
    return { recipe: migrated, source: "png" };
  }

  throw new Error(`Unsupported file type: ${file.name}`);
}

function validateRecipeAssets(recipe: LuminaRecipe): void {
  const assetEntries = recipe.asset;
  validateAsset(assetEntries?.primary);
  const relief = recipe.recipe.converter?.relief;
  if (relief?.enable_relief && relief.auto_height_mode === "use-heightmap" && !assetEntries.heightmap) {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  }
  if (assetEntries?.heightmap !== undefined) {
    validateAsset(assetEntries.heightmap);
  }
  if (assetEntries?.editor !== undefined) {
    if (assetEntries.editor.byte_size > EDITOR_PROJECT_MAX_BYTES
        || assetEntries.editor.payload_b64?.length > Math.ceil(EDITOR_PROJECT_MAX_BYTES / 3) * 4) {
      throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
    }
    validateAsset(assetEntries.editor);
  }
}

function validateAsset(
  asset: AssetEntry | undefined,
): void {
  if (
    !asset ||
    asset.encoding !== "base64" ||
    typeof asset.payload_b64 !== "string" ||
    !isNonEmptyString(asset.filename) ||
    !isNonEmptyString(asset.mime_type) ||
    !Number.isSafeInteger(asset.byte_size) ||
    asset.byte_size < 0
  ) {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  }

  let file: File;
  try {
    file = base64ToFile(
      asset.payload_b64,
      asset.filename,
      asset.mime_type,
    );
  } catch {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  }

  if (file.size !== asset.byte_size) {
    throw new Error(RECIPE_ASSET_CORRUPT_ERROR);
  }

}

// ========== LUT matching ==========

export type LutMatchResult =
  | { matched: true; lutName: string; matchType: "record" | "name" }
  | { matched: false; originalName: string };

/**
 * Match a LUT reference against the locally available LUT list.
 * 将 LUT 引用与本地可用的 LUT 列表匹配。
 *
 * Prefer the existing record path, then a unique name and color mode.
 * 优先使用已有记录路径，其次匹配唯一名称与颜色模式。
 */
export function matchLut(
  lutRef: LutReference,
  localLuts: LutInfo[],
): LutMatchResult {
  const compatible = localLuts.filter((lut) => lut.color_mode === lutRef.color_mode);
  const byRecord = lutRef.path_hint
    ? compatible.filter((lut) => lut.path === lutRef.path_hint)
    : [];
  const candidates = byRecord.length > 0
    ? byRecord
    : compatible.filter((lut) => lut.name === lutRef.name);
  const candidate = candidates[0];
  // Converter selection is name-based; a duplicate name cannot restore safely.
  if (candidates.length !== 1 || localLuts.filter((lut) => lut.name === candidate.name).length !== 1) {
    return { matched: false, originalName: lutRef.name };
  }
  return {
    matched: true,
    lutName: candidate.name,
    matchType: byRecord.length > 0 ? "record" : "name",
  };
}

function normalizeStringList(values: string[] | undefined): string[] {
  const seen = new Set<string>();
  return (values ?? []).filter((value) => {
    const trimmed = value.trim();
    if (!trimmed || seen.has(trimmed)) {
      return false;
    }
    seen.add(trimmed);
    return true;
  });
}

function restoreLegacyLutNames(
  primaryName: string,
  selectedNames: string[] | undefined,
  localLuts: LutInfo[],
): { names: string[]; missingSecondary: boolean } {
  if (!primaryName) {
    return { names: [], missingSecondary: false };
  }

  const normalized = normalizeStringList(selectedNames);
  const secondaryNames = normalized.slice(1);
  const names = [primaryName];
  let missingSecondary = false;
  for (const name of secondaryNames) {
    if (name === primaryName || names.includes(name)) {
      continue;
    }
    if (localLuts.filter((lut) => lut.name === name).length === 1) {
      names.push(name);
    } else {
      missingSecondary = true;
    }
  }
  return { names, missingSecondary };
}

// ========== Restore result ==========

export interface RestoreResult {
  /** Partial state to merge into converter store. */
  state: Partial<ConverterState>;
  /** Restored primary asset as a File object. */
  assetFile: File;
  /** Restored heightmap as a File object (if present). */
  heightmapFile: File | null;
  /** Warnings to display to the user. */
  warnings: string[];
  /** The full parsed recipe (for display in confirm dialog). */
  recipe: LuminaRecipe;
}

/**
 * Restore converter state from a parsed LuminaRecipe.
 * 从解析的 LuminaRecipe 恢复 converter 状态。
 *
 * @param recipe - The parsed and migrated LuminaRecipe.
 * @param localLuts - Available LUT list from the store.
 * @returns RestoreResult with partial state, files, and warnings.
 */
export function restoreConverterRecipe(
  recipe: LuminaRecipe,
  localLuts: LutInfo[],
): RestoreResult {
  if (!recipe.recipe.converter) {
    throw new Error("Recipe does not contain converter data");
  }

  const conv = recipe.recipe.converter;
  const svgCompensation = svgHoleCompensationOptions(conv.base);
  if (!validSvgHoleCompensationOptions(svgCompensation)) {
    throw new Error(tRuntime("svg_hole_compensation_invalid"));
  }
  const warnings: string[] = [...recipe.warnings];
  const rawWorkshopSource = recipe.recipe.workshop;
  const workshopSource =
    rawWorkshopSource === undefined
      ? null
      : validateWorkshopRecipeEnvelope(rawWorkshopSource);
  if (
    rawWorkshopSource !== undefined &&
    !workshopSource &&
    !warnings.includes(RECIPE_IMPORT_WARNING_WORKSHOP_DEGRADED)
  ) {
    warnings.push(RECIPE_IMPORT_WARNING_WORKSHOP_DEGRADED);
  }

  // --- Restore primary asset ---
  const primaryAsset = recipe.asset.primary;
  const assetFile = base64ToFile(
    primaryAsset.payload_b64,
    primaryAsset.filename,
    primaryAsset.mime_type,
  );

  // --- Restore heightmap asset ---
  let heightmapFile: File | null = null;
  if (recipe.asset.heightmap) {
    const hm = recipe.asset.heightmap;
    heightmapFile = base64ToFile(hm.payload_b64, hm.filename, hm.mime_type);
  }
  const editor = recipe.asset.editor;
  const pendingEditorProject = editor
    ? base64ToFile(editor.payload_b64, editor.filename, editor.mime_type)
    : null;

  // --- Restore source-specific LUT selection ---
  const source = conv.source;
  const sourceVersion = source?.source_version ?? "legacy";
  let lutName = "";
  let legacyLutNames: string[] = [];
  if (sourceVersion === "legacy") {
    const lutMatch = matchLut(conv.base.lut, localLuts);
    if (lutMatch.matched) {
      lutName = lutMatch.lutName;
      if (lutMatch.matchType === "name" && conv.base.lut.path_hint) {
        warnings.push(RECIPE_IMPORT_WARNING_LUT_DEGRADED);
      }
    } else {
      warnings.push(RECIPE_IMPORT_WARNING_LUT_MISSING);
    }
    const restored = restoreLegacyLutNames(
      lutName,
      source?.selected_legacy_lut_names,
      localLuts,
    );
    legacyLutNames = restored.names;
    if (restored.missingSecondary) {
      warnings.push(RECIPE_IMPORT_WARNING_SECONDARY_LUT_MISSING);
    }
  }
  const dynamicBounds = resolveImportedDynamicLayerBounds(source);
  const dynamicMaterialEnabled =
    source?.source_version === "material" &&
    source.material_dynamic_layer_count_enabled === true;
  const importedDynamicMaterial = restoreImportedDynamicMaterialMetadata(
    conv.material_dynamic,
    dynamicMaterialEnabled,
  );

  // --- Normalize hex values (strip '#' for store) ---
  const replacementRegions: ColorReplacementItem[] =
    conv.color_ops.replacement_regions.map((r) => ({
      quantized_hex: stripHash(r.quantized_hex),
      matched_hex: stripHash(r.matched_hex),
      replacement_hex: stripHash(r.replacement_hex),
      ...(r.source_scope ? { source_scope: r.source_scope } : {}),
    }));

  const freeColorSet = new Set(
    conv.color_ops.free_color_set.map(stripHash),
  );

  // V2+ optional: recipe_overrides (back-compat: missing → empty array)
  const recipeOverrides = (conv.color_ops.recipe_overrides ?? []).map(
    (item) => {
      const virtualMaterials = cloneVirtualMaterials(item.virtual_materials);
      return {
        region_id: item.region_id,
        recipe: [...item.recipe],
        layer_order: item.layer_order,
        ...(virtualMaterials
          ? { virtual_materials: virtualMaterials }
          : {}),
      };
    },
  );
  if (recipeOverrides.length > 0 && !pendingEditorProject) {
    warnings.push(RECIPE_IMPORT_WARNING_REGION_RECIPES_NOT_RESTORED);
  }

  // V2+ optional: custom_recipe_history — fromModel is forced to false on import
  // because we left the original session's forward-model context.
  // 历史条目导入后 fromModel 强制为 false：离开原会话模型上下文后不再保留"来自模型"标记。
  const customRecipeHistory: RecipeHistoryItem[] = (
    conv.color_ops.custom_recipe_history ?? []
  ).map((item) => {
    const virtualMaterials = cloneVirtualMaterials(item.virtual_materials);
    return {
      id: item.id,
      recipe: [...item.recipe],
      layerOrder: item.layer_order,
      predictedRgb: [
        item.predicted_rgb[0],
        item.predicted_rgb[1],
        item.predicted_rgb[2],
      ],
      predictedLab: [
        item.predicted_lab[0],
        item.predicted_lab[1],
        item.predicted_lab[2],
      ],
      hex: item.hex,
      fromModel: false,
      createdAtMs: item.created_at_ms,
      ...(item.display_hexes
        ? { displayHexes: [...item.display_hexes] }
        : {}),
      ...(item.display_labels
        ? { displayLabels: [...item.display_labels] }
        : {}),
      ...(virtualMaterials ? { virtualMaterials } : {}),
    };
  });

  const colorHeightMap: Record<string, number> = {};
  for (const [hex, height] of Object.entries(conv.relief.color_height_map)) {
    colorHeightMap[stripHash(hex)] = height;
  }

  const puzzle = conv.puzzle ?? DEFAULT_CONVERTER_RECIPE_PUZZLE;

  const fridgeMagnet = conv.fridge_magnet ?? {
    enable_fridge_magnet: false,
    fridge_magnets: [],
  };
  const normalizedFridgeMagnets = normalizeFridgeMagnetItems(
    fridgeMagnet.fridge_magnets as FridgeMagnetItem[],
  );

  const fridgeMagnetEnabled = Boolean(fridgeMagnet.enable_fridge_magnet);
  const puzzleEnabled = fridgeMagnetEnabled
    ? false
    : Boolean(puzzle.puzzle_enabled);
  const largeFormatEnabled = fridgeMagnetEnabled
    ? false
    : puzzleEnabled
      ? false
      : conv.large_format.large_format_enabled;
  const addLoop = fridgeMagnetEnabled
    ? false
    : puzzleEnabled
      ? false
      : conv.geometry.add_loop;
  const engraveBackLabels = false;

  if (fridgeMagnetEnabled && puzzle.puzzle_enabled) {
    warnings.push(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_PUZZLE);
  }
  if (fridgeMagnetEnabled && conv.large_format.large_format_enabled) {
    warnings.push(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LARGE_FORMAT);
  }
  if (fridgeMagnetEnabled && conv.geometry.add_loop) {
    warnings.push(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LOOP);
  }
  if (puzzleEnabled && conv.large_format.large_format_enabled) {
    warnings.push(
      RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LARGE_FORMAT,
    );
  }
  if (puzzleEnabled && conv.geometry.add_loop) {
    warnings.push(
      RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LOOP,
    );
  }
  if (puzzle.engrave_back_labels) {
    warnings.push(
      RECIPE_IMPORT_WARNING_BACK_LABELS_UNAVAILABLE,
    );
  }

  // --- Build partial state ---
  const state: Partial<ConverterState> = {
    workshopSource,
    native_filament_profiles: { ...(conv.device.native_filament_profiles ?? {}) },
    nativeFilamentProfileScope: conv.device.native_filament_profiles ? {
      slicer: conv.device.slicer,
      printer_id: conv.device.printer_id,
      device_profile_id: conv.device.device_profile_id ?? "",
      nozzle_size: conv.device.nozzle_size,
    } : null,
    nativeMaterialSelection: null,

    // Model-surface uploads and face selections are session-bound and are not
    // represented by the current recipe schema. Clear every related field so
    // an imported recipe cannot inherit a previously loaded model.
    modelSurfaceEnabled: false,
    modelSurfaceFile: null,
    modelSurfacePreviewUrl: null,
    modelSurfaceModelFileId: null,
    modelSurfaceSummary: null,
    modelSurfaceSelectionId: null,
    modelSurfaceSelection: null,
    modelSurfaceFootprint: null,
    modelSurfaceCandidates: [],
    modelSurfacePlacement: { ...DEFAULT_MODEL_SURFACE_PLACEMENT },
    modelSurfaceModelRotation: { ...DEFAULT_MODEL_SURFACE_MODEL_ROTATION },
    modelSurfaceLoading: false,
    modelSurfaceSelecting: false,
    modelSurfaceError: null,
    modelSurfaceWarnings: [],

    // Base
    source_version: sourceVersion as ConverterState["source_version"],
    lut_name: lutName,
    lut_names: legacyLutNames,
    color_mode: conv.base.color_mode as ConverterState["color_mode"],
    modeling_mode: conv.base.modeling_mode as ConverterState["modeling_mode"],
    target_width_mm: conv.base.target_width_mm,
    target_height_mm: conv.base.target_height_mm,
    quantize_colors: conv.base.quantize_colors,
    quantize_colors_unlocked:
      conv.base.quantize_colors_unlocked ?? conv.base.quantize_colors > 256,
    high_precision_3d_preview: Boolean(conv.base.high_precision_3d_preview),
    enable_cleanup: conv.base.enable_cleanup,
    ...svgCompensation,
    hue_enable: dynamicMaterialEnabled ? false : conv.base.hue_enable,
    use_lut_constrained: Boolean(conv.base.use_lut_constrained),
    auto_dynamic_range: Boolean(conv.base.auto_dynamic_range),
    chroma_gate: conv.base.chroma_gate,
    selectedNativeBrandKey: source?.selected_native_brand_key ?? "",
    selectedNativeDbNames: [...(source?.selected_native_db_names ?? [])],
    color_layers: source?.color_layers ?? null,
    layer_height_mm: source?.layer_height_mm ?? null,
    model_enable: source?.model_enable ?? false,
    model_only: source?.model_only ?? false,
    model_threshold: source?.model_threshold ?? null,
    model_margin: source?.model_margin ?? null,
    selectedMaterialDirNames: [...(source?.selected_material_dir_names ?? [])],
    materialLayerCount: source?.material_layer_count ?? 5,
    materialLayerHeightMm: source?.material_layer_height_mm ?? 0.08,
    materialBackingMaterialDirName: source?.material_backing_material_dir_name ?? null,
    materialDynamicLayerCountEnabled: dynamicMaterialEnabled,
    materialMinLayerCount: dynamicBounds.minimum,
    materialMaxLayerCount: dynamicBounds.maximum,
    // Imported results are historical evidence only. Generation does not
    // consume them; the next successful preview replaces them with current
    // backend results for the imported image/material runtime.
    materialDynamicRecipes: importedDynamicMaterial.recipes,
    materialLayerBenefitCurve: importedDynamicMaterial.benefit_curve,
    materialLayerBenefitScope:
      importedDynamicMaterial.scope ?? "all_printable_pixels",
    materialLayerBenefitPixelCount: importedDynamicMaterial.pixel_count ?? 0,

    // Geometry
    spacer_thick: resolveFridgeMagnetSpacerThick(
      conv.geometry.spacer_thick,
      fridgeMagnetEnabled,
      normalizedFridgeMagnets,
    ),
    base_spacer_thick: conv.geometry.spacer_thick,
    backing_infill_density_percent:
      conv.relief.enable_relief
        ? 100
        : normalizeBackingInfillDensityPercent(
            conv.geometry.backing_infill_density_percent,
          ),
    structure_mode: (
      fridgeMagnetEnabled
        ? "Single-sided"
        : conv.geometry.structure_mode
    ) as ConverterState["structure_mode"],
    separate_backing: conv.geometry.separate_backing,
    backingOutput: conv.geometry.backing_output ?? "same_project",
    add_loop: addLoop,
    loop_width: conv.geometry.loop_width,
    loop_length: conv.geometry.loop_length,
    loop_hole: conv.geometry.loop_hole,
    loop_angle: conv.geometry.loop_angle,
    loop_offset_x: conv.geometry.loop_offset_x,
    loop_offset_y: conv.geometry.loop_offset_y,
    loop_position_preset: conv.geometry.loop_position_preset,

    // Relief
    enable_relief: conv.relief.enable_relief,
    autoHeightMode: conv.relief.auto_height_mode as ConverterState["autoHeightMode"],
    color_height_map: colorHeightMap,
    heightmap_max_height: conv.relief.heightmap_max_height,

    // Outline
    enable_outline: conv.outline.enable_outline,
    outline_width: conv.outline.outline_width,

    // Cloisonne
    enable_cloisonne: conv.cloisonne.enable_cloisonne,
    wire_width_mm: conv.cloisonne.wire_width_mm,
    wire_height_mm: conv.cloisonne.wire_height_mm,

    // Coating
    enable_coating: conv.coating.enable_coating,
    coating_height_mm: conv.coating.coating_height_mm,

    // Color ops
    replacement_regions: replacementRegions,
    free_color_set: freeColorSet,
    // Activate spatial overrides only after the checkpoint has been validated
    // against the new preview's source and working-coordinate grid.
    // 空间覆盖在快照通过新预览的来源和工作坐标校验后才激活。
    recipe_overrides: [],
    pendingEditorProject,
    customRecipeHistory: customRecipeHistory,
    // Clear remap state — replacement_regions already contains merged data
    colorRemapMap: {},
    remapHistory: [],

    // Large format
    largeFormatEnabled: largeFormatEnabled,
    tileWidthMm: conv.large_format.tile_width_mm,
    tileHeightMm: conv.large_format.tile_height_mm,
    puzzleEnabled,
    puzzleStyle: puzzle.puzzle_style as ConverterState["puzzleStyle"],
    puzzleSizingMode: puzzle.puzzle_sizing_mode as ConverterState["puzzleSizingMode"],
    pieceWidthMm: puzzle.piece_width_mm,
    pieceHeightMm: puzzle.piece_height_mm,
    puzzleRows: puzzle.puzzle_rows,
    puzzleCols: puzzle.puzzle_cols,
    targetPieceCount: puzzle.target_piece_count,
    connectorStyle: puzzle.connector_style as ConverterState["connectorStyle"],
    labelsEnabled: puzzle.labels_enabled,
    engraveBackLabels,
    irregularityStrength: puzzle.irregularity_strength,
    minNeckWidthMm: puzzle.min_neck_width_mm,
    enable_fridge_magnet: fridgeMagnetEnabled,
    fridge_magnets: normalizedFridgeMagnets,
    selectedFridgeMagnetId: null,

    // Clear session/preview state (will be rebuilt on next preview)
    sessionId: null,
    previewImageUrl: null,
    previewGlbUrl: null,
    modelUrl: null,
    threemfDiskPath: null,
    downloadUrl: null,
    hasManualPreview: false,
    layerImages: [],
    layerImagesOpen: false,
    layerImagesSourceKey: null,
    regionData: null,
    selectedRegions: [],
    pendingReplacement: null,
    regionReplacementCount: 0,
    error: null,
    puzzleOverlayUrl: null,
    puzzleWarnings: [],
    puzzleResolvedRows: null,
    puzzleResolvedCols: null,
    puzzleResolvedPieceCount: null,
    puzzleDerivedPieceWidthMm: null,
    puzzleDerivedPieceHeightMm: null,
  };

  return {
    state,
    assetFile,
    heightmapFile,
    warnings,
    recipe,
  };
}
