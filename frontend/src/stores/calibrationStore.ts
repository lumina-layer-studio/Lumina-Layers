import { workflowRuntime, workflowSettings } from "../project/workflowRuntime";
import { create } from "zustand";
import { apiErrorToVisibleMessage } from "../api/client";
import type { CalibrationColorMode } from "../api/types";
import { CalibrationColorMode as CalibrationColorModeEnum } from "../api/types";
import {
  calibrationGenerate,
  generateSingleStageKit,
} from "../api/calibration";
import { tRuntime } from "../i18n/runtime";
import {
  showBrowserCompletionNotification,
  type CompletionNotificationKind,
} from "../utils/browserNotifications";
import { clampValue } from "./converter";
import {
  captureGeneratedArtifactIdentity,
  isGeneratedArtifactIdentityCurrent,
  registerGeneratedArtifactInvalidator,
} from "./generatedArtifactInvalidation";
import { useSettingsStore } from "./settingsStore";

export type CalibrationWorkflow = "legacy" | "single-stage";
const SINGLE_STAGE_LAYER_HEIGHT_OPTIONS = [0.04, 0.08, 0.1] as const;
let calibrationGenerateSequence = 0;

function notifyCompletion(kind: CompletionNotificationKind): void {
  const settings = useSettingsStore.getState();
  if (!settings.enableCompletionNotifications) return;
  showBrowserCompletionNotification(kind, settings.language);
}

/** Backing thickness slider bounds (mm). Mirrors the backend
 * `MIN_BACKING_THICKNESS_MM` / `MAX_BACKING_THICKNESS_MM` constants. */
export const BACKING_THICKNESS_MIN_MM = 0.4;
export const BACKING_THICKNESS_MAX_MM = 3.5;
export const BACKING_THICKNESS_STEP_MM = 0.08;
export const BACKING_THICKNESS_DEFAULT_MM = 1.2;

function normalizeSingleStageLayerHeight(value: number): number {
  return SINGLE_STAGE_LAYER_HEIGHT_OPTIONS.includes(
    value as (typeof SINGLE_STAGE_LAYER_HEIGHT_OPTIONS)[number],
  )
    ? value
    : 0.08;
}

function buildSingleStagePalette(materialDefault: string) {
  return [
    {
      color: "Sample",
      material: materialDefault,
      hex_color: "#808080",
      color_name: "Sample",
    },
  ];
}

function hasApiResponse(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "response" in error
  );
}

function calibrationErrorToVisibleMessage(error: unknown): string {
  const fallback = tRuntime("calibration_generation_failed");
  if (!(error instanceof Error) && !hasApiResponse(error)) {
    return fallback;
  }
  return apiErrorToVisibleMessage(
    error,
    fallback,
  );
}

export interface CalibrationState {
  workflow: CalibrationWorkflow;
  lastSubmittedWorkflow: CalibrationWorkflow | null;
  color_mode: CalibrationColorMode;
  block_size: number;
  gap: number;
  backing_thickness: number;
  eight_color_full_export: boolean;
  substrateId: string;
  substrateDisplayName: string;
  materialDefault: string;
  singleStageLayerHeightMm: number;
  isLoading: boolean;
  error: string | null;
  downloadUrl: string | null;
  threemfDiskPath: string | null;
  previewImageUrl: string | null;
  layerImageUrls: string[] | null;
  modelUrl: string | null;
  statusMessage: string | null;
  warnings: string[];
  manifestUrl: string | null;
  singleStageJobs: Array<{
    color: string;
    color_name: string;
    material: string;
    substrate_id: string;
    substrate_display_name: string;
    filename: string;
  }>;
}

