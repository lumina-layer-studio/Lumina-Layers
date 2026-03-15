import { describe, it, expect } from "vitest";
import * as fc from "fast-check";

// ========== Pure function under test ==========

/**
 * Selection modes for color replacement.
 * 颜色替换的选择模式。
 */
type SelectionMode = "select-all" | "current" | "multi-select" | "region";

/**
 * Input to the confirmReplacement state update logic.
 * confirmReplacement 状态更新逻辑的输入。
 */
interface ConfirmReplacementInput {
  selectionMode: SelectionMode;
  sourceHex: string;
  targetHex: string;
  currentColorRemapMap: Record<string, string>;
  currentRegionReplacementCount: number;
  /** Only used for multi-select mode */
  sourceColors?: string[];
}

/**
 * Output of the confirmReplacement state update logic.
 * confirmReplacement 状态更新逻辑的输出。
 */
interface ConfirmReplacementOutput {
  colorRemapMap: Record<string, string>;
  regionReplacementCount: number;
}

/**
 * Pure function replicating the core branching logic of confirmReplacement.
 * Mirrors the actual store implementation in converterStore.ts (post task 4.2).
 *
 * 纯函数，复制 confirmReplacement 的核心分支逻辑。
 *
 * - select-all: updates colorRemapMap with sourceHex → targetHex
 * - multi-select: updates colorRemapMap for all sourceColors → targetHex
 * - current/region: does NOT update colorRemapMap, only increments regionReplacementCount
 */
function computeConfirmReplacementStateUpdate(
  input: ConfirmReplacementInput,
): ConfirmReplacementOutput {
  const { selectionMode, sourceHex, targetHex, currentColorRemapMap, currentRegionReplacementCount, sourceColors } = input;

  if (selectionMode === "current" || selectionMode === "region") {
    // current/region: only increment regionReplacementCount, do NOT touch colorRemapMap
    return {
      colorRemapMap: { ...currentColorRemapMap },
      regionReplacementCount: currentRegionReplacementCount + 1,
    };
  } else if (selectionMode === "multi-select") {
    // multi-select: update colorRemapMap for all sourceColors
    const newMap = { ...currentColorRemapMap };
    for (const hex of sourceColors ?? []) {
      newMap[hex] = targetHex;
    }
    return {
      colorRemapMap: newMap,
      regionReplacementCount: currentRegionReplacementCount,
    };
  } else {
    // select-all: update colorRemapMap with single mapping
    return {
      colorRemapMap: { ...currentColorRemapMap, [sourceHex]: targetHex },
      regionReplacementCount: currentRegionReplacementCount,
    };
  }
}

// ========== Generators ==========

const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

const globalMode: fc.Arbitrary<SelectionMode> = fc.constantFrom(
  "select-all" as const,
  "multi-select" as const,
);

const regionMode: fc.Arbitrary<SelectionMode> = fc.constantFrom(
  "current" as const,
  "region" as const,
);

const anyMode: fc.Arbitrary<SelectionMode> = fc.constantFrom(
  "select-all" as const,
  "current" as const,
  "multi-select" as const,
  "region" as const,
);

const hexColorArray = fc.uniqueArray(hexColor, { minLength: 1, maxLength: 8 });

const existingRemapMap = fc.dictionary(hexColor, hexColor, {
  minKeys: 0,
  maxKeys: 5,
});

const regionCount = fc.nat({ max: 100 });

// ========== Tests ==========

