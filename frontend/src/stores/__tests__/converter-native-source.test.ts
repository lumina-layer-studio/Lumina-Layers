import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_STATE,
  resolveConverterSourceSelection,
  useConverterStore,
} from "../../stores/converter";
import { useSettingsStore } from "../../stores/settingsStore";
import * as lutApi from "../../api/lut";
import { ColorMode, ModelingMode, StructureMode } from "../../api/types";

const mocks = vi.hoisted(() => ({
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  convertGenerateLargeFormat: vi.fn(),
  convertGeneratePuzzle: vi.fn(),
  applyRecipeOverride: vi.fn(),
  getGlbStatus: vi.fn(),
  showBrowserCompletionNotification: vi.fn(),
  fetchExportMaterialSelection: vi.fn(),
}));

vi.mock("../../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../../api/converter")>(
    "../../api/converter",
  );
  return {
    ...actual,
    convertPreview: mocks.convertPreview,
    convertGenerate: mocks.convertGenerate,
    convertGenerateLargeFormat: mocks.convertGenerateLargeFormat,
    convertGeneratePuzzle: mocks.convertGeneratePuzzle,
    applyRecipeOverride: mocks.applyRecipeOverride,
    getGlbStatus: mocks.getGlbStatus,
    fetchExportMaterialSelection: mocks.fetchExportMaterialSelection,
  };
});

vi.mock("../../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../../api/lut")>(
    "../../api/lut",
  );
  return {
    ...actual,
    fetchLutInfo: vi.fn(),
    fetchLutCatalog: vi.fn(),
    fetchLutDetailsCatalog: vi.fn(),
  };
});

vi.mock("../../utils/browserNotifications", () => ({
  showBrowserCompletionNotification:
    mocks.showBrowserCompletionNotification,
}));

function resetStore(): void {
  useConverterStore.setState({
    ...DEFAULT_STATE,
    source_version: "legacy",
    lut_name: "",
    nativeBrandGroups: [],
    nativeBrandGroupsLoading: false,
    selectedNativeBrandKey: "",
    selectedNativeDbNames: [],
    legacyCatalogGroups: [],
    legacyCatalogLoading: false,
    selectedLegacyManufacturer: "",
  });
}

function makeDbOption(name: string) {
  return {
    name,
    path: `/${name}.json`,
    color_mode: "8-Color Max",
  };
}

function makePredictiveBrand() {
  return {
    brand_key: "brand-a",
    material_type: "PLA",
    vendor: "Vendor A",
    display_name: "Brand A",
    db_options: [makeDbOption("A1"), makeDbOption("A2")],
    default_db_names: ["A2"],
    package_name: "brand-a-package",
    model_name: "brand-a-model",
    supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
  };
}

function makeNonPredictiveBrand() {
  return {
    brand_key: "brand-b",
    material_type: "PLA",
    vendor: "Vendor B",
    display_name: "Vendor B PLA",
    db_options: [
      { name: "DB-B1", path: "/db-b1.json", color_mode: "4-Color (RYBW)" },
    ],
    default_db_names: ["DB-B1"],
    supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
  };
}

function makeLegacyDetailsCatalog() {
  return {
    groups: [
      {
        manufacturer: "Brand A",
        items: [
          {
            name: "legacy-a",
            path: "/legacy-a.npy",
            color_mode: ColorMode.FOUR_COLOR_RYBW,
            source_kind: "legacy_lookup",
            manufacturer: "Brand A",
            material_type: "",
            manufacturer_source: "metadata",
            material_source: "metadata",
            search_tokens: ["legacy", "a"],
          },
        ],
      },
      {
        manufacturer: "Brand B",
        items: [
          {
            name: "legacy-b",
            path: "/legacy-b.npy",
            color_mode: ColorMode.EIGHT_COLOR,
            source_kind: "legacy_lookup",
            manufacturer: "Brand B",
            material_type: "",
            manufacturer_source: "metadata",
            material_source: "metadata",
            search_tokens: ["legacy", "b"],
          },
        ],
      },
    ],
  };
}

