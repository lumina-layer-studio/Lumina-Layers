import { describe, it, expect } from "vitest";

import {
  detectRecipeFileType,
  matchLut,
  restoreConverterRecipe,
  validateWorkshopRecipeEnvelope,
  RECIPE_IMPORT_WARNING_BACK_LABELS_UNAVAILABLE,
  RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LARGE_FORMAT,
  RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LOOP,
  RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_PUZZLE,
  RECIPE_IMPORT_WARNING_LUT_DEGRADED,
  RECIPE_IMPORT_WARNING_LUT_MISSING,
  RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LARGE_FORMAT,
  RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LOOP,
  RECIPE_IMPORT_WARNING_SECONDARY_LUT_MISSING,
  RECIPE_IMPORT_WARNING_WORKSHOP_DEGRADED,
} from "../recipe/importRecipe";
import { migrateRecipe } from "../recipe/migration";
import type { LuminaRecipe } from "../recipe/types";
import type {
  DynamicMaterialRecipe,
  LutInfo,
  MaterialLayerBenefitPoint,
} from "../api/types";
import { ColorMode } from "../api/types";
import { exportConverterRecipe } from "../recipe/exportRecipe";
import type { ConverterState } from "../stores/converter/store";
import { DEFAULT_STATE } from "../stores/converter";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import { createBeadRecipeSourceFixture } from "./fixtures/beadRecipeSource";

// ========== Helpers ==========

const DYNAMIC_RECIPE: DynamicMaterialRecipe = {
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
  layer_cap_options: ([5, 6, 7] as const).map((cap) => ({
      max_effective_layer_count: cap,
      actual_layer_count: 5,
      matched_srgb: [238, 218, 198],
      actual_recipe_top_to_bottom: [0, 1, 0, 1, 0],
      print_recipe_top_to_bottom: [0, 1, 0, 1, 0, 1, 1],
      delta_e00: 0.7,
    })),
};

const BENEFIT_CURVE: MaterialLayerBenefitPoint[] = ([5, 6, 7] as const).map(
  (cap) => ({
    max_effective_layer_count: cap,
    weighted_mean_delta_e00: 0.7,
    marginal_delta_e00_reduction: 0.2,
  }),
);

function enableDynamicMaterial(recipe: LuminaRecipe): void {
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
    selected_material_dir_names: ["brand/red", "brand/white"],
    material_layer_count: 7,
    material_layer_height_mm: 0.08,
    material_backing_material_dir_name: "brand/white",
    material_dynamic_layer_count_enabled: true,
    material_min_layer_count: 5,
    material_max_layer_count: 7,
    material_delta_e00_tolerance: 0.7,
  };
}

