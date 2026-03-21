import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { computeAutoHeightMap, hexToLuminance } from '../colorUtils';
import type { PaletteEntry } from '../../api/types';

/**
 * Property 4: 自动高度映射单调性
 * **Validates: Requirements 6.2, 6.3**
 *
 * For any palette with at least two distinct colors,
 * computeAutoHeightMap(palette, mode, maxHeight, minHeight) must satisfy:
 *   (a) all heights in [minHeight, maxHeight]
 *   (b) darker-higher: lower luminance → height >= higher luminance height
 *   (c) lighter-higher: higher luminance → height >= lower luminance height
 */

/** Arbitrary: 6-digit lowercase hex color string */
const arbHexColor = fc
  .tuple(
    fc.integer({ min: 0, max: 255 }),
    fc.integer({ min: 0, max: 255 }),
    fc.integer({ min: 0, max: 255 }),
  )
  .map(
    ([r, g, b]) =>
      r.toString(16).padStart(2, '0') +
      g.toString(16).padStart(2, '0') +
      b.toString(16).padStart(2, '0'),
  );

/** Arbitrary: PaletteEntry with random hex colors */
const arbPaletteEntry: fc.Arbitrary<PaletteEntry> = arbHexColor.chain(
  (hex) =>
    arbHexColor.map((matchedHex) => ({
      quantized_hex: hex,
      matched_hex: matchedHex,
      pixel_count: 1,
      percentage: 1,
    })),
);

/** Arbitrary: palette with 2-10 entries, each with unique matched_hex */
const arbPalette: fc.Arbitrary<PaletteEntry[]> = fc
  .array(arbPaletteEntry, { minLength: 2, maxLength: 10 })
  .filter((entries) => {
    const uniqueMatched = new Set(entries.map((e) => e.matched_hex));
    return uniqueMatched.size >= 2;
  });

/** Arbitrary: minHeight and maxHeight where minHeight < maxHeight, both positive */
const arbHeightRange = fc
  .tuple(
    fc.double({ min: 0.01, max: 5.0, noNaN: true }),
    fc.double({ min: 0.01, max: 10.0, noNaN: true }),
  )
  .filter(([a, b]) => a < b)
  .map(([minH, maxH]) => ({ minHeight: minH, maxHeight: maxH }));

describe('Property 4: 自动高度映射单调性', () => {
  it('darker-higher: all heights bounded in [minHeight, maxHeight]', () => {
    fc.assert(
      fc.property(arbPalette, arbHeightRange, (palette, { minHeight, maxHeight }) => {
        const heightMap = computeAutoHeightMap(palette, 'darker-higher', maxHeight, minHeight);

        for (const entry of palette) {
          const h = heightMap[entry.matched_hex];
          expect(h).toBeGreaterThanOrEqual(minHeight - 1e-9);
          expect(h).toBeLessThanOrEqual(maxHeight + 1e-9);
        }
      }),
      { numRuns: 200 },
    );
  });

  it('lighter-higher: all heights bounded in [minHeight, maxHeight]', () => {
    fc.assert(
      fc.property(arbPalette, arbHeightRange, (palette, { minHeight, maxHeight }) => {
        const heightMap = computeAutoHeightMap(palette, 'lighter-higher', maxHeight, minHeight);

        for (const entry of palette) {
          const h = heightMap[entry.matched_hex];
          expect(h).toBeGreaterThanOrEqual(minHeight - 1e-9);
          expect(h).toBeLessThanOrEqual(maxHeight + 1e-9);
        }
      }),
      { numRuns: 200 },
    );
  });

  it('darker-higher: lower luminance colors get height >= higher luminance colors', () => {
    fc.assert(
      fc.property(arbPalette, arbHeightRange, (palette, { minHeight, maxHeight }) => {
        const heightMap = computeAutoHeightMap(palette, 'darker-higher', maxHeight, minHeight);

        // Deduplicate by matched_hex, then sort by luminance ascending
        const uniqueEntries = [
          ...new Map(palette.map((e) => [e.matched_hex, e])).values(),
        ];
        const sorted = uniqueEntries.sort(
          (a, b) => hexToLuminance(a.matched_hex) - hexToLuminance(b.matched_hex),
        );

        // Lower luminance (darker) should have >= height than higher luminance (brighter)
        for (let i = 0; i < sorted.length - 1; i++) {
          const darkerH = heightMap[sorted[i].matched_hex];
          const brighterH = heightMap[sorted[i + 1].matched_hex];
          expect(darkerH).toBeGreaterThanOrEqual(brighterH - 1e-9);
        }
      }),
      { numRuns: 200 },
    );
  });

  it('lighter-higher: higher luminance colors get height >= lower luminance colors', () => {
    fc.assert(
      fc.property(arbPalette, arbHeightRange, (palette, { minHeight, maxHeight }) => {
        const heightMap = computeAutoHeightMap(palette, 'lighter-higher', maxHeight, minHeight);

        // Deduplicate by matched_hex, then sort by luminance ascending
        const uniqueEntries = [
          ...new Map(palette.map((e) => [e.matched_hex, e])).values(),
        ];
        const sorted = uniqueEntries.sort(
          (a, b) => hexToLuminance(a.matched_hex) - hexToLuminance(b.matched_hex),
        );

        // Higher luminance (brighter) should have >= height than lower luminance (darker)
        for (let i = 0; i < sorted.length - 1; i++) {
          const darkerH = heightMap[sorted[i].matched_hex];
          const brighterH = heightMap[sorted[i + 1].matched_hex];
          expect(brighterH).toBeGreaterThanOrEqual(darkerH - 1e-9);
        }
      }),
      { numRuns: 200 },
    );
  });
});

