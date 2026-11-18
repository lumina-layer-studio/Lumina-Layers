import { describe, expect, it } from "vitest";
import { filamentIdentity } from "../utils/filamentIdentity";
import { buildResourceSearch, filterResources, resourceFacets, EMPTY_RESOURCE_FILTERS } from "../utils/resourceSearch";

const material = (name: string, display: Record<string, unknown>, rgb?: number[]) => ({
  id: name,
  search: buildResourceSearch({
    identity: filamentIdentity(String(display.brand ?? ""), name, "zh", display),
    kind: "materials", name, display, rgb,
  }),
});

describe("resource search", () => {
  const black = material("PLA Basic 黑色", { brand: "拓竹", material_type: "PLA", series: "Basic", author: "小明" }, [15, 15, 15]);
  const red = material("PETG 红色", { brand: "Bambu Lab", material_type: "PETG", series: "HF" }, [220, 20, 30]);
  const other = material("PLA Basic Black", { brand: "Aliz", material_type: "PLA", series: "Basic" });

  it("combines Chinese brand, material and color without spaces; indexes series and attribution", () => {
    expect(filterResources([red, black, other], "拓竹PLA黑色", EMPTY_RESOURCE_FILTERS)).toEqual([black]);
    expect(filterResources([red, black], "Bambu basic 小明", EMPTY_RESOURCE_FILTERS)).toEqual([black]);
  });

  it("ranks an exact SKU ahead of a partial filename and accepts full-width codes", () => {
    const partial = material("Copy of 10101 measurement", { brand: "Aliz" });
    expect(filterResources([partial, black], "１０１０１", EMPTY_RESOURCE_FILTERS)).toEqual([black, partial]);
  });

  it("canonicalizes brand aliases and intersects facets while showing alternatives on the same axis", () => {
    const filters = { ...EMPTY_RESOURCE_FILTERS, brand: [black.search.brand[0].value], material: ["PLA"] };
    expect(filterResources([black, red, other], "", filters)).toEqual([black]);
    const facets = resourceFacets([black, red, other], "", filters);
    expect(facets.brand.map((option) => [option.label, option.count])).toEqual(expect.arrayContaining([["拓竹", 1], ["爱丽兹", 1]]));
    expect(facets.material.map((option) => [option.value, option.count])).toEqual(expect.arrayContaining([["PLA", 1], ["PETG", 1]]));
    expect(filterResources([black, red, other], "", { ...filters, material: ["PLA", "PETG"] })).toEqual([black, red]);
  });

  it("uses declared LUT filaments for brand, material and ALL required colors, never board pixels", () => {
    const makeLut = (name: string, display: Record<string, unknown>, mode: string) => ({
      id: name, search: buildResourceSearch({ kind: "luts", name, mode, display,
        identity: filamentIdentity("Custom", name, "zh", display) }),
    });
    const mixed = makeLut("My print", { filaments: [
      { slot: 0, brand: "Bambu", material_type: "PLA", color_name: "Red" },
      { slot: 1, brand: "Aliz", material_type: "PLA", color_name: "White" },
    ] }, "2-Color");
    const unknown = makeLut("Unknown print", { lut_board_preview: { colors: ["#ff0000", "#ffffff"] } }, "4-Color");
    expect(filterResources([mixed, unknown], "爱丽兹 红色", EMPTY_RESOURCE_FILTERS)).toEqual([mixed]);
    expect(filterResources([mixed, unknown], "", { ...EMPTY_RESOURCE_FILTERS, color: ["red", "white"], count: ["2"] })).toEqual([mixed]);
    expect(filterResources([mixed], "", { ...EMPTY_RESOURCE_FILTERS, color: ["red", "blue"] })).toEqual([]);
    expect(unknown.search.color).toEqual([]);
  });

  it("does not pretend an unrecorded series or color is known", () => {
    const unknown = material("Artist PLA special", { brand: "Aliz" });
    expect(unknown.search.series).toEqual([]);
    expect(unknown.search.color).toEqual([]);
    expect(unknown.search.material.map((option) => option.value)).toEqual(["PLA"]);
  });
});
