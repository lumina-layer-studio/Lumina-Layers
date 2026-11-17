import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  convertBatch: vi.fn(),
  replaceColorsBatch: vi.fn(),
  applyRecipeOverride: vi.fn(),
  resetReplacements: vi.fn(),
  fetchGradientGroups: vi.fn(),
  fetchSessionLutInfo: vi.fn(),
}));

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    fetchExportMaterialSelection: vi.fn(async () => (await import("./fixtures/exportMaterialSelection")).READY_EXPORT_MATERIAL_SELECTION),
    convertPreview: mocks.convertPreview,
    convertGenerate: mocks.convertGenerate,
    convertBatch: mocks.convertBatch,
    replaceColorsBatch: mocks.replaceColorsBatch,
    applyRecipeOverride: mocks.applyRecipeOverride,
    resetReplacements: mocks.resetReplacements,
    fetchGradientGroups: mocks.fetchGradientGroups,
  };
});

vi.mock("../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../api/lut")>(
    "../api/lut",
  );
  return {
    ...actual,
    fetchSessionLutInfo: mocks.fetchSessionLutInfo,
  };
});

import { ColorMode, ModelingMode } from "../api/types";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

const DYNAMIC_RECIPES = [
  {
    target_srgb: [17, 34, 51] as [number, number, number],
    matched_srgb: [20, 30, 40] as [number, number, number],
    actual_layer_count: 5,
    padding_layer_count: 4,
    actual_recipe_top_to_bottom: [1, 2, 1, 2, 1],
    print_recipe_top_to_bottom: [1, 2, 1, 2, 1, 0, 0, 0, 0],
    selected_delta_e00: 1.2,
    best_range_delta_e00: 0.9,
    fixed_max_delta_e00: 1.0,
    delta_e00_sacrifice: 0.3,
    layer_cap_options: [],
  },
];

const BENEFIT_CURVE = [
  {
    max_effective_layer_count: 5,
    weighted_mean_delta_e00: 2.5,
    marginal_delta_e00_reduction: 0,
  },
];

const UPDATED_DYNAMIC_RECIPES = [
  {
    ...DYNAMIC_RECIPES[0],
    matched_srgb: [41, 51, 61] as [number, number, number],
    selected_delta_e00: 0.8,
  },
];

const UPDATED_BENEFIT_CURVE = [
  {
    ...BENEFIT_CURVE[0],
    weighted_mean_delta_e00: 1.8,
    marginal_delta_e00_reduction: 0.7,
  },
];

function previewResponse(overrides: Record<string, unknown> = {}) {
  return {
    session_id: "dynamic-session",
    status: "ok",
    message: "Preview generated",
    preview_url: "/api/files/dynamic-preview.png",
    preview_glb_url: "/api/files/dynamic-preview.glb",
    palette: [
      {
        quantized_hex: "#112233",
        matched_hex: "#141e28",
        pixel_count: 10,
        percentage: 100,
      },
    ],
    dimensions: { width: 2, height: 2 },
    warnings: [],
    ...overrides,
  };
}

function seedMaterialState(dynamicEnabled = true): void {
  useConverterStore.setState({
    ...DEFAULT_STATE,
    imageFile: new File(["png"], "material.png", { type: "image/png" }),
    source_version: "material",
    selectedMaterialDirNames: ["brand/white", "brand/blue"],
    materialBackingMaterialDirName: "brand/white",
    materialLayerCount: 7,
    materialLayerHeightMm: 0.08,
    materialDynamicLayerCountEnabled: dynamicEnabled,
    materialMinLayerCount: 6,
    materialMaxLayerCount: 9,
    target_width_mm: 60,
    color_mode: ColorMode.FOUR_COLOR_RYBW,
    modeling_mode: ModelingMode.HIGH_FIDELITY,
    quantize_colors: 48,
    enable_cleanup: true,
    hue_enable: true,
    chroma_gate: 22,
    enable_relief: false,
    largeFormatEnabled: false,
    puzzleEnabled: false,
  } as never);
  useSettingsStore.setState({
    ...DEFAULT_SETTINGS,
    materialDeltaE00Tolerance: 0.7,
  });
}

