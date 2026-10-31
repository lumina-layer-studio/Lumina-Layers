import { describe, expect, it } from "vitest";
import { collectTutorialStepKeys, TUTORIAL_STEPS } from "../data/tutorialSteps";
import { translations } from "../i18n/translations";

describe("beginner tutorial steps", () => {
  it("reference translation keys that exist with non-empty zh and en text", () => {
    const problems = collectTutorialStepKeys().filter((key) => {
      const entry = translations[key];
      return !entry || !entry.zh.trim() || !entry.en.trim();
    });
    expect(problems).toEqual([]);
  });

  it("have unique ids", () => {
    const ids = TUTORIAL_STEPS.map((step) => step.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("walk a beginner through the recommended path in order", () => {
    expect(TUTORIAL_STEPS.map((step) => step.id)).toEqual([
      "device-settings",
      "color-source",
      "materials-open",
      "picker-palette",
      "picker-cards",
      "picker-favorites",
      "picker-done",
      "materials-summary",
      "materials-backing",
      "materials-missing",
      "layer-height",
      "layer-count",
      "coating",
      "image-upload",
      "output-size",
      "preview",
      "view-3d",
      "print-output",
      "help",
    ]);
  });

  it("fall back to the color block when Material Archive controls are hidden", () => {
    for (const id of [
      "materials-open",
      "picker-palette",
      "picker-cards",
      "picker-favorites",
      "picker-done",
      "materials-summary",
      "materials-backing",
      "layer-height",
      "layer-count",
    ]) {
      const anchor = TUTORIAL_STEPS.find((step) => step.id === id)?.anchor;
      expect(Array.isArray(anchor)).toBe(true);
      expect((anchor as readonly string[]).at(-1)).toBe("color-source");
    }
  });

  it("open the material picker only for the steps inside it", () => {
    const pickerSteps = TUTORIAL_STEPS.filter((step) => step.prepare?.materialPicker).map(
      (step) => step.id,
    );
    expect(pickerSteps).toEqual(["picker-palette", "picker-cards", "picker-favorites", "picker-done"]);
  });

  it("let the user set things up in the setting steps", () => {
    const interactive = TUTORIAL_STEPS.filter((step) => step.interactive).map((step) => step.id);
    expect(interactive).toEqual(
      expect.arrayContaining([
        "device-settings",
        "color-source",
        "materials-open",
        "picker-palette",
        "picker-cards",
        "picker-done",
        "materials-backing",
        "layer-height",
        "layer-count",
        "coating",
        "image-upload",
        "output-size",
      ]),
    );
    // Generating is never triggered from inside the tour.
    expect(interactive).not.toContain("print-output");
  });

  it("recommend 8 colors, 7 + clear, and 4 colors after the picker opens", () => {
    const palette = TUTORIAL_STEPS.find((step) => step.id === "picker-palette");
    expect(palette?.prepare?.materialPicker).toBe(true);
    const labels = palette?.palettes?.map((item) => item.swatches.map((s) => s.labelKey));
    expect(labels?.[0]).toHaveLength(8);
    expect(labels?.[1]).toContain("tutorial_color_clear");
    expect(labels?.[2]).toHaveLength(4);
  });
});
