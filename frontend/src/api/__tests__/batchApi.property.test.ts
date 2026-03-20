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
  spacer_thick: fc.double({ min: 0.1, max: 2.0, noNaN: true, noDefaultInfinity: true }),
  structure_mode: fc.constantFrom("Double-sided", "Single-sided"),
  auto_bg: fc.boolean(),
  bg_tol: fc.integer({ min: 0, max: 100 }),
  color_mode: fc.constantFrom("4-Color", "6-Color (Smart 1296)", "8-Color Max", "BW (Black & White)"),
  modeling_mode: fc.constantFrom("high-fidelity", "pixel", "vector"),
  quantize_colors: fc.integer({ min: 2, max: 256 }),
  enable_cleanup: fc.boolean(),
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
          const formValue = fd.get(key);
          expect(formValue).toBe(String(value));
        }

        // Verify the endpoint
        expect(capturedUrl).toBe("/convert/batch");
      }),
      { numRuns: 100 },
    );
  });
});
