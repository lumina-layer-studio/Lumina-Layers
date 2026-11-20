import type { CalibrationPreviewInput } from "./calibrationPreview";
import type { FilamentIdentity } from "./filamentIdentity";
import { translations } from "../i18n/translations";

const text = (value: unknown) => typeof value === "string" ? value.trim() : "";
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const legacyGrade = /^(?:PLA|PETG|ABS|ASA|TPU)(?:\+|[- ]?(?:Basic|GO|HF|Matte|Pro))?$/i;
const legacyCode = /^(CMYWGK|RYBWGK|CMYW|RYBW|BW)(?:-(.+))?$/i;
const legacyCount = /^(\d+)(?:色|colou?rs?)/i;
const colorToken = "[深浅]?(?:品红|红|黄|蓝|白|黑|绿|青)";
function completeColorNames(field: string): string[] | undefined {
  const raw = field.replace(/-\d{8}$/, "");
  if (!new RegExp(`^(?:${colorToken})(?:[- ]?(?:${colorToken})){1,15}$`).test(raw)) return;
  return raw.match(new RegExp(colorToken, "g")) ?? undefined;
}

export function resourceColorMode(mode: string | null | undefined, language: "zh" | "en"): string {
  const raw = mode?.trim() ?? "";
  if (/^unknown$/i.test(raw)) return translations.lut_library_unknown[language];
  const match = raw.match(/^(\d+)[ -]?colou?rs?((?:\s.*|[-_].*)?)$/i);
  return match ? translations.resources_color_count[language].replace("{count}", match[1]) + match[2] : raw;
}

export function lutDisplayIdentity(identity: FilamentIdentity, language: "zh" | "en"): FilamentIdentity {
  if (identity.name !== identity.originalName || !identity.name.includes("&")) return identity;
  const tokens = identity.name.split("&").map((token) => token.trim()).filter(Boolean);
  // Only canonical legacy filename fields qualify. Custom titles keep their wording.
  let grade: string | undefined, code: string | undefined, count: string | undefined;
  const recognized = tokens.slice(1).every((raw) => {
    if (/^\d{8}$/.test(raw)) return true;
    const numbered = raw.match(legacyCount);
    if (numbered) count = numbered[1];
    const field = raw.replace(legacyCount, "");
    if (!field && numbered) return true;
    if (legacyGrade.test(field)) { grade = field; return true; }
    const coded = field.match(legacyCode);
    if (coded && (!coded[2] || completeColorNames(coded[2]))) { code = coded[1]; return true; }
    return Boolean(completeColorNames(field));
  });
  if (!grade || !recognized || (!code && !count)) return identity;
  return { ...identity, materialType: identity.materialType || grade,
    name: [grade, code?.toUpperCase() ?? translations.resources_color_count[language].replace("{count}", count!)].join(" · ") };
}

