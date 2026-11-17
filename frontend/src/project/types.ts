export const PROJECT_FORMAT = "lumina-project" as const;
export const PROJECT_CONTAINER_VERSION = 1 as const;
export const PROJECT_SCHEMA_VERSION = 1 as const;

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface WorkflowDocument {
  documentId: string;
  kind: string;
  schemaVersion: number;
  payload: JsonObject;
  inputRevisionIds: string[];
  resourceRefs: string[];
  requiredCapabilities: string[];
}

export interface ProjectDocumentDescriptor {
  documentId: string;
  kind: string;
  schemaVersion: number;
  path: string;
}

export type ProjectAssetRole = "asset" | "resource";

export interface ProjectResourceDescriptor {
  assetId: string;
  sha256: string;
  path: string;
  byteSize: number;
  mediaType: string;
  filename?: string;
  role: ProjectAssetRole;
}

export interface ProjectManifest {
  format: typeof PROJECT_FORMAT;
  containerVersion: typeof PROJECT_CONTAINER_VERSION;
  schemaVersion: typeof PROJECT_SCHEMA_VERSION;
  projectId: string;
  revisionId: string;
  name: string;
  workflowKinds: string[];
  createdAt: string;
  modifiedAt: string;
  entryDocumentId: string;
  documents: ProjectDocumentDescriptor[];
  resources: ProjectResourceDescriptor[];
  thumbnail: {
    path: "preview/thumbnail.png";
    sha256: string;
    byteSize: number;
    mediaType: string;
  } | null;
  requiredCapabilities: string[];
  degradedFields: string[];
  warnings: string[];
}

export interface ProjectMetadata {
  projectId: string;
  revisionId: string;
  name: string;
  workflowKinds: string[];
  entryDocumentId: string;
  sourceProjectId: string | null;
  sourceRevisionId: string | null;
  documentIds: string[];
  resourceRefs: string[];
}

export interface ProjectAsset extends ProjectResourceDescriptor {
  data: Uint8Array;
}

export interface ProjectSnapshot {
  manifest: ProjectManifest;
  project: ProjectMetadata;
  documents: Record<string, WorkflowDocument>;
  assets: Record<string, ProjectAsset>;
  thumbnail: ProjectAsset | null;
}
