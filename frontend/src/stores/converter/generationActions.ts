import { trackLuminaEvent } from "../../analytics/umami";
import { freezeGenerationProject } from "../../project/generationExport";
import { useProjectSessionStore } from "../projectSessionStore";
import { apiErrorToVisibleMessage as visibleConverterError } from "../../api/client";
import {
  convertBatch as apiConvertBatch,
  convertGenerate as apiConvertGenerate,
  convertGenerateLargeFormat as apiConvertGenerateLargeFormat,
  convertGeneratePuzzle as apiConvertGeneratePuzzle,
  fetchExportMaterialSelection,
} from "../../api/converter";
import type {
  BatchConvertParams,
  ColorReplacementItem,
  ConvertGenerateRequest,
  ExportMaterialSelection,
} from "../../api/types";
import { ModelingMode as ModelingModeEnum } from "../../api/types";
import {
  showBrowserCompletionNotification,
  type CompletionNotificationKind,
} from "../../utils/browserNotifications";
import { postClientLog, summarizeErrorForLog, summarizeFileForLog } from "../../utils/clientLog";
import { colorRemapToReplacementRegions } from "../../utils/colorUtils";
import { normalizeResourceUrl } from "../../utils/resourceUrl";
import {
  captureGeneratedArtifactIdentity,
  invalidateGeneratedArtifacts,
  isGeneratedArtifactIdentityCurrent,
  registerGeneratedArtifactInvalidator,
  registerSingleItemDownloadInvalidator,
} from "../generatedArtifactInvalidation";
import { useSettingsStore } from "../settingsStore";
import { boundProjectResources, resolveConverterSettings } from "./project";
import { isGenerateRevisionConflict } from "./editorRevision";
import {
  materialSelectionFromExportError,
  nativeFilamentProfileScope,
  scopedNativeFilamentProfiles,
} from "./nativeMaterialSelection";
import { buildPuzzlePreviewParams, normalizeStoreResourceUrl } from "./previewArtifacts";
import { buildBatchParams, buildGenerateParams, buildMissingAutoReliefHeightMap } from "./requests";
import {
  buildConversionSourceParams,
  normalizePublicColorMode,
  resolveConverterSourceSelection,
} from "./sources";
import type { ConverterActions, ConverterState, NativeMaterialSelectionAction } from "./types";

const BATCH_PREVIEW_BROWSER_SAFE_LIMIT = 96;

export function notifyCompletion(kind: CompletionNotificationKind): void {
  const settings = useSettingsStore.getState();
  if (!settings.enableCompletionNotifications) return;
  showBrowserCompletionNotification(kind, settings.language);
}

export const CONVERTER_ERROR_KEYS = {
  heightmapUploadRequired: "relief_heightmap_generate_requires_upload",
  largeFormatModelSurfaceConflict: "large_format_model_surface_conflict",
} as const;

let _generateStartTime: number | null = null;

const _GENERATE_TIMER_LABEL = "[LUMINA] generate";

let _generateTimerActive = false;

function _startGenerateTimer(): void {
  if (_generateTimerActive) {
    try {
      console.timeEnd(_GENERATE_TIMER_LABEL);
    } catch {
      // Ignore missing timer in non-browser/test environments.
    }
  }
  console.time(_GENERATE_TIMER_LABEL);
  _generateTimerActive = true;
}

function _logGenerateTimer(message: string): void {
  if (!_generateTimerActive) return;
  try {
    console.timeLog(_GENERATE_TIMER_LABEL, message);
  } catch {
    // Ignore when console.timeLog is unavailable.
  }
}

function _endGenerateTimer(): void {
  if (!_generateTimerActive) return;
  try {
    console.timeEnd(_GENERATE_TIMER_LABEL);
  } catch {
    // Ignore missing timer in non-browser/test environments.
  }
  _generateTimerActive = false;
}

export function _clientLog(
  label: string,
  details?: Record<string, unknown>,
  method: "log" | "warn" | "error" = "log",
) {
  postClientLog(label, {
    startTime: _generateStartTime,
    details,
    scope: "generate",
    phase: label,
    method,
  });
}

export function getElapsedMsSince(startTime: number | null): number | null {
  if (startTime == null || typeof performance === "undefined") {
    return null;
  }
  return Math.round(performance.now() - startTime);
}

export function getFileCountBucket(count: number): string {
  if (count <= 0) return "0";
  if (count === 1) return "1";
  if (count <= 5) return "2-5";
  if (count <= 10) return "6-10";
  if (count <= 25) return "11-25";
  return "26+";
}

export function getErrorType(error: unknown): string {
  return error instanceof Error ? error.name : typeof error;
}

let _generateRequestSequence = 0;

let _batchRequestSequence = 0;

