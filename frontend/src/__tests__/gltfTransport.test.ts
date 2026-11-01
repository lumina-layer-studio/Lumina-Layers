import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { configureGltfTransport } from "../utils/gltfTransport";

function makeGlb(): ArrayBuffer {
  const json = JSON.stringify({
    asset: { version: "2.0" },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ name: "ticket-model", translation: [1, 2, 3] }],
  });
  const chunk = new TextEncoder().encode(json.padEnd(Math.ceil(json.length / 4) * 4));
  const buffer = new ArrayBuffer(20 + chunk.length);
  const header = new DataView(buffer);
  header.setUint32(0, 0x46546c67, true);
  header.setUint32(4, 2, true);
  header.setUint32(8, buffer.byteLength, true);
  header.setUint32(12, chunk.length, true);
  header.setUint32(16, 0x4e4f534a, true);
  new Uint8Array(buffer, 20).set(chunk);
  return buffer;
}

function gzip(data: ArrayBuffer): ArrayBuffer {
  return Uint8Array.from(gzipSync(new Uint8Array(data))).buffer;
}

describe("GLTF transport decoding", () => {
  it.each([false, true])("loads a GLB with leftover gzip = %s", async (compressed) => {
    const loader = new GLTFLoader();
    configureGltfTransport(loader);
    const bytes = makeGlb();
    const model = await loader.parseAsync(compressed ? gzip(bytes) : bytes, "/api/files/");
    expect(model.scene.children[0].name).toBe("ticket-model");
    expect(model.scene.children[0].position.toArray()).toEqual([1, 2, 3]);
  });

  it("keeps JSON glTF support", async () => {
    const loader = new GLTFLoader();
    configureGltfTransport(loader);
    const model = await loader.parseAsync('{"asset":{"version":"2.0"},"scenes":[{}]}', "");
    expect(model.scene.children).toEqual([]);
  });

  it("does not wrap a shared cached loader more than once", async () => {
    const loader = new GLTFLoader();
    configureGltfTransport(loader);
    const parse = loader.parse;
    configureGltfTransport(loader);
    expect(loader.parse).toBe(parse);
    expect((await loader.parseAsync(gzip(makeGlb()), "")).scene.children).toHaveLength(1);
  });

  it("rejects a truncated gzip instead of leaving the model pending", async () => {
    const loader = new GLTFLoader();
    configureGltfTransport(loader);
    await expect(loader.parseAsync(gzip(makeGlb()).slice(0, 12), "")).rejects.toBeDefined();
  });

  it("forwards a parser failure after successful decompression", async () => {
    const loader = new GLTFLoader();
    configureGltfTransport(loader);
    const invalid = new TextEncoder().encode("not a glTF file");
    await expect(loader.parseAsync(gzip(invalid.buffer), "")).rejects.toThrow();
  });
});
