import { useEffect, useState } from "react";
import {
  actOnContributionQueue,
  configureAutomaticContributions,
  getContributionQueue,
} from "../api/contributions";
import type { ContributionQueueStatus, QueuedContribution } from "../api/contributions";
import { apiErrorToVisibleMessage } from "../api/client";
import { useCommunityStore } from "../stores/communityStore";
import { useI18n } from "../i18n/context";
import Button from "./ui/Button";
import Checkbox from "./ui/Checkbox";
import { DataLicenseLink } from "./ui/ResourceLicense";
import DisclosureSummary from "./ui/DisclosureSummary";
import { cx, StatusBanner, wellClass } from "./ui/panelPrimitives";

function queueBadgeClass(state: string): string {
  if (state === "sending") {
    return "bg-blue-500/12 text-blue-700 dark:bg-blue-400/15 dark:text-blue-300";
  }
  if (state === "needs_review") {
    return "bg-amber-500/12 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300";
  }
  return "bg-slate-500/12 text-slate-700 dark:bg-slate-400/15 dark:text-slate-300";
}

export default function ContributionQueue({
  onReview,
}: {
  onReview: (item: QueuedContribution) => void;
}) {
  const { t } = useI18n();
  const connection = useCommunityStore((state) => state.connection);
  const [queue, setQueue] = useState<ContributionQueueStatus | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const subject = connection?.state === "connected" ? connection.subject : undefined;

  useEffect(() => {
    let active = true;
    let loading = false;
    setConsent(false);
    const refresh = async () => {
      if (loading) return;
      loading = true;
      try {
        const result = await getContributionQueue();
        if (active) {
          setQueue(result);
          setError("");
        }
      } catch (err) {
        if (active) setError(apiErrorToVisibleMessage(err, t("contribution_failed")));
      } finally {
        loading = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [subject, t]);

  const run = async (action: () => Promise<ContributionQueueStatus>) => {
    setBusy(true);
    setError("");
    try {
      setQueue(await action());
      setConsent(false);
    } catch (err) {
      setError(apiErrorToVisibleMessage(err, t("contribution_failed")));
    } finally {
      setBusy(false);
    }
  };

  const pending = queue?.items.filter((item) => !["received", "cancelled"].includes(item.state)) || [];
  const enabled = Boolean(queue?.enabled && queue.account_id === subject);

  return (
    <div className="flex flex-col gap-3.5 border-t border-[var(--surface-divider)] pt-3.5">
      <details className={`${wellClass} px-3.5 py-2.5`}>
        <DisclosureSummary className="py-0.5 text-sm font-medium text-slate-800 dark:text-slate-100">
          <span className="inline-flex flex-wrap items-center gap-2">
            <span>{t("contribution_auto_title")}</span>
            <span
              className={cx(
                "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium",
                enabled
                  ? "bg-emerald-500/12 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300"
                  : "bg-slate-500/12 text-slate-600 dark:bg-slate-400/15 dark:text-slate-300",
              )}
            >
              {t(enabled ? "contribution_auto_on" : "contribution_auto_off")}
            </span>
          </span>
        </DisclosureSummary>
        <div className="mt-3 flex flex-col gap-3 border-t border-[var(--surface-divider)] pt-3">
          <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
            {t("contribution_auto_scope")}
          </p>
          {queue?.enabled ? (
            <div>
              <Button
                label={t("contribution_auto_disable")}
                size="sm"
                disabled={busy}
                onClick={() =>
                  void run(() => configureAutomaticContributions(queue.account_id!, false, false))
                }
              />
            </div>
          ) : (
            <>
              {!connection?.email_verified && (
                <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
                  {t("contribution_auto_verify")}
                </p>
              )}
              <Checkbox
                appearance="checkbox"
                checked={consent}
                onChange={setConsent}
                disabled={busy || !subject || !connection?.email_verified}
                label={t("contribution_auto_consent")}
              />
              <div className="flex flex-wrap items-center justify-between gap-3 pt-0.5">
                <DataLicenseLink />
                <Button
                  label={t("contribution_auto_enable")}
                  variant="primary"
                  size="sm"
                  disabled={busy || !queue || !consent || !subject || !connection?.email_verified}
                  onClick={() =>
                    void run(() => configureAutomaticContributions(subject!, true, true))
                  }
                />
              </div>
            </>
          )}
        </div>
      </details>

      {error && <StatusBanner tone="error">{error}</StatusBanner>}

      {pending.length > 0 && (
        <div className="flex flex-col gap-2.5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              {t("contribution_queue_title")}
            </p>
            <span className="rounded-md bg-[var(--surface-well)] px-2 py-0.5 text-xs tabular-nums text-slate-500 dark:text-slate-400">
              {pending.length}
            </span>
          </div>
          {pending.map((item) => (
            <div
              key={item.id}
              className={`${wellClass} flex min-w-0 flex-col gap-2 px-3.5 py-3`}
            >
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <p className="min-w-0 flex-1 break-words text-sm font-medium text-slate-900 dark:text-slate-100">
                  {item.name}
                </p>
                <span
                  className={cx(
                    "inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-[11px] font-medium",
                    queueBadgeClass(item.state),
                  )}
                >
                  {t(`contribution_queue_${item.state}`)}
                </span>
              </div>
              {subject !== item.account && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  {t("contribution_queue_other_account")}
                </p>
              )}
              {item.reason && item.reason !== "details" && (
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t(`contribution_queue_reason_${item.reason}`)}
                </p>
              )}
              <div className="flex flex-wrap items-center justify-end gap-1.5 pt-0.5">
                {(item.state === "needs_review" || !item.reviewed) && (
                  <Button
                    label={t("contribution_queue_review")}
                    size="sm"
                    variant="secondary"
                    disabled={busy || subject !== item.account}
                    onClick={() => onReview(item)}
                  />
                )}
                {item.reviewed > 0 && ["paused", "queued", "needs_review"].includes(item.state) && (
                  <Button
                    label={t(
                      item.state === "queued"
                        ? "contribution_queue_pause"
                        : "contribution_queue_retry",
                    )}
                    size="sm"
                    variant="ghost"
                    disabled={busy || (item.state !== "queued" && subject !== item.account)}
                    onClick={() =>
                      void run(() =>
                        actOnContributionQueue(
                          item.id,
                          item.state === "queued" ? "pause" : "retry",
                          subject,
                        ),
                      )
                    }
                  />
                )}
                {item.state !== "sending" && (
                  <Button
                    label={t("contribution_queue_cancel")}
                    size="sm"
                    variant="ghost"
                    tone="danger"
                    disabled={busy}
                    onClick={() => void run(() => actOnContributionQueue(item.id, "cancel"))}
                  />
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
