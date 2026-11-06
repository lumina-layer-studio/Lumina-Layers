import type { ProjectAsset, ProjectSnapshot, WorkflowDocument } from "../types";

export interface ProjectCaptureResult {
  document: WorkflowDocument;
  assets: ProjectAsset[];
  nameHint?: string;
}

export interface ProjectRestoreContext {
  projectId: string;
  revisionId: string;
  runtimeEpoch: number;
  /** Optional live-session guard used by asynchronous adapters. */
  isCurrent?: () => boolean;
}

export interface PreparedProjectRestore {
  snapshot: ProjectSnapshot;
  document: WorkflowDocument;
  /** Adapter-owned state captured before commit for transaction rollback. */
  rollbackState?: unknown;
}

export interface ProjectAdapter {
  readonly kind: string;
  unavailable?(document: WorkflowDocument): Promise<boolean>;
  subscribe?(listener: () => void): () => void;
  reset?(): void;
  assertReadyToReplace?(): void;
  capture(options?: { allowGenerating?: boolean }): Promise<ProjectCaptureResult>;
  validate(document: WorkflowDocument): void;
  prepareRestore(
    snapshot: ProjectSnapshot,
    context: ProjectRestoreContext,
  ): Promise<PreparedProjectRestore>;
  commitRestore(
    prepared: PreparedProjectRestore,
    context: ProjectRestoreContext,
  ): void | Promise<void>;
  /** Restore the adapter's pre-commit state after another document fails. */
  rollbackRestore?(
    prepared: PreparedProjectRestore,
    context: ProjectRestoreContext,
  ): Promise<void>;
  /** Release runtime resources prepared for an abandoned open. */
  discardRestore?(prepared: PreparedProjectRestore): Promise<void>;
  /** Release the previous editor's URLs after every document has committed. */
  finalizeRestore?(prepared: PreparedProjectRestore): void;
}

export class ProjectStaleResponseError extends Error {
  constructor(message = "Project response is no longer current") {
    super(message);
    this.name = "ProjectStaleResponseError";
  }
}

export function assertRestoreIsCurrent(
  context: ProjectRestoreContext,
): void {
  if (context.isCurrent && !context.isCurrent()) {
    throw new ProjectStaleResponseError();
  }
}
