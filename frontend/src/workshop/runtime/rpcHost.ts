import {
  WORKSHOP_RPC_VERSION,
  errorResponseEnvelope,
  eventEnvelope,
  isRpcEnvelopeShape,
  isWorkshopRpcMethod,
  responseEnvelope,
  type HostWorkshopRpcMethod,
  type WorkshopModuleIdentity,
  type WorkshopPermissionName,
  type WorkshopRpcEventName,
  type WorkshopRpcResponse,
  type WorkshopUiState,
} from "../contracts";
import {
  hasMethodPermission,
  normalizeWorkshopPermissions,
} from "./capabilities";
import {
  RpcPayloadValidationError,
  validateMethodPayload,
} from "./payloadValidation";
import { WorkshopProjectDisconnectedError, type WorkshopProjectChannel } from "./projectChannel";


export {
  WORKSHOP_RPC_BINARY_PAYLOAD_BYTES,
  WORKSHOP_RPC_CONTROL_PAYLOAD_BYTES,
} from "./payloadValidation";

const REQUEST_TIMEOUT_MS = 30_000;
const IMAGE_PICK_TIMEOUT_MS = 300_000;
const HANDOFF_TIMEOUT_MS = 120_000;
const TOKEN_REFILL_PER_SECOND = 30;
const TOKEN_BURST_CAPACITY = 60;

export interface WorkshopRpcHandlerContext {
  readonly identity: WorkshopModuleIdentity;
  readonly signal: AbortSignal;
}

export type WorkshopRpcHandler = (
  payload: unknown,
  context: WorkshopRpcHandlerContext,
) => unknown | Promise<unknown>;

export type WorkshopRpcHandlers = Partial<
  Record<HostWorkshopRpcMethod, WorkshopRpcHandler>
>;

export interface WorkshopRpcScheduler {
  set(callback: () => void, delayMs: number): unknown;
  clear(handle: unknown): void;
}

export interface WorkshopMessagePort {
  onmessage: ((event: MessageEvent) => void) | null;
  onmessageerror: ((event: MessageEvent) => void) | null;
  addEventListener?(type: "close", listener: () => void): void;
  removeEventListener?(type: "close", listener: () => void): void;
  postMessage(message: unknown, transfer?: Transferable[]): void;
  start(): void;
  close(): void;
}

export interface CreateWorkshopRpcHostOptions {
  identity: WorkshopModuleIdentity;
  permissions: ReadonlySet<string>;
  handlers: WorkshopRpcHandlers;
  supportedEvents?: ReadonlySet<string>;
  /** The exact module version declares a backend (manifest v2). */
  backendEnabled?: boolean;
  projectChannel?: WorkshopProjectChannel;
  onDisconnect?: () => void;
  now?: () => number;
  scheduler?: WorkshopRpcScheduler;
}

export interface WorkshopRpcHost {
  readonly identity: WorkshopModuleIdentity;
  readonly permissions: ReadonlySet<WorkshopPermissionName>;
  dispatch(value: unknown): Promise<WorkshopRpcResponse>;
  emit(event: WorkshopRpcEventName, payload: WorkshopUiState): boolean;
  attach(port: WorkshopMessagePort): () => void;
  disconnect(): void;
  close(): void;
}

interface PendingRequest {
  controller: AbortController;
  timer: unknown;
  finish(response: WorkshopRpcResponse): void;
}

const DEFAULT_SCHEDULER: WorkshopRpcScheduler = {
  set: (callback, delayMs) => globalThis.setTimeout(callback, delayMs),
  clear: (handle) => {
    globalThis.clearTimeout(
      handle as ReturnType<typeof globalThis.setTimeout>,
    );
  },
};

function defaultNow(): number {
  return typeof performance === "undefined"
    ? Date.now()
    : performance.now();
}

