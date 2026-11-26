import { useCallback, useEffect, useState } from "react";

import type {
  WorkshopBackendApi,
  WorkshopBackendStatus,
  WorkshopBackendTaskResponse,
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
import { PreparationProgress } from "./PreparationProgress";

const POLL_INTERVAL_MS = 4_000;

type BackendAction = "stop" | "acceleration" | "cancel-preparation";

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
  const [preparation, setPreparation] = useState<WorkshopBackendTaskResponse | null>(null);
  const preparationTaskId = status?.preparation_task_id ?? null;

  const updateStatus = useCallback((next: WorkshopBackendStatus) => {
    setStatus((current) => (
      current && next.preparation_task_id !== null && current.preparation_task_id === next.preparation_task_id
        ? { ...next, download_estimate: current.download_estimate }
        : next
    ));
  }, []);

  const refresh = useCallback(async () => {
    try {
      updateStatus(await api.status(moduleId, version));
      setRefreshFailed(false);
    } catch {
      setRefreshFailed(true);
    }
  }, [api, moduleId, updateStatus, version]);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      await refresh();
      if (!disposed) timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [refresh, refreshKey]);

  useEffect(() => {
    if (preparationTaskId === null) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const followPreparation = async () => {
      try {
        const task = await api.task(moduleId, preparationTaskId);
        if (disposed) return;
        setPreparation(task);
        if (task.status !== "queued" && task.status !== "running") {
          await refresh();
        }
      } catch {
        // A transient polling failure leaves the last observation visible.
      }
      if (!disposed) timer = setTimeout(() => void followPreparation(), 500);
    };
    void followPreparation();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [api, moduleId, preparationTaskId, refresh]);

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
  const cancelledVariant = preparationTaskId === null && status.failure_code === "cancelled"
    ? variants.find((variant) => variant.id === status.acceleration && !variant.prepared)
    : undefined;
  const retryVariant = cancelledVariant ?? failedVariant;
  // A failed stop is resolved once the backend no longer runs.
  const stopError = actionError?.action === "stop" && running ? actionError : null;
  const accelerationError = actionError?.action === "acceleration" ? actionError : null;
  const cancelError = actionError?.action === "cancel-preparation" && preparationTaskId ? actionError : null;
  const changeAcceleration = (value: string | null) => {
    setBusy(true);
    void api.setAcceleration(moduleId, value)
      .then((next) => {
        updateStatus(next);
        settle("acceleration");
      })
      .catch(fail("acceleration"))
      .finally(() => setBusy(false));
  };

  return (
    <div
      data-testid={`workshop-backend-${moduleId}`}
      className={cx(wellPadClass, "mt-3 flex flex-col gap-2 text-xs text-slate-600 dark:text-slate-300")}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        {preparationTaskId === null ? (
          <span role="status" className="font-medium text-slate-800 dark:text-slate-100">
            {t(`workshop.backend.state.${key}`)}
          </span>
        ) : null}
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
          {preparationTaskId !== null ? (
            <Button
              label={t("workshop.backend.cancelPreparation")}
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={() => {
                setBusy(true);
                void api.cancel(moduleId, preparationTaskId)
                  .then(() => settle("cancel-preparation"))
                  .catch(fail("cancel-preparation"))
                  .finally(() => {
                    setBusy(false);
                    void refresh();
                  });
              }}
            />
          ) : null}
        </div>
      </div>
      {preparationTaskId !== null ? (
        <PreparationProgress
          key={preparationTaskId}
          progress={preparation?.task_id === preparationTaskId ? preparation.progress : null}
          estimate={status.download_estimate}
        />
      ) : null}
      {cancelError ? (
        <StatusBanner tone="error" role="alert">
          {t("workshop.backend.cancelFailed").replace("{reason}", t(cancelError.reasonKey))}
        </StatusBanner>
      ) : null}
      {status.review_level === "unreviewed" ? (
        <StatusBanner tone="error">{t("workshop.backend.unreviewedRisk")}</StatusBanner>
      ) : null}
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
              disabled={busy || preparationTaskId !== null}
              onChange={(event) => changeAcceleration(event.target.value || null)}
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
      {retryVariant && preparationTaskId === null && status.preparation === "prepared" ? (
        <div className="flex flex-wrap items-center gap-2">
          <span>{t(cancelledVariant ? "workshop.backend.variantCancelled" : "workshop.backend.variantFailed")}</span>
          <Button
            label={t("workshop.backend.retryAcceleration")}
            size="sm"
            variant="secondary"
            loading={busy}
            disabled={status.authorization === "required"}
            onClick={() => changeAcceleration(retryVariant.id)}
          />
        </div>
      ) : null}
    </div>
  );
}

export default BackendStatusRow;