export interface CalibrationActions {
  setWorkflow: (workflow: CalibrationWorkflow) => void;
  setColorMode: (mode: CalibrationColorMode) => void;
  setBlockSize: (size: number) => void;
  setGap: (gap: number) => void;
  setBackingThickness: (thickness: number) => void;
  setEightColorFullExport: (enabled: boolean) => void;
  setSubstrateId: (value: string) => void;
  setSubstrateDisplayName: (value: string) => void;
  setMaterialDefault: (value: string) => void;
  setSingleStageLayerHeightMm: (value: number) => void;
  submitLegacyGenerate: () => Promise<void>;
  submitSingleStageGenerate: () => Promise<void>;
  submitGenerate: () => Promise<void>;
  setError: (error: string | null) => void;
  clearError: () => void;
}

const DEFAULT_STATE: CalibrationState = {
  workflow: "legacy",
  lastSubmittedWorkflow: null,
  color_mode: CalibrationColorModeEnum.FOUR_COLOR_RYBW,
  block_size: 5,
  gap: 0.84,
  backing_thickness: BACKING_THICKNESS_DEFAULT_MM,
  eight_color_full_export: false,
  substrateId: "white",
  substrateDisplayName: "White",
  materialDefault: "PLA Basic",
  singleStageLayerHeightMm: 0.08,
  isLoading: false,
  error: null,
  downloadUrl: null,
  threemfDiskPath: null,
  previewImageUrl: null,
  layerImageUrls: null,
  modelUrl: null,
  statusMessage: null,
  warnings: [],
  manifestUrl: null,
  singleStageJobs: [],
};

export const useCalibrationStore = create<
  CalibrationState & CalibrationActions
