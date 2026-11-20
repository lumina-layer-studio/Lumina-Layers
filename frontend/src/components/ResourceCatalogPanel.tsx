import type { PersonalFilter } from "../api/community";
import { useEffect, useState } from "react";
import type { ResourceKind, ResourceSource } from "../api/resources";
import { useI18n } from "../i18n/context";
import { useResourceStore } from "../stores/resourceStore";
import MaterialCloudSyncPanel from "./MaterialCloudSyncPanel";
import LutCloudSyncPanel from "./LutCloudSyncPanel";
import OfflineResourceCatalog from "./OfflineResourceCatalog";
import Button from "./ui/Button";
import ResourceSourceSetting from "./ResourceSourceSetting";
import { catalogSourceLabel } from "../utils/resourcePresentation";
import { EMPTY_RESOURCE_FILTERS } from "../utils/resourceSearch";

export function ResourceCatalogSourceControls({
  kind,
  source: controlledSource,
  onSourceChange,
  open: controlledOpen,
  onOpenChange,
  inlineBar = false,
}: {
  kind: ResourceKind;
  source?: ResourceSource;
  onSourceChange?: (value: ResourceSource) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  inlineBar?: boolean;
}) {
  const { t } = useI18n();
  const pageSource = useResourceStore((state) => state.catalogSource[kind]);
  const setPageSource = useResourceStore((state) => state.setCatalogSource);
  const storeDialogKind = useResourceStore((state) => state.sourceDialogKind);
  const setSourceDialogKind = useResourceStore((state) => state.setSourceDialogKind);
  const library = useResourceStore((state) => state.status?.[kind]);
  const sourceMode = useResourceStore((state) => state.status?.source_settings?.mode);
  const sourceUrl = useResourceStore((state) => state.status?.source_settings?.urls[kind]);
  const health = useResourceStore((state) => state.catalogHealth[kind]);
  const refresh = useResourceStore((state) => state.refresh);

  useEffect(() => {
    if (!useResourceStore.getState().status) void refresh();
  }, [refresh]);

  const source = controlledSource ?? pageSource;
  const setSource = onSourceChange ?? ((value: ResourceSource) => setPageSource(kind, value));
  const dialogOpen = controlledOpen ?? storeDialogKind === kind;
  const setDialogOpen =
    onOpenChange ?? ((next: boolean) => setSourceDialogKind(next ? kind : null));

  const hasOffline = Boolean(library?.seed.available);
  const isDisabled = library?.configured === false;
  const currentHealth = health && sourceUrl && health.sourceUrl === sourceUrl ? health : null;
  const catalogLabel = t(catalogSourceLabel(sourceMode, library?.provider));
  const statusLabel = t(catalogSourceLabel(sourceMode, library?.provider, library?.configured));
  const statusDotClass = isDisabled
    ? "bg-slate-400 dark:bg-slate-500"
    : currentHealth?.state === "error"
      ? "bg-red-500"
      : currentHealth?.state === "cached"
        ? "bg-amber-500"
        : currentHealth?.state === "ready"
          ? "bg-emerald-500"
          : "bg-slate-400 dark:bg-slate-500";
  const active = hasOffline && isDisabled ? "offline" : source;

  const sourceSelector =
    hasOffline || source === "offline" ? (
      <div className="inline-flex items-center gap-0.5 rounded-lg bg-[var(--surface-well)] p-0.5">
        <Button
          label={catalogLabel}
          variant="ghost"
          size="sm"
          active={active === "cloud"}
          disabled={isDisabled}
          onClick={() => setSource("cloud")}
        />
        <Button
          label={t("resources_offline_catalog")}
          variant="ghost"
          size="sm"
          active={active === "offline"}
          onClick={() => setSource("offline")}
        />
      </div>
    ) : (
      <span className="inline-flex min-h-8 items-center gap-2 px-1 text-xs font-medium text-slate-600 dark:text-slate-300">
        <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${statusDotClass}`} />
        {statusLabel}
      </span>
    );

  if (!inlineBar) {
    return (
      <div
        role="group"
        aria-label={t("resources_catalog_source")}
        data-testid="catalog-source-bar"
        className="flex shrink-0 items-center gap-1.5 text-xs"
      >
        <span aria-hidden="true" className="mx-0.5 h-4 border-l panel-divider" />
        {sourceSelector}
        <ResourceSourceSetting compact kind={kind} open={dialogOpen} onOpenChange={setDialogOpen} />
      </div>
    );
  }

  return (
    <div
      role="group"
      aria-label={t("resources_catalog_source")}
      className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b panel-divider px-4 py-2"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">{sourceSelector}</div>
      <ResourceSourceSetting compact kind={kind} open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}

export default function ResourceCatalogPanel({
  kind,
  initialSource,
  initialPersonalFilter = "all",
  initialQuery = "",
  hideSourceBar = false,
  onQueryChange,
  onInstalled,
}: {
  kind: ResourceKind;
  initialSource?: ResourceSource;
  initialPersonalFilter?: PersonalFilter;
  initialQuery?: string;
  hideSourceBar?: boolean;
  onQueryChange?: (query: string) => void;
  onInstalled?: () => void | Promise<unknown>;
}) {
  const [pickerSource, setPickerSource] = useState(initialSource);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [query, setQuery] = useState(initialQuery);
  const [filters, setFilters] = useState(EMPTY_RESOURCE_FILTERS);
  const filterProps = { filters, onFiltersChange: setFilters };
  const changeQuery = (value: string) => {
    setQuery(value);
    onQueryChange?.(value);
  };
  const pageSource = useResourceStore((state) => state.catalogSource[kind]);
  const setPageSource = useResourceStore((state) => state.setCatalogSource);
  const setSourceDialogKind = useResourceStore((state) => state.setSourceDialogKind);
  const source = pickerSource ?? pageSource;
  const setSource = (value: ResourceSource) => {
    if (initialSource) setPickerSource(value);
    else setPageSource(kind, value);
  };
  const library = useResourceStore((state) => state.status?.[kind]);
  const generation = useResourceStore((state) => state.generation);
  const refresh = useResourceStore((state) => state.refresh);

  useEffect(() => {
    const update = () => {
      void refresh();
    };
    update();
    window.addEventListener("focus", update);
    return () => window.removeEventListener("focus", update);
  }, [refresh]);

  const hasOffline = Boolean(library?.seed.available);
  const isDisabled = library?.configured === false;
  const active = hasOffline && isDisabled ? "offline" : source;
  const openSourceSettings = () => {
    if (hideSourceBar) setSourceDialogKind(kind);
    else setSourceOpen(true);
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      {!hideSourceBar && (
        <ResourceCatalogSourceControls
          kind={kind}
          source={source}
          onSourceChange={setSource}
          open={sourceOpen}
          onOpenChange={setSourceOpen}
          inlineBar
        />
      )}
      <div key={`${kind}:${generation}`} className="min-h-0 flex-1">
        {active === "offline" ? (
          <OfflineResourceCatalog
            {...filterProps}
            key={kind}
            kind={kind}
            initialQuery={query}
            onQueryChange={changeQuery}
            onInstalled={onInstalled}
          />
        ) : kind === "materials" ? (
          <MaterialCloudSyncPanel
            initialPersonalFilter={initialPersonalFilter}
            {...filterProps}
            initialQuery={query}
            onQueryChange={changeQuery}
            onBrowseOffline={hasOffline ? () => setSource("offline") : undefined}
            onOpenSourceSettings={openSourceSettings}
            onInstalled={onInstalled}
          />
        ) : (
          <LutCloudSyncPanel
            initialPersonalFilter={initialPersonalFilter}
            {...filterProps}
            initialQuery={query}
            onQueryChange={changeQuery}
            onBrowseOffline={hasOffline ? () => setSource("offline") : undefined}
            onOpenSourceSettings={openSourceSettings}
            onInstalled={onInstalled}
          />
        )}
      </div>
    </div>
  );
}
