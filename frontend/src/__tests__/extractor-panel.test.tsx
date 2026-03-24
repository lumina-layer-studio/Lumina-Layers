import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent, within } from "@testing-library/react";
import fc from "fast-check";
import { useExtractorStore } from "../stores/extractorStore";
import { ExtractorColorMode, ExtractorPage } from "../api/types";

// ========== Mock browser APIs ==========

vi.stubGlobal(
  "URL",
  Object.assign(globalThis.URL ?? {}, {
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  })
);

// Mock Image constructor for store's setImageFile
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
    if (this.onload) this.onload();
  }
}
vi.stubGlobal("Image", MockImage);

// Mock the extractor API to prevent real network calls
vi.mock("../api/extractor", () => ({
  extractColors: vi.fn(),
  manualFixCell: vi.fn(),
}));

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
    page1Extracted: false,
    page2Extracted: false,
    mergeLoading: false,
    mergeError: null,
    page1Extracted_5c: false,
    page2Extracted_5c: false,
    manufacturer: "",
    type: "",
    defaultPalette: [],
    paletteConfirmed: false,
    paletteConfirmLoading: false,
    paletteConfirmError: null,
  });
}

// ========== Generators ==========

const arbCornerPoint = fc.tuple(
  fc.integer({ min: 0, max: 10000 }),
  fc.integer({ min: 0, max: 10000 })
) as fc.Arbitrary<[number, number]>;

/** Generate corner_points array of length 0..4 */
const arbCorners0to4 = fc
  .integer({ min: 0, max: 4 })
  .chain((len) => fc.array(arbCornerPoint, { minLength: len, maxLength: len }));

/** Generate imageFile: null or a mock File */
const arbImageFile = fc.constantFrom(null, "file") as fc.Arbitrary<null | string>;

// ========== Tests ==========

beforeEach(() => {
  resetExtractorStore();
  cleanup();
});

// **Feature: extractor-calibration-tab, Property 6: 提取按钮禁用状态前置条件**
// **Validates: Requirements 6.2**
describe("Feature: extractor-calibration-tab, Property 6: 提取按钮禁用状态前置条件", () => {
  it("For any imageFile (null or non-null) and any corner_points (length 0..4), extract button disabled === (imageFile === null || corner_points.length < 4)", async () => {
    const ExtractorPanel = (await import("../components/ExtractorPanel")).default;

    await fc.assert(
      fc.asyncProperty(arbImageFile, arbCorners0to4, async (imageFileFlag, corners) => {
        cleanup();

        const imageFile = imageFileFlag === null
          ? null
          : new File(["test"], "test.png", { type: "image/png" });

        useExtractorStore.setState({
          imageFile,
          imagePreviewUrl: imageFile ? "blob:mock-url" : null,
          corner_points: corners,
          isLoading: false,
        });

        render(<ExtractorPanel />);

        const extractDiv = screen.getByTestId("extract-button");
        const button = extractDiv.querySelector("button")!;

        const expectedDisabled = imageFile === null || corners.length < 4;

        expect(button.disabled).toBe(expectedDisabled);

        cleanup();
        resetExtractorStore();
      }),
      { numRuns: 100 }
    );
  });
});

// ========== Unit Tests ==========

