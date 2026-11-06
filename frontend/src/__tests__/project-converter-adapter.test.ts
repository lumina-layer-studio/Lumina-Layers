import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EditorCommitStatusResponse, PreviewResponse, SelectionDocumentResponse } from "../api/types";

vi.mock("../api/converter", async () => ({
  ...await vi.importActual<typeof import("../api/converter")>("../api/converter"),
  convertPreview: vi.fn(), exportEditorProject: vi.fn(), restoreEditorProject: vi.fn(), getEditorSelection: vi.fn(),
  uploadModelSurface: vi.fn(), selectModelSurface: vi.fn(),
  replaceColorsBatch: vi.fn(), mutateEditorSelection: vi.fn(),
}));
vi.mock("../api/session", () => ({ closeSession: vi.fn().mockResolvedValue(undefined) }));
vi.mock("../project/resources", () => ({ captureConverterResources: vi.fn(), captureProjectTemplate: vi.fn().mockResolvedValue(null), restoreProjectTemplate: vi.fn() }));

import { convertPreview, exportEditorProject, getEditorSelection, restoreEditorProject, selectModelSurface, uploadModelSurface, replaceColorsBatch, mutateEditorSelection } from "../api/converter";
import { closeSession } from "../api/session";
import { createConverterProjectAdapter } from "../project/adapters/converterAdapter";
import { ProjectAdapterRegistry } from "../project/adapters/registry";
import { parseProject, serializeProject } from "../project/archive";
import { createProjectSnapshot } from "../project/identity";
import { captureConverterResources } from "../project/resources";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { captureProjectSettings } from "../stores/converter/project";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

const selection: SelectionDocumentResponse = {
  selection_revision: 2, content_revision: 1, editor_content_revision: 3,
  selected_pixel_count: 2, selected_component_count: 1, selected_color_hexes: ["#112233"],
  region_ids: [], components: [], contours: [], can_undo: false, can_redo: false,
};
const preview: PreviewResponse = {
  status: "ok", message: "preview", preview_glb_url: null, warnings: [], session_id: "fresh",
  preview_url: "/api/files/preview", palette: [], dimensions: { width: 6, height: 4 },
};
const receipt: EditorCommitStatusResponse = {
  status: "committed", operation_id: "restore", editor_content_revision: 3,
  result: { preview_url: "/api/files/edited", region_replacement_count: 1, recipe_overrides: [], free_color_set: [] },
};
const adapter = createConverterProjectAdapter();
const registry = new ProjectAdapterRegistry([adapter]);

async function snapshot() {
  const captured = await adapter.capture();
  return parseProject(await serializeProject(createProjectSnapshot({ name: "Artwork", workflowKinds: ["converter"], documents: [captured.document], assets: captured.assets })));
}

beforeEach(() => {
  vi.clearAllMocks();
  useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  useConverterStore.setState({ ...DEFAULT_STATE, source_version: "legacy", lut_name: "portable", lut_names: ["portable"],
    imageFile: new File(["source"], "source.png", { type: "image/png" }),
    sessionId: "source", selectionDocument: selection, regionReplacementCount: 1,
    projectSettings: captureProjectSettings({ ...DEFAULT_SETTINGS, svgPixelsPerMm: 18, nozzleSize: "0.2" }),
  });
  vi.mocked(captureConverterResources).mockImplementation(async (state) => ({ lut: state.projectLutFile ?? new File(["real LUT snapshot bytes"], "source.lut.zip"), materials: null }));
  vi.mocked(exportEditorProject).mockResolvedValue(new File(["current editor"], "editor.json.gz", { type: "application/gzip" }));
  vi.mocked(getEditorSelection).mockResolvedValue(selection);
  vi.mocked(convertPreview).mockResolvedValue(preview);
  vi.mocked(restoreEditorProject).mockResolvedValue(receipt);
});

