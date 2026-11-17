import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiErrorToVisibleMessage } from "../../api/client";
import {
  fetchMaterialRegistryCatalog,
  fetchMaterialSyncStatus,
  installMaterialRegistryCatalogEntry,
  rollbackMaterialSyncRevision,
} from "../../api/materialSync";
import type {
  MaterialRegistryCatalogEntry,
  MaterialRegistryCatalogResponse,
  MaterialSyncInstalledEntry,
  MaterialSyncStatusResponse,
} from "../../api/types";
import { useI18n } from "../../i18n/context";
import { useCommunityStore } from "../../stores/communityStore";
import { buildResourceSearch, filterResources, resourceFacets, hasResourceFilters, EMPTY_RESOURCE_FILTERS, type ResourceFilters } from "../../utils/resourceSearch";
import { clampPage, resolvePageCount } from "../ui/paginationModel";
import { DEFAULT_CATALOG_PAGE_SIZE, useCatalogPagination } from "../../hooks/useCatalogPagination";
import {
  CATALOG_FILTERS,
  catalogEntryKey,
  hasLocalMaterialFiles,
  matchesCatalogFilter,
  materialLocalSignatureKey,
  regionalCatalogDisplay,
  resolveInstallState,
  resolveRollbackRevisions,
} from "./catalogModel";
import type { CatalogFilter } from "./catalogModel";

export const MATERIAL_CATALOG_PAGE_SIZE = DEFAULT_CATALOG_PAGE_SIZE;
export const MATERIAL_CATALOG_SEARCH_DEBOUNCE_MS = 400;
const MATERIAL_REGISTRY_NOT_CONFIGURED_DETAIL = "Material registry URL is not configured";
const MATERIAL_REGISTRY_STALE_INSTALL_DETAIL =
  "Selected material registry package is not in current material registry catalog";

type CatalogAvailability = "loading" | "ready" | "not_configured" | "error";

interface ServerCatalogPage {
  query: string;
  page: number;
  pageSize: number;
  response: MaterialRegistryCatalogResponse;
}

interface FullCatalog {
  query: string;
  materials: MaterialRegistryCatalogEntry[];
  cached?: boolean;
}

interface LoadResult {
  isCurrent: boolean;
  hasError: boolean;
  hasNotice: boolean;
}

/** What the catalog list area should render. 目录列表区域的渲染状态。 */
export type MaterialCatalogView =
  | { kind: "loading" }
  | { kind: "full_catalog_failed" }
  | {
    kind: "entries";
    entries: MaterialRegistryCatalogEntry[];
    total: number;
    page: number;
    pageCount: number;
  };

export type CatalogFilterCounts = Partial<Record<CatalogFilter, number>>;

const readApiErrorDetail = (err: unknown): string | null => {
  if (!err || typeof err !== "object" || !("response" in err)) {
    return null;
  }
  const data = (err as { response?: { data?: unknown } }).response?.data;
  if (!data || typeof data !== "object" || !("detail" in data)) {
    return null;
  }
  const detail = (data as { detail?: unknown }).detail;
  return typeof detail === "string" && detail.trim() ? detail.trim() : null;
};

const readApiErrorStatus = (err: unknown): number | null => {
  if (!err || typeof err !== "object" || !("response" in err)) {
    return null;
  }
  const status = (err as { response?: { status?: unknown } }).response?.status;
  return typeof status === "number" ? status : null;
};

const isNotConfiguredError = (err: unknown): boolean =>
  readApiErrorDetail(err) === MATERIAL_REGISTRY_NOT_CONFIGURED_DETAIL;

const resolveErrorMessage = (err: unknown, fallback: string): string =>
  apiErrorToVisibleMessage(err, readApiErrorDetail(err) ?? fallback);

const resolveInstallErrorMessage = (err: unknown, fallback: string): string => {
  if (
    readApiErrorStatus(err) === 422
    && readApiErrorDetail(err) === MATERIAL_REGISTRY_STALE_INSTALL_DETAIL
  ) {
    return fallback;
  }
  return apiErrorToVisibleMessage(err, fallback);
};

const emptyCatalogResponse = (): MaterialRegistryCatalogResponse => ({
  schema_version: "1.0",
  channels: [],
  count: 0,
  total_count: 0,
  offset: 0,
  limit: MATERIAL_CATALOG_PAGE_SIZE,
  materials: [],
});

