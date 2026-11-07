import { beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"),
  default: { get: vi.fn(), post: vi.fn() },
  downloadResourceBlob: vi.fn(async () => new Blob(["actual output"], { type: "image/png" })),
}));
vi.mock("../api/session", () => ({ closeSession: vi.fn().mockResolvedValue(undefined) }));
vi.mock("../api/extractor", async () => ({ ...await vi.importActual<typeof import("../api/extractor")>("../api/extractor"), colorcheckerRelease: vi.fn().mockResolvedValue(undefined) }));

import apiClient from "../api/client";
import { ColorMode } from "../api/types";
import { closeSession } from "../api/session";
import { createWorkflowAdapters } from "../project/adapters/workflows";
import { ProjectAdapterRegistry } from "../project/adapters/registry";
import { createProjectSnapshot } from "../project/identity";
import { parseProject, serializeProject } from "../project/archive";
import { useWorkflowRuntime, workflowHeaders, workflowSettings } from "../project/workflowRuntime";
import { useCalibrationStore } from "../stores/calibrationStore";
import { useExtractorStore } from "../stores/extractorStore";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useFiveColorStore } from "../stores/fiveColorStore";
import { useLutManagerStore } from "../stores/lutManagerStore";
import { useLutCompareStore } from "../stores/lutCompareStore";
import { useLutDetailsStore } from "../stores/lutDetailsStore";
import { useVectorizerStore } from "../stores/vectorizerStore";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

const adapters = createWorkflowAdapters();
const resets = [
  () => useCalibrationStore.setState(useCalibrationStore.getInitialState()),
  () => useExtractorStore.setState(useExtractorStore.getInitialState()),
  () => useSingleStageStore.setState(useSingleStageStore.getInitialState()),
  () => useFiveColorStore.setState(useFiveColorStore.getInitialState()),
  () => useLutManagerStore.setState(useLutManagerStore.getInitialState()),
  () => useLutCompareStore.setState(useLutCompareStore.getInitialState()),
  () => useLutDetailsStore.setState(useLutDetailsStore.getInitialState()),
  () => useVectorizerStore.setState(useVectorizerStore.getInitialState()),
];
beforeEach(() => {
  vi.clearAllMocks();
  resets.forEach((reset) => reset());
  useWorkflowRuntime.setState({ workflows: {} });
  useSettingsStore.setState({ ...DEFAULT_SETTINGS, nozzleSize: "0.2" });
  vi.mocked(apiClient.get).mockResolvedValue({ data: new Blob(["checkpoint / calibrated pixels"]) });
  vi.mocked(apiClient.post).mockImplementation(async (url) => url === "/lut/project-source"
    ? { data: new Blob(["LUT bytes"]) }
    : { data: { session_id: "fresh-session", file_id: "fresh-colorchecker", urls: { lut_path: "/api/files/fresh-lut" } } });
});
async function roundtrip(kind: string) {
  const adapter = adapters.find((item) => item.kind === kind)!;
  const captured = await adapter.capture();
  const snapshot = await parseProject(await serializeProject(createProjectSnapshot({ name: kind, workflowKinds: [kind], documents: [captured.document], assets: captured.assets })));
  expect(JSON.stringify(snapshot.documents)).not.toContain("/api/files/");
  return { snapshot, restore: () => new ProjectAdapterRegistry([adapter]).restore(snapshot, { projectId: snapshot.project.projectId, revisionId: snapshot.project.revisionId, runtimeEpoch: 1 }), adapter };
}

