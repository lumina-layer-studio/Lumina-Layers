import { useResourceActivity } from "../hooks/useResourceActivity";
import ResourceFeedback from "./ResourceFeedback";
import { useCatalogHealth, catalogCheckedTime } from "../hooks/useCatalogHealth";
import { ArrowPathIcon, ClockIcon } from "@heroicons/react/24/outline";
import TransientBanner from "./ui/TransientBanner";
import { LibraryIdentity, LibraryFields } from "./ui/LibraryDetails";
import CloudLibraryPreview from "./ui/CloudLibraryPreview";
import { regionalCatalogDisplay, resolveCatalogFitError, resolveCatalogChannel, formatBytes } from "./materialCloud/catalogModel";
import { useCallback, useMemo, useState } from "react";
import { CommunityFilter, CommunityNotice, ResourceActivityActions } from "./ui/ResourceActivity";
import type { PersonalFilter } from "../api/community";
import { useCommunityStore } from "../stores/communityStore";

import { useI18n } from "../i18n/context";
import { useFilamentMarket } from "../hooks/useFilamentMarket";
import MaterialCloudHistoryDialog from "./materialCloud/MaterialCloudHistoryDialog";
import { CATALOG_FILTERS, catalogEntryKey } from "./materialCloud/catalogModel";
import {
  useMaterialCloudCatalog,
} from "./materialCloud/useMaterialCloudCatalog";
import Button from "./ui/Button";
import Pagination from "./ui/Pagination";
import CloseButton from "./ui/CloseButton";
import { useResourceFilters, type ResourceFilterProps } from "../hooks/useResourceFilters";
import { hasResourceFilters, EMPTY_RESOURCE_FILTERS } from "../utils/resourceSearch";
import ResourceCatalogFilters from "./ui/ResourceCatalogFilters";
import ResourceCatalogToolbar, { ResourceInstallFilters } from "./ui/ResourceCatalogToolbar";
import {
  StatusBanner,
  wellClass,
} from "./ui/panelPrimitives";

const SKELETON_CARD_COUNT = 6;
const CATALOG_GRID_CLASS =
  "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,17.5rem),1fr))]";

function CatalogSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className={CATALOG_GRID_CLASS}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: SKELETON_CARD_COUNT }, (_, index) => (
        <div key={index} aria-hidden="true" className={`${wellClass} flex animate-pulse flex-col gap-4 p-4`}>
          <div className="flex gap-3">
            <div className="h-14 w-14 rounded-lg bg-slate-300/50 dark:bg-slate-600/40" />
            <div className="flex-1 space-y-2 pt-1">
              <div className="h-3 w-3/4 rounded bg-slate-300/50 dark:bg-slate-600/40" />
              <div className="h-3 w-1/2 rounded bg-slate-300/40 dark:bg-slate-600/30" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {Array.from({ length: 4 }, (__, cell) => (
              <div key={cell} className="h-8 rounded bg-slate-300/40 dark:bg-slate-600/30" />
            ))}
          </div>
          <div className="h-11 rounded-[10px] bg-slate-300/40 dark:bg-slate-600/30" />
        </div>
      ))}
    </div>
  );
}

/**
 * Cloud material library page: browse the Registry catalog page by page,
 * install or update materials, and roll back local revisions.
 * 云端耗材库页面：分页浏览 Registry 目录，安装/更新耗材，回滚本地版本。
 */
