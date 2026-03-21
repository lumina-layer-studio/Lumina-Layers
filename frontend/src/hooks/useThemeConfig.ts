import { useSettingsStore } from "../stores/settingsStore";
import { THEME_CONFIG, type ThemeColors } from "../components/themeConfig";

/**
 * Returns the ThemeColors object for the current theme mode.
 * 根据当前主题模式返回对应的 ThemeColors 配置对象。
 *
 * Reads the active theme from settingsStore and resolves it
 * against THEME_CONFIG. Non-"dark" values fall back to light.
 *
 * @returns {ThemeColors} Visual parameters for the active theme.
 *   (当前激活主题的视觉参数)
 */
export function useThemeConfig(): ThemeColors {
  const theme = useSettingsStore((s) => s.theme);
  return theme === "dark" ? THEME_CONFIG.dark : THEME_CONFIG.light;
}
