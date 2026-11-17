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
  /** Low-contrast build-plate branding color (热床低对比品牌标识色) */
  bedBrand: string;
  /** Neutral model body color in the model-surface workflow (覆面模型本体中性色) */
  modelSurfaceBody: string;
  /** Large-format tile cut line; bright so it reads on dark artwork (大画幅切割线色) */
  largeFormatTileOutline: string;
  /** Halo under the cut line so it reads on light artwork (大画幅切割线描边色) */
  largeFormatTileOutlineHalo: string;
}

/** Color roles used by the virtual printer bed. (虚拟打印热床使用的颜色角色) */
export type BedSurfaceColors = Pick<
  ThemeColors,
  | "bedBase"
  | "bedInner"
  | "bedFineGrid"
  | "bedBoldGrid"
  | "bedBorder"
  | "bedBrand"
>;

type BedPaletteFamily =
  | "generic"
  | "bambu-a"
  | "bambu-p"
  | "bambu-x"
  | "bambu-h"
  | "snapmaker"
  | "elegoo"
  | "anycubic"
  | "flashforge"
  | "qidi";

type BuildPlatePaletteFamily =
  | "generic"
  | "cool"
  | "engineering"
  | "high-temp"
  | "textured-pei"
  | "textured-cool"
  | "supertack";

const BED_FAMILY_ACCENTS: Record<Exclude<BedPaletteFamily, "generic">, string> = {
  "bambu-a": "#00ae42",
  "bambu-p": "#00977a",
  "bambu-x": "#0b8293",
  "bambu-h": "#168763",
  snapmaker: "#1769d2",
  elegoo: "#5555f5",
  anycubic: "#005cff",
  flashforge: "#2299cc",
  qidi: "#7c3aed",
};

const BUILD_PLATE_ACCENTS: Record<
  Exclude<BuildPlatePaletteFamily, "generic">,
  string
> = {
  cool: "#2f9eca",
  engineering: "#c47f28",
  "high-temp": "#7b8797",
  "textured-pei": "#8f7749",
  "textured-cool": "#397ca8",
  supertack: "#35a86a",
};

/**
 * Centralized theme configuration for light and dark modes.
 * 日间和夜间模式的集中式主题配置。
 */
export const THEME_CONFIG: Record<"light" | "dark", ThemeColors> = {
  light: {
    canvasClearColor: "#e8e8ec",
    environmentIntensity: 1.0,
    keyLightIntensity: 0.8,
    keyLightColor: "#ffffff",
    bedBase: "#aeb4bd",
    bedInner: "#d4d8de",
    bedFineGrid: "#b7bec8",
    bedBoldGrid: "#7d8794",
    bedBorder: "#9da6b1",
    bedBrand: "#606b78",
    modelSurfaceBody: "#a8b4c4",
    largeFormatTileOutline: "#f59e0b",
    largeFormatTileOutlineHalo: "#0f172a",
  },
  dark: {
    canvasClearColor: "#1e1e26",
    environmentIntensity: 1.0,
    keyLightIntensity: 0.8,
    keyLightColor: "#ffffff",
    bedBase: "#1d222b",
    bedInner: "#303640",
    bedFineGrid: "#4a5360",
    bedBoldGrid: "#697482",
    bedBorder: "#171b22",
    bedBrand: "#9ba6b4",
    modelSurfaceBody: "#64748b",
    largeFormatTileOutline: "#f59e0b",
    largeFormatTileOutlineHalo: "#0f172a",
  },
};

function mixHexColors(baseHex: string, accentHex: string, amount: number): string {
  const clampedAmount = Math.min(1, Math.max(0, amount));
  const channels = [1, 3, 5].map((offset) => {
    const base = Number.parseInt(baseHex.slice(offset, offset + 2), 16);
    const accent = Number.parseInt(accentHex.slice(offset, offset + 2), 16);
    return Math.round(base + (accent - base) * clampedAmount)
      .toString(16)
      .padStart(2, "0");
  });
  return `#${channels.join("")}`;
}

