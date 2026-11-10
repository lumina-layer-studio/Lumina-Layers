import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("../project/files", async () => ({
  ...await vi.importActual<typeof import("../project/files")>("../project/files"),
  prepareProjectSave: vi.fn().mockResolvedValue(undefined),
  saveProjectFile: vi.fn(), listProjectFiles: vi.fn().mockResolvedValue([]),
}));
vi.mock("../project/thumbnail", () => ({ attachProjectThumbnail: vi.fn() }));
vi.mock("../project/recoveryStore", () => ({
  saveRecoverySnapshot: vi.fn().mockResolvedValue(undefined),
  listRecoverySnapshots: vi.fn().mockResolvedValue([]), removeRecoverySnapshot: vi.fn(),
}));
import { converterDocumentHistory as history, DEFAULT_STATE, useConverterStore as converter } from "../stores/converter";
import { useProjectSessionStore as session } from "../stores/projectSessionStore";
import { newProject, saveCurrentProject, startProjectTracking, useProjectUi } from "../project/controller";
import { projectAdapterRegistry } from "../project/adapters/registry";
import { saveProjectFile, type ProjectFileEntry } from "../project/files";
import { beginDocumentGesture } from "../stores/converter/documentGestures";

let stop: () => void;
beforeEach(() => {
  vi.clearAllMocks();
  converter.setState({ ...DEFAULT_STATE });
  newProject("converter", "Concurrent");
  converter.setState({ imageFile: new File(["art"], "art.png"), target_width_mm: 100, target_height_mm: 100 });
  history.reset();
  vi.spyOn(projectAdapterRegistry, "capture").mockImplementation(async kind => ({ document: {
    documentId: `${kind}.main`, kind, schemaVersion: 2, payload: { width: converter.getState().target_width_mm },
    inputRevisionIds: [], resourceRefs: [], requiredCapabilities: [],
  }, assets: [] }));
  vi.mocked(saveProjectFile).mockImplementation(async snapshot => ({ persisted: true, entry: {
    fileEntryId: "file", name: snapshot.manifest.name, projectId: snapshot.manifest.projectId,
    revisionId: snapshot.manifest.revisionId, workflowKinds: ["converter"], modifiedAt: snapshot.manifest.modifiedAt,
    lastOpenedAt: snapshot.manifest.modifiedAt, pinned: false,
  } }));
  stop = startProjectTracking();
});
afterEach(() => { stop(); vi.restoreAllMocks(); });

it.each([false, true])("keeps the real disk savepoint when editing during a write (Save As: %s)", async saveAs => {
  await saveCurrentProject();
  const originalId = session.getState().activeProjectId;
  converter.getState().setTargetWidthMm(120);
  let savedEntry!: ProjectFileEntry;
  vi.mocked(saveProjectFile).mockImplementationOnce(async snapshot => {
    converter.getState().setTargetWidthMm(140);
    savedEntry = { ...useProjectUi.getState().entry!, fileEntryId: "actual-file", projectId: snapshot.project.projectId, revisionId: snapshot.project.revisionId };
    return { persisted: true, entry: savedEntry };
  });
  expect(await saveCurrentProject(saveAs)).toBe(false); // latest edit still needs saving
  expect(converter.getState().target_width_mm).toBe(140);
  expect(useProjectUi.getState().entry).toEqual(savedEntry);
  expect(session.getState().activeProjectId).toBe(savedEntry.projectId);
  expect(savedEntry.projectId === originalId).toBe(!saveAs);
  expect(session.getState().savedRevisionId).toBe(savedEntry.revisionId);
  expect(session.getState().dirty).toBe(true);
  await history.undo();
  expect(converter.getState().target_width_mm).toBe(120);
  expect(session.getState().dirty).toBe(false);
  await history.undo();
  expect(converter.getState().target_width_mm).toBe(100);
  expect(session.getState().dirty).toBe(true);
});

it("keeps an explicit save reachable inside a long pointer gesture", async () => {
  const finish = beginDocumentGesture();
  try {
    converter.getState().setTargetWidthMm(120);
    await saveCurrentProject();
    converter.getState().setTargetWidthMm(140);
  } finally { finish(); }
  await history.undo();
  expect(converter.getState().target_width_mm).toBe(120);
  expect(session.getState().dirty).toBe(false);
});
