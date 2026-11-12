import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import App from "../App";
import { useSettingsStore } from "../stores/settingsStore";
import { useWidgetStore } from "../stores/widgetStore";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
  },
  apiErrorToVisibleMessage: (_error: unknown, fallback: string) => fallback,
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
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 2400 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 1200 });
    Object.defineProperty(window, "devicePixelRatio", { configurable: true, value: 1 });
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });
    useWidgetStore.getState().resetLayout();
    useSettingsStore.setState({ headerNavAlignment: "center" });
  });

  it('preserves "Lumina Studio 2" header', async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    expect(screen.getByText("Lumina Studio 2")).toBeInTheDocument();
  });

  it("renders widget workspace with Scene3D", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    expect(screen.getByTestId("scene3d-mock")).toBeInTheDocument();
  });

  it("renders panel controls toggle button in header", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    // Widget toggles are now inside a dropdown menu
    expect(screen.getByTestId("panel-controls-toggle")).toBeInTheDocument();
  });

  it("renders the full main-app top-level navigation", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    expect(screen.getByTestId("tab-converter")).toBeInTheDocument();
    expect(screen.getByTestId("tab-lut-management")).toBeInTheDocument();
    expect(screen.getByTestId("tab-material-management")).toBeInTheDocument();
    expect(screen.getByTestId("tab-vectorizer")).toBeInTheDocument();
    expect(screen.getByTestId("tab-workshop")).toBeInTheDocument();
    expect(screen.getByTestId("tab-settings")).toBeInTheDocument();
  });

  it("places Creative Workshop between Vectorizer and Settings", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");

    const primaryTabs = screen
      .getAllByRole("button")
      .map((button) => button.dataset.testid)
      .filter((testId) => testId?.startsWith("tab-"));

    expect(primaryTabs).toEqual([
      "tab-converter",
      "tab-lut-management",
      "tab-material-management",
      "tab-vectorizer",
      "tab-workshop",
      "tab-settings",
    ]);
  });

  it("keeps the top-level navigation in the centered header column by default", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");

    const converterTab = screen.getByTestId("tab-converter");
    const nav = converterTab.closest("nav");
    const header = nav?.closest("header");
    const tabWrapper = nav?.parentElement;

    expect(header).toHaveClass("grid-cols-[auto_minmax(0,1fr)_auto]");
    expect(tabWrapper).toHaveClass("col-start-2", "row-start-1", "justify-center");
    expect(tabWrapper).not.toHaveClass("w-full");
    // Centering spacers flank both strips so the rows share one centre line.
    expect(nav?.previousElementSibling).toHaveAttribute("aria-hidden", "true");
    expect(nav?.nextElementSibling).toHaveAttribute("aria-hidden", "true");
    const subTabs = screen.getByTestId("subtab-converter-core").closest("nav");
    expect(subTabs?.previousElementSibling).toHaveAttribute("aria-hidden", "true");
    expect(subTabs?.nextElementSibling).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByTestId("sub-tab-row")).toHaveClass("justify-center");
  });

  it("left-aligns both navigation rows when the setting asks for it", async () => {
    useSettingsStore.setState({ headerNavAlignment: "left" });
    render(<App />);
    await screen.findByTestId("tab-converter");

    const nav = screen.getByTestId("tab-converter").closest("nav");
    const header = nav?.closest("header");
    const tabWrapper = nav?.parentElement;

    expect(header).toHaveClass("grid-cols-[auto_minmax(0,1fr)_auto]");
    expect(tabWrapper).toHaveClass("col-start-2", "row-start-1", "justify-start");
    expect(nav?.previousElementSibling).toHaveStyle({ display: "none" });
    expect(nav?.nextElementSibling).toHaveStyle({ display: "none" });
    expect(screen.getByTestId("sub-tab-row")).toHaveClass("justify-start");
  });

  it("keeps the sub tabs while the alignment setting changes", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");
    const primaryTabs = screen.getByTestId("tab-converter").closest("nav");
    const subTabs = screen.getByTestId("subtab-converter-core").closest("nav");

    act(() => useSettingsStore.getState().setHeaderNavAlignment("left"));
    expect(screen.getByTestId("sub-tab-row")).toHaveClass("justify-start");
    expect(screen.getByTestId("subtab-converter-core")).toBeVisible();

    act(() => useSettingsStore.getState().setHeaderNavAlignment("center"));
    expect(screen.getByTestId("sub-tab-row")).toHaveClass("justify-center");
    expect(screen.getByTestId("subtab-converter-core")).toBeVisible();

    // The same strips stay mounted, keeping their scroll position and focus.
    expect(screen.getByTestId("tab-converter").closest("nav")).toBe(primaryTabs);
    expect(screen.getByTestId("subtab-converter-core").closest("nav")).toBe(subTabs);
  });

  it("applies the stored dark theme to the page", async () => {
    useSettingsStore.setState({ theme: "dark" });
    try {
      render(<App />);
    await screen.findByTestId("tab-converter");
      expect(document.documentElement).toHaveClass("dark");
    } finally {
      useSettingsStore.setState({ theme: "light" });
      document.documentElement.classList.remove("dark");
    }
  });

  it("shows the brand title next to the logo while the header has room", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");

    const title = screen.getByTestId("header-brand-title");
    expect(title).toHaveTextContent("Lumina Studio 2");
    expect(title).not.toHaveClass("max-w-0");
  });

  it("renders local LUT and material secondary tabs in the main app", async () => {
    render(<App />);
    await screen.findByTestId("tab-converter");

    fireEvent.click(screen.getByTestId("tab-lut-management"));
    expect(screen.getByTestId("subtab-lut-library")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-calibration")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-extractor")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-lut-cloud-sync")).toBeInTheDocument();
    expect(screen.queryByTestId("subtab-lut-manager")).not.toBeInTheDocument();
    expect(screen.getByTestId("subtab-five-color")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("tab-material-management"));
    expect(screen.getByTestId("subtab-material-library")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-material-cloud-sync")).toBeInTheDocument();
    expect(screen.queryByTestId("subtab-lut-cloud-sync")).not.toBeInTheDocument();
    expect(screen.getByTestId("subtab-material-recipe")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-material-gamut")).toBeInTheDocument();
    expect(screen.getByTestId("subtab-material-cache")).toBeInTheDocument();

    expect(screen.queryByTestId("tab-calibration")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-extractor")).not.toBeInTheDocument();
  });
});
