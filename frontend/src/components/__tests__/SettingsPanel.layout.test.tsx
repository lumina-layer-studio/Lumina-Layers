import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";

vi.mock("../../api/system", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/system")>();
  return {
    ...actual,
    clearCache: vi.fn(),
    getPrinters: vi.fn(),
    getCustom3mfTemplates: vi.fn().mockResolvedValue([]),
    getSlicers: vi.fn(),
    saveSettings: vi.fn(),
  };
});

vi.mock("../../utils/retryAsync", () => ({
  retryAsync: vi.fn((operation: () => Promise<unknown>) => operation()),
}));

import type { PrinterInfo, SlicerOption } from "../../api/types";
import { ModelingMode } from "../../api/types";
import * as systemApi from "../../api/system";
import { I18nProvider } from "../../i18n/context";
import { translations } from "../../i18n/translations";
import { DEFAULT_SETTINGS, useSettingsStore } from "../../stores/settingsStore";
import { DEFAULT_STATE, useConverterStore } from "../../stores/converter";
import { useSlicerStore } from "../../stores/slicerStore";
import { useWidgetStore } from "../../stores/widgetStore";
import { useActionHistoryStore } from "../../stores/actionHistoryStore";
import { useActionHistoryBootstrap } from "../../hooks/useActionHistoryBootstrap";
import { collectBugReportContext } from "../../utils/bugReportContext";
import SettingsPanel from "../SettingsPanel";

const SLICERS: SlicerOption[] = [
  { id: "BambuStudio", display_name: "Bambu Studio" },
];

const PRINTERS: PrinterInfo[] = [
  {
    id: "bambu-h2d",
    display_name: "Bambu Lab H2D",
    brand: "Bambu Lab",
    bed_width: 350,
    bed_depth: 320,
    bed_height: 325,
    supported_nozzle_sizes: ["0.2", "0.4"],
    supported_slicers: ["BambuStudio"],
    thumbnail: "slicers/BambuStudio/h2d.png",
    device_profiles: [
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.4",
        slicer_id: "BambuStudio",
        nozzle_size: "0.4",
        source_profile_name: "Bambu Lab H2D 0.4 nozzle",
        revision: "sha256:h2d",
        supported: true,
      },
    ],
  },
  {
    id: "bambu-p1s",
    display_name: "Bambu Lab P1S",
    brand: "Bambu Lab",
    bed_width: 256,
    bed_depth: 256,
    bed_height: 250,
    supported_nozzle_sizes: ["0.4"],
    supported_slicers: ["BambuStudio"],
    thumbnail: "slicers/BambuStudio/p1s.png",
    device_profiles: [
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-p1s:0.4",
        slicer_id: "BambuStudio",
        nozzle_size: "0.4",
        source_profile_name: "Bambu Lab P1S 0.4 nozzle",
        revision: "sha256:p1s",
        supported: true,
      },
    ],
  },
];

function renderPanel() {
  return render(
    <I18nProvider>
      <SettingsPanel />
    </I18nProvider>,
  );
}

