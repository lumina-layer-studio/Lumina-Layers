import { useCallback, useEffect, useState } from "react";

import type {
  WorkshopBackendApi,
  WorkshopBackendStatus,
} from "../../api/workshop";
import Button from "../../components/ui/Button";
import {
  StatusBanner,
  compactFieldClass,
  cx,
  wellPadClass,
} from "../../components/ui/panelPrimitives";
import { useI18n } from "../../i18n/context";
import { backendActionErrorKey } from "./backendErrors";
import { formatBytes } from "./backendSetup";

const POLL_INTERVAL_MS = 4_000;

type BackendAction = "stop" | "acceleration";

interface ActionError {
  action: BackendAction;
  reasonKey: string;
}

interface BackendStatusRowProps {
  moduleId: string;
  version: string;
  api: WorkshopBackendApi;
  refreshKey: number;
  onPrepare(status: WorkshopBackendStatus): void;
}

function stateKey(status: WorkshopBackendStatus): string {
  if (status.preparation === "preparing" || status.preparation_task_id !== null) {
    return "preparing";
  }
  if (status.preparation !== "prepared") {
    return status.preparation === "failed" ? "prepareFailed" : "unprepared";
  }
  if (status.authorization === "required") {
    return "authorizationRequired";
  }
  return status.runtime.state;
}

/**
 * Installed/enabled/running are separate: a prepared backend shows as ready
 * but not running until a task needs it. A failed action keeps its reason
 * and next step beside the control until the action succeeds; refreshing
 * the status never hides it. 已准备不等于常驻运行；操作失败的原因留在控件旁。
 */
export function BackendStatusRow({
  moduleId,
  version,
  api,
  refreshKey,
  onPrepare,
}: BackendStatusRowProps) {
  const { t, lang } = useI18n();
  const [status, setStatus] = useState<WorkshopBackendStatus | null>(null);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<ActionError | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.status(moduleId, version));
      setRefreshFailed(false);
    } catch {
      setRefreshFailed(true);
    }
  }, [api, moduleId, version]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refresh, refreshKey]);

  const settle = (action: BackendAction) =>
    setActionError((current) => (current?.action === action ? null : current));
  const fail = (action: BackendAction) => (error: unknown) =>
    setActionError({ action, reasonKey: backendActionErrorKey(error) });

  if (refreshFailed && status === null) {
    return (
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
        {t("workshop.backend.statusUnavailable")}
      </p>
    );
  }
  if (status === null) {
    return null;
  }
  const key = stateKey(status);
  const running = ["starting", "ready", "busy"].includes(status.runtime.state);
  const variants = status.variants.filter((variant) => variant.available);
  const failedVariant = variants.find(
    (variant) => variant.id === status.acceleration && variant.failure_code !== null,
  );
  // A failed stop is resolved once the backend no longer runs.
  const stopError = actionError?.action === "stop" && running ? actionError : null;
  const accelerationError = actionError?.action === "acceleration" ? actionError : null;

  return (
    <div
      data-testid={`workshop-backend-${moduleId}`}
      className={cx(wellPadClass, "mt-3 flex flex-col gap-2 text-xs text-slate-600 dark:text-slate-300")}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span role="status" className="font-medium text-slate-800 dark:text-slate-100">
          {t(`workshop.backend.state.${key}`)}
        </span>
        <div className="flex gap-2">
          {key === "unprepared" || key === "prepareFailed" || key === "authorizationRequired" ? (
            <Button
              label={t("workshop.backend.prepareAction")}
              size="sm"
              variant="secondary"
              onClick={() => onPrepare(status)}
            />
          ) : null}
          {running ? (
            <Button
              label={t("workshop.backend.stop")}
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={() => {
                setBusy(true);
                void api
                  .stop(moduleId)
                  .then(() => settle("stop"))
                  .catch(fail("stop"))
                  .finally(() => {
                    setBusy(false);
                    void refresh();
                  });
              }}
            />
          ) : null}
        </div>
      </div>
      {stopError ? (
        <StatusBanner tone="error" role="alert">
          {t("workshop.backend.stopFailed").replace("{reason}", t(stopError.reasonKey))}
        </StatusBanner>
      ) : null}
      {refreshFailed ? (
        <StatusBanner tone="warning">{t("workshop.backend.statusStale")}</StatusBanner>
      ) : null}
      {status.footprint ? (
        <span>
          {t("workshop.backend.footprintMeasured")
            .replace(
              "{new}",
              formatBytes(status.footprint.environment_new_bytes + status.footprint.model_new_bytes),
            )
            .replace(
              "{shared}",
              formatBytes(status.footprint.environment_shared_bytes + status.footprint.model_shared_bytes),
            )}
        </span>
      ) : null}
      {variants.length > 0 && status.preparation === "prepared" ? (
        <label className="flex items-center gap-2">
          <span>{t("workshop.backend.acceleration")}</span>
          <span className="w-40">
            <select
              value={status.acceleration ?? ""}
              disabled={busy}
              onChange={(event) => {
                const value = event.target.value === "" ? null : event.target.value;
                setBusy(true);
                void api
                  .setAcceleration(moduleId, value)
                  .then((next) => {
                    setStatus(next);
                    settle("acceleration");
                  })
                  .catch(fail("acceleration"))
                  .finally(() => setBusy(false));
              }}
              className={compactFieldClass}
            >
              <option value="">{t("workshop.backend.cpu")}</option>
              {variants.map((variant) => (
                <option key={variant.id} value={variant.id}>
                  {lang === "zh" ? variant.name["zh-CN"] : variant.name["en-US"]}
                </option>
              ))}
            </select>
          </span>
        </label>
      ) : null}
      {accelerationError ? (
        <StatusBanner tone="error" role="alert">
          {t("workshop.backend.accelerationFailed").replace("{reason}", t(accelerationError.reasonKey))}
        </StatusBanner>
      ) : null}
      {failedVariant ? <span>{t("workshop.backend.variantFailed")}</span> : null}
    </div>
  );
}

export default BackendStatusRow;