>((set, get) => ({
  ...DEFAULT_STATE,

  setWorkflow: (workflow: CalibrationWorkflow) =>
    set({
      workflow,
      downloadUrl: null,
      threemfDiskPath: null,
      previewImageUrl: null,
      layerImageUrls: null,
      manifestUrl: null,
      singleStageJobs: [],
      statusMessage: null,
      warnings: [],
      error: null,
    }),

  setColorMode: (mode: CalibrationColorMode) =>
    set((state) => ({
      color_mode: mode,
      eight_color_full_export:
        mode === CalibrationColorModeEnum.EIGHT_COLOR
          ? state.eight_color_full_export
          : false,
    })),

  setBlockSize: (size: number) => set({ block_size: clampValue(size, 3, 10) }),

  setGap: (gap: number) => set({ gap: clampValue(gap, 0.4, 2.0) }),

  setBackingThickness: (thickness: number) =>
    set({
      backing_thickness: clampValue(
        thickness,
        BACKING_THICKNESS_MIN_MM,
        BACKING_THICKNESS_MAX_MM,
      ),
    }),

  setEightColorFullExport: (enabled: boolean) =>
    set({ eight_color_full_export: enabled }),

  setSubstrateId: (value: string) => set({ substrateId: value }),

  setSubstrateDisplayName: (value: string) =>
    set({ substrateDisplayName: value }),

  setMaterialDefault: (value: string) => set({ materialDefault: value }),
  setSingleStageLayerHeightMm: (value: number) =>
    set({ singleStageLayerHeightMm: normalizeSingleStageLayerHeight(value) }),

  submitLegacyGenerate: async () => {
    const state = get();
    const settings = workflowSettings("calibration");
    const requestIdentity = captureGeneratedArtifactIdentity(
      settings.deviceProfileId,
      settings.buildPlateId,
      !workflowRuntime("calibration")?.settings,
    );
    const requestSequence = ++calibrationGenerateSequence;
    const isCurrentRequest = (): boolean => {
      const latestSettings = workflowSettings("calibration");
      return (
        requestSequence === calibrationGenerateSequence &&
        isGeneratedArtifactIdentityCurrent(
          requestIdentity,
          latestSettings.deviceProfileId,
          latestSettings.buildPlateId,
        )
      );
    };
    // Warnings stay with the downloadable artifact until a result replaces it.
    set({ isLoading: true, error: null, lastSubmittedWorkflow: "legacy" });
    try {
      const response = await calibrationGenerate({
        color_mode: state.color_mode,
        block_size: state.block_size,
        gap: state.gap,
        backing_thickness: state.backing_thickness,
        eight_color_full_export: state.eight_color_full_export,
        printer_id: settings.printerModel,
        slicer: settings.slicerSoftware,
        nozzle_size: settings.nozzleSize,
        device_profile_id: settings.deviceProfileId,
        build_plate_id: settings.buildPlateId,
        custom_3mf_template_id: settings.custom3mfTemplateId,
      });
      if (!isCurrentRequest()) return;
      set({
        downloadUrl: response.download_url,
        threemfDiskPath: null,
        previewImageUrl: response.preview_url ?? null,
        layerImageUrls: response.layer_urls ?? null,
        modelUrl: null,
        manifestUrl: null,
        singleStageJobs: [],
        statusMessage: response.message,
        warnings: response.warnings ?? [],
        isLoading: false,
      });
      notifyCompletion("calibration");
    } catch (err) {
      if (!isCurrentRequest()) return;
      set({
        error: calibrationErrorToVisibleMessage(err),
        isLoading: false,
      });
    }
  },

  submitSingleStageGenerate: async () => {
    const state = get();
    const settings = workflowSettings("calibration");
    const requestIdentity = captureGeneratedArtifactIdentity(
      settings.deviceProfileId,
      settings.buildPlateId,
      !workflowRuntime("calibration")?.settings,
    );
    const requestSequence = ++calibrationGenerateSequence;
    const isCurrentRequest = (): boolean => {
      const latestSettings = workflowSettings("calibration");
      return (
        requestSequence === calibrationGenerateSequence &&
        isGeneratedArtifactIdentityCurrent(
          requestIdentity,
          latestSettings.deviceProfileId,
          latestSettings.buildPlateId,
        )
      );
    };
    set({
      isLoading: true,
      error: null,
      lastSubmittedWorkflow: "single-stage",
    });
    try {
      const response = await generateSingleStageKit({
        palette: buildSingleStagePalette(state.materialDefault),
        substrate_id: state.substrateId,
        substrate_display_name: state.substrateDisplayName,
        material_default: state.materialDefault,
        layer_height_mm: state.singleStageLayerHeightMm,
        printer_id: settings.printerModel,
        slicer: settings.slicerSoftware,
        nozzle_size: settings.nozzleSize,
        device_profile_id: settings.deviceProfileId,
        build_plate_id: settings.buildPlateId,
        custom_3mf_template_id: settings.custom3mfTemplateId,
      });
      if (!isCurrentRequest()) return;
      set({
        downloadUrl: response.kit_download_url,
        threemfDiskPath: null,
        previewImageUrl: response.preview_url ?? null,
        modelUrl: null,
        manifestUrl: response.manifest_url,
        singleStageJobs: response.jobs ?? [],
        statusMessage: response.message,
        warnings: [],
        isLoading: false,
      });
      notifyCompletion("calibration");
    } catch (err) {
      if (!isCurrentRequest()) return;
      set({
        error: calibrationErrorToVisibleMessage(err),
        isLoading: false,
      });
    }
  },

  submitGenerate: async () => {
    if (get().workflow === "single-stage") {
      await get().submitSingleStageGenerate();
      return;
    }

    await get().submitLegacyGenerate();
  },

  setError: (error: string | null) => set({ error }),
  clearError: () => set({ error: null }),
}));

registerGeneratedArtifactInvalidator(({ preservePreviews, source }) => {
  if (source === "defaults" && workflowRuntime("calibration")?.settings) return;
  calibrationGenerateSequence += 1;
  useCalibrationStore.setState({
    isLoading: false,
    error: null,
    downloadUrl: null,
    threemfDiskPath: null,
    statusMessage: null,
    warnings: [],
    manifestUrl: null,
    singleStageJobs: [],
    ...(preservePreviews
      ? {}
      : {
          previewImageUrl: null,
          layerImageUrls: null,
          modelUrl: null,
        }),
  });
});
