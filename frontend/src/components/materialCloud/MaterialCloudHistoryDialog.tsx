import type { MaterialSyncInstalledEntry } from "../../api/types";
import ResourceHistoryDialog from "../ui/ResourceHistoryDialog";

interface Props {
  entries: MaterialSyncInstalledEntry[];
  pendingRollback: string | null;
  error: string | null;
  success: string | null;
  onDismissSuccess: () => void;
  onClose: () => void;
  onRollback: (entry: MaterialSyncInstalledEntry, revision: string) => void;
}

export default function MaterialCloudHistoryDialog({ entries, pendingRollback, onRollback, ...props }: Props) {
  return <ResourceHistoryDialog {...props} pending={pendingRollback}
    entries={entries.map(entry => ({
      resource_id: entry.material_id,
      name: entry.display_name || entry.local_directory || entry.material_id,
      current_revision: entry.revision_id,
      revisions: [...new Set([entry.revision_id, ...entry.available_revisions])].map(revision => ({
        revision_id: revision,
        installed_at: entry.revision_history?.find(row => row.revision_id === revision)?.installed_at
          ?? (revision === entry.revision_id ? entry.installed_at : null),
      })),
    }))}
    onRestore={(id, revision) => {
      const entry = entries.find(row => row.material_id === id);
      if (entry) onRollback(entry, revision);
    }} />;
}
