import { describe, it, expect, afterEach } from "vitest";
import * as fc from "fast-check";
import { render, screen, cleanup } from "@testing-library/react";
import BatchResultSummary from "../ui/BatchResultSummary";
import type { BatchResponse, BatchItemResult } from "../../api/types";

// ========== Arbitraries ==========

/** Arbitrary: a successful BatchItemResult */
const arbSuccessItem: fc.Arbitrary<BatchItemResult> = fc.record({
  filename: fc.string({ minLength: 1, maxLength: 30 }),
  status: fc.constant("success"),
  error: fc.constant(undefined),
});

/** Arbitrary: a failed BatchItemResult with non-empty error */
const arbFailedItem: fc.Arbitrary<BatchItemResult> = fc.record({
  filename: fc.string({ minLength: 1, maxLength: 30 }),
  status: fc.constant("failed"),
  error: fc.string({ minLength: 1, maxLength: 50 }),
});

/** Arbitrary: a BatchResponse with a mix of success and failed results */
const arbMixedBatchResponse: fc.Arbitrary<BatchResponse> = fc
  .tuple(
    fc.array(arbSuccessItem, { minLength: 0, maxLength: 8 }),
    fc.array(arbFailedItem, { minLength: 0, maxLength: 8 }),
  )
  .filter(([s, f]) => s.length + f.length > 0)
  .map(([successItems, failedItems]) => ({
    status: failedItems.length === 0 ? "ok" : "failed",
    message: "batch done",
    download_url: "/output/batch.zip",
    results: [...successItems, ...failedItems],
  }));

/** Arbitrary: a BatchResponse with at least one success */
const arbWithSuccess: fc.Arbitrary<BatchResponse> = fc
  .tuple(
    fc.array(arbSuccessItem, { minLength: 1, maxLength: 8 }),
    fc.array(arbFailedItem, { minLength: 0, maxLength: 5 }),
    fc.string({ minLength: 1, maxLength: 40 }),
  )
  .map(([successItems, failedItems, dlUrl]) => ({
    status: "ok",
    message: "done",
    download_url: `/output/${dlUrl}.zip`,
    results: [...successItems, ...failedItems],
  }));

/** Arbitrary: a BatchResponse with ALL failed (zero success) */
const arbAllFailed: fc.Arbitrary<BatchResponse> = fc
  .array(arbFailedItem, { minLength: 1, maxLength: 10 })
  .map((failedItems) => ({
    status: "failed",
    message: "all failed",
    download_url: "/output/batch.zip",
    results: failedItems,
  }));

// ========== Helpers ==========

afterEach(() => {
  cleanup();
});

// ========== Property 5 ==========

/**
 * Feature: batch-processing-mode, Property 5: 批量结果摘要正确统计成功和失败数
 * **Validates: Requirements 6.1, 6.3**
 *
 * For any BatchResponse with any number of success and failed results,
 * after rendering BatchResultSummary, the displayed success count should
 * equal the number of items with status === "success", the failed count
 * should equal the number with status === "failed", and each failed item's
 * filename and error should appear in the rendered output.
 */
describe("Feature: batch-processing-mode, Property 5: 批量结果摘要正确统计成功和失败数", () => {
  it("displays correct success count, failed count, and failed item details", () => {
    fc.assert(
      fc.property(arbMixedBatchResponse, (batchResponse) => {
        cleanup();

        const successCount = batchResponse.results.filter(
          (r) => r.status === "success",
        ).length;
        const failedCount = batchResponse.results.filter(
          (r) => r.status === "failed",
        ).length;
        const total = batchResponse.results.length;

        const { container } = render(
          <BatchResultSummary result={batchResponse} />,
        );
        const text = container.textContent ?? "";

        // Verify success count and total are displayed
        expect(text).toContain(String(successCount));
        expect(text).toContain(String(total));

        // Verify failed count is displayed when > 0
        if (failedCount > 0) {
          expect(text).toContain(String(failedCount));
        }

        // Verify each failed item's filename and error appear
        const failedItems = batchResponse.results.filter(
          (r) => r.status === "failed",
        );
        for (const item of failedItems) {
          expect(text).toContain(item.filename);
          if (item.error) {
            expect(text).toContain(item.error);
          }
        }
      }),
      { numRuns: 100 },
    );
  });
});

// ========== Property 6 ==========

/**
 * Feature: batch-processing-mode, Property 6: 存在成功文件时显示下载按钮
 * **Validates: Requirements 6.2**
 *
 * For any BatchResponse, when results contain at least one item with
 * status === "success", BatchResultSummary should render a download button
 * whose href contains the download_url; when all items have status === "failed",
 * no download button should be rendered.
 */
describe("Feature: batch-processing-mode, Property 6: 存在成功文件时显示下载按钮", () => {
  it("renders download button with correct href when at least one success exists", () => {
    fc.assert(
      fc.property(arbWithSuccess, (batchResponse) => {
        cleanup();

        render(<BatchResultSummary result={batchResponse} />);

        const downloadLink = screen.getByRole("link", {
          name: "下载 ZIP 文件",
        });
        expect(downloadLink).toBeInTheDocument();
        expect(downloadLink).toHaveAttribute(
          "href",
          `http://localhost:8000${batchResponse.download_url}`,
        );
      }),
      { numRuns: 100 },
    );
  });

  it("does not render download button when all results are failed", () => {
    fc.assert(
      fc.property(arbAllFailed, (batchResponse) => {
        cleanup();

        render(<BatchResultSummary result={batchResponse} />);

        const downloadLink = screen.queryByRole("link", {
          name: "下载 ZIP 文件",
        });
        expect(downloadLink).not.toBeInTheDocument();
      }),
      { numRuns: 100 },
    );
  });
});
