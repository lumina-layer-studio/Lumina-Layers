import { useEffect, useRef, useState } from "react";

import type {
  WorkshopBackendProgress,
  WorkshopBackendStatus,
  WorkshopDownloadPreferences,
} from "../../api/workshop";
import Button from "../../components/ui/Button";
import Checkbox from "../../components/ui/Checkbox";
import CloseButton from "../../components/ui/CloseButton";
import {
  StatusBanner,
  cx,
  wellPadClass,
} from "../../components/ui/panelPrimitives";
import { useI18n } from "../../i18n/context";
import { BackendDownloadSources } from "./BackendDownloadSources";
import { formatBytes } from "./backendSetup";
import { PreparationProgress } from "./PreparationProgress";
import { backendDialogShellClass, backendDialogTitleClass } from "./dialogClasses";

export type BackendSetupPhase = "review" | "preparing" | "failed";

interface BackendSetupDialogProps {
  moduleName: string;
  status: WorkshopBackendStatus;
  phase: BackendSetupPhase;
  progress: WorkshopBackendProgress | null;
  cancelling?: boolean;
  failureCode: string | null;
  failureDetail?: string | null;
  /** Why the last cancel request failed; preparation is still running. */
  cancelError?: string | null;
  onConfirm(acknowledgeUnreviewed: boolean, sources?: WorkshopDownloadPreferences): void;
  onRetry(): void;
  onCancel(): void;
}

/**
 * Consent and preparation for a module backend. Declarations explain intent
 * only; local-process mode is not an OS sandbox.
 * 后端授权与准备：声明只说明用途，本机进程模式不是系统级沙箱。
 */
