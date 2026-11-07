import type { ExportMaterialSelection } from "../../api/types";
import type { SettingsState } from "../settingsStore";
import type { ConverterState, NativeFilamentProfileScope } from "./types";
import { normalizeSlicerOptionId } from "../../utils/settingsOptionIds";
import { normalizeLegacyLutNames } from "./sources";

export function supportsExternalSpool(settings: SettingsState): boolean {
  return !settings.custom3mfTemplateId && normalizeSlicerOptionId(settings.slicerSoftware) === "BambuStudio" &&
    (settings.deviceProfileId
      ? settings.deviceProfileId.startsWith("BambuStudio:bbl:bambu-lab-x2d:")
      : settings.printerModel === "bambu-lab-x2d");
}

/** Material names stay attached to their palette even when its channels are reordered. */
export function externalSpoolPaletteKey(state: ConverterState): string {
  if (state.source_version === "material") {
    return JSON.stringify(["material", ...[...state.selectedMaterialDirNames].sort()]);
  }
  if (state.source_version === "native") {
    return JSON.stringify(["native", state.selectedNativeBrandKey, ...[...state.selectedNativeDbNames].sort()]);
  }
  const lutNames = normalizeLegacyLutNames(state.lut_names, state.lut_name);
  return JSON.stringify(["legacy", state.color_mode, ...lutNames.sort()]);
}

export function externalSpoolMaterial(state: ConverterState, settings: SettingsState): string | undefined {
  return supportsExternalSpool(settings) ? settings.externalSpoolSelections[externalSpoolPaletteKey(state)] : undefined;
}

/** An external spool must resolve to exactly one exported slot. */
export function selectableExternalSpoolMaterials(selection: ExportMaterialSelection): string[] {
  const names = selection.materials.map(({ name }) => name);
  return names.filter((name, index) => names.indexOf(name) === index && names.lastIndexOf(name) === index);
}

/** The exact hardware target that owns the user's native filament choices. */
export function nativeFilamentProfileScope(
  settings: SettingsState,
): NativeFilamentProfileScope {
  return {
    slicer: settings.slicerSoftware,
    printer_id: settings.printerModel,
    device_profile_id: settings.deviceProfileId,
    nozzle_size: settings.nozzleSize,
  };
}

/** Omit choices made for a different slicer, machine, or nozzle. */
export function scopedNativeFilamentProfiles(
  state: Pick<ConverterState, "native_filament_profiles" | "nativeFilamentProfileScope">,
  settings: SettingsState,
): Record<string, string> | undefined {
  const scope = state.nativeFilamentProfileScope;
  if (!scope) return undefined;
  const target = nativeFilamentProfileScope(settings);
  if (
    scope.slicer !== target.slicer ||
    scope.printer_id !== target.printer_id ||
    scope.device_profile_id !== target.device_profile_id ||
    scope.nozzle_size !== target.nozzle_size
  ) return undefined;
  const profiles = state.native_filament_profiles;
  return Object.keys(profiles).length > 0 ? { ...profiles } : undefined;
}

/** Recover the same actionable selection when the final export rejects it. */
export function materialSelectionFromExportError(
  error: unknown,
): ExportMaterialSelection | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  const response = (error as { response?: { status?: number; data?: unknown } }).response;
  if (response?.status !== 422 || !response.data || typeof response.data !== "object") {
    return null;
  }
  const detail = (response.data as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return null;
  const rejection = detail as { error?: unknown; material_selection?: unknown };
  if (rejection.error !== "native_material_selection_required") return null;
  const selection = rejection.material_selection as ExportMaterialSelection | undefined;
  return selection && typeof selection.ready === "boolean" &&
    Array.isArray(selection.materials) && Array.isArray(selection.build_plates) &&
    Array.isArray(selection.issues)
    ? selection
    : null;
}
