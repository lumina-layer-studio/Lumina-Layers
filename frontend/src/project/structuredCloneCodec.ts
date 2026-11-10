import type { JsonValue } from "./types";

export type StructuredCloneNode = JsonValue;

export interface StructuredCloneLimits {
  maxDepth: number;
  maxNodes: number;
  maxBytes: number;
}

export const DEFAULT_STRUCTURED_CLONE_LIMITS: StructuredCloneLimits = {
  maxDepth: 32,
  maxNodes: 10000,
  maxBytes: 64 * 1024 * 1024,
};

export class StructuredCloneCodecError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StructuredCloneCodecError";
  }
}

type TaggedNode = {
  $type: string;
  [key: string]: JsonValue;
};

function isTaggedNode(value: JsonValue): value is TaggedNode {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    typeof value.$type === "string"
  );
}

function utf8Size(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function bytesToBase64(bytes: Uint8Array): string {
  const chunkSize = 0x8000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(
      ...bytes.subarray(offset, Math.min(bytes.length, offset + chunkSize)),
    );
  }
  if (typeof btoa === "function") return btoa(binary);
  throw new StructuredCloneCodecError("Base64 encoding is unavailable");
}

function base64ToBytes(value: string): Uint8Array {
  if (typeof atob !== "function") {
    throw new StructuredCloneCodecError("Base64 decoding is unavailable");
  }
  let binary: string;
  try {
    binary = atob(value);
  } catch {
    throw new StructuredCloneCodecError("Invalid binary snapshot payload");
  }
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function assertPlainObject(value: object): void {
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new StructuredCloneCodecError(
      "Only structured-clone built-ins and plain objects are supported",
    );
  }
}

function asJson(value: unknown): JsonValue {
  return value as JsonValue;
}

export async function encodeStructuredClone(
  value: unknown,
  limits: Partial<StructuredCloneLimits> = {},
): Promise<StructuredCloneNode> {
  const effective = { ...DEFAULT_STRUCTURED_CLONE_LIMITS, ...limits };
  const active = new WeakSet<object>();
  let nodes = 0;
  let bytes = 0;

  const visit = async (current: unknown, depth: number): Promise<JsonValue> => {
    if (depth > effective.maxDepth) {
      throw new StructuredCloneCodecError("Snapshot state is too deeply nested");
    }
    nodes += 1;
    if (nodes > effective.maxNodes) {
      throw new StructuredCloneCodecError("Snapshot state has too many values");
    }
    if (
      current === null ||
      typeof current === "string" ||
      typeof current === "boolean"
    ) {
      if (typeof current === "string") bytes += utf8Size(current);
      return current;
    }
    if (typeof current === "number") {
      if (!Number.isFinite(current)) {
        throw new StructuredCloneCodecError("Snapshot state has a non-finite number");
      }
      return current;
    }
    if (typeof current === "undefined") return { $type: "undefined" };
    if (typeof current === "bigint") {
      return { $type: "bigint", value: current.toString() };
    }
    if (typeof current === "function" || typeof current === "symbol") {
      throw new StructuredCloneCodecError("Snapshot state contains an unsupported value");
    }

    const objectValue = current as object;
    if (active.has(objectValue)) {
      throw new StructuredCloneCodecError("Snapshot state must not contain cycles");
    }
    active.add(objectValue);
    try {
      if (objectValue instanceof ArrayBuffer) {
        const encoded = bytesToBase64(new Uint8Array(objectValue));
        bytes += objectValue.byteLength;
        return { $type: "array-buffer", base64: encoded };
      }
      if (ArrayBuffer.isView(objectValue)) {
        const view = objectValue as ArrayBufferView;
        const raw = new Uint8Array(
          view.buffer.slice(view.byteOffset, view.byteOffset + view.byteLength),
        );
        bytes += raw.byteLength;
        const type = view instanceof DataView
          ? "DataView"
          : view.constructor.name;
        return {
          $type: "typed-array",
          constructor: type,
          base64: bytesToBase64(raw),
        };
      }
      if (typeof Blob !== "undefined" && objectValue instanceof Blob) {
        const raw = new Uint8Array(await objectValue.arrayBuffer());
        bytes += raw.byteLength;
        return {
          $type: "blob",
          mimeType: objectValue.type,
          base64: bytesToBase64(raw),
        };
      }
      if (objectValue instanceof Date) {
        if (Number.isNaN(objectValue.getTime())) {
          throw new StructuredCloneCodecError("Snapshot state has an invalid date");
        }
        return { $type: "date", value: objectValue.toISOString() };
      }
      if (objectValue instanceof RegExp) {
        return { $type: "regexp", source: objectValue.source, flags: objectValue.flags };
      }
      if (objectValue instanceof Map) {
        const entries: JsonValue[] = [];
        for (const [key, item] of objectValue.entries()) {
          entries.push([await visit(key, depth + 1), await visit(item, depth + 1)]);
        }
        return { $type: "map", entries };
      }
      if (objectValue instanceof Set) {
        const values: JsonValue[] = [];
        for (const item of objectValue.values()) {
          values.push(await visit(item, depth + 1));
        }
        return { $type: "set", values };
      }
      if (Array.isArray(objectValue)) {
        return Promise.all(objectValue.map((item) => visit(item, depth + 1)));
      }
      assertPlainObject(objectValue);
      const result: Record<string, JsonValue> = {};
      for (const key of Object.keys(objectValue)) {
        const child = await visit(
          (objectValue as Record<string, unknown>)[key],
          depth + 1,
        );
        Object.defineProperty(result, key, { value: child, enumerable: true });
      }
      return Object.hasOwn(result, "$type")
        ? { $type: "object", entries: Object.entries(result) }
        : result;
    } finally {
      active.delete(objectValue);
    }
  };

  const encoded = await visit(value, 0);
  if (bytes > effective.maxBytes) {
    throw new StructuredCloneCodecError("Snapshot binary data exceeds its limit");
  }
  return encoded;
}