describe("ExtractorPanel 单元测试", () => {
  it("renders all color mode options in the dropdown", async () => {
    const ExtractorPanel = (await import("../components/ExtractorPanel")).default;

    render(<ExtractorPanel />);

    const colorModeDiv = screen.getByTestId("color-mode-select");
    const combobox = within(colorModeDiv).getByRole("combobox");

    fireEvent.click(combobox);

    const listbox = screen.getByRole("listbox");
    const options = within(listbox).getAllByRole("option");
    const optionLabels = options.map((option) => option.textContent?.trim());
    const expectedModes = Object.values(ExtractorColorMode);

    expect(optionLabels).toEqual(expect.arrayContaining(expectedModes));
    expect(options).toHaveLength(expectedModes.length);

    fireEvent.click(within(listbox).getByRole("option", { name: ExtractorColorMode.FIVE_COLOR_EXT }));
    expect(useExtractorStore.getState().color_mode).toBe(ExtractorColorMode.FIVE_COLOR_EXT);
  });

  it("shows page-select when color_mode is EIGHT_COLOR", async () => {
    const ExtractorPanel = (await import("../components/ExtractorPanel")).default;

    useExtractorStore.setState({ color_mode: ExtractorColorMode.EIGHT_COLOR });

    render(<ExtractorPanel />);

    expect(screen.getByTestId("page-select")).toBeInTheDocument();
  });

  it("hides page-select when color_mode is not EIGHT_COLOR", async () => {
    const ExtractorPanel = (await import("../components/ExtractorPanel")).default;

    for (const mode of [
      ExtractorColorMode.BW,
      ExtractorColorMode.FOUR_COLOR_RYBW,
      ExtractorColorMode.SIX_COLOR,
    ]) {
      cleanup();
      resetExtractorStore();
      useExtractorStore.setState({ color_mode: mode });

      render(<ExtractorPanel />);

      expect(screen.queryByTestId("page-select")).not.toBeInTheDocument();

      cleanup();
    }
  });

  it("renders download link when lut_download_url is set", async () => {
    const ExtractorPanel = (await import("../components/ExtractorPanel")).default;

    useExtractorStore.setState({ lut_download_url: "/api/files/lut-test.npy" });

    render(<ExtractorPanel />);

    const link = screen.getByTestId("lut-download-link");
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/api/files/lut-test.npy");
    expect(link).toHaveAttribute("download");
  });

  it("does not render download link when lut_download_url is null", async () => {
    const ExtractorPanel = (await import("../components/ExtractorPanel")).default;

    useExtractorStore.setState({ lut_download_url: null });

    render(<ExtractorPanel />);

    expect(screen.queryByTestId("lut-download-link")).not.toBeInTheDocument();
  });

  it("renders error message when error is set", async () => {
    const ExtractorPanel = (await import("../components/ExtractorPanel")).default;

    useExtractorStore.setState({ error: "颜色提取失败，请重试" });

    render(<ExtractorPanel />);

    const errorEl = screen.getByTestId("error-message");
    expect(errorEl).toBeInTheDocument();
    expect(errorEl.textContent).toBe("颜色提取失败，请重试");
  });

  it("does not render error message when error is null", async () => {
    const ExtractorPanel = (await import("../components/ExtractorPanel")).default;

    useExtractorStore.setState({ error: null });

    render(<ExtractorPanel />);

    expect(screen.queryByTestId("error-message")).not.toBeInTheDocument();
  });

  it("renders colordb metadata inputs and updates store state", async () => {
    const ExtractorPanel = (await import("../components/ExtractorPanel")).default;

    useExtractorStore.setState({
      manufacturer: "Bambu Lab",
      type: "PLA Basic",
      defaultPalette: [
        {
          color: "White",
          material: "PLA",
          hex_color: "#FFFFFF",
          color_name: "Jade White",
        },
      ],
      paletteConfirmed: false,
    });

    render(<ExtractorPanel />);

    const section = screen.getByTestId("palette-confirm-section");
    expect(section).toBeInTheDocument();
    expect(screen.getByText("White")).toBeInTheDocument();

    const textboxes = within(section).getAllByRole("textbox");
    expect(textboxes).toHaveLength(3);
    expect(textboxes[0]).toHaveValue("Bambu Lab");
    expect(textboxes[1]).toHaveValue("PLA Basic");
    expect(textboxes[2]).toHaveValue("Jade White");

    fireEvent.change(textboxes[0], { target: { value: "Prusa" } });
    fireEvent.change(textboxes[1], { target: { value: "PETG" } });
    fireEvent.change(textboxes[2], { target: { value: "Pearl White" } });

    const state = useExtractorStore.getState();
    expect(state.manufacturer).toBe("Prusa");
    expect(state.type).toBe("PETG");
    expect(state.defaultPalette[0].color_name).toBe("Pearl White");
  });
});
