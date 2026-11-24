import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("../api/workshop", () => ({ workshopApi: { listModules: vi.fn() } }));
import { translations } from "../i18n/translations";
import { workshopApi, type WorkshopModules } from "../api/workshop";
import { createWorkshopProjectAdapter } from "../project/adapters/workshopAdapter";
import { ProjectAdapterRegistry } from "../project/adapters/registry";
import { parseProject, serializeProject } from "../project/archive";
import { projectErrorMessage } from "../project/errors";
import { createProjectSnapshot } from "../project/identity";
import { registerWorkshopProject, retainWorkshopProject, useWorkshopProjectRuntime, waitForWorkshopProject, workshopProjectChanged } from "../project/workshopRuntime";
import { WorkshopProjectChannel } from "../workshop/runtime/projectChannel";
import { createWorkshopRpcHost, type WorkshopMessagePort } from "../workshop/runtime/rpcHost";
import { useWorkshopStore } from "../workshop/store";

const identity = { moduleId: "fixture.editor", moduleVersion: "1.0.0" };
const secondIdentity = { moduleId: "fixture.second", moduleVersion: "1.0.0" };
const context = { projectId: "project", revisionId: "revision", runtimeEpoch: 1, isCurrent: () => true };
type EditorState = { cells: number[]; pixels: Uint8ClampedArray; history: unknown[] };

function editorFixture(module = identity, cells = [1, 2]) {
  const requests: string[] = [];
  const delayed = new Set<string>();
  const probe: { count: number; reply: "success" | "error" | "ignore" } = { count: 0, reply: "success" };
  const pixels = new Uint8ClampedArray([1, 2, 3, 255]);
  const live: EditorState = { cells, pixels, history: [{ pixels }] };
  let prepared: { token: string; state: EditorState } | null = null;
  const channel = new WorkshopProjectChannel(module, ["fixture/v1"], workshopProjectChanged);
  const port: WorkshopMessagePort = {
    onmessage: null, onmessageerror: null, start() {}, close() {},
    postMessage(value) {
      const message = value as { operation: string; requestId: string; payload: { state: EditorState; token: string } };
      const isProbe = message.operation === "discard" && message.payload.token === "";
      if (isProbe) {
        probe.count++;
        if (probe.reply === "ignore") return;
      } else {
        requests.push(message.operation);
      }
      if (delayed.has(message.operation)) return;
      let result: unknown = null;
      if (message.operation === "capture") result = { schemaVersion: "fixture/v1", state: live };
      if (message.operation === "prepare") {
        prepared = { token: message.requestId, state: structuredClone(message.payload.state) };
        result = { token: message.requestId };
      }
      if (message.operation === "commit" && prepared?.token === message.payload.token) {
        Object.assign(live, prepared.state);
        prepared = null;
      }
      if (message.operation === "discard" && prepared?.token === message.payload.token) prepared = null;
      const response = { protocol: "lumina-workshop-project", version: 1, kind: "response", requestId: message.requestId,
        ok: !isProbe || probe.reply !== "error", result: structuredClone(result) };
      queueMicrotask(() => port.onmessage?.(new MessageEvent("message", {
        data: response,
      })));
    },
  };
  const host = createWorkshopRpcHost({ identity: module, handlers: {}, permissions: new Set(["project.storage"]), projectChannel: channel });
  host.attach(port);
  const detach = registerWorkshopProject(channel);
  return {
    channel, live, requests, delayed, port, probe,
    disconnect: () => port.onmessageerror?.(new MessageEvent("messageerror")),
    close: () => { detach(); host.close(); },
  };
}

function installedSnapshots(...modules: Array<typeof identity>): WorkshopModules {
  return { modules: modules.map((module) => ({
    module_id: module.moduleId, enabled: true,
    version_details: [{
      version: module.moduleVersion, permissions: [{ name: "project.storage", reason: "Project snapshots" }],
      project_snapshot_protocol: 1, project_snapshot_schemas: ["fixture/v1"],
    }],
  })) } as WorkshopModules;
}

function visibleError(error: unknown, language: "zh" | "en") {
  const storedError = error instanceof Error ? error.message : String(error);
  return projectErrorMessage(storedError, (key) => translations[key]?.[language] ?? key);
}

let editor: ReturnType<typeof editorFixture>;
beforeEach(() => {
  editor = editorFixture();
  useWorkshopStore.getState().openModule(identity.moduleId, identity.moduleVersion);
  vi.mocked(workshopApi.listModules).mockResolvedValue(installedSnapshots(identity));
});
afterEach(() => {
  editor.close();
  vi.useRealTimers();
  useWorkshopProjectRuntime.setState({ retained: null, disconnected: null });
  useWorkshopStore.getState().returnHome();
});

