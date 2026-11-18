import type { SavedMaterialLibraryItem } from "../api/types";
import { filamentIdentity, materialDisplayName, type FilamentIdentity } from "./filamentIdentity";
import { lutDisplayIdentity } from "./resourcePresentation";
import { translations } from "../i18n/translations";
import { POLYMAKER_PANCHROMA_LOGO } from "../data/filamentBrands";

export function savedMaterialIdentity(item: SavedMaterialLibraryItem, lang: "zh" | "en", market?: string) {
  const identity = materialDisplayName(filamentIdentity(item.brand, item.material_name, lang, item.display, market));
  return {
    ...identity,
    contributor: item.contributor_name || identity.contributor,
    searchText: [identity.searchText, item.material_type, item.material_product_id, item.material_profile_id,
      item.directory_name, item.contributor_name].filter(Boolean).join(" "),
  };
}

export function localLutIdentity(brand: string | undefined, name: string, lang: "zh" | "en", display?: Record<string, unknown> | null, market?: string) {
  const catalogName = [display?.name, display?.display_name, display?.lut_name, display?.title]
    .find((value): value is string => typeof value === "string" && Boolean(value.trim()));
  const maker = [display?.manufacturer, display?.brand, display?.vendor]
    .find((value): value is string => typeof value === "string" && Boolean(value.trim()));
  const identity = lutDisplayIdentity(filamentIdentity(maker ?? brand, catalogName ?? name, lang, display, market), lang);
  const filaments = display?.filaments;
  if (Array.isArray(filaments) && filaments.length) {
    const makers = filaments.map((entry) => entry && typeof entry === "object" && !Array.isArray(entry)
      ? filamentIdentity(typeof entry.brand === "string" ? entry.brand : undefined, "", lang, entry, market)
      : undefined);
    if (makers.every((entry) => entry?.brand)) {
      const unique = new Set(makers.map((entry) => entry!.brand));
      const common = unique.size === 1 ? makers[0]! : undefined;
      const logo = common?.logo === POLYMAKER_PANCHROMA_LOGO && makers.some((entry) => entry?.logo !== common.logo)
        ? undefined : common?.logo;
      return { ...identity, brand: common?.brand ?? translations.resources_mixed_brands[lang], logo,
        searchText: [identity.searchText, ...makers.map((entry) => entry!.searchText)].join(" ") };
    }
    if (identity.logo === POLYMAKER_PANCHROMA_LOGO) return { ...identity, logo: undefined };
  }
  return identity;
}

export function lutGroupBrand(
  group: string, items: FilamentIdentity[], lang: "zh" | "en", market: string,
): Pick<FilamentIdentity, "brand" | "logo"> {
  const first = items[0];
  if (first?.brand && items.every((item) => item.brand === first.brand)) {
    return { brand: first.brand, logo: first.logo === POLYMAKER_PANCHROMA_LOGO ? undefined : first.logo };
  }
  return filamentIdentity(group, "", lang, undefined, market);
}
