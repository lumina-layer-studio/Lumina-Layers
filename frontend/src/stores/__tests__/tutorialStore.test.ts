import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../analytics/umami", () => ({ trackLuminaEvent: vi.fn() }));

import { trackLuminaEvent } from "../../analytics/umami";
import { TUTORIAL_STEPS } from "../../data/tutorialSteps";
import type { WidgetId, WidgetLayoutState } from "../../types/widget";
import {
  readTutorialProgress,
  TUTORIAL_STORAGE_KEY,
  TUTORIAL_WORKSPACE_STORAGE_KEY,
  writeTutorialProgress,
} from "../../utils/tutorialProgress";
import { useTutorialStore } from "../tutorialStore";
import { DEFAULT_LAYOUT, useWidgetStore } from "../widgetStore";

const trackMock = vi.mocked(trackLuminaEvent);
const TOTAL = TUTORIAL_STEPS.length;

function freshLayout(): Record<WidgetId, WidgetLayoutState> {
  return Object.fromEntries(
    Object.entries(DEFAULT_LAYOUT).map(([id, layout]) => [id, { ...layout }]),
  ) as Record<WidgetId, WidgetLayoutState>;
}

function eventsNamed(name: string) {
  return trackMock.mock.calls.filter(([eventName]) => eventName === name);
}

