import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { useConverterStore } from '../../stores/converterStore';

/**
 * Property 3: 颜色替换与撤销状态一致性
 * **Validates: Requirements 3.3, 4.1, 4.4**
 *
 * For any initial empty colorRemapMap and any sequence of operations
 * (mix of applyColorRemap and undoColorRemap), the final colorRemapMap
 * state should be equivalent to replaying all non-undone applyColorRemap
 * operations in order. clearAllRemaps should leave both colorRemapMap
 * and remapHistory empty.
 */

// ========== Arbitraries ==========

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

/** Operation type: either apply a color remap or undo */
type ApplyOp = { type: 'apply'; origHex: string; newHex: string };
type UndoOp = { type: 'undo' };
type Op = ApplyOp | UndoOp;

/** Arbitrary: a single operation (apply or undo) */
const arbOp: fc.Arbitrary<Op> = fc.oneof(
  fc.tuple(arbHexColor, arbHexColor).map(([origHex, newHex]) => ({
    type: 'apply' as const,
    origHex,
    newHex,
  })),
  fc.constant({ type: 'undo' as const }),
);

/** Arbitrary: a sequence of 0-30 operations */
const arbOpSequence: fc.Arbitrary<Op[]> = fc.array(arbOp, {
  minLength: 0,
  maxLength: 30,
});

// ========== Helpers ==========

/** Reset the store to default state before each property iteration */
function resetStore(): void {
  useConverterStore.setState({
    colorRemapMap: {},
    remapHistory: [],
    selectedColor: null,
  });
}

/**
 * Simulate the operation sequence to compute the expected colorRemapMap.
 *
 * The store uses a snapshot-based undo: each applyColorRemap pushes the
 * current map as a snapshot, then applies the change. undoColorRemap pops
 * the last snapshot and restores it. So we simulate this exact logic to
 * derive the expected final state.
 */
function simulateOps(ops: Op[]): Record<string, string> {
  let currentMap: Record<string, string> = {};
  const history: Record<string, string>[] = [];

  for (const op of ops) {
    if (op.type === 'apply') {
      // Push snapshot of current map
      history.push({ ...currentMap });
      // Apply the remap
      currentMap = { ...currentMap, [op.origHex]: op.newHex };
    } else {
      // Undo: pop last snapshot if available
      if (history.length > 0) {
        currentMap = history.pop()!;
      }
    }
  }

  return currentMap;
}

// ========== Tests ==========

describe('Property 3: 颜色替换与撤销状态一致性', () => {
  beforeEach(() => {
    resetStore();
  });

  it('final colorRemapMap matches simulated replay of operations', () => {
    fc.assert(
      fc.property(arbOpSequence, (ops) => {
        resetStore();

        const store = useConverterStore.getState;

        // Execute all operations on the real store
        for (const op of ops) {
          if (op.type === 'apply') {
            useConverterStore.getState().applyColorRemap(op.origHex, op.newHex);
          } else {
            useConverterStore.getState().undoColorRemap();
          }
        }

        const actualMap = store().colorRemapMap;
        const expectedMap = simulateOps(ops);

        expect(actualMap).toEqual(expectedMap);
      }),
      { numRuns: 200 },
    );
  });

  it('remapHistory length equals number of undoable operations remaining', () => {
    fc.assert(
      fc.property(arbOpSequence, (ops) => {
        resetStore();

        // Track expected history length
        let historyLen = 0;
        for (const op of ops) {
          if (op.type === 'apply') {
            useConverterStore.getState().applyColorRemap(op.origHex, op.newHex);
            historyLen++;
          } else {
            useConverterStore.getState().undoColorRemap();
            if (historyLen > 0) historyLen--;
          }
        }

        expect(useConverterStore.getState().remapHistory).toHaveLength(historyLen);
      }),
      { numRuns: 200 },
    );
  });

  it('clearAllRemaps leaves colorRemapMap and remapHistory empty', () => {
    fc.assert(
      fc.property(arbOpSequence, (ops) => {
        resetStore();

        // Execute random operations first
        for (const op of ops) {
          if (op.type === 'apply') {
            useConverterStore.getState().applyColorRemap(op.origHex, op.newHex);
          } else {
            useConverterStore.getState().undoColorRemap();
          }
        }

        // Clear all
        useConverterStore.getState().clearAllRemaps();

        const state = useConverterStore.getState();
        expect(state.colorRemapMap).toEqual({});
        expect(state.remapHistory).toEqual([]);
      }),
      { numRuns: 200 },
    );
  });

  it('undo on empty history is a no-op', () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 10 }), (undoCount) => {
        resetStore();

        // Undo multiple times on empty store
        for (let i = 0; i < undoCount; i++) {
          useConverterStore.getState().undoColorRemap();
        }

        const state = useConverterStore.getState();
        expect(state.colorRemapMap).toEqual({});
        expect(state.remapHistory).toEqual([]);
      }),
      { numRuns: 100 },
    );
  });
});


