import { create } from "zustand";
import { invalidatePreviewRequest } from "../previewRequestCoordinator";
import { boundProjectResources, captureProjectSettings, resolveConverterSettings, withCurrentConverterCatalogs } from "./project";
import { previewResultState } from "./previewResult";
import { installConverterDocumentHistory } from "./documentHistory";
import { createDocumentCommandWrapper } from "./documentCommands";
import { externalSpoolPaletteKey } from "./nativeMaterialSelection";
import { subscribeWithSelector } from "zustand/middleware";
import { trackLuminaEvent } from "../../analytics/umami";
import {
  apiErrorToVisibleMessage,
  downloadResourceBlob,
} from "../../api/client";
import {
  applyRecipeOverride as apiApplyRecipeOverride,
  autoDetectColors as apiAutoDetectColors,
  cleanupSessionFiles as apiCleanupSessionFiles,
  convertPreview as apiConvertPreview,
  convertPuzzleLayoutPreview as apiConvertPuzzleLayoutPreview,
  cropImage as apiCropImage,
  detectRegion as apiDetectRegion,
  fetchBedSizes as apiFetchBedSizes,
  fetchGradientGroups as apiFetchGradientGroups,
  fetchLutColors as apiFetchLutColors,
  fetchLutList as apiFetchLutList,
  getEditorCommitStatus as apiGetEditorCommitStatus,
  getEditorSelection as apiGetEditorSelection,
  exportEditorProject as apiExportEditorProject,
  restoreEditorProject as apiRestoreEditorProject,
  mutateEditorSelection as apiMutateEditorSelection,
  mutateFreeColors as apiMutateFreeColors,
  regionReplace as apiRegionReplace,
  regionReplaceBatch as apiRegionReplaceBatch,
  regionRequantize as apiRegionRequantize,
  replaceColor as apiReplaceColor,
  replaceColorsBatch as apiReplaceColorsBatch,
  replacementHistory as apiReplacementHistory,
  resetReplacements as apiResetReplacements,
  selectModelSurface as apiSelectModelSurface,
  uploadHeightmap as apiUploadHeightmap,
  uploadLut as apiUploadLut,
  uploadModelSurface as apiUploadModelSurface
} from "../../api/converter";
import {
  fetchLutCatalog as apiFetchLutCatalog,
  fetchLutDetailsCatalog as apiFetchLutDetailsCatalog,
  fetchLutInfo as apiFetchLutInfo,
  fetchSessionLutInfo as apiFetchSessionLutInfo,
} from "../../api/lut";
import { fetchMaterialColorSuggestions } from "../../api/materialCache";
import { uploadImagePreview } from "../../api/system";
import { closeSession } from "../../api/session";
import type {
  AutoHeightMode,
  ColorMode,
  DynamicMaterialResultResponse,
  FridgeMagnetItem,
  GradientSelectionSource,
  MaterialColorSuggestionsResponse,
  ModelingMode,
  ModelSurfaceSelectResponse,
  PaletteEntry,
  PuzzleConnectorStyle,
  PuzzleSizingMode,
  PuzzleStyle,
  RecipeHistoryItem,
  ReplacementHistoryResponse,
  SelectionDocumentResponse,
  StructureMode,
  VirtualMaterial
} from "../../api/types";
import {
  ColorMode as ColorModeEnum,
  ModelingMode as ModelingModeEnum,
  StructureMode as StructureModeEnum,
} from "../../api/types";
import {
  createFridgeMagnetFromPreset,
  getDefaultFridgeMagnetPresetKey,
  normalizeFridgeMagnetItem,
  resolveFridgeMagnetSpacerThick,
} from "../../constants/fridgeMagnets";
import {
  SVG_HOLE_COMPENSATION_DEFAULTS,
  svgHoleCompensationOptions,
  validSvgHoleCompensationOptions,
  type SvgHoleCompensationOptions,
} from "../../constants/svgHoleCompensation";
import { tRuntime } from "../../i18n/runtime";
import {
  postClientLog,
  summarizeErrorForLog,
  summarizeFileForLog,
} from "../../utils/clientLog";
import {
  colorRemapToReplacementRegions,
  computeAutoHeightMap
} from "../../utils/colorUtils";
import { rememberDerivedImageSource, resolveSourceFile } from "../../utils/sourceFileOrigins";
import {
  autoLayoutFridgeMagnets,
  buildSuggestedFridgeMagnetCenters,
  canonicalizeFridgeMagnets,
  getDefaultFridgeMagnetCount,
  layoutFridgeMagnetsByCenters,
} from "../../utils/fridgeMagnetLayout";
import {
  isSvgImageFile,
  resolveRotatedImageSize,
  rotateImageFile,
  type ImageRotationDegrees,
} from "../../utils/imageRotation";
import { createPreviewSpace,type PreviewSpaceBounds } from "../../utils/previewSpace";
import { normalizeResourceUrl } from "../../utils/resourceUrl";
import { computeScaleFactor } from "../../utils/scaleUtils";
import {
  invalidateGeneratedArtifacts,
  registerPreviewArtifactInvalidator
} from "../generatedArtifactInvalidation";
import { lutErrorToVisibleMessage } from "../lutErrorMessages";
import { registerPrinterBedLabelSynchronizer } from "../printerBedLabelSync";
import { useSettingsStore, withExternalSpoolSelection } from "../settingsStore";
import { fitTargetDimensions, getTargetDimensionLimits } from "./dimensions";
import { createConversionPresetActions } from "./conversionPresetActions";
import {
  newestEditorContentRevision
} from "./editorRevision";
import {
  buildCurrentVisibleColorRemapMap,buildSourceChangeProjectColorState,chooseLastSelectedColor,clonePortableProjectColorState,cloneRecipeOverrides,cloneRemapHistory,cloneReplacementRegions,colorRemapFromReplacementRegions,editorCommitResultStateFromResponse,EMPTY_LUT_MATCH_STATE,getPreviewBaseUrl,hasAdjustmentState,historyFlagsFromResponse,INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,normalizeHexNoHash,normalizeReplacementRegionsFromHistory,selectionModeForTool,selectionStateFromDocument,selectionToolForLegacyMode,toggleHexInSet,
} from "./editorState";
import {
  CONVERTER_ERROR_KEYS,createGenerationActions,getElapsedMsSince,getErrorType,invalidateGenerationRequests,notifyCompletion,
} from "./generationActions";
import {
  buildLutCatalogIndex,
  findLutLocationByPath,
} from "./legacyLutSelection";
import {
  buildPuzzlePreviewParams,buildPuzzlePreviewSourceKey,cancelDerivedPreviewWork,createDerivedPreviewActions,DEFAULT_LAYER_IMAGES_STATE,DEFAULT_PUZZLE_PREVIEW_STATE,
} from "./previewArtifacts";
import {
  canCommitPreviewResponse,
  capturePreviewCommitGuard,
  type PreviewCommitGuard,
  type PreviewCommitOwner,
} from "./previewCommitGuard";
import { buildMissingAutoReliefHeightMap,buildPreviewParams } from "./requests";
import {
  buildConversionSourceParams,buildNativeModelDefaults,buildNativeModelState,clampValue,filterNativeBrandGroups,getMaterialArchiveReliefMinimumExtraHeight,getNativeBrandGroupByKey,getNativeDbNamesForGroup,getNativeDbOptionNames,getSelectedNativeBrandGroup,getSupportedModeByPair,inferDefaultMaterialBackingDirName,isDynamicMaterialActive,MATERIAL_DYNAMIC_LAYER_COUNT_MAX,MATERIAL_DYNAMIC_LAYER_COUNT_MIN,normalizeDynamicMaterialLayerCount,normalizeLegacyLutNames,normalizeLutColorMode,normalizeLutDrivenReliefState,normalizeLutGroups,normalizeNativeBrandGroups,normalizePublicColorMode,normalizeStringArray,RELIEF_MAX_EXTRA_HEIGHT_MM,resolveConverterSourceSelection,resolveMaterialPrintLayerCount,resolveNativeBrandSelection,resolveNativeSupportedModeForBrand,resolvePreferredSupportedMode,
} from "./sources";
import type {
  ConverterActions,ConverterState,ModelSurfaceModelRotation,ModelSurfacePlacement,PendingReplacement,RegionData,SelectionMode,SelectionTool,SourceVersion,
} from "./types";
export { CONVERTER_ERROR_KEYS } from "./generationActions";
export { buildLayerImagesSourceKey } from "./previewArtifacts";
export {
  clampValue,getMaterialArchiveReliefMinimumExtraHeight,getMaterialArchiveReliefMinimumTotalHeight,inferDefaultMaterialBackingDirName,isDynamicMaterialActive,MATERIAL_DYNAMIC_LAYER_COUNT_MAX,MATERIAL_DYNAMIC_LAYER_COUNT_MIN,resolveConverterSourceSelection,
} from "./sources";
export type {
  ContentCommitStatus,ConverterActions,ConverterState,ModelSurfaceModelRotation,ModelSurfacePlacement,ModelSurfacePlacementMode,PendingReplacement,RegionData,SelectionDocument,SelectionMode,SelectionTool,SourceVersion,WorkshopConverterImageInput,
} from "./types";

type LuminaWindow = Window & {
  __luminaGenerateStart?: number;
  __luminaPreviewStart?: number;
};

const BACKING_INFILL_DENSITY_STORAGE_KEY =
  "lumina_backingInfillDensityPercent";
const BACKING_INFILL_DENSITY_MIN_PERCENT = 5;
const BACKING_INFILL_DENSITY_MAX_PERCENT = 100;
const BACKING_INFILL_DENSITY_DEFAULT_PERCENT = 100;

// ===========================================================================
// Material-archive achievable-color suggestion helpers (module-local state)
// 材料档案可达色建议的模块级辅助状态（LRU + AbortController）
// ===========================================================================

/**
 * Upper bound on the number of cached suggestion responses kept in memory.
 * Suggestions are small (~4 KB each), and users rarely explore more than a
 * handful of targets per session, so a modest cap avoids unbounded growth
 * while still delivering instant re-picks when the same target is clicked.
 * 缓存上限：每条约 4 KB，此上限既能覆盖典型交互又避免无界增长。
 */
const MATERIAL_SUGGEST_LRU_LIMIT = 64;

/**
 * Insertion-order :class:`Map` used as an LRU cache. Re-inserting on hit
 * refreshes recency; eviction removes the oldest key when capacity is hit.
 * 以插入顺序维护的 LRU：命中时重新插入以刷新，超额时淘汰最早项。
 */
const _materialSuggestCache = new Map<
  string,
  MaterialColorSuggestionsResponse
>();

/**
 * Holds the currently in-flight suggestion request so a newer call can
 * cancel the older one and avoid races on ``materialSuggestions`` state.
 * 持有当前未完成请求，便于后续请求取消前者、避免状态竞态。
 */
let _materialSuggestAbortController: AbortController | null = null;
let _materialSuggestRequestToken = 0;

function _cancelMaterialSuggestionWork() {
  _materialSuggestRequestToken += 1;
  _materialSuggestAbortController?.abort();
  _materialSuggestAbortController = null;
  return {
    materialSuggestions: null,
    materialSuggestionsLoading: false,
    materialSuggestionsTargetHex: null,
    materialSuggestionsError: null,
  };
}

/**
 * In-flight gradient-groups request controller.
 * 当前未完成的渐变分组请求控制器。
 */
let _gradientGroupsAbortController: AbortController | null = null;

// Latest-request tokens keep slower catalog/palette responses from
// overwriting a newer converter selection.
// 最新请求令牌用于阻止较慢的目录或调色板响应覆盖较新的转换选择。
let _lutCatalogRequestToken = 0;
let _lutColorsRequestToken = 0;

/**
 * Build a deterministic cache key from a suggestion request's parameters.
 * ``directoryNames`` is joined (order-sensitive: we want the user palette
 * ordering preserved, matching the backend recipe rebinding). Substrate is
 * included for forward compatibility once the UI exposes black substrates.
 * 从请求参数生成确定性缓存键；保留耗材顺序以匹配后端配方重绑定语义。
 */