export function BackendSetupDialog({
  moduleName,
  status,
  phase,
  progress,
  cancelling = false,
  failureCode,
  failureDetail,
  cancelError = null,
  onConfirm,
  onRetry,
  onCancel,
}: BackendSetupDialogProps) {
  const { t, lang } = useI18n();
  const [acknowledged, setAcknowledged] = useState(false);
  const [sources, setSources] = useState<WorkshopDownloadPreferences>(status.download_preferences ?? {});
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (phase === "preparing") heading.current?.focus();
  }, [phase]);
  const needsAcknowledgement = status.requires_unreviewed_confirmation;
  const blocked = status.blocked;
  const unavailable =
    !status.platform_supported || !status.tool_available || blocked;
  const dependencies = status.dependencies;
  const files = [...status.models, ...(status.artifacts ?? [])];
  const newFiles = files.filter((file) => !file.shared);
  const acceleration = status.variants.find((variant) => variant.id === status.acceleration && variant.available);
  const newBytes = status.download_estimate?.bytes ?? (
    (dependencies?.new_download_bytes ?? 0) +
    (acceleration?.dependencies?.new_download_bytes ?? 0) +
    status.interpreter_download_bytes +
    newFiles.reduce((total, file) => total + file.bytes, 0));
  const sizeIncomplete = status.download_estimate?.incomplete ?? (
    (dependencies?.unknown_size_packages ?? 0)
    + (acceleration?.dependencies?.unknown_size_packages ?? 0) > 0);
  const confirmLabel =
    status.authorization === "required"
      ? t("workshop.backend.authorizeAndPrepare")
      : t("workshop.backend.prepare");
  const variantNames = status.variants
    .filter((variant) => variant.available)
    .map((variant) => (lang === "zh" ? variant.name["zh-CN"] : variant.name["en-US"]));
  const title = t(phase === "preparing" ? "workshop.backend.preparing" : "workshop.backend.setupTitle");
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
    >
      <section className={cx(backendDialogShellClass, "max-w-xl max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-y-contain")}>
        <div className="flex items-start justify-between gap-3">
          <h2 ref={heading} tabIndex={-1} className={cx(backendDialogTitleClass, "focus:outline-none")}>{title}</h2>
          {phase !== "preparing" ? (
            <CloseButton label={t("common_close")} onClick={onCancel} />
          ) : null}
        </div>
        {phase === "preparing" ? (
          <p className="mt-1 truncate text-sm text-slate-600 dark:text-slate-300" title={moduleName}>
            {moduleName}
          </p>
        ) : (
          <>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t("workshop.backend.setupIntro").replace("{name}", moduleName)}
            </p>
            <p className="mt-3 text-sm font-medium text-slate-800 dark:text-slate-100">
              {t(`workshop.backend.review.${status.review_level}`)}
            </p>
          </>
        )}
        {phase !== "preparing" && status.review_level === "unreviewed" ? (
          <StatusBanner tone="error" role="alert" className="mt-4">
            <strong className="block">{t("workshop.backend.unreviewedRisk")}</strong>
            {t("workshop.backend.unreviewedWarning")}
          </StatusBanner>
        ) : null}

        {phase === "review" ? (
          <>
            <h3 className="mt-5 text-sm font-semibold text-slate-900 dark:text-slate-50">
              {t("workshop.backend.capabilities")}
            </h3>
            {status.capabilities.length === 0 ? (
              <p className="mt-2 text-xs leading-5 text-slate-600 dark:text-slate-300">
                {t("workshop.backend.noCapabilities")}
              </p>
            ) : (
              <ul className={cx(wellPadClass, "mt-2 flex flex-col gap-3")}>
                {status.capabilities.map((capability) => (
                  <li key={capability.name}>
                    <p className="text-sm font-medium text-slate-800 dark:text-slate-100">
                      {t(`workshop.backend.capability.${capability.name}`)}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
                      {(lang === "zh" ? capability.reason_i18n?.zh_cn : capability.reason_i18n?.en_us)
                        ?? capability.reason}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <h3 className="mt-5 text-sm font-semibold text-slate-900 dark:text-slate-50">
              {t("workshop.backend.footprint")}
            </h3>
            <p className="mt-2 text-xs leading-5 text-slate-600 dark:text-slate-300">
              {t(sizeIncomplete ? "workshop.backend.newDownloadPartial" : "workshop.backend.newDownload")
                .replace("{bytes}", formatBytes(newBytes))}
            </p>
            <BackendDownloadSources status={status} preferences={sources} disabled={unavailable} onChange={setSources} />
            <ul className="mt-3 flex flex-col gap-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
              {dependencies?.environment_reused ? (
                <li>{t("workshop.backend.environmentReused")}</li>
              ) : dependencies ? (
                <li>
                  {t("workshop.backend.dependencies")
                    .replace("{packages}", String(dependencies.package_count))
                    .replace("{shared}", String(dependencies.shared_package_count))
                    .replace("{bytes}", formatBytes(dependencies.new_download_bytes))}
                </li>
              ) : null}
              {dependencies && dependencies.unknown_size_packages > 0 ? (
                <li>
                  {t("workshop.backend.unknownSizes").replace(
                    "{count}",
                    String(dependencies.unknown_size_packages),
                  )}
                </li>
              ) : null}
              {status.interpreter_download_bytes > 0 ? (
                <li>
                  {t("workshop.backend.interpreter")
                    .replace("{version}", status.python)
                    .replace("{bytes}", formatBytes(status.interpreter_disk_bytes))}
                </li>
              ) : null}
              {status.models.map((model) => (
                <li key={model.id}>
                  {t("workshop.backend.model")
                    .replace("{file}", model.file_name)
                    .replace("{bytes}", formatBytes(model.bytes))
                    .replace("{license}", model.license)}
                  {model.shared ? ` · ${t("workshop.backend.shared")}` : ""}
                </li>
              ))}
              {(status.artifacts ?? []).map((file) => (
                <li key={file.id}>
                  {t("workshop.backend.artifact")
                    .replace("{file}", file.file_name)
                    .replace("{bytes}", formatBytes(file.bytes))
                    .replace("{license}", file.license)}
                  {file.shared ? ` · ${t("workshop.backend.shared")}` : ""}
                </li>
              ))}
              {variantNames.length > 0 ? (
                <li>
                  {t("workshop.backend.variantsAvailable").replace(
                    "{names}",
                    variantNames.join(lang === "zh" ? "、" : ", "),
                  )}
                </li>
              ) : null}
            </ul>

            {blocked ? (
              <StatusBanner tone="error" className="mt-4">
                {t("workshop.backend.blocked")}
              </StatusBanner>
            ) : !status.platform_supported ? (
              <StatusBanner tone="error" className="mt-4">
                {t("workshop.backend.platformUnsupported")}
              </StatusBanner>
            ) : !status.tool_available ? (
              <StatusBanner tone="error" className="mt-4">
                {t("workshop.backend.toolUnavailable")}
              </StatusBanner>
            ) : null}

            {needsAcknowledgement && !unavailable ? (
              <div className="mt-4">
                <Checkbox
                  appearance="checkbox"
                  label={t("workshop.backend.acknowledgeUnreviewed")}
                  checked={acknowledged}
                  onChange={setAcknowledged}
                />
              </div>
            ) : null}

            <div className="mt-5 flex justify-end gap-2">
              <Button
                label={t("workshop.manager.cancel")}
                variant="secondary"
                onClick={onCancel}
              />
              <Button
                label={confirmLabel}
                variant="primary"
                disabled={unavailable || (needsAcknowledgement && !acknowledged)}
                onClick={() => onConfirm(
                  needsAcknowledgement && acknowledged,
                  Object.keys(sources).length > 0 ? sources : undefined,
                )}
              />
            </div>
          </>
        ) : null}

        {phase === "preparing" ? (
          <div className="mt-4 text-sm">
            <PreparationProgress progress={progress} estimate={{ bytes: newBytes, incomplete: sizeIncomplete }} />
            {/* Fixed-height footer: the cancel notice sits in a reserved slot beside the button. */}
            <div className="mt-5 flex min-h-12 items-center justify-end gap-3">
              <div className="min-w-0 flex-1">
                {cancelError ? (
                  <p
                    role="alert"
                    className="line-clamp-3 break-words text-xs leading-4 text-red-600 dark:text-red-400"
                    title={cancelError}
                  >
                    {cancelError}
                  </p>
                ) : cancelling ? (
                  <p role="status" className="truncate text-xs leading-4 text-slate-500 dark:text-slate-400">
                    {t("workshop.backend.progress.cancelling")}
                  </p>
                ) : null}
              </div>
              <Button
                label={t("workshop.backend.cancelPreparation")}
                variant="secondary"
                className="shrink-0"
                loading={cancelling}
                onClick={onCancel}
              />
            </div>
          </div>
        ) : null}

        {phase === "failed" ? (
          <div className="mt-5">
            <StatusBanner tone="error">
              {t("workshop.backend.prepareFailed").replace("{code}", failureCode ?? "unknown")}
              {failureDetail ? <p className="mt-1 break-words">{failureDetail}</p> : null}
            </StatusBanner>
            <div className="mt-5 flex justify-end gap-2">
              <Button label={t("workshop.manager.close")} variant="secondary" onClick={onCancel} />
              <Button label={t("workshop.manager.retry")} variant="primary" onClick={onRetry} />
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}

export default BackendSetupDialog;
