import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import MaterialCachePanel from "../components/materialWorkbench/MaterialCachePanel";
import MaterialCacheStatusLine from "../components/materialWorkbench/MaterialCacheStatusLine";
import { listGradientCardMaterials } from "../api/extractor";
import {
  fetchMaterialSolverCacheStatus,
  fetchMaterialSolverRuntimeStatus,
} from "../api/materialCache";
import {
  deleteMaterialDynamicCache,
  fetchMaterialCacheOverview,
  prepareMaterialDynamicCache,
} from "../api/materialGamut";
import type { MaterialDynamicCacheOverview } from "../api/types";
import { translations } from "../i18n/translations";
import { useConverterStore } from "../stores/converter";
import { useMaterialWorkbenchStore } from "../stores/materialWorkbenchStore";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { useWidgetStore } from "../stores/widgetStore";

vi.mock("../api/extractor", () => ({
  colorcheckerConfirm: vi.fn(),
  colorcheckerRelease: vi.fn(),
  colorcheckerTouch: vi.fn(() => Promise.resolve()),
  listGradientCardMaterials: vi.fn(),
}));

vi.mock("../api/materialGamut", () => ({
  fetchMaterialGamutCoverage: vi.fn(),
  fetchMaterialGamutContributions: vi.fn(),
  fetchMaterialCacheOverview: vi.fn(),
  prepareMaterialDynamicCache: vi.fn(),
  deleteMaterialDynamicCache: vi.fn(),
}));

vi.mock("../api/materialCache", () => ({
  buildMaterialSolverCache: vi.fn(),
  buildMaterialSolverRuntime: vi.fn(),
  DEFAULT_MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGET: 33_554_432,
  deleteMaterialSolverCache: vi.fn(),
  deleteMaterialSolverRuntime: vi.fn(),
  fetchMaterialSolverCacheDetails: vi.fn(),
  fetchMaterialSolverCacheStatus: vi.fn(),
  fetchMaterialSolverRuntimeDetails: vi.fn(),
  fetchMaterialSolverRuntimeStatus: vi.fn(),
  MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGETS: [1_048_576, 4_194_304, 8_388_608, 33_554_432, 67_108_864],
}));

vi.mock("../components/LutDetailsPanel", () => ({
  LutColorDistributionCharts: () => null,
}));

const zh = (key: string, params: Record<string, string | number> = {}): string =>
  translations[key].zh.replace(/\{(\w+)\}/g, (_m, name: string) => String(params[name]));

const INITIAL_WORKBENCH = useMaterialWorkbenchStore.getState();

const dynamicOverview = (
  overrides: Partial<MaterialDynamicCacheOverview> = {},
): MaterialDynamicCacheOverview => ({
  candidate_budget: 1_048_576,
  is_ready: false,
  catalog: null,
  saved_layer_counts: [],
  missing_layer_counts: [5, 6],
  prepared_layer_counts: [],
  ...overrides,
});

const READY_OVERVIEW = dynamicOverview({
  is_ready: true,
  catalog: { size_bytes: 3 * 1024 * 1024, modified_at: "2026-10-11T08:00:00Z" },
  saved_layer_counts: [5, 6],
  prepared_layer_counts: [5, 6],
  missing_layer_counts: [],
});