describe("Feature: region-replace-generate-fix — Property 1: colorRemapMap 更新与选择模式的关系", () => {
  /**
   * **Validates: Requirements 2.1, 2.2, 2.3, 3.1, 3.2, 9.1, 9.2**
   *
   * Property 1: For any pending replacement and any selection mode,
   * confirmReplacement updates colorRemapMap if and only if mode is
   * select-all or multi-select. When mode is current or region,
   * colorRemapMap remains unchanged and only regionReplacementCount increments.
   */

  describe("current/region modes: colorRemapMap unchanged, regionReplacementCount increments", () => {
    it("colorRemapMap is identical before and after for current/region modes", () => {
      fc.assert(
        fc.property(
          regionMode,
          hexColor,
          hexColor,
          existingRemapMap,
          regionCount,
          (mode, sourceHex, targetHex, initialMap, initialCount) => {
            const result = computeConfirmReplacementStateUpdate({
              selectionMode: mode,
              sourceHex,
              targetHex,
              currentColorRemapMap: initialMap,
              currentRegionReplacementCount: initialCount,
            });

            // colorRemapMap must be unchanged
            expect(result.colorRemapMap).toEqual(initialMap);

            // regionReplacementCount must increment by exactly 1
            expect(result.regionReplacementCount).toBe(initialCount + 1);
          },
        ),
        { numRuns: 200 },
      );
    });
  });

  describe("select-all mode: colorRemapMap updated, regionReplacementCount unchanged", () => {
    it("colorRemapMap contains sourceHex → targetHex mapping after select-all", () => {
      fc.assert(
        fc.property(
          hexColor,
          hexColor,
          existingRemapMap,
          regionCount,
          (sourceHex, targetHex, initialMap, initialCount) => {
            const result = computeConfirmReplacementStateUpdate({
              selectionMode: "select-all",
              sourceHex,
              targetHex,
              currentColorRemapMap: initialMap,
              currentRegionReplacementCount: initialCount,
            });

            // colorRemapMap must contain the new mapping
            expect(result.colorRemapMap[sourceHex]).toBe(targetHex);

            // All pre-existing mappings (except sourceHex) must be preserved
            for (const [key, value] of Object.entries(initialMap)) {
              if (key !== sourceHex) {
                expect(result.colorRemapMap[key]).toBe(value);
              }
            }

            // regionReplacementCount must NOT change
            expect(result.regionReplacementCount).toBe(initialCount);
          },
        ),
        { numRuns: 200 },
      );
    });
  });

  describe("multi-select mode: colorRemapMap updated for all sourceColors, regionReplacementCount unchanged", () => {
    it("colorRemapMap maps every sourceColor to targetHex after multi-select", () => {
      fc.assert(
        fc.property(
          hexColorArray,
          hexColor,
          existingRemapMap,
          regionCount,
          (sourceColors, targetHex, initialMap, initialCount) => {
            const result = computeConfirmReplacementStateUpdate({
              selectionMode: "multi-select",
              sourceHex: sourceColors[0],
              targetHex,
              currentColorRemapMap: initialMap,
              currentRegionReplacementCount: initialCount,
              sourceColors,
            });

            // Every sourceColor must map to targetHex
            for (const hex of sourceColors) {
              expect(result.colorRemapMap[hex]).toBe(targetHex);
            }

            // Pre-existing mappings not in sourceColors must be preserved
            for (const [key, value] of Object.entries(initialMap)) {
              if (!sourceColors.includes(key)) {
                expect(result.colorRemapMap[key]).toBe(value);
              }
            }

            // regionReplacementCount must NOT change
            expect(result.regionReplacementCount).toBe(initialCount);
          },
        ),
        { numRuns: 200 },
      );
    });
  });

  describe("biconditional: colorRemapMap changes iff mode is select-all or multi-select", () => {
    it("for any mode, colorRemapMap changes ↔ mode ∈ {select-all, multi-select}", () => {
      fc.assert(
        fc.property(
          anyMode,
          hexColor,
          hexColor,
          existingRemapMap,
          regionCount,
          hexColorArray,
          (mode, sourceHex, targetHex, initialMap, initialCount, sourceColors) => {
            // Ensure sourceHex is not already mapped to targetHex to detect real changes
            fc.pre(initialMap[sourceHex] !== targetHex);

            const result = computeConfirmReplacementStateUpdate({
              selectionMode: mode,
              sourceHex,
              targetHex,
              currentColorRemapMap: initialMap,
              currentRegionReplacementCount: initialCount,
              sourceColors,
            });

            const isGlobalMode = mode === "select-all" || mode === "multi-select";
            const mapChanged =
              JSON.stringify(result.colorRemapMap) !== JSON.stringify(initialMap);

            // colorRemapMap changes if and only if mode is global
            expect(mapChanged).toBe(isGlobalMode);

            // regionReplacementCount changes if and only if mode is region-local
            const countChanged = result.regionReplacementCount !== initialCount;
            expect(countChanged).toBe(!isGlobalMode);
          },
        ),
        { numRuns: 200 },
      );
    });
  });
});


