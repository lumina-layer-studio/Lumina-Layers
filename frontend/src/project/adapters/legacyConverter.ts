import { applyRecipeOverride, detectRegion, getEditorSelection, mutateEditorSelection, regionReplace, regionReplaceBatch, regionRequantize, replaceColorsBatch, resetReplacements } from "../../api/converter";
import type { EditorCommitResult, VirtualMaterial } from "../../api/types";
import type { ConverterRecipe } from "../../recipe/types";
import { DEFAULT_STATE } from "../../stores/converter";
import { editorCommitResultStateFromResponse } from "../../stores/converter/editorState";
import { captureProjectSettings } from "../../stores/converter/project";
import type { ConverterState } from "../../stores/converter/types";
import { DEFAULT_SETTINGS } from "../../stores/settingsStore";
import type { JsonObject, WorkflowDocument } from "../types";
import type { ConverterPayload } from "./converterAdapter";
import { assertRestoreIsCurrent, type ProjectRestoreContext } from "./types";

type RecordValue = Record<string, unknown>;
function object(value: unknown): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid legacy project data");
  return value as RecordValue;
}
function array(value: unknown): unknown[] {
  if (!Array.isArray(value) || value.length > 10000) throw new Error("Invalid legacy edit list");
  return value;
}
function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("Invalid legacy edit coordinate");
  return value;
}
function hex(value: unknown): string {
  if (typeof value !== "string" || !/^#?[a-f\d]{6}$/i.test(value)) throw new Error("Invalid legacy edit colour");
  return `#${value.replace(/^#/, "")}`;
}

/** Read the old envelope once; all new captures use the current recipe/checkpoint. */
export function legacyConverterPayload(document: WorkflowDocument): ConverterPayload {
  const payload = object(document.payload);
  const source = object(payload.source);
  const model = object(payload.modelSurface);
  object(payload.spatialEdits);
  const recipe = object(payload.recipe) as unknown as ConverterRecipe;
  if (!recipe.device || !recipe.base || !recipe.color_ops) throw new Error("Legacy converter recipe is incomplete");
  if (recipe.device.custom_3mf_template_id) throw new Error("This old project did not embed its custom 3MF template. Open it in the original version and export its template first.");
  const ref = (value: unknown): string | null => {
    if (value === null || value === undefined) return null;
    if (typeof value !== "string" || !document.resourceRefs.includes(value)) throw new Error("Legacy project resource is missing");
    return value;
  };
  const settings = captureProjectSettings(DEFAULT_SETTINGS);
  Object.assign(settings, {
    printerModel: recipe.device.printer_id || settings.printerModel,
    slicerSoftware: recipe.device.slicer || settings.slicerSoftware,
    nozzleSize: recipe.device.nozzle_size || settings.nozzleSize,
    deviceProfileId: recipe.device.device_profile_id ?? settings.deviceProfileId,
    buildPlateId: recipe.device.build_plate_id ?? settings.buildPlateId,
    enableBaseLayerHeightModifier: recipe.device.enable_base_layer_height_modifier ?? settings.enableBaseLayerHeightModifier,
    enableWipeTowerAutoPlacement: recipe.device.enable_wipe_tower_auto_placement ?? settings.enableWipeTowerAutoPlacement,
    svgPixelsPerMm: recipe.base.svg_pixels_per_mm ?? settings.svgPixelsPerMm,
    materialDeltaE00Tolerance: recipe.source?.material_delta_e00_tolerance ?? settings.materialDeltaE00Tolerance,
  });
  return {
    recipe, settings,
    files: { primary: ref(source.primaryAssetId), original: null, heightmap: ref(source.heightmapAssetId), editor: null, lut: ref(source.projectLutAssetId), materials: ref(source.projectMaterialArchiveAssetId), model: ref(model.sourceAssetId), template: null, batch: [] },
    model: { enabled: model.enabled === true, faceIndex: model.selectedFaceIndex as number | null ?? null, rotation: { ...DEFAULT_STATE.modelSurfaceModelRotation, ...object(model.modelRotation) }, placement: { ...DEFAULT_STATE.modelSurfacePlacement, ...object(model.placement) } },
    nativeBrand: null,
    editor: { hadPreview: Boolean(source.primaryAssetId), batchMode: false, enableCrop: false, brushSizePx: DEFAULT_STATE.brushSizePx, colorRangeTolerance: DEFAULT_STATE.colorRangeTolerance, preferredSizeAxis: DEFAULT_STATE.preferredSizeAxis, selectionTool: DEFAULT_STATE.selectionTool },
    workshopSource: null,
  };
}

export function legacyHasOrderedEdits(document: WorkflowDocument): boolean {
  return array(object(document.payload.spatialEdits).editOrder ?? []).length > 0;
}

/** Replay into a private fresh session. Nothing touches the active editor until commit. */
export async function replayLegacyConverter(document: WorkflowDocument, initial: ConverterState, context: ProjectRestoreContext): Promise<ConverterState> {
  const spatial = object(document.payload.spatialEdits);
  const operations = array(spatial.editOrder ?? []).map(object);
  const session = initial.sessionId;
  if (!session) throw new Error("Legacy spatial edits require their original image");
  let state = initial;
  const apply = (result: EditorCommitResult, operation?: string) => {
    assertRestoreIsCurrent(context);
    state = { ...state, ...editorCommitResultStateFromResponse(state, session, operation, result) };
  };
  const region = async (raw: unknown) => {
    const value = object(raw);
    const result = await detectRegion(session, number(value.clickX), number(value.clickY));
    assertRestoreIsCurrent(context);
    return result.region_id;
  };
  const recipe = async (operation: RecordValue, refs: unknown[]) => {
    const ids = [];
    for (const ref of refs) ids.push(await region(ref));
    const values = array(operation.recipe).map(number);
    if (!values.length || values.length > 64 || values.some((v) => !Number.isSafeInteger(v) || v < 0) || typeof operation.layerOrder !== "string") throw new Error("Invalid legacy stack recipe");
    const materials = operation.virtualMaterials as VirtualMaterial[] | undefined;
    if (materials && (!Array.isArray(materials) || materials.some((v) => !v || typeof v.name !== "string" || !/^#?[a-f\d]{6}$/i.test(v.hex)))) throw new Error("Invalid legacy virtual material");
    apply(await applyRecipeOverride({ session_id: session, region_ids: ids, recipe: values, layer_order: operation.layerOrder, color_layers: Math.max(values.length, state.color_layers ?? values.length), layer_height_mm: state.layer_height_mm ?? 0.08, virtual_materials: materials }));
  };
  for (const operation of operations) {
    assertRestoreIsCurrent(context);
    switch (operation.kind) {
      case "global-remap":
        apply(await replaceColorsBatch(session, Object.entries(object(operation.mapping)).map(([source, target]) => ({ selectedColor: hex(source), replacementColor: hex(target) })))); break;
      case "region-replace":
        await region(operation.region);
        apply(await regionReplace(session, hex(operation.targetHex))); break;
      case "region-batch-replace":
        apply(await regionReplaceBatch(session, array(operation.regions).map((raw) => { const value = object(raw); return { clickX: number(value.clickX), clickY: number(value.clickY), replacementColor: hex(operation.targetHex) }; }))); break;
      case "gradient-replace":
        apply(await regionReplace(session, hex(operation.targetHex), { gradientGroupIndex: number(operation.groupIndex), ...(operation.regionIndex === undefined ? {} : { gradientRegionIndex: number(operation.regionIndex) }) })); break;
      case "gradient-batch-replace":
        apply(await regionReplaceBatch(session, array(operation.regions).map((raw) => { const value = object(raw); return { gradientGroupIndex: number(value.groupIndex), gradientRegionIndex: number(value.regionIndex), replacementColor: hex(operation.targetHex) }; }))); break;
      case "gradient-requantize":
        apply(await regionRequantize(session, array(operation.regions).map((raw) => { const value = object(raw); return { gradientGroupIndex: number(value.groupIndex), gradientRegionIndex: number(value.regionIndex) }; }), number(operation.localQuantizeColors))); break;
      case "recipe-override": await recipe(operation, array(operation.regions)); break;
      case "clear-replacements": apply(await resetReplacements(session), "reset_replacements"); break;
      default: throw new Error(`Unsupported legacy spatial operation: ${String(operation.kind)}`);
    }
  }
  const selected = array(spatial.selectedRegions ?? []).map(object);
  if (!operations.length) {
    for (const raw of array(spatial.recipeOverrides ?? [])) {
      const value = object(raw);
      const anchor = selected.find((item) => item.regionId === value.region_id);
      if (!anchor) throw new Error("The old project did not preserve this custom recipe's region coordinates");
      await recipe({ recipe: value.recipe, layerOrder: value.layer_order, virtualMaterials: value.virtual_materials }, [anchor]);
    }
  }
  let selection = await getEditorSelection(session);
  selection = await mutateEditorSelection({ session_id: session, operation: "clear", base_selection_revision: selection.selection_revision, content_revision: selection.content_revision });
  for (const anchor of selected) {
    selection = await mutateEditorSelection({ session_id: session, operation: "point-toggle", base_selection_revision: selection.selection_revision, content_revision: selection.content_revision, x: number(anchor.clickX), y: number(anchor.clickY) });
  }
  const oldSelection = spatial.selectionDocument as JsonObject | null;
  if (oldSelection && Number(oldSelection.selected_pixel_count) > 0 && selected.length === 0) throw new Error("The old project did not preserve its brush selection mask. Export a current editor checkpoint from the original version.");
  assertRestoreIsCurrent(context);
  return state;
}
