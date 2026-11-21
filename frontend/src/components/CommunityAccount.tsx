import { useEffect, useState, type MouseEvent } from "react";
import { ArrowPathIcon, ArrowTopRightOnSquareIcon, UserCircleIcon } from "@heroicons/react/24/outline";
import { useCommunityStore } from "../stores/communityStore";
import { useI18n } from "../i18n/context";
import Button from "./ui/Button";
import DisclosureSummary from "./ui/DisclosureSummary";
import ResourceDialog from "./ui/ResourceDialog";
import { actionLinkClass, StatusBanner, wellClass } from "./ui/panelPrimitives";

export function CommunityConnection({
  disabled = false,
  requireVerifiedEmail = false,
  compact = false,
}: {
  disabled?: boolean;
  requireVerifiedEmail?: boolean;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const connection = useCommunityStore((state) => state.connection);
  const error = useCommunityStore((state) => state.connectionError);
  const [action, setAction] = useState<"start" | "check" | "disconnect" | "restart" | null>(null);
  const [linkError, setLinkError] = useState(false);
  const busy = disabled || action !== null;
  const needsVerification =
    requireVerifiedEmail && connection?.state === "connected" && !connection.email_verified;

  useEffect(() => {
    void useCommunityStore.getState().refreshConnection();
  }, []);

  useEffect(() => {
    if (connection?.state !== "pending") return;
    const timer = window.setInterval(() => {
      void useCommunityStore.getState().refreshConnection();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [connection?.state]);

  const run = async (name: Exclude<typeof action, null>, task: () => Promise<void>) => {
    setLinkError(false);
    setAction(name);
    try {
      await task();
    } finally {
      setAction(null);
    }
  };

  const openWebLink = (event: MouseEvent<HTMLAnchorElement>) => {
    const openCommunityPage = (window as Window & {
      electronAPI?: { openCommunityPage?: (url: string) => Promise<void> };
    }).electronAPI?.openCommunityPage;
    const url = event.currentTarget.getAttribute("href");
    if (!openCommunityPage || !url) return;
    event.preventDefault();
    setLinkError(false);
    void openCommunityPage(url).catch(() => setLinkError(true));
  };

  return (
    <div className="flex min-w-0 flex-col gap-3">
      {connection?.state === "connected" ? (
        <div className={`${wellClass} flex flex-col gap-2.5 px-3.5 py-3`}>
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 flex-1 items-center gap-2.5">
              <UserCircleIcon
                className="h-7 w-7 shrink-0 text-slate-500 dark:text-slate-400"
                aria-hidden="true"
              />
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {connection.display_name}
                </p>
                <p
                  role="status"
                  className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400"
                >
                  <span
                    aria-hidden="true"
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${needsVerification ? "bg-amber-500" : "bg-emerald-500"}`}
                  />
                  {t("community_connected")}
                </p>
              </div>
            </div>
            <Button
              label={t("contribution_disconnect")}
              variant="secondary"
              size="sm"
              disabled={busy}
              loading={action === "disconnect"}
              onClick={() => void run("disconnect", useCommunityStore.getState().disconnect)}
            />
          </div>
          {(!compact || needsVerification) && (
            <div className="flex flex-wrap items-center gap-2 border-t panel-divider pt-2.5">
              <a
                className={`${actionLinkClass} ghost-control -ml-2.5 min-h-8 px-2.5 py-1 text-xs`}
                href={connection.web_url + "/#/account"}
                target="_blank"
                rel="noreferrer"
                onClick={openWebLink}
              >
                <ArrowTopRightOnSquareIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                {t(needsVerification ? "community_verify_email" : "community_web_account")}
              </a>
              {needsVerification && (
                <Button
                  label={t("community_verification_check")}
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  loading={action === "check"}
                  leadingIcon={<ArrowPathIcon className="h-3.5 w-3.5" />}
                  onClick={() => void run("check", useCommunityStore.getState().refreshConnection)}
                />
              )}
            </div>
          )}
        </div>
      ) : connection?.state === "pending" ? (
        <>
          <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t("contribution_approve_hint")}
          </p>
          <div className={`${wellClass} flex flex-col items-center gap-1.5 px-4 py-4 text-center`}>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {t("contribution_code")}
            </span>
            <p className="select-all break-all font-mono text-2xl font-semibold tracking-[0.2em] text-slate-900 dark:text-slate-50">
              {connection.code}
            </p>
            <p role="status" className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {t("contribution_waiting")}
            </p>
          </div>
          <a
            className={`${actionLinkClass} action-control action-control-primary w-full`}
            href={busy ? undefined : connection.connect_url}
            aria-disabled={busy || undefined}
            target="_blank"
            rel="noreferrer"
            onClick={openWebLink}
          >
            <ArrowTopRightOnSquareIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{t("contribution_browser")}</span>
          </a>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button
              label={t("contribution_restart")}
              variant="ghost"
              size="sm"
              disabled={busy}
              loading={action === "restart"}
              onClick={() =>
                void run("restart", async () => {
                  await useCommunityStore.getState().disconnect();
                  if (useCommunityStore.getState().connection?.state === "disconnected") {
                    await useCommunityStore.getState().start();
                  }
                })
              }
            />
            <Button
              label={t("contribution_check")}
              variant="ghost"
              size="sm"
              disabled={busy}
              loading={action === "check"}
              leadingIcon={<ArrowPathIcon className="h-4 w-4" />}
              onClick={() => void run("check", useCommunityStore.getState().refreshConnection)}
            />
          </div>
          <details className="text-xs text-slate-500 dark:text-slate-400">
            <DisclosureSummary className="py-1">{t("contribution_connection_lifetime")}</DisclosureSummary>
            <p className="pt-2 leading-5">
              {t(connection.can_remember ? "contribution_device_hint" : "contribution_session_hint")}
            </p>
          </details>
        </>
      ) : (
        <div className={`${wellClass} flex flex-wrap items-center justify-between gap-3 px-3.5 py-3`}>
          <p className="min-w-0 flex-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
            {t("contribution_account_hint")}
          </p>
          {connection?.state === "unavailable" ? (
            <StatusBanner tone="warning" className="w-full">
              {t("community_unavailable")}
            </StatusBanner>
          ) : (
            <Button
              label={t("contribution_connect")}
              variant="primary"
              size="sm"
              loading={action === "start" || (!connection && !error)}
              disabled={busy || !connection}
              onClick={() => void run("start", useCommunityStore.getState().start)}
            />
          )}
        </div>
      )}
      {connection?.disconnect_incomplete && (
        <StatusBanner tone="warning">{t("community_disconnect_incomplete")}</StatusBanner>
      )}
      {linkError && (
        <StatusBanner tone="error" role="alert">{t("contribution_browser_error")}</StatusBanner>
      )}
      {error && (
        <StatusBanner tone="error" role="alert">
          {error}
        </StatusBanner>
      )}
      {(connection?.state === "unavailable" || (!connection && !!error)) && (
        <div className="flex justify-end">
          <Button
            label={t("contribution_check")}
            variant="ghost"
            size="sm"
            disabled={busy}
            loading={action === "check"}
            leadingIcon={<ArrowPathIcon className="h-4 w-4" />}
            onClick={() => void run("check", useCommunityStore.getState().refreshConnection)}
          />
        </div>
      )}
    </div>
  );
}

export function CommunityAccountDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const connection = useCommunityStore((state) => state.connection);
  return (
    <ResourceDialog title={t("community_account")} width="sm" account onClose={onClose}>
      <CommunityConnection />
      {connection?.state === "connected" && (
        <details className="text-xs text-slate-500 dark:text-slate-400">
          <DisclosureSummary className="py-1">{t("community_login_details")}</DisclosureSummary>
          <p className="pt-2 leading-5">
            {t(connection.persistent ? "community_remembered" : "community_session_only")}
          </p>
        </details>
      )}
    </ResourceDialog>
  );
}

export default function CommunityAccountSetting() {
  const { t } = useI18n();
  const connection = useCommunityStore((state) => state.connection);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    void useCommunityStore.getState().refreshConnection();
  }, []);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t panel-divider pt-5">
      <div className="grid gap-1">
        <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
          {t("community_account")}
        </span>
        <span className="break-words text-xs text-slate-500 dark:text-slate-400">
          {connection?.state === "connected" ? connection.display_name : t("community_disconnected")}
        </span>
      </div>
      <Button
        label={t(connection?.state === "connected" ? "community_manage" : "contribution_connect")}
        onClick={() => setOpen(true)}
      />
      {open && <CommunityAccountDialog onClose={() => setOpen(false)} />}
    </div>
  );
}
