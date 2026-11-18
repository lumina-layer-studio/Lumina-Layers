import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MaterialSolverCacheStatusCard from "../components/MaterialSolverCacheStatusCard";
import { translations } from "../i18n/translations";
import {
  buildMaterialSolverCache,
  buildMaterialSolverRuntime,
  deleteMaterialSolverCache,
  deleteMaterialSolverRuntime,
  fetchMaterialSolverCacheDetails,
  fetchMaterialSolverCacheStatus,
  fetchMaterialSolverRuntimeDetails,
  fetchMaterialSolverRuntimeStatus,
} from "../api/materialCache";
import type {
  MaterialSolverCacheEntry,
  MaterialSolverRuntimeEntry,
} from "../api/types";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

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
  MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGETS: [
    1_048_576,
    4_194_304,
    8_388_608,
    33_554_432,
    67_108_864,
  ],
}));

function buildCacheEntry(
  overrides: Partial<MaterialSolverCacheEntry> = {},
): MaterialSolverCacheEntry {
  return {
    palette_hash: "0123456789abcdef",
    material_directory_names: ["red", "white"],
    layer_count: 5,
    layer_height_mm: 0.08,
    substrate: "white",
    grid_resolution: 64,
    total_combinations: 243,
    valid_cell_count: 178,
    total_cell_count: 262144,
    mean_delta_e: 1.23,
    max_delta_e: 4.56,
    build_time_seconds: 12.5,
    built_at: "2026-04-17T04:00:00Z",
    cache_file_size_bytes: 3_145_728,
    ...overrides,
  };
}

function buildRuntimeEntry(
  overrides: Partial<MaterialSolverRuntimeEntry> = {},
): MaterialSolverRuntimeEntry {
  return {
    palette_hash: "0123456789abcdef",
    material_directory_names: ["red", "white"],
    layer_count: 8,
    layer_height_mm: 0.04,
    substrate: "white",
    mode: "candidate_hybrid",
    candidate_budget: 33_554_432,
    candidate_count: 33_554_432,
    candidate_pool_multiplier: 2,
    batch_recipe_count: 524_288,
    lab_grid_resolution: 64,
    seed: 0,
    inverse_refinement_enabled: true,
    built_at: "2026-06-07T04:00:00Z",
    cache_file_size_bytes: 268_435_456,
    ...overrides,
  };
}

function buildRuntimeDetailsResponse() {
  const range = { min: 0, max: 1 };
  const point = {
    x: 0,
    y: 0,
    hex_color: "#010203",
    rgb: [1, 2, 3] as [number, number, number],
    label: "1",
  };
  return {
    status: "ok",
    message: "Runtime details",
    palette_hash: "0123456789abcdef",
    material_directory_names: ["red", "white"],
    layer_count: 8,
    layer_height_mm: 0.04,
    substrate: "white",
    grid_resolution: 64,
    valid_cell_count: 1,
    total_cell_count: 33_554_432,
    candidate_budget: 33_554_432,
    candidate_count: 33_554_432,
    coverage_stats: {
      entry_count: 1,
      plotted_point_count: 1,
      l_range: range,
      a_range: range,
      b_range: range,
      r_range: range,
      g_range: range,
      b_rgb_range: range,
    },
    lab_points: [point],
    lab_points_3d: [
      {
        l: 10,
        a: 0,
        b: 0,
        hex_color: "#010203",
        rgb: [1, 2, 3] as [number, number, number],
        label: "1",
      },
    ],
    lab_hull: [],
    rgb_points: [point],
  };
}

function expectRawMaterialCacheErrorsHidden() {
  expect(screen.queryByText(/network down/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/Request failed with status code/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/status code 422/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/status code 500/i)).not.toBeInTheDocument();
}

describe("MaterialSolverCacheStatusCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset the opt-in settings so each test starts from the shipped default
    // (switch off, low-tier 64) unless it flips the toggle explicitly.
    useSettingsStore.setState({
      enableSolverCacheGridSelection:
        DEFAULT_SETTINGS.enableSolverCacheGridSelection,
      solverCacheGridResolution: DEFAULT_SETTINGS.solverCacheGridResolution,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok",
      message: "No runtime found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      candidate_budget: 33_554_432,
      entry: null,
    });
    vi.mocked(fetchMaterialSolverRuntimeDetails).mockResolvedValue(
      buildRuntimeDetailsResponse(),
    );
  });

  it.each([{ cached: false, layers: 11 }, { cached: true, layers: 30 }])(
    "disables exhaustive build at $layers layers while keeping smart build available",
    async ({ cached, layers }) => {
      vi.mocked(fetchMaterialSolverCacheStatus).mockImplementation(async (key) => ({
        status: "ok", message: "", cached, palette_hash: "x",
        layer_count: key.layerCount, layer_height_mm: key.layerHeightMm, substrate: "white",
        entry: cached ? buildCacheEntry({ layer_count: key.layerCount }) : null,
      }));
      vi.mocked(buildMaterialSolverRuntime).mockResolvedValue({
        status: "ok", message: "", entry: buildRuntimeEntry({ layer_count: layers }),
      });
      const names = ["red", "white"];
      const view = render(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={layers} layerHeightMm={0.08} />);
      const buildName = cached ? "重新构建" : "立即构建缓存";
      await waitFor(() => expect(screen.getByRole("button", { name: buildName })).toBeDisabled());
      expect(screen.getByText("穷举缓存最多支持 10 层。更多层数请使用下方的智能缓存。")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: buildName }));
      expect(buildMaterialSolverCache).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "构建智能缓存" }));
      await waitFor(() => expect(buildMaterialSolverRuntime).toHaveBeenCalledWith(
        expect.objectContaining({ layerCount: layers }), expect.any(Object),
      ));
      view.rerender(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={10} layerHeightMm={0.08} />);
      await waitFor(() => expect(screen.getByRole("button", { name: buildName })).toBeEnabled());
    },
  );

  it.each(["exhaustive", "smart"] as const)("ignores an old %s build after changing the layer count", async (kind) => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockImplementation(async (key) => ({
      status: "ok", message: "", cached: false, palette_hash: "x",
      layer_count: key.layerCount, layer_height_mm: key.layerHeightMm, substrate: "white", entry: null,
    }));
    let finish!: () => void;
    if (kind === "exhaustive") {
      vi.mocked(buildMaterialSolverCache).mockImplementation(() => new Promise((resolve) => {
        finish = () => resolve({ status: "ok", message: "", entry: buildCacheEntry() });
      }));
    } else {
      vi.mocked(buildMaterialSolverRuntime).mockImplementation(() => new Promise((resolve) => {
        finish = () => resolve({ status: "ok", message: "", entry: buildRuntimeEntry({ layer_count: 5 }) });
      }));
    }
    const names = ["red", "white"];
    const view = render(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={5} layerHeightMm={0.08} />);
    const pillId = kind === "exhaustive" ? "material-solver-cache-status-pill" : "material-solver-runtime-status-pill";
    await waitFor(() => expect(screen.getByTestId(pillId)).toHaveAttribute("data-tone", "warn"));
    fireEvent.click(screen.getByRole("button", { name: kind === "exhaustive" ? "立即构建缓存" : "构建智能缓存" }));
    view.rerender(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={6} layerHeightMm={0.08} />);
    await waitFor(() => expect(screen.getByTestId(pillId)).toHaveAttribute("data-tone", "warn"));
    await act(async () => { finish(); });
    expect(screen.getByTestId(pillId)).toHaveAttribute("data-tone", "warn");
  });

  it.each(["exhaustive", "smart"] as const)("ignores an old %s deletion after changing the layer count", async (kind) => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockImplementation(async (key) => ({
      status: "ok", message: "", cached: true, palette_hash: "x",
      layer_count: key.layerCount, layer_height_mm: key.layerHeightMm, substrate: "white",
      entry: buildCacheEntry({ layer_count: key.layerCount }),
    }));
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockImplementation(async (key) => ({
      status: "ok", message: "", cached: true, palette_hash: "x", candidate_budget: 33_554_432,
      layer_count: key.layerCount, layer_height_mm: key.layerHeightMm, substrate: "white",
      entry: buildRuntimeEntry({ layer_count: key.layerCount }),
    }));
    let finish!: () => void;
    const deleted = { status: "ok", message: "", deleted: true, palette_hash: "x", layer_count: 5, layer_height_mm: 0.08, substrate: "white", candidate_budget: 33_554_432 };
    if (kind === "exhaustive") {
      vi.mocked(deleteMaterialSolverCache).mockImplementation(() => new Promise((resolve) => { finish = () => resolve(deleted); }));
    } else {
      vi.mocked(deleteMaterialSolverRuntime).mockImplementation(() => new Promise((resolve) => { finish = () => resolve(deleted); }));
    }
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const names = ["red", "white"];
    const view = render(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={5} layerHeightMm={0.08} />);
    const pillId = kind === "exhaustive" ? "material-solver-cache-status-pill" : "material-solver-runtime-status-pill";
    await waitFor(() => expect(screen.getByTestId(pillId)).toHaveAttribute("data-tone", "ok"));
    fireEvent.click(screen.getByRole("button", { name: kind === "exhaustive" ? "删除缓存" : "删除智能缓存" }));
    view.rerender(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={6} layerHeightMm={0.08} />);
    await waitFor(() => expect(screen.getByTestId(pillId)).toHaveAttribute("data-tone", "ok"));
    await act(async () => { finish(); });
    expect(screen.getByTestId(pillId)).toHaveAttribute("data-tone", "ok");
    confirm.mockRestore();
  });

  it.each(["exhaustive", "smart"] as const)("keeps the new %s build busy when an old build fails", async (kind) => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok", message: "", cached: false, palette_hash: "x", layer_count: 5,
      layer_height_mm: 0.08, substrate: "white", entry: null,
    });
    let rejectOld!: (error: Error) => void;
    let finishNew!: () => void;
    if (kind === "exhaustive") {
      vi.mocked(buildMaterialSolverCache)
        .mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }))
        .mockImplementationOnce(() => new Promise((resolve) => { finishNew = () => resolve({ status: "ok", message: "", entry: buildCacheEntry({ layer_count: 6 }) }); }));
    } else {
      vi.mocked(buildMaterialSolverRuntime)
        .mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }))
        .mockImplementationOnce(() => new Promise((resolve) => { finishNew = () => resolve({ status: "ok", message: "", entry: buildRuntimeEntry({ layer_count: 6 }) }); }));
    }
    const names = ["red", "white"];
    const view = render(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={5} layerHeightMm={0.08} />);
    const label = kind === "exhaustive" ? "立即构建缓存" : "构建智能缓存";
    await waitFor(() => expect(screen.getByRole("button", { name: label })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: label }));
    view.rerender(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={6} layerHeightMm={0.08} />);
    const newButton = await screen.findByRole("button", { name: label });
    fireEvent.click(newButton);
    await act(async () => { rejectOld(new Error("old build failed")); });
    expect(newButton).toBeDisabled();
    expect(screen.queryByText(/缓存构建失败/)).not.toBeInTheDocument();
    await act(async () => { finishNew(); });
  });

  it.each(["exhaustive", "smart"] as const)("does not revive %s charts from a previous combination", async (kind) => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok", message: "", cached: true, palette_hash: "x", layer_count: 5,
      layer_height_mm: 0.08, substrate: "white", entry: buildCacheEntry(),
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok", message: "", cached: true, palette_hash: "x", candidate_budget: 33_554_432,
      layer_count: 5, layer_height_mm: 0.08, substrate: "white", entry: buildRuntimeEntry(),
    });
    let rejectOld!: (error: Error) => void;
    if (kind === "exhaustive") {
      vi.mocked(fetchMaterialSolverCacheDetails).mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }));
    } else {
      vi.mocked(fetchMaterialSolverRuntimeDetails).mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }));
    }
    const names = ["red", "white"];
    const view = render(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={5} layerHeightMm={0.08} />);
    const toggleId = kind === "exhaustive" ? "material-solver-cache-charts-toggle" : "material-solver-runtime-charts-toggle";
    fireEvent.click(await screen.findByTestId(toggleId));
    view.rerender(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={6} layerHeightMm={0.08} />);
    const newToggle = await screen.findByTestId(toggleId);
    await act(async () => { rejectOld(new Error("old chart failure")); });
    expect(newToggle).toBeEnabled();
    const prefix = kind === "exhaustive" ? "basic_material_cache" : "basic_material_runtime";
    expect(newToggle).toHaveTextContent(translations[`${prefix}_charts_show_button`].zh);
    expect(screen.queryByText(translations[`${prefix}_charts_failed`].zh)).not.toBeInTheDocument();
  });

  it.each(["exhaustive", "smart"] as const)("fetches fresh %s charts instead of reusing a late old payload", async (kind) => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok", message: "", cached: true, palette_hash: "x", layer_count: 5,
      layer_height_mm: 0.08, substrate: "white", entry: buildCacheEntry(),
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok", message: "", cached: true, palette_hash: "x", candidate_budget: 33_554_432,
      layer_count: 5, layer_height_mm: 0.08, substrate: "white", entry: buildRuntimeEntry(),
    });
    let finishOld!: () => void;
    if (kind === "exhaustive") {
      vi.mocked(fetchMaterialSolverCacheDetails)
        .mockImplementationOnce(() => new Promise((resolve) => { finishOld = () => resolve(buildRuntimeDetailsResponse()); }))
        .mockImplementationOnce(() => new Promise(() => {}));
    } else {
      vi.mocked(fetchMaterialSolverRuntimeDetails)
        .mockImplementationOnce(() => new Promise((resolve) => { finishOld = () => resolve(buildRuntimeDetailsResponse()); }))
        .mockImplementationOnce(() => new Promise(() => {}));
    }
    const names = ["red", "white"];
    const view = render(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={5} layerHeightMm={0.08} />);
    const toggleId = kind === "exhaustive" ? "material-solver-cache-charts-toggle" : "material-solver-runtime-charts-toggle";
    fireEvent.click(await screen.findByTestId(toggleId));
    view.rerender(<MaterialSolverCacheStatusCard materialDirectoryNames={names} layerCount={6} layerHeightMm={0.08} />);
    const newToggle = await screen.findByTestId(toggleId);
    await act(async () => { finishOld(); });
    fireEvent.click(newToggle);
    expect(kind === "exhaustive" ? fetchMaterialSolverCacheDetails : fetchMaterialSolverRuntimeDetails).toHaveBeenCalledTimes(2);
  });

  it("shows the idle state when no materials are selected", async () => {
    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={[]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const pill = await screen.findByTestId(
      "material-solver-cache-status-pill",
    );
    expect(pill).toHaveAttribute("data-tone", "neutral");
    // Build button is present but disabled because no materials selected.
    const buildButton = screen.getByRole("button", { name: "立即构建缓存" });
    expect(buildButton).toBeDisabled();
    expect(fetchMaterialSolverCacheStatus).not.toHaveBeenCalled();
    expect(fetchMaterialSolverRuntimeStatus).not.toHaveBeenCalled();
  });

  it("queries and shows ready state when a cache is found", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "Cache found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: buildCacheEntry(),
    });

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );

    await waitFor(() => {
      expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledTimes(1);
    });
    expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledWith(
      {
        materialDirectoryNames: ["red", "white"],
        layerCount: 5,
        layerHeightMm: 0.08,
        substrate: "white",
      },
      // With the opt-in toggle off, the call omits a concrete
      // gridResolution so the backend applies its low-tier default.
      { gridResolution: undefined },
    );

    const pill = await screen.findByTestId(
      "material-solver-cache-status-pill",
    );
    await waitFor(() => {
      expect(pill).toHaveAttribute("data-tone", "ok");
    });
    expect(screen.getByText("缓存已就绪")).toBeInTheDocument();
    // Rebuild + Delete buttons appear in cached state.
    expect(
      screen.getByRole("button", { name: "重新构建" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "删除缓存" }),
    ).toBeInTheDocument();
  });

  it("shows missing state with fallback hint and build button", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const pill = await screen.findByTestId(
      "material-solver-cache-status-pill",
    );
    await waitFor(() => {
      expect(pill).toHaveAttribute("data-tone", "warn");
    });
    expect(screen.getByText("缓存未构建")).toBeInTheDocument();
    // Fallback hint should be visible when cache is missing.
    expect(
      screen.getByText(/参数调整不会自动预览.*临时候选求解器/),
    ).toBeInTheDocument();
    const buildButton = screen.getByRole("button", { name: "立即构建缓存" });
    expect(buildButton).not.toBeDisabled();
  });

  it("invokes the build API and transitions to ready state on success", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });
    vi.mocked(buildMaterialSolverCache).mockResolvedValue({
      status: "ok",
      message: "Built cache",
      entry: buildCacheEntry(),
    });

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const buildButton = await screen.findByRole("button", {
      name: "立即构建缓存",
    });
    await act(async () => {
      fireEvent.click(buildButton);
    });

    await waitFor(() => {
      expect(buildMaterialSolverCache).toHaveBeenCalledTimes(1);
    });
    expect(buildMaterialSolverCache).toHaveBeenCalledWith(
      {
        materialDirectoryNames: ["red", "white"],
        layerCount: 5,
        layerHeightMm: 0.08,
        substrate: "white",
      },
      { gridResolution: undefined },
    );

    // After a successful build, pill should transition to "ok".
    await waitFor(() => {
      expect(
        screen.getByTestId("material-solver-cache-status-pill"),
      ).toHaveAttribute("data-tone", "ok");
    });
    expect(screen.getByText("缓存已就绪")).toBeInTheDocument();
  });

  it("forwards selected runtime candidate budget to status build and delete calls", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      entry: null,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok",
      message: "Runtime found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      candidate_budget: 67_108_864,
      entry: buildRuntimeEntry({ candidate_budget: 67_108_864 }),
    });
    vi.mocked(buildMaterialSolverRuntime).mockResolvedValue({
      status: "ok",
      message: "Built runtime",
      entry: buildRuntimeEntry({ candidate_budget: 67_108_864 }),
    });
    vi.mocked(deleteMaterialSolverRuntime).mockResolvedValue({
      status: "ok",
      message: "Runtime deleted",
      deleted: true,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      candidate_budget: 67_108_864,
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={8}
        layerHeightMm={0.04}
      />,
    );

    await waitFor(() => {
      expect(fetchMaterialSolverRuntimeStatus).toHaveBeenCalledWith(
        expect.any(Object),
        { candidateBudget: 33_554_432 },
      );
    });

    const runtimeSection = await screen.findByTestId(
      "material-solver-runtime-section",
    );
    fireEvent.click(within(runtimeSection).getByRole("combobox"));
    fireEvent.click(await screen.findByRole("option", { name: /64M/ }));

    await waitFor(() => {
      expect(fetchMaterialSolverRuntimeStatus).toHaveBeenLastCalledWith(
        expect.any(Object),
        { candidateBudget: 67_108_864 },
      );
    });

    const rebuildButton = within(runtimeSection).getByRole("button", {
      name: "重建智能缓存",
    });
    const deleteButton = within(runtimeSection).getByRole("button", {
      name: "删除智能缓存",
    });
    await act(async () => {
      fireEvent.click(rebuildButton);
    });
    await waitFor(() => {
      expect(buildMaterialSolverRuntime).toHaveBeenCalledTimes(1);
    });
    expect(buildMaterialSolverRuntime).toHaveBeenLastCalledWith(
      expect.any(Object),
      { candidateBudget: 67_108_864 },
    );

    await act(async () => {
      fireEvent.click(deleteButton);
    });
    await waitFor(() => {
      expect(deleteMaterialSolverRuntime).toHaveBeenCalledTimes(1);
    });
    expect(deleteMaterialSolverRuntime).toHaveBeenLastCalledWith(
      expect.any(Object),
      { candidateBudget: 67_108_864 },
    );

    confirmSpy.mockRestore();
  });

  it("loads recipe coverage charts for a cached smart recipe cache", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      entry: null,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok",
      message: "Runtime found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      candidate_budget: 33_554_432,
      entry: buildRuntimeEntry(),
    });

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={8}
        layerHeightMm={0.04}
      />,
    );

    const runtimeSection = await screen.findByTestId(
      "material-solver-runtime-section",
    );
    const chartsButton = within(runtimeSection).getByRole("button", {
      name: "查看配方覆盖图",
    });
    await act(async () => {
      fireEvent.click(chartsButton);
    });

    await waitFor(() => {
      expect(fetchMaterialSolverRuntimeDetails).toHaveBeenCalledTimes(1);
    });
    expect(fetchMaterialSolverRuntimeDetails).toHaveBeenCalledWith(
      {
        materialDirectoryNames: ["red", "white"],
        layerCount: 8,
        layerHeightMm: 0.04,
        substrate: "white",
      },
      { candidateBudget: 33_554_432, maxPoints: 8000 },
    );
    expect(
      screen.getByTestId("material-solver-runtime-charts-region"),
    ).toBeInTheDocument();
    expect(fetchMaterialSolverCacheDetails).not.toHaveBeenCalled();
  });

  it("deletes a cached entry after confirmation", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "Cache found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: buildCacheEntry(),
    });
    vi.mocked(deleteMaterialSolverCache).mockResolvedValue({
      status: "ok",
      message: "Cache deleted",
      deleted: true,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const deleteButton = await screen.findByRole("button", {
      name: "删除缓存",
    });
    await act(async () => {
      fireEvent.click(deleteButton);
    });

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(deleteMaterialSolverCache).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("material-solver-cache-status-pill"),
      ).toHaveAttribute("data-tone", "warn");
    });
    expect(screen.getByText("缓存未构建")).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("renders safe copy when the cache status request fails", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockRejectedValue(
      new Error("Request failed with status code 422"),
    );

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const pill = await screen.findByTestId(
      "material-solver-cache-status-pill",
    );
    await waitFor(() => {
      expect(pill).toHaveAttribute("data-tone", "error");
    });
    expect(
      screen.getByText("缓存状态查询失败，请稍后重试。"),
    ).toBeInTheDocument();
    expectRawMaterialCacheErrorsHidden();
  });

  it("renders safe copy when cache build fails", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });
    vi.mocked(buildMaterialSolverCache).mockRejectedValue(
      new Error("Request failed with status code 500"),
    );

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const buildButton = await screen.findByRole("button", {
      name: "立即构建缓存",
    });
    await act(async () => {
      fireEvent.click(buildButton);
    });

    await waitFor(() => {
      expect(buildMaterialSolverCache).toHaveBeenCalledTimes(1);
    });
    expect(
      screen.getByText("缓存构建失败，请稍后重试。"),
    ).toBeInTheDocument();
    expectRawMaterialCacheErrorsHidden();
  });

  it("renders safe copy when cache delete fails", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "Cache found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: buildCacheEntry(),
    });
    vi.mocked(deleteMaterialSolverCache).mockRejectedValue(
      new Error("Request failed with status code 500"),
    );
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const deleteButton = await screen.findByRole("button", {
      name: "删除缓存",
    });
    await act(async () => {
      fireEvent.click(deleteButton);
    });

    await waitFor(() => {
      expect(deleteMaterialSolverCache).toHaveBeenCalledTimes(1);
    });
    expect(
      screen.getByText("缓存删除失败，请稍后重试。"),
    ).toBeInTheDocument();
    expectRawMaterialCacheErrorsHidden();
    confirmSpy.mockRestore();
  });

  it("renders safe copy when cache charts fail to load", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "Cache found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: buildCacheEntry(),
    });
    vi.mocked(fetchMaterialSolverCacheDetails).mockRejectedValue(
      new Error("network down"),
    );

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const chartsButton = await screen.findByRole("button", {
      name: "查看色彩分布图",
    });
    await act(async () => {
      fireEvent.click(chartsButton);
    });

    await waitFor(() => {
      expect(fetchMaterialSolverCacheDetails).toHaveBeenCalledTimes(1);
    });
    expect(
      screen.getByText("色彩分布图加载失败，请稍后重试。"),
    ).toBeInTheDocument();
    expectRawMaterialCacheErrorsHidden();
  });

  it("renders safe copy when the runtime status request fails", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockRejectedValue(
      new Error("Request failed with status code 422"),
    );

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const pill = await screen.findByTestId(
      "material-solver-runtime-status-pill",
    );
    await waitFor(() => {
      expect(pill).toHaveAttribute("data-tone", "error");
    });
    expect(
      screen.getByText("智能缓存状态查询失败，请稍后重试。"),
    ).toBeInTheDocument();
    expectRawMaterialCacheErrorsHidden();
  });

  it("renders safe copy when runtime build fails", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok",
      message: "No runtime found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      candidate_budget: 33_554_432,
      entry: null,
    });
    vi.mocked(buildMaterialSolverRuntime).mockRejectedValue(
      new Error("Request failed with status code 500"),
    );

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const runtimeSection = await screen.findByTestId(
      "material-solver-runtime-section",
    );
    const runtimeBuildButton = within(runtimeSection).getByRole("button", {
      name: "构建智能缓存",
    });
    await act(async () => {
      fireEvent.click(runtimeBuildButton);
    });

    await waitFor(() => {
      expect(buildMaterialSolverRuntime).toHaveBeenCalledTimes(1);
    });
    expect(
      screen.getByText("智能缓存构建失败，请稍后重试。"),
    ).toBeInTheDocument();
    expectRawMaterialCacheErrorsHidden();
  });

  it("renders safe copy when runtime delete fails", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      entry: null,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok",
      message: "Runtime found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      candidate_budget: 33_554_432,
      entry: buildRuntimeEntry(),
    });
    vi.mocked(deleteMaterialSolverRuntime).mockRejectedValue(
      new Error("Request failed with status code 500"),
    );
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={8}
        layerHeightMm={0.04}
      />,
    );
    const runtimeSection = await screen.findByTestId(
      "material-solver-runtime-section",
    );
    const runtimeDeleteButton = within(runtimeSection).getByRole("button", {
      name: "删除智能缓存",
    });
    await act(async () => {
      fireEvent.click(runtimeDeleteButton);
    });

    await waitFor(() => {
      expect(deleteMaterialSolverRuntime).toHaveBeenCalledTimes(1);
    });
    expect(
      screen.getByText("智能缓存删除失败，请稍后重试。"),
    ).toBeInTheDocument();
    expectRawMaterialCacheErrorsHidden();
    confirmSpy.mockRestore();
  });

  it("renders safe copy when runtime charts fail to load", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      entry: null,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok",
      message: "Runtime found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      candidate_budget: 33_554_432,
      entry: buildRuntimeEntry(),
    });
    vi.mocked(fetchMaterialSolverRuntimeDetails).mockRejectedValue(
      new Error("network down"),
    );

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={8}
        layerHeightMm={0.04}
      />,
    );
    const runtimeSection = await screen.findByTestId(
      "material-solver-runtime-section",
    );
    const chartsButton = within(runtimeSection).getByRole("button", {
      name: "查看配方覆盖图",
    });
    await act(async () => {
      fireEvent.click(chartsButton);
    });

    await waitFor(() => {
      expect(fetchMaterialSolverRuntimeDetails).toHaveBeenCalledTimes(1);
    });
    expect(
      screen.getByText("配方覆盖图加载失败，请稍后重试。"),
    ).toBeInTheDocument();
    expectRawMaterialCacheErrorsHidden();
  });

  it("forwards the chosen gridResolution to every API call when the opt-in toggle is on", async () => {
    // Flip the store into opt-in mode with medium density before the card mounts.
    useSettingsStore.setState({
      enableSolverCacheGridSelection: true,
      solverCacheGridResolution: 128,
    });

    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });
    vi.mocked(buildMaterialSolverCache).mockResolvedValue({
      status: "ok",
      message: "Built cache",
      entry: buildCacheEntry({ grid_resolution: 128 }),
    });
    vi.mocked(deleteMaterialSolverCache).mockResolvedValue({
      status: "ok",
      message: "Cache deleted",
      deleted: true,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );

    // 1) The initial status query targets grid 128.
    await waitFor(() => {
      expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledTimes(1);
    });
    expect(fetchMaterialSolverCacheStatus).toHaveBeenLastCalledWith(
      expect.any(Object),
      { gridResolution: 128 },
    );

    // 2) Build also targets grid 128.
    const buildButton = await screen.findByRole("button", {
      name: "立即构建缓存",
    });
    await act(async () => {
      fireEvent.click(buildButton);
    });
    await waitFor(() => {
      expect(buildMaterialSolverCache).toHaveBeenCalledTimes(1);
    });
    expect(buildMaterialSolverCache).toHaveBeenLastCalledWith(
      expect.any(Object),
      { gridResolution: 128 },
    );

    // 3) Delete the entry and confirm the delete call also targets grid 128.
    const deleteButton = await screen.findByRole("button", {
      name: "删除缓存",
    });
    await act(async () => {
      fireEvent.click(deleteButton);
    });
    await waitFor(() => {
      expect(deleteMaterialSolverCache).toHaveBeenCalledTimes(1);
    });
    expect(deleteMaterialSolverCache).toHaveBeenLastCalledWith(
      expect.any(Object),
      { gridResolution: 128 },
    );

    confirmSpy.mockRestore();
  });
});
