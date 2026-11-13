import { zipSync } from "fflate";
import { serializeProject } from "./archive";
import { newProjectIdentity } from "./identity";
import type { ProjectSnapshot } from "./types";
import type { SaveOutcome } from "../utils/saveGeneratedFile";

export interface ProjectFileHandle {
  name: string;
  getFile(): Promise<File>;
  createWritable(): Promise<{ write(data: Uint8Array): Promise<void>; close(): Promise<void>; abort(): Promise<void> }>;
  requestPermission(options: { mode: "readwrite" }): Promise<string>;
  isSameEntry(other: ProjectFileHandle): Promise<boolean>;
}
export interface ProjectFileEntry {
  fileEntryId: string;
  path?: string;
  name: string;
  projectId: string;
  revisionId: string;
  workflowKinds: string[];
  modifiedAt: string;
  lastOpenedAt: string;
  pinned: boolean;
  handle?: ProjectFileHandle;
  bytes?: Uint8Array;
  thumbnail?: Uint8Array;
  thumbnailDataUrl?: string;
  catalogWarning?: string;
}
export interface NativeProjectOpen {
  requestId?: string;
  state: string;
  error?: string;
  result?: { bytes: Uint8Array; path: string };
}
interface NativeProjects {
  ready(): Promise<boolean>;
  progress(id: string, state: "awaiting-user" | "opening"): Promise<boolean>;
  setDirty(dirty: boolean): Promise<boolean>;
  closeAnswer(id: string, accepted: boolean): Promise<boolean>;
  onClose(listener: (id: string) => void): () => void;
  open(requestId: string): Promise<NativeProjectOpen>;
  openEntry(id: string): Promise<NativeProjectOpen>;
  complete(requestId: string, state: string, metadata?: unknown): Promise<ProjectFileEntry | boolean>;
  save(payload: { bytes: Uint8Array; fileEntryId?: string; suggestedName: string; metadata: unknown; bundle?: boolean }): Promise<{ state: string; entry: ProjectFileEntry | null }>;
  catalog(): Promise<ProjectFileEntry[]>;
  updateEntry(id: string, change: "pin" | "remove" | "locate"): Promise<void>;
  onOpen(listener: (value: NativeProjectOpen) => void): () => void;
}
export const nativeProjects = (window as unknown as { electronAPI?: { projects?: NativeProjects } }).electronAPI?.projects;
export interface OpenedProjectFile { bytes: Uint8Array; entry?: ProjectFileEntry; requestId?: string; handle?: ProjectFileHandle }

