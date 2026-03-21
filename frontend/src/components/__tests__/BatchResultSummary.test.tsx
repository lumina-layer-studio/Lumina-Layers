import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import BatchResultSummary from "../ui/BatchResultSummary";
import type { BatchResponse } from "../../api/types";

// ========== Fixtures ==========

const allSuccessResult: BatchResponse = {
  status: "ok",
  message: "batch done",
  download_url: "/output/batch_123.zip",
  results: [
    { filename: "photo1.png", status: "success" },
    { filename: "photo2.jpg", status: "success" },
    { filename: "photo3.svg", status: "success" },
  ],
};

const allFailedResult: BatchResponse = {
  status: "failed",
  message: "all failed",
  download_url: "/output/batch_456.zip",
  results: [
    { filename: "bad1.png", status: "failed", error: "LUT not found" },
    { filename: "bad2.jpg", status: "failed", error: "Invalid dimensions" },
  ],
};

const mixedResult: BatchResponse = {
  status: "ok",
  message: "partial success",
  download_url: "/output/batch_789.zip",
  results: [
    { filename: "good1.png", status: "success" },
    { filename: "good2.jpg", status: "success" },
    { filename: "fail1.svg", status: "failed", error: "Unsupported format" },
  ],
};

// ========== Tests ==========

describe("BatchResultSummary", () => {
  describe("all success", () => {
    it("shows correct success count and total", () => {
      const { container } = render(
        <BatchResultSummary result={allSuccessResult} />,
      );
      const text = container.textContent ?? "";
      // "成功 3 / 总计 3"
      expect(text).toContain("3");
      expect(text).toMatch(/成功.*3.*总计.*3/);
    });

    it("renders download button with correct href", () => {
      render(<BatchResultSummary result={allSuccessResult} />);
      const link = screen.getByRole("link", { name: "下载 ZIP 文件" });
      expect(link).toBeInTheDocument();
      expect(link).toHaveAttribute(
        "href",
        "http://localhost:8000/output/batch_123.zip",
      );
    });

    it("does not show failed section", () => {
      render(<BatchResultSummary result={allSuccessResult} />);
      expect(screen.queryByText("失败文件：")).not.toBeInTheDocument();
    });

    it("does not show failed count in summary", () => {
      const { container } = render(
        <BatchResultSummary result={allSuccessResult} />,
      );
      const text = container.textContent ?? "";
      expect(text).not.toContain("失败");
    });
  });

  describe("all failed", () => {
    it("shows correct counts with zero success", () => {
      const { container } = render(
        <BatchResultSummary result={allFailedResult} />,
      );
      const text = container.textContent ?? "";
      expect(text).toMatch(/成功.*0.*总计.*2/);
      expect(text).toMatch(/失败.*2/);
    });

    it("does not render download button", () => {
      render(<BatchResultSummary result={allFailedResult} />);
      expect(
        screen.queryByRole("link", { name: "下载 ZIP 文件" }),
      ).not.toBeInTheDocument();
    });

    it("shows failed section header", () => {
      render(<BatchResultSummary result={allFailedResult} />);
      expect(screen.getByText("失败文件：")).toBeInTheDocument();
    });

    it("shows each failed filename and error", () => {
      render(<BatchResultSummary result={allFailedResult} />);
      expect(screen.getByText("bad1.png")).toBeInTheDocument();
      expect(screen.getByText(/LUT not found/)).toBeInTheDocument();
      expect(screen.getByText("bad2.jpg")).toBeInTheDocument();
      expect(screen.getByText(/Invalid dimensions/)).toBeInTheDocument();
    });
  });

  describe("mixed results", () => {
    it("shows correct success, failed, and total counts", () => {
      const { container } = render(
        <BatchResultSummary result={mixedResult} />,
      );
      const text = container.textContent ?? "";
      expect(text).toMatch(/成功.*2.*总计.*3/);
      expect(text).toMatch(/失败.*1/);
    });

    it("renders download button", () => {
      render(<BatchResultSummary result={mixedResult} />);
      const link = screen.getByRole("link", { name: "下载 ZIP 文件" });
      expect(link).toBeInTheDocument();
      expect(link).toHaveAttribute(
        "href",
        "http://localhost:8000/output/batch_789.zip",
      );
    });

    it("shows failed items with details", () => {
      render(<BatchResultSummary result={mixedResult} />);
      expect(screen.getByText("失败文件：")).toBeInTheDocument();
      expect(screen.getByText("fail1.svg")).toBeInTheDocument();
      expect(screen.getByText(/Unsupported format/)).toBeInTheDocument();
    });

    it("does not show successful filenames in failed list", () => {
      render(<BatchResultSummary result={mixedResult} />);
      const failedList = screen.getByRole("list", { name: "失败文件列表" });
      expect(failedList.textContent).not.toContain("good1.png");
      expect(failedList.textContent).not.toContain("good2.jpg");
    });
  });
});
