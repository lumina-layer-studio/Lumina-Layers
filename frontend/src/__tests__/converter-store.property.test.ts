import { describe, it, beforeEach } from "vitest";
import * as fc from "fast-check";
import {
  useConverterStore,
  clampValue,
  isValidImageType,
} from "../stores/converterStore";

// ========== Helpers ==========

/** Numeric field definitions: [setter name, state key, min, max] */
const NUMERIC_FIELDS = [
  ["setTargetWidthMm", "target_width_mm", 10, 400],
  ["setTargetHeightMm", "target_height_mm", 10, 400],
  ["setSpacerThick", "spacer_thick", 0.2, 3.5],
  ["setQuantizeColors", "quantize_colors", 8, 256],
  ["setBgTol", "bg_tol", 0, 150],
  ["setLoopWidth", "loop_width", 2, 10],
  ["setLoopLength", "loop_length", 4, 15],
  ["setLoopHole", "loop_hole", 1, 5],
  ["setOutlineWidth", "outline_width", 0.5, 10.0],
  ["setWireWidthMm", "wire_width_mm", 0.2, 1.2],
  ["setWireHeightMm", "wire_height_mm", 0.04, 1.0],
  ["setCoatingHeightMm", "coating_height_mm", 0.04, 0.12],
  ["setHeightmapMaxHeight", "heightmap_max_height", 0.08, 15.0],
] as const;

/** Fields that do NOT trigger aspect-ratio linking (exclude width/height) */
const ISOLATED_NUMERIC_FIELDS = NUMERIC_FIELDS.filter(
  ([, key]) => key !== "target_width_mm" && key !== "target_height_mm"
);

/** Reset store to default state before each test */
function resetStore(): void {
  useConverterStore.setState({
    imageFile: null,
    imagePreviewUrl: null,
    aspectRatio: null,
    lut_name: "",
    target_width_mm: 60,
    target_height_mm: 60,
    spacer_thick: 1.2,
    structure_mode: "Double-sided" as never,
    color_mode: "4-Color" as never,
    modeling_mode: "high-fidelity" as never,
    auto_bg: false,
    bg_tol: 40,
    quantize_colors: 48,
    enable_cleanup: true,
    separate_backing: false,
    add_loop: false,
    loop_width: 4.0,
    loop_length: 8.0,
    loop_hole: 2.5,
    enable_relief: false,
    color_height_map: {},
    heightmap_max_height: 5.0,
    enable_outline: false,
    outline_width: 2.0,
    enable_cloisonne: false,
    wire_width_mm: 0.4,
    wire_height_mm: 0.4,
    enable_coating: false,
    coating_height_mm: 0.08,
    replacement_regions: [],
    free_color_set: new Set(),
    isLoading: false,
    error: null,
    previewImageUrl: null,
    lutList: [],
    lutListLoading: false,
  });
}

// ========== Tests ==========

