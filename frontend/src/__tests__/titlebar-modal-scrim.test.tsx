import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render } from "@testing-library/react";
import { useDocumentThemeClass } from "../hooks/useDocumentThemeClass";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";

const setTitlebarTheme = vi.hoisted(() => vi.fn());

vi.mock("../integrations/electron", async (original) => {
  const actual = await original<typeof import("../integrations/electron")>();
  return { ...actual, electronAPI: { platform: "win32", setTitlebarTheme } };
});

function Root({ modal }: { modal: boolean }) {
  useDocumentThemeClass();
  return modal ? <div role="dialog" aria-modal="true" aria-label="Dialog" /> : null;
}

beforeEach(() => {
  setTitlebarTheme.mockClear();
  useSettingsStore.setState({ ...DEFAULT_SETTINGS, theme: "light" });
});

describe("win32 title bar under a modal", () => {
  it("tells the title bar when a modal opens and closes", async () => {
    const { rerender } = render(<Root modal={false} />);
    expect(setTitlebarTheme).toHaveBeenLastCalledWith("light", false);

    // MutationObserver callbacks run as microtasks after the DOM change.
    await act(async () => {
      rerender(<Root modal />);
    });
    expect(setTitlebarTheme).toHaveBeenLastCalledWith("light", true);

    await act(async () => {
      useSettingsStore.getState().setTheme("dark");
    });
    expect(setTitlebarTheme).toHaveBeenLastCalledWith("dark", true);

    await act(async () => {
      rerender(<Root modal={false} />);
    });
    expect(setTitlebarTheme).toHaveBeenLastCalledWith("dark", false);
  });

  it("notices a modal portalled straight into the body", async () => {
    render(<Root modal={false} />);
    const portal = document.createElement("div");
    portal.setAttribute("aria-modal", "true");

    await act(async () => {
      document.body.appendChild(portal);
    });
    expect(setTitlebarTheme).toHaveBeenLastCalledWith("light", true);

    await act(async () => {
      portal.remove();
    });
    expect(setTitlebarTheme).toHaveBeenLastCalledWith("light", false);
  });
});
