import type { SavedMaterialLibraryItem } from "../../api/types";
import { favoriteKeyForMaterial } from "../../utils/materialPickerPreferences";
import { filamentBrandLogo, filamentMatches, type FilamentIdentity } from "../../utils/filamentIdentity";
import { savedMaterialIdentity } from "../../utils/libraryFilamentIdentity";

export type MaterialTypeFilter =
  | "favorites"
  | "all"
  | "pla"
  | "petg"
  | "other";

export type MaterialPickerSort = "name" | "recent";

export type MaterialProductGroup = {
  key: string;
  productId: string | null;
  brand: string | null;
  brandKey: string;
  materialType: string | null;
  profiles: SavedMaterialLibraryItem[];
  displayProfiles?: SavedMaterialLibraryItem[];
};

export type MaterialBrandOption = {
  key: string;
  label: string;
  count: number;
  logo?: string;
};

const ALL_BRANDS_KEY = "all";
const UNASSIGNED_BRAND_KEY = "unassigned";

export function resolvedMaterialType(
  item: SavedMaterialLibraryItem,
): string | null {
  const materialType = item.material_type?.trim();
  return materialType ? materialType.toUpperCase() : null;
}

export function getMaterialTypeCategory(
  item: SavedMaterialLibraryItem,
): Exclude<MaterialTypeFilter, "favorites" | "all"> {
  const materialType = resolvedMaterialType(item);
  if (materialType === "PLA") return "pla";
  if (materialType === "PETG") return "petg";
  return "other";
}

export function normalizeMaterialBrandKey(brand: string | null | undefined): string {
  const cleaned = brand?.normalize("NFKC").trim();
  return cleaned
    ? `brand:${cleaned.toLocaleLowerCase()}`
    : UNASSIGNED_BRAND_KEY;
}

export function buildBrandOptions(
  materials: SavedMaterialLibraryItem[],
  labels: { all: string; unassigned: string },
  identities?: ReadonlyMap<string, FilamentIdentity>,
): MaterialBrandOption[] {
  const grouped = new Map<string, MaterialBrandOption>();
  for (const material of materials) {
    const key = normalizeMaterialBrandKey(material.brand);
    const existing = grouped.get(key);
    if (existing) {
      existing.count += 1;
      continue;
    }
    grouped.set(key, {
      key,
      label:
        key === UNASSIGNED_BRAND_KEY
          ? labels.unassigned
          : identities?.get(material.directory_name)?.brand || material.brand?.normalize("NFKC").trim() || labels.unassigned,
      logo: filamentBrandLogo(material.brand),
      count: 1,
    });
  }

  const assigned = Array.from(grouped.values())
    .filter((option) => option.key !== UNASSIGNED_BRAND_KEY)
    .sort((left, right) =>
      left.label.localeCompare(right.label, undefined, {
        sensitivity: "base",
        numeric: true,
      }),
    );
  const unassigned = grouped.get(UNASSIGNED_BRAND_KEY);
  return [
    { key: ALL_BRANDS_KEY, label: labels.all, count: materials.length },
    ...assigned,
    ...(unassigned ? [unassigned] : []),
  ];
}

function productGroupKey(item: SavedMaterialLibraryItem): {
  key: string;
  productId: string | null;
} {
  const productId = item.material_product_id?.trim() || null;
  return productId
    ? { key: `product:${productId}`, productId }
    : { key: `profile:${favoriteKeyForMaterial(item)}`, productId: null };
}

function profileDisplayOrder(
  left: SavedMaterialLibraryItem,
  right: SavedMaterialLibraryItem,
): number {
  const leftContributor = left.contributor_name?.trim() || "\uffff";
  const rightContributor = right.contributor_name?.trim() || "\uffff";
  const contributorOrder = leftContributor.localeCompare(
    rightContributor,
    undefined,
    { sensitivity: "base", numeric: true },
  );
  if (contributorOrder !== 0) return contributorOrder;
  return left.directory_name.localeCompare(right.directory_name, undefined, {
    sensitivity: "base",
    numeric: true,
  });
}

export function buildMaterialProductGroups(
  materials: SavedMaterialLibraryItem[],
): MaterialProductGroup[] {
  const grouped = new Map<string, MaterialProductGroup>();
  for (const material of materials) {
    const identity = productGroupKey(material);
    const existing = grouped.get(identity.key);
    if (existing) {
      existing.profiles.push(material);
      continue;
    }
    grouped.set(identity.key, {
      key: identity.key,
      productId: identity.productId,
      brand: material.brand?.trim() || null,
      brandKey: normalizeMaterialBrandKey(material.brand),
      materialType: resolvedMaterialType(material),
      profiles: [material],
    });
  }
  return Array.from(grouped.values()).map((group) => ({
    ...group,
    profiles: [...group.profiles].sort(profileDisplayOrder),
  }));
}

