import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import MaterialGamutPanel from "../components/materialWorkbench/MaterialGamutPanel";
import { listGradientCardMaterials } from "../api/extractor";
import {
  fetchMaterialGamutContributions,
  fetchMaterialGamutCoverage,
} from "../api/materialGamut";
import type {
  MaterialGamutAccuracy,
  MaterialGamutContributionsResponse,
  MaterialGamutCoverageResponse,
} from "../api/types";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { translations } from "../i18n/translations";
import { useMaterialWorkbenchStore } from "../stores/materialWorkbenchStore";

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

vi.mock("../components/LutDetailsPanel", () => ({
  LutColorDistributionCharts: () => <div data-testid="gamut-charts-stub" />,
}));

const INITIAL_WORKBENCH = useMaterialWorkbenchStore.getState();

const renderPanel = () => render(<MaterialGamutPanel />);

/** Expected zh text (the test setup renders every t() call in Chinese). */
const zh = (key: string, params: Record<string, string | number> = {}): string =>
  translations[key].zh.replace(/\{(\w+)\}/g, (_m, name: string) => String(params[name]));
const CALCULATE = () => screen.getByRole("button", { name: zh("material_gamut_calculate") });

const accuracy = (
  means: [number, number, number, number, number],
  darkest = 6,
  lightest = 89,
): MaterialGamutAccuracy => ({
  groups: (["all", "neutral", "dark", "skin", "vivid"] as const).map((group, index) => ({
    group,
    target_count: 100,
    mean_delta_e: means[index],
  })),
  darkest_lightness: darkest,
  lightest_lightness: lightest,
});

const coverage = (overrides: Partial<MaterialGamutCoverageResponse> = {}): MaterialGamutCoverageResponse => ({
  status: "ok",
  message: "ok",
  material_directory_names: ["red", "white"],
  layer_mode: "fixed",
  layer_count: 5,
  min_layer_count: null,
  layer_height_mm: 0.08,
  substrate: "white",
  backing_material_directory_name: null,
  cell_size_delta_e: 5,
  coverage: { reached_cell_count: 1940, reference_cell_count: 8392, percent: 23.12 },
  accuracy: accuracy([10, 3.26, 13.8, 2.4, 13.4]),
  color_count: 20795,
  source: { kind: "quick_sample", candidate_budget: 1_048_576, is_complete: false, was_cached: false },
  layer_cap_coverage: [],
  coverage_stats: {
    entry_count: 20795,
    plotted_point_count: 0,
    l_range: { min: 0, max: 0 },
    a_range: { min: 0, max: 0 },
    b_range: { min: 0, max: 0 },
    r_range: { min: 0, max: 0 },
    g_range: { min: 0, max: 0 },
    b_rgb_range: { min: 0, max: 0 },
  },
  lab_points: [],
  lab_points_3d: [],
  lab_hull: [],
  rgb_points: [],
  ...overrides,
});

const contributions: MaterialGamutContributionsResponse = {
  status: "ok",
  message: "ok",
  layer_count: 5,
  cell_size_delta_e: 5,
  baseline: { reached_cell_count: 1940, reference_cell_count: 8392, percent: 23.12 },
  baseline_accuracy: accuracy([10, 3.26, 13.8, 2.4, 13.4]),
  is_complete: false,
  items: [
    {
      directory_name: "white",
      material_name: "White PLA",
      coverage_without: { reached_cell_count: 1950, reference_cell_count: 8392, percent: 23.24 },
      drop_percent: -0.12,
      accuracy_without: accuracy([10.1, 3.5, 13.8, 2.6, 13.4]),
      largest_loss_group: "skin",
      largest_loss_delta_e: 0.2,
    },
    {
      directory_name: "black",
      material_name: "Black PLA",
      coverage_without: { reached_cell_count: 1300, reference_cell_count: 8392, percent: 15.1 },
      drop_percent: 8.02,
      accuracy_without: accuracy([15.7, 17.3, 34.6, 7.4, 16], 52.5),
      largest_loss_group: "dark",
      largest_loss_delta_e: 20.8,
    },
  ],
};

