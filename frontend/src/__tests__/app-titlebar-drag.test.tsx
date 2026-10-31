import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App";

vi.mock("../integrations/electron", async (original) => {
  const actual = await original<typeof import("../integrations/electron")>();
  return { ...actual, electronAPI: { platform: "win32" } };
});

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { status: "ok" } }),
    post: vi.fn(),
  },
  apiErrorToVisibleMessage: vi.fn(
    (_error: unknown, fallback = "Request failed") => fallback,
  ),
}));

vi.mock("../components/Scene3D", () => ({
  default: () => <div data-testid="scene3d-mock" />,
}));

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
  generateSingleStageKit: vi.fn(),
}));

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn().mockResolvedValue({ luts: [] }),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  getFileUrl: vi.fn((id: string) => `/api/files/${id}`),
}));

describe("desktop title bar", () => {
  it("keeps the empty space beside the primary tabs draggable", async () => {
    render(<App />);
    const tab = await screen.findByTestId("tab-converter");

    const header = tab.closest("header");
    expect(header).toHaveClass("desktop-titlebar");
    // Only the tab strip opts out of dragging; its row and spacers stay draggable.
    const strip = tab.closest("nav");
    expect(strip).toHaveClass("desktop-titlebar-controls");
    expect(strip?.parentElement?.closest(".desktop-titlebar-controls")).toBeNull();
  });
});
