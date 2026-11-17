import { buildPreviewParams } from "../stores/converter/requests";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { converterDocumentHistory, useConverterStore } from "../stores/converter";
import type {
  ColorReplacementItem,
  ExportMaterialSelection,
  RecipeOverrideItem,
  SelectionDocumentResponse,
} from "../api/types";

vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>(
      "../api/converter",
    );
  return {
    ...actual,
    resetReplacements: vi.fn(),
    applyRecipeOverride: vi.fn(),
    replacementHistory: vi.fn(),
    replaceColorsBatch: vi.fn(),
    convertGenerate: vi.fn(),
    fetchExportMaterialSelection: vi.fn(),
    getEditorSelection: vi.fn(),
    getEditorCommitStatus: vi.fn(),
  };
});

import {
  applyRecipeOverride,
  convertGenerate,
  fetchExportMaterialSelection,
  getEditorCommitStatus,
  getEditorSelection,
  replacementHistory,
  replaceColorsBatch,
  resetReplacements,
} from "../api/converter";

const mockedResetReplacements = vi.mocked(resetReplacements);
const mockedApplyRecipeOverride = vi.mocked(applyRecipeOverride);
const mockedReplacementHistory = vi.mocked(replacementHistory);
const mockedReplaceColorsBatch = vi.mocked(replaceColorsBatch);
const mockedConvertGenerate = vi.mocked(convertGenerate);
const mockedFetchExportMaterialSelection = vi.mocked(fetchExportMaterialSelection);
const mockedGetEditorCommitStatus = vi.mocked(getEditorCommitStatus);
const mockedGetEditorSelection = vi.mocked(getEditorSelection);

let sessionCounter = 0;

function document(revision: number, contentRevision = 1): SelectionDocumentResponse {
  return {
    selection_revision: revision,
    content_revision: contentRevision,
    selected_pixel_count: 0,
    selected_component_count: 0,
    selected_color_hexes: [],
    region_ids: [],
    components: [],
    contours: [],
    can_undo: true,
    can_redo: false,
    editor_content_revision: contentRevision,
  };
}

const previousReplacement: ColorReplacementItem = {
  quantized_hex: "#ff0000",
  matched_hex: "#ff0000",
  replacement_hex: "#00ff00",
};

const previousRecipe: RecipeOverrideItem = {
  region_id: "region-a",
  recipe: [1, 1, 1],
  layer_order: "Top2Bottom",
};

function seedEditorState(overrides: Record<string, unknown> = {}) {
  sessionCounter += 1;
  useConverterStore.setState({
    sessionId: `commit-reconciliation-${sessionCounter}`,
    selectionDocument: document(1, 1),
    previewRequestRevision: 1,
    previewImageUrl: "/api/files/preview-before.png",
    previewBaseImageUrl: "/api/files/preview-before.png",
    originalPreviewUrl: "/api/files/preview-before.png",
    previewGlbUrl: "/api/files/preview-before.glb",
    colorRemapMap: { ff0000: "00ff00" },
    replacement_regions: [previousReplacement],
    recipe_overrides: [previousRecipe],
    regionReplacementCount: 2,
    free_color_set: new Set(["abcdef"]),
    remapHistory: [{ ff0000: "0000ff" }],
    remapRedoHistory: [],
    layerImages: [
      { layer_index: 0, name: "L0", url: "/api/files/layer-before.png" },
    ],
    layerImagesSourceKey: "before",
    historyCanUndo: true,
    historyCanRedo: false,
    historyBusy: false,
    replacePreviewLoading: false,
    contentCommitStatus: "idle",
    contentCommitOperationId: null,
    error: null,
    source_version: "legacy",
    lut_name: "test-lut",
    ...overrides,
  } as never);
  converterDocumentHistory.reset();
  return `commit-reconciliation-${sessionCounter}`;
}

