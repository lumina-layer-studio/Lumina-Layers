import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App";
import { useWidgetStore } from "../stores/widgetStore";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
  },
}));

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn().mockResolvedValue({ luts: [] }),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  getFileUrl: vi.fn(),
}));

// Mock Scene3D to avoid Three.js rendering in jsdom
vi.mock("../components/Scene3D", () => ({
  default: () => <div data-testid="scene3d-mock">scene</div>,
}));

import apiClient from "../api/client";

describe("Widget Workspace Layout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });
    useWidgetStore.getState().resetLayout();
  });

  it('preserves "Lumina Studio 2.0" header', () => {
    render(<App />);
    expect(screen.getByText("Lumina Studio 2.0")).toBeInTheDocument();
  });

  it("renders widget workspace with Scene3D", () => {
    render(<App />);
    expect(screen.getByTestId("scene3d-mock")).toBeInTheDocument();
  });

  it("renders widget toggle buttons for current tab in header", () => {
    render(<App />);
    // Default tab is converter, so converter widgets should show
    expect(screen.getByTestId("widget-toggle-basic-settings")).toBeInTheDocument();
    // Calibration widget toggle should NOT show on converter tab
    expect(screen.queryByTestId("widget-toggle-calibration")).not.toBeInTheDocument();
  });

  it("renders TabNavBar with tab buttons", () => {
    render(<App />);
    expect(screen.getByTestId("tab-converter")).toBeInTheDocument();
    expect(screen.getByTestId("tab-calibration")).toBeInTheDocument();
    expect(screen.getByTestId("tab-extractor")).toBeInTheDocument();
    expect(screen.getByTestId("tab-lut-manager")).toBeInTheDocument();
    expect(screen.getByTestId("tab-five-color")).toBeInTheDocument();
  });
});
