import { useEffect, useId, useState } from "react";
import { AdjustmentsHorizontalIcon, CheckCircleIcon } from "@heroicons/react/24/outline";
import {
  checkResourceSource,
  saveResourceSource,
  type ResourceKind,
  type ResourceSourceSettings,
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
  StatusBanner,
  wellClass,
  workstationFieldLabelClass,
  workstationInputClass,
} from "./ui/panelPrimitives";

export default function ResourceSourceSetting({
  compact = false,
  kind = "materials",
}: {
  compact?: boolean;
  kind?: ResourceKind;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
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
              {t(catalogSourceLabel(status?.source_settings?.mode, status?.[kind].provider))}
            </span>
          </div>
          {button}
        </div>
      )}
      {open && <SourceDialog kind={kind} onClose={() => setOpen(false)} />}
    </>
  );
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

  const changed =
    mode !== settings?.mode ||
    (mode === "mirror" && mirror.trim().replace(/\/+$/, "") !== settings?.mirror_url);
  const currentHealth = health && health.sourceUrl === settings?.urls[kind] ? health : null;
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

  const dotTone =
    currentHealth?.state === "ready"
      ? "bg-emerald-500"
      : currentHealth?.state === "cached"
        ? "bg-amber-500"
        : currentHealth?.state === "error"
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
            label: t(
              settings?.default_provider === "registry"
                ? "resources_source_default_hosted"
                : "resources_source_default_github",
            ),
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
        <div className="min-w-0 flex-1 space-y-1 text-xs">
          <div className="flex flex-wrap items-center gap-2 font-medium text-slate-800 dark:text-slate-100">
            <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${dotTone}`} />
            <span>
              {t(catalogSourceLabel(settings?.mode, status?.[kind].provider))}
            </span>
            <span className="font-normal text-slate-500 dark:text-slate-400">
              {t(
                currentHealth
                  ? `resources_source_state_${currentHealth.state}`
                  : loading
                    ? "resources_source_loading"
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
        </div>
        <Button
          label={t("resources_source_check")}
          variant="secondary"
          size="sm"
          disabled={busy || !settings || changed || !settings.urls[kind]}
          loading={checking}
          onClick={() => {
            if (!settings) return;
            setChecking(true);
            setError("");
            void checkResourceSource(kind, settings.urls[kind])
              .then((value) => useResourceStore.getState().observeCatalog(kind, value))
              .catch((err) => {
                useResourceStore
                  .getState()
                  .observeCatalog(kind, { sourceUrl: settings.urls[kind], state: "error" });
                setError(apiErrorToVisibleMessage(err, t("resources_source_check_failed")));
              })
              .finally(() => setChecking(false));
          }}
        />
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
