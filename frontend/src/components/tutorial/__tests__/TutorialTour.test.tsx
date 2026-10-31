import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../analytics/umami", () => ({ trackLuminaEvent: vi.fn() }));

import { trackLuminaEvent } from "../../../analytics/umami";
import { TUTORIAL_STEPS } from "../../../data/tutorialSteps";
import { TUTORIAL_ANCHOR_TIMEOUT_MS } from "../../../hooks/useTutorialAnchor";
import { translations } from "../../../i18n/translations";
import { useTutorialStore } from "../../../stores/tutorialStore";
import { readTutorialProgress } from "../../../utils/tutorialProgress";
import TutorialTour from "../TutorialTour";

// setupTests.ts renders the Chinese copy for every t() call.
const zh = (key: string) => translations[key].zh;

function mountAnchor(anchor: string): HTMLElement {
  const element = document.createElement("div");
  element.setAttribute("data-tutorial", anchor);
  element.getBoundingClientRect = () =>
    ({ top: 20, left: 40, width: 600, height: 48, right: 640, bottom: 68, x: 40, y: 20, toJSON: () => ({}) }) as DOMRect;
  document.body.appendChild(element);
  return element;
}

function startTourAt(stepIndex: number) {
  useTutorialStore.getState().startTour("manual");
  useTutorialStore.setState({ stepIndex });
}

