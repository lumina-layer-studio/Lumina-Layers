import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { newProject, openProjectFile, recoverProject, useProjectUi } from "../project/controller";
import { projectAdapterRegistry } from "../project/adapters/registry";
import { createProjectSnapshot } from "../project/identity";
import { serializeProject } from "../project/archive";
import * as files from "../project/files";
import * as recovery from "../project/recoveryStore";
import { useProjectSessionStore } from "../stores/projectSessionStore";
import { converterDocumentHistory } from "../stores/converter";
import { useWidgetStore } from "../stores/widgetStore";

const snapshot = () => createProjectSnapshot({
  name: "Opened artwork", workflowKinds: ["converter"],
  documents: [{ documentId: "converter", kind: "converter", schemaVersion: 2,
    payload: {}, inputRevisionIds: [], resourceRefs: [], requiredCapabilities: [] }],
});

beforeEach(() => {
  newProject("converter", "Previous");
  vi.spyOn(projectAdapterRegistry, "restore").mockImplementation(async () => { converterDocumentHistory.reset(); });
  vi.spyOn(files, "listProjectFiles").mockResolvedValue([]);
  vi.spyOn(recovery, "listRecoverySnapshots").mockResolvedValue([]);
});
afterEach(() => { newProject("converter", "End"); vi.restoreAllMocks(); });

it("keeps opening busy until the native file acknowledgement finishes", async () => {
  const next = snapshot();
  const entry: files.ProjectFileEntry = {
    fileEntryId: "saved-file", ...next.manifest, thumbnail: undefined, lastOpenedAt: next.manifest.modifiedAt, pinned: false,
  };
  let acknowledge!: (value: files.ProjectFileEntry) => void;
  const remember = vi.spyOn(files, "rememberProject").mockImplementation(() => new Promise(resolve => { acknowledge = resolve; }));
  const pending = openProjectFile({ bytes: await serializeProject(next) });
  try {
    await vi.waitFor(() => expect(remember).toHaveBeenCalledOnce());
    expect(useProjectSessionStore.getState()).toMatchObject({ status: "opening", activeProjectId: next.project.projectId, dirty: false });
  } finally { acknowledge(entry); await pending; }
  expect(useProjectSessionStore.getState().status).toBe("idle");
  expect(useProjectUi.getState().entry).toBe(entry);
});

it.each(["file", "recovery"] as const)("activates %s with the correct save point and fresh history baseline", async origin => {
  const next = snapshot();
  const entry: files.ProjectFileEntry = {
    fileEntryId: "saved-file", ...next.manifest, thumbnail: undefined, lastOpenedAt: next.manifest.modifiedAt, pinned: false,
  };
  vi.spyOn(files, "rememberProject").mockResolvedValue(entry);
  if (origin === "file") await openProjectFile({ bytes: await serializeProject(next) });
  else await recoverProject({ key: "draft", projectId: next.project.projectId, revisionId: next.project.revisionId,
    savedAt: next.manifest.modifiedAt, snapshot: next });
  expect(useProjectUi.getState()).toMatchObject({ name: next.manifest.name, draftId: next.project.projectId, centerOpen: false, limited: [] });
  expect(useProjectUi.getState().entry).toBe(origin === "file" ? entry : null);
  expect(useProjectSessionStore.getState()).toMatchObject({
    status: "idle", activeProjectId: next.project.projectId, dirty: origin === "recovery",
    savedRevisionId: origin === "file" ? next.project.revisionId : null,
    documentVersions: { converter: converterDocumentHistory.store.getState().position },
  });
  expect(converterDocumentHistory.store.getState()).toMatchObject({ canUndo: false, canRedo: false });
  expect(useWidgetStore.getState().activeTab).toBe("converter");
});

it("keeps the current project identity when adapter restoration fails", async () => {
  const before = useProjectSessionStore.getState();
  vi.mocked(projectAdapterRegistry.restore).mockRejectedValueOnce(new Error("restore failed"));
  await expect(openProjectFile({ bytes: await serializeProject(snapshot()) })).rejects.toThrow("restore failed");
  expect(useProjectSessionStore.getState()).toMatchObject({ activeProjectId: before.activeProjectId, snapshot: before.snapshot, status: "error" });
  expect(useProjectUi.getState().name).toBe("Previous");
});
