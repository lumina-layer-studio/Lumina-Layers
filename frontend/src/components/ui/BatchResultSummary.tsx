import type { BatchResponse } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { cx, StatusBanner, wellPadClass } from "./panelPrimitives";
import { normalizeResourceUrl } from "../../utils/resourceUrl";
import { isUnsafeVisibleErrorText } from "../../utils/visibleErrorText";

interface BatchResultSummaryProps {
  result: BatchResponse;
}

const API_BATCH_ITEM_FAILED_DETAIL =
  "This file could not be converted. Re-upload it or check the server log for details.";

function shouldHideRawBatchItemError(error: string): boolean {
  const trimmed = error.trim();
  return (
    trimmed === API_BATCH_ITEM_FAILED_DETAIL ||
    isUnsafeVisibleErrorText(trimmed)
  );
}

function visibleBatchItemError(
  error: string | undefined,
  fallback: string,
): string | null {
  if (!error?.trim()) {
    return null;
  }
  const trimmed = error.trim();
  return shouldHideRawBatchItemError(trimmed) ? fallback : trimmed;
}

export default function BatchResultSummary({ result }: BatchResultSummaryProps) {
  const { t } = useI18n();
  const downloadUrl =
    normalizeResourceUrl(result.download_url) ?? result.download_url ?? "";
  const hasDownload =
    typeof downloadUrl === "string" && downloadUrl.length > 0;
  const successCount = result.results.filter(
    (r) => r.status === "success",
  ).length;
  const failedCount = result.results.filter(
    (r) => r.status === "failed",
  ).length;
  const total = result.results.length;
  const failedItems = result.results.filter((r) => r.status === "failed");
  const downloadableItems = result.results.filter((item) => item.download_url);

  return (
    <div className={cx(wellPadClass, "flex flex-col gap-3 text-sm")}>
      {/* Summary stats */}
      <p className="text-slate-600 dark:text-slate-300">
        {t("batch_success")}{" "}
        <span className="font-medium text-green-700 dark:text-green-400">{successCount}</span>
        {" / "}{t("batch_total")}{" "}
        <span className="font-medium text-slate-800 dark:text-slate-200">{total}</span>
        {failedCount > 0 && (
          <>
            {"，"}{t("batch_failed")}{" "}
            <span className="font-medium text-red-700 dark:text-red-400">{failedCount}</span>
          </>
        )}
      </p>

      {/* Download button — rendered unconditionally when download_url is non-empty */}
      {hasDownload && (
        <a
          href={downloadUrl}
          download
          className="inline-flex items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          aria-label={t("batch.download.mergedThreemf")}
        >
          <svg
            className="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          {t("batch.download.mergedThreemf")}
        </a>
      )}

      {downloadableItems.length > 0 && (
        <ul className="flex flex-col gap-1">
          {downloadableItems.map((item, index) => (
            <li key={`${item.filename}-${index}`}>
              <a
                href={normalizeResourceUrl(item.download_url) ?? item.download_url ?? ""}
                download
                className="text-blue-700 underline underline-offset-2 dark:text-blue-400"
              >
                {item.filename}
              </a>
            </li>
          ))}
        </ul>
      )}

      {/* Plate-overflow warnings — keyed by WarningEntry.code, never by message text */}
      {result.warnings?.map((w) => {
        if (w.code === "merge-unavailable") {
          return (
            <StatusBanner key={w.code} role="status" tone="warning">
              {t("batch.warnings.mergeUnavailable.body")}
            </StatusBanner>
          );
        }
        if (w.code === "plate-overflow") {
          return (
            <StatusBanner key={w.code} role="status" tone="warning">
              {t("batch.warnings.plateOverflow.body")}
            </StatusBanner>
          );
        }
        if (w.code === "preview-limited") {
          return (
            <StatusBanner key={w.code} role="status" tone="warning">
              {t("batch.warnings.previewLimited.body")}
            </StatusBanner>
          );
        }
        if (w.code === "wipe_tower_manual_adjustment_required") {
          return (
            <StatusBanner
              key={w.code}
              role="alert"
              tone="warning"
              title={t("batch.warnings.wipeTowerManual.title")}
            >
              {t("batch.warnings.wipeTowerManual.body")}
            </StatusBanner>
          );
        }
        return null;
      })}

      {/* Failed items list */}
      {failedItems.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium text-red-700 dark:text-red-400">{t("batch_failed_files")}</p>
          <ul className="flex flex-col" aria-label={t("batch_failed_list_label")}>
            {failedItems.map((item, index) => {
              const visibleError = visibleBatchItemError(
                item.error,
                t("batch.itemError.conversionFailed"),
              );
              return (
                <li
                  key={`${item.filename}-${index}`}
                  className="border-t border-[color:var(--surface-divider)] px-2 py-1.5 text-xs text-slate-600 first:border-t-0 dark:text-slate-300"
                >
                  <span className="font-medium">{item.filename}</span>
                  {visibleError && (
                    <span className="text-red-700 dark:text-red-300"> — {visibleError}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
