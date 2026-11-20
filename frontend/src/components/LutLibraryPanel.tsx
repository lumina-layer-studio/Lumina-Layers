import { LibraryIdentity, LibraryFields, LibraryCardIdentity, LibraryCardPalette } from "./ui/LibraryDetails";
import ResourceDetailsPanel from "./ui/ResourceDetailsPanel";
import { resourceColorMode } from "../utils/resourcePresentation";
import CalibrationThumbnail from "./ui/CalibrationThumbnail";
import ResourceContribution from "./ResourceContribution";
import { useFilamentMarket } from "../hooks/useFilamentMarket";
import { filamentMatches } from "../utils/filamentIdentity";
import { localLutIdentity, lutGroupBrand } from "../utils/libraryFilamentIdentity";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { motion } from "framer-motion";
import { createPortal } from "react-dom";
import { DndContext, DragOverlay, PointerSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import { LibraryBrandHeader, SortableLibraryBrand } from "./ui/LibraryBrandGroup";

import { apiErrorToVisibleMessage } from "../api/client";
import { fetchLutDetailsCatalog, uploadLocalLut } from "../api/lut";
import type { LutDetailsCatalogGroup, LutDetailsCatalogItem } from "../api/types";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import { useLutDetailsStore } from "../stores/lutDetailsStore";
import { useWidgetStore } from "../stores/widgetStore";
import { useResourceStore } from "../stores/resourceStore";
import Button from "./ui/Button";
import MaterialArchiveGuide from "./ui/MaterialArchiveGuide";
import ResourceLibraryEmpty from "./ui/ResourceLibraryEmpty";
import TransientBanner from "./ui/TransientBanner";
import CloseButton from "./ui/CloseButton";
import {
  StatusBanner,
  cardPadClass,
} from "./ui/panelPrimitives";

function readPreference(key: string): string[] {
  try { const value: unknown = JSON.parse(localStorage.getItem(key) ?? "[]"); return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []; }
  catch { return []; }
}

const flattenCatalog = (groups: LutDetailsCatalogGroup[]): LutDetailsCatalogItem[] =>
  groups.flatMap((group) => group.items ?? []);

const normalizedText = (value: string): string =>
  value.toLowerCase().replace(/[\s\-_&/\\]+/g, "");

const itemMatchesQuery = (item: LutDetailsCatalogItem, query: string, identityTerms: string): boolean => {
  const terms = query.trim().split(/\s+/).map(normalizedText).filter(Boolean);
  if (terms.length === 0) {
    return true;
  }
  const tokens = [
    item.name,
    item.manufacturer,
    item.material_type,
    item.color_mode,
    item.source_kind,
    item.path,
    ...item.search_tokens,
  ].map(normalizedText);
  return terms.every((term) => tokens.some((token) => token.includes(term)) || filamentMatches(term, identityTerms));
};

const groupItems = (
  items: LutDetailsCatalogItem[],
  unknownLabel: string,
): LutDetailsCatalogGroup[] => {
  const groups = new Map<string, LutDetailsCatalogItem[]>();
  for (const item of items) {
    const key = item.manufacturer || unknownLabel;
    const existing = groups.get(key);
    if (existing) {
      existing.push(item);
    } else {
      groups.set(key, [item]);
    }
  }
  return Array.from(groups, ([manufacturer, groupItemsValue]) => ({
    manufacturer,
    items: groupItemsValue,
  })).sort((left, right) => left.manufacturer.localeCompare(right.manufacturer));
};

export default function LutLibraryPanel() {
  const { t, lang } = useI18n();
  const market = useFilamentMarket();
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const setActiveTab = useWidgetStore((state) => state.setActiveTab);
  const [catalog, setCatalog] = useState<LutDetailsCatalogGroup[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const refreshCatalog = useCallback(async () => {
    setError(null);
    try {
      const response = await fetchLutDetailsCatalog();
      useResourceStore.getState().observeLibrary("luts", flattenCatalog(response.groups).length);
      setCatalog(response.groups ?? []);
      return response.groups ?? [];
    } catch (err) {
      setError(apiErrorToVisibleMessage(err, t("lut_library_load_failed")));
      return [];
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refreshCatalog();
  }, [refreshCatalog]);

  const allItems = useMemo(() => flattenCatalog(catalog), [catalog]);
  const identities = useMemo(() => new Map(allItems.map((item) =>
    [item.path, localLutIdentity(item.manufacturer, item.name, lang, item.display, market)])), [allItems, lang, market]);
  const groupBrands = useMemo(() => new Map(groupItems(allItems, t("lut_library_unknown")).map((group) => [
    group.manufacturer, lutGroupBrand(group.manufacturer, group.items.map((item) => identities.get(item.path)!), lang, market),
  ])), [allItems, identities, lang, market, t]);
  const filteredItems = useMemo(
    () => allItems.filter((item) => itemMatchesQuery(item, query, identities.get(item.path)!.searchText)),
    [allItems, identities, query],
  );
  const groupedItems = useMemo(
    () => groupItems(filteredItems, t("lut_library_unknown")),
    [filteredItems, t],
  );
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    setSuccess(null);
    try {
      await refreshCatalog();
    } finally {
      setIsRefreshing(false);
    }
  }, [refreshCatalog]);

  const handleUpload = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setIsUploading(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await uploadLocalLut(file);
      await refreshCatalog();
      setSuccess(response.message || t("lut_library_upload_success"));
    } catch (err) {
      setError(apiErrorToVisibleMessage(err, t("lut_library_upload_failed")));
    } finally {
      setIsUploading(false);
    }
  }, [refreshCatalog, t]);

  const openDetails = useCallback(async (item: LutDetailsCatalogItem) => {
    const store = useLutDetailsStore.getState();
    await store.fetchCatalog();
    useLutDetailsStore.getState().setQuery("");
    useLutDetailsStore.getState().selectManufacturer(item.manufacturer);
    useLutDetailsStore.getState().selectLut(item.name);
    setActiveTab("lut-details");
    void useLutDetailsStore.getState().loadSelectedLut();
  }, [setActiveTab]);

  const [expanded, setExpanded] = useState<string[]>(() => readPreference("lut-library-pins"));
  const [pinned, setPinned] = useState<string[]>(() => readPreference("lut-library-pins"));
  const [order, setOrder] = useState<string[]>(() => readPreference("lut-library-order"));
  const [searchCollapsed, setSearchCollapsed] = useState<string[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [dragged, setDragged] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  useEffect(() => {
    try {
      localStorage.setItem("lut-library-pins", JSON.stringify(pinned));
      localStorage.setItem("lut-library-order", JSON.stringify(order));
    } catch { /* Preferences remain usable in this session. */ }
  }, [pinned, order]);
  useEffect(() => {
    if (selectedPath) closeRef.current?.focus({ preventScroll: window.innerWidth >= 1024 });
  }, [selectedPath]);
  const selected = allItems.find((item) => item.path === selectedPath);
  const selectedIdentity = selected && identities.get(selected.path);
  const sortedGroups = useMemo(() => [...groupedItems].sort((a, b) => {
    const rank = (key: string) => { const index = order.indexOf(key); return index < 0 ? order.length : index; };
    return rank(a.manufacturer) - rank(b.manufacturer);
  }), [groupedItems, order]);
  const isExpanded = (key: string) => query.trim() ? !searchCollapsed.includes(key) : expanded.includes(key);
  const hasExpanded = sortedGroups.some((group) => isExpanded(group.manufacturer));
  const toggle = (key: string) => {
    const setter = query.trim() ? setSearchCollapsed : setExpanded;
    setter((previous) => previous.includes(key) ? previous.filter((value) => value !== key) : [...previous, key]);
  };
  const move = (from: string, to: string) => {
    const keys = [...new Set([...order, ...groupItems(allItems, t("lut_library_unknown")).map((group) => group.manufacturer)])];
    const start = keys.indexOf(from), end = keys.indexOf(to);
    if (start < 0 || end < 0 || start === end) return;
    keys.splice(start, 1); keys.splice(end, 0, from); setOrder(keys);
  };
  const closeDetails = () => { setSelectedPath(null); triggerRef.current?.focus(); };

  return (
    <motion.aside initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}
      data-testid="lut-library-panel" className="lut-library-workspace flex h-full min-h-0 w-full flex-col overflow-hidden">
      <div data-testid="lut-library-toolbar" style={{ borderBottomColor: scrolled ? "var(--surface-divider)" : "transparent" }}
        className="z-10 flex shrink-0 flex-col gap-3 border-b bg-slate-50 px-3 py-3 transition-colors duration-200 sm:px-5 xl:flex-row xl:items-center xl:justify-between dark:bg-slate-950">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
          <div className="relative min-w-48 flex-1 xl:max-w-sm">
            <svg aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></svg>
            <input type="search" data-testid="lut-library-search-input" aria-label={t("lut_library_search_placeholder")} placeholder={t("lut_library_search_placeholder")} value={query}
              onChange={(event) => { setQuery(event.target.value); setSearchCollapsed([]); setScrolled(false); if (scrollRef.current) scrollRef.current.scrollTop = 0; }}
              className="w-full rounded-lg border border-transparent bg-slate-100 py-2 pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-500 focus:border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:bg-slate-800 dark:text-slate-100" />
          </div>
          <p aria-live="polite" className="shrink-0 text-xs text-slate-500 dark:text-slate-400">{tRuntime("lut_library_inventory_summary", { count: filteredItems.length, brands: sortedGroups.length })}</p>
        </div>
        <div className="flex flex-wrap justify-end gap-3">
          <ResourceContribution kind="luts" />
          <Button label={t(hasExpanded ? "mat_gradient_library_collapse_all" : "mat_gradient_library_expand_all")} disabled={sortedGroups.length === 0}
            onClick={() => { const keys = sortedGroups.map((group) => group.manufacturer); if (query.trim()) setSearchCollapsed(hasExpanded ? keys : []); else setExpanded(hasExpanded ? [] : keys); }} />
          <Button label={t("lut_library_upload_btn")} onClick={() => uploadInputRef.current?.click()} loading={isUploading} disabled={isRefreshing} />
          <Button label={t("lut_library_refresh_btn")} onClick={() => void handleRefresh()} loading={isRefreshing} disabled={isUploading} />
          <input ref={uploadInputRef} type="file" accept=".npy,.json,.npz,.msgpack" className="hidden" onChange={(event) => void handleUpload(event)} />
        </div>
      </div>
      <div ref={scrollRef} data-testid="lut-library-scroll-content" onScroll={(event) => setScrolled(event.currentTarget.scrollTop > 1)}
        className="flex min-h-0 flex-1 flex-col gap-5 overflow-auto overscroll-y-contain px-3 py-4 sm:px-5">
        <TransientBanner data-testid="lut-library-success" message={success} onDismiss={() => setSuccess(null)} />
        <MaterialArchiveGuide compact />
        {error && <StatusBanner data-testid="lut-library-error" tone="error">{error}</StatusBanner>}
        {isLoading ? <p className="py-12 text-center text-sm text-slate-500">{t("lut_library_loading")}</p> : (
          <div className="resource-detail-layout grid items-start gap-5">
            <ResourceDetailsPanel open={!!selected && !!selectedIdentity} data-testid="lut-library-details" aria-label={t("lut_library_details_btn")}
              onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); closeDetails(); } }}
              className={`${cardPadClass} relative order-first min-w-0 lg:sticky lg:top-0 lg:order-last lg:col-start-2 lg:row-start-1 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto lg:overscroll-y-contain`}>
              <div className="absolute right-4 top-4"><CloseButton ref={closeRef} label={t("mat_gradient_library_history_close_btn")} onClick={closeDetails} /></div>
              {selected && selectedIdentity && <div className="grid gap-4">
                <LibraryIdentity {...selectedIdentity} subtitle={[selectedIdentity.brand, selected.material_type || selectedIdentity.materialType].filter(Boolean).join(" · ")}
                  thumbnail={{ kind: "luts", resourceKey: selected.path, name: selected.name, mode: selected.color_mode, display: selected.display }} />
                <div className="border-t panel-divider pt-3.5">
                  <LibraryFields rows={[
                    { label: t("lut_library_color_mode_label"), value: resourceColorMode(selected.color_mode, lang) || t("lut_library_unknown") },
                    { label: t("lut_library_path_label"), value: selected.path, multiline: true },
                  ]} />
                </div>
                <div className="grid gap-2 border-t panel-divider pt-3.5">
                  <Button label={t("lut_library_analyze_btn")} onClick={() => void openDetails(selected)} className="w-full" />
                  <ResourceContribution kind="luts" resourceKey={selected.name}
                    initialDisplay={{ brand: selected.manufacturer, material_type: selected.material_type, ...selected.display }} />
                </div>
              </div>}
            </ResourceDetailsPanel>
            <DndContext sensors={sensors} collisionDetection={closestCenter} modifiers={[restrictToVerticalAxis]}
              onDragStart={({ active }) => setDragged(String(active.id))} onDragCancel={() => setDragged(null)}
              onDragEnd={({ active, over }) => { if (over) move(String(active.id), String(over.id)); setDragged(null); }}>
              <SortableContext items={sortedGroups.map((group) => group.manufacturer)} strategy={verticalListSortingStrategy}>
                <div className="grid min-w-0 gap-6">
                  {allItems.length === 0 && !error && <ResourceLibraryEmpty kind="luts" onBrowse={(source) => {
                    useResourceStore.getState().setCatalogSource("luts", source);
                    setActiveTab("lut-cloud-sync");
                  }} onImport={() => uploadInputRef.current?.click()} onCalibrate={() => setActiveTab("calibration")} />}
                  {allItems.length > 0 && sortedGroups.length === 0 && <p data-testid="lut-library-no-match" role="status" className="py-12 text-center text-sm text-slate-500">{t("resources_no_matches")}</p>}
                  {sortedGroups.map((group, index) => <SortableLibraryBrand key={group.manufacturer} testIdPrefix="lut-library" groupKey={group.manufacturer} brand={group.manufacturer}
                    label={groupBrands.get(group.manufacturer)?.brand || group.manufacturer} logo={groupBrands.get(group.manufacturer)?.logo}
                    count={group.items.length} countLabel={tRuntime("lut_library_group_count", { count: group.items.length })}
                    collapsed={!isExpanded(group.manufacturer)} pinned={pinned.includes(group.manufacturer)} onToggle={() => toggle(group.manufacturer)}
                    onPin={() => { setPinned((previous) => previous.includes(group.manufacturer) ? previous.filter((key) => key !== group.manufacturer) : [...previous, group.manufacturer]); if (!pinned.includes(group.manufacturer)) setExpanded((previous) => [...new Set([...previous, group.manufacturer])]); }}
                    onMove={(direction) => { const target = sortedGroups[index + direction]; if (target) move(group.manufacturer, target.manufacturer); }}>
                    {isExpanded(group.manufacturer) && <div className="grid auto-rows-fr items-stretch gap-4 [grid-template-columns:repeat(auto-fill,min(100%,15rem))]">
                      {group.items.map((item) => {
                        const identity = identities.get(item.path)!;
                        const thumbnail = { kind: "luts" as const, name: item.name, mode: item.color_mode, display: item.display };
                        const metric = resourceColorMode(item.color_mode, lang) || undefined;
                        return <button key={item.path} type="button" data-testid="lut-library-card" aria-expanded={selectedPath === item.path}
                        onClick={(event) => { triggerRef.current = event.currentTarget; if (selectedPath === item.path) closeDetails(); else setSelectedPath(item.path); }}
                        className={`${cardPadClass} material-library-card flex min-w-0 flex-col items-stretch gap-3 text-left transition-colors`}>
                        <span className="flex min-w-0 items-start gap-3.5">
                          <CalibrationThumbnail {...thumbnail} />
                          <LibraryCardIdentity {...identity} subtitle={[identity.brand, item.material_type || identity.materialType].filter(Boolean).join(" · ")}
                            thumbnail={thumbnail} localVersion={item.local_version} showMeta={false} />
                        </span>
                        <LibraryCardPalette thumbnail={thumbnail} metric={metric} />
                      </button>; })}
                    </div>}
                  </SortableLibraryBrand>)}
                </div>
              </SortableContext>
              {createPortal(<DragOverlay dropAnimation={null}>{dragged && (() => {
                const group = sortedGroups.find((entry) => entry.manufacturer === dragged);
                const identity = groupBrands.get(dragged);
                return group ? <div aria-hidden="true" className="rounded-lg bg-slate-100 shadow-lg ring-1 ring-slate-300 dark:bg-slate-800 dark:ring-slate-600"><LibraryBrandHeader label={identity?.brand || dragged} logo={identity?.logo} count={group.items.length} countLabel={tRuntime("lut_library_group_count", { count: group.items.length })} collapsed={!isExpanded(dragged)} pinned={pinned.includes(dragged)} /></div> : null;
              })()}</DragOverlay>, document.body)}
            </DndContext>
          </div>
        )}
      </div>
    </motion.aside>
  );
}
