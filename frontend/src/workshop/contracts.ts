/**
 * Host-side identities derived from the public Workshop SDK.
 * 宿主侧只在这里扩展公开 Workshop SDK 的身份类型。
 */

import {
  WORKSHOP_PERMISSION_NAMES,
  WORKSHOP_RPC_VERSION,
  type WorkshopPermissionName,
  type WorkshopRpcMethod,
  type WorkshopRpcResponse,
  type WorkshopUiState,
} from "@lumina/workshop-sdk";
import type {
  WorkshopImageHandoff as PublicWorkshopImageHandoff,
} from "@lumina/workshop-sdk";

export {
  WORKSHOP_API_VERSION,
  WORKSHOP_MANIFEST_VERSION,
  WORKSHOP_PERMISSION_NAMES,
  WORKSHOP_RPC_VERSION,
} from "@lumina/workshop-sdk";

export type {
  LocalizedText,
  WorkshopColorEntry,
  WorkshopColorLibrary,
  WorkshopManifestV1,
  WorkshopPermissionName,
  WorkshopPickedImage,
  WorkshopProjectRecord,
  WorkshopRaster,
  WorkshopRecipeSource,
  WorkshopRpcMethod,
  WorkshopRpcRequest,
  WorkshopRpcResponse,
  WorkshopSquareGridLayout,
  WorkshopUiState,
} from "@lumina/workshop-sdk";

/**
 * Backward-compatible host extension for richer image handoff sources.
 * 宿主对图像交接的向后兼容扩展，用于接收更完整的图源与成品厚度。
 */
export interface WorkshopImageHandoff
  extends PublicWorkshopImageHandoff {
  svgBytes?: ArrayBuffer;
  recommendedTotalThicknessMm?: number;
}

export interface WorkshopModuleIdentity {
  readonly moduleId: string;
  readonly moduleVersion: string;
}

export interface WorkshopRpcEnvelopeShape {
  protocol: "lumina-workshop-rpc";
  version: unknown;
  kind: "request";
  requestId: string;
  method: string;
  payload: unknown;
}

/**
 * Optional v1 host events. Modules must advertise each event during the
 * ready handshake before the host sends it.
 */
export const WORKSHOP_RPC_EVENT_NAMES = ["ui.stateChanged"] as const;

export type WorkshopRpcEventName =
  (typeof WORKSHOP_RPC_EVENT_NAMES)[number];

export interface WorkshopRpcEventEnvelope {
  protocol: "lumina-workshop-rpc";
  version: typeof WORKSHOP_RPC_VERSION;
  kind: "event";
  event: WorkshopRpcEventName;
  payload: WorkshopUiState;
}

/**
 * Workshop API implemented by this host. 1.1.0 adds module backends; the
 * pinned SDK package still exports 1.0.0, which frontend-only modules keep
 * negotiating. 宿主实现的 Workshop API 版本；纯前端模块仍协商 1.0.0。
 */
export const HOST_WORKSHOP_API_VERSION = "1.1.0";

/** Ready-handshake feature a module lists to use backend task RPC. */
export const WORKSHOP_BACKEND_FEATURE = "backend.tasks";

/**
 * Host-owned backend task methods (Workshop API 1.1.0, public SDK 1.1.0).
 * Eligibility comes from the version's backend declaration and consent,
 * not from a v1 permission. 资格来自后端声明与授权，而不是 v1 权限。
 */
export const WORKSHOP_BACKEND_RPC_METHODS = [
  "backend.status",
  "backend.submit",
  "backend.get",
  "backend.list",
  "backend.cancel",
  "backend.readOutput",
  "backend.remove",
] as const;

export type WorkshopBackendRpcMethod =
  (typeof WORKSHOP_BACKEND_RPC_METHODS)[number];

export type HostWorkshopRpcMethod =
  | WorkshopRpcMethod
  | WorkshopBackendRpcMethod;

export type WorkshopBackendTaskStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";

/** RPC shape of one host-owned backend task. */
export interface WorkshopBackendTask {
  taskId: string;
  moduleVersion: string;
  operation: string;
  status: WorkshopBackendTaskStatus;
  progress: { completed: number; total: number; phase: string } | null;
  error: { code: string; message: string } | null;
  outputs: Array<{ name: string; fileName: string; mimeType: string; bytes: number }>;
  variant: string | null;
  createdAt: string;
  updatedAt: string;
  finishedAt: string | null;
}

export interface WorkshopBackendInput {
  name: string;
  fileName: string;
  mimeType: string;
  bytes: ArrayBuffer;
}

export interface WorkshopBackendSubmitRequest {
  operation: string;
  params: Record<string, unknown>;
  inputs: WorkshopBackendInput[];
  idempotencyKey?: string;
}

export const WORKSHOP_RPC_METHODS = [
  "image.pick",
  "project.save",
  "project.load",
  "project.latest",
  "project.remove",
  "colorLibrary.read",
  "handoff.image",
  "ui.getState",
  "status.progress",
  "status.error",
  "status.diagnostics",
  "lifecycle.ready",
  ...WORKSHOP_BACKEND_RPC_METHODS,
] as const satisfies readonly HostWorkshopRpcMethod[];

const RPC_METHOD_SET = new Set<string>(WORKSHOP_RPC_METHODS);
const BACKEND_METHOD_SET = new Set<string>(WORKSHOP_BACKEND_RPC_METHODS);
const PERMISSION_SET = new Set<string>(WORKSHOP_PERMISSION_NAMES);

export function isWorkshopRpcMethod(
  value: unknown,
): value is HostWorkshopRpcMethod {
  return typeof value === "string" && RPC_METHOD_SET.has(value);
}

export function isWorkshopBackendRpcMethod(
  value: unknown,
): value is WorkshopBackendRpcMethod {
  return typeof value === "string" && BACKEND_METHOD_SET.has(value);
}

export function isWorkshopPermissionName(
  value: unknown,
): value is WorkshopPermissionName {
  return typeof value === "string" && PERMISSION_SET.has(value);
}

export function responseEnvelope(
  requestId: string,
  result: unknown,
): WorkshopRpcResponse {
  return {
    protocol: "lumina-workshop-rpc",
    version: WORKSHOP_RPC_VERSION,
    kind: "response",
    requestId,
    ok: true,
    result,
  };
}

export function errorResponseEnvelope(
  requestId: string,
  code: string,
  message: string,
  retryable = false,
): WorkshopRpcResponse {
  return {
    protocol: "lumina-workshop-rpc",
    version: WORKSHOP_RPC_VERSION,
    kind: "response",
    requestId,
    ok: false,
    error: {
      code,
      message,
      retryable,
    },
  };
}

export function eventEnvelope(
  event: WorkshopRpcEventName,
  payload: WorkshopUiState,
): WorkshopRpcEventEnvelope {
  return {
    protocol: "lumina-workshop-rpc",
    version: WORKSHOP_RPC_VERSION,
    kind: "event",
    event,
    payload,
  };
}

export function isRpcEnvelopeShape(
  value: unknown,
): value is WorkshopRpcEnvelopeShape {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value)
  ) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    candidate.protocol === "lumina-workshop-rpc" &&
    candidate.kind === "request" &&
    typeof candidate.requestId === "string" &&
    candidate.requestId.length > 0 &&
    candidate.requestId.length <= 128 &&
    typeof candidate.method === "string" &&
    "payload" in candidate
  );
}
