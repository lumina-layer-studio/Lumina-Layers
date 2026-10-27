import type { ColorMode, LutSupportedMode, NativeBrandGroup } from "../../api/types";
import { ColorMode as ColorModeEnum, ModelingMode as ModelingModeEnum } from "../../api/types";
import { useSettingsStore } from "../settingsStore";
import type { ConverterState, SourceVersion } from "./types";

function looksLikeWhiteMaterialLabel(label: string | null | undefined): boolean {
  const text = String(label ?? "").trim().toLowerCase();
  if (!text) return false;
  if (text.includes("白")) return true;
  const tokens = text
    .replace(/\\/g, "/")
    .replace(/\//g, " ")
    .replace(/[-_]/g, " ")
    .split(/\s+/)
    .filter(Boolean);
  return tokens.includes("white") || tokens.includes("w");
}

export function inferDefaultMaterialBackingDirName(names: string[]): string | null {
  return names.find((name) => looksLikeWhiteMaterialLabel(name)) ?? names[0] ?? null;
}

// ========== Helpers ==========

export function clampValue(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

const RELIEF_MIN_EXTRA_HEIGHT_MM = 0.08;

export const RELIEF_MAX_EXTRA_HEIGHT_MM = 15.0;

const MATERIAL_ARCHIVE_RELIEF_LAYER_HEIGHT_MM = 0.08;

export const MATERIAL_DYNAMIC_LAYER_COUNT_MIN = 5;

export const MATERIAL_DYNAMIC_LAYER_COUNT_MAX = 30;

/** Default upper bound of the dynamic range (wider ranges cost build time). */
export const MATERIAL_DYNAMIC_LAYER_COUNT_DEFAULT_MAX = 10;

/** Upper bound for fixed material-archive colour layers (layer-wise DP > 10). */
export const MATERIAL_LAYER_COUNT_MAX = 30;

export function normalizeDynamicMaterialLayerCount(
  value: number,
  fallback: number,
): number {
  if (!Number.isFinite(value)) {
    return fallback;
  }
  return clampValue(
    Math.round(value),
    MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
    MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  );
}

type MaterialArchiveReliefMinimumState = {
  source_version: SourceVersion;
  materialLayerCount: number;
  materialDynamicLayerCountEnabled?: boolean;
  materialMaxLayerCount?: number;
  spacer_thick: number;
};

type DynamicMaterialActivationState = {
  source_version: SourceVersion;
  materialDynamicLayerCountEnabled: boolean;
};

type MaterialPrintLayerCountState = {
  source_version: SourceVersion;
  materialLayerCount: number;
  materialDynamicLayerCountEnabled?: boolean;
  materialMaxLayerCount?: number;
};

export function isDynamicMaterialActive(
  state: DynamicMaterialActivationState,
): boolean {
  return (
    state.source_version === "material" &&
    state.materialDynamicLayerCountEnabled === true
  );
}

export function resolveMaterialPrintLayerCount(
  state: MaterialPrintLayerCountState,
): number {
  return state.source_version === "material" &&
    state.materialDynamicLayerCountEnabled === true
    ? (state.materialMaxLayerCount ?? state.materialLayerCount)
    : state.materialLayerCount;
}

export function resolveRecipeAwareLayerCount(
  state: ConverterState,
  baseLayerCount: number | undefined,
): number | undefined {
  const overrideLayerCount = state.recipe_overrides.reduce(
    (maximum, override) => Math.max(maximum, override.recipe.length),
    0,
  );
  const resolved = Math.max(baseLayerCount ?? 0, overrideLayerCount);
  return resolved > 0 ? resolved : undefined;
}

export function resolveColorMatchingWeights(
  state: Pick<
    ConverterState,
    | "source_version"
    | "materialDynamicLayerCountEnabled"
    | "hue_enable"
    | "chroma_gate"
  >,
): { hue_weight: number; chroma_gate: number } {
  if (isDynamicMaterialActive(state)) {
    return { hue_weight: 0, chroma_gate: 0 };
  }
  return {
    hue_weight: state.hue_enable ? 0.5 : 0,
    chroma_gate: state.hue_enable ? state.chroma_gate : 0,
  };
}

export function getMaterialArchiveReliefMinimumTotalHeight(
  state: MaterialArchiveReliefMinimumState,
): number {
  if (state.source_version !== "material") {
    return RELIEF_MIN_EXTRA_HEIGHT_MM;
  }
  const layerCount = state.materialDynamicLayerCountEnabled
    ? (state.materialMaxLayerCount ?? state.materialLayerCount)
    : state.materialLayerCount;
  return (
    Math.max(1, Math.round(layerCount)) *
    MATERIAL_ARCHIVE_RELIEF_LAYER_HEIGHT_MM
  );
}

export function getMaterialArchiveReliefMinimumExtraHeight(
  state: MaterialArchiveReliefMinimumState,
): number {
  const minimumTotalHeight = getMaterialArchiveReliefMinimumTotalHeight(state);
  return clampValue(
    minimumTotalHeight - state.spacer_thick,
    RELIEF_MIN_EXTRA_HEIGHT_MM,
    RELIEF_MAX_EXTRA_HEIGHT_MM,
  );
}

export function clampAbsoluteReliefHeightMap(
  map: Record<string, number> | undefined,
  minimumTotalHeight: number,
): Record<string, number> | undefined {
  if (!map) {
    return undefined;
  }
  return Object.fromEntries(
    Object.entries(map).map(([hex, height]) => [
      hex,
      Math.max(height, minimumTotalHeight),
    ]),
  );
}

export function normalizeStringArray(values: string[]): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  for (const value of values) {
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    normalized.push(value);
  }
  return normalized;
}

export function normalizePublicColorMode(value: string): ColorMode {
  return value === "8-Color" ? ColorModeEnum.EIGHT_COLOR : (value as ColorMode);
}

export function normalizeLutColorMode<T extends { color_mode?: string }>(info: T): T {
  if (!info.color_mode) {
    return info;
  }
  const colorMode = normalizePublicColorMode(info.color_mode);
  return colorMode === info.color_mode
    ? info
    : { ...info, color_mode: colorMode };
}

export function normalizeLutDrivenReliefState(
  state: Pick<
    ConverterState,
    "color_mode" | "enable_relief" | "modeling_mode"
  >,
  updates: Partial<ConverterState>,
): Partial<ConverterState> {
  const nextColorMode = updates.color_mode ?? state.color_mode;
  const nextModelingMode = updates.modeling_mode ?? state.modeling_mode;
  if (
    nextModelingMode === ModelingModeEnum.VECTOR &&
    nextColorMode === ColorModeEnum.FIVE_COLOR_EXT
  ) {
    return { ...updates, enable_relief: false };
  }
  return updates;
}

export function normalizeLutGroups<
  TGroup extends { items?: TItem[] },
  TItem extends { color_mode?: string },
>(groups: TGroup[]): TGroup[] {
  return groups.map((group) => ({
    ...group,
    items: (group.items ?? []).map(normalizeLutColorMode),
  }));
}

export function normalizeNativeBrandGroups(
  groups: NativeBrandGroup[],
): NativeBrandGroup[] {
  return groups.map((group) => ({
    ...group,
    db_options: group.db_options.map(normalizeLutColorMode),
  }));
}

export function getNativeBrandGroupByKey(
  groups: NativeBrandGroup[],
  brandKey: string,
): NativeBrandGroup | null {
  return groups.find((group) => group.brand_key === brandKey) ?? null;
}

export function filterNativeBrandGroups(
  groups: NativeBrandGroup[],
): NativeBrandGroup[] {
  return groups.filter((group) => group.brand_key === "bambulab_pla");
}

export function getNativeDbOptionNames(group: NativeBrandGroup | null): string[] {
  return group
    ? normalizeStringArray(group.db_options.map((option) => option.name))
    : [];
}

function hasNativePredictiveModel(group: NativeBrandGroup | null): boolean {
  return Boolean(group?.package_name?.trim() || group?.model_name?.trim());
}

export function buildNativeModelDefaults(
  group: NativeBrandGroup | null,
): Pick<
  ConverterState,
  "model_enable" | "model_only" | "model_threshold" | "model_margin"
> {
  return hasNativePredictiveModel(group)
    ? {
      model_enable: true,
      model_only: false,
      model_threshold: null,
      model_margin: null,
    }
    : {
      model_enable: false,
      model_only: false,
      model_threshold: null,
      model_margin: null,
    };
}

export function buildNativeModelState(
  group: NativeBrandGroup | null,
  currentState?: Pick<
    ConverterState,
    | "selectedNativeBrandKey"
    | "model_enable"
    | "model_only"
    | "model_threshold"
    | "model_margin"
  >,
): Pick<
  ConverterState,
  "model_enable" | "model_only" | "model_threshold" | "model_margin"
> {
  if (!group) {
    return buildNativeModelDefaults(null);
  }
  if (
    currentState &&
    currentState.selectedNativeBrandKey === group.brand_key &&
    hasNativePredictiveModel(group)
  ) {
    return {
      model_enable: currentState.model_enable,
      model_only: currentState.model_only,
      model_threshold: currentState.model_threshold,
      model_margin: currentState.model_margin,
    };
  }
  return buildNativeModelDefaults(group);
}

export function getSelectedNativeBrandGroup(
  state: Pick<ConverterState, "nativeBrandGroups" | "selectedNativeBrandKey">,
): NativeBrandGroup | null {
  if (state.selectedNativeBrandKey) {
    const byKey = getNativeBrandGroupByKey(
      state.nativeBrandGroups,
      state.selectedNativeBrandKey,
    );
    if (byKey) {
      return byKey;
    }
  }
  return state.nativeBrandGroups[0] ?? null;
}

export function getNativeDbNamesForGroup(group: NativeBrandGroup | null): string[] {
  if (!group) {
    return [];
  }

  const allowed = new Set(getNativeDbOptionNames(group));
  return normalizeStringArray(
    group.default_db_names.filter((name) => allowed.has(name)),
  );
}

export function getSupportedModeByPair(
  modes: LutSupportedMode[],
  colorLayers: number | null,
  layerHeightMm: number | null,
): LutSupportedMode | null {
  if (colorLayers == null || layerHeightMm == null) {
    return null;
  }
  return (
    modes.find(
      (mode) =>
        mode.color_layers === colorLayers &&
        mode.layer_height_mm === layerHeightMm,
    ) ?? null
  );
}

export function resolvePreferredSupportedMode(
  modes: LutSupportedMode[],
): LutSupportedMode | null {
  if (modes.length === 0) return null;
  const exactFive = modes.find((mode) => mode.color_layers === 5);
  if (exactFive) return exactFive;
  let preferred = modes[0];
  for (const mode of modes) {
    if (mode.color_layers > preferred.color_layers) {
      preferred = mode;
    }
  }
  return preferred;
}

export function resolveNativeSupportedModeForBrand(
  brand: NativeBrandGroup,
  colorLayers: number | null,
  layerHeightMm: number | null,
): LutSupportedMode | null {
  const supported_modes = brand.supported_modes ?? [];
  const exactMode = getSupportedModeByPair(
    supported_modes,
    colorLayers,
    layerHeightMm,
  );
  if (exactMode) {
    return exactMode;
  }
  const preferredFive = supported_modes.find((mode) => mode.color_layers === 5);
  if (preferredFive) {
    return preferredFive;
  }
  if (layerHeightMm != null) {
    const matchingHeight = supported_modes.filter(
      (mode) => mode.layer_height_mm === layerHeightMm,
    );
    if (matchingHeight.length > 0) {
      if (colorLayers != null) {
        let preferred = matchingHeight[0];
        let smallestDistance = Math.abs(preferred.color_layers - colorLayers);
        for (const mode of matchingHeight.slice(1)) {
          const distance = Math.abs(mode.color_layers - colorLayers);
          if (distance < smallestDistance) {
            preferred = mode;
            smallestDistance = distance;
          }
        }
        return preferred;
      }
      return matchingHeight[0];
    }
  }
  return resolvePreferredSupportedMode(supported_modes);
}

export function resolveNativeBrandSelection(
  state: Pick<
    ConverterState,
    | "nativeBrandGroups"
    | "selectedNativeBrandKey"
    | "selectedNativeDbNames"
    | "color_layers"
    | "layer_height_mm"
  >,
): {
  brand: NativeBrandGroup | null;
  db_names: string[];
  supported_mode: LutSupportedMode | null;
  supported_modes: LutSupportedMode[];
  predictive_model_available: boolean;
  isReady: boolean;
} {
  const brand = getSelectedNativeBrandGroup(state);
  if (!brand) {
    return {
      brand: null,
      db_names: [],
      supported_mode: null,
      supported_modes: [],
      predictive_model_available: false,
      isReady: false,
    };
  }

  const allowedNames = new Set(getNativeDbOptionNames(brand));
  const selectedDbNames = normalizeStringArray(
    state.selectedNativeDbNames.filter((name) => allowedNames.has(name)),
  );
  const db_names =
    state.selectedNativeDbNames.length === 0
      ? []
      : selectedDbNames.length > 0
        ? selectedDbNames
        : normalizeStringArray(
          brand.default_db_names.filter((name) => allowedNames.has(name)),
        );
  const supported_modes = brand.supported_modes ?? [];
  const supported_mode = resolveNativeSupportedModeForBrand(
    brand,
    state.color_layers,
    state.layer_height_mm,
  );

  return {
    brand,
    db_names,
    supported_mode,
    supported_modes,
    predictive_model_available: hasNativePredictiveModel(brand),
    isReady: db_names.length > 0 && supported_mode != null,
  };
}

export function resolveConverterSourceSelection(
  state: Pick<
    ConverterState,
    | "source_version"
    | "lut_name"
    | "lut_names"
    | "nativeBrandGroups"
    | "selectedNativeBrandKey"
    | "selectedNativeDbNames"
    | "color_layers"
    | "layer_height_mm"
    | "selectedMaterialDirNames"
    | "materialLayerCount"
    | "materialLayerHeightMm"
  > &
    Partial<
      Pick<
        ConverterState,
        | "lutListFull"
        | "legacyCatalogGroups"
        | "materialDynamicLayerCountEnabled"
        | "materialMaxLayerCount"
      >
    >,
): {
  source_kind: "legacy_single" | "legacy_multi" | "native_bundle";
  isReady: boolean;
  isMaterial: boolean;
  lut_name: string;
  db_names: string[];
  native: ReturnType<typeof resolveNativeBrandSelection>;
  color_layers: number | null;
  layer_height_mm: number | null;
} {
  const emptyNative = {
    brand: null,
    db_names: [] as string[],
    supported_mode: null,
    supported_modes: [] as { color_layers: number; layer_height_mm: number }[],
    predictive_model_available: false,
    isReady: false,
  };

  if (state.source_version === "material") {
    return {
      source_kind: "legacy_single",
      isReady: (state.selectedMaterialDirNames ?? []).length > 0,
      isMaterial: true,
      lut_name: "",
      db_names: [],
      native: emptyNative,
      color_layers: resolveMaterialPrintLayerCount(state),
      layer_height_mm: state.materialLayerHeightMm ?? 0.08,
    };
  }

  if (state.source_version === "legacy") {
    const lutNames = normalizeLegacyLutNames(state.lut_names, state.lut_name);
    return {
      source_kind: lutNames.length > 1 ? "legacy_multi" : "legacy_single",
      isReady: lutNames.length > 0,
      isMaterial: false,
      lut_name: lutNames[0] ?? "",
      db_names: [],
      native: emptyNative,
      color_layers: null,
      layer_height_mm: null,
    };
  }

  const native = resolveNativeBrandSelection(state);
  return {
    source_kind: "native_bundle",
    isReady: native.isReady,
    isMaterial: false,
    lut_name: "",
    db_names: native.db_names,
    native,
    color_layers: native.supported_mode?.color_layers ?? null,
    layer_height_mm: native.supported_mode?.layer_height_mm ?? null,
  };
}

export function buildLegacySourceParams(
  state: Pick<ConverterState, "lut_name" | "lut_names">,
) {
  const lutNames = normalizeLegacyLutNames(state.lut_names, state.lut_name);
  const primaryName = lutNames[0] ?? state.lut_name;
  if (lutNames.length > 1) {
    return {
      source_kind: "legacy_multi" as const,
      lut_name: primaryName,
      lut_names: lutNames,
    };
  }
  return {
    source_kind: "legacy_single" as const,
    lut_name: primaryName,
  };
}

export function buildMaterialSourceParams(
  state: Pick<
    ConverterState,
    | "selectedMaterialDirNames"
    | "source_version"
    | "materialLayerCount"
    | "materialLayerHeightMm"
    | "materialBackingMaterialDirName"
    | "materialDynamicLayerCountEnabled"
    | "materialMinLayerCount"
    | "materialMaxLayerCount"
  >,
) {
  const settingsState = useSettingsStore.getState();
  const materialGridResolution = settingsState.enableSolverCacheGridSelection
    ? settingsState.solverCacheGridResolution
    : undefined;
  const resolvedBackingDirName =
    state.materialBackingMaterialDirName &&
      state.selectedMaterialDirNames.includes(state.materialBackingMaterialDirName)
      ? state.materialBackingMaterialDirName
      : inferDefaultMaterialBackingDirName(state.selectedMaterialDirNames);
  const backingMaterialIndex = resolvedBackingDirName
    ? state.selectedMaterialDirNames.indexOf(resolvedBackingDirName)
    : -1;
  const printLayerCount = resolveMaterialPrintLayerCount(state);
  return {
    source_kind: "legacy_single" as const,
    lut_name: "__material_archive__",
    material_source: "material_archive" as const,
    selected_materials: state.selectedMaterialDirNames,
    material_layer_count: printLayerCount,
    material_layer_height_mm: state.materialLayerHeightMm,
    material_grid_resolution: materialGridResolution,
    material_backing_material_index:
      backingMaterialIndex >= 0 ? backingMaterialIndex : 0,
    material_dynamic_layer_count_enabled: isDynamicMaterialActive(state),
    material_min_layer_count: state.materialMinLayerCount,
    material_max_layer_count: state.materialMaxLayerCount,
    material_delta_e00_tolerance: settingsState.materialDeltaE00Tolerance,
  };
}

export function buildNativeSourceParams(
  selection: ReturnType<typeof resolveConverterSourceSelection>,
  modelState?: Pick<
    ConverterState,
    "model_enable" | "model_only" | "model_threshold" | "model_margin"
  >,
) {
  if (selection.source_kind !== "native_bundle" || !selection.native.brand) {
    return null;
  }
  const supportedMode = selection.native.supported_mode;

  return {
    source_kind: "native_bundle" as const,
    material_type: selection.native.brand.material_type,
    vendor: selection.native.brand.vendor,
    db_names: selection.native.db_names,
    color_layers: supportedMode?.color_layers ?? undefined,
    layer_height_mm: supportedMode?.layer_height_mm ?? undefined,
    ...(selection.native.predictive_model_available
      ? {
        model_enable: modelState?.model_enable ?? false,
        model_only: modelState?.model_only ?? false,
        model_threshold: modelState?.model_threshold ?? undefined,
        model_margin: modelState?.model_margin ?? undefined,
      }
      : {}),
  };
}

export function normalizeLegacyLutNames(
  lutNames: string[] | undefined,
  fallbackLutName: string,
): string[] {
  const ordered = [
    ...(fallbackLutName ? [fallbackLutName] : []),
    ...(lutNames ?? []),
  ];
  const seen = new Set<string>();
  return ordered.filter((name) => {
    const trimmed = name.trim();
    if (!trimmed || seen.has(trimmed)) {
      return false;
    }
    seen.add(trimmed);
    return true;
  });
}

export function buildConversionSourceParams(state: ConverterState) {
  return state.source_version === "material"
    ? buildMaterialSourceParams(state)
    : state.source_version === "native"
      ? buildNativeSourceParams(resolveConverterSourceSelection(state), state)
      : buildLegacySourceParams(state);
}
