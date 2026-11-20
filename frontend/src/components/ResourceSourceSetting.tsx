import { useEffect, useId, useState } from "react";
import { AdjustmentsHorizontalIcon, CheckCircleIcon } from "@heroicons/react/24/outline";
import {
  checkResourceSource,
  saveResourceSource,
  type ResourceKind,
  type ResourceSourceSettings,
  type ResourceStatus,
} from "../api/resources";
import { apiErrorToVisibleMessage } from "../api/client";
import { useResourceStore } from "../stores/resourceStore";
import { useI18n } from "../i18n/context";
import { catalogSourceLabel } from "../utils/resourcePresentation";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import ResourceDialog from "./ui/ResourceDialog";
import DisclosureSummary from "./ui/DisclosureSummary";
import {
  cx,
  StatusBanner,
  wellClass,
  workstationFieldLabelClass,
  workstationInputClass,
} from "./ui/panelPrimitives";

function sourceStateBadgeClass(state: "ready" | "cached" | "error" | "idle"): string {
  if (state === "ready") {
    return "bg-emerald-500/12 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300";
  }
  if (state === "cached") {
    return "bg-amber-500/12 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300";
  }
  if (state === "error") {
    return "bg-red-500/12 text-red-700 dark:bg-red-400/15 dark:text-red-300";
  }
  return "bg-slate-500/12 text-slate-600 dark:bg-slate-400/15 dark:text-slate-300";
}

