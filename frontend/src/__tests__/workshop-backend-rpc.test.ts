import { describe, expect, it, vi } from "vitest";

import type {
  WorkshopBackendApi,
  WorkshopBackendTaskResponse,
} from "../api/workshop";
import { createWorkshopBackendHandlers } from "../workshop/runtime/handlers";
import {
  isAcceptedHandshakeApiVersion,
  negotiateReady,
} from "../workshop/runtime/health";
import { createWorkshopRpcHost } from "../workshop/runtime/rpcHost";

const TASK_ID = "0123456789abcdef0123456789abcdef";

function task(
  overrides: Partial<WorkshopBackendTaskResponse> = {},
): WorkshopBackendTaskResponse {
  return {
    task_id: TASK_ID,
    module_id: "fixture.backend",
    module_version: "1.0.0",
    kind: "operation",
    operation: "alpha-invert",
    status: "queued",
    progress: null,
    error: null,
    inputs: [],
    outputs: [],
    variant: null,
    created_at: "2026-11-04T00:00:00+00:00",
    updated_at: "2026-11-04T00:00:00+00:00",
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

function fakeBackend(overrides: Partial<WorkshopBackendApi> = {}): WorkshopBackendApi {
  return {
    status: vi.fn(),
    authorize: vi.fn(),
    prepare: vi.fn(),
    setAcceleration: vi.fn(),
    stop: vi.fn(),
    presence: vi.fn(),
    submit: vi.fn().mockResolvedValue(task()),
    task: vi.fn().mockResolvedValue(task()),
    tasks: vi.fn().mockResolvedValue([task()]),
    cancel: vi.fn().mockResolvedValue(task({ status: "cancelled" })),
    remove: vi.fn(),
    output: vi.fn(),
    storage: vi.fn(),
    deleteRetainedModel: vi.fn(),
    deleteTaskData: vi.fn(),
    ...overrides,
  };
}

function request(method: string, payload: unknown, requestId = "req-1") {
  return {
    protocol: "lumina-workshop-rpc",
    version: 1,
    kind: "request",
    requestId,
    method,
    payload,
  };
}

const identity = { moduleId: "fixture.backend", moduleVersion: "1.0.0" };
const submitPayload = {
  operation: "alpha-invert",
  params: { strength: 1 },
  inputs: [
    {
      name: "image",
      fileName: "source.png",
      mimeType: "image/png",
      bytes: new Uint8Array([1, 2, 3]).buffer,
    },
  ],
};

describe("Workshop backend RPC", () => {
  it("allows backend methods only for versions that declare a backend", async () => {
    const backend = fakeBackend();
    const frontendOnly = createWorkshopRpcHost({
      identity,
      permissions: new Set(),
      handlers: createWorkshopBackendHandlers(backend),
    });
    const denied = await frontendOnly.dispatch(request("backend.submit", submitPayload));
    expect(denied.ok).toBe(false);
    expect(denied.error?.code).toBe("permission-denied");
    expect(backend.submit).not.toHaveBeenCalled();

    const declared = createWorkshopRpcHost({
      identity,
      permissions: new Set(),
      handlers: createWorkshopBackendHandlers(backend),
      backendEnabled: true,
    });
    const accepted = await declared.dispatch(request("backend.submit", submitPayload));
    expect(accepted.ok).toBe(true);
    expect(backend.submit).toHaveBeenCalledWith(
      "fixture.backend",
      "1.0.0",
      expect.objectContaining({ operation: "alpha-invert", params: { strength: 1 } }),
    );
    expect(accepted.result).toMatchObject({ taskId: TASK_ID, status: "queued" });
  });

  it("rejects malformed backend payloads before reaching the host API", async () => {
    const backend = fakeBackend();
    const host = createWorkshopRpcHost({
      identity,
      permissions: new Set(),
      handlers: createWorkshopBackendHandlers(backend),
      backendEnabled: true,
    });
    const invalid = [
      request("backend.get", { taskId: "../escape" }, "a"),
      request("backend.submit", { ...submitPayload, operation: "Bad Name" }, "b"),
      request(
        "backend.submit",
        { ...submitPayload, inputs: Array.from({ length: 9 }, (_, index) => ({ ...submitPayload.inputs[0], name: `in-${index}` })) },
        "c",
      ),
      request("backend.submit", { ...submitPayload, params: { bad: () => 1 } }, "d"),
      request("backend.readOutput", { taskId: TASK_ID, name: "../x" }, "e"),
    ];
    for (const item of invalid) {
      const response = await host.dispatch(item);
      expect(response.ok).toBe(false);
    }
    expect(backend.submit).not.toHaveBeenCalled();
    expect(backend.task).not.toHaveBeenCalled();
  });

  it("closing the frame ends only the wait and never cancels the host task", async () => {
    let finishSubmit: (value: WorkshopBackendTaskResponse) => void = () => undefined;
    const backend = fakeBackend({
      submit: vi.fn(
        () =>
          new Promise<WorkshopBackendTaskResponse>((resolve) => {
            finishSubmit = resolve;
          }),
      ),
    });
    const host = createWorkshopRpcHost({
      identity,
      permissions: new Set(),
      handlers: createWorkshopBackendHandlers(backend),
      backendEnabled: true,
    });
    const pending = host.dispatch(request("backend.submit", submitPayload));
    await Promise.resolve();
    host.close();
    const response = await pending;
    expect(response.error?.code).toBe("rpc-host-closed");
    finishSubmit(task({ status: "running" }));
    await Promise.resolve();
    expect(backend.cancel).not.toHaveBeenCalled();
  });

  it("hides host preparation tasks from modules", async () => {
    const backend = fakeBackend({
      tasks: vi.fn().mockResolvedValue([task(), task({ task_id: "f".repeat(32), kind: "prepare", operation: "prepare" })]),
      task: vi.fn().mockResolvedValue(task({ kind: "prepare", operation: "prepare" })),
    });
    const handlers = createWorkshopBackendHandlers(backend);
    const context = { identity, signal: new AbortController().signal };
    const listed = (await handlers["backend.list"]?.({}, context)) as Array<{ taskId: string }>;
    expect(listed.map((item) => item.taskId)).toEqual([TASK_ID]);
    await expect(handlers["backend.get"]?.({ taskId: TASK_ID }, context)).rejects.toThrow();
  });
});

describe("Workshop ready handshake negotiation", () => {
  it("accepts frontend-only 1.0.0 and backend 1.1.0 modules on this host", () => {
    expect(isAcceptedHandshakeApiVersion("1.0.0")).toBe(true);
    expect(isAcceptedHandshakeApiVersion("1.1.0")).toBe(true);
    expect(isAcceptedHandshakeApiVersion("1.2.0")).toBe(false);
    expect(isAcceptedHandshakeApiVersion("2.0.0")).toBe(false);
    expect(isAcceptedHandshakeApiVersion(1)).toBe(false);
  });

  it("reports the backend feature only when the module asks for it", () => {
    const base = {
      type: "lumina.workshop.ready",
      moduleId: "fixture.backend",
      moduleVersion: "1.0.0",
      apiVersion: "1.1.0",
      events: ["ui.stateChanged", "unknown.event"],
    };
    const withBackend = negotiateReady(
      { ...base, features: ["backend.tasks"] },
      "fixture.backend",
      "1.0.0",
    );
    expect(withBackend?.backendRequested).toBe(true);
    expect([...(withBackend?.events ?? [])]).toEqual(["ui.stateChanged"]);
    expect(negotiateReady(base, "fixture.backend", "1.0.0")?.backendRequested).toBe(false);
    expect(negotiateReady({ ...base, apiVersion: "2.0.0" }, "fixture.backend", "1.0.0")).toBeNull();
    expect(negotiateReady(base, "fixture.other", "1.0.0")).toBeNull();
  });
});
