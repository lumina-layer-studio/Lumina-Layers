import { beforeEach, describe, expect, it, vi } from "vitest";
import { useConverterStore } from "../stores/converter";
import type { ConverterState } from "../stores/converter";
import type {
  ColorReplaceResponse,
  RegionReplaceResponse,
  SelectionDocumentResponse,
} from "../api/types";

/*
 * Regression tests for :func:`confirmReplacement` when the pending
 * replacement was seeded by a Gradient Groups *region* button.
 *
 * The user's mental model is: "I picked a region, I picked a colour,
 * now repaint that one region." The classic ``select-all`` branch of
 * ``confirmReplacement`` however applies a whole-image ``hex → hex``
 * remap via ``POST /api/convert/replace-colors-batch`` — that's the "replace
 * cyan band → every skin pixel turns red" regression we are pinning
 * here. ``confirmReplacement`` must detect ``gradientSelection.kind ===
 * 'region'`` and route to the spatial ``applyGradientRegionPixelReplace``
 * action (backed by ``/region-replace`` with gradient scope) instead.
 * 确认 confirmReplacement 在 region 来源时走空间替换路径，而不是全图 hex 替换。
 */

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn(),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  fetchBedSizes: vi.fn(),
  uploadHeightmap: vi.fn(),
  fetchLutColors: vi.fn(),
  cropImage: vi.fn(),
  convertBatch: vi.fn(),
  replaceColorsBatch: vi.fn(),
  applyRecipeOverride: vi.fn(),
  colorHighlight: vi.fn(),
  detectRegion: vi.fn(),
  regionReplace: vi.fn(),
  getEditorCommitStatus: vi.fn().mockResolvedValue({
    status: "failed",
    operation_id: "test-operation",
    editor_content_revision: 0,
    visible_content_revision: 0,
  }),
  mutateEditorSelection: vi.fn(),
  resetReplacements: vi.fn(),
  autoDetectColors: vi.fn(),
  fetchGradientGroups: vi.fn(),
  fetchMaterialColorSuggestions: vi.fn(),
}));

import { regionReplace, replaceColorsBatch, mutateEditorSelection } from "../api/converter";

