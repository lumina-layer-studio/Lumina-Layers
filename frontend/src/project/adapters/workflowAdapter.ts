import type { StoreApi } from "zustand";
import apiClient, { downloadResourceBlob } from "../../api/client";
import { colorcheckerRelease } from "../../api/extractor";
import { closeSession } from "../../api/session";
import { captureProjectSettings, PROJECT_SETTING_KEYS } from "../../stores/converter/project";
import { DEFAULT_SETTINGS } from "../../stores/settingsStore";
import { fileAsset, projectFile } from "../assets";
import { decodeStructuredClone, encodeStructuredClone } from "../structuredCloneCodec";
import { captureProjectTemplate, restoreProjectTemplate } from "../resources";
import { setWorkflowRuntime, workflowHeaders, workflowRuntime, workflowSettings, type WorkflowRuntime } from "../workflowRuntime";
import type { JsonObject, JsonValue, ProjectAsset, ProjectSnapshot, WorkflowDocument } from "../types";
import { assertRestoreIsCurrent, type PreparedProjectRestore, type ProjectAdapter, type ProjectRestoreContext } from "./types";

type State = Record<string, unknown>;
const RESOURCE_FIELDS: Record<string, string> = {
  downloadUrl: "outputResource", modelUrl: "modelResource", previewUrl: "previewResource",
  download_url: "output_resource", model_url: "model_resource", preview_url: "preview_resource",
};
const RUNTIME_FIELDS = Object.fromEntries(Object.entries(RESOURCE_FIELDS).map(([key, value]) => [value, key]));
interface WorkflowPayload {
  state: JsonValue;
  checkpoint: string | null;
  template: string | null;
  colorchecker: Record<string, string>;
  luts: Record<string, string>;
  settings: WorkflowRuntime["settings"];
}
interface PreparedWorkflow extends PreparedProjectRestore {
  state: State;
  runtime: WorkflowRuntime;
  previousRuntime: WorkflowRuntime | undefined;
  urls: string[];
  sessions: string[];
  colorcheckerIds: string[];
}
export interface WorkflowSpec<S extends object> {
  kind: string;
  store: StoreApi<S>;
  fields: Array<keyof S & string>;
  busy: Array<keyof S & string>;
  catalogFields?: Array<keyof S & string>;
  session?: { field: keyof S & string; kind: "extractor" | "single-stage"; urls: Record<string, keyof S & string>; workspaceField?: keyof S & string };
  colorchecker?: Array<keyof S & string>;
  lutNames?: (state: S) => string[];
}

