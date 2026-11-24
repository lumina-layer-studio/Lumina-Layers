import type { WorkshopBackendProgress, WorkshopDownloadEstimate } from "../../api/workshop";
import { useI18n } from "../../i18n/context";
import { DownloadProgressDetails } from "../DownloadProgressDetails";
import { formatBytes } from "./backendSetup";

export function PreparationProgress({
  progress,
  estimate,
}: {
  progress: WorkshopBackendProgress | null;
  estimate?: WorkshopDownloadEstimate;
}) {
  const { t } = useI18n();
  const percent = progress && progress.total > 0
    ? Math.min(100, Math.round(100 * progress.completed / progress.total))
    : undefined;
  const downloaded = progress?.downloaded_bytes ?? 0;
  const complete = progress?.phase === "complete";
  const rate = progress?.download?.bytes_per_second;
  const remaining = estimate && !estimate.incomplete && rate && estimate.bytes > downloaded
    ? Math.ceil((estimate.bytes - downloaded) / rate)
    : null;
  const total = estimate
    ? t(estimate.incomplete ? "workshop.backend.downloadKnownSizes" : "workshop.backend.downloadAbout")
      .replace("{bytes}", formatBytes(Math.max(estimate.bytes, downloaded)))
    : t("workshop.backend.downloadSizeUnknown");
  return (
    <div>
      <p role="status" className="text-sm text-slate-700 dark:text-slate-200">
        {t("workshop.backend.preparing")}
        {progress ? ` · ${t(`workshop.backend.phase.${progress.phase}`)}` : ""}
      </p>
      <progress className="mt-2 h-2 w-full" max={100} value={percent} aria-label={t("workshop.backend.preparing")} />
      {progress?.download ? <DownloadProgressDetails download={progress.download} /> : null}
      {estimate || progress?.downloaded_bytes != null ? (
        <p className="mt-3 flex flex-wrap gap-x-3 text-xs text-slate-500 dark:text-slate-400">
          <span>{t("workshop.backend.downloadOverall")
            .replace("{received}", formatBytes(downloaded))
            .replace("{total}", complete ? formatBytes(downloaded) : total)}</span>
          {remaining !== null ? (
            <span>{t(remaining < 60 ? "workshop.backend.downloadOverallEtaSeconds" : "workshop.backend.downloadOverallEtaMinutes")
              .replace("{count}", String(remaining < 60 ? remaining : Math.ceil(remaining / 60)))}</span>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}
