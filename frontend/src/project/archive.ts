import { unzipSync, zipSync } from "fflate";
import { sha256Hex } from "./hash";
import {
  PROJECT_CONTAINER_VERSION,
  PROJECT_FORMAT,
  PROJECT_SCHEMA_VERSION,
  type JsonValue,
  type ProjectAsset,
  type ProjectManifest,
  type ProjectMetadata,
  type ProjectSnapshot,
  type WorkflowDocument,
} from "./types";

export const PROJECT_ARCHIVE_LIMITS = {
  maxArchiveBytes: 512 * 1024 * 1024,
  maxEntries: 4096,
  maxMemberBytes: 256 * 1024 * 1024,
  maxTotalUncompressedBytes: 1024 * 1024 * 1024,
  maxThumbnailPixels: 16 * 1024 * 1024,
} as const;

export class ProjectArchiveError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProjectArchiveError";
  }
}

const FORBIDDEN_RUNTIME_KEYS = new Set([
  "sessionId",
  "session_id",
  "fileId",
  "file_id",
  "previewUrl",
  "preview_url",
  "modelUrl",
  "model_url",
  "downloadUrl",
  "download_url",
  "localPath",
  "local_path",
  "accessToken",
  "access_token",
  "command",
  "commands",
  "commandLine",
  "executable",
  "download",
  "downloadUrl",
  "externalUrl",
  "script",
]);

const SVG_UNSAFE_PATTERN =
  /<\s*script\b|\bon[a-z0-9_-]+\s*=|(?:href|src|action)\s*=\s*["'](?:https?:|file:|javascript:|\/\/)|@import\s+url\(/i;

function sortedJson(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map(sortedJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, sortedJson(item)]),
    );
  }
  if (typeof value === "number" && !Number.isFinite(value)) {
    throw new ProjectArchiveError("Project JSON contains a non-finite number");
  }
  return value;
}

function jsonBytes(value: unknown): Uint8Array {
  return new TextEncoder().encode(
    JSON.stringify(sortedJson(value as JsonValue)),
  );
}

function readJson(bytes: Uint8Array, member: string): Record<string, unknown> {
  try {
    const value = JSON.parse(new TextDecoder().decode(bytes)) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("not an object");
    }
    return value as Record<string, unknown>;
  } catch {
    throw new ProjectArchiveError("Invalid project JSON: " + member);
  }
}

function validateJsonValue(
  value: unknown,
  depth = 0,
  ancestors = new WeakSet<object>(),
): void {
  if (depth > 32) throw new ProjectArchiveError("Project JSON is too deep");
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new ProjectArchiveError("Project JSON contains a non-finite number");
    }
    return;
  }
  if (Array.isArray(value)) {
    if (ancestors.has(value)) {
      throw new ProjectArchiveError("Project JSON contains a cycle");
    }
    ancestors.add(value);
    value.forEach((item) => validateJsonValue(item, depth + 1, ancestors));
    ancestors.delete(value);
    return;
  }
  if (typeof value === "object") {
    const objectValue = value as object;
    if (ancestors.has(objectValue)) {
      throw new ProjectArchiveError("Project JSON contains a cycle");
    }
    const prototype = Object.getPrototypeOf(objectValue);
    if (prototype !== Object.prototype && prototype !== null) {
      throw new ProjectArchiveError("Project JSON contains a non-plain object");
    }
    ancestors.add(objectValue);
    for (const [key, item] of Object.entries(value)) {
      if (FORBIDDEN_RUNTIME_KEYS.has(key)) {
        throw new ProjectArchiveError(
          "Runtime-only field is not project data: " + key,
        );
      }
      validateJsonValue(item, depth + 1, ancestors);
    }
    ancestors.delete(objectValue);
    return;
  }
  throw new ProjectArchiveError("Project JSON contains an unsupported value");
}

function normalizedMemberName(name: string): string {
  if (
    !name ||
    name.includes("\\") ||
    name.includes("\0") ||
    name.startsWith("/") ||
    /^[A-Za-z]:/.test(name)
  ) {
    throw new ProjectArchiveError("Unsafe project ZIP member path");
  }
  const parts = name.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new ProjectArchiveError("Unsafe project ZIP member path");
  }
  const normalized = parts.join("/");
  if (normalized !== name) {
    throw new ProjectArchiveError("Non-canonical project ZIP member path");
  }
  return normalized.normalize("NFC").toLowerCase();
}

