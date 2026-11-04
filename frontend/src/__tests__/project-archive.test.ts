import { unzipSync, zipSync } from "fflate";
import { describe, expect, it } from "vitest";
import {
  createProjectSnapshot,
  createProjectAsset,
  forkProjectSnapshot,
} from "../project/identity";
import {
  parseProject,
  PROJECT_ARCHIVE_LIMITS,
  serializeProject,
} from "../project/archive";
import type { WorkflowDocument } from "../project/types";

const converterDocument: WorkflowDocument = {
  documentId: "doc-converter",
  kind: "converter",
  schemaVersion: 1,
  payload: {
    source: null,
    parameters: { targetWidthMm: 40 },
    colorEdits: [],
    modelSurface: null,
  },
  inputRevisionIds: [],
  resourceRefs: ["source", "source-copy"],
  requiredCapabilities: ["converter.v1"],
};

describe("lumina-project archive", () => {
  it("round-trips editable JSON and binary assets without embedding base64", async () => {
    const source = await createProjectAsset(
      "source",
      new Uint8Array([1, 2, 3]),
      "image/png",
      "source.png",
    );
    const duplicate = await createProjectAsset(
      "source-copy",
      new Uint8Array([1, 2, 3]),
      "application/octet-stream",
      "copy.bin",
    );
    const snapshot = createProjectSnapshot({
      name: "Draft",
      workflowKinds: ["converter"],
      documents: [converterDocument],
      assets: [source, duplicate],
    });

    const encoded = await serializeProject(snapshot);
    const members = unzipSync(encoded);
    const assetMembers = Object.keys(members).filter((name) =>
      name.startsWith("assets/"),
    );

    expect(assetMembers).toHaveLength(1);
    expect(Object.keys(members)).toContain("documents/doc-converter.json");

    const restored = await parseProject(encoded);
    expect(restored.manifest.projectId).toBe(snapshot.manifest.projectId);
    expect(restored.manifest.revisionId).toBe(snapshot.manifest.revisionId);
    expect(restored.assets.source.data).toEqual(new Uint8Array([1, 2, 3]));
    expect(restored.documents["doc-converter"].resourceRefs).toEqual([
      "source",
      "source-copy",
    ]);
  });

  it("creates a new project identity on Save As while retaining source revision", () => {
    const snapshot = createProjectSnapshot({
      name: "Original",
      workflowKinds: ["converter"],
      documents: [{ ...converterDocument, resourceRefs: [] }],
    });

    const fork = forkProjectSnapshot(snapshot, "Copy");

    expect(fork.manifest.projectId).not.toBe(snapshot.manifest.projectId);
    expect(fork.manifest.revisionId).not.toBe(snapshot.manifest.revisionId);
    expect(fork.project.sourceProjectId).toBe(snapshot.manifest.projectId);
    expect(fork.project.sourceRevisionId).toBe(snapshot.manifest.revisionId);
  });

  it("rejects unsafe member paths before returning project data", async () => {
    const unsafe = zipSync({ "../evil.json": new Uint8Array([1]) });

    await expect(parseProject(unsafe)).rejects.toThrow(/ZIP|project/i);
  });

  it("rejects a tampered asset and malformed manifest as project errors", async () => {
    const snapshot = createProjectSnapshot({
      name: "Tamper check",
      workflowKinds: ["converter"],
      documents: [{ ...converterDocument, resourceRefs: [] }],
    });
    const encoded = await serializeProject(snapshot);
    const members = unzipSync(encoded);
    members["manifest.json"] = new TextEncoder().encode(
      JSON.stringify({ format: "lumina-project" }),
    );
    await expect(parseProject(zipSync(members))).rejects.toThrow(/schema|metadata|project|manifest/i);

    const source = await createProjectAsset(
      "source",
      new Uint8Array([4, 5, 6]),
      "image/png",
      "source.png",
    );
    const withAsset = createProjectSnapshot({
      name: "Asset tamper",
      workflowKinds: ["converter"],
      documents: [{ ...converterDocument, resourceRefs: ["source"] }],
      assets: [source],
    });
    const assetMembers = unzipSync(await serializeProject(withAsset));
    assetMembers[source.path] = new Uint8Array([9, 9, 9]);
    await expect(parseProject(zipSync(assetMembers))).rejects.toThrow(/checksum|size/i);
  });

  it("rejects thumbnails over the decoded pixel budget", async () => {
    const width = 4097;
    const height = 4097;
    const pngHeader = new Uint8Array([
      0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
      0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
      (width >>> 24) & 0xff, (width >>> 16) & 0xff, (width >>> 8) & 0xff, width & 0xff,
      (height >>> 24) & 0xff, (height >>> 16) & 0xff, (height >>> 8) & 0xff, height & 0xff,
      0x08, 0x06, 0x00, 0x00, 0x00,
    ]);
    const snapshot = createProjectSnapshot({
      name: "Large cover",
      workflowKinds: ["converter"],
      documents: [{ ...converterDocument, resourceRefs: [] }],
    });
    const thumbnail = await createProjectAsset(
      "thumbnail",
      pngHeader,
      "image/png",
      "thumbnail.png",
      "resource",
    );
    snapshot.thumbnail = {
      ...thumbnail,
      path: "preview/thumbnail.png",
    };
    snapshot.manifest.thumbnail = {
      path: "preview/thumbnail.png",
      sha256: thumbnail.sha256,
      byteSize: thumbnail.byteSize,
      mediaType: "image/png",
    };

    await expect(serializeProject(snapshot)).rejects.toThrow(/pixel/i);
  });

  it("rejects an oversized ZIP member from the central directory before inflate", async () => {
    const encoded = zipSync({
      "manifest.json": new TextEncoder().encode("{}"),
    });
    const centralOffset = encoded.findIndex(
      (_value, index) =>
        encoded[index] === 0x50 &&
        encoded[index + 1] === 0x4b &&
        encoded[index + 2] === 0x01 &&
        encoded[index + 3] === 0x02,
    );
    expect(centralOffset).toBeGreaterThanOrEqual(0);
    new DataView(encoded.buffer, encoded.byteOffset, encoded.byteLength).setUint32(
      centralOffset + 24,
      PROJECT_ARCHIVE_LIMITS.maxMemberBytes + 1,
      true,
    );

    await expect(parseProject(encoded)).rejects.toThrow(/member|size/i);
  });
});
