import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import BatchFileUploader from "../ui/BatchFileUploader";

function makeFile(name: string): File {
  return new File(["dummy"], name, { type: "image/png" });
}

describe("BatchFileUploader", () => {
  const defaultProps = {
    files: [] as File[],
    onFilesAdd: vi.fn(),
    onFileRemove: vi.fn(),
    accept: "image/jpeg,image/png,image/svg+xml",
  };

  it("shows upload prompt text when no files are selected", () => {
    render(<BatchFileUploader {...defaultProps} />);
    expect(
      screen.getByText("拖拽图片或点击上传（支持多选）"),
    ).toBeInTheDocument();
  });

  it("does not show file count when file list is empty", () => {
    render(<BatchFileUploader {...defaultProps} />);
    expect(screen.queryByText(/已选/)).not.toBeInTheDocument();
  });

  it("renders file names when files are provided", () => {
    const files = [makeFile("photo1.png"), makeFile("photo2.jpg")];
    render(<BatchFileUploader {...defaultProps} files={files} />);

    expect(screen.getByText("photo1.png")).toBeInTheDocument();
    expect(screen.getByText("photo2.jpg")).toBeInTheDocument();
  });

  it("shows correct file count", () => {
    const files = [makeFile("a.png"), makeFile("b.png"), makeFile("c.png")];
    render(<BatchFileUploader {...defaultProps} files={files} />);

    expect(screen.getByText("已选 3 个文件")).toBeInTheDocument();
  });

  it("calls onFileRemove with correct index when delete button is clicked", () => {
    const onFileRemove = vi.fn();
    const files = [makeFile("first.png"), makeFile("second.png")];
    render(
      <BatchFileUploader {...defaultProps} files={files} onFileRemove={onFileRemove} />,
    );

    const deleteBtn = screen.getByRole("button", { name: "删除 second.png" });
    fireEvent.click(deleteBtn);

    expect(onFileRemove).toHaveBeenCalledTimes(1);
    expect(onFileRemove).toHaveBeenCalledWith(1);
  });

  it("calls onFilesAdd with dropped files on drop event", () => {
    const onFilesAdd = vi.fn();
    render(<BatchFileUploader {...defaultProps} onFilesAdd={onFilesAdd} />);

    const dropZone = screen.getByRole("button", {
      name: "拖拽图片或点击上传多个文件",
    });

    const droppedFile = makeFile("dropped.png");
    const dataTransfer = {
      files: [droppedFile],
    };

    fireEvent.drop(dropZone, { dataTransfer });

    expect(onFilesAdd).toHaveBeenCalledTimes(1);
    expect(onFilesAdd).toHaveBeenCalledWith([droppedFile]);
  });

  it("renders a delete button for each file", () => {
    const files = [makeFile("x.png"), makeFile("y.jpg")];
    render(<BatchFileUploader {...defaultProps} files={files} />);

    expect(screen.getByRole("button", { name: "删除 x.png" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "删除 y.jpg" })).toBeInTheDocument();
  });
});