const catalogResponseTotal = (response: MaterialRegistryCatalogResponse): number =>
  response.total_count ?? response.count ?? response.materials.length;

const fetchCatalogPage = (query: string, page: number, signal?: AbortSignal, refresh = false, pageSize = MATERIAL_CATALOG_PAGE_SIZE) =>
  fetchMaterialRegistryCatalog({
    limit: pageSize,
    offset: (page - 1) * pageSize,
    ...(query ? { q: query } : {}),
    ...(refresh ? { refresh: true } : {}),
  }, signal);

const scopeOf = (page: MaterialRegistryCatalogResponse): string =>
  page.source_scope ?? JSON.stringify(page.channels);

const isComplete = (page: MaterialRegistryCatalogResponse): boolean =>
  page.offset === 0 && page.materials.length >= catalogResponseTotal(page);

// Older registries cap even an unpaginated request. Advance by rows actually returned.
async function completeCatalog(query: string, scope: string, initial?: MaterialRegistryCatalogResponse, signal?: AbortSignal) {
  let current = initial ?? await fetchMaterialRegistryCatalog(query ? { q: query } : {}, signal);
  const materials: MaterialRegistryCatalogEntry[] = [];
  let cached = false;
  for (;;) {
    if (scopeOf(current) !== scope || current.offset !== materials.length) {
      throw new Error("Material catalog changed during pagination");
    }
    materials.push(...current.materials);
    cached ||= current.cached === true;
    if (materials.length >= catalogResponseTotal(current)) return { ...current, materials, offset: 0, cached };
    if (current.materials.length === 0) throw new Error("Material catalog returned an incomplete page");
    signal?.throwIfAborted();
    current = await fetchMaterialRegistryCatalog({ ...(query ? { q: query } : {}), offset: materials.length, limit: 500 }, signal);
  }
}

/** Fetch a page; if it is past the end (catalog shrank), fetch the last page once. */
const fetchCatalogPageClamped = async (
  query: string,
  page: number,
  signal?: AbortSignal,
  refresh = false,
  pageSize = MATERIAL_CATALOG_PAGE_SIZE,
): Promise<{ page: number; pageSize: number; response: MaterialRegistryCatalogResponse }> => {
  const response = await fetchCatalogPage(query, page, signal, refresh, pageSize);
  const total = catalogResponseTotal(response);
  const lastPage = resolvePageCount(total, pageSize);
  if (page > lastPage && response.materials.length === 0) {
    return { page: lastPage, pageSize, response: await fetchCatalogPage(query, lastPage, signal, refresh, pageSize) };
  }
  return { page, pageSize, response };
};

/**
 * State and actions for the paginated cloud material catalog.
 *
 * Fetch one page first. Search, opening facets, or installed-cloud update
 * counts request a complete metadata index, reused for five minutes within
 * this panel and credential scope. Files are downloaded only by install().
 */