describe("dynamic material request transport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useConverterStore.setState({ ...DEFAULT_STATE } as never);
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    mocks.fetchGradientGroups.mockResolvedValue({ status: "ok", groups: [] });
    mocks.fetchSessionLutInfo.mockResolvedValue({
      name: "material-session",
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      color_count: 2,
    });
    mocks.convertPreview.mockResolvedValue(previewResponse());
    mocks.convertGenerate.mockResolvedValue({
      status: "ok",
      message: "Generated",
      download_url: "/api/files/model.3mf",
      preview_3d_url: "/api/files/model.glb",
    });
    mocks.convertBatch.mockResolvedValue({
      status: "ok",
      message: "Batch generated",
      download_url: "/api/files/batch.zip",
      preview_3d_url: null,
      preview_items: [],
      results: [],
      warnings: [],
    });
    mocks.resetReplacements.mockResolvedValue({
      status: "ok",
      message: "Reset",
      preview_url: "/api/files/reset.png",
      preview_glb_url: null,
      material_dynamic_recipes: DYNAMIC_RECIPES,
      material_layer_benefit_curve: BENEFIT_CURVE,
      material_layer_benefit_scope: "all_printable_pixels",
      material_layer_benefit_pixel_count: 10,
    });
  });

  it("sends the 30-layer dynamic range for preview and generate without unlocking fixed layers", async () => {
    seedMaterialState(true);
    useConverterStore.getState().setMaterialMinLayerCount(5);
    useConverterStore.getState().setMaterialMaxLayerCount(30);
    expect(useConverterStore.getState().materialLayersUnlocked).toBe(false);
    await useConverterStore.getState().submitPreview();
    await useConverterStore.getState().submitGenerate();
    for (const request of [mocks.convertPreview.mock.calls[0], mocks.convertGenerate.mock.calls[0]]) {
      expect(request[1]).toMatchObject({
        material_dynamic_layer_count_enabled: true,
        material_min_layer_count: 5, material_max_layer_count: 30,
        material_layer_count: 30, color_layers: 30,
      });
    }
  });

  it("sends dynamic settings, maximum physical depth, and zero hue weights for preview", async () => {
    seedMaterialState(true);

    await useConverterStore.getState().submitPreview();

    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(params).toMatchObject({
      material_dynamic_layer_count_enabled: true,
      material_min_layer_count: 6,
      material_max_layer_count: 9,
      material_delta_e00_tolerance: 0.7,
      material_layer_count: 9,
      color_layers: 9,
      hue_weight: 0,
      chroma_gate: 0,
    });
    expect(useConverterStore.getState().color_layers).toBe(9);
  });

  it("sends the same dynamic contract for generate", async () => {
    seedMaterialState(true);
    useConverterStore.setState({ sessionId: "dynamic-session" });

    await useConverterStore.getState().submitGenerate();

    const [, params] = mocks.convertGenerate.mock.calls[0];
    expect(params).toMatchObject({
      material_dynamic_layer_count_enabled: true,
      material_min_layer_count: 6,
      material_max_layer_count: 9,
      material_delta_e00_tolerance: 0.7,
      material_layer_count: 9,
      color_layers: 9,
      hue_weight: 0,
      chroma_gate: 0,
    });
  });

  it("can send cached spatial state together with a confirmed global remap", async () => {
    seedMaterialState(true);
    useConverterStore.setState({
      sessionId: "dynamic-session",
      palette: previewResponse().palette,
      regionReplacementCount: 1,
      colorRemapMap: { "#141e28": "#abcdef" },
    });

    await useConverterStore.getState().submitGenerate();

    const [, params] = mocks.convertGenerate.mock.calls[0];
    expect(params.use_cached_matched_rgb).toBe(true);
    expect(params.replacement_regions).toEqual([
      {
        quantized_hex: "#112233",
        matched_hex: "#141e28",
        replacement_hex: "#abcdef",
      },
    ]);
  });

  it("sends the same dynamic contract for batch", async () => {
    seedMaterialState(true);
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [new File(["a"], "a.png", { type: "image/png" })],
    });

    await useConverterStore.getState().submitBatch();

    const [, params] = mocks.convertBatch.mock.calls[0];
    expect(params).toMatchObject({
      material_dynamic_layer_count_enabled: true,
      material_min_layer_count: 6,
      material_max_layer_count: 9,
      material_delta_e00_tolerance: 0.7,
      material_layer_count: 9,
      color_layers: 9,
      hue_weight: 0,
      chroma_gate: 0,
    });
  });

  it("keeps fixed material depth and hue behavior while sending disabled dynamic defaults", async () => {
    seedMaterialState(false);

    await useConverterStore.getState().submitPreview();

    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(params).toMatchObject({
      material_dynamic_layer_count_enabled: false,
      material_min_layer_count: 6,
      material_max_layer_count: 9,
      material_delta_e00_tolerance: 0.7,
      material_layer_count: 7,
      color_layers: 7,
      hue_weight: 0.5,
      chroma_gate: 22,
    });
  });
});

