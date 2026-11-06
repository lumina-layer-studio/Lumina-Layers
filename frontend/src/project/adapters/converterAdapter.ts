import {
  convertPreview, getEditorSelection, mutateFreeColors, restoreEditorProject,
  selectModelSurface, uploadHeightmap, uploadModelSurface,
} from "../../api/converter";
import { closeSession } from "../../api/session";
import type { LutInfo, NativeBrandGroup } from "../../api/types";
import { buildFullRecipe, buildRecipeAssets, exportConverterRecipe } from "../../recipe/exportRecipe";
import { restoreConverterRecipe } from "../../recipe/importRecipe";
import { migrateRecipe } from "../../recipe/migration";
import type { ConverterRecipe } from "../../recipe/types";
import { DEFAULT_STATE, useConverterStore, converterDocumentHistory } from "../../stores/converter";
import { editorCommitResultStateFromResponse, selectionStateFromDocument } from "../../stores/converter/editorState";
import {
  captureProjectSettings, converterSourceKey, PROJECT_SETTING_KEYS, resolveConverterSettings,
  type ProjectConverterSettings,
} from "../../stores/converter/project";
import { previewResultState } from "../../stores/converter/previewResult";
import { editorMutationPending } from "../../stores/converter/editorRuntime";
import { buildPreviewParams } from "../../stores/converter/requests";
import { buildConversionSourceParams } from "../../stores/converter/sources";
import type { ConverterState } from "../../stores/converter/types";
import { DEFAULT_SETTINGS, useSettingsStore } from "../../stores/settingsStore";
import { rememberDerivedImageSource, resolveSourceFile } from "../../utils/sourceFileOrigins";
import { fileAsset, projectFile } from "../assets";
import { newProjectIdentity } from "../identity";
import { captureConverterResources, captureProjectTemplate, restoreProjectTemplate } from "../resources";
import type { JsonObject, ProjectAsset, ProjectSnapshot, WorkflowDocument } from "../types";
import { assertRestoreIsCurrent, type PreparedProjectRestore, type ProjectAdapter, type ProjectRestoreContext } from "./types";
import { legacyConverterPayload, legacyHasOrderedEdits, replayLegacyConverter } from "./legacyConverter";

const KIND = "converter";
const SCHEMA = 2;

export interface ConverterPayload {
  recipe: ConverterRecipe;
  settings: ProjectConverterSettings;
  files: { primary: string | null; original: string | null; heightmap: string | null; editor: string | null; lut: string | null; materials: string | null; model: string | null; template: string | null; batch: string[] };
  model: { enabled: boolean; faceIndex: number | null; rotation: ConverterState["modelSurfaceModelRotation"]; placement: ConverterState["modelSurfacePlacement"] };
  nativeBrand: NativeBrandGroup | null;
  editor: { hadPreview: boolean; batchMode: boolean; enableCrop: boolean; brushSizePx: number; colorRangeTolerance: number; preferredSizeAxis: "width" | "height"; selectionTool: ConverterState["selectionTool"] };
  workshopSource: ConverterState["workshopSource"];
}

type PreparedConverter = PreparedProjectRestore & { state: ConverterState; freshSessionId: string | null; templateSessionId: string | null };

function json<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function selectedFaceIndex(state: ConverterState): number | null {
  const selection = state.modelSurfaceSelection;
  const indices = selection?.face_indices ?? selection?.faceIndices;
  const index = selection?.face_index ?? selection?.faceIndex ?? (Array.isArray(indices) ? indices[0] : null);
  return typeof index === "number" && Number.isSafeInteger(index) && index >= 0 ? index : null;
}

function portableNativeBrand(state: ConverterState): NativeBrandGroup | null {
  const brand = state.nativeBrandGroups.find((item) => item.brand_key === state.selectedNativeBrandKey);
  return brand ? {
    ...brand,
    db_options: brand.db_options.map(({ name, color_mode }) => ({ name, color_mode, path: "" })),
    package_name: brand.package_name ? brand.package_name.split(/[\\/]/).pop() : null,
    model_name: brand.model_name ? brand.model_name.split(/[\\/]/).pop() : null,
  } : null;
}

