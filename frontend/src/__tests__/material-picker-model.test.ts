import { describe, expect, it } from "vitest";

import type { SavedMaterialLibraryItem } from "../api/types";
import { POLYMAKER_PANCHROMA_LOGO } from "../data/filamentBrands";
import { savedMaterialIdentity } from "../utils/libraryFilamentIdentity";
import {
  buildBrandOptions,
  buildMaterialProductGroups,
  filterMaterialGroups,
  getMaterialTypeCategory,
  summarizeSelectedMaterialTypes,
} from "../components/ui/materialPickerModel";

function makeMaterial(
  overrides: Partial<SavedMaterialLibraryItem> & {
    material_name: string;
    directory_name: string;
  },
): SavedMaterialLibraryItem {
  return {
    material_file_url: null,
    estimated_rgb: [128, 128, 128],
    verification_count: 1,
    verification_history: [],
    ...overrides,
  };
}

describe("materialPickerModel", () => {
  it("classifies explicit and legacy-resolved material types", () => {
    const pla = makeMaterial({
      material_name: "Red PLA",
      directory_name: "JAYO/red-pla",
      material_type: "PLA",
    });
    const petg = makeMaterial({
      material_name: "Black PETG",
      directory_name: "JAYO/black-petg",
      material_type: "petg",
      material_type_source: "legacy_name",
    });
    const unknown = makeMaterial({
      material_name: "Legacy Red",
      directory_name: "legacy-red",
      material_type: null,
    });

    expect(getMaterialTypeCategory(pla)).toBe("pla");
    expect(getMaterialTypeCategory(petg)).toBe("petg");
    expect(getMaterialTypeCategory(unknown)).toBe("other");
  });

  it("shows all brands neutrally and merges case-only brand labels", () => {
    const materials = [
      makeMaterial({
        material_name: "Red PLA",
        directory_name: "JAYO/red-pla",
        brand: "JAYO",
      }),
      makeMaterial({
        material_name: "Black PETG",
        directory_name: "jayo/black-petg",
        brand: "jayo",
      }),
      makeMaterial({
        material_name: "Legacy Red",
        directory_name: "legacy-red",
        brand: null,
      }),
    ];

    expect(
      buildBrandOptions(materials, {
        all: "全部品牌",
        unassigned: "未分组",
      }),
    ).toEqual([
      { key: "all", label: "全部品牌", count: 3 },
      { key: "brand:jayo", label: "JAYO", logo: expect.any(String), count: 2 },
      { key: "unassigned", label: "未分组", count: 1 },
    ]);
  });

  it("does not use a product-specific logo for the whole picker brand", () => {
    const profiles = ["Panchroma PLA", "Basic PLA"].map((name) =>
      makeMaterial({ brand: "Polymaker", directory_name: name, material_name: name }),
    );
    const identities = new Map(profiles.map((profile, i) => [profile.directory_name, {
      ...savedMaterialIdentity(profile, "en"), logo: i === 0 ? POLYMAKER_PANCHROMA_LOGO : undefined,
    }]));
    for (const order of [profiles, [...profiles].reverse()]) {
      const group = buildBrandOptions(order, { all: "All", unassigned: "Unassigned" }, identities)[1];
      expect(group).toMatchObject({ label: "Polymaker", count: 2 });
      expect(group.logo).toBeUndefined();
    }
  });

  it("groups only profiles with the same explicit physical product id", () => {
    const materials = [
      makeMaterial({
        material_name: "PLA Basic Red",
        directory_name: "Brand/pla-red-alice",
        brand: "Brand",
        material_product_id: "product-red",
        material_profile_id: "profile-alice",
        contributor_name: "Alice",
      }),
      makeMaterial({
        material_name: "PLA Basic Red",
        directory_name: "Brand/pla-red-bob",
        brand: "Brand",
        material_product_id: "product-red",
        material_profile_id: "profile-bob",
        contributor_name: "Bob",
      }),
      makeMaterial({
        material_name: "PLA Basic Red",
        directory_name: "Brand/pla-red-legacy",
        brand: "Brand",
      }),
    ];

    const groups = buildMaterialProductGroups(materials);

    expect(groups).toHaveLength(2);
    expect(groups[0].profiles).toHaveLength(2);
    expect(groups[0].profiles.map((item) => item.contributor_name)).toEqual([
      "Alice",
      "Bob",
    ]);
    expect(groups[1].profiles).toHaveLength(1);
  });

  it("searches contributor, brand, type and name while preserving groups", () => {
    const groups = buildMaterialProductGroups([
      makeMaterial({
        material_name: "PLA Basic Red",
        directory_name: "Brand/pla-red-alice",
        brand: "Brand",
        material_type: "PLA",
        material_product_id: "product-red",
        material_profile_id: "profile-alice",
        contributor_name: "Alice",
      }),
      makeMaterial({
        material_name: "PLA Basic Red",
        directory_name: "Brand/pla-red-bob",
        brand: "Brand",
        material_type: "PLA",
        material_product_id: "product-red",
        material_profile_id: "profile-bob",
        contributor_name: "Bob",
      }),
      makeMaterial({
        material_name: "Black PETG",
        directory_name: "Other/black-petg",
        brand: "Other",
        material_type: "PETG",
      }),
    ]);

    const byAuthor = filterMaterialGroups(groups, {
      query: "Alice",
      type: "all",
      brandKey: "all",
      favoriteKeys: new Set(),
      sort: "name",
    });
    const byType = filterMaterialGroups(groups, {
      query: "petg",
      type: "all",
      brandKey: "all",
      favoriteKeys: new Set(),
      sort: "name",
    });

    expect(byAuthor).toHaveLength(1);
    expect(byAuthor[0].profiles).toHaveLength(2);
    expect(byType).toHaveLength(1);
    expect(byType[0].profiles[0].material_name).toBe("Black PETG");
  });

  it("filters the favorites tab to every independently favorited profile", () => {
    const groups = buildMaterialProductGroups([
      makeMaterial({
        material_name: "PLA Basic Red",
        directory_name: "Brand/pla-red-alice",
        material_product_id: "product-red",
        material_profile_id: "profile-alice",
        contributor_name: "Alice",
      }),
      makeMaterial({
        material_name: "PLA Basic Red",
        directory_name: "Brand/pla-red-bob",
        material_product_id: "product-red",
        material_profile_id: "profile-bob",
        contributor_name: "Bob",
      }),
      makeMaterial({
        material_name: "PLA Basic Blue",
        directory_name: "Brand/pla-blue",
        material_profile_id: "profile-blue",
      }),
    ]);

    const filtered = filterMaterialGroups(groups, {
      query: "",
      type: "favorites",
      brandKey: "all",
      favoriteKeys: new Set(["profile:profile-alice", "profile:profile-bob"]),
      sort: "name",
    });

    expect(filtered).toHaveLength(1);
    expect(filtered[0].profiles.map((item) => item.contributor_name)).toEqual([
      "Alice",
      "Bob",
    ]);
  });

  it("sorts favorite cards by the visible profiles' recent usage", () => {
    const groups = buildMaterialProductGroups([
      makeMaterial({
        material_name: "Product A",
        directory_name: "Brand/product-a-alice",
        material_product_id: "product-a",
        material_profile_id: "profile-a-alice",
        contributor_name: "Alice",
        usage_last_used_at: "2026-07-30T00:00:00Z",
      }),
      makeMaterial({
        material_name: "Product A",
        directory_name: "Brand/product-a-bob",
        material_product_id: "product-a",
        material_profile_id: "profile-a-bob",
        contributor_name: "Bob",
        usage_last_used_at: "2026-07-20T00:00:00Z",
      }),
      makeMaterial({
        material_name: "Product B",
        directory_name: "Brand/product-b",
        material_product_id: "product-b",
        material_profile_id: "profile-b",
        contributor_name: "Carol",
        usage_last_used_at: "2026-07-25T00:00:00Z",
      }),
    ]);

    const filtered = filterMaterialGroups(groups, {
      query: "",
      type: "favorites",
      brandKey: "all",
      favoriteKeys: new Set(["profile:profile-a-bob", "profile:profile-b"]),
      sort: "recent",
    });

    expect(
      filtered.map(
        (group) =>
          (group.displayProfiles ?? group.profiles)[0].directory_name,
      ),
    ).toEqual(["Brand/product-b", "Brand/product-a-bob"]);
  });

  it("summarizes mixed known types and unknown compatibility", () => {
    const materials = [
      makeMaterial({
        material_name: "Red PLA",
        directory_name: "pla-red",
        material_type: "PLA",
      }),
      makeMaterial({
        material_name: "Black PETG",
        directory_name: "petg-black",
        material_type: "PETG",
      }),
      makeMaterial({
        material_name: "Legacy",
        directory_name: "legacy",
        material_type: null,
      }),
    ];

    expect(
      summarizeSelectedMaterialTypes(materials, ["pla-red", "petg-black"]),
    ).toEqual({
      counts: [
        { label: "PETG", count: 1 },
        { label: "PLA", count: 1 },
      ],
      requiresConfirmation: true,
      hasUnknown: false,
    });
    expect(
      summarizeSelectedMaterialTypes(materials, ["pla-red", "legacy"]),
    ).toEqual({
      counts: [
        { label: "PLA", count: 1 },
        { label: "UNKNOWN", count: 1 },
      ],
      requiresConfirmation: true,
      hasUnknown: true,
    });
    expect(summarizeSelectedMaterialTypes(materials, ["legacy"])).toEqual({
      counts: [{ label: "UNKNOWN", count: 1 }],
      requiresConfirmation: false,
      hasUnknown: true,
    });
  });

  it("sorts product cards by most recent actual usage when requested", () => {
    const groups = buildMaterialProductGroups([
      makeMaterial({
        material_name: "A Material",
        directory_name: "a",
        usage_last_used_at: "2026-07-20T00:00:00Z",
      }),
      makeMaterial({
        material_name: "Z Material",
        directory_name: "z",
        usage_last_used_at: "2026-07-28T00:00:00Z",
      }),
    ]);

    const filtered = filterMaterialGroups(groups, {
      query: "",
      type: "all",
      brandKey: "all",
      favoriteKeys: new Set(),
      sort: "recent",
    });

    expect(filtered.map((group) => group.profiles[0].directory_name)).toEqual([
      "z",
      "a",
    ]);
  });
});
