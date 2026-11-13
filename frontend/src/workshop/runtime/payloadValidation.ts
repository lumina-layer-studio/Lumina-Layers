import type {
  HostWorkshopRpcMethod,
  WorkshopModuleIdentity,
} from "../contracts";


export const WORKSHOP_RPC_CONTROL_PAYLOAD_BYTES = 1 * 1024 * 1024;
export const WORKSHOP_RPC_BINARY_PAYLOAD_BYTES = 64 * 1024 * 1024;

const MAX_PAYLOAD_DEPTH = 100;
const MAX_PROJECT_ID_LENGTH = 256;
const MAX_SCHEMA_VERSION_LENGTH = 128;
const MAX_STATUS_TEXT_LENGTH = 500;
const MAX_DIAGNOSTIC_FIELDS = 64;
const MAX_BACKEND_INPUTS = 8;
const MAX_BACKEND_PARAMS_BYTES = 64 * 1024;
const BACKEND_TASK_ID = /^[0-9a-f]{32}$/;
const BACKEND_OPERATION = /^[a-z][a-z0-9.-]{0,63}$/;
const BACKEND_FILE_KEY = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const BACKEND_FILE_NAME = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$/;
const BACKEND_MIME_TYPE =
  /^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}\/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$/;

export type RpcPayloadValidationCode =
  | "rpc-payload-invalid"
  | "rpc-payload-too-large"
  | "rpc-binary-too-large"
  | "rpc-identity-mismatch";

export class RpcPayloadValidationError extends Error {
  readonly code: RpcPayloadValidationCode;

  constructor(code: RpcPayloadValidationCode, message: string) {
    super(message);
    this.name = "RpcPayloadValidationError";
    this.code = code;
  }
}

interface PayloadMeasurement {
  controlBytes: number;
  binaryBytes: number;
}

