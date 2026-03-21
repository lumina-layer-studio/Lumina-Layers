import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { computeCenterOffset } from "../components/ModelViewer";

/**
 * Feature: 3d-renderer-integration
 * Property 1: 模型居中算法正确性
 *
 * For any bounding box defined by (min, max) where min < max on each axis,
 * applying computeCenterOffset should produce an offset that moves the
 * bounding box center to the origin (0, 0, 0).
 *
 * **Validates: Requirements 4.4**
 */
describe("Feature: 3d-renderer-integration, Property 1: 模型居中算法正确性", () => {
  it("offset moves bounding box center to origin for any valid box", () => {
    fc.assert(
      fc.property(
        fc.tuple(
          fc.double({ min: -1e6, max: 1e6, noNaN: true, noDefaultInfinity: true }),
          fc.double({ min: -1e6, max: 1e6, noNaN: true, noDefaultInfinity: true }),
          fc.double({ min: -1e6, max: 1e6, noNaN: true, noDefaultInfinity: true }),
        ),
        fc.tuple(
          fc.double({ min: 0.001, max: 1e6, noNaN: true, noDefaultInfinity: true }),
          fc.double({ min: 0.001, max: 1e6, noNaN: true, noDefaultInfinity: true }),
          fc.double({ min: 0.001, max: 1e6, noNaN: true, noDefaultInfinity: true }),
        ),
        (minCoords, sizes) => {
          const min: [number, number, number] = [
            minCoords[0],
            minCoords[1],
            minCoords[2],
          ];
          const max: [number, number, number] = [
            minCoords[0] + sizes[0],
            minCoords[1] + sizes[1],
            minCoords[2] + sizes[2],
          ];

          const offset = computeCenterOffset(min, max);

          // After applying offset, the new center should be at origin
          const newCenterX = (min[0] + max[0]) / 2 + offset[0];
          const newCenterY = (min[1] + max[1]) / 2 + offset[1];
          const newCenterZ = (min[2] + max[2]) / 2 + offset[2];

          expect(Math.abs(newCenterX)).toBeLessThan(1e-6);
          expect(Math.abs(newCenterY)).toBeLessThan(1e-6);
          expect(Math.abs(newCenterZ)).toBeLessThan(1e-6);
        },
      ),
      { numRuns: 200 },
    );
  });
});
