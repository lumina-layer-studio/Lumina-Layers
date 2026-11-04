import { sha256Hex } from "./hash";
import type {
  JsonObject,
  ProjectAsset,
  ProjectSnapshot,
  ProjectManifest,
  ProjectMetadata,
  WorkflowDocument,
} from "./types";
import {
  PROJECT_CONTAINER_VERSION,
  PROJECT_FORMAT,
  PROJECT_SCHEMA_VERSION,
} from "./types";

export function newProjectIdentity(): string {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (typeof randomUUID === "function") {
    return randomUUID.call(globalThis.crypto);
  }
  return "lumina-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
}

export async function createProjectAsset(
  assetId: string,
  data: Uint8Array,
  mediaType: string,
  filename?: string,
  role: "asset" | "resource" = "asset",
): Promise<ProjectAsset> {
  const sha256 = await sha256Hex(
    data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength),
  );
  return {
    assetId,
    sha256,
    path: (role === "resource" ? "resources/" : "assets/") + sha256,
    byteSize: data.byteLength,
    mediaType,
    ...(filename ? { filename } : {}),
    role,
    data: new Uint8Array(data),
  };
}

function cloneJson<T extends JsonObject>(value: T): T {
  if (typeof structuredClone === "function") {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

function buildManifest(
  projectId: string,
  revisionId: string,
  name: string,
  workflowKinds: string[],
  documents: WorkflowDocument[],
  assets: ProjectAsset[],
  now: string,
  sourceProjectId: string | null,
  sourceRevisionId: string | null,
): { manifest: ProjectManifest; project: ProjectMetadata } {
  // Keep one logical descriptor per asset id even when two logical references
  // share the same content-addressed bytes. The archive writer deduplicates
  // the physical member, while the manifest preserves every reference target.
  const descriptors = assets.map(({ data: _data, ...descriptor }) => descriptor);
  const requiredCapabilities = unique(
    documents.flatMap((document) => document.requiredCapabilities),
  );
  const entryDocumentId = documents[0]?.documentId ?? "";
  const manifest: ProjectManifest = {
    format: PROJECT_FORMAT,
    containerVersion: PROJECT_CONTAINER_VERSION,
    schemaVersion: PROJECT_SCHEMA_VERSION,
    projectId,
    revisionId,
    name,
    workflowKinds: unique(workflowKinds),
    createdAt: now,
    modifiedAt: now,
    entryDocumentId,
    documents: documents.map((document) => ({
      documentId: document.documentId,
      kind: document.kind,
      schemaVersion: document.schemaVersion,
      path: "documents/" + document.documentId + ".json",
    })),
    resources: descriptors,
    thumbnail: null,
    requiredCapabilities,
    degradedFields: [],
    warnings: [],
  };
  const project: ProjectMetadata = {
    projectId,
    revisionId,
    name,
    workflowKinds: unique(workflowKinds),
    entryDocumentId,
    sourceProjectId,
    sourceRevisionId,
    documentIds: documents.map((document) => document.documentId),
    resourceRefs: assets.map((asset) => asset.assetId),
  };
  return { manifest, project };
}

export function createProjectSnapshot(input: {
  name: string;
  workflowKinds: string[];
  documents: WorkflowDocument[];
  assets?: ProjectAsset[];
  identity?: { projectId: string; revisionId: string };
}): ProjectSnapshot {
  if (input.documents.length === 0) {
    throw new Error("A project needs at least one workflow document");
  }
  if (
    new Set(input.documents.map((document) => document.documentId)).size !==
    input.documents.length
  ) {
    throw new Error("Project document identities must be unique");
  }
  const inputAssets = input.assets ?? [];
  if (
    new Set(inputAssets.map((asset) => asset.assetId)).size !== inputAssets.length
  ) {
    throw new Error("Project asset identities must be unique");
  }
  const projectId = input.identity?.projectId ?? newProjectIdentity();
  const revisionId = input.identity?.revisionId ?? newProjectIdentity();
  const now = new Date().toISOString();
  const documents = input.documents.map((document) => ({
    ...document,
    inputRevisionIds: [...document.inputRevisionIds],
    resourceRefs: [...document.resourceRefs],
    requiredCapabilities: [...document.requiredCapabilities],
    payload: cloneJson(document.payload),
  }));
  const assets = Object.fromEntries(
    inputAssets.map((asset) => [
      asset.assetId,
      { ...asset, data: new Uint8Array(asset.data) },
    ]),
  );
  const built = buildManifest(
    projectId,
    revisionId,
    input.name,
    input.workflowKinds,
    documents,
    Object.values(assets),
    now,
    null,
    null,
  );
  return {
    manifest: built.manifest,
    project: built.project,
    documents: Object.fromEntries(
      documents.map((document) => [document.documentId, document]),
    ),
    assets,
    thumbnail: null,
  };
}

export function forkProjectSnapshot(
  source: ProjectSnapshot,
  name: string,
): ProjectSnapshot {
  const documents = Object.values(source.documents).map((document) => ({
    ...document,
    inputRevisionIds: [...document.inputRevisionIds],
    resourceRefs: [...document.resourceRefs],
    requiredCapabilities: [...document.requiredCapabilities],
    payload: cloneJson(document.payload),
  }));
  const assets = Object.fromEntries(
    Object.values(source.assets).map((asset) => [
      asset.assetId,
      { ...asset, data: new Uint8Array(asset.data) },
    ]),
  );
  const projectId = newProjectIdentity();
  const revisionId = newProjectIdentity();
  const now = new Date().toISOString();
  const built = buildManifest(
    projectId,
    revisionId,
    name,
    source.manifest.workflowKinds,
    documents,
    Object.values(assets),
    now,
    source.manifest.projectId,
    source.manifest.revisionId,
  );
  return {
    manifest: built.manifest,
    project: built.project,
    documents: Object.fromEntries(
      documents.map((document) => [document.documentId, document]),
    ),
    assets,
    thumbnail: source.thumbnail
      ? { ...source.thumbnail, data: new Uint8Array(source.thumbnail.data) }
      : null,
  };
}

/**
 * Rebind a freshly captured editor state to an existing project identity.
 * Saving a later revision must keep ``projectId`` stable while changing only
 * the immutable ``revisionId``; Save As should use ``forkProjectSnapshot``.
 */
export function createProjectRevision(
  previous: ProjectSnapshot,
  captured: ProjectSnapshot,
): ProjectSnapshot {
  const modifiedAt = new Date().toISOString();
  return {
    ...captured,
    manifest: {
      ...captured.manifest,
      projectId: previous.manifest.projectId,
      createdAt: previous.manifest.createdAt,
      modifiedAt,
    },
    project: {
      ...captured.project,
      projectId: previous.manifest.projectId,
      sourceProjectId: previous.project.sourceProjectId,
      sourceRevisionId: previous.project.sourceRevisionId,
    },
  };
}