/**
 * Property 5: 浮雕启用时高度初始化完整性
 * **Validates: Requirements 5.5**
 *
 * For any non-empty palette, when enable_relief switches from false to true,
 * color_height_map should contain an entry for every color in the palette,
 * all initial height values should be equal, and within the valid range
 * [0.08, heightmap_max_height].
 */

// ========== Arbitraries for Property 5 ==========

/** Arbitrary: a PaletteEntry with random hex colors and pixel stats */
const arbPaletteEntry = fc
  .tuple(
    arbHexColor,
    arbHexColor,
    fc.integer({ min: 1, max: 100000 }),
  )
  .map(([quantized_hex, matched_hex, pixel_count]) => ({
    quantized_hex,
    matched_hex,
    pixel_count,
    percentage: 0, // not relevant for this property
  }));

/** Arbitrary: a non-empty palette with 1-10 entries and unique matched_hex */
const arbUniquePalette = fc
  .array(arbPaletteEntry, { minLength: 1, maxLength: 10 })
  .map((entries) => {
    // Deduplicate by matched_hex to avoid ambiguity
    const seen = new Set<string>();
    return entries.filter((e) => {
      if (seen.has(e.matched_hex)) return false;
      seen.add(e.matched_hex);
      return true;
    });
  })
  .filter((entries) => entries.length > 0);

/** Arbitrary: heightmap_max_height in valid range (must be > 0.08 so 50% can be >= 0.08 when max >= 0.16) */
const arbMaxHeight = fc.double({ min: 0.16, max: 15.0, noNaN: true });

// ========== Tests for Property 5 ==========

describe('Property 5: 浮雕启用时高度初始化完整性', () => {
  beforeEach(() => {
    useConverterStore.setState({
      enable_relief: false,
      color_height_map: {},
      palette: [],
      heightmap_max_height: 5.0,
    });
  });

  it('color_height_map contains all palette colors after enabling relief', () => {
    fc.assert(
      fc.property(arbUniquePalette, arbMaxHeight, (palette, maxHeight) => {
        // Reset state
        useConverterStore.setState({
          enable_relief: false,
          color_height_map: {},
          palette,
          heightmap_max_height: maxHeight,
        });

        // Enable relief
        useConverterStore.getState().setEnableRelief(true);

        const state = useConverterStore.getState();
        const map = state.color_height_map;

        // (a) color_height_map has entries for all palette colors
        for (const entry of palette) {
          expect(map).toHaveProperty(entry.matched_hex);
        }
      }),
      { numRuns: 200 },
    );
  });

  it('all initial height values are equal', () => {
    fc.assert(
      fc.property(arbUniquePalette, arbMaxHeight, (palette, maxHeight) => {
        useConverterStore.setState({
          enable_relief: false,
          color_height_map: {},
          palette,
          heightmap_max_height: maxHeight,
        });

        useConverterStore.getState().setEnableRelief(true);

        const map = useConverterStore.getState().color_height_map;
        const heights = Object.values(map);

        // All heights should be equal
        if (heights.length > 1) {
          const first = heights[0];
          for (const h of heights) {
            expect(h).toBeCloseTo(first, 10);
          }
        }
      }),
      { numRuns: 200 },
    );
  });

  it('all initial heights are within [0.08, heightmap_max_height]', () => {
    fc.assert(
      fc.property(arbUniquePalette, arbMaxHeight, (palette, maxHeight) => {
        useConverterStore.setState({
          enable_relief: false,
          color_height_map: {},
          palette,
          heightmap_max_height: maxHeight,
        });

        useConverterStore.getState().setEnableRelief(true);

        const map = useConverterStore.getState().color_height_map;

        for (const height of Object.values(map)) {
          expect(height).toBeGreaterThanOrEqual(0.08);
          expect(height).toBeLessThanOrEqual(maxHeight);
        }
      }),
      { numRuns: 200 },
    );
  });

  it('enabling relief when already enabled does not re-initialize heights', () => {
    fc.assert(
      fc.property(arbUniquePalette, arbMaxHeight, (palette, maxHeight) => {
        useConverterStore.setState({
          enable_relief: false,
          color_height_map: {},
          palette,
          heightmap_max_height: maxHeight,
        });

        // Enable relief first time
        useConverterStore.getState().setEnableRelief(true);

        // Modify one height
        const firstHex = palette[0].matched_hex;
        useConverterStore.getState().updateColorHeight(firstHex, 0.1);

        // Enable relief again (already true → true)
        useConverterStore.getState().setEnableRelief(true);

        // The modified height should be preserved (not re-initialized)
        const map = useConverterStore.getState().color_height_map;
        expect(map[firstHex]).toBeCloseTo(0.1, 10);
      }),
      { numRuns: 100 },
    );
  });
});