describe("ConverterStore Property-Based Tests", () => {
  beforeEach(() => {
    resetStore();
  });

  // **Validates: Requirements 1.3**
  describe("Property 1: 字段隔离性 (Field Isolation)", () => {
    it("setting a numeric field does not affect other numeric fields", () => {
      fc.assert(
        fc.property(
          fc.integer({ min: 0, max: ISOLATED_NUMERIC_FIELDS.length - 1 }),
          fc.double({ min: -1e6, max: 1e6, noNaN: true }),
          (fieldIndex, rawValue) => {
            resetStore();
            const [setterName, targetKey] = ISOLATED_NUMERIC_FIELDS[fieldIndex];

            // Snapshot all numeric field values before the call
            const before: Record<string, number> = {};
            for (const [, key] of NUMERIC_FIELDS) {
              before[key] = useConverterStore.getState()[key] as number;
            }

            // Call the setter
            const store = useConverterStore.getState();
            (store[setterName] as (v: number) => void)(rawValue);

            // Verify other fields unchanged
            const after = useConverterStore.getState();
            for (const [, key] of NUMERIC_FIELDS) {
              if (key !== targetKey) {
                if (after[key] !== before[key]) return false;
              }
            }
            return true;
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // **Validates: Requirements 2.1, 2.2**
  describe("Property 2: 浮雕与掐丝珐琅互斥不变量 (Relief-Cloisonné Mutual Exclusion)", () => {
    it("enable_relief and enable_cloisonne are never both true", () => {
      fc.assert(
        fc.property(
          fc.array(
            fc.record({
              target: fc.constantFrom("relief", "cloisonne"),
              value: fc.boolean(),
            }),
            { minLength: 1, maxLength: 20 }
          ),
          (operations) => {
            resetStore();
            const store = useConverterStore.getState();

            for (const op of operations) {
              if (op.target === "relief") {
                store.setEnableRelief(op.value);
              } else {
                store.setEnableCloisonne(op.value);
              }

              const state = useConverterStore.getState();
              // Invariant: never both true
              if (state.enable_relief && state.enable_cloisonne) return false;
            }
            return true;
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // **Validates: Requirements 3.1–3.12**
  describe("Property 3: 数值字段范围约束 (Numeric Field Clamping)", () => {
    it("all numeric fields are always within [min, max] after setting any value", () => {
      fc.assert(
        fc.property(
          fc.integer({ min: 0, max: NUMERIC_FIELDS.length - 1 }),
          fc.oneof(
            fc.double({ min: -1e9, max: 1e9, noNaN: true }),
            fc.constant(-Infinity),
            fc.constant(Infinity),
            fc.constant(0)
          ),
          (fieldIndex, rawValue) => {
            resetStore();
            // Ensure no aspect ratio linking for width/height tests
            useConverterStore.setState({ aspectRatio: null });

            const [setterName, stateKey, min, max] = NUMERIC_FIELDS[fieldIndex];
            const store = useConverterStore.getState();
            (store[setterName] as (v: number) => void)(rawValue);

            const stored = useConverterStore.getState()[stateKey] as number;
            return stored >= min && stored <= max;
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // **Validates: Requirements 4.1, 4.2**
  describe("Property 4: 宽高比联动一致性 (Aspect Ratio Linked Update)", () => {
    it("setTargetWidthMm updates height = clamp(round(width / aspectRatio), 10, 400)", () => {
      fc.assert(
        fc.property(
          fc.double({ min: 0.1, max: 10.0, noNaN: true }),
          fc.double({ min: -500, max: 1000, noNaN: true }),
          (aspectRatio, width) => {
            resetStore();
            useConverterStore.setState({ aspectRatio });

            useConverterStore.getState().setTargetWidthMm(width);

            const state = useConverterStore.getState();
            const clampedWidth = clampValue(width, 10, 400);
            const expectedHeight = clampValue(
              Math.round(clampedWidth / aspectRatio),
              10,
              400
            );

            return (
              state.target_width_mm === clampedWidth &&
              state.target_height_mm === expectedHeight
            );
          }
        ),
        { numRuns: 100 }
      );
    });

    it("setTargetHeightMm updates width = clamp(round(height * aspectRatio), 10, 400)", () => {
      fc.assert(
        fc.property(
          fc.double({ min: 0.1, max: 10.0, noNaN: true }),
          fc.double({ min: -500, max: 1000, noNaN: true }),
          (aspectRatio, height) => {
            resetStore();
            useConverterStore.setState({ aspectRatio });

            useConverterStore.getState().setTargetHeightMm(height);

            const state = useConverterStore.getState();
            const clampedHeight = clampValue(height, 10, 400);
            const expectedWidth = clampValue(
              Math.round(clampedHeight * aspectRatio),
              10,
              400
            );

            return (
              state.target_height_mm === clampedHeight &&
              state.target_width_mm === expectedWidth
            );
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // **Validates: Requirements 4.3**
  describe("Property 5: 无宽高比时尺寸独立 (Independent Dimensions Without Aspect Ratio)", () => {
    it("setting width does not change height when aspectRatio is null", () => {
      fc.assert(
        fc.property(
          fc.double({ min: -500, max: 1000, noNaN: true }),
          (width) => {
            resetStore();
            useConverterStore.setState({ aspectRatio: null });

            const heightBefore = useConverterStore.getState().target_height_mm;
            useConverterStore.getState().setTargetWidthMm(width);
            const heightAfter = useConverterStore.getState().target_height_mm;

            return heightBefore === heightAfter;
          }
        ),
        { numRuns: 100 }
      );
    });

    it("setting height does not change width when aspectRatio is null", () => {
      fc.assert(
        fc.property(
          fc.double({ min: -500, max: 1000, noNaN: true }),
          (height) => {
            resetStore();
            useConverterStore.setState({ aspectRatio: null });

            const widthBefore = useConverterStore.getState().target_width_mm;
            useConverterStore.getState().setTargetHeightMm(height);
            const widthAfter = useConverterStore.getState().target_width_mm;

            return widthBefore === widthAfter;
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // **Validates: Requirements 5.3**
  describe("Property 6: 文件类型验证 (File Type Validation)", () => {
    it("isValidImageType returns true only for jpeg, png, svg+xml", () => {
      const validTypes = ["image/jpeg", "image/png", "image/svg+xml"];

      fc.assert(
        fc.property(fc.string({ minLength: 0, maxLength: 50 }), (mimeType) => {
          const result = isValidImageType(mimeType);
          if (validTypes.includes(mimeType)) {
            return result === true;
          }
          return result === false;
        }),
        { numRuns: 100 }
      );
    });

    it("always returns true for the three valid types", () => {
      fc.assert(
        fc.property(
          fc.constantFrom("image/jpeg", "image/png", "image/svg+xml"),
          (validType) => {
            return isValidImageType(validType) === true;
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  // **Validates: Requirements 11.5**
  describe("Property 7: 新请求清除错误状态 (Error Clearing on New Request)", () => {
    it("clearError always sets error to null regardless of previous error", () => {
      fc.assert(
        fc.property(
          fc.string({ minLength: 1, maxLength: 200 }),
          (errorMsg) => {
            resetStore();
            useConverterStore.getState().setError(errorMsg);

            // Verify error was set
            if (useConverterStore.getState().error !== errorMsg) return false;

            // Clear error
            useConverterStore.getState().clearError();

            return useConverterStore.getState().error === null;
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