interface MeasureState {
  active: WeakSet<object>;
  visited: WeakSet<object>;
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function invalidPayload(message: string): never {
  throw new RpcPayloadValidationError(
    "rpc-payload-invalid",
    message,
  );
}

function isBlobValue(value: object): value is Blob {
  const prototype = Object.getPrototypeOf(value) as
    | { constructor?: { name?: string } }
    | null;
  return (
    (typeof Blob !== "undefined" && value instanceof Blob) ||
    (Object.prototype.toString.call(value) === "[object Blob]" &&
      prototype?.constructor?.name === "Blob" &&
      typeof (value as Blob).slice === "function")
  );
}

function addMeasurement(
  left: PayloadMeasurement,
  right: PayloadMeasurement,
): PayloadMeasurement {
  return {
    controlBytes: left.controlBytes + right.controlBytes,
    binaryBytes: left.binaryBytes + right.binaryBytes,
  };
}

function measureValue(
  value: unknown,
  state: MeasureState,
  depth: number,
): PayloadMeasurement {
  if (depth > MAX_PAYLOAD_DEPTH) {
    return invalidPayload("Workshop RPC payload nesting is too deep.");
  }
  if (value === null || value === undefined) {
    return { controlBytes: 0, binaryBytes: 0 };
  }
  switch (typeof value) {
    case "string":
      return {
        controlBytes: utf8Bytes(value),
        binaryBytes: 0,
      };
    case "number":
    case "bigint":
      return { controlBytes: 8, binaryBytes: 0 };
    case "boolean":
      return { controlBytes: 1, binaryBytes: 0 };
    case "symbol":
    case "function":
      return invalidPayload(
        "Workshop RPC payload contains a non-cloneable value.",
      );
    case "object":
      break;
    default:
      return invalidPayload(
        "Workshop RPC payload contains an unsupported value.",
      );
  }

  const objectValue = value as object;
  if (state.active.has(objectValue)) {
    return invalidPayload(
      "Workshop RPC payload must not contain cycles.",
    );
  }
  if (state.visited.has(objectValue)) {
    return { controlBytes: 0, binaryBytes: 0 };
  }
  state.active.add(objectValue);
  let measurement: PayloadMeasurement;
  try {
    if (
      typeof SharedArrayBuffer !== "undefined" &&
      value instanceof SharedArrayBuffer
    ) {
      return invalidPayload(
        "SharedArrayBuffer is not allowed in Workshop RPC.",
      );
    }
    if (value instanceof ArrayBuffer) {
      measurement = {
        controlBytes: 8,
        binaryBytes: value.byteLength,
      };
    } else if (ArrayBuffer.isView(value)) {
      measurement = {
        controlBytes: 8,
        binaryBytes: value.byteLength,
      };
    } else if (isBlobValue(value)) {
      measurement = {
        controlBytes: utf8Bytes(value.type),
        binaryBytes: value.size,
      };
    } else if (value instanceof Date) {
      if (Number.isNaN(value.getTime())) {
        return invalidPayload(
          "Workshop RPC payload contains an invalid date.",
        );
      }
      measurement = { controlBytes: 8, binaryBytes: 0 };
    } else if (value instanceof RegExp) {
      measurement = {
        controlBytes:
          utf8Bytes(value.source) + utf8Bytes(value.flags),
        binaryBytes: 0,
      };
    } else if (value instanceof Map) {
      measurement = { controlBytes: 8, binaryBytes: 0 };
      for (const [key, item] of value) {
        measurement = addMeasurement(
          measurement,
          measureValue(key, state, depth + 1),
        );
        measurement = addMeasurement(
          measurement,
          measureValue(item, state, depth + 1),
        );
      }
    } else if (value instanceof Set) {
      measurement = { controlBytes: 8, binaryBytes: 0 };
      for (const item of value) {
        measurement = addMeasurement(
          measurement,
          measureValue(item, state, depth + 1),
        );
      }
    } else if (Array.isArray(value)) {
      measurement = { controlBytes: 8, binaryBytes: 0 };
      for (const item of value) {
        measurement = addMeasurement(
          measurement,
          measureValue(item, state, depth + 1),
        );
      }
    } else {
      const prototype = Object.getPrototypeOf(value);
      if (prototype !== Object.prototype && prototype !== null) {
        return invalidPayload(
          "Workshop RPC payload contains a class instance.",
        );
      }
      measurement = { controlBytes: 8, binaryBytes: 0 };
      for (const key of Reflect.ownKeys(value)) {
        if (typeof key !== "string") {
          return invalidPayload(
            "Workshop RPC payload contains a symbol key.",
          );
        }
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (
          descriptor?.get !== undefined ||
          descriptor?.set !== undefined
        ) {
          return invalidPayload(
            "Workshop RPC payload contains an accessor.",
          );
        }
        if (descriptor?.enumerable) {
          measurement.controlBytes += utf8Bytes(key);
          measurement = addMeasurement(
            measurement,
            measureValue(
              (value as Record<string, unknown>)[key],
              state,
              depth + 1,
            ),
          );
        }
      }
    }
  } finally {
    state.active.delete(objectValue);
  }
  state.visited.add(objectValue);
  return measurement;
}

export function assertRpcPayloadBounds(payload: unknown): void {
  const measurement = measureValue(
    payload,
    {
      active: new WeakSet<object>(),
      visited: new WeakSet<object>(),
    },
    0,
  );
  if (
    measurement.controlBytes >
    WORKSHOP_RPC_CONTROL_PAYLOAD_BYTES
  ) {
    throw new RpcPayloadValidationError(
      "rpc-payload-too-large",
      "Workshop RPC control payload exceeds 1 MiB.",
    );
  }
  if (
    measurement.binaryBytes >
    WORKSHOP_RPC_BINARY_PAYLOAD_BYTES
  ) {
    throw new RpcPayloadValidationError(
      "rpc-binary-too-large",
      "Workshop RPC binary payload exceeds 64 MiB.",
    );
  }
}

function isRecord(
  value: unknown,
): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) === Object.prototype
  );
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const keys = Object.keys(value);
  const allowed = new Set([...required, ...optional]);
  return (
    required.every((key) => key in value) &&
    keys.every((key) => allowed.has(key))
  );
}

