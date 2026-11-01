import { describe, it, expect, beforeEach, vi } from "vitest";
import type { BatchResponse } from "../api/types";
import { StructureMode, ColorMode, ModelingMode } from "../api/types";

// Mock the converter API module
vi.mock("../api/converter", () => ({
  fetchExportMaterialSelection: vi.fn(async () => (await import("./fixtures/exportMaterialSelection")).READY_EXPORT_MATERIAL_SELECTION),
  convertBatch: vi.fn(),
  fetchLutList: vi.fn(),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  fetchBedSizes: vi.fn(),
  uploadHeightmap: vi.fn(),
  fetchLutColors: vi.fn(),
  cropImage: vi.fn(),
}));

import { useConverterStore } from "../stores/converter";
import { convertBatch } from "../api/converter";

const mockedConvertBatch = vi.mocked(convertBatch);

/**
 * 批量模式 store 测试：验证 submitBatch 对 modelUrl 和 batchResult 的状态管理
 * Validates: Requirements 2.3, 2.4, 6.4, 10.6
 */

function resetStore(overrides: Record<string, unknown> = {}): void {
  useConverterStore.setState({
    batchMode: true,
    batchFiles: [new File(["a"], "img1.png", { type: "image/png" })],
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
    enable_coating: false,
    coating_height_mm: 0.08,
    enable_outline: false,
    outline_width: 2,
    svg_hole_compensation_enabled: false,
    svg_hole_max_area_mm2: 0.5,
    svg_hole_max_width_mm: 0.1,
    enable_relief: false,
    color_height_map: {},
    heightmap_max_height: 3.0,
    autoHeightMode: "darker-higher",
    palette: [],
    lutColors: [],
    modelUrl: null,
    previewGlbUrl: null,
    batchPreviewItems: [],
    threemfDiskPath: null,
    downloadUrl: null,
    ...overrides,
  });
}