function expectPageStateUnchanged(
  before: ReturnType<typeof useConverterStore.getState>,
): void {
  const after = useConverterStore.getState();
  expect(after.sessionId).toBe(before.sessionId);
  expect(after.contentCommitStatus).toBe(before.contentCommitStatus);
  expect(after.contentCommitOperationId).toBe(before.contentCommitOperationId);
  expect(after.replacePreviewLoading).toBe(before.replacePreviewLoading);
  expect(after.historyBusy).toBe(before.historyBusy);
  expect(after.error).toBe(before.error);
  expect(after.previewImageUrl).toBe(before.previewImageUrl);
  expect(after.previewBaseImageUrl).toBe(before.previewBaseImageUrl);
  expect(after.previewGlbUrl).toBe(before.previewGlbUrl);
  expect(after.colorRemapMap).toEqual(before.colorRemapMap);
  expect(after.replacement_regions).toEqual(before.replacement_regions);
  expect(after.recipe_overrides).toEqual(before.recipe_overrides);
  expect(after.free_color_set).toEqual(before.free_color_set);
  expect(after.selectionDocument).toEqual(before.selectionDocument);
  expect(after.historyCanUndo).toBe(before.historyCanUndo);
  expect(after.historyCanRedo).toBe(before.historyCanRedo);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedFetchExportMaterialSelection.mockResolvedValue({
    ready: true,
    slicer_id: "BambuStudio",
    machine_uid: "bbl:bambu-lab-h2d",
    nozzle_uid: "nozzle:0.4mm",
    device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.4",
    machine_profile_id: "bbl:bambu-lab-h2d",
    build_plate_uid: "plate:textured-pei",
    materials: [],
    build_plates: [],
    issues: [],
  } satisfies ExportMaterialSelection);
});