function payloadOf(document: WorkflowDocument): ConverterPayload {
  if (document.kind !== KIND || ![1, SCHEMA].includes(document.schemaVersion)) throw new Error("Unsupported converter project version");
  const value = document.schemaVersion === 1 ? legacyConverterPayload(document) : document.payload as unknown as ConverterPayload;
  if (!value.recipe || !value.files || !value.model || !value.editor || !value.settings || !Array.isArray(value.files.batch)) {
    throw new Error("Converter project is incomplete");
  }
  for (const ref of [...Object.values(value.files).filter((ref) => !Array.isArray(ref)), ...value.files.batch]) {
    if (ref !== null && (typeof ref !== "string" || !document.resourceRefs.includes(ref))) throw new Error("Invalid converter resource reference");
  }
  for (const key of PROJECT_SETTING_KEYS) {
    const actual = value.settings[key];
    const expected = DEFAULT_SETTINGS[key];
    if (key === "custom3mfTemplateId" && (actual === null || typeof actual === "string")) continue;
    if (typeof actual !== typeof expected || (typeof actual === "number" && !Number.isFinite(actual))) throw new Error(`Invalid project setting: ${key}`);
  }
  if (!["0.2", "0.25", "0.4"].includes(value.settings.nozzleSize)) throw new Error("Invalid project nozzle size");
  for (const number of [...Object.values(value.model.rotation), ...Object.values(value.model.placement).filter((v) => typeof v === "number")]) {
    if (typeof number !== "number" || !Number.isFinite(number)) throw new Error("Invalid model placement");
  }
  if (value.model.faceIndex !== null && (!Number.isSafeInteger(value.model.faceIndex) || value.model.faceIndex < 0)) throw new Error("Invalid model face");
  return value;
}

async function capture(options: { allowGenerating?: boolean } = {}) {
  const { state, editorFile } = await useConverterStore.getState().prepareRecipeExport();
  if (state.isLoading || (!options.allowGenerating && (state.isGenerating || state.batchLoading)) || state.isCropping || state.modelSurfaceLoading || state.modelSurfaceSelecting) {
    throw new Error("Wait for the current operation before saving the project");
  }
  const settings = resolveConverterSettings(state, useSettingsStore.getState());
  const resources = await captureConverterResources(state);
  const original = resolveSourceFile(state.imageFile);
  const assets: ProjectAsset[] = [];
  async function add(name: string, file: File | null, resource = false): Promise<string | null> {
    if (!file) return null;
    const asset = await fileAsset(`converter.${name}`, file, resource ? "resource" : "asset");
    assets.push(asset);
    return asset.assetId;
  }
  const files: ConverterPayload["files"] = {
    primary: await add("image", state.imageFile),
    original: await add("original", original !== state.imageFile ? original : null),
    heightmap: await add("heightmap", state.heightmapFile),
    editor: await add("editor", editorFile),
    lut: await add("lut", resources.lut, true),
    materials: await add("materials", resources.materials, true),
    model: await add("model", state.modelSurfaceFile),
    template: await add("template", await captureProjectTemplate(settings.custom3mfTemplateId), true),
    batch: [],
  };
  for (const [index, file] of state.batchFiles.entries()) files.batch.push((await add(`batch-${index}`, file))!);
  const payload: ConverterPayload = {
    recipe: exportConverterRecipe(state, settings),
    settings: { ...captureProjectSettings(settings), custom3mfTemplateId: files.template ? null : settings.custom3mfTemplateId }, files,
    model: { enabled: state.modelSurfaceEnabled, faceIndex: selectedFaceIndex(state), rotation: state.modelSurfaceModelRotation, placement: state.modelSurfacePlacement },
    nativeBrand: portableNativeBrand(state),
    editor: { hadPreview: Boolean(state.sessionId), batchMode: state.batchMode, enableCrop: state.enableCrop, brushSizePx: state.brushSizePx, colorRangeTolerance: state.colorRangeTolerance, preferredSizeAxis: state.preferredSizeAxis, selectionTool: state.selectionTool },
    workshopSource: state.workshopSource,
  };
  return {
    document: { documentId: "converter.main", kind: KIND, schemaVersion: SCHEMA, payload: json(payload) as unknown as JsonObject, inputRevisionIds: [], resourceRefs: assets.map((asset) => asset.assetId), requiredCapabilities: ["converter.recipe-v5"] },
    assets,
    nameHint: (state.imageFile ?? state.modelSurfaceFile ?? state.batchFiles[0])?.name.replace(/\.[^.]+$/, ""),
  };
}