describe("dynamic material response lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seedMaterialState(true);
    mocks.fetchGradientGroups.mockResolvedValue({ status: "ok", groups: [] });
    mocks.fetchSessionLutInfo.mockResolvedValue({
      name: "material-session",
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      color_count: 2,
    });
  });

  it("adopts exact dynamic arrays and clears them when a later response omits them", async () => {
    mocks.convertPreview
      .mockResolvedValueOnce(
        previewResponse({
          material_dynamic_recipes: DYNAMIC_RECIPES,
          material_layer_benefit_curve: BENEFIT_CURVE,
          material_layer_benefit_scope: "all_printable_pixels",
          material_layer_benefit_pixel_count: 10,
        }),
      )
      .mockResolvedValueOnce(
        previewResponse({ session_id: "fixed-session" }),
      );

    await useConverterStore.getState().submitPreview();
    expect(useConverterStore.getState()).toMatchObject({
      materialDynamicRecipes: DYNAMIC_RECIPES,
      materialLayerBenefitCurve: BENEFIT_CURVE,
      materialLayerBenefitScope: "all_printable_pixels",
      materialLayerBenefitPixelCount: 10,
    });

    await useConverterStore.getState().submitPreview();
    expect(useConverterStore.getState()).toMatchObject({
      materialDynamicRecipes: [],
      materialLayerBenefitCurve: [],
    });
  });

  it("adopts recomputed dynamic metadata after a backend color replacement", async () => {
    vi.useFakeTimers();
    try {
      mocks.replaceColorsBatch.mockResolvedValue({
        status: "ok",
        message: "Replaced",
        preview_url: "/api/files/replaced.png",
        preview_3d_url: "/api/files/replaced.glb",
        replacement_count: 1,
        material_dynamic_recipes: UPDATED_DYNAMIC_RECIPES,
        material_layer_benefit_curve: UPDATED_BENEFIT_CURVE,
        material_layer_benefit_scope: "automatic_pixels",
        material_layer_benefit_pixel_count: 6,
      });
      useConverterStore.setState({
        sessionId: "dynamic-session",
        selectedColors: new Set(["141e28"]),
        materialDynamicRecipes: DYNAMIC_RECIPES,
        materialLayerBenefitCurve: BENEFIT_CURVE,
      } as never);

      await useConverterStore.getState().applyBatchColorRemap("ffffff");

      expect(useConverterStore.getState()).toMatchObject({
        materialDynamicRecipes: UPDATED_DYNAMIC_RECIPES,
        materialLayerBenefitCurve: UPDATED_BENEFIT_CURVE,
        materialLayerBenefitScope: "automatic_pixels",
        materialLayerBenefitPixelCount: 6,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("adopts recomputed dynamic metadata after a manual recipe edit", async () => {
    vi.useFakeTimers();
    try {
      mocks.applyRecipeOverride.mockResolvedValue({
        status: "ok",
        message: "Applied",
        preview_url: "/api/files/manual.png",
        preview_glb_url: "/api/files/manual.glb",
        applied_region_ids: ["region-1"],
        material_dynamic_recipes: UPDATED_DYNAMIC_RECIPES,
        material_layer_benefit_curve: UPDATED_BENEFIT_CURVE,
        material_layer_benefit_scope: "automatic_pixels",
        material_layer_benefit_pixel_count: 4,
      });
      useConverterStore.setState({
        sessionId: "dynamic-session",
        color_layers: 9,
        layer_height_mm: 0.08,
        materialDynamicRecipes: DYNAMIC_RECIPES,
        materialLayerBenefitCurve: BENEFIT_CURVE,
      } as never);

      await useConverterStore
        .getState()
        .applyCustomRecipeOverride(["region-1"], [1, 0, 1, 0, 1]);

      expect(mocks.applyRecipeOverride).toHaveBeenCalledWith(
        expect.objectContaining({
          // The backend validates dynamic ``color_layers`` against the actual
          // short recipe, while its session-owned max still controls printing.
          color_layers: 5,
        }),
      );

      expect(useConverterStore.getState()).toMatchObject({
        materialDynamicRecipes: UPDATED_DYNAMIC_RECIPES,
        materialLayerBenefitCurve: UPDATED_BENEFIT_CURVE,
        materialLayerBenefitScope: "automatic_pixels",
        materialLayerBenefitPixelCount: 4,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("resets local manual overrides with the backend preview snapshot", async () => {
    useConverterStore.setState({
      sessionId: "dynamic-session",
      recipe_overrides: [
        {
          region_id: "region-1",
          recipe: [1, 0, 1, 0, 1],
          layer_order: "Top2Bottom",
        },
      ],
      materialDynamicRecipes: UPDATED_DYNAMIC_RECIPES,
      materialLayerBenefitCurve: UPDATED_BENEFIT_CURVE,
      materialLayerBenefitScope: "automatic_pixels",
      materialLayerBenefitPixelCount: 4,
    } as never);

    useConverterStore.getState().clearAllRemaps();
    await Promise.resolve();
    await Promise.resolve();

    expect(mocks.resetReplacements).toHaveBeenCalledWith(
      "dynamic-session",
      expect.any(String),
    );
    expect(useConverterStore.getState()).toMatchObject({
      recipe_overrides: [],
      materialDynamicRecipes: DYNAMIC_RECIPES,
      materialLayerBenefitCurve: BENEFIT_CURVE,
      materialLayerBenefitScope: "all_printable_pixels",
      materialLayerBenefitPixelCount: 10,
    });
  });

  it("does not let an older preview overwrite a changed dynamic configuration", async () => {
    seedMaterialState(true);
    let resolveOldPreview: (value: ReturnType<typeof previewResponse>) => void =
      () => {
        throw new Error("The deferred preview resolver was not initialized.");
      };
    mocks.convertPreview.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOldPreview = resolve;
        }),
    );

    const pendingPreview = useConverterStore.getState().submitPreview();
    await Promise.resolve();
    expect(mocks.convertPreview).toHaveBeenCalledTimes(1);

    useConverterStore.getState().setMaterialDynamicLayerCountEnabled(false);
    useConverterStore.getState().setMaterialMinLayerCount(5);
    useConverterStore.getState().setMaterialMaxLayerCount(8);
    useSettingsStore.getState().setMaterialDeltaE00Tolerance(0.9);
    expect(mocks.convertPreview.mock.calls[0][2]?.aborted).toBe(true);

    resolveOldPreview(
      previewResponse({
        session_id: "stale-dynamic-session",
        material_dynamic_recipes: DYNAMIC_RECIPES,
        material_layer_benefit_curve: BENEFIT_CURVE,
      }),
    );
    await pendingPreview;

    expect(useConverterStore.getState()).toMatchObject({
      sessionId: null,
      materialDynamicRecipes: [],
      materialLayerBenefitCurve: [],
      materialDynamicLayerCountEnabled: false,
      materialMinLayerCount: 5,
      materialMaxLayerCount: 8,
    });
  });
});