/** Adapters persist explicit state fields; actions stay owned by each store. */
export function createWorkflowAdapter<S extends object>(spec: WorkflowSpec<S>): ProjectAdapter {
  const store = spec.store;
  const allowed = new Set<string>(spec.fields);
  function validate(document: WorkflowDocument): WorkflowPayload {
    if (document.kind !== spec.kind || document.schemaVersion !== 2) throw new Error(`Unsupported ${spec.kind} project version`);
    const payload = document.payload as unknown as WorkflowPayload;
    if (!payload.state || !payload.colorchecker || !payload.luts) throw new Error("Workflow project is incomplete");
    if (payload.settings !== null) {
      if (!payload.settings || typeof payload.settings !== "object" || Object.keys(payload.settings).some((key) => !PROJECT_SETTING_KEYS.includes(key as typeof PROJECT_SETTING_KEYS[number]))) throw new Error("Invalid project settings");
      for (const key of PROJECT_SETTING_KEYS) {
        const value = payload.settings[key];
        if (key === "custom3mfTemplateId" && (value === null || typeof value === "string")) continue;
        if (typeof value !== typeof DEFAULT_SETTINGS[key] || (typeof value === "number" && !Number.isFinite(value))) throw new Error(`Invalid project setting: ${key}`);
      }
    }
    const state = decodeStructuredClone(payload.state);
    if (!state || typeof state !== "object" || Array.isArray(state) || Object.keys(state).some((key) => !allowed.has(RUNTIME_FIELDS[key] ?? key))) throw new Error("Invalid workflow state");
    const defaults = store.getInitialState() as State;
    for (const [savedKey, value] of Object.entries(state)) {
      const expected = defaults[RUNTIME_FIELDS[savedKey] ?? savedKey];
      if (expected === null || expected === undefined) continue;
      if (Array.isArray(expected) ? !Array.isArray(value) : expected instanceof Map ? !(value instanceof Map) : expected instanceof Set ? !(value instanceof Set) : typeof value !== typeof expected) throw new Error(`Invalid workflow field: ${savedKey}`);
      if (typeof value === "number" && !Number.isFinite(value)) throw new Error(`Invalid workflow number: ${savedKey}`);
    }
    const refs = [payload.checkpoint, payload.template, ...Object.values(payload.colorchecker), ...Object.values(payload.luts)];
    if (refs.some((ref) => ref !== null && ref !== undefined && (typeof ref !== "string" || !document.resourceRefs.includes(ref)))) throw new Error("Invalid workflow resource reference");
    if (Object.keys(payload.colorchecker).some((key) => !spec.colorchecker?.includes(key as keyof S & string))) throw new Error("Invalid calibrated image reference");
    return payload;
  }
  async function capture() {
    const state = store.getState();
    if (spec.busy.some((key) => state[key])) throw new Error("Wait for the current operation before saving the project");
    const phase = (state as State).colorchecker_phase;
    if (phase === "calibrating" || phase === "confirming") throw new Error("Finish ColorChecker confirmation before saving the project");
    const assets: ProjectAsset[] = [];
    let assetSequence = 0;
    const add = async (file: File, role: "asset" | "resource" = "asset") => {
      const asset = await fileAsset(`${spec.kind}.${assetSequence++}`, file, role);
      assets.push(asset);
      return asset.assetId;
    };
    async function portable(value: unknown, key = ""): Promise<unknown> {
      if (value instanceof File) return { __projectAsset: await add(value), as: "file" };
      if (typeof value === "string" && (value.startsWith("blob:") || /\/api\/files\//.test(value))) {
        const blob = await downloadResourceBlob(value);
        return { __projectAsset: await add(new File([blob], `${key || "result"}.${blob.type.includes("svg") ? "svg" : blob.type.includes("png") ? "png" : "bin"}`, { type: blob.type })), as: "url" };
      }
      if (Array.isArray(value)) return Promise.all(value.map((item) => portable(item, key)));
      if (value instanceof Map) return new Map(await Promise.all([...value].map(async ([k, v]) => [k, await portable(v, String(k))] as const)));
      if (value instanceof Set) return new Set(value);
      if (value && typeof value === "object") {
        const entries = await Promise.all(Object.entries(value).filter(([k]) => !k.endsWith("_path") && !["path", "threemfDiskPath"].includes(k)).map(async ([k, v]) => [RESOURCE_FIELDS[k] ?? k, await portable(v, k)]));
        return Object.fromEntries(entries);
      }
      return value;
    }
    const captured = await portable(Object.fromEntries(spec.fields.map((key) => [key, state[key]])));
    const payload: WorkflowPayload = { state: await encodeStructuredClone(captured), checkpoint: null, template: null, colorchecker: {}, luts: {}, settings: captureProjectSettings(workflowSettings(spec.kind)) };
    const template = await captureProjectTemplate(payload.settings?.custom3mfTemplateId ?? null);
    if (template) { payload.template = await add(template, "resource"); payload.settings!.custom3mfTemplateId = null; }
    if (spec.session && state[spec.session.field]) {
      const response = await apiClient.get<Blob>(`/projects/workflows/${spec.session.kind}/${encodeURIComponent(String(state[spec.session.field]))}`, { responseType: "blob" });
      payload.checkpoint = await add(new File([response.data], "checkpoint.zip", { type: "application/zip" }), "resource");
    }
    for (const key of spec.colorchecker ?? []) {
      if (!state[key]) continue;
      const result = await apiClient.get<Blob>(`/projects/colorchecker/${encodeURIComponent(String(state[key]))}`, { responseType: "blob" });
      payload.colorchecker[key] = await add(new File([result.data], "calibrated.png", { type: "image/png" }), "resource");
    }
    for (const name of [...new Set(spec.lutNames?.(state) ?? [])].filter(Boolean)) {
      let file = workflowRuntime(spec.kind)?.lutFiles[name];
      if (!file) {
        const response = await apiClient.post<Blob>("/lut/project-source", { source_kind: "legacy_single", lut_name: name }, { headers: workflowHeaders(spec.kind), responseType: "blob" });
        file = new File([response.data], "source.lut.zip", { type: "application/zip" });
      }
      payload.luts[name] = await add(file, "resource");
    }
    return { document: { documentId: `${spec.kind}.main`, kind: spec.kind, schemaVersion: 2, payload: payload as unknown as JsonObject, inputRevisionIds: [], resourceRefs: assets.map((asset) => asset.assetId), requiredCapabilities: [`workflow.${spec.kind}-v2`] }, assets };
  }
  async function discard(prepared: PreparedWorkflow) {
    prepared.urls.forEach((url) => URL.revokeObjectURL(url));
    await Promise.all([...prepared.sessions.map((id) => closeSession(id)), ...prepared.colorcheckerIds.map(colorcheckerRelease)]);
  }
  async function prepareRestore(snapshot: ProjectSnapshot, context: ProjectRestoreContext): Promise<PreparedWorkflow> {
    assertRestoreIsCurrent(context);
    const document = Object.values(snapshot.documents).find((doc) => doc.kind === spec.kind)!;
    const payload = validate(document);
    const prepared: PreparedWorkflow = {
      snapshot, document, rollbackState: store.getState(), previousRuntime: workflowRuntime(spec.kind),
      state: { ...store.getInitialState() } as State, runtime: { contextId: null, lutFiles: {}, settings: payload.settings },
      urls: [], sessions: [], colorcheckerIds: [],
    };
    function restore(value: unknown): unknown {
      if (Array.isArray(value)) return value.map(restore);
      if (value instanceof Map) return new Map([...value].map(([k, v]) => [k, restore(v)]));
      if (value instanceof Set) return value;
      if (value && typeof value === "object") {
        const node = value as Record<string, unknown>;
        if (typeof node.__projectAsset === "string") {
          if (!document.resourceRefs.includes(node.__projectAsset) || !["file", "url"].includes(String(node.as))) throw new Error("Invalid workflow asset");
          const file = projectFile(snapshot, node.__projectAsset)!;
          if (node.as === "file") return file;
          const url = URL.createObjectURL(file);
          prepared.urls.push(url);
          return url;
        }
        return Object.fromEntries(Object.entries(node).map(([k, v]) => [RUNTIME_FIELDS[k] ?? k, restore(v)]));
      }
      return value;
    }
    try {
      Object.assign(prepared.state, restore(decodeStructuredClone(payload.state)));
      if (payload.template) {
        const template = await restoreProjectTemplate(projectFile(snapshot, payload.template)!);
        prepared.sessions.push(template.session_id);
        prepared.runtime.settings = { ...prepared.runtime.settings!, custom3mfTemplateId: template.template_id };
      }
      for (const [key, ref] of Object.entries(payload.colorchecker)) {
        const form = new FormData();
        form.append("image", projectFile(snapshot, ref)!);
        const response = await apiClient.post<{ file_id: string }>("/projects/colorchecker", form);
        prepared.colorcheckerIds.push(response.data.file_id);
        prepared.state[key] = response.data.file_id;
      }
      if (payload.checkpoint && spec.session) {
        const form = new FormData();
        form.append("checkpoint", projectFile(snapshot, payload.checkpoint)!);
        const result = await apiClient.post<{ session_id: string; urls: Record<string, string> }>(`/projects/workflows/${spec.session.kind}`, form);
        prepared.sessions.push(result.data.session_id);
        prepared.state[spec.session.field] = result.data.session_id;
        if (spec.session.workspaceField) prepared.state[spec.session.workspaceField] = result.data.session_id;
        for (const [key, field] of Object.entries(spec.session.urls)) {
          if (result.data.urls[key]) prepared.state[field] = result.data.urls[key];
        }
      }
      if (Object.keys(payload.luts).length) {
        const form = new FormData();
        form.append("names", JSON.stringify(Object.keys(payload.luts)));
        for (const [name, ref] of Object.entries(payload.luts)) {
          const file = projectFile(snapshot, ref)!;
          prepared.runtime.lutFiles[name] = file;
          form.append("files", file);
        }
        const result = await apiClient.post<{ session_id: string }>("/projects/lut-context", form);
        prepared.sessions.push(result.data.session_id);
        prepared.runtime.contextId = result.data.session_id;
      }
      assertRestoreIsCurrent(context);
      prepared.runtime.sessionIds = prepared.sessions;
      prepared.runtime.urls = prepared.urls;
      prepared.runtime.colorcheckerIds = prepared.colorcheckerIds;
      return prepared;
    } catch (error) {
      await discard(prepared);
      throw error;
    }
  }
  return {
    kind: spec.kind, capture, validate, prepareRestore,
    unavailable: async (document) => document.schemaVersion !== 2,
    assertReadyToReplace: () => {
      const state = store.getState();
      if (spec.busy.some((key) => state[key]) || ["calibrating", "confirming"].includes(String((state as State).colorchecker_phase))) throw new Error(`Wait for the ${spec.kind} operation before opening another project`);
    },
    subscribe: (listener) => store.subscribe((next, previous) => {
      if (spec.fields.some((key) => !spec.catalogFields?.includes(key) && next[key] !== previous[key]) || (spec.session && next[spec.session.field] !== previous[spec.session.field])) listener();
    }),
    reset: () => {
      const runtime = workflowRuntime(spec.kind);
      runtime?.urls?.forEach((url) => URL.revokeObjectURL(url));
      runtime?.colorcheckerIds?.forEach((id) => { void colorcheckerRelease(id); });
      store.setState(store.getInitialState()); setWorkflowRuntime(spec.kind, undefined);
    },
    enumerateDependencies: (document) => [...document.resourceRefs],
    commitRestore(value, context) {
      assertRestoreIsCurrent(context);
      const prepared = value as PreparedWorkflow;
      setWorkflowRuntime(spec.kind, prepared.runtime);
      store.setState(prepared.state as S);
    },
    async rollbackRestore(value) {
      const prepared = value as PreparedWorkflow;
      setWorkflowRuntime(spec.kind, prepared.previousRuntime);
      store.setState(prepared.rollbackState as S);
    },
    discardRestore: (value) => discard(value as PreparedWorkflow),
    finalizeRestore(value) {
      const runtime = (value as PreparedWorkflow).previousRuntime;
      runtime?.urls?.forEach((url) => URL.revokeObjectURL(url));
      runtime?.colorcheckerIds?.forEach((id) => { void colorcheckerRelease(id); });
    },
    migration: (document) => document,
    normalizeForCompare: (document) => document.payload,
  };
}
