import { hexToRgb } from "./colorUtils";

export interface CalibrationPreviewInput {
  kind: "materials" | "luts";
  rgb?: unknown;
  mode?: string | null;
  name?: string | null;
  display?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
}

export interface CalibrationPreview {
  kind: "measured" | "illustrative" | "palette" | "unknown" | "lookup";
  black: string[];
  white: string[];
  boardThicknessMm?: number;
  lutBoard?: LutBoardPreview;
  lutVariant?: "cmyw" | "rybw";
}

export interface LutBoardPage {
  number: number; rows: number; cols: number; count: number; padding: number; png: string;
}
export interface LutBoardPreview {
  family: "five" | "eight" | "full" | "board" | "index";
  setSize: number;
  blockFraction?: number;
  pages: LutBoardPage[];
}

const STEPS = 18;
const MAX_PALETTE_CHANNELS = 16;
const neutral = "#9298a0";
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};

function lutBoard(value: unknown): LutBoardPreview | undefined {
  const { family, set_size: setSize, block_fraction: fraction, pages } = record(value);
  if (family !== "five" && family !== "eight" && family !== "full" && family !== "board" && family !== "index") return;
  if (typeof setSize !== "number" || !Number.isInteger(setSize) || setSize < 1 || setSize > 24
    || !Array.isArray(pages) || !pages.length || pages.length > setSize) return;
  const result: LutBoardPage[] = [];
  for (const raw of pages) {
    const { number, rows, cols, padding, count, png } = record(raw);
    if (typeof number !== "number" || !Number.isInteger(number) || number <= (result.at(-1)?.number ?? 0) || number > setSize
      || typeof rows !== "number" || !Number.isInteger(rows) || rows < 1 || rows > 65536
      || typeof cols !== "number" || !Number.isInteger(cols) || cols < 1 || cols > 65536
      || typeof padding !== "number" || !Number.isInteger(padding) || padding < 0 || padding > 8
      || typeof count !== "number" || !Number.isInteger(count) || count < 1 || count > rows * cols
      || typeof png !== "string" || png.length > 16384 || !/^iVBORw0KGgo[A-Za-z0-9+/]+={0,2}$/.test(png)) return;
    result.push({ number, rows, cols, padding, count, png });
  }
  const blockFraction = typeof fraction === "number" && fraction > 0 && fraction < 1 ? fraction : undefined;
  return { family, setSize, blockFraction, pages: result };
}

function colorHex(value: unknown, bgr = false): string | undefined {
  const channels = typeof value === "string" && /^#?[\da-f]{6}$/i.test(value) ? hexToRgb(value) : value;
  if (!Array.isArray(channels) || channels.length !== 3
    || !channels.every((byte) => Number.isInteger(byte) && byte >= 0 && byte <= 255)) return undefined;
  const ordered = bgr ? [channels[2], channels[1], channels[0]] : channels;
  return "#" + ordered.map((byte: number) => byte.toString(16).padStart(2, "0")).join("");
}

// Select source colors, including both endpoints, without interpolating new ones.
function sampleUpTo(colors: string[], limit: number): string[] {
  if (colors.length <= limit) return colors;
  return Array.from({ length: limit }, (_, i) => colors[Math.round(i * (colors.length - 1) / (limit - 1))]);
}

function patches(values: unknown, bgr = false): string[] | undefined {
  if (!Array.isArray(values) || values.length === 0) return undefined;
  const colors = values.map((value) => colorHex(value, bgr));
  return colors.every((color): color is string => color !== undefined) ? colors : undefined;
}

function substrateSamples(value: unknown): CalibrationPreview | undefined {
  const samples = record(value);
  if (samples.source !== undefined && samples.source !== "measured" && samples.source !== "model") return undefined;
  const black = patches(samples.black);
  const white = patches(samples.white);
  if (!black || !white || black.length < 2 || black.length !== white.length) return undefined;
  const depth = samples.board_thickness_mm;
  return {
    kind: samples.source === "model" ? "illustrative" : "measured",
    black: sampleUpTo(black, STEPS), white: sampleUpTo(white, STEPS),
    ...(typeof depth === "number" && depth > 0 && depth <= 34 ? { boardThicknessMm: depth } : {}),
  };
}

// config.py ColorSystem.preview, in the slot order used by each calibration mode.
const white = "#ffffff", black = "#000000", cyan = "#0086d6", magenta = "#ec008c";
const yellow = "#f4ee2a", red = "#dc143c", rybwYellow = "#ffe600", blue = "#0064f0", green = "#00ae42";
const standardModes = {
  BW: [white, black],
  CMYW: [white, cyan, magenta, yellow],
  RYBW: [white, red, rybwYellow, blue],
  CMYWGK: [white, cyan, magenta, green, yellow, black],
  RYBWGK: [white, red, rybwYellow, blue, green, black],
  extended: [white, red, rybwYellow, blue, "#141414"],
  max: [white, cyan, magenta, yellow, black, "#c12e1f", "#0a2989", green],
};