describe("editor commit receipt business-state reconciliation", () => {
  it.each(["single", "batch", "gradient"].flatMap(mode => [false, true].map(delayed => ({ mode, delayed }))))("restores $mode remaps and exports on failure (delayed=$delayed)", async ({ mode, delayed }) => {
    seedEditorState({
      selectedColors: new Set(["00ff00"]),
      remapRedoHistory: [{ ff0000: "cccccc" }],
      threemfDiskPath: "/saved/model.3mf",
      downloadUrl: "/api/files/model.3mf",
      gradientGroups: [{ representative_hex: "#0000ff", material_colours: [{ hex: "#00ff00" }] }],
      contentCommitStatus: "committed",
    });
    const before = useConverterStore.getState();
    const beforePosition = converterDocumentHistory.store.getState().position;
    mockedReplaceColorsBatch.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: delayed ? "pending" : "failed", operation_id: "remap-operation", editor_content_revision: 1, visible_content_revision: 1,
    });

    if (mode === "single") before.applyColorRemap("00ff00", "0000ff");
    else if (mode === "batch") await before.applyBatchColorRemap("0000ff");
    else await before.applyAutoGradientReplace();
    await vi.waitFor(() => expect(useConverterStore.getState().contentCommitStatus).toBe(delayed ? "unknown" : "failed"));
    if (delayed) {
      expect(useConverterStore.getState().colorRemapMap).not.toEqual(before.colorRemapMap);
      mockedGetEditorCommitStatus.mockResolvedValueOnce({
        status: "failed", operation_id: "remap-operation", editor_content_revision: 1, visible_content_revision: 1,
      });
      await useConverterStore.getState().reconcileUnknownContentCommit();
    }

    const after = useConverterStore.getState();
    expect(after.contentCommitStatus).toBe("failed");
    expect(after.colorRemapMap).toEqual(before.colorRemapMap);
    expect(after.remapHistory).toEqual(before.remapHistory);
    expect(after.remapRedoHistory).toEqual(before.remapRedoHistory);
    expect(after.threemfDiskPath).toBe(before.threemfDiskPath);
    expect(after.downloadUrl).toBe(before.downloadUrl);
    expect(after.previewImageUrl).toBe(before.previewImageUrl);
    expect(converterDocumentHistory.store.getState().position).toBe(beforePosition);
  });

  it("prepares a queued single-color edit from the rolled-back map after a failed receipt", async () => {
    const sid = seedEditorState();
    const before = useConverterStore.getState();
    const beforePosition = converterDocumentHistory.store.getState().position;
    mockedReplaceColorsBatch.mockRejectedValue(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "pending", operation_id: "first-remap", editor_content_revision: 1, visible_content_revision: 1,
    });
    before.applyColorRemap("00ff00", "0000ff");
    await vi.waitFor(() => expect(useConverterStore.getState().contentCommitStatus).toBe("unknown"));
    before.applyColorRemap("00ff00", "ffffff");
    await Promise.resolve();
    expect(mockedReplaceColorsBatch).toHaveBeenCalledTimes(1);
    expect(useConverterStore.getState().colorRemapMap.ff0000).toBe("0000ff");
    mockedGetEditorCommitStatus.mockResolvedValue({
      status: "failed", operation_id: "remap", editor_content_revision: 1, visible_content_revision: 1,
    });
    await useConverterStore.getState().reconcileUnknownContentCommit();
    await vi.waitFor(() => {
      expect(mockedReplaceColorsBatch).toHaveBeenCalledTimes(2);
      expect(useConverterStore.getState().contentCommitStatus).toBe("failed");
    });
    expect(mockedReplaceColorsBatch).toHaveBeenLastCalledWith(sid, [
      { selectedColor: "#ff0000", replacementColor: "#ffffff" },
      { selectedColor: "#00ff00", replacementColor: "#ffffff" },
    ], expect.any(String));
    expect(useConverterStore.getState().colorRemapMap).toEqual(before.colorRemapMap);
    expect(converterDocumentHistory.store.getState().position).toBe(beforePosition);
  });

  it("restores the clear snapshot when a later receipt confirms failure", async () => {
    const sessionId = seedEditorState();
    mockedResetReplacements.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "pending",
      operation_id: "clear-operation",
      editor_content_revision: 1,
      visible_content_revision: 1,
    });

    await useConverterStore.getState().clearAllRemaps();
    await vi.waitFor(() => {
      expect(mockedGetEditorCommitStatus).toHaveBeenCalledWith(
        sessionId,
        expect.any(String),
      );
    });

    expect(useConverterStore.getState().contentCommitStatus).toBe("unknown");
    expect(useConverterStore.getState().colorRemapMap).toEqual({});

    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "failed",
      operation_id: "clear-operation",
      editor_content_revision: 1,
      visible_content_revision: 1,
    });
    await useConverterStore.getState().reconcileUnknownContentCommit();

    const state = useConverterStore.getState();
    expect(state.contentCommitStatus).toBe("failed");
    expect(state.colorRemapMap).toEqual({ ff0000: "00ff00" });
    expect(state.replacement_regions).toEqual([previousReplacement]);
    expect(state.recipe_overrides).toEqual([previousRecipe]);
    expect(state.previewBaseImageUrl).toBe("/api/files/preview-before.png");
    expect(state.previewGlbUrl).toBe("/api/files/preview-before.glb");
  });

  it("applies a committed recipe result when the HTTP response is lost", async () => {
    seedEditorState({ recipe_overrides: [] });
    mockedApplyRecipeOverride.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "committed",
      operation_id: "recipe-operation",
      editor_content_revision: 4,
      visible_content_revision: 4,
      selection_revision: 1,
      result: {
        preview_url: "/api/files/recipe-committed.png",
        preview_glb_url: "/api/files/recipe-committed.glb",
        recipe_overrides: [
          {
            region_id: "region-a",
            recipe: [3, 3, 3],
            layer_order: "Top2Bottom",
          },
        ],
        recipe_override_count: 1,
        region_replacement_count: 2,
        can_undo: true,
        can_redo: false,
      },
    } as never);
    mockedGetEditorSelection.mockResolvedValueOnce(document(1, 4));

    await useConverterStore
      .getState()
      .applyCustomRecipeOverride(["region-a"], [3, 3, 3]);

    const state = useConverterStore.getState();
    expect(state.contentCommitStatus).toBe("committed");
    expect(state.recipe_overrides).toEqual([
      {
        region_id: "region-a",
        recipe: [3, 3, 3],
        layer_order: "Top2Bottom",
      },
    ]);
    expect(state.previewBaseImageUrl).toBe("/api/files/recipe-committed.png");
    expect(state.previewGlbUrl).toBe("/api/files/recipe-committed.glb");
  });

  it("keeps the document history unchanged when a delayed recipe receipt confirms failure", async () => {
    seedEditorState({ recipe_overrides: [] });
    const beforePosition = converterDocumentHistory.store.getState().position;
    mockedApplyRecipeOverride.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "pending",
      operation_id: "recipe-failed-operation",
      editor_content_revision: 1,
      visible_content_revision: 1,
    });

    await useConverterStore
      .getState()
      .applyCustomRecipeOverride(["region-a"], [3, 3, 3]);
    expect(useConverterStore.getState().contentCommitStatus).toBe("unknown");
    expect(converterDocumentHistory.store.getState().position).toBe(beforePosition);

    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "failed",
      operation_id: "recipe-failed-operation",
      editor_content_revision: 1,
      visible_content_revision: 1,
    });
    await useConverterStore.getState().reconcileUnknownContentCommit();

    expect(useConverterStore.getState().contentCommitStatus).toBe("failed");
    expect(useConverterStore.getState().recipe_overrides).toEqual([]);
    expect(converterDocumentHistory.store.getState()).toMatchObject({ position: beforePosition, canUndo: false });
  });

  it("uses the committed undo result when preparing generation after sync", async () => {
    const sessionId = seedEditorState();
    mockedReplacementHistory.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "pending",
      operation_id: "undo-operation",
      editor_content_revision: 1,
      visible_content_revision: 1,
    });

    await useConverterStore.getState().undoColorRemap();
    expect(useConverterStore.getState().contentCommitStatus).toBe("unknown");

    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "committed",
      operation_id: "undo-operation",
      editor_content_revision: 5,
      visible_content_revision: 5,
      selection_revision: 1,
      result: {
        preview_url: "/api/files/undo-committed.png",
        replacement_regions: [],
        recipe_overrides: [],
        recipe_override_count: 0,
        region_replacement_count: 0,
        free_color_set: [],
        can_undo: false,
        can_redo: true,
      },
    } as never);
    mockedGetEditorSelection.mockResolvedValueOnce(document(1, 5));
    await useConverterStore.getState().reconcileUnknownContentCommit();

    mockedConvertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "generated",
      download_url: "/api/files/result.3mf",
    });
    await useConverterStore.getState().submitGenerate();

    expect(mockedConvertGenerate).toHaveBeenCalledWith(
      sessionId,
      expect.objectContaining({
        replacement_regions: undefined,
        recipe_overrides: undefined,
        free_color_set: undefined,
      }),
      expect.anything(),
    );
    expect(useConverterStore.getState().replacement_regions).toEqual([]);
    expect(useConverterStore.getState().recipe_overrides).toEqual([]);
    expect(useConverterStore.getState().free_color_set).toEqual(new Set());
  });

  it("keeps complete serialized receipt lists and preserves omitted business fields", async () => {
    seedEditorState({
      color_layers: 5,
      layer_height_mm: 0.08,
      materialDynamicRecipes: [],
      materialLayerBenefitCurve: [],
      materialLayerBenefitScope: "all_printable_pixels",
      materialLayerBenefitPixelCount: 4,
    });
    const recipeOverrides = Array.from({ length: 129 }, (_, index) => ({
      region_id: `region-${index}`,
      recipe: [index % 3],
      layer_order: "Top2Bottom" as const,
    }));
    const freeColors = Array.from(
      { length: 129 },
      (_, index) => `${index.toString(16).padStart(6, "0")}`,
    );
    const dynamicRecipe = {
      target_srgb: [1, 2, 3] as [number, number, number],
      matched_srgb: [1, 2, 3] as [number, number, number],
      actual_layer_count: 5,
      padding_layer_count: 0,
      actual_recipe_top_to_bottom: [0, 0, 0, 0, 0],
      print_recipe_top_to_bottom: [0, 0, 0, 0, 0],
      selected_delta_e00: 0,
      best_range_delta_e00: 0,
      fixed_max_delta_e00: 0,
      delta_e00_sacrifice: 0,
      layer_cap_options: [
        {
          max_effective_layer_count: 5,
          actual_layer_count: 5,
          matched_srgb: [1, 2, 3] as [number, number, number],
          actual_recipe_top_to_bottom: [0, 0, 0, 0, 0],
          print_recipe_top_to_bottom: [0, 0, 0, 0, 0],
          delta_e00: 0,
        },
      ],
    };
    mockedApplyRecipeOverride.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "committed",
      operation_id: "serialized-recipe-operation",
      operation: "apply_recipe_override",
      editor_content_revision: 4,
      visible_content_revision: 4,
      selection_revision: 1,
      // This mirrors the actual response-model serialization: optional fields
      // that were not published are present as null, while empty lists remain
      // meaningful business values.
      result: {
        preview_url: "/api/files/serialized-recipe.png",
        preview_glb_url: null,
        replacement_regions: null,
        recipe_overrides: recipeOverrides,
        recipe_override_count: 129,
        region_replacement_count: null,
        color_layers: null,
        layer_height_mm: null,
        gradient_groups: null,
        free_color_set: freeColors,
        can_undo: true,
        can_redo: false,
        material_dynamic_recipes: [dynamicRecipe],
        material_layer_benefit_curve: [
          {
            max_effective_layer_count: 5,
            weighted_mean_delta_e00: 0,
            marginal_delta_e00_reduction: 0,
          },
        ],
        material_layer_benefit_scope: "automatic_pixels",
        material_layer_benefit_pixel_count: 4,
      },
    } as never);
    mockedGetEditorSelection.mockResolvedValueOnce(document(1, 4));

    await useConverterStore
      .getState()
      .applyCustomRecipeOverride(["region-a"], [3, 3, 3]);

    const state = useConverterStore.getState();
    expect(state.contentCommitStatus).toBe("committed");
    expect(state.recipe_overrides).toHaveLength(129);
    expect(state.recipe_overrides.at(-1)?.region_id).toBe("region-128");
    expect(state.free_color_set.size).toBe(129);
    expect(state.free_color_set.has("000080")).toBe(true);
    expect(state.materialDynamicRecipes).toEqual([dynamicRecipe]);
    expect(state.materialLayerBenefitCurve).toHaveLength(1);
    expect(state.materialLayerBenefitScope).toBe("automatic_pixels");
    expect(state.materialLayerBenefitPixelCount).toBe(4);
    expect(state.color_layers).toBe(5);
    expect(state.layer_height_mm).toBe(0.08);
    expect(state.previewGlbUrl).toBe("/api/files/preview-before.glb");
  });

  it.each([
    { selectionOutcome: "resolve", bStatus: "pending" },
    { selectionOutcome: "resolve", bStatus: "unknown" },
    { selectionOutcome: "reject", bStatus: "pending" },
    { selectionOutcome: "reject", bStatus: "unknown" },
  ])(
    "does not let old selection reconciliation mutate session B",
    async ({ selectionOutcome, bStatus }) => {
      const sessionA = seedEditorState({ recipe_overrides: [] });
      mockedApplyRecipeOverride.mockRejectedValueOnce(new Error("response lost"));
      mockedGetEditorCommitStatus.mockResolvedValueOnce({
        status: "committed",
        operation_id: "session-a-recipe-operation",
        operation: "apply_recipe_override",
        editor_content_revision: 4,
        visible_content_revision: 4,
        selection_revision: 1,
        result: {
          preview_url: "/api/files/session-a.png",
          recipe_overrides: [
            {
              region_id: "region-a",
              recipe: [3, 3, 3],
              layer_order: "Top2Bottom",
            },
          ],
          recipe_override_count: 1,
          region_replacement_count: 2,
          can_undo: true,
          can_redo: false,
        },
      } as never);

      let resolveSelection!: (value: SelectionDocumentResponse) => void;
      let rejectSelection!: (reason?: unknown) => void;
      const selectionRequest = new Promise<SelectionDocumentResponse>(
        (resolve, reject) => {
          resolveSelection = resolve;
          rejectSelection = reject;
        },
      );
      mockedGetEditorSelection.mockReturnValueOnce(selectionRequest);

      const oldAction = useConverterStore
        .getState()
        .applyCustomRecipeOverride(["region-a"], [3, 3, 3]);
      await vi.waitFor(() => {
        expect(mockedGetEditorSelection).toHaveBeenCalledWith(sessionA);
      });

      seedEditorState({
        contentCommitStatus: bStatus,
        contentCommitOperationId: "session-b-operation",
        replacePreviewLoading: true,
        historyBusy: true,
        error: "session B is still reconciling",
        previewImageUrl: "/api/files/session-b.png",
        previewBaseImageUrl: "/api/files/session-b.png",
        previewGlbUrl: "/api/files/session-b.glb",
        colorRemapMap: { aabbcc: "112233" },
        replacement_regions: [
          {
            quantized_hex: "#aabbcc",
            matched_hex: "#aabbcc",
            replacement_hex: "#112233",
          },
        ],
        recipe_overrides: [
          {
            region_id: "region-b",
            recipe: [4, 4, 4],
            layer_order: "Top2Bottom",
          },
        ],
        free_color_set: new Set(["445566"]),
        selectionDocument: document(7, 7),
      });
      const beforeB = useConverterStore.getState();

      if (selectionOutcome === "resolve") {
        resolveSelection(document(2, 4));
      } else {
        rejectSelection(new Error("old selection read failed"));
      }
      await oldAction;

      expectPageStateUnchanged(beforeB);
    },
  );

  it("does not let a rejected old receipt query mark session B unknown", async () => {
    const sessionA = seedEditorState({ recipe_overrides: [] });
    mockedApplyRecipeOverride.mockRejectedValueOnce(new Error("response lost"));

    let rejectReceipt!: (reason?: unknown) => void;
    const receiptRequest = new Promise<never>((_, reject) => {
      rejectReceipt = reject;
    });
    mockedGetEditorCommitStatus.mockReturnValueOnce(receiptRequest);

    const oldAction = useConverterStore
      .getState()
      .applyCustomRecipeOverride(["region-a"], [3, 3, 3]);
    await vi.waitFor(() => {
      expect(mockedGetEditorCommitStatus).toHaveBeenCalledWith(
        sessionA,
        expect.any(String),
      );
    });

    seedEditorState({
      contentCommitStatus: "pending",
      contentCommitOperationId: "session-b-operation",
      replacePreviewLoading: true,
      historyBusy: true,
      error: "session B is still reconciling",
      previewImageUrl: "/api/files/session-b.png",
      previewBaseImageUrl: "/api/files/session-b.png",
      previewGlbUrl: "/api/files/session-b.glb",
      colorRemapMap: { aabbcc: "112233" },
      replacement_regions: [
        {
          quantized_hex: "#aabbcc",
          matched_hex: "#aabbcc",
          replacement_hex: "#112233",
        },
      ],
      recipe_overrides: [
        {
          region_id: "region-b",
          recipe: [4, 4, 4],
          layer_order: "Top2Bottom",
        },
      ],
      free_color_set: new Set(["445566"]),
      selectionDocument: document(7, 7),
    });
    const beforeB = useConverterStore.getState();

    rejectReceipt(new Error("old receipt query failed"));
    await oldAction;

    expectPageStateUnchanged(beforeB);
  });
});


