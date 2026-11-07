import { fileAsset, projectFile } from "./assets";
import { decodeStructuredClone, encodeStructuredClone } from "./structuredCloneCodec";
import type { JsonValue, ProjectAsset, ProjectSnapshot } from "./types";

/** Keep large raster/source buffers content-addressed rather than repeating them in history JSON. */
export async function encodeWorkshopState(value: unknown): Promise<{ state: JsonValue; assets: ProjectAsset[] }> {
  const assets: ProjectAsset[] = [];
  const binaries = new WeakMap<object, Promise<unknown>>();
  const active = new WeakSet<object>();
  let nodes = 0;
  let binarySequence = 0;
  async function visit(item: unknown, depth: number): Promise<unknown> {
    if (++nodes > 2_000_000 || depth > 28) throw new Error("Workshop state is too complex");
    if (!item || typeof item !== "object") return item;
    if (item instanceof Blob || item instanceof ArrayBuffer || ArrayBuffer.isView(item)) {
      const existing = binaries.get(item);
      if (existing) return existing;
      const sequence = binarySequence++;
      const task = (async () => {
        const encoded = await encodeStructuredClone(item);
        const asset = await fileAsset(`workshop.binary.${sequence}`, new File([JSON.stringify(encoded)], "buffer.json", { type: "application/vnd.lumina.structured-clone+json" }), "resource");
        assets.push(asset);
        return { $projectBinary: asset.assetId };
      })();
      binaries.set(item, task);
      return task;
    }
    if (active.has(item)) throw new Error("Workshop state must not contain cycles");
    active.add(item);
    try {
      if (Array.isArray(item)) {
        const result = [];
        for (const child of item) result.push(await visit(child, depth + 1));
        return result;
      }
      if (item instanceof Map) {
        const result = new Map();
        for (const [key, child] of item) result.set(await visit(key, depth + 1), await visit(child, depth + 1));
        return result;
      }
      if (item instanceof Set) {
        const result = new Set();
        for (const child of item) result.add(await visit(child, depth + 1));
        return result;
      }
      if (Object.getPrototypeOf(item) !== Object.prototype && Object.getPrototypeOf(item) !== null) return item;
      if ("$projectBinary" in item) throw new Error("Reserved Workshop resource marker");
      const result: Record<string, unknown> = {};
      for (const [key, child] of Object.entries(item)) {
        Object.defineProperty(result, key, { value: await visit(child, depth + 1), enumerable: true });
      }
      return result;
    } finally { active.delete(item); }
  }
  return { state: await encodeStructuredClone(await visit(value, 0), { maxNodes: 2_000_000 }), assets };
}

export async function decodeWorkshopState(state: JsonValue, snapshot: ProjectSnapshot, refs: readonly string[]): Promise<unknown> {
  const binaries = new Map<string, Promise<unknown>>();
  let nodes = 0;
  async function visit(item: unknown, depth: number): Promise<unknown> {
    if (++nodes > 2_000_000 || depth > 28) throw new Error("Workshop state is too complex");
    if (!item || typeof item !== "object") return item;
    if ("$projectBinary" in item) {
      const id = (item as { $projectBinary: unknown }).$projectBinary;
      if (typeof id !== "string" || !refs.includes(id)) throw new Error("Invalid Workshop binary reference");
      if (!binaries.has(id)) binaries.set(id, projectFile(snapshot, id)!.text().then((text) => decodeStructuredClone(JSON.parse(text))));
      return binaries.get(id);
    }
    if (Array.isArray(item)) return Promise.all(item.map((child) => visit(child, depth + 1)));
    if (item instanceof Map) return new Map(await Promise.all([...item].map(async ([key, value]) => [await visit(key, depth + 1), await visit(value, depth + 1)] as const)));
    if (item instanceof Set) return new Set(await Promise.all([...item].map((child) => visit(child, depth + 1))));
    if (Object.getPrototypeOf(item) !== Object.prototype && Object.getPrototypeOf(item) !== null) return item;
    return Object.fromEntries(await Promise.all(Object.entries(item).map(async ([key, value]) => [key, await visit(value, depth + 1)])));
  }
  return visit(decodeStructuredClone(state, { maxNodes: 2_000_000 }), 0);
}
