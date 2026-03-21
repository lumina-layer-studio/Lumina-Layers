import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import App from "../App";

// Mock the API client module
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

import apiClient from "../api/client";

describe("App component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders green badge when API returns status "ok"', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("health-badge-ok")).toBeInTheDocument();
    });
  });

  it("renders red badge when API request fails", async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("Network Error"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("health-badge-fail")).toBeInTheDocument();
    });
  });

  it('renders header with "Lumina Studio 2.0"', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: { status: "ok", version: "2.0", uptime_seconds: 100 },
    });

    render(<App />);

    expect(screen.getByText("Lumina Studio 2.0")).toBeInTheDocument();
  });
});