/**
 * Inspect ZIP central-directory metadata before fflate allocates output
 * buffers.  The decompressor is intentionally kept behind this gate so a
 * small compressed package cannot claim gigabytes of uncompressed data.
 */
function preflightArchiveMembers(data: Uint8Array): void {
  if (data.byteLength < 22) {
    throw new ProjectArchiveError("Invalid project ZIP");
  }
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const minimumEnd = Math.max(0, data.byteLength - 22 - 0xffff);
  let endOffset = -1;
  for (let offset = data.byteLength - 22; offset >= minimumEnd; offset -= 1) {
    if (
      view.getUint32(offset, true) === 0x06054b50 &&
      offset + 22 <= data.byteLength
    ) {
      endOffset = offset;
      break;
    }
  }
  if (endOffset < 0) throw new ProjectArchiveError("Invalid project ZIP");

  const diskNumber = view.getUint16(endOffset + 4, true);
  const centralDisk = view.getUint16(endOffset + 6, true);
  const entriesOnDisk = view.getUint16(endOffset + 8, true);
  const entryCount = view.getUint16(endOffset + 10, true);
  const centralSize = view.getUint32(endOffset + 12, true);
  const centralOffset = view.getUint32(endOffset + 16, true);
  if (diskNumber !== 0 || centralDisk !== 0 || entriesOnDisk !== entryCount) {
    throw new ProjectArchiveError("Multi-disk project ZIPs are not supported");
  }
  if (
    entryCount === 0xffff ||
    centralSize === 0xffffffff ||
    centralOffset === 0xffffffff
  ) {
    throw new ProjectArchiveError("ZIP64 project archives are not supported");
  }
  if (entryCount > PROJECT_ARCHIVE_LIMITS.maxEntries) {
    throw new ProjectArchiveError("Project ZIP has too many entries");
  }
  const centralEnd = centralOffset + centralSize;
  if (
    centralOffset < 0 ||
    centralEnd > endOffset ||
    centralEnd > data.byteLength
  ) {
    throw new ProjectArchiveError("Invalid project ZIP central directory");
  }

  const normalized = new Set<string>();
  let cursor = centralOffset;
  let totalBytes = 0;
  for (let index = 0; index < entryCount; index += 1) {
    if (cursor + 46 > centralEnd || view.getUint32(cursor, true) !== 0x02014b50) {
      throw new ProjectArchiveError("Invalid project ZIP central directory");
    }
    const flags = view.getUint16(cursor + 8, true);
    const compressedSize = view.getUint32(cursor + 20, true);
    const uncompressedSize = view.getUint32(cursor + 24, true);
    const filenameLength = view.getUint16(cursor + 28, true);
    const extraLength = view.getUint16(cursor + 30, true);
    const commentLength = view.getUint16(cursor + 32, true);
    const localHeaderOffset = view.getUint32(cursor + 42, true);
    const recordEnd = cursor + 46 + filenameLength + extraLength + commentLength;
    if (recordEnd > centralEnd || localHeaderOffset >= data.byteLength) {
      throw new ProjectArchiveError("Invalid project ZIP member metadata");
    }
    if (flags & 0x0001) {
      throw new ProjectArchiveError("Encrypted project ZIP members are not supported");
    }
    if (uncompressedSize === 0xffffffff || compressedSize === 0xffffffff) {
      throw new ProjectArchiveError("ZIP64 project members are not supported");
    }
    let name: string;
    try {
      name = new TextDecoder("utf-8", { fatal: true }).decode(
        data.subarray(cursor + 46, cursor + 46 + filenameLength),
      );
    } catch {
      throw new ProjectArchiveError("Project ZIP member name is not valid UTF-8");
    }
    const normalizedName = normalizedMemberName(name);
    if (normalized.has(normalizedName)) {
      throw new ProjectArchiveError("Project ZIP has duplicate normalized members");
    }
    normalized.add(normalizedName);
    if (uncompressedSize > PROJECT_ARCHIVE_LIMITS.maxMemberBytes) {
      throw new ProjectArchiveError("Project ZIP member exceeds size limit");
    }
    totalBytes += uncompressedSize;
    if (totalBytes > PROJECT_ARCHIVE_LIMITS.maxTotalUncompressedBytes) {
      throw new ProjectArchiveError("Project ZIP exceeds total size limit");
    }
    cursor = recordEnd;
  }
  if (cursor !== centralEnd) {
    throw new ProjectArchiveError("Invalid project ZIP central directory");
  }
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isPlainRecord(value)) {
    throw new ProjectArchiveError(`${label} must be an object`);
  }
  return value;
}

