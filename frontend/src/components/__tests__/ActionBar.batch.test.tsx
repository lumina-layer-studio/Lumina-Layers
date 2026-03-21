import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { useConverterStore } from "../../stores/converterStore";
import ActionBar from "../sections/ActionBar";

// Mock child components with complex dependencies
vi.mock("../sections/BedSizeSelector", () => ({
  default: () => <div data-testid="bed-size-selector" />,
}));

vi.mock("../sections/SlicerSelector", () => ({
  default: () => <div data-testid="slicer-selector" />,
}));

function makeFile(name: string, type = "image/png"): File {
  return new File(["dummy"], name, { type });
}

describe("ActionBar — batch mode", () => {
  beforeEach(() => {
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      batchLoading: false,
      batchResult: null,
      imageFile: null,
      lut_name: "",
      isLoading: false,
      error: null,
      previewImageUrl: null,
      modelUrl: null,
    });
  });

  // --- Non-batch mode ---

  it("shows preview and generate buttons when batchMode is false", () => {
    useConverterStore.setState({ batchMode: false });
    render(<ActionBar />);
    expect(screen.getByText("预览")).toBeInTheDocument();
    expect(screen.getByText("生成")).toBeInTheDocument();
    expect(screen.queryByText("批量生成")).not.toBeInTheDocument();
  });

  // --- Batch mode visibility ---

  it("shows batch generate button and hides preview/generate when batchMode is true", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
    });
    render(<ActionBar />);
    expect(screen.getByText("批量生成")).toBeInTheDocument();
    expect(screen.queryByText("预览")).not.toBeInTheDocument();
    expect(screen.queryByText("生成")).not.toBeInTheDocument();
  });

  // --- Disabled conditions ---

  it("disables batch generate button when batchFiles is empty", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [],
      lut_name: "test_lut",
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).toBeDisabled();
  });

  it("disables batch generate button when lut_name is empty", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "",
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).toBeDisabled();
  });

  it("disables batch generate button when batchLoading is true", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchLoading: true,
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).toBeDisabled();
  });

  // --- Enabled condition ---

  it("enables batch generate button when files exist and lut_name is set", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchLoading: false,
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).not.toBeDisabled();
  });

  // --- BatchResultSummary ---

  it("shows BatchResultSummary when batchResult is not null", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchResult: {
        status: "ok",
        message: "done",
        download_url: "/output/batch.zip",
        results: [{ filename: "a.png", status: "success" }],
      },
    });
    const { container } = render(<ActionBar />);
    // BatchResultSummary renders — text is split across child elements
    const text = container.textContent ?? "";
    expect(text).toContain("成功");
    expect(text).toContain("总计");
    expect(screen.getByLabelText("下载 ZIP 文件")).toBeInTheDocument();
  });

  it("does not show BatchResultSummary when batchResult is null", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchResult: null,
    });
    render(<ActionBar />);
    expect(screen.queryByText(/成功.*总计/)).not.toBeInTheDocument();
  });
});
