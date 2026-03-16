import { describe, it, expect, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useConverterStore } from "../converterStore";
import type { BatchResponse, BatchItemResult } from "../../api/types";

// ========== Arbitraries ==========

const VALID_MIME_TYPES = ["image/jpeg", "image/png", "image/svg+xml"] as const;

const INVALID_MIME_TYPES = [
  "text/plain",
  "application/pdf",
  "image/gif",
  "image/webp",
  "image/bmp",
  "video/mp4",
  "application/json",
  "audio/mpeg",
];

/** Arbitrary: a File with a valid image MIME type */
const arbValidFile: fc.Arbitrary<File> = fc
  .tuple(
    fc.string({ minLength: 1, maxLength: 20 }),
    fc.constantFrom(...VALID_MIME_TYPES),
  )
  .map(([name, type]) => new File(["data"], `${name}.img`, { type }));

/** Arbitrary: a File with an invalid MIME type */
const arbInvalidFile: fc.Arbitrary<File> = fc
  .tuple(
    fc.string({ minLength: 1, maxLength: 20 }),
    fc.constantFrom(...INVALID_MIME_TYPES),
  )
  .map(([name, type]) => new File(["data"], `${name}.bad`, { type }));

/** Arbitrary: a non-empty list of valid files */
const arbValidFileList: fc.Arbitrary<File[]> = fc.array(arbValidFile, {
  minLength: 1,
  maxLength: 10,
});

/** Arbitrary: a BatchItemResult */
const arbBatchItemResult: fc.Arbitrary<BatchItemResult> = fc.record({
  filename: fc.string({ minLength: 1, maxLength: 30 }),
  status: fc.constantFrom("success", "failed"),
  error: fc.option(fc.string({ minLength: 1, maxLength: 50 }), { nil: undefined }),
});

/** Arbitrary: a BatchResponse */
const arbBatchResponse: fc.Arbitrary<BatchResponse> = fc.record({
  status: fc.constantFrom("ok", "failed"),
  message: fc.string({ minLength: 0, maxLength: 50 }),
  download_url: fc.string({ minLength: 1, maxLength: 50 }),
  results: fc.array(arbBatchItemResult, { minLength: 0, maxLength: 10 }),
});

// ========== Helpers ==========

function resetStore(): void {
  useConverterStore.setState({
    batchMode: false,
    batchFiles: [],
    batchLoading: false,
    batchResult: null,
  });
}

// ========== Property 1 ==========

/**
 * Feature: batch-processing-mode, Property 1: 禁用批量模式清空所有批量状态
 * **Validates: Requirements 1.3, 8.3**
 *
 * For any Converter_Store state where batchMode is true, batchFiles contains
 * any number of files, and batchResult contains any BatchResponse, calling
 * setBatchMode(false) should set batchMode to false, batchFiles to empty
 * array, and batchResult to null.
 */
describe("Feature: batch-processing-mode, Property 1: 禁用批量模式清空所有批量状态", () => {
  beforeEach(() => {
    resetStore();
  });

  it("setBatchMode(false) clears batchMode, batchFiles, and batchResult", () => {
    fc.assert(
      fc.property(arbValidFileList, arbBatchResponse, (files, result) => {
        // Set up state with batchMode enabled, files, and result
        useConverterStore.setState({
          batchMode: true,
          batchFiles: files,
          batchResult: result,
        });

        // Disable batch mode
        useConverterStore.getState().setBatchMode(false);

        const state = useConverterStore.getState();
        expect(state.batchMode).toBe(false);
        expect(state.batchFiles).toEqual([]);
        expect(state.batchResult).toBeNull();
      }),
      { numRuns: 100 },
    );
  });
});

// ========== Property 2 ==========

/**
 * Feature: batch-processing-mode, Property 2: 文件类型过滤
 * **Validates: Requirements 3.1, 3.5**
 *
 * For any file, when its MIME type is in {image/jpeg, image/png, image/svg+xml},
 * addBatchFiles should add it to batchFiles; when its MIME type is not in that
 * set, addBatchFiles should ignore it and batchFiles length stays unchanged.
 */
