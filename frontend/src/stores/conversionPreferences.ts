import { StructureMode } from "../api/types";
import type { ConverterState, ConverterActions } from "./converter/types";

export const PRESET_OPTION_KEYS = {
  advanced: ["enable_cleanup", "separate_backing", "backingOutput", "use_lut_constrained",
    "auto_dynamic_range", "high_precision_3d_preview", "hue_enable", "chroma_gate", "quantize_colors_unlocked",
    "materialLayersUnlocked"],
  outline: ["enable_outline", "outline_width"],
  coating: ["enable_coating", "coating_height_mm"],
} as const;
export type PresetOptions = Record<keyof typeof PRESET_OPTION_KEYS, boolean>;
export const DEFAULT_PRESET_OPTIONS: PresetOptions = { advanced: false, outline: false, coating: false };
type OptionalParameterKey = typeof PRESET_OPTION_KEYS[keyof typeof PRESET_OPTION_KEYS][number];

export type ConversionParameters = Pick<ConverterState,
  "source_version" | "structure_mode" | "base_spacer_thick" |
  "backing_infill_density_percent" | "selectedMaterialDirNames" |
  "materialBackingMaterialDirName" | "materialLayerCount" |
  "materialLayerHeightMm" | "materialDynamicLayerCountEnabled" |
  "materialMinLayerCount" | "materialMaxLayerCount" | "lut_names" | "selectedNativeBrandKey" | "selectedNativeDbNames" |
  "largeFormatEnabled" | "tileWidthMm" | "tileHeightMm"
> & Partial<Pick<ConverterState, OptionalParameterKey>> & { size_axis: "long_edge"; size_mm: number };

/** Highest layer count a remembered setting may carry (30 when unlocked). */
const REMEMBERED_LAYER_COUNT_MAX = 30;

/** Omit unselected groups entirely, including when serializing to backend settings. */
export function selectPresetParameters(parameters: ConversionParameters, options: PresetOptions): ConversionParameters {
  const selected = { ...parameters };
  for (const group of Object.keys(PRESET_OPTION_KEYS) as Array<keyof PresetOptions>) {
    if (!options[group]) for (const key of PRESET_OPTION_KEYS[group]) delete selected[key];
  }
  return selected;
}

export function getPresetOptions(parameters: ConversionParameters): PresetOptions {
  return {
    advanced: PRESET_OPTION_KEYS.advanced.some(key => parameters[key] !== undefined),
    outline: PRESET_OPTION_KEYS.outline.some(key => parameters[key] !== undefined),
    coating: PRESET_OPTION_KEYS.coating.some(key => parameters[key] !== undefined),
  };
}

export function presetMatchesCurrent(saved: ConversionParameters, current: ConversionParameters): boolean {
  return (Object.keys(saved) as Array<keyof ConversionParameters>).every(key =>
    JSON.stringify(saved[key]) === JSON.stringify(current[key]));
}

export interface ConversionPreset {
  id: string;
  name: string;
  parameters: ConversionParameters;
}
export interface ConversionPreferences {
  last: ConversionParameters | null;
  presets: ConversionPreset[];
  selectedPresetId?: string | null;
}

export type PresetNameError = "invalid-name" | "duplicate-name";
export type SavePresetResult = { id: string } | { error: PresetNameError };

export function validatePresetName(name: string, presets: ConversionPreset[], exceptId?: string): PresetNameError | null {
  const clean = name.trim();
  if (!clean || clean.length > 40) return "invalid-name";
  return presets.some(p => p.id !== exceptId && p.name === clean) ? "duplicate-name" : null;
}

