import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import fc from "fast-check";
import { useExtractorStore } from "../stores/extractorStore";
import { CORNER_LABELS } from "../components/ExtractorCanvas";
import { ExtractorColorMode, ExtractorPage } from "../api/types";

// ========== Mock browser APIs ==========

vi.stubGlobal(
  "URL",
  Object.assign(globalThis.URL ?? {}, {
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  })
);

// Mock canvas getContext so jsdom doesn't choke
HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
  clearRect: vi.fn(),
  drawImage: vi.fn(),
  beginPath: vi.fn(),
  arc: vi.fn(),
  fill: vi.fn(),
  stroke: vi.fn(),
  fillText: vi.fn(),
  set fillStyle(_v: string) {},
  set strokeStyle(_v: string) {},
  set lineWidth(_v: number) {},
  set font(_v: string) {},
  set textAlign(_v: string) {},
  set textBaseline(_v: string) {},
  canvas: { width: 800, height: 600 },
})) as unknown as typeof HTMLCanvasElement.prototype.getContext;

// Mock Image constructor for the component's useEffect
class MockImage {
  onload: (() => void) | null = null;
  _src = "";
  naturalWidth = 800;
  naturalHeight = 600;
  get src() {
    return this._src;
  }
  set src(val: string) {
    this._src = val;
    // Trigger onload synchronously for testing
    if (this.onload) this.onload();
  }
}
vi.stubGlobal("Image", MockImage);

// ========== Helpers ==========

function resetExtractorStore(): void {
  useExtractorStore.setState({
    imageFile: null,
    imagePreviewUrl: null,
    imageNaturalWidth: null,
    imageNaturalHeight: null,
    color_mode: ExtractorColorMode.FOUR_COLOR_RYBW,
    page: ExtractorPage.PAGE_1,
    corner_points: [],
    offset_x: 0,
    offset_y: 0,
    zoom: 1.0,
    distortion: 0.0,
    vignette_correction: false,
    isLoading: false,
    error: null,
    session_id: null,
    lut_download_url: null,
    warp_view_url: null,
    lut_preview_url: null,
    manualFixLoading: false,
    manualFixError: null,
  });
}

// ========== Generators ==========

const arbExtractorColorMode = fc.constantFrom(
  ExtractorColorMode.BW,
  ExtractorColorMode.FOUR_COLOR_RYBW,
  ExtractorColorMode.SIX_COLOR,
  ExtractorColorMode.SIX_COLOR_RYBW,
  ExtractorColorMode.EIGHT_COLOR
);

const arbCornerCount = fc.integer({ min: 0, max: 3 });

// ========== Tests ==========

beforeEach(() => {
  resetExtractorStore();
  cleanup();
});


