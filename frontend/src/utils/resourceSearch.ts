import { filamentBrands } from "../data/filamentBrands";
import { filamentIdentity, type FilamentIdentity } from "./filamentIdentity";
import { resourceColors, resourceFilaments } from "./resourcePresentation";
import type { CalibrationPreviewInput } from "./calibrationPreview";

export const RESOURCE_AXES = ["brand", "material", "series", "color", "count"] as const;
export type ResourceAxis = typeof RESOURCE_AXES[number];
export type ResourceFilters = Record<ResourceAxis, string[]>;
export const EMPTY_RESOURCE_FILTERS: ResourceFilters = { brand: [], material: [], series: [], color: [], count: [] };
export interface ResourceOption { value: string; label: string; terms?: string; swatch?: string; logo?: string }
export type ResourceFacets = Record<ResourceAxis, (ResourceOption & { count: number })[]>;
export type ResourceSearch = Record<ResourceAxis, ResourceOption[]> & {
  text: string; compactText: string; code: string[]; names: string[]; kind: "materials" | "luts";
};
const fold = (value: string) => value.normalize("NFKC").toLowerCase();
const compact = (value: string) => fold(value).replace(/[\s._/-]+/g, "");
const text = (value: unknown) => typeof value === "string" ? value.trim() : "";
const unique = (options: ResourceOption[]) => [...new Map(options.map((option) => [option.value, option])).values()];
export const hasResourceFilters = (filters: ResourceFilters) => RESOURCE_AXES.some((axis) => filters[axis].length > 0);

// These are broad search families, not manufacturer color names or measured values.
const colors = [
  ["black", "黑", "Black", "#252525"], ["white", "白", "White", "#ffffff"],
  ["gray", "灰", "Gray", "#9298a0"], ["red", "红", "Red", "#dc143c"],
  ["orange", "橙", "Orange", "#f78527"], ["yellow", "黄", "Yellow", "#f4ce35"],
  ["green", "绿", "Green", "#36a767"], ["cyan", "青", "Cyan", "#21bdc7"],
  ["blue", "蓝", "Blue", "#3576df"], ["purple", "紫", "Purple", "#9255ce"],
  ["magenta", "品红", "Magenta", "#de3b98"], ["pink", "粉", "Pink", "#ef9abd"],
  ["brown", "棕", "Brown", "#985e38"],
] as const;
const polymers = /(?<![a-z])(?:PLA|PETG|PCTG|ABS|ASA|TPU|TPE|PAHT|PA12|PA6|PPA|PPS|PET|PVA|HIPS|PC)(?![a-z])/gi;

function colorFamily(label: string, rgb: unknown, language: "zh" | "en"): ResourceOption[] {
  const normalized = fold(label);
  let entry = colors.find(([value, zh, en]) => normalized === value || normalized === zh || normalized === zh + "色"
    || normalized === fold(en) || (value === "gray" && normalized === "grey"));
  if (!entry) {
    // Prefer magenta over its Chinese red suffix.
    entry = [...colors].sort((a, b) => b[1].length - a[1].length).find(([, zh, en]) =>
      normalized.includes(zh) || new RegExp(`\\b${en}\\b`, "i").test(normalized));
  }
  if (!entry) {
    const values = typeof rgb === "string" && /^#[\da-f]{6}$/i.test(rgb)
      ? [1, 3, 5].map((offset) => parseInt(rgb.slice(offset, offset + 2), 16)) : rgb;
    if (Array.isArray(values) && values.length === 3 && values.every((v) => Number.isFinite(v) && v >= 0 && v <= 255)) {
      const [r, g, b] = values.map((v) => v / 255), max = Math.max(r, g, b), min = Math.min(r, g, b);
      const delta = max - min, lightness = (max + min) / 2;
      const hue = delta === 0 ? 0 : ((max === r ? (g - b) / delta : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4) * 60 + 360) % 360;
      const family = max < 0.19 ? "black" : delta < 0.10 ? (min > 0.78 ? "white" : "gray")
        : hue < 15 || hue >= 350 ? "red" : hue < 45 ? (lightness < 0.45 ? "brown" : "orange")
          : hue < 70 ? "yellow" : hue < 165 ? "green" : hue < 195 ? "cyan"
            : hue < 260 ? "blue" : hue < 290 ? "purple" : lightness > 0.7 ? "pink" : "magenta";
      entry = colors.find(([value]) => value === family);
    }
  }
  return entry ? [{ value: entry[0], label: language === "zh" ? entry[1] + "色" : entry[2],
    terms: `${entry[0]} ${entry[1]} ${entry[1]}色 ${entry[2]}${entry[0] === "gray" ? " grey" : ""}`, swatch: entry[3] }] : [];
}

function brandOption(brand: string, language: "zh" | "en", market?: string): ResourceOption[] {
  if (!brand) return [];
  const known = filamentBrands.find((candidate) => [candidate.intl, candidate.cn, ...(candidate.aliases ?? [])].some((alias) => compact(alias) === compact(brand)));
  const identity = filamentIdentity(brand, "", language, undefined, market);
  return [{ value: compact(known?.intl ?? brand), label: identity.brand, terms: identity.searchText, logo: identity.logo }];
}