let _activeFilenameEligibleGenerateSequence: number | null = null;

/** True while a generate retry after a revision conflict is running. 版本冲突重试进行中。 */
let _generateRevisionRetryActive = false;

function _isCurrentGenerateRequest(
  sequence: number,
  sessionId: string,
  getCurrentSessionId: () => string | null,
): boolean {
  return _generateRequestSequence === sequence && getCurrentSessionId() === sessionId;
}

export function invalidateGenerationRequests(): void {
  _generateRequestSequence += 1;
  _batchRequestSequence += 1;
  _activeFilenameEligibleGenerateSequence = null;
  _endGenerateTimer();
}

function generationReplacements(state: ConverterState): ColorReplacementItem[] | undefined {
  const replacements = [
    ...state.replacement_regions,
    ...colorRemapToReplacementRegions(state.colorRemapMap, state.palette),
  ];
  return replacements.length > 0 ? replacements : undefined;
}

export function createGenerationActions(
  set: (partial: Partial<ConverterState>) => void,
  _get: () => ConverterState & ConverterActions,
  editor: {
    waitForSelectionMutation: (sessionId: string) => Promise<boolean> | null;
    waitForContentCommits: (sessionId: string) => Promise<boolean> | null;
    getReplacementEpoch: () => number;
    confirmedEditorRevision: (sessionId: string) => number | undefined;
    refreshConfirmedEditorContentRevision: (sessionId: string) => Promise<boolean>;
  },
): Pick<ConverterActions,
  | "submitGenerate"
  | "submitBatch"
  | "openNativeMaterialSelection"
  | "refreshNativeMaterialSelection"
  | "applyNativeMaterialSelection"
  | "cancelNativeMaterialSelection"