function createTestRecipe(overrides?: Partial<LuminaRecipe>): LuminaRecipe {
  return {
    format: "lumina-recipe",
    schema_version: 1,
    app_version: "0.0.0",
    created_at: "2025-01-01T00:00:00.000Z",
    source: "converter",
    cover: { width: 100, height: 75, mime_type: "image/png" },
    asset: {
      primary: {
        filename: "photo.png",
        mime_type: "image/png",
        byte_size: 4,
        encoding: "base64",
        payload_b64: "dGVzdA==", // "test"
      },
    },
    recipe: {
      converter: {
        base: {
          lut: { name: "MyLUT", color_mode: "4-Color (RYBW)", path_hint: "/luts/my.json" },
          color_mode: "4-Color (RYBW)",
          modeling_mode: "high-fidelity",
          target_width_mm: 80,
          target_height_mm: 60,
          quantize_colors: 32,
          quantize_colors_unlocked: true,
          enable_cleanup: true,
          hue_enable: false,
          use_lut_constrained: true,
          auto_dynamic_range: true,
          chroma_gate: 0,
        },
        geometry: {
          spacer_thick: 0.6,
          structure_mode: "single-sided",
          separate_backing: false,
          add_loop: false,
          loop_width: 5,
          loop_length: 8,
          loop_hole: 3,
          loop_angle: 45,
          loop_offset_x: 1,
          loop_offset_y: -2,
          loop_position_preset: "top-right",
        },
        relief: {
          enable_relief: true,
          auto_height_mode: "darker-higher",
          color_height_map: { "#ff0000": 0.3, "#00ff00": 0.5 },
          heightmap_max_height: 0.8,
        },
        outline: { enable_outline: true, outline_width: 0.5 },
        cloisonne: { enable_cloisonne: false, wire_width_mm: 0.4, wire_height_mm: 0.3 },
        coating: { enable_coating: true, coating_height_mm: 0.15 },
        color_ops: {
          replacement_regions: [
            { quantized_hex: "#aa0000", matched_hex: "#bb0000", replacement_hex: "#cc0000" },
          ],
          free_color_set: ["#ff0000", "#00ff00"],
        },
        large_format: { large_format_enabled: false, tile_width_mm: 150, tile_height_mm: 120 },
        puzzle: {
          puzzle_enabled: true,
          puzzle_style: "irregular",
          puzzle_sizing_mode: "grid",
          piece_width_mm: 20,
          piece_height_mm: 20,
          puzzle_rows: 4,
          puzzle_cols: 5,
          target_piece_count: 20,
          puzzle_seed: 42,
          connector_style: "classic",
          labels_enabled: true,
          engrave_back_labels: false,
          irregularity_strength: 0.35,
          min_neck_width_mm: 1.2,
        },
        fridge_magnet: {
          enable_fridge_magnet: false,
          fridge_magnets: [],
        },
        device: { printer_id: "bambu-h2d", slicer: "BambuStudio", nozzle_size: "0.2" },
      },
    },
    compat: { min_schema_version: 1 },
    warnings: [],
    ...overrides,
  };
}

