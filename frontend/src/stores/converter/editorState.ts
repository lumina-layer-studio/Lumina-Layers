import type { ColorReplacementItem, EditorCommitResult, RecipeOverrideItem } from "../../api/types";
import { colorRemapToReplacementRegions } from "../../utils/colorUtils";
import { normalizeResourceUrl } from "../../utils/resourceUrl";
import type {
  ConverterState,
  RegionData,
  RemapSnapshot,
  SelectionDocument,
  SelectionMode,
  SelectionTool,
} from "./types";

export function selectionModeForTool(tool: SelectionTool): SelectionMode {
  return tool === "same-color" ? "select-all" : "multi-select";
}

export function selectionToolForLegacyMode(mode: SelectionMode): SelectionTool {
  return mode === "select-all" ? "same-color" : "point";
}

function regionDataFromSelectionComponent(
  component: SelectionDocument["components"][number],
  previewUrl: string,
): RegionData {
  return {
    regionId: component.region_id,
    colorHex: component.color_hex,
    pixelCount: component.pixel_count,
    previewUrl,
    bbox:
      component.bbox.length === 4
        ? (component.bbox as [number, number, number, number])
        : null,
    clickX: component.anchor[0],
    clickY: component.anchor[1],
  };
}

export function selectionStateFromDocument(
  document: SelectionDocument,
  previewUrl: string,
): Partial<ConverterState> {
  const selectedRegions = document.components.map((component) =>
    regionDataFromSelectionComponent(component, previewUrl),
  );
  const last = selectedRegions[selectedRegions.length - 1] ?? null;
  return {
    selectionDocument: document,
    selectedRegions,
    regionData: last,
    selectedColors: new Set(
      document.selected_color_hexes.map((hex) => hex.replace(/^#/, "")),
    ),
    selectedColor: last?.colorHex.replace(/^#/, "") ?? null,
    historyCanUndo: document.can_undo,
    historyCanRedo: document.can_redo,
  };
}

export function normalizeHexNoHash(hex: string | null | undefined): string | null {
  if (!hex) return null;
  const raw = hex.replace(/^#/, "").trim();
  return /^[0-9a-fA-F]{6}$/.test(raw) ? raw : null;
}

export function chooseLastSelectedColor(colors: Set<string>): string | null {
  const values = Array.from(colors);
  return values.length > 0 ? values[values.length - 1] : null;
}

function findMatchingHexInSet(colors: Set<string>, hex: string): string | null {
  const target = hex.toLowerCase();
  return Array.from(colors).find((value) => value.toLowerCase() === target) ?? null;
}

export function toggleHexInSet(colors: Set<string>, hex: string): Set<string> {
  const next = new Set(colors);
  const existing = findMatchingHexInSet(next, hex);
  if (existing) {
    next.delete(existing);
  } else {
    next.add(hex);
  }
  return next;
}

export function buildCurrentVisibleColorRemapMap(
  currentMap: Record<string, string>,
  sourceHexes: string[],
  targetHex: string,
): Record<string, string> {
  const normalizedTarget = normalizeHexNoHash(targetHex);
  if (!normalizedTarget) {
    return { ...currentMap };
  }

  const rawSources = sourceHexes
    .map((hex) => normalizeHexNoHash(hex))
    .filter((hex): hex is string => hex !== null);
  if (rawSources.length === 0) {
    return { ...currentMap };
  }

  const sourceSet = new Set(rawSources.map((hex) => hex.toLowerCase()));
  const next = { ...currentMap };
  for (const [origHex, mappedHex] of Object.entries(currentMap)) {
    const normalizedMapped = normalizeHexNoHash(mappedHex);
    if (normalizedMapped && sourceSet.has(normalizedMapped.toLowerCase())) {
      next[origHex] = normalizedTarget;
    }
  }

  for (const sourceHex of rawSources) {
    const existingKey =
      Object.keys(next).find(
        (key) => normalizeHexNoHash(key)?.toLowerCase() === sourceHex.toLowerCase(),
      ) ?? sourceHex;
    next[existingKey] = normalizedTarget;
  }

  return next;
}

export function cloneRecipeOverrides(items: RecipeOverrideItem[]): RecipeOverrideItem[] {
  return items.map((item) => ({
    region_id: item.region_id,
    recipe: [...item.recipe],
    layer_order: item.layer_order,
    ...(item.color_layers !== undefined
      ? { color_layers: item.color_layers }
      : {}),
    ...(item.actual_recipe_top_to_bottom
      ? { actual_recipe_top_to_bottom: [...item.actual_recipe_top_to_bottom] }
      : {}),
    ...(item.print_recipe_top_to_bottom
      ? { print_recipe_top_to_bottom: [...item.print_recipe_top_to_bottom] }
      : {}),
    ...(item.actual_layer_count !== undefined
      ? { actual_layer_count: item.actual_layer_count }
      : {}),
    ...(item.padding_layer_count !== undefined
      ? { padding_layer_count: item.padding_layer_count }
      : {}),
    ...(item.virtual_materials
      ? {
        virtual_materials: item.virtual_materials.map((material) => ({
          ...material,
        })),
      }
      : {}),
  }));
}

export function cloneReplacementRegions(
  items: ColorReplacementItem[],
): ColorReplacementItem[] {
  return items.map((item) => ({ ...item }));
}

function replacementRegionStringField(
  region: ColorReplacementItem | Record<string, unknown>,
  key: string,
): string | null {
  const value = (region as Record<string, unknown>)[key];
  return typeof value === "string" ? value : null;
}

export function normalizeReplacementRegionsFromHistory(
  regions: Array<ColorReplacementItem | Record<string, unknown>>,
): ColorReplacementItem[] {
  return regions.flatMap((region) => {
    const matchedHex = normalizeHexNoHash(
      replacementRegionStringField(region, "matched_hex") ??
      replacementRegionStringField(region, "selected_color") ??
      replacementRegionStringField(region, "quantized_hex"),
    );
    const replacementHex = normalizeHexNoHash(
      replacementRegionStringField(region, "replacement_hex") ??
      replacementRegionStringField(region, "replacement_color"),
    );
    if (!matchedHex || !replacementHex) return [];
    const quantizedHex = normalizeHexNoHash(
      replacementRegionStringField(region, "quantized_hex") ?? matchedHex,
    ) ?? matchedHex;
    return [
      {
        quantized_hex: quantizedHex,
        matched_hex: matchedHex,
        replacement_hex: replacementHex,
        ...('source_scope' in region && region.source_scope
          ? { source_scope: region.source_scope as ColorReplacementItem['source_scope'] } : {}),
      },
    ];
  });
}

export function historyFlagsFromResponse(
  response: { can_undo?: boolean; can_redo?: boolean } | null | undefined,
): Pick<ConverterState, "historyCanUndo" | "historyCanRedo"> {
  return {
    historyCanUndo: Boolean(response?.can_undo),
    historyCanRedo: Boolean(response?.can_redo),
  };
}

export function editorCommitResultStateFromResponse(
  current: ConverterState,
  sessionId: string,
  operation: string | null | undefined,
  result: EditorCommitResult | null | undefined,
): Partial<ConverterState> {
  if (!result || current.sessionId !== sessionId) return {};

  const updates: Partial<ConverterState> = {};
  const hasPreviewUrl = Object.prototype.hasOwnProperty.call(
    result,
    "preview_url",
  );
  if (hasPreviewUrl && result.preview_url) {
    const previewUrl = normalizeResourceUrl(result.preview_url);
    updates.previewImageUrl = previewUrl;
    updates.previewBaseImageUrl = previewUrl;
    updates.threemfDiskPath = null;
    updates.downloadUrl = null;
    updates.layerImages = [];
    updates.layerImagesSourceKey = null;
  }
  if (result.preview_glb_url) {
    updates.previewGlbUrl = normalizeResourceUrl(result.preview_glb_url);
  } else if (
    operation === "reset_replacements" &&
    result.preview_glb_url === null
  ) {
    // Reset explicitly publishes a null GLB because the old derived artifact
    // no longer describes the restored content. Other receipts also serialize
    // omitted optional fields as null; those must not clear a live GLB.
    updates.previewGlbUrl = null;
  }
  if (result.replacement_regions !== undefined && result.replacement_regions !== null) {
    updates.replacement_regions = normalizeReplacementRegionsFromHistory(
      result.replacement_regions,
    );
    updates.colorRemapMap = colorRemapFromReplacementRegions(
      result.replacement_regions,
    );
  }
  if (result.recipe_overrides !== undefined && result.recipe_overrides !== null) {
    updates.recipe_overrides = cloneRecipeOverrides(result.recipe_overrides);
  }
  if (
    result.region_replacement_count !== undefined &&
    result.region_replacement_count !== null
  ) {
    updates.regionReplacementCount = result.region_replacement_count;
  }
  if (result.free_color_set !== undefined && result.free_color_set !== null) {
    updates.free_color_set = new Set(result.free_color_set);
  }
  if (result.color_layers !== undefined && result.color_layers !== null) {
    updates.color_layers = result.color_layers;
  }
  if (result.layer_height_mm !== undefined && result.layer_height_mm !== null) {
    updates.layer_height_mm = result.layer_height_mm;
  }
  if (Array.isArray(result.gradient_groups)) {
    updates.gradientGroups = result.gradient_groups;
  }
  if (result.can_undo !== undefined && result.can_undo !== null) {
    updates.historyCanUndo = result.can_undo;
  }
  if (result.can_redo !== undefined && result.can_redo !== null) {
    updates.historyCanRedo = result.can_redo;
  }
  const dynamicRecipes = result.material_dynamic_recipes;
  const benefitCurve = result.material_layer_benefit_curve;
  const hasDynamicRecipes = dynamicRecipes !== undefined && dynamicRecipes !== null;
  const hasBenefitCurve = benefitCurve !== undefined && benefitCurve !== null;
  if (hasDynamicRecipes) {
    updates.materialDynamicRecipes = dynamicRecipes;
  }
  if (hasBenefitCurve) {
    updates.materialLayerBenefitCurve = benefitCurve;
  }
  if (
    result.material_layer_benefit_scope !== undefined &&
    result.material_layer_benefit_scope !== null &&
    result.material_layer_benefit_pixel_count !== undefined &&
    result.material_layer_benefit_pixel_count !== null
  ) {
    updates.materialLayerBenefitScope =
      result.material_layer_benefit_scope;
    updates.materialLayerBenefitPixelCount =
      result.material_layer_benefit_pixel_count;
  } else if (hasDynamicRecipes || hasBenefitCurve) {
    // Match the normal edit response's legacy fallback only when a dynamic
    // result was actually supplied; null-only optional fields mean no update.
    updates.materialLayerBenefitScope = "all_printable_pixels";
    updates.materialLayerBenefitPixelCount = 0;
  }
  if (operation === "reset_replacements" && hasPreviewUrl) {
    updates.originalPreviewUrl = normalizeResourceUrl(result.preview_url);
  }
  return updates;
}

export function colorRemapFromReplacementRegions(
  regions: Array<ColorReplacementItem | Record<string, unknown>>,
): Record<string, string> {
  const map: Record<string, string> = {};
  for (const region of regions) {
    const source = normalizeHexNoHash(
      replacementRegionStringField(region, "matched_hex") ??
      replacementRegionStringField(region, "selected_color") ??
      replacementRegionStringField(region, "quantized_hex"),
    );
    const target = normalizeHexNoHash(
      replacementRegionStringField(region, "replacement_hex") ??
      replacementRegionStringField(region, "replacement_color"),
    );
    if (source && target) {
      map[source] = target;
    }
  }
  return map;
}

export function cloneRemapHistory(history: RemapSnapshot[]): RemapSnapshot[] {
  return history.map((snapshot) => ({ ...snapshot }));
}


export function hasAdjustmentState(
  state: Pick<
    ConverterState,
    | "colorRemapMap"
    | "replacement_regions"
    | "recipe_overrides"
    | "regionReplacementCount"
  >,
): boolean {
  return (
    Object.keys(state.colorRemapMap).length > 0 ||
    state.replacement_regions.length > 0 ||
    state.recipe_overrides.length > 0 ||
    state.regionReplacementCount > 0
  );
}

export function getPreviewBaseUrl(
  state: Pick<
    ConverterState,
    "previewBaseImageUrl" | "originalPreviewUrl" | "previewImageUrl"
  >,
): string | null {
  return (
    state.previewBaseImageUrl ??
    state.originalPreviewUrl ??
    state.previewImageUrl
  );
}

// ========== localStorage Helpers ==========

export const EMPTY_LUT_MATCH_STATE = {
  lutMatchMode: null,
  lutMatchInfo: null,
} as const;

/**
 * Partial invalidation for cached per-layer preview images after a color
 * replacement. Preserves `layerImagesOpen` (user panel visibility) and
 * `layerImagesLoading`, but drops stale image URLs and source key so the
 * next hover/fetch refreshes layer data against the new preview.
 * 颜色替换后用于失效分层预览图缓存的局部状态：保留用户面板可见性与
 * 加载状态，清除过期的图片 URL 与 source key，确保下次悬停/拉取
 * 能针对新预览刷新分层数据。
 */
export const INVALIDATE_LAYER_IMAGES_AFTER_REPLACE = {
  layerImages: [] as { layer_index: number; name: string; url: string }[],
  layerImagesSourceKey: null as string | null,
} as const;

type PortableProjectColorState = Pick<
  ConverterState,
  | "replacement_regions"
  | "free_color_set"
  | "customRecipeHistory"
>;

function normalizeReplacementHex(hex: string): string {
  return hex.trim().replace(/^#/, "").toLowerCase();
}

function mergePortableReplacementRegions(
  persisted: ColorReplacementItem[],
  live: ColorReplacementItem[],
): ColorReplacementItem[] {
  const bySource = new Map<string, ColorReplacementItem>();
  for (const item of [...persisted, ...live]) {
    const quantized = normalizeReplacementHex(item.quantized_hex);
    const matched = normalizeReplacementHex(item.matched_hex);
    const source = quantized || matched;
    if (!source) continue;
    bySource.set(source, { ...item });
  }
  return Array.from(bySource.values());
}

export function clonePortableProjectColorState(
  state: Pick<
    ConverterState,
    "replacement_regions" | "free_color_set" | "customRecipeHistory"
  >,
): PortableProjectColorState {
  return {
    replacement_regions: state.replacement_regions.map((item) => ({
      ...item,
    })),
    free_color_set: new Set(state.free_color_set),
    customRecipeHistory: state.customRecipeHistory.map((item) => ({
      ...item,
      recipe: [...item.recipe],
      predictedRgb: [...item.predictedRgb] as [number, number, number],
      predictedLab: [...item.predictedLab] as [number, number, number],
      ...(item.displayHexes ? { displayHexes: [...item.displayHexes] } : {}),
      ...(item.displayLabels
        ? { displayLabels: [...item.displayLabels] }
        : {}),
      ...(item.virtualMaterials
        ? {
          virtualMaterials: item.virtualMaterials.map((material) => ({
            ...material,
          })),
        }
        : {}),
    })),
  };
}

export function buildSourceChangeProjectColorState(
  state: ConverterState,
): PortableProjectColorState {
  const portable = clonePortableProjectColorState(state);
  const liveRemaps = colorRemapToReplacementRegions(
    state.colorRemapMap,
    state.palette, state.replacement_regions,
  );
  return {
    ...portable,
    replacement_regions: mergePortableReplacementRegions(
      portable.replacement_regions,
      liveRemaps,
    ),
  };
}
