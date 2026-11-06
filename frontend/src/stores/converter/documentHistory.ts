import { createStore, type StoreApi } from "zustand/vanilla";
import { tRuntime } from "../../i18n/runtime";
import { captureConverterDocument, equalDocumentValue, sameConverterDocument } from "./document";
import { captureEditorRuntime, captureSourceRuntime, editorMutationPending, type EditorRuntime, type SourceRuntimeSnapshot } from "./editorRuntime";
import { currentDocumentGesture } from "./documentGestures";
import type { DocumentCommandOptions } from "./documentCommands";
import { resolveSourceFile } from "../../utils/sourceFileOrigins";
import type { ConverterActions, ConverterDocumentState, ConverterState } from "./types";

type Store = ConverterState & ConverterActions;
type EditorHandle = { value: EditorRuntime; confirmed: ConverterState["confirmedEditorCommit"] };
type Node = { id: string; document: ConverterDocumentState; sources: SourceRuntimeSnapshot; editor: EditorHandle };
type Entry = { kind: "document" | "editor"; before: Node; after: Node; group: symbol };
export interface DocumentHistoryState {
  position: string;
  canUndo: boolean;
  canRedo: boolean;
  busy: boolean;
  retainedSessionIds: string[];
}

const LOCAL_EDITOR_KEYS = ["colorRemapMap", "replacement_regions", "recipe_overrides", "free_color_set"] as const;
function localEditorChanged(a: ConverterState, b: ConverterState) {
  return LOCAL_EDITOR_KEYS.some(key => !equalDocumentValue(a[key], b[key]));
}

