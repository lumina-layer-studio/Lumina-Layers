import { useResourceActivity } from "../hooks/useResourceActivity";
import ResourceFeedback from "./ResourceFeedback";
import { useCatalogHealth, catalogCheckedTime } from "../hooks/useCatalogHealth";
import TransientBanner from "./ui/TransientBanner";
import { LibraryIdentity, LibraryFields } from "./ui/LibraryDetails";
import CloudLibraryPreview from "./ui/CloudLibraryPreview";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiErrorToVisibleMessage } from "../api/client";
import {
  fetchCloudLutRegistryCatalog,
  fetchCloudLutRegistryStatus,
  fetchCloudLutPreviews,
  installCloudLut,
  restoreCloudLutRevision,
} from "../api/lut";
import type {
  CloudLutRegistryCatalogItem,
  CloudLutRegistryCatalogResponse,
  CloudLutRegistryStatusResponse,
} from "../api/types";
import { useI18n } from "../i18n/context";
import { useFilamentMarket } from "../hooks/useFilamentMarket";
import { buildResourceSearch, filterResources, resourceFacets, hasResourceFilters, EMPTY_RESOURCE_FILTERS } from "../utils/resourceSearch";
import { useResourceFilters, type ResourceFilterProps } from "../hooks/useResourceFilters";
import ResourceCatalogFilters from "./ui/ResourceCatalogFilters";
import { localLutIdentity } from "../utils/libraryFilamentIdentity";
import { resourceColorMode } from "../utils/resourcePresentation";
import Button from "./ui/Button";
import { StatusBanner } from "./ui/panelPrimitives";
import Pagination from "./ui/Pagination";
import { resolvePageCount } from "./ui/paginationModel";
import { useCatalogPagination } from "../hooks/useCatalogPagination";
import { CommunityFilter, CommunityNotice, ResourceActivityActions } from "./ui/ResourceActivity";
import { ArrowPathIcon, ClockIcon } from "@heroicons/react/24/outline";
import ResourceCatalogToolbar, { ResourceInstallFilters } from "./ui/ResourceCatalogToolbar";
import type { PersonalFilter } from "../api/community";
import { useCommunityStore } from "../stores/communityStore";
import ResourceHistoryDialog from "./ui/ResourceHistoryDialog";
import { CATALOG_FILTERS, formatBytes, type CatalogFilter } from "./materialCloud/catalogModel";

const CLOUD_LUT_PAGE_SIZE = 100;
const previewKey = (scope: string, row: { lut_id: string; revision_id: string; content_hash: string }) =>
  JSON.stringify([scope, row.lut_id, row.revision_id, row.content_hash]);

type CloudLutInstallState = "not_installed" | "installed" | "local_available" | "update_available" | "local_missing" | "local_modified";

const emptyCloudLutCatalog = (
  status: CloudLutRegistryStatusResponse | null,
): CloudLutRegistryCatalogResponse => ({
  configured: status?.configured ?? false,
  channels: status?.channels ?? [],
  items: [],
  total: 0,
});

