import { estimateStoredBytes, WORKSHOP_RECORD_QUOTA_BYTES } from "../projectStorage";
import type { WorkshopModuleIdentity } from "../contracts";

const PROTOCOL = "lumina-workshop-project";
export interface CurrentWorkshopProject { schemaVersion: string; state: unknown }

export class WorkshopProjectDisconnectedError extends Error {
  constructor() {
    super("Workshop editor is no longer connected");
    this.name = "WorkshopProjectDisconnectedError";
  }
}

export class WorkshopProjectChannel {
  private sendMessage: ((message: unknown) => void) | null = null;
  private pending = new Map<string, { resolve(value: unknown): void; reject(error: Error): void; timer: ReturnType<typeof setTimeout> }>();
  private closeListeners = new Set<() => void>();
  private closed = false;
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

  connect(sendMessage: (message: unknown) => void) {
    if (!this.closed) this.sendMessage = sendMessage;
  }
  receive(value: unknown): boolean {
    if (!value || typeof value !== "object" || (value as { protocol?: string }).protocol !== PROTOCOL) return false;
    const message = value as Record<string, unknown>;
    if (this.closed || message.version !== 1) return true;
    if (message.kind === "changed") { this.changed(); return true; }
    const pending = this.pending.get(String(message.requestId));
    if (message.kind !== "response" || !pending) return true;
    clearTimeout(pending.timer);
    this.pending.delete(String(message.requestId));
    if (message.ok !== true) pending.reject(new Error(typeof message.error === "string" ? message.error.slice(0, 2000) : "Workshop project operation failed"));
    else {
      try {
        if (estimateStoredBytes(message.result) > WORKSHOP_RECORD_QUOTA_BYTES) throw new Error("Workshop project exceeds the snapshot limit");
        pending.resolve(message.result);
      } catch (error) { pending.reject(error instanceof Error ? error : new Error(String(error))); }
    }
    return true;
  }
  async request(operation: "capture" | "prepare" | "commit" | "discard", payload?: unknown): Promise<unknown> {
    const sendMessage = this.sendMessage;
    if (this.closed || !sendMessage) throw new WorkshopProjectDisconnectedError();
    if (this.pending.size >= 4) throw new Error("Workshop project operation is already in progress");
    if (payload !== undefined && estimateStoredBytes(payload) > WORKSHOP_RECORD_QUOTA_BYTES) throw new Error("Workshop project exceeds the snapshot limit");
    const requestId = crypto.randomUUID();
    const value = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(requestId); reject(new Error("Workshop editor did not respond to the project request")); }, 30_000);
      this.pending.set(requestId, { resolve, reject, timer });
      try { sendMessage({ protocol: PROTOCOL, version: 1, kind: "request", requestId, operation, payload }); }
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
    this.sendMessage = null;
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
