import { useSessionLease } from "../hooks/useSessionLease";
import { heartbeatSession } from "../api/session";
vi.mock("../api/session", async () => {
  const actual = await vi.importActual<typeof import("../api/session")>("../api/session");
  return { ...actual, heartbeatSession: vi.fn() };
});
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import "./communityTestMocks";
import { TUTORIAL_STEPS } from "../data/tutorialSteps";
import { useTutorialStore } from "../stores/tutorialStore";
import { useWidgetStore } from "../stores/widgetStore";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useExtractorStore } from "../stores/extractorStore";
import { discardResourceCalibration, useMaterialTrialStore } from "../stores/converter/resourceSelection";
import { useMaterialGuideStore } from "../stores/materialGuideStore";
import TutorialTour from "../components/tutorial/TutorialTour";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import BasicSettings from "../components/sections/BasicSettings";
import BedSizeSelector from "../components/sections/BedSizeSelector";
import { useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import * as converterApi from "../api/converter";
import * as lutApi from "../api/lut";
import * as extractorApi from "../api/extractor";
import * as materialSyncApi from "../api/materialSync";
import {
  ColorMode as ColorModeEnum,
  StructureMode as StructureModeEnum,
  ModelingMode as ModelingModeEnum,
} from "../api/types";
import type { LutDetailsCatalogGroup, SavedMaterialLibraryItem } from "../api/types";

vi.mock("../api/materialGamut", () => ({
  // The cache status line asks for an overview; keep it pending so no request leaves the test.
  fetchMaterialCacheOverview: vi.fn(() => new Promise(() => {})),
}));

vi.mock("../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../api/lut")>(
    "../api/lut",
  );
  return {
    ...actual,
    fetchLutInfo: vi.fn(),
    fetchLutCatalog: vi.fn(),
    fetchLutDetailsCatalog: vi.fn(),
    fetchCloudLutRegistryStatus: vi.fn(),
    fetchCloudLutRegistryCatalog: vi.fn(),
    installCloudLut: vi.fn(),
  };
});

vi.mock("../api/materialSync", () => ({ fetchMaterialSyncStatus: vi.fn(), fetchMaterialRegistryCatalog: vi.fn(), installMaterialRegistryCatalogEntry: vi.fn(), rollbackMaterialSyncRevision: vi.fn() }));

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    fetchLutList: vi.fn(),
    uploadLut: vi.fn(),
    uploadModelSurface: vi.fn(),
  };
});

vi.mock("../api/extractor", async () => {
  const actual = await vi.importActual<typeof import("../api/extractor")>(
    "../api/extractor",
  );
  return {
    ...actual,
    listGradientCardMaterials: vi.fn(),
    installExtractedLut: vi.fn(),
  };
});

function makeLegacyCatalogGroups(): LutDetailsCatalogGroup[] {
  return [
    {
      manufacturer: "Brand A",
      items: [
        {
          name: "A 4C",
          path: "lut-ref/fp-a4.npy",
          color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
          compatibility_key: "sig-a4",
          source_kind: "legacy_lookup",
          manufacturer: "Brand A",
          material_type: "",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["brand", "a", "4c"],
        },
        {
          name: "A 4C Alt",
          path: "lut-ref/fp-a4-alt.npy",
          color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
          compatibility_key: "sig-a4-alt",
          source_kind: "legacy_lookup",
          manufacturer: "Brand A",
          material_type: "",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["brand", "a", "4c", "alt"],
        },
        {
          name: "A 8C",
          path: "lut-ref/fp-a8.npy",
          color_mode: ColorModeEnum.EIGHT_COLOR,
          compatibility_key: "sig-a8",
          source_kind: "legacy_lookup",
          manufacturer: "Brand A",
          material_type: "",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["brand", "a", "8c"],
        },
      ],
    },
    {
      manufacturer: "Brand B",
      items: [
        {
          name: "B BW",
          path: "lut-ref/fp-bbw.npy",
          color_mode: ColorModeEnum.BW,
          compatibility_key: "sig-bw",
          source_kind: "legacy_lookup",
          manufacturer: "Brand B",
          material_type: "",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["brand", "b", "bw"],
        },
      ],
    },
    {
      manufacturer: "Unlabeled",
      items: [
        {
          name: "Loose Merged",
          path: "lut-ref/fp-loose.npy",
          color_mode: ColorModeEnum.MERGED,
          compatibility_key: "sig-merged",
          source_kind: "legacy_lookup",
          manufacturer: "Unlabeled",
          material_type: "",
          manufacturer_source: "fallback",
          material_source: "fallback",
          search_tokens: ["loose", "merged"],
        },
      ],
    },
  ];
}

// Reset store to a clean state before each test
beforeEach(() => {
  localStorage.removeItem("lumina.material-archive-guide.dismissed.v1");
  useMaterialGuideStore.setState({ requested: false });
  useMaterialTrialStore.setState({ backup: null });
  vi.clearAllMocks();
  vi.mocked(converterApi.fetchLutList).mockResolvedValue({
    luts: [
      {
        name: "Brand A - A4",
        color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
        path: "lut-ref/fp-a4.npy",
      },
    ],
  });
  vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValue({
    groups: makeLegacyCatalogGroups(),
  });
  vi.mocked(lutApi.fetchLutCatalog).mockResolvedValue({
    legacy_groups: [],
    native_brand_groups: [],
  });
  vi.mocked(lutApi.fetchLutInfo).mockResolvedValue({
    name: "A 4C",
    color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
    color_count: 4,
  });
  vi.mocked(converterApi.uploadModelSurface).mockResolvedValue({
    status: "ok",
    model_file_id: "model-file-1",
    summary: {
      vertex_count: 8,
      face_count: 12,
      bounds_min_mm: [0, 0, 0],
      bounds_max_mm: [20, 10, 2],
      extents_mm: [20, 10, 2],
      is_watertight: true,
      is_winding_consistent: true,
      body_count: 1,
      unit_warning: null,
    },
    surface_candidates: [],
    warnings: [],
  });
  vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({
    status: "success",
    message: "ok",
    materials: [],
  });
  useConverterStore.setState({
    imageFile: null,
    imagePreviewUrl: null,
    source_version: "legacy",
    batchMode: false,
    batchFiles: [],
    enableCrop: false,
    cropModalOpen: false,
    isCropping: false,
    lut_name: "",
    lut_names: [],
    lutList: [],
    lutListFull: [
      {
        name: "Brand A - A4",
        color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
        path: "lut-ref/fp-a4.npy",
      },
      {
        name: "Brand A - A4 Alt",
        color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
        path: "lut-ref/fp-a4-alt.npy",
      },
      {
        name: "Brand A - A8",
        color_mode: ColorModeEnum.EIGHT_COLOR,
        path: "lut-ref/fp-a8.npy",
      },
      {
        name: "Brand B - BW",
        color_mode: ColorModeEnum.BW,
        path: "lut-ref/fp-bbw.npy",
      },
      {
        name: "Loose Merged",
        color_mode: ColorModeEnum.MERGED,
        path: "lut-ref/fp-loose.npy",
      },
    ],
    lutListLoading: false,
    lutListError: null,
    legacyCatalogGroups: makeLegacyCatalogGroups(),
    legacyCatalogLoading: false,
    legacyCatalogError: null,
    selectedLegacyManufacturer: "",
    nativeBrandGroups: [],
    nativeBrandGroupsLoading: false,
    selectedNativeBrandKey: "",
    selectedNativeDbNames: [],
    color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
    target_width_mm: 80,
    target_height_mm: 80,
    aspectRatio: null,
    bedSizes: [],
    largeFormatEnabled: false,
    spacer_thick: 0.64,
    structure_mode: StructureModeEnum.SINGLE_SIDED,
    modeling_mode: ModelingModeEnum.HIGH_FIDELITY,
    enable_relief: false,
    modelSurfaceEnabled: false,
    modelSurfaceFile: null,
    modelSurfacePreviewUrl: null,
    modelSurfaceModelFileId: null,
    modelSurfaceSummary: null,
    modelSurfaceSelectionId: null,
    modelSurfaceSelection: null,
    modelSurfaceFootprint: null,
    modelSurfaceCandidates: [],
    modelSurfaceLoading: false,
    modelSurfaceSelecting: false,
    modelSurfaceError: null,
    modelSurfaceWarnings: [],
    previewWarnings: [],
    largeFormatWarnings: [],
    materialDynamicLayerCountEnabled: false,
    materialMinLayerCount: 5,
    materialMaxLayerCount: 10,
    materialDynamicRecipes: [],
    materialLayerBenefitCurve: [],
  });
  useSettingsStore.setState({
    ...DEFAULT_SETTINGS,
    language: "zh",
  });
});

