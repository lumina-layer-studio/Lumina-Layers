import { useEffect, useRef, useState } from "react";
import { ArrowDownTrayIcon, ArrowTopRightOnSquareIcon } from "@heroicons/react/24/outline";
import { fetchResourceReportImage, type ResourceReport } from "../api/community";
import { useCommunityStore } from "../stores/communityStore";
import { useI18n } from "../i18n/context";
import Button from "./ui/Button";
import DisclosureSummary from "./ui/DisclosureSummary";
import { actionLinkClass, cx, reportStatusBadgeClass, StatusBanner, wellClass } from "./ui/panelPrimitives";

export function ResourceReportCard({
  report,
  subtitle,
  showTarget = false,
}: {
  report: ResourceReport;
  subtitle: string;
  showTarget?: boolean;
}) {
  const { t, lang } = useI18n();
  return (
    <div className={`${wellClass} flex min-w-0 flex-col gap-2 px-3.5 py-3 text-sm`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cx(
              "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
              reportStatusBadgeClass(report.status),
            )}
          >
            {t(`resource_feedback_status_${report.status}`)}
          </span>
          <span className="text-xs text-slate-500 dark:text-slate-400">{subtitle}</span>
        </div>
        <span className="select-all font-mono text-[11px] text-slate-400 dark:text-slate-500">
          #{report.report_id.slice(0, 8)}
        </span>
      </div>
      <p className="break-words text-sm leading-relaxed text-slate-800 dark:text-slate-100">
        {report.message}
      </p>
      {report.decision && (
        <div className="rounded-r-lg border-l-2 border-blue-400/70 bg-[var(--surface-card)] px-3 py-2 text-xs leading-5 text-slate-700 dark:text-slate-200">
          <span className="font-semibold text-slate-900 dark:text-slate-100">
            {t("resource_feedback_reply_label")}
            {lang === "zh" ? "：" : ": "}
          </span>
          <span className="break-words">{report.decision}</span>
        </div>
      )}
      <ResourceReportSupplements report={report} />
      {showTarget && (
        <details className="text-xs text-slate-500 dark:text-slate-400">
          <DisclosureSummary className="py-0.5 text-[11px]">
            {t("resource_feedback_target")}
          </DisclosureSummary>
          <p className="mt-1.5 select-all break-all font-mono text-[11px]">
            {report.resource_id} · {report.revision_id}
          </p>
          <p className="mt-0.5 select-all break-all font-mono text-[11px]">
            {t("resource_feedback_receipt")} {report.report_id}
          </p>
        </details>
      )}
    </div>
  );
}

export default function ResourceReportSupplements({ report }: { report: ResourceReport }) {
  const { t } = useI18n();
  const subject = useCommunityStore((state) =>
    state.connection?.state === "connected" ? state.connection.subject : undefined,
  );
  const [open, setOpen] = useState(false);
  const [pictures, setPictures] = useState<{ owner: string; values: string[] }>();
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const cache = useRef<{ key: string; values: string[] } | null>(null);
  const imageIds = (report.images || []).map((image) => image.image_id).join(",");

  let link = "";
  try {
    const url = new URL(report.evidence_url);
    if (url.protocol === "https:" && !url.username && !url.password) link = url.href;
  } catch {
    /* A link is optional. */
  }

  useEffect(() => {
    cache.current = null;
    setPictures(undefined);
  }, [subject]);

  useEffect(() => {
    let active = true;
    if (!open || !subject || !imageIds) return;
    const key = `${subject}:${report.report_id}:${imageIds}`;
    if (cache.current?.key === key) {
      setPictures({ owner: subject, values: cache.current.values });
      return;
    }
    setBusy(true);
    setError(false);
    void Promise.all(
      imageIds.split(",").map((imageId) => fetchResourceReportImage(report.report_id, imageId, subject)),
    )
      .then((results) => {
        if (!active || useCommunityStore.getState().connection?.subject !== subject) return;
        if (
          results.some(
            (value) =>
              value.subject !== subject ||
              value.data_url.length > 1_398_168 ||
              !/^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/.test(value.data_url),
          )
        ) {
          throw new Error("Invalid screenshot");
        }
        const values = results.map((value) => value.data_url);
        cache.current = { key, values };
        setPictures({ owner: subject, values });
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [open, subject, report.report_id, imageIds, attempt]);

  if (!link && !imageIds) return null;

  return (
    <details
      open={open}
      onToggle={(event) => {
        if (event.target === event.currentTarget) setOpen(event.currentTarget.open);
      }}
      className="min-w-0 text-xs text-slate-500 dark:text-slate-400"
    >
      <DisclosureSummary className="py-0.5 text-[11px] font-medium">
        {t("resource_feedback_details")}
      </DisclosureSummary>
      <div className="mt-2 flex min-w-0 flex-col gap-2.5">
        {link && (
          <a
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            className={`${actionLinkClass} ghost-control -ml-2.5 min-h-7 justify-self-start px-2.5 py-1 text-xs`}
          >
            <ArrowTopRightOnSquareIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>{t("resource_feedback_view_link")}</span>
          </a>
        )}
        {open &&
          pictures &&
          pictures.owner === subject &&
          pictures.values.map((url, index) => (
            <figure key={index} className="flex min-w-0 flex-col gap-1.5">
              <img
                src={url}
                alt={t("resource_feedback_image_number").replace("{number}", String(index + 1))}
                className="max-h-80 w-full rounded-lg bg-[var(--surface-card)] p-1 object-contain"
              />
              <a
                href={url}
                download={`feedback-${index + 1}.jpg`}
                className={`${actionLinkClass} ghost-control -ml-2.5 min-h-7 self-start px-2.5 py-1 text-xs`}
              >
                <ArrowDownTrayIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span>{t("resource_feedback_save_image")}</span>
              </a>
            </figure>
          ))}
        {busy && <p role="status">{t("common_loading")}</p>}
        {error && (
          <StatusBanner
            tone="warning"
            action={
              <Button
                label={t("resources_retry")}
                variant="ghost"
                size="sm"
                onClick={() => setAttempt((value) => value + 1)}
              />
            }
          >
            {t("resource_feedback_image_load_failed")}
          </StatusBanner>
        )}
      </div>
    </details>
  );
}
