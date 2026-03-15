import { describe, it, expect, beforeEach, vi } from "vitest";
import type { BatchResponse } from "../../api/types";
import { StructureMode, ColorMode, ModelingMode } from "../../api/types";

// Mock the converter API module
vi.mock("../../api/converter", () => ({
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

import { useConverterStore } from "../converterStore";
import { convertBatch } from "../../api/converter";

const mockedConvertBatch = vi.mocked(convertBatch);

/**
 * Store 批量模式 unit tests
 * Validates: Requirements 4.1, 5.1, 5.3, 6.4
 */

function resetStore(): void {
  useConverterStore.setState({
    batchMode: true,
    batchFiles: [],
    batchLoading: false,
    batchResult: null,
    error: null,
    lut_name: "test-lut",
    target_width_mm: 60,
    spacer_thick: 1.2,
    structure_mode: StructureMode.DOUBLE_SIDED,
    auto_bg: false,
    bg_tol: 40,
    color_mode: ColorMode.FOUR_COLOR,
    modeling_mode: ModelingMode.HIGH_FIDELITY,
    quantize_colors: 48,
    enable_cleanup: true,
  });
}

const mockBatchResponse: BatchResponse = {
  status: "ok",
  message: "Batch completed",
  download_url: "/api/files/batch_result.zip",
  results: [
    { filename: "img1.png", status: "success" },
    { filename: "img2.jpg", status: "failed", error: "Invalid image" },
  ],
};

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
      lut_name: "test-lut",
      target_width_mm: 60,
      spacer_thick: 1.2,
      structure_mode: StructureMode.DOUBLE_SIDED,
      auto_bg: false,
      bg_tol: 40,
      color_mode: ColorMode.FOUR_COLOR,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      enable_cleanup: true,
      hue_weight: 0,
      chroma_gate: 0,
    });
  });

  // Requirement 5.1: batchLoading 在请求期间为 true
  it("submitBatch 开始时 batchLoading 为 true", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    useConverterStore.setState({ batchFiles: files });

    // Use a deferred promise to control when the API resolves
    let resolveApi!: (value: BatchResponse) => void;
    const apiPromise = new Promise<BatchResponse>((resolve) => {
      resolveApi = resolve;
    });
    mockedConvertBatch.mockReturnValueOnce(apiPromise);

    const submitPromise = useConverterStore.getState().submitBatch();

    // While the API is pending, batchLoading should be true
    expect(useConverterStore.getState().batchLoading).toBe(true);

    resolveApi(mockBatchResponse);
    await submitPromise;

    // After completion, batchLoading should be false
    expect(useConverterStore.getState().batchLoading).toBe(false);
  });

  // Requirement 5.3: batchResult 在请求完成后正确存储
  it("submitBatch 成功后 batchResult 存储 API 响应", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    useConverterStore.setState({ batchFiles: files });
    mockedConvertBatch.mockResolvedValueOnce(mockBatchResponse);

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.batchResult).toEqual(mockBatchResponse);
    expect(state.batchLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  // Error handling: API 错误时 error 状态设置
  it("submitBatch API 错误时设置 error 并将 batchLoading 恢复为 false", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    useConverterStore.setState({ batchFiles: files });
    mockedConvertBatch.mockRejectedValueOnce(new Error("Network error"));

    await useConverterStore.getState().submitBatch();

    const state = useConverterStore.getState();
    expect(state.error).toBe("Network error");
    expect(state.batchLoading).toBe(false);
    expect(state.batchResult).toBeNull();
  });

  // Requirement 6.4: 重新发起批量生成时清空之前的 batchResult
  it("submitBatch 开始时清空之前的 batchResult", async () => {
    const files = [new File(["a"], "img.png", { type: "image/png" })];
    const previousResult: BatchResponse = {
      status: "ok",
      message: "Previous",
      download_url: "/old.zip",
      results: [{ filename: "old.png", status: "success" }],
    };
    useConverterStore.setState({
      batchFiles: files,
      batchResult: previousResult,
      error: "old error",
    });

    let resolveApi!: (value: BatchResponse) => void;
    const apiPromise = new Promise<BatchResponse>((resolve) => {
      resolveApi = resolve;
    });
    mockedConvertBatch.mockReturnValueOnce(apiPromise);

    const submitPromise = useConverterStore.getState().submitBatch();

    // Immediately after calling submitBatch, previous result should be cleared
    expect(useConverterStore.getState().batchResult).toBeNull();
    expect(useConverterStore.getState().error).toBeNull();

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