const colors: Record<string, [string, string, string]> = {
  W: ["白", "White", "#ffffff"], K: ["黑", "Black", "#222222"],
  R: ["红", "Red", "#dc143c"], Y: ["黄", "Yellow", "#ffe600"],
  B: ["蓝", "Blue", "#0064f0"], G: ["绿", "Green", "#00ae42"],
  C: ["青", "Cyan", "#0086d6"], M: ["品红", "Magenta", "#ec008c"],
};
function namedColor(label: string, language: "zh" | "en"): ResourceColor | undefined {
  const value = label.trim().replace(/色$/, "").toLowerCase();
  const entry = Object.values(colors).find(([zh, en]) => zh === value || en.toLowerCase() === value);
  return entry ? { label: entry[language === "zh" ? 0 : 1], hex: entry[2] } : undefined;
}
export interface ResourceColor { label: string; hex?: string }
export function resourceFilaments(input: CalibrationPreviewInput): Record<string, unknown>[] {
  const rows = input.display?.filaments ?? input.metadata?.filaments;
  if (!Array.isArray(rows) || !rows.length || rows.length > 16 || !rows.every((entry) => Object.keys(record(entry)).length)) return [];
  const values = rows.map(record);
  const slots = values.map((row) => row.slot);
  return slots.every((slot) => Number.isInteger(slot) && Number(slot) >= 0 && Number(slot) < values.length)
    && new Set(slots).size === values.length
    ? [...values].sort((a, b) => Number(a.slot) - Number(b.slot)) : values;
}
function rgbHex(value: unknown, bgr = false): string | undefined {
  if (typeof value === "string" && /^#?[\da-f]{6}$/i.test(value)) return "#" + value.replace(/^#/, "");
  if (!Array.isArray(value) || value.length !== 3 || !value.every((v) => Number.isInteger(v) && v >= 0 && v <= 255)) return;
  return "#" + (bgr ? [...value].reverse() : value).map((v) => v.toString(16).padStart(2, "0")).join("");
}

/** Declared channels only; calibration-board pixels are never material identities. */
export function resourceColors(input: CalibrationPreviewInput, language: "zh" | "en"): ResourceColor[] {
  if (input.kind !== "luts") return [];
  const display = input.display ?? {}, metadata = input.metadata ?? {};
  const channelName = (index: number) => translations.resources_channel_name[language].replace("{number}", String(index + 1));
  const filaments = resourceFilaments(input);
  if (filaments.length) {
    return filaments.map((slot, index) => {
      return { label: text(slot.color_name) || text(slot.material_name) || channelName(index),
        hex: rgbHex(slot.color_hex ?? slot.rgb) };
    });
  }
  for (const data of [metadata, display]) {
    const palette = data.palette ?? data.channels;
    const entries: [string, unknown][] = Array.isArray(data.ordered_channels)
      ? data.ordered_channels.map((slot) => [typeof slot === "string" ? slot : "", typeof slot === "string" ? record(palette)[slot] ?? slot : slot])
      : palette && typeof palette === "object" ? Object.entries(palette) : [];
    if (entries.length && entries.length <= 16) return entries.map(([key, value], i) => {
      const slot = record(value);
      const label = text(slot.color_name) || text(slot.name) || text(slot.color) || (typeof value === "string" && !rgbHex(value) ? value : "")
        || (!/^\d+$/.test(key) ? key : "") || channelName(i);
      const named = namedColor(label, language);
      return { label: named?.label ?? label, hex: rgbHex(slot.hex_color ?? slot.hex ?? slot.rgb ?? value) ?? rgbHex(slot.bgr, true) ?? named?.hex };
    });
    const rgb = data.palette_rgb ?? data.palette_bgr;
    if (Array.isArray(rgb) && rgb.length && rgb.length <= 16 && rgb.every((value) => rgbHex(value))) {
      return rgb.map((value, index) => ({
        label: channelName(index),
        hex: rgbHex(value, data.palette_rgb === undefined),
      }));
    }
  }
  // Legacy filenames may explicitly declare a named set. These are color labels,
  // not measured filament RGB or a guessed manufacturer product.
  const names = [input.name, display.name].map(text);
  const declaration = names.join(" ");
  const mode = [input.mode, metadata.color_mode, display.color_mode, declaration].map(text).join(" ");
  if (/merged|合并/i.test(mode)) return [];
  const expectedCount = text(input.mode ?? metadata.color_mode ?? display.color_mode).match(/^(\d+)(?:[ -]?colou?r|色)/i)?.[1];
  const labels = names.flatMap((name) => name.split("&")).map((field) => {
    const withoutMode = field.trim().replace(legacyCount, "")
      .replace(/^(?:PLA|PETG|ABS|ASA|TPU)[- ]/, "");
    const coded = withoutMode.match(legacyCode);
    return completeColorNames(coded?.[2] ?? withoutMode);
  }).find(Boolean);
  if (labels) {
    if (expectedCount && labels.length !== Number(expectedCount)) return [];
    return labels.map((label) => {
      const match = Object.values(colors).find(([zh]) => zh === label.replace(/^[深浅]/, ""));
      const qualifier = label.startsWith("深") ? "Deep " : label.startsWith("浅") ? "Light " : "";
      return { label: language === "en" && match ? qualifier + match[1] : label, hex: qualifier ? undefined : match?.[2] };
    });
  }
  const codes = [...mode.matchAll(/(?<![A-Z])(CMYWGK|RYBWGK|CMYW|RYBW|BW)(?![A-Z])/gi)].map(([code]) => code.toUpperCase());
  if (new Set(codes).size !== 1 || (expectedCount && codes[0].length !== Number(expectedCount))) return [];
  return [...codes[0]].map((letter, index) => {
    const entry = colors[letter === "B" && codes[0] === "BW" && index === 0 ? "K" : letter];
    return { label: entry[language === "zh" ? 0 : 1], hex: entry[2] };
  });
}
export function catalogSourceLabel(
  mode: string | undefined,
  provider: string | undefined,
  configured?: boolean,
): string {
  if (configured === false) return "resources_source_disabled_catalog";
  return mode === "mirror" ? "resources_mirror_catalog" : provider === "github" ? "resources_github_catalog" : "resources_cloud_catalog";
}