function selectCombo(layerMode: "fixed" | "dynamic", substrate: "white" | "black" = "white") {
  useMaterialWorkbenchStore.getState().applySelection({
    materialDirectoryNames: ["red", "white"],
    layerMode,
    layerCount: 5,
    minLayerCount: 5,
    maxLayerCount: 6,
    layerHeightMm: 0.08,
    substrate,
    backingDirName: "white",
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
  useMaterialWorkbenchStore.setState(INITIAL_WORKBENCH, true);
  useConverterStore.setState({ isLoading: false });
  vi.mocked(listGradientCardMaterials).mockResolvedValue({ status: "ok", message: "ok", materials: [] });
});

describe("MaterialCachePanel", () => {
  it("prepares the dynamic layer cache and shows it as ready", async () => {
    selectCombo("dynamic");
    vi.mocked(fetchMaterialCacheOverview).mockResolvedValue({
      status: "ok",
      message: "ok",
      layer_mode: "dynamic",
      fixed: null,
      dynamic: dynamicOverview(),
    });
    vi.mocked(prepareMaterialDynamicCache).mockResolvedValue({
      status: "ok",
      message: "ok",
      built: true,
      elapsed_seconds: 12.34,
      dynamic: READY_OVERVIEW,
    });
    render(<MaterialCachePanel />);

    const status = screen.getByTestId("dynamic-layer-cache-status");
    await waitFor(() => expect(status).toHaveTextContent(zh("material_cache_dynamic_status_missing")));
    expect(screen.getByTestId("dynamic-layer-cache-layers")).toHaveTextContent(
      zh("material_cache_dynamic_layers_value", { saved: 0, total: 2 }),
    );

    fireEvent.click(screen.getByRole("button", { name: zh("material_cache_dynamic_prepare_button") }));

    expect(await screen.findByText(zh("material_cache_dynamic_prepared", { seconds: "12.3" }))).toBeInTheDocument();
    expect(status).toHaveTextContent(zh("material_cache_dynamic_status_ready"));
    expect(prepareMaterialDynamicCache).toHaveBeenCalledWith(
      expect.objectContaining({ layerMode: "dynamic", minLayerCount: 5, maxLayerCount: 6, backingDirName: "white" }),
    );
  });

  it("deletes the prepared cache after confirmation and refreshes the status", async () => {
    selectCombo("dynamic");
    vi.mocked(fetchMaterialCacheOverview)
      .mockResolvedValueOnce({ status: "ok", message: "ok", layer_mode: "dynamic", fixed: null, dynamic: READY_OVERVIEW })
      .mockResolvedValueOnce({
        status: "ok",
        message: "ok",
        layer_mode: "dynamic",
        fixed: null,
        dynamic: dynamicOverview(),
      });
    vi.mocked(deleteMaterialDynamicCache).mockResolvedValue({ status: "ok", message: "ok", deleted: true });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<MaterialCachePanel />);

    fireEvent.click(await screen.findByRole("button", { name: zh("material_cache_dynamic_delete_button") }));

    await waitFor(() =>
      expect(screen.getByTestId("dynamic-layer-cache-status")).toHaveTextContent(
        zh("material_cache_dynamic_status_missing"),
      ),
    );
    expect(deleteMaterialDynamicCache).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("dynamic-layer-cache-layers")).toHaveTextContent(
      zh("material_cache_dynamic_layers_value", { saved: 0, total: 2 }),
    );
  });

  it("explains that saved per-layer candidates make a re-merge fast", async () => {
    selectCombo("dynamic");
    vi.mocked(fetchMaterialCacheOverview).mockResolvedValue({
      status: "ok",
      message: "ok",
      layer_mode: "dynamic",
      fixed: null,
      dynamic: dynamicOverview({ saved_layer_counts: [5, 6], prepared_layer_counts: [5, 6], missing_layer_counts: [] }),
    });
    render(<MaterialCachePanel />);

    expect(
      await screen.findByText(zh("material_cache_dynamic_partial_hint", { saved: 2 })),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: zh("material_cache_dynamic_delete_button") })).toBeEnabled();
  });

  it("clears the old catalog when another combination's overview fails", async () => {
    selectCombo("dynamic");
    vi.mocked(fetchMaterialCacheOverview)
      .mockResolvedValueOnce({ status: "ok", message: "ok", layer_mode: "dynamic", fixed: null, dynamic: READY_OVERVIEW })
      .mockRejectedValueOnce(new Error("offline"));
    render(<MaterialCachePanel />);
    await screen.findByRole("button", { name: zh("material_cache_dynamic_delete_button") });

    act(() => useMaterialWorkbenchStore.getState().setMaxLayerCount(7));

    await waitFor(() => expect(screen.getByTestId("dynamic-layer-cache-status")).toHaveTextContent(zh("material_cache_dynamic_status_error")));
    expect(screen.queryByTestId("dynamic-layer-cache-layers")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: zh("material_cache_dynamic_delete_button") })).not.toBeInTheDocument();
  });

  it("does not offer deletion when only manual smart caches are reusable", async () => {
    selectCombo("dynamic");
    vi.mocked(fetchMaterialCacheOverview).mockResolvedValue({
      status: "ok", message: "ok", layer_mode: "dynamic", fixed: null,
      dynamic: dynamicOverview({ saved_layer_counts: [5, 6], missing_layer_counts: [] }),
    });
    render(<MaterialCachePanel />);
    await screen.findByTestId("dynamic-layer-cache-layers");
    expect(screen.queryByRole("button", { name: zh("material_cache_dynamic_delete_button") })).not.toBeInTheDocument();
  });

  it("keeps a successful delete separate from a failed status refresh", async () => {
    selectCombo("dynamic");
    vi.mocked(fetchMaterialCacheOverview)
      .mockResolvedValueOnce({ status: "ok", message: "ok", layer_mode: "dynamic", fixed: null, dynamic: READY_OVERVIEW })
      .mockRejectedValueOnce(new Error("refresh failed"));
    vi.mocked(deleteMaterialDynamicCache).mockResolvedValue({ status: "ok", message: "ok", deleted: true });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<MaterialCachePanel />);
    fireEvent.click(await screen.findByRole("button", { name: zh("material_cache_dynamic_delete_button") }));

    expect(await screen.findByText(zh("material_cache_dynamic_deleted"))).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("dynamic-layer-cache-status")).toHaveTextContent(zh("material_cache_dynamic_status_error")));
    expect(screen.queryByText(zh("material_cache_dynamic_failed"))).not.toBeInTheDocument();
    expect(screen.queryByTestId("dynamic-layer-cache-layers")).not.toBeInTheDocument();
  });

  it("ignores an old preparation failure after the combination changes", async () => {
    selectCombo("dynamic");
    vi.mocked(fetchMaterialCacheOverview).mockResolvedValue({
      status: "ok", message: "ok", layer_mode: "dynamic", fixed: null, dynamic: dynamicOverview(),
    });
    let rejectPreparation!: (error: Error) => void;
    vi.mocked(prepareMaterialDynamicCache).mockReturnValueOnce(new Promise((_, reject) => {
      rejectPreparation = reject;
    }));
    render(<MaterialCachePanel />);
    const prepare = () => screen.getByRole("button", { name: zh("material_cache_dynamic_prepare_button") });
    await waitFor(() => expect(prepare()).toBeEnabled());
    fireEvent.click(prepare());
    act(() => useMaterialWorkbenchStore.getState().setMaxLayerCount(7));
    await waitFor(() => expect(prepare()).toBeEnabled());

    await act(async () => { rejectPreparation(new Error("old failure")); });

    expect(screen.queryByText(zh("material_cache_dynamic_failed"))).not.toBeInTheDocument();
    expect(prepare()).toBeEnabled();
  });

  it("always manages white-substrate caches, even if black was chosen on the gamut tab", async () => {
    selectCombo("dynamic", "black");
    vi.mocked(fetchMaterialCacheOverview).mockResolvedValue({
      status: "ok", message: "ok", layer_mode: "dynamic", fixed: null, dynamic: dynamicOverview(),
    });
    render(<MaterialCachePanel />);

    await waitFor(() =>
      expect(fetchMaterialCacheOverview).toHaveBeenCalledWith(
        expect.objectContaining({ substrate: "white" }),
        expect.anything(),
      ),
    );
    expect(screen.queryByText(zh("material_recipe_substrate_label"))).not.toBeInTheDocument();
    expect(useMaterialWorkbenchStore.getState().substrate).toBe("black");
  });

  it("shows the existing exhaustive and smart cache card in fixed mode", async () => {
    selectCombo("fixed");
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok", message: "", cached: false, palette_hash: "x", layer_count: 5,
      layer_height_mm: 0.08, substrate: "white", entry: null,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok", message: "", cached: false, palette_hash: "x", layer_count: 5,
      layer_height_mm: 0.08, substrate: "white", candidate_budget: 33_554_432, entry: null,
    });
    render(<MaterialCachePanel />);

    expect(screen.getByTestId("material-solver-cache-status-card")).toBeInTheDocument();
    expect(screen.queryByTestId("dynamic-layer-cache-card")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledWith(
        expect.objectContaining({ materialDirectoryNames: ["red", "white"], layerCount: 5 }),
        expect.anything(),
      ),
    );
  });
});