export function useMaterialCloudCatalog(market: string, onInstalled?: () => void | Promise<unknown>, initialQuery = "", filters: ResourceFilters = EMPTY_RESOURCE_FILTERS, selectedIds: ReadonlySet<string> | null = null) {
  const { t, lang } = useI18n();
  const [status, setStatus] = useState<MaterialSyncStatusResponse | null>(null);
  const [serverPage, setServerPage] = useState<ServerCatalogPage | null>(null);
  const [fullCatalog, setFullCatalog] = useState<FullCatalog | null>(null);
  const [facetsRequested, setFacetsRequested] = useState(false);
  const [fullCatalogFailedQuery, setFullCatalogFailedQuery] = useState<string | null>(null);
  const [availability, setAvailability] = useState<CatalogAvailability>("loading");
  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const [catalogQuery, setCatalogQuery] = useState(initialQuery);
  const [activeFilter, setActiveFilter] = useState<CatalogFilter>("all");
  const { page, pageSize, setPage, updatePage, resizePage, navigationKey, paginationRef } = useCatalogPagination();
  const [isLoading, setIsLoading] = useState(true);
  const [isPageLoading, setIsPageLoading] = useState(false);
  const [isFullCatalogLoading, setIsFullCatalogLoading] = useState(false);
  const [isSearchPending, setIsSearchPending] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [pendingInstall, setPendingInstall] = useState<string | null>(null);
  const [pendingRollback, setPendingRollback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const catalogRequestIdRef = useRef(0);
  const fullCatalogRequestIdRef = useRef(0);
  const searchScheduleIdRef = useRef(0);
  const latestSearchQueryRef = useRef(initialQuery);
  const indexRef = useRef<MaterialRegistryCatalogResponse | null>(null);
  const displayedScopeRef = useRef<string | null>(null);
  const indexFetchedAt = useRef(0);
  const pageController = useRef<AbortController | null>(null);
  const navigationAnchor = useRef<number | null>(null);
  const indexPending = useRef<{ scope: string; controller: AbortController; promise: Promise<MaterialRegistryCatalogResponse> } | null>(null);
  const indexRows = useMemo(() => {
    const cache = new WeakMap<MaterialRegistryCatalogEntry, { entry: MaterialRegistryCatalogEntry; search: ReturnType<typeof buildResourceSearch> }>();
    return (entries: MaterialRegistryCatalogEntry[]) => entries.map((entry) => {
      const cached = cache.get(entry);
      if (cached) return cached;
      const identity = regionalCatalogDisplay(entry, lang, market);
      const row = { entry, search: buildResourceSearch({ kind: "materials", identity, name: identity.originalName,
        display: entry.display, materialType: identity.materialType, rgb: identity.rgb, language: lang, market,
        extra: [entry.material_id, entry.revision_id, entry.local_directory, entry.channel].join(" ") }) };
      cache.set(entry, row);
      return row;
    });
  }, [lang, market]);
  const needsFacets = facetsRequested || hasResourceFilters(filters) || selectedIds !== null;
  const getIndex = useCallback((scope: string) => {
    const current = indexRef.current;
    if (current && scopeOf(current) === scope && isComplete(current) && Date.now() - indexFetchedAt.current < 5 * 60_000) return Promise.resolve(current);
    if (indexPending.current?.scope === scope) return indexPending.current.promise;
    indexPending.current?.controller.abort();
    const controller = new AbortController();
    const promise = completeCatalog("", scope, undefined, controller.signal).then((result) => {
      if (!controller.signal.aborted && displayedScopeRef.current === scope) {
        indexRef.current = result;
        indexFetchedAt.current = Date.now();
      }
      return result;
    }).finally(() => { if (indexPending.current?.controller === controller) indexPending.current = null; });
    indexPending.current = { scope, controller, promise };
    return promise;
  }, []);
  useEffect(() => () => {
    pageController.current?.abort();
    indexPending.current?.controller.abort();
    catalogRequestIdRef.current++;
    fullCatalogRequestIdRef.current++;
  }, []);

  const clearCatalog = useCallback(() => {
    fullCatalogRequestIdRef.current += 1;
    displayedScopeRef.current = null;
    indexRef.current = null;
    indexFetchedAt.current = 0;
    indexPending.current?.controller.abort();
    indexPending.current = null;
    setFullCatalog(null);
    setServerPage(null);
    setFullCatalogFailedQuery(null);
    setIsFullCatalogLoading(false);
  }, []);

  const loadCatalogAndStatus = useCallback(async (
    query: string,
    requestedPage: number,
    { preserveFullCatalog = false, refresh = false }: { preserveFullCatalog?: boolean; refresh?: boolean } = {},
  ): Promise<LoadResult> => {
    const requestId = ++catalogRequestIdRef.current;
    const requestedPageSize = paginationRef.current.pageSize;
    pageController.current?.abort();
    const controller = new AbortController();
    pageController.current = controller;
    if (!preserveFullCatalog) {
      fullCatalogRequestIdRef.current += 1;
      setFullCatalogFailedQuery(null);
      setIsFullCatalogLoading(false);
    }
    setIsLoading(true);
    setIsPageLoading(false);
    setError(null);
    setNotice(null);
    try {
      // A complete, recent directory can answer keystrokes locally. Check the
      // configured credential scope before reuse; never serve another source.
      const available = indexRef.current;
      let checkedStatus: MaterialSyncStatusResponse | undefined;
      if (available && isComplete(available) && Date.now() - indexFetchedAt.current < 5 * 60_000) {
        checkedStatus = await fetchMaterialSyncStatus(controller.signal).catch(() => undefined);
        if (requestId !== catalogRequestIdRef.current) return { isCurrent: false, hasError: false, hasNotice: false };
        if (checkedStatus?.source_scope && checkedStatus.source_scope === scopeOf(available)) {
          const matches = filterResources(indexRows(available.materials), query, EMPTY_RESOURCE_FILTERS).map((row) => row.entry);
          setStatus(checkedStatus);
          setCatalogQuery(query);
          setFullCatalog({ query, materials: matches, cached: available.cached });
          setServerPage({ query, page: requestedPage, pageSize: requestedPageSize, response: { ...available, materials: matches, total_count: matches.length, count: matches.length } });
          if (requestedPageSize === paginationRef.current.pageSize) updatePage(requestedPage);
          setAvailability("ready");
          return { isCurrent: true, hasError: false, hasNotice: available.cached === true };
        }
      }
      const [statusResult, catalogResult] = await Promise.allSettled([
        checkedStatus ?? fetchMaterialSyncStatus(controller.signal),
        fetchCatalogPageClamped(query, requestedPage, controller.signal, refresh, requestedPageSize),
      ] as const);
      if (requestId !== catalogRequestIdRef.current) {
        return { isCurrent: false, hasError: false, hasNotice: false };
      }

      const failures: string[] = [];
      let nextNotice: string | null = null;
      if (statusResult.status === "rejected") {
        failures.push(resolveErrorMessage(statusResult.reason, t("mat_sync_status_failed")));
      }
      const statusScope = statusResult.status === "fulfilled" ? statusResult.value.source_scope : null;
      const changedWhileOffline = statusScope && displayedScopeRef.current && statusScope !== displayedScopeRef.current;
      if (catalogResult.status === "fulfilled") {
        const { response } = catalogResult.value;
        const changedSource = displayedScopeRef.current !== null && displayedScopeRef.current !== scopeOf(response);
        if (changedSource) clearCatalog();
        displayedScopeRef.current = scopeOf(response);
        if (!query && response.offset === 0 && !(indexRef.current && isComplete(indexRef.current) && scopeOf(indexRef.current) === scopeOf(response))) {
          indexRef.current = response;
          if (isComplete(response)) indexFetchedAt.current = Date.now();
        }
        setCatalogQuery(query);
        if (!preserveFullCatalog) setFullCatalog(null);
        setServerPage({ query, ...catalogResult.value });
        if (requestedPageSize === paginationRef.current.pageSize) updatePage(catalogResult.value.page);
        setAvailability("ready");
      } else if (isNotConfiguredError(catalogResult.reason)) {
        clearCatalog();
        nextNotice = t("mat_sync_catalog_not_configured");
        setServerPage({ query, page: 1, pageSize: requestedPageSize, response: emptyCatalogResponse() });
        updatePage(1);
        setAvailability("not_configured");
      } else {
        failures.push(resolveErrorMessage(catalogResult.reason, t("mat_sync_status_failed")));
        if (changedWhileOffline || [401, 403].includes(readApiErrorStatus(catalogResult.reason) ?? 0)) {
          clearCatalog();
          setAvailability("error");
        } else {
          setAvailability((previous) => previous === "ready" ? previous : "error");
        }
      }

      if (statusResult.status === "fulfilled") setStatus(statusResult.value);
      setNotice(nextNotice);
      if (failures.length > 0) {
        setError(failures.join(" / "));
      }
      return {
        isCurrent: true,
        hasError: failures.length > 0,
        hasNotice: nextNotice !== null || (catalogResult.status === "fulfilled" && catalogResult.value.response.cached === true),
      };
    } finally {
      if (requestId === catalogRequestIdRef.current) {
        setIsLoading(false);
      }
    }
  }, [clearCatalog, indexRows, t, updatePage, paginationRef]);

  useEffect(() => {
    const scheduledQuery = searchQuery.trim();
    const scheduleId = ++searchScheduleIdRef.current;
    catalogRequestIdRef.current += 1;

    const runScheduledSearch = () => {
      if (scheduleId === searchScheduleIdRef.current) {
        setIsSearchPending(false);
        void loadCatalogAndStatus(scheduledQuery, 1);
      }
    };
    const timer = scheduledQuery
      ? window.setTimeout(runScheduledSearch, indexRef.current?.source_scope && Date.now() - indexFetchedAt.current < 5 * 60_000 ? 0 : MATERIAL_CATALOG_SEARCH_DEBOUNCE_MS)
      : null;
    if (timer === null) {
      runScheduledSearch();
    }

    return () => {
      if (timer !== null) {
        window.clearTimeout(timer);
      }
      catalogRequestIdRef.current += 1;
    };
  }, [loadCatalogAndStatus, searchQuery]);

  const reloadCurrentQuery = useCallback((options?: { preserveFullCatalog?: boolean; refresh?: boolean }) => {
    searchScheduleIdRef.current += 1;
    setIsSearchPending(false);
    return loadCatalogAndStatus(latestSearchQueryRef.current.trim(), paginationRef.current.page, options);
  }, [loadCatalogAndStatus, paginationRef]);

  const hasLocalInstalled = useMemo(
    () => (status?.installed ?? []).some(hasLocalMaterialFiles),
    [status],
  );

  // A query may match a regional alias missing from a registry's search index.
  // Preserve its native hits and order, then add matching identities from this source.
  useEffect(() => {
    if (
      availability !== "ready"
      || isLoading
      || !serverPage
      || serverPage.query !== catalogQuery
      || latestSearchQueryRef.current.trim() !== catalogQuery
      || (!hasLocalInstalled && !catalogQuery && !needsFacets)
      || isFullCatalogLoading
      || fullCatalog?.query === catalogQuery
      || fullCatalogFailedQuery === catalogQuery
    ) {
      return;
    }
    const requestId = ++fullCatalogRequestIdRef.current;
    const query = catalogQuery;
    const scope = scopeOf(serverPage.response);
    setIsFullCatalogLoading(true);
    const getMatches = async () => {
      if (!query) {
        const complete = await getIndex(scope);
        if (requestId === fullCatalogRequestIdRef.current) { indexRef.current = complete; indexFetchedAt.current = Date.now(); }
        return complete;
      }
      const first = serverPage.page === 1 ? serverPage.response : undefined;
      const [native, all] = await Promise.all([
        completeCatalog(query, scope, first, pageController.current?.signal),
        getIndex(scope),
      ]);
      if (requestId === fullCatalogRequestIdRef.current) { indexRef.current = all; indexFetchedAt.current = Date.now(); }
      const keys = new Set(native.materials.map(catalogEntryKey));
      const additional = filterResources(indexRows(all.materials), query, EMPTY_RESOURCE_FILTERS).map((row) => row.entry)
        .filter((entry) => !keys.has(catalogEntryKey(entry)));
      return { materials: [...native.materials, ...additional], cached: native.cached || all.cached };
    };
    getMatches()
      .then((response) => {
        if (requestId === fullCatalogRequestIdRef.current) {
          setFullCatalog({ query, materials: response.materials, cached: response.cached });
        }
      })
      .catch((err) => {
        if (requestId === fullCatalogRequestIdRef.current) {
          if ([401, 403].includes(readApiErrorStatus(err) ?? 0)) {
            clearCatalog();
            setAvailability("error");
            setError(resolveErrorMessage(err, t("mat_sync_status_failed")));
            return;
          }
          setFullCatalogFailedQuery(query);
        }
      })
      .finally(() => {
        if (requestId === fullCatalogRequestIdRef.current) {
          setIsFullCatalogLoading(false);
        }
      });
  }, [
    availability,
    catalogQuery,
    clearCatalog,
    fullCatalog,
    fullCatalogFailedQuery,
    hasLocalInstalled,
    needsFacets,
    indexRows,
    getIndex,
    isFullCatalogLoading,
    isLoading,
    lang,
    market,
    serverPage,
    t,
  ]);

  const installedByMaterialId = useMemo(() => {
    const result = new Map<string, MaterialSyncInstalledEntry>();
    for (const entry of status?.installed ?? []) {
      result.set(entry.material_id, entry);
    }
    return result;
  }, [status]);

  const installedByLocalSignature = useMemo(() => {
    const result = new Map<string, MaterialSyncInstalledEntry>();
    for (const entry of status?.installed ?? []) {
      const signatureKey = hasLocalMaterialFiles(entry)
        ? materialLocalSignatureKey(entry.local_directory, entry.content_hash)
        : null;
      if (signatureKey) {
        result.set(signatureKey, entry);
      }
    }
    return result;
  }, [status]);

  const resolveCatalogInstalledEntry = useCallback((entry: MaterialRegistryCatalogEntry) => {
    const signatureKey = materialLocalSignatureKey(entry.local_directory, entry.content_hash);
    const localMatch = signatureKey ? installedByLocalSignature.get(signatureKey) : undefined;
    return localMatch ?? installedByMaterialId.get(entry.material_id);
  }, [installedByLocalSignature, installedByMaterialId]);

  const resolveEntryInstallState = useCallback(
    (entry: MaterialRegistryCatalogEntry) =>
      resolveInstallState(entry, resolveCatalogInstalledEntry(entry)),
    [resolveCatalogInstalledEntry],
  );

  const allRows = useMemo(() => indexRows(fullCatalog?.query === catalogQuery ? fullCatalog.materials : serverPage?.response.materials ?? []),
    [fullCatalog, catalogQuery, serverPage, indexRows]);
  // Native Registry hits may include server-only aliases. Keep them, but rank
  // exact local product codes first and apply every structured filter.
  const nativeRows = useMemo(() => new Set(allRows), [allRows]);
  const localCatalog = useMemo(() => fullCatalog?.query === catalogQuery
    ? filterResources(allRows, catalogQuery, filters, nativeRows).map((row) => row.entry)
      .filter((entry) => selectedIds === null || selectedIds.has(entry.material_id)) : null,
  [fullCatalog, catalogQuery, filters, allRows, nativeRows, selectedIds]);
  const facets = useMemo(() => resourceFacets(indexRef.current && isComplete(indexRef.current) ? indexRows(indexRef.current.materials) : allRows,
    catalogQuery, filters, nativeRows), [allRows, catalogQuery, filters, nativeRows, indexRows]);
  const serverTotal = serverPage ? catalogResponseTotal(serverPage.response) : 0;
  const catalogTotalCount = localCatalog?.length ?? serverTotal;

  const filterCounts = useMemo<CatalogFilterCounts>(() => {
    if (localCatalog) {
      const counts: CatalogFilterCounts = {};
      for (const filter of CATALOG_FILTERS) {
        counts[filter] = 0;
      }
      for (const entry of localCatalog) {
        const installState = resolveEntryInstallState(entry);
        for (const filter of CATALOG_FILTERS) {
          if (matchesCatalogFilter(installState, filter)) {
            counts[filter] = (counts[filter] ?? 0) + 1;
          }
        }
      }
      return counts;
    }
    if (!serverPage) {
      return {};
    }
    if (!hasLocalInstalled) {
      return { all: serverTotal, not_installed: serverTotal, updates: 0, installed: 0 };
    }
    return { all: serverTotal };
  }, [hasLocalInstalled, localCatalog, resolveEntryInstallState, serverPage, serverTotal]);

  /** Exact update count, or null while the full catalog is still loading. */
  const updateCount = filterCounts.updates ?? null;

  const view = useMemo<MaterialCatalogView>(() => {
    if (localCatalog) {
      const filtered = localCatalog.filter(
        (entry) => matchesCatalogFilter(resolveEntryInstallState(entry), activeFilter),
      );
      const pageCount = resolvePageCount(filtered.length, pageSize);
      const currentPage = clampPage(page, pageCount);
      const start = (currentPage - 1) * pageSize;
      return {
        kind: "entries",
        entries: filtered.slice(start, start + pageSize),
        total: filtered.length,
        page: currentPage,
        pageCount,
      };
    }
    if (!serverPage) {
      return isLoading
        ? { kind: "loading" }
        : { kind: "entries", entries: [], total: 0, page: 1, pageCount: 1 };
    }
    const serverServesFilter = selectedIds === null && !hasResourceFilters(filters) && (activeFilter === "all"
      || (activeFilter === "not_installed" && !hasLocalInstalled));
    if (serverServesFilter) {
      return {
        kind: "entries",
        entries: serverPage.response.materials,
        total: serverTotal,
        page: serverPage.page,
        pageCount: resolvePageCount(serverTotal, serverPage.pageSize),
      };
    }
    if ((!hasLocalInstalled && !hasResourceFilters(filters) && selectedIds === null) || availability !== "ready") {
      return { kind: "entries", entries: [], total: 0, page: 1, pageCount: 1 };
    }
    if (fullCatalogFailedQuery === catalogQuery) {
      return { kind: "full_catalog_failed" };
    }
    return { kind: "loading" };
  }, [
    activeFilter,
    filters,
    availability,
    catalogQuery,
    fullCatalogFailedQuery,
    hasLocalInstalled,
    isLoading,
    localCatalog,
    page,
    pageSize,
    resolveEntryInstallState,
    serverPage,
    serverTotal,
    selectedIds,
  ]);

  const loadServerPage = useCallback(async (target: number) => {
    const requestedPageSize = paginationRef.current.pageSize;
    const previousPage = serverPage?.page ?? 1;
    if (localCatalog || !serverPage || (serverPage.page === target && serverPage.pageSize === requestedPageSize) || availability !== "ready") {
      return;
    }
    const requestId = ++catalogRequestIdRef.current;
    pageController.current?.abort();
    const controller = new AbortController();
    pageController.current = controller;
    const query = serverPage.query;
    setIsPageLoading(true);
    setError(null);
    try {
      const result = await fetchCatalogPageClamped(query, target, controller.signal, false, requestedPageSize);
      if (requestId === catalogRequestIdRef.current) {
        const scope = scopeOf(result.response);
        if (displayedScopeRef.current !== null && displayedScopeRef.current !== scope) {
          clearCatalog();
        }
        displayedScopeRef.current = scope;
        setServerPage({ query, ...result });
        if (requestedPageSize === paginationRef.current.pageSize) updatePage(result.page);
      }
    } catch (err) {
      if (requestId === catalogRequestIdRef.current) {
        if ([401, 403].includes(readApiErrorStatus(err) ?? 0)) {
          clearCatalog();
          setAvailability("error");
        }
        if (requestedPageSize === paginationRef.current.pageSize) updatePage(previousPage);
        setError(resolveErrorMessage(err, t("mat_sync_status_failed")));
      }
    } finally {
      if (requestId === catalogRequestIdRef.current) {
        setIsPageLoading(false);
      }
    }
  }, [availability, clearCatalog, localCatalog, serverPage, t, updatePage, paginationRef]);

  const goToPage = useCallback(async (target: number) => {
    const anchor = (target - 1) * paginationRef.current.pageSize;
    navigationAnchor.current = anchor;
    setPage(target);
    try {
      await loadServerPage(target);
    } finally {
      if (navigationAnchor.current === anchor) navigationAnchor.current = null;
    }
  }, [setPage, loadServerPage, paginationRef]);

  useEffect(() => {
    if (!isLoading && !isPageLoading && !isSearchPending && searchQuery.trim() === catalogQuery
      && !error && serverPage && serverPage.pageSize !== pageSize) {
      void loadServerPage(paginationRef.current.page);
    }
  }, [pageSize, serverPage, isLoading, isPageLoading, isSearchPending, searchQuery, catalogQuery, error, loadServerPage, paginationRef]);

  const selectFilter = useCallback((filter: CatalogFilter) => {
    setActiveFilter(filter);
    void goToPage(1);
  }, [goToPage]);

  const handleSearchQueryChange = useCallback((value: string) => {
    latestSearchQueryRef.current = value;
    navigationAnchor.current = null;
    pageController.current?.abort();
    catalogRequestIdRef.current += 1;
    fullCatalogRequestIdRef.current += 1;
    searchScheduleIdRef.current += 1;
    setIsFullCatalogLoading(false);
    setIsLoading(false);
    setIsPageLoading(false);
    setIsSearchPending(Boolean(value.trim()));
    setSearchQuery(value);
  }, []);

  const refreshCatalog = useCallback(async () => {
    setIsRefreshing(true);
    setSuccess(null);
    indexRef.current = null;
    indexFetchedAt.current = 0;
    indexPending.current?.controller.abort();
    indexPending.current = null;
    try {
      const result = await reloadCurrentQuery({ refresh: true });
      if (result.isCurrent && !result.hasError && !result.hasNotice) {
        setSuccess(t("mat_sync_catalog_refresh_success"));
      }
    } finally {
      setIsRefreshing(false);
    }
  }, [reloadCurrentQuery, t]);

  const retryFullCatalog = useCallback(() => {
    setFullCatalogFailedQuery(null);
  }, []);

  const installEntry = useCallback(async (entry: MaterialRegistryCatalogEntry) => {
    const installState = resolveInstallState(entry, resolveCatalogInstalledEntry(entry));
    setPendingInstall(`${entry.material_id}:${entry.revision_id}`);
    setError(null);
    setSuccess(null);
    try {
      const subject = useCommunityStore.getState().connection?.subject;
      const result = await installMaterialRegistryCatalogEntry({
        material_id: entry.material_id,
        revision_id: entry.revision_id,
        package_url: entry.package_url,
        package_sha256: entry.package_sha256,
        ...(subject ? { account_id: subject } : {}),
      });
      useCommunityStore.getState().downloaded("materials", entry.material_id, subject, result?.activity_recorded);
      await reloadCurrentQuery({ preserveFullCatalog: true });
      await onInstalled?.();
      setSuccess(t(installState === "update_available" ? "resources_updated_named" : installState === "local_missing" ? "resources_redownloaded_named" : "resources_added_named")
        .replace("{name}", () => regionalCatalogDisplay(entry, lang, market).name));
    } catch (err) {
      setError(resolveInstallErrorMessage(err, t("mat_sync_install_failed")));
    } finally {
      setPendingInstall(null);
    }
  }, [reloadCurrentQuery, resolveCatalogInstalledEntry, onInstalled, lang, market, t]);

  const rollbackEntry = useCallback(async (
    entry: MaterialSyncInstalledEntry,
    revisionId: string,
  ) => {
    setPendingRollback(`${entry.material_id}:${revisionId}`);
    setError(null);
    setSuccess(null);
    try {
      await rollbackMaterialSyncRevision(entry.material_id, revisionId);
      await reloadCurrentQuery({ preserveFullCatalog: true });
      await onInstalled?.();
      setSuccess(t("mat_sync_rollback_success"));
    } catch (err) {
      setError(resolveErrorMessage(err, t("mat_sync_rollback_failed")));
    } finally {
      setPendingRollback(null);
    }
  }, [reloadCurrentQuery, onInstalled, t]);

  const rollbackCandidates = useMemo(
    () => (status?.installed ?? []).filter(
      (entry) => hasLocalMaterialFiles(entry) && resolveRollbackRevisions(entry).length > 0,
    ),
    [status],
  );

  return {
    status,
    cached: localCatalog ? fullCatalog?.cached : serverPage?.response.cached,
    fetchedAt: serverPage?.response.fetched_at,
    view,
    navigationKey,
    resizePage: (columns: number, anchorIndex: number) => {
      // Explicit navigation wins if closing the detail changes columns while
      // the next server page is still loading; do not anchor to the old page.
      if (latestSearchQueryRef.current.trim() !== catalogQuery) {
        resizePage(columns, 0, 1);
      } else if (navigationAnchor.current !== null) {
        resizePage(columns, navigationAnchor.current, 1);
      } else {
        resizePage(columns, anchorIndex, view.kind === "entries" ? view.page : page,
          localCatalog ? pageSize : serverPage?.pageSize ?? pageSize);
      }
    },
    facets,
    facetsComplete: fullCatalog?.query === catalogQuery,
    facetLookupFailed: needsFacets && fullCatalogFailedQuery === catalogQuery,
    requestFacets: () => setFacetsRequested(true),
    activeFilter,
    filterCounts,
    updateCount,
    catalogTotalCount,
    rollbackCandidates,
    searchQuery,
    isLoading,
    isPageLoading,
    isSearchPending,
    isRefreshing,
    isFullCatalogLoading,
    aliasLookupFailed: Boolean(catalogQuery && fullCatalogFailedQuery === catalogQuery && view.kind === "entries"),
    pendingInstall,
    pendingRollback,
    error,
    notice,
    success,
    dismissError: () => setError(null),
    dismissSuccess: () => setSuccess(null),
    resolveEntryInstallState,
    resolveLocalDirectory: (entry: MaterialRegistryCatalogEntry): string | null => {
      const installed = resolveCatalogInstalledEntry(entry);
      return installed && hasLocalMaterialFiles(installed) ? installed.local_directory : null;
    },
    handleSearchQueryChange,
    selectFilter,
    goToPage,
    refreshCatalog,
    retryFullCatalog,
    installEntry,
    rollbackEntry,
  };
}