function validatedIdentity(
  identity: WorkshopModuleIdentity,
): WorkshopModuleIdentity {
  if (
    typeof identity.moduleId !== "string" ||
    !/^[a-z0-9]+(?:[.-][a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)*$/.test(
      identity.moduleId,
    ) ||
    typeof identity.moduleVersion !== "string" ||
    !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(
      identity.moduleVersion,
    )
  ) {
    throw new TypeError("Workshop module identity is invalid.");
  }
  return Object.freeze({
    moduleId: identity.moduleId,
    moduleVersion: identity.moduleVersion,
  });
}

function fallbackRequestId(value: unknown): string {
  if (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  ) {
    const requestId = (value as Record<string, unknown>).requestId;
    if (
      typeof requestId === "string" &&
      requestId.length > 0 &&
      requestId.length <= 128
    ) {
      return requestId;
    }
  }
  return "invalid-request";
}

function requestHasExactKeys(value: object): boolean {
  const keys = Object.keys(value);
  const required = new Set([
    "protocol",
    "version",
    "kind",
    "requestId",
    "method",
    "payload",
  ]);
  return (
    keys.length === required.size &&
    keys.every((key) => required.has(key))
  );
}

class TokenBucket {
  private tokens = TOKEN_BURST_CAPACITY;
  private lastRefill: number;

  constructor(
    private readonly now: () => number,
  ) {
    this.lastRefill = this.readClock();
  }

  private readClock(): number {
    const value = this.now();
    return Number.isFinite(value) ? value : 0;
  }

  consume(): boolean {
    const current = this.readClock();
    const elapsedMs = Math.max(0, current - this.lastRefill);
    this.lastRefill = Math.max(this.lastRefill, current);
    this.tokens = Math.min(
      TOKEN_BURST_CAPACITY,
      this.tokens +
        (elapsedMs / 1000) * TOKEN_REFILL_PER_SECOND,
    );
    if (this.tokens < 1) {
      return false;
    }
    this.tokens -= 1;
    return true;
  }
}

function requestTimeout(method: HostWorkshopRpcMethod): number {
  switch (method) {
    case "image.pick":
      return IMAGE_PICK_TIMEOUT_MS;
    case "handoff.image":
    case "backend.submit":
    case "backend.readOutput":
      return HANDOFF_TIMEOUT_MS;
    default:
      return REQUEST_TIMEOUT_MS;
  }
}

class WorkshopRpcHostImpl implements WorkshopRpcHost {
  readonly identity: WorkshopModuleIdentity;
  readonly permissions: ReadonlySet<WorkshopPermissionName>;

  private readonly handlers: WorkshopRpcHandlers;
  private readonly supportedEvents: ReadonlySet<string>;
  private readonly backendEnabled: boolean;
  private readonly scheduler: WorkshopRpcScheduler;
  private readonly bucket: TokenBucket;
  private readonly pending = new Map<string, PendingRequest>();
  private activePort: WorkshopMessagePort | null = null;
  private removePortCloseListener: (() => void) | null = null;
  private closed = false;
  private readonly projectChannel?: WorkshopProjectChannel;
  private readonly onDisconnect?: () => void;

  constructor(options: CreateWorkshopRpcHostOptions) {
    this.identity = validatedIdentity(options.identity);
    this.permissions = normalizeWorkshopPermissions(
      options.permissions,
    );
    this.handlers = Object.freeze({ ...options.handlers });
    this.supportedEvents = new Set(options.supportedEvents ?? []);
    this.backendEnabled = options.backendEnabled === true;
    this.projectChannel = options.projectChannel;
    this.onDisconnect = options.onDisconnect;
    this.scheduler = options.scheduler ?? DEFAULT_SCHEDULER;
    this.bucket = new TokenBucket(options.now ?? defaultNow);
  }

  async dispatch(value: unknown): Promise<WorkshopRpcResponse> {
    const requestId = fallbackRequestId(value);
    if (this.closed) {
      return errorResponseEnvelope(
        requestId,
        "rpc-host-closed",
        "The Workshop frame has been closed.",
      );
    }
    if (!isRpcEnvelopeShape(value) || !requestHasExactKeys(value)) {
      return errorResponseEnvelope(
        requestId,
        "rpc-invalid-request",
        "The Workshop RPC request is malformed.",
      );
    }
    if (value.version !== WORKSHOP_RPC_VERSION) {
      return errorResponseEnvelope(
        requestId,
        "rpc-version-unsupported",
        "The Workshop RPC protocol version is unsupported.",
      );
    }
    if (!isWorkshopRpcMethod(value.method)) {
      return errorResponseEnvelope(
        requestId,
        "rpc-unknown-method",
        "The Workshop RPC method is not supported.",
      );
    }
    if (this.pending.has(requestId)) {
      return errorResponseEnvelope(
        requestId,
        "rpc-duplicate-request",
        "The Workshop RPC request ID is already pending.",
      );
    }
    if (!this.bucket.consume()) {
      return errorResponseEnvelope(
        requestId,
        "rpc-rate-limited",
        "The Workshop module is sending requests too quickly.",
        true,
      );
    }
    if (
      !hasMethodPermission(
        this.permissions,
        value.method,
        { backend: this.backendEnabled },
      )
    ) {
      return errorResponseEnvelope(
        requestId,
        "permission-denied",
        "The Workshop module did not declare this permission.",
      );
    }

    let payload: unknown;
    try {
      payload = validateMethodPayload(
        value.method,
        value.payload,
        this.identity,
      );
    } catch (error) {
      if (error instanceof RpcPayloadValidationError) {
        return errorResponseEnvelope(
          requestId,
          error.code,
          error.message,
        );
      }
      return errorResponseEnvelope(
        requestId,
        "rpc-payload-invalid",
        "The Workshop RPC payload is invalid.",
      );
    }

    const handler = this.handlers[value.method];
    if (handler === undefined) {
      return errorResponseEnvelope(
        requestId,
        "rpc-handler-unavailable",
        "The Workshop host method is unavailable.",
        true,
      );
    }
    return this.runHandler(
      requestId,
      value.method,
      payload,
      handler,
    );
  }

  attach(port: WorkshopMessagePort): () => void {
    if (this.activePort !== null) {
      throw new Error("Workshop RPC host already has an active port.");
    }
    if (this.closed) {
      port.close();
      return () => undefined;
    }
    this.activePort = port;
    this.projectChannel?.connect((message) => {
      if (this.activePort !== port) throw new WorkshopProjectDisconnectedError();
      try {
        port.postMessage(message);
      } catch (error) {
        // A serialization failure only affects this project request.
        if (error && typeof error === "object" && "name" in error && error.name === "DataCloneError") {
          throw error;
        }
        this.disconnect(port);
        throw new WorkshopProjectDisconnectedError();
      }
    }, () => this.disconnect(port));
    port.onmessage = (event) => {
      if (this.activePort !== port) return;
      if (this.projectChannel?.receive(event.data)) return;
      void this.dispatch(event.data).then((response) => {
        if (this.activePort !== port || this.closed) {
          return;
        }
        try {
          port.postMessage(response);
        } catch {
          this.disconnect(port);
        }
      });
    };
    port.onmessageerror = () => {
      this.disconnect(port);
    };
    const handleClose = () => this.disconnect(port);
    port.addEventListener?.("close", handleClose);
    this.removePortCloseListener = () => port.removeEventListener?.("close", handleClose);
    port.start();
    return () => {
      if (this.activePort !== port) {
        return;
      }
      this.detachPort();
      this.projectChannel?.close();
    };
  }

  emit(
    event: WorkshopRpcEventName,
    payload: WorkshopUiState,
  ): boolean {
    const port = this.activePort;
    if (
      this.closed ||
      port === null ||
      !this.supportedEvents.has(event)
    ) {
      return false;
    }
    try {
      port.postMessage(eventEnvelope(event, payload));
      return true;
    } catch {
      this.disconnect(port);
      return false;
    }
  }

  disconnect(port = this.activePort): void {
    if (this.closed || port === null || this.activePort !== port) return;
    this.close();
    this.onDisconnect?.();
  }

  private detachPort(): void {
    const port = this.activePort;
    this.activePort = null;
    this.removePortCloseListener?.();
    this.removePortCloseListener = null;
    if (port === null) return;
    port.onmessage = null;
    port.onmessageerror = null;
    port.close();
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.projectChannel?.close();
    this.detachPort();
    for (const [requestId, pending] of [
      ...this.pending.entries(),
    ]) {
      pending.controller.abort();
      pending.finish(
        errorResponseEnvelope(
          requestId,
          "rpc-host-closed",
          "The Workshop frame has been closed.",
        ),
      );
    }
  }

  private runHandler(
    requestId: string,
    method: HostWorkshopRpcMethod,
    payload: unknown,
    handler: WorkshopRpcHandler,
  ): Promise<WorkshopRpcResponse> {
    return new Promise<WorkshopRpcResponse>((resolve) => {
      const controller = new AbortController();
      let settled = false;
      const pending: PendingRequest = {
        controller,
        timer: undefined,
        finish: (response) => {
          if (settled) {
            return;
          }
          settled = true;
          this.scheduler.clear(pending.timer);
          this.pending.delete(requestId);
          resolve(response);
        },
      };
      this.pending.set(requestId, pending);
      pending.timer = this.scheduler.set(() => {
        controller.abort();
        pending.finish(
          errorResponseEnvelope(
            requestId,
            "rpc-timeout",
            "The Workshop host request timed out.",
            true,
          ),
        );
      }, requestTimeout(method));

      void Promise.resolve()
        .then(() =>
          handler(payload, {
            identity: this.identity,
            signal: controller.signal,
          }),
        )
        .then(
          (result) => {
            pending.finish(responseEnvelope(requestId, result));
          },
          () => {
            pending.finish(
              errorResponseEnvelope(
                requestId,
                "rpc-handler-failed",
                "The Workshop host could not complete the request.",
              ),
            );
          },
        );
    });
  }
}

export function createWorkshopRpcHost(
  options: CreateWorkshopRpcHostOptions,
): WorkshopRpcHost {
  return new WorkshopRpcHostImpl(options);
}