const readDisplayString = (
  display: Record<string, unknown> | null | undefined,
  keys: string[],
): string | null => {
  if (!display) {
    return null;
  }
  for (const key of keys) {
    const value = display[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
};

const normalizeRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;

const catalogItemKey = (entry: CloudLutRegistryCatalogItem): string =>
  `${entry.lut_id}:${entry.revision_id}`;

const accessDenied = (error: unknown) =>
  [401, 403].includes((error as { response?: { status: number } })?.response?.status ?? 0);

const resolveCatalogInstallState = (
  entry: CloudLutRegistryCatalogItem,
): CloudLutInstallState => {
  if (entry.local_state === "installed") {
    return "installed";
  }
  if (entry.local_state === "update_available" || entry.local_state === "local_missing" || entry.local_state === "local_modified") return entry.local_state;
  if (entry.local_state === "local_available" || entry.local_exists === true) {
    return "local_available";
  }
  return "not_installed";
};

const resolveLocalPath = (entry: CloudLutRegistryCatalogItem): string | null =>
  ["installed", "local_available"].includes(resolveCatalogInstallState(entry))
    ? entry.installed_path || entry.local_match_path || null : null;

const matchesInstallFilter = (state: CloudLutInstallState, filter: CatalogFilter) =>
  filter === "all" || (filter === "updates" ? state === "update_available"
    : filter === "installed" ? state === "installed" || state === "local_available"
    : state === "not_installed" || state === "local_missing" || state === "local_modified");

const mergeCatalogPage = (
  current: CloudLutRegistryCatalogResponse | null,
  nextPage: CloudLutRegistryCatalogResponse,
): CloudLutRegistryCatalogResponse => {
  if (!current) {
    return nextPage;
  }
  const existing = new Set(current.items.map(catalogItemKey));
  const appended = nextPage.items.filter((entry) => !existing.has(catalogItemKey(entry)));
  return {
    ...nextPage,
    cached: current.cached || nextPage.cached,
    channels: nextPage.channels.length > 0 ? nextPage.channels : current.channels,
    items: [...current.items, ...appended],
    total: nextPage.total ?? current.total,
  };
};

export default function LutCloudSyncPanel({ initialPersonalFilter = "all", initialQuery = "", onQueryChange, onBrowseOffline, onInstalled, ...filterProps }: {
  initialPersonalFilter?: PersonalFilter;
  initialQuery?: string;
  onQueryChange?: (query: string) => void;
  onBrowseOffline?: () => void;
  onInstalled?: () => void | Promise<unknown>;
} & ResourceFilterProps = {}) {
  const { t, lang } = useI18n();
  const market = useFilamentMarket();
  const [personalFilter, setPersonalFilter] = useState<PersonalFilter>(initialPersonalFilter);
  const [installFilter, setInstallFilter] = useState<CatalogFilter>("all");
  const [showHistory, setShowHistory] = useState(false);
  const [historyLut, setHistoryLut] = useState<string | null>(null);
  const [pendingRestore, setPendingRestore] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const myActivity = useCommunityStore((state) => state.mine.luts);
  const [status, setStatus] = useState<CloudLutRegistryStatusResponse | null>(null);
  const [catalog, setCatalog] = useState<CloudLutRegistryCatalogResponse | null>(null);
  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const changeQuery = (value: string) => {
    setSearchQuery(value);
    setPage(1);
    onQueryChange?.(value);
  };
  const { page, pageSize, setPage, resizePage, navigationKey } = useCatalogPagination();
  const [filters, setFilters] = useResourceFilters(filterProps, () => setPage(1));
  const [boards, setBoards] = useState(() => new Map<string, Record<string, unknown>>());
  const [previewError, setPreviewError] = useState(false);
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [pendingInstall, setPendingInstall] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const offset = useRef(0);

  const loadCatalogAndStatus = useCallback(async (refresh = false) => {
    const request = ++generation.current;
    setIsLoading(true);
    setIsLoadingMore(false);
    setError(null);
    setNotice(null);
    try {
      const statusResponse = await fetchCloudLutRegistryStatus();
      if (request !== generation.current) return false;
      setStatus(statusResponse);
      setCatalog((current) => current && statusResponse.source_scope && current.source_scope !== statusResponse.source_scope ? null : current);
      if (!statusResponse.configured) {
        setCatalog(emptyCloudLutCatalog(statusResponse));
        setNotice(t("lut_sync_catalog_not_configured"));
        return false;
      }
      const catalogResponse = await fetchCloudLutRegistryCatalog({
        channels: statusResponse.channels,
        limit: CLOUD_LUT_PAGE_SIZE,
        offset: 0,
        ...(refresh ? { refresh: true } : {}),
      });
      if (request !== generation.current) return false;
      offset.current = catalogResponse.items.length;
      setCatalog(catalogResponse);
      return catalogResponse.cached !== true;
    } catch (err) {
      if (request !== generation.current) return false;
      if (accessDenied(err)) setCatalog(null);
      setError(apiErrorToVisibleMessage(err, t("lut_sync_status_failed")));
      return false;
    } finally {
      if (request === generation.current) setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadCatalogAndStatus();
    return () => { generation.current += 1; };
  }, [loadCatalogAndStatus]);

  const refreshCatalog = useCallback(async () => {
    setIsRefreshing(true);
    setSuccess(null);
    try {
      if (await loadCatalogAndStatus(true)) setSuccess(t("lut_sync_catalog_refresh_success"));
    } finally {
      setIsRefreshing(false);
    }
  }, [loadCatalogAndStatus, t]);

  const loadMoreCatalog = useCallback(async () => {
    if (!status?.configured || !catalog || isLoading || isLoadingMore) {
      return;
    }
    const loadedCount = offset.current;
    if (loadedCount >= catalog.total) {
      return;
    }
    setIsLoadingMore(true);
    const request = generation.current;
    setError(null);
    try {
      const nextPage = await fetchCloudLutRegistryCatalog({
        channels: status.channels,
        limit: CLOUD_LUT_PAGE_SIZE,
        offset: loadedCount,
      });
      if (request !== generation.current) return;
      if (nextPage.source_scope !== catalog.source_scope) {
        setCatalog(null);
        await loadCatalogAndStatus();
        return;
      }
      offset.current += nextPage.items.length;
      if (!nextPage.items.length && offset.current < nextPage.total) {
        setError(t("lut_sync_status_failed"));
        return;
      }
      setCatalog((current) => mergeCatalogPage(current, nextPage));
    } catch (err) {
      if (request !== generation.current) return;
      if (accessDenied(err)) setCatalog(null);
      setError(apiErrorToVisibleMessage(err, t("lut_sync_status_failed")));
    } finally {
      if (request === generation.current) setIsLoadingMore(false);
    }
  }, [catalog, isLoading, isLoadingMore, loadCatalogAndStatus, status, t]);

  const handleInstall = useCallback(async (entry: CloudLutRegistryCatalogItem, name: string) => {
    const installKey = catalogItemKey(entry);
    const state = resolveCatalogInstallState(entry);
    setPendingInstall(installKey);
    setError(null);
    setSuccess(null);
    try {
      const subject = useCommunityStore.getState().connection?.subject;
      const result = subject ? await installCloudLut(entry, subject) : await installCloudLut(entry);
      useCommunityStore.getState().downloaded("luts", entry.lut_id, subject, result?.activity_recorded);
      await loadCatalogAndStatus();
      await onInstalled?.();
      setSuccess(t(state === "update_available" ? "resources_updated_named"
        : state === "local_missing" || state === "local_modified" ? "resources_redownloaded_named" : "resources_added_named").replace("{name}", () => name));
    } catch (err) {
      setError(apiErrorToVisibleMessage(err, t("lut_sync_install_failed")));
    } finally {
      setPendingInstall(null);
    }
  }, [loadCatalogAndStatus, onInstalled, t]);

  const refreshHistory = async () => {
    setHistoryError(null);
    try { setStatus(await fetchCloudLutRegistryStatus()); }
    catch (cause) { setHistoryError(apiErrorToVisibleMessage(cause, t("lut_sync_status_failed"))); }
  };
  const restoreRevision = async (id: string, revision: string) => {
    setPendingRestore(`${id}:${revision}`);
    setHistoryError(null);
    setSuccess(null);
    try {
      await restoreCloudLutRevision(id, revision);
      await loadCatalogAndStatus();
      await onInstalled?.();
      setSuccess(t("mat_sync_rollback_success"));
    } catch (cause) {
      setHistoryError(apiErrorToVisibleMessage(cause, t("resources_history_failed")));
    } finally { setPendingRestore(null); }
  };
  const openHistory = (id: string | null) => {
    setHistoryLut(id);
    setHistoryError(null);
    setShowHistory(true);
    void refreshHistory();
  };

  const items = useMemo(
    () => (catalog?.items ?? []).map((entry) => {
      const display = normalizeRecord(entry.display);
      const identity = localLutIdentity(
        readDisplayString(display, ["manufacturer", "brand", "vendor"]) ?? undefined,
        readDisplayString(display, ["name", "display_name", "lut_name", "title"]) ?? entry.local_path ?? entry.lut_id,
        lang, display, market,
      );
      const compatibility = normalizeRecord(entry.compatibility) ?? {};
      const declaredModes = Array.isArray(compatibility.color_modes)
        ? [...new Set(compatibility.color_modes.filter((value): value is string => typeof value === "string" && Boolean(value.trim())).map(value => value.trim()))]
        : [];
      const mode = readDisplayString(compatibility, ["color_mode", "mode", "profile"])
        || (declaredModes.length === 1 ? declaredModes[0] : "");
      const materialType = readDisplayString(display, ["material_type", "material"]) || identity.materialType;
      const searchText = [identity.searchText, identity.colorDescription, mode, materialType, entry.lut_id,
        entry.revision_id, entry.content_hash, entry.local_path, entry.channel, entry.visibility].filter(Boolean).join(" ");
      return { entry, identity, mode, materialType, search: buildResourceSearch({ kind: "luts", identity,
        display, metadata: entry.compatibility, name: identity.originalName, mode, materialType, extra: searchText, language: lang, market }) };
    }), [catalog, lang, market],
  );
  const matchingItems = useMemo(() => filterResources(items, searchQuery, filters)
    .filter(({ entry }) => personalFilter === "all" || myActivity[entry.lut_id]?.[personalFilter]),
  [items, searchQuery, filters, personalFilter, myActivity]);
  const filteredItems = useMemo(() => matchingItems.filter(({ entry }) =>
    matchesInstallFilter(resolveCatalogInstallState(entry), installFilter)), [matchingItems, installFilter]);
  const facets = useMemo(() => resourceFacets(items, searchQuery, filters), [items, searchQuery, filters]);
  const pageCount = resolvePageCount(filteredItems.length, pageSize);
  const currentPage = Math.min(page, pageCount);
  const visibleItems = useMemo(() => filteredItems.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    [filteredItems, currentPage, pageSize]);
  const scope = catalog?.source_scope;
  useResourceActivity("luts", visibleItems.map(({ entry }) => entry.lut_id));
  const channels = status?.channels;
  useEffect(() => {
    setPreviewError(false);
    if (!scope || !channels) return;
    const missing = visibleItems.map((item) => item.entry).filter((entry) => entry.display?.lut_board_available === true
      && !entry.display?.lut_board_preview && !boards.has(previewKey(scope, entry)));
    if (!missing.length) return;
    const controller = new AbortController();
    // Coalesce a burst of search keystrokes or quick page changes.
    const timer = window.setTimeout(() => {
      void fetchCloudLutPreviews(missing.map((entry) => entry.lut_id), channels, controller.signal)
        .then((result) => {
          if (controller.signal.aborted) return;
          if (result.source_scope !== scope) { setPreviewError(true); return; }
          const previews = new Map(result.previews.map((row) => [previewKey(scope, row), row.display ?? {}]));
          if (missing.some((entry) => !previews.get(previewKey(scope, entry))?.lut_board_preview)) {
            setPreviewError(true);
            return;
          }
          setBoards((previous) => {
            const next = new Map(previous);
            for (const entry of missing) {
              const key = previewKey(scope, entry);
              next.set(key, previews.get(key) ?? {});
            }
            while (next.size > 512) next.delete(next.keys().next().value!);
            return next;
          });
        }).catch(() => { if (!controller.signal.aborted) setPreviewError(true); });
    }, 140);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [scope, channels, visibleItems, boards, previewAttempt]);

  const catalogLoadedCount = catalog?.items.length ?? 0;
  useCatalogHealth("luts", !!catalog && !isLoading, catalog?.cached, catalog?.fetched_at, error);
  const catalogTotalCount = catalog?.total ?? catalogLoadedCount;
  const hasMoreCatalogEntries = status?.configured === true && offset.current < catalogTotalCount;
  const offlineAction = onBrowseOffline
    ? <Button label={t("resources_browse_offline")} onClick={onBrowseOffline} />
    : undefined;

  // Complete the lightweight catalog before presenting search as complete.
  useEffect(() => {
    if ( hasMoreCatalogEntries && !isLoading && !isLoadingMore && !error) void loadMoreCatalog();
  }, [hasMoreCatalogEntries, isLoading, isLoadingMore, error, loadMoreCatalog]);

  return <><CloudLibraryPreview resetKey={`${searchQuery}:${JSON.stringify(filters)}:${installFilter}:${personalFilter}:${navigationKey}`} busy={isLoading}
    onColumnsChange={(columns, anchor) => resizePage(columns, anchor, currentPage)}
    toolbar={<ResourceCatalogToolbar query={searchQuery} searchLabel={t("lut_sync_search_placeholder")} onQueryChange={changeQuery}
      actions={<>
      <CommunityFilter value={personalFilter} onChange={(value) => { setPersonalFilter(value); setPage(1); }} />
      <Button label={t("mat_sync_local_section_title")} variant="ghost" size="sm" leadingIcon={<ClockIcon className="h-4 w-4" />}
        disabled={pendingInstall !== null} onClick={() => openHistory(null)} />
      <Button label={t("lut_sync_refresh_btn")} variant="ghost" size="sm" leadingIcon={<ArrowPathIcon className="h-4 w-4" />}
        loading={isRefreshing} disabled={isLoading} onClick={() => void refreshCatalog()} />
      </>}
      status={<ResourceInstallFilters label={t("resources_install_filter")} value={installFilter}
        onChange={(filter) => { setInstallFilter(filter); setPage(1); }}
        options={CATALOG_FILTERS.map(filter => ({ value: filter, label: t(`mat_sync_filter_${filter}`),
          count: isLoading || hasMoreCatalogEntries ? null : matchingItems.filter(({ entry }) => matchesInstallFilter(resolveCatalogInstallState(entry), filter)).length }))} />}>
      <ResourceCatalogFilters kind="luts" facets={facets} filters={filters} onChange={setFilters} complete={!isLoading && !hasMoreCatalogEntries} />
    </ResourceCatalogToolbar>}
    footer={<><span className="text-xs text-slate-500 dark:text-slate-400">{t("cloud_library_results_count").replace("{count}", String(filteredItems.length))}</span>
      {pageCount > 1 && <Pagination page={currentPage} pageCount={pageCount} onPageChange={setPage} />}</>}
    emptyMessage={error || notice ? "" : hasMoreCatalogEntries ? t("resources_search_incomplete") : undefined}
    emptyAction={!error && !notice && (searchQuery.trim() || hasResourceFilters(filters) || installFilter !== "all") && <Button label={t(hasResourceFilters(filters) || installFilter !== "all" ? "resources_clear_filters" : "resources_clear_search")} onClick={() => { changeQuery(""); setFilters(EMPTY_RESOURCE_FILTERS); setInstallFilter("all"); }} />}
    notices={<><CommunityNotice kind="luts" ids={visibleItems.map(({ entry }) => entry.lut_id)} />{notice && <StatusBanner tone="warning">{notice}</StatusBanner>}{error && <StatusBanner tone="error" action={offlineAction}>{error}</StatusBanner>}{previewError && <StatusBanner tone="warning" action={<Button label={t("resources_retry")} variant="secondary" onClick={() => setPreviewAttempt((value) => value + 1)} />}>{t("resources_lut_preview_failed")}</StatusBanner>}{catalog?.cached && <StatusBanner tone="info" action={!error ? offlineAction : undefined}>{t("resources_cached_catalog")}{catalogCheckedTime(catalog?.fetched_at, lang) && <span className="mt-1 block text-xs">{t("resources_source_checked_at")} · {catalogCheckedTime(catalog?.fetched_at, lang)}</span>}</StatusBanner>}{error && catalog && <StatusBanner tone="info">{t("resources_previous_catalog")}</StatusBanner>}<TransientBanner message={success} onDismiss={() => setSuccess(null)} /><TransientBanner tone="info" autoDismiss={false} message={hasMoreCatalogEntries ? t("cloud_library_loading_index") : null} action={<Button label={t("lut_sync_load_more_btn")} variant="secondary" loading={isLoadingMore} onClick={() => void loadMoreCatalog()} />} /></>}
    items={visibleItems.map(({ entry, identity, mode: rawMode, materialType }) => {
      const maker = identity.brand || t("lut_sync_unknown");
      const mode = resourceColorMode(rawMode, lang) || t("lut_sync_unknown");
      const state = resolveCatalogInstallState(entry);
      const key = catalogItemKey(entry);
      const action = state === "installed" || state === "local_available" ? undefined : <Button
        label={t(state === "update_available" ? "cloud_library_update" : state === "local_missing" || state === "local_modified" ? "resources_redownload" : "lut_sync_install_btn")}
        variant="secondary" loading={pendingInstall === key} disabled={pendingInstall !== null || pendingRestore !== null} onClick={() => void handleInstall(entry, identity.name)} />;
      const hasHistory = status?.history?.some(row => row.resource_id === entry.lut_id) ?? false;
      const stateLabel = t(state === "update_available" ? "resources_version_differs" : state === "local_missing" ? "mat_sync_catalog_state_local_missing"
        : state === "local_modified" ? "resources_local_modified" : state === "local_available" && hasHistory ? "mat_sync_catalog_state_local_available" : `lut_sync_catalog_state_${state}`);
      const artwork = scope ? boards.get(previewKey(scope, entry)) : undefined;
      const thumbnail = { kind: "luts" as const, resourceKey: key, mode: rawMode, name: identity.originalName,
        display: artwork ? { ...entry.display, ...artwork } : entry.display, metadata: entry.compatibility,
        loading: entry.display?.lut_board_available === true && !entry.display?.lut_board_preview && !artwork && !previewError };
      return { key, ...identity, thumbnail, subtitle: [maker, materialType].filter(Boolean).join(" · "), metric: mode, activity: <ResourceActivityActions kind="luts" resource={{ resource_id: entry.lut_id, revision_id: entry.revision_id, content_hash: entry.content_hash }} />, state: state === "not_installed" ? undefined : stateLabel, action,
        detail: <div className="flex flex-col gap-4">
          <LibraryIdentity {...identity} subtitle={[maker, materialType].filter(Boolean).join(" · ")} thumbnail={thumbnail} />
          <div className="border-t panel-divider pt-3.5">
            <LibraryFields rows={[
              { label: t("lut_library_color_mode_label"), value: mode },
              { label: t("lut_sync_catalog_state_label"), value: stateLabel },
              ...(entry.channel ? [{ label: t("mat_sync_channel_label"), value: ["official", "community", "team"].includes(entry.channel) ? t(`mat_sync_channel_${entry.channel}`) : entry.channel }] : []),
              { label: t("lut_sync_package_size_label"), value: formatBytes(Number(entry.package_bytes)) },
              ...(resolveLocalPath(entry) ? [{ label: t("lut_sync_local_path_label"), value: resolveLocalPath(entry), multiline: true }] : []),
            ]} />
          </div>
          <div className="flex flex-col gap-2 border-t panel-divider pt-4 [&>button]:w-full">
            {action}
            {hasHistory && <Button label={t("mat_sync_local_section_title")} disabled={pendingInstall !== null} onClick={() => openHistory(entry.lut_id)} />}
            <ResourceFeedback kind="luts" resource={{ resource_id: entry.lut_id, revision_id: entry.revision_id, content_hash: entry.content_hash }} />
          </div>
        </div>};
    })} />
    {showHistory && <ResourceHistoryDialog entries={(status?.history ?? []).filter(row => historyLut === null || row.resource_id === historyLut)}
      pending={pendingRestore} error={historyError} success={success} note={t("resources_history_preserve")}
      onDismissSuccess={() => setSuccess(null)} onClose={() => setShowHistory(false)}
      onRestore={(id, revision) => void restoreRevision(id, revision)} onRefresh={() => void refreshHistory()} />}
    </>;

}