it("publishes normal HTTP success scope before material reset and next preview", async () => {
  const scope = { shape: [1, 2], bits: "eJxrAAAAgQCB" };
  seedEditorState({
    replacement_regions: [], colorRemapMap: {}, recipe_overrides: [], regionReplacementCount: 0,
    palette: [{ quantized_hex: "010101", matched_hex: "112233", pixel_count: 1, percentage: 50 }],
    _pollAsyncGlb: vi.fn(),
  });
  mockedReplaceColorsBatch.mockResolvedValueOnce({
    status: "ok", message: "Replaced 1 colors in batch", preview_url: "/api/files/changed.png",
    replacement_count: 1, replacement_regions: [{ quantized_hex: "#112233", matched_hex: "#112233",
      replacement_hex: "#ff0000", source_scope: scope }],
    selection: document(2, 2), editor_content_revision: 2,
  });
  useConverterStore.getState().applyColorRemap("112233", "ff0000");
  await vi.waitFor(() => expect(useConverterStore.getState().replacement_regions[0]?.source_scope).toEqual(scope));
  expect(mockedGetEditorCommitStatus).not.toHaveBeenCalled();
  useConverterStore.getState().setLutName("");
  const after = useConverterStore.getState();
  expect(after.sessionId).toBeNull();
  expect(after.replacement_regions).toHaveLength(1);
  expect(after.replacement_regions[0].source_scope).toEqual(scope);
  const params = buildPreviewParams(after, DEFAULT_SETTINGS,
    { source_kind: "legacy_single", lut_name: "new-lut" }, after.replacement_regions);
  expect(JSON.parse(JSON.stringify(params)).replacement_regions[0].source_scope).toEqual(scope);
});