export function captureConversionParameters(state: ConverterState): ConversionParameters {
  return {
    source_version: state.source_version,
    structure_mode: state.structure_mode,
    size_axis: "long_edge",
    size_mm: Math.max(state.target_width_mm, state.target_height_mm),
    base_spacer_thick: state.base_spacer_thick,
    backing_infill_density_percent: state.backing_infill_density_percent,
    selectedMaterialDirNames: state.selectedMaterialDirNames,
    materialBackingMaterialDirName: state.materialBackingMaterialDirName,
    materialLayerCount: state.materialLayerCount,
    materialLayerHeightMm: state.materialLayerHeightMm,
    materialDynamicLayerCountEnabled: state.materialDynamicLayerCountEnabled,
    materialMinLayerCount: state.materialMinLayerCount,
    materialMaxLayerCount: state.materialMaxLayerCount,
    enable_cleanup: state.enable_cleanup,
    separate_backing: state.separate_backing,
    backingOutput: state.backingOutput,
    use_lut_constrained: state.use_lut_constrained,
    auto_dynamic_range: state.auto_dynamic_range,
    high_precision_3d_preview: state.high_precision_3d_preview,
    hue_enable: state.hue_enable,
    chroma_gate: state.chroma_gate,
    quantize_colors_unlocked: state.quantize_colors_unlocked,
    materialLayersUnlocked: state.materialLayersUnlocked,
    enable_outline: state.enable_outline,
    outline_width: state.outline_width,
    enable_coating: state.enable_coating,
    coating_height_mm: state.coating_height_mm,
    lut_names: state.lut_names,
    selectedNativeBrandKey: state.selectedNativeBrandKey,
    selectedNativeDbNames: state.selectedNativeDbNames,
    largeFormatEnabled: state.largeFormatEnabled,
    tileWidthMm: state.tileWidthMm,
    tileHeightMm: state.tileHeightMm,
  };
}

function normalizeParameters(value: unknown): ConversionParameters | null {
  if (!value || typeof value !== "object") return null;
  const p = value as Record<string, unknown>;
  const number = (key: string, min: number, max = Infinity) =>
    typeof p[key] === "number" && Number.isFinite(p[key]) && p[key] >= min && p[key] <= max;
  const strings = (key: string) => Array.isArray(p[key]) && p[key].every(v => typeof v === "string");
  if (!(p.source_version === "material" || p.source_version === "legacy" || p.source_version === "native") ||
      !(p.structure_mode === StructureMode.SINGLE_SIDED || p.structure_mode === StructureMode.DOUBLE_SIDED) ||
      !(p.size_axis === "long_edge" || p.size_axis === "width" || p.size_axis === "height") || !number("size_mm", 10) ||
      !number("base_spacer_thick", 0.2, 10) || !number("backing_infill_density_percent", 5, 100) ||
      !number("materialLayerCount", 1, REMEMBERED_LAYER_COUNT_MAX) || !number("materialLayerHeightMm", 0.04, 0.2) ||
      !number("materialMinLayerCount", 1, REMEMBERED_LAYER_COUNT_MAX) ||
      !number("materialMaxLayerCount", 1, REMEMBERED_LAYER_COUNT_MAX) ||
      ![p.materialLayerCount, p.materialMinLayerCount, p.materialMaxLayerCount].every(Number.isInteger) ||
      Number(p.materialMinLayerCount) > Number(p.materialMaxLayerCount) ||
      typeof p.largeFormatEnabled !== "boolean" || !number("tileWidthMm", 50) || !number("tileHeightMm", 50) ||
      (p.coating_height_mm !== undefined && !number("coating_height_mm", 0.04, 0.12)) ||
      typeof p.materialDynamicLayerCountEnabled !== "boolean" || (p.enable_coating !== undefined && typeof p.enable_coating !== "boolean") ||
      !strings("selectedMaterialDirNames") || !strings("lut_names") || !strings("selectedNativeDbNames") ||
      typeof p.selectedNativeBrandKey !== "string" ||
      !(p.materialBackingMaterialDirName === null || typeof p.materialBackingMaterialDirName === "string")) return null;
  const booleans = ["enable_cleanup", "separate_backing", "use_lut_constrained", "auto_dynamic_range",
    "high_precision_3d_preview", "hue_enable", "quantize_colors_unlocked", "materialLayersUnlocked", "enable_outline"];
  if (booleans.some(key => p[key] !== undefined && typeof p[key] !== "boolean") ||
      (p.backingOutput !== undefined && p.backingOutput !== "same_project" && p.backingOutput !== "separate_project") ||
      (p.chroma_gate !== undefined && !number("chroma_gate", 0, 50)) ||
      (p.outline_width !== undefined && !number("outline_width", 0.5, 10))) return null;
  // Build a whitelist; never restore sessions, resource URLs, images, or edits.
  const keys: Array<keyof ConversionParameters> = ["source_version", "structure_mode", "size_axis", "size_mm",
    "base_spacer_thick", "backing_infill_density_percent", "selectedMaterialDirNames",
    "materialBackingMaterialDirName", "materialLayerCount", "materialLayerHeightMm",
    "materialDynamicLayerCountEnabled", "materialMinLayerCount", "materialMaxLayerCount",
    "enable_coating", "coating_height_mm", "lut_names", "selectedNativeBrandKey", "selectedNativeDbNames",
    "largeFormatEnabled", "tileWidthMm", "tileHeightMm",
    ...PRESET_OPTION_KEYS.advanced, ...PRESET_OPTION_KEYS.outline];
  // Older records contain only one dimension, so retain its value as the long edge.
  return { ...Object.fromEntries(keys.filter(key => p[key] !== undefined).map(key => [key, Array.isArray(p[key]) ? [...p[key]] : p[key]])),
    size_axis: "long_edge" } as ConversionParameters;
}