function requireString(value: unknown, label: string, nonEmpty = true): string {
  if (typeof value !== "string" || (nonEmpty && value.length === 0)) {
    throw new ProjectArchiveError(`${label} must be a string`);
  }
  return value;
}

function requireStringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) {
    throw new ProjectArchiveError(`${label} must be an array`);
  }
  for (const item of value) requireString(item, label + "[]");
  return value;
}

function requireInteger(value: unknown, label: string, minimum = 0): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < minimum
  ) {
    throw new ProjectArchiveError(`${label} must be an integer`);
  }
  return value;
}

function requireSha256(value: unknown, label: string): string {
  const sha256 = requireString(value, label).toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(sha256)) {
    throw new ProjectArchiveError(`${label} must be a SHA-256 hex digest`);
  }
  return sha256;
}

function requireSafePath(value: unknown, label: string): string {
  const path = requireString(value, label);
  normalizedMemberName(path);
  return path;
}

function requireIdentifier(value: unknown, label: string): string {
  const identifier = requireString(value, label);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(identifier)) {
    throw new ProjectArchiveError(`${label} must be a bounded project identifier`);
  }
  return identifier;
}

function assertDocumentDescriptor(
  value: unknown,
  label: string,
): asserts value is ProjectManifest["documents"][number] {
  const descriptor = requireRecord(value, label);
  requireIdentifier(descriptor.documentId, label + ".documentId");
  requireString(descriptor.kind, label + ".kind");
  requireInteger(descriptor.schemaVersion, label + ".schemaVersion", 1);
  requireSafePath(descriptor.path, label + ".path");
}

function assertResourceDescriptor(
  value: unknown,
  label: string,
): asserts value is ProjectManifest["resources"][number] {
  const descriptor = requireRecord(value, label);
  requireIdentifier(descriptor.assetId, label + ".assetId");
  requireSha256(descriptor.sha256, label + ".sha256");
  requireSafePath(descriptor.path, label + ".path");
  requireInteger(descriptor.byteSize, label + ".byteSize");
  requireString(descriptor.mediaType, label + ".mediaType");
  if (descriptor.filename !== undefined) {
    const filename = requireString(descriptor.filename, label + ".filename");
    if (filename.includes("/") || filename.includes("\\") || filename.includes("\0")) {
      throw new ProjectArchiveError(`${label}.filename must be a plain filename`);
    }
  }
  if (descriptor.role !== "asset" && descriptor.role !== "resource") {
    throw new ProjectArchiveError(`${label}.role is invalid`);
  }
}

function assertManifest(value: unknown): asserts value is ProjectManifest {
  const manifest = requireRecord(value, "manifest");
  requireString(manifest.format, "manifest.format");
  requireInteger(manifest.containerVersion, "manifest.containerVersion", 1);
  requireInteger(manifest.schemaVersion, "manifest.schemaVersion", 1);
  requireIdentifier(manifest.projectId, "manifest.projectId");
  requireIdentifier(manifest.revisionId, "manifest.revisionId");
  requireString(manifest.name, "manifest.name");
  requireStringArray(manifest.workflowKinds, "manifest.workflowKinds");
  requireString(manifest.createdAt, "manifest.createdAt");
  requireString(manifest.modifiedAt, "manifest.modifiedAt");
  requireIdentifier(manifest.entryDocumentId, "manifest.entryDocumentId");
  if (!Array.isArray(manifest.documents)) {
    throw new ProjectArchiveError("manifest.documents must be an array");
  }
  manifest.documents.forEach((document, index) =>
    assertDocumentDescriptor(document, `manifest.documents[${index}]`),
  );
  if (!Array.isArray(manifest.resources)) {
    throw new ProjectArchiveError("manifest.resources must be an array");
  }
  manifest.resources.forEach((resource, index) =>
    assertResourceDescriptor(resource, `manifest.resources[${index}]`),
  );
  if (manifest.thumbnail !== null) {
    const thumbnail = requireRecord(manifest.thumbnail, "manifest.thumbnail");
    if (thumbnail.path !== "preview/thumbnail.png") {
      throw new ProjectArchiveError("manifest.thumbnail.path is not canonical");
    }
    requireSha256(thumbnail.sha256, "manifest.thumbnail.sha256");
    requireInteger(thumbnail.byteSize, "manifest.thumbnail.byteSize");
    requireString(thumbnail.mediaType, "manifest.thumbnail.mediaType");
  }
  requireStringArray(manifest.requiredCapabilities, "manifest.requiredCapabilities");
  requireStringArray(manifest.degradedFields, "manifest.degradedFields");
  requireStringArray(manifest.warnings, "manifest.warnings");
}