/** Coordinates document commands with the existing authoritative backend history. */
export function installConverterDocumentHistory(store: StoreApi<Store>, restore: (document: ConverterDocumentState, editor: EditorRuntime, sources: SourceRuntimeSnapshot) => void) {
  const handles = new Map<string, EditorHandle>();
  let serial = 0;
  let past: Entry[] = [], future: Entry[] = [];
  let suspended = false;
  let syncGroup: symbol | null = null;
  const asyncGroups = new Map<symbol, number>();
  let navigation: { entry: Entry; direction: "undo" | "redo" } | null = null;
  const runtime = (state: ConverterState): EditorHandle => {
    const value = captureEditorRuntime(state);
    if (!state.sessionId) return { value, confirmed: null };
    let handle = handles.get(state.sessionId);
    if (!handle) {
      handle = { value, confirmed: {
        sessionId: state.sessionId,
        selectionRevision: state.selectionDocument?.selection_revision ?? 0,
        contentRevision: state.selectionDocument?.editor_content_revision ?? state.selectionDocument?.content_revision ?? 0,
      } };
      handles.set(state.sessionId, handle);
    }
    return handle;
  };
  const node = (state: ConverterState): Node => ({ id: `converter:${++serial}`, document: captureConverterDocument(state), sources: captureSourceRuntime(state), editor: runtime(state) });
  let current = node(store.getState());
  let checkpoint: string | null = null;
  const history = createStore<DocumentHistoryState>(() => ({ position: current.id, canUndo: false, canRedo: false, busy: false, retainedSessionIds: [] }));

  const nodes = () => [current, ...past.flatMap(entry => [entry.before, entry.after]), ...future.flatMap(entry => [entry.before, entry.after])];
  const retained = () => new Set(nodes()
    .flatMap(item => [item.editor.value.sessionId, item.sources.heightmapUploadSessionId, ...item.sources.projectResourceSessionIds])
    .filter((id): id is string => Boolean(id)));
  const overBudget = () => {
    const snapshots = nodes();
    const sessions = new Set(snapshots.map(item => item.editor.value.sessionId).filter(Boolean));
    const files = new Set(snapshots.flatMap(({ document: doc, editor }) => [doc.imageFile, resolveSourceFile(doc.imageFile), doc.heightmapFile, doc.modelSurfaceFile, doc.projectLutFile, doc.projectMaterialArchiveFile, editor.value.pendingEditorProject, ...doc.batchFiles]));
    return sessions.size > 4 || [...files].reduce((size, file) => size + (file?.size ?? 0), 0) > 256 * 1024 * 1024;
  };
  const available = (entry: Entry | undefined, direction: "undo" | "redo") => Boolean(entry && (entry.kind === "document"
    || (entry.before.editor.value.sessionId === store.getState().sessionId && (direction === "undo" ? store.getState().historyCanUndo : store.getState().historyCanRedo))));
  const publish = () => {
    // A bounded journal owns at most four backend editor sessions, including redo.
    while (past.length > 80 || (past.length && overBudget())) past.shift();
    while (future.length && overBudget()) future.shift();
    const ids = [...retained()];
    for (const id of handles.keys()) if (!ids.includes(id)) handles.delete(id);
    const previous = history.getState();
    const next = { position: current.id, canUndo: available(past.at(-1), "undo"), canRedo: available(future.at(-1), "redo"),
      busy: Boolean(navigation) || asyncGroups.size > 0,
      retainedSessionIds: equalDocumentValue(previous.retainedSessionIds, ids) ? previous.retainedSessionIds : ids };
    if (Object.keys(next).some(key => next[key as keyof DocumentHistoryState] !== previous[key as keyof DocumentHistoryState])) history.setState(next);
  };
  const record = (kind: Entry["kind"], state: ConverterState, group: symbol) => {
    const next = node(state);
    const last = past.at(-1);
    if (kind === "document" && last?.kind === "document" && last.group === group && last.after.id !== checkpoint && !future.length) {
      last.after = next;
      const sameEditor = last.before.editor === next.editor || (!last.before.editor.value.sessionId && !next.editor.value.sessionId
        && LOCAL_EDITOR_KEYS.every(key => equalDocumentValue(last.before.editor.value[key], next.editor.value[key]))
        && last.before.editor.value.pendingEditorProject === next.editor.value.pendingEditorProject);
      if (sameConverterDocument(last.before.document, next.document) && sameEditor) {
        past.pop(); current = last.before;
      } else current = next;
    } else {
      past.push({ kind, before: current, after: next, group });
      current = next;
    }
    future = [];
    publish();
  };
  const finishNavigation = () => {
    if (!navigation) return;
    const { entry, direction } = navigation;
    if (direction === "undo") { past.pop(); future.push(entry); current = entry.before; }
    else { future.pop(); past.push(entry); current = entry.after; }
    navigation = null;
    current.document = captureConverterDocument(store.getState());
    current.sources = captureSourceRuntime(store.getState());
    current.editor = runtime(store.getState());
    publish();
  };

  store.subscribe((next, previous) => {
    if (suspended) return;
    if (navigation && previous.contentCommitStatus === "unknown" && next.contentCommitStatus === "failed") navigation = null;
    const handle = runtime(next);
    // The server revisions always move forward, including undo. Never restore an old revision.
    handle.value = captureEditorRuntime(next);
    const commit = next.confirmedEditorCommit;
    const acknowledged = commit?.sessionId === next.sessionId && commit && (
      commit.selectionRevision > (handle.confirmed?.selectionRevision ?? 0)
      || commit.contentRevision > (handle.confirmed?.contentRevision ?? 0));
    const settled = !next.historyBusy && !next.replacePreviewLoading
      && next.contentCommitStatus !== "pending" && next.contentCommitStatus !== "unknown";
    if (acknowledged && settled && !next.isLoading) {
      handle.confirmed = commit;
      if (navigation) finishNavigation();
      else record("editor", next, Symbol("editor commit"));
    } else {
      const group = syncGroup ?? [...asyncGroups.keys()].at(-1);
      if (group && (!sameConverterDocument(previous, next) || (!next.sessionId && localEditorChanged(previous, next)))) record("document", next, group);
      else {
        // Source decoding/catalog normalization completes the same user command,
        // but still advances save ownership if it changes persisted inputs.
        if (!sameConverterDocument(previous, next)) current.id = `converter:${++serial}`;
        current.document = captureConverterDocument(next);
        current.sources = captureSourceRuntime(next);
        current.editor = handle;
      }
    }
    if (next.isLoading && acknowledged) handle.confirmed = commit;
    publish();
  });

  const raw = store.getState();
  function run<Result>(action: () => Result, blocked: () => Result, options: DocumentCommandOptions): Result {
    const state = store.getState();
    const unconfirmed = state.historyBusy || state.pendingSelectionMutations.length > 0
      || state.contentCommitStatus === "pending" || state.contentCommitStatus === "unknown";
    if (!syncGroup && !options.localEditor && (navigation || unconfirmed)) {
      store.getState().setError(tRuntime("recipe_export_wait_edits"));
      return blocked();
    }
    const parent = syncGroup;
    const group = parent ?? currentDocumentGesture()
      ?? (options.joinAsync ? [...asyncGroups.keys()].at(-1) : null) ?? Symbol("document command");
    syncGroup = group;
    try {
      const result = action();
      if (result instanceof Promise) {
        asyncGroups.set(group, (asyncGroups.get(group) ?? 0) + 1);
        publish();
        const finish = () => {
          const remaining = (asyncGroups.get(group) ?? 1) - 1;
          if (remaining) asyncGroups.set(group, remaining); else asyncGroups.delete(group);
          publish();
        };
        void result.then(finish, finish);
      }
      return result;
    } finally { syncGroup = parent; }
  }

  const navigate = async (direction: "undo" | "redo") => {
    const state = store.getState();
    if (navigation || asyncGroups.size || editorMutationPending(state) || state.isGenerating || state.batchLoading || state.isCropping) return;
    const entry = (direction === "undo" ? past : future).at(-1);
    if (!entry || !available(entry, direction)) return;
    if (entry.kind === "document") {
      const target = direction === "undo" ? entry.before : entry.after;
      suspended = true;
      try { restore(target.document, target.editor.value, target.sources); }
      finally { suspended = false; }
      navigation = { entry, direction };
      finishNavigation();
    } else {
      navigation = { entry, direction }; publish();
      try { await (direction === "undo" ? raw.undoColorRemap() : raw.redoColorRemap()); }
      finally {
        // An unknown commit remains reserved until the existing receipt reconciler settles it.
        if (navigation && store.getState().contentCommitStatus !== "unknown") { navigation = null; publish(); }
      }
    }
  };
  return {
    store: history,
    run,
    undo: () => navigate("undo"),
    redo: () => navigate("redo"),
    checkpoint() { checkpoint = current.id; },
    amendCurrent(action: () => void) {
      const previous = suspended;
      suspended = true;
      try { action(); }
      finally {
        suspended = previous;
        current = node(store.getState());
        if (past.length) past[past.length - 1].after = current;
        if (future.length) future[future.length - 1].before = current;
        publish();
      }
    },
    replaceRuntime(action: () => void) {
      const previous = suspended;
      suspended = true;
      try { action(); } finally { suspended = previous; }
    },
    reset() {
      past = []; future = []; navigation = null; checkpoint = null; asyncGroups.clear();
      current = node(store.getState()); publish();
    },
  };
}