const LOCAL_LUTS: LutInfo[] = [
  { name: "MyLUT", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/luts/my.json" },
  { name: "OtherLUT", color_mode: ColorMode.SIX_COLOR, path: "/luts/other.json" },
];

// ========== Tests ==========

describe("recipe/importRecipe", () => {
  describe("detectRecipeFileType", () => {
    it("detects .lumina.json", () => {
      const file = new File(["{}"], "card.lumina.json", { type: "application/json" });
      expect(detectRecipeFileType(file)).toBe("json");
    });

    it("detects .png", () => {
      const file = new File([""], "share.png", { type: "image/png" });
      expect(detectRecipeFileType(file)).toBe("png");
    });

    it("returns null for unsupported types", () => {
      const file = new File([""], "photo.jpg", { type: "image/jpeg" });
      expect(detectRecipeFileType(file)).toBeNull();
    });
  });

  describe("matchLut", () => {
    it("requires compatible color mode metadata even for an existing record", () => {
      const result = matchLut({ name: "MyLUT", color_mode: ColorMode.BW, path_hint: "/luts/my.json" }, LOCAL_LUTS);
      expect(result.matched).toBe(false);
    });

    it("leaves duplicate names unresolved even if one record path matches", () => {
      const luts = [LOCAL_LUTS[0], { ...LOCAL_LUTS[0], path: "/luts/duplicate.json" }];
      expect(matchLut({ name: "MyLUT", color_mode: ColorMode.FOUR_COLOR_RYBW, path_hint: "/luts/my.json" }, luts).matched).toBe(false);
    });

    it("matches by the existing record path", () => {
      const result = matchLut({ name: "SomeName", color_mode: ColorMode.FOUR_COLOR_RYBW, path_hint: "/luts/my.json" }, LOCAL_LUTS);
      expect(result.matched).toBe(true);
      if (result.matched) {
        expect(result.lutName).toBe("MyLUT");
        expect(result.matchType).toBe("record");
      }
    });

    it("falls back to name match", () => {
      const result = matchLut({ name: "OtherLUT", color_mode: ColorMode.SIX_COLOR, path_hint: "missing-record" }, LOCAL_LUTS);
      expect(result.matched).toBe(true);
      if (result.matched) {
        expect(result.lutName).toBe("OtherLUT");
        expect(result.matchType).toBe("name");
      }
    });

    it("returns not matched when LUT is missing", () => {
      const result = matchLut({ name: "NonExistent", color_mode: ColorMode.FOUR_COLOR_RYBW }, LOCAL_LUTS);
      expect(result.matched).toBe(false);
      if (!result.matched) {
        expect(result.originalName).toBe("NonExistent");
      }
    });
  });

  describe("restoreConverterRecipe", () => {
    it("restores compressed color ownership with the saved project", () => {
      const recipe = createTestRecipe();
      const scope = { shape: [1, 2], bits: "eJxrAAAAgQCB" };
      recipe.recipe.converter!.color_ops.replacement_regions[0].source_scope = scope;
      const { state } = restoreConverterRecipe(JSON.parse(JSON.stringify(recipe)), LOCAL_LUTS);
      expect(state.replacement_regions?.[0].source_scope).toEqual(scope);
    });

    it("restores all converter parameters", () => {
      const recipe = createTestRecipe();
      const { state, assetFile, warnings } = restoreConverterRecipe(recipe, LOCAL_LUTS);

      // Base params
      expect(state.lut_name).toBe("MyLUT");
      expect(state.target_width_mm).toBe(80);
      expect(state.target_height_mm).toBe(60);
      expect(state.quantize_colors_unlocked).toBe(true);
      expect(state.hue_enable).toBe(false);
      expect(state.use_lut_constrained).toBe(true);
      expect(state.auto_dynamic_range).toBe(true);

      // Geometry
      expect(state.spacer_thick).toBe(0.6);
      expect(state.add_loop).toBe(false);
      expect(state.loop_angle).toBe(45);
      expect(state.loop_position_preset).toBe("top-right");

      // Relief
      expect(state.enable_relief).toBe(true);
      // Hex keys should have '#' stripped for store
      expect(state.color_height_map).toEqual({ ff0000: 0.3, "00ff00": 0.5 });

      // Color ops — hex stripped
      expect(state.replacement_regions).toHaveLength(1);
      expect(state.replacement_regions![0].quantized_hex).toBe("aa0000");
      expect(state.free_color_set).toEqual(new Set(["ff0000", "00ff00"]));

      // Large format
      expect(state.largeFormatEnabled).toBe(false);
      expect(state.tileWidthMm).toBe(150);

      // Puzzle
      expect(state.puzzleEnabled).toBe(true);
      expect(state.puzzleStyle).toBe("irregular");
      expect(state.puzzleSizingMode).toBe("grid");
      expect(state.puzzleRows).toBe(4);
      expect(state.puzzleCols).toBe(5);
      expect(state.connectorStyle).toBe("classic");
      expect(state.labelsEnabled).toBe(true);
      expect(state.enable_fridge_magnet).toBe(false);
      expect(state.fridge_magnets).toEqual([]);
      expect(state.base_spacer_thick).toBe(0.6);

      // Model-surface state is session-bound and must never leak into an
      // imported recipe that cannot reproduce the uploaded model and face.
      expect(state.modelSurfaceEnabled).toBe(false);
      expect(state.modelSurfaceFile).toBeNull();
      expect(state.modelSurfacePreviewUrl).toBeNull();
      expect(state.modelSurfaceModelFileId).toBeNull();
      expect(state.modelSurfaceSummary).toBeNull();
      expect(state.modelSurfaceSelectionId).toBeNull();
      expect(state.modelSurfaceSelection).toBeNull();
      expect(state.modelSurfaceFootprint).toBeNull();
      expect(state.modelSurfaceCandidates).toEqual([]);
      expect(state.modelSurfacePlacement).toEqual({
        mode: "edge_to_edge",
        offset_x_mm: 0,
        offset_y_mm: 0,
        scale: 1,
        rotation_deg: 0,
        inset_mm: 0,
      });
      expect(state.modelSurfaceModelRotation).toEqual({
        x_deg: 0,
        y_deg: 0,
        z_deg: 0,
      });
      expect(state.modelSurfaceLoading).toBe(false);
      expect(state.modelSurfaceSelecting).toBe(false);
      expect(state.modelSurfaceError).toBeNull();
      expect(state.modelSurfaceWarnings).toEqual([]);

      // Asset
      expect(assetFile).toBeInstanceOf(File);
      expect(assetFile.name).toBe("photo.png");

      // No warnings for record match
      expect(warnings).toHaveLength(0);
    });

    it("uses legacy-safe defaults for omitted project matching flags", () => {
      const recipe = createTestRecipe();
      delete recipe.recipe.converter!.base.quantize_colors_unlocked;
      delete recipe.recipe.converter!.base.use_lut_constrained;
      delete recipe.recipe.converter!.base.auto_dynamic_range;
      recipe.recipe.converter!.base.quantize_colors = 512;

      const { state } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );

      expect(state.quantize_colors_unlocked).toBe(true);
      expect(state.use_lut_constrained).toBe(false);
      expect(state.auto_dynamic_range).toBe(false);
    });

    it("restores converter source parameters used by share cards", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.source = {
        source_version: "native",
        selected_native_brand_key: "bambulab_pla",
        selected_native_db_names: ["PLA Basic", "PLA Matte"],
        color_layers: 6,
        layer_height_mm: 0.08,
        model_enable: true,
        model_only: false,
        model_threshold: 0.42,
        model_margin: 3,
        selected_material_dir_names: ["brand/red", "brand/white"],
        material_layer_count: 10,
        material_layer_height_mm: 0.06,
        material_backing_material_dir_name: "brand/white",
      };

      const { state } = restoreConverterRecipe(recipe, LOCAL_LUTS);

      expect(state.source_version).toBe("native");
      expect(state.selectedNativeBrandKey).toBe("bambulab_pla");
      expect(state.selectedNativeDbNames).toEqual(["PLA Basic", "PLA Matte"]);
      expect(state.color_layers).toBe(6);
      expect(state.layer_height_mm).toBe(0.08);
      expect(state.model_enable).toBe(true);
      expect(state.model_only).toBe(false);
      expect(state.model_threshold).toBe(0.42);
      expect(state.model_margin).toBe(3);
      expect(state.selectedMaterialDirNames).toEqual(["brand/red", "brand/white"]);
      expect(state.materialLayerCount).toBe(10);
      expect(state.materialLayerHeightMm).toBe(0.06);
      expect(state.materialBackingMaterialDirName).toBe("brand/white");
    });

    it("restores dynamic material bounds and keeps absent result metadata empty", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.base.hue_enable = true;
      enableDynamicMaterial(recipe);

      const { state } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );

      expect(state).toMatchObject({
        source_version: "material",
        materialDynamicLayerCountEnabled: true,
        materialMinLayerCount: 5,
        materialMaxLayerCount: 7,
        hue_enable: false,
        materialDynamicRecipes: [],
        materialLayerBenefitCurve: [],
      });
    });

    it("deep-clones valid imported dynamic result metadata", () => {
      const recipe = createTestRecipe();
      enableDynamicMaterial(recipe);
      const importedMetadata = {
        recipes: [DYNAMIC_RECIPE],
        benefit_curve: BENEFIT_CURVE,
      };
      recipe.recipe.converter!.material_dynamic = importedMetadata;

      const { state } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );

      expect(state.materialDynamicRecipes).toEqual([DYNAMIC_RECIPE]);
      expect(state.materialLayerBenefitCurve).toEqual(BENEFIT_CURVE);
      expect(state.materialDynamicRecipes).not.toBe(importedMetadata.recipes);
      expect(state.materialDynamicRecipes![0]).not.toBe(DYNAMIC_RECIPE);
      expect(state.materialDynamicRecipes![0].target_srgb).not.toBe(
        DYNAMIC_RECIPE.target_srgb,
      );
      expect(state.materialDynamicRecipes![0].layer_cap_options[0]).not.toBe(
        DYNAMIC_RECIPE.layer_cap_options[0],
      );
      expect(state.materialLayerBenefitCurve).not.toBe(BENEFIT_CURVE);
      expect(state.materialLayerBenefitCurve![0]).not.toBe(BENEFIT_CURVE[0]);
      expect(state.materialLayerBenefitScope).toBe("all_printable_pixels");
      expect(state.materialLayerBenefitPixelCount).toBe(0);
    });

    it("clears invalid or inapplicable imported dynamic result metadata", () => {
      const invalidRecipe = createTestRecipe();
      enableDynamicMaterial(invalidRecipe);
      (
        invalidRecipe.recipe.converter as unknown as {
          material_dynamic: unknown;
        }
      ).material_dynamic = {
        recipes: [
          {
            ...DYNAMIC_RECIPE,
            print_recipe_top_to_bottom: [0],
          },
        ],
        benefit_curve: BENEFIT_CURVE,
      };

      const invalidState = restoreConverterRecipe(
        invalidRecipe,
        LOCAL_LUTS,
      ).state;
      expect(invalidState.materialDynamicRecipes).toEqual([]);
      expect(invalidState.materialLayerBenefitCurve).toEqual([]);

      const inapplicableRecipe = createTestRecipe();
      inapplicableRecipe.recipe.converter!.material_dynamic = {
        recipes: [DYNAMIC_RECIPE],
        benefit_curve: BENEFIT_CURVE,
      };
      const inapplicableState = restoreConverterRecipe(
        inapplicableRecipe,
        LOCAL_LUTS,
      ).state;
      expect(inapplicableState.materialDynamicRecipes).toEqual([]);
      expect(inapplicableState.materialLayerBenefitCurve).toEqual([]);
    });

    it("preserves dynamic result metadata across export-import-export", () => {
      const state = {
        ...DEFAULT_STATE,
        source_version: "material",
        selectedMaterialDirNames: ["brand/red", "brand/white"],
        materialBackingMaterialDirName: "brand/white",
        materialDynamicLayerCountEnabled: true,
        materialMinLayerCount: 5,
        materialMaxLayerCount: 7,
        materialDynamicRecipes: [DYNAMIC_RECIPE],
        materialLayerBenefitCurve: BENEFIT_CURVE,
        materialLayerBenefitScope: "automatic_pixels",
        materialLayerBenefitPixelCount: 37,
      } as ConverterState;
      const firstExport = exportConverterRecipe(
        state,
        { ...DEFAULT_SETTINGS, materialDeltaE00Tolerance: 0.7 },
        "fp123",
      );
      const recipe = createTestRecipe();
      recipe.recipe.converter = firstExport;
      const restored = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );
      const secondExport = exportConverterRecipe(
        { ...state, ...restored.state } as ConverterState,
        { ...DEFAULT_SETTINGS, materialDeltaE00Tolerance: 0.7 },
        "fp123",
      );

      expect(secondExport.material_dynamic).toEqual(
        firstExport.material_dynamic,
      );
      expect(secondExport.material_dynamic).not.toBe(
        firstExport.material_dynamic,
      );
    });

    it("normalizes puzzle-specific mutually exclusive settings from imported recipes", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.geometry.add_loop = true;
      recipe.recipe.converter!.large_format.large_format_enabled = true;
      recipe.recipe.converter!.puzzle!.labels_enabled = false;
      recipe.recipe.converter!.puzzle!.engrave_back_labels = true;

      const { state, warnings } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );

      expect(state.puzzleEnabled).toBe(true);
      expect(state.largeFormatEnabled).toBe(false);
      expect(state.add_loop).toBe(false);
      expect(state.labelsEnabled).toBe(false);
      expect(state.engraveBackLabels).toBe(false);
      expect(
        warnings,
      ).toContain(RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LARGE_FORMAT);
      expect(
        warnings,
      ).toContain(RECIPE_IMPORT_WARNING_PUZZLE_CONFLICT_LOOP);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_BACK_LABELS_UNAVAILABLE);
    });

    it("disables imported back-label engraving even when piece labels are enabled", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.puzzle!.labels_enabled = true;
      recipe.recipe.converter!.puzzle!.engrave_back_labels = true;

      const { state, warnings } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );

      expect(state.labelsEnabled).toBe(true);
      expect(state.engraveBackLabels).toBe(false);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_BACK_LABELS_UNAVAILABLE);
    });

    it("keeps fridge magnet mode and disables puzzle, large format, and loop conflicts from imported recipes", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.geometry.structure_mode = "Double-sided";
      recipe.recipe.converter!.geometry.spacer_thick = 1.1;
      recipe.recipe.converter!.geometry.add_loop = true;
      recipe.recipe.converter!.large_format.large_format_enabled = true;
      recipe.recipe.converter!.puzzle!.puzzle_enabled = true;
      recipe.recipe.converter!.fridge_magnet = {
        enable_fridge_magnet: true,
        fridge_magnets: [
          {
            id: "magnet-round",
            shape: "round",
            preset_key: "round-d12x3",
            diameter_mm: 12,
            width_mm: null,
            height_mm: null,
            thickness_mm: 3,
            center_x_mm: 40,
            center_y_mm: 20,
          },
        ],
      };

      const { state, warnings } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );

      expect(state.enable_fridge_magnet).toBe(true);
      expect(state.fridge_magnets).toHaveLength(1);
      expect(state.puzzleEnabled).toBe(false);
      expect(state.largeFormatEnabled).toBe(false);
      expect(state.add_loop).toBe(false);
      expect(state.structure_mode).toBe("Single-sided");
      expect(state.base_spacer_thick).toBe(1.1);
      expect(state.spacer_thick).toBe(3.44);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_PUZZLE);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LARGE_FORMAT);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_FRIDGE_CONFLICT_LOOP);
    });

    it("normalizes imported fridge magnets before restoring them", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.geometry.spacer_thick = 0.7;
      recipe.recipe.converter!.fridge_magnet = {
        enable_fridge_magnet: true,
        fridge_magnets: [
          {
            id: "bad-round",
            shape: "round",
            preset_key: "rect-20x10x2",
            diameter_mm: 0.2,
            width_mm: 8,
            height_mm: 9,
            thickness_mm: 9,
            center_x_mm: 5,
            center_y_mm: 6,
          },
          {
            id: "bad-rect",
            shape: "rect",
            preset_key: "round-d6x2",
            diameter_mm: 7,
            width_mm: 0.2,
            height_mm: 0.1,
            thickness_mm: 0.05,
            center_x_mm: -2,
            center_y_mm: -3,
          },
        ],
      };

      const { state } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );

      expect(state.fridge_magnets).toEqual([
        {
          id: "bad-round",
          shape: "round",
          preset_key: "custom",
          diameter_mm: 1,
          width_mm: null,
          height_mm: null,
          thickness_mm: 3.1,
          center_x_mm: 5,
          center_y_mm: 6,
        },
        {
          id: "bad-rect",
          shape: "rect",
          preset_key: "custom",
          diameter_mm: null,
          width_mm: 1,
          height_mm: 1,
          thickness_mm: 0.1,
          center_x_mm: -2,
          center_y_mm: -3,
        },
      ]);
      expect(state.base_spacer_thick).toBe(0.7);
      expect(state.spacer_thick).toBe(3.52);
    });

    it("adds warning for name-only LUT match", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.base.lut.path_hint = "missing-record";
      const { warnings, state } = restoreConverterRecipe(recipe, LOCAL_LUTS);

      expect(state.lut_name).toBe("MyLUT"); // Still matches by name
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_LUT_DEGRADED);
    });

    it("adds warning for missing LUT", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.base.lut.name = "GoneLUT";
      recipe.recipe.converter!.base.lut.path_hint = "missing-record";
      const { state, warnings } = restoreConverterRecipe(recipe, LOCAL_LUTS);

      expect(state.lut_name).toBe(""); // Empty — user must select manually
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_LUT_MISSING);
    });

    it("restores existing secondary legacy LUT names and warns for missing ones", () => {
      const recipe = createTestRecipe();
      recipe.recipe.converter!.source = {
        source_version: "legacy",
        selected_legacy_lut_names: ["MyLUT", "OtherLUT", "MissingLUT"],
        selected_native_brand_key: "",
        selected_native_db_names: [],
        color_layers: null,
        layer_height_mm: null,
        model_enable: false,
        model_only: false,
        model_threshold: null,
        model_margin: null,
        selected_material_dir_names: [],
        material_layer_count: 5,
        material_layer_height_mm: 0.08,
        material_backing_material_dir_name: null,
      };

      const { state, warnings } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );

      expect(state.lut_name).toBe("MyLUT");
      expect(state.lut_names).toEqual(["MyLUT", "OtherLUT"]);
      expect(warnings).toContain(RECIPE_IMPORT_WARNING_SECONDARY_LUT_MISSING);
    });

    it("clears session and preview state", () => {
      const recipe = createTestRecipe();
      const { state } = restoreConverterRecipe(recipe, LOCAL_LUTS);

      expect(state.sessionId).toBeNull();
      expect(state.previewImageUrl).toBeNull();
      expect(state.modelUrl).toBeNull();
      expect(state.hasManualPreview).toBe(false);
    });

    it("restores heightmap asset when present", () => {
      const recipe = createTestRecipe();
      recipe.asset.heightmap = {
        filename: "height.png",
        mime_type: "image/png",
        byte_size: 4,
        encoding: "base64",
        payload_b64: "AAAA",
      };
      const { heightmapFile } = restoreConverterRecipe(recipe, LOCAL_LUTS);
      expect(heightmapFile).toBeInstanceOf(File);
      expect(heightmapFile!.name).toBe("height.png");
    });

    it("restores a valid bead workshop source without its original screenshot", () => {
      const recipe = createTestRecipe({ schema_version: 3 });
      const source = createBeadRecipeSourceFixture();
      recipe.recipe.workshop = source;

      const { state, warnings } = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );

      expect(state.workshopSource).toEqual(source);
      expect(state.workshopSource?.payload).toMatchObject({
        rows: 2,
        columns: 3,
        beadPitchMm: 2.6,
        compression: 73,
      });
      expect(JSON.stringify(state.workshopSource)).not.toContain(
        "share-card-bead",
      );
      expect(warnings).not.toContain(
        RECIPE_IMPORT_WARNING_WORKSHOP_DEGRADED,
      );
    });

    it("degrades a malformed workshop envelope without blocking converter restore", () => {
      const malformed = createTestRecipe({ schema_version: 3 });
      const malformedSource = createBeadRecipeSourceFixture();
      malformedSource.moduleId = "Invalid Module ID";
      malformed.recipe.workshop = malformedSource;

      const malformedResult = restoreConverterRecipe(
        malformed,
        LOCAL_LUTS,
      );
      expect(malformedResult.state.workshopSource).toBeNull();
      expect(malformedResult.state.target_width_mm).toBe(80);
      expect(malformedResult.assetFile.name).toBe("photo.png");
      expect(malformedResult.warnings).toContain(
        RECIPE_IMPORT_WARNING_WORKSHOP_DEGRADED,
      );
    });

    it("keeps a structurally valid source for a module that is not installed", () => {
      const unavailable = createTestRecipe({ schema_version: 3 });
      const unavailableSource = createBeadRecipeSourceFixture();
      unavailableSource.moduleId = "third-party.unknown";
      unavailable.recipe.workshop = unavailableSource;
      const unavailableResult = restoreConverterRecipe(
        unavailable,
        LOCAL_LUTS,
      );
      expect(unavailableResult.state.workshopSource).toEqual(
        unavailableSource,
      );
      expect(unavailableResult.warnings).not.toContain(
        RECIPE_IMPORT_WARNING_WORKSHOP_DEGRADED,
      );
    });

    it("degrades an envelope above 1 MiB to converter-only import", () => {
      const recipe = createTestRecipe({ schema_version: 3 });
      const oversized = createBeadRecipeSourceFixture();
      oversized.payload = {
        privateProject: "x".repeat(1024 * 1024),
      };
      recipe.recipe.workshop = oversized;

      const result = restoreConverterRecipe(
        recipe,
        LOCAL_LUTS,
      );

      expect(result.state.workshopSource).toBeNull();
      expect(result.state.target_width_mm).toBe(80);
      expect(result.assetFile.name).toBe("photo.png");
      expect(result.warnings).toContain(
        RECIPE_IMPORT_WARNING_WORKSHOP_DEGRADED,
      );
    });

    it("validates and deep-clones only a module-independent JSON envelope", () => {
      const source = createBeadRecipeSourceFixture();
      const validated = validateWorkshopRecipeEnvelope(source);

      expect(validated).toEqual(source);
      expect(validated).not.toBe(source);
      expect(validated?.payload).not.toBe(source.payload);
      expect(
        validateWorkshopRecipeEnvelope({
          ...source,
          payload: [],
        }),
      ).toBeNull();
      expect(
        validateWorkshopRecipeEnvelope({
          ...source,
          moduleVersion: "1.0",
        }),
      ).toBeNull();
    });

    it.each([1, 2])(
      "imports legacy schema v%s without workshop degradation",
      (schemaVersion) => {
        const recipe = createTestRecipe({
          schema_version: schemaVersion,
        });
        const result = restoreConverterRecipe(
          recipe,
          LOCAL_LUTS,
        );
        expect(result.state.workshopSource).toBeNull();
        expect(result.warnings).not.toContain(
          RECIPE_IMPORT_WARNING_WORKSHOP_DEGRADED,
        );
      },
    );
  });
});

