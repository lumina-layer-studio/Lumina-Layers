import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import App from "../App";
import { useWidgetStore } from "../stores/widgetStore";

// Mock apiClient to prevent real HTTP calls (health check)
vi.mock("../api/client", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { status: "ok" } }),
    post: vi.fn(),
  },
}));

// Mock Scene3D to avoid Three.js rendering in jsdom
vi.mock("../components/Scene3D", () => ({
  default: ({ modelUrl }: { modelUrl?: string }) => (
    <div data-testid="scene3d-mock">{modelUrl ?? "no-model"}</div>
  ),
}));

// Mock calibration API to prevent CalibrationPanel network calls
vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
}));

// Mock converter API to prevent fetchLutList call during data init
vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn().mockResolvedValue({ luts: [] }),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  getFileUrl: vi.fn((id: string) => `/api/files/${id}`),
}));

beforeEach(() => {
  vi.clearAllMocks();
  // Reset widget store to default layout before each test
  useWidgetStore.getState().resetLayout();
});

describe("App Widget Toggles", () => {
  it("renders widget toggle buttons only for current tab (converter by default)", () => {
    render(<App />);

    // Converter page widgets (default active tab) should be visible
    expect(screen.getByTestId("widget-toggle-basic-settings")).toBeInTheDocument();
    expect(screen.getByTestId("widget-toggle-advanced-settings")).toBeInTheDocument();
    expect(screen.getByTestId("widget-toggle-action-bar")).toBeInTheDocument();
    // Other page widgets should NOT be visible on converter tab
    expect(screen.queryByTestId("widget-toggle-calibration")).not.toBeInTheDocument();
    expect(screen.queryByTestId("widget-toggle-extractor")).not.toBeInTheDocument();
    expect(screen.queryByTestId("widget-toggle-lut-manager")).not.toBeInTheDocument();
    expect(screen.queryByTestId("widget-toggle-five-color")).not.toBeInTheDocument();
  });

  it("converter tab widgets are visible by default", () => {
    render(<App />);

    const basicToggle = screen.getByTestId("widget-toggle-basic-settings");
    const actionBarToggle = screen.getByTestId("widget-toggle-action-bar");

    // Both should have the active style (bg-blue-600)
    expect(basicToggle.className).toContain("bg-blue-600");
    expect(actionBarToggle.className).toContain("bg-blue-600");
  });

  it("toggles widget visibility when toggle button is clicked", () => {
    render(<App />);

    const basicToggle = screen.getByTestId("widget-toggle-basic-settings");

    // Initially visible (blue)
    expect(basicToggle.className).toContain("bg-blue-600");

    // Click to hide
    fireEvent.click(basicToggle);

    // Should now be inactive (gray)
    expect(basicToggle.className).not.toContain("bg-blue-600");
    expect(basicToggle.className).toContain("bg-gray-200");
  });

  it("toggles widget back to visible when clicked again", () => {
    render(<App />);

    const basicToggle = screen.getByTestId("widget-toggle-basic-settings");

    // Click to hide
    fireEvent.click(basicToggle);
    expect(basicToggle.className).toContain("bg-gray-200");

    // Click to show again
    fireEvent.click(basicToggle);
    expect(basicToggle.className).toContain("bg-blue-600");
  });

  it("renders reset layout button", () => {
    render(<App />);

    const resetButton = screen.getByTestId("widget-reset-layout");
    expect(resetButton).toBeInTheDocument();
    expect(resetButton.textContent).toBe("↺");
  });
});
