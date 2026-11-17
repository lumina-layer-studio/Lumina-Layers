import type { ProjectSnapshot, WorkflowDocument } from "../types";
import { assertRestoreIsCurrent, type PreparedProjectRestore, type ProjectAdapter, type ProjectRestoreContext } from "./types";
import { createConverterProjectAdapter } from "./converterAdapter";
import { createWorkflowAdapters } from "./workflows";
import { createWorkshopProjectAdapter } from "./workshopAdapter";

export class ProjectAdapterRegistry {
  private readonly adapters = new Map<string, ProjectAdapter>();
  constructor(adapters: ProjectAdapter[] = [createConverterProjectAdapter(), ...createWorkflowAdapters(), createWorkshopProjectAdapter()]) {
    for (const adapter of adapters) this.register(adapter);
  }
  register(adapter: ProjectAdapter) {
    if (!adapter.kind || this.adapters.has(adapter.kind)) throw new Error(`Duplicate project workflow: ${adapter.kind}`);
    this.adapters.set(adapter.kind, adapter);
  }
  get(kind: string) { return this.adapters.get(kind); }
  all() { return [...this.adapters.values()]; }
  require(kind: string) {
    const adapter = this.get(kind);
    if (!adapter) throw new Error(`Unsupported project workflow: ${kind}`);
    return adapter;
  }
  capture(kind: string, options?: { allowGenerating?: boolean }) { return this.require(kind).capture(options); }
  async unavailable(snapshot: ProjectSnapshot): Promise<WorkflowDocument[]> {
    const result: WorkflowDocument[] = [];
    for (const doc of Object.values(snapshot.documents)) {
      const adapter = this.get(doc.kind);
      if (!adapter || await adapter.unavailable?.(doc)) result.push(doc);
    }
    return result;
  }
  async restore(snapshot: ProjectSnapshot, context: ProjectRestoreContext, skippedKinds: readonly string[] = []): Promise<void> {
    for (const adapter of this.adapters.values()) adapter.assertReadyToReplace?.();
    const documents = Object.values(snapshot.documents);
    // Unknown documents can be inspected in the project center, but never
    // execute or clear a live editor. The user explicitly chooses limited open.
    const known = documents.filter((doc) => this.get(doc.kind) && !skippedKinds.includes(doc.kind));
    if (!known.length) throw new Error("This project has no supported editable workspace");
    if (new Set(known.map((doc) => doc.kind)).size !== known.length) throw new Error("Multiple documents of one workspace require a newer project reader");
    const prepared: Array<{ adapter: ProjectAdapter; value: PreparedProjectRestore }> = [];
    const committed: typeof prepared = [];
    try {
      for (const document of known) this.require(document.kind).validate(document);
      for (const document of known) {
        assertRestoreIsCurrent(context);
        const adapter = this.require(document.kind);
        prepared.push({ adapter, value: await adapter.prepareRestore(snapshot, context) });
      }
      assertRestoreIsCurrent(context);
      for (const item of prepared) {
        // Include a partially committed adapter in rollback as well.
        committed.push(item);
        const committedValue = item.adapter.commitRestore(item.value, context);
        if (committedValue) await committedValue;
        assertRestoreIsCurrent(context);
      }
    } catch (error) {
      const cleanupErrors: unknown[] = [];
      for (const item of [...committed].reverse()) {
        if (context.isCurrent && !context.isCurrent()) break;
        try { await item.adapter.rollbackRestore?.(item.value, context); } catch (rollbackError) { cleanupErrors.push(rollbackError); }
      }
      for (const item of prepared) {
        try { await item.adapter.discardRestore?.(item.value); } catch (discardError) { cleanupErrors.push(discardError); }
      }
      if (cleanupErrors.length) throw new AggregateError([error, ...cleanupErrors], "Project open failed during rollback");
      throw error;
    }
    for (const item of prepared) item.adapter.finalizeRestore?.(item.value);
    const restoredKinds = new Set(known.map((document) => document.kind));
    for (const adapter of this.adapters.values()) {
      if (!restoredKinds.has(adapter.kind)) adapter.reset?.();
    }
  }
}

export const projectAdapterRegistry = new ProjectAdapterRegistry();