export function decodeStructuredClone(value: StructuredCloneNode, limits: Partial<StructuredCloneLimits> = {}): unknown {
  const effective = { ...DEFAULT_STRUCTURED_CLONE_LIMITS, ...limits };
  let nodes = 0;
  let bytes = 0;
  let depth = 0;
  const visit = (current: JsonValue): unknown => {
    if (++nodes > effective.maxNodes || ++depth > effective.maxDepth) throw new StructuredCloneCodecError("Snapshot state exceeds its complexity limit");
    try { return decode(current); } finally { depth--; }
  };
  const decode = (current: JsonValue): unknown => {
    if (typeof current === "string") bytes += utf8Size(current);
    else if (isTaggedNode(current)) {
      for (const item of Object.values(current)) if (typeof item === "string") bytes += utf8Size(item);
    }
    if (bytes > effective.maxBytes) throw new StructuredCloneCodecError("Snapshot data exceeds its size limit");
    if (typeof current === "number" && !Number.isFinite(current)) throw new StructuredCloneCodecError("Invalid number");
    if (!isTaggedNode(current)) {
      if (Array.isArray(current)) return current.map(visit);
      if (current && typeof current === "object") {
        return Object.fromEntries(
          Object.entries(current).map(([key, item]) => [key, visit(item)]),
        );
      }
      return current;
    }
    switch (current.$type) {
      case "object":
        if (!Array.isArray(current.entries)) throw new StructuredCloneCodecError("Invalid object");
        return Object.fromEntries(current.entries.map((entry) => {
          if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== "string") throw new StructuredCloneCodecError("Invalid object entry");
          return [entry[0], visit(entry[1])];
        }));
      case "undefined":
        return undefined;
      case "bigint":
        if (typeof current.value !== "string") throw new StructuredCloneCodecError("Invalid bigint");
        return BigInt(current.value);
      case "array-buffer":
        if (typeof current.base64 !== "string") throw new StructuredCloneCodecError("Invalid ArrayBuffer");
        return base64ToBytes(current.base64).buffer;
      case "typed-array": {
        if (typeof current.base64 !== "string" || typeof current.constructor !== "string") {
          throw new StructuredCloneCodecError("Invalid typed array");
        }
        const bytes = base64ToBytes(current.base64);
        if (current.constructor === "DataView") return new DataView(bytes.buffer);
        const constructors: Record<string, new (buffer: ArrayBuffer) => unknown> = {
          Uint8Array,
          Uint8ClampedArray,
          Uint16Array,
          Uint32Array,
          Int8Array,
          Int16Array,
          Int32Array,
          Float32Array,
          Float64Array,
          BigInt64Array,
          BigUint64Array,
        };
        const Ctor = Object.hasOwn(constructors, current.constructor) ? constructors[current.constructor] : null;
        if (!Ctor) throw new StructuredCloneCodecError("Unsupported typed array");
        return new Ctor(bytes.buffer);
      }
      case "blob":
        if (typeof current.base64 !== "string" || typeof current.mimeType !== "string") {
          throw new StructuredCloneCodecError("Invalid Blob");
        }
        return new Blob([base64ToBytes(current.base64)], { type: current.mimeType });
      case "date":
        if (typeof current.value !== "string") throw new StructuredCloneCodecError("Invalid date");
        if (!Number.isFinite(Date.parse(current.value))) throw new StructuredCloneCodecError("Invalid date");
        return new Date(current.value);
      case "regexp":
        if (typeof current.source !== "string" || typeof current.flags !== "string") {
          throw new StructuredCloneCodecError("Invalid regexp");
        }
        return new RegExp(current.source, current.flags);
      case "map":
        if (!Array.isArray(current.entries)) throw new StructuredCloneCodecError("Invalid map");
        return new Map(
          current.entries.map((entry) => {
            if (!Array.isArray(entry) || entry.length !== 2) {
              throw new StructuredCloneCodecError("Invalid map entry");
            }
            return [visit(entry[0]), visit(entry[1])];
          }),
        );
      case "set":
        if (!Array.isArray(current.values)) throw new StructuredCloneCodecError("Invalid set");
        return new Set(current.values.map(visit));
      default:
        throw new StructuredCloneCodecError("Unknown structured-clone tag");
    }
  };
  return visit(asJson(value));
}
