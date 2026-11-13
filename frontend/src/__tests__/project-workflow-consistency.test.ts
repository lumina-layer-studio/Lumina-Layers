import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../api/converter", async () => ({
  ...await vi.importActual<typeof import("../api/converter")>("../api/converter"),
  convertPreview: vi.fn(), getEditorSelection: vi.fn(), getGlbStatus: vi.fn(),
}));
vi.mock("../api/session", () => ({ closeSession: vi.fn().mockResolvedValue(undefined) }));
vi.mock("../project/resources", () => ({
  captureConverterResources: vi.fn().mockResolvedValue({ lut: null, materials: null }),
  captureProjectTemplate: vi.fn().mockResolvedValue(null), restoreProjectTemplate: vi.fn(),
}));
vi.mock("../api/materialCache", async () => ({
  ...await vi.importActual<typeof import("../api/materialCache")>("../api/materialCache"),
  fetchMaterialColorSuggestions: vi.fn(),
}));
vi.mock("../utils/saveGeneratedFile", () => ({ saveGeneratedFile: vi.fn().mockResolvedValue("saved") }));

import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { captureProjectSettings, resolveConverterSettings } from "../stores/converter/project";
import { createConverterProjectAdapter } from "../project/adapters/converterAdapter";
import { ProjectAdapterRegistry, projectAdapterRegistry } from "../project/adapters/registry";
import { createProjectSnapshot } from "../project/identity";
import { convertPreview, getEditorSelection, getGlbStatus } from "../api/converter";
import { fetchMaterialColorSuggestions } from "../api/materialCache";
import { applyImport, exportShareCard } from "../recipe/importFlow";
import * as exportRecipeModule from "../recipe/exportRecipe";
import * as pngMetadataModule from "../recipe/pngMetadata";
import * as projectFiles from "../project/files";
import { captureCurrentProject, exportCurrentProject, useProjectUi } from "../project/controller";
import { useProjectSessionStore } from "../stores/projectSessionStore";
import { captureGeneratedArtifactIdentity, isGeneratedArtifactIdentityCurrent } from "../stores/generatedArtifactInvalidation";

const beds = [
  { label: "P1S", printer_id: "bambu-p1s", width_mm: 256, height_mm: 256, is_default: false },
  { label: "H2D", printer_id: "bambu-h2d", width_mm: 350, height_mm: 320, is_default: false },
];