function assertProjectMetadata(value: unknown): asserts value is ProjectMetadata {
  const project = requireRecord(value, "project");
  requireIdentifier(project.projectId, "project.projectId");
  requireIdentifier(project.revisionId, "project.revisionId");
  requireString(project.name, "project.name");
  requireStringArray(project.workflowKinds, "project.workflowKinds");
  requireIdentifier(project.entryDocumentId, "project.entryDocumentId");
  if (project.sourceProjectId !== null && project.sourceProjectId !== undefined) {
    requireIdentifier(project.sourceProjectId, "project.sourceProjectId");
  }
  if (project.sourceRevisionId !== null && project.sourceRevisionId !== undefined) {
    requireIdentifier(project.sourceRevisionId, "project.sourceRevisionId");
  }
  requireStringArray(project.documentIds, "project.documentIds");
  requireStringArray(project.resourceRefs, "project.resourceRefs");
}

function assertWorkflowDocument(value: unknown, label: string): asserts value is WorkflowDocument {
  const document = requireRecord(value, label);
  requireIdentifier(document.documentId, label + ".documentId");
  requireString(document.kind, label + ".kind");
  requireInteger(document.schemaVersion, label + ".schemaVersion", 1);
  requireRecord(document.payload, label + ".payload");
  requireStringArray(document.inputRevisionIds, label + ".inputRevisionIds");
  requireStringArray(document.resourceRefs, label + ".resourceRefs");
  requireStringArray(document.requiredCapabilities, label + ".requiredCapabilities");
}

function expectedAssetPath(
  asset: Pick<ProjectManifest["resources"][number], "role" | "sha256">,
): string {
  return `${asset.role === "resource" ? "resources" : "assets"}/${asset.sha256}`;
}