describe("Feature: batch-processing-mode, Property 2: 文件类型过滤", () => {
  beforeEach(() => {
    resetStore();
  });

  it("valid MIME type files are added to batchFiles", () => {
    fc.assert(
      fc.property(arbValidFile, (file) => {
        resetStore();

        useConverterStore.getState().addBatchFiles([file]);

        const state = useConverterStore.getState();
        expect(state.batchFiles).toHaveLength(1);
        expect(state.batchFiles[0]).toBe(file);
      }),
      { numRuns: 100 },
    );
  });

  it("invalid MIME type files are ignored by addBatchFiles", () => {
    fc.assert(
      fc.property(arbInvalidFile, (file) => {
        resetStore();

        const lengthBefore = useConverterStore.getState().batchFiles.length;
        useConverterStore.getState().addBatchFiles([file]);

        const state = useConverterStore.getState();
        expect(state.batchFiles).toHaveLength(lengthBefore);
      }),
      { numRuns: 100 },
    );
  });

  it("mixed valid and invalid files: only valid files are added", () => {
    fc.assert(
      fc.property(
        fc.array(arbValidFile, { minLength: 0, maxLength: 5 }),
        fc.array(arbInvalidFile, { minLength: 0, maxLength: 5 }),
        (validFiles, invalidFiles) => {
          resetStore();

          // Shuffle valid and invalid together
          const mixed = [...validFiles, ...invalidFiles];
          useConverterStore.getState().addBatchFiles(mixed);

          const state = useConverterStore.getState();
          expect(state.batchFiles).toHaveLength(validFiles.length);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ========== Property 3 ==========

/**
 * Feature: batch-processing-mode, Property 3: 批量文件追加不丢失已有文件
 * **Validates: Requirements 3.2**
 *
 * For any initial batchFiles list and any new valid file list, after calling
 * addBatchFiles, the result list should contain all original files plus all
 * new valid files, with original files first and new files appended.
 */
describe("Feature: batch-processing-mode, Property 3: 批量文件追加不丢失已有文件", () => {
  beforeEach(() => {
    resetStore();
  });

  it("addBatchFiles appends new valid files after existing files", () => {
    fc.assert(
      fc.property(arbValidFileList, arbValidFileList, (initialFiles, newFiles) => {
        // Set initial files directly
        useConverterStore.setState({ batchFiles: [...initialFiles] });

        // Add new files
        useConverterStore.getState().addBatchFiles(newFiles);

        const state = useConverterStore.getState();
        const expected = [...initialFiles, ...newFiles];

        expect(state.batchFiles).toHaveLength(expected.length);

        // Verify order: initial files first, then new files
        for (let i = 0; i < initialFiles.length; i++) {
          expect(state.batchFiles[i]).toBe(initialFiles[i]);
        }
        for (let i = 0; i < newFiles.length; i++) {
          expect(state.batchFiles[initialFiles.length + i]).toBe(newFiles[i]);
        }
      }),
      { numRuns: 100 },
    );
  });
});

// ========== Property 4 ==========

/**
 * Feature: batch-processing-mode, Property 4: 按索引移除文件的正确性
 * **Validates: Requirements 3.4**
 *
 * For any non-empty batchFiles list and any valid index i (0 ≤ i < length),
 * after calling removeBatchFile(i), the result list length should decrease
 * by 1, and the file originally at index i should no longer appear at that
 * position.
 */
describe("Feature: batch-processing-mode, Property 4: 按索引移除文件的正确性", () => {
  beforeEach(() => {
    resetStore();
  });

  it("removeBatchFile(i) reduces length by 1 and removes the file at index i", () => {
    fc.assert(
      fc.property(
        arbValidFileList.chain((files) =>
          fc.tuple(
            fc.constant(files),
            fc.integer({ min: 0, max: files.length - 1 }),
          ),
        ),
        ([files, index]) => {
          // Set files on store
          useConverterStore.setState({ batchFiles: [...files] });

          const originalLength = files.length;
          const removedFile = files[index];

          // Remove file at index
          useConverterStore.getState().removeBatchFile(index);

          const state = useConverterStore.getState();

          // Length decreased by 1
          expect(state.batchFiles).toHaveLength(originalLength - 1);

          // The file at the original index position is no longer there
          // (either the position doesn't exist or has a different file)
          if (index < state.batchFiles.length) {
            expect(state.batchFiles[index]).not.toBe(removedFile);
          }

          // Verify the remaining files are in correct order
          const expectedRemaining = [
            ...files.slice(0, index),
            ...files.slice(index + 1),
          ];
          expect(state.batchFiles).toHaveLength(expectedRemaining.length);
          for (let i = 0; i < expectedRemaining.length; i++) {
            expect(state.batchFiles[i]).toBe(expectedRemaining[i]);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
