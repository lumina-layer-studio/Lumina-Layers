import { create } from "zustand";
import { downloadResourceBlob } from "../api/client";
import { useConverterStore } from "../stores/converter";
import { useProjectSessionStore } from "../stores/projectSessionStore";
import { useWidgetStore } from "../stores/widgetStore";
import { useSettingsStore } from "../stores/settingsStore";
import { captureProjectSettings } from "../stores/converter/project";
import { useWorkflowRuntime } from "./workflowRuntime";
import type { TabId } from "../types/widget";
import { projectAdapterRegistry } from "./adapters/registry";
import { parseProject } from "./archive";
import { exportProjectBundle, listProjectFiles, nativeProjects, prepareProjectSave, rememberProject, saveProjectFile, type OpenedProjectFile, type ProjectFileEntry } from "./files";
import { createProjectAsset, createProjectRevision, createProjectSnapshot, forkProjectSnapshot, newProjectIdentity } from "./identity";
import { createOpenRequestCoordinator } from "./openRequestCoordinator";
import { listRecoverySnapshots, removeRecoverySnapshot, saveRecoverySnapshot, type RecoveryRecord } from "./recoveryStore";
import type { ProjectSnapshot } from "./types";

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
let recoveryTimer: ReturnType<typeof setTimeout> | undefined;
let stopTracking: (() => void) | null = null;
export function markProjectChanged(kind?: string) {
  if (suppressed) return;
  if (kind) touched.add(kind);
  useProjectSessionStore.getState().markDirty(newProjectIdentity());
  clearTimeout(recoveryTimer);
  recoveryTimer = setTimeout(() => { void recoverCurrentDraft(); }, 5000);
}

