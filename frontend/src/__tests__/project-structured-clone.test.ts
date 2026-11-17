import { describe, expect, it } from "vitest";
import { decodeStructuredClone, encodeStructuredClone } from "../project/structuredCloneCodec";

describe("project structured clone values", () => {
  it("preserves user object tags and own prototype keys alongside actual typed arrays", async () => {
    const state = JSON.parse('{"$type":"typed-array","constructor":"application data","__proto__":{"safe":true},"nested":{"$type":"undefined","value":12}}');
    state.pixels = new Uint8ClampedArray([4, 5, 6, 255]);
    const restored = decodeStructuredClone(await encodeStructuredClone(state));
    expect(restored).toEqual(state);
    expect(Object.getPrototypeOf(restored)).toBe(Object.prototype);
    expect(Object.hasOwn(restored as object, "__proto__")).toBe(true);
  });
  it("rejects oversized nested or binary data before adoption", () => {
    expect(() => decodeStructuredClone([[[1]]], { maxDepth: 2 })).toThrow("complexity");
    expect(() => decodeStructuredClone({ $type: "typed-array", constructor: "Uint8Array", base64: "AAAA" }, { maxBytes: 2 })).toThrow("size");
    expect(() => decodeStructuredClone({ $type: "typed-array", constructor: "__proto__", base64: "" })).toThrow("Unsupported");
  });
});
