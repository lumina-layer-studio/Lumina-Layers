import { describe, it, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useConverterStore } from "../stores/converterStore";

// ========== Helpers ==========

/** Reset store to default state before each test */
function resetStore(): void {
  useConverterStore.setState({
    bed_label: "256×256 mm",
    bedSizes: [],
    bedSizesLoading: false,
    target_width_mm: 60,
    target_height_mm: 60,
    aspectRatio: null,
  });
}

// ========== Tests ==========

describe("BedSizeSelector Property-Based Tests", () => {
  beforeEach(() => {
    resetStore();
  });

  // **Validates: Requirements 2.2, 5.1**
  describe("Property 2: setBedLabel 状态隔离性", () => {
    it("setBedLabel updates bed_label without changing target_width_mm or target_height_mm", () => {
      fc.assert(
        fc.property(
          fc.string({ minLength: 1, maxLength: 100 }),
          fc.integer({ min: 10, max: 400 }),
          fc.integer({ min: 10, max: 400 }),
          (label, initialWidth, initialHeight) => {
            resetStore();

            // Set initial target values
            useConverterStore.setState({
              target_width_mm: initialWidth,
              target_height_mm: initialHeight,
            });

            // Call setBedLabel
            useConverterStore.getState().setBedLabel(label);

            const state = useConverterStore.getState();

            // bed_label should be updated
            if (state.bed_label !== label) return false;

            // target values should remain unchanged
            if (state.target_width_mm !== initialWidth) return false;
            if (state.target_height_mm !== initialHeight) return false;

            return true;
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
