import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { fetchCloudLutPreviews, fetchLutCatalog, fetchLutDetails, fetchLutDetailsCatalog } from "../api/lut";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const mockGet = vi.mocked(apiClient.get);

beforeEach(() => {
  vi.resetAllMocks();
});

describe("cloud LUT preview requests", () => {
  it.each([24, 25, 27, 28, 49])("loads all %i visible previews within the server's 24-ID limit", async (count) => {
    const ids = Array.from({ length: count }, (_, i) => `lut_${i}`);
    const signal = new AbortController().signal;
    mockGet.mockImplementation(async (_url, config) => {
      const requested = (config!.params as URLSearchParams).getAll("lut_id");
      if (requested.length > 24) throw new Error("HTTP 422: at most 24 LUT IDs");
      return { data: { source_scope: "public", previews: requested.map((lut_id) => ({ lut_id })) } };
    });

    const result = await fetchCloudLutPreviews(ids, ["official", "community"], signal);

    expect(result.source_scope).toBe("public");
    expect(result.previews.map((row) => row.lut_id)).toEqual(ids);
    expect(mockGet).toHaveBeenCalledTimes(Math.ceil(count / 24));
    for (const [url, config] of mockGet.mock.calls) {
      expect(url).toBe("/lut-registry/previews");
      expect((config!.params as URLSearchParams).getAll("channel")).toEqual(["official", "community"]);
      expect(config).toMatchObject({ signal, suppressErrorTicket: true });
    }
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("does not combine batches from different registry scopes", async () => {
    mockGet.mockResolvedValueOnce({ data: { source_scope: "public", previews: [] } })
      .mockResolvedValueOnce({ data: { source_scope: "private", previews: [] } });
    await expect(fetchCloudLutPreviews(
      Array.from({ length: 25 }, (_, i) => `lut_${i}`), ["official"], new AbortController().signal,
    )).rejects.toThrow(/source/i);
  });

  it("stops queuing batches when a page change cancels the request", async () => {
    const controller = new AbortController();
    mockGet.mockImplementationOnce(async () => {
      controller.abort();
      return { data: { source_scope: "public", previews: [] } };
    });
    await expect(fetchCloudLutPreviews(
      Array.from({ length: 25 }, (_, i) => `lut_${i}`), ["official"], controller.signal,
    )).rejects.toMatchObject({ name: "AbortError" });
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("leaves a failed later batch retryable and returns every preview after retry", async () => {
    const ids = Array.from({ length: 25 }, (_, i) => `lut_${i}`);
    const signal = new AbortController().signal;
    mockGet.mockResolvedValueOnce({ data: { source_scope: "public", previews: ids.slice(0, 24).map((lut_id) => ({ lut_id })) } })
      .mockRejectedValueOnce(new Error("offline"));
    await expect(fetchCloudLutPreviews(ids, ["official"], signal)).rejects.toThrow("offline");
    mockGet.mockImplementation(async (_url, config) => ({
      data: { source_scope: "public", previews: (config!.params as URLSearchParams).getAll("lut_id").map((lut_id) => ({ lut_id })) },
    }));
    const result = await fetchCloudLutPreviews(ids, ["official"], signal);
    expect(result.previews.map((row) => row.lut_id)).toEqual(ids);
  });
});

describe("lut details api", () => {
  it("keeps legacy entries but hides native brand bundles in the converter catalog", async () => {
    const legacy = { group_name: "Printed", items: [] };
    mockGet.mockResolvedValueOnce({ data: {
      legacy_groups: [legacy],
      native_brand_groups: [{ brand_key: "bambulab_pla" }],
    } });

    const result = await fetchLutCatalog();

    expect(result.legacy_groups).toEqual([legacy]);
    expect(result.native_brand_groups).toEqual([]);
  });

  it("hides predictive LUTs from all consumers of the grouped library catalog", async () => {
    const kinds = ["legacy_lookup", "colordb_backed", "predictive_stage_model", "predictive_package"];
    mockGet.mockResolvedValueOnce({ data: { groups: [
      { manufacturer: "Mixed", items: kinds.map((source_kind) => ({ name: source_kind, source_kind })) },
      { manufacturer: "Predictive only", items: [{ name: "hidden", source_kind: "predictive_package" }] },
    ] } });

    const result = await fetchLutDetailsCatalog();

    expect(result.groups.map((group) => group.manufacturer)).toEqual(["Mixed"]);
    expect(result.groups[0].items.map((item) => item.name)).toEqual(["legacy_lookup"]);
  });

  it("fetchLutDetailsCatalog loads the grouped catalog", async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        groups: [
          {
            manufacturer: "Bambu Lab",
            items: [
              {
                name: "Bambu Lab - PLA - RYBW",
                path: "lut-ref/fp-a.json",
                color_mode: "4-Color (RYBW)",
                source_kind: "legacy_lookup",
                manufacturer: "Bambu Lab",
                material_type: "PLA",
                manufacturer_source: "metadata",
                material_source: "folder",
                search_tokens: ["bambulab", "pla", "rybw"],
              },
            ],
          },
        ],
      },
    });

    const result = await fetchLutDetailsCatalog();

    expect(mockGet).toHaveBeenCalledWith("/lut/details/catalog");
    expect(result.groups[0].manufacturer).toBe("Bambu Lab");
    expect(result.groups[0].items[0]).toMatchObject({
      material_type: "PLA",
      search_tokens: ["bambulab", "pla", "rybw"],
    });
  });

  it("can suppress client logs for background catalog probes", async () => {
    mockGet.mockResolvedValueOnce({ data: { groups: [] } });

    const result = await fetchLutDetailsCatalog({ suppressClientLog: true });

    expect(mockGet).toHaveBeenCalledWith("/lut/details/catalog", {
      suppressClientLog: true,
    });
    expect(result.groups).toEqual([]);
  });

  it("fetchLutDetails loads one detail payload", async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        name: "Bambu Lab - PLA - RYBW",
        path: "lut-ref/fp-a.json",
        manufacturer: "Bambu Lab",
        manufacturer_source: "metadata",
        material_type: "PLA",
        material_source: "folder",
        color_mode: "4-Color (RYBW)",
        color_count: 4,
        source_kind: "legacy_lookup",
        schema_version: "1.0",
        capabilities: ["legacy_lookup"],
        supported_modes: [],
        raw_metadata: {},
        palette: [],
        coverage_stats: {
          entry_count: 4,
          plotted_point_count: 4,
          l_range: { min: 0, max: 100 },
          a_range: { min: -40, max: 60 },
          b_range: { min: -50, max: 50 },
          r_range: { min: 0, max: 255 },
          g_range: { min: 0, max: 255 },
          b_rgb_range: { min: 0, max: 255 },
        },
        lab_points: [],
        lab_points_3d: [],
        lab_hull: [],
        rgb_points: [],
        max_color_layers: 5,
        layer_height_mm: 0.08,
        line_width_mm: 0.42,
        base_layers: 10,
        base_channel_idx: 0,
        layer_order: "Top2Bottom",
      },
    });

    const result = await fetchLutDetails("Bambu Lab - PLA - RYBW");

    expect(mockGet).toHaveBeenCalledWith("/lut/Bambu%20Lab%20-%20PLA%20-%20RYBW/details");
    expect(result).toMatchObject({
      color_count: 4,
      manufacturer: "Bambu Lab",
      lab_points_3d: [],
      coverage_stats: {
        entry_count: 4,
      },
      raw_metadata: {},
    });
  });
});
