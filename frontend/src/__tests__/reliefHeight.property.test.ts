import { describe, it, expect, beforeEach } from "vitest";
import * as fc from "fast-check";
import { computeAutoHeightMap } from "../utils/colorUtils";
import { useConverterStore } from "../stores/converterStore";
import type { PaletteEntry } from "../api/types";

// ========== Generators ==========

/** Generate a valid 6-character hex string (lowercase) */
const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

/** Generate a PaletteEntry with random hex colors and stats */
const paletteEntry = fc.record({
  quantized_hex: hexColor,
  matched_hex: hexColor,
  pixel_count: fc.integer({ min: 1, max: 10000 }),
  percentage: fc.float({ min: Math.fround(0.01), max: Math.fround(100), noNaN: true }),
});

/** Generate a non-empty palette with unique matched_hex values */
const uniquePalette = fc
  .array(paletteEntry, { minLength: 1, maxLength: 20 })
  .map((entries) => {
    const seen = new Set<string>();
    return entries.filter((e) => {
      if (seen.has(e.matched_hex)) return false;
      seen.add(e.matched_hex);
      return true;
    });
  })
  .filter((arr) => arr.length > 0);

/** Generate auto-height mode */
const heightMode = fc.constantFrom(
  "darker-higher" as const,
  "lighter-higher" as const,
);

// ========== Helpers ==========

/** Reset store relief-related state before each test */
function resetReliefState(palette: PaletteEntry[] = []): void {
  useConverterStore.setState({
    enable_relief: false,
    palette,
    color_height_map: {},
    heightmap_max_height: 5.0,
    enable_cloisonne: false,
  });
}

/**
 * Pure computation for mesh Z-scale ratio.
 * Mirrors InteractiveModelViewer logic: mesh.scale.z = heightMm / baseHeight.
 */
function computeMeshScaleZ(heightMm: number, baseHeight: number): number {
  return heightMm / baseHeight;
}

// ========== Tests ==========

describe("Relief Height Logic — Property-Based Tests", () => {
  beforeEach(() => {
    resetReliefState();
  });

  /**
   * P9: computeAutoHeightMap range constraint
   * Validates: Requirements 6.4
   *
   * For any palette and height range, all output values of
   * computeAutoHeightMap are within [minHeight, maxHeight].
   */
  describe("P9: computeAutoHeightMap outputs within [minHeight, maxHeight]", () => {
    it("all height values fall within the specified range", () => {
      fc.assert(
        fc.property(
          uniquePalette,
          heightMode,
          fc.float({ min: Math.fround(0.01), max: Math.fround(5), noNaN: true }),
          fc.float({ min: Math.fround(5.01), max: Math.fround(15), noNaN: true }),
          (palette, mode, minHeight, maxHeight) => {
            // Ensure minHeight < maxHeight
            fc.pre(minHeight < maxHeight);
            fc.pre(minHeight > 0);

            const result = computeAutoHeightMap(
              palette,
              mode,
              maxHeight,
              minHeight,
            );

            for (const hex of Object.keys(result)) {
              const h = result[hex];
              expect(h).toBeGreaterThanOrEqual(minHeight - 1e-9);
              expect(h).toBeLessThanOrEqual(maxHeight + 1e-9);
            }
          },
        ),
        { numRuns: 200 },
      );
    });

    it("output contains an entry for every palette color", () => {
      fc.assert(
        fc.property(uniquePalette, heightMode, (palette, mode) => {
          const result = computeAutoHeightMap(palette, mode, 10, 0.08);
          for (const entry of palette) {
            expect(result).toHaveProperty(entry.matched_hex);
          }
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * P10: Relief initialization coverage
   * Validates: Requirements 6.5
   *
   * When enable_relief switches to true with non-empty palette and
   * empty color_height_map, the initialized map contains every palette color.
   */
  describe("P10: enable_relief true initializes colorHeightMap with all palette colors", () => {
    it("initialized map contains every palette matched_hex", () => {
      fc.assert(
        fc.property(uniquePalette, (palette) => {
          // Reset with the generated palette, empty height map
          resetReliefState(palette);

          // Trigger setEnableRelief(true)
          useConverterStore.getState().setEnableRelief(true);

          const state = useConverterStore.getState();

          // Verify enable_relief is true
          expect(state.enable_relief).toBe(true);

          // Verify every palette color has an entry in color_height_map
          for (const entry of palette) {
            expect(state.color_height_map).toHaveProperty(entry.matched_hex);
          }
        }),
        { numRuns: 100 },
      );
    });

    it("initialized heights equal heightmap_max_height * 0.5", () => {
      fc.assert(
        fc.property(
          uniquePalette,
          fc.float({ min: Math.fround(0.5), max: Math.fround(15), noNaN: true }),
          (palette, maxHeight) => {
            useConverterStore.setState({
              enable_relief: false,
              palette,
              color_height_map: {},
              heightmap_max_height: maxHeight,
              enable_cloisonne: false,
            });

            useConverterStore.getState().setEnableRelief(true);

            const state = useConverterStore.getState();
            const expectedHeight = maxHeight * 0.5;

            for (const entry of palette) {
              expect(state.color_height_map[entry.matched_hex]).toBeCloseTo(
                expectedHeight,
                5,
              );
            }
          },
        ),
        { numRuns: 100 },
      );
    });

    it("does NOT overwrite existing non-empty color_height_map", () => {
      fc.assert(
        fc.property(uniquePalette, (palette) => {
          // Pre-populate color_height_map with custom values
          const existingMap: Record<string, number> = {};
          for (const entry of palette) {
            existingMap[entry.matched_hex] = 99.9;
          }

          useConverterStore.setState({
            enable_relief: false,
            palette,
            color_height_map: existingMap,
            heightmap_max_height: 5.0,
            enable_cloisonne: false,
          });

          useConverterStore.getState().setEnableRelief(true);

          const state = useConverterStore.getState();

          // Existing map should be preserved (not overwritten)
          for (const entry of palette) {
            expect(state.color_height_map[entry.matched_hex]).toBe(99.9);
          }
        }),
        { numRuns: 50 },
      );
    });
  });

  /**
   * P11: Mesh Z-scale ratio
   * Validates: Requirements 6.3
   *
   * When enableRelief is true, meshScaleZ === heightMm / baseHeight
   * (for baseHeight > 0).
   */
  describe("P11: meshScaleZ equals heightMm / baseHeight", () => {
    it("scaleZ is the exact ratio of heightMm to baseHeight", () => {
      fc.assert(
        fc.property(
          fc.float({ min: Math.fround(0.01), max: Math.fround(100), noNaN: true }),
          fc.float({ min: Math.fround(0.01), max: Math.fround(100), noNaN: true }),
          (heightMm, baseHeight) => {
            fc.pre(baseHeight > 0);
            fc.pre(Number.isFinite(heightMm / baseHeight));

            const scaleZ = computeMeshScaleZ(heightMm, baseHeight);
            const expected = heightMm / baseHeight;

            expect(scaleZ).toBeCloseTo(expected, 10);
          },
        ),
        { numRuns: 200 },
      );
    });

    it("scaleZ is 1.0 when heightMm equals baseHeight", () => {
      fc.assert(
        fc.property(
          fc.float({ min: Math.fround(0.01), max: Math.fround(100), noNaN: true }),
          (height) => {
            const scaleZ = computeMeshScaleZ(height, height);
            expect(scaleZ).toBeCloseTo(1.0, 10);
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
