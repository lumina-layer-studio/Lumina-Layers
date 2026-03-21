import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import LutManagerPanel from "../components/LutManagerPanel";
import { useLutManagerStore } from "../stores/lutManagerStore";

vi.mock("../api/lut", () => ({
  fetchLutInfo: vi.fn(),
  mergeLuts: vi.fn(),
}));

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn().mockResolvedValue({ luts: [] }),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
}));

beforeEach(() => {
  useLutManagerStore.setState({
    lutList: [
      { name: "Test LUT", color_mode: "8-Color Max" as any, path: "/fake/path.npy" },
    ],
    lutListLoading: false,
    primaryName: "",
    primaryInfo: null,
    primaryLoading: false,
    secondaryNames: [],
    secondaryInfos: new Map(),
    filteredSecondaryOptions: [],
    dedupThreshold: 3.0,
    merging: false,
    mergeResult: null,
    error: null,
  });
});

describe("LutManagerPanel", () => {
  it("renders all controls", () => {
    render(<LutManagerPanel />);

    expect(screen.getByTestId("lut-manager-panel")).toBeInTheDocument();
    expect(screen.getByText("LUT Merge Tool")).toBeInTheDocument();
    expect(screen.getByText("Primary LUT")).toBeInTheDocument();
    expect(screen.getByTestId("primary-dropdown")).toBeInTheDocument();
    expect(screen.getByTestId("secondary-list")).toBeInTheDocument();
    expect(screen.getByText("Secondary LUTs")).toBeInTheDocument();
    expect(screen.getByText("Dedup Threshold")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Merge & Save" })).toBeInTheDocument();
  });

  it("shows loading indicator when primaryLoading is true", () => {
    useLutManagerStore.setState({ primaryLoading: true });
    render(<LutManagerPanel />);

    expect(screen.getByTestId("loading-indicator")).toBeInTheDocument();
    expect(screen.getByTestId("loading-indicator")).toHaveTextContent("加载中");
  });

  it("does not show loading indicator when primaryLoading is false", () => {
    render(<LutManagerPanel />);

    expect(screen.queryByTestId("loading-indicator")).not.toBeInTheDocument();
  });

  it("shows error message when error is set", () => {
    useLutManagerStore.setState({ error: "合并失败：文件不存在" });
    render(<LutManagerPanel />);

    const errorEl = screen.getByTestId("error-message");
    expect(errorEl).toBeInTheDocument();
    expect(errorEl).toHaveTextContent("合并失败：文件不存在");
  });

  it("does not show error message when error is null", () => {
    render(<LutManagerPanel />);

    expect(screen.queryByTestId("error-message")).not.toBeInTheDocument();
  });

  it("shows merge result when mergeResult is set", () => {
    useLutManagerStore.setState({
      mergeResult: {
        status: "success",
        message: "合并成功",
        filename: "Merged_8-Color+4-Color_20250101_120000.npz",
        stats: {
          total_before: 3762,
          total_after: 3450,
          exact_dupes: 200,
          similar_removed: 112,
        },
      },
    });
    render(<LutManagerPanel />);

    const resultEl = screen.getByTestId("merge-result");
    expect(resultEl).toBeInTheDocument();
    expect(resultEl).toHaveTextContent("3762");
    expect(resultEl).toHaveTextContent("3450");
    expect(resultEl).toHaveTextContent("200");
    expect(resultEl).toHaveTextContent("112");
    expect(resultEl).toHaveTextContent("Merged_8-Color+4-Color_20250101_120000.npz");
  });

  it("disables merge button when primaryName is empty", () => {
    useLutManagerStore.setState({ primaryName: "", secondaryNames: ["LUT B"] });
    render(<LutManagerPanel />);

    expect(screen.getByRole("button", { name: "Merge & Save" })).toBeDisabled();
  });

  it("disables merge button when secondaryNames is empty", () => {
    useLutManagerStore.setState({
      primaryName: "Test LUT",
      primaryInfo: { name: "Test LUT", color_mode: "8-Color", color_count: 2738 },
      secondaryNames: [],
    });
    render(<LutManagerPanel />);

    expect(screen.getByRole("button", { name: "Merge & Save" })).toBeDisabled();
  });
});