function boundedString(
  value: unknown,
  maximum: number,
): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= maximum &&
    !value.includes("\0")
  );
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function cloneProjectValue(value: unknown): unknown {
  try {
    return structuredClone(value);
  } catch {
    return invalidPayload(
      "Workshop project payload is not structured-cloneable.",
    );
  }
}

function validateEmptyPayload(payload: unknown): Record<string, never> {
  if (!isRecord(payload) || Object.keys(payload).length !== 0) {
    return invalidPayload("Workshop RPC method expects an empty payload.");
  }
  return {};
}

function validateProjectSave(payload: unknown): unknown {
  if (
    !isRecord(payload) ||
    !hasOnlyKeys(payload, ["record"]) ||
    !isRecord(payload.record)
  ) {
    return invalidPayload("Project save payload is invalid.");
  }
  const record = payload.record;
  if (
    !hasOnlyKeys(record, [
      "projectId",
      "schemaVersion",
      "createdAt",
      "updatedAt",
      "project",
    ]) ||
    !boundedString(record.projectId, MAX_PROJECT_ID_LENGTH) ||
    !boundedString(
      record.schemaVersion,
      MAX_SCHEMA_VERSION_LENGTH,
    ) ||
    !boundedString(record.createdAt, 64) ||
    !boundedString(record.updatedAt, 64)
  ) {
    return invalidPayload("Workshop project record is invalid.");
  }
  return {
    record: {
      projectId: record.projectId,
      schemaVersion: record.schemaVersion,
      createdAt: record.createdAt,
      updatedAt: record.updatedAt,
      project: cloneProjectValue(record.project),
    },
  };
}

function validateProjectIdPayload(payload: unknown): unknown {
  if (
    !isRecord(payload) ||
    !hasOnlyKeys(payload, ["projectId"]) ||
    !boundedString(payload.projectId, MAX_PROJECT_ID_LENGTH)
  ) {
    return invalidPayload("Workshop project ID payload is invalid.");
  }
  return { projectId: payload.projectId };
}

function validateHandoff(
  payload: unknown,
  identity: WorkshopModuleIdentity,
): unknown {
  if (
    !isRecord(payload) ||
    !boundedString(payload.moduleId, 128) ||
    !boundedString(payload.moduleVersion, 128)
  ) {
    return invalidPayload("Workshop handoff identity is invalid.");
  }
  if (
    payload.moduleId !== identity.moduleId ||
    payload.moduleVersion !== identity.moduleVersion
  ) {
    throw new RpcPayloadValidationError(
      "rpc-identity-mismatch",
      "Workshop handoff identity does not match the active frame.",
    );
  }
  if (
    !hasOnlyKeys(
      payload,
      [
        "moduleId",
        "moduleVersion",
        "projectId",
        "pngBytes",
        "pixelWidth",
        "pixelHeight",
        "recommendedWidthMm",
        "recommendedHeightMm",
        "preserveCanvasBounds",
        "colorLibraryId",
        "recipeSource",
      ],
      ["layout", "svgBytes", "recommendedTotalThicknessMm"],
    ) ||
    !boundedString(payload.projectId, 256) ||
    !(payload.pngBytes instanceof ArrayBuffer) ||
    ("svgBytes" in payload &&
      !(payload.svgBytes instanceof ArrayBuffer)) ||
    !Number.isInteger(payload.pixelWidth) ||
    !Number.isInteger(payload.pixelHeight) ||
    (payload.pixelWidth as number) <= 0 ||
    (payload.pixelHeight as number) <= 0 ||
    !finiteNumber(payload.recommendedWidthMm) ||
    !finiteNumber(payload.recommendedHeightMm) ||
    payload.recommendedWidthMm <= 0 ||
    payload.recommendedHeightMm <= 0 ||
    ("recommendedTotalThicknessMm" in payload &&
      (!finiteNumber(payload.recommendedTotalThicknessMm) ||
        payload.recommendedTotalThicknessMm <= 0)) ||
    payload.preserveCanvasBounds !== true ||
    !(
      payload.colorLibraryId === null ||
      boundedString(payload.colorLibraryId, 256)
    ) ||
    !isRecord(payload.recipeSource)
  ) {
    return invalidPayload("Workshop image handoff payload is invalid.");
  }
  return {
    moduleId: identity.moduleId,
    moduleVersion: identity.moduleVersion,
    projectId: payload.projectId,
    pngBytes: payload.pngBytes,
    ...(payload.svgBytes instanceof ArrayBuffer
      ? { svgBytes: payload.svgBytes }
      : {}),
    pixelWidth: payload.pixelWidth,
    pixelHeight: payload.pixelHeight,
    recommendedWidthMm: payload.recommendedWidthMm,
    recommendedHeightMm: payload.recommendedHeightMm,
    ...(finiteNumber(payload.recommendedTotalThicknessMm)
      ? {
          recommendedTotalThicknessMm:
            payload.recommendedTotalThicknessMm,
        }
      : {}),
    preserveCanvasBounds: true,
    colorLibraryId: payload.colorLibraryId,
    recipeSource: cloneProjectValue(payload.recipeSource),
    ...("layout" in payload
      ? { layout: cloneProjectValue(payload.layout) }
      : {}),
  };
}

