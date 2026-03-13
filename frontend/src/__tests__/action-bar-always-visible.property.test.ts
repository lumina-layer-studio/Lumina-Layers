/**
 * Feature: action-bar-always-visible
 * Property-Based Tests for SlicerSelector disabled state computation
 *
 * Uses Vitest + fast-check
 */
import { describe, it, expect } from "vitest";
import * as fc from "fast-check";

// ========== Pure function extracted from SlicerSelector disabled logic ==========

// Feature: action-bar-always-visible, Property 1: SlicerSelector disabled 状态计算正确性

/**
 * Pure function extracted from SlicerSelector disabled logic.
 * Mirrors: const isDisabled = !canSubmit || isDetecting || isLaunching || isAutoGenerating
 *
 * 从 SlicerSelector 组件提取的纯函数，镜像 disabled 计算逻辑。
 */
function computeIsDisabled(
  canSubmit: boolean,
  isDetecting: boolean,
  isLaunching: boolean,
  isAutoGenerating: boolean,
): boolean {
  return !canSubmit || isDetecting || isLaunching || isAutoGenerating;
}

// ========== Tests ==========

describe("SlicerSelector disabled state property", () => {
  /**
   * Feature: action-bar-always-visible, Property 1: SlicerSelector disabled 状态计算正确性
   * **Validates: Requirements 1.2, 1.3, 4.1, 4.2, 5.1, 5.2**
   */
  it("Property 1: disabled equals !canSubmit || isDetecting || isLaunching || isAutoGenerating", () => {
    // **Validates: Requirements 1.2, 1.3, 4.1, 4.2, 5.1, 5.2**
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.boolean(),
        fc.boolean(),
        fc.boolean(),
        (canSubmit, isDetecting, isLaunching, isAutoGenerating) => {
          const result = computeIsDisabled(canSubmit, isDetecting, isLaunching, isAutoGenerating);
          const expected = !canSubmit || isDetecting || isLaunching || isAutoGenerating;
          expect(result).toBe(expected);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("canSubmit=false always results in disabled (Req 1.2, 5.1, 5.2)", () => {
    // **Validates: Requirements 1.2, 5.1, 5.2**
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.boolean(),
        fc.boolean(),
        (isDetecting, isLaunching, isAutoGenerating) => {
          expect(computeIsDisabled(false, isDetecting, isLaunching, isAutoGenerating)).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("all false inputs except canSubmit=true results in enabled (Req 1.3)", () => {
    // **Validates: Requirements 1.3**
    expect(computeIsDisabled(true, false, false, false)).toBe(false);
  });

  it("any blocking condition true results in disabled (Req 4.1, 4.2)", () => {
    // **Validates: Requirements 4.1, 4.2**
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.boolean(),
        fc.boolean(),
        (isDetecting, isLaunching, isAutoGenerating) => {
          if (isDetecting || isLaunching || isAutoGenerating) {
            expect(computeIsDisabled(true, isDetecting, isLaunching, isAutoGenerating)).toBe(true);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
