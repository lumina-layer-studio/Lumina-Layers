import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { createKeychainRingGeometry } from "../components/KeychainRing3D";

// ========== Generators ==========

/** Generate width in valid range [2, 10] mm */
const widthArb = fc.double({ min: 2, max: 10, noNaN: true, noDefaultInfinity: true });

/** Generate length in valid range [4, 15] mm */
const lengthArb = fc.double({ min: 4, max: 15, noNaN: true, noDefaultInfinity: true });

/** Generate hole in valid range [1, 5] mm */
const holeArb = fc.double({ min: 1, max: 5, noNaN: true, noDefaultInfinity: true });

// ========== Tests ==========

describe("Keychain Ring Params — Property-Based Tests", () => {
  /**
   * P12: valid width/length/hole produce non-degenerate geometry
   * **Validates: Requirements 7.4**
   *
   * For any width in [2,10], length in [4,15], hole in [1,5],
   * if hole < min(width, length), then the generated geometry
   * has vertices > 0 (non-degenerate).
   */
  it("P12: valid params with hole < min(width, length) produce non-degenerate geometry", () => {
    fc.assert(
      fc.property(widthArb, lengthArb, holeArb, (width, length, hole) => {
        // Precondition: hole must be strictly less than min(width, length)
        fc.pre(hole < Math.min(width, length));

        const geometry = createKeychainRingGeometry(width, length, hole);

        // Geometry must not be null
        expect(geometry).not.toBeNull();

        // Geometry must have vertices (non-degenerate)
        const vertexCount = geometry!.attributes.position.count;
        expect(vertexCount).toBeGreaterThan(0);
      }),
      { numRuns: 200 },
    );
  });

  /**
   * Complementary: when hole >= min(width, length), geometry should be null.
   * **Validates: Requirements 7.4**
   */
  it("P12 complement: hole >= min(width, length) produces null geometry", () => {
    fc.assert(
      fc.property(widthArb, lengthArb, holeArb, (width, length, hole) => {
        // Precondition: hole must be >= min(width, length)
        fc.pre(hole >= Math.min(width, length));

        const geometry = createKeychainRingGeometry(width, length, hole);
        expect(geometry).toBeNull();
      }),
      { numRuns: 200 },
    );
  });
});
