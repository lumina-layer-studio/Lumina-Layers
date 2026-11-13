import type { PaletteEntry, ColorReplacementItem, LutColorEntry } from '../api/types';

/**
 * 计算 RGB 颜色的感知亮度 (ITU-R BT.601)。
 * @param hex - 6 位 hex 颜色字符串（无 # 前缀）
 * @returns 亮度值 0-255
 */
export function hexToLuminance(hex: string): number {
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

/**
 * 根据调色板颜色亮度自动分配浮雕高度。
 * @param palette - 调色板条目列表
 * @param mode - 自动高度模式 ('darker-higher' or 'lighter-higher')
 * @param maxHeight - 最大高度 (mm)
 * @param minHeight - 最小高度 (mm)，默认 0.08
 * @returns color_height_map { hex: heightMm }
 */
export function computeAutoHeightMap(
  palette: PaletteEntry[],
  mode: 'darker-higher' | 'lighter-higher',
  maxHeight: number,
  minHeight: number = 0.08,
): Record<string, number> {
  const result: Record<string, number> = {};
  const range = maxHeight - minHeight;

  for (const entry of palette) {
    const lum = hexToLuminance(entry.matched_hex);
    const ratio = lum / 255;

    if (mode === 'darker-higher') {
      // luminance 0 → maxHeight, luminance 255 → minHeight
      result[entry.matched_hex] = maxHeight - ratio * range;
    } else {
      // luminance 0 → minHeight, luminance 255 → maxHeight
      result[entry.matched_hex] = minHeight + ratio * range;
    }
  }

  return result;
}

/**
 * Convert UI relief-extra heights into backend absolute model heights.
 * 将界面中的“额外浮雕高度”转换为后端需要的“底板 + 浮雕”总高度。
 *
 * @param map - UI/store relief-extra height map. (界面或 store 中的额外浮雕高度映射)
 * @param spacerThick - Base spacer thickness in millimetres. (底板厚度，单位 mm)
 * @returns New map with spacer thickness added to each value. (每个值都加上底板厚度的新映射)
 */
export function toAbsoluteReliefHeightMap(
  map: Record<string, number>,
  spacerThick: number,
): Record<string, number> {
  const result: Record<string, number> = {};
  for (const [hex, reliefExtra] of Object.entries(map)) {
    result[hex] = spacerThick + reliefExtra;
  }
  return result;
}

/**
 * 将前端 colorRemapMap 转换为后端 replacement_regions 格式。
 * @param remapMap - 前端颜色替换映射 { origHex: newHex }，origHex 是 matched_hex
 * @param palette - 调色板条目
 * @returns ColorReplacementItem[] 后端格式（hex 值带 # 前缀）
 */
export function colorRemapToReplacementRegions(
  remapMap: Record<string, string>,
  palette: PaletteEntry[],
  saved: ColorReplacementItem[] = [],
): ColorReplacementItem[] {
  const result: ColorReplacementItem[] = [];

  for (const [origHex, newHex] of Object.entries(remapMap)) {
    const entry = palette.find((p) => p.matched_hex === origHex);
    const source = origHex.replace(/^#/, "").toLowerCase();
    let savedEntry: ColorReplacementItem | undefined;
    for (let index = saved.length - 1; index >= 0; index--) {
      if (saved[index].matched_hex.replace(/^#/, "").toLowerCase() === source) {
        savedEntry = saved[index];
        break;
      }
    }

    const scope = savedEntry?.source_scope;
    // Backend expects #rrggbb format per API contract
    const ensureHash = (h: string) => (h.startsWith('#') ? h : `#${h}`);

    result.push({
      quantized_hex: ensureHash(scope ? savedEntry!.quantized_hex : entry?.quantized_hex ?? origHex),
      matched_hex: ensureHash(entry?.matched_hex ?? origHex),
      replacement_hex: ensureHash(newHex),
      ...(scope ? { source_scope: scope } : {}),
    });
  }

  return result;
}

/**
 * Convert a 6-digit hex string to an [R, G, B] tuple.
 * 将 6 位 hex 字符串转换为 [R, G, B] 数组。
 *
 * @param hex - Hex color string, with or without '#' prefix. (带或不带 # 前缀的 hex 颜色字符串)
 * @returns [R, G, B] tuple with values 0-255. (0-255 范围的 RGB 元组)
 */
export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.startsWith('#') ? hex.slice(1) : hex;
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

/**
 * Compute the Euclidean distance between two RGB colors.
 * 计算两个 RGB 颜色之间的欧氏距离。
 *
 * @param a - First RGB color. (第一个 RGB 颜色)
 * @param b - Second RGB color. (第二个 RGB 颜色)
 * @returns Euclidean distance (0 to ~441.67). (欧氏距离)
 */
export function rgbEuclideanDistance(
  a: [number, number, number],
  b: [number, number, number],
): number {
  return Math.sqrt(
    (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2,
  );
}

/**
 * Sort LUT colors by RGB Euclidean distance to a base color and return the top K.
 * 按 RGB 欧氏距离对 LUT 颜色排序，返回前 topK 个。
 *
 * @param baseRgb - Reference RGB color to measure distance from. (基准 RGB 颜色)
 * @param colors - Array of LUT color entries. (LUT 颜色条目数组)
 * @param topK - Number of closest colors to return. (返回最近的颜色数量)
 * @returns Sorted slice of the closest LutColorEntry items. (按距离排序的最近颜色切片)
 */
export function sortByColorDistance(
  baseRgb: [number, number, number],
  colors: LutColorEntry[],
  topK: number,
): LutColorEntry[] {
  return [...colors]
    .sort(
      (a, b) =>
        rgbEuclideanDistance(baseRgb, a.rgb) -
        rgbEuclideanDistance(baseRgb, b.rgb),
    )
    .slice(0, topK);
}

// ==================== sRGB ↔ CIE Lab (D65) ====================
// 采用 D65 白点与标准 sRGB 伽马，参考 https://www.easyrgb.com/en/math.php。
// sRGB ↔ CIE Lab (D65) conversions following EasyRGB's reference formulas.

const D65_REF_WHITE: readonly [number, number, number] = [
  95.047,
  100.0,
  108.883,
];

function pivotEncode(t: number): number {
  return t > 0.008856 ? Math.cbrt(t) : (7.787 * t) + 16 / 116;
}

function pivotDecode(t: number): number {
  const t3 = t * t * t;
  return t3 > 0.008856 ? t3 : (t - 16 / 116) / 7.787;
}

function srgbToLinear(channel: number): number {
  const c = channel / 255;
  return c > 0.04045 ? Math.pow((c + 0.055) / 1.055, 2.4) : c / 12.92;
}

function linearToSrgb(channel: number): number {
  const c =
    channel > 0.0031308
      ? 1.055 * Math.pow(channel, 1 / 2.4) - 0.055
      : 12.92 * channel;
  return Math.max(0, Math.min(255, Math.round(c * 255)));
}

/**
 * Convert an sRGB triple (0-255) to CIE Lab under D65.
 * sRGB (0-255) 转 CIE Lab (D65)。
 */
export function rgbToLab(
  rgb: readonly [number, number, number],
): [number, number, number] {
  const [r, g, b] = rgb.map(srgbToLinear) as [number, number, number];
  // sRGB → XYZ (D65)
  const x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) * 100;
  const y = (r * 0.2126729 + g * 0.7151522 + b * 0.072175) * 100;
  const z = (r * 0.0193339 + g * 0.119192 + b * 0.9503041) * 100;
  const [xr, yr, zr] = [
    x / D65_REF_WHITE[0],
    y / D65_REF_WHITE[1],
    z / D65_REF_WHITE[2],
  ];
  const fx = pivotEncode(xr);
  const fy = pivotEncode(yr);
  const fz = pivotEncode(zr);
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

/**
 * Convert CIE Lab (D65) back to an sRGB triple (0-255).
 * CIE Lab (D65) 转 sRGB (0-255)，结果已 clamp 到 [0,255] 并取整。
 */
export function labToRgb(
  lab: readonly [number, number, number],
): [number, number, number] {
  const [l, a, b] = lab;
  const fy = (l + 16) / 116;
  const fx = a / 500 + fy;
  const fz = fy - b / 200;
  const xr = pivotDecode(fx);
  const yr = pivotDecode(fy);
  const zr = pivotDecode(fz);
  const x = (xr * D65_REF_WHITE[0]) / 100;
  const y = (yr * D65_REF_WHITE[1]) / 100;
  const z = (zr * D65_REF_WHITE[2]) / 100;
  // XYZ → linear sRGB
  const r = x * 3.2404542 + y * -1.5371385 + z * -0.4985314;
  const g = x * -0.969266 + y * 1.8760108 + z * 0.041556;
  const bl = x * 0.0556434 + y * -0.2040259 + z * 1.0572252;
  return [linearToSrgb(r), linearToSrgb(g), linearToSrgb(bl)];
}

/**
 * Convert a hex string (with or without '#') to CIE Lab (D65).
 * hex 字符串转 CIE Lab (D65)。
 */
export function hexToLab(hex: string): [number, number, number] {
  return rgbToLab(hexToRgb(hex));
}

/**
 * Convert CIE Lab (D65) back to a hex string with leading '#'.
 * CIE Lab 转带 "#" 前缀的 hex 字符串。
 */
export function labToHex(lab: readonly [number, number, number]): string {
  const [r, g, b] = labToRgb(lab);
  const toHex = (n: number) => n.toString(16).padStart(2, "0").toUpperCase();
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}
