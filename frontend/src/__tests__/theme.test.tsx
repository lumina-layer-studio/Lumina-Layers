import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { renderHook, act } from "@testing-library/react";
import { ThemeToggle } from "../components/ThemeToggle";
import { useThemeConfig } from "../hooks/useThemeConfig";
import { THEME_CONFIG } from "../components/themeConfig";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";

// ========== Setup ==========

beforeEach(() => {
  // Reset store to defaults before each test
  useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  // Clean up dark class from documentElement
  document.documentElement.classList.remove("dark");
});

// ========== ThemeToggle Component Tests ==========

describe("ThemeToggle", () => {
  it("renders moon icon (🌙) in light mode", () => {
    useSettingsStore.setState({ theme: "light" });
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Toggle theme" })).toHaveTextContent("🌙");
  });

  it("renders sun icon (☀️) in dark mode", () => {
    useSettingsStore.setState({ theme: "dark" });
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Toggle theme" })).toHaveTextContent("☀️");
  });

  it("toggles theme from light to dark on click", () => {
    useSettingsStore.setState({ theme: "light" });
    render(<ThemeToggle />);

    const button = screen.getByRole("button", { name: "Toggle theme" });
    fireEvent.click(button);

    expect(useSettingsStore.getState().theme).toBe("dark");
  });
});

// ========== useThemeConfig Hook Tests ==========

describe("useThemeConfig", () => {
  it("returns THEME_CONFIG.light when theme is 'light'", () => {
    useSettingsStore.setState({ theme: "light" });
    const { result } = renderHook(() => useThemeConfig());
    expect(result.current).toEqual(THEME_CONFIG.light);
  });

  it("returns THEME_CONFIG.dark when theme is 'dark'", () => {
    useSettingsStore.setState({ theme: "dark" });
    const { result } = renderHook(() => useThemeConfig());
    expect(result.current).toEqual(THEME_CONFIG.dark);
  });

  it("updates when store theme changes", () => {
    useSettingsStore.setState({ theme: "light" });
    const { result } = renderHook(() => useThemeConfig());

    expect(result.current).toEqual(THEME_CONFIG.light);

    act(() => {
      useSettingsStore.getState().setTheme("dark");
    });

    expect(result.current).toEqual(THEME_CONFIG.dark);
  });
});

// ========== Default Theme Tests ==========

describe("Default theme", () => {
  it("DEFAULT_SETTINGS.theme is 'light'", () => {
    expect(DEFAULT_SETTINGS.theme).toBe("light");
  });
});