describe("recipe/migration", () => {
  it("migrates V1 to the editable V4 format", () => {
    const recipe = createTestRecipe();
    const migrated = migrateRecipe(recipe);
    expect(migrated.schema_version).toBe(5);
    expect(migrated.recipe.converter).toEqual(recipe.recipe.converter);
  });

  it("migrates V2 without inventing workshop data", () => {
    const recipe = createTestRecipe({ schema_version: 2 });
    const migrated = migrateRecipe(recipe);
    expect(migrated.schema_version).toBe(5);
    expect(migrated.recipe.workshop).toBeUndefined();
  });

  it("rejects invalid format", () => {
    expect(() => migrateRecipe({ format: "not-lumina" })).toThrow("Invalid recipe format");
  });

  it("rejects schema version 0", () => {
    expect(() => migrateRecipe({ format: "lumina-recipe", schema_version: 0 })).toThrow(
      "Unsupported recipe schema version",
    );
  });

  it("adds warning for future schema version", () => {
    const future = createTestRecipe({ schema_version: 99 });
    const migrated = migrateRecipe(future);
    expect(migrated.warnings.some((w) => w.includes("schema version 99"))).toBe(true);
  });

  it("rejects non-object input", () => {
    expect(() => migrateRecipe(null)).toThrow("not an object");
    expect(() => migrateRecipe("string")).toThrow("not an object");
  });
});