export default function ResourceSourceSetting({
  compact = false,
  kind = "materials",
  open: controlledOpen,
  onOpenChange,
}: {
  compact?: boolean;
  kind?: ResourceKind;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const [internalOpen, setInternalOpen] = useState(false);
  const open = controlledOpen ?? internalOpen;
  const setOpen = (next: boolean) => {
    if (controlledOpen === undefined) setInternalOpen(next);
    onOpenChange?.(next);
  };
  const status = useResourceStore((state) => state.status);
  const refresh = useResourceStore((state) => state.refresh);

  useEffect(() => {
    if (!status) void refresh();
  }, [status, refresh]);

  const button = (
    <Button
      label={t("resources_source_settings")}
      variant={compact ? "ghost" : "secondary"}
      size="sm"
      leadingIcon={
        compact ? <AdjustmentsHorizontalIcon className="h-4 w-4" aria-hidden="true" /> : undefined
      }
      onClick={() => setOpen(true)}
    />
  );

  return (
    <>
      {compact ? (
        button
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t panel-divider pt-5">
          <div className="grid min-w-0 gap-1">
            <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
              {t("resources_catalog_source")}
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {t(
                catalogSourceLabel(
                  status?.source_settings?.mode,
                  status?.[kind].provider,
                  status?.[kind].configured,
                ),
              )}
            </span>
          </div>
          {button}
        </div>
      )}
      {open && <SourceDialog kind={kind} onClose={() => setOpen(false)} />}
    </>
  );
}

function defaultSourceLabel(kind: ResourceKind, status: ResourceStatus | null): string {
  if (!status?.source_settings) return "resources_source_default";
  const settings = status.source_settings;
  const defaultUrl = settings.default_urls[kind];
  if (!defaultUrl) return "resources_source_default_disabled";

  const activeProvider = settings.urls[kind] === defaultUrl ? status[kind].provider : undefined;
  // The API reports the material default's provider. It also applies to LUTs
  // that use the same default URL.
  const sharedProvider = settings.default_urls.materials === defaultUrl ? settings.default_provider : undefined;
  switch (activeProvider ?? sharedProvider) {
    case "github": return "resources_source_default_github";
    case "registry": return "resources_source_default_registry";
    default: return "resources_source_default";
  }
}

function SourceDialog({ kind, onClose }: { kind: ResourceKind; onClose: () => void }) {
  const { t, lang } = useI18n();
  const mirrorInputId = useId();
  const status = useResourceStore((state) => state.status);
  const health = useResourceStore((state) => state.catalogHealth[kind]);
  const loading = useResourceStore((state) => state.loading);
  const loadError = useResourceStore((state) => state.error);
  const settings = status?.source_settings;
  const [mode, setMode] = useState<ResourceSourceSettings["mode"]>(settings?.mode ?? "default");
  const [mirror, setMirror] = useState(settings?.mirror_url ?? "");
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const activeUrl = settings?.urls[kind] ?? "";
  const activeConfigured = Boolean(activeUrl);
  const changed =
    mode !== settings?.mode ||
    (mode === "mirror" && mirror.trim().replace(/\/+$/, "") !== settings?.mirror_url);
  const currentHealth = health && activeConfigured && health.sourceUrl === activeUrl ? health : null;
  const date = currentHealth?.fetchedAt ? new Date(currentHealth.fetchedAt) : null;

  useEffect(() => {
    if (settings) {
      setMode(settings.mode);
      setMirror(settings.mirror_url);
    }
  }, [settings]);

  useEffect(() => {
    void useResourceStore.getState().refresh();
  }, []);

  const healthState: "ready" | "cached" | "error" | "idle" = currentHealth?.state ?? "idle";
  const dotTone =
    healthState === "ready"
      ? "bg-emerald-500"
      : healthState === "cached"
        ? "bg-amber-500"
        : healthState === "error"
          ? "bg-red-500"
          : "bg-slate-400 dark:bg-slate-500";

  return (
    <ResourceDialog
      title={t("resources_source_settings")}
      width="sm"
      busy={busy || checking}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        if (busy || !changed || !settings) return;
        setBusy(true);
        setError("");
        setSaved(false);
        void saveResourceSource(mode, mirror)
          .then((value) => {
            useResourceStore.getState().sourceChanged(value);
            setSaved(true);
          })
          .catch((err) => setError(apiErrorToVisibleMessage(err, t("resources_source_save_failed"))))
          .finally(() => setBusy(false));
      }}
      footer={
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-h-5">
            {saved && (
              <span
                role="status"
                className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-600 dark:text-emerald-400"
              >
                <CheckCircleIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {t("resources_source_saved")}
              </span>
            )}
          </div>
          <Button
            label={t("resources_source_apply")}
            variant="primary"
            type="submit"
            loading={busy}
            disabled={
              checking ||
              !settings ||
              !changed ||
              (mode === "mirror" && !mirror.trim()) ||
              !!settings.error
            }
          />
        </div>
      }
    >
      <Dropdown
        label={t("resources_catalog_source")}
        value={mode}
        onChange={(value) => {
          setMode(value as typeof mode);
          setSaved(false);
        }}
        disabled={busy || checking || !settings}
        options={[
          {
            value: "default",
            label: t(defaultSourceLabel(kind, status)),
          },
          { value: "github", label: t("resources_github_catalog") },
          { value: "mirror", label: t("resources_source_custom") },
        ]}
      />
      {mode === "mirror" && (
        <div className="flex min-w-0 flex-col gap-1.5">
          <label htmlFor={mirrorInputId} className={workstationFieldLabelClass}>
            {t("resources_source_address")}
          </label>
          <input
            id={mirrorInputId}
            type="url"
            name="mirror_url"
            autoComplete="url"
            autoCorrect="off"
            autoCapitalize="none"
            spellCheck={false}
            className={`${workstationInputClass} w-full min-w-0 font-mono text-xs sm:text-sm`}
            value={mirror}
            required
            maxLength={2048}
            disabled={busy || checking}
            onChange={(event) => {
              setMirror(event.target.value);
              setSaved(false);
            }}
            placeholder={t("resources_source_example")}
          />
        </div>
      )}
      <div
        className={`${wellClass} flex flex-wrap items-center justify-between gap-3 px-3.5 py-3`}
        role="status"
      >
        <div className="min-w-0 flex-1 space-y-1.5 text-xs">
          <div className="flex flex-wrap items-center gap-2 font-medium text-slate-800 dark:text-slate-100">
            <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${dotTone}`} />
            <span>
              {t(
                catalogSourceLabel(
                  settings?.mode,
                  status?.[kind].provider,
                  settings ? activeConfigured : undefined,
                ),
              )}
            </span>
            <span
              className={cx(
                "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium",
                sourceStateBadgeClass(healthState),
              )}
            >
              {t(
                currentHealth
                  ? `resources_source_state_${currentHealth.state}`
                  : loading
                    ? "resources_source_loading"
                    : settings && !activeConfigured
                      ? "resources_source_unconfigured"
                      : "resources_source_unchecked",
              )}
            </span>
          </div>
          {date && Number.isFinite(date.getTime()) && (
            <p className="pl-4 text-[11px] text-slate-500 dark:text-slate-400">
              {t("resources_source_checked_at")}{" "}
              <time dateTime={date.toISOString()}>
                {date.toLocaleString(lang === "zh" ? "zh-CN" : "en-US")}
              </time>
            </p>
          )}
          {changed ? (
            <p className="pl-4 text-[11px] leading-5 text-slate-500 dark:text-slate-400">
              {t("resources_source_pending_apply")}
            </p>
          ) : settings && !activeConfigured ? (
            <p className="pl-4 text-[11px] leading-5 text-slate-500 dark:text-slate-400">
              {t("resources_source_disabled_hint")}
            </p>
          ) : null}
        </div>
        {(!settings || activeConfigured) && (
          <Button
            label={t("resources_source_check")}
            variant="secondary"
            size="sm"
            disabled={busy || !settings || changed || !activeConfigured}
            loading={checking}
            onClick={() => {
              if (!settings || !activeUrl) return;
              setChecking(true);
              setError("");
              void checkResourceSource(kind, activeUrl)
                .then((value) => useResourceStore.getState().observeCatalog(kind, value))
                .catch((err) => {
                  useResourceStore
                    .getState()
                    .observeCatalog(kind, { sourceUrl: activeUrl, state: "error" });
                  setError(apiErrorToVisibleMessage(err, t("resources_source_check_failed")));
                })
                .finally(() => setChecking(false));
            }}
          />
        )}
      </div>
      <details className="min-w-0 text-xs text-slate-500 dark:text-slate-400">
        <DisclosureSummary className="py-1">{t("resources_source_addresses")}</DisclosureSummary>
        <dl className={`${wellClass} mt-2 grid gap-2.5 px-3 py-2.5`}>
          {(["materials", "luts"] as const).map((family) => (
            <div key={family} className="grid min-w-0 gap-0.5">
              <dt className="text-[11px] font-medium text-slate-600 dark:text-slate-300">
                {t(family === "materials" ? "resources_materials" : "resources_luts")}
              </dt>
              <dd className="select-text break-all font-mono text-[11px] text-slate-500 dark:text-slate-400">
                {settings?.urls[family] || t("resources_source_unconfigured")}
              </dd>
            </div>
          ))}
        </dl>
      </details>
      {(error || loadError) && <StatusBanner tone="error">{error || loadError}</StatusBanner>}
      {settings?.error && (
        <StatusBanner tone="error">{t("resources_source_invalid_settings")}</StatusBanner>
      )}
    </ResourceDialog>
  );
}
