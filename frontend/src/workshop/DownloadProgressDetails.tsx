import type { WorkshopDownloadProgress } from "../api/workshop";
import { cx, wellPadClass } from "../components/ui/panelPrimitives";
import { useI18n } from "../i18n/context";
import { downloadSourceName, formatBytes } from "./backend/backendSetup";

export function DownloadProgressDetails({ download }: { download: WorkshopDownloadProgress }) {
  const { t } = useI18n();
  const fileOnly = download.total_bytes === null && download.file_total_bytes != null;
  const total = fileOnly ? download.file_total_bytes : download.total_bytes;
  const received = fileOnly ? download.file_received_bytes ?? 0 : download.received_bytes;
  const remaining = download.eta_seconds;
  const etaKey = fileOnly ? "workshop.backend.downloadFileEta" : "workshop.backend.downloadEta";
  return (
    <div className={cx(wellPadClass, "mt-3 flex flex-col gap-2 text-xs text-slate-600 dark:text-slate-300")}>
      <p className="break-all font-medium">
        {t("workshop.backend.downloadFile")
          .replace("{file}", download.file_name)
          .replace("{source}", downloadSourceName(download.source))
          .replace("{index}", String(download.file_index))
          .replace("{count}", String(download.file_count))}
      </p>
      <p>
        {t(fileOnly ? "workshop.backend.downloadFileBytes" : "workshop.backend.downloadBytes")
          .replace("{received}", formatBytes(received))
          .replace("{total}", total == null ? t("workshop.backend.downloadSizeUnknown") : formatBytes(total))}
      </p>
      <progress
        className="h-2 w-full"
        max={100}
        value={total ? Math.min(100, Math.round(100 * received / total)) : undefined}
        aria-label={t("workshop.backend.downloadMeter")}
      />
      <p className="flex flex-wrap gap-x-4 gap-y-1">
        {download.bytes_per_second ? (
          <span>{t("workshop.backend.downloadSpeed").replace("{speed}", formatBytes(download.bytes_per_second))}</span>
        ) : null}
        {remaining != null ? (
          <span>{t(etaKey + (remaining < 60 ? "Seconds" : "Minutes"))
            .replace("{count}", String(remaining < 60 ? remaining : Math.ceil(remaining / 60)))}</span>
        ) : null}
      </p>
    </div>
  );
}
