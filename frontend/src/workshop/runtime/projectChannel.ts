import { estimateStoredBytes, WORKSHOP_RECORD_QUOTA_BYTES } from "../projectStorage";
import type { WorkshopModuleIdentity } from "../contracts";

const PROTOCOL = "lumina-workshop-project";
const PROJECT_REQUEST_TIMEOUT_MS = 30_000;
const PROJECT_PROBE_TIMEOUT_MS = 1_500;
type ProjectOperation = "capture" | "prepare" | "commit" | "discard";

export interface CurrentWorkshopProject { schemaVersion: string; state: unknown }

export class WorkshopProjectDisconnectedError extends Error {
  constructor() {
    super("Workshop editor is no longer connected");
    this.name = "WorkshopProjectDisconnectedError";
  }
}

export class WorkshopProjectChannel {
  private connection: { send(message: unknown): void; disconnect(): void } | null = null;
  private pending = new Map<string, {
    resolve(value: unknown): void;
    reject(error: Error): void;
    timer: ReturnType<typeof setTimeout>;
    probe: boolean;
  }>();
  private closeListeners = new Set<() => void>();
  private closed = false;
  private checkingLiveness: Promise<void> | null = null;
  constructor(readonly identity: WorkshopModuleIdentity, readonly schemas: readonly string[], private changed: () => void) {}

  get isClosed(): boolean { return this.closed; }

  onClose(listener: () => void): () => void {
    if (this.closed) {
      listener();
      return () => undefined;
    }
    this.closeListeners.add(listener);
    return () => { this.closeListeners.delete(listener); };
  }

  connect(send: (message: unknown) => void, disconnect: () => void = () => this.close()) {
    if (!this.closed) this.connection = { send, disconnect };
  }
  receive(value: unknown): boolean {
    if (!value || typeof value !== "object" || (value as { protocol?: string }).protocol !== PROTOCOL) return false;
    const message = value as Record<string, unknown>;
    if (this.closed || message.version !== 1) return true;
    if (message.kind === "changed") { this.changed(); return true; }
    const pending = this.pending.get(String(message.requestId));
    if (message.kind !== "response" || !pending) return true;
    if (pending.probe && typeof message.ok !== "boolean") return true;
    clearTimeout(pending.timer);
    this.pending.delete(String(message.requestId));
    if (pending.probe) pending.resolve(true);
    else if (message.ok !== true) pending.reject(new Error(typeof message.error === "string" ? message.error.slice(0, 2000) : "Workshop project operation failed"));
    else {
      try {
        if (estimateStoredBytes(message.result) > WORKSHOP_RECORD_QUOTA_BYTES) throw new Error("Workshop project exceeds the snapshot limit");
        pending.resolve(message.result);
      } catch (error) { pending.reject(error instanceof Error ? error : new Error(String(error))); }
    }
    return true;
  }

  private checkLiveness(): Promise<void> | undefined {
    if (this.checkingLiveness) return this.checkingLiveness;
    // The v1 SDK serves project operations in order. A healthy capture or
    // restore already in flight has its own full response window.
    if (this.pending.size) return;
    // An empty token can never match a prepared restore. Every v1 endpoint
    // replies to discard without calling the editor's capture, prepare or commit.
    this.checkingLiveness = this.sendRequest("discard", { token: "" }, true)
      .then(() => undefined)
      .finally(() => { this.checkingLiveness = null; });
    return this.checkingLiveness;
  }

  async request(operation: ProjectOperation, payload?: unknown): Promise<unknown> {
    if (operation === "capture" || operation === "prepare") {
      const check = this.checkLiveness();
      if (check) await check;
    }
    return this.sendRequest(operation, payload);
  }

  private async sendRequest(operation: ProjectOperation, payload?: unknown, probe = false): Promise<unknown> {
    const connection = this.connection;
    if (this.closed || !connection) throw new WorkshopProjectDisconnectedError();
    if (this.pending.size >= 4) throw new Error("Workshop project operation is already in progress");
    if (payload !== undefined && estimateStoredBytes(payload) > WORKSHOP_RECORD_QUOTA_BYTES) throw new Error("Workshop project exceeds the snapshot limit");
    const requestId = crypto.randomUUID();
    const value = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        connection.disconnect();
      }, probe ? PROJECT_PROBE_TIMEOUT_MS : PROJECT_REQUEST_TIMEOUT_MS);
      this.pending.set(requestId, { resolve, reject, timer, probe });
      try { connection.send({ protocol: PROTOCOL, version: 1, kind: "request", requestId, operation, payload }); }
      catch (error) { clearTimeout(timer); this.pending.delete(requestId); reject(error); }
    });
    if (this.closed) throw new WorkshopProjectDisconnectedError();
    return value;
  }
  async capture(): Promise<CurrentWorkshopProject> {
    const value = await this.request("capture") as CurrentWorkshopProject;
    this.validate(value);
    return value;
  }
  validate(value: CurrentWorkshopProject) {
    if (!value || typeof value !== "object" || !this.schemas.includes(value.schemaVersion) || !("state" in value)) throw new Error("Workshop snapshot schema is not supported by the installed module");
  }
  async prepare(value: CurrentWorkshopProject): Promise<{ token: string }> {
    this.validate(value);
    const result = await this.request("prepare", value) as { token?: string };
    if (!result || typeof result.token !== "string" || !result.token || result.token.length > 128) throw new Error("Workshop editor returned an invalid prepare token");
    return { token: result.token };
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.connection = null;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(new WorkshopProjectDisconnectedError());
    }
    this.pending.clear();
    const listeners = [...this.closeListeners];
    this.closeListeners.clear();
    for (const listener of listeners) listener();
  }
}
