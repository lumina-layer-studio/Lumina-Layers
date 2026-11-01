import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GradientGroupsPanel from "../components/sections/GradientGroupsPanel";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import type { GradientGroupItem, SelectionDocumentResponse, SelectionMutationRequest } from "../api/types";

// Highlight dialogs and shared selection mutations use separate API paths.
const colorHighlightMock = vi.hoisted(() => vi.fn());
const mutateEditorSelectionMock = vi.hoisted(() => vi.fn());
const getEditorSelectionMock = vi.hoisted(() => vi.fn());
const replaceColorMock = vi.hoisted(() => vi.fn());
const regionReplaceMock = vi.hoisted(() => vi.fn());
const regionReplaceBatchMock = vi.hoisted(() => vi.fn());
const regionRequantizeMock = vi.hoisted(() => vi.fn());
const fetchGradientGroupsMock = vi.hoisted(() => vi.fn());
const editorCommitStatusMock = vi.hoisted(() =>
  vi.fn().mockResolvedValue({
    status: "failed",
    operation_id: "test-operation",
    editor_content_revision: 0,
    visible_content_revision: 0,
  }),
);

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    colorHighlight: colorHighlightMock,
    mutateEditorSelection: mutateEditorSelectionMock,
    getEditorSelection: getEditorSelectionMock,
    replaceColor: replaceColorMock,
    replaceColorsBatch: vi.fn().mockResolvedValue({
      status: "ok",
      message: "ok",
      preview_url: "/api/files/flattened.png",
      replacement_count: 1,
    }),
    regionReplace: regionReplaceMock,
    regionReplaceBatch: regionReplaceBatchMock,
    regionRequantize: regionRequantizeMock,
    fetchGradientGroups: fetchGradientGroupsMock,
    getEditorCommitStatus: editorCommitStatusMock,
  };
});

function _makeGroup(
  overrides: Partial<GradientGroupItem> = {},
): GradientGroupItem {
  return {
    group_index: 1,
    total_pixel_count: 500_000,
    material_colour_count: 2,
    material_colours: [
      { hex: "#D2AEB4", rgb: [210, 174, 180], pixel_count: 300_000 },
      { hex: "#CB9994", rgb: [203, 153, 148], pixel_count: 200_000 },
    ],
    representative_hex: "#D2AEB4",
    representative_rgb: [210, 174, 180],
    boundary_pair_count: 1,
    regions: [
      {
        region_index: 1,
        pixel_count: 350_000,
        bbox: [0, 0, 100, 100],
        centroid: [50, 50],
        material_breakdown: [
          { hex: "#D2AEB4", rgb: [210, 174, 180], pixel_count: 210_000 },
          { hex: "#CB9994", rgb: [203, 153, 148], pixel_count: 140_000 },
        ],
      },
      {
        region_index: 2,
        pixel_count: 150_000,
        bbox: [120, 50, 200, 150],
        centroid: [160, 100],
        material_breakdown: [
          { hex: "#D2AEB4", rgb: [210, 174, 180], pixel_count: 90_000 },
          { hex: "#CB9994", rgb: [203, 153, 148], pixel_count: 60_000 },
        ],
      },
    ],
    ...overrides,
  };
}

function _resetStores(
  overrides: Partial<ReturnType<typeof useConverterStore.getState>> = {},
) {
  useConverterStore.setState({
    source_version: "material",
    sessionId: "sess-test",
    gradientGroups: [_makeGroup()],
    gradientGroupsLoading: false,
    gradientGroupsError: null,
    gradientGroupsSessionId: "sess-test",
    gradientSelection: null,
    selectedGradientRegions: [],
    selectedColor: null,
    selectionDocument: selectionDocument(++selectionRevision * 10, []),
    selectionMode: "current",
    selectedColors: new Set<string>(),
    selectedRegions: [],
    regionData: null,
    replacePreviewLoading: false,
    colorRemapMap: {},
    remapHistory: [],
    previewImageUrl: "/api/files/preview.png",
    previewBaseImageUrl: "/api/files/preview.png",
    historyCanUndo: false,
    historyCanRedo: false,
    historyBusy: false,
    contentCommitStatus: "idle",
    contentCommitOperationId: null,
    ...overrides,
  });
  useSettingsStore.setState({ autoReplaceGradientBanding: false });
}

