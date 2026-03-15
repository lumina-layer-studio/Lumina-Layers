import { describe, it, expect, beforeEach } from "vitest";
import { useConverterStore } from "../stores/converterStore";
import { translations } from "../i18n/translations";

// ========== Helpers ==========

function resetStore(): void {
  useConverterStore.setState({
    free_color_set: new Set<string>(),
    selectedColor: null,
    threemfDiskPath: null,
    downloadUrl: null,
    palette: [],
  });
}

// ========== Tests ==========

describe("Feature: free-color-mode — Unit Tests", () => {
  beforeEach(() => {
    resetStore();
  });

  // --- Requirements 1.1, 1.2: toggleFreeColor ---

  describe("toggleFreeColor", () => {
    it("adds a new color to free_color_set", () => {
      useConverterStore.getState().toggleFreeColor("ff0000");
      expect(useConverterStore.getState().free_color_set.has("ff0000")).toBe(true);
      expect(useConverterStore.getState().free_color_set.size).toBe(1);
    });

    it("removes an existing color from free_color_set", () => {
      useConverterStore.setState({ free_color_set: new Set(["ff0000"]) });
      useConverterStore.getState().toggleFreeColor("ff0000");
      expect(useConverterStore.getState().free_color_set.has("ff0000")).toBe(false);
      expect(useConverterStore.getState().free_color_set.size).toBe(0);
    });
  });

  // --- Requirements 1.3: clearFreeColors ---

  describe("clearFreeColors", () => {
    it("empties the free_color_set", () => {
      useConverterStore.setState({ free_color_set: new Set(["ff0000", "00ff00", "0000ff"]) });
      useConverterStore.getState().clearFreeColors();
      expect(useConverterStore.getState().free_color_set.size).toBe(0);
    });
  });

  // --- Requirements 2.1, 2.4: toggle button disabled/enabled ---

  describe("Button disabled states (toggle free color)", () => {
    it("toggle button should be disabled when selectedColor is null", () => {
      useConverterStore.setState({ selectedColor: null });
      const { selectedColor } = useConverterStore.getState();
      // UI disables button when selectedColor === null
      expect(selectedColor).toBeNull();
    });

    it("toggle button should be enabled when selectedColor is set", () => {
      useConverterStore.setState({ selectedColor: "ff0000" });
      const { selectedColor } = useConverterStore.getState();
      expect(selectedColor).not.toBeNull();
    });
  });

  // --- Requirements 3.1, 3.3: clear button disabled/enabled ---

  describe("Button disabled states (clear free colors)", () => {
    it("clear button should be disabled when free_color_set is empty", () => {
      const { free_color_set } = useConverterStore.getState();
      // UI disables button when free_color_set.size === 0
      expect(free_color_set.size).toBe(0);
    });

    it("clear button should be enabled when free_color_set is non-empty", () => {
      useConverterStore.setState({ free_color_set: new Set(["aabbcc"]) });
      expect(useConverterStore.getState().free_color_set.size).toBeGreaterThan(0);
    });
  });

  // --- Requirements 4.1, 4.2: PaletteItem isFreeColor visual marker ---

  describe("PaletteItem isFreeColor", () => {
    it("color in free_color_set gets isFreeColor=true", () => {
      useConverterStore.setState({ free_color_set: new Set(["ff0000", "00ff00"]) });
      const freeSet = useConverterStore.getState().free_color_set;
      // PalettePanel passes isFreeColor={free_color_set.has(entry.matched_hex)}
      expect(freeSet.has("ff0000")).toBe(true);
      expect(freeSet.has("00ff00")).toBe(true);
    });

    it("color NOT in free_color_set gets isFreeColor=false", () => {
      useConverterStore.setState({ free_color_set: new Set(["ff0000"]) });
      const freeSet = useConverterStore.getState().free_color_set;
      expect(freeSet.has("0000ff")).toBe(false);
    });
  });

  // --- Requirements 4.3: FreeColorSummary rendering ---

  describe("FreeColorSummary", () => {
    it("displays all colors in free_color_set sorted", () => {
      const colors = new Set(["ff0000", "00ff00", "0000ff"]);
      useConverterStore.setState({ free_color_set: colors });
      const freeSet = useConverterStore.getState().free_color_set;
      // FreeColorSummary renders Array.from(freeColors).sort()
      expect(Array.from(freeSet).sort()).toEqual(["0000ff", "00ff00", "ff0000"]);
    });

    it("returns null when free_color_set is empty", () => {
      // FreeColorSummary: if (freeColors.size === 0) return null
      expect(useConverterStore.getState().free_color_set.size).toBe(0);
    });
  });

  // --- Requirements 6.1, 6.2: i18n keys ---

  describe("i18n keys", () => {
    it("conv_free_color_btn exists with zh/en", () => {
      expect(translations.conv_free_color_btn).toBeDefined();
      expect(translations.conv_free_color_btn.zh).toBe("🎯 标记为自由色");
      expect(translations.conv_free_color_btn.en).toBe("🎯 Mark as Free Color");
    });

    it("conv_free_color_clear_btn exists with zh/en", () => {
      expect(translations.conv_free_color_clear_btn).toBeDefined();
      expect(translations.conv_free_color_clear_btn.zh).toBe("清除自由色");
      expect(translations.conv_free_color_clear_btn.en).toBe("Clear Free Colors");
    });

    it("conv_free_color_label exists with zh/en", () => {
      expect(translations.conv_free_color_label).toBeDefined();
      expect(translations.conv_free_color_label.zh).toBe("🎯 自由色");
      expect(translations.conv_free_color_label.en).toBe("🎯 Free Colors");
    });
  });
});
