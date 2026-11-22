import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { fileToBase64, base64ToFile } from "../recipe/utils";
import { exportConverterRecipe } from "../recipe/exportRecipe";
import { restoreConverterRecipe } from "../recipe/importRecipe";
import { resolveFridgeMagnetSpacerThick } from "../constants/fridgeMagnets";
import { DEFAULT_STATE } from "../stores/converter";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import type { ConverterState } from "../stores/converter/store";
import type { LutInfo } from "../api/types";
import { ColorMode } from "../api/types";
import { createBeadRecipeSourceFixture } from "./fixtures/beadRecipeSource";

// ========== Arbitraries ==========

const arbHexColor = fc
  .array(fc.constantFrom(..."0123456789abcdef".split("")), { minLength: 6, maxLength: 6 })
  .map((chars) => chars.join(""));

const arbBytes = fc.uint8Array({ minLength: 1, maxLength: 128 });

const arbFilename = fc
  .array(fc.constantFrom(..."abcdefghijklmnopqrstuvwxyz0123456789".split("")), {
    minLength: 1,
    maxLength: 20,
  })
  .map((chars) => `${chars.join("")}.png`);

const arbMimeType = fc.constantFrom("image/png", "image/jpeg", "image/webp");

// ========== Property Tests ==========

describe("recipe round-trip properties", () => {
  it("base64 round-trip preserves file name, type, and content", async () => {
    await fc.assert(
      fc.asyncProperty(arbBytes, arbFilename, arbMimeType, async (bytes, name, mime) => {
        const original = new File([bytes], name, { type: mime });
        const b64 = await fileToBase64(original);
        const restored = base64ToFile(b64, name, mime);

        expect(restored.name).toBe(name);
        expect(restored.type).toBe(mime);
        expect(restored.size).toBe(original.size);

        const origBuf = new Uint8Array(await original.arrayBuffer());
        const restBuf = new Uint8Array(await restored.arrayBuffer());
        expect(restBuf).toEqual(origBuf);
      }),
      { numRuns: 30 },
    );
  });

  it("export → import round-trip preserves key converter parameters", () => {
    const arbState = fc.record({
      source_version: fc.constantFrom("legacy", "native", "material" as const),
      lut_name: fc.constantFrom("LUT-A", "LUT-B"),
      selectedNativeBrandKey: fc.constantFrom("", "bambulab_pla", "brand-b"),
      selectedNativeDbNames: fc.array(fc.constantFrom("PLA Basic", "PLA Matte", "PETG HF"), {
        maxLength: 3,
      }),
      color_layers: fc.option(fc.integer({ min: 1, max: 12 }), { nil: null }),
      layer_height_mm: fc.option(fc.constantFrom(0.04, 0.06, 0.08, 0.12), { nil: null }),
      model_enable: fc.boolean(),
      model_only: fc.boolean(),
      model_threshold: fc.option(fc.double({ min: 0, max: 1, noNaN: true }), { nil: null }),
      model_margin: fc.option(fc.integer({ min: 0, max: 8 }), { nil: null }),
      selectedMaterialDirNames: fc.array(
        fc.constantFrom("brand/red", "brand/white", "brand/black", "brand/yellow"),
        { maxLength: 4 },
      ),
      materialLayerCount: fc.integer({ min: 1, max: 12 }),
      materialLayerHeightMm: fc.constantFrom(0.04, 0.06, 0.08, 0.12),
      materialBackingMaterialDirName: fc.option(
        fc.constantFrom("brand/red", "brand/white", "brand/black", "brand/yellow"),
        { nil: null },
      ),
      target_width_mm: fc.integer({ min: 10, max: 400 }),
      target_height_mm: fc.integer({ min: 10, max: 400 }),
      spacer_thick: fc.double({ min: 0.2, max: 10, noNaN: true }),
      backing_infill_density_percent: fc.integer({ min: 5, max: 100 }),
      enable_wipe_tower_auto_placement: fc.boolean(),
      quantize_colors: fc.integer({ min: 2, max: 128 }),
      high_precision_3d_preview: fc.boolean(),
      enable_cleanup: fc.boolean(),
      hue_enable: fc.boolean(),
      chroma_gate: fc.integer({ min: 0, max: 100 }),
      add_loop: fc.boolean(),
      loop_angle: fc.integer({ min: -180, max: 180 }),
      enable_relief: fc.boolean(),
      enable_outline: fc.boolean(),
      outline_width: fc.double({ min: 0.1, max: 2.0, noNaN: true }),
      enable_cloisonne: fc.boolean(),
      enable_coating: fc.boolean(),
      coating_height_mm: fc.constantFrom(0.04, 0.08, 0.12),
      largeFormatEnabled: fc.boolean(),
      tileWidthMm: fc.integer({ min: 50, max: 500 }),
      tileHeightMm: fc.integer({ min: 50, max: 500 }),
      puzzleEnabled: fc.boolean(),
      puzzleStyle: fc.constantFrom("regular", "irregular" as const),
      puzzleSizingMode: fc.constantFrom("piece_size", "grid", "piece_count" as const),
      puzzleRows: fc.integer({ min: 1, max: 20 }),
      puzzleCols: fc.integer({ min: 1, max: 20 }),
      targetPieceCount: fc.integer({ min: 2, max: 100 }),
      connectorStyle: fc.constantFrom("classic", "easy_cut" as const),
      labelsEnabled: fc.boolean(),
      engraveBackLabels: fc.boolean(),
      enable_fridge_magnet: fc.boolean(),
      base_spacer_thick: fc.double({ min: 0.2, max: 10, noNaN: true }),
      fridge_magnets: fc.array(
        fc.oneof(
          fc.record({
            id: fc.uuid(),
            shape: fc.constant("round" as const),
            preset_key: fc.constantFrom("round-d6x2", "round-d8x3", "round-d10x3", "round-d12x3"),
            diameter_mm: fc.constantFrom(6, 8, 10, 12),
            width_mm: fc.constant(null),
            height_mm: fc.constant(null),
            thickness_mm: fc.constantFrom(2, 3),
            center_x_mm: fc.double({ min: -200, max: 200, noNaN: true }),
            center_y_mm: fc.double({ min: -200, max: 200, noNaN: true }),
          }),
          fc.record({
            id: fc.uuid(),
            shape: fc.constant("rect" as const),
            preset_key: fc.constantFrom("rect-10x5x1", "rect-15x5x2", "rect-20x10x2"),
            diameter_mm: fc.constant(null),
            width_mm: fc.constantFrom(10, 15, 20),
            height_mm: fc.constantFrom(5, 10),
            thickness_mm: fc.constantFrom(1, 2),
            center_x_mm: fc.double({ min: -200, max: 200, noNaN: true }),
            center_y_mm: fc.double({ min: -200, max: 200, noNaN: true }),
          }),
        ),
        { maxLength: 4 },
      ),
    });

    const localLuts: LutInfo[] = [
      { name: "LUT-A", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/a" },
      { name: "LUT-B", color_mode: ColorMode.SIX_COLOR, path: "/b" },
    ];
    const pathForLut: Record<string, string> = { "LUT-A": "/a", "LUT-B": "/b" };

    fc.assert(
      fc.property(arbState, (overrides) => {
        const baseSpacerThick = overrides.enable_fridge_magnet
          ? overrides.base_spacer_thick
          : overrides.spacer_thick;
        const state = {
          ...DEFAULT_STATE,
          ...overrides,
          color_mode: localLuts.find((lut) => lut.name === overrides.lut_name)!.color_mode,
          base_spacer_thick: baseSpacerThick,
          spacer_thick: resolveFridgeMagnetSpacerThick(
            baseSpacerThick,
            overrides.enable_fridge_magnet,
            overrides.fridge_magnets,
          ),
          structure_mode: overrides.enable_fridge_magnet
            ? "Single-sided"
            : DEFAULT_STATE.structure_mode,
        } as ConverterState;
        const recipe = exportConverterRecipe(
          state,
          {
            ...DEFAULT_SETTINGS,
            enableWipeTowerAutoPlacement:
              overrides.enable_wipe_tower_auto_placement,
          },
          pathForLut[overrides.lut_name],
        );
        expect(recipe.puzzle.engrave_back_labels).toBe(false);

        // Build a minimal LuminaRecipe wrapper for restoreConverterRecipe
        const fullRecipe = {
          format: "lumina-recipe" as const,
          schema_version: 1,
          app_version: "0.0.0",
          created_at: new Date().toISOString(),
          source: "converter" as const,
          cover: { width: 1, height: 1, mime_type: "image/png" as const },
          asset: {
            primary: {
              filename: "test.png",
              mime_type: "image/png",
              byte_size: 4,
              encoding: "base64" as const,
              payload_b64: "dGVzdA==",
            },
          },
          recipe: { converter: recipe },
          compat: { min_schema_version: 1 },
          warnings: [] as string[],
        };

        const { state: restored } = restoreConverterRecipe(fullRecipe, localLuts);
        const expectedLargeFormatEnabled = overrides.puzzleEnabled
          ? false
          : overrides.enable_fridge_magnet
            ? false
            : overrides.largeFormatEnabled;
        const expectedAddLoop = overrides.add_loop && !overrides.puzzleEnabled
          && !overrides.enable_fridge_magnet && !expectedLargeFormatEnabled;
        const expectedPuzzleEnabled = overrides.enable_fridge_magnet
          ? false
          : overrides.puzzleEnabled;
        const expectedStructureMode = overrides.enable_fridge_magnet
          ? "Single-sided"
          : state.structure_mode;
        const expectedSpacerThick = resolveFridgeMagnetSpacerThick(
          baseSpacerThick,
          overrides.enable_fridge_magnet,
          overrides.fridge_magnets,
        );

        // Key parameters must survive round-trip
        expect(restored.source_version).toBe(overrides.source_version);
        expect(restored.lut_name).toBe(
          overrides.source_version === "legacy" ? overrides.lut_name : "",
        );
        expect(restored.lut_names).toEqual(
          overrides.source_version === "legacy" ? [overrides.lut_name] : [],
        );
        expect(restored.selectedNativeBrandKey).toBe(overrides.selectedNativeBrandKey);
        expect(restored.selectedNativeDbNames).toEqual(overrides.selectedNativeDbNames);
        expect(restored.color_layers).toBe(overrides.color_layers);
        expect(restored.layer_height_mm).toBe(overrides.layer_height_mm);
        expect(restored.model_enable).toBe(overrides.model_enable);
        expect(restored.model_only).toBe(overrides.model_only);
        expect(restored.model_threshold).toBe(overrides.model_threshold);
        expect(restored.model_margin).toBe(overrides.model_margin);
        expect(restored.selectedMaterialDirNames).toEqual(overrides.selectedMaterialDirNames);
        expect(restored.materialLayerCount).toBe(overrides.materialLayerCount);
        expect(restored.materialLayerHeightMm).toBe(overrides.materialLayerHeightMm);
        expect(restored.materialBackingMaterialDirName).toBe(overrides.materialBackingMaterialDirName);
        expect(restored.target_width_mm).toBe(overrides.target_width_mm);
        expect(restored.target_height_mm).toBe(overrides.target_height_mm);
        expect(restored.quantize_colors).toBe(overrides.quantize_colors);
        expect(restored.high_precision_3d_preview).toBe(overrides.high_precision_3d_preview);
        expect(restored.enable_cleanup).toBe(overrides.enable_cleanup);
        expect(restored.hue_enable).toBe(overrides.hue_enable);
        expect(restored.chroma_gate).toBe(overrides.chroma_gate);
        expect(restored.add_loop).toBe(expectedAddLoop);
        expect(restored.loop_angle).toBe(overrides.loop_angle);
        expect(restored.enable_relief).toBe(overrides.enable_relief);
        expect(restored.enable_outline).toBe(overrides.enable_outline);
        expect(restored.enable_cloisonne).toBe(overrides.enable_cloisonne);
        expect(restored.enable_coating).toBe(overrides.enable_coating);
        expect(restored.coating_height_mm).toBe(overrides.coating_height_mm);
        expect(restored.largeFormatEnabled).toBe(expectedLargeFormatEnabled);
        expect(restored.tileWidthMm).toBe(overrides.tileWidthMm);
        expect(restored.tileHeightMm).toBe(overrides.tileHeightMm);
        expect(restored.puzzleEnabled).toBe(expectedPuzzleEnabled);
        expect(restored.puzzleStyle).toBe(overrides.puzzleStyle);
        expect(restored.puzzleSizingMode).toBe(overrides.puzzleSizingMode);
        expect(restored.puzzleRows).toBe(overrides.puzzleRows);
        expect(restored.puzzleCols).toBe(overrides.puzzleCols);
        expect(restored.targetPieceCount).toBe(overrides.targetPieceCount);
        expect(restored.connectorStyle).toBe(overrides.connectorStyle);
        expect(restored.labelsEnabled).toBe(overrides.labelsEnabled);
        expect(restored.engraveBackLabels).toBe(false);
        expect(recipe.geometry.spacer_thick).toBe(baseSpacerThick);
        expect(restored.enable_fridge_magnet).toBe(overrides.enable_fridge_magnet);
        expect(restored.fridge_magnets).toEqual(overrides.fridge_magnets);
        expect(restored.base_spacer_thick).toBe(baseSpacerThick);
        expect(restored.spacer_thick).toBe(expectedSpacerThick);
        expect(restored.structure_mode).toBe(expectedStructureMode);
        expect(recipe.device.enable_wipe_tower_auto_placement).toBe(
          overrides.enable_wipe_tower_auto_placement,
        );
        expect(restored.backing_infill_density_percent).toBe(
          restored.enable_relief
            ? 100
            : overrides.backing_infill_density_percent,
        );
      }),
      { numRuns: 50 },
    );
  });

  it("free_color_set survives Set→Array→Set round-trip", () => {
    fc.assert(
      fc.property(fc.uniqueArray(arbHexColor, { minLength: 0, maxLength: 8 }), (hexes) => {
        const state = {
          ...DEFAULT_STATE,
          free_color_set: new Set(hexes),
        } as ConverterState;

        const recipe = exportConverterRecipe(state, DEFAULT_SETTINGS, "fp");
        // Exported as array with '#' prefix
        expect(recipe.color_ops.free_color_set).toHaveLength(hexes.length);

        // Build full recipe wrapper to test import
        const fullRecipe = {
          format: "lumina-recipe" as const,
          schema_version: 1,
          app_version: "0.0.0",
          created_at: new Date().toISOString(),
          source: "converter" as const,
          cover: { width: 1, height: 1, mime_type: "image/png" as const },
          asset: {
            primary: {
              filename: "t.png",
              mime_type: "image/png",
              byte_size: 4,
              encoding: "base64" as const,
              payload_b64: "dGVzdA==",
            },
          },
          recipe: { converter: recipe },
          compat: { min_schema_version: 1 },
          warnings: [] as string[],
        };

        const { state: restored } = restoreConverterRecipe(fullRecipe, []);
        // Restored Set should match original (both without '#')
        expect(restored.free_color_set).toEqual(new Set(hexes));
      }),
      { numRuns: 30 },
    );
  });

  it("valid bead workshop sources preserve pressure, pitch, support, and orientation", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 100 }),
        fc.constantFrom(0.5, 1.3, 2.6, 5, 10),
        fc.constantFrom(0, 90, 180, 270),
        fc.boolean(),
        (compression, beadPitchMm, rotation, flipVertical) => {
          const source = createBeadRecipeSourceFixture();
          const calibration = source.payload.calibration as {
            inputMode: string;
            orientation: {
              rotation: number;
              flipHorizontal: boolean;
              flipVertical: boolean;
            };
          };
          source.payload = {
            ...source.payload,
            compression,
            beadPitchMm,
            calibration: {
              ...calibration,
              orientation: {
                ...calibration.orientation,
                rotation,
                flipVertical,
              },
            },
          };
          const converter = exportConverterRecipe(
            { ...DEFAULT_STATE, lut_name: "LUT-A" } as ConverterState,
            DEFAULT_SETTINGS,
            "/a",
          );
          const fullRecipe = {
            format: "lumina-recipe" as const,
            schema_version: 3,
            app_version: "0.0.0",
            created_at: "2026-07-30T00:00:00.000Z",
            source: "converter" as const,
            cover: {
              width: 1,
              height: 1,
              mime_type: "image/png" as const,
            },
            asset: {
              primary: {
                filename: "bead.png",
                mime_type: "image/png",
                byte_size: 4,
                encoding: "base64" as const,
                payload_b64: "dGVzdA==",
              },
            },
            recipe: { converter, workshop: source },
            compat: { min_schema_version: 1 },
            warnings: [] as string[],
          };

          const { state: restored, warnings } = restoreConverterRecipe(
            fullRecipe,
            [
              {
                name: "LUT-A",
                color_mode: ColorMode.FOUR_COLOR_RYBW,
                path: "/a",
              },
            ],
          );
          expect(restored.workshopSource).toEqual(source);
          expect(restored.workshopSource?.payload.cellsRle).toContainEqual([
            -2,
            1,
          ]);
          expect(restored.workshopSource?.payload.compression).toBe(
            compression,
          );
          expect(restored.workshopSource?.payload.beadPitchMm).toBe(
            beadPitchMm,
          );
          expect(warnings).toEqual([]);
        },
      ),
      { numRuns: 40 },
    );
  });
});
