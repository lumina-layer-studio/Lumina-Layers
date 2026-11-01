import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GradientGroupsResponse } from "../api/types";

const mocks = vi.hoisted(() => ({
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  fetchGradientGroups: vi.fn(),
  replaceColorsBatch: vi.fn(),
}));

vi.mock("../api/converter", async () => ({
  ...await vi.importActual<typeof import("../api/converter")>("../api/converter"),
  ...mocks,
  fetchExportMaterialSelection: vi.fn(async () =>
    (await import("./fixtures/exportMaterialSelection")).READY_EXPORT_MATERIAL_SELECTION),
}));
vi.mock("../api/lut", async () => ({
  ...await vi.importActual<typeof import("../api/lut")>("../api/lut"),
  fetchSessionLutInfo: vi.fn().mockResolvedValue(null),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

const groups: GradientGroupsResponse = {
  session_id: "gradient-session",
  status: "ok",
  groups: [{
    group_index: 1,
    total_pixel_count: 100,
    material_colour_count: 2,
    material_colours: [
      { hex: "#413435", rgb: [65, 52, 53], pixel_count: 60 },
      { hex: "#51413c", rgb: [81, 65, 60], pixel_count: 40 },
    ],
    representative_hex: "#413435",
    representative_rgb: [65, 52, 53],
    boundary_pair_count: 1,
    regions: [],
  }],
};
const replaced = {
  status: "ok",
  message: "Updated",
  preview_url: "/api/files/merged.png",
  preview_3d_url: "/api/files/merged.glb",
  replacement_count: 1,
};

async function seed(enabled = true) {
  const { useConverterStore: store } = await import("../stores/converter");
  const { useSettingsStore: settings, DEFAULT_SETTINGS } = await import("../stores/settingsStore");
  settings.setState({ ...DEFAULT_SETTINGS, autoReplaceGradientBanding: enabled });
  store.setState({
    imageFile: new File(["<svg/>"], "gradient.svg", { type: "image/svg+xml" }),
    source_version: "material",
    selectedMaterialDirNames: ["test/white", "test/black"],
    materialBackingMaterialDirName: "test/white",
  });
  return { store, settings };
}

describe("automatic gradient replacement is part of preview completion", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    mocks.convertPreview.mockResolvedValue({
      status: "ok", message: "Preview", session_id: "gradient-session",
      preview_url: "/api/files/original.png", preview_glb_url: "/api/files/original.glb",
      palette: [], dimensions: { width: 2, height: 2 }, warnings: [],
    });
    mocks.convertGenerate.mockResolvedValue({
      status: "ok", message: "Generated", download_url: "/api/files/result.3mf",
    });
    mocks.fetchGradientGroups.mockResolvedValue(groups);
    mocks.replaceColorsBatch.mockResolvedValue(replaced);
  });

  it("holds preview and generation until the automatic replacement commits", async () => {
    const { store } = await seed();
    const groupRequest = deferred<GradientGroupsResponse>();
    const replacementRequest = deferred<typeof replaced>();
    mocks.fetchGradientGroups.mockReturnValue(groupRequest.promise);
    mocks.replaceColorsBatch.mockReturnValue(replacementRequest.promise);
    let completed = false;
    const preview = store.getState().submitPreview().then(() => { completed = true; });
    await vi.waitFor(() => expect(mocks.fetchGradientGroups).toHaveBeenCalled());
    expect(store.getState().isLoading).toBe(true);
    expect(completed).toBe(false);
    await store.getState().submitGenerate();
    expect(mocks.convertGenerate).not.toHaveBeenCalled();

    groupRequest.resolve(groups);
    await vi.waitFor(() => expect(mocks.replaceColorsBatch).toHaveBeenCalled());
    expect(store.getState().isLoading).toBe(true);
    expect(completed).toBe(false);
    replacementRequest.resolve(replaced);
    await preview;
    expect(store.getState().previewImageUrl).toBe("/api/files/merged.png");
    expect(store.getState().isLoading).toBe(false);
  });

  it("exports the final preview when starting the full pipeline without a session", async () => {
    const { store } = await seed();
    const replacementRequest = deferred<typeof replaced>();
    mocks.replaceColorsBatch.mockReturnValue(replacementRequest.promise);
    const pipeline = store.getState().submitFullPipeline();
    await vi.waitFor(() => expect(mocks.replaceColorsBatch).toHaveBeenCalled());
    expect(mocks.convertGenerate).not.toHaveBeenCalled();
    replacementRequest.resolve(replaced);
    await pipeline;
    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    expect(mocks.convertGenerate.mock.calls[0][1].replacement_regions).toEqual([
      expect.objectContaining({ matched_hex: "#51413c", replacement_hex: "#413435" }),
    ]);
  });

  it("does not perform edits when merely fetching gradient groups", async () => {
    const { store } = await seed();
    store.setState({ sessionId: "gradient-session" });
    await store.getState().fetchGradientGroups("gradient-session");
    expect(store.getState().gradientGroups).toEqual(groups.groups);
    expect(mocks.replaceColorsBatch).not.toHaveBeenCalled();
  });

  it("keeps preview usable without waiting for optional groups when automation is off", async () => {
    const { store } = await seed(false);
    const groupRequest = deferred<GradientGroupsResponse>();
    mocks.fetchGradientGroups.mockReturnValue(groupRequest.promise);
    await store.getState().submitPreview();
    expect(store.getState().isLoading).toBe(false);
    groupRequest.resolve(groups);
    await vi.waitFor(() => expect(store.getState().gradientGroups).toEqual(groups.groups));
    expect(mocks.replaceColorsBatch).not.toHaveBeenCalled();
  });

  it("does not edit a new session when the old group request arrives late", async () => {
    const { store } = await seed();
    const groupRequest = deferred<GradientGroupsResponse>();
    mocks.fetchGradientGroups.mockReturnValue(groupRequest.promise);
    const preview = store.getState().submitPreview();
    await vi.waitFor(() => expect(mocks.fetchGradientGroups).toHaveBeenCalled());
    store.setState({ sessionId: "new-session", isLoading: true });
    groupRequest.resolve(groups);
    await preview;
    expect(mocks.replaceColorsBatch).not.toHaveBeenCalled();
    expect(store.getState().sessionId).toBe("new-session");
    expect(store.getState().isLoading).toBe(true);
  });

  it("honors disabling automation while the group request is pending", async () => {
    const { store, settings } = await seed();
    const groupRequest = deferred<GradientGroupsResponse>();
    mocks.fetchGradientGroups.mockReturnValue(groupRequest.promise);
    const preview = store.getState().submitPreview();
    await vi.waitFor(() => expect(mocks.fetchGradientGroups).toHaveBeenCalled());
    settings.getState().setAutoReplaceGradientBanding(false);
    groupRequest.resolve(groups);
    await preview;
    expect(mocks.replaceColorsBatch).not.toHaveBeenCalled();
    expect(store.getState().previewImageUrl).toBe("/api/files/original.png");
    expect(store.getState().isLoading).toBe(false);
  });

  it("stops the full pipeline if the required automatic group analysis fails", async () => {
    const { store } = await seed();
    mocks.fetchGradientGroups.mockRejectedValue(new Error("group analysis unavailable"));
    await store.getState().submitFullPipeline();
    expect(mocks.convertGenerate).not.toHaveBeenCalled();
    expect(store.getState().isLoading).toBe(false);
    expect(store.getState().error).toBeTruthy();
  });
});
