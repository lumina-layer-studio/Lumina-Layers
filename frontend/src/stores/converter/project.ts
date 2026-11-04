import type { SettingsState } from "../settingsStore";
import type { ConverterState } from "./types";

/** Only output-affecting preferences travel with an artwork. */
export const PROJECT_SETTING_KEYS = [
  "printerModel", "slicerSoftware", "nozzleSize", "deviceProfileId", "buildPlateId",
  "custom3mfTemplateId", "enableBaseLayerHeightModifier", "enableWipeTowerAutoPlacement",
  "svgPixelsPerMm", "materialDeltaE00Tolerance", "enableSolverCacheGridSelection",
  "solverCacheGridResolution", "preserveUploadFilenameFor3mf",
] as const satisfies readonly (keyof SettingsState)[];

export type ProjectConverterSettings = Pick<SettingsState, typeof PROJECT_SETTING_KEYS[number]>;

export function captureProjectSettings(settings: SettingsState): ProjectConverterSettings {
  return Object.fromEntries(PROJECT_SETTING_KEYS.map((key) => [key, settings[key]])) as ProjectConverterSettings;
}

export function resolveConverterSettings(
  state: { projectSettings?: ProjectConverterSettings | null },
  settings: SettingsState,
): SettingsState {
  return state.projectSettings ? { ...settings, ...state.projectSettings } : settings;
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
