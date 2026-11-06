import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  applyImport,
  exportShareCard,
  exportSidecar,
  MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR,
  prepareImport,
} from "../recipe/importFlow";
import type { RestoreResult } from "../recipe/importRecipe";
import type { ConverterRecipeDevice, LuminaRecipe } from "../recipe/types";
import type { PrinterInfo } from "../api/types";
import type {
  DynamicMaterialRecipe,
  MaterialLayerBenefitPoint,
} from "../api/types";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { resolveConverterSettings } from "../stores/converter/project";
const effectiveSettings = () => resolveConverterSettings(useConverterStore.getState(), useSettingsStore.getState());
import { useWidgetStore } from "../stores/widgetStore";
import { useWorkshopStore } from "../workshop/store";
import { createBeadRecipeSourceFixture } from "./fixtures/beadRecipeSource";
import * as exportRecipeModule from "../recipe/exportRecipe";
import * as pngMetadataModule from "../recipe/pngMetadata";
import * as systemApi from "../api/system";
import apiClient from "../api/client";

const PRINTERS: PrinterInfo[] = [
  {
    id: "bambu-h2d",
    display_name: "Bambu Lab H2D",
    brand: "Bambu Lab",
    bed_width: 350,
    bed_depth: 320,
    bed_height: 325,
    supported_nozzle_sizes: ["0.2", "0.4"],
    supported_slicers: ["BambuStudio", "OrcaSlicer"],
    thumbnail: "",
    device_profiles: [
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.4",
        machine_profile_id: "BambuStudio:bbl:bambu-lab-h2d",
        slicer_id: "BambuStudio",
        nozzle_size: "0.4",
        source_profile_name: "Bambu Lab H2D 0.4 nozzle",
        revision: "sha256:h2d",
        supported: true,
        build_plates: [
          {
            id: "engineering-plate",
            display_name: "Engineering Plate",
            image_url: "/h2d-engineering.png",
          },
          {
            id: "textured-pei-plate",
            display_name: "Textured PEI Plate",
            image_url: "/h2d-textured.png",
          },
        ],
        default_build_plate_id: "textured-pei-plate",
      },
    ],
  },
  {
    id: "bambu-p1s",
    display_name: "Bambu Lab P1S",
    brand: "Bambu Lab",
    bed_width: 256,
    bed_depth: 256,
    bed_height: 256,
    supported_nozzle_sizes: ["0.2", "0.4"],
    supported_slicers: ["BambuStudio", "OrcaSlicer"],
    thumbnail: "",
    device_profiles: [
      {
        device_profile_id: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
        machine_profile_id: "OrcaSlicer:bbl:bambu-lab-p1s",
        slicer_id: "OrcaSlicer",
        nozzle_size: "0.2",
        source_profile_name: "Bambu Lab P1S 0.2 nozzle",
        revision: "sha256:p1s",
        supported: true,
        build_plates: [
          {
            id: "smooth-high-temp-plate",
            display_name: "Smooth High Temp Plate",
            image_url: "/p1s-smooth.png",
          },
          {
            id: "textured-pei-plate",
            display_name: "Textured PEI Plate",
            image_url: "/p1s-textured.png",
          },
        ],
        default_build_plate_id: "textured-pei-plate",
      },
    ],
  },
  {
    id: "flashforge-guider-3-ultra",
    display_name: "Flashforge Guider 3 Ultra",
    brand: "Flashforge",
    bed_width: 330,
    bed_depth: 340,
    bed_height: 600,
    supported_nozzle_sizes: ["0.4"],
    supported_slicers: ["FlashStudio"],
    thumbnail: "",
    device_profiles: [
      {
        device_profile_id: "FlashStudio:flashforge:guider-3-ultra:0.4",
        machine_profile_id: "FlashStudio:flashforge:guider-3-ultra",
        slicer_id: "FlashStudio",
        nozzle_size: "0.4",
        source_profile_name: "Flashforge Guider 3 Ultra 0.4 nozzle",
        revision: "sha256:guider",
        supported: true,
        build_plates: [],
        default_build_plate_id: "",
      },
    ],
  },
];