describe("submitBatch modelUrl 与 batchResult 状态管理", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  it.each([
    { enabled: true, width: 0.5, mode: ModelingMode.HIGH_FIDELITY, extension: "png" },
    { enabled: true, width: 10, mode: ModelingMode.VECTOR, extension: "svg" },
    { enabled: false, width: 3, mode: ModelingMode.HIGH_FIDELITY, extension: "png" },
  ])("forwards outline settings for $extension: $enabled, $width mm", async ({ enabled, width, mode, extension }) => {
    const files = ["one", "two"].map((name) => new File(["image"], `${name}.${extension}`));
    resetStore({ batchFiles: files, modeling_mode: mode, enable_outline: enabled, outline_width: width });
    mockedConvertBatch.mockResolvedValueOnce({ status: "ok", message: "done",
      download_url: null, threemf_disk_path: null, preview_3d_url: null,
      results: [], warnings: [] });

    await useConverterStore.getState().submitBatch();

    expect(mockedConvertBatch).toHaveBeenCalledWith(files, expect.objectContaining({
      enable_outline: enabled, outline_width: width,
    }));
  });

  it.each([true, false])("forwards coating and compensation settings for multiple SVGs: %s", async (enabled) => {
    const files = ["one.svg", "two.svg"].map((name) =>
      new File(['<svg xmlns="http://www.w3.org/2000/svg"/>'], name, { type: "image/svg+xml" }),
    );
    resetStore({ batchFiles: files, modeling_mode: ModelingMode.VECTOR,
      enable_coating: enabled, coating_height_mm: 0.12,
      svg_hole_compensation_enabled: true, svg_hole_max_area_mm2: 0.75,
      svg_hole_max_width_mm: 0.21 });
    mockedConvertBatch.mockResolvedValueOnce({ status: "ok", message: "done",
      download_url: null, threemf_disk_path: null, preview_3d_url: null,
      results: [], warnings: [] });
    await useConverterStore.getState().submitBatch();
    expect(mockedConvertBatch).toHaveBeenCalledWith(files, expect.objectContaining({
      enable_coating: enabled, coating_height_mm: 0.12,
      svg_hole_compensation_enabled: true, svg_hole_max_area_mm2: 0.75,
      svg_hole_max_width_mm: 0.21,
    }));
  });

  // 用例 A: preview_3d_url 非空但 preview_items 为空时，不使用旧合并 GLB 兜底
  // Validates: Requirements 2.3
  it("preview_3d_url 非空但 preview_items 为空时不设置单模型预览 URL", async () => {
    const response: BatchResponse = {
      status: "ok",
      message: "Batch completed",
      download_url: "/api/files/merged.3mf",
      threemf_disk_path: "/tmp/merged.3mf",
      preview_3d_url: "/api/files/abc.glb",
      results: [
        { filename: "img1.png", status: "success" },
        { filename: "img2.png", status: "success" },
      ],
      warnings: [],
    };
    mockedConvertBatch.mockResolvedValueOnce(response);

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.modelUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.batchPreviewItems).toEqual([]);
    expect(state.batchResult).toEqual({
      ...response,
      download_url: "/api/files/merged.3mf",
      threemf_disk_path: null,
    });
    expect(state.threemfDiskPath).toBeNull();
    expect(state.downloadUrl).toBe("/api/files/merged.3mf");
    expect(state.batchLoading).toBe(false);
  });

  // 用例 A2: preview_items 非空时，优先使用多模型批量预览
  // Validates: Requirements 2.3
  it("preview_items 非空时使用批量预览条目，并清空单模型预览 URL", async () => {
    resetStore({
      modelUrl: "/api/files/old-model.glb",
      previewGlbUrl: "/api/files/old-preview.glb",
    });
    const response: BatchResponse = {
      status: "ok",
      message: "Batch completed",
      download_url: "/api/files/merged.3mf",
      threemf_disk_path: "/tmp/merged.3mf",
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
        {
          url: "/api/files/second.glb",
          filename: "img2.png",
          tx_mm: 33,
          ty_mm: 0,
          width_mm: 30,
          depth_mm: 20,
        },
      ],
      results: [
        { filename: "img1.png", status: "success" },
        { filename: "img2.png", status: "success" },
      ],
      warnings: [],
    };
    mockedConvertBatch.mockResolvedValueOnce(response);

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.batchPreviewItems).toEqual(response.preview_items);
    expect(state.modelUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.batchResult).toEqual({
      ...response,
      threemf_disk_path: null,
    });
    expect(state.threemfDiskPath).toBeNull();
    expect(state.downloadUrl).toBe("/api/files/merged.3mf");
  });

  it("即使接口返回超多 preview_items，前端也保留浏览器保护上限", async () => {
    resetStore();
    const previewItems = Array.from({ length: 120 }, (_, index) => ({
      url: `/api/files/item-${index}.glb`,
      filename: `img${index}.png`,
      tx_mm: index * 2,
      ty_mm: 0,
      width_mm: 30,
      depth_mm: 20,
    }));
    const response: BatchResponse = {
      status: "ok",
      message: "Batch completed",
      download_url: "/api/files/merged.3mf",
      threemf_disk_path: "/tmp/merged.3mf",
      preview_3d_url: "/api/files/item-0.glb",
      preview_items: previewItems,
      results: previewItems.map((item) => ({
        filename: item.filename,
        status: "success" as const,
      })),
      warnings: [],
    };
    mockedConvertBatch.mockResolvedValueOnce(response);

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.batchPreviewItems).toHaveLength(96);
    expect(state.batchPreviewItems.map((item) => item.filename)).toEqual(
      previewItems.slice(0, 96).map((item) => item.filename),
    );
    expect(state.batchResult).toEqual({
      ...response,
      threemf_disk_path: null,
    });
  });

  // 用例 B: preview_3d_url 为 null 时，清空旧模型预览，避免显示上一批结果
  // Validates: Requirements 2.4
  it("preview_3d_url 为 null 时清空旧模型预览", async () => {
    const previousModelUrl = "/api/files/previous-model.glb";
    resetStore({ modelUrl: previousModelUrl });

    const response: BatchResponse = {
      status: "ok",
      message: "Batch completed",
      download_url: "/api/files/merged.3mf",
      threemf_disk_path: "/tmp/merged.3mf",
      preview_3d_url: null,
      results: [
        { filename: "img1.png", status: "success" },
      ],
      warnings: [],
    };
    mockedConvertBatch.mockResolvedValueOnce(response);

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.modelUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.batchPreviewItems).toEqual([]);
    expect(state.batchResult).toEqual({
      ...response,
      threemf_disk_path: null,
    });
    expect(state.threemfDiskPath).toBeNull();
    expect(state.downloadUrl).toBe("/api/files/merged.3mf");
  });

  // 用例 C: download_url 和 preview_3d_url 都为 null（全失败语义）
  // → modelUrl 保持不变，batchResult.results 被记录
  // Validates: Requirements 2.4, 6.4
  it("全失败时 modelUrl 保持不变，batchResult.results 被记录", async () => {
    const previousModelUrl = "/api/files/old-model.glb";
    resetStore({ modelUrl: previousModelUrl });

    const response: BatchResponse = {
      status: "ok",
      message: "All items failed",
      download_url: null,
      threemf_disk_path: null,
      preview_3d_url: null,
      results: [
        { filename: "img1.png", status: "failed", error: "Invalid image" },
        { filename: "img2.png", status: "failed", error: "Unsupported format" },
      ],
      warnings: [],
    };
    mockedConvertBatch.mockResolvedValueOnce(response);

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.modelUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.batchPreviewItems).toEqual([]);
    expect(state.batchResult).not.toBeNull();
    expect(state.batchResult!.results).toHaveLength(2);
    expect(state.batchResult!.results[0].status).toBe("failed");
    expect(state.batchResult!.results[1].status).toBe("failed");
    expect(state.batchResult!.download_url).toBeNull();
    expect(state.batchResult!.threemf_disk_path).toBeNull();
    expect(state.batchResult!.preview_3d_url).toBeNull();
    expect(state.threemfDiskPath).toBeNull();
    expect(state.downloadUrl).toBeNull();
  });
});