export function startProjectTracking(): () => void {
  if (stopTracking) return () => {};
  const stops = projectAdapterRegistry.all().map((adapter) => adapter.subscribe?.(() => {
    if (adapter.kind === "converter" && !useProjectSessionStore.getState().activeProjectId && !touched.has("converter")) {
      const state = useConverterStore.getState();
      if (!state.imageFile && !state.modelSurfaceFile && !state.batchFiles.length) return;
    }
    markProjectChanged(adapter.kind);
  })).filter((stop): stop is () => void => Boolean(stop));
  stops.push(useSettingsStore.subscribe((next, previous) => {
    if (!useProjectSessionStore.getState().activeProjectId && !touched.size) return;
    if (JSON.stringify(captureProjectSettings(next)) !== JSON.stringify(captureProjectSettings(previous))) markProjectChanged();
  }));
  stops.push(useWorkflowRuntime.subscribe((next, previous) => {
    if (next.workflows !== previous.workflows) markProjectChanged();
  }));
  stopTracking = () => { stops.forEach((stop) => stop()); clearTimeout(recoveryTimer); stopTracking = null; };
  return stopTracking;
}
export async function refreshProjects() {
  const [entries, recoveries] = await Promise.all([listProjectFiles(), listRecoverySnapshots()]);
  useProjectUi.setState({ entries: entries.sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.lastOpenedAt.localeCompare(a.lastOpenedAt)), recoveries });
}
async function attachThumbnail(snapshot: ProjectSnapshot, workflow: string) {
  let blob: Blob | null = null;
  if (workflow === "converter") {
    const preview = useConverterStore.getState().previewBaseImageUrl;
    if (preview) blob = await downloadResourceBlob(preview);
  }
  blob ??= Object.values(snapshot.assets).find((asset) => /^image\/(png|jpeg|webp|svg\+xml)$/.test(asset.mediaType))
    ? (() => { const asset = Object.values(snapshot.assets).find((item) => /^image\/(png|jpeg|webp|svg\+xml)$/.test(item.mediaType))!; return new Blob([asset.data], { type: asset.mediaType }); })() : null;
  const canvas = document.createElement("canvas");
  canvas.width = 640; canvas.height = 400;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Project thumbnail could not be created");
  context.fillStyle = "#e8edf3"; context.fillRect(0, 0, 640, 400);
  if (blob) {
    const image = await createImageBitmap(blob);
    const scale = Math.min(608 / image.width, 368 / image.height);
    context.drawImage(image, (640 - image.width * scale) / 2, (400 - image.height * scale) / 2, image.width * scale, image.height * scale);
    image.close();
  } else {
    context.fillStyle = "#344459"; context.font = "600 28px sans-serif"; context.fillText(snapshot.manifest.name.slice(0, 32), 32, 180);
    context.font = "18px sans-serif"; context.fillText(workflow, 32, 220);
  }
  const png = await new Promise<Blob>((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error("Project thumbnail could not be encoded")), "image/png"));
  const asset = await createProjectAsset("thumbnail", new Uint8Array(await png.arrayBuffer()), "image/png", "thumbnail.png", "resource");
  snapshot.thumbnail = { ...asset, path: "preview/thumbnail.png" };
  snapshot.manifest.thumbnail = { path: "preview/thumbnail.png", sha256: asset.sha256, byteSize: asset.byteSize, mediaType: "image/png" };
}
export async function captureCurrentProject(options?: { allowGenerating?: boolean }): Promise<{ snapshot: ProjectSnapshot; sequence: number }> {
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
    name: useProjectUi.getState().name, workflowKinds: [...kinds], documents: [...captures.map((item) => item.document), ...preserved], assets,
    identity: { projectId: session.activeProjectId ?? useProjectUi.getState().draftId, revisionId: newProjectIdentity() },
  });
  const entry = captures.find((item) => item.document.kind === workflow)?.document.documentId;
  if (entry) { snapshot.manifest.entryDocumentId = entry; snapshot.project.entryDocumentId = entry; }
  await attachThumbnail(snapshot, workflow);
  if (useProjectSessionStore.getState().changeSequence !== sequence || useProjectSessionStore.getState().runtimeEpoch !== session.runtimeEpoch) throw new Error("The project changed while it was being captured. Save again to include the latest edits.");
  return { snapshot: session.snapshot ? createProjectRevision(session.snapshot, snapshot) : snapshot, sequence };
}
async function run<T>(status: "opening" | "saving", action: () => Promise<T>): Promise<T | undefined> {
  if (operation) throw new Error("Wait for the current project operation to finish");
  operation = true;
  useProjectSessionStore.getState().setStatus(status);
  useProjectUi.setState({ notice: null });
  try { return await action(); }
  catch (error) { useProjectSessionStore.getState().setStatus("error", error instanceof Error ? error.message : String(error)); throw error; }
  finally {
    operation = false;
    if (useProjectSessionStore.getState().status !== "error") useProjectSessionStore.getState().setStatus("idle");
  }
}
export async function saveCurrentProject(saveAs = false): Promise<boolean> {
  const result = await run("saving", async () => {
    const destination = await prepareProjectSave(useProjectUi.getState().entry, saveAs, useProjectUi.getState().name);
    if (destination === null) return false;
    const captured = await captureCurrentProject();
    const originalId = useProjectSessionStore.getState().activeProjectId;
    const snapshot = saveAs ? forkProjectSnapshot(captured.snapshot, useProjectUi.getState().name) : captured.snapshot;
    const result = await saveProjectFile(snapshot, useProjectUi.getState().entry, saveAs, destination);
    if (!result) return false;
    let committed = false;
    if (result.persisted) {
      if (saveAs) committed = useProjectSessionStore.getState().commitSavedFork(snapshot, captured.sequence, originalId);
      else committed = useProjectSessionStore.getState().commitSavedSnapshot(snapshot, captured.sequence);
    }
    if (committed) useProjectUi.setState({ entry: result.entry, draftId: snapshot.project.projectId });
    useProjectUi.setState({ notice: result.persisted ? (committed ? "project_saved" : "project_saved_earlier") : "project_downloaded" });
    try { await saveRecoverySnapshot(snapshot); await refreshProjects(); }
    catch (error) { useProjectUi.setState({ recoveryError: String(error) }); }
    return committed;
  });
  return result === true;
}
export async function exportCurrentProject() {
  return run("saving", async () => {
    const { snapshot } = await captureCurrentProject();
    await exportProjectBundle(snapshot);
    useProjectUi.setState({ notice: "project_bundle_exported" });
  });
}
export async function openProjectFile(opened: OpenedProjectFile, allowLimited = false): Promise<void> {
  await run("opening", async () => {
    if (!coordinator.claim(opened.requestId ?? null)) return;
    if (opened.requestId) await nativeProjects?.progress(opened.requestId, "opening");
    const snapshot = await parseProject(opened.bytes);
    const unknown = (await projectAdapterRegistry.unavailable(snapshot)).map((doc) => doc.kind);
    if (unknown.length && !allowLimited) throw new Error(`Unsupported project workspaces: ${unknown.join(", ")}`);
    const epoch = useProjectSessionStore.getState().beginRuntimeEpoch();
    suppressed = true;
    try {
      await projectAdapterRegistry.restore(snapshot, { projectId: snapshot.project.projectId, revisionId: snapshot.project.revisionId, runtimeEpoch: epoch, isCurrent: () => useProjectSessionStore.getState().runtimeEpoch === epoch }, unknown);
      useProjectSessionStore.getState().activate(snapshot, { savedRevisionId: snapshot.project.revisionId, dirty: false });
      touched.clear();
      useProjectUi.setState({ name: snapshot.manifest.name, entry: opened.entry ?? null, draftId: snapshot.project.projectId, limited: unknown, centerOpen: false });
      const document = unknown.includes(snapshot.documents[snapshot.project.entryDocumentId]?.kind) ? Object.values(snapshot.documents).find((doc) => !unknown.includes(doc.kind)) : snapshot.documents[snapshot.project.entryDocumentId];
      useWidgetStore.getState().setActiveTab((document && PROJECT_TABS[document.kind]) ?? "converter");
    } finally { suppressed = false; }
    try {
      const entry = await rememberProject(snapshot, opened, unknown.length ? "limited" : "opened");
      useProjectUi.setState({ entry });
      await refreshProjects();
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
    touched.clear(); touched.add(kind);
    useProjectUi.setState({ name: name.trim() || "Untitled", draftId: newProjectIdentity(), entry: null, limited: [], centerOpen: false });
    useWidgetStore.getState().setActiveTab(PROJECT_TABS[kind] ?? "converter");
  } finally { suppressed = false; }
}
export async function recoverProject(record: RecoveryRecord) {
  await run("opening", async () => {
    const unavailable = (await projectAdapterRegistry.unavailable(record.snapshot)).map((doc) => doc.kind);
    if (unavailable.length) throw new Error(`Install the required workspace versions before recovering: ${unavailable.join(", ")}`);
    const epoch = useProjectSessionStore.getState().beginRuntimeEpoch();
    suppressed = true;
    try {
      await projectAdapterRegistry.restore(record.snapshot, { projectId: record.projectId, revisionId: record.revisionId, runtimeEpoch: epoch, isCurrent: () => useProjectSessionStore.getState().runtimeEpoch === epoch });
      useProjectSessionStore.getState().activate(record.snapshot, { dirty: true });
      touched.clear();
      useProjectUi.setState({ name: record.snapshot.manifest.name, entry: null, draftId: record.projectId, limited: [], centerOpen: false });
      useWidgetStore.getState().setActiveTab(PROJECT_TABS[record.snapshot.documents[record.snapshot.project.entryDocumentId].kind] ?? "converter");
    } finally { suppressed = false; }
  });
}
async function recoverCurrentDraft() {
  if (operation || !useProjectSessionStore.getState().dirty) return;
  try {
    const { snapshot } = await captureCurrentProject();
    await saveRecoverySnapshot(snapshot);
    useProjectSessionStore.getState().setRecoveryRevision(snapshot.project.revisionId);
    const older = (await listRecoverySnapshots()).filter((item) => item.projectId === snapshot.project.projectId).slice(3);
    await Promise.all(older.map((record) => removeRecoverySnapshot(record.projectId, record.revisionId)));
    useProjectUi.setState({ recoveryError: null });
  } catch (error) { useProjectUi.setState({ recoveryError: error instanceof Error ? error.message : String(error) }); }
}