describe("live Workshop projects", () => {
  it("saves unsaved changes, deduplicates binary history and restores editable state", async () => {
    const adapter = createWorkshopProjectAdapter();
    const { live, requests } = editor;
    live.cells.push(9); // No project.storage/latest record is involved.
    const capture = await adapter.capture();
    expect(capture.assets).toHaveLength(2);
    const snapshot = await parseProject(await serializeProject(createProjectSnapshot({ name: "Workshop", workflowKinds: ["workshop"], documents: [capture.document], assets: capture.assets })));
    live.cells = [0];
    await new ProjectAdapterRegistry([adapter]).restore(snapshot, context);
    expect(live.cells).toEqual([1, 2, 9]);
    expect([...live.pixels]).toEqual([1, 2, 3, 255]);
    expect((live.history[0] as { pixels: unknown }).pixels).toBe(live.pixels);
    live.cells.push(10);
    expect((await adapter.capture()).assets[0].sha256).not.toBe(capture.assets[0].sha256);
    expect(requests).toEqual(["capture", "capture", "prepare", "commit", "capture"]);
  });
  it("rolls back a committed module when another workspace fails", async () => {
    const adapter = createWorkshopProjectAdapter();
    const { live } = editor;
    const capture = await adapter.capture();
    const document = { ...capture.document, kind: "failure", documentId: "failure.main" };
    const snapshot = createProjectSnapshot({ name: "Transaction", workflowKinds: ["workshop", "failure"], documents: [capture.document, document], assets: capture.assets });
    live.cells = [77];
    const failure = { ...adapter, kind: "failure", validate() {}, async prepareRestore() { return { snapshot, document }; }, commitRestore() { throw new Error("commit failed"); }, rollbackRestore: undefined, discardRestore: undefined };
    await expect(new ProjectAdapterRegistry([adapter, failure]).restore(snapshot, context)).rejects.toThrow("commit failed");
    expect(live.cells).toEqual([77]);
  });
  it("checks installed version/schema without launching a missing module", async () => {
    const adapter = createWorkshopProjectAdapter();
    const { document } = await adapter.capture();
    vi.mocked(workshopApi.listModules).mockResolvedValue({ modules: [] });
    expect(await adapter.unavailable!(document)).toBe(true);
    expect(useWorkshopStore.getState().activeModule?.moduleId).toBe(identity.moduleId);
    expect(editor.requests).toEqual(["capture"]);
  });
  it("tracks edit events and rejects requests after a frame disconnects", async () => {
    const listener = vi.fn();
    const stop = createWorkshopProjectAdapter().subscribe!(listener);
    editor.channel.receive({ protocol: "lumina-workshop-project", version: 1, kind: "changed" });
    expect(listener).toHaveBeenCalledTimes(1);
    stop(); editor.close();
    expect(useWorkshopProjectRuntime.getState().current).toBeNull();
    await expect(editor.channel.capture()).rejects.toThrow("no longer connected");
  });

  it("unregisters the channel when the host receives a MessagePort error", async () => {
    const waiting = waitForWorkshopProject(identity.moduleId, identity.moduleVersion);
    editor.disconnect();
    expect(useWorkshopProjectRuntime.getState().current).toBeNull();
    await expect(waiting).rejects.toThrow("no longer connected");

    const waitingForReplacement = waitForWorkshopProject(identity.moduleId, identity.moduleVersion);
    const replacement = editorFixture();
    try {
      await expect(waitingForReplacement).resolves.toBe(replacement.channel);
      editor.close();
      expect(useWorkshopProjectRuntime.getState().current).toBe(replacement.channel);
    } finally {
      replacement.close();
    }
  });

  it("asks the user to reload a supported editor before saving its stale retained data", async () => {
    await retainWorkshopProject();
    editor.live.cells.push(9);
    editor.disconnect();

    const error = await createWorkshopProjectAdapter().capture().catch((cause: unknown) => cause);
    expect(visibleError(error, "zh")).toMatch(/重新加载.*保存/);
    expect(visibleError(error, "en")).toMatch(/reload.*sav/i);
    expect(editor.requests).toEqual(["capture"]);
  });

  it("does not save retained data after leaving a disconnected editor", async () => {
    await retainWorkshopProject();
    editor.live.cells.push(9);
    editor.disconnect();
    useWorkshopStore.getState().returnHome();

    const error = await createWorkshopProjectAdapter().capture().catch((cause: unknown) => cause);
    expect(visibleError(error, "en")).toMatch(/reload.*sav/i);
  });

  it("keeps the final live capture after deliberately returning to the Workshop manager", async () => {
    const adapter = createWorkshopProjectAdapter();
    editor.live.cells.push(9);
    const expected = await adapter.capture();
    await retainWorkshopProject();
    useWorkshopStore.getState().returnHome();
    editor.close();

    const retained = await adapter.capture();
    expect(retained.document).toEqual(expected.document);
    expect(retained.assets.map((asset) => asset.sha256)).toEqual(expected.assets.map((asset) => asset.sha256));
  });

  it("keeps unsupported snapshots distinct from a disconnected editor", async () => {
    editor.close();
    const modules = installedSnapshots(identity);
    const versions = modules.modules[0].version_details;
    versions.push({ ...versions[0], version: "2.0.0" });
    versions[0].project_snapshot_protocol = null;
    vi.mocked(workshopApi.listModules).mockResolvedValue(modules);

    const error = await createWorkshopProjectAdapter().capture().catch((cause: unknown) => cause);
    expect(visibleError(error, "zh")).toMatch(/不支持.*快照/);
    expect(visibleError(error, "en")).toMatch(/does not support.*snapshots/i);
  });

  it("aborts a save when the live port fails during capture", async () => {
    editor.delayed.add("capture");
    const error = createWorkshopProjectAdapter().capture().catch((cause: unknown) => cause);
    await vi.waitFor(() => expect(editor.requests).toContain("capture"));
    editor.disconnect();

    expect(visibleError(await error, "zh")).toMatch(/重新加载.*保存/);
  });

  it("unregisters the editor when the port cannot send a capture request", async () => {
    const send = editor.port.postMessage;
    vi.spyOn(editor.port, "postMessage").mockImplementation((value) => {
      if ((value as { operation: string }).operation === "capture") {
        throw new DOMException("The port is unavailable", "InvalidStateError");
      }
      send(value);
    });

    const error = await createWorkshopProjectAdapter().capture().catch((cause: unknown) => cause);
    expect(useWorkshopProjectRuntime.getState().current).toBeNull();
    expect(visibleError(error, "zh")).toMatch(/重新加载.*保存/);
    expect(visibleError(error, "en")).toMatch(/reload.*sav/i);
  });

  it("keeps the editor connected when a prepare request cannot be cloned", async () => {
    const detachedBuffer = new ArrayBuffer(4);
    structuredClone(detachedBuffer, { transfer: [detachedBuffer] });
    const send = editor.port.postMessage;
    vi.spyOn(editor.port, "postMessage").mockImplementation((message) => {
      if ((message as { operation: string }).operation === "prepare") structuredClone(message);
      send(message);
    });

    await expect(editor.channel.prepare({ schemaVersion: "fixture/v1", state: { detachedBuffer } }))
      .rejects.toMatchObject({ name: "DataCloneError" });
    expect(useWorkshopProjectRuntime.getState().current).toBe(editor.channel);
    await expect(editor.channel.capture()).resolves.toMatchObject({ schemaVersion: "fixture/v1" });
  });

  it.each(["success", "error"] as const)("recognizes a %s probe response then catches an idle peer loss in 1.5 s", async (reply) => {
    const adapter = createWorkshopProjectAdapter();
    editor.probe.reply = reply;
    await adapter.capture();
    editor.probe.reply = "ignore";
    vi.useFakeTimers();
    const error = adapter.capture().catch((cause: unknown) => cause);

    await vi.advanceTimersByTimeAsync(1499);
    expect(editor.requests).toEqual(["capture"]);
    expect(useWorkshopProjectRuntime.getState().current).toBe(editor.channel);
    await vi.advanceTimersByTimeAsync(1);

    expect(visibleError(await error, "en")).toMatch(/reload.*sav/i);
    expect(useWorkshopProjectRuntime.getState().current).toBeNull();
  });

  it("catches an idle peer loss before the first save in 1.5 s", async () => {
    const adapter = createWorkshopProjectAdapter();
    editor.probe.reply = "ignore";
    vi.useFakeTimers();
    const error = adapter.capture().catch((cause: unknown) => cause);

    await vi.advanceTimersByTimeAsync(1499);
    expect(editor.requests).toEqual([]);
    expect(useWorkshopProjectRuntime.getState().current).toBe(editor.channel);
    await vi.advanceTimersByTimeAsync(1);

    expect(visibleError(await error, "en")).toMatch(/reload.*sav/i);
    expect(useWorkshopProjectRuntime.getState().current).toBeNull();
    expect(editor.probe.count).toBe(1);
  });

  it("does not discard a real prepared token during an idle probe", async () => {
    const token = await editor.channel.prepare({ schemaVersion: "fixture/v1", state: { ...editor.live, cells: [9] } });
    await editor.channel.capture();
    await editor.channel.request("commit", token);

    expect(editor.probe.count).toBe(2);
    expect(editor.live.cells).toEqual([9]);
  });

  it("gives a heavy capture 30 s and closes the host when it expires", async () => {
    vi.useFakeTimers();
    const send = editor.port.postMessage;
    const slowPort = vi.spyOn(editor.port, "postMessage").mockImplementation((message) => {
      if ((message as { operation: string }).operation === "capture") setTimeout(() => send(message), 20_000);
      else send(message);
    });
    const heavy = editor.channel.capture();
    await vi.advanceTimersByTimeAsync(1000);
    const queued = editor.channel.capture();
    await vi.advanceTimersByTimeAsync(20_000);
    await expect(heavy).resolves.toMatchObject({ schemaVersion: "fixture/v1" });
    await expect(queued).resolves.toMatchObject({ schemaVersion: "fixture/v1" });
    expect(editor.probe.count).toBe(1);
    slowPort.mockRestore();
    editor.delayed.add("capture");

    const stalled = editor.channel.capture().catch((cause: unknown) => cause);
    await vi.advanceTimersByTimeAsync(29_999);
    expect(useWorkshopProjectRuntime.getState().current).toBe(editor.channel);
    await vi.advanceTimersByTimeAsync(1);

    expect(await stalled).toMatchObject({ message: "Workshop editor is no longer connected" });
    expect(useWorkshopProjectRuntime.getState().current).toBeNull();
  });

  it("keeps the current editor selected when opening a project loses its rollback capture", async () => {
    const adapter = createWorkshopProjectAdapter();
    const capture = await adapter.capture();
    const snapshot = createProjectSnapshot({ name: "Workshop", workflowKinds: ["workshop"], documents: [capture.document], assets: capture.assets });
    editor.delayed.add("capture");
    const error = adapter.prepareRestore(snapshot, context).catch((cause: unknown) => cause);
    await vi.waitFor(() => expect(editor.requests).toEqual(["capture", "capture"]));
    editor.disconnect();

    expect(visibleError(await error, "zh")).toMatch(/重新加载.*打开/);
    expect(visibleError(await error, "en")).toMatch(/reload.*open/i);
    expect(useWorkshopStore.getState().activeModule?.moduleId).toBe(identity.moduleId);
  });

  it("restores the previous Workshop editor when the target port fails during prepare", async () => {
    const adapter = createWorkshopProjectAdapter();
    const capture = await adapter.capture();
    editor.live.cells.push(9);
    const targetDocument = {
      ...capture.document,
      payload: { ...capture.document.payload, module: { moduleId: secondIdentity.moduleId, version: secondIdentity.moduleVersion } },
    };
    const snapshot = createProjectSnapshot({ name: "Target", workflowKinds: ["workshop"], documents: [targetDocument], assets: capture.assets });
    let selected = editor;
    vi.mocked(workshopApi.listModules).mockResolvedValue(installedSnapshots(identity, secondIdentity));
    const switchModule = useWorkshopStore.subscribe((state, previous) => {
      if (state.activeModule === previous.activeModule || !state.activeModule) return;
      selected.close();
      if (state.activeModule.moduleId === secondIdentity.moduleId) {
        selected = editorFixture(secondIdentity, [5]);
        selected.delayed.add("prepare");
      } else {
        selected = editorFixture(identity, [0]);
      }
    });
    try {
      const error = adapter.prepareRestore(snapshot, context).catch((cause: unknown) => cause);
      await vi.waitFor(() => expect(selected.requests).toContain("prepare"));
      selected.disconnect();

      expect(visibleError(await error, "en")).toMatch(/reload.*open/i);
      expect(useWorkshopStore.getState().activeModule?.moduleId).toBe(identity.moduleId);
      expect(selected.live.cells).toEqual([1, 2, 9]);
    } finally {
      switchModule();
      selected.close();
    }
  });

  it("reports a disconnect before commit even when Workshop was ready during prepare", async () => {
    const adapter = createWorkshopProjectAdapter();
    const capture = await adapter.capture();
    const document = { ...capture.document, kind: "disconnect", documentId: "disconnect.main" };
    const snapshot = createProjectSnapshot({ name: "Workshop", workflowKinds: ["workshop", "disconnect"], documents: [capture.document, document], assets: capture.assets });
    const disconnectBeforeCommit = {
      ...adapter,
      kind: "disconnect",
      validate() {},
      async prepareRestore() { editor.disconnect(); return { snapshot, document }; },
      commitRestore: vi.fn(),
      rollbackRestore: undefined,
      discardRestore: undefined,
    };
    const opening = new ProjectAdapterRegistry([adapter, disconnectBeforeCommit]).restore(snapshot, context);

    const error = await opening.catch((cause: unknown) => cause);
    expect(visibleError(error, "en")).toMatch(/reload.*open/i);
    expect(editor.requests).toEqual(["capture", "capture", "prepare"]);
    expect(disconnectBeforeCommit.commitRestore).not.toHaveBeenCalled();
  });
});