describe("TutorialTour", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(trackLuminaEvent).mockClear();
    useTutorialStore.setState({ phase: "idle", stepIndex: 0, trigger: "auto", startedAtMs: null });
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) =>
      window.setTimeout(() => cb(performance.now()), 16),
    );
    vi.stubGlobal("cancelAnimationFrame", (id: number) => window.clearTimeout(id));
  });

  afterEach(() => {
    cleanup();
    document.querySelectorAll("[data-tutorial]").forEach((node) => node.remove());
    document.querySelectorAll('[role="dialog"]').forEach((node) => node.remove());
    vi.unstubAllGlobals();
  });

  it("spotlights the step anchor and shows the step copy", async () => {
    mountAnchor("device-settings");
    startTourAt(0);
    render(<TutorialTour />);

    expect(await screen.findByTestId("tutorial-spotlight")).toBeInTheDocument();
    // The dimming cut-out must sit exactly on the padded anchor rect
    // (anchor 40,20 600x48 plus 6px padding), not be offset by a transform.
    const cutout = screen.getByTestId("tutorial-spotlight-cutout");
    expect(cutout).toHaveAttribute("x", "34");
    expect(cutout).toHaveAttribute("y", "14");
    expect(cutout).toHaveAttribute("width", "612");
    expect(cutout).toHaveAttribute("height", "60");
    expect(cutout).not.toHaveAttribute("transform");
    expect(screen.getByTestId("tutorial-spotlight")).toHaveStyle({
      top: "14px",
      left: "34px",
      width: "612px",
      height: "60px",
    });
    expect(screen.getByText(zh("tutorial_step_device_title"))).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-card")).toHaveAttribute("data-side", "bottom");
    expect(screen.queryByText(zh("tutorial_back"))).not.toBeInTheDocument();
  });

  it("falls back to a centered card when the anchor never appears", async () => {
    startTourAt(0);
    render(<TutorialTour />);

    // While searching the card is hidden; it becomes visible once the anchor
    // is declared missing.
    expect(screen.getByTestId("tutorial-card")).not.toBeVisible();
    await waitFor(() => expect(screen.getByTestId("tutorial-card")).toBeVisible(), {
      timeout: TUTORIAL_ANCHOR_TIMEOUT_MS + 1000,
    });
    expect(screen.getByTestId("tutorial-card")).toHaveAttribute("data-side", "center");
    expect(screen.queryByTestId("tutorial-spotlight")).not.toBeInTheDocument();
  });

  it("shows the recommended palettes as swatches", async () => {
    const paletteIndex = TUTORIAL_STEPS.findIndex((step) => step.id === "picker-palette");
    mountAnchor("material-picker-search");
    startTourAt(paletteIndex);
    render(<TutorialTour />);

    const palettes = await screen.findByTestId("tutorial-palettes");
    expect(palettes.querySelectorAll("section")).toHaveLength(3);
    expect(screen.getByText(zh("tutorial_palette_clear_title"))).toBeInTheDocument();
    expect(screen.getAllByText(zh("tutorial_color_clear"))).toHaveLength(1);
    expect(screen.getByTestId("tutorial-interactive-hint")).toHaveTextContent(
      zh("tutorial_interactive_auto_hint"),
    );
  });

  it("illustrates that larger prints are clearer on the size step", async () => {
    const sizeIndex = TUTORIAL_STEPS.findIndex((step) => step.id === "output-size");
    mountAnchor("output-size");
    startTourAt(sizeIndex);
    render(<TutorialTour />);

    const figure = await screen.findByTestId("tutorial-illustration-print-size");
    expect(figure.querySelectorAll("svg")).toHaveLength(2);
    expect(screen.getByText(zh("tutorial_size_caption"))).toBeInTheDocument();
  });

  it("lets clicks through the spotlight on setting steps", async () => {
    mountAnchor("device-settings");
    startTourAt(0);
    render(<TutorialTour />);

    await screen.findByTestId("tutorial-spotlight");
    expect(screen.queryByTestId("tutorial-click-shield")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("tutorial-click-shield-part")).toHaveLength(4);
  });

  it("steps aside while a dialog the user opened is up, then comes back", async () => {
    mountAnchor("device-settings");
    startTourAt(0);
    render(<TutorialTour />);
    await screen.findByTestId("tutorial-card");

    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.getClientRects = () => [{} as DOMRect] as unknown as DOMRectList;
    document.body.appendChild(dialog);
    await waitFor(() => expect(screen.queryByTestId("tutorial-tour")).not.toBeInTheDocument());

    // Escape belongs to the user's dialog meanwhile, not to the tour.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(useTutorialStore.getState().phase).toBe("touring");

    dialog.remove();
    expect(await screen.findByTestId("tutorial-tour")).toBeInTheDocument();
  });

  it("keeps arrow keys for the caret inside text fields", async () => {
    const paletteIndex = TUTORIAL_STEPS.findIndex((step) => step.id === "picker-palette");
    const search = mountAnchor("material-picker-search");
    const input = document.createElement("input");
    search.appendChild(input);
    startTourAt(paletteIndex);
    render(<TutorialTour />);
    await screen.findByTestId("tutorial-spotlight");

    fireEvent.keyDown(input, { key: "ArrowRight" });
    expect(useTutorialStore.getState().stepIndex).toBe(paletteIndex);
    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(useTutorialStore.getState().stepIndex).toBe(paletteIndex + 1);
  });

  it("prefers the precise anchor and falls back to its section", async () => {
    const materialsIndex = TUTORIAL_STEPS.findIndex((step) => step.id === "materials-open");
    const section = mountAnchor("color-source");
    section.getBoundingClientRect = () =>
      ({ top: 100, left: 40, width: 600, height: 400, right: 640, bottom: 500, x: 40, y: 100, toJSON: () => ({}) }) as DOMRect;
    startTourAt(materialsIndex);
    const { unmount } = render(<TutorialTour />);

    // Classic LUT mode: no filament picker, so the whole color block is used.
    expect(await screen.findByTestId("tutorial-spotlight")).toHaveStyle({ top: "94px", height: "412px" });
    unmount();

    // Material Archive mode: the picker itself is highlighted.
    mountAnchor("material-picker");
    render(<TutorialTour />);
    await waitFor(() =>
      expect(screen.getByTestId("tutorial-spotlight")).toHaveStyle({ top: "14px", height: "60px" }),
    );
  });

  it("explains 3D mouse controls and lets the user try them in the spotlight", async () => {
    const viewIndex = TUTORIAL_STEPS.findIndex((step) => step.id === "view-3d");
    mountAnchor("viewport-3d");
    startTourAt(viewIndex);
    render(<TutorialTour />);

    // Wait until the anchor is found; while searching the full shield stays up.
    await screen.findByTestId("tutorial-spotlight");
    const controls = screen.getByTestId("tutorial-controls");
    expect(controls.querySelectorAll("dt")).toHaveLength(4);
    expect(screen.getByText(zh("tutorial_control_left_drag"))).toBeInTheDocument();
    expect(screen.getByText(zh("tutorial_control_rotate"))).toBeInTheDocument();
    expect(screen.getByText(zh("tutorial_control_right_drag"))).toBeInTheDocument();
    expect(screen.getByText(zh("tutorial_control_pan"))).toBeInTheDocument();
    expect(screen.getByText(zh("tutorial_control_wheel"))).toBeInTheDocument();
    expect(screen.getByText(zh("tutorial_control_zoom"))).toBeInTheDocument();

    // Only the area around the spotlight is shielded; the spotlight itself
    // (the 3D view) stays usable, and the card sits inside it.
    expect(screen.queryByTestId("tutorial-click-shield")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("tutorial-click-shield-part")).toHaveLength(4);
    expect(screen.getByTestId("tutorial-tour")).toHaveClass("pointer-events-none");
    expect(screen.getByTestId("tutorial-card")).toHaveAttribute("data-side", "inside");
  });

  it("caps the card height and scrolls only the copy so actions stay reachable", async () => {
    const materialsIndex = TUTORIAL_STEPS.findIndex((step) => step.id === "materials-open");
    mountAnchor("color-source");
    startTourAt(materialsIndex);
    render(<TutorialTour />);

    await screen.findByTestId("tutorial-spotlight");
    const card = screen.getByTestId("tutorial-card");
    expect(card).toHaveClass("flex", "flex-col", "max-h-[calc(100dvh-32px)]");
    const body = screen.getByTestId("tutorial-card-body");
    expect(body).toHaveClass("overflow-y-auto", "min-h-0");
    expect(body.contains(screen.getByText(zh("tutorial_next")))).toBe(false);
    expect(body.contains(screen.getByTestId("tutorial-skip-button"))).toBe(false);
  });

  it("keeps keyboard focus inside the step card", async () => {
    const outside = document.createElement("button");
    outside.textContent = "background";
    document.body.appendChild(outside);
    // The preview step only explains; it does not let clicks through.
    mountAnchor("preview-button");
    startTourAt(TUTORIAL_STEPS.findIndex((step) => step.id === "preview"));
    render(<TutorialTour />);
    await screen.findByTestId("tutorial-spotlight");

    outside.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByTestId("tutorial-card").contains(document.activeElement)).toBe(true);
    outside.remove();
  });

  it("keeps the whole app shielded on regular steps", async () => {
    // The preview step only explains; it does not let clicks through.
    mountAnchor("preview-button");
    startTourAt(TUTORIAL_STEPS.findIndex((step) => step.id === "preview"));
    render(<TutorialTour />);

    await screen.findByTestId("tutorial-spotlight");
    expect(screen.getByTestId("tutorial-click-shield")).toHaveClass("pointer-events-auto", "inset-0");
    expect(screen.queryByTestId("tutorial-click-shield-part")).not.toBeInTheDocument();
  });

  it("moves forward and back with the buttons and arrow keys", async () => {
    mountAnchor("device-settings");
    startTourAt(0);
    render(<TutorialTour />);

    fireEvent.click(await screen.findByText(zh("tutorial_next")));
    expect(useTutorialStore.getState().stepIndex).toBe(1);

    fireEvent.click(screen.getByText(zh("tutorial_back")));
    expect(useTutorialStore.getState().stepIndex).toBe(0);

    act(() => {
      fireEvent.keyDown(document, { key: "ArrowRight" });
    });
    expect(useTutorialStore.getState().stepIndex).toBe(1);
    act(() => {
      fireEvent.keyDown(document, { key: "ArrowLeft" });
    });
    expect(useTutorialStore.getState().stepIndex).toBe(0);
  });

  it("skips in one click", async () => {
    startTourAt(3);
    render(<TutorialTour />);

    fireEvent.click(screen.getByTestId("tutorial-skip-button"));

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(readTutorialProgress()?.outcome).toBe("skipped");
    expect(trackLuminaEvent).toHaveBeenCalledWith(
      "lumina_tutorial_skipped",
      expect.objectContaining({ via: "skip_button", step_index: 4 }),
    );
  });

  it("skips with the Escape key", () => {
    startTourAt(0);
    render(<TutorialTour />);

    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(trackLuminaEvent).toHaveBeenCalledWith(
      "lumina_tutorial_skipped",
      expect.objectContaining({ via: "escape" }),
    );
  });

  it("finishes from the last step", async () => {
    mountAnchor("tutorial-launcher");
    startTourAt(TUTORIAL_STEPS.length - 1);
    render(<TutorialTour />);

    fireEvent.click(await screen.findByText(zh("tutorial_done")));

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(readTutorialProgress()?.outcome).toBe("completed");
  });

  it("covers the app with a click shield that does not end the tour", () => {
    startTourAt(0);
    render(<TutorialTour />);

    const shield = screen.getByTestId("tutorial-click-shield");
    expect(shield).toHaveClass("absolute", "inset-0");
    fireEvent.click(shield);

    expect(useTutorialStore.getState().phase).toBe("touring");
  });
});
