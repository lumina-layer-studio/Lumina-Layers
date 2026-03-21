import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { computeScaleFactor } from "../utils/scaleUtils";

// ========== Generators ==========

/** Positive float dimension in [1, 1000], no NaN */
const positiveDimension = fc.float({ min: 1, max: 1000, noNaN: true });

/** Preview dimension that may be null (simulating missing preview size) */
const optionalDimension = fc.option(positiveDimension, { nil: null });

/** Zero or negative float for invalid preview dimensions */
const nonPositiveDimension = fc.oneof(
  fc.constant(0),
  fc.float({ min: -1000, max: Math.fround(-0.01), noNaN: true }),
);

// ========== Tests ==========

describe("Feature: auto-preview-realtime-resize, Property 1: 缩放比例计算正确性", () => {
  /**
   * **Validates: Requirements 4.1, 5.3, 6.1, 6.2, 6.3**
   *
   * For any positive currentWidth, currentHeight, previewWidth, previewHeight,
   * computeScaleFactor should return uniform scale = min(cw/pw, ch/ph)
   * so that the model preserves its aspect ratio.
   */
  describe("正数维度 → 返回等比缩放比例", () => {
    it("scaleX === scaleY === min(cw/pw, ch/ph)（保持宽高比）", () => {
      fc.assert(
        fc.property(
          positiveDimension,
          positiveDimension,
          positiveDimension,
          positiveDimension,
          (currentWidth, currentHeight, previewWidth, previewHeight) => {
            const result = computeScaleFactor(
              currentWidth,
              currentHeight,
              previewWidth,
              previewHeight,
            );

            const expected = Math.min(currentWidth / previewWidth, currentHeight / previewHeight);
            expect(result.scaleX).toBeCloseTo(expected, 5);
            expect(result.scaleY).toBeCloseTo(expected, 5);
            // Uniform: both axes must be equal
            expect(result.scaleX).toBe(result.scaleY);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("相等尺寸 → 缩放比例为 1.0", () => {
      fc.assert(
        fc.property(
          positiveDimension,
          positiveDimension,
          (width, height) => {
            const result = computeScaleFactor(width, height, width, height);

            expect(result.scaleX).toBeCloseTo(1.0, 10);
            expect(result.scaleY).toBeCloseTo(1.0, 10);
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  /**
   * **Validates: Requirements 4.1, 5.3, 6.1, 6.2, 6.3**
   *
   * When previewWidth or previewHeight is null, 0, or negative,
   * the function should return { scaleX: 1.0, scaleY: 1.0 }.
   */
  describe("无效预览维度 → 返回默认值 (1.0, 1.0)", () => {
    it("previewWidth 为 null → 返回默认值", () => {
      fc.assert(
        fc.property(
          positiveDimension,
          positiveDimension,
          optionalDimension,
          (currentWidth, currentHeight, previewHeight) => {
            const result = computeScaleFactor(
              currentWidth,
              currentHeight,
              null,
              previewHeight,
            );

            expect(result.scaleX).toBe(1);
            expect(result.scaleY).toBe(1);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("previewHeight 为 null → 返回默认值", () => {
      fc.assert(
        fc.property(
          positiveDimension,
          positiveDimension,
          optionalDimension,
          (currentWidth, currentHeight, previewWidth) => {
            const result = computeScaleFactor(
              currentWidth,
              currentHeight,
              previewWidth,
              null,
            );

            expect(result.scaleX).toBe(1);
            expect(result.scaleY).toBe(1);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("previewWidth 为 0 或负数 → 返回默认值", () => {
      fc.assert(
        fc.property(
          positiveDimension,
          positiveDimension,
          nonPositiveDimension,
          positiveDimension,
          (currentWidth, currentHeight, badPreviewWidth, previewHeight) => {
            const result = computeScaleFactor(
              currentWidth,
              currentHeight,
              badPreviewWidth,
              previewHeight,
            );

            expect(result.scaleX).toBe(1);
            expect(result.scaleY).toBe(1);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("previewHeight 为 0 或负数 → 返回默认值", () => {
      fc.assert(
        fc.property(
          positiveDimension,
          positiveDimension,
          positiveDimension,
          nonPositiveDimension,
          (currentWidth, currentHeight, previewWidth, badPreviewHeight) => {
            const result = computeScaleFactor(
              currentWidth,
              currentHeight,
              previewWidth,
              badPreviewHeight,
            );

            expect(result.scaleX).toBe(1);
            expect(result.scaleY).toBe(1);
          },
        ),
        { numRuns: 100 },
      );
    });

    it("两个预览维度都为 null → 返回默认值", () => {
      fc.assert(
        fc.property(
          positiveDimension,
          positiveDimension,
          (currentWidth, currentHeight) => {
            const result = computeScaleFactor(
              currentWidth,
              currentHeight,
              null,
              null,
            );

            expect(result.scaleX).toBe(1);
            expect(result.scaleY).toBe(1);
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
