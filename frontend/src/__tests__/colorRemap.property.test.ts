import { describe, it, expect, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useConverterStore } from "../stores/converterStore";

// ========== Generators ==========

/** Generate a valid 6-character hex string (lowercase) */
const hexColor = fc.stringMatching(/^[0-9a-f]{6}$/).filter((s) => s.length === 6);

/** Generate a remap operation {origHex, newHex} */
const remapOp = fc.record({ origHex: hexColor, newHex: hexColor });

// ========== Helpers ==========

/** Reset store color remap state before each test */
function resetRemapState(): void {
  useConverterStore.setState({
    colorRemapMap: {},
    remapHistory: [],
  });
}

// ========== Tests ==========

describe("Color Remap Core Logic — Property-Based Tests", () => {
  beforeEach(() => {
    resetRemapState();
  });

  // Validates: Requirements 3.1, 3.5
  describe("P3: N applyColorRemap ops produce remapHistory.length === N with latest mapping", () => {
    it("remapHistory length equals number of apply operations", () => {
      fc.assert(
        fc.property(
          fc.array(remapOp, { minLength: 0, maxLength: 30 }),
          (ops) => {
            resetRemapState();
            const store = useConverterStore.getState();

            for (const op of ops) {
              store.applyColorRemap(op.origHex, op.newHex);
            }

            const state = useConverterStore.getState();
            return state.remapHistory.length === ops.length;
          }
        ),
        { numRuns: 100 }
      );
    });

    it("colorRemapMap contains the latest mapping for each unique origHex", () => {
      fc.assert(
        fc.property(
          fc.array(remapOp, { minLength: 1, maxLength: 30 }),
          (ops) => {
            resetRemapState();
            const store = useConverterStore.getState();

            for (const op of ops) {
              store.applyColorRemap(op.origHex, op.newHex);
            }

            const state = useConverterStore.getState();

            // Build expected map: last write wins for each origHex
            const expected: Record<string, string> = {};
            for (const op of ops) {
              expected[op.origHex] = op.newHex;
            }

            // Verify each unique origHex maps to its last newHex
            for (const [orig, newH] of Object.entries(expected)) {
              if (state.colorRemapMap[orig] !== newH) return false;
            }
            return true;
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // Validates: Requirements 3.3, 10.1
  describe("P4: N apply then K undo produces colorRemapMap equal to snapshot at (N-K)", () => {
    it("undoing K times after N applies restores the snapshot at position N-K", () => {
      fc.assert(
        fc.property(
          fc.array(remapOp, { minLength: 1, maxLength: 20 }),
          (ops) => {
            resetRemapState();
            const store = useConverterStore.getState();

            // Take snapshots at each step (before each apply, snapshot[0] = initial empty)
            const snapshots: Record<string, string>[] = [];
            snapshots.push({ ...useConverterStore.getState().colorRemapMap });

            for (const op of ops) {
              store.applyColorRemap(op.origHex, op.newHex);
              snapshots.push({ ...useConverterStore.getState().colorRemapMap });
            }

            // Pick a random K from [0, ops.length] using the ops length
            // We test all possible K values for thoroughness
            const N = ops.length;
            for (let K = 0; K <= N; K++) {
              // Reset and replay to get back to N applies
              resetRemapState();
              for (const op of ops) {
                useConverterStore.getState().applyColorRemap(op.origHex, op.newHex);
              }

              // Undo K times
              for (let u = 0; u < K; u++) {
                useConverterStore.getState().undoColorRemap();
              }

              const currentMap = useConverterStore.getState().colorRemapMap;
              const expectedMap = snapshots[N - K];

              // Compare maps
              const currentKeys = Object.keys(currentMap).sort();
              const expectedKeys = Object.keys(expectedMap).sort();
              if (currentKeys.length !== expectedKeys.length) return false;
              for (let i = 0; i < currentKeys.length; i++) {
                if (currentKeys[i] !== expectedKeys[i]) return false;
                if (currentMap[currentKeys[i]] !== expectedMap[expectedKeys[i]]) return false;
              }
            }
            return true;
          }
        ),
        { numRuns: 50 }
      );
    });

    it("undo on empty history is a no-op", () => {
      fc.assert(
        fc.property(fc.constant(null), () => {
          resetRemapState();
          const before = { ...useConverterStore.getState().colorRemapMap };
          useConverterStore.getState().undoColorRemap();
          const after = useConverterStore.getState().colorRemapMap;

          return (
            Object.keys(before).length === Object.keys(after).length &&
            useConverterStore.getState().remapHistory.length === 0
          );
        }),
        { numRuns: 5 }
      );
    });
  });

  // Validates: Requirements 3.4, 10.4
  describe("P5: clearAllRemaps resets colorRemapMap and remapHistory to empty", () => {
    it("after arbitrary remap ops, clearAllRemaps empties both colorRemapMap and remapHistory", () => {
      fc.assert(
        fc.property(
          fc.array(remapOp, { minLength: 1, maxLength: 30 }),
          (ops) => {
            resetRemapState();
            const store = useConverterStore.getState();

            // Apply some operations to build up state
            for (const op of ops) {
              store.applyColorRemap(op.origHex, op.newHex);
            }

            // Verify state is non-empty before clear
            const preState = useConverterStore.getState();
            expect(preState.remapHistory.length).toBe(ops.length);

            // Clear all
            useConverterStore.getState().clearAllRemaps();

            const postState = useConverterStore.getState();
            return (
              Object.keys(postState.colorRemapMap).length === 0 &&
              postState.remapHistory.length === 0
            );
          }
        ),
        { numRuns: 100 }
      );
    });

    it("clearAllRemaps on already empty state is idempotent", () => {
      fc.assert(
        fc.property(fc.constant(null), () => {
          resetRemapState();
          useConverterStore.getState().clearAllRemaps();

          const state = useConverterStore.getState();
          return (
            Object.keys(state.colorRemapMap).length === 0 &&
            state.remapHistory.length === 0
          );
        }),
        { numRuns: 5 }
      );
    });
  });
});
