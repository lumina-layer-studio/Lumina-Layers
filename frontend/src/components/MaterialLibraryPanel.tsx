import { LibraryIdentity, LibraryFields } from "./ui/LibraryDetails";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { motion } from "framer-motion";
import { createPortal } from "react-dom";
import { DndContext, DragOverlay, PointerSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import { CheckIcon } from "@heroicons/react/24/outline";

import { apiErrorToVisibleMessage } from "../api/client";
import { tRuntime } from "../i18n/runtime";
import {
  deleteGradientCardMaterial,
  exportGradientCardMaterials,
  importGradientCardMaterials,
  listGradientCardMaterials,
  updateGradientCardMaterial,
} from "../api/extractor";
import type { SavedMaterialLibraryItem } from "../api/types";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useWidgetStore } from "../stores/widgetStore";

import { normalizeResourceUrl } from "../utils/resourceUrl";
import Button from "./ui/Button";
import CloseButton from "./ui/CloseButton";
import { LibraryBrandHeader as MaterialBrandHeader, SortableLibraryBrand as SortableMaterialBrand } from "./ui/LibraryBrandGroup";
import {
  StatusBanner,
  cardPadClass,
  mutedSectionCardClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";

const isRgbTriplet = (value: number[] | null | undefined): value is [number, number, number] =>
  Array.isArray(value) && value.length === 3;

const PINNED_BRANDS_STORAGE_KEY = "lumina-material-library-pinned-brands";
const BRAND_ORDER_STORAGE_KEY = "lumina-material-library-brand-order";
function readBrandPreference(storageKey: string): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(storageKey) ?? "[]");
    return Array.isArray(value) ? value.filter((key): key is string => typeof key === "string") : [];
  } catch {
    return [];
  }
}