const mockRegionReplace = vi.mocked(regionReplace);
const mockReplaceColorsBatch = vi.mocked(replaceColorsBatch);
const mockMutateEditorSelection = vi.mocked(mutateEditorSelection);

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function seedStore(overrides: Partial<ConverterState> = {}) {
  useConverterStore.setState({
    sessionId: "sess-confirm",
    previewImageUrl: "/api/files/preview-old",
    previewBaseImageUrl: "/api/files/preview-old",
    previewGlbUrl: null,
    palette: [],
    colorRemapMap: {},
    remapHistory: [],
    replacePreviewLoading: false,
    error: null,
    regionReplacementCount: 0,
    selectionMode: "select-all",
    selectedColor: null,
    selectedColors: new Set(["aabbcc", "ddeeff"]),
    selectedRegions: [],
    gradientSelection: { kind: "region", groupIndex: 2, regionIndex: 3 },
    pendingReplacement: {
      sourceHex: "aabbcc",
      targetHex: "ff0000",
      mode: "select-all",
      sourceColors: ["aabbcc", "ddeeff"],
    },
    ...overrides,
  } as Partial<ConverterState>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("confirmReplacement · gradient-region scope", () => {
  it("routes to applyGradientRegionPixelReplace when gradientSelection.kind === 'region'", async () => {
    seedStore();
    const response: RegionReplaceResponse = {
      preview_url: "/api/files/preview-after.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    };
    mockRegionReplace.mockResolvedValue(response);

    await useConverterStore.getState().confirmReplacement();

    // Must call /region-replace with the gradient scope — not /replace-colors-batch.
    // 必须调 /region-replace 带 scope，不能调 /replace-colors-batch。
    expect(mockReplaceColorsBatch).not.toHaveBeenCalled();
    expect(mockRegionReplace).toHaveBeenCalledTimes(1);
    expect(mockRegionReplace).toHaveBeenCalledWith(
      "sess-confirm",
      "#ff0000",
      { gradientGroupIndex: 2, gradientRegionIndex: 3 },
      undefined,
      expect.any(String),
    );

    const state = useConverterStore.getState();
    expect(state.pendingReplacement).toBeNull();
    expect(state.previewImageUrl).toBe("/api/files/preview-after.png");
    expect(state.regionReplacementCount).toBe(1);
  });

  it("does NOT touch colorRemapMap when taking the gradient-region path", async () => {
    // colorRemapMap is a whole-image hex→hex mapping; polluting it with
    // a region-scoped edit would cause the 3D preview / future applies
    // to recolour every matching pixel — exactly what we are avoiding.
    // 空间替换不应污染 colorRemapMap，否则 3D 预览会把全图同色都改掉。
    seedStore({ colorRemapMap: { foo: "bar" } });
    mockRegionReplace.mockResolvedValue({
      preview_url: "/api/files/preview-after.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    await useConverterStore.getState().confirmReplacement();

    expect(useConverterStore.getState().colorRemapMap).toEqual({ foo: "bar" });
  });

  it("falls through to the classic select-all hex remap when gradientSelection is null", async () => {
    // Sanity: users who never touched the Gradient Groups panel still
    // get the original whole-image remap behaviour — this path is the
    // one we must not regress.
    // gradientSelection 为空时走原 select-all → /replace-colors-batch 路径。
    seedStore({
      gradientSelection: null,
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ff0000",
        mode: "select-all",
      },
      selectedColors: new Set<string>(),
      selectedColor: "aabbcc",
    });
    const response: ColorReplaceResponse = {
      status: "ok",
      message: "ok",
      preview_url: "/api/files/preview-after.png",
      replacement_count: 1,
    };
    mockReplaceColorsBatch.mockResolvedValue(response);

    await useConverterStore.getState().confirmReplacement();

    expect(mockRegionReplace).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(useConverterStore.getState().previewImageUrl).toBe(response.preview_url));
    expect(mockReplaceColorsBatch).toHaveBeenCalledWith("sess-confirm", [
      { selectedColor: "#aabbcc", replacementColor: "#ff0000" },
    ], expect.any(String));
    expect(useConverterStore.getState().colorRemapMap).toMatchObject({
      aabbcc: "ff0000",
    });
  });

  it("still uses the gradient-region path even when pending.mode is 'current'", async () => {
    // Defence in depth: some UI paths set mode='current'/'region' on the
    // pending payload even though the selection actually came from a
    // gradient region button. The scope branch must trigger on
    // ``gradientSelection.kind`` alone, not on pending.mode.
    // pending.mode 不等于 region 来源；以 gradientSelection 为唯一判据。
    seedStore({
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ff0000",
        mode: "current",
      },
    });
    mockRegionReplace.mockResolvedValue({
      preview_url: "/api/files/preview-after.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    await useConverterStore.getState().confirmReplacement();

    expect(mockReplaceColorsBatch).not.toHaveBeenCalled();
    expect(mockRegionReplace).toHaveBeenCalledTimes(1);
    expect(mockRegionReplace).toHaveBeenCalledWith(
      "sess-confirm",
      "#ff0000",
      { gradientGroupIndex: 2, gradientRegionIndex: 3 },
      undefined,
      expect.any(String),
    );
  });

  it("syncs the authoritative selection revision after selection-scoped replacement so clear-all still works", async () => {
    seedStore({
      gradientSelection: null,
      selectionDocument: {
        selection_revision: 7,
        content_revision: 10,
        selected_pixel_count: 4,
        selected_component_count: 1,
        selected_color_hexes: ["#aabbcc"],
        region_ids: ["__editor_selection__:7"],
        components: [
          {
            label: 1,
            region_id: "__editor_selection__:7",
            color_hex: "#aabbcc",
            pixel_count: 4,
            bbox: [0, 0, 2, 2],
            anchor: [0, 0],
          },
        ],
        contours: [],
        can_undo: false,
        can_redo: false,
      },
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ff0000",
        mode: "multi-select",
      },
    });
    mockRegionReplace.mockResolvedValue({
      preview_url: "/api/files/preview-after.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
      selection: {
        selection_revision: 7,
        content_revision: 42,
        selected_pixel_count: 4,
        selected_component_count: 1,
        selected_color_hexes: ["#ff0000"],
        region_ids: ["__editor_selection__:7"],
        components: [
          {
            label: 1,
            region_id: "__editor_selection__:7",
            color_hex: "#ff0000",
            pixel_count: 4,
            bbox: [0, 0, 2, 2],
            anchor: [0, 0],
          },
        ],
        contours: [],
        can_undo: true,
        can_redo: false,
      },
    });
    mockMutateEditorSelection.mockResolvedValue({
      selection_revision: 8,
      content_revision: 42,
      selected_pixel_count: 0,
      selected_component_count: 0,
      selected_color_hexes: [],
      region_ids: [],
      components: [],
      contours: [],
      can_undo: true,
      can_redo: false,
    });

    await useConverterStore.getState().confirmReplacement();
    await useConverterStore.getState().clearSelection();
    await Promise.resolve();

    expect(mockRegionReplace).toHaveBeenCalledWith(
      "sess-confirm",
      "#ff0000",
      undefined,
      7,
      expect.any(String),
    );
    expect(mockMutateEditorSelection).toHaveBeenCalledWith(
      expect.objectContaining({
        operation: "clear",
        base_selection_revision: 7,
        content_revision: 42,
      }),
    );
    expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBe(0);
  });

  it("does not commit a selection replacement from an older preview revision", async () => {
    const response = deferred<RegionReplaceResponse>();
    mockRegionReplace.mockReturnValueOnce(response.promise);
    seedStore({
      previewRequestRevision: 40,
      gradientSelection: null,
      selectionDocument: {
        selection_revision: 5,
        content_revision: 9,
        selected_pixel_count: 4,
        selected_component_count: 1,
        selected_color_hexes: ["#aabbcc"],
        region_ids: ["selected-region"],
        components: [
          {
            label: 1,
            region_id: "selected-region",
            color_hex: "#aabbcc",
            pixel_count: 4,
            bbox: [0, 0, 2, 2],
            anchor: [0, 0],
          },
        ],
        contours: [],
        can_undo: false,
        can_redo: false,
      },
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ff0000",
        mode: "multi-select",
      },
    });

    const request = useConverterStore.getState().confirmReplacement();
    useConverterStore.setState({
      previewRequestRevision: 41,
      previewImageUrl: "/api/files/new-revision.png",
      previewBaseImageUrl: "/api/files/new-revision.png",
      previewGlbUrl: "/api/files/new-revision.glb",
      replacePreviewLoading: false,
    });
    response.resolve({
      preview_url: "/api/files/stale-selection.png",
      preview_glb_url: "/api/files/stale-selection.glb",
      color_contours: null,
      message: "stale",
    });
    await request;

    expect(useConverterStore.getState()).toMatchObject({
      previewRequestRevision: 41,
      previewImageUrl: "/api/files/new-revision.png",
      previewBaseImageUrl: "/api/files/new-revision.png",
      previewGlbUrl: "/api/files/new-revision.glb",
      replacePreviewLoading: false,
    });
  });

  it.each(["clear", "point-toggle"] as const)(
    "does not replace any pixels when a queued %s leaves the selection empty",
    async (operation) => {
      const empty: SelectionDocumentResponse = {
        selection_revision: 2, content_revision: 10,
        selected_pixel_count: 0, selected_component_count: 0,
        selected_color_hexes: [], region_ids: [], components: [], contours: [],
        can_undo: true, can_redo: false,
      };
      seedStore({
        sessionId: `empty-selection-before-target-${operation}`,
        gradientSelection: null,
        selectionDocument: {
          ...empty, selection_revision: 1, selected_pixel_count: 4,
          selected_component_count: 1, selected_color_hexes: ["#aabbcc"],
        },
      });
      const selectionResponse = deferred<SelectionDocumentResponse>();
      mockMutateEditorSelection.mockReturnValueOnce(selectionResponse.promise);
      const selection = useConverterStore.getState().applySelectionMutation({ operation, x: 0, y: 0 });
      const replacement = useConverterStore.getState().confirmReplacement();
      await vi.waitFor(() => expect(mockMutateEditorSelection).toHaveBeenCalledOnce());
      expect(mockRegionReplace).not.toHaveBeenCalled();
      selectionResponse.resolve(empty);
      await Promise.all([selection, replacement]);
      expect(mockRegionReplace).not.toHaveBeenCalled();
      expect(mockReplaceColorsBatch).not.toHaveBeenCalled();
      expect(useConverterStore.getState()).toMatchObject({
        colorRemapMap: {}, regionReplacementCount: 0, error: null,
      });
    },
  );
});
