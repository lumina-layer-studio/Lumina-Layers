import { filamentBrands, polymakerPanchromaLogo, type FilamentBrand } from "../data/filamentBrands";
import { bambuFilamentColors, cailabPlaColors, filamentColorDescriptions } from "../data/filamentColors";

type Language = "zh" | "en";
type Market = "CN" | "INTL";
type Metadata = Record<string, unknown>;

export interface FilamentIdentity {
  name: string;
  originalName: string;
  brand: string;
  logo?: string;
  productCode?: string;
  colorDescription?: string;
  colorName?: string;
  series?: string;
  materialType?: string;
  description?: string;
  contributor?: string;
  purchaseLinks?: { label: string; url: string; host: string }[];
  searchText: string;
}

const textValue = (value: unknown) => typeof value === "string" ? value.trim() : "";
const record = (value: unknown): Metadata =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Metadata : {};
const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.map(textValue).filter(Boolean) : [textValue(value)].filter(Boolean);
const codeValue = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) ? String(value) : textValue(value);
const fold = (value: string) => value.normalize("NFKC").toLowerCase();
const key = (value: string) => fold(value).replace(/[\s._/-]+/g, "");
const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function purchaseLinks(metadata: Metadata, market: Market): NonNullable<FilamentIdentity["purchaseLinks"]> {
  const links = Array.isArray(metadata.purchase_links) ? metadata.purchase_links : [];
  const candidates = [...links, ...[metadata.product_url, metadata.purchase_url].map((url) => ({ url }))];
  const seen = new Set<string>();
  return candidates.flatMap((entry) => {
    const link = record(entry);
    const region = textValue(link.market).toUpperCase();
    if (region && region !== "ALL" && region !== market) return [];
    try {
      const url = new URL(textValue(link.url));
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || seen.has(url.href)) return [];
      seen.add(url.href);
      return [{ label: textValue(link.label), url: url.href, host: url.hostname }];
    } catch { return []; }
  }).slice(0, 8);
}

function brandAliases(brand: FilamentBrand): string[] {
  return [brand.intl, brand.cn, brand.intl + brand.cn, brand.cn + brand.intl, ...(brand.aliases ?? [])];
}

const brandsByAlias = new Map<string, FilamentBrand>();
for (const brand of filamentBrands) {
  for (const alias of brandAliases(brand)) brandsByAlias.set(key(alias), brand);
}

export function filamentBrandLogo(brand: string | null | undefined): string | undefined {
  return brand ? brandsByAlias.get(key(brand))?.logo : undefined;
}

function localized(value: unknown, language: Language): string {
  const names = record(value);
  const locales = language === "zh" ? ["zh", "zh-CN", "zh-Hans"] : ["en", "en-US", "en-GB"];
  return locales.map((locale) => textValue(names[locale])).find(Boolean) ?? "";
}

function marketName(value: unknown, market: Market, language: Language): string {
  const names = record(value);
  const chosen = names[market] ?? names[market.toLowerCase()];
  return textValue(chosen) || localized(chosen, language) || localized(chosen, market === "CN" ? "zh" : "en");
}

function allNames(value: unknown): string[] {
  return Object.values(record(value)).flatMap((entry) =>
    typeof entry === "string" ? [entry] : Object.values(record(entry)).map(textValue).filter(Boolean),
  );
}

interface PackageColor {
  series: string;
  code: string;
  zh: string;
  en: string;
}

const bambuByLabel = new Map<string, PackageColor>();
const bambuByCode = new Map<string, PackageColor>();
for (const [series, colors] of Object.entries(bambuFilamentColors)) {
  for (const [code, zh, en] of colors) {
    const color = { series, code, zh, en };
    bambuByCode.set(code, color);
    for (const label of [zh, en]) {
      bambuByLabel.set(key(series + label), color);
      bambuByLabel.set(key(series + label + " (" + code + ")"), color);
      bambuByLabel.set(key(series + "(" + code + ") " + label), color);
    }
  }
}

const cailabByLabel = new Map<string, PackageColor>();
const cailabByCode = new Map<string, PackageColor>();
for (const [code, zh, en] of cailabPlaColors) {
  const color = { series: "PLA", code, zh, en };
  cailabByCode.set(code, color);
  for (const label of [zh, en]) {
    cailabByLabel.set(key("PLA " + code + label), color);
    cailabByLabel.set(key("PLA " + label + code), color);
  }
}

const materialSeries = /PLA|PETG|ABS|ASA|TPU|PA6|PA12|PCTG|PET-CF|PPA|PPS|PVA|HIPS|PAHT|\bPC\b/i;

