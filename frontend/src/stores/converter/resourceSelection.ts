import { create } from "zustand";
import { apiErrorToVisibleMessage } from "../../api/client";
import { installExtractedLut } from "../../api/extractor";
import type { ResourceKind } from "../../api/resources";
import { tRuntime } from "../../i18n/runtime";
import { useWidgetStore } from "../widgetStore";
import { useConverterStore } from "./store";
import { getCompatibilityBucket, normalizeLutPath } from "./legacyLutSelection";
import { normalizePublicColorMode } from "./sources";
import { useCalibrationStore } from "../calibrationStore";

type LutTrialBackup = Pick<ReturnType<typeof useConverterStore.getState>,
  "imageFile" | "batchFiles" | "modelSurfaceFile" | "lut_name" | "lut_names" | "color_mode" |
  "color_layers" | "layer_height_mm" | "hue_enable" | "model_enable" | "model_only" | "model_threshold" | "model_margin">;

export const useMaterialTrialStore = create<{ backup: LutTrialBackup | null }>(() => ({ backup: null }));

export function restoreTrialLut(): void {
  const { backup } = useMaterialTrialStore.getState();
  const current = useConverterStore.getState();
  if (!backup || current.imageFile !== backup.imageFile || current.batchFiles !== backup.batchFiles
    || current.modelSurfaceFile !== backup.modelSurfaceFile) return;
  const { imageFile: _image, batchFiles: _batch, modelSurfaceFile: _surface, ...settings } = backup;
  current.setSourceVersion("legacy");
  useConverterStore.setState(settings);
  useMaterialTrialStore.setState({ backup: null });
  if (current.imageFile) void useConverterStore.getState().submitPreview();
}

export interface ResourceSelectionCheck {
  error?: string;
  modeChange?: string;
}

/** Refresh inventory without reconciling or changing the current task's selection. */
export function refreshConverterResources(): Promise<void> {
  return useConverterStore.getState().refreshResourceCatalog();
}

/** A picker belongs to one task. Once that task changes, it cannot apply again. */
export function createResourceSelectionIntent(options: { materialTrial?: boolean; initialQuery?: string } = {}) {
  const owner = useConverterStore.getState();
  let stale = false;
  const unsubscribe = useConverterStore.subscribe((current) => {
    if (current.imageFile !== owner.imageFile || current.sessionId !== owner.sessionId
      || current.batchFiles !== owner.batchFiles || current.modelSurfaceFile !== owner.modelSurfaceFile
      || current.source_version !== owner.source_version || current.color_mode !== owner.color_mode
      || current.conversionParameterContext !== owner.conversionParameterContext) stale = true;
  });
  const checkLuts = (names: string[]): ResourceSelectionCheck => {
    if (stale) return { error: "resources_task_changed" };
    const state = useConverterStore.getState();
    const entries = names.map((name) => state.lutListFull.find((entry) => entry.name === name));
    if (entries.some((entry) => !entry)) return { error: "resources_lut_unavailable" };
    const modes = new Set(entries.map((entry) => normalizePublicColorMode(entry!.color_mode)));
    const details = state.legacyCatalogGroups.flatMap((group) => group.items);
    const compatibility = new Set(entries.map((entry) => {
      const detail = details.find((item) => normalizeLutPath(item.path) === normalizeLutPath(entry!.path));
      return detail ? getCompatibilityBucket(detail) : normalizePublicColorMode(entry!.color_mode);
    }));
    if (modes.size > 1 || compatibility.size > 1) return { error: "resources_incompatible_lut" };
    const mode = [...modes][0];
    return mode && mode !== normalizePublicColorMode(state.color_mode) ? { modeChange: mode } : {};
  };
  return {
    materialTrial: options.materialTrial ?? false,
    initialQuery: options.initialQuery ?? "",
    dispose: () => { stale = true; unsubscribe(); },
    checkLuts,
    checkMaterials: () => stale ? "resources_task_changed" : null,
    applyLuts: (names: string[], allowModeChange = false): string | null => {
      const check = checkLuts(names);
      if (check.error) return check.error;
      if (check.modeChange && !allowModeChange) return "resources_incompatible_lut";
      useConverterStore.getState().setLegacyLutNames(names);
      return null;
    },
    applyMaterials: (names: string[]): string | null => {
      if (stale) return "resources_task_changed";
      if (options.materialTrial && names.length === 0) return "material_guide_select_required";
      if (options.materialTrial) {
        const current = useConverterStore.getState();
        if (current.source_version === "legacy") {
          const { imageFile, batchFiles, modelSurfaceFile, lut_name, lut_names, color_mode,
            color_layers, layer_height_mm, hue_enable, model_enable, model_only, model_threshold, model_margin } = current;
          useMaterialTrialStore.setState({ backup: { imageFile, batchFiles, modelSurfaceFile, lut_name, lut_names, color_mode,
            color_layers, layer_height_mm, hue_enable, model_enable, model_only, model_threshold, model_margin } });
        }
        current.setSourceVersion("material");
      }
      useConverterStore.getState().setSelectedMaterialDirNames(names);
      return null;
    },
  };
}