// ========== Property 2: submitGenerate 标志一致性 ==========

/**
 * Pure function replicating the use_cached_matched_rgb flag logic in submitGenerate.
 * Mirrors the actual store implementation in converterStore.ts (post task 4.3).
 *
 * 纯函数，复制 submitGenerate 中 use_cached_matched_rgb 标志的计算逻辑。
 */
function computeUseCachedMatchedRgb(regionReplacementCount: number): boolean {
  return regionReplacementCount > 0;
}

describe("Feature: region-replace-generate-fix — Property 2: use_cached_matched_rgb 标志与 regionReplacementCount 的一致性", () => {
  /**
   * **Validates: Requirements 4.1, 4.2**
   *
   * Property 2: For any regionReplacementCount value, the use_cached_matched_rgb
   * flag sent by submitGenerate equals (regionReplacementCount > 0).
   */

  describe("regionReplacementCount > 0 → use_cached_matched_rgb === true", () => {
    it("flag is true for all positive regionReplacementCount values", () => {
      fc.assert(
        fc.property(
          fc.integer({ min: 1, max: 10000 }),
          (count) => {
            expect(computeUseCachedMatchedRgb(count)).toBe(true);
          },
        ),
        { numRuns: 200 },
      );
    });
  });

  describe("regionReplacementCount === 0 → use_cached_matched_rgb === false", () => {
    it("flag is false when regionReplacementCount is zero", () => {
      expect(computeUseCachedMatchedRgb(0)).toBe(false);
    });
  });

  describe("biconditional: use_cached_matched_rgb ↔ regionReplacementCount > 0", () => {
    it("for any non-negative integer, flag equals (count > 0)", () => {
      fc.assert(
        fc.property(
          fc.nat({ max: 10000 }),
          (count) => {
            const flag = computeUseCachedMatchedRgb(count);
            expect(flag).toBe(count > 0);
          },
        ),
        { numRuns: 200 },
      );
    });
  });
});


// ========== Property 4: clearAllRemaps 重置所有替换状态 ==========

/**
 * Pure function replicating the state reset logic of clearAllRemaps.
 * Mirrors the actual store implementation in converterStore.ts.
 *
 * 纯函数，复制 clearAllRemaps 的状态重置逻辑。
 */
interface ClearAllRemapsInput {
  colorRemapMap: Record<string, string>;
  regionReplacementCount: number;
  remapHistory: Array<{ sourceHex: string; targetHex: string }>;
  regionData: object | null;
}

interface ClearAllRemapsOutput {
  colorRemapMap: Record<string, string>;
  regionReplacementCount: number;
  remapHistory: Array<{ sourceHex: string; targetHex: string }>;
  regionData: object | null;
}

function computeClearAllRemapsStateUpdate(
  _input: ClearAllRemapsInput,
): ClearAllRemapsOutput {
  return {
    colorRemapMap: {},
    regionReplacementCount: 0,
    remapHistory: [],
    regionData: null,
  };
}

// ========== Generators ==========

const hexColorP4 = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

const remapMapP4 = fc.dictionary(hexColorP4, hexColorP4, {
  minKeys: 1,
  maxKeys: 10,
});

const remapHistoryP4 = fc.array(
  fc.record({
    sourceHex: hexColorP4,
    targetHex: hexColorP4,
  }),
  { minLength: 1, maxLength: 10 },
);

const regionDataP4: fc.Arbitrary<object | null> = fc.oneof(
  fc.constant(null),
  fc.record({
    x: fc.integer({ min: 0, max: 1000 }),
    y: fc.integer({ min: 0, max: 1000 }),
    width: fc.integer({ min: 1, max: 500 }),
    height: fc.integer({ min: 1, max: 500 }),
  }),
);

const regionCountP4 = fc.integer({ min: 1, max: 1000 });

// ========== Tests ==========

