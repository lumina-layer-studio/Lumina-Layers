import { useId, useState } from "react";
import type { LocalResourceHistory } from "../../api/types";
import { useI18n } from "../../i18n/context";
import Button from "./Button";
import ResourceDialog from "./ResourceDialog";
import { RadioIndicator } from "./RadioGroup";
import TransientBanner from "./TransientBanner";
import { StatusBanner } from "./panelPrimitives";

export interface ResourceHistoryDialogProps {
  entries: LocalResourceHistory[];
  pending: string | null;
  error: string | null;
  success: string | null;
  note?: string;
  onDismissSuccess: () => void;
  onClose: () => void;
  onRestore: (resourceId: string, revisionId: string) => void;
  onRefresh?: () => void;
}

/** Local installation dates identify versions; hashes remain internal. */
export default function ResourceHistoryDialog({ entries, pending, error, success, note, onDismissSuccess, onClose, onRestore, onRefresh }: ResourceHistoryDialogProps) {
  const { t, lang } = useI18n();
  const titleId = useId();
  const [selection, setSelection] = useState<{ resource: string; revision: string } | null>(null);
  const selectedEntry = entries.find(entry => entry.resource_id === selection?.resource
    && entry.current_revision !== selection.revision
    && entry.revisions.some(revision => revision.revision_id === selection.revision && revision.available !== false));
  const date = (value?: string | null) => {
    if (!value || !Number.isFinite(Date.parse(value))) return t("mat_sync_history_unknown_date");
    return new Date(value).toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  };
  return <ResourceDialog title={t("mat_sync_local_section_title")} busy={pending !== null} onClose={onClose}
    footer={close => <div className="grid gap-3">
      {error && <StatusBanner tone="error">{error}</StatusBanner>}
      <TransientBanner message={success} onDismiss={onDismissSuccess} />
      <div className="flex flex-wrap justify-end gap-2">
        {onRefresh && <Button variant="ghost" label={t("lut_library_refresh_btn")} onClick={onRefresh} disabled={pending !== null} />}
        <Button label={t("mat_sync_history_close")} onClick={close} disabled={pending !== null} />
        <Button variant="primary" label={t("mat_sync_history_restore")} disabled={!selectedEntry || !selection || pending !== null}
          loading={pending !== null} onClick={() => { if (selectedEntry && selection) onRestore(selectedEntry.resource_id, selection.revision); }} />
      </div>
    </div>}>
        <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">{note || t("mat_sync_history_hint")}</p>
          {entries.length === 0 && <p className="py-6 text-sm text-slate-500">{t("mat_sync_history_empty")}</p>}
          {entries.map(entry => {
            const current = entry.revisions.find(row => row.revision_id === entry.current_revision);
            const revisions = entry.revisions.filter(row => row.revision_id !== entry.current_revision)
              .sort((a, b) => (Date.parse(b.installed_at ?? "") || 0) - (Date.parse(a.installed_at ?? "") || 0));
            return <fieldset key={entry.resource_id} className="min-w-0">
              <legend className="mb-2 break-words text-sm font-semibold text-slate-900 dark:text-slate-100">{entry.name}</legend>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-[10px] bg-[var(--surface-well)] px-3.5 py-2.5 text-sm text-slate-700 dark:text-slate-200">
                <span className="tabular-nums">{date(current?.installed_at)}</span>
                <span className="rounded-md bg-[var(--surface-card)] px-2 py-0.5 text-xs font-medium text-slate-700 dark:text-slate-200">{t("mat_sync_history_current")}</span>
                {current?.available === false && <span className="w-full text-xs text-slate-500 dark:text-slate-400">{t("resources_history_unavailable")}</span>}
              </div>
              <div className="space-y-1">
                {revisions.map((revision, index) => {
                  const selected = selection?.resource === entry.resource_id && selection.revision === revision.revision_id;
                  return <label key={revision.revision_id}
                    className={`flex items-center gap-3 rounded-[10px] px-3.5 py-2.5 text-sm text-slate-700 transition-colors dark:text-slate-200 ${revision.available === false ? "opacity-60" : "cursor-pointer"} ${selected ? "bg-[var(--surface-well)] font-medium text-slate-900 dark:text-slate-100" : "hover:bg-[var(--surface-well)]/60"}`}>
                    <input type="radio" name={titleId} checked={selected}
                      disabled={pending !== null || revision.available === false} onChange={() => setSelection({ resource: entry.resource_id, revision: revision.revision_id })}
                      className="peer sr-only" />
                    <RadioIndicator checked={selected} />
                    <span className="min-w-0 flex-1 tabular-nums">{date(revision.installed_at)}
                      {revision.available === false && <span className="mt-1 block text-xs font-normal text-slate-500 dark:text-slate-400">{t("resources_history_unavailable")}</span>}
                    </span>
                    <span className="shrink-0 text-xs text-slate-500 dark:text-slate-400">{t("mat_sync_history_previous")} {index + 1}</span>
                  </label>;
                })}
              </div>
            </fieldset>;
          })}
  </ResourceDialog>;
}
