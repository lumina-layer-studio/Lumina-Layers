import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import LoadingSpinner from "../components/LoadingSpinner";

describe("LoadingSpinner", () => {
  it("renders a loading spinner element", () => {
    render(<LoadingSpinner />);
    const spinner = screen.getByTestId("loading-spinner");
    expect(spinner).toBeInTheDocument();
  });

  it("contains an animated element", () => {
    render(<LoadingSpinner />);
    const spinner = screen.getByTestId("loading-spinner");
    const animated = spinner.querySelector(".animate-spin");
    expect(animated).not.toBeNull();
  });
});
