import { afterEach, describe, expect, it, vi } from "vitest";

import {
  WORKSHOP_RPC_BINARY_PAYLOAD_BYTES,
  WORKSHOP_RPC_CONTROL_PAYLOAD_BYTES,
  createWorkshopRpcHost,
  type WorkshopMessagePort,
  type WorkshopRpcHandler,
} from "../workshop/runtime/rpcHost";
import { METHOD_PERMISSION } from "../workshop/runtime/capabilities";


function request(
  method: string,
  payload: unknown,
  requestId = `request-${method}`,
): Record<string, unknown> {
  return {
    protocol: "lumina-workshop-rpc",
    version: 1,
    kind: "request",
    requestId,
    method,
    payload,
  };
}

function hostOptions(
  handlers: Record<string, WorkshopRpcHandler>,
  permissions: string[] = [],
) {
  return {
    identity: {
      moduleId: "fixture.hello",
      moduleVersion: "1.0.0",
    },
    permissions: new Set(permissions),
    handlers,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("createWorkshopRpcHost", () => {
  it("emits UI state events only to sessions that advertised support", () => {
    const uiState = {
      locale: "en-US" as const,
      theme: "light" as const,
      tokens: { "--lumina-surface": "#ffffff" },
    };
    const legacyPort: WorkshopMessagePort = {
      onmessage: null,
      onmessageerror: null,
      postMessage: vi.fn(),
      start: vi.fn(),
      close: vi.fn(),
    };
    const capablePort: WorkshopMessagePort = {
      onmessage: null,
      onmessageerror: null,
      postMessage: vi.fn(),
      start: vi.fn(),
      close: vi.fn(),
    };
    const legacyHost = createWorkshopRpcHost(hostOptions({}));
    const capableHost = createWorkshopRpcHost({
      ...hostOptions({}),
      supportedEvents: new Set(["ui.stateChanged"]),
    });
    legacyHost.attach(legacyPort);
    capableHost.attach(capablePort);

    expect(legacyHost.emit("ui.stateChanged", uiState)).toBe(false);
    expect(legacyPort.postMessage).not.toHaveBeenCalled();
    expect(capableHost.emit("ui.stateChanged", uiState)).toBe(true);
    expect(capablePort.postMessage).toHaveBeenCalledWith({
      protocol: "lumina-workshop-rpc",
      version: 1,
      kind: "event",
      event: "ui.stateChanged",
      payload: uiState,
    });

    capableHost.close();
    expect(capableHost.emit("ui.stateChanged", uiState)).toBe(false);
    expect(capablePort.postMessage).toHaveBeenCalledTimes(1);
  });

  it("keeps every v1 method on the explicit capability table", () => {
    expect(METHOD_PERMISSION).toEqual({
      "image.pick": "image.pick",
      "project.save": "project.storage",
      "project.load": "project.storage",
      "project.latest": "project.storage",
      "project.remove": "project.storage",
      "colorLibrary.read": "color-library.read",
      "handoff.image": "handoff.image",
      "material.import": "material.import",
      "ui.getState": null,
      "status.progress": null,
      "status.error": null,
      "status.diagnostics": null,
      "lifecycle.ready": null,
    });
  });

  it("denies an undeclared method before calling the handler", async () => {
    const handler = vi.fn();
    const host = createWorkshopRpcHost(
      hostOptions({ "image.pick": handler }),
    );

    const response = await host.dispatch(
      request("image.pick", {}),
    );

    expect(response).toMatchObject({
      ok: false,
      error: { code: "permission-denied" },
    });
    expect(handler).not.toHaveBeenCalled();
  });

  it("allows baseline UI and status methods without manifest permissions", async () => {
    const getState = vi.fn().mockResolvedValue({
      locale: "zh-CN",
      theme: "dark",
      tokens: {},
    });
    const progress = vi.fn().mockResolvedValue(undefined);
    const host = createWorkshopRpcHost(
      hostOptions({
        "ui.getState": getState,
        "status.progress": progress,
      }),
    );

    const state = await host.dispatch(
      request("ui.getState", {}, "state"),
    );
    const status = await host.dispatch(
      request(
        "status.progress",
        { phase: "render", completed: 1, total: 2 },
        "progress",
      ),
    );

    expect(state.ok).toBe(true);
    expect(status.ok).toBe(true);
    expect(getState).toHaveBeenCalledTimes(1);
    expect(progress).toHaveBeenCalledTimes(1);
  });

  it("rejects a control payload above 1 MiB", async () => {
    const handler = vi.fn();
    const host = createWorkshopRpcHost(
      hostOptions(
        { "project.save": handler },
        ["project.storage"],
      ),
    );

    const response = await host.dispatch(
      request("project.save", {
        value: "x".repeat(
          WORKSHOP_RPC_CONTROL_PAYLOAD_BYTES + 1,
        ),
      }),
    );

    expect(response).toMatchObject({
      ok: false,
      error: { code: "rpc-payload-too-large" },
    });
    expect(handler).not.toHaveBeenCalled();
  });

  it("rejects aggregate binary payload above 64 MiB", async () => {
    const handler = vi.fn();
    const host = createWorkshopRpcHost(
      hostOptions(
        { "handoff.image": handler },
        ["handoff.image"],
      ),
    );

    const response = await host.dispatch(
      request("handoff.image", {
        moduleId: "fixture.hello",
        moduleVersion: "1.0.0",
        pngBytes: new ArrayBuffer(
          WORKSHOP_RPC_BINARY_PAYLOAD_BYTES + 1,
        ),
      }),
    );

    expect(response).toMatchObject({
      ok: false,
      error: { code: "rpc-binary-too-large" },
    });
    expect(handler).not.toHaveBeenCalled();
  });

  it("uses a 30 per second sustained and 60 burst token bucket", async () => {
    const handler = vi.fn().mockResolvedValue(undefined);
    const host = createWorkshopRpcHost({
      ...hostOptions({ "ui.getState": handler }),
      now: () => 0,
    });

    const results = await Promise.all(
      Array.from({ length: 61 }, (_, index) =>
        host.dispatch(
          request("ui.getState", {}, `request-${index}`),
        ),
      ),
    );

    expect(results.at(-1)).toMatchObject({
      ok: false,
      error: { code: "rpc-rate-limited" },
    });
    expect(handler).toHaveBeenCalledTimes(60);
  });

  it("refills rate-limit tokens at 30 requests per second", async () => {
    let now = 0;
    const handler = vi.fn().mockResolvedValue(undefined);
    const host = createWorkshopRpcHost({
      ...hostOptions({ "ui.getState": handler }),
      now: () => now,
    });
    await Promise.all(
      Array.from({ length: 60 }, (_, index) =>
        host.dispatch(
          request("ui.getState", {}, `burst-${index}`),
        ),
      ),
    );
    now = 100;

    const refilled = await Promise.all(
      Array.from({ length: 4 }, (_, index) =>
        host.dispatch(
          request("ui.getState", {}, `refill-${index}`),
        ),
      ),
    );

    expect(refilled.slice(0, 3).every((item) => item.ok)).toBe(true);
    expect(refilled[3]).toMatchObject({
      ok: false,
      error: { code: "rpc-rate-limited" },
    });
  });

  it("rejects duplicate request IDs while the first request is pending", async () => {
    let finish: (() => void) | undefined;
    const handler = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const host = createWorkshopRpcHost(
      hostOptions({ "ui.getState": handler }),
    );

    const first = host.dispatch(
      request("ui.getState", {}, "duplicate"),
    );
    const duplicate = await host.dispatch(
      request("ui.getState", {}, "duplicate"),
    );
    finish?.();

    expect(duplicate).toMatchObject({
      ok: false,
      error: { code: "rpc-duplicate-request" },
    });
    expect((await first).ok).toBe(true);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("releases request IDs after a completed call", async () => {
    const handler = vi.fn().mockResolvedValue(undefined);
    const host = createWorkshopRpcHost(hostOptions({ "ui.getState": handler }));

    const first = await host.dispatch(request("ui.getState", {}, "reused"));
    const second = await host.dispatch(request("ui.getState", {}, "reused"));

    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    expect(handler).toHaveBeenCalledTimes(2);
    host.close();
  });

  it("keeps a long-lived frame usable beyond 10,000 completed calls", async () => {
    let now = 0;
    const handler = vi.fn().mockResolvedValue(undefined);
    const host = createWorkshopRpcHost({
      ...hostOptions({ "ui.getState": handler }),
      now: () => now,
    });

    for (let index = 0; index < 10_001; index += 1) {
      now += 1000;
      const response = await host.dispatch(request("ui.getState", {}, `long-lived-${index}`));
      expect(response.ok).toBe(true);
    }
    expect(handler).toHaveBeenCalledTimes(10_001);
    host.close();
  });

  it("rejects unknown methods and wrong protocol versions", async () => {
    const host = createWorkshopRpcHost(hostOptions({}));

    const unknown = await host.dispatch(
      request("network.fetch", {}, "unknown"),
    );
    const wrongVersion = await host.dispatch({
      ...request("ui.getState", {}, "version"),
      version: 2,
    });

    expect(unknown).toMatchObject({
      ok: false,
      error: { code: "rpc-unknown-method" },
    });
    expect(wrongVersion).toMatchObject({
      ok: false,
      error: { code: "rpc-version-unsupported" },
    });
  });

  it("rejects identity mismatch before handoff reaches the handler", async () => {
    const handler = vi.fn();
    const host = createWorkshopRpcHost(
      hostOptions(
        { "handoff.image": handler },
        ["handoff.image"],
      ),
    );

    const response = await host.dispatch(
      request("handoff.image", {
        moduleId: "other.module",
        moduleVersion: "1.0.0",
        pngBytes: new ArrayBuffer(8),
        pixelWidth: 1,
        pixelHeight: 1,
        recommendedWidthMm: 1,
        recommendedHeightMm: 1,
        preserveCanvasBounds: true,
        colorLibraryId: null,
        recipeSource: {},
      }),
    );

    expect(response).toMatchObject({
      ok: false,
      error: { code: "rpc-identity-mismatch" },
    });
    expect(handler).not.toHaveBeenCalled();
  });

  it("accepts the complete SDK image handoff emitted by an installed module", async () => {
    const handler = vi.fn().mockResolvedValue({ status: "completed" });
    const host = createWorkshopRpcHost(
      hostOptions(
        { "handoff.image": handler },
        ["handoff.image"],
      ),
    );
    const payload = {
      moduleId: "fixture.hello",
      moduleVersion: "1.0.0",
      projectId: "bead-project-acceptance",
      pngBytes: new ArrayBuffer(8),
      pixelWidth: 184,
      pixelHeight: 136,
      recommendedWidthMm: 59.8,
      recommendedHeightMm: 44.2,
      preserveCanvasBounds: true as const,
      layout: {
        kind: "square-grid",
        rows: 17,
        columns: 23,
        pitchMm: 2.6,
      },
      colorLibraryId: "lut:acceptance",
      recipeSource: {
        manifestSchemaVersion: 1,
        moduleId: "fixture.hello",
        moduleVersion: "1.0.0",
        projectSchemaVersion: "bead-project/v1",
        renderSchemaVersion: "bead-render/v1",
        payload: {
          payloadVersion: "bead-recipe/v1",
          rows: 17,
          columns: 23,
          compression: 80,
          palette: [[51, 126, 224]],
        },
      },
    };

    const response = await host.dispatch(
      request("handoff.image", payload, "complete-handoff"),
    );

    expect(response).toMatchObject({
      ok: true,
      result: { status: "completed" },
    });
    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({
        projectId: "bead-project-acceptance",
        layout: expect.objectContaining({ rows: 17, columns: 23 }),
        recipeSource: expect.objectContaining({
          projectSchemaVersion: "bead-project/v1",
        }),
      }),
      expect.any(Object),
    );
  });

  it("passes optional native SVG and total thickness through the v1 handoff", async () => {
    const handler = vi.fn().mockResolvedValue({ status: "completed" });
    const host = createWorkshopRpcHost(
      hostOptions(
        { "handoff.image": handler },
        ["handoff.image"],
      ),
    );
    const svgBytes = Uint8Array.from(
      new TextEncoder().encode(
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L1 0L1 1Z"/></svg>',
      ),
    ).buffer;

    const response = await host.dispatch(
      request("handoff.image", {
        moduleId: "fixture.hello",
        moduleVersion: "1.0.0",
        projectId: "project-svg",
        pngBytes: new ArrayBuffer(23),
        svgBytes,
        pixelWidth: 1,
        pixelHeight: 1,
        recommendedWidthMm: 2.6,
        recommendedHeightMm: 2.6,
        recommendedTotalThicknessMm: 1.85,
        preserveCanvasBounds: true,
        colorLibraryId: null,
        recipeSource: {},
      }),
    );

    expect(response).toMatchObject({ ok: true });
    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({
        svgBytes,
        recommendedTotalThicknessMm: 1.85,
      }),
      expect.anything(),
    );
  });

  it.each([
    { svgBytes: "not-bytes", recommendedTotalThicknessMm: 1.85 },
    { svgBytes: new ArrayBuffer(8), recommendedTotalThicknessMm: 0 },
    { svgBytes: new ArrayBuffer(8), recommendedTotalThicknessMm: NaN },
  ])("rejects invalid optional native handoff fields", async (optional) => {
    const handler = vi.fn();
    const host = createWorkshopRpcHost(
      hostOptions(
        { "handoff.image": handler },
        ["handoff.image"],
      ),
    );

    const response = await host.dispatch(
      request("handoff.image", {
        moduleId: "fixture.hello",
        moduleVersion: "1.0.0",
        projectId: "project-svg-invalid",
        pngBytes: new ArrayBuffer(24),
        pixelWidth: 1,
        pixelHeight: 1,
        recommendedWidthMm: 2.6,
        recommendedHeightMm: 2.6,
        preserveCanvasBounds: true,
        colorLibraryId: null,
        recipeSource: {},
        ...optional,
      }),
    );

    expect(response).toMatchObject({
      ok: false,
      error: { code: "rpc-payload-invalid" },
    });
    expect(handler).not.toHaveBeenCalled();
  });

  it("validates and reconstructs project payloads before calling handlers", async () => {
    const handler = vi.fn().mockResolvedValue(undefined);
    const host = createWorkshopRpcHost(
      hostOptions(
        { "project.save": handler },
        ["project.storage"],
      ),
    );

    const invalid = await host.dispatch(
      request(
        "project.save",
        {
          record: {
            projectId: "",
            schemaVersion: "fixture/v1",
            createdAt: "2026-07-30T00:00:00.000Z",
            updatedAt: "2026-07-30T00:00:00.000Z",
            project: {},
          },
        },
        "invalid-project",
      ),
    );
    const valid = await host.dispatch(
      request(
        "project.save",
        {
          record: {
            projectId: "p1",
            schemaVersion: "fixture/v1",
            createdAt: "2026-07-30T00:00:00.000Z",
            updatedAt: "2026-07-30T00:00:00.000Z",
            project: { value: 1 },
          },
        },
        "valid-project",
      ),
    );

    expect(invalid).toMatchObject({
      ok: false,
      error: { code: "rpc-payload-invalid" },
    });
    expect(valid.ok).toBe(true);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith(
      {
        record: {
          projectId: "p1",
          schemaVersion: "fixture/v1",
          createdAt: "2026-07-30T00:00:00.000Z",
          updatedAt: "2026-07-30T00:00:00.000Z",
          project: { value: 1 },
        },
      },
      expect.objectContaining({
        identity: {
          moduleId: "fixture.hello",
          moduleVersion: "1.0.0",
        },
      }),
    );
  });

  it("times ordinary handlers out after 30 seconds", async () => {
    vi.useFakeTimers();
    const handler = vi.fn(() => new Promise(() => undefined));
    const host = createWorkshopRpcHost(
      hostOptions({ "ui.getState": handler }),
    );

    const pending = host.dispatch(
      request("ui.getState", {}, "timeout"),
    );
    await vi.advanceTimersByTimeAsync(30_001);

    await expect(pending).resolves.toMatchObject({
      ok: false,
      error: { code: "rpc-timeout", retryable: true },
    });
  });

  it("keeps the native image picker alive for up to five minutes", async () => {
    vi.useFakeTimers();
    const handler = vi.fn(() => new Promise(() => undefined));
    const host = createWorkshopRpcHost(
      hostOptions(
        { "image.pick": handler },
        ["image.pick"],
      ),
    );
    const pending = host.dispatch(
      request("image.pick", {}, "slow-native-picker"),
    );
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(30_001);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(270_000);

    await expect(pending).resolves.toMatchObject({
      ok: false,
      error: { code: "rpc-timeout", retryable: true },
    });
  });

  it("allows handoff up to its 120 second timeout", async () => {
    vi.useFakeTimers();
    const handler = vi.fn(() => new Promise(() => undefined));
    const host = createWorkshopRpcHost(
      hostOptions(
        { "handoff.image": handler },
        ["handoff.image"],
      ),
    );
    const pending = host.dispatch(
      request("handoff.image", {
        moduleId: "fixture.hello",
        moduleVersion: "1.0.0",
        projectId: "timeout-project",
        pngBytes: new ArrayBuffer(8),
        pixelWidth: 1,
        pixelHeight: 1,
        recommendedWidthMm: 1,
        recommendedHeightMm: 1,
        preserveCanvasBounds: true,
        colorLibraryId: null,
        recipeSource: {},
      }),
    );
    let settled = false;
    void pending.then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(30_001);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(90_000);

    await expect(pending).resolves.toMatchObject({
      ok: false,
      error: { code: "rpc-timeout" },
    });
  });

  it("cancels pending handlers when the frame host closes", async () => {
    let handlerSignal: AbortSignal | undefined;
    const handler = vi.fn(
      (_payload: unknown, context: { signal: AbortSignal }) => {
        handlerSignal = context.signal;
        return new Promise(() => undefined);
      },
    );
    const host = createWorkshopRpcHost(
      hostOptions({ "ui.getState": handler }),
    );
    const pending = host.dispatch(
      request("ui.getState", {}, "close"),
    );
    await vi.waitFor(() => expect(handlerSignal).toBeDefined());

    host.close();

    await expect(pending).resolves.toMatchObject({
      ok: false,
      error: { code: "rpc-host-closed" },
    });
    expect(handlerSignal?.aborted).toBe(true);
  });

  it("attaches one MessagePort and returns protocol responses", async () => {
    const posted: unknown[] = [];
    const port: WorkshopMessagePort = {
      onmessage: null,
      onmessageerror: null,
      postMessage: vi.fn((value: unknown) => {
        posted.push(value);
      }),
      start: vi.fn(),
      close: vi.fn(),
    };
    const host = createWorkshopRpcHost(
      hostOptions({
        "lifecycle.ready": vi.fn().mockResolvedValue(undefined),
      }),
    );

    host.attach(port);
    port.onmessage?.({
      data: request("lifecycle.ready", {}, "ready"),
    } as MessageEvent);
    await vi.waitFor(() => expect(posted).toHaveLength(1));

    expect(posted[0]).toMatchObject({
      requestId: "ready",
      ok: true,
    });
    expect(port.start).toHaveBeenCalledTimes(1);

    host.close();
    expect(port.close).toHaveBeenCalledTimes(1);
  });

  it("never returns handler stack traces to a module", async () => {
    const handler = vi.fn(() => {
      throw new Error("private host failure");
    });
    const host = createWorkshopRpcHost(
      hostOptions({ "ui.getState": handler }),
    );

    const response = await host.dispatch(
      request("ui.getState", {}, "failure"),
    );

    expect(response).toMatchObject({
      ok: false,
      error: {
        code: "rpc-handler-failed",
        message: "The Workshop host could not complete the request.",
      },
    });
    expect(JSON.stringify(response)).not.toContain("rpcHost");
  });
});