describe("editable workflow projects", () => {
  it("keeps the loaded local catalog when creating a new LUT workspace", () => {
    const catalog = [{ name: "Local", color_mode: ColorMode.FOUR_COLOR_CMYW, path: "" }];
    useLutManagerStore.setState({ lutList: catalog, primaryName: "previous", filteredSecondaryOptions: ["old secondary"] });
    adapters.find(adapter => adapter.kind === "lut-manager")!.reset!();
    expect(useLutManagerStore.getState()).toMatchObject({ lutList: catalog, primaryName: "", filteredSecondaryOptions: [] });
  });

  it("refreshes local choices after restore while keeping the portable source", async () => {
    useLutManagerStore.setState({ primaryName: "Embedded", lutList: [{ name: "Embedded", color_mode: ColorMode.EIGHT_COLOR, path: "" }] });
    const project = await roundtrip("lut-manager");
    vi.mocked(apiClient.get).mockResolvedValue({ data: { luts: [{ name: "New local", color_mode: ColorMode.FOUR_COLOR_CMYW, path: "" }] } });
    await project.restore();
    await vi.waitFor(() => expect(useLutManagerStore.getState().lutList.map(item => item.name)).toEqual(["New local", "Embedded"]));
    expect(useLutManagerStore.getState().primaryName).toBe("Embedded");
    expect(workflowHeaders("lut-manager")).toEqual({ "X-Lumina-Project-Context": "fresh-session" });
  });
  it("rejects machine-local preferences before replacing a workflow", async () => {
    const { snapshot, adapter } = await roundtrip("calibration");
    const document = snapshot.documents["calibration.main"];
    (document.payload.settings as Record<string, unknown>).printerIp = "192.0.2.1";
    expect(() => adapter.validate(document)).toThrow("Invalid project settings");
    expect(useWorkflowRuntime.getState().workflows).toEqual({});
  });
  it("keeps calibration and gradient generation parameters with project output settings", async () => {
    useCalibrationStore.setState({ workflow: "single-stage", block_size: 9, singleStageLayerHeightMm: 0.1, materialDefault: "PETG", substrateDisplayName: "Warm white" });
    const project = await roundtrip("calibration");
    useCalibrationStore.setState(useCalibrationStore.getInitialState());
    useSettingsStore.setState({ nozzleSize: "0.4" });
    await project.restore();
    expect(useCalibrationStore.getState()).toMatchObject({ block_size: 9, singleStageLayerHeightMm: 0.1, materialDefault: "PETG", substrateDisplayName: "Warm white" });
    expect(workflowSettings("calibration").nozzleSize).toBe("0.2");
    expect(useSettingsStore.getState().nozzleSize).toBe("0.4");
  });
  it("recreates the extractor session and confirmed ColorChecker from bytes", async () => {
    useExtractorStore.setState({ imageFile: new File(["raw pixels"], "source.raw"), session_id: "expired", calibratedFullFileId: "expired-cc", colorchecker_phase: "done", corner_points: [[1, 2], [3, 4], [5, 6], [7, 8]], page1Extracted: true, manufacturer: "My PETG", paletteConfirmed: true });
    const project = await roundtrip("extractor");
    expect(JSON.stringify(project.snapshot.documents)).not.toContain("expired");
    useExtractorStore.setState(useExtractorStore.getInitialState());
    await project.restore();
    const state = useExtractorStore.getState();
    expect(state).toMatchObject({ session_id: "fresh-session", workspaceSessionId: "fresh-session", calibratedFullFileId: "fresh-colorchecker", page1Extracted: true, manufacturer: "My PETG", paletteConfirmed: true });
    expect(await state.imageFile?.text()).toBe("raw pixels");
    state.setManufacturer("Edited after reopen");
    const resaved = await roundtrip("extractor");
    await resaved.restore();
    expect(useExtractorStore.getState().manufacturer).toBe("Edited after reopen");
  });
  it("keeps both gradient photos, manual orientation, fit and calibrated source intent", async () => {
    useSingleStageStore.setState({ datasetFile: new File(["dataset"], "cards.zip"), whiteImageFile: new File(["white"], "white.png"), blackImageFile: new File(["black"], "black.png"), imageSource: "restored", whiteColorcheckerFileId: "old-white", blackColorcheckerFileId: "old-black", sessionId: "old-fit", materialName: "Cyan", manualWhiteAnchor: "tl", whiteCornerPoints: [[1, 2]], blackCornerPoints: [[5, 6]] });
    const project = await roundtrip("single-stage");
    useSingleStageStore.setState(useSingleStageStore.getInitialState());
    await project.restore();
    expect(useSingleStageStore.getState()).toMatchObject({ sessionId: "fresh-session", whiteColorcheckerFileId: "fresh-colorchecker", blackColorcheckerFileId: "fresh-colorchecker", imageSource: "restored", manualWhiteAnchor: "tl", whiteCornerPoints: [[1, 2]], blackCornerPoints: [[5, 6]] });
    expect(await useSingleStageStore.getState().blackImageFile?.text()).toBe("black");
  });
  it.each(["five-color", "lut-manager", "lut-compare", "lut-details"])("binds %s to its portable source in an empty library", async (kind) => {
    useFiveColorStore.setState({ lutName: "missing locally", selectedIndices: [1, 2, 0, 1, 2], collectedRecipes: [{ id: "recipe", label: "Favorite", selectedIndices: [1, 2, 0, 1, 2], resultHex: "#112233", baseColorNames: ["Cyan"], baseColorHexes: ["#00FFFF"] }] });
    useLutManagerStore.setState({ primaryName: "missing locally", secondaryNames: ["secondary"], dedupThreshold: 4.5 });
    useLutCompareStore.setState({ lutAName: "missing locally", lutBName: "secondary" });
    useLutDetailsStore.setState({ selectedLutName: "missing locally", loadedLutName: "missing locally", query: "Cyan" });
    const project = await roundtrip(kind);
    resets.slice(3, 7).forEach((reset) => reset());
    await project.restore();
    expect(workflowHeaders(kind)).toEqual({ "X-Lumina-Project-Context": "fresh-session" });
    expect(await useWorkflowRuntime.getState().workflows[kind].lutFiles["missing locally"].text()).toBe("LUT bytes");
    if (kind === "five-color") expect(useFiveColorStore.getState().collectedRecipes[0].label).toBe("Favorite");
    if (kind === "lut-manager") expect(useLutManagerStore.getState().dedupThreshold).toBe(4.5);
  });
  it("restores vectorization input, parameters and output without an expired URL", async () => {
    useVectorizerStore.getState().setImageFile(new File(["image"], "drawing.png"));
    useVectorizerStore.getState().setParam("curve_fit_error", 1.25);
    useVectorizerStore.setState({ result: { status: "ok", message: "done", svg_url: "/api/files/expired-svg", width: 300, height: 200, num_shapes: 40, num_colors: 3, palette: ["#112233"] } });
    const project = await roundtrip("vectorizer");
    useVectorizerStore.getState().reset();
    await project.restore();
    expect(useVectorizerStore.getState().params.curve_fit_error).toBe(1.25);
    expect(useVectorizerStore.getState().result?.svg_url).toMatch(/^blob:/);
    expect(await useVectorizerStore.getState().imageFile?.text()).toBe("image");
  });
  it("releases a newly restored checkpoint when opening becomes stale", async () => {
    useExtractorStore.setState({ session_id: "original" });
    const { snapshot, adapter } = await roundtrip("extractor");
    let current = true;
    vi.mocked(apiClient.post).mockImplementation(async () => { current = false; return { data: { session_id: "abandoned", urls: {} } }; });
    await expect(adapter.prepareRestore(snapshot, { projectId: snapshot.project.projectId, revisionId: snapshot.project.revisionId, runtimeEpoch: 1, isCurrent: () => current })).rejects.toThrow("no longer current");
    expect(useExtractorStore.getState().session_id).toBe("original");
    expect(closeSession).toHaveBeenCalledWith("abandoned");
  });
});