describe("MaterialCacheStatusLine", () => {
  it("refreshes readiness after conversion finishes without changing the combination", async () => {
    useConverterStore.setState({ selectedMaterialDirNames: ["red", "white"], materialDynamicLayerCountEnabled: true, isLoading: false });
    vi.mocked(fetchMaterialCacheOverview)
      .mockResolvedValueOnce({ status: "ok", message: "ok", layer_mode: "dynamic", fixed: null, dynamic: dynamicOverview() })
      .mockResolvedValueOnce({ status: "ok", message: "ok", layer_mode: "dynamic", fixed: null, dynamic: READY_OVERVIEW });
    render(<MaterialCacheStatusLine />);
    await screen.findByText(zh("basic_material_cache_status_line_dynamic_missing"));

    act(() => useConverterStore.setState({ isLoading: true }));
    act(() => useConverterStore.setState({ isLoading: false }));

    expect(await screen.findByText(zh("basic_material_cache_status_line_dynamic_ready"))).toBeInTheDocument();
    expect(fetchMaterialCacheOverview).toHaveBeenCalledTimes(2);
  });
  it("summarizes the converter's cache state and opens the cache tab with its combination", async () => {
    useConverterStore.setState({
      selectedMaterialDirNames: ["red", "white"],
      materialDynamicLayerCountEnabled: true,
      materialMinLayerCount: 6,
      materialMaxLayerCount: 8,
      materialLayerHeightMm: 0.08,
      materialBackingMaterialDirName: "white",
    });
    vi.mocked(fetchMaterialCacheOverview).mockResolvedValue({
      status: "ok", message: "ok", layer_mode: "dynamic", fixed: null, dynamic: dynamicOverview(),
    });
    render(<MaterialCacheStatusLine />);

    expect(await screen.findByText(zh("basic_material_cache_status_line_dynamic_missing"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: zh("basic_material_cache_manage_button") }));

    expect(useWidgetStore.getState().activeTab).toBe("material-cache");
    const workbench = useMaterialWorkbenchStore.getState();
    expect(workbench.materialDirectoryNames).toEqual(["red", "white"]);
    expect([workbench.layerMode, workbench.minLayerCount, workbench.maxLayerCount]).toEqual(["dynamic", 6, 8]);
  });

  it("renders nothing until materials are selected", () => {
    useConverterStore.setState({ selectedMaterialDirNames: [] });
    const { container } = render(<MaterialCacheStatusLine />);

    expect(container).toBeEmptyDOMElement();
    expect(fetchMaterialCacheOverview).not.toHaveBeenCalled();
  });
});
