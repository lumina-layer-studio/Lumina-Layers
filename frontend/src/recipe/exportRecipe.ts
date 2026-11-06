/**
 * Recipe export adapter: extracts stable parameters from converter store state.
 * 配方导出适配器：从 converter store 状态中提取稳定参数。
 */

import type {
  ConverterRecipe,
  LuminaRecipe,
  LutReference,
  RecipeAssets,
  RecipeCover,
} from "./types";
import { RECIPE_FORMAT, RECIPE_SCHEMA_VERSION } from "./types";
import { buildAssetEntry } from "./utils";
import { colorRemapToReplacementRegions } from "../utils/colorUtils";
import type { ConverterState } from "../stores/converter/store";
import type { SettingsState } from "../stores/settingsStore";
import { resolveConverterSettings } from "../stores/converter/project";
import type { ColorReplacementItem } from "../api/types";
import type { WorkshopRecipeSource } from "../workshop/types";
import { svgHoleCompensationOptions } from "../constants/svgHoleCompensation";
import { scopedNativeFilamentProfiles } from "../stores/converter/nativeMaterialSelection";
import {
  cloneDynamicMaterialRecipe,
  cloneMaterialLayerBenefitCurve,
} from "./dynamicMaterialMetadata";
import {
  MIN_COVER_WIDTH,
  computeFooterLayout,
  drawShareCardFooter,
  getFooterCaption,
  makeCanvasMeasurer,
} from "./shareCardFooter";

// ========== Hex normalization ==========

/** Ensure hex color has '#' prefix. */
function ensureHash(hex: string): string {
  return hex.startsWith("#") ? hex : `#${hex}`;
}

function normalizeLegacyLutNames(state: ConverterState): string[] {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const rawName of state.lut_names.length > 0 ? state.lut_names : [state.lut_name]) {
    const name = rawName.trim();
    if (!name || seen.has(name)) {
      continue;
    }
    seen.add(name);
    names.push(name);
  }
  return names;
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

function virtualMaterialsField(
  materials: Array<{ name: string; hex: string }> | undefined,
): { virtual_materials?: Array<{ name: string; hex: string }> } {
  const cloned = cloneVirtualMaterials(materials);
  return cloned ? { virtual_materials: cloned } : {};
}

function cloneWorkshopRecipeSource(
  source: WorkshopRecipeSource,
): WorkshopRecipeSource {
  return {
    manifestSchemaVersion: source.manifestSchemaVersion,
    moduleId: source.moduleId,
    moduleVersion: source.moduleVersion,
    projectSchemaVersion: source.projectSchemaVersion,
    renderSchemaVersion: source.renderSchemaVersion,
    payload: JSON.parse(
      JSON.stringify(source.payload),
    ) as Record<string, unknown>,
  };
}

// ========== App version ==========

declare const __LUMINA_VERSION__: string | undefined;

function getAppVersion(): string {
  try {
    return typeof __LUMINA_VERSION__ === "string" ? __LUMINA_VERSION__ : "0.0.0";
  } catch {
    return "0.0.0";
  }
}

// ========== Export adapter ==========

/**
 * Build a ConverterRecipe from the current converter store state and settings.
 * 从当前 converter store 状态和设置中构建 ConverterRecipe。
 *
 * @param state - Current ConverterState snapshot.
 * @param settings - Current SettingsState snapshot.
 * @param lutPath - Existing local LUT record path, when available.
 */