describe("tutorialStore", () => {
  beforeEach(() => {
    localStorage.clear();
    trackMock.mockClear();
    useTutorialStore.setState({
      phase: "idle",
      stepIndex: 0,
      trigger: "auto",
      startedAtMs: null,
    });
    useWidgetStore.setState({
      widgets: freshLayout(),
      activeTab: "converter",
      activeConverterSubTab: "core",
      color2DOverlayOpen: false,
    });
  });

  it("offers the welcome once and records the offer immediately", () => {
    useTutorialStore.getState().offerFirstRun();

    expect(useTutorialStore.getState().phase).toBe("welcome");
    expect(readTutorialProgress()?.outcome).toBe("offered");
    expect(eventsNamed("lumina_tutorial_offered")).toHaveLength(1);

    useTutorialStore.setState({ phase: "idle" });
    useTutorialStore.getState().offerFirstRun();

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(eventsNamed("lumina_tutorial_offered")).toHaveLength(1);
  });

  it("does not auto-offer when a previous outcome exists", () => {
    writeTutorialProgress("skipped");

    useTutorialStore.getState().offerFirstRun();

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(trackMock).not.toHaveBeenCalled();
  });

  it("treats an unreadable record as not offered", () => {
    localStorage.setItem(TUTORIAL_STORAGE_KEY, "{not json");

    useTutorialStore.getState().offerFirstRun();

    expect(useTutorialStore.getState().phase).toBe("welcome");
  });

  it("starts the tour from the welcome and reports the first step", () => {
    const store = useTutorialStore.getState();
    store.offerFirstRun();
    store.startTour("auto");

    const state = useTutorialStore.getState();
    expect(state.phase).toBe("touring");
    expect(state.stepIndex).toBe(0);
    expect(trackMock).toHaveBeenCalledWith("lumina_tutorial_started", { trigger: "auto" });
    expect(trackMock).toHaveBeenCalledWith("lumina_tutorial_step_view", {
      trigger: "auto",
      step_id: "device-settings",
      step_index: 1,
      total_steps: TOTAL,
    });
  });

  it("walks every step and records completion", () => {
    const store = useTutorialStore.getState();
    store.startTour("manual");
    for (let i = 0; i < TOTAL; i += 1) {
      useTutorialStore.getState().next();
    }

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(readTutorialProgress()?.outcome).toBe("completed");
    expect(eventsNamed("lumina_tutorial_step_view")).toHaveLength(TOTAL);
    const [completed] = eventsNamed("lumina_tutorial_completed");
    expect(completed?.[1]).toMatchObject({ trigger: "manual", total_steps: TOTAL });
    expect(eventsNamed("lumina_tutorial_skipped")).toHaveLength(0);
  });

  it("back is a no-op on the first step and returns one step otherwise", () => {
    const store = useTutorialStore.getState();
    store.startTour("auto");
    useTutorialStore.getState().back();
    expect(useTutorialStore.getState().stepIndex).toBe(0);

    useTutorialStore.getState().next();
    useTutorialStore.getState().next();
    useTutorialStore.getState().back();
    expect(useTutorialStore.getState().stepIndex).toBe(1);
  });

  it("skips mid-tour in one call and reports where the user left", () => {
    const store = useTutorialStore.getState();
    store.startTour("auto");
    useTutorialStore.getState().next();
    useTutorialStore.getState().next();

    useTutorialStore.getState().skip("skip_button");

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(readTutorialProgress()?.outcome).toBe("skipped");
    const [skipped] = eventsNamed("lumina_tutorial_skipped");
    expect(skipped?.[1]).toMatchObject({
      trigger: "auto",
      via: "skip_button",
      step_id: "materials-open",
      step_index: 3,
      total_steps: TOTAL,
    });
  });

  it("skipping the welcome is reported as the welcome step", () => {
    const store = useTutorialStore.getState();
    store.offerFirstRun();
    store.skip("welcome");

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(readTutorialProgress()?.outcome).toBe("skipped");
    const [skipped] = eventsNamed("lumina_tutorial_skipped");
    expect(skipped?.[1]).toMatchObject({ via: "welcome", step_id: "welcome", step_index: 0 });
  });

  it("opens the page and panel a step needs", () => {
    useWidgetStore.setState((state) => ({
      activeTab: "settings",
      activeConverterSubTab: "color",
      color2DOverlayOpen: true,
      widgets: {
        ...state.widgets,
        "basic-settings": { ...state.widgets["basic-settings"], visible: false, collapsed: true },
        "action-bar": { ...state.widgets["action-bar"], collapsed: true },
      },
    }));

    useTutorialStore.getState().startTour("manual");
    useTutorialStore.getState().next(); // image-upload

    let widgets = useWidgetStore.getState();
    expect(widgets.activeTab).toBe("converter");
    expect(widgets.activeConverterSubTab).toBe("core");
    expect(widgets.color2DOverlayOpen).toBe(false);
    expect(widgets.widgets["basic-settings"]).toMatchObject({ visible: true, collapsed: false });

    const previewIndex = TUTORIAL_STEPS.findIndex((step) => step.id === "preview");
    useTutorialStore.setState({ stepIndex: previewIndex - 1 });
    useTutorialStore.getState().next();

    widgets = useWidgetStore.getState();
    expect(widgets.widgets["action-bar"]).toMatchObject({ visible: true, collapsed: false });
  });

  function hideAndCollapseWorkspace() {
    useWidgetStore.setState((state) => ({
      activeTab: "settings",
      activeConverterSubTab: "color",
      color2DOverlayOpen: true,
      widgets: {
        ...state.widgets,
        "basic-settings": { ...state.widgets["basic-settings"], visible: false, collapsed: true },
        "action-bar": { ...state.widgets["action-bar"], collapsed: true },
      },
    }));
  }

  function expectOriginalWorkspace() {
    const widgets = useWidgetStore.getState();
    expect(widgets.activeTab).toBe("settings");
    expect(widgets.activeConverterSubTab).toBe("color");
    expect(widgets.color2DOverlayOpen).toBe(true);
    expect(widgets.widgets["basic-settings"]).toMatchObject({ visible: false, collapsed: true });
    expect(widgets.widgets["action-bar"]).toMatchObject({ collapsed: true });
  }

  it("restores the user's page and panels when the tour is skipped", () => {
    hideAndCollapseWorkspace();

    useTutorialStore.getState().startTour("manual");
    useTutorialStore.getState().next(); // opens basic-settings
    expect(useWidgetStore.getState().activeTab).toBe("converter");

    useTutorialStore.getState().skip("escape");

    expectOriginalWorkspace();
  });

  it("restores the user's page and panels when the tour finishes", () => {
    hideAndCollapseWorkspace();

    useTutorialStore.getState().startTour("manual");
    for (let i = 0; i < TOTAL; i += 1) {
      useTutorialStore.getState().next();
    }

    expect(useTutorialStore.getState().phase).toBe("idle");
    expectOriginalWorkspace();
  });

  it("keeps panels the tour did not change as the user left them", () => {
    useTutorialStore.getState().startTour("manual");
    useTutorialStore.getState().next();
    // The user collapses an already-open panel during an interactive step.
    useWidgetStore.getState().toggleCollapse("action-bar");

    useTutorialStore.getState().skip("skip_button");

    expect(useWidgetStore.getState().widgets["action-bar"].collapsed).toBe(true);
  });

  it("restores the user's workspace after a reload interrupts the tour", async () => {
    hideAndCollapseWorkspace();
    useTutorialStore.getState().startTour("manual");
    useTutorialStore.getState().next(); // switches page and opens basic-settings
    expect(useWidgetStore.getState().activeTab).toBe("converter");

    // Reload: in-memory stores are rebuilt from browser storage only.
    vi.resetModules();
    const reloadedWidgets = (await import("../widgetStore")).useWidgetStore;
    const reloadedTutorial = (await import("../tutorialStore")).useTutorialStore;
    expect(reloadedWidgets.getState().activeTab).toBe("converter");

    reloadedTutorial.getState().recoverInterruptedTour();

    const widgets = reloadedWidgets.getState();
    expect(widgets.activeTab).toBe("settings");
    expect(widgets.activeConverterSubTab).toBe("color");
    expect(widgets.widgets["basic-settings"]).toMatchObject({ visible: false, collapsed: true });
    expect(localStorage.getItem(TUTORIAL_WORKSPACE_STORAGE_KEY)).toBeNull();
  });

  it("clears the stored workspace snapshot on a normal exit", () => {
    useTutorialStore.getState().startTour("manual");
    expect(localStorage.getItem(TUTORIAL_WORKSPACE_STORAGE_KEY)).not.toBeNull();

    useTutorialStore.getState().skip("skip_button");

    expect(localStorage.getItem(TUTORIAL_WORKSPACE_STORAGE_KEY)).toBeNull();
  });
});