async function prepareRestore(snapshot: ProjectSnapshot, context: ProjectRestoreContext): Promise<PreparedConverter> {
  assertRestoreIsCurrent(context);
  const document = Object.values(snapshot.documents).find((item) => item.kind === KIND);
  if (!document) throw new Error("Converter document is missing");
  const payload = payloadOf(document);
  const files = payload.files;
  const image = projectFile(snapshot, files.primary);
  const heightmap = projectFile(snapshot, files.heightmap);
  const editorFile = projectFile(snapshot, files.editor);
  const lut = projectFile(snapshot, files.lut);
  const materials = projectFile(snapshot, files.materials);
  const model = projectFile(snapshot, files.model);
  const previous = useConverterStore.getState();
  let state: ConverterState = { ...DEFAULT_STATE };
  // Even empty/model-only drafts use the canonical recipe mapping; the temporary
  // empty source is never published as artwork or added to the archive.
  const recipe = migrateRecipe(await buildFullRecipe(
    payload.recipe, { width: 1, height: 1, mime_type: "image/png" },
    await buildRecipeAssets(image ?? new File([], "draft.png", { type: "image/png" }), heightmap, editorFile), payload.workshopSource,
  ));
  const names = [...new Set([payload.recipe.base.lut.name, ...(payload.recipe.source?.selected_legacy_lut_names ?? [])])];
  const luts: LutInfo[] = lut ? names.map((name) => ({ name, color_mode: payload.recipe.base.lut.color_mode as LutInfo["color_mode"], path: "" })) : previous.lutListFull;
  const restored = restoreConverterRecipe(recipe, luts);
  state = {
    ...state, ...restored.state,
    imageFile: image, heightmapFile: heightmap,
    projectSettings: captureProjectSettings({ ...DEFAULT_SETTINGS, ...payload.settings }),
    projectLutFile: lut, projectMaterialArchiveFile: materials,
    batchFiles: files.batch.map((id) => projectFile(snapshot, id)!),
    batchMode: payload.editor.batchMode,
    enableCrop: payload.editor.enableCrop, brushSizePx: payload.editor.brushSizePx,
    colorRangeTolerance: payload.editor.colorRangeTolerance,
    preferredSizeAxis: payload.editor.preferredSizeAxis,
    selectionTool: payload.editor.selectionTool,
    aspectRatio: payload.recipe.base.target_width_mm / payload.recipe.base.target_height_mm,
    conversionParameterContext: "project",
    nativeBrandGroups: payload.nativeBrand ? [payload.nativeBrand] : previous.nativeBrandGroups,
    lutList: [...new Set([...previous.lutList, ...luts.map((item) => item.name)])],
    lutListFull: [...previous.lutListFull.filter((item) => !lut || !names.includes(item.name)), ...(lut ? luts : [])],
    bedSizes: previous.bedSizes,
    modelSurfaceEnabled: payload.model.enabled,
    modelSurfaceFile: model, modelSurfacePlacement: payload.model.placement, modelSurfaceModelRotation: payload.model.rotation,
  };
  state.projectSourceKey = converterSourceKey(state);
  if (document.schemaVersion === 1 && legacyHasOrderedEdits(document)) {
    state.replacement_regions = []; state.colorRemapMap = {}; state.recipe_overrides = [];
  }
  let freshSessionId: string | null = null;
  let templateSessionId: string | null = null;
  try {
    const template = projectFile(snapshot, files.template ?? null);
    if (template) {
      const restored = await restoreProjectTemplate(template);
      templateSessionId = restored.session_id;
      state.projectResourceSessionIds = [templateSessionId];
      state.projectSettings = { ...state.projectSettings!, custom3mfTemplateId: restored.template_id };
    }
    if (model) {
      const upload = await uploadModelSurface(model);
      assertRestoreIsCurrent(context);
      state.modelSurfaceModelFileId = upload.model_file_id;
      state.modelSurfaceSummary = upload.summary;
      state.modelSurfaceCandidates = upload.surface_candidates;
      state.modelSurfaceWarnings = upload.warnings;
      if (payload.model.faceIndex !== null) {
        const rotation = payload.model.rotation;
        const selected = await selectModelSurface(upload.model_file_id, { face_index: payload.model.faceIndex, model_transform: { rotation_deg: { x: rotation.x_deg, y: rotation.y_deg, z: rotation.z_deg } } });
        assertRestoreIsCurrent(context);
        state.modelSurfaceSelectionId = selected.selection_id;
        state.modelSurfaceSelection = selected.selection;
        state.modelSurfaceFootprint = selected.footprint;
      }
    }
    if (image && payload.editor.hadPreview) {
      const source = buildConversionSourceParams(state);
      if (!source) throw new Error("Project color source is incomplete");
      const preview = await convertPreview(image, buildPreviewParams(state, resolveConverterSettings(state, useSettingsStore.getState()), source, state.replacement_regions), undefined, { lut, materials });
      freshSessionId = preview.session_id;
      assertRestoreIsCurrent(context);
      state = { ...state, ...previewResultState(state, preview) };
      if (editorFile) {
        const receipt = await restoreEditorProject(preview.session_id, editorFile, newProjectIdentity());
        if (receipt.status !== "committed" || !receipt.result?.preview_url) throw new Error("Project editor restore was not confirmed");
        state = { ...state, ...editorCommitResultStateFromResponse(state, preview.session_id, receipt.operation, receipt.result), pendingEditorProject: null };
      } else if (state.free_color_set.size) {
        await mutateFreeColors(preview.session_id, "replace", Array.from(state.free_color_set));
      }
      if (document.schemaVersion === 1) state = await replayLegacyConverter(document, state, context);
      const selection = await getEditorSelection(preview.session_id);
      state = { ...state, ...selectionStateFromDocument(selection, state.previewBaseImageUrl ?? "") };
      if (heightmap && state.enable_relief && state.autoHeightMode === "use-heightmap") {
        const result = await uploadHeightmap(heightmap, preview.session_id, state.heightmap_max_height);
        state.heightmapThumbnailUrl = result.thumbnail_url;
        state.heightmapUploadSessionId = preview.session_id;
        state.color_height_map = result.color_height_map;
      }
    }
    assertRestoreIsCurrent(context);
    return { snapshot, document, state, freshSessionId, templateSessionId, rollbackState: previous };
  } catch (error) {
    if (freshSessionId) await closeSession(freshSessionId);
    if (templateSessionId) await closeSession(templateSessionId);
    throw error;
  }
}