describe("MaterialGamutPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
    useMaterialWorkbenchStore.setState(INITIAL_WORKBENCH, true);
    useMaterialWorkbenchStore.getState().applySelection({
      materialDirectoryNames: ["red", "white"],
      layerMode: "fixed",
      layerCount: 5,
      minLayerCount: 5,
      maxLayerCount: 10,
      layerHeightMm: 0.08,
      substrate: "white",
      backingDirName: null,
    });
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "ok",
      materials: [],
    });
  });

  it("shows an empty state until coverage is calculated", () => {
    renderPanel();

    expect(screen.getByTestId("material-gamut-empty-state")).toBeInTheDocument();
    expect(fetchMaterialGamutCoverage).not.toHaveBeenCalled();
  });

  it("calculates coverage and accuracy, then ranks materials by their largest accuracy loss", async () => {
    vi.mocked(fetchMaterialGamutCoverage).mockResolvedValue(coverage());
    vi.mocked(fetchMaterialGamutContributions).mockResolvedValue(contributions);
    renderPanel();

    fireEvent.click(CALCULATE());

    expect(await screen.findByTestId("material-gamut-percent")).toHaveTextContent("23.1%");
    expect(screen.getByTestId("material-gamut-exactness")).toHaveTextContent(zh("material_gamut_estimated_badge"));
    expect(screen.getByTestId("material-gamut-source")).toHaveTextContent(
      zh("material_gamut_source_quick_sample", { budget: "1M" }),
    );
    expect(fetchMaterialGamutCoverage).toHaveBeenCalledWith(
      expect.objectContaining({ materialDirectoryNames: ["red", "white"], layerMode: "fixed" }),
      expect.objectContaining({ maxPoints: 8000 }),
    );

    const unit = zh("material_gamut_delta_e_unit");
    const far = zh("quick_replace_delta_e_far");
    const near = zh("quick_replace_delta_e_near");
    const groups = screen.getAllByTestId("material-gamut-accuracy-group");
    expect(groups.map((row) => row.textContent)).toEqual([
      `${zh("material_gamut_group_all")}10.0${unit}${far}`,
      `${zh("material_gamut_group_neutral")}3.3${unit}${near}`,
      `${zh("material_gamut_group_dark")}13.8${unit}${far}`,
      `${zh("material_gamut_group_skin")}2.4${unit}${near}`,
      `${zh("material_gamut_group_vivid")}13.4${unit}${far}`,
    ]);
    expect(screen.getByTestId("material-gamut-lightness-range")).toHaveTextContent(
      zh("material_gamut_lightness_range", { darkest: "6", lightest: "89" }),
    );

    const cellTexts = (row: HTMLElement) =>
      Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent);
    const dash = zh("material_gamut_contrib_no_change");
    expect(cellTexts(await screen.findByTestId("material-gamut-contribution-baseline"))).toEqual([
      zh("material_gamut_contrib_baseline"), "3.3", "13.8", "2.4", "13.4", "6", "23.1%",
    ]);
    const items = screen.getAllByTestId("material-gamut-contribution-item");
    expect(cellTexts(items[0])).toEqual(["Black PLA", "+14.0", "+20.8", "+5.0", "+2.6", "+47", "−8.0"]);
    expect(cellTexts(items[1])).toEqual(["White PLA", dash, dash, dash, dash, dash, dash]);
    expect(screen.getByTestId("material-gamut-contrib-exactness")).toHaveTextContent(
      zh("material_gamut_estimated_badge"),
    );
    expect(screen.getByTestId("gamut-charts-stub")).toBeInTheDocument();
  });

  it("explains the dynamic per-layer coverage bars", async () => {
    useMaterialWorkbenchStore.getState().setLayerMode("dynamic");
    vi.mocked(fetchMaterialGamutCoverage).mockResolvedValue(
      coverage({
        layer_mode: "dynamic",
        source: { kind: "dynamic_catalog", candidate_budget: 1_048_576, is_complete: true, was_cached: true },
        layer_cap_coverage: [
          { layer_count: 5, coverage: { reached_cell_count: 1, reference_cell_count: 10, percent: 10 } },
          { layer_count: 6, coverage: { reached_cell_count: 2, reference_cell_count: 10, percent: 20 } },
        ],
      }),
    );
    vi.mocked(fetchMaterialGamutContributions).mockResolvedValue(contributions);
    renderPanel();

    fireEvent.click(CALCULATE());

    const bars = await screen.findAllByTestId("material-gamut-layer-cap");
    expect(bars.map((bar) => bar.textContent)).toEqual([
      `${zh("material_gamut_layer_cap_label", { count: 5 })}10.0%`,
      `${zh("material_gamut_layer_cap_label", { count: 6 })}20.0%`,
    ]);
    expect(screen.getByText(zh("material_gamut_layer_caps_header"))).toBeInTheDocument();
    expect(screen.getByText(zh("material_gamut_layer_caps_description"))).toBeInTheDocument();
    expect(screen.getByTestId("material-gamut-exactness")).toHaveTextContent(zh("material_gamut_exact_badge"));
    expect(screen.getByTestId("material-gamut-exactness")).toHaveAttribute("title", zh("material_gamut_exact_tooltip"));
  });

  it("warns that results are stale after the combination changes", async () => {
    vi.mocked(fetchMaterialGamutCoverage).mockResolvedValue(coverage());
    vi.mocked(fetchMaterialGamutContributions).mockResolvedValue(contributions);
    renderPanel();
    fireEvent.click(CALCULATE());
    await screen.findByTestId("material-gamut-percent");

    useMaterialWorkbenchStore.getState().setLayerCount(8);

    expect(await screen.findByText(zh("material_gamut_stale_hint"))).toBeInTheDocument();
  });

  it("reports a failed calculation without showing old results as new", async () => {
    vi.mocked(fetchMaterialGamutCoverage).mockRejectedValue(new Error("boom"));
    renderPanel();

    fireEvent.click(CALCULATE());

    expect(await screen.findByTestId("material-gamut-error")).toHaveTextContent(
      zh("material_gamut_failed", { message: "" }).trim(),
    );
    expect(fetchMaterialGamutContributions).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(CALCULATE()).not.toBeDisabled(),
    );
  });

  it("clears an aborted contribution's loading state when recalculation fails", async () => {
    vi.mocked(fetchMaterialGamutCoverage)
      .mockResolvedValueOnce(coverage())
      .mockRejectedValueOnce(new Error("second calculation failed"));
    vi.mocked(fetchMaterialGamutContributions).mockReturnValueOnce(new Promise(() => {}));
    renderPanel();
    fireEvent.click(CALCULATE());
    await screen.findByText(zh("material_gamut_contrib_loading"));

    fireEvent.click(CALCULATE());

    await screen.findByTestId("material-gamut-error");
    expect(screen.queryByText(zh("material_gamut_contrib_loading"))).not.toBeInTheDocument();
  });
});
