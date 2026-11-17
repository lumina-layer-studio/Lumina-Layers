import { beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("../api/workshop", () => ({ workshopApi: { listModules: vi.fn() } }));
import { workshopApi } from "../api/workshop";
import { createWorkshopProjectAdapter } from "../project/adapters/workshopAdapter";
import { ProjectAdapterRegistry } from "../project/adapters/registry";
import { parseProject, serializeProject } from "../project/archive";
import { createProjectSnapshot } from "../project/identity";
import { registerWorkshopProject, useWorkshopProjectRuntime, workshopProjectChanged } from "../project/workshopRuntime";
import { WorkshopProjectChannel } from "../workshop/runtime/projectChannel";
import type { WorkshopMessagePort } from "../workshop/runtime/rpcHost";
import { useWorkshopStore } from "../workshop/store";

const identity = { moduleId: "fixture.editor", moduleVersion: "1.0.0" };
const context = { projectId: "project", revisionId: "revision", runtimeEpoch: 1, isCurrent: () => true };
let live: { cells: number[]; pixels: Uint8ClampedArray; history: unknown[] };
let channel: WorkshopProjectChannel;
let close: () => void;
let requests: string[];
beforeEach(() => {
  close?.();
  requests = [];
  const pixels = new Uint8ClampedArray([1, 2, 3, 255]);
  live = { cells: [1, 2], pixels, history: [{ pixels }] };
  let prepared: typeof live | null = null;
  channel = new WorkshopProjectChannel(identity, ["fixture/v1"], workshopProjectChanged);
  const port: WorkshopMessagePort = {
    onmessage: null, onmessageerror: null, start() {}, close() {},
    postMessage(value) {
      const message = value as { operation: string; requestId: string; payload: { state: typeof live; token: string } };
      requests.push(message.operation);
      let result: unknown = null;
      if (message.operation === "capture") result = { schemaVersion: "fixture/v1", state: live };
      if (message.operation === "prepare") { prepared = structuredClone(message.payload.state); result = { token: message.requestId }; }
      if (message.operation === "commit") { live = prepared!; prepared = null; }
      if (message.operation === "discard") prepared = null;
      queueMicrotask(() => channel.receive({ protocol: "lumina-workshop-project", version: 1, kind: "response", requestId: message.requestId, ok: true, result }));
    },
  };
  channel.connect(port);
  close = registerWorkshopProject(channel);
  useWorkshopStore.getState().openModule(identity.moduleId, identity.moduleVersion);
  vi.mocked(workshopApi.listModules).mockResolvedValue({ modules: [{ module_id: identity.moduleId, enabled: true, version_details: [{ version: identity.moduleVersion, project_snapshot_protocol: 1, project_snapshot_schemas: ["fixture/v1"] }] }] } as never);
});

describe("live Workshop projects", () => {
  it("saves unsaved changes, deduplicates binary history and restores editable state", async () => {
    const adapter = createWorkshopProjectAdapter();
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
    expect(requests).toEqual(["capture"]);
  });
  it("tracks edit events and rejects requests after a frame disconnects", async () => {
    const listener = vi.fn();
    const stop = createWorkshopProjectAdapter().subscribe!(listener);
    channel.receive({ protocol: "lumina-workshop-project", version: 1, kind: "changed" });
    expect(listener).toHaveBeenCalledTimes(1);
    stop(); close();
    expect(useWorkshopProjectRuntime.getState().current).toBeNull();
    await expect(channel.capture()).rejects.toThrow("no longer connected");
  });
});
