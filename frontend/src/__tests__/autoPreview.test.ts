import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  fetchMaterialSolverCacheStatus,
  type MaterialSolverCacheKey,
} from "../api/materialCache";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { useAutoPreview } from "../hooks/useAutoPreview";
import {
  ModelingMode,
  type MaterialSolverCacheStatusResponse,
} from "../api/types";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

vi.mock("../api/materialCache", () => ({
  fetchMaterialSolverCacheStatus: vi.fn(),
}));

function fakeFile(name = "test.png"): File {
  return new File(["pixels"], name, { type: "image/png" });
}

function materialCacheStatus(
  key: MaterialSolverCacheKey,
  cached: boolean,
): MaterialSolverCacheStatusResponse {
  return {
    status: "ok",
    message: cached ? "Cache found" : "No cache found",
    cached,
    palette_hash: "material-palette",
    layer_count: key.layerCount,
    layer_height_mm: key.layerHeightMm,
    substrate: key.substrate,
    entry: cached
      ? {
          palette_hash: "material-palette",
          material_directory_names: key.materialDirectoryNames,
          layer_count: key.layerCount,
          layer_height_mm: key.layerHeightMm,
          substrate: key.substrate,
          grid_resolution: 64,
          total_combinations: 64,
          valid_cell_count: 64,
          total_cell_count: 64,
          mean_delta_e: 0,
          max_delta_e: 0,
          build_time_seconds: 1,
          built_at: "2026-07-28T15:00:00Z",
          cache_file_size_bytes: 1024,
        }
      : null,
  };
}

