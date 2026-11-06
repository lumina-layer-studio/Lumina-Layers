import type { ConverterSourceRuntimeState, ConverterState } from "./types";
import type { NativeBrandGroup } from "../../api/types";

/** Backend-owned editor projection. Shared by history nodes referring to the same live session. */
export const EDITOR_RUNTIME_KEYS = [
  "sessionId", "nativeMaterialSelection", "previewImageUrl", "originalPreviewUrl", "previewBaseImageUrl", "previewGlbUrl",
  "palette", "colorContours", "materialDynamicRecipes", "materialLayerBenefitCurve", "materialLayerBenefitScope", "materialLayerBenefitPixelCount",
  "colorRemapMap", "remapHistory", "remapRedoHistory", "historyCanUndo", "historyCanRedo",
  "replacement_regions", "recipe_overrides", "customRecipeHistory", "free_color_set", "regionReplacementCount", "pendingEditorProject",
  "selectionDocument", "selectedColor", "selectedColors", "selectedRegions", "regionData", "gradientSelection", "selectedGradientRegions",
  "preview_width_mm", "preview_height_mm", "preview_spacer_thick", "previewPixelWidth", "previewPixelHeight", "modelBounds",
  "hasManualPreview", "previewAutoRefreshPending", "lutMatchMode", "lutMatchInfo", "previewWarnings",
  "layerImages", "layerImagesSourceKey", "gradientGroups", "gradientGroupsSessionId",
  "puzzleOverlayUrl", "puzzleWarnings", "puzzleResolvedRows", "puzzleResolvedCols", "puzzleResolvedPieceCount", "puzzleDerivedPieceWidthMm", "puzzleDerivedPieceHeightMm",
] as const satisfies readonly (keyof ConverterState)[];

export type EditorRuntime = Pick<ConverterState, typeof EDITOR_RUNTIME_KEYS[number]>;
export function captureEditorRuntime(state: ConverterState): EditorRuntime {
  return Object.fromEntries(EDITOR_RUNTIME_KEYS.map(key => [key, state[key]])) as unknown as EditorRuntime;
}

export function editorMutationPending(state: ConverterState): boolean {
  return state.historyBusy || state.replacePreviewLoading || state.pendingSelectionMutations.length > 0
    || state.contentCommitStatus === "pending" || state.contentCommitStatus === "unknown";
}

const sourceFields: Record<keyof ConverterSourceRuntimeState, true> = {
  imagePreviewUrl: true,
  modelSurfacePreviewUrl: true,
  projectSourceKey: true,
  projectResourceSessionIds: true,
  aspectRatio: true,
  conversionParameterContext: true,
  modelSurfaceModelFileId: true,
  modelSurfaceSummary: true,
  modelSurfaceSelectionId: true,
  modelSurfaceFootprint: true,
  modelSurfaceCandidates: true,
  selectedLutInfo: true,
  heightmapThumbnailUrl: true,
  heightmapUploadSessionId: true,
};
export type SourceRuntimeSnapshot = ConverterSourceRuntimeState & { portableBrand: NativeBrandGroup | null };
export function captureSourceRuntime(state: ConverterState): SourceRuntimeSnapshot {
  return {
    ...Object.fromEntries(Object.keys(sourceFields).map(key => [key, state[key as keyof ConverterSourceRuntimeState]])) as unknown as ConverterSourceRuntimeState,
    portableBrand: state.projectLutFile ? state.nativeBrandGroups.find(brand => brand.brand_key === state.selectedNativeBrandKey) ?? null : null,
  };
}