/** Index only directory metadata. Preview images and recipe arrays are never searched. */
export function buildResourceSearch(input: CalibrationPreviewInput & {
  identity: FilamentIdentity; language?: "zh" | "en"; market?: string; materialType?: string | null; extra?: string;
}): ResourceSearch {
  const { identity, kind, language = "zh", market, display = {}, metadata = {} } = input;
  const slots = kind === "luts" ? resourceFilaments(input) : [];
  const identities = slots.length
    ? slots.map((slot) => filamentIdentity(text(slot.brand), text(slot.material_name) || text(slot.color_name), language, slot, market))
    : [identity];
  const brand = unique(slots.length ? slots.flatMap((slot) => brandOption(text(slot.brand), language, market))
    : brandOption(identity.brand, language, market));
  const material = unique(identities.flatMap((item) => {
    const grade = item.materialType || input.materialType || text(display?.material_type) || item.originalName;
    return [...grade.matchAll(polymers)].map(([value]) => ({ value: value.toUpperCase(), label: value.toUpperCase() }));
  }));
  const series = unique(identities.flatMap((item) => item.series ? [{ value: fold(item.series), label: item.series }] : []));
  const color = unique(kind === "luts" ? resourceColors(input, "en").flatMap((entry) => colorFamily(entry.label, entry.hex, language))
    : colorFamily(identity.colorName || identity.colorDescription || identity.name, input.rgb ?? display?.color_hex ?? display?.rgb, language));
  const rawMode = input.mode || text(metadata?.color_mode) || text(display?.color_mode);
  const modeCount = !/merged|合并/i.test(rawMode)
    ? rawMode.match(/^(\d+)(?:[ -]?colou?r|色)/i)?.[1]
      ?? ({ bw: "2", cmyw: "4", rybw: "4", cmywgk: "6", rybwgk: "6" } as Record<string, string>)[fold(rawMode)]
    : undefined;
  const count: ResourceOption[] = kind === "luts" && modeCount ? [{ value: modeCount, label: modeCount }] : [];
  const fields = { brand, material, series, color, count };
  const searchText = fold([identity.searchText, ...identities.map((item) => item.searchText), input.extra,
    rawMode, modeCount ? `${modeCount}色 ${modeCount} colors` : "",
    ...Object.values(fields).flat().map((option) => `${option.label} ${option.terms ?? ""}`)].filter(Boolean).join(" "));
  return { ...fields, kind,
    code: identities.flatMap((item) => item.productCode ? [compact(item.productCode)] : []),
    names: [identity.name, identity.originalName].map(compact),
    text: searchText, compactText: compact(searchText),
  };
}

const chineseBrands = filamentBrands.flatMap((brand) => [brand.cn, ...(brand.aliases ?? [])])
  .filter((alias) => /^[\p{Script=Han}]{2,}$/u.test(alias)).sort((a, b) => b.length - a.length);
function queryTokens(query: string): string[] {
  const separated = fold(query).replace(/([\p{Script=Han}])([a-z0-9])|([a-z0-9])([\p{Script=Han}])/gu, "$1$3 $2$4");
  return separated.split(/\s+/).filter(Boolean).flatMap((token) => {
    const brand = chineseBrands.find((name) => token.startsWith(name) && token.length > name.length);
    return brand ? [brand, token.slice(brand.length)] : [token];
  });
}

export function resourceSearchScore(search: ResourceSearch, query: string): number {
  return scoreTokens(search, queryTokens(query), compact(query));
}

function scoreTokens(search: ResourceSearch, tokens: string[], exact: string): number {
  if (!tokens.every((token) => search.text.includes(token) || (compact(token) !== "" && search.compactText.includes(compact(token))))) return -1;
  if (!tokens.length) return 0;
  return search.code.includes(exact) ? 100 : search.names.includes(exact) ? 80
    : tokens.reduce((score, token) => score + (search.code.includes(compact(token)) ? 30 : search.names.some((name) => name.startsWith(compact(token))) ? 10 : 1), 0);
}

function matchesFilters(search: ResourceSearch, filters: ResourceFilters, exclude?: ResourceAxis): boolean {
  return RESOURCE_AXES.every((axis) => axis === exclude || !filters[axis].length
    || (axis === "color" && search.kind === "luts"
      ? filters[axis].every((value) => search[axis].some((option) => option.value === value))
      : filters[axis].some((value) => search[axis].some((option) => option.value === value))));
}

export function filterResources<T extends { search: ResourceSearch }>(rows: T[], query: string, filters: ResourceFilters, nativeKeys?: Set<T>): T[] {
  const tokens = queryTokens(query), exact = compact(query);
  return rows.map((row) => ({ row, score: scoreTokens(row.search, tokens, exact) }))
    .filter(({ row, score }) => (score >= 0 || nativeKeys?.has(row)) && matchesFilters(row.search, filters))
    .sort((a, b) => b.score - a.score).map(({ row }) => row);
}

/** Self-excluding counts: choosing a brand doesn't hide all alternative brands. */
export function resourceFacets<T extends { search: ResourceSearch }>(rows: T[], query: string, filters: ResourceFilters, nativeKeys?: Set<T>): ResourceFacets {
  const tokens = queryTokens(query), exact = compact(query);
  const matches = new Set(rows.filter((row) => scoreTokens(row.search, tokens, exact) >= 0 || nativeKeys?.has(row)));
  return Object.fromEntries(RESOURCE_AXES.map((axis) => {
    const options = new Map<string, ResourceOption & { count: number }>();
    for (const row of rows) {
      for (const option of row.search[axis]) {
        const existing = options.get(option.value) ?? { ...option, count: 0 };
        const containsOtherColors = axis !== "color" || row.search.kind !== "luts"
          || filters.color.filter((value) => value !== option.value).every((value) => row.search.color.some((color) => color.value === value));
        if (matches.has(row) && matchesFilters(row.search, filters, axis) && containsOtherColors) existing.count++;
        options.set(option.value, existing);
      }
    }
    return [axis, [...options.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, undefined, { numeric: true }))];
  })) as ResourceFacets;
}
