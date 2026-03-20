import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import CalibrationPanel from "../components/CalibrationPanel";
import { useCalibrationStore } from "../stores/calibrationStore";
import { CalibrationColorMode, BackingColor } from "../api/types";

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
}));

beforeEach(() => {
  useCalibrationStore.setState({
    color_mode: CalibrationColorMode.FOUR_COLOR_RYBW,
    block_size: 5,
    gap: 0.82,
    backing: BackingColor.WHITE,
    isLoading: false,
    error: null,
    downloadUrl: null,
    previewImageUrl: null,
    modelUrl: null,
    statusMessage: null,
  });
});

describe("CalibrationPanel", () => {
  it("renders all controls", () => {
    render(<CalibrationPanel />);

    expect(screen.getByTestId("calibration-panel")).toBeInTheDocument();
    expect(screen.getByText("颜色模式")).toBeInTheDocument();
    expect(screen.getByText("色块尺寸")).toBeInTheDocument();
    expect(screen.getByText("色块间距")).toBeInTheDocument();
    expect(screen.getByText("底板颜色")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成校准板" })).toBeInTheDocument();
  });

  it("shows correct default values", () => {
    render(<CalibrationPanel />);

    // Color mode dropdown defaults to 4-Color
    const selects = screen.getAllByRole("combobox");
    expect(selects[0]).toHaveTextContent(CalibrationColorMode.FOUR_COLOR_RYBW);

    // Block size default 5 mm, rendered with two decimals
    expect(screen.getByLabelText("色块尺寸 value")).toHaveValue("5.00");

    // Gap default 0.82 mm
    expect(screen.getByLabelText("色块间距 value")).toHaveValue("0.82");

    // Backing color defaults to White
    expect(selects[1]).toHaveTextContent(BackingColor.WHITE);
  });

  it("disables block_size, gap, and backing in 8-Color Max mode", () => {
    useCalibrationStore.setState({ color_mode: CalibrationColorMode.EIGHT_COLOR });
    render(<CalibrationPanel />);

    const sliders = screen.getAllByRole("slider");
    const selects = screen.getAllByRole("combobox");

    // block_size slider disabled
    expect(sliders[0]).toBeDisabled();
    // gap slider disabled
    expect(sliders[1]).toBeDisabled();
    // backing dropdown disabled
    expect(selects[1]).toBeDisabled();
  });

  it("disables only backing in 6-Color mode", () => {
    useCalibrationStore.setState({ color_mode: CalibrationColorMode.SIX_COLOR });
    render(<CalibrationPanel />);

    const sliders = screen.getAllByRole("slider");
    const selects = screen.getAllByRole("combobox");

    // block_size and gap sliders enabled
    expect(sliders[0]).not.toBeDisabled();
    expect(sliders[1]).not.toBeDisabled();
    // backing dropdown disabled
    expect(selects[1]).toBeDisabled();
  });

  it("enables all controls in BW mode", () => {
    useCalibrationStore.setState({ color_mode: CalibrationColorMode.BW });
    render(<CalibrationPanel />);

    const sliders = screen.getAllByRole("slider");
    const selects = screen.getAllByRole("combobox");

    expect(sliders[0]).not.toBeDisabled();
    expect(sliders[1]).not.toBeDisabled();
    expect(selects[0]).not.toBeDisabled();
    expect(selects[1]).not.toBeDisabled();
  });

  it("enables all controls in 4-Color mode", () => {
    render(<CalibrationPanel />);

    const sliders = screen.getAllByRole("slider");
    const selects = screen.getAllByRole("combobox");

    expect(sliders[0]).not.toBeDisabled();
    expect(sliders[1]).not.toBeDisabled();
    expect(selects[0]).not.toBeDisabled();
    expect(selects[1]).not.toBeDisabled();
  });

  it("disables generate button when isLoading is true", () => {
    useCalibrationStore.setState({ isLoading: true });
    render(<CalibrationPanel />);

    expect(screen.getByRole("button", { name: "生成校准板" })).toBeDisabled();
  });

  it("shows error message when error is set", () => {
    useCalibrationStore.setState({ error: "网络连接失败" });
    render(<CalibrationPanel />);

    const errorEl = screen.getByTestId("error-message");
    expect(errorEl).toBeInTheDocument();
    expect(errorEl).toHaveTextContent("网络连接失败");
  });

  it("shows status message when statusMessage is set", () => {
    useCalibrationStore.setState({ statusMessage: "校准板生成成功" });
    render(<CalibrationPanel />);

    const statusEl = screen.getByTestId("status-message");
    expect(statusEl).toBeInTheDocument();
    expect(statusEl).toHaveTextContent("校准板生成成功");
  });

  it("shows download link when downloadUrl is set", () => {
    useCalibrationStore.setState({ downloadUrl: "/api/files/test.3mf" });
    render(<CalibrationPanel />);

    const link = screen.getByTestId("download-link");
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/api/files/test.3mf");
    expect(link).toHaveAttribute("download");
  });

  it("shows preview image when previewImageUrl is set", () => {
    useCalibrationStore.setState({ previewImageUrl: "/api/files/preview.png" });
    render(<CalibrationPanel />);

    const img = screen.getByTestId("preview-image");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "/api/files/preview.png");
    expect(img).toHaveAttribute("alt", "校准板预览");
  });
});