export function exportConverterRecipe(
  state: ConverterState,
  defaultSettings: SettingsState,
  lutPath?: string,
): ConverterRecipe {
  const settings = resolveConverterSettings(state, defaultSettings);
  // Merge global-only colorRemapMap entries into global replacement_regions.
  // Local edits use the authoritative checkpoint embedded beside the source.
  // 这里只合并全局映射；局部编辑通过原图旁的权威快照保存。
  let mergedReplacements: ColorReplacementItem[] = [
    ...state.replacement_regions,
  ];
  if (Object.keys(state.colorRemapMap).length > 0) {
    const remapRegions = colorRemapToReplacementRegions(
      state.colorRemapMap,
      state.palette,
    );
    mergedReplacements = [...mergedReplacements, ...remapRegions];
  }

  // Normalize replacement hex values to '#' prefix
  const normalizedReplacements = mergedReplacements.map((r) => ({
    quantized_hex: ensureHash(r.quantized_hex),
    matched_hex: ensureHash(r.matched_hex),
    replacement_hex: ensureHash(r.replacement_hex),
  }));

  // Normalize free_color_set to '#' prefix
  const normalizedFreeColors = Array.from(state.free_color_set).map(ensureHash);

  // Normalize color_height_map keys to '#' prefix
  const normalizedHeightMap: Record<string, number> = {};
  for (const [hex, height] of Object.entries(state.color_height_map)) {
    normalizedHeightMap[ensureHash(hex)] = height;
  }
  const selectedLegacyLutNames = normalizeLegacyLutNames(state);
  const isMaterialSource = state.source_version === "material";
  const nativeFilamentProfiles = scopedNativeFilamentProfiles(state, settings);
  const hasDynamicResult =
    state.materialDynamicRecipes.length > 0 ||
    state.materialLayerBenefitCurve.length > 0;

  const lutRef: LutReference = {
    name: state.lut_name,
    color_mode: state.color_mode,
    ...(lutPath ? { path_hint: lutPath } : {}),
  };

  return {
    base: {
      lut: lutRef,
      color_mode: state.color_mode,
      modeling_mode: state.modeling_mode,
      target_width_mm: state.target_width_mm,
      target_height_mm: state.target_height_mm,
      quantize_colors: state.quantize_colors,
      quantize_colors_unlocked: state.quantize_colors_unlocked,
      high_precision_3d_preview: state.high_precision_3d_preview,
      enable_cleanup: state.enable_cleanup,
      svg_pixels_per_mm: settings.svgPixelsPerMm,
      ...svgHoleCompensationOptions(state),
      hue_enable: state.hue_enable,
      use_lut_constrained: state.use_lut_constrained,
      auto_dynamic_range: state.auto_dynamic_range,
      chroma_gate: state.chroma_gate,
    },
    source: {
      source_version: state.source_version,
      ...(state.source_version === "legacy" && selectedLegacyLutNames.length > 0
        ? { selected_legacy_lut_names: selectedLegacyLutNames }
        : {}),
      selected_native_brand_key: state.selectedNativeBrandKey,
      selected_native_db_names: [...state.selectedNativeDbNames],
      color_layers: state.color_layers,
      layer_height_mm: state.layer_height_mm,
      model_enable: state.model_enable,
      model_only: state.model_only,
      model_threshold: state.model_threshold,
      model_margin: state.model_margin,
      selected_material_dir_names: [...state.selectedMaterialDirNames],
      material_layer_count: state.materialLayerCount,
      material_layer_height_mm: state.materialLayerHeightMm,
      material_backing_material_dir_name: state.materialBackingMaterialDirName,
      ...(isMaterialSource
        ? {
            material_dynamic_layer_count_enabled:
              state.materialDynamicLayerCountEnabled,
            material_min_layer_count: state.materialMinLayerCount,
            material_max_layer_count: state.materialMaxLayerCount,
            material_delta_e00_tolerance:
              settings.materialDeltaE00Tolerance,
          }
        : {}),
    },
    ...(isMaterialSource &&
    state.materialDynamicLayerCountEnabled &&
    hasDynamicResult
      ? {
          material_dynamic: {
            recipes: state.materialDynamicRecipes.map(
              cloneDynamicMaterialRecipe,
            ),
            benefit_curve: cloneMaterialLayerBenefitCurve(
              state.materialLayerBenefitCurve,
            ),
            scope: state.materialLayerBenefitScope,
            pixel_count: state.materialLayerBenefitPixelCount,
          },
        }
      : {}),
    geometry: {
      spacer_thick: state.enable_fridge_magnet
        ? state.base_spacer_thick
        : state.spacer_thick,
      backing_infill_density_percent:
        state.backing_infill_density_percent,
      structure_mode: state.structure_mode,
      separate_backing: state.separate_backing,
      backing_output: state.backingOutput,
      add_loop: state.add_loop,
      loop_width: state.loop_width,
      loop_length: state.loop_length,
      loop_hole: state.loop_hole,
      loop_angle: state.loop_angle,
      loop_offset_x: state.loop_offset_x,
      loop_offset_y: state.loop_offset_y,
      loop_position_preset: state.loop_position_preset,
    },
    relief: {
      enable_relief: state.enable_relief,
      auto_height_mode: state.autoHeightMode,
      color_height_map: normalizedHeightMap,
      heightmap_max_height: state.heightmap_max_height,
    },
    outline: {
      enable_outline: state.enable_outline,
      outline_width: state.outline_width,
    },
    cloisonne: {
      enable_cloisonne: state.enable_cloisonne,
      wire_width_mm: state.wire_width_mm,
      wire_height_mm: state.wire_height_mm,
    },
    coating: {
      enable_coating: state.enable_coating,
      coating_height_mm: state.coating_height_mm,
    },
    color_ops: {
      replacement_regions: normalizedReplacements,
      free_color_set: normalizedFreeColors,
      recipe_overrides: state.recipe_overrides.map((item) => ({
        region_id: item.region_id,
        recipe: [...item.recipe],
        layer_order: item.layer_order,
        ...virtualMaterialsField(item.virtual_materials),
      })),
      custom_recipe_history: state.customRecipeHistory.map((item) => ({
        id: item.id,
        recipe: [...item.recipe],
        layer_order: item.layerOrder,
        predicted_rgb: [...item.predictedRgb],
        predicted_lab: [...item.predictedLab],
        hex: item.hex,
        from_model: item.fromModel,
        created_at_ms: item.createdAtMs,
        ...(item.displayHexes
          ? { display_hexes: [...item.displayHexes] }
          : {}),
        ...(item.displayLabels
          ? { display_labels: [...item.displayLabels] }
          : {}),
        ...virtualMaterialsField(item.virtualMaterials),
      })),
    },
    large_format: {
      large_format_enabled: state.largeFormatEnabled,
      tile_width_mm: state.tileWidthMm,
      tile_height_mm: state.tileHeightMm,
    },
    puzzle: {
      puzzle_enabled: state.puzzleEnabled,
      puzzle_style: state.puzzleStyle,
      puzzle_sizing_mode: state.puzzleSizingMode,
      piece_width_mm: state.pieceWidthMm,
      piece_height_mm: state.pieceHeightMm,
      puzzle_rows: state.puzzleRows,
      puzzle_cols: state.puzzleCols,
      target_piece_count: state.targetPieceCount,
      puzzle_seed: 0,
      connector_style: state.connectorStyle,
      labels_enabled: state.labelsEnabled,
      engrave_back_labels: false,
      irregularity_strength: state.irregularityStrength,
      min_neck_width_mm: state.minNeckWidthMm,
    },
    fridge_magnet: {
      enable_fridge_magnet: state.enable_fridge_magnet,
      fridge_magnets: state.fridge_magnets.map((item) => ({
        ...item,
      })),
    },
    device: {
      printer_id: settings.printerModel,
      slicer: settings.slicerSoftware,
      nozzle_size: settings.nozzleSize,
      device_profile_id: settings.deviceProfileId,
      custom_3mf_template_id: settings.custom3mfTemplateId,
      ...(nativeFilamentProfiles ? { native_filament_profiles: nativeFilamentProfiles } : {}),
      ...(settings.buildPlateId
        ? { build_plate_id: settings.buildPlateId }
        : {}),
      enable_base_layer_height_modifier:
        settings.enableBaseLayerHeightModifier,
      enable_wipe_tower_auto_placement:
        settings.enableWipeTowerAutoPlacement,
    },
  };
}