function sameStringArray(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function sameResourceDescriptor(
  descriptor: ProjectManifest["resources"][number],
  asset: ProjectAsset,
): boolean {
  return (
    descriptor.assetId === asset.assetId &&
    descriptor.sha256 === asset.sha256 &&
    descriptor.path === asset.path &&
    descriptor.byteSize === asset.byteSize &&
    descriptor.mediaType === asset.mediaType &&
    descriptor.role === asset.role &&
    descriptor.filename === asset.filename
  );
}

function validateAssetContent(asset: ProjectAsset): void {
  if (
    asset.mediaType.toLowerCase() !== "image/svg+xml" &&
    !(asset.filename?.toLowerCase().endsWith(".svg") ?? false)
  ) {
    return;
  }
  let source: string;
  try {
    source = new TextDecoder("utf-8", { fatal: true }).decode(asset.data);
  } catch {
    throw new ProjectArchiveError("SVG asset is not valid UTF-8");
  }
  if (SVG_UNSAFE_PATTERN.test(source)) {
    throw new ProjectArchiveError(
      "SVG assets must not contain scripts or external references",
    );
  }
}

function validateThumbnailPng(data: Uint8Array): void {
  const signature = new Uint8Array([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  ]);
  if (
    data.byteLength < 24 ||
    !signature.every((value, index) => data[index] === value) ||
    new TextDecoder().decode(data.subarray(12, 16)) !== "IHDR"
  ) {
    throw new ProjectArchiveError("Project thumbnail is not a valid PNG");
  }
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const width = view.getUint32(16);
  const height = view.getUint32(20);
  if (width === 0 || height === 0) {
    throw new ProjectArchiveError("Project thumbnail dimensions are invalid");
  }
  if (width * height > PROJECT_ARCHIVE_LIMITS.maxThumbnailPixels) {
    throw new ProjectArchiveError(
      "Project thumbnail exceeds decoded pixel limit",
    );
  }
}

async function verifySnapshotChecksums(snapshot: ProjectSnapshot): Promise<void> {
  const assets = Object.values(snapshot.assets);
  for (const asset of assets) {
    const hash = await sha256Hex(
      asset.data.buffer.slice(asset.data.byteOffset, asset.data.byteOffset + asset.data.byteLength),
    );
    if (hash !== asset.sha256) {
      throw new ProjectArchiveError("Asset checksum mismatch: " + asset.assetId);
    }
  }
  if (snapshot.thumbnail) {
    const hash = await sha256Hex(
      snapshot.thumbnail.data.buffer.slice(
        snapshot.thumbnail.data.byteOffset,
        snapshot.thumbnail.data.byteOffset + snapshot.thumbnail.data.byteLength,
      ),
    );
    if (hash !== snapshot.thumbnail.sha256) {
      throw new ProjectArchiveError("Project thumbnail checksum mismatch");
    }
  }
}

function validateArchiveMembers(entries: Record<string, Uint8Array>): void {
  const names = Object.keys(entries);
  if (names.length > PROJECT_ARCHIVE_LIMITS.maxEntries) {
    throw new ProjectArchiveError("Project ZIP has too many entries");
  }
  const normalized = new Set<string>();
  let totalBytes = 0;
  for (const name of names) {
    const key = normalizedMemberName(name);
    if (normalized.has(key)) {
      throw new ProjectArchiveError("Project ZIP has duplicate normalized members");
    }
    normalized.add(key);
    const data = entries[name];
    if (data.byteLength > PROJECT_ARCHIVE_LIMITS.maxMemberBytes) {
      throw new ProjectArchiveError("Project ZIP member exceeds size limit");
    }
    totalBytes += data.byteLength;
  }
  if (totalBytes > PROJECT_ARCHIVE_LIMITS.maxTotalUncompressedBytes) {
    throw new ProjectArchiveError("Project ZIP exceeds total size limit");
  }
}

export async function serializeProject(
  snapshot: ProjectSnapshot,
): Promise<Uint8Array> {
  validateSnapshot(snapshot);
  await verifySnapshotChecksums(snapshot);
  const entries: Record<string, Uint8Array> = {
    "manifest.json": jsonBytes(snapshot.manifest),
    "project.json": jsonBytes(snapshot.project),
  };
  for (const document of Object.values(snapshot.documents)) {
    entries["documents/" + document.documentId + ".json"] = jsonBytes(document);
  }
  const written = new Set<string>();
  for (const asset of Object.values(snapshot.assets)) {
    if (!written.has(asset.path)) {
      entries[asset.path] = asset.data;
      written.add(asset.path);
    }
  }
  if (snapshot.thumbnail) {
    entries["preview/thumbnail.png"] = snapshot.thumbnail.data;
  }
  const zipped = zipSync(entries, { level: 6 });
  if (zipped.byteLength > PROJECT_ARCHIVE_LIMITS.maxArchiveBytes) {
    throw new ProjectArchiveError("Project ZIP exceeds size limit");
  }
  return zipped;
}

export async function parseProject(data: Uint8Array): Promise<ProjectSnapshot> {
  if (data.byteLength > PROJECT_ARCHIVE_LIMITS.maxArchiveBytes) {
    throw new ProjectArchiveError("Project ZIP exceeds size limit");
  }
  preflightArchiveMembers(data);
  let entries: Record<string, Uint8Array>;
  try {
    entries = unzipSync(data);
  } catch {
    throw new ProjectArchiveError("Invalid project ZIP");
  }
  validateArchiveMembers(entries);
  if (!entries["manifest.json"] || !entries["project.json"]) {
    throw new ProjectArchiveError("Project ZIP is missing metadata");
  }
  const manifest = readJson(
    entries["manifest.json"],
    "manifest.json",
  ) as unknown as ProjectManifest;
  const project = readJson(
    entries["project.json"],
    "project.json",
  );
  validateJsonValue(manifest);
  validateJsonValue(project);
  assertManifest(manifest);
  assertProjectMetadata(project);
  if (
    manifest.format !== PROJECT_FORMAT ||
    manifest.containerVersion !== PROJECT_CONTAINER_VERSION ||
    manifest.schemaVersion !== PROJECT_SCHEMA_VERSION
  ) {
    throw new ProjectArchiveError("Unsupported lumina-project schema");
  }
  if (
    project.projectId !== manifest.projectId ||
    project.revisionId !== manifest.revisionId
  ) {
    throw new ProjectArchiveError("Project identities disagree");
  }
  const documents: Record<string, WorkflowDocument> = {};
  for (const descriptor of manifest.documents) {
    const expectedPath = "documents/" + descriptor.documentId + ".json";
    if (descriptor.path !== expectedPath || !entries[descriptor.path]) {
      throw new ProjectArchiveError("Document path is not canonical");
    }
    const document = readJson(
      entries[descriptor.path],
      descriptor.path,
    );
    validateJsonValue(document);
    assertWorkflowDocument(document, descriptor.path);
    if (
      document.documentId !== descriptor.documentId ||
      document.kind !== descriptor.kind ||
      document.schemaVersion !== descriptor.schemaVersion
    ) {
      throw new ProjectArchiveError("Document descriptor does not match payload");
    }
    if (documents[document.documentId]) {
      throw new ProjectArchiveError("Duplicate workflow document");
    }
    documents[document.documentId] = document;
  }

  const assets: Record<string, ProjectAsset> = {};
  for (const descriptor of manifest.resources) {
    if (assets[descriptor.assetId]) {
      throw new ProjectArchiveError("Duplicate project resource");
    }
    if (descriptor.path !== expectedAssetPath(descriptor)) {
      throw new ProjectArchiveError("Resource path is not canonical");
    }
    const bytes = entries[descriptor.path];
    if (!bytes) {
      throw new ProjectArchiveError("Missing resource: " + descriptor.assetId);
    }
    if (bytes.byteLength !== descriptor.byteSize) {
      throw new ProjectArchiveError(
        "Resource size mismatch: " + descriptor.assetId,
      );
    }
    const hash = await sha256Hex(
      bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    );
    if (hash !== descriptor.sha256) {
      throw new ProjectArchiveError(
        "Resource checksum mismatch: " + descriptor.assetId,
      );
    }
    assets[descriptor.assetId] = { ...descriptor, data: bytes };
  }
  const thumbnail = manifest.thumbnail
    ? {
        assetId: "thumbnail",
        sha256: manifest.thumbnail.sha256,
        path: manifest.thumbnail.path,
        byteSize: manifest.thumbnail.byteSize,
        mediaType: manifest.thumbnail.mediaType,
        role: "resource" as const,
        data: entries[manifest.thumbnail.path],
      }
    : null;
  if (thumbnail && !thumbnail.data) {
    throw new ProjectArchiveError("Project thumbnail is missing");
  }

  const snapshot: ProjectSnapshot = {
    manifest,
    project,
    documents,
    assets,
    thumbnail,
  };
  validateSnapshot(snapshot);
  await verifySnapshotChecksums(snapshot);
  return snapshot;
}

export function validateSnapshot(snapshot: ProjectSnapshot): void {
  if (!snapshot || typeof snapshot !== "object") {
    throw new ProjectArchiveError("Project snapshot must be an object");
  }
  validateJsonValue(snapshot.manifest);
  validateJsonValue(snapshot.project);
  assertManifest(snapshot.manifest);
  assertProjectMetadata(snapshot.project);
  if (
    snapshot.manifest.format !== PROJECT_FORMAT ||
    snapshot.manifest.containerVersion !== PROJECT_CONTAINER_VERSION ||
    snapshot.manifest.schemaVersion !== PROJECT_SCHEMA_VERSION
  ) {
    throw new ProjectArchiveError("Unsupported lumina-project schema");
  }
  if (snapshot.manifest.documents.length === 0) {
    throw new ProjectArchiveError("Project needs a workflow document");
  }

  if (!isPlainRecord(snapshot.documents) || !isPlainRecord(snapshot.assets)) {
    throw new ProjectArchiveError("Project document/resource maps are invalid");
  }

  if (
    snapshot.project.projectId !== snapshot.manifest.projectId ||
    snapshot.project.revisionId !== snapshot.manifest.revisionId ||
    snapshot.project.name !== snapshot.manifest.name ||
    snapshot.project.entryDocumentId !== snapshot.manifest.entryDocumentId ||
    !sameStringArray(snapshot.project.workflowKinds, snapshot.manifest.workflowKinds)
  ) {
    throw new ProjectArchiveError("Project metadata disagrees with manifest");
  }

  const manifestDocumentIds = new Set<string>();
  for (const descriptor of snapshot.manifest.documents) {
    if (manifestDocumentIds.has(descriptor.documentId)) {
      throw new ProjectArchiveError("Duplicate workflow document descriptor");
    }
    manifestDocumentIds.add(descriptor.documentId);
    const expectedPath = "documents/" + descriptor.documentId + ".json";
    if (descriptor.path !== expectedPath) {
      throw new ProjectArchiveError("Document path is not canonical");
    }
    const document = snapshot.documents[descriptor.documentId];
    if (!document) {
      throw new ProjectArchiveError("Missing workflow document: " + descriptor.documentId);
    }
    assertWorkflowDocument(document, "workflow document");
    validateJsonValue(document);
    if (
      document.documentId !== descriptor.documentId ||
      document.kind !== descriptor.kind ||
      document.schemaVersion !== descriptor.schemaVersion
    ) {
      throw new ProjectArchiveError("Document descriptor does not match payload");
    }
  }
  if (snapshot.manifest.entryDocumentId && !manifestDocumentIds.has(snapshot.manifest.entryDocumentId)) {
    throw new ProjectArchiveError("Manifest entry document is missing");
  }
  const documentIds = Object.keys(snapshot.documents);
  if (
    documentIds.length !== manifestDocumentIds.size ||
    documentIds.some((documentId) => !manifestDocumentIds.has(documentId)) ||
    !sameStringArray(snapshot.project.documentIds, [...manifestDocumentIds])
  ) {
    throw new ProjectArchiveError("Project document index is inconsistent");
  }

  const resourceIds = new Set<string>();
  for (const descriptor of snapshot.manifest.resources) {
    if (resourceIds.has(descriptor.assetId)) {
      throw new ProjectArchiveError("Duplicate project resource descriptor");
    }
    resourceIds.add(descriptor.assetId);
    if (descriptor.path !== expectedAssetPath(descriptor)) {
      throw new ProjectArchiveError("Resource path is not canonical");
    }
    const asset = snapshot.assets[descriptor.assetId];
    if (!asset || !sameResourceDescriptor(descriptor, asset)) {
      throw new ProjectArchiveError("Resource descriptor does not match asset");
    }
  }
  const assetIds = Object.keys(snapshot.assets);
  if (
    assetIds.length !== resourceIds.size ||
    assetIds.some((assetId) => !resourceIds.has(assetId)) ||
    !sameStringArray(snapshot.project.resourceRefs, [...resourceIds])
  ) {
    throw new ProjectArchiveError("Project resource index is inconsistent");
  }
  for (const asset of Object.values(snapshot.assets)) {
    if (!(asset.data instanceof Uint8Array)) {
      throw new ProjectArchiveError("Asset bytes are invalid: " + asset.assetId);
    }
    assertResourceDescriptor(asset, "project asset");
    validateAssetContent(asset);
    if (asset.data.byteLength !== asset.byteSize) {
      throw new ProjectArchiveError("Asset size mismatch: " + asset.assetId);
    }
  }

  for (const document of Object.values(snapshot.documents)) {
    for (const assetId of document.resourceRefs) {
      if (!snapshot.assets[assetId]) {
        throw new ProjectArchiveError(
          "Document references missing asset: " + assetId,
        );
      }
    }
  }

  if (snapshot.manifest.thumbnail === null) {
    if (snapshot.thumbnail !== null) {
      throw new ProjectArchiveError("Unexpected project thumbnail");
    }
  } else {
    const descriptor = snapshot.manifest.thumbnail;
    const thumbnail = snapshot.thumbnail;
    if (!thumbnail) {
      throw new ProjectArchiveError("Project thumbnail is missing");
    }
    if (
      thumbnail.assetId !== "thumbnail" ||
      thumbnail.path !== descriptor.path ||
      thumbnail.sha256 !== descriptor.sha256 ||
      thumbnail.byteSize !== descriptor.byteSize ||
      thumbnail.mediaType !== descriptor.mediaType ||
      thumbnail.role !== "resource" ||
      !(thumbnail.data instanceof Uint8Array) ||
      thumbnail.data.byteLength !== thumbnail.byteSize
    ) {
      throw new ProjectArchiveError("Project thumbnail descriptor is invalid");
    }
    if (thumbnail.mediaType.toLowerCase() !== "image/png") {
      throw new ProjectArchiveError("Project thumbnail must use image/png");
    }
    validateThumbnailPng(thumbnail.data);
  }
}
