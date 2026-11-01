import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fc from "fast-check";
import type { BatchConvertParams } from "../types";

// ========== Mock apiClient ==========

let capturedFormData: FormData | null = null;
let capturedUrl: string | null = null;

vi.mock("../client", () => ({
  default: {
    post: vi.fn(async (url: string, data: unknown) => {
      capturedUrl = url;
      capturedFormData = data as FormData;
      return {
        data: {
          status: "ok",
          message: "mock",
          download_url: "/mock.zip",
          results: [],
        },
      };
    }),
  },
}));

import { convertBatch } from "../converter";

// ========== Generators ==========

const arbFile = fc
  .string({ minLength: 1, maxLength: 20 })
  .map((name) => new File(["data"], `${name}.png`, { type: "image/png" }));

const arbFileList = fc.array(arbFile, { minLength: 1, maxLength: 10 });

const arbBatchConvertParams: fc.Arbitrary<BatchConvertParams> = fc.record({
  lut_name: fc.string({ minLength: 1, maxLength: 30 }),
  target_width_mm: fc.double({ min: 10, max: 300, noNaN: true, noDefaultInfinity: true }),
  spacer_thick: fc.double({ min: 0.2, max: 10, noNaN: true, noDefaultInfinity: true }),
  backing_infill_density_percent: fc.integer({ min: 5, max: 100 }),
  structure_mode: fc.constantFrom("Double-sided", "Single-sided"),
  color_mode: fc.constantFrom("4-Color (CMYW)", "4-Color (RYBW)", "6-Color (CMYWGK 1296)", "6-Color (RYBWGK 1296)", "8-Color Max", "BW (Black & White)"),
  modeling_mode: fc.constantFrom("high-fidelity", "pixel", "vector"),
  color_layers: fc.integer({ min: 1, max: 20 }),
  layer_height_mm: fc.double({ min: 0.04, max: 0.3, noNaN: true, noDefaultInfinity: true }),
  quantize_colors: fc.integer({ min: 2, max: 256 }),
  enable_cleanup: fc.boolean(),
  separate_backing: fc.boolean(),
  enable_coating: fc.boolean(),
  coating_height_mm: fc.constantFrom(0.04, 0.08, 0.12),
  enable_outline: fc.boolean(),
  outline_width: fc.double({ min: 0.5, max: 10, noNaN: true, noDefaultInfinity: true }),
  hue_weight: fc.double({ min: 0, max: 2 }),
  chroma_gate: fc.integer({ min: 0, max: 50 }),
  enable_relief: fc.boolean(),
  height_mode: fc.constantFrom("color", undefined),
  color_height_map: fc.option(
    fc.dictionary(
      fc.constantFrom("#ff0000", "#00ff00", "#0000ff", "#ffffff"),
      fc.double({ min: 0.08, max: 20, noNaN: true, noDefaultInfinity: true }),
    ),
    { nil: undefined },
  ),
  heightmap_max_height: fc.option(
    fc.double({ min: 0.08, max: 20, noNaN: true, noDefaultInfinity: true }),
    { nil: undefined },
  ),
  printer_id: fc.constantFrom("bambu-h2d", "bambu-p1s", "snapmaker-u1"),
  slicer: fc.constantFrom("BambuStudio", "OrcaSlicer"),
  nozzle_size: fc.constantFrom("0.2", "0.4"),
  enable_base_layer_height_modifier: fc.boolean(),
});

// ========== Tests ==========

beforeEach(() => {
  capturedFormData = null;
  capturedUrl = null;
  vi.clearAllMocks();
});

// **Feature: batch-processing-mode, Property 7: FormData 构建完整性**
// **Validates: Requirements 7.2**
describe("Feature: batch-processing-mode, Property 7: FormData 构建完整性", () => {
  it("For any file list (1-10) and BatchConvertParams, convertBatch FormData contains matching images entries and all param fields", async () => {
    await fc.assert(
      fc.asyncProperty(arbFileList, arbBatchConvertParams, async (files, params) => {
        capturedFormData = null;

        await convertBatch(files, params);

        expect(capturedFormData).not.toBeNull();
        const fd = capturedFormData!;

        // Verify images entries count matches file count
        const imageEntries = fd.getAll("images");
        expect(imageEntries).toHaveLength(files.length);

        // Verify each param key exists as a form field with stringified value
        for (const [key, value] of Object.entries(params)) {
          if (value === null || value === undefined) {
            expect(fd.has(key)).toBe(false);
            continue;
          }
          const formValue = fd.get(key);
          expect(formValue).toBe(
            typeof value === "object" ? JSON.stringify(value) : String(value),
          );
        }

        // Verify the endpoint
        expect(capturedUrl).toBe("/convert/batch");
      }),
      { numRuns: 100 },
    );
  });
});
