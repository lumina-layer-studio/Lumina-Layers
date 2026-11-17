import { useCallback, useEffect, useState } from "react";

import type { WorkshopBackendApi, WorkshopBackendStorage } from "../../api/workshop";
import Button from "../../components/ui/Button";
import {
  StatusBanner,
  resolveSectionCardClass,
} from "../../components/ui/panelPrimitives";
import { useI18n } from "../../i18n/context";
import { backendActionErrorKey } from "./backendErrors";
import { formatBytes } from "./backendSetup";

interface StorageOverviewProps {
  api: WorkshopBackendApi;
}

interface DeletionError {
  item: string;
  reasonKey: string;
}

/**
 * Backend storage owned by the host, with manual cleanup of retained data.
 * A failed deletion keeps its reason beside the item even after the list
 * refreshes, so a successful refresh never looks like a successful delete.
 * 失败的删除原因始终留在对应条目旁，刷新成功不代表删除成功。
 */
export function StorageOverview({ api }: StorageOverviewProps) {
  const { t } = useI18n();
  const [storage, setStorage] = useState<WorkshopBackendStorage | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [deletionError, setDeletionError] = useState<DeletionError | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStorage(await api.storage());
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, [api]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const remove = (item: string, action: () => Promise<void>) => {
    setBusy(item);
    void action()
      .then(() => setDeletionError((current) => (current?.item === item ? null : current)))
      .catch((error: unknown) => setDeletionError({ item, reasonKey: backendActionErrorKey(error) }))
      .finally(() => {
        setBusy(null);
        void refresh();
      });
  };

  const retry = (
    <Button label={t("workshop.manager.retry")} size="sm" variant="secondary" onClick={() => void refresh()} />
  );
  const deletionErrorFor = (item: string) =>
    deletionError?.item === item ? (
      <StatusBanner tone="error" role="alert" className="mt-1">
        {t("workshop.storage.deleteFailed").replace("{reason}", t(deletionError.reasonKey))}
      </StatusBanner>
    ) : null;

  if (loadFailed && storage === null) {
    return (
      <StatusBanner tone="error" role="alert" action={retry}>
        {t("workshop.storage.loadError")}
      </StatusBanner>
    );
  }
  if (storage === null) {
    return (
      <p role="status" className="text-sm text-slate-500 dark:text-slate-400">
        {t("workshop.manager.loading")}
      </p>
    );
  }
  const copies = storage.model_copies ?? { files: 0, bytes: 0 };
  const empty =
    storage.environments.length === 0 &&
    storage.retained_models.length === 0 &&
    storage.task_data.length === 0 &&
    storage.shared_store.objects === 0 &&
    copies.files === 0;

  return (
    <section className={resolveSectionCardClass("standard")} aria-label={t("workshop.storage.title")}>
      <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
        {t("workshop.storage.title")}
      </h3>
      <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
        {t("workshop.storage.description")}
      </p>
      {loadFailed ? (
        <StatusBanner tone="warning" className="mt-3" action={retry}>
          {t("workshop.storage.refreshError")}
        </StatusBanner>
      ) : null}
      {!storage.tool_available ? (
        <StatusBanner tone="info" className="mt-3">
          {t("workshop.backend.toolUnavailable")}
        </StatusBanner>
      ) : null}
      {empty ? (
        <p className="mt-4 text-sm text-slate-500 dark:text-slate-400">{t("workshop.storage.empty")}</p>
      ) : null}

      {storage.environments.length > 0 ? (
        <div className="mt-4">
          <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("workshop.storage.environments")}
          </h4>
          <ul className="mt-2 flex flex-col gap-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
            {storage.environments.map((environment) => (
              <li key={environment.key}>
                {t("workshop.storage.environmentRow")
                  .replace("{python}", environment.python)
                  .replace("{packages}", String(environment.packages))
                  .replace("{bytes}", formatBytes(environment.exclusive_bytes))
                  .replace(
                    "{users}",
                    environment.users.length > 0
                      ? environment.users.join(", ")
                      : t("workshop.storage.noUsers"),
                  )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {storage.shared_store.objects > 0 ? (
        <p className="mt-3 text-xs text-slate-600 dark:text-slate-300">
          {t("workshop.storage.sharedStore")
            .replace("{count}", String(storage.shared_store.objects))
            .replace("{bytes}", formatBytes(storage.shared_store.bytes))}
        </p>
      ) : null}

      {copies.files > 0 ? (
        <p className="mt-3 text-xs text-slate-600 dark:text-slate-300">
          {t("workshop.storage.modelCopies")
            .replace("{count}", String(copies.files))
            .replace("{bytes}", formatBytes(copies.bytes))}
        </p>
      ) : null}

      {storage.interpreters.length > 0 ? (
        <p className="mt-3 text-xs text-slate-600 dark:text-slate-300">
          {t("workshop.storage.interpreters").replace(
            "{versions}",
            storage.interpreters.map((item) => item.python).join(", "),
          )}
        </p>
      ) : null}

      {storage.retained_models.length > 0 ? (
        <div className="mt-4">
          <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("workshop.storage.retainedModels")}
          </h4>
          <ul className="mt-2 flex flex-col gap-2">
            {storage.retained_models.map((model) => (
              <li key={model.sha256} className="text-xs text-slate-600 dark:text-slate-300">
                <div className="flex items-center justify-between gap-3">
                  <span>
                    {model.file_name} · {formatBytes(model.size_bytes)} · {model.module_id}
                  </span>
                  <Button
                    label={t("workshop.storage.delete")}
                    size="sm"
                    variant="secondary"
                    tone="danger"
                    loading={busy === model.sha256}
                    onClick={() => remove(model.sha256, () => api.deleteRetainedModel(model.sha256))}
                  />
                </div>
                {deletionErrorFor(model.sha256)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {storage.task_data.length > 0 ? (
        <div className="mt-4">
          <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("workshop.storage.taskData")}
          </h4>
          <ul className="mt-2 flex flex-col gap-2">
            {storage.task_data.map((item) => (
              <li key={item.module_id} className="text-xs text-slate-600 dark:text-slate-300">
                <div className="flex items-center justify-between gap-3">
                  <span>
                    {t("workshop.storage.taskRow")
                      .replace("{module}", item.module_id)
                      .replace("{count}", String(item.task_count))
                      .replace("{bytes}", formatBytes(item.bytes))}
                  </span>
                  <Button
                    label={t("workshop.storage.delete")}
                    size="sm"
                    variant="secondary"
                    tone="danger"
                    loading={busy === item.module_id}
                    onClick={() => remove(item.module_id, () => api.deleteTaskData(item.module_id))}
                  />
                </div>
                {deletionErrorFor(item.module_id)}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{t("workshop.storage.retention")}</p>
        </div>
      ) : null}

      {storage.pending.length > 0 ? (
        <StatusBanner tone="warning" className="mt-4">
          {t("workshop.storage.pending").replace("{count}", String(storage.pending.length))}
        </StatusBanner>
      ) : null}
    </section>
  );
}

export default StorageOverview;
