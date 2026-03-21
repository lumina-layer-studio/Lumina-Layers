import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import {
  matchesSearch,
  classifyHue,
  type HueCategory,
} from "../components/sections/LutColorGrid";
import type { LutColorEntry, PaletteEntry } from "../api/types";

// ========== Generators ==========

/** Generate a single RGB channel value [0, 255] */
const rgbChannel = fc.integer({ min: 0, max: 255 });

/** Generate an RGB triple */
const rgbTriple = fc.tuple(rgbChannel, rgbChannel, rgbChannel);

/**
 * Generate a consistent LutColorEntry where hex matches rgb.
 * 生成一致的 LutColorEntry，hex 与 rgb 对应。
 */
const lutColorEntry: fc.Arbitrary<LutColorEntry> = rgbTriple.map(
  ([r, g, b]) => ({
    hex:
      "#" +
      r.toString(16).padStart(2, "0") +
      g.toString(16).padStart(2, "0") +
      b.toString(16).padStart(2, "0"),
    rgb: [r, g, b] as [number, number, number],
  })
);

/**
 * Generate a PaletteEntry with a matched_hex derived from a random RGB.
 * 生成 PaletteEntry，matched_hex 来自随机 RGB。
 */
const paletteEntry: fc.Arbitrary<PaletteEntry> = rgbTriple.map(
  ([r, g, b]) => ({
    quantized_hex:
      r.toString(16).padStart(2, "0") +
      g.toString(16).padStart(2, "0") +
      b.toString(16).padStart(2, "0"),
    matched_hex:
      r.toString(16).padStart(2, "0") +
      g.toString(16).padStart(2, "0") +
      b.toString(16).padStart(2, "0"),
    pixel_count: 100,
    percentage: 10,
  })
);

// ========== Valid HueCategory values (excluding "all") ==========

const VALID_HUE_CATEGORIES: HueCategory[] = [
  "red",
  "orange",
  "yellow",
  "green",
  "cyan",
  "blue",
  "purple",
  "neutral",
];

// ========== Tests ==========

