import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it } from "vitest";
import {
  loadRecoverySnapshot,
  removeRecoverySnapshot,
  saveRecoverySnapshot,
} from "../project/recoveryStore";
import { createProjectAsset, createProjectSnapshot } from "../project/identity";

const recoveryProject = async () => {
  const source = await createProjectAsset(
    "source",
    new Uint8Array([7, 8, 9]),
    "image/png",
    "source.png",
  );
  return createProjectSnapshot({
    name: "Recovery draft",
    workflowKinds: ["converter"],
    documents: [
      {
        documentId: "doc",
        kind: "converter",
        schemaVersion: 1,
        payload: { source: null },
        inputRevisionIds: [],
        resourceRefs: ["source"],
        requiredCapabilities: ["converter.v1"],
      },
    ],
    assets: [source],
  });
};

describe("project recovery storage", () => {
  beforeEach(async () => {
    indexedDB.deleteDatabase("lumina-project-recovery-v1");
  });

  it("persists immutable snapshot data and binary assets", async () => {
    const snapshot = await recoveryProject();

    await saveRecoverySnapshot(snapshot);
    const record = await loadRecoverySnapshot(
      snapshot.manifest.projectId,
      snapshot.manifest.revisionId,
    );

    expect(record?.projectId).toBe(snapshot.manifest.projectId);
    expect(record?.snapshot.documents.doc.payload).toEqual({ source: null });
    expect(Array.from(record?.snapshot.assets.source.data ?? [])).toEqual([
      7,
      8,
      9,
    ]);
  });

  it("removes only the addressed recovery point", async () => {
    const first = await recoveryProject();
    const second = await recoveryProject();
    await saveRecoverySnapshot(first);
    await saveRecoverySnapshot(second);

    await removeRecoverySnapshot(first.manifest.projectId, first.manifest.revisionId);

    expect(
      await loadRecoverySnapshot(first.manifest.projectId, first.manifest.revisionId),
    ).toBeNull();
    expect(
      await loadRecoverySnapshot(second.manifest.projectId, second.manifest.revisionId),
    ).not.toBeNull();
  });
});