function validateProgress(payload: unknown): unknown {
  if (payload === null) {
    return null;
  }
  if (
    !isRecord(payload) ||
    !hasOnlyKeys(payload, ["phase", "completed", "total"]) ||
    !boundedString(payload.phase, MAX_STATUS_TEXT_LENGTH) ||
    !finiteNumber(payload.completed) ||
    !finiteNumber(payload.total) ||
    payload.completed < 0 ||
    payload.total < 0 ||
    payload.completed > payload.total
  ) {
    return invalidPayload("Workshop progress payload is invalid.");
  }
  return {
    phase: payload.phase,
    completed: payload.completed,
    total: payload.total,
  };
}

function validateVisibleError(payload: unknown): unknown {
  if (payload === null) {
    return null;
  }
  if (
    !isRecord(payload) ||
    !hasOnlyKeys(payload, ["code", "message", "retryable"]) ||
    !boundedString(payload.code, 128) ||
    !boundedString(payload.message, MAX_STATUS_TEXT_LENGTH) ||
    typeof payload.retryable !== "boolean"
  ) {
    return invalidPayload("Workshop error payload is invalid.");
  }
  return {
    code: payload.code,
    message: payload.message,
    retryable: payload.retryable,
  };
}

function validateDiagnostics(payload: unknown): unknown {
  if (!isRecord(payload)) {
    return invalidPayload("Workshop diagnostics payload is invalid.");
  }
  const entries = Object.entries(payload);
  if (
    entries.length > MAX_DIAGNOSTIC_FIELDS ||
    entries.some(
      ([key, value]) =>
        !boundedString(key, 128) ||
        !(
          value === null ||
          typeof value === "string" ||
          typeof value === "number" ||
          typeof value === "boolean"
        ) ||
        (typeof value === "string" &&
          value.length > MAX_STATUS_TEXT_LENGTH) ||
        (typeof value === "number" && !Number.isFinite(value)),
    )
  ) {
    return invalidPayload("Workshop diagnostics payload is invalid.");
  }
  return Object.fromEntries(entries);
}

