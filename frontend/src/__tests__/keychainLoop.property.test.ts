/**
 * Property-Based Tests for KeychainRing3D ring geometry.
 * 钥匙扣环 3D 几何体的 Property-Based 测试。
 *
 * Feature: keychain-loop-enhancement
 * Properties: 5, 6
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { createKeychainRingGeometry } from "../components/KeychainRing3D";

/**
 * Smart generator: derive hole from width/length to guarantee validity.
 * Constraints:
 * - hole < min(width, length) (geometry validity)
 * - length >= width/2 + 0.5 (rectHeight not clamped, so BB height ≈ length)
 * - hole/2 <= rectHeight = length - width/2 (hole circle stays within shape,
 *   preventing BB extension below y=0 from ExtrudeGeometry triangulation)
 */
const validGeomParamsArb = fc
  .record({
    width: fc.double({ min: 2, max: 12, noNaN: true, noDefaultInfinity: true }),
    length: fc.double({ min: 2, max: 20, noNaN: true, noDefaultInfinity: true }),
    holeFraction: fc.double({ min: 0.05, max: 0.9, noNaN: true, noDefaultInfinity: true }),
  })
  .filter(({ width, length }) => {
    // Ensure rectHeight is not clamped: length - width/2 >= 0.5
    return length >= width / 2 + 0.5;
  })
  .map(({ width, length, holeFraction }) => {
    const rectHeight = length - width / 2;
    // hole must be < min(width, length) AND hole/2 <= rectHeight
    const maxHole = Math.min(Math.min(width, length) * 0.99, rectHeight * 2);
    return {
      width,
      length,
      hole: holeFraction * maxHole,
    };
  })
  .filter(({ hole }) => hole > 0.1);

/**
 * Generator for invalid geometry params with a non-positive dimension.
 */
const invalidGeomParamsArb = fc.oneof(
  // Case 1: some param <= 0
  fc.record({
    width: fc.double({ min: -10, max: 0, noNaN: true, noDefaultInfinity: true }),
    length: fc.double({ min: 1, max: 15, noNaN: true, noDefaultInfinity: true }),
    hole: fc.double({ min: 0.5, max: 5, noNaN: true, noDefaultInfinity: true }),
  }),
  fc.record({
    width: fc.double({ min: 1, max: 10, noNaN: true, noDefaultInfinity: true }),
    length: fc.double({ min: -10, max: 0, noNaN: true, noDefaultInfinity: true }),
    hole: fc.double({ min: 0.5, max: 5, noNaN: true, noDefaultInfinity: true }),
  }),
  fc.record({
    width: fc.double({ min: 1, max: 10, noNaN: true, noDefaultInfinity: true }),
    length: fc.double({ min: 1, max: 15, noNaN: true, noDefaultInfinity: true }),
    hole: fc.double({ min: -10, max: 0, noNaN: true, noDefaultInfinity: true }),
  }),
);

// ========== Property-Based Tests ==========

describe("KeychainRing3D — Property-Based Tests", () => {
  /**
   * Feature: keychain-loop-enhancement, Property 5: 前端几何体有效参数生成正确性
   * **Validates: Requirements 4.2**
   *
   * For any valid params (width > 0, length > 0, hole > 0, hole < min(width, length)),
   * createKeychainRingGeometry returns a non-null ExtrudeGeometry whose bounding box
   * width ≈ width and height ≈ length.
   */
  it("Property 5: 前端几何体有效参数生成正确性 — valid params produce geometry with correct bounding box", () => {
    fc.assert(
      fc.property(validGeomParamsArb, ({ width, length, hole }) => {
        const geometry = createKeychainRingGeometry(width, length, hole);

        // Must return non-null
        expect(geometry).not.toBeNull();

        // Compute bounding box
        geometry!.computeBoundingBox();
        const bb = geometry!.boundingBox!;

        // BB width (X axis): shape spans from -halfW to +halfW = width
        // With constrained hole (doesn't extend beyond shape boundary),
        // the BB should closely match the theoretical dimensions.
        const bbWidth = bb.max.x - bb.min.x;
        expect(bbWidth).toBeCloseTo(width, 0);

        // BB height (Y axis): shape spans from 0 to rectHeight + circleRadius
        // When length >= width/2 + 0.5, rectHeight = length - width/2,
        // so total = (length - width/2) + width/2 = length.
        // With hole constrained within shape, BB min Y ≈ 0.
        const bbHeight = bb.max.y - bb.min.y;
        expect(bbHeight).toBeCloseTo(length, 0);
      }),
      { numRuns: 200 },
    );
  });

  /**
   * Feature: keychain-loop-enhancement, Property 6: 前端几何体无效参数返回 null
   * **Validates: Requirements 6.3**
   *
   * For any invalid params (any param <= 0),
   * createKeychainRingGeometry returns null.
   */
  it("Property 6: 前端几何体无效参数返回 null — invalid params produce null geometry", () => {
    fc.assert(
      fc.property(invalidGeomParamsArb, ({ width, length, hole }) => {
        const result = createKeychainRingGeometry(width, length, hole);
        expect(result).toBeNull();
      }),
      { numRuns: 200 },
    );
  });
});

