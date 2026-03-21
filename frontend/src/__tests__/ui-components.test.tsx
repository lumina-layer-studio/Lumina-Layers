import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import Accordion from "../components/ui/Accordion";
import Slider from "../components/ui/Slider";
import ImageUpload from "../components/ui/ImageUpload";

describe("Accordion", () => {
  it("hides children when defaultOpen is false", () => {
    render(
      <Accordion title="Test Section" defaultOpen={false}>
        <p>Hidden content</p>
      </Accordion>,
    );
    expect(screen.queryByText("Hidden content")).not.toBeInTheDocument();
  });

  it("shows children after clicking the title", () => {
    render(
      <Accordion title="Test Section" defaultOpen={false}>
        <p>Hidden content</p>
      </Accordion>,
    );
    fireEvent.click(screen.getByText("Test Section"));
    expect(screen.getByText("Hidden content")).toBeInTheDocument();
  });

  it("hides children again on second click", () => {
    render(
      <Accordion title="Test Section" defaultOpen={false}>
        <p>Hidden content</p>
      </Accordion>,
    );
    const title = screen.getByText("Test Section");
    fireEvent.click(title);
    expect(screen.getByText("Hidden content")).toBeInTheDocument();
    fireEvent.click(title);
    expect(screen.queryByText("Hidden content")).not.toBeInTheDocument();
  });
});

describe("Slider", () => {
  it("displays the current value", () => {
    render(
      <Slider label="Width" value={50} min={0} max={100} step={1} onChange={() => {}} />,
    );
    expect(screen.getByText("50")).toBeInTheDocument();
  });

  it("displays value with unit when provided", () => {
    render(
      <Slider label="Width" value={50} min={0} max={100} step={1} onChange={() => {}} unit="mm" />,
    );
    expect(screen.getByText("50 mm")).toBeInTheDocument();
  });
});

describe("ImageUpload", () => {
  it("passes accept prop to the hidden file input", () => {
    render(
      <ImageUpload
        onFileSelect={vi.fn()}
        accept="image/jpeg,image/png,image/svg+xml"
      />,
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.accept).toBe("image/jpeg,image/png,image/svg+xml");
  });
});
