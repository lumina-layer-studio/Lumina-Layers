import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { THEME_CONFIG } from "../components/themeConfig";
import type { ThemeColors } from "../components/themeConfig";

// Feature: dark-light-mode, Property 1: 主题配置结构完整性

// ========== Helpers ==========

/** All expected keys in ThemeColors. (ThemeColors 接口的所有预期字段) */
const STRING_FIELDS: (keyof ThemeColors)[] = [
  "canvasClearColor",
  "keyLightColor",
  "bedBase",
  "bedInner",
  "bedFineGrid",
  "bedBoldGrid",
  "bedBorder",
];

const NUMBER_FIELDS: (keyof ThemeColors)[] = [
  "environmentIntensity",
  "keyLightIntensity",
];

const ALL_FIELDS = [...STRING_FIELDS, ...NUMBER_FIELDS];

// ========== Generators ==========

const arbThemeMode = fc.constantFrom<"light" | "dark">("light", "dark");

// ========== Property 1: 主题配置结构完整性 ==========

// **Validates: Requirements 1.1**
describe("Feature: dark-light-mode, Property 1: 主题配置结构完整性", () => {
  it("every field in THEME_CONFIG[mode] is defined and non-null", () => {
    fc.assert(
      fc.property(arbThemeMode, (mode) => {
        const config = THEME_CONFIG[mode];
        for (const field of ALL_FIELDS) {
          expect(config[field]).toBeDefined();
          expect(config[field]).not.toBeNull();
        }
      }),
      { numRuns: 100 }
    );
  });

  it("light and dark configs have the exact same set of keys", () => {
    fc.assert(
      fc.property(arbThemeMode, (_mode) => {
        const lightKeys = Object.keys(THEME_CONFIG.light).sort();
        const darkKeys = Object.keys(THEME_CONFIG.dark).sort();
        expect(lightKeys).toEqual(darkKeys);
      }),
      { numRuns: 100 }
    );
  });

  it("string fields are non-empty strings", () => {
    fc.assert(
      fc.property(arbThemeMode, (mode) => {
        const config = THEME_CONFIG[mode];
        for (const field of STRING_FIELDS) {
          const value = config[field];
          expect(typeof value).toBe("string");
          expect((value as string).length).toBeGreaterThan(0);
        }
      }),
      { numRuns: 100 }
    );
  });

  it("number fields are positive numbers", () => {
    fc.assert(
      fc.property(arbThemeMode, (mode) => {
        const config = THEME_CONFIG[mode];
        for (const field of NUMBER_FIELDS) {
          const value = config[field];
          expect(typeof value).toBe("number");
          expect(value).toBeGreaterThan(0);
        }
      }),
      { numRuns: 100 }
    );
  });
});

// Feature: dark-light-mode, Property 2: 主题切换双重切换恒等性

// ========== Helpers ==========

/** Pure toggle function. (纯主题切换函数) */
const toggle = (t: "light" | "dark"): "light" | "dark" =>
  t === "light" ? "dark" : "light";

// ========== Property 2: 主题切换双重切换恒等性 ==========

// **Validates: Requirements 2.3**
describe("Feature: dark-light-mode, Property 2: 主题切换双重切换恒等性", () => {
  it("toggle(toggle(theme)) === theme for any initial theme", () => {
    fc.assert(
      fc.property(
        fc.constantFrom<"light" | "dark">("light", "dark"),
        (theme) => {
          expect(toggle(toggle(theme))).toBe(theme);
        }
      ),
      { numRuns: 100 }
    );
  });
});

// Feature: dark-light-mode, Property 3: 主题持久化 Round-Trip

import { beforeEach } from "vitest";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";

// ========== Property 3: 主题持久化 Round-Trip ==========

// **Validates: Requirements 8.1**
describe("Feature: dark-light-mode, Property 3: 主题持久化 Round-Trip", () => {
  beforeEach(() => {
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  });

  it("writing a theme to Settings_Store then reading it back yields the same value", () => {
    fc.assert(
      fc.property(
        fc.constantFrom<"light" | "dark">("light", "dark"),
        (theme) => {
          useSettingsStore.getState().setTheme(theme);
          expect(useSettingsStore.getState().theme).toBe(theme);
        }
      ),
      { numRuns: 100 }
    );
  });
});
