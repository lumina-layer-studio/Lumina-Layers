import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import fc from "fast-check";

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

vi.mock("../api/extractor", () => ({
  extractColors: vi.fn(),
  manualFixCell: vi.fn(),
}));

vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
  I18nProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("../components/Scene3D", () => ({ default: () => null }));
vi.mock("../components/CalibrationPanel", () => ({ default: () => null }));
vi.mock("../components/ExtractorPanel", () => ({ default: () => null }));
vi.mock("../components/ExtractorCanvas", () => ({ default: () => null }));
vi.mock("../components/LutManagerPanel", () => ({ default: () => null }));
vi.mock("../components/AboutView", () => ({ default: () => null }));
vi.mock("../components/FiveColorQueryPanel", () => ({ default: () => null }));
vi.mock("../components/LoadingSpinner", () => ({ default: () => null }));
vi.mock("../components/LanguageToggle", () => ({ LanguageToggle: () => null }));
vi.mock("../components/ThemeToggle", () => ({ ThemeToggle: () => null }));

import App from "../App";
import apiClient from "../api/client";

describe("Feature: frontend-scaffold, Property 2: 非 'ok' 状态显示失败徽章", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    cleanup();
  });

  /**
   * Validates: Requirements 5.3
   * For any non-"ok" status string, the App should render a red (fail) badge.
   */
  it("renders red badge for any non-ok status", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string().filter((s) => s !== "ok"),
        async (status) => {
          vi.clearAllMocks();
          cleanup();

          vi.mocked(apiClient.get).mockResolvedValueOnce({
            data: { status, version: "2.0", uptime_seconds: 0 },
          });

          render(<App />);

          await waitFor(() => {
            expect(screen.getByTestId("health-badge-fail")).toBeInTheDocument();
          });

          expect(
            screen.queryByTestId("health-badge-ok")
          ).not.toBeInTheDocument();
        }
      ),
      { numRuns: 20 }
    );
  }, 30000);
});