const toRgbCss = (rgb: [number, number, number]) => `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;

const clampChannel = (channel: number): number =>
  Math.max(0, Math.min(255, Math.round(Number.isFinite(channel) ? channel : 0)));

const toHex = (rgb: [number, number, number]) =>
  `#${rgb
    .map((channel) => clampChannel(channel).toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;

const HEX_COLOR_PATTERN = /^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

const parseHexColor = (hex: string): [number, number, number] | null => {
  const match = HEX_COLOR_PATTERN.exec(hex.trim());
  if (!match) {
    return null;
  }
  const digits = match[1];
  const expanded = digits.length === 3
    ? digits.split("").map((char) => char + char).join("")
    : digits;
  const r = Number.parseInt(expanded.slice(0, 2), 16);
  const g = Number.parseInt(expanded.slice(2, 4), 16);
  const b = Number.parseInt(expanded.slice(4, 6), 16);
  return [r, g, b];
};

const DEFAULT_EDIT_COLOR: [number, number, number] = [128, 128, 128];

const formatNumericValue = (value: number | null | undefined, digits = 3) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";

const formatNumericVector = (values: number[] | null | undefined, digits = 3) =>
  Array.isArray(values) && values.length > 0
    ? values.map((value) => formatNumericValue(value, digits)).join(", ")
    : "-";

const triggerDownload = (url: string, filename?: string) => {
  const link = document.createElement("a");
  link.href = url;
  if (filename) {
    link.download = filename;
  }
  document.body.appendChild(link);
  link.click();
  link.remove();
};

const textInputClass =
  "min-h-10 w-full rounded-2xl border border-slate-200/80 bg-white/90 px-3 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-100";

const colorPickerInputClass =
  "h-10 w-14 shrink-0 cursor-pointer rounded-2xl border border-slate-200/80 bg-white/90 p-1 shadow-[var(--shadow-control)] dark:border-slate-700/80 dark:bg-slate-900";

const normalizeLibraryItem = (item: SavedMaterialLibraryItem): SavedMaterialLibraryItem => ({
  ...item,
  material_file_url: normalizeResourceUrl(item.material_file_url) ?? item.material_file_url,
  stage_a_params_url: normalizeResourceUrl(item.stage_a_params_url) ?? item.stage_a_params_url,
});

const getMaterialBrand = (item: SavedMaterialLibraryItem): string | null => {
  const brand = item.brand?.trim();
  return brand ? brand : null;
};

const UNASSIGNED_BRAND_GROUP_KEY = "__unassigned__";

const getMaterialBrandGroupKey = (brand: string | null): string =>
  brand ?? UNASSIGNED_BRAND_GROUP_KEY;

const normalizeMaterialIdentityText = (value: string | null | undefined): string =>
  (value ?? "").trim().toLocaleLowerCase();

const getMaterialIdentityKey = (item: SavedMaterialLibraryItem): string =>
  `${normalizeMaterialIdentityText(getMaterialBrand(item))}\u0000${normalizeMaterialIdentityText(item.material_name)}`;

const getMaterialSortTimestamp = (item: SavedMaterialLibraryItem): number => {
  const value = item.updated_at || item.created_at;
  if (!value) {
    return 0;
  }
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
};

const compareMaterialLibraryItems = (
  left: SavedMaterialLibraryItem,
  right: SavedMaterialLibraryItem,
): number => {
  const leftName = normalizeMaterialIdentityText(left.material_name);
  const rightName = normalizeMaterialIdentityText(right.material_name);
  const byName = leftName.localeCompare(rightName);
  if (byName !== 0) {
    return byName;
  }
  const byTimestamp = getMaterialSortTimestamp(right) - getMaterialSortTimestamp(left);
  if (byTimestamp !== 0) {
    return byTimestamp;
  }
  return left.directory_name.localeCompare(right.directory_name);
};

type MaterialLibraryBrandGroup = {
  brand: string | null;
  items: SavedMaterialLibraryItem[];
};

const formatMaterialLibraryError = (
  error: unknown,
  fallbackKey: string,
  t: (key: string) => string,
): string => apiErrorToVisibleMessage(error, t(fallbackKey));

export default function MaterialLibraryPanel() {
  const { t, lang } = useI18n();
  const workspace = useWorkspaceMode();
  const setActiveTab = useWidgetStore((state) => state.setActiveTab);
  const startMaterialVerification = useSingleStageStore((state) => state.startMaterialVerification);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const listScrollRef = useRef<HTMLDivElement | null>(null);
  const [listScrolled, setListScrolled] = useState(false);
  const [materials, setMaterials] = useState<SavedMaterialLibraryItem[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchCollapsedBrands, setSearchCollapsedBrands] = useState<string[]>([]);
  const searchTerm = searchQuery.trim().toLocaleLowerCase();
  const [selectionMode, setSelectionMode] = useState(false);
  const [detailDirectory, setDetailDirectory] = useState<string | null>(null);
  const detailCloseRef = useRef<HTMLButtonElement | null>(null);
  const detailTriggerRef = useRef<HTMLButtonElement | null>(null);
  const detailMaterial = materials.find((item) => item.directory_name === detailDirectory);
  useEffect(() => {
    if (detailDirectory) detailCloseRef.current?.focus({ preventScroll: window.innerWidth >= 1024 });
  }, [detailDirectory]);
  const closeDetails = () => {
    setDetailDirectory(null);
    detailTriggerRef.current?.focus();
  };
  const [isLoading, setIsLoading] = useState(true);
  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [pendingDeleteDirectoryName, setPendingDeleteDirectoryName] = useState<string | null>(null);
  const [pendingUpdateDirectoryName, setPendingUpdateDirectoryName] = useState<string | null>(null);
  const [historyMaterial, setHistoryMaterial] = useState<SavedMaterialLibraryItem | null>(null);
  const [selectedDirectoryNames, setSelectedDirectoryNames] = useState<string[]>([]);
  const [editingMaterial, setEditingMaterial] = useState<SavedMaterialLibraryItem | null>(null);
  const [pinnedBrandGroupKeys, setPinnedBrandGroupKeys] = useState<string[]>(() => readBrandPreference(PINNED_BRANDS_STORAGE_KEY));
  const [brandOrder, setBrandOrder] = useState<string[]>(() => readBrandPreference(BRAND_ORDER_STORAGE_KEY));
  const [draggedBrand, setDraggedBrand] = useState<string | null>(null);
  const brandSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  useEffect(() => {
    try {
      localStorage.setItem(BRAND_ORDER_STORAGE_KEY, JSON.stringify(brandOrder));
    } catch {
      // Sorting still works for this session when storage is unavailable.
    }
  }, [brandOrder]);
  const [expandedBrandGroupKeys, setExpandedBrandGroupKeys] = useState<string[]>(() => [...pinnedBrandGroupKeys]);
  useEffect(() => {
    try {
      localStorage.setItem(PINNED_BRANDS_STORAGE_KEY, JSON.stringify(pinnedBrandGroupKeys));
    } catch {
      // Keep the current session usable when browser storage is unavailable.
    }
  }, [pinnedBrandGroupKeys]);

  const refreshMaterials = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listGradientCardMaterials();
      const nextMaterials = (response.materials ?? []).map(normalizeLibraryItem);
      setMaterials(nextMaterials);
      setHistoryMaterial((previous) =>
        previous
          ? nextMaterials.find((item) => item.directory_name === previous.directory_name) ?? null
          : null,
      );
      setSelectedDirectoryNames((previous) =>
        previous.filter((directoryName) =>
          nextMaterials.some((item) => item.directory_name === directoryName),
        ),
      );
      return nextMaterials;
    } catch (err) {
      setError(formatMaterialLibraryError(err, "mat_gradient_library_load_failed", t));
      setMaterials([]);
      setSelectedDirectoryNames([]);
      return [];
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refreshMaterials();
  }, [refreshMaterials]);

  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    }),
    [lang],
  );

  const formatCreatedAt = useCallback((value: string | null | undefined) => {
    if (!value) {
      return "-";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return dateFormatter.format(parsed);
  }, [dateFormatter]);

  const selectedCount = selectedDirectoryNames.length;
  const materialDuplicateCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of materials) {
      const key = getMaterialIdentityKey(item);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [materials]);
  const groupedMaterials = useMemo<MaterialLibraryBrandGroup[]>(() => {
    const groups = new Map<string, SavedMaterialLibraryItem[]>();
    const unassigned: SavedMaterialLibraryItem[] = [];
    for (const item of materials) {
      const brand = getMaterialBrand(item);
      if (!brand) {
        unassigned.push(item);
        continue;
      }
      const existing = groups.get(brand);
      if (existing) {
        existing.push(item);
      } else {
        groups.set(brand, [item]);
      }
    }
    const result: MaterialLibraryBrandGroup[] = Array.from(groups, ([brand, items]) => ({
      brand,
      items: [...items].sort(compareMaterialLibraryItems),
    }));
    if (unassigned.length > 0) {
      result.push({ brand: null, items: [...unassigned].sort(compareMaterialLibraryItems) });
    }
    const positions = new Map(brandOrder.map((key, index) => [key, index]));
    return result.sort((a, b) =>
      (positions.get(getMaterialBrandGroupKey(a.brand)) ?? brandOrder.length)
      - (positions.get(getMaterialBrandGroupKey(b.brand)) ?? brandOrder.length));
  }, [materials, brandOrder]);

  const visibleGroups = useMemo(() => groupedMaterials.map((group) => ({
    ...group,
    items: group.items.filter((item) => !searchTerm || [item.material_name, group.brand ?? t("mat_gradient_library_brand_unassigned"), item.material_type]
      .some((value) => value?.toLocaleLowerCase().includes(searchTerm))),
  })).filter((group) => group.items.length > 0), [groupedMaterials, searchTerm, t]);
  const visibleMaterials = visibleGroups.flatMap(({ items }) => items);
  const allSelected = visibleMaterials.length > 0 && visibleMaterials.every((item) => selectedDirectoryNames.includes(item.directory_name));
  const groupIsExpanded = (key: string) => searchTerm ? !searchCollapsedBrands.includes(key) : expandedBrandGroupKeys.includes(key);

  const moveBrand = (source: string, target: string) => {
    const keys = groupedMaterials.map(({ brand }) => getMaterialBrandGroupKey(brand));
    const from = keys.indexOf(source);
    const to = keys.indexOf(target);
    if (from < 0 || to < 0 || from === to) return;
    keys.splice(from, 1);
    keys.splice(to, 0, source);
    setBrandOrder(keys);
  };

  const hasExpandedBrand = visibleGroups.some(({ brand }) => groupIsExpanded(getMaterialBrandGroupKey(brand)));

  const handleStartVerification = useCallback((item: SavedMaterialLibraryItem) => {
    startMaterialVerification({
      materialName: item.material_name,
      directoryName: item.directory_name,
      verificationCount: item.verification_count ?? 1,
    });
    setActiveTab("gradient-card-extract");
  }, [setActiveTab, startMaterialVerification]);

  const handleOpenEditDialog = useCallback((item: SavedMaterialLibraryItem) => {
    setEditingMaterial(item);
    setError(null);
    setSuccess(null);
  }, []);

  const handleCloseEditDialog = useCallback(() => {
    setEditingMaterial(null);
  }, []);

  const handleOpenHistoryDialog = useCallback((item: SavedMaterialLibraryItem) => {
    setHistoryMaterial(item);
  }, []);

  const handleCloseHistoryDialog = useCallback(() => {
    setHistoryMaterial(null);
  }, []);

  const handleSaveEditDialog = useCallback(
    async (values: {
      materialName: string;
      brand: string | null;
      estimatedRgb: [number, number, number];
    }) => {
      if (!editingMaterial) {
        return;
      }
      const directoryName = editingMaterial.directory_name;
      setPendingUpdateDirectoryName(directoryName);
      setError(null);
      setSuccess(null);
      try {
        const response = await updateGradientCardMaterial(directoryName, {
          materialName: values.materialName,
          brand: values.brand,
          estimatedRgb: values.estimatedRgb,
        });
        const nextItem = normalizeLibraryItem(response.material);
        setMaterials((previous) =>
          previous.map((item) =>
            item.directory_name === directoryName ? nextItem : item,
          ),
        );
        setSuccess(response.message || t("mat_gradient_library_edit_success"));
        setEditingMaterial(null);
      } catch (err) {
        setError(formatMaterialLibraryError(err, "mat_gradient_library_edit_failed", t));
      } finally {
        setPendingUpdateDirectoryName(null);
      }
    },
    [editingMaterial, t],
  );

  const handleDeleteMaterial = useCallback(async (item: SavedMaterialLibraryItem) => {
    const confirmed = window.confirm(
      tRuntime("mat_gradient_library_delete_confirm", {
        materialName: item.material_name,
        directoryName: item.directory_name,
        updatedAt: formatCreatedAt(item.updated_at || item.created_at),
      }),
    );
    if (!confirmed) {
      return;
    }
    setPendingDeleteDirectoryName(item.directory_name);
    setError(null);
    try {
      await deleteGradientCardMaterial(item.directory_name);
      setMaterials((previous) =>
        previous.filter((entry) => entry.directory_name !== item.directory_name),
      );
      setHistoryMaterial((previous) =>
        previous?.directory_name === item.directory_name ? null : previous,
      );
      setSelectedDirectoryNames((previous) =>
        previous.filter((directoryName) => directoryName !== item.directory_name),
      );
      setSuccess(t("mat_gradient_library_delete_success"));
    } catch (err) {
      setError(formatMaterialLibraryError(err, "mat_gradient_library_delete_failed", t));
    } finally {
      setPendingDeleteDirectoryName(null);
    }
  }, [formatCreatedAt, t]);

  const toggleMaterialSelection = useCallback((directoryName: string) => {
    setSelectedDirectoryNames((previous) =>
      previous.includes(directoryName)
        ? previous.filter((item) => item !== directoryName)
        : [...previous, directoryName],
    );
  }, []);

  const toggleSelectAll = () => {
    const visibleKeys = new Set(visibleMaterials.map((item) => item.directory_name));
    setSelectedDirectoryNames((previous) => allSelected
      ? previous.filter((key) => !visibleKeys.has(key))
      : [...new Set([...previous, ...visibleKeys])]);
  };

  const toggleBrandGroupCollapsed = (groupKey: string) => {
    const setKeys = searchTerm ? setSearchCollapsedBrands : setExpandedBrandGroupKeys;
    setKeys((previous) => previous.includes(groupKey) ? previous.filter((key) => key !== groupKey) : [...previous, groupKey]);
  };

  const handleExportSelected = useCallback(async () => {
    if (selectedDirectoryNames.length === 0) {
      setError(t("mat_gradient_library_export_requires_selection"));
      return;
    }
    setIsExporting(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await exportGradientCardMaterials(selectedDirectoryNames);
      const downloadUrl = normalizeResourceUrl(response.download_url) ?? response.download_url;
      triggerDownload(downloadUrl, response.filename);
      setSuccess(response.message || t("mat_gradient_library_export_success"));
    } catch (err) {
      setError(formatMaterialLibraryError(err, "mat_gradient_library_export_failed", t));
    } finally {
      setIsExporting(false);
    }
  }, [selectedDirectoryNames, t]);

  const handleImportClick = useCallback(() => {
    setError(null);
    setSuccess(null);
    importInputRef.current?.click();
  }, []);

  const handleImportArchives = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length === 0) {
      return;
    }
    setIsImporting(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await importGradientCardMaterials(files);
      const refreshedMaterials = await refreshMaterials();
      const importedDirectoryNames = (response.imported_materials ?? [])
        .map((item) => item.directory_name)
        .filter((directoryName) =>
          refreshedMaterials.some((material) => material.directory_name === directoryName),
        );
      setSelectedDirectoryNames(importedDirectoryNames);
      setSelectionMode(importedDirectoryNames.length > 0);
      setSuccess(response.message || t("mat_gradient_library_import_success"));
    } catch (err) {
      setError(formatMaterialLibraryError(err, "mat_gradient_library_import_failed", t));
    } finally {
      setIsImporting(false);
    }
  }, [refreshMaterials, t]);

  const renderMaterialDetails = (item: SavedMaterialLibraryItem) => {
    const rgb = isRgbTriplet(item.estimated_rgb) ? item.estimated_rgb : null;
    const busy = pendingDeleteDirectoryName === item.directory_name || pendingUpdateDirectoryName === item.directory_name;
    return (
      <div className="grid min-w-0 gap-5">
        <LibraryIdentity name={item.material_name} subtitle={`${getMaterialBrand(item) ?? t("mat_gradient_library_brand_unassigned")} · ${item.material_type?.trim() || t("mat_gradient_library_type_missing")}`} color={rgb ? toRgbCss(rgb) : undefined}>
          {item.sync_official && <span data-testid="material-library-official-badge" className="mt-2 block text-xs text-slate-500">{t("mat_sync_official_badge")}</span>}
        </LibraryIdentity>
        <LibraryFields rows={[
          { label: t("mat_gradient_library_fit_error_label"), value: formatNumericValue(item.mean_delta_e, 2) },
          { label: t("mat_gradient_library_layer_height_label"), value: typeof item.layer_height_mm === "number" ? `${item.layer_height_mm.toFixed(2)} mm` : "—" },
          { label: t("mat_gradient_library_verification_count_label"), value: Math.max(1, Number(item.verification_count ?? 1)) },
        ]} />
        <div data-testid="material-library-item-usage" className="grid gap-3">
          <LibraryFields rows={[{ label: t("mat_gradient_library_usage_count_label"), value: Number(item.usage_total ?? 0) }]} />
          {item.usage_by_color_mode && <ul className="grid gap-1 text-xs text-slate-500 dark:text-slate-400">{Object.entries(item.usage_by_color_mode).sort((left, right) => right[1] - left[1]).map(([mode, count]) => <li key={mode} className="flex justify-between gap-2"><span>{mode}</span><span>{count}</span></li>)}</ul>}
          {item.usage_last_used_at && <p className="text-xs text-slate-500">{tRuntime("mat_gradient_library_usage_last_used", { when: formatCreatedAt(item.usage_last_used_at) })}</p>}
        </div>
        <LibraryFields rows={[
          { label: t("mat_gradient_library_created_at_label"), value: formatCreatedAt(item.created_at) },
          { label: t("mat_gradient_library_updated_at_label"), value: formatCreatedAt(item.updated_at) },
          { label: t("mat_gradient_library_directory_label"), value: item.directory_name, multiline: true },
        ]} />
        <div className="grid grid-cols-2 gap-2">
          <Button label={t("mat_gradient_library_edit_btn")} variant="secondary" onClick={() => handleOpenEditDialog(item)} disabled={busy} />
          <Button label={t("mat_gradient_library_reverify_btn")} variant="secondary" onClick={() => handleStartVerification(item)} disabled={busy} />
          <Button label={t("mat_gradient_library_show_history_btn")} variant="secondary" onClick={() => handleOpenHistoryDialog(item)} disabled={busy} />
          <Button label={t("mat_gradient_library_delete_btn")} variant="secondary" tone="danger" onClick={() => void handleDeleteMaterial(item)} disabled={busy} loading={pendingDeleteDirectoryName === item.directory_name} />
        </div>
      </div>
    );
  };

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="material-library-panel"
      className="material-library-workspace flex h-full min-h-0 w-full flex-col overflow-hidden"
    >
      <input
        ref={importInputRef}
        type="file"
        accept=".zip,application/zip"
        multiple
        className="hidden"
        data-testid="material-library-import-input"
        onChange={(event) => void handleImportArchives(event)}
      />

      <div data-testid="material-library-toolbar"
        style={{ borderBottomColor: listScrolled ? "var(--surface-divider)" : "transparent" }}
        className="z-10 flex shrink-0 flex-col gap-3 border-b bg-slate-50 px-3 py-3 transition-colors duration-200 sm:px-5 xl:flex-row xl:items-center xl:justify-between dark:bg-slate-950">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
          <div className="relative min-w-48 flex-1 xl:max-w-sm">
            <svg aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></svg>
            <input type="search" aria-label={t("mat_gradient_library_search")} placeholder={t("mat_gradient_library_search")}
              value={searchQuery} onChange={(event) => {
                setSearchQuery(event.target.value);
                setSearchCollapsedBrands([]);
                if (listScrollRef.current) listScrollRef.current.scrollTop = 0;
                setListScrolled(false);
              }}
              className="w-full rounded-lg border border-transparent bg-slate-100 py-2 pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-500 focus:border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:bg-slate-800 dark:text-slate-100" />
          </div>
          <p aria-live="polite" className="shrink-0 text-xs text-slate-500 dark:text-slate-400">
            {selectionMode ? tRuntime("mat_gradient_library_selection_summary", { selected: selectedCount, total: materials.length }) : tRuntime("mat_gradient_library_inventory_summary", { count: visibleMaterials.length, brands: visibleGroups.length })}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3">
          <Button
            label={t(hasExpandedBrand ? "mat_gradient_library_collapse_all" : "mat_gradient_library_expand_all")}
            variant="secondary"
            onClick={() => {
              const keys = visibleGroups.map(({ brand }) => getMaterialBrandGroupKey(brand));
              if (searchTerm) setSearchCollapsedBrands(hasExpandedBrand ? keys : []);
              else setExpandedBrandGroupKeys(hasExpandedBrand ? [] : keys);
            }}
            disabled={visibleGroups.length === 0}
          />
          <Button
            label={t(selectionMode ? "mat_gradient_library_selection_done" : "mat_gradient_library_selection_start")}
            variant="secondary"
            onClick={() => { setSelectionMode(!selectionMode); setSelectedDirectoryNames([]); setDetailDirectory(null); }}
          />
          {selectionMode && <Button
            label={t(
              allSelected
                ? "mat_gradient_library_clear_selection_btn"
                : "mat_gradient_library_select_all_btn",
            )}
            variant="secondary"
            onClick={toggleSelectAll}
            disabled={visibleMaterials.length === 0 || isLoading || isExporting || isImporting}
          />}
          <Button
            label={t("mat_gradient_library_import_btn")}
            title={t("mat_gradient_library_import_hint")}
            variant="secondary"
            onClick={handleImportClick}
            disabled={isLoading || isExporting || pendingDeleteDirectoryName !== null}
            loading={isImporting}
          />
          {selectionMode && <Button
            label={t("mat_gradient_library_export_btn")}
            variant="secondary"
            onClick={() => void handleExportSelected()}
            disabled={selectedCount === 0 || isLoading || isImporting || pendingDeleteDirectoryName !== null}
            loading={isExporting}
          />}
          <Button
            label={t("mat_gradient_library_refresh_btn")}
            variant="secondary"
            onClick={() => void refreshMaterials()}
            disabled={isLoading || isImporting || isExporting}
            loading={isLoading}
          />
        </div>
      </div>

      <div ref={listScrollRef} data-testid="material-library-scroll-content"
        onScroll={(event) => setListScrolled(event.currentTarget.scrollTop > 1)}
        className="flex min-h-0 flex-1 flex-col gap-5 overflow-auto overscroll-y-contain px-3 py-4 sm:px-5">
      {error ? (
        <StatusBanner data-testid="material-library-error" tone="error">
          {error}
        </StatusBanner>
      ) : null}

      {success ? (
        <StatusBanner data-testid="material-library-success" tone="success">
          {success}
        </StatusBanner>
      ) : null}

      {editingMaterial ? (
        <MaterialLibraryEditDialog
          item={editingMaterial}
          pending={pendingUpdateDirectoryName === editingMaterial.directory_name}
          onCancel={handleCloseEditDialog}
          onSave={handleSaveEditDialog}
        />
      ) : null}

      {historyMaterial ? (
        <div
          data-testid="material-library-history-dialog-overlay"
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "var(--surface-scrim)" }}
          onClick={handleCloseHistoryDialog}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-label={t("mat_gradient_library_history_title")}
            data-testid="material-library-history-dialog"
            className="relative flex max-h-[85vh] w-full max-w-5xl flex-col gap-4 overflow-hidden rounded-[28px] border p-4 shadow-2xl sm:p-5"
            style={{
              borderColor: "var(--surface-outline)",
              background: "var(--surface-panel-strong)",
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
                  {t("mat_gradient_library_history_title")}
                </h3>
                <p className="mt-1 truncate text-sm text-slate-500 dark:text-slate-400">
                  {historyMaterial.material_name}
                </p>
              </div>
              <CloseButton label={t("mat_gradient_library_history_close_btn")} onClick={handleCloseHistoryDialog} />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className={`${mutedSectionCardClass} px-4 py-3`}>
                <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  {t("mat_gradient_library_directory_label")}
                </dt>
                <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                  {historyMaterial.directory_name}
                </dd>
              </div>
              <div className={`${mutedSectionCardClass} px-4 py-3`}>
                <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  {t("mat_gradient_library_verification_count_label")}
                </dt>
                <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                  {Math.max(
                    historyMaterial.verification_history?.length ?? 0,
                    Number(historyMaterial.verification_count ?? 0),
                    0,
                  )}
                </dd>
              </div>
            </div>

            <div className="overflow-y-auto overscroll-y-contain pr-1">
              {(historyMaterial.verification_history?.length ?? 0) === 0 ? (
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  {t("mat_gradient_library_history_empty")}
                </p>
              ) : (
                <div className="grid gap-3">
                  {[...(historyMaterial.verification_history ?? [])]
                    .sort((left, right) => right.verification_index - left.verification_index)
                    .map((historyItem) => {
                      const historyRgb = isRgbTriplet(historyItem.estimated_rgb)
                        ? historyItem.estimated_rgb
                        : null;
                      const historyHex = historyRgb ? toHex(historyRgb) : "-";
                      return (
                        <article
                          key={`${historyMaterial.directory_name}-history-${historyItem.verification_index}`}
                          data-testid="material-library-history-item"
                          className={`${mutedSectionCardClass} p-4`}
                        >
                          <div className="flex items-start gap-4">
                            <div
                              className="h-12 w-12 shrink-0 rounded-2xl border border-slate-200/80 dark:border-slate-700/80"
                              style={historyRgb ? { backgroundColor: toRgbCss(historyRgb) } : undefined}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <h5 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                                  {tRuntime("mat_gradient_library_history_run_label", {
                                    index: historyItem.verification_index,
                                  })}
                                </h5>
                                <span className="text-xs text-slate-500 dark:text-slate-400">
                                  {formatCreatedAt(historyItem.captured_at)}
                                </span>
                              </div>
                              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                                {historyHex}
                              </p>
                            </div>
                          </div>

                          <dl className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_time_label")}
                              </dt>
                              <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {formatCreatedAt(historyItem.captured_at)}
                              </dd>
                            </div>
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_fit_error_label")}
                              </dt>
                              <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {formatNumericValue(historyItem.mean_delta_e, 2)}
                              </dd>
                            </div>
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_rmse_label")}
                              </dt>
                              <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {formatNumericValue(historyItem.rmse_linear, 4)}
                              </dd>
                            </div>
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_color_label")}
                              </dt>
                              <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {historyRgb ? historyRgb.join(", ") : "-"}
                              </dd>
                            </div>
                            <div className={`${mutedSectionCardClass} px-3 py-3 sm:col-span-2 xl:col-span-2`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_orientation_label")}
                              </dt>
                              <dd className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {tRuntime("mat_gradient_library_history_orientation_value", {
                                  white: historyItem.white_detected_orientation || "-",
                                  black: historyItem.black_detected_orientation || "-",
                                })}
                              </dd>
                            </div>
                          </dl>

                          <dl className="mt-3 grid gap-3">
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_e_label")}
                              </dt>
                              <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {formatNumericVector(historyItem.e_values)}
                              </dd>
                            </div>
                            <div className={`${mutedSectionCardClass} px-3 py-3`}>
                              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                {t("mat_gradient_library_history_k_label")}
                              </dt>
                              <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {formatNumericVector(historyItem.k_values)}
                              </dd>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2">
                              <div className={`${mutedSectionCardClass} px-3 py-3`}>
                                <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                  {t("mat_gradient_library_history_white_c0_label")}
                                </dt>
                                <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                                  {formatNumericVector(historyItem.white_c0_values)}
                                </dd>
                              </div>
                              <div className={`${mutedSectionCardClass} px-3 py-3`}>
                                <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                                  {t("mat_gradient_library_history_black_c0_label")}
                                </dt>
                                <dd className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
                                  {formatNumericVector(historyItem.black_c0_values)}
                                </dd>
                              </div>
                            </div>
                          </dl>
                        </article>
                      );
                    })}
                </div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {isLoading ? (
        <section className={`${resolveSectionCardClass(workspace.mode)} flex min-h-48 items-center justify-center`}>
          <p className="text-sm text-slate-500 dark:text-slate-400">{t("mat_gradient_library_loading")}</p>
        </section>
      ) : materials.length === 0 ? (
        <section className={`${resolveSectionCardClass(workspace.mode)} flex min-h-48 items-center justify-center`}>
          <p className="max-w-lg text-center text-sm text-slate-500 dark:text-slate-400">{t("mat_gradient_library_empty")}</p>
        </section>
      ) : visibleGroups.length === 0 ? (
        <p role="status" className="py-12 text-center text-sm text-slate-500">{t("mat_gradient_library_search_empty")}</p>
      ) : (
        <div className={`grid items-start gap-5 ${detailMaterial ? "lg:grid-cols-[minmax(0,1fr)_22rem]" : ""}`}>
          {detailMaterial && (
            <section aria-label={t("mat_gradient_library_details")} data-testid="material-library-details" className={`${cardPadClass} relative order-first min-w-0 lg:sticky lg:top-0 lg:order-last lg:col-start-2 lg:row-start-1 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto lg:overscroll-y-contain`} onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); closeDetails(); } }}>
              <div className="absolute right-4 top-3"><CloseButton ref={detailCloseRef} label={t("mat_gradient_library_history_close_btn")} onClick={closeDetails} /></div>
              {renderMaterialDetails(detailMaterial)}
            </section>
          )}
          <DndContext
            sensors={brandSensors}
            collisionDetection={closestCenter}
            modifiers={[restrictToVerticalAxis]}
            onDragStart={({ active }) => setDraggedBrand(String(active.id))}
            onDragCancel={() => setDraggedBrand(null)}
            onDragEnd={({ active, over }) => {
              if (over) moveBrand(String(active.id), String(over.id));
              setDraggedBrand(null);
            }}
          >
          <SortableContext items={visibleGroups.map(({ brand }) => getMaterialBrandGroupKey(brand))} strategy={verticalListSortingStrategy}>
          <div className="grid min-w-0 gap-6">
          {visibleGroups.map(({ brand, items }) => {
            const groupKey = getMaterialBrandGroupKey(brand);
            const groupLabel = brand ?? t("mat_gradient_library_brand_unassigned");
            const isCollapsed = !groupIsExpanded(groupKey);
            const isPinned = pinnedBrandGroupKeys.includes(groupKey);
            return (
              <SortableMaterialBrand
                key={groupKey}
                groupKey={groupKey}
                brand={brand}
                label={groupLabel}
                count={items.length}
                collapsed={isCollapsed}
                pinned={isPinned}
                onToggle={() => toggleBrandGroupCollapsed(groupKey)}
                onPin={() => {
                  setPinnedBrandGroupKeys((previous) => isPinned ? previous.filter((key) => key !== groupKey) : [...previous, groupKey]);
                  if (!isPinned) setExpandedBrandGroupKeys((previous) => [...new Set([...previous, groupKey])]);
                }}
                onMove={(direction) => {
                  const index = groupedMaterials.findIndex(({ brand }) => getMaterialBrandGroupKey(brand) === groupKey);
                  const target = groupedMaterials[index + direction];
                  if (target) moveBrand(groupKey, getMaterialBrandGroupKey(target.brand));
                }}
              >
                {isCollapsed ? null : (
                  <div className="grid auto-rows-fr items-stretch gap-4 [grid-template-columns:repeat(auto-fill,min(100%,15rem))]">
                {items.map((item) => {
                  const rgb = isRgbTriplet(item.estimated_rgb) ? item.estimated_rgb : null;
                  const selected = selectedDirectoryNames.includes(item.directory_name);
                  return (
                    <button
                      type="button"
                      key={item.directory_name}
                      data-testid="material-library-item"
                      aria-pressed={selectionMode ? selected : undefined}
                      aria-expanded={!selectionMode ? detailDirectory === item.directory_name : undefined}
                      onClick={(event) => {
                        if (selectionMode) {
                          toggleMaterialSelection(item.directory_name);
                        } else {
                          detailTriggerRef.current = event.currentTarget;
                          setDetailDirectory(item.directory_name);
                        }
                      }}
                      className={`${cardPadClass} material-library-card relative flex min-w-0 items-center gap-4 text-left transition-colors`}
                    >
                      {selectionMode && <span aria-hidden="true" className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border text-xs ${selected ? "border-blue-500 bg-blue-500 text-white" : "border-slate-300 dark:border-slate-600"}`}>{selected && <CheckIcon className="h-3.5 w-3.5" />}</span>}
                      <span aria-hidden="true" className="h-14 w-14 shrink-0 rounded-xl border border-black/10 bg-slate-100 dark:border-white/15 dark:bg-slate-800" style={rgb ? { backgroundColor: toRgbCss(rgb) } : undefined} />
                      <span className="min-w-0 flex-1">
                        <span className="material-library-card-name block break-words text-sm font-semibold">{item.material_name}</span>
                        <span className="material-library-card-meta mt-2 block text-xs">{item.material_type?.trim() || t("mat_gradient_library_type_missing")}</span>
                        <span data-testid="material-library-card-fit-error" className="material-library-card-meta mt-1 block text-xs tabular-nums">{t("mat_gradient_library_fit_error_label")} {formatNumericValue(item.mean_delta_e, 2)}</span>
                        {(materialDuplicateCounts.get(getMaterialIdentityKey(item)) ?? 0) > 1 && <span data-testid="material-library-duplicate-badge" className="material-library-card-meta mt-1 block text-[11px] tabular-nums">{formatCreatedAt(item.updated_at || item.created_at)}</span>}
                      </span>
                    </button>
                  );
                })}
                  </div>
                )}
              </SortableMaterialBrand>
            );
          })}
          </div>
          </SortableContext>
          {createPortal(
            <DragOverlay dropAnimation={null}>
              {draggedBrand !== null && (() => {
                const group = visibleGroups.find(({ brand }) => getMaterialBrandGroupKey(brand) === draggedBrand);
                return group ? <div className="rounded-lg bg-slate-100 shadow-lg ring-1 ring-slate-300 dark:bg-slate-800 dark:ring-slate-600" aria-hidden="true">
                  <MaterialBrandHeader label={group.brand ?? t("mat_gradient_library_brand_unassigned")} count={group.items.length} collapsed={!groupIsExpanded(draggedBrand)} pinned={pinnedBrandGroupKeys.includes(draggedBrand)} />
                </div> : null;
              })()}
            </DragOverlay>, document.body,
          )}
          </DndContext>
        </div>
      )}
      </div>
    </motion.aside>
  );
}

interface MaterialLibraryEditDialogProps {
  item: SavedMaterialLibraryItem;
  pending: boolean;
  onCancel: () => void;
  onSave: (values: {
    materialName: string;
    brand: string | null;
    estimatedRgb: [number, number, number];
  }) => void;
}

function MaterialLibraryEditDialog({
  item,
  pending,
  onCancel,
  onSave,
}: MaterialLibraryEditDialogProps) {
  const { t } = useI18n();

  const initialColor = useMemo<[number, number, number]>(() => {
    if (!isRgbTriplet(item.estimated_rgb)) {
      return DEFAULT_EDIT_COLOR;
    }
    return [
      clampChannel(item.estimated_rgb[0]),
      clampChannel(item.estimated_rgb[1]),
      clampChannel(item.estimated_rgb[2]),
    ];
  }, [item.estimated_rgb]);

  const [materialName, setMaterialName] = useState(item.material_name);
  const [brand, setBrand] = useState(item.brand?.trim() || "");
  const [color, setColor] = useState<[number, number, number]>(initialColor);
  const [colorHex, setColorHex] = useState<string>(toHex(initialColor));
  const [colorHexError, setColorHexError] = useState<string | null>(null);

  const handleColorPickerChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const parsed = parseHexColor(event.target.value);
    if (!parsed) {
      return;
    }
    setColor(parsed);
    setColorHex(toHex(parsed));
    setColorHexError(null);
  }, []);

  const handleColorHexChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const raw = event.target.value;
      setColorHex(raw);
      const parsed = parseHexColor(raw);
      if (parsed) {
        setColor(parsed);
        setColorHexError(null);
      } else if (raw.trim() === "") {
        setColorHexError(null);
      } else {
        setColorHexError(t("mat_gradient_library_edit_color_invalid_hex"));
      }
    },
    [t],
  );

  const handleSave = useCallback(() => {
    const trimmedName = materialName.trim();
    if (!trimmedName || colorHexError) {
      return;
    }
    onSave({
      materialName: trimmedName,
      brand: brand.trim() || null,
      estimatedRgb: [clampChannel(color[0]), clampChannel(color[1]), clampChannel(color[2])],
    });
  }, [brand, color, colorHexError, materialName, onSave]);

  return (
    <div
      data-testid="material-library-edit-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "var(--surface-scrim)" }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label={t("mat_gradient_library_edit_title")}
        className="relative flex w-full max-w-lg flex-col gap-4 overflow-hidden rounded-[28px] border p-4 shadow-2xl sm:p-5"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
      >
        <div>
          <div className="flex items-start justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
              {t("mat_gradient_library_edit_title")}
            </h3>
            <CloseButton label={t("common_close")} onClick={onCancel} disabled={pending} />
          </div>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {tRuntime("mat_gradient_library_edit_desc", {
              directoryName: item.directory_name,
            })}
          </p>
        </div>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_gradient_material_name_label")}
          </span>
          <input
            data-testid="material-library-edit-name-input"
            value={materialName}
            onChange={(event) => setMaterialName(event.target.value)}
            placeholder={t("mat_gradient_material_name_placeholder")}
            className={textInputClass}
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_gradient_brand_label")}
          </span>
          <input
            data-testid="material-library-edit-brand-input"
            value={brand}
            onChange={(event) => setBrand(event.target.value)}
            placeholder={t("mat_gradient_brand_placeholder")}
            className={textInputClass}
          />
        </label>

        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_gradient_library_edit_color_label")}
          </span>
          <div className="flex items-center gap-3">
            <input
              type="color"
              data-testid="material-library-edit-color-picker"
              value={toHex(color)}
              onChange={handleColorPickerChange}
              aria-label={t("mat_gradient_library_edit_color_label")}
              className={colorPickerInputClass}
            />
            <input
              type="text"
              data-testid="material-library-edit-color-hex-input"
              value={colorHex}
              onChange={handleColorHexChange}
              placeholder={t("mat_gradient_library_edit_color_hex_placeholder")}
              className={textInputClass}
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
            />
            <div
              data-testid="material-library-edit-color-swatch"
              aria-hidden="true"
              className="h-10 w-10 shrink-0 rounded-2xl border border-slate-200/80 dark:border-slate-700/80"
              style={{ backgroundColor: toRgbCss(color) }}
            />
          </div>
          {colorHexError ? (
            <p
              data-testid="material-library-edit-color-hex-error"
              className="text-xs font-medium text-rose-600 dark:text-rose-400"
            >
              {colorHexError}
            </p>
          ) : (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("mat_gradient_library_edit_color_hint")}
            </p>
          )}
        </div>

        <div className={`${mutedSectionCardClass} px-4 py-3`}>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            {t("mat_gradient_library_directory_label")}
          </p>
          <p className="mt-1 break-all text-sm font-semibold text-slate-900 dark:text-slate-50">
            {item.directory_name}
          </p>
        </div>

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button
            label={t("mat_gradient_library_edit_cancel_btn")}
            variant="secondary"
            onClick={onCancel}
            disabled={pending}
            className="w-full sm:w-auto"
          />
          <Button
            label={t("mat_gradient_library_edit_save_btn")}
            onClick={handleSave}
            disabled={!materialName.trim() || Boolean(colorHexError)}
            loading={pending}
            className="w-full sm:w-auto"
            variant="primary"
          />
        </div>
      </section>
    </div>
  );
}
