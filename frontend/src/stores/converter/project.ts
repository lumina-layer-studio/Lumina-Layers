import type { PrinterInfo } from "../../api/types";
import { resolveDeviceProfileOptionId, resolveNozzleSizeOption, resolvePrinterOptionId, normalizeSlicerOptionId } from "../../utils/settingsOptionIds";
import { resolveBuildPlateSelection, type SettingsState, type NozzleSize } from "../settingsStore";
import type { ConverterState } from "./types";

/** Only output-affecting preferences travel with an artwork. */
export const PROJECT_SETTING_KEYS = [
  "printerModel", "slicerSoftware", "nozzleSize", "deviceProfileId", "buildPlateId",
  "custom3mfTemplateId", "enableBaseLayerHeightModifier", "enableWipeTowerAutoPlacement",
  "svgPixelsPerMm", "materialDeltaE00Tolerance", "enableSolverCacheGridSelection",
  "solverCacheGridResolution", "preserveUploadFilenameFor3mf",
] as const satisfies readonly (keyof SettingsState)[];

type StoredProjectSettings = Pick<SettingsState, typeof PROJECT_SETTING_KEYS[number]>;
export type ProjectConverterSettings = StoredProjectSettings & {
  /** Session-local choices. Only the active palette's material travels, in the recipe. */
  externalSpoolSelections?: SettingsState["externalSpoolSelections"];
};

export function captureProjectSettings(settings: SettingsState): StoredProjectSettings {
  return Object.fromEntries(PROJECT_SETTING_KEYS.map((key) => [key, settings[key]])) as StoredProjectSettings;
}

export function resolveConverterSettings(
  state: { projectSettings?: ProjectConverterSettings | null },
  settings: SettingsState,
): SettingsState {
  return state.projectSettings
    ? { ...settings, ...state.projectSettings, externalSpoolSelections: state.projectSettings.externalSpoolSelections ?? {} }
    : settings;
}

/** Resolve the coupled machine/profile/plate fields as one settings change. */
export function resolveProjectDeviceSettings(
  current: ProjectConverterSettings,
  changes: Partial<ProjectConverterSettings>,
  printers: PrinterInfo[],
): ProjectConverterSettings {
  const next = { ...current, ...changes };
  next.slicerSoftware = normalizeSlicerOptionId(next.slicerSoftware);
  next.printerModel = resolvePrinterOptionId(next.printerModel, printers, next.slicerSoftware);
  const printer = printers.find((item) => item.id === next.printerModel);
  next.nozzleSize = resolveNozzleSizeOption(next.nozzleSize, printer, next.slicerSoftware) as NozzleSize;
  next.deviceProfileId = resolveDeviceProfileOptionId(next.deviceProfileId, printer, next.slicerSoftware, next.nozzleSize);
  const profile = printer?.device_profiles?.find((item) => item.device_profile_id === next.deviceProfileId);
  if (printer) {
    const machineId = profile?.machine_profile_id ?? "";
    next.buildPlateId = resolveBuildPlateSelection(
      machineId, profile?.build_plates?.map((plate) => plate.id) ?? [],
      profile?.default_build_plate_id ?? "",
      machineId ? { [machineId]: next.buildPlateId } : {},
    ).plateId;
  }
  if (next.slicerSoftware !== current.slicerSoftware && changes.custom3mfTemplateId === undefined) next.custom3mfTemplateId = null;
  return next;
}

export function converterSourceKey(state: Pick<ConverterState,
  "source_version" | "lut_name" | "lut_names" | "selectedNativeBrandKey" | "selectedNativeDbNames" | "selectedMaterialDirNames"
>): string {
  return JSON.stringify(state.source_version === "material"
    ? ["material", state.selectedMaterialDirNames]
    : state.source_version === "native"
      ? ["native", state.selectedNativeBrandKey, state.selectedNativeDbNames]
      : ["legacy", state.lut_name, state.lut_names]);
}

export function boundProjectResources(state: ConverterState) {
  return state.projectSourceKey === converterSourceKey(state)
    ? { lut: state.projectLutFile, materials: state.projectMaterialArchiveFile }
    : { lut: null, materials: null };
}

/** Catalogs belong to this installation and can finish loading during restore. */
export function withCurrentConverterCatalogs(state: ConverterState, current: ConverterState): ConverterState {
  const boundNames = boundProjectResources(state).lut ? new Set([state.lut_name, ...state.lut_names].filter(Boolean)) : new Set<string>();
  const boundBrand = boundProjectResources(state).lut
    ? state.nativeBrandGroups.find((brand) => brand.brand_key === state.selectedNativeBrandKey)
    : undefined;
  return {
    ...state,
    bedSizes: current.bedSizes,
    bedSizesLoading: current.bedSizesLoading,
    lutListLoading: current.lutListLoading,
    lutList: [...new Set([...current.lutList, ...boundNames])],
    lutListFull: [...current.lutListFull.filter((lut) => !boundNames.has(lut.name)), ...state.lutListFull.filter((lut) => boundNames.has(lut.name))],
    nativeBrandGroupsLoading: current.nativeBrandGroupsLoading,
    nativeBrandGroups: boundBrand ? [...current.nativeBrandGroups.filter((brand) => brand.brand_key !== boundBrand.brand_key), boundBrand] : current.nativeBrandGroups,
  };
}