let selectionRevision = 0;

function selectionDocument(revision: number, colors: string[]): SelectionDocumentResponse {
  const components = colors.map((color, index) => ({
    label: index + 1,
    region_id: `region-${color}`,
    color_hex: `#${color}`,
    pixel_count: 10,
    bbox: [index * 10, 0, 10, 1],
    anchor: [index * 10, 0],
  }));
  return {
    selection_revision: revision,
    content_revision: 1,
    editor_content_revision: 1,
    selected_pixel_count: colors.length * 10,
    selected_component_count: colors.length,
    selected_color_hexes: colors.map((color) => `#${color}`),
    region_ids: components.map((component) => component.region_id),
    components,
    contours: [],
    can_undo: colors.length > 0,
    can_redo: false,
  };
}

describe("GradientGroupsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetStores();
    colorHighlightMock.mockResolvedValue({
      preview_url: "/api/files/highlighted.png",
    });
    mutateEditorSelectionMock.mockImplementation(async (request: SelectionMutationRequest) =>
      selectionDocument(request.base_selection_revision + 1, request.color_hexes ?? ["d2aeb4", "cb9994"]),
    );
    getEditorSelectionMock.mockImplementation(async () => useConverterStore.getState().selectionDocument);
    fetchGradientGroupsMock.mockResolvedValue({
      status: "ok",
      groups: [_makeGroup()],
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when not in material-archive mode", () => {
    _resetStores({ source_version: "legacy" });
    const { container } = render(<GradientGroupsPanel />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when gradientGroups is null (not fetched yet)", () => {
    _resetStores({ gradientGroups: null });
    const { container } = render(<GradientGroupsPanel />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when gradientGroups is an empty list (no banding)", () => {
    _resetStores({ gradientGroups: [] });
    const { container } = render(<GradientGroupsPanel />);
    expect(container.firstChild).toBeNull();
  });

  it("renders loading state while fetching", () => {
    _resetStores({ gradientGroupsLoading: true, gradientGroups: null });
    render(<GradientGroupsPanel />);
    expect(screen.getByText(/loading gradient groups|正在读取/i)).toBeInTheDocument();
  });

  it("renders error state when the fetch failed", () => {
    _resetStores({
      gradientGroupsError: "boom",
      gradientGroups: null,
    });
    render(<GradientGroupsPanel />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("boom");
  });

  it("normalizes HTTP status errors before storing gradient group failures", async () => {
    regionReplaceBatchMock.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );
    render(<GradientGroupsPanel />);
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    fireEvent.click(screen.getByTestId("merge-check-1-1"));
    fireEvent.click(screen.getByTestId("merge-check-1-2"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("merge-flatten-1"));
    });

    const error = useConverterStore.getState().error;
    expect(error).toBeTruthy();
    expect(error).not.toMatch(/Request failed with status code 500/i);
    expect(error).not.toMatch(/status code\s+500/i);
  });

  it("normalizes HTTP status errors before showing gradient group load failures", async () => {
    _resetStores({ gradientGroups: null });
    fetchGradientGroupsMock.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    await useConverterStore.getState().fetchGradientGroups("sess-test");

    const error = useConverterStore.getState().gradientGroupsError;
    expect(error).toBeTruthy();
    expect(error).not.toMatch(/Request failed with status code 500/i);
    expect(error).not.toMatch(/status code\s+500/i);
  });

  it("renders a group row with material count and select button", () => {
    render(<GradientGroupsPanel />);
    expect(screen.getByTestId("gradient-groups-panel")).toBeInTheDocument();
    expect(screen.getByText(/2 (colors|种颜色)/i)).toBeInTheDocument();
    // Both select-group and flatten-all buttons are present.
    expect(
      screen.getByRole("button", { name: /select all|选中整组/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /flatten all|一键去除/i }),
    ).toBeInTheDocument();
  });

  it("select-group commits the shared selection and its history", async () => {
    render(<GradientGroupsPanel />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /select all|选中整组/i }));
    });

    const state = useConverterStore.getState();
    expect(state.selectionMode).toBe("select-all");
    expect(Array.from(state.selectedColors).sort()).toEqual(
      ["cb9994", "d2aeb4"].sort(),
    );
    expect(state.selectedRegions.map((region) => region.regionId)).toEqual(["region-d2aeb4", "region-cb9994"]);
    expect(state.selectedColor).toBe("cb9994");
    expect(state.historyCanUndo).toBe(true);
    // Source stamp identifies which panel row initiated the multi-select.
    // 记录点击来源，供按钮排它性高亮判断。
    expect(state.gradientSelection).toEqual({
      kind: "group",
      groupIndex: 1,
    });
    expect(mutateEditorSelectionMock).toHaveBeenCalledWith(expect.objectContaining({
      session_id: "sess-test",
      operation: "colors-set",
      color_hexes: expect.arrayContaining(["cb9994", "d2aeb4"]),
    }));
    expect(colorHighlightMock).not.toHaveBeenCalled();
  });

  it("keeps local group selection available before a session exists", () => {
    _resetStores({ sessionId: null, selectionDocument: null });
    render(<GradientGroupsPanel />);
    fireEvent.click(screen.getByRole("button", { name: /select all|选中整组/i }));

    expect(useConverterStore.getState().selectedColors).toEqual(new Set(["d2aeb4", "cb9994"]));
    expect(useConverterStore.getState().gradientSelection).toEqual({ kind: "group", groupIndex: 1 });
    expect(mutateEditorSelectionMock).not.toHaveBeenCalled();
    expect(colorHighlightMock).not.toHaveBeenCalled();
  });

  it("shows a friendly error when the highlight response has no preview URL", async () => {
    colorHighlightMock.mockResolvedValueOnce({ preview_url: "" });
    render(<GradientGroupsPanel />);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /view highlight|查看高亮图/i }),
      );
    });

    expect(screen.getByText(/failed to generate highlight|生成高亮图失败/i))
      .toBeInTheDocument();
    expect(screen.queryByText(/empty preview_url/i)).not.toBeInTheDocument();
  });

  it("normalizes HTTP status errors in the highlight dialog", async () => {
    colorHighlightMock.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );
    render(<GradientGroupsPanel />);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /view highlight|查看高亮图/i }),
      );
    });

    const error = screen.getByText(/failed to generate highlight|生成高亮图失败/i);
    expect(error).toBeInTheDocument();
    expect(error.textContent).not.toMatch(/Request failed with status code 500/i);
    expect(error.textContent).not.toMatch(/status code\s+500/i);
  });

  it("renders the highlight image when the response contains a preview URL", async () => {
    colorHighlightMock.mockResolvedValueOnce({
      preview_url: "/api/files/highlight-dialog.png",
    });
    render(<GradientGroupsPanel />);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /view highlight|查看高亮图/i }),
      );
    });

    const image = screen.getByRole("img", {
      name: /highlight preview|高亮预览/i,
    });
    expect(image).toHaveAttribute("src", "/api/files/highlight-dialog.png");
  });

  it("expands regions and commits an exact region selection with a region-scoped source", async () => {
    render(<GradientGroupsPanel />);
    // Expand regions for the only group on screen.
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    // Two "select region" buttons are now visible (one per region).
    const regionBtns = screen.getAllByRole("button", {
      name: /select region|选中区域/i,
    });
    expect(regionBtns).toHaveLength(2);
    await act(async () => { fireEvent.click(regionBtns[0]); });

    const state = useConverterStore.getState();
    expect(state.selectionMode).toBe("select-all");
    expect(Array.from(state.selectedColors).sort()).toEqual(
      ["cb9994", "d2aeb4"].sort(),
    );
    // Key disambiguator: even when the region breakdown happens to equal
    // the enclosing group's material set, the source must be "region".
    // 关键：就算 region.breakdown 与整组 hex 一致，source 也必须是 region。
    expect(state.gradientSelection).toEqual({
      kind: "region",
      groupIndex: 1,
      regionIndex: 1,
    });
    expect(mutateEditorSelectionMock).toHaveBeenCalledWith(expect.objectContaining({
      operation: "gradient-region-set",
      gradient_group_index: 1,
      gradient_region_index: 1,
    }));
    expect(state.selectionDocument?.selected_component_count).toBe(2);
    expect(state.historyCanUndo).toBe(true);
    expect(colorHighlightMock).not.toHaveBeenCalled();
  });

  it("flatten-all button invokes applyAutoGradientReplace", async () => {
    replaceColorMock.mockResolvedValue({
      preview_url: "/api/files/flattened.png",
      preview_3d_url: null,
    });
    render(<GradientGroupsPanel />);
    // Wrapped in ``act`` so the async store update (colorRemapMap + followup
    // submitReplacePreview) completes before the assertion, preventing the
    // "not wrapped in act" warning from React.
    // 用 act 包裹：等待异步 action 内部的状态更新落地再断言。
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /flatten all|一键去除/i }),
      );
    });

    const state = useConverterStore.getState();
    // colorRemapMap now carries the non-representative -> representative pair.
    expect(state.colorRemapMap).toMatchObject({ cb9994: "d2aeb4" });
  });

  it("shows that automatic merging is enabled without claiming an edit already completed", () => {
    useSettingsStore.setState({ autoReplaceGradientBanding: true });
    render(<GradientGroupsPanel />);
    expect(
      screen.getByText(/Automatic gradient merging is enabled|已开启自动合并渐变色/i),
    ).toBeInTheDocument();
  });

  it("highlights the group row only when gradientSelection identifies it as the origin", () => {
    // Pure selectedColors match is no longer enough — the store also needs
    // gradientSelection to point at this group. This prevents the old bug
    // where selecting a region whose breakdown equals the group's material
    // set would leave the group button highlighted.
    // 单纯 selectedColors 匹配不再能高亮整组按钮，必须 gradientSelection 也指向本组。
    _resetStores({
      selectionMode: "select-all",
      selectedColors: new Set(["d2aeb4", "cb9994"]),
      gradientSelection: { kind: "group", groupIndex: 1 },
    });
    render(<GradientGroupsPanel />);
    const btn = screen.getByRole("button", { name: /select all|选中整组/i });
    expect(btn).toHaveAttribute("aria-pressed", "true");
  });

  it("does NOT highlight the group button when gradientSelection points at a region", () => {
    // Regression for the reported bug: group A's material_colours were
    // {d2aeb4, cb9994} and the single region inside had the identical
    // breakdown, so the legacy "every hex in selectedColors" rule lit up
    // *both* the group button and the region button at once.
    // 关键回归：即使 selectedColors 与整组 hex 完全一致，只要来源是 region，
    // 整组按钮必须保持灰色。
    _resetStores({
      selectionMode: "select-all",
      selectedColors: new Set(["d2aeb4", "cb9994"]),
      gradientSelection: {
        kind: "region",
        groupIndex: 1,
        regionIndex: 1,
      },
    });
    render(<GradientGroupsPanel />);
    const groupBtn = screen.getByRole("button", {
      name: /select all|选中整组/i,
    });
    expect(groupBtn).toHaveAttribute("aria-pressed", "false");
  });

  it("switching from a group to one of its regions moves the highlight", async () => {
    // End-to-end flow through the real store: first click the group's
    // select button (gradientSelection becomes {group, 1}), then expand
    // and click region 1's select button (gradientSelection should flip
    // to {region, 1, 1}). The group button must dim and the region
    // button must light up.
    // 全链路：先选整组 → 再选组内区域 1 → 整组按钮变灰、区域按钮变蓝。
    render(<GradientGroupsPanel />);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /select all|选中整组/i }),
      );
    });
    // At this point the group button is blue.
    const groupBtn1 = screen.getByRole("button", {
      name: /select all|选中整组/i,
    });
    expect(groupBtn1).toHaveAttribute("aria-pressed", "true");

    // Expand and click region 1's "select region" button.
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    const regionBtns = screen.getAllByRole("button", {
      name: /select region|选中区域/i,
    });
    await act(async () => {
      fireEvent.click(regionBtns[0]);
    });

    // Group button no longer blue; region button now blue.
    const groupBtn2 = screen.getByRole("button", {
      name: /select all|选中整组/i,
    });
    expect(groupBtn2).toHaveAttribute("aria-pressed", "false");
    expect(regionBtns[0]).toHaveAttribute("aria-pressed", "true");

    // Sanity: the store recorded the region-scoped source.
    const state = useConverterStore.getState();
    expect(state.gradientSelection).toEqual({
      kind: "region",
      groupIndex: 1,
      regionIndex: 1,
    });
  });

  it("per-group Flatten button calls regionReplace with group-only scope", async () => {
    regionReplaceMock.mockResolvedValue({
      preview_url: "/api/files/flattened.png",
      preview_glb_url: null,
      color_contours: null,
      message: "Region replaced",
    });
    render(<GradientGroupsPanel />);
    // Two Flatten-style buttons on screen: the panel-level "Flatten all
    // gradients" and the per-group "Flatten". Pick the per-group one by
    // its shorter label.
    // 面板上有两个去海带纹按钮，按文本长度取短的那一个。
    const flattenButtons = screen.getAllByRole("button", {
      name: /^flatten$|^去海带纹$/i,
    });
    expect(flattenButtons).toHaveLength(1);
    await act(async () => {
      fireEvent.click(flattenButtons[0]);
    });

    // Now uses spatially-scoped regionReplace instead of colorRemapMap.
    // 现在走空间受限的 regionReplace 而非全图 colorRemapMap。
    expect(regionReplaceMock).toHaveBeenCalledWith(
      "sess-test",
      "#d2aeb4",
      { gradientGroupIndex: 1 },
      undefined,
      expect.any(String),
    );
    const state = useConverterStore.getState();
    expect(state.colorRemapMap).toEqual({});
  });

  it("per-region Flatten button calls regionReplace with region scope", async () => {
    regionReplaceMock.mockResolvedValue({
      preview_url: "/api/files/region-flattened.png",
      preview_glb_url: null,
      color_contours: null,
      message: "Region replaced",
    });
    // Region breakdowns differ so we can verify region-scoped call.
    // 构造区域不同的 breakdown，验证 region 按钮只影响自己那部分。
    _resetStores({
      gradientGroups: [
        {
          group_index: 1,
          total_pixel_count: 500_000,
          material_colour_count: 3,
          material_colours: [
            { hex: "#AAAAAA", rgb: [170, 170, 170], pixel_count: 250_000 },
            { hex: "#BBBBBB", rgb: [187, 187, 187], pixel_count: 150_000 },
            { hex: "#CCCCCC", rgb: [204, 204, 204], pixel_count: 100_000 },
          ],
          representative_hex: "#AAAAAA",
          representative_rgb: [170, 170, 170],
          boundary_pair_count: 2,
          regions: [
            {
              region_index: 1,
              pixel_count: 300_000,
              bbox: [0, 0, 100, 100],
              centroid: [50, 50],
              material_breakdown: [
                { hex: "#AAAAAA", rgb: [170, 170, 170], pixel_count: 200_000 },
                { hex: "#BBBBBB", rgb: [187, 187, 187], pixel_count: 100_000 },
              ],
            },
            {
              region_index: 2,
              pixel_count: 200_000,
              bbox: [120, 50, 200, 150],
              centroid: [160, 100],
              material_breakdown: [
                { hex: "#AAAAAA", rgb: [170, 170, 170], pixel_count: 50_000 },
                { hex: "#CCCCCC", rgb: [204, 204, 204], pixel_count: 150_000 },
              ],
            },
          ],
        },
      ],
    });
    render(<GradientGroupsPanel />);
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    // After expanding, 2 per-region Flatten buttons show up alongside the
    // per-group Flatten — the per-region ones are inside the region list.
    const allFlatten = screen.getAllByRole("button", {
      name: /^flatten$|^去海带纹$/i,
    });
    // 1 per-group + 2 per-region = 3.
    expect(allFlatten).toHaveLength(3);
    await act(async () => {
      fireEvent.click(allFlatten[1]); // First region's Flatten button.
    });

    // Spatially-scoped: regionReplace called with region scope, not colorRemapMap.
    // 空间受限替换：走 regionReplace 而非 colorRemapMap。
    expect(regionReplaceMock).toHaveBeenCalledWith(
      "sess-test",
      "#aaaaaa",
      { gradientGroupIndex: 1, gradientRegionIndex: 1 },
      undefined,
      expect.any(String),
    );
    const state = useConverterStore.getState();
    expect(state.colorRemapMap).toEqual({});
  });

  it("serializes consecutive group selections and publishes the latest confirmed mask", async () => {
    const deferredA: { resolve: (v: SelectionDocumentResponse) => void } = {
      resolve: () => {},
    };
    const promiseA = new Promise<SelectionDocumentResponse>((res) => {
      deferredA.resolve = res;
    });
    mutateEditorSelectionMock.mockReturnValueOnce(promiseA);

    const groupA = _makeGroup({
      group_index: 1,
      material_colours: [
        { hex: "#AAAAAA", rgb: [170, 170, 170], pixel_count: 100 },
        { hex: "#A1A1A1", rgb: [161, 161, 161], pixel_count: 80 },
      ],
      regions: [],
    });
    const groupB = _makeGroup({
      group_index: 2,
      material_colours: [
        { hex: "#BBBBBB", rgb: [187, 187, 187], pixel_count: 100 },
        { hex: "#B1B1B1", rgb: [177, 177, 177], pixel_count: 80 },
      ],
      regions: [],
    });
    _resetStores({ gradientGroups: [groupA, groupB] });
    const baseRevision = useConverterStore.getState().selectionDocument!.selection_revision;

    const { selectGradientGroupColors } = useConverterStore.getState();
    act(() => {
      selectGradientGroupColors(["#AAAAAA", "#A1A1A1"], { kind: "group", groupIndex: 1 });
    });
    await waitFor(() => expect(mutateEditorSelectionMock).toHaveBeenCalledTimes(1));
    expect(useConverterStore.getState().selectedColors.size).toBe(0);

    act(() => {
      selectGradientGroupColors(["#BBBBBB", "#B1B1B1"], { kind: "group", groupIndex: 2 });
    });
    expect(mutateEditorSelectionMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      deferredA.resolve(selectionDocument(baseRevision + 1, ["aaaaaa", "a1a1a1"]));
    });
    await waitFor(() => expect(useConverterStore.getState().selectionDocument?.selection_revision)
      .toBe(baseRevision + 2));
    expect(useConverterStore.getState().selectedColors).toEqual(new Set(["bbbbbb", "b1b1b1"]));
    expect(useConverterStore.getState().gradientSelection).toEqual({ kind: "group", groupIndex: 2 });
    expect(mutateEditorSelectionMock).toHaveBeenNthCalledWith(2, expect.objectContaining({
      operation: "colors-set",
      base_selection_revision: baseRevision + 1,
      color_hexes: ["bbbbbb", "b1b1b1"],
    }));
    expect(colorHighlightMock).not.toHaveBeenCalled();
  });

  it("manual toggleColorInSelection clears the region-scoped gradientSelection", async () => {
    // Users who first click a region button and then tweak the multi-select
    // by clicking palette tiles end up with a selection that no longer
    // matches the region's exact colour list. The palette should recover
    // its normal selected-tile rendering in that case; the mechanism is
    // ``toggleColorInSelection`` dropping ``gradientSelection`` on any
    // manual edit so downstream consumers like ``PalettePanel`` stop
    // suppressing selection borders.
    // 用户手动在调色板上 toggle 色块时，gradientSelection 应被清除，
    // 让 PalettePanel 恢复常规选中态渲染。
    const { selectGradientGroupColors, toggleColorInSelection } =
      useConverterStore.getState();

    await act(async () => {
      selectGradientGroupColors(["#D2AEB4", "#CB9994"], {
        kind: "region",
        groupIndex: 1,
        regionIndex: 1,
      });
    });
    expect(useConverterStore.getState().gradientSelection).toEqual({
      kind: "region",
      groupIndex: 1,
      regionIndex: 1,
    });

    await act(async () => {
      toggleColorInSelection("AABBCC");
    });

    // Manual multi-select edit must erase the region-scoped stamp so the
    // palette no longer hides selection indicators.
    // 手动编辑多选必须清除区域来源标记，让调色板恢复正常选中态。
    expect(useConverterStore.getState().gradientSelection).toBeNull();
  });

  // -----------------------------------------------------------------
  // Multi-region merge feature (checkbox + "Merge flatten" button).
  // -----------------------------------------------------------------

  it("merge-flatten button is hidden until ≥2 regions of the group are checked", () => {
    render(<GradientGroupsPanel />);
    // Expand the group so the region checkboxes render.
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    // No checkboxes ticked yet → no merge button. 未勾选时按钮隐藏。
    expect(screen.queryByTestId("merge-flatten-1")).toBeNull();

    // Tick one checkbox → still hidden (single region would be a no-op).
    // 只勾 1 个仍然隐藏。
    fireEvent.click(screen.getByTestId("merge-check-1-1"));
    expect(screen.queryByTestId("merge-flatten-1")).toBeNull();

    // Tick the second → button appears with the count.
    // 勾上第 2 个时按钮出现，显示计数。
    fireEvent.click(screen.getByTestId("merge-check-1-2"));
    const mergeBtn = screen.getByTestId("merge-flatten-1");
    expect(mergeBtn).toBeInTheDocument();
    expect(mergeBtn.textContent).toMatch(/2/);
  });

  it("merge-flatten click fires regionReplaceBatch with a unified target for every ticked region", async () => {
    regionReplaceBatchMock.mockResolvedValue({
      preview_url: "/api/files/merged.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    render(<GradientGroupsPanel />);
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    fireEvent.click(screen.getByTestId("merge-check-1-1"));
    fireEvent.click(screen.getByTestId("merge-check-1-2"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("merge-flatten-1"));
    });

    expect(regionReplaceBatchMock).toHaveBeenCalledTimes(1);
    const [, items] = regionReplaceBatchMock.mock.calls[0];
    // Same replacementColor across all items — this is the whole point of
    // "merged flatten, one unified color". 所有 items 的 replacementColor
    // 必须一致，这就是 "合并到同一个色" 的含义。
    expect(new Set(items.map((i: { replacementColor: string }) => i.replacementColor)).size).toBe(1);
    expect(items.map((i: { gradientRegionIndex: number }) => i.gradientRegionIndex).sort()).toEqual([
      1, 2,
    ]);
  });

  // -----------------------------------------------------------------
  // Re-quantize button + dialog (per-region secondary quantization)
  // 二次量化按钮 + 弹窗：区域级二次量化（12-256 色预算）
  // -----------------------------------------------------------------

  it("external batch requantize button is disabled when nothing is checked and enabled once a region is ticked", () => {
    render(<GradientGroupsPanel />);
    // 0 checked → batch button is present (always discoverable) but
    // disabled with a tooltip explaining why it cannot fire.
    // 无勾选时批量按钮始终可见但 disabled，带 tooltip 提示原因。
    const batchBtn = screen.getByTestId(
      "gradient-groups-batch-requantize",
    ) as HTMLButtonElement;
    expect(batchBtn).toBeInTheDocument();
    expect(batchBtn.disabled).toBe(true);

    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    fireEvent.click(screen.getByTestId("merge-check-1-1"));
    const refreshedBtn = screen.getByTestId(
      "gradient-groups-batch-requantize",
    ) as HTMLButtonElement;
    expect(refreshedBtn.disabled).toBe(false);
  });

  it("per-region requantize button opens the dialog without requiring a checkbox tick", () => {
    // The single-region entry is always available on every region row so
    // the user can correct one banded region without assembling a batch
    // selection first. This is the core UX promise of this feature.
    // 单 region 按钮始终可用，不依赖勾选；用户可直接对某个 region 做二次量化。
    render(<GradientGroupsPanel />);
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    const btn = screen.getByTestId("requantize-region-1-1");
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(screen.getByTestId("requantize-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("requantize-dialog-submit")).toBeInTheDocument();
  });

  it("per-region requantize submits exactly one target and preserves the checkbox selection", async () => {
    regionRequantizeMock.mockResolvedValue({
      preview_url: "/api/files/requantized.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    render(<GradientGroupsPanel />);
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    // Pre-seed a batch-style multi-selection BEFORE pressing the per-region
    // button. The per-region path must not wipe this selection — that is
    // the whole reason we disambiguate per-region from batch.
    // 预先勾选两个 region，用于验证 per-region 量化不会清掉批量勾选。
    fireEvent.click(screen.getByTestId("merge-check-1-1"));
    fireEvent.click(screen.getByTestId("merge-check-1-2"));

    fireEvent.click(screen.getByTestId("requantize-region-1-1"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("requantize-dialog-submit"));
    });

    expect(regionRequantizeMock).toHaveBeenCalledTimes(1);
    const [, targets] = regionRequantizeMock.mock.calls[0];
    expect(
      targets.map((t: { gradientRegionIndex: number }) => t.gradientRegionIndex),
    ).toEqual([1]);
    // Pre-existing checkbox selection must survive a per-region submit.
    // 单 region 按钮提交后，原多选列表保持不变。
    expect(useConverterStore.getState().selectedGradientRegions).toEqual([
      { groupIndex: 1, regionIndex: 1 },
      { groupIndex: 1, regionIndex: 2 },
    ]);
  });

  it("batch requantize submits all checked targets and clears the checkbox selection", async () => {
    regionRequantizeMock.mockResolvedValue({
      preview_url: "/api/files/requantized.png",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    });

    render(<GradientGroupsPanel />);
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    fireEvent.click(screen.getByTestId("merge-check-1-1"));
    fireEvent.click(screen.getByTestId("merge-check-1-2"));

    fireEvent.click(screen.getByTestId("gradient-groups-batch-requantize"));

    // Belt-and-braces: confirm the numeric input + slider share state.
    // 通过数字输入设置量化色数，验证与滑块共享状态。
    fireEvent.change(screen.getByTestId("requantize-dialog-input"), {
      target: { value: "32" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("requantize-dialog-submit"));
    });

    expect(regionRequantizeMock).toHaveBeenCalledTimes(1);
    const [, targets, count] = regionRequantizeMock.mock.calls[0];
    expect(count).toBe(32);
    expect(
      targets
        .map((t: { gradientRegionIndex: number }) => t.gradientRegionIndex)
        .sort(),
    ).toEqual([1, 2]);
    // Dialog closes on submit; batch path clears the checkbox list so the
    // panel returns to a clean state (consistent with flatten / merge UX).
    // 批量路径提交后弹窗关闭且勾选清空，与 flatten 一致。
    expect(screen.queryByTestId("requantize-dialog")).toBeNull();
    expect(useConverterStore.getState().selectedGradientRegions).toEqual([]);
  });

  it("checkbox is a controlled input bound to selectedGradientRegions", () => {
    render(<GradientGroupsPanel />);
    fireEvent.click(
      screen.getByRole("button", { name: /expand regions|展开区域/i }),
    );
    const box = screen.getByTestId("merge-check-1-1") as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    expect(useConverterStore.getState().selectedGradientRegions).toEqual([
      { groupIndex: 1, regionIndex: 1 },
    ]);
    expect(
      (screen.getByTestId("merge-check-1-1") as HTMLInputElement).checked,
    ).toBe(true);
  });
});
