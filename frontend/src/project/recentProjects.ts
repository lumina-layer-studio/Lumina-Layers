import type { ProjectFileEntry } from "./files";
import type { RecoveryRecord } from "./recoveryStore";

/** Show one newer draft per project; older saved revisions remain in storage. */
export function availableRecoveries(records: RecoveryRecord[], entries: ProjectFileEntry[]): RecoveryRecord[] {
  const newest = new Map<string, RecoveryRecord>();
  for (const record of [...records].sort((a, b) => b.savedAt.localeCompare(a.savedAt))) {
    if (!newest.has(record.projectId)) newest.set(record.projectId, record);
  }
  return [...newest.values()].filter((record) => !entries.some((entry) =>
    entry.projectId === record.projectId && (entry.revisionId === record.revisionId || entry.modifiedAt >= record.snapshot.manifest.modifiedAt),
  ));
}

export function suggestedProjectName(name: string, sourceName?: string): string {
  if (name.trim() && name !== "Untitled" && name !== "未命名工程") return name;
  return sourceName?.trim() || name || "Untitled";
}
