import { describe, it, expect, beforeEach, vi } from "vitest";
import type { BatchResponse } from "../../api/types";
import { StructureMode, ColorMode, ModelingMode } from "../../api/types";

const notificationMocks = vi.hoisted(() => ({
  showBrowserCompletionNotification: vi.fn(),
}));

// Mock the converter API module
vi.mock("../../api/converter", () => ({
  fetchExportMaterialSelection: vi.fn(async () => (await import("../../__tests__/fixtures/exportMaterialSelection")).READY_EXPORT_MATERIAL_SELECTION),
  convertBatch: vi.fn(),
  // Provide stubs for other imports used by converterStore
  fetchLutList: vi.fn(),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  fetchBedSizes: vi.fn(),
  uploadHeightmap: vi.fn(),
  fetchLutColors: vi.fn(),
  cropImage: vi.fn(),
}));

vi.mock("../../utils/browserNotifications", () => ({
  showBrowserCompletionNotification:
    notificationMocks.showBrowserCompletionNotification,
}));

import { useConverterStore } from "../converter";
import { useSettingsStore } from "../settingsStore";
import { convertBatch } from "../../api/converter";

const mockedConvertBatch = vi.mocked(convertBatch);

/**
 * Store 批量模式 unit tests
 * Validates: Requirements 4.1, 5.1, 5.3, 6.4
 */

function resetStore(): void {
  useSettingsStore.setState({
    printerModel: "bambu-p1s",
    slicerSoftware: "OrcaSlicer",
    nozzleSize: "0.2",
    deviceProfileId: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
    buildPlateId: "textured-pei-plate",
    enableBaseLayerHeightModifier: false,
    enableWipeTowerAutoPlacement: false,
    custom3mfTemplateId: null,
    svgPixelsPerMm: 10,
    enableCompletionNotifications: false,
    language: "zh",
  });
  useConverterStore.setState({
    batchMode: true,
    batchFiles: [],
    batchLoading: false,
    batchResult: null,
    error: null,
    source_version: "legacy",
    lut_name: "test-lut",
    target_width_mm: 60,
    spacer_thick: 1.2,
    structure_mode: StructureMode.DOUBLE_SIDED,
    color_mode: ColorMode.FOUR_COLOR_RYBW,
    modeling_mode: ModelingMode.HIGH_FIDELITY,
    color_layers: 5,
    layer_height_mm: 0.08,
    quantize_colors: 48,
    enable_cleanup: true,
    enable_relief: false,
    color_height_map: {},
    heightmap_max_height: 3.0,
    autoHeightMode: "darker-higher",
    palette: [],
    lutColors: [],
    selectedMaterialDirNames: [],
    materialLayerCount: 5,
    materialLayerHeightMm: 0.08,
    materialBackingMaterialDirName: "",
    nativeBrandGroups: [],
    selectedNativeBrandKey: "",
    selectedNativeDbNames: [],
    model_enable: false,
    model_only: false,
    model_threshold: null,
    model_margin: null,
    use_lut_constrained: false,
    auto_dynamic_range: false,
    modelUrl: null,
    previewGlbUrl: null,
    batchPreviewItems: [],
    threemfDiskPath: null,
    downloadUrl: null,
  });
}

