import { create } from "zustand";
import { useConverterStore, converterDocumentHistory } from "../stores/converter";
import { useProjectSessionStore, type ProjectSavePoint } from "../stores/projectSessionStore";
import { useWidgetStore } from "../stores/widgetStore";
import { useSettingsStore } from "../stores/settingsStore";
import { captureProjectSettings } from "../stores/converter/project";
import { externalSpoolMaterial } from "../stores/converter/nativeMaterialSelection";
import { useWorkflowRuntime } from "./workflowRuntime";
import type { TabId } from "../types/widget";
import { projectAdapterRegistry } from "./adapters/registry";
import { parseProject } from "./archive";
import { exportProjectBundle, listProjectFiles, nativeProjects, prepareProjectSave, rememberProject, saveProjectFile, type OpenedProjectFile, type ProjectFileEntry } from "./files";
import { createProjectRevision, createProjectSnapshot, forkProjectSnapshot, newProjectIdentity } from "./identity";
import { createOpenRequestCoordinator } from "./openRequestCoordinator";
import { listRecoverySnapshots, removeRecoverySnapshot, saveRecoverySnapshot, type RecoveryRecord } from "./recoveryStore";
import type { ProjectSnapshot } from "./types";
import { suggestedProjectName } from "./recentProjects";
import { attachProjectThumbnail } from "./thumbnail";
import { createRecoveryScheduler } from "./recoveryScheduler";

export const PROJECT_TABS: Record<string, TabId> = {
  converter: "converter", calibration: "calibration", extractor: "extractor", "single-stage": "gradient-card-extract",
  "five-color": "five-color", "lut-manager": "lut-manager", "lut-compare": "lut-compare", "lut-details": "lut-details", vectorizer: "vectorizer", workshop: "workshop",
};
export function activeWorkflow(): string {
  const tab = useWidgetStore.getState().activeTab;
  if (tab === "gradient-card-generate") return "calibration";
  return Object.keys(PROJECT_TABS).find((kind) => PROJECT_TABS[kind] === tab) ?? "converter";
}
export const useProjectUi = create<{
  centerOpen: boolean; name: string; entry: ProjectFileEntry | null; entries: ProjectFileEntry[]; recoveries: RecoveryRecord[];
  notice: string | null; recoveryError: string | null; limited: string[]; draftId: string;
}>(() => ({ centerOpen: false, name: "Untitled", entry: null, entries: [], recoveries: [], notice: null, recoveryError: null, limited: [], draftId: newProjectIdentity() }));
const touched = new Set<string>();
const coordinator = createOpenRequestCoordinator();
let suppressed = false;
let operation = false;
const recovery = createRecoveryScheduler({
  needed: () => useProjectSessionStore.getState().dirty,
  ready: () => {
    if (operation || suppressed) return false;
    try { for (const adapter of projectAdapterRegistry.all()) adapter.assertReadyToReplace?.(); return true; }
    catch { return false; }
  },
  save: recoverCurrentDraft,
  onError: error => useProjectUi.setState({ recoveryError: error instanceof Error ? error.message : String(error) }),
});
let stopTracking: (() => void) | null = null;
export function markProjectChanged(kind?: string) {
  if (suppressed) return;
  if (kind) touched.add(kind);
  if (kind === "converter") suggestCurrentProjectName();
  if (kind === "converter") useProjectSessionStore.getState().markDocumentChanged(kind, converterDocumentHistory.store.getState().position, newProjectIdentity());
  else useProjectSessionStore.getState().markDirty(newProjectIdentity());
  recovery.request();
}

function suggestCurrentProjectName() {
  const state = useConverterStore.getState();
  const name = suggestedProjectName(useProjectUi.getState().name, (state.imageFile ?? state.modelSurfaceFile ?? state.batchFiles[0])?.name.replace(/\.[^.]+$/, ""));
  if (name !== useProjectUi.getState().name) useProjectUi.setState({ name });
}