export function normalizeConversionPreferences(value: unknown): ConversionPreferences {
  if (!value || typeof value !== "object") return { last: null, presets: [], selectedPresetId: null };
  const raw = value as Record<string, unknown>;
  const presets: ConversionPreset[] = [];
  if (Array.isArray(raw.presets)) for (const entry of raw.presets) {
    if (!entry || typeof entry !== "object") continue;
    const parameters = normalizeParameters(entry.parameters);
    if (typeof entry.id !== "string" || !entry.id || typeof entry.name !== "string" ||
        !entry.name.trim() || entry.name.trim().length > 40 || !parameters ||
        presets.some(p => p.id === entry.id || p.name === entry.name.trim())) continue;
    presets.push({ id: entry.id, name: entry.name.trim(), parameters });
  }
  return { last: normalizeParameters(raw.last), presets,
    selectedPresetId: presets.some(p => p.id === raw.selectedPresetId) ? raw.selectedPresetId as string : null };
}

export function applyConversionParameters(getState: () => ConverterState & ConverterActions, p: ConversionParameters): void {
  const state = getState();
  const different = (a: unknown, b: unknown) => JSON.stringify(a) !== JSON.stringify(b);
  if (getState().source_version !== p.source_version) state.setSourceVersion(p.source_version);
  if (p.source_version === "legacy" && different(getState().lut_names, p.lut_names)) state.setLegacyLutNames(p.lut_names);
  if (p.source_version === "native") {
    if (getState().selectedNativeBrandKey !== p.selectedNativeBrandKey) state.setNativeBrandKey(p.selectedNativeBrandKey);
    if (different(getState().selectedNativeDbNames, p.selectedNativeDbNames)) state.setNativeDbNames(p.selectedNativeDbNames);
  }
  // Restore the 30-layer switch first so deeper counts are not clamped to 10.
  // 先恢复“解锁 30 层”，否则后面的层数会被截到 10。
  const unlockLayers = p.materialLayersUnlocked ??
    Math.max(p.materialLayerCount, p.materialMaxLayerCount) > 10;
  if (getState().materialLayersUnlocked !== unlockLayers && (unlockLayers || p.materialLayersUnlocked !== undefined)) {
    state.setMaterialLayersUnlocked(unlockLayers);
  }
  if (different(getState().selectedMaterialDirNames, p.selectedMaterialDirNames)) state.setSelectedMaterialDirNames(p.selectedMaterialDirNames);
  if (getState().materialBackingMaterialDirName !== p.materialBackingMaterialDirName) state.setMaterialBackingMaterialDirName(p.materialBackingMaterialDirName);
  if (getState().materialLayerCount !== p.materialLayerCount) state.setMaterialLayerCount(p.materialLayerCount);
  if (getState().materialLayerHeightMm !== p.materialLayerHeightMm) state.setMaterialLayerHeightMm(p.materialLayerHeightMm);
  if (getState().materialMinLayerCount !== p.materialMinLayerCount) state.setMaterialMinLayerCount(p.materialMinLayerCount);
  if (getState().materialMaxLayerCount !== p.materialMaxLayerCount) state.setMaterialMaxLayerCount(p.materialMaxLayerCount);
  if (getState().materialDynamicLayerCountEnabled !== p.materialDynamicLayerCountEnabled) state.setMaterialDynamicLayerCountEnabled(p.materialDynamicLayerCountEnabled);
  if (getState().base_spacer_thick !== p.base_spacer_thick) state.setSpacerThick(p.base_spacer_thick);
  if (getState().backing_infill_density_percent !== p.backing_infill_density_percent) state.setBackingInfillDensityPercent(p.backing_infill_density_percent);
  if (getState().structure_mode !== p.structure_mode) state.setStructureMode(p.structure_mode);
  if (p.enable_coating !== undefined && getState().enable_coating !== p.enable_coating) state.setEnableCoating(p.enable_coating);
  if (p.coating_height_mm !== undefined && getState().coating_height_mm !== p.coating_height_mm) state.setCoatingHeightMm(p.coating_height_mm);
  if (getState().largeFormatEnabled !== p.largeFormatEnabled) state.setLargeFormatEnabled(p.largeFormatEnabled);
  if (getState().tileWidthMm !== p.tileWidthMm) state.setTileWidthMm(p.tileWidthMm);
  if (getState().tileHeightMm !== p.tileHeightMm) state.setTileHeightMm(p.tileHeightMm);
  if (p.enable_cleanup !== undefined && getState().enable_cleanup !== p.enable_cleanup) state.setEnableCleanup(p.enable_cleanup);
  if (p.separate_backing !== undefined && getState().separate_backing !== p.separate_backing) state.setSeparateBacking(p.separate_backing);
  if (p.backingOutput !== undefined && getState().backingOutput !== p.backingOutput) state.setBackingOutput(p.backingOutput);
  if (p.use_lut_constrained !== undefined && getState().use_lut_constrained !== p.use_lut_constrained) state.setUseLutConstrained(p.use_lut_constrained);
  if (p.auto_dynamic_range !== undefined && getState().auto_dynamic_range !== p.auto_dynamic_range) state.setAutoDynamicRange(p.auto_dynamic_range);
  if (p.high_precision_3d_preview !== undefined && getState().high_precision_3d_preview !== p.high_precision_3d_preview) state.setHighPrecision3dPreview(p.high_precision_3d_preview);
  if (p.hue_enable !== undefined && getState().hue_enable !== p.hue_enable) state.setHueEnable(p.hue_enable);
  if (p.chroma_gate !== undefined && getState().chroma_gate !== p.chroma_gate) state.setChromaGate(p.chroma_gate);
  if (p.quantize_colors_unlocked !== undefined && getState().quantize_colors_unlocked !== p.quantize_colors_unlocked) state.setQuantizeColorsUnlocked(p.quantize_colors_unlocked);
  if (p.enable_outline !== undefined && getState().enable_outline !== p.enable_outline) state.setEnableOutline(p.enable_outline);
  if (p.outline_width !== undefined && getState().outline_width !== p.outline_width) state.setOutlineWidth(p.outline_width);
  const ratio = getState().aspectRatio;
  if (ratio !== null && ratio < 1) state.setTargetHeightMm(p.size_mm);
  else state.setTargetWidthMm(p.size_mm);
  // Without an image, clear the old short edge too; the next image supplies its ratio.
  if (ratio === null) state.setTargetHeightMm(p.size_mm);
}