// **Feature: extractor-calibration-tab, Property 2: 角点提示标签正确性**
// **Validates: Requirements 4.1, 4.3**
describe("Feature: extractor-calibration-tab, Property 2: 角点提示标签正确性", () => {
  it("For any CalibrationColorMode and corner count 0..3, the hint label equals CORNER_LABELS[color_mode][corner_count]", () => {
    fc.assert(
      fc.property(arbExtractorColorMode, arbCornerCount, (colorMode, cornerCount) => {
        const labels = CORNER_LABELS[colorMode] ?? CORNER_LABELS["4-Color (RYBW)"];
        const expectedLabel = labels[cornerCount];

        // The component builds hint text as:
        // `请点击第 ${cornerCount + 1} 个角点: ${labels[cornerCount]}`
        // We verify the CORNER_LABELS mapping is correct and the label exists
        const isValidLabel = typeof expectedLabel === "string" && expectedLabel.length > 0;

        // Verify the label index is within bounds
        const isInBounds = cornerCount < labels.length;

        return isValidLabel && isInBounds;
      }),
      { numRuns: 100 }
    );
  });

  it("When corner count is 4, the hint text contains '定位完成'", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    // For each color mode, verify that 4 corners shows "定位完成"
    for (const mode of [
      ExtractorColorMode.BW,
      ExtractorColorMode.FOUR_COLOR_RYBW,
      ExtractorColorMode.SIX_COLOR,
      ExtractorColorMode.SIX_COLOR_RYBW,
      ExtractorColorMode.EIGHT_COLOR,
    ]) {
      cleanup();
      useExtractorStore.setState({
        imagePreviewUrl: "blob:test-image",
        imageNaturalWidth: 800,
        imageNaturalHeight: 600,
        color_mode: mode,
        corner_points: [
          [100, 100],
          [700, 100],
          [700, 500],
          [100, 500],
        ],
        warp_view_url: null,
        lut_preview_url: null,
      });

      render(<ExtractorCanvas />);
      const hint = screen.getByTestId("corner-hint");
      expect(hint.textContent).toContain("定位完成");
      cleanup();
      resetExtractorStore();
    }
  });

  it("For any color mode and corner count 0..3, rendered hint contains the correct CORNER_LABELS entry", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    await fc.assert(
      fc.asyncProperty(arbExtractorColorMode, arbCornerCount, async (colorMode, cornerCount) => {
        cleanup();

        // Build corner_points array of the given length
        const corners: Array<[number, number]> = Array.from({ length: cornerCount }, (_, i) => [
          100 + i * 200,
          100 + i * 100,
        ]);

        useExtractorStore.setState({
          imagePreviewUrl: "blob:test-image",
          imageNaturalWidth: 800,
          imageNaturalHeight: 600,
          color_mode: colorMode,
          corner_points: corners,
          warp_view_url: null,
          lut_preview_url: null,
        });

        render(<ExtractorCanvas />);

        const hint = screen.getByTestId("corner-hint");
        const labels = CORNER_LABELS[colorMode] ?? CORNER_LABELS["4-Color (RYBW)"];
        const expectedLabel = labels[cornerCount];

        expect(hint.textContent).toContain(expectedLabel);

        cleanup();
        resetExtractorStore();
      }),
      { numRuns: 100 }
    );
  });
});

// ========== Unit Tests ==========

describe("ExtractorCanvas 单元测试", () => {
  it("renders empty state when no image is uploaded", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    useExtractorStore.setState({
      imagePreviewUrl: null,
      warp_view_url: null,
      lut_preview_url: null,
    });

    render(<ExtractorCanvas />);
    expect(screen.getByTestId("extractor-empty-state")).toBeInTheDocument();
    expect(screen.getByText("请在左侧面板上传校准板照片")).toBeInTheDocument();
  });

  it("shows '定位完成' hint when 4 corner points are marked", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      imageNaturalWidth: 800,
      imageNaturalHeight: 600,
      color_mode: ExtractorColorMode.FOUR_COLOR_RYBW,
      corner_points: [
        [100, 100],
        [700, 100],
        [700, 500],
        [100, 500],
      ],
      warp_view_url: null,
      lut_preview_url: null,
    });

    render(<ExtractorCanvas />);
    const hint = screen.getByTestId("corner-hint");
    expect(hint.textContent).toContain("定位完成");
    expect(hint).toHaveClass("text-emerald-600");
  });

  it("renders warp_view and lut_preview images when extraction results exist", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      warp_view_url: "/api/files/warp-123",
      lut_preview_url: "/api/files/lut-456",
    });

    render(<ExtractorCanvas />);
    expect(screen.getByTestId("extractor-results")).toBeInTheDocument();
    expect(screen.getByTestId("warp-view-image")).toHaveAttribute("src", "/api/files/warp-123");
    expect(screen.getByTestId("lut-preview-image")).toHaveAttribute("src", "/api/files/lut-456");
  });

  it("renders only warp_view when lut_preview is null", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      warp_view_url: "/api/files/warp-123",
      lut_preview_url: null,
    });

    render(<ExtractorCanvas />);
    expect(screen.getByTestId("extractor-results")).toBeInTheDocument();
    expect(screen.getByTestId("warp-view-image")).toBeInTheDocument();
    expect(screen.queryByTestId("lut-preview-image")).not.toBeInTheDocument();
  });

  it("shows canvas mode with corner hint when image is uploaded but corners incomplete", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      imageNaturalWidth: 800,
      imageNaturalHeight: 600,
      color_mode: ExtractorColorMode.FOUR_COLOR_RYBW,
      corner_points: [[100, 100]],
      warp_view_url: null,
      lut_preview_url: null,
    });

    render(<ExtractorCanvas />);
    const hint = screen.getByTestId("corner-hint");
    // 1 corner placed, so hint should show the 2nd corner label
    expect(hint.textContent).toContain("右上");
    expect(hint).toHaveClass("text-amber-600");
  });
});
