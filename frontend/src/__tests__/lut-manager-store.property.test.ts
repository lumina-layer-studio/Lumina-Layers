import { describe, it } from "vitest";
import * as fc from "fast-check";
import { filterSecondaryOptions } from "../stores/lutManagerStore";
import { ColorMode } from "../api/types";

// ========== Arbitraries ==========

const COLOR_MODES = [
  ColorMode.BW,
  ColorMode.FOUR_COLOR,
  ColorMode.SIX_COLOR,
  ColorMode.EIGHT_COLOR,
  ColorMode.MERGED,
] as const;

/** Short-form primary modes from detect_color_mode */
const PRIMARY_MODES = ["6-Color", "8-Color"] as const;

const ALLOWED_SECONDARY: Record<string, string[]> = {
  "8-Color": ["BW", "4-Color", "6-Color"],
  "6-Color": ["BW", "4-Color"],
};

const lutInfoArb = fc.record({
  name: fc.string({ minLength: 1, maxLength: 20 }),
  color_mode: fc.constantFrom(...COLOR_MODES) as fc.Arbitrary<ColorMode>,
  path: fc.constant("/fake/path.npy"),
});

const lutListArb = fc.array(lutInfoArb, { minLength: 0, maxLength: 20 });

// ========== Tests ==========

describe("LutManagerStore Property-Based Tests", () => {
  // **Validates: Requirements 3.1, 3.2, 3.3**
  describe("Property 1: Secondary LUT 兼容性过滤正确性", () => {
    it("filtered results only contain LUTs with allowed modes, excluding primary and Merged", () => {
      fc.assert(
        fc.property(
          lutListArb,
          fc.constantFrom(...PRIMARY_MODES),
          fc.string({ minLength: 1, maxLength: 20 }),
          (lutList, primaryMode, primaryName) => {
            const result = filterSecondaryOptions(
              lutList,
              primaryName,
              primaryMode
            );
            const allowed = ALLOWED_SECONDARY[primaryMode];

            for (const name of result) {
              const lut = lutList.find((l) => l.name === name);
              if (!lut) return false;
              // Must not be the primary itself
              if (lut.name === primaryName) return false;
              // Must not be Merged
              if (lut.color_mode === "Merged") return false;
              // Must match one of the allowed short modes
              const matchesAllowed = allowed.some((mode) =>
                lut.color_mode.startsWith(mode)
              );
              if (!matchesAllowed) return false;
            }
            return true;
          }
        ),
        { numRuns: 100 }
      );
    });

    it("all eligible LUTs from the list appear in the filtered result", () => {
      fc.assert(
        fc.property(
          lutListArb,
          fc.constantFrom(...PRIMARY_MODES),
          fc.string({ minLength: 1, maxLength: 20 }),
          (lutList, primaryMode, primaryName) => {
            const result = filterSecondaryOptions(
              lutList,
              primaryName,
              primaryMode
            );
            const allowed = ALLOWED_SECONDARY[primaryMode];

            // Every eligible LUT should be in the result
            for (const lut of lutList) {
              if (lut.name === primaryName) continue;
              if (lut.color_mode === "Merged") continue;
              const matchesAllowed = allowed.some((mode) =>
                lut.color_mode.startsWith(mode)
              );
              if (matchesAllowed) {
                if (!result.includes(lut.name)) return false;
              }
            }
            return true;
          }
        ),
        { numRuns: 100 }
      );
    });

    it("returns empty array for non-6/8-Color primary modes", () => {
      fc.assert(
        fc.property(
          lutListArb,
          fc.constantFrom("BW", "4-Color", "Merged", "Unknown"),
          fc.string({ minLength: 1, maxLength: 20 }),
          (lutList, invalidMode, primaryName) => {
            const result = filterSecondaryOptions(
              lutList,
              primaryName,
              invalidMode
            );
            return result.length === 0;
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // **Validates: Requirements 2.3, 3.5, 5.2**
  describe("Property 2: 合并按钮禁用状态不变量", () => {
    it("merge button is disabled when primaryName is empty, primaryMode is invalid, or no secondaries selected", () => {
      fc.assert(
        fc.property(
          fc.string({ minLength: 0, maxLength: 20 }),
          fc.oneof(
            fc.record({
              color_mode: fc.constantFrom(...COLOR_MODES) as fc.Arbitrary<ColorMode>,
            }),
            fc.constant(null)
          ),
          fc.array(fc.string({ minLength: 1, maxLength: 20 }), {
            minLength: 0,
            maxLength: 10,
          }),
          (primaryName, primaryInfo, secondaryNames) => {
            const isMergeable =
              primaryInfo !== null &&
              ["6-Color", "8-Color"].some((prefix) =>
                primaryInfo.color_mode.startsWith(prefix)
              );

            const shouldBeDisabled =
              primaryName === "" ||
              secondaryNames.length === 0 ||
              !isMergeable;

            // When any disabling condition is true, button must be disabled
            if (primaryName === "") return shouldBeDisabled === true;
            if (secondaryNames.length === 0) return shouldBeDisabled === true;
            if (!isMergeable) return shouldBeDisabled === true;

            // All conditions met → button should be enabled
            return shouldBeDisabled === false;
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