const mockBatchResponse: BatchResponse = {
  status: "ok",
  message: "Batch completed",
  download_url: "/api/files/batch_result.3mf",
  threemf_disk_path: "/tmp/batch_result.3mf",
  preview_3d_url: null,
  results: [
    { filename: "img1.png", status: "success" },
    { filename: "img2.jpg", status: "failed", error: "Invalid image" },
  ],
  warnings: [],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("submitBatch API 调用和状态管理", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  // Requirement 4.1: submitBatch 调用 API 并传入正确的文件和参数
  it("submitBatch 调用 convertBatch 并传入 batchFiles 和当前共享参数", async () => {
    const files = [
      new File(["a"], "img1.png", { type: "image/png" }),
      new File(["b"], "img2.jpg", { type: "image/jpeg" }),
    ];
    useConverterStore.setState({ batchFiles: files });
    mockedConvertBatch.mockResolvedValueOnce(mockBatchResponse);

    await useConverterStore.getState().submitBatch();

    expect(mockedConvertBatch).toHaveBeenCalledOnce();
    const [calledFiles, calledParams] = mockedConvertBatch.mock.calls[0];
    expect(calledFiles).toBe(files);
    expect(calledParams).toEqual({
      source_kind: "legacy_single",
      lut_name: "test-lut",
      target_width_mm: 60,
      spacer_thick: 1.2,
      backing_infill_density_percent: 100,
      structure_mode: StructureMode.DOUBLE_SIDED,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      color_layers: 5,
      layer_height_mm: 0.08,
      quantize_colors: 48,
      high_precision_3d_preview: false,
      enable_cleanup: true,
      svg_pixels_per_mm: 10,
      svg_hole_compensation_enabled: false,
      svg_hole_max_area_mm2: 0.5,
      svg_hole_max_width_mm: 0.1,
      hue_weight: 0,
      chroma_gate: 0,
      use_lut_constrained: false,
      auto_dynamic_range: false,
      separate_backing: false,
      backing_output: "same_project",
      native_filament_profiles: undefined,
      enable_relief: false,
      enable_coating: false,
      coating_height_mm: 0.08,
      enable_outline: false,
      outline_width: 2,
      printer_id: "bambu-p1s",
      slicer: "OrcaSlicer",
      nozzle_size: "0.2",
      device_profile_id: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
      build_plate_id: "textured-pei-plate",
      enable_base_layer_height_modifier: false,
      enable_wipe_tower_auto_placement: false,
      custom_3mf_template_id: null,
    });
    expect(
      notificationMocks.showBrowserCompletionNotification,
    ).not.toHaveBeenCalled();
  });

  it("submitBatch 会把 2.5D 浮雕参数传给批量生成 API", async () => {
    const files = [new File(["a"], "img1.png", { type: "image/png" })];
    useConverterStore.setState({
      batchFiles: files,
      enable_relief: true,
      spacer_thick: 1.2,
      heightmap_max_height: 3.0,
      color_height_map: { "#ff0000": 0.5, "#ffffff": 0.1 },
      autoHeightMode: "darker-higher",
    });
    mockedConvertBatch.mockResolvedValueOnce(mockBatchResponse);

    await useConverterStore.getState().submitBatch();

    const [, calledParams] = mockedConvertBatch.mock.calls[0];
    expect(calledParams).toMatchObject({
      enable_relief: true,
      height_mode: "color",
      heightmap_max_height: 4.2,
      color_height_map: {
        "#ff0000": 1.7,
        "#ffffff": 1.3,
      },
    });
  });

  it("submitBatch 支持耗材档案来源参数", async () => {
    const files = [new File(["a"], "img1.png", { type: "image/png" })];
    useConverterStore.setState({
      batchFiles: files,
      source_version: "material",
      selectedMaterialDirNames: ["brand/red", "brand/white"],
      materialLayerCount: 7,
      materialLayerHeightMm: 0.06,
      materialBackingMaterialDirName: "brand/white",
    });
    mockedConvertBatch.mockResolvedValueOnce(mockBatchResponse);

    await useConverterStore.getState().submitBatch();

    const [, calledParams] = mockedConvertBatch.mock.calls[0];
    expect(calledParams).toMatchObject({
      source_kind: "legacy_single",
      lut_name: "__material_archive__",
      material_source: "material_archive",
      selected_materials: ["brand/red", "brand/white"],
      material_layer_count: 7,
      material_layer_height_mm: 0.06,
      material_backing_material_index: 1,
      color_layers: 7,
      layer_height_mm: 0.06,
    });
  });

  it("submitBatch 会保留耗材档案的分离底板选择", async () => {
    const files = [new File(["a"], "img1.png", { type: "image/png" })];
    useConverterStore.setState({
      batchFiles: files,
      source_version: "material",
      selectedMaterialDirNames: ["brand/yellow", "brand/white"],
      materialBackingMaterialDirName: "brand/white",
      separate_backing: true,
    });
    mockedConvertBatch.mockResolvedValueOnce(mockBatchResponse);

    await useConverterStore.getState().submitBatch();

    const [, calledParams] = mockedConvertBatch.mock.calls[0];
    expect(calledParams).toMatchObject({
      material_backing_material_index: 1,
      separate_backing: true,
    });
  });

  it("submitBatch 支持反推 LUT 来源参数", async () => {
    const files = [new File(["a"], "img1.png", { type: "image/png" })];
    useConverterStore.setState({
      batchFiles: files,
      source_version: "native",
      selectedNativeBrandKey: "pla-bambu",
      selectedNativeDbNames: ["red.cdb", "white.cdb"],
      color_layers: 6,
      layer_height_mm: 0.08,
      model_enable: true,
      model_only: true,
      model_threshold: 0.3,
      model_margin: 0.1,
      nativeBrandGroups: [
        {
          brand_key: "pla-bambu",
          material_type: "PLA",
          vendor: "Bambu",
          display_name: "Bambu PLA",
          db_options: [
            {
              name: "red.cdb",
              path: "/db/red.cdb",
              color_mode: "native",
            },
            {
              name: "white.cdb",
              path: "/db/white.cdb",
              color_mode: "native",
            },
          ],
          default_db_names: ["red.cdb"],
          supported_modes: [{ color_layers: 6, layer_height_mm: 0.08 }],
          model_name: "model.json",
          package_name: "package.msgpack",
        },
      ],
    });
    mockedConvertBatch.mockResolvedValueOnce(mockBatchResponse);

    await useConverterStore.getState().submitBatch();

    const [, calledParams] = mockedConvertBatch.mock.calls[0];
    expect(calledParams).toMatchObject({
      source_kind: "native_bundle",
      material_type: "PLA",
      vendor: "Bambu",
      db_names: ["red.cdb", "white.cdb"],
      color_layers: 6,
      layer_height_mm: 0.08,
      model_enable: true,
      model_only: true,
      model_threshold: 0.3,
      model_margin: 0.1,
    });
  });

  it("submitBatch 在无预览 palette 时会用 LUT 颜色自动生成浮雕高度", async () => {
    const files = [new File(["a"], "img1.png", { type: "image/png" })];
    useConverterStore.setState({
      batchFiles: files,
      enable_relief: true,
      spacer_thick: 1.2,
      heightmap_max_height: 2.0,
      color_height_map: {},
      palette: [],
      lutColors: [
        { hex: "#000000", rgb: [0, 0, 0] },
        { hex: "#ffffff", rgb: [255, 255, 255] },
      ],
      autoHeightMode: "darker-higher",
    });
    mockedConvertBatch.mockResolvedValueOnce(mockBatchResponse);

    await useConverterStore.getState().submitBatch();

    const [, calledParams] = mockedConvertBatch.mock.calls[0];
    expect(calledParams.enable_relief).toBe(true);
    expect(calledParams.height_mode).toBe("color");
    expect(calledParams.heightmap_max_height).toBeCloseTo(3.2);
    expect(calledParams.color_height_map?.["000000"]).toBeCloseTo(3.2);
    expect(calledParams.color_height_map?.["ffffff"]).toBeCloseTo(1.28);
  });

  // Requirement 5.1: batchLoading 在请求期间为 true
  it("submitBatch 开始时 batchLoading 为 true", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    useConverterStore.setState({ batchFiles: files });
    useSettingsStore.setState({
      enableCompletionNotifications: true,
      language: "zh",
    });

    // Use a deferred promise to control when the API resolves
    let resolveApi!: (value: BatchResponse) => void;
    const apiPromise = new Promise<BatchResponse>((resolve) => {
      resolveApi = resolve;
    });
    mockedConvertBatch.mockReturnValueOnce(apiPromise);

    const submitPromise = useConverterStore.getState().submitBatch();

    // While the API is pending, batchLoading should be true
    expect(useConverterStore.getState().batchLoading).toBe(true);

    useSettingsStore.setState({ language: "en" });
    resolveApi(mockBatchResponse);
    await submitPromise;

    // After completion, batchLoading should be false
    expect(useConverterStore.getState().batchLoading).toBe(false);
    expect(
      notificationMocks.showBrowserCompletionNotification,
    ).toHaveBeenCalledWith("batch", "en");
  });

  // Requirement 5.3: batchResult 在请求完成后正确存储
  it("submitBatch 成功后 batchResult 存储 API 响应", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    useConverterStore.setState({ batchFiles: files });
    mockedConvertBatch.mockResolvedValueOnce(mockBatchResponse);

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.batchResult).toEqual({
      ...mockBatchResponse,
      threemf_disk_path: null,
    });
    expect(state.batchLoading).toBe(false);
    expect(state.error).toBeNull();
    expect(state.threemfDiskPath).toBeNull();
    expect(state.downloadUrl).toBe("/api/files/batch_result.3mf");
  });

  it("切换打印板后旧批量响应不会覆盖新请求或提前结束 loading", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    const stale = deferred<BatchResponse>();
    const fresh = deferred<BatchResponse>();
    mockedConvertBatch
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    useConverterStore.setState({ batchFiles: files });

    const staleRequest = useConverterStore.getState().submitBatch();
    await vi.waitFor(() => expect(mockedConvertBatch).toHaveBeenCalledTimes(1));
    useSettingsStore
      .getState()
      .setBuildPlateForMachine(
        "OrcaSlicer:bbl:bambu-lab-p1s",
        "smooth-pei-plate",
      );

    const stateAfterPlateChange = useConverterStore.getState();

    const freshRequest = useConverterStore.getState().submitBatch();
    await vi.waitFor(() => expect(mockedConvertBatch).toHaveBeenCalledTimes(2));
    expect(mockedConvertBatch.mock.calls[0][1].build_plate_id).toBe(
      "textured-pei-plate",
    );
    expect(mockedConvertBatch.mock.calls[1][1].build_plate_id).toBe(
      "smooth-pei-plate",
    );

    stale.resolve({
      ...mockBatchResponse,
      download_url: "/api/files/stale-batch.3mf",
    });
    await staleRequest;

    const stateAfterStaleResponse = useConverterStore.getState();

    fresh.resolve({
      ...mockBatchResponse,
      download_url: "/api/files/fresh-batch.3mf",
    });
    await freshRequest;

    expect(stateAfterPlateChange).toMatchObject({
      batchLoading: false,
      batchResult: null,
      downloadUrl: null,
    });
    expect(stateAfterStaleResponse).toMatchObject({
      batchLoading: true,
      batchResult: null,
      downloadUrl: null,
    });
    expect(useConverterStore.getState()).toMatchObject({
      batchLoading: false,
      downloadUrl: "/api/files/fresh-batch.3mf",
    });
  });

  it("submitBatch 成功后存储批量预览条目并清空单模型预览 URL", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    const response: BatchResponse = {
      ...mockBatchResponse,
      preview_3d_url: "/api/files/first.glb",
      preview_items: [
        {
          url: "/api/files/first.glb",
          filename: "img1.png",
          tx_mm: 0,
          ty_mm: 0,
          width_mm: 30,
          depth_mm: 20,
        },
      ],
    };
    useConverterStore.setState({
      batchFiles: files,
      modelUrl: "/api/files/old-model.glb",
      previewGlbUrl: "/api/files/old-preview.glb",
    });
    mockedConvertBatch.mockResolvedValueOnce(response);

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.batchPreviewItems).toEqual(response.preview_items);
    expect(state.modelUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.batchLoading).toBe(false);
  });

  // Error handling: API 错误时 error 状态设置
  it("submitBatch API 错误时设置 error 并将 batchLoading 恢复为 false", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    useConverterStore.setState({ batchFiles: files });
    useSettingsStore.setState({ enableCompletionNotifications: true });
    mockedConvertBatch.mockRejectedValueOnce(new Error("Network error"));

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.error).toBe("请求没有收到服务器响应。请确认 Lumina 后端已启动、网络连接正常，然后重试。");
    expect(state.batchLoading).toBe(false);
    expect(state.batchResult).toBeNull();
    expect(
      notificationMocks.showBrowserCompletionNotification,
    ).not.toHaveBeenCalled();
  });

  // Requirement 6.4: 重新发起批量生成时清空之前的 batchResult
  it("submitBatch 开始时清空之前的 batchResult", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    const previousResult: BatchResponse = {
      status: "ok",
      message: "Previous",
      download_url: "/old.3mf",
      threemf_disk_path: "/tmp/old.3mf",
      preview_3d_url: null,
      results: [{ filename: "old.png", status: "success" }],
      warnings: [],
    };
    useConverterStore.setState({
      batchFiles: files,
      batchResult: previousResult,
      error: "old error",
      threemfDiskPath: "/tmp/old.3mf",
      downloadUrl: "/old.3mf",
    });

    let resolveApi!: (value: BatchResponse) => void;
    const apiPromise = new Promise<BatchResponse>((resolve) => {
      resolveApi = resolve;
    });
    mockedConvertBatch.mockReturnValueOnce(apiPromise);

    const submitPromise = useConverterStore.getState().submitBatch();

    // Immediately after calling submitBatch, previous result should be cleared
    expect(useConverterStore.getState().batchResult).toBeNull();
    expect(useConverterStore.getState().batchPreviewItems).toEqual([]);
    expect(useConverterStore.getState().error).toBeNull();
    expect(useConverterStore.getState().threemfDiskPath).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBeNull();

    resolveApi(mockBatchResponse);
    await submitPromise;
  });

  // Non-Error object thrown by API
  it("submitBatch 处理非 Error 对象的异常", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    useConverterStore.setState({ batchFiles: files });
    mockedConvertBatch.mockRejectedValueOnce("string error");

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.error).toBe("批量处理失败");
    expect(state.batchLoading).toBe(false);
  });
});
