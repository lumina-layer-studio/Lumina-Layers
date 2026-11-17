import { describe, expect, it } from "vitest";
import { calibrationPreview } from "../utils/calibrationPreview";

describe("calibration thumbnails", () => {
  it("samples actual, paired black and white substrate readings in their original order", () => {
    const black = Array.from({ length: 36 }, (_, layer) => [layer, 4, 110]);
    const white = Array.from({ length: 36 }, (_, layer) => [100, layer, 8]);
    const preview = calibrationPreview({
      kind: "materials", rgb: [255, 0, 0], display: { preview_swatches: { black, white, board_thickness_mm: 2.96 } },
    });
    expect(preview.kind).toBe("measured");
    const layers = ["00", "02", "04", "06", "08", "0a", "0c", "0e", "10", "13", "15", "17", "19", "1b", "1d", "1f", "21", "23"];
    expect(preview.black).toEqual(layers.map((v) => `#${v}046e`));
    expect(preview.white).toEqual(layers.map((v) => `#64${v}08`));
    expect(preview.boardThicknessMm).toBe(2.96);
    expect(black[0]).toEqual([0, 4, 110]);
  });

  it("falls back to an illustrative color without manufacturing black or white substrate measurements", () => {
    const input = { kind: "materials" as const, rgb: [0, 14, 255], display: {
      preview_swatches: { black: [[0, 0, 0], [4, 5, 6]], white: [[9, 8, 7]] },
      palette_rgb: [[240, 255, 255]], estimated_rgb: [240, 255, 255],
    } };
    expect(calibrationPreview(input)).toEqual({
      kind: "illustrative", black: ["#000eff"], white: ["#000eff"],
    });
    expect(calibrationPreview({ kind: "materials", display: { estimated_rgb: [0, 0, 0] } }).black[0]).toBe("#000000");
    expect(calibrationPreview({ kind: "materials", display: { rgb: "#FFFFFF" } }).white[0]).toBe("#ffffff");
  });

  it("only labels measured samples as measured and can render recorded model samples as illustrations", () => {
    const samples = { black: [[0, 4, 5], [7, 8, 9]], white: [[90, 75, 2], [40, 80, 60]] };
    for (const [source, kind] of [["measured", "measured"], ["model", "illustrative"], ["unknown", "unknown"]]) {
      expect(calibrationPreview({ kind: "materials", display: { preview_swatches: { ...samples, source } } }).kind).toBe(kind);
    }
    expect(calibrationPreview({ kind: "materials", display: { preview_swatches: { black: ["#abcdef"], white: ["#dddddd"] } } }).kind).toBe("unknown");
  });

  it("uses explicit channel colors ahead of conflicting modes and preserves source channel order", () => {
    const raw = [[12, 34, 56], [17, 18, 19], [235, 2, 106]];
    const result = calibrationPreview({
      kind: "luts", mode: "4-Color (RYBW)", display: { palette_rgb: raw },
      metadata: { palette: { White: { hex_color: "#ffffff" }, Cyan: { hex_color: "#00ffff" } } },
    });
    expect(result.kind).toBe("palette");
    expect(result.black).toEqual(["#0c2238", "#111213", "#eb026a"]);
    expect(result.white).toEqual(result.black);
    expect(calibrationPreview({ kind: "luts", metadata: { palette_bgr: raw } }).black[0]).toBe("#38220c");
    expect(raw[0]).toEqual([12, 34, 56]);
  });

  it("reads keyed JSON, native channel arrays, and explicit RGB / BGR slot metadata", () => {
    const keyed = calibrationPreview({ kind: "luts", metadata: { base_channel_idx: 1, palette: {
      Magenta: { material: "PLA", hex_color: "#ec008c" }, White: { material: "PLA", hex_color: "#ffffff" },
    } } });
    expect([keyed.black[0], keyed.black.at(-1)]).toEqual(["#ec008c", "#ffffff"]);
    const native = calibrationPreview({ kind: "luts", metadata: { palette: [
      { color: "Bambu Green" }, { color: "Black" }, { color_name: "Slot 7 (Deep Blue)" }, { color: "未知", bgr: [55, 33, 11] },
    ] } });
    expect(new Set(native.black)).toEqual(new Set(["#00ae42", "#000000", "#0a2989", "#0b2137"]));
    expect(calibrationPreview({ kind: "luts", metadata: { channels: [{ rgb: [30, 20, 1] }, { color: "白色" }] } }).black[0]).toBe("#1e1401");
    const reordered = calibrationPreview({ kind: "luts", metadata: { ordered_channels: ["Ink", "Ivory"],
      palette: { Ivory: { hex: "#f1daaa" }, Ink: { hex_color: "#123456" } } } });
    expect([reordered.black[0], reordered.black.at(-1)]).toEqual(["#123456", "#f1daaa"]);
  });

  it("recognizes explicit CMYW and RYBW variants independently of their shared color count", () => {
    const cmyw = calibrationPreview({ kind: "luts", mode: "4-color", name: "赛纳&4色PETG&CMYW-品红-青-黄-白" });
    const rybw = calibrationPreview({ kind: "luts", mode: "4-color", name: "bambulab_pla_basic_rybw" });
    expect(cmyw.kind).toBe("palette");
    expect(rybw.kind).toBe("palette");
    expect(cmyw.black).toContain("#0086d6");
    expect(cmyw.black).not.toContain("#dc143c");
    expect(rybw.black).toContain("#dc143c");
    expect(rybw.black).not.toContain("#0086d6");
    expect(calibrationPreview({ kind: "luts", mode: "6-color-rybw-1296" }).white).toContain("#00ae42");
    expect(calibrationPreview({ kind: "luts", mode: "6-Color (CMYWGK 1296)" }).white).toContain("#0086d6");
    expect(calibrationPreview({ kind: "luts", mode: "BW (Black & White)" }).black).toEqual(["#ffffff", "#000000"]);
    expect(calibrationPreview({ kind: "luts", mode: "5-Color Extended" }).kind).toBe("palette");
    expect(calibrationPreview({ kind: "luts", mode: "8-Color Max" }).kind).toBe("palette");
    for (const mode of ["2-color", "4-color", "6色", "8-color", "Merged_6-Color+BW+4-Color", "CMYW/RYBW"]) {
      expect(calibrationPreview({ kind: "luts", mode }).kind).toBe("unknown");
    }
  });

  it("keeps every channel through 16 and samples larger custom palettes without inventing colors", () => {
    for (const count of [2, 4, 5, 6, 8, 12, 16, 27]) {
      const slots = Array.from({ length: count }, (_, i) => [i, 100, 225]);
      const preview = calibrationPreview({ kind: "luts", display: { palette_rgb: slots } });
      const expected = slots.map(([r]) => "#" + r.toString(16).padStart(2, "0") + "64e1");
      if (count <= 16) {
        expect(preview.black).toEqual(expected);
      } else {
        const indices = preview.black.map((color) => expected.indexOf(color));
        expect(indices).toHaveLength(16);
        expect(indices.every((slot, i) => slot >= 0 && (i === 0 || slot > indices[i - 1]))).toBe(true);
      }
      expect(preview.black[0]).toBe(expected[0]);
      expect(preview.black.at(-1)).toBe(expected.at(-1));
    }
  });

  it("does not use measured colors, product IDs, or malformed metadata as LUT channel identities", () => {
    const unknown = calibrationPreview({ kind: "luts", mode: "4-color", rgb: [255, 0, 0], metadata: { palette: {
      Scarlet: { hex_color: "red" }, White: { hex_color: "#ffffff" },
    } } });
    expect(unknown.kind).toBe("unknown");
    expect(new Set([...unknown.black, ...unknown.white]).size).toBe(1);
    for (const rgb of [["255", 0, 1], [255, 0, 256], [1.2, 3, 4], [23, 154, 29, 0], "#ffff", "#11223344", { bgr: [1, 2, 3] }]) {
      expect(calibrationPreview({ kind: "materials", rgb }).kind).toBe("unknown");
    }
    expect(calibrationPreview({ kind: "luts", mode: "4-color", display: {
      palette_rgb: [[255, 0, 0], [0, -1, 0]], preview_swatches: { black: [], white: [] },
    } }).kind).toBe("unknown");
  });
});