function makeRecipe(
  device_profile_id: string | null = "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
  build_plate_id: string | null = "smooth-high-temp-plate",
): LuminaRecipe {
  const device: ConverterRecipeDevice = {
    printer_id: "bambu-p1s",
    slicer: "OrcaSlicer",
    nozzle_size: "0.2",
  };
  if (device_profile_id !== null) {
    device.device_profile_id = device_profile_id;
  }
  if (build_plate_id !== null) {
    device.build_plate_id = build_plate_id;
  }

  return {
    format: "lumina-recipe",
    schema_version: 1,
    app_version: "0.0.0",
    created_at: "2026-06-10T00:00:00.000Z",
    source: "converter",
    cover: { width: 100, height: 80, mime_type: "image/png" },
    asset: {
      primary: {
        filename: "source.png",
        mime_type: "image/png",
        byte_size: 4,
        encoding: "base64",
        payload_b64: "dGVzdA==",
      },
    },
    recipe: {
      converter: {
        base: {
          lut: { name: "lut", color_mode: "4-Color (RYBW)" },
          color_mode: "4-Color (RYBW)",
          modeling_mode: "high-fidelity",
          target_width_mm: 60,
          target_height_mm: 45,
          quantize_colors: 48,
          enable_cleanup: true,
          hue_enable: false,
          chroma_gate: 15,
        },
        geometry: {
          spacer_thick: 1.2,
          structure_mode: "double-sided",
          separate_backing: false,
          add_loop: false,
          loop_width: 4,
          loop_length: 8,
          loop_hole: 2.5,
          loop_angle: 0,
          loop_offset_x: 0,
          loop_offset_y: 0,
          loop_position_preset: "",
        },
        relief: {
          enable_relief: false,
          auto_height_mode: "darker-higher",
          color_height_map: {},
          heightmap_max_height: 5,
        },
        outline: { enable_outline: false, outline_width: 2 },
        cloisonne: { enable_cloisonne: false, wire_width_mm: 0.4, wire_height_mm: 0.4 },
        coating: { enable_coating: false, coating_height_mm: 0.08 },
        color_ops: { replacement_regions: [], free_color_set: [] },
        large_format: { large_format_enabled: false, tile_width_mm: 180, tile_height_mm: 180 },
        puzzle: {
          puzzle_enabled: false,
          puzzle_style: "regular",
          puzzle_sizing_mode: "piece_size",
          piece_width_mm: 20,
          piece_height_mm: 20,
          puzzle_rows: 3,
          puzzle_cols: 3,
          target_piece_count: 12,
          puzzle_seed: 0,
          connector_style: "classic",
          labels_enabled: false,
          engrave_back_labels: false,
          irregularity_strength: 0.35,
          min_neck_width_mm: 1.2,
        },
        device,
      },
    },
    compat: { min_schema_version: 1 },
    warnings: [],
  };
}

function makeNativeRecipe(): LuminaRecipe {
  const recipe = makeRecipe();
  recipe.recipe.converter!.source = {
    source_version: "native",
    selected_native_brand_key: "bambulab_pla",
    selected_native_db_names: ["RYBW_008_5L.json"],
    color_layers: 5, layer_height_mm: 0.08,
    model_enable: true, model_only: false, model_threshold: null, model_margin: null,
    selected_material_dir_names: [], material_layer_count: 5,
    material_layer_height_mm: 0.08, material_backing_material_dir_name: null,
  };
  return recipe;
}