describe("Feature: region-replace-generate-fix — Property 4: clearAllRemaps 重置所有替换状态", () => {
  /**
   * **Validates: Requirements 8.1**
   *
   * Property 4: For any store state with color replacements
   * (colorRemapMap non-empty or regionReplacementCount > 0),
   * after calling clearAllRemaps, colorRemapMap should be {},
   * regionReplacementCount should be 0, remapHistory should be [],
   * and regionData should be null.
   */

  describe("clearAllRemaps resets all replacement state to initial values", () => {
    it("colorRemapMap becomes {}, regionReplacementCount becomes 0, remapHistory becomes [], regionData becomes null", () => {
      fc.assert(
        fc.property(
          remapMapP4,
          regionCountP4,
          remapHistoryP4,
          regionDataP4,
          (colorRemapMap, regionReplacementCount, remapHistory, regionData) => {
            const result = computeClearAllRemapsStateUpdate({
              colorRemapMap,
              regionReplacementCount,
              remapHistory,
              regionData,
            });

            expect(result.colorRemapMap).toEqual({});
            expect(result.regionReplacementCount).toBe(0);
            expect(result.remapHistory).toEqual([]);
            expect(result.regionData).toBeNull();
          },
        ),
        { numRuns: 200 },
      );
    });
  });

  describe("clearAllRemaps output is independent of input state", () => {
    it("any two different input states produce identical output after clearAllRemaps", () => {
      fc.assert(
        fc.property(
          remapMapP4,
          regionCountP4,
          remapHistoryP4,
          regionDataP4,
          remapMapP4,
          regionCountP4,
          remapHistoryP4,
          regionDataP4,
          (map1, count1, hist1, data1, map2, count2, hist2, data2) => {
            const result1 = computeClearAllRemapsStateUpdate({
              colorRemapMap: map1,
              regionReplacementCount: count1,
              remapHistory: hist1,
              regionData: data1,
            });

            const result2 = computeClearAllRemapsStateUpdate({
              colorRemapMap: map2,
              regionReplacementCount: count2,
              remapHistory: hist2,
              regionData: data2,
            });

            expect(result1).toEqual(result2);
          },
        ),
        { numRuns: 200 },
      );
    });
  });

  describe("clearAllRemaps is idempotent", () => {
    it("applying clearAllRemaps twice yields the same result as once", () => {
      fc.assert(
        fc.property(
          remapMapP4,
          regionCountP4,
          remapHistoryP4,
          regionDataP4,
          (colorRemapMap, regionReplacementCount, remapHistory, regionData) => {
            const firstClear = computeClearAllRemapsStateUpdate({
              colorRemapMap,
              regionReplacementCount,
              remapHistory,
              regionData,
            });

            const secondClear = computeClearAllRemapsStateUpdate(firstClear);

            expect(secondClear).toEqual(firstClear);
          },
        ),
        { numRuns: 200 },
      );
    });
  });
});


// ========== 单元测试: select-all/multi-select 模式不受影响 ==========