// Native LUTs can identify a channel by name alone. Use only full, known labels.
const channelColors: Record<string, string> = {
  white, black, cyan, magenta, yellow, red, blue, green,
  "deep blue": "#0a2989", "bambu green": green,
  白: white, 黑: black, 青: cyan, 品红: magenta, 黄: yellow, 红: red, 蓝: blue, 绿: green,
  深蓝: "#0a2989", 拓竹绿: green,
};

function namedChannel(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const label = value.trim().toLowerCase().replace(/^slot\s*\d+\s*\(([^()]+)\)$/, "$1").replace(/色$/, "");
  return Object.hasOwn(channelColors, label) ? channelColors[label] : undefined;
}

function channels(value: unknown, order?: unknown): string[] | undefined {
  // Keyed palettes can declare their channel order separately. Otherwise JSON
  // insertion order is the slot order, including when the base is not slot 0.
  const palette = record(value);
  const entries: [string, unknown][] = Array.isArray(order)
    ? order.map((slot) => typeof slot === "string" ? [slot, palette[slot] ?? slot] : ["", slot])
    : value && typeof value === "object" ? Object.entries(value) : [];
  if (!entries.length) return undefined;
  const colors = entries.map(([key, entry]) => {
    const slot = record(entry);
    return colorHex(entry) ?? colorHex(slot.hex_color) ?? colorHex(slot.hex) ?? colorHex(slot.rgb) ?? colorHex(slot.bgr, true)
      ?? namedChannel(slot.color_name) ?? namedChannel(slot.color) ?? namedChannel(entry) ?? namedChannel(key);
  });
  return colors.every((color): color is string => color !== undefined) ? colors : undefined;
}

function modeColors(value: unknown): string[] | undefined {
  if (typeof value !== "string") return undefined;
  const label = value.normalize("NFKC").toUpperCase();
  if (/MERGED|合并/.test(label)) return undefined;
  const codes = [...label.matchAll(/(?<![A-Z])(CMYWGK|RYBWGK|CMYW|RYBW|BW)(?![A-Z])/g)].map(([code]) => code);
  if (new Set(codes).size > 1) return undefined;
  const code = codes[0] as keyof typeof standardModes | undefined;
  if (code) {
    if (/6\s*[-_ ]?\s*(?:COLORS?|色)/.test(label) && (code === "RYBW" || code === "CMYW")) {
      return standardModes[code === "RYBW" ? "RYBWGK" : "CMYWGK"];
    }
    return standardModes[code];
  }
  if (/^5[-_ ]COLOR[-_ ]EXTENDED(?:\s*\(1444\))?$/.test(label.trim())) return standardModes.extended;
  if (/^8[-_ ]COLOR[-_ ]MAX$/.test(label.trim())) return standardModes.max;
  return undefined;
}

function identicalRows(kind: "illustrative" | "palette" | "unknown", colors: string[]): CalibrationPreview {
  // Ordinary LUTs display every channel. Large custom palettes show up to 16
  // representative slots in their original order, retaining both endpoints.
  const samples = sampleUpTo(colors, MAX_PALETTE_CHANNELS);
  return { kind, black: samples, white: samples };
}

export function calibrationPreview(input: CalibrationPreviewInput): CalibrationPreview {
  const display = input.display ?? {};
  const metadata = input.metadata ?? {};
  if (input.kind === "materials") {
    const samples = substrateSamples(display.preview_swatches) ?? substrateSamples(metadata.preview_swatches);
    if (samples) return samples;
    const rgb = colorHex(input.rgb) ?? colorHex(display.estimated_rgb) ?? colorHex(display.rgb);
    if (rgb) return identicalRows("illustrative", [rgb]);
  } else {
    const palette = patches(display.palette_rgb) ?? patches(metadata.palette_rgb)
      ?? patches(display.palette_bgr, true) ?? patches(metadata.palette_bgr, true)
      ?? channels(metadata.palette, metadata.ordered_channels) ?? channels(display.palette, display.ordered_channels)
      ?? channels(metadata.channels) ?? channels(display.channels);
    const board = lutBoard(display.lut_board_preview) ?? lutBoard(metadata.lut_board_preview);
    const fromMode = modeColors(metadata.color_mode) ?? modeColors(display.color_mode) ?? modeColors(input.mode)
      ?? modeColors(input.name) ?? modeColors(display.name);
    if (board) {
      const lutVariant = fromMode === standardModes.CMYW || fromMode === standardModes.CMYWGK ? "cmyw"
        : fromMode === standardModes.RYBW || fromMode === standardModes.RYBWGK ? "rybw" : undefined;
      const count = board.pages[0].count;
      let template = fromMode;
      if (board.family === "five") template = standardModes.extended;
      else if (board.family === "eight" || board.family === "full") template = standardModes.max;
      else if (board.family === "board" && count === 32) template = standardModes.BW;
      else if (board.family === "board" && count === 1296 && lutVariant) {
        template = lutVariant === "rybw" ? standardModes.RYBWGK : standardModes.CMYWGK;
      }
      return { kind: "lookup", black: palette ?? template ?? [], white: [], lutBoard: board, lutVariant };
    }
    const slots = palette ?? fromMode;
    if (slots) return identicalRows("palette", slots);
  }
  return identicalRows("unknown", [neutral]);
}