function groupDisplayProfiles(
  group: MaterialProductGroup,
): SavedMaterialLibraryItem[] {
  return group.displayProfiles ?? group.profiles;
}

function groupMostRecentTimestamp(group: MaterialProductGroup): number {
  let latest = 0;
  for (const profile of groupDisplayProfiles(group)) {
    const timestamp = Date.parse(profile.usage_last_used_at ?? "");
    if (Number.isFinite(timestamp)) latest = Math.max(latest, timestamp);
  }
  return latest;
}

function groupName(group: MaterialProductGroup, identities?: ReadonlyMap<string, FilamentIdentity>): string {
  const profile = groupDisplayProfiles(group)[0];
  return identities?.get(profile.directory_name)?.name ?? profile.material_name;
}

export function filterMaterialGroups(
  groups: MaterialProductGroup[],
  filters: {
    query: string;
    type: MaterialTypeFilter;
    brandKey: string;
    favoriteKeys: Set<string>;
    sort: MaterialPickerSort;
    identities?: ReadonlyMap<string, FilamentIdentity>;
  },
): MaterialProductGroup[] {
  const normalizedQuery = filters.query
    .normalize("NFKC")
    .trim()
    .toLocaleLowerCase();
  const visible: MaterialProductGroup[] = [];

  for (const group of groups) {
    if (
      filters.brandKey !== ALL_BRANDS_KEY &&
      group.brandKey !== filters.brandKey
    ) {
      continue;
    }
    if (
      filters.type !== "all" &&
      filters.type !== "favorites" &&
      !group.profiles.some(
        (profile) => getMaterialTypeCategory(profile) === filters.type,
      )
    ) {
      continue;
    }

    const candidateProfiles =
      filters.type === "favorites"
        ? group.profiles.filter((profile) =>
            filters.favoriteKeys.has(favoriteKeyForMaterial(profile)),
          )
        : group.profiles;
    if (candidateProfiles.length === 0) continue;
    if (
      normalizedQuery &&
      !candidateProfiles.some((profile) =>
        filamentMatches(normalizedQuery, (filters.identities?.get(profile.directory_name) ?? savedMaterialIdentity(profile, "en")).searchText),
      )
    ) {
      continue;
    }

    visible.push({
      ...group,
      displayProfiles:
        filters.type === "favorites"
          ? candidateProfiles
          : undefined,
    });
  }

  return visible.sort((left, right) => {
    if (filters.sort === "recent") {
      const recentOrder =
        groupMostRecentTimestamp(right) - groupMostRecentTimestamp(left);
      if (recentOrder !== 0) return recentOrder;
    }
    return groupName(left, filters.identities).localeCompare(groupName(right, filters.identities), undefined, {
      sensitivity: "base",
      numeric: true,
    });
  });
}

export function summarizeSelectedMaterialTypes(
  materials: SavedMaterialLibraryItem[],
  selectedDirectoryNames: string[],
): {
  counts: Array<{ label: string; count: number }>;
  requiresConfirmation: boolean;
  hasUnknown: boolean;
} {
  const byDirectory = new Map(
    materials.map((material) => [material.directory_name, material]),
  );
  const countByType = new Map<string, number>();
  for (const directoryName of selectedDirectoryNames) {
    const materialType = resolvedMaterialType(byDirectory.get(directoryName) ?? {
      material_name: directoryName,
      directory_name: directoryName,
      material_file_url: null,
      estimated_rgb: [],
    });
    const label = materialType ?? "UNKNOWN";
    countByType.set(label, (countByType.get(label) ?? 0) + 1);
  }

  const hasUnknown = countByType.has("UNKNOWN");
  const knownTypeCount = Array.from(countByType.keys()).filter(
    (label) => label !== "UNKNOWN",
  ).length;
  const counts = Array.from(countByType.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => {
      if (left.label === "UNKNOWN") return 1;
      if (right.label === "UNKNOWN") return -1;
      return left.label.localeCompare(right.label);
    });

  return {
    counts,
    requiresConfirmation:
      knownTypeCount >= 2 || (knownTypeCount >= 1 && hasUnknown),
    hasUnknown,
  };
}
