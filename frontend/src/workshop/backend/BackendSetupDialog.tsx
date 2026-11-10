import { useState } from "react";

import type { WorkshopBackendStatus } from "../../api/workshop";
import Button from "../../components/ui/Button";
import Checkbox from "../../components/ui/Checkbox";
import CloseButton from "../../components/ui/CloseButton";
import {
  StatusBanner,
  cx,
  wellPadClass,
} from "../../components/ui/panelPrimitives";
import { useI18n } from "../../i18n/context";
import { formatBytes } from "./backendSetup";
import { backendDialogShellClass, backendDialogTitleClass } from "./dialogClasses";

export type BackendSetupPhase = "review" | "preparing" | "failed";

interface BackendSetupDialogProps {
  moduleName: string;
  status: WorkshopBackendStatus;
  phase: BackendSetupPhase;
  progress: { completed: number; total: number; phase: string } | null;
  failureCode: string | null;
  /** Why the last cancel request failed; preparation is still running. */
  cancelError?: string | null;
  onConfirm(acknowledgeUnreviewed: boolean): void;
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
  failureCode,
  cancelError = null,
  onConfirm,
  onCancel,
}: BackendSetupDialogProps) {
  const { t, lang } = useI18n();
  const [acknowledged, setAcknowledged] = useState(false);
  const unreviewed = status.requires_unreviewed_confirmation;
  const blocked = status.blocked;
  const unavailable =
    !status.platform_supported || !status.tool_available || blocked;
  const dependencies = status.dependencies;
  const newModels = status.models.filter((model) => !model.shared);
  const newBytes =
    (dependencies?.new_download_bytes ?? 0) +
    status.interpreter_download_bytes +
    newModels.reduce((total, model) => total + model.bytes, 0);
  const confirmLabel =
    status.authorization === "required"
      ? t("workshop.backend.authorizeAndPrepare")
      : t("workshop.backend.prepare");
  const variantNames = status.variants
    .filter((variant) => variant.available)
    .map((variant) => (lang === "zh" ? variant.name["zh-CN"] : variant.name["en-US"]));
  const title = t("workshop.backend.setupTitle");

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
    >
      <section className={cx(backendDialogShellClass, "max-w-xl")}>
        <div className="flex items-start justify-between gap-3">
          <h2 className={backendDialogTitleClass}>{title}</h2>
          {phase !== "preparing" ? (
            <CloseButton label={t("common_close")} onClick={onCancel} />
          ) : null}
        </div>
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
          {t("workshop.backend.setupIntro").replace("{name}", moduleName)}
        </p>
        <p className="mt-3 text-sm font-medium text-slate-800 dark:text-slate-100">
          {t(`workshop.backend.review.${status.review_level}`)}
        </p>

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
                      {capability.reason}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
              {t("workshop.backend.declarationNotice")}
            </p>

            <h3 className="mt-5 text-sm font-semibold text-slate-900 dark:text-slate-50">
              {t("workshop.backend.footprint")}
            </h3>
            <ul className="mt-2 flex flex-col gap-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
              <li>{t("workshop.backend.newDownload").replace("{bytes}", formatBytes(newBytes))}</li>
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

            {unreviewed && !unavailable ? (
              <div className="mt-4">
                <StatusBanner tone="warning">
                  {t("workshop.backend.unreviewedWarning")}
                </StatusBanner>
                <div className="mt-2">
                  <Checkbox
                    appearance="checkbox"
                    label={t("workshop.backend.acknowledgeUnreviewed")}
                    checked={acknowledged}
                    onChange={setAcknowledged}
                  />
                </div>
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
                disabled={unavailable || (unreviewed && !acknowledged)}
                onClick={() => onConfirm(unreviewed && acknowledged)}
              />
            </div>
          </>
        ) : null}

        {phase === "preparing" ? (
          <div className="mt-5">
            <p role="status" className="text-sm text-slate-700 dark:text-slate-200">
              {t("workshop.backend.preparing")}
              {progress ? ` · ${t(`workshop.backend.phase.${progress.phase}`)}` : ""}
            </p>
            <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-[color:var(--surface-section-muted)]">
              <div
                className="h-full rounded-full bg-blue-600 transition-[width]"
                style={{
                  width: `${progress && progress.total > 0 ? Math.round((progress.completed / progress.total) * 100) : 5}%`,
                }}
              />
            </div>
            {cancelError ? (
              <StatusBanner tone="error" role="alert" className="mt-4">
                {cancelError}
              </StatusBanner>
            ) : null}
            <div className="mt-5 flex justify-end">
              <Button
                label={t("workshop.backend.cancelPreparation")}
                variant="secondary"
                onClick={onCancel}
              />
            </div>
          </div>
        ) : null}

        {phase === "failed" ? (
          <div className="mt-5">
            <StatusBanner tone="error">
              {t("workshop.backend.prepareFailed").replace("{code}", failureCode ?? "unknown")}
            </StatusBanner>
            <div className="mt-5 flex justify-end">
              <Button label={t("workshop.manager.close")} variant="secondary" onClick={onCancel} />
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}

export default BackendSetupDialog;
