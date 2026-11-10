import { describe, expect, it } from "vitest";
import {
  createProjectRevision,
  createProjectSnapshot,
  forkProjectSnapshot,
} from "../project/identity";
import { serializeProject } from "../project/archive";

const document = {
  documentId: "converter.main",
  kind: "converter",
  schemaVersion: 1,
  payload: { recipe: { colorMode: "RYBW" } },
  inputRevisionIds: [],
  resourceRefs: [],
  requiredCapabilities: ["converter.v1"],
};

describe("project revision identity", () => {
  it("keeps formal project identity stable while freezing each export revision", async () => {
    const first = createProjectSnapshot({
      name: "First",
      workflowKinds: ["converter"],
      documents: [document],
    });
    const captured = createProjectSnapshot({
      name: "First",
      workflowKinds: ["converter"],
      documents: [{ ...document, payload: { recipe: { colorMode: "CMYK" } } }],
    });

    const second = createProjectRevision(first, captured);
    const firstBytes = await serializeProject(first);
    const secondBytes = await serializeProject(second);

    expect(second.manifest.projectId).toBe(first.manifest.projectId);
    expect(second.manifest.revisionId).not.toBe(first.manifest.revisionId);
    expect(second.manifest.createdAt).toBe(first.manifest.createdAt);
    expect(secondBytes).not.toEqual(firstBytes);
  });

  it("records Save As lineage without sharing the project identity", () => {
    const source = createProjectSnapshot({
      name: "Source",
      workflowKinds: ["converter"],
      documents: [document],
    });
    const copied = forkProjectSnapshot(source, "Copy");

    expect(copied.manifest.projectId).not.toBe(source.manifest.projectId);
    expect(copied.project.sourceProjectId).toBe(source.manifest.projectId);
    expect(copied.project.sourceRevisionId).toBe(source.manifest.revisionId);
  });
});
