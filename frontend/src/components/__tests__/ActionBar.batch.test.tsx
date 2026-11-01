import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useConverterStore } from "../../stores/converter";
import { buildLayerImagesSourceKey } from "../../stores/converter/store";
import * as recipeImportFlow from "../../recipe/importFlow";
import ActionBar from "../sections/ActionBar";
import { translations } from "../../i18n/translations";
import { useSettingsStore } from "../../stores/settingsStore";

let capturedSlicerSelectorProps: Record<string, unknown> | null = null;

// Mock child components with complex dependencies
vi.mock("../sections/BedSizeSelector", () => ({
  default: () => <div data-testid="bed-size-selector" />,
}));

vi.mock("../sections/SlicerSelector", () => ({
  default: (props: Record<string, unknown>) => {
    capturedSlicerSelectorProps = props;
    return <div data-testid="slicer-selector" />;
  },
}));

vi.mock("../ui/CanvasPreviewSurface", () => ({
  default: () => <div data-testid="canvas-preview-surface-mock" />,
}));

vi.mock("../../recipe/importFlow", () => ({
  exportShareCard: vi.fn(),
  exportSidecar: vi.fn(),
  MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR:
    "Model surface recipes are not supported",
}));

function makeFile(name: string, type = "image/png"): File {
  return new File(["dummy"], name, { type });
}

