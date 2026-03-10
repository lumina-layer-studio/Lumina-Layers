/**
 * Theme configuration for light and dark modes.
 * 日间/夜间模式的主题配置。
 *
 * Centralizes all visual parameters for 3D scene, lighting, and bed platform
 * so that theme switching is driven by a single source of truth.
 */

/** Visual parameters for a single theme mode. (单一主题模式的视觉参数) */
export interface ThemeColors {
  /** Canvas clear color (Canvas 清除色) */
  canvasClearColor: string;
  /** Environment light intensity (环境光强度) */
  environmentIntensity: number;
  /** Key light intensity (方向光强度) */
  keyLightIntensity: number;
  /** Key light color (方向光颜色) */
  keyLightColor: string;
  /** Bed base color (热床底色) */
  bedBase: string;
  /** Bed inner area color (热床内区色) */
  bedInner: string;
  /** Bed fine grid color (热床细网格色) */
  bedFineGrid: string;
  /** Bed bold grid color (热床粗网格色) */
  bedBoldGrid: string;
  /** Bed border color (热床边框色) */
  bedBorder: string;
}

/**
 * Centralized theme configuration for light and dark modes.
 * 日间和夜间模式的集中式主题配置。
 */
export const THEME_CONFIG: Record<"light" | "dark", ThemeColors> = {
  light: {
    canvasClearColor: "#e8e8ec",
    environmentIntensity: 1.2,
    keyLightIntensity: 0.8,
    keyLightColor: "#ffffff",
    bedBase: "#d8d8dc",
    bedInner: "#e8e8ec",
    bedFineGrid: "#d0d0d4",
    bedBoldGrid: "#b0b0b8",
    bedBorder: "#c0c0c8",
  },
  dark: {
    canvasClearColor: "#1e1e26",
    environmentIntensity: 0.8,
    keyLightIntensity: 0.5,
    keyLightColor: "#ffffff",
    bedBase: "#26262c",
    bedInner: "#3a3a42",
    bedFineGrid: "#2a2a30",
    bedBoldGrid: "#5a5a64",
    bedBorder: "#2d2d34",
  },
};
