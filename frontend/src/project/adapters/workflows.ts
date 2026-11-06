import { useCalibrationStore } from "../../stores/calibrationStore";
import { useExtractorStore } from "../../stores/extractorStore";
import { useSingleStageStore } from "../../stores/singleStageStore";
import { useFiveColorStore } from "../../stores/fiveColorStore";
import { useLutManagerStore } from "../../stores/lutManagerStore";
import { useLutCompareStore } from "../../stores/lutCompareStore";
import { useLutDetailsStore } from "../../stores/lutDetailsStore";
import { useVectorizerStore } from "../../stores/vectorizerStore";
import { createWorkflowAdapter } from "./workflowAdapter";

export function createWorkflowAdapters() {
  return [
    createWorkflowAdapter({
      kind: "calibration", store: useCalibrationStore, busy: ["isLoading"],
      fields: ["workflow", "lastSubmittedWorkflow", "color_mode", "block_size", "gap", "backing_thickness", "eight_color_full_export", "substrateId", "substrateDisplayName", "materialDefault", "singleStageLayerHeightMm", "downloadUrl", "previewImageUrl", "layerImageUrls", "modelUrl", "statusMessage", "warnings", "manifestUrl", "singleStageJobs"],
    }),
    createWorkflowAdapter({
      kind: "extractor", store: useExtractorStore,
      busy: ["isLoading", "manualFixLoading", "mergeLoading", "paletteConfirmLoading"],
      fields: ["imageFile", "imagePreviewUrl", "imageNaturalWidth", "imageNaturalHeight", "color_mode", "page", "eight_color_full_export", "corner_points", "nudge_step", "active_corner_index", "offset_x", "offset_y", "zoom", "distortion", "vignette_correction", "auto_wb", "colorchecker_enabled", "colorchecker_phase", "calibratedPreviewUrl", "calibratedFullWidth", "calibratedFullHeight", "calibratedPreviewWidth", "calibratedPreviewHeight", "originalPreviewUrl", "originalPreviewWidth", "originalPreviewHeight", "colorcheckerSummary", "lut_download_url", "warp_view_url", "lut_preview_url", "lut_layout", "page1Extracted", "page2Extracted", "extractedEightColorFullPages", "page1Extracted_5c", "page2Extracted_5c", "manufacturer", "type", "defaultPalette", "paletteConfirmed"],
      session: { kind: "extractor", field: "session_id", workspaceField: "workspaceSessionId", urls: { lut_path: "lut_download_url" } },
      colorchecker: ["calibratedFullFileId"],
    }),
    createWorkflowAdapter({
      kind: "single-stage", store: useSingleStageStore,
      busy: ["isRotatingWhite", "isRotatingBlack", "isExtracting", "isSaving"],
      fields: ["workflow", "datasetFile", "whiteImageFile", "whiteImagePreviewUrl", "whiteImageNaturalWidth", "whiteImageNaturalHeight", "whiteCornerPoints", "blackImageFile", "blackImagePreviewUrl", "blackImageNaturalWidth", "blackImageNaturalHeight", "blackCornerPoints", "activeCanvas", "activeCornerIndex", "nudgeStep", "warnings", "stageAParamsUrl", "whiteWarpPreviewUrl", "blackWarpPreviewUrl", "fitSummary", "materialSummary", "orientationRanking", "manualWhiteAnchor", "manualBlackAnchor", "imageSource", "colorchecker_enabled", "colorchecker_phase", "originalWhitePreviewUrl", "originalWhitePreviewWidth", "originalWhitePreviewHeight", "originalBlackPreviewUrl", "originalBlackPreviewWidth", "originalBlackPreviewHeight", "colorcheckerSummary", "materialName", "materialBrand", "materialFileUrl", "savedStageAParamsUrl"],
      session: { kind: "single-stage", field: "sessionId", urls: { stage_a_params_path: "stageAParamsUrl" } },
      colorchecker: ["whiteColorcheckerFileId", "blackColorcheckerFileId"],
    }),
    createWorkflowAdapter({
      kind: "five-color", store: useFiveColorStore, busy: ["isLoading", "isGeneratingSwatch"],
      fields: ["lutName", "baseColors", "combinations", "selectedIndices", "manualSelectedIndices", "selectionSource", "queryResult", "collectedRecipes", "swatchBlockSize", "swatchGap", "swatchCols", "swatchStructureMode", "swatchDownloadUrl", "swatchPreviewUrl"],
      lutNames: (state) => [state.lutName],
    }),
    createWorkflowAdapter({
      kind: "lut-manager", store: useLutManagerStore, busy: ["primaryLoading", "merging"],
      catalogFields: ["lutList"], ignoredChanges: ["filteredSecondaryOptions"],
      refreshCatalog: () => useLutManagerStore.getState().fetchLutList(),
      fields: ["lutList", "primaryName", "primaryInfo", "secondaryNames", "secondaryInfos", "filteredSecondaryOptions", "dedupThreshold", "mergeResult"],
      lutNames: (state) => [state.primaryName, ...state.secondaryNames],
    }),
    createWorkflowAdapter({
      kind: "lut-compare", store: useLutCompareStore, busy: ["lutAInfoLoading", "lutBInfoLoading", "comparing"],
      catalogFields: ["lutList"],
      refreshCatalog: () => useLutCompareStore.getState().fetchLutList(),
      fields: ["lutList", "lutAName", "lutBName", "lutAInfo", "lutBInfo", "compareResult"],
      lutNames: (state) => [state.lutAName, state.lutBName],
    }),
    createWorkflowAdapter({
      kind: "lut-details", store: useLutDetailsStore, busy: ["detailLoading"],
      catalogFields: ["catalog"], ignoredChanges: ["selectedManufacturer", "selectedLutName", "canLoadSelectedLut", "isSelectionDirty"],
      refreshCatalog: () => useLutDetailsStore.getState().fetchCatalog(),
      fields: ["catalog", "selectedManufacturer", "selectedLutName", "loadedLutName", "query", "detail", "hasLoadedDetail", "isSelectionDirty", "canLoadSelectedLut"],
      lutNames: (state) => [state.selectedLutName, state.loadedLutName],
    }),
    createWorkflowAdapter({
      kind: "vectorizer", store: useVectorizerStore, busy: ["isProcessing"],
      fields: ["imageFile", "imagePreviewUrl", "params", "result"],
    }),
  ];
}