describe("ActionBar — auto batch mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedSlicerSelectorProps = null;
    useSettingsStore.setState({ autoReplaceGradientBanding: false });
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      batchLoading: false,
      batchResult: null,
      imageFile: null,
      modelSurfaceEnabled: false,
      source_version: "legacy",
      lut_name: "",
      nativeBrandGroups: [],
      nativeBrandGroupsLoading: false,
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
      isLoading: false,
      isGenerating: false,
      replacePreviewLoading: false,
      contentCommitStatus: "committed",
      error: null,
      previewImageUrl: null,
      previewBaseImageUrl: null,
      sessionId: null,
      layerImages: [],
      layerImagesLoading: false,
      layerImagesSourceKey: null,
      fetchLayerImages: vi.fn(),
      modelUrl: null,
      threemfDiskPath: null,
      downloadUrl: null,
      generateWarnings: [],
    });
    vi.mocked(recipeImportFlow.exportShareCard).mockResolvedValue('canceled');
    vi.mocked(recipeImportFlow.exportSidecar).mockResolvedValue('canceled');
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // --- SingleMode (batchFiles empty → batchMode false) ---

  it("exposes the automatic gradient setting next to preview for material workflows", () => {
    useConverterStore.setState({ source_version: "material" });
    useSettingsStore.setState({ autoReplaceGradientBanding: true });
    render(<ActionBar />);
    const toggle = screen.getByRole("switch", { name: translations["settings.auto_replace_gradient_heading"].zh });
    expect(toggle).toBeChecked();
    expect(screen.getByText(translations.action_auto_gradient_hint.zh)).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(useSettingsStore.getState().autoReplaceGradientBanding).toBe(false);
    expect(toggle).not.toBeChecked();
  });

  it("blocks output and layer thumbnails while preview postprocessing is running", () => {
    useConverterStore.setState({
      source_version: "material", selectedMaterialDirNames: ["test/white"],
      imageFile: makeFile("gradient.png"), sessionId: "processing",
      previewImageUrl: "/api/files/intermediate.png", isLoading: true,
    });
    useSettingsStore.setState({ autoReplaceGradientBanding: true });
    render(<ActionBar />);
    expect(capturedSlicerSelectorProps?.canSubmit).toBe(false);
    expect(useConverterStore.getState().fetchLayerImages).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: translations.recipe_export_btn.zh })).toBeDisabled();
    expect(screen.getByRole("button", { name: translations.recipe_export_sidecar_btn.zh })).toBeDisabled();
  });

  it.each(['recipe_export_btn', 'recipe_export_sidecar_btn'])("shows actual save outcomes for %s", async (buttonKey) => {
    useConverterStore.setState({ imageFile: makeFile('art.png'), sessionId: 'save-test', previewImageUrl: '/preview.png' });
    const save = vi.mocked(buttonKey === 'recipe_export_btn' ? recipeImportFlow.exportShareCard : recipeImportFlow.exportSidecar);
    render(<ActionBar />);
    const click = () => fireEvent.click(screen.getByText(translations[buttonKey].zh));
    click();
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText(translations[buttonKey].zh).closest("button")).toBeEnabled());
    expect(screen.queryByText(translations.file_save_saved.zh)).not.toBeInTheDocument();
    save.mockResolvedValue('saved');
    await act(async () => { click(); });
    expect(screen.getByText(translations.file_save_saved.zh)).toBeInTheDocument();
    save.mockRejectedValue(new Error('file_save_failed'));
    await act(async () => { click(); });
    expect(screen.getByText(new RegExp(translations.file_save_failed.zh))).toBeInTheDocument();
    expect(screen.queryByText(translations.file_save_saved.zh)).not.toBeInTheDocument();
  });

  it("shows preview and output actions without a standalone generate button in SingleMode", () => {
    useConverterStore.setState({ batchMode: false, batchFiles: [] });
    render(<ActionBar />);
    expect(screen.getByText("预览")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成" })).not.toBeInTheDocument();
    expect(screen.getByTestId("slicer-selector")).toBeInTheDocument();
    expect(screen.queryByText("批量生成")).not.toBeInTheDocument();
  });

  it("shows a mandatory manual-adjustment warning for a generated wipe tower conflict", () => {
    useConverterStore.setState({
      downloadUrl: "/api/files/model.3mf",
      generateWarnings: ["wipe_tower_manual_adjustment_required"],
    });

    render(<ActionBar />);

    expect(screen.getByText("打印前请手动检查摆放")).toBeInTheDocument();
    expect(
      screen.getByText(/模型尺寸、原生工艺和擦料塔均已保留/),
    ).toBeInTheDocument();
  });

  // --- BatchMode (batchFiles has items → batchMode true) ---

  it("shows batch generate button and hides preview/generate when batchFiles has items", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png"), makeFile("b.png")],
      lut_name: "test_lut",
    });
    render(<ActionBar />);
    expect(screen.getByText("批量生成")).toBeInTheDocument();
    expect(screen.queryByText("预览")).not.toBeInTheDocument();
    expect(screen.queryByText("生成")).not.toBeInTheDocument();
  });

  // --- Auto-maintained batchMode via handleFilesSelect ---

  it("auto-enters BatchMode via handleFilesSelect with multiple files", () => {
    // Start from empty state
    useConverterStore.setState({ batchMode: false, batchFiles: [], imageFile: null });

    // Use handleFilesSelect to add multiple files (auto-sets batchMode)
    useConverterStore.getState().handleFilesSelect([makeFile("a.png"), makeFile("b.png")]);

    const state = useConverterStore.getState();
    expect(state.batchMode).toBe(true);
    expect(state.batchFiles).toHaveLength(2);

    render(<ActionBar />);
    expect(screen.getByText("批量生成")).toBeInTheDocument();
    expect(screen.queryByText("预览")).not.toBeInTheDocument();
  });

  // --- Disabled conditions ---

  it("disables batch generate button when batchFiles is empty", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [],
      lut_name: "test_lut",
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).toBeDisabled();
  });

  it("disables batch generate button when lut_name is empty", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "",
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).toBeDisabled();
  });

  it("disables batch generate button when batchLoading is true", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchLoading: true,
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).toBeDisabled();
  });

  it("shows a source-only hint after an image is uploaded but legacy LUT is still missing", () => {
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: makeFile("uploaded.png"),
      source_version: "legacy",
      lut_name: "",
    });

    render(<ActionBar />);

    expect(screen.getByText("请先选择 LUT")).toBeInTheDocument();
    expect(screen.queryByText("请先上传图片并选择 LUT")).not.toBeInTheDocument();
    expect(screen.getByText("预览").closest("button")).toBeDisabled();
  });

  // --- Enabled condition ---

  it("enables batch generate button when files exist and lut_name is set", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchLoading: false,
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).not.toBeDisabled();
  });

  it("disables the output action and explains why while large format and model texture are both on", () => {
    useConverterStore.setState({
      imageFile: makeFile("art.png"),
      lut_name: "test_lut",
      sessionId: "conflict-session",
      largeFormatEnabled: true,
      modelSurfaceEnabled: false,
    });
    const { rerender } = render(<ActionBar />);
    expect(capturedSlicerSelectorProps?.canSubmit).toBe(true);
    expect(
      screen.queryByText(translations.large_format_model_surface_conflict.zh),
    ).not.toBeInTheDocument();

    act(() => {
      useConverterStore.setState({ modelSurfaceEnabled: true });
    });
    rerender(<ActionBar />);

    expect(capturedSlicerSelectorProps?.canSubmit).toBe(false);
    expect(
      screen.getByText(translations.large_format_model_surface_conflict.zh),
    ).toBeInTheDocument();
  });

  it("enables batch generate button for material archive source without a legacy LUT", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      source_version: "material",
      lut_name: "",
      selectedMaterialDirNames: ["brand/red", "brand/white"],
      materialLayerCount: 7,
      materialLayerHeightMm: 0.06,
      batchLoading: false,
    });

    render(<ActionBar />);

    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).not.toBeDisabled();
  });

  it("enables batch generate button for native reverse LUT source without a legacy LUT", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      source_version: "native",
      lut_name: "",
      selectedNativeBrandKey: "bambulab_pla",
      selectedNativeDbNames: ["DB-A", "DB-B"],
      color_layers: 5,
      layer_height_mm: 0.08,
      nativeBrandGroups: [
        {
          brand_key: "bambulab_pla",
          material_type: "PLA",
          vendor: "Bambu Lab",
          display_name: "Bambu PLA",
          db_options: [
            { name: "DB-A", path: "/DB-A.json", color_mode: "8-Color Max" },
            { name: "DB-B", path: "/DB-B.json", color_mode: "8-Color Max" },
          ],
          default_db_names: ["DB-A", "DB-B"],
          supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
        },
      ],
      batchLoading: false,
    } as never);

    render(<ActionBar />);

    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).not.toBeDisabled();
  });

  it("shows source-specific batch hints when material or native source is incomplete", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      source_version: "material",
      lut_name: "",
      selectedMaterialDirNames: [],
    });
    const { rerender } = render(<ActionBar />);
    expect(screen.getByText("请先添加图片并选择耗材")).toBeInTheDocument();

    useConverterStore.setState({
      source_version: "native",
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
      nativeBrandGroups: [],
    });
    rerender(<ActionBar />);
    expect(screen.getByText("请先添加图片并选择品牌和数据库")).toBeInTheDocument();
  });

  it("generates the single 3MF through the output action without a standalone generate button", async () => {
    const submitFullPipeline = vi.fn(async () => {
      useConverterStore.setState({ downloadUrl: "/api/files/single-model" });
      return "/api/files/single-model";
    });
    useConverterStore.setState({
      imageFile: makeFile("art.png"),
      lut_name: "test_lut",
      submitFullPipeline,
    });

    render(<ActionBar />);

    expect(capturedSlicerSelectorProps?.canSubmit).toBe(true);
    const onAutoGenerate = capturedSlicerSelectorProps?.onAutoGenerate as () => Promise<string | null>;
    await expect(onAutoGenerate()).resolves.toBe("/api/files/single-model");
    expect(submitFullPipeline).toHaveBeenCalledOnce();
  });

  it("reuses the slicer-open action for batch merged 3MF generation", async () => {
    const submitBatch = vi.fn(async () => {
      useConverterStore.setState({ downloadUrl: "/api/files/batch-merged" });
    });
    const submitFullPipeline = vi.fn();
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png"), makeFile("b.png")],
      lut_name: "test_lut",
      batchLoading: false,
      largeFormatEnabled: true,
      submitBatch,
      submitFullPipeline,
    });

    render(<ActionBar />);

    expect(capturedSlicerSelectorProps?.canSubmit).toBe(true);
    expect(capturedSlicerSelectorProps?.largeFormat).toBe(false);
    const onAutoGenerate = capturedSlicerSelectorProps?.onAutoGenerate as
      | (() => Promise<string | null>)
      | undefined;
    expect(onAutoGenerate).toBeTypeOf("function");

    await expect(onAutoGenerate!()).resolves.toBe("/api/files/batch-merged");
    expect(submitBatch).toHaveBeenCalledOnce();
    expect(submitFullPipeline).not.toHaveBeenCalled();
  });

  it("enables preview and automatic output before a native bundle session exists even when lut_name is empty", () => {
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: makeFile("native.png"),
      source_version: "native",
      lut_name: "",
      selectedNativeBrandKey: "bambulab_pla",
      selectedNativeDbNames: ["DB-A", "DB-B"],
      nativeBrandGroups: [
        {
          brand_key: "bambulab_pla",
          material_type: "PLA",
          vendor: "Bambu Lab",
          display_name: "Bambu PLA",
          db_options: [
            { name: "DB-A", path: "/DB-A.json", color_mode: "8-Color Max" },
            { name: "DB-B", path: "/DB-B.json", color_mode: "8-Color Max" },
          ],
          default_db_names: ["DB-A", "DB-B"],
          supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
        },
      ],
    } as never);

    render(<ActionBar />);

    const previewBtn = screen.getByText("预览").closest("button")!;
    expect(previewBtn).not.toBeDisabled();
    expect(screen.queryByRole("button", { name: "生成" })).not.toBeInTheDocument();
    expect(capturedSlicerSelectorProps?.canSubmit).toBe(true);
  });

  // --- BatchResultSummary ---

  it("shows BatchResultSummary when batchResult is not null", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchResult: {
        status: "ok",
        message: "done",
        download_url: "/output/batch.3mf",
        preview_3d_url: null,
        preview_items: [],
        results: [{ filename: "a.png", status: "success" }],
        warnings: [],
      },
    });
    const { container } = render(<ActionBar />);
    // BatchResultSummary renders — text is split across child elements
    const text = container.textContent ?? "";
    expect(text).toContain("成功");
    expect(text).toContain("总计");
    expect(screen.getByLabelText("下载批量 3MF")).toBeInTheDocument();
  });

  it("does not show BatchResultSummary when batchResult is null", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchResult: null,
    });
    render(<ActionBar />);
    expect(screen.queryByText(/成功.*总计/)).not.toBeInTheDocument();
  });

  it.each([null, "/api/files/puzzle-overlay.png"])(
    "keeps preview and export actions without an embedded 2D window (puzzle overlay: %s)",
    (puzzleOverlayUrl) => {
      useConverterStore.setState({
        imageFile: makeFile("preview.png"),
        lut_name: "test_lut",
        sessionId: "session-1",
        previewImageUrl: "/api/files/preview.png",
        previewBaseImageUrl: "/api/files/preview-base.png",
        puzzleOverlayUrl,
      });

      render(<ActionBar />);

      expect(screen.queryByTestId("canvas-preview-surface-mock")).not.toBeInTheDocument();
      expect(screen.queryByTestId("action-hover-inspector")).not.toBeInTheDocument();
      expect(screen.getByText(translations.action_preview.zh).closest("button")).toBeEnabled();
      expect(screen.queryByRole("button", { name: translations.action_view_layers.zh })).not.toBeInTheDocument();
      expect(screen.getByText(translations.recipe_export_btn.zh)).toBeInTheDocument();
      expect(screen.getByText(translations.recipe_export_sidecar_btn.zh)).toBeInTheDocument();
      expect(screen.getByTestId("bed-size-selector")).toBeInTheDocument();
      expect(screen.getByTestId("slicer-selector")).toBeInTheDocument();
    },
  );

  it("shows readable share-card export failures instead of raw HTTP status text", async () => {
    vi.mocked(recipeImportFlow.exportShareCard).mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    useConverterStore.setState({
      batchMode: false,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: "session-1",
      previewImageUrl: "/api/files/preview.png",
      previewBaseImageUrl: "/api/files/preview.png",
      layerImages: [],
      layerImagesLoading: false,
    });

    render(<ActionBar />);

    fireEvent.click(screen.getByRole("button", { name: "导出分享卡" }));

    await waitFor(() => {
      expect(screen.getByText(/导出失败：服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Request failed with status code 500/)).not.toBeInTheDocument();
  });

  it("disables incomplete recipe exports while model texture is active", () => {
    useConverterStore.setState({
      batchMode: false,
      modelSurfaceEnabled: true,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: "session-1",
      previewImageUrl: "/api/files/preview.png",
      previewBaseImageUrl: "/api/files/preview.png",
      layerImages: [],
      layerImagesLoading: false,
    });

    render(<ActionBar />);

    expect(screen.getByRole("button", { name: "导出分享卡" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存项目" })).toBeDisabled();
    expect(
      screen.getByText("模型贴图暂不支持配方导出，因为配方无法包含上传模型和选面。"),
    ).toBeInTheDocument();
    expect(recipeImportFlow.exportShareCard).not.toHaveBeenCalled();
    expect(recipeImportFlow.exportSidecar).not.toHaveBeenCalled();
  });

  it("shows a readable share-card export failure when PNG encoding fails", async () => {
    vi.mocked(recipeImportFlow.exportShareCard).mockRejectedValueOnce(
      new Error("Failed to create cover PNG blob"),
    );

    useConverterStore.setState({
      batchMode: false,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: "session-1",
      previewImageUrl: "/api/files/preview.png",
      previewBaseImageUrl: "/api/files/preview.png",
      layerImages: [],
      layerImagesLoading: false,
    });

    render(<ActionBar />);

    fireEvent.click(screen.getByRole("button", { name: "导出分享卡" }));

    await waitFor(() => {
      expect(screen.getByText(/导出失败：导出没有完成，请稍后重试。/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Failed to create cover PNG blob/)).not.toBeInTheDocument();
  });

  it("shows a readable share-card export failure when the preview cover image is unavailable", async () => {
    vi.mocked(recipeImportFlow.exportShareCard).mockRejectedValueOnce(
      new Error("Failed to load preview image for cover"),
    );

    useConverterStore.setState({
      batchMode: false,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: "session-1",
      previewImageUrl: "/api/files/preview.png",
      previewBaseImageUrl: "/api/files/preview.png",
      layerImages: [],
      layerImagesLoading: false,
    });

    render(<ActionBar />);

    fireEvent.click(screen.getByRole("button", { name: "导出分享卡" }));

    await waitFor(() => {
      expect(
        screen.getByText(/导出失败：预览图已失效，请重新生成预览后再导出。/),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByText(/Failed to load preview image for cover/),
    ).not.toBeInTheDocument();
  });

  it("shows a readable sidecar export failure when the preview cover image is unavailable", async () => {
    vi.mocked(recipeImportFlow.exportSidecar).mockRejectedValueOnce(
      new Error("Failed to load preview image for cover"),
    );

    useConverterStore.setState({
      batchMode: false,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: "session-1",
      previewImageUrl: "/api/files/preview.png",
      previewBaseImageUrl: "/api/files/preview.png",
      layerImages: [],
      layerImagesLoading: false,
    });

    render(<ActionBar />);

    fireEvent.click(screen.getByRole("button", { name: "保存项目" }));

    await waitFor(() => {
      expect(
        screen.getByText(/导出失败：预览图已失效，请重新生成预览后再导出。/),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByText(/Failed to load preview image for cover/),
    ).not.toBeInTheDocument();
  });

  it("refetches layer images when the 2D preview changes within the same session", async () => {
    const fetchLayerImages = vi.fn();

    useConverterStore.setState({
      batchMode: false,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: "session-1",
      previewImageUrl: "/api/files/preview-a.png",
      previewBaseImageUrl: "/api/files/preview-a.png",
      layerImages: [{ layer_index: 0, name: "Layer 1", url: "/api/files/layer-a" }],
      layerImagesLoading: false,
      layerImagesOpen: true,
      fetchLayerImages,
    });
    useConverterStore.setState({
      layerImagesSourceKey: buildLayerImagesSourceKey(useConverterStore.getState()),
    });

    render(<ActionBar />);

    expect(fetchLayerImages).not.toHaveBeenCalled();

    act(() => {
      useConverterStore.setState({
        previewImageUrl: "/api/files/preview-b.png",
        previewBaseImageUrl: "/api/files/preview-b.png",
      });
    });

    await waitFor(() => {
      expect(fetchLayerImages).toHaveBeenCalledWith(
        buildLayerImagesSourceKey(useConverterStore.getState()),
      );
    });
  });

  it("does not refetch layer images for highlight-only preview churn when the base preview is unchanged", async () => {
    const fetchLayerImages = vi.fn();

    useConverterStore.setState({
      batchMode: false,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: "session-1",
      previewImageUrl: "/api/files/highlight-a.png",
      previewBaseImageUrl: "/api/files/preview-base.png",
      layerImages: [{ layer_index: 0, name: "Layer 1", url: "/api/files/layer-a" }],
      layerImagesLoading: false,
      layerImagesOpen: true,
      fetchLayerImages,
    });
    useConverterStore.setState({
      layerImagesSourceKey: buildLayerImagesSourceKey(useConverterStore.getState()),
    });

    render(<ActionBar />);

    act(() => {
      useConverterStore.setState({
        previewImageUrl: "/api/files/highlight-b.png",
      });
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(fetchLayerImages).not.toHaveBeenCalled();
  });
});