export default function MaterialCloudSyncPanel({ initialPersonalFilter = "all", initialQuery = "", onQueryChange, onBrowseOffline, onInstalled, ...filterProps }: {
  initialPersonalFilter?: PersonalFilter;
  initialQuery?: string;
  onQueryChange?: (query: string) => void;
  onBrowseOffline?: () => void;
  onInstalled?: () => void | Promise<unknown>;
} & ResourceFilterProps = {}) {
  const { t, lang } = useI18n();
  const market = useFilamentMarket();
  const [personalFilter, setPersonalFilter] = useState<PersonalFilter>(initialPersonalFilter);
  const myActivity = useCommunityStore((state) => state.mine.materials);
  const selectedIds = useMemo(() => personalFilter === "all" ? null : new Set(Object.values(myActivity)
    .filter((row) => row[personalFilter]).map((row) => row.resource_id)), [myActivity, personalFilter]);
  const [filters, setFilters] = useResourceFilters(filterProps, () => { void catalog.goToPage(1); });
  const catalog = useMaterialCloudCatalog(market, onInstalled, initialQuery, filters, selectedIds);
  const [showHistory, setShowHistory] = useState(false);
  const [historyMaterial, setHistoryMaterial] = useState<string | null>(null);
  const { dismissSuccess, success, view } = catalog;
  const handlePageChange = useCallback((nextPage: number) => {
    void catalog.goToPage(nextPage);
  }, [catalog]);

  const isListBusy = catalog.isLoading || catalog.isPageLoading || catalog.isSearchPending;
  const paginationDisabled = isListBusy || catalog.pendingInstall !== null;
  const changeQuery = (value: string) => {
    catalog.handleSearchQueryChange(value);
    onQueryChange?.(value);
  };
  const offlineAction = onBrowseOffline
    ? <Button label={t("resources_browse_offline")} onClick={onBrowseOffline} />
    : undefined;

  const renderCatalogBody = () => {
    if (view.kind === "loading") {
      return <CatalogSkeleton label={t("mat_gradient_library_loading")} />;
    }
    if (view.kind === "full_catalog_failed") {
      return (
        <StatusBanner
          data-testid="material-cloud-full-catalog-failed"
          tone="warning"
          action={(
            <Button
              label={t("mat_sync_full_catalog_retry_btn")}
              variant="secondary"
              size="sm"
              onClick={catalog.retryFullCatalog}
            />
          )}
        >
          {t("mat_sync_full_catalog_failed")}
        </StatusBanner>
      );
    }
    return null;
  };

  const entries = view.kind === "entries" ? view.entries : [];
  useCatalogHealth("materials", !catalog.isLoading && view.kind === "entries", catalog.cached, catalog.fetchedAt, catalog.error);
  useResourceActivity("materials", entries.map((entry) => entry.material_id));
  const findingAliases = Boolean(catalog.searchQuery.trim() && catalog.isFullCatalogLoading);
  return <><CloudLibraryPreview emptyMessage={catalog.error || catalog.notice || view.kind === "full_catalog_failed" ? "" : t(findingAliases ? "resources_search_incomplete" : "mat_sync_catalog_empty")} busy={isListBusy || view.kind === "loading"} loadingMessage={view.kind === "loading" ? "" : t("mat_gradient_library_loading")} resetKey={`${catalog.searchQuery}:${catalog.activeFilter}:${JSON.stringify(filters)}:${catalog.navigationKey}`}
    onColumnsChange={catalog.resizePage}
    emptyAction={!catalog.error && !catalog.notice && (catalog.searchQuery.trim() || catalog.activeFilter !== "all" || hasResourceFilters(filters)) && <Button
      label={t(catalog.activeFilter === "all" && !hasResourceFilters(filters) ? "resources_clear_search" : "resources_clear_filters")}
      onClick={() => { changeQuery(""); catalog.selectFilter("all"); setFilters(EMPTY_RESOURCE_FILTERS); }} />}
    toolbar={<ResourceCatalogToolbar query={catalog.searchQuery} searchLabel={t("mat_sync_search_placeholder")} onQueryChange={changeQuery}
      actions={<>
      <CommunityFilter value={personalFilter} onChange={(value) => { setPersonalFilter(value); void catalog.goToPage(1); }} />
      <Button label={t("mat_sync_local_section_title")} variant="ghost" size="sm" leadingIcon={<ClockIcon className="h-4 w-4" />}
        disabled={catalog.pendingInstall !== null} onClick={() => { setHistoryMaterial(null); setShowHistory(true); }} />
      <Button label={t("mat_sync_refresh_btn")} variant="ghost" size="sm" leadingIcon={<ArrowPathIcon className="h-4 w-4" />}
        loading={catalog.isRefreshing} disabled={catalog.isLoading} onClick={() => void catalog.refreshCatalog()} />
      </>}
      status={<ResourceInstallFilters label={t("mat_sync_filter_group_label")} value={catalog.activeFilter}
        onChange={catalog.selectFilter} options={CATALOG_FILTERS.map((filter) => ({ value: filter, label: t(`mat_sync_filter_${filter}`), count: catalog.filterCounts[filter] }))} />}>
      <ResourceCatalogFilters kind="materials" filters={filters} facets={catalog.facets} onChange={setFilters}
        onOpen={catalog.requestFacets} complete={catalog.facetsComplete} />
    </ResourceCatalogToolbar>}
    notices={<>{catalog.error && <StatusBanner data-testid="material-cloud-sync-error" tone="error" action={<div className="flex flex-wrap items-center gap-2">{offlineAction}<CloseButton label={t("mat_sync_dismiss_btn")} onClick={catalog.dismissError} /></div>}>{catalog.error}</StatusBanner>}{catalog.cached && <StatusBanner tone="info" action={!catalog.error ? offlineAction : undefined}>{t("resources_cached_catalog")}{catalogCheckedTime(catalog.fetchedAt, lang) && <span className="mt-1 block text-xs">{t("resources_source_checked_at")} · {catalogCheckedTime(catalog.fetchedAt, lang)}</span>}</StatusBanner>}{catalog.error && entries.length > 0 && <StatusBanner tone="info">{t("resources_previous_catalog")}</StatusBanner>}
      {catalog.searchQuery.trim() && catalog.isFullCatalogLoading && <StatusBanner tone="info">{t("cloud_library_loading_index")}</StatusBanner>}
      <CommunityNotice kind="materials" ids={entries.map((entry) => entry.material_id)} />
      {catalog.aliasLookupFailed && <StatusBanner tone="warning" action={<Button label={t("resources_retry")} onClick={catalog.retryFullCatalog} />}>{t("resources_alias_search_partial")}</StatusBanner>}
      {catalog.facetLookupFailed && !catalog.aliasLookupFailed && view.kind !== "full_catalog_failed" && <StatusBanner tone="warning"
        action={<Button label={t("resources_retry")} onClick={catalog.retryFullCatalog} />}>{t("resources_filter_failed")}</StatusBanner>}
      <TransientBanner data-testid="material-cloud-sync-notice" tone="info" autoDismiss={false} message={catalog.notice} /><TransientBanner data-testid="material-cloud-sync-success" message={success} onDismiss={dismissSuccess} />{view.kind !== "entries" && renderCatalogBody()}</>}
    footer={view.kind === "entries" && <><span className="text-xs text-slate-500 dark:text-slate-400">{t("cloud_library_results_count").replace("{count}", String(view.total))}</span>{view.pageCount > 1 && <Pagination page={view.page} pageCount={view.pageCount} onPageChange={handlePageChange} disabled={paginationDisabled} showJump={view.pageCount > 7} />}</>}
    items={entries.map((entry) => {
      const display = regionalCatalogDisplay(entry, lang, market);
      const fit = resolveCatalogFitError(entry);
      const state = catalog.resolveEntryInstallState(entry);
      const key = catalogEntryKey(entry);
      const thumbnail = { kind: "materials" as const, rgb: display.rgb, display: entry.display };
      const actionLabel = t(state === "update_available" ? "cloud_library_update" : state === "local_missing" ? "resources_redownload" : "mat_sync_install_btn");
      const action = state === "installed" || state === "local_available" ? undefined : <Button label={actionLabel}
        variant="secondary" loading={catalog.pendingInstall === key} disabled={catalog.pendingInstall !== null || catalog.pendingRollback !== null}
        onClick={() => void catalog.installEntry(entry)} />;
      return { key, name: display.name, originalName: display.originalName, logo: display.logo, colorDescription: display.colorDescription, subtitle: [display.brand, display.materialType].filter(Boolean).join(" · "), thumbnail,
        activity: <ResourceActivityActions kind="materials" resource={{ resource_id: entry.material_id, revision_id: entry.revision_id, content_hash: entry.content_hash }} />,
        state: state === "not_installed" ? undefined : t(`mat_sync_catalog_state_${state}`),
        action,
        detail: <div className="flex flex-col gap-4">
          <LibraryIdentity {...display} subtitle={[display.brand, display.materialType].filter(Boolean).join(" · ")} thumbnail={thumbnail} />
          <div className="border-t panel-divider pt-3.5">
            <LibraryFields rows={[
              { label: t("mat_sync_fit_error_label"), value: fit.meanDeltaE?.toFixed(2) ?? "—" },
              ...(fit.layerHeightMm !== null ? [{ label: t("mat_gradient_library_layer_height_label"), value: `${fit.layerHeightMm} mm` }] : []),
              ...(fit.verificationCount !== null ? [{ label: t("mat_gradient_library_verification_count_label"), value: fit.verificationCount }] : []),
            ]} />
          </div>
          <div className="border-t panel-divider pt-3.5">
            <LibraryFields rows={[
              { label: t("mat_sync_catalog_state_label"), value: t(`mat_sync_catalog_state_${state}`) },
              { label: t("mat_sync_channel_label"), value: resolveCatalogChannel(entry) === "other" ? entry.channel : t(`mat_sync_channel_${resolveCatalogChannel(entry)}`) },
              { label: t("mat_sync_package_size_label"), value: formatBytes(entry.package_bytes) },
              ...(catalog.resolveLocalDirectory(entry) ? [{ label: t("mat_gradient_library_directory_label"), value: catalog.resolveLocalDirectory(entry), multiline: true }] : []),
            ]} />
          </div>
          <div className="flex flex-col gap-2 border-t panel-divider pt-4 [&>button]:w-full">
            {action}
            {catalog.rollbackCandidates.some(item => item.material_id === entry.material_id) && <Button variant="secondary" disabled={catalog.pendingInstall !== null} label={t("mat_sync_local_section_title")} onClick={() => { setHistoryMaterial(entry.material_id); setShowHistory(true); }} />}
            <ResourceFeedback kind="materials" resource={{ resource_id: entry.material_id, revision_id: entry.revision_id, content_hash: entry.content_hash }} />
          </div>
        </div>
      };
    })} />
    {showHistory && <MaterialCloudHistoryDialog
      entries={catalog.rollbackCandidates.filter(item => historyMaterial === null || item.material_id === historyMaterial)}
      pendingRollback={catalog.pendingRollback} error={catalog.error} success={success} onDismissSuccess={dismissSuccess}
      onClose={() => setShowHistory(false)} onRollback={(entry, revision) => void catalog.rollbackEntry(entry, revision)} />}
  </>;
}