async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("lumina-project-files-v1", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("files", { keyPath: "fileEntryId" });
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}
async function catalogOperation<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database();
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = db.transaction("files", mode);
      const request = action(transaction.objectStore("files"));
      transaction.oncomplete = () => resolve(request.result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally { db.close(); }
}
export function listProjectFiles(): Promise<ProjectFileEntry[]> {
  return nativeProjects ? nativeProjects.catalog() : catalogOperation("readonly", (store) => store.getAll());
}
export async function updateProjectFile(entry: ProjectFileEntry, change: "pin" | "remove" | "locate") {
  if (nativeProjects) return nativeProjects.updateEntry(entry.fileEntryId, change);
  if (change === "remove") await catalogOperation("readwrite", (store) => store.delete(entry.fileEntryId));
  if (change === "pin") await catalogOperation("readwrite", (store) => store.put({ ...entry, pinned: !entry.pinned }));
}
export function nativeOpenedFile(value: NativeProjectOpen): OpenedProjectFile | null {
  if (value.state === "cancelled") return null;
  if (value.state !== "opening" || !value.result?.bytes) throw new Error(value.error || "Project file could not be opened");
  return { bytes: new Uint8Array(value.result.bytes), requestId: value.requestId };
}
export async function pickProject(): Promise<OpenedProjectFile | null> {
  if (nativeProjects) return nativeOpenedFile(await nativeProjects.open(newProjectIdentity()));
  const picker = (window as unknown as { showOpenFilePicker?: (options: unknown) => Promise<ProjectFileHandle[]> }).showOpenFilePicker;
  if (picker) {
    try {
      const [handle] = await picker({ multiple: false, types: [{ description: "Lumina project", accept: { "application/zip": [".lum"] } }] });
      if (!handle) return null;
      const file = await handle.getFile();
      let entry: ProjectFileEntry | undefined;
      for (const candidate of await listProjectFiles()) {
        if (candidate.handle && await handle.isSameEntry(candidate.handle)) { entry = candidate; break; }
      }
      return { bytes: new Uint8Array(await file.arrayBuffer()), handle, entry };
    } catch (error) { if (error instanceof DOMException && error.name === "AbortError") return null; throw error; }
  }
  const file = await new Promise<File | null>((resolve) => {
    const input = document.createElement("input");
    input.type = "file"; input.accept = ".lum";
    input.onchange = () => resolve(input.files?.[0] ?? null);
    input.oncancel = () => resolve(null);
    input.click();
  });
  return file ? { bytes: new Uint8Array(await file.arrayBuffer()) } : null;
}
export async function openProjectEntry(entry: ProjectFileEntry): Promise<OpenedProjectFile | null> {
  if (nativeProjects) return nativeOpenedFile(await nativeProjects.openEntry(entry.fileEntryId));
  if (entry.handle) {
    const file = await entry.handle.getFile();
    return { bytes: new Uint8Array(await file.arrayBuffer()), entry, handle: entry.handle };
  }
  if (entry.bytes) return { bytes: entry.bytes, entry };
  throw new Error("Locate the project file to reopen it");
}
function metadata(snapshot: ProjectSnapshot) {
  const { projectId, revisionId, name, workflowKinds, modifiedAt } = snapshot.manifest;
  let thumbnailDataUrl: string | undefined;
  const cover = snapshot.thumbnail?.data;
  // The archive already owns a validated PNG. Catalogs do not need a second,
  // potentially stalled decoder or another render of the same cover.
  if (cover && cover.length <= 71_980) {
    let binary = "";
    for (let offset = 0; offset < cover.length; offset += 8192) binary += String.fromCharCode(...cover.subarray(offset, offset + 8192));
    thumbnailDataUrl = `data:image/png;base64,${btoa(binary)}`;
  }
  return { projectId, revisionId, name, workflowKinds, modifiedAt, thumbnailDataUrl };
}
export async function rememberProject(snapshot: ProjectSnapshot, opened: OpenedProjectFile, state = "opened"): Promise<ProjectFileEntry> {
  if (nativeProjects && opened.requestId) {
    const result = await nativeProjects.complete(opened.requestId, state, await metadata(snapshot));
    if (!result || typeof result === "boolean") throw new Error("Project open could not be acknowledged");
    return result;
  }
  const entry: ProjectFileEntry = {
    fileEntryId: opened.entry?.fileEntryId ?? newProjectIdentity(), ...await metadata(snapshot),
    pinned: opened.entry?.pinned ?? false, lastOpenedAt: new Date().toISOString(),
    handle: opened.handle ?? opened.entry?.handle,
    ...(!opened.handle && !opened.entry?.handle ? { bytes: opened.bytes } : {}),
    thumbnail: snapshot.thumbnail?.data,
  };
  await catalogOperation("readwrite", (store) => store.put(entry));
  return entry;
}
export function downloadBytes(bytes: Uint8Array, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = name;
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function prepareProjectSave(entry: ProjectFileEntry | null, saveAs: boolean, name: string): Promise<ProjectFileHandle | null | undefined> {
  if (nativeProjects) return undefined;
  let handle = saveAs ? undefined : entry?.handle;
  const picker = (window as unknown as { showSaveFilePicker?: (options: unknown) => Promise<ProjectFileHandle> }).showSaveFilePicker;
  if (!handle && picker) {
    try { handle = await picker({ suggestedName: `${name.replace(/[\\/:*?"<>|]/g, "-") || "Untitled"}.lum`, types: [{ description: "Lumina project", accept: { "application/zip": [".lum"] } }] }); }
    catch (error) { if (error instanceof DOMException && error.name === "AbortError") return null; throw error; }
  }
  if (handle && await handle.requestPermission({ mode: "readwrite" }) !== "granted") throw new Error("Write access to this project file was denied");
  return handle;
}
export async function saveProjectFile(snapshot: ProjectSnapshot, entry: ProjectFileEntry | null, saveAs: boolean, handle?: ProjectFileHandle): Promise<{ persisted: boolean; entry: ProjectFileEntry } | null> {
  const bytes = await serializeProject(snapshot);
  const suggestedName = `${snapshot.manifest.name.replace(/[\\/:*?"<>|]/g, "-") || "Untitled"}.lum`;
  if (nativeProjects) {
    const result = await nativeProjects.save({ bytes, fileEntryId: saveAs ? undefined : entry?.fileEntryId, suggestedName, metadata: await metadata(snapshot) });
    if (result.state === "cancelled") return null;
    if (result.state !== "saved" || !result.entry) throw new Error("Project could not be saved");
    return { persisted: true, entry: result.entry };
  }
  if (handle) {
    const stream = await handle.createWritable();
    try { await stream.write(bytes); await stream.close(); }
    catch (error) { await stream.abort(); throw error; }
  } else { downloadBytes(bytes, suggestedName, "application/zip"); }
  let sameEntry = saveAs ? undefined : entry ?? undefined;
  try {
    if (handle) for (const candidate of await listProjectFiles()) {
      if (candidate.handle && await handle.isSameEntry(candidate.handle)) { sameEntry = candidate; break; }
    }
    const saved = await rememberProject(snapshot, { bytes, handle, entry: sameEntry });
    return { persisted: Boolean(handle), entry: saved };
  } catch (error) {
    // A completed writable is the save receipt. Losing the optional catalog
    // must not lose the handle or lie about the file that was just written.
    return { persisted: Boolean(handle), entry: {
      ...sameEntry, ...metadata(snapshot), fileEntryId: sameEntry?.fileEntryId ?? newProjectIdentity(),
      pinned: sameEntry?.pinned ?? false, lastOpenedAt: new Date().toISOString(), handle,
      ...(!handle ? { bytes } : {}), catalogWarning: `Project catalog update failed: ${String(error)}`,
    } };
  }
}
export async function exportProjectBundle(snapshot: ProjectSnapshot): Promise<SaveOutcome> {
  if (!snapshot.thumbnail) throw new Error("This project has no preview image");
  const project = await serializeProject(snapshot);
  const bytes = zipSync({ "project.lum": project, "preview.png": snapshot.thumbnail.data }, { level: 6 });
  const suggestedName = `${snapshot.manifest.name}.lumina.zip`;
  if (nativeProjects) {
    const result = await nativeProjects.save({ bytes, suggestedName, metadata: {}, bundle: true });
    if (result.state === "cancelled") return "canceled";
    if (result.state === "saved") return "saved";
    throw new Error("file_save_failed");
  }
  downloadBytes(bytes, suggestedName, "application/zip");
  return "download-started";
}