import { colorRemapToReplacementRegions } from '../colorUtils';

/**
 * Property 7: colorRemapMap 到 replacement_regions 转换正确性
 * **Validates: Requirements 10.1**
 *
 * For any non-empty colorRemapMap and corresponding palette,
 * colorRemapToReplacementRegions(remapMap, palette) must satisfy:
 *   (a) output length equals remapMap entry count
 *   (b) each output item's quantized_hex and matched_hex come from the palette
 *   (c) each output item's replacement_hex equals the remapMap target color
 */

/** Arbitrary: palette with unique matched_hex values (1-10 entries) */
const arbUniquePalette: fc.Arbitrary<PaletteEntry[]> = fc
  .uniqueArray(arbHexColor, { minLength: 1, maxLength: 10, comparator: (a, b) => a === b })
  .chain((matchedHexes) =>
    fc.tuple(...matchedHexes.map((mh) => arbHexColor.map((qh) => ({ mh, qh })))).map(
      (pairs) =>
        pairs.map(({ mh, qh }) => ({
          quantized_hex: qh,
          matched_hex: mh,
          pixel_count: 1,
          percentage: 1,
        })),
    ),
  );

/** Arbitrary: remapMap built from a subset of palette matched_hex keys → random target hex */
const arbRemapFromPalette: fc.Arbitrary<{
  palette: PaletteEntry[];
  remapMap: Record<string, string>;
}> = arbUniquePalette.chain((palette) => {
  // Pick a non-empty subset of matched_hex values as remap keys
  const matchedHexes = palette.map((e) => e.matched_hex);
  return fc
    .subarray(matchedHexes, { minLength: 1 })
    .chain((keys) =>
      fc.tuple(...keys.map(() => arbHexColor)).map((targets) => {
        const remapMap: Record<string, string> = {};
        keys.forEach((k, i) => {
          remapMap[k] = targets[i];
        });
        return { palette, remapMap };
      }),
    );
});

describe('Property 7: colorRemapMap 到 replacement_regions 转换正确性', () => {
  it('output length equals remapMap entry count', () => {
    fc.assert(
      fc.property(arbRemapFromPalette, ({ palette, remapMap }) => {
        const result = colorRemapToReplacementRegions(remapMap, palette);
        expect(result).toHaveLength(Object.keys(remapMap).length);
      }),
      { numRuns: 200 },
    );
  });

  it('each output item quantized_hex and matched_hex come from palette', () => {
    fc.assert(
      fc.property(arbRemapFromPalette, ({ palette, remapMap }) => {
        const result = colorRemapToReplacementRegions(remapMap, palette);

        for (const item of result) {
          // Output hex values have # prefix; palette values do not
          const matchedNoHash = item.matched_hex.replace(/^#/, '');
          const paletteEntry = palette.find((p) => p.matched_hex === matchedNoHash);
          expect(paletteEntry).toBeDefined();
          const quantizedNoHash = item.quantized_hex.replace(/^#/, '');
          expect(quantizedNoHash).toBe(paletteEntry!.quantized_hex);
        }
      }),
      { numRuns: 200 },
    );
  });

  it('each output item replacement_hex equals remapMap target color (with # prefix)', () => {
    fc.assert(
      fc.property(arbRemapFromPalette, ({ palette, remapMap }) => {
        const result = colorRemapToReplacementRegions(remapMap, palette);

        for (const item of result) {
          const matchedNoHash = item.matched_hex.replace(/^#/, '');
          const replacementNoHash = item.replacement_hex.replace(/^#/, '');
          expect(replacementNoHash).toBe(remapMap[matchedNoHash]);
        }
      }),
      { numRuns: 200 },
    );
  });
});
