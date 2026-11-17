import { beforeEach, expect, it, vi } from "vitest";
import { ColorMode } from "../api/types";
import { fetchLutCatalog } from "../api/lut";
import { fetchLutList } from "../api/converter";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";

vi.mock("../api/lut", async (original) => ({
  ...await original<typeof import("../api/lut")>(),
  fetchLutCatalog: vi.fn(),
  fetchLutInfo: vi.fn(() => new Promise(() => {})),
}));
vi.mock("../api/converter", async (original) => ({
  ...await original<typeof import("../api/converter")>(), fetchLutList: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.setItem("lumina_lastLut", "Brand - old");
  useConverterStore.setState({ ...DEFAULT_STATE, source_version: "legacy",
    lut_name: "Brand - old", lut_names: ["Brand - old", "Personal"],
    target_width_mm: 143, spacer_thick: 2.2, color_mode: ColorMode.FOUR_COLOR_RYBW });
});

it.each(["list", "catalog"])("restores a migrated remembered selection from %s without clearing the task", async (source) => {
  const luts = ["Cloud - Brand - old", "Personal"].map((name) => ({
    name, color_mode: ColorMode.FOUR_COLOR_RYBW, path: `${name}.json`,
  }));
  const legacy_aliases = { "Brand - old": "Cloud - Brand - old" };
  vi.mocked(fetchLutList).mockResolvedValue({ luts, legacy_aliases });
  vi.mocked(fetchLutCatalog).mockResolvedValue({ legacy_groups: [{ group_name: "Cloud", items: luts }], native_brand_groups: [], legacy_aliases });
  if (source === "list") await useConverterStore.getState().fetchLutList();
  else await useConverterStore.getState().fetchLutCatalog();
  expect(useConverterStore.getState()).toMatchObject({
    lut_name: "Cloud - Brand - old", lut_names: ["Cloud - Brand - old", "Personal"],
    target_width_mm: 143, spacer_thick: 2.2, color_mode: ColorMode.FOUR_COLOR_RYBW,
  });
  expect(localStorage.getItem("lumina_lastLut")).toBeTruthy();
});