function flushGlbPoll(timerStep = 600): Promise<void> {
  vi.advanceTimersByTime(timerStep);
  return Promise.resolve().then(() => Promise.resolve());
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function seedLegacyGenerateState(
  sessionId: string,
  overrides: Partial<ReturnType<typeof useConverterStore.getState>> = {},
): void {
  useConverterStore.setState({
    ...DEFAULT_STATE,
    source_version: "legacy",
    lut_name: "legacy-lut",
    sessionId,
    color_mode: ColorMode.FOUR_COLOR_RYBW,
    modeling_mode: ModelingMode.HIGH_FIDELITY,
    structure_mode: StructureMode.DOUBLE_SIDED,
    enable_relief: false,
    color_height_map: {},
    autoHeightMode: null,
    puzzleEnabled: false,
    largeFormatEnabled: false,
    enable_cloisonne: false,
    enable_coating: false,
    enable_fridge_magnet: false,
    fridge_magnets: [],
    replacement_regions: [],
    recipe_overrides: [],
    free_color_set: new Set<string>(),
    colorRemapMap: {},
    regionReplacementCount: 0,
    ...overrides,
  } as never);
}

describe("native bundle converter flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
    mocks.convertPreview.mockReset();
    mocks.convertGenerate.mockReset();
    mocks.convertGenerateLargeFormat.mockReset();
    mocks.convertGeneratePuzzle.mockReset();
    mocks.applyRecipeOverride.mockReset();
    mocks.getGlbStatus.mockReset();
    mocks.showBrowserCompletionNotification.mockReset();
    mocks.fetchExportMaterialSelection.mockReset().mockResolvedValue({
      ready: true, materials: [], issues: [], build_plates: [],
      slicer_id: "BambuStudio", machine_uid: "bambu-lab-a1",
      nozzle_uid: "nozzle:0.4mm", build_plate_uid: "textured-pei-plate",
    });
    useSettingsStore.setState({
      enableCompletionNotifications: false,
      language: "zh",
      preserveUploadFilenameFor3mf: false,
    });
  });

  it("resets selected DBs to the brand defaults when the brand changes", () => {
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [
        makePredictiveBrand(),
        {
          brand_key: "brand-b",
          material_type: "PLA",
          vendor: "Vendor B",
          display_name: "Brand B",
          db_options: [makeDbOption("B1"), makeDbOption("B2"), makeDbOption("B3")],
          default_db_names: ["B1", "B3"],
          supported_modes: [{ color_layers: 8, layer_height_mm: 0.12 }],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
    } as never);

    useConverterStore.getState().setNativeBrandKey("brand-b");

    const state = useConverterStore.getState();
    expect(state.selectedNativeBrandKey).toBe("brand-b");
    expect(state.selectedNativeDbNames).toEqual(["B1", "B3"]);
    expect(state.color_layers).toBe(8);
    expect(state.layer_height_mm).toBe(0.12);
  });

  it("resolves legacy and native source readiness in one place", () => {
    useConverterStore.setState({
      source_version: "legacy",
      lut_name: "legacy-lut",
    });
    expect(resolveConverterSourceSelection(useConverterStore.getState()).isReady).toBe(true);

    useConverterStore.setState({
      source_version: "native",
      lut_name: "",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          default_db_names: [],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: [],
    } as never);
    expect(resolveConverterSourceSelection(useConverterStore.getState()).isReady).toBe(false);

    useConverterStore.setState({ selectedNativeDbNames: ["A2"] } as never);
    expect(resolveConverterSourceSelection(useConverterStore.getState()).isReady).toBe(true);
  });

  it("falls back to brand defaults when persisted native DB names are all invalid", () => {
    useConverterStore.setState({
      source_version: "native",
      lut_name: "",
      nativeBrandGroups: [makePredictiveBrand()],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["STALE-DB"],
    } as never);

    const selection = resolveConverterSourceSelection(useConverterStore.getState());

    expect(selection.native.db_names).toEqual(["A2"]);
    expect(selection.isReady).toBe(true);
  });

  it("preserves an explicitly cleared native DB selection", () => {
    useConverterStore.setState({
      source_version: "native",
      lut_name: "",
      nativeBrandGroups: [makePredictiveBrand()],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: [],
    } as never);

    const selection = resolveConverterSourceSelection(useConverterStore.getState());

    expect(selection.native.db_names).toEqual([]);
    expect(selection.isReady).toBe(false);
  });

  it("defaults model controls when switching to a predictive native source", () => {
    useConverterStore.setState({
      source_version: "legacy",
      nativeBrandGroups: [makePredictiveBrand()],
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
    } as never);

    useConverterStore.getState().setSourceVersion("native");

    const state = useConverterStore.getState();
    expect(state.source_version).toBe("native");
    expect(state.model_enable).toBe(true);
    expect(state.model_only).toBe(false);
    expect(state.model_threshold).toBeNull();
    expect(state.model_margin).toBeNull();
  });

  it.each(["ok", "partial"])("retains available tiles and reports %s large-format results", async (status) => {
    mocks.convertGenerateLargeFormat.mockResolvedValue({
      status,
      message: "Generated 4 tiles",
      download_url: "http://localhost:8000/api/files/lf-zip",
      tile_count: 4,
      grid_cols: 2,
      grid_rows: 2,
      warnings: ["Raster fallback was used for this large-format SVG request."],
      failed_tiles: status === "partial" ? ["R2C2"] : [],
    });

    useConverterStore.setState({
      ...DEFAULT_STATE,
      source_version: "native",
      lut_name: "",
      sessionId: "session-large",
      largeFormatEnabled: true,
      isGenerating: false,
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      nativeBrandGroups: [makePredictiveBrand()],
      model_threshold: 0.42,
      model_margin: 1.25,
      model_enable: true,
      model_only: false,
    } as never);
    useSettingsStore.setState({
      enableCompletionNotifications: true,
      language: "en",
    });

    await useConverterStore.getState().submitGenerate();

    const state = useConverterStore.getState();
    expect(mocks.convertGenerateLargeFormat).toHaveBeenCalledOnce();
    const [, request] = mocks.convertGenerateLargeFormat.mock.calls[0];
    expect(request.target_height_mm).toBeUndefined();
    expect(request.params.model_threshold).toBe(0.42);
    expect(request.params.model_margin).toBe(1.25);
    expect(state.isGenerating).toBe(false);
    expect(state.downloadUrl).toBe("/api/files/lf-zip");
    expect(state.largeFormatWarnings).toEqual([
      "Raster fallback was used for this large-format SVG request.",
    ]);
    expect(state.largeFormatFailedTiles).toEqual(status === "partial" ? ["R2C2"] : []);
    if (status === "partial") {
      expect(mocks.showBrowserCompletionNotification).not.toHaveBeenCalled();
    } else {
      expect(mocks.showBrowserCompletionNotification).toHaveBeenCalledWith("generation", "en");
    }
  });

  it.each(["preview", "generate"] as const)(
    "keeps partial ZIP warnings during and after a failed %s retry",
    async (action) => {
      seedLegacyGenerateState("partial-session", {
        imageFile: new File(["png"], "partial.png", { type: "image/png" }),
        largeFormatEnabled: true,
        downloadUrl: "/api/files/partial.zip",
        largeFormatFailedTiles: ["R2C2"],
        largeFormatWarnings: ["Raster fallback"],
      });
      const response = deferred<never>();
      const requestMock = action === "preview"
        ? mocks.convertPreview
        : mocks.convertGenerateLargeFormat;
      requestMock.mockReturnValueOnce(response.promise);

      const request = action === "preview"
        ? useConverterStore.getState().submitPreview()
        : useConverterStore.getState().submitGenerate();
      await vi.waitFor(() => expect(requestMock).toHaveBeenCalledOnce());
      const pendingState = useConverterStore.getState();
      response.reject(new Error("Retry failed"));
      await request;

      for (const state of [pendingState, useConverterStore.getState()]) {
        expect(state.downloadUrl).toBe("/api/files/partial.zip");
        expect(state.largeFormatFailedTiles).toEqual(["R2C2"]);
        expect(state.largeFormatWarnings).toEqual(["Raster fallback"]);
      }
    },
  );

  it("keeps partial ZIP warnings when a successful preview retains the download", async () => {
    seedLegacyGenerateState("partial-session", {
      imageFile: new File(["png"], "partial.png", { type: "image/png" }),
      largeFormatEnabled: true,
      downloadUrl: "/api/files/partial.zip",
      largeFormatFailedTiles: ["R2C2"],
      largeFormatWarnings: ["Raster fallback"],
    });
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "new-preview-session", status: "ok", message: "Preview generated",
      preview_url: "/api/files/new-preview", preview_glb_url: "/api/files/new.glb",
      palette: [], dimensions: { width: 200, height: 160 },
    });
    await useConverterStore.getState().submitPreview();
    const state = useConverterStore.getState();
    expect(mocks.convertPreview).toHaveBeenCalledOnce();
    expect(state.sessionId).toBe("new-preview-session");
    expect(state.downloadUrl).toBe("/api/files/partial.zip");
    expect(state.largeFormatFailedTiles).toEqual(["R2C2"]);
    expect(state.largeFormatWarnings).toEqual(["Raster fallback"]);
  });

  it.each(["replace image", "remove image", "change databases"])(
    "clears partial ZIP warnings with its download when users %s",
    (action) => {
      seedLegacyGenerateState("partial-session", {
        imageFile: new File(["png"], "partial.png", { type: "image/png" }),
        largeFormatEnabled: true,
        downloadUrl: "/api/files/partial.zip",
        largeFormatFailedTiles: ["R2C2"],
        largeFormatWarnings: ["Raster fallback"],
      });
      if (action === "change databases") {
        useConverterStore.getState().setNativeDbNames(["A2"]);
      } else {
        useConverterStore.getState().setImageFile(action === "replace image"
          ? new File(["png"], "replacement.png", { type: "image/png" })
          : null);
      }
      const state = useConverterStore.getState();
      expect(state.sessionId).toBeNull();
      expect(state.downloadUrl).toBeNull();
      expect(state.largeFormatFailedTiles).toEqual([]);
      expect(state.largeFormatWarnings).toEqual([]);
    },
  );

  it("replaces partial ZIP warnings when generation succeeds completely", async () => {
    seedLegacyGenerateState("partial-session", {
      largeFormatEnabled: true,
      downloadUrl: "/api/files/partial.zip",
      largeFormatFailedTiles: ["R2C2"],
      largeFormatWarnings: ["Raster fallback"],
    });
    mocks.convertGenerateLargeFormat.mockResolvedValueOnce({
      status: "ok", message: "Generated 4 tiles",
      download_url: "/api/files/complete.zip", tile_count: 4,
      grid_cols: 2, grid_rows: 2, warnings: [], failed_tiles: [],
    });
    await useConverterStore.getState().submitGenerate();
    const state = useConverterStore.getState();
    expect(state.downloadUrl).toBe("/api/files/complete.zip");
    expect(state.largeFormatFailedTiles).toEqual([]);
    expect(state.largeFormatWarnings).toEqual([]);
  });

  it("submitGenerate omits recipe_overrides when local override state is empty", async () => {
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/legacy-model",
      preview_3d_url: "/api/files/legacy-model.glb",
    });

    useConverterStore.setState({
      ...DEFAULT_STATE,
      source_version: "legacy",
      lut_name: "legacy-lut",
      sessionId: "session-legacy",
      recipe_overrides: [],
    } as never);
    useSettingsStore.setState({
      enableCompletionNotifications: true,
      language: "zh",
    });

    await useConverterStore.getState().submitGenerate();

    const [, params] = mocks.convertGenerate.mock.calls.at(-1)!;
    expect(params.recipe_overrides).toBeUndefined();
    expect(mocks.showBrowserCompletionNotification).toHaveBeenCalledWith(
      "generation",
      "zh",
    );
  });

  it("ignores a stale regular generate response after the session changes", async () => {
    const stale = deferred<{
      status: string;
      message: string;
      download_url: string;
      threemf_disk_path: string;
      preview_3d_url: string;
    }>();
    mocks.convertGenerate
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce({
        status: "ok",
        message: "fresh",
        download_url: "/api/files/fresh.3mf",
        threemf_disk_path: "/tmp/fresh.3mf",
        preview_3d_url: "/api/files/fresh.glb",
      });

    seedLegacyGenerateState("session-old");
    const oldRequest = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());

    seedLegacyGenerateState("session-fresh");
    const freshRequest = useConverterStore.getState().submitGenerate();
    await freshRequest;

    expect(useConverterStore.getState().downloadUrl).toBe("/api/files/fresh.3mf");

    stale.resolve({
      status: "ok",
      message: "stale",
      download_url: "/api/files/stale.3mf",
      threemf_disk_path: "/tmp/stale.3mf",
      preview_3d_url: "/api/files/stale.glb",
    });
    await oldRequest;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBe("session-fresh");
    expect(state.downloadUrl).toBe("/api/files/fresh.3mf");
    expect(state.threemfDiskPath).toBeNull();
    expect(state.modelUrl).toBeNull();
    expect(state.isGenerating).toBe(false);
    expect(state.error).toBeNull();
  });

  it("invalidates an in-flight regular result when the build plate changes", async () => {
    const stale = deferred<{
      status: string;
      message: string;
      download_url: string;
      preview_3d_url: string;
    }>();
    const fresh = deferred<{
      status: string;
      message: string;
      download_url: string;
      preview_3d_url: string;
    }>();
    mocks.convertGenerate
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    useSettingsStore.setState({
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
      buildPlateId: "engineering-plate",
    });
    seedLegacyGenerateState("session-plate-race", {
      downloadUrl: "/api/files/previous-plate.3mf",
      threemfDiskPath: "/tmp/previous-plate.3mf",
      modelUrl: "/api/files/previous-plate.glb",
      previewGlbUrl: "/api/files/current-preview.glb",
    });

    const staleRequest = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());
    useSettingsStore
      .getState()
      .setBuildPlateForMachine(
        "BambuStudio:bbl:bambu-lab-h2d",
        "textured-pei-plate",
      );

    const stateAfterPlateChange = useConverterStore.getState();

    const freshRequest = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledTimes(2));
    expect(mocks.convertGenerate.mock.calls[0][1].build_plate_id).toBe(
      "engineering-plate",
    );
    expect(mocks.convertGenerate.mock.calls[1][1].build_plate_id).toBe(
      "textured-pei-plate",
    );

    stale.resolve({
      status: "ok",
      message: "stale",
      download_url: "/api/files/stale-plate.3mf",
      preview_3d_url: "/api/files/stale-plate.glb",
    });
    await staleRequest;

    const stateAfterStaleResponse = useConverterStore.getState();

    fresh.resolve({
      status: "ok",
      message: "fresh",
      download_url: "/api/files/fresh-plate.3mf",
      preview_3d_url: "/api/files/fresh-plate.glb",
    });
    await freshRequest;

    expect(stateAfterPlateChange).toMatchObject({
      isGenerating: false,
      downloadUrl: null,
      threemfDiskPath: null,
      modelUrl: "/api/files/previous-plate.glb",
      previewGlbUrl: "/api/files/current-preview.glb",
    });
    expect(stateAfterStaleResponse).toMatchObject({
      isGenerating: true,
      downloadUrl: null,
      modelUrl: "/api/files/previous-plate.glb",
      previewGlbUrl: "/api/files/current-preview.glb",
    });
    expect(useConverterStore.getState()).toMatchObject({
      isGenerating: false,
      downloadUrl: "/api/files/fresh-plate.3mf",
      previewGlbUrl: "/api/files/current-preview.glb",
    });
  });

  it("does not restore a color-card artifact generated for the previous plate", async () => {
    const pending = deferred<{
      status: string;
      message: string;
      download_url: string;
      preview_3d_url: string;
    }>();
    mocks.convertGenerate.mockReturnValueOnce(pending.promise);
    useSettingsStore.setState({
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
      buildPlateId: "engineering-plate",
    });
    seedLegacyGenerateState("color-card-plate", {
      modeling_mode: ModelingMode.COLOR_CARD,
    });

    const request = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());
    useSettingsStore
      .getState()
      .setBuildPlateForMachine(
        "BambuStudio:bbl:bambu-lab-h2d",
        "textured-pei-plate",
      );
    pending.resolve({
      status: "ok",
      message: "stale color card",
      download_url: "/api/files/stale-color-card.3mf",
      preview_3d_url: "/api/files/stale-color-card.glb",
    });
    await request;

    expect(useConverterStore.getState()).toMatchObject({
      isGenerating: false,
      downloadUrl: null,
      modelUrl: null,
    });
  });

  it("ignores an in-flight regular result when the filename preference changes", async () => {
    const pending = deferred<{
      status: string;
      message: string;
      download_url: string;
      preview_3d_url: string;
    }>();
    mocks.convertGenerate.mockReturnValueOnce(pending.promise);
    seedLegacyGenerateState("session-filename-preference", {
      modelUrl: "/api/files/existing-model.glb",
      previewGlbUrl: "/api/files/existing-preview.glb",
    });

    const request = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledWith(
      "session-filename-preference", expect.any(Object), false,
    ));

    useSettingsStore.getState().setPreserveUploadFilenameFor3mf(true);

    expect(useConverterStore.getState()).toMatchObject({
      isGenerating: false,
      downloadUrl: null,
      threemfDiskPath: null,
      modelUrl: "/api/files/existing-model.glb",
      previewGlbUrl: "/api/files/existing-preview.glb",
    });

    pending.resolve({
      status: "ok",
      message: "stale naming preference",
      download_url: "/api/files/stale-name.3mf",
      preview_3d_url: "/api/files/stale-name.glb",
    });
    await request;

    expect(useConverterStore.getState()).toMatchObject({
      isGenerating: false,
      downloadUrl: null,
      threemfDiskPath: null,
      modelUrl: "/api/files/existing-model.glb",
      previewGlbUrl: "/api/files/existing-preview.glb",
    });
  });

  it("invalidates a pending regular result after the page switches to puzzle mode", async () => {
    const pending = deferred<{
      status: string;
      message: string;
      download_url: string;
      preview_3d_url: string;
    }>();
    mocks.convertGenerate.mockReturnValueOnce(pending.promise);
    seedLegacyGenerateState("session-regular-before-puzzle", {
      modelUrl: "/api/files/existing-model.glb",
      previewGlbUrl: "/api/files/existing-preview.glb",
    });

    const request = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());

    useConverterStore.setState({ puzzleEnabled: true });
    useSettingsStore.getState().setPreserveUploadFilenameFor3mf(true);

    expect(useConverterStore.getState()).toMatchObject({
      isGenerating: false,
      downloadUrl: null,
      threemfDiskPath: null,
      modelUrl: "/api/files/existing-model.glb",
      previewGlbUrl: "/api/files/existing-preview.glb",
    });

    pending.resolve({
      status: "ok",
      message: "stale regular result",
      download_url: "/api/files/stale-regular.3mf",
      preview_3d_url: "/api/files/stale-regular.glb",
    });
    await request;

    expect(useConverterStore.getState()).toMatchObject({
      downloadUrl: null,
      threemfDiskPath: null,
      modelUrl: "/api/files/existing-model.glb",
      previewGlbUrl: "/api/files/existing-preview.glb",
    });
  });

  it("keeps a pending large-format result after the page exits large-format mode", async () => {
    const pending = deferred<{
      status: string;
      message: string;
      download_url: string;
      tile_count: number;
      grid_cols: number;
      grid_rows: number;
      warnings: string[];
    }>();
    mocks.convertGenerateLargeFormat.mockReturnValueOnce(pending.promise);
    seedLegacyGenerateState("session-large-before-ordinary", {
      largeFormatEnabled: true,
      modelUrl: "/api/files/existing-model.glb",
      previewGlbUrl: "/api/files/existing-preview.glb",
    });

    const request = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerateLargeFormat).toHaveBeenCalledOnce());

    useConverterStore.setState({ largeFormatEnabled: false });
    useSettingsStore.getState().setPreserveUploadFilenameFor3mf(true);

    expect(useConverterStore.getState()).toMatchObject({
      isGenerating: true,
      downloadUrl: null,
      modelUrl: "/api/files/existing-model.glb",
      previewGlbUrl: "/api/files/existing-preview.glb",
    });

    pending.resolve({
      status: "ok",
      message: "large-format result",
      download_url: "/api/files/large-result.zip",
      tile_count: 4,
      grid_cols: 2,
      grid_rows: 2,
      warnings: [],
    });
    await request;

    expect(useConverterStore.getState()).toMatchObject({
      isGenerating: false,
      downloadUrl: "/api/files/large-result.zip",
      threemfDiskPath: null,
    });
  });

  it("clears loading without applying a stale generate response after only the session changes", async () => {
    const stale = deferred<{
      status: string;
      message: string;
      download_url: string;
      threemf_disk_path: string;
      preview_3d_url: string;
    }>();
    mocks.convertGenerate.mockReturnValueOnce(stale.promise);
    useSettingsStore.setState({
      enableCompletionNotifications: true,
      language: "en",
    });

    seedLegacyGenerateState("session-old");
    const oldRequest = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());

    useConverterStore.setState({
      sessionId: "session-new",
      downloadUrl: null,
      threemfDiskPath: null,
      modelUrl: null,
      previewGlbUrl: null,
    });

    stale.resolve({
      status: "ok",
      message: "stale",
      download_url: "/api/files/stale-only.3mf",
      threemf_disk_path: "/tmp/stale-only.3mf",
      preview_3d_url: "/api/files/stale-only.glb",
    });
    await oldRequest;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBe("session-new");
    expect(state.downloadUrl).toBeNull();
    expect(state.threemfDiskPath).toBeNull();
    expect(state.modelUrl).toBeNull();
    expect(state.isGenerating).toBe(false);
    expect(state.error).toBeNull();
    expect(mocks.showBrowserCompletionNotification).not.toHaveBeenCalled();
  });

  it("does not notify when regular generation fails", async () => {
    mocks.convertGenerate.mockRejectedValueOnce(new Error("generation failed"));
    useSettingsStore.setState({
      enableCompletionNotifications: true,
      language: "en",
    });
    seedLegacyGenerateState("session-failure");

    await useConverterStore.getState().submitGenerate();

    expect(useConverterStore.getState().error).not.toBeNull();
    expect(mocks.showBrowserCompletionNotification).not.toHaveBeenCalled();
  });

  it("ignores a stale regular generate response from an older request in the same session", async () => {
    const stale = deferred<{
      status: string;
      message: string;
      download_url: string;
      threemf_disk_path: string;
      preview_3d_url: string;
    }>();
    mocks.convertGenerate
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce({
        status: "ok",
        message: "second",
        download_url: "/api/files/second.3mf",
        threemf_disk_path: "/tmp/second.3mf",
        preview_3d_url: "/api/files/second.glb",
      });

    seedLegacyGenerateState("session-same");
    const firstRequest = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());
    const secondRequest = useConverterStore.getState().submitGenerate();
    await secondRequest;

    stale.resolve({
      status: "ok",
      message: "first",
      download_url: "/api/files/first.3mf",
      threemf_disk_path: "/tmp/first.3mf",
      preview_3d_url: "/api/files/first.glb",
    });
    await firstRequest;

    const state = useConverterStore.getState();
    expect(state.downloadUrl).toBe("/api/files/second.3mf");
    expect(state.threemfDiskPath).toBeNull();
    expect(state.modelUrl).toBeNull();
    expect(state.error).toBeNull();
  });

  it("ignores stale generate failures after a newer generate succeeds", async () => {
    const stale = deferred<never>();
    mocks.convertGenerate
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce({
        status: "ok",
        message: "fresh",
        download_url: "/api/files/fresh-after-error.3mf",
        threemf_disk_path: "/tmp/fresh-after-error.3mf",
        preview_3d_url: "/api/files/fresh-after-error.glb",
      });

    seedLegacyGenerateState("session-error");
    const staleRequest = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());
    const freshRequest = useConverterStore.getState().submitGenerate();
    await freshRequest;

    stale.reject(new Error("old generate failed"));
    await staleRequest;

    const state = useConverterStore.getState();
    expect(state.downloadUrl).toBe("/api/files/fresh-after-error.3mf");
    expect(state.error).toBeNull();
    expect(state.isGenerating).toBe(false);
  });

  it("ignores a stale puzzle generate response after the session changes", async () => {
    const stale = deferred<{
      status: string;
      message: string;
      download_url: string;
      threemf_disk_path: string;
      piece_count: number;
      grid_cols: number;
      grid_rows: number;
      warnings: string[];
    }>();
    mocks.convertGeneratePuzzle
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce({
        status: "ok",
        message: "fresh puzzle",
        download_url: "/api/files/fresh-puzzle.3mf",
        threemf_disk_path: "/tmp/fresh-puzzle.3mf",
        piece_count: 4,
        grid_cols: 2,
        grid_rows: 2,
        warnings: [],
      });

    seedLegacyGenerateState("puzzle-old", { puzzleEnabled: true });
    const oldRequest = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGeneratePuzzle).toHaveBeenCalledOnce());

    seedLegacyGenerateState("puzzle-fresh", { puzzleEnabled: true });
    const freshRequest = useConverterStore.getState().submitGenerate();
    await freshRequest;

    stale.resolve({
      status: "ok",
      message: "stale puzzle",
      download_url: "/api/files/stale-puzzle.3mf",
      threemf_disk_path: "/tmp/stale-puzzle.3mf",
      piece_count: 9,
      grid_cols: 3,
      grid_rows: 3,
      warnings: ["stale"],
    });
    await oldRequest;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBe("puzzle-fresh");
    expect(state.downloadUrl).toBe("/api/files/fresh-puzzle.3mf");
    expect(state.threemfDiskPath).toBeNull();
    expect(state.puzzleResolvedPieceCount).toBe(4);
    expect(state.puzzleWarnings).toEqual([]);
  });

  it("does not restore a puzzle artifact generated for the previous plate", async () => {
    const pending = deferred<{
      status: string;
      message: string;
      download_url: string;
      threemf_disk_path: string;
      piece_count: number;
      grid_cols: number;
      grid_rows: number;
      warnings: string[];
    }>();
    mocks.convertGeneratePuzzle.mockReturnValueOnce(pending.promise);
    useSettingsStore.setState({
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
      buildPlateId: "engineering-plate",
    });
    seedLegacyGenerateState("puzzle-plate", { puzzleEnabled: true });

    const request = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGeneratePuzzle).toHaveBeenCalledOnce());
    useSettingsStore
      .getState()
      .setBuildPlateForMachine(
        "BambuStudio:bbl:bambu-lab-h2d",
        "textured-pei-plate",
      );
    pending.resolve({
      status: "ok",
      message: "stale puzzle",
      download_url: "/api/files/stale-puzzle-plate.3mf",
      threemf_disk_path: "/tmp/stale-puzzle-plate.3mf",
      piece_count: 4,
      grid_cols: 2,
      grid_rows: 2,
      warnings: ["stale"],
    });
    await request;

    expect(useConverterStore.getState()).toMatchObject({
      isGenerating: false,
      downloadUrl: null,
      puzzleResolvedPieceCount: null,
      puzzleWarnings: [],
    });
  });

  it("ignores a stale large-format generate response after the session changes", async () => {
    const stale = deferred<{
      status: string;
      message: string;
      download_url: string;
      tile_count: number;
      grid_cols: number;
      grid_rows: number;
      warnings: string[];
    }>();
    mocks.convertGenerateLargeFormat
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce({
        status: "ok",
        message: "fresh large-format",
        download_url: "/api/files/fresh-large.zip",
        tile_count: 4,
        grid_cols: 2,
        grid_rows: 2,
        warnings: [],
      });

    seedLegacyGenerateState("large-old", { largeFormatEnabled: true });
    const oldRequest = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerateLargeFormat).toHaveBeenCalledOnce());

    seedLegacyGenerateState("large-fresh", { largeFormatEnabled: true });
    const freshRequest = useConverterStore.getState().submitGenerate();
    await freshRequest;

    stale.resolve({
      status: "ok",
      message: "stale large-format",
      download_url: "/api/files/stale-large.zip",
      tile_count: 9,
      grid_cols: 3,
      grid_rows: 3,
      warnings: ["stale"],
    });
    await oldRequest;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBe("large-fresh");
    expect(state.downloadUrl).toBe("/api/files/fresh-large.zip");
    expect(state.largeFormatWarnings).toEqual([]);
  });

  it("does not restore a large-format artifact generated for the previous plate", async () => {
    const pending = deferred<{
      status: string;
      message: string;
      download_url: string;
      tile_count: number;
      grid_cols: number;
      grid_rows: number;
      warnings: string[];
    }>();
    mocks.convertGenerateLargeFormat.mockReturnValueOnce(pending.promise);
    useSettingsStore.setState({
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
      buildPlateId: "engineering-plate",
    });
    seedLegacyGenerateState("large-format-plate", {
      largeFormatEnabled: true,
    });

    const request = useConverterStore.getState().submitGenerate();
    await vi.waitFor(() => expect(mocks.convertGenerateLargeFormat).toHaveBeenCalledOnce());
    useSettingsStore
      .getState()
      .setBuildPlateForMachine(
        "BambuStudio:bbl:bambu-lab-h2d",
        "textured-pei-plate",
      );
    pending.resolve({
      status: "ok",
      message: "stale large-format",
      download_url: "/api/files/stale-large-format-plate.zip",
      tile_count: 4,
      grid_cols: 2,
      grid_rows: 2,
      warnings: ["stale"],
    });
    await request;

    expect(useConverterStore.getState()).toMatchObject({
      isGenerating: false,
      downloadUrl: null,
      largeFormatWarnings: [],
    });
  });

  it("defaults native layer count to 5 when entering native mode without a valid current selection", () => {
    useConverterStore.setState({
      source_version: "legacy",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
            { color_layers: 8, layer_height_mm: 0.12 },
          ],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      color_layers: null,
      layer_height_mm: null,
    } as never);

    useConverterStore.getState().setSourceVersion("native");

    const state = useConverterStore.getState();
    expect(state.source_version).toBe("native");
    expect(state.color_layers).toBe(5);
    expect(state.layer_height_mm).toBe(0.08);
  });

  it("prefers 5 layers when entering native mode with an invalid current pair and 5L is available", () => {
    useConverterStore.setState({
      source_version: "legacy",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
            { color_layers: 8, layer_height_mm: 0.12 },
          ],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      color_layers: 8,
      layer_height_mm: 0.08,
    } as never);

    useConverterStore.getState().setSourceVersion("native");

    const state = useConverterStore.getState();
    expect(state.color_layers).toBe(5);
    expect(state.layer_height_mm).toBe(0.08);
  });

  it("preserves a valid native selection when switching brands", () => {
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
            { color_layers: 8, layer_height_mm: 0.12 },
          ],
        },
        {
          brand_key: "brand-b",
          material_type: "PLA",
          vendor: "Vendor B",
          display_name: "Brand B",
          db_options: [makeDbOption("B1"), makeDbOption("B2")],
          default_db_names: ["B1"],
          supported_modes: [
            { color_layers: 8, layer_height_mm: 0.12 },
            { color_layers: 12, layer_height_mm: 0.12 },
          ],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      color_layers: 8,
      layer_height_mm: 0.12,
    } as never);

    useConverterStore.getState().setNativeBrandKey("brand-b");

    const state = useConverterStore.getState();
    expect(state.selectedNativeBrandKey).toBe("brand-b");
    expect(state.selectedNativeDbNames).toEqual(["B1"]);
    expect(state.color_layers).toBe(8);
    expect(state.layer_height_mm).toBe(0.12);
  });

  it("prefers 5 layers on brand switch when the current pair is invalid and 5L is available", () => {
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [
            { color_layers: 8, layer_height_mm: 0.12 },
          ],
        },
        {
          brand_key: "brand-b",
          material_type: "PLA",
          vendor: "Vendor B",
          display_name: "Brand B",
          db_options: [makeDbOption("B1")],
          default_db_names: ["B1"],
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
            { color_layers: 8, layer_height_mm: 0.08 },
          ],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      color_layers: 8,
      layer_height_mm: 0.12,
    } as never);

    useConverterStore.getState().setNativeBrandKey("brand-b");

    const state = useConverterStore.getState();
    expect(state.selectedNativeBrandKey).toBe("brand-b");
    expect(state.color_layers).toBe(5);
    expect(state.layer_height_mm).toBe(0.08);
  });

  it("normalizes native mode selection to a supported pair", () => {
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
            { color_layers: 8, layer_height_mm: 0.12 },
          ],
        },
      ],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      color_layers: 8,
      layer_height_mm: 0.08,
    } as never);

    const resolved = resolveConverterSourceSelection(useConverterStore.getState());
    expect(resolved.native?.supported_mode).toEqual({
      color_layers: 5,
      layer_height_mm: 0.08,
    });
    expect(resolved.color_layers).toBe(5);
    expect(resolved.layer_height_mm).toBe(0.08);
  });

  it("clears native dynamic values immediately when switching back to legacy LUTs", () => {
    vi.mocked(lutApi.fetchLutInfo).mockResolvedValueOnce({
      name: "legacy-lut",
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      color_count: 4,
    } as never);

    useConverterStore.setState({
      source_version: "native",
      color_layers: 8,
      layer_height_mm: 0.12,
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      nativeBrandGroups: [
        {
          ...makePredictiveBrand(),
          supported_modes: [{ color_layers: 8, layer_height_mm: 0.12 }],
        },
      ],
    } as never);

    useConverterStore.getState().setLutName("legacy-lut");

    const state = useConverterStore.getState();
    expect(state.source_version).toBe("legacy");
    expect(state.color_layers).toBeNull();
    expect(state.layer_height_mm).toBeNull();
    expect(state.selectedNativeBrandKey).toBe("");
    expect(state.selectedNativeDbNames).toEqual([]);
    expect(state.model_enable).toBe(false);
    expect(state.model_only).toBe(false);
    expect(state.model_threshold).toBeNull();
    expect(state.model_margin).toBeNull();
  });

  it.each([
    ["setLutName", "catalog"],
    ["setLutName", "async info"],
    ["setLegacyLutNames", "catalog"],
    ["setLegacyLutNames", "async info"],
  ] as const)(
    "clears vector relief when %s resolves 5-color from %s",
    async (setterName, source) => {
      const lutName = `legacy-five-${setterName}-${source}`;
      const hasCatalogColorMode = source === "catalog";
      vi.mocked(lutApi.fetchLutInfo).mockResolvedValueOnce({
        name: lutName,
        color_mode: ColorMode.FIVE_COLOR_EXT,
        color_count: 5,
      } as never);
      useConverterStore.setState({
        lutListFull: hasCatalogColorMode
          ? [
              {
                name: lutName,
                color_mode: ColorMode.FIVE_COLOR_EXT,
                path: `/${lutName}.npy`,
              },
            ]
          : [],
        lutColorsLutName: lutName,
        modeling_mode: ModelingMode.VECTOR,
        structure_mode: StructureMode.SINGLE_SIDED,
        color_mode: ColorMode.FOUR_COLOR_RYBW,
      } as never);
      useConverterStore.getState().setEnableRelief(true);

      if (setterName === "setLutName") {
        useConverterStore.getState().setLutName(lutName);
      } else {
        useConverterStore.getState().setLegacyLutNames([lutName]);
      }
      if (!hasCatalogColorMode) {
        expect(useConverterStore.getState().enable_relief).toBe(true);
        await Promise.resolve();
        await Promise.resolve();
      }

      expect(useConverterStore.getState().color_mode).toBe(
        ColorMode.FIVE_COLOR_EXT,
      );
      expect(useConverterStore.getState().enable_relief).toBe(false);
    },
  );

  it("normalizes legacy 8-Color LUT info before storing state and sending requests", async () => {
    vi.mocked(lutApi.fetchLutInfo).mockResolvedValueOnce({
      name: "legacy-eight",
      color_mode: "8-Color",
      color_count: 8,
    } as never);
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-eight",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/eight-preview",
      preview_glb_url: null,
      palette: [],
      dimensions: { width: 200, height: 160 },
    });
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/eight-model",
      preview_3d_url: "/api/files/eight-model.glb",
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "legacy-eight.png", { type: "image/png" }),
      source_version: "legacy",
      lutListFull: [
        {
          name: "legacy-eight",
          color_mode: "8-Color",
          path: "/legacy-eight.npy",
        },
      ],
      target_width_mm: 90,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      separate_backing: false,
      add_loop: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      enable_relief: false,
      heightmap_max_height: 5.0,
      enable_outline: false,
      outline_width: 2.0,
      enable_cloisonne: false,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: false,
      coating_height_mm: 0.08,
    } as never);

    useConverterStore.getState().setLutName("legacy-eight");
    await Promise.resolve();

    expect(useConverterStore.getState().color_mode).toBe(ColorMode.EIGHT_COLOR);

    await useConverterStore.getState().submitPreview();
    const previewParams = mocks.convertPreview.mock.calls[0][1];
    expect(previewParams.color_mode).toBe(ColorMode.EIGHT_COLOR);

    await useConverterStore.getState().submitGenerate();
    const generateParams = mocks.convertGenerate.mock.calls[0][1];
    expect(generateParams.color_mode).toBe(ColorMode.EIGHT_COLOR);
  });

  it("keeps legacy multi-select names across color-mode buckets", () => {
    vi.mocked(lutApi.fetchLutInfo).mockResolvedValueOnce({
      name: "legacy-rybw",
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      color_count: 4,
    } as never);

    useConverterStore.setState({
      legacyCatalogGroups: [
        {
          manufacturer: "Brand A",
          items: [
            {
              name: "A RYBW",
              path: "/legacy-rybw.npy",
              color_mode: ColorMode.FOUR_COLOR_RYBW,
              compatibility_key: "sig-rybw",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["rybw"],
            },
            {
              name: "A RYBW Alt",
              path: "/legacy-rybw-alt.npy",
              color_mode: ColorMode.FOUR_COLOR_RYBW,
              compatibility_key: "sig-rybw",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["rybw", "alt"],
            },
            {
              name: "A 8C",
              path: "/legacy-eight.npy",
              color_mode: ColorMode.EIGHT_COLOR,
              compatibility_key: "sig-eight",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["eight"],
            },
          ],
        },
      ],
      lutListFull: [
        {
          name: "legacy-rybw",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          path: "/legacy-rybw.npy",
        },
        {
          name: "legacy-eight",
          color_mode: ColorMode.EIGHT_COLOR,
          path: "/legacy-eight.npy",
        },
        {
          name: "legacy-rybw-alt",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          path: "/legacy-rybw-alt.npy",
        },
      ],
    } as never);

    useConverterStore.getState().setLegacyLutNames([
      "legacy-rybw",
      "legacy-eight",
      "legacy-rybw-alt",
    ]);

    const state = useConverterStore.getState();
    expect(state.lut_name).toBe("legacy-rybw");
    expect(state.lut_names).toEqual([
      "legacy-rybw",
      "legacy-eight",
      "legacy-rybw-alt",
    ]);
    expect(state.selectedLegacyManufacturer).toBe("Brand A");
  });

  it("keeps same-color-mode legacy names when compatibility keys differ", () => {
    vi.mocked(lutApi.fetchLutInfo).mockResolvedValueOnce({
      name: "legacy-a",
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      color_count: 4,
    } as never);

    useConverterStore.setState({
      legacyCatalogGroups: [
        {
          manufacturer: "Brand A",
          items: [
            {
              name: "A RYBW",
              path: "/legacy-a.npy",
              color_mode: ColorMode.FOUR_COLOR_RYBW,
              compatibility_key: "sig-a",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["a"],
            },
            {
              name: "B RYBW",
              path: "/legacy-b.npy",
              color_mode: ColorMode.FOUR_COLOR_RYBW,
              compatibility_key: "sig-b",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["b"],
            },
          ],
        },
      ],
      lutListFull: [
        {
          name: "legacy-a",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          path: "/legacy-a.npy",
        },
        {
          name: "legacy-b",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          path: "/legacy-b.npy",
        },
      ],
    } as never);

    useConverterStore.getState().setLegacyLutNames(["legacy-a", "legacy-b"]);

    expect(useConverterStore.getState().lut_names).toEqual(["legacy-a", "legacy-b"]);
  });

  it("keeps legacy multi-select names when LUT list loads after details catalog", async () => {
    vi.mocked(lutApi.fetchLutInfo).mockResolvedValue({
      name: "legacy-a",
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      color_count: 4,
    } as never);
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValueOnce({
      groups: [
        {
          manufacturer: "Brand A",
          items: [
            {
              name: "Display A",
              path: "/legacy-a.npy",
              color_mode: ColorMode.FOUR_COLOR_RYBW,
              compatibility_key: "sig-a",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["a"],
            },
            {
              name: "Display B",
              path: "/legacy-b.npy",
              color_mode: ColorMode.FOUR_COLOR_RYBW,
              compatibility_key: "sig-b",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["b"],
            },
          ],
        },
      ],
    });
    vi.mocked(lutApi.fetchLutCatalog).mockResolvedValueOnce({
      legacy_groups: [
        {
          group_name: "Legacy",
          items: [
            { name: "legacy-a", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/legacy-a.npy" },
            { name: "legacy-b", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/legacy-b.npy" },
          ],
        },
      ],
      native_brand_groups: [],
    });

    useConverterStore.setState({
      source_version: "legacy",
      lut_name: "legacy-a",
      lut_names: ["legacy-a", "legacy-b"],
      lutListFull: [],
      legacyCatalogGroups: [],
    } as never);

    await useConverterStore.getState().fetchLegacyCatalog();
    expect(useConverterStore.getState().lut_names).toEqual(["legacy-a", "legacy-b"]);

    await useConverterStore.getState().fetchLutCatalog();

    expect(useConverterStore.getState().lut_names).toEqual(["legacy-a", "legacy-b"]);
  });

  it("submitPreview sends legacy_multi names across compatibility keys", async () => {
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-legacy",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/legacy-preview",
      preview_glb_url: null,
      palette: [],
      dimensions: { width: 200, height: 160 },
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "legacy.png", { type: "image/png" }),
      source_version: "legacy",
      lut_name: "legacy-a",
      lut_names: ["legacy-a", "legacy-b"],
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      legacyCatalogGroups: [
        {
          manufacturer: "Brand A",
          items: [
            {
              name: "Display A",
              path: "/legacy-a.npy",
              color_mode: ColorMode.FOUR_COLOR_RYBW,
              compatibility_key: "sig-a",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["a"],
            },
            {
              name: "Display B",
              path: "/legacy-b.npy",
              color_mode: ColorMode.FOUR_COLOR_RYBW,
              compatibility_key: "sig-b",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["b"],
            },
          ],
        },
      ],
      lutListFull: [
        {
          name: "legacy-a",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          path: "/legacy-a.npy",
        },
        {
          name: "legacy-b",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          path: "/legacy-b.npy",
        },
      ],
    } as never);

    await useConverterStore.getState().submitPreview();

    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(params).toMatchObject({
      source_kind: "legacy_multi",
      lut_name: "legacy-a",
      lut_names: ["legacy-a", "legacy-b"],
    });
  });

  it("submitPreview keeps legacy_multi names even before catalog compatibility resolves", async () => {
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-legacy",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/legacy-preview",
      preview_glb_url: null,
      palette: [],
      dimensions: { width: 200, height: 160 },
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "legacy.png", { type: "image/png" }),
      source_version: "legacy",
      lut_name: "legacy-a",
      lut_names: ["legacy-a", "legacy-b"],
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      legacyCatalogGroups: [
        {
          manufacturer: "Brand A",
          items: [
            {
              name: "Display A",
              path: "/legacy-a.npy",
              color_mode: ColorMode.FOUR_COLOR_RYBW,
              compatibility_key: "sig-a",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["a"],
            },
            {
              name: "Display B",
              path: "/legacy-b.npy",
              color_mode: ColorMode.FOUR_COLOR_RYBW,
              compatibility_key: "sig-b",
              source_kind: "legacy_lookup",
              manufacturer: "Brand A",
              material_type: "",
              manufacturer_source: "metadata",
              material_source: "metadata",
              search_tokens: ["b"],
            },
          ],
        },
      ],
      lutListFull: [],
    } as never);

    await useConverterStore.getState().submitPreview();

    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(params).toMatchObject({
      source_kind: "legacy_multi",
      lut_name: "legacy-a",
      lut_names: ["legacy-a", "legacy-b"],
    });
  });

  it("hydrates the legacy LUT list from the catalog response", async () => {
    vi.mocked(lutApi.fetchLutCatalog).mockResolvedValueOnce({
      legacy_groups: [
        {
          group_name: "Preset",
          items: [
            { name: "legacy-a", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/a.npy" },
          ],
        },
        {
          group_name: "ReferenceDB",
          items: [
            { name: "legacy-b", color_mode: ColorMode.BW, path: "/b.npy" },
          ],
        },
      ],
      native_brand_groups: [],
    });

    await useConverterStore.getState().fetchLutCatalog();

    expect(useConverterStore.getState().lutList).toEqual(["legacy-a", "legacy-b"]);
    expect(useConverterStore.getState().lutListFull).toHaveLength(2);
  });

  it("normalizes catalog load HTTP status errors before showing them", async () => {
    vi.mocked(lutApi.fetchLutCatalog).mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    await useConverterStore.getState().fetchLutCatalog();

    const error = useConverterStore.getState().error;
    expect(error).toBeTruthy();
    expect(error).not.toMatch(/Request failed with status code 500/i);
    expect(error).not.toMatch(/status code\s+500/i);
  });

  it("fetches the legacy details catalog into converter state", async () => {
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValueOnce(
      makeLegacyDetailsCatalog(),
    );

    await useConverterStore.getState().fetchLegacyCatalog();

    expect(lutApi.fetchLutDetailsCatalog).toHaveBeenCalledOnce();
    expect(useConverterStore.getState().legacyCatalogGroups).toHaveLength(2);
    expect(useConverterStore.getState().legacyCatalogLoading).toBe(false);
  });

  it("normalizes legacy details catalog HTTP status errors before showing them", async () => {
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockRejectedValueOnce(
      new Error("Request failed with status code 402"),
    );

    await useConverterStore.getState().fetchLegacyCatalog();

    const error = useConverterStore.getState().error;
    expect(error).toBeTruthy();
    expect(error).not.toMatch(/Request failed with status code 402/i);
    expect(error).not.toMatch(/status code\s+402/i);
  });

  it("hydrates selectedLegacyManufacturer from a remembered lut_name", async () => {
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValueOnce(
      makeLegacyDetailsCatalog(),
    );
    useConverterStore.setState({
      lut_name: "legacy-b",
      lutListFull: [
        {
          name: "legacy-b",
          color_mode: ColorMode.EIGHT_COLOR,
          path: "/legacy-b.npy",
        },
      ],
    });

    await useConverterStore.getState().fetchLegacyCatalog();

    expect(useConverterStore.getState().selectedLegacyManufacturer)
      .toBe("Brand B");
  });

  it("keeps applied LUTs and preview intact when browsing another manufacturer", () => {
    localStorage.setItem("lumina_lastLut", "legacy-a");
    useConverterStore.setState({
      legacyCatalogGroups: makeLegacyDetailsCatalog().groups,
      selectedLegacyManufacturer: "Brand A",
      lut_name: "legacy-a",
      lut_names: ["legacy-a", "legacy-b"],
      sessionId: "session-applied",
      previewUrl: "/api/files/applied-preview",
      color_layers: 5,
      layer_height_mm: 0.08,
      lutListFull: [
        {
          name: "legacy-a",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          path: "/legacy-a.npy",
        },
      ],
    } as never);

    useConverterStore.getState().setLegacyManufacturer("Brand B");

    expect(useConverterStore.getState().selectedLegacyManufacturer)
      .toBe("Brand B");
    expect(useConverterStore.getState()).toMatchObject({
      lut_name: "legacy-a",
      lut_names: ["legacy-a", "legacy-b"],
      sessionId: "session-applied",
      previewUrl: "/api/files/applied-preview",
      color_layers: 5,
      layer_height_mm: 0.08,
    });
    expect(localStorage.getItem("lumina_lastLut")).toBe("legacy-a");
  });

  it("filters the native catalog down to the BambuLab PLA brand", async () => {
    vi.mocked(lutApi.fetchLutCatalog).mockResolvedValueOnce({
      legacy_groups: [],
      native_brand_groups: [
        {
          brand_key: "bambulab_pla",
          material_type: "PLA",
          vendor: "Bambu Lab",
          display_name: "Bambu PLA",
          db_options: [
            { ...makeDbOption("B1"), color_mode: "8-Color" },
            makeDbOption("B2"),
          ],
          default_db_names: ["B1"],
          package_name: "bambu-pla-package",
          model_name: "bambu-pla-model",
          supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
        },
        makePredictiveBrand(),
        makeNonPredictiveBrand(),
      ],
    });

    await useConverterStore.getState().fetchLutCatalog();

    expect(useConverterStore.getState().nativeBrandGroups).toHaveLength(1);
    expect(useConverterStore.getState().nativeBrandGroups[0].brand_key).toBe("bambulab_pla");
    expect(useConverterStore.getState().nativeBrandGroups[0].display_name).toBe("Bambu PLA");
    expect(useConverterStore.getState().nativeBrandGroups[0].db_options[0].color_mode).toBe(
      ColorMode.EIGHT_COLOR,
    );
  });

  it("submitPreview sends native bundle fields instead of lut_name", async () => {
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-native",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/native-preview",
      preview_glb_url: null,
      palette: [],
      dimensions: { width: 200, height: 160 },
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "native.png", { type: "image/png" }),
      source_version: "native",
      lut_name: "",
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      color_layers: 5,
      layer_height_mm: 0.08,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      model_only: false,
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      largeFormatEnabled: true,
      nativeBrandGroups: [
        makePredictiveBrand(),
      ],
    } as never);

    useConverterStore.getState().setModelEnable(true);
    useConverterStore.getState().setModelThreshold(6.5);
    useConverterStore.getState().setModelMargin(0.9);
    useSettingsStore.setState({
      enableCompletionNotifications: true,
      language: "en",
    });

    await useConverterStore.getState().submitPreview();

    expect(mocks.convertPreview).toHaveBeenCalledOnce();
    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(params).toMatchObject({
      source_kind: "native_bundle",
      material_type: "PLA",
      vendor: "Vendor A",
      db_names: ["A2"],
      color_layers: 5,
      layer_height_mm: 0.08,
      model_enable: true,
      model_only: false,
      model_threshold: 6.5,
      model_margin: 0.9,
      target_width_mm: 90,
      large_format_enabled: true,
    });
    expect(params).not.toHaveProperty("lut_name");
    expect(useConverterStore.getState().sessionId).toBe("session-native");
    expect(mocks.showBrowserCompletionNotification).toHaveBeenCalledWith(
      "preview",
      "en",
    );
  });

  it("replays global color replacements when material preview is refreshed", async () => {
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-material-refresh",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/material-preview",
      preview_glb_url: null,
      palette: [
        {
          quantized_hex: "#111111",
          matched_hex: "#111111",
          pixel_count: 12,
          percentage: 100,
        },
      ],
      dimensions: { width: 200, height: 160 },
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "material.png", { type: "image/png" }),
      source_version: "material",
      selectedMaterialDirNames: [
        "拓竹/Bambu PLA Basic 黑色",
        "拓竹/Bambu PLA Basic 玉石白",
      ],
      materialLayerCount: 5,
      materialLayerHeightMm: 0.08,
      materialBackingMaterialDirName: "拓竹/Bambu PLA Basic 黑色",
      target_width_mm: 60,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      palette: [
        {
          quantized_hex: "111111",
          matched_hex: "111111",
          pixel_count: 12,
          percentage: 100,
        },
      ],
      colorRemapMap: { "111111": "222222" },
      remapHistory: [{ "111111": "111111" }],
    } as never);

    await useConverterStore.getState().submitPreview();

    expect(mocks.convertPreview).toHaveBeenCalledOnce();
    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(params.replacement_regions).toEqual([
      {
        quantized_hex: "#111111",
        matched_hex: "#111111",
        replacement_hex: "#222222",
      },
    ]);
    expect(useConverterStore.getState().colorRemapMap).toEqual({
      "111111": "222222",
    });
    expect(useConverterStore.getState().remapHistory).toEqual([
      { "111111": "111111" },
    ]);
  });

  it("keeps an ordinary raster on lightweight preview state until async GLB arrives", async () => {
    vi.useFakeTimers();
    try {
      mocks.convertPreview.mockResolvedValueOnce({
        session_id: "session-preview-async",
        status: "ok",
        message: "Preview generated",
        preview_url: "/api/files/native-preview",
        preview_glb_url: null,
        palette: [],
        dimensions: { width: 200, height: 160 },
      });
      mocks.getGlbStatus.mockResolvedValueOnce({
        session_id: "session-preview-async",
        status: "ready",
        glb_url: "/api/files/preview-ready.glb",
        job_token: "token-preview",
        error: null,
        color_contours: {
          ff0000: [[[0, 0], [1, 0], [1, 1]]],
        },
      });
      mocks.convertGenerate.mockResolvedValueOnce({
        status: "ok",
        message: "Model generated",
        download_url: "/api/files/native-model.3mf",
        preview_3d_url: "/api/files/generated-material-model.glb",
      });

      useConverterStore.setState({
        imageFile: new File(["png"], "native.png", { type: "image/png" }),
        source_version: "native",
        lut_name: "",
        target_width_mm: 90,
        color_mode: ColorMode.FOUR_COLOR_RYBW,
        modeling_mode: ModelingMode.HIGH_FIDELITY,
        color_layers: 5,
        layer_height_mm: 0.08,
        quantize_colors: 48,
        enable_cleanup: true,
        hue_enable: false,
        selectedNativeBrandKey: "brand-a",
        selectedNativeDbNames: ["A2"],
        nativeBrandGroups: [makePredictiveBrand()],
      } as never);

      await useConverterStore.getState().submitPreview();
      await useConverterStore.getState().submitGenerate();

      expect(useConverterStore.getState().modelUrl).toBeNull();
      expect(useConverterStore.getState().previewGlbUrl).toBeNull();

      await flushGlbPoll();
      await flushGlbPoll(0);

      expect(mocks.getGlbStatus).toHaveBeenCalledWith("session-preview-async");
      expect(useConverterStore.getState().previewGlbUrl).toBe(
        "/api/files/preview-ready.glb",
      );
      expect(useConverterStore.getState().modelUrl).toBeNull();
      expect(useConverterStore.getState().colorContours).toEqual({
        ff0000: [[[0, 0], [1, 0], [1, 1]]],
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("waits for async segmented GLB instead of showing generated Vector GLB", async () => {
    vi.useFakeTimers();
    try {
      mocks.convertPreview.mockResolvedValueOnce({
        session_id: "session-vector-async",
        status: "ok",
        message: "Preview generated",
        preview_url: "/api/files/vector-preview",
        preview_glb_url: null,
        palette: [],
        dimensions: { width: 1110, height: 2407 },
      });
      mocks.getGlbStatus.mockResolvedValueOnce({
        session_id: "session-vector-async",
        status: "ready",
        glb_url: "/api/files/segmented-vector-preview.glb",
        job_token: "token-vector-preview",
        error: null,
        color_contours: null,
      });
      mocks.convertGenerate.mockResolvedValueOnce({
        status: "ok",
        message: "Model generated",
        download_url: "/api/files/vector-model.3mf",
        preview_3d_url: "/api/files/print-exact-vector.glb",
      });

      useConverterStore.setState({
        imageFile: new File(["<svg/>"], "native-vector.svg", {
          type: "image/svg+xml",
        }),
        source_version: "native",
        lut_name: "",
        target_width_mm: 111,
        color_mode: ColorMode.FOUR_COLOR_RYBW,
        modeling_mode: ModelingMode.VECTOR,
        color_layers: 5,
        layer_height_mm: 0.08,
        quantize_colors: 48,
        enable_cleanup: true,
        hue_enable: false,
        selectedNativeBrandKey: "brand-a",
        selectedNativeDbNames: ["A2"],
        nativeBrandGroups: [makePredictiveBrand()],
      } as never);

      await useConverterStore.getState().submitPreview();
      await useConverterStore.getState().submitGenerate();

      expect(useConverterStore.getState().modelUrl).toBeNull();
      expect(useConverterStore.getState().previewGlbUrl).toBeNull();

      await flushGlbPoll();
      await flushGlbPoll(0);

      expect(mocks.getGlbStatus).toHaveBeenCalledWith("session-vector-async");
      expect(useConverterStore.getState().previewGlbUrl).toBe(
        "/api/files/segmented-vector-preview.glb",
      );
      expect(useConverterStore.getState().modelUrl).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  const generatedVectorGeometryCases: Array<
    [string, Record<string, unknown>]
  > = [
    [
      "color relief",
      {
        enable_relief: true,
        autoHeightMode: "darker-higher",
        color_height_map: { "111111": 0.5 },
      },
    ],
    ["coating", { enable_coating: true }],
    ["keychain loop", { add_loop: true }],
    [
      "fridge magnet",
      {
        enable_fridge_magnet: true,
        fridge_magnets: [
          {
            id: "magnet-round",
            shape: "round",
            preset_key: "round-18",
            diameter_mm: 18,
            width_mm: null,
            height_mm: null,
            thickness_mm: 2,
            center_x_mm: 20,
            center_y_mm: 25,
          },
        ],
      },
    ],
    ["outline", { enable_outline: true }],
    ["cloisonne", { enable_cloisonne: true }],
    [
      "model surface overlay",
      {
        modelSurfaceEnabled: true,
        modelSurfaceModelFileId: "surface-model-id",
        modelSurfaceSelection: { face_indices: [1] },
        modelSurfaceFootprint: { width_mm: 111, height_mm: 241 },
      },
    ],
  ];

  const staleGeneratedGeometryParameterCases: Array<
    [
      string,
      Record<string, unknown>,
      Record<string, unknown>,
    ]
  > = [
    [
      "relief height map",
      {
        enable_relief: true,
        autoHeightMode: "darker-higher",
        color_height_map: { "111111": 0.5 },
      },
      { color_height_map: { "111111": 1.5 } },
    ],
    [
      "outline width",
      { enable_outline: true, outline_width: 0.8 },
      { outline_width: 1.6 },
    ],
    [
      "keychain placement",
      { add_loop: true, loop_offset_x: 0 },
      { loop_offset_x: 4 },
    ],
    [
      "cloisonne dimensions",
      { enable_cloisonne: true, wire_height_mm: 0.4 },
      { wire_height_mm: 1.2 },
    ],
    [
      "coating height",
      { enable_coating: true, coating_height_mm: 0.2 },
      { coating_height_mm: 0.8 },
    ],
    [
      "fridge magnet layout",
      {
        enable_fridge_magnet: true,
        fridge_magnets: [
          {
            id: "magnet-round",
            shape: "round",
            preset_key: "round-18",
            diameter_mm: 18,
            width_mm: null,
            height_mm: null,
            thickness_mm: 2,
            center_x_mm: 20,
            center_y_mm: 25,
          },
        ],
      },
      {
        fridge_magnets: [
          {
            id: "magnet-round",
            shape: "round",
            preset_key: "round-18",
            diameter_mm: 18,
            width_mm: null,
            height_mm: null,
            thickness_mm: 2,
            center_x_mm: 24,
            center_y_mm: 25,
          },
        ],
      },
    ],
    [
      "model surface placement",
      {
        modelSurfaceEnabled: true,
        modelSurfaceModelFileId: "surface-model-id",
        modelSurfaceSelection: { face_indices: [1] },
        modelSurfaceFootprint: { width_mm: 111, height_mm: 241 },
      },
      {
        modelSurfacePlacement: {
          mode: "inset",
          offset_x_mm: 2,
          offset_y_mm: 0,
          scale: 0.9,
          rotation_deg: 0,
          inset_mm: 1,
        },
      },
    ],
  ];

  it.each(generatedVectorGeometryCases)(
    "keeps the lightweight preview authoritative for %s",
    async (_label, overrides) => {
      mocks.convertGenerate.mockResolvedValueOnce({
        status: "ok",
        message: "Model generated",
        download_url: "/api/files/surface-model.3mf",
        preview_3d_url: "/api/files/generated-surface.glb",
      });
      seedLegacyGenerateState("session-generated-surface", {
        imageFile: new File(["<svg/>"], "native-vector.svg", {
          type: "image/svg+xml",
        }),
        modeling_mode: ModelingMode.VECTOR,
        previewGlbUrl: "/api/files/flat-preview.glb",
        ...overrides,
      } as never);

      await useConverterStore.getState().submitGenerate();

      expect(useConverterStore.getState().modelUrl).toBeNull();
      expect(useConverterStore.getState().previewGlbUrl).toBe(
        "/api/files/flat-preview.glb",
      );
    },
  );

  it.each(generatedVectorGeometryCases)(
    "keeps the lightweight %s preview when Generate returns no GLB",
    async (_label, overrides) => {
      mocks.convertGenerate.mockResolvedValueOnce({
        status: "ok",
        message: "Model generated without optional GLB",
        download_url: "/api/files/surface-model.3mf",
        preview_3d_url: null,
      });
      seedLegacyGenerateState("session-generated-surface", {
        imageFile: new File(["<svg/>"], "native-vector.svg", {
          type: "image/svg+xml",
        }),
        modeling_mode: ModelingMode.VECTOR,
        previewGlbUrl: "/api/files/flat-preview.glb",
        ...overrides,
      } as never);

      await useConverterStore.getState().submitGenerate();

      expect(useConverterStore.getState().modelUrl).toBeNull();
      expect(useConverterStore.getState().previewGlbUrl).toBe(
        "/api/files/flat-preview.glb",
      );
    },
  );

  it.each(staleGeneratedGeometryParameterCases)(
    "does not display a generated %s GLB after its parameters change",
    async (_label, initialOverrides, changedOverrides) => {
      const generation = deferred<{
        status: string;
        message: string;
        download_url: string;
        preview_3d_url: string;
      }>();
      mocks.convertGenerate.mockReturnValueOnce(generation.promise);
      seedLegacyGenerateState("session-stale-generated-geometry", {
        imageFile: new File(["<svg/>"], "native-vector.svg", {
          type: "image/svg+xml",
        }),
        modeling_mode: ModelingMode.VECTOR,
        previewGlbUrl: "/api/files/current-quick-preview.glb",
        ...initialOverrides,
      } as never);

      const submitGenerate = useConverterStore.getState().submitGenerate();
      await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());

      useConverterStore.setState(changedOverrides as never);
      generation.resolve({
        status: "ok",
        message: "Model generated with old parameters",
        download_url: "/api/files/stale-model.3mf",
        preview_3d_url: "/api/files/stale-generated.glb",
      });
      await submitGenerate;

      expect(useConverterStore.getState().modelUrl).toBeNull();
      expect(useConverterStore.getState().previewGlbUrl).toBe(
        "/api/files/current-quick-preview.glb",
      );
    },
  );

  const generatedGeometryEnabledDuringGenerationCases: Array<
    [string, Record<string, unknown>, () => void, string | null]
  > = [
    [
      "raster relief",
      { modeling_mode: ModelingMode.HIGH_FIDELITY },
      () => useConverterStore.setState({
        enable_relief: true,
        autoHeightMode: "darker-higher",
        color_height_map: { "111111": 0.5 },
      }),
      "/api/files/old-flat-model.3mf",
    ],
    [
      "raster coating",
      { modeling_mode: ModelingMode.HIGH_FIDELITY },
      // Coating changes the export material slots, so the old download is stale too.
      () => useConverterStore.getState().setEnableCoating(true),
      null,
    ],
    [
      "Vector model surface",
      {
        imageFile: new File(["<svg/>"], "native-vector.svg", {
          type: "image/svg+xml",
        }),
        modeling_mode: ModelingMode.VECTOR,
      },
      () => useConverterStore.setState({
        modelSurfaceEnabled: true,
        modelSurfaceModelFileId: "surface-model-id",
        modelSurfaceSelection: { face_indices: [1] },
        modelSurfaceFootprint: { width_mm: 111, height_mm: 241 },
      }),
      "/api/files/old-flat-model.3mf",
    ],
  ];

  it.each(generatedGeometryEnabledDuringGenerationCases)(
    "does not display an old flat GLB after enabling %s during generation",
    async (_label, initialOverrides, enable, expectedDownload) => {
      const generation = deferred<{
        status: string;
        message: string;
        download_url: string;
        preview_3d_url: string;
      }>();
      mocks.convertGenerate.mockReturnValueOnce(generation.promise);
      seedLegacyGenerateState("session-enable-generated-geometry", {
        previewGlbUrl: null,
        modelUrl: null,
        ...initialOverrides,
      } as never);

      const submitGenerate = useConverterStore.getState().submitGenerate();
      await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());

      enable();
      generation.resolve({
        status: "ok",
        message: "Old flat model generated",
        download_url: "/api/files/old-flat-model.3mf",
        preview_3d_url: "/api/files/old-flat-generated.glb",
      });
      await submitGenerate;

      expect(useConverterStore.getState().modelUrl).toBeNull();
      expect(useConverterStore.getState().previewGlbUrl).toBeNull();
      expect(useConverterStore.getState().downloadUrl).toBe(expectedDownload);
    },
  );

  it("keeps generated GLBs out of state while switching to heightmap", async () => {
    vi.useFakeTimers();
    try {
      mocks.getGlbStatus.mockResolvedValueOnce({
        session_id: "session-mode-switch",
        status: "ready",
        glb_url: "/api/files/flat-preview.glb",
        job_token: "token-mode-switch",
        error: null,
        color_contours: null,
      });
      mocks.convertGenerate.mockResolvedValueOnce({
        status: "ok",
        message: "Model generated",
        download_url: "/api/files/model.3mf",
        preview_3d_url: "/api/files/generated-normal.glb",
      });
      seedLegacyGenerateState("session-mode-switch");

      useConverterStore.getState()._pollAsyncGlb();
      await useConverterStore.getState().submitGenerate();

      expect(useConverterStore.getState().modelUrl).toBeNull();

      useConverterStore.getState().setEnableRelief(true);
      useConverterStore.getState().setAutoHeightMode("use-heightmap");
      await flushGlbPoll();
      await flushGlbPoll(0);

      expect(useConverterStore.getState().previewGlbUrl).toBe(
        "/api/files/flat-preview.glb",
      );
      expect(useConverterStore.getState().modelUrl).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps polling the lightweight heightmap approximation after Generate", async () => {
    vi.useFakeTimers();
    try {
      mocks.getGlbStatus.mockResolvedValueOnce({
        session_id: "session-heightmap-async",
        status: "ready",
        glb_url: "/api/files/flat-preview.glb",
        job_token: "token-heightmap",
        error: null,
        color_contours: null,
      });
      mocks.convertGenerate.mockResolvedValueOnce({
        status: "ok",
        message: "Model generated",
        download_url: "/api/files/model.3mf",
        preview_3d_url: "/api/files/generated-heightmap.glb",
      });
      seedLegacyGenerateState("session-heightmap-async", {
        enable_relief: true,
        autoHeightMode: "use-heightmap",
        color_height_map: { "111111": 0.5 },
        heightmapUploadSessionId: "session-heightmap-async",
      });

      useConverterStore.getState()._pollAsyncGlb();
      await useConverterStore.getState().submitGenerate();

      expect(mocks.convertGenerate.mock.calls[0]?.[1]).toMatchObject({
        height_mode: "heightmap",
      });
      expect(useConverterStore.getState().modelUrl).toBeNull();

      await flushGlbPoll();
      await flushGlbPoll(0);

      expect(mocks.getGlbStatus).toHaveBeenCalledWith(
        "session-heightmap-async",
      );
      expect(useConverterStore.getState().previewGlbUrl).toBe(
        "/api/files/flat-preview.glb",
      );
      expect(useConverterStore.getState().modelUrl).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps a newer preview authoritative when it resolves during heightmap generation", async () => {
    vi.useFakeTimers();
    try {
      const generation = deferred<{
        status: string;
        message: string;
        download_url: string;
        preview_3d_url: string;
      }>();
      mocks.convertGenerate.mockReturnValueOnce(generation.promise);
      mocks.getGlbStatus.mockResolvedValueOnce({
        session_id: "session-heightmap-newer-poll",
        status: "ready",
        glb_url: "/api/files/newer-preview.glb",
        job_token: "token-newer-preview",
        error: null,
        color_contours: null,
      });
      seedLegacyGenerateState("session-heightmap-newer-poll", {
        enable_relief: true,
        autoHeightMode: "use-heightmap",
        color_height_map: { "111111": 0.5 },
        heightmapUploadSessionId: "session-heightmap-newer-poll",
      });

      const submitGenerate = useConverterStore.getState().submitGenerate();
      await vi.waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());

      useConverterStore.getState()._pollAsyncGlb();
      await flushGlbPoll();
      await flushGlbPoll(0);

      expect(mocks.getGlbStatus).toHaveBeenCalledWith(
        "session-heightmap-newer-poll",
      );
      expect(useConverterStore.getState().previewGlbUrl).toBe(
        "/api/files/newer-preview.glb",
      );

      generation.resolve({
        status: "ok",
        message: "Model generated",
        download_url: "/api/files/model.3mf",
        preview_3d_url: "/api/files/generated-heightmap.glb",
      });
      await submitGenerate;

      expect(useConverterStore.getState().previewGlbUrl).toBe(
        "/api/files/newer-preview.glb",
      );
      expect(useConverterStore.getState().modelUrl).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("submitPreview omits model fields for non-predictive native brands", async () => {
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-native",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/native-preview",
      preview_glb_url: null,
      palette: [],
      dimensions: { width: 200, height: 160 },
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "native.png", { type: "image/png" }),
      source_version: "native",
      lut_name: "",
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      color_layers: 5,
      layer_height_mm: 0.08,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      selectedNativeBrandKey: "brand-b",
      selectedNativeDbNames: ["DB-B1"],
      nativeBrandGroups: [makeNonPredictiveBrand()],
      model_enable: true,
      model_only: true,
    } as never);
    useSettingsStore.setState({ enableSmoothVectorPreview: false });

    await useConverterStore.getState().submitPreview();

    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(params).toMatchObject({
      source_kind: "native_bundle",
      material_type: "PLA",
      vendor: "Vendor B",
      db_names: ["DB-B1"],
    });
    expect(params).not.toHaveProperty("model_enable");
    expect(params).not.toHaveProperty("model_only");
    expect(params).not.toHaveProperty("model_threshold");
    expect(params).not.toHaveProperty("model_margin");
    expect(params.enable_smooth_vector_preview).toBe(false);
  });

  it("submitGenerate sends native bundle fields in the JSON body", async () => {
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "Model generated",
      download_url: "http://localhost:8000/api/files/native-model",
      preview_3d_url: "http://localhost:8000/api/files/native-model.glb",
    });

    useConverterStore.setState({
      sessionId: "session-native",
      source_version: "native",
      lut_name: "",
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      separate_backing: false,
      add_loop: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      enable_relief: false,
      heightmap_max_height: 5.0,
      enable_outline: false,
      outline_width: 2.0,
      enable_cloisonne: false,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: false,
      coating_height_mm: 0.08,
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      nativeBrandGroups: [
        makePredictiveBrand(),
      ],
    } as never);

    useConverterStore.getState().setModelEnable(true);
    useConverterStore.getState().setModelOnly(false);
    useConverterStore.getState().setModelThreshold(6.5);
    useConverterStore.getState().setModelMargin(0.9);

    const result = await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    const [, params] = mocks.convertGenerate.mock.calls[0];
    expect(params).toMatchObject({
      source_kind: "native_bundle",
      material_type: "PLA",
      vendor: "Vendor A",
      db_names: ["A2"],
      color_layers: 5,
      layer_height_mm: 0.08,
      model_enable: true,
      model_only: false,
      target_width_mm: 90,
    });
    expect(params).not.toHaveProperty("lut_name");
    expect(result).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBe("/api/files/native-model");
    expect(mocks.showBrowserCompletionNotification).not.toHaveBeenCalled();
  });

  it("submitGenerate uses the puzzle endpoint when puzzle mode is enabled", async () => {
    mocks.convertGeneratePuzzle.mockResolvedValueOnce({
      status: "ok",
      message: "Generated puzzle",
      download_url: "http://localhost:8000/api/files/puzzle-model",
      threemf_disk_path: "E:/tmp/puzzle.3mf",
      piece_count: 6,
      grid_cols: 3,
      grid_rows: 2,
      warnings: ["wipe_tower_manual_adjustment_required"],
    });

    useConverterStore.setState({
      sessionId: "session-puzzle",
      source_version: "legacy",
      lut_name: "legacy-lut",
      target_width_mm: 90,
      target_height_mm: 60,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      separate_backing: false,
      add_loop: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      enable_relief: false,
      heightmap_max_height: 5.0,
      enable_outline: false,
      outline_width: 2.0,
      enable_cloisonne: false,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: false,
      coating_height_mm: 0.08,
      puzzleEnabled: true,
      puzzleStyle: "regular",
      puzzleSizingMode: "grid",
      pieceWidthMm: 20,
      pieceHeightMm: 20,
      puzzleRows: 2,
      puzzleCols: 3,
      targetPieceCount: 6,
      connectorStyle: "classic",
      labelsEnabled: true,
      engraveBackLabels: false,
      irregularityStrength: 0.35,
      minNeckWidthMm: 1.2,
    } as never);
    useSettingsStore.setState({
      deviceProfileId: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
      enableCompletionNotifications: true,
      language: "zh",
    } as never);

    const result = await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGeneratePuzzle).toHaveBeenCalledOnce();
    expect(mocks.convertGenerate).not.toHaveBeenCalled();
    const [, params] = mocks.convertGeneratePuzzle.mock.calls[0];
    expect(params).toMatchObject({
      target_height_mm: 60,
      puzzle_style: "regular",
      sizing_mode: "grid",
      rows: 2,
      cols: 3,
      target_piece_count: 6,
    });
    expect(params.params).toMatchObject({
      lut_name: "legacy-lut",
      target_width_mm: 90,
      device_profile_id: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
    });
    expect(result).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBe("/api/files/puzzle-model");
    expect(useConverterStore.getState().puzzleWarnings).toEqual([
      "wipe_tower_manual_adjustment_required",
    ]);
    expect(useConverterStore.getState().generateWarnings).toEqual([
      "wipe_tower_manual_adjustment_required",
    ]);
    expect(mocks.showBrowserCompletionNotification).toHaveBeenCalledWith(
      "generation",
      "zh",
    );
  });

  it("submitGenerate forwards fridge magnet fields to the backend payload", async () => {
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/fridge-model",
      preview_3d_url: "/api/files/fridge-model.glb",
    });

    useConverterStore.setState({
      sessionId: "session-fridge",
      source_version: "legacy",
      lut_name: "legacy-lut",
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      spacer_thick: 1.2,
      structure_mode: StructureMode.SINGLE_SIDED,
      separate_backing: false,
      add_loop: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      enable_relief: false,
      heightmap_max_height: 5.0,
      enable_outline: false,
      outline_width: 2.0,
      enable_cloisonne: false,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: false,
      coating_height_mm: 0.08,
      enable_fridge_magnet: true,
      fridge_magnets: [
        {
          id: "magnet-1",
          shape: "round",
          preset_key: "round-d12x3",
          diameter_mm: 12,
          width_mm: null,
          height_mm: null,
          thickness_mm: 3,
          center_x_mm: 12,
          center_y_mm: 18,
        },
      ],
    } as never);

    await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGenerate).toHaveBeenCalledOnce();
    const [, params] = mocks.convertGenerate.mock.calls[0];
    expect(params).toMatchObject({
      enable_fridge_magnet: true,
      fridge_magnets: [
        {
          id: "magnet-1",
          shape: "round",
          diameter_mm: 12,
          thickness_mm: 3,
        },
      ],
    });
  });

  it("changing native source selection invalidates stale preview session state", () => {
    useConverterStore.setState({
      source_version: "native",
      sessionId: "session-stale",
      previewImageUrl: "/api/files/preview",
      originalPreviewUrl: "/api/files/preview",
      previewBaseImageUrl: "/api/files/base",
      previewGlbUrl: "/api/files/model.glb",
      threemfDiskPath: "E:/tmp/model.3mf",
      downloadUrl: "/api/files/model.3mf",
      palette: [{ quantized_hex: "ffffff", matched_hex: "ffffff", pixel_count: 1, percentage: 100 }],
      recipe_overrides: [{ region_id: "region-1", recipe: [1, 2, 3, 4, 5], layer_order: "Top2Bottom" }],
      nativeBrandGroups: [makePredictiveBrand(), makeNonPredictiveBrand()],
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      imageFile: new File(["png"], "native.png", { type: "image/png" }),
      hasManualPreview: true,
    } as never);

    useConverterStore.getState().setNativeBrandKey("brand-b");

    const state = useConverterStore.getState();
    expect(state.sessionId).toBeNull();
    expect(state.previewImageUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.recipe_overrides).toEqual([]);
    expect(state.hasManualPreview).toBe(false);
  });

  it("applyCustomRecipeOverride works for native sources without lut_name", async () => {
    mocks.applyRecipeOverride.mockResolvedValueOnce({
      status: "ok",
      message: "Recipe override applied",
      preview_url: "/api/files/recipe-preview",
      preview_glb_url: "/api/files/recipe-preview.glb",
      rgb: [255, 255, 255],
      lab: [100, 0, 0],
      source: "stage_model",
      runtime_mode_key: "0.08x5",
      override_count: 1,
    });

    useConverterStore.setState({
      sessionId: "session-native",
      source_version: "native",
      lut_name: "",
      selectedNativeBrandKey: "brand-a",
      selectedNativeDbNames: ["A2"],
      nativeBrandGroups: [makePredictiveBrand()],
      color_layers: 5,
      layer_height_mm: 0.08,
      selectedRegions: [{ regionId: "region-1", colorHex: "ffffff", pixelCount: 1, previewUrl: "/api/files/region" }],
    } as never);

    await useConverterStore.getState().applyCustomRecipeOverride(["region-1"], [1, 1, 1, 1, 1]);

    expect(mocks.applyRecipeOverride).toHaveBeenCalledOnce();
    expect(useConverterStore.getState().error).toBeNull();
  });

  it("omits model fields for legacy preview and generate payloads", async () => {
    mocks.convertPreview.mockResolvedValueOnce({
      session_id: "session-legacy",
      status: "ok",
      message: "Preview generated",
      preview_url: "/api/files/legacy-preview",
      preview_glb_url: null,
      palette: [],
      dimensions: { width: 200, height: 160 },
    });
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "Model generated",
      download_url: "/api/files/legacy-model",
      preview_3d_url: "/api/files/legacy-model.glb",
    });

    useConverterStore.setState({
      imageFile: new File(["png"], "legacy.png", { type: "image/png" }),
      source_version: "legacy",
      lut_name: "legacy-lut",
      target_width_mm: 90,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      color_layers: null,
      layer_height_mm: null,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_enable: false,
      model_enable: true,
      model_only: true,
      spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      separate_backing: false,
      add_loop: false,
      loop_width: 4,
      loop_length: 8,
      loop_hole: 2.5,
      enable_relief: false,
      heightmap_max_height: 5.0,
      enable_outline: false,
      outline_width: 2.0,
      enable_cloisonne: false,
      wire_width_mm: 0.4,
      wire_height_mm: 0.4,
      enable_coating: false,
      coating_height_mm: 0.08,
    } as never);

    await useConverterStore.getState().submitPreview();
    const previewParams = mocks.convertPreview.mock.calls[0][1];
    expect(previewParams).not.toHaveProperty("model_enable");
    expect(previewParams).not.toHaveProperty("model_only");
    expect(previewParams).not.toHaveProperty("model_threshold");
    expect(previewParams).not.toHaveProperty("model_margin");

    await useConverterStore.getState().submitGenerate();
    const generateParams = mocks.convertGenerate.mock.calls[0][1];
    expect(generateParams).not.toHaveProperty("model_enable");
    expect(generateParams).not.toHaveProperty("model_only");
    expect(generateParams).not.toHaveProperty("model_threshold");
    expect(generateParams).not.toHaveProperty("model_margin");
  });
});