// Strip presentation-only decoration. The input name stays intact for display and search.
function productLabel(name: string, aliases: string[]): string {
  let label = name.normalize("NFKC").trim()
    .replace(/\s*\bby\s*.+$/iu, "")
    .replace(/(?:__\w{8}|_\d{8}_\d{6})$/u, "")
    .trim();
  const prefixes = aliases.filter(Boolean).sort((a, b) => b.length - a.length).map(escapeRegExp);
  if (prefixes.length) {
    // Legacy names may join a brand directly to a polymer, but never strip part of a product word.
    const boundary = "(?=$|[\\s_./&-]|(?:" + materialSeries.source + ")(?![A-Za-z]))";
    const brandPrefix = new RegExp("^(?:(?:" + prefixes.join("|") + ")" + boundary + "[\\s_./&-]*)+", "iu");
    label = label.replace(brandPrefix, "");
  }
  return label;
}

function structuredProductLabel(label: string, display: Metadata) {
  const materialType = textValue(display.material_type);
  const series = textValue(display.series);
  const color = textValue(display.color_name);
  if (!materialType || !color) return;
  const grade = materialSeries.test(series) ? series : [materialType, series].filter(Boolean).join(" ");
  if (!key(grade).startsWith(key(materialType))) return;
  const fullLabel = `${grade} ${color}`;
  if (![color, `${series} ${color}`, fullLabel].some((candidate) => key(candidate) === key(label))) return;
  const titleSeries = materialSeries.test(label) ? grade
    : series.replace(new RegExp("^" + escapeRegExp(materialType) + "(?:\\s+|$)", "i"), "");
  return { label: fullLabel, titleSeries };
}

