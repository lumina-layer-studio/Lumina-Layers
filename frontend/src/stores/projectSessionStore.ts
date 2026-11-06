import { create } from "zustand";
import type { ProjectSnapshot } from "../project/types";

export type ProjectSessionStatus =
  | "idle"
  | "opening"
  | "saving"
  | "recovering"
  | "error";

export interface ProjectSavePoint {
  runtimeEpoch: number;
  documentVersions: Record<string, string>;
}

function sameVersions(left: Record<string, string>, right: Record<string, string>) {
  return Object.keys(left).length === Object.keys(right).length
    && Object.keys(left).every(key => left[key] === right[key]);
}

function savedState(current: ProjectSessionState, snapshot: ProjectSnapshot, sequence: number, point?: ProjectSavePoint) {
  if (point ? current.runtimeEpoch !== point.runtimeEpoch : current.changeSequence !== sequence) return null;
  const savedDocumentVersions = { ...(point?.documentVersions ?? current.documentVersions) };
  const dirty = !sameVersions(current.documentVersions, savedDocumentVersions);
  return {
    activeProjectId: snapshot.manifest.projectId,
    revisionId: dirty ? current.revisionId : snapshot.manifest.revisionId,
    savedRevisionId: snapshot.manifest.revisionId,
    dirty, snapshot, savedDocumentVersions,
    lastError: null,
  };
}

export interface ProjectSessionState {
  activeProjectId: string | null;
  revisionId: string | null;
  savedRevisionId: string | null;
  dirty: boolean;
  recoveryRevisionId: string | null;
  /** Monotonic edit generation used to reject stale async saves. */
  changeSequence: number;
  documentVersions: Record<string, string>;
  savedDocumentVersions: Record<string, string> | null;
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
  markDocumentChanged: (kind: string, version: string, revisionId: string) => void;
  setDocumentBaseline: (versions: Record<string, string>) => void;
  commitSavedSnapshot: (
    snapshot: ProjectSnapshot,
    expectedChangeSequence: number,
    point?: ProjectSavePoint,
  ) => boolean;
  /** Commit a Save As result only if the source project stayed active. */
  commitSavedFork: (
    snapshot: ProjectSnapshot,
    expectedChangeSequence: number,
    expectedProjectId: string | null,
    point?: ProjectSavePoint,
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
  | "markDocumentChanged"
  | "setDocumentBaseline"
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
  documentVersions: {},
  savedDocumentVersions: {},
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
      lastError: null,
      snapshot,
      changeSequence: get().changeSequence + 1,
      runtimeEpoch: get().runtimeEpoch + 1,
      documentVersions: {},
      savedDocumentVersions: null,
    });
  },
  markSaved: (revisionId) => {
    set((state) => ({
      savedRevisionId: revisionId,
      dirty: state.revisionId !== revisionId,
      status: "idle",
      lastError: null,
      ...(state.revisionId === revisionId ? { savedDocumentVersions: { ...state.documentVersions } } : {}),
    }));
  },
  markDirty: (revisionId) => set((state) => ({
    revisionId,
    dirty: true,
    changeSequence: state.changeSequence + 1,
    documentVersions: { ...state.documentVersions, other: revisionId },
  })),
  setDocumentBaseline: (documentVersions) => set(state => ({
    documentVersions,
    savedDocumentVersions: state.dirty ? null : { ...documentVersions },
  })),
  markDocumentChanged: (kind, version, revisionId) => set(state => {
    const documentVersions = { ...state.documentVersions, [kind]: version };
    const saved = state.savedDocumentVersions;
    const dirty = !saved || !sameVersions(documentVersions, saved);
    return { documentVersions, dirty, revisionId, changeSequence: state.changeSequence + 1 };
  }),
  commitSavedSnapshot: (snapshot, expectedChangeSequence, point) => {
    const current = get();
    if (current.activeProjectId !== null && current.activeProjectId !== snapshot.manifest.projectId) return false;
    const saved = savedState(current, snapshot, expectedChangeSequence, point);
    if (!saved) return false;
    set(saved);
    return true;
  },
  commitSavedFork: (snapshot, expectedChangeSequence, expectedProjectId, point) => {
    const current = get();
    if (
      current.activeProjectId !== expectedProjectId ||
      (expectedProjectId !== null &&
        snapshot.project.sourceProjectId !== expectedProjectId)
    ) {
      return false;
    }
    const saved = savedState(current, snapshot, expectedChangeSequence, point);
    if (!saved) return false;
    set(saved);
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
