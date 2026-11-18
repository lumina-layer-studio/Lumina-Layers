import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchOfflineCatalog, installOfflineResource, type OfflineResource, type ResourceKind } from "../api/resources";
import { useFilamentMarket } from "../hooks/useFilamentMarket";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import { filamentIdentity, materialDisplayName } from "../utils/filamentIdentity";
import { buildResourceSearch, filterResources, resourceFacets, hasResourceFilters, EMPTY_RESOURCE_FILTERS } from "../utils/resourceSearch";
import { useResourceFilters, type ResourceFilterProps } from "../hooks/useResourceFilters";
import ResourceCatalogFilters from "./ui/ResourceCatalogFilters";
import ResourceCatalogToolbar from "./ui/ResourceCatalogToolbar";
import { localLutIdentity } from "../utils/libraryFilamentIdentity";
import { resourceColorMode } from "../utils/resourcePresentation";
import Button from "./ui/Button";
import CloudLibraryPreview from "./ui/CloudLibraryPreview";
import { LibraryFields, LibraryIdentity } from "./ui/LibraryDetails";
import Pagination from "./ui/Pagination";
import TransientBanner from "./ui/TransientBanner";
import { StatusBanner } from "./ui/panelPrimitives";
import { resolvePageCount } from "./ui/paginationModel";
import { useCatalogPagination } from "../hooks/useCatalogPagination";

const entryKey = (item: OfflineResource) => JSON.stringify([item.resource_id, item.revision_id]);

function offlineError(error: unknown): string {
  const status = (error as { response?: { status?: number } })?.response?.status;
  if (status === 404) return "resources_seed_missing";
  if (status === 409) return "resources_offline_busy";
  if (status === 422) return "resources_seed_damaged";
  return "resources_offline_failed";
}

export default function OfflineResourceCatalog({ kind, initialQuery = "", onQueryChange, onInstalled, ...filterProps }: {
  kind: ResourceKind;
  initialQuery?: string;
  onQueryChange?: (query: string) => void;
  onInstalled?: () => void | Promise<unknown>;
} & ResourceFilterProps) {
  const { t, lang } = useI18n();
  const market = useFilamentMarket();
  const [items, setItems] = useState<OfflineResource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [query, setQuery] = useState(initialQuery);
  const changeQuery = (value: string) => {
    setPage(1);
    setQuery(value);
    onQueryChange?.(value);
  };
  const { page, pageSize, setPage, resizePage, navigationKey } = useCatalogPagination();
  const [filters, setFilters] = useResourceFilters(filterProps, () => setPage(1));
  const request = useRef(0);
  const mounted = useRef(false);

  const load = useCallback(async () => {
    const current = ++request.current;
    setError(null);
    setLoading(true);
    try {
      const catalog = await fetchOfflineCatalog(kind);
      if (request.current === current) setItems(catalog.items);
    } catch (cause) {
      if (request.current === current) setError(offlineError(cause));
    } finally {
      if (request.current === current) setLoading(false);
    }
  }, [kind]);

  useEffect(() => {
    const req = request;
    mounted.current = true;
    void load();
    return () => { mounted.current = false; req.current++; };
  }, [load]);

  const indexed = useMemo(() => items.map((item) => {
    const identity = kind === "luts" ? localLutIdentity(item.brand ?? undefined, item.name, lang, item.display, market)
      : materialDisplayName(filamentIdentity(item.brand, item.name, lang, item.display, market));
    return { item, identity, key: entryKey(item), search: buildResourceSearch({ identity, kind, name: item.name,
      display: item.display, mode: item.color_mode, materialType: item.material_type, rgb: item.rgb, language: lang, market }) };
  }), [items, kind, lang, market]);
  const rows = useMemo(() => filterResources(indexed, query, filters), [indexed, query, filters]);
  const facets = useMemo(() => resourceFacets(indexed, query, filters), [indexed, query, filters]);
  const pageCount = resolvePageCount(rows.length, pageSize);
  const currentPage = Math.min(page, pageCount);

  const install = async (item: OfflineResource, name: string) => {
    const key = entryKey(item);
    setInstalling(key);
    setError(null);
    setAdded(null);
    try {
      await installOfflineResource(kind, item);
      if (mounted.current) {
        setItems((previous) => previous.map((row) => entryKey(row) === key ? { ...row, installed: true } : row));
        setAdded(name);
      }
      await onInstalled?.();
    } catch (cause) {
      if (mounted.current) setError(offlineError(cause));
    } finally {
      if (mounted.current) setInstalling(null);
    }
  };

  return <CloudLibraryPreview
    resetKey={`${query}:${JSON.stringify(filters)}:${navigationKey}`} busy={loading} loadingMessage={t("resources_offline_loading")}
    onColumnsChange={(columns, anchor) => resizePage(columns, anchor, currentPage)}
    toolbar={<ResourceCatalogToolbar query={query} searchLabel={t("resources_offline_search")} onQueryChange={changeQuery}>
      <ResourceCatalogFilters kind={kind} facets={facets} filters={filters} onChange={setFilters} complete={!loading} />
    </ResourceCatalogToolbar>}
    emptyMessage={error ? "" : t(query.trim() || hasResourceFilters(filters) ? "resources_no_matches" : "resources_offline_empty")}
    emptyAction={!error && (query.trim() || hasResourceFilters(filters)) && <Button label={t(hasResourceFilters(filters) ? "resources_clear_filters" : "resources_clear_search")} onClick={() => { changeQuery(""); setFilters(EMPTY_RESOURCE_FILTERS); }} />}
    notices={<>
      {error && <StatusBanner tone="error" action={<Button label={t("resources_retry")} onClick={() => void load()} />}>{t(error)}</StatusBanner>}
      <TransientBanner message={added ? tRuntime("resources_added_named", { name: added }) : null} onDismiss={() => setAdded(null)} />
    </>}
    footer={<><span className="text-xs text-slate-500 dark:text-slate-400">{t("cloud_library_results_count").replace("{count}", String(rows.length))}</span>
      {pageCount > 1 && <Pagination page={currentPage} pageCount={pageCount} onPageChange={setPage} />}</>}
    items={rows.slice((currentPage - 1) * pageSize, currentPage * pageSize).map(({ item, key, identity }) => {
      const subtitle = [identity.brand, item.material_type || identity.materialType].filter(Boolean).join(" · ");
      const thumbnail = { kind, resourceKey: key, rgb: item.rgb, display: item.display, mode: item.color_mode, name: item.name };
      const state = t(item.installed ? "resources_local_available" : "resources_in_bundle");
      const action = item.installed ? undefined : <Button label={t("resources_add_local")}
        disabled={installing !== null} loading={installing === key} onClick={() => void install(item, identity.name)} />;
      return { key, name: identity.name, originalName: identity.originalName, subtitle, logo: identity.logo, thumbnail,
        metric: resourceColorMode(item.color_mode, lang) || undefined, colorDescription: identity.colorDescription, state: item.installed ? state : undefined, action,
        detail: <div className="flex flex-col gap-4">
          <LibraryIdentity {...identity} subtitle={subtitle} thumbnail={thumbnail} />
          <div className="border-t panel-divider pt-3.5">
            <LibraryFields rows={[
              ...(item.color_mode ? [{ label: t("lut_library_color_mode_label"), value: resourceColorMode(item.color_mode, lang) }] : []),
              { label: t("mat_sync_catalog_state_label"), value: state },
            ]} />
          </div>
          {action && <div className="border-t panel-divider pt-4 [&>button]:w-full">{action}</div>}
        </div> };
    })} />;
}