> {
  const { waitForSelectionMutation, waitForContentCommits, refreshConfirmedEditorContentRevision } = editor;
  let pendingMaterialSelection: {
    action: NativeMaterialSelectionAction;
    response: ExportMaterialSelection;
    sessionId: string | null;
    params: ConvertGenerateRequest | BatchConvertParams;
    refreshSequence: number;
    isCurrent: () => boolean;
  } | null = null;

  function showMaterialSelection(
    response: ExportMaterialSelection,
    sessionId: string | null,
    params: ConvertGenerateRequest | BatchConvertParams,
    action: NativeMaterialSelectionAction,
    isCurrent: () => boolean,
  ): void {
    pendingMaterialSelection = { action, response, sessionId, params, refreshSequence: 0, isCurrent };
    set({
      nativeMaterialSelection: response,
      nativeMaterialSelectionAction: action,
      nativeMaterialSelectionLoading: false,
      nativeMaterialSelectionError: null,
      isGenerating: false,
      batchLoading: false,
      error: null,
    });
  }

  async function preflightMaterials(
    sessionId: string | null,
    params: ConvertGenerateRequest | BatchConvertParams,
    action: NativeMaterialSelectionAction,
    isCurrent: () => boolean,
  ): Promise<boolean> {
    const response = await fetchExportMaterialSelection(sessionId, params, boundProjectResources(_get()));
    if (!isCurrent()) return false;
    if (action === "edit" || !response.ready) {
      showMaterialSelection(response, sessionId, params, action, isCurrent);
      return false;
    }
    return true;
  }

  registerGeneratedArtifactInvalidator(({ preservePreviews, source }) => {
    if (source === "defaults" && _get().projectSettings) return;
    pendingMaterialSelection = null;
    invalidateGenerationRequests();
    set({
      nativeMaterialSelection: null,
      nativeMaterialSelectionAction: null,
      nativeMaterialSelectionLoading: false,
      nativeMaterialSelectionError: null,
      isGenerating: false,
      batchLoading: false,
      batchResult: null,
      threemfDiskPath: null,
      downloadUrl: null,
      generatePerformanceTiming: null,
      puzzleWarnings: [],
      puzzleResolvedRows: null,
      puzzleResolvedCols: null,
      puzzleResolvedPieceCount: null,
      largeFormatWarnings: [],
      largeFormatFailedTiles: [],
      ...(preservePreviews
        ? {}
        : {
          modelUrl: null,
          previewGlbUrl: null,
          previewImageUrl: null,
          previewBaseImageUrl: null,
          batchPreviewItems: [],
          layerImages: [],
          layerImagesSourceKey: null,
        }),
    });
  });
  registerSingleItemDownloadInvalidator(() => {
    if (_get().projectSettings) return;
    if (
      _activeFilenameEligibleGenerateSequence !== null &&
      _activeFilenameEligibleGenerateSequence === _generateRequestSequence
    ) {
      _generateRequestSequence += 1;
      _activeFilenameEligibleGenerateSequence = null;
      set({ isGenerating: false });
    }

    const state = _get();
    if (
      state.batchMode ||
      state.puzzleEnabled ||
      state.largeFormatEnabled ||
      state.modeling_mode === ModelingModeEnum.COLOR_CARD
    ) {
      return;
    }
    set({
      threemfDiskPath: null,
      downloadUrl: null,
    });
  });
  return {
    openNativeMaterialSelection: async () => {
      let state = _get();
      const sessionId = state.sessionId;
      if (!sessionId || state.batchMode || state.isLoading || state.isGenerating ||
        state.batchLoading || state.nativeMaterialSelectionLoading ||
        state.contentCommitStatus === "unknown") return;
      const settings = resolveConverterSettings(state, useSettingsStore.getState());
      const identity = captureGeneratedArtifactIdentity(settings.deviceProfileId, settings.buildPlateId, !state.projectSettings);
      const sourceIdentity = JSON.stringify(buildConversionSourceParams(state));
      const sequence = ++_generateRequestSequence;
      pendingMaterialSelection = null;
      set({
        nativeMaterialSelection: null,
        nativeMaterialSelectionAction: null,
        nativeMaterialSelectionLoading: true,
        nativeMaterialSelectionError: null,
        error: null,
      });
      const isCurrentInput = (): boolean => {
        const currentSettings = resolveConverterSettings(_get(), useSettingsStore.getState());
        return _isCurrentGenerateRequest(sequence, sessionId, () => _get().sessionId) &&
          !_get().batchMode &&
          JSON.stringify(buildConversionSourceParams(_get())) === sourceIdentity &&
          isGeneratedArtifactIdentityCurrent(identity, currentSettings.deviceProfileId, currentSettings.buildPlateId);
      };
      let isCurrent = isCurrentInput;
      try {
        const pendingSelection = waitForSelectionMutation(sessionId);
        if (pendingSelection && !await pendingSelection) return;
        if (!isCurrentInput()) return;
        const pendingContentCommit = waitForContentCommits(sessionId);
        if (pendingContentCommit && !await pendingContentCommit) return;
        if (!isCurrentInput()) return;
        state = _get();
        const sourceParams = buildConversionSourceParams(state);
        if (!sourceParams || !resolveConverterSourceSelection(state).isReady) return;
        const replacementEpoch = editor.getReplacementEpoch();
        const selectionRevision = state.selectionDocument?.selection_revision;
        isCurrent = (): boolean => isCurrentInput() &&
          editor.getReplacementEpoch() === replacementEpoch &&
          _get().selectionDocument?.selection_revision === selectionRevision;
        const params = buildGenerateParams(
          state, settings, sourceParams, generationReplacements(state),
          editor.confirmedEditorRevision(sessionId),
        );
        await preflightMaterials(sessionId, params, "edit", isCurrent);
      } catch (error) {
        if (isCurrent()) {
          set({ error: visibleConverterError(error, "native_material_load_failed") });
        }
      } finally {
        if (_generateRequestSequence === sequence) set({ nativeMaterialSelectionLoading: false });
      }
    },
    refreshNativeMaterialSelection: async (profiles, buildPlateId) => {
      const pending = pendingMaterialSelection;
      if (!pending || _get().nativeMaterialSelection !== pending.response) return;
      if (!pending.isCurrent()) {
        _get().cancelNativeMaterialSelection();
        return;
      }
      const sequence = ++pending.refreshSequence;
      const params = {
        ...pending.params,
        native_filament_profiles: Object.fromEntries(
          Object.entries(profiles).filter(([, name]) => Boolean(name)),
        ),
        build_plate_id: buildPlateId,
      };
      pending.params = params;
      set({ nativeMaterialSelectionLoading: true, nativeMaterialSelectionError: null });
      const isLatest = (): boolean => pendingMaterialSelection === pending &&
        pending.refreshSequence === sequence && _get().nativeMaterialSelection === pending.response;
      try {
        const response = await fetchExportMaterialSelection(pending.sessionId, params, boundProjectResources(_get()));
        if (!isLatest()) return;
        if (!pending.isCurrent()) {
          _get().cancelNativeMaterialSelection();
          return;
        }
        pending.response = response;
        set({ nativeMaterialSelection: response });
      } catch (error) {
        if (!isLatest()) return;
        if (!pending.isCurrent()) {
          _get().cancelNativeMaterialSelection();
          return;
        }
        set({ nativeMaterialSelectionError: visibleConverterError(error, "native_material_recheck_failed") });
      } finally {
        if (isLatest()) set({ nativeMaterialSelectionLoading: false });
      }
    },
    cancelNativeMaterialSelection: () => {
      pendingMaterialSelection = null;
      invalidateGenerationRequests();
      set({
        nativeMaterialSelection: null,
        nativeMaterialSelectionAction: null,
        nativeMaterialSelectionLoading: false,
        nativeMaterialSelectionError: null,
        isGenerating: false,
        batchLoading: false,
      });
    },
    applyNativeMaterialSelection: async (profiles, buildPlateId) => {
      const pending = pendingMaterialSelection;
      if (!pending || _get().nativeMaterialSelection !== pending.response) return;
      if (_get().nativeMaterialSelectionLoading || _get().nativeMaterialSelectionError ||
        !pending.response.ready) return;
      if (!pending.isCurrent()) {
        pendingMaterialSelection = null;
        set({
          nativeMaterialSelection: null,
          nativeMaterialSelectionAction: null,
          nativeMaterialSelectionError: null,
          isGenerating: false,
          batchLoading: false,
        });
        return;
      }
      const plate = pending.response.build_plates.find((row) => row.id === buildPlateId);
      if (!plate?.compatible || plate.build_plate_uid !== pending.response.build_plate_uid) return;
      const selectedProfiles: Record<string, string> = {};
      for (const material of pending.response.materials) {
        const requested = profiles[material.name] || undefined;
        if (requested !== (pending.params.native_filament_profiles?.[material.name] || undefined)) return;
        const selectedName = material.selected_profile_name;
        if (!selectedName || (requested && selectedName !== requested)) return;
        selectedProfiles[material.name] = selectedName;
      }
      const settings = resolveConverterSettings(_get(), useSettingsStore.getState());
      const previousProfiles = scopedNativeFilamentProfiles(_get(), settings) ?? {};
      const profilesChanged = Object.keys(previousProfiles).length !== Object.keys(selectedProfiles).length ||
        Object.entries(selectedProfiles).some(([name, profile]) => previousProfiles[name] !== profile);
      pendingMaterialSelection = null;
      if (_get().projectSettings) {
        set({ projectSettings: { ..._get().projectSettings!, buildPlateId: plate.id } });
      } else {
        useSettingsStore.getState().setBuildPlateForMachine(pending.response.machine_profile_id, plate.id);
        void useSettingsStore.getState().syncToBackend();
      }
      if (profilesChanged) invalidateGeneratedArtifacts({ preservePreviews: true });
      set({
        nativeMaterialSelection: null,
        nativeMaterialSelectionAction: null,
        nativeMaterialSelectionError: null,
        native_filament_profiles: selectedProfiles,
        nativeFilamentProfileScope: nativeFilamentProfileScope(resolveConverterSettings(_get(), useSettingsStore.getState())),
        error: null,
      });
      if (pending.action === "batch") {
        await _get().submitBatch();
      } else if (pending.action === "generate") {
        await _get().submitGenerate();
      }
    },
    submitGenerate: async () => {
      let state = _get();
      if (state.isLoading) return null;
      if (!state.sessionId) {
        set({ error: "请先预览图片" });
        return null;
      }
      const sessionId = state.sessionId;
      if (state.contentCommitStatus === "unknown") {
        set({
          error:
            "编辑提交结果暂时未知，已暂停生成；请先同步这次编辑的提交状态。",
        });
        return null;
      }
      const pendingSelection = waitForSelectionMutation(sessionId);
      if (pendingSelection) {
        const selectionCommitSucceeded = await pendingSelection;
        if (_get().sessionId !== sessionId) return null;
        if (!selectionCommitSucceeded) return null;
      }
      const pendingContentCommit = waitForContentCommits(sessionId);
      if (pendingContentCommit) {
        const contentCommitSucceeded = await pendingContentCommit;
        if (_get().sessionId !== sessionId) return null;
        if (!contentCommitSucceeded) {
          // A failed edit already left its previous committed state visible.
          // Do not send a generate request that could combine that state with
          // a partially failed mutation.
          return null;
        }
      }
      state = _get();
      // Large-format tiles are cut from flat artwork, so the uploaded model
      // would be dropped. Refuse before material preflight or any export call.
      if (state.largeFormatEnabled && state.modelSurfaceEnabled) {
        set({ error: CONVERTER_ERROR_KEYS.largeFormatModelSurfaceConflict });
        return null;
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
        return null;
      }
      const autoReliefHeightMap = buildMissingAutoReliefHeightMap(state);
      if (autoReliefHeightMap) {
        set({ color_height_map: autoReliefHeightMap });
        state = _get();
      }
      const hasCurrentHeightmapUpload =
        state.heightmapUploadSessionId === sessionId &&
        Object.keys(state.color_height_map).length > 0;
      if (
        state.enable_relief &&
        state.autoHeightMode === "use-heightmap" &&
        !hasCurrentHeightmapUpload
      ) {
        set({ error: CONVERTER_ERROR_KEYS.heightmapUploadRequired });
        return null;
      }
      // Requirement 10.4: enable_relief 为 true 且 color_height_map 为空时阻止生成
      if (
        state.enable_relief &&
        Object.keys(state.color_height_map).length === 0
      ) {
        // Requirement 10.3: 高度图模式时给出更具体的提示
        if (state.autoHeightMode === "use-heightmap") {
          set({ error: CONVERTER_ERROR_KEYS.heightmapUploadRequired });
        } else {
          set({ error: "请先设置颜色高度映射后再生成" });
        }
        return null;
      }

      const generateSettings = resolveConverterSettings(state, useSettingsStore.getState());
      const generateIdentity = captureGeneratedArtifactIdentity(
        generateSettings.deviceProfileId,
        generateSettings.buildPlateId,
        !state.projectSettings,
      );
      const generateReplacementEpoch = editor.getReplacementEpoch();
      const sourceIdentity = JSON.stringify(buildConversionSourceParams(state));
      const generateSelectionRevision = state.selectionDocument?.selection_revision;
      pendingMaterialSelection = null;
      set({
        nativeMaterialSelection: null,
        nativeMaterialSelectionAction: null,
        nativeMaterialSelectionLoading: false,
        nativeMaterialSelectionError: null,
        isGenerating: true,
        error: null,
        generatePerformanceTiming: null,
        // The previous download and its warnings remain available while retrying.
      });
      _generateRequestSequence += 1;
      const generateSequence = _generateRequestSequence;
      _activeFilenameEligibleGenerateSequence =
        !state.batchMode &&
          !state.puzzleEnabled &&
          !state.largeFormatEnabled &&
          state.modeling_mode !== ModelingModeEnum.COLOR_CARD
          ? generateSequence
          : null;
      const shouldIgnoreStaleGenerateResponse = (): boolean => {
        const latestSettings = resolveConverterSettings(_get(), useSettingsStore.getState());
        if (
          _isCurrentGenerateRequest(
            generateSequence,
            sessionId,
            () => _get().sessionId,
          ) &&
          editor.getReplacementEpoch() === generateReplacementEpoch &&
          _get().selectionDocument?.selection_revision === generateSelectionRevision &&
          JSON.stringify(buildConversionSourceParams(_get())) === sourceIdentity &&
          isGeneratedArtifactIdentityCurrent(
            generateIdentity,
            latestSettings.deviceProfileId,
            latestSettings.buildPlateId,
          )
        ) {
          return false;
        }

        const latestState = _get();
        if (
          _generateRequestSequence === generateSequence &&
          latestState.isGenerating
        ) {
          set({ isGenerating: false });
        }
        return true;
      };
      _generateStartTime = performance.now();
      (window as Window & { __luminaGenerateStart?: number }).__luminaGenerateStart = _generateStartTime;
      _clientLog("generate: click", {
        image: summarizeFileForLog(state.imageFile),
        session_id: sessionId,
        source_version: state.source_version,
        target_width_mm: state.target_width_mm,
        color_mode: state.color_mode,
        modeling_mode: state.modeling_mode,
        quantize_colors: state.quantize_colors,
        high_precision_3d_preview: state.high_precision_3d_preview,
        enable_cleanup: state.enable_cleanup,
        enable_relief: state.enable_relief,
        enable_outline: state.enable_outline,
        enable_cloisonne: state.enable_cloisonne,
        puzzle_enabled: state.puzzleEnabled,
        large_format_enabled: state.largeFormatEnabled,
      });
      _startGenerateTimer();
      let preparedParams: ConvertGenerateRequest | null = null;
      try {
        // Merge global-only replacement mappings. Spatial edits stay in the
        // session preview cache and are selected by use_cached_matched_rgb.
        // 仅合并全局替色映射；空间局部改色保留在会话预览缓存中。
        const mergedReplacements = generationReplacements(state);
        const colorMode = normalizePublicColorMode(state.color_mode);
        const sourceParams =
          buildConversionSourceParams(state);
        if (!sourceParams) {
          set({
            isGenerating: false,
            error: "请先选择品牌和数据库",
          });
          return null;
        }
        const baseParams: ConvertGenerateRequest = buildGenerateParams(state, generateSettings, sourceParams, mergedReplacements, editor.confirmedEditorRevision(sessionId));
        const projectSequence = useProjectSessionStore.getState().changeSequence;
        preparedParams = baseParams;

        if (!await preflightMaterials(
          sessionId,
          baseParams,
          "generate",
          () => !shouldIgnoreStaleGenerateResponse(),
        )) return null;

        const projectRevision = await freezeGenerationProject(projectSequence);
        if (projectRevision) baseParams.project_revision_file_id = projectRevision;

        _clientLog("generate: request prepared", {
          source_kind: sourceParams.source_kind,
          replacement_count: mergedReplacements?.length ?? 0,
          recipe_override_count: state.recipe_overrides.length,
          free_color_count: state.free_color_set.size,
          fridge_magnet_count: state.fridge_magnets.length,
          color_layers: baseParams.color_layers ?? null,
          layer_height_mm: baseParams.layer_height_mm ?? null,
          structure_mode: baseParams.structure_mode,
          separate_backing: baseParams.separate_backing,
          enable_relief: baseParams.enable_relief,
          enable_outline: baseParams.enable_outline,
          enable_cloisonne: baseParams.enable_cloisonne,
        });

        if (state.puzzleEnabled) {
          const puzzleResponse = await apiConvertGeneratePuzzle(sessionId, {
            ...buildPuzzlePreviewParams(state),
            params: baseParams,
          });
          if (shouldIgnoreStaleGenerateResponse()) {
            return null;
          }
          const downloadUrl = normalizeStoreResourceUrl(puzzleResponse.download_url);
          set({
            isGenerating: false,
            modelUrl: null,
            batchPreviewItems: [],
            downloadUrl,
            threemfDiskPath: null,
            generateWarnings: puzzleResponse.warnings ?? [],
            largeFormatWarnings: [],
            largeFormatFailedTiles: [],
            puzzleWarnings: puzzleResponse.warnings ?? [],
            puzzleResolvedRows: puzzleResponse.grid_rows ?? null,
            puzzleResolvedCols: puzzleResponse.grid_cols ?? null,
            puzzleResolvedPieceCount: puzzleResponse.piece_count ?? null,
          });
          _logGenerateTimer("puzzle 3mf received");
          _clientLog("generate: puzzle 3mf received", {
            download_url: downloadUrl,
            has_legacy_threemf_disk_path: Boolean(
              puzzleResponse.threemf_disk_path,
            ),
            warning_count: (puzzleResponse.warnings ?? []).length,
            grid_rows: puzzleResponse.grid_rows ?? null,
            grid_cols: puzzleResponse.grid_cols ?? null,
            piece_count: puzzleResponse.piece_count ?? null,
          });
          trackLuminaEvent("lumina_converter_generate_done", {
            source_version: state.source_version,
            source_kind: sourceParams.source_kind,
            color_mode: colorMode,
            modeling_mode: state.modeling_mode,
            output_kind: "puzzle_3mf",
            puzzle: true,
            large_format: false,
            elapsed_ms: getElapsedMsSince(_generateStartTime),
            warning_count: (puzzleResponse.warnings ?? []).length,
          });
          notifyCompletion("generation");
          return null;
        }

        if (state.largeFormatEnabled) {
          const lfResponse = await apiConvertGenerateLargeFormat(sessionId, {
            // Let the backend derive height from the preview cache aspect
            // ratio. SVG files can report slightly different browser and
            // server dimensions (CSS width/height vs viewBox/content), and
            // sending both values makes the backend reject large-format
            // generation with 422 when they differ by more than 1 mm.
            // 大画幅只提交宽度，让后端按预览缓存比例推导高度。SVG 的浏览器
            // 预览比例与后端解析比例可能不完全一致；同时提交宽高会触发后端
            // 1mm 容差校验并返回 422。
            tile_width_mm: state.tileWidthMm,
            tile_height_mm: state.tileHeightMm,
            params: baseParams,
          });
          if (shouldIgnoreStaleGenerateResponse()) {
            return null;
          }
          const downloadUrl = normalizeStoreResourceUrl(lfResponse.download_url);
          set({
            isGenerating: false,
            modelUrl: null,
            batchPreviewItems: [],
            threemfDiskPath: null,
            downloadUrl,
            generateWarnings: [],
            largeFormatWarnings: lfResponse.warnings ?? [],
            largeFormatFailedTiles: lfResponse.failed_tiles ?? [],
          });
          _clientLog("generate: large-format zip received", {
            download_url: downloadUrl,
            warning_count: (lfResponse.warnings ?? []).length,
            target_height_mm: state.target_height_mm,
            tile_width_mm: state.tileWidthMm,
            tile_height_mm: state.tileHeightMm,
          });
          trackLuminaEvent("lumina_converter_generate_done", {
            source_version: state.source_version,
            source_kind: sourceParams.source_kind,
            color_mode: colorMode,
            modeling_mode: state.modeling_mode,
            output_kind: "large_format_zip",
            puzzle: false,
            large_format: true,
            elapsed_ms: getElapsedMsSince(_generateStartTime),
            warning_count: (lfResponse.warnings ?? []).length,
          });
          if (lfResponse.status !== "partial" && !lfResponse.failed_tiles?.length) {
            notifyCompletion("generation");
          }
          return null;
        }

        _logGenerateTimer("request sent");
        _clientLog("generate: request sent", {
          session_id: sessionId,
          source_kind: sourceParams.source_kind,
          replacement_count: mergedReplacements?.length ?? 0,
          recipe_override_count: state.recipe_overrides.length,
          free_color_count: state.free_color_set.size,
        });
        const response = await apiConvertGenerate(
          sessionId,
          baseParams,
          generateSettings.preserveUploadFilenameFor3mf,
        );
        if (shouldIgnoreStaleGenerateResponse()) {
          return null;
        }
        _logGenerateTimer("response received");
        _clientLog("generate: response received", {
          preview_3d_url: response.preview_3d_url ?? null,
          download_url: response.download_url ?? null,
          has_legacy_threemf_disk_path: Boolean(response.threemf_disk_path),
        });
        const responseModelUrl = normalizeStoreResourceUrl(
          response.preview_3d_url,
        );
        const downloadUrl = normalizeStoreResourceUrl(response.download_url);
        set({
          isGenerating: false,
          // Generate owns the exact downloadable 3MF only. Browser geometry
          // remains preview-owned so async lightweight polling and real-time
          // Three.js helpers continue without a print-scene GLB takeover.
          // Generate 只拥有精确 3MF 下载；浏览器几何继续由轻量预览负责。
          modelUrl: null,
          batchPreviewItems: [],
          downloadUrl,
          threemfDiskPath: null,
          generatePerformanceTiming: response.performance_timing ?? null,
          generateWarnings: response.warnings ?? [],
          largeFormatWarnings: [],
          largeFormatFailedTiles: [],
        });
        _logGenerateTimer("UI unlocked (isGenerating=false, 3MF set)");
        _clientLog("generate: UI unlocked", {
          response_model_url: responseModelUrl,
          selected_model_url: null,
          download_url: downloadUrl,
          has_legacy_threemf_disk_path: Boolean(response.threemf_disk_path),
          warning_count: (response.warnings ?? []).length,
        });
        trackLuminaEvent("lumina_converter_generate_done", {
          source_version: state.source_version,
          source_kind: sourceParams.source_kind,
          color_mode: colorMode,
          modeling_mode: state.modeling_mode,
          output_kind: "threemf",
          puzzle: false,
          large_format: false,
          elapsed_ms: getElapsedMsSince(_generateStartTime),
          warning_count: (response.warnings ?? []).length,
        });
        notifyCompletion("generation");
        return null;
      } catch (err) {
        if (shouldIgnoreStaleGenerateResponse()) {
          return null;
        }
        const materialSelection = materialSelectionFromExportError(err);
        if (materialSelection && preparedParams) {
          showMaterialSelection(materialSelection, sessionId, preparedParams, "generate", () => !shouldIgnoreStaleGenerateResponse());
          return null;
        }
        // The editor revision this client sent was behind the server. All
        // pending edits were already awaited above, so re-read the committed
        // revision once and retry; a second conflict is surfaced to the user.
        // 客户端版本落后于服务端：前面已等待所有未完成编辑，这里重读一次
        // 已提交版本并重试；再次冲突才提示用户。
        if (!_generateRevisionRetryActive && isGenerateRevisionConflict(err)) {
          const refreshed = await refreshConfirmedEditorContentRevision(sessionId);
          if (refreshed && _get().sessionId === sessionId) {
            _clientLog("generate: retry after editor revision refresh", {
              session_id: sessionId,
            });
            _generateRevisionRetryActive = true;
            try {
              return await _get().submitGenerate();
            } finally {
              _generateRevisionRetryActive = false;
            }
          }
        }
        set({
          isGenerating: false,
          error: visibleConverterError(err, "生成失败"),
        });
        trackLuminaEvent("lumina_converter_generate_failed", {
          source_version: state.source_version,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          puzzle: state.puzzleEnabled,
          large_format: state.largeFormatEnabled,
          elapsed_ms: getElapsedMsSince(_generateStartTime),
          error_type: getErrorType(err),
        });
        _clientLog("generate: failed", summarizeErrorForLog(err), "error");
        return null;
      } finally {
        if (_activeFilenameEligibleGenerateSequence === generateSequence) {
          _activeFilenameEligibleGenerateSequence = null;
        }
        if (_generateRequestSequence === generateSequence) {
          _endGenerateTimer();
        }
      }
    },
    submitBatch: async () => {
      let state = _get();
      const batchStartTime =
        typeof performance !== "undefined" ? performance.now() : null;
      const batchFileCount = state.batchFiles.length;
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
      const autoReliefHeightMap = buildMissingAutoReliefHeightMap(state);
      if (autoReliefHeightMap) {
        set({ color_height_map: autoReliefHeightMap });
        state = _get();
      }
      if (state.enable_relief && state.autoHeightMode === "use-heightmap") {
        set({
          error: "批量生成暂不支持高度图浮雕，请改用按颜色浮雕或单图生成",
        });
        return;
      }
      if (
        state.enable_relief &&
        Object.keys(state.color_height_map).length === 0
      ) {
        set({ error: "请先设置颜色高度映射后再批量生成" });
        return;
      }
      const settings = resolveConverterSettings(state, useSettingsStore.getState());
      const batchIdentity = captureGeneratedArtifactIdentity(
        settings.deviceProfileId,
        settings.buildPlateId,
        !state.projectSettings,
      );
      const batchSequence = ++_batchRequestSequence;
      const batchSourceIdentity = JSON.stringify(buildConversionSourceParams(state));
      const isCurrentBatchRequest = (): boolean => {
        const latestSettings = resolveConverterSettings(_get(), useSettingsStore.getState());
        const isCurrent = (
          batchSequence === _batchRequestSequence &&
          _get().batchFiles === state.batchFiles &&
          JSON.stringify(buildConversionSourceParams(_get())) === batchSourceIdentity &&
          isGeneratedArtifactIdentityCurrent(
            batchIdentity,
            latestSettings.deviceProfileId,
            latestSettings.buildPlateId,
          )
        );
        if (!isCurrent && batchSequence === _batchRequestSequence) {
          set({ batchLoading: false });
        }
        return isCurrent;
      };
      pendingMaterialSelection = null;
      set({
        nativeMaterialSelection: null,
        nativeMaterialSelectionAction: null,
        nativeMaterialSelectionLoading: false,
        nativeMaterialSelectionError: null,
        batchLoading: true,
        batchResult: null,
        batchPreviewItems: [],
        modelUrl: null,
        previewGlbUrl: null,
        generatePerformanceTiming: null,
        threemfDiskPath: null,
        downloadUrl: null,
        error: null,
      });
      let preparedParams: BatchConvertParams | null = null;
      try {
        const sourceParams =
          buildConversionSourceParams(state);
        if (!sourceParams) {
          set({
            batchLoading: false,
            error: "请先选择品牌和数据库",
          });
          return;
        }
        const params: BatchConvertParams = buildBatchParams(state, settings, sourceParams);
        const projectSequence = useProjectSessionStore.getState().changeSequence;
        preparedParams = params;
        if (!await preflightMaterials(null, params, "batch", isCurrentBatchRequest)) return;
        const projectRevision = await freezeGenerationProject(projectSequence);
        if (projectRevision) params.project_revision_file_id = projectRevision;
        const resources = boundProjectResources(state);
        const result = resources.lut || resources.materials
          ? await apiConvertBatch(state.batchFiles, params, resources)
          : await apiConvertBatch(state.batchFiles, params);
        if (!isCurrentBatchRequest()) return;
        const previewItems = (result.preview_items ?? [])
          .slice(0, BATCH_PREVIEW_BROWSER_SAFE_LIMIT)
          .map((item) => ({
            ...item,
            url: normalizeResourceUrl(item.url) ?? item.url,
          }));
        const downloadUrl = normalizeStoreResourceUrl(result.download_url);
        set({
          batchResult: {
            ...result,
            download_url: downloadUrl,
            threemf_disk_path: null,
          },
          batchLoading: false,
          batchPreviewItems: previewItems,
          // 批量预览只接受 preview_items。旧的 preview_3d_url 曾经指向
          // 合并 GLB，颜色与背面显示不可靠，因此不再作为 UI 兜底。
          modelUrl: null,
          previewGlbUrl: null,
          previewPerformanceTiming: null,
          generatePerformanceTiming: null,
          downloadUrl,
          threemfDiskPath: null,
        });
        trackLuminaEvent("lumina_batch_convert_done", {
          source_version: state.source_version,
          source_kind: sourceParams.source_kind,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          file_count_bucket: getFileCountBucket(batchFileCount),
          elapsed_ms: getElapsedMsSince(batchStartTime),
          preview_item_count: previewItems.length,
        });
        notifyCompletion("batch");
      } catch (err) {
        if (!isCurrentBatchRequest()) return;
        const materialSelection = materialSelectionFromExportError(err);
        if (materialSelection && preparedParams) {
          showMaterialSelection(materialSelection, null, preparedParams, "batch", isCurrentBatchRequest);
          return;
        }
        set({
          batchLoading: false,
          error: visibleConverterError(err, "批量处理失败"),
        });
        trackLuminaEvent("lumina_batch_convert_failed", {
          source_version: state.source_version,
          color_mode: state.color_mode,
          modeling_mode: state.modeling_mode,
          file_count_bucket: getFileCountBucket(batchFileCount),
          elapsed_ms: getElapsedMsSince(batchStartTime),
          error_type: getErrorType(err),
        });
      }
    },
  };
}
