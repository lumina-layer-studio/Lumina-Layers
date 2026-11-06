import { expect, it } from "vitest";
import { availableRecoveries, suggestedProjectName } from "../project/recentProjects";
import { projectErrorMessage } from "../project/errors";
import { createProjectSnapshot } from "../project/identity";
import type { ProjectFileEntry } from "../project/files";
import type { RecoveryRecord } from "../project/recoveryStore";
import { translations } from "../i18n/translations";

function recovery(projectId: string, revisionId: string, time: string): RecoveryRecord {
  const snapshot = createProjectSnapshot({ name: projectId, workflowKinds: ["converter"], documents: [{ documentId: "converter.main", kind: "converter", schemaVersion: 2, payload: {}, resourceRefs: [], inputRevisionIds: [], requiredCapabilities: [] }], assets: [], identity: { projectId, revisionId } });
  snapshot.manifest.modifiedAt = time;
  return { key: `${projectId}:${revisionId}`, projectId, revisionId, savedAt: time, snapshot };
}

it("shows only the newest draft for each project, excluding revisions already saved", () => {
  const records = [recovery("art", "draft1", "2026-11-05T10:00:00Z"), recovery("art", "draft2", "2026-11-05T11:00:00Z"), recovery("saved", "draft3", "2026-11-05T09:00:00Z"), recovery("new", "draft4", "2026-11-05T12:00:00Z")];
  const entries = [{ projectId: "art", revisionId: "saved1", modifiedAt: "2026-11-05T10:30:00Z" }, { projectId: "saved", revisionId: "saved2", modifiedAt: "2026-11-05T10:30:00Z" }] as ProjectFileEntry[];
  expect(availableRecoveries(records, entries).map((record) => record.revisionId)).toEqual(["draft4", "draft2"]);
  expect(availableRecoveries(records, [...entries, { projectId: "art", revisionId: "draft2", modifiedAt: "2026-11-05T11:00:00Z" } as ProjectFileEntry]).map((record) => record.revisionId)).toEqual(["draft4"]);
});

it("uses source names for unnamed artwork while preserving explicit names and dots", () => {
  expect(suggestedProjectName("Untitled", "六朔.v2")).toBe("六朔.v2");
  expect(suggestedProjectName("未命名工程", "六朔")).toBe("六朔");
  expect(suggestedProjectName("用户的名称", "六朔")).toBe("用户的名称");
});

it.each([
  ["Unexpected project thumbnail", "project_error_invalid"],
  ["Write access to this project file was denied", "file_save_failed"],
  ["Project thumbnail could not be encoded", "project_error_thumbnail"],
  ["The project changed while it was being captured. Save again", "project_error_changed"],
])("explains %s in the selected UI language", (message, key) => {
  const t = (value: string) => translations[value]?.zh ?? value;
  expect(projectErrorMessage(message, t)).toBe(t(key));
});