describe("useAutoPreview", () => {
  const mockSubmitPreview = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

  it("adopts a restored project preview without regenerating away its local edits", () => {
    useConverterStore.setState({ imageFile: fakeFile("before.png"), source_version: "legacy", lut_name: "before", hasManualPreview: true, sessionId: "before" });
    renderHook(() => useAutoPreview());
    act(() => {
      useConverterStore.getState().commitProjectRestore({ ...useConverterStore.getState(), imageFile: fakeFile("restored.png"), lut_name: "restored", sessionId: "restored", previewBaseImageUrl: "/api/files/edited", regionReplacementCount: 3, hasManualPreview: true, previewAutoRefreshPending: false });
    });
    act(() => vi.advanceTimersByTime(1000));
    expect(mockSubmitPreview).not.toHaveBeenCalled();
    expect(useConverterStore.getState()).toMatchObject({ sessionId: "restored", previewBaseImageUrl: "/api/files/edited", regionReplacementCount: 3 });
  });

  function establishMaterialPreviewBaseline() {
    useConverterStore.setState({
      imageFile: fakeFile("material-preview.png"),
      source_version: "material",
      lut_name: "",
      lut_names: [],
      selectedMaterialDirNames: ["profile/yellow", "profile/black"],
      materialLayerCount: 10,
      materialLayerHeightMm: 0.04,
      materialBackingMaterialDirName: "profile/black",
      target_width_mm: 148,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      high_precision_3d_preview: false,
      enable_cleanup: true,
      enable_outline: false,
      outline_width: 2,
      hue_enable: false,
      chroma_gate: 15,
      use_lut_constrained: false,
      auto_dynamic_range: false,
      largeFormatEnabled: false,
      cropModalOpen: false,
      hasManualPreview: true,
      sessionId: "material-session-old",
      previewImageUrl: "/api/files/preview-old.png",
      previewGlbUrl: "/api/files/preview-old.glb",
      palette: [
        {
          quantized_hex: "112233",
          matched_hex: "445566",
          pixel_count: 10,
          percentage: 100,
        },
      ],
      layerImages: [
        { layer_index: 0, name: "layer-1", url: "/api/files/layer-old.png" },
      ],
      submitPreview: mockSubmitPreview,
    });
  }

  function establishCompensatedSvgPreviewBaseline() {
    establishMaterialPreviewBaseline();
    useConverterStore.setState({
      imageFile: new File(["<svg/>"], "holes.svg", { type: "image/svg+xml" }),
      modeling_mode: ModelingMode.VECTOR,
      svg_hole_compensation_enabled: true,
      svg_hole_max_area_mm2: 0.5,
      svg_hole_max_width_mm: 0.1,
    });
  }

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mockSubmitPreview.mockResolvedValue(undefined);
    vi.mocked(fetchMaterialSolverCacheStatus).mockImplementation(
      async (key) => materialCacheStatus(key, true),
    );
    useConverterStore.setState({
      ...DEFAULT_STATE,
      imageFile: null,
      source_version: "legacy",
      lut_name: "",
      lut_names: [],
      selectedMaterialDirNames: [],
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
      submitPreview: mockSubmitPreview,
    });
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not trigger when hasManualPreview is false", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({ imageFile: fakeFile(), lut_name: "my-lut" });
      vi.advanceTimersByTime(500);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();
  });

  it("does not re-trigger immediately after manual preview baseline is established", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({
        imageFile: fakeFile(),
        lut_name: "my-lut",
        hasManualPreview: true,
      });
      vi.advanceTimersByTime(500);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();
  });

  it("triggers submitPreview 300ms after a tracked param changes on an established baseline", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({
        imageFile: fakeFile(),
        lut_name: "my-lut",
        hasManualPreview: true,
      });
    });

    act(() => {
      useConverterStore.setState({ hue_enable: true });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("does NOT trigger while cropModalOpen is true, and only triggers after baseline re-established plus a new change", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({
        imageFile: fakeFile(),
        lut_name: "my-lut",
        hasManualPreview: true,
        cropModalOpen: true,
      });
      vi.advanceTimersByTime(500);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();

    act(() => {
      useConverterStore.setState({ cropModalOpen: false });
      useConverterStore.setState({ chroma_gate: 16 });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(mockSubmitPreview).toHaveBeenCalledTimes(0);

    act(() => {
      useConverterStore.setState({ hue_enable: true });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("re-triggers when a new image is uploaded after baseline and subsequent change", () => {
    renderHook(() => useAutoPreview());

    const file1 = fakeFile("img1.png");
    const file2 = fakeFile("img2.png");

    act(() => {
      useConverterStore.setState({
        imageFile: file1,
        lut_name: "my-lut",
        hasManualPreview: true,
      });
    });

    act(() => {
      useConverterStore.setState({ hue_enable: true });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);

    act(() => {
      useConverterStore.setState({ imageFile: file2 });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(2);
  });

  it("does not trigger sync-external-store loops for native bundle state", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => {
      renderHook(() => useAutoPreview());

      act(() => {
        useConverterStore.setState({
          imageFile: fakeFile(),
          source_version: "native",
          lut_name: "",
          selectedNativeBrandKey: "brand-a",
          selectedNativeDbNames: ["db-1"],
          color_layers: 5,
          layer_height_mm: 0.08,
          hasManualPreview: true,
        });
      });

      act(() => {
        vi.advanceTimersByTime(500);
      });
    }).not.toThrow();

    expect(
      consoleErrorSpy.mock.calls.some(
        ([message]) =>
          typeof message === "string" &&
          (
            message.includes("getSnapshot should be cached") ||
            message.includes("Maximum update depth exceeded")
          ),
      ),
    ).toBe(false);

    consoleErrorSpy.mockRestore();
  });

  it("invalidates a stale material preview as soon as quantize colors change", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useConverterStore.getState().setQuantizeColors(8);
    });

    const state = useConverterStore.getState();
    expect(state.sessionId).toBeNull();
    expect(state.previewImageUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.layerImages).toEqual([]);
    expect(state.hasManualPreview).toBe(true);
  });

  it("regenerates a material preview after the quantize count changes", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useConverterStore.getState().setQuantizeColors(8);
    });
    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(mockSubmitPreview).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("regenerates when parameters return to the last successful snapshot after invalidation", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useConverterStore.getState().setQuantizeColors(8);
    });
    act(() => {
      vi.advanceTimersByTime(150);
      useConverterStore.getState().setQuantizeColors(48);
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(useConverterStore.getState().previewImageUrl).toBeNull();
    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("keeps the current preview when the material selection is unchanged", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });
    const stateBeforeConfirmation = useConverterStore.getState();
    act(() => {
      useConverterStore.getState().setSelectedMaterialDirNames([
        "profile/yellow",
        "profile/black",
      ]);
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    const stateAfterConfirmation = useConverterStore.getState();
    expect(stateAfterConfirmation).toBe(stateBeforeConfirmation);
    expect(stateAfterConfirmation.sessionId).toBe("material-session-old");
    expect(stateAfterConfirmation.previewImageUrl).toBe(
      "/api/files/preview-old.png",
    );
    expect(stateAfterConfirmation.previewGlbUrl).toBe(
      "/api/files/preview-old.glb",
    );
    expect(stateAfterConfirmation.layerImages).toEqual([
      {
        layer_index: 0,
        name: "layer-1",
        url: "/api/files/layer-old.png",
      },
    ]);
    expect(mockSubmitPreview).not.toHaveBeenCalled();
  });

  it("keeps a pending refresh across an actual hook unmount and remount", () => {
    const firstMount = renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });
    act(() => {
      useConverterStore.getState().setQuantizeColors(8);
    });

    firstMount.unmount();
    renderHook(() => useAutoPreview());

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("cancels the automatic timer when the user submits the pending preview manually", () => {
    mockSubmitPreview.mockImplementation(async () => {
      useConverterStore.setState({
        isLoading: true,
        hasManualPreview: true,
      });
    });
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });
    act(() => {
      useConverterStore.getState().setQuantizeColors(8);
    });
    act(() => {
      void useConverterStore.getState().submitPreview();
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("does not regenerate when a material preview response synchronizes compatibility fields", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useConverterStore.setState({
        color_layers: 10,
        layer_height_mm: 0.04,
      });
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();
    expect(useConverterStore.getState().sessionId).toBe(
      "material-session-old",
    );
  });

  it("keeps an ordinary preview session and GLB while dimensions update live", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useConverterStore.getState().setTargetWidthMm(160);
      vi.advanceTimersByTime(300);
    });

    const state = useConverterStore.getState();
    expect(state.target_width_mm).toBe(160);
    expect(state.sessionId).toBe("material-session-old");
    expect(state.previewImageUrl).toBe("/api/files/preview-old.png");
    expect(state.previewGlbUrl).toBe("/api/files/preview-old.glb");
    expect(state.previewAutoRefreshPending).toBe(false);
    expect(mockSubmitPreview).not.toHaveBeenCalled();
  });

  it.each(["legacy", "material"] as const)("refreshes compensated SVG dimensions once without a %s source cache preflight", async (sourceVersion) => {
    establishMaterialPreviewBaseline();
    useConverterStore.setState({
      imageFile: new File(["<svg/>"], "holes.svg", { type: "image/svg+xml" }),
      source_version: sourceVersion,
      lut_name: "my-lut", lut_names: ["my-lut"],
      modeling_mode: ModelingMode.VECTOR,
      svg_hole_compensation_enabled: true,
      aspectRatio: 2, target_width_mm: 60, target_height_mm: 30,
    });
    renderHook(() => useAutoPreview());

    act(() => { useConverterStore.getState().setTargetWidthMm(220); });
    expect(useConverterStore.getState()).toMatchObject({
      target_width_mm: 220, target_height_mm: 110,
      sessionId: null, previewImageUrl: null, previewGlbUrl: null,
      hasManualPreview: true, previewAutoRefreshPending: true,
    });
    expect(mockSubmitPreview).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(fetchMaterialSolverCacheStatus).not.toHaveBeenCalled();
    expect(mockSubmitPreview).toHaveBeenCalledOnce();
  });

  it("restarts the compensated-size debounce for the latest linked dimensions", async () => {
    establishMaterialPreviewBaseline();
    useConverterStore.setState({
      imageFile: new File(["<svg/>"], "holes.svg", { type: "image/svg+xml" }),
      modeling_mode: ModelingMode.VECTOR,
      svg_hole_compensation_enabled: true,
      aspectRatio: 2, target_width_mm: 60, target_height_mm: 30,
    });
    renderHook(() => useAutoPreview());
    act(() => { useConverterStore.getState().setTargetWidthMm(120); });
    await act(async () => { await vi.advanceTimersByTimeAsync(150); });
    act(() => { useConverterStore.getState().setTargetHeightMm(110); });
    await act(async () => { await vi.advanceTimersByTimeAsync(299); });
    expect(mockSubmitPreview).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(mockSubmitPreview).toHaveBeenCalledOnce();
    expect(useConverterStore.getState()).toMatchObject({ target_width_mm: 220, target_height_mm: 110 });
  });

  it("keeps ordinary SVG dimension changes projection-only when compensation is disabled", async () => {
    establishMaterialPreviewBaseline();
    useConverterStore.setState({
      imageFile: new File(["<svg/>"], "holes.svg", { type: "image/svg+xml" }),
      modeling_mode: ModelingMode.VECTOR,
      svg_hole_compensation_enabled: false,
      aspectRatio: 2, target_width_mm: 60, target_height_mm: 30,
    });
    renderHook(() => useAutoPreview());
    act(() => { useConverterStore.getState().setTargetHeightMm(110); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(useConverterStore.getState()).toMatchObject({
      target_width_mm: 220, target_height_mm: 110,
      sessionId: "material-session-old", previewImageUrl: "/api/files/preview-old.png",
      previewGlbUrl: "/api/files/preview-old.glb", previewAutoRefreshPending: false,
    });
    expect(mockSubmitPreview).not.toHaveBeenCalled();
  });

  it("refreshes consecutive SVG area and width changes without querying the material solver cache", async () => {
    const completeCacheQueries: Array<() => void> = [];
    vi.mocked(fetchMaterialSolverCacheStatus).mockImplementation((key) =>
      new Promise((resolve) => {
        completeCacheQueries.push(() => resolve(materialCacheStatus(key, true)));
      }),
    );
    mockSubmitPreview.mockImplementation(async () => {
      const state = useConverterStore.getState();
      useConverterStore.setState({
        hasManualPreview: true, isLoading: false, previewAutoRefreshPending: false,
        previewSubmissionSequence: state.previewSubmissionSequence + 1,
        sessionId: "refreshed-compensation", previewImageUrl: "/api/files/refreshed.png",
      });
    });
    establishCompensatedSvgPreviewBaseline();
    renderHook(() => useAutoPreview());
    act(() => { useConverterStore.getState().setSvgHoleMaxAreaMm2(0.8); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    act(() => { useConverterStore.getState().setSvgHoleMaxWidthMm(0.2); });
    await act(async () => {
      completeCacheQueries.forEach((complete) => complete());
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(mockSubmitPreview).toHaveBeenCalledTimes(2);
    expect(fetchMaterialSolverCacheStatus).not.toHaveBeenCalled();
    expect(useConverterStore.getState()).toMatchObject({
      sessionId: "refreshed-compensation", previewAutoRefreshPending: false,
      svg_hole_max_area_mm2: 0.8, svg_hole_max_width_mm: 0.2,
    });
  });

  it("debounces consecutive SVG compensation thresholds from the latest change", async () => {
    establishCompensatedSvgPreviewBaseline();
    useConverterStore.setState({ source_version: "legacy", lut_name: "my-lut", lut_names: ["my-lut"] });
    renderHook(() => useAutoPreview());
    act(() => { useConverterStore.getState().setSvgHoleMaxAreaMm2(0.8); });
    await act(async () => { await vi.advanceTimersByTimeAsync(150); });
    act(() => { useConverterStore.getState().setSvgHoleMaxWidthMm(0.2); });
    await act(async () => { await vi.advanceTimersByTimeAsync(299); });
    expect(mockSubmitPreview).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(mockSubmitPreview).toHaveBeenCalledOnce();
    expect(useConverterStore.getState()).toMatchObject({ svg_hole_max_area_mm2: 0.8, svg_hole_max_width_mm: 0.2 });
  });

  it("still requires the first manual preview after editing SVG compensation options", async () => {
    establishCompensatedSvgPreviewBaseline();
    useConverterStore.setState({
      hasManualPreview: false, sessionId: null, previewImageUrl: null, previewGlbUrl: null,
      svg_hole_compensation_enabled: false,
    });
    renderHook(() => useAutoPreview());
    act(() => {
      useConverterStore.getState().setSvgHoleMaxAreaMm2(0.8);
      useConverterStore.getState().setSvgHoleCompensationEnabled(true);
      useConverterStore.getState().setSvgHoleMaxWidthMm(0.2);
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(mockSubmitPreview).not.toHaveBeenCalled();
    expect(fetchMaterialSolverCacheStatus).not.toHaveBeenCalled();
    expect(useConverterStore.getState()).toMatchObject({ hasManualPreview: false, previewAutoRefreshPending: false });
    await act(async () => { await useConverterStore.getState().submitPreview(); });
    expect(mockSubmitPreview).toHaveBeenCalledOnce();
  });

  it("keeps the dedicated large-format refresh when total dimensions change", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
      useConverterStore.setState({ largeFormatEnabled: true });
    });

    act(() => {
      useConverterStore.getState().setTargetWidthMm(320);
    });

    expect(useConverterStore.getState().sessionId).toBeNull();
    expect(useConverterStore.getState().previewGlbUrl).toBeNull();

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["modeling mode", { modeling_mode: ModelingMode.PIXEL }],
    ["cleanup", { enable_cleanup: false }],
    ["backing material", { materialBackingMaterialDirName: "profile/yellow" }],
    ["LUT-constrained matching", { use_lut_constrained: true }],
    ["automatic dynamic range", { auto_dynamic_range: true }],
    ["high-precision 3D", { high_precision_3d_preview: true }],
    ["outline", { enable_outline: true }],
  ])("regenerates a material preview after %s changes", (_label, patch) => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useConverterStore.setState(patch);
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it.each([
    [
      "selection",
      () =>
        useConverterStore.getState().setSelectedMaterialDirNames([
          "profile/white",
          "profile/black",
        ]),
    ],
    [
      "layer count",
      () => useConverterStore.getState().setMaterialLayerCount(8),
    ],
    [
      "layer height",
      () => useConverterStore.getState().setMaterialLayerHeightMm(0.08),
    ],
  ])(
    "regenerates after the material %s setter finds a persisted cache",
    async (_label, change) => {
      renderHook(() => useAutoPreview());

      act(() => {
        establishMaterialPreviewBaseline();
      });
      act(() => {
        change();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300);
      });

      expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledTimes(1);
      expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
    },
  );

  it("waits for a manual preview when the new material layer count has no cache", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockImplementationOnce(
      async (key) => materialCacheStatus(key, false),
    );
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });
    act(() => {
      useConverterStore.getState().setMaterialLayerCount(8);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledWith(
      {
        materialDirectoryNames: ["profile/yellow", "profile/black"],
        layerCount: 8,
        layerHeightMm: 0.04,
        substrate: "white",
      },
      { gridResolution: undefined },
    );
    expect(mockSubmitPreview).not.toHaveBeenCalled();
    expect(useConverterStore.getState().previewAutoRefreshPending).toBe(false);
  });

  it("keeps checking material cache keys after a miss", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus)
      .mockImplementationOnce(async (key) => materialCacheStatus(key, false))
      .mockImplementationOnce(async (key) => materialCacheStatus(key, true));
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });
    act(() => {
      useConverterStore.getState().setMaterialLayerCount(8);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();

    act(() => {
      useConverterStore.getState().setMaterialLayerCount(10);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledTimes(2);
    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("clears stale output without regenerating when the source becomes incomplete", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });
    act(() => {
      useConverterStore.getState().setSelectedMaterialDirNames([]);
      vi.advanceTimersByTime(300);
    });

    expect(useConverterStore.getState().previewImageUrl).toBeNull();
    expect(useConverterStore.getState().previewGlbUrl).toBeNull();
    expect(mockSubmitPreview).not.toHaveBeenCalled();
  });

  it.each([
    ["solver cache resolution", { enableSolverCacheGridSelection: true }],
    ["SVG sampling density", { svgPixelsPerMm: 12 }],
  ])("regenerates a material preview after %s changes", (_label, patch) => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useSettingsStore.setState(patch);
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("does not rebuild the full preview when the SVG renderer preference changes", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({
        imageFile: fakeFile("preview.svg"),
        lut_name: "my-lut",
        modeling_mode: ModelingMode.VECTOR,
        hasManualPreview: true,
        sessionId: "vector-session",
        previewImageUrl: "/api/files/current.png",
        previewGlbUrl: "/api/files/current.glb",
      });
    });
    act(() => {
      useSettingsStore.getState().setEnableSmoothVectorPreview(false);
      vi.advanceTimersByTime(500);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();
    expect(useConverterStore.getState().sessionId).toBe("vector-session");
    expect(useConverterStore.getState().previewGlbUrl).toBe(
      "/api/files/current.glb",
    );
  });

  it("does not restart a legacy preview when a recipe changes only derived layers", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({
        imageFile: fakeFile("legacy-recipe.png"),
        source_version: "legacy",
        lut_name: "my-lut",
        color_layers: 4,
        layer_height_mm: 0.08,
        hasManualPreview: true,
        sessionId: "legacy-recipe-session",
        previewImageUrl: "/api/files/legacy-preview.png",
        previewGlbUrl: "/api/files/legacy-preview.glb",
      });
    });

    act(() => {
      useConverterStore
        .getState()
        .upsertRecipeOverrides(
          ["region-1"],
          [1, 1, 1, 1, 1, 1],
          "Top2Bottom",
        );
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();
    expect(useConverterStore.getState().sessionId).toBe(
      "legacy-recipe-session",
    );
    expect(useConverterStore.getState().color_layers).toBe(4);
  });
});