export function createConverterProjectAdapter(): ProjectAdapter {
  return {
    kind: KIND, capture,
    unavailable: async (document) => ![1, SCHEMA].includes(document.schemaVersion),
    assertReadyToReplace: () => {
      const state = useConverterStore.getState();
      if (state.isLoading || state.isGenerating || state.batchLoading || state.isCropping || state.modelSurfaceLoading || state.modelSurfaceSelecting || editorMutationPending(state) || converterDocumentHistory.store.getState().busy) throw new Error("Wait for the converter operation before opening another project");
    },
    subscribe: (listener) => converterDocumentHistory.store.subscribe((next, previous) => {
      if (next.position !== previous.position) listener();
    }),
    reset: () => {
      const current = useConverterStore.getState();
      current.commitProjectRestore({ ...DEFAULT_STATE, lutList: current.lutList, lutListFull: current.lutListFull, nativeBrandGroups: current.nativeBrandGroups, bedSizes: current.bedSizes });
      converterDocumentHistory.reset();
    },
    validate: (document) => { payloadOf(document); },
    enumerateDependencies: (document) => [...document.resourceRefs],
    prepareRestore,
    commitRestore: (prepared, context) => {
      assertRestoreIsCurrent(context);
      const { state, snapshot, document } = prepared as PreparedConverter;
      const original = projectFile(snapshot, payloadOf(document).files.original);
      if (state.imageFile && original) rememberDerivedImageSource(state.imageFile, original);
      state.imagePreviewUrl = state.imageFile ? URL.createObjectURL(state.imageFile) : null;
      state.modelSurfacePreviewUrl = state.modelSurfaceFile ? URL.createObjectURL(state.modelSurfaceFile) : null;
      converterDocumentHistory.replaceRuntime(() => useConverterStore.getState().commitProjectRestore(state));
    },
    rollbackRestore: async (prepared, context) => {
      assertRestoreIsCurrent(context);
      converterDocumentHistory.replaceRuntime(() => useConverterStore.getState().commitProjectRestore(prepared.rollbackState as ConverterState));
      const current = useConverterStore.getState();
      if (current.sessionId && !current.previewGlbUrl) current._pollAsyncGlb();
    },
    discardRestore: async (prepared) => {
      const { freshSessionId, templateSessionId, state } = prepared as PreparedConverter;
      if (freshSessionId) await closeSession(freshSessionId);
      if (templateSessionId) await closeSession(templateSessionId);
      for (const url of [state.imagePreviewUrl, state.modelSurfacePreviewUrl]) if (url?.startsWith("blob:")) URL.revokeObjectURL(url);
    },
    finalizeRestore: (prepared) => {
      converterDocumentHistory.reset();
      const previous = prepared.rollbackState as ConverterState;
      for (const url of [previous.imagePreviewUrl, previous.modelSurfacePreviewUrl]) if (url?.startsWith("blob:")) URL.revokeObjectURL(url);
      // Start derived work only after every workspace has committed. A failed
      // multi-workspace restore must never publish its temporary 3D result.
      const current = useConverterStore.getState();
      if (current.sessionId && !current.previewGlbUrl) current._pollAsyncGlb();
    },
    migration: (document) => document,
    normalizeForCompare: (document) => json(document.payload),
  };
}