function validateBackendSubmit(payload: unknown): unknown {
  if (
    !isRecord(payload) ||
    !hasOnlyKeys(payload, ["operation", "params", "inputs"], ["idempotencyKey"]) ||
    typeof payload.operation !== "string" ||
    !BACKEND_OPERATION.test(payload.operation) ||
    !isRecord(payload.params) ||
    !Array.isArray(payload.inputs) ||
    payload.inputs.length > MAX_BACKEND_INPUTS ||
    ("idempotencyKey" in payload &&
      !boundedString(payload.idempotencyKey, 128))
  ) {
    return invalidPayload("Workshop backend task request is invalid.");
  }
  let params: Record<string, unknown>;
  try {
    const encoded = JSON.stringify(payload.params);
    if (utf8Bytes(encoded) > MAX_BACKEND_PARAMS_BYTES) {
      throw new RpcPayloadValidationError(
        "rpc-payload-too-large",
        "Workshop backend task parameters exceed 64 KiB.",
      );
    }
    params = JSON.parse(encoded) as Record<string, unknown>;
  } catch (error) {
    if (error instanceof RpcPayloadValidationError) {
      throw error;
    }
    return invalidPayload("Workshop backend task parameters must be JSON.");
  }
  const names = new Set<string>();
  const inputs = payload.inputs.map((item) => {
    if (
      !isRecord(item) ||
      !hasOnlyKeys(item, ["name", "fileName", "mimeType", "bytes"]) ||
      typeof item.name !== "string" ||
      !BACKEND_FILE_KEY.test(item.name) ||
      names.has(item.name) ||
      typeof item.fileName !== "string" ||
      !BACKEND_FILE_NAME.test(item.fileName) ||
      /[. ]$/.test(item.fileName) ||
      typeof item.mimeType !== "string" ||
      !BACKEND_MIME_TYPE.test(item.mimeType) ||
      !(item.bytes instanceof ArrayBuffer) ||
      item.bytes.byteLength === 0
    ) {
      return invalidPayload("Workshop backend task input is invalid.");
    }
    names.add(item.name);
    return {
      name: item.name,
      fileName: item.fileName,
      mimeType: item.mimeType,
      bytes: item.bytes,
    };
  });
  return {
    operation: payload.operation,
    params,
    inputs,
    ...(typeof payload.idempotencyKey === "string"
      ? { idempotencyKey: payload.idempotencyKey }
      : {}),
  };
}

function validateBackendTaskId(payload: unknown): unknown {
  if (
    !isRecord(payload) ||
    !hasOnlyKeys(payload, ["taskId"]) ||
    typeof payload.taskId !== "string" ||
    !BACKEND_TASK_ID.test(payload.taskId)
  ) {
    return invalidPayload("Workshop backend task ID is invalid.");
  }
  return { taskId: payload.taskId };
}

function validateBackendOutput(payload: unknown): unknown {
  if (
    !isRecord(payload) ||
    !hasOnlyKeys(payload, ["taskId", "name"]) ||
    typeof payload.taskId !== "string" ||
    !BACKEND_TASK_ID.test(payload.taskId) ||
    typeof payload.name !== "string" ||
    !BACKEND_FILE_KEY.test(payload.name)
  ) {
    return invalidPayload("Workshop backend output request is invalid.");
  }
  return { taskId: payload.taskId, name: payload.name };
}

export function validateMethodPayload(
  method: HostWorkshopRpcMethod,
  payload: unknown,
  identity: WorkshopModuleIdentity,
): unknown {
  assertRpcPayloadBounds(payload);
  switch (method) {
    case "backend.status":
    case "backend.list":
      return validateEmptyPayload(payload);
    case "backend.submit":
      return validateBackendSubmit(payload);
    case "backend.get":
    case "backend.cancel":
    case "backend.remove":
      return validateBackendTaskId(payload);
    case "backend.readOutput":
      return validateBackendOutput(payload);
    case "image.pick":
    case "project.latest":
    case "colorLibrary.read":
    case "ui.getState":
    case "lifecycle.ready":
      return validateEmptyPayload(payload);
    case "project.save":
      return validateProjectSave(payload);
    case "project.load":
    case "project.remove":
      return validateProjectIdPayload(payload);
    case "handoff.image":
      return validateHandoff(payload, identity);
    case "status.progress":
      return validateProgress(payload);
    case "status.error":
      return validateVisibleError(payload);
    case "status.diagnostics":
      return validateDiagnostics(payload);
  }
}
