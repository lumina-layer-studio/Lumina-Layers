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

export default function ResourceCatalogPanel({
  kind,
  initialSource,
  initialPersonalFilter = "all",
  initialQuery = "",
  onQueryChange,
  onInstalled,
}: {
  kind: ResourceKind;
  initialSource?: ResourceSource;
  initialPersonalFilter?: PersonalFilter;
  initialQuery?: string;
  onQueryChange?: (query: string) => void;
  onInstalled?: () => void | Promise<unknown>;
}) {
  const { t } = useI18n();
  const [pickerSource, setPickerSource] = useState(initialSource);
  const [query, setQuery] = useState(initialQuery);
  const [filters, setFilters] = useState(EMPTY_RESOURCE_FILTERS);
  const filterProps = { filters, onFiltersChange: setFilters };
  const changeQuery = (value: string) => {
    setQuery(value);
    onQueryChange?.(value);
  };
  const pageSource = useResourceStore((state) => state.catalogSource[kind]);
  const setPageSource = useResourceStore((state) => state.setCatalogSource);
  const source = pickerSource ?? pageSource;
  const setSource = (value: ResourceSource) => {
    if (initialSource) setPickerSource(value);
    else setPageSource(kind, value);
  };
  const library = useResourceStore((state) => state.status?.[kind]);
  const sourceMode = useResourceStore((state) => state.status?.source_settings?.mode);
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
  const catalogLabel = t(catalogSourceLabel(sourceMode, library?.provider));
  const active = hasOffline && library?.configured === false ? "offline" : source;

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div
        role="group"
        aria-label={t("resources_catalog_source")}
        className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b panel-divider px-4 py-2"
      >
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {hasOffline || source === "offline" ? (
            <div className="inline-flex items-center gap-0.5 rounded-lg bg-[var(--surface-well)] p-0.5">
              <Button
                label={catalogLabel}
                variant="ghost"
                size="sm"
                active={active === "cloud"}
                disabled={library?.configured === false}
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
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              {catalogLabel}
            </span>
          )}
        </div>
        <ResourceSourceSetting compact kind={kind} />
      </div>
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
            onInstalled={onInstalled}
          />
        ) : (
          <LutCloudSyncPanel
            initialPersonalFilter={initialPersonalFilter}
            {...filterProps}
            initialQuery={query}
            onQueryChange={changeQuery}
            onBrowseOffline={hasOffline ? () => setSource("offline") : undefined}
            onInstalled={onInstalled}
          />
        )}
      </div>
    </div>
  );
}