type SelectionIntent = ReturnType<typeof createResourceSelectionIntent>;
interface CalibrationSelection {
  id: number;
  family: ResourceKind;
  selected: string[];
  intent: SelectionIntent;
  phase: "calibrating" | "ready";
}

/** In-memory, single-use ownership transfer while a picker visits calibration. */
export const useResourceCalibrationStore = create<{
  context: CalibrationSelection | null;
  returning: boolean;
  error: string | null;
}>(() => ({ context: null, returning: false, error: null }));
let calibrationId = 0;

export function discardResourceCalibration(): void {
  useResourceCalibrationStore.getState().context?.intent.dispose();
  useResourceCalibrationStore.setState({ context: null, returning: false, error: null });
}

export function beginResourceCalibration(family: ResourceKind, selected: string[], intent: SelectionIntent): void {
  discardResourceCalibration();
  if (family === "materials") {
    const height = useConverterStore.getState().materialLayerHeightMm;
    if ([0.04, 0.08, 0.1].includes(height)) useCalibrationStore.getState().setSingleStageLayerHeightMm(height);
  }
  useResourceCalibrationStore.setState({ context: { id: ++calibrationId, family, selected: [...selected], intent, phase: "calibrating" } });
  useWidgetStore.getState().setActiveTab(family === "materials" ? "gradient-card-generate" : "calibration");
}

export function takeResourceCalibrationReturn(family: ResourceKind): CalibrationSelection | null {
  const { context } = useResourceCalibrationStore.getState();
  if (!context || context.family !== family || context.phase !== "ready") return null;
  useResourceCalibrationStore.setState({ context: null, returning: false, error: null });
  return context;
}

export async function returnFromResourceCalibration(family: ResourceKind, resource: string): Promise<void> {
  const { context, returning } = useResourceCalibrationStore.getState();
  if (!context || context.family !== family || context.phase !== "calibrating" || returning) return;
  useResourceCalibrationStore.setState({ returning: true, error: null });
  try {
    const name = family === "luts" ? (await installExtractedLut(resource)).name : resource;
    if (family === "luts") await refreshConverterResources();
    if (useResourceCalibrationStore.getState().context !== context) return;
    // A successful save remains in the library even if its original task changed.
    const error = context.intent.checkMaterials();
    if (error) {
      useResourceCalibrationStore.setState({ error: tRuntime("resources_calibration_task_changed") });
      return;
    }
    useResourceCalibrationStore.setState({ context: { ...context, phase: "ready", selected: [...new Set([...context.selected, name])] } });
    useWidgetStore.getState().setActiveTab("converter");
  } catch (error) {
    if (useResourceCalibrationStore.getState().context === context) {
      useResourceCalibrationStore.setState({ error: apiErrorToVisibleMessage(error, tRuntime("resources_calibration_return_failed")) });
    }
  } finally {
    if (useResourceCalibrationStore.getState().context?.id === context.id) useResourceCalibrationStore.setState({ returning: false });
  }
}