afterEach(() => {
  discardResourceCalibration();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function makeDbOption(name: string) {
  return {
    name,
    path: `/${name}.json`,
    color_mode: "8-Color Max",
  };
}

function makePredictiveBrand() {
  return {
    brand_key: "bambulab_pla",
    material_type: "PLA",
    vendor: "Bambu Lab",
    display_name: "Bambu PLA",
    db_options: [makeDbOption("DB-A"), makeDbOption("DB-B"), makeDbOption("DB-C")],
    default_db_names: ["DB-B", "DB-C"],
    package_name: "bambu-pla-package",
    model_name: "bambu-pla-model",
    supported_modes: [
      { color_layers: 5, layer_height_mm: 0.08 },
      { color_layers: 8, layer_height_mm: 0.12 },
    ],
  };
}

function makeMaterial(
  directoryName: string,
  materialName: string,
): SavedMaterialLibraryItem {
  return {
    material_name: materialName,
    directory_name: directoryName,
    material_file_url: `/materials/${directoryName}/material.json`,
    estimated_rgb: [255, 255, 255],
  };
}

function isMultipleOfStep(value: number, step: number): boolean {
  const ratio = value / step;
  return Math.abs(ratio - Math.round(ratio)) < 1e-9;
}

describe("BasicSettings", () => {
  it("returns a saved calibration to the original material draft after navigation and keeps mixed-type confirmation", async () => {
    const old = { ...makeMaterial("old", "Old PLA"), material_type: "PLA" };
    const draft = { ...makeMaterial("draft", "Draft PLA"), material_type: "PLA" };
    const added = { ...makeMaterial("calibrated", "New PETG"), material_type: "PETG" };
    const imageFile = new File(["image"], "kept.png", { type: "image/png" });
    useConverterStore.setState({ source_version: "material", selectedMaterialDirNames: ["old"], imageFile, target_width_mm: 137 });
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({ status: "ok", message: "ok", materials: [old, draft] });
    const converter = render(<BasicSettings />);
    fireEvent.click(screen.getByTestId("material-picker-trigger"));
    fireEvent.click(await screen.findByRole("button", { name: "选择 Draft PLA" }));
    fireEvent.click(screen.getByRole("button", { name: "自己校准" }));
    expect(useWidgetStore.getState().activeTab).toBe("gradient-card-generate");
    converter.unmount();
    const GradientCardExtractPanel = (await import("../components/GradientCardExtractPanel")).default;
    useSingleStageStore.setState({ savedMaterialSummary: null });
    const extraction = render(<GradientCardExtractPanel />);
    expect(screen.queryByRole("button", { name: "加入当前配色" })).not.toBeInTheDocument();
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({ status: "ok", message: "ok", materials: [old, draft, added] });
    act(() => useSingleStageStore.setState({ savedMaterialSummary: { directory_name: "calibrated", material_name: "New PETG" }, saveSuccess: "Saved" }));
    fireEvent.click(screen.getByRole("button", { name: "加入当前配色" }));
    extraction.unmount();
    render(<BasicSettings />);
    await screen.findByRole("button", { name: "取消选择 New PETG" });
    expect(screen.getByRole("button", { name: "取消选择 Draft PLA" })).toBeInTheDocument();
    expect(useConverterStore.getState().selectedMaterialDirNames).toEqual(["old"]);
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(screen.getByRole("alertdialog", { name: "确认混合耗材类型？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "仍然使用" }));
    expect(useConverterStore.getState()).toMatchObject({ selectedMaterialDirNames: ["old", "draft", "calibrated"], imageFile, target_width_mm: 137 });
  });

  it("installs a confirmed LUT calibration and reopens the preserved draft for compatibility confirmation", async () => {
    const groups = makeLegacyCatalogGroups();
    groups[0].items[1].compatibility_key = groups[0].items[0].compatibility_key;
    useConverterStore.setState({ source_version: "legacy", legacyCatalogGroups: groups, selectedLegacyManufacturer: "Brand A", lut_names: ["Brand A - A4"], lut_name: "Brand A - A4", target_width_mm: 137 });
    const converter = render(<BasicSettings />);
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    fireEvent.click(screen.getByRole("checkbox", { name: /A 4C Alt/ }));
    fireEvent.click(screen.getByRole("button", { name: "自己校准" }));
    converter.unmount();
    const ExtractorPanel = (await import("../components/ExtractorPanel")).default;
    useExtractorStore.setState({ session_id: "confirmed-calibration", paletteConfirmed: false, defaultPalette: [], lut_download_url: "/old-unconfirmed-snapshot.npy" });
    const extraction = render(<ExtractorPanel />);
    expect(screen.queryByRole("button", { name: "用于当前任务" })).not.toBeInTheDocument();
    act(() => useExtractorStore.setState({ paletteConfirmed: true }));
    const added = { name: "Brand A - Calibrated", path: "lut-ref/calibrated.npy", color_mode: ColorModeEnum.EIGHT_COLOR };
    groups[0].items.push({ ...groups[0].items[2], name: "Calibrated LUT", path: added.path });
    vi.mocked(extractorApi.installExtractedLut).mockResolvedValue({ name: added.name });
    vi.mocked(lutApi.fetchLutCatalog).mockResolvedValue({ legacy_groups: [{ manufacturer: "Brand A", items: [...useConverterStore.getState().lutListFull, added] }], native_brand_groups: [] } as never);
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValue({ groups });
    fireEvent.click(screen.getByRole("button", { name: "用于当前任务" }));
    await waitFor(() => expect(useWidgetStore.getState().activeTab).toBe("converter"));
    expect(extractorApi.installExtractedLut).toHaveBeenCalledWith("confirmed-calibration");
    expect(converterApi.uploadLut).not.toHaveBeenCalled();
    extraction.unmount();
    render(<BasicSettings />);
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Calibrated LUT/ })).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByRole("checkbox", { name: /A 4C Alt/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("button", { name: "确认" })).toBeDisabled();
    expect(useConverterStore.getState()).toMatchObject({ lut_names: ["Brand A - A4"], color_mode: ColorModeEnum.FOUR_COLOR_RYBW, target_width_mm: 137 });
    fireEvent.click(screen.getAllByRole("checkbox").find((option) => within(option).queryByText("A 4C"))!);
    fireEvent.click(screen.getByRole("checkbox", { name: /A 4C Alt/ }));
    fireEvent.click(screen.getByRole("button", { name: `使用 ${ColorModeEnum.EIGHT_COLOR} 模式` }));
    expect(useConverterStore.getState().lut_names).toEqual([added.name]);
    expect(useConverterStore.getState().color_mode).toBe(ColorModeEnum.EIGHT_COLOR);
  });

  it("traps Tab and Escape in public material history before returning to its picker", async () => {
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({ status: "ok", message: "ok", materials: [makeMaterial("old", "Old PLA")] });
    vi.mocked(materialSyncApi.fetchMaterialSyncStatus).mockResolvedValue({ status: "ok", message: "ok", schema_version: "1.0", index_state: "ready", last_sync_at: null, registries: {}, installed_count: 1, local_overrides_count: 0, installed: [{ material_id: "old", revision_id: "r2", content_hash: "sha256:abc", channel: "official", source: "package", local_directory: "old", display_name: "Old PLA", display_brand: "", local_exists: true, material_file_exists: true, available_revisions: ["r1", "r2"] }] });
    vi.mocked(materialSyncApi.fetchMaterialRegistryCatalog).mockResolvedValue({ schema_version: "1.0", channels: ["official"], count: 0, total_count: 0, offset: 0, limit: 24, materials: [] });
    useConverterStore.setState({ source_version: "material", selectedMaterialDirNames: ["old"] });
    render(<BasicSettings />);
    fireEvent.click(screen.getByTestId("material-picker-trigger"));
    await screen.findByRole("button", { name: "取消选择 Old PLA" });
    fireEvent.click(screen.getByRole("button", { name: "去公开库查找" }));
    await waitFor(() => expect(screen.getByRole("searchbox")).toHaveFocus());
    const historyTrigger = screen.getByRole("button", { name: "本地历史版本" });
    historyTrigger.focus();
    fireEvent.click(historyTrigger);
    const history = screen.getByRole("dialog", { name: "本地历史版本" });
    const close = within(history).getAllByRole("button", { name: "关闭" })[0];
    expect(close).toHaveFocus();
    fireEvent.click(within(history).getByRole("radio"));
    const restore = within(history).getByRole("button", { name: "恢复所选版本" });
    restore.focus();
    fireEvent.keyDown(restore, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(restore).toHaveFocus();
    const revision = within(history).getByRole("radio");
    revision.focus();
    const normalTab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    revision.dispatchEvent(normalTab);
    expect(normalTab.defaultPrevented).toBe(false);
    expect(revision).toHaveFocus();
    fireEvent.keyDown(revision, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "本地历史版本" })).not.toBeInTheDocument());
    expect(historyTrigger).toHaveFocus();
    expect(screen.getByRole("button", { name: "返回本地选择" })).toBeInTheDocument();
    fireEvent.keyDown(historyTrigger, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "返回本地选择" })).not.toBeInTheDocument();
    expect(screen.getByTestId("material-picker-dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("material-picker-dialog")).not.toBeInTheDocument();
  });

  it.each(["unchanged", "image", "session"])("imports a local LUT without closing or applying the picker; context=%s", async (change) => {
    const groups = makeLegacyCatalogGroups();
    groups[0].items[1].compatibility_key = groups[0].items[0].compatibility_key;
    const added = { name: "Brand A - Imported", path: "lut-ref/imported.npy", color_mode: ColorModeEnum.FOUR_COLOR_RYBW };
    const refreshedGroups = groups.map((group) => ({ ...group, items: [...group.items] }));
    refreshedGroups[0].items.push({ ...groups[0].items[0], name: "Imported LUT", path: added.path });
    const imageFile = new File(["image"], "kept.png", { type: "image/png" });
    const nextImage = new File(["new"], "new.png", { type: "image/png" });
    useConverterStore.setState({ source_version: "legacy", legacyCatalogGroups: groups, selectedLegacyManufacturer: "Brand A", lut_names: ["Brand A - A4"], lut_name: "Brand A - A4", imageFile, target_width_mm: 137 });
    vi.mocked(lutApi.fetchLutCatalog).mockResolvedValue({ legacy_groups: [{ manufacturer: "Brand A", items: [...useConverterStore.getState().lutListFull, added] }], native_brand_groups: [] } as never);
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValue({ groups: refreshedGroups });
    let finish!: (value: Awaited<ReturnType<typeof converterApi.uploadLut>>) => void;
    vi.mocked(converterApi.uploadLut).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    render(<BasicSettings />);
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    fireEvent.click(screen.getByRole("checkbox", { name: /A 4C Alt/ }));
    fireEvent.click(screen.getByRole("button", { name: "+ 上传" }));
    expect(screen.getByTestId("lut-picker-dialog")).toBeInTheDocument();
    const input = document.querySelector('input[accept=".npy,.json,.npz,.msgpack"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["lut"], "local.npy")] } });
    expect(screen.getByRole("button", { name: "+ 上传" })).toBeDisabled();
    if (change === "image") act(() => useConverterStore.getState().setImageFile(nextImage));
    if (change === "session") act(() => useConverterStore.setState({ sessionId: "new-session" }));
    await act(async () => { finish({ status: "ok", message: "Imported", name: added.name }); });
    const imported = await screen.findByRole("checkbox", { name: /Imported LUT/ });
    expect(imported).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("checkbox", { name: /A 4C Alt/ })).toHaveAttribute("aria-checked", "true");
    expect(useConverterStore.getState()).toMatchObject({ lut_names: ["Brand A - A4"], color_mode: ColorModeEnum.FOUR_COLOR_RYBW, target_width_mm: 137 });
    fireEvent.click(imported);
    if (change === "unchanged") {
      fireEvent.click(screen.getByRole("button", { name: "确认" }));
      expect(useConverterStore.getState().lut_names).toEqual(["Brand A - A4", "Brand A - A4 Alt", added.name]);
      expect(useConverterStore.getState().imageFile).toBe(imageFile);
    } else {
      expect(screen.getByRole("button", { name: "确认" })).toBeDisabled();
      expect(screen.getByText(/当前图片或颜色模式已改变/)).toBeInTheDocument();
      if (change === "image") expect(useConverterStore.getState().imageFile).toBe(nextImage);
      else expect(useConverterStore.getState().sessionId).toBe("new-session");
    }
  });

  it("imports from an empty LUT picker, keeps an upload error visible, and requires confirmation of a new color mode", async () => {
    useConverterStore.setState({ lutList: [], lutListFull: [], legacyCatalogGroups: [], selectedLegacyManufacturer: "", lut_names: [], lut_name: "" });
    vi.mocked(converterApi.fetchLutList).mockResolvedValue({ luts: [] });
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValue({ groups: [] });
    vi.mocked(converterApi.uploadLut).mockRejectedValueOnce(new Error("Invalid local LUT"));
    render(<BasicSettings />);
    await waitFor(() => expect(screen.getByTestId("lut-picker-trigger")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    fireEvent.click(await screen.findByRole("button", { name: "导入本地文件" }));
    const input = document.querySelector('input[accept=".npy,.json,.npz,.msgpack"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["bad"], "bad.npy")] } });
    await screen.findByText("Invalid local LUT");
    expect(screen.getByTestId("resource-library-empty")).toBeInTheDocument();
    const added = { name: "Brand A - A8", path: "lut-ref/fp-a8.npy", color_mode: ColorModeEnum.EIGHT_COLOR };
    vi.mocked(converterApi.uploadLut).mockResolvedValue({ status: "ok", message: "Imported", name: added.name });
    vi.mocked(lutApi.fetchLutCatalog).mockResolvedValue({ legacy_groups: [{ manufacturer: "Brand A", items: [added] }], native_brand_groups: [] } as never);
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValue({ groups: [{ manufacturer: "Brand A", items: [makeLegacyCatalogGroups()[0].items[2]] }] });
    fireEvent.change(input, { target: { files: [new File(["valid"], "valid.npy")] } });
    fireEvent.click(await screen.findByTestId("lut-picker-brand-option-Brand A"));
    expect(useConverterStore.getState()).toMatchObject({ lut_names: [], lut_name: "", color_mode: ColorModeEnum.FOUR_COLOR_RYBW });
    fireEvent.click(screen.getByRole("checkbox", { name: /A 8C/ }));
    fireEvent.click(screen.getByRole("button", { name: `使用 ${ColorModeEnum.EIGHT_COLOR} 模式` }));
    expect(useConverterStore.getState()).toMatchObject({ lut_names: [added.name], color_mode: ColorModeEnum.EIGHT_COLOR });
  });
  it("installs a public material inside the picker and appends it without losing the task", async () => {
    const old = { ...makeMaterial("old", "Old PLA"), material_type: "PLA" };
    const added = { ...makeMaterial("added", "Added PLA"), material_type: "PLA" };
    const imageFile = new File(["image"], "kept.png", { type: "image/png" });
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({ status: "ok", message: "ok", materials: [old] });
    vi.mocked(materialSyncApi.fetchMaterialSyncStatus).mockResolvedValue({ status: "ok", message: "ok", schema_version: "1.0", index_state: "ready", last_sync_at: null, registries: {}, installed_count: 0, installed: [], local_overrides_count: 0 });
    vi.mocked(materialSyncApi.fetchMaterialRegistryCatalog).mockResolvedValue({ schema_version: "1.0", channels: ["official"], count: 1, total_count: 1, offset: 0, limit: 24, materials: [{ material_id: "added", revision_id: "r1", content_hash: "sha256:abc", local_directory: "added", display: { material_name: "Added PLA" }, compatibility: {}, channel: "official", visibility: "official", package_url: "/added.zip", package_sha256: "a".repeat(64), package_bytes: 123 }] });
    vi.mocked(materialSyncApi.installMaterialRegistryCatalogEntry).mockImplementation(async () => {
      vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({ status: "ok", message: "ok", materials: [old, added] });
      return { status: "ok", message: "Installed", installed_count: 1, installed_materials: [] };
    });
    useConverterStore.setState({ source_version: "material", selectedMaterialDirNames: ["old"], imageFile, target_width_mm: 137 });
    render(<BasicSettings />);
    fireEvent.click(screen.getByTestId("material-picker-trigger"));
    await screen.findByRole("button", { name: "取消选择 Old PLA" });
    fireEvent.click(screen.getByRole("button", { name: "去公开库查找" }));
    fireEvent.click(await screen.findByRole("button", { name: "下载到本地" }));
    await waitFor(() => expect(extractorApi.listGradientCardMaterials).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "返回本地选择" }));
    fireEvent.click(await screen.findByRole("button", { name: "选择 Added PLA" }));
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(useConverterStore.getState()).toMatchObject({ selectedMaterialDirNames: ["old", "added"], imageFile, target_width_mm: 137 });
  });

  it.each([false, true])("downloads a public LUT without auto-applying it; changed task=%s", async (changeTask) => {
    const groups = makeLegacyCatalogGroups();
    groups[0].items.push({ ...groups[0].items[0], name: "Added LUT", path: "lut-ref/added.npy" });
    const imageFile = new File(["image"], "kept.png", { type: "image/png" });
    const nextImage = new File(["new"], "new.png", { type: "image/png" });
    const newLut = { name: "Brand A - Added", path: "lut-ref/added.npy", color_mode: ColorModeEnum.FOUR_COLOR_RYBW };
    const entry = { lut_id: "added", revision_id: "r1", content_hash: "a", package_url: "/added.zip", package_sha256: "a".repeat(64), package_bytes: 123, local_path: "added.npy", display: { name: "Public LUT" }, compatibility: { color_mode: ColorModeEnum.FOUR_COLOR_RYBW } };
    vi.mocked(lutApi.fetchCloudLutRegistryStatus).mockResolvedValue({ configured: true, base_url: "https://example.test", channels: ["official"], installed_count: 0 });
    vi.mocked(lutApi.fetchCloudLutRegistryCatalog).mockResolvedValue({ configured: true, channels: ["official"], total: 1, items: [entry] });
    vi.mocked(lutApi.fetchLutCatalog).mockResolvedValue({ legacy_groups: [{ manufacturer: "Brand A", items: [...useConverterStore.getState().lutListFull, newLut] }], native_brand_groups: [] } as never);
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValue({ groups });
    let finish!: (value: Awaited<ReturnType<typeof lutApi.installCloudLut>>) => void;
    vi.mocked(lutApi.installCloudLut).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    useConverterStore.setState({ source_version: "legacy", selectedLegacyManufacturer: "Brand A", lut_names: ["Brand A - A4"], lut_name: "Brand A - A4", imageFile, target_width_mm: 137 });
    render(<BasicSettings />);
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    fireEvent.click(screen.getByRole("button", { name: "去公开库查找" }));
    fireEvent.click(await screen.findByRole("button", { name: "下载到本地" }));
    if (changeTask) act(() => useConverterStore.getState().setImageFile(nextImage));
    await act(async () => { finish({ ...entry, installed_path: "Cloud/added.npy" }); });
    await waitFor(() => expect(useConverterStore.getState().lutListFull.some((item) => item.name === newLut.name)).toBe(true));
    expect(useConverterStore.getState().lut_names).toEqual(["Brand A - A4"]);
    fireEvent.click(screen.getByRole("button", { name: "返回本地选择" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /Added LUT/ }));
    if (changeTask) {
      expect(screen.getByRole("button", { name: "确认" })).toBeDisabled();
      expect(screen.getByText(/当前图片或颜色模式已改变/)).toBeInTheDocument();
      expect(useConverterStore.getState().imageFile).toBe(nextImage);
    } else {
      fireEvent.click(screen.getByRole("button", { name: "确认" }));
      expect(useConverterStore.getState()).toMatchObject({ lut_names: ["Brand A - A4", "Brand A - Added"], imageFile, target_width_mm: 137 });
    }
  });
  it("keeps partial ZIP warnings visible when the source session expires", async () => {
    vi.useFakeTimers();
    vi.mocked(heartbeatSession).mockRejectedValueOnce({ response: { status: 404 } });
    useConverterStore.setState({
      sessionId: "partial-zip-expiry", downloadUrl: "/api/files/partial-zip",
      largeFormatWarnings: ["wipe_tower_manual_adjustment_required"],
      largeFormatFailedTiles: ["r2_c3"], generateWarnings: ["saved export warning"],
      imageFile: new File(["source"], "source.png", { type: "image/png" }), target_width_mm: 301,
    });
    function SettingsWithLease() {
      const sid = useConverterStore(state => state.sessionId);
      const expire = useConverterStore(state => state.expireSession);
      useSessionLease(sid, "converter", ["partial-zip"], expire);
      return <BasicSettings />;
    }
    const view = render(<SettingsWithLease />);
    expect(screen.getByText(/下载包缺少以下切片：r2_c3/)).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(useConverterStore.getState()).toMatchObject({
      sessionId: null, downloadUrl: "/api/files/partial-zip", target_width_mm: 301,
      largeFormatWarnings: ["wipe_tower_manual_adjustment_required"],
      largeFormatFailedTiles: ["r2_c3"], generateWarnings: ["saved export warning"],
    });
    expect(screen.getByText(/下载包缺少以下切片：r2_c3/)).toBeInTheDocument();
    expect(screen.getByText(/自动摆放未能确认模型/)).toBeInTheDocument();
    view.unmount();
  });

  it.each([
    [2, "宽度", "500", "250"],
    [0.5, "高度", "150", "300"],
  ])("keeps slider scales tied to the bed when aspect ratio is %s", (ratio, longEdgeLabel, width, height) => {
    useConverterStore.setState({
      aspectRatio: ratio as number,
      bedSizes: [
        { label: "Large", printer_id: "large", width_mm: 500, height_mm: 300, is_default: false },
      ],
    });
    useSettingsStore.getState().setPrinterModel("large");
    render(<BasicSettings />);

    const widthSlider = screen.getByRole("slider", { name: "宽度" });
    const heightSlider = screen.getByRole("slider", { name: "高度" });
    expect(widthSlider).toHaveAttribute("max", "500");
    expect(heightSlider).toHaveAttribute("max", "300");

    const longEdgeSlider = screen.getByRole("slider", { name: longEdgeLabel as string });
    fireEvent.change(longEdgeSlider, { target: { value: longEdgeSlider.getAttribute("max") } });
    expect(widthSlider).toHaveValue(width);
    expect(heightSlider).toHaveValue(height);

    const shortEdgeSlider = ratio === 2 ? heightSlider : widthSlider;
    expect(Number((shortEdgeSlider as HTMLInputElement).value)).toBeLessThan(Number(shortEdgeSlider.getAttribute("max")));
  });

  it("updates both dimension controls when the configured printer changes", () => {
    useConverterStore.setState({
      bedSizes: [
        { label: "Small", printer_id: "small", width_mm: 180, height_mm: 200, is_default: false },
        { label: "Large", printer_id: "large", width_mm: 500, height_mm: 300, is_default: false },
      ],
    });
    useSettingsStore.getState().setPrinterModel("small");
    render(<BasicSettings />);
    expect(screen.getByRole("slider", { name: "宽度" })).toHaveAttribute("max", "180");
    expect(screen.getByRole("slider", { name: "高度" })).toHaveAttribute("max", "200");

    act(() => useSettingsStore.getState().setPrinterModel("large"));
    expect(screen.getByRole("slider", { name: "宽度" })).toHaveAttribute("max", "500");
    expect(screen.getByRole("slider", { name: "高度" })).toHaveAttribute("max", "300");

    fireEvent.change(screen.getByRole("textbox", { name: "宽度 value" }), { target: { value: "600" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "宽度 value" }));
    expect(useConverterStore.getState().target_width_mm).toBe(500);
  });

  it("shows one decimal place without rounding the stored dimensions on focus or confirmation", () => {
    useConverterStore.setState({
      target_width_mm: 58.125,
      target_height_mm: 201.6666667,
    });

    render(<BasicSettings />);

    expect(
      screen.getByRole("slider", { name: "宽度" }),
    ).toHaveAttribute("step", "0.001");
    expect(
      screen.getByRole("textbox", { name: "宽度 value" }),
    ).toHaveValue("58.1");
    expect(
      screen.getByRole("slider", { name: "高度" }),
    ).toHaveAttribute("step", "0.001");
    expect(
      screen.getByRole("textbox", { name: "高度 value" }),
    ).toHaveValue("201.7");

    const widthInput = screen.getByRole("textbox", { name: "宽度 value" });
    const heightInput = screen.getByRole("textbox", { name: "高度 value" });
    fireEvent.focus(widthInput);
    fireEvent.blur(widthInput);
    fireEvent.focus(heightInput);
    fireEvent.keyDown(heightInput, { key: "Enter" });
    fireEvent.blur(heightInput);
    expect(useConverterStore.getState()).toMatchObject({
      target_width_mm: 58.125,
      target_height_mm: 201.6666667,
    });

    fireEvent.focus(widthInput);
    fireEvent.change(widthInput, { target: { value: "58.2" } });
    fireEvent.blur(widthInput);
    expect(useConverterStore.getState().target_width_mm).toBe(58.2);

    act(() => {
      useConverterStore.setState({
        target_width_mm: 80,
        target_height_mm: 80,
      });
    });

    expect(
      screen.getByRole("slider", { name: "宽度" }),
    ).toHaveAttribute("step", "1");
    expect(
      screen.getByRole("textbox", { name: "宽度 value" }),
    ).toHaveValue("80.0");
  });

  it("keeps large-format manual dimensions above the everyday slider range", () => {
    useConverterStore.setState({
      largeFormatEnabled: true,
      target_width_mm: 120,
      target_height_mm: 160,
      tileWidthMm: 200,
      tileHeightMm: 200,
    } as never);

    render(<BasicSettings />);

    expect(screen.getByRole("slider", { name: "宽度" })).toHaveAttribute("max", "256");
    expect(screen.getByRole("slider", { name: "高度" })).toHaveAttribute("max", "256");
    expect(screen.getByRole("slider", { name: "切片宽度" })).toHaveAttribute("max", "500");
    expect(screen.getByRole("slider", { name: "切片高度" })).toHaveAttribute("max", "500");

    const widthInput = screen.getByRole("textbox", { name: "宽度 value" });
    fireEvent.change(widthInput, { target: { value: "30000" } });
    fireEvent.blur(widthInput);

    expect(useConverterStore.getState().target_width_mm).toBe(30000);
    expect(widthInput).toHaveValue("30000.0");
  });

  it("offers a preview-only cut outline toggle in large-format mode", () => {
    useConverterStore.setState({
      largeFormatEnabled: false,
      largeFormatTileOverlayVisible: true,
    } as never);
    const { rerender } = render(<BasicSettings />);
    expect(
      screen.queryByRole("switch", { name: "在预览中显示切割轮廓" }),
    ).not.toBeInTheDocument();

    act(() => {
      useConverterStore.setState({
        largeFormatEnabled: true,
        target_width_mm: 600,
        target_height_mm: 400,
        tileWidthMm: 250,
        tileHeightMm: 250,
        previewPixelWidth: null,
        previewPixelHeight: null,
        downloadUrl: "/api/files/ready.zip",
      } as never);
    });
    rerender(<BasicSettings />);

    expect(screen.getByText("3×2 = 6 (100×150mm)")).toBeInTheDocument();
    const toggle = screen.getByRole("switch", { name: "在预览中显示切割轮廓" });
    expect(toggle).toBeChecked();

    fireEvent.click(toggle);

    const state = useConverterStore.getState();
    expect(state.largeFormatTileOverlayVisible).toBe(false);
    // Preview-only toggle must not invalidate an already generated download.
    expect(state.downloadUrl).toBe("/api/files/ready.zip");
  });

  it("counts large-format rows from the backend-derived height", () => {
    // SVG case: browser height 400 mm (2 rows) but the backend preview ratio
    // gives 520 mm, which generation actually splits into 3 rows.
    useConverterStore.setState({
      largeFormatEnabled: true,
      target_width_mm: 600,
      target_height_mm: 400,
      tileWidthMm: 250,
      tileHeightMm: 250,
      previewPixelWidth: 600,
      previewPixelHeight: 520,
    } as never);

    render(<BasicSettings />);

    expect(screen.getByText("3×3 = 9 (100×20mm)")).toBeInTheDocument();
  });

  it("accepts an empty LUT library as a successful read and guides the user to their first LUT", async () => {
    vi.useFakeTimers();
    vi.mocked(converterApi.fetchLutList).mockResolvedValue({ luts: [] });
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValue({ groups: [] });
    useConverterStore.setState({ source_version: "legacy", lut_name: "", lut_names: [], lutList: [],
      lutListFull: [], legacyCatalogGroups: [], selectedLegacyManufacturer: "" });
    try {
      render(<BasicSettings />);
      await act(async () => { await vi.advanceTimersByTimeAsync(6_000); });
      expect(screen.getByTestId("lut-picker-trigger")).toHaveTextContent("本地还没有 LUT，查找第一份");
      expect(converterApi.fetchLutList).toHaveBeenCalledTimes(1);
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenCalledTimes(1);
      fireEvent.click(screen.getByTestId("lut-picker-trigger"));
      expect(screen.getByRole("button", { name: "去云端找 LUT" })).toBeEnabled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("backs off failed startup LUT loads instead of retrying immediately", async () => {
    vi.useFakeTimers();
    vi.mocked(converterApi.fetchLutList)
      .mockRejectedValueOnce(new Error("backend offline"))
      .mockResolvedValue({
        luts: [
          {
            name: "Recovered LUT",
            color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
            path: "/recovered.npy",
          },
        ],
      });
    vi.mocked(lutApi.fetchLutDetailsCatalog)
      .mockRejectedValueOnce(new Error("backend offline"))
      .mockResolvedValue({ groups: makeLegacyCatalogGroups() });
    useConverterStore.setState({
      source_version: "legacy",
      lutList: [],
      lutListFull: [],
      lutListLoading: false,
      legacyCatalogGroups: [],
      legacyCatalogLoading: false,
    });

    try {
      render(<BasicSettings />);

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
        await Promise.resolve();
      });

      expect(converterApi.fetchLutList).toHaveBeenCalledTimes(1);
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenCalledTimes(1);
      expect(converterApi.fetchLutList).toHaveBeenNthCalledWith(1, {
        suppressClientLog: true,
      });
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenNthCalledWith(1, {
        suppressClientLog: true,
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4_000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(converterApi.fetchLutList).toHaveBeenCalledTimes(2);
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenCalledTimes(2);
      expect(converterApi.fetchLutList).toHaveBeenNthCalledWith(2, {
        suppressClientLog: true,
      });
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenNthCalledWith(2, {
        suppressClientLog: true,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops startup LUT retries after repeated backend failures", async () => {
    vi.useFakeTimers();
    vi.mocked(converterApi.fetchLutList).mockRejectedValue(
      new Error("backend offline"),
    );
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockRejectedValue(
      new Error("backend offline"),
    );
    useConverterStore.setState({
      source_version: "legacy",
      lutList: [],
      lutListFull: [],
      lutListLoading: false,
      legacyCatalogGroups: [],
      legacyCatalogLoading: false,
    });

    try {
      render(<BasicSettings />);

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(converterApi.fetchLutList).toHaveBeenCalledTimes(2);
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenCalledTimes(2);
      expect(converterApi.fetchLutList).toHaveBeenNthCalledWith(2, {
        suppressClientLog: true,
      });
      expect(lutApi.fetchLutDetailsCatalog).toHaveBeenNthCalledWith(2, {
        suppressClientLog: true,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  // Req 2.1: "批量模式" checkbox removed
  it("does NOT render the batch mode checkbox", () => {
    render(<BasicSettings />);
    expect(screen.queryByText("批量模式")).not.toBeInTheDocument();
  });

  it("opens cropping repeatedly without enabling crop after upload", () => {
    const file = new File(["img"], "edited.png", { type: "image/png" });
    useConverterStore.setState({
      imageFile: file,
      imagePreviewUrl: "blob:edited-image",
      enableCrop: false,
    });
    render(<BasicSettings />);

    expect(screen.getByText("导入", { exact: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "裁切与旋转" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByRole("img")).toHaveAttribute(
      "src", "blob:edited-image",
    );
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(useConverterStore.getState().imageFile).toBe(file);

    fireEvent.click(screen.getByRole("button", { name: "裁切与旋转" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(useConverterStore.getState().enableCrop).toBe(false);
    expect(useConverterStore.getState().imageFile).toBe(file);
  });

  it("previews a thumbnail while cropping keeps the source image", () => {
    const createdImages: HTMLImageElement[] = [];
    vi.stubGlobal("Image", function FakeImage() {
      const image = document.createElement("img");
      Object.defineProperty(image, "naturalWidth", { value: 6000 });
      Object.defineProperty(image, "naturalHeight", { value: 4000 });
      createdImages.push(image);
      return image;
    });
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: vi.fn(),
    } as never);
    const toBlob = vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => {
      callback(new Blob(["thumbnail"], { type: "image/png" }));
    });
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:thumbnail");

    try {
      useConverterStore.setState({
        imageFile: new File(["img"], "large.png", { type: "image/png" }),
        imagePreviewUrl: "blob:large-source",
        enableCrop: false,
      });
      render(<BasicSettings />);

      const sourceLoader = createdImages.find((image) => image.getAttribute("src") === "blob:large-source");
      act(() => sourceLoader?.onload?.(new Event("load")));

      expect(document.querySelector("[data-unified-uploader-drop-zone] img")).toHaveAttribute(
        "src", "blob:thumbnail",
      );

      fireEvent.click(screen.getByRole("button", { name: "裁切与旋转" }));
      expect(within(screen.getByRole("dialog")).getByRole("img")).toHaveAttribute(
        "src", "blob:large-source",
      );
    } finally {
      getContext.mockRestore();
      toBlob.mockRestore();
      createObjectURL.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it.each([
    { imagePreviewUrl: null, isLoading: false, isCropping: false },
    { imagePreviewUrl: "blob:image", isLoading: true, isCropping: false },
    { imagePreviewUrl: "blob:image", isLoading: false, isCropping: true },
  ])("disables cropping until the image is ready and idle: %o", (state) => {
    useConverterStore.setState({
      imageFile: new File(["img"], "photo.png", { type: "image/png" }),
      ...state,
    });
    render(<BasicSettings />);
    expect(screen.getByRole("button", { name: "裁切与旋转" })).toBeDisabled();
  });

  it("offers SVG rotation inside the tool without raster crop controls", () => {
    useConverterStore.setState({
      imageFile: new File(["<svg/>"], "drawing.svg", { type: "image/svg+xml" }),
      imagePreviewUrl: "blob:drawing",
    });
    render(<BasicSettings />);
    fireEvent.click(screen.getByRole("button", { name: "裁切与旋转" }));
    expect(screen.getByRole("button", { name: "向右旋转 90°" })).toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  // Req 3.2: crop checkbox visible in SingleMode
  it("renders crop checkbox in SingleMode (imageFile set, batchFiles empty)", () => {
    const file = new File(["img"], "test.jpg", { type: "image/jpeg" });
    useConverterStore.setState({
      imageFile: file,
      imagePreviewUrl: "data:image/jpeg;base64,fake",
      batchMode: false,
      batchFiles: [],
    });
    render(<BasicSettings />);
    expect(screen.getByText("上传后裁剪")).toBeInTheDocument();
  });

  // Req 4.4: crop checkbox hidden in BatchMode
  it("does NOT render crop checkbox in BatchMode (batchFiles has items)", () => {
    const files = [
      new File(["a"], "a.jpg", { type: "image/jpeg" }),
      new File(["b"], "b.png", { type: "image/png" }),
    ];
    useConverterStore.setState({
      imageFile: null,
      imagePreviewUrl: null,
      batchMode: true,
      batchFiles: files,
    });
    render(<BasicSettings />);
    expect(screen.queryByText("上传后裁剪")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "裁切与旋转" })).not.toBeInTheDocument();
  });

  // UnifiedUploader is rendered (present in both modes)
  it("renders UnifiedUploader in empty state", () => {
    render(<BasicSettings />);
    // UnifiedUploader shows the translated upload hint in empty state
    expect(
      screen.getByText("拖拽图片或 Lumina 项目文件"),
    ).toBeInTheDocument();
  });

  it("lets users enable crop after upload before choosing an image", () => {
    render(<BasicSettings />);
    fireEvent.click(screen.getByRole("switch", { name: "上传后裁剪" }));
    expect(useConverterStore.getState().enableCrop).toBe(true);
    expect(screen.queryByRole("button", { name: "裁切与旋转" })).not.toBeInTheDocument();
    expect(screen.queryByText("图像旋转")).not.toBeInTheDocument();
  });

  it("keeps structure and backing-infill controls visible but disabled in model texture mode", () => {
    useConverterStore.setState({
      structure_mode: StructureModeEnum.SINGLE_SIDED,
      modelSurfaceEnabled: true,
    } as never);

    render(<BasicSettings />);

    expect(useConverterStore.getState().structure_mode).toBe(
      StructureModeEnum.SINGLE_SIDED,
    );
    // The controls stay in place so the mode switch does not read as a
    // vanished feature; they are disabled and explain themselves instead.
    expect(screen.getByText("单面/双面打印")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "双面" })).toBeDisabled();
    expect(screen.getByRole("slider", { name: "底板填充率" })).toBeDisabled();
    expect(
      screen.getByText("模型覆面只生成单面结构，无法切换结构模式。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "模型覆面开启时由模型本身决定背衬，填充率不可调整。",
      ),
    ).toBeInTheDocument();
  });

  it("names every block of the column", () => {
    render(<BasicSettings />);

    for (const block of [
      "导入",
      "颜色设置",
      "尺寸和底板",
      "单面/双面打印",
      "建模模式",
    ]) {
      expect(screen.getByText(block)).toBeInTheDocument();
    }
  });

  it("lets users append one more image after a single image has a preview", async () => {
    const existingFile = new File(["existing"], "existing.jpg", { type: "image/jpeg" });
    const newFile = new File(["new"], "new.jpg", { type: "image/jpeg" });
    useConverterStore.setState({
      imageFile: existingFile,
      imagePreviewUrl: "data:image/jpeg;base64,fake",
      previewImageUrl: "/api/files/preview.png",
      batchMode: false,
      batchFiles: [],
    });

    render(<BasicSettings />);

    await waitFor(() => {
      expect(screen.getByText("点击更换或追加")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("点击更换或追加").closest("button")!);
    fireEvent.click(screen.getByText("添加更多图片"));

    const input = Array.from(
      document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
    ).find((candidate) => candidate.multiple);
    expect(input).toBeTruthy();
    fireEvent.change(input!, { target: { files: [newFile] } });

    await waitFor(() => {
      const state = useConverterStore.getState();
      expect(state.imageFile).toBeNull();
      expect(state.batchMode).toBe(true);
      expect(state.batchFiles).toEqual([existingFile, newFile]);
    });
    expect(screen.getByText("existing.jpg")).toBeInTheDocument();
    expect(screen.getByText("new.jpg")).toBeInTheDocument();
  });

  it("localizes large-format fallback warnings and shows the reason", () => {
    useConverterStore.setState({
      largeFormatEnabled: false,
      previewWarnings: [
        "Native vector large-format is unavailable for this SVG; large-format generation will fall back to raster tiling. Unsupported features: text.",
      ],
      largeFormatWarnings: [
        "Raster fallback was used for this large-format SVG request.",
        "Native vector generation failed; raster fallback was used for this large-format SVG request.",
      ],
    });

    render(<BasicSettings />);

    expect(
      screen.getByText("此 SVG 含有原生大画幅暂不支持的特性（text），已改用栅格切片。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("本次大画幅 SVG 已改用栅格切片。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("原生矢量切片生成失败，已自动改用栅格切片。"),
    ).toBeInTheDocument();
  });

  it("localizes embedded wipe-tower warnings returned by large-format generation", () => {
    useConverterStore.setState({
      largeFormatWarnings: ["wipe_tower_manual_adjustment_required"],
    });

    render(<BasicSettings />);

    expect(
      screen.getByText(/自动摆放未能确认模型、底边（brim）和擦料塔的安全位置/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("wipe_tower_manual_adjustment_required"),
    ).not.toBeInTheDocument();
  });

  it("renders the source version selector and legacy LUT database panel in old mode", () => {
    render(<BasicSettings />);

    expect(screen.getByText("色彩数据来源")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "经典 LUT" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "反推LUT" })).not.toBeInTheDocument();
    expect(screen.getByTestId("lut-picker-trigger")).toBeInTheDocument();
    expect(screen.getByText("选择LUT")).toBeInTheDocument();
  });
  it("lets a LUT user cancel a material trial without changing the current task", async () => {
    useConverterStore.setState({ lut_name: "Brand A - A4", lut_names: ["Brand A - A4"] });
    render(<BasicSettings />);
    fireEvent.click(screen.getByRole("button", { name: "试试耗材档案配色" }));
    fireEvent.click(screen.getByRole("button", { name: "查找我的耗材" }));
    await screen.findByTestId("material-picker-dialog");
    await waitFor(() => expect(extractorApi.listGradientCardMaterials).toHaveBeenCalled());
    expect(screen.getByTestId("material-picker-search-input")).toHaveValue("Brand A");
    fireEvent.click(within(screen.getByTestId("material-picker-dialog")).getByRole("button", { name: "关闭" }));
    expect(useConverterStore.getState()).toMatchObject({ source_version: "legacy", lut_names: ["Brand A - A4"] });
  });
  it("confirms a material trial before switching and previews the original image", async () => {
    const preview = vi.spyOn(useConverterStore.getState(), "submitPreview").mockResolvedValue();
    const file = new File(["image"], "image.png", { type: "image/png" });
    useConverterStore.setState({ imageFile: file, selectedMaterialDirNames: [] });
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({
      status: "success", message: "ok", materials: [{
        material_name: "Trial Red", directory_name: "trial/red", estimated_rgb: [200, 40, 40],
        brand: "Trial", material_type: "PLA", layer_height_mm: 0.08,
      } as SavedMaterialLibraryItem],
    });
    render(<BasicSettings />);
    fireEvent.click(screen.getByRole("button", { name: "试试耗材档案配色" }));
    fireEvent.click(screen.getByRole("button", { name: "查找我的耗材" }));
    fireEvent.click(await screen.findByRole("button", { name: "选择 Trial Red" }));
    expect(useConverterStore.getState().source_version).toBe("legacy");
    fireEvent.click(screen.getByRole("button", { name: "使用这些耗材预览" }));
    await waitFor(() => expect(preview).toHaveBeenCalledOnce());
    expect(useConverterStore.getState()).toMatchObject({ source_version: "material", imageFile: file, selectedMaterialDirNames: ["trial/red"] });
    expect(screen.queryByTestId("material-picker-dialog")).not.toBeInTheDocument();
  });

  it("keeps a Snapmaker LUT independent from the configured Bambu printer", async () => {
    const snapmakerGroup: LutDetailsCatalogGroup = {
      manufacturer: "snapmaker",
      items: [
        {
          name: "快造&4色PLA&RYBW",
          path: "lut-ref/snapmaker-rybw.npy",
          color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
          compatibility_key: "sig-snapmaker-rybw",
          source_kind: "legacy_lookup",
          manufacturer: "snapmaker",
          material_type: "PLA",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["snapmaker", "rybw"],
        },
      ],
    };
    vi.mocked(lutApi.fetchLutDetailsCatalog).mockResolvedValue({
      groups: [snapmakerGroup],
    });
    vi.mocked(converterApi.fetchLutList).mockResolvedValue({
      luts: [
        {
          name: "snapmaker - 快造&4色PLA&RYBW",
          color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
          path: "lut-ref/snapmaker-rybw.npy",
        },
      ],
    });
    useConverterStore.setState({
      legacyCatalogGroups: [snapmakerGroup],
      selectedLegacyManufacturer: "",
      bed_label: "Bambu Lab P1S",
      bedSizes: [
        {
          label: "Bambu Lab P1S",
          width_mm: 256,
          height_mm: 256,
          is_default: false,
          printer_id: "bambu-p1s",
        },
      ],
    });
    useSettingsStore.setState({ printerModel: "bambu-p1s" });

    render(
      <>
        <BasicSettings />
        <BedSizeSelector />
      </>,
    );

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    // Brand sidebar opens inside the dialog; click snapmaker brand
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "快造" }));

    await waitFor(() => {
      expect(useConverterStore.getState().selectedLegacyManufacturer)
        .toBe("snapmaker");
    });
    expect(useSettingsStore.getState().printerModel).toBe("bambu-p1s");
    expect(useConverterStore.getState().bed_label).toBe("Bambu Lab P1S");
    expect(screen.getAllByText("选择LUT").length).toBeGreaterThan(0);
    expect(screen.getByText("打印机热床")).toBeInTheDocument();
    expect(
      screen.getByText("Bambu Lab P1S · 256×256 毫米"),
    ).toBeInTheDocument();
  });

  it("shows the inferred white material as the base plate when no backing is persisted", async () => {
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValueOnce({
      status: "success",
      message: "ok",
      materials: [
        makeMaterial("brand/pla-green", "Green PLA"),
        makeMaterial("brand/pla-yellow", "Yellow PLA"),
        makeMaterial("brand/pla-white", "White PLA"),
      ],
    });
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: [
        "brand/pla-green",
        "brand/pla-yellow",
        "brand/pla-white",
      ],
      materialBackingMaterialDirName: null,
    });

    render(<BasicSettings />);

    const backingDropdown = screen.getByRole("combobox", { name: "底板耗材" });
    await waitFor(() => {
      expect(backingDropdown).toHaveTextContent("3. White PLA");
    });
  });

  it("shows fixed material layers by default and swaps to the dynamic range controls", () => {
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: ["brand/pla-white"],
      materialLayerCount: 7,
      materialDynamicLayerCountEnabled: false,
      materialMinLayerCount: 5,
      materialMaxLayerCount: 10,
    } as never);

    render(<BasicSettings />);

    const dynamicToggle = screen.getByRole("switch", {
      name: /动态调整有效叠层数/,
    });
    expect(dynamicToggle).not.toBeChecked();
    expect(screen.getByRole("slider", { name: "叠色层数" })).toHaveValue("7");
    // Locked to 10 layers until the advanced switch is turned on.
    expect(screen.getByRole("slider", { name: "叠色层数" })).toHaveAttribute(
      "max",
      "10",
    );
    act(() => useConverterStore.getState().setMaterialLayersUnlocked(true));
    expect(screen.getByRole("slider", { name: "叠色层数" })).toHaveAttribute(
      "max",
      "30",
    );
    act(() => useConverterStore.getState().setMaterialLayersUnlocked(false));
    expect(
      screen.queryByRole("slider", { name: "最小有效叠层数" }),
    ).not.toBeInTheDocument();
    // Cache management moved to Material > Solver Cache; both layer modes link there.
    expect(screen.getByTestId("material-cache-status-line")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "管理缓存" })).toBeInTheDocument();

    fireEvent.click(dynamicToggle);

    expect(useConverterStore.getState().materialDynamicLayerCountEnabled).toBe(
      true,
    );
    expect(
      screen.queryByRole("slider", { name: "叠色层数" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("slider", { name: "最小有效叠层数" }),
    ).toHaveAttribute("step", "1");
    expect(
      screen.getByRole("slider", { name: "最大有效叠层数" }),
    ).toHaveAttribute("max", "30");
    fireEvent.change(screen.getByRole("slider", { name: "最大有效叠层数" }), {
      target: { value: "30" },
    });
    expect(useConverterStore.getState()).toMatchObject({
      materialLayersUnlocked: false, materialMaxLayerCount: 30,
    });
    expect(screen.queryByText(/单一层数的缓存入口已隐藏/)).not.toBeInTheDocument();
    // The cache status line replaces the old "cache control is hidden" banner.
    expect(screen.getByRole("button", { name: "管理缓存" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "穷举缓存…" }),
    ).not.toBeInTheDocument();
  });

  it("couples dynamic material range controls in both edit directions", () => {
    useConverterStore.setState({
      source_version: "material",
      materialDynamicLayerCountEnabled: true,
      materialMinLayerCount: 5,
      materialMaxLayerCount: 7,
    } as never);

    render(<BasicSettings />);

    fireEvent.change(
      screen.getByRole("slider", { name: "最小有效叠层数" }),
      { target: { value: "9" } },
    );
    expect(useConverterStore.getState()).toMatchObject({
      materialMinLayerCount: 9,
      materialMaxLayerCount: 9,
    });

    fireEvent.change(
      screen.getByRole("slider", { name: "最大有效叠层数" }),
      { target: { value: "6" } },
    );
    expect(useConverterStore.getState()).toMatchObject({
      materialMinLayerCount: 6,
      materialMaxLayerCount: 6,
    });
  });

  it("does not expose dynamic material controls for non-material sources", () => {
    useConverterStore.setState({
      source_version: "legacy",
      materialDynamicLayerCountEnabled: true,
    } as never);

    render(<BasicSettings />);

    expect(
      screen.queryByRole("switch", { name: "动态调整有效叠层数" }),
    ).not.toBeInTheDocument();
  });

  it("lists every selected material with its color swatch", async () => {
    const names = ["White", "Red", "Blue", "Yellow", "Cyan", "Magenta", "Black", "Green"];
    const colors = [
      [250, 250, 250], [200, 30, 40], [20, 60, 200], [250, 220, 30],
      [0, 160, 220], [220, 0, 140], [10, 10, 10], [40, 160, 60],
    ];
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValueOnce({
      status: "success",
      message: "ok",
      materials: names.map((name, index) => ({
        ...makeMaterial(`Brand/${name}`, `Brand PLA ${name}`),
        estimated_rgb: colors[index],
      })),
    });
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: names.map((name) => `Brand/${name}`),
      materialBackingMaterialDirName: null,
    });

    render(<BasicSettings />);

    const list = await screen.findByTestId("material-picker-summary-list");
    await waitFor(() => expect(list).toHaveTextContent("Brand PLA Green"));
    // All eight are named (no "and N more"), each with its own swatch.
    for (const name of names) {
      expect(list).toHaveTextContent(`Brand PLA ${name}`);
    }
    const dots = screen.getByTestId("material-picker-summary-dots").children;
    expect(dots).toHaveLength(8);
    expect(dots[1]).toHaveStyle({ backgroundColor: "rgb(200, 30, 40)" });
  });

  it("opens the picker for the tour's picker steps and closes it afterwards", async () => {
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({
      status: "success",
      message: "ok",
      materials: [makeMaterial("JAYO/red-pla", "Red PLA")],
    });
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: [],
      materialBackingMaterialDirName: null,
    });
    const searchStep = TUTORIAL_STEPS.findIndex((step) => step.id === "picker-palette");
    const summaryStep = TUTORIAL_STEPS.findIndex((step) => step.id === "materials-summary");

    render(<BasicSettings />);
    expect(screen.queryByTestId("material-picker-dialog")).not.toBeInTheDocument();

    act(() => {
      useTutorialStore.setState({ phase: "touring", stepIndex: searchStep });
    });
    expect(await screen.findByTestId("material-picker-dialog")).toBeInTheDocument();

    act(() => {
      while (useTutorialStore.getState().stepIndex < summaryStep) useTutorialStore.getState().next();
    });
    await waitFor(() =>
      expect(screen.queryByTestId("material-picker-dialog")).not.toBeInTheDocument(),
    );
    act(() => {
      useTutorialStore.setState({ phase: "idle", stepIndex: 0 });
    });
  });

  it("keeps what the user selected in the picker when the tour moves on", async () => {
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({
      status: "success",
      message: "ok",
      materials: [makeMaterial("JAYO/red-pla", "Red PLA")],
    });
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: [],
      materialBackingMaterialDirName: null,
    });
    const paletteStep = TUTORIAL_STEPS.findIndex((step) => step.id === "picker-palette");
    const backingStep = TUTORIAL_STEPS.findIndex((step) => step.id === "materials-backing");

    render(<BasicSettings />);
    act(() => {
      useTutorialStore.setState({ phase: "touring", stepIndex: paletteStep });
    });
    const dialog = await screen.findByTestId("material-picker-dialog");
    fireEvent.click(await within(dialog).findByRole("button", { name: "选择 Red PLA" }));

    act(() => {
      while (useTutorialStore.getState().stepIndex < backingStep) useTutorialStore.getState().next();
    });
    await waitFor(() =>
      expect(screen.queryByTestId("material-picker-dialog")).not.toBeInTheDocument(),
    );
    expect(useConverterStore.getState().selectedMaterialDirNames).toEqual(["JAYO/red-pla"]);
    act(() => {
      useTutorialStore.setState({ phase: "idle", stepIndex: 0 });
    });
  });

  describe("leaving the interactive material tutorial", () => {
    function TutorialWorkspace() {
      const tab = useWidgetStore((state) => state.activeTab);
      const phase = useTutorialStore((state) => state.phase);
      return <>
        {tab === "converter" && <BasicSettings />}
        {phase === "touring" && <TutorialTour />}
      </>;
    }

    async function startMaterialTour(tab: "converter" | "settings", mixed = false) {
      vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValue({
        status: "success",
        message: "ok",
        materials: [
          { ...makeMaterial("review/red", "Red PLA"), material_type: "PLA" },
          ...(mixed ? [{ ...makeMaterial("review/black", "Black PETG"), material_type: "PETG" }] : []),
        ],
      });
      useConverterStore.setState({
        source_version: "material",
        selectedMaterialDirNames: [],
        materialBackingMaterialDirName: null,
      });
      useTutorialStore.setState({ phase: "idle", stepIndex: 0 });
      useWidgetStore.setState({ activeTab: tab, activeConverterSubTab: "core" });
      render(<TutorialWorkspace />);
      act(() => {
        useTutorialStore.getState().startTour("manual");
        const cardsStep = TUTORIAL_STEPS.findIndex((step) => step.id === "picker-cards");
        for (let i = 0; i < cardsStep; i += 1) useTutorialStore.getState().next();
      });
      fireEvent.click(await screen.findByRole("button", { name: "选择 Red PLA" }));
      if (mixed) fireEvent.click(screen.getByRole("button", { name: "选择 Black PETG" }));
      await screen.findByRole("button", { name: "跳过引导" });
    }

    it.each([
      ["converter", "skip"], ["settings", "skip"],
      ["converter", "escape"], ["settings", "escape"],
    ] as const)("keeps material edits when exiting via %s/%s", async (tab, exit) => {
      await startMaterialTour(tab);
      if (exit === "skip") fireEvent.click(screen.getByRole("button", { name: "跳过引导" }));
      else fireEvent.keyDown(document, { key: "Escape" });

      await waitFor(() => expect(useTutorialStore.getState().phase).toBe("idle"));
      expect(useConverterStore.getState().selectedMaterialDirNames).toEqual(["review/red"]);
      expect(useWidgetStore.getState().activeTab).toBe(tab);
      expect(screen.queryByTestId("material-picker-dialog")).not.toBeInTheDocument();
    });

    it.each(["skip", "done"] as const)("waits for mixed confirmation; cancel then %s follows the new action", async (nextAction) => {
      await startMaterialTour("settings", true);
      fireEvent.click(screen.getByRole("button", { name: "跳过引导" }));

      expect(await screen.findByRole("alertdialog", { name: "确认混合耗材类型？" })).toBeInTheDocument();
      expect(useTutorialStore.getState().phase).toBe("touring");
      expect(useWidgetStore.getState().activeTab).toBe("converter");
      expect(useConverterStore.getState().selectedMaterialDirNames).toEqual([]);

      fireEvent.click(screen.getByRole("button", { name: "返回调整" }));
      expect(useTutorialStore.getState().phase).toBe("touring");
      if (nextAction === "skip") {
        fireEvent.click(await screen.findByRole("button", { name: "跳过引导" }));
      } else {
        fireEvent.click(screen.getByRole("button", { name: "完成" }));
      }
      fireEvent.click(await screen.findByRole("button", { name: "仍然使用" }));

      await waitFor(() => expect(screen.queryByTestId("material-picker-dialog")).not.toBeInTheDocument());
      expect(useTutorialStore.getState().phase).toBe(nextAction === "skip" ? "idle" : "touring");
      expect(useWidgetStore.getState().activeTab).toBe(nextAction === "skip" ? "settings" : "converter");
      expect(useConverterStore.getState().selectedMaterialDirNames).toEqual(["review/red", "review/black"]);
    });
  });

  it("does not open the picker for the tour in Classic LUT mode", () => {
    useConverterStore.setState({ source_version: "legacy" });
    const searchStep = TUTORIAL_STEPS.findIndex((step) => step.id === "picker-palette");
    act(() => {
      useTutorialStore.setState({ phase: "touring", stepIndex: searchStep });
    });

    render(<BasicSettings />);

    expect(screen.queryByTestId("material-picker-dialog")).not.toBeInTheDocument();
    act(() => {
      useTutorialStore.setState({ phase: "idle", stepIndex: 0 });
    });
  });

  it("lets users retry a failed material-library load from the picker", async () => {
    vi.mocked(extractorApi.listGradientCardMaterials)
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({
        status: "success",
        message: "ok",
        materials: [makeMaterial("JAYO/red-pla", "Red PLA")],
      });
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: [],
      materialBackingMaterialDirName: null,
    });

    render(<BasicSettings />);

    await waitFor(() => {
      expect(extractorApi.listGradientCardMaterials).toHaveBeenCalledOnce();
    });
    fireEvent.click(screen.getByTestId("material-picker-trigger"));
    expect(
      await screen.findByTestId("material-picker-load-error"),
    ).toBeInTheDocument();

    fireEvent.click(within(screen.getByTestId("material-picker-load-error")).getByRole("button", { name: "重试" }));

    await waitFor(() => {
      expect(extractorApi.listGradientCardMaterials).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Red PLA")).toBeInTheDocument();
  });

  it("reconciles renamed material selections imported after the library loads", async () => {
    vi.mocked(extractorApi.listGradientCardMaterials).mockResolvedValueOnce({
      status: "success",
      message: "ok",
      materials: [makeMaterial("Karvax/Karvax PLA 耀石黑", "Karvax PLA 耀石黑")],
    });
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: [],
      materialBackingMaterialDirName: null,
    });

    render(<BasicSettings />);

    fireEvent.click(screen.getByTestId("material-picker-trigger"));
    await screen.findByRole("button", { name: /选择.*耀石黑/ });

    act(() => {
      useConverterStore.getState().importRecipeState(
        {
          source_version: "material",
          selectedMaterialDirNames: ["无境新材/无境新材 PLA 耀石黑"],
          materialBackingMaterialDirName: "无境新材/无境新材 PLA 耀石黑",
        },
        new File(["recipe"], "recipe.png", { type: "image/png" }),
      );
    });

    await waitFor(() => {
      expect(useConverterStore.getState().selectedMaterialDirNames).toEqual([
        "Karvax/Karvax PLA 耀石黑",
      ]);
      expect(useConverterStore.getState().materialBackingMaterialDirName).toBe(
        "Karvax/Karvax PLA 耀石黑",
      );
    });
  });

  it("shows brand options from the loaded legacy details catalog", () => {
    render(<BasicSettings />);

    // Open the picker dialog and check brand options in the sidebar
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Brand A" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Brand B" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "个人" })).toBeInTheDocument();
  });

  it("enables grouped LUT choices after selecting a legacy brand", async () => {
    render(<BasicSettings />);

    // Open picker dialog and select a brand from the sidebar
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Brand A" }));

    // Brand selection is immediate (sync store update)
    await waitFor(() => {
      expect(useConverterStore.getState().selectedLegacyManufacturer)
        .toBe("Brand A");
    });
    expect(useConverterStore.getState().legacyCatalogGroups).toHaveLength(3);

    // LUT options should now appear in the dialog
    await waitFor(() => {
      expect(within(dialog).getByText("A 4C")).toBeInTheDocument();
      expect(within(dialog).getByText("A 4C Alt")).toBeInTheDocument();
      expect(within(dialog).getByText("A 8C")).toBeInTheDocument();
    });

    const fourColor = within(dialog).getAllByRole("checkbox").find((el) => el.textContent?.includes("A 4C") && !el.textContent?.includes("Alt"));
    const eightColor = within(dialog).getAllByRole("checkbox").find((el) => el.textContent?.includes("A 8C"));
    expect(fourColor).toBeDefined();
    expect(eightColor).toBeDefined();

    fireEvent.click(fourColor!);
    fireEvent.click(eightColor!);
    // Different modes remain visible for browsing, but cannot be applied together.
    expect(within(dialog).getByRole("button", { name: "确认" })).toBeDisabled();
    expect(within(dialog).getByText(/颜色模式或通道不兼容/)).toBeInTheDocument();
    expect(useConverterStore.getState().lut_names).toEqual([]);
    fireEvent.click(eightColor!);
    fireEvent.click(within(dialog).getByRole("button", { name: "确认" }));
    expect(useConverterStore.getState().lut_names).toEqual(["Brand A - A4"]);
  });

  it("applies cross-brand LUTs together and leaves applied selection intact on cancel", async () => {
    // Cross-brand selection is valid when palette/channel compatibility matches.
    const groups = makeLegacyCatalogGroups();
    groups[1].items[0].color_mode = ColorModeEnum.FOUR_COLOR_RYBW;
    groups[1].items[0].compatibility_key = groups[0].items[0].compatibility_key;
    useConverterStore.setState({
      legacyCatalogGroups: groups,
      lutListFull: useConverterStore.getState().lutListFull.map((item) => item.name === "Brand B - BW" ? { ...item, color_mode: ColorModeEnum.FOUR_COLOR_RYBW } : item),
      lut_name: "Brand A - A4",
      lut_names: ["Brand A - A4"],
      selectedLegacyManufacturer: "Brand A",
      sessionId: "existing-preview",
    });
    render(<BasicSettings />);
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    let dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Brand B" }));
    expect(useConverterStore.getState().sessionId).toBe("existing-preview");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /B BW/ }));
    expect(useConverterStore.getState().lut_names).toEqual(["Brand A - A4"]);
    fireEvent.click(within(dialog).getByRole("button", { name: "确认" }));
    await waitFor(() => {
      expect(useConverterStore.getState().lut_names)
        .toEqual(["Brand A - A4", "Brand B - BW"]);
    });
    const trigger = screen.getByTestId("lut-picker-trigger");
    expect(trigger).toHaveTextContent("A 4C");
    expect(trigger).toHaveTextContent("已选 2 个 LUT");
    fireEvent.click(trigger);
    dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Brand B" }));
    expect(within(dialog).getByRole("checkbox", { name: /B BW/ }))
      .toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /B BW/ }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(useConverterStore.getState().lut_names)
      .toEqual(["Brand A - A4", "Brand B - BW"]);
  });

  it("submits the LUTManager name when a catalog LUT path maps to a shorter legacy LUT name", async () => {
    // Ensure clean slate so staged starts empty
    useConverterStore.setState({
      lut_name: "",
      lut_names: [],
      selectedLegacyManufacturer: "",
    } as never);

    render(<BasicSettings />);

    // Open picker dialog and select Brand A from sidebar
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Brand A" }));

    // Wait for A 4C option to appear (not Alt)
    await waitFor(() => {
      expect(within(dialog).getAllByRole("checkbox").some(
        (el) => el.textContent?.includes("A 4C") && !el.textContent?.includes("Alt"),
      )).toBe(true);
    });

    // Click only "A 4C" (not Alt); staged starts empty so this adds it
    const allCheckboxes = within(dialog).getAllByRole("checkbox");
    const fourColor = allCheckboxes.find(
      (el) => el.textContent?.includes("A 4C") && !el.textContent?.includes("Alt"),
    );
    expect(fourColor).toHaveAttribute("aria-checked", "false");
    fireEvent.click(fourColor!);
    expect(fourColor).toHaveAttribute("aria-checked", "true");

    fireEvent.click(within(dialog).getByRole("button", { name: "确认" }));

    await waitFor(() => {
      expect(useConverterStore.getState().lut_name).toBe("Brand A - A4");
    });
    expect(screen.getByTestId("lut-picker-trigger")).toHaveTextContent("A 4C");
  });

  it("hides LUT choices until LUTManager names are mapped", () => {
    useConverterStore.setState({
      selectedLegacyManufacturer: "Brand A",
      lutListFull: [],
      lutListLoading: true,
      lut_name: "",
    } as never);

    render(<BasicSettings />);

    // No LUT options shown on trigger (no chips)
    const trigger = screen.getByTestId("lut-picker-trigger");
    expect(trigger).not.toHaveTextContent("A 4C");
    // Open the dialog to confirm loading hint
    fireEvent.click(trigger);
    expect(screen.getByText("品牌目录加载中…")).toBeInTheDocument();
    expect(useConverterStore.getState().lut_name).toBe("");
  });

  it("syncs the legacy brand after a hydrated lut_name catalog fetch", async () => {
    useConverterStore.setState({
      legacyCatalogGroups: [],
      selectedLegacyManufacturer: "",
      lut_name: "Brand B - BW",
    } as never);

    render(<BasicSettings />);

    // Hydration still syncs the picker brand; the summary describes selected LUTs.
    await waitFor(() => {
      expect(useConverterStore.getState().selectedLegacyManufacturer).toBe("Brand B");
    });
  });

  it("blocks large format while model texture is enabled instead of showing a flat tile count", () => {
    useConverterStore.setState({
      modelSurfaceEnabled: true,
      largeFormatEnabled: false,
      target_width_mm: 60,
      target_height_mm: 30,
      tileWidthMm: 240,
      tileHeightMm: 240,
      previewPixelWidth: 9600,
      previewPixelHeight: 4800,
    } as never);

    const { rerender } = render(<BasicSettings />);

    expect(screen.getByRole("switch", { name: "大画幅模式" })).toBeDisabled();
    expect(screen.getByText("模型贴图开启时，大画幅模式会被禁用。")).toBeInTheDocument();

    // A restored or imported project can still carry both modes; the user must
    // see the conflict and be able to turn large format off again.
    act(() => {
      useConverterStore.setState({ largeFormatEnabled: true } as never);
    });
    rerender(<BasicSettings />);

    expect(screen.getByTestId("large-format-model-surface-conflict")).toHaveTextContent(
      "大画幅模式不支持模型贴图",
    );
    expect(screen.queryByText(/^\d+×\d+ = \d+/)).not.toBeInTheDocument();
    const toggle = screen.getByRole("switch", { name: "大画幅模式" });
    expect(toggle).toBeEnabled();
    fireEvent.click(toggle);
    expect(useConverterStore.getState().largeFormatEnabled).toBe(false);
    expect(useConverterStore.getState().modelSurfaceEnabled).toBe(true);
  });

  it("resets a restored native source without displaying predictive controls", async () => {
    const imageFile = new File(["image"], "kept.png", { type: "image/png" });
    useConverterStore.setState({
      source_version: "native",
      imageFile,
      lut_name: "A 4C",
      nativeBrandGroups: [makePredictiveBrand()],
      selectedNativeBrandKey: "bambulab_pla",
      selectedNativeDbNames: ["DB-B", "DB-C"],
      model_enable: true,
      model_only: true,
      color_layers: 5,
      layer_height_mm: 0.08,
    });

    render(<BasicSettings />);

    expect(screen.queryByRole("combobox", { name: "品牌" })).not.toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "模型辅助匹配" })).not.toBeInTheDocument();
    expect(screen.queryByText("DB-B")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(useConverterStore.getState()).toMatchObject({
        source_version: "legacy", lut_name: "", selectedNativeBrandKey: "",
        selectedNativeDbNames: [], model_enable: false, model_only: false,
      });
    });
    expect(useConverterStore.getState().imageFile).toBe(imageFile);
    expect(screen.getByTestId("lut-picker-trigger")).toBeInTheDocument();
  });

  it("clears predictive packages restored through the legacy LUT path", async () => {
    useConverterStore.setState({
      source_version: "legacy",
      lut_name: "A 4C",
      selectedLutInfo: {
        name: "A 4C", color_mode: "8-Color Max", color_count: 8,
        source_kind: "predictive_package", supports_dynamic_layer_count: true,
      },
    });

    render(<BasicSettings />);

    await waitFor(() => expect(useConverterStore.getState().lut_name).toBe(""));
    expect(screen.queryByText("叠色层数")).not.toBeInTheDocument();
  });

  it("anchors the thickness slider to the 0.08mm layer grid", () => {
    render(<BasicSettings />);

    const slider = screen.getByRole("slider", { name: "底板厚度" }) as HTMLInputElement;
    const min = Number(slider.min);
    const max = Number(slider.max);
    const step = Number(slider.step);

    expect(step).toBeCloseTo(0.08, 10);
    expect(isMultipleOfStep(min, step)).toBe(true);
    expect(isMultipleOfStep(max, step)).toBe(true);

    for (let value = min; value <= max + 1e-9; value = Number((value + step).toFixed(10))) {
      expect(isMultipleOfStep(value, step)).toBe(true);
    }
  });

  it("snaps manually entered thickness to the exported 0.08mm layer grid", async () => {
    render(<BasicSettings />);

    const input = screen.getByRole("textbox", { name: "底板厚度 value" });
    fireEvent.change(input, { target: { value: "0.3" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(useConverterStore.getState().spacer_thick).toBeCloseTo(0.32, 10);
    expect(useConverterStore.getState().base_spacer_thick).toBeCloseTo(0.32, 10);
    await waitFor(() => expect(input).toHaveValue("0.32"));

    fireEvent.change(input, { target: { value: "0.36" } });
    fireEvent.blur(input);

    expect(useConverterStore.getState().spacer_thick).toBeCloseTo(0.32, 10);
    expect(useConverterStore.getState().base_spacer_thick).toBeCloseTo(0.32, 10);
    await waitFor(() => expect(input).toHaveValue("0.32"));

    fireEvent.change(input, { target: { value: "1.88" } });
    fireEvent.blur(input);

    expect(useConverterStore.getState().spacer_thick).toBeCloseTo(1.84, 10);
    expect(useConverterStore.getState().base_spacer_thick).toBeCloseTo(1.84, 10);
    await waitFor(() => expect(input).toHaveValue("1.84"));

    fireEvent.change(input, { target: { value: "2.36" } });
    fireEvent.blur(input);

    expect(useConverterStore.getState().spacer_thick).toBeCloseTo(2.32, 10);
    expect(useConverterStore.getState().base_spacer_thick).toBeCloseTo(2.32, 10);
    await waitFor(() => expect(input).toHaveValue("2.32"));
  });

  it("disables structure and large-format controls while fridge mode is enabled", () => {
    useConverterStore.setState({
      enable_fridge_magnet: true,
      largeFormatEnabled: false,
      structure_mode: StructureModeEnum.SINGLE_SIDED,
    } as never);

    render(<BasicSettings />);

    expect(
      screen.getByRole("switch", { name: /大画幅模式/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("radio", { name: "单面" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("radio", { name: "双面" }),
    ).toBeDisabled();
  });
});
