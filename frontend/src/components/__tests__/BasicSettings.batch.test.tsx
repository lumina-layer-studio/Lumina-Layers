import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { useConverterStore } from "../../stores/converterStore";
import BasicSettings from "../sections/BasicSettings";

// Mock heavy child components to isolate conditional rendering logic
vi.mock("../ui/CropModal", () => ({
  CropModal: () => null,
}));

vi.mock("../ui/Dropdown", () => ({
  default: ({ label }: { label: string }) => (
    <div data-testid={`dropdown-${label}`}>{label}</div>
  ),
}));

vi.mock("../ui/Slider", () => ({
  default: ({ label }: { label: string }) => (
    <div data-testid={`slider-${label}`}>{label}</div>
  ),
}));

vi.mock("../ui/RadioGroup", () => ({
  default: ({ label }: { label: string }) => (
    <div data-testid={`radio-${label}`}>{label}</div>
  ),
}));

function makeFile(name: string, type = "image/png"): File {
  return new File(["dummy"], name, { type });
}

describe("BasicSettings — batch mode", () => {
  beforeEach(() => {
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imagePreviewUrl: null,
      lut_name: "",
      lutList: [],
      target_width_mm: 60,
      target_height_mm: 60,
      spacer_thick: 1.2,
      enableCrop: false,
      cropModalOpen: false,
      isCropping: false,
    });
  });

  it("renders the batch mode checkbox", () => {
    render(<BasicSettings />);
    const checkbox = screen.getByRole("checkbox", { name: "批量模式" });
    expect(checkbox).toBeInTheDocument();
  });

  it("shows ImageUpload area when batchMode is false", () => {
    useConverterStore.setState({ batchMode: false });
    render(<BasicSettings />);
    // ImageUpload renders "拖拽图片或点击上传" when no preview
    expect(screen.getByText("拖拽图片或点击上传")).toBeInTheDocument();
  });

  it("shows crop checkbox when batchMode is false", () => {
    useConverterStore.setState({ batchMode: false });
    render(<BasicSettings />);
    expect(
      screen.getByRole("checkbox", { name: "上传后裁剪" }),
    ).toBeInTheDocument();
  });

  it("shows BatchFileUploader when batchMode is true", () => {
    useConverterStore.setState({ batchMode: true, batchFiles: [] });
    render(<BasicSettings />);
    expect(
      screen.getByText("拖拽图片或点击上传（支持多选）"),
    ).toBeInTheDocument();
  });

  it("hides ImageUpload when batchMode is true", () => {
    useConverterStore.setState({ batchMode: true, batchFiles: [] });
    render(<BasicSettings />);
    expect(screen.queryByText("拖拽图片或点击上传")).not.toBeInTheDocument();
  });

  it("hides crop checkbox when batchMode is true", () => {
    useConverterStore.setState({ batchMode: true, batchFiles: [] });
    render(<BasicSettings />);
    expect(
      screen.queryByRole("checkbox", { name: "上传后裁剪" }),
    ).not.toBeInTheDocument();
  });

  it("shows batch file list when batchMode is true and files exist", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png"), makeFile("b.jpg")],
    });
    render(<BasicSettings />);
    expect(screen.getByText("a.png")).toBeInTheDocument();
    expect(screen.getByText("b.jpg")).toBeInTheDocument();
    expect(screen.getByText("已选 2 个文件")).toBeInTheDocument();
  });
});