export function startProjectTracking(): () => void {
  if (stopTracking) return () => {};
  if (!Object.keys(useProjectSessionStore.getState().documentVersions).length) establishDocumentBaseline();
  const stops = projectAdapterRegistry.all().map((adapter) => adapter.subscribe?.(() => {
    if (adapter.kind === "converter" && !useProjectSessionStore.getState().activeProjectId && !touched.has("converter")) {
      const state = useConverterStore.getState();
      if (!state.imageFile && !state.modelSurfaceFile && !state.batchFiles.length) return;
    }
    markProjectChanged(adapter.kind);
  })).filter((stop): stop is () => void => Boolean(stop));
  stops.push(useSettingsStore.subscribe((next, previous) => {
    if (!useProjectSessionStore.getState().activeProjectId && !touched.size) return;
    const kinds = new Set([...(useProjectSessionStore.getState().snapshot?.manifest.workflowKinds ?? []), ...touched]);
    const usesDefaults = [...kinds].some((kind) => kind === "converter"
      ? !useConverterStore.getState().projectSettings
      : !useWorkflowRuntime.getState().workflows[kind]?.settings);
    const converter = useConverterStore.getState();
    const spoolChanged = kinds.has("converter") && !converter.projectSettings && next.externalSpoolSelections !== previous.externalSpoolSelections
      && externalSpoolMaterial(converter, next) !== externalSpoolMaterial(converter, previous);
    if (spoolChanged || (usesDefaults && JSON.stringify(captureProjectSettings(next)) !== JSON.stringify(captureProjectSettings(previous)))) markProjectChanged();
  }));
  stops.push(useWorkflowRuntime.subscribe((next, previous) => {
    if (next.workflows !== previous.workflows) markProjectChanged();
  }));
  stopTracking = () => { stops.forEach((stop) => stop()); recovery.stop(); stopTracking = null; };
  if (useProjectSessionStore.getState().dirty) recovery.request();
  return stopTracking;
}
function establishDocumentBaseline() {
  useProjectSessionStore.getState().setDocumentBaseline({ converter: converterDocumentHistory.store.getState().position });
}
export async function refreshProjects() {
  const [entries, recoveries] = await Promise.all([listProjectFiles(), listRecoverySnapshots()]);
  useProjectUi.setState({ entries: entries.sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.lastOpenedAt.localeCompare(a.lastOpenedAt)), recoveries });
}
export async function captureCurrentProject(options?: { allowGenerating?: boolean }): Promise<{ snapshot: ProjectSnapshot; sequence: number; savePoint: ProjectSavePoint }> {
  const session = useProjectSessionStore.getState();
  const sequence = session.changeSequence;
  const workflow = activeWorkflow();
  const kinds = new Set([...(session.snapshot?.manifest.workflowKinds ?? []), ...touched, workflow]);
  const limited = useProjectUi.getState().limited;
  const captures = [];
  for (const kind of kinds) {
    if (projectAdapterRegistry.get(kind) && !limited.includes(kind)) captures.push(await projectAdapterRegistry.capture(kind, options));
  }
  const preserved = Object.values(session.snapshot?.documents ?? {}).filter((doc) => !projectAdapterRegistry.get(doc.kind) || limited.includes(doc.kind));
  const preservedRefs = new Set(preserved.flatMap((doc) => doc.resourceRefs));
  const assets = [...captures.flatMap((item) => item.assets), ...Object.values(session.snapshot?.assets ?? {}).filter((asset) => preservedRefs.has(asset.assetId))];
  const snapshot = createProjectSnapshot({
    name: suggestedProjectName(useProjectUi.getState().name, captures.find((item) => item.document.kind === workflow)?.nameHint), workflowKinds: [...kinds], documents: [...captures.map((item) => item.document), ...preserved], assets,
    identity: { projectId: session.activeProjectId ?? useProjectUi.getState().draftId, revisionId: newProjectIdentity() },
  });
  const entry = captures.find((item) => item.document.kind === workflow)?.document.documentId;
  if (entry) { snapshot.manifest.entryDocumentId = entry; snapshot.project.entryDocumentId = entry; }
  await attachProjectThumbnail(snapshot, workflow, workflow === "converter" ? useConverterStore.getState().previewBaseImageUrl : null);
  if (useProjectSessionStore.getState().changeSequence !== sequence || useProjectSessionStore.getState().runtimeEpoch !== session.runtimeEpoch) throw new Error("The project changed while it was being captured. Save again to include the latest edits.");
  return { snapshot: session.snapshot ? createProjectRevision(session.snapshot, snapshot) : snapshot, sequence,
    savePoint: { runtimeEpoch: session.runtimeEpoch, documentVersions: { ...session.documentVersions } } };
}
async function run<T>(status: "opening" | "saving", action: () => Promise<T>): Promise<T> {
  if (operation) throw new Error("Wait for the current project operation to finish");
  operation = true;
  useProjectSessionStore.getState().setStatus(status);
  useProjectUi.setState({ notice: null });
  try { await recovery.settled(); return await action(); }
  catch (error) { useProjectSessionStore.getState().setStatus("error", error instanceof Error ? error.message : String(error)); throw error; }
  finally {
    operation = false;
    recovery.wake();
    if (useProjectSessionStore.getState().status !== "error") useProjectSessionStore.getState().setStatus("idle");
  }
}
export async function saveCurrentProject(saveAs = false): Promise<boolean> {
  const result = await run("saving", async () => {
    if (activeWorkflow() === "converter") suggestCurrentProjectName();
    const destination = await prepareProjectSave(useProjectUi.getState().entry, saveAs, useProjectUi.getState().name);
    if (destination === null) return false;
    const captured = await captureCurrentProject();
    const originalId = useProjectSessionStore.getState().activeProjectId;
    const snapshot = saveAs ? forkProjectSnapshot(captured.snapshot, useProjectUi.getState().name) : captured.snapshot;
    converterDocumentHistory.checkpoint();
    const result = await saveProjectFile(snapshot, useProjectUi.getState().entry, saveAs, destination);
    if (!result) return false;
    let committed = false;
    if (result.persisted) {
      if (saveAs) committed = useProjectSessionStore.getState().commitSavedFork(snapshot, captured.sequence, originalId, captured.savePoint);
      else committed = useProjectSessionStore.getState().commitSavedSnapshot(snapshot, captured.sequence, captured.savePoint);
    }
    const clean = committed && !useProjectSessionStore.getState().dirty;
    if (committed) useProjectUi.setState({ ...(clean ? { name: snapshot.manifest.name } : {}), entry: result.entry, draftId: snapshot.project.projectId });
    useProjectUi.setState({ notice: result.persisted ? (clean ? "project_saved" : "project_saved_earlier") : "project_downloaded" });
    try { await saveRecoverySnapshot(snapshot); await refreshProjects(); }
    catch (error) { useProjectUi.setState({ recoveryError: String(error) }); }
    if (result.entry.catalogWarning) useProjectUi.setState({ recoveryError: result.entry.catalogWarning });
    return clean;
  });
  return result === true;
}
export async function exportCurrentProject() {
  return run("saving", async () => {
    const { snapshot } = await captureCurrentProject();
    const result = await exportProjectBundle(snapshot);
    if (result !== "canceled") useProjectUi.setState({ notice: result === "saved" ? "project_bundle_exported" : "project_bundle_downloaded" });
  });
}