// ========== Store Clamping Tests ==========

import { useConverterStore } from "../stores/converter";

describe("converterStore — Property-Based Clamping Tests", () => {
  /**
   * Feature: keychain-loop-enhancement, Property 1: 挂孔参数 clamping 正确性
   * **Validates: Requirements 1.1, 3.2, 3.3**
   *
   * For any numeric input, converterStore clamping functions should constrain
   * loop_angle to [-180, 180], loop_offset_x to [-20, 20], loop_offset_y to [-20, 20],
   * and the result is always within the corresponding range.
   */
  it("Property 1: setLoopAngle clamps to [-180, 180]", () => {
    fc.assert(
      fc.property(
        fc.double({ noNaN: true, noDefaultInfinity: true, min: -1e6, max: 1e6 }),
        (angle) => {
          useConverterStore.getState().setLoopAngle(angle);
          const result = useConverterStore.getState().loop_angle;
          expect(result).toBeGreaterThanOrEqual(-180);
          expect(result).toBeLessThanOrEqual(180);
        },
      ),
      { numRuns: 200 },
    );
  });

  it("Property 1: setLoopOffsetX clamps to [-200, 200]", () => {
    fc.assert(
      fc.property(
        fc.double({ noNaN: true, noDefaultInfinity: true, min: -1e6, max: 1e6 }),
        (x) => {
          useConverterStore.getState().setLoopOffsetX(x);
          const result = useConverterStore.getState().loop_offset_x;
          expect(result).toBeGreaterThanOrEqual(-200);
          expect(result).toBeLessThanOrEqual(200);
        },
      ),
      { numRuns: 200 },
    );
  });

  it("Property 1: setLoopOffsetY clamps to [-200, 200]", () => {
    fc.assert(
      fc.property(
        fc.double({ noNaN: true, noDefaultInfinity: true, min: -1e6, max: 1e6 }),
        (y) => {
          useConverterStore.getState().setLoopOffsetY(y);
          const result = useConverterStore.getState().loop_offset_y;
          expect(result).toBeGreaterThanOrEqual(-200);
          expect(result).toBeLessThanOrEqual(200);
        },
      ),
      { numRuns: 200 },
    );
  });

  it("Property 1: in-range values are preserved exactly", () => {
    fc.assert(
      fc.property(
        fc.double({ noNaN: true, noDefaultInfinity: true, min: -180, max: 180 }),
        fc.double({ noNaN: true, noDefaultInfinity: true, min: -200, max: 200 }),
        fc.double({ noNaN: true, noDefaultInfinity: true, min: -200, max: 200 }),
        (angle, offX, offY) => {
          const { setLoopAngle, setLoopOffsetX, setLoopOffsetY } =
            useConverterStore.getState();
          setLoopAngle(angle);
          setLoopOffsetX(offX);
          setLoopOffsetY(offY);

          const state = useConverterStore.getState();
          expect(state.loop_angle).toBe(angle);
          expect(state.loop_offset_x).toBe(offX);
          expect(state.loop_offset_y).toBe(offY);
        },
      ),
      { numRuns: 200 },
    );
  });
});