/**
 * Build a full LuminaRecipe from components.
 * 从各组件构建完整 LuminaRecipe。
 *
 * @param converterRecipe - The converter recipe section.
 * @param cover - Cover image metadata.
 * @param assets - Primary and optional heightmap asset entries.
 * @param workshopSource - Optional matrix-only workshop restore source.
 * @returns The complete editable LuminaRecipe.
 */
export async function buildFullRecipe(
  converterRecipe: ConverterRecipe,
  cover: RecipeCover,
  assets: RecipeAssets,
  workshopSource?: WorkshopRecipeSource | null,
): Promise<LuminaRecipe> {
  return {
    format: RECIPE_FORMAT,
    schema_version: RECIPE_SCHEMA_VERSION,
    app_version: getAppVersion(),
    created_at: new Date().toISOString(),
    source: "converter",
    cover,
    asset: assets,
    recipe: {
      converter: converterRecipe,
      ...(workshopSource
        ? { workshop: cloneWorkshopRecipeSource(workshopSource) }
        : {}),
    },
    compat: {
      min_schema_version: RECIPE_SCHEMA_VERSION,
    },
    warnings: [],
  };

}

/**
 * Build assets from File objects.
 * 从 File 对象构建 assets。
 */
export async function buildRecipeAssets(
  primaryFile: File,
  heightmapFile?: File | null,
  editorFile?: File | null,
): Promise<RecipeAssets> {
  const primary = await buildAssetEntry(primaryFile);
  const assets: RecipeAssets = { primary };
  if (heightmapFile) {
    assets.heightmap = await buildAssetEntry(heightmapFile);
  }
  if (editorFile) {
    assets.editor = await buildAssetEntry(editorFile);
  }
  return assets;
}