/** File opens and recovery share one activation boundary; only their save points differ. */
async function restoreProjectSnapshot(snapshot: ProjectSnapshot, options: {
  dirty?: boolean;
  entry?: ProjectFileEntry | null;
  limited?: string[];
} = {}): Promise<void> {
  const { dirty = false, entry = null, limited = [] } = options;
  const epoch = useProjectSessionStore.getState().beginRuntimeEpoch();
  suppressed = true;
  try {
    await projectAdapterRegistry.restore(snapshot, {
      projectId: snapshot.project.projectId, revisionId: snapshot.project.revisionId,
      runtimeEpoch: epoch, isCurrent: () => useProjectSessionStore.getState().runtimeEpoch === epoch,
    }, limited);
    useProjectSessionStore.getState().activate(snapshot, {
      savedRevisionId: dirty ? null : snapshot.project.revisionId, dirty,
    });
    establishDocumentBaseline();
    touched.clear();
    useProjectUi.setState({ name: snapshot.manifest.name, entry, draftId: snapshot.project.projectId, limited, centerOpen: false });
    const preferred = snapshot.documents[snapshot.project.entryDocumentId];
    const document = limited.includes(preferred?.kind)
      ? Object.values(snapshot.documents).find(doc => !limited.includes(doc.kind)) : preferred;
    useWidgetStore.getState().setActiveTab((document && PROJECT_TABS[document.kind]) ?? "converter");
  } finally { suppressed = false; }
}

