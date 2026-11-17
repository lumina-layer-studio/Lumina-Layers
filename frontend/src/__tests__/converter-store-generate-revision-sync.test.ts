import { beforeEach, describe, expect, it, vi } from "vitest";
import { useConverterStore } from "../stores/converter";
import type { ExportMaterialSelection, SelectionDocumentResponse } from "../api/types";

vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>(
      "../api/converter",
    );
  return {
    ...actual,
    replacementHistory: vi.fn(),
    convertGenerate: vi.fn(),
    fetchExportMaterialSelection: vi.fn(),
    getEditorSelection: vi.fn(),
    getEditorCommitStatus: vi.fn(),
  };
});

import {
  convertGenerate,
  fetchExportMaterialSelection,
  getEditorSelection,
  replacementHistory,
} from "../api/converter";

const mockedReplacementHistory = vi.mocked(replacementHistory);
const mockedConvertGenerate = vi.mocked(convertGenerate);
const mockedFetchExportMaterialSelection = vi.mocked(fetchExportMaterialSelection);
const mockedGetEditorSelection = vi.mocked(getEditorSelection);

let sessionCounter = 0;

function document(
  editorRevision: number,
  selectionRevision = 1,
  contentRevision = 1,
): SelectionDocumentResponse {
  return {
    selection_revision: selectionRevision,
    content_revision: contentRevision,
    selected_pixel_count: 0,
    selected_component_count: 0,
    selected_color_hexes: [],
    region_ids: [],
    components: [],
    contours: [],
    can_undo: true,
    can_redo: false,
    editor_content_revision: editorRevision,
  };
}

function seedEditorState(): string {
  sessionCounter += 1;
  const sessionId = `generate-revision-${sessionCounter}`;
  useConverterStore.setState({
    sessionId,
    selectionDocument: document(1),
    previewRequestRevision: 1,
    previewImageUrl: "/api/files/preview-before.png",
    previewBaseImageUrl: "/api/files/preview-before.png",
    originalPreviewUrl: "/api/files/preview-before.png",
    colorRemapMap: {},
    replacement_regions: [],
    recipe_overrides: [],
    regionReplacementCount: 0,
    free_color_set: new Set<string>(),
    remapHistory: [],
    remapRedoHistory: [],
    historyCanUndo: true,
    historyCanRedo: false,
    historyBusy: false,
    replacePreviewLoading: false,
    contentCommitStatus: "idle",
    contentCommitOperationId: null,
    error: null,
    isGenerating: false,
    enable_relief: false,
    puzzleEnabled: false,
    largeFormatEnabled: false,
    batchMode: false,
    source_version: "legacy",
    lut_name: "test-lut",
  } as never);
  return sessionId;
}

function historyResponse(editorRevision: number) {
  return {
    status: "ok",
    preview_url: "/api/files/preview-after.png",
    replacement_regions: [],
    recipe_overrides: [],
    free_color_set: [],
    can_undo: false,
    can_redo: true,
    entry_kind: "selection",
    selection: null,
    editor_content_revision: editorRevision,
  } as never;
}

function revisionConflict(): Error {
  return Object.assign(new Error("Request failed with status code 409"), {
    response: {
      status: 409,
      data: {
        detail:
          "Visible content changed before generation started " +
          "(editor content revision mismatch); refresh the editor state and try again.",
      },
    },
  });
}

const generated = {
  status: "ok",
  message: "generated",
  download_url: "/api/files/result.3mf",
};

function sentRevisions(): unknown[] {
  return mockedConvertGenerate.mock.calls.map(
    (call) => (call[1] as { editor_content_revision?: number }).editor_content_revision,
  );
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

describe("generate editor content revision", () => {
  it.each([
    ["coating enabled", () => useConverterStore.getState().setEnableCoating(true)],
    ["coating height", () => useConverterStore.getState().setCoatingHeightMm(0.12)],
    ["backing plates", () => useConverterStore.getState().setBackingOutput("separate_project")],
  ] as const)("discards a late download after changing %s", async (_name, change) => {
    seedEditorState();
    useConverterStore.setState({ downloadUrl: null, enable_coating: false });
    let complete!: (value: Awaited<ReturnType<typeof convertGenerate>>) => void;
    mockedConvertGenerate.mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }));
    const generating = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mockedConvertGenerate).toHaveBeenCalledOnce());
    change();
    complete(generated as never);
    await generating;
    expect(useConverterStore.getState().downloadUrl).toBeNull();
  });

  it("sends the revision confirmed by an undo response without a selection", async () => {
    seedEditorState();
    mockedReplacementHistory.mockResolvedValueOnce(historyResponse(7));
    await useConverterStore.getState().undoColorRemap();

    mockedConvertGenerate.mockResolvedValueOnce(generated as never);
    await useConverterStore.getState().submitGenerate();

    expect(sentRevisions()).toEqual([7]);
    expect(useConverterStore.getState().error).toBeNull();
  });

  it("does not let a late selection document roll the revision back", async () => {
    seedEditorState();
    mockedReplacementHistory.mockResolvedValueOnce(historyResponse(7));
    await useConverterStore.getState().undoColorRemap();

    // Same selection/content version, older editor revision: accepted as a
    // selection refresh, but must not lower the revision used for generation.
    mockedGetEditorSelection.mockResolvedValueOnce(document(6, 2, 1));
    await useConverterStore.getState().hydrateSelectionDocument();

    mockedConvertGenerate.mockResolvedValueOnce(generated as never);
    await useConverterStore.getState().submitGenerate();

    expect(sentRevisions()).toEqual([7]);
  });

  it("never sends the visible-region content_revision as the editor revision", async () => {
    seedEditorState();
    const withoutEditorRevision = { ...document(1, 1, 42) };
    delete (withoutEditorRevision as Partial<SelectionDocumentResponse>)
      .editor_content_revision;
    useConverterStore.setState({ selectionDocument: withoutEditorRevision });

    mockedConvertGenerate.mockResolvedValueOnce(generated as never);
    await useConverterStore.getState().submitGenerate();

    expect(sentRevisions()[0]).not.toBe(42);
  });

  it("refreshes the committed revision and retries once after a 409 conflict", async () => {
    seedEditorState();
    mockedConvertGenerate
      .mockRejectedValueOnce(revisionConflict())
      .mockResolvedValueOnce(generated as never);
    mockedGetEditorSelection.mockResolvedValueOnce(document(9));

    await useConverterStore.getState().submitGenerate();

    expect(sentRevisions()).toEqual([1, 9]);
    const state = useConverterStore.getState();
    expect(state.error).toBeNull();
    expect(state.isGenerating).toBe(false);
    expect(state.downloadUrl).toBe("/api/files/result.3mf");
  });

  it("surfaces the error when the retry conflicts again", async () => {
    seedEditorState();
    mockedConvertGenerate
      .mockRejectedValueOnce(revisionConflict())
      .mockRejectedValueOnce(revisionConflict());
    mockedGetEditorSelection.mockResolvedValueOnce(document(9));

    await useConverterStore.getState().submitGenerate();

    expect(mockedConvertGenerate).toHaveBeenCalledTimes(2);
    const state = useConverterStore.getState();
    expect(state.error).toBeTruthy();
    expect(state.isGenerating).toBe(false);
  });
});