/**
 * Create a cover image by rendering the preview URL onto a canvas and
 * appending a Lumina share-card footer (QR code + localized caption).
 * 通过将预览 URL 渲染到画布并在底部追加分享卡尾标（二维码 + 多语言文字）来创建封面图。
 *
 * The footer points to the Lumina wiki and tells viewers that this PNG can be
 * imported back into Lumina 2.0 directly.
 *
 * @param previewUrl - URL of the current 2D preview image.
 * @param maxWidth - Maximum width for the cover thumbnail (default: 800).
 * @returns Cover PNG blob and metadata. `width`/`height` describe the final
 *   composed image including the footer.
 */
export async function buildCoverImage(
  previewUrl: string,
  maxWidth: number = 800,
): Promise<{ blob: Blob; cover: RecipeCover }> {
  const img = await loadImage(previewUrl);

  // 1) Scale the preview to fit `maxWidth` while preserving aspect ratio.
  const scale = Math.min(1, maxWidth / img.naturalWidth);
  const previewW = Math.max(1, Math.round(img.naturalWidth * scale));
  const previewH = Math.max(1, Math.round(img.naturalHeight * scale));

  // 2) The cover canvas must be wide enough to host the QR + caption. If the
  //    preview is narrower, pad horizontally so the footer never gets clipped.
  //    封面画布最小宽度受页脚约束；预览较窄时左右补白，避免 QR/文字被裁。
  const coverW = Math.max(previewW, MIN_COVER_WIDTH);

  // 3) Compute footer layout (QR size, font, wrapped lines) for the canvas
  //    width using a real canvas measurer so caption shrink/wrap is accurate.
  await document.fonts.load('400 14px "MiSans"');
  const measureCanvas = document.createElement("canvas");
  const measureCtx = measureCanvas.getContext("2d");
  if (!measureCtx) {
    throw new Error("Failed to create measurement canvas context");
  }
  const layout = computeFooterLayout(
    coverW,
    getFooterCaption(),
    makeCanvasMeasurer(measureCtx),
  );

  const totalH = previewH + layout.height;
  const canvas = document.createElement("canvas");
  canvas.width = coverW;
  canvas.height = totalH;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("Failed to create canvas context");
  }

  // 4) Fill any horizontal padding white so the cover has no transparent gap
  //    around the preview when coverW > previewW.
  if (coverW > previewW) {
    ctx.fillStyle = "#FFFFFF";
    ctx.fillRect(0, 0, coverW, previewH);
  }

  // 5) Draw the preview centered horizontally in the top region.
  const previewX = Math.round((coverW - previewW) / 2);
  ctx.drawImage(img, previewX, 0, previewW, previewH);

  // 6) Footer below the preview.
  await drawShareCardFooter(ctx, coverW, previewH, layout);

  const blob = await canvasToPngBlob(canvas);
  return {
    blob,
    cover: { width: coverW, height: totalH, mime_type: "image/png" },
  };
}

/** Load an image element from a URL, resolving once decoded. */
function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load preview image for cover"));
    img.src = url;
  });
}

/** Convert a canvas into a PNG blob, rejecting on encoder failure. */
function canvasToPngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          reject(new Error("Failed to create cover PNG blob"));
          return;
        }
        resolve(blob);
      },
      "image/png",
    );
  });
}
