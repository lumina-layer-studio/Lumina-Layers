import { create } from "zustand";
import type { ProjectSnapshot } from "../project/types";

export type ProjectSessionStatus =
  | "idle"
  | "opening"
  | "saving"
  | "recovering"
  | "error";

export interface ProjectSessionState {
  activeProjectId: string | null;
  revisionId: string | null;
  savedRevisionId: string | null;
  dirty: boolean;
  recoveryRevisionId: string | null;
  /** Monotonic edit generation used to reject stale async saves. */
  changeSequence: number;
  runtimeEpoch: number;
  status: ProjectSessionStatus;
  lastError: string | null;
  snapshot: ProjectSnapshot | null;
  activate: (
    snapshot: ProjectSnapshot,
    options?: { savedRevisionId?: string | null; dirty?: boolean },
  ) => void;
  markSaved: (revisionId: string) => void;
  markDirty: (revisionId: string) => void;
  commitSavedSnapshot: (
    snapshot: ProjectSnapshot,
    expectedChangeSequence: number,
  ) => boolean;
  /** Commit a Save As result only if the source project stayed active. */
  commitSavedFork: (
    snapshot: ProjectSnapshot,
    expectedChangeSequence: number,
    expectedProjectId: string | null,
  ) => boolean;
  setRecoveryRevision: (revisionId: string | null) => void;
  setStatus: (status: ProjectSessionStatus, error?: string | null) => void;
  beginRuntimeEpoch: () => number;
  reset: () => void;
}

const INITIAL_STATE: Omit<
  ProjectSessionState,
  | "activate"
  | "markSaved"
  | "markDirty"
  | "commitSavedSnapshot"
  | "commitSavedFork"
  | "setRecoveryRevision"
  | "setStatus"
  | "beginRuntimeEpoch"
  | "reset"
> = {
  activeProjectId: null,
  revisionId: null,
  savedRevisionId: null,
  dirty: false,
  recoveryRevisionId: null,
  changeSequence: 0,
  runtimeEpoch: 0,
  status: "idle",
  lastError: null,
  snapshot: null,
};

export const useProjectSessionStore = create<ProjectSessionState>((set, get) => ({
  ...INITIAL_STATE,
  activate: (snapshot, options = {}) => {
    set({
      activeProjectId: snapshot.manifest.projectId,
      revisionId: snapshot.manifest.revisionId,
      savedRevisionId:
        options.savedRevisionId === undefined ? null : options.savedRevisionId,
      dirty:
        options.dirty ??
        options.savedRevisionId !== snapshot.manifest.revisionId,
      status: "idle",
      lastError: null,
      snapshot,
      changeSequence: get().changeSequence + 1,
      runtimeEpoch: get().runtimeEpoch + 1,
    });
  },
  markSaved: (revisionId) => {
    set((state) => ({
      savedRevisionId: revisionId,
      dirty: state.revisionId !== revisionId,
      status: "idle",
      lastError: null,
    }));
  },
  markDirty: (revisionId) => set((state) => ({
    revisionId,
    dirty: true,
    changeSequence: state.changeSequence + 1,
  })),
  commitSavedSnapshot: (snapshot, expectedChangeSequence) => {
    const current = get();
    if (
      current.changeSequence !== expectedChangeSequence ||
      (current.activeProjectId !== null &&
        current.activeProjectId !== snapshot.manifest.projectId)
    ) {
      return false;
    }
    set({
      activeProjectId: snapshot.manifest.projectId,
      revisionId: snapshot.manifest.revisionId,
      savedRevisionId: snapshot.manifest.revisionId,
      dirty: false,
      status: "idle",
      lastError: null,
      snapshot,
    });
    return true;
  },
  commitSavedFork: (snapshot, expectedChangeSequence, expectedProjectId) => {
    const current = get();
    if (
      current.changeSequence !== expectedChangeSequence ||
      current.activeProjectId !== expectedProjectId ||
      (expectedProjectId !== null &&
        snapshot.project.sourceProjectId !== expectedProjectId)
    ) {
      return false;
    }
    set({
      activeProjectId: snapshot.manifest.projectId,
      revisionId: snapshot.manifest.revisionId,
      savedRevisionId: snapshot.manifest.revisionId,
      dirty: false,
      status: "idle",
      lastError: null,
      snapshot,
    });
    return true;
  },
  setRecoveryRevision: (recoveryRevisionId) => set({ recoveryRevisionId }),
  setStatus: (status, lastError = null) => set({ status, lastError }),
  beginRuntimeEpoch: () => {
    const next = get().runtimeEpoch + 1;
    set({ runtimeEpoch: next });
    return next;
  },
  reset: () => set({
    ...INITIAL_STATE,
    changeSequence: get().changeSequence + 1,
    runtimeEpoch: get().runtimeEpoch + 1,
  }),
}));
