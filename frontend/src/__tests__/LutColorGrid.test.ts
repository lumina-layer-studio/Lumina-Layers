import { describe, it, expect } from "vitest";
import { matchesSearch } from "../components/sections/LutColorGrid";
import type { LutColorEntry } from "../api/types";

/** Helper to create a LutColorEntry for testing. */
function entry(hex: string, rgb: [number, number, number]): LutColorEntry {
  return { hex, rgb };
}

describe("matchesSearch", () => {
  // --- Empty query ---
  it("returns true for empty query (matches everything)", () => {
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "")).toBe(true);
  });

  it("returns true for whitespace-only query", () => {
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "   ")).toBe(true);
  });

  // --- Hex substring matching ---
  it('matches hex substring: "ff00" matches "#ff0000"', () => {
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "ff00")).toBe(true);
  });

  it("matches hex with # prefix in query", () => {
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "#ff00")).toBe(true);
  });

  it("matches hex case-insensitively", () => {
    expect(matchesSearch(entry("#FF0000", [255, 0, 0]), "ff00")).toBe(true);
  });

  it("matches full hex value without #", () => {
    expect(matchesSearch(entry("#aabbcc", [170, 187, 204]), "aabbcc")).toBe(true);
  });

  it("does not match unrelated hex substring", () => {
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "00ff00")).toBe(false);
  });

  // --- RGB exact matching (comma format) ---
  it('matches RGB comma format: "255,0,0" matches rgb [255,0,0]', () => {
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "255,0,0")).toBe(true);
  });

  it('matches RGB with spaces: "255, 0, 0" matches rgb [255,0,0]', () => {
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "255, 0, 0")).toBe(true);
  });

  // --- RGB exact matching (rgb() format) ---
  it('matches rgb() format: "rgb(255,0,0)" matches rgb [255,0,0]', () => {
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "rgb(255,0,0)")).toBe(true);
  });

  it('matches rgb() format with spaces: "rgb(255, 0, 0)"', () => {
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "rgb(255, 0, 0)")).toBe(true);
  });

  // --- RGB non-matching ---
  it("does not match when RGB values differ", () => {
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "255,0,1")).toBe(false);
  });

  it('partial RGB does not match: "255,0" should not match', () => {
    // "255,0" has only two numbers, so the RGB regex won't capture three groups.
    // It also won't match as hex substring for "#ff0000".
    expect(matchesSearch(entry("#ff0000", [255, 0, 0]), "255,0")).toBe(false);
  });

  // --- Edge cases ---
  it("matches black color via RGB", () => {
    expect(matchesSearch(entry("#000000", [0, 0, 0]), "0,0,0")).toBe(true);
  });

  it("matches white color via RGB", () => {
    expect(matchesSearch(entry("#ffffff", [255, 255, 255]), "255,255,255")).toBe(true);
  });
});