function bambuColor(label: string, display: Metadata): PackageColor | undefined {
  const fromName = bambuByLabel.get(key(label));
  const metadataCode = [display.fila_color_code, display.color_code, display.sku].map(codeValue).find((v) => /^\d{5}$/.test(v));
  const embedded = [...label.matchAll(/(?<![a-z0-9])\d{5}(?![a-z0-9])/gi)].map(([v]) => v);
  const codes = new Set([...embedded, ...(metadataCode ? [metadataCode] : [])]);
  if (codes.size > 1) return undefined;
  const [code] = codes;
  if (!code) return fromName;
  const color = bambuByCode.get(code);
  if (!color || (fromName && fromName.code !== code)) return undefined;
  const polymer = color.series.split(" ", 1)[0];
  const declaredType = textValue(display.material_type);
  if (declaredType && key(declaredType) !== key(polymer)) return undefined;
  // A number in an old file name is not evidence of a product series.
  // Translate only when the recorded grade also matches the manufacturer's entry.
  const namedGrade = label.match(descriptorGrade)?.[0].trim() ?? "";
  if (key(namedGrade) !== key(color.series)) return undefined;
  const beforeCode = label.split(/[（(]/, 1)[0].replace(code, "").trim();
  const namedColor = bambuByLabel.get(key(beforeCode));
  if (namedColor && namedColor.code !== code) return undefined;
  return color;
}

function cailabColor(label: string, display: Metadata): PackageColor | undefined {
  const fromName = cailabByLabel.get(key(label));
  const code = [display.color_code, display.sku].map((v) => codeValue(v).toUpperCase()).find((v) => /^AC\d+$/.test(v));
  const color = code ? cailabByCode.get(code) : fromName;
  if (!color || (fromName && fromName.code !== color.code)) return undefined;
  // AC numbers describe colors. A code on an unrelated grade is not a PLA identity.
  if (!fromName && !cailabByLabel.has(key(label + color.code))) return undefined;
  const recordedGrade = textValue(display.material_type);
  if (recordedGrade && !["pla", "pla+bio"].includes(key(recordedGrade))) return undefined;
  return key(recordedGrade) === "pla+bio" ? { ...color, series: recordedGrade } : color;
}

const descriptions = new Map<string, { zh: string; en: string }>();
for (const [stem, en] of filamentColorDescriptions) {
  const color = { zh: stem + "色", en };
  for (const label of [stem, color.zh, en]) descriptions.set(key(label), color);
}

// Only an entire color descriptor next to a known polymer/grade qualifies.
// This keeps creator nicknames, multi-color LUT titles and unknown finishes intact.
const descriptorGrade = /^(?:(?:Panchroma\s+)?(?:PETG|PLA|ABS|ASA|TPU|PCTG)(?:\+|[\s_-]*(?:Basic|Pro|Matte|Translucent|Silk|Glow|Lite|CF|HF|HS|Classic|K5))*)[\s:_-]*/i;

function colorDescription(label: string) {
  const tokens = label.replace(descriptorGrade, "").trim();
  const direct = descriptions.get(key(tokens)) ?? descriptions.get(key(label.replace(/(?:PLA|PETG)\+?$/i, "")));
  if (direct) return direct;
  const qualified = tokens.match(/^(.+?)\s+([A-Z]\d*)$/u);
  const base = qualified && descriptions.get(key(qualified[1]));
  return base ? { zh: `${base.zh} ${qualified![2]}`, en: `${base.en} ${qualified![2]}` } : undefined;
}

export function filamentIdentity(
  brand: string | null | undefined,
  name: string,
  language: Language,
  display?: Metadata | null,
  market?: string,
): FilamentIdentity {
  const selectedMarket = market === "CN" || market === "INTL" ? market : language === "zh" ? "CN" : "INTL";
  const marketLanguage = selectedMarket === "CN" ? "zh" : "en";
  const metadata = display ?? {};
  const brandIdentity = record(metadata.brand_identity);
  const rawBrand = textValue(brand) || textValue(metadata.brand);
  const brandCandidates = [rawBrand, textValue(brandIdentity.key), textValue(brandIdentity.label)];
  const fromTitle = name.split("&", 1)[0];
  const known = brandCandidates.map((candidate) => brandsByAlias.get(key(candidate))).find(Boolean)
    ?? (/^(?:custom|unknown|unassigned)?$/i.test(rawBrand) ? brandsByAlias.get(key(fromTitle)) : undefined);
  const aliases = known ? brandAliases(known) : [rawBrand];
  const displayBrand = marketName(brandIdentity.market_names, selectedMarket, language)
    || (known && (selectedMarket === "CN" ? known.cn : known.intl))
    || localized(brandIdentity.names, marketLanguage) || rawBrand || textValue(brandIdentity.label);

  const label = productLabel(name, [...aliases, rawBrand]);
  const structured = structuredProductLabel(label, metadata);
  const lookupLabel = structured?.label ?? label;
  const explicitName = marketName(metadata.market_names, selectedMarket, language)
    || localized(metadata.localized_names, marketLanguage);
  let color: PackageColor | undefined;
  if (known?.intl === "Bambu Lab") color = bambuColor(lookupLabel, metadata);
  if (known?.intl === "CAILAB") color = cailabColor(lookupLabel, metadata);
  const colorName = color && [structured?.titleSeries ?? color.series, color[marketLanguage], known?.intl === "CAILAB" && color.code].filter(Boolean).join(" ");
  const description = (explicitName || color) ? undefined : colorDescription(lookupLabel);
  const catalogCodes = [metadata.color_code, metadata.fila_color_code, metadata.sku].map(codeValue).filter(Boolean);
  const descriptorName = structured && description && !catalogCodes.length
    ? [structured.titleSeries, description[marketLanguage]].filter(Boolean).join(" ") : undefined;
  const regionalColor = structured && (color?.[marketLanguage] || (descriptorName && description?.[marketLanguage]));
  const descriptionText = descriptorName ? undefined : description?.[language];
  const allTerms = [
    name, textValue(metadata.material_name), textValue(metadata.color_name), textValue(metadata.material_type),
    textValue(metadata.series), textValue(metadata.contributor_name), textValue(metadata.author),
    ...catalogCodes,
    ...allNames(metadata.market_names), ...allNames(metadata.localized_names), ...strings(metadata.aliases),
    ...brandCandidates, ...aliases, displayBrand, ...allNames(brandIdentity.market_names), ...allNames(brandIdentity.names),
    ...strings(brandIdentity.search_terms), color?.code, color?.series, color?.en, color?.zh, description?.en, description?.zh,
  ];
  return {
    name: explicitName || colorName || descriptorName || name,
    originalName: name,
    brand: displayBrand,
    logo: known?.logo ?? polymakerPanchromaLogo(known?.intl, textValue(metadata.series), textValue(metadata.material_type)),
    productCode: catalogCodes[0] ?? color?.code,
    colorDescription: descriptionText && !fold(label).includes(fold(descriptionText)) ? descriptionText : undefined,
    colorName: regionalColor || textValue(metadata.color_name) || color?.[marketLanguage] || undefined,
    series: textValue(metadata.series) || color?.series.replace(/^(?:PLA|PETG)\s*/i, "") || undefined,
    materialType: textValue(metadata.material_type) || undefined,
    description: localized(metadata.description, language) || textValue(metadata.description) || undefined,
    contributor: textValue(metadata.contributor_name) || textValue(metadata.author) || undefined,
    purchaseLinks: purchaseLinks(metadata, selectedMarket),
    searchText: [...new Set(allTerms.filter(Boolean))].join(" "),
  };
}

/** Simplify known brand decoration without changing product wording or attribution records. */
export function materialDisplayName(identity: FilamentIdentity): FilamentIdentity {
  const known = brandsByAlias.get(key(identity.brand));
  if (!known || identity.name !== identity.originalName) return identity;
  const name = productLabel(identity.name, brandAliases(known));
  return { ...identity, name: name || identity.name };
}

export function filamentMatches(query: string, searchable: string): boolean {
  const tokens = fold(query).trim().split(/\s+/).filter(Boolean);
  const haystack = fold(searchable);
  const compact = key(haystack);
  return tokens.every((token) => haystack.includes(token) || (key(token) !== "" && compact.includes(key(token))));
}