function resolveBedPaletteFamily(
  printerId?: string | null,
  bedLabel: string = "",
): BedPaletteFamily {
  const identity = `${printerId ?? ""} ${bedLabel}`.toLowerCase();

  if (identity.includes("bambu")) {
    if (/\b(?:p1p|p1s|p2s)\b/.test(identity)) return "bambu-p";
    if (/\b(?:x1c|x1e|x2d)\b/.test(identity)) return "bambu-x";
    if (/\b(?:h2c|h2d|h2s|h3c)\b/.test(identity)) return "bambu-h";
    return "bambu-a";
  }
  if (identity.includes("snapmaker")) return "snapmaker";
  if (identity.includes("elegoo")) return "elegoo";
  if (identity.includes("anycubic")) return "anycubic";
  if (identity.includes("flashforge")) return "flashforge";
  if (identity.includes("qidi")) return "qidi";
  return "generic";
}

function resolveBuildPlatePaletteFamily(
  buildPlateId?: string | null,
): BuildPlatePaletteFamily {
  switch (buildPlateId?.toLowerCase()) {
    case "cool-plate":
    case "smooth-cool-plate":
      return "cool";
    case "engineering-plate":
      return "engineering";
    case "smooth-pei-plate":
    case "smooth-high-temp-plate":
      return "high-temp";
    case "textured-pei-plate":
      return "textured-pei";
    case "textured-cool-plate":
      return "textured-cool";
    case "supertack-plate":
      return "supertack";
    default:
      return "generic";
  }
}

function tintBedColors(
  colors: BedSurfaceColors,
  accent: string,
  strengths: {
    base: number;
    inner: number;
    fine: number;
    bold: number;
    border: number;
    brand: number;
  },
): BedSurfaceColors {
  return {
    bedBase: mixHexColors(colors.bedBase, accent, strengths.base),
    bedInner: mixHexColors(colors.bedInner, accent, strengths.inner),
    bedFineGrid: mixHexColors(colors.bedFineGrid, accent, strengths.fine),
    bedBoldGrid: mixHexColors(colors.bedBoldGrid, accent, strengths.bold),
    bedBorder: mixHexColors(colors.bedBorder, accent, strengths.border),
    bedBrand: mixHexColors(colors.bedBrand, accent, strengths.brand),
  };
}

function getNeutralBedColors(theme: "light" | "dark"): BedSurfaceColors {
  const {
    bedBase,
    bedInner,
    bedFineGrid,
    bedBoldGrid,
    bedBorder,
    bedBrand,
  } = THEME_CONFIG[theme];
  return {
    bedBase,
    bedInner,
    bedFineGrid,
    bedBoldGrid,
    bedBorder,
    bedBrand,
  };
}

/**
 * Resolve a material-led palette, using machine tint only without plate identity.
 * 以打印板材质为主；仅在没有板材标识时加入克制的机器系列色。
 */
export function resolveBedPlatformColors(
  theme: "light" | "dark",
  printerId?: string | null,
  bedLabel: string = "",
  buildPlateId?: string | null,
): BedSurfaceColors {
  const neutral = getNeutralBedColors(theme);
  const plateFamily = resolveBuildPlatePaletteFamily(buildPlateId);
  const family = resolveBedPaletteFamily(printerId, bedLabel);

  if (plateFamily === "generic") {
    if (family === "generic") return neutral;

    const familyStrengths =
      theme === "light"
        ? {
            base: 0.1,
            inner: 0.035,
            fine: 0.18,
            bold: 0.34,
            border: 0.2,
            brand: 0.4,
          }
        : {
            base: 0.08,
            inner: 0.05,
            fine: 0.16,
            bold: 0.3,
            border: 0.14,
            brand: 0.34,
          };
    return tintBedColors(neutral, BED_FAMILY_ACCENTS[family], familyStrengths);
  }

  const plateStrengths =
    theme === "light"
      ? {
          base: 0.17,
          inner: 0.11,
          fine: 0.28,
          bold: 0.58,
          border: 0.4,
          brand: 0.5,
        }
      : {
          base: 0.14,
          inner: 0.13,
          fine: 0.26,
          bold: 0.52,
          border: 0.34,
          brand: 0.46,
        };
  const plateColors = tintBedColors(
    neutral,
    BUILD_PLATE_ACCENTS[plateFamily],
    plateStrengths,
  );

  return plateColors;
}