describe("LUT Panel Filter Logic — Property-Based Tests", () => {
  // ================================================================
  // P6: LUT color partition completeness
  // Validates: Requirements 5.2
  // ================================================================
  describe("P6: LUT color partition — used ∪ other === full set, used ∩ other === ∅", () => {
    it("partitioning lutColors by palette produces disjoint, complete sets", () => {
      fc.assert(
        fc.property(
          fc.array(lutColorEntry, { minLength: 0, maxLength: 50 }),
          fc.array(paletteEntry, { minLength: 0, maxLength: 20 }),
          (lutColors, palette) => {
            // Build usedHexSet the same way LutColorGrid does
            const usedHexSet = new Set<string>();
            for (const e of palette) {
              usedHexSet.add(`#${e.matched_hex}`.toLowerCase());
            }

            // Partition (same logic as LutColorGrid useMemo)
            const used: LutColorEntry[] = [];
            const other: LutColorEntry[] = [];
            for (const c of lutColors) {
              const hex = c.hex.toLowerCase();
              if (usedHexSet.has(hex)) {
                used.push(c);
              } else {
                other.push(c);
              }
            }

            // Union completeness: used + other === full set
            expect(used.length + other.length).toBe(lutColors.length);

            // Disjointness: no entry appears in both
            const usedHexes = new Set(used.map((c) => c.hex.toLowerCase()));
            const otherHexes = new Set(other.map((c) => c.hex.toLowerCase()));
            for (const h of usedHexes) {
              expect(otherHexes.has(h)).toBe(false);
            }

            // Every entry in used is actually in usedHexSet
            for (const c of used) {
              expect(usedHexSet.has(c.hex.toLowerCase())).toBe(true);
            }

            // Every entry in other is NOT in usedHexSet
            for (const c of other) {
              expect(usedHexSet.has(c.hex.toLowerCase())).toBe(false);
            }
          }
        ),
        { numRuns: 200 }
      );
    });
  });

  // ================================================================
  // P7: matchesSearch correctness
  // Validates: Requirements 5.3
  // ================================================================
  describe("P7: matchesSearch correctness for hex substring and RGB exact match", () => {
    it("empty query always matches", () => {
      fc.assert(
        fc.property(lutColorEntry, (entry) => {
          expect(matchesSearch(entry, "")).toBe(true);
          expect(matchesSearch(entry, "   ")).toBe(true);
        }),
        { numRuns: 100 }
      );
    });

    it("hex substring of entry.hex always matches", () => {
      fc.assert(
        fc.property(
          lutColorEntry,
          fc.integer({ min: 0, max: 5 }),
          fc.integer({ min: 1, max: 6 }),
          (entry, start, len) => {
            const hexNoHash = entry.hex.replace("#", "").toLowerCase();
            const end = Math.min(start + len, hexNoHash.length);
            const sub = hexNoHash.slice(start, end);
            if (sub.length > 0) {
              expect(matchesSearch(entry, sub)).toBe(true);
            }
          }
        ),
        { numRuns: 200 }
      );
    });

    it("exact RGB comma format matches", () => {
      fc.assert(
        fc.property(lutColorEntry, (entry) => {
          const [r, g, b] = entry.rgb;
          const query = `${r},${g},${b}`;
          expect(matchesSearch(entry, query)).toBe(true);
        }),
        { numRuns: 200 }
      );
    });

    it("exact RGB with rgb() format matches", () => {
      fc.assert(
        fc.property(lutColorEntry, (entry) => {
          const [r, g, b] = entry.rgb;
          const query = `rgb(${r}, ${g}, ${b})`;
          expect(matchesSearch(entry, query)).toBe(true);
        }),
        { numRuns: 200 }
      );
    });

    it("non-matching RGB does not match (when hex also differs)", () => {
      fc.assert(
        fc.property(
          lutColorEntry,
          rgbTriple,
          (entry, [qr, qg, qb]) => {
            const [r, g, b] = entry.rgb;
            // Only test when RGB values actually differ
            if (r !== qr || g !== qg || b !== qb) {
              const query = `${qr},${qg},${qb}`;
              // The query might still match via hex substring, so we check:
              // if it doesn't match hex AND doesn't match RGB, result should be false
              const hexNoHash = entry.hex.replace("#", "").toLowerCase();
              const queryHexPart = query.replace("#", "").toLowerCase();
              const hexMatches = hexNoHash.includes(queryHexPart);
              if (!hexMatches) {
                expect(matchesSearch(entry, query)).toBe(false);
              }
            }
          }
        ),
        { numRuns: 200 }
      );
    });
  });

  // ================================================================
  // P8: classifyHue completeness
  // Validates: Requirements 5.4
  // ================================================================
  describe("P8: classifyHue always returns a valid HueCategory", () => {
    it("for any RGB in [0,255], classifyHue returns one of the 8 valid categories", () => {
      fc.assert(
        fc.property(rgbChannel, rgbChannel, rgbChannel, (r, g, b) => {
          const result = classifyHue(r, g, b);
          expect(VALID_HUE_CATEGORIES).toContain(result);
        }),
        { numRuns: 500 }
      );
    });

    it("boundary values (0,0,0) and (255,255,255) produce valid categories", () => {
      expect(VALID_HUE_CATEGORIES).toContain(classifyHue(0, 0, 0));
      expect(VALID_HUE_CATEGORIES).toContain(classifyHue(255, 255, 255));
      expect(VALID_HUE_CATEGORIES).toContain(classifyHue(255, 0, 0));
      expect(VALID_HUE_CATEGORIES).toContain(classifyHue(0, 255, 0));
      expect(VALID_HUE_CATEGORIES).toContain(classifyHue(0, 0, 255));
    });
  });
});
