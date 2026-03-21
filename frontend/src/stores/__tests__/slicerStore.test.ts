import { describe, it, expect, beforeEach, vi } from "vitest";
import { useSlicerStore } from "../slicerStore";
import type { SlicerInfo } from "../../api/types";

/**
 * Slicer_Store 单元测试
 * Validates: Requirements 4.2, 4.3, 4.4, 4.5
 */

vi.mock("../../api/slicer", () => ({
  detectSlicers: vi.fn(),
  launchSlicer: vi.fn(),
}));

import {
  detectSlicers as apiDetectSlicers,
  launchSlicer as apiLaunchSlicer,
} from "../../api/slicer";

const mockDetect = vi.mocked(apiDetectSlicers);
const mockLaunch = vi.mocked(apiLaunchSlicer);

const MOCK_SLICERS: SlicerInfo[] = [
  { id: "bambu_studio", display_name: "Bambu Studio", exe_path: "C:\\bambu.exe" },
  { id: "orca_slicer", display_name: "OrcaSlicer", exe_path: "C:\\orca.exe" },
];

function resetStore(): void {
  useSlicerStore.setState({
    slicers: [],
    selectedSlicerId: null,
    isDetecting: false,
    isLaunching: false,
    launchMessage: null,
    error: null,
  });
}

describe("detectSlicers", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  it("成功时更新 slicers 列表并自动选中第一个", async () => {
    mockDetect.mockResolvedValue({ slicers: MOCK_SLICERS });

    await useSlicerStore.getState().detectSlicers();

    const state = useSlicerStore.getState();
    expect(state.slicers).toEqual(MOCK_SLICERS);
    expect(state.selectedSlicerId).toBe("bambu_studio");
    expect(state.isDetecting).toBe(false);
    expect(state.error).toBeNull();
  });

  it("失败时设置 error 状态", async () => {
    mockDetect.mockRejectedValue(new Error("网络错误"));

    await useSlicerStore.getState().detectSlicers();

    const state = useSlicerStore.getState();
    expect(state.slicers).toEqual([]);
    expect(state.isDetecting).toBe(false);
    expect(state.error).toBe("网络错误");
  });

  it("失败且非 Error 实例时使用默认错误消息", async () => {
    mockDetect.mockRejectedValue("unknown");

    await useSlicerStore.getState().detectSlicers();

    expect(useSlicerStore.getState().error).toBe("切片软件检测失败");
  });

  it("检测到空列表时 selectedSlicerId 为 null", async () => {
    mockDetect.mockResolvedValue({ slicers: [] });

    await useSlicerStore.getState().detectSlicers();

    const state = useSlicerStore.getState();
    expect(state.slicers).toEqual([]);
    expect(state.selectedSlicerId).toBeNull();
  });
});

describe("setSelectedSlicerId", () => {
  beforeEach(() => {
    resetStore();
  });

  it("更新 selectedSlicerId 为指定值", () => {
    useSlicerStore.getState().setSelectedSlicerId("orca_slicer");
    expect(useSlicerStore.getState().selectedSlicerId).toBe("orca_slicer");
  });

  it("设置为 null 清除选中", () => {
    useSlicerStore.getState().setSelectedSlicerId("bambu_studio");
    useSlicerStore.getState().setSelectedSlicerId(null);
    expect(useSlicerStore.getState().selectedSlicerId).toBeNull();
  });
});

describe("launchSlicer", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  it("成功时设置 launchMessage", async () => {
    useSlicerStore.setState({ selectedSlicerId: "bambu_studio" });
    mockLaunch.mockResolvedValue({
      status: "success",
      message: "已在 Bambu Studio 中打开",
    });

    await useSlicerStore.getState().launchSlicer("/output/model.3mf");

    const state = useSlicerStore.getState();
    expect(state.launchMessage).toBe("已在 Bambu Studio 中打开");
    expect(state.isLaunching).toBe(false);
    expect(state.error).toBeNull();
    expect(mockLaunch).toHaveBeenCalledWith({
      slicer_id: "bambu_studio",
      file_path: "/output/model.3mf",
    });
  });

  it("失败时设置 error 状态", async () => {
    useSlicerStore.setState({ selectedSlicerId: "bambu_studio" });
    mockLaunch.mockRejectedValue(new Error("启动失败"));

    await useSlicerStore.getState().launchSlicer("/output/model.3mf");

    const state = useSlicerStore.getState();
    expect(state.error).toBe("启动失败");
    expect(state.isLaunching).toBe(false);
    expect(state.launchMessage).toBeNull();
  });

  it("未选择切片软件时直接设置 error 不调用 API", async () => {
    await useSlicerStore.getState().launchSlicer("/output/model.3mf");

    expect(useSlicerStore.getState().error).toBe("请先选择切片软件");
    expect(mockLaunch).not.toHaveBeenCalled();
  });
});