beforeEach(() => {
  vi.clearAllMocks();
  useConverterStore.setState({ ...DEFAULT_STATE });
  useSettingsStore.setState({ ...DEFAULT_SETTINGS, printerModel: "bambu-p1s" });
  useConverterStore.setState({
    bedSizes: beds, bed_label: "H2D", aspectRatio: null,
    projectSettings: captureProjectSettings({ ...DEFAULT_SETTINGS, printerModel: "bambu-h2d", nozzleSize: "0.2" }),
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("lets an H2D project use 300 mm even when daily printer is P1S", () => {
  useConverterStore.getState().setTargetWidthMm(300);
  expect(useConverterStore.getState().target_width_mm).toBe(300);
});

it("keeps artwork inside the project P1S bed when daily printer is H2D", () => {
  useSettingsStore.setState({ printerModel: "bambu-h2d" });
  useConverterStore.setState({ projectSettings: captureProjectSettings({ ...DEFAULT_SETTINGS, printerModel: "bambu-p1s" }), bed_label: "P1S" });
  useConverterStore.getState().setTargetWidthMm(300);
  expect(useConverterStore.getState().target_width_mm).toBe(256);
});

it("changes the project's printer without changing defaults or erasing valid editor content", () => {
  const defaults = useSettingsStore.getState();
  useConverterStore.setState({ sessionId: "edited", previewBaseImageUrl: "/edited.png", downloadUrl: "/old.3mf", target_width_mm: 300, target_height_mm: 200 });
  useConverterStore.getState().setProjectSettings({ printerModel: "bambu-p1s" });
  expect(useSettingsStore.getState()).toBe(defaults);
  expect(useConverterStore.getState()).toMatchObject({ target_width_mm: 256, target_height_mm: 200, bed_label: "P1S", downloadUrl: null });
});

it("preserves the authoritative editor when only the build plate changes", () => {
  useConverterStore.setState({ sessionId: "edited", previewBaseImageUrl: "/edited.png", downloadUrl: "/old.3mf" });
  useConverterStore.getState().setProjectSettings({ buildPlateId: "smooth-pei" });
  expect(useConverterStore.getState()).toMatchObject({ sessionId: "edited", previewBaseImageUrl: "/edited.png", downloadUrl: null });
});

it("keeps a bound project's preview and generated artifact when daily defaults change", () => {
  useConverterStore.setState({ sessionId: "edited", previewBaseImageUrl: "/edited.png", previewGlbUrl: "/edited.glb", downloadUrl: "/saved.3mf" });
  const identity = captureGeneratedArtifactIdentity("project-device", "project-plate", false);
  useSettingsStore.getState().setNozzleSize("0.2");
  expect(useConverterStore.getState()).toMatchObject({ sessionId: "edited", previewBaseImageUrl: "/edited.png", previewGlbUrl: "/edited.glb", downloadUrl: "/saved.3mf" });
  expect(isGeneratedArtifactIdentityCurrent(identity, "project-device", "project-plate")).toBe(true);
});

it("exports the displayed project's device in share-card metadata", async () => {
  useConverterStore.setState({ imageFile: new File(["image"], "art.png", { type: "image/png" }), previewImageUrl: "blob:preview" });
  vi.spyOn(exportRecipeModule, "buildCoverImage").mockResolvedValue({ blob: new Blob(["cover"], { type: "image/png" }), cover: { width: 32, height: 32, mime_type: "image/png" } });
  const embedded = vi.spyOn(pngMetadataModule, "embedRecipeInPng").mockResolvedValue(new Blob(["share"], { type: "image/png" }));
  await exportShareCard();
  expect(embedded.mock.calls[0][1].recipe.converter!.device).toMatchObject({ printer_id: "bambu-h2d", nozzle_size: "0.2" });
});

it("publishes the async 3D result after opening a saved project", async () => {
  useConverterStore.setState({ imageFile: new File(["source"], "art.png", { type: "image/png" }), source_version: "legacy", lut_name: "portable", lut_names: ["portable"] });
  const adapter = createConverterProjectAdapter();
  const captured = await adapter.capture();
  (captured.document.payload.editor as Record<string, unknown>).hadPreview = true;
  const snapshot = createProjectSnapshot({ name: "review", workflowKinds: ["converter"], documents: [captured.document], assets: captured.assets });
  useConverterStore.setState({ bedSizes: [], bedSizesLoading: true });
  vi.mocked(convertPreview).mockImplementation(async () => {
    // Startup catalogs arrive while the heavier project preview is preparing.
    useConverterStore.setState({ bedSizes: beds, bedSizesLoading: false });
    return { status: "ok", message: "ready", preview_glb_url: null, session_id: "fresh-review", preview_url: "/api/files/preview", palette: [], warnings: [], dimensions: { width: 4, height: 4 } };
  });
  vi.mocked(getEditorSelection).mockResolvedValue({ selection_revision: 0, content_revision: 0, editor_content_revision: 0, selected_pixel_count: 0, selected_component_count: 0, selected_color_hexes: [], region_ids: [], components: [], contours: [], can_undo: false, can_redo: false });
  vi.mocked(getGlbStatus).mockResolvedValue({ status: "ready", glb_url: "/api/files/restored.glb" } as never);
  await new ProjectAdapterRegistry([adapter]).restore(snapshot, { projectId: "p", revisionId: "r", runtimeEpoch: 1 });
  expect(useConverterStore.getState()).toMatchObject({ bedSizes: beds, bedSizesLoading: false, bed_label: "H2D" });
  await vi.waitFor(() => expect(useConverterStore.getState().previewGlbUrl).toBe("/api/files/restored.glb"), { timeout: 1500 });
});

it("finishes material suggestions when project grid differs from daily defaults", async () => {
  useConverterStore.setState({
    source_version: "material", selectedMaterialDirNames: ["PLA"],
    projectSettings: captureProjectSettings({ ...DEFAULT_SETTINGS, enableSolverCacheGridSelection: true, solverCacheGridResolution: 128 }),
  });
  useSettingsStore.setState({ enableSolverCacheGridSelection: false });
  const result = { suggestions: [] };
  vi.mocked(fetchMaterialColorSuggestions).mockResolvedValue(result as never);
  await useConverterStore.getState().fetchMaterialSuggestions("#123456");
  expect(useConverterStore.getState()).toMatchObject({ materialSuggestionsLoading: false, materialSuggestions: result });
});

it("does not keep the previous .lum device after importing a different recipe", async () => {
  useSettingsStore.setState({ printerModel: "bambu-p1s", nozzleSize: "0.4" });
  const source = new File(["other"], "other.png", { type: "image/png" });
  const recipe = await exportRecipeModule.buildFullRecipe(
    exportRecipeModule.exportConverterRecipe({ ...DEFAULT_STATE, target_width_mm: 100, target_height_mm: 100 }, useSettingsStore.getState()),
    { width: 32, height: 32, mime_type: "image/png" },
    await exportRecipeModule.buildRecipeAssets(source),
  );
  applyImport({ state: { target_width_mm: 100, target_height_mm: 100 }, assetFile: source, heightmapFile: null, warnings: [], recipe });
  expect(resolveConverterSettings(useConverterStore.getState(), useSettingsStore.getState()).printerModel).toBe("bambu-p1s");
});

it("does not announce a successful bundle export when the native dialog was canceled", async () => {
  useProjectSessionStore.getState().reset();
  useProjectUi.setState({ name: "Review", notice: null, limited: [] });
  vi.spyOn(projectAdapterRegistry, "capture").mockResolvedValue({
    document: { documentId: "converter.main", kind: "converter", schemaVersion: 2, payload: {}, inputRevisionIds: [], resourceRefs: [], requiredCapabilities: [] },
    assets: [],
  });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ fillRect() {}, fillText() {} } as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(callback => callback(new Blob(["cover"], { type: "image/png" })));
  const exported = vi.spyOn(projectFiles, "exportProjectBundle").mockResolvedValue("canceled");
  await exportCurrentProject();
  expect(exported).toHaveBeenCalledOnce();
  expect(useProjectUi.getState().notice).toBeNull();
});

it.each(["no canvas", "encoding failure", "encoding timeout"])("captures a valid engineering document despite %s", async (failure) => {
  useProjectSessionStore.getState().reset();
  useProjectUi.setState({ name: "No cover", limited: [] });
  vi.spyOn(projectAdapterRegistry, "capture").mockResolvedValue({
    document: { documentId: "converter.main", kind: "converter", schemaVersion: 2, payload: {}, inputRevisionIds: [], resourceRefs: [], requiredCapabilities: [] }, assets: [],
  });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(failure === "no canvas" ? null : { fillRect() {}, fillText() {} } as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(callback => { if (failure !== "encoding timeout") callback(null); });
  vi.useFakeTimers();
  const captured = captureCurrentProject();
  await vi.advanceTimersByTimeAsync(2500);
  const { snapshot } = await captured;
  expect(snapshot.documents["converter.main"]).toBeDefined();
  expect(snapshot.thumbnail).toBeNull();
});
