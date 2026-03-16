import type { BatchResponse } from "../../api/types";
import { useI18n } from "../../i18n/context";

interface BatchResultSummaryProps {
  result: BatchResponse;
}

export default function BatchResultSummary({ result }: BatchResultSummaryProps) {
  const { t } = useI18n();
  const successCount = result.results.filter(
    (r) => r.status === "success",
  ).length;
  const failedCount = result.results.filter(
    (r) => r.status === "failed",
  ).length;
  const total = result.results.length;
  const failedItems = result.results.filter((r) => r.status === "failed");

  return (
    <div className="flex flex-col gap-3 rounded-md bg-gray-800 p-3 text-sm">
      {/* Summary stats */}
      <p className="text-gray-300">
        {t("batch_success")}{" "}
        <span className="font-medium text-green-400">{successCount}</span>
        {" / "}{t("batch_total")}{" "}
        <span className="font-medium text-gray-200">{total}</span>
        {failedCount > 0 && (
          <>
            {"，"}{t("batch_failed")}{" "}
            <span className="font-medium text-red-400">{failedCount}</span>
          </>
        )}
      </p>

      {/* Download button */}
      {successCount > 0 && (
        <a
          href={`http://localhost:8000${result.download_url}`}
          download
          className="inline-flex items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          aria-label={t("batch_download_zip_aria")}
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
          {t("batch_download_zip")}
        </a>
      )}

      {/* Failed items list */}
      {failedItems.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium text-red-400">{t("batch_failed_files")}</p>
          <ul className="flex flex-col gap-1" aria-label={t("batch_failed_list_label")}>
            {failedItems.map((item, index) => (
              <li
                key={`${item.filename}-${index}`}
                className="rounded bg-red-900/20 px-2 py-1 text-xs text-gray-300"
              >
                <span className="font-medium">{item.filename}</span>
                {item.error && (
                  <span className="text-red-300"> — {item.error}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