describe("SettingsPanel information architecture", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useConverterStore.setState({ ...DEFAULT_STATE });
    useWidgetStore.setState({ activeTab: "settings" });
    useActionHistoryStore.getState()._resetForTests();
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      printerModel: "bambu-h2d",
      slicerSoftware: "BambuStudio",
      nozzleSize: "0.4",
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
      language: "zh",
    });
    useSlicerStore.setState({
      slicers: [],
      selectedSlicerId: null,
      isDetecting: false,
      isLaunching: false,
      isValidatingCustomPath: false,
      launchMessage: null,
      customPathMessage: null,
      customPathError: null,
      error: null,
    });
    vi.mocked(systemApi.getPrinters).mockResolvedValue(PRINTERS);
    vi.mocked(systemApi.getSlicers).mockResolvedValue(SLICERS);
    vi.mocked(systemApi.clearCache).mockResolvedValue({
      status: "success",
      message: "ok",
      deleted_files: 0,
      freed_bytes: 0,
      details: {
        registry_cleaned: 0,
        sessions_cleaned: 0,
        output_files_cleaned: 0,
      },
    });
    vi.mocked(systemApi.saveSettings).mockResolvedValue({
      status: "success",
      message: "Settings saved",
    });
  });

  it("keeps SVG scope in help while preserving the editable value", async () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /转换与精度/ }));
    const section = screen.getByTestId("settings-svg-raster-density-section");
    expect(within(section).queryByText(translations["settings.svg_pixels_per_mm_scope"].zh)).not.toBeInTheDocument();
    const slider = within(section).getByRole("slider", { name: "采样密度" });
    const initialValue = slider.getAttribute("aria-valuenow") ?? slider.getAttribute("value");
    fireEvent.click(within(section).getByRole("button", { name: /仅在.*高保真/ }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(translations["settings.svg_pixels_per_mm_tip"].zh);
    expect(slider.getAttribute("aria-valuenow") ?? slider.getAttribute("value")).toBe(initialValue);
  });

  it("keeps cache explanations in help and displays the cleanup result inline", async () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /存储与维护/ }));
    expect(screen.queryByText(translations["settings.clear_cache_desc"].zh)).not.toBeInTheDocument();
    expect(screen.queryByText(translations["settings.cache_summary"].zh)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "缓存管理" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(translations["settings.cache_summary"].zh);
    expect(systemApi.clearCache).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "清除缓存" }));
    expect(await screen.findByText("已清除 0 个临时文件，释放 0.0 KB")).toBeInTheDocument();
    expect(systemApi.clearCache).toHaveBeenCalledTimes(1);
  });

  it("shows one settings category at a time", async () => {
    renderPanel();

    const navigation = screen.getByRole("navigation", { name: "设置分类" });
    const deviceButton = within(navigation).getByRole("button", {
      name: /打印与切片/,
    });

    expect(deviceButton).toHaveAttribute("aria-current", "page");
    // A settings category owns its scroll boundary. Chaining into the clipped
    // app shell can latch a wheel sequence there, even after it reverses.
    expect(screen.getByRole("region", { name: /打印与切片/ })).toHaveClass("overscroll-y-contain");
    expect(
      await screen.findByRole("heading", { name: "当前设备", level: 3 }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "完成通知" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(navigation).getByRole("button", { name: /常规/ }),
    );
    expect(
      screen.getByRole("heading", { name: "完成通知", level: 3 }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "当前设备" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(navigation).getByRole("button", { name: /转换与精度/ }),
    );
    expect(screen.getByRole("region", { name: /转换与精度/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /转换与精度/ })).toHaveClass("overscroll-y-contain");
    expect(
      screen.getByRole("heading", { name: "转换与精度", level: 2 }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "SVG 清晰度",
        level: 3,
      }),
    ).toBeInTheDocument();

    fireEvent.click(
      within(navigation).getByRole("button", { name: /存储与维护/ }),
    );
    expect(screen.getByRole("region", { name: /存储与维护/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /存储与维护/ })).toHaveClass("overscroll-y-contain");
    expect(
      screen.getByRole("heading", { name: "存储与维护", level: 2 }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "缓存管理", level: 3 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "清除缓存" })).toBeInTheDocument();
  });

  it("offers SVG hole compensation in Conversion and precision settings", async () => {
    useConverterStore.setState({
      imageFile: new File(["<svg/>"], "art.svg", { type: "image/svg+xml" }),
      modeling_mode: ModelingMode.VECTOR,
    });
    renderHook(() => useActionHistoryBootstrap());
    renderPanel();
    await screen.findByRole("heading", { name: "当前设备", level: 3 });
    const navigation = screen.getByRole("navigation", { name: "设置分类" });
    fireEvent.click(within(navigation).getByRole("button", { name: /转换与精度/ }));

    const conversionSettings = screen.getByRole("region", { name: /转换与精度/ });
    const toggle = within(conversionSettings).getByRole("switch", { name: "SVG 小洞补偿" });
    expect(toggle).not.toBeChecked();
    expect(toggle).toBeEnabled();
    fireEvent.click(toggle);
    expect(toggle).toBeChecked();
    expect(useConverterStore.getState().svg_hole_compensation_enabled).toBe(true);
    const areaInput = within(conversionSettings).getByRole("textbox", { name: /mm²/ });
    const widthInput = within(conversionSettings).getByRole("textbox", { name: /mm\)/ });
    expect(areaInput).toHaveValue("0.5");
    expect(widthInput).toHaveValue("0.1");
    fireEvent.change(areaInput, {
      target: { value: "0.25" },
    });
    fireEvent.blur(areaInput);
    fireEvent.change(widthInput, {
      target: { value: "0.05" },
    });
    fireEvent.blur(widthInput);

    const report = collectBugReportContext();
    expect(report.active_tab).toBe("settings");
    expect(report.advanced_params).toBeNull();
    for (const [key, from, to] of [
      ["svg_hole_compensation_enabled", false, true],
      ["svg_hole_max_area_mm2", 0.5, 0.25],
      ["svg_hole_max_width_mm", 0.1, 0.05],
    ] as const) {
      const entry = report.action_history?.find((event) => event.changed_fields?.[key]);
      expect(entry?.changed_fields?.[key]).toEqual({ from, to });
      expect(entry?.snapshot.active_tab).toBe("settings");
    }

    fireEvent.click(within(navigation).getByRole("button", { name: /常规/ }));
    expect(screen.queryByRole("switch", { name: "SVG 小洞补偿" })).not.toBeInTheDocument();
    fireEvent.click(within(navigation).getByRole("button", { name: /转换与精度/ }));
    expect(screen.getByRole("switch", { name: "SVG 小洞补偿" })).toBeChecked();

    act(() => useWidgetStore.setState({ activeTab: "converter" }));
    expect(collectBugReportContext().advanced_params).toMatchObject({
      generation: {
        svg_hole_compensation_enabled: true,
        svg_hole_max_area_mm2: 0.25,
        svg_hole_max_width_mm: 0.05,
      },
    });
  });

  it("uses one concise label for each toggle setting", async () => {
    renderPanel();

    const navigation = screen.getByRole("navigation", { name: "设置分类" });
    fireEvent.click(
      within(navigation).getByRole("button", { name: /常规/ }),
    );

    expect(screen.getAllByText("完成通知")).toHaveLength(1);
    expect(
      screen.getByRole("switch", { name: "完成通知" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("启用浏览器完成通知")).not.toBeInTheDocument();
    expect(screen.getAllByText("加载趣味消息")).toHaveLength(1);

    fireEvent.click(
      within(navigation).getByRole("button", { name: /转换与精度/ }),
    );

    expect(screen.getAllByText("颜色计算精度")).toHaveLength(1);
    expect(
      screen.getByRole("switch", { name: "颜色计算精度" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("自动合并渐变色")).toHaveLength(1);
    expect(
      screen.getByRole("switch", { name: "自动合并渐变色" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("平滑 SVG 轻量预览")).toHaveLength(1);
    const smoothVectorSwitch = screen.getByRole("switch", {
      name: "平滑 SVG 轻量预览",
    });
    expect(smoothVectorSwitch).toBeChecked();

    fireEvent.click(smoothVectorSwitch);

    expect(smoothVectorSwitch).not.toBeChecked();
    expect(useSettingsStore.getState().enableSmoothVectorPreview).toBe(false);
    expect(
      screen.getByLabelText("关于平滑 SVG 轻量预览"),
    ).toBeInTheDocument();
  });

  it("offers uploaded filename help without toggling the default-off setting", async () => {
    renderPanel();

    const navigation = screen.getByRole("navigation", { name: "设置分类" });
    fireEvent.click(
      within(navigation).getByRole("button", { name: /常规/ }),
    );

    const filenameSection = screen.getByTestId(
      "settings-preserve-upload-filename-section",
    );
    const filenameSwitch = within(filenameSection).getByRole("switch", {
      name: "导出 3MF 时沿用上传文件名",
    });
    expect(filenameSwitch).not.toBeChecked();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.click(within(filenameSection).getByRole("button", {
      name: "导出 3MF 时沿用上传文件名",
    }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "开启后，普通单件生成会把“海报.png”下载为“海报.3mf”。默认关闭；批量、拼图和大画幅继续使用原有名称。",
    );
    expect(filenameSwitch).not.toBeChecked();

    fireEvent.click(filenameSwitch);

    expect(filenameSwitch).toBeChecked();
    expect(
      useSettingsStore.getState().preserveUploadFilenameFor3mf,
    ).toBe(true);
  });

  it("provides matching English copy for the uploaded filename switch", () => {
    expect(translations["settings.preserve_upload_filename_heading"].en).toBe(
      "Use uploaded filename for 3MF exports",
    );
    expect(
      translations["settings.preserve_upload_filename_description"].en,
    ).toBe(
      "When enabled, a normal single-item export downloads “poster.png” as “poster.3mf”. It is off by default; batch, puzzle, and large-format exports keep their existing names.",
    );
  });

  it("leaves the interface scale to the browser's own zoom outside the desktop app", () => {
    renderPanel();
    const navigation = screen.getByRole("navigation", { name: "设置分类" });
    fireEvent.click(within(navigation).getByRole("button", { name: /常规/ }));

    expect(screen.getByTestId("settings-language-section")).toBeInTheDocument();
    expect(
      screen.queryByTestId("settings-interface-scale-section"),
    ).not.toBeInTheDocument();
  });

  it("selects and remembers the interface language under General", () => {
    useSettingsStore.getState().setLanguage("en");
    renderPanel();
    const navigation = screen.getByRole("navigation", { name: "设置分类" });
    fireEvent.click(within(navigation).getByRole("button", { name: /常规/ }));

    const languagePicker = within(screen.getByTestId("settings-language-section"))
      .getByRole("combobox", { name: "界面语言 / Language" });
    expect(languagePicker).toHaveTextContent("English");
    fireEvent.click(languagePicker);
    fireEvent.click(screen.getByRole("option", { name: "简体中文" }));
    expect(useSettingsStore.getState().language).toBe("zh");
    expect(JSON.parse(localStorage.getItem("lumina-settings")!).state.language).toBe("zh");

    fireEvent.click(languagePicker);
    fireEvent.click(screen.getByRole("option", { name: "English" }));
    expect(useSettingsStore.getState().language).toBe("en");
    expect(JSON.parse(localStorage.getItem("lumina-settings")!).state.language).toBe("en");
    fireEvent.click(within(navigation).getByRole("button", { name: /打印与切片/ }));
    fireEvent.click(within(navigation).getByRole("button", { name: /常规/ }));
    expect(within(screen.getByTestId("settings-language-section"))
      .getByRole("combobox")).toHaveTextContent("English");
  });

  it("offers the centered or left top navigation choice under General", () => {
    renderPanel();

    const navigation = screen.getByRole("navigation", { name: "设置分类" });
    fireEvent.click(
      within(navigation).getByRole("button", { name: /常规/ }),
    );

    const alignmentSection = screen.getByTestId(
      "settings-header-nav-alignment-section",
    );
    expect(
      within(alignmentSection).getByRole("heading", {
        name: "顶部导航对齐",
        level: 3,
      }),
    ).toBeInTheDocument();
    const centered = within(alignmentSection).getByRole("radio", { name: "居中" });
    const left = within(alignmentSection).getByRole("radio", { name: "居左" });
    expect(centered).toBeChecked();
    expect(left).not.toBeChecked();

    fireEvent.click(left);

    expect(left).toBeChecked();
    expect(useSettingsStore.getState().headerNavAlignment).toBe("left");
  });

  it("provides matching English copy for the top navigation choice", () => {
    expect(translations["settings.header_nav_alignment_heading"].en).toBe(
      "Top navigation alignment",
    );
    expect(translations["settings.header_nav_alignment_center"].en).toBe(
      "Centered",
    );
    expect(translations["settings.header_nav_alignment_left"].en).toBe("Left");
  });

  it("keeps the machine registry out of the page until the chooser opens", async () => {
    renderPanel();

    await screen.findByRole("heading", { name: "当前设备", level: 3 });
    expect(
      screen.queryByTestId("machine-adapter-card-bambu-h2d"),
    ).not.toBeInTheDocument();

    const changeDeviceButton = screen.getByRole("button", { name: "更改设备" });
    await waitFor(() => {
      expect(changeDeviceButton).toBeEnabled();
    });
    fireEvent.click(changeDeviceButton);

    const dialog = await screen.findByRole("dialog", { name: "选择打印设备" });
    expect(
      within(dialog).getByTestId("machine-adapter-card-bambu-h2d"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByTestId("machine-adapter-card-bambu-p1s"),
    ).toBeInTheDocument();

    fireEvent.change(
      within(dialog).getByRole("searchbox", { name: "搜索打印机" }),
      { target: { value: "P1S" } },
    );

    expect(
      within(dialog).queryByTestId("machine-adapter-card-bambu-h2d"),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByTestId("machine-adapter-card-bambu-p1s"),
    ).toBeInTheDocument();
  });

  it("shows normalized transparent printer artwork without a decorative stage", async () => {
    renderPanel();

    const summaryImage = await screen.findByRole("img", {
      name: "Bambu Lab H2D",
    });
    expect(summaryImage.parentElement).toHaveClass(
      "rounded-none",
      "bg-transparent",
    );
    expect(summaryImage).toHaveClass("p-0");

    const changeDeviceButton = screen.getByRole("button", { name: "更改设备" });
    await waitFor(() => {
      expect(changeDeviceButton).toBeEnabled();
    });
    fireEvent.click(changeDeviceButton);

    const dialog = await screen.findByRole("dialog", { name: "选择打印设备" });
    const h2dCard = within(dialog).getByTestId("machine-adapter-card-bambu-h2d");
    const chooserImage = within(h2dCard).getByRole("img", {
      name: "Bambu Lab H2D",
    });

    expect(chooserImage.parentElement).toHaveClass(
      "aspect-square",
      "rounded-none",
      "bg-transparent",
    );
    expect(chooserImage).toHaveClass("p-0");
  });

  it("keeps manual slicer setup collapsed until requested", async () => {
    renderPanel();

    await waitFor(() => {
      expect(systemApi.getSlicers).toHaveBeenCalled();
    });
    expect(screen.queryByLabelText("手动切片软件路径")).not.toBeInTheDocument();

    const disclosure = screen.getByRole("button", { name: /手动设置/ });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(disclosure);

    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("手动切片软件路径")).toBeInTheDocument();
  });

  it("closes the machine chooser with Escape", async () => {
    renderPanel();

    const changeDeviceButton = screen.getByRole("button", { name: "更改设备" });
    await waitFor(() => {
      expect(changeDeviceButton).toBeEnabled();
    });
    changeDeviceButton.focus();
    fireEvent.click(changeDeviceButton);
    expect(
      await screen.findByRole("dialog", { name: "选择打印设备" }),
    ).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "选择打印设备" }),
      ).not.toBeInTheDocument();
    });
    expect(changeDeviceButton).toHaveFocus();
  });

  it("keeps Tab and Shift+Tab focus inside the machine chooser", async () => {
    renderPanel();

    const changeDeviceButton = screen.getByRole("button", { name: "更改设备" });
    await waitFor(() => {
      expect(changeDeviceButton).toBeEnabled();
    });
    changeDeviceButton.focus();
    fireEvent.click(changeDeviceButton);

    const dialog = await screen.findByRole("dialog", { name: "选择打印设备" });
    const searchInput = within(dialog).getByRole("searchbox", {
      name: "搜索打印机",
    });
    const closeButton = within(dialog).getByRole("button", { name: "关闭" });
    const doneButton = within(dialog).getByRole("button", { name: "完成" });

    expect(searchInput).toHaveFocus();

    doneButton.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(closeButton).toHaveFocus();

    closeButton.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(doneButton).toHaveFocus();
  });

  it("restores focus after closing the machine chooser with its buttons", async () => {
    renderPanel();

    const changeDeviceButton = screen.getByRole("button", { name: "更改设备" });
    await waitFor(() => {
      expect(changeDeviceButton).toBeEnabled();
    });
    changeDeviceButton.focus();
    fireEvent.click(changeDeviceButton);

    let dialog = await screen.findByRole("dialog", { name: "选择打印设备" });
    fireEvent.click(within(dialog).getByRole("button", { name: "完成" }));
    expect(changeDeviceButton).toHaveFocus();

    fireEvent.click(changeDeviceButton);
    dialog = await screen.findByRole("dialog", { name: "选择打印设备" });
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }));
    expect(changeDeviceButton).toHaveFocus();
  });
});
