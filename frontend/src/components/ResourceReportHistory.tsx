import { useEffect, useState } from "react";
import { apiErrorToVisibleMessage } from "../api/client";
import { fetchResourceReportHistory, type ResourceReport } from "../api/community";
import { useCommunityStore } from "../stores/communityStore";
import { useI18n } from "../i18n/context";
import Button from "./ui/Button";
import DisclosureSummary from "./ui/DisclosureSummary";
import { StatusBanner, wellClass } from "./ui/panelPrimitives";
import { ResourceReportCard } from "./ResourceReportSupplements";

export default function ResourceReportHistory() {
  const { t } = useI18n();
  const subject = useCommunityStore((state) =>
    state.connection?.state === "connected" ? state.connection.subject : undefined,
  );
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<ResourceReport[]>([]);
  const [owner, setOwner] = useState<string>();
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    setRows([]);
    setOffset(0);
    setMore(false);
    setError("");
  }, [subject]);

  useEffect(() => {
    let active = true;
    if (!open || !subject) return;
    setBusy(true);
    setError("");
    void fetchResourceReportHistory(offset)
      .then((result) => {
        if (
          active &&
          result.subject === subject &&
          useCommunityStore.getState().connection?.subject === subject
        ) {
          setRows((previous) =>
            offset
              ? [
                  ...previous,
                  ...result.items.filter(
                    (row) => !previous.some((old) => old.report_id === row.report_id),
                  ),
                ]
              : result.items,
          );
          setOwner(subject);
          setMore(result.has_more);
        }
      })
      .catch((err) => {
        if (active) setError(apiErrorToVisibleMessage(err, t("resource_feedback_load_failed")));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [open, subject, offset, attempt, t]);

  const visibleRows = subject === owner ? rows : [];

  return (
    <details
      open={open}
      onToggle={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.currentTarget.open) setOffset(0);
        setOpen(event.currentTarget.open);
      }}
      className={`${wellClass} px-3.5 py-2.5`}
    >
      <DisclosureSummary className="py-0.5 text-sm font-medium text-slate-800 dark:text-slate-100">
        {t("resource_feedback_receipts")}
      </DisclosureSummary>
      <div className="mt-3 flex flex-col gap-2.5 border-t border-[var(--surface-divider)] pt-3">
        {!subject ? (
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t("resource_feedback_verify")}
          </p>
        ) : (
          <>
            {visibleRows.map((row) => (
              <ResourceReportCard
                key={row.report_id}
                report={row}
                subtitle={t(row.kind === "materials" ? "resources_materials" : "resources_luts")}
                showTarget
              />
            ))}
            {!busy && !error && !visibleRows.length && (
              <p className="py-2 text-xs text-slate-500 dark:text-slate-400">
                {t("resource_feedback_empty")}
              </p>
            )}
            {busy && (
              <p role="status" className="text-xs text-slate-500 dark:text-slate-400">
                {t("common_loading")}
              </p>
            )}
            {error && (
              <StatusBanner
                tone="error"
                action={
                  <Button
                    label={t("resources_retry")}
                    variant="ghost"
                    size="sm"
                    onClick={() => setAttempt((value) => value + 1)}
                  />
                }
              >
                {error}
              </StatusBanner>
            )}
            {subject === owner && more && !busy && !error && (
              <div className="flex justify-center pt-1">
                <Button
                  label={t("resource_feedback_more")}
                  variant="ghost"
                  size="sm"
                  onClick={() => setOffset((value) => value + 50)}
                />
              </div>
            )}
          </>
        )}
      </div>
    </details>
  );
}
