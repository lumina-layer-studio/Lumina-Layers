import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

type ScaleResult =
  | { status: "ok"; preference: string }
  | { status: "error"; code: string };
type ScaleListener = (payload: { preference: string }) => void;

// The desktop bridge as the preload script exposes it, backed by one saved
// value. The integration module reads window.electronAPI when it loads, so the
// fake has to exist before the imports below.
const desktop = vi.hoisted(() => {
  const listeners = new Set<ScaleListener>();
  let saved = "auto";
  const bridge = {
    listeners,
    getInterfaceScale: vi.fn(async (): Promise<ScaleResult> => ({ status: "ok", preference: saved })),
    setInterfaceScale: vi.fn(async (preference: string): Promise<ScaleResult> => {
      saved = preference;
      return { status: "ok", preference };
    }),
    onInterfaceScaleChanged: vi.fn((listener: ScaleListener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    }),
    reset(preference: string) {
      saved = preference;
      listeners.clear();
    },
    /** What the desktop host does after Ctrl with plus, minus or zero. */
    pressShortcut(preference: string) {
      saved = preference;
      for (const listener of listeners) listener({ preference });
    },
  };
  (globalThis as { electronAPI?: unknown }).electronAPI = bridge;
  return bridge;
});

import InterfaceScaleSetting from "../components/settings/InterfaceScaleSetting";
import { I18nProvider } from "../i18n/context";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

function renderSetting() {
  return render(
    <I18nProvider>
      <InterfaceScaleSetting />
    </I18nProvider>,
  );
}

async function findLoadedPicker(expectedLabel: string) {
  const picker = await screen.findByRole("combobox", { name: "界面缩放" });
  await waitFor(() => expect(picker).toHaveTextContent(expectedLabel));
  return picker;
}

describe("InterfaceScaleSetting", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    desktop.reset("100");
    useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
  });

  it("shows the saved scale and lists the sizes from smallest to largest", async () => {
    desktop.reset("150");
    renderSetting();

    fireEvent.click(await findLoadedPicker("150%"));

    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "30%",
      "40%",
      "50%",
      "60%",
      "70%",
      "80%",
      "90%",
      "100%",
      "110%",
      "120%",
      "130%",
      "140%",
      "150%",
      "160%",
      "170%",
      "180%",
    ]);
  });

  it("applies the chosen scale through the desktop host", async () => {
    renderSetting();

    const picker = await findLoadedPicker("100%");
    fireEvent.click(picker);
    fireEvent.click(screen.getByRole("option", { name: "30%" }));

    await waitFor(() => expect(picker).toHaveTextContent("30%"));
    expect(desktop.setInterfaceScale).toHaveBeenCalledWith("30");
  });

  it("follows changes made with the keyboard shortcuts and stops listening when closed", async () => {
    const view = renderSetting();

    const picker = await findLoadedPicker("100%");
    act(() => desktop.pressShortcut("110"));
    expect(picker).toHaveTextContent("110%");

    view.unmount();
    expect(desktop.listeners.size).toBe(0);
  });

  it("keeps the current scale and reports it when the desktop host refuses a change", async () => {
    desktop.setInterfaceScale.mockResolvedValueOnce({ status: "error", code: "denied" });
    renderSetting();

    const picker = await findLoadedPicker("100%");
    fireEvent.click(picker);
    fireEvent.click(screen.getByRole("option", { name: "150%" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("无法读取或更改界面缩放");
    expect(picker).toHaveTextContent("100%");
  });
});