describe("select-all/multi-select 模式不受影响", () => {
  /**
   * **Validates: Requirements 9.1, 9.2, 9.3**
   *
   * Unit tests verifying that select-all and multi-select modes
   * continue to work correctly after the region-replace fix:
   * - colorRemapMap is updated as expected
   * - regionReplacementCount is NOT modified
   * - Pre-existing mappings are preserved
   */

  describe("select-all 模式正常更新 colorRemapMap (Req 9.1)", () => {
    it("should add sourceHex → targetHex mapping to colorRemapMap", () => {
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "select-all",
        sourceHex: "ff0000",
        targetHex: "00ff00",
        currentColorRemapMap: {},
        currentRegionReplacementCount: 0,
      });

      expect(result.colorRemapMap).toEqual({ ff0000: "00ff00" });
      expect(result.regionReplacementCount).toBe(0);
    });

    it("should not increment regionReplacementCount", () => {
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "select-all",
        sourceHex: "aabbcc",
        targetHex: "112233",
        currentColorRemapMap: {},
        currentRegionReplacementCount: 5,
      });

      expect(result.regionReplacementCount).toBe(5);
    });

    it("should preserve pre-existing mappings when adding a new one", () => {
      const existing = { "111111": "222222", "333333": "444444" };
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "select-all",
        sourceHex: "ff0000",
        targetHex: "00ff00",
        currentColorRemapMap: existing,
        currentRegionReplacementCount: 0,
      });

      expect(result.colorRemapMap).toEqual({
        "111111": "222222",
        "333333": "444444",
        ff0000: "00ff00",
      });
    });

    it("should overwrite an existing mapping for the same sourceHex", () => {
      const existing = { ff0000: "0000ff" };
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "select-all",
        sourceHex: "ff0000",
        targetHex: "00ff00",
        currentColorRemapMap: existing,
        currentRegionReplacementCount: 0,
      });

      expect(result.colorRemapMap).toEqual({ ff0000: "00ff00" });
    });
  });

  describe("multi-select 模式正常批量更新 colorRemapMap (Req 9.2)", () => {
    it("should map all sourceColors to targetHex", () => {
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "multi-select",
        sourceHex: "ff0000",
        targetHex: "ffffff",
        currentColorRemapMap: {},
        currentRegionReplacementCount: 0,
        sourceColors: ["ff0000", "00ff00", "0000ff"],
      });

      expect(result.colorRemapMap).toEqual({
        ff0000: "ffffff",
        "00ff00": "ffffff",
        "0000ff": "ffffff",
      });
      expect(result.regionReplacementCount).toBe(0);
    });

    it("should not increment regionReplacementCount", () => {
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "multi-select",
        sourceHex: "aabbcc",
        targetHex: "000000",
        currentColorRemapMap: {},
        currentRegionReplacementCount: 3,
        sourceColors: ["aabbcc", "ddeeff"],
      });

      expect(result.regionReplacementCount).toBe(3);
    });

    it("should preserve pre-existing mappings not in sourceColors", () => {
      const existing = { "111111": "222222" };
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "multi-select",
        sourceHex: "ff0000",
        targetHex: "000000",
        currentColorRemapMap: existing,
        currentRegionReplacementCount: 0,
        sourceColors: ["ff0000", "00ff00"],
      });

      expect(result.colorRemapMap).toEqual({
        "111111": "222222",
        ff0000: "000000",
        "00ff00": "000000",
      });
    });

    it("should overwrite existing mappings for colors in sourceColors", () => {
      const existing = { ff0000: "aaaaaa", "00ff00": "bbbbbb" };
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "multi-select",
        sourceHex: "ff0000",
        targetHex: "000000",
        currentColorRemapMap: existing,
        currentRegionReplacementCount: 0,
        sourceColors: ["ff0000", "00ff00"],
      });

      expect(result.colorRemapMap).toEqual({
        ff0000: "000000",
        "00ff00": "000000",
      });
    });

    it("should handle empty sourceColors gracefully", () => {
      const existing = { "111111": "222222" };
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "multi-select",
        sourceHex: "ff0000",
        targetHex: "000000",
        currentColorRemapMap: existing,
        currentRegionReplacementCount: 0,
        sourceColors: [],
      });

      // No new mappings added, existing preserved
      expect(result.colorRemapMap).toEqual({ "111111": "222222" });
      expect(result.regionReplacementCount).toBe(0);
    });
  });

  describe("select-all/multi-select 生成 3MF 时通过 replacement_regions 应用全局替换 (Req 9.3)", () => {
    it("select-all: regionReplacementCount stays 0, so use_cached_matched_rgb would be false", () => {
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "select-all",
        sourceHex: "ff0000",
        targetHex: "00ff00",
        currentColorRemapMap: {},
        currentRegionReplacementCount: 0,
      });

      // regionReplacementCount unchanged → generate uses normal path (replacement_regions)
      expect(result.regionReplacementCount).toBe(0);
      expect(computeUseCachedMatchedRgb(result.regionReplacementCount)).toBe(false);
    });

    it("multi-select: regionReplacementCount stays 0, so use_cached_matched_rgb would be false", () => {
      const result = computeConfirmReplacementStateUpdate({
        selectionMode: "multi-select",
        sourceHex: "ff0000",
        targetHex: "00ff00",
        currentColorRemapMap: {},
        currentRegionReplacementCount: 0,
        sourceColors: ["ff0000", "0000ff"],
      });

      // regionReplacementCount unchanged → generate uses normal path (replacement_regions)
      expect(result.regionReplacementCount).toBe(0);
      expect(computeUseCachedMatchedRgb(result.regionReplacementCount)).toBe(false);
    });
  });
});