describe("Layers converter project adapter", () => {
  it("migrates an old ordered edit once and resaves the authoritative current checkpoint", async () => {
    const project = await snapshot();
    const doc = project.documents["converter.main"];
    const current = doc.payload;
    doc.schemaVersion = 1;
    doc.payload = {
      schemaVersion: 1, recipe: current.recipe,
      source: { primaryAssetId: "converter.image", projectLutAssetId: "converter.lut" },
      modelSurface: { enabled: false, sourceAssetId: null, modelRotation: {}, placement: {} },
      spatialEdits: { editOrder: [{ kind: "global-remap", mapping: { "112233": "aabbcc" } }], selectedRegions: [], recipeOverrides: [] },
    };
    vi.mocked(replaceColorsBatch).mockResolvedValue({ preview_url: "/api/files/migrated" } as never);
    vi.mocked(mutateEditorSelection).mockResolvedValue(selection);
    await registry.restore(project, { projectId: "p", revisionId: "r", runtimeEpoch: 1 });
    expect(replaceColorsBatch).toHaveBeenCalledWith("fresh", [{ selectedColor: "#112233", replacementColor: "#aabbcc" }]);
    expect(restoreEditorProject).not.toHaveBeenCalled();
    expect(useConverterStore.getState().previewBaseImageUrl).toBe("/api/files/migrated");
    const resaved = await snapshot();
    expect(resaved.documents["converter.main"].schemaVersion).toBe(2);
    expect(resaved.documents["converter.main"].payload).not.toHaveProperty("spatialEdits");
    expect(resaved.assets["converter.editor"]).toBeDefined();
  });
  it("restores in an empty library, retains project settings, and saves subsequent edits", async () => {
    const project = await snapshot();
    expect(exportEditorProject).toHaveBeenCalledWith("source", 3, 2);
    expect(JSON.stringify(project.documents)).not.toContain("/api/files/");
    expect(new TextDecoder().decode(project.assets["converter.editor"].data)).toBe("current editor");
    useConverterStore.setState({ ...DEFAULT_STATE, lutList: [], lutListFull: [], bedSizes: [
      { label: "Bambu Lab H2D", printer_id: "bambu-h2d", width_mm: 350, height_mm: 320, is_default: false },
    ] });
    await registry.restore(project, { projectId: project.project.projectId, revisionId: project.project.revisionId, runtimeEpoch: 1 });
    const restored = useConverterStore.getState();
    expect(restored.previewBaseImageUrl).toBe("/api/files/edited");
    expect(restored.regionReplacementCount).toBe(1);
    expect(restored.selectionDocument?.selected_pixel_count).toBe(2);
    expect(restored.projectSettings?.nozzleSize).toBe("0.2");
    expect(restored.bed_label).toBe("Bambu Lab H2D");
    expect(useSettingsStore.getState().nozzleSize).toBe(DEFAULT_SETTINGS.nozzleSize);
    expect(convertPreview).toHaveBeenCalledWith(expect.any(File), expect.objectContaining({ svg_pixels_per_mm: 18 }), undefined, expect.objectContaining({ lut: expect.any(File) }));
    expect(await restored.projectLutFile!.text()).toBe("real LUT snapshot bytes");
    vi.mocked(exportEditorProject).mockResolvedValue(new File(["edited again"], "editor.json.gz", { type: "application/gzip" }));
    const resaved = await snapshot();
    expect(new TextDecoder().decode(resaved.assets["converter.editor"].data)).toBe("edited again");
    expect(resaved.assets["converter.lut"].sha256).toBe(project.assets["converter.lut"].sha256);
  });

  it("leaves the previous editor intact and releases a failed fresh session", async () => {
    const project = await snapshot();
    useConverterStore.setState({ sessionId: "keep-me", imagePreviewUrl: "blob:keep" });
    vi.mocked(restoreEditorProject).mockRejectedValue(new Error("source binding differs"));
    await expect(registry.restore(project, { projectId: "p", revisionId: "r", runtimeEpoch: 1 })).rejects.toThrow("source binding differs");
    expect(useConverterStore.getState().sessionId).toBe("keep-me");
    expect(useConverterStore.getState().imagePreviewUrl).toBe("blob:keep");
    expect(closeSession).toHaveBeenCalledWith("fresh");
  });

  it("prepares a model-only draft using a fresh model and face selection", async () => {
    useConverterStore.setState({ imageFile: null, sessionId: null, regionReplacementCount: 0, selectionDocument: null,
      modelSurfaceEnabled: true, modelSurfaceFile: new File(["mesh"], "model.stl"),
      modelSurfaceModelFileId: "old-model-id", modelSurfaceSelection: { face_indices: [7] },
      modelSurfaceModelRotation: { x_deg: 10, y_deg: 20, z_deg: 30 },
      modelSurfacePlacement: { ...DEFAULT_STATE.modelSurfacePlacement, scale: 2 },
    });
    const project = await snapshot();
    expect(JSON.stringify(project.documents)).not.toContain("old-model-id");
    vi.mocked(uploadModelSurface).mockResolvedValue({ status: "ok", model_file_id: "fresh-model", summary: {} as never, surface_candidates: [], warnings: [] });
    vi.mocked(selectModelSurface).mockResolvedValue({ status: "ok", selection_id: "fresh-face", selection: { face_indices: [7] }, footprint: {}, warnings: [] });
    await registry.restore(project, { projectId: "p", revisionId: "r", runtimeEpoch: 1 });
    expect(selectModelSurface).toHaveBeenCalledWith("fresh-model", { face_index: 7, model_transform: { rotation_deg: { x: 10, y: 20, z: 30 } } });
    expect(useConverterStore.getState().modelSurfaceSelectionId).toBe("fresh-face");
    expect(useConverterStore.getState().modelSurfacePlacement.scale).toBe(2);
    expect(useConverterStore.getState().imageFile).toBeNull();
    expect(convertPreview).not.toHaveBeenCalled();
  });

  it("rejects stale preparation before publishing its session", async () => {
    const project = await snapshot();
    let current = true;
    vi.mocked(convertPreview).mockImplementation(async () => { current = false; return preview; });
    await expect(registry.restore(project, { projectId: "p", revisionId: "r", runtimeEpoch: 1, isCurrent: () => current })).rejects.toThrow("no longer current");
    expect(useConverterStore.getState().sessionId).toBe("source");
    expect(closeSession).toHaveBeenCalledWith("fresh");
  });
});