export async function openProjectFile(opened: OpenedProjectFile, allowLimited = false): Promise<void> {
  await run("opening", async () => {
    if (!coordinator.claim(opened.requestId ?? null)) return;
    if (opened.requestId) await nativeProjects?.progress(opened.requestId, "opening");
    const snapshot = await parseProject(opened.bytes);
    const unknown = (await projectAdapterRegistry.unavailable(snapshot)).map((doc) => doc.kind);
    if (unknown.length && !allowLimited) throw new Error(`Unsupported project workspaces: ${unknown.join(", ")}`);
    await restoreProjectSnapshot(snapshot, { entry: opened.entry, limited: unknown });
    try {
      const entry = await rememberProject(snapshot, opened, unknown.length ? "limited" : "opened");
      useProjectUi.setState({ entry });
      await refreshProjects();
      if (entry.catalogWarning) useProjectUi.setState({ recoveryError: entry.catalogWarning });
    } catch (error) { useProjectUi.setState({ recoveryError: `Project opened; recent-file entry could not be updated: ${String(error)}` }); }
  }).catch(async error => {
    if (nativeProjects && opened.requestId) await nativeProjects.complete(opened.requestId, "failed");
    throw error;
  });
}
export function newProject(kind: string, name: string) {
  if (operation) return;
  for (const adapter of projectAdapterRegistry.all()) adapter.assertReadyToReplace?.();
  suppressed = true;
  try {
    for (const adapter of projectAdapterRegistry.all()) adapter.reset?.();
    useProjectSessionStore.getState().reset();
    establishDocumentBaseline();
    touched.clear(); touched.add(kind);
    useProjectUi.setState({ name: name.trim() || "Untitled", draftId: newProjectIdentity(), entry: null, limited: [], centerOpen: false });
    useWidgetStore.getState().setActiveTab(PROJECT_TABS[kind] ?? "converter");
  } finally { suppressed = false; }
}
export async function recoverProject(record: RecoveryRecord) {
  await run("opening", async () => {
    const unavailable = (await projectAdapterRegistry.unavailable(record.snapshot)).map((doc) => doc.kind);
    if (unavailable.length) throw new Error(`Install the required workspace versions before recovering: ${unavailable.join(", ")}`);
    await restoreProjectSnapshot(record.snapshot, { dirty: true });
    recovery.request();
  });
}
async function recoverCurrentDraft() {
  const epoch = useProjectSessionStore.getState().runtimeEpoch;
  try {
    const { snapshot, sequence } = await captureCurrentProject();
    await saveRecoverySnapshot(snapshot);
    if (useProjectSessionStore.getState().runtimeEpoch !== epoch) return;
    useProjectSessionStore.getState().setRecoveryRevision(snapshot.project.revisionId);
    const older = (await listRecoverySnapshots()).filter((item) => item.projectId === snapshot.project.projectId).slice(3);
    await Promise.all(older.map((record) => removeRecoverySnapshot(record.projectId, record.revisionId)));
    if (useProjectSessionStore.getState().runtimeEpoch !== epoch) return;
    useProjectUi.setState({ recoveryError: null });
    if (useProjectSessionStore.getState().changeSequence !== sequence) recovery.request();
  } catch (error) {
    if (useProjectSessionStore.getState().runtimeEpoch === epoch) throw error;
  }
}
