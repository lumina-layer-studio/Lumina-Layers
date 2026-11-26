import { Fragment, type ReactNode } from "react";

import type { WorkshopBackendProgress, WorkshopDownloadEstimate } from "../../api/workshop";
import { cardDividerClass, cx } from "../../components/ui/panelPrimitives";
import { useI18n } from "../../i18n/context";
import { downloadSourceName, formatBytes } from "./backendSetup";
import { useFilteredDownloadTime } from "./useFilteredDownloadTime";

const LOCAL_PHASES = new Set(["python-install", "environment", "variant-install", "variant-check", "self-check"]);
/** Not applicable in the current phase (DESIGN: unknown/absent values use “—”). */
const NONE = "—";

type Mode = "waiting" | "transfer" | "local" | "complete";

function modeOf(progress: WorkshopBackendProgress | null): Mode {
  if (!progress) return "waiting";
  if (progress.phase === "complete") return "complete";
  if (LOCAL_PHASES.has(progress.phase)) return "local";
  if (progress.download) return "transfer";
  return "waiting";
}

interface Row {
  id: string;
  label: string;
  value: ReactNode;
  title: string;
}

function DataRows({ rows, className }: { rows: Row[]; className?: string }) {
  return (
    <dl className={cx("grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs leading-5", className)}>
      {rows.map((row) => (
        <Fragment key={row.id}>
          <dt className="whitespace-nowrap text-slate-500 dark:text-slate-400">{row.label}</dt>
          <dd
            className="min-w-0 truncate text-right tabular-nums text-slate-700 dark:text-slate-200"
            title={row.title}
          >
            {row.value}
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}

function ProgressBar({ label, value }: { label: string; value?: number }) {
  return (
    <progress
      className={cx(
        "workshop-install-progress h-2 w-full appearance-none overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700",
        "[&::-webkit-progress-bar]:bg-transparent [&::-webkit-progress-value]:rounded-full [&::-webkit-progress-value]:bg-[var(--button-primary)]",
        "[&::-moz-progress-bar]:rounded-full [&::-moz-progress-bar]:bg-[var(--button-primary)]",
      )}
      max={100}
      value={value}
      aria-label={label}
    />
  );
}

/**
 * Backend preparation progress built only from server observations. Every
 * data row is always rendered on one line, so the block keeps its height
 * while values move between placeholders and measurements.
 * 后端准备进度只使用服务端观测值；每个数据行始终单行占位，数值与占位文字
 * 切换时整体高度不变。
 */
export function PreparationProgress({
  progress,
  estimate,
}: {
  progress: WorkshopBackendProgress | null;
  estimate?: WorkshopDownloadEstimate;
}) {
  const { t } = useI18n();
  const mode = modeOf(progress);
  const transfer = mode === "transfer" ? progress?.download ?? null : null;
  const phase = progress?.phase ?? "";

  const phaseKey = `workshop.backend.phase.${phase}`;
  const phaseLabel = t(phaseKey);
  const phaseName = phaseLabel !== phaseKey ? phaseLabel : t("workshop.backend.progress.starting");
  const stepTotal = progress && progress.total > 0 ? Math.floor(progress.total) : 0;
  const stepIndex = mode === "complete"
    ? stepTotal
    : Math.min(stepTotal, Math.max(0, Math.floor(progress?.completed ?? 0)) + 1);
  const step = stepTotal > 0
    ? t("workshop.backend.progress.step")
      .replace("{index}", String(stepIndex))
      .replace("{count}", String(stepTotal))
    : null;
  const overallLabel = t("workshop.backend.progress.overall");
  const overallPercent = mode === "complete"
    ? 100
    : stepTotal > 0
      ? Math.min(100, Math.max(0, 100 * (progress?.completed ?? 0) / stepTotal))
      : undefined;

  const duration = (seconds: number) => {
    const whole = Math.max(0, Math.ceil(seconds));
    return whole < 60
      ? t("workshop.backend.progress.etaSeconds").replace("{count}", String(whole))
      : t("workshop.backend.progress.etaMinutes").replace("{count}", String(Math.ceil(whole / 60)));
  };
  const measuring = t("workshop.backend.progress.measuring");
  const calculating = t("workshop.backend.progress.calculating");
  const unknown = t("workshop.backend.progress.unknown");
  const done = t("workshop.backend.progress.done");

  // Current transfer, as reported by the host for this phase.
  const phaseTotal = transfer?.total_bytes ?? null;
  const phaseReceived = transfer?.received_bytes ?? 0;
  const rate = transfer?.bytes_per_second != null
    && Number.isFinite(transfer.bytes_per_second) && transfer.bytes_per_second > 0
    ? transfer.bytes_per_second
    : null;
  const phasePercent = mode === "complete"
    ? 100
    : phaseTotal != null && phaseTotal > 0
      ? Math.min(100, Math.max(0, (100 * phaseReceived) / phaseTotal))
      : undefined;

  let fileValue: ReactNode = NONE;
  let fileTitle = NONE;
  if (transfer) {
    const sourceName = downloadSourceName(transfer.source, t);
    const index = transfer.file_count > 0
      ? t("workshop.backend.progress.fileIndex")
        .replace("{index}", String(transfer.file_index))
        .replace("{count}", String(transfer.file_count))
      : null;
    fileTitle = [
      transfer.file_name,
      sourceName === transfer.source ? sourceName : `${sourceName} (${transfer.source})`,
      index,
    ].filter(Boolean).join(" · ");
    fileValue = (
      <span className="flex min-w-0 items-baseline justify-end gap-1.5">
        <span className="min-w-0 truncate" translate="no">{transfer.file_name}</span>
        <span className="shrink-0" aria-hidden="true">·</span>
        <span className="max-w-[40%] shrink-0 truncate" translate="no">{sourceName}</span>
        {index ? <span className="shrink-0">{index}</span> : null}
      </span>
    );
  }

  const phaseBytes = transfer
    ? `${formatBytes(phaseReceived)} / ${phaseTotal == null ? t("workshop.backend.downloadSizeUnknown") : formatBytes(phaseTotal)}`
    : NONE;
  const speed = transfer
    ? rate !== null ? t("workshop.backend.downloadSpeed").replace("{speed}", formatBytes(rate)) : measuring
    : mode === "waiting" ? measuring : NONE;
  // Whole download: host byte counter against the host estimate. The time is
  // only derived when that estimate covers every file and a rate is observed.
  const downloaded = progress?.downloaded_bytes ?? null;
  const batchTotal = transfer && phaseTotal != null && downloaded != null
    ? downloaded - phaseReceived + phaseTotal
    : 0;
  const expectedBytes = Math.max(estimate?.bytes ?? 0, downloaded ?? 0, batchTotal);
  const hasTotalEstimate = estimate !== undefined && !estimate.incomplete;
  const bytesLeft = expectedBytes - (downloaded ?? 0);
  const totalText = estimate
    ? t(estimate.incomplete ? "workshop.backend.downloadKnownSizes" : "workshop.backend.downloadAbout")
      .replace("{bytes}", formatBytes(expectedBytes))
    : t("workshop.backend.downloadSizeUnknown");
  const receivedText = downloaded == null ? NONE : formatBytes(downloaded);
  const totalBytes = mode === "complete" ? receivedText : `${receivedText} / ${totalText}`;
  const batch = transfer ? `${phase}:${transfer.source}` : null;
  const phaseRawSeconds = phaseTotal !== null && rate !== null ? transfer?.eta_seconds ?? null : null;
  const totalRawSeconds = hasTotalEstimate && bytesLeft > 0 && rate !== null ? bytesLeft / rate : null;
  const phaseSeconds = useFilteredDownloadTime(phase, batch, phaseReceived, phaseRawSeconds);
  const totalSeconds = useFilteredDownloadTime("total", batch, phaseReceived, totalRawSeconds);

  let phaseRemaining = NONE;
  if (mode === "waiting" || mode === "transfer") {
    if (phaseTotal !== null && phaseReceived >= phaseTotal) {
      phaseRemaining = done;
    } else if (phaseSeconds !== null) {
      phaseRemaining = duration(phaseSeconds);
    } else {
      phaseRemaining = transfer && phaseTotal === null ? unknown : calculating;
    }
  }
  // CPU self-check can be followed by a download for the selected acceleration.
  const totalRemaining =
    mode === "complete" || phase === "variant-check"
      ? t("workshop.backend.progress.downloadsDone")
      : !hasTotalEstimate
        ? unknown
        : bytesLeft <= 0
          ? NONE
          : totalSeconds !== null ? duration(totalSeconds) : calculating;

  const phaseRows: Row[] = [
    { id: "file", label: t("workshop.backend.progress.currentFile"), value: fileValue, title: fileTitle },
    { id: "phase", label: t("workshop.backend.progress.phaseBytes"), value: phaseBytes, title: phaseBytes },
    { id: "speed", label: t("workshop.backend.progress.speed"), value: speed, title: speed },
    { id: "phase-eta", label: t("workshop.backend.progress.phaseRemaining"), value: phaseRemaining, title: phaseRemaining },
  ];
  const totalRows: Row[] = [
    { id: "total", label: t("workshop.backend.progress.totalBytes"), value: totalBytes, title: totalBytes },
    { id: "total-eta", label: t("workshop.backend.progress.totalRemaining"), value: totalRemaining, title: totalRemaining },
  ];

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <p className="flex min-w-0 items-baseline justify-between gap-3 leading-5">
        <span className="min-w-0 truncate font-medium text-slate-800 dark:text-slate-100">{overallLabel}</span>
        {step ? (
          <span className="shrink-0 text-xs tabular-nums text-slate-500 dark:text-slate-400">{step}</span>
        ) : null}
      </p>
      <ProgressBar label={overallLabel} value={overallPercent} />
      {/* Announce phase changes without repeating byte counts or timing samples. */}
      <p role="status" className="mt-1 min-w-0 truncate font-medium leading-5 text-slate-800 dark:text-slate-100" title={phaseName}>
        {phaseName}
      </p>
      <ProgressBar label={phaseName} value={phasePercent} />
      <DataRows rows={phaseRows} />
      <DataRows rows={totalRows} className={cx(cardDividerClass, "pt-2")} />
    </div>
  );
}