function _materialSuggestCacheKey(params: {
  directoryNames: string[];
  layerCount: number;
  layerHeightMm: number;
  substrate: string;
  gridResolution?: number;
  targetHex: string;
}): string {
  const dirs = params.directoryNames.join(",");
  const hex = params.targetHex.replace(/^#/, "").toLowerCase();
  const gridResolution = params.gridResolution ?? "default";
  return `${dirs}|${params.layerCount}|${params.layerHeightMm}|${params.substrate}|${gridResolution}|${hex}`;
}

export const RAW_EXTENSIONS_CONVERTER = new Set([
  ".dng",
  ".cr2",
  ".cr3",
  ".nef",
  ".arw",
  ".orf",
  ".rw2",
  ".raf",
  ".pef",
  ".srw",
  ".raw",
]);

function isRawFileConverter(file: File): boolean {
  const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
  return RAW_EXTENSIONS_CONVERTER.has(ext);
}

/** Resolve the user-selected source behind a cropped or rotated converter file.
 *
 * 获取裁剪或旋转后的 Converter 文件所对应的用户原始输入文件。
 */
export function resolveBugReportOriginalImageFile(
  currentFile: File | null,
): File | null {
  return resolveSourceFile(currentFile);
}

function visibleConverterError(error: unknown, fallback: string): string {
  return apiErrorToVisibleMessage(error, fallback);
}

function selectionUpdatesFromResponse(
  current: ConverterState,
  sessionId: string,
  document: SelectionDocumentResponse | null | undefined,
): Partial<ConverterState> {
  if (!document || current.sessionId !== sessionId) return {};
  if (!rememberConfirmedSelectionDocument(sessionId, document)) return {};
  const currentDocument = current.selectionDocument;
  if (
    currentDocument &&
    (currentDocument.selection_revision > document.selection_revision ||
      (currentDocument.selection_revision === document.selection_revision &&
        currentDocument.content_revision > document.content_revision))
  ) {
    return {};
  }
  return {
    ...selectionStateFromDocument(document, getPreviewBaseUrl(current) ?? ""),
    confirmedEditorCommit: {
      sessionId, selectionRevision: document.selection_revision,
      contentRevision: document.editor_content_revision ?? document.content_revision,
    },
  };
}

function clearedHeightmapUploadState() {
  return {
    heightmapThumbnailUrl: null,
    color_height_map: {},
    heightmapUploadSessionId: null,
  };
}

function rawPreviewFailureMessage(error: unknown): string {
  const detail = visibleConverterError(error, tRuntime("api_error_http_default"));
  return tRuntime("converter_raw_preview_failed", { error: detail });
}

function isSvgFile(file: File): boolean {
  return (
    file.type === "image/svg+xml" ||
    file.name.toLowerCase().endsWith(".svg")
  );
}

/** Default CIEDE2000 tolerance for the colour-range selection tool. */
export const DEFAULT_COLOR_RANGE_TOLERANCE = 6;
/** Upper bound for the colour-range tolerance slider (ΔE00). */
export const MAX_COLOR_RANGE_TOLERANCE = 30;

export const DEFAULT_MODEL_SURFACE_PLACEMENT: ModelSurfacePlacement = {
  mode: "edge_to_edge",
  offset_x_mm: 0,
  offset_y_mm: 0,
  scale: 1,
  rotation_deg: 0,
  inset_mm: 0,
};

export const DEFAULT_MODEL_SURFACE_MODEL_ROTATION: ModelSurfaceModelRotation = {
  x_deg: 0,
  y_deg: 0,
  z_deg: 0,
};

function editorCommitStateFromResponse(
  response: { editor_content_revision?: number | null } | null | undefined,
): Partial<ConverterState> {
  const revision = response?.editor_content_revision;
  if (typeof revision !== "number" || !Number.isFinite(revision)) return {};

  const current = useConverterStore.getState();
  if (current.sessionId) {
    rememberConfirmedEditorContentRevision(current.sessionId, revision);
  }
  const document = current.selectionDocument;
  const selectionDocument = document &&
    (document.editor_content_revision ?? -1) < revision
    ? { ...document, editor_content_revision: revision }
    : undefined;
  return {
    contentCommitStatus: "committed",
    contentCommitOperationId: null,
    confirmedEditorCommit: current.sessionId ? {
      sessionId: current.sessionId,
      selectionRevision: current.selectionDocument?.selection_revision ?? 0,
      contentRevision: revision,
    } : null,
    ...(selectionDocument ? { selectionDocument } : {}),
  };
}

function dynamicMaterialResultState(
  response: DynamicMaterialResultResponse,
): Pick<
  ConverterState,
  | "materialDynamicRecipes"
  | "materialLayerBenefitCurve"
  | "materialLayerBenefitScope"
  | "materialLayerBenefitPixelCount"
> &
  Partial<
    Pick<
      ConverterState,
      "contentCommitStatus" | "contentCommitOperationId" | "selectionDocument" | "confirmedEditorCommit"
    >
  > {
  return {
    materialDynamicRecipes: response.material_dynamic_recipes ?? [],
    materialLayerBenefitCurve: response.material_layer_benefit_curve ?? [],
    materialLayerBenefitScope:
      response.material_layer_benefit_scope ?? "all_printable_pixels",
    materialLayerBenefitPixelCount:
      response.material_layer_benefit_pixel_count ?? 0,
    ...editorCommitStateFromResponse(response),
  };
}

function buildHistoryRestoreState(
  response: ReplacementHistoryResponse,
): Partial<ConverterState> {
  const previewUrl = normalizeResourceUrl(response.preview_url);
  const activePreviewUrl = previewUrl || useConverterStore.getState().previewBaseImageUrl;
  const replacementRegions = normalizeReplacementRegionsFromHistory(
    response.replacement_regions ?? [],
  );
  return {
    previewImageUrl: activePreviewUrl,
    previewBaseImageUrl: activePreviewUrl,
    replacement_regions: replacementRegions,
    recipe_overrides: cloneRecipeOverrides(response.recipe_overrides ?? []),
    regionReplacementCount: response.region_replacement_count ?? replacementRegions.length,
    ...(response.color_layers !== undefined ? { color_layers: response.color_layers } : {}),
    ...(response.layer_height_mm !== undefined ? { layer_height_mm: response.layer_height_mm } : {}),
    colorRemapMap: colorRemapFromReplacementRegions(response.replacement_regions ?? []),
    historyCanUndo: response.can_undo,
    historyCanRedo: response.can_redo,
    // color_height_map 由用户在浮雕面板本地编辑（updateColorHeight），从未随预览
    // 会话上传/持久化到服务端；历史响应不再携带该字段，撤销/重做时必须保留当前
    // 本地值，避免把用户已配置的逐色高度清空。
    // color_height_map is edited locally in the relief panel and never persisted
    // to the preview session; history responses no longer carry it, so undo/redo
    // must preserve the current local map.
    free_color_set: new Set(response.free_color_set ?? []),
    selectedGradientRegions: [],
    gradientSelection: null,
    pendingReplacement: null,
    threemfDiskPath: null,
    downloadUrl: null,
    ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
    ...(response.gradient_groups !== undefined
      ? { gradientGroups: response.gradient_groups ?? null }
      : {}),
  };
}

type FridgeMagnetBoundsState = Pick<
  ConverterState,
  | "modelBounds"
  | "target_width_mm"
  | "target_height_mm"
  | "preview_width_mm"
  | "preview_height_mm"
>;

function getFallbackModelBounds(
  state: FridgeMagnetBoundsState,
): PreviewSpaceBounds {
  if (state.modelBounds) {
    const { scaleX, scaleY } = computeScaleFactor(
      state.target_width_mm,
      state.target_height_mm,
      state.preview_width_mm,
      state.preview_height_mm,
    );
    const displayBounds = createPreviewSpace(
      state.modelBounds,
      scaleX,
      scaleY,
    ).displayBounds;
    const width = displayBounds.maxX - displayBounds.minX;
    const height = displayBounds.maxY - displayBounds.minY;
    return {
      minX: -width / 2,
      maxX: width / 2,
      minY: -height / 2,
      maxY: height / 2,
      maxZ: displayBounds.maxZ,
    };
  }

  return {
    minX: -state.target_width_mm / 2,
    maxX: state.target_width_mm / 2,
    minY: -state.target_height_mm / 2,
    maxY: state.target_height_mm / 2,
    maxZ: 0,
  };
}

function sanitizeFiniteNumber(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function sanitizeOptionalFiniteNumber(
  value: number | null | undefined,
  fallback: number | null,
): number | null {
  if (value === undefined) {
    return fallback;
  }
  if (value === null) {
    return null;
  }

  return Number.isFinite(value) ? value : fallback;
}

function createNextFridgeMagnetId(fridgeMagnets: FridgeMagnetItem[]): string {
  const maxId = fridgeMagnets.reduce((max, item) => {
    const match = item.id.match(/^fridge-magnet-(\d+)$/);
    if (!match) {
      return max;
    }
    return Math.max(max, Number(match[1]));
  }, 0);

  return `fridge-magnet-${maxId + 1}`;
}

function buildDefaultFridgeMagnetLayout(
  state: FridgeMagnetBoundsState,
): FridgeMagnetItem[] {
  const bounds = getFallbackModelBounds(state);
  const magnets = buildSuggestedFridgeMagnetCenters(
    bounds,
    getDefaultFridgeMagnetCount(bounds),
  ).map(({ x, y }, index) =>
    createFridgeMagnetFromPreset(
      `fridge-magnet-${index + 1}`,
      getDefaultFridgeMagnetPresetKey("round"),
      x,
      y,
    ),
  );

  return layoutFridgeMagnetsByCenters(
    bounds,
    magnets,
    magnets.map((magnet) => ({
      x: magnet.center_x_mm,
      y: magnet.center_y_mm,
    })),
  );
}

function buildFridgeMagnetState(
  state: Pick<
    ConverterState,
    | "modelBounds"
    | "target_width_mm"
    | "target_height_mm"
    | "preview_width_mm"
    | "preview_height_mm"
    | "base_spacer_thick"
    | "enable_fridge_magnet"
    | "fridge_magnets"
  >,
  overrides?: Partial<
    Pick<
      ConverterState,
      "enable_fridge_magnet" | "fridge_magnets" | "base_spacer_thick"
    >
  >,
): Pick<
  ConverterState,
  | "enable_fridge_magnet"
  | "fridge_magnets"
  | "base_spacer_thick"
  | "spacer_thick"
> {
  const baseSpacerThick =
    overrides?.base_spacer_thick ?? state.base_spacer_thick;
  const enableFridgeMagnet =
    overrides?.enable_fridge_magnet ?? state.enable_fridge_magnet;
  const fridgeMagnets = canonicalizeFridgeMagnets(
    getFallbackModelBounds(state),
    overrides?.fridge_magnets ?? state.fridge_magnets,
  );

  return {
    enable_fridge_magnet: enableFridgeMagnet,
    fridge_magnets: fridgeMagnets,
    base_spacer_thick: baseSpacerThick,
    spacer_thick: resolveFridgeMagnetSpacerThick(
      baseSpacerThick,
      enableFridgeMagnet,
      fridgeMagnets,
    ),
  };
}

function getLastSelectedRegion(regions: RegionData[]): RegionData | null {
  return regions.length > 0 ? regions[regions.length - 1] : null;
}

function getSelectedRegionPreviewUrl(
  regions: RegionData[],
  fallbackPreviewUrl: string | null,
): string | null {
  const lastRegion = getLastSelectedRegion(regions);
  return lastRegion?.previewUrl || fallbackPreviewUrl;
}

function resolveRegionContours(
  contours: number[][][] | null | undefined,
): number[][][] | null {
  if (contours && contours.length > 0) {
    return contours;
  }
  return null;
}

function resolveRegionBbox(
  bbox: [number, number, number, number] | number[] | null | undefined,
): [number, number, number, number] | null {
  if (!bbox || bbox.length !== 4) {
    return null;
  }
  const normalized = bbox.map((value) => Number(value));
  if (normalized.some((value) => !Number.isFinite(value))) {
    return null;
  }
  return normalized as [number, number, number, number];
}

let replacementPreviewEpoch = 0;

let editorOperationSequence = 0;

/** Create a client operation id used only to reconcile a lost response. */
export function createEditorOperationId(): string {
  editorOperationSequence += 1;
  return `editor-${Date.now().toString(36)}-${editorOperationSequence.toString(36)}`;
}

type ContentCommitHandle = {
  sessionId: string;
  replacementEpoch: number;
  operationId: string;
  resolve: (success: boolean) => void;
  settled: boolean;
  rollbackState?: Partial<ConverterState>;
};

type ContentCommitReservation = {
  sessionId: string;
  ready: Promise<boolean>;
  resolve: (success: boolean) => void;
  readyImmediately: boolean;
  settled: boolean;
};

const contentCommitQueues = new Map<string, Promise<boolean>>();
const contentCommitHandles = new Map<number, ContentCommitHandle>();
const contentCommitReservations = new Map<
  string,
  Set<ContentCommitReservation>
>();

function reserveContentCommit(sessionId: string): ContentCommitReservation {
  let resolve!: (success: boolean) => void;
  const completion = new Promise<boolean>((resolvePromise) => {
    resolve = resolvePromise;
  });
  const hasPrevious = contentCommitQueues.has(sessionId);
  const previous = contentCommitQueues.get(sessionId) ?? Promise.resolve(true);
  const queued = previous.then(() => completion);
  contentCommitQueues.set(sessionId, queued);
  const reservation: ContentCommitReservation = {
    sessionId,
    ready: previous,
    resolve,
    readyImmediately: !hasPrevious,
    settled: false,
  };
  const reservations = contentCommitReservations.get(sessionId) ?? new Set();
  reservations.add(reservation);
  contentCommitReservations.set(sessionId, reservations);
  void queued.then(() => {
    if (contentCommitQueues.get(sessionId) === queued) {
      contentCommitQueues.delete(sessionId);
    }
  });
  return reservation;
}

function releaseContentCommit(
  reservation: ContentCommitReservation,
  _success: boolean,
): void {
  if (reservation.settled) return;
  reservation.settled = true;
  const reservations = contentCommitReservations.get(reservation.sessionId);
  reservations?.delete(reservation);
  if (reservations && reservations.size === 0) {
    contentCommitReservations.delete(reservation.sessionId);
  }
  // The queue boolean means "safe for the next operation to start", not
  // "the previous operation succeeded". A known pre-commit failure leaves
  // the prior committed artwork intact and must not permanently block later
  // edits. Only an unresolved receipt keeps the reservation pending.
  // 队列布尔值表示“后续操作是否安全开始”，不是“上一操作是否成功”。已知的
  // 提交前失败仍保留上一份作品，不能把后续编辑永久阻塞；只有未知回执保持挂起。
  reservation.resolve(true);
}

function acquireContentCommitTurn(sessionId: string): ContentCommitReservation {
  // Reserve synchronously before the first await. This is what makes two
  // same-class actions started in the same event turn serialize instead of
  // both capturing a replacement epoch.
  // 在第一次 await 前同步占位，保证同一事件循环内发起的同类编辑也会串行，
  // 不会同时捕获两个 replacement epoch。
  return reserveContentCommit(sessionId);
}

function beginContentCommit(
  sessionId: string,
  replacementEpoch: number,
  operationId: string,
  reservation: ContentCommitReservation = reserveContentCommit(sessionId),
): void {
  contentCommitHandles.set(replacementEpoch, {
    sessionId,
    replacementEpoch,
    operationId,
    resolve: (success) => releaseContentCommit(reservation, success),
    settled: false,
  });
}

function finishContentCommit(replacementEpoch: number, success: boolean): void {
  const handle = contentCommitHandles.get(replacementEpoch);
  if (!handle || handle.settled) return;
  handle.settled = true;
  contentCommitHandles.delete(replacementEpoch);
  if (success && useConverterStore.getState().sessionId === handle.sessionId) {
    // A committed edit invalidates the current launch shortcut. Its existing
    // TTL download remains on the server for anyone who already saved the URL.
    useConverterStore.setState({ threemfDiskPath: null, downloadUrl: null });
  }
  handle.resolve(success);
}

function attachContentCommitRollback(
  guard: PreviewCommitGuard,
  rollbackState: Partial<ConverterState>,
): void {
  const handle = contentCommitHandles.get(guard.replacementEpoch);
  if (!handle || handle.operationId !== guard.operationId) return;
  handle.rollbackState = rollbackState;
}

function waitForContentCommits(sessionId: string): Promise<boolean> | null {
  const hasActiveCommit = Array.from(contentCommitHandles.values()).some(
    (handle) => handle.sessionId === sessionId && !handle.settled,
  );
  const hasReservation = (contentCommitReservations.get(sessionId)?.size ?? 0) > 0;
  return hasActiveCommit || hasReservation
    ? contentCommitQueues.get(sessionId) ?? null
    : null;
}

function captureReplacementPreviewCommit(
  owner: PreviewCommitOwner,
  reservation?: ContentCommitReservation,
): PreviewCommitGuard {
  replacementPreviewEpoch += 1;
  const operationId = createEditorOperationId();
  if (owner.sessionId) {
    beginContentCommit(
      owner.sessionId,
      replacementPreviewEpoch,
      operationId,
      reservation,
    );
  }
  return capturePreviewCommitGuard(owner, replacementPreviewEpoch, operationId);
}

function observeLateContentCommit(guard: PreviewCommitGuard): void {
  if (!guard.sessionId) return;
  if (typeof apiGetEditorCommitStatus !== "function") {
    // Keep compatibility with isolated legacy test doubles that predate the
    // receipt endpoint. The real API client always provides this function;
    // a real query failure still follows the unknown/pause path below.
    finishContentCommit(guard.replacementEpoch, false);
    return;
  }
  // A stale response must not repaint the current session, but dropping it
  // silently is unsafe: the backend may have committed the operation before
  // the session changed or a newer epoch won the UI race. Query the bounded
  // receipt and retain only the per-session confirmed revision for the next
  // hydration; no current-session draft is mutated here.
  // Start from a resolved promise so a test/legacy client that does not expose
  // the optional receipt endpoint is handled as an asynchronous query failure
  // instead of throwing synchronously from the stale-response guard.
  void Promise.resolve()
    .then(() => apiGetEditorCommitStatus(guard.sessionId!, guard.operationId))
    .then((receipt) => {
      const current = useConverterStore.getState();
      const sameSession = current.sessionId === guard.sessionId;
      const hasHandle = contentCommitHandles.has(guard.replacementEpoch);
      if (receipt.status === "committed") {
        const revision =
          receipt.visible_content_revision ?? receipt.editor_content_revision;
        if (typeof revision === "number" && Number.isFinite(revision)) {
          rememberConfirmedContentRevision(guard.sessionId as string, revision);
        }
        rememberConfirmedEditorContentRevision(
          guard.sessionId as string,
          receipt.editor_content_revision,
        );
        // A same-session stale response still owns a live barrier. Release it
        // only after the receipt proves that the backend committed the edit.
        // 同 session 的旧响应仍持有屏障，只有回执确认已提交后才能释放。
        if (sameSession && hasHandle) {
          finishContentCommit(guard.replacementEpoch, true);
        } else {
          finishContentCommit(guard.replacementEpoch, false);
        }
        return;
      }
      if (receipt.status === "failed") {
        finishContentCommit(guard.replacementEpoch, false);
        return;
      }
      if (sameSession && hasHandle) {
        // pending/unknown is deliberately left unresolved. The explicit
        // reconciliation action can query it again; dependent edits and
        // generation must not guess a content version in the meantime.
        // pending/unknown 故意保持未解决，等待显式同步；依赖操作不能猜版本。
        useConverterStore.setState({
          contentCommitStatus: "unknown",
          contentCommitOperationId: guard.operationId,
          error: "旧编辑响应的提交结果暂时未知，已暂停后续编辑/生成。",
        });
        return;
      }
      finishContentCommit(guard.replacementEpoch, false);
    })
    .catch(() => {
      const current = useConverterStore.getState();
      if (
        current.sessionId === guard.sessionId &&
        contentCommitHandles.has(guard.replacementEpoch)
      ) {
        useConverterStore.setState({
          contentCommitStatus: "unknown",
          contentCommitOperationId: guard.operationId,
          error: "旧编辑响应的提交结果暂时未知，已暂停后续编辑/生成。",
        });
        return;
      }
      // The session may already be gone. The stale response remains isolated
      // and is never treated as proof of failure.
      finishContentCommit(guard.replacementEpoch, false);
    });
}

function isCurrentReplacementPreviewCommit(
  current: PreviewCommitOwner,
  guard: PreviewCommitGuard,
  success = true,
): boolean {
  const isCurrent = canCommitPreviewResponse(
    current,
    guard,
    replacementPreviewEpoch,
  );
  if (!isCurrent) {
    observeLateContentCommit(guard);
    // Keep a live same-session barrier until the receipt query settles. A
    // session switch has no dependent work left in this UI, so its old
    // operation can be isolated immediately.
    if (
      current.sessionId === guard.sessionId &&
      contentCommitHandles.has(guard.replacementEpoch)
    ) {
      return false;
    }
  }
  finishContentCommit(guard.replacementEpoch, success);
  return isCurrent;
}

type ReplacementErrorSettlement = {
  active: boolean;
  committed: boolean;
  unknown?: boolean;
};

function rememberConfirmedContentRevision(
  sessionId: string,
  contentRevision: number,
): void {
  const known = confirmedSelectionRevisions.get(sessionId);
  const current = useConverterStore.getState();
  const currentSelectionRevision =
    current.sessionId === sessionId
      ? current.selectionDocument?.selection_revision ?? 0
      : 0;
  if (!known || contentRevision >= known.contentRevision) {
    confirmedSelectionRevisions.set(sessionId, {
      selectionRevision: known?.selectionRevision ?? currentSelectionRevision,
      contentRevision,
      editorContentRevision: known?.editorContentRevision,
    });
  }
}

function rememberConfirmedEditorContentRevision(
  sessionId: string,
  editorContentRevision: number,
): void {
  if (!Number.isFinite(editorContentRevision)) return;
  const known = confirmedSelectionRevisions.get(sessionId);
  const current = useConverterStore.getState();
  const currentSelectionRevision =
    current.sessionId === sessionId
      ? current.selectionDocument?.selection_revision ?? 0
      : 0;
  const currentContentRevision =
    current.sessionId === sessionId
      ? current.selectionDocument?.content_revision ?? 0
      : 0;
  if (
    known?.editorContentRevision !== undefined &&
    editorContentRevision < known.editorContentRevision
  ) {
    return;
  }
  confirmedSelectionRevisions.set(sessionId, {
    selectionRevision: known?.selectionRevision ?? currentSelectionRevision,
    contentRevision: known?.contentRevision ?? currentContentRevision,
    editorContentRevision,
  });
  if (
    current.sessionId === sessionId &&
    current.selectionDocument &&
    (current.selectionDocument.editor_content_revision ?? -1) <
      editorContentRevision
  ) {
    useConverterStore.setState({
      selectionDocument: {
        ...current.selectionDocument,
        editor_content_revision: editorContentRevision,
      },
    });
  }
}

async function reconcileContentCommitStatus(
  current: PreviewCommitOwner,
  guard: PreviewCommitGuard,
  getState: () => ConverterState,
  setState: (partial: Partial<ConverterState>) => void,
  message: string,
  options: { allowStaleReceipt?: boolean } = {},
): Promise<ReplacementErrorSettlement> {
  const allowStaleReceipt = options.allowStaleReceipt === true;
  if (
    !allowStaleReceipt &&
    !canCommitPreviewResponse(current, guard, replacementPreviewEpoch)
  ) {
    observeLateContentCommit(guard);
    if (
      current.sessionId !== guard.sessionId ||
      !contentCommitHandles.has(guard.replacementEpoch)
    ) {
      finishContentCommit(guard.replacementEpoch, false);
    }
    return { active: false, committed: false };
  }
  const sessionId = guard.sessionId;
  if (!sessionId) {
    finishContentCommit(guard.replacementEpoch, false);
    return { active: false, committed: false };
  }

  const ownsCurrentPage = (): boolean => {
    const latest = getState();
    const handle = contentCommitHandles.get(guard.replacementEpoch);
    return (
      latest.sessionId === sessionId &&
      handle?.sessionId === sessionId &&
      handle.operationId === guard.operationId &&
      !handle.settled &&
      (allowStaleReceipt ||
        canCommitPreviewResponse(latest, guard, replacementPreviewEpoch))
    );
  };

  if (allowStaleReceipt && !ownsCurrentPage()) {
    finishContentCommit(guard.replacementEpoch, false);
    return { active: false, committed: false };
  }

  try {
    const receipt = await apiGetEditorCommitStatus(
      sessionId,
      guard.operationId,
    );
    if (!ownsCurrentPage()) {
      finishContentCommit(guard.replacementEpoch, false);
      return { active: false, committed: false };
    }

    if (receipt.status === "committed") {
      const visibleRevision =
        receipt.visible_content_revision ?? receipt.editor_content_revision;
      if (typeof visibleRevision !== "number" || !Number.isFinite(visibleRevision)) {
        setState({
          contentCommitStatus: "unknown",
          contentCommitOperationId: guard.operationId,
          error: `${message}：服务端未返回可用内容版本，已暂停后续编辑。`,
        });
        return { active: true, committed: false, unknown: true };
      }
      const operation = receipt.operation;
      const requiresBusinessResult =
        operation === "reset_replacements" ||
        operation === "apply_recipe_override" ||
        operation === "replacement_history_undo" ||
        operation === "replacement_history_redo" ||
        operation === "replace_color" ||
        operation === "replace_colors_batch" ||
        operation === "region_replace" ||
        operation === "region_replace_batch" ||
        operation === "region_requantize" ||
        operation === "free_colors";
      if (requiresBusinessResult && !receipt.result) {
        setState({
          contentCommitStatus: "unknown",
          contentCommitOperationId: guard.operationId,
          replacePreviewLoading: false,
          historyBusy: false,
          error: `${message}；服务端已确认版本，但未返回可对账的编辑结果，已暂停后续编辑/生成。`,
        });
        return { active: true, committed: false, unknown: true };
      }
      rememberConfirmedContentRevision(sessionId, visibleRevision);
      rememberConfirmedEditorContentRevision(
        sessionId,
        receipt.editor_content_revision,
      );
      const businessState = editorCommitResultStateFromResponse(
        getState(),
        sessionId,
        operation,
        receipt.result,
      );
      if (Object.keys(businessState).length > 0) {
        setState(businessState);
      }
      try {
        const document = await apiGetEditorSelection(sessionId);
        const currentAfterRead = getState();
        if (
          currentAfterRead.sessionId === sessionId &&
          (allowStaleReceipt ||
            canCommitPreviewResponse(
              currentAfterRead,
              guard,
              replacementPreviewEpoch,
            )) &&
          !isSelectionDocumentOlder(
            document,
            currentAfterRead.selectionDocument
              ? {
                  selectionRevision:
                    currentAfterRead.selectionDocument.selection_revision,
                  contentRevision:
                    currentAfterRead.selectionDocument.content_revision,
                }
              : confirmedSelectionRevisions.get(sessionId) ?? null,
          ) &&
          rememberConfirmedSelectionDocument(sessionId, document)
        ) {
          setState(selectionUpdatesFromResponse(currentAfterRead, sessionId, document));
        }
      } catch {
        // The operation receipt is authoritative even if selection hydration
        // is temporarily unavailable. The next selection request will use the
        // confirmed visible revision recorded above.
      }
      if (!ownsCurrentPage()) {
        finishContentCommit(guard.replacementEpoch, false);
        return { active: false, committed: false };
      }
      setState({
        ...editorCommitStateFromResponse(receipt),
        replacePreviewLoading: false,
        historyBusy: false,
        error: `${message}；服务端已确认本次编辑已提交（编辑版本 ${receipt.editor_content_revision}），已保留当前草稿。`,
      });
      finishContentCommit(guard.replacementEpoch, true);
      return { active: true, committed: true };
    }

    if (receipt.status === "failed") {
      const handle = contentCommitHandles.get(guard.replacementEpoch);
      if (handle?.rollbackState) {
        setState(handle.rollbackState);
      }
      setState({
        contentCommitStatus: "failed",
        contentCommitOperationId: null,
        replacePreviewLoading: false,
        historyBusy: false,
      });
      finishContentCommit(guard.replacementEpoch, false);
      return { active: true, committed: false };
    }
  } catch {
    // Query failure is not evidence of rollback. Keep the content barrier
    // unresolved so dependent selection/edit/generate operations cannot use a
    // guessed version or replay the mutation blindly.
  }

  if (!ownsCurrentPage()) {
    finishContentCommit(guard.replacementEpoch, false);
    return { active: false, committed: false };
  }

  setState({
    contentCommitStatus: "unknown",
    contentCommitOperationId: guard.operationId,
    replacePreviewLoading: false,
    historyBusy: false,
    error: `${message}；提交结果暂时未知，已保留草稿并暂停后续编辑/生成，请先重新同步。`,
  });
  return { active: true, committed: false, unknown: true };
}

/**
 * Resolve an ambiguous content-edit failure against the server's revision.
 *
 * A lost response is not proof that the backend rolled back. Querying the
 * operation receipt distinguishes committed, confirmed-not-committed, and
 * unknown; only the first two may resolve the content barrier.
 *
 * 对内容编辑的非确定性失败按服务端版本收敛：响应丢失并不等于后端回滚。
 * 响应丢失并不等于后端回滚。操作回执区分已提交、已确认未提交和未知；只有
 * 前两种状态可以释放内容屏障，未知必须保留草稿并暂停依赖操作。
 */
async function settleReplacementPreviewError(
  current: PreviewCommitOwner,
  guard: PreviewCommitGuard,
  getState: () => ConverterState,
  setState: (partial: Partial<ConverterState>) => void,
  error: unknown,
  fallback: string,
): Promise<ReplacementErrorSettlement> {
  if (!canCommitPreviewResponse(current, guard, replacementPreviewEpoch)) {
    // An old request can still have reached the backend before its error
    // response arrived. Reconcile the operation receipt instead of treating
    // the stale error as proof of rollback; same-session dependants must keep
    // waiting while the receipt is pending or unknown.
    // 旧请求的错误响应也可能晚于服务端实际提交到达。不能把过期错误直接当成
    // 回滚证据；同 session 的依赖操作要等待回执明确收敛。
    observeLateContentCommit(guard);
    if (
      current.sessionId === guard.sessionId &&
      contentCommitHandles.has(guard.replacementEpoch)
    ) {
      return { active: false, committed: false };
    }
    finishContentCommit(guard.replacementEpoch, false);
    return { active: false, committed: false };
  }

  const sessionId = guard.sessionId;
  if (!sessionId) {
    finishContentCommit(guard.replacementEpoch, false);
    return { active: true, committed: false };
  }

  setState({
    contentCommitStatus: "unknown",
    contentCommitOperationId: guard.operationId,
    replacePreviewLoading: false,
    historyBusy: false,
    error: visibleConverterError(error, fallback),
  });
  return reconcileContentCommitStatus(
    current,
    guard,
    getState,
    setState,
    visibleConverterError(error, fallback),
  );
}

async function reconcileUnknownContentCommit(
  getState: () => ConverterState,
  setState: (partial: Partial<ConverterState>) => void,
): Promise<void> {
  const current = getState();
  const operationId = current.contentCommitOperationId;
  if (!operationId || !current.sessionId) return;
  const handle = Array.from(contentCommitHandles.values()).find(
    (candidate) =>
      candidate.sessionId === current.sessionId &&
      candidate.operationId === operationId &&
      !candidate.settled,
  );
  if (!handle) return;
  const guard: PreviewCommitGuard = {
    sessionId: handle.sessionId,
    previewRequestRevision: current.previewRequestRevision,
    replacementEpoch: handle.replacementEpoch,
    operationId: handle.operationId,
  };
  await reconcileContentCommitStatus(
    current,
    guard,
    getState,
    setState,
    "编辑提交状态同步",
    { allowStaleReceipt: true },
  );
}

function invalidateReplacementPreviewCommits(): void {
  replacementPreviewEpoch += 1;
  for (const replacementEpoch of Array.from(contentCommitHandles.keys())) {
    finishContentCommit(replacementEpoch, false);
  }
  for (const reservations of Array.from(contentCommitReservations.values())) {
    for (const reservation of Array.from(reservations)) {
      releaseContentCommit(reservation, false);
    }
  }
}

const selectionMutationQueues = new Map<string, Promise<boolean>>();
let nextSelectionMutationId = 0;
const confirmedSelectionRevisions = new Map<
  string,
  {
    selectionRevision: number;
    contentRevision: number;
    editorContentRevision?: number;
  }
>();

function queueSelectionMutation(
  sessionId: string,
  mutationId: number,
  work: () => Promise<boolean>,
): Promise<boolean> {
  const previous = selectionMutationQueues.get(sessionId) ?? Promise.resolve(true);
  const run = async (): Promise<boolean> => {
    try {
      return await work();
    } finally {
      // Covers cancellation/session changes as well as failures. Successful
      // responses remove their intent atomically with the confirmed document.
      useConverterStore.setState((state) => {
        if (!state.pendingSelectionMutations.some((item) => item.id === mutationId)) return state;
        return { pendingSelectionMutations: state.pendingSelectionMutations.filter((item) => item.id !== mutationId) };
      });
    }
  };
  const next = previous.then(run, run);
  const settled = next.catch(() => false);
  selectionMutationQueues.set(sessionId, settled);
  void settled.then(() => {
    if (selectionMutationQueues.get(sessionId) === settled) {
      selectionMutationQueues.delete(sessionId);
    }
  });
  return settled;
}

function waitForSelectionMutation(sessionId: string): Promise<boolean> | null {
  return selectionMutationQueues.get(sessionId) ?? null;
}

/**
 * Whether a colour replacement may target the shared selection mask: either a
 * selection gesture is still in flight or a selection document is loaded.
 * 颜色替换是否可能作用于共享选区：仍有选区手势在提交，或已加载选区文档。
 */
function mayUseSharedSelectionReplace(
  state: Pick<ConverterState, "sessionId" | "selectionDocument">,
): boolean {
  if (!state.sessionId) return false;
  return (
    waitForSelectionMutation(state.sessionId) !== null ||
    state.selectionDocument?.selection_revision !== undefined
  );
}

function selectionDocumentVersion(
  document: Pick<SelectionDocumentResponse, "selection_revision" | "content_revision">,
): [number, number] {
  return [document.selection_revision, document.content_revision];
}

function isSelectionDocumentOlder(
  candidate: Pick<SelectionDocumentResponse, "selection_revision" | "content_revision">,
  known: { selectionRevision: number; contentRevision: number } | null,
): boolean {
  if (!known) return false;
  const [selectionRevision, contentRevision] = selectionDocumentVersion(candidate);
  return (
    selectionRevision < known.selectionRevision ||
    (selectionRevision === known.selectionRevision &&
      contentRevision < known.contentRevision)
  );
}

function rememberConfirmedSelectionDocument(
  sessionId: string,
  document: SelectionDocumentResponse,
): boolean {
  const known = confirmedSelectionRevisions.get(sessionId) ?? null;
  if (isSelectionDocumentOlder(document, known)) return false;
  confirmedSelectionRevisions.set(sessionId, {
    selectionRevision: document.selection_revision,
    contentRevision: document.content_revision,
    editorContentRevision: newestEditorContentRevision(
      document.editor_content_revision,
      known?.editorContentRevision,
    ),
  });
  return true;
}

async function readConfirmedSelectionDocument(
  sessionId: string,
  canPublish: () => boolean = () => true,
  recordMutation = false,
): Promise<void> {
  try {
    const document = await apiGetEditorSelection(sessionId);
    const current = useConverterStore.getState();
    if (current.sessionId !== sessionId || !canPublish()) return;
    const confirmed = confirmedSelectionRevisions.get(sessionId);
    if (
      isSelectionDocumentOlder(document, confirmed ?? null) ||
      (current.selectionDocument && isSelectionDocumentOlder(document, {
        selectionRevision: current.selectionDocument.selection_revision,
        contentRevision: current.selectionDocument.content_revision,
      }))
    ) return;
    rememberConfirmedSelectionDocument(sessionId, document);
    useConverterStore.setState(recordMutation || document.can_undo
      ? selectionUpdatesFromResponse(current, sessionId, document)
      : selectionStateFromDocument(document, getPreviewBaseUrl(current) ?? ""));
  } catch {
    // Startup and error reconciliation are best-effort. Mutations expose their
    // own errors and keep using only server-confirmed revisions.
  }
}

const freeColorMutationQueues = new Map<string, Promise<void>>();

function queueFreeColorMutation(
  sessionId: string,
  work: () => Promise<void>,
): Promise<void> {
  const previous = freeColorMutationQueues.get(sessionId) ?? Promise.resolve();
  const next = previous.then(work, work);
  const settled = next.catch(() => undefined);
  freeColorMutationQueues.set(sessionId, settled);
  void settled.then(() => {
    if (freeColorMutationQueues.get(sessionId) === settled) {
      freeColorMutationQueues.delete(sessionId);
    }
  });
  return next;
}

let regionSelectionMutationSeq = 0;
let lastRegionSelectionClearSeq = 0;
const removedRegionMutationSeq = new Map<string, number>();
let singleRegionDetectSeq = 0;
let latestSingleRegionDetectIntent:
  | { seq: number; x: number; y: number }
  | null = null;

function getRegionSelectionMutationSeq(): number {
  return regionSelectionMutationSeq;
}

function markRegionSelectionCleared(regionIds: Iterable<string | null | undefined>): void {
  regionSelectionMutationSeq += 1;
  lastRegionSelectionClearSeq = regionSelectionMutationSeq;
  for (const regionId of regionIds) {
    if (regionId) {
      removedRegionMutationSeq.set(regionId, regionSelectionMutationSeq);
    }
  }
}

function markRegionRemoved(regionId: string | null | undefined): void {
  if (!regionId) return;
  regionSelectionMutationSeq += 1;
  removedRegionMutationSeq.set(regionId, regionSelectionMutationSeq);
}

function wasRegionRemovedAfterRequest(
  regionId: string,
  mutationSeqAtRequest: number,
): boolean {
  return (
    lastRegionSelectionClearSeq > mutationSeqAtRequest ||
    (removedRegionMutationSeq.get(regionId) ?? 0) > mutationSeqAtRequest
  );
}

function beginSingleRegionDetectIntent(x: number, y: number): number {
  singleRegionDetectSeq += 1;
  latestSingleRegionDetectIntent = { seq: singleRegionDetectSeq, x, y };
  return singleRegionDetectSeq;
}

function hasNewerDifferentSingleRegionDetectIntent(
  seq: number,
  x: number,
  y: number,
): boolean {
  const latest = latestSingleRegionDetectIntent;
  return Boolean(
    latest &&
      latest.seq > seq &&
      (latest.x !== x || latest.y !== y),
  );
}

function extractFileIdFromApiUrl(
  url: string | null | undefined,
): string | null {
  if (!url) return null;
  const match = url.match(/\/api\/files\/([^/?#]+)/);
  return match ? match[1] : null;
}

function collectKeepFileIds(urls: Array<string | null | undefined>): string[] {
  const keepIds = new Set<string>();
  for (const url of urls) {
    const fileId = extractFileIdFromApiUrl(url);
    if (fileId) {
      keepIds.add(fileId);
    }
  }
  return Array.from(keepIds);
}

export function collectConverterKeepFileIds(state: {
  downloadUrl: string | null;
  previewImageUrl: string | null;
  previewBaseImageUrl: string | null;
  originalPreviewUrl: string | null;
  previewGlbUrl: string | null;
  modelUrl: string | null;
  puzzleOverlayUrl: string | null;
  batchPreviewItems: Array<{ url: string | null }>;
  regionData: { previewUrl: string | null } | null;
  selectedRegions: Array<{ previewUrl: string | null }>;
  layerImages: Array<{ url: string | null }>;
}): string[] {
  return collectKeepFileIds([
    state.downloadUrl,
    state.previewImageUrl,
    state.previewBaseImageUrl,
    state.originalPreviewUrl,
    state.previewGlbUrl,
    state.modelUrl,
    state.puzzleOverlayUrl,
    ...state.batchPreviewItems.map((item) => item.url),
    state.regionData?.previewUrl ?? null,
    ...state.selectedRegions.map((region) => region.previewUrl),
    ...state.layerImages.map((layer) => layer.url),
  ]);
}

const VALID_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/svg+xml",
  "image/webp",
  "image/heic",
  "image/heif",
  "image/x-adobe-dng",
  "image/x-canon-cr2",
  "image/x-canon-cr3",
  "image/x-nikon-nef",
  "image/x-sony-arw",
  "image/x-olympus-orf",
  "image/x-panasonic-rw2",
  "image/x-fuji-raf",
  "image/x-pentax-pef",
  "image/x-samsung-srw",
  "image/x-raw",
]);

export const ACCEPT_IMAGE_FORMATS =
  Array.from(VALID_IMAGE_TYPES).join(",") +
  "," +
  Array.from(RAW_EXTENSIONS_CONVERTER).join(",") +
  ",.jfif,.lumina.json";

export function isValidImageType(mimeType: string, fileName?: string): boolean {
  if (VALID_IMAGE_TYPES.has(mimeType)) return true;
  if (fileName) {
    const ext = fileName.toLowerCase().slice(fileName.lastIndexOf("."));
    if (ext === ".jfif" || RAW_EXTENSIONS_CONVERTER.has(ext)) return true;
  }
  return false;
}

function buildPreviewSessionResetState(
  current: ConverterState,
  preserveProjectComparisonState = false,
): Partial<ConverterState> {
  const previewAutoRefreshPending = preserveProjectComparisonState &&
    (current.hasManualPreview || current.previewAutoRefreshPending);
  const portableProjectColors = preserveProjectComparisonState
    ? buildSourceChangeProjectColorState(current)
    : null;
  return {
    sessionId: null,
    nativeMaterialSelection: null,
    nativeMaterialSelectionAction: null,
    nativeMaterialSelectionLoading: false,
    nativeMaterialSelectionError: null,
    isLoading: false,
    previewImageUrl: null,
    originalPreviewUrl: null,
    previewBaseImageUrl: null,
    previewGlbUrl: null,
    modelUrl: null,
    previewPerformanceTiming: null,
    generatePerformanceTiming: null,
    batchPreviewItems: [],
    threemfDiskPath: null,
    downloadUrl: null,
    generateWarnings: [],
    largeFormatWarnings: [],
    largeFormatFailedTiles: [],
    palette: [],
    materialDynamicRecipes: [],
    materialLayerBenefitCurve: [],
    materialLayerBenefitScope: "all_printable_pixels",
    materialLayerBenefitPixelCount: 0,
    colorContours: {},
    colorRemapMap: {},
    remapHistory: [],
    remapRedoHistory: [],
    historyCanUndo: false,
    historyCanRedo: false,
    historyBusy: false,
    contentCommitStatus: "idle",
    contentCommitOperationId: null,
    confirmedEditorCommit: null,
    replacement_regions: [],
    pendingEditorProject: preserveProjectComparisonState ? current.pendingEditorProject : null,
    recipe_overrides: [],
    customRecipeHistory: [],
    free_color_set: new Set<string>(),
    regionReplacementCount: 0,
    replacePreviewLoading: false,
    selectedColor: null,
    selectedColors: new Set<string>(),
    regionData: null,
    selectedRegions: [],
    selectionBlinkEnabled: false,
    selectionTool: "point",
    selectionDocument: null,
    pendingSelectionMutations: [],
    brushSizePx: 24,
    pendingReplacement: null,
    preview_width_mm: null,
    preview_height_mm: null,
    preview_spacer_thick: null,
    previewPixelWidth: null,
    previewPixelHeight: null,
    modelBounds: null,
    hasManualPreview: false,
    previewAutoRefreshPending,
    previewRequestRevision: current.previewRequestRevision + 1,
    ...EMPTY_LUT_MATCH_STATE,
    ...DEFAULT_LAYER_IMAGES_STATE,
    ...DEFAULT_PUZZLE_PREVIEW_STATE,
    ...(portableProjectColors ?? {}),
  };
}

const SVG_HOLE_COMPENSATION_STORAGE_KEY = "lumina_svgHoleCompensation";

function loadSvgHoleCompensationSettings(): SvgHoleCompensationOptions {
  try {
    const raw = localStorage.getItem(SVG_HOLE_COMPENSATION_STORAGE_KEY);
    const value = raw ? JSON.parse(raw) : {};
    const options = svgHoleCompensationOptions(value);
    if (validSvgHoleCompensationOptions(options)) return options;
  } catch {
    // Storage is optional; a damaged preference must not prevent startup.
  }
  return { ...SVG_HOLE_COMPENSATION_DEFAULTS };
}

/** Whether every current input is SVG. 当前输入是否全部为 SVG。 */
export function hasOnlySvgInputs(state: ConverterState): boolean {
  const files = state.batchMode ? state.batchFiles : [state.imageFile];
  return files.length > 0 && files.every(isSvgImageFile);
}

/** Whether the current source can use 2D compensation. 当前素材是否支持二维补洞。 */
export function isSvgHoleCompensationAvailable(state: ConverterState): boolean {
  return state.modeling_mode === ModelingModeEnum.VECTOR && hasOnlySvgInputs(state);
}

function persistSvgHoleCompensationSettings(options: SvgHoleCompensationOptions): void {
  try {
    localStorage.setItem(SVG_HOLE_COMPENSATION_STORAGE_KEY, JSON.stringify(options));
  } catch {
    // Saving settings is best-effort, including private browsing.
  }
}

function buildSvgHoleCompensationChangeState(
  current: ConverterState,
  updates: Partial<SvgHoleCompensationOptions>,
  resetPreview = true,
): Partial<ConverterState> {
  const options = { ...svgHoleCompensationOptions(current), ...updates };
  if (!isSvgHoleCompensationAvailable(current)) {
    options.svg_hole_compensation_enabled = false;
  }
  persistSvgHoleCompensationSettings(options);
  _cancelPreviewWork();
  invalidateGenerationRequests();
  return {
    ...(resetPreview ? buildPreviewSessionResetState(current, true) : {}),
    ...options,
    // Compensation changes SVG geometry, not the material solver cache key.
    // Keep an established preview baseline without a new cache preflight.
    hasManualPreview: current.hasManualPreview,
    isGenerating: false,
    batchLoading: false,
    batchResult: null,
  };
}

function buildSvgHoleCompensationResizeState(
  current: ConverterState,
  dimensions: Partial<Pick<ConverterState, "target_width_mm" | "target_height_mm">>,
): Partial<ConverterState> {
  const width = dimensions.target_width_mm ?? current.target_width_mm;
  const height = dimensions.target_height_mm ?? current.target_height_mm;
  if (
    !current.svg_hole_compensation_enabled ||
    !isSvgHoleCompensationAvailable(current) ||
    (width === current.target_width_mm && height === current.target_height_mm)
  ) {
    return {};
  }
  return buildSvgHoleCompensationChangeState(current, {});
}

function loadEnableCrop(): boolean {
  try {
    const stored = localStorage.getItem("lumina_enableCrop");
    if (stored === null) return true;
    return stored === "true";
  } catch {
    return true;
  }
}

const STRUCTURE_MODE_STORAGE_KEY = "lumina_structureMode";

function loadStructureMode(): StructureMode {
  try {
    const stored = localStorage.getItem(STRUCTURE_MODE_STORAGE_KEY);
    if (
      stored === StructureModeEnum.SINGLE_SIDED ||
      stored === StructureModeEnum.DOUBLE_SIDED
    ) {
      return stored;
    }
  } catch {
    // Local preferences are best-effort when browser storage is unavailable.
  }
  return StructureModeEnum.SINGLE_SIDED;
}

const OUTPUT_DIMENSIONS_STORAGE_KEY = "lumina_outputDimensions";
const BACKING_THICKNESS_STORAGE_KEY = "lumina_backingThickness";

function loadOutputDimensions() {
  try {
    const saved = JSON.parse(localStorage.getItem(OUTPUT_DIMENSIONS_STORAGE_KEY) ?? "null");
    if (
      saved && Number.isFinite(saved.target_width_mm) && saved.target_width_mm >= 10 &&
      Number.isFinite(saved.target_height_mm) && saved.target_height_mm >= 10
    ) {
      return { target_width_mm: saved.target_width_mm as number, target_height_mm: saved.target_height_mm as number };
    }
  } catch {
    // Browser preferences are best-effort.
  }
  return { target_width_mm: 60, target_height_mm: 60 };
}

function loadBackingThickness(): number {
  try {
    const saved = Number(localStorage.getItem(BACKING_THICKNESS_STORAGE_KEY));
    if (Number.isFinite(saved) && saved >= 0.2 && saved <= 10) return saved;
  } catch {
    // Browser preferences are best-effort.
  }
  return 1.2;
}

function buildImageAspectRatioState(state: ConverterState, ratio: number): Partial<ConverterState> {
  if (!Number.isFinite(ratio) || ratio <= 0) return {};
  // An imported project already supplies explicit dimensions before its image loads.
  if (state.aspectRatio !== null) return { aspectRatio: ratio };
  const remembered = state.conversionParameterContext === "defaults"
    ? useSettingsStore.getState().conversionPreferences.last
    : null;
  const longestEdge = remembered?.size_mm ?? Math.max(state.target_width_mm, state.target_height_mm);
  const requested = {
    target_width_mm: ratio >= 1 ? longestEdge : Math.max(10, Math.round(longestEdge * ratio)),
    target_height_mm: ratio >= 1 ? Math.max(10, Math.round(longestEdge / ratio)) : longestEdge,
  };
  const dimensions = fitTargetDimensions(requested, state, resolveConverterSettings(state, useSettingsStore.getState()).printerModel);
  return {
    aspectRatio: ratio,
    ...dimensions,
    fridge_magnets: canonicalizeFridgeMagnets(
      getFallbackModelBounds({ ...state, ...dimensions, modelBounds: null }),
      state.fridge_magnets,
    ),
  };
}

function buildPrinterDimensionState(state: ConverterState): Partial<ConverterState> {
  const dimensions = fitTargetDimensions(state, state, resolveConverterSettings(state, useSettingsStore.getState()).printerModel);
  if (dimensions.target_width_mm === state.target_width_mm && dimensions.target_height_mm === state.target_height_mm) return {};
  return {
    ...buildSvgHoleCompensationResizeState(state, dimensions),
    ...dimensions,
    fridge_magnets: canonicalizeFridgeMagnets(getFallbackModelBounds({ ...state, ...dimensions }), state.fridge_magnets),
    threemfDiskPath: null,
    downloadUrl: null,
  };
}

function loadLutName(): string {
  try {
    return localStorage.getItem("lumina_lastLut") ?? "";
  } catch {
    return "";
  }
}

function areStringArraysEqual(left: string[], right: string[]): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

function buildLegacySelectionAvailabilityUpdates(
  state: Pick<
    ConverterState,
    | "lut_name"
    | "lut_names"
    | "color_layers"
    | "layer_height_mm"
    | "model_enable"
    | "model_only"
    | "model_threshold"
    | "model_margin"
    | "lutListFull"
    | "legacyCatalogGroups"
  >,
  availableNames: Iterable<string>,
): Partial<ConverterState> {
  const available = new Set(availableNames);
  const normalized = normalizeLegacyLutNames(state.lut_names, state.lut_name);
  if (normalized.length === 0) {
    return {};
  }
  const primary = normalized[0];
  if (!available.has(primary)) {
    return {
      lut_name: "",
      lut_names: [],
      selectedLutInfo: null,
      color_layers: null,
      layer_height_mm: null,
      model_enable: false,
      model_only: false,
      model_threshold: null,
      model_margin: null,
    };
  }

  const filtered = normalized.filter((name) => available.has(name));
  if (state.lut_name !== primary || !areStringArraysEqual(state.lut_names, filtered)) {
    return {
      lut_name: primary,
      lut_names: filtered,
    };
  }
  return {};
}

const SELECTED_MATERIAL_DIR_NAMES_KEY = "lumina_selectedMaterialDirNames";
const MATERIAL_BACKING_MATERIAL_DIR_NAME_KEY =
  "lumina_materialBackingMaterialDirName";

function loadSelectedMaterialDirNames(): string[] {
  try {
    const raw = localStorage.getItem(SELECTED_MATERIAL_DIR_NAMES_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (value): value is string =>
        typeof value === "string" && value.trim().length > 0,
    );
  } catch {
    return [];
  }
}

function persistSelectedMaterialDirNames(names: string[]): void {
  try {
    localStorage.setItem(
      SELECTED_MATERIAL_DIR_NAMES_KEY,
      JSON.stringify(names),
    );
  } catch {
    /* localStorage unavailable, ignore */
  }
}

function loadMaterialBackingMaterialDirName(): string | null {
  try {
    const raw = localStorage.getItem(MATERIAL_BACKING_MATERIAL_DIR_NAME_KEY);
    return raw && raw.trim().length > 0 ? raw : null;
  } catch {
    return null;
  }
}

function normalizeBackingInfillDensityPercent(value: number): number {
  if (!Number.isFinite(value)) {
    return BACKING_INFILL_DENSITY_DEFAULT_PERCENT;
  }
  return clampValue(
    Math.round(value),
    BACKING_INFILL_DENSITY_MIN_PERCENT,
    BACKING_INFILL_DENSITY_MAX_PERCENT,
  );
}

function loadBackingInfillDensityPercent(): number {
  try {
    const raw = localStorage.getItem(BACKING_INFILL_DENSITY_STORAGE_KEY);
    if (raw === null) return BACKING_INFILL_DENSITY_DEFAULT_PERCENT;
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) {
      return BACKING_INFILL_DENSITY_DEFAULT_PERCENT;
    }
    return normalizeBackingInfillDensityPercent(parsed);
  } catch {
    return BACKING_INFILL_DENSITY_DEFAULT_PERCENT;
  }
}

function persistBackingInfillDensityPercent(density: number): void {
  try {
    localStorage.setItem(
      BACKING_INFILL_DENSITY_STORAGE_KEY,
      String(normalizeBackingInfillDensityPercent(density)),
    );
  } catch {
    /* localStorage unavailable, ignore */
  }
}

function persistMaterialBackingMaterialDirName(name: string | null): void {
  try {
    if (name && name.trim().length > 0) {
      localStorage.setItem(MATERIAL_BACKING_MATERIAL_DIR_NAME_KEY, name);
    } else {
      localStorage.removeItem(MATERIAL_BACKING_MATERIAL_DIR_NAME_KEY);
    }
  } catch {
    return;
  }
}

// ========== Default State ==========

const DEFAULT_LUT_NAME = loadLutName();

export const DEFAULT_STATE: ConverterState = {
  projectSettings: null,
  projectLutFile: null,
  projectMaterialArchiveFile: null,
  projectSourceKey: null,
  projectResourceSessionIds: [],
  imageFile: null,
  imagePreviewUrl: null,
  aspectRatio: null,
  preferredSizeAxis: "width",
  conversionParameterContext: "defaults",
  workshopSource: null,
  modelSurfaceEnabled: false,
  modelSurfaceFile: null,
  modelSurfacePreviewUrl: null,
  modelSurfaceModelFileId: null,
  modelSurfaceSummary: null,
  modelSurfaceSelectionId: null,
  modelSurfaceSelection: null,
  modelSurfaceFootprint: null,
  modelSurfaceCandidates: [],
  modelSurfacePlacement: { ...DEFAULT_MODEL_SURFACE_PLACEMENT },
  modelSurfaceModelRotation: { ...DEFAULT_MODEL_SURFACE_MODEL_ROTATION },
  modelSurfaceLoading: false,
  modelSurfaceSelecting: false,
  modelSurfaceError: null,
  modelSurfaceWarnings: [],
  sessionId: null,
  source_version: "material",
  lut_name: DEFAULT_LUT_NAME,
  lut_names: normalizeLegacyLutNames([], DEFAULT_LUT_NAME),
  nativeBrandGroups: [],
  nativeBrandGroupsLoading: false,
  selectedNativeBrandKey: "",
  selectedNativeDbNames: [],
  ...loadOutputDimensions(),
  spacer_thick: loadBackingThickness(),
  backing_infill_density_percent: loadBackingInfillDensityPercent(),
  structure_mode: loadStructureMode(),
  color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
  modeling_mode: ModelingModeEnum.HIGH_FIDELITY,
  color_layers: null,
  layer_height_mm: null,
  model_enable: false,
  model_only: false,
  model_threshold: null,
  model_margin: null,
  selectedLutInfo: null,
  selectedMaterialDirNames: loadSelectedMaterialDirNames(),
  materialLayerCount: 5,
  materialLayerHeightMm: 0.08,
  materialBackingMaterialDirName: loadMaterialBackingMaterialDirName(),
  materialDynamicLayerCountEnabled: false,
  materialMinLayerCount: MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
  materialMaxLayerCount: MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  materialDynamicRecipes: [],
  materialLayerBenefitCurve: [],
  materialLayerBenefitScope: "all_printable_pixels",
  materialLayerBenefitPixelCount: 0,
  quantize_colors: 48,
  quantize_colors_unlocked: false,
  high_precision_3d_preview: false,
  enable_cleanup: true,
  ...loadSvgHoleCompensationSettings(),
  svg_hole_compensation_enabled: false,
  hue_enable: false,
  use_lut_constrained: false,
  auto_dynamic_range: false,
  chroma_gate: 15,
  separate_backing: false,
  backingOutput: "same_project",
  add_loop: false,
  loop_width: 4.0,
  loop_length: 8.0,
  loop_hole: 2.5,
  loop_angle: 0,
  loop_offset_x: 0,
  loop_offset_y: 0,
  loop_position_preset: "top-center",
  enable_fridge_magnet: false,
  fridge_magnets: [],
  selectedFridgeMagnetId: null,
  base_spacer_thick: loadBackingThickness(),
  enable_relief: false,
  color_height_map: {},
  heightmap_max_height: 3.0,
  enable_outline: false,
  outline_width: 2.0,
  enable_cloisonne: false,
  wire_width_mm: 0.4,
  wire_height_mm: 0.4,
  enable_coating: false,
  coating_height_mm: 0.08,
  largeFormatEnabled: false,
  tileWidthMm: 250,
  tileHeightMm: 250,
  largeFormatTileOverlayVisible: true,
  puzzleEnabled: false,
  puzzleStyle: "regular" as PuzzleStyle,
  puzzleSizingMode: "piece_size" as PuzzleSizingMode,
  pieceWidthMm: 20,
  pieceHeightMm: 20,
  puzzleRows: 3,
  puzzleCols: 3,
  targetPieceCount: 12,
  connectorStyle: "classic" as PuzzleConnectorStyle,
  labelsEnabled: false,
  engraveBackLabels: false,
  irregularityStrength: 0.35,
  minNeckWidthMm: 1.2,
  ...DEFAULT_PUZZLE_PREVIEW_STATE,
  replacement_regions: [],
  recipe_overrides: [],
  customRecipeHistory: [],
  free_color_set: new Set(),
  selectedColor: null,
  palette: [],
  colorRemapMap: {},
  remapHistory: [],
  remapRedoHistory: [],
  historyCanUndo: false,
  historyCanRedo: false,
  historyBusy: false,
  contentCommitStatus: "idle",
  contentCommitOperationId: null,
  confirmedEditorCommit: null,
  pendingEditorProject: null,
  colorContours: {},
  autoHeightMode: "darker-higher" as AutoHeightMode,
  heightmapFile: null,
  heightmapThumbnailUrl: null,
  heightmapUploadSessionId: null,
  previewGlbUrl: null,
  previewPerformanceTiming: null,
  generatePerformanceTiming: null,
  lutMatchMode: null,
  lutMatchInfo: null,
  preview_width_mm: null,
  preview_height_mm: null,
  preview_spacer_thick: null,
  previewPixelWidth: null,
  previewPixelHeight: null,
  previewWarnings: [],
  generateWarnings: [],
  largeFormatWarnings: [],
  largeFormatFailedTiles: [],
  modelBounds: null,
  enableCrop: loadEnableCrop(),
  cropModalOpen: false,
  isCropping: false,
  autoDetectColorsLoading: false,
  isLoading: false,
  isGenerating: false,
  native_filament_profiles: {},
  nativeFilamentProfileScope: null,
  nativeMaterialSelection: null,
  nativeMaterialSelectionAction: null,
  nativeMaterialSelectionLoading: false,
  nativeMaterialSelectionError: null,
  error: null,
  previewImageUrl: null,
  modelUrl: null,
  lutList: [],
  lutListLoading: false,
  lutListFull: [],
  legacyCatalogGroups: [],
  legacyCatalogLoading: false,
  selectedLegacyManufacturer: "",
  lutColors: [],
  lutColorCards: [],
  lutColorsLoading: false,
  lutColorsLutName: "",
  lutColorsSessionId: null,
  materialSuggestions: null,
  materialSuggestionsLoading: false,
  materialSuggestionsTargetHex: null,
  materialSuggestionsError: null,
  gradientGroups: null,
  gradientGroupsLoading: false,
  gradientGroupsError: null,
  gradientGroupsSessionId: null,
  gradientSelection: null,
  selectedGradientRegions: [],
  bed_label: "256×256 mm",
  bedSizes: [],
  bedSizesLoading: false,
  batchMode: false,
  batchFiles: [],
  batchLoading: false,
  batchResult: null,
  batchPreviewItems: [],
  replacePreviewLoading: false,
  originalPreviewUrl: null,
  previewBaseImageUrl: null,
  threemfDiskPath: null,
  downloadUrl: null,
  ...DEFAULT_LAYER_IMAGES_STATE,
  selectionMode: "multi-select" as SelectionMode,
  selectionTool: "point" as SelectionTool,
  selectionDocument: null,
  pendingSelectionMutations: [],
  brushSizePx: 24,
  colorRangeTolerance: DEFAULT_COLOR_RANGE_TOLERANCE,
  selectedColors: new Set<string>(),
  regionData: null,
  selectedRegions: [],
  selectionBlinkEnabled: false,
  pendingReplacement: null,
  regionReplacementCount: 0,
  hasManualPreview: false,
  previewAutoRefreshPending: false,
  previewRequestRevision: 0,
  previewSubmissionSequence: 0,
};

// ========== Client-side timing log (writes to server log) ==========
let _previewStartTime: number | null = null;
const _PREVIEW_TIMER_LABEL = "[LUMINA] preview";
let _previewTimerActive = false;

function _startPreviewTimer(): void {
  if (_previewTimerActive) {
    try {
      console.timeEnd(_PREVIEW_TIMER_LABEL);
    } catch {
      void 0;
    }
  }
  console.time(_PREVIEW_TIMER_LABEL);
  _previewTimerActive = true;
}

function _logPreviewTimer(message: string): void {
  if (!_previewTimerActive) return;
  try {
    console.timeLog(_PREVIEW_TIMER_LABEL, message);
  } catch {
    void 0;
  }
}

function _endPreviewTimer(): void {
  if (!_previewTimerActive) return;
  try {
    console.timeEnd(_PREVIEW_TIMER_LABEL);
  } catch {
    void 0;
  }
  _previewTimerActive = false;
}

function _previewClientLog(
  label: string,
  details?: Record<string, unknown>,
  method: "log" | "warn" | "error" = "log",
) {
  postClientLog(label, {
    startTime: _previewStartTime,
    details,
    scope: "preview",
    phase: label,
    method,
  });
}

/**
 * Re-read the authoritative editor content revision from the backend.
 * 从后端重新读取权威编辑内容版本。
 *
 * @returns Whether a finite revision was confirmed for the session.
 *   (是否为该 session 确认到有效版本)
 */
async function refreshConfirmedEditorContentRevision(
  sessionId: string,
): Promise<boolean> {
  try {
    const document = await apiGetEditorSelection(sessionId);
    const revision = document.editor_content_revision;
    if (typeof revision !== "number" || !Number.isFinite(revision)) return false;
    if (useConverterStore.getState().sessionId !== sessionId) return false;
    rememberConfirmedEditorContentRevision(sessionId, revision);
    return true;
  } catch {
    return false;
  }
}

// ========== Preview AbortController ==========

let _previewAbortController: AbortController | null = null;

/** Cancel every async task owned by the current preview input. */
function _cancelPreviewWork(): void {
  if (_previewAbortController) {
    _previewAbortController.abort();
    _previewAbortController = null;
  }
  _gradientGroupsAbortController?.abort();
  _gradientGroupsAbortController = null;
  cancelDerivedPreviewWork();
  invalidateReplacementPreviewCommits();
  _endPreviewTimer();
}

// ========== Store ==========

function restoreConversionDefaultsForNewSource(): void {
  const current = useConverterStore.getState();
  if (current.conversionParameterContext !== "project") return;
  current.restoreConversionDefaults();
}

/** Serialize full-map edits and keep their optimistic state owned by the receipt. */
async function commitColorRemap(
  getState: () => ConverterState & ConverterActions,
  setState: (updates: Partial<ConverterState>) => void,
  updateMap?: (state: ConverterState) => Record<string, string> | null,
  failureMessage = "颜色替换预览失败",
): Promise<void> {
  const sid = getState().sessionId;
  if (!sid) return;
  const pendingSelection = waitForSelectionMutation(sid);
  if (pendingSelection && !(await pendingSelection)) return;
  const reservation = acquireContentCommitTurn(sid);
  if (!reservation.readyImmediately && !(await reservation.ready)) {
    releaseContentCommit(reservation, false);
    return;
  }
  const state = getState();
  if (state.sessionId !== sid) {
    releaseContentCommit(reservation, false);
    return;
  }
  const map = updateMap ? updateMap(state) : state.colorRemapMap;
  if (!map) {
    releaseContentCommit(reservation, false);
    return;
  }
  const previewCommit = captureReplacementPreviewCommit(state, reservation);
  if (updateMap) {
    // The same rollback applies to immediate failure and a later failed receipt.
    attachContentCommitRollback(previewCommit, {
      colorRemapMap: state.colorRemapMap,
      remapHistory: state.remapHistory,
      remapRedoHistory: state.remapRedoHistory,
      threemfDiskPath: state.threemfDiskPath,
      downloadUrl: state.downloadUrl,
    });
  }
  setState({
    ...(updateMap ? {
      colorRemapMap: map,
      remapHistory: [...state.remapHistory, { ...state.colorRemapMap }],
      remapRedoHistory: [],
      threemfDiskPath: null,
      downloadUrl: null,
    } : {}),
    replacePreviewLoading: true,
    error: null,
  });
  try {
    const pairs = Object.entries(map).map(([origHex, newHex]) => ({
      selectedColor: `#${state.palette.find(p => p.matched_hex === origHex)?.matched_hex ?? origHex}`,
      replacementColor: `#${newHex}`,
    }));
    const response = await apiReplaceColorsBatch(sid, pairs, previewCommit.operationId);
    if (!isCurrentReplacementPreviewCommit(getState(), previewCommit)) return;
    setState({
      replacePreviewLoading: false,
      previewImageUrl: normalizeResourceUrl(response.preview_url),
      previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
      ...(response.preview_3d_url ? { previewGlbUrl: normalizeResourceUrl(response.preview_3d_url) } : {}),
      ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
      ...dynamicMaterialResultState(response),
      ...historyFlagsFromResponse(response),
      ...selectionUpdatesFromResponse(getState(), sid, response.selection),
    });
    getState()._pollAsyncGlb();
  } catch (err) {
    const settlement = await settleReplacementPreviewError(
      getState(), previewCommit, getState, setState, err, failureMessage,
    );
    if (!settlement.active || settlement.committed || settlement.unknown) return;
    setState({ replacePreviewLoading: false, error: visibleConverterError(err, failureMessage) });
  }
}

/** One backend history transition owns ordering, receipts and preview publication. */
async function navigateEditorHistory(
  direction: "undo" | "redo",
  getState: () => ConverterState & ConverterActions,
  setState: (updates: Partial<ConverterState>) => void,
): Promise<void> {
  const state = getState();
  if (!state.sessionId || state.historyBusy) return;
  const failureMessage = direction === "undo" ? "撤销颜色调整失败" : "重做颜色调整失败";
  const sid = state.sessionId;
  const pendingSelection = waitForSelectionMutation(sid);
  if (pendingSelection && !(await pendingSelection)) return;
  const contentReservation = acquireContentCommitTurn(sid);
  if (
    !contentReservation.readyImmediately &&
    !(await contentReservation.ready)
  ) {
    releaseContentCommit(contentReservation, false);
    return;
  }
  const latestState = getState();
  if (
    latestState.sessionId !== sid ||
    latestState.historyBusy ||
    !(direction === "undo" ? latestState.historyCanUndo : latestState.historyCanRedo)
  ) {
    releaseContentCommit(contentReservation, false);
    return;
  }
  const previewCommit = captureReplacementPreviewCommit(
    latestState,
    contentReservation,
  );
  setState({ historyBusy: true, replacePreviewLoading: true, error: null });
  try {
    const response = await apiReplacementHistory(
      sid,
      direction,
      previewCommit.operationId,
    );
    if (
      !isCurrentReplacementPreviewCommit(getState(), previewCommit)
    ) return;
    setState({
      ...editorCommitStateFromResponse(response),
      ...buildHistoryRestoreState(response),
      historyBusy: false,
      replacePreviewLoading: false,
      ...selectionUpdatesFromResponse(getState(), sid, response.selection),
    });
    if (response.entry_kind !== "selection") {
      getState()._pollAsyncGlb();
    }
  } catch (err) {
    const settlement = await settleReplacementPreviewError(
      getState(),
      previewCommit,
      getState,
      setState,
      err,
      failureMessage,
    );
    if (!settlement.active || settlement.committed || settlement.unknown) return;
    setState({
      historyBusy: false,
      replacePreviewLoading: false,
      error: apiErrorToVisibleMessage(err, failureMessage),
    });
  }
}

const documentCommand = createDocumentCommandWrapper((action, blocked, options) =>
  converterDocumentHistory.run(action, blocked, options));

export const useConverterStore = create<ConverterState & ConverterActions>()(
  subscribeWithSelector((set, _get) => ({
    ...DEFAULT_STATE,
    ...createGenerationActions(set, _get, {
      waitForSelectionMutation,
      waitForContentCommits,
      getReplacementEpoch: () => replacementPreviewEpoch,
      confirmedEditorRevision: (sessionId) => confirmedSelectionRevisions.get(sessionId)?.editorContentRevision,
      refreshConfirmedEditorContentRevision,
    }, documentCommand),
    ...createDerivedPreviewActions(set, _get),
    ...createConversionPresetActions(set, _get, documentCommand),

    setProjectSettings: documentCommand((changes) => {
      const current = _get();
      const defaults = useSettingsStore.getState();
      const palette = externalSpoolPaletteKey(current);
      const previous = current.projectSettings ?? {
        ...captureProjectSettings(defaults),
        externalSpoolSelections: withExternalSpoolSelection(palette, defaults.externalSpoolSelections[palette]),
      };
      const settings = { ...previous, ...changes };
      if (JSON.stringify(previous) === JSON.stringify(settings)) {
        if (!current.projectSettings) set({ projectSettings: settings });
        return;
      }
      invalidateGeneratedArtifacts({ preservePreviews: true });
      const dimensions = buildPrinterDimensionState({ ...current, projectSettings: settings });
      const previewChanged = ["svgPixelsPerMm", "materialDeltaE00Tolerance", "enableSolverCacheGridSelection", "solverCacheGridResolution"]
        .some((key) => previous[key as keyof typeof previous] !== settings[key as keyof typeof settings]);
      set({ projectSettings: settings, ...dimensions });
      _get().clearMaterialSuggestions();
      if (previewChanged && (current.sessionId || current.isLoading || current.hasManualPreview)) _get().invalidatePreviewForAutoRefresh();
    }),

    // --- 图片 ---
    commitProjectRestore: (state) => {
      _cancelPreviewWork();
      invalidateGenerationRequests();
      _materialSuggestCache.clear();
      state = withCurrentConverterCatalogs(state, _get());
      const printer = resolveConverterSettings(state, useSettingsStore.getState()).printerModel;
      const bed = state.bedSizes.find((item) => item.printer_id === printer);
      set({ ...state, ...(bed ? { bed_label: bed.label } : {}), previewRequestRevision: _get().previewRequestRevision + 1, previewSubmissionSequence: _get().previewSubmissionSequence + 1 });
    },
    setImageFile: documentCommand((file: File | null) => {
      const currentFile = _get().imageFile;
      // Rotations and other derived images still belong to the current project.
      // Restore daily defaults only when the underlying source is replaced or cleared.
      if (!file || !currentFile || resolveSourceFile(file) !== resolveSourceFile(currentFile)) {
        restoreConversionDefaultsForNewSource();
      }
      _cancelPreviewWork();

      // Revoke previous blob URL to avoid memory leaks
      const currentState = _get();
      const prev = currentState.imagePreviewUrl;
      if (prev && prev.startsWith("blob:")) {
        URL.revokeObjectURL(prev);
      }
      const modelSurfaceArtworkReset = _get().modelSurfaceEnabled
        ? { modelSurfacePlacement: { ...DEFAULT_MODEL_SURFACE_PLACEMENT } }
        : {};

      if (!file) {
        const currentMode = currentState.modeling_mode;
        set({
          imageFile: null,
          imagePreviewUrl: null,
          aspectRatio: null,
          workshopSource: null,
          ...modelSurfaceArtworkReset,
          modeling_mode: currentMode === ModelingModeEnum.VECTOR
            ? ModelingModeEnum.HIGH_FIDELITY
            : currentMode,
          ...buildPreviewSessionResetState(currentState),
        });
        return;
      }

      if (isRawFileConverter(file)) {
        const shouldOpenCrop = currentState.enableCrop;
        set({
          imageFile: file,
          imagePreviewUrl: null,
          aspectRatio: null,
          workshopSource: null,
          ...modelSurfaceArtworkReset,
          modeling_mode: currentState.modeling_mode === ModelingModeEnum.VECTOR
            ? ModelingModeEnum.HIGH_FIDELITY
            : currentState.modeling_mode,
          ...buildPreviewSessionResetState(currentState),
          cropModalOpen: shouldOpenCrop,
        });
        uploadImagePreview(file)
          .then(({ preview_url, width, height }) => {
            if (_get().imageFile !== file || _get().imagePreviewUrl !== null) {
              return;
            }
            set({
              imagePreviewUrl: preview_url,
              ...buildImageAspectRatioState(_get(), width / height),
              error: null,
            });
          })
          .catch((err) => {
            if (_get().imageFile !== file || _get().imagePreviewUrl !== null) {
              return;
            }
            set({ error: rawPreviewFailureMessage(err) });
          });
        return;
      }

      const previewUrl = URL.createObjectURL(file);

      // Calculate aspect ratio from image dimensions
      const img = new Image();
      img.onload = () => {
        if (
          _get().imageFile !== file ||
          _get().imagePreviewUrl !== previewUrl
        ) {
          return;
        }
        const ratio = img.naturalWidth / img.naturalHeight;
        set(buildImageAspectRatioState(_get(), ratio));
      };
      img.src = previewUrl;

      const isSvg = isSvgImageFile(file);
      const shouldOpenCrop = currentState.enableCrop && !isSvg;
      const modelingMode = isSvg
        ? ModelingModeEnum.VECTOR
        : currentState.modeling_mode === ModelingModeEnum.VECTOR
          ? ModelingModeEnum.HIGH_FIDELITY
          : currentState.modeling_mode;
      set({
        imageFile: file,
        imagePreviewUrl: previewUrl,
        aspectRatio: null,
        workshopSource: null,
        ...(isSvg ? loadSvgHoleCompensationSettings() : { svg_hole_compensation_enabled: false }),
        ...modelSurfaceArtworkReset,
        modeling_mode: modelingMode,
        ...buildPreviewSessionResetState(currentState),
        cropModalOpen: shouldOpenCrop,
      });
    }, { joinAsync: true }),

    rotateImageForExport: documentCommand(async (degrees: ImageRotationDegrees) => {
      const state = _get();
      if (!state.imageFile || !state.imagePreviewUrl || state.batchMode) {
        return;
      }
      set({ isLoading: true, error: null });
      try {
        const rotatedFile = await rotateImageFile(
          state.imageFile,
          state.imagePreviewUrl,
          degrees,
        );
        rememberDerivedImageSource(rotatedFile, state.imageFile);
        _get().setImageFile(rotatedFile);
        if (state.conversionParameterContext === "project") {
          // A project owns exact millimeter dimensions. Publish the rotated
          // axes before Image.onload so it only updates the artwork ratio.
          const rotatedSize = resolveRotatedImageSize(
            state.target_width_mm, state.target_height_mm, degrees,
          );
          const aspectRatio = rotatedSize.width / rotatedSize.height;
          const dimensions = fitTargetDimensions({
            target_width_mm: rotatedSize.width,
            target_height_mm: rotatedSize.height,
          }, { ...state, aspectRatio }, useSettingsStore.getState().printerModel);
          set({
            ...dimensions,
            aspectRatio,
            fridge_magnets: canonicalizeFridgeMagnets(
              getFallbackModelBounds({ ...state, ...dimensions, modelBounds: null }),
              state.fridge_magnets,
            ),
          });
        }
      } catch (err) {
        set({
          error: visibleConverterError(err, tRuntime("basic_image_rotation_failed")),
        });
      } finally {
        if (_get().isLoading) {
          set({ isLoading: false });
        }
      }
    }, { blocked: () => Promise.resolve() }),

    loadVectorizedSvgIntoConverter: documentCommand((file: File) => {
      restoreConversionDefaultsForNewSource();
      _cancelPreviewWork();

      const currentState = _get();
      const prev = currentState.imagePreviewUrl;
      if (prev && prev.startsWith("blob:")) {
        URL.revokeObjectURL(prev);
      }
      const modelSurfaceArtworkReset = _get().modelSurfaceEnabled
        ? { modelSurfacePlacement: { ...DEFAULT_MODEL_SURFACE_PLACEMENT } }
        : {};

      const previewUrl = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        if (
          _get().imageFile !== file ||
          _get().imagePreviewUrl !== previewUrl
        ) {
          return;
        }
        set(buildImageAspectRatioState(_get(), img.naturalWidth / img.naturalHeight));
      };
      img.src = previewUrl;

      set({
        imageFile: file,
        imagePreviewUrl: previewUrl,
        aspectRatio: null,
        workshopSource: null,
        ...modelSurfaceArtworkReset,
        ...buildPreviewSessionResetState(currentState),
        modeling_mode: ModelingModeEnum.VECTOR,
        ...loadSvgHoleCompensationSettings(),
        isLoading: false,
        error: null,
        cropModalOpen: false,
        batchMode: false,
        batchFiles: [],
        batchResult: null,
        batchLoading: false,
        previewWarnings: [],
        generateWarnings: [],
        largeFormatWarnings: [],
        largeFormatFailedTiles: [],
        gradientGroups: null,
        gradientGroupsLoading: false,
        gradientGroupsError: null,
        gradientGroupsSessionId: null,
        gradientSelection: null,
        selectedGradientRegions: [],
        puzzleEnabled: false,
      });
    }),

    loadWorkshopImageIntoConverter: documentCommand(({
      file,
      pixelWidth,
      pixelHeight,
      targetWidthMm,
      targetHeightMm,
      source,
    }) => {
      restoreConversionDefaultsForNewSource();
      _cancelPreviewWork();

      const currentState = _get();
      const previousPreviewUrl = currentState.imagePreviewUrl;
      if (
        previousPreviewUrl &&
        previousPreviewUrl.startsWith("blob:")
      ) {
        URL.revokeObjectURL(previousPreviewUrl);
      }

      const previewUrl = URL.createObjectURL(file);
      const modelSurfaceArtworkReset = currentState.modelSurfaceEnabled
        ? { modelSurfacePlacement: { ...DEFAULT_MODEL_SURFACE_PLACEMENT } }
        : {};
      set({
        imageFile: file,
        imagePreviewUrl: previewUrl,
        aspectRatio: pixelWidth / pixelHeight,
        workshopSource: source,
        target_width_mm: targetWidthMm,
        target_height_mm: targetHeightMm,
        ...modelSurfaceArtworkReset,
        ...buildPreviewSessionResetState(currentState),
        modeling_mode:
          isSvgImageFile(file)
            ? ModelingModeEnum.VECTOR
            : currentState.modeling_mode === ModelingModeEnum.VECTOR
            ? ModelingModeEnum.HIGH_FIDELITY
            : currentState.modeling_mode,
        cropModalOpen: false,
        isCropping: false,
        batchMode: false,
        batchFiles: [],
        batchResult: null,
        batchLoading: false,
        previewWarnings: [],
        generateWarnings: [],
        largeFormatWarnings: [],
        largeFormatFailedTiles: [],
        gradientGroups: null,
        gradientGroupsLoading: false,
        gradientGroupsError: null,
        gradientGroupsSessionId: null,
        gradientSelection: null,
        selectedGradientRegions: [],
        puzzleEnabled: false,
        error: null,
      });
    }),

    setModelSurfaceEnabled: documentCommand((enabled: boolean) => {
      set((state) => ({
        modelSurfaceEnabled: enabled,
        backing_infill_density_percent: enabled
          ? BACKING_INFILL_DENSITY_DEFAULT_PERCENT
          : state.enable_relief ? BACKING_INFILL_DENSITY_DEFAULT_PERCENT : loadBackingInfillDensityPercent(),
        structure_mode: enabled
          ? StructureModeEnum.SINGLE_SIDED
          : state.structure_mode,
        modelSurfaceError: null,
        ...buildPreviewSessionResetState(state),
      }));
    }),

    uploadModelSurfaceFile: documentCommand(async (file: File) => {
      const currentState = _get();
      const prev = currentState.modelSurfacePreviewUrl;
      if (prev && prev.startsWith("blob:")) {
        URL.revokeObjectURL(prev);
      }
      const previewUrl = URL.createObjectURL(file);
      set({
        modelSurfaceEnabled: true,
        backing_infill_density_percent:
          BACKING_INFILL_DENSITY_DEFAULT_PERCENT,
        structure_mode: StructureModeEnum.SINGLE_SIDED,
        modelSurfaceFile: file,
        modelSurfacePreviewUrl: previewUrl,
        modelSurfaceModelFileId: null,
        modelSurfaceSummary: null,
        modelSurfaceSelectionId: null,
        modelSurfaceSelection: null,
        modelSurfaceFootprint: null,
        modelSurfaceCandidates: [],
        modelSurfacePlacement: { ...DEFAULT_MODEL_SURFACE_PLACEMENT },
        modelSurfaceModelRotation: { ...DEFAULT_MODEL_SURFACE_MODEL_ROTATION },
        modelSurfaceLoading: true,
        modelSurfaceSelecting: false,
        modelSurfaceError: null,
        modelSurfaceWarnings: [],
        ...buildPreviewSessionResetState(currentState),
      });
      try {
        const response = await apiUploadModelSurface(file);
        if (_get().modelSurfaceFile !== file) {
          return;
        }
        set({
          modelSurfaceLoading: false,
          modelSurfaceModelFileId: response.model_file_id,
          modelSurfaceSummary: response.summary,
          modelSurfaceCandidates: response.surface_candidates ?? [],
          modelSurfaceWarnings: response.warnings ?? [],
          modelSurfaceError: null,
        });
      } catch (err) {
        if (_get().modelSurfaceFile !== file) {
          return;
        }
        set({
          modelSurfaceLoading: false,
          modelSurfaceModelFileId: null,
          modelSurfaceError: visibleConverterError(
            err,
            tRuntime("model_surface_upload_failed"),
          ),
        });
      }
    }, { blocked: () => Promise.resolve() }),

    clearModelSurface: documentCommand(() => {
      const currentState = _get();
      const prev = currentState.modelSurfacePreviewUrl;
      if (prev && prev.startsWith("blob:")) {
        URL.revokeObjectURL(prev);
      }
      set({
        modelSurfaceEnabled: false,
        modelSurfaceFile: null,
        modelSurfacePreviewUrl: null,
        modelSurfaceModelFileId: null,
        modelSurfaceSummary: null,
        modelSurfaceSelectionId: null,
        modelSurfaceSelection: null,
        modelSurfaceFootprint: null,
        modelSurfaceCandidates: [],
        modelSurfacePlacement: { ...DEFAULT_MODEL_SURFACE_PLACEMENT },
        modelSurfaceModelRotation: { ...DEFAULT_MODEL_SURFACE_MODEL_ROTATION },
        modelSurfaceLoading: false,
        modelSurfaceSelecting: false,
        modelSurfaceError: null,
        modelSurfaceWarnings: [],
        ...buildPreviewSessionResetState(currentState),
      });
    }),

    selectModelSurfaceFace: documentCommand(async (faceIndex: number, candidateId?: string) => {
      const state = _get();
      if (state.modelSurfaceLoading || state.modelSurfaceSelecting) {
        return;
      }
      if (!state.modelSurfaceModelFileId || !Number.isFinite(faceIndex)) {
        set({ modelSurfaceError: tRuntime("model_surface_error_upload_first") });
        return;
      }
      const modelFileId = state.modelSurfaceModelFileId;
      set({
        modelSurfaceSelecting: true,
        modelSurfaceError: null,
      });
      try {
        const response: ModelSurfaceSelectResponse = await apiSelectModelSurface(
          modelFileId,
          {
            face_index: Math.max(0, Math.floor(faceIndex)),
            ...(candidateId ? { candidate_id: candidateId } : {}),
            model_transform: {
              rotation_deg: {
                x: state.modelSurfaceModelRotation.x_deg,
                y: state.modelSurfaceModelRotation.y_deg,
                z: state.modelSurfaceModelRotation.z_deg,
              },
            },
          },
        );
        if (_get().modelSurfaceModelFileId !== modelFileId) {
          return;
        }
        set((currentState) => ({
          modelSurfaceSelecting: false,
          modelSurfaceSelectionId: response.selection_id,
          modelSurfaceSelection: response.selection,
          modelSurfaceFootprint: response.footprint,
          modelSurfacePlacement: { ...DEFAULT_MODEL_SURFACE_PLACEMENT },
          modelSurfaceWarnings: response.warnings ?? [],
          modelSurfaceError: null,
          ...buildPreviewSessionResetState(currentState),
        }));
      } catch (err) {
        if (_get().modelSurfaceModelFileId !== modelFileId) {
          return;
        }
        set({
          modelSurfaceSelecting: false,
          modelSurfaceError: visibleConverterError(
            err,
            tRuntime("model_surface_select_failed"),
          ),
        });
      }
    }, { blocked: () => Promise.resolve() }),

    updateModelSurfacePlacement: documentCommand((updates: Partial<ModelSurfacePlacement>) => {
      const currentState = _get();
      const current = currentState.modelSurfacePlacement;
      set({
        modelSurfacePlacement: {
          ...current,
          ...updates,
          scale: clampValue(updates.scale ?? current.scale, 0.1, 10),
          inset_mm: Math.max(0, updates.inset_mm ?? current.inset_mm),
        },
        ...buildPreviewSessionResetState(currentState),
      });
    }),

    updateModelSurfaceModelRotation: documentCommand((updates: Partial<ModelSurfaceModelRotation>) => {
      const currentState = _get();
      const current = currentState.modelSurfaceModelRotation;
      set({
        modelSurfaceModelRotation: {
          ...current,
          ...updates,
        },
        ...buildPreviewSessionResetState(currentState),
      });
    }),

    fitModelSurfaceArtwork: documentCommand(() => {
      set((state) => ({
        modelSurfacePlacement: { ...DEFAULT_MODEL_SURFACE_PLACEMENT },
        ...buildPreviewSessionResetState(state),
      }));
    }),

    // --- 基础参数 ---
    setLutName: documentCommand((name: string) => {
      const state = _get();
      const lutInfo = state.lutListFull.find((l) => l.name === name);
      const lutLocation = lutInfo
        ? findLutLocationByPath(
            buildLutCatalogIndex(state.legacyCatalogGroups),
            lutInfo.path,
          )
        : null;
      const updates: Partial<ConverterState> = {
        source_version: "legacy",
        lut_name: name,
        lut_names: name ? [name] : [],
        selectedLutInfo: null,
        selectedNativeBrandKey: "",
        selectedNativeDbNames: [],
        color_layers: null,
        layer_height_mm: null,
        model_enable: false,
        model_only: false,
        model_threshold: null,
        model_margin: null,
        ...buildPreviewSessionResetState(state, true),
      };
      if (lutLocation) {
        updates.selectedLegacyManufacturer = lutLocation.manufacturer;
      }
      if (lutInfo && lutInfo.color_mode) {
        updates.color_mode = normalizePublicColorMode(lutInfo.color_mode);
      }
      set((current) => normalizeLutDrivenReliefState(current, updates));
      try {
        localStorage.setItem("lumina_lastLut", name);
      } catch {
        /* noop */
      }
      // 仅当 LUT 名称实际变化时获取颜色
      if (name && name !== state.lutColorsLutName) {
        _get().fetchLutColors(name);
      }
      if (name) {
        void apiFetchLutInfo(name)
          .then((info) => {
            const normalizedInfo = normalizeLutColorMode(info);
            const nextUpdates: Partial<ConverterState> = {
              selectedLutInfo: normalizedInfo,
            };
            if (normalizedInfo.color_mode) {
              nextUpdates.color_mode = normalizePublicColorMode(
                normalizedInfo.color_mode,
              );
            }
            if (
              normalizedInfo.supports_predictive_match ||
              normalizedInfo.supports_dynamic_layer_count
            ) {
              if (
                Array.isArray(normalizedInfo.supported_modes) &&
                normalizedInfo.supported_modes.length > 0
              ) {
                const preferredMode =
                  normalizedInfo.supported_modes.find(
                    (mode) => mode.color_layers === 5,
                  ) ??
                  normalizedInfo.supported_modes.find(
                    (mode) =>
                      mode.color_layers === normalizedInfo.max_color_layers,
                  ) ??
                  normalizedInfo.supported_modes[0];
                nextUpdates.color_layers =
                  preferredMode.color_layers ??
                  normalizedInfo.max_color_layers ??
                  null;
                nextUpdates.layer_height_mm =
                  preferredMode.layer_height_mm ??
                  normalizedInfo.layer_height_mm ??
                  null;
              } else {
                nextUpdates.color_layers =
                  normalizedInfo.max_color_layers ?? null;
                nextUpdates.layer_height_mm =
                  normalizedInfo.layer_height_mm ?? null;
              }
            } else {
              nextUpdates.color_layers = null;
              nextUpdates.layer_height_mm = null;
            }
            set((current) =>
              normalizeLutDrivenReliefState(current, nextUpdates),
            );
          })
          .catch(() => {
            /* best effort */
          });
      }
    }),

    setLegacyLutNames: documentCommand((names: string[]) => {
      const state = _get();
      const normalized = normalizeLegacyLutNames(names, "");
      const primaryName = normalized[0] ?? "";
      // Re-selecting the same LUT is a no-op: skip the full preview reset so
      // clicking the current option doesn't clear the user's work for nothing.
      // 重选同一 LUT 为空操作：跳过整场预览重置，避免点当前项白清用户成果。
      const sameNames =
        normalized.length === (state.lut_names ?? []).length &&
        normalized.every((name, index) => name === state.lut_names?.[index]);
      if (sameNames && primaryName === state.lut_name) return;
      const lutInfo = primaryName
        ? state.lutListFull.find((l) => l.name === primaryName)
        : null;
      const lutLocation = lutInfo
        ? findLutLocationByPath(
            buildLutCatalogIndex(state.legacyCatalogGroups),
            lutInfo.path,
          )
        : null;
      const updates: Partial<ConverterState> = {
        source_version: "legacy",
        lut_name: primaryName,
        lut_names: normalized,
        selectedLutInfo: null,
        selectedNativeBrandKey: "",
        selectedNativeDbNames: [],
        color_layers: null,
        layer_height_mm: null,
        model_enable: false,
        model_only: false,
        model_threshold: null,
        model_margin: null,
        ...buildPreviewSessionResetState(state, true),
      };
      if (lutLocation) {
        updates.selectedLegacyManufacturer = lutLocation.manufacturer;
      }
      if (lutInfo?.color_mode) {
        updates.color_mode = normalizePublicColorMode(lutInfo.color_mode);
      }
      set((current) => normalizeLutDrivenReliefState(current, updates));
      try {
        if (primaryName) {
          localStorage.setItem("lumina_lastLut", primaryName);
        } else {
          localStorage.removeItem("lumina_lastLut");
        }
      } catch {
        /* noop */
      }
      if (primaryName && primaryName !== state.lutColorsLutName) {
        _get().fetchLutColors(primaryName);
      }
      if (primaryName) {
        void apiFetchLutInfo(primaryName)
          .then((info) => {
            const current = _get();
            if (
              current.lut_name !== primaryName ||
              !areStringArraysEqual(
                normalizeLegacyLutNames(current.lut_names, current.lut_name),
                normalized,
              )
            ) {
              return;
            }
            const normalizedInfo = normalizeLutColorMode(info);
            const nextUpdates: Partial<ConverterState> = {
              selectedLutInfo: normalizedInfo,
            };
            if (normalizedInfo.color_mode) {
              nextUpdates.color_mode = normalizePublicColorMode(
                normalizedInfo.color_mode,
              );
            }
            if (
              normalizedInfo.supports_predictive_match ||
              normalizedInfo.supports_dynamic_layer_count
            ) {
              const preferredMode =
                normalizedInfo.supported_modes?.find(
                  (mode) => mode.color_layers === 5,
                ) ??
                normalizedInfo.supported_modes?.find(
                  (mode) =>
                    mode.color_layers === normalizedInfo.max_color_layers,
                ) ??
                normalizedInfo.supported_modes?.[0];
              nextUpdates.color_layers =
                preferredMode?.color_layers ??
                normalizedInfo.max_color_layers ??
                null;
              nextUpdates.layer_height_mm =
                preferredMode?.layer_height_mm ??
                normalizedInfo.layer_height_mm ??
                null;
            }
            set((current) =>
              normalizeLutDrivenReliefState(current, nextUpdates),
            );
          })
          .catch(() => {
            /* best effort */
          });
      }
    }),

    setLegacyManufacturer: (name: string) => {
      // Browsing the catalog must not change the applied LUTs or preview.
      set({
        selectedLegacyManufacturer: name,
      });
    },

    setSourceVersion: documentCommand((version: SourceVersion) =>
      set((state) => {
        if (version === state.source_version) {
          return {};
        }

        if (version === "legacy") {
          return {
            source_version: "legacy",
            color_layers: null,
            layer_height_mm: null,
            selectedNativeBrandKey: "",
            selectedNativeDbNames: [],
            model_enable: false,
            model_only: false,
            model_threshold: null,
            model_margin: null,
            ...buildPreviewSessionResetState(state, true),
          };
        }

        if (version === "material") {
          return {
            source_version: "material",
            hue_enable: state.materialDynamicLayerCountEnabled
              ? false
              : state.hue_enable,
            model_enable: false,
            model_only: false,
            model_threshold: null,
            model_margin: null,
            ...buildPreviewSessionResetState(state, true),
          };
        }

        const selection = resolveNativeBrandSelection(state);
        const selectedBrand =
          selection.brand ?? state.nativeBrandGroups[0] ?? null;
        const preferredMode = selectedBrand
          ? resolveNativeSupportedModeForBrand(
              selectedBrand,
              state.color_layers,
              state.layer_height_mm,
            )
          : null;
        return {
          source_version: "native",
          selectedNativeBrandKey: selectedBrand?.brand_key ?? "",
          selectedNativeDbNames: getNativeDbNamesForGroup(selectedBrand),
          color_layers: preferredMode?.color_layers ?? null,
          layer_height_mm: preferredMode?.layer_height_mm ?? null,
          ...buildNativeModelState(selectedBrand, state),
          ...buildPreviewSessionResetState(state, true),
        };
      })),

    setSelectedMaterialDirNames: documentCommand((names: string[]) => {
      const state = _get();
      const currentBacking = state.materialBackingMaterialDirName;
      const nextBacking =
        currentBacking && names.includes(currentBacking)
          ? currentBacking
          : inferDefaultMaterialBackingDirName(names);
      const selectionUnchanged =
        names.length === state.selectedMaterialDirNames.length &&
        names.every(
          (name, index) => name === state.selectedMaterialDirNames[index],
        );
      if (selectionUnchanged && nextBacking === currentBacking) {
        return;
      }

      persistSelectedMaterialDirNames(names);
      persistMaterialBackingMaterialDirName(nextBacking);
      set({
        selectedMaterialDirNames: names,
        materialBackingMaterialDirName: nextBacking,
        ..._cancelMaterialSuggestionWork(),
        ...buildPreviewSessionResetState(state, true),
      });
    }),
    setMaterialLayerCount: documentCommand((count: number) => {
      const materialSuggestionReset = _cancelMaterialSuggestionWork();
      set((state) => {
        const materialLayerCount = clampValue(Math.round(count), 1, 20);
        return {
          materialLayerCount,
          ...materialSuggestionReset,
          heightmap_max_height: state.enable_relief
            ? clampValue(
                state.heightmap_max_height,
                getMaterialArchiveReliefMinimumExtraHeight({
                  ...state,
                  materialLayerCount,
                }),
                RELIEF_MAX_EXTRA_HEIGHT_MM,
              )
            : state.heightmap_max_height,
          ...buildPreviewSessionResetState(state, true),
        };
      });
    }),
    setMaterialDynamicLayerCountEnabled: documentCommand((enabled: boolean) => {
      _cancelPreviewWork();
      const materialSuggestionReset = _cancelMaterialSuggestionWork();
      set((state) => ({
        materialDynamicLayerCountEnabled: enabled,
        ...materialSuggestionReset,
        hue_enable: enabled ? false : state.hue_enable,
        heightmap_max_height:
          enabled && state.enable_relief
            ? clampValue(
                state.heightmap_max_height,
                getMaterialArchiveReliefMinimumExtraHeight({
                  ...state,
                  materialDynamicLayerCountEnabled: true,
                }),
                RELIEF_MAX_EXTRA_HEIGHT_MM,
              )
            : state.heightmap_max_height,
        ...buildPreviewSessionResetState(state, true),
      }));
    }),
    setMaterialMinLayerCount: documentCommand((count: number) => {
      _cancelPreviewWork();
      const materialSuggestionReset = _cancelMaterialSuggestionWork();
      set((state) => {
        const materialMinLayerCount = normalizeDynamicMaterialLayerCount(
          count,
          state.materialMinLayerCount,
        );
        const materialMaxLayerCount = Math.max(
          normalizeDynamicMaterialLayerCount(
            state.materialMaxLayerCount,
            MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
          ),
          materialMinLayerCount,
        );
        return {
          materialMinLayerCount,
          materialMaxLayerCount,
          ...materialSuggestionReset,
          heightmap_max_height: state.enable_relief
            ? clampValue(
                state.heightmap_max_height,
                getMaterialArchiveReliefMinimumExtraHeight({
                  ...state,
                  materialMaxLayerCount,
                }),
                RELIEF_MAX_EXTRA_HEIGHT_MM,
              )
            : state.heightmap_max_height,
          ...buildPreviewSessionResetState(state, true),
        };
      });
    }),
    setMaterialMaxLayerCount: documentCommand((count: number) => {
      _cancelPreviewWork();
      const materialSuggestionReset = _cancelMaterialSuggestionWork();
      set((state) => {
        const materialMaxLayerCount = normalizeDynamicMaterialLayerCount(
          count,
          state.materialMaxLayerCount,
        );
        const materialMinLayerCount = Math.min(
          normalizeDynamicMaterialLayerCount(
            state.materialMinLayerCount,
            MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
          ),
          materialMaxLayerCount,
        );
        return {
          materialMinLayerCount,
          materialMaxLayerCount,
          ...materialSuggestionReset,
          heightmap_max_height: state.enable_relief
            ? clampValue(
                state.heightmap_max_height,
                getMaterialArchiveReliefMinimumExtraHeight({
                  ...state,
                  materialMaxLayerCount,
                }),
                RELIEF_MAX_EXTRA_HEIGHT_MM,
              )
            : state.heightmap_max_height,
          ...buildPreviewSessionResetState(state, true),
        };
      });
    }),
    setMaterialLayerHeightMm: documentCommand((height: number) => {
      const materialSuggestionReset = _cancelMaterialSuggestionWork();
      set((state) => ({
        materialLayerHeightMm: height,
        ...materialSuggestionReset,
        ...buildPreviewSessionResetState(state, true),
      }));
    }),
    setMaterialBackingMaterialDirName: documentCommand((name: string | null) => {
      persistMaterialBackingMaterialDirName(name);
      if (isDynamicMaterialActive(_get())) {
        set({
          materialBackingMaterialDirName: name,
          ...buildPreviewSessionResetState(_get(), true),
        });
        return;
      }
      set({
        materialBackingMaterialDirName: name,
        modelUrl: null,
        threemfDiskPath: null,
        downloadUrl: null,
      });
    }),

    setNativeBrandKey: documentCommand((brandKey: string) =>
      set((state) => {
        const selectedBrand = getNativeBrandGroupByKey(
          state.nativeBrandGroups,
          brandKey,
        );
        if (!selectedBrand) {
          return {
            selectedNativeBrandKey: brandKey,
            selectedNativeDbNames: [],
            color_layers: null,
            layer_height_mm: null,
            ...buildNativeModelDefaults(null),
            ...buildPreviewSessionResetState(state, true),
          };
        }

        const preferredMode = resolveNativeSupportedModeForBrand(
          selectedBrand,
          state.color_layers,
          state.layer_height_mm,
        );
        return {
          source_version: "native",
          selectedNativeBrandKey: selectedBrand.brand_key,
          selectedNativeDbNames: getNativeDbNamesForGroup(selectedBrand),
          color_layers: preferredMode?.color_layers ?? null,
          layer_height_mm: preferredMode?.layer_height_mm ?? null,
          ...buildNativeModelState(selectedBrand, state),
          ...buildPreviewSessionResetState(state, true),
        };
      })),

    setNativeSupportedMode: documentCommand((mode: {
      color_layers: number;
      layer_height_mm: number;
    }) =>
      set((state) => {
        const brand = getSelectedNativeBrandGroup(state);
        if (!brand) {
          return {
            source_version: "native",
            color_layers: mode.color_layers,
            layer_height_mm: mode.layer_height_mm,
            ...buildPreviewSessionResetState(state, true),
          };
        }
        const supported = getSupportedModeByPair(
          brand.supported_modes ?? [],
          mode.color_layers,
          mode.layer_height_mm,
        );
        if (!supported) {
          const preferred = resolveNativeSupportedModeForBrand(
            brand,
            mode.color_layers,
            mode.layer_height_mm,
          );
          return {
            source_version: "native",
            color_layers: preferred?.color_layers ?? null,
            layer_height_mm: preferred?.layer_height_mm ?? null,
            ...buildPreviewSessionResetState(state, true),
          };
        }
        return {
          source_version: "native",
          color_layers: supported.color_layers,
          layer_height_mm: supported.layer_height_mm,
          ...buildPreviewSessionResetState(state, true),
        };
      })),

    setNativeDbNames: documentCommand((dbNames: string[]) =>
      set((state) => {
        const selectedBrand = getSelectedNativeBrandGroup(state);
        const allowed = selectedBrand
          ? new Set(getNativeDbOptionNames(selectedBrand))
          : null;
        const normalized = normalizeStringArray(
          dbNames.filter((dbName) => (allowed ? allowed.has(dbName) : true)),
        );
        return {
          source_version: "native",
          selectedNativeDbNames: normalized,
          ...buildPreviewSessionResetState(state, true),
        };
      })),

    setTargetWidthMm: documentCommand((width: number) =>
      set((state) => {
        const limits = getTargetDimensionLimits(state, useSettingsStore.getState().printerModel);
        const safeWidth = Number.isFinite(width) ? width : 10;
        const clamped = state.largeFormatEnabled
          ? Math.max(10, safeWidth)
          : clampValue(safeWidth, 10, limits.width);
        const dimensions = state.aspectRatio
          ? {
              target_width_mm: clamped,
              target_height_mm: state.largeFormatEnabled
                ? Math.max(10, Math.round(clamped / state.aspectRatio))
                : clampValue(Math.round(clamped / state.aspectRatio), 10, limits.height),
            }
          : { target_width_mm: clamped };
        const fridgeMagnets = state.fridge_magnets.length > 0
          ? canonicalizeFridgeMagnets(
              getFallbackModelBounds({ ...state, ...dimensions }),
              state.fridge_magnets,
            )
          : state.fridge_magnets;
        return {
          preferredSizeAxis: "width",
          ...buildSvgHoleCompensationResizeState(state, dimensions),
          ...dimensions,
          fridge_magnets: fridgeMagnets,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      })),

    setTargetHeightMm: documentCommand((height: number) =>
      set((state) => {
        const limits = getTargetDimensionLimits(state, useSettingsStore.getState().printerModel);
        const safeHeight = Number.isFinite(height) ? height : 10;
        const clamped = state.largeFormatEnabled
          ? Math.max(10, safeHeight)
          : clampValue(safeHeight, 10, limits.height);
        const dimensions = state.aspectRatio
          ? {
              target_height_mm: clamped,
              target_width_mm: state.largeFormatEnabled
                ? Math.max(10, Math.round(clamped * state.aspectRatio))
                : clampValue(Math.round(clamped * state.aspectRatio), 10, limits.width),
            }
          : { target_height_mm: clamped };
        return {
          preferredSizeAxis: "height",
          ...buildSvgHoleCompensationResizeState(state, dimensions),
          ...dimensions,
          fridge_magnets:
            state.fridge_magnets.length > 0
              ? canonicalizeFridgeMagnets(
                  getFallbackModelBounds({ ...state, ...dimensions }),
                  state.fridge_magnets,
                )
              : state.fridge_magnets,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      })),

    setSpacerThick: documentCommand((thick: number) =>
      set((state) => {
        const fridgeState = buildFridgeMagnetState(state, {
          base_spacer_thick: clampValue(thick, 0.2, 10),
        });
        return {
          ...fridgeState,
          heightmap_max_height: state.enable_relief
            ? clampValue(
                state.heightmap_max_height,
                getMaterialArchiveReliefMinimumExtraHeight({
                  ...state,
                  spacer_thick: fridgeState.spacer_thick,
                }),
                RELIEF_MAX_EXTRA_HEIGHT_MM,
              )
            : state.heightmap_max_height,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      })),

    setBackingInfillDensityPercent: documentCommand((density: number) => {
      const normalized = normalizeBackingInfillDensityPercent(density);
      persistBackingInfillDensityPercent(normalized);
      set({
        backing_infill_density_percent: normalized,
        threemfDiskPath: null,
        downloadUrl: null,
      });
    }),

    setStructureMode: documentCommand((mode: StructureMode) =>
      set((state) => {
        // Automatic single-sided constraints must not replace the user's choice.
        if (
          !state.enable_fridge_magnet &&
          !state.modelSurfaceEnabled &&
          !state.enable_relief &&
          state.color_mode !== ColorModeEnum.FIVE_COLOR_EXT
        ) {
          try {
            localStorage.setItem(STRUCTURE_MODE_STORAGE_KEY, mode);
          } catch {
            // Keep the current selection usable even if it cannot be saved.
          }
        }
        return {
          structure_mode:
            (state.enable_fridge_magnet ||
              state.modelSurfaceEnabled ||
              (state.enable_relief &&
                state.modeling_mode === ModelingModeEnum.VECTOR)) &&
            mode !== StructureModeEnum.SINGLE_SIDED
              ? StructureModeEnum.SINGLE_SIDED
              : mode,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      })),
    setColorMode: documentCommand((mode: ColorMode) =>
      set((state) => ({
        color_mode: mode,
        enable_relief:
          state.modeling_mode === ModelingModeEnum.VECTOR &&
          mode === ColorModeEnum.FIVE_COLOR_EXT
            ? false
            : state.enable_relief,
        threemfDiskPath: null,
        downloadUrl: null,
      }))),
    setModelingMode: documentCommand((mode: ModelingMode) => {
      const state = _get();
      if (mode === ModelingModeEnum.VECTOR && !hasOnlySvgInputs(state)) {
        return;
      }
      const restoredBatchSvgSettings = state.batchMode &&
        mode === ModelingModeEnum.VECTOR && state.modeling_mode !== mode
        ? buildSvgHoleCompensationChangeState(
            { ...state, modeling_mode: mode },
            loadSvgHoleCompensationSettings(),
          )
        : {};
      set({
        ...restoredBatchSvgSettings,
        modeling_mode: mode,
        enable_relief:
          mode === ModelingModeEnum.VECTOR &&
          (state.color_mode === ColorModeEnum.FIVE_COLOR_EXT ||
            state.structure_mode !== StructureModeEnum.SINGLE_SIDED)
            ? false
            : state.enable_relief,
        threemfDiskPath: null,
        downloadUrl: null,
      });
    }),
    setColorLayers: documentCommand((layers: number | null) =>
      set({
        color_layers:
          layers == null ? null : clampValue(Math.round(layers), 1, 20),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setLayerHeightMm: documentCommand((height: number | null) =>
      set({
        layer_height_mm: height == null ? null : clampValue(height, 0.04, 0.2),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setModelEnable: documentCommand((enabled: boolean) =>
      set({
        model_enable: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setModelOnly: documentCommand((enabled: boolean) =>
      set({
        model_only: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setModelThreshold: documentCommand((value: number | null) =>
      set({
        model_threshold: value == null ? null : Number(value),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setModelMargin: documentCommand((value: number | null) =>
      set({
        model_margin: value == null ? null : Number(value),
        threemfDiskPath: null,
        downloadUrl: null,
      })),

    // --- 高级设置 ---
    setQuantizeColors: documentCommand((colors: number) => {
      const state = _get();
      const upperBound = state.quantize_colors_unlocked ? 8192 : 256;
      set({
        quantize_colors: clampValue(colors, 8, upperBound),
        threemfDiskPath: null,
        downloadUrl: null,
      });
    }),
    setQuantizeColorsUnlocked: documentCommand((unlocked: boolean) => {
      const state = _get();
      const upperBound = unlocked ? 8192 : 256;
      set({
        quantize_colors_unlocked: unlocked,
        quantize_colors: clampValue(state.quantize_colors, 8, upperBound),
        threemfDiskPath: null,
        downloadUrl: null,
      });
    }),
    setHighPrecision3dPreview: documentCommand((enabled: boolean) =>
      set({
        high_precision_3d_preview: enabled,
        previewGlbUrl: null,
        modelUrl: null,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setEnableCleanup: documentCommand((enabled: boolean) =>
      set({
        enable_cleanup: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setSvgHoleCompensationEnabled: documentCommand((enabled: boolean) => {
      const current = _get();
      if (enabled === current.svg_hole_compensation_enabled) return;
      set(buildSvgHoleCompensationChangeState(current, { svg_hole_compensation_enabled: enabled }));
    }),
    setSvgHoleMaxAreaMm2: documentCommand((area: number) => {
      const current = _get();
      if (!Number.isFinite(area) || area < 0 || area === current.svg_hole_max_area_mm2) return;
      set(buildSvgHoleCompensationChangeState(current, { svg_hole_max_area_mm2: area }));
    }),
    setSvgHoleMaxWidthMm: documentCommand((width: number) => {
      const current = _get();
      if (!Number.isFinite(width) || width < 0 || width === current.svg_hole_max_width_mm) return;
      set(buildSvgHoleCompensationChangeState(current, { svg_hole_max_width_mm: width }));
    }),
    setHueEnable: documentCommand((enabled: boolean) =>
      set((state) => ({
        hue_enable:
          enabled && isDynamicMaterialActive(state) ? false : enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }))),
    setUseLutConstrained: documentCommand((enabled: boolean) =>
      set({ use_lut_constrained: enabled })),
    setAutoDynamicRange: documentCommand((enabled: boolean) =>
      set({
        auto_dynamic_range: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setChromaGate: documentCommand((gate: number) =>
      set({
        chroma_gate: clampValue(gate, 0, 50),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setSeparateBacking: documentCommand((enabled: boolean) =>
      set({ separate_backing: enabled })),
    setBackingOutput: documentCommand((backingOutput) => {
      invalidateGeneratedArtifacts({ preservePreviews: true });
      set({ backingOutput, threemfDiskPath: null, downloadUrl: null });
    }),

    // --- 鎸備欢鐜?---
    setAddLoop: documentCommand((enabled: boolean) =>
      set((state) => ({
        add_loop:
          enabled && (state.puzzleEnabled || state.enable_fridge_magnet)
            ? false
            : enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      }))),
    setLoopWidth: documentCommand((width: number) =>
      set({ loop_width: clampValue(width, 2, 10) })),
    setLoopLength: documentCommand((length: number) =>
      set({ loop_length: clampValue(length, 4, 15) })),
    setLoopHole: documentCommand((hole: number) => set({ loop_hole: clampValue(hole, 1, 5) })),
    setLoopAngle: documentCommand((angle: number) =>
      set({ loop_angle: clampValue(angle, -180, 180) })),
    setLoopOffsetX: documentCommand((x: number) =>
      set((state) => {
        const offset = clampValue(x, -200, 200);
        return Object.is(state.loop_offset_x, offset) ? state : { loop_offset_x: offset };
      })),
    setLoopOffsetY: documentCommand((y: number) =>
      set((state) => {
        const offset = clampValue(y, -200, 200);
        return Object.is(state.loop_offset_y, offset) ? state : { loop_offset_y: offset };
      })),
    setLoopOffsets: documentCommand((x: number, y: number) =>
      set((state) => {
        const offsetX = clampValue(x, -200, 200);
        const offsetY = clampValue(y, -200, 200);
        return Object.is(state.loop_offset_x, offsetX) && Object.is(state.loop_offset_y, offsetY)
          ? state
          : { loop_offset_x: offsetX, loop_offset_y: offsetY };
      })),
    setLoopPositionPreset: documentCommand((preset: string) => {
      set({ loop_position_preset: preset });
    }),

    setEnableFridgeMagnet: documentCommand((enabled: boolean) =>
      set((state) => {
        const shouldSeedDefaults =
          enabled &&
          !state.enable_fridge_magnet &&
          state.fridge_magnets.length === 0;
        const fridgeMagnets = shouldSeedDefaults
          ? buildDefaultFridgeMagnetLayout(state)
          : state.fridge_magnets;

        return {
          ...buildFridgeMagnetState(state, {
            enable_fridge_magnet: enabled,
            fridge_magnets: fridgeMagnets,
          }),
          structure_mode: enabled
            ? StructureModeEnum.SINGLE_SIDED
            : state.structure_mode,
          largeFormatEnabled: enabled ? false : state.largeFormatEnabled,
          puzzleEnabled: enabled ? false : state.puzzleEnabled,
          add_loop: enabled ? false : state.add_loop,
          selectedFridgeMagnetId: enabled ? state.selectedFridgeMagnetId : null,
          ...DEFAULT_PUZZLE_PREVIEW_STATE,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      })),

    resetFridgeMagnetLayout: documentCommand(() =>
      set((state) => ({
        ...buildFridgeMagnetState(state, {
          fridge_magnets: autoLayoutFridgeMagnets(
            getFallbackModelBounds(state),
            state.fridge_magnets,
          ),
        }),
        selectedFridgeMagnetId: null,
        threemfDiskPath: null,
        downloadUrl: null,
      }))),

    addFridgeMagnet: documentCommand(() =>
      set((state) => {
        const nextFridgeMagnets = autoLayoutFridgeMagnets(
          getFallbackModelBounds(state),
          [
            ...state.fridge_magnets,
            createFridgeMagnetFromPreset(
              createNextFridgeMagnetId(state.fridge_magnets),
              getDefaultFridgeMagnetPresetKey("round"),
              0,
              0,
            ),
          ],
        );

        return {
          ...buildFridgeMagnetState(state, {
            fridge_magnets: nextFridgeMagnets,
          }),
          selectedFridgeMagnetId:
            nextFridgeMagnets[nextFridgeMagnets.length - 1].id,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      })),

    removeFridgeMagnet: documentCommand((id: string) =>
      set((state) => {
        const nextFridgeMagnets = state.fridge_magnets.filter(
          (item) => item.id !== id,
        );

        return {
          ...buildFridgeMagnetState(state, {
            fridge_magnets: nextFridgeMagnets,
          }),
          selectedFridgeMagnetId:
            state.selectedFridgeMagnetId === id
              ? null
              : state.selectedFridgeMagnetId,
          threemfDiskPath: null,
          downloadUrl: null,
        };
      })),

    updateFridgeMagnet: documentCommand((
      id: string,
      updates: Partial<Omit<FridgeMagnetItem, "id">>,
    ) =>
      set((state) => {
        const nextFridgeMagnets = state.fridge_magnets.map((item) =>
          item.id === id
            ? normalizeFridgeMagnetItem({
                ...item,
                ...updates,
                diameter_mm: sanitizeOptionalFiniteNumber(
                  updates.diameter_mm,
                  item.diameter_mm,
                ),
                width_mm: sanitizeOptionalFiniteNumber(
                  updates.width_mm,
                  item.width_mm,
                ),
                height_mm: sanitizeOptionalFiniteNumber(
                  updates.height_mm,
                  item.height_mm,
                ),
                thickness_mm:
                  updates.thickness_mm == null
                    ? item.thickness_mm
                    : sanitizeFiniteNumber(
                        updates.thickness_mm,
                        item.thickness_mm,
                      ),
                center_x_mm:
                  updates.center_x_mm == null
                    ? item.center_x_mm
                    : sanitizeFiniteNumber(
                        updates.center_x_mm,
                        item.center_x_mm,
                      ),
                center_y_mm:
                  updates.center_y_mm == null
                    ? item.center_y_mm
                    : sanitizeFiniteNumber(
                        updates.center_y_mm,
                        item.center_y_mm,
                      ),
              })
            : item,
        );

        return {
          ...buildFridgeMagnetState(state, {
            fridge_magnets: nextFridgeMagnets,
          }),
          threemfDiskPath: null,
          downloadUrl: null,
        };
      })),

    updateFridgeMagnetCenter: documentCommand((id: string, centerX: number, centerY: number) =>
      set((state) => {
        const nextFridgeMagnets = state.fridge_magnets.map((item) =>
          item.id === id
            ? {
                ...item,
                center_x_mm: sanitizeFiniteNumber(centerX, item.center_x_mm),
                center_y_mm: sanitizeFiniteNumber(centerY, item.center_y_mm),
              }
            : item,
        );

        return {
          ...buildFridgeMagnetState(state, {
            fridge_magnets: nextFridgeMagnets,
          }),
          threemfDiskPath: null,
          downloadUrl: null,
        };
      })),

    selectFridgeMagnet: (id: string | null) =>
      set({ selectedFridgeMagnetId: id }),

    clearSelectedFridgeMagnet: () => set({ selectedFridgeMagnetId: null }),

    // --- 浮雕（互斥） ---
    setEnableRelief: documentCommand((enabled: boolean) => {
      set((state) => {
        if (
          enabled &&
          state.modeling_mode === ModelingModeEnum.VECTOR &&
          (state.color_mode === ColorModeEnum.FIVE_COLOR_EXT ||
            state.structure_mode !== StructureModeEnum.SINGLE_SIDED)
        ) {
          return state;
        }
        const minimumReliefExtraHeight = getMaterialArchiveReliefMinimumExtraHeight(state);
        const reliefMaxHeight = enabled
          ? clampValue(
              state.heightmap_max_height,
              minimumReliefExtraHeight,
              RELIEF_MAX_EXTRA_HEIGHT_MM,
            )
          : state.heightmap_max_height;
        const updates: Partial<ConverterState> = {
          enable_relief: enabled,
          backing_infill_density_percent: enabled
            ? BACKING_INFILL_DENSITY_DEFAULT_PERCENT
            : state.modelSurfaceEnabled ? BACKING_INFILL_DENSITY_DEFAULT_PERCENT : loadBackingInfillDensityPercent(),
          enable_cloisonne: enabled ? false : state.enable_cloisonne,
          // Relief only supports single-sided structure
          structure_mode: enabled
            ? StructureModeEnum.SINGLE_SIDED
            : state.structure_mode,
          heightmap_max_height: reliefMaxHeight,
          threemfDiskPath: null,
          downloadUrl: null,
        };
        // Requirement 6.5: When switching enable_relief from false to true,
        // auto-initialize color_height_map ONLY if it is currently empty.
        // Use computeAutoHeightMap to assign different heights based on
        // luminance, so the relief effect is visible immediately.
        if (
          enabled &&
          !state.enable_relief &&
          state.palette.length > 0 &&
          Object.keys(state.color_height_map).length === 0
        ) {
          const mode =
            state.autoHeightMode === "use-heightmap"
              ? "darker-higher"
              : (state.autoHeightMode as "darker-higher" | "lighter-higher");
          updates.color_height_map = computeAutoHeightMap(
            state.palette,
            mode,
            reliefMaxHeight,
          );
        }
        return updates;
      });
    }),
    setColorHeightMap: documentCommand((map: Record<string, number>) =>
      set({ color_height_map: map })),
    setHeightmapMaxHeight: documentCommand((height: number) => {
      const state = _get();
      const minimumReliefExtraHeight = getMaterialArchiveReliefMinimumExtraHeight(state);
      const newMax = clampValue(
        height,
        minimumReliefExtraHeight,
        RELIEF_MAX_EXTRA_HEIGHT_MM,
      );
      const oldMax = state.heightmap_max_height;
      // Proportionally rescale all existing color heights
      if (oldMax > 0 && Object.keys(state.color_height_map).length > 0) {
        const ratio = newMax / oldMax;
        const scaled: Record<string, number> = {};
        for (const [hex, h] of Object.entries(state.color_height_map)) {
          scaled[hex] = clampValue(h * ratio, minimumReliefExtraHeight, newMax);
        }
        set({ heightmap_max_height: newMax, color_height_map: scaled });
      } else {
        set({ heightmap_max_height: newMax });
      }
    }),

    // --- 描边 ---
    setEnableOutline: documentCommand((enabled: boolean) =>
      set({
        enable_outline: enabled,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setOutlineWidth: documentCommand((width: number) =>
      set({ outline_width: clampValue(width, 0.5, 10.0) })),

    // --- 掐丝珐琅（互斥） ---
    setEnableCloisonne: documentCommand((enabled: boolean) =>
      set((state) => ({
        enable_cloisonne: enabled,
        enable_relief: enabled ? false : state.enable_relief,
        threemfDiskPath: null,
        downloadUrl: null,
      }))),
    setWireWidthMm: documentCommand((width: number) =>
      set({ wire_width_mm: clampValue(width, 0.2, 1.2) })),
    setWireHeightMm: documentCommand((height: number) =>
      set({ wire_height_mm: clampValue(height, 0.04, 1.0) })),

    // --- 涂层 ---
    setEnableCoating: documentCommand((enabled: boolean) => {
      invalidateGeneratedArtifacts({ preservePreviews: true });
      set({
        enable_coating: enabled,
        nativeMaterialSelection: null,
        nativeMaterialSelectionError: null,
        threemfDiskPath: null,
        downloadUrl: null,
      });
    }),
    setCoatingHeightMm: documentCommand((height: number) => {
      invalidateGeneratedArtifacts({ preservePreviews: true });
      set({ coating_height_mm: clampValue(height, 0.04, 0.12),
        threemfDiskPath: null, downloadUrl: null });
    }),

    // --- 大画幅 ---
    setLargeFormatEnabled: documentCommand((enabled: boolean) =>
      set((state) => ({
        largeFormatEnabled:
          enabled && (state.puzzleEnabled || state.enable_fridge_magnet)
            ? false
            : enabled,
        largeFormatWarnings: [],
        largeFormatFailedTiles: [],
        threemfDiskPath: null,
        downloadUrl: null,
      }))),
    setTileWidthMm: documentCommand((width: number) =>
      set({
        tileWidthMm: Math.max(50, Number.isFinite(width) ? width : 50),
        largeFormatWarnings: [],
        largeFormatFailedTiles: [],
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setTileHeightMm: documentCommand((height: number) =>
      set({
        tileHeightMm: Math.max(50, Number.isFinite(height) ? height : 50),
        largeFormatWarnings: [],
        largeFormatFailedTiles: [],
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    // View-only toggle: does not change generated output, so keep downloads.
    setLargeFormatTileOverlayVisible: (visible: boolean) =>
      set({ largeFormatTileOverlayVisible: visible }),

    setPuzzleEnabled: documentCommand((enabled: boolean) =>
      set((state) => {
        const puzzleEnabled = enabled && !state.batchMode;
        return {
          puzzleEnabled,
          largeFormatEnabled: enabled ? false : state.largeFormatEnabled,
          largeFormatWarnings: [],
          largeFormatFailedTiles: [],
          add_loop: enabled ? false : state.add_loop,
          ...buildFridgeMagnetState(state, {
            enable_fridge_magnet: enabled ? false : state.enable_fridge_magnet,
          }),
          selectedFridgeMagnetId: enabled
            ? null
            : state.selectedFridgeMagnetId,
          ...(!enabled ? DEFAULT_PUZZLE_PREVIEW_STATE : {}),
          threemfDiskPath: null,
          downloadUrl: null,
        };
      })),
    setPuzzleStyle: documentCommand((style: PuzzleStyle) =>
      set({
        puzzleStyle: style,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setPuzzleSizingMode: documentCommand((mode: PuzzleSizingMode) =>
      set({
        puzzleSizingMode: mode,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setPieceWidthMm: documentCommand((width: number) =>
      set({
        pieceWidthMm: clampValue(width, 5, 200),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setPieceHeightMm: documentCommand((height: number) =>
      set({
        pieceHeightMm: clampValue(height, 5, 200),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setPuzzleRows: documentCommand((rows: number) =>
      set({
        puzzleRows: clampValue(Math.round(rows), 1, 200),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setPuzzleCols: documentCommand((cols: number) =>
      set({
        puzzleCols: clampValue(Math.round(cols), 1, 200),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setTargetPieceCount: documentCommand((count: number) =>
      set({
        targetPieceCount: clampValue(Math.round(count), 2, 2000),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setConnectorStyle: documentCommand((style: PuzzleConnectorStyle) =>
      set({
        connectorStyle: style,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setLabelsEnabled: documentCommand((enabled: boolean) =>
      set({
        labelsEnabled: enabled,
        engraveBackLabels: false,
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setEngraveBackLabels: documentCommand(() => {
      set({
        engraveBackLabels: false,
        threemfDiskPath: null,
        downloadUrl: null,
      });
    }),
    setIrregularityStrength: documentCommand((strength: number) =>
      set({
        irregularityStrength: clampValue(strength, 0, 1),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    setMinNeckWidthMm: documentCommand((width: number) =>
      set({
        minNeckWidthMm: clampValue(width, 0.2, 20),
        threemfDiskPath: null,
        downloadUrl: null,
      })),
    submitPuzzleLayoutPreview: async () => {
      const state = _get();
      if (!state.puzzleEnabled || !state.sessionId) {
        set({ ...DEFAULT_PUZZLE_PREVIEW_STATE });
        return false;
      }

      const requestedSessionId = state.sessionId;
      const requestedParams = buildPuzzlePreviewParams(state);
      const requestedSourceKey = buildPuzzlePreviewSourceKey(state);

      try {
        const response = await apiConvertPuzzleLayoutPreview(
          requestedSessionId,
          requestedParams,
        );
        const latestState = _get();
        const latestParams = buildPuzzlePreviewParams(latestState);
        const latestSourceKey = buildPuzzlePreviewSourceKey(latestState);
        if (
          latestState.sessionId !== requestedSessionId ||
          !latestState.puzzleEnabled ||
          JSON.stringify(latestParams) !== JSON.stringify(requestedParams) ||
          latestSourceKey !== requestedSourceKey
        ) {
          return false;
        }
        set({
          puzzleOverlayUrl:
            normalizeResourceUrl(response.overlay_url) ?? response.overlay_url,
          puzzleWarnings: response.warnings ?? [],
          puzzleResolvedRows: response.grid_rows,
          puzzleResolvedCols: response.grid_cols,
          puzzleResolvedPieceCount: response.piece_count,
          puzzleDerivedPieceWidthMm: response.derived_piece_width_mm,
          puzzleDerivedPieceHeightMm: response.derived_piece_height_mm,
          error: null,
        });
        return true;
      } catch (err) {
        const latestState = _get();
        const latestParams = buildPuzzlePreviewParams(latestState);
        const latestSourceKey = buildPuzzlePreviewSourceKey(latestState);
        if (
          latestState.sessionId !== requestedSessionId ||
          !latestState.puzzleEnabled ||
          JSON.stringify(latestParams) !== JSON.stringify(requestedParams) ||
          latestSourceKey !== requestedSourceKey
        ) {
          return false;
        }
        set({
          ...DEFAULT_PUZZLE_PREVIEW_STATE,
          error: visibleConverterError(err, "Puzzle preview failed"),
        });
        return false;
      }
    },
    clearPuzzleLayoutPreview: () =>
      set({
        ...DEFAULT_PUZZLE_PREVIEW_STATE,
      }),

    // --- 热床尺寸 ---
    setBedLabel: (label: string) => {
      set({ bed_label: label });
      const state = _get();
      if (!state.bedSizes.some((bed) => bed.label === label)) return;
      set(buildPrinterDimensionState(state));
    },

    // --- 调色板与选择 ---
    setSelectedColor: (hex: string | null) => set({ selectedColor: hex }),
    setPalette: (entries: PaletteEntry[]) => set({ palette: entries }),

    clearSelection: async () => {
      const state = _get();
      if (state.sessionId) {
        // Use the unified selection mutation to clear the server-authoritative
        // selection. This also works after custom recipe / gradient operations
        // that may have cleared legacy state but kept the selectionDocument.
        await _get().applySelectionMutation({ operation: "clear" });
        return;
      }
      markRegionSelectionCleared([
        state.regionData?.regionId,
        ...state.selectedRegions.map((region) => region.regionId),
      ]);
      const base = getPreviewBaseUrl(state);
      set({
        selectedColor: null,
        selectedColors: new Set<string>(),
        regionData: null,
        selectedRegions: [],
        selectionDocument: null,
        gradientSelection: null,
        pendingReplacement: null,
        previewImageUrl: base,
      });
    },

    // --- 选择工具与统一选区 ---
    setSelectionMode: (mode: SelectionMode) => {
      // Compatibility callers keep their legacy discriminant, while the new
      // toolbar uses selectionTool. Neither path mutates an authoritative
      // SelectionDocument; legacy state is cleared only when no document exists.
      const hasUnifiedSelection = Boolean(_get().selectionDocument);
      set({
        selectionMode: mode,
        selectionTool: selectionToolForLegacyMode(mode),
        ...(hasUnifiedSelection
          ? {}
          : {
              selectedColor: null,
              selectedColors: new Set<string>(),
              regionData: null,
              selectedRegions: [],
            }),
      });
    },

    setSelectionTool: (tool: SelectionTool) => {
      // Tool changes never mutate the shared selection or its draft.
      set({ selectionTool: tool, selectionMode: selectionModeForTool(tool) });
    },

    setBrushSizePx: (size: number) => {
      set({ brushSizePx: Math.max(1, Math.min(512, Math.round(size))) });
    },

    setColorRangeTolerance: (tolerance: number) => {
      const finite = Number.isFinite(tolerance) ? tolerance : DEFAULT_COLOR_RANGE_TOLERANCE;
      set({
        colorRangeTolerance: Math.max(
          0,
          Math.min(MAX_COLOR_RANGE_TOLERANCE, Math.round(finite * 10) / 10),
        ),
      });
    },

    hydrateSelectionDocument: async () => {
      const sessionId = _get().sessionId;
      if (!sessionId) return;
      const pending = waitForSelectionMutation(sessionId);
      if (pending) await pending;
      if (_get().sessionId !== sessionId) return;
      // A GET may already include a POST whose response is still in flight.
      // Publishing it with that gesture pending would visually toggle twice.
      // A gesture started during this GET will publish its own confirmation.
      await readConfirmedSelectionDocument(sessionId, () => waitForSelectionMutation(sessionId) === null);
    },

    applySelectionMutation: async (input) => {
      const initial = _get();
      if (!initial.sessionId) {
        set({ error: "请先预览图片" });
        return false;
      }
      const requestedSessionId = initial.sessionId;
      // A free-color operation may itself be waiting for an earlier selection.
      // Capture it now so later gestures keep their place after it without
      // making earlier gestures wait for a subsequently queued free-color edit.
      const pendingFreeColor = freeColorMutationQueues.get(requestedSessionId);
      const mutationId = ++nextSelectionMutationId;
      const result = queueSelectionMutation(requestedSessionId, mutationId, async (): Promise<boolean> => {
        if (pendingFreeColor) await pendingFreeColor;
        const pendingContentCommit = waitForContentCommits(requestedSessionId);
        if (pendingContentCommit) {
          const contentCommitSucceeded = await pendingContentCommit;
          if (_get().sessionId !== requestedSessionId || !contentCommitSucceeded) {
            return false;
          }
        }
        if (_get().sessionId !== requestedSessionId) return false;
        if (!_get().selectionDocument) await readConfirmedSelectionDocument(requestedSessionId);
        const state = _get();
        if (state.sessionId !== requestedSessionId) return false;
        const previousDocument = state.selectionDocument;
        // A restored editor can publish a newer document than the last local request.
        if (previousDocument) rememberConfirmedSelectionDocument(requestedSessionId, previousDocument);
        const confirmed = confirmedSelectionRevisions.get(requestedSessionId);
        const baseRevision =
          confirmed?.selectionRevision ?? state.selectionDocument?.selection_revision ?? 0;
        const contentRevision =
          confirmed?.contentRevision ?? state.selectionDocument?.content_revision ?? 0;
        try {
          const document = await apiMutateEditorSelection({
            session_id: requestedSessionId,
            operation: input.operation,
            base_selection_revision: baseRevision,
            content_revision: contentRevision,
            ...(input.x !== undefined ? { x: input.x } : {}),
            ...(input.y !== undefined ? { y: input.y } : {}),
            ...(input.colorHex ? { color_hex: input.colorHex } : {}),
            ...(input.colorHexes ? { color_hexes: input.colorHexes } : {}),
            ...(input.gradientGroupIndex !== undefined
              ? { gradient_group_index: input.gradientGroupIndex } : {}),
            ...(input.gradientRegionIndex !== undefined
              ? { gradient_region_index: input.gradientRegionIndex } : {}),
            ...(input.colorTolerance !== undefined
              ? { color_tolerance: input.colorTolerance }
              : {}),
            ...(input.brushRadius !== undefined
              ? { brush_radius: input.brushRadius }
              : {}),
            ...(input.brushPoints && input.brushPoints.length > 0
              ? { brush_points: input.brushPoints }
              : {}),
            ...(input.brushStrokes ? { brush_strokes: input.brushStrokes } : {}),
          });
          const current = _get();
          if (current.sessionId !== requestedSessionId) return false;
          if (!rememberConfirmedSelectionDocument(requestedSessionId, document)) {
            // A late response may be older in either selection or content
            // version. Do not repaint it over the current document or let a
            // dependent content edit consume an unknown base.
            // 晚到响应可能在选区或内容版本上更旧；不能覆盖当前文档，也不能
            // 让依赖内容编辑使用不确定的 base。
            void _get().hydrateSelectionDocument();
            return false;
          }
          // The document, union outline and history flags come from the same
          // confirmed operation. Pending gestures never invent server revisions.
          set({
            ...selectionUpdatesFromResponse(current, requestedSessionId, document),
            gradientSelection: input.selectionSource ?? null,
            selectedGradientRegions: [],
            pendingSelectionMutations: current.pendingSelectionMutations.filter((item) => item.id !== mutationId),
            ...(input.operation === "clear" ? { pendingReplacement: null } : {}),
          });
          return true;
        } catch (err) {
          if (_get().sessionId !== requestedSessionId) return false;
          // A failed response may still have committed. Read the server before
          // the next queued gesture; never replay a toggle to recover it.
          const confirmedSelection = confirmedSelectionRevisions.get(
            requestedSessionId,
          );
          const rollbackDocument =
            previousDocument &&
            confirmedSelection &&
            previousDocument.selection_revision <=
              confirmedSelection.selectionRevision &&
            previousDocument.content_revision === confirmedSelection.contentRevision
              ? previousDocument
              : null;
          const error = visibleConverterError(err, "Selection update failed");
          if (rollbackDocument) {
            set({
              ...selectionStateFromDocument(
                rollbackDocument,
                getPreviewBaseUrl(_get()) ?? "",
              ),
              error,
              pendingSelectionMutations: _get().pendingSelectionMutations.filter((item) => item.id !== mutationId),
            });
          } else {
            set({
              selectionDocument: null,
              selectedColor: null,
              selectedColors: new Set<string>(),
              selectedRegions: [],
              regionData: null,
              error,
              pendingSelectionMutations: _get().pendingSelectionMutations.filter((item) => item.id !== mutationId),
            });
          }
          await readConfirmedSelectionDocument(requestedSessionId, undefined, true);
          return false;
        }
      });
      // Reserve the queue before publishing the visual intent so a synchronous
      // subscriber's replacement/undo action also waits for this selection.
      set((state) => ({
        error: null,
        pendingSelectionMutations: [...state.pendingSelectionMutations, { id: mutationId, sessionId: requestedSessionId, input }],
      }));
      return result;
    },

    // --- Legacy colour-set compatibility ---
    removeColorFromSelection: (hex: string) => {
      const normalized = normalizeHexNoHash(hex);
      if (!normalized) return;
      const state = _get();
      if (state.sessionId) {
        void state.applySelectionMutation({ operation: "same-color-remove", colorHex: normalized });
        return;
      }
      const next = new Set(Array.from(state.selectedColors).filter(
        (color) => color.toLowerCase() !== normalized.toLowerCase(),
      ));
      set({ selectedColors: next, selectedColor: chooseLastSelectedColor(next), gradientSelection: null });
    },

    toggleColorInSelection: (hex: string) => {
      const normalized = normalizeHexNoHash(hex);
      if (!normalized) return;
      const current = _get();
      if (current.sessionId) {
        void current.applySelectionMutation({ operation: "same-color-toggle", colorHex: normalized });
        return;
      }
      const prev = _get().selectedColors;
      const next = toggleHexInSet(prev, normalized);
      // Any manual tweak to the multi-select set implies the user is no
      // longer inside a "gradient region"-scoped selection. Drop that stamp
      // so the palette tiles recover their normal selection rendering;
      // otherwise the palette would keep hiding selection borders even
      // after the user has diverged from the region's exact colour list.
      // 用户手动改动多选集合时，表示已从"区域选中"转为常规多选，清除
      // gradientSelection 让调色板恢复正常的选中态渲染。
      set({
        selectedColors: next,
        selectedColor: chooseLastSelectedColor(next),
        gradientSelection: null,
      });
    },

    // --- 批量颜色替换 ---
    applyBatchColorRemap: async (newHex: string) => {
      await commitColorRemap(_get, set, state => state.selectedColors.size
        ? buildCurrentVisibleColorRemapMap(state.colorRemapMap, [...state.selectedColors], newHex)
        : null, "批量颜色替换失败");
    },

    // --- Connected region detection: single region ---
    detectRegion: async (x: number, y: number) => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return;
      }
      const sessionIdAtRequest = state.sessionId;
      const regionIdAtRequest = state.regionData?.regionId ?? null;
      const mutationSeqAtRequest = getRegionSelectionMutationSeq();
      const requestSeq = beginSingleRegionDetectIntent(x, y);
      try {
        const response = await apiDetectRegion(sessionIdAtRequest, x, y);
        const currentState = _get();
        if (
          currentState.sessionId !== sessionIdAtRequest ||
          (currentState.selectionMode !== "current" &&
            currentState.selectionMode !== "region")
        ) {
          return;
        }
        if (hasNewerDifferentSingleRegionDetectIntent(requestSeq, x, y)) {
          return;
        }
        if (wasRegionRemovedAfterRequest(response.region_id, mutationSeqAtRequest)) {
          return;
        }
        const basePreviewUrl = getPreviewBaseUrl(currentState);
        const previewUrl =
          normalizeResourceUrl(response.preview_url) ?? basePreviewUrl ?? "";
        if (
          regionIdAtRequest === response.region_id &&
          currentState.regionData?.regionId === response.region_id
        ) {
          set({
            regionData: null,
            selectedColor: null,
            previewImageUrl: getPreviewBaseUrl(currentState),
          });
          markRegionSelectionCleared([response.region_id]);
          return;
        }
        set({
          regionData: {
            regionId: response.region_id,
            colorHex: response.color_hex,
            pixelCount: response.pixel_count,
            previewUrl,
            contours: resolveRegionContours(response.contours),
            bbox: resolveRegionBbox(response.bbox),
            clickX: x,
            clickY: y,
          },
          selectedColor: response.color_hex.replace(/^#/, ""),
          previewImageUrl: getPreviewBaseUrl(currentState),
        });
      } catch (err) {
        set({
          error: visibleConverterError(err, "Region detect failed"),
        });
      }
    },

    // --- Connected region detection: multi-select accumulation ---
    detectAndAccumulateRegion: async (x: number, y: number) => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return;
      }
      const sessionIdAtRequest = state.sessionId;
      const selectedRegionIdsAtRequest = new Set(
        state.selectedRegions.map((region) => region.regionId),
      );
      const mutationSeqAtRequest = getRegionSelectionMutationSeq();
      try {
        const response = await apiDetectRegion(sessionIdAtRequest, x, y);
        const currentState = _get();
        if (
          currentState.sessionId !== sessionIdAtRequest ||
          currentState.selectionMode !== "multi-select"
        ) {
          return;
        }
        const basePreviewUrl = getPreviewBaseUrl(currentState);
        const newRegion: RegionData = {
          regionId: response.region_id,
          colorHex: response.color_hex,
          pixelCount: response.pixel_count,
          previewUrl:
            normalizeResourceUrl(response.preview_url) ?? basePreviewUrl ?? "",
          contours: resolveRegionContours(response.contours),
          bbox: resolveRegionBbox(response.bbox),
          clickX: x,
          clickY: y,
        };
        const existing = _get().selectedRegions;
        const idx = existing.findIndex(
          (region) => region.regionId === newRegion.regionId,
        );
        if (idx >= 0) {
          if (selectedRegionIdsAtRequest.has(newRegion.regionId)) {
            const next = existing.filter((_, i) => i !== idx);
            const lastRegion = getLastSelectedRegion(next);
            markRegionRemoved(newRegion.regionId);
            set({
              selectedRegions: next,
              selectedColor: lastRegion
                ? lastRegion.colorHex.replace(/^#/, "")
                : null,
              previewImageUrl: getSelectedRegionPreviewUrl(
                next,
                getPreviewBaseUrl(currentState),
              ),
            });
          }
        } else if (
          !wasRegionRemovedAfterRequest(newRegion.regionId, mutationSeqAtRequest)
        ) {
          const next = [...existing, newRegion];
          set({
            selectedRegions: next,
            selectedColor: response.color_hex.replace(/^#/, ""),
            previewImageUrl: getSelectedRegionPreviewUrl(next, basePreviewUrl),
          });
        }
      } catch (err) {
        set({
          error: visibleConverterError(err, "Region detect failed"),
        });
      }
    },

    removeRegionFromSelection: (regionId: string) => {
      const state = _get();
      const document = state.selectionDocument;
      const componentIndex = document?.components.findIndex(
        (component) => component.region_id === regionId,
      ) ?? -1;
      if (document && componentIndex >= 0) {
        const component = document.components[componentIndex];
        markRegionRemoved(regionId);
        void _get().applySelectionMutation({
          operation: "point-remove",
          x: component.anchor[0],
          y: component.anchor[1],
        });
        return;
      }

      const next = state.selectedRegions.filter(
        (region) => region.regionId !== regionId,
      );
      if (next.length === state.selectedRegions.length) {
        return;
      }
      const lastRegion = getLastSelectedRegion(next);
      markRegionRemoved(regionId);
      set({
        selectedRegions: next,
        selectedColor: lastRegion ? lastRegion.colorHex.replace(/^#/, "") : null,
        previewImageUrl: getSelectedRegionPreviewUrl(next, getPreviewBaseUrl(state)),
      });
    },

    setSelectionBlinkEnabled: (enabled: boolean) => {
      set({ selectionBlinkEnabled: enabled });
    },

    toggleSelectionBlink: () => {
      set((state) => ({
        selectionBlinkEnabled: !state.selectionBlinkEnabled,
      }));
    },

    upsertRecipeOverrides: documentCommand((
      regionIds: string[],
      recipe: number[],
      layerOrder: string,
      virtualMaterials?: VirtualMaterial[],
    ) => {
      const validRegionIds = regionIds.filter((value) => !!value);
      if (validRegionIds.length === 0) {
        return;
      }
      const normalizedRecipe = recipe.map((value) =>
        Math.max(0, Math.round(value)),
      );
      // Deep-copy the virtuals so later mutations on either the caller's
      // list or the stored items don't bleed across overrides. Virtuals are
      // the part of the override payload that ``/generate`` relies on to
      // extend the worker palette; losing them collapses virtual-index
      // pixels back onto the LUT's native channels.
      // 对 virtuals 做深拷贝，避免外部改动污染 store。generate 端依赖它扩
      // 展 worker 调色板，丢了会让虚拟索引像素坍缩回 LUT 原生通道。
      const clonedVirtuals = (virtualMaterials ?? []).map((material) => ({
        name: material.name,
        hex: material.hex,
      }));
      set((state) => {
        const existing = state.recipe_overrides.filter(
          (item) => !validRegionIds.includes(item.region_id),
        );
        const next = [
          ...existing,
          ...validRegionIds.map((regionId) => ({
            region_id: regionId,
            recipe: normalizedRecipe,
            layer_order: layerOrder,
            ...(clonedVirtuals.length > 0
              ? {
                  virtual_materials: clonedVirtuals.map((material) => ({
                    ...material,
                  })),
                }
              : {}),
          })),
        ];
        return {
          recipe_overrides: next,
        };
      });
    }, { localEditor: true }),

    clearRecipeOverrides: documentCommand((regionIds?: string[]) => {
      if (!regionIds || regionIds.length === 0) {
        set({ recipe_overrides: [] });
        return;
      }
      set((state) => ({
        recipe_overrides: state.recipe_overrides.filter(
          (item) => !regionIds.includes(item.region_id),
        ),
      }));
    }, { localEditor: true }),

    pushCustomRecipeHistory: (item: RecipeHistoryItem) => {
      set((state) => {
        const filtered = state.customRecipeHistory.filter(
          (history) => history.id !== item.id,
        );
        const next = [item, ...filtered].slice(0, 10);
        return { customRecipeHistory: next };
      });
    },

    clearCustomRecipeHistory: () => {
      set({ customRecipeHistory: [] });
    },

    applyCustomRecipeFromHistory: async (
      historyId: string,
      regionIds: string[],
    ) => {
      const state = _get();
      const entry = state.customRecipeHistory.find(
        (history) => history.id === historyId,
      );
      if (!entry) {
        set({ error: "Custom recipe history entry not found" });
        return;
      }
      // Forward the virtuals captured at the original apply so the replay
      // round-trips ``recipe[i] >= LUT.N`` through backend validation and
      // reaches the worker with an intact virtual-material registry.
      // 带上首次 apply 时记下的虚拟耗材，保证重放时 ``recipe[i] >= LUT.N``
      // 通过后端校验、worker 也能重建虚拟材料注册表。
      await _get().applyCustomRecipeOverride(
        regionIds,
        entry.recipe,
        entry.layerOrder,
        entry.virtualMaterials,
      );
    },

    // --- 连通区域替换 ---
    applyRegionReplace: async (newHex: string) => {
      const initialState = _get();
      const sid = initialState.sessionId;
      if (!sid) {
        set({ error: "请先预览图片" });
        return;
      }
      const pendingSelection = waitForSelectionMutation(sid);
      if (pendingSelection && !(await pendingSelection)) return;
      const contentReservation = acquireContentCommitTurn(sid);
      if (
        !contentReservation.readyImmediately &&
        !(await contentReservation.ready)
      ) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const state = _get();
      if (state.sessionId !== sid) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      if (!state.regionData) {
        releaseContentCommit(contentReservation, false);
        set({ error: "Please select a connected region first" });
        return;
      }
      const previewCommit = captureReplacementPreviewCommit(
        state,
        contentReservation,
      );
      set({
        replacePreviewLoading: true,
        error: null,
      });
      try {
        const response = await apiRegionReplace(
          sid,
          `#${newHex}`,
          undefined,
          undefined,
          previewCommit.operationId,
        );
        if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) return;
        if (_get().sessionId !== sid) {
          return;
        }
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          regionData: null,
          replacePreviewLoading: false,
          regionReplacementCount: state.regionReplacementCount + 1,
          threemfDiskPath: null,
          downloadUrl: null,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
          ...dynamicMaterialResultState(response),
          ...historyFlagsFromResponse(response),
          ...selectionUpdatesFromResponse(_get(), sid, response.selection),
        };

        // 更新 3D 预览 GLB URL（仅当后端返回非空 URL 时）
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        // preview_glb_url 为 null 时不清除现有 previewGlbUrl

        // 更新颜色轮廓数据（仅当后端返回非空数据时）
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }

        // Only a successful response proves that the spatial mutation reached
        // the session cache. Read the live count here so overlapping requests
        // cannot overwrite one another with an earlier snapshot.
        // 仅成功响应才能证明空间编辑已写入 session cache；读取最新计数，避免
        // 并发请求用旧快照相互覆盖。
        set((current) => ({
          ...updates,
          regionReplacementCount: current.regionReplacementCount + 1,
        }));
        _get()._pollAsyncGlb();
      } catch (err) {
        const settlement = await settleReplacementPreviewError(
          _get(),
          previewCommit,
          _get,
          (partial) => set(partial),
          err,
          "区域颜色替换失败",
        );
        if (!settlement.active || settlement.committed || settlement.unknown) return;
        if (_get().sessionId !== sid) {
          return;
        }
        set({
          replacePreviewLoading: false,
          error: visibleConverterError(err, "区域颜色替换失败"),
        });
      }
    },

    applyGradientRegionPixelReplace: async (
      groupIndex: number,
      regionIndex: number,
      targetHex: string,
    ) => {
      const initialState = _get();
      const sid = initialState.sessionId;
      if (!sid) {
        set({ error: "请先预览图片" });
        return;
      }
      const pendingSelection = waitForSelectionMutation(sid);
      if (pendingSelection && !(await pendingSelection)) return;
      const contentReservation = acquireContentCommitTurn(sid);
      if (
        !contentReservation.readyImmediately &&
        !(await contentReservation.ready)
      ) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const state = _get();
      if (state.sessionId !== sid) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const hexNoHash = targetHex.replace(/^#/, "").toLowerCase();
      const previewCommit = captureReplacementPreviewCommit(
        state,
        contentReservation,
      );
      set({
        replacePreviewLoading: true,
        error: null,
      });
      try {
        const response = await apiRegionReplace(
          sid,
          `#${hexNoHash}`,
          {
            gradientGroupIndex: groupIndex,
            gradientRegionIndex: regionIndex,
          },
          undefined,
          previewCommit.operationId,
        );
        if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) return;
        if (_get().sessionId !== sid) return;
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
          // The edit is spatial and the chosen region's pixels are now
          // ``targetHex``; keep the panel state consistent by clearing
          // the region highlight and any leftover multi-selection so the
          // LUT picker/preview return to the default "nothing selected"
          // mode after the replace completes.
          // 空间替换完成后清除区域高亮与遗留的多选集合，恢复默认态。
          gradientSelection: null,
          selectedColors: new Set<string>(),
          selectedColor: null,
          regionData: null,
          // generate() must reuse the cached matched_rgb (which the server
          // has just mutated) rather than re-running the fresh-pipeline,
          // exactly like applyRegionReplace does.
          // 与 applyRegionReplace 一致：让 generate 走 use_cached_matched_rgb。
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
          ...dynamicMaterialResultState(response),
          ...historyFlagsFromResponse(response),
          ...selectionUpdatesFromResponse(_get(), sid, response.selection),
        };
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }
        set((current) => ({
          ...updates,
          regionReplacementCount: current.regionReplacementCount + 1,
        }));
        _get()._pollAsyncGlb();
      } catch (err) {
        const settlement = await settleReplacementPreviewError(
          _get(),
          previewCommit,
          _get,
          (partial) => set(partial),
          err,
          "区域颜色替换失败",
        );
        if (!settlement.active || settlement.committed || settlement.unknown) return;
        if (_get().sessionId !== sid) return;
        set({
          replacePreviewLoading: false,
          error: visibleConverterError(err, "区域颜色替换失败"),
        });
      }
    },

    toggleGradientRegionSelection: (
      groupIndex: number,
      regionIndex: number,
    ) => {
      const state = _get();
      const current = state.selectedGradientRegions;
      // Same-group invariant: a click on a region belonging to a different
      // group drops the prior list entirely and seeds the selection with
      // just the new region, so the user can "switch" between groups
      // without first pressing Clear. Matches the intuition that merging
      // regions from unrelated gradients isn't meaningful.
      // 同 group 不变式：点跨 group 的 region 时清空旧选择并只保留新的。
      const isCrossGroup =
        current.length > 0 && current[0].groupIndex !== groupIndex;
      let next: Array<{ groupIndex: number; regionIndex: number }>;
      if (isCrossGroup) {
        next = [{ groupIndex, regionIndex }];
      } else {
        const existingIdx = current.findIndex(
          (r) => r.groupIndex === groupIndex && r.regionIndex === regionIndex,
        );
        next =
          existingIdx >= 0
            ? [
                ...current.slice(0, existingIdx),
                ...current.slice(existingIdx + 1),
              ]
            : [...current, { groupIndex, regionIndex }];
      }
      // gradientSelection mirrors selectedGradientRegions so LUT dispatch
      // can route through applyMultiRegionPixelReplace via a single source
      // of truth. Empty list → null; single-entry list still uses
      // "multi-region" so the batch path stays active even with 1 box
      // ticked.
      // gradientSelection 与 selectedGradientRegions 同步，即便只勾 1 个
      // 也走 batch 路径，语义统一。
      const source: GradientSelectionSource | null =
        next.length === 0
          ? null
          : {
              kind: "multi-region",
              groupIndex: next[0].groupIndex,
              regionIndices: next.map((r) => r.regionIndex),
            };
      // Reset the 2D preview highlight state so ticking a checkbox is a
      // pure "mark region for batch merge" action — it must NOT trigger a
      // select-all-style cyan overlay on the canvas. Without this reset,
      // any leftover ``selectedColors`` / ``regionData`` / highlight PNG
      // from a prior "Select group" / "Select region" click or palette
      // tile interaction would still be visible, looking as if the
      // checkbox itself caused the highlight.
      // 勾选 checkbox 只是"标记 region 加入合并"，不应触发 2D 高亮。重置
      // selectedColors/regionData 并把 previewImageUrl 回退到 base，避免
      // 先前"选中整组/区域"或调色板点击留下的 cyan 覆盖被误认为是
      // checkbox 触发的。
      const baseUrl = getPreviewBaseUrl(state);
      set({
        selectedGradientRegions: next,
        gradientSelection: source,
        selectedColors: new Set<string>(),
        selectedColor: null,
        regionData: null,
        selectedRegions: [],
        previewImageUrl: baseUrl,
      });
    },

    clearGradientRegionSelection: () => {
      // Also null out gradientSelection when it was tracking the multi-
      // region list; leave the region/group kinds alone so clearing does
      // not disturb an unrelated single-row highlight.
      // 同步清空 multi-region 源标识；单 region/group 的高亮标识不受影响。
      const current = _get().gradientSelection;
      const nextSource = current?.kind === "multi-region" ? null : current;
      set({
        selectedGradientRegions: [],
        gradientSelection: nextSource,
      });
    },

    flattenSelectedGradientRegions: async () => {
      const initialState = _get();
      const sid = initialState.sessionId;
      if (!sid) return;
      const pendingSelection = waitForSelectionMutation(sid);
      if (pendingSelection && !(await pendingSelection)) return;
      const contentReservation = acquireContentCommitTurn(sid);
      if (
        !contentReservation.readyImmediately &&
        !(await contentReservation.ready)
      ) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const state = _get();
      if (state.sessionId !== sid) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const regions = state.selectedGradientRegions;
      if (regions.length < 2) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const groups = state.gradientGroups;
      if (!groups || groups.length === 0) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const groupIndex = regions[0].groupIndex;
      const group = groups.find((g) => g.group_index === groupIndex);
      if (!group) {
        releaseContentCommit(contentReservation, false);
        return;
      }

      // Pixel-count-weighted representative across the union of the
      // selected regions' material_breakdowns: sum pixel_count per hex
      // across every picked region, then keep the hex with the largest
      // total. This matches the existing group-level representative_hex
      // semantics (majority colour wins) but restricted to the subset the
      // user actually checked, so merging "region 1 + region 3" collapses
      // to whatever colour dominates those two regions specifically — not
      // the whole-group majority.
      // 按勾选 region 的 material_breakdown 累加像素数，最多的 hex 做代表色。
      // 与整组 representative_hex 同思想，但只在选中的子集里评估，避免把未
      // 勾选的 region 纳入计算。
      const selectedRegionSet = new Set(regions.map((r) => r.regionIndex));
      const totals = new Map<string, number>();
      for (const region of group.regions) {
        if (!selectedRegionSet.has(region.region_index)) continue;
        for (const mb of region.material_breakdown) {
          const hex = mb.hex.replace(/^#/, "").toLowerCase();
          totals.set(hex, (totals.get(hex) ?? 0) + (mb.pixel_count ?? 0));
        }
      }
      if (totals.size === 0) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      let targetHex = "";
      let best = -1;
      for (const [hex, count] of totals.entries()) {
        if (count > best) {
          best = count;
          targetHex = hex;
        }
      }
      if (!targetHex) {
        releaseContentCommit(contentReservation, false);
        return;
      }

      const previewCommit = captureReplacementPreviewCommit(
        state,
        contentReservation,
      );
      set({
        replacePreviewLoading: true,
        error: null,
      });
      try {
        const response = await apiRegionReplaceBatch(
          sid,
          regions.map((r) => ({
            gradientGroupIndex: r.groupIndex,
            gradientRegionIndex: r.regionIndex,
            replacementColor: `#${targetHex}`,
          })),
          previewCommit.operationId,
        );
        if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) return;
        if (_get().sessionId !== sid) return;
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
          // Matched to applyGradientRegionPixelReplace / regionReplace
          // post-state: clear selection and bump regionReplacementCount so
          // downstream generate() takes the cached-matched_rgb shortcut.
          // 与单 region 替换后一致：清空选择 + regionReplacementCount 自增。
          gradientSelection: null,
          selectedGradientRegions: [],
          selectedColors: new Set<string>(),
          selectedColor: null,
          regionData: null,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
          ...dynamicMaterialResultState(response),
          ...historyFlagsFromResponse(response),
          ...selectionUpdatesFromResponse(_get(), sid, response.selection),
        };
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }
        set((current) => ({
          ...updates,
          regionReplacementCount:
            current.regionReplacementCount + regions.length,
        }));
        _get()._pollAsyncGlb();
      } catch (err) {
        const settlement = await settleReplacementPreviewError(
          _get(),
          previewCommit,
          _get,
          (partial) => set(partial),
          err,
          "合并去海带纹失败",
        );
        if (!settlement.active || settlement.committed || settlement.unknown) return;
        if (_get().sessionId !== sid) return;
        set({
          replacePreviewLoading: false,
          error: visibleConverterError(err, "合并去海带纹失败"),
        });
      }
    },

    requantizeSelectedGradientRegions: async (
      localQuantizeColors: number,
      explicitTargets?: ReadonlyArray<{
        groupIndex: number;
        regionIndex: number;
      }>,
    ) => {
      const initialState = _get();
      const sid = initialState.sessionId;
      if (!sid) return;
      const pendingSelection = waitForSelectionMutation(sid);
      if (pendingSelection && !(await pendingSelection)) return;
      const contentReservation = acquireContentCommitTurn(sid);
      if (
        !contentReservation.readyImmediately &&
        !(await contentReservation.ready)
      ) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const state = _get();
      if (state.sessionId !== sid) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      // Explicit targets from a per-region button: honour them and leave
      // the batch checkbox list intact so the user's in-progress merge
      // selection survives. Falls back to the checkbox list otherwise.
      // 显式 targets：per-region 按钮传入，保留用户已有的批量勾选。
      const usingExplicitTargets =
        explicitTargets !== undefined && explicitTargets.length > 0;
      const regions = usingExplicitTargets
        ? (explicitTargets as ReadonlyArray<{
            groupIndex: number;
            regionIndex: number;
          }>)
        : state.selectedGradientRegions;
      if (regions.length === 0) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      // Clamp to the backend's validated range [12, 256]. The dialog enforces
      // it too, but belt-and-braces protects against rogue callers.
      // 边界兜底：后端也校验 12-256，这里再夹一道避免发送非法值。
      const clamped = Math.max(
        12,
        Math.min(256, Math.round(localQuantizeColors)),
      );

      const previewCommit = captureReplacementPreviewCommit(
        state,
        contentReservation,
      );
      set({
        replacePreviewLoading: true,
        error: null,
      });
      try {
        const response = await apiRegionRequantize(
          sid,
          regions.map((r) => ({
            gradientGroupIndex: r.groupIndex,
            gradientRegionIndex: r.regionIndex,
          })),
          clamped,
          previewCommit.operationId,
        );
        if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) return;
        if (_get().sessionId !== sid) return;
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
          // Match post-state of flatten / region-replace so generate() picks
          // up the cached-matched_rgb shortcut and layer images are invalidated.
          // 与 flatten 保持一致：LUT 选中/高亮一律清空；批量勾选仅在隐式调用
          // （走当前勾选列表）时清空，显式 per-region 操作保留用户选中。
          selectedColors: new Set<string>(),
          selectedColor: null,
          regionData: null,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
          ...dynamicMaterialResultState(response),
          ...historyFlagsFromResponse(response),
          ...selectionUpdatesFromResponse(_get(), sid, response.selection),
        };
        if (!usingExplicitTargets) {
          updates.gradientSelection = null;
          updates.selectedGradientRegions = [];
        }
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }
        // The backend re-runs gradient-group analysis because requantize
        // shifts matched_rgb enough to change the segmentation. When the
        // response carries the refreshed groups, write them straight into
        // the store (and pin gradientGroupsSessionId so the cached-short
        // circuit in fetchGradientGroups keeps working for later reads).
        // Without this, the panel would keep showing the pre-requantize
        // groups and the user would feel the panel is "frozen".
        // 后端在二次量化后会重跑分组分析；响应带了新分组时直接写进 store，
        // 并把 gradientGroupsSessionId 置回当前 session，保持
        // fetchGradientGroups 的缓存短路对后续读取仍然有效。
        if (response.gradient_groups !== undefined) {
          updates.gradientGroups = response.gradient_groups ?? [];
          updates.gradientGroupsError = null;
          updates.gradientGroupsLoading = false;
          updates.gradientGroupsSessionId = sid;
        }
        set((current) => ({
          ...updates,
          regionReplacementCount:
            current.regionReplacementCount + regions.length,
        }));
        _get()._pollAsyncGlb();
      } catch (err) {
        const settlement = await settleReplacementPreviewError(
          _get(),
          previewCommit,
          _get,
          (partial) => set(partial),
          err,
          "区域二次量化失败",
        );
        if (!settlement.active || settlement.committed || settlement.unknown) return;
        if (_get().sessionId !== sid) return;
        set({
          replacePreviewLoading: false,
          error: visibleConverterError(err, "区域二次量化失败"),
        });
      }
    },

    applyMultiRegionPixelReplace: async (targetHex: string) => {
      const initialState = _get();
      const sid = initialState.sessionId;
      if (!sid) return;
      const pendingSelection = waitForSelectionMutation(sid);
      if (pendingSelection && !(await pendingSelection)) return;
      const contentReservation = acquireContentCommitTurn(sid);
      if (
        !contentReservation.readyImmediately &&
        !(await contentReservation.ready)
      ) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const state = _get();
      if (state.sessionId !== sid) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const regions = state.selectedGradientRegions;
      if (regions.length === 0) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const hexNoHash = targetHex.replace(/^#/, "").toLowerCase();
      if (!hexNoHash) {
        releaseContentCommit(contentReservation, false);
        return;
      }

      const previewCommit = captureReplacementPreviewCommit(
        state,
        contentReservation,
      );
      set({
        replacePreviewLoading: true,
        error: null,
      });
      try {
        const response = await apiRegionReplaceBatch(
          sid,
          regions.map((r) => ({
            gradientGroupIndex: r.groupIndex,
            gradientRegionIndex: r.regionIndex,
            replacementColor: `#${hexNoHash}`,
          })),
          previewCommit.operationId,
        );
        if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) return;
        if (_get().sessionId !== sid) return;
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
          gradientSelection: null,
          selectedGradientRegions: [],
          selectedColors: new Set<string>(),
          selectedColor: null,
          regionData: null,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
          ...dynamicMaterialResultState(response),
          ...historyFlagsFromResponse(response),
        };
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }
        set((current) => ({
          ...updates,
          regionReplacementCount:
            current.regionReplacementCount + regions.length,
        }));
        _get()._pollAsyncGlb();
      } catch (err) {
        const settlement = await settleReplacementPreviewError(
          _get(),
          previewCommit,
          _get,
          (partial) => set(partial),
          err,
          "合并换色失败",
        );
        if (!settlement.active || settlement.committed || settlement.unknown) return;
        if (_get().sessionId !== sid) return;
        set({
          replacePreviewLoading: false,
          error: visibleConverterError(err, "合并换色失败"),
        });
      }
    },

    applyCustomRecipeOverride: async (
      regionIds: string[],
      recipe: number[],
      layerOrder: string = "Top2Bottom",
      virtualMaterials?: VirtualMaterial[],
    ) => {
      const state = _get();
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return;
      }
      await _get().commitRecipeOverride({
        session_id: state.sessionId, region_ids: regionIds, recipe,
        layer_order: layerOrder,
        color_layers: isDynamicMaterialActive(state) ? recipe.length
          : Math.max(recipe.length, state.color_layers ?? recipe.length),
        layer_height_mm: state.layer_height_mm ?? state.selectedLutInfo?.layer_height_mm ?? 0.08,
        ...(virtualMaterials?.length ? { virtual_materials: virtualMaterials } : {}),
      });
    },

    commitRecipeOverride: async (request) => {
      const regionIds = request.region_ids ?? [];
      const recipe = [...request.recipe];
      const layerOrder = request.layer_order;
      const virtualMaterials = request.virtual_materials;
      const initialState = _get();
      if (!initialState.sessionId || initialState.sessionId !== request.session_id) {
        set({ error: "请先预览图片" });
        return;
      }
      const sessionId = initialState.sessionId;
      const pendingSelection = waitForSelectionMutation(sessionId);
      if (pendingSelection && !(await pendingSelection)) return;
      const contentReservation = acquireContentCommitTurn(sessionId);
      if (
        !contentReservation.readyImmediately &&
        !(await contentReservation.ready)
      ) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const state = _get();
      if (state.sessionId !== sessionId) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const targetRegionIds = regionIds.filter(Boolean);
      if (targetRegionIds.length === 0) {
        releaseContentCommit(contentReservation, false);
        set({ error: "请先选择区域" });
        return;
      }
      // Dynamic sessions transport the user's actual recipe length. The
      // preview's physical print depth remains in the session and the backend
      // pads it with the configured backing material; sending the maximum
      // depth here turns a valid short recipe into a 422 mismatch.
      const resolvedLayers = request.color_layers;
      const resolvedHeight = request.layer_height_mm;
      // Deep-copy virtuals to isolate the payload / state from later
      // caller-side mutations; 422 on ``recipe[i] >= LUT.N`` requires this
      // list to be present, so forward it when non-empty.
      // 深拷贝 virtuals 避免调用方随后改动影响 store / 请求体；recipe 里有
      // 虚拟索引时后端 422 校验需要它，故非空时必须透传。
      const clonedVirtuals = (virtualMaterials ?? []).map((material) => ({
        name: material.name,
        hex: material.hex,
      }));

      const previewCommit = captureReplacementPreviewCommit(
        state,
        contentReservation,
      );
      set({
        replacePreviewLoading: true,
        error: null,
      });
      try {
        const response = await apiApplyRecipeOverride({
          session_id: sessionId,
          region_ids: targetRegionIds,
          recipe,
          layer_order: layerOrder,
          color_layers: resolvedLayers,
          layer_height_mm: resolvedHeight,
          ...(clonedVirtuals.length > 0
            ? { virtual_materials: clonedVirtuals }
            : {}),
          operation_id: previewCommit.operationId,
        });
        if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) return;
        // The response owns the post-edit mask and revisions. A second
        // selection mutation here would race dependent save/generate work.
        set((current) => ({
          replacePreviewLoading: false,
          previewImageUrl:
            normalizeResourceUrl(response.preview_url) ?? response.preview_url,
          previewBaseImageUrl:
            normalizeResourceUrl(response.preview_url) ?? response.preview_url,
          previewGlbUrl: response.preview_glb_url
            ? normalizeResourceUrl(response.preview_glb_url)
            : current.previewGlbUrl,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
          ...dynamicMaterialResultState(response),
          ...historyFlagsFromResponse(response),
          recipe_overrides: response.recipe_overrides ?? [
            ...current.recipe_overrides.filter(
              (item) => !targetRegionIds.includes(item.region_id),
            ),
            ...targetRegionIds.map((regionId) => ({
              region_id: regionId,
              recipe: [...recipe],
              layer_order: layerOrder,
              ...(clonedVirtuals.length > 0
                ? {
                    virtual_materials: clonedVirtuals.map((material) => ({
                      ...material,
                    })),
                  }
                : {}),
            })),
          ],
          lutMatchMode: "predictive",
          lutMatchInfo: {
            ...(current.lutMatchInfo ?? {}),
            match_mode: "predictive",
            runtime_mode_key: response.runtime_mode_key ?? null,
            source: response.source,
            override: true,
          },
          ...selectionUpdatesFromResponse(
            current,
            sessionId,
            response.selection,
          ),
        }));
        if (!response.selection) void _get().hydrateSelectionDocument();
        _get()._pollAsyncGlb();
        return response;
      } catch (err) {
        const settlement = await settleReplacementPreviewError(
          _get(),
          previewCommit,
          _get,
          (partial) => set(partial),
          err,
          "自定义配方应用失败",
        );
              if (!settlement.active || settlement.committed || settlement.unknown) return;
        set({
          replacePreviewLoading: false,
          error: visibleConverterError(err, "自定义配方应用失败"),
        });
      }
    },

    replaceSharedSelectionColor: async (targetHex: string) => {
      // Shared-selection path: repaint exactly the authoritative server mask.
      // 共享选区路径：只重绘服务端权威选区内的像素。
      const initialSelectionState = _get();
      const pendingSelection = initialSelectionState.sessionId
        ? waitForSelectionMutation(initialSelectionState.sessionId)
        : null;
      if (pendingSelection && !(await pendingSelection)) return true;
      let currentSelectionState = _get();
      if (currentSelectionState.sessionId !== initialSelectionState.sessionId) {
        return true;
      }
      const currentSessionId = currentSelectionState.sessionId;
      const selectionRevision = currentSelectionState.selectionDocument?.selection_revision;
      if (selectionRevision !== undefined && currentSessionId) {
        const contentReservation = acquireContentCommitTurn(currentSessionId);
        if (
          !contentReservation.readyImmediately &&
          !(await contentReservation.ready)
        ) {
          releaseContentCommit(contentReservation, false);
          return true;
        }
        currentSelectionState = _get();
        if (
          currentSelectionState.sessionId !== currentSessionId ||
          currentSelectionState.selectionDocument?.selection_revision === undefined ||
          currentSelectionState.selectionDocument.selected_pixel_count === 0
        ) {
          // A target pick may have been queued behind a clear/toggle-off. It
          // consumes that intent without falling back to a global recolour.
          releaseContentCommit(contentReservation, false);
          return true;
        }
        const latestSelectionRevision =
          currentSelectionState.selectionDocument.selection_revision;
        const previewCommit = captureReplacementPreviewCommit(
          currentSelectionState,
          contentReservation,
        );
        set({ replacePreviewLoading: true, error: null });
        try {
          const response = await apiRegionReplace(
            currentSessionId,
            `#${targetHex}`,
            undefined,
            latestSelectionRevision,
            previewCommit.operationId,
          );
          if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) {
            return true;
          }
          const current = _get();
          set({
            previewImageUrl: normalizeResourceUrl(response.preview_url),
            previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
            replacePreviewLoading: false,
            regionReplacementCount: current.regionReplacementCount + 1,
            threemfDiskPath: null,
            downloadUrl: null,
            ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
            ...dynamicMaterialResultState(response),
            ...historyFlagsFromResponse(response),
            ...selectionUpdatesFromResponse(
              current,
              currentSessionId,
              response.selection,
            ),
          });
          if (!response.selection) {
            // Never guess ``content_revision + 1`` on the client. The
            // endpoint must return the authoritative document; an older
            // server can still be synchronized explicitly before the next
            // selection operation.
            void _get().hydrateSelectionDocument();
          }
          _get()._pollAsyncGlb();
        } catch (err) {
          const settlement = await settleReplacementPreviewError(
            _get(),
            previewCommit,
            _get,
            (partial) => set(partial),
            err,
            "Selection color replacement failed",
          );
          if (!settlement.active || settlement.committed || settlement.unknown) return true;
          set({
            replacePreviewLoading: false,
            error: visibleConverterError(err, "Selection color replacement failed"),
          });
        }
        return true;
      }
      return false;
    },

    // --- 待确认颜色替换 ---
    setPendingReplacement: (pending: PendingReplacement | null) => {
      set({ pendingReplacement: pending });
    },

    confirmReplacement: async () => {
      const state = _get();
      const pending = state.pendingReplacement;
      if (!pending) return;

      // 清除 pending 状态
      set({ pendingReplacement: null });

      // When the pending replacement was seeded by a Gradient Groups
      // *region* button, the user's intent is strictly spatial: repaint
      // only the pixels inside that banded sub-region. The classic
      // ``select-all`` branch below would apply a whole-image ``hex →
      // hex`` remap which recolours every matching pixel on the canvas —
      // that's exactly the "replace cyan band → whole body turns red"
      // regression we are fixing. Route to :func:`applyGradientRegionPixelReplace`
      // first so the backend rebuilds the mask from the cached
      // per-pixel ``gradient_region_id_map``.
      // 区域来源时改走空间替换：用 /region-replace 的 gradient 路径，
      // 服务端从 region_id_map 生成精确 mask，仅改该区域像素，避免全图
      // hex 替换误伤共享同色的其它区域。
      const gradSel = state.gradientSelection;
      if (gradSel?.kind === "multi-region") {
        // Multi-region checkbox flow: the user ticked ≥1 region box and
        // then picked a LUT colour. Fan out the pick to every selected
        // region via a single /region-replace-batch call (same spatial
        // path applyGradientRegionPixelReplace uses for one region).
        // 多勾 region → LUT 点色：一次 batch 把所有勾选 region 刷成该色，
        // 与单 region 的空间替换路径同源。
        await _get().applyMultiRegionPixelReplace(pending.targetHex);
        return;
      }
      // Tool choice and the source button do not change the selected pixels.
      // Every colour picker targets the shared mask, including same-colour LUT
      // picks and selections initiated by the gradient panel.
      if (
        mayUseSharedSelectionReplace(_get()) &&
        (await _get().replaceSharedSelectionColor(pending.targetHex))
      ) {
        return;
      }
      if (gradSel?.kind === "region") {
        await _get().applyGradientRegionPixelReplace(
          gradSel.groupIndex,
          gradSel.regionIndex,
          pending.targetHex,
        );
        return;
      }

      switch (pending.mode) {
        case "select-all":
          if (pending.sourceColors && pending.sourceColors.length > 1) {
            // 多选批量替换：所有选中的源色 → 同一目标色
            // 先临时写入 selectedColors 以供 applyBatchColorRemap 使用
            set({ selectedColors: new Set(pending.sourceColors) });
            await _get().applyBatchColorRemap(pending.targetHex);
            set({ selectedColors: new Set<string>(), selectedColor: null });
          } else {
            // 单色替换：乐观更新 colorRemapMap → 3D 预览即时响应
            _get().applyColorRemap(pending.sourceHex, pending.targetHex);
          }
          break;
        case "multi-select": {
          // Legacy multi-region fallback.
          // one batch request. The server rebuilds each mask via the same
          // flood-fill kernel /region-detect uses, applies all mutations
          // to matched_rgb cumulatively, and renders PNG + GLB exactly
          // once for the whole batch. Previously this path looped N times
          // and triggered N GLB rebuilds — the main "multi-region replace
          // feels slow" regression we are fixing.
          // 多区域模式：每条 region 的 click 坐标 + 目标色一次性发批量请求，
          // 后端内部循环建 mask 并累积应用，PNG/GLB/物料 sync 各只跑 1 次。
          // 旧实现是 N 次 detect + N 次 replace → N 次 GLB 重建。
          const regions = pending.sourceRegions ?? [];
          if (regions.length === 0) break;
          const curState = _get();
          const sid = curState.sessionId;
          if (!sid) break;
          const batchItems = regions
            .filter((r) => r.clickX != null && r.clickY != null)
            .map((r) => ({
              clickX: r.clickX as number,
              clickY: r.clickY as number,
              replacementColor: `#${pending.targetHex}`,
            }));
          if (batchItems.length === 0) break;
          const contentReservation = acquireContentCommitTurn(sid);
          if (
            !contentReservation.readyImmediately &&
            !(await contentReservation.ready)
          ) {
            releaseContentCommit(contentReservation, false);
            break;
          }
          const latestState = _get();
          if (latestState.sessionId !== sid) {
            releaseContentCommit(contentReservation, false);
            break;
          }
          const previewCommit = captureReplacementPreviewCommit(
            latestState,
            contentReservation,
          );
          set({
            replacePreviewLoading: true,
            threemfDiskPath: null,
            downloadUrl: null,
          });
          try {
            const response = await apiRegionReplaceBatch(
              sid,
              batchItems,
              previewCommit.operationId,
            );
            if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) {
              return;
            }
            if (_get().sessionId !== sid) return;
            const updates: Partial<ConverterState> = {
              previewImageUrl: normalizeResourceUrl(response.preview_url),
              previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
              replacePreviewLoading: false,
              selectedRegions: [],
              regionData: null,
              selectedColor: null,
              ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
              ...dynamicMaterialResultState(response),
              ...selectionUpdatesFromResponse(_get(), sid, response.selection),
            };
            if (response.preview_glb_url) {
              updates.previewGlbUrl = normalizeResourceUrl(
                response.preview_glb_url,
              );
            }
            if (response.color_contours) {
              updates.colorContours = response.color_contours;
            }
            set((current) => ({
              ...updates,
              regionReplacementCount:
                current.regionReplacementCount + batchItems.length,
            }));
            _get()._pollAsyncGlb();
          } catch (err) {
            const settlement = await settleReplacementPreviewError(
              _get(),
              previewCommit,
              _get,
              (partial) => set(partial),
              err,
              "Multi-region color replacement failed",
            );
            if (!settlement.active || settlement.committed || settlement.unknown) return;
            if (_get().sessionId !== sid) return;
            set({
              replacePreviewLoading: false,
              error: visibleConverterError(
                err,
                "Multi-region color replacement failed",
              ),
            });
          }
          break;
        }
        case "current":
        case "region": {
          // 不更新 colorRemapMap（避免 3D 预览全局变色）
          // 调用后端区域替换；计数和历史快照由 applyRegionReplace 统一处理。
          const curState = _get();
          // 调用后端 region-replace → 2D 预览精确区域替换
          if (curState.regionData) {
            await _get().applyRegionReplace(pending.targetHex);
          }
          break;
        }
      }
    },

    // --- 全图颜色替换 ---
    applyColorRemap: documentCommand((origHex: string, newHex: string) => {
      const state = _get();
      if (state.sessionId) {
        void commitColorRemap(_get, set, current =>
          buildCurrentVisibleColorRemapMap(current.colorRemapMap, [origHex], newHex));
        return;
      }
      // 推入当前快照到 history
      const snapshot = { ...state.colorRemapMap };
      const newHistory = [...state.remapHistory, snapshot];
      // 更新 map。origHex 表示当前可见颜色；若该颜色来自此前的 A→origHex
      // 替换，也同步改写那些上游映射，使“点当前看到的颜色再替换”生效。
      const newMap = buildCurrentVisibleColorRemapMap(
        state.colorRemapMap,
        [origHex],
        newHex,
      );
      set({
        colorRemapMap: newMap,
        remapHistory: newHistory,
        remapRedoHistory: [],
        threemfDiskPath: null,
        downloadUrl: null,
      });
    }, { localEditor: true }),

    undoColorRemap: async () => {
      const state = _get();
      if (!state.sessionId) {
        const newHistory = [...state.remapHistory];
        const previousMap = newHistory.pop();
        if (!previousMap) return;
        set({
          colorRemapMap: previousMap,
          remapHistory: newHistory,
          remapRedoHistory: [state.colorRemapMap, ...state.remapRedoHistory],
          threemfDiskPath: null,
          downloadUrl: null,
        });
        return;
      }
      await navigateEditorHistory("undo", _get, set);
    },

    redoColorRemap: async () => {
      const state = _get();
      if (!state.sessionId) {
        const [nextMap, ...remainingRedo] = state.remapRedoHistory;
        if (!nextMap) return;
        set({
          colorRemapMap: nextMap,
          remapHistory: [...state.remapHistory, { ...state.colorRemapMap }],
          remapRedoHistory: remainingRedo,
          threemfDiskPath: null,
          downloadUrl: null,
        });
        return;
      }
      await navigateEditorHistory("redo", _get, set);
    },

    canUndoAdjustments: () => {
      const state = _get();
      if (!state.sessionId) {
        return state.remapHistory.length > 0 || hasAdjustmentState(state);
      }
      return state.historyCanUndo && !state.historyBusy;
    },

    canRedoAdjustments: () => {
      const state = _get();
      if (!state.sessionId) {
        return state.remapRedoHistory.length > 0;
      }
      return state.historyCanRedo && !state.historyBusy;
    },

    clearAllRemaps: documentCommand(async () => {
      let state = _get();
      const sessionId = state.sessionId;
      let contentReservation: ContentCommitReservation | undefined;
      if (sessionId) {
        const pendingSelection = waitForSelectionMutation(sessionId);
        if (pendingSelection && !(await pendingSelection)) return;
        contentReservation = acquireContentCommitTurn(sessionId);
        if (
          !contentReservation.readyImmediately &&
          !(await contentReservation.ready)
        ) {
          releaseContentCommit(contentReservation, false);
          return;
        }
        state = _get();
        if (state.sessionId !== sessionId) {
          releaseContentCommit(contentReservation, false);
          return;
        }
      }
      const previewCommit = captureReplacementPreviewCommit(
        state,
        contentReservation,
      );
      // 关键修复：清空本身也要可撤销。无 session（本地预览）时 remapHistory 是
      // 唯一撤销数据源，原先无条件 remapHistory: [] 把"清空前状态"抹掉，导致
      // "清空替换完全无法撤销"。这里把清空前 colorRemapMap 入栈，让清空可回退。
      // Record the pre-clear map so "clear replacements" is itself undoable in the
      // local (session-less) flow — previously remapHistory was wiped, so clear
      // could never be undone.
      const hadRemaps = Object.keys(state.colorRemapMap).length > 0;
      const nextRemapHistory = state.sessionId
        ? state.remapHistory
        : hadRemaps
          ? [...state.remapHistory, { ...state.colorRemapMap }]
          : state.remapHistory;
      const clearRollbackState: Partial<ConverterState> = {
        colorRemapMap: { ...state.colorRemapMap },
        remapHistory: cloneRemapHistory(state.remapHistory),
        remapRedoHistory: cloneRemapHistory(state.remapRedoHistory),
        replacement_regions: cloneReplacementRegions(state.replacement_regions),
        recipe_overrides: cloneRecipeOverrides(state.recipe_overrides),
        previewImageUrl: state.previewImageUrl,
        previewBaseImageUrl: state.previewBaseImageUrl,
        previewGlbUrl: state.previewGlbUrl,
        threemfDiskPath: state.threemfDiskPath,
        downloadUrl: state.downloadUrl,
        layerImages: [...state.layerImages],
        layerImagesSourceKey: state.layerImagesSourceKey,
        gradientSelection: state.gradientSelection,
        pendingReplacement: state.pendingReplacement,
        regionReplacementCount: state.regionReplacementCount,
      };
      if (sessionId) {
        attachContentCommitRollback(previewCommit, clearRollbackState);
      }
      set({
        colorRemapMap: {},
        remapHistory: nextRemapHistory,
        remapRedoHistory: [],
        replacement_regions: [],
        recipe_overrides: [],
        replacePreviewLoading: Boolean(state.sessionId),
        previewGlbUrl: null,
        threemfDiskPath: null,
        downloadUrl: null,
        // The shared SelectionDocument is intentionally preserved: clearing
        // replacements is a content action and must not collapse the user's
        // current selection, per the selection-history invariants.
        gradientSelection: null,
        pendingReplacement: null,
        regionReplacementCount: 0,
        ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
      });
      // 调用后端清空 replacement_regions 并从原始 matched_rgb 重新生成预览和 GLB
      // 不能依赖 originalPreviewUrl，因为 region-replace 会修改后端缓存的 matched_rgb
      if (sessionId) {
        apiResetReplacements(sessionId, previewCommit.operationId)
          .then((res) => {
            if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) {
              return;
            }
            const url =
              normalizeResourceUrl(res?.preview_url) ??
              _get().originalPreviewUrl ??
              state.originalPreviewUrl;
            const updates: Partial<ConverterState> = {
              previewImageUrl: url,
              originalPreviewUrl: url,
              previewBaseImageUrl: url,
              replacePreviewLoading: false,
              previewGlbUrl: res?.preview_glb_url
                ? normalizeResourceUrl(res.preview_glb_url)
                : null,
              ...dynamicMaterialResultState(res),
              ...historyFlagsFromResponse(res),
              ...selectionUpdatesFromResponse(
                _get(),
                sessionId,
                res?.selection,
              ),
            };
            set(updates);
            _get()._pollAsyncGlb();
          })
          .catch(async (err) => {
            const settlement = await settleReplacementPreviewError(
              _get(),
              previewCommit,
              _get,
              (partial) => set(partial),
              err,
              "清空颜色调整失败",
            );
            if (!settlement.active || settlement.committed || settlement.unknown) return;
            const fallback = _get().originalPreviewUrl;
            set({
              ...clearRollbackState,
              previewImageUrl: clearRollbackState.previewImageUrl ?? fallback,
              previewBaseImageUrl:
                clearRollbackState.previewBaseImageUrl ?? fallback,
              replacePreviewLoading: false,
              error: visibleConverterError(err, "清空颜色调整失败"),
            });
          });
      } else {
        const originalUrl = state.originalPreviewUrl;
        // Local (session-less) flow: the first set() above already pushed the
        // pre-clear map onto remapHistory so "clear" itself stays undoable.
        // Only restore the local preview URL here — do not touch the history.
        // 本地（无 session）流程：上面的第一次 set 已把清空前快照推入
        // remapHistory，使"清空"可撤销；这里只恢复本地预览 URL，不动历史。
        set({
          previewImageUrl: originalUrl,
          previewBaseImageUrl: originalUrl,
          replacePreviewLoading: false,
        });
      }
    }, { blocked: () => Promise.resolve(), localEditor: true }),

    // --- 浮雕高度 ---
    updateColorHeight: documentCommand((hex: string, heightMm: number) => {
      set((state) => ({
        color_height_map: { ...state.color_height_map, [hex]: heightMm },
      }));
    }),

    applyAutoHeight: documentCommand((mode: "darker-higher" | "lighter-higher") => {
      const state = _get();
      const heightMap = computeAutoHeightMap(
        state.palette,
        mode,
        state.heightmap_max_height,
      );
      set({ color_height_map: heightMap });
    }),

    setAutoHeightMode: documentCommand((mode: AutoHeightMode) =>
      set((state) => ({
        autoHeightMode: mode,
        ...(mode === "use-heightmap" && state.autoHeightMode !== "use-heightmap"
          ? clearedHeightmapUploadState()
          : {}),
      }))),

    // --- 高度图 ---
    setHeightmapFile: documentCommand((file: File | null) =>
      set({
        ...clearedHeightmapUploadState(),
        heightmapFile: file,
        isLoading: false,
      })),

    uploadHeightmap: async () => {
      const state = _get();
      if (!state.heightmapFile || !state.sessionId) {
        set({
          ...clearedHeightmapUploadState(),
          error: "请先上传高度图文件并完成预览",
        });
        return;
      }
      const requestedSessionId = state.sessionId;
      const requestedHeightmapFile = state.heightmapFile;
      const isCurrentHeightmapUpload = () => {
        const currentState = _get();
        return (
          currentState.sessionId === requestedSessionId &&
          currentState.heightmapFile === requestedHeightmapFile
        );
      };
      set({ isLoading: true, error: null });
      try {
        const response = await apiUploadHeightmap(
          requestedHeightmapFile,
          requestedSessionId,
          state.heightmap_max_height,
        );
        if (!isCurrentHeightmapUpload()) {
          return;
        }
        const thumbnailUrl = `${response.thumbnail_url}`;
        set({
          isLoading: false,
          heightmapThumbnailUrl: thumbnailUrl,
          color_height_map: response.color_height_map,
          heightmapUploadSessionId: requestedSessionId,
        });
      } catch (err) {
        if (!isCurrentHeightmapUpload()) {
          return;
        }
        set({
          ...clearedHeightmapUploadState(),
          isLoading: false,
          error: visibleConverterError(err, "Heightmap upload failed"),
        });
      }
    },

    // --- 模型边界 ---
    setModelBounds: (bounds: ConverterState["modelBounds"]) =>
      set((state) => ({
        modelBounds: bounds,
        ...(state.fridge_magnets.length > 0
          ? buildFridgeMagnetState(
              {
                ...state,
                modelBounds: bounds,
              },
              {
                fridge_magnets: state.fridge_magnets,
              },
            )
          : {}),
      })),

    fetchBedSizes: async () => {
      set({ bedSizesLoading: true });
      try {
        const response = await apiFetchBedSizes();
        const beds = response.beds;

        const settingsPrinterModel = resolveConverterSettings(_get(), useSettingsStore.getState()).printerModel;
        const printerBed = beds.find(
          (bed) => bed.printer_id === settingsPrinterModel,
        );

        set({
          bedSizes: beds,
          bedSizesLoading: false,
          ...(printerBed ? { bed_label: printerBed.label } : {}),
        });
        if (printerBed) _get().setBedLabel(printerBed.label);
      } catch (err) {
        set({
          bedSizesLoading: false,
          error: visibleConverterError(err, "热床尺寸列表加载失败"),
        });
      }
    },

    // --- API 操作 ---
    uploadLut: async (file: File) => {
      set({ lutListLoading: true, error: null });
      try {
        const res = await apiUploadLut(file);
        // 上传成功后通过 catalog 刷新 legacy/native 共享状态，再选中新 LUT
        await Promise.all([
          _get().fetchLutCatalog(),
          _get().fetchLegacyCatalog(),
        ]);
        _get().setLutName(res.name);
      } catch (err) {
        set({
          error: visibleConverterError(err, "LUT 上传失败"),
        });
      } finally {
        set({ lutListLoading: false });
      }
    },

    fetchLutList: async (options = {}) => {
      set({ lutListLoading: true });
      try {
        const response = await apiFetchLutList(options);
        let luts = response.luts.map(normalizeLutColorMode);
        const bound = _get();
        if (boundProjectResources(bound).lut) {
          const names = new Set([bound.lut_name, ...bound.lut_names]);
          luts = [...luts.filter((lut) => !names.has(lut.name)), ...bound.lutListFull.filter((lut) => names.has(lut.name))];
          set({ lutList: luts.map((lut) => lut.name), lutListFull: luts, lutListLoading: false });
          return;
        }
        const updates: Partial<ConverterState> = {
          lutList: luts.map((l) => l.name),
          lutListFull: luts,
          lutListLoading: false,
        };

        // If a remembered LUT exists, apply its color_mode.
        const currentState = _get();
        const selectionState = {
          ...currentState,
          lutListFull: luts,
        };
        Object.assign(
          updates,
          buildLegacySelectionAvailabilityUpdates(
            selectionState,
            luts.map((lut) => lut.name),
          ),
        );
        const remembered = updates.lut_name ?? currentState.lut_name;
        if (remembered) {
          const info = luts.find((l) => l.name === remembered);
          if (info && info.color_mode) {
            updates.color_mode = normalizePublicColorMode(info.color_mode);
          }
        }
        if (updates.lut_name === "") {
          try {
            localStorage.removeItem("lumina_lastLut");
          } catch {
            /* noop */
          }
        }

        set(updates);
      } catch (err) {
        set({
          lutListLoading: false,
          error: visibleConverterError(err, "LUT 列表加载失败"),
        });
      }
    },

    fetchLutCatalog: async (signal?: AbortSignal) => {
      const requestToken = ++_lutCatalogRequestToken;
      set({ nativeBrandGroupsLoading: true });
      try {
        const response = await apiFetchLutCatalog(signal);
        if (
          signal?.aborted ||
          requestToken !== _lutCatalogRequestToken
        ) {
          if (requestToken === _lutCatalogRequestToken) {
            set({ nativeBrandGroupsLoading: false });
          }
          return;
        }
        const legacyGroups = normalizeLutGroups(response.legacy_groups ?? []);
        const groups = filterNativeBrandGroups(
          normalizeNativeBrandGroups(response.native_brand_groups ?? []),
        );
        const legacyLuts = legacyGroups.flatMap((group) => group.items ?? []);
        const currentState = _get();
        if (boundProjectResources(currentState).lut) {
          // Refresh the library without replacing a project's independent source.
          const boundNames = new Set([currentState.lut_name, ...currentState.lut_names]);
          const boundBrand = currentState.nativeBrandGroups.find((brand) => brand.brand_key === currentState.selectedNativeBrandKey);
          set({
            lutList: [...new Set([...legacyLuts.map((lut) => lut.name), ...boundNames])],
            lutListFull: [...legacyLuts.filter((lut) => !boundNames.has(lut.name)), ...currentState.lutListFull.filter((lut) => boundNames.has(lut.name))],
            nativeBrandGroups: boundBrand ? [...groups.filter((brand) => brand.brand_key !== boundBrand.brand_key), boundBrand] : groups,
            nativeBrandGroupsLoading: false,
          });
          return;
        }
        const updates: Partial<ConverterState> = {
          lutList: legacyLuts.map((lut) => lut.name),
          lutListFull: legacyLuts,
          nativeBrandGroups: groups,
          nativeBrandGroupsLoading: false,
        };
        const remembered = currentState.lut_name;
        const selectionState = {
          ...currentState,
          lutListFull: legacyLuts,
        };
        Object.assign(
          updates,
          buildLegacySelectionAvailabilityUpdates(
            selectionState,
            legacyLuts.map((lut) => lut.name),
          ),
        );
        if (remembered) {
          const activeName = updates.lut_name ?? remembered;
          const info = legacyLuts.find((lut) => lut.name === activeName);
          if (info && info.color_mode) {
            updates.color_mode = normalizePublicColorMode(info.color_mode);
          }
        }
        if (updates.lut_name === "") {
          try {
            localStorage.removeItem("lumina_lastLut");
          } catch {
            /* noop */
          }
        }
        const selection =
          currentState.source_version === "native"
            ? resolveNativeBrandSelection({
                nativeBrandGroups: groups,
                selectedNativeBrandKey: currentState.selectedNativeBrandKey,
                selectedNativeDbNames: currentState.selectedNativeDbNames,
                color_layers: currentState.color_layers,
                layer_height_mm: currentState.layer_height_mm,
              })
            : null;
        const fallbackBrand = selection?.brand ?? groups[0] ?? null;
        const preferredMode =
          selection?.supported_mode ??
          resolvePreferredSupportedMode(fallbackBrand?.supported_modes ?? []);
        set({
          ...updates,
          ...(currentState.source_version === "native" && fallbackBrand
            ? {
                selectedNativeBrandKey: fallbackBrand.brand_key,
                selectedNativeDbNames:
                  selection?.db_names ??
                  getNativeDbNamesForGroup(fallbackBrand),
                color_layers: preferredMode?.color_layers ?? null,
                layer_height_mm: preferredMode?.layer_height_mm ?? null,
                ...buildNativeModelState(fallbackBrand, currentState),
              }
            : {}),
        });
      } catch (err) {
        if (
          signal?.aborted ||
          requestToken !== _lutCatalogRequestToken
        ) {
          if (requestToken === _lutCatalogRequestToken) {
            set({ nativeBrandGroupsLoading: false });
          }
          return;
        }
        set({
          nativeBrandGroupsLoading: false,
          error: visibleConverterError(err, "品牌目录加载失败"),
        });
      }
    },

    fetchLegacyCatalog: async (options = {}) => {
      set({ legacyCatalogLoading: true, error: null });
      try {
        const response = await apiFetchLutDetailsCatalog(options);
        const groups = normalizeLutGroups(response.groups ?? []);
        const currentState = _get();
        const index = buildLutCatalogIndex(groups);
        const currentLutInfo = currentState.lut_name
          ? currentState.lutListFull.find(
              (l) => l.name === currentState.lut_name,
            )
          : null;
        const location = currentLutInfo
          ? findLutLocationByPath(index, currentLutInfo.path)
          : null;
        const selectedManufacturer =
          location?.manufacturer ??
          (currentState.selectedLegacyManufacturer &&
          index.byManufacturer[currentState.selectedLegacyManufacturer]
            ? currentState.selectedLegacyManufacturer
            : "");
        set({
          legacyCatalogGroups: groups,
          legacyCatalogLoading: false,
          selectedLegacyManufacturer: selectedManufacturer,
        });
      } catch (err) {
        set({ legacyCatalogLoading: false });
        _get().setError(visibleConverterError(err, "LUT 详情目录加载失败"));
      }
    },

    fetchLutColors: async (
      lutName: string,
      signal?: AbortSignal,
    ) => {
      const requestToken = ++_lutColorsRequestToken;
      const lutSessionId = boundProjectResources(_get()).lut ? _get().sessionId : null;
      if (boundProjectResources(_get()).lut && !_get().sessionId) {
        // A portable draft has no globally installed LUT. Its first preview
        // creates the private session from which the palette can be read.
        set({ lutColors: [], lutColorCards: [], lutColorsLutName: "", lutColorsSessionId: null, lutColorsLoading: false });
        return;
      }
      if (!lutName) {
        set({
          lutColors: [],
          lutColorCards: [],
          lutColorsLutName: "",
          lutColorsSessionId: null,
          lutColorsLoading: false,
        });
        return;
      }
      // 缓存命中检查：LUT 名称未变且已有数据时跳过请求
      if (lutName === _get().lutColorsLutName && lutSessionId === _get().lutColorsSessionId && _get().lutColors.length > 0) {
        set({ lutColorsLoading: false });
        return;
      }
      set({ lutColorsLoading: true, lutColors: [], lutColorCards: [], lutColorsLutName: "", lutColorsSessionId: null });
      try {
        const response = await apiFetchLutColors(lutName, signal, lutSessionId);
        if (
          signal?.aborted ||
          requestToken !== _lutColorsRequestToken
        ) {
          if (requestToken === _lutColorsRequestToken) {
            set({ lutColorsLoading: false });
          }
          return;
        }
        set({
          lutColors: response.colors,
          lutColorCards: response.cards ?? [],
          lutColorsLoading: false,
          lutColorsLutName: lutName,
          lutColorsSessionId: lutSessionId,
        });
      } catch (err) {
        if (
          signal?.aborted ||
          requestToken !== _lutColorsRequestToken
        ) {
          if (requestToken === _lutColorsRequestToken) {
            set({ lutColorsLoading: false });
          }
          return;
        }
        set({
          lutColorsLoading: false,
          error: lutErrorToVisibleMessage(err, "LUT 颜色加载失败"),
        });
      }
    },

    fetchMaterialSuggestions: async (targetHex: string) => {
      // Require material-archive mode with a non-empty palette.
      // Caller (MaterialColorPicker) ensures this, but we double-check.
      // 调用方应保证处于材料档案模式且已选耗材，这里再校验一次。
      const state = _get();
      if (state.source_version !== "material") {
        set({
          materialSuggestionsError:
            "fetchMaterialSuggestions requires source_version='material'",
        });
        return;
      }
      const dirNames = state.selectedMaterialDirNames ?? [];
      if (dirNames.length === 0) {
        set({
          materialSuggestions: null,
          materialSuggestionsTargetHex: targetHex,
          materialSuggestionsError:
            "No materials selected; cannot suggest achievable colors",
        });
        return;
      }
      const cleaned = (targetHex || "").trim();
      if (!cleaned) {
        set({
          materialSuggestions: null,
          materialSuggestionsTargetHex: null,
          materialSuggestionsError: null,
        });
        return;
      }

      // Abort any in-flight suggestion request before launching a new one.
      // 发起新请求前先取消上一次未完成的请求。
      _materialSuggestAbortController?.abort();
      _materialSuggestAbortController = new AbortController();
      const { signal } = _materialSuggestAbortController;
      const requestToken = ++_materialSuggestRequestToken;
      const suggestionLayerCount = resolveMaterialPrintLayerCount(state);
      const settingsState = resolveConverterSettings(state, useSettingsStore.getState());
      const gridResolutionOverride =
        settingsState.enableSolverCacheGridSelection
          ? settingsState.solverCacheGridResolution
          : undefined;

      const cacheKey = (boundProjectResources(state).materials ? `${state.sessionId}:` : "") + _materialSuggestCacheKey({
        directoryNames: dirNames,
        layerCount: suggestionLayerCount,
        layerHeightMm: state.materialLayerHeightMm,
        substrate: "white",
        gridResolution: gridResolutionOverride,
        targetHex: cleaned,
      });
      const cached = _materialSuggestCache.get(cacheKey);
      if (cached) {
        // Re-insert to refresh LRU recency.
        _materialSuggestCache.delete(cacheKey);
        _materialSuggestCache.set(cacheKey, cached);
        set({
          materialSuggestions: cached,
          materialSuggestionsLoading: false,
          materialSuggestionsTargetHex: cleaned,
          materialSuggestionsError: null,
        });
        return;
      }

      set({
        materialSuggestionsLoading: true,
        materialSuggestionsTargetHex: cleaned,
        materialSuggestionsError: null,
      });
      // Forward the opt-in grid resolution so the suggest-colors lookup
      // hits the same on-disk cache the user built through the dialog;
      // otherwise we would silently fall back to a slower MITM run.
      try {
        const response = await fetchMaterialColorSuggestions(
          {
            materialDirectoryNames: dirNames,
            layerCount: suggestionLayerCount,
            layerHeightMm: state.materialLayerHeightMm,
            substrate: "white",
          },
          cleaned,
          { signal, gridResolution: gridResolutionOverride },
          ...(boundProjectResources(state).materials ? [state.sessionId] as const : []),
        );
        const currentSettingsState = resolveConverterSettings(_get(), useSettingsStore.getState());
        const currentGridResolution =
          currentSettingsState.enableSolverCacheGridSelection
            ? currentSettingsState.solverCacheGridResolution
            : undefined;
        if (
          signal.aborted ||
          requestToken !== _materialSuggestRequestToken
        ) {
          return;
        }
        if (currentGridResolution !== gridResolutionOverride) {
          set({ materialSuggestionsLoading: false });
          return;
        }
        // Stash into LRU, evicting oldest when over limit.
        // 写入 LRU，超额时淘汰最早项。
        _materialSuggestCache.set(cacheKey, response);
        while (_materialSuggestCache.size > MATERIAL_SUGGEST_LRU_LIMIT) {
          const oldest = _materialSuggestCache.keys().next().value;
          if (oldest == null) break;
          _materialSuggestCache.delete(oldest);
        }
        set({
          materialSuggestions: response,
          materialSuggestionsLoading: false,
          materialSuggestionsTargetHex: cleaned,
          materialSuggestionsError: null,
        });
      } catch (err) {
        if (
          signal.aborted ||
          requestToken !== _materialSuggestRequestToken
        ) {
          return; // Superseded by a newer request.
        }
        set({
          materialSuggestions: null,
          materialSuggestionsTargetHex: cleaned,
          materialSuggestionsLoading: false,
          materialSuggestionsError: visibleConverterError(
            err,
            "Material color suggestion request failed",
          ),
        });
      }
    },

    clearMaterialSuggestions: () => {
      set(_cancelMaterialSuggestionWork());
    },

    fetchGradientGroups: async (sessionId: string) => {
      if (!sessionId) {
        return;
      }
      // Reuse cached groups when the session hasn't changed — the backend
      // recomputes synchronously on every new preview, so a matching session
      // id means the payload is still fresh.
      // 同一 session 的结果是稳定的，命中直接复用。
      const current = _get();
      if (
        current.gradientGroupsSessionId === sessionId &&
        current.gradientGroups !== null
      ) {
        return;
      }
      _gradientGroupsAbortController?.abort();
      _gradientGroupsAbortController = new AbortController();
      const { signal } = _gradientGroupsAbortController;

      set({
        gradientGroupsLoading: true,
        gradientGroupsError: null,
      });
      try {
        const response = await apiFetchGradientGroups(sessionId, signal);
        // Abandon the response if the user moved on to another session
        // between the request start and the response arrival.
        // 期间换了 session 则丢弃这次结果。
        if (signal.aborted || _get().sessionId !== sessionId) {
          return;
        }
        set({
          gradientGroups: response.status === "ok" ? response.groups : [],
          gradientGroupsLoading: false,
          gradientGroupsError: null,
          gradientGroupsSessionId: sessionId,
        });
      } catch (err) {
        if (signal.aborted || _get().sessionId !== sessionId) {
          return; // Superseded by a newer fetch or an explicit clear.
        }
        set({
          gradientGroupsLoading: false,
          gradientGroupsError: visibleConverterError(
            err,
            "Failed to load gradient groups",
          ),
        });
      }
    },

    clearGradientGroups: () => {
      _gradientGroupsAbortController?.abort();
      _gradientGroupsAbortController = null;
      set({
        gradientGroups: null,
        gradientGroupsLoading: false,
        gradientGroupsError: null,
        gradientGroupsSessionId: null,
        gradientSelection: null,
      });
    },

    selectGradientGroupColors: (
      hexes: string[],
      source?: GradientSelectionSource,
    ) => {
      const normalised = Array.from(
        new Set(hexes.map((h) => h.replace(/^#/, "").toLowerCase())),
      );
      if (normalised.length === 0) {
        return;
      }
      const state = _get();
      if (state.sessionId) {
        state.setSelectionTool("same-color");
        void state.applySelectionMutation(
          source?.kind === "region"
            ? {
                operation: "gradient-region-set",
                gradientGroupIndex: source.groupIndex,
                gradientRegionIndex: source.regionIndex,
                selectionSource: source,
              }
            : { operation: "colors-set", colorHexes: normalised, selectionSource: source },
        );
        return;
      }
      set({
        selectionMode: "select-all",
        selectedColors: new Set(normalised),
        selectedColor: null,
        regionData: null,
        selectedRegions: [],
        previewImageUrl: getPreviewBaseUrl(state),
        gradientSelection: source ?? null,
      });
    },

    applyGradientReplaceForGroup: async (
      groupIndex: number,
      regionIndex?: number,
    ) => {
      const initialState = _get();
      const sid = initialState.sessionId;
      if (!sid) return;
      const pendingSelection = waitForSelectionMutation(sid);
      if (pendingSelection && !(await pendingSelection)) return;
      const contentReservation = acquireContentCommitTurn(sid);
      if (
        !contentReservation.readyImmediately &&
        !(await contentReservation.ready)
      ) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const state = _get();
      if (state.sessionId !== sid) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const groups = state.gradientGroups;
      if (!groups || groups.length === 0) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const group = groups.find((g) => g.group_index === groupIndex);
      if (!group) {
        releaseContentCommit(contentReservation, false);
        return;
      }

      const rep = group.representative_hex.replace(/^#/, "").toLowerCase();
      if (!rep) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const previewCommit = captureReplacementPreviewCommit(
        state,
        contentReservation,
      );

      // Use the spatially-scoped /region-replace endpoint so that only
      // pixels inside the gradient group (or single region) are repainted
      // with the representative colour. The old colorRemapMap approach
      // was a whole-image hex→hex remap that would pollute unrelated areas
      // sharing the same quantised hex — the "去海带纹 repaints the whole
      // body" bug.
      // 走空间受限的 /region-replace 端点，仅把组内（或单区域内）像素刷成
      // 代表色。旧方案 colorRemapMap 是全图 hex→hex，会误伤其它同色区域。
      const scope =
        regionIndex !== undefined
          ? { gradientGroupIndex: groupIndex, gradientRegionIndex: regionIndex }
          : { gradientGroupIndex: groupIndex };

      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiRegionReplace(
          sid,
          `#${rep}`,
          scope,
          undefined,
          previewCommit.operationId,
        );
        if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) {
          return;
        }
        const updates: Partial<ConverterState> = {
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          replacePreviewLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
          gradientSelection: null,
          selectedColors: new Set<string>(),
          selectedColor: null,
          regionData: null,
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
          ...dynamicMaterialResultState(response),
          ...historyFlagsFromResponse(response),
          ...selectionUpdatesFromResponse(_get(), sid, response.selection),
        };
        if (response.preview_glb_url) {
          updates.previewGlbUrl = normalizeResourceUrl(
            response.preview_glb_url,
          );
        }
        if (response.color_contours) {
          updates.colorContours = response.color_contours;
        }
        set((current) => ({
          ...updates,
          regionReplacementCount: current.regionReplacementCount + 1,
        }));
        _get()._pollAsyncGlb();
      } catch (err) {
        const settlement = await settleReplacementPreviewError(
          _get(),
          previewCommit,
          _get,
          (partial) => set(partial),
          err,
          "去海带纹替换失败",
        );
        if (!settlement.active || settlement.committed || settlement.unknown) return;
        set({
          replacePreviewLoading: false,
          error: visibleConverterError(err, "去海带纹替换失败"),
        });
      }
    },

    applyAutoGradientReplace: async () => {
      await commitColorRemap(_get, set, state => {
        const remap: Record<string, string> = {};
        for (const group of state.gradientGroups ?? []) {
          const representative = group.representative_hex.replace(/^#/, "").toLowerCase();
          for (const color of group.material_colours) {
            const source = color.hex.replace(/^#/, "").toLowerCase();
            if (source && source !== representative) remap[source] = representative;
          }
        }
        return Object.keys(remap).length ? { ...state.colorRemapMap, ...remap } : null;
      });
    },

    invalidatePreviewForAutoRefresh: () => {
      _cancelPreviewWork();

      set((current) => ({
        sessionId: null,
        isLoading: false,
        previewImageUrl: null,
        originalPreviewUrl: null,
        previewBaseImageUrl: null,
        previewGlbUrl: null,
        modelUrl: null,
        previewPerformanceTiming: null,
        generatePerformanceTiming: null,
        batchPreviewItems: [],
        threemfDiskPath: null,
        downloadUrl: null,
        replacePreviewLoading: false,
        preview_width_mm: null,
        preview_height_mm: null,
        preview_spacer_thick: null,
        previewPixelWidth: null,
        previewPixelHeight: null,
        modelBounds: null,
        gradientGroups: null,
        gradientGroupsLoading: false,
        gradientGroupsError: null,
        gradientGroupsSessionId: null,
        gradientSelection: null,
        selectedGradientRegions: [],
        previewAutoRefreshPending: true,
        previewRequestRevision: current.previewRequestRevision + 1,
        ...DEFAULT_LAYER_IMAGES_STATE,
        ...DEFAULT_PUZZLE_PREVIEW_STATE,
      }));
    },

    submitPreview: async () => {
      let state: ConverterState = _get();
      const imageFile = state.imageFile;
      if (!imageFile) {
        set({ error: "请先上传图片" });
        return;
      }
      const sourceSelection = resolveConverterSourceSelection(state);
      if (!sourceSelection.isReady) {
        set({
          error:
            state.source_version === "material"
              ? "请先选择耗材"
              : state.source_version === "native"
                ? "请先选择品牌和数据库"
                : "请先选择 LUT",
        });
        return;
      }
      if (
        state.modelSurfaceEnabled &&
        (
          !state.modelSurfaceModelFileId ||
          !state.modelSurfaceSelection ||
          !state.modelSurfaceFootprint
        )
      ) {
        set({ error: tRuntime("model_surface_error_select_first") });
        return;
      }

      // Cancel any in-flight preview request.
      if (_previewAbortController) {
        _previewAbortController.abort();
      }
      const requestController = new AbortController();
      _previewAbortController = requestController;
      const { signal } = requestController;
      const previewRequestRevision = state.previewRequestRevision;
      const isStalePreviewRequest = (): boolean => {
        const latest = _get();
        return (
          signal.aborted ||
          latest.previewRequestRevision !== previewRequestRevision
        );
      };

      _previewStartTime = performance.now();
      (window as LuminaWindow).__luminaPreviewStart = _previewStartTime;
      _startPreviewTimer();
      _previewClientLog("preview: click", {
        image: summarizeFileForLog(state.imageFile),
        source_version: state.source_version,
        target_width_mm: state.target_width_mm,
        color_mode: state.color_mode,
        modeling_mode: state.modeling_mode,
        quantize_colors: state.quantize_colors,
        high_precision_3d_preview: state.high_precision_3d_preview,
        enable_cleanup: state.enable_cleanup,
        hue_enable: state.hue_enable,
      });

      set({
        isLoading: true,
        error: null,
        hasManualPreview: true,
        previewAutoRefreshPending: false,
        previewSubmissionSequence: state.previewSubmissionSequence + 1,
        previewWarnings: [],
        // Keep export warnings with the retained download until it is replaced or invalidated.
        ...DEFAULT_LAYER_IMAGES_STATE,
        ...DEFAULT_PUZZLE_PREVIEW_STATE,
      });
      console.log("[DEBUG] submitPreview: cleared layerImages");
      let freshSessionId: string | null = null;
      try {
        // Capture the current confirmed editor, not the original import asset.
        // 重新预览前复用保存项目的确认屏障，保留后续编辑及其空间掩码。
        const project = state.sessionId
          ? await _get().prepareRecipeExport()
          : { state, editorFile: state.pendingEditorProject };
        if (isStalePreviewRequest()) return;
        state = project.state;
        const editorFile = project.editorFile;
        const editorGuard = capturePreviewCommitGuard(state, replacementPreviewEpoch, "preview");
        const selectionRevision = state.selectionDocument?.selection_revision;
        const requireCurrentEditor = (): void => {
          const current = _get();
          if (editorFile && state.sessionId && (
            !canCommitPreviewResponse(current, editorGuard, replacementPreviewEpoch)
            || current.selectionDocument?.selection_revision !== selectionRevision
            || current.contentCommitStatus === "pending"
            || current.contentCommitStatus === "unknown"
          )) {
            throw new Error(tRuntime("recipe_export_wait_edits"));
          }
        };
        const portableProjectColors = clonePortableProjectColorState(state);
        const remapReplacementRegions = colorRemapToReplacementRegions(
          state.colorRemapMap,
          state.palette,
        );
        const previewReplacementRegions = [
          ...portableProjectColors.replacement_regions,
          ...remapReplacementRegions,
        ];
        const shouldReplayGlobalReplacements = previewReplacementRegions.length > 0;
        const colorMode = normalizePublicColorMode(state.color_mode);
        const sourceParams =
          buildConversionSourceParams(state);
        if (!sourceParams) {
          _previewClientLog(
            "preview: invalid source",
            {
              source_version: state.source_version,
            },
            "warn",
          );
          set({
            isLoading: false,
            error: "请先选择品牌和数据库",
          });
          return;
        }
        const previewParams = buildPreviewParams(state, useSettingsStore.getState(), sourceParams, previewReplacementRegions);
        _logPreviewTimer("request sent");
        _previewClientLog("preview: request sent", {
          source_kind: sourceParams.source_kind,
          color_layers: previewParams.color_layers ?? null,
          layer_height_mm: previewParams.layer_height_mm ?? null,
          target_width_mm: previewParams.target_width_mm,
          color_mode: previewParams.color_mode,
          modeling_mode: previewParams.modeling_mode,
          quantize_colors: previewParams.quantize_colors,
          enable_outline: previewParams.enable_outline,
          outline_width: previewParams.outline_width,
        });
        const response = await apiConvertPreview(
          imageFile,
          previewParams,
          signal,
          { ...boundProjectResources(state), editor: editorFile },
        );
        freshSessionId = response.session_id;
        if (isStalePreviewRequest()) {
          return;
        }
        requireCurrentEditor();
        let restoredEditor: Awaited<ReturnType<typeof apiRestoreEditorProject>> | null = null;
        if (editorFile) {
          restoredEditor = await apiRestoreEditorProject(response.session_id, editorFile, createEditorOperationId());
        }
        if (isStalePreviewRequest()) {
          return;
        }
        requireCurrentEditor();
        if (restoredEditor && (restoredEditor.status !== "committed" || !restoredEditor.result?.preview_url)) {
          throw new Error(tRuntime("recipe_editor_restore_unconfirmed"));
        }
        const editorResult = restoredEditor?.result;
        // Apply the normal content-commit contract in the same publication as
        // the fresh session, so its stable 2D base cannot retain unedited raw pixels.
        const restoredEditorState = editorCommitResultStateFromResponse(
          { ...state, sessionId: response.session_id },
          response.session_id,
          restoredEditor?.operation,
          editorResult,
        );
        if (restoredEditor?.editor_content_revision !== undefined) {
          rememberConfirmedEditorContentRevision(response.session_id, restoredEditor.editor_content_revision);
        }
        _logPreviewTimer("response received");
        // 后端返回 JSON，preview_url 是相对路径如 /api/files/xxx
        const sourcePreviewUrl = normalizeResourceUrl(response.preview_url) ?? response.preview_url;
        const previewUrl = restoredEditorState.previewImageUrl ?? sourcePreviewUrl;
        const responseGlb = editorResult ? editorResult.preview_glb_url : response.preview_glb_url;
        const glbUrl = responseGlb
          ? normalizeResourceUrl(responseGlb)
          : null;
        const publishedPreview = previewResultState(state, response);
        const normalizedPalette = publishedPreview.palette ?? [];
        const autoReliefHeightMap = buildMissingAutoReliefHeightMap(
          state,
          normalizedPalette,
        );
        const resolvedColorLayers = sourceSelection.isMaterial
          ? resolveMaterialPrintLayerCount(state)
          : sourceSelection.source_kind === "native_bundle"
            ? (sourceSelection.color_layers ?? null)
            : state.color_layers;
        const resolvedLayerHeightMm = sourceSelection.isMaterial
          ? state.materialLayerHeightMm
          : sourceSelection.source_kind === "native_bundle"
            ? (sourceSelection.layer_height_mm ?? null)
            : state.layer_height_mm;
        const shouldResetHeightmapMapping =
          state.enable_relief && state.autoHeightMode === "use-heightmap";
        const shouldReuploadHeightmap =
          shouldResetHeightmapMapping && state.heightmapFile !== null;

        _previewClientLog("preview: response received", {
          session_id: response.session_id,
          preview_url: previewUrl,
          preview_glb_url: glbUrl,
          palette_count: normalizedPalette.length,
          warning_count: (response.warnings ?? []).length,
          dimensions: response.dimensions ?? null,
          source_kind: sourceParams.source_kind,
        });

        set({
          ...publishedPreview,
          previewImageUrl: previewUrl,
          originalPreviewUrl: sourcePreviewUrl,
          previewBaseImageUrl:
            normalizeResourceUrl(response.dimensions?.preview_raw_url) ??
            sourcePreviewUrl,
          ...(shouldResetHeightmapMapping
            ? clearedHeightmapUploadState()
            : autoReliefHeightMap
              ? { color_height_map: autoReliefHeightMap }
              : {}),
          previewGlbUrl: glbUrl,
          generatePerformanceTiming: null,
          colorRemapMap: shouldReplayGlobalReplacements
            ? state.colorRemapMap
            : {},
          remapHistory: shouldReplayGlobalReplacements
            ? state.remapHistory
            : [],
          remapRedoHistory: shouldReplayGlobalReplacements
            ? state.remapRedoHistory
            : [],
          historyCanUndo: false,
          historyCanRedo: false,
          historyBusy: false,
          replacement_regions: portableProjectColors.replacement_regions,
          recipe_overrides: [],
          pendingEditorProject: null,
          customRecipeHistory: portableProjectColors.customRecipeHistory,
          free_color_set: portableProjectColors.free_color_set,
          regionReplacementCount: 0,
          selectedColor: null,
          selectedColors: new Set<string>(),
          regionData: null,
          selectedRegions: [],
          selectionTool: "point",
          selectionMode: "multi-select",
          selectionDocument: null,
          pendingSelectionMutations: [],
          brushSizePx: state.brushSizePx,
          selectionBlinkEnabled: false,
          selectedGradientRegions: [],
          pendingReplacement: null,
          color_layers: resolvedColorLayers,
          layer_height_mm: resolvedLayerHeightMm,
          layerImages: [],
          layerImagesOpen: false,
          // Reset gradient-group cache so the panel shows loading while the
          // new session's groups are fetched below. Without this the UI
          // would briefly show stale groups from the previous preview.
          // 新预览就位后先清空渐变组缓存，避免面板短暂显示旧 session 的分组。
          gradientGroups: null,
          gradientGroupsLoading: false,
          gradientGroupsError: null,
          gradientGroupsSessionId: null,
          gradientSelection: null,
          ...restoredEditorState,
        });
        await _get().hydrateSelectionDocument();
        if (!editorResult && portableProjectColors.free_color_set.size > 0) {
          const freeColorRestoreSessionId = response.session_id;
          try {
            await queueFreeColorMutation(freeColorRestoreSessionId, async () => {
              if (_get().sessionId !== freeColorRestoreSessionId) return;
              const restoredFreeColors = await apiMutateFreeColors(
                freeColorRestoreSessionId,
                "replace",
                Array.from(portableProjectColors.free_color_set),
              );
              if (isStalePreviewRequest()) return;
              if (_get().sessionId !== freeColorRestoreSessionId) return;
              set({
                free_color_set: new Set(restoredFreeColors.free_color_set),
                historyCanUndo: restoredFreeColors.can_undo,
                historyCanRedo: restoredFreeColors.can_redo,
              });
            });
            if (isStalePreviewRequest()) return;
            if (_get().sessionId !== freeColorRestoreSessionId) return;
          } catch (err) {
            if (isStalePreviewRequest()) return;
            if (_get().sessionId !== freeColorRestoreSessionId) return;
            set({
              error: visibleConverterError(
                err,
                "Free color restore failed",
              ),
            });
            return;
          }
        }
        let heightmapReuploadFailed = false;
        if (
          shouldReuploadHeightmap &&
          _get().sessionId === response.session_id
        ) {
          await _get().uploadHeightmap();
          const latestState = _get();
          if (
            isStalePreviewRequest() ||
            latestState.sessionId !== response.session_id
          ) {
            return;
          }
          heightmapReuploadFailed = Boolean(latestState.error);
        }
        if (!glbUrl) {
          _get()._pollAsyncGlb();
        }
        // Automatic colour edits belong to this preview request. Reading the
        // groups elsewhere must never repaint an already confirmed preview.
        const previewSessionId = response.session_id;
        if (sourceSelection.isMaterial && useSettingsStore.getState().autoReplaceGradientBanding) {
          await _get().fetchGradientGroups(previewSessionId);
          if (isStalePreviewRequest() || _get().sessionId !== previewSessionId) return;
          if (_get().gradientGroupsError) {
            set({ error: _get().gradientGroupsError });
            return;
          }
          if (useSettingsStore.getState().autoReplaceGradientBanding) {
            await _get().applyAutoGradientReplace();
            if (isStalePreviewRequest() || _get().sessionId !== previewSessionId) return;
            if (_get().error || _get().contentCommitStatus === "unknown") return;
          }
        } else {
          void _get().fetchGradientGroups(previewSessionId);
        }
        set({ isLoading: false });
        console.log(
          "[DEBUG] submitPreview success: cleared layerImages for new sessionId",
        );
        _logPreviewTimer("UI unlocked (isLoading=false, preview state set)");
        _previewClientLog("preview: UI unlocked", {
          session_id: response.session_id,
          preview_url: previewUrl,
          preview_glb_url: glbUrl,
          preview_pixel_width: response.dimensions?.width ?? null,
          preview_pixel_height: response.dimensions?.height ?? null,
          warning_count: (response.warnings ?? []).length,
        });
        trackLuminaEvent("lumina_converter_preview_done", {
          source_version: state.source_version,
          source_kind: sourceParams.source_kind,
          color_mode: colorMode,
          modeling_mode: state.modeling_mode,
          elapsed_ms: getElapsedMsSince(_previewStartTime),
          warning_count: (response.warnings ?? []).length,
          palette_count: normalizedPalette.length,
        });
        if (!heightmapReuploadFailed) {
          notifyCompletion("preview");
        }
        // 预览绑定会话后，拉取会话所绑定 LUT 的通道调色板，便于自定义配方编辑器
        // 在材料档案 / 原生打包流程里也能显示按通道顺序的耗材列表。
        // After the preview binds a session, refresh the channel palette for
        // the custom recipe editor so material-archive / native-bundle flows
        // also see the per-channel material list, not just legacy named LUTs.
        void apiFetchSessionLutInfo(previewSessionId)
          .then((info) => {
            // Only apply if the user hasn't moved on to another session.
            if (_get().sessionId === previewSessionId) {
              set({ selectedLutInfo: normalizeLutColorMode(info) });
            }
          })
          .catch(() => {
            // Best-effort: if the session hasn't been bound yet or the
            // endpoint errors, leave selectedLutInfo untouched.
          });
        if (boundProjectResources(_get()).lut) void _get().fetchLutColors(_get().lut_name);
      } catch (err) {
        if (isStalePreviewRequest()) {
          return;
        }
        // Ignore aborted requests (user started a new preview)
        if (err instanceof Error && err.name === "CanceledError") {
          _previewClientLog(
            "preview: canceled",
            summarizeErrorForLog(err),
            "warn",
          );
          return;
        }
        set({
          isLoading: false,
          error: visibleConverterError(err, "预览失败"),
        });
        trackLuminaEvent("lumina_converter_preview_failed", {
          source_version: state.source_version,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          elapsed_ms: getElapsedMsSince(_previewStartTime),
          error_type: getErrorType(err),
        });
        _previewClientLog(
          "preview: failed",
          summarizeErrorForLog(err),
          "error",
        );
      } finally {
        if (freshSessionId && _get().sessionId !== freshSessionId) {
          void closeSession(freshSessionId);
        }
        if (_previewAbortController === requestController) {
          if (!isStalePreviewRequest() && (!freshSessionId || _get().sessionId === freshSessionId)) {
            set({ isLoading: false });
          }
          _previewAbortController = null;
          _endPreviewTimer();
        }
      }
    },

    reconcileUnknownContentCommit: async () => {
      await reconcileUnknownContentCommit(_get, (partial) => set(partial));
    },

    // --- 裁剪 ---
    setEnableCrop: (enabled: boolean) => {
      set({ enableCrop: enabled });
      try {
        localStorage.setItem("lumina_enableCrop", String(enabled));
      } catch {
        // localStorage unavailable, ignore
      }
    },

    setCropModalOpen: (open: boolean) => set({ cropModalOpen: open }),

    submitCrop: documentCommand(async (x: number, y: number, width: number, height: number, rotation: 0 | ImageRotationDegrees = 0) => {
      const state = _get();
      if (!state.imageFile) {
        set({ error: "No image file to crop" });
        return;
      }
      set({ isCropping: true, error: null });
      try {
        // Keep rotation as a draft until the entire crop succeeds.
        const cropSource = rotation && state.imagePreviewUrl
          ? await rotateImageFile(state.imageFile, state.imagePreviewUrl, rotation)
          : state.imageFile;
        const response = await apiCropImage(
          cropSource,
          x,
          y,
          width,
          height,
        );
        const croppedFullUrl = `${response.cropped_url}`;

        // Fetch cropped image as Blob to create a new File
        const blob = await downloadResourceBlob(croppedFullUrl);
        const sourceBaseName = state.imageFile.name.replace(/\.[^.]+$/, "") || "image";
        const croppedFile = new File([blob], `${sourceBaseName}_cropped.png`, {
          type: "image/png",
        });
        rememberDerivedImageSource(croppedFile, state.imageFile);

        const currentState = _get();
        if (currentState.imageFile !== state.imageFile) {
          set({ isCropping: false });
          return;
        }
        _cancelPreviewWork();

        // Revoke previous preview URL
        const prev = currentState.imagePreviewUrl;
        if (prev) URL.revokeObjectURL(prev);

        const newPreviewUrl = URL.createObjectURL(croppedFile);

        // Update aspect ratio from cropped dimensions
        const ratio = response.width / response.height;

        set({
          imageFile: croppedFile,
          imagePreviewUrl: newPreviewUrl,
          ...buildImageAspectRatioState({ ...currentState, aspectRatio: null }, ratio),
          workshopSource: null,
          ...buildPreviewSessionResetState(currentState),
          cropModalOpen: false,
          isCropping: false,
        });
      } catch (err) {
        set({
          isCropping: false,
          error: visibleConverterError(err, "Crop failed"),
        });
      }
    }, { blocked: () => Promise.resolve() }),

    // --- 自动检测颜色 ---
    autoDetectColors: documentCommand(async () => {
      const state = _get();
      if (!state.imageFile) {
        set({ error: "请先上传图片" });
        return;
      }
      set({ autoDetectColorsLoading: true });
      try {
        const result = await apiAutoDetectColors(
          state.imageFile,
          state.target_width_mm,
        );
        set({
          quantize_colors: clampValue(
            result.recommended,
            8,
            _get().quantize_colors_unlocked ? 8192 : 256,
          ),
          autoDetectColorsLoading: false,
          threemfDiskPath: null,
          downloadUrl: null,
        });
      } catch (err) {
        set({
          autoDetectColorsLoading: false,
          error: visibleConverterError(err, "Auto color detection failed"),
        });
      }
    }, { blocked: () => Promise.resolve() }),

    // --- 批量模式 ---
    addBatchFiles: documentCommand((files: File[]) => {
      const valid = files.filter((f) => isValidImageType(f.type, f.name));
      if (valid.length === 0) return;
      restoreConversionDefaultsForNewSource();
      set((state) => ({
        batchFiles: [...state.batchFiles, ...valid],
        workshopSource: null,
      }));
    }),

    removeBatchFile: documentCommand((index: number) => {
      const state = _get();
      const remaining = state.batchFiles.filter((_, i) => i !== index);
      _cancelPreviewWork();
      const nextPreviewRevision = state.previewRequestRevision + 1;

      if (remaining.length === 1) {
        // Auto-downgrade: move last file to imageFile, exit BatchMode
        const lastFile = remaining[0];
        if (isRawFileConverter(lastFile)) {
          set({
            batchFiles: [],
            imageFile: lastFile,
            imagePreviewUrl: null,
            aspectRatio: null,
            workshopSource: null,
            batchMode: false,
            hasManualPreview: false,
            previewAutoRefreshPending: false,
            previewRequestRevision: nextPreviewRevision,
          });
          uploadImagePreview(lastFile)
            .then(({ preview_url, width, height }) => {
              if (_get().imageFile !== lastFile || _get().imagePreviewUrl !== null) {
                return;
              }
              set({
                imagePreviewUrl: preview_url,
                ...buildImageAspectRatioState(_get(), width / height),
                error: null,
              });
            })
            .catch((err) => {
              if (_get().imageFile !== lastFile || _get().imagePreviewUrl !== null) {
                return;
              }
              set({ error: rawPreviewFailureMessage(err) });
            });
        } else {
          const previewUrl = URL.createObjectURL(lastFile);
          const img = new Image();
          img.onload = () => {
            if (
              _get().imageFile !== lastFile ||
              _get().imagePreviewUrl !== previewUrl
            ) {
              return;
            }
            set(buildImageAspectRatioState(_get(), img.naturalWidth / img.naturalHeight));
          };
          img.src = previewUrl;

          set({
            batchFiles: [],
            imageFile: lastFile,
            imagePreviewUrl: previewUrl,
            aspectRatio: null,
            workshopSource: null,
            batchMode: false,
            hasManualPreview: false,
            previewAutoRefreshPending: false,
            previewRequestRevision: nextPreviewRevision,
          });
        }
      } else if (remaining.length === 0) {
        // All files removed: clear all image state
        const prev = state.imagePreviewUrl;
        if (prev) URL.revokeObjectURL(prev);

        set({
          batchFiles: [],
          imageFile: null,
          imagePreviewUrl: null,
          aspectRatio: null,
          workshopSource: null,
          previewImageUrl: null,
          originalPreviewUrl: null,
          previewBaseImageUrl: null,
          sessionId: null,
          previewGlbUrl: null,
          isLoading: false,
          previewPerformanceTiming: null,
          generatePerformanceTiming: null,
          batchPreviewItems: [],
          ...EMPTY_LUT_MATCH_STATE,
          selectedColor: null,
          selectedColors: new Set<string>(),
          regionData: null,
          selectedRegions: [],
          batchMode: false,
          batchResult: null,
          hasManualPreview: false,
          previewAutoRefreshPending: false,
          previewRequestRevision: nextPreviewRevision,
        });
      } else {
        // Still in BatchMode with multiple files
        set({
          batchFiles: remaining,
          workshopSource: null,
          batchResult: null,
          hasManualPreview: false,
          previewAutoRefreshPending: false,
          previewRequestRevision: nextPreviewRevision,
        });
      }
    }),

    clearBatchFiles: documentCommand(() => {
      const state = _get();
      _cancelPreviewWork();
      set({
        batchFiles: [],
        workshopSource: null,
        batchResult: null,
        ...EMPTY_LUT_MATCH_STATE,
        puzzleEnabled: false,
        threemfDiskPath: null,
        downloadUrl: null,
        batchPreviewItems: [],
        modelUrl: null,
        previewGlbUrl: null,
        previewPerformanceTiming: null,
        generatePerformanceTiming: null,
        previewWarnings: [],
        largeFormatWarnings: [],
        largeFormatFailedTiles: [],
        hasManualPreview: false,
        previewAutoRefreshPending: false,
        previewRequestRevision: state.previewRequestRevision + 1,
        ...DEFAULT_PUZZLE_PREVIEW_STATE,
      });
    }),

    handleFilesSelect: documentCommand((files: File[]) => {
      // Filter out falsy values and invalid formats
      const validFiles = files.filter(
        (f) => f && isValidImageType(f.type, f.name),
      );
      if (validFiles.length === 0) return;

      const state = _get();
      _cancelPreviewWork();
      const inBatchMode = state.batchFiles.length > 0;
      const selectedFiles = [
        ...state.batchFiles,
        ...(state.imageFile ? [state.imageFile] : []),
        ...validFiles,
      ];
      const compatibleModelingMode =
        state.modeling_mode === ModelingModeEnum.VECTOR &&
        selectedFiles.some((file) => !isSvgFile(file))
          ? ModelingModeEnum.HIGH_FIDELITY
          : state.modeling_mode;

      // Already in BatchMode → append new files
      if (inBatchMode) {
        set({
          batchFiles: [...state.batchFiles, ...validFiles],
          workshopSource: null,
          modeling_mode: compatibleModelingMode,
          batchMode: true,
          batchResult: null,
          hasManualPreview: false,
          previewAutoRefreshPending: false,
          previewRequestRevision: state.previewRequestRevision + 1,
        });
        return;
      }

      if (validFiles.length === 1) {
        const singleFile = validFiles[0];
        const isSvg = isSvgFile(singleFile);
        const autoModelingMode = isSvg
          ? ModelingModeEnum.VECTOR
          : compatibleModelingMode;

        if (state.imageFile) {
          const prev = state.imagePreviewUrl;
          if (prev) URL.revokeObjectURL(prev);

          set({
            batchFiles: [state.imageFile, singleFile],
            imageFile: null,
            imagePreviewUrl: null,
            aspectRatio: null,
            workshopSource: null,
            previewImageUrl: null,
            previewBaseImageUrl: null,
            sessionId: null,
            isLoading: false,
            previewGlbUrl: null,
            modelUrl: null,
            previewPerformanceTiming: null,
            generatePerformanceTiming: null,
            batchPreviewItems: [],
            threemfDiskPath: null,
            downloadUrl: null,
            previewWarnings: [],
            largeFormatWarnings: [],
            largeFormatFailedTiles: [],
            ...EMPTY_LUT_MATCH_STATE,
            puzzleEnabled: false,
            ...DEFAULT_PUZZLE_PREVIEW_STATE,
            modeling_mode: compatibleModelingMode,
            batchMode: true,
            hasManualPreview: false,
            previewAutoRefreshPending: false,
            previewRequestRevision: state.previewRequestRevision + 1,
            layerImages: [],
            layerImagesOpen: false,
            batchResult: null,
          });
          return;
        }

        if (isRawFileConverter(singleFile)) {
          const prev = state.imagePreviewUrl;
          const nextPreviewRevision = state.previewRequestRevision + 1;
          if (prev && prev.startsWith("blob:")) URL.revokeObjectURL(prev);
          set({
            imageFile: singleFile,
            imagePreviewUrl: null,
            aspectRatio: null,
            workshopSource: null,
            previewImageUrl: null,
            previewBaseImageUrl: null,
            sessionId: null,
            isLoading: false,
            previewGlbUrl: null,
            modelUrl: null,
            previewPerformanceTiming: null,
            generatePerformanceTiming: null,
            batchPreviewItems: [],
            threemfDiskPath: null,
            downloadUrl: null,
            previewWarnings: [],
            largeFormatWarnings: [],
            largeFormatFailedTiles: [],
            ...EMPTY_LUT_MATCH_STATE,
            puzzleEnabled: false,
            ...DEFAULT_PUZZLE_PREVIEW_STATE,
            modeling_mode: compatibleModelingMode,
            batchMode: false,
            hasManualPreview: false,
            previewAutoRefreshPending: false,
            previewRequestRevision: nextPreviewRevision,
            cropModalOpen: state.enableCrop,
            layerImages: [],
            layerImagesOpen: false,
            batchResult: null,
          });
          uploadImagePreview(singleFile)
            .then(({ preview_url, width, height }) => {
              if (_get().imageFile !== singleFile || _get().imagePreviewUrl !== null) {
                return;
              }
              set({
                imagePreviewUrl: preview_url,
                ...buildImageAspectRatioState(_get(), width / height),
                error: null,
              });
            })
            .catch((err) => {
              if (_get().imageFile !== singleFile || _get().imagePreviewUrl !== null) {
                return;
              }
              set({ error: rawPreviewFailureMessage(err) });
            });
          return;
        }

        const previewUrl = URL.createObjectURL(singleFile);
        const nextPreviewRevision = state.previewRequestRevision + 1;
        const img = new Image();
        img.onload = () => {
          if (
            _get().imageFile !== singleFile ||
            _get().imagePreviewUrl !== previewUrl
          ) {
            return;
          }
          set(buildImageAspectRatioState(_get(), img.naturalWidth / img.naturalHeight));
        };
        img.src = previewUrl;

        set({
          imageFile: singleFile,
          imagePreviewUrl: previewUrl,
          aspectRatio: null,
          workshopSource: null,
          previewImageUrl: null,
          previewBaseImageUrl: null,
          sessionId: null,
          isLoading: false,
          previewGlbUrl: null,
          modelUrl: null,
          previewPerformanceTiming: null,
          generatePerformanceTiming: null,
          batchPreviewItems: [],
          threemfDiskPath: null,
          downloadUrl: null,
          previewWarnings: [],
          largeFormatWarnings: [],
          largeFormatFailedTiles: [],
          ...EMPTY_LUT_MATCH_STATE,
          puzzleEnabled: false,
          ...DEFAULT_PUZZLE_PREVIEW_STATE,
          batchMode: false,
          hasManualPreview: false,
          previewAutoRefreshPending: false,
          previewRequestRevision: nextPreviewRevision,
          cropModalOpen: isSvg ? false : state.enableCrop,
          layerImages: [],
          layerImagesOpen: false,
          batchResult: null,
          modeling_mode: autoModelingMode,
          ...(isSvg ? loadSvgHoleCompensationSettings() : { svg_hole_compensation_enabled: false }),
        });
        return;
      }

      // validFiles.length >= 2: enter BatchMode
      // Merge existing imageFile (if any) into batchFiles
      const allFiles = state.imageFile
        ? [state.imageFile, ...validFiles]
        : [...validFiles];
      const savedSvgSettings = loadSvgHoleCompensationSettings();

      // Revoke previous preview URL
      const prev = state.imagePreviewUrl;
      if (prev) URL.revokeObjectURL(prev);

      set({
        batchFiles: allFiles,
        imageFile: null,
        imagePreviewUrl: null,
        aspectRatio: null,
        workshopSource: null,
        previewImageUrl: null,
        previewBaseImageUrl: null,
        sessionId: null,
        isLoading: false,
        previewGlbUrl: null,
        modelUrl: null,
        previewPerformanceTiming: null,
        generatePerformanceTiming: null,
        batchPreviewItems: [],
        threemfDiskPath: null,
        downloadUrl: null,
        previewWarnings: [],
        largeFormatWarnings: [],
        largeFormatFailedTiles: [],
        ...EMPTY_LUT_MATCH_STATE,
        puzzleEnabled: false,
        ...DEFAULT_PUZZLE_PREVIEW_STATE,
        modeling_mode: compatibleModelingMode,
        ...savedSvgSettings,
        // Keep the selected modeling mode. Restore the remembered switch only
        // when the all-SVG batch actually enters vector mode.
        svg_hole_compensation_enabled: savedSvgSettings.svg_hole_compensation_enabled &&
          compatibleModelingMode === ModelingModeEnum.VECTOR && allFiles.every(isSvgFile),
        batchMode: true,
        hasManualPreview: false,
        previewAutoRefreshPending: false,
        previewRequestRevision: state.previewRequestRevision + 1,
        layerImages: [],
        layerImagesOpen: false,
        batchResult: null,
      });
    }),

    // --- 颜色替换：单次即时替换 ---
    submitSingleReplace: async (origHex: string, newHex: string) => {
      const initialState = _get();
      const sid = initialState.sessionId;
      if (!sid) return;
      const pendingSelection = waitForSelectionMutation(sid);
      if (pendingSelection && !(await pendingSelection)) return;
      const contentReservation = acquireContentCommitTurn(sid);
      if (
        !contentReservation.readyImmediately &&
        !(await contentReservation.ready)
      ) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const state = _get();
      if (state.sessionId !== sid) {
        releaseContentCommit(contentReservation, false);
        return;
      }
      const previewCommit = captureReplacementPreviewCommit(
        state,
        contentReservation,
      );
      set({ replacePreviewLoading: true, error: null });
      try {
        const response = await apiReplaceColor(
          state.sessionId,
          `#${origHex}`,
          `#${newHex}`,
          previewCommit.operationId,
        );
        if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) return;
        if (_get().sessionId !== sid) return;
        const updates: Partial<ConverterState> = {
          replacePreviewLoading: false,
          previewImageUrl: normalizeResourceUrl(response.preview_url),
          previewBaseImageUrl: normalizeResourceUrl(response.preview_url),
          ...INVALIDATE_LAYER_IMAGES_AFTER_REPLACE,
          ...dynamicMaterialResultState(response),
          ...historyFlagsFromResponse(response),
        };
        if (response.preview_3d_url) {
          updates.previewGlbUrl = normalizeResourceUrl(response.preview_3d_url);
        }
        set({
          ...updates,
          ...selectionUpdatesFromResponse(
            _get(),
            state.sessionId,
            response.selection,
          ),
        });
        _get()._pollAsyncGlb();
      } catch (err) {
        const settlement = await settleReplacementPreviewError(
          _get(),
          previewCommit,
          _get,
          (partial) => set(partial),
          err,
          "颜色替换失败",
        );
        if (!settlement.active || settlement.committed || settlement.unknown) return;
        if (_get().sessionId !== sid) return;
        // 回滚 colorRemapMap 到操作前状态
        const currentHistory = _get().remapHistory;
        if (currentHistory.length > 0) {
          const previousMap = currentHistory[currentHistory.length - 1];
          set({
            colorRemapMap: previousMap,
            remapHistory: currentHistory.slice(0, -1),
            replacePreviewLoading: false,
            error: visibleConverterError(err, "颜色替换失败"),
          });
        } else {
          set({
            replacePreviewLoading: false,
            error: visibleConverterError(err, "颜色替换失败"),
          });
        }
      }
    },

    // --- 颜色替换预览 ---
    submitReplacePreview: async () => {
      await commitColorRemap(_get, set);
    },

    // --- 完整流水线（preview → generate）---
    submitFullPipeline: async () => {
      const state = _get();

      // Refuse the unsupported pair before starting a preview that generation
      // would reject anyway.
      if (state.largeFormatEnabled && state.modelSurfaceEnabled) {
        set({ error: CONVERTER_ERROR_KEYS.largeFormatModelSurfaceConflict });
        return null;
      }

      // 步骤 1：如果没有 sessionId，先执行预览
      if (!state.sessionId) {
        await _get().submitPreview();
        // 检查预览是否成功
        const afterPreview = _get();
        if (!afterPreview.sessionId || afterPreview.error) {
          return null; // 预览失败，错误已由 submitPreview 设置
        }
      }

      // 步骤 2：执行生成
      return await _get().submitGenerate();
    },

    // --- 自由色 ---
    toggleFreeColor: documentCommand((hex: string) => {
      const state = _get();
      if (!state.sessionId) {
        const selectionColors = state.selectionDocument?.selected_color_hexes ?? [];
        const colors = selectionColors.length > 0 ? selectionColors : [hex];
        set((current) => {
          const next = new Set(current.free_color_set);
          for (const value of colors) {
            const normalized = value.replace(/^#/, "");
            if (next.has(normalized)) next.delete(normalized);
            else next.add(normalized);
          }
          return {
            free_color_set: next,
            threemfDiskPath: null,
            downloadUrl: null,
          };
        });
        return;
      }
      const sid = state.sessionId;
      // Capture only earlier gestures: a later gesture waits for this content
      // operation and must not become a dependency of it.
      const pendingSelection = waitForSelectionMutation(sid);
      void queueFreeColorMutation(sid, async () => {
        if (pendingSelection && !(await pendingSelection)) return;
        const pendingContentCommit = waitForContentCommits(sid);
        if (pendingContentCommit && !(await pendingContentCommit)) return;
        if (_get().sessionId !== sid) return;
        const latest = _get();
        const selectionColors = latest.selectionDocument?.selected_color_hexes ?? [];
        const colors = selectionColors.length > 0 ? selectionColors : [hex];
        const previewCommit = captureReplacementPreviewCommit(latest);
        set({
          contentCommitStatus: "pending",
          contentCommitOperationId: previewCommit.operationId,
          error: null,
        });
        try {
          const response = await apiMutateFreeColors(
            sid,
            "toggle",
            colors,
            previewCommit.operationId,
          );
          if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) return;
          if (_get().sessionId !== sid) return;
          set({
            free_color_set: new Set(response.free_color_set),
            historyCanUndo: response.can_undo,
            historyCanRedo: response.can_redo,
            ...editorCommitStateFromResponse(response),
            contentCommitStatus: "committed",
            contentCommitOperationId: null,
            threemfDiskPath: null,
            downloadUrl: null,
          });
        } catch (err) {
          if (_get().sessionId !== sid) return;
          const settlement = await settleReplacementPreviewError(
            _get(),
            previewCommit,
            _get,
            (partial) => set(partial),
            err,
            "Free color update failed",
          );
          if (settlement.unknown || settlement.committed || !settlement.active) return;
          set({ error: visibleConverterError(err, "Free color update failed") });
        }
      });
    }, { localEditor: true }),

    clearFreeColors: documentCommand(() => {
      const state = _get();
      if (!state.sessionId) {
        set({
          free_color_set: new Set(),
          threemfDiskPath: null,
          downloadUrl: null,
        });
        return;
      }
      const sid = state.sessionId;
      const pendingSelection = waitForSelectionMutation(sid);
      void queueFreeColorMutation(sid, async () => {
        if (pendingSelection && !(await pendingSelection)) return;
        const pendingContentCommit = waitForContentCommits(sid);
        if (pendingContentCommit && !(await pendingContentCommit)) return;
        if (_get().sessionId !== sid) return;
        const latest = _get();
        const previewCommit = captureReplacementPreviewCommit(latest);
        set({
          contentCommitStatus: "pending",
          contentCommitOperationId: previewCommit.operationId,
          error: null,
        });
        try {
          const response = await apiMutateFreeColors(
            sid,
            "clear",
            [],
            previewCommit.operationId,
          );
          if (!isCurrentReplacementPreviewCommit(_get(), previewCommit)) return;
          if (_get().sessionId !== sid) return;
          set({
            free_color_set: new Set(response.free_color_set),
            historyCanUndo: response.can_undo,
            historyCanRedo: response.can_redo,
            ...editorCommitStateFromResponse(response),
            contentCommitStatus: "committed",
            contentCommitOperationId: null,
            threemfDiskPath: null,
            downloadUrl: null,
          });
        } catch (err) {
          if (_get().sessionId !== sid) return;
          const settlement = await settleReplacementPreviewError(
            _get(),
            previewCommit,
            _get,
            (partial) => set(partial),
            err,
            "Free color clear failed",
          );
          if (settlement.unknown || settlement.committed || !settlement.active) return;
          set({ error: visibleConverterError(err, "Free color clear failed") });
        }
      });
    }, { localEditor: true }),

    // --- UI 状态 ---
    setError: (error: string | null) => set({ error }),
    clearError: () => set({ error: null }),

    prepareRecipeExport: async () => {
      const initial = _get();
      if (initial.sessionId) {
        const selection = waitForSelectionMutation(initial.sessionId);
        if (selection && !(await selection)) throw new Error(tRuntime("recipe_export_wait_edits"));
        const content = waitForContentCommits(initial.sessionId);
        if (content && !(await content)) throw new Error(tRuntime("recipe_export_wait_edits"));
        await _get().hydrateSelectionDocument();
      }
      const state = _get();
      if (state.sessionId !== initial.sessionId || state.contentCommitStatus === "pending" || state.contentCommitStatus === "unknown") {
        throw new Error(tRuntime("recipe_export_wait_edits"));
      }
      const hasSpatialData = state.regionReplacementCount > 0 || state.recipe_overrides.length > 0
        || (state.selectionDocument?.selected_pixel_count ?? 0) > 0;
      if (!hasSpatialData || !state.sessionId) return { state, editorFile: state.pendingEditorProject };
      const revision = confirmedSelectionRevisions.get(state.sessionId)?.editorContentRevision
        ?? state.selectionDocument?.editor_content_revision ?? undefined;
      const selectionRevision = state.selectionDocument?.selection_revision;
      const editorFile = await apiExportEditorProject(state.sessionId, revision, selectionRevision);
      const latest = _get();
      const latestRevision = confirmedSelectionRevisions.get(state.sessionId)?.editorContentRevision
        ?? latest.selectionDocument?.editor_content_revision ?? undefined;
      if (latest.sessionId !== state.sessionId || latestRevision !== revision
          || latest.selectionDocument?.selection_revision !== selectionRevision
          || latest.contentCommitStatus === "pending" || latest.contentCommitStatus === "unknown") {
        throw new Error(tRuntime("recipe_export_wait_edits"));
      }
      return { state, editorFile };
    },

    importRecipeState: documentCommand((
      partial: Partial<ConverterState>,
      imageFile: File,
      heightmapFile?: File | null,
    ) => {
      // Load the embedded source first. Ordinary uploads intentionally clear
      // session state, so project parameters and portable colour data must be
      // applied only after setImageFile finishes its synchronous reset.
      // 先装载项目内嵌原图。普通上传会清空会话状态，因此项目参数和可携带的
      // 调色数据必须在 setImageFile 的同步重置之后再写回。
      const prevEnableCrop = _get().enableCrop;
      const restoredWorkshopSource = partial.workshopSource ?? null;
      set({
        enableCrop: false, conversionParameterContext: "restoring",
        projectSettings: null, projectLutFile: null, projectMaterialArchiveFile: null,
        projectSourceKey: null, projectResourceSessionIds: [],
      });
      _get().setImageFile(imageFile);

      const baseState = _get();
      const nextState = {
        ...baseState,
        ...partial,
        modelBounds: null,
      };
      const fridgeMagnetState = buildFridgeMagnetState(nextState, {
        enable_fridge_magnet: partial.enable_fridge_magnet,
        fridge_magnets: partial.fridge_magnets,
        base_spacer_thick: partial.base_spacer_thick,
      });
      set({
        ...partial,
        aspectRatio: nextState.target_width_mm / nextState.target_height_mm,
        modelBounds: null,
        ...fridgeMagnetState,
        conversionParameterContext: "project",
        engraveBackLabels: false,
        enableCrop: prevEnableCrop,
      });

      // Keep validated dynamic results as historical export evidence until a
      // fresh preview replaces them. This explicit assignment also documents
      // the values that are safe to survive the source reset.
      set({
        materialDynamicRecipes: partial.materialDynamicRecipes ?? [],
        materialLayerBenefitCurve:
          partial.materialLayerBenefitCurve ?? [],
        materialLayerBenefitScope:
          partial.materialLayerBenefitScope ?? "all_printable_pixels",
        materialLayerBenefitPixelCount:
          partial.materialLayerBenefitPixelCount ?? 0,
      });

      set({
        workshopSource: restoredWorkshopSource,
      });
      persistSvgHoleCompensationSettings(svgHoleCompensationOptions(_get()));

      // Restore the optional heightmap after all project state is in place.
      if (heightmapFile) {
        _get().setHeightmapFile(heightmapFile);
      }
    }),

    cleanupAfterDownload: () => {
      const state = _get();
      if (!state.sessionId) return;
      // Preserve download, preview, and GLB files so share card export
      // and 3D viewer still work after slicer launch / download.
      const keepIds = collectConverterKeepFileIds(state);
      apiCleanupSessionFiles(state.sessionId, keepIds);
      set({ isLoading: false });
    },
  })),
);

export const converterDocumentHistory = installConverterDocumentHistory(useConverterStore, (document, editor, sources) => {
  const current = useConverterStore.getState();
  const { portableBrand, ...sourceRuntime } = sources;
  for (const url of [current.imagePreviewUrl, current.modelSurfacePreviewUrl]) if (url?.startsWith("blob:")) URL.revokeObjectURL(url);
  current.commitProjectRestore({
    ...current, ...document, ...sourceRuntime, ...editor,
    nativeBrandGroups: portableBrand ? [...current.nativeBrandGroups.filter(brand => brand.brand_key !== portableBrand.brand_key), portableBrand] : current.nativeBrandGroups,
    imagePreviewUrl: document.imageFile ? (isRawFileConverter(document.imageFile) ? sources.imagePreviewUrl : URL.createObjectURL(document.imageFile)) : null,
    modelSurfacePreviewUrl: document.modelSurfaceFile ? URL.createObjectURL(document.modelSurfaceFile) : null,
    isLoading: false, isGenerating: false, isCropping: false, batchLoading: false, batchResult: null, batchPreviewItems: [],
    cropModalOpen: false, historyBusy: false, replacePreviewLoading: false,
    contentCommitStatus: "idle", contentCommitOperationId: null, pendingSelectionMutations: [], pendingReplacement: null,
    modelSurfaceLoading: false, modelSurfaceSelecting: false, modelSurfaceError: null,
    nativeMaterialSelection: null, nativeMaterialSelectionLoading: false, nativeMaterialSelectionAction: null, nativeMaterialSelectionError: null,
    materialSuggestions: null, materialSuggestionsLoading: false, materialSuggestionsTargetHex: null, materialSuggestionsError: null,
    gradientGroupsLoading: false, gradientGroupsError: null, layerImagesLoading: false,
    error: null, downloadUrl: null, threemfDiskPath: null, modelUrl: null,
    previewPerformanceTiming: null, generatePerformanceTiming: null, generateWarnings: [], largeFormatWarnings: [], largeFormatFailedTiles: [],
  });
  const restored = useConverterStore.getState();
  const file = restored.imageFile;
  const previewUrl = restored.imagePreviewUrl;
  if (file && sources.aspectRatio === null) {
    const publishDimensions = (width: number, height: number, url?: string) => {
      const latest = useConverterStore.getState();
      if (latest.imageFile === file && latest.imagePreviewUrl === previewUrl) useConverterStore.setState({ ...buildImageAspectRatioState(latest, width / height), ...(url ? { imagePreviewUrl: url } : {}) });
    };
    if (isRawFileConverter(file) && !previewUrl) {
      void uploadImagePreview(file).then(result => publishDimensions(result.width, result.height, result.preview_url)).catch(error => {
        if (useConverterStore.getState().imageFile === file) useConverterStore.setState({ error: rawPreviewFailureMessage(error) });
      });
    } else if (previewUrl) {
      const image = new Image();
      image.onload = () => publishDimensions(image.naturalWidth, image.naturalHeight);
      image.src = previewUrl;
    }
  }
  if (editor.sessionId && !editor.previewGlbUrl) current._pollAsyncGlb();
});

registerPrinterBedLabelSynchronizer((printerId) => {
  const { bedSizes, bed_label, setBedLabel, projectSettings } = useConverterStore.getState();
  const activePrinter = projectSettings?.printerModel ?? printerId;
  const printerBed = bedSizes.find((bed) => bed.printer_id === activePrinter);
  if (printerBed && (!projectSettings || printerBed.label !== bed_label)) {
    setBedLabel(printerBed.label);
  }
});

useConverterStore.subscribe(
  (state) => state.projectSettings?.printerModel,
  () => {
    const state = useConverterStore.getState();
    const printer = resolveConverterSettings(state, useSettingsStore.getState()).printerModel;
    const bed = state.bedSizes.find((item) => item.printer_id === printer);
    if (bed && bed.label !== state.bed_label) state.setBedLabel(bed.label);
  },
);

useConverterStore.subscribe(
  (state) => [state.target_width_mm, state.target_height_mm] as const,
  ([width, height]) => {
    if (!Number.isFinite(width) || !Number.isFinite(height) || width < 10 || height < 10) return;
    try {
      localStorage.setItem(OUTPUT_DIMENSIONS_STORAGE_KEY, JSON.stringify({ target_width_mm: width, target_height_mm: height }));
    } catch {
      // Keep editing available when browser storage is unavailable.
    }
  },
  { equalityFn: (left, right) => left[0] === right[0] && left[1] === right[1] },
);

useConverterStore.subscribe(
  (state) => state.base_spacer_thick,
  (thickness) => {
    if (!Number.isFinite(thickness) || thickness < 0.2 || thickness > 10) return;
    try {
      localStorage.setItem(BACKING_THICKNESS_STORAGE_KEY, String(thickness));
    } catch {
      // Keep editing available when browser storage is unavailable.
    }
  },
);

useConverterStore.subscribe(
  (state) => state.largeFormatEnabled,
  (enabled) => {
    if (!enabled) useConverterStore.setState(buildPrinterDimensionState(useConverterStore.getState()));
  },
);

// All source-entry paths share this boundary, including batch and project imports.
// 所有素材入口（含批量与项目导入）共用此可用性边界。
useConverterStore.subscribe(
  (state) => state.svg_hole_compensation_enabled && !isSvgHoleCompensationAvailable(state),
  (unavailable) => {
    if (!unavailable) return;
    const current = useConverterStore.getState();
    // Upload actions may already own the next revision. Do not cancel their
    // thumbnail response by incrementing that revision a second time.
    useConverterStore.setState(buildSvgHoleCompensationChangeState(current, {
      svg_hole_compensation_enabled: false,
    }, Boolean(current.sessionId || current.isLoading || current.hasManualPreview)));
  },
);

registerPreviewArtifactInvalidator(() => {
  if (useConverterStore.getState().projectSettings) return;
  invalidatePreviewRequest();
  if (!isDynamicMaterialActive(useConverterStore.getState())) return;
  useConverterStore.setState(
    buildPreviewSessionResetState(useConverterStore.getState()),
  );
});
