import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { computeThicknessScale } from "../utils/scaleUtils";

// ========== Generators ==========

/** Positive float thickness in [0.01, 100], no NaN */
const positiveThickness = fc.float({ min: Math.fround(0.01), max: 100, noNaN: true });

/** Preview thickness that may be null (simulating missing preview) */
const optionalThickness = fc.option(
  fc.float({ min: Math.fround(-10), max: 100, noNaN: true }),
  { nil: null },
);

/** Zero or negative float for invalid preview thickness */
const nonPositiveThickness = fc.oneof(
  fc.constant(0),
  fc.float({ min: Math.fround(-10), max: Math.fround(-0.001), noNaN: true }),
);

// ========== Tests ==========

describe("Feature: realtime-3d-parameter-preview, Property 1: 厚度缩放比例计算正确性", () => {
  /**
   * **Validates: Requirements 1.1, 1.4, 6.1, 6.2, 6.3**
   *
   * For any positive currentThickness and positive previewThickness,
   * computeThicknessScale should return currentThickness / previewThickness.
   */
  describe("正数厚度 → 返回正确缩放比例", () => {
    it("result === currentThickness / previewThickness", () => {
      fc.assert(
        fc.property(
          positiveThickness,
          positiveThickness,
          (currentThickness, previewThickness) => {
            const result = computeThicknessScale(currentThickness, previewThickness);
            const expected = currentThickness / previewThickness;
            expect(result).toBeCloseTo(expected, 5);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("相等厚度 → 缩放比例为 1.0", () => {
      fc.assert(
        fc.property(positiveThickness, (thickness) => {
          const result = computeThicknessScale(thickness, thickness);
          expect(result).toBeCloseTo(1.0, 10);
        }),
        { numRuns: 100 },
      );
    });

    it("当前厚度为预览厚度两倍 → 缩放比例为 2.0", () => {
      fc.assert(
        fc.property(positiveThickness, (previewThickness) => {
          const result = computeThicknessScale(previewThickness * 2, previewThickness);
          expect(result).toBeCloseTo(2.0, 5);
        }),
        { numRuns: 100 },
      );
    });
  });

  /**
   * **Validates: Requirements 1.4, 6.2**
   *
   * When previewThickness is null, 0, or negative,
   * the function should return 1.0.
   */
  describe("无效预览厚度 → 返回默认值 1.0", () => {
    it("previewThickness 为 null → 返回 1.0", () => {
      fc.assert(
        fc.property(positiveThickness, (currentThickness) => {
          const result = computeThicknessScale(currentThickness, null);
          expect(result).toBe(1.0);
        }),
        { numRuns: 100 },
      );
    });

    it("previewThickness 为 0 或负数 → 返回 1.0", () => {
      fc.assert(
        fc.property(
          positiveThickness,
          nonPositiveThickness,
          (currentThickness, badPreview) => {
            const result = computeThicknessScale(currentThickness, badPreview);
            expect(result).toBe(1.0);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("随机可选 previewThickness（含 null）→ 无效时返回 1.0，有效时返回比例", () => {
      fc.assert(
        fc.property(
          positiveThickness,
          optionalThickness,
          (currentThickness, previewThickness) => {
            const result = computeThicknessScale(currentThickness, previewThickness);
            if (previewThickness === null || previewThickness <= 0) {
              expect(result).toBe(1.0);
            } else {
              expect(result).toBeCloseTo(currentThickness / previewThickness, 5);
            }
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  /**
   * **Validates: Requirements 6.4**
   *
   * computeThicknessScale is a pure function — same inputs always produce same output.
   */
  describe("纯函数性质", () => {
    it("相同输入 → 相同输出（幂等性）", () => {
      fc.assert(
        fc.property(
          positiveThickness,
          optionalThickness,
          (currentThickness, previewThickness) => {
            const r1 = computeThicknessScale(currentThickness, previewThickness);
            const r2 = computeThicknessScale(currentThickness, previewThickness);
            expect(r1).toBe(r2);
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});

// ========== Property 2: 浮雕与掐丝珐琅互斥不变量 ==========

import { useConverterStore } from "../stores/converterStore";

/** Operation type for mutual exclusion test */
type MutualExclusionOp = "relief" | "cloisonne";

/** Generator: random sequence of relief/cloisonne toggle operations */
const opSequence = fc.array(
  fc.oneof(fc.constant<MutualExclusionOp>("relief"), fc.constant<MutualExclusionOp>("cloisonne")),
  { minLength: 1, maxLength: 50 },
);

/** Reset relief/cloisonne state before each property run */
function resetMutualExclusionState(): void {
  useConverterStore.setState({
    enable_relief: false,
    enable_cloisonne: false,
  });
}

describe("Feature: realtime-3d-parameter-preview, Property 2: 浮雕与掐丝珐琅互斥不变量", () => {
  /**
   * **Validates: Requirements 8.1, 8.2**
   *
   * For any sequence of setEnableRelief(true) / setEnableCloisonne(true) calls,
   * enable_relief && enable_cloisonne should never both be true simultaneously.
   */
  describe("任意操作序列 → enable_relief 与 enable_cloisonne 不能同时为 true", () => {
    it("随机操作序列后互斥不变量始终成立", () => {
      fc.assert(
        fc.property(opSequence, (ops) => {
          resetMutualExclusionState();
          const store = useConverterStore.getState();

          for (const op of ops) {
            if (op === "relief") {
              store.setEnableRelief(true);
            } else {
              store.setEnableCloisonne(true);
            }

            const state = useConverterStore.getState();
            // Invariant: never both true at the same time
            expect(state.enable_relief && state.enable_cloisonne).toBe(false);
          }
        }),
        { numRuns: 100 },
      );
    });

    it("启用掐丝珐琅 → 浮雕自动禁用", () => {
      fc.assert(
        fc.property(fc.constant(null), () => {
          resetMutualExclusionState();
          const store = useConverterStore.getState();

          // First enable relief
          store.setEnableRelief(true);
          expect(useConverterStore.getState().enable_relief).toBe(true);

          // Then enable cloisonne — relief should be disabled
          store.setEnableCloisonne(true);
          const state = useConverterStore.getState();
          expect(state.enable_cloisonne).toBe(true);
          expect(state.enable_relief).toBe(false);
        }),
        { numRuns: 100 },
      );
    });

    it("启用浮雕 → 掐丝珐琅自动禁用", () => {
      fc.assert(
        fc.property(fc.constant(null), () => {
          resetMutualExclusionState();
          const store = useConverterStore.getState();

          // First enable cloisonne
          store.setEnableCloisonne(true);
          expect(useConverterStore.getState().enable_cloisonne).toBe(true);

          // Then enable relief — cloisonne should be disabled
          store.setEnableRelief(true);
          const state = useConverterStore.getState();
          expect(state.enable_relief).toBe(true);
          expect(state.enable_cloisonne).toBe(false);
        }),
        { numRuns: 100 },
      );
    });

    it("禁用操作不影响另一个标志", () => {
      fc.assert(
        fc.property(
          fc.oneof(fc.constant<MutualExclusionOp>("relief"), fc.constant<MutualExclusionOp>("cloisonne")),
          (enableFirst) => {
            resetMutualExclusionState();
            const store = useConverterStore.getState();

            // Enable one
            if (enableFirst === "relief") {
              store.setEnableRelief(true);
            } else {
              store.setEnableCloisonne(true);
            }

            // Disable the same one
            if (enableFirst === "relief") {
              store.setEnableRelief(false);
            } else {
              store.setEnableCloisonne(false);
            }

            const state = useConverterStore.getState();
            // Both should be false after disabling
            expect(state.enable_relief).toBe(false);
            expect(state.enable_cloisonne).toBe(false);
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