describe("recipe/importFlow", () => {
  beforeEach(() => {
    useConverterStore.setState({ ...DEFAULT_STATE });
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    useWidgetStore.setState({ activeTab: "settings" });
    useWorkshopStore.setState({
      activeModule: null,
      pendingRecipeSource: null,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("rejects predictive share cards before decoding assets or changing the current project", async () => {
    const imageFile = new File(["current"], "current.png", { type: "image/png" });
    useConverterStore.setState({ imageFile, lut_name: "current-lut" });

    await expect(prepareImport(new File([JSON.stringify(makeNativeRecipe())], "native.lumina.json")))
      .rejects.toThrow(/反推 LUT|inferred LUT/i);

    expect(useConverterStore.getState()).toMatchObject({ imageFile, lut_name: "current-lut" });
    expect(useWidgetStore.getState().activeTab).toBe("settings");
  });

  it("refuses a prepared native import before changing image or device settings", () => {
    const imageFile = new File(["current"], "current.png", { type: "image/png" });
    useConverterStore.setState({ imageFile, lut_name: "current-lut" });
    const beforeSettings = useSettingsStore.getState();
    const restored: RestoreResult = {
      recipe: makeNativeRecipe(), state: { source_version: "native" },
      assetFile: new File(["incoming"], "incoming.png", { type: "image/png" }),
      heightmapFile: null, warnings: [],
    };

    expect(() => applyImport(restored, PRINTERS)).toThrow(/反推 LUT|inferred LUT/i);

    expect(useConverterStore.getState()).toMatchObject({ imageFile, lut_name: "current-lut" });
    expect(useSettingsStore.getState()).toBe(beforeSettings);
    expect(useWidgetStore.getState().activeTab).toBe("settings");
  });

  it.each(["primary", "heightmap"])("rejects an undecodable %s before applying imported settings", async (assetKey) => {
    const recipe = makeRecipe();
    if (assetKey === "heightmap") recipe.asset.heightmap = { ...recipe.asset.primary, filename: "height.png" };
    if (assetKey === "heightmap") {
      vi.spyOn(apiClient, "post").mockRejectedValue(new Error("Cannot decode heightmap"));
    }
    class ImportImage {
      src = "";
      naturalWidth = 1;
      naturalHeight = 1;
      async decode() {
        if (assetKey === "primary") throw new Error("Cannot decode image");
      }
    }
    vi.stubGlobal("Image", ImportImage);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:import-image");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const printers = vi.spyOn(systemApi, "getPrinters").mockResolvedValue([]);
    const initialWidth = useConverterStore.getState().target_width_mm;
    const initialPrinter = useSettingsStore.getState().printerModel;
    await expect(prepareImport(new File([JSON.stringify(recipe)], "invalid.lumina.json"))).rejects.toThrow("Asset data is corrupted");
    expect(useConverterStore.getState().imageFile).toBeNull();
    expect(useConverterStore.getState().target_width_mm).toBe(initialWidth);
    expect(useSettingsStore.getState().printerModel).toBe(initialPrinter);
    expect(printers).not.toHaveBeenCalled();
    expect(revoke).toHaveBeenCalledTimes(1);
  });

  it.each(["source.nef", "source.heic"])("uses the existing backend decoder for %s and preserves failures", async (filename) => {
    const recipe = makeRecipe();
    recipe.asset.primary.filename = filename;
    recipe.asset.primary.mime_type = filename.endsWith("heic") ? "image/heic" : "application/octet-stream";
    const decodeFailure = new Error("Optional image decoder unavailable");
    vi.spyOn(systemApi, "uploadImagePreview").mockRejectedValue(decodeFailure);
    await expect(prepareImport(new File([JSON.stringify(recipe)], "image.lumina.json"))).rejects.toBe(decodeFailure);
    expect(useConverterStore.getState().imageFile).toBeNull();
  });

  it.each(["primary", "heightmap"])("bounds a pending %s decoder and releases its URL without applying state", async (assetKey) => {
    vi.useFakeTimers();
    const recipe = makeRecipe();
    if (assetKey === "heightmap") recipe.asset.heightmap = { ...recipe.asset.primary, filename: "height.png" };
    let markDecodingStarted: () => void = () => {};
    const decodingStarted = new Promise<void>((resolve) => { markDecodingStarted = resolve; });
    let heightmapSignal: AbortSignal | undefined;
    if (assetKey === "heightmap") {
      vi.spyOn(apiClient, "post").mockImplementation((_url, _data, options) => {
        heightmapSignal = options?.signal as AbortSignal;
        markDecodingStarted();
        return new Promise(() => {});
      });
    }
    class PendingImage {
      src = "";
      naturalWidth = 1;
      naturalHeight = 1;
      decode() {
        if (assetKey === "heightmap") return Promise.resolve();
        markDecodingStarted();
        return new Promise<void>(() => {});
      }
    }
    vi.stubGlobal("Image", PendingImage);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:pending-decode");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    let failure: unknown;
    const preparation = prepareImport(new File([JSON.stringify(recipe)], "pending.lumina.json"))
      .catch((error: unknown) => { failure = error; });
    await decodingStarted;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).toContain("Asset data is corrupted");
    expect(useConverterStore.getState().imageFile).toBeNull();
    expect(revoke).toHaveBeenCalledTimes(1);
    if (assetKey === "heightmap") expect(heightmapSignal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    await preparation;
  });

  it("restores the recipe device without changing daily defaults", () => {
    const restoreResult: RestoreResult = {
      state: {},
      assetFile: new File(["test"], "source.png", { type: "image/png" }),
      heightmapFile: null,
      warnings: [],
      recipe: makeRecipe(),
    };

    const dailySettings = useSettingsStore.getState();
    applyImport(restoreResult, PRINTERS);
    expect(useSettingsStore.getState()).toEqual(dailySettings);

    expect(effectiveSettings().printerModel).toBe("bambu-p1s");
    expect(effectiveSettings().slicerSoftware).toBe("OrcaSlicer");
    expect(effectiveSettings().nozzleSize).toBe("0.2");
    expect(effectiveSettings().deviceProfileId).toBe(
      "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
    );
    expect(effectiveSettings().buildPlateId).toBe(
      "smooth-high-temp-plate",
    );
  });

  it("restores the base-layer height modifier project setting", () => {
    const recipe = makeRecipe();
    recipe.recipe.converter!.device.enable_base_layer_height_modifier = false;
    useSettingsStore.setState({ enableBaseLayerHeightModifier: true });
    const restoreResult: RestoreResult = {
      state: {},
      assetFile: new File(["test"], "source.png", { type: "image/png" }),
      heightmapFile: null,
      warnings: [],
      recipe,
    };

    applyImport(restoreResult);

    expect(
      effectiveSettings().enableBaseLayerHeightModifier,
    ).toBe(false);
  });

  it("restores the wipe-tower auto-placement project setting", () => {
    const recipe = makeRecipe();
    recipe.recipe.converter!.device.enable_wipe_tower_auto_placement = false;
    useSettingsStore.setState({ enableWipeTowerAutoPlacement: true });
    const restoreResult: RestoreResult = {
      state: {},
      assetFile: new File(["test"], "source.png", { type: "image/png" }),
      heightmapFile: null,
      warnings: [],
      recipe,
    };

    applyImport(restoreResult);

    expect(
      effectiveSettings().enableWipeTowerAutoPlacement,
    ).toBe(false);
  });

  it("restores the dynamic material Delta-E00 tolerance", () => {
    const recipe = makeRecipe();
    recipe.recipe.converter!.source = {
      source_version: "material",
      selected_native_brand_key: "",
      selected_native_db_names: [],
      color_layers: null,
      layer_height_mm: null,
      model_enable: false,
      model_only: false,
      model_threshold: null,
      model_margin: null,
      selected_material_dir_names: ["brand/white"],
      material_layer_count: 7,
      material_layer_height_mm: 0.08,
      material_backing_material_dir_name: "brand/white",
      material_dynamic_layer_count_enabled: true,
      material_min_layer_count: 5,
      material_max_layer_count: 7,
      material_delta_e00_tolerance: 0.8,
    };
    const restoreResult: RestoreResult = {
      state: {},
      assetFile: new File(["test"], "source.png", { type: "image/png" }),
      heightmapFile: null,
      warnings: [],
      recipe,
    };

    applyImport(restoreResult);

    expect(effectiveSettings().materialDeltaE00Tolerance).toBe(0.8);
  });

  it("keeps imported dynamic result evidence after setImageFile invalidation", () => {
    const dynamicRecipe: DynamicMaterialRecipe = {
      target_srgb: [240, 220, 200],
      matched_srgb: [238, 218, 198],
      actual_layer_count: 5,
      padding_layer_count: 2,
      actual_recipe_top_to_bottom: [0, 1, 0, 1, 0],
      print_recipe_top_to_bottom: [0, 1, 0, 1, 0, 1, 1],
      selected_delta_e00: 0.7,
      best_range_delta_e00: 0.4,
      fixed_max_delta_e00: 0.5,
      delta_e00_sacrifice: 0.3,
      layer_cap_options: [],
    };
    const benefitCurve: MaterialLayerBenefitPoint[] = [
      {
        max_effective_layer_count: 5,
        weighted_mean_delta_e00: 0.7,
        marginal_delta_e00_reduction: 0.2,
      },
    ];
    const restoreResult: RestoreResult = {
      state: {
        source_version: "material",
        materialDynamicLayerCountEnabled: true,
        materialDynamicRecipes: [dynamicRecipe],
        materialLayerBenefitCurve: benefitCurve,
      },
      assetFile: new File(["test"], "source.png", { type: "image/png" }),
      heightmapFile: null,
      warnings: [],
      recipe: makeRecipe(),
    };

    applyImport(restoreResult);

    expect(useConverterStore.getState()).toMatchObject({
      materialDynamicRecipes: [dynamicRecipe],
      materialLayerBenefitCurve: benefitCurve,
    });
  });

  it("applies restored project color data after the embedded image reset", () => {
    const replacement = {
      quantized_hex: "aa0000",
      matched_hex: "bb0000",
      replacement_hex: "cc0000",
    };
    const historyEntry = {
      id: "project-recipe",
      recipe: [0, 1, 2, 3],
      layerOrder: "Top2Bottom",
      predictedRgb: [20, 30, 40] as [number, number, number],
      predictedLab: [10, 0, 0] as [number, number, number],
      hex: "141e28",
      fromModel: false,
      createdAtMs: 123,
    };
    const restoreResult: RestoreResult = {
      state: {
        replacement_regions: [replacement],
        free_color_set: new Set(["cc0000"]),
        customRecipeHistory: [historyEntry],
        regionReplacementCount: 0,
      },
      assetFile: new File(["test"], "source.png", { type: "image/png" }),
      heightmapFile: null,
      warnings: [],
      recipe: makeRecipe(),
    };

    applyImport(restoreResult);

    const state = useConverterStore.getState();
    expect(state.replacement_regions).toEqual([replacement]);
    expect(state.free_color_set).toEqual(new Set(["cc0000"]));
    expect(state.customRecipeHistory).toEqual([historyEntry]);
    expect(state.regionReplacementCount).toBe(0);
  });

  it("resolves device profile from imported printer slicer and nozzle when older recipe lacks it", () => {
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
    });

    const restoreResult: RestoreResult = {
      state: {},
      assetFile: new File(["test"], "source.png", { type: "image/png" }),
      heightmapFile: null,
      warnings: [],
      recipe: makeRecipe(null),
    };

    const dailySettings = useSettingsStore.getState();
    applyImport(restoreResult, PRINTERS);
    expect(useSettingsStore.getState()).toEqual(dailySettings);

    expect(effectiveSettings().printerModel).toBe("bambu-p1s");
    expect(effectiveSettings().slicerSoftware).toBe("OrcaSlicer");
    expect(effectiveSettings().nozzleSize).toBe("0.2");
    expect(effectiveSettings().deviceProfileId).toBe(
      "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
    );
  });

  it("falls back to the target device default for a cross-device plate", () => {
    const recipe = makeRecipe(
      "BambuStudio:bbl:bambu-lab-h2d:0.4",
      "engineering-plate",
    );
    recipe.recipe.converter!.device = {
      ...recipe.recipe.converter!.device,
      printer_id: "bambu-p1s",
      slicer: "OrcaSlicer",
      nozzle_size: "0.2",
    };
    useSettingsStore.setState({
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
      buildPlateId: "engineering-plate",
      buildPlateSelections: {
        "BambuStudio:bbl:bambu-lab-h2d": "engineering-plate",
        "OrcaSlicer:bbl:bambu-lab-p1s": "smooth-high-temp-plate",
      },
    });

    applyImport(
      {
        state: {},
        assetFile: new File(["test"], "source.png", { type: "image/png" }),
        heightmapFile: null,
        warnings: [],
        recipe,
      },
      PRINTERS,
    );

    expect(effectiveSettings()).toMatchObject({
      deviceProfileId: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
      buildPlateId: "textured-pei-plate",
    });
  });

  it("uses the target device default for a legacy recipe without a plate", () => {
    const recipe = makeRecipe(null, null);
    useSettingsStore.setState({
      deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
      buildPlateId: "engineering-plate",
      buildPlateSelections: {
        "BambuStudio:bbl:bambu-lab-h2d": "engineering-plate",
        "OrcaSlicer:bbl:bambu-lab-p1s": "smooth-high-temp-plate",
      },
    });

    applyImport(
      {
        state: {},
        assetFile: new File(["test"], "source.png", { type: "image/png" }),
        heightmapFile: null,
        warnings: [],
        recipe,
      },
      PRINTERS,
    );

    expect(effectiveSettings()).toMatchObject({
      deviceProfileId: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
      buildPlateId: "textured-pei-plate",
    });
  });

  it("clears the active plate when the imported target device has no plates", () => {
    const recipe = makeRecipe(
      "FlashStudio:flashforge:guider-3-ultra:0.4",
      "engineering-plate",
    );
    recipe.recipe.converter!.device = {
      ...recipe.recipe.converter!.device,
      printer_id: "flashforge-guider-3-ultra",
      slicer: "FlashStudio",
      nozzle_size: "0.2",
    };
    useSettingsStore.setState({
      buildPlateId: "engineering-plate",
      buildPlateSelections: {
        "BambuStudio:bbl:bambu-lab-h2d": "engineering-plate",
      },
    });

    applyImport(
      {
        state: {},
        assetFile: new File(["test"], "source.png", { type: "image/png" }),
        heightmapFile: null,
        warnings: [],
        recipe,
      },
      PRINTERS,
    );

    expect(effectiveSettings()).toMatchObject({
      nozzleSize: "0.4",
      deviceProfileId: "FlashStudio:flashforge:guider-3-ultra:0.4",
      buildPlateId: "",
    });
  });

  it("restores converter state first and then opens a valid workshop source for editing", () => {
    const source = createBeadRecipeSourceFixture();
    const recipe = makeRecipe();
    recipe.recipe.workshop = source;
    const assetFile = new File(["test"], "bead.png", {
      type: "image/png",
    });
    const restoreResult: RestoreResult = {
      state: {
        target_width_mm: 7.8,
        target_height_mm: 5.2,
        workshopSource: source,
      },
      assetFile,
      heightmapFile: null,
      warnings: [],
      recipe,
    };

    applyImport(restoreResult, [], { destination: "workshop" });

    expect(useConverterStore.getState().imageFile).toBe(assetFile);
    expect(useConverterStore.getState().target_width_mm).toBe(7.8);
    expect(useConverterStore.getState().workshopSource).toEqual(source);
    expect(useWorkshopStore.getState().activeModule).toEqual({
      moduleId: "lumina.bead-pattern",
      version: "1.0.0",
    });
    expect(useWorkshopStore.getState().pendingRecipeSource).toEqual(
      source,
    );
    expect(useWidgetStore.getState().activeTab).toBe("workshop");
  });

  it("keeps the normal import destination in converter even when editing data exists", () => {
    const source = createBeadRecipeSourceFixture();
    const recipe = makeRecipe();
    recipe.recipe.workshop = source;
    const restoreResult: RestoreResult = {
      state: { workshopSource: source },
      assetFile: new File(["test"], "bead.png", {
        type: "image/png",
      }),
      heightmapFile: null,
      warnings: [],
      recipe,
    };

    applyImport(restoreResult);

    expect(useConverterStore.getState().workshopSource).toEqual(source);
    expect(useWorkshopStore.getState().pendingRecipeSource).toBeNull();
    expect(useWidgetStore.getState().activeTab).toBe("converter");
  });

  it.each([
    ["share card", exportShareCard],
    ["JSON sidecar", exportSidecar],
  ])("rejects incomplete model-surface %s exports", async (_label, exporter) => {
    useConverterStore.setState({
      modelSurfaceEnabled: true,
      imageFile: new File(["image"], "source.png", { type: "image/png" }),
      previewImageUrl: "/api/files/preview.png",
    });

    await expect(exporter()).rejects.toThrow(
      MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR,
    );
  });

  it("passes workshop source to both PNG and JSON export builders", async () => {
    const source = createBeadRecipeSourceFixture();
    useConverterStore.setState({
      ...DEFAULT_STATE,
      imageFile: new File(["image"], "bead.png", {
        type: "image/png",
      }),
      previewImageUrl: "blob:preview",
      workshopSource: source,
    });
    const buildFullRecipe = vi.spyOn(
      exportRecipeModule,
      "buildFullRecipe",
    );
    vi.spyOn(exportRecipeModule, "buildCoverImage").mockResolvedValue({
      blob: new Blob(["cover"], { type: "image/png" }),
      cover: { width: 32, height: 32, mime_type: "image/png" },
    });
    vi.spyOn(
      pngMetadataModule,
      "embedRecipeInPng",
    ).mockResolvedValue(
      new Blob(["share"], { type: "image/png" }),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:download");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.spyOn(
      HTMLAnchorElement.prototype,
      "click",
    ).mockImplementation(() => undefined);

    await exportShareCard();
    await exportSidecar();

    expect(buildFullRecipe).toHaveBeenCalledTimes(2);
    expect(buildFullRecipe.mock.calls[0]?.[3]).toEqual(source);
    expect(buildFullRecipe.mock.calls[1]?.[3]).toEqual(source);
  });
});
